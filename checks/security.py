"""Helpers de seguridad compartidos por todos los checks.

Política: el alarm NUNCA debe filtrar
- URLs (ni en logs, ni en mensajes de error, ni en stack traces)
- valores de variables de entorno
- mensajes completos de excepciones de librerías externas
- contenido de responses HTTP
- nombres de host al fallar una conexión SSL
"""

from __future__ import annotations

import os
import socket
import ssl
import urllib.parse
from datetime import datetime, timezone
from typing import Final

import urllib3

# Suprime warnings tipo InsecureRequestWarning / SubjectAltNameWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ALLOWED_SCHEMES: Final = frozenset({"https"})

_MIN_SSL_DAYS: Final = 14


def is_configured(env_var: str) -> bool:
    """True si la variable existe y no está vacía."""
    return bool(os.environ.get(env_var, "").strip())


def validate_https_url(url: str) -> bool:
    """Devuelve True si la URL es HTTPS válida con hostname. No loguea nada."""
    if not url or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except (ValueError, AttributeError):
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    if not parsed.hostname:
        return False
    # Bloquear credenciales embebidas en la URL (https://user:pass@host/...)
    if parsed.username or parsed.password:
        return False
    return True


def safe_request(url: str, timeout: int) -> bool:
    """GET HTTPS sin redirects. True = hay problema.

    - Rechaza http://, IPs en claro, o URLs malformadas antes de tocar la red.
    - allow_redirects=False para no leakear a hosts inesperados.
    - Cualquier excepción (red, timeout, parseo) → True.
    - NUNCA se imprime la URL ni el mensaje de la excepción.
    """
    if not validate_https_url(url):
        return True
    import requests  # import local para no requerirlo si el check no se usa
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "alarm/1.0"},
        )
        return not (200 <= r.status_code < 300)
    except Exception:
        return True


def safe_get_json(url: str, timeout: int) -> dict | None:
    """GET HTTPS y devuelve el JSON. None = problema. Nunca se imprime la URL."""
    if not validate_https_url(url):
        return None
    import requests
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "alarm/1.0", "Accept": "application/json"},
        )
        if not (200 <= r.status_code < 300):
            return None
        return r.json()
    except Exception:
        return None


def safe_ssl_check(host: str) -> bool:
    """Conecta por TLS al host:443. True = hay problema.

    - Rechaza hosts vacíos.
    - NUNCA loguea el hostname ni el mensaje de error.
    """
    if not host or not host.strip():
        return False
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host.strip(), 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host.strip()) as ssock:
                cert = ssock.getpeercert()
        if not cert or "notAfter" not in cert:
            return True
        raw = cert["notAfter"]
        # OpenSSL usa doble espacio cuando el día es de 1 dígito
        parsed = None
        for fmt in ("%b %d  %H:%M:%S %Y %Z", "%b %d %H:%M:%S %Y %Z"):
            try:
                parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if parsed is None:
            return True
        days_left = (parsed - datetime.now(timezone.utc)).days
        return days_left < _MIN_SSL_DAYS
    except Exception:
        return True


def parse_iso_utc(date_str: str) -> datetime | None:
    """Parsea ISO 8601 con o sin timezone, devuelve datetime UTC. None = problema."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

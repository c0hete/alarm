"""Helpers de seguridad compartidos por todos los checks.

Política: el alarm NUNCA debe filtrar
- URLs (ni en logs, ni en mensajes de error, ni en stack traces)
- valores de variables de entorno
- mensajes completos de excepciones de librerías externas
- contenido de responses HTTP
- nombres de host al fallar una conexión SSL
"""

from __future__ import annotations

import ipaddress
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


# Redes bloqueadas por el check SSRF (default seguro).
# Incluye: privadas RFC1918, loopback, link-local (AWS metadata en 169.254.169.254),
# CGNAT, multicast, reserved, IPv6 equivalentes.
# Opt-out: ALLOW_PRIVATE_TARGETS=true
_PRIVATE_NETS: Final = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),       # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),         # loopback IPv4
    ipaddress.ip_network("169.254.0.0/16"),      # link-local + AWS metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),        # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),       # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),     # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),         # multicast
    ipaddress.ip_network("240.0.0.0/4"),         # reserved
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),             # loopback IPv6
    ipaddress.ip_network("::ffff:0:0/96"),       # IPv4-mapped
    ipaddress.ip_network("64:ff9b::/96"),        # IPv4-IPv6 translation
    ipaddress.ip_network("100::/64"),            # discard
    ipaddress.ip_network("2001::/32"),           # Teredo
    ipaddress.ip_network("2001:db8::/32"),       # documentation
    ipaddress.ip_network("fc00::/7"),            # unique local
    ipaddress.ip_network("fe80::/10"),           # link-local IPv6
    ipaddress.ip_network("ff00::/8"),            # multicast IPv6
]


def is_configured(env_var: str) -> bool:
    """True si la variable existe y no está vacía."""
    return bool(os.environ.get(env_var, "").strip())


def _ssrf_opted_out() -> bool:
    """True si el usuario explícitamente deshabilitó la protección SSRF.

    Opt-out via ALLOW_PRIVATE_TARGETS=true. Default: False (protegido).
    Acepta: 1, true, yes (case-insensitive).
    """
    val = os.environ.get("ALLOW_PRIVATE_TARGETS", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def is_private_ip(host: str) -> bool:
    """True si el host es una IP literal en una red bloqueada.

    Para hostnames (DNS), devuelve False — no hace resolución DNS. Eso evita
    side effects, pero deja un gap: un atacante que controle DNS puede
    bypasear el check (DNS rebinding). Para cerrar ese gap, correr el alarm
    en un entorno con DNS confiable y/o un egress proxy que filtre targets.
    """
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # es un hostname, no una IP literal
    return any(ip in net for net in _PRIVATE_NETS)


def is_safe_target(url_or_host: str) -> bool:
    """True si el target NO es una IP privada/bloqueada. Acepta URL o hostname.

    NO hace DNS lookup. Para hostnames, devuelve True (asume que el operador
    sabe lo que hace). Para IPs literales, evalúa contra las redes bloqueadas.

    Defense-in-depth contra SSRF, no garantía absoluta.
    """
    if not url_or_host:
        return False
    if "://" in url_or_host:
        try:
            parsed = urllib.parse.urlparse(url_or_host)
            host = parsed.hostname
        except (ValueError, AttributeError):
            return False
    else:
        host = url_or_host.strip()
    if not host:
        return False
    return not is_private_ip(host)


def _ssrf_check(url_or_host: str) -> bool:
    """Devuelve True si el target pasa el check SSRF.

    Si el usuario setea ALLOW_PRIVATE_TARGETS=true, devuelve True siempre
    (bypass explícito). Default: bloquea IPs privadas.
    """
    if _ssrf_opted_out():
        return True
    return is_safe_target(url_or_host)


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
    - Bloquea targets privados (IPs literales RFC1918, loopback, link-local,
      metadata AWS/GCP, etc.) salvo opt-out via ALLOW_PRIVATE_TARGETS=true.
    - Cualquier excepción (red, timeout, parseo) → True.
    - NUNCA se imprime la URL ni el mensaje de la excepción.
    """
    if not validate_https_url(url):
        return True
    if not _ssrf_check(url):
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
    if not _ssrf_check(url):
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
    - Bloquea IPs literales en redes privadas salvo opt-out.
    - NUNCA loguea el hostname ni el mensaje de error.
    """
    if not host or not host.strip():
        return False
    if not _ssrf_check(host):
        return True
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

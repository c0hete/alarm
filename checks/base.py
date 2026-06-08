"""Base check class and registry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


@dataclass
class Check:
    """Un check individual.

    bit_index: posición en el código binario (0 = LSB).
    name: nombre humano, solo se muestra en modo --verbose.
    run(): callable que devuelve True si hay problema, False si OK.
    """

    bit_index: int
    name: str
    run: Callable[[], bool]

    def execute(self) -> bool:
        try:
            return bool(self.run())
        except Exception:
            return True


def _filter_by_env(all_checks: list["Check"]) -> list["Check"]:
    """Filtra el registry según la env var CHECKS.

    Formato: lista separada por comas. Cada item puede ser:
    - Un número de bit (0-7): match exacto
    - Una palabra clave: match por substring (case-insensitive) contra el name

    Ejemplos:
        CHECKS=0,3                  # solo URL primaria + SSL primaria
        CHECKS=URL,SSL              # todos los URL y SSL
        CHECKS=backup               # solo el check de backup

    Si CHECKS no está seteada o está vacía, devuelve todos los checks sin filtrar.
    Si un item no matchea nada, se ignora silenciosamente.
    """
    selected = os.environ.get("CHECKS", "").strip()
    if not selected:
        return all_checks
    wanted: set[int] = set()
    for item in selected.split(","):
        item = item.strip()
        if not item:
            continue
        if item.isdigit():
            idx = int(item)
            if 0 <= idx <= 7:
                wanted.add(idx)
            continue
        # buscar por nombre
        for c in all_checks:
            if item.lower() in c.name.lower():
                wanted.add(c.bit_index)
    if not wanted:
        return all_checks
    return [c for c in all_checks if c.bit_index in wanted]


def build_registry(timeout: int) -> list[Check]:
    """Importa los módulos de checks perezosamente y arma la lista en orden de bit.

    Aplica el filtro de la env var CHECKS (si está seteada).
    """
    from . import http, ssl_cert, github_status, backup

    all_checks = [
        Check(0, f"URL primaria (timeout={timeout}s)", lambda: http.check_url("URL_PRIMARY", timeout)),
        Check(1, "URL secundaria", lambda: http.check_url("URL_SECONDARY", timeout)),
        Check(2, "URL terciaria", lambda: http.check_url("URL_TERTIARY", timeout)),
        Check(3, "SSL primaria (>=14d)", lambda: ssl_cert.check_ssl("SSL_PRIMARY")),
        Check(4, "SSL secundaria", lambda: ssl_cert.check_ssl("SSL_SECONDARY")),
        Check(5, "GitHub status API", github_status.check),
        Check(6, "Backup freshness", backup.check),
        Check(7, "Custom API", lambda: http.check_url("CUSTOM_API_URL", timeout)),
    ]
    return _filter_by_env(all_checks)

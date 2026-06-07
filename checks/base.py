"""Base check class and registry."""

from __future__ import annotations

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


def build_registry(timeout: int) -> list[Check]:
    """Importa los módulos de checks perezosamente y arma la lista en orden de bit."""
    from . import http, ssl_cert, github_status, backup

    return [
        Check(0, f"URL primaria (timeout={timeout}s)", lambda: http.check_url("URL_PRIMARY", timeout)),
        Check(1, "URL secundaria", lambda: http.check_url("URL_SECONDARY", timeout)),
        Check(2, "URL terciaria", lambda: http.check_url("URL_TERTIARY", timeout)),
        Check(3, "SSL primaria (>=14d)", lambda: ssl_cert.check_ssl("SSL_PRIMARY")),
        Check(4, "SSL secundaria", lambda: ssl_cert.check_ssl("SSL_SECONDARY")),
        Check(5, "GitHub status API", github_status.check),
        Check(6, "Backup freshness", backup.check),
        Check(7, "Custom API", lambda: http.check_url("CUSTOM_API_URL", timeout)),
    ]

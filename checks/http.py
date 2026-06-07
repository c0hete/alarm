"""HTTP health checks para slots 0, 1, 2 y 7. Delega en security.safe_request."""

from __future__ import annotations

from . import security


def check_url(env_var: str, timeout: int) -> bool:
    """True = problema. Vacío = slot deshabilitado (False)."""
    if not security.is_configured(env_var):
        return False
    return security.safe_request(  # type: ignore[arg-type]
        __import__("os").environ[env_var].strip(), timeout
    )

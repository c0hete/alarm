"""SSL cert expiry checks para slots 3 y 4. Delega en security.safe_ssl_check."""

from __future__ import annotations

from . import security


def check_ssl(env_var: str) -> bool:
    """True = problema. Vacío = slot deshabilitado (False)."""
    if not security.is_configured(env_var):
        return False
    import os
    return security.safe_ssl_check(os.environ[env_var])

"""GitHub status API check para slot 5. Delega en security.safe_get_json."""

from __future__ import annotations

from . import security

URL = "https://www.githubstatus.com/api/v2/status.json"


def check() -> bool:
    """True = problema. indicator != 'none' cuenta como problema."""
    data = security.safe_get_json(URL, timeout=10)
    if data is None:
        return True
    indicator = data.get("status", {}).get("indicator", "unknown")
    return indicator != "none"

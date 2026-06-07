"""Backup freshness check para slot 6."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from . import security

_DEFAULT_MAX_AGE_DAYS = 2


def check() -> bool:
    """True = problema. Lee BACKUP_MANIFEST (HTTPS JSON con 'date' o 'last_backup')."""
    if not security.is_configured("BACKUP_MANIFEST"):
        return False
    url = os.environ["BACKUP_MANIFEST"].strip()
    data = security.safe_get_json(url, timeout=10)
    if data is None:
        return True
    date_str = data.get("date") or data.get("last_backup")
    last = security.parse_iso_utc(date_str) if isinstance(date_str, str) else None
    if last is None:
        return True
    try:
        max_age = int(os.environ.get("BACKUP_MAX_AGE_DAYS", str(_DEFAULT_MAX_AGE_DAYS)))
    except ValueError:
        max_age = _DEFAULT_MAX_AGE_DAYS
    age_days = (datetime.now(timezone.utc) - last).days
    return age_days > max_age

"""Stable fingerprint for issue idempotency / dedupe."""

from __future__ import annotations

import hashlib

LABEL = "cro-advisor"


def fingerprint(opportunity_label: str) -> str:
    """Deterministic id for an opportunity, used as a hidden marker in the issue
    body and as the dedupe key against already-open issues."""
    digest = hashlib.sha1(opportunity_label.encode()).hexdigest()[:12]
    return f"cro-{digest}"

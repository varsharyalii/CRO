"""Phase 3 — Slack digest of the weekly top opportunities (read-only output).

Posts to an incoming-webhook URL if configured; otherwise the digest is just
printed (safe no-op), so the autonomous run never hard-fails on a missing webhook.
"""

from __future__ import annotations

import httpx

from ..config import settings


class SlackClient:
    def __init__(self) -> None:
        self.webhook_url = settings.slack_webhook_url

    def post(self, text: str) -> bool:
        """Returns True if posted to Slack, False if no webhook is configured."""
        if not self.webhook_url:
            print("[slack: no webhook configured — digest below]\n" + text)
            return False
        resp = httpx.post(self.webhook_url, json={"text": text}, timeout=30)
        resp.raise_for_status()
        return True

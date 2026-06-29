"""Phase 3 — durable metric snapshots for week-over-week regression detection.

Each run appends a timestamped MetricsBundle snapshot under HISTORY_DIR. The
weekly run loads the most recent *prior* snapshot to diff against. JSON files
(one per run) keep this trivially inspectable and testable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schemas import MetricsBundle

_STAMP_FMT = "%Y%m%dT%H%M%SZ"


def save_snapshot(metrics: MetricsBundle, history_dir: str | Path, when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc)
    root = Path(history_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"metrics-{when.strftime(_STAMP_FMT)}.json"
    path.write_text(metrics.model_dump_json(indent=2))
    return path


def _snapshots(history_dir: str | Path) -> list[Path]:
    root = Path(history_dir)
    if not root.exists():
        return []
    return sorted(root.glob("metrics-*.json"))


def load_previous(history_dir: str | Path, before: Path | None = None) -> MetricsBundle | None:
    """Most recent snapshot strictly older than `before` (or the latest if None)."""
    snaps = _snapshots(history_dir)
    if before is not None:
        snaps = [s for s in snaps if s.name < before.name]
    if not snaps:
        return None
    return MetricsBundle.model_validate_json(snaps[-1].read_text())

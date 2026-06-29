"""Grounding validator: reject hallucinated data and nonexistent file paths."""

from __future__ import annotations

import os
from pathlib import Path

from ..schemas import MetricsBundle, Recommendation


class GroundingError(Exception):
    """Raised when a recommendation fails grounding checks."""


def _close(a: float, b: float, rel: float = 0.02, abs_: float = 0.5) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def validate_recommendation(
    rec: Recommendation,
    metrics: MetricsBundle,
    repo_root: str | os.PathLike[str],
) -> None:
    """Raise GroundingError if any cited metric is not in the ingested data
    or any referenced file path does not exist in the repo."""
    known = metrics.known_numbers()

    for ev in rec.evidence:
        if not any(_close(ev.value, k) for k in known):
            raise GroundingError(
                f"Fabricated metric: '{ev.metric_name}'={ev.value} not present in ingested data"
            )

    root = Path(repo_root)
    for rel in rec.target_files:
        if not (root / rel).exists():
            raise GroundingError(f"Referenced file does not exist in repo: {rel}")

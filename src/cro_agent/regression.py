"""Phase 3 — week-over-week regression detection.

Compares the current funnel/liquidity drop-offs against the previous snapshot and
surfaces steps that newly WORSENED, so the weekly run can prioritize them. Pure
functions over MetricsBundles (the scoring already computes per-label drop-offs),
so this is fully unit-testable.
"""

from __future__ import annotations

from pydantic import BaseModel

from .schemas import MetricsBundle, Opportunity
from .scoring import score_buyer_funnel, score_liquidity


class Regression(BaseModel):
    label: str
    kind: str
    previous_dropoff: float
    current_dropoff: float
    delta: float  # positive == got worse


def _by_label(metrics: MetricsBundle) -> dict[str, Opportunity]:
    return {o.label: o for o in (score_buyer_funnel(metrics) + score_liquidity(metrics))}


def detect_regressions(
    current: MetricsBundle, previous: MetricsBundle, threshold: float
) -> list[Regression]:
    """Labels whose drop-off (buyer) or gap (liquidity) rose by >= threshold."""
    cur = _by_label(current)
    prev = _by_label(previous)
    out: list[Regression] = []
    for label, c in cur.items():
        p = prev.get(label)
        if p is None:
            continue
        delta = c.dropoff_rate - p.dropoff_rate
        if delta >= threshold:
            out.append(
                Regression(
                    label=label,
                    kind=c.kind,
                    previous_dropoff=p.dropoff_rate,
                    current_dropoff=c.dropoff_rate,
                    delta=round(delta, 4),
                )
            )
    return sorted(out, key=lambda r: r.delta, reverse=True)


def boost_regressed(
    opportunities: list[Opportunity], regressions: list[Regression], boost: float = 2.0
) -> list[Opportunity]:
    """Re-rank: multiply the score of any regressed opportunity so newly-worsened
    steps float to the top of the weekly backlog. Returns a new sorted list."""
    regressed = {r.label for r in regressions}
    out: list[Opportunity] = []
    for o in opportunities:
        score = o.score * boost if o.label in regressed else o.score
        out.append(o.model_copy(update={"score": round(score, 2)}))
    return sorted(out, key=lambda o: o.score, reverse=True)

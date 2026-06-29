"""Phase 3 — auto-prioritized backlog + Slack digest rendering (pure)."""

from __future__ import annotations

from .regression import Regression
from .schemas import Opportunity


def render_backlog(opportunities: list[Opportunity]) -> str:
    """Full ranked backlog of every scored opportunity (markdown)."""
    lines = ["# CRO/Liquidity backlog (auto-prioritized)", ""]
    for i, o in enumerate(opportunities, 1):
        where = f" — worst: {o.segment}" if o.segment else ""
        lines.append(
            f"{i}. **{o.label}** ({o.kind}) — score {o.score}, "
            f"dropoff {o.dropoff_rate}, n={o.sample_size}{where}"
        )
    return "\n".join(lines)


def render_digest(
    opportunities: list[Opportunity], regressions: list[Regression], window_days: int, top: int = 5
) -> str:
    """Short Slack digest: regressions first, then the top opportunities."""
    parts = [f":bar_chart: *CRO & Liquidity weekly digest* (last {window_days}d)"]

    if regressions:
        parts.append("\n:rotating_light: *Newly worsened (vs last week)*")
        for r in regressions[:top]:
            parts.append(
                f"• `{r.label}` dropoff {r.previous_dropoff:.0%} → {r.current_dropoff:.0%} "
                f"(+{r.delta:.0%})"
            )
    else:
        parts.append("\n:white_check_mark: No regressions vs last week.")

    parts.append("\n:dart: *Top opportunities*")
    for o in opportunities[:top]:
        where = f" — worst: {o.segment}" if o.segment else ""
        parts.append(f"• `{o.label}` — score {o.score} (dropoff {o.dropoff_rate}){where}")

    return "\n".join(parts)

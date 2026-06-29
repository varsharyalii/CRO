"""Deterministic opportunity scoring and prioritization (NOT LLM)."""

from __future__ import annotations

from .schemas import LiquidityMetric, MetricsBundle, Opportunity

# liquidity metrics where a LOWER value is worse (gap = 1 - value)
_GAP_METRICS = {"sell_through", "claim_to_paid", "seller_activation"}
# liquidity metrics where a HIGHER value is worse (the rate itself is the loss)
_RATE_METRICS = {"expired_claim_rate"}

# The forward marketplace_view -> drop_view edge is NOT a leak: most users
# deep-link to a drop from Instagram without visiting the marketplace first, so
# drop_view > marketplace_view is expected (an entry-point split). The REVERSE
# direction is the real, high-priority opportunity (see below).
_EXCLUDED_FUNNEL_EDGES = {"marketplace_view->drop_view"}

# Cross-sell exploration leak: drop-landers who never reach the marketplace feed
# and therefore never discover OTHER sellers. Converting Instagram drop-landers
# into marketplace explorers is a stated liquidity goal, so this is scored as a
# first-class buyer-funnel opportunity (lost = drop_landers - explorers).
_EXPLORATION_FROM = "drop_view"
_EXPLORATION_TO = "marketplace_view"


def _edge_opportunity(from_name: str, to_name: str, up_vol: int, down_vol: int) -> Opportunity:
    dropoff = max(0.0, 1.0 - down_vol / up_vol)
    return Opportunity(
        kind="buyer_funnel",
        label=f"{from_name}->{to_name}",
        from_step=from_name,
        to_step=to_name,
        dropoff_rate=round(dropoff, 4),
        upstream_volume=up_vol,
        sample_size=up_vol,
        score=round(dropoff * up_vol, 2),
    )


def score_buyer_funnel(metrics: MetricsBundle) -> list[Opportunity]:
    """Per step: lost = dropoff_rate × upstream_volume."""
    out: list[Opportunity] = []
    steps = metrics.buyer_funnel
    for upstream, downstream in zip(steps, steps[1:]):
        if upstream.volume <= 0:
            continue
        if f"{upstream.name}->{downstream.name}" in _EXCLUDED_FUNNEL_EDGES:
            continue
        out.append(
            _edge_opportunity(upstream.name, downstream.name, upstream.volume, downstream.volume)
        )

    # Cross-sell exploration leak (drop_view -> marketplace_view), scored as a
    # first-class buyer-funnel opportunity regardless of step adjacency.
    by_name = {s.name: s.volume for s in steps}
    up = by_name.get(_EXPLORATION_FROM, 0)
    down = by_name.get(_EXPLORATION_TO, 0)
    if up > 0:
        out.append(_edge_opportunity(_EXPLORATION_FROM, _EXPLORATION_TO, up, down))

    return out


def _liquidity_gap(m: LiquidityMetric) -> float:
    if m.name in _RATE_METRICS:
        return m.value
    if m.name in _GAP_METRICS:
        return max(0.0, 1.0 - m.value)
    return 0.0


def score_liquidity(metrics: MetricsBundle) -> list[Opportunity]:
    out: list[Opportunity] = []
    for m in metrics.liquidity_metrics:
        gap = _liquidity_gap(m)
        out.append(
            Opportunity(
                kind="liquidity",
                label=f"liquidity:{m.name}",
                dropoff_rate=round(gap, 4),
                upstream_volume=m.sample_size,
                sample_size=m.sample_size,
                score=round(gap * m.sample_size, 2),
            )
        )
    return out


def rank_opportunities(
    metrics: MetricsBundle, min_sample_size: int
) -> list[Opportunity]:
    """Score both sides, drop below-sample noise, sort by score desc."""
    opps = score_buyer_funnel(metrics) + score_liquidity(metrics)
    opps = [o for o in opps if o.sample_size >= min_sample_size]
    return sorted(opps, key=lambda o: o.score, reverse=True)

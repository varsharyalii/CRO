"""Phase 3 — regression detection, history round-trip, backlog/digest, cost cap."""

from __future__ import annotations

from cro_agent.backlog import render_digest
from cro_agent.history import load_previous, save_snapshot
from cro_agent.regression import boost_regressed, detect_regressions
from cro_agent.schemas import FunnelStep, LiquidityMetric, MetricsBundle
from cro_agent.scoring import rank_opportunities


def _bundle(item_view: int, claim: int) -> MetricsBundle:
    return MetricsBundle(
        window_days=7,
        buyer_funnel=[
            FunnelStep(name="item_view", event="jz_item_view", volume=item_view),
            FunnelStep(name="claim_attempt", event="jz_claim_attempt", volume=claim),
        ],
        liquidity_metrics=[LiquidityMetric(name="claim_to_paid", value=0.9, sample_size=200)],
    )


def test_detects_worsened_step():
    last_week = _bundle(1000, 500)  # dropoff 0.50
    this_week = _bundle(1000, 300)  # dropoff 0.70 → +0.20
    regs = detect_regressions(this_week, last_week, threshold=0.05)
    labels = {r.label: r for r in regs}
    assert "item_view->claim_attempt" in labels
    assert labels["item_view->claim_attempt"].delta == 0.2


def test_no_regression_when_improved():
    last_week = _bundle(1000, 300)  # 0.70
    this_week = _bundle(1000, 500)  # 0.50 (improved)
    assert detect_regressions(this_week, last_week, threshold=0.05) == []


def test_boost_floats_regressed_to_top():
    metrics = _bundle(1000, 300)
    opps = rank_opportunities(metrics, min_sample_size=100)
    regs = detect_regressions(metrics, _bundle(1000, 500), threshold=0.05)
    boosted = boost_regressed(opps, regs, boost=2.0)
    # the regressed edge is now first
    assert boosted[0].label == "item_view->claim_attempt"


def test_history_round_trip(tmp_path):
    save_snapshot(_bundle(1000, 500), tmp_path)
    save_snapshot(_bundle(1000, 300), tmp_path)
    prev = load_previous(tmp_path)  # latest snapshot
    assert prev is not None
    assert prev.buyer_funnel[1].volume == 300


def test_load_previous_empty(tmp_path):
    assert load_previous(tmp_path) is None


def test_digest_lists_regressions():
    metrics = _bundle(1000, 300)
    opps = rank_opportunities(metrics, 100)
    regs = detect_regressions(metrics, _bundle(1000, 500), 0.05)
    text = render_digest(opps, regs, window_days=7)
    assert "Newly worsened" in text and "item_view->claim_attempt" in text

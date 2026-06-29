"""Phase 1 — the segment node breaks top buyer leaks by cohort and folds the
stats into the metrics bundle (so they're citable + grounded)."""

from __future__ import annotations

import cro_agent.graph as graph_mod
from cro_agent.graph import SEGMENT_DIMENSION, node_segment
from cro_agent.schemas import FunnelStep, MetricsBundle, Opportunity
from cro_agent.state import AgentState


class _FakeClient:
    def segment_edge(self, from_step, to_step, dimension, window_days, top_n=4):
        # ended drops convert worst; a tiny scheduled cohort is below the floor
        return [
            ("live", 0.78, 679),
            ("ended", 0.94, 270),
            ("scheduled", 1.0, 1),
        ]


def _state() -> AgentState:
    metrics = MetricsBundle(
        window_days=14,
        buyer_funnel=[
            FunnelStep(name="item_view", event="jz_item_view", volume=915),
            FunnelStep(name="claim_attempt", event="jz_claim_attempt", volume=150),
        ],
    )
    opp = Opportunity(
        kind="buyer_funnel",
        label="item_view->claim_attempt",
        from_step="item_view",
        to_step="claim_attempt",
        dropoff_rate=0.836,
        upstream_volume=915,
        sample_size=915,
        score=765.0,
    )
    return AgentState(metrics=metrics, opportunities=[opp])


def test_segment_picks_worst_cohort_above_floor(monkeypatch):
    import cro_agent.clients.posthog as ph_mod

    monkeypatch.setattr(ph_mod, "PostHogClient", _FakeClient)  # patched at import source
    monkeypatch.setattr(graph_mod.settings, "fixture_path", "", raising=False)

    out = node_segment(_state())

    # worst eligible cohort is 'ended' (0.94); 'scheduled' (n=1) is below floor
    assert out["opportunities"][0].segment == f"{SEGMENT_DIMENSION}=ended"
    # all three stats folded into the bundle and citable as grounded numbers
    segs = out["metrics"].segments
    assert len(segs) == 3
    known = out["metrics"].known_numbers()
    assert 0.94 in known and 270.0 in known


def test_segment_skipped_in_fixture_mode(monkeypatch):
    monkeypatch.setattr(graph_mod.settings, "fixture_path", "data/fixtures/sample_metrics.json")
    assert node_segment(_state()) == {}

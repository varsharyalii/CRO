"""LangGraph StateGraph wiring the advisor pipeline.

ingest_metrics → detect_opportunities → segment → map_to_surface
  → recommend → guardrails → human_approval → emit_issues
"""

from __future__ import annotations

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .config import settings
from .harness.grounding import GroundingError, validate_recommendation
from .nodes.recommend import recommend
from .schemas import SegmentStat
from .scoring import rank_opportunities
from .state import AgentState

# Top N per the MVP cut: 3 buyer-funnel leaks + 2 liquidity leaks.
TOP_BUYER = 3
TOP_LIQUIDITY = 2


def node_ingest_metrics(state: AgentState) -> dict:
    from .clients.posthog import PostHogClient, load_fixture

    if settings.fixture_path:
        metrics = load_fixture(settings.fixture_path)
        note = f"ingested metrics from fixture {settings.fixture_path}"
    else:
        metrics = PostHogClient().ingest(settings.analysis_window_days)
        note = "ingested metrics from PostHog"
    return {"metrics": metrics, "notes": [*state.notes, note]}


def node_detect_opportunities(state: AgentState) -> dict:
    assert state.metrics is not None
    ranked = rank_opportunities(state.metrics, settings.min_sample_size)
    buyer = [o for o in ranked if o.kind == "buyer_funnel"][:TOP_BUYER]
    liquidity = [o for o in ranked if o.kind == "liquidity"][:TOP_LIQUIDITY]
    selected = sorted(buyer + liquidity, key=lambda o: o.score, reverse=True)
    return {"opportunities": selected, "notes": [*state.notes, f"selected {len(selected)} opps"]}


# Cohort dimension to break the top leaks by. drop_status (live/scheduled/ended)
# is present on ~100% of funnel events and is the most actionable cohort.
SEGMENT_DIMENSION = "drop_status"
# Don't trust a segment's drop-off below this many upstream persons (noise).
SEGMENT_MIN_VOLUME = 30


def node_segment(state: AgentState) -> dict:
    """Phase 1: break the selected buyer-funnel leaks by cohort so each
    recommendation can say WHERE the leak is worst. Read-only PostHog breakdowns.
    Skipped in fixture mode (offline) since there is no live client."""
    if settings.fixture_path or state.metrics is None:
        return {}

    from .clients.posthog import PostHogClient

    client = PostHogClient()
    segments: list[SegmentStat] = []
    opps = list(state.opportunities)

    for opp in opps:
        if opp.kind != "buyer_funnel" or not opp.from_step or not opp.to_step:
            continue
        rows = client.segment_edge(
            opp.from_step, opp.to_step, SEGMENT_DIMENSION, settings.analysis_window_days
        )
        worst: tuple[str, float, int] | None = None
        for seg_value, dropoff, up in rows:
            segments.append(
                SegmentStat(
                    opportunity_label=opp.label,
                    dimension=SEGMENT_DIMENSION,
                    segment_value=seg_value,
                    dropoff_rate=dropoff,
                    upstream_volume=up,
                )
            )
            if up >= SEGMENT_MIN_VOLUME and (worst is None or dropoff > worst[1]):
                worst = (seg_value, dropoff, up)
        if worst is not None:
            opp.segment = f"{SEGMENT_DIMENSION}={worst[0]}"

    # Fold segment stats into the metrics bundle so the grounding harness accepts
    # cited segment numbers and the recommend prompt can see them.
    metrics = state.metrics.model_copy(update={"segments": segments})
    return {
        "metrics": metrics,
        "opportunities": opps,
        "notes": [*state.notes, f"segmented {len(opps)} opps into {len(segments)} cohort stats"],
    }


def node_recommend(state: AgentState) -> dict:
    assert state.metrics is not None
    repo = settings.jhaazi_frontend_path
    recs = []
    calls = state.llm_calls
    notes = list(state.notes)
    for opp in state.opportunities:
        # Cost cap (Phase 3): protect autonomous cron runs from running away.
        if calls >= settings.max_llm_calls:
            notes.append(f"stopped at max_llm_calls={settings.max_llm_calls}")
            break
        if (calls + 1) * settings.usd_per_llm_call > settings.max_run_cost_usd:
            notes.append(f"stopped at max_run_cost_usd=${settings.max_run_cost_usd}")
            break
        rec = recommend(opp, state.metrics, repo)
        calls += 1
        recs.append(rec)
    return {"recommendations": recs, "llm_calls": calls, "notes": notes}


def node_guardrails(state: AgentState) -> dict:
    assert state.metrics is not None
    repo = settings.jhaazi_frontend_path
    kept = []
    notes = list(state.notes)
    for rec in state.recommendations:
        try:
            validate_recommendation(rec, state.metrics, repo)
            kept.append(rec)
        except GroundingError as e:
            notes.append(f"dropped recommendation '{rec.title}': {e}")
    return {"recommendations": kept, "notes": notes}


def node_human_approval(state: AgentState) -> dict:
    if state.dry_run:
        return {"approved": False, "notes": [*state.notes, "dry-run: stopped before emit"]}
    decision = interrupt({"recommendations": [r.model_dump() for r in state.recommendations]})
    return {"approved": bool(decision)}


def node_emit_issues(state: AgentState) -> dict:
    if state.dry_run or not state.approved:
        return {}
    from .clients.github import GitHubClient

    gh = GitHubClient()
    already = gh.open_fingerprints()
    urls = []
    for rec in state.recommendations:
        if rec.fingerprint in already:
            continue
        urls.append(gh.create_issue(rec))
    return {"emitted_issue_urls": urls}


def build_graph(checkpointer: SqliteSaver | None = None):
    g = StateGraph(AgentState)
    g.add_node("ingest_metrics", node_ingest_metrics)
    g.add_node("detect_opportunities", node_detect_opportunities)
    g.add_node("segment", node_segment)
    g.add_node("recommend", node_recommend)
    g.add_node("guardrails", node_guardrails)
    g.add_node("human_approval", node_human_approval)
    g.add_node("emit_issues", node_emit_issues)

    g.add_edge(START, "ingest_metrics")
    g.add_edge("ingest_metrics", "detect_opportunities")
    g.add_edge("detect_opportunities", "segment")
    g.add_edge("segment", "recommend")
    g.add_edge("recommend", "guardrails")
    g.add_edge("guardrails", "human_approval")
    g.add_edge("human_approval", "emit_issues")
    g.add_edge("emit_issues", END)

    return g.compile(checkpointer=checkpointer)

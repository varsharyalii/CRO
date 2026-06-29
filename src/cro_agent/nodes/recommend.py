"""recommend node — LLM with structured output, one Recommendation per opportunity."""

from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..harness.fingerprint import fingerprint
from ..schemas import MetricsBundle, Opportunity, Recommendation
from ..surface_map import surface_for

_SYSTEM = """You are a CRO & marketplace-liquidity analyst for Jhaazi, a live-drop fashion marketplace.
You produce ONE grounded optimization recommendation for a single funnel/liquidity opportunity.

Hard rules:
- Every number in `evidence` MUST be a value from the provided metrics. Never invent statistics.
- `target_files` MUST be chosen from the candidate files provided. Do not invent paths.
- Be concrete: name the UI/UX change and a runnable experiment (variant, goal metric, min sample).
- Fill `experiment` with a handoff-ready PostHog Experiment spec: a kebab-case
  `feature_flag_key`, a one-line `hypothesis`, and `goal_event` set to the
  PostHog event (a `jz_*` name from the funnel) whose conversion the change
  should move. Pick `minimum_sample_per_variant` from the upstream volume."""


def _read_snippet(repo_root: str, rel: str, limit: int = 4000) -> str:
    p = Path(repo_root) / rel
    if not p.exists():
        return f"[missing: {rel}]"
    return p.read_text(errors="replace")[:limit]


def _segment_context(opp: Opportunity, metrics: MetricsBundle) -> str:
    """Cohort breakdown for this opportunity, so the rec can say WHERE it's worst."""
    rows = [s for s in metrics.segments if s.opportunity_label == opp.label]
    if not rows:
        return ""
    lines = "\n".join(
        f"- {s.dimension}={s.segment_value}: dropoff {s.dropoff_rate} over {s.upstream_volume} users"
        for s in rows
    )
    worst = f" Worst cohort: {opp.segment}." if opp.segment else ""
    return (
        f"\nCohort breakdown (state WHERE the leak is worst; these numbers are also "
        f"citable as evidence):{worst}\n{lines}\n"
    )


def _prior_context(opp: Opportunity) -> str:
    """Phase 4: cite the learned prior over what kinds of changes have moved
    metrics before, so generation is informed by past experiment outcomes."""
    from ..learning import change_kind, load_prior

    hint = load_prior(settings.history_dir).hint_for(change_kind(opp.label))
    return f"\nLearned prior (from past shipped experiments): {hint}\n" if hint else ""


def build_prompt(opp: Opportunity, metrics: MetricsBundle, repo_root: str) -> str:
    surface = surface_for(opp.label)
    files_ctx = "\n\n".join(
        f"### {rel}\n```\n{_read_snippet(repo_root, rel)}\n```" for rel in surface.files
    )
    return f"""Opportunity: {opp.label}
kind={opp.kind} dropoff_rate={opp.dropoff_rate} upstream_volume={opp.upstream_volume} score={opp.score}

Surface note: {surface.note}
{_segment_context(opp, metrics)}{_prior_context(opp)}
Ingested metrics (the ONLY numbers you may cite):
{metrics.model_dump_json(indent=2)}

Candidate files (choose target_files from these only):
{files_ctx}
"""


def _build_llm():
    """Construct the structured-output LLM for the configured provider.

    Imported lazily so tests / fixture dry-runs don't require an API key or the
    provider package to be installed."""
    provider = settings.llm_provider.lower()
    if provider == "groq":
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            model=settings.cro_agent_model,
            api_key=settings.groq_api_key,
            max_tokens=2000,
            temperature=0,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=settings.cro_agent_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2000,
        )
    else:
        raise ValueError(f"Unknown llm_provider: {settings.llm_provider}")

    return llm.with_structured_output(Recommendation)


def recommend(opp: Opportunity, metrics: MetricsBundle, repo_root: str) -> Recommendation:
    """Call the LLM for a structured Recommendation."""
    llm = _build_llm()
    rec: Recommendation = llm.invoke(
        [("system", _SYSTEM), ("human", build_prompt(opp, metrics, repo_root))]
    )
    rec.fingerprint = fingerprint(opp.label)
    return rec

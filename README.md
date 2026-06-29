# CRO & Liquidity Optimization Advisor Agent

A read-only LLM advisor agent that analyzes Jhaazi's PostHog funnel data and emits
grounded, codebase-aware optimization suggestions as GitHub issues (behind a
human-approval gate).

**This is an advisor, not a mutator.** It is read-only against PostHog, the repo, and
seller data. Its only write is opening GitHub issues. See [PLAN.md](PLAN.md) for full design.

## What it does

A LangGraph `StateGraph` walks:

```
ingest_metrics → detect_opportunities → segment → map_to_surface
  → recommend → guardrails → human_approval → emit_issues
```

- **ingest_metrics** — PostHog Query API (HogQL): buyer funnel + seller-liquidity metrics.
- **detect_opportunities** — deterministic scoring (`lost = dropoff_rate × upstream_volume`).
- **segment** — break top leaks by cohort.
- **map_to_surface** — hand-authored funnel-step → component/file map (codebase-aware).
- **recommend** — LLM, structured output: leak, evidence, root cause, proposed change, experiment design.
- **guardrails** — grounding validator, sample-size gate, dedupe.
- **human_approval** — LangGraph `interrupt()` before any issue opens.
- **emit_issues** — idempotent GitHub issue creation.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install langchain-groq        # default LLM provider
cp .env.example .env              # fill in keys (see below)
```

Required `.env` values:

| Var | Purpose |
|---|---|
| `POSTHOG_HOST` / `POSTHOG_PROJECT_ID` | US production project (e.g. `https://us.posthog.com`, `447081`) |
| `POSTHOG_PERSONAL_API_KEY` | **Personal** API key (`phx_…`) with `query:read` — NOT the `phc_` project token |
| `LLM_PROVIDER` / `CRO_AGENT_MODEL` | `groq` + `llama-3.3-70b-versatile` (or `anthropic` + a Claude model) |
| `GROQ_API_KEY` *or* `ANTHROPIC_API_KEY` | LLM key for the chosen provider |
| `GITHUB_TOKEN` / `GITHUB_REPO` | fine-grained token with **Issues: Read and write**; `owner/repo` |
| `JHAAZI_FRONTEND_PATH` | local checkout of `jhaazi-frontend` (for grounding file paths) |

## Run

```bash
# inspect the live metrics the agent ingests (no LLM, no writes)
python -m cro_agent.run --print-metrics

# dry-run: ingest → score → recommend → grounding → stop at approval, write nothing
python -m cro_agent.run --dry-run

# real run: prompts for terminal approval, then opens idempotent GitHub issues
python -m cro_agent.run

# offline (no PostHog creds) — ingest from a fixture
python -m cro_agent.run --dry-run --fixture data/fixtures/sample_metrics.json

# Phase 2 — measure whether shipped experiments moved their goal, annotate issues
python -m cro_agent.run --attribute

# Phase 3 — manual "weekly" run: snapshot, regression-diff vs last snapshot,
#           prioritized backlog (data/history/backlog.md), Slack digest
python -m cro_agent.run --weekly
```

## Test

```bash
pytest          # 31 tests: scoring, grounding, surface map, dedupe,
                #            segmentation, attribution, regression, learning
```

## Capabilities by phase

- **Phase 0 (MVP)** — live HogQL buyer funnel + liquidity metrics, deterministic scoring, codebase-grounded recommendations, human-gated idempotent GitHub issues.
- **Phase 1** — `segment` node breaks top leaks by `drop_status` cohort via PostHog `FunnelsQuery`; recs say *where* a leak is worst.
- **Phase 2** — handoff-ready PostHog `ExperimentSpec` per rec; `--attribute` measures goal movement and comments on the issue.
- **Phase 3** — `--weekly` regression detection (vs snapshot history), auto-prioritized backlog, Slack digest, per-run cost cap.
- **Phase 4** — durable learned prior over which *kinds* of changes move metrics, fed back into the recommend prompt.

> Jhaazi note: `drop_view` is a primary entry point (Instagram deep-links), so
> `drop_view → marketplace_view` (converting drop-landers into marketplace
> explorers) is scored as the top cross-sell opportunity, not a defect.

## Safety properties

- Read-only PostHog personal API key (queries only).
- Repo read locally; GitHub token scoped to `issues:write`.
- Every cited metric must trace to ingested data; every file path must exist.
- Sample-size / confidence gate — never recommend off noise.
- Human-in-the-loop `interrupt()` before emitting.
- Durable state (`SqliteSaver`) + append-only audit log; cost/rate caps.

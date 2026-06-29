"""CLI entrypoint.

  python -m cro_agent.run --print-metrics   # ingest, dump MetricsBundle JSON, exit
  python -m cro_agent.run --dry-run         # ingest, recommend, stop at approval, write nothing
  python -m cro_agent.run                   # prompts for terminal approval before opening issues

Add --fixture data/fixtures/sample_metrics.json to any command to ingest offline
(no PostHog credentials required).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from .graph import build_graph
from .state import AgentState

DB_PATH = Path("data/checkpoints/cro-agent.sqlite")


def _print_metrics() -> None:
    """Ingest and dump the MetricsBundle as JSON for manual eyeballing vs PostHog."""
    from .clients.posthog import PostHogClient, load_fixture
    from .config import settings

    if settings.fixture_path:
        bundle = load_fixture(settings.fixture_path)
    else:
        bundle = PostHogClient().ingest(settings.analysis_window_days)
    print(bundle.model_dump_json(indent=2))


def _run_attribution() -> None:
    """Phase 2: regenerate recommendations (to recover their experiment specs),
    then measure goal-metric movement per experiment and comment on the issues."""
    from .attribution import run_attribution
    from .clients.github import GitHubClient
    from .clients.posthog import PostHogClient
    from .config import settings

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(DB_PATH)) as saver:
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": "cro-attribution"}}
        result = graph.invoke(AgentState(dry_run=True), config)
        recs = AgentState.model_validate(result).recommendations

    specs = [(r.fingerprint, r.experiment) for r in recs if r.experiment]
    if not specs:
        print("No recommendations carry an experiment spec — nothing to attribute.")
        return

    results = run_attribution(
        PostHogClient(),
        GitHubClient(),
        specs,
        settings.analysis_window_days,
        history_dir=settings.history_dir,  # Phase 4: learn from outcomes
    )
    for fingerprint, res, url in results:
        loc = f" → commented {url}" if url else " (no matching issue)"
        print(f"[{fingerprint}] {res.note}{loc}")


def _run_weekly() -> None:
    """Phase 3: autonomous weekly run. Read-only except the Slack digest.

    Ingest → snapshot → regression diff vs last week → prioritized backlog →
    Slack digest. Issue emission still requires a human-approved non-dry run."""
    from .backlog import render_backlog, render_digest
    from .clients.posthog import PostHogClient, load_fixture
    from .clients.slack import SlackClient
    from .config import settings
    from .history import load_previous, save_snapshot
    from .regression import boost_regressed, detect_regressions
    from .scoring import rank_opportunities

    metrics = (
        load_fixture(settings.fixture_path)
        if settings.fixture_path
        else PostHogClient().ingest(settings.analysis_window_days)
    )

    previous = load_previous(settings.history_dir)  # most recent prior snapshot
    save_snapshot(metrics, settings.history_dir)

    opportunities = rank_opportunities(metrics, settings.min_sample_size)
    regressions = (
        detect_regressions(metrics, previous, settings.regression_threshold)
        if previous
        else []
    )
    if previous is None:
        print("No prior snapshot — saved this run as the week-1 baseline.")
    opportunities = boost_regressed(opportunities, regressions)

    backlog_path = Path(settings.history_dir) / "backlog.md"
    backlog_path.write_text(render_backlog(opportunities))
    print(f"Backlog written: {backlog_path}  ({len(opportunities)} opportunities)")

    digest = render_digest(opportunities, regressions, metrics.window_days)
    posted = SlackClient().post(digest)
    print(f"Slack digest {'posted' if posted else 'printed (no webhook)'}; "
          f"{len(regressions)} regression(s) detected.")


def _print_recommendations(recs: list) -> None:
    if not recs:
        print("\nNo grounded recommendations passed the harness.")
        return
    print(f"\n=== {len(recs)} recommendation(s) ===")
    for i, rec in enumerate(recs, 1):
        print(f"\n[{i}] {rec.title}  (effort {rec.effort})")
        print(f"    files: {', '.join(rec.target_files)}")
        print(f"    {rec.leak_description}")


def main() -> None:
    ap = argparse.ArgumentParser(description="CRO & Liquidity Advisor Agent")
    ap.add_argument("--dry-run", action="store_true", help="print recommendations, write nothing")
    ap.add_argument(
        "--print-metrics",
        action="store_true",
        help="ingest and dump the MetricsBundle as JSON, then exit (no LLM, no writes)",
    )
    ap.add_argument(
        "--fixture",
        metavar="PATH",
        help="ingest from a MetricsBundle JSON fixture instead of PostHog (offline)",
    )
    ap.add_argument(
        "--attribute",
        action="store_true",
        help="Phase 2: measure whether shipped recs' experiments moved their goal "
        "metric and annotate the matching GitHub issues (read-only except comments)",
    )
    ap.add_argument(
        "--weekly",
        action="store_true",
        help="Phase 3: autonomous weekly run — snapshot metrics, detect regressions "
        "vs last week, write a prioritized backlog, post a Slack digest. Read-only "
        "(no GitHub writes; issue emission still needs an approved non-dry run).",
    )
    args = ap.parse_args()

    # --fixture overrides the ingest source for this process via settings env.
    if args.fixture:
        os.environ["FIXTURE_PATH"] = args.fixture
        from .config import settings

        settings.fixture_path = args.fixture

    if args.print_metrics:
        _print_metrics()
        return

    if args.attribute:
        _run_attribution()
        return

    if args.weekly:
        _run_weekly()
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(DB_PATH)) as saver:
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": "cro-advisor"}}

        result = graph.invoke(AgentState(dry_run=args.dry_run), config)
        state = AgentState.model_validate(result)

        _print_recommendations(state.recommendations)

        if args.dry_run:
            print("\nDry-run complete — nothing written.")
            return

        if not state.recommendations:
            return
        answer = input("\nOpen these as GitHub issues? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted; nothing written.")
            return

        # resume past the interrupt with approval
        from langgraph.types import Command

        final = graph.invoke(Command(resume=True), config)
        for url in AgentState.model_validate(final).emitted_issue_urls:
            print(f"opened: {url}")


if __name__ == "__main__":
    main()

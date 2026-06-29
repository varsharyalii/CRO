"""Phase 0.4 — idempotent issue emission.

emit_issues must skip any recommendation whose fingerprint already appears in an
open advisor issue, so re-running the agent never creates duplicates. We mock
the GitHub client's network calls (open_fingerprints + create_issue) so the test
is hermetic."""

from __future__ import annotations

from cro_agent.graph import node_emit_issues
from cro_agent.harness.fingerprint import fingerprint
from cro_agent.schemas import Evidence, Recommendation
from cro_agent.state import AgentState


def _rec(label: str, title: str) -> Recommendation:
    return Recommendation(
        title=title,
        leak_description="leak",
        evidence=[Evidence(metric_name="lost_volume", value=300.0)],
        root_cause_hypothesis="hypothesis",
        proposed_change="change",
        target_files=["real.tsx"],
        experiment_design="A/B, goal=x, n=1000",
        expected_impact="+5%",
        effort="M",
        fingerprint=fingerprint(label),
    )


def test_matching_fingerprint_is_skipped(monkeypatch):
    """A rec whose fingerprint is already open is NOT re-created; a new one is."""
    existing_label = "drop_view->marketplace_view"
    new_label = "item_view->claim_attempt"

    recs = [
        _rec(existing_label, "already filed"),
        _rec(new_label, "brand new"),
    ]

    created: list[Recommendation] = []

    class FakeGitHub:
        def open_fingerprints(self) -> set[str]:
            return {fingerprint(existing_label)}  # the first rec already exists

        def create_issue(self, rec: Recommendation) -> str:
            created.append(rec)
            return f"https://github.com/test/repo/issues/{len(created)}"

    # node_emit_issues imports GitHubClient lazily from .clients.github
    import cro_agent.clients.github as gh_mod

    monkeypatch.setattr(gh_mod, "GitHubClient", FakeGitHub)

    state = AgentState(dry_run=False, approved=True, recommendations=recs)
    out = node_emit_issues(state)

    # only the NEW recommendation was created — the duplicate was skipped
    assert len(created) == 1
    assert created[0].fingerprint == fingerprint(new_label)
    assert len(out["emitted_issue_urls"]) == 1


def test_dry_run_emits_nothing(monkeypatch):
    import cro_agent.clients.github as gh_mod

    def _boom():  # pragma: no cover - must never be constructed in dry-run
        raise AssertionError("GitHubClient must not be used in dry-run")

    monkeypatch.setattr(gh_mod, "GitHubClient", _boom)

    state = AgentState(dry_run=True, approved=False, recommendations=[_rec("x", "x")])
    assert node_emit_issues(state) == {}


def test_unapproved_emits_nothing(monkeypatch):
    import cro_agent.clients.github as gh_mod

    def _boom():  # pragma: no cover
        raise AssertionError("GitHubClient must not be used when unapproved")

    monkeypatch.setattr(gh_mod, "GitHubClient", _boom)

    state = AgentState(dry_run=False, approved=False, recommendations=[_rec("x", "x")])
    assert node_emit_issues(state) == {}

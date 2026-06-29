"""Phase 2 — impact-attribution query logic.

Tests the pure compute (moved / lift / inconclusive) and the orchestrator's
PostHog-read + GitHub-comment wiring (both mocked, no network)."""

from __future__ import annotations

from cro_agent.attribution import (
    MIN_EXPOSED_PER_VARIANT,
    compute_attribution,
    run_attribution,
)
from cro_agent.schemas import ExperimentSpec


def test_detects_positive_movement():
    r = compute_attribution("flag", "jz_claim_attempt", 1000, 200, 1000, 260)
    assert r.control_rate == 0.2
    assert r.variant_rate == 0.26
    assert r.lift == 0.3  # +30%
    assert r.moved is True
    assert "improved" in r.note


def test_detects_regression():
    r = compute_attribution("flag", "jz_claim_attempt", 1000, 200, 1000, 180)
    assert r.lift == -0.1
    assert r.moved is True
    assert "regressed" in r.note


def test_below_threshold_is_not_moved():
    r = compute_attribution("flag", "g", 1000, 200, 1000, 206)  # +3%
    assert r.moved is False
    assert "No meaningful movement" in r.note


def test_insufficient_sample_is_inconclusive():
    r = compute_attribution("flag", "g", 10, 2, 10, 5)
    assert r.moved is False
    assert "Inconclusive" in r.note
    assert MIN_EXPOSED_PER_VARIANT == 100


def test_run_attribution_reads_posthog_and_comments():
    class FakeClient:
        def variant_counts(self, event, flag_key, window_days):
            # exposure equal; goal event converts better on variant
            if event == "$feature_flag_called":
                return {"control": 1000, "variant": 1000}
            return {"control": 200, "variant": 260}

    commented: list[tuple[str, str]] = []

    class FakeGitHub:
        def comment_on_fingerprint(self, fingerprint, body):
            commented.append((fingerprint, body))
            return f"https://github.com/test/repo/issues/1#comment"

    spec = ExperimentSpec(
        feature_flag_key="drop-explore",
        hypothesis="adding explore CTA lifts claims",
        goal_event="jz_claim_attempt",
        minimum_sample_per_variant=500,
    )
    out = run_attribution(FakeClient(), FakeGitHub(), [("cro-abc", spec)], window_days=14)

    assert len(out) == 1
    fingerprint, result, url = out[0]
    assert fingerprint == "cro-abc"
    assert result.moved is True and result.lift == 0.3
    assert len(commented) == 1 and commented[0][0] == "cro-abc"
    assert "Impact attribution" in commented[0][1]


def test_run_attribution_dry_run_does_not_comment():
    class FakeClient:
        def variant_counts(self, event, flag_key, window_days):
            return {"control": 1000, "variant": 1000} if "called" in event else {"control": 200, "variant": 260}

    class FakeGitHub:
        def comment_on_fingerprint(self, fingerprint, body):  # pragma: no cover
            raise AssertionError("must not comment in dry-run")

    spec = ExperimentSpec(
        feature_flag_key="f", hypothesis="h", goal_event="jz_claim_attempt", minimum_sample_per_variant=500
    )
    out = run_attribution(FakeClient(), FakeGitHub(), [("fp", spec)], 14, dry_run=True)
    assert out[0][2] is None

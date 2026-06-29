import pytest

from cro_agent.harness import fingerprint
from cro_agent.harness.grounding import GroundingError, validate_recommendation
from cro_agent.schemas import Evidence, Recommendation


def _rec(**kw) -> Recommendation:
    base = dict(
        title="Reduce claim→checkout drop",
        leak_description="big leak",
        evidence=[Evidence(metric_name="lost_volume", value=300.0)],
        root_cause_hypothesis="auth gate",
        proposed_change="inline OTP",
        target_files=["real.tsx"],
        experiment_design="A/B inline vs redirect, goal=checkout_submit, n=1000",
        expected_impact="+5%",
        effort="M",
    )
    base.update(kw)
    return Recommendation(**base)


def test_accepts_grounded_recommendation(metrics, tmp_path):
    (tmp_path / "real.tsx").write_text("// component")
    validate_recommendation(_rec(), metrics, tmp_path)  # no raise


def test_rejects_fabricated_metric(metrics, tmp_path):
    (tmp_path / "real.tsx").write_text("// component")
    rec = _rec(evidence=[Evidence(metric_name="made_up", value=99999.0)])
    with pytest.raises(GroundingError, match="Fabricated metric"):
        validate_recommendation(rec, metrics, tmp_path)


def test_rejects_nonexistent_file(metrics, tmp_path):
    rec = _rec(target_files=["does/not/exist.tsx"])
    with pytest.raises(GroundingError, match="does not exist"):
        validate_recommendation(rec, metrics, tmp_path)


def test_fingerprint_is_stable():
    assert fingerprint("liquidity:claim_to_paid") == fingerprint("liquidity:claim_to_paid")
    assert fingerprint("a") != fingerprint("b")

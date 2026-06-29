"""Phase 4 — closed loop: learned prior over what kinds of changes move metrics."""

from __future__ import annotations

from cro_agent.attribution import compute_attribution
from cro_agent.learning import (
    change_kind,
    load_prior,
    update_prior_from_attribution,
)


def test_change_kind_buckets():
    assert change_kind("drop_view->marketplace_view") == "discovery"
    assert change_kind("item_view->claim_attempt") == "claim"
    assert change_kind("checkout_intent->checkout_submit") == "checkout"
    assert change_kind("liquidity:seller_activation") == "seller"
    assert change_kind("liquidity:expired_claim_rate") == "liquidity_hold"


def test_prior_records_wins_and_persists(tmp_path):
    win = compute_attribution("f", "jz_claim_attempt", 1000, 200, 1000, 260)  # +30%, moved
    flat = compute_attribution("f", "jz_claim_attempt", 1000, 200, 1000, 202)  # ~flat

    update_prior_from_attribution(tmp_path, "jz_claim_attempt", win)
    update_prior_from_attribution(tmp_path, "jz_claim_attempt", flat)

    prior = load_prior(tmp_path)
    entry = prior.entries["claim"]
    assert entry.trials == 2
    assert entry.wins == 1
    assert entry.win_rate == 0.5


def test_hint_for_unseen_kind_is_none(tmp_path):
    assert load_prior(tmp_path).hint_for("checkout") is None


def test_hint_for_seen_kind(tmp_path):
    win = compute_attribution("f", "jz_checkout_submit", 1000, 200, 1000, 300)
    update_prior_from_attribution(tmp_path, "jz_checkout_submit", win)
    hint = load_prior(tmp_path).hint_for("checkout")
    assert hint is not None and "win rate" in hint

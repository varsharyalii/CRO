"""Phase 4 — closed loop: learn a durable prior over what kinds of changes move
metrics, from past attribution results, and feed it back into recommendation
generation.

The prior is keyed by a coarse "change kind" (the opportunity label's funnel area,
e.g. 'checkout', 'claim', 'discovery') so it generalizes across drops/sellers. It
is stored as JSON under HISTORY_DIR and cited as additional context in the
recommend prompt. Read-only; learning only happens when an attribution result is
recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .schemas import AttributionResult

PRIOR_FILENAME = "learned_prior.json"


def change_kind(opportunity_label: str) -> str:
    """Map an opportunity label to a coarse change-kind bucket the prior is keyed on."""
    label = opportunity_label.lower()
    if "marketplace_view" in label or "drop_view->drop_card" in label:
        return "discovery"
    if "expired" in label:  # check before generic "claim" (expired_claim_rate)
        return "liquidity_hold"
    if "checkout" in label or "payment" in label or "claim_to_paid" in label:
        return "checkout"
    if "claim" in label:
        return "claim"
    if "seller" in label or "sell_through" in label or "activation" in label:
        return "seller"
    return "other"


class PriorEntry(BaseModel):
    kind: str
    trials: int = 0          # experiments observed
    wins: int = 0            # experiments that moved the goal positively
    cumulative_lift: float = 0.0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trials) if self.trials else 0.0

    @property
    def avg_lift(self) -> float:
        return (self.cumulative_lift / self.trials) if self.trials else 0.0


class LearnedPrior(BaseModel):
    entries: dict[str, PriorEntry] = {}

    def record(self, kind: str, result: AttributionResult) -> None:
        entry = self.entries.setdefault(kind, PriorEntry(kind=kind))
        entry.trials += 1
        entry.cumulative_lift += result.lift
        if result.moved and result.lift > 0:
            entry.wins += 1

    def hint_for(self, kind: str) -> str | None:
        """One-line prior hint for the recommend prompt, or None if unseen."""
        e = self.entries.get(kind)
        if e is None or e.trials == 0:
            return None
        return (
            f"Prior for '{kind}' changes: {e.wins}/{e.trials} past experiments moved "
            f"the goal positively (win rate {e.win_rate:.0%}, avg lift {e.avg_lift:+.1%})."
        )


def load_prior(history_dir: str | Path) -> LearnedPrior:
    path = Path(history_dir) / PRIOR_FILENAME
    if not path.exists():
        return LearnedPrior()
    return LearnedPrior.model_validate_json(path.read_text())


def save_prior(prior: LearnedPrior, history_dir: str | Path) -> Path:
    root = Path(history_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / PRIOR_FILENAME
    path.write_text(prior.model_dump_json(indent=2))
    return path


def update_prior_from_attribution(
    history_dir: str | Path, opportunity_label: str, result: AttributionResult
) -> LearnedPrior:
    """Closed-loop step: fold one attribution result into the durable prior."""
    prior = load_prior(history_dir)
    prior.record(change_kind(opportunity_label), result)
    save_prior(prior, history_dir)
    return prior

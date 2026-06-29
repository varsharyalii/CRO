"""Phase 2 — impact attribution.

After a recommendation ships and its PostHog experiment runs, measure whether the
goal metric moved between control and variant, and annotate the original GitHub
issue with the result. Read-only against PostHog; the only write is the issue
comment (added by the caller via GitHubClient.comment_on_fingerprint).

The conversion-fetching query and the moved/lift computation are kept separate so
the math is unit-testable without any network.
"""

from __future__ import annotations

from .schemas import AttributionResult

# Minimum relative lift (absolute) to call a metric "moved", and minimum exposed
# users per variant before we trust the result.
MOVED_LIFT_THRESHOLD = 0.05
MIN_EXPOSED_PER_VARIANT = 100


def compute_attribution(
    feature_flag_key: str,
    goal_event: str,
    control_exposed: int,
    control_converted: int,
    variant_exposed: int,
    variant_converted: int,
) -> AttributionResult:
    """Pure: turn per-variant exposure/conversion counts into an AttributionResult."""
    control_rate = (control_converted / control_exposed) if control_exposed else 0.0
    variant_rate = (variant_converted / variant_exposed) if variant_exposed else 0.0
    lift = (variant_rate / control_rate - 1.0) if control_rate else 0.0

    enough = control_exposed >= MIN_EXPOSED_PER_VARIANT and variant_exposed >= MIN_EXPOSED_PER_VARIANT
    moved = enough and abs(lift) >= MOVED_LIFT_THRESHOLD

    if not enough:
        note = (
            f"Inconclusive: need ≥{MIN_EXPOSED_PER_VARIANT} exposed per variant "
            f"(control={control_exposed}, variant={variant_exposed})."
        )
    elif moved:
        direction = "improved" if lift > 0 else "regressed"
        note = (
            f"Goal `{goal_event}` {direction} {lift:+.1%} "
            f"(control {control_rate:.1%} → variant {variant_rate:.1%})."
        )
    else:
        note = (
            f"No meaningful movement: {lift:+.1%} on `{goal_event}` "
            f"(below ±{MOVED_LIFT_THRESHOLD:.0%} threshold)."
        )

    return AttributionResult(
        feature_flag_key=feature_flag_key,
        goal_event=goal_event,
        control_exposed=control_exposed,
        control_converted=control_converted,
        variant_exposed=variant_exposed,
        variant_converted=variant_converted,
        control_rate=round(control_rate, 4),
        variant_rate=round(variant_rate, 4),
        lift=round(lift, 4),
        moved=moved,
        note=note,
    )


def attribute_experiment(client, feature_flag_key: str, goal_event: str, window_days: int) -> AttributionResult:
    """Fetch per-variant exposure + goal conversion from PostHog and attribute.

    Exposure is read from `$feature_flag_called`; conversion is the goal_event,
    both bucketed by the experiment's variant property `$feature/<flag_key>`.
    """
    exposed = client.variant_counts("$feature_flag_called", feature_flag_key, window_days)
    converted = client.variant_counts(goal_event, feature_flag_key, window_days)
    return compute_attribution(
        feature_flag_key,
        goal_event,
        control_exposed=exposed.get(client_control_key := "control", 0),
        control_converted=converted.get(client_control_key, 0),
        variant_exposed=exposed.get("variant", 0) or exposed.get("test", 0),
        variant_converted=converted.get("variant", 0) or converted.get("test", 0),
    )


def run_attribution(client, gh, specs, window_days: int, dry_run: bool = False, history_dir=None):
    """For each (fingerprint, ExperimentSpec), measure goal movement and annotate
    the matching GitHub issue. Returns [(fingerprint, AttributionResult, comment_url)].

    The issue comment is the ONLY write; everything else is read-only PostHog.
    When history_dir is given (and not dry_run), fold each result into the durable
    learned prior (Phase 4 closed loop)."""
    out = []
    for fingerprint, spec in specs:
        result = attribute_experiment(
            client, spec.feature_flag_key, spec.goal_event, window_days
        )
        comment_url = None
        if not dry_run:
            comment_url = gh.comment_on_fingerprint(
                fingerprint, render_attribution_comment(result)
            )
            if history_dir is not None:
                from .learning import update_prior_from_attribution

                update_prior_from_attribution(history_dir, spec.goal_event, result)
        out.append((fingerprint, result, comment_url))
    return out


def render_attribution_comment(result: AttributionResult) -> str:
    """Markdown comment body appended to the original advisor GitHub issue."""
    verdict = "✅ moved" if result.moved else "➖ no clear movement"
    return f"""<!-- cro-attribution: {result.feature_flag_key} -->

## Impact attribution — {verdict}

{result.note}

| | exposed | converted | rate |
|---|--:|--:|--:|
| control | {result.control_exposed} | {result.control_converted} | {result.control_rate:.1%} |
| {result.variant_converted and 'variant' or 'variant'} | {result.variant_exposed} | {result.variant_converted} | {result.variant_rate:.1%} |

Relative lift: **{result.lift:+.1%}** on `{result.goal_event}` (flag `{result.feature_flag_key}`).

---
*Read-only attribution by the CRO & Liquidity Advisor Agent.*
"""

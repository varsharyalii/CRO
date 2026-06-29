"""Read-only PostHog Query API (HogQL) client.

Queries the canonical buyer funnel and the seller-liquidity metrics. Where a
stable named PostHog insight is configured (POSTHOG_*_INSIGHT_ID), it is queried
by id for comparability over time; otherwise the inline HogQL below is used.

The MVP leans on PostHog only. All queries are read-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from ..config import settings
from ..schemas import FunnelStep, LiquidityMetric, MetricsBundle

# Canonical buyer funnel (event order). Names mirror posthog-setup-report.md.
# jz_checkout_submit is the canonical wrapper event (the `jz_checkout_submitted`
# direct-capture variant is name-drift being fixed in frontend Phase A.1).
BUYER_FUNNEL_EVENTS: list[tuple[str, str]] = [
    ("marketplace_view", "jz_marketplace_view"),
    ("drop_view", "jz_drop_view"),
    ("drop_card_select", "jz_drop_card_select"),
    ("item_view", "jz_item_view"),
    ("claim_attempt", "jz_claim_attempt"),
    ("claim_success", "jz_claim_success"),
    ("checkout_intent", "jz_checkout_intent"),
    ("checkout_submit", "jz_checkout_submit"),
    ("checkout_created", "jz_checkout_created"),
    ("payment_return", "jz_payment_return"),
    ("purchase_confirmed", "jz_purchase_confirmed"),
]


class PostHogClient:
    def __init__(self) -> None:
        self.host = settings.posthog_host.rstrip("/")
        self.project_id = settings.posthog_project_id
        self.key = settings.posthog_personal_api_key

    # --- transport -----------------------------------------------------------

    def _query(self, hogql: str) -> list[list]:
        url = f"{self.host}/api/projects/{self.project_id}/query/"
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self.key}"},
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _scalar(self, hogql: str) -> float:
        rows = self._query(hogql)
        return float(rows[0][0]) if rows and rows[0] else 0.0

    def _funnel_breakdown(
        self, from_event: str, to_event: str, dimension: str, window_days: int
    ) -> list[tuple[str, int, int]]:
        """Run a 2-step PostHog FunnelsQuery broken down by an event property.

        Returns [(breakdown_value, step1_count, step2_count), ...] using PostHog's
        real same-person, ordered conversion per cohort (not naive event counts).
        """
        url = f"{self.host}/api/projects/{self.project_id}/query/"
        query = {
            "kind": "FunnelsQuery",
            "series": [
                {"kind": "EventsNode", "event": from_event},
                {"kind": "EventsNode", "event": to_event},
            ],
            "breakdownFilter": {"breakdown": dimension, "breakdown_type": "event"},
            "dateRange": {"date_from": f"-{window_days}d"},
        }
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self.key}"},
            json={"query": query},
            timeout=90,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        out: list[tuple[str, int, int]] = []
        for series in results:  # one entry per breakdown value
            if not series or len(series) < 2:
                continue
            step1, step2 = series[0], series[1]
            bv = step1.get("breakdown_value")
            if isinstance(bv, list):
                bv = bv[0] if bv else ""
            out.append((str(bv), int(step1.get("count", 0)), int(step2.get("count", 0))))
        return out

    def _insight_result(self, insight_id: str) -> dict:
        """Fetch a saved insight's last result (read-only) for stable definitions."""
        url = f"{self.host}/api/projects/{self.project_id}/insights/{insight_id}/"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {self.key}"}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    # --- public API ----------------------------------------------------------

    def ingest(self, window_days: int) -> MetricsBundle:
        return MetricsBundle(
            window_days=window_days,
            buyer_funnel=self._buyer_funnel(window_days),
            liquidity_metrics=self._liquidity(window_days),
        )

    # --- buyer funnel --------------------------------------------------------

    def _buyer_funnel(self, window_days: int) -> list[FunnelStep]:
        if settings.posthog_buyer_funnel_insight_id:
            return self._buyer_funnel_from_insight(
                settings.posthog_buyer_funnel_insight_id
            )
        steps: list[FunnelStep] = []
        for name, event in BUYER_FUNNEL_EVENTS:
            volume = int(
                self._scalar(
                    f"SELECT count(DISTINCT person_id) FROM events "
                    f"WHERE event = '{event}' "
                    f"AND timestamp >= now() - INTERVAL {window_days} DAY"
                )
            )
            steps.append(FunnelStep(name=name, event=event, volume=volume))
        return steps

    def _buyer_funnel_from_insight(self, insight_id: str) -> list[FunnelStep]:
        """Map a saved PostHog funnel insight's result onto our FunnelStep list.

        PostHog funnel results are an ordered list of steps with `count` and an
        `action_id`/`custom_name`; we align by order against BUYER_FUNNEL_EVENTS.
        """
        result = self._insight_result(insight_id).get("result", [])
        steps: list[FunnelStep] = []
        for (name, event), row in zip(BUYER_FUNNEL_EVENTS, result):
            count = int(row.get("count", 0)) if isinstance(row, dict) else 0
            steps.append(FunnelStep(name=name, event=event, volume=count))
        return steps

    # --- seller liquidity ----------------------------------------------------

    def _liquidity(self, window_days: int) -> list[LiquidityMetric]:
        w = window_days
        metrics: list[LiquidityMetric] = []

        # claim → paid: the core liquidity funnel (paid / claimed).
        claimed = self._scalar(
            f"SELECT count() FROM events WHERE event = 'jz_claim_success' "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        paid = self._scalar(
            f"SELECT count() FROM events WHERE event = 'jz_purchase_confirmed' "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        metrics.append(
            LiquidityMetric(
                name="claim_to_paid",
                value=round(paid / claimed, 4) if claimed else 0.0,
                sample_size=int(claimed),
            )
        )

        # expired_claim_rate: claimed-but-released/cancelled before paying.
        # NOTE: explicit jz_claim_expired lands in frontend Phase A.4; until then
        # this is approximated from released + cancelled holds over claims.
        released = self._scalar(
            f"SELECT count() FROM events WHERE event IN "
            f"('jz_claim_expired','jz_claim_released','jz_claim_cancel') "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        metrics.append(
            LiquidityMetric(
                name="expired_claim_rate",
                value=round(released / claimed, 4) if claimed else 0.0,
                sample_size=int(claimed),
            )
        )

        # sell_through: PROXY = distinct sellers with >=1 purchase / distinct
        # sellers whose items were viewed. True item-level sell-through (units
        # sold / units listed) needs the /v1/analytics/drops/me scorecard — the
        # PostHog purchase event has no item/drop id (items are a nested blob),
        # so we approximate at the seller level via seller_profile_id, which is
        # present on both jz_item_view and jz_purchase_confirmed.
        sellers_viewed = self._scalar(
            f"SELECT count(DISTINCT properties.seller_profile_id) FROM events "
            f"WHERE event = 'jz_item_view' "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        sellers_sold = self._scalar(
            f"SELECT count(DISTINCT properties.seller_profile_id) FROM events "
            f"WHERE event = 'jz_purchase_confirmed' "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        metrics.append(
            LiquidityMetric(
                name="sell_through",
                value=round(sellers_sold / sellers_viewed, 4) if sellers_viewed else 0.0,
                sample_size=int(sellers_viewed),
            )
        )

        # NOTE: the drop-lander -> marketplace explorer cross-sell opportunity is
        # scored as a first-class buyer-funnel leak (drop_view -> marketplace_view)
        # in scoring.py, computed from the funnel volumes above — not duplicated
        # here as a liquidity metric.

        # seller_activation: apply → setup completion (apply → setup → first drop).
        applied = self._scalar(
            f"SELECT count(DISTINCT person_id) FROM events "
            f"WHERE event = 'jz_seller_apply_submit' "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        set_up = self._scalar(
            f"SELECT count(DISTINCT person_id) FROM events "
            f"WHERE event = 'jz_seller_setup_complete' "
            f"AND timestamp >= now() - INTERVAL {w} DAY"
        )
        metrics.append(
            LiquidityMetric(
                name="seller_activation",
                value=round(set_up / applied, 4) if applied else 0.0,
                sample_size=int(applied),
            )
        )

        return metrics


    # --- attribution (Phase 2) ----------------------------------------------

    def variant_counts(self, event: str, flag_key: str, window_days: int) -> dict[str, int]:
        """Distinct persons for `event` bucketed by the experiment variant
        property `$feature/<flag_key>` (e.g. {'control': 1200, 'variant': 1180})."""
        prop = f"$feature/{flag_key}"
        rows = self._query(
            f"SELECT properties['{prop}'] AS variant, count(DISTINCT person_id) "
            f"FROM events WHERE event = '{event}' "
            f"AND properties['{prop}'] != '' "
            f"AND timestamp >= now() - INTERVAL {window_days} DAY "
            f"GROUP BY variant"
        )
        out: dict[str, int] = {}
        for row in rows:
            if row and len(row) >= 2 and row[0]:
                out[str(row[0])] = int(row[1])
        return out

    # --- segmentation (Phase 1) ---------------------------------------------

    def segment_edge(
        self, from_step: str, to_step: str, dimension: str, window_days: int, top_n: int = 4
    ) -> list[tuple[str, float, int]]:
        """Break one buyer-funnel edge's drop-off by a cohort dimension.

        Returns [(segment_value, dropoff_rate, upstream_volume), ...] sorted by
        upstream volume desc, using PostHog's real per-cohort funnel conversion.
        """
        name_to_event = dict(BUYER_FUNNEL_EVENTS)
        fe = name_to_event.get(from_step)
        te = name_to_event.get(to_step)
        if not fe or not te:
            return []
        rows = self._funnel_breakdown(fe, te, dimension, window_days)
        stats: list[tuple[str, float, int]] = []
        for seg, up, down in rows:
            if not seg or up <= 0:
                continue
            dropoff = max(0.0, 1.0 - down / up)
            stats.append((seg, round(dropoff, 4), up))
        stats.sort(key=lambda s: s[2], reverse=True)
        return stats[:top_n]


def load_fixture(path: str | Path) -> MetricsBundle:
    """Load a MetricsBundle from JSON — offline ingest for dry-runs / tests."""
    return MetricsBundle.model_validate_json(Path(path).read_text())

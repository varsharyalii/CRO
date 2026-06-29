import pytest

from cro_agent.schemas import FunnelStep, LiquidityMetric, MetricsBundle


@pytest.fixture
def metrics() -> MetricsBundle:
    return MetricsBundle(
        window_days=14,
        buyer_funnel=[
            FunnelStep(name="item_view", event="jz_item_view", volume=1000),
            FunnelStep(name="claim_attempt", event="jz_claim_attempt", volume=600),
            FunnelStep(name="claim_success", event="jz_claim_success", volume=500),
            FunnelStep(name="checkout_submit", event="jz_checkout_submit", volume=200),
            FunnelStep(name="purchase_confirmed", event="jz_purchase_confirmed", volume=150),
        ],
        liquidity_metrics=[
            LiquidityMetric(name="claim_to_paid", value=0.30, sample_size=500),
            LiquidityMetric(name="sell_through", value=0.45, sample_size=300),
        ],
    )

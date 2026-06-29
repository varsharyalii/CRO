from cro_agent.scoring import rank_opportunities, score_buyer_funnel, score_liquidity


def test_buyer_funnel_lost_volume(metrics):
    opps = {o.label: o for o in score_buyer_funnel(metrics)}
    # claim_success(500) -> checkout_submit(200): dropoff 0.6, lost = 300
    leak = opps["claim_success->checkout_submit"]
    assert leak.dropoff_rate == 0.6
    assert leak.score == 300.0


def test_liquidity_gap_scoring(metrics):
    opps = {o.label: o for o in score_liquidity(metrics)}
    # claim_to_paid 0.30 -> gap 0.70 over 500 = 350
    assert opps["liquidity:claim_to_paid"].score == 350.0


def test_sample_size_gate_drops_noise(metrics):
    # min sample above every step → nothing survives
    assert rank_opportunities(metrics, min_sample_size=10_000) == []


def test_ranking_is_score_desc(metrics):
    ranked = rank_opportunities(metrics, min_sample_size=100)
    scores = [o.score for o in ranked]
    assert scores == sorted(scores, reverse=True)

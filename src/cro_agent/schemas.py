"""Pydantic schemas: typed graph state and structured LLM outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# --- Ingested metrics ---------------------------------------------------------


class FunnelStep(BaseModel):
    name: str
    event: str
    volume: int


class LiquidityMetric(BaseModel):
    name: str
    value: float
    sample_size: int


class SegmentStat(BaseModel):
    """A top leak broken down by one cohort dimension (Phase 1).

    e.g. opportunity 'item_view->claim_attempt' by dimension 'drop_status',
    segment_value 'scheduled', dropoff_rate 0.91 over upstream_volume 120.
    """

    opportunity_label: str
    dimension: str
    segment_value: str
    dropoff_rate: float
    upstream_volume: int


class MetricsBundle(BaseModel):
    """Everything ingest_metrics produced; the grounding validator checks against this."""

    window_days: int
    buyer_funnel: list[FunnelStep] = Field(default_factory=list)
    liquidity_metrics: list[LiquidityMetric] = Field(default_factory=list)
    segments: list[SegmentStat] = Field(default_factory=list)

    def known_numbers(self) -> set[float]:
        nums: set[float] = set()
        for s in self.buyer_funnel:
            nums.add(float(s.volume))
        for m in self.liquidity_metrics:
            nums.add(float(m.value))
            nums.add(float(m.sample_size))
        for seg in self.segments:
            nums.add(float(seg.dropoff_rate))
            nums.add(float(seg.upstream_volume))
        return nums


# --- Scored opportunities (deterministic) -------------------------------------


class Opportunity(BaseModel):
    kind: Literal["buyer_funnel", "liquidity"]
    label: str
    from_step: str | None = None
    to_step: str | None = None
    dropoff_rate: float
    upstream_volume: int
    sample_size: int
    score: float
    segment: str | None = None


# --- Surface mapping ----------------------------------------------------------


class Surface(BaseModel):
    files: list[str]
    note: str


# --- LLM structured recommendation --------------------------------------------


class Evidence(BaseModel):
    metric_name: str
    value: float


class ExperimentSpec(BaseModel):
    """Phase 2: handoff-ready PostHog Experiment definition (human-launched).

    The agent does NOT launch experiments — it produces a spec a human can paste
    into PostHog Experiments. feature_flag_key + goal_event are the fields the
    attribution step later reads to measure whether the change worked.
    """

    feature_flag_key: str  # e.g. "drop-explore-more-sellers"
    hypothesis: str
    control_label: str = "control"
    variant_label: str = "variant"
    goal_event: str  # PostHog event whose conversion the experiment moves
    minimum_sample_per_variant: int


class Recommendation(BaseModel):
    title: str
    leak_description: str
    evidence: list[Evidence] = Field(..., min_length=1)
    root_cause_hypothesis: str
    proposed_change: str
    target_files: list[str] = Field(..., min_length=1)
    experiment_design: str
    experiment: ExperimentSpec | None = None
    expected_impact: str
    effort: Literal["S", "M", "L"]
    fingerprint: str = ""


# --- Impact attribution (Phase 2) ---------------------------------------------


class AttributionResult(BaseModel):
    feature_flag_key: str
    goal_event: str
    control_exposed: int
    control_converted: int
    variant_exposed: int
    variant_converted: int
    control_rate: float
    variant_rate: float
    lift: float  # relative lift, variant vs control (e.g. 0.12 == +12%)
    moved: bool  # True if |lift| past the threshold AND min sample met
    note: str

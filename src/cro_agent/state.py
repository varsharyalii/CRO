"""LangGraph typed state."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import MetricsBundle, Opportunity, Recommendation


class AgentState(BaseModel):
    dry_run: bool = True

    metrics: MetricsBundle | None = None
    opportunities: list[Opportunity] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)

    approved: bool = False
    emitted_issue_urls: list[str] = Field(default_factory=list)

    # audit / diagnostics
    notes: list[str] = Field(default_factory=list)
    llm_calls: int = 0

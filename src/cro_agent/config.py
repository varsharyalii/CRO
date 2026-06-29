"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostHog — production project is US. Set POSTHOG_PROJECT_ID in .env to the
    # US project that carries live traffic (the 189774 "Default project" in the
    # pre-launch audit report was a different/EU project — do not assume it).
    posthog_host: str = "https://us.posthog.com"
    posthog_project_id: str = ""
    posthog_personal_api_key: str = ""

    # Optional: query stable named insights by id instead of ad-hoc HogQL.
    # Empty → fall back to the inline HogQL definitions in clients/posthog.py.
    posthog_buyer_funnel_insight_id: str = ""
    posthog_liquidity_insight_id: str = ""

    # Offline fixture: when set, ingest reads this MetricsBundle JSON instead of
    # hitting the PostHog API (lets dry-runs work before live traffic exists).
    fixture_path: str = ""

    # Repo grounding
    jhaazi_frontend_path: str = "../jhaazi-frontend"

    # GitHub
    github_token: str = ""
    github_repo: str = "Jhaazi/jhaazi-frontend"

    # LLM — provider-agnostic. llm_provider selects the client; model + key follow.
    llm_provider: str = "groq"  # "groq" | "anthropic"
    cro_agent_model: str = "llama-3.3-70b-versatile"
    anthropic_api_key: str = ""
    groq_api_key: str = ""

    # Analysis
    analysis_window_days: int = 14
    min_sample_size: int = 100

    # Caps
    max_llm_calls: int = 25
    # Phase 3: hard per-run cost ceiling (USD). Estimated from llm_calls; the run
    # aborts recommend once exceeded so an autonomous cron can't run away.
    max_run_cost_usd: float = 1.0
    usd_per_llm_call: float = 0.02  # rough per-recommendation estimate

    # Phase 3: regression detection + digest
    regression_threshold: float = 0.05  # dropoff worsening (abs) to flag a regression
    slack_webhook_url: str = ""  # empty → digest is printed, not posted
    history_dir: str = "data/history"


settings = Settings()

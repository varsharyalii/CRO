"""GitHub issue client — idempotent issue creation, scoped to issues:write."""

from __future__ import annotations

import httpx

from ..config import settings
from ..harness.fingerprint import LABEL
from ..schemas import Recommendation

API = "https://api.github.com"


class GitHubClient:
    def __init__(self) -> None:
        self.repo = settings.github_repo
        self.token = settings.github_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def open_fingerprints(self) -> set[str]:
        """Fingerprints already present in open advisor issues (dedupe key)."""
        resp = httpx.get(
            f"{API}/repos/{self.repo}/issues",
            headers=self._headers(),
            params={"state": "open", "labels": LABEL, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        seen: set[str] = set()
        for issue in resp.json():
            body = issue.get("body") or ""
            marker = "<!-- cro-fingerprint: "
            if marker in body:
                seen.add(body.split(marker, 1)[1].split(" ", 1)[0])
        return seen

    def find_issue_by_fingerprint(self, fingerprint: str) -> int | None:
        """Issue number of the open advisor issue carrying this fingerprint, if any."""
        resp = httpx.get(
            f"{API}/repos/{self.repo}/issues",
            headers=self._headers(),
            params={"state": "all", "labels": LABEL, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        marker = f"<!-- cro-fingerprint: {fingerprint} -->"
        for issue in resp.json():
            if marker in (issue.get("body") or ""):
                return int(issue["number"])
        return None

    def comment_on_fingerprint(self, fingerprint: str, body: str) -> str | None:
        """Append a comment (e.g. an attribution result) to the issue for this
        fingerprint. Returns the comment URL, or None if no matching issue."""
        number = self.find_issue_by_fingerprint(fingerprint)
        if number is None:
            return None
        resp = httpx.post(
            f"{API}/repos/{self.repo}/issues/{number}/comments",
            headers=self._headers(),
            json={"body": body},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["html_url"]

    def create_issue(self, rec: Recommendation) -> str:
        body = _render_body(rec)
        resp = httpx.post(
            f"{API}/repos/{self.repo}/issues",
            headers=self._headers(),
            json={"title": rec.title, "body": body, "labels": [LABEL]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["html_url"]


def _render_experiment(rec: Recommendation) -> str:
    """Handoff-ready PostHog Experiment block (Phase 2), if the LLM produced one."""
    e = rec.experiment
    if e is None:
        return f"## Experiment design\n{rec.experiment_design}\n"
    return f"""## Experiment design
{rec.experiment_design}

**PostHog Experiment (handoff-ready — launch manually):**
- Feature flag: `{e.feature_flag_key}`
- Hypothesis: {e.hypothesis}
- Variants: `{e.control_label}` vs `{e.variant_label}`
- Goal metric: `{e.goal_event}`
- Min sample / variant: {e.minimum_sample_per_variant}
"""


def _render_body(rec: Recommendation) -> str:
    evidence = "\n".join(f"- `{e.metric_name}` = {e.value}" for e in rec.evidence)
    files = "\n".join(f"- `{f}`" for f in rec.target_files)
    return f"""<!-- cro-fingerprint: {rec.fingerprint} -->

## Leak
{rec.leak_description}

## Evidence (from PostHog)
{evidence}

## Root-cause hypothesis
{rec.root_cause_hypothesis}

## Proposed change
{rec.proposed_change}

**Target files:**
{files}

{_render_experiment(rec)}
## Expected impact / effort
{rec.expected_impact} · effort: **{rec.effort}**

---
*Filed by the CRO & Liquidity Advisor Agent. Read-only analysis; review before acting.*
"""

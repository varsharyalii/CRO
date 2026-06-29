# Carry-forward implementation prompts

Paste these into Claude Code **one at a time**, in order. Each is self-contained so a
cold session can run it without prior context. Every prompt assumes you've opened this
repo and that [PLAN.md](PLAN.md) is the source of truth — point Claude at it first.

**Two repos are involved:**
- `cro-liquidity-agent` (this repo) — the agent. Most prompts run here.
- `jhaazi-frontend` — the PostHog instrumentation work (Part A). Prompts tagged **[frontend]** run there.

**Always-on rule to give Claude:** *"Read PLAN.md before doing anything. This is a read-only advisor agent — never add code that mutates PostHog, the frontend, or seller data. Run `pytest` before telling me you're done."*

---

## Phase 0 — MVP (finish the scaffold, get a real dry-run)

The pipeline is already scaffolded and tests pass. These prompts make it run against
real data end-to-end.

### 0.1 — Wire real HogQL queries
```
Read PLAN.md and src/cro_agent/clients/posthog.py. The buyer-funnel queries use the
canonical jz_* event names but the liquidity query is a placeholder. Replace the
liquidity section with the real "claim → paid" liquidity funnel and add sell_through,
expired_claim_rate, and seller_activation metrics per PLAN.md Part B1 step 1. Where a
named PostHog insight exists, query it by id instead of ad-hoc HogQL. I'll provide the
PostHog project id and personal API key in .env. Add a `--print-metrics` flag to run.py
that ingests and dumps the MetricsBundle as JSON so I can eyeball it against PostHog
manually. Don't touch the LLM path yet.
```

### 0.2 — Ground the surface map against the real frontend
```
Open the jhaazi-frontend repo at the path in JHAAZI_FRONTEND_PATH. For every entry in
src/cro_agent/surface_map.py, verify the file paths actually exist and correspond to the
funnel step (cross-check against jhaazi-frontend's posthog-setup-report.md event↔component
map). Fix any wrong/missing paths. The grounding harness rejects nonexistent paths, so
after this a recommendation referencing these files must pass validate_recommendation.
Add a quick test that asserts every surface_map path exists under JHAAZI_FRONTEND_PATH.
```

### 0.3 — First real dry-run + spot-check
```
Run `python -m cro_agent.run --dry-run` against real PostHog (.env is filled in). It
should ingest, score, produce schema-valid recommendations for the top 3 buyer + top 2
liquidity leaks, pass the grounding harness, stop before emit, and write nothing. Show me
the output. Then spot-check ONE recommendation: confirm its cited metric matches a HogQL
query you run via the PostHog client, and confirm its target files exist. Report anything
that looks off — do not open any issues.
```

### 0.4 — Idempotent issue emission (the only write path)
```
Read src/cro_agent/clients/github.py and the emit_issues node in graph.py. Do a single
real run (not dry-run) with terminal approval against a TEST repo I'll set in GITHUB_REPO.
Approve once and confirm one issue is created per recommendation with the cro-fingerprint
marker and cro-advisor label. Then re-run and approve again — confirm ZERO duplicates are
created (open_fingerprints dedupe works). Add a test that mocks open_fingerprints and
asserts a matching fingerprint is skipped.
```

---

## Phase A — PostHog instrumentation **[frontend]**

These land in `jhaazi-frontend` and make the next agent run read cleaner data. None blocks
Phase 0. Order is by value (PLAN.md Part A).

### A.1 — Funnel-anchor consistency (highest value) **[frontend]**
```
In jhaazi-frontend, read posthog-events-audit-report.md §1. Fix the jz_checkout_submit
vs jz_checkout_submitted name-drift and the trackEvent/direct-capture double-fire in
shipping-checkout-screen.tsx and payment-return-screen.tsx so each funnel step fires
exactly once under one canonical name. Then run `npm run typecheck` and `npm run lint`,
and confirm the existing Playwright checkout/storefront smoke still passes. Don't change
any other events.
```

### A.2 — Drop-off reason properties **[frontend]**
```
In jhaazi-frontend, add reason properties to existing events per PLAN.md Part A item 2:
- jz_claim_conflict → conflict_reason ('sold_out' | 'limit' | 'already_claimed')
- jz_payment_return → return_status / failure_reason
- capture the checkout step where abandonment happens
These are additive properties only — don't rename or remove events. typecheck + lint, and
verify in PostHog live events that jz_claim_conflict now carries conflict_reason.
```

### A.3 — Auth-gate friction instrumentation **[frontend]**
```
In jhaazi-frontend, instrument the checkout auth interruption per PLAN.md Part A item 3:
auth_gate_surface, time-to-verify, OTP retry count, and the drop-off between jz_auth_start
and jz_otp_verify_success. Sites: checkout-auth-screen.tsx, quick-auth-sheet.tsx. Additive
only. typecheck + lint.
```

### A.4 — Claim-expiry event (core liquidity signal) **[frontend]**
```
In jhaazi-frontend, add an explicit jz_claim_expired event (hold timed out) with
seller_profile_id, drop_id, and time-held, per PLAN.md Part A item 4. Today only
jz_claim_released/cancel exist; expiry-by-timeout is dark. typecheck + lint.
```

### A.5 — Seller group analytics **[frontend]**
```
In jhaazi-frontend, register a PostHog group of type "seller" (key = seller_profile_id,
props: category, follower bucket, drops_count) per PLAN.md Part A item 5. No group() calls
exist today. typecheck + lint.
```

### A.6 — Server-side purchase capture **[frontend/backend]**
```
Add a server-side jz_purchase_confirmed capture via posthog-node keyed on the
booking/payment webhook, per PLAN.md Part A item 7, so the bottom of funnel is trustworthy
across devices (the client-side localStorage-deduped version undercounts). Keep the
client event too; ensure they dedupe on a shared transaction id.
```

---

## Phase 1 — Richer, segment-level recommendations (agent)

Run after Phase A events are live.
```
Read PLAN.md Part B1 step 3 (segment node) and Phase 1. Now that drop-off reasons,
jz_claim_expired, server-side purchase, and seller groups exist, upgrade the agent:
1. Make the `segment` node real — break the top leaks by cohort (category, new vs
   returning, live vs scheduled drop) using PostHog breakdowns, so recommendations say
   WHERE a leak is worst.
2. Add the new liquidity metrics (expired-claim rate from jz_claim_expired; per-seller-
   cohort claim-to-paid via the seller group) to the PostHog client and scoring.
3. Feed conflict_reason / failure_reason into the recommend prompt as evidence.
Keep everything grounded (evidence must trace to ingested data) and keep tests green.
```

---

## Phase 2 — Runnable experiments + impact attribution
```
Read PLAN.md Phase 2. Make the experiment-design output handoff-ready to PostHog
Experiments (still human-launched — the agent does NOT launch them). Add an impact-
attribution step: when a shipped recommendation's experiment exists, query whether its
goal metric moved vs baseline and annotate the original GitHub issue with the result.
Read-only except for the issue comment. Tests for the attribution query logic.
```

---

## Phase 3 — Scheduled autonomous runs + regression detection
```
Read PLAN.md Phase 3. Add a weekly scheduled run (cron) that:
1. Diffs this week's funnel vs last week (regression detection) using the SqliteSaver
   history, surfacing newly-worsened steps as high priority.
2. Maintains an auto-prioritized backlog.
3. Posts a Slack digest of the top opportunities.
Keep the human-approval interrupt before any GitHub write. Respect MAX_LLM_CALLS and add
a per-run cost cap. The autonomous run must still be read-only except for issues + Slack.
```

---

## Phase 4 — Closed loop / meta-insights
```
Read PLAN.md Phase 4. Build the closed loop: recommend → experiment → measure → learn a
prior over what kinds of changes actually move metrics, and feed cross-seller/cohort
meta-insights back into recommendation generation. Store the learned prior durably and
cite it as additional context in the recommend prompt. Keep it grounded and read-only.
```

---

## Verification checklist (give Claude after any phase)
```
Per PLAN.md "Verification": run pytest (unit tests for scoring, grounding validator
rejecting a fabricated metric + nonexistent path, and dedupe). Do a dry-run that produces
schema-valid recommendations and stops at human_approval writing nothing. Confirm the
agent remains read-only except for GitHub issues. Report results plainly — if anything
fails, show the output.
```

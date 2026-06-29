# Plan: CRO & Liquidity Optimization Advisor Agent (PostHog-driven)

## Context

**Goal:** increase marketplace *liquidity* on Jhaazi (a live-drop fashion marketplace) by having an LLM agent **analyze PostHog data and emit grounded, codebase-aware suggestions** for two-sided optimization:
- **Buyer CRO** — leaks in `marketplace_view → drop_view → drop_card_select → item_view → claim_attempt → claim_success → checkout_intent → checkout_submit → checkout_created → payment_return → purchase_confirmed`, plus the auth/OTP gate and payment-return failures.
- **Seller liquidity** — supply/matching efficiency: sell-through %, expired claims, claim-to-paid %, slow-moving drops, seller activation (`apply → setup → first drop`) and repeat drops.

**Why now:** PostHog tracking + identity are already solid (`trackEvent()` dual-pushes to dataLayer + `posthog.capture`; identity unified on `user.id` with phone/anon aliasing; full buyer+seller funnel instrumented per `posthog-setup-report.md`). The missing piece is *interpretation*: nobody is systematically turning that funnel data into prioritized, actionable optimization work. The agent does that and files it as GitHub issues.

**This is an advisor, not a mutator.** It is **read-only** against PostHog, the repo, and seller data. Its only write is opening GitHub issues, behind a human-approval gate in the MVP. This is the core safety property — no autonomous changes to live content, analytics, or code.

**Decisions made with the user:**
- **Scope = both buyer CRO + seller liquidity** (two-sided).
- **Codebase-aware**: each leak is traced to the responsible component/file in this repo, with a concrete proposed UI/UX change and an experiment design to validate it.
- **Output = GitHub issues** (one per high-priority recommendation, idempotent).
- Agent lives in a **separate repo/service** (Python/LangGraph). No frontend mutation is required for the MVP to run; frontend work is *optional instrumentation* that strengthens the signal for future runs.

**Two deliverables (per the request):**
1. **PostHog changes** to strengthen the CRO/liquidity signal.
2. A **state-based LangGraph agent + grounding harness**.

---

## Part A — PostHog: strengthen the signal (Outcome 1)

The agent's suggestion quality is bounded by data quality. Gaps to close (frontend / instrumentation work, landed incrementally — none blocks the MVP from running on existing events):

1. **Funnel-anchor consistency** *(highest value)* — fix `jz_checkout_submit` vs `jz_checkout_submitted` name-drift + `trackEvent`/direct-`capture` double-fire (`posthog-events-audit-report.md` §1, sites in `shipping-checkout-screen.tsx`, `payment-return-screen.tsx`). Without clean joins, funnel leak detection is unreliable.
2. **Drop-off *reason* properties** — turn "a leak exists" into "leak because X":
   - `jz_claim_conflict` → `conflict_reason` (`sold_out` | `limit` | `already_claimed`).
   - `jz_payment_return` → `return_status` / `failure_reason`.
   - capture the checkout step where abandonment happens.
3. **Auth-gate friction** — instrument the checkout auth interruption: `auth_gate_surface`, time-to-verify, OTP retry count, drop-off between `jz_auth_start` and `jz_otp_verify_success`. Auth gates are a classic CRO killer.
4. **Claim-expiry event** — explicit `jz_claim_expired` (hold timed out) with `seller_profile_id`, `drop_id`, time-held. This is the core **liquidity-loss** signal (claimed but never paid); today only `jz_claim_released`/`cancel` exist, expiry-by-timeout may be dark.
5. **Seller group analytics** — register a PostHog `group` of type `seller` (key = `seller_profile_id`, props: category, follower bucket, drops_count). No `group` calls exist today; grouping lets metrics aggregate per-seller/segment so the agent can say *which seller cohorts* have the worst claim-to-paid or sell-through.
6. **Drop dimension completeness** — ensure buyer funnel events consistently carry `drop_id` + `drop_status` (`live`/`scheduled`/`ended`) so per-drop liquidity is measurable.
7. **Server-side purchase capture** — `jz_purchase_confirmed` is client-side + `localStorage`-deduped → undercounts cross-device (audit §1). Add a server-side `posthog-node` capture keyed on the booking/payment webhook so the bottom of funnel is trustworthy; CRO ROI is unmeasurable otherwise.
8. **Canonical funnel + insight definitions** — define a stable buyer funnel and a `claim → paid` liquidity funnel in PostHog so the agent queries named definitions, not ad-hoc HogQL each run (robustness + comparability over time).

---

## Part B — LangGraph agent + harness (separate repo, Outcome 2)

A lightweight **`StateGraph`** with a typed `pydantic` state, a `SqliteSaver` checkpointer (durable cron re-entry), and an append-only audit log. Read-only by default.

### B1. State machine (nodes → edges)
1. `ingest_metrics` — query the **PostHog Query API (HogQL)** for the buyer funnel + seller-liquidity metrics over a window, with segment breakdowns. Optionally read `/v1/analytics/drops/me` scorecards for sell-through/claim-to-paid.
2. `detect_opportunities` — **deterministic** scoring (not LLM): per funnel step, `lost = dropoff_rate × upstream_volume`; per liquidity metric, score sell-through gap, expired-claim rate, claim-to-paid gap, seller-activation drop. Rank.
3. `segment` — break the top leaks by cohort (category, new vs returning, live vs scheduled drop) to locate *where* it's worst.
4. `map_to_surface` *(codebase-aware)* — a hand-authored **funnel-step → component map** (built from the event↔component map already in `posthog-setup-report.md`, e.g. claim→checkout drop ⇒ `item-detail-screen.tsx` + `shipping-checkout-screen.tsx`; auth friction ⇒ `checkout-auth-screen.tsx` / `quick-auth-sheet.tsx`; payment failures ⇒ `payment-return-screen.tsx`; sell-through ⇒ `seller-storefront-screen.tsx` / drop merchandising). LLM reads the actual file to ground a concrete change.
5. `recommend` *(LLM, structured output)* — per opportunity: leak description, **evidence (cited metric names + values)**, root-cause hypothesis, proposed UI/UX change (component/file + specifics), experiment design to validate (variant, goal metric, min sample), expected impact, effort.
6. `guardrails` — **the harness** (see B2). Fail → drop the recommendation or re-ask.
7. `human_approval` — LangGraph `interrupt()` before any issue is opened (MVP).
8. `emit_issues` — open one **GitHub issue** per high-priority recommendation via the GitHub API; **idempotent** (stable fingerprint/label; skip if a matching open issue exists). Attach evidence + proposed change + experiment design.

### B2. Grounding harness / mishap-prevention (explicit requirement)
For a *suggestion* agent the risks are hallucinated data and noise, so the harness is grounding-focused:
- **Structured outputs only** (pydantic/JSON-schema) for every LLM step; required `evidence` fields.
- **Grounding validator**: every cited metric/number must trace to a value present in the ingested dataset (reject fabricated stats); every referenced file path must exist in the repo.
- **Sample-size / confidence gate**: don't surface a "leak" below a min volume — never recommend off noise.
- **Deterministic prioritization** (impact × volume × confidence ÷ effort) computed in code, not LLM-vibed.
- **Dedupe / idempotency** vs already-open GitHub issues (stable title/label fingerprint).
- **Read-only by default**: PostHog read-only personal API key; repo read-only; GitHub token scoped to `issues:write`. No mutation of analytics, code, or seller data.
- **Human-in-the-loop `interrupt()`** before emitting issues.
- **Durable state + audit log** (`SqliteSaver`); **cost/rate caps** on LLM + API calls.

### B3. Connectivity / auth (from exploration)
- **PostHog**: US project (`/ingest` → `us.i.posthog.com`); agent uses a **personal API key** for the Query API (read). Token env: `NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN` (events) + a new personal key (queries).
- **Repo**: read locally from a checkout (the agent runs with the repo available) or via GitHub contents API.
- **GitHub**: token scoped to issues on `jhaazi-frontend`.
- **Jhaazi API** (optional, liquidity scorecards): `GET /v1/analytics/drops/me` etc. with `Authorization: Bearer` — but most signal is in PostHog; MVP can lean on PostHog only.

---

## MVP cut (~2–4h, buildable by coding agents)

**Agent repo (separate):** the `StateGraph` `ingest_metrics → detect_opportunities → map_to_surface → recommend → guardrails → human_approval → emit_issues`, scoped to the **top 3 buyer-funnel leaks + top 2 liquidity leaks**. Hand-authored funnel→component map. Two canonical PostHog funnels (buyer; `claim → paid`). Runs on **existing events** — no frontend change needed to run. Human approval = terminal confirm; dry-run prints issues before opening.

**This repo (optional, if time):** land the two highest-value instrumentation fixes — A1 (name-drift/double-fire) and A2 (`conflict_reason` on `jz_claim_conflict`) — so the next agent run reads cleaner data.

**Deliberately deferred from MVP:** server-side purchase capture, claim-expiry event, seller group analytics, scheduled autonomous runs, Slack digest, impact attribution.

---

## Phased scaling

- **Phase 0 (MVP):** read-only advisor, top-5 buyer+liquidity opportunities, GitHub issues, human-gated, PostHog-only signal.
- **Phase 1:** land Part A instrumentation (drop-off reasons, `jz_claim_expired`, server-side purchase, seller group) → richer, segment-level recommendations.
- **Phase 2:** experiment-design output becomes *runnable* — recommendations hand off to PostHog Experiments (human-launched); track which shipped recs moved the metric (**impact attribution**), closing the learn loop.
- **Phase 3:** scheduled autonomous runs (weekly cron) with **regression detection** (vs last week), auto-prioritized backlog, Slack digest; optional seller-facing "optimize your storefront" tips.
- **Phase 4:** closed loop — recommend → experiment → measure → learn a prior over what works; cross-seller/cohort meta-insights feeding generation.

---

## Verification

**Agent (separate repo):**
- Unit-test the deterministic scoring/prioritization; the **grounding validator** (rejects a fabricated metric and a nonexistent file path); the **dedupe** (skips an already-open issue).
- **Dry-run**: agent ingests real PostHog (or a fixture), produces schema-valid recommendations, **stops at `human_approval`**, writes nothing.
- Approve once → confirm idempotent GitHub issue creation (re-run does not duplicate).
- **Spot-check one recommendation end-to-end**: the cited metric matches a PostHog query you run manually; the referenced component/file exists; the proposed change + experiment design are sensible.

**This repo (if instrumentation fixes land):**
- `npm run typecheck` + `npm run lint`; confirm the funnel events now join cleanly (no `submit`/`submitted` split) and `jz_claim_conflict` carries `conflict_reason` in PostHog live events.
- Existing Playwright storefront/checkout smoke still passes.

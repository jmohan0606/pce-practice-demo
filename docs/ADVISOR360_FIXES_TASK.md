# Copilot Task — Advisor 360: 3 Fixes (Anomaly rename + Transactions drill-down + Personalized Coaching)

## HOW TO RUN THIS (read first — same discipline as prior tasks)
- Run in Copilot **agent mode**. Review the diff before "Keep All".
- **PROGRESS TRACKING:** Copilot sometimes hits a max-request / tool-call limit mid-task.
  Maintain a checklist file **ADVISOR360_FIXES_PROGRESS.md**: record each step as NOT
  STARTED / IN PROGRESS / DONE, update continuously, commit after each completed step.
  **If you hit a limit or stop, write exactly where you stopped and the next step to resume
  in that file — do NOT restart from scratch and do NOT leave a half-edited file without a
  note.** A ready checklist is at the bottom of this doc.
- **Back up each file before editing it.**
- **ADDITIVE / MINIMAL-CHANGE ONLY.** Do not change model logic. Do not change any existing
  endpoint's response shape except where this doc explicitly says to ADD a field. Do not
  touch unrelated cards or pages. If anything is ambiguous, **STOP and ask** rather than
  guessing.
- The user cannot share screenshots. Your own in-session verification is the proof — observe
  that the app boots, pages render for advisors WITH and WITHOUT flags, nothing regresses —
  and record what you observed in the progress file.
- The three fixes are independent — if one is blocked, do the others and flag the blocked one.

## FILES LIKELY INVOLVED
- `frontend/components/advisor360/advisor360-workspace.tsx` (all 3 fixes touch this)
- `frontend/components/patterns/ai-coaching-card.tsx` (Fix 3 display, if needed)
- `app/ai/insights/structured_view.py` (Fix 3 backend — the coaching card builder)
- `app/ai/insights/insight_generation_engine.py` (Fix 3 — where action steps originate)
- A transactions query/endpoint for Fix 2 (see Fix 2 — reuse existing where possible)
- Progress: `ADVISOR360_FIXES_PROGRESS.md` (create + maintain)

## LLM HELPER (reuse the app's existing pattern, e.g. app/scope/insight.py)
```python
from app.llm.client import get_llm_client, LLMClientError
text = get_llm_client().generate(prompt, {"facts": <dict>})   # returns str
```
ALWAYS wrap LLM calls in try/except (catch LLMClientError and Exception); on failure, fall
back to the deterministic value. The LLM must NEVER break an endpoint or the page.

---

# FIX 1 — Rename the anomaly card (trivial)
Rename the "Activity Pattern Review" card heading to **"Anomaly Detected · Activity Pattern
Review"**.
- Frontend: in `advisor360-workspace.tsx`, the card currently titled "Activity Pattern
  Review" (the block gated by `review?.available && review.flagged.length > 0`). Change the
  `<h2>` text to "Anomaly Detected · Activity Pattern Review".
- Keep everything else about that card the same (styling, chip, disclaimer).
- (Optional: if the label also appears in `app/ai/insights/structured_view.py` or a backend
  label, update for consistency — but the visible heading is the requirement.)

---

# FIX 2 — Household transactions drill-down from the anomaly card

## Goal
From the anomaly card's "Where to check", let the user open a **transactions view for the
flagged household**, showing recent transactions with the **anomaly-contributing ones
highlighted and labeled by which signal they triggered**, flagged ones surfaced first,
paginated.

## Data — it already exists (do NOT build a new data pipeline)
- Vertex `phx_dm_revenue_transaction` has: `transaction_id`, `transaction_date` (DATETIME),
  `revenue_amount` (DOUBLE), `transaction_type` (STRING), `quantity`, `gross_amount`,
  `source_system`.
- Edge `phx_dm_transaction_for_household` (reverse `rev_phx_dm_transaction_for_household`)
  connects transactions to a household.
- An existing query `GQ-012_get_account_holdings_and_activity` already returns `transactions`
  for an account via `rev_phx_dm_transaction_for_account`.

### Backend approach (reuse first)
1. FIRST check whether a household-level transactions path already exists (an endpoint,
   service method, or query that returns transactions for a household). If one exists, reuse it.
2. If NOT, add a MINIMAL read endpoint, e.g. `GET /predictions/household-transactions/{household_id}`
   (or under an existing router that fits), that returns recent transactions for that
   household: use the `phx_dm_transaction_for_household` edge (or reuse GQ-012 per the
   household's accounts and aggregate). Return rows with: transaction_id, transaction_date,
   revenue_amount, transaction_type, gross_amount, quantity, source_system.
   - Default window: transactions in the **last 90 days** relative to the latest data month;
     if that yields too few, fall back to the most recent ~30. Support simple pagination
     (page/size, default size 15). Route reads through the existing graph client (same
     get_graph_client/run_query pattern used elsewhere) — do NOT read .store directly.
3. HIGHLIGHT LOGIC (the valuable part): the anomaly model flags a household on aggregate
   SIGNALS (recent_rev_zmax, largest_tx_vs_median, tx_frequency_ratio, slope_break,
   recency_vs_own_gap, single_tx_share) — not on transaction ids. Map each flagged signal to
   the transaction(s) that most explain it, deterministically from the real rows:
     - largest_tx_vs_median / single_tx_share  -> the single largest-amount recent transaction
     - recent_rev_zmax                          -> the highest-revenue transaction(s) in the recent spike window
     - slope_break                              -> transaction(s) around the sharpest change in the recent trend
     - tx_frequency_ratio / recency_vs_own_gap  -> the most recent transaction (recency-related)
   Add, to the transactions endpoint response, a per-transaction `anomaly_flag` (bool) and
   `anomaly_signal` (the signal name it explains, or null). The highlight set is derived from
   the household's flagged signals (available via /predictions/activity-review/{advisor}).
   If the mapping is uncertain for a signal, highlight the single most-extreme recent
   transaction rather than guessing many.

### Frontend
1. In the anomaly card, make "Where to check" an actionable link/button per flagged
   household (e.g. "View transactions") that opens the transactions view for that
   household_id (a modal/drawer, or a new tab/section on the page — pick the cleanest that
   fits the existing design; a modal/drawer is preferred so it doesn't navigate away).
2. The transactions view shows a paginated table: Date, Type, Amount (revenue_amount),
   Gross, Product/Source as available. Columns consistent with the page's tokens.
3. Flagged transactions: render FIRST (pin flagged rows to the top of the first page),
   visually highlighted (amber row + a small "⚠ flagged: <signal plain-English>" tag using
   the signal→plain-English map from the anomaly work). Non-flagged rows follow, paginated.
4. Header line: household id (+ name if available) and "Showing recent transactions; AI-
   flagged items are highlighted." Keep the anomaly disclaimer visible nearby.
5. Guard all fetches with .catch so a failure hides the view cleanly (no crash).

---

# FIX 3 — Personalized AI Coaching Card (fix "same for everyone" + wow factor)

## The bug (confirmed in code)
In `app/ai/insights/structured_view.py`, the coaching card's `action_steps` =
`plan.next_best_actions[:4]`. In `app/ai/insights/insight_generation_engine.py` the plan's
`next_best_actions` are gathered generically from insight cards' `recommended_actions`, so
they come out largely the same across advisors — and the SAME card is shown on both Advisor
360 and the Executive Dashboard. The `recommendation` and `shoutout` already vary somewhat;
the `action_steps` are the weak, non-personalized part.

## Goal (true wow)
Make `action_steps` GENUINELY PERSONALIZED and specific to THIS advisor's real data —
referencing their actual households, numbers, gaps, and opportunities — so two different
advisors get clearly different, data-grounded coaching, and the Executive Dashboard shows a
correctly scope-appropriate card.

## Backend (app/ai/insights/structured_view.py — the structured_insight_coaching path)
For ADVISOR scope, build personalized action steps from the advisor's REAL signals, which are
already available via these endpoints/services (call the underlying services directly to
avoid HTTP round-trips if easy; otherwise reuse their logic):
- Household churn: /predictions/household-churn/{advisor}  (elevated-risk households)
- Next-best-product: /predictions/next-best-product/{advisor}  (top cross-sell + propensity)
- Activity anomaly: /predictions/activity-review/{advisor}  (flagged households)
- Opportunities: /opportunities/detect/{advisor}  (open opportunities, pipeline)
- AGP status: /agp/track-status/{advisor} and /agp/kpi-scorecard/{advisor}  (goal attainment, gaps)
- Recommendations: /recommendations/advisor/{advisor}  (open recommendations)

Compose 3-5 SPECIFIC action steps, each grounded in a real datum, e.g.:
  "Schedule a managed-account review for <household name/id> ($<AUM>, no managed account) —
   <peer %>% of similar households hold one"
  "Clear <N> overdue CRM follow-ups aging >30 days — oldest first"
  "AGP goal at <X>% attainment with <N> months left — prioritize the $<pipeline> open pipeline"
Generate the final wording with the LLM (get_llm_client().generate), grounded ONLY in the
real facts you assembled (pass them as the facts dict), inventing NO figures — mirror the
grounded-prompt style of app/scope/insight.py. 
- DETERMINISTIC FALLBACK: if the LLM fails, fall back to a deterministic personalized list
  built directly from the real facts (e.g. formatted strings from the churn/nbp/opportunity
  data) — NOT the old generic plan.next_best_actions. Only if NO real signals are available,
  fall back to the existing plan.next_best_actions as a last resort.
- Keep `recommendation`, `shoutout`, `guideline_basis` working as today (additive change to
  how action_steps is produced). Do not change the response SHAPE — action_steps stays a
  list[str]; it just becomes personalized.
- For NON-advisor scope (Executive Dashboard / firm / division): ensure the card is built
  from that scope's real rollup data (so it's scope-appropriate, not a copy of one advisor's).
  If personalization isn't feasible at rollup scope, make the steps clearly scope-level
  (e.g. "N advisors below peer managed-mix — prioritize coaching") rather than identical
  advisor-level text.

## Frontend
- The existing `ai-coaching-card.tsx` already renders `action_steps` as a list — likely no
  change needed beyond confirming it displays the new personalized steps. Add an "✦ AI
  Generated" chip if not already present. Verify both Advisor 360 and the Executive Dashboard
  render correctly-scoped, non-identical cards.

---

# VERIFICATION (record observations in ADVISOR360_FIXES_PROGRESS.md)
- Backend imports + app boots; no regressions.
- FIX 1: the card heading reads "Anomaly Detected · Activity Pattern Review".
- FIX 2: for an advisor WITH a flagged household, the "View transactions" link opens the
  transactions view; flagged transactions appear first, highlighted + labeled by signal;
  pagination works; a household with no transactions / a failure hides cleanly.
- FIX 3: two DIFFERENT advisors show clearly DIFFERENT, data-grounded action steps (not
  identical); the Executive Dashboard card is scope-appropriate, not a copy of one advisor;
  with the LLM unavailable, the deterministic personalized fallback still differs per advisor
  and nothing breaks.
- Advisor 360 still renders for an advisor with NO flags (cards hide correctly, no crash).

# RULES RECAP
- Additive/minimal only. No model-logic changes. No .store direct reads for the new
  transactions path (use the graph client / run_query). Everything degrades gracefully.
- Use REAL cdao/Claude via get_llm_client(). Match existing design tokens (colors.*, type.*).
- If ambiguous, STOP and ask. Record per-file changes + observations in the progress file.

# ADVISOR360_FIXES_PROGRESS.md — checklist (maintain; resume point if interrupted)
- [ ] Back up all files to be edited
- [ ] FIX 1: rename anomaly card heading
- [ ] FIX 2 backend: transactions endpoint (reuse or minimal new) + highlight mapping + anomaly_flag/anomaly_signal fields
- [ ] FIX 2 frontend: "View transactions" link + paginated table + flagged-first highlighting
- [ ] FIX 3 backend: personalized action_steps from real signals (LLM + deterministic fallback), advisor + scope
- [ ] FIX 3 frontend: confirm card renders personalized steps + AI chip (Advisor360 + Exec Dashboard)
- [ ] VERIFY all (boots; with/without flags; two advisors differ; LLM-fail fallback; no regressions)
- [ ] Record per-file change summary
- (If interrupted: write the exact next step to resume here before stopping.)

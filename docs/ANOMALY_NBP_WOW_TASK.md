# Copilot Task — Advisor 360 "Wow-Factor" Cards (Anomaly + Next-Best-Product)

## HOW TO RUN THIS (read first)
- Run in Copilot **agent mode**. Review the diff before "Keep All".
- **PROGRESS TRACKING (important):** Copilot sometimes hits a max-request / tool-call
  limit mid-task. To survive that, maintain a checklist file **WOW_TASK_PROGRESS.md**:
  record each step as NOT STARTED / IN PROGRESS / DONE as you go, update it continuously,
  and commit after each completed step. **If you hit a limit or stop, write exactly where
  you stopped and the next step to resume in WOW_TASK_PROGRESS.md so you can pick up from
  there — do NOT restart from scratch and do NOT leave a half-edited file without noting it.**
- Back up each file before editing it.
- **ADDITIVE ONLY.** Do not change model logic, existing endpoint behavior (beyond adding
  the one new optional field described), or any other card. If anything is ambiguous, STOP
  and ask rather than guessing.
- Note: the user cannot share screenshots externally — so your own verification in-session
  (app boots, pages render with/without flags, failure path falls back) is the proof;
  describe what you observed in WOW_TASK_PROGRESS.md.

---

## GOAL
Two additive UI enhancements on Advisor 360, each with a deterministic layer PLUS an
optional LLM-generated narrative that degrades gracefully (so a demo-time LLM hiccup can
never break the page):
1. Make the existing **Activity Pattern Review (anomaly)** card meaningful + actionable.
2. Add a new **Next-Best-Product** card (it currently has NO UI, though the endpoint works).

This must NOT break anything that currently works. The app must still boot, Advisor 360
must still render for ALL advisors (including those with no flags), nothing existing may
regress.

## FILES INVOLVED (only these)
- Backend: `app/ml/anomaly.py`, `app/ml/next_best_product.py`
- Frontend: `frontend/components/advisor360/advisor360-workspace.tsx`
- Progress: `WOW_TASK_PROGRESS.md` (create + maintain)

## LLM HELPER TO REUSE (already used elsewhere, e.g. `app/scope/insight.py`)
```python
from app.llm.client import get_llm_client, LLMClientError
text = get_llm_client().generate(prompt, {"facts": <dict>})   # returns str
```
ALWAYS wrap LLM calls in try/except (catch `LLMClientError` and `Exception`); on any
failure set the narrative field to `None`. The LLM must NEVER break the endpoint.

---

## PART 1 — ANOMALY (Activity Pattern Review) richer card

### Backend (`app/ml/anomaly.py`, in `activity_review()`)
The function already returns, per flagged household: `household_id`, `review_reason`,
`top_signals [{signal, value}]`, `features`, plus top-level `disclaimer` +
`false_positive_note`. ADD, per flagged household, a new field `ai_narrative`:
- Build a facts dict with: `household_id` (and household name if resolvable via existing
  data access — if not, just the id), and the `top_signals` with their plain-English
  meaning (map below), noting this is **own-history-relative (NOT peer/wealth)**.
- Prompt the LLM for a 2-3 sentence plain-English explanation of WHAT the model detected
  and WHY it merits a review, grounded ONLY in the given signals, inventing NO figures.
  Mirror the grounded-prompt style of `app/scope/insight.py`.
- Set `household["ai_narrative"] = <generated text>`, or `None` on any failure.
- Purely additive — keep every existing field exactly as-is.

### Signal → {what, check, where} map
(Used by BOTH the backend prompt context AND the frontend fallback; add to the frontend
as a const dictionary.)

| signal | what | check | where |
|---|---|---|---|
| recent_rev_zmax | Unusually large recent revenue spike vs. own history | Confirm the spike is expected (planned event vs. error) | Household → Transactions (recent) |
| largest_tx_vs_median | One transaction far larger than their typical | Verify the outlier transaction is legitimate | Household → Transactions (sort by amount) |
| tx_frequency_ratio | Change in how often they transact | Check for a shift in client engagement/behavior | Household → Activity timeline |
| slope_break | Sudden break in their revenue trend | Investigate what changed around the break point | Household → Revenue trend |
| recency_vs_own_gap | Unusual gap since last activity | Re-engage — possible disengagement/attrition risk | Household → Last contact / CRM |
| single_tx_share | One transaction dominating the period | Confirm concentration isn't masking normal flow | Household → Transaction mix |

### Frontend (`advisor360-workspace.tsx`)
Enhance the EXISTING "Activity Pattern Review" card block (gated by
`review?.available && review.flagged.length > 0`). Keep the same amber styling, the
"{n} to review" chip, the disclaimer, and false_positive_note. For each flagged household,
replace the single cryptic line with a richer card showing:
- Header: `household_id` (+ name if present) and, IF `ai_narrative` present, an
  "✦ AI Generated" chip.
- "What the model detected": render `f.ai_narrative` if present; ELSE the deterministic
  `what` text from the map (keyed by the highest-|value| signal in `f.top_signals`).
- "What to check": the `check` text for that primary signal.
- "Where to check": the `where` text for that primary signal.
- Small/muted line: the raw `top_signals` (signal + value), as today.

Update the TS type for `review.flagged[]` to include optional
`ai_narrative?: string | null`. Keep the existing `.catch(() => setReview(null))` so a
failure just hides the card (no crash).

---

## PART 2 — NEXT-BEST-PRODUCT new card (currently has NO UI)

The endpoint `GET /predictions/next-best-product/{advisor}` already works and returns:
```
{ available, advisor_id, model, method, served, caveat, households: [
  { household_id, segment, held_categories: string[], next_best: [
    { category_id, category_name, propensity, peer_adoption, overall_adoption, reason }
  ] } ] }
```
(households are pre-sorted strongest-opportunity first.)

### Backend (`app/ml/next_best_product.py`, in `next_best_product()`)
ADD an optional `ai_narrative` string on the **TOP-LEVEL** result (not per household) — a
2-3 sentence plain-English summary of the single strongest cross-sell opportunity across
the book, grounded ONLY in the real data (the top household's top `next_best`:
`category_name`, `propensity`, `peer_adoption`, `segment`, and what they already hold).
Mirror the `app/scope/insight.py` grounded-prompt style. Wrap in try/except; set to `None`
on failure. Additive only — keep all existing fields.

### Frontend (`advisor360-workspace.tsx`)
1. Add a new fetch mirroring the existing pattern EXACTLY:
   ```
   const [nbp, setNbp] = useState<NbpResponse | null>(null);
   // in load(): apiClient.get<NbpResponse>(`/predictions/next-best-product/${advisorId}`)
   //   .then(setNbp).catch(() => setNbp(null));
   ```
   (define `NbpResponse` to match the structure above, including optional
   `ai_narrative?: string | null`).
2. Add a NEW card (place near the churn/anomaly cards, consistent styling/tokens) gated by
   `nbp?.available && nbp.households.length > 0`, showing:
   - Title "Next Best Product" + an "✦ AI Generated" chip if `nbp.ai_narrative` present.
   - If `nbp.ai_narrative` present: show it as the lead summary line.
   - A short list of the top few households: `household_id` (+segment), and their #1
     `next_best` as "Recommend: {category_name} · {round(propensity*100)}% propensity" with
     the `reason` text beneath (muted).
   - The top-level `caveat` as a small muted footnote.
   - If failure/empty, render nothing (card simply absent).

---

## RULES / VERIFICATION
- **ADDITIVE ONLY.** Do not alter model logic, existing endpoint responses (beyond adding
  the new optional `ai_narrative` field), or any other card.
- Both `ai_narrative` additions MUST degrade gracefully (`None` on any LLM failure), so the
  cards always render their deterministic version and the page never breaks.
- Use REAL cdao/Claude via `get_llm_client()` (the same adapter the app uses).
- Match the page's existing design tokens (`colors.*`, `type.*`), consistent with the
  churn/anomaly/referral cards.
- VERIFY (and record observations in WOW_TASK_PROGRESS.md):
  (a) backend imports + app boots;
  (b) Advisor 360 renders for an advisor WITH flagged households AND one WITHOUT (no crash,
      cards appear/hide correctly);
  (c) next-best-product card renders with real propensity data;
  (d) with the LLM available, `ai_narrative` shows; simulate an LLM failure and confirm the
      deterministic fallback shows and nothing breaks.
- Report exactly what you changed per file in WOW_TASK_PROGRESS.md. If anything is
  ambiguous, STOP and ask rather than guessing.

## WOW_TASK_PROGRESS.md — maintain this checklist (resume point if interrupted)
- [ ] Back up the 3 files
- [ ] PART 1 backend: anomaly.py ai_narrative added + guarded
- [ ] PART 1 frontend: anomaly card enhanced + signal map + type updated
- [ ] PART 2 backend: next_best_product.py ai_narrative added + guarded
- [ ] PART 2 frontend: NbpResponse type + fetch + new card
- [ ] Verify (a) boots (b) renders with/without flags (c) nbp renders (d) LLM-fail fallback
- [ ] Record per-file change summary
- (If interrupted: write the exact next step to resume here before stopping.)

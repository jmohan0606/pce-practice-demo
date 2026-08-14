# Round C (docs/rules) — COMPLETE (docs/spec/ROUND_C_DOCS_RULES_SPEC.md)

Documents and Rules Management: rule scoping/provenance/lifecycle (main thread,
tasks 1–2), document categories + rule list UI (Subagent A, tasks 3–4), manual
authoring + retry (Subagent B, tasks 5–6), Rule Versions screen (Subagent C,
task 7) — dispatched concurrently with strict file ownership, re-verified by
execution in the main thread, committed per task. Task 8 ran every check live
against the servers (headless-chromium for the visual ones).

Session LLM cost ≈ **$3.30** of the $10 ceiling (trace-measured: $4.82 today minus A2B's $1.52) (three seed compiles + one
manual compile + one retry ≈ $0.23; extraction of two small PLAN .txt docs +
conflict audit ≈ $0.35; Subagent B's compiles $0.17; one advisor run $0.10; the
21-run insight regeneration onto RSV_v7 ≈ $2.5).

## The checks — what was actually observed

```
[ 1] NEW_BILLING edited to applies_to=ADVISOR/V000002, published (RSV_v4):
     practice run  → skipped=True  "rule applies to advisor V000002 only — not applicable
                                    to a practice-level evaluation"
     V000009 run   → skipped=True  "…this evaluation is for V000009"
     V000002 run   → evaluated=True matched=7          (never an error anywhere)
[ 2] applies_to vs scopes documented (DECISIONS.md 2026-08-14): the probe rule above IS
     practice-evaluable by scopes yet ADVISOR-applied — both fields serialize on every rule
[ 3] browser: v0 expansion shows 6× "TECH TEAM WRITTEN" chips; v7 shows 2× "DOCUMENT
     DERIVED" and 1× "MANUALLY WRITTEN-PRACTICE"; documents page shows "MANUALLY
     WRITTEN-TECH" on the seeded examples — all four tags rendered as chips
[ 4] app/shared/fee_schedule.py: STANDARD_MANAGED_FEE_BPS=145.0 + citations (FAQ p.13,
     PCA p.3, SAG p.4); importers: generate_mock_data, make_test_raw_extracts,
     app/rules/service (seed example); every remaining "115" is inside labelled
     worked-example prose (sample-PDF §3.2, make_test_pdf) — no constant, by design
[ 5] RETAINED_ACCOUNT deactivated → RSV_v5: new-version evaluation skips it
     ("rule is inactive — comp team validating retained-count methodology");
     RSV_v0 still queryable (status PUBLISHED, active true THERE); the stored A2B
     aggregate run (RSV_v0, 5 findings) served unchanged
[ 6] the deactivation minted RSV_v5 recording active_changed_by=janagaraj-mohan,
     active_changed_at=2026-08-14 19:00:57, reason on the rule AND in the version notes;
     an empty reason is refused: "a reason is required to deactivate a rule …"
[ 7] POST /api/rules/delete on R_RETAINED_ACCOUNT_RSV_v4 → 400 "…is approved (PUBLISHED
     in RSV_v4) — approved rules can never be deleted, only superseded or deactivated;
     nothing was deleted" — refused AT THE STORE (all-or-nothing; a mixed selection
     deletes nothing, proven in the Task-2 store probe)
[ 8] browser: scrap draft + published Lost Account selected → "Delete Selected" DISABLED
     with the note "The selection includes approved rules — approved rules can never be
     deleted, only superseded or deactivated, so Delete is disabled."; deselect approved →
     enabled; confirm modal lists exactly what goes; after delete the scrap row is gone
     from the manager and Lost Account remains
[ 9] all six categories uploaded (PLAN/GUIDANCE/PLAYBOOK/TRAINING/FAQ/OTHER, each
     indexed); extract-rules on TRAINING → 400 "TRAINING documents are indexed and
     searchable but never produce rules. Only PLAN and FAQ documents feed the Rule
     Extractor."; unknown category → 400 naming the valid set; PATCH →PLAN flips
     extraction_offered=True and extract-rules then runs (Subagent A's isolated 26/26
     re-proven by main-thread TestClient probe)
[10] .txt chunks with page_no=1 and heading-derived section_path ("Fee Schedule Change
     2026"); .csv = ONE has_table=true markdown chunk; embedding search for the 125 bps
     sentence returns the .txt at sim 0.84
[11] the one-line 145→125 .txt (PLAN) extracted → FEE_SCHEDULE_CHANGE_2026 draft;
     compiled → honest NEEDS_DATA (needs the September effective date) WITH its drafted
     population stored; Conflict Auditor output, verbatim:
       conflict_type: OVERLAPPING_POPULATION_TRIGGER
       new_rule: DRAFT_FEE_SCHEDULE_CHANGE_2026_0013 → existing: R_STANDARD_FEE_RATE_RSV_v7
       proposed_resolution: SUPERSEDE   (llm_reviewed: true)
       reasoning: "New rule has explicit effective date (1 September 2026) that is later
         than existing rule's creation date (2026-08-14). New rule represents a schedule
         rate change (145 bps → 125 bps) and directly supersedes the constant 145 bps
         calculation in the existing rule. Both rules target the same population
         (is_managed = true) at account grain with driver_tag 'Fee Rate'. The new rule's
         effective date wins per precedence order. Recommend retiring or versioning the
         existing rule and activating the new rule with temporal gating on the September
         2026 effective date."
       new_citation:      fee_schedule_change_2026.txt p.1 "Fee Schedule Change 2026"
       existing_citation: plan_addendum_2026.txt p.1 "Standard Fee Schedule"
       note: "proposals only — nothing was applied; a human approves"
[12] browser: "5 extracted · 3 compiled · 0 need a value · 2 need data we don't have";
     expanding the needs-data bucket shows the per-rule reason, e.g. FEE_SCHEDULE_VARIANCE
     "…needs aggregation to compute the book-wide average (sum of credited_amt / sum of
     end_balance, annualized) and compare it to 145 bps…"
[13] POST /api/rules/manual generate_query=true ("Large Trade Concentration Watch",
     MANUALLY_WRITTEN_TECH) → COMPILED with plan, approved=None — reviewable before
     approval; browser shows it in "Compiled — Awaiting Approval" with the full plan JSON
[14] the NL rule ("September Campaign Context", MANUALLY_WRITTEN_PRACTICE,
     generate_query=false) stored with plan=None, compile_error=None; evaluator skips it
     "guidance only — no plan by design; the statement is injected into the Insights
     Miner's context instead of being evaluated"; miner opening carries the labelled
     MANUAL GUIDANCE block (check_manual_rules 17/17); browser shows "Guidance only,
     not computed"
[15] the three seeded examples exist as MANUALLY_WRITTEN_TECH drafts and compiled LIVE:
     BILLABLE_DAYS → COMPILED (honest simplification, no day_of_month() invented);
     QUARTERLY_BILLING_CYCLE → COMPILED; FEE_SCHEDULE_VARIANCE → NEEDS_DATA naming the
     ratio-of-aggregates gap; all render editable on the documents page
[15a] the NL rule published (RSV_v1) → promote (reason recorded) minted RSV_v2 with a
     compiled plan → demote (reason recorded) minted RSV_v3 back to guidance —
     version notes carry both reasons verbatim
[16] recompile with note "try measuring at RPG level rather than account" on
     FEE_SCHEDULE_VARIANCE: attempt 1 KEPT (original NEEDS_DATA), attempt 2 added —
     honestly NEEDS_DATA again, naming the operator's RPG request and why the schema
     cannot link it; browser shows both attempts side by side; 5 rule_compile|<key>
     rows in the trace with per-run cost (retries ride the same turn-log path)
[17] browser: v0 expands ("View 6 rules") to full rule detail — statement, worked
     example, chips, plan; 6 Edit buttons; editing mints a new version (RSV_v4/v5/v6
     all born from edits this session)
[18] browser: ticking v6+v7 renders the comparison — "2 ADDED / 0 REMOVED / 0 MODIFIED /
     7 UNCHANGED" naming Concentration Account Revenue Threshold and Standard Managed
     Fee Schedule Rate as the additions (bookkeeping churn ignored, zero false positives)
[19] "Rules That Never Fired" renders: RETAINED_ACCOUNT (deactivated — never evaluated)
     and SEPTEMBER_CAMPAIGN_CONTEXT (guidance-only), "Checked 3 months across 22
     advisors plus the practice scope"
[20] plan_addendum_2026.txt uploaded as PLAN → extracted 2 rules WITH citations →
     compiled → approved → published (RSV_v7) → CONCENTRATION_ACCOUNT_THRESHOLD fires
     (187 practice-wide / 13 for V000002) → insights regenerated → the dashboard
     AI-Insights bullet, verbatim from the rendered DOM:
       "Concentration Account Revenue Threshold — 187 match(es) in 202605 —
        CONCENTRATION REVIEW  Rule CONCENTRATION_ACCOUNT_THRESHOLD fired for 187
        account(s) in 202605. Any account that produces more than 1,000 dollars of
        credited revenue in a single month is classified as a concentration account and
        must be flagged for review by the practice supervisor.
        Rule: Concentration Account Revenue Threshold · plan_addendum_2026.txt · p. 1 ·
        Account Concentration Review"
     — the first document→rule→insight→citation chain ever shown end to end in this app
     (closing Round A2B's carried observation #1). The Standard Fee Schedule bullet cites
     the same document's p.1 "Standard Fee Schedule" section.
```

## Found & fixed during verification

1. **Extractor citations carried no `document_name`** — the UI's citation line
   fell back to "No document citation"/blank on document-derived rules: the
   exact chain check 20 exists to prove, broken at the last hop. Both citation
   serializers (`_rule_citation` in the insights router; `_serialize` in the
   rules router) now resolve the name from the rule's `document_id` via the
   knowledge catalog. Found only by rendering the page — the API-level data
   looked complete until the component's contract was checked.
2. **Conflict audit on an uncompiled draft cannot see populations** — the
   detector is deterministic over compiled plans, so the 125 bps draft produced
   zero conflicts until compiled. Not changed (conservative-by-design; drafts
   compile before publish anyway) but the flow is now documented: extract →
   compile → audit. The compile itself lands honest NEEDS_DATA (September
   effective date not in the data) while still storing the drafted population —
   which is what the auditor overlaps on.

## Verification suites (final)

```
verify_round_a 25/25 · verify_round_b 19/19 · verify_round_c 13/13 ·
verify_round_e 8/8 · verify_round_h 9/9 · verify_round_a1 17/17
check_manual_rules 17/17 · check_flags 8/8
npm run build: passes — 8 routes (documents 8.71 kB, rules 7.85 kB)
```

B3-13 re-pinned (v0 all TECH_TEAM_WRITTEN — Round C rename). No other pin
changes anywhere.

## Deviations / notes

- **All six v0 rules are TECH_TEAM_WRITTEN** (spec 1.2 "rename the v0 seed's
  existing tag" applied to the ex-OPERATOR_SPECIFIED five too — the tag's own
  definition covers them; DECISIONS.md).
- **Recompile is draft-pool only** — a version-bound rule 400s ("edit the rule
  to mint a draft, then retry on the draft"); immutability precedent.
- **Deactivate/Reactivate is offered on the current version's rows only** in
  the UI (minting from a stale superseded row would resurrect old content);
  Edit is available on every version's rows.
- **The never-fired card lists the guidance-only rule** as "never evaluated" —
  technically true (it is never evaluated BY DESIGN); a "guidance only" note on
  that card is a candidate polish item.
- **reporter_sources/coach treat every non-GUIDANCE category as PLAN search
  material** (found by Subagent A) — PLAYBOOK/TRAINING/OTHER now count as PLAN
  sources for reporter/coach retrieval. They are still never extraction inputs.
  Left as-is this round; deserves an operator ruling (carried observation).
- The Round-C demo trail deliberately lives in the served store: RSV_v0…v7 with
  the full deactivate/promote/demote/scope/publish history, the 21-run insight
  batch regenerated on RSV_v7, and the NEEDS_DATA drafts (incl. the 125 bps
  conflict draft, deliberately unpublished — the auditor proposes, a human
  approves).

Servers: uvicorn :8002 healthy (RSV_v7 serving, 22 stored insight runs) ·
next :3002 (forwarded-URL build). Public visibility still needs the Ports panel
(gh token lacks the codespace scope — carried since Round C-fix).

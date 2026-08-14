"use client";

/** Round C (docs/rules) task 4 — rule list management on Documents & Rules.
 *
 * CONTRACT (main-thread authored): Subagent A fully implements this component
 * IN PLACE (it owns this file); Subagent B mounts it on
 * frontend/app/documents/page.tsx and never edits it. Self-contained: fetches
 * its own data (drafts + latest version via lib/api getRulesDetailed,
 * extraction summary; mutations via lib/rulesApi deleteRules/setRuleActive).
 *
 * Required behaviour (spec task 4): multi-select checkboxes on unapproved
 * rules with select-all per status group; Delete Selected with a confirm
 * listing what goes (disabled on a mixed selection); Deactivate/Reactivate on
 * approved rules via ReasonModal (mandatory reason); filters by status,
 * provenance tag, scope and severity; extraction counts line
 * ("38 extracted · 22 compiled · 4 need a value · 12 need data we don't
 * have") with each bucket expandable to its per-rule reasons.
 */
export default function RuleListManager() {
  // Placeholder shell — Subagent A replaces this file with the full
  // implementation. Rendering nothing (not fake content) until then.
  return null;
}

"""Round F2 task 2 — CRM stage grouping, the ONE place it is defined.

The extract's `stagename` is source data and stored verbatim on
`phx_dm_pce_opportunity.stage_name`. `stage_group` is DERIVED here as a
funnel position: EARLY | MID | LATE | CLOSING.

HONESTY NOTES
- The operator's transcription (docs/spec/CRM_AND_PLAN_FINDINGS.md §1) says
  the extract holds 15 DISTINCT stage values but lists only 14 names — one
  stage name has not been observed. An unmapped stage therefore maps to
  "UNGROUPED" and is COUNTED in build/validation output; it is never guessed
  into a group.
- There is NO Won or Lost stage in the source and none is derived anywhere.
  Outcome hints live only in the free-text comments, which are never parsed
  for outcome keywords by any code path that produces a field or a figure
  (the labelled ai_read interpretation is descriptive text beside the row —
  see spec 2.4).
"""
from __future__ import annotations

STAGE_GROUP_ORDER = ("EARLY", "MID", "LATE", "CLOSING", "UNGROUPED")

STAGE_GROUPS: dict[str, str] = {
    # first contact through qualification
    "Contact Attempted": "EARLY",
    "Contact Made": "EARLY",
    "Opportunity": "EARLY",
    "Opportunity Identified": "EARLY",
    "Qualified Prospect": "EARLY",
    # active engagement
    "Meeting Scheduled": "MID",
    "Meeting Held": "MID",
    "Planning": "MID",
    "Positive Buying Signals": "MID",
    # proposal on the table
    "Proposal": "LATE",
    "Proposal Generated": "LATE",
    "Verbal Commitment": "LATE",
    # money moving / account opening
    "Funding": "CLOSING",
    "Onboarding": "CLOSING",
}


def stage_group_for(stage_name: str) -> str:
    """Stage name -> EARLY|MID|LATE|CLOSING, or "UNGROUPED" for a stage we
    have not seen documented (counted by callers, never guessed)."""
    return STAGE_GROUPS.get((stage_name or "").strip(), "UNGROUPED")


def strip_invalid_advisor_suffix(raw_sid: str) -> tuple[str, bool]:
    """`ownersid__c` -> (advisor_sid, advisor_valid).

    Values like 'I817209_CWM_INVALID' mark invalid advisor references in the
    source. The suffix (everything from the first '_') is stripped into the
    join key; the caller keeps the raw value in advisor_sid_raw and reports
    the invalid count — these rows are never dropped and never silently
    joined as if valid.
    """
    raw_sid = (raw_sid or "").strip()
    if "_" in raw_sid:
        return raw_sid.split("_", 1)[0], False
    return raw_sid, True

"""Round 5 task 4 — the client's job-code → display-name / plan-family mapping.

`DisplayName` is NOT in `fpic_employee_tb` — the client supplied this table
(requirements of 17 Aug 2026) and we maintain it here, in ONE place. The
client's instruction: "maintain the display name but the job_cd filter should
be applied with all the job codes listed" — so this mapping is AUTHORITATIVE
and the source `em_pay_title_txt` is not (four job codes have a blank source
title; that is expected).

An unmapped job code renders as the raw code, never as a guess; its plan
family is blank (unknown), never invented.

The plan family answers the question open since Round 1b: which comp plan
applies to which advisor — PRIVATE_CLIENT → CWM Private Client Advisor Plan,
SELECT_ADVISOR → CWM Select Advisor Group Plan.
"""
from __future__ import annotations

PRIVATE_CLIENT = "PRIVATE_CLIENT"
SELECT_ADVISOR = "SELECT_ADVISOR"

# job_cd -> (DisplayName, plan family) — the client's table, verbatim.
JOB_CODE_MAP: dict[str, tuple[str, str]] = {
    "HK0058": ("WM Private Client Advisor", PRIVATE_CLIENT),
    "HK0059": ("WM Select Advisor - I", SELECT_ADVISOR),
    "HK0176": ("WM Select Advisor Group", SELECT_ADVISOR),
    "HK0183": ("WM Select Advisor - I", SELECT_ADVISOR),
    "HK0184": ("WM Select Advisor - I", SELECT_ADVISOR),
    "HK0185": ("WM Select Advisor - I", SELECT_ADVISOR),
    "HK0186": ("WM Select Advisor Group", SELECT_ADVISOR),
    "HK0187": ("WM Select Advisor Group", SELECT_ADVISOR),
    "HK0188": ("WM Select Advisor Group", SELECT_ADVISOR),
    "HK0280": ("WM Private Client Advisor II", PRIVATE_CLIENT),
    "HK0286": ("PCA Community Advisor", PRIVATE_CLIENT),
    "HK0289": ("Select Advisor Retiree", SELECT_ADVISOR),
}

# The 12 codes are also the cohort's job_cd filter (scripts/build_cohort.py
# carries them verbatim inside the client's query).
COHORT_JOB_CODES: tuple[str, ...] = tuple(sorted(JOB_CODE_MAP))


def job_display_name(job_code: str | None) -> str:
    """DisplayName for a job code. Unmapped -> the RAW code (shown, never
    guessed); blank -> blank (a blank stays blank)."""
    code = str(job_code or "").strip()
    if not code:
        return ""
    entry = JOB_CODE_MAP.get(code)
    return entry[0] if entry else code


def advisor_plan_for(job_code: str | None) -> str:
    """Plan family (PRIVATE_CLIENT | SELECT_ADVISOR) for a job code; blank
    when the code is blank or unmapped — never invented."""
    entry = JOB_CODE_MAP.get(str(job_code or "").strip())
    return entry[1] if entry else ""

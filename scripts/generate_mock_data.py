"""Deterministic mock data generator — Round A task 5.

Generates the full source-loaded data set per SCHEMA_SPEC §1/§3/§5:
  data/vertices/phx_dm_pce_<name>.csv   (16 source vertices)
  data/edges/phx_dm_pce_<edge>.csv      (27 source-derivable edges)
  data/manifest.json                    (row counts per file — ingestion verifies)
  docs/data/cohort_advisors.csv         (cohort + scenario flags)

Scenarios covered (BUILD_PLAN §4.5 / SCHEMA_SPEC §5 cohort selection):
  - accounts opened in Q2 (opened_in_scope)
  - accounts zeroed between months
  - inbound and outbound transfers (incl. non-cohort counterparties)
  - fee reductions above 10% with and WITHOUT a recorded grid_reduction
  - team agreements (shares as fractions)
  - a syndicate one-off (two large STRT allocations, one advisor, May only)
  - an advisor crossing the $4MM NNM threshold (flows, Apr+May only)
  - two boring advisors with nothing dramatic
  - one advisor with a blank name (blank stays blank — never invented)
  - one unmapped product (visible, never dropped)

Deterministic: seeded RNG, no timestamps from the clock.
Run: python3 scripts/generate_mock_data.py
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.revenue.aggregation import build_monthly_revenue  # noqa: E402
from app.revenue.products import (  # noqa: E402
    PRODUCT_GROUPS,
    product_group_rows,
    resolve_product,
    revenue_class_rows,
)
from app.shared.ids import normalize_account_key  # noqa: E402

RNG = random.Random(42)

DATA = ROOT / "data"
VDIR = DATA / "vertices"
EDIR = DATA / "edges"

MONTHS = [
    # month_id, name, start, end, trading_days, is_baseline, is_partial
    # 4.5: Phase 0 in the client environment confirmed June is COMPLETE
    # (min_trade_dt=2026-06-01, max_trade_dt=2026-06-30, 30 distinct dates).
    # This table accrues daily — every calendar day has rows — so the
    # trading-day counts are the calendar-day counts 30 / 31 / 30.
    ("202604", "Apr 2026", "2026-04-01 00:00:00", "2026-04-30 00:00:00", 30, True, False),
    ("202605", "May 2026", "2026-05-01 00:00:00", "2026-05-31 00:00:00", 31, False, False),
    ("202606", "Jun 2026", "2026-06-01 00:00:00", "2026-06-30 00:00:00", 30, False, False),
]
# June is a complete month (Phase 0 confirmation) — no partial-month scaling.
JUNE_FACTOR = 1.0

TRADE_DAYS = {
    "202604": [f"2026-04-{d:02d}" for d in range(1, 31)],
    "202605": [f"2026-05-{d:02d}" for d in range(1, 32)],
    "202606": [f"2026-06-{d:02d}" for d in range(1, 31)],
}

SURNAMES = ["Alvarez", "Mehta", "Okafor", "Lindqvist", "Tanaka", "Rossi", "Novak", "Osei",
            "Fournier", "Petrov", "Nguyen", "Silva", "Hansen", "Marino", "Iqbal", "Weber",
            "Castillo", "Byrne", "Sato", "Kaur", "Dumont", "Ellis"]


def money(x: float) -> str:
    return f"{round(x, 2):.2f}"


def bl(b: bool) -> str:
    return "true" if b else "false"


# --------------------------------------------------------------------------- products
def build_products() -> list[dict]:
    rows = []
    for g in PRODUCT_GROUPS:
        if g.group_id == "unmapped":
            continue
        for cd in g.product_cds:
            if "/" in cd:
                base, sub = cd.split("/")
            else:
                base, sub = cd, ""
            pid = f"{base}|{sub}"
            rows.append({
                "product_id": pid, "product_cd": base, "product_sub_cd": sub,
                "product_name": g.group_name if len(g.product_cds) == 1 else f"{g.group_name} — {base}{('/' + sub) if sub else ''}",
                "sor": "PCR", "file_key": "product_hierarchy", "group_id": g.group_id,
                "grid_type": "PRODUCT_TYPE",
            })
    # one deliberately unmapped product — visible, never dropped
    rows.append({
        "product_id": "MISC|", "product_cd": "MISC", "product_sub_cd": "",
        "product_name": "Miscellaneous Level Two", "sor": "PCR", "file_key": "product_hierarchy",
        "group_id": "unmapped", "grid_type": "PRODUCT_TYPE",
    })
    return rows


# --------------------------------------------------------------------------- advisors
def build_advisors() -> tuple[list[dict], list[str]]:
    rows = []
    cohort = []
    for i in range(1, 21):
        sid = f"V{i:06d}"
        cohort.append(sid)
        name = "" if i == 15 else f"{'KSAMLJTPNCDRBFEWGYHZ'[i % 20]}. {SURNAMES[i - 1]}"  # blank name stays blank
        rows.append({
            "advisor_sid": sid, "rep_code": f"R{700000 + i * 7}", "advisor_name": name,
            "branch_cd": f"BR{100 + (i % 5)}", "employee_id": f"E{50000 + i}", "in_cohort": bl(True),
        })
    for j, sid in enumerate(("X900001", "X900002"), start=1):
        rows.append({
            "advisor_sid": sid, "rep_code": f"R{880000 + j}", "advisor_name": f"T. {SURNAMES[19 + j]}",
            "branch_cd": "BR900", "employee_id": f"E{90000 + j}", "in_cohort": bl(False),
        })
    return rows, cohort


# --------------------------------------------------------------------------- accounts
def build_accounts(cohort: list[str]) -> tuple[list[dict], dict[str, list[dict]], list[dict], list[dict], list[dict], list[dict]]:
    """Returns (account_rows, accounts_by_advisor, rel_rows, map_rows, household_rows, rpg_rows)."""
    accounts: list[dict] = []
    by_advisor: dict[str, list[dict]] = defaultdict(list)
    rel_rows: list[dict] = []
    map_rows: list[dict] = []
    hh_counts: dict[str, int] = defaultdict(int)
    rpg_counts: dict[str, int] = defaultdict(int)
    seq = 1590

    def add_account(advisor: str, opened: str | None, rpg: str | None, scenario: str) -> dict:
        nonlocal seq
        seq += 7
        raw = str(seq).zfill(10)
        key = normalize_account_key(raw)
        eci = f"ECI{3000 + (seq % 160)}"
        hh_counts[eci] += 1
        opened_in_scope = bool(opened and "2026-04-01" <= opened[:10] < "2026-07-01")
        acct = {
            "acct_key": key, "account_no_raw": raw,
            "account_class_cd": RNG.choice(["01", "02", "07"]),
            "account_class_nm": RNG.choice(["Individual", "Joint", "IRA"]),
            "account_lob_cd": "CWM", "account_purpose_cd": RNG.choice(["INV", "RET"]),
            "managed_platform_cd": RNG.choice(["MGP", "MGP", "MGP", ""]),
            "service_channel_cd": "FA",
            "account_open_dt": opened or "",
            "is_managed": "",  # filled below
            "opened_in_scope": bl(opened_in_scope),
            "primary_eci_id": eci,
            # bookkeeping (not written to CSV)
            "_advisor": advisor, "_rpg": rpg or "", "_scenario": scenario,
        }
        acct["is_managed"] = bl(bool(acct["managed_platform_cd"]))
        accounts.append(acct)
        by_advisor[advisor].append(acct)
        # relationships: primary owner always; sometimes joint owner; sometimes beneficiary
        codes = [("001", "Sole Owner", True)]
        if RNG.random() < 0.3:
            codes = [("151", "Primary Joint Owner", True), ("201", "Sec Joint Owner", True)]
        if RNG.random() < 0.4:
            codes.append(("802", "Beneficiary", False))
        for code, role, owner in codes:
            rel_eci = eci if owner else f"ECI{9000 + (seq % 90)}"
            hh_counts.setdefault(rel_eci, hh_counts[rel_eci] if rel_eci in hh_counts else 0)
            rel_rows.append({
                "rel_id": f"{key}|{rel_eci}|{code}", "acct_key": key, "eci_id": rel_eci,
                "enterprise_relationship_code": code, "party_role_name": role,
                "client_employee_ind": "N", "is_owner_role": bl(owner),
            })
        # cross-system bridge (latest bus_dt per account)
        src_raw = str(seq).zfill(15)
        map_rows.append({
            "map_id": f"2026-06-30 00:00:00|WM1|{normalize_account_key(src_raw)}",
            "acct_src_key": normalize_account_key(src_raw), "acct_src_raw": src_raw,
            "wm_src_sys_cd": "WM1", "eci_id": eci, "bus_dt": "2026-06-30 00:00:00",
            "new_exst_adv_clnt_in": "E",
        })
        if rpg:
            rpg_counts[rpg] += 1
        return acct

    # baseline book: 10 accounts per cohort advisor
    for i, sid in enumerate(cohort):
        for k in range(10):
            opened = f"20{RNG.randint(15, 25)}-{RNG.randint(1, 12):02d}-{RNG.randint(1, 28):02d} 00:00:00"
            if RNG.random() < 0.05:
                opened = None  # blank open date — parsed NULL, stays blank
            rpg = f"RPG{(i * 3 + k) % 28:03d}" if RNG.random() < 0.5 else None
            add_account(sid, opened, rpg, "baseline")

    # new accounts opened in Q2 (8, spread over advisors 9-12)
    for n in range(8):
        sid = cohort[8 + n % 4]
        add_account(sid, f"2026-0{4 + n % 2}-{5 + n:02d} 00:00:00", None, "new_in_scope")

    # transferred-in books (April): 6 accounts to V000002, 5 to V000003, all from X900001
    for n in range(6):
        add_account("V000002", "2019-06-15 00:00:00", "RPG900", "transfer_in_feecut")
    for n in range(5):
        add_account("V000003", "2020-02-10 00:00:00", "RPG901", "transfer_in_feecut")

    # zeroed accounts: mark 10 existing baseline accounts (advisors 13-16) as zeroed in May
    zero_pool = [a for sid in cohort[12:16] for a in by_advisor[sid] if a["_scenario"] == "baseline"]
    for a in zero_pool[:10]:
        a["_scenario"] = "zeroed_may"

    household_rows = [{"eci_id": e, "account_count": str(c)} for e, c in sorted(hh_counts.items())]
    rpg_rows = [{"rpg_id": r, "account_count": str(c)} for r, c in sorted(rpg_counts.items())]
    # strip bookkeeping keys for the CSV copy later (kept on dicts; writer selects columns)
    return accounts, by_advisor, rel_rows, map_rows, household_rows, rpg_rows


# --------------------------------------------------------------------------- transactions
def build_transactions(products: list[dict], by_advisor: dict[str, list[dict]], cohort: list[str]) -> list[dict]:
    txns: list[dict] = []
    ref = 100000

    boring = set(cohort[16:20])  # V000017..V000020: quiet books
    # accounts above the 10% fee-reduction threshold: 11 transferred + 2 scattered = 13
    feecut = [a for sid in ("V000002", "V000003") for a in by_advisor[sid] if a["_scenario"] == "transfer_in_feecut"]
    scattered = [by_advisor["V000009"][0], by_advisor["V000011"][1]]
    reduction_accounts = feecut + scattered
    # only 2 of the 13 carry a RECORDED grid_reduction (expected-vs-recorded divergence)
    recorded = {feecut[1]["acct_key"], scattered[0]["acct_key"]}

    mapped_products = [p for p in products if p["group_id"] != "unmapped"]

    def emit(advisor: str, acct: dict, product: dict, month_id: str, amount: float,
             reason_cd: str = "__NONE__", std_bps: float = 0.0, cli_bps: float = 0.0,
             grid_red: float = 0.0, description: str = "") -> None:
        nonlocal ref
        ref += 1
        credited = reason_cd == "__NONE__"
        day = RNG.choice(TRADE_DAYS[month_id])
        dtp = RNG.randint(1, 5)
        proc = day  # simplification: proc within month; days_to_process carried explicitly
        eff = round((std_bps - cli_bps) / std_bps * 100, 1) if std_bps else 0.0
        txns.append({
            "txn_id": f"{ref}|1|{advisor}", "trade_ref_no": str(ref), "split_seq_no": "1",
            "advisor_sid": advisor, "acct_key": acct["acct_key"], "product_id": product["product_id"],
            "month_id": month_id, "trade_dt": f"{day} 00:00:00", "proc_dt": f"{proc} 00:00:00",
            "days_to_process": str(dtp),
            "credited_amt": money(amount if credited else 0.0),
            "non_credited_amt": money(0.0 if credited else amount),
            "pre_split_amt": money(amount / 0.85),
            "split_pct": "0.85", "reason_cd": reason_cd, "is_credited": bl(credited),
            "standard_rate_bps": money(std_bps), "client_rate_bps": money(cli_bps),
            "discount_amt": money(amount * eff / 100 if eff > 0 else 0.0),
            "eff_disc_pct": f"{eff:.1f}", "grid_reduction": money(grid_red),
            "rpg": acct["_rpg"], "concession_type": "STD" if eff <= 10 else "DISC",
            "file_key": "daily_trade_details", "trade_description": description or product["product_name"],
        })

    for sid in cohort:
        accts = by_advisor[sid]
        base_scale = 0.45 if sid in boring else 1.0
        for month_id, _, _, _, _, _, _ in MONTHS:
            month_factor = JUNE_FACTOR if month_id == "202606" else 1.0
            growth = {"202604": 1.0, "202605": 1.035, "202606": 1.0}[month_id]
            for p in mapped_products:
                # each advisor trades a stable subset of products
                if (hash(sid + p["product_id"]) % 10) < 4:
                    continue
                n = max(1, int(round(2 * month_factor)))
                for _ in range(n):
                    acct = RNG.choice([a for a in accts if a["_scenario"] != "transfer_in_feecut"] or accts)
                    if acct["_scenario"] == "zeroed_may" and month_id != "202604":
                        continue  # zeroed accounts stop producing after April
                    if acct["_scenario"] == "new_in_scope" and month_id == "202604":
                        continue  # opened in Q2 → first revenue in the following month
                    amount = RNG.uniform(300, 2600) * base_scale * growth
                    if RNG.random() < 0.06:
                        emit(sid, acct, p, month_id, amount, reason_cd=RNG.choice(["INELG", "ADJ"]))
                    else:
                        emit(sid, acct, p, month_id, amount)

    # fee-reduction scenario: managed-account fees on the 13 reduced accounts (May + June)
    oisc = next(p for p in mapped_products if p["product_id"] == "OISC|")
    for acct in reduction_accounts:
        cli = RNG.choice([118.0, 124.0, 126.0, 128.0])
        grid = 3.0 if acct["acct_key"] in recorded else 0.0
        for month_id in ("202605", "202606"):
            factor = JUNE_FACTOR if month_id == "202606" else 1.0
            emit(acct["_advisor"], acct, oisc, month_id, RNG.uniform(900, 1800) * factor,
                 std_bps=145.0, cli_bps=cli, grid_red=grid, description="Managed account fee — discounted")

    # syndicate one-off: two large STRT allocations, V000001, May only
    strt = next(p for p in mapped_products if p["product_id"] == "STRT|")
    for _ in range(2):
        emit("V000001", by_advisor["V000001"][0], strt, "202605", RNG.uniform(26000, 31000),
             description="Syndicate allocation")

    # unmapped product activity — visible, never dropped
    misc = next(p for p in products if p["group_id"] == "unmapped")
    for month_id in ("202604", "202605"):
        emit("V000006", by_advisor["V000006"][2], misc, month_id, RNG.uniform(400, 900),
             description="Unmapped level-two product")

    return txns


# --------------------------------------------------------------------------- other vertices
def build_account_month(by_advisor: dict[str, list[dict]], txns: list[dict]) -> list[dict]:
    per = defaultdict(lambda: {"credited": 0.0, "count": 0})
    for t in txns:
        k = (t["acct_key"], t["advisor_sid"], t["month_id"])
        per[k]["credited"] += float(t["credited_amt"])
        per[k]["count"] += 1
    rows = []
    for sid, accts in by_advisor.items():
        for a in accts:
            base_balance = RNG.uniform(150_000, 2_400_000)
            prior_bal, prior_credited = 0.0, 0.0  # baseline month has no prior
            for month_id, *_ in MONTHS:
                zeroed = a["_scenario"] == "zeroed_may" and month_id != "202604"
                bal = 0.0 if zeroed else base_balance * {"202604": 1.0, "202605": 1.02, "202606": 1.01}[month_id]
                if a["_scenario"] == "new_in_scope" and month_id == "202604":
                    bal = 0.0
                agg = per.get((a["acct_key"], sid, month_id), {"credited": 0.0, "count": 0})
                rows.append({
                    "am_id": f"{a['acct_key']}|{sid}|{month_id}",
                    "acct_key": a["acct_key"], "advisor_sid": sid, "month_id": month_id,
                    "end_balance": money(bal), "credited_amt": money(agg["credited"]),
                    "txn_count": str(agg["count"]), "is_zero_balance": bl(bal == 0.0),
                    "present_prior_month": bl(month_id != "202604"),
                    "prior_end_balance": money(prior_bal),
                    "prior_credited_amt": money(prior_credited),
                })
                prior_bal, prior_credited = bal, float(agg["credited"])
    return rows


def build_transfers(by_advisor: dict[str, list[dict]]) -> list[dict]:
    rows = []
    seq = 0
    # inbound: the transferred fee-cut books arrived 14 Apr from X900001
    for sid in ("V000002", "V000003"):
        for a in by_advisor[sid]:
            if a["_scenario"] != "transfer_in_feecut":
                continue
            seq += 1
            ts = "2026-04-14 09:30:00"
            rows.append({
                "transfer_id": f"OCC1|{a['acct_key']}|R880001|{seq}|20260414093000",
                "acct_key": a["acct_key"], "from_advisor_sid": "X900001", "to_advisor_sid": sid,
                "from_rr": "R880001", "to_rr": "R7000XX", "transfer_ts": ts, "month_id": "202604",
                "is_intra_team": bl(False), "occd_cd": "OCC1",
            })
    # outbound: two accounts leave V000005 to X900002 in April
    for a in by_advisor["V000005"][:2]:
        seq += 1
        rows.append({
            "transfer_id": f"OCC2|{a['acct_key']}|R700035|{seq}|20260421110000",
            "acct_key": a["acct_key"], "from_advisor_sid": "V000005", "to_advisor_sid": "X900002",
            "from_rr": "R700035", "to_rr": "R880002", "transfer_ts": "2026-04-21 11:00:00",
            "month_id": "202604", "is_intra_team": bl(False), "occd_cd": "OCC2",
        })
    return rows


def build_team_agreements() -> list[dict]:
    rows = []
    specs = [
        (9001, "TR100", "V000004", 0.5, "V000006", 0.5),
        (9002, "TR101", "V000007", 0.6, "X900002", 0.4),
        (9003, "TR102", "V000002", 0.5, "V000012", 0.5),
    ]
    for aid, rep, prm, ps, sec, ss in specs:
        rows.append({
            "agreement_key": f"{aid}|{rep}|{prm}|{sec}|20260101",
            "agreement_id": str(aid), "team_rep_cd": rep, "agreement_type": "REV_SHARE",
            "status_cd": "ACTIVE", "prm_advisor_sid": prm, "prm_share_pct": f"{ps}",
            "sec_advisor_sid": sec, "sec_share_pct": f"{ss}",
            "start_ts": "2026-01-01 00:00:00", "end_ts": "2026-12-31 00:00:00",
        })
    return rows


def build_flows(cohort: list[str]) -> list[dict]:
    rows = []
    flow_products = [("MGDF", "Managed Flows"), ("BRKF", "Brokerage Flows")]
    for sid in cohort:
        # V000008 crosses the $4MM annual NNM threshold
        scale = 2_400_000.0 if sid == "V000008" else RNG.uniform(120_000, 700_000)
        for month_id in ("202604", "202605"):  # June has no flow rows
            for cd, desc in flow_products:
                inflow = scale * RNG.uniform(0.8, 1.2)
                outflow = inflow * RNG.uniform(0.2, 0.6)
                rows.append({
                    "afm_id": f"{sid}|{month_id}|{cd}",
                    "advisor_sid": sid, "month_id": month_id,
                    "flow_product_cd": cd, "flow_product_desc": desc,
                    "comp_group_type": "NNM",
                    "total_inflows": money(inflow), "total_outflows": money(outflow),
                    "total_net_flows": money(inflow - outflow), "credited_flows": money(inflow - outflow),
                    "departed_advisor_sid": "", "departed_advisor_excl_am": "0.00",
                    "lob_trfr_excl_am": "0.00", "oi_pa_referral_cap_adj_am": "0.00",
                    "large_flow_cap_adj_am": "0.00", "forced_closure_excl_am": "0.00",
                })
    return rows


# --------------------------------------------------------------------------- opportunities
def build_opportunities(by_advisor: dict[str, list[dict]]) -> list[dict]:
    """CRM pipeline rows, joined through ECI — DUMMY data on every row until a
    real CRM feed exists (data_source='DUMMY'; the UI shows a Dummy Data chip)."""
    stages = ["Prospecting", "Discovery", "Proposal", "Negotiation", "Closed"]
    groups = ["managed_accounts", "twhs_structured", "insurance_annuities",
              "lending", "mutual_funds"]
    sources = ["Referral", "Existing Client", "Event", "Cold Outreach"]
    rows = []
    n = 0
    for sid, accts in sorted(by_advisor.items()):
        eci_ids = sorted({a["primary_eci_id"] for a in accts if a.get("primary_eci_id")})
        for eci in eci_ids[:2]:  # a couple of open opportunities per advisor
            n += 1
            status = RNG.choice(["PENDING", "PENDING", "WON", "LOST"])
            open_dt = f"2026-{RNG.choice(['04','05','06'])}-{RNG.randint(1, 28):02d}"
            close_dt = "" if status == "PENDING" else f"2026-06-{RNG.randint(1, 30):02d}"
            rows.append({
                "opportunity_id": f"OPP{n:05d}", "eci_id": eci, "advisor_sid": sid,
                "stage": "Closed" if status != "PENDING" else RNG.choice(stages[:4]),
                "status": status, "amount": money(RNG.uniform(50_000, 1_500_000)),
                "product_group": RNG.choice(groups),
                "open_dt": f"{open_dt} 00:00:00",
                "expected_close_dt": f"2026-07-{RNG.randint(1, 31):02d} 00:00:00",
                "close_dt": f"{close_dt} 00:00:00" if close_dt else "",
                "source": RNG.choice(sources),
                "data_source": "DUMMY",  # every row — the honesty flag the UI keys on
            })
    return rows


# --------------------------------------------------------------------------- writers
VERTEX_COLUMNS = {
    "phx_dm_pce_month": ["month_id", "month_name", "start_dt", "end_dt", "trading_days", "is_baseline", "is_partial"],
    "phx_dm_pce_revenue_class": ["class_id", "class_name"],
    "phx_dm_pce_product_group": ["group_id", "group_name", "display_prefix", "class_id", "sort_order", "is_aggregated"],
    "phx_dm_pce_product": ["product_id", "product_cd", "product_sub_cd", "product_name", "sor", "file_key", "group_id", "grid_type"],
    "phx_dm_pce_advisor": ["advisor_sid", "rep_code", "advisor_name", "branch_cd", "employee_id", "in_cohort"],
    "phx_dm_pce_account": ["acct_key", "account_no_raw", "account_class_cd", "account_class_nm", "account_lob_cd",
                            "account_purpose_cd", "managed_platform_cd", "service_channel_cd", "account_open_dt",
                            "is_managed", "opened_in_scope", "primary_eci_id"],
    "phx_dm_pce_household": ["eci_id", "account_count"],
    "phx_dm_pce_account_eci_rel": ["rel_id", "acct_key", "eci_id", "enterprise_relationship_code",
                                    "party_role_name", "client_employee_ind", "is_owner_role"],
    "phx_dm_pce_account_eci_map": ["map_id", "acct_src_key", "acct_src_raw", "wm_src_sys_cd", "eci_id", "bus_dt", "new_exst_adv_clnt_in"],
    "phx_dm_pce_rpg": ["rpg_id", "account_count"],
    "phx_dm_pce_team_agreement": ["agreement_key", "agreement_id", "team_rep_cd", "agreement_type", "status_cd",
                                   "prm_advisor_sid", "prm_share_pct", "sec_advisor_sid", "sec_share_pct", "start_ts", "end_ts"],
    "phx_dm_pce_revenue_transaction": ["txn_id", "trade_ref_no", "split_seq_no", "advisor_sid", "acct_key", "product_id",
                                        "month_id", "trade_dt", "proc_dt", "days_to_process", "credited_amt", "non_credited_amt",
                                        "pre_split_amt", "split_pct", "reason_cd", "is_credited", "standard_rate_bps",
                                        "client_rate_bps", "discount_amt", "eff_disc_pct", "grid_reduction", "rpg",
                                        "concession_type", "file_key", "trade_description"],
    "phx_dm_pce_monthly_revenue": ["mr_id", "advisor_sid", "month_id", "product_id", "group_id", "class_id",
                                    "credited_amt", "non_credited_amt", "txn_count", "distinct_accounts"],
    "phx_dm_pce_account_month": ["am_id", "acct_key", "advisor_sid", "month_id", "end_balance", "credited_amt",
                                  "txn_count", "is_zero_balance", "present_prior_month",
                                  "prior_end_balance", "prior_credited_amt"],
    "phx_dm_pce_account_transfer": ["transfer_id", "acct_key", "from_advisor_sid", "to_advisor_sid", "from_rr",
                                     "to_rr", "transfer_ts", "month_id", "is_intra_team", "occd_cd"],
    "phx_dm_pce_advisor_flow_month": ["afm_id", "advisor_sid", "month_id", "flow_product_cd", "flow_product_desc",
                                       "comp_group_type", "total_inflows", "total_outflows", "total_net_flows",
                                       "credited_flows", "departed_advisor_sid", "departed_advisor_excl_am",
                                       "lob_trfr_excl_am", "oi_pa_referral_cap_adj_am", "large_flow_cap_adj_am",
                                       "forced_closure_excl_am"],
    "phx_dm_pce_opportunity": ["opportunity_id", "eci_id", "advisor_sid", "stage", "status", "amount",
                                "product_group", "open_dt", "expected_close_dt", "close_dt", "source",
                                "data_source"],
}

ID_COLUMNS = {
    "phx_dm_pce_month": "month_id", "phx_dm_pce_revenue_class": "class_id",
    "phx_dm_pce_product_group": "group_id", "phx_dm_pce_product": "product_id",
    "phx_dm_pce_advisor": "advisor_sid", "phx_dm_pce_account": "acct_key",
    "phx_dm_pce_household": "eci_id", "phx_dm_pce_account_eci_rel": "rel_id",
    "phx_dm_pce_account_eci_map": "map_id", "phx_dm_pce_rpg": "rpg_id",
    "phx_dm_pce_team_agreement": "agreement_key", "phx_dm_pce_revenue_transaction": "txn_id",
    "phx_dm_pce_monthly_revenue": "mr_id", "phx_dm_pce_account_month": "am_id",
    "phx_dm_pce_account_transfer": "transfer_id", "phx_dm_pce_advisor_flow_month": "afm_id",
    "phx_dm_pce_opportunity": "opportunity_id",
}

# edge_name -> (from_type, to_type, source vertex, from_field, to_field)
EDGES = {
    "phx_dm_pce_product_in_group": ("phx_dm_pce_product", "phx_dm_pce_product_group", "phx_dm_pce_product", "product_id", "group_id"),
    "phx_dm_pce_group_in_class": ("phx_dm_pce_product_group", "phx_dm_pce_revenue_class", "phx_dm_pce_product_group", "group_id", "class_id"),
    "phx_dm_pce_txn_by_advisor": ("phx_dm_pce_revenue_transaction", "phx_dm_pce_advisor", "phx_dm_pce_revenue_transaction", "txn_id", "advisor_sid"),
    "phx_dm_pce_txn_for_account": ("phx_dm_pce_revenue_transaction", "phx_dm_pce_account", "phx_dm_pce_revenue_transaction", "txn_id", "acct_key"),
    "phx_dm_pce_txn_of_product": ("phx_dm_pce_revenue_transaction", "phx_dm_pce_product", "phx_dm_pce_revenue_transaction", "txn_id", "product_id"),
    "phx_dm_pce_txn_in_month": ("phx_dm_pce_revenue_transaction", "phx_dm_pce_month", "phx_dm_pce_revenue_transaction", "txn_id", "month_id"),
    "phx_dm_pce_mr_by_advisor": ("phx_dm_pce_monthly_revenue", "phx_dm_pce_advisor", "phx_dm_pce_monthly_revenue", "mr_id", "advisor_sid"),
    "phx_dm_pce_mr_in_month": ("phx_dm_pce_monthly_revenue", "phx_dm_pce_month", "phx_dm_pce_monthly_revenue", "mr_id", "month_id"),
    "phx_dm_pce_mr_of_product": ("phx_dm_pce_monthly_revenue", "phx_dm_pce_product", "phx_dm_pce_monthly_revenue", "mr_id", "product_id"),
    "phx_dm_pce_mr_in_group": ("phx_dm_pce_monthly_revenue", "phx_dm_pce_product_group", "phx_dm_pce_monthly_revenue", "mr_id", "group_id"),
    "phx_dm_pce_am_for_account": ("phx_dm_pce_account_month", "phx_dm_pce_account", "phx_dm_pce_account_month", "am_id", "acct_key"),
    "phx_dm_pce_am_by_advisor": ("phx_dm_pce_account_month", "phx_dm_pce_advisor", "phx_dm_pce_account_month", "am_id", "advisor_sid"),
    "phx_dm_pce_am_in_month": ("phx_dm_pce_account_month", "phx_dm_pce_month", "phx_dm_pce_account_month", "am_id", "month_id"),
    "phx_dm_pce_account_in_household": ("phx_dm_pce_account", "phx_dm_pce_household", "phx_dm_pce_account", "acct_key", "primary_eci_id"),
    "phx_dm_pce_rel_of_account": ("phx_dm_pce_account_eci_rel", "phx_dm_pce_account", "phx_dm_pce_account_eci_rel", "rel_id", "acct_key"),
    "phx_dm_pce_rel_to_household": ("phx_dm_pce_account_eci_rel", "phx_dm_pce_household", "phx_dm_pce_account_eci_rel", "rel_id", "eci_id"),
    "phx_dm_pce_map_of_account": ("phx_dm_pce_account_eci_map", "phx_dm_pce_account", "phx_dm_pce_account_eci_map", "map_id", "_acct_key"),
    "phx_dm_pce_map_to_household": ("phx_dm_pce_account_eci_map", "phx_dm_pce_household", "phx_dm_pce_account_eci_map", "map_id", "eci_id"),
    "phx_dm_pce_account_in_rpg": ("phx_dm_pce_account", "phx_dm_pce_rpg", "phx_dm_pce_account", "acct_key", "_rpg"),
    "phx_dm_pce_txn_in_rpg": ("phx_dm_pce_revenue_transaction", "phx_dm_pce_rpg", "phx_dm_pce_revenue_transaction", "txn_id", "rpg"),
    "phx_dm_pce_transfer_of_account": ("phx_dm_pce_account_transfer", "phx_dm_pce_account", "phx_dm_pce_account_transfer", "transfer_id", "acct_key"),
    "phx_dm_pce_transfer_from": ("phx_dm_pce_account_transfer", "phx_dm_pce_advisor", "phx_dm_pce_account_transfer", "transfer_id", "from_advisor_sid"),
    "phx_dm_pce_transfer_to": ("phx_dm_pce_account_transfer", "phx_dm_pce_advisor", "phx_dm_pce_account_transfer", "transfer_id", "to_advisor_sid"),
    "phx_dm_pce_team_primary": ("phx_dm_pce_team_agreement", "phx_dm_pce_advisor", "phx_dm_pce_team_agreement", "agreement_key", "prm_advisor_sid"),
    "phx_dm_pce_team_secondary": ("phx_dm_pce_team_agreement", "phx_dm_pce_advisor", "phx_dm_pce_team_agreement", "agreement_key", "sec_advisor_sid"),
    "phx_dm_pce_flow_by_advisor": ("phx_dm_pce_advisor_flow_month", "phx_dm_pce_advisor", "phx_dm_pce_advisor_flow_month", "afm_id", "advisor_sid"),
    "phx_dm_pce_flow_in_month": ("phx_dm_pce_advisor_flow_month", "phx_dm_pce_month", "phx_dm_pce_advisor_flow_month", "afm_id", "month_id"),
    "phx_dm_pce_opportunity_for_household": ("phx_dm_pce_opportunity", "phx_dm_pce_household", "phx_dm_pce_opportunity", "opportunity_id", "eci_id"),
    "phx_dm_pce_opportunity_by_advisor": ("phx_dm_pce_opportunity", "phx_dm_pce_advisor", "phx_dm_pce_opportunity", "opportunity_id", "advisor_sid"),
}


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            # booleans serialise as TigerGraph-friendly "true"/"false", never "True"
            w.writerow({k: (bl(v) if isinstance(v, bool) else v) for k, v in r.items()})
    return len(rows)


def main() -> None:
    vertex_rows: dict[str, list[dict]] = {}

    vertex_rows["phx_dm_pce_month"] = [
        {"month_id": m, "month_name": n, "start_dt": s, "end_dt": e,
         "trading_days": str(td), "is_baseline": bl(b), "is_partial": bl(p)}
        for m, n, s, e, td, b, p in MONTHS
    ]
    vertex_rows["phx_dm_pce_revenue_class"] = revenue_class_rows()
    vertex_rows["phx_dm_pce_product_group"] = product_group_rows()
    products = build_products()
    vertex_rows["phx_dm_pce_product"] = products

    advisors, cohort = build_advisors()
    vertex_rows["phx_dm_pce_advisor"] = advisors

    accounts, by_advisor, rel_rows, map_rows, hh_rows, rpg_rows = build_accounts(cohort)
    vertex_rows["phx_dm_pce_account"] = accounts
    vertex_rows["phx_dm_pce_household"] = hh_rows
    vertex_rows["phx_dm_pce_account_eci_rel"] = rel_rows
    vertex_rows["phx_dm_pce_account_eci_map"] = map_rows
    vertex_rows["phx_dm_pce_rpg"] = rpg_rows
    vertex_rows["phx_dm_pce_team_agreement"] = build_team_agreements()

    txns = build_transactions(products, by_advisor, cohort)
    vertex_rows["phx_dm_pce_revenue_transaction"] = txns
    vertex_rows["phx_dm_pce_monthly_revenue"] = build_monthly_revenue(txns)
    vertex_rows["phx_dm_pce_account_month"] = build_account_month(by_advisor, txns)
    vertex_rows["phx_dm_pce_account_transfer"] = build_transfers(by_advisor)
    vertex_rows["phx_dm_pce_advisor_flow_month"] = build_flows(cohort)
    vertex_rows["phx_dm_pce_opportunity"] = build_opportunities(by_advisor)

    # --- vertices ---
    manifest_files = []
    order = 0
    for target, columns in VERTEX_COLUMNS.items():
        order += 1
        rows = vertex_rows[target]
        rel = f"vertices/{target}.csv"
        n = write_csv(DATA / rel, columns, rows)
        manifest_files.append({
            "file": rel, "kind": "vertex", "target": target,
            "id_column": ID_COLUMNS[target],
            "columns": {c: c for c in columns},
            "expected_rows": n, "order": order,
        })
        print(f"vertex {target}: {n} rows")

    # --- edges (derived from the vertex rows) ---
    acct_key_by_map = {m["map_id"]: None for m in map_rows}
    # map edges join through eci/src key; simplest correct derivation: map row → its account
    # was built 1:1 in build_accounts order.
    for m, a in zip(map_rows, accounts):
        m["_acct_key"] = a["acct_key"]

    valid_ids = {t: {r[ID_COLUMNS[t]] for r in vertex_rows[t]} for t in VERTEX_COLUMNS}

    for edge_name, (ftype, ttype, source, ffield, tfield) in EDGES.items():
        order += 1
        rows = []
        seen = set()
        for r in vertex_rows[source]:
            fid = r.get(ffield, "")
            tid = r.get(tfield, "")
            if not fid or not tid:
                continue  # e.g. accounts without an RPG, txns with blank rpg
            if tid not in valid_ids[ttype]:
                continue  # e.g. account_in_household when the eci was only a beneficiary id
            k = (fid, tid)
            if k in seen:
                continue
            seen.add(k)
            rows.append({"from_id": fid, "to_id": tid})
        rel = f"edges/{edge_name}.csv"
        n = write_csv(DATA / rel, ["from_id", "to_id"], rows)
        manifest_files.append({
            "file": rel, "kind": "edge", "target": edge_name,
            "from_type": ftype, "to_type": ttype,
            "from_column": "from_id", "to_column": "to_id",
            "columns": {}, "expected_rows": n, "order": order,
        })
        print(f"edge {edge_name}: {n} rows")

    manifest = {
        "graph": "phx_dm_pce_practice_demo",
        "generated_by": "scripts/generate_mock_data.py (seed 42)",
        "batch_size": 500,
        "files": manifest_files,
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total_v = sum(f["expected_rows"] for f in manifest_files if f["kind"] == "vertex")
    total_e = sum(f["expected_rows"] for f in manifest_files if f["kind"] == "edge")
    print(f"\nmanifest: {len(manifest_files)} files, {total_v} vertex rows, {total_e} edge rows")

    # cohort selection file (SCHEMA_SPEC §5 step 1)
    cohort_path = ROOT / "docs" / "data" / "cohort_advisors.csv"
    cohort_path.parent.mkdir(parents=True, exist_ok=True)
    flags = {
        "V000001": "syndicate_one_off", "V000002": "transfer_in;fee_reduction;team_agreement",
        "V000003": "transfer_in;fee_reduction", "V000004": "team_agreement_primary",
        "V000005": "transfer_out", "V000006": "team_agreement_secondary;unmapped_product",
        "V000007": "team_agreement_primary", "V000008": "nnm_above_4mm",
        "V000009": "fee_reduction_recorded", "V000011": "fee_reduction_unrecorded",
        "V000013": "accounts_zeroed", "V000014": "accounts_zeroed",
        "V000015": "blank_name", "V000017": "quiet", "V000018": "quiet",
        "V000019": "quiet", "V000020": "quiet",
    }
    with cohort_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["advisor_sid", "scenario_flags"])
        for sid in cohort:
            w.writerow([sid, flags.get(sid, "")])
    print(f"cohort file: {cohort_path}")


if __name__ == "__main__":
    main()

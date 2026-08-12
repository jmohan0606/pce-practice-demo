"""Round F task 4 — fabricate a small raw-extract set matching RAW_CONTRACT.

    python3 scripts/make_test_raw_extracts.py [--out data/real_test/_raw]

The scripts in the real-data chain (select_cohort -> generate_extraction_sql ->
build_real_data -> load/verify) cannot be tested against the client's
PostgreSQL from here, so this generator fabricates source-shaped raw CSVs with
the exact RAW_CONTRACT columns (zero-padded account numbers, MM/DD/YYYY open
dates, a *_cyr column, reason-coded rows, and so on) and every §5 scenario:

  - 3 advisors with recorded grid_reduction rows (the scarce flag)
  - fee reductions >10% with and WITHOUT a recorded grid_reduction
  - transfers in and out, incl. counterparties OUTSIDE the cohort
  - accounts opened in scope; accounts zeroed between April and May
  - team agreements; flows for April+May only; non-credited reason rows
  - one hierarchy product outside the 24-group seed (-> unmapped, visible)
  - two trades on an account absent from raw_account.csv (-> demonstrably
    DROPPED txn_for_account edges, counted and printed by the build)
  - a duplicate older bus_dt row in the eci map (latest-only rule exercised)

DELIBERATELY placed under data/real_test/ (committed), never data/real/
(gitignored, reserved for the client's actual extracts) — the fabricated set
must never be mistaken for real client data.

Deterministic: seeded RNG, no clock reads.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_real_data import RAW_CONTRACT  # noqa: E402
from scripts.select_cohort import select  # noqa: E402

RNG = random.Random(4242)

MONTH_DAYS = {"202604": 30, "202605": 31, "202606": 30}
MONTHS = list(MONTH_DAYS)

# (product_cd, product_sub_cd, name) — real seed codes + one off-seed (MISC)
HIERARCHY = [
    ("OISC", "", "Managed Accounts Fee"), ("UMA", "", "Unified Managed Accounts"),
    ("ATMF", "", "Trails Mutual Funds"), ("MMKT", "", "Money Market Funds"),
    ("STRT", "", "Structured Products"), ("ELIS", "EQ", "Equities"),
    ("ELIS", "OP", "Options"), ("MUFD", "", "Mutual Funds"),
    ("FCXX", "", "Corporate Bonds"), ("FIX", "", "Fixed Annuities"),
    ("ALTI", "", "Alternative Investments"), ("LEND", "SBL", "Security Based Lending"),
    ("EDK", "", "Everyday 401K"), ("MISC", "", "Miscellaneous Level Two"),  # -> unmapped
]


def bl(b: bool) -> str:
    return "true" if b else "false"


def money(x: float) -> str:
    return f"{round(x, 2):.2f}"


def day_in(month_id: str, d: int) -> str:
    return f"{month_id[:4]}-{month_id[4:]}-{d:02d}"


def write(out: Path, name: str, rows: list[dict]) -> None:
    cols = RAW_CONTRACT[name]
    out.mkdir(parents=True, exist_ok=True)
    with (out / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {out / name} ({len(rows)} rows)")


def build_flags() -> list[dict]:
    """26 candidates: 3 grid-reduction, 14 with assorted flags, 3 with none,
    6 low-revenue losers whose flags duplicate already-covered ones."""
    def row(i: int, rev: float, **flags) -> dict:
        sid = f"T{i:06d}"
        r = {"advisor_sid": sid, "rep_code": f"R{500000 + i}",
             "advisor_name": "" if i == 15 else f"Test Advisor {i:02d}",
             "total_credited_amt": money(rev)}
        for c in RAW_CONTRACT["raw_advisor_flags.csv"][4:]:
            r[c] = bl(bool(flags.get(c, False)))
        return r

    rows = [
        # 1 — the scarce grid-reduction advisors (highest revenue first)
        row(1, 61_000, has_recorded_grid_reduction=True, has_fee_reduction_gt10=True,
            has_flows=True, has_non_credited=True),
        row(2, 58_000, has_recorded_grid_reduction=True, has_fee_reduction_gt10=True,
            has_transfer_in=True, has_flows=True),
        row(3, 54_000, has_recorded_grid_reduction=True, has_fee_reduction_gt10=True,
            has_team_agreement=True),
        # 2 — coverage of the remaining flags
        row(4, 52_000, has_transfer_out=True, has_flows=True, has_non_credited=True),
        row(5, 50_000, has_new_account=True, has_zeroed_account=True, has_flows=True),
        row(6, 48_000, has_team_agreement=True, has_transfer_in=True, has_non_credited=True),
        row(7, 46_000, has_fee_reduction_gt10=True, has_flows=True),  # unrecorded reduction
        row(8, 45_000, has_zeroed_account=True, has_non_credited=True),
        row(9, 44_000, has_new_account=True, has_flows=True),
        row(10, 43_000, has_transfer_in=True, has_flows=True),
        row(11, 42_000, has_transfer_out=True, has_non_credited=True),
        row(12, 41_000, has_team_agreement=True, has_flows=True),
        row(13, 40_000, has_flows=True, has_non_credited=True),
        row(14, 39_000, has_new_account=True),
        row(15, 38_000, has_flows=True),  # blank name stays blank
        row(16, 37_000, has_zeroed_account=True, has_flows=True),
        row(17, 36_000, has_non_credited=True, has_flows=True),
        # 4 — the deliberately boring, no-flag advisors
        row(18, 35_000),
        row(19, 34_000),
        row(20, 33_000),
        # losers: low revenue, only already-covered flags — must NOT be selected
        row(21, 9_000, has_flows=True),
        row(22, 8_500, has_non_credited=True),
        row(23, 8_000, has_new_account=True),
        row(24, 7_500, has_flows=True),
        row(25, 7_000, has_zeroed_account=True),
        row(26, 6_500, has_transfer_in=True),
    ]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/real_test/_raw")
    args = ap.parse_args()
    out = Path(args.out)

    flags = build_flags()
    write(out, "raw_advisor_flags.csv", flags)

    # the cohort the selector will pick — fabricate raw extracts for exactly it
    selected, _reasons = select([dict(r) for r in flags])
    cohort = [r["advisor_sid"] for r in selected]
    flag_by_sid = {r["advisor_sid"]: r for r in flags}
    print(f"fixture cohort ({len(cohort)}): {cohort}")

    counterparties = ["X800001", "X800002"]

    # ---- raw_advisor.csv (cohort + transfer counterparties) ----
    advisors = []
    for sid in cohort:
        f = flag_by_sid[sid]
        advisors.append({
            "advisor_sid": sid, "rep_code": f["rep_code"],
            "advisor_name": f["advisor_name"],
            "branch_cd": f"BR{100 + int(sid[1:]) % 4}",
            "employee_id": f"E{40000 + int(sid[1:])}", "in_cohort": "true",
        })
    for j, sid in enumerate(counterparties, start=1):
        advisors.append({
            "advisor_sid": sid, "rep_code": f"R{690000 + j}",
            "advisor_name": f"Outside Advisor {j}", "branch_cd": "BR900",
            "employee_id": f"E{90000 + j}", "in_cohort": "false",
        })
    write(out, "raw_advisor.csv", advisors)

    # ---- accounts: 6 per cohort advisor, zero-padded 10-wide numbers ----
    accounts, acct_by_sid = [], {}
    seq = 3000
    for sid in cohort:
        f = flag_by_sid[sid]
        mine = []
        for k in range(6):
            seq += 7
            raw_no = str(seq).zfill(10)
            opened = "03/15/2021 09:30:00 AM"
            if f["has_new_account"] == "true" and k == 5:
                opened = "04/10/2026 10:00:00 AM"  # opened in scope
            accounts.append({
                "account_no": raw_no,
                "account_class_cd": RNG.choice(["01", "02", "07"]),
                "account_class_nm": RNG.choice(["Individual", "Joint", "IRA"]),
                "account_lob_cd": "CWM",
                "account_purpose_cd": RNG.choice(["INV", "RET"]),
                "managed_platform_cd": RNG.choice(["MGP", "MGP", ""]),
                "service_channel_cd": "FA",
                "account_open_dt": opened,
                "primary_eci_id": f"ECI{7000 + seq % 300}",
            })
            mine.append(raw_no)
        acct_by_sid[sid] = mine
    write(out, "raw_account.csv", accounts)
    eci_by_acct = {a["account_no"]: a["primary_eci_id"] for a in accounts}

    # ---- product hierarchy (incl. MISC -> unmapped) ----
    write(out, "raw_product_hierarchy.csv", [{
        "product_cd": cd, "product_sub_cd": sub, "product_name": name,
        "sor": "PCR", "file_key": "", "grid_type": "PRODUCT_TYPE",
    } for cd, sub, name in HIERARCHY])

    # ---- transactions ----
    txns, ref = [], 700000

    def emit(sid: str, acct_no: str, cd: str, sub: str, month: str, amount: float,
             reason: str = "", std: float = 0.0, cli: float = 0.0,
             grid: float = 0.0, desc: str = "") -> None:
        nonlocal ref
        ref += 1
        d = RNG.randint(1, MONTH_DAYS[month])
        trade = day_in(month, d)
        proc = day_in(month, min(d + 2, MONTH_DAYS[month])) if d + 2 <= MONTH_DAYS[month] \
            else day_in("202607" if month == "202606" else MONTHS[MONTHS.index(month) + 1], 1)
        eff = round((std - cli) / std * 100, 1) if std else 0.0
        txns.append({
            "trade_ref_no": str(ref), "split_seq_no": "1", "advisor_sid": sid,
            "account_no": acct_no, "product_cd": cd, "product_sub_cd": sub,
            "trade_dt": trade, "proc_dt": proc,
            "post_split_credited_amt": money(amount),
            "pre_split_credited_amt": money(amount / 0.85), "split_pct": "0.85",
            "reason_cd": reason,
            "standard_rate_bps": money(std), "client_rate_bps": money(cli),
            "discount_amt": money(amount * eff / 100 if eff > 0 else 0.0),
            "eff_disc_pct": f"{eff:.1f}", "grid_reduction": money(grid),
            "rpg": f"RPG{int(acct_no) % 9:03d}" if int(acct_no) % 2 else "",
            "concession_type": "DISC" if eff > 10 else "STD",
            "file_key": "daily_trade_details", "trade_description": desc or f"{cd} trade",
        })

    products = [(cd, sub) for cd, sub, _ in HIERARCHY if cd != "MISC"]
    for sid in cohort:
        f = flag_by_sid[sid]
        scale = float(f["total_credited_amt"]) / 30_000.0
        for month in MONTHS:
            for _ in range(RNG.randint(24, 32)):
                acct = RNG.choice(acct_by_sid[sid])
                cd, sub = RNG.choice(products)
                amount = RNG.uniform(250, 1400) * scale
                if f["has_non_credited"] == "true" and RNG.random() < 0.08:
                    emit(sid, acct, cd, sub, month, amount, reason=RNG.choice(["INELG", "ADJ"]))
                else:
                    emit(sid, acct, cd, sub, month, amount)
        # fee-reduction scenario on the advisor's first account (May + June)
        if f["has_fee_reduction_gt10"] == "true":
            grid = 3.0 if f["has_recorded_grid_reduction"] == "true" else 0.0
            for month in ("202605", "202606"):
                emit(sid, acct_by_sid[sid][0], "OISC", "", month,
                     RNG.uniform(900, 1800), std=145.0,
                     cli=RNG.choice([118.0, 124.0, 128.0]), grid=grid,
                     desc="Managed account fee — discounted")
    # unmapped product activity (MISC is in the hierarchy but not the 24-group seed)
    emit(cohort[3], acct_by_sid[cohort[3]][1], "MISC", "", "202604", 480.0,
         desc="Unmapped level-two product")
    emit(cohort[3], acct_by_sid[cohort[3]][1], "MISC", "", "202605", 512.0,
         desc="Unmapped level-two product")
    # product traded but ABSENT from the hierarchy -> synthetic unmapped vertex
    emit(cohort[4], acct_by_sid[cohort[4]][2], "ZZZZ", "", "202605", 333.0,
         desc="Product missing from hierarchy")
    # trades on an account absent from raw_account.csv -> DROPPED txn_for_account
    emit(cohort[0], "0009999999", "MUFD", "", "202604", 150.0, desc="Orphan account trade")
    emit(cohort[0], "0009999999", "MUFD", "", "202605", 175.0, desc="Orphan account trade")
    write(out, "raw_revenue_transaction.csv", txns)

    # ---- transfers (in from X800001, out to X800002) ----
    transfers, tseq = [], 0
    for sid in cohort:
        f = flag_by_sid[sid]
        if f["has_transfer_in"] == "true":
            tseq += 1
            transfers.append({
                "occd_cd": "OCC1", "account_no": acct_by_sid[sid][1],
                "transfer_ts": "2026-04-14 09:30:00", "seq_no": str(tseq),
                "from_rr": "R690001", "from_mem_sid": "X800001",
                "to_rr": flag_by_sid[sid]["rep_code"], "to_mem_sid": sid,
            })
        if f["has_transfer_out"] == "true":
            tseq += 1
            transfers.append({
                "occd_cd": "OCC2", "account_no": acct_by_sid[sid][2],
                "transfer_ts": "2026-04-21 11:00:00", "seq_no": str(tseq),
                "from_rr": flag_by_sid[sid]["rep_code"], "from_mem_sid": sid,
                "to_rr": "R690002", "to_mem_sid": "X800002",
            })
    write(out, "raw_rr_changes.csv", transfers)

    # ---- balances (12-wide padded ids; zeroed accounts drop to 0 in May) ----
    balances = []
    for sid in cohort:
        f = flag_by_sid[sid]
        for k, acct in enumerate(acct_by_sid[sid]):
            base = RNG.uniform(150_000, 1_900_000)
            zeroed = f["has_zeroed_account"] == "true" and k == 3
            for month in MONTHS:
                bal = 0.0 if (zeroed and month != "202604") else \
                    base * {"202604": 1.0, "202605": 1.02, "202606": 1.01}[month]
                balances.append({"month_id": month,
                                 "acct_id": acct.zfill(12), "acct_bal": money(bal)})
    write(out, "raw_monthly_balance.csv", balances)

    # ---- month meta (30/31/30, complete months) ----
    write(out, "raw_month_meta.csv", [{
        "month_id": m, "start_dt": day_in(m, 1),
        "end_dt": day_in(m, MONTH_DAYS[m]), "trading_days": str(MONTH_DAYS[m]),
    } for m in MONTHS])

    # ---- eci relationships (owners + a beneficiary) ----
    rels = []
    for a in accounts:
        rels.append({"account_number": a["account_no"].zfill(15),
                     "party_eci_id": a["primary_eci_id"],
                     "enterprise_relationship_code": "001",
                     "party_role_name": "Sole Owner", "client_employee_ind": "N"})
        if RNG.random() < 0.3:
            rels.append({"account_number": a["account_no"].zfill(15),
                         "party_eci_id": f"ECI{9500 + int(a['account_no']) % 80}",
                         "enterprise_relationship_code": "802",
                         "party_role_name": "Beneficiary", "client_employee_ind": "N"})
    write(out, "raw_acct_eci_rel.csv", rels)

    # ---- eci map (15-wide keys, *_cyr column, one stale-snapshot duplicate) ----
    maps = []
    for a in accounts:
        maps.append({"bus_dt": "2026-06-30", "wm_src_sys_cd": "WM1",
                     "wm_acct_src_nb": a["account_no"].zfill(15),
                     "eci_nb": a["primary_eci_id"],
                     "new_exst_adv_clnt_in_cyr": RNG.choice(["E", "E", "N"])})
    # older snapshot row for the first account — latest-bus_dt rule must win
    maps.append({"bus_dt": "2026-05-31", "wm_src_sys_cd": "WM1",
                 "wm_acct_src_nb": accounts[0]["account_no"].zfill(15),
                 "eci_nb": "ECI_STALE", "new_exst_adv_clnt_in_cyr": "N"})
    write(out, "raw_acct_eci_map.csv", maps)

    # ---- team agreements ----
    team_sids = [sid for sid in cohort if flag_by_sid[sid]["has_team_agreement"] == "true"]
    agreements = []
    for i, sid in enumerate(team_sids, start=1):
        partner = cohort[(cohort.index(sid) + 5) % len(cohort)]
        agreements.append({
            "agreement_id": str(9000 + i), "team_rep_cd": f"TR{100 + i}",
            "team_agreement_typ": "REV_SHARE", "team_agreement_status_cd": "ACTIVE",
            "prm_standard_id": sid, "prm_share_pct": "0.6",
            "sec_standard_id": partner, "sec_share_pct": "0.4",
            "start_ts": "2026-01-01 00:00:00", "end_ts": "2026-12-31 00:00:00",
        })
    write(out, "raw_team_agreement.csv", agreements)

    # ---- flows (April and May ONLY) ----
    flows = []
    for sid in cohort:
        if flag_by_sid[sid]["has_flows"] != "true":
            continue
        for month in ("202604", "202605"):
            for cd, desc in (("MGDF", "Managed Flows"), ("BRKF", "Brokerage Flows")):
                inflow = RNG.uniform(120_000, 700_000)
                outflow = inflow * RNG.uniform(0.2, 0.6)
                flows.append({
                    "advisor_sid": sid, "month_id": month, "flow_product_cd": cd,
                    "flow_product_desc": desc, "comp_group_type": "NNM",
                    "total_inflows": money(inflow), "total_outflows": money(outflow),
                    "total_net_flows": money(inflow - outflow),
                    "credited_flows": money(inflow - outflow),
                    "departed_advisor_sid": "", "departed_advisor_excl_am": "0",
                    "lob_trfr_excl_am": "0", "oi_pa_referral_cap_adj_am": "0",
                    "large_flow_cap_adj_am": "0", "forced_closure_excl_am": "0",
                })
    write(out, "raw_adv_flows.csv", flows)

    print(f"\nfabricated raw set complete: {len(RAW_CONTRACT)} files in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

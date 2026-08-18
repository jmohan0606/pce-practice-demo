#!/usr/bin/env python3
"""Round 2a task 6 check 5f — the 12.4M-row streaming memory proof.

    python3 scripts/make_scale_proof.py [--out /tmp/pce_scale_proof]

Fabricates a raw drop at the CLIENT-MEASURED row counts (EXPECTED_COUNTS.json:
12,436,738 transactions, 2,689,176 accounts, 6,971,181 eci_rel, 2,915,901
eci_map, 8,683,364 balances, 5,746 advisors, 166,985 flows, 141,054 transfers,
firm-wide 308,534-row CRM file), entirely deterministic and written streaming,
then runs scripts/build_real_data.py against it with the DEFAULT
--max-memory-mb 4096 guard and reports wall time + per-entity peak RSS.

The content is synthetic; the CARDINALITIES are the client's. This proves the
memory model (spec 2.6), not the data. Needs ~12 GB free on --out's
filesystem. The generated drop is disposable.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import parse_nnm  # noqa: E402

BASE = json.loads((ROOT / "docs/data/extraction/EXPECTED_COUNTS.json").read_text())
RAW = BASE["raw"]
MONTHS = BASE["months"]
N_ADV = 5746
N_ACC = RAW["raw_account"]["rows"]          # 2,689,176
N_REL = RAW["raw_acct_eci_rel"]["rows"]     # 6,971,181
N_MAP = RAW["raw_acct_eci_map"]["rows"]     # 2,915,901
N_FLOW = RAW["raw_adv_flows"]["rows"]       # 166,985
N_RR = RAW["raw_rr_changes"]["rows"]        # 141,054
N_CRM = RAW["crm_opportunities"]["rows"]    # 308,534
MONTH_DAYS = {"202604": 30, "202605": 31, "202606": 30}

PRODUCTS = [("OISC", ""), ("UMA", ""), ("ATMF", ""), ("MMKT", ""),
            ("STRT", ""), ("ELIS", "EQ"), ("ELIS", "OP"), ("MUFD", ""),
            ("FCXX", ""), ("FIX", ""), ("LEND", "SBL"), ("PCS", "SP"),
            ("PCS", "PBR"), ("ALTI", ""), ("DCCR", "")]


def sid(i: int) -> str:
    return f"S{(i % N_ADV) + 1:06d}"


def acct(i: int) -> str:
    return f"1{(i % N_ACC) + 1:08d}"  # no leading zero — normalises to itself


def eci(i: int) -> str:
    return f"E{(i % (N_ACC // 3 + 1)) + 1:07d}"


def w(path: Path, header: list[str]):
    f = path.open("w", newline="", encoding="utf-8")
    wr = csv.writer(f)
    wr.writerow(header)
    return f, wr


def generate(raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # advisors (Round 5: +em_status_cd/work state/city; flags file retired)
    f, wr = w(raw / "raw_advisor.csv",
              ["advisor_sid", "rep_code", "advisor_name", "branch_cd",
               "employee_id", "in_cohort", "job_code",
               "em_status_cd", "em_work_st_cd", "em_work_city_txt"])
    for i in range(N_ADV):
        wr.writerow([sid(i), f"R{i:05d}", f"Advisor {i}", f"B{i % 40:03d}",
                     sid(i), "true", "HK0186" if i % 3 else "",
                     "A" if i % 29 else "T", "NY", "New York"])
    f.close()

    # month meta / products (transcribed shape, tiny)
    f, wr = w(raw / "raw_month_meta.csv",
              ["month_id", "start_dt", "end_dt", "trading_days"])
    for m in MONTHS:
        d = MONTH_DAYS[m]
        wr.writerow([m, f"{m[:4]}-{m[4:]}-01 00:00:00",
                     f"{m[:4]}-{m[4:]}-{d:02d} 00:00:00", str(d)])
    f.close()
    f, wr = w(raw / "raw_product_hierarchy.csv",
              ["product_cd", "product_sub_cd", "product_name", "sor",
               "file_key", "grid_type", "l1_pay_type_cd", "l2_pay_type_cd"])
    for cd, sub in PRODUCTS:
        wr.writerow([cd, sub, f"Product {cd}{sub}", "SOR", "", "PRODUCT_TYPE",
                     "managed", cd.lower()])
    f.close()

    # accounts — 4 bucket chunks (the real chunk form)
    per = (N_ACC + 3) // 4
    n = 0
    for b in range(4):
        f, wr = w(raw / f"raw_account_b{b + 1:03d}.csv",
                  ["account_no", "account_class_cd", "account_class_nm",
                   "account_lob_cd", "account_purpose_cd",
                   "managed_platform_cd", "service_channel_cd",
                   "account_open_dt", "primary_eci_id"])
        for i in range(b * per, min((b + 1) * per, N_ACC)):
            wr.writerow([acct(i), "IND", "Individual", "WM", "INV",
                         "MGD" if i % 2 else "", "ONL",
                         "2020-01-01 00:00:00", eci(i)])
            n += 1
        f.close()
    print(f"  accounts: {n:,} in 4 buckets ({time.time() - t0:.0f}s)")

    # eci_rel — 4 buckets
    per = (N_REL + 3) // 4
    codes = ["001", "802", "151"]
    r = 0
    for b in range(4):
        f, wr = w(raw / f"raw_acct_eci_rel_b{b + 1:03d}.csv",
                  ["account_number", "party_eci_id",
                   "enterprise_relationship_code", "party_role_name",
                   "client_employee_ind"])
        for _ in range(min(per, N_REL - b * per)):
            p = r // N_ACC
            wr.writerow([acct(r), eci(r + p), codes[p % 3], "Owner", "N"])
            r += 1
        f.close()
    print(f"  eci_rel: {r:,} in 4 buckets ({time.time() - t0:.0f}s)")

    # eci_map — 4 buckets (rows beyond N_ACC are older snapshots -> superseded)
    per = (N_MAP + 3) // 4
    r = 0
    for b in range(4):
        f, wr = w(raw / f"raw_acct_eci_map_b{b + 1:03d}.csv",
                  ["bus_dt", "wm_src_sys_cd", "wm_acct_src_nb", "eci_nb",
                   "new_exst_adv_clnt_in_cyr"])
        for _ in range(min(per, N_MAP - b * per)):
            snap = r // N_ACC
            wr.writerow([f"2026-06-{28 - snap:02d}", "WM", acct(r), eci(r),
                         "E" if r % 2 else "N"])
            r += 1
        f.close()
    print(f"  eci_map: {r:,} in 4 buckets ({time.time() - t0:.0f}s)")

    # balances — one chunk per month
    for m in MONTHS:
        target = RAW["raw_monthly_balance"]["per_month"][m]
        f, wr = w(raw / f"raw_balance_{m}.csv", ["month_id", "acct_id", "acct_bal"])
        for i in range(target):
            wr.writerow([m, acct(i), str(50000 + (i % 1000) * 10)])
        f.close()
        print(f"  balances {m}: {target:,} ({time.time() - t0:.0f}s)")

    # transactions — month x 29 advisor-batch chunks (the real chunk form)
    for m in MONTHS:
        target = RAW["raw_revenue_transaction"]["per_month"][m]
        batches = 29
        per = (target + batches - 1) // batches
        days = MONTH_DAYS[m]
        written = 0
        for b in range(batches):
            f, wr = w(raw / f"raw_txn_{m}_b{b + 1:03d}.csv",
                      ["trade_ref_no", "split_seq_no", "advisor_sid",
                       "account_no", "product_cd", "product_sub_cd", "trade_dt",
                       "proc_dt", "post_split_credited_amt",
                       "pre_split_credited_amt", "split_pct", "reason_cd",
                       "standard_rate_bps", "client_rate_bps", "discount_amt",
                       "eff_disc_pct", "grid_reduction", "rpg",
                       "concession_type", "file_key", "trade_description"])
            for _ in range(min(per, target - written)):
                i = written
                cd, sub = PRODUCTS[i % len(PRODUCTS)]
                day = (i % days) + 1
                dt = f"{m[:4]}-{m[4:]}-{day:02d}"
                # the account's OWNING advisor trades it (matches the client
                # reality: pair cardinality ~ account cardinality, not txns)
                wr.writerow([f"T{m}{i:08d}", "1", sid(i % N_ACC), acct(i), cd, sub,
                             dt, dt, str(40 + i % 20), str(40 + i % 20), "1",
                             "ADJ" if i % 50 == 7 else "",
                             "145", "130" if i % 9 else "100", "0", "10.3",
                             "2" if i % 90 == 3 else "0",
                             f"RPG{i % 50:03d}" if i % 10 == 0 else "",
                             "", "", ""])
                written += 1
            f.close()
        print(f"  txns {m}: {written:,} in {batches} chunks "
              f"({time.time() - t0:.0f}s)")

    # transfers / team / flows
    f, wr = w(raw / "raw_rr_changes.csv",
              ["occd_cd", "account_no", "transfer_ts", "seq_no", "from_rr",
               "from_mem_sid", "to_rr", "to_mem_sid"])
    for i in range(N_RR):
        m = MONTHS[i % 3]
        wr.writerow(["RR", acct(i * 7), f"{m[:4]}-{m[4:]}-10 12:00:00",
                     str(i), f"R{i % N_ADV:05d}", sid(i), f"R{(i + 1) % N_ADV:05d}",
                     sid(i + 1)])
    f.close()
    f, wr = w(raw / "raw_team_agreement.csv",
              ["agreement_id", "team_rep_cd", "team_agreement_typ",
               "team_agreement_status_cd", "prm_standard_id", "prm_share_pct",
               "sec_standard_id", "sec_share_pct", "start_ts", "end_ts"])
    for i in range(RAW["raw_team_agreement"]["rows"]):
        wr.writerow([f"AG{i:04d}", f"TR{i:03d}", "SPLIT", "ACTIVE", sid(i),
                     "0.6", sid(i + 1), "0.4", "2025-01-01 00:00:00", ""])
    f.close()
    f, wr = w(raw / "raw_adv_flows.csv",
              ["advisor_sid", "month_id", "flow_product_cd",
               "flow_product_desc", "comp_group_type", "total_inflows",
               "total_outflows", "total_net_flows", "credited_flows",
               "departed_advisor_sid", "departed_advisor_excl_am",
               "lob_trfr_excl_am", "oi_pa_referral_cap_adj_am",
               "large_flow_cap_adj_am", "forced_closure_excl_am"])
    for i in range(N_FLOW):
        wr.writerow([sid(i), MONTHS[(i // N_ADV) % 3],
                     f"FP{i // (N_ADV * 3):02d}", "Flow product", "NNM",
                     "1000", "400", "600", "600", "", "0", "0", "0", "0", "0"])
    f.close()

    # CRM — firm-wide: ~20% out-of-scope + every 1000th an invalid reference
    f, wr = w(raw / "crm_opportunities.csv",
              ["opportunity_id", "eci_id", "ownersid", "account_record_type",
               "product_service_type", "stage_name", "amount", "actual_assets",
               "anticipated_investment_dt", "created_dt", "last_modified_dt",
               "date_of_last_contact", "days_to_close", "comments"])
    for i in range(N_CRM):
        out_of_scope = i % 5 == 4
        owner = (f"{sid(i)}_CWM_INVALID" if i % 1000 == 0
                 else ("ZOUT" + str(i) if out_of_scope else sid(i)))
        e = ("EXOUT" + str(i)) if out_of_scope else eci(i)
        wr.writerow([f"OP{i:07d}", e, owner, "Brokerage", "Managed",
                     "Qualification", "0", "100000", "2026-09-01",
                     "2026-05-01 00:00:00", "2026-06-01 00:00:00",
                     "2026-06-15 00:00:00", str(30 if i % 4 else -5), ""])
    f.close()
    print(f"  crm: {N_CRM:,} rows (~20% out-of-scope by design) "
          f"({time.time() - t0:.0f}s)")

    # NNM — ~50k rows via the real parser's mock writer
    cohort = [sid(i) for i in range(2083)]
    parse_nnm.write_mock_nnm_files(raw, cohort, seed=177)
    n_nnm = len(parse_nnm.parse_nnm_dir(raw))
    print(f"  nnm: {n_nnm:,} rows across the four category files "
          f"({time.time() - t0:.0f}s)")
    print(f"generation done in {time.time() - t0:.0f}s; drop size: "
          f"{sum(p.stat().st_size for p in raw.iterdir()) / 1e9:.2f} GB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/pce_scale_proof")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated drop + built set (default: delete)")
    args = ap.parse_args()
    out = Path(args.out)
    raw, built = out / "_raw", out / "built"
    if raw.exists():
        shutil.rmtree(raw)
    if built.exists():
        shutil.rmtree(built)

    free_gb = shutil.disk_usage(out.parent if not out.exists() else out).free / 1e9
    if free_gb < 12:
        print(f"ERROR: only {free_gb:.1f} GB free at {out} — the proof needs "
              f"~12 GB", file=sys.stderr)
        return 1

    print(f"[1/2] generating the firm-scale drop at the client-measured "
          f"cardinalities -> {raw}")
    generate(raw)

    print(f"\n[2/2] building with the DEFAULT --max-memory-mb 4096 guard")
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, "scripts/build_real_data.py", "--raw", str(raw),
         "--out", str(built)], cwd=ROOT, capture_output=True, text=True)
    wall = time.time() - t0
    # show the memory lines + validation verdict, not 60 lines of counts
    for ln in r.stdout.splitlines():
        if ("[memory]" in ln or "VALIDATIONS" in ln or ln.startswith("wrote")
                or "transaction extract" in ln or "CRM:" in ln):
            print(ln)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:], file=sys.stderr)
        print(f"\nSCALE PROOF FAILED after {wall / 60:.1f} min", file=sys.stderr)
        return 1
    report = json.loads((built / "build_report.json").read_text())
    peaks = report["peak_rss_mb_per_entity"]
    print(f"\nSCALE PROOF PASSED — 12.4M-row build in {wall / 60:.1f} min; "
          f"peak RSS {max(peaks.values())} MB (guard 4096 MB)")
    print("per-entity peak RSS (MB):",
          json.dumps(peaks, indent=None))
    print("entity rows:", {k.replace('phx_dm_pce_', ''): v
                           for k, v in report['entities'].items()
                           if v > 1_000_000})
    if not args.keep:
        shutil.rmtree(out, ignore_errors=True)
        print("(drop + built set deleted; pass --keep to retain)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

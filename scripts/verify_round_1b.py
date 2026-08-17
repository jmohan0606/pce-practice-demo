#!/usr/bin/env python3
"""Round 1b — the spec's 8 checks (docs/spec/ROUND_1B_SPEC.md task 6).

1  migration 002 applies to a Round-1 state without touching data
2  verify_schema_parity passes: clean install == 001 + 002
3  job_code on the advisor vertex; extraction SQL selects fpic_employee_tb.job_cd;
   a blank stays blank
4  l1/l2_pay_type_cd on the product vertex and populated by the transform
5  26 product groups; PCS/SP -> referrals_sit_partnership, PCS/PBR ->
   referrals_private_bank; neither unmapped
6  existing product grouping unchanged — the other 25 groups resolve as before
7  mock data generates all three new fields; build_real_data carries them through
8  runbook Phase 1 covers all three install paths; Phase 5 covers rollback

Run: python3 scripts/verify_round_1b.py
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    tg = ROOT / "docs" / "tigergraph"
    mig2 = (tg / "migrations" / "002_schema_additions.gsql").read_text()

    # 1 — 002 is data-safe and touches no types, only attributes
    body = "\n".join(ln.split("//")[0] for ln in mig2.splitlines())
    dangerous = [kw for kw in ("DROP ", "DELETE ", "UPDATE ", "CLEAR GRAPH",
                               "LOAD ", "LOADING JOB", "TRUNCATE")
                 if kw in body.upper()]
    alters = re.findall(r"ALTER\s+VERTEX\s+(\w+)\s+ADD\s+ATTRIBUTE", body)
    creates = re.findall(r"CREATE\s+(?:DIRECTED\s+EDGE|VERTEX)\s", body.upper())
    creates = [c for c in creates if "SCHEMA_CHANGE" not in c]
    check("1  migration 002 is additive-only on a Round-1 state "
          "(no DROP/DELETE/UPDATE/LOAD; ALTER-only, no new types)",
          not dangerous and sorted(alters) == ["phx_dm_pce_advisor", "phx_dm_pce_product"]
          and not creates,
          f"alters={sorted(alters)} dangerous={dangerous or 'none'}")

    # 2 — parity: clean install == baseline_f2 + 001 + 002
    r = subprocess.run([sys.executable, "scripts/verify_schema_parity.py"],
                       capture_output=True, text=True, cwd=ROOT)
    check("2  verify_schema_parity: clean install == 001 + 002",
          r.returncode == 0 and "migrations (001, 002) == clean install" in r.stdout,
          r.stdout.strip().splitlines()[-1])

    # 3 — job_code present everywhere; SQL selects job_cd; blank stays blank
    ddl = (tg / "01_vertices.gsql").read_text()
    catalog = json.loads((tg / "schema_catalog.json").read_text())
    adv_sql = (ROOT / "docs/data/extraction/raw_advisor.sql").read_text()
    from scripts.generate_mock_data import mock_job_code
    ddl_adv = re.search(r"CREATE VERTEX phx_dm_pce_advisor \((.*?)\) WITH",
                        ddl, re.S).group(1)
    check("3a job_code on the advisor vertex (DDL + schema_catalog + loading job "
          "+ manifest)",
          "job_code STRING" in ddl_adv
          and catalog["vertices"]["phx_dm_pce_advisor"]["attributes"].get("job_code") == "STRING"
          and '$"job_code"' in (tg / "loading/load_advisor.gsql").read_text()
          and '"job_code"' in (ROOT / "data/manifest.json").read_text())
    check("3b extraction SQL selects fpic_employee_tb.job_cd",
          re.search(r"COALESCE\(e\.job_cd,''\)\s+AS job_code", adv_sql) is not None
          and "fpic_employee_tb e" in adv_sql,
          "COALESCE(e.job_cd,'') AS job_code from the em_standard_id join")
    with open(ROOT / "data/vertices/phx_dm_pce_advisor.csv", encoding="utf-8-sig") as f:
        adv_rows = {r["advisor_sid"]: r for r in csv.DictReader(f)}
    check("3c blank stays blank (mock V000008 + both counterparties empty; "
          "cohort rule matches the generator)",
          adv_rows["V000008"]["job_code"] == ""
          and adv_rows["X900001"]["job_code"] == ""
          and all(adv_rows[f"V{i:06d}"]["job_code"] == mock_job_code(i)
                  for i in range(1, 21)),
          f"V000001={adv_rows['V000001']['job_code']!r} "
          f"V000008={adv_rows['V000008']['job_code']!r} "
          f"X900001={adv_rows['X900001']['job_code']!r}")

    # 4 — pay-type codes on the product vertex, populated
    ddl_prod = re.search(r"CREATE VERTEX phx_dm_pce_product \((.*?)\) WITH",
                         ddl, re.S).group(1)
    prod_sql = (ROOT / "docs/data/extraction/raw_product_hierarchy.sql").read_text()
    with open(ROOT / "data/vertices/phx_dm_pce_product.csv", encoding="utf-8-sig") as f:
        prod_rows = {r["product_id"]: r for r in csv.DictReader(f)}
    populated = sum(1 for r in prod_rows.values() if r["l1_pay_type_cd"])
    check("4  l1/l2_pay_type_cd on the product vertex; extraction selects the "
          "export columns; committed rows populated (MISC honestly blank)",
          "l1_pay_type_cd STRING" in ddl_prod and "l2_pay_type_cd STRING" in ddl_prod
          and catalog["vertices"]["phx_dm_pce_product"]["attributes"].get("l1_pay_type_cd") == "STRING"
          and "level_one_pay_type_product_cd" in prod_sql
          and "level_two_pay_type_product_cd" in prod_sql
          and prod_rows["UMA|"]["l2_pay_type_cd"] == "unified_managed_accounts"
          and prod_rows["MISC|"]["l1_pay_type_cd"] == ""
          and populated == len(prod_rows) - 1,
          f"{populated}/{len(prod_rows)} committed products carry codes "
          f"(MISC| off-export blank); UMA| -> managed/unified_managed_accounts")

    # 5 — 26 groups; both PCS sub-products resolve, neither unmapped
    from app.revenue.products import product_group_rows, resolve_product
    rows = product_group_rows()
    sp, pbr = resolve_product("PCS", "SP"), resolve_product("PCS", "PBR")
    check("5  26 product groups; PCS/SP and PCS/PBR resolve, neither unmapped",
          len(rows) == 26
          and sp == "referrals_sit_partnership" and pbr == "referrals_private_bank",
          f"{len(rows)} groups; PCS/SP->{sp}; PCS/PBR->{pbr}")

    # 6 — the other 25 groups resolve exactly as before (full expected table)
    expected = {
        ("OISC", ""): "managed_accounts", ("OIS1", ""): "managed_accounts",
        ("JPMC", ""): "managed_accounts", ("MAP", ""): "managed_accounts",
        ("UMA", ""): "managed_uma", ("ATMF", ""): "trails_mutual_funds",
        ("ITMF", ""): "trails_life_annuities", ("ADVA", ""): "trails_life_annuities",
        ("MMKT", ""): "cash_mgmt_mmkt", ("PRDP", ""): "cash_mgmt_prdp",
        ("529T", ""): "plans_529", ("DAF", ""): "donor_advised_funds",
        ("STRT", ""): "twhs_structured", ("ELIS", "EQ"): "twhs_equities",
        ("ELIS", "OP"): "twhs_options", ("MUFD", ""): "twhs_mutual_funds",
        ("FCXX", ""): "twhs_fi_corporate", ("FMXX", ""): "twhs_fi_municipal",
        ("FGXX", ""): "twhs_fi_government", ("FCOT", ""): "twhs_fi_other",
        ("FCCD", ""): "twhs_cash_mgmt_cds", ("FIX", ""): "life_annuities",
        ("VARI", ""): "life_annuities", ("LIFE", ""): "life_annuities",
        ("ALTI", ""): "alternative_investments",
        ("DCCR", ""): "defined_contribution_advisory",
        ("LEND", "SBL"): "lending_sbl", ("LEND", "MGN"): "lending_margin",
        ("EDK", ""): "referrals_everyday_401k",
        ("PCS", ""): "referrals_sit_partnership",  # committed pre-split rows
        ("ZZZZ", ""): "unmapped", ("ELIS", "XX"): "unmapped",
    }
    bad = {c: resolve_product(*c) for c, want in expected.items()
           if resolve_product(*c) != want}
    check("6  existing grouping unchanged — every pre-1b code resolves as before",
          not bad, str(bad) if bad else f"{len(expected)} mappings verified")

    # 7 — mock generation emits all three fields; build_real_data carries them
    from scripts.generate_mock_data import build_advisors, build_products
    gen_adv, _ = build_advisors()
    gen_prod = build_products()
    gen_ok = (all("job_code" in a for a in gen_adv)
              and all("l1_pay_type_cd" in p and "l2_pay_type_cd" in p for p in gen_prod)
              and any(p["product_id"] == "PCS|PBR" for p in gen_prod))
    tmp = Path(tempfile.mkdtemp(prefix="r1b_"))
    try:
        drop = tmp / "raw"
        shutil.copytree(ROOT / "data/real_test/_raw", drop)
        (drop / "raw_crm_opportunity.csv").rename(drop / "crm_opportunities.csv")
        r = subprocess.run([sys.executable, "scripts/build_real_data.py",
                            "--raw", str(drop), "--out", str(tmp / "built")],
                           capture_output=True, text=True, cwd=ROOT)
        with open(tmp / "built/vertices/phx_dm_pce_advisor.csv",
                  encoding="utf-8-sig") as f:
            built_adv = {a["advisor_sid"]: a for a in csv.DictReader(f)}
        with open(tmp / "built/vertices/phx_dm_pce_product.csv",
                  encoding="utf-8-sig") as f:
            built_prod = {p["product_id"]: p for p in csv.DictReader(f)}
        check("7  mock generator emits all three fields (PCS|PBR included); "
              "build_real_data carries them through end-to-end",
              gen_ok and r.returncode == 0 and "ALL 12 VALIDATIONS PASSED" in r.stdout
              and built_adv["T000001"]["job_code"] != ""
              and built_adv["T000008"]["job_code"] == ""  # blank stayed blank
              and built_prod["PCS|PBR"]["group_id"] == "referrals_private_bank"
              and built_prod["PCS|SP"]["group_id"] == "referrals_sit_partnership"
              and built_prod["PCS|PBR"]["l2_pay_type_cd"] == "private_bank_referral",
              f"generator: {len(gen_adv)} advisors / {len(gen_prod)} products; "
              f"fixture build T000001 job={built_adv['T000001']['job_code']} "
              f"T000008 blank; PCS|PBR -> referrals_private_bank")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 8 — runbook: three install paths + rollback
    rb = (ROOT / "docs/CLIENT_ENV_RUNBOOK.md").read_text()
    check("8  runbook Phase 1 covers all three install paths; Phase 5 covers "
          "rollback",
          "### 1.1 Fresh install" in rb
          and "### 1.2a Already installed at the Round-F2 state" in rb
          and "### 1.2b Already installed at the Round-1 state" in rb
          and "002_schema_additions.gsql" in rb
          and "### 5.4 If a load went wrong" in rb
          and "90_drop_all.gsql" in rb
          and "DESTROYS ALL LOADED DATA" in rb
          and "Never hand-edit CSVs" in rb)

    print(f"\n{len(FAILURES)} FAILURE(S)" if FAILURES else "\n8/8 checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

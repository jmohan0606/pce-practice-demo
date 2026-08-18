#!/usr/bin/env python3
"""Round 2a — the spec's Task 6 checks (docs/ROUND_2A_EXTRACTION_SPEC.md).

 1   batch_size 5000 in the manifest generator and settings; env override works
 2   raw_adv_flows.sql covers April-June and still aggregates; 166,985 expected
 3   no extraction template inlines the cohort or the account set
 4   scoped_acct created once per session and joined, not recomputed per table
 5   dry-run prints the FULL plan with per-chunk estimates (87+3+12+7 at firm
     scale); 5a >2M warning (balance months spec-exempt); 5b resume mid-family;
     5c scoped_acct recreated per session; 5d five chunk families read /
     missing bucket fails / both forms fail; 5e per-chunk contracts;
     5f streaming + memory guard (full 12.4M proof via --full-scale, its output
     recorded in ROUND_2A_COMPLETE.md); 5g account_month month-at-a-time;
     5h disk checks; 5i advisor_flags retired (Round 5); 5j validator V-2 all families
 6   manifest carries phase (vertices 1, edges 2)
 7   a phase-2 entity refuses to start while phase 1 is incomplete
 8   --max-parallel defaults to 3 and is respected
 9   reconcile_load compares source/extracted/loaded and fails hard
 10  the expected-count baseline is committed and used
 11  COPILOT_EXTRACTION_GUIDE.md — DELIBERATELY DEFERRED (Task 5 is written
     separately after review, so it describes what exists)

Run: python3 scripts/verify_round_2a.py [--full-scale]
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []
TMP = Path(tempfile.mkdtemp(prefix="pce-verify-r2a-"))


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=e)


def make_chunked_drop(dst: Path) -> None:
    """The fixture drop re-cut into all five chunk families."""
    shutil.copytree(ROOT / "data/real_test/_raw", dst)
    (dst / "raw_crm_opportunity.csv").rename(dst / "crm_opportunities.csv")
    plans = [("raw_revenue_transaction.csv", "txn"), ("raw_account.csv", 2),
             ("raw_acct_eci_rel.csv", 3), ("raw_acct_eci_map.csv", 2),
             ("raw_monthly_balance.csv", "month")]
    for src, n in plans:
        rows = list(csv.DictReader(open(dst / src, encoding="utf-8-sig")))
        cols = list(rows[0].keys())
        if n == "month":
            for m in sorted({r["month_id"] for r in rows}):
                with open(dst / f"raw_balance_{m}.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=cols)
                    w.writeheader()
                    for r in rows:
                        if r["month_id"] == m:
                            w.writerow(r)
        elif n == "txn":
            by_month: dict[str, list] = {}
            for r in rows:
                # Round 5: txn chunks are PROC-month bounded (month_id basis)
                by_month.setdefault(r["proc_dt"][:7].replace("-", ""), []).append(r)
            for m, mrows in sorted(by_month.items()):
                half = (len(mrows) + 1) // 2
                for b, part in enumerate((mrows[:half], mrows[half:]), start=1):
                    with open(dst / f"raw_txn_{m}_b{b:03d}.csv", "w", newline="") as f:
                        w = csv.DictWriter(f, fieldnames=cols)
                        w.writeheader()
                        w.writerows(part)
        else:
            stem = src[:-4]
            for b in range(n):
                with open(dst / f"{stem}_b{b + 1:03d}.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=cols)
                    w.writeheader()
                    for i, r in enumerate(rows):
                        if i % n == b:
                            w.writerow(r)
        (dst / src).unlink()


def main() -> int:  # noqa: PLR0915 — one check per stanza, deliberately linear
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full-scale", action="store_true",
                    help="also run the 12.4M-row streaming memory proof "
                         "(long; its output is recorded in ROUND_2A_COMPLETE.md)")
    args = ap.parse_args()

    from scripts.generate_extraction_sql import (
        BALANCE_TABLES, session_setup_statements, templates,
    )
    from scripts import extract_chunked

    # ---- 1: batch size 5000 -------------------------------------------------
    gen_src = (ROOT / "scripts/generate_mock_data.py").read_text()
    build_src = (ROOT / "scripts/build_real_data.py").read_text()
    mock_manifest = json.loads((ROOT / "data/manifest.json").read_text())
    r_default = run([sys.executable, "-c",
                     "from app.config.settings import get_settings; "
                     "print(get_settings().ingestion_batch_size)"])
    r_override = run([sys.executable, "-c",
                      "from app.ingestion.entity_registry import list_entity_configs; "
                      "print(sorted({c.batch_size for c in list_entity_configs()}))"],
                     env={"INGESTION_BATCH_SIZE": "777"})
    check("1  batch_size 5000 in both manifest generators, committed manifest "
          "and settings; INGESTION_BATCH_SIZE env override beats the manifest",
          '"batch_size": 5000' in gen_src and '"batch_size": 5000' in build_src
          and mock_manifest["batch_size"] == 5000
          and r_default.stdout.strip() == "5000"
          and r_override.stdout.strip() == "[777]",
          f"settings default {r_default.stdout.strip()}, "
          f"override -> {r_override.stdout.strip()}")

    # ---- 2: flows April-June, aggregated, 166,985 expected -------------------
    flows = templates()["raw_adv_flows.sql"]
    baseline = json.loads(
        (ROOT / "docs/data/extraction/EXPECTED_COUNTS.json").read_text())
    check("2  raw_adv_flows covers April-June and still aggregates; expected "
          "output 166,985 rows in the committed baseline",
          "DATE '2026-04-01'" in flows and "DATE '2026-07-01'" in flows
          and "GROUP  BY 1, 2, 3, 4, 5" in flows and "sum(" in flows
          and baseline["raw"]["raw_adv_flows"]["rows"] == 166_985,
          "date bound < 2026-07-01; GROUP BY intact; baseline 166,985 "
          "(19.4M daily rows never cross the wire)")

    # ---- 3: nothing inlines the cohort or the account set --------------------
    big = [f"X{i:05d}" for i in range(6000)]
    inlined = [name for name, sql in templates(big).items() if "IN ('" in sql]
    setup = session_setup_statements(big)
    per_stmt_max = max(s.count("('") for s in setup if s.startswith("INSERT"))
    chunk_sql = extract_chunked.txn_chunk_sql(big[:200], "202605")
    check("3  no extraction template inlines SIDs or account keys — temp "
          "tables and joins only (txn CHUNKS inline their <=batch-size batch)",
          not inlined and per_stmt_max <= 500
          and chunk_sql.count("','") == 199 and "cohort_adv" not in chunk_sql,
          f"templates inlining lists: {inlined or 'none'}; setup inserts "
          f"<=500 SIDs/statement; txn chunk carries exactly its 200-SID batch")

    # ---- 4: scoped_acct once per session, joined ------------------------------
    scoped_creates = [s for s in setup if "CREATE TEMP TABLE scoped_acct" in s]
    scans = [name for name, sql in templates().items()
             if name in ("raw_account.sql", "raw_acct_eci_rel.sql",
                         "raw_acct_eci_map.sql")
             and "fpic_daily_trade_details_tb_prod" in sql]
    joins = [name for name in ("raw_account.sql", "raw_acct_eci_rel.sql",
                               "raw_acct_eci_map.sql")
             if "JOIN   scoped_acct s" not in templates()[name]]
    bal_join = all("JOIN   scoped_acct s" in
                   __import__("scripts.generate_extraction_sql",
                              fromlist=["monthly_balance_sql"])
                   .monthly_balance_sql(m) for m in BALANCE_TABLES)
    check("4  scoped_acct created ONCE per session and joined — the 12.4M-row "
          "trade table is never re-scanned per table",
          len(scoped_creates) == 1 and not scans and not joins and bal_join,
          "1 CREATE in session setup; account/eci_rel/eci_map/balances all "
          "join scoped_acct; none re-scans the trade table")

    # ---- 5 + 5a: the firm-scale dry-run plan ---------------------------------
    firm = TMP / "firm_cohort.txt"
    firm.write_text("\n".join(f"S{i:05d}" for i in range(5746)))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = extract_chunked.main(
            ["--months", "202604,202605,202606", "--advisors-file", str(firm),
             "--out", str(TMP / "plan_out"), "--dry-run"])
    dry = buf.getvalue()
    n_est = dry.count("(projected)")
    # Round 5 re-pin: raw_advisor_flags retired -> 6 singles, 108 chunks.
    check("5  --dry-run prints the FULL plan with per-chunk estimates: 87 txn "
          "+ 3 monthly-balance (never a UNION) + 4 buckets x 3 tables + "
          "6 small singles",
          rc == 0 and "87 transaction chunks" in dry
          and "3 monthly-balance chunks" in dry
          and "12 account-bucket chunks (3 tables x 4 buckets)" in dry
          and "= 108 chunks" in dry and "raw_balance_202606" in dry
          and "UNION" not in dry and n_est >= 100,
          f"108-chunk plan, {n_est} chunks carry row projections")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        extract_chunked.main(
            ["--months", "202604,202605,202606", "--advisors-file", str(firm),
             "--out", str(TMP / "plan_out2"), "--dry-run", "--buckets", "1"])
    dry1 = buf2.getvalue()
    check("5a no chunk projects above ~2M rows at the default plan; --buckets "
          "raises the split when one does (balance months are the spec's own "
          "~2.9M-per-month design and exempt)",
          "WARNING" not in dry and "WARNING" in dry1
          and "raise --buckets" in dry1 and "raw_acct_eci_rel_b001" in dry1,
          "default plan clean; --buckets 1 trips the >2M warning naming "
          "--buckets")

    # ---- 5b + 5c: resume mid-family; scoped_acct per session -----------------
    adv450 = TMP / "adv450.txt"
    adv450.write_text("\n".join(f"T{i:06d}" for i in range(1, 451)))
    out_dir = TMP / "extract_out"

    class StubCursor:
        executed = 0
        sqls: list[str] = []

        def __init__(self, fail_after):
            self.fail_after = fail_after
            self._rows = None
            self.description = [("a",), ("b",)]

        def execute(self, sql, params=None):
            if sql.startswith("SET"):
                return
            StubCursor.executed += 1
            StubCursor.sqls.append(sql[:60])
            if self.fail_after is not None and StubCursor.executed > self.fail_after:
                raise RuntimeError("PAM authentication failed — token expired")
            self._rows = [("x", i) for i in range(5)]

        def fetchmany(self, n):
            rows, self._rows = (self._rows or []), []
            return rows

        def close(self):
            pass

    class StubConn:
        def __init__(self, fail_after):
            self.fail_after = fail_after

        def cursor(self):
            return StubCursor(self.fail_after)

        def close(self):
            pass

    argv = ["--months", "202604,202605", "--advisors-file", str(adv450),
            "--out", str(out_dir)]
    # plan (Round 5: flags retired): 6 singles + 2 balances + account b1-4 +
    # eci_rel b1-4 + eci_map b1-4 + 6 txn = 26 chunks; 5 setup executes per
    # connection. Fail DURING raw_acct_eci_rel_b003 (chunk 15 = execute 20
    # -> fail_after 19).
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        rc1 = extract_chunked.main(argv, connect=lambda: StubConn(19))
    cp1 = json.loads((out_dir / "extract_checkpoint.json").read_text())
    done1 = set(cp1["completed"])
    execs_run1 = StubCursor.executed
    StubCursor.executed = 0
    StubCursor.sqls = []
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        rc2 = extract_chunked.main(argv, connect=lambda: StubConn(None))
    cp2 = json.loads((out_dir / "extract_checkpoint.json").read_text())
    check("5b a token expiry mid-acct_eci_rel resumes at the NEXT bucket, "
          "never the start of the table",
          rc1 == 3 and "raw_acct_eci_rel_b001" in done1
          and "raw_acct_eci_rel_b002" in done1
          and "raw_acct_eci_rel_b003" not in done1
          and rc2 == 0 and len(cp2["completed"]) == 26
          and StubCursor.executed == 5 + (26 - 14),
          f"first run died in eci_rel_b003 with b001..b002 checkpointed "
          f"({len(done1)}/26); resume ran exactly the {26 - 14} remaining "
          f"chunks (+5 session setup)")
    scoped_runs = sum(1 for s in StubCursor.sqls
                      if s.startswith("CREATE TEMP TABLE scoped_acct"))
    check("5c scoped_acct is recreated per session — the resumed connection "
          "re-ran the setup and its chunks succeeded",
          scoped_runs == 1 and execs_run1 >= 5,
          "setup ran on BOTH connections (a temp table dies with its session; "
          "a token refresh is a reconnect)")

    # ---- 5d: five families read; missing bucket fails; both forms fail -------
    chunked = TMP / "chunked_drop"
    make_chunked_drop(chunked)
    r_ok = run([sys.executable, "scripts/build_real_data.py", "--raw",
                str(chunked), "--out", str(TMP / "built_chunked")])
    single_built = TMP / "built_single"
    fix = TMP / "single_drop"
    shutil.copytree(ROOT / "data/real_test/_raw", fix)
    (fix / "raw_crm_opportunity.csv").rename(fix / "crm_opportunities.csv")
    r_single = run([sys.executable, "scripts/build_real_data.py", "--raw",
                    str(fix), "--out", str(single_built)])

    def rows_of(p: Path):
        with open(p, encoding="utf-8-sig") as f:
            return sorted(tuple(sorted(r.items())) for r in csv.DictReader(f))

    man = json.loads((single_built / "manifest.json").read_text())
    diff_files = [f["file"] for f in man["files"]
                  if rows_of(single_built / f["file"])
                  != rows_of(TMP / "built_chunked" / f["file"])]
    gap = TMP / "gap_drop"
    shutil.copytree(chunked, gap)
    (gap / "raw_acct_eci_rel_b002.csv").unlink()
    r_gap = run([sys.executable, "scripts/build_real_data.py", "--raw",
                 str(gap), "--out", str(TMP / "nope1")])
    both = TMP / "both_drop"
    shutil.copytree(chunked, both)
    shutil.copy(fix / "raw_account.csv", both / "raw_account.csv")
    r_both = run([sys.executable, "scripts/build_real_data.py", "--raw",
                  str(both), "--out", str(TMP / "nope2")])
    check("5d build_real_data reads all five chunk families (chunked == "
          "single-file content); a missing bucket fails; both-forms fails",
          r_ok.returncode == 0 and r_single.returncode == 0 and not diff_files
          and r_gap.returncode == 1 and "missing bucket(s) [2]" in r_gap.stderr
          and r_both.returncode == 1 and "ambiguous" in r_both.stderr,
          "chunked and single builds identical (order-insensitive); gap and "
          "both-forms refused loudly")

    # ---- 5e: every chunk contract-checked individually ------------------------
    bad = TMP / "badcol_drop"
    shutil.copytree(chunked, bad)
    lines = (bad / "raw_acct_eci_rel_b002.csv").read_text().splitlines()
    lines[0] = lines[0].replace("party_eci_id", "party_id")
    (bad / "raw_acct_eci_rel_b002.csv").write_text("\n".join(lines))
    r_badcol = run([sys.executable, "scripts/build_real_data.py", "--raw",
                    str(bad), "--out", str(TMP / "nope3")])
    check("5e every chunk is contract-checked individually — a column "
          "mismatch in bucket 2 fails naming that file",
          r_badcol.returncode == 1
          and "raw_acct_eci_rel_b002.csv" in r_badcol.stderr
          and "party_eci_id" in r_badcol.stderr,
          "bucket 2's header mismatch named in the error, not silently "
          "concatenated")

    # ---- 5f: streaming + the memory guard -------------------------------------
    r_guard = run([sys.executable, "scripts/build_real_data.py", "--raw",
                   str(fix), "--out", str(TMP / "nope4"), "--max-memory-mb", "10"])
    rep = json.loads((TMP / "built_chunked" / "build_report.json").read_text())
    peaks = rep.get("peak_rss_mb_per_entity", {})
    check("5f the build streams with a --max-memory-mb guard: per-entity peak "
          "RSS reported; exceeding the guard fails loudly, never OOM-killed "
          "(12.4M-row proof via --full-scale, output in ROUND_2A_COMPLETE.md)",
          r_guard.returncode == 1 and "MemoryGuardError" in r_guard.stderr
          and "Nothing was committed" in r_guard.stderr
          and set(peaks) >= {"account", "revenue_transaction", "account_month"},
          f"guard trips at 10MB naming the entity; fixture peaks: "
          f"{ {k: f'{v}MB' for k, v in list(peaks.items())[:3]} }...")

    # ---- 5g: account_month month-at-a-time ------------------------------------
    src = build_src
    check("5g account_month processes one month at a time — per-month spills "
          "during the txn pass, only the prior month's map held",
          "_spill_month" in src and "read_spill" in src
          and "prior: dict[tuple, tuple] = {}" in src
          and "new_prior" in src
          and rep["transform_deltas"]["account_month"]["months"] == 3,
          "spill/emit mechanism present; build_report records "
          f"{rep['transform_deltas']['account_month']['pairs']} pairs x 3 months")

    # ---- 5h: disk checks in both scripts --------------------------------------
    r_disk_b = run([sys.executable, "scripts/build_real_data.py", "--raw",
                    str(fix), "--out", str(ROOT / ".tmp_disk_probe")])
    with contextlib.suppress(OSError):
        (ROOT / ".tmp_disk_probe").rmdir()
    r_disk_e = run([sys.executable, "scripts/extract_chunked.py", "--months",
                    "202604", "--advisors-file", str(adv450), "--out",
                    str(ROOT / ".tmp_disk_probe2")])
    with contextlib.suppress(OSError):
        shutil.rmtree(ROOT / ".tmp_disk_probe2")
    skip_ok = run([sys.executable, "scripts/build_real_data.py", "--raw",
                   str(fix), "--out", str(TMP / "skip_ok"), "--skip-disk-check"])
    check("5h both scripts check free disk before starting and refuse under "
          "20 GB; --skip-disk-check overrides",
          r_disk_b.returncode == 1 and "GB free" in r_disk_b.stderr
          and r_disk_e.returncode == 1 and "GB free" in r_disk_e.stderr
          and skip_ok.returncode == 0,
          "both refused on this repo's <20GB filesystem; --skip-disk-check "
          "proceeded")

    # ---- 5i: advisor_flags RETIRED (Round 5 task 1 re-pin — the client now
    # defines the cohort; nothing selects anything, nothing consumes the file)
    from scripts.build_real_data import RAW_CONTRACT
    check("5i raw_advisor_flags + select_cohort RETIRED; build_cohort.py "
          "replaces them (Round 5: the client defines the cohort)",
          "raw_advisor_flags.sql" not in templates()
          and "raw_advisor_flags.csv" not in RAW_CONTRACT
          and not (ROOT / "scripts/select_cohort.py").exists()
          and not (ROOT / "docs/data/extraction/raw_advisor_flags.sql").exists()
          and (ROOT / "scripts/build_cohort.py").exists(),
          "no template, no contract entry, select_cohort.py gone, "
          "build_cohort.py present")

    # ---- 5j: validator V-2 on all five families --------------------------------
    r_vgap = run([sys.executable, "scripts/validate_raw_extracts.py", "--raw",
                  str(gap)])
    cp_probe = TMP / "cp_drop"
    shutil.copytree(chunked, cp_probe)
    (cp_probe / "extract_checkpoint.json").write_text(json.dumps({
        "fingerprint": "x", "completed": {
            "raw_acct_eci_rel_b001": {"rows": 999_999,
                                      "path": "raw_acct_eci_rel_b001.csv"}}}))
    r_vcp = run([sys.executable, "scripts/validate_raw_extracts.py", "--raw",
                 str(cp_probe)])
    check("5j validate_raw_extracts applies V-2 sequence + checkpoint checks "
          "to all five families — a missing eci_rel bucket and a row-count "
          "mismatch on a NON-transaction chunk both fail",
          r_vgap.returncode == 1 and "missing bucket(s) [2]" in r_vgap.stdout
          and r_vcp.returncode == 1
          and "raw_acct_eci_rel_b001" in r_vcp.stdout
          and "checkpoint recorded 999999" in r_vcp.stdout,
          "gap fails V-1/V-2; doctored checkpoint rows fail V-2 naming the "
          "eci_rel bucket")

    # ---- 6: manifest phase field ------------------------------------------------
    fix_man = json.loads((ROOT / "data/real_test/manifest.json").read_text())
    ok6 = all(
        all(e.get("phase") == (1 if e["kind"] == "vertex" else 2)
            for e in m["files"])
        for m in (mock_manifest, fix_man))
    check("6  manifest carries a phase field — every vertex phase 1, every "
          "edge phase 2 (committed mock + fixture manifests)", ok6,
          f"{sum(1 for e in mock_manifest['files'] if e.get('phase') == 1)} "
          f"phase-1 / {sum(1 for e in mock_manifest['files'] if e.get('phase') == 2)} "
          f"phase-2 in data/manifest.json")

    # ---- 7 + 8: refusal + --max-parallel -----------------------------------------
    dataset = TMP / "dataset"
    dataset.mkdir()
    for sub in ("vertices", "edges"):
        shutil.copytree(single_built / sub, dataset / sub)
    shutil.copy(single_built / "manifest.json", dataset / "manifest.json")
    shutil.copy(single_built / "build_report.json", dataset / "build_report.json")
    r_refuse = run([sys.executable, "-c", f"""
import os, sys
os.environ["DATA_DIR"] = r"{dataset}"
os.environ["SQLITE_DB_PATH"] = r"{dataset}/checkpoints/refusal.db"
sys.path.insert(0, r"{ROOT}")
from scripts.load_real_data import assert_phase_complete
from app.ingestion.entity_registry import list_entity_configs
from app.ingestion.checkpoint_repository import CheckpointRepository
try:
    assert_phase_complete(list_entity_configs(), CheckpointRepository(), 1)
    print("NO-REFUSAL")
except RuntimeError as e:
    print("REFUSED:", e)
"""])
    check("7  a phase-2 entity refuses to start while any phase-1 entity is "
          "incomplete — a refusal, not a warning",
          "REFUSED: REFUSING to start phase 2" in r_refuse.stdout
          and "never loaded" in r_refuse.stdout,
          "assert_phase_complete raised on an empty checkpoint db, naming the "
          "incomplete entities")
    load_src = (ROOT / "scripts/load_real_data.py").read_text()
    r_load = run([sys.executable, "scripts/load_real_data.py", "--data-dir",
                  str(dataset), "--fresh", "--max-parallel", "3"])
    check("8  --max-parallel defaults to 3 and is respected (phase-scoped "
          "ThreadPoolExecutor; a worker failure fails the whole phase)",
          'default=3' in load_src
          and "ThreadPoolExecutor(max_workers=args.max_parallel)" in load_src
          and "stop.set()" in load_src
          and r_load.returncode == 0
          and "phase 1: 18 entities, up to 3 in parallel" in r_load.stdout
          and "phase 2: 31 entities, up to 3 in parallel" in r_load.stdout
          and "mismatches=0" in r_load.stdout,
          "full fixture load under the parallel loader: 49 targets, 0 "
          "mismatches; stop-flag failure semantics in place")

    # ---- 9 + 10: reconcile + baseline ---------------------------------------------
    env9 = {"DATA_DIR": str(dataset),
            "SQLITE_DB_PATH": str(dataset / "checkpoints" / "ingestion.db")}
    r_rec = run([sys.executable, "scripts/reconcile_load.py", "--raw", str(fix),
                 "--data-dir", str(dataset), "--no-baseline"], env=env9)
    bad_ds = TMP / "dataset_bad"
    shutil.copytree(dataset, bad_ds)
    rep_bad = json.loads((bad_ds / "build_report.json").read_text())
    rep_bad["transform_deltas"]["revenue_transaction"]["rows"] -= 40_000
    (bad_ds / "build_report.json").write_text(json.dumps(rep_bad))
    r_rec_bad = run([sys.executable, "scripts/reconcile_load.py", "--raw",
                     str(fix), "--data-dir", str(bad_ds), "--no-baseline"],
                    env={"DATA_DIR": str(bad_ds),
                         "SQLITE_DB_PATH": str(dataset / "checkpoints" / "ingestion.db")})
    check("9  reconcile_load compares source / extracted / loaded (CRM + NNM "
          "included) and fails HARD naming the entity and the numbers",
          r_rec.returncode == 0 and "RECONCILIATION PASSED" in r_rec.stdout
          and "advisor_nnm (four NNM flat files)" in r_rec.stdout
          and "opportunity (CRM flat file)" in r_rec.stdout
          and "*_CWM_INVALID kept" in r_rec.stdout
          and r_rec_bad.returncode == 1
          and "RECONCILIATION FAILED" in r_rec_bad.stdout
          and "revenue_transaction" in r_rec_bad.stdout,
          "clean load PASSES (49 targets incl. both flat-file sources); a "
          "simulated 40k silent drop FAILS naming revenue_transaction")
    r_base = run([sys.executable, "scripts/reconcile_load.py", "--raw",
                  str(fix), "--data-dir", str(dataset)], env=env9)
    committed = run(["git", "ls-files", "--error-unmatch",
                     "docs/data/extraction/EXPECTED_COUNTS.json"])
    check("10 the expected-count baseline is committed and USED — without "
          "--no-baseline the fixture drop fails against the measured client "
          "counts, proving the comparison is live",
          committed.returncode == 0 and r_base.returncode == 1
          and "committed baseline" in r_base.stdout
          and "12436738" in r_base.stdout.replace(",", ""),
          "baseline committed; fixture vs 12,436,738-row baseline correctly "
          "mismatches")

    # ---- 11: deferred by operator instruction --------------------------------------
    print("SKIP  11 COPILOT_EXTRACTION_GUIDE.md — Task 5 DELIBERATELY "
          "DEFERRED (operator: written separately after reviewing the changed "
          "scripts, so it describes what exists)")

    # ---- optional: the 12.4M-row streaming proof -------------------------------
    if args.full_scale:
        print("\n--full-scale: generating + building a 12.4M-row transaction "
              "set (this is the long pole; output recorded in "
              "ROUND_2A_COMPLETE.md)")
        r_fs = run([sys.executable, "scripts/make_scale_proof.py"])
        print(r_fs.stdout[-4000:])
        check("5f-FULL 12.4M-row build stays under the 4096MB guard",
              r_fs.returncode == 0, r_fs.stderr[-300:])

    shutil.rmtree(TMP, ignore_errors=True)
    n = 16
    print(f"\n{len(FAILURES)} FAILURE(S) of {n}" if FAILURES
          else f"\n{n}/{n} checks passed (check 11 deferred by operator "
               f"instruction)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

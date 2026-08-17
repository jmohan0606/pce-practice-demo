"""Round F task 4.3 — build data/real/{vertices,edges}/ + manifest.json from raw extracts.

    python3 scripts/build_real_data.py [--raw data/real/_raw] [--out data/real] [--seed 42]

THE MISSING MIDDLE of the real-data path (ROUND_D_EXTRACTION.md §1): a human runs the
SQL in docs/data/extraction/ against the client's PostgreSQL and drops the results as
CSV into data/real/_raw/; this script turns those source-shaped raw extracts into the
graph-shaped vertex/edge CSV set + manifest that the EXISTING manifest-driven ingestion
pipeline consumes unchanged (same manifest structure scripts/generate_mock_data.py
produces).

Contract: RAW_CONTRACT below — the raw filenames with their exact expected columns.
A missing file or column raises ColumnMismatchError naming both. Never a silent
partial build: NOTHING is written until every §5 validation passes.

Transformations (ROUND_D_EXTRACTION.md §2 — all in Python, none in SQL):
  - normalize_account_key() from app/shared/ids.py on every account column; *_raw kept
  - credited / non-credited split on reason_cd == '__NONE__'
  - month_id from trade_dt, never proc_dt
  - product model IMPORTED from app/revenue/products.py (never retyped)
  - monthly_revenue aggregated from the transaction rows already built, never re-queried
  - prior_end_balance / prior_credited_amt COMPUTED from the previous month; 0 for the
    baseline month; present_prior_month=false for every baseline-month row
  - CRM opportunities transformed from raw_crm_opportunity.csv (Round F2): invalid
    advisor suffix stripped with the raw kept + advisor_valid=false + count REPORTED
    (never dropped, never silently joined); stage_group derived in app/shared/crm.py;
    is_stalled = days_to_close < 0; ai_read columns left EMPTY at build — the one-time
    interpretation pass runs at ingestion, not here
  - NNM rows parsed from the four delivered ECNNM_/NBNNM_/YINNM_/FSNNM_*.txt files via
    scripts/parse_nnm.py (H header as-of, D-prefix strip, negatives preserved)
  - all 29 edge files derived from the vertex rows; dropped-edge count printed per file
  - trades are NEVER joined to team agreements (post_split_credited_amt already carries
    the split; the join fans out one row per secondary member)
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.revenue.aggregation import build_monthly_revenue, verify_against_transactions  # noqa: E402
from app.revenue.products import (  # noqa: E402
    UNMAPPED_GROUP_ID,
    class_for_group,
    make_product_id,
    product_group_rows,
    resolve_product,
    revenue_class_rows,
    split_product_id,
)
from app.shared.ids import normalize_account_key  # noqa: E402
from app.shared.crm import stage_group_for, strip_invalid_advisor_suffix  # noqa: E402

# Round F2: the NNM parser is Subagent B's module — imported, never retyped.
sys.path.insert(0, str(ROOT / "scripts"))
import parse_nnm  # noqa: E402

SCOPE_FROM, SCOPE_TO = date(2026, 4, 1), date(2026, 7, 1)
OWNER_ROLE_CODES = {"001", "151", "201"}


class ColumnMismatchError(Exception):
    """A raw extract is missing, or missing a contracted column. Names both."""


class ValidationFailure(Exception):
    """A §5 validation failed — the dataset is NOT written."""


# ---------------------------------------------------------------- RAW_CONTRACT
# The raw extract filenames with their exact expected columns (source-shaped —
# the SELECT lists of docs/data/extraction/*.sql). raw_advisor_flags.csv is the
# step-1 cohort-selection extract (scripts/select_cohort.py reads it); it is
# still contracted here so a build against an incomplete drop fails loudly.
FLAG_COLUMNS = [
    "has_fee_reduction_gt10", "has_recorded_grid_reduction", "has_transfer_in",
    "has_transfer_out", "has_new_account", "has_zeroed_account",
    "has_team_agreement", "has_flows", "has_non_credited",
]

RAW_CONTRACT: dict[str, list[str]] = {
    "raw_advisor_flags.csv": ["advisor_sid", "rep_code", "advisor_name",
                              "total_credited_amt", *FLAG_COLUMNS],
    "raw_advisor.csv": ["advisor_sid", "rep_code", "advisor_name", "branch_cd",
                        "employee_id", "in_cohort", "job_code"],
    "raw_account.csv": ["account_no", "account_class_cd", "account_class_nm",
                        "account_lob_cd", "account_purpose_cd", "managed_platform_cd",
                        "service_channel_cd", "account_open_dt", "primary_eci_id"],
    "raw_product_hierarchy.csv": ["product_cd", "product_sub_cd", "product_name",
                                  "sor", "file_key", "grid_type",
                                  "l1_pay_type_cd", "l2_pay_type_cd"],
    "raw_revenue_transaction.csv": ["trade_ref_no", "split_seq_no", "advisor_sid",
                                    "account_no", "product_cd", "product_sub_cd",
                                    "trade_dt", "proc_dt", "post_split_credited_amt",
                                    "pre_split_credited_amt", "split_pct", "reason_cd",
                                    "standard_rate_bps", "client_rate_bps",
                                    "discount_amt", "eff_disc_pct", "grid_reduction",
                                    "rpg", "concession_type", "file_key",
                                    "trade_description"],
    "raw_rr_changes.csv": ["occd_cd", "account_no", "transfer_ts", "seq_no",
                           "from_rr", "from_mem_sid", "to_rr", "to_mem_sid"],
    "raw_monthly_balance.csv": ["month_id", "acct_id", "acct_bal"],
    "raw_month_meta.csv": ["month_id", "start_dt", "end_dt", "trading_days"],
    "raw_acct_eci_rel.csv": ["account_number", "party_eci_id",
                             "enterprise_relationship_code", "party_role_name",
                             "client_employee_ind"],
    # source column IS new_exst_adv_clnt_in_cyr — graph column has no _cyr; the
    # rename happens here (ROUND_D_EXTRACTION.md §3 correction). eci_nb -> eci_id.
    "raw_acct_eci_map.csv": ["bus_dt", "wm_src_sys_cd", "wm_acct_src_nb", "eci_nb",
                             "new_exst_adv_clnt_in_cyr"],
    "raw_team_agreement.csv": ["agreement_id", "team_rep_cd", "team_agreement_typ",
                               "team_agreement_status_cd", "prm_standard_id",
                               "prm_share_pct", "sec_standard_id", "sec_share_pct",
                               "start_ts", "end_ts"],
    "raw_adv_flows.csv": ["advisor_sid", "month_id", "flow_product_cd",
                          "flow_product_desc", "comp_group_type", "total_inflows",
                          "total_outflows", "total_net_flows", "credited_flows",
                          "departed_advisor_sid", "departed_advisor_excl_am",
                          "lob_trfr_excl_am", "oi_pa_referral_cap_adj_am",
                          "large_flow_cap_adj_am", "forced_closure_excl_am"],
    # Round F2 — cohort-filtered CRM extract (docs/data/extraction/raw_crm_opportunity.sql)
    "raw_crm_opportunity.csv": ["opportunity_id", "eci_id", "ownersid",
                                "account_record_type", "product_service_type",
                                "stage_name", "amount", "actual_assets",
                                "anticipated_investment_dt", "created_dt",
                                "last_modified_dt", "date_of_last_contact",
                                "days_to_close", "comments"],
}
# Round F2 — the four NNM files are DELIVERED pipe-delimited .txt files, not SQL
# extract CSVs; contracted here by prefix so a missing file fails loudly.
NNM_RAW_PREFIXES = tuple(sorted(parse_nnm.CATEGORY_BY_PREFIX))

# Round 1 (schema freeze) task 5 — THREE source kinds land in ONE directory
# (data/real/_raw/), each detected by filename pattern:
#   raw_*.csv                        the chunked PostgreSQL extracts
#   ECNNM_/NBNNM_/YINNM_/FSNNM_*.txt the four NNM files, ORIGINAL names kept
#                                    (the category prefix is the identity)
#   crm_opportunities.csv            the CRM opportunity export, original name
# The transaction table may arrive as extract_chunked.py chunks
# (raw_txn_<month>_b<batch>.csv) instead of one raw_revenue_transaction.csv;
# every chunk is contract-checked and they concatenate in sorted order.
TXN_CHUNK_GLOB = "raw_txn_*_b*.csv"
CRM_EXPORT_NAME = "crm_opportunities.csv"
CRM_LEGACY_NAME = "raw_crm_opportunity.csv"


def detect_sources(raw_dir: Path) -> dict:
    """Detect the three source kinds by filename pattern; fail loudly on an
    ambiguous or incomplete drop BEFORE anything is read."""
    txn_chunks = sorted(raw_dir.glob(TXN_CHUNK_GLOB))
    txn_single = raw_dir / "raw_revenue_transaction.csv"
    if txn_chunks and txn_single.exists():
        raise ColumnMismatchError(
            f"both raw_revenue_transaction.csv AND {len(txn_chunks)} "
            f"raw_txn_*_b*.csv chunks exist in {raw_dir} — ambiguous: remove "
            f"one form (the chunks are extract_chunked.py's output)")
    crm_new = raw_dir / CRM_EXPORT_NAME
    crm_legacy = raw_dir / CRM_LEGACY_NAME
    if crm_new.exists() and crm_legacy.exists():
        raise ColumnMismatchError(
            f"both {CRM_EXPORT_NAME} and {CRM_LEGACY_NAME} exist in {raw_dir} "
            f"— ambiguous: keep the original export name {CRM_EXPORT_NAME}")
    if not crm_new.exists() and not crm_legacy.exists():
        raise ColumnMismatchError(
            f"CRM opportunity export missing from {raw_dir}: expected "
            f"{CRM_EXPORT_NAME} (the export's original name; contracted "
            f"columns: {RAW_CONTRACT[CRM_LEGACY_NAME]})")
    # Three of four NNM files present would otherwise load silently incomplete
    # — build_advisor_nnm re-checks, but the drop is validated up front here.
    present = {f.name[:5].upper() for f in raw_dir.glob("*NNM_*.txt")}
    missing = [p for p in NNM_RAW_PREFIXES if p not in present]
    if missing:
        raise ColumnMismatchError(
            f"NNM category file(s) missing from {raw_dir}: {missing} — all "
            f"four of {list(NNM_RAW_PREFIXES)} are required (original "
            f"filenames, e.g. ECNNM_20260630.txt); three of four would load "
            f"silently incomplete, so the build refuses to start")
    return {
        "txn_chunks": txn_chunks,
        "crm_file": (crm_new if crm_new.exists() else crm_legacy).name,
        "nnm_files": sorted(f.name for f in raw_dir.glob("*NNM_*.txt")),
    }


def read_txn_raw(raw_dir: Path, txn_chunks: list[Path]) -> list[dict]:
    """The transaction extract: one file, or extract_chunked.py's chunks
    concatenated in sorted order — each chunk enforces the full contract."""
    if not txn_chunks:
        return read_raw(raw_dir, "raw_revenue_transaction.csv")
    expected = RAW_CONTRACT["raw_revenue_transaction.csv"]
    rows: list[dict] = []
    for path in txn_chunks:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = [h.strip() for h in (reader.fieldnames or [])]
            missing = [c for c in expected if c not in header]
            if missing:
                raise ColumnMismatchError(
                    f"transaction chunk '{path.name}' is missing contracted "
                    f"column(s) {missing} — found columns {header}")
            rows.extend({(k or "").strip(): (v or "").strip()
                         for k, v in row.items() if k} for row in reader)
    print(f"transaction extract: {len(txn_chunks)} chunk file(s) -> {len(rows)} rows")
    return rows


def read_raw(raw_dir: Path, filename: str) -> list[dict]:
    """Read one raw extract, enforcing RAW_CONTRACT loudly (never partial)."""
    expected = RAW_CONTRACT[filename]
    path = raw_dir / filename
    if not path.exists():
        raise ColumnMismatchError(
            f"missing raw extract file '{filename}' (expected at {path}; "
            f"contracted columns: {expected})"
        )
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in expected if c not in header]
        if missing:
            raise ColumnMismatchError(
                f"raw extract file '{filename}' is missing contracted column(s) "
                f"{missing} — found columns {header}"
            )
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
                for row in reader]


# ----------------------------------------------------------------- helpers
def money(x: float) -> str:
    return f"{round(x, 2):.2f}"


def bl(b: bool) -> str:
    return "true" if b else "false"


def as_bool(v: str) -> bool:
    return str(v).strip().lower() in ("true", "t", "1", "y", "yes")


def num(v: str) -> float:
    v = (v or "").strip()
    return float(v) if v else 0.0


def parse_dt(v: str) -> datetime | None:
    v = (v or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %I:%M:%S %p", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def ts(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def month_of(dt: datetime) -> str:
    return dt.strftime("%Y%m")


def prior_month(month_id: str) -> str:
    y, m = int(month_id[:4]), int(month_id[4:])
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y}{m:02d}"


# ------------------------------------------------------------- vertex builders
def build_months(meta_rows: list[dict]) -> list[dict]:
    rows = []
    ordered = sorted(meta_rows, key=lambda r: r["month_id"])
    for i, r in enumerate(ordered):
        start = parse_dt(r["start_dt"])
        end = parse_dt(r["end_dt"])
        rows.append({
            "month_id": r["month_id"],
            "month_name": datetime.strptime(r["month_id"], "%Y%m").strftime("%b %Y"),
            "start_dt": ts(start), "end_dt": ts(end),
            "trading_days": str(int(num(r["trading_days"]))),
            "is_baseline": bl(i == 0),
            # client Phase 0 confirmed all three months COMPLETE (30/31/30) —
            # is_partial=false for every month (ROUND_D_EXTRACTION.md §3).
            "is_partial": bl(False),
        })
    return rows


def build_products(hier_rows: list[dict], txns_products: set[str]) -> list[dict]:
    rows, seen = [], set()
    for r in hier_rows:
        if (r.get("grid_type") or "PRODUCT_TYPE") != "PRODUCT_TYPE":
            continue
        pid = make_product_id(r["product_cd"], r["product_sub_cd"])
        if pid in seen:
            continue
        seen.add(pid)
        rows.append({
            "product_id": pid, "product_cd": r["product_cd"],
            "product_sub_cd": r["product_sub_cd"],
            "product_name": r["product_name"], "sor": r["sor"],
            "file_key": r["file_key"] or "product_hierarchy",
            "group_id": resolve_product(r["product_cd"], r["product_sub_cd"]),
            "grid_type": r.get("grid_type") or "PRODUCT_TYPE",
            # Round 1b: the export's parallel pay-type taxonomy, carried as-is
            "l1_pay_type_cd": r["l1_pay_type_cd"],
            "l2_pay_type_cd": r["l2_pay_type_cd"],
        })
    # products traded but absent from the hierarchy: kept VISIBLE as unmapped
    # vertices (never dropped — a missing product row silently drops every
    # txn_of_product / mr_of_product edge for that product).
    for pid in sorted(txns_products - seen):
        cd, sub = split_product_id(pid)
        rows.append({
            "product_id": pid, "product_cd": cd, "product_sub_cd": sub,
            "product_name": f"Unmapped product {pid}", "sor": "",
            "file_key": "txn_only", "group_id": resolve_product(cd, sub),
            "grid_type": "PRODUCT_TYPE",
            # not in the hierarchy export -> no pay-type codes, never guessed
            "l1_pay_type_cd": "", "l2_pay_type_cd": "",
        })
    return rows


def build_transactions(raw: list[dict]) -> list[dict]:
    txns = []
    for r in raw:
        trade_dt = parse_dt(r["trade_dt"])
        proc_dt = parse_dt(r["proc_dt"])
        if trade_dt is None:
            continue
        if not (SCOPE_FROM <= trade_dt.date() < SCOPE_TO):
            continue
        # month from trade_dt, NEVER proc_dt (proc runs after month end)
        month_id = month_of(trade_dt)
        reason = r["reason_cd"].strip() or "__NONE__"
        amount = num(r["post_split_credited_amt"])
        credited = reason == "__NONE__"
        acct_key = normalize_account_key(r["account_no"])
        dtp = (proc_dt.date() - trade_dt.date()).days if proc_dt else 0
        txns.append({
            "txn_id": f"{r['trade_ref_no']}|{r['split_seq_no']}|{r['advisor_sid']}",
            "trade_ref_no": r["trade_ref_no"], "split_seq_no": r["split_seq_no"],
            "advisor_sid": r["advisor_sid"], "acct_key": acct_key,
            "product_id": make_product_id(r["product_cd"], r["product_sub_cd"]),
            "month_id": month_id, "trade_dt": ts(trade_dt), "proc_dt": ts(proc_dt),
            "days_to_process": str(dtp),
            "credited_amt": money(amount if credited else 0.0),
            "non_credited_amt": money(0.0 if credited else amount),
            "pre_split_amt": money(num(r["pre_split_credited_amt"])),
            "split_pct": r["split_pct"] or "0",
            "reason_cd": reason, "is_credited": bl(credited),
            "standard_rate_bps": money(num(r["standard_rate_bps"])),
            "client_rate_bps": money(num(r["client_rate_bps"])),
            "discount_amt": money(num(r["discount_amt"])),
            "eff_disc_pct": f"{num(r['eff_disc_pct']):.1f}",
            "grid_reduction": money(num(r["grid_reduction"])),
            "rpg": r["rpg"], "concession_type": r["concession_type"],
            "file_key": r["file_key"] or "daily_trade_details",
            "trade_description": r["trade_description"],
        })
    return txns


def build_accounts(raw: list[dict]) -> list[dict]:
    rows, seen = [], set()
    for r in raw:
        key = normalize_account_key(r["account_no"])
        if not key or key in seen:
            continue
        seen.add(key)
        opened = parse_dt(r["account_open_dt"])
        rows.append({
            "acct_key": key, "account_no_raw": r["account_no"],
            "account_class_cd": r["account_class_cd"],
            "account_class_nm": r["account_class_nm"],
            "account_lob_cd": r["account_lob_cd"],
            "account_purpose_cd": r["account_purpose_cd"],
            "managed_platform_cd": r["managed_platform_cd"],
            "service_channel_cd": r["service_channel_cd"],
            "account_open_dt": ts(opened),
            "is_managed": bl(bool(r["managed_platform_cd"].strip())),
            "opened_in_scope": bl(bool(opened) and SCOPE_FROM <= opened.date() < SCOPE_TO),
            "primary_eci_id": r["primary_eci_id"],
        })
    return rows


def build_eci_rel(raw: list[dict]) -> list[dict]:
    rows, seen = [], set()
    for r in raw:
        key = normalize_account_key(r["account_number"])
        rel_id = f"{key}|{r['party_eci_id']}|{r['enterprise_relationship_code']}"
        if not key or rel_id in seen:
            continue
        seen.add(rel_id)
        rows.append({
            "rel_id": rel_id, "acct_key": key, "eci_id": r["party_eci_id"],
            "enterprise_relationship_code": r["enterprise_relationship_code"],
            "party_role_name": r["party_role_name"],
            "client_employee_ind": r["client_employee_ind"],
            "is_owner_role": bl(r["enterprise_relationship_code"] in OWNER_ROLE_CODES),
        })
    return rows


def build_eci_map(raw: list[dict]) -> list[dict]:
    # latest bus_dt per (wm_src_sys_cd, wm_acct_src_nb) — the SQL already filters,
    # but a daily-snapshot re-drop must not corrupt the build, so enforce here too.
    latest: dict[tuple[str, str], dict] = {}
    for r in raw:
        k = (r["wm_src_sys_cd"], r["wm_acct_src_nb"])
        if k not in latest or (parse_dt(r["bus_dt"]) or datetime.min) > (parse_dt(latest[k]["bus_dt"]) or datetime.min):
            latest[k] = r
    rows = []
    for (sys_cd, src_nb), r in sorted(latest.items()):
        key = normalize_account_key(src_nb)
        bus = ts(parse_dt(r["bus_dt"]))
        rows.append({
            "map_id": f"{bus}|{sys_cd}|{key}",
            "acct_src_key": key, "acct_src_raw": src_nb,
            "wm_src_sys_cd": sys_cd, "eci_id": r["eci_nb"], "bus_dt": bus,
            # source new_exst_adv_clnt_in_cyr -> graph new_exst_adv_clnt_in
            "new_exst_adv_clnt_in": r["new_exst_adv_clnt_in_cyr"],
        })
    return rows


def build_transfers(raw: list[dict]) -> list[dict]:
    rows, seen = [], set()
    for r in raw:
        t = parse_dt(r["transfer_ts"])
        if t is None or not (SCOPE_FROM <= t.date() < SCOPE_TO):
            continue
        key = normalize_account_key(r["account_no"])
        tid = f"{r['occd_cd']}|{key}|{r['from_rr']}|{r['seq_no']}|{t.strftime('%Y%m%d%H%M%S')}"
        if tid in seen:
            continue
        seen.add(tid)
        rows.append({
            "transfer_id": tid, "acct_key": key,
            "from_advisor_sid": r["from_mem_sid"], "to_advisor_sid": r["to_mem_sid"],
            "from_rr": r["from_rr"], "to_rr": r["to_rr"],
            "transfer_ts": ts(t), "month_id": month_of(t),
            "is_intra_team": bl(r["from_rr"] == r["to_rr"]),
            "occd_cd": r["occd_cd"],
        })
    return rows


def build_team_agreements(raw: list[dict]) -> list[dict]:
    rows, seen = [], set()
    for r in raw:
        start = parse_dt(r["start_ts"])
        key = (f"{r['agreement_id']}|{r['team_rep_cd']}|{r['prm_standard_id']}|"
               f"{r['sec_standard_id']}|{start.strftime('%Y%m%d') if start else ''}")
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "agreement_key": key, "agreement_id": r["agreement_id"],
            "team_rep_cd": r["team_rep_cd"], "agreement_type": r["team_agreement_typ"],
            "status_cd": r["team_agreement_status_cd"],
            "prm_advisor_sid": r["prm_standard_id"], "prm_share_pct": r["prm_share_pct"],
            "sec_advisor_sid": r["sec_standard_id"], "sec_share_pct": r["sec_share_pct"],
            "start_ts": ts(start), "end_ts": ts(parse_dt(r["end_ts"])),
        })
    return rows


def build_flows(raw: list[dict], month_ids: list[str]) -> list[dict]:
    rows, seen = [], set()
    for r in raw:
        if r["month_id"] not in month_ids:
            continue  # April + May only exist; anything else is out of scope
        afm_id = f"{r['advisor_sid']}|{r['month_id']}|{r['flow_product_cd']}"
        if afm_id in seen:
            continue
        seen.add(afm_id)
        rows.append({
            "afm_id": afm_id, "advisor_sid": r["advisor_sid"], "month_id": r["month_id"],
            "flow_product_cd": r["flow_product_cd"],
            "flow_product_desc": r["flow_product_desc"],
            "comp_group_type": r["comp_group_type"],
            "total_inflows": money(num(r["total_inflows"])),
            "total_outflows": money(num(r["total_outflows"])),
            "total_net_flows": money(num(r["total_net_flows"])),
            "credited_flows": money(num(r["credited_flows"])),
            "departed_advisor_sid": r["departed_advisor_sid"],
            "departed_advisor_excl_am": money(num(r["departed_advisor_excl_am"])),
            "lob_trfr_excl_am": money(num(r["lob_trfr_excl_am"])),
            "oi_pa_referral_cap_adj_am": money(num(r["oi_pa_referral_cap_adj_am"])),
            "large_flow_cap_adj_am": money(num(r["large_flow_cap_adj_am"])),
            "forced_closure_excl_am": money(num(r["forced_closure_excl_am"])),
        })
    return rows


def build_account_month(
    txns: list[dict], balances: list[dict], transfers: list[dict], month_ids: list[str]
) -> tuple[list[dict], int]:
    """(acct_key, advisor_sid, month_id) grain. end_balance from the balance
    extract; credited/txn_count from the transaction rows; prior_* COMPUTED from
    the previous month's row (0 for the baseline month); present_prior_month =
    same (acct, advisor) existed in the previous month (false for baseline).

    Returns (rows, skipped_balance_rows) — balance rows whose account has no
    resolvable advisor anywhere in scope are skipped WITH A PRINTED COUNT.
    """
    per_txn: dict[tuple[str, str, str], dict] = defaultdict(lambda: {"credited": 0.0, "count": 0})
    advisor_by_acct_month: dict[tuple[str, str], set[str]] = defaultdict(set)
    advisor_by_acct: dict[str, set[str]] = defaultdict(set)
    for t in txns:
        k = (t["acct_key"], t["advisor_sid"], t["month_id"])
        per_txn[k]["credited"] += float(t["credited_amt"])
        per_txn[k]["count"] += 1
        advisor_by_acct_month[(t["acct_key"], t["month_id"])].add(t["advisor_sid"])
        advisor_by_acct[t["acct_key"]].add(t["advisor_sid"])
    for tr in transfers:  # a transferred account's balance belongs to its receiver
        advisor_by_acct[tr["acct_key"]].add(tr["to_advisor_sid"])

    balance: dict[tuple[str, str], float] = {}
    skipped = 0
    keys: set[tuple[str, str, str]] = set(per_txn)
    for b in balances:
        acct = normalize_account_key(b["acct_id"])
        month = b["month_id"]
        if month not in month_ids or not acct:
            continue
        balance[(acct, month)] = balance.get((acct, month), 0.0) + num(b["acct_bal"])
        advisors = (advisor_by_acct_month.get((acct, month))
                    or advisor_by_acct.get(acct) or set())
        if not advisors:
            skipped += 1
            continue
        for sid in advisors:
            keys.add((acct, sid, month))

    # carry every (acct, advisor) forward through all scope months so zeroed /
    # gone-quiet accounts still get rows (LOST_ACCOUNT needs them)
    pairs = {(a, s) for a, s, _ in keys}
    rows = []
    for acct, sid in sorted(pairs):
        prior_bal, prior_credited, prior_present = 0.0, 0.0, False
        for i, month in enumerate(month_ids):
            agg = per_txn.get((acct, sid, month), {"credited": 0.0, "count": 0})
            bal = balance.get((acct, month), 0.0)
            present = (acct, sid, month) in keys or bool(agg["count"])
            rows.append({
                "am_id": f"{acct}|{sid}|{month}",
                "acct_key": acct, "advisor_sid": sid, "month_id": month,
                "end_balance": money(bal), "credited_amt": money(agg["credited"]),
                "txn_count": str(agg["count"]), "is_zero_balance": bl(bal == 0.0),
                # false for EVERY baseline-month row, else: did the prior month row exist
                "present_prior_month": bl(i > 0 and prior_present),
                "prior_end_balance": money(prior_bal if i > 0 else 0.0),
                "prior_credited_amt": money(prior_credited if i > 0 else 0.0),
            })
            prior_bal, prior_credited, prior_present = bal, agg["credited"], present
    return rows, skipped


def build_households(accounts: list[dict], rels: list[dict], maps: list[dict]) -> list[dict]:
    counts: dict[str, set[str]] = defaultdict(set)
    for r in rels:
        counts[r["eci_id"]].add(r["acct_key"])
    for a in accounts:
        if a["primary_eci_id"]:
            counts[a["primary_eci_id"]].add(a["acct_key"])
    for m in maps:
        counts.setdefault(m["eci_id"], set())
    return [{"eci_id": e, "account_count": str(len(s))} for e, s in sorted(counts.items()) if e]


def build_rpgs(txns: list[dict]) -> list[dict]:
    accts: dict[str, set[str]] = defaultdict(set)
    for t in txns:
        if t["rpg"]:
            accts[t["rpg"]].add(t["acct_key"])
    return [{"rpg_id": r, "account_count": str(len(s))} for r, s in sorted(accts.items())]


def build_crm_opportunities(raw: list[dict]) -> tuple[list[dict], dict]:
    """Round F2: transform the raw CRM extract. Rows are NEVER dropped: an
    invalid advisor reference keeps its raw value (advisor_valid=false) and is
    counted for the validation report. ai_read columns stay EMPTY — the
    one-time interpretation pass runs at ingestion, never at build."""
    rows, invalid, ungrouped = [], 0, 0
    for r in raw:
        sid, valid = strip_invalid_advisor_suffix(r["ownersid"])
        if not valid:
            invalid += 1
        group = stage_group_for(r["stage_name"])
        if group == "UNGROUPED":
            ungrouped += 1
        days = int(float(r["days_to_close"] or 0))
        rows.append({
            "opportunity_id": r["opportunity_id"], "eci_id": r["eci_id"],
            "advisor_sid": sid, "advisor_sid_raw": r["ownersid"],
            "advisor_valid": bl(valid),
            "account_record_type": r["account_record_type"],
            "product_service_type": r["product_service_type"],
            "stage_name": r["stage_name"], "stage_group": group,
            "amount": money(num(r["amount"])),
            "actual_assets": money(num(r["actual_assets"])),
            "anticipated_investment_dt": ts(parse_dt(r["anticipated_investment_dt"])),
            "created_dt": ts(parse_dt(r["created_dt"])),
            "last_modified_dt": ts(parse_dt(r["last_modified_dt"])),
            "date_of_last_contact": ts(parse_dt(r["date_of_last_contact"])),
            "days_to_close": str(days), "is_stalled": bl(days < 0),
            "comments": r["comments"],
            "ai_read": "", "ai_read_confidence": "", "ai_read_evidence": "",
            "ai_read_model": "", "data_source": "CRM",
        })
    stats = {"raw_rows": len(raw), "kept_rows": len(rows),
             "invalid_advisor_rows": invalid, "ungrouped_stage_rows": ungrouped}
    return rows, stats


def build_advisor_nnm(raw_dir: Path) -> list[dict]:
    """Round F2: parse the four delivered NNM files (parse_nnm enforces the
    format loudly — H header, content-recognised column line, D-prefix strip,
    negatives preserved). A missing prefix raises before anything is built."""
    present = {f.name[:5].upper() for f in raw_dir.glob("*NNM_*.txt")}
    missing = [p for p in NNM_RAW_PREFIXES if p not in present]
    if missing:
        raise ColumnMismatchError(
            f"NNM raw files missing from {raw_dir}: {missing} — expected all "
            f"four of {list(NNM_RAW_PREFIXES)} (delivered files, no SQL template)")
    return [{**r, "mtd_nnm": f"{r['mtd_nnm']:.2f}", "ytd_nnm": f"{r['ytd_nnm']:.2f}"}
            for r in parse_nnm.parse_nnm_dir(raw_dir)]


# --------------------------------------------------------- columns / ids / edges
# Kept structurally IDENTICAL to scripts/generate_mock_data.py so the manifest
# this script writes is consumed by the ingestion pipeline unchanged.
VERTEX_COLUMNS = {
    "phx_dm_pce_month": ["month_id", "month_name", "start_dt", "end_dt", "trading_days", "is_baseline", "is_partial"],
    "phx_dm_pce_revenue_class": ["class_id", "class_name"],
    "phx_dm_pce_product_group": ["group_id", "group_name", "display_prefix", "class_id", "sort_order", "is_aggregated"],
    "phx_dm_pce_product": ["product_id", "product_cd", "product_sub_cd", "product_name", "sor", "file_key", "group_id", "grid_type", "l1_pay_type_cd", "l2_pay_type_cd"],
    "phx_dm_pce_advisor": ["advisor_sid", "rep_code", "advisor_name", "branch_cd", "employee_id", "in_cohort", "job_code"],
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
    "phx_dm_pce_opportunity": "opportunity_id", "phx_dm_pce_advisor_nnm": "nnm_id",
}

# edge -> (from_type, to_type, source vertex, from_field, to_field)
# _acct_key / _rpg are build-time bookkeeping fields (as in generate_mock_data.py)
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
    "phx_dm_pce_nnm_by_advisor": ("phx_dm_pce_advisor_nnm", "phx_dm_pce_advisor", "phx_dm_pce_advisor_nnm", "nnm_id", "advisor_sid"),
    "phx_dm_pce_nnm_in_month": ("phx_dm_pce_advisor_nnm", "phx_dm_pce_month", "phx_dm_pce_advisor_nnm", "nnm_id", "month_id"),
}


def derive_edges(vertex_rows: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """All 29 edge files from the vertex rows. Returns (edge_rows, dropped_per_file).
    An edge whose to_id is non-blank but missing from its target vertex file is
    DROPPED AND COUNTED — never silently."""
    valid_ids = {t: {r[ID_COLUMNS[t]] for r in vertex_rows[t]} for t in VERTEX_COLUMNS}
    edge_rows: dict[str, list[dict]] = {}
    dropped: dict[str, int] = {}
    for edge_name, (_ftype, ttype, source, ffield, tfield) in EDGES.items():
        rows, seen, n_dropped = [], set(), 0
        for r in vertex_rows[source]:
            fid, tid = r.get(ffield, ""), r.get(tfield, "")
            if not fid or not tid:
                continue  # blank endpoint = no edge (e.g. blank rpg), not a drop
            if tid not in valid_ids[ttype]:
                n_dropped += 1
                continue
            k = (fid, tid)
            if k in seen:
                continue
            seen.add(k)
            rows.append({"from_id": fid, "to_id": tid})
        edge_rows[edge_name] = rows
        dropped[edge_name] = n_dropped
    return edge_rows, dropped


# ----------------------------------------------------------------- validation
def run_validations(vertex_rows: dict[str, list[dict]], edge_rows: dict[str, list[dict]],
                    dropped: dict[str, int], skipped_balance_rows: int,
                    month_ids: list[str]) -> None:
    """The 12 checks of ROUND_D_EXTRACTION.md §5, printed in full. Raises
    ValidationFailure on any hard failure — the dataset is then NOT written."""
    failures: list[str] = []
    txns = vertex_rows["phx_dm_pce_revenue_transaction"]
    print("\n================ VALIDATION (ROUND_D_EXTRACTION.md §5) ================")

    # 1 — row count per file
    n_files = len(vertex_rows) + len(edge_rows)
    print(f"\n 1. row counts ({n_files} files)")
    for t, rows in vertex_rows.items():
        print(f"    vertex {t}: {len(rows)}")
    for e, rows in edge_rows.items():
        print(f"    edge   {e}: {len(rows)}")

    # 2 — primary key uniqueness
    print("\n 2. primary key uniqueness per vertex file")
    for t, rows in vertex_rows.items():
        ids = [r[ID_COLUMNS[t]] for r in rows]
        dups = len(ids) - len(set(ids))
        print(f"    {t}: {dups} duplicates")
        if dups:
            failures.append(f"validation 2: {t} has {dups} duplicate primary keys")

    # 3 — acct_key leading zeros
    bad = 0
    for t, fields in (("phx_dm_pce_account", ["acct_key"]),
                      ("phx_dm_pce_revenue_transaction", ["acct_key"]),
                      ("phx_dm_pce_account_month", ["acct_key"]),
                      ("phx_dm_pce_account_transfer", ["acct_key"]),
                      ("phx_dm_pce_account_eci_rel", ["acct_key"]),
                      ("phx_dm_pce_account_eci_map", ["acct_src_key"])):
        for r in vertex_rows[t]:
            for f in fields:
                v = r.get(f, "")
                if v and v != normalize_account_key(v):
                    bad += 1
    print(f"\n 3. acct_key values with leading zeros: {bad} (must be 0)")
    if bad:
        failures.append(f"validation 3: {bad} account keys not normalised")

    # 4 — reason_cd empty strings
    empty_reason = sum(1 for t in txns if not t["reason_cd"].strip())
    print(f"\n 4. reason_cd empty strings: {empty_reason} (must be 0 — blank becomes '__NONE__')")
    if empty_reason:
        failures.append(f"validation 4: {empty_reason} blank reason_cd rows")

    # 5 — reason-coded rows must carry zero credited_amt
    bad5 = sum(1 for t in txns if t["reason_cd"] != "__NONE__" and float(t["credited_amt"]) != 0.0)
    print(f"\n 5. rows where reason_cd != '__NONE__' AND credited_amt != 0: {bad5} (must be 0)")
    if bad5:
        failures.append(f"validation 5: {bad5} reason-coded rows with credited_amt")

    # 6 — unmapped products, kept and listed, never dropped
    print("\n 6. product_ids in group 'unmapped' (kept, never dropped)")
    unmapped_counts: dict[str, int] = defaultdict(int)
    for t in txns:
        cd, sub = split_product_id(t["product_id"])
        if resolve_product(cd, sub) == UNMAPPED_GROUP_ID:
            unmapped_counts[t["product_id"]] += 1
    if unmapped_counts:
        for pid, n in sorted(unmapped_counts.items()):
            print(f"    {pid}: {n} rows")
    else:
        print("    none")

    # 7 — monthly_revenue vs independent re-sum of the transaction rows
    check = verify_against_transactions(txns, vertex_rows["phx_dm_pce_monthly_revenue"])
    print(f"\n 7. monthly_revenue vs independent re-sum of transactions: "
          f"{'MATCH' if check['ok'] else 'MISMATCH'}")
    if not check["ok"]:
        for m in check["mismatches"][:5]:
            print(f"    {m}")
        failures.append(f"validation 7: {len(check['mismatches'])} (advisor, month) mismatches")

    # 8 — dropped edges per file
    print("\n 8. dropped edges per file (unresolvable to_id)")
    for e in EDGES:
        print(f"    {e}: dropped {dropped[e]}")
    if skipped_balance_rows:
        print(f"    (account_month: {skipped_balance_rows} balance rows skipped — no resolvable advisor)")

    # 9 — prior_* computed: zero for baseline, populated after
    ams = vertex_rows["phx_dm_pce_account_month"]
    baseline = month_ids[0]
    bad9 = sum(1 for r in ams if r["month_id"] == baseline
               and (float(r["prior_end_balance"]) != 0.0 or float(r["prior_credited_amt"]) != 0.0
                    or r["present_prior_month"] != "false"))
    later_nonzero = sum(1 for r in ams if r["month_id"] != baseline
                        and (float(r["prior_end_balance"]) != 0.0 or float(r["prior_credited_amt"]) != 0.0))
    print(f"\n 9. prior_end_balance/prior_credited_amt: {bad9} non-zero baseline rows (must be 0); "
          f"{later_nonzero} later rows populated (must be > 0)")
    if bad9:
        failures.append(f"validation 9: {bad9} baseline rows carry prior values")
    if later_nonzero == 0 and len(month_ids) > 1:
        failures.append("validation 9: no later-month row has computed prior values")

    # 10 — scenario coverage
    print("\n10. scenario coverage")
    reduced_accts = {t["acct_key"] for t in txns
                     if float(t["standard_rate_bps"]) > 0
                     and (float(t["standard_rate_bps"]) - float(t["client_rate_bps"]))
                     / float(t["standard_rate_bps"]) * 100 > 10}
    recorded_accts = {t["acct_key"] for t in txns
                      if t["acct_key"] in reduced_accts and float(t["grid_reduction"]) != 0.0}
    transfers = vertex_rows["phx_dm_pce_account_transfer"]
    cohort = {a["advisor_sid"] for a in vertex_rows["phx_dm_pce_advisor"] if as_bool(a["in_cohort"])}
    print(f"    accounts with fee reduction >10%: {len(reduced_accts)}; "
          f"with a recorded grid_reduction: {len(recorded_accts)}")
    print(f"    transfers in (to cohort): {sum(1 for t in transfers if t['to_advisor_sid'] in cohort)}; "
          f"out (from cohort): {sum(1 for t in transfers if t['from_advisor_sid'] in cohort)}")
    print(f"    accounts opened in scope: "
          f"{sum(1 for a in vertex_rows['phx_dm_pce_account'] if a['opened_in_scope'] == 'true')}")
    zeroed = {r["acct_key"] for r in ams if r["month_id"] != baseline
              and r["is_zero_balance"] == "true" and float(r["prior_end_balance"]) > 0}
    print(f"    accounts zeroed between months: {len(zeroed)}")
    print(f"    team agreements: {len(vertex_rows['phx_dm_pce_team_agreement'])}")
    flow_advisors = {f['advisor_sid'] for f in vertex_rows['phx_dm_pce_advisor_flow_month']}
    print(f"    advisors with flows: {len(flow_advisors)}")

    # 11 — per-month credited_amt and txn_count (+ sanity anchor)
    print("\n11. per-month credited_amt / txn_count")
    per_month: dict[str, dict] = defaultdict(lambda: {"credited": 0.0, "count": 0})
    for t in txns:
        per_month[t["month_id"]]["credited"] += float(t["credited_amt"])
        per_month[t["month_id"]]["count"] += 1
    for m in month_ids:
        v = per_month.get(m, {"credited": 0.0, "count": 0})
        flag = ""
        if not (1e5 <= v["credited"] <= 1e7):
            flag = ("  << SANITY: outside high-hundreds-of-thousands..low-millions — "
                    "check proc_dt misuse or a team-agreement fan-out")
        print(f"    {m}: credited ${v['credited']:,.2f}  txns {v['count']}{flag}")

    # 12 — trading days per month
    print("\n12. trading days per month")
    distinct_dates: dict[str, set[str]] = defaultdict(set)
    for t in txns:
        distinct_dates[t["month_id"]].add(t["trade_dt"][:10])
    for r in vertex_rows["phx_dm_pce_month"]:
        print(f"    {r['month_id']}: trading_days={r['trading_days']} "
              f"(distinct trade dates seen: {len(distinct_dates.get(r['month_id'], set()))}, "
              f"is_partial={r['is_partial']})")
        if r["is_partial"] != "false":
            failures.append(f"validation 12: {r['month_id']} marked partial — "
                            "client Phase 0 confirmed all three months complete")

    print("\n========================================================================")
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        raise ValidationFailure(f"{len(failures)} validation failure(s) — dataset NOT written")
    print("ALL 12 VALIDATIONS PASSED")


# ----------------------------------------------------------------- write out
def write_csv(path: Path, columns: list[str], rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (bl(v) if isinstance(v, bool) else v) for k, v in r.items()})
    return len(rows)


def build(raw_dir: Path, out_dir: Path, seed: int = 42) -> dict:
    # Round 1 task 5 — detect the three source kinds by filename pattern
    # BEFORE reading anything; an incomplete or ambiguous drop fails here.
    sources = detect_sources(raw_dir)
    print(f"source detection: PostgreSQL extracts raw_*.csv "
          f"({'single transaction file' if not sources['txn_chunks'] else str(len(sources['txn_chunks'])) + ' transaction chunks'}), "
          f"NNM files {sources['nnm_files']}, CRM export {sources['crm_file']}")
    raw = {}
    for name in RAW_CONTRACT:
        if name == "raw_revenue_transaction.csv":
            raw[name] = read_txn_raw(raw_dir, sources["txn_chunks"])
        elif name == CRM_LEGACY_NAME and sources["crm_file"] != CRM_LEGACY_NAME:
            # the export keeps its original name; the contract is unchanged
            expected = RAW_CONTRACT[CRM_LEGACY_NAME]
            path = raw_dir / sources["crm_file"]
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                header = [h.strip() for h in (reader.fieldnames or [])]
                missing = [c for c in expected if c not in header]
                if missing:
                    raise ColumnMismatchError(
                        f"CRM export '{sources['crm_file']}' is missing "
                        f"contracted column(s) {missing} — found columns {header}")
                raw[name] = [{(k or "").strip(): (v or "").strip()
                              for k, v in row.items() if k} for row in reader]
        else:
            raw[name] = read_raw(raw_dir, name)
    print(f"raw contract satisfied: {len(raw)} files read from {raw_dir}")

    meta_rows = sorted(raw["raw_month_meta.csv"], key=lambda r: r["month_id"])
    month_ids = [r["month_id"] for r in meta_rows]

    txns = build_transactions(raw["raw_revenue_transaction.csv"])
    transfers = build_transfers(raw["raw_rr_changes.csv"])
    accounts = build_accounts(raw["raw_account.csv"])
    rels = build_eci_rel(raw["raw_acct_eci_rel.csv"])
    maps = build_eci_map(raw["raw_acct_eci_map.csv"])
    advisors = [{
        "advisor_sid": r["advisor_sid"], "rep_code": r["rep_code"],
        "advisor_name": r["advisor_name"],  # blank stays blank — never invented
        "branch_cd": r["branch_cd"], "employee_id": r["employee_id"],
        "in_cohort": bl(as_bool(r["in_cohort"])),
        "job_code": r["job_code"],  # blank stays blank — never invented
    } for r in raw["raw_advisor.csv"]]

    vertex_rows: dict[str, list[dict]] = {
        "phx_dm_pce_month": build_months(meta_rows),
        "phx_dm_pce_revenue_class": revenue_class_rows(),
        # imported from app/revenue/products.py — never retyped
        "phx_dm_pce_product_group": [
            {**r, "is_aggregated": bl(r["is_aggregated"]), "sort_order": str(r["sort_order"])}
            for r in product_group_rows()
        ],
        "phx_dm_pce_product": build_products(
            raw["raw_product_hierarchy.csv"], {t["product_id"] for t in txns}),
        "phx_dm_pce_advisor": advisors,
        "phx_dm_pce_account": accounts,
        "phx_dm_pce_account_eci_rel": rels,
        "phx_dm_pce_account_eci_map": maps,
        "phx_dm_pce_household": build_households(accounts, rels, maps),
        "phx_dm_pce_rpg": build_rpgs(txns),
        "phx_dm_pce_team_agreement": build_team_agreements(raw["raw_team_agreement.csv"]),
        "phx_dm_pce_revenue_transaction": txns,
        # aggregated from the transaction rows already built, never re-queried
        "phx_dm_pce_monthly_revenue": [
            {**r, "credited_amt": money(r["credited_amt"]),
             "non_credited_amt": money(r["non_credited_amt"]),
             "txn_count": str(r["txn_count"]), "distinct_accounts": str(r["distinct_accounts"])}
            for r in build_monthly_revenue(txns)
        ],
        "phx_dm_pce_account_transfer": transfers,
        "phx_dm_pce_advisor_flow_month": build_flows(raw["raw_adv_flows.csv"], month_ids),
    }
    crm_rows, crm_stats = build_crm_opportunities(raw["raw_crm_opportunity.csv"])
    vertex_rows["phx_dm_pce_opportunity"] = crm_rows
    vertex_rows["phx_dm_pce_advisor_nnm"] = build_advisor_nnm(raw_dir)
    print(f"CRM: {crm_stats['raw_rows']} raw rows -> {crm_stats['kept_rows']} kept "
          f"(0 dropped BY DESIGN); invalid advisor references: "
          f"{crm_stats['invalid_advisor_rows']} (kept + reported); "
          f"UNGROUPED stages: {crm_stats['ungrouped_stage_rows']}")
    ams, skipped_balance_rows = build_account_month(
        txns, raw["raw_monthly_balance.csv"], transfers, month_ids)
    vertex_rows["phx_dm_pce_account_month"] = ams

    # bookkeeping fields for the two indirect edges (as in generate_mock_data.py)
    acct_keys = {a["acct_key"] for a in accounts}
    for m in vertex_rows["phx_dm_pce_account_eci_map"]:
        m["_acct_key"] = m["acct_src_key"] if m["acct_src_key"] in acct_keys else ""
    rpg_by_acct: dict[str, str] = {}
    for t in txns:
        if t["rpg"] and t["acct_key"] not in rpg_by_acct:
            rpg_by_acct[t["acct_key"]] = t["rpg"]
    for a in vertex_rows["phx_dm_pce_account"]:
        a["_rpg"] = rpg_by_acct.get(a["acct_key"], "")

    edge_rows, dropped = derive_edges(vertex_rows)

    # STOP on any failure — nothing is written until this passes
    run_validations(vertex_rows, edge_rows, dropped, skipped_balance_rows, month_ids)

    manifest_files, order = [], 0
    for target, columns in VERTEX_COLUMNS.items():
        order += 1
        rel = f"vertices/{target}.csv"
        n = write_csv(out_dir / rel, columns, vertex_rows[target])
        manifest_files.append({
            "file": rel, "kind": "vertex", "target": target,
            "id_column": ID_COLUMNS[target], "columns": {c: c for c in columns},
            "expected_rows": n, "order": order,
        })
    for edge_name, (ftype, ttype, _s, _f, _t) in EDGES.items():
        order += 1
        rel = f"edges/{edge_name}.csv"
        n = write_csv(out_dir / rel, ["from_id", "to_id"], edge_rows[edge_name])
        manifest_files.append({
            "file": rel, "kind": "edge", "target": edge_name,
            "from_type": ftype, "to_type": ttype,
            "from_column": "from_id", "to_column": "to_id",
            "columns": {}, "expected_rows": n, "order": order,
        })

    manifest = {
        "graph": "phx_dm_pce_practice_demo",
        "generated_by": f"scripts/build_real_data.py (raw={raw_dir}, seed {seed})",
        # Round 2a task 1: measured default (see app/config/settings.py
        # ingestion_batch_size — 7,706 rows/s p95 at 5000 vs 3,169 at 500).
        "batch_size": 5000,
        "files": manifest_files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total_v = sum(f["expected_rows"] for f in manifest_files if f["kind"] == "vertex")
    total_e = sum(f["expected_rows"] for f in manifest_files if f["kind"] == "edge")
    print(f"\nwrote {out_dir}: {len(manifest_files)} files, {total_v} vertex rows, "
          f"{total_e} edge rows, manifest.json")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default="data/real/_raw", help="raw extract directory")
    ap.add_argument("--out", default="data/real", help="output dataset directory")
    ap.add_argument("--seed", type=int, default=42, help="seed for the DUMMY opportunity rows")
    args = ap.parse_args()
    try:
        build(Path(args.raw), Path(args.out), args.seed)
    except (ColumnMismatchError, ValidationFailure) as exc:
        print(f"\nBUILD FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

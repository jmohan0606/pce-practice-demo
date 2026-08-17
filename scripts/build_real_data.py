"""Round F task 4.3 / Round 2a task 2 — build data/real/{vertices,edges}/ + manifest.json.

    python3 scripts/build_real_data.py [--raw data/real/_raw] [--out data/real]
        [--seed 42] [--max-memory-mb 4096] [--skip-disk-check]

THE MISSING MIDDLE of the real-data path (ROUND_D_EXTRACTION.md §1): the chunked
extracts land as CSV in data/real/_raw/; this script turns those source-shaped raw
extracts into the graph-shaped vertex/edge CSV set + manifest that the EXISTING
manifest-driven ingestion pipeline consumes unchanged.

Round 2a: the real load is 12.4M transactions / 34.2M vertex rows — the old
hold-everything-in-a-list build (~25 GB for the transactions alone) cannot run on
the client machine. The four large entities now STREAM:

  - transactions: read chunk by chunk, transform, write vertex + 5 edge CSVs row
    by row; monthly_revenue accumulates in a dict as rows stream past
  - accounts / eci_rel / eci_map: stream per bucket, write per bucket (dedupe and
    latest-bus_dt state confined to one bucket — the buckets partition by account
    key, so nothing needs cross-bucket state)
  - account_month: ONE MONTH AT A TIME — per-month (acct, advisor) aggregates are
    spilled to temp files during the transaction pass, and emission holds only the
    prior month's (pair) -> (balance, credited, present) map (~2.9M small entries)

A --max-memory-mb guard (default 4096) reports peak RSS per entity and fails with
a clear message instead of being OOM-killed at 90% with nothing written.

Chunk forms read (Round 2a task 2.5 — five families; single-file forms still
accepted, BOTH forms present for one family is an ambiguity error):
  raw_txn_<month>_b<NNN>.csv    transactions        raw_balance_<month>.csv  balances
  raw_account_b<NNN>.csv        accounts            raw_acct_eci_rel_b<NNN>.csv
  raw_acct_eci_map_b<NNN>.csv                       (each chunk contract-checked
  individually; a missing bucket in a sequence is a LOST CHUNK and fails)

Safety unchanged: RAW_CONTRACT per file, NOTHING lands in --out until every §5
validation passes (the stream writes into <out>/.building and the finished set
moves into place atomically-per-directory at the end; a failed build removes the
staging directory and leaves --out untouched). Free disk is checked up front
(20 GB floor; --skip-disk-check to override).

Transformations (ROUND_D_EXTRACTION.md §2 — all in Python, none in SQL):
  - normalize_account_key() from app/shared/ids.py on every account column
  - credited / non-credited split on reason_cd == '__NONE__'
  - month_id from trade_dt, never proc_dt
  - product model IMPORTED from app/revenue/products.py (never retyped)
  - monthly_revenue aggregated from the transaction stream, never re-queried
  - prior_end_balance / prior_credited_amt from the previous month; baseline 0
  - CRM (Round 2a): the firm-wide flat file (308,534 rows) is FILTERED to
    in-scope rows — kept iff the (suffix-stripped) owner sid is a known advisor
    OR the eci is a known in-scope household; out-of-scope rows are dropped WITH
    A REPORTED COUNT. Invalid advisor references (*_CWM_INVALID) are still kept
    (advisor_valid=false) and reported, never silently dropped.
  - NNM rows parsed from the four delivered files via scripts/parse_nnm.py; a
    missing category refuses to start
  - trades are NEVER joined to team agreements

build_report.json (Round 2a task 4) records raw-rows-in / rows-out / explained
deltas per entity so scripts/reconcile_load.py can prove the counts three ways.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import resource
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from sys import intern

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.revenue.aggregation import build_monthly_revenue  # noqa: E402
from app.revenue.products import (  # noqa: E402
    UNMAPPED_GROUP_ID,
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
MIN_FREE_GB = 20


class ColumnMismatchError(Exception):
    """A raw extract is missing, or missing a contracted column. Names both."""


class ValidationFailure(Exception):
    """A §5 validation failed — the dataset is NOT written."""


class MemoryGuardError(Exception):
    """Peak RSS exceeded --max-memory-mb — failed loudly instead of OOM-killed."""


# ---------------------------------------------------------------- RAW_CONTRACT
# Round 2a task 2.8: raw_advisor_flags reduced to the four columns actually
# consumed — the nine scenario flags were a cohort-SELECTION aid and the cohort
# is now the firm. FLAG_COLUMNS is kept exported for scripts/select_cohort.py,
# which only ever reads OLD-format files (retired for the firm-wide load).
FLAG_COLUMNS = [
    "has_fee_reduction_gt10", "has_recorded_grid_reduction", "has_transfer_in",
    "has_transfer_out", "has_new_account", "has_zeroed_account",
    "has_team_agreement", "has_flows", "has_non_credited",
]

RAW_CONTRACT: dict[str, list[str]] = {
    "raw_advisor_flags.csv": ["advisor_sid", "rep_code", "advisor_name",
                              "total_credited_amt"],
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
    # Round F2 — the CRM export (original name crm_opportunities.csv)
    "raw_crm_opportunity.csv": ["opportunity_id", "eci_id", "ownersid",
                                "account_record_type", "product_service_type",
                                "stage_name", "amount", "actual_assets",
                                "anticipated_investment_dt", "created_dt",
                                "last_modified_dt", "date_of_last_contact",
                                "days_to_close", "comments"],
}
NNM_RAW_PREFIXES = tuple(sorted(parse_nnm.CATEGORY_BY_PREFIX))

# Round 2a task 2.5 — the FIVE chunk families. Each maps the canonical single
# filename to the chunk pattern extract_chunked.py emits. A family may arrive
# as ONE file or as chunks; both at once is ambiguous and refuses.
CHUNK_FAMILIES: dict[str, dict] = {
    "raw_revenue_transaction.csv": {
        "glob": "raw_txn_*_b*.csv",
        "regex": re.compile(r"raw_txn_(\d{6})_b(\d+)\.csv"),
        "sequenced": "per_month",
    },
    "raw_monthly_balance.csv": {
        "glob": "raw_balance_*.csv",
        "regex": re.compile(r"raw_balance_(\d{6})\.csv"),
        "sequenced": "months",  # completeness checked against raw_month_meta
    },
    "raw_account.csv": {
        "glob": "raw_account_b*.csv",
        "regex": re.compile(r"raw_account_b(\d+)\.csv"),
        "sequenced": "buckets",
    },
    "raw_acct_eci_rel.csv": {
        "glob": "raw_acct_eci_rel_b*.csv",
        "regex": re.compile(r"raw_acct_eci_rel_b(\d+)\.csv"),
        "sequenced": "buckets",
    },
    "raw_acct_eci_map.csv": {
        "glob": "raw_acct_eci_map_b*.csv",
        "regex": re.compile(r"raw_acct_eci_map_b(\d+)\.csv"),
        "sequenced": "buckets",
    },
}
TXN_CHUNK_GLOB = CHUNK_FAMILIES["raw_revenue_transaction.csv"]["glob"]
CRM_EXPORT_NAME = "crm_opportunities.csv"
CRM_LEGACY_NAME = "raw_crm_opportunity.csv"


def _check_sequence(family: str, spec: dict, chunks: list[Path]) -> None:
    """A missing bucket/batch in a dense sequence is a LOST CHUNK, not a small
    extract — refuse before anything is read."""
    if spec["sequenced"] == "buckets":
        nums = sorted(int(spec["regex"].fullmatch(p.name).group(1)) for p in chunks)
        missing = sorted(set(range(1, max(nums) + 1)) - set(nums))
        if missing:
            raise ColumnMismatchError(
                f"{family} bucket chunk sequence has gaps: missing bucket(s) "
                f"{missing} of b001..b{max(nums):03d} — a lost chunk, not a "
                f"small extract; re-run the extraction (it resumes)")
    elif spec["sequenced"] == "per_month":
        by_month: dict[str, list[int]] = defaultdict(list)
        for p in chunks:
            m = spec["regex"].fullmatch(p.name)
            by_month[m.group(1)].append(int(m.group(2)))
        gaps = {mo: sorted(set(range(1, max(b) + 1)) - set(b))
                for mo, b in by_month.items()}
        gaps = {mo: g for mo, g in gaps.items() if g}
        if gaps:
            raise ColumnMismatchError(
                f"{family} chunk sequence has gaps per month: {gaps} — lost "
                f"chunk(s); re-run the extraction (it resumes)")


def detect_sources(raw_dir: Path) -> dict:
    """Detect the three source kinds by filename pattern; fail loudly on an
    ambiguous or incomplete drop BEFORE anything is read. Round 2a: all five
    chunk families detected, sequence-checked, and returned per family."""
    chunks: dict[str, list[Path]] = {}
    for family, spec in CHUNK_FAMILIES.items():
        found = sorted(raw_dir.glob(spec["glob"]))
        found = [p for p in found if spec["regex"].fullmatch(p.name)]
        single = raw_dir / family
        if found and single.exists():
            raise ColumnMismatchError(
                f"both {family} AND {len(found)} chunk file(s) "
                f"({spec['glob']}) exist in {raw_dir} — ambiguous: remove one "
                f"form (the chunks are extract_chunked.py's output)")
        if found:
            _check_sequence(family, spec, found)
        chunks[family] = found
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
    present = {f.name[:5].upper() for f in raw_dir.glob("*NNM_*.txt")}
    missing = [p for p in NNM_RAW_PREFIXES if p not in present]
    if missing:
        raise ColumnMismatchError(
            f"NNM category file(s) missing from {raw_dir}: {missing} — all "
            f"four of {list(NNM_RAW_PREFIXES)} are required (original "
            f"filenames, e.g. ECNNM_20260630.txt); three of four would load "
            f"silently incomplete, so the build refuses to start")
    return {
        "chunks": chunks,
        "txn_chunks": chunks["raw_revenue_transaction.csv"],
        "crm_file": (crm_new if crm_new.exists() else crm_legacy).name,
        "nnm_files": sorted(f.name for f in raw_dir.glob("*NNM_*.txt")),
    }


def family_files(raw_dir: Path, sources: dict, family: str) -> list[Path]:
    """The file list for one family — its chunks, or its single file."""
    found = sources["chunks"].get(family) or []
    if found:
        return found
    path = raw_dir / family
    if not path.exists():
        raise ColumnMismatchError(
            f"missing raw extract '{family}' (no single file at {path} and no "
            f"{CHUNK_FAMILIES[family]['glob']} chunks; contracted columns: "
            f"{RAW_CONTRACT[family]})")
    return [path]


def iter_csv_rows(path: Path, expected: list[str]):
    """Stream one CSV, enforcing the contract on ITS OWN header (every chunk is
    contract-checked individually — a mismatch in bucket 3 fails loudly)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in expected if c not in header]
        if missing:
            raise ColumnMismatchError(
                f"raw extract file '{path.name}' is missing contracted "
                f"column(s) {missing} — found columns {header}")
        for row in reader:
            yield {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}


def read_raw(raw_dir: Path, filename: str) -> list[dict]:
    """Read one SMALL raw extract fully (contract enforced)."""
    path = raw_dir / filename
    if not path.exists():
        raise ColumnMismatchError(
            f"missing raw extract file '{filename}' (expected at {path}; "
            f"contracted columns: {RAW_CONTRACT[filename]})")
    return list(iter_csv_rows(path, RAW_CONTRACT[filename]))


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


def peak_rss_mb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


class MemoryGuard:
    """Reports peak RSS after every entity and fails LOUDLY when the limit is
    exceeded — a build the OS kills at 90% with no output is the worst outcome
    after a multi-hour extract."""

    def __init__(self, limit_mb: int) -> None:
        self.limit_mb = limit_mb
        self.per_entity: dict[str, int] = {}

    def check(self, entity: str) -> None:
        peak = peak_rss_mb()
        self.per_entity[entity] = peak
        print(f"  [memory] peak RSS after {entity}: {peak} MB "
              f"(limit {self.limit_mb} MB)")
        if peak > self.limit_mb:
            raise MemoryGuardError(
                f"peak RSS {peak} MB exceeded --max-memory-mb {self.limit_mb} "
                f"after building {entity}. Nothing was committed to the output "
                f"directory. Raise --max-memory-mb if the machine genuinely "
                f"has the headroom, or raise --buckets / re-chunk the extract.")


def check_free_disk(out_dir: Path, skip: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(out_dir).free / 1e9
    if free_gb >= MIN_FREE_GB:
        return
    if skip:
        print(f"WARNING: only {free_gb:.1f} GB free on {out_dir} "
              f"(< {MIN_FREE_GB} GB) — proceeding on --skip-disk-check")
        return
    raise ValidationFailure(
        f"{free_gb:.1f} GB free on {out_dir}'s filesystem — the built dataset "
        f"peaks at ~15 GB at firm scale and needs {MIN_FREE_GB} GB headroom. "
        f"Free space or pass --skip-disk-check.")


# --------------------------------------------------------- columns / ids / edges
# Kept structurally IDENTICAL to scripts/generate_mock_data.py so the manifest
# this script writes is consumed by the ingestion pipeline unchanged.
# Round 2a FIX (pre-existing bug): phx_dm_pce_opportunity here still carried the
# pre-F2 dummy 12-column shape (the 23 real CRM columns were silently dropped at
# write) and phx_dm_pce_advisor_nnm was MISSING entirely — so the built manifest
# had 17 vertices while 31 edge files (nnm edges included) were written: dangling
# nnm edges at load. Both now match the mock manifest exactly.
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
    "phx_dm_pce_opportunity": ["opportunity_id", "eci_id", "advisor_sid", "advisor_sid_raw", "advisor_valid",
                               "account_record_type", "product_service_type", "stage_name", "stage_group",
                               "amount", "actual_assets", "anticipated_investment_dt", "created_dt",
                               "last_modified_dt", "date_of_last_contact", "days_to_close", "is_stalled",
                               "comments", "ai_read", "ai_read_confidence", "ai_read_evidence",
                               "ai_read_model", "data_source"],
    "phx_dm_pce_advisor_nnm": ["nnm_id", "advisor_sid", "month_id", "category", "category_source",
                               "mtd_nnm", "ytd_nnm", "entry_dt", "as_of_dt"],
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


class StreamWriter:
    """One output CSV, written row by row into the staging directory."""

    def __init__(self, path: Path, columns: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.columns = columns
        self._f = path.open("w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._f, fieldnames=columns, extrasaction="ignore")
        self._w.writeheader()
        self.rows = 0

    def write(self, row: dict) -> None:
        self._w.writerow({k: (bl(v) if isinstance(v, bool) else v)
                          for k, v in row.items()})
        self.rows += 1

    def close(self) -> int:
        self._f.close()
        return self.rows


class EdgeWriters:
    """The 31 edge CSVs, open for streaming; drops counted per file."""

    def __init__(self, staging: Path) -> None:
        self.w: dict[str, StreamWriter] = {}
        self.dropped: dict[str, int] = {e: 0 for e in EDGES}
        self.seen: dict[str, set] = {}
        self.staging = staging

    def writer(self, edge: str) -> StreamWriter:
        if edge not in self.w:
            self.w[edge] = StreamWriter(self.staging / "edges" / f"{edge}.csv",
                                        ["from_id", "to_id"])
        return self.w[edge]

    def emit(self, edge: str, from_id: str, to_id: str,
             valid_targets: set | None = None, dedupe: bool = False) -> None:
        """blank endpoint = no edge (not a drop); invalid target = DROPPED AND
        COUNTED, never silently."""
        if not from_id or not to_id:
            return
        if valid_targets is not None and to_id not in valid_targets:
            self.dropped[edge] += 1
            return
        if dedupe:
            seen = self.seen.setdefault(edge, set())
            if (from_id, to_id) in seen:
                return
            seen.add((from_id, to_id))
        self.writer(edge).write({"from_id": from_id, "to_id": to_id})

    def counts(self) -> dict[str, int]:
        return {e: (self.w[e].rows if e in self.w else 0) for e in EDGES}

    def close(self) -> None:
        for w in self.w.values():
            w.close()


# ------------------------------------------------------- small-entity builders
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
            # client Phase 0 confirmed all three months COMPLETE (30/31/30)
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
            "l1_pay_type_cd": "", "l2_pay_type_cd": "",
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
            continue  # Round 2a: April-June in scope; anything else is out of scope
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


def build_advisor_nnm(raw_dir: Path) -> list[dict]:
    present = {f.name[:5].upper() for f in raw_dir.glob("*NNM_*.txt")}
    missing = [p for p in NNM_RAW_PREFIXES if p not in present]
    if missing:
        raise ColumnMismatchError(
            f"NNM raw files missing from {raw_dir}: {missing} — expected all "
            f"four of {list(NNM_RAW_PREFIXES)} (delivered files, no SQL template)")
    return [{**r, "mtd_nnm": f"{r['mtd_nnm']:.2f}", "ytd_nnm": f"{r['ytd_nnm']:.2f}"}
            for r in parse_nnm.parse_nnm_dir(raw_dir)]


def transform_txn(r: dict) -> dict | None:
    """One raw transaction row -> vertex row (None = out of scope/undated)."""
    trade_dt = parse_dt(r["trade_dt"])
    proc_dt = parse_dt(r["proc_dt"])
    if trade_dt is None or not (SCOPE_FROM <= trade_dt.date() < SCOPE_TO):
        return None
    month_id = intern(month_of(trade_dt))  # month from trade_dt, NEVER proc_dt
    reason = r["reason_cd"].strip() or "__NONE__"
    amount = num(r["post_split_credited_amt"])
    credited = reason == "__NONE__"
    acct_key = intern(normalize_account_key(r["account_no"]))
    dtp = (proc_dt.date() - trade_dt.date()).days if proc_dt else 0
    return {
        "txn_id": f"{r['trade_ref_no']}|{r['split_seq_no']}|{r['advisor_sid']}",
        "trade_ref_no": r["trade_ref_no"], "split_seq_no": r["split_seq_no"],
        "advisor_sid": intern(r["advisor_sid"]), "acct_key": acct_key,
        "product_id": intern(make_product_id(r["product_cd"], r["product_sub_cd"])),
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
        "rpg": intern(r["rpg"]), "concession_type": r["concession_type"],
        "file_key": r["file_key"] or "daily_trade_details",
        "trade_description": r["trade_description"],
    }


# ----------------------------------------------------------------- validation
def run_validations(agg: dict) -> None:
    """The 12 checks of ROUND_D_EXTRACTION.md §5, computed from streaming
    accumulators, printed in full. Raises ValidationFailure on any hard
    failure — the staged dataset is then discarded, never committed."""
    failures: list[str] = []
    month_ids = agg["month_ids"]
    baseline = month_ids[0] if month_ids else ""
    print("\n================ VALIDATION (ROUND_D_EXTRACTION.md §5) ================")

    # 1 — row count per file
    v_counts, e_counts = agg["vertex_counts"], agg["edge_counts"]
    print(f"\n 1. row counts ({len(v_counts) + len(e_counts)} files)")
    for t, n in v_counts.items():
        print(f"    vertex {t}: {n}")
    for e, n in e_counts.items():
        print(f"    edge   {e}: {n}")

    # 2 — primary key uniqueness (streamed entities: duplicates counted during
    # the stream; deduped/derived entities are unique by construction)
    print("\n 2. primary key uniqueness per vertex file")
    for t in v_counts:
        dups = agg["pk_duplicates"].get(t, 0)
        print(f"    {t}: {dups} duplicates")
        if dups:
            failures.append(f"validation 2: {t} has {dups} duplicate primary keys")

    # 3 — acct_key leading zeros
    bad = agg["unnormalised_keys"]
    print(f"\n 3. acct_key values with leading zeros: {bad} (must be 0)")
    if bad:
        failures.append(f"validation 3: {bad} account keys not normalised")

    # 4 — reason_cd empty strings
    print(f"\n 4. reason_cd empty strings: {agg['empty_reason']} (must be 0 — blank becomes '__NONE__')")
    if agg["empty_reason"]:
        failures.append(f"validation 4: {agg['empty_reason']} blank reason_cd rows")

    # 5 — reason-coded rows must carry zero credited_amt (true by construction
    # in transform_txn; counted anyway so a transform edit cannot silently break it)
    print(f"\n 5. rows where reason_cd != '__NONE__' AND credited_amt != 0: "
          f"{agg['coded_with_credit']} (must be 0)")
    if agg["coded_with_credit"]:
        failures.append(f"validation 5: {agg['coded_with_credit']} reason-coded rows with credited_amt")

    # 6 — unmapped products, kept and listed, never dropped
    print("\n 6. product_ids in group 'unmapped' (kept, never dropped)")
    if agg["unmapped_counts"]:
        for pid, n in sorted(agg["unmapped_counts"].items()):
            print(f"    {pid}: {n} rows")
    else:
        print("    none")

    # 7 — monthly_revenue vs independent re-sum of the transaction stream
    check = agg["mr_check"]
    print(f"\n 7. monthly_revenue vs independent re-sum of transactions: "
          f"{'MATCH' if check['ok'] else 'MISMATCH'}")
    if not check["ok"]:
        for m in check["mismatches"][:5]:
            print(f"    {m}")
        failures.append(f"validation 7: {len(check['mismatches'])} (advisor, month) mismatches")

    # 8 — dropped edges per file
    print("\n 8. dropped edges per file (unresolvable to_id)")
    for e in EDGES:
        print(f"    {e}: dropped {agg['edge_dropped'][e]}")
    if agg["skipped_balance_rows"]:
        print(f"    (account_month: {agg['skipped_balance_rows']} balance rows "
              f"skipped — no resolvable advisor)")

    # 9 — prior_* computed: zero for baseline, populated after
    print(f"\n 9. prior_end_balance/prior_credited_amt: {agg['bad_baseline_prior']} "
          f"non-zero baseline rows (must be 0); {agg['later_prior_nonzero']} later "
          f"rows populated (must be > 0)")
    if agg["bad_baseline_prior"]:
        failures.append(f"validation 9: {agg['bad_baseline_prior']} baseline rows carry prior values")
    if agg["later_prior_nonzero"] == 0 and len(month_ids) > 1:
        failures.append("validation 9: no later-month row has computed prior values")

    # 10 — scenario coverage
    print("\n10. scenario coverage")
    print(f"    accounts with fee reduction >10%: {len(agg['reduced_accts'])}; "
          f"with a recorded grid_reduction: {len(agg['recorded_accts'])}")
    print(f"    transfers in (to cohort): {agg['transfers_in']}; "
          f"out (from cohort): {agg['transfers_out']}")
    print(f"    accounts opened in scope: {agg['opened_in_scope']}")
    print(f"    accounts zeroed between months: {len(agg['zeroed_accts'])}")
    print(f"    team agreements: {v_counts['phx_dm_pce_team_agreement']}")
    print(f"    advisors with flows: {len(agg['flow_advisors'])}")

    # 11 — per-month credited_amt and txn_count (+ sanity anchor)
    print("\n11. per-month credited_amt / txn_count")
    for m in month_ids:
        v = agg["per_month"].get(m, {"credited": 0.0, "count": 0})
        flag = ""
        if not (1e5 <= v["credited"] <= 1e7):
            flag = ("  << SANITY: outside high-hundreds-of-thousands..low-millions — "
                    "check proc_dt misuse or a team-agreement fan-out "
                    "(EXPECTED at firm scale: 5,746 advisors x ~$33k ≈ $190M/month)")
        print(f"    {m}: credited ${v['credited']:,.2f}  txns {v['count']}{flag}")

    # 12 — trading days per month
    print("\n12. trading days per month")
    for r in agg["month_rows"]:
        print(f"    {r['month_id']}: trading_days={r['trading_days']} "
              f"(distinct trade dates seen: {len(agg['trade_dates'].get(r['month_id'], set()))}, "
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


# ----------------------------------------------------------------- the build
def build(raw_dir: Path, out_dir: Path, seed: int = 42,
          max_memory_mb: int = 4096, skip_disk_check: bool = False) -> dict:
    check_free_disk(out_dir, skip_disk_check)
    guard = MemoryGuard(max_memory_mb)

    sources = detect_sources(raw_dir)
    txn_files = family_files(raw_dir, sources, "raw_revenue_transaction.csv")
    n_txn_chunks = len(sources["chunks"]["raw_revenue_transaction.csv"])
    print(f"source detection: PostgreSQL extracts raw_*.csv "
          f"({'single transaction file' if not n_txn_chunks else str(n_txn_chunks) + ' transaction chunks'}), "
          f"NNM files {sources['nnm_files']}, CRM export {sources['crm_file']}")

    staging = out_dir.parent / (out_dir.name + ".building")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    report: dict = {"raw_input_rows": {}, "entities": {}, "transform_deltas": {}}

    try:
        return _build_staged(raw_dir, out_dir, staging, sources, txn_files,
                             guard, report, seed)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _build_staged(raw_dir: Path, out_dir: Path, staging: Path, sources: dict,
                  txn_files: list[Path], guard: MemoryGuard, report: dict,
                  seed: int) -> dict:
    edges = EdgeWriters(staging)
    vw: dict[str, StreamWriter] = {}

    def vwriter(target: str) -> StreamWriter:
        if target not in vw:
            vw[target] = StreamWriter(staging / "vertices" / f"{target}.csv",
                                      VERTEX_COLUMNS[target])
        return vw[target]

    # ---- small raws, fully read (contract enforced) -------------------------
    flags_rows = read_raw(raw_dir, "raw_advisor_flags.csv")  # contract input only
    report["raw_input_rows"]["raw_advisor_flags.csv"] = len(flags_rows)
    meta_rows = sorted(read_raw(raw_dir, "raw_month_meta.csv"),
                       key=lambda r: r["month_id"])
    month_ids = [r["month_id"] for r in meta_rows]
    month_set = set(month_ids)
    hier_rows = read_raw(raw_dir, "raw_product_hierarchy.csv")
    rr_rows = read_raw(raw_dir, "raw_rr_changes.csv")
    team_rows = read_raw(raw_dir, "raw_team_agreement.csv")
    flow_rows = read_raw(raw_dir, "raw_adv_flows.csv")
    adv_raw = read_raw(raw_dir, "raw_advisor.csv")
    for name, rows in (("raw_month_meta.csv", meta_rows),
                       ("raw_product_hierarchy.csv", hier_rows),
                       ("raw_rr_changes.csv", rr_rows),
                       ("raw_team_agreement.csv", team_rows),
                       ("raw_adv_flows.csv", flow_rows),
                       ("raw_advisor.csv", adv_raw)):
        report["raw_input_rows"][name] = len(rows)

    advisors = [{
        "advisor_sid": r["advisor_sid"], "rep_code": r["rep_code"],
        "advisor_name": r["advisor_name"],  # blank stays blank — never invented
        "branch_cd": r["branch_cd"], "employee_id": r["employee_id"],
        "in_cohort": bl(as_bool(r["in_cohort"])),
        "job_code": r["job_code"],  # blank stays blank — never invented
    } for r in adv_raw]
    advisor_set = {intern(a["advisor_sid"]) for a in advisors}
    cohort = {a["advisor_sid"] for a in advisors if a["in_cohort"] == "true"}
    transfers = build_transfers(rr_rows)

    agg: dict = {
        "month_ids": month_ids, "vertex_counts": {}, "edge_counts": {},
        "pk_duplicates": {}, "unnormalised_keys": 0, "empty_reason": 0,
        "coded_with_credit": 0, "unmapped_counts": defaultdict(int),
        "skipped_balance_rows": 0, "bad_baseline_prior": 0,
        "later_prior_nonzero": 0, "reduced_accts": set(), "recorded_accts": set(),
        "opened_in_scope": 0, "zeroed_accts": set(), "flow_advisors": set(),
        "per_month": defaultdict(lambda: {"credited": 0.0, "count": 0}),
        "trade_dates": defaultdict(set),
        "transfers_in": sum(1 for t in transfers if t["to_advisor_sid"] in cohort),
        "transfers_out": sum(1 for t in transfers if t["from_advisor_sid"] in cohort),
    }

    # ---- pass 1: accounts (streamed per bucket) -----------------------------
    acct_set: set[str] = set()
    households: dict[str, set] = {}  # eci -> distinct acct keys seen
    w_acct = vwriter("phx_dm_pce_account")
    raw_acct_rows = dedup_acct = blank_acct = 0
    acct_files = family_files(raw_dir, sources, "raw_account.csv")
    for path in acct_files:
        for r in iter_csv_rows(path, RAW_CONTRACT["raw_account.csv"]):
            raw_acct_rows += 1
            key = intern(normalize_account_key(r["account_no"]))
            if not key:
                blank_acct += 1
                continue
            if key in acct_set:
                dedup_acct += 1
                continue
            acct_set.add(key)
            opened = parse_dt(r["account_open_dt"])
            in_scope = bool(opened) and SCOPE_FROM <= opened.date() < SCOPE_TO
            if in_scope:
                agg["opened_in_scope"] += 1
            eci = r["primary_eci_id"]
            w_acct.write({
                "acct_key": key, "account_no_raw": r["account_no"],
                "account_class_cd": r["account_class_cd"],
                "account_class_nm": r["account_class_nm"],
                "account_lob_cd": r["account_lob_cd"],
                "account_purpose_cd": r["account_purpose_cd"],
                "managed_platform_cd": r["managed_platform_cd"],
                "service_channel_cd": r["service_channel_cd"],
                "account_open_dt": ts(opened),
                "is_managed": bl(bool(r["managed_platform_cd"].strip())),
                "opened_in_scope": bl(in_scope),
                "primary_eci_id": eci,
            })
            if eci:
                # household vertex will contain every primary eci by
                # construction, so the edge needs no validity check
                edges.emit("phx_dm_pce_account_in_household", key, eci)
                households.setdefault(intern(eci), set()).add(key)
    report["raw_input_rows"]["raw_account.csv"] = raw_acct_rows
    report["transform_deltas"]["account"] = {
        "raw_rows": raw_acct_rows, "deduplicated": dedup_acct,
        "blank_key": blank_acct, "rows": w_acct.rows}
    guard.check("account")

    # ---- pass 2: transactions (streamed; monthly_revenue accumulates) -------
    w_txn = vwriter("phx_dm_pce_revenue_transaction")
    txn_pk_hashes: set[int] = set()
    txn_dups = 0
    raw_txn_rows = out_of_scope_txn = 0
    product_ids: set[str] = set()
    rpg_accts: dict[str, set] = defaultdict(set)
    rpg_by_acct: dict[str, str] = {}
    advisor_by_acct: dict[str, set] = defaultdict(set)
    expected_totals: dict[tuple, dict] = {}
    am_dir = staging / "_am_spill"
    am_dir.mkdir()
    spill_state = {"month": None, "agg": {}, "files": {}}
    input_chunked = bool(sources["chunks"]["raw_revenue_transaction.csv"])

    def _spill_month() -> None:
        m, data = spill_state["month"], spill_state["agg"]
        if m is None:
            return
        path = am_dir / f"{m}.csv"
        mode = "a" if path.exists() else "w"
        with path.open(mode, newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if mode == "w":
                w.writerow(["acct_key", "advisor_sid", "credited", "count"])
            for (acct, sid), (cred, cnt) in data.items():
                w.writerow([acct, sid, f"{cred:.10g}", cnt])
        spill_state["files"][m] = path
        spill_state["agg"] = {}
        spill_state["month"] = None

    import hashlib as _hashlib

    def txn_stream():
        nonlocal raw_txn_rows, out_of_scope_txn, txn_dups
        for path in txn_files:
            for r in iter_csv_rows(path, RAW_CONTRACT["raw_revenue_transaction.csv"]):
                raw_txn_rows += 1
                t = transform_txn(r)
                if t is None:
                    out_of_scope_txn += 1
                    continue
                h = int.from_bytes(
                    _hashlib.blake2b(t["txn_id"].encode(), digest_size=8).digest(),
                    "big")
                if h in txn_pk_hashes:
                    txn_dups += 1
                else:
                    txn_pk_hashes.add(h)
                w_txn.write(t)
                tid, sid, acct = t["txn_id"], t["advisor_sid"], t["acct_key"]
                month, pid = t["month_id"], t["product_id"]
                edges.emit("phx_dm_pce_txn_by_advisor", tid, sid, advisor_set)
                edges.emit("phx_dm_pce_txn_for_account", tid, acct, acct_set)
                # product/rpg vertices are BUILT FROM the stream, so every
                # non-blank target exists by construction — no validity check
                edges.emit("phx_dm_pce_txn_of_product", tid, pid)
                edges.emit("phx_dm_pce_txn_in_month", tid, month, month_set)
                edges.emit("phx_dm_pce_txn_in_rpg", tid, t["rpg"])
                product_ids.add(pid)
                if t["rpg"]:
                    rpg_accts[t["rpg"]].add(acct)
                    rpg_by_acct.setdefault(acct, t["rpg"])
                advisor_by_acct[acct].add(sid)
                cred = float(t["credited_amt"])
                # validation accumulators
                cd, sub = split_product_id(pid)
                if resolve_product(cd, sub) == UNMAPPED_GROUP_ID:
                    agg["unmapped_counts"][pid] += 1
                if not t["reason_cd"].strip():
                    agg["empty_reason"] += 1
                if t["reason_cd"] != "__NONE__" and cred != 0.0:
                    agg["coded_with_credit"] += 1
                if acct != normalize_account_key(acct):
                    agg["unnormalised_keys"] += 1
                std, cli = float(t["standard_rate_bps"]), float(t["client_rate_bps"])
                if std > 0 and (std - cli) / std * 100 > 10:
                    agg["reduced_accts"].add(acct)
                    if float(t["grid_reduction"]) != 0.0:
                        agg["recorded_accts"].add(acct)
                pm = agg["per_month"][month]
                pm["credited"] += cred
                pm["count"] += 1
                agg["trade_dates"][month].add(t["trade_dt"][:10])
                exp = expected_totals.setdefault(
                    (sid, month), {"credited_amt": 0.0, "non_credited_amt": 0.0,
                                   "txn_count": 0})
                exp["credited_amt"] += cred
                exp["non_credited_amt"] += float(t["non_credited_amt"])
                exp["txn_count"] += 1
                # per-month account_month aggregates — spilled at month
                # boundaries when the input is chunked (chunk names are
                # month-major), held whole only for the small single-file form
                if input_chunked and spill_state["month"] not in (None, month):
                    _spill_month()
                if spill_state["month"] is None:
                    spill_state["month"] = month
                elif not input_chunked and spill_state["month"] != month:
                    # single file interleaving months: aggregate keyed by month
                    pass
                key = (acct, sid) if input_chunked else (acct, sid, month)
                data = spill_state["agg"]
                if not input_chunked:
                    cur = data.setdefault(key, [0.0, 0])
                else:
                    cur = data.setdefault(key, [0.0, 0])
                cur[0] += cred
                cur[1] += 1
                yield t

    # single-file form keys by (acct, sid, month); chunked form by (acct, sid)
    # per month — unify by making the single-file spill write per month at end.
    mr_rows = build_monthly_revenue(txn_stream())
    if input_chunked:
        _spill_month()
    else:
        # split the held aggregate per month and spill each
        by_month: dict[str, dict] = defaultdict(dict)
        for (acct, sid, month), v in spill_state["agg"].items():
            by_month[month][(acct, sid)] = v
        for m, data in by_month.items():
            spill_state["month"], spill_state["agg"] = m, data
            _spill_month()
    agg["pk_duplicates"]["phx_dm_pce_revenue_transaction"] = txn_dups
    txn_pk_hashes.clear()
    report["raw_input_rows"]["raw_revenue_transaction.csv"] = raw_txn_rows
    report["transform_deltas"]["revenue_transaction"] = {
        "raw_rows": raw_txn_rows, "out_of_scope_or_undated": out_of_scope_txn,
        "rows": w_txn.rows}
    print(f"transaction extract: {len(txn_files)} file(s) -> {w_txn.rows} rows "
          f"({out_of_scope_txn} out of scope)")
    guard.check("revenue_transaction")

    # ---- monthly_revenue (accumulated during the stream) --------------------
    w_mr = vwriter("phx_dm_pce_monthly_revenue")
    for r in mr_rows:
        row = {**r, "credited_amt": money(r["credited_amt"]),
               "non_credited_amt": money(r["non_credited_amt"]),
               "txn_count": str(r["txn_count"]),
               "distinct_accounts": str(r["distinct_accounts"])}
        w_mr.write(row)
        edges.emit("phx_dm_pce_mr_by_advisor", r["mr_id"], r["advisor_sid"], advisor_set)
        edges.emit("phx_dm_pce_mr_in_month", r["mr_id"], r["month_id"], month_set)
        edges.emit("phx_dm_pce_mr_of_product", r["mr_id"], r["product_id"])
        edges.emit("phx_dm_pce_mr_in_group", r["mr_id"], r["group_id"])
    # independent re-sum (validation 7): expected_totals accumulated during
    # the transaction STREAM (same semantics as verify_against_transactions,
    # which needs a second full pass the stream design deliberately avoids)
    from app.revenue.aggregation import _to_float  # noqa: PLC0415

    actual: dict[tuple, dict] = {}
    for row in mr_rows:
        k = (row["advisor_sid"], row["month_id"])
        a = actual.setdefault(k, {"credited_amt": 0.0, "non_credited_amt": 0.0,
                                  "txn_count": 0})
        a["credited_amt"] += _to_float(row["credited_amt"])
        a["non_credited_amt"] += _to_float(row["non_credited_amt"])
        a["txn_count"] += int(row["txn_count"])
    mismatches = []
    for k in sorted(set(expected_totals) | set(actual)):
        e = expected_totals.get(k, {"credited_amt": 0.0, "non_credited_amt": 0.0, "txn_count": 0})
        a = actual.get(k, {"credited_amt": 0.0, "non_credited_amt": 0.0, "txn_count": 0})
        problems = [f for f in ("credited_amt", "non_credited_amt")
                    if abs(e[f] - a[f]) > 0.01]
        if e["txn_count"] != a["txn_count"]:
            problems.append("txn_count")
        if problems:
            mismatches.append({"advisor_sid": k[0], "month_id": k[1],
                               "fields": problems})
    agg["mr_check"] = {"ok": not mismatches, "mismatches": mismatches}
    del mr_rows, actual, expected_totals
    guard.check("monthly_revenue")

    # ---- products / groups / classes / months / advisors / rpg --------------
    for target, rows in (
        ("phx_dm_pce_month", build_months(meta_rows)),
        ("phx_dm_pce_revenue_class", revenue_class_rows()),
        ("phx_dm_pce_product_group", [
            {**r, "is_aggregated": bl(r["is_aggregated"]), "sort_order": str(r["sort_order"])}
            for r in product_group_rows()]),
        ("phx_dm_pce_product", build_products(hier_rows, product_ids)),
        ("phx_dm_pce_advisor", advisors),
        ("phx_dm_pce_team_agreement", build_team_agreements(team_rows)),
        ("phx_dm_pce_advisor_flow_month", build_flows(flow_rows, month_ids)),
        ("phx_dm_pce_account_transfer", transfers),
    ):
        w = vwriter(target)
        ids = set()
        for r in rows:
            w.write(r)
            ids.add(r[ID_COLUMNS[target]])
        agg["pk_duplicates"][target] = len(rows) - len(ids)
    agg["month_rows"] = build_months(meta_rows)
    report["raw_input_rows"]["raw_month_meta.csv"] = len(meta_rows)
    report["transform_deltas"]["advisor"] = {
        "raw_rows": len(adv_raw), "rows": len(advisors)}
    report["transform_deltas"]["account_transfer"] = {
        "raw_rows": len(rr_rows),
        "out_of_scope_or_deduplicated": len(rr_rows) - len(transfers),
        "rows": len(transfers)}
    report["transform_deltas"]["advisor_flow_month"] = {
        "raw_rows": len(flow_rows),
        "out_of_scope_or_deduplicated": len(flow_rows)
        - vw["phx_dm_pce_advisor_flow_month"].rows,
        "rows": vw["phx_dm_pce_advisor_flow_month"].rows}
    agg["flow_advisors"] = {r["advisor_sid"] for r in flow_rows
                            if r["month_id"] in month_set}
    prod_rows_written = vw["phx_dm_pce_product"].rows
    report["transform_deltas"]["product"] = {
        "raw_rows": len(hier_rows), "rows": prod_rows_written,
        "note": "hierarchy filtered to PRODUCT_TYPE + txn-only products added"}

    # small-source edges
    for r in build_products(hier_rows, product_ids):
        edges.emit("phx_dm_pce_product_in_group", r["product_id"], r["group_id"])
    for r in product_group_rows():
        edges.emit("phx_dm_pce_group_in_class", r["group_id"], r["class_id"])
    for t in transfers:
        edges.emit("phx_dm_pce_transfer_of_account", t["transfer_id"], t["acct_key"], acct_set)
        edges.emit("phx_dm_pce_transfer_from", t["transfer_id"], t["from_advisor_sid"], advisor_set)
        edges.emit("phx_dm_pce_transfer_to", t["transfer_id"], t["to_advisor_sid"], advisor_set)
        advisor_by_acct[t["acct_key"]].add(t["to_advisor_sid"])
    for r in build_team_agreements(team_rows):
        edges.emit("phx_dm_pce_team_primary", r["agreement_key"], r["prm_advisor_sid"], advisor_set)
        edges.emit("phx_dm_pce_team_secondary", r["agreement_key"], r["sec_advisor_sid"], advisor_set)
    for r in build_flows(flow_rows, month_ids):
        edges.emit("phx_dm_pce_flow_by_advisor", r["afm_id"], r["advisor_sid"], advisor_set)
        edges.emit("phx_dm_pce_flow_in_month", r["afm_id"], r["month_id"], month_set)

    # account_in_rpg (needed the txn pass: rpg_by_acct) + rpg vertex
    w_rpg = vwriter("phx_dm_pce_rpg")
    for rpg_id in sorted(rpg_accts):
        w_rpg.write({"rpg_id": rpg_id, "account_count": str(len(rpg_accts[rpg_id]))})
    for acct in sorted(rpg_by_acct):
        if acct in acct_set:
            edges.emit("phx_dm_pce_account_in_rpg", acct, rpg_by_acct[acct])
    agg["pk_duplicates"]["phx_dm_pce_rpg"] = 0
    guard.check("small_entities")

    # ---- pass 3: eci_rel (streamed per bucket; dedupe confined per bucket) --
    w_rel = vwriter("phx_dm_pce_account_eci_rel")
    raw_rel_rows = dedup_rel = blank_rel = 0
    rel_files = family_files(raw_dir, sources, "raw_acct_eci_rel.csv")
    for path in rel_files:
        seen_rel: set[str] = set()  # buckets partition by acct key — per-file dedupe is exact
        for r in iter_csv_rows(path, RAW_CONTRACT["raw_acct_eci_rel.csv"]):
            raw_rel_rows += 1
            key = intern(normalize_account_key(r["account_number"]))
            rel_id = f"{key}|{r['party_eci_id']}|{r['enterprise_relationship_code']}"
            if not key:
                blank_rel += 1
                continue
            if rel_id in seen_rel:
                dedup_rel += 1
                continue
            seen_rel.add(rel_id)
            eci = intern(r["party_eci_id"])
            w_rel.write({
                "rel_id": rel_id, "acct_key": key, "eci_id": eci,
                "enterprise_relationship_code": r["enterprise_relationship_code"],
                "party_role_name": r["party_role_name"],
                "client_employee_ind": r["client_employee_ind"],
                "is_owner_role": bl(r["enterprise_relationship_code"] in OWNER_ROLE_CODES),
            })
            edges.emit("phx_dm_pce_rel_of_account", rel_id, key, acct_set)
            edges.emit("phx_dm_pce_rel_to_household", rel_id, eci)
            if eci:
                s = households.setdefault(eci, set())
                s.add(key)
            if key != normalize_account_key(key):
                agg["unnormalised_keys"] += 1
    agg["pk_duplicates"]["phx_dm_pce_account_eci_rel"] = 0  # deduped in-stream
    report["raw_input_rows"]["raw_acct_eci_rel.csv"] = raw_rel_rows
    report["transform_deltas"]["account_eci_rel"] = {
        "raw_rows": raw_rel_rows, "deduplicated": dedup_rel,
        "blank_key": blank_rel, "rows": w_rel.rows}
    guard.check("account_eci_rel")

    # ---- pass 4: eci_map (latest bus_dt per key, confined per bucket) -------
    w_map = vwriter("phx_dm_pce_account_eci_map")
    raw_map_rows = superseded = 0
    map_files = family_files(raw_dir, sources, "raw_acct_eci_map.csv")
    for path in map_files:
        latest: dict[tuple, dict] = {}
        for r in iter_csv_rows(path, RAW_CONTRACT["raw_acct_eci_map.csv"]):
            raw_map_rows += 1
            k = (r["wm_src_sys_cd"], r["wm_acct_src_nb"])
            if k not in latest or (parse_dt(r["bus_dt"]) or datetime.min) > \
                    (parse_dt(latest[k]["bus_dt"]) or datetime.min):
                if k in latest:
                    superseded += 1
                latest[k] = r
            else:
                superseded += 1
        for (sys_cd, src_nb), r in sorted(latest.items()):
            key = normalize_account_key(src_nb)
            bus = ts(parse_dt(r["bus_dt"]))
            map_id = f"{bus}|{sys_cd}|{key}"
            eci = intern(r["eci_nb"])
            w_map.write({
                "map_id": map_id, "acct_src_key": key, "acct_src_raw": src_nb,
                "wm_src_sys_cd": sys_cd, "eci_id": eci, "bus_dt": bus,
                # source new_exst_adv_clnt_in_cyr -> graph new_exst_adv_clnt_in
                "new_exst_adv_clnt_in": r["new_exst_adv_clnt_in_cyr"],
            })
            # blank endpoint (account outside the built set) = no edge — same
            # semantics as the old _acct_key bookkeeping field
            edges.emit("phx_dm_pce_map_of_account", map_id,
                       key if key in acct_set else "")
            edges.emit("phx_dm_pce_map_to_household", map_id, eci)
            if eci:
                households.setdefault(eci, set())
            if key and key != normalize_account_key(key):
                agg["unnormalised_keys"] += 1
    agg["pk_duplicates"]["phx_dm_pce_account_eci_map"] = 0  # latest-wins by key
    report["raw_input_rows"]["raw_acct_eci_map.csv"] = raw_map_rows
    report["transform_deltas"]["account_eci_map"] = {
        "raw_rows": raw_map_rows, "superseded_snapshots": superseded,
        "rows": w_map.rows}
    guard.check("account_eci_map")

    # ---- households vertex ---------------------------------------------------
    w_hh = vwriter("phx_dm_pce_household")
    for eci in sorted(households):
        if eci:
            w_hh.write({"eci_id": eci, "account_count": str(len(households[eci]))})
    hh_set = {e for e in households if e}
    agg["pk_duplicates"]["phx_dm_pce_household"] = 0
    guard.check("household")

    # ---- CRM (Round 2a: firm-wide flat file FILTERED to in-scope) -----------
    w_opp = vwriter("phx_dm_pce_opportunity")
    crm_path = raw_dir / sources["crm_file"]
    crm_raw = crm_kept = crm_out_of_scope = crm_invalid = crm_ungrouped = 0
    for r in iter_csv_rows(crm_path, RAW_CONTRACT[CRM_LEGACY_NAME]):
        crm_raw += 1
        sid, valid = strip_invalid_advisor_suffix(r["ownersid"])
        in_scope = (sid in advisor_set) or (r["eci_id"] in hh_set)
        if not in_scope:
            crm_out_of_scope += 1
            continue
        crm_kept += 1
        if not valid:
            crm_invalid += 1  # kept + reported, never silently dropped
        group = stage_group_for(r["stage_name"])
        if group == "UNGROUPED":
            crm_ungrouped += 1
        days = int(float(r["days_to_close"] or 0))
        opp_id = r["opportunity_id"]
        w_opp.write({
            "opportunity_id": opp_id, "eci_id": r["eci_id"],
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
        edges.emit("phx_dm_pce_opportunity_for_household", opp_id, r["eci_id"], hh_set)
        edges.emit("phx_dm_pce_opportunity_by_advisor", opp_id, sid, advisor_set)
    agg["pk_duplicates"]["phx_dm_pce_opportunity"] = 0
    report["raw_input_rows"][sources["crm_file"]] = crm_raw
    report["transform_deltas"]["opportunity"] = {
        "raw_rows": crm_raw, "out_of_scope_dropped": crm_out_of_scope,
        "invalid_advisor_kept": crm_invalid, "rows": crm_kept}
    print(f"CRM: {crm_raw} raw rows -> {crm_kept} in-scope kept, "
          f"{crm_out_of_scope} out-of-scope dropped (REPORTED — firm-wide "
          f"export filtered to in-scope advisors/ECIs); invalid advisor "
          f"references KEPT: {crm_invalid}; UNGROUPED stages: {crm_ungrouped}")
    guard.check("opportunity")

    # ---- NNM ------------------------------------------------------------------
    nnm_rows = build_advisor_nnm(raw_dir)
    w_nnm = vwriter("phx_dm_pce_advisor_nnm")
    nnm_ids = set()
    for r in nnm_rows:
        w_nnm.write(r)
        nnm_ids.add(r["nnm_id"])
        edges.emit("phx_dm_pce_nnm_by_advisor", r["nnm_id"], r["advisor_sid"], advisor_set)
        edges.emit("phx_dm_pce_nnm_in_month", r["nnm_id"], r["month_id"], month_set)
    agg["pk_duplicates"]["phx_dm_pce_advisor_nnm"] = len(nnm_rows) - len(nnm_ids)
    report["raw_input_rows"]["nnm_files"] = len(nnm_rows)
    report["transform_deltas"]["advisor_nnm"] = {
        "raw_rows": len(nnm_rows), "rows": w_nnm.rows}
    guard.check("advisor_nnm")

    # ---- account_month: ONE MONTH AT A TIME (spec 2.6) -----------------------
    def read_spill(month: str) -> dict:
        path = spill_state["files"].get(month)
        if not path or not path.exists():
            return {}
        out = {}
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                k = (intern(row["acct_key"]), intern(row["advisor_sid"]))
                cur = out.setdefault(k, [0.0, 0])
                cur[0] += float(row["credited"])
                cur[1] += int(row["count"])
        return out

    balance_files_all = family_files(raw_dir, sources, "raw_monthly_balance.csv")
    balance_chunked = bool(sources["chunks"]["raw_monthly_balance.csv"])
    if balance_chunked:
        bal_by_month: dict[str, list[Path]] = defaultdict(list)
        for p in balance_files_all:
            m = CHUNK_FAMILIES["raw_monthly_balance.csv"]["regex"].fullmatch(p.name)
            bal_by_month[m.group(1)].append(p)
        missing_bal = [m for m in month_ids if m not in bal_by_month]
        if missing_bal:
            raise ColumnMismatchError(
                f"monthly balance chunk(s) missing for month(s) {missing_bal} "
                f"— raw_month_meta.csv lists them; a missing month is a lost "
                f"chunk, not a small extract")

    def read_balances(month: str) -> tuple[dict, int]:
        """(acct -> summed balance) for one month + raw row count read."""
        bal: dict[str, float] = {}
        n = 0
        files = bal_by_month[month] if balance_chunked else balance_files_all
        for path in files:
            for r in iter_csv_rows(path, RAW_CONTRACT["raw_monthly_balance.csv"]):
                if not balance_chunked and r["month_id"] != month:
                    continue
                n += 1
                acct = intern(normalize_account_key(r["acct_id"]))
                if not acct or r["month_id"] not in month_set:
                    continue
                bal[acct] = bal.get(acct, 0.0) + num(r["acct_bal"])
        return bal, n

    # pre-pass: the pair universe (txn pairs + balance-attributed pairs) —
    # every (acct, advisor) is carried through ALL scope months so zeroed /
    # gone-quiet accounts still get rows (LOST_ACCOUNT needs them)
    pairs: set[tuple] = set()
    attributed_by_month: dict[str, set] = {}
    raw_balance_rows = 0
    for month in month_ids:
        cur_txn = read_spill(month)
        pairs.update(cur_txn)
        attributed: set = set(cur_txn)
        bal, n = read_balances(month)
        raw_balance_rows += n
        month_advisors: dict[str, set] = defaultdict(set)
        for (acct, sid) in cur_txn:
            month_advisors[acct].add(sid)
        for acct in bal:
            sids = month_advisors.get(acct) or advisor_by_acct.get(acct) or set()
            if not sids:
                agg["skipped_balance_rows"] += 1
                continue
            for sid in sids:
                pairs.add((acct, sid))
                attributed.add((acct, sid))
        attributed_by_month[month] = attributed
    report["raw_input_rows"]["raw_monthly_balance.csv"] = raw_balance_rows

    # emission: month-major, holding only the prior month's map
    w_am = vwriter("phx_dm_pce_account_month")
    sorted_pairs = sorted(pairs)
    prior: dict[tuple, tuple] = {}  # pair -> (bal, credited, present)
    baseline = month_ids[0] if month_ids else ""
    for i, month in enumerate(month_ids):
        cur_txn = read_spill(month)
        bal_map, _ = read_balances(month)
        attributed = attributed_by_month.get(month, set())
        new_prior: dict[tuple, tuple] = {}
        for pair in sorted_pairs:
            acct, sid = pair
            cred, cnt = cur_txn.get(pair, (0.0, 0))
            bal = bal_map.get(acct, 0.0)
            present = pair in attributed or cnt > 0
            p_bal, p_cred, p_present = prior.get(pair, (0.0, 0.0, False))
            am_id = f"{acct}|{sid}|{month}"
            row = {
                "am_id": am_id, "acct_key": acct, "advisor_sid": sid,
                "month_id": month, "end_balance": money(bal),
                "credited_amt": money(cred), "txn_count": str(cnt),
                "is_zero_balance": bl(bal == 0.0),
                "present_prior_month": bl(i > 0 and p_present),
                "prior_end_balance": money(p_bal if i > 0 else 0.0),
                "prior_credited_amt": money(p_cred if i > 0 else 0.0),
            }
            w_am.write(row)
            edges.emit("phx_dm_pce_am_for_account", am_id, acct, acct_set)
            edges.emit("phx_dm_pce_am_by_advisor", am_id, sid, advisor_set)
            edges.emit("phx_dm_pce_am_in_month", am_id, month, month_set)
            if month == baseline and (float(row["prior_end_balance"]) != 0.0
                                      or float(row["prior_credited_amt"]) != 0.0
                                      or row["present_prior_month"] != "false"):
                agg["bad_baseline_prior"] += 1
            if month != baseline and (float(row["prior_end_balance"]) != 0.0
                                      or float(row["prior_credited_amt"]) != 0.0):
                agg["later_prior_nonzero"] += 1
            if month != baseline and bal == 0.0 and p_bal > 0:
                agg["zeroed_accts"].add(acct)
            new_prior[pair] = (bal, cred, present)
        prior = new_prior
    agg["pk_duplicates"]["phx_dm_pce_account_month"] = 0  # unique by construction
    agg["pk_duplicates"]["phx_dm_pce_monthly_revenue"] = 0
    agg["pk_duplicates"]["phx_dm_pce_account"] = 0  # deduped in-stream
    report["transform_deltas"]["account_month"] = {
        "raw_balance_rows": raw_balance_rows,
        "skipped_balance_rows_no_advisor": agg["skipped_balance_rows"],
        "pairs": len(pairs), "months": len(month_ids), "rows": w_am.rows}
    guard.check("account_month")
    shutil.rmtree(am_dir, ignore_errors=True)

    # ---- finalize: counts, validations, manifest, commit ---------------------
    edges.close()
    for t in VERTEX_COLUMNS:
        if t not in vw:
            vwriter(t)  # empty file with header (never silently absent)
    agg["vertex_counts"] = {t: vw[t].rows for t in VERTEX_COLUMNS}
    agg["edge_counts"] = edges.counts()
    agg["edge_dropped"] = edges.dropped
    for t in VERTEX_COLUMNS:
        agg["pk_duplicates"].setdefault(t, 0)
    for w in vw.values():
        w.close()

    run_validations(agg)

    manifest_files, order = [], 0
    for target in VERTEX_COLUMNS:
        order += 1
        manifest_files.append({
            "file": f"vertices/{target}.csv", "kind": "vertex", "target": target,
            "id_column": ID_COLUMNS[target],
            "columns": {c: c for c in VERTEX_COLUMNS[target]},
            "expected_rows": agg["vertex_counts"][target], "order": order,
            "phase": 1,  # Round 2a task 3: vertices load first, in parallel
        })
    for edge_name, (ftype, ttype, _s, _f, _t) in EDGES.items():
        order += 1
        manifest_files.append({
            "file": f"edges/{edge_name}.csv", "kind": "edge", "target": edge_name,
            "from_type": ftype, "to_type": ttype,
            "from_column": "from_id", "to_column": "to_id",
            "columns": {}, "expected_rows": agg["edge_counts"][edge_name],
            "order": order,
            "phase": 2,  # only after EVERY phase-1 vertex entity completes
        })
    manifest = {
        "graph": "phx_dm_pce_practice_demo",
        "generated_by": f"scripts/build_real_data.py (raw={raw_dir}, seed {seed})",
        # Round 2a task 1: measured default (see app/config/settings.py
        # ingestion_batch_size — 7,706 rows/s p95 at 5000 vs 3,169 at 500).
        "batch_size": 5000,
        "files": manifest_files,
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                           encoding="utf-8")
    report["entities"] = {f["target"]: f["expected_rows"] for f in manifest_files}
    report["peak_rss_mb_per_entity"] = guard.per_entity
    (staging / "build_report.json").write_text(json.dumps(report, indent=2),
                                               encoding="utf-8")

    # validations passed — commit the staged set into --out (replace only what
    # this build owns; _raw/, cohort.txt, checkpoints are never touched)
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("vertices", "edges"):
        dst = out_dir / sub
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(staging / sub), str(dst))
    for name in ("manifest.json", "build_report.json"):
        shutil.move(str(staging / name), str(out_dir / name))
    shutil.rmtree(staging, ignore_errors=True)

    total_v = sum(f["expected_rows"] for f in manifest_files if f["kind"] == "vertex")
    total_e = sum(f["expected_rows"] for f in manifest_files if f["kind"] == "edge")
    print(f"\nwrote {out_dir}: {len(manifest_files)} files, {total_v} vertex rows, "
          f"{total_e} edge rows, manifest.json + build_report.json")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default="data/real/_raw", help="raw extract directory")
    ap.add_argument("--out", default="data/real", help="output dataset directory")
    ap.add_argument("--seed", type=int, default=42,
                    help="kept for call compatibility (no random content remains)")
    ap.add_argument("--max-memory-mb", type=int, default=4096,
                    help="peak-RSS guard: fail loudly instead of being "
                         "OOM-killed (default 4096)")
    ap.add_argument("--skip-disk-check", action="store_true",
                    help="proceed even with under 20 GB free (operator override)")
    args = ap.parse_args()
    try:
        build(Path(args.raw), Path(args.out), args.seed,
              max_memory_mb=args.max_memory_mb,
              skip_disk_check=args.skip_disk_check)
    except (ColumnMismatchError, ValidationFailure, MemoryGuardError) as exc:
        print(f"\nBUILD FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

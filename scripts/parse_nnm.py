"""Round F2 task 4 — parser for the four NNM category files (shared module).

OWNERSHIP (Round F2 parallel plan): this module is owned by Subagent B.
Subagent A's scripts/build_real_data.py and scripts/generate_mock_data.py
IMPORT it and rely on the frozen signatures below — established by the main
thread pre-dispatch so the two workstreams never edit one file:

    parse_nnm_file(path)                     -> ParsedNnmFile (dict)
    parse_nnm_dir(dir_path)                  -> list[row dict] across all four
    write_mock_nnm_files(out_dir, advisor_sids, seed=77, months=..., as_of=...)
                                             -> list[Path] (four files)

File format (identical across ECNNM_/NBNNM_/YINNM_/FSNNM_*.txt):

    H2026-07-31                                        <- header, as-of date
    DEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM    <- column header
    D2026-01-01|F029380|2026-01-31|0.00|548952.66      <- D prefix on the date

Parsing rules (spec 4.2): skip the H line but take the as-of date from it;
the second line is the column header (its first field reads "Entry_Dt" once
the D prefix is stripped — it is recognised by CONTENT, not position); strip
the leading D from every data row's Entry_Dt; split on '|'. Values can be
NEGATIVE in both NNM columns — that is real data, not an error.

Category provenance (spec 4.1): only EC is confirmed by the plan document
(the award-rate table is titled "Existing Client Annual NNM Flows" — PCA
p.4); NB / YI / FS are INFERRED from the filenames. Every row therefore
carries category_source = the raw file prefix, so a mislabel is correctable
without re-parsing.
"""
from __future__ import annotations

import random
from pathlib import Path

# raw file prefix -> category code. The prefix is stored on every row as
# category_source; the code is the working label (EC confirmed, rest inferred).
CATEGORY_BY_PREFIX = {
    "ECNNM": "EC",   # Existing Client — CONFIRMED by the plan document
    "NBNNM": "NB",   # New Business — inferred from the filename
    "YINNM": "YI",   # Year-Initiated — inferred from the filename
    "FSNNM": "FS",   # Full Service — inferred from the filename
}

CATEGORY_LABELS = {
    "EC": "Existing Client",
    "NB": "New Business",
    "YI": "Year-Initiated",
    "FS": "Full Service",
}


class NnmParseError(ValueError):
    """Malformed NNM file — names the file and the offending line."""


def _dt(date_str: str) -> str:
    """'2026-01-31' -> the graph's DATETIME string convention."""
    date_str = date_str.strip()
    if len(date_str) != 10 or date_str[4] != "-" or date_str[7] != "-":
        raise NnmParseError(f"not a YYYY-MM-DD date: {date_str!r}")
    return f"{date_str} 00:00:00"


def category_for_filename(path: str | Path) -> tuple[str, str]:
    """(category, category_source) from the raw filename prefix.

    'ECNNM_20260731.txt' -> ('EC', 'ECNNM'). Raises NnmParseError on an
    unrecognised prefix — a fifth file must be looked at, never guessed.
    """
    name = Path(path).name
    for prefix, category in CATEGORY_BY_PREFIX.items():
        if name.upper().startswith(prefix):
            return category, prefix
    raise NnmParseError(
        f"unrecognised NNM filename {name!r} — expected a prefix in "
        f"{sorted(CATEGORY_BY_PREFIX)}; a new file kind needs a human look, "
        "not a guess")


def parse_nnm_file(path: str | Path) -> dict:
    """Parse one NNM file into row dicts matching phx_dm_pce_advisor_nnm.

    Returns {"as_of_dt", "category", "category_source", "rows": [...]} where
    each row carries nnm_id / advisor_sid / month_id / category /
    category_source / mtd_nnm / ytd_nnm / entry_dt / as_of_dt.
    """
    path = Path(path)
    category, category_source = category_for_filename(path)
    lines = [ln.rstrip("\r\n") for ln in path.read_text().splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    if not lines or not lines[0].startswith("H"):
        raise NnmParseError(f"{path.name}: first line must be the H<as-of-date> header")
    as_of_dt = _dt(lines[0][1:])

    rows: list[dict] = []
    seen_ids: dict[str, int] = {}
    trailer_count: int | None = None
    trailer_lineno: int | None = None
    for lineno, line in enumerate(lines[1:], start=2):
        # Round 5 task 5: a line beginning with 'T' is the TRAILER — 'T'
        # followed by the record count the file says it holds. It turns a
        # crash into a verification: we can prove we read every row.
        if line.startswith("T"):
            if trailer_count is not None:
                raise NnmParseError(
                    f"{path.name}:{lineno}: second trailer line {line!r} "
                    f"(first at line {trailer_lineno})")
            try:
                trailer_count = int(line[1:].strip())
            except ValueError as exc:
                raise NnmParseError(
                    f"{path.name}:{lineno}: trailer is not 'T<count>': "
                    f"{line!r}") from exc
            trailer_lineno = lineno
            continue
        if trailer_count is not None:
            raise NnmParseError(
                f"{path.name}:{lineno}: data after the trailer line "
                f"(trailer at line {trailer_lineno}): {line!r}")
        if not line.startswith("D"):
            raise NnmParseError(f"{path.name}:{lineno}: expected a D-prefixed line, got {line!r}")
        fields = line[1:].split("|")  # strip the D prefix, split on |
        if fields[0].strip() == "Entry_Dt":
            continue  # the column-header line — recognised by content
        if len(fields) != 5:
            raise NnmParseError(
                f"{path.name}:{lineno}: expected 5 fields "
                "(Entry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM), got "
                f"{len(fields)}: {line!r}")
        entry_dt_raw, advisor_sid, month_year, mtd_raw, ytd_raw = (f.strip() for f in fields)
        month_id = month_year[:4] + month_year[5:7]  # '2026-01-31' -> '202601'
        try:
            mtd_nnm = float(mtd_raw)   # negatives are REAL, preserved as-is
            ytd_nnm = float(ytd_raw)
        except ValueError as exc:
            raise NnmParseError(f"{path.name}:{lineno}: non-numeric NNM value: {line!r}") from exc
        nnm_id = f"{advisor_sid}|{month_id}|{category}"
        if nnm_id in seen_ids:
            raise NnmParseError(
                f"{path.name}:{lineno}: duplicate advisor+month row "
                f"({nnm_id!r}, first seen line {seen_ids[nnm_id]}) — one MTD/YTD "
                "row per advisor per month is the format; a duplicate is a feed "
                "fault to raise, not to silently overwrite")
        seen_ids[nnm_id] = lineno
        rows.append({
            "nnm_id": nnm_id,
            "advisor_sid": advisor_sid,
            "month_id": month_id,
            "category": category,
            "category_source": category_source,
            "mtd_nnm": mtd_nnm,
            "ytd_nnm": ytd_nnm,
            "entry_dt": _dt(entry_dt_raw),
            "as_of_dt": as_of_dt,
        })
    # Round 5 task 5: the trailer states how many data rows the file should
    # hold — a mismatch is a truncated or padded feed and FAILS LOUDLY.
    if trailer_count is not None and trailer_count != len(rows):
        raise NnmParseError(
            f"{path.name}: trailer says {trailer_count} data rows but "
            f"{len(rows)} were parsed — truncated or altered feed; do not load")
    return {"as_of_dt": as_of_dt, "category": category,
            "category_source": category_source, "rows": rows,
            "trailer_count": trailer_count}


def parse_nnm_dir(dir_path: str | Path, pattern: str = "*NNM_*.txt") -> list[dict]:
    """Parse every NNM file in a directory; rows across all four, sorted for
    deterministic CSV output. Raises if no file matches — silence would look
    like an empty feed."""
    dir_path = Path(dir_path)
    files = sorted(dir_path.glob(pattern))
    if not files:
        raise NnmParseError(f"no NNM files matching {pattern!r} in {dir_path}")
    rows: list[dict] = []
    for f in files:
        rows.extend(parse_nnm_file(f)["rows"])
    rows.sort(key=lambda r: (r["category"], r["advisor_sid"], r["month_id"]))
    return rows


# --------------------------------------------------------------------------- mock fabrication
# Used by BOTH generators: generate_mock_data.py (demo advisors V0000xx) and
# make_test_raw_extracts.py (fabricated client-shaped raw set, T0000xx). Own
# seeded RNG, no builtin hash(), never touches the caller's RNG stream — the
# 9X post-pass determinism precedent.

DEFAULT_MOCK_MONTHS = ("202601", "202602", "202603", "202604", "202605", "202606")

# Per-category YTD scale bands (drawn once per advisor x category). EC spreads
# advisors across the plan's award bands (negative through well above the
# qualification threshold) so the threshold display has honest variety without any band value
# living anywhere but the plan document.
_SCALE_RANGES = {
    "EC": (-1_500_000.0, 14_000_000.0),
    "NB": (-400_000.0, 5_000_000.0),
    "YI": (-250_000.0, 2_500_000.0),
    "FS": (-600_000.0, 3_500_000.0),
}


def _month_end(month_id: str) -> str:
    days = {"01": "31", "02": "28", "03": "31", "04": "30", "05": "31",
            "06": "30", "07": "31", "08": "31", "09": "30", "10": "31",
            "11": "30", "12": "31"}[month_id[4:6]]
    return f"{month_id[:4]}-{month_id[4:6]}-{days}"


def build_mock_nnm_lines(advisor_sids: list[str], seed: int = 77,
                         months: tuple[str, ...] = DEFAULT_MOCK_MONTHS,
                         as_of: str = "2026-06-30") -> dict[str, list[str]]:
    """{file prefix: [file lines]} for the four NNM files, deterministic."""
    out: dict[str, list[str]] = {}
    for prefix in sorted(CATEGORY_BY_PREFIX):
        rng = random.Random(f"{seed}|{prefix}|nnm")  # own stream per file
        category = CATEGORY_BY_PREFIX[prefix]
        lines = [f"H{as_of}", "DEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM"]
        lo, hi = _SCALE_RANGES[category]
        for sid in sorted(advisor_sids):
            target_ytd = rng.uniform(lo, hi)
            ytd = 0.0
            for i, month_id in enumerate(months):
                # monthly step toward the target with noise; some months dip
                # negative even when the year trends positive — real feeds do
                step = target_ytd / len(months)
                mtd = step + rng.uniform(-0.8, 0.8) * abs(step)
                if rng.random() < 0.12:
                    mtd = -abs(mtd)
                if rng.random() < 0.08:
                    mtd = 0.0
                ytd = round(ytd + mtd, 2)
                mtd = round(mtd, 2)
                entry_dt = f"{month_id[:4]}-{month_id[4:6]}-01"
                lines.append(
                    f"D{entry_dt}|{sid}|{_month_end(month_id)}|{mtd:.2f}|{ytd:.2f}")
        # Round 5 task 5: the real feed ends with a T<record-count> trailer —
        # the fabricated files carry one too so generation round-trips the
        # parser's trailer verification.
        lines.append(f"T{len(lines) - 2}")  # data rows only (H + column header excluded)
        out[prefix] = lines
    return out


def write_mock_nnm_files(out_dir: str | Path, advisor_sids: list[str],
                         seed: int = 77,
                         months: tuple[str, ...] = DEFAULT_MOCK_MONTHS,
                         as_of: str = "2026-06-30") -> list[Path]:
    """Write the four raw-format NNM files (round-trippable through the
    parser — generation and parsing stay honest to one format)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = as_of.replace("-", "")
    paths = []
    for prefix, lines in build_mock_nnm_lines(advisor_sids, seed=seed,
                                              months=months, as_of=as_of).items():
        p = out_dir / f"{prefix}_{date_tag}.txt"
        p.write_text("\n".join(lines) + "\n")
        paths.append(p)
    return paths

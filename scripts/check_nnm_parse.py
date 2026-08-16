"""Round F2 task 4.1 — deterministic checks for scripts/parse_nnm.py.

Fabricates NNM files in a temp dir and asserts every parsing rule the spec
states. Prints PASS/FAIL per check; exits nonzero on any failure. No LLM, no
network, no writes outside the temp dir.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parse_nnm import (  # noqa: E402
    CATEGORY_BY_PREFIX,
    NnmParseError,
    parse_nnm_dir,
    parse_nnm_file,
    write_mock_nnm_files,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def expect_error(name: str, fn, needle: str) -> None:
    try:
        fn()
    except NnmParseError as exc:
        check(name, needle in str(exc), f"error: {exc}")
    else:
        check(name, False, "no NnmParseError raised")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="nnm_check_"))

    # --- N1: canonical file parses; H line skipped but as-of captured
    f = tmp / "ECNNM_20260731.txt"
    f.write_text(
        "H2026-07-31\n"
        "DEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
        "D2026-01-01|F029380|2026-01-31|0.00|548952.66\n"
        "D2026-02-01|F029380|2026-02-28|-125000.10|423952.56\n")
    parsed = parse_nnm_file(f)
    check("N1 as-of taken from H line", parsed["as_of_dt"] == "2026-07-31 00:00:00",
          parsed["as_of_dt"])
    check("N1 H line yields no data row", len(parsed["rows"]) == 2)

    # --- N2: column-header recognised by CONTENT, not position (header after
    # a data line still skipped)
    f2 = tmp / "NBNNM_20260731.txt"
    f2.write_text(
        "H2026-07-31\n"
        "D2026-01-01|F000001|2026-01-31|10.00|10.00\n"
        "DEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
        "D2026-02-01|F000001|2026-02-28|5.00|15.00\n")
    p2 = parse_nnm_file(f2)
    check("N2 header line recognised by content anywhere", len(p2["rows"]) == 2,
          f"{len(p2['rows'])} rows")

    # --- N3: D prefix stripped from the entry date
    check("N3 D prefix stripped", parsed["rows"][0]["entry_dt"] == "2026-01-01 00:00:00",
          parsed["rows"][0]["entry_dt"])

    # --- N4: negatives preserved in both columns
    f4 = tmp / "YINNM_20260731.txt"
    f4.write_text("H2026-07-31\nDEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
                  "D2026-03-01|F9|2026-03-31|-1.50|-2.75\n")
    r4 = parse_nnm_file(f4)["rows"][0]
    check("N4 negatives preserved (mtd and ytd)",
          r4["mtd_nnm"] == -1.50 and r4["ytd_nnm"] == -2.75, f"{r4['mtd_nnm']}/{r4['ytd_nnm']}")

    # --- N5: month_id derivation from Month_Year
    check("N5 month_id from Month_Year", r4["month_id"] == "202603", r4["month_id"])

    # --- N6: nnm_id format advisor|month|category
    check("N6 nnm_id format", r4["nnm_id"] == "F9|202603|YI", r4["nnm_id"])

    # --- N7: category + category_source from filename prefix
    check("N7 category/category_source from prefix",
          r4["category"] == "YI" and r4["category_source"] == "YINNM",
          f"{r4['category']}/{r4['category_source']}")

    # --- N8: unrecognised filename prefix raises, never guessed
    f8 = tmp / "XXNNM_20260731.txt"
    f8.write_text("H2026-07-31\nDEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n")
    expect_error("N8 unrecognised prefix raises", lambda: parse_nnm_file(f8), "unrecognised")

    # --- N9: malformed lines raise naming file + line
    f9 = tmp / "FSNNM_20260731.txt"
    f9.write_text("H2026-07-31\nDEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
                  "D2026-01-01|F1|2026-01-31|1.00\n")  # 4 fields
    expect_error("N9 wrong field count names file:line", lambda: parse_nnm_file(f9),
                 "FSNNM_20260731.txt:3")
    f9.write_text("H2026-07-31\nDEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
                  "D2026-01-01|F1|2026-01-31|abc|1.00\n")
    expect_error("N9b non-numeric NNM names file:line", lambda: parse_nnm_file(f9),
                 "FSNNM_20260731.txt:3")
    f9.write_text("D2026-01-01|F1|2026-01-31|1.00|1.00\n")
    expect_error("N9c missing H header raises", lambda: parse_nnm_file(f9), "H<as-of-date>")
    f9.write_text("H2026-07-31\nDEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
                  "X2026-01-01|F1|2026-01-31|1.00|1.00\n")
    expect_error("N9d non-D data line raises", lambda: parse_nnm_file(f9), "D-prefixed")

    # --- N10: duplicate advisor+month row raises (feed fault, not overwrite)
    f9.write_text("H2026-07-31\nDEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM\n"
                  "D2026-01-01|F1|2026-01-31|1.00|1.00\n"
                  "D2026-01-15|F1|2026-01-31|2.00|3.00\n")
    expect_error("N10 duplicate advisor+month raises", lambda: parse_nnm_file(f9), "duplicate")

    # --- N11: round-trip — write_mock_nnm_files output parses; deterministic
    mock_dir = tmp / "mock"
    sids = ["V000001", "V000002", "V000019"]
    paths = write_mock_nnm_files(mock_dir, sids, seed=77)
    rows_a = parse_nnm_dir(mock_dir)
    paths2 = write_mock_nnm_files(mock_dir, sids, seed=77)
    rows_b = parse_nnm_dir(mock_dir)
    check("N11 four files written", len(paths) == 4 and
          {p.name[:5] for p in paths} == set(CATEGORY_BY_PREFIX), str([p.name for p in paths]))
    check("N11b round-trip parses (3 sids x 6 months x 4 cats)", len(rows_a) == 72,
          f"{len(rows_a)} rows")
    check("N11c deterministic across regenerations", rows_a == rows_b)
    check("N11d negatives exist in the mock feed",
          any(r["mtd_nnm"] < 0 for r in rows_a), "real feeds go negative; so must the mock")

    # --- N12: parse_nnm_dir raises on an empty dir (silence would look like
    # an empty feed)
    empty = tmp / "empty"; empty.mkdir()
    expect_error("N12 empty dir raises", lambda: parse_nnm_dir(empty), "no NNM files")

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

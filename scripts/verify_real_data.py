"""Round F task 4.4 — verify the loaded REAL dataset against its manifest.

    python3 scripts/verify_real_data.py [--data-dir data/real]

Thin wrapper over the existing manifest verification: counts every manifest
target in the active graph client and compares with expected_rows — any
deviation fails loudly (exit 1). Run after scripts/load_real_data.py, with the
same --data-dir.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data/real")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    manifest = (data_dir if data_dir.is_absolute() else ROOT / data_dir) / "manifest.json"
    if not manifest.exists():
        print(f"ERROR: {manifest} not found — run scripts/build_real_data.py first",
              file=sys.stderr)
        return 1

    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.setdefault(
        "SQLITE_DB_PATH", str(Path(str(data_dir)) / "checkpoints" / "ingestion.db")
    )

    # import AFTER the env is set — settings are cached at first use
    from app.graph.client import get_graph_client  # noqa: E402
    from app.ingestion.manifest_check import verify_counts_against_manifest  # noqa: E402

    try:
        report = verify_counts_against_manifest(get_graph_client())
    except RuntimeError as exc:  # count mismatch raises — keep the message, exit 1
        print(f"VERIFY FAILED — {exc}", file=sys.stderr)
        return 1
    print(f"manifest verification: ok={report['ok']} "
          f"targets checked={len(report['checked'])} mismatches={len(report['mismatches'])}")
    for m in report.get("mismatches", []):
        print(f"  MISMATCH {m}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

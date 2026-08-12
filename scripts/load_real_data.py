"""Round F task 4.4 — load the REAL dataset through the existing ingestion pipeline.

    python3 scripts/load_real_data.py [--data-dir data/real] [--fresh]

Thin wrapper over the manifest-driven ingestion (the same path
scripts/load_mock_data.py exercises): it points DATA_DIR at the real dataset
built by scripts/build_real_data.py and runs every manifest entity (vertices
first, then edges) through IngestionService's batch/checkpoint loop, then
verifies loaded counts against data/real/manifest.json — failing loudly on any
mismatch. NO GSQL loading jobs run; ingestion is Python upserts. Schema DDL
(docs/tigergraph/01..03) is still a required one-time install on a real graph.

The env is set BEFORE any app import, because get_settings() is cached at first
use. SQLITE_DB_PATH keeps real-data checkpoints separate from the mock set's,
so loading real data never corrupts the mock checkpoint state the
verify_round_* suites rely on.
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
    ap.add_argument("--data-dir", default="data/real",
                    help="dataset directory (manifest.json + vertices/ + edges/)")
    ap.add_argument("--fresh", action="store_true",
                    help="clear ingestion checkpoints first (full re-write)")
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
    print(f"DATA_DIR={os.environ['DATA_DIR']}  SQLITE_DB_PATH={os.environ['SQLITE_DB_PATH']}")

    # import AFTER the env is set — settings are cached at first use
    import scripts.load_mock_data as loader  # noqa: E402

    if args.fresh and "--fresh" not in sys.argv:
        sys.argv.append("--fresh")
    loader.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

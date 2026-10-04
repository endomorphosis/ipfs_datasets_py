#!/usr/bin/env python3
"""Ingest a CourtListener docket into the docket dataset pipeline."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    cli_path = PROJECT_ROOT / "ipfs_datasets_py" / "cli" / "docket_cli.py"
    spec = importlib.util.spec_from_file_location("courtlistener_docket_cli", cli_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load docket CLI from {cli_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = list(argv if argv is not None else sys.argv[1:])
    if "--input-type" not in args:
        args = ["--input-type", "courtlistener", *args]
    return int(module.main(args))


if __name__ == "__main__":
    raise SystemExit(main())

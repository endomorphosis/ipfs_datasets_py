#!/usr/bin/env python3
"""Observe the candidate parser and generate a sealed, bounded context note."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--task-cid", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    from run_autoformal_supervisor import pin_accelerate
    pin_accelerate(args.accelerate_root)
    from ipfs_datasets_py.logic.autoformal.repair_context import build_note, persist_note
    result = persist_note(args.output_directory, build_note(
        ROOT, args.packet, args.sha256, args.task_cid,
    ))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

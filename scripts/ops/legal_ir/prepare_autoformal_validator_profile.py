#!/usr/bin/env python3
"""Generate a reviewed private validator profile, then seal the applied result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--seal", action="store_true", help="Seal an already applied exact profile.")
    parser.add_argument("--runtime-profile", choices=["autoformal-runtime-v1", "autoformal-runtime-v2"], default="",
                        help="New versioned deployment only; legacy profiles are not rewritten.")
    args = parser.parse_args(argv)
    repository = args.repository_root.resolve(strict=True)
    runtime = args.runtime_root.resolve(strict=True)
    if repository == ROOT or repository.parent != runtime:
        parser.error("deployment requires a private Git repository directly inside the owned runtime")
    top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repository, text=True).strip()
    if Path(top).resolve() != repository:
        parser.error("deployment target is not a Git root")
    from ipfs_datasets_py.logic.autoformal.validator_profile import (
        deployment_path, profile_patch, seal_deployment,
    )
    packets = runtime / "packets"
    if args.seal:
        seal_deployment(repository, packets, runtime_profile=args.runtime_profile)
        print(json.dumps({"sealed": True, "receipt": str(deployment_path(repository)), "published": False}))
    else:
        print(json.dumps({"patch": profile_patch(repository, packets, runtime_profile=args.runtime_profile), "repository": str(repository)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

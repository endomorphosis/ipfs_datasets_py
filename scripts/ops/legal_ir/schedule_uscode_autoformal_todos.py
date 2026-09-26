#!/usr/bin/env python3
"""Locate Hugging Face autoformal todos and enqueue them for time management.

Reads a local release pointer or locator (not JSONL). Pins the accelerate
checkout, materializes the supervisor board, and registers ready tasks on the
persistent queue using estimated tokens and wall time.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--pointer", type=Path, required=True, help="Release pointer or locator.json")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--board",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "uscode-autoformal.todo.md",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "uscode-autoformal-queue.json",
    )
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-validation-seconds", type=int, default=None)
    parser.add_argument("--package-root", type=Path, default=None)
    args = parser.parse_args(argv)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "autoformal_supervisor_pin",
        Path(__file__).with_name("run_autoformal_supervisor.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load accelerate pin helper")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    binding = helper.pin_accelerate(args.accelerate_root)
    receipt = schedule_from_pointer(
        args.pointer,
        repo_root=args.repo_root,
        board=args.board,
        queue_path=args.queue,
        package_root=args.package_root,
        max_tokens=args.max_tokens,
        max_validation_seconds=args.max_validation_seconds,
    )
    print(json.dumps({**binding, **receipt}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    raise SystemExit(main())

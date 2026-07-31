"""CLI: ``python -m benchmarks.knowledge_graphs.chaos``."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run_chaos_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated KG chaos suite and write a receipt."
    )
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path.cwd(), type=Path)
    parser.add_argument("--timeout", default=900.0, type=float)
    args = parser.parse_args(argv)
    result = run_chaos_suite(
        repo_root=args.repo_root,
        work_dir=args.work_dir,
        receipt_path=args.receipt,
        environment_id=args.environment_id,
        timeout_s=args.timeout,
    )
    print(f"status={result.status}")
    print(f"tests={result.receipt['summary']['tests']}")
    print(f"digest={result.receipt['digest']}")
    print(f"receipt={result.receipt_path}")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

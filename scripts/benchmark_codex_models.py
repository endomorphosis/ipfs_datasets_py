"""Compatibility wrapper.

This benchmark script has been renamed to scripts/benchmark_symai.py.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        # When executed as a script (e.g. `python ipfs_datasets_py/scripts/...`),
        # this directory is on sys.path, so import directly.
        from benchmark_symai import main as _main  # type: ignore
    except Exception:
        # Fallback for installed-package contexts.
        from scripts.benchmark_symai import main as _main  # type: ignore

    return int(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

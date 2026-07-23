#!/usr/bin/env python3
"""Thin wrapper around the crypto-exchange proof CLI for ops automation."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import main as prove_all_main


def main(argv: list[str] | None = None) -> int:
    return prove_all_main(argv)


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

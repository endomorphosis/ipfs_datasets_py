#!/usr/bin/env python3
"""Autoformalize supported codebases into canonical security IR JSON."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import SourceCodeExtractor
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import canonicalize_ir_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_path', help='Supported source file or directory to autoformalize')
    parser.add_argument('--model-id', help='Optional model_id override for the emitted IR')
    parser.add_argument('--out', help='Optional output path; stdout is used when omitted')
    args = parser.parse_args(argv)

    model = SourceCodeExtractor().extract_ir_from_path(args.source_path, model_id=args.model_id)
    payload = canonicalize_ir_json(model)
    if args.out:
        Path(args.out).write_text(payload + '\n', encoding='utf-8')
    else:
        print(payload)
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())

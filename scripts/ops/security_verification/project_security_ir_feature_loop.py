#!/usr/bin/env python3
"""Project security IR facts into a Codex-friendly feature-loop bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import SecurityIRFeatureLoopProjector
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import SecurityModelIR, validate_ir


def _load_projected_payload(
    *,
    example: bool,
    model_path: str | None,
    source_path: str | None,
    model_id: str | None,
) -> dict[str, object]:
    projector = SecurityIRFeatureLoopProjector()
    if source_path:
        return projector.project_path(source_path, model_id=model_id)
    if example or not model_path:
        from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model

        return projector.project_model(example_minimal_exchange_model())
    payload = json.loads(Path(model_path).read_text(encoding='utf-8'))
    return projector.project_model(validate_ir(SecurityModelIR.from_dict(payload)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', action='store_true', help='Project the built-in example model')
    parser.add_argument('--model', help='Existing canonical security IR JSON file')
    parser.add_argument('--source-path', help='Supported source file or directory to autoformalize and project')
    parser.add_argument('--model-id', help='Optional model_id override when using --source-path')
    parser.add_argument('--out', help='Optional output path; stdout is used when omitted')
    args = parser.parse_args(argv)
    if sum(bool(value) for value in (args.example, args.model, args.source_path)) > 1:
        parser.error('choose only one input: --example, --model, or --source-path')

    payload = _load_projected_payload(
        example=args.example,
        model_path=args.model,
        source_path=args.source_path,
        model_id=args.model_id,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(rendered + '\n', encoding='utf-8')
    else:
        print(rendered)
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())

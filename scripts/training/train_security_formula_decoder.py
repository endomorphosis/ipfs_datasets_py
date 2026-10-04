"""Train an isolated code-production head from explicitly selected source samples.

Samples are JSON rows with id/split/source and optional source_sha256. Supply an
admitted LegalIR lexical fork descriptor. The parent is validated and preserved.
This command neither downloads training inputs nor publishes the result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--initializer-descriptor", required=True, type=Path)
    parser.add_argument("--published-binding", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=160)
    parser.add_argument("--training-data-scope", default="caller_declared_development_controls",
        choices=["authored_development_controls", "publicus_and_authored_development_controls",
                 "caller_declared_development_controls"])
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable
    from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_decoder import train_security_formula_decoder
    try:
        paths = [args.samples, args.initializer_descriptor, args.published_binding, args.provenance]
        pinned = {path.absolute(): portable._read(path.absolute(), 2 * 1024 * 1024)
                  for path in paths if path is not None}
        load = lambda path: portable._decode(pinned[path.absolute()]) if path is not None else None
        samples = load(args.samples)
        if type(samples) is not list:
            raise ValueError("explicit bounded sample list required")
        provenance_sha256 = portable._sha(pinned[args.provenance.absolute()]) if args.provenance else None
        decoder = train_security_formula_decoder(samples=samples, weight_transfer=load(args.initializer_descriptor),
            published_binding=load(args.published_binding), output=args.output.absolute(), epochs=args.epochs,
            training_data_scope=args.training_data_scope, training_provenance_sha256=provenance_sha256)
        if any(portable._read(path, 2 * 1024 * 1024) != raw for path, raw in pinned.items()):
            raise ValueError("training input declaration changed")
        result = {"status": "trained", "decoder": decoder, "provider_calls": 0, "download_calls": 0,
            "legal_parent_modified": False, "input_sha256": {str(path): portable._sha(raw) for path, raw in pinned.items()},
            "exit_code": 0}
    except Exception as error:
        result = {"status": "not_qualified", "error_type": type(error).__name__, "exit_code": 2}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

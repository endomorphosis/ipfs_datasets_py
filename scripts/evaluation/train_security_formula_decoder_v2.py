#!/usr/bin/env python3
"""Fork a pinned v1 SecurityIR production checkpoint into bounded v2 controls.

Run with the repository package on PYTHONPATH. No download, provider, publication
or benchmark source is used. Every output goes into a new local directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder_v2 as decoder
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_curriculum_v2 import authored_formula_samples_v2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-checkpoint-descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=200)
    arguments = parser.parse_args()
    if not 1 <= arguments.epochs <= 256:
        parser.error("--epochs must be between 1 and 256")
    output = arguments.output.resolve()
    if output.exists():
        parser.error("--output must be a fresh directory")
    parent_raw = arguments.parent_checkpoint_descriptor.read_bytes()
    parent = json.loads(parent_raw)
    samples = authored_formula_samples_v2()
    raw = json.dumps(samples, sort_keys=True, indent=2).encode()
    source_digest = hashlib.sha256(raw).hexdigest()
    output.mkdir(parents=True)
    (output / "controls.json").write_bytes(raw)
    checkpoint = decoder.train_security_formula_decoder_v2(samples=samples, parent_checkpoint=parent,
        output=output / "checkpoint", epochs=arguments.epochs, training_provenance_sha256=source_digest)
    loaded = decoder.load_security_formula_decoder_v2(checkpoint)
    (output / "descriptor.json").write_text(json.dumps(checkpoint, sort_keys=True, indent=2) + "\n")
    receipt = {"schema": "security-production-expansion-training-run@1", "checkpoint": checkpoint,
        "controls_sha256": source_digest, "parent_descriptor_sha256": hashlib.sha256(parent_raw).hexdigest(),
        "parent_transfer": loaded["training"]["parent_transfer"], "metrics": loaded["training"]["metrics"], "raw_metrics": loaded["training"]["raw_metrics"],
        "epochs": arguments.epochs, "provider_calls": 0, "download_calls": 0,
        "benchmark_source_used_for_training": False, "heldout_used_for_fit": False,
        "scope": "authored development capabilities; structural split exclusion; no blind generalization claim"}
    (output / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"descriptor": str(output / "descriptor.json"), "metrics": receipt["metrics"]}, indent=2))


if __name__ == "__main__":
    main()

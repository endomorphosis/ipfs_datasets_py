#!/usr/bin/env python3
"""Synthetic metadata-only control; never load weights, tensors or an encoder.

Only private fixture JSON files under the requested fresh artifact directory
are written. The production metadata owner and its basic fixture are read.
"""
import argparse
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    repository = options.repository
    if not repository.is_absolute() or repository != repository.resolve(strict=True):
        raise ValueError("explicit canonical existing repository required")
    if not options.output.is_absolute() or options.output.exists():
        raise ValueError("fresh absolute output required")
    location = options.output.parent / (options.output.stem + "-fixture")
    if location.exists():
        raise ValueError("fresh private fixture location required")
    os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        CUDA_VISIBLE_DEVICES="")
    forbidden = {"torch", "numpy", "transformers", "sentence_transformers", "accelerate",
                 "datasets", "huggingface_hub", "safetensors", "duckdb", "sqlite3"}

    class RefuseHeavy(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in forbidden:
                raise AssertionError("metadata attempted heavy import: " + fullname)

    def deny_effects(event, arguments):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "subprocess.Popen"}:
            raise AssertionError("metadata attempted network/process effect: " + event)

    sys.meta_path.insert(0, RefuseHeavy())
    sys.addaudithook(deny_effects)
    sys.path.insert(0, str(repository))
    from tests.unit.logic.formalization.autoencoder.test_contextual_legal_ir_runtime import (
        make_contextual, prepare, repin,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as owner
    assert Path(owner.__file__) == repository / "ipfs_datasets_py/logic/formalization/autoencoder/contextual_legal_ir_runtime.py"
    owners = [Path(owner.__file__).with_name(name + ".py") for name in owner.SOURCE_OWNER_NAMES]
    owners.append(repository / "tests/unit/logic/formalization/autoencoder/test_contextual_legal_ir_runtime.py")
    sources_before = [pin(path) for path in owners]
    fixture = make_contextual(location)
    original = prepare(fixture)
    old_assets = {key: value for key, value in fixture["options"].items() if key.endswith("_pin")}
    # Replace only a paragraph vector with another finite384-wide unit vector.
    # Source text, clause vectors, saved source inventory and frozen model stay.
    fixture["rows"][0]["input"] = [float(index == 2) for index in range(384)]
    repin(fixture)
    altered = prepare(fixture)
    new_assets = {key: value for key, value in fixture["options"].items() if key.endswith("_pin")}
    assert old_assets["source_inputs_pin"]["sha256"] != new_assets["source_inputs_pin"]["sha256"]
    for key in ("checkpoint_pin", "preprocessing_pin", "donor_checkpoint_pin", "source_contexts_pin"):
        assert old_assets[key] == new_assets[key]
    assert original["row_ids"] == altered["row_ids"]
    assert all(value is False for value in altered["authority"].values())
    assert not altered["model_load_performed"] and not altered["model_inference_executed"]
    assert not any(name.split(".")[0] in forbidden for name in sys.modules)
    sources_after = [pin(path) for path in owners]
    assert sources_before == sources_after
    result = {
        "schema": "contextual-paragraph-caller-pin-boundary-observation/v1",
        "synthetic_untrained_fixture": True,
        "original_metadata_prepared": True,
        "caller_rehashed_changed_paragraph_vector_metadata_prepared": True,
        "unchanged_asset_pins": {key: old_assets[key] for key in (
            "checkpoint_pin", "preprocessing_pin", "donor_checkpoint_pin", "source_contexts_pin")},
        "paragraph_assets_before_after": [old_assets["source_inputs_pin"], new_assets["source_inputs_pin"]],
        "changed_source_row_id": "source:0",
        "source_text_context_inventory_and_model_bytes_unchanged": True,
        "source_owner_pins": sources_before,
        "source_endpoints_unchanged": True,
        "model_loaded": False, "model_inference_executed": False,
        "embeddings_generated": False, "training_executed": False,
        "database_or_network_executed": False, "original_assets_read_or_mutated": False,
        "authority": altered["authority"],
        "scope": "Caller-supplied paragraph asset SHA authenticates selected bytes. Saved source IDs/text and clause-context digest do not independently authenticate historical paragraph vector production. Actual original44-file-pinned replay is unaffected.",
        "recommendation": "State caller pin custody and independent producer correspondence separately. Before admitting different paragraph assets, require an explicit source/vector receipt join (or a saved authenticated per-row input-vector inventory), without rewriting historical checkpoint/preprocessing pins.",
    }
    options.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(pin(options.output)))


if __name__ == "__main__":
    main()

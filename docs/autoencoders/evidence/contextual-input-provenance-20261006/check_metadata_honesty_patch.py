#!/usr/bin/env python3
"""Prepare the original48-row lanes through the reviewed metadata-only patch."""
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
    parser.add_argument("--original-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if options.output.exists():
        raise ValueError("fresh output required")
    os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
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
    sys.path.insert(0, str(options.repository))
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as owner
    assert Path(owner.__file__) == options.repository / "ipfs_datasets_py/logic/formalization/autoencoder/contextual_legal_ir_runtime.py"
    sources = [Path(owner.__file__).with_name(name + ".py") for name in owner.SOURCE_OWNER_NAMES]
    before = [pin(path) for path in sources]
    results, assets = [], {}
    for dimension in (384, 768):
        historical = options.original_evidence / (str(dimension) + "-metadata-plan.json")
        original = json.loads(historical.read_bytes())
        native_pins = original["artifact_receipts"]
        for value in native_pins.values():
            observed = pin(Path(value["path"]))
            assert observed == value
            assets[value["path"]] = observed
        configured = dict(request=original["request"], row_ids=original["row_ids"],
            checkpoint_pin=native_pins["checkpoint"], preprocessing_pin=native_pins["preprocessing"],
            donor_checkpoint_pin=native_pins["donor_checkpoint"], source_inputs_pin=native_pins["source_inputs"],
            source_contexts_pin=native_pins["source_contexts"],
            source_owner_pins={name: pin(Path(owner.__file__).with_name(name + ".py")) for name in owner.SOURCE_OWNER_NAMES})
        prepared = owner.prepare_contextual_legal_ir_runtime(**configured)
        assert len(prepared["row_ids"]) == 48
        assert prepared["row_ids"] == original["row_ids"]
        cached_rows = json.loads(Path(native_pins["source_inputs"]["path"]).read_bytes())
        cached_contexts = json.loads(Path(native_pins["source_contexts"]["path"]).read_bytes())
        rows_by_id = {row["id"]: row for row in cached_rows}
        expected_inputs = {"rows": [rows_by_id[identifier] for identifier in original["row_ids"]],
            "contexts": {identifier: cached_contexts[identifier] for identifier in original["row_ids"]}}
        assert prepared["source_inputs"] == expected_inputs
        assert prepared["model_tensor_sha256"] == original["model_tensor_sha256"]
        assert prepared["input_contract"]["paragraph_vector_binding"] == "caller_pinned_asset_bytes"
        assert prepared["input_contract"]["saved_paragraph_vector_producer_authenticated"] is False
        assert all(value is False for value in prepared["authority"].values())
        assert not prepared["model_load_performed"] and not prepared["model_inference_executed"]
        results.append({"dimension": dimension, "row_count": 48, "source_inputs_unchanged": True,
            "selected_tensor_sha256": prepared["model_tensor_sha256"], "input_contract": prepared["input_contract"],
            "all_authority_false": True, "historical_metadata_plan_pin": pin(historical)})
    assert before == [pin(path) for path in sources]
    assert all(pin(Path(path)) == expected for path, expected in assets.items())
    assert not any(name.split(".")[0] in forbidden for name in sys.modules)
    result = {"schema": "contextual-honesty-patch-original-metadata-controls/v1", "completed": True,
        "lanes": results, "source_pins": before, "original_asset_pins": list(assets.values()),
        "source_and_original_asset_endpoints_unchanged": True, "model_loaded": False,
        "model_inference_executed": False, "training_executed": False, "embeddings_generated": False,
        "database_or_network_executed": False, "torch_or_ml_imported": False, "proof_authority": False,
        "scope": "Original48-row metadata preparation only on the additive provenance patch; no numerical replay or new quality qualification."}
    options.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(pin(options.output)))


if __name__ == "__main__":
    main()

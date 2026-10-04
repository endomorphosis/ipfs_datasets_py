"""Strict complete-checkpoint loader for the pinned native multilingual GTE.

The published safetensors includes the encoder and a two-tensor sparse token
classifier. The earlier bare-NewModel reference loader correctly rejects those
unexpected tensors. This separate adapter admits the declared complete
NewForTokenClassification architecture with no missing or ignored tensors, then
uses its unmodified encoder hidden states for the same CLS/L2 dense profile.
It never changes model bytes, supplies synthetic vectors, or resolves remote
code. The existing reference producer and its historical artifacts are intact.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.metadata
import json
from pathlib import Path
import sys
import types
import uuid

from . import source_embeddings_768 as reference

_require = reference._require
PROFILE_ID = reference.PROFILE_ID
DIMENSION = reference.DIMENSION
SCHEMA = "gte-complete-native-embedding-production/v1"


def _implementation():
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ("complete_loader", __file__), ("reference_producer", reference.__file__),
        ("asset_profile", reference._PROFILE.__file__))}


def _admit_loading(loading, actual_keys, stored_keys):
    for field in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
        _require(not loading.get(field), "complete model weight loading differs: " + field)
    _require(set(actual_keys) == set(stored_keys), "complete checkpoint tensor keys differ")
    _require({"classifier.weight", "classifier.bias"} <= set(actual_keys)
             and all(key.startswith("new.") or key in {"classifier.weight", "classifier.bias"}
                     for key in actual_keys), "expected complete encoder/classifier architecture required")


def _load_backend(assets):
    import torch
    from safetensors import safe_open
    from transformers import XLMRobertaTokenizerFast

    profile = reference._PROFILE
    model_directory, code_directory = Path(assets["model_directory"]), Path(assets["code_directory"])
    pins = {(item["relative_to"], item["path"]): item for item in assets["files"]}
    namespace = "_gte768_complete_verified_" + uuid.uuid4().hex
    package = types.ModuleType(namespace)
    package.__path__ = [str(code_directory)]
    package.__package__ = namespace
    package.__spec__ = importlib.machinery.ModuleSpec(namespace, loader=None, is_package=True)
    package.__spec__.submodule_search_locations = package.__path__
    loaded = [namespace]
    sys.modules[namespace] = package
    try:
        for name in ("configuration", "modeling"):
            path = code_directory / (name + ".py")
            sha, count, raw, _ = profile._read_or_hash(path, profile.MAX_JSON_BYTES, retain=True)
            pin = pins[("code", path.name)]
            _require(sha == pin["sha256"] and count == pin["bytes"], "verified complete-model source changed")
            qualified = namespace + "." + name
            module = types.ModuleType(qualified)
            module.__file__ = str(path)
            module.__package__ = namespace
            module.__spec__ = importlib.machinery.ModuleSpec(qualified, loader=None)
            sys.modules[qualified] = module
            loaded.append(qualified)
            exec(compile(raw, str(path), "exec"), module.__dict__)
        sha, count, raw, _ = profile._read_or_hash(model_directory / "config.json", profile.MAX_JSON_BYTES, retain=True)
        pin = pins[("model", "config.json")]
        _require(sha == pin["sha256"] and count == pin["bytes"], "verified complete-model configuration changed")
        config = sys.modules[namespace + ".configuration"].NewConfig.from_dict(json.loads(raw))
        _require(config.hidden_size == DIMENSION and config.max_position_embeddings == reference.MAX_TOKENS
                 and "NewForTokenClassification" in config.architectures and config.num_labels == 1,
                 "published complete architecture/shape differs")
        tokenizer = XLMRobertaTokenizerFast.from_pretrained(str(model_directory), local_files_only=True)
        with torch.random.fork_rng(devices=[]):
            model, loading = sys.modules[namespace + ".modeling"].NewForTokenClassification.from_pretrained(
                str(model_directory), config=config, local_files_only=True, use_safetensors=True,
                torch_dtype=torch.float32, attn_implementation="eager", output_loading_info=True)
        with safe_open(str(model_directory / "model.safetensors"), framework="pt", device="cpu") as stored:
            stored_keys = list(stored.keys())
        _admit_loading(loading, model.state_dict().keys(), stored_keys)
        _require(tuple(model.classifier.weight.shape) == (1, DIMENSION)
                 and tuple(model.classifier.bias.shape) == (1,), "sparse classifier tensor shapes differ")
        _require(model.config._attn_implementation == "eager" and not model.config.use_memory_efficient_attention,
                 "complete-model reference attention differs")
        model.to(device="cpu", dtype=torch.float32)
        model.eval()
        _require(all(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                     for parameter in model.parameters()), "complete model must be CPU float32")
        return torch, tokenizer, model, {"architecture": "NewForTokenClassification", "tensor_count": len(stored_keys),
            "tensor_names": sorted(stored_keys), "missing_keys": [], "unexpected_keys": [], "mismatched_keys": [],
            "error_msgs": [], "classifier_loaded": True, "classifier_logits_used_for_dense_embedding": False}
    finally:
        for name in reversed(loaded):
            sys.modules.pop(name, None)


def _verify_dense_path(torch, model, tokenizer, token_row):
    """Check complete-output hidden states against its actual bare encoder."""
    inputs = tokenizer.pad([token_row], padding=True, return_tensors="pt")
    with torch.inference_mode():
        complete = model(**inputs).last_hidden_state
        encoder = model.new(**inputs).last_hidden_state
    _require(torch.equal(complete, encoder), "complete model changed encoder hidden states")
    return {"probe_tokens": len(token_row["input_ids"]), "encoder_and_complete_hidden_states_bitwise_equal": True,
            "evaluation_mode": not model.training, "scope": "first admitted source; source used only, no targets"}


def embed_rows(rows, *, manifest_path, expected_manifest_sha256, model_directory, code_directory, batch_size=1):
    """Produce source-bound native 768D receipts using all published weights."""
    data = reference._source_rows(rows)
    _require(type(batch_size) is int and 1 <= batch_size <= 16, "batch_size must be in1..16")
    pins = _implementation()
    arguments = dict(expected_sha256=expected_manifest_sha256, model_directory=model_directory,
                     code_directory=code_directory)
    assets = reference._PROFILE.inspect_local_assets(manifest_path, **arguments)
    _require(assets["status"] == "available", "complete native model assets unavailable")
    torch, tokenizer, model, loading = _load_backend(assets)
    _require(tokenizer.padding_side == "right", "right padding required")
    token_rows = reference._tokenize(data, tokenizer, model.config.vocab_size)
    _require(reference._PROFILE.inspect_local_assets(manifest_path, **arguments) == assets,
             "complete-model assets changed while loading")
    path_verification = _verify_dense_path(torch, model, tokenizer, token_rows[0])
    vectors = reference._vectors(torch, model, tokenizer, token_rows, batch_size)
    _require(len(vectors) == len(data), "complete native embedding coverage differs")
    _require(reference._PROFILE.inspect_local_assets(manifest_path, **arguments) == assets and _implementation() == pins,
             "complete-model assets/implementation changed during inference")
    receipts = [{"schema": reference.RECEIPT_SCHEMA, "id": row["id"], "source_sha256": row["source_sha256"],
        "profile_id": PROFILE_ID, "dimension": DIMENSION, "embedding": vector,
        "token_count_including_special_tokens": len(tokens["input_ids"]),
        "token_input_sha256": reference._digest(tokens["input_ids"]), "truncated": False, "normalized": True,
        "asset_manifest_sha256": assets["manifest_sha256"]} for row, tokens, vector in zip(data, token_rows, vectors)]
    return {"schema": SCHEMA, "status": "completed", "profile_id": PROFILE_ID, "input_row_count": len(data),
        "receipt_count": len(receipts), "receipts": receipts, "assets": assets, "implementation": pins,
        "complete_checkpoint_loading": loading, "dense_path_verification": path_verification,
        "execution_profile": {"batch_size": batch_size, "device": "cpu", "dtype": "float32",
            "attention_implementation": "eager", "padding_side": "right", "pooling": "cls", "normalization": "l2",
            "max_tokens_including_special_tokens": reference.MAX_TOKENS, "overlength_policy": "reject"},
        "runtime_versions": {"python": sys.version.split()[0], **{name: importlib.metadata.version(name)
            for name in ("torch", "transformers", "tokenizers", "safetensors")}},
        "model_inference_executed": True, "runtime_compatibility_verified": True,
        "maximum_context_numerics_verified": False, "training_executed": False, "download_executed": False,
        "ir_decoder_executed": False, "source_semantics_verified": False, "proof_authority": False}

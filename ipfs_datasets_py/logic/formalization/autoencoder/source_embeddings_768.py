"""Offline, pinned CPU reference producer for multilingual GTE embeddings.

This module imports no tensor libraries until local assets pass admission.
It produces source embeddings, not IR candidates or a trained 768D decoder.
The 8D and 384D runtimes, caches and checkpoints are independent of this path.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import sys
import types
import uuid


def _profile_module():
    path = Path(__file__).with_name("gte_multilingual_profile.py")
    spec = importlib.util.spec_from_file_location("_gte768_local_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PROFILE = _profile_module()
PROFILE_ID = _PROFILE.PROFILE_ID
DIMENSION = 768
MAX_TOKENS = 8192
MAX_ROWS = 4096
MAX_SOURCE_CHARACTERS = 65536
MAX_SOURCE_BYTES = 262144
MAX_TOTAL_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_TOKENS = 262144
RECEIPT_SCHEMA = "gte-multilingual-embedding-receipt/v1"
PRODUCTION_SCHEMA = "gte-multilingual-embedding-production/v1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _source_rows(rows):
    _require(type(rows) is list and 0 < len(rows) <= MAX_ROWS,
             "source rows must be a nonempty list within the 4096 row limit")
    result, seen, total = [], set(), 0
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text"},
                 "embedding inputs must contain only id and source_text")
        identifier, source = row["id"], row["source_text"]
        _require(type(identifier) is str and 0 < len(identifier) <= 256
                 and "\x00" not in identifier, "bounded source identifier required")
        _require(identifier not in seen, "duplicate source identifier")
        _require(type(source) is str and source.strip() and "\x00" not in source
                 and len(source) <= MAX_SOURCE_CHARACTERS, "bounded nonempty source text required")
        try:
            identifier.encode("utf-8")
            raw = source.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("source and identifier must be valid UTF8") from error
        _require(len(raw) <= MAX_SOURCE_BYTES, "source exceeds UTF8 byte limit")
        total += len(raw)
        _require(total <= MAX_TOTAL_SOURCE_BYTES, "source rows exceed total UTF8 byte limit")
        seen.add(identifier)
        result.append({"id": identifier, "source_text": source,
                       "source_sha256": hashlib.sha256(raw).hexdigest()})
    return result


def _load_backend(assets):
    """Load the verified two-module implementation without remote resolution.

    The synthetic namespace has no initializer. Its modules are compiled from
    the admitted bytes, so an adjacent __init__.py or bytecode is never executed.
    This is integrity admission for trusted code, not an execution sandbox.
    """
    import torch
    from transformers import XLMRobertaTokenizerFast

    model_directory = Path(assets["model_directory"])
    code_directory = Path(assets["code_directory"])
    pins = {(item["relative_to"], item["path"]): item for item in assets["files"]}
    namespace = "_gte768_verified_" + uuid.uuid4().hex
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
            sha, count, raw, _ = _PROFILE._read_or_hash(path, _PROFILE.MAX_JSON_BYTES, retain=True)
            pin = pins[("code", path.name)]
            _require(sha == pin["sha256"] and count == pin["bytes"],
                     "verified implementation changed before loading")
            qualified = namespace + "." + name
            module = types.ModuleType(qualified)
            module.__file__ = str(path)
            module.__package__ = namespace
            module.__spec__ = importlib.machinery.ModuleSpec(qualified, loader=None)
            sys.modules[qualified] = module
            loaded.append(qualified)
            exec(compile(raw, str(path), "exec"), module.__dict__)
        sha, count, raw, _ = _PROFILE._read_or_hash(
            model_directory / "config.json", _PROFILE.MAX_JSON_BYTES, retain=True)
        pin = pins[("model", "config.json")]
        _require(sha == pin["sha256"] and count == pin["bytes"],
                 "verified configuration changed before loading")
        config = sys.modules[namespace + ".configuration"].NewConfig.from_dict(
            json.loads(raw))
        _require(config.hidden_size == DIMENSION and config.max_position_embeddings == MAX_TOKENS,
                 "model shape and context limit differ from profile")
        tokenizer = XLMRobertaTokenizerFast.from_pretrained(
            str(model_directory), local_files_only=True)
        with torch.random.fork_rng(devices=[]):
            model, loading = sys.modules[namespace + ".modeling"].NewModel.from_pretrained(
                str(model_directory), config=config, local_files_only=True,
                use_safetensors=True, torch_dtype=torch.float32,
                attn_implementation="eager", output_loading_info=True)
        for field in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
            _require(not loading.get(field), "model weight loading is incomplete: " + field)
        _require(model.config._attn_implementation == "eager"
                 and not model.config.use_memory_efficient_attention,
                 "reference attention implementation differs from profile")
        model.to(device="cpu", dtype=torch.float32)
        model.eval()
        for parameter in model.parameters():
            _require(parameter.device.type == "cpu" and parameter.dtype == torch.float32,
                     "reference model parameters must be CPU float32")
        return torch, tokenizer, model
    finally:
        for name in reversed(loaded):
            sys.modules.pop(name, None)


def _tokenize(rows, tokenizer, vocabulary_size):
    token_rows, total = [], 0
    for row in rows:
        ids = tokenizer.encode(row["source_text"], add_special_tokens=True, truncation=False)
        _require(type(ids) is list and 1 <= len(ids) <= MAX_TOKENS,
                 "source exceeds 8192 tokens including special tokens")
        _require(all(type(token) is int and 0 <= token < vocabulary_size for token in ids),
                 "token IDs must belong to the model vocabulary")
        total += len(ids)
        _require(total <= MAX_TOTAL_TOKENS, "request exceeds total token budget")
        token_rows.append({"input_ids": list(ids), "attention_mask": [1] * len(ids)})
    return token_rows


def _vectors(torch, model, tokenizer, token_rows, batch_size):
    result = []
    with torch.inference_mode():
        for start in range(0, len(token_rows), batch_size):
            batch = token_rows[start:start + batch_size]
            inputs = tokenizer.pad(batch, padding=True, return_tensors="pt")
            _require(set(inputs) == {"input_ids", "attention_mask"},
                     "tokenizer padding produced unexpected model inputs")
            width = max(len(row["input_ids"]) for row in batch)
            _require(tuple(inputs["input_ids"].shape) == (len(batch), width)
                     and tuple(inputs["attention_mask"].shape) == (len(batch), width),
                     "padded token input has the wrong shape")
            for index, row in enumerate(batch):
                active = inputs["input_ids"][index][inputs["attention_mask"][index].bool()].tolist()
                _require(active == row["input_ids"], "padding changed active token IDs")
                _require(inputs["attention_mask"][index].tolist() ==
                         row["attention_mask"] + [0] * (width - len(row["input_ids"])),
                         "reference tokenizer must pad on the right")
            inputs = {key: tensor.to("cpu") for key, tensor in inputs.items()}
            output = model(**inputs)
            hidden = output.last_hidden_state
            _require(tuple(hidden.shape) == (len(batch), width, DIMENSION)
                     and hidden.device.type == "cpu" and hidden.dtype == torch.float32,
                     "model output differs from the CPU float32 768D profile")
            cls = hidden[:, 0, :]
            _require(bool(torch.isfinite(cls).all()), "nonfinite CLS embedding")
            norms = torch.linalg.vector_norm(cls, dim=1, keepdim=True)
            _require(bool(torch.isfinite(norms).all()) and bool((norms > 0).all()),
                     "CLS embeddings must have a finite nonzero norm")
            for vector in (cls / norms).tolist():
                _require(len(vector) == DIMENSION and all(math.isfinite(value) for value in vector)
                         and abs(math.hypot(*vector) - 1.0) <= 1e-4,
                         "normalized embeddings must be finite 768D unit vectors")
                result.append(vector)
    return result


def embed_rows(rows, *, manifest_path, expected_manifest_sha256, model_directory,
               code_directory, batch_size=1):
    """Embed exact sources, or return an explicit unavailable-assets report.

    Every input is token checked without truncation before the first forward.
    Missing assets return zero receipts; malformed inputs or changed assets fail.
    The per-request byte/token bounds and batch limit are admission bounds, not
    measured evidence that 8192-token attention fits a particular machine.
    """
    data = _source_rows(rows)
    _require(type(batch_size) is int and 1 <= batch_size <= 16, "batch_size must be within 1..16")
    arguments = dict(expected_sha256=expected_manifest_sha256,
                     model_directory=model_directory, code_directory=code_directory)
    assets = _PROFILE.inspect_local_assets(manifest_path, **arguments)
    result = {"schema": PRODUCTION_SCHEMA, "status": "unavailable", "profile_id": PROFILE_ID,
              "input_row_count": len(data), "receipt_count": 0, "receipts": [],
              "assets": assets, "model_inference_executed": False,
              "training_executed": False, "download_executed": False,
              "ir_decoder_executed": False, "proof_authority": False,
              "runtime_compatibility_verified": False, "maximum_context_numerics_verified": False,
              "execution_profile": {"batch_size": batch_size, "device": "cpu", "dtype": "float32",
                                    "attention_implementation": "eager", "padding_side": "right",
                                    "pooling": "cls", "normalization": "l2",
                                    "max_tokens_including_special_tokens": MAX_TOKENS,
                                    "max_total_tokens": MAX_TOTAL_TOKENS,
                                    "overlength_policy": "reject"},
              "runtime_versions": {}}
    if assets["status"] != "available":
        return result
    torch, tokenizer, model = _load_backend(assets)
    versions = {"python": sys.version.split()[0]}
    for dependency in ("torch", "transformers", "tokenizers", "safetensors"):
        try:
            versions[dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            versions[dependency] = "unavailable"
    _require(tokenizer.padding_side == "right", "reference tokenizer must pad on the right")
    token_rows = _tokenize(data, tokenizer, model.config.vocab_size)
    _require(_PROFILE.inspect_local_assets(manifest_path, **arguments) == assets,
             "assets changed while loading the model")
    vectors = _vectors(torch, model, tokenizer, token_rows, batch_size)
    _require(len(vectors) == len(data), "embedding coverage is incomplete")
    _require(_PROFILE.inspect_local_assets(manifest_path, **arguments) == assets,
             "assets changed during model inference")
    receipts = []
    for row, tokens, vector in zip(data, token_rows, vectors):
        receipts.append({"schema": RECEIPT_SCHEMA, "id": row["id"],
                         "source_sha256": row["source_sha256"], "profile_id": PROFILE_ID,
                         "dimension": DIMENSION, "embedding": vector,
                         "token_count_including_special_tokens": len(tokens["input_ids"]),
                         "token_input_sha256": _digest(tokens["input_ids"]),
                         "truncated": False, "normalized": True,
                         "asset_manifest_sha256": assets["manifest_sha256"]})
    result.update(status="completed", receipt_count=len(receipts), receipts=receipts,
                  model_inference_executed=True, runtime_compatibility_verified=True,
                  runtime_versions=versions)
    return result

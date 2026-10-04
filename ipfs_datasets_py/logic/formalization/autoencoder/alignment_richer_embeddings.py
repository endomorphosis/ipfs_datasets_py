"""Exact source-only, separately identified native embedding lanes.

Importing this module loads no encoder. Production calls run local CPU inference
with no training, model download, target input, IR compiler or prover. The two
explicit-context interpretations retain distinct input identities but forward
the same source text; their context is unapplied, not resolved. Integrity checks
are not external runtime attestation or independent semantic qualification.

The 8D lane is the frozen spaCy lexical/POS/dependency/modal-cue feature hash,
not a learned autoencoder latent. It forwards the exact source to the codec,
whose documented internal feature preprocessing collapses whitespace. The
384D and 768D lanes preserve the actual normalized float32 model outputs.
Use production functions in a dedicated worker: offline environment/socket
and CPU thread guards are reversible process-wide settings, not an OS sandbox.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import re
import stat
import struct
import tempfile
from pathlib import Path

INPUT_SCHEMA = "alignment-richer-embedding-inputs/v1"
SCHEMA = "alignment-richer-embedding-lane/v1"
INPUT_RECIPE = "exact_source_only"
IDENTITY_RECIPE = "sha256:authored_panel_input_sha256;context_not_forwarded"
MAX_ROWS = 128
MAX_SOURCE_BYTES = 65536
MAX_TOTAL_SOURCE_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
DIMENSIONS = {"legacy8": 8, "native384": 384, "native768": 768}
GTE384_PROFILE_ID = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
                     "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
SPACY_PROFILE_ID = "legacy-linguistic-features-8d/v1"
_OPTIMIZER = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
_AUTOENCODER = "ipfs_datasets_py.logic.formalization.autoencoder."
_HASH = re.compile(r"[0-9a-f]{64}")
_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FALSE_FIELDS = ("training_executed", "download_executed", "context_semantics_applied",
                 "source_fidelity_established", "proof_authority", "qualified")
_INPUT_KEYS = {"schema", "input_recipe", "identity_recipe", "rows", "row_count",
               "context_unapplied_rows", "all_context_unapplied", "qualified", "proof_authority",
               "payload_sha256"}
_ROW_KEYS = {"id", "input_sha256", "source_text", "source_sha256", "context_role", "context_applied"}
_LANE_KEYS = {"schema", "lane_id", "dimension", "status", "input_manifest_sha256", "input_recipe",
              "receipts", "backend_evidence", "issues", "encoder_execution_executed",
              "model_inference_executed", "payload_sha256", *_FALSE_FIELDS}
_RECEIPT_KEYS = {"id", "input_sha256", "source_sha256", "context_role", "context_applied", "status",
                 "embedding", "embedding_sha256", "token_count", "token_input_sha256",
                 "backend_input_id", "normalized_source_sha256"}
_BACKEND_KEYS = {"execution_kind", "profile_id", "implementation", "execution_profile", "runtime_versions",
                 "asset_evidence", "source_blob_binding", "production_evidence", "production_evidence_sha256"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value, *, ascii=False):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=ascii,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("strict finite UTF8 JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _source_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keys(value, expected, label):
    _require(type(value) is dict and set(value) == expected, label + " has unknown or missing fields")


def _hash(value, label):
    _require(type(value) is str and _HASH.fullmatch(value), label + " requires lowercase SHA256")


def _seal(value):
    value["payload_sha256"] = _digest({key: item for key, item in value.items() if key != "payload_sha256"})
    return value


def _integrity(value):
    _hash(value["payload_sha256"], "payload_sha256")
    _require(value["payload_sha256"] == _digest({key: item for key, item in value.items()
                                               if key != "payload_sha256"}), "payload SHA256 mismatch")


def prepare_richer_embedding_inputs(panel: dict) -> dict:
    """Strip targets, splits, authored IDs and assumptions before any encoder.

    The owner's full panel contract is validated first. Pseudonyms depend on its
    source/context input identity, never on its target, class label or split.
    An input hash is a retained panel binding; this closed source-only manifest
    cannot reconstruct a withheld context from that hash.
    """
    owner = importlib.import_module(_AUTOENCODER + "alignment_richer_panel")
    owner.validate_alignment_richer_panel(panel)
    rows = [{"id": "sha256:" + row["input_sha256"], "input_sha256": row["input_sha256"],
             "source_text": row["source_text"], "source_sha256": row["source_sha256"],
             "context_role": row["context"]["role"], "context_applied": False} for row in panel["rows"]]
    rows.sort(key=lambda row: row["id"])
    result = _seal({"schema": INPUT_SCHEMA, "input_recipe": INPUT_RECIPE,
                    "identity_recipe": IDENTITY_RECIPE, "rows": rows, "row_count": len(rows),
                    "context_unapplied_rows": sum(row["context_role"] == "explicit_assumptions" for row in rows),
                    "all_context_unapplied": True, "qualified": False, "proof_authority": False})
    validate_richer_embedding_inputs(result)
    return result


def validate_richer_embedding_inputs(inputs: dict) -> dict:
    """Validate exact text and retained identity bindings; no model or target load."""
    _keys(inputs, _INPUT_KEYS, "embedding inputs")
    _require(inputs["schema"] == INPUT_SCHEMA and inputs["input_recipe"] == INPUT_RECIPE
             and inputs["identity_recipe"] == IDENTITY_RECIPE, "input schema/recipe changed")
    _require(inputs["all_context_unapplied"] is True and inputs["qualified"] is False
             and inputs["proof_authority"] is False, "source inputs cannot claim context or authority")
    rows = inputs["rows"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "input row count exceeds bound")
    total, identities, contexts = 0, [], 0
    for row in rows:
        _keys(row, _ROW_KEYS, "input row")
        _hash(row["input_sha256"], "input_sha256")
        _hash(row["source_sha256"], "source_sha256")
        _require(row["id"] == "sha256:" + row["input_sha256"], "input pseudonym differs from input binding")
        text = row["source_text"]
        _require(type(text) is str and bool(text.strip()) and "\x00" not in text, "nonempty exact source required")
        try:
            encoded = text.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("source must be exact UTF8") from error
        total += len(encoded)
        _require(len(encoded) <= MAX_SOURCE_BYTES and total <= MAX_TOTAL_SOURCE_BYTES,
                 "source UTF8 byte bound exceeded")
        _require(_source_sha(text) == row["source_sha256"], "exact source SHA256 mismatch")
        _require(type(row["context_role"]) is str and row["context_role"] in
                 {"none_required", "explicit_assumptions"} and row["context_applied"] is False,
                 "context must remain declared and unapplied")
        contexts += row["context_role"] == "explicit_assumptions"
        identities.append(row["id"])
    _require(identities == sorted(set(identities)), "input identities must be unique and sorted")
    _require(type(inputs["row_count"]) is int and inputs["row_count"] == len(rows)
             and type(inputs["context_unapplied_rows"]) is int and inputs["context_unapplied_rows"] == contexts,
             "input counts mismatch")
    _require(len(_raw(inputs)) <= MAX_RESULT_BYTES, "input JSON byte bound exceeded")
    _integrity(inputs)
    return {"status": "validated", "input_manifest_sha256": inputs["payload_sha256"], "rows": len(rows),
            "exact_source_bytes": total, "context_unapplied_rows": contexts,
            "context_identity_independently_recomputed": False, "qualified": False, "proof_authority": False}


def _receipt(row, embedding, *, token_count, token_input_sha256=None,
             backend_input_id=None, normalized_source_sha256=None, status="embedded"):
    return {"id": row["id"], "input_sha256": row["input_sha256"], "source_sha256": row["source_sha256"],
            "context_role": row["context_role"], "context_applied": False, "status": status,
            "embedding": embedding, "embedding_sha256": _digest(embedding) if embedding is not None else None,
            "token_count": token_count, "token_input_sha256": token_input_sha256,
            "backend_input_id": backend_input_id or row["id"],
            "normalized_source_sha256": normalized_source_sha256}


def _backend(profile_id, *, execution_kind="observed_native", implementation=None,
             execution_profile=None, runtime_versions=None, asset_evidence=None,
             source_blob_binding=None, production_evidence=None):
    return {"execution_kind": execution_kind, "profile_id": profile_id, "implementation": implementation or {},
            "execution_profile": execution_profile or {}, "runtime_versions": runtime_versions or {},
            "asset_evidence": asset_evidence, "source_blob_binding": source_blob_binding,
            "production_evidence": production_evidence,
            "production_evidence_sha256": _digest(production_evidence) if production_evidence is not None else None}


def _lane(inputs, lane_id, receipts, backend_evidence, *, status="produced", issues=None,
          model_inference_executed=True, encoder_execution_executed=True):
    result = _seal({"schema": SCHEMA, "lane_id": lane_id, "dimension": DIMENSIONS[lane_id], "status": status,
                    "input_manifest_sha256": inputs["payload_sha256"], "input_recipe": INPUT_RECIPE,
                    "receipts": receipts, "backend_evidence": backend_evidence, "issues": issues or [],
                    "model_inference_executed": model_inference_executed,
                    "encoder_execution_executed": encoder_execution_executed,
                    **dict.fromkeys(_FALSE_FIELDS, False)})
    validate_embedding_lane(result, inputs)
    return result


def _unavailable(inputs, lane_id, profile_id, reason):
    return _lane(inputs, lane_id, [], _backend(profile_id, execution_kind="not_executed"),
                 status="unavailable", issues=[reason], model_inference_executed=False,
                 encoder_execution_executed=False)


def _vector(vector, dimension):
    _require(type(vector) is list and len(vector) == dimension, "embedding dimension mismatch")
    _require(all(type(item) is float and math.isfinite(item) for item in vector), "finite float embeddings required")
    _require(abs(math.hypot(*vector) - 1.0) <= 1e-5, "embedding must be a nonzero L2 unit vector")
    if dimension != 8:
        try:
            _require(all(struct.unpack(">f", struct.pack(">f", item))[0] == item for item in vector),
                     "native output must preserve exact float32 values")
        except (OverflowError, struct.error) as error:
            raise ValueError("native output exceeds float32") from error


def _source_blob(inputs):
    raw = b"".join(row["source_text"].encode("utf-8") for row in inputs["rows"])
    return raw, {"recipe": "input_rows_ordered_utf8_concatenation_no_separator/v1",
                 "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "row_count": len(inputs["rows"]),
                 "normalization": "identity"}


def _native384_inputs(inputs):
    codec = importlib.import_module(_OPTIMIZER + "autoencoder_embedding_production")
    corpus = importlib.import_module(_OPTIMIZER + "autoencoder_corpus_manifest")
    raw, blob = _source_blob(inputs)
    artifact = corpus.SourceArtifact(blob["sha256"], blob["bytes"])
    offset, selected = 0, []
    for row in inputs["rows"]:
        end = offset + len(row["source_text"].encode("utf-8"))
        source = corpus.SourceSpan(artifact, "diagnostic", "alignment-richer-exact-source/v1", row["id"], "en",
                                   row["id"], offset, end, "identity")
        selected.append(codec.EmbeddingInput(source, "authored richer source diagnostic", row["id"],
                                              row["source_text"], row["id"]))
        offset = end
    return selected, raw, blob


def _validate_native384(backend, receipts, inputs):
    codec = importlib.import_module(_OPTIMIZER + "autoencoder_embedding_production")
    production = codec.EmbeddingProductionReceipt(_raw(backend["production_evidence"], ascii=True))
    data = production.to_dict()
    _require(data["execution"]["kind"] == "native", "injected384 receipt cannot assert native execution")
    _require(backend["profile_id"] == GTE384_PROFILE_ID, "native384 profile changed")
    selected, _, blob = _native384_inputs(inputs)
    _require(_raw(backend["source_blob_binding"]) == _raw(blob), "native source blob binding mismatch")
    _require(_raw(data["inputs"]) == _raw([item.to_dict() for item in selected]), "native source spans differ")
    _require(_raw(backend["asset_evidence"]) == _raw(data["model_assets"])
             and _raw(backend["execution_profile"]) == _raw(data["execution"])
             and _raw(backend["runtime_versions"]) == _raw(data["producer"]["runtime_versions"]),
             "native384 backend evidence differs")
    runtime = importlib.import_module(_OPTIMIZER + "autoencoder_embedding_runtime")
    pinned_assets = [{"name": name, "bytes": size, "sha256": digest}
                     for name, (size, digest) in sorted(runtime._PINNED_ASSETS.items())]
    _require(_raw(data["model_assets"]) == _raw(pinned_assets), "native384 asset pins differ")
    for receipt, output in zip(receipts, data["results"], strict=True):
        _require(receipt["backend_input_id"] == output["input_id"] and receipt["normalized_source_sha256"] is None,
                 "native384 backend input binding mismatch")
        if output["status"] == "embedded":
            vector = list(codec._decode_vector(output["vector"]))
            _require(receipt["status"] == "embedded" and _raw(receipt["embedding"]) == _raw(vector)
                     and receipt["token_count"] == len(output["tokens"]["input_ids"])
                     and receipt["token_input_sha256"] == _digest(output["tokens"]),
                     "native384 actual output/token evidence mismatch")
        else:
            _require(output["status"] == receipt["status"] == "token_limit_exceeded"
                     and receipt["token_count"] == output["tokens"]["token_count"]
                     and receipt["token_input_sha256"] == output["tokens"]["sha256"],
                     "native384 overlength disposition mismatch")


def _validate_native768(backend, receipts, inputs):
    complete = importlib.import_module(_AUTOENCODER + "source_embeddings_768_complete")
    data, reference = backend["production_evidence"], complete.reference
    _require(type(data) is dict and data.get("schema") == complete.SCHEMA and data.get("status") == "completed"
             and data.get("profile_id") == backend["profile_id"] == complete.PROFILE_ID,
             "complete768 native production required")
    _require(data.get("model_inference_executed") is True and data.get("runtime_compatibility_verified") is True
             and all(data.get(field) is False for field in ("training_executed", "download_executed",
                 "ir_decoder_executed", "source_semantics_verified", "proof_authority", "maximum_context_numerics_verified")),
             "complete768 execution scope changed")
    loading = data.get("complete_checkpoint_loading")
    _require(type(loading) is dict and loading.get("architecture") == "NewForTokenClassification"
             and loading.get("classifier_loaded") is True and loading.get("classifier_logits_used_for_dense_embedding") is False,
             "complete768 checkpoint architecture differs")
    names = loading.get("tensor_names")
    _require(type(names) is list and all(type(name) is str for name in names)
             and names == sorted(set(names)) and type(loading.get("tensor_count")) is int
             and loading["tensor_count"] == len(names), "complete768 tensor evidence differs")
    complete._admit_loading(loading, names, names)
    dense = data.get("dense_path_verification")
    _require(type(dense) is dict and dense.get("encoder_and_complete_hidden_states_bitwise_equal") is True
             and dense.get("evaluation_mode") is True, "complete768 encoder hidden-state check absent")
    native = data.get("receipts")
    _require(type(native) is list and len(native) == len(receipts) and type(data.get("receipt_count")) is int
             and data["receipt_count"] == len(native) and type(data.get("input_row_count")) is int
             and data["input_row_count"] == len(inputs["rows"]), "complete768 source coverage differs")
    assets = data.get("assets")
    _require(type(assets) is dict and assets.get("status") == "available" and assets.get("profile_id") == complete.PROFILE_ID
             and assets.get("model_revision") == reference._PROFILE.MODEL_REV
             and assets.get("code_revision") == reference._PROFILE.CODE_REV, "complete768 asset provenance differs")
    manifest = {"schema": reference._PROFILE.MANIFEST_SCHEMA,
                "model_revision": assets["model_revision"], "code_revision": assets["code_revision"],
                "files": assets.get("files")}
    entries = reference._PROFILE._manifest_entries(manifest)
    _require(set(entries) == set(reference._PROFILE.PUBLISHED_ASSETS), "complete768 asset closure incomplete")
    _hash(assets.get("manifest_sha256"), "asset manifest SHA256")
    _require(assets.get("unavailable_reasons") == [] and assets.get("proof_authority") is False
             and assets.get("model_numerics_verified") is False, "complete768 asset scope changed")
    _require(_raw(backend["asset_evidence"]) == _raw(assets) and backend["source_blob_binding"] is None
             and _raw(backend["execution_profile"]) == _raw(data["execution_profile"])
             and _raw(backend["runtime_versions"]) == _raw(data["runtime_versions"]), "complete768 backend evidence differs")
    execution = data["execution_profile"]
    for key, value in {"device": "cpu", "dtype": "float32", "attention_implementation": "eager", "padding_side": "right",
                       "pooling": "cls", "normalization": "l2", "max_tokens_including_special_tokens": 8192,
                       "overlength_policy": "reject"}.items():
        _require(type(execution.get(key)) is type(value) and execution[key] == value, "complete768 execution profile differs")
    for receipt, output in zip(receipts, native, strict=True):
        _require(output.get("schema") == reference.RECEIPT_SCHEMA and output.get("id") == receipt["id"]
                 and output.get("source_sha256") == receipt["source_sha256"] and output.get("profile_id") == complete.PROFILE_ID
                 and type(output.get("dimension")) is int and output["dimension"] == 768
                 and output.get("truncated") is False and output.get("normalized") is True
                 and output.get("asset_manifest_sha256") == assets.get("manifest_sha256")
                 and _raw(output.get("embedding")) == _raw(receipt["embedding"])
                 and output.get("token_count_including_special_tokens") == receipt["token_count"]
                 and output.get("token_input_sha256") == receipt["token_input_sha256"]
                 and receipt["backend_input_id"] == receipt["id"] and receipt["normalized_source_sha256"] is None,
                 "complete768 source/output evidence mismatch")
    _require(dense.get("probe_tokens") == receipts[0]["token_count"], "complete768 hidden-state check source differs")


def _validate_spacy(backend, receipts, inputs):
    _require(backend["profile_id"] == SPACY_PROFILE_ID, "8D profile changed")
    data = backend["production_evidence"]
    _require(type(data) is dict and set(data) == {"codec_snapshot", "numerical_snapshot", "model_identity", "receipts"},
             "8D production evidence fields changed")
    identity = data["model_identity"]
    _require(type(identity) is dict and identity.get("backend") in {"local_en_core_web_sm", "historical_blank_en"}
             and identity.get("used_fallback_model") is (identity["backend"] == "historical_blank_en"),
             "8D backend/fallback evidence changed")
    _require(data["codec_snapshot"].get("vendored_sha256") ==
             "16ec4e141d5cb2f9d37cd4db42733921bc046e17fee12afc43ab31ca7a60cd59",
             "8D frozen codec changed")
    _require(type(data["receipts"]) is list and len(data["receipts"]) == len(receipts)
             and backend["source_blob_binding"] is None, "8D production coverage differs")
    _require(backend["execution_profile"].get("ir_compiler_executed") is False
             and backend["execution_profile"].get("autoencoder_executed") is False,
             "8D source features cannot claim IR/autoencoder execution")
    for row, receipt, evidence in zip(inputs["rows"], receipts, data["receipts"], strict=True):
        expected = {"id": row["id"], "token_count": receipt["token_count"],
                    "normalized_source_sha256": _source_sha(re.sub(r"\s+", " ", row["source_text"]).strip())}
        _require(_raw(evidence) == _raw(expected) and receipt["normalized_source_sha256"] == expected["normalized_source_sha256"]
                 and receipt["backend_input_id"] == row["id"] and receipt["token_input_sha256"] is None,
                 "8D normalized feature input evidence differs")


def validate_embedding_lane(result: dict, inputs: dict) -> dict:
    """Check bounded evidence and exact input/output linkage, without inference.

    Fixture records are diagnostic and cannot acquire encoder-execution flags.
    Native labels describe receipts from the local producer; neither those
    labels nor this validator cryptographically attest the computation.
    """
    validate_richer_embedding_inputs(inputs)
    _keys(result, _LANE_KEYS, "embedding lane")
    _require(result["schema"] == SCHEMA and type(result["lane_id"]) is str and result["lane_id"] in DIMENSIONS,
             "embedding lane schema/id changed")
    lane_id, dimension = result["lane_id"], result["dimension"]
    _require(type(dimension) is int and dimension == DIMENSIONS[lane_id], "lane dimension changed")
    _require(result["input_manifest_sha256"] == inputs["payload_sha256"] and result["input_recipe"] == INPUT_RECIPE,
             "lane source manifest/recipe binding differs")
    _require(all(result[field] is False for field in _FALSE_FIELDS), "lane cannot acquire context/semantic/proof authority")
    _require(type(result["issues"]) is list and len(result["issues"]) <= 32
             and all(type(item) is str and 0 < len(item) <= 1024 for item in result["issues"]), "bounded issues required")
    _require(type(result["model_inference_executed"]) is bool and type(result["encoder_execution_executed"]) is bool,
             "execution flags must be booleans")
    backend = result["backend_evidence"]
    _keys(backend, _BACKEND_KEYS, "backend evidence")
    _require(type(backend["profile_id"]) is str and 0 < len(backend["profile_id"]) <= 1024, "backend profile required")
    for key in ("implementation", "execution_profile", "runtime_versions"):
        _require(type(backend[key]) is dict, "backend evidence mappings required")
    for name, digest in backend["implementation"].items():
        _require(type(name) is str and 0 < len(name) <= 512, "implementation binding name required")
        _hash(digest, "implementation SHA256")
    production = backend["production_evidence"]
    _require(backend["production_evidence_sha256"] == (_digest(production) if production is not None else None),
             "production evidence SHA256 differs")
    receipts = result["receipts"]
    _require(type(receipts) is list, "receipts must be a list")
    status, kind = result["status"], backend["execution_kind"]
    _require(type(status) is str and status in {"produced", "partial", "unavailable", "diagnostic_fixture"},
             "unknown production status")
    if status == "unavailable":
        _require(not receipts and bool(result["issues"]) and kind == "not_executed" and production is None
                 and result["model_inference_executed"] is False and result["encoder_execution_executed"] is False,
                 "unavailable lane cannot assert execution")
    else:
        _require(len(receipts) == len(inputs["rows"]), "lane receipts must cover all source inputs")
        for row, receipt in zip(inputs["rows"], receipts, strict=True):
            _keys(receipt, _RECEIPT_KEYS, "embedding receipt")
            for field in ("id", "input_sha256", "source_sha256", "context_role"):
                _require(receipt[field] == row[field], "receipt input binding mismatch")
            _require(receipt["context_applied"] is False, "receipt cannot resolve context")
            _require(type(receipt["backend_input_id"]) is str and 0 < len(receipt["backend_input_id"]) <= 256,
                     "backend input identity required")
            _require(type(receipt["token_count"]) is int and 1 <= receipt["token_count"] <= 1048576,
                     "bounded actual token count required")
            if receipt["token_input_sha256"] is not None:
                _hash(receipt["token_input_sha256"], "token_input_sha256")
            if receipt["normalized_source_sha256"] is not None:
                _hash(receipt["normalized_source_sha256"], "normalized_source_sha256")
            if receipt["status"] == "embedded":
                _vector(receipt["embedding"], dimension)
                _require(receipt["embedding_sha256"] == _digest(receipt["embedding"]), "embedding SHA256 mismatch")
            else:
                _require(lane_id == "native384" and receipt["status"] == "token_limit_exceeded"
                         and receipt["token_count"] > 512 and receipt["embedding"] is None
                         and receipt["embedding_sha256"] is None, "unsupported empty-vector disposition")
        complete = all(receipt["status"] == "embedded" for receipt in receipts)
        _require(status == "diagnostic_fixture" or (status == "produced") == complete, "production status differs from receipts")
        if status == "diagnostic_fixture":
            _require(kind == "injected_fixture" and result["model_inference_executed"] is False
                     and result["encoder_execution_executed"] is False, "fixtures cannot claim native execution")
        else:
            _require(kind == "observed_native" and result["encoder_execution_executed"] is True
                     and production is not None, "actual native production evidence required")
            if lane_id == "legacy8":
                _validate_spacy(backend, receipts, inputs)
                _require(result["model_inference_executed"] is
                         (production["model_identity"]["backend"] == "local_en_core_web_sm"), "8D model execution flag differs")
            else:
                _require(result["model_inference_executed"] is any(row["status"] == "embedded" for row in receipts),
                         "native neural inference flag differs from actual forward coverage")
                (_validate_native384 if lane_id == "native384" else _validate_native768)(backend, receipts, inputs)
    _require(len(_raw(result)) <= MAX_RESULT_BYTES, "lane JSON byte bound exceeded")
    _integrity(result)
    return {"status": "validated", "lane_id": lane_id, "dimension": dimension, "receipt_count": len(receipts),
            "embedded_count": sum(row["status"] == "embedded" for row in receipts),
            "production_status": status, "runtime_cryptographically_attested": False,
            "source_fidelity_established": False, "qualified": False, "proof_authority": False}


def _implementation(*modules):
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _LOADED_SHA256,
             "embedding wrapper source changed after import")
    result = {"richer_embedding_wrapper": _LOADED_SHA256}
    for module in modules:
        result[module.__name__] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return result


def _package_assets(package_directory):
    """Hash this explicit small installed spaCy package, with bounded enumeration."""
    root = Path(package_directory)
    _require(root.is_dir() and not root.is_symlink(), "spaCy package must be a regular local directory")
    files, total, scanned = [], 0, 0
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name != "__pycache__")
        for name in directories:
            _require(not (Path(directory) / name).is_symlink(), "spaCy model directory symlink forbidden")
        for name in sorted(names):
            scanned += 1
            _require(scanned <= 512, "spaCy package entry bound exceeded")
            if name.endswith(".pyc"):
                continue
            path = Path(directory) / name
            before = path.lstat()
            _require(stat.S_ISREG(before.st_mode) and before.st_size <= 16 * 1024 * 1024,
                     "spaCy package file must be bounded and regular")
            total += before.st_size
            _require(total <= 64 * 1024 * 1024, "spaCy package byte bound exceeded")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            after = path.lstat()
            _require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                     (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "spaCy package file changed")
            files.append({"name": path.relative_to(root).as_posix(), "bytes": before.st_size, "sha256": digest.hexdigest()})
    files.sort(key=lambda item: item["name"])
    return {"package_directory": str(root.resolve()), "files": files, "bytes": total,
            "files_manifest_sha256": _digest(files)}


def run_spacy8(inputs: dict, *, backend="local_en_core_web_sm") -> dict:
    """Run the verified source feature codec; never construct an autoencoder."""
    validate_richer_embedding_inputs(inputs)
    _require(type(backend) is str and backend in {"local_en_core_web_sm", "historical_blank_en"}, "unknown spaCy backend")
    try:
        snapshot = importlib.import_module(_OPTIMIZER + "autoencoder_lineages.legacy_v1._linguistic_snapshot")
        contract = importlib.import_module(_OPTIMIZER + "autoencoder_lineages._contract")
        codec = importlib.import_module(snapshot.__name__ + ".spacy_modal_codec")
        import spacy
        from thinc.api import use_ops
    except ImportError as error:
        return _unavailable(inputs, "legacy8", SPACY_PROFILE_ID, "spaCy dependency unavailable: " + str(error)[:256])
    codec_manifest = snapshot.verify_snapshot()
    numerical_directory = Path(snapshot.__file__).parent.parent / "_snapshot"
    numerical_manifest = contract.verify_snapshot(numerical_directory)
    implementation = _implementation(snapshot, contract, codec)
    with importlib.import_module(_OPTIMIZER + "autoencoder_embedding_runtime")._offline_guard(), use_ops("numpy"):
        assets = None
        if backend == "historical_blank_en":
            class BlankEncoder(codec.SpaCyLegalEncoder):
                def _load_nlp(self, model_name):
                    nlp = spacy.blank("en")
                    nlp.add_pipe("sentencizer")
                    return nlp, True
            encoder = BlankEncoder(model_name="explicit_historical_blank_en")
        else:
            try:
                package = spacy.util.get_package_path("en_core_web_sm")
                assets = _package_assets(package)
                encoder = codec.SpaCyLegalEncoder(model_name="en_core_web_sm")
            except OSError as error:
                return _unavailable(inputs, "legacy8", SPACY_PROFILE_ID, "installed spaCy model unavailable: " + str(error)[:256])
            _require(encoder.used_fallback_model is False, "local spaCy model fallback forbidden")
        identity = {"backend": backend, "model_name": encoder.model_name, "used_fallback_model": encoder.used_fallback_model,
                    "spacy_version": spacy.__version__, "package": "en_core_web_sm" if assets else None,
                    "model_version": importlib.metadata.version("en-core-web-sm") if assets else None,
                    "model_files_manifest_sha256": assets["files_manifest_sha256"] if assets else None,
                    "pipeline": list(encoder.nlp.pipe_names),
                    "pipeline_config_sha256": _source_sha(encoder.nlp.config.to_str())}
        decoder, receipts, evidence = codec.SpaCyModalDecoder(), [], []
        for row in inputs["rows"]:
            encoding = encoder.encode(row["source_text"], document_id=row["id"], citation=None, source="legal_text")
            _require(encoding.text == row["source_text"], "spaCy encoding changed exact original source")
            normalized = _source_sha(encoding.normalized_text)
            receipts.append(_receipt(row, decoder.decode_embedding(encoding, dimensions=8), token_count=len(encoding.tokens),
                                     normalized_source_sha256=normalized))
            evidence.append({"id": row["id"], "token_count": len(encoding.tokens), "normalized_source_sha256": normalized})
        _require(snapshot.verify_snapshot() == codec_manifest and contract.verify_snapshot(numerical_directory) == numerical_manifest
                 and _implementation(snapshot, contract, codec) == implementation, "spaCy implementation changed during encoding")
        if assets:
            _require(_package_assets(package) == assets, "spaCy model package changed during encoding")
        production = {"codec_snapshot": codec_manifest, "numerical_snapshot": numerical_manifest,
                      "model_identity": identity, "receipts": evidence}
        execution = {"backend": backend, "device": "cpu", "pooling": "feature_hash", "normalization": "l2_then_round6",
                     "feature_hash": "sha256:first4be_mod8:signed_0.5_plus_byte5_over255",
                     "feature_preprocessing": "collapse_whitespace", "source_forwarding": "exact_utf8",
                     "ir_compiler_executed": False, "autoencoder_executed": False}
        return _lane(inputs, "legacy8", receipts, _backend(SPACY_PROFILE_ID, implementation=implementation,
                     execution_profile=execution, runtime_versions={"python": importlib.import_module("platform").python_version(),
                     "spacy": spacy.__version__}, asset_evidence=assets, production_evidence=production),
                     model_inference_executed=backend == "local_en_core_web_sm")


def run_gte384(inputs: dict, snapshot_path=None, *, batch_size=16) -> dict:
    """Run the existing pinned source-byte-verified CPU producer, retaining it."""
    validate_richer_embedding_inputs(inputs)
    _require(type(batch_size) is int and 1 <= batch_size <= 16, "batch_size must be1..16")
    runtime = importlib.import_module(_OPTIMIZER + "autoencoder_embedding_runtime")
    codec = importlib.import_module(_OPTIMIZER + "autoencoder_embedding_production")
    path = Path(runtime.DEFAULT_SNAPSHOT_PATH if snapshot_path is None else snapshot_path).expanduser()
    _require(path.is_absolute(), "native384 snapshot must be an absolute path")
    if not path.is_dir():
        return _unavailable(inputs, "native384", GTE384_PROFILE_ID, "pinned native384 local snapshot unavailable")
    selected, raw, blob = _native384_inputs(inputs)
    implementation = _implementation(runtime, codec)
    try:
        with tempfile.TemporaryDirectory(prefix="richer-exact-source-") as directory:
            source_path = Path(directory) / "source.utf8"
            source_path.write_bytes(raw)
            def resolver(reference):
                _require(reference == {"sha256": blob["sha256"], "bytes": blob["bytes"]}, "unknown native source artifact")
                return source_path
            production = runtime.produce_native_embedding_receipt(selected, resolver=resolver, snapshot_path=path,
                                                                    batch_size=batch_size).to_dict()
    except ImportError as error:
        return _unavailable(inputs, "native384", GTE384_PROFILE_ID, "native384 dependency unavailable: " + str(error)[:256])
    _require(_implementation(runtime, codec) == implementation, "native384 wrapper implementation changed")
    receipts = []
    for row, output in zip(inputs["rows"], production["results"], strict=True):
        embedded = output["status"] == "embedded"
        receipts.append(_receipt(row, list(codec._decode_vector(output["vector"])) if embedded else None,
                                 token_count=len(output["tokens"]["input_ids"]) if embedded else output["tokens"]["token_count"],
                                 token_input_sha256=_digest(output["tokens"]) if embedded else output["tokens"]["sha256"],
                                 backend_input_id=output["input_id"], status=output["status"]))
    return _lane(inputs, "native384", receipts, _backend(GTE384_PROFILE_ID, implementation=implementation,
                 execution_profile=production["execution"], runtime_versions=production["producer"]["runtime_versions"],
                 asset_evidence=production["model_assets"], source_blob_binding=blob, production_evidence=production),
                 status="produced" if all(row["status"] == "embedded" for row in receipts) else "partial",
                 model_inference_executed=any(row["status"] == "embedded" for row in receipts))


def run_gte768(inputs: dict, *, manifest_path, expected_manifest_sha256, model_directory,
               code_directory, batch_size=1) -> dict:
    """Use the strict complete-checkpoint producer, not the earlier bare loader."""
    validate_richer_embedding_inputs(inputs)
    _require(type(batch_size) is int and 1 <= batch_size <= 16, "batch_size must be1..16")
    complete = importlib.import_module(_AUTOENCODER + "source_embeddings_768_complete")
    guard = importlib.import_module(_OPTIMIZER + "autoencoder_embedding_runtime")
    implementation = _implementation(complete, complete.reference, complete.reference._PROFILE, guard)
    arguments = {"manifest_path": manifest_path, "expected_manifest_sha256": expected_manifest_sha256,
                 "model_directory": model_directory, "code_directory": code_directory, "batch_size": batch_size}
    rows = [{"id": row["id"], "source_text": row["source_text"]} for row in inputs["rows"]]
    # Admit missing roots without importing tensors; corrupted existing assets fail.
    profile = complete.reference._PROFILE
    if any(not Path(path).exists() for path in (manifest_path, model_directory, code_directory)):
        assets = profile.inspect_local_assets(manifest_path, expected_sha256=expected_manifest_sha256,
                                              model_directory=model_directory, code_directory=code_directory)
        _require(assets["status"] == "unavailable", "asset status changed during missing-root admission")
        return _unavailable(inputs, "native768", complete.PROFILE_ID, "complete native768 local assets unavailable")
    try:
        with guard._offline_guard():
            import torch
            old_threads = torch.get_num_threads()
            try:
                torch.set_num_threads(1)
                with torch.random.fork_rng(devices=[]):
                    production = complete.embed_rows(rows, **arguments)
            finally:
                torch.set_num_threads(old_threads)
    except ImportError as error:
        return _unavailable(inputs, "native768", complete.PROFILE_ID, "native768 dependency unavailable: " + str(error)[:256])
    _require(_implementation(complete, complete.reference, complete.reference._PROFILE, guard) == implementation,
             "native768 wrapper implementation changed")
    receipts = [_receipt(row, output["embedding"], token_count=output["token_count_including_special_tokens"],
                         token_input_sha256=output["token_input_sha256"])
                for row, output in zip(inputs["rows"], production["receipts"], strict=True)]
    return _lane(inputs, "native768", receipts, _backend(complete.PROFILE_ID, implementation=implementation,
                 execution_profile=production["execution_profile"], runtime_versions=production["runtime_versions"],
                 asset_evidence=production["assets"], production_evidence=production))

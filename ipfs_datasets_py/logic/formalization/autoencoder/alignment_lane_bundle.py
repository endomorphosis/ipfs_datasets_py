"""Validate externally pinned representation declarations without inference.

Producer rows are bound declarations, not runtime attestation. This boundary
never fits, reconstructs, pads, truncates, normalizes or executes an encoder.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct

SCHEMA = "alignment-lane-bundle/v1"
PROFILE_SCHEMA = "alignment-representation-profile/v1"
PRODUCER_SCHEMA = "alignment-producer-row-bindings/v1"
VALIDATION_SCHEMA = "alignment-lane-bundle-validation/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 128
MAX_DIMENSION = 8192
MAX_JSON_NODES = 1200000
MAX_JSON_DEPTH = 20
RECIPES = {"exact_source_only/v1", "role_marked_source_frame/v1", "role_marked_declared_context/v1"}
STAGES = {"historical_linguistic_features", "raw_embedding", "learned_latent", "learned_projection",
          "reconstruction", "decoder_condition", "final_hidden_embedding"}
DERIVED = {"learned_latent", "learned_projection", "reconstruction", "decoder_condition"}
ROW_BINDING_FIELDS = {"id", "input_sha256", "encoder_text_sha256", "status", "reason", "vector_sha256",
                      "upstream_vector_sha256", "token_receipt_sha256"}
ROW_FIELDS = ROW_BINDING_FIELDS | {"input", "encoder_text", "vector", "producer_row_sha256"}
MASKS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision", "proof_supervision", "fidelity_evaluation")
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "source_semantics_verified",
                      "proof_authority", "runtime_computation_proven", "producer_identity_authenticated",
                      "file_bindings_verified", "semantic_label_admission", "training_executed", "model_executed",
                      "target_access", "sample_memory_used", "target_aware_reconstruction_used"), False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _raw(value):
    remaining = MAX_JSON_NODES

    def visit(node, depth):
        nonlocal remaining
        remaining -= 1
        _require(remaining >= 0 and depth <= MAX_JSON_DEPTH, "lane JSON node/depth bound exceeded")
        if type(node) is dict:
            _require(all(type(key) is str for key in node), "plain string JSON keys required")
            for key, child in node.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(node) is list:
            for child in node:
                visit(child, depth + 1)
        elif type(node) is float:
            _require(math.isfinite(node), "finite JSON scalars required")
        else:
            _require(node is None or type(node) in (str, bool, int), "ordinary JSON values required")

    visit(value, 0)
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("bounded finite UTF8 JSON required") from error
    _require(len(data) <= MAX_BYTES, "lane payload exceeds byte bound")
    return data


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha(value, label, *, nullable=False):
    if nullable and value is None:
        return
    _require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
             label + " must be lowercase SHA256")


def _text(value, label, *, maximum=65536, empty=False):
    _require(type(value) is str and "\x00" not in value and len(value) <= maximum
             and (bool(value.strip()) or empty and value == ""), "bounded " + label + " required")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF8 " + label + " required") from error


def _seal_check(value, label):
    _sha(value["content_sha256"], label + " seal")
    _require(value["content_sha256"] == _digest({k: v for k, v in value.items() if k != "content_sha256"}),
             label + " content seal differs")


def _profile(profile):
    _closed(profile, {"schema", "lane_id", "stage", "dimension", "producer", "pooling", "normalization",
                      "precision", "fit_input_recipe", "inference_input_recipe", "content_sha256"}, "lane profile")
    _require(profile["schema"] == PROFILE_SCHEMA, "lane profile schema differs")
    _require(type(profile["lane_id"]) is str and profile["lane_id"] in {"legacy8", "native384", "native768", "leanstral"},
             "known lane identity required")
    _require(type(profile["stage"]) is str and profile["stage"] in STAGES, "known representation stage required")
    _require(type(profile["dimension"]) is int and 1 <= profile["dimension"] <= MAX_DIMENSION,
             "bounded actual output width required")
    _require(type(profile["precision"]) is str and profile["precision"] in {"float32", "float64", "decimal6"},
             "known declared precision required")
    _require(type(profile["fit_input_recipe"]) is str and profile["fit_input_recipe"] in RECIPES
             and profile["fit_input_recipe"] == profile["inference_input_recipe"],
             "fit and inference require the same known input recipe")
    producer = profile["producer"]
    _closed(producer, {"profile_id", "model_id", "model_revision", "code_sha256", "model_assets_sha256",
                       "checkpoint_sha256"}, "producer identity")
    for name in ("profile_id", "model_id", "model_revision"):
        _text(producer[name], "producer " + name, maximum=4096)
    for name in ("code_sha256", "model_assets_sha256"):
        _sha(producer[name], "producer " + name)
    _sha(producer["checkpoint_sha256"], "checkpoint", nullable=True)
    pooling = profile["pooling"]
    _closed(pooling, {"method", "endpoint"}, "pooling identity")
    _require(type(pooling["method"]) is str and pooling["method"] in {"none", "mean", "cls", "last_token", "tensor_endpoint"},
             "known pooling method required")
    _text(pooling["endpoint"], "representation endpoint", maximum=512)
    norm = profile["normalization"]
    _closed(norm, {"kind", "unit_tolerance"}, "normalization identity")
    _require(type(norm["kind"]) is str and norm["kind"] in {"none", "l2"}, "known normalization required")
    if norm["kind"] == "l2":
        _require(type(norm["unit_tolerance"]) is float and math.isfinite(norm["unit_tolerance"])
                 and 0 < norm["unit_tolerance"] <= 0.01, "bounded declared L2 tolerance required")
    else:
        _require(norm["unit_tolerance"] is None, "unmodified non-unit producers have no L2 tolerance")
    lane, stage = profile["lane_id"], profile["stage"]
    if stage == "historical_linguistic_features":
        _require(lane == "legacy8" and profile["dimension"] == 8 and profile["precision"] == "decimal6"
                 and pooling["method"] == "none" and producer["checkpoint_sha256"] is None,
                 "historical8 features cannot impersonate a learned endpoint")
    elif stage == "raw_embedding":
        _require(lane in {"native384", "native768"}
                 and profile["dimension"] == {"native384": 384, "native768": 768}[lane]
                 and profile["precision"] == "float32" and norm["kind"] == "l2"
                 and pooling["method"] == {"native384": "mean", "native768": "cls"}[lane]
                 and producer["checkpoint_sha256"] is None, "raw native lane profile differs")
    elif stage in DERIVED:
        _require(lane != "leanstral" and producer["checkpoint_sha256"] is not None
                 and pooling["method"] == "tensor_endpoint", "derived view requires its own checkpoint and endpoint")
    else:
        _require(lane == "leanstral" and pooling["method"] in {"last_token", "mean"}
                 and producer["checkpoint_sha256"] is not None,
                 "final hidden view requires a separately bound Leanstral pooling/checkpoint declaration")
    _seal_check(profile, "profile")


def _input(request):
    _closed(request, {"source_text", "context"}, "source and context")
    _text(request["source_text"], "exact source text")
    context = request["context"]
    _closed(context, {"role", "text", "bindings", "sha256"}, "declared context")
    _require(type(context["role"]) is str and context["role"] in {
        "none_required", "explicit_assumptions", "declared_context", "required_unavailable"}, "known context role required")
    _text(context["text"], "context text", empty=True)
    _sha(context["sha256"], "context text digest")
    _require(context["sha256"] == hashlib.sha256(context["text"].encode("utf-8")).hexdigest(), "context digest differs")
    _require(type(context["bindings"]) is dict and len(context["bindings"]) <= 16, "bounded context bindings required")
    for name, binding in context["bindings"].items():
        _text(name, "context binding name", maximum=256)
        _closed(binding, {"kind", "value"}, "opaque context binding")
        _text(binding["kind"], "binding kind", maximum=256)
        _text(binding["value"], "binding value", maximum=4096)
    if context["role"] in {"none_required", "required_unavailable"}:
        _require(context["text"] == "" and context["bindings"] == {}, "empty context required for this role")
    else:
        _require(bool(context["text"].strip()), "declared context requires text")


def _encoder_text(request, recipe):
    if recipe == "exact_source_only/v1":
        return request["source_text"]
    forward = recipe == "role_marked_declared_context/v1"
    return _raw({"schema": "role-marked-source-context/v1",
                 "source": {"role": "source", "text": request["source_text"]},
                 "assumptions": {"role": "declared_assumptions", "text": request["context"]["text"] if forward else "",
                                 "bindings": request["context"]["bindings"] if forward else {}}}).decode("utf-8")


def _row_binding(row):
    return {key: row[key] for key in ROW_BINDING_FIELDS}


def validate_lane_bundle(bundle, *, expected_bindings):
    """Check exact input/vector joins against separately pinned producer rows.

    The caller selects profile and normalized producer-receipt content hashes.
    File pins in that receipt are declarations here; this API performs no I/O.
    """
    _raw(bundle)
    _raw(expected_bindings)
    _closed(bundle, {"schema", "profile", "producer_receipt", "rows", "content_sha256"}, "lane bundle")
    _require(bundle["schema"] == SCHEMA, "lane bundle schema differs")
    _seal_check(bundle, "bundle")
    _closed(expected_bindings, {"profile_sha256", "producer_receipt_sha256", "inputs"}, "externally selected bindings")
    for name in ("profile_sha256", "producer_receipt_sha256"):
        _sha(expected_bindings[name], name)
    profile = bundle["profile"]
    _profile(profile)
    _require(_digest(profile) == expected_bindings["profile_sha256"], "externally pinned producer/stage profile differs")
    producer = bundle["producer_receipt"]
    _closed(producer, {"schema", "profile_sha256", "artifact_binding", "rows", "content_sha256"}, "producer row receipt")
    _require(producer["schema"] == PRODUCER_SCHEMA and producer["profile_sha256"] == _digest(profile),
             "producer receipt profile differs")
    _seal_check(producer, "producer receipt")
    _require(_digest(producer) == expected_bindings["producer_receipt_sha256"], "externally pinned producer rows differ")
    artifact = producer["artifact_binding"]
    _closed(artifact, {"path", "bytes", "sha256"}, "declared artifact binding")
    _text(artifact["path"], "declared artifact path", maximum=4096)
    _require(type(artifact["bytes"]) is int and 0 < artifact["bytes"] <= 256 * 1024 * 1024, "bounded artifact size required")
    _sha(artifact["sha256"], "artifact file SHA")
    rows, producer_rows, inputs = bundle["rows"], producer["rows"], expected_bindings["inputs"]
    _require(all(type(value) is list for value in (rows, producer_rows, inputs)) and 1 <= len(rows) <= MAX_ROWS
             and len(rows) == len(producer_rows) == len(inputs), "complete ordered lane/producer/input rows required")
    seen, summaries = set(), []
    for row, bound, expected in zip(rows, producer_rows, inputs, strict=True):
        _closed(row, ROW_FIELDS, "representation row")
        _closed(bound, ROW_BINDING_FIELDS, "producer row binding")
        _closed(expected, {"id", "input_sha256"}, "externally pinned input row")
        _text(row["id"], "row id", maximum=512)
        _require(row["id"] not in seen and row["id"] == bound["id"] == expected["id"], "duplicate, foreign or reordered row id")
        seen.add(row["id"])
        _input(row["input"])
        _sha(row["input_sha256"], "row input SHA")
        _require(row["input_sha256"] == _digest(row["input"]) == expected["input_sha256"], "externally pinned source/context input differs")
        _text(row["encoder_text"], "serialized encoder text", maximum=262144)
        _sha(row["encoder_text_sha256"], "encoder text SHA")
        _require(row["encoder_text"] == _encoder_text(row["input"], profile["inference_input_recipe"])
                 and row["encoder_text_sha256"] == hashlib.sha256(row["encoder_text"].encode("utf-8")).hexdigest(),
                 "exact serialized encoder input recipe differs")
        _require(type(row["status"]) is str and row["status"] in {"available", "unavailable", "ablation_zero"}, "known vector outcome required")
        _sha(row["upstream_vector_sha256"], "upstream vector SHA", nullable=True)
        _sha(row["token_receipt_sha256"], "token receipt SHA", nullable=True)
        if profile["stage"] in DERIVED and row["status"] != "unavailable":
            _require(row["upstream_vector_sha256"] is not None, "derived representation requires an upstream vector binding")
        elif profile["stage"] in {"raw_embedding", "historical_linguistic_features"}:
            _require(row["upstream_vector_sha256"] is None, "raw producer cannot impersonate a derived view")
        if row["status"] == "unavailable":
            _text(row["reason"], "unavailable reason", maximum=4096)
            _require(row["vector"] is None and row["vector_sha256"] is None, "unavailable vectors cannot be padded or invented")
        else:
            vector = row["vector"]
            _require(type(vector) is list and len(vector) == profile["dimension"]
                     and all(type(value) is float and math.isfinite(value) for value in vector), "exact-width finite float vector required")
            _sha(row["vector_sha256"], "vector SHA")
            _require(row["vector_sha256"] == _digest(vector), "exact vector serialization digest differs")
            if profile["precision"] == "float32":
                try:
                    exact = all(struct.unpack("<f", struct.pack("<f", value))[0] == value for value in vector)
                except (OverflowError, struct.error) as error:
                    raise ValueError("exact finite float32 producer values required") from error
                _require(exact, "exact finite float32 producer values required")
            elif profile["precision"] == "decimal6":
                _require(all(round(value, 6) == value for value in vector), "preserved round6 feature values required")
            if row["status"] == "ablation_zero":
                _text(row["reason"], "explicit zero ablation reason", maximum=4096)
                _require(all(value == 0.0 for value in vector), "zero ablation cannot carry real vectors")
            else:
                _require(row["reason"] is None, "available vector cannot carry an unavailable/ablation reason")
                norm = math.hypot(*vector)
                _require(math.isfinite(norm) and norm > 0, "zero/nonfinite norm cannot be a real representation")
                if profile["normalization"]["kind"] == "l2":
                    _require(abs(norm - 1.0) <= profile["normalization"]["unit_tolerance"], "producer-declared L2 normalization differs")
        _sha(row["producer_row_sha256"], "producer row SHA")
        _require(_raw(_row_binding(row)) == _raw(bound) and row["producer_row_sha256"] == _digest(bound),
                 "vector/input/token/stage outcome differs from bound producer row")
        context_forwarded = profile["inference_input_recipe"] == "role_marked_declared_context/v1" and bool(row["input"]["context"]["text"])
        summaries.append({**_row_binding(row), "producer_row_sha256": row["producer_row_sha256"],
                          "source_sha256": hashlib.sha256(row["input"]["source_text"].encode("utf-8")).hexdigest(),
                          "context_sha256": row["input"]["context"]["sha256"], "context_forwarded": context_forwarded,
                          "context_resolved": False})
    result = {"schema": VALIDATION_SCHEMA, "status": "validated_declared_representation_identity_only",
              "lane_id": profile["lane_id"], "stage": profile["stage"], "dimension": profile["dimension"],
              "bundle_sha256": _digest(bundle), "profile_sha256": _digest(profile), "producer_receipt_sha256": _digest(producer),
              "row_count": len(rows), "rows": summaries,
              "available_count": sum(row["status"] == "available" for row in rows),
              "unavailable_count": sum(row["status"] == "unavailable" for row in rows),
              "zero_ablation_count": sum(row["status"] == "ablation_zero" for row in rows),
              "input_recipes_agree": True, "normalization_performed": False, "padding_or_truncation_performed": False,
              "token_receipt_contents_verified": False, "leanstral_runtime_qualified": False,
              "verification_status": "pending", "admission_status": "pending", "masks": dict.fromkeys(MASKS, 0),
              "model_calls": 0, "encoder_calls": 0, "prover_calls": 0, "optimizer_updates": 0, **FALSE}
    result["content_sha256"] = _digest(result)
    return result


__all__ = ["validate_lane_bundle"]

"""Reference-free numerical assay of source formatting and supplied context.

The assay consumes already bound native or explicitly diagnostic receipts. It
runs no encoder, fits no weights, resolves no context, and judges no meaning.
Observed equality is a comparison of supplied results, not independent replay
or general determinism. Different vectors establish numerical sensitivity only.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict

SCHEMA = "alignment-context-embedding-assay/v1"
VALIDATION_SCHEMA = "alignment-context-embedding-assay-validation/v1"
TOLERANCE = 1e-5
MAX_BYTES = 8 * 1024 * 1024
ARMS = ("raw_source", "source_frame_only", "declared_context")
COMPARISONS = {"formatting": ("raw_source", "source_frame_only"),
               "declared_context": ("source_frame_only", "declared_context"),
               "total": ("raw_source", "declared_context")}
_AUTHORITY = {"qualified": False, "source_fidelity_established": False, "context_resolution_executed": False,
              "context_semantics_applied": False,
              "independent_fidelity_available": False, "proof_authority": False,
              "training_executed": False, "query_generation_executed": False,
              "model_inference_executed": False, "encoder_execution_executed": False}
_NUMERIC_FIELDS = ("unit_cosine_similarity", "unit_cosine_distance", "normalized_value_l2_distance")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError) as error:
        raise ValueError("bounded finite ordinary UTF8 JSON required") from error
    _require(len(raw) <= MAX_BYTES, "context assay exceeds artifact byte bound")
    return raw


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _direction(vector, dimension):
    _require(type(vector) is list and len(vector) == dimension
             and all(type(value) is float and math.isfinite(value) for value in vector),
             "finite native-width float vector required")
    scale = max(abs(value) for value in vector)
    _require(scale > 0, "zero vector has no cosine direction")
    scaled = [value / scale for value in vector]
    length = math.hypot(*scaled)
    return [value / length for value in scaled]


def _comparison(left, right, *, left_text, right_text, dimension):
    endpoints = {"left_status": left["status"] if left is not None else "receipt_missing",
                 "right_status": right["status"] if right is not None else "receipt_missing",
                 "encoder_text_equal": left_text == right_text}
    absent = [name + "_" + (receipt["status"] if receipt is not None else "receipt_missing")
              for name, receipt in (("left", left), ("right", right))
              if receipt is None or receipt["status"] != "embedded"]
    if absent:
        return {**endpoints, "status": "unavailable", "reason": ";".join(absent),
                "exact_vector_hash_equal": None, "exact_vector_values_equal": None,
                **dict.fromkeys(_NUMERIC_FIELDS), "within_tolerance": None}
    first, second = left["embedding"], right["embedding"]
    first_unit, second_unit = _direction(first, dimension), _direction(second, dimension)
    cosine = max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(first_unit, second_unit, strict=True))))
    distance = math.hypot(*(a - b for a, b in zip(first, second, strict=True)))
    _require(math.isfinite(cosine) and math.isfinite(distance), "nonfinite context comparison")
    return {**endpoints, "status": "available", "reason": None,
            "exact_vector_hash_equal": left["embedding_sha256"] == right["embedding_sha256"],
            "exact_vector_values_equal": first == second,
            "unit_cosine_similarity": cosine, "unit_cosine_distance": 1.0 - cosine,
            "normalized_value_l2_distance": distance,
            "within_tolerance": distance <= TOLERANCE and 1.0 - cosine <= TOLERANCE}


def _summary(records):
    summary = {"original_inputs": len(records), "comparisons": {}}
    for name in COMPARISONS:
        comparisons = [row["comparisons"][name] for row in records]
        available = [item for item in comparisons if item["status"] == "available"]
        summary["comparisons"][name] = {
            "eligible_count": len(available), "unavailable_count": len(comparisons) - len(available),
            "equal_encoder_text_count": sum(item["encoder_text_equal"] for item in comparisons),
            "exact_vector_hash_equal_count": sum(item["exact_vector_hash_equal"] for item in available),
            "exact_vector_values_equal_count": sum(item["exact_vector_values_equal"] for item in available),
            "within_tolerance_count": sum(item["within_tolerance"] for item in available),
            "means": {field: math.fsum(item[field] for item in available) / len(available) if available else None
                      for field in _NUMERIC_FIELDS},
            "maxima": {field: max(item[field] for item in available) if available else None
                       for field in _NUMERIC_FIELDS}}
    return summary


def compare_context_embeddings(inputs, raw_source_inputs, raw_source_lane, context_lane):
    """Compare bound raw, source-framed, and context-framed receipts, no gold.

    The fixed authored input contract has 34 originals, including 32 without
    supplied assumptions and one same-wording pair with two explicit contexts.
    Framed arms retain a common JSON shell. No semantic reference is accepted.
    Owner validators are lazy and do not load models for this receipt assay.
    """
    from .alignment_context_embeddings import (
        validate_context_embedding_inputs,
        validate_context_embedding_lane,
    )
    from .alignment_richer_embeddings import (
        validate_embedding_lane,
        validate_richer_embedding_inputs,
    )

    _raw((inputs, raw_source_inputs, raw_source_lane, context_lane))
    validate_context_embedding_inputs(inputs)
    validate_richer_embedding_inputs(raw_source_inputs)
    validate_embedding_lane(raw_source_lane, raw_source_inputs)
    validate_context_embedding_lane(context_lane, inputs)
    _require(raw_source_lane["lane_id"] == context_lane["lane_id"]
             and raw_source_lane["dimension"] == context_lane["dimension"]
             and type(raw_source_lane["dimension"]) is int
             and raw_source_lane["dimension"] in (8, 384, 768), "raw/context native lane identities or widths differ")
    dimension = raw_source_lane["dimension"]
    originals = {row["input_sha256"]: row for row in raw_source_inputs["rows"]}
    _require(len(originals) == 34, "fixed 34 original inputs required")
    framed, context_metadata = {}, {}
    for row in inputs["rows"]:
        identity = row["original_input_sha256"]
        _require(identity in originals and row["arm_id"] in ARMS[1:], "framed receipt belongs to an unknown original or arm")
        original = originals[identity]
        _require(row["source_sha256"] == original["source_sha256"]
                 and row["source_text"] == original["source_text"]
                 and row["context"]["role"] == original["context_role"], "framed source/context does not match the raw baseline input")
        key = (identity, row["arm_id"])
        _require(key not in framed, "duplicate original/arm framing")
        framed[key] = row
        if identity in context_metadata:
            _require(_raw(context_metadata[identity]) == _raw(row["context"]), "original context differs between framed arms")
        context_metadata[identity] = row["context"]
    _require(len(framed) == 68 and set(context_metadata) == set(originals)
             and all((identity, arm) in framed for identity in originals for arm in ARMS[1:]),
             "two complete framed arms for all 34 originals required")
    contexts = [identity for identity, row in originals.items() if row["context_role"] == "explicit_assumptions"]
    _require(len(contexts) == 2, "fixed two explicit-context inputs required")
    raw_receipts = {row["id"]: row for row in raw_source_lane["receipts"]}
    framed_receipts = {row["id"]: row for row in context_lane["receipts"]}
    records, endpoints = [], {}
    for identity in sorted(originals):
        original = originals[identity]
        rows = {arm: framed[(identity, arm)] for arm in ARMS[1:]}
        receipts = {"raw_source": raw_receipts.get(original["id"]),
                    **{arm: framed_receipts.get(rows[arm]["id"]) for arm in ARMS[1:]}}
        texts = {"raw_source": original["source_text"], **{arm: rows[arm]["encoder_text"] for arm in ARMS[1:]}}
        for arm, receipt in receipts.items():
            if receipt is not None and arm != "raw_source":
                _require(receipt["original_input_sha256"] == identity and receipt["arm_id"] == arm,
                         "framed receipt original/arm linkage changed")
        endpoints[identity] = {"receipts": receipts, "texts": texts}
        record = {"original_input_sha256": identity, "source_sha256": original["source_sha256"],
                  "context_role": original["context_role"], "raw_source_id": original["id"],
                  "framed_ids": {arm: rows[arm]["id"] for arm in ARMS[1:]},
                  "encoder_text_sha256": {arm: hashlib.sha256(text.encode("utf-8")).hexdigest() for arm, text in texts.items()},
                  "comparisons": {name: _comparison(receipts[left], receipts[right], left_text=texts[left],
                      right_text=texts[right], dimension=dimension) for name, (left, right) in COMPARISONS.items()}}
        if original["context_role"] == "none_required":
            _require(texts["source_frame_only"] == texts["declared_context"], "no-context framing control changed encoder text")
        records.append(record)
    groups = defaultdict(list)
    for identity, original in originals.items():
        groups[original["source_sha256"]].append(identity)
    duplicated = [sorted(ids) for ids in groups.values() if len(ids) > 1]
    _require(len(duplicated) == 1 and len(duplicated[0]) == 2 and set(duplicated[0]) == set(contexts),
             "expected one two-member same-source explicit-context group")
    pairs = []
    for identities in sorted(duplicated):
        left, right = identities
        _require(originals[left]["source_text"] == originals[right]["source_text"], "same source hash has different source bytes")
        _require(_raw(context_metadata[left]) != _raw(context_metadata[right]), "same-wording interpretations need distinct supplied contexts")
        pairs.append({"source_sha256": originals[left]["source_sha256"], "original_input_sha256s": identities,
                      "distinct_declared_contexts": True,
                      "arms": {arm: _comparison(endpoints[left]["receipts"][arm], endpoints[right]["receipts"][arm],
                           left_text=endpoints[left]["texts"][arm], right_text=endpoints[right]["texts"][arm],
                           dimension=dimension) for arm in ARMS}})
    fixture = any(lane["status"] == "diagnostic_fixture" for lane in (raw_source_lane, context_lane))
    native = all(lane["status"] == "produced" and lane["encoder_execution_executed"] is True
                 for lane in (raw_source_lane, context_lane))
    available = sum(comparison["status"] == "available" for record in records for comparison in record["comparisons"].values())
    result = {"schema": SCHEMA, "status": "complete" if available == 102 else "partial" if available else "unavailable",
              "lane_id": raw_source_lane["lane_id"], "dimension": dimension,
              "bindings": {"context_inputs_sha256": _digest(inputs), "raw_source_inputs_sha256": _digest(raw_source_inputs),
                           "raw_source_lane_sha256": _digest(raw_source_lane), "context_lane_sha256": _digest(context_lane)},
              "original_input_count": 34, "framed_input_count": 68, "non_context_controls": 32, "explicit_context_inputs": 2,
              "comparison_count": 102, "available_comparison_count": available,
              "tolerance": TOLERANCE, "tolerance_recipe": "both_supplied_normalized_value_l2_and_unit_cosine_distance_le_1e-5",
              "distance_recipe": "l2_on_supplied_normalized_values_without_renormalization; cosine_on_stable_l2_directions_clamped_roundoff",
              "value_equality_recipe": "ordered_original_float_numeric_equality_signed_zero_equal",
              "hash_equality_recipe": "original_owner_canonical_json_embedding_sha256",
              "records": records, "summaries": {"all_inputs": _summary(records),
                  "none_required": _summary([row for row in records if row["context_role"] == "none_required"]),
                  "explicit_assumptions": _summary([row for row in records if row["context_role"] == "explicit_assumptions"])},
              "context_pairs": pairs, "diagnostic_fixture": fixture,
              "evidence_scope": "diagnostic_fixture" if fixture else "observed_native_receipts" if native else "partial_or_unavailable_receipts",
              "native_receipt_evidence_available": native and not fixture,
              "runtime_cryptographically_attested": False, "independent_replay_established": False,
              "general_encoder_determinism_established": False, "vector_separation_establishes_fidelity": False,
              "source_context_identity_independently_authenticated": False,
              "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0, **_AUTHORITY}
    result["assay_sha256"] = _digest(result)
    return result


def validate_context_assay(assay, inputs, raw_source_inputs, raw_source_lane, context_lane):
    """Recompute the closed assay from unchanged receipts; integrity only."""
    expected = compare_context_embeddings(inputs, raw_source_inputs, raw_source_lane, context_lane)
    _require(_raw(assay) == _raw(expected), "context assay differs from exact reference-free receipt recomputation")
    return {"schema": VALIDATION_SCHEMA, "status": "validated_integrity_only", "assay_sha256": expected["assay_sha256"],
            "bindings": dict(expected["bindings"]), "original_input_count": 34, "framed_input_count": 68,
            "diagnostic_fixture": expected["diagnostic_fixture"], "semantic_quality_checked": False, **_AUTHORITY}


__all__ = ["compare_context_embeddings", "validate_context_assay"]

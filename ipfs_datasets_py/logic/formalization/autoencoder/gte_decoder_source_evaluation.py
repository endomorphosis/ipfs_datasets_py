"""Prepare source-only regression evaluation from the original cached archives.

All 242 original audit rows and donor/replay bindings are admitted before this
plan selects the original 60 exposed validation rows and two legacy training
diagnostics. References are scoring data and never generation inputs. Native
evaluation readiness is independent of the selected training-prefix readiness.
This module imports no numerical or encoder library and grants no qualification.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


SCHEMA = "gte-decoder-source-evaluation/v1"
SCORE_SCHEMA = "gte-decoder-source-generation-score/v1"
MAX_PLAN_BYTES = 8 * 1024 * 1024
FLAGS = {
    "archived_inputs_reused": True,
    "source_split_memberships_changed": False,
    "source_only_generation_required": True,
    "reference_prefix_used": False,
    "references_used_only_for_scoring": True,
    "validation_is_independent_holdout": False,
    "independent_qualification_executed": False,
    "producer_execution_authenticated": False,
    "archive_authenticity_verified": False,
    "teacher_qualified": False,
    "production_kd_eligible": False,
    "encoder_inference_executed": False,
    "embeddings_generated": False,
    "generation_executed": False,
    "training_executed": False,
    "distillation_executed": False,
    "proof_authority": False,
}
_FIELDS = {"schema", "status", "initialization_representation_id", "initialization_content_sha256",
    "native_plan_sha256", "batch_sha256", "replay_sha256", "donor_pins", "profile_id",
    "asset_manifest_sha256", "source_manifest_bindings", "max_primary_rows", "max_auxiliary_rows",
    "full_original_audit_row_count", "heads", "selected_row_count", "donor_ready_row_count",
    "native_ready_row_count", "native_missing_row_count", "native_quarantined_row_count",
    "plan_sha256", *FLAGS}
_HEAD_FIELDS = {"codec_sha256", "target_vocabulary", "inherited_max_target_tokens", "max_new_tokens",
    "status", "selected_row_count", "donor_ready_row_count", "native_ready_row_count",
    "native_missing_row_count", "native_quarantined_row_count", "rows", "rows_sha256"}
_ROW_FIELDS = {"id", "source_text", "source_sha256", "split", "evaluation_role", "audit_row_sha256",
    "embedding_task_id", "embedding_task", "native_receipt", "native_receipt_sha256",
    "native_status", "quarantine_reasons", "generation_input", "native_generation_input", "reference"}
_REFERENCE_FIELDS = {"target", "target_sha256", "token_ids", "token_ids_sha256"}
_GENERATION_FIELDS = {"generated_ids", "terminated", "truncated"}


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_source_evaluation_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load source evaluation dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_NATIVE = _helper("gte_decoder_native_batch")
_BATCH = _NATIVE._BATCH


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError("bounded finite source evaluation JSON required") from exc


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _limits(primary, auxiliary):
    _require(type(primary) is int and 1 <= primary <= 60,
             "max_primary_rows must be an integer from 1 to 60")
    _require(type(auxiliary) is int and 1 <= auxiliary <= 2,
             "max_auxiliary_rows must be an integer from 1 to 2")


def _input(vector, dimension, origin):
    return {"input_dimension": dimension, "input_vector": deepcopy(vector),
            "input_sha256": digest(vector), "input_origin": origin}


def _assemble(initialization, native_plan, batch, replay, pins, primary_limit, auxiliary_limit):
    tasks = {task["id"]: task for task in native_plan["task_manifest"]["tasks"]}
    receipts = {row["id"]: row for row in native_plan["cache_reuse"]["reused_receipts"]}
    rejected = {row["row_sha256"]: row for row in native_plan["task_manifest"]["rejected_rows"]}
    _, legacy_training = _NATIVE._legacy_sources(native_plan["legacy8_inputs"])
    legacy_latents = {row["id"]: row["latent"] for row in legacy_training}
    heads = {}
    for name, selected, nested, width, role, origin in (
        ("primary384", native_plan["audit_rows"][180:240][:primary_limit], "primary", 384,
         "original_validation_exposed_regression_only", "original_cached_384d_validation_input"),
        ("legacy8", native_plan["audit_rows"][240:][:auxiliary_limit], "legacy8", 8,
         "legacy_training_diagnostic_only", "original_8d_raw_latent_reconstructed_from_cached_embedding"),
    ):
        codec = initialization[nested]["codec"]
        max_tokens = initialization[nested]["config"]["max_target_tokens"]
        vocabulary = codec["target_vocabulary"]
        rows = []
        for original in selected:
            source_sha = hashlib.sha256(original["source_text"].encode("utf-8")).hexdigest()
            row_sha = _NATIVE._AUDIT._digest(original)
            task_id = _NATIVE._CORPUS._task_id("legal_ir", original["id"])
            reject = rejected.get(row_sha)
            task = tasks.get(task_id)
            receipt = receipts.get(task_id)
            if reject is not None:
                _require(task is None and receipt is None, "quarantined evaluation source entered native cache")
                native_status = "quarantined"
            else:
                _require(task is not None and task["source_sha256"] == source_sha
                         and task["metadata"]["split"] == original["split"]
                         and task["metadata"]["reference_target_sha256"] == digest(original["reference_target"]),
                         "evaluation source task differs from original audited reference")
                native_status = "ready" if receipt is not None else "missing"
            reference = deepcopy(original["reference_target"])
            token_ids = _BATCH._encode(reference, vocabulary, name)
            _require(len(token_ids) <= max_tokens, "original evaluation target exceeds inherited codec budget")
            vector = original["embedding"] if name == "primary384" else legacy_latents[original["id"]]
            rows.append({"id": original["id"], "source_text": original["source_text"],
                "source_sha256": source_sha, "split": original["split"], "evaluation_role": role,
                "audit_row_sha256": row_sha, "embedding_task_id": task_id,
                "embedding_task": deepcopy(task), "native_receipt": deepcopy(receipt),
                "native_receipt_sha256": digest(receipt) if receipt is not None else None,
                "native_status": native_status,
                "quarantine_reasons": deepcopy(reject["reasons"]) if reject is not None else [],
                "generation_input": _input(vector, width, origin),
                "native_generation_input": _input(receipt["embedding"], 768,
                    "exact_cached_multilingual_768d_source_receipt") if receipt is not None else None,
                "reference": {"target": reference, "target_sha256": digest(reference),
                    "token_ids": token_ids, "token_ids_sha256": digest(token_ids)}})
        counts = {"selected_row_count": len(rows), "donor_ready_row_count": len(rows),
            "native_ready_row_count": sum(row["native_status"] == "ready" for row in rows),
            "native_missing_row_count": sum(row["native_status"] == "missing" for row in rows),
            "native_quarantined_row_count": sum(row["native_status"] == "quarantined" for row in rows)}
        heads[name] = {"codec_sha256": digest(codec), "target_vocabulary": deepcopy(vocabulary),
            "inherited_max_target_tokens": max_tokens, "max_new_tokens": max_tokens - 1,
            "status": _NATIVE._status(len(rows), counts["native_ready_row_count"]),
            **counts, "rows": rows, "rows_sha256": digest(rows)}
    counts = {key: sum(head[key] for head in heads.values()) for key in (
        "selected_row_count", "donor_ready_row_count", "native_ready_row_count",
        "native_missing_row_count", "native_quarantined_row_count")}
    result = {"schema": SCHEMA,
        "status": _NATIVE._status(counts["selected_row_count"], counts["native_ready_row_count"]),
        "initialization_representation_id": initialization["representation_id"],
        "initialization_content_sha256": digest(initialization), "native_plan_sha256": native_plan["plan_sha256"],
        "batch_sha256": batch["batch_sha256"], "replay_sha256": digest(replay), "donor_pins": deepcopy(pins),
        "profile_id": native_plan["profile_id"], "asset_manifest_sha256": native_plan["asset_manifest_sha256"],
        "source_manifest_bindings": deepcopy(native_plan["source_manifest_bindings"]),
        "max_primary_rows": primary_limit, "max_auxiliary_rows": auxiliary_limit,
        "full_original_audit_row_count": len(native_plan["audit_rows"]), "heads": heads, **counts, **FLAGS}
    result["plan_sha256"] = digest(result)
    _require(len(_raw(result)) <= MAX_PLAN_BYTES, "source evaluation plan exceeds 8 MiB")
    return result


def prepare_source_evaluation(initialization, native_plan, batch, replay, *, expected_donor_pins,
                              max_primary_rows=60, max_auxiliary_rows=2):
    """Reuse the original exposed validation and training diagnostic inputs exactly."""
    _limits(max_primary_rows, max_auxiliary_rows)
    _NATIVE.inspect_decoder_native_batch(native_plan, initialization, batch, replay,
                                         expected_donor_pins=expected_donor_pins)
    return _assemble(initialization, native_plan, batch, replay, expected_donor_pins,
                     max_primary_rows, max_auxiliary_rows)


def inspect_source_evaluation(plan, initialization, native_plan, batch, replay, *, expected_donor_pins):
    """Reconstruct every field without importing a model or authenticating execution."""
    _NATIVE.inspect_decoder_native_batch(native_plan, initialization, batch, replay,
                                         expected_donor_pins=expected_donor_pins)
    _BATCH._closed(plan, _FIELDS, "source evaluation plan")
    _limits(plan["max_primary_rows"], plan["max_auxiliary_rows"])
    _require(len(_raw(plan)) <= MAX_PLAN_BYTES, "source evaluation plan exceeds 8 MiB")
    _BATCH._closed(plan["heads"], {"primary384", "legacy8"}, "source evaluation heads")
    for head in plan["heads"].values():
        _BATCH._closed(head, _HEAD_FIELDS, "source evaluation head")
        _require(type(head["rows"]) is list, "evaluation row list required")
        for row in head["rows"]:
            _BATCH._closed(row, _ROW_FIELDS, "source evaluation row")
    reconstructed = _assemble(initialization, native_plan, batch, replay, expected_donor_pins,
                              plan["max_primary_rows"], plan["max_auxiliary_rows"])
    _require(_raw(plan) == _raw(reconstructed), "source evaluation differs from original archives or cache")
    return {"schema": "gte-decoder-source-evaluation-inspection/v1", "status": plan["status"],
        "plan_sha256": plan["plan_sha256"], "native_plan_sha256": plan["native_plan_sha256"],
        "selected_row_count": plan["selected_row_count"], "donor_ready_row_count": plan["donor_ready_row_count"],
        "native_ready_row_count": plan["native_ready_row_count"],
        "native_missing_row_count": plan["native_missing_row_count"],
        "native_quarantined_row_count": plan["native_quarantined_row_count"],
        "full_original_audit_row_count": plan["full_original_audit_row_count"], **FLAGS}


def _edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for index, first in enumerate(left, 1):
        current = [index]
        for position, second in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[position] + 1,
                               previous[position - 1] + (first != second)))
        previous = current
    return previous[-1]


def score_generation(generation, reference, codec, head):
    """Score every completed or capped raw token run; syntax failures stay failures.

    The caller first admits the full numerical generation receipt and extracts
    its generated_ids/terminated/truncated fields. This scorer authenticates no
    model execution. It strictly decodes canonical donor grammar and compares
    the stored original reference only after generation has finished.
    """
    _require(head in ("primary384", "legacy8"), "independent original decoder head required")
    _BATCH._closed(generation, _GENERATION_FIELDS, "generation scoring input")
    _BATCH._closed(reference, _REFERENCE_FIELDS, "original scoring reference")
    _require(type(codec) is dict and type(codec.get("target_vocabulary")) is list,
             "original donor codec required")
    vocabulary = codec["target_vocabulary"]
    _require(3 <= len(vocabulary) <= 4096 and all(type(token) is str for token in vocabulary)
             and len(set(vocabulary)) == len(vocabulary) and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"],
             "bounded distinct original vocabulary with exact special tokens required")
    expected = _BATCH._encode(reference["target"], vocabulary, head)
    _require(_raw(reference["token_ids"]) == _raw(expected) and digest(reference["target"]) == reference["target_sha256"]
             and digest(expected) == reference["token_ids_sha256"], "scoring reference hashes or codec differ")
    ids = generation["generated_ids"]
    bound = 512 if head == "primary384" else 64
    _require(type(ids) is list and 1 <= len(ids) <= bound
             and all(type(token) is int and token >= 0 for token in ids),
             "bounded raw generated integer token IDs required")
    _require(type(generation["terminated"]) is bool and type(generation["truncated"]) is bool
             and generation["truncated"] is not generation["terminated"], "exact generation stop flags required")
    terminated = generation["terminated"]
    _require((ids[-1] == 2 and ids.count(2) == 1) if terminated else (2 not in ids),
             "raw EOS tokens differ from generation termination flags")
    decoded, reason = None, None
    if not terminated:
        reason = "token_limit_without_eos"
    elif ids[0] != 1:
        reason = "invalid_start_token"
    elif any(token >= len(vocabulary) or token in (0, 1) for token in ids[1:-1]):
        reason = "invalid_raw_token"
    else:
        try:
            decoded = _BATCH._decode(ids, vocabulary, head)
        except (ValueError, TypeError, IndexError, UnicodeError, RecursionError):
            reason = "invalid_canonical_target"
    valid = decoded is not None
    exact = valid and digest(decoded) == reference["target_sha256"]
    field_matches = sum(decoded["rules"][0][field] == reference["target"]["rules"][0][field]
                        for field in _BATCH._FACETS) if valid else 0
    distance = _edit_distance(ids, expected)
    return {"schema": SCORE_SCHEMA, "head": head, "codec_sha256": digest(codec),
        "reference_sha256": reference["target_sha256"], "reference_token_ids_sha256": digest(expected),
        "generated_ids_sha256": digest(ids), "reference_token_count": len(expected),
        "generated_token_count": len(ids), "terminated": terminated, "truncated": generation["truncated"],
        "syntax_valid": valid, "invalid_generation": not valid, "exact_target_match": exact,
        "decoded_target": deepcopy(decoded), "decoded_target_sha256": digest(decoded) if valid else None,
        "field_match_count": field_matches, "field_count": len(_BATCH._FACETS),
        "token_edit_distance": distance, "normalized_token_edit_distance": distance / max(len(ids), len(expected)),
        "reason": reason, "reference_prefix_used": False, "references_used_only_for_scoring": True,
        "generation_execution_authenticated": False, "teacher_qualified": False,
        "production_kd_eligible": False, "proof_authority": False}

"""Source-only runtime capture for the independent legal formula lineage.

These are reproducible observations, not signatures or semantic attestations.
The producer invokes a trusted local runtime. Offline validation checks the
retained identities and output contract without importing weights or fitting.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from collections.abc import Mapping

SCHEMA = "learned-legal-formula-observation/v1"
RUNTIME_ID = "legal_ir:source_conditioned_formula_v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
          "semantic_correctness_verified", "promotion_performed", "publication_performed")
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _raw(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def learned_formula_model_identity(checkpoint_sha256):
    _require(isinstance(checkpoint_sha256, str) and _SHA.fullmatch(checkpoint_sha256),
             "learned formula checkpoint requires a SHA-256 identity")
    return RUNTIME_ID + ":sha256:" + checkpoint_sha256


def validate_learned_formula_observation(observation, source_text, *, source_span_id=None,
                                         expected_checkpoint_sha256=None):
    """Return the exact runtime row after validating its retained evidence.

    Source hashes identify the producer version; they need not equal today's
    checkout during historical import. Self-addressing detects inconsistency,
    not a malicious producer that fabricates a completely new signed-looking
    record. There is no signature, proof or qualification authority here.
    """
    _require(isinstance(observation, Mapping), "learned formula observation must be an object")
    keys = {"schema", "runtime_id", "model_identity", "checkpoint_sha256", "runtime_source_identity",
            "capture_source_sha256", "source_text_sha256", "source_span_id", "row_index", "inference",
            "inference_sha256", "provenance_scope"}
    _require(set(observation) == keys and observation["schema"] == SCHEMA
             and observation["runtime_id"] == RUNTIME_ID, "learned formula observation schema differs")
    checkpoint = observation["checkpoint_sha256"]
    _require(observation["model_identity"] == learned_formula_model_identity(checkpoint),
             "learned formula model identity differs")
    if expected_checkpoint_sha256 is not None:
        _require(checkpoint == expected_checkpoint_sha256, "learned formula checkpoint binding differs")
    _require(type(source_text) is str and 0 < len(source_text) <= 16384
             and observation["source_text_sha256"] == hashlib.sha256(source_text.encode()).hexdigest(),
             "learned formula source hash differs")
    _require(type(observation["source_span_id"]) is str and observation["source_span_id"].strip(),
             "learned formula source span identity required")
    if source_span_id is not None:
        _require(observation["source_span_id"] == source_span_id, "learned formula source span differs")
    identity = observation["runtime_source_identity"]
    _require(isinstance(identity, Mapping) and set(identity) == {"files", "sha256", "scope"}
             and identity["scope"] == "listed_runtime_files_only_not_transitive_dependency_provenance"
             and isinstance(identity["files"], Mapping) and bool(identity["files"])
             and all(type(k) is str and isinstance(v, str) and _SHA.fullmatch(v) for k, v in identity["files"].items())
             and identity["sha256"] == _sha(identity["files"]), "learned formula runtime source identity differs")
    _require(isinstance(observation["capture_source_sha256"], str) and _SHA.fullmatch(observation["capture_source_sha256"])
             and observation["provenance_scope"] == "local_runtime_capture_not_external_execution_attestation",
             "learned formula capture provenance differs")
    receipt = observation["inference"]
    receipt_fields = {"schema", "lineage_id", "checkpoint_sha256", "rows", "trained_checkpoint",
        "checkpoint_optimizer_steps", "status", "decoded_formulas_generated", "decoded_count",
        "training_executed", "source_input_conditioned", "independent_text_to_logic",
        "learned_formula_generation", "teacher_forcing", "target_access", *_FALSE}
    _require(isinstance(receipt, Mapping) and set(receipt) == receipt_fields
             and len(_raw(receipt)) <= 1024 * 1024 and observation["inference_sha256"] == _sha(receipt),
             "learned formula inference hash differs")
    _require(receipt.get("schema") == "learned-legal-formula-inference/v1"
             and receipt.get("lineage_id") == "source_conditioned_formula_v1"
             and receipt.get("checkpoint_sha256") == checkpoint
             and type(observation["row_index"]) is int and observation["row_index"] == 0
             and type(receipt.get("rows")) is list and len(receipt["rows"]) == 1,
             "learned formula inference checkpoint or row binding differs")
    row = receipt["rows"][0]
    row_required = {"source_sha256", "status", "canonical_ir", "formula_text", "formal_outputs", "teacher_forcing",
        "target_access", "training_executed", "source_input_conditioned", "independent_text_to_logic",
        "learned_formula_generation", "sample_memory_used", "family_syntax_checked", "temperature", "reason", *_FALSE}
    _require(isinstance(row, Mapping) and row_required <= set(row)
             and set(row) <= row_required | {"detail", "generated_token_ids", "minimum_decision_logit_margin", "syntax_scope"}
             and row.get("source_sha256") == observation["source_text_sha256"],
             "learned formula runtime source differs")
    for value in (receipt, row):
        _require(all(value.get(name) is False for name in (*_FALSE, "training_executed", "teacher_forcing", "target_access"))
                 and all(value.get(name) is True for name in ("source_input_conditioned", "independent_text_to_logic", "learned_formula_generation")),
                 "learned formula no-target or authority contract differs")
    _require(row.get("sample_memory_used") is False and row.get("family_syntax_checked") is False
             and type(row.get("temperature")) is int and row["temperature"] == 0,
             "learned formula inference policy differs")
    steps = receipt.get("checkpoint_optimizer_steps")
    _require(type(steps) is int and steps >= 0 and receipt.get("trained_checkpoint") is (steps > 0),
             "learned formula training provenance differs")
    decoded = row.get("status") == "decoded"
    _require(row.get("status") in {"decoded", "abstained"}
             and receipt.get("status") == row["status"] and type(receipt.get("decoded_count")) is int
             and receipt["decoded_count"] == int(decoded)
             and receipt.get("decoded_formulas_generated") is decoded,
             "learned formula status differs")
    if "detail" in row:
        _require(type(row["detail"]) is str, "learned formula detail must be text")
    if "minimum_decision_logit_margin" in row:
        margin = row["minimum_decision_logit_margin"]
        _require(margin is None or (type(margin) in (int, float) and math.isfinite(margin) and margin > 0),
                 "learned formula decision margin must be positive finite numeric evidence")
    if "generated_token_ids" in row:
        tokens = row["generated_token_ids"]
        _require(type(tokens) is list and 1 <= len(tokens) <= 64
                 and all(type(token) is int and 0 <= token < 4096 for token in tokens) and tokens[0] == 1,
                 "learned formula generation token evidence differs")
    if not decoded:
        _require(row.get("canonical_ir") is None and row.get("formula_text") is None
                 and row.get("formal_outputs") == [] and type(row.get("reason")) is str and row["reason"],
                 "learned formula abstention contains a formula or lacks a reason")
        return row
    from ...optimizers.logic_theorem_optimizer.legal_formula_codec import _rule
    try:
        rule = _rule(row.get("canonical_ir"))
    except (TypeError, ValueError) as error:
        raise ValueError("learned formula canonical output is invalid: " + str(error)) from error
    outputs = row.get("formal_outputs")
    _require(type(outputs) is list and len(outputs) == 1 and isinstance(outputs[0], Mapping),
             "learned formula requires the exact single-rule output")
    output = outputs[0]
    _require(set(output) == {"family", "format", "payload", "formula_text", "formula_text_role", "syntax_scope", "origin", *_FALSE}
             and output.get("family") == "deontic" and output.get("format") == "typed-deontic-rule/v1"
             and output.get("origin") == "learned_source_conditioned_formula_decoder"
             and output.get("payload") == rule and output.get("formula_text") == row.get("formula_text")
             and type(row.get("formula_text")) is str and row["formula_text"]
             and output.get("formula_text_role") == "display_only_full_ast_is_authoritative"
             and output.get("syntax_scope") == row.get("syntax_scope") == "canonical_rule_schema_and_decoder_grammar"
             and all(output.get(name) is False for name in _FALSE) and row.get("reason") is None,
             "learned formula native output differs from canonical IR or provenance")
    tokens = row.get("generated_token_ids")
    _require(type(tokens) is list and 2 <= len(tokens) <= 64
             and all(type(token) is int and 0 <= token < 4096 for token in tokens)
             and tokens[0] == 1 and tokens[-1] == 2 and "minimum_decision_logit_margin" in row,
             "learned formula generation token evidence differs")
    return row


def capture_learned_formula_observations(runtime, sources):
    """Invoke the real, cached worker-private runtime on source strings only.

    ``sources`` contain exactly ``source_span_id`` and ``text``. Compilation,
    target preparation, training and Lake admission are separate caller paths.
    Each capture retains the exact single-source inference receipt, avoiding
    repeated copies of other rows when observations are published incrementally.
    """
    from ...optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import LearnedFormulaRuntime
    from .tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    _require(type(runtime) is LearnedFormulaRuntime, "capture requires the installed learned formula runtime")
    _require(type(sources) in (list, tuple) and 1 <= len(sources) <= 128,
             "capture requires one to 128 source rows")
    descriptor = runtime.describe()
    _require(descriptor["checkpoint_present"], "capture requires a bound checkpoint")
    result, seen = [], set()
    for source in sources:
        _require(type(source) is dict and set(source) == {"source_span_id", "text"}
                 and type(source["source_span_id"]) is str and source["source_span_id"].strip()
                 and source["source_span_id"] not in seen, "capture requires unique target-free source rows")
        seen.add(source["source_span_id"])
        receipt = runtime.infer([source["text"]])
        observation = {"schema": SCHEMA, "runtime_id": RUNTIME_ID,
            "model_identity": learned_formula_model_identity(descriptor["checkpoint_sha256"]),
            "checkpoint_sha256": descriptor["checkpoint_sha256"],
            "runtime_source_identity": descriptor["source_identity"], "capture_source_sha256": _SOURCE_SHA,
            "source_text_sha256": hashlib.sha256(source["text"].encode()).hexdigest(),
            "source_span_id": source["source_span_id"], "row_index": 0,
            "inference": receipt, "inference_sha256": _sha(receipt),
            "provenance_scope": "local_runtime_capture_not_external_execution_attestation"}
        validate_learned_formula_observation(observation, source["text"], source_span_id=source["source_span_id"],
                                             expected_checkpoint_sha256=descriptor["checkpoint_sha256"])
        # Detach shared Python aliases: edits to one retained AST view must not
        # silently mutate the other view and defeat the consistency check.
        result.append(json.loads(_raw(observation)))
    _require(runtime.describe() == descriptor and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
             "learned formula source or checkpoint changed during capture")
    return result

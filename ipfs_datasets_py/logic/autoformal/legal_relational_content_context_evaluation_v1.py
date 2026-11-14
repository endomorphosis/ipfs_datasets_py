"""Diagnostic context availability around the unchanged CONTENT batch owner.

An offered signature/role context is not permission to use that context at
inference time. This companion retains complete declarations and compares
their bindings; the existing batch owner alone owns prediction accounting and
reference comparisons. Public import requires only the standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA = "legal-relational-content-context-evaluation/v1"
PROFILE = "full-selected-unverified-content-context-inventory/v1"
CONTEXTS_SCHEMA = "legal-relational-content-context-inventory/v1"
MAX_CONTEXTS_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_POPULATION_BYTES = 128 * 1024
MAX_PREDICTIONS_BYTES = 16 * 1024 * 1024
MAX_REFERENCES_BYTES = 16 * 1024 * 1024
MAX_CONTEXT_BYTES = 524288
MAX_PREFIX_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_OBSERVATIONS = 256
MAX_JSON_NODES, MAX_JSON_DEPTH = 500000, 96
DECLARED_STATUSES = ("available", "unavailable", "unsupported", "pending", "error", "timeout",
                     "cancellation", "not_started")
AVAILABILITY_STATUSES = (*DECLARED_STATUSES, "missing", "duplicate", "malformed", "unverifiable_binding")
BINDING_STATUSES = ("matched", "mismatched", "unavailable", "missing", "duplicate", "malformed",
                    "unverifiable_binding", "unexpected", "unidentifiable", "not_generated")
_ORIGINS = ("authored_fixture", "target_derived_label", "caller_supplied_unverified")
_CONTEXT_FIELDS = {"content_context_utf8", "content_context_sha256", "content_context_origin"}
_ROW_FIELDS = {"id", "source_sha256", "context_sha256", "status", "reason"} | _CONTEXT_FIELDS
_OUTPUT_FIELDS = {"schema", "profile", "status", "inputs", "original_evaluation", "original_evaluation_sha256",
    "population", "coverage", "observation_ledger", "occurrences", "availability_counts",
    "generated_context_bindings", "generated_context_binding_counts", "producer_pins", "authority",
    "training_mask", "evaluation_gold_mask", "context_claims_are_declarations_only", "limitations"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_ROOT = _SELF_PATH.parents[2]
_DIRECT_SPECS = (
    ("logic/autoformal/legal_relational_batch_evaluation_v1.py",
     "663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138"),
    ("logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
)
_OPERATION_SNAPSHOTS = None
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_bound", "source_commitments_verified",
    "legal_roles_verified", "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "decoder_accuracy_established", "model_executed", "training_executed",
    "backend_executed", "Lean_admitted", "proof_authority", "numerical_execution_authenticated",
    "permitted_inference_context_verified", "content_context_origin_verified",
    "content_context_independence_verified", "checkpoint_compatibility_verified",
    "context_available_before_generation_verified", "context_inventory_completeness_authenticated"), False)


class RelationalContentContextEvaluationError(ValueError):
    """Whole-input, asset, trusted-source or complete-output refusal."""


def _need(condition, message):
    if not condition:
        raise RelationalContentContextEvaluationError(message)


def _is_sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _text(value, maximum):
    return type(value) is str and 0 < len(value) <= maximum and bool(value.strip())


def _copy(value, maximum, budget=None):
    remaining = maximum
    budget = [MAX_JSON_NODES] if budget is None else budget

    def visit(item, depth):
        nonlocal remaining
        budget[0] -= 1
        _need(budget[0] >= 0 and depth <= MAX_JSON_DEPTH, "ordinary JSON node/depth bound exceeded")
        if type(item) is dict:
            _need(len(item) <= budget[0], "ordinary JSON object bound exceeded")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "ordinary JSON byte bound exceeded")
            result = {}
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        if type(item) is list:
            _need(len(item) <= budget[0], "ordinary JSON list bound exceeded")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "ordinary JSON byte bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is str:
            _need(len(item) <= remaining, "ordinary JSON string bound exceeded")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError:
                raise RelationalContentContextEvaluationError("ordinary UTF8 required") from None
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded ordinary integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
            remaining -= len(repr(item))
        else:
            raise RelationalContentContextEvaluationError("ordinary finite JSON required")
        _need(remaining >= 0, "ordinary JSON byte bound exceeded")
        return item

    return visit(value, 0)


def _wire(value, maximum):
    checked = _copy(value, maximum)
    try:
        raw = json.dumps(checked, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RelationalContentContextEvaluationError("bounded ordinary UTF8 JSON required") from None
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded; truncation refused")
    return raw


def _digest(value, maximum):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _pairs(entries):
    result = {}
    for key, value in entries:
        _need(key not in result, "duplicate outer JSON key refused")
        result[key] = value
    return result


def _transport(raw, expected, maximum, budget):
    _need(_is_sha(expected), "independent whole-transport SHA256 required")
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded original transport bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent whole-transport pin differs")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(RelationalContentContextEvaluationError("finite outer JSON required")))
    except (ValueError, UnicodeError, RecursionError):
        raise RelationalContentContextEvaluationError("duplicate-free finite original UTF8 JSON required") from None
    value = _copy(value, maximum, budget)
    _wire(value, maximum)
    return value


def _snapshot(path):
    _need(path.is_absolute() and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "unaliased trusted source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES,
              "bounded regular trusted source required")
        raw = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
          "trusted source changed during snapshot")
    return hashlib.sha256(raw).hexdigest(), identity(before)


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)


def _direct_sources():
    snapshots = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "companion source changed since import")
    for relative, expected in _DIRECT_SPECS:
        path = _ROOT / relative
        snapshots[str(path)] = _snapshot(path)
        _need(snapshots[str(path)][0] == expected, "fixed owner source generation differs")
    return snapshots


def _owners():
    before = _direct_sources()
    from . import legal_relational_batch_evaluation_v1 as batch
    from ..formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
    from . import legal_compact_content_v1 as content
    modules = (batch, tokens, content)
    for module, (relative, _) in zip(modules, _DIRECT_SPECS):
        path = _ROOT / relative
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == path,
              "canonical operation module origin required")
    _need(batch._SELF_SNAPSHOT == before[str(Path(batch.__file__).absolute())],
          "batch import physical anchor differs")
    for module in (tokens, content):
        _need(module._SELF_SHA == before[str(Path(module.__file__).absolute())][0],
              "content import anchor differs")
    _need(_direct_sources() == before, "operation source changed during lazy import")
    return modules


def _sources(owners, closure=None):
    """Only executed fixed-owner closure can extend the fixed source population."""
    snapshots = _direct_sources()
    if closure is not None:
        _need(type(closure) is dict and 0 < len(closure) <= 128, "bounded actual batch producer closure required")
        for name, expected in closure.items():
            _need(type(name) is str and _is_sha(expected), "actual batch closure identity required")
            path = Path(name)
            _need(path.is_absolute() and path.is_relative_to(_ROOT) and path.suffix == ".py"
                  and ".." not in path.parts, "canonical actual batch closure path required")
            snapshots[name] = _snapshot(path)
            _need(snapshots[name][0] == expected, "actual batch closure source pin differs")
    elif _OPERATION_SNAPSHOTS is not None:
        snapshots.update({name: _snapshot(Path(name)) for name in _OPERATION_SNAPSHOTS})
    if _OPERATION_SNAPSHOTS is not None:
        _need(snapshots == _OPERATION_SNAPSHOTS, "operation source identity changed since first use")
    _need(owners[0]._SELF_SNAPSHOT == snapshots[str(Path(owners[0].__file__).absolute())],
          "actual batch loaded source anchor differs")
    return snapshots


def _asset(row):
    """A complete offered byte/hash pair is checked regardless of row association."""
    if type(row) is not dict:
        return None
    text, expected = row.get("content_context_utf8"), row.get("content_context_sha256")
    if type(text) is str:
        raw = text.encode("utf-8")
        _need(0 < len(raw) <= MAX_CONTEXT_BYTES, "complete available context byte bound exceeded")
        if _is_sha(expected):
            _need(hashlib.sha256(raw).hexdigest() == expected, "available context raw pin differs")
            return raw
    return None


def _prefix_record(raw, row, predictions, tokens, snapshots):
    checked = tokens.compact_content_allowed_token_ids_v1([], raw,
        expected_context_sha256=row["content_context_sha256"], codec=predictions["codec"],
        expected_codec_sha256=predictions["codec_sha256"])
    _need(type(checked) is dict and set(checked) == {
              "schema", "profile", "format", "codec_sha256", "context_sha256", "context_raw_sha256",
              "owner_pins", "authority", "training_mask", "evaluation_gold_mask", "status", "reason",
              "offered_ids", "allowed_token_ids", "counts", "local_prefix_only", "global_completability_proven",
              "remaining_token_slots"}
          and checked.get("schema") == "legal-compact-content-token-prefix/v1"
          and checked.get("profile") == "object-relational-compact-content-tokens/v1"
          and checked.get("format") == "fixed-json-lexical-compact-content/v1"
          and checked.get("offered_ids") == [] and checked.get("codec_sha256") == predictions["codec_sha256"]
          and checked.get("context_raw_sha256") == row["content_context_sha256"]
          and checked.get("status") == "empty" and checked.get("reason") is None
          and type(checked.get("allowed_token_ids")) is list and checked["allowed_token_ids"] == [1]
          and type(checked["allowed_token_ids"][0]) is int and checked.get("local_prefix_only") is True
          and checked.get("global_completability_proven") is False
          and type(checked.get("remaining_token_slots")) is int and checked["remaining_token_slots"] == 512
          and checked.get("counts") == {"nodes": 0, "quantifiers": 0, "modal_nodes": 0, "predicate_occurrences": 0}
          and all(type(value) is int for value in checked["counts"].values()),
          "public empty-prefix input commitments differ")
    # The actual public owner checked duplicate-free context syntax. This hashes
    # those exact supplied bytes in canonical form, never reference-derived data.
    canonical = _wire(json.loads(raw), MAX_CONTEXT_BYTES)
    _need(checked.get("context_sha256") == hashlib.sha256(canonical).hexdigest(),
          "public context canonical commitment differs")
    expected_paths = {str(_ROOT / relative) for relative, _ in _DIRECT_SPECS[1:]}
    records = checked.get("owner_pins")
    _need(type(records) is list and len(records) == len(expected_paths), "complete public prefix producer pins required")
    seen = set()
    for record in records:
        _need(type(record) is dict and set(record) == {"path", "bytes", "sha256"}, "closed prefix source record required")
        name = record["path"]
        _need(type(name) is str and name in expected_paths and name not in seen and name in snapshots
              and record["sha256"] == snapshots[name][0] and type(record["bytes"]) is int
              and record["bytes"] == snapshots[name][1][3], "public prefix source custody differs")
        seen.add(name)
    _need(seen == expected_paths and type(checked.get("authority")) is dict and checked["authority"]
          and all(value is False for value in checked["authority"].values())
          and type(checked.get("training_mask")) is int and checked["training_mask"] == 0
          and type(checked.get("evaluation_gold_mask")) is int and checked["evaluation_gold_mask"] == 0,
          "public context prefix authority differs")
    return _copy(checked, MAX_PREFIX_BYTES)


def _observe(value, index, population_rows, by_id):
    identity = value.get("id") if type(value) is dict else None
    identity = identity if _text(identity, 256) else None
    associated = by_id.get(identity) if identity is not None else None
    declared = value.get("status") if type(value) is dict else None
    declared = declared if type(declared) is str and len(declared) <= 128 else None
    row = {"index": index, "id": identity, "sha256": _digest(value, MAX_CONTEXTS_BYTES),
        "raw_observation": _copy(value, MAX_CONTEXTS_BYTES), "associated_population_index": associated,
        "declared_status": declared, "shape_valid": False, "shape_reasons": [], "binding_valid": False,
        "binding_reasons": [], "available_prefix": None, "available_prefix_sha256": None, "outcome": None}
    shape, binding = row["shape_reasons"], row["binding_reasons"]
    if type(value) is not dict:
        shape.append("context_observation_not_object")
    else:
        if set(value) != _ROW_FIELDS:
            shape.append("context_fields_mismatch")
        if identity is None:
            shape.append("context_id_invalid")
        for name in ("source_sha256", "context_sha256"):
            if not _is_sha(value.get(name)):
                shape.append("context_" + name + "_invalid")
            elif associated is not None and value[name] != population_rows[associated][name]:
                binding.append("context_" + name + "_mismatch")
        if declared == "available":
            if type(value.get("content_context_utf8")) is not str or not _is_sha(value.get("content_context_sha256")):
                shape.append("available_context_bytes_and_sha256_required")
            if value.get("content_context_origin") not in _ORIGINS:
                shape.append("content_context_origin_invalid")
            if value.get("reason") is not None:
                shape.append("available_reason_nonnull")
        elif declared in DECLARED_STATUSES:
            if any(value.get(key) is not None for key in _CONTEXT_FIELDS):
                shape.append("nonavailable_contains_content_context")
            if not _text(value.get("reason"), 512):
                shape.append("nonavailable_reason_required")
        else:
            shape.append("context_status_invalid")
    if associated is None:
        binding.append("context_identity_unidentifiable" if identity is None else "context_identity_unexpected")
    row["shape_valid"], row["binding_valid"] = not shape, not binding
    return row


def _binding(observed, occurrences, ledger, by_id):
    identity, associated = observed["id"], observed["associated_population_index"]
    result = {"index": observed["index"], "id": identity, "associated_population_index": associated,
        "original_outcome": observed["outcome"], "context_observation_indices": [], "status": None,
        "reasons": [], "raw_equal": None, "canonical_equal": None, "origin_equal": None}
    raw = observed["raw_observation"]
    if type(raw) is not dict or raw.get("status") != "generated":
        result["status"] = "not_generated"
        return result
    if associated is None:
        result["status"] = "unidentifiable" if identity is None else "unexpected"
        return result
    occurrence = occurrences[by_id[identity]]
    result["context_observation_indices"] = list(occurrence["observation_indices"])
    status = occurrence["status"]
    if status != "available":
        result["status"] = status if status in ("missing", "duplicate", "malformed", "unverifiable_binding") else "unavailable"
        result["reasons"] = ["inventory_" + status]
        return result
    if not observed["shape_valid"]:
        result["status"], result["reasons"] = "malformed", ["original_generated_observation_malformed"]
        return result
    if any(raw[name] != occurrence[name] for name in ("source_sha256", "context_sha256")):
        result["status"], result["reasons"] = "unverifiable_binding", ["original_generated_source_binding_differs"]
        return result
    decoded = observed["content_decoding"]
    if decoded is None:
        result["status"], result["reasons"] = "malformed", ["original_generated_context_not_checked"]
        return result
    inventory = ledger[occurrence["observation_indices"][0]]
    offered = inventory["raw_observation"]
    result["raw_equal"] = (raw["content_context_sha256"] == offered["content_context_sha256"]
                            and raw["content_context_utf8"] == offered["content_context_utf8"])
    result["canonical_equal"] = decoded["context_sha256"] == inventory["available_prefix"]["context_sha256"]
    result["origin_equal"] = raw["content_context_origin"] == offered["content_context_origin"]
    result["status"] = "matched" if all(result[name] for name in ("raw_equal", "canonical_equal", "origin_equal")) else "mismatched"
    result["reasons"] = [name + "_differs" for name in ("raw", "canonical", "origin") if not result[name + "_equal"]]
    return result


def prepare_relational_content_context_evaluation_v1(population_raw, references_raw, predictions_raw, contexts_raw, *,
        expected_population_sha256, expected_references_sha256, expected_predictions_sha256, expected_contexts_sha256):
    """Retain full context declarations around the original unchanged evaluation."""
    global _OPERATION_SNAPSHOTS
    budget = [MAX_JSON_NODES]
    population = _transport(population_raw, expected_population_sha256, MAX_POPULATION_BYTES, budget)
    predictions = _transport(predictions_raw, expected_predictions_sha256, MAX_PREDICTIONS_BYTES, budget)
    contexts = _transport(contexts_raw, expected_contexts_sha256, MAX_CONTEXTS_BYTES, budget)
    _need(type(references_raw) is bytes and 0 < len(references_raw) <= MAX_REFERENCES_BYTES
          and _is_sha(expected_references_sha256)
          and hashlib.sha256(references_raw).hexdigest() == expected_references_sha256,
          "bounded independently pinned original references required")
    _need(type(contexts) is dict and set(contexts) == {"schema", "population_sha256", "rows"}
          and contexts["schema"] == CONTEXTS_SCHEMA and contexts["population_sha256"] == expected_population_sha256
          and type(contexts["rows"]) is list and len(contexts["rows"]) <= MAX_OBSERVATIONS,
          "closed bounded population-bound context inventory required")
    assets = [_asset(row) for row in contexts["rows"]]
    originals = ((population, MAX_POPULATION_BYTES), (predictions, MAX_PREDICTIONS_BYTES),
                 (contexts, MAX_CONTEXTS_BYTES))
    original_hashes = tuple(_digest(value, maximum) for value, maximum in originals)
    owners = _owners()
    before = _sources(owners)
    batch, tokens, _ = owners
    original = batch.prepare_relational_content_token_batch_evaluation_v1(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256)
    snapshots = _sources(owners, original["producer_pins"])
    _need(all(snapshots.get(path) == value for path, value in before.items()), "sources changed across original batch evaluation")
    if _OPERATION_SNAPSHOTS is None:
        _OPERATION_SNAPSHOTS = dict(snapshots)
    original_sha = batch.relational_content_token_batch_evaluation_sha256(original)

    def fence():
        _need(tuple(_digest(value, maximum) for value, maximum in originals) == original_hashes,
              "detached complete context evaluation inputs changed")
        _need(_sources(owners, original["producer_pins"]) == snapshots,
              "operation sources changed during context evaluation")
        _need(batch.relational_content_token_batch_evaluation_sha256(original) == original_sha,
              "original batch evaluation changed during context diagnostics")

    fence()
    rows = population["rows"]
    expected_ids = original["population"]["ordered_ids"]
    _need([row["id"] for row in rows] == expected_ids, "actual original selected order differs")
    by_id = {identity: index for index, identity in enumerate(expected_ids)}
    ledger = [_observe(value, index, rows, by_id) for index, value in enumerate(contexts["rows"])]
    for observed, raw in zip(ledger, assets):
        if raw is not None:
            fence()
            checked = _prefix_record(raw, observed["raw_observation"], predictions, tokens, snapshots)
            fence()
            observed["available_prefix"] = checked
            observed["available_prefix_sha256"] = _digest(checked, MAX_PREFIX_BYTES)
    indices, unidentified = {}, []
    for observed in ledger:
        if observed["id"] is None:
            unidentified.append(observed["index"])
            observed["outcome"] = "unidentifiable"
        else:
            indices.setdefault(observed["id"], []).append(observed["index"])
            if observed["id"] not in by_id:
                observed["outcome"] = "unexpected"
    missing = [identity for identity in expected_ids if identity not in indices]
    duplicates = {identity: list(indices[identity]) for identity in expected_ids if len(indices.get(identity, [])) > 1}
    unexpected = {identity: list(values) for identity, values in indices.items() if identity not in by_id}
    occurrences, counts = [], dict.fromkeys(AVAILABILITY_STATUSES, 0)
    for index, row in enumerate(rows):
        selected = indices.get(row["id"], [])
        reasons = []
        if not selected:
            status, reasons = "missing", ["context_observation_missing"]
        elif len(selected) > 1:
            status, reasons = "duplicate", ["multiple_context_observations"]
        elif not ledger[selected[0]]["shape_valid"]:
            status, reasons = "malformed", list(ledger[selected[0]]["shape_reasons"])
        elif not ledger[selected[0]]["binding_valid"]:
            status, reasons = "unverifiable_binding", list(ledger[selected[0]]["binding_reasons"])
        else:
            status = ledger[selected[0]]["declared_status"]
        for observation_index in selected:
            ledger[observation_index]["outcome"] = status
        counts[status] += 1
        occurrences.append({"index": index, **row, "observation_indices": list(selected), "status": status, "reasons": reasons})
    _need(sum(counts.values()) == len(expected_ids) and all(row["outcome"] is not None for row in ledger)
          and sum(len(value) for value in indices.values()) + len(unidentified) == len(ledger),
          "complete selected and raw context population must be conserved")
    bindings = [_binding(observed, occurrences, ledger, by_id) for observed in original["observation_ledger"]]
    binding_counts = dict.fromkeys(BINDING_STATUSES, 0)
    for binding in bindings:
        binding_counts[binding["status"]] += 1
    _need(sum(binding_counts.values()) == len(original["observation_ledger"]), "complete original observation bindings required")
    result = {"schema": SCHEMA, "profile": PROFILE, "status": "full_selected_unreviewed_content_context_evaluated",
        "inputs": {name: {"sha256": expected, "bytes": len(raw)} for name, raw, expected in (
            ("population", population_raw, expected_population_sha256), ("references", references_raw, expected_references_sha256),
            ("predictions", predictions_raw, expected_predictions_sha256), ("contexts", contexts_raw, expected_contexts_sha256))},
        "original_evaluation": original, "original_evaluation_sha256": original_sha,
        "population": _copy(original["population"], MAX_POPULATION_BYTES),
        "coverage": {"valid": not (missing or duplicates or unexpected or unidentified), "expected_count": len(expected_ids),
            "context_row_count": len(ledger), "missing_ids": missing, "duplicate_ids": duplicates,
            "unexpected_ids": unexpected, "unidentifiable_indices": unidentified},
        "observation_ledger": ledger, "occurrences": occurrences, "availability_counts": counts,
        "generated_context_bindings": bindings, "generated_context_binding_counts": binding_counts,
        "producer_pins": {name: value[0] for name, value in snapshots.items()}, "authority": dict(_AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0, "context_claims_are_declarations_only": True,
        "limitations": [
            "The existing public CONTENT batch owner is replayed in full and embedded unchanged; this companion never selects an available subset, changes its denominator, repairs candidates or rescores predictions.",
            "Every submitted inventory row and original prediction observation is retained. Missing, duplicate, malformed and binding-conflicting declarations never select a favorable context.",
            "Available means a caller offered bytes that the existing public empty-prefix owner accepted. Availability before generation, source fidelity, independence and permitted inference use remain unverified.",
            "Source context_sha256 and content_context_sha256 name different objects. Exact raw bytes, canonical context and origin-label equality are separate diagnostics; whitespace-only raw differences remain visible.",
            "Origins and operational dispositions are caller declarations. Authored and target-derived contexts can support conditional transport diagnostics but cannot become source-only inference context, training gold or statutory review.",
            "Every complete offered byte/hash pair is checked even in duplicate, orphan or otherwise malformed rows. Invalid assets, trusted-owner/source errors, interruption and whole-input/output bounds abort without a partial report.",
            "The fixed vocabulary still requires every declared predicate to occur. Empty-prefix acceptance does not prove global completability, qualify broad-catalog selection or establish a model/checkpoint/numerical head.",
            "The original batch retains its 8MiB bound; this complete companion has a separate 16MiB bound and never truncates either report. No model, training, provider, database, backend, review, admission or publication occurs.",
            "Source snapshots bind fixed reviewed owners and their actual replayed dependency closure; they do not generally prove executed bytecode of preloaded modules. Native execution qualification is separate evidence.",
        ]}
    raw = _wire(result, MAX_OUTPUT_BYTES)
    fence()
    return json.loads(raw)


def relational_content_context_evaluation_sha256(report):
    """Hash a complete closed diagnostic; a self-address grants no authority."""
    detached = _copy(report, MAX_OUTPUT_BYTES)
    _need(type(detached) is dict and set(detached) == _OUTPUT_FIELDS
          and detached["schema"] == SCHEMA and detached["profile"] == PROFILE,
          "complete closed content-context evaluation required")
    return _digest(detached, MAX_OUTPUT_BYTES)


def validate_relational_content_context_evaluation_v1(report, population_raw, references_raw, predictions_raw, contexts_raw, *,
        expected_evaluation_sha256, expected_population_sha256, expected_references_sha256,
        expected_predictions_sha256, expected_contexts_sha256):
    """Require the independent complete report pin and full four-input replay."""
    _need(_is_sha(expected_evaluation_sha256), "independent complete evaluation SHA256 required")
    offered = _copy(report, MAX_OUTPUT_BYTES)
    _need(relational_content_context_evaluation_sha256(offered) == expected_evaluation_sha256,
          "independent complete evaluation pin differs")
    before = _wire(offered, MAX_OUTPUT_BYTES)
    regenerated = prepare_relational_content_context_evaluation_v1(population_raw, references_raw, predictions_raw, contexts_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256, expected_contexts_sha256=expected_contexts_sha256)
    _need(before == _wire(regenerated, MAX_OUTPUT_BYTES), "context evaluation differs from full original-bound regeneration")
    return regenerated


__all__ = ["RelationalContentContextEvaluationError", "prepare_relational_content_context_evaluation_v1",
           "relational_content_context_evaluation_sha256", "validate_relational_content_context_evaluation_v1"]

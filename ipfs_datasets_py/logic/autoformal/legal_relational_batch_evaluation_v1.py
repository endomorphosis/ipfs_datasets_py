"""Complete selected-population accounting over existing relational diagnostics.

The existing relational and paired owners validate syntax and compare declared
structure. This owner accounts for every submitted observation without running
a decoder, selecting statutory meaning, or granting training/gold authority.
Generation metadata is a declaration, not numerical or latent-only evidence.
Public import requires only the standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA = "legal-relational-batch-evaluation/v1"
PROFILE = "full-selected-authored-relational-output-diagnostics/v1"
COMPACT_SCHEMA = "legal-relational-compact-batch-evaluation/v1"
COMPACT_PROFILE = "full-selected-compact-id-output-diagnostics/v1"
COMPACT_PREDICTIONS_SCHEMA = "legal-relational-compact-batch-predictions/v1"
CONTENT_SCHEMA = "legal-relational-content-token-batch-evaluation/v1"
CONTENT_PROFILE = "full-selected-context-bound-content-token-output-diagnostics/v1"
CONTENT_PREDICTIONS_SCHEMA = "legal-relational-content-token-batch-predictions/v1"
MAX_POPULATION_BYTES = 128 * 1024
MAX_REFERENCES_BYTES = 16 * 1024 * 1024
MAX_PREDICTIONS_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 524288
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_PAIR_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_POPULATION_ROWS = 64
MAX_OBSERVATIONS = 256
MAX_JSON_NODES = 500000
MAX_JSON_DEPTH = 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE_FIELDS = {"id", "status", "request_utf8", "request_sha256", "report", "report_sha256", "reason"}
_PREDICTION_FIELDS = {"id", "source_sha256", "context_sha256", "status", "teacher_forcing",
                      "target_access", "request_utf8", "request_sha256", "reason"}
_GENERATION_FIELDS = {"kind", "population_sha256", "latent_dimension", "checkpoint_sha256",
                      "encoder_sha256", "settings_sha256", "teacher_forcing", "target_access"}
TERMINAL_STATUSES = ("missing", "duplicate", "malformed", "unverifiable_generation", "abstained",
                     "unsupported", "invalid_typed_output", "valid_without_reference", "compared")
_COMPACT_DECLARED_ONLY = ("abstained", "unsupported", "error", "timeout", "cancellation", "not_started")
COMPACT_TERMINAL_STATUSES = (*TERMINAL_STATUSES, "incomplete", "invalid_frame", "invalid_utf8",
                           "invalid_compact_output", "error", "timeout", "cancellation", "not_started")
_COMPACT_PREDICTION_FIELDS = {"id", "source_sha256", "context_sha256", "status", "teacher_forcing",
                            "target_access", "generated_ids", "generated_ids_sha256", "reason"}
_COMPACT_REJECTION_STATUSES = {"invalid_frame": "invalid_frame", "invalid_utf8": "invalid_utf8",
    "compact_json_rejected": "invalid_compact_output", "compact_projection_rejected": "invalid_compact_output",
    "typed_request_rejected": "invalid_typed_output"}
_CONTENT_CONTEXT_FIELDS = {"content_context_utf8", "content_context_sha256", "content_context_origin"}
_CONTENT_CONTEXT_ORIGINS = ("authored_fixture", "target_derived_label", "caller_supplied_unverified")
CONTENT_TERMINAL_STATUSES = (*TERMINAL_STATUSES, "incomplete", "invalid_frame", "invalid_content_output",
                           "budget_exhausted", "error", "timeout", "cancellation", "not_started")
_CONTENT_REJECTION_STATUSES = {"invalid_token_ids": "invalid_frame", "missing_bos": "invalid_frame",
    "interior_special_tokens": "invalid_frame", "invalid_compact_prefix": "invalid_content_output",
    "invalid_compact_content": "invalid_content_output", "output_limit_without_eos": "budget_exhausted",
    "no_admissible_next_token_within_total_limit": "budget_exhausted"}
COMPARISON_FIELDS = ("exact_typed_expression_equal", "family_profile_equal", "signature_declarations_equal",
                     "argument_roles_equal", "declared_structure_equal", "lexical_alpha_structure_equal")
FALSE_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified", "applicability_verified",
    "governing_use_verified", "independently_reviewed", "accepted", "admitted",
    "semantic_equivalence_verified", "legal_equivalence_verified", "semantic_graph_admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "decoder_accuracy_established", "model_executed", "training_executed", "backend_executed",
    "Lean_admitted", "proof_authority", "model_execution_verified",
    "generation_declarations_are_independent_proof", "partition_membership_verified",
    "source_commitments_verified", "reviewed_targets_verified",
    "numerical_execution_authenticated", "latent_only_verified",
), False)
_OUTPUT_FIELDS = {"schema", "profile", "status", "inputs", "population", "reference_availability",
    "coverage", "observation_ledger", "occurrences", "terminal_counts", "valid_typed_output",
    "full_selected_structure_diagnostics", "comparable_pair_structure_diagnostics", "generation",
    "generation_issues", "producer_pins", "authority", "training_mask", "evaluation_gold_mask",
    "generation_claims_are_declarations_only", "metric_reference_access", "limitations"}
_SELF_PATH = Path(__file__).absolute()
_OPERATION_SNAPSHOTS = None
_COMPACT_OPERATION_SNAPSHOTS = None
_CONTENT_OPERATION_SNAPSHOTS = None
# This fixed profile admits the reviewed token/content source generation only.
# No descriptor returned by an offered artifact may extend these source paths.
_CONTENT_DIRECT_SPECS = (
    ("logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
)
_CONTENT_PREDICTION_SOURCE_RELS = (
    "logic/autoformal/legal_compact_content_v1.py",
    "logic/autoformal/legal_relational_norm_v1.py",
    "logic/syntax_core/ast.py", "logic/syntax_core/signatures.py",
    "logic/TDFOL/tdfol_core.py",
)


class RelationalBatchEvaluationError(ValueError):
    """Original asset, ordinary intake, trusted source or complete bound failed."""


def _need(condition, message):
    if not condition:
        raise RelationalBatchEvaluationError(message)


def _is_sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _text(value, maximum):
    return type(value) is str and 0 < len(value) <= maximum and bool(value.strip())


def _copy(value, maximum, budget=None):
    """Detach finite ordinary JSON with bounds before encoding supplied strings."""
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
                raise RelationalBatchEvaluationError("valid ordinary UTF8 required") from None
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded ordinary integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
            remaining -= len(repr(item))
        else:
            raise RelationalBatchEvaluationError("ordinary finite JSON required")
        _need(remaining >= 0, "ordinary JSON byte bound exceeded")
        return item

    return visit(value, 0)


def _wire(value, maximum):
    checked = _copy(value, maximum)
    try:
        raw = json.dumps(checked, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RelationalBatchEvaluationError("bounded ordinary UTF8 JSON required") from None
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
            parse_constant=lambda _: (_ for _ in ()).throw(RelationalBatchEvaluationError("finite outer JSON required")))
    except (ValueError, UnicodeError, RecursionError):
        raise RelationalBatchEvaluationError("duplicate-free finite original UTF8 JSON required") from None
    value = _copy(value, maximum, budget)
    _wire(value, maximum)
    return value


def _reference(row, identity):
    _need(type(row) is dict and set(row) == _REFERENCE_FIELDS and row["id"] == identity,
          "exact ordered closed reference row required")
    status = row["status"]
    _need(type(status) is str and status in ("available", "unavailable"), "reference availability status required")
    if status == "unavailable":
        _need(all(row[key] is None for key in ("request_utf8", "request_sha256", "report", "report_sha256"))
              and _text(row["reason"], 512), "closed unavailable reference required")
        return
    text = row["request_utf8"]
    _need(type(text) is str and len(text) <= MAX_REQUEST_BYTES, "bounded reference request string required")
    raw = text.encode("utf-8")
    _need(0 < len(raw) <= MAX_REQUEST_BYTES and _is_sha(row["request_sha256"])
          and hashlib.sha256(raw).hexdigest() == row["request_sha256"], "reference request raw pin differs")
    _need(row["reason"] is None and type(row["report"]) is dict and _is_sha(row["report_sha256"])
          and _digest(row["report"], MAX_REPORT_BYTES) == row["report_sha256"],
          "available complete reference report pin differs")


def _generation(predictions, population_sha):
    present = "generation" in predictions
    value = predictions.get("generation")
    summary = {"present": present, "declaration_sha256": _digest(value, MAX_PREDICTIONS_BYTES) if present else None,
        "kind": None, "latent_dimension": None, "checkpoint_sha256": None,
        "encoder_sha256": None, "settings_sha256": None, "valid": False}
    if not present:
        return summary, ["generation_missing"]
    if type(value) is not dict:
        return summary, ["generation_not_object"]
    issues = []
    if set(value) != _GENERATION_FIELDS:
        issues.append("generation_fields_mismatch")
    kind = value.get("kind")
    if type(kind) is str and kind in ("decoder_declared", "authored_control"):
        summary["kind"] = kind
    else:
        issues.append("generation_kind_invalid")
    if value.get("population_sha256") != population_sha:
        issues.append("generation_population_mismatch")
    for name in ("checkpoint_sha256", "encoder_sha256", "settings_sha256"):
        if _is_sha(value.get(name)):
            summary[name] = value[name]
    if not _is_sha(value.get("settings_sha256")):
        issues.append("generation_settings_sha256_invalid")
    for name in ("teacher_forcing", "target_access"):
        if value.get(name) is not False:
            issues.append("generation_" + name + "_not_false")
    dimension = value.get("latent_dimension")
    if type(dimension) is int and dimension in (8, 384, 768):
        summary["latent_dimension"] = dimension
    if summary["kind"] == "decoder_declared":
        if summary["latent_dimension"] is None:
            issues.append("generation_decoder_dimension_invalid")
        for name in ("checkpoint", "encoder"):
            if summary[name + "_sha256"] is None:
                issues.append("generation_decoder_" + name + "_invalid")
    elif summary["kind"] == "authored_control":
        if any(value.get(key) is not None for key in ("latent_dimension", "checkpoint_sha256", "encoder_sha256")):
            issues.append("generation_authored_binding_nonnull")
    summary["valid"] = not issues
    return summary, issues


def _observation(value, index, population_index, population_rows, generation_issues):
    identity = value.get("id") if type(value) is dict else None
    identity = identity if _text(identity, 256) else None
    associated = population_index.get(identity) if identity is not None else None
    declared = value.get("status") if type(value) is dict else None
    declared = declared if type(declared) is str and len(declared) <= 128 else None
    row = {"index": index, "id": identity, "sha256": _digest(value, MAX_PREDICTIONS_BYTES),
        "associated_population_index": associated, "declared_status": declared,
        "shape_valid": False, "shape_reasons": [], "provenance_valid": False,
        "provenance_reasons": [], "outcome": None}
    shape, provenance = row["shape_reasons"], row["provenance_reasons"]
    request_raw, request_overflow = None, False
    if type(value) is not dict:
        shape.append("observation_not_object")
    else:
        if set(value) != _PREDICTION_FIELDS:
            shape.append("prediction_fields_mismatch")
        if identity is None:
            shape.append("prediction_id_invalid")
        for name in ("source_sha256", "context_sha256"):
            if not _is_sha(value.get(name)):
                shape.append("prediction_" + name + "_invalid")
            elif associated is not None and value[name] != population_rows[associated][name]:
                provenance.append("prediction_" + name + "_mismatch")
        for name in ("teacher_forcing", "target_access"):
            if value.get(name) is not False:
                provenance.append("prediction_" + name + "_not_false")
        if declared not in ("decoded", "abstained", "unsupported"):
            shape.append("prediction_status_invalid")
        elif declared == "decoded":
            if value.get("reason") is not None:
                shape.append("decoded_reason_nonnull")
            text = value.get("request_utf8")
            if type(text) is not str:
                shape.append("decoded_request_string_required")
            elif len(text) > MAX_REQUEST_BYTES:
                request_overflow = True
            else:
                request_raw = text.encode("utf-8")
                request_overflow = len(request_raw) > MAX_REQUEST_BYTES
                if request_overflow:
                    request_raw = None
            if not _is_sha(value.get("request_sha256")):
                shape.append("candidate_request_sha256_invalid")
            elif request_raw is not None and hashlib.sha256(request_raw).hexdigest() != value["request_sha256"]:
                shape.append("candidate_request_sha256_mismatch")
        else:
            if value.get("request_utf8") is not None or value.get("request_sha256") is not None:
                shape.append("abstention_contains_request")
            if not _text(value.get("reason"), 512):
                shape.append("abstention_reason_required")
    if generation_issues:
        provenance.append("generation_declaration_invalid")
    row["shape_valid"], row["provenance_valid"] = not shape, not provenance
    return row, request_raw, request_overflow


def _compact_observation(value, index, population_index, population_rows, generation_issues, *, content=False,
                         content_generation_kind=None):
    """Retain the complete offered observation, without inventing request text."""
    identity = value.get("id") if type(value) is dict else None
    identity = identity if _text(identity, 256) else None
    associated = population_index.get(identity) if identity is not None else None
    declared = value.get("status") if type(value) is dict else None
    declared = declared if type(declared) is str and len(declared) <= 128 else None
    row = {"index": index, "id": identity, "sha256": _digest(value, MAX_PREDICTIONS_BYTES),
        "associated_population_index": associated, "declared_status": declared,
        "shape_valid": False, "shape_reasons": [], "provenance_valid": False,
        "provenance_reasons": [], "outcome": None,
        "raw_observation": _copy(value, MAX_PREDICTIONS_BYTES)}
    if content:
        row.update(content_decoding=None, content_decoding_sha256=None)
    else:
        row["compact_decoding"] = None
    shape, provenance, decodable_ids = row["shape_reasons"], row["provenance_reasons"], None
    if type(value) is not dict:
        shape.append("observation_not_object")
    else:
        if set(value) != _COMPACT_PREDICTION_FIELDS | (_CONTENT_CONTEXT_FIELDS if content else set()):
            shape.append("prediction_fields_mismatch")
        if identity is None:
            shape.append("prediction_id_invalid")
        for name in ("source_sha256", "context_sha256"):
            if not _is_sha(value.get(name)):
                shape.append("prediction_" + name + "_invalid")
            elif associated is not None and value[name] != population_rows[associated][name]:
                provenance.append("prediction_" + name + "_mismatch")
        for name in ("teacher_forcing", "target_access"):
            if value.get(name) is not False:
                provenance.append("prediction_" + name + "_not_false")
        if declared == "generated":
            if value.get("reason") is not None:
                shape.append("generated_reason_nonnull")
            ids = value.get("generated_ids")
            if content and type(ids) is list:
                _need(len(ids) <= 512, "complete content sequence exceeds 512 IDs; truncation refused")
            valid_ids = type(ids) is list and all(type(token) is int and
                (-(1 << 63) < token < (1 << 63) if content else -(1 << 31) <= token < (1 << 31)) for token in ids)
            if not valid_ids:
                shape.append("generated_ids_plain_int63_list_required" if content else "generated_ids_plain_int32_list_required")
            elif not _is_sha(value.get("generated_ids_sha256")):
                shape.append("generated_ids_sha256_invalid")
            elif _digest(ids, MAX_PREDICTIONS_BYTES) != value["generated_ids_sha256"]:
                shape.append("generated_ids_sha256_mismatch")
            else:
                # Identity/provenance/duplicate failures do not erase the byte
                # observations. Mechanical decoding supplies no credit for them.
                decodable_ids = list(ids)
            if content:
                text, expected = value.get("content_context_utf8"), value.get("content_context_sha256")
                raw = text.encode("utf-8") if type(text) is str else None
                if raw is not None:
                    _need(0 < len(raw) <= MAX_REQUEST_BYTES, "complete content context byte bound exceeded")
                if type(text) is not str or not _is_sha(expected):
                    shape.append("content_context_bytes_and_sha256_required")
                    decodable_ids = None
                else:
                    _need(hashlib.sha256(raw).hexdigest() == expected, "independent content context pin differs")
                if value.get("content_context_origin") not in _CONTENT_CONTEXT_ORIGINS:
                    shape.append("content_context_origin_invalid")
                    decodable_ids = None
                elif (value["content_context_origin"] == "target_derived_label" and
                      content_generation_kind == "decoder_declared"):
                    provenance.append("decoder_declared_target_derived_context")
        elif declared in _COMPACT_DECLARED_ONLY:
            if value.get("generated_ids") is not None or value.get("generated_ids_sha256") is not None:
                shape.append("declared_nonoutput_contains_generated_ids")
            if not _text(value.get("reason"), 512):
                shape.append("declared_nonoutput_reason_required")
            if content and any(value.get(key) is not None for key in _CONTENT_CONTEXT_FIELDS):
                shape.append("declared_nonoutput_contains_content_context")
        else:
            shape.append("prediction_status_invalid")
    if generation_issues:
        provenance.append("generation_declaration_invalid")
    row["shape_valid"], row["provenance_valid"] = not shape, not provenance
    return row, decodable_ids, False


def _preflight(population_raw, references_raw, predictions_raw, population_sha, references_sha, predictions_sha,
               *, compact=False, content=False):
    budget = [MAX_JSON_NODES]
    population = _transport(population_raw, population_sha, MAX_POPULATION_BYTES, budget)
    references = _transport(references_raw, references_sha, MAX_REFERENCES_BYTES, budget)
    predictions = _transport(predictions_raw, predictions_sha, MAX_PREDICTIONS_BYTES, budget)
    _need(type(population) is dict and set(population) == {"schema", "partition", "selection_sha256", "rows"}
          and population["schema"] == "legal-relational-batch-population/v1"
          and _text(population["partition"], 128) and _is_sha(population["selection_sha256"])
          and type(population["rows"]) is list and 1 <= len(population["rows"]) <= MAX_POPULATION_ROWS,
          "closed nonempty bounded population required")
    by_id = {}
    for index, row in enumerate(population["rows"]):
        _need(type(row) is dict and set(row) == {"id", "source_sha256", "context_sha256"}
              and _text(row["id"], 256) and _is_sha(row["source_sha256"]) and _is_sha(row["context_sha256"])
              and row["id"] not in by_id, "unique closed population occurrence required")
        by_id[row["id"]] = index
    _need(type(references) is dict and set(references) == {"schema", "population_sha256", "rows"}
          and references["schema"] == "legal-relational-batch-references/v1"
          and references["population_sha256"] == population_sha and type(references["rows"]) is list
          and len(references["rows"]) == len(by_id), "complete population-bound references required")
    for reference, identity in zip(references["rows"], by_id):
        _reference(reference, identity)
    extra = {"codec", "codec_sha256"} if compact or content else set()
    schema = CONTENT_PREDICTIONS_SCHEMA if content else COMPACT_PREDICTIONS_SCHEMA if compact else "legal-relational-batch-predictions/v1"
    _need(type(predictions) is dict and set(predictions) in (
              {"schema", "generation", "rows"} | extra, {"schema", "rows"} | extra)
          and predictions["schema"] == schema
          and type(predictions["rows"]) is list and len(predictions["rows"]) <= MAX_OBSERVATIONS,
          "closed bounded predictions envelope required")
    if compact or content:
        _need(type(predictions["codec"]) is dict and _is_sha(predictions["codec_sha256"])
              and _digest(predictions["codec"], 32768) == predictions["codec_sha256"],
              "independently bound complete compact codec required")
    generation, issues = _generation(predictions, population_sha)
    observe = _compact_observation if compact or content else _observation
    observations = [observe(value, i, by_id, population["rows"], issues,
                    **({"content": True, "content_generation_kind": generation["kind"]} if content else {}))
                    for i, value in enumerate(predictions["rows"])]
    return population, references, predictions, generation, issues, observations


def _owners():
    from . import legal_relational_norm_v1, legal_relational_reconstruction_v1, legal_family_routes
    from .. import syntax_core, parsers
    from ..syntax_core import ast, algebra, contracts, signatures, diagnostics, lexer, registry
    from ..families import namespaces
    from ..parsers import legacy_modal, modal, event_calculus
    from ..TDFOL import tdfol_core
    from ..intent_ir.formalize import modal_projections
    # families is a natural namespace with no source file; its concrete
    # namespaces.py owner below is fenced without inventing a package file.
    modules = (legal_relational_norm_v1, legal_relational_reconstruction_v1, legal_family_routes,
               syntax_core, parsers, ast, algebra, contracts, signatures,
               diagnostics, lexer, registry, namespaces, legacy_modal, modal,
               event_calculus, tdfol_core, modal_projections)
    return legal_relational_norm_v1, legal_relational_reconstruction_v1, legal_family_routes, modules


def _snapshot(path):
    _need(type(path) is Path or isinstance(path, Path), "trusted fixed source path required")
    _need(path.is_absolute(), "absolute trusted fixed source required")
    for parent in (path.parent, *path.parent.parents):
        _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased trusted source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES,
              "bounded regular trusted source required")
        raw = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
          "trusted source changed during snapshot")
    return hashlib.sha256(raw).hexdigest(), identity(before)


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)
_SELF_PIN = _SELF_SNAPSHOT[0]


def _trusted_sources(owners):
    global _OPERATION_SNAPSHOTS
    paths = {_SELF_PATH}
    for module in owners[3]:
        _need(type(module.__file__) is str, "trusted module source required")
        paths.add(Path(module.__file__))
    try:
        closure = owners[2].producer_pins()
    except ValueError:
        raise RelationalBatchEvaluationError("trusted native producer closure changed") from None
    _need(type(closure) is dict and len(closure) <= 128, "bounded trusted native closure required")
    for path, expected in closure.items():
        _need(type(path) is str and Path(path).is_absolute() and _is_sha(expected),
              "trusted native closure identity required")
        paths.add(Path(path))
    snapshots = {str(path): _snapshot(path) for path in sorted(paths, key=str)}
    pins = {path: observation[0] for path, observation in snapshots.items()}
    _need(pins[str(_SELF_PATH)] == _SELF_PIN, "batch owner changed since import")
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "batch owner physical identity changed since import")
    _need(all(pins[path] == expected for path, expected in closure.items()), "trusted native closure pin differs")
    # These fixed owners expose import anchors and lazily captured source maps.
    # Check their state before the candidate ValueError boundary: an old loaded
    # owner must not turn source drift into an invalid-output observation.
    # No private helper or path named by an offered artifact is used here.
    for module, cache_name in ((owners[0], "_OWNER_PINS"), (owners[1], "_OPERATION_PINS")):
        _need(module._SELF_PIN == pins[str(Path(module.__file__))],
              "trusted relational owner import anchor differs from current source")
        cached = getattr(module, cache_name)
        _need(cached is None or (type(cached) is dict and cached.items() <= pins.items()),
              "trusted relational owner cached source identity differs")
    if _OPERATION_SNAPSHOTS is None:
        _OPERATION_SNAPSHOTS = dict(snapshots)
    _need(snapshots == _OPERATION_SNAPSHOTS, "trusted source physical identity or bytes changed since first use")
    return pins, snapshots


def _owned_report(report, pins):
    _need(type(report) is dict and type(report.get("producer_pins")) is dict
          and report["producer_pins"].items() <= pins.items(), "replayed report differs from trusted fixed closure")


def _compact_owners():
    from ..formalization.autoencoder import legal_relational_compact_codec_v1 as compact
    from ..formalization.autoencoder import legal_relational_target_codec_v1 as original
    directory = _SELF_PATH.parents[1] / "formalization" / "autoencoder"
    for module, filename in ((compact, "legal_relational_compact_codec_v1.py"),
                             (original, "legal_relational_target_codec_v1.py")):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == directory / filename,
              "canonical compact/original codec module origin required")
    return compact, original


def _compact_sources(modules):
    """Fence fixed codec dependencies separately from the unchanged v1 cache."""
    global _COMPACT_OPERATION_SNAPSHOTS
    compact, original = modules
    root = _SELF_PATH.parents[3]
    _need(type(original._SOURCE_RELS) is tuple and 0 < len(original._SOURCE_RELS) <= 64,
          "bounded trusted original codec closure required")
    paths = {Path(compact.__file__).absolute(), Path(original.__file__).absolute()}
    # Only the actual, source-pinned original owner's fixed closure names can
    # nominate reads. Offered reports and codec metadata cannot add paths.
    for relative in original._SOURCE_RELS:
        _need(type(relative) is str and relative.startswith("ipfs_datasets_py/") and
              not Path(relative).is_absolute() and ".." not in Path(relative).parts and relative.endswith(".py"),
              "trusted canonical codec dependency path required")
        paths.add(root / relative)
    snapshots = {str(path): _snapshot(path) for path in sorted(paths, key=str)}
    pins = {path: item[0] for path, item in snapshots.items()}
    for module in modules:
        path = str(Path(module.__file__).absolute())
        _need(module._SELF_SNAPSHOT[0] == pins[path], "codec import anchor differs from current source")
    # Preserve the original codec's existing physical anchor and lazy closure.
    def original_witness(snapshot):
        digest, value = snapshot
        return digest, (value[0], value[1], value[2], value[6], value[3], value[4], value[5])
    _need(original._SELF_SNAPSHOT == original_witness(snapshots[str(Path(original.__file__).absolute())]),
          "original codec physical import anchor differs")
    compact_snapshot = snapshots[str(Path(compact.__file__).absolute())]
    value = compact_snapshot[1]
    _need(compact._SELF_SNAPSHOT == (compact_snapshot[0], (value[0], value[1], value[3], value[4], value[5])),
          "compact codec physical import anchor differs")
    cached = original._SOURCE_BASELINE
    _need(cached is None or (type(cached) is dict and all(
        path in snapshots and observation == original_witness(snapshots[path]) for path, observation in cached.items())),
        "original codec cached source custody differs")
    if _COMPACT_OPERATION_SNAPSHOTS is None:
        _COMPACT_OPERATION_SNAPSHOTS = dict(snapshots)
    _need(snapshots == _COMPACT_OPERATION_SNAPSHOTS, "compact dependency physical identity or bytes changed")
    return pins, snapshots


def _decode_compact_observations(observations, predictions, modules, pins, fence):
    """Mechanical candidate intake receives no population reference or target."""
    compact = modules[0]
    retained_fields = ("schema", "profile", "format", "codec_sha256", "status", "reason", "framing",
        "generated_transport_utf8", "generated_transport_hex", "generated_transport_sha256",
        "generated_transport_bytes", "canonical_request_sha256", "canonical_request_bytes",
        "owner_codec_sha256", "relational_owner_report_sha256", "typed_expression_codec_sha256")
    output = []
    for row, ids, _ in observations:
        request_raw = None
        if ids is not None:
            fence()
            # No catch: source/owner errors, complete-bound failures and
            # interruption are operational refusals, never model outcomes.
            checked = compact.decode_relational_compact_candidate_v1(ids,
                codec=predictions["codec"], expected_codec_sha256=predictions["codec_sha256"])
            fence()
            _owned_report(checked, pins)
            _need(checked["generated_ids"] == ids, "compact intake changed original generated IDs")
            status, reason = checked["status"], checked["reason"]
            _need((status == "valid_candidate" and reason is None) or
                  (status == "incomplete" and reason in ("missing_bos_and_eos", "missing_eos")) or
                  (status == "rejected" and reason in _COMPACT_REJECTION_STATUSES),
                  "unsupported compact intake disposition")
            row["compact_decoding"] = {key: checked[key] for key in retained_fields}
            row["compact_decoding"]["report_sha256"] = _digest(checked, MAX_REPORT_BYTES)
            if status == "valid_candidate":
                request_raw = checked["canonical_request_raw_utf8"].encode("utf-8")
                _need(0 < len(request_raw) <= MAX_REQUEST_BYTES and len(request_raw) == checked["canonical_request_bytes"]
                      and hashlib.sha256(request_raw).hexdigest() == checked["canonical_request_sha256"],
                      "compact reconstructed request commitment differs")
        output.append((row, request_raw, False))
    return output


def _content_direct_sources():
    """Fence the two reviewed canonical owners before their lazy imports."""
    root = _SELF_PATH.parents[2]
    snapshots = {}
    for relative, expected in _CONTENT_DIRECT_SPECS:
        path = root / relative
        snapshots[str(path)] = _snapshot(path)
        _need(snapshots[str(path)][0] == expected,
              "fixed content source generation differs")
    return snapshots


def _content_owners():
    before = _content_direct_sources()
    from ..formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
    from . import legal_compact_content_v1 as content
    for module, path in ((tokens, _SELF_PATH.parents[1] / "formalization" / "autoencoder" /
                           "legal_compact_content_tokens_v1.py"),
                         (content, _SELF_PATH.with_name("legal_compact_content_v1.py"))):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == path,
              "canonical content token/AST owner module origin required")
    _need(_content_direct_sources() == before,
          "content owner source changed during lazy import")
    return tokens, content


def _content_sources(modules, core_pins):
    """Use only actual fixed owner dependencies; leave both prior caches intact."""
    global _CONTENT_OPERATION_SNAPSHOTS
    tokens, content = modules
    snapshots = {str(Path(module.__file__).absolute()): _snapshot(Path(module.__file__).absolute())
                 for module in modules}
    _need(snapshots == _content_direct_sources(),
          "canonical content sources differ from fixed reviewed generation")
    pins = {path: snapshot[0] for path, snapshot in snapshots.items()}
    for module in modules:
        _need(module._SELF_SHA == pins[str(Path(module.__file__).absolute())],
              "content owner import anchor differs from current source")
    _need(tokens._OWNER_SHA == content._SELF_SHA, "token owner's fixed content generation differs")
    _need(type(content._OWNER_SPECS) is tuple and 0 < len(content._OWNER_SPECS) <= 16,
          "bounded fixed content dependency declaration required")
    for spec in content._OWNER_SPECS:
        _need(type(spec) is tuple and len(spec) == 3, "fixed content owner spec required")
        name, relative, expected = spec
        _need(type(name) is str and name.startswith("ipfs_datasets_py.logic.") and
              type(relative) is str and relative.startswith("logic/") and
              not Path(relative).is_absolute() and ".." not in Path(relative).parts and _is_sha(expected),
              "canonical fixed content dependency required")
        path = str(_SELF_PATH.parents[2] / relative)
        _need(path in core_pins and core_pins[path] == expected,
              "content dependency differs from trusted core owner generation")
    if _CONTENT_OPERATION_SNAPSHOTS is None:
        _CONTENT_OPERATION_SNAPSHOTS = dict(snapshots)
    _need(snapshots == _CONTENT_OPERATION_SNAPSHOTS, "content dependency physical identity or bytes changed")
    return pins, snapshots


def _content_report_pins(report, pins, states):
    """Verify the complete known producer population without reading offered paths."""
    _need(type(report) is dict and type(report.get("owner_pins")) is list and
          0 < len(report["owner_pins"]) <= 16, "bounded content owner source records required")
    root = _SELF_PATH.parents[2]
    if report.get("schema") in ("legal-compact-content-token-prefix/v1", "legal-compact-content-token-candidate/v1"):
        expected = {str(root / relative) for relative, _ in _CONTENT_DIRECT_SPECS}
    else:
        _need(report.get("schema") == "legal-relational-compact-prediction/v1",
              "known public content report schema required")
        expected = {str(root / relative) for relative in _CONTENT_PREDICTION_SOURCE_RELS}
    seen = set()
    for row in report["owner_pins"]:
        _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"} and
              type(row["path"]) is str and row["path"] not in seen and row["path"] in pins and
              row["path"] in states and pins[row["path"]] == row["sha256"] and
              type(row["bytes"]) is int and row["bytes"] == states[row["path"]][1][3],
              "content report differs from trusted fixed source closure")
        seen.add(row["path"])
    _need(seen == expected, "complete public content producer population differs")
    _need(type(report.get("authority")) is dict and bool(report["authority"])
          and all(value is False for value in report["authority"].values())
          and type(report.get("training_mask")) is int and report["training_mask"] == 0
          and type(report.get("evaluation_gold_mask")) is int and report["evaluation_gold_mask"] == 0,
          "unreviewed content output authority or masks differ")


def _decode_content_observations(observations, predictions, modules, pins, states, fence):
    """Decode supplied context independently of metric references and archival IDs."""
    tokens, content = modules
    output = []
    for row, ids, _ in observations:
        request_raw = None
        if ids is not None:
            offered = row["raw_observation"]
            context_raw = offered["content_context_utf8"].encode("utf-8")
            fence()
            # No catch: actual owner/source/bound failures and interruption are
            # operational refusals, never fabricated model rejection outcomes.
            checked = tokens.decode_compact_content_tokens_v1(ids, context_raw,
                expected_context_sha256=offered["content_context_sha256"],
                codec=predictions["codec"], expected_codec_sha256=predictions["codec_sha256"])
            fence()
            _content_report_pins(checked, pins, states)
            # The public owner already validated the original context JSON.
            # Canonicalize those exact offered bytes, not a returned target or
            # reference-derived replacement, to bind its canonical commitment.
            canonical_context_raw = _wire(json.loads(context_raw), MAX_REQUEST_BYTES)
            canonical_context_sha = hashlib.sha256(canonical_context_raw).hexdigest()
            _need(checked["generated_ids"] == ids
                  and checked["context_raw_sha256"] == offered["content_context_sha256"]
                  and checked["context_sha256"] == canonical_context_sha
                  and checked["codec_sha256"] == predictions["codec_sha256"],
                  "content decoder input commitments differ")
            text = checked["generated_content_raw_utf8"]
            if text is None:
                _need(checked["generated_content_hex"] is checked["generated_content_sha256"] is None,
                      "unrecoverable content cannot claim byte commitments")
            else:
                _need(type(text) is str, "recoverable content must be UTF8 text")
                raw_content = text.encode("utf-8")
                _need(checked["generated_content_hex"] == raw_content.hex()
                      and checked["generated_content_sha256"] == hashlib.sha256(raw_content).hexdigest(),
                      "generated content byte commitments differ")
            status, reason = checked["status"], checked["reason"]
            _need((status == "valid_candidate" and reason is None) or
                  (status == "incomplete" and reason in ("missing_bos_and_eos", "missing_eos")) or
                  (status == "rejected" and reason in _CONTENT_REJECTION_STATUSES),
                  "unsupported content-token intake disposition")
            if status == "valid_candidate":
                prediction = checked["prediction"]
                _content_report_pins(prediction, pins, states)
                _need(prediction["identity_mode"] == "generated"
                      and _wire(prediction["content"], 262144).decode("utf-8") == text
                      and prediction["content_sha256"] == checked["generated_content_sha256"]
                      == _digest(prediction["content"], 262144)
                      and prediction["context_sha256"] == canonical_context_sha
                      == _digest(prediction["context"], MAX_REQUEST_BYTES)
                      and prediction["counts"] == checked["counts"],
                      "nested content prediction commitments or fresh identity differ")
                fence()
                replayed = content.decode_prediction_v1(raw_content, canonical_context_raw,
                    expected_content_sha256=checked["generated_content_sha256"],
                    expected_context_sha256=canonical_context_sha)
                fence()
                _content_report_pins(replayed, pins, states)
                _need(_wire(replayed, MAX_REPORT_BYTES) == _wire(prediction, MAX_REPORT_BYTES),
                      "nested content prediction differs from target-free public replay")
                request_raw = _wire(prediction["request"], MAX_REQUEST_BYTES)
                _need(hashlib.sha256(request_raw).hexdigest() == prediction["request_sha256"],
                      "content reconstructed request commitment differs")
            else:
                _need(checked["prediction"] is None, "nonvalid content cannot contain a reconstructed prediction")
            row["content_decoding"] = _copy(checked, MAX_REPORT_BYTES)
            row["content_decoding_sha256"] = _digest(checked, MAX_REPORT_BYTES)
        output.append((row, request_raw, False))
    return output


def _pair_diagnostic(pair, paired):
    _wire(pair, MAX_PAIR_BYTES)
    comparisons = pair["comparisons"]
    _need(type(comparisons) is dict and set(comparisons) == set(COMPARISON_FIELDS)
          and all(type(value) is bool for value in comparisons.values()), "complete public pair diagnostics required")
    counts = {"total": len(pair["feature_ledger"]), "shared": 0, "reference_only": 0, "candidate_only": 0}
    for row in pair["feature_ledger"]:
        presence = row["presence"]
        _need(presence in ("both", "reference_only", "candidate_only"), "public pair feature presence differs")
        counts["shared" if presence == "both" else presence] += 1
    return {"comparison_sha256": paired.relational_reconstruction_comparison_sha256(pair),
        "comparisons": dict(comparisons), "feature_counts": counts,
        "reference_only_paths": list(pair["reference_only_paths"]),
        "candidate_only_paths": list(pair["candidate_only_paths"])}


def _fraction(matched, total):
    return {"matched": matched, "total": total, "fraction": matched / total if total else None}


def prepare_relational_batch_evaluation_v1(population_raw, references_raw, predictions_raw, *,
        expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Account for every expected occurrence and submitted declared observation."""
    return _prepare_batch(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256, compact=False)


def prepare_relational_compact_batch_evaluation_v1(population_raw, references_raw, predictions_raw, *,
        expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Account for raw compact IDs through the existing population/comparison loop."""
    return _prepare_batch(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256, compact=True)


def prepare_relational_content_token_batch_evaluation_v1(population_raw, references_raw, predictions_raw, *,
        expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Account for context-bound content tokens; supplied context is unverified."""
    return _prepare_batch(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256, compact=False, content=True)


def _prepare_batch(population_raw, references_raw, predictions_raw, *, expected_population_sha256,
                   expected_references_sha256, expected_predictions_sha256, compact, content=False):
    _need(not (compact and content), "one explicit generated-output profile required")
    population, references, predictions, generation, issues, observations = _preflight(
        population_raw, references_raw, predictions_raw, expected_population_sha256,
        expected_references_sha256, expected_predictions_sha256, compact=compact, content=content)
    originals = ((population, MAX_POPULATION_BYTES), (references, MAX_REFERENCES_BYTES),
                 (predictions, MAX_PREDICTIONS_BYTES))
    tokens = tuple(_digest(value, bound) for value, bound in originals)
    owners = _owners()
    relational, paired, _, _ = owners
    core_pins, initial = _trusted_sources(owners)
    pins = dict(core_pins)
    compact_modules, compact_initial, compact_pins = None, None, None
    content_modules, content_initial, content_pins = None, None, None
    if compact:
        compact_modules = _compact_owners()
        compact_pins, compact_initial = _compact_sources(compact_modules)
        _need(all(path not in pins or pins[path] == digest for path, digest in compact_pins.items()),
              "shared compact/core source identities differ")
        pins.update(compact_pins)
        _need(compact_modules[0].relational_compact_codec_sha256(predictions["codec"]) == predictions["codec_sha256"],
              "fixed compact codec differs")
    if content:
        content_modules = _content_owners()
        content_pins, content_initial = _content_sources(content_modules, core_pins)
        _need(all(path not in pins or pins[path] == digest for path, digest in content_pins.items()),
              "shared content/core source identities differ")
        pins.update(content_pins)
        _need(content_modules[0].compact_content_token_codec_sha256(predictions["codec"]) == predictions["codec_sha256"],
              "fixed content-token codec differs")

    def fence():
        _need(tuple(_digest(value, bound) for value, bound in originals) == tokens,
              "detached original batch inputs changed")
        current_pins, snapshots = _trusted_sources(owners)
        _need(snapshots == initial and current_pins == core_pins, "trusted operation sources changed during evaluation")
        if compact:
            current_extra, current_extra_snapshots = _compact_sources(compact_modules)
            _need(current_extra == compact_pins and current_extra_snapshots == compact_initial,
                  "compact operation sources changed during evaluation")
        if content:
            current_extra, current_extra_snapshots = _content_sources(content_modules, core_pins)
            _need(current_extra == content_pins and current_extra_snapshots == content_initial,
                  "content operation sources changed during evaluation")

    fence()
    # Reference failure is an asset error even if its observation is absent.
    for reference in references["rows"]:
        if reference["status"] == "available":
            try:
                checked = relational.validate_relational_norm_v1(reference["report"],
                    reference["request_utf8"].encode("utf-8"), expected_request_sha256=reference["request_sha256"],
                    expected_report_sha256=reference["report_sha256"])
            except ValueError:
                fence()
                raise RelationalBatchEvaluationError("available original reference replay refused") from None
            fence()
            _need(checked == reference["report"], "reference replay changed original report")
            _owned_report(checked, pins)
            del checked
    if compact:
        observations = _decode_compact_observations(observations, predictions, compact_modules, pins, fence)
    if content:
        content_states = {**initial, **content_initial}
        observations = _decode_content_observations(observations, predictions, content_modules, pins, content_states, fence)
    by_id, unidentified = {}, []
    for row, _, _ in observations:
        if row["id"] is None:
            unidentified.append(row["index"])
            row["outcome"] = "unidentifiable"
        else:
            by_id.setdefault(row["id"], []).append(row["index"])
    expected_ids = [row["id"] for row in population["rows"]]
    missing = [identity for identity in expected_ids if identity not in by_id]
    duplicate = {identity: by_id[identity] for identity in expected_ids if len(by_id.get(identity, [])) > 1}
    unexpected = {identity: indices for identity, indices in by_id.items() if identity not in expected_ids}
    for indices in unexpected.values():
        for index in indices:
            observations[index][0]["outcome"] = "unexpected"
    count = len(expected_ids)
    terminal = dict.fromkeys(CONTENT_TERMINAL_STATUSES if content else
                            COMPACT_TERMINAL_STATUSES if compact else TERMINAL_STATUSES, 0)
    matched = dict.fromkeys(COMPARISON_FIELDS, 0)
    occurrences = []
    # Keep only compact summaries, never all complete candidate/pair reports.
    retained_output_bytes = 0
    for index, source in enumerate(population["rows"]):
        reference = references["rows"][index]
        indices = list(by_id.get(source["id"], []))
        occurrence = {"index": index, **source, "reference": {key: reference[key] for key in
            ("status", "request_sha256", "report_sha256", "reason")}, "observation_indices": indices,
            "declared_status": None, "status": None, "reasons": [], "pair_diagnostic": None}
        status, reasons = None, []
        if not indices:
            status, reasons = "missing", ["missing_prediction"]
        elif len(indices) > 1:
            status, reasons = "duplicate", ["duplicate_prediction_id"]
        else:
            submitted, request_raw, overflow = observations[indices[0]]
            occurrence["declared_status"] = submitted["declared_status"]
            if not submitted["shape_valid"]:
                status, reasons = "malformed", list(submitted["shape_reasons"])
            elif not submitted["provenance_valid"]:
                status, reasons = "unverifiable_generation", list(submitted["provenance_reasons"])
            elif submitted["declared_status"] in (_COMPACT_DECLARED_ONLY if compact or content else ("abstained", "unsupported")):
                status = submitted["declared_status"]
                reasons = ["declared_" + status]
            elif compact and submitted["compact_decoding"]["status"] != "valid_candidate":
                decoded = submitted["compact_decoding"]
                status = "incomplete" if decoded["status"] == "incomplete" else _COMPACT_REJECTION_STATUSES[decoded["reason"]]
                reasons = [decoded["reason"]]
            elif content and submitted["content_decoding"]["status"] != "valid_candidate":
                decoded = submitted["content_decoding"]
                status = "incomplete" if decoded["status"] == "incomplete" else _CONTENT_REJECTION_STATUSES[decoded["reason"]]
                reasons = [decoded["reason"]]
            elif overflow:
                status, reasons = "invalid_typed_output", ["candidate_request_bound_exceeded"]
            else:
                prediction = predictions["rows"][indices[0]]
                request_sha = hashlib.sha256(request_raw).hexdigest() if compact or content else prediction["request_sha256"]
                fence()
                try:
                    candidate = relational.prepare_relational_norm_v1(request_raw,
                        expected_request_sha256=request_sha)
                except ValueError:
                    fence()
                    if compact or content:
                        raise RelationalBatchEvaluationError("public replay refused an already validated compact candidate") from None
                    status, reasons = "invalid_typed_output", ["candidate_relational_preparation_rejected"]
                else:
                    fence()
                    candidate_sha = relational.relational_norm_report_sha256(candidate)
                    validated = relational.validate_relational_norm_v1(candidate, request_raw,
                        expected_request_sha256=request_sha, expected_report_sha256=candidate_sha)
                    fence()
                    _need(candidate == validated, "candidate public validation changed prepared output")
                    _owned_report(validated, pins)
                    del validated
                    if reference["status"] == "unavailable":
                        status, reasons = "valid_without_reference", ["reference_unavailable"]
                    else:
                        pair = paired.prepare_relational_reconstruction_comparison_v1(reference["report"], candidate,
                            reference_request_raw=reference["request_utf8"].encode("utf-8"), candidate_request_raw=request_raw,
                            expected_reference_request_sha256=reference["request_sha256"],
                            expected_candidate_request_sha256=request_sha,
                            expected_reference_report_sha256=reference["report_sha256"], expected_candidate_report_sha256=candidate_sha)
                        fence()
                        _owned_report(pair, pins)
                        diagnostic = _pair_diagnostic(pair, paired)
                        del pair
                        occurrence["pair_diagnostic"] = diagnostic
                        for name in COMPARISON_FIELDS:
                            matched[name] += int(diagnostic["comparisons"][name])
                        status = "compared"
                    del candidate
        occurrence["status"], occurrence["reasons"] = status, reasons
        terminal[status] += 1
        for observation_index in indices:
            observations[observation_index][0]["outcome"] = status
        retained_output_bytes += len(_wire(occurrence, MAX_OUTPUT_BYTES))
        _need(retained_output_bytes <= MAX_OUTPUT_BYTES, "complete occurrence output bound exceeded")
        occurrences.append(occurrence)
    ledger = [row for row, _, _ in observations]
    _need(sum(terminal.values()) == count and all(row["outcome"] is not None for row in ledger),
          "complete occurrence/observation accounting required")
    _need(sum(len(indices) for indices in by_id.values()) + len(unidentified) == len(ledger),
          "every observation must be retained exactly once")
    available = sum(row["status"] == "available" for row in references["rows"])
    valid = terminal["compared"] + terminal["valid_without_reference"]
    result = {"schema": CONTENT_SCHEMA if content else COMPACT_SCHEMA if compact else SCHEMA,
        "profile": CONTENT_PROFILE if content else COMPACT_PROFILE if compact else PROFILE,
        "status": "full_selected_unreviewed_relational_batch_evaluated",
        "inputs": {name: {"sha256": expected, "bytes": len(raw)} for name, raw, expected in (
            ("population", population_raw, expected_population_sha256), ("references", references_raw, expected_references_sha256),
            ("predictions", predictions_raw, expected_predictions_sha256))},
        "population": {"population_sha256": expected_population_sha256, "partition": population["partition"],
            "selection_sha256": population["selection_sha256"], "ordered_ids": expected_ids},
        "reference_availability": {"available": available, "unavailable": count - available,
            "total": count, "fraction": available / count if count else None},
        "coverage": {"valid": not (missing or duplicate or unexpected or unidentified), "expected_count": count,
            "prediction_row_count": len(ledger), "missing_ids": missing, "duplicate_ids": duplicate,
            "unexpected_ids": unexpected, "unidentifiable_indices": unidentified},
        "observation_ledger": ledger, "occurrences": occurrences, "terminal_counts": terminal,
        "valid_typed_output": {"count": valid, "total": count, "fraction": valid / count if count else None},
        "full_selected_structure_diagnostics": {name: _fraction(matched[name], count) for name in COMPARISON_FIELDS},
        "comparable_pair_structure_diagnostics": {name: _fraction(matched[name], terminal["compared"]) for name in COMPARISON_FIELDS},
        "generation": generation, "generation_issues": issues, "producer_pins": dict(pins),
        "authority": dict(FALSE_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "generation_claims_are_declarations_only": True, "metric_reference_access": True,
        "limitations": [
            "The independently pinned selected population is the denominator; selection, partition and source/context hashes remain unauthenticated caller declarations.",
            "Current comparison scope is exact tdfol/tdfol_default@1.0.0 with source_binding=null and the existing bounded Object-predicate relational fragment; wider logic families are not qualified.",
            "Available references are replayed authored unreviewed declarations, not reviewed statutory gold; unavailable references remain in the denominator.",
            "All observations retain arrival indices and full canonical row hashes; duplicates never select a favorable candidate and unexpected observations never alter the population denominator.",
            "Generation dimension/checkpoint/encoder/settings fields and no-target flags are declarations only; no model, numerical execution, target-withholding or latent-only inference is authenticated.",
            "No decoder inference receipt adapter is supplied. Existing single-rule deontic observation evidence does not establish these typed requests as learned relational decoder outputs.",
            "File snapshots and known owner import anchors do not generally prove executed bytecode for preloaded unanchored modules; a qualified fresh checked-buffer native run supplies that separate execution context.",
            "Candidate lowering and existing public replay are deterministic syntax postprocessing, not model generation or legal-source equivalence.",
            "request_utf8 covers bounded UTF8 text, including malformed candidate JSON; arbitrary nonUTF8 model byte streams are outside this schema and invalid outer UTF8 refuses intake.",
            "Unsupported is an explicit caller abstention category; rejected typed outputs do not establish a syntax-versus-family-capability taxonomy.",
            "Full selected and comparable-pair rates are separate descriptive structural diagnostics; neither is reviewed accuracy or training qualification.",
            "No models, training, native Lake/backend execution, legal review, admission or publication occurs; existing owners may regenerate syntax-only Lean text.",
        ]}
    if compact:
        result["compact_codec"] = {"schema": predictions["codec"]["schema"], "sha256": predictions["codec_sha256"]}
        result["declared_operational_statuses_are_unverified"] = True
        result["limitations"] = [line for line in result["limitations"] if not line.startswith((
            "No decoder inference receipt adapter", "request_utf8 covers", "Unsupported is an explicit"))]
        result["limitations"].extend([
            "Raw compact IDs and codec replay describe offered output bytes, not authenticated numerical generation or provider delivery.",
            "Every offered observation is retained verbatim as ordinary JSON, including malformed, duplicate, unexpected and unidentifiable rows; framing/raw hex is retained where mechanical decoding is available.",
            "Explicit error, timeout, cancellation and not_started are caller-declared outcomes only; actual owner/source/bound errors and interruption refuse the operation without a partial report.",
            "Invalid frames, nonUTF8 bytes, incomplete sequences, invalid compact structures and rejected typed requests remain distinct; no reference repairs generated output.",
            "Shared byte/node/population/observation limits remain unchanged; complete input, expansion or output overflow refuses atomically without dropping rows.",
        ])
    if content:
        result["content_codec"] = {"schema": predictions["codec"]["schema"], "sha256": predictions["codec_sha256"]}
        result["declared_operational_statuses_are_unverified"] = True
        result["content_context_claims_are_declarations_only"] = True
        result["authority"].update(dict.fromkeys(("permitted_inference_context_verified",
            "content_context_origin_verified", "content_context_independence_verified",
            "checkpoint_compatibility_verified"), False))
        result["limitations"] = [line for line in result["limitations"] if not line.startswith((
            "No decoder inference receipt adapter", "request_utf8 covers", "Unsupported is an explicit"))]
        result["limitations"].extend([
            "Raw content tokens are interpreted only with each observation's separately committed signature/ordered-role context; source context_sha256 is a different binding.",
            "Context origin labels are unverified declarations. Authored fixtures and target-derived label contexts do not establish permitted source-only or held-out inference; caller-supplied context is also unverified.",
            "A decoder_declared generation with target_derived_label context contradicts its no-target-access declaration and receives no comparison credit; authored-control transport diagnostics remain conditional.",
            "Every observation and complete available content-decoder/prediction report is retained, including duplicate, unexpected and unidentifiable observations; no favorable observation is selected.",
            "Prediction decoding receives no reference, target identity sidecar or repair map. Content/context generate fresh IDs and binder names; exact identity, declared structure and lexical alpha structure remain distinct diagnostics.",
            "All comparisons are conditional on the supplied unverified vocabulary and ordered roles; the unchanged profile requires every declared predicate to occur and does not qualify broad-catalog selection.",
            "The fixed 537-entry content vocabulary admits at most 512 total IDs including BOS/EOS. This does not qualify a numerical head, checkpoint, target withholding, trained model or provider token savings.",
            "Incomplete, invalid frames, invalid content and exhausted local token budgets remain distinct; invalid UTF8 is not representable by this fixed lexical vocabulary and is not inferred from missing output.",
            "Explicit error, timeout, cancellation and not_started are caller declarations. Actual context, owner, source or full-bound refusal and interruption abort without a partial report.",
            "The complete report retains the unchanged 8MiB bound; no context, prediction, identity or selected occurrence is dropped to fit it. Archival exact restoration and unary definition profiles remain separate owners.",
        ])
    raw = _wire(result, MAX_OUTPUT_BYTES)
    fence()
    return json.loads(raw)


def relational_batch_evaluation_sha256(report):
    """Hash the complete bounded diagnostic; a self-address grants no authority."""
    detached = _copy(report, MAX_OUTPUT_BYTES)
    _need(type(detached) is dict and set(detached) == _OUTPUT_FIELDS
          and detached["schema"] == SCHEMA and detached["profile"] == PROFILE,
          "complete closed relational batch evaluation required")
    return _digest(detached, MAX_OUTPUT_BYTES)


def validate_relational_batch_evaluation_v1(report, population_raw, references_raw, predictions_raw, *,
        expected_evaluation_sha256, expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Require an independent output pin and full original-bound regeneration."""
    _need(_is_sha(expected_evaluation_sha256), "independent complete evaluation SHA256 required")
    offered = _copy(report, MAX_OUTPUT_BYTES)
    _need(relational_batch_evaluation_sha256(offered) == expected_evaluation_sha256,
          "independent complete evaluation pin differs")
    original = _wire(offered, MAX_OUTPUT_BYTES)
    regenerated = prepare_relational_batch_evaluation_v1(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256)
    _need(original == _wire(regenerated, MAX_OUTPUT_BYTES), "evaluation differs from full original-bound regeneration")
    return regenerated


def relational_compact_batch_evaluation_sha256(report):
    """Hash this explicit versioned report without granting generation authority."""
    detached = _copy(report, MAX_OUTPUT_BYTES)
    _need(type(detached) is dict and set(detached) == _OUTPUT_FIELDS | {
        "compact_codec", "declared_operational_statuses_are_unverified"}
        and detached["schema"] == COMPACT_SCHEMA and detached["profile"] == COMPACT_PROFILE,
        "complete closed compact batch evaluation required")
    return _digest(detached, MAX_OUTPUT_BYTES)


def validate_relational_compact_batch_evaluation_v1(report, population_raw, references_raw, predictions_raw, *,
        expected_evaluation_sha256, expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Replay the complete original selected population and raw compact inputs."""
    _need(_is_sha(expected_evaluation_sha256), "independent complete evaluation SHA256 required")
    offered = _copy(report, MAX_OUTPUT_BYTES)
    _need(relational_compact_batch_evaluation_sha256(offered) == expected_evaluation_sha256,
          "independent complete compact evaluation pin differs")
    original = _wire(offered, MAX_OUTPUT_BYTES)
    regenerated = prepare_relational_compact_batch_evaluation_v1(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256)
    _need(original == _wire(regenerated, MAX_OUTPUT_BYTES), "compact evaluation differs from full original-bound regeneration")
    return regenerated


def relational_content_token_batch_evaluation_sha256(report):
    """Commit complete conditional diagnostics without qualifying supplied context."""
    detached = _copy(report, MAX_OUTPUT_BYTES)
    _need(type(detached) is dict and set(detached) == _OUTPUT_FIELDS | {
        "content_codec", "declared_operational_statuses_are_unverified", "content_context_claims_are_declarations_only"}
        and detached["schema"] == CONTENT_SCHEMA and detached["profile"] == CONTENT_PROFILE,
        "complete closed content-token batch evaluation required")
    return _digest(detached, MAX_OUTPUT_BYTES)


def validate_relational_content_token_batch_evaluation_v1(report, population_raw, references_raw, predictions_raw, *,
        expected_evaluation_sha256, expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Replay every original context-bound observation against the full population."""
    _need(_is_sha(expected_evaluation_sha256), "independent complete evaluation SHA256 required")
    offered = _copy(report, MAX_OUTPUT_BYTES)
    _need(relational_content_token_batch_evaluation_sha256(offered) == expected_evaluation_sha256,
          "independent complete content-token evaluation pin differs")
    original = _wire(offered, MAX_OUTPUT_BYTES)
    regenerated = prepare_relational_content_token_batch_evaluation_v1(population_raw, references_raw, predictions_raw,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256)
    _need(original == _wire(regenerated, MAX_OUTPUT_BYTES), "content-token evaluation differs from full original-bound regeneration")
    return regenerated


__all__ = ["RelationalBatchEvaluationError", "prepare_relational_batch_evaluation_v1",
           "relational_batch_evaluation_sha256", "validate_relational_batch_evaluation_v1",
           "prepare_relational_compact_batch_evaluation_v1", "relational_compact_batch_evaluation_sha256",
           "validate_relational_compact_batch_evaluation_v1", "prepare_relational_content_token_batch_evaluation_v1",
           "relational_content_token_batch_evaluation_sha256", "validate_relational_content_token_batch_evaluation_v1"]

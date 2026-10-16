"""Paired valid-input reconstruction diagnostics over existing typed syntax.

Both authored relational reports are independently replayed. Flat path features
describe their declared structure; the shared syntax algebra owns lexical alpha
comparison. No replacement AST, statutory meaning target or accuracy claim is
created. Invalid inputs refuse and are not an evaluated corpus denominator.
Public import uses only the standard library and performs no operation replay.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA = "legal-relational-reconstruction-comparison/v1"
PROFILE = "paired-valid-authored-relational-structure-diagnostics/v1"
MAX_REQUEST_BYTES = 524288
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_NODES = 500000
MAX_JSON_DEPTH = 96
MAX_FEATURE_ROWS = 1024
MAX_LEDGER_ROWS = 2 * MAX_FEATURE_ROWS
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST_FIELDS = {"schema", "interpretation_status", "expression", "argument_roles", "source_binding"}
_OUTPUT_FIELDS = {
    "schema", "profile", "status", "reference", "candidate", "comparisons",
    "signature_diagnostics", "role_diagnostics", "feature_ledger",
    "reference_only_paths", "candidate_only_paths", "valid_input_pair_only",
    "invalid_inputs_refused", "abstention_coverage_evaluated", "producer_pins",
    "authority", "training_mask", "evaluation_gold_mask", "limitations",
}
_FEATURE_FIELDS = (
    "kind", "node_id", "native_path", "symbol", "sort", "ordered_child_paths",
    "binder_paths", "binder_name", "binding_quantifier_path", "quantifier_kind",
    "predicate_symbol", "predicate_typed_path", "predicate_argument_index",
    "declared_argument_role", "argument_roles", "modal_operator",
    "extension_payload_schema", "extension_family", "extension_profile",
    "extension_features", "extension_payload", "modal_ancestry", "connective_ancestry",
)
_LIST_FEATURES = frozenset({"ordered_child_paths", "binder_paths", "argument_roles",
                            "extension_features", "modal_ancestry", "connective_ancestry"})
FALSE_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified", "applicability_verified",
    "governing_use_verified", "independently_reviewed", "accepted", "admitted",
    "semantic_equivalence_verified", "legal_equivalence_verified", "semantic_graph_admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "decoder_accuracy_established", "model_executed", "training_executed", "backend_executed",
    "Lean_admitted", "proof_authority",
), False)
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_OPERATION_PINS = None


class RelationalReconstructionError(ValueError):
    """Independent inputs, existing typed contracts or finite boundaries differ."""


def _need(condition, message):
    if not condition:
        raise RelationalReconstructionError(message)


def _pin(value, label):
    _need(type(value) is str and _SHA.fullmatch(value), "independent SHA256 required: " + label)


def _copy(value, maximum):
    """Detach bounded finite ordinary JSON without invoking supplied objects."""
    remaining, nodes = maximum, MAX_JSON_NODES

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= MAX_JSON_DEPTH, "ordinary input node/depth bound exceeded")
        if type(item) is dict:
            _need(len(item) <= nodes, "ordinary input object bound exceeded")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "ordinary input byte bound exceeded")
            result = {}
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        if type(item) is list:
            _need(len(item) <= nodes, "ordinary input list bound exceeded")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "ordinary input byte bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded ordinary UTF8 string required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise RelationalReconstructionError("valid ordinary UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded ordinary integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
            remaining -= len(repr(item))
        else:
            raise RelationalReconstructionError("ordinary finite JSON required")
        _need(remaining >= 0, "ordinary input byte bound exceeded")
        return item

    return visit(value, 0)


def _wire(value, maximum):
    checked = _copy(value, maximum)
    try:
        raw = json.dumps(checked, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise RelationalReconstructionError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded; truncation refused")
    return raw


def _digest(value, maximum=MAX_OUTPUT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _pairs(entries):
    result = {}
    for key, value in entries:
        _need(key not in result, "duplicate request JSON key refused")
        result[key] = value
    return result


def _request(raw, expected):
    _pin(expected, "request raw bytes")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES, "bounded original request bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent request transport pin differs")
    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(RelationalReconstructionError("finite request JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RelationalReconstructionError("bounded duplicate-free request UTF8 JSON required") from error
    request = _copy(request, MAX_REQUEST_BYTES)
    _wire(request, MAX_REQUEST_BYTES)
    _need(type(request) is dict and set(request) == _REQUEST_FIELDS
          and request["schema"] == "legal-relational-norm-request/v1"
          and request["interpretation_status"] == "authored_unreviewed_declaration"
          and request["source_binding"] is None
          and type(request["expression"]) is dict and type(request["argument_roles"]) is list,
          "closed authored relational request required")
    return request


def _preflight(reference_report, candidate_report, reference_request_raw, candidate_request_raw,
               expected_reference_request_sha256, expected_candidate_request_sha256,
               expected_reference_report_sha256, expected_candidate_report_sha256):
    _pin(expected_reference_report_sha256, "reference full report")
    _pin(expected_candidate_report_sha256, "candidate full report")
    reference = _copy(reference_report, MAX_REPORT_BYTES)
    candidate = _copy(candidate_report, MAX_REPORT_BYTES)
    _need(type(reference) is dict and type(candidate) is dict, "ordinary complete report objects required")
    _need(_digest(reference, MAX_REPORT_BYTES) == expected_reference_report_sha256
          and _digest(candidate, MAX_REPORT_BYTES) == expected_candidate_report_sha256,
          "independent complete report pin differs")
    _request(reference_request_raw, expected_reference_request_sha256)
    _request(candidate_request_raw, expected_candidate_request_sha256)
    return reference, candidate


def _owners():
    # All imports occur only after finite ordinary inputs and independent pins.
    from . import legal_relational_norm_v1, legal_family_routes
    from ..syntax_core import ast, algebra, contracts, signatures
    from ..families import namespaces
    from ..parsers import legacy_modal
    from ..TDFOL import tdfol_core
    from ..intent_ir.formalize import modal_projections
    modules = (legal_relational_norm_v1, legal_family_routes, ast, algebra, contracts,
               signatures, namespaces, legacy_modal, tdfol_core, modal_projections)
    return legal_relational_norm_v1, ast, algebra, legal_family_routes, modules


def _source_pin(path):
    _need(type(path) is Path or isinstance(path, Path), "trusted source path required")
    _need(path.is_absolute(), "absolute trusted source required")
    try:
        for parent in (path.parent, *path.parent.parents):
            _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased trusted source parents required")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular trusted source required")
            raw = stream.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(stream.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
        _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
              "trusted source changed during read")
    except OSError as error:
        raise RelationalReconstructionError("trusted source unavailable") from error
    return hashlib.sha256(raw).hexdigest()


def _trusted_pins(owners):
    global _OPERATION_PINS
    _need(_source_pin(_SELF_PATH) == _SELF_PIN, "reconstruction owner changed since import")
    pins = {str(_SELF_PATH): _SELF_PIN}
    for module in owners[4]:
        path = Path(module.__file__).resolve()
        pins[str(path)] = _source_pin(path)
    # This is the trusted fixed owner's public closure, never an offered map.
    public = owners[3].producer_pins()
    _need(type(public) is dict and len(public) <= 128, "bounded trusted native producer closure required")
    for spelling, expected in public.items():
        _pin(expected, "trusted native producer")
        _need(type(spelling) is str and Path(spelling).is_absolute(), "absolute trusted native producer path required")
        _need(_source_pin(Path(spelling)) == expected, "trusted native producer source differs")
        _need(spelling not in pins or pins[spelling] == expected, "trusted producer pin conflict")
        pins[spelling] = expected
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "reconstruction operation owners changed since first use")
    return pins


def _signature(expression):
    result = _copy(expression.signature.to_dict(), MAX_REQUEST_BYTES)
    del result["signature_id"]
    result["sorts"] = sorted(result["sorts"], key=lambda row: _wire(row, MAX_REQUEST_BYTES))
    result["symbols"] = sorted(result["symbols"], key=lambda row: _wire(row, MAX_REQUEST_BYTES))
    return result


def _roles(report):
    return sorted(_copy(report["argument_roles"], MAX_REQUEST_BYTES), key=lambda row: row["symbol"])


def _resolve(expression, path):
    """Resolve only authoritative existing structural-mapping JSON paths."""
    _need(type(path) is str and path.startswith("/root") and len(path) <= 8192,
          "authoritative typed path required")
    value = expression
    for part in path.split("/")[1:]:
        if type(value) is dict:
            _need(part in value, "authoritative typed path is missing")
            value = value[part]
        elif type(value) is list:
            _need(re.fullmatch(r"0|[1-9][0-9]*", part) is not None and int(part) < len(value),
                  "authoritative typed list path differs")
            value = value[int(part)]
        else:
            raise RelationalReconstructionError("authoritative typed path leaves its existing AST")
    _need(type(value) is dict, "authoritative typed path must identify an existing record")
    return value


def _declared_projection(expression, mapping, signature):
    result = _copy(expression.to_dict(), MAX_REQUEST_BYTES)
    del result["expression_id"]
    del result["content_digest"]
    result["signature"] = signature
    for row in mapping:
        original = _resolve(result, row["typed_path"])
        if row["kind"] != "binder":
            _need(original.get("node_id") == row["node_id"], "projection node identity differs from authoritative mapping")
            del original["node_id"]
    return result


def _features(expression, report):
    """Flat diagnostic facts; the existing AST owns all syntax and typing."""
    mapping = report["structural_mapping"]
    _need(type(mapping) is list and 0 < len(mapping) <= MAX_FEATURE_ROWS,
          "complete finite authoritative mapping required")
    roles = {row["symbol"]: row["roles"] for row in report["argument_roles"]}
    result = []

    def append(path, kind, *, node_id=None, binder_name=None, binder_sort=None,
               modal_ancestry=(), connective_ancestry=(), **facts):
        _need(len(result) < len(mapping), "derived feature population exceeds authoritative mapping")
        original = mapping[len(result)]
        _need(original["typed_path"] == path and original["kind"] == kind,
              "derived typed path order or kind differs from authoritative mapping")
        if kind == "binder":
            _need(original.get("binder_name") == binder_name and original.get("typed_sort") == binder_sort["name"]
                  and original.get("native_sort") is None, "derived binder differs from authoritative mapping")
        else:
            _need(original.get("node_id") == node_id, "derived node ID differs from authoritative mapping")
        row = {key: [] if key in _LIST_FEATURES else None for key in _FEATURE_FIELDS}
        row.update(kind=kind, node_id=node_id, native_path=original["native_path"],
                   modal_ancestry=list(modal_ancestry), connective_ancestry=list(connective_ancestry), **facts)
        if binder_name is not None:
            row.update(binder_name=binder_name, sort=binder_sort)
        result.append({"typed_path": path, "features": row})
        return row

    def visit(node, path, bound, modal_ancestry=(), connective_ancestry=(), argument=None, depth=0):
        _need(depth <= 48, "complete typed feature depth exceeded")
        kind = node.kind.value
        row = append(path, kind, node_id=node.node_id, symbol=node.symbol or None,
                     sort=None if node.sort is None else node.sort.to_dict(),
                     modal_ancestry=modal_ancestry, connective_ancestry=connective_ancestry)
        if kind == "variable":
            _need(node.symbol in bound and argument is not None, "lexically bound predicate argument required")
            binding = bound[node.symbol]
            row.update(binder_name=node.symbol, binding_quantifier_path=binding["quantifier_path"],
                       quantifier_kind=binding["quantifier_kind"], **argument)
        elif kind == "predicate":
            row.update(predicate_symbol=node.symbol, argument_roles=list(roles[node.symbol]),
                       ordered_child_paths=[path + "/arguments/" + str(index) for index in range(len(node.arguments))])
            for index, child in enumerate(node.arguments):
                visit(child, path + "/arguments/" + str(index), bound, modal_ancestry, connective_ancestry,
                      {"predicate_symbol": node.symbol, "predicate_typed_path": path,
                       "predicate_argument_index": index, "declared_argument_role": roles[node.symbol][index]}, depth + 1)
        elif kind in {"forall", "exists"}:
            binder, binder_path, body_path = node.binders[0], path + "/binders/0", path + "/arguments/0"
            row.update(quantifier_kind=kind, binder_paths=[binder_path], ordered_child_paths=[body_path])
            append(binder_path, "binder", binder_name=binder.name, binder_sort=binder.sort.to_dict(),
                   binding_quantifier_path=path, quantifier_kind=kind,
                   modal_ancestry=modal_ancestry, connective_ancestry=connective_ancestry)
            visit(node.arguments[0], body_path,
                  {**bound, binder.name: {"quantifier_path": path, "quantifier_kind": kind}},
                  modal_ancestry, connective_ancestry, depth=depth + 1)
        elif kind == "extension":
            extension = node.extension
            extension_path = path + "/extension"
            child_path = extension_path + "/children/0"
            serialized = extension.to_dict()
            letter = serialized["payload"]["letter"]
            row.update(modal_operator=letter, ordered_child_paths=[extension_path])
            _need(len(result) < len(mapping) and mapping[len(result)].get("operator") == letter,
                  "derived modal operator differs from authoritative mapping")
            append(extension_path, "legacy.deontic/v1", node_id=extension.node_id,
                   sort=None if node.sort is None else node.sort.to_dict(),
                   modal_operator=letter, ordered_child_paths=[child_path],
                   extension_payload_schema=extension.payload_schema,
                   extension_family=serialized["family"], extension_profile=serialized["profile"],
                   extension_features=serialized["features"], extension_payload=serialized["payload"],
                   modal_ancestry=modal_ancestry, connective_ancestry=connective_ancestry)
            visit(extension.children[0], child_path, bound,
                  (*modal_ancestry, {"typed_path": path, "modal_operator": letter}),
                  connective_ancestry, depth=depth + 1)
        elif kind in {"and", "or", "implies", "iff", "not"}:
            row["ordered_child_paths"] = [path + "/arguments/" + str(index) for index in range(len(node.arguments))]
            for index, child in enumerate(node.arguments):
                visit(child, path + "/arguments/" + str(index), bound, modal_ancestry,
                      (*connective_ancestry, {"typed_path": path, "connective_operator": kind,
                                             "argument_index": index}), depth=depth + 1)
        else:
            raise RelationalReconstructionError("existing relational fragment has an unsupported feature kind")

    visit(expression.root, "/root", {})
    _need(len(result) == len(mapping) and len({row["typed_path"] for row in result}) == len(result),
          "complete unique typed feature population differs")
    return result


def _ledger(reference, candidate):
    ref = {row["typed_path"]: row["features"] for row in reference}
    cand = {row["typed_path"]: row["features"] for row in candidate}
    paths = list(ref) + [path for path in cand if path not in ref]
    _need(len(paths) <= MAX_LEDGER_ROWS, "complete path-union bound exceeded")
    result = []
    for path in paths:
        left, right = ref.get(path), cand.get(path)
        present = left is not None and right is not None
        differences = [] if not present else [key for key in _FEATURE_FIELDS if key != "node_id" and left[key] != right[key]]
        identities = [] if not present or left["node_id"] == right["node_id"] else ["node_id"]
        result.append({"typed_path": path,
                       "presence": "both" if present else "reference_only" if left is not None else "candidate_only",
                       "reference": left, "candidate": right,
                       "declared_features_equal": not differences if present else None,
                       "declared_differences": differences, "identity_differences": identities})
    return result, [path for path in ref if path not in cand], [path for path in cand if path not in ref]


def _declaration_diagnostics(reference, candidate, key):
    left = {row[key]: row for row in reference}
    right = {row[key]: row for row in candidate}
    return {"reference": reference, "candidate": candidate,
            "reference_only": [name for name in left if name not in right],
            "candidate_only": [name for name in right if name not in left],
            "different": [name for name in left if name in right and left[name] != right[name]]}


def _reference(report, request_raw, request_sha, report_sha, signature, roles, declared):
    return {"schema": report["schema"], "profile": report["profile"],
            "request_raw_sha256": request_sha, "request_raw_bytes": len(request_raw),
            "report_full_canonical_sha256": report_sha,
            "typed_expression_full_canonical_sha256": _digest(report["typed_expression"], MAX_REQUEST_BYTES),
            "typed_expression_content_digest": report["typed_expression_content_digest"],
            "signature_declarations_sha256": _digest(signature),
            "argument_roles_sha256": _digest(roles),
            "declared_structure_sha256": _digest(declared, MAX_REQUEST_BYTES)}


def prepare_relational_reconstruction_comparison_v1(
        reference_report, candidate_report, *, reference_request_raw, candidate_request_raw,
        expected_reference_request_sha256, expected_candidate_request_sha256,
        expected_reference_report_sha256, expected_candidate_report_sha256):
    """Compare two independently replayed valid declarations, never legal truth."""
    reference, candidate = _preflight(reference_report, candidate_report,
        reference_request_raw, candidate_request_raw, expected_reference_request_sha256,
        expected_candidate_request_sha256, expected_reference_report_sha256, expected_candidate_report_sha256)
    token = (_digest(reference, MAX_REPORT_BYTES), _digest(candidate, MAX_REPORT_BYTES),
             hashlib.sha256(reference_request_raw).hexdigest(), hashlib.sha256(candidate_request_raw).hexdigest())
    owners = _owners()
    relational, ast, algebra, _, _ = owners
    initial_pins = _trusted_pins(owners)

    def fence():
        _need((_digest(reference, MAX_REPORT_BYTES), _digest(candidate, MAX_REPORT_BYTES),
               hashlib.sha256(reference_request_raw).hexdigest(), hashlib.sha256(candidate_request_raw).hexdigest()) == token,
              "detached original comparison inputs changed")
        pins = _trusted_pins(owners)
        _need(pins == initial_pins, "trusted producer sources changed during comparison")
        return pins

    fence()
    checked_reference = relational.validate_relational_norm_v1(reference, reference_request_raw,
        expected_request_sha256=expected_reference_request_sha256,
        expected_report_sha256=expected_reference_report_sha256)
    fence()
    checked_candidate = relational.validate_relational_norm_v1(candidate, candidate_request_raw,
        expected_request_sha256=expected_candidate_request_sha256,
        expected_report_sha256=expected_candidate_report_sha256)
    pins = fence()
    _need(checked_reference == reference and checked_candidate == candidate,
          "public owner replay changed original reports")
    for checked in (checked_reference, checked_candidate):
        _need(type(checked["producer_pins"]) is dict
              and checked["producer_pins"].items() <= pins.items(),
              "replayed original producer closure differs from trusted fixed sources")
    left = ast.TypedExpression.from_dict(checked_reference["typed_expression"])
    right = ast.TypedExpression.from_dict(checked_candidate["typed_expression"])
    _need(left.to_dict() == checked_reference["typed_expression"]
          and right.to_dict() == checked_candidate["typed_expression"],
          "shared typed-expression reconstruction differs")
    left_signature, right_signature = _signature(left), _signature(right)
    left_roles, right_roles = _roles(checked_reference), _roles(checked_candidate)
    left_declared = _declared_projection(left, checked_reference["structural_mapping"], left_signature)
    right_declared = _declared_projection(right, checked_candidate["structural_mapping"], right_signature)
    left_features, right_features = _features(left, checked_reference), _features(right, checked_candidate)
    ledger, missing, unexpected = _ledger(left_features, right_features)
    family_profile_equal = left.to_dict()["family"] == right.to_dict()["family"] and left.to_dict()["profile"] == right.to_dict()["profile"]
    signature_equal, roles_equal = left_signature == right_signature, left_roles == right_roles
    shared_algebra = algebra.LogicExpressionAlgebra(limits=algebra.AlgebraLimits(max_nodes=4096, max_depth=96))
    alpha_equal = shared_algebra.alpha_equivalent(left.root, right.root)
    fence()
    result = {
        "schema": SCHEMA, "profile": PROFILE, "status": "unreviewed_valid_relational_pair_compared",
        "reference": _reference(checked_reference, reference_request_raw, expected_reference_request_sha256,
            expected_reference_report_sha256, left_signature, left_roles, left_declared),
        "candidate": _reference(checked_candidate, candidate_request_raw, expected_candidate_request_sha256,
            expected_candidate_report_sha256, right_signature, right_roles, right_declared),
        "comparisons": {
            "exact_typed_expression_equal": checked_reference["typed_expression"] == checked_candidate["typed_expression"],
            "family_profile_equal": family_profile_equal, "signature_declarations_equal": signature_equal,
            "argument_roles_equal": roles_equal,
            "declared_structure_equal": left_declared == right_declared and roles_equal,
            "lexical_alpha_structure_equal": bool(family_profile_equal and signature_equal and roles_equal and alpha_equal),
        },
        "signature_diagnostics": {
            "reference": left_signature, "candidate": right_signature,
            "predicate_declarations": _declaration_diagnostics(left_signature["symbols"], right_signature["symbols"], "name"),
        },
        "role_diagnostics": _declaration_diagnostics(left_roles, right_roles, "symbol"),
        "feature_ledger": ledger, "reference_only_paths": missing, "candidate_only_paths": unexpected,
        "valid_input_pair_only": True, "invalid_inputs_refused": True, "abstention_coverage_evaluated": False,
        "producer_pins": pins, "authority": dict(FALSE_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": [
            "Both inputs are valid authored declarations replayed under the existing relational profile; invalid or unsupported inputs refuse.",
            "Paired valid inputs do not define corpus validity, malformed-output or abstention coverage; a separate batch evaluator is required.",
            "Exact serialization, ordered declared structure and lexical alpha comparison are different diagnostic outcomes.",
            "Signature declaration ordering and existing expression/node/signature IDs are excluded only from the named declared projection.",
            "Predicate identities, ordered arguments and roles, quantifiers, connective direction, modal placement and extension schema/payload/features remain explicit.",
            "Flat path features describe existing validated syntax; lexical alpha comparison uses the shared bounded algebra, not a replacement AST.",
            "Open subterms are interpreted only within their enclosing validated expression and lexical binder paths, never as independent closed formulas.",
            "The comparison selects no statutory meaning, authenticates no source/reviewer and creates no gold target, accuracy score, admitted graph or theorem.",
            "There are no model, training or native build calls; the existing relational owner may regenerate syntax-only Lean text without executing it.",
        ],
    }
    raw = _wire(result, MAX_OUTPUT_BYTES)
    fence()
    return json.loads(raw)


def relational_reconstruction_comparison_sha256(report):
    """Hash the complete diagnostic; an internally computed hash grants no trust."""
    _need(type(report) is dict and set(report) == _OUTPUT_FIELDS
          and report["schema"] == SCHEMA and report["profile"] == PROFILE,
          "complete closed relational reconstruction comparison required")
    return _digest(report, MAX_OUTPUT_BYTES)


def validate_relational_reconstruction_comparison_v1(report, *args,
        expected_comparison_sha256, **kwargs):
    """Require an independent whole-output pin and exact public-owner replay."""
    _pin(expected_comparison_sha256, "complete comparison")
    _need(relational_reconstruction_comparison_sha256(report) == expected_comparison_sha256,
          "independent complete comparison pin differs")
    offered = _wire(report, MAX_OUTPUT_BYTES)
    expected = prepare_relational_reconstruction_comparison_v1(*args, **kwargs)
    _need(offered == _wire(expected, MAX_OUTPUT_BYTES), "comparison differs from full original-bound regeneration")
    return expected


__all__ = ["RelationalReconstructionError", "prepare_relational_reconstruction_comparison_v1",
           "relational_reconstruction_comparison_sha256", "validate_relational_reconstruction_comparison_v1"]

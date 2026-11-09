"""Lossless bounded SpanCache rows to explicit source-bound graph proposals.

The existing export/grouping helpers default missing statuses to sealed and
coerce malformed rule JSON to an empty object. This intake deliberately consumes
raw SPAN_EXPORT_COLUMNS or legacy rows instead. It retains every field and
presentation, refuses unpinned populations, and leaves pending/gap/unsealed,
unknown status, malformed rules and ambiguous occurrences explicitly unresolved.
No legacy boolean, successful type check, or graph construction grants meaning.
"""
from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re

from . import legal_semantic_graph as graphs
from . import legal_statutory_context as context
from .span_cache import SPAN_EXPORT_COLUMNS
from ..legal_ir.canonical_contracts import CanonicalRoundTripIR

SCHEMA = "legal-span-cache-source-graph-intake/v1"
MAX_ROWS = 128
MAX_ROW_BYTES = 1024 * 1024
MAX_BYTES = 8 * 1024 * 1024
MAX_SELECTORS = 64
MAX_HTML_BYTES = 8_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BINDING_REQUIRED = {"document", "raw_html_base64", "document_revision", "scope", "candidate_selectors"}
_BINDING_OPTIONAL = {"context_observation", "dependency_refs", "evidence_refs"}
_FALSE = {key: False for key in ("source_semantics_verified", "source_authenticity_verified",
    "global_consistency_verified", "context_closure_verified", "reviewed_label", "training_qualified",
    "proof_authority", "admitted", "formalized", "legacy_admission_flags_used")}


class SpanGraphIntakeError(ValueError):
    """The bounded source population or independent custody binding differs."""


def _need(ok, message):
    if not ok:
        raise SpanGraphIntakeError(message)


def _wire(value, maximum=MAX_BYTES):
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        _need(depth <= 40 and count <= 262144, "intake JSON depth/node bound exceeded")
        if type(item) is dict:
            _need(all(type(key) is str for key in item), "plain JSON string keys required at every depth")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):  # Official extractor's class lists are list subclasses.
            for child in item:
                visit(child, depth + 1)
        else:
            _need(item is None or type(item) in (str, bool, int, float), "plain JSON values required without coercion")
            if type(item) is float:
                _need(math.isfinite(item), "finite JSON values required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SpanGraphIntakeError("bounded finite UTF-8 JSON required") from exc
    _need(len(raw) <= maximum, "intake byte bound exceeded; no truncation performed")
    return raw


def _digest(value, maximum=MAX_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _text(value, label):
    _need(type(value) is str and value.strip() and len(value.encode()) <= 2048,
          "bounded nonblank " + label + " required")
    return value


def _cache_identity(value):
    _need(type(value) is dict and set(value) == {"repository", "revision", "artifact_sha256"},
          "closed explicit cache identity required")
    _text(value["repository"], "cache repository")
    _text(value["revision"], "cache revision")
    _need(type(value["artifact_sha256"]) is str and _SHA.fullmatch(value["artifact_sha256"]),
          "immutable cache artifact SHA256 required")
    return deepcopy(value)


def row_sha256(row):
    """Hash the entire inert raw row, including unknown fields and null values."""
    _need(type(row) is dict and all(type(key) is str for key in row), "raw cache row must be a JSON object")
    return _digest(row, MAX_ROW_BYTES)


def record_sha256(row, *, ordinal, cache_identity):
    _need(type(ordinal) is int and ordinal >= 0, "exact physical row ordinal required")
    return _digest({"row_ordinal": ordinal, "raw_row_sha256": row_sha256(row),
                    "cache_identity": _cache_identity(cache_identity)})


def source_bindings_sha256(source_bindings):
    _need(type(source_bindings) is dict and all(type(key) is str for key in source_bindings),
          "source bindings must map exact span IDs to declarations")
    return _digest(source_bindings)


def make_source_binding(document, raw_html, *, document_revision, scope, candidate_selectors,
                        context_observation=None, dependency_refs=(), evidence_refs=()):
    """Make JSON custody input, without choosing among physical occurrences.

    Candidate selectors are supplied independently of the cached rule. They
    must address exact text; no normalization or inferred first match is used.
    Context/evidence remain observations, never resolved legal dependencies.
    """
    _need(type(raw_html) is bytes and 0 < len(raw_html) <= MAX_HTML_BYTES, "bounded raw HTML required")
    result = {"document": document, "raw_html_base64": base64.b64encode(raw_html).decode("ascii"),
              "document_revision": document_revision, "scope": scope,
              "candidate_selectors": candidate_selectors,
              "context_observation": context_observation,
              "dependency_refs": list(dependency_refs), "evidence_refs": list(evidence_refs)}
    return json.loads(_wire(result))


def _strict_rule_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate rule JSON field")
            result[key] = value
        return result

    if type(raw) is dict:
        return json.loads(_wire(raw, MAX_ROW_BYTES))
    _need(type(raw) is str, "rule JSON must be a string or explicit legacy object")
    _need(len(raw.encode()) <= MAX_ROW_BYTES, "rule JSON exceeds row byte bound")
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite rule JSON: " + value)))


def _rule(row):
    """Return original typed structure; never serialize the validator's sorting."""
    channels = []
    for key in ("rule_json", "rule"):
        if key in row and row[key] not in (None, ""):
            channels.append((key, row[key]))
    if not channels:
        return {"status": "missing_rule", "decoded_rule": None, "ast": None, "issues": []}
    decoded = []
    for key, raw in channels:
        try:
            decoded.append((key, _strict_rule_json(raw)))
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            return {"status": "malformed_rule_json", "decoded_rule": None, "ast": None,
                    "issues": [{"code": "malformed_rule_json", "channel": key, "message": str(exc)[:512]}]}
    if len(decoded) > 1 and _wire(decoded[0][1]) != _wire(decoded[1][1]):
        return {"status": "conflicting_rule_channels", "decoded_rule": [value for _, value in decoded],
                "ast": None, "issues": [{"code": "conflicting_rule_channels"}]}
    value = decoded[0][1]
    if type(value) is not dict:
        return {"status": "unsupported_rule_ast", "decoded_rule": value, "ast": None,
                "issues": [{"code": "rule_is_not_an_object"}]}
    ast = deepcopy(value) if set(value) == {"rules"} else {"rules": [deepcopy(value)]}
    try:
        CanonicalRoundTripIR.from_dict(ast)  # Type-only check; do NOT use to_dict().
        graphs.wire(ast)  # Existing graph depth/JSON type constraints, still no projection.
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        return {"status": "unsupported_rule_ast", "decoded_rule": value, "ast": None,
                "issues": [{"code": "canonical_rule_contract_refused", "message": str(exc)[:512]}]}
    return {"status": "typed_unreviewed_rule", "decoded_rule": value, "ast": ast,
            "transport": "canonical_rule_list" if set(value) == {"rules"} else "single_rule_wrapped_once",
            "issues": []}


def _bound_source(row, source_bindings):
    span_id = row.get("source_span_id", row.get("id"))
    if not isinstance(span_id, str) or not span_id.strip():
        return None, None, [{"code": "missing_source_span_identity"}]
    if "id" in row and "source_span_id" in row and row["id"] != row["source_span_id"]:
        return None, None, [{"code": "conflicting_source_span_aliases"}]
    source = row.get("source_text", row.get("text"))
    if type(source) is not str or not source.strip():
        return None, None, [{"code": "missing_exact_source_text"}]
    if "text" in row and "source_text" in row and row["text"] != row["source_text"]:
        return None, None, [{"code": "conflicting_source_text_aliases"}]
    if row.get("source_sha256") != hashlib.sha256(source.encode()).hexdigest():
        return None, None, [{"code": "cached_source_hash_mismatch"}]
    binding = source_bindings.get(span_id)
    if binding is None:
        return None, None, [{"code": "missing_independent_source_binding"}]
    try:
        _need(type(binding) is dict and _BINDING_REQUIRED <= set(binding)
              and set(binding) <= _BINDING_REQUIRED | _BINDING_OPTIONAL, "closed source binding declaration required")
        _text(binding["document_revision"], "document revision")
        for key in ("source_revision", "revision"):
            declared_revision = row.get(key)
            if declared_revision not in (None, ""):
                _need(declared_revision == binding["document_revision"], "cache/source revision differs")
        encoded = binding["raw_html_base64"]
        _need(type(encoded) is str and len(encoded) <= 4 * ((MAX_HTML_BYTES + 2) // 3), "bounded HTML base64 required")
        raw = base64.b64decode(encoded, validate=True)
        _need(0 < len(raw) <= MAX_HTML_BYTES, "raw HTML byte bound exceeded")
        document, scope = binding["document"], binding["scope"]
        _need(type(document) is dict and type(scope) is dict and type(scope.get("edition")) is int
              and scope["edition"] == document.get("edition"), "source scope/document edition differs")
        expected_scope = graphs.bind_scope(**{key: scope[key] for key in (
            "jurisdiction", "instrument", "edition", "applicability", "definition_scope")})
        _need(_wire(scope) == _wire(expected_scope), "source scope identity differs")
        context.normalized_document_view(document, raw)
        if row.get("legal_id") not in (None, ""):
            _need(row["legal_id"] == document["legal_id"], "cache/source legal identity differs")
        candidates = binding["candidate_selectors"]
        _need(type(candidates) is list and len(candidates) <= MAX_SELECTORS, "bounded selector candidate list required")
        matches = []
        for selector in candidates:
            matched = graphs.bind_source_occurrence(document, raw, selector=selector,
                                                     document_revision=binding["document_revision"])
            _need(selector["text"] == source and selector["text_sha256"] == row["source_sha256"],
                  "candidate selector is not exact complete cached source text")
            matches.append(matched)
        if not matches:
            return None, binding, [{"code": "no_exact_physical_occurrence_candidate"}]
        if len(matches) != 1:
            return None, binding, [{"code": "ambiguous_physical_occurrence_candidates",
                                    "occurrence_ids": [m["selector"]["occurrence_id"] for m in matches]}]
        return matches[0], binding, []
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        return None, binding, [{"code": "invalid_independent_source_binding", "message": str(exc)[:512]}]


def _paired_observation(row):
    """Recognize real paired-cache rows without pretending they are flat rules."""
    if row.get("schema_version") not in ("uscode-paired-span-census/v1", "uscode-paired-span-census/v2"):
        return None
    nested = row.get("source")
    projection = ({"source_span_id": nested.get("span_id"), "source_text": nested.get("text"),
                   "source_sha256": nested.get("text_sha256"), "legal_id": nested.get("legal_id"),
                   "source_revision": nested.get("revision")} if type(nested) is dict else {})
    issues = [{"code": "paired_cache_observation_only_no_span_rule_transport"}]
    autoencoder, compiler = row.get("autoencoder"), row.get("compiler")
    autoencoder = autoencoder if type(autoencoder) is dict else {}
    compiler = compiler if type(compiler) is dict else {}
    if any("mock" in str(autoencoder.get(key, "")).casefold() for key in ("model_identity", "embedding_model")):
        issues.append({"code": "mock_or_diagnostic_producer_observation"})
    outputs = autoencoder.get("formal_outputs")
    if type(outputs) is list and any(type(item) is dict and item.get("target_conditioned") is True for item in outputs):
        issues.append({"code": "target_conditioned_formal_output_observation"})
    if compiler.get("canonical_complete") is not True:
        issues.append({"code": "canonical_source_coverage_unverified"})
    return projection, issues


def prepare_span_cache_intake(rows, *, cache_identity, expected_row_sha256s,
                             expected_record_sha256s, source_bindings,
                             expected_source_bindings_sha256, start_ordinal=0):
    """Retain a complete bounded raw-row population and prepare real proposals.

    The expected hash sequences and binding-map digest are independent caller
    inputs. A bad population/pin fails the whole batch. Row-specific malformed
    data is retained with explicit issues. No row is selected out of the result.
    """
    cache_identity = _cache_identity(cache_identity)
    _need(type(start_ordinal) is int and start_ordinal >= 0, "exact starting physical ordinal required")
    _need(type(rows) is list and 0 < len(rows) <= MAX_ROWS, "bounded nonempty cache row batch required")
    for expected in (expected_row_sha256s, expected_record_sha256s):
        _need(isinstance(expected, (list, tuple)) and len(expected) == len(rows)
              and all(type(value) is str and _SHA.fullmatch(value) for value in expected),
              "exact independent ordered row/record hash population required")
    bindings_digest = source_bindings_sha256(source_bindings)
    _need(bindings_digest == expected_source_bindings_sha256, "independent source binding map pin differs")
    actual_rows = [row_sha256(row) for row in rows]
    actual_records = [record_sha256(row, ordinal=start_ordinal + index, cache_identity=cache_identity)
                      for index, row in enumerate(rows)]
    _need(actual_rows == list(expected_row_sha256s) and actual_records == list(expected_record_sha256s),
          "cache row population, order, multiplicity, ordinal or revision differs")
    _wire(rows)
    reports = []
    for index, row in enumerate(rows):
        raw_row = json.loads(_wire(row, MAX_ROW_BYTES))
        paired = _paired_observation(raw_row)
        rule = (_rule(raw_row) if paired is None else {
            "status": "unsupported_paired_observation_transport", "decoded_rule": None, "ast": None,
            "issues": paired[1]})
        source, binding, issues = _bound_source(raw_row if paired is None else paired[0], source_bindings)
        issues = [*rule["issues"], *issues]
        status = raw_row.get("status")
        if status not in ("pending", "gap", "unsealed", "sealed"):
            issues.append({"code": "cache_status_missing" if status in (None, "") else "cache_status_unsupported"})
        elif status != "sealed":
            issues.append({"code": "cache_" + status + "_unresolved"})
        if status == "sealed" and raw_row.get("sealed") is False:
            issues.append({"code": "conflicting_cache_status_flags"})
        if rule["status"] != "typed_unreviewed_rule" and not rule["issues"]:
            issues.append({"code": rule["status"]})
        graph_request, graph = None, None
        if not issues and source is not None and binding is not None:
            graph_request = {"ast": rule["ast"], "profile": "canonical_rules_v1", "source": source,
                             "scope": binding["scope"], "dependency_refs": binding.get("dependency_refs", []),
                             "evidence_refs": binding.get("evidence_refs", [])}
            try:
                graph = graphs.build_graph(**graph_request)
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
                issues.append({"code": "existing_graph_profile_refused", "message": str(exc)[:512]})
                graph_request = None
        reports.append({"row_ordinal": start_ordinal + index, "raw_row": raw_row,
                        "raw_row_sha256": actual_rows[index], "record_sha256": actual_records[index],
                        "record_id": "legal-span-cache-record:sha256:" + actual_records[index],
                        "row_transport": "span_export_or_legacy" if paired is None else raw_row["schema_version"],
                        "cache_status_observation": status, "rule_assessment": rule,
                        "source_binding": source, "source_binding_declaration_sha256": _digest(binding) if binding is not None else None,
                        "context_observation": deepcopy(binding.get("context_observation")) if type(binding) is dict else None,
                        "issues": issues, "disposition": "proposed_unreviewed_graph" if graph else "unresolved",
                        "graph_request": graph_request, "graph": graph, **_FALSE})
    report = {"schema": SCHEMA, "cache_identity": cache_identity, "start_ordinal": start_ordinal,
              "end_ordinal": start_ordinal + len(rows), "row_count": len(rows),
              "expected_row_sha256s": list(expected_row_sha256s), "expected_record_sha256s": list(expected_record_sha256s),
              "source_bindings_sha256": bindings_digest, "rows": reports,
              "disposition_counts": dict(Counter(row["disposition"] for row in reports)),
              "population_complete": True, "coverage_scope": "exact_supplied_raw_cache_row_population_only",
              "source_export_columns": list(SPAN_EXPORT_COLUMNS), "whole_cache_coverage_verified": False, **_FALSE}
    report["intake_sha256"] = _digest(report)
    return json.loads(_wire(report))


def validate_span_cache_intake(report, rows, **trusted_inputs):
    expected = prepare_span_cache_intake(rows, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "span intake differs from independently pinned regeneration")
    return expected


def prepare_entity_cache_graphs(cache, entity_id, rows, **trusted_inputs):
    """Delegate an entire resolved section batch to the existing read-only API.

    Mixed sections, duplicate physical bindings and any unresolved row remain
    an unresolved population. This boundary never keeps a convenient subset.
    The raw-row intake still preserves every presentation and diagnostic.
    """
    report = prepare_span_cache_intake(rows, **trusted_inputs)
    result = {"schema": "legal-span-cache-entity-graph-intake/v1", "intake": report,
              "entity_cache_proposal": None, "disposition": "unresolved_population", **_FALSE}
    if any(row["graph"] is None for row in report["rows"]):
        return result
    bindings = trusted_inputs["source_bindings"]
    sources = [row["source_binding"] for row in report["rows"]]
    scopes = [row["graph_request"]["scope"] for row in report["rows"]]
    if len({(s["view_id"], s["document_revision"]) for s in sources}) != 1 or len({_digest(s) for s in scopes}) != 1:
        result["disposition"] = "unresolved_cross_section_population"
        return result
    span_ids = [row["raw_row"].get("source_span_id", row["raw_row"].get("id")) for row in report["rows"]]
    occurrence_ids = [s["selector"]["occurrence_id"] for s in sources]
    if len(set(span_ids)) != len(span_ids) or len(set(occurrence_ids)) != len(occurrence_ids):
        result["disposition"] = "unresolved_repeated_physical_binding"
        return result
    declaration = bindings[span_ids[0]]
    occurrences, population = [], []
    for row, span_id in zip(report["rows"], span_ids):
        graph_request, selector = row["graph_request"], row["source_binding"]["selector"]
        occurrences.append({"source_span_id": span_id, "source_sha256": selector["text_sha256"],
            "source_text": selector["text"], "selector": selector, "ast": graph_request["ast"],
            "profile": graph_request["profile"], "dependency_refs": graph_request["dependency_refs"],
            "evidence_refs": graph_request["evidence_refs"]})
        population.append({"source_span_id": span_id, "source_sha256": selector["text_sha256"],
                           "occurrence_id": selector["occurrence_id"]})
    result["entity_cache_proposal"] = cache.build_proposed_graphs(entity_id,
        document=declaration["document"], raw_html=base64.b64decode(declaration["raw_html_base64"], validate=True),
        document_revision=declaration["document_revision"], scope=declaration["scope"],
        occurrences=occurrences, expected_population=population)
    result["disposition"] = "proposed_unreviewed_entity_graphs"
    return json.loads(_wire(result))


__all__ = ["SpanGraphIntakeError", "row_sha256", "record_sha256", "source_bindings_sha256",
           "make_source_binding", "prepare_span_cache_intake", "validate_span_cache_intake",
           "prepare_entity_cache_graphs"]


# Explicitly separate coordinate replay from the legacy raw-cache-row profile.
# An independently nominated HTML occurrence is not a coordinate/source crosswalk.
from pathlib import Path as _CoordinateGraphPath

COORDINATE_GRAPH_REQUEST_SCHEMA = "legal-coordinate-source-graph-intake-request/v1"
COORDINATE_GRAPH_SCHEMA = "legal-coordinate-source-graph-intake/v1"
COORDINATE_GRAPH_PROFILE = "paired-coordinate-source-graph-intake/v1"
COORDINATE_GRAPH_REQUEST_SCHEMA_V2 = "legal-coordinate-source-graph-intake-request/v2"
COORDINATE_GRAPH_SCHEMA_V2 = "legal-coordinate-source-graph-intake/v2"
COORDINATE_GRAPH_PROFILE_V2 = "original-input-coordinate-source-graph-intake/v1"
COORDINATE_GRAPH_REQUEST_SCHEMA_V3 = "legal-coordinate-source-graph-intake-request/v3"
COORDINATE_GRAPH_SCHEMA_V3 = "legal-coordinate-source-graph-intake/v3"
COORDINATE_GRAPH_PROFILE_V3 = "original-input-wire-coordinate-source-graph-intake/v1"
COORDINATE_GRAPH_METADATA_PROFILE_V3 = "hf-default-parquet-envelope/v1"
COORDINATE_GRAPH_ELIGIBILITY_REFERENCE_SCHEMA = "legal-coordinate-source-graph-eligibility-reference/v1"
COORDINATE_GRAPH_JOIN_REFERENCE_SCHEMA = "legal-coordinate-source-graph-join-reference/v1"
_COORDINATE_GRAPH_MAX_BYTES = 64 * 1024 * 1024
_COORDINATE_GRAPH_INPUT_BYTES = 16 * 1024 * 1024
_COORDINATE_GRAPH_REQUEST_BYTES = 128 * 1024
_COORDINATE_GRAPH_SELF_PIN = hashlib.sha256(_CoordinateGraphPath(__file__).read_bytes()).hexdigest()
_COORDINATE_GRAPH_OWNER_PINS = None
_COORDINATE_GRAPH_AUTHORITY = {**_FALSE, **dict.fromkeys(("current_source_release_correspondence_verified",
    "coordinate_to_graph_source_correspondence_verified", "historical_occurrence_selected",
    "semantic_review_verified", "evaluation_gold_qualified", "model_executed", "training_executed",
    "Lean_admitted", "published"), False)}


def _coordinate_graph_wire(value, maximum=_COORDINATE_GRAPH_MAX_BYTES):
    from .legal_paired_manifest_inventory_v1 import _wire as ordinary_wire
    return ordinary_wire(value, maximum)


def _coordinate_graph_read(raw, maximum, label):
    from .legal_paired_manifest_inventory_v1 import _read_json
    return _read_json(raw, maximum, label)


def _coordinate_graph_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _coordinate_graph_originals(value):
    """Detach exact public join arguments; no paths, code or opaque objects."""
    fields = {"request_raw", "source_request_raw", "source_metadata_bytes", "paired_inventory_request_raw",
              "paired_manifest_bytes", "entity_info_raw", "expected_request_sha256", "legacy_join_inputs"}
    _need(type(value) is dict and set(value) == fields, "closed coordinate graph join originals required")
    captured, total = {}, 0
    for key in ("request_raw", "source_request_raw", "paired_inventory_request_raw", "entity_info_raw"):
        raw = value[key]
        _need(type(raw) is bytes and 0 < len(raw) <= 256 * 1024, "bounded exact original join bytes required")
        captured[key], total = raw, total + len(raw)
    for key in ("source_metadata_bytes", "paired_manifest_bytes"):
        mapping = value[key]
        _need(type(mapping) is dict and 0 < len(mapping) <= 16, "bounded ordinary original metadata mapping required")
        captured[key] = {}
        for name, raw in mapping.items():
            _need(type(name) is str and 0 < len(name.encode("utf-8")) <= 512 and type(raw) is bytes
                  and 0 < len(raw) <= MAX_BYTES, "bounded exact original metadata names and bytes required")
            captured[key][name], total = raw, total + len(raw)
    _need(total <= MAX_BYTES, "coordinate graph original input aggregate exceeds bound")
    digest, legacy = value["expected_request_sha256"], value["legacy_join_inputs"]
    _need(type(digest) is str and _SHA.fullmatch(digest), "exact original request SHA256 required")
    _need(legacy is None or type(legacy) is dict and not legacy, "coordinate graph cannot mix legacy join inputs")
    captured.update(expected_request_sha256=digest, legacy_join_inputs=None if legacy is None else {})
    return captured


def _coordinate_graph_owners():
    """Pin this profile's graph/source owners beside the eligibility closure."""
    import importlib
    from . import legal_source_span_target_eligibility_v1 as eligibility, tree_pin
    from . import legal_paired_manifest_inventory_v1 as ordinary, span_cache, legal_context_obligations
    root = _CoordinateGraphPath(__file__).resolve().parents[3]
    modules = [graphs, context, eligibility, tree_pin, ordinary, span_cache,
        importlib.import_module(CanonicalRoundTripIR.__module__), graphs.statement_scope,
        legal_context_obligations]
    paths = []
    for module in modules:
        path = _CoordinateGraphPath(module.__file__).resolve()
        expected = root.joinpath(*module.__name__.split(".")).with_suffix(".py")
        _need(path == expected, "coordinate graph owner escaped selected source tree")
        paths.append(path)
    guard_paths = tree_pin.require_workspace_logic_tree()
    paths.extend(_CoordinateGraphPath(path).resolve() for path in guard_paths.values())
    paths.append(_CoordinateGraphPath(__file__).resolve())
    _need(all(root in path.parents for path in paths), "coordinate graph compiler escaped selected source tree")
    pins = {str(path): _coordinate_graph_sha(path.read_bytes()) for path in sorted(set(paths))}
    pins["logic_tree_guard_paths"] = guard_paths
    global _COORDINATE_GRAPH_OWNER_PINS
    if _COORDINATE_GRAPH_OWNER_PINS is None:
        _COORDINATE_GRAPH_OWNER_PINS = _coordinate_graph_read(_coordinate_graph_wire(pins),
            _COORDINATE_GRAPH_REQUEST_BYTES, "coordinate graph owner pins")
    _need(pins == _COORDINATE_GRAPH_OWNER_PINS, "coordinate graph operation owner changed since first use")
    return eligibility, pins


def _coordinate_graph_runtime(eligibility):
    """Reuse the current eligibility owner's metadata-only runtime custody."""
    owners = eligibility._owners()
    return owners[4], owners[5]


def _coordinate_graph_callables(eligibility, *, eligibility_version=2):
    _need(type(eligibility_version) is int and eligibility_version in (2, 3, 4),
          "explicit coordinate graph eligibility version required")
    validator = (eligibility.validate_source_span_target_eligibility_v2 if eligibility_version == 2
                 else eligibility.validate_source_span_target_eligibility_v3 if eligibility_version == 3
                 else eligibility.validate_source_span_target_eligibility_v4)
    result = (validator,
        eligibility.source_span_target_join_originals_sha256, eligibility.source_span_target_eligibility_sha256,
        _rule, _bound_source, graphs.build_graph, graphs.graph_to_ast, graphs.bind_scope,
        graphs.bind_source_occurrence, context.normalized_document_view, context.validate_source_selector,
        CanonicalRoundTripIR.from_dict.__func__)
    if eligibility_version in (3, 4):
        result += (eligibility._owners, _coordinate_graph_runtime(eligibility)[0].describe_runtime,
            _coordinate_graph_preflight, _coordinate_graph_sources, _coordinate_graph_outputs,
            _coordinate_graph_references_v2, _coordinate_graph_owners, _coordinate_graph_callables,
            _coordinate_graph_runtime)
    if eligibility_version == 4:
        join = eligibility._owners()[0]
        result += (join._coordinate_file_witnesses, join._coordinate_owner_pins, join._owners,
                   join.validate_source_span_entity_join_manifest_v3,
                   prepare_coordinate_source_graph_intake_v3, validate_coordinate_source_graph_intake_v3,
                   _prepare_coordinate_source_graph_intake, _validate_coordinate_source_graph_intake,
                   _coordinate_graph_wire_file_plan, _coordinate_graph_wire_unqualified)
    return result


def _coordinate_graph_preflight(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, expected_request_sha256, join_originals, source_bindings, *, profile_version=1):
    _need(type(profile_version) is int and profile_version in (1, 2, 3), "explicit coordinate graph version required")
    _need(type(expected_request_sha256) is str and _SHA.fullmatch(expected_request_sha256),
          "exact coordinate graph request SHA256 required")
    _need(type(request_raw) is bytes and _coordinate_graph_sha(request_raw) == expected_request_sha256,
          "coordinate graph request bytes differ from independent pin")
    request = _coordinate_graph_read(request_raw, _COORDINATE_GRAPH_REQUEST_BYTES, "coordinate graph request")
    fields = {"schema", "graph_profile", "eligibility_report_raw_sha256", "eligibility_report_sha256",
        "eligibility_request_sha256", "join_manifest_raw_sha256", "join_manifest_sha256",
        "join_originals_sha256", "source_bindings_sha256", "expected_physical_ids"}
    if profile_version in (2, 3):
        fields.add("source_compatibility_profile")
    if profile_version == 3:
        fields.add("metadata_profile")
    _need(type(request) is dict and set(request) == fields, "closed coordinate graph request required")
    _need(request["schema"] == (COORDINATE_GRAPH_REQUEST_SCHEMA if profile_version == 1
          else COORDINATE_GRAPH_REQUEST_SCHEMA_V2 if profile_version == 2
          else COORDINATE_GRAPH_REQUEST_SCHEMA_V3) and request["graph_profile"] == "canonical_rules_v1",
          "unsupported coordinate graph intake profile")
    if profile_version in (2, 3):
        _need(request["source_compatibility_profile"] == (COORDINATE_GRAPH_PROFILE_V2 if profile_version == 2
                                                        else COORDINATE_GRAPH_PROFILE_V3),
              "explicit original-input coordinate graph v2 profile required" if profile_version == 2
              else "explicit original-input wire coordinate graph v3 profile required")
    if profile_version == 3:
        _need(request["metadata_profile"] == COORDINATE_GRAPH_METADATA_PROFILE_V3,
              "explicit graph wire metadata profile required")
    for key in fields - {"schema", "graph_profile", "expected_physical_ids", "source_compatibility_profile", "metadata_profile"}:
        _need(type(request[key]) is str and _SHA.fullmatch(request[key]), "exact independent coordinate graph pin required")
    for raw, field, maximum in ((eligibility_report_raw, "eligibility_report_raw_sha256", _COORDINATE_GRAPH_INPUT_BYTES),
            (eligibility_request_raw, "eligibility_request_sha256", _COORDINATE_GRAPH_REQUEST_BYTES),
            (join_manifest_raw, "join_manifest_raw_sha256", _COORDINATE_GRAPH_INPUT_BYTES)):
        _need(type(raw) is bytes and 0 < len(raw) <= maximum and _coordinate_graph_sha(raw) == request[field],
              "coordinate graph input bytes differ from independent pin: " + field)
    offered = _coordinate_graph_read(eligibility_report_raw, _COORDINATE_GRAPH_INPUT_BYTES, "coordinate eligibility report")
    retained = _coordinate_graph_read(join_manifest_raw, _COORDINATE_GRAPH_INPUT_BYTES, "coordinate join report")
    if profile_version in (2, 3):
        eligibility_request = _coordinate_graph_read(eligibility_request_raw, _COORDINATE_GRAPH_REQUEST_BYTES,
                                                    "original-input eligibility request")
        eligibility_schema = ("legal-source-span-target-eligibility/v3" if profile_version == 2
                              else "legal-source-span-target-eligibility/v4")
        eligibility_profile = ("original-input-coordinate-target-eligibility/v1" if profile_version == 2
                               else "original-input-wire-coordinate-target-eligibility/v1")
        request_schema = ("legal-source-span-target-eligibility-request/v3" if profile_version == 2
                          else "legal-source-span-target-eligibility-request/v4")
        _need(type(offered) is dict and offered.get("schema") == eligibility_schema
              and offered.get("source_compatibility_profile") == eligibility_profile
              and type(eligibility_request) is dict
              and eligibility_request.get("schema") == request_schema
              and eligibility_request.get("source_compatibility_profile") == eligibility_profile,
              "coordinate graph v2 requires explicit original-input eligibility v3 request and report"
              if profile_version == 2 else
              "coordinate graph v3 requires explicit original-input wire eligibility v4 request and report")
        if profile_version == 3:
            _need(offered.get("metadata_profile") == eligibility_request.get("metadata_profile")
                  == COORDINATE_GRAPH_METADATA_PROFILE_V3
                  and type(retained) is dict
                  and retained.get("schema") == "legal-source-span-entity-join-manifest/v3"
                  and retained.get("source_compatibility_profile") == "paired-coordinate-hf-wire-three-cache-join/v1"
                  and retained.get("source_metadata_profile") == COORDINATE_GRAPH_METADATA_PROFILE_V3
                  and type(offered.get("source_metadata_intake_sha256")) is str
                  and _SHA.fullmatch(offered["source_metadata_intake_sha256"])
                  and offered.get("source_metadata_intake_sha256") == retained.get("source_metadata_intake_sha256"),
                  "wire graph requires explicit eligibility v4 and matching wire-coordinate join v3")
    _need(_coordinate_graph_sha(_coordinate_graph_wire(offered)) == request["eligibility_report_sha256"]
          and _coordinate_graph_sha(_coordinate_graph_wire(retained)) == request["join_manifest_sha256"],
          "coordinate graph canonical input identity differs")
    ids = request["expected_physical_ids"]
    _need(type(ids) is list and 1 <= len(ids) <= 64 and all(type(item) is str and _SHA.fullmatch(item) for item in ids)
          and len(set(ids)) == len(ids), "complete bounded unique physical population required")
    _need(type(source_bindings) is dict and all(type(key) is str and key in ids for key in source_bindings),
          "coordinate source bindings must name selected physical identities")
    binding_raw = _coordinate_graph_wire(source_bindings, MAX_BYTES)
    _need(_coordinate_graph_sha(binding_raw) == request["source_bindings_sha256"],
          "independent coordinate source binding map pin differs")
    bindings = _coordinate_graph_read(binding_raw, MAX_BYTES, "coordinate source bindings")
    return request, offered, retained, _coordinate_graph_originals(join_originals), bindings, binding_raw


def _coordinate_graph_sources(retained, eligible, expected_ids, *, eligibility_version=2):
    """Keep original nested sources and every physical reference, without selection."""
    _need(type(eligibility_version) is int and eligibility_version in (2, 3, 4),
          "explicit coordinate graph eligibility version required")
    _need(eligible.get("schema") == ("legal-source-span-target-eligibility/v2" if eligibility_version == 2
          else "legal-source-span-target-eligibility/v3" if eligibility_version == 3
          else "legal-source-span-target-eligibility/v4")
          and eligible.get("source_compatibility_profile") == ("paired-coordinate-target-eligibility/v1"
          if eligibility_version == 2 else "original-input-coordinate-target-eligibility/v1"
          if eligibility_version == 3 else "original-input-wire-coordinate-target-eligibility/v1")
          and eligible.get("upstream_reexecution_performed") is True,
          "genuinely replayed coordinate eligibility for the explicit graph profile required")
    if eligibility_version == 4:
        _need(eligible.get("metadata_profile") == COORDINATE_GRAPH_METADATA_PROFILE_V3
              and eligible.get("source_metadata_intake_sha256") == retained.get("source_metadata_intake_sha256"),
              "genuinely replayed wire graph metadata identity differs")
    physical, refs, outputs = eligible["physical_rows"], eligible["row_references"], eligible["output_occurrences"]
    _need([row["physical_identity_sha256"] for row in physical] == expected_ids
          and _coordinate_graph_wire(refs) == _coordinate_graph_wire(retained["row_references"]),
          "coordinate graph complete physical/reference population differs")
    payloads = [row for bundle in retained["paired_bundles"] for row in bundle["payload_intake"]["rows"]]
    _need(len(payloads) == len(refs), "coordinate graph complete payload population differs")
    sources = {}
    for ref, payload in zip(refs, payloads):
        raw = payload["derived_row_json"].encode("utf-8")
        _need(_coordinate_graph_sha(raw) == payload["row_sha256"] == ref["row_sha256"],
              "coordinate graph source row pin differs")
        observed = _coordinate_graph_read(raw, MAX_ROW_BYTES, "coordinate paired source row")
        _need(observed.get("schema_version") == "uscode-paired-span-census/v2" and type(observed.get("source")) is dict,
              "complete coordinate paired source required")
        identity, source = ref["physical_identity_sha256"], observed["source"]
        if identity in sources:
            _need(_coordinate_graph_wire(source) == _coordinate_graph_wire(sources[identity]),
                  "conflicting coordinate sources for physical identity")
        sources[identity] = source
    _need(list(sources) == expected_ids and all(output["physical_identity_sha256"] in sources for output in outputs),
          "coordinate graph source/output population differs")
    return sources


def _finish_coordinate_graph(checks, primary):
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary coordinate graph custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
    elif failures:
        label, error = failures[0]
        error.add_note("closing coordinate graph custody check: " + label)
        for other, failure in failures[1:]:
            error.add_note("secondary closing check (" + other + "): " + str(failure)[:512])
        raise error


def _coordinate_graph_references_v2(request, eligibility_report_raw, join_manifest_raw, *, report=None):
    """Bind exact artifact bytes and canonical identities without copying carriers."""
    eligible = _coordinate_graph_read(eligibility_report_raw, _COORDINATE_GRAPH_INPUT_BYTES,
                                      "referenced original-input eligibility")
    retained = _coordinate_graph_read(join_manifest_raw, _COORDINATE_GRAPH_INPUT_BYTES,
                                      "referenced original-input join")
    _need(_coordinate_graph_sha(eligibility_report_raw) == request["eligibility_report_raw_sha256"]
          and _coordinate_graph_sha(_coordinate_graph_wire(eligible)) == request["eligibility_report_sha256"]
          and _coordinate_graph_sha(join_manifest_raw) == request["join_manifest_raw_sha256"]
          and _coordinate_graph_sha(_coordinate_graph_wire(retained)) == request["join_manifest_sha256"],
          "coordinate graph referenced artifact/canonical identities differ")
    _need(type(eligible.get("join_manifest_raw_utf8")) is str
          and eligible["join_manifest_raw_utf8"].encode("utf-8") == join_manifest_raw,
          "coordinate graph referenced join pointer does not name the exact artifact")
    references = {
        "eligibility_report_reference": {
            "schema": COORDINATE_GRAPH_ELIGIBILITY_REFERENCE_SCHEMA,
            "container": "eligibility_report_raw_utf8",
            "report_artifact_sha256": request["eligibility_report_raw_sha256"],
            "report_sha256": request["eligibility_report_sha256"],
            "report_bytes": len(eligibility_report_raw)},
        "join_manifest_reference": {
            "schema": COORDINATE_GRAPH_JOIN_REFERENCE_SCHEMA,
            "container": "eligibility_report_raw_utf8",
            "json_pointer": "/join_manifest_raw_utf8",
            "join_manifest_raw_sha256": request["join_manifest_raw_sha256"],
            "join_manifest_sha256": request["join_manifest_sha256"],
            "join_manifest_bytes": len(join_manifest_raw)}}
    if report is not None:
        _need(type(report.get("eligibility_report_raw_utf8")) is str
              and report["eligibility_report_raw_utf8"].encode("utf-8") == eligibility_report_raw
              and "eligibility_report" not in report and "join_manifest_raw_utf8" not in report,
              "coordinate graph v2 must retain one complete raw eligibility carrier")
        for key, value in references.items():
            _need(_coordinate_graph_wire(report.get(key)) == _coordinate_graph_wire(value),
                  "coordinate graph closed typed reference differs: " + key)
    return references


def _coordinate_graph_outputs(eligible, sources, bindings):
    """One mechanical projection for both explicit coordinate graph profiles."""
    outputs = []
    for ordinal, output in enumerate(eligible["output_occurrences"]):
        identity = output["physical_identity_sha256"]
        nested = sources[identity]
        projection = {"source_span_id": nested.get("span_id"), "source_text": nested.get("text"),
            "source_sha256": nested.get("text_sha256"), "legal_id": nested.get("legal_id"),
            "source_revision": nested.get("revision")}
        one_binding = {nested["span_id"]: bindings[identity]} if identity in bindings else {}
        source, binding, issues = _bound_source(projection, one_binding)
        formal = output["formal_output"]
        supported = (output["target_status"] == "mechanically_supported" and type(formal) is dict
            and formal.get("family") == "typed_deontic" and formal.get("format") == "typed-deontic-rule/v1")
        rule = _rule({"rule_json": formal["payload_json"]}) if supported else {
            "status": "unsupported_coordinate_target", "decoded_rule": None, "ast": None,
            "issues": [{"code": "coordinate_target_not_mechanically_supported_typed_deontic_rule"}]}
        issues = [*rule["issues"], *issues]
        if supported:
            _need(_coordinate_graph_wire(rule["ast"]) == _coordinate_graph_wire(output["canonical_ir"]),
                  "coordinate graph rule differs from complete eligibility target")
        graph_request, graph = None, None
        if not issues and source is not None and binding is not None:
            graph_request = {"ast": rule["ast"], "profile": "canonical_rules_v1", "source": source,
                "scope": binding["scope"], "dependency_refs": binding.get("dependency_refs", []),
                "evidence_refs": binding.get("evidence_refs", [])}
            graph_input = _coordinate_graph_wire(graph_request)
            delegated_request = graph_request
            try:
                graph = graphs.build_graph(**graph_request)
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
                issues.append({"code": "existing_graph_profile_refused", "message": str(error)[:512]})
                graph_request, graph = None, None
            _need(_coordinate_graph_wire(delegated_request) == graph_input,
                  "coordinate graph builder changed admitted graph inputs")
            if graph is not None:
                _need(_coordinate_graph_wire(graphs.graph_to_ast(graph)) == _coordinate_graph_wire(rule["ast"]),
                      "coordinate graph ordered AST round trip differs")
        outputs.append({**deepcopy(output), "output_occurrence_ordinal": ordinal,
            "eligibility_output": deepcopy(output), "paired_source": deepcopy(nested),
            "rule_assessment": rule, "source_binding": source,
            "source_binding_declaration_sha256": _digest(binding) if binding is not None else None,
            "context_observation": deepcopy(binding.get("context_observation")) if type(binding) is dict else None,
            "selected_occurrence": None, "source_binding_mask": 0,
            "graph_source_relationship": "independently_nominated_exact_source_occurrence_crosswalk_unverified",
            "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
            "issues": issues, "disposition": "proposed_unreviewed_graph" if graph is not None else "unresolved",
            "graph_request": graph_request, "graph": graph, **_FALSE})
    return outputs


def _prepare_coordinate_source_graph_intake(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, join_originals, source_bindings, profile_version):
    """Retain every coordinate target and nominate exact, unreviewed source graphs.

    Opening and closing eligibility validation replay the genuine original join.
    An independent HTML nomination does not select the retained coordinate
    occurrence, establish an edition crosswalk, or qualify statutory meaning.
    """
    request, offered, retained, captured, bindings, binding_raw = _coordinate_graph_preflight(request_raw,
        eligibility_report_raw, eligibility_request_raw, join_manifest_raw, expected_request_sha256,
        join_originals, source_bindings, profile_version=profile_version)
    eligibility_version = 2 if profile_version == 1 else 3 if profile_version == 2 else 4
    snapshots = tuple(_coordinate_graph_wire(value) for value in (request, offered, retained))
    eligibility, before, callables, eligible, eligible_raw = None, None, None, None, None
    opened, primary, result = False, None, None
    runtime, runtime_pins, runtime_description_raw, result_raw = None, None, None, None
    wire_commitment = request["join_originals_sha256"] if profile_version == 3 else None
    replay_returns = []
    live_outputs, live_outputs_raw, report, report_raw = (None,) * 4
    file_plan, file_witnesses, final = None, None, None

    def originals_unchanged():
        _coordinate_graph_originals(join_originals)
        if eligibility is not None:
            commitment = wire_commitment if profile_version == 3 else request["join_originals_sha256"]
            _need(eligibility.source_span_target_join_originals_sha256(join_originals)
                  == eligibility.source_span_target_join_originals_sha256(captured) == commitment,
                  "coordinate graph original join inputs changed during operation")
        _need(_coordinate_graph_wire(source_bindings, MAX_BYTES) == binding_raw
              and _coordinate_graph_wire(bindings, MAX_BYTES) == binding_raw,
              "coordinate graph source bindings changed during operation")
        _need(tuple(_coordinate_graph_wire(value) for value in (request, offered, retained)) == snapshots,
              "coordinate graph admitted input snapshots changed during operation")
        if eligible is not None:
            _need(_coordinate_graph_wire(eligible) == eligible_raw,
                  "coordinate graph replayed eligibility changed during operation")

    def producers_unchanged():
        _need(_coordinate_graph_sha(_CoordinateGraphPath(__file__).read_bytes()) == _COORDINATE_GRAPH_SELF_PIN,
              "coordinate graph producer changed since import")
        if before is not None:
            _need(_coordinate_graph_owners()[1] == before, "coordinate graph producer sources changed during operation")
            current_callables = _coordinate_graph_callables(eligibility, eligibility_version=eligibility_version)
            _need(len(current_callables) == len(callables)
                  and all(left is right for left, right in zip(current_callables, callables)),
                  "coordinate graph producer callable changed during operation")
            if profile_version in (2, 3):
                current_runtime, owner_pins = _coordinate_graph_runtime(eligibility)
                _need(current_runtime is runtime and _coordinate_graph_wire(owner_pins,
                    _COORDINATE_GRAPH_REQUEST_BYTES) == runtime_pins,
                    "coordinate graph eligibility runtime owners changed during operation")
                if runtime_description_raw is not None:
                    _need(_coordinate_graph_wire(runtime.describe_runtime("legal_ir",
                        eligible["request"]["decoder_profile"])) == runtime_description_raw,
                        "coordinate graph runtime description changed during operation")

    def replay_eligibility():
        validator = (eligibility.validate_source_span_target_eligibility_v2 if profile_version == 1 else callables[0])
        value = validator(offered, eligibility_request_raw,
            join_manifest_raw, expected_request_sha256=request["eligibility_request_sha256"],
            expected_report_sha256=request["eligibility_report_sha256"], join_originals=captured)
        if profile_version == 3:
            _need(_coordinate_graph_wire(value) == _coordinate_graph_wire(offered),
                  "genuine wire eligibility return differs from the independently pinned artifact")
            replay_returns.append((value, _coordinate_graph_wire(value)))
        return value

    def closing_eligibility():
        if opened:
            closing = replay_eligibility()
            _need(_coordinate_graph_wire(closing) == eligible_raw,
                  "coordinate graph closing eligibility replay changed")

    def wire_files_unchanged():
        if profile_version == 3 and file_witnesses is not None:
            join = eligibility._owners()[0]
            _need(_coordinate_graph_wire(join._coordinate_file_witnesses(*file_plan),
                                          _COORDINATE_GRAPH_REQUEST_BYTES) == file_witnesses,
                  "wire coordinate graph physical files changed after genuine replay")

    def wire_returns_unchanged():
        if profile_version == 3:
            for value, snapshot in replay_returns:
                _need(_coordinate_graph_wire(value) == snapshot,
                      "genuine wire eligibility return changed during graph preparation")
            if live_outputs_raw is not None:
                _need(_coordinate_graph_wire(live_outputs) == live_outputs_raw,
                      "live graph or projection return changed during closing custody")
            if report_raw is not None:
                _coordinate_graph_wire_unqualified(report)
                _need(_coordinate_graph_wire(report) == report_raw,
                      "assembled wire graph report changed during final serialization")
            if result_raw is not None:
                _coordinate_graph_wire_unqualified(result)
                _need(_coordinate_graph_wire(result) == result_raw,
                      "detached wire graph report changed during closing custody")
            if final is not None:
                _coordinate_graph_wire_unqualified(final)
                _need(_coordinate_graph_wire(final) == result_raw,
                      "final detached wire graph return changed during serialization")

    try:
        producers_unchanged()
        eligibility, before = _coordinate_graph_owners()
        before = _coordinate_graph_read(_coordinate_graph_wire(before), _COORDINATE_GRAPH_REQUEST_BYTES,
                                       "coordinate graph owner pins")
        callables = _coordinate_graph_callables(eligibility, eligibility_version=eligibility_version)
        if profile_version in (2, 3):
            runtime, owner_pins = _coordinate_graph_runtime(eligibility)
            runtime_pins = _coordinate_graph_wire(owner_pins, _COORDINATE_GRAPH_REQUEST_BYTES)
        originals_unchanged()
        _need(eligibility.source_span_target_eligibility_sha256(offered) == request["eligibility_report_sha256"],
              "coordinate graph eligibility identity differs from original owner")
        eligible = replay_eligibility()
        eligible_raw, opened = _coordinate_graph_wire(eligible), True
        _need(eligible["request_sha256"] == request["eligibility_request_sha256"]
              and eligible["request_raw_utf8"].encode("utf-8") == eligibility_request_raw
              and eligible["join_manifest_raw_utf8"].encode("utf-8") == join_manifest_raw
              and eligible["join_manifest_sha256"] == request["join_manifest_sha256"]
              and eligible["join_originals_sha256"] == request["join_originals_sha256"],
              "coordinate graph input request/report ancestry differs")
        if profile_version in (2, 3):
            runtime_description_raw = _coordinate_graph_wire(eligible["runtime_description"])
            _need(_coordinate_graph_wire(runtime.describe_runtime("legal_ir", eligible["request"]["decoder_profile"]))
                  == runtime_description_raw, "coordinate graph runtime description differs from eligibility")
        if profile_version == 3:
            originals_unchanged()
            file_plan = _coordinate_graph_wire_file_plan(eligibility, eligible, join_manifest_raw, captured)
            file_witnesses = _coordinate_graph_wire(eligibility._owners()[0]._coordinate_file_witnesses(*file_plan),
                                                    _COORDINATE_GRAPH_REQUEST_BYTES)
        sources = _coordinate_graph_sources(retained, eligible, request["expected_physical_ids"],
                                            eligibility_version=eligibility_version)
        outputs = _coordinate_graph_outputs(eligible, sources, bindings)
        if profile_version == 3:
            # The unchanged projection keeps the genuine build_graph objects
            # and delegated request dictionaries in these live output records.
            live_outputs, live_outputs_raw = outputs, _coordinate_graph_wire(outputs)
        report = {"schema": COORDINATE_GRAPH_SCHEMA, "source_compatibility_profile": COORDINATE_GRAPH_PROFILE,
            "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
            "request_sha256": expected_request_sha256, "eligibility_report_raw_utf8": eligibility_report_raw.decode("utf-8"),
            "eligibility_report": eligible, "eligibility_request_raw_utf8": eligibility_request_raw.decode("utf-8"),
            "join_manifest_raw_utf8": join_manifest_raw.decode("utf-8"),
            "join_originals_sha256": request["join_originals_sha256"],
            "source_bindings_sha256": request["source_bindings_sha256"],
            "physical_rows": deepcopy(eligible["physical_rows"]), "row_references": deepcopy(eligible["row_references"]),
            "output_occurrences": outputs, "population_complete": True,
            "coverage_scope": "complete_supplied_coordinate_eligibility_physical_and_output_population_only",
            "upstream_reexecution_performed": True,
            "upstream_reexecution_requirement": "opening_and_closing_public_coordinate_eligibility_original_input_replay",
            "graph_source_relationship": "independently_nominated_exact_source_occurrence_crosswalk_unverified",
            "coordinate_to_graph_source_correspondence": "unverified_no_independent_crosswalk",
            "current_source_release_correspondence": "unverified_no_independent_crosswalk",
            "entity_binding": "unavailable_semantic_companions_not_supplied",
            "selected_occurrence": None, "source_binding_mask": 0,
            "counts": {"physical_rows": len(eligible["physical_rows"]), "row_references": len(eligible["row_references"]),
                "output_occurrences": len(outputs), "proposed_unreviewed_graphs": sum(row["graph"] is not None for row in outputs),
                "unresolved_outputs": sum(row["graph"] is None for row in outputs)},
            "producer_pins": {"coordinate_graph_intake": before, "eligibility": deepcopy(eligible["producer_pins"])},
            "producer_pins_scope": "listed_graph_source_and_eligibility_owner_files_not_complete_execution_closure",
            "runtime_description": deepcopy(eligible["runtime_description"]), "checkpoint_status": "not_assessed",
            "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(_COORDINATE_GRAPH_AUTHORITY), **_FALSE}
        if profile_version in (2, 3):
            report.update(schema=COORDINATE_GRAPH_SCHEMA_V2 if profile_version == 2 else COORDINATE_GRAPH_SCHEMA_V3,
                source_compatibility_profile=COORDINATE_GRAPH_PROFILE_V2 if profile_version == 2 else COORDINATE_GRAPH_PROFILE_V3,
                upstream_reexecution_requirement=("opening_and_closing_public_eligibility_v3_original_input_replay"
                    if profile_version == 2 else "opening_and_closing_public_eligibility_v4_wire_original_input_replay"),
                **_coordinate_graph_references_v2(request, eligibility_report_raw, join_manifest_raw))
            # Mutate only our new outer report; genuine eligibility stays intact.
            del report["eligibility_report"]
            del report["join_manifest_raw_utf8"]
        if profile_version == 3:
            report.update(metadata_profile=COORDINATE_GRAPH_METADATA_PROFILE_V3,
                          source_metadata_intake_sha256=eligible["source_metadata_intake_sha256"])
            _coordinate_graph_wire_unqualified(report)
            report_raw = _coordinate_graph_wire(report)
        result = _coordinate_graph_read(report_raw if profile_version == 3 else _coordinate_graph_wire(report), _COORDINATE_GRAPH_MAX_BYTES,
                                        "coordinate source graph intake")
        if profile_version in (2, 3):
            _coordinate_graph_references_v2(request, eligibility_report_raw, join_manifest_raw, report=result)
            result_raw = _coordinate_graph_wire(result)
    except BaseException as error:
        primary = error
        raise
    finally:
        checks = (("closing public eligibility replay", closing_eligibility),
            ("original and admitted inputs", originals_unchanged), ("producer sources and callables", producers_unchanged))
        if profile_version == 3:
            checks += (("live wire eligibility and graph returns", wire_returns_unchanged),
                       ("physical wire graph files", wire_files_unchanged),
                       ("final original wire inputs", originals_unchanged),
                       ("final wire producer sources", producers_unchanged))
        _finish_coordinate_graph(checks, primary)
    if profile_version == 3:
        # Complete final serialization stays inside the same original/source/
        # physical-file fences. No offered parsed object supplies a file plan.
        primary = None
        try:
            _coordinate_graph_references_v2(request, eligibility_report_raw, join_manifest_raw, report=result)
            final = _coordinate_graph_read(result_raw, _COORDINATE_GRAPH_MAX_BYTES, "detached wire coordinate graph v3")
            _need(_coordinate_graph_wire(final) == result_raw, "wire graph detached final serialization differs")
            return final
        except BaseException as error:
            primary = error
            raise
        finally:
            _finish_coordinate_graph((("final live wire returns", wire_returns_unchanged),
                ("final original wire inputs", originals_unchanged),
                ("final wire producers", producers_unchanged),
                ("final physical wire files", wire_files_unchanged)), primary)
    if profile_version == 2:
        _need(_coordinate_graph_wire(result) == result_raw,
              "coordinate graph detached result changed during closing replay")
        _coordinate_graph_references_v2(request, eligibility_report_raw, join_manifest_raw, report=result)
        return _coordinate_graph_read(result_raw, _COORDINATE_GRAPH_MAX_BYTES,
                                      "detached original-input coordinate graph v2")
    return result


def coordinate_source_graph_intake_sha256(report):
    """Identity of the complete ordinary report, without semantic authority."""
    return _coordinate_graph_sha(_coordinate_graph_wire(report))


def _validate_coordinate_source_graph_intake(report, request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, expected_report_sha256, join_originals, source_bindings, profile_version):
    """Regenerate every proposal and refusal, including genuine closing replay."""
    _need(type(expected_report_sha256) is str and _SHA.fullmatch(expected_report_sha256),
          "exact coordinate graph report SHA256 required")
    raw = report if type(report) is bytes else _coordinate_graph_wire(report)
    offered = _coordinate_graph_read(raw, _COORDINATE_GRAPH_MAX_BYTES, "offered coordinate source graph intake")
    original = _coordinate_graph_wire(offered)
    _need(_coordinate_graph_sha(original) == expected_report_sha256, "coordinate graph report SHA256 differs")
    primary = None
    expected, expected_snapshot, wire_plan, wire_files, wire_runtime_description = (None,) * 5
    if profile_version == 3:
        _need(type(offered) is dict and offered.get("schema") == COORDINATE_GRAPH_SCHEMA_V3
              and offered.get("source_compatibility_profile") == COORDINATE_GRAPH_PROFILE_V3
              and offered.get("metadata_profile") == COORDINATE_GRAPH_METADATA_PROFILE_V3,
              "explicit wire coordinate graph v3 report required")
        wire_request, wire_offered, wire_retained, wire_originals, wire_bindings, wire_binding_raw = \
            _coordinate_graph_preflight(request_raw, eligibility_report_raw, eligibility_request_raw,
                join_manifest_raw, expected_request_sha256, join_originals, source_bindings, profile_version=3)
        wire_snapshots = tuple(_coordinate_graph_wire(value) for value in
                               (wire_request, wire_offered, wire_retained))
        wire_commitment = wire_request["join_originals_sha256"]
        wire_eligibility, wire_owner_pins = _coordinate_graph_owners()
        wire_owner_raw = _coordinate_graph_wire(wire_owner_pins, _COORDINATE_GRAPH_REQUEST_BYTES)
        wire_callables = _coordinate_graph_callables(wire_eligibility, eligibility_version=4)
        wire_runtime, wire_runtime_pins = _coordinate_graph_runtime(wire_eligibility)
        wire_runtime_pins_raw = _coordinate_graph_wire(wire_runtime_pins, _COORDINATE_GRAPH_REQUEST_BYTES)
        wire_decoder_profile = _coordinate_graph_read(eligibility_request_raw,
            _COORDINATE_GRAPH_REQUEST_BYTES, "wire eligibility request")["decoder_profile"]

    def wire_outer_unchanged():
        if profile_version == 3:
            _coordinate_graph_originals(join_originals)
            _coordinate_graph_originals(wire_originals)
            _need(wire_eligibility.source_span_target_join_originals_sha256(join_originals)
                  == wire_eligibility.source_span_target_join_originals_sha256(wire_originals) == wire_commitment,
                  "outer wire graph originals changed during validation")
            _need(_coordinate_graph_wire(source_bindings, MAX_BYTES) == wire_binding_raw
                  and _coordinate_graph_wire(wire_bindings, MAX_BYTES) == wire_binding_raw,
                  "outer wire graph source bindings changed during validation")
            _need(tuple(_coordinate_graph_wire(value) for value in
                        (wire_request, wire_offered, wire_retained)) == wire_snapshots,
                  "outer wire graph parsed input snapshots changed during validation")
            current_eligibility, current_pins = _coordinate_graph_owners()
            current_callables = _coordinate_graph_callables(wire_eligibility, eligibility_version=4)
            current_runtime, current_runtime_pins = _coordinate_graph_runtime(wire_eligibility)
            _need(current_eligibility is wire_eligibility
                  and _coordinate_graph_wire(current_pins, _COORDINATE_GRAPH_REQUEST_BYTES) == wire_owner_raw
                  and len(current_callables) == len(wire_callables)
                  and all(left is right for left, right in zip(current_callables, wire_callables))
                  and current_runtime is wire_runtime
                  and _coordinate_graph_wire(current_runtime_pins, _COORDINATE_GRAPH_REQUEST_BYTES) == wire_runtime_pins_raw,
                  "outer wire graph source/callable/runtime custody changed")
            if expected_snapshot is not None:
                _coordinate_graph_wire_unqualified(expected)
                _need(_coordinate_graph_wire(expected) == expected_snapshot
                      and _coordinate_graph_sha(expected_snapshot) == expected_report_sha256,
                      "regenerated wire graph changed during outer validation")
            if wire_runtime_description is not None:
                _need(_coordinate_graph_wire(wire_runtime.describe_runtime("legal_ir",
                    wire_decoder_profile)) == wire_runtime_description,
                    "outer wire graph runtime description changed")
            if wire_files is not None:
                join = wire_eligibility._owners()[0]
                _need(_coordinate_graph_wire(join._coordinate_file_witnesses(*wire_plan),
                    _COORDINATE_GRAPH_REQUEST_BYTES) == wire_files,
                    "wire graph physical files changed during outer validation")
    try:
        prepare = (prepare_coordinate_source_graph_intake_v1 if profile_version == 1
                   else prepare_coordinate_source_graph_intake_v2 if profile_version == 2
                   else prepare_coordinate_source_graph_intake_v3)
        expected = prepare(request_raw, eligibility_report_raw, eligibility_request_raw,
            join_manifest_raw, expected_request_sha256=expected_request_sha256,
            join_originals=join_originals, source_bindings=source_bindings)
        _need(original == _coordinate_graph_wire(expected), "coordinate graph report differs from complete original-input replay")
        if profile_version == 3:
            expected_snapshot = _coordinate_graph_wire(expected)
            _need(expected_snapshot == original, "wire graph regenerated report identity changed")
            wire_outer_unchanged()
            # Only the genuinely regenerated immutable artifact may nominate
            # physical inputs. Outer offered/parsed objects are witnesses only.
            regenerated_eligibility_raw = expected["eligibility_report_raw_utf8"].encode("utf-8")
            _need(regenerated_eligibility_raw == eligibility_report_raw,
                  "regenerated graph retained different eligibility bytes")
            regenerated_eligibility = _coordinate_graph_read(regenerated_eligibility_raw,
                _COORDINATE_GRAPH_INPUT_BYTES, "regenerated original wire eligibility")
            wire_plan = _coordinate_graph_wire_file_plan(wire_eligibility, regenerated_eligibility,
                                                         join_manifest_raw, wire_originals)
            wire_files = _coordinate_graph_wire(wire_eligibility._owners()[0]._coordinate_file_witnesses(*wire_plan),
                                                 _COORDINATE_GRAPH_REQUEST_BYTES)
            wire_runtime_description = _coordinate_graph_wire(expected["runtime_description"])
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            current = _coordinate_graph_read(report, _COORDINATE_GRAPH_MAX_BYTES, "offered coordinate graph report") \
                if type(report) is bytes else report
            _need(_coordinate_graph_wire(current) == original, "offered coordinate graph report changed during validation")
        checks = (("offered graph report", offered_unchanged),)
        if profile_version == 3:
            checks += (("outer wire graph custody", wire_outer_unchanged),)
        _finish_coordinate_graph(checks, primary)


def prepare_coordinate_source_graph_intake_v1(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, join_originals, source_bindings):
    """Historical original-input eligibility-v2 profile; no current-v2 fallback."""
    return _prepare_coordinate_source_graph_intake(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, expected_request_sha256=expected_request_sha256,
        join_originals=join_originals, source_bindings=source_bindings, profile_version=1)


def validate_coordinate_source_graph_intake_v1(report, request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, expected_report_sha256, join_originals, source_bindings):
    """Regenerate the historical graph v1 contract without a profile upgrade."""
    return _validate_coordinate_source_graph_intake(report, request_raw, eligibility_report_raw,
        eligibility_request_raw, join_manifest_raw, expected_request_sha256=expected_request_sha256,
        expected_report_sha256=expected_report_sha256, join_originals=join_originals,
        source_bindings=source_bindings, profile_version=1)


def prepare_coordinate_source_graph_intake_v2(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, join_originals, source_bindings):
    """Prepare unreviewed proposals only from explicit genuine eligibility v3."""
    return _prepare_coordinate_source_graph_intake(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, expected_request_sha256=expected_request_sha256,
        join_originals=join_originals, source_bindings=source_bindings, profile_version=2)


def validate_coordinate_source_graph_intake_v2(report, request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, expected_report_sha256, join_originals, source_bindings):
    """Regenerate every v2 proposal/reference through genuine closing v3 replay."""
    return _validate_coordinate_source_graph_intake(report, request_raw, eligibility_report_raw,
        eligibility_request_raw, join_manifest_raw, expected_request_sha256=expected_request_sha256,
        expected_report_sha256=expected_report_sha256, join_originals=join_originals,
        source_bindings=source_bindings, profile_version=2)


def _coordinate_graph_wire_file_plan(eligibility, eligible, join_manifest_raw, captured):
    """Derive physical nominations only after genuine eligibility-v4 validation.

    Callers retain the exact validator result and its fixed canonical identity.
    The offered graph/preflight objects never supply these filesystem paths.
    """
    _need(type(eligible) is dict and eligible.get("schema") == "legal-source-span-target-eligibility/v4"
          and eligible.get("source_compatibility_profile") == "original-input-wire-coordinate-target-eligibility/v1"
          and eligible.get("metadata_profile") == COORDINATE_GRAPH_METADATA_PROFILE_V3
          and type(eligible.get("join_manifest_raw_utf8")) is str
          and eligible["join_manifest_raw_utf8"].encode("utf-8") == join_manifest_raw,
          "genuinely regenerated wire eligibility must retain the exact original join bytes")
    joined = _coordinate_graph_read(eligible["join_manifest_raw_utf8"].encode("utf-8"),
        _COORDINATE_GRAPH_INPUT_BYTES, "genuinely regenerated wire coordinate join")
    _need(joined.get("schema") == "legal-source-span-entity-join-manifest/v3"
          and joined.get("source_compatibility_profile") == "paired-coordinate-hf-wire-three-cache-join/v1"
          and joined.get("source_metadata_profile") == COORDINATE_GRAPH_METADATA_PROFILE_V3
          and joined.get("source_metadata_intake_sha256") == eligible.get("source_metadata_intake_sha256")
          and type(joined.get("request_raw_utf8")) is str
          and joined["request_raw_utf8"].encode("utf-8") == captured["request_raw"],
          "genuinely regenerated graph source ancestry differs from the original wire join")
    request = _coordinate_graph_read(joined["request_raw_utf8"].encode("utf-8"),
        256 * 1024, "genuinely regenerated original wire join request")
    locations, selected = request["paired_bundles"], joined["span_inventory"]["manifests"]
    _need(type(locations) is list and type(selected) is list and len(locations) == len(selected) == 1
          and locations[0]["manifest_path_in_repo"] == selected[0]["path_in_repo"],
          "one genuinely regenerated physical wire graph bundle required")
    return (locations[0], selected[0])


def _coordinate_graph_wire_unqualified(report):
    """Keep graph proposals separate from reviewed source or consumer authority."""
    _need(type(report) is dict and report.get("schema") == COORDINATE_GRAPH_SCHEMA_V3
          and report.get("source_compatibility_profile") == COORDINATE_GRAPH_PROFILE_V3
          and report.get("metadata_profile") == COORDINATE_GRAPH_METADATA_PROFILE_V3,
          "explicit wire graph v3 report required")
    authority = report.get("authority")
    _need(type(authority) is dict and set(authority) == set(_COORDINATE_GRAPH_AUTHORITY)
          and all(value is False for value in authority.values())
          and all(report.get(key) is False for key in _FALSE),
          "wire graph proposals cannot grant authority")
    for key in ("training_mask", "evaluation_gold_mask", "source_binding_mask"):
        _need(type(report.get(key)) is int and report[key] == 0, "wire graph masks must remain plain integer zero")
    _need(report.get("selected_occurrence") is None
          and report.get("graph_source_relationship") == "independently_nominated_exact_source_occurrence_crosswalk_unverified"
          and report.get("coordinate_to_graph_source_correspondence") == "unverified_no_independent_crosswalk"
          and report.get("current_source_release_correspondence") == "unverified_no_independent_crosswalk"
          and report.get("entity_binding") == "unavailable_semantic_companions_not_supplied",
          "wire graph proposals cannot infer source or entity correspondence")
    for row in report["physical_rows"] + report["row_references"] + report["output_occurrences"]:
        for key in ("training_mask", "evaluation_gold_mask"):
            _need(type(row.get(key)) is int and row[key] == 0, "wire graph row masks must remain plain integer zero")
        for key, value in row.items():
            if key.endswith("_mask"):
                _need(type(value) is int and value == 0, "wire graph facet masks must remain plain integer zero")
        if "field_masks" in row:
            fields = row["field_masks"]
            _need(type(fields) is dict and set(fields) == {"modality", "actor", "action", "object", "conditions", "exceptions", "temporal"}
                  and all(type(value) is int and value == 0 for value in fields.values()),
                  "wire graph field masks must remain plain integer zero")
    for row in report["output_occurrences"]:
        _need(row.get("selected_occurrence") is None
              and type(row.get("source_binding_mask")) is int and row["source_binding_mask"] == 0
              and row.get("consumer_eligible") is False
              and row.get("graph_source_relationship") == "independently_nominated_exact_source_occurrence_crosswalk_unverified"
              and row.get("coordinate_to_graph_source_correspondence") == "unverified_no_independent_crosswalk"
              and all(row.get(key) is False for key in _FALSE),
              "wire graph output cannot promote a proposed occurrence or target")


def prepare_coordinate_source_graph_intake_v3(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, *, expected_request_sha256, join_originals, source_bindings):
    """Propose graphs only from explicit, genuinely replayed wire eligibility v4."""
    return _prepare_coordinate_source_graph_intake(request_raw, eligibility_report_raw, eligibility_request_raw,
        join_manifest_raw, expected_request_sha256=expected_request_sha256,
        join_originals=join_originals, source_bindings=source_bindings, profile_version=3)


def validate_coordinate_source_graph_intake_v3(report, request_raw, eligibility_report_raw,
        eligibility_request_raw, join_manifest_raw, *, expected_request_sha256, expected_report_sha256,
        join_originals, source_bindings):
    """Regenerate the wire graph proposal and retain original-input/physical custody."""
    return _validate_coordinate_source_graph_intake(report, request_raw, eligibility_report_raw,
        eligibility_request_raw, join_manifest_raw, expected_request_sha256=expected_request_sha256,
        expected_report_sha256=expected_report_sha256, join_originals=join_originals,
        source_bindings=source_bindings, profile_version=3)


__all__ += ["prepare_coordinate_source_graph_intake_v1", "validate_coordinate_source_graph_intake_v1",
            "prepare_coordinate_source_graph_intake_v2", "validate_coordinate_source_graph_intake_v2",
            "coordinate_source_graph_intake_sha256",
            "prepare_coordinate_source_graph_intake_v3", "validate_coordinate_source_graph_intake_v3"]

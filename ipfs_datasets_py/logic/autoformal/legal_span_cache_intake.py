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

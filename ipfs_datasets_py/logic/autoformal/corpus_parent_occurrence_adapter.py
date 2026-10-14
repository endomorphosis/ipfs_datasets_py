"""Project replayed literal parent evidence into bounded candidate records.

Core source identities address exact decoded Parquet ``text`` field bytes.
Complete original reports stay externally bound by raw CID/SHA/size and a
separate FULL canonical owner hash. Roles and physical cache bindings remain
separate from shared source occurrences. No unique occurrence, governing body,
edition, region, sentence gold, semantic graph or authenticated review is chosen.
Importing this module does not load the parent decoder or native/model owners.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_bytes

from . import corpus_contracts as contracts
from . import corpus_source as source

SCHEMA = "legal-corpus-parent-occurrence-manifest/v1"
PARENT_SCHEMA = "legal-corpus-parent-field/v1"
CACHE_ROW_SCHEMA = "legal-corpus-parent-cache-row/v1"
MATCH_SCHEMA = "legal-corpus-parent-cache-match/v1"
ROLE_SCHEMA = "legal-corpus-parent-source-role/v1"
PROFILE = "exact-decoded-parent-field-candidate-records/v1"
UNDECLARED_EDITION = "not_declared_in_source_artifact"
REPORT_KEYS = ("parent_text_views", "cache_parent_occurrences", "parent_sentence_candidates")
REPLAY_FIELDS = {
    "provenance_reports", "lineage_report", "expected_lineage_report_sha256", "lineage_inputs",
    "parent_text_views_inputs", "expected_record_sha256s", "expected_provenance_report_sha256s",
}
ROLES = ("region", "marker", "segment", "dependency", "boundary", "prefix", "suffix")
MISSING_CONTEXT = (
    "definition", "authority", "antecedent", "shared_qualifier", "temporal_origin", "referenced_provision",
)
DEFAULT_LIMITS = {
    "max_report_bytes": 8 * 1024**2,
    "max_replay_bytes": 16 * 1024**2,
    "max_total_input_bytes": 32 * 1024**2,
    "max_records": 8192,
    "max_collection_bytes": 16 * 1024**2,
}
MAX_JSON_DEPTH = 48
MAX_JSON_NODES = 1_000_000
FALSE_FLAGS = dict.fromkeys((
    "source_authenticity_verified", "source_semantics_verified", "context_closure_verified",
    "source_region_roles_verified", "governing_body_selected", "governing_edition_verified",
    "producer_original_character_mapping_verified", "historical_invocation_verified",
    "sentence_gold_qualified", "sentence_boundaries_verified", "dependency_targets_resolved",
    "autoformalization_eligible", "formalization_eligible", "independently_reviewed",
    "admitted", "formalized", "accepted_graph_view_enabled", "training_qualified",
    "training_gold_qualified", "proof_authority", "backend_executed", "lean_compilation_verified",
    "legal_dependency_inventory_exhaustive", "whole_cache_coverage_verified",
), False)
UNSELECTED = {"selected_occurrence": None, "governing_source_binding": None}
MANIFEST_FIELDS = {
    "profile", "limits", "report_bindings", "replay_bindings", "producer_pins", "record_refs",
    "populations", "counts", "hash_recipes", "population_complete", "coverage_scope", "view",
    *FALSE_FLAGS, *UNSELECTED,
}
PARENT_FIELDS = {
    "ordinal", "source_identity", "source_identity_sha256", "source_version_cid", "view_sha256",
    "raw_row_sha256", "literal_legal_id_observation", "disposition", "issues", "external_binding",
    "original_row_binding", *FALSE_FLAGS, *UNSELECTED,
}
CACHE_ROW_FIELDS = {
    "ordinal", "cache_identity", "cache_row_ordinal", "record_sha256", "raw_row_sha256", "source_identity",
    "prior_provenance_classification", "prior_lineage_status", "prior_lineage_issues", "status", "issues",
    "producer_row_witness", "parent_row_witness", "local_parent_reference_view_indices",
    "source_text_sha256_matches_raw_declaration", "comparisons", "external_binding", "original_row_binding",
    *FALSE_FLAGS, *UNSELECTED,
}
MATCH_FIELDS = {
    "ordinal", "cache_row_record_cid", "cache_identity", "cache_row_ordinal", "record_sha256",
    "raw_row_sha256", "view_index", "match_index", "parent_record_cid", "source_version_cid",
    "source_occurrence_cid", "context_cid", "selector_sha256", "literal_legal_id_matches",
    "local_parent_reference_view", "external_binding", *FALSE_FLAGS, *UNSELECTED,
}
ROLE_FIELDS = {
    "ordinal", "role", "parent_record_cid", "source_version_cid", "source_occurrence_cid", "context_cid",
    "owner_id", "observations", "external_binding", *FALSE_FLAGS, *UNSELECTED,
}
HASH_RECIPES = {
    "raw_report": "SHA256 and raw CID of exact original supplied JSON bytes; no canonical replacement",
    "owner_report": "FULL canonical sorted compact UTF8 JSON SHA256 including the owner self-seal",
    "external_value": "canonical sorted compact UTF8 JSON SHA256 of the exact JSON-pointer value",
    "record": "canonical DAG JSON of the complete sealed record including record_cid and cid_scope",
    "portable_source": "immutable original file/revision/complete-row/physical-row/field identity; excludes local custody path",
}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail("closed lower-only adapter limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail("unknown or raised parent occurrence adapter limit")
        result[key] = bound
    return result


def _plain(value, maximum):
    """Separate report/collection bounds never enlarge common sealed records."""
    remaining = MAX_JSON_NODES
    remaining_bytes = maximum

    def consume(size):
        nonlocal remaining_bytes
        remaining_bytes -= size
        if remaining_bytes < 0:
            _fail("complete JSON byte bound exceeded before serialization")

    def string(item, *, key=False):
        # Each code point requires at least one JSON byte. Refuse before making
        # a UTF8 or escaped-string copy, then account exactly without allocation.
        if len(item) + 2 > remaining_bytes or key and len(item) > 4096:
            _fail("complete JSON string/key byte bound exceeded before encoding")
        consume(2)  # quotation delimiters
        utf8_size = 0
        for char in item:
            code = ord(char)
            if 0xD800 <= code <= 0xDFFF:
                _fail("valid UTF8 JSON strings required")
            width = 1 if code <= 0x7F else 2 if code <= 0x7FF else 3 if code <= 0xFFFF else 4
            utf8_size += width
            if key and utf8_size > 4096:
                _fail("ordinary bounded JSON keys required")
            if char in ('"', "\\") or char in "\b\f\n\r\t":
                consume(2)
            elif code < 0x20:
                consume(6)  # canonical \u00XX escape
            else:
                consume(width)

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if depth > MAX_JSON_DEPTH or remaining < 0:
            _fail("complete JSON node/depth bound exceeded")
        if type(item) is dict:
            consume(2)
            for index, (key, child) in enumerate(item.items()):
                if type(key) is not str:
                    _fail("ordinary bounded JSON keys required")
                if index:
                    consume(1)
                string(key, key=True)
                consume(1)
                visit(child, depth + 1)
        elif type(item) is list:
            consume(2)
            for index, child in enumerate(item):
                if index:
                    consume(1)
                visit(child, depth + 1)
        elif type(item) is str:
            string(item)
        elif type(item) is int:
            if not -(1 << 63) < item < (1 << 63):
                _fail("bounded ordinary JSON integer required")
            consume(len(str(item)))
        elif type(item) is float:
            if not math.isfinite(item):
                _fail("finite JSON number required")
            consume(len(json.dumps(item, allow_nan=False)))
        elif item is None:
            consume(4)
        elif type(item) is bool:
            consume(4 if item else 5)
        elif item is not None and type(item) is not bool:
            _fail("plain JSON required; custom readers and callbacks are refused")

    try:
        visit(value, 0)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        if isinstance(error, contracts.CorpusContractError):
            raise
        raise contracts.CorpusContractError("bounded finite UTF8 JSON required") from error
    if len(raw) > maximum:
        _fail("complete JSON byte bound exceeded; no truncation")
    if len(raw) != maximum - remaining_bytes:
        _fail("incremental JSON byte accounting differs from canonical encoding")
    return raw


def _load(raw, maximum):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                _fail("duplicate original report JSON key")
            result[key] = item
        return result

    def constant(_):
        _fail("non-finite original report JSON")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        _plain(result, maximum)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, contracts.CorpusContractError):
            raise
        raise contracts.CorpusContractError("invalid original report JSON bytes") from error
    if type(result) is not dict:
        _fail("original report must be a JSON object")
    return result


def _digest(value):
    return _sha(_plain(value, DEFAULT_LIMITS["max_replay_bytes"]))


def _owners():
    from . import (
        legal_cache_parent_occurrences,
        legal_parent_sentence_candidates,
        legal_parent_text_views,
    )

    return legal_parent_text_views, legal_cache_parent_occurrences, legal_parent_sentence_candidates


def _pins(owners):
    from . import (
        legal_parent_parquet_pages,
        legal_producer_lineage,
        legal_producer_page_lineage,
        legal_span_cache_intake,
        legal_span_provenance,
        legal_span_section_bridge,
    )

    modules = (contracts, source, cid_utils, *owners, legal_parent_parquet_pages, legal_producer_lineage,
               legal_producer_page_lineage, legal_span_cache_intake, legal_span_provenance)
    modules = (*modules, legal_span_section_bridge)
    paths = [Path(__file__).resolve(), *(Path(module.__file__).resolve() for module in modules)]
    return {str(path): _sha(path.read_bytes()) for path in paths}


def _inputs(report_bytes, expected_report_pins, replay_inputs, bounds):
    contracts.require_keys(report_bytes, REPORT_KEYS, "original report byte population")
    pins = contracts.clone_json(expected_report_pins)
    contracts.require_keys(pins, REPORT_KEYS, "independent original report pins")
    total = 0
    # All original byte pins precede any JSON parsing or operation-owner import.
    for key in REPORT_KEYS:
        contracts.require_keys(pins[key], {"raw_sha256", "canonical_sha256"}, "report hash namespaces")
        for field in ("raw_sha256", "canonical_sha256"):
            contracts.require_sha256(pins[key][field], field)
        raw = report_bytes[key]
        if type(raw) is not bytes or not 0 < len(raw) <= bounds["max_report_bytes"]:
            _fail("bounded complete immutable original report bytes required")
        if _sha(raw) != pins[key]["raw_sha256"]:
            _fail("original report differs from independently expected raw SHA256")
        total += len(raw)
    contracts.require_keys(replay_inputs, REPLAY_FIELDS, "complete fixed-owner replay inputs")
    residual = bounds["max_total_input_bytes"] - total
    if residual <= 0:
        _fail("aggregate complete original input bound exceeded before replay serialization")
    replay_raw = _plain(replay_inputs, min(bounds["max_replay_bytes"], residual))
    if total + len(replay_raw) > bounds["max_total_input_bytes"]:
        _fail("aggregate complete original input bound exceeded; no population may be omitted")
    replay = json.loads(replay_raw)
    owners = _owners()
    producer_pins = _pins(owners)
    reports = {key: _load(report_bytes[key], bounds["max_report_bytes"]) for key in REPORT_KEYS}
    views, occurrences, sentences = owners
    hashers = (views.parent_text_views_report_sha256, occurrences.cache_parent_occurrences_report_sha256,
               sentences.parent_sentence_candidates_report_sha256)
    for key, hasher in zip(REPORT_KEYS, hashers, strict=True):
        if hasher(reports[key]) != pins[key]["canonical_sha256"]:
            _fail("original report differs from independently expected FULL canonical owner hash")
    contracts.require_sha256(replay["expected_lineage_report_sha256"], "expected lineage report SHA256")
    try:
        views.validate_parent_text_views(reports["parent_text_views"],
            reports["parent_text_views"]["selected_rows_report"],
            expected_report_sha256=pins["parent_text_views"]["canonical_sha256"],
            **replay["parent_text_views_inputs"])
        occurrences.validate_cache_parent_occurrences(reports["cache_parent_occurrences"],
            replay["provenance_reports"], replay["lineage_report"], reports["parent_text_views"],
            expected_report_sha256=pins["cache_parent_occurrences"]["canonical_sha256"],
            expected_provenance_report_sha256s=replay["expected_provenance_report_sha256s"],
            expected_record_sha256s=replay["expected_record_sha256s"],
            expected_lineage_report_sha256=replay["expected_lineage_report_sha256"],
            lineage_inputs=replay["lineage_inputs"],
            expected_parent_text_views_report_sha256=pins["parent_text_views"]["canonical_sha256"],
            parent_text_views_inputs=replay["parent_text_views_inputs"])
        sentences.validate_parent_sentence_candidates(reports["parent_sentence_candidates"],
            reports["parent_text_views"],
            expected_report_sha256=pins["parent_sentence_candidates"]["canonical_sha256"],
            expected_parent_text_views_report_sha256=pins["parent_text_views"]["canonical_sha256"],
            parent_text_views_inputs=replay["parent_text_views_inputs"])
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        raise contracts.CorpusContractError("original reports refused complete fixed-owner regeneration") from error
    if _pins(owners) != producer_pins:
        _fail("parent occurrence producers changed during original report regeneration")
    bindings = {key: {
        "raw_cid": cid_for_bytes(report_bytes[key]), "raw_sha256": pins[key]["raw_sha256"],
        "raw_bytes": len(report_bytes[key]), "canonical_sha256": pins[key]["canonical_sha256"],
        "owner_schema": reports[key]["schema"],
    } for key in REPORT_KEYS}
    return reports, replay, bindings, owners, producer_pins


def _pointer(document, pointer):
    current = document
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        current = current[int(part)] if type(current) is list else current[part]
    return current


def _external(reports, bindings, report_key, pointer):
    binding = bindings[report_key]
    return {
        "report_key": report_key, "report_raw_cid": binding["raw_cid"],
        "report_raw_sha256": binding["raw_sha256"], "report_canonical_sha256": binding["canonical_sha256"],
        "json_pointer": pointer, "value_sha256": _digest(_pointer(reports[report_key], pointer)),
    }


def _identity(physical, descriptor):
    return {
        "repository": descriptor["repository"], "revision": descriptor["revision"],
        "path_in_repo": descriptor["path_in_repo"], "file_sha256": descriptor["sha256"],
        "file_bytes": descriptor["bytes"], "file_row_count": descriptor["row_count"],
        "row_ordinal": physical["row_ordinal"], "row_group": physical["row_group"],
        "row_group_ordinal": physical["row_group_ordinal"], "raw_row_sha256": physical["raw_row_sha256"],
        "field": "text",
    }


def build_parent_occurrence_corpus(report_bytes, *, expected_report_pins, replay_inputs, limits=None):
    """Replay complete parent/cache/sentence populations and project every role.

    ``report_bytes`` and ``expected_report_pins`` have exactly ``REPORT_KEYS``;
    each pin is ``{raw_sha256, canonical_sha256}``. Replay inputs have exactly
    ``REPLAY_FIELDS`` and delegate to the existing fixed owners. Each record and
    the root manifest retain common 1MiB limits. The detached collection has a
    separate finite aggregate bound; its source originals remain external.
    """
    bounds = _limits(limits)
    reports, replay, report_bindings, owners, producer_pins = _inputs(
        report_bytes, expected_report_pins, replay_inputs, bounds)
    records, refs, seen, count, retained = [], [], set(), Counter(), 0
    populations = {"parents": [], "cache_rows": [], "cache_matches": [], "roles": {role: [] for role in ROLES}}

    def put(kind, record):
        nonlocal retained
        cid = record["record_cid"]
        if cid in seen:
            _fail("duplicate projected record identity; separate evidence must not collapse")
        if len(records) >= bounds["max_records"]:
            _fail("complete projected record population exceeds bound; no truncation")
        raw = canonical_dag_json_bytes(record)
        retained += len(raw) + 1
        if retained > bounds["max_collection_bytes"]:
            _fail("complete detached collection byte bound exceeded")
        seen.add(cid)
        records.append(record)
        refs.append({"record_cid": cid, "sha256": _sha(raw)})
        count[kind] += 1
        return record

    view_report = reports["parent_text_views"]
    occurrence_report = reports["cache_parent_occurrences"]
    sentence_report = reports["parent_sentence_candidates"]
    descriptor = view_report["selected_rows_report"]["descriptor"]
    parents, versions, texts, occurrence_cache, context_cache = [], {}, {}, {}, {}
    for number, (envelope, physical) in enumerate(zip(view_report["views"], view_report["selected_rows_report"]["rows"], strict=True)):
        identity = _identity(physical, descriptor)
        identity_sha = _digest(identity)
        view = envelope["text_view"]
        version = None
        if view is not None:
            if identity != view["source_identity"]:
                _fail("literal view portable source identity differs from physical parent")
            text = view["text"]
            version = put("source_version", source.build_source_version(
                source_id="parent-literal-field:sha256:" + identity_sha,
                release_id=f"parquet:{identity['repository']}@{identity['revision']};sha256={identity['file_sha256']}",
                edition=UNDECLARED_EDITION,
                provision_id=f"physical-parent-row:{identity['row_ordinal']}:field:text",
                raw_bytes=text.encode("utf-8"), expected_raw_sha256=view["text_sha256"],
                extracted_text=text, expected_extracted_sha256=view["text_sha256"],
                extraction_profile=owners[0].PROFILE, normalization_profile="identity/v1", media_type="text/plain",
                historical_aliases=[],
            ))
            versions[number], texts[number] = version, text
        parent = put("parent", contracts.seal_record({
            "schema": PARENT_SCHEMA, "ordinal": number, "source_identity": identity,
            "source_identity_sha256": identity_sha,
            "source_version_cid": None if version is None else version["record_cid"],
            "view_sha256": None if view is None else view["view_sha256"],
            "raw_row_sha256": physical["raw_row_sha256"],
            "literal_legal_id_observation": occurrence_report["parent_views"][number]["literal_legal_id"],
            "disposition": envelope["disposition"], "issues": envelope["issues"],
            "external_binding": _external(reports, report_bindings, "parent_text_views", f"/views/{number}"),
            "original_row_binding": _external(reports, report_bindings, "parent_text_views", f"/selected_rows_report/rows/{number}/raw_row"),
            **FALSE_FLAGS, **UNSELECTED,
        }))
        parents.append(parent)
        populations["parents"].append(parent["record_cid"])

    def occurrence(number, selector):
        if number not in versions:
            _fail("a missing original text field cannot supply an occurrence")
        version, text = versions[number], texts[number]
        start, end = selector["char_start"], selector["char_end"]
        start_utf8, end_utf8 = selector["utf8byte_start"], selector["utf8byte_end"]
        key = (version["record_cid"], start, end, start_utf8, end_utf8)
        if key not in occurrence_cache:
            digest = _sha(text.encode("utf-8"))
            item = put("source_occurrence", source.build_source_occurrence(
                version, expected_raw_sha256=digest, extracted_text=text,
                expected_extracted_sha256=digest, start_char=start, end_char=end,
                start_utf8=start_utf8, end_utf8=end_utf8, historical_aliases=[],
            ))
            occurrence_cache[key] = item
            context_cache[item["record_cid"]] = put("context", source.build_context_declaration(
                item, expected_occurrence_cid=item["record_cid"], availability="required_unavailable",
                reason="Exact physical literal-field geometry supplies no qualified governing context.",
                context_references=[{"record_cid": version["record_cid"], "record_kind": "source_version",
                                     "purpose": "complete exact parent field; governing roles and context remain unresolved"}],
                missing_requirements=list(MISSING_CONTEXT),
            ))
        item = occurrence_cache[key]
        return item, context_cache[item["record_cid"]]

    for number, row in enumerate(occurrence_report["rows"]):
        cache_record = put("cache_row", contracts.seal_record({
            "schema": CACHE_ROW_SCHEMA, "ordinal": number, "cache_identity": row["cache_identity"],
            "cache_row_ordinal": row["row_ordinal"], "record_sha256": row["record_sha256"],
            "raw_row_sha256": row["raw_row_sha256"], "source_identity": row["source_identity"],
            **{field: row[field] for field in ("prior_provenance_classification", "prior_lineage_status",
                "prior_lineage_issues", "status", "issues", "producer_row_witness", "parent_row_witness",
                "local_parent_reference_view_indices", "source_text_sha256_matches_raw_declaration")},
            "comparisons": [{
                "view_index": comparison["view_index"], "parent_record_cid": parents[comparison["view_index"]]["record_cid"],
                **{field: comparison[field] for field in ("view_available", "literal_parent_legal_id",
                    "literal_cache_legal_id", "literal_legal_id_matches", "occurrence_count", "association_scope")},
            } for comparison in row["comparison_views"]],
            "external_binding": _external(reports, report_bindings, "cache_parent_occurrences", f"/rows/{number}"),
            "original_row_binding": _external(reports, report_bindings, "cache_parent_occurrences", f"/rows/{number}/raw_row"),
            **FALSE_FLAGS, **UNSELECTED,
        }))
        populations["cache_rows"].append(cache_record["record_cid"])
        for comparison in row["comparison_views"]:
            view_index = comparison["view_index"]
            for match_index, candidate in enumerate(comparison["occurrences"]):
                item, context = occurrence(view_index, candidate["selector"])
                binding = put("cache_match", contracts.seal_record({
                    "schema": MATCH_SCHEMA, "ordinal": len(populations["cache_matches"]),
                    "cache_row_record_cid": cache_record["record_cid"],
                    **{field: row[field] for field in ("cache_identity", "record_sha256", "raw_row_sha256")},
                    "cache_row_ordinal": row["row_ordinal"], "view_index": view_index, "match_index": match_index,
                    "parent_record_cid": parents[view_index]["record_cid"],
                    "source_version_cid": versions[view_index]["record_cid"],
                    "source_occurrence_cid": item["record_cid"], "context_cid": context["record_cid"],
                    "selector_sha256": candidate["selector"]["selector_sha256"],
                    "literal_legal_id_matches": comparison["literal_legal_id_matches"],
                    "local_parent_reference_view": view_index in row["local_parent_reference_view_indices"],
                    "external_binding": _external(reports, report_bindings, "cache_parent_occurrences",
                        f"/rows/{number}/comparison_views/{view_index}/occurrences/{match_index}"),
                    **FALSE_FLAGS, **UNSELECTED,
                }))
                populations["cache_matches"].append(binding["record_cid"])

    def role(number, name, selector, report_key, pointer, owner_id, observations):
        item, context = occurrence(number, selector)
        record = put("role", contracts.seal_record({
            "schema": ROLE_SCHEMA, "ordinal": sum(map(len, populations["roles"].values())), "role": name,
            "parent_record_cid": parents[number]["record_cid"],
            "source_version_cid": versions[number]["record_cid"],
            "source_occurrence_cid": item["record_cid"], "context_cid": context["record_cid"],
            "owner_id": owner_id, "observations": observations,
            "external_binding": _external(reports, report_bindings, report_key, pointer),
            **FALSE_FLAGS, **UNSELECTED,
        }))
        populations["roles"][name].append(record["record_cid"])

    for number, envelope in enumerate(view_report["views"]):
        view = envelope["text_view"]
        if view is None:
            continue
        for index, region in enumerate(view["regions"]):
            role(number, "region", region, "parent_text_views", f"/views/{number}/text_view/regions/{index}",
                 region["region_id"], {field: region[field] for field in ("region_kind", "legal_role_verified")})
        for index, marker in enumerate(view["marker_observations"]):
            role(number, "marker", marker, "parent_text_views", f"/views/{number}/text_view/marker_observations/{index}",
                 marker["marker_sha256"], {field: marker[field] for field in
                 ("marker_kind", "marker_text", "marker_origin", "legal_role_verified")})

    for number, row in enumerate(sentence_report["rows"]):
        for index, piece in enumerate(row["segments"]):
            role(number, "segment", piece["selector"], "parent_sentence_candidates", f"/rows/{number}/segments/{index}",
                 piece["sentence_candidate_id"], {
                     **{field: piece[field] for field in ("kind", "disposition", "issues", "dependency_candidate_ids",
                                                         "selected_as_legal_sentence", "autoformalization_eligible")},
                     "context_coverage_scope": piece["context"]["coverage_scope"],
                 })
            for name in ("prefix", "suffix"):
                window = piece["context"][name]
                if window is not None:
                    role(number, name, window, "parent_sentence_candidates", f"/rows/{number}/segments/{index}/context/{name}",
                         window["selector_sha256"], {"purpose": "bounded exact source-local window; legal context remains unresolved"})
        for index, candidate in enumerate(row["dependency_candidates"]):
            role(number, "dependency", candidate["selector"], "parent_sentence_candidates", f"/rows/{number}/dependency_candidates/{index}",
                 candidate["dependency_candidate_id"], {field: candidate[field] for field in
                 ("disposition", "target_candidates", "selected_target", "reference_scope_verified")})
        for index, boundary in enumerate(row["boundary_observations"]):
            role(number, "boundary", boundary["selector"], "parent_sentence_candidates", f"/rows/{number}/boundary_observations/{index}",
                 boundary["selector"]["selector_sha256"], {field: boundary[field] for field in
                 ("punctuation", "split_candidate", "issues", "boundary_verified")})

    parent_inputs = replay["parent_text_views_inputs"]
    lineage_inputs = replay["lineage_inputs"]
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "limits": bounds, "report_bindings": report_bindings,
        "replay_bindings": {
            "replay_inputs_canonical_sha256": _digest(replay),
            "expected_lineage_report_sha256": replay["expected_lineage_report_sha256"],
            "expected_record_sha256s": replay["expected_record_sha256s"],
            "expected_provenance_report_sha256s": replay["expected_provenance_report_sha256s"],
            "expected_parent_page_inputs_sha256": lineage_inputs["expected_parent_page_inputs_sha256"],
            "expected_witness_manifest_sha256": lineage_inputs["expected_witness_manifest_sha256"],
            **{field: parent_inputs[field] for field in ("expected_selected_rows_report_sha256",
                "expected_parent_descriptor_sha256", "expected_preflight_sha256", "row_ordinals", "expected_row_sha256s")},
        },
        "producer_pins": producer_pins, "record_refs": refs, "populations": populations,
        "counts": {
            "records": len(records), "record_kinds": dict(count), "physical_parent_rows": len(parents),
            "physical_cache_rows": len(populations["cache_rows"]),
            "comparison_cells": sum(len(row["comparison_views"]) for row in occurrence_report["rows"]),
            "cache_match_bindings": len(populations["cache_matches"]),
            "roles": {name: len(rows) for name, rows in populations["roles"].items()},
            "occurrence_status_counts": occurrence_report["status_counts"],
            "prior_lineage_status_counts": occurrence_report["prior_lineage_status_counts"],
            "source_characters": sentence_report["total_source_characters"],
            "source_utf8_bytes": view_report["total_text_utf8_bytes"],
        },
        "hash_recipes": HASH_RECIPES, "population_complete": True,
        "coverage_scope": "complete independently pinned supplied parent/cache/role populations only",
        "view": "candidate", **FALSE_FLAGS, **UNSELECTED,
    })
    bundle = {"manifest": manifest, "records": records}
    raw = _plain(bundle, bounds["max_collection_bytes"])
    if _pins(owners) != producer_pins:
        _fail("parent occurrence producers changed during complete projection")
    return json.loads(raw)


def validate_parent_occurrence_corpus(bundle, *, report_bytes, expected_report_pins, replay_inputs, limits=None):
    """Validate every seal/order/reference and replay all original owner inputs."""
    bounds = _limits(limits)
    contracts.require_keys(bundle, {"manifest", "records"}, "detached parent occurrence bundle")
    if type(bundle["records"]) is not list or len(bundle["records"]) > bounds["max_records"]:
        _fail("bounded complete record collection required")
    raw = _plain(bundle, bounds["max_collection_bytes"])
    detached = json.loads(raw)
    manifest = contracts.validate_record(detached["manifest"], schema=SCHEMA, fields=MANIFEST_FIELDS)
    schemas = {
        PARENT_SCHEMA: PARENT_FIELDS, CACHE_ROW_SCHEMA: CACHE_ROW_FIELDS,
        MATCH_SCHEMA: MATCH_FIELDS, ROLE_SCHEMA: ROLE_FIELDS,
        source.SOURCE_VERSION_SCHEMA: source._VERSION_FIELDS,
        source.SOURCE_OCCURRENCE_SCHEMA: source._OCCURRENCE_FIELDS,
        source.CONTEXT_DECLARATION_SCHEMA: source._CONTEXT_FIELDS,
    }
    refs, seen = [], set()
    for record in detached["records"]:
        schema = record.get("schema") if type(record) is dict else None
        if type(schema) is not str or schema not in schemas:
            _fail("unsupported projected record schema")
        checked = contracts.validate_record(record, schema=schema, fields=schemas[schema])
        cid = checked["record_cid"]
        if cid in seen:
            _fail("duplicate projected record identity")
        seen.add(cid)
        refs.append({"record_cid": cid, "sha256": _sha(canonical_dag_json_bytes(checked))})
    if manifest["record_refs"] != refs:
        _fail("root record population differs in membership, order, or complete record hashes")
    expected = build_parent_occurrence_corpus(report_bytes, expected_report_pins=expected_report_pins,
        replay_inputs=replay_inputs, limits=limits)
    if raw != _plain(expected, bounds["max_collection_bytes"]):
        _fail("parent occurrence corpus differs from complete independent regeneration")
    return detached


__all__ = ["build_parent_occurrence_corpus", "validate_parent_occurrence_corpus"]

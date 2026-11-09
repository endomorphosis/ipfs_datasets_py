"""Source-bound, unreviewed lexical scope proposals over whole sampled blocks.

This adapter preserves a caller's existing normative-scope declaration. It does
not compile a formal norm or resolve legal meaning. The legacy ``actor`` slot
does not resolve a passive grammatical subject to the agent of an action.
Operation owners load only after bounded, independently hashed input parsing.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "legal-source-norm-scope-proposal/v1"
PROFILE = "whole-sampled-block-unreviewed-lexical-scope/v1"
MAX_SCOPE_BYTES = 65536
MAX_SAMPLING_BYTES = 32 * 1024 * 1024
MAX_RAW_BYTES = 8_000_000
MAX_REPORT_BYTES = 1024 * 1024
AUTHORITY = dict.fromkeys(
    (
        "source_semantics_verified", "legal_roles_verified", "source_context_resolved",
        "context_closure_verified", "dependency_inventory_exhaustive",
        "declared_issues_exhaustive", "applicability_verified",
        "singular_plural_identity_verified", "governing_use_verified",
        "independently_reviewed", "accepted", "admitted", "formalized",
        "semantic_graph_admitted", "training_qualified", "training_gold_qualified",
        "evaluation_gold_qualified", "Lean_admitted", "proof_authority",
        "formal_norm_semantics_encoded", "lowering_authorized", "model_executed",
        "training_executed", "backend_executed",
    ),
    False,
)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SPAN_FIELDS = {"origin", "start", "end", "text", "offset_unit"}
_REFERENCE_FIELDS = {"schema", "record_cid", "sha256"}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LAZY_PINS = None


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value, maximum):
    """Refuse nonordinary, oversized and overly nested JSON before imports."""
    remaining = 2_000_000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 64, "norm scope JSON node/depth bound exceeded")
        if type(item) is dict:
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= maximum,
                  "bounded ordinary UTF8 string required")
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
        elif type(item) is float:
            _need(math.isfinite(item), "finite JSON required")
        else:
            raise ValueError("ordinary JSON values required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded finite ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete norm scope JSON byte bound exceeded; no truncation")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _load(raw, expected_sha256, label):
    _sha(expected_sha256, label)
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_SCOPE_BYTES,
          "bounded exact scope bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256,
          "independent scope byte pin differs: " + label)

    def pairs(entries):
        result = {}
        for key, value in entries:
            _need(key not in result, "duplicate JSON key refused: " + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON constant refused: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("ordinary duplicate-free scope JSON required: " + label) from error
    _need(type(value) is dict, "scope JSON object required: " + label)
    _wire(value, MAX_SCOPE_BYTES)
    return value


def _owners():
    from . import corpus_contracts as contracts
    from . import legal_source_sampling as sampling
    from . import legal_statutory_context_v2 as context
    from ..legal_ir import canonical_statement_scope as scope
    from ..legal_ir import canonical_statement_scope_bridge as bridge
    from ..legal_ir import canonical_contracts as scope_contracts
    from ipfs_datasets_py.utils import cid_utils

    return sampling, context, scope, bridge, contracts, cid_utils, scope_contracts


def _pins(owners):
    global _LAZY_PINS
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "norm scope owner changed since import")
    sampling, context = owners[:2]
    modules = (*owners, sampling.sources, sampling.views, sampling.contexts,
               context.obligations, sampling.views.custody)
    pins = {str(Path(module.__file__).resolve()):
            hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules}
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _LAZY_PINS is None:
        _LAZY_PINS = pins
    _need(pins == _LAZY_PINS, "norm scope operation owners changed since first use")
    return dict(pins)


def _reference(record):
    return {"schema": record["schema"], "record_cid": record["record_cid"],
            "sha256": _digest(record)}


def _selected(report, selected_unit_ref, sampling):
    _need(report["status"] == "whole_source_blocks_prepared",
          "complete sampled source view required")
    _need(selected_unit_ref in report["unit_refs"], "selected exact sealed unit reference absent")
    by_cid = {record["record_cid"]: record for record in report["records"]}
    _need(len(by_cid) == len(report["records"]), "duplicate sampled record identity")
    unit = by_cid.get(selected_unit_ref["record_cid"])
    _need(unit is not None and _reference(unit) == selected_unit_ref,
          "selected sealed unit reference differs")
    _need(unit["schema"] == sampling.UNIT_SCHEMA
          and unit["sampling_stratum"] == "candidate_statute_paragraph"
          and unit["candidate_input"] is True
          and unit["paragraph_fragment_withheld"] is False,
          "one complete unfragmented candidate statute paragraph required")
    records = {"unit": unit}
    for name, field in (("source_version", "source_version_ref"),
                        ("source_occurrence", "source_occurrence_ref"),
                        ("context", "context_ref")):
        reference = unit[field]
        record = by_cid.get(reference["record_cid"])
        _need(record is not None and _reference(record) == reference,
              "sampled source/context/version reference differs")
        records[name] = record
    context = records["context"]
    _need(context["availability"] == "required_unavailable"
          and context["missing_requirements"] == list(sampling.contexts.DEPENDENCY_KINDS),
          "original complete open context obligations required")
    return records


def _literal_accounting(request, declaration):
    _need(request["context"] == {
        "role": "required_unavailable", "text": "", "bindings": {},
        "sha256": hashlib.sha256(b"").hexdigest(),
    }, "original required-unavailable empty context must remain open")
    coverage = declaration["coverage"]
    _need(coverage["declared_status"] in {"partial", "unassessed"}
          and bool(declaration["unresolved"]),
          "partial or unassessed semantic coverage with explicit unresolved issues required")
    end = 0
    for start, stop in sorted((segment["span"]["start"], segment["span"]["end"])
                              for segment in coverage["segments"]):
        _need(start <= end, "full literal accounting has an uncovered source gap")
        end = max(end, stop)
    _need(end == len(request["source_text"]),
          "full literal accounting omits a source suffix or complete source")


def _anchors(value, path=""):
    if type(value) is dict:
        if set(value) == _SPAN_FIELDS:
            yield path, value
        else:
            for key, child in value.items():
                pointer = key.replace("~", "~0").replace("/", "~1")
                yield from _anchors(child, path + "/" + pointer)
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from _anchors(child, path + "/" + str(index))


def prepare_sampled_norm_scope_v1(
    sampling_report, raw_html, scope_request_raw, scope_declaration_raw, *,
    expected_sampling_report_sha256, selected_unit_ref,
    expected_scope_request_sha256, expected_scope_declaration_sha256,
    **sampler_replay_inputs,
):
    """Retain exact caller lexical proposals; refuse incomplete literal custody.

    ``sampler_replay_inputs`` are the unchanged ``prepare_source_sampling``
    inputs: descriptor, independent descriptor/raw pins and byte count, plus
    optional lowered view/sampling limits. A selected unit is an exact sealed
    reference, not a list index, ordinal, spelling search or cache coordinate.
    """
    request = _load(scope_request_raw, expected_scope_request_sha256, "scope request")
    declaration = _load(scope_declaration_raw, expected_scope_declaration_sha256,
                        "scope declaration")
    _sha(expected_sampling_report_sha256, "complete sampling report")
    _need(type(raw_html) is bytes and 0 < len(raw_html) <= MAX_RAW_BYTES,
          "complete bounded independent source HTML bytes required")
    _need(type(selected_unit_ref) is dict and set(selected_unit_ref) == _REFERENCE_FIELDS,
          "closed selected sealed unit reference required")
    _sha(selected_unit_ref["sha256"], "selected sealed unit")
    _wire(selected_unit_ref, 4096)
    _wire(sampler_replay_inputs, MAX_SCOPE_BYTES)
    required = {"descriptor", "expected_descriptor_sha256", "expected_raw_sha256",
                "expected_raw_bytes"}
    _need(required <= set(sampler_replay_inputs)
          and not (set(sampler_replay_inputs) - required - {"view_limits", "limits"}),
          "closed original sampler replay inputs required")
    for key in ("expected_descriptor_sha256", "expected_raw_sha256"):
        _sha(sampler_replay_inputs[key], key)
    _need(type(sampler_replay_inputs["expected_raw_bytes"]) is int
          and sampler_replay_inputs["expected_raw_bytes"] == len(raw_html)
          and sampler_replay_inputs["expected_raw_sha256"] == hashlib.sha256(raw_html).hexdigest(),
          "independent complete source HTML byte pins differ")
    _need(type(sampler_replay_inputs["descriptor"]) is dict
          and _digest(sampler_replay_inputs["descriptor"], MAX_SCOPE_BYTES)
          == sampler_replay_inputs["expected_descriptor_sha256"],
          "independent acquisition descriptor canonical pin differs")
    _need(type(sampling_report) is dict, "ordinary complete sampling report required")
    _need(_digest(sampling_report, MAX_SAMPLING_BYTES) == expected_sampling_report_sha256,
          "independent complete sampling report pin differs")

    owners = _owners()
    sampling, context, scope, bridge = owners[:4]
    pins = _pins(owners)
    checked = sampling.validate_source_sampling(
        sampling_report, raw_html, expected_report_sha256=expected_sampling_report_sha256,
        **sampler_replay_inputs)
    records = _selected(checked, selected_unit_ref, sampling)
    view = checked["document_view_report"]
    view_inputs = {key: sampler_replay_inputs[key] for key in
                   ("descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes")}
    if "view_limits" in sampler_replay_inputs:
        view_inputs["limits"] = sampler_replay_inputs["view_limits"]
    source = records["source_occurrence"]
    selector_args = dict(expected_report_sha256=checked["document_view_report_sha256"],
                         **view_inputs)
    selection = context.source_selector_v2(
        view, raw_html, char_start=source["start_char"], char_end=source["end_char"],
        **selector_args)
    _need(request.get("source_text") == selection["text"],
          "scope source must equal the complete selected source paragraph")
    _need((source["start_utf8"], source["end_utf8"], source["span_text"])
          == (selection["utf8_byte_start"], selection["utf8_byte_end"], selection["text"]),
          "sampled source occurrence and V2 selector geometry differ")
    expected_input_sha256 = _digest(request, MAX_SCOPE_BYTES)
    validation = scope.validate_scope_declaration(
        request, declaration, expected_input_sha256=expected_input_sha256)
    _literal_accounting(request, declaration)
    open_packet = context.build_context_packet_v2(
        view, raw_html, char_start=selection["char_start"], char_end=selection["char_end"],
        **selector_args)
    context_validation = context.validate_context_packet_v2(
        open_packet, view, raw_html, expected_selector=selection, **selector_args)

    mapped, cache = [], {(selection["char_start"], selection["char_end"]): selection}
    for path, anchor in _anchors(declaration):
        _need(anchor["origin"] == "source", "unavailable context cannot supply an anchor")
        left = selection["char_start"] + anchor["start"]
        right = selection["char_start"] + anchor["end"]
        if (left, right) not in cache:
            cache[(left, right)] = context.source_selector_v2(
                view, raw_html, char_start=left, char_end=right, **selector_args)
        selected = cache[(left, right)]
        _need(selected["text"] == anchor["text"], "mapped source anchor text differs")
        mapped.append({"declaration_path": path, "local_anchor": anchor,
                       "document_selector": selected})
    bridge_view = bridge.prepare_scope_bridge_view(
        request, declaration, expected_input_sha256=expected_input_sha256)
    bridge_validation = bridge.validate_scope_bridge_view(
        bridge_view, request, expected_input_sha256=expected_input_sha256)
    compatibility = scope.assess_flat_profile_compatibility(declaration)
    _need(all(row["status"] == "unavailable" for row in compatibility["profiles"].values())
          and compatibility["lowered_ir"] is None,
          "open partial scope must not acquire an available legacy route or lowered IR")
    result = {
        "schema": SCHEMA, "profile": PROFILE,
        "status": "unreviewed_lexical_scope_transport_retained",
        "input_pins": {
            "sampling_report_full_canonical_sha256": expected_sampling_report_sha256,
            "selected_unit_ref": selected_unit_ref,
            "scope_request_raw_sha256": expected_scope_request_sha256,
            "scope_request_raw_bytes": len(scope_request_raw),
            "scope_request_canonical_sha256": expected_input_sha256,
            "scope_declaration_raw_sha256": expected_scope_declaration_sha256,
            "scope_declaration_raw_bytes": len(scope_declaration_raw),
            "scope_declaration_canonical_sha256": _digest(declaration, MAX_SCOPE_BYTES),
            "sampler_replay_inputs": sampler_replay_inputs,
        },
        "source_records": records, "source_selector": selection,
        "source_context_packet": open_packet,
        "source_context_validation": context_validation,
        "scope_request": request, "scope_declaration": declaration,
        "scope_validation": validation, "scope_bridge_view": bridge_view.to_dict(),
        "scope_bridge_validation": bridge_validation, "flat_compatibility": compatibility,
        "anchor_mappings": mapped,
        "literal_accounting_complete": True,
        "literal_accounting_scope": "every selected source character assigned a caller coverage disposition; not semantic completeness",
        "declared_semantic_coverage": declaration["coverage"]["declared_status"],
        "original_context_preserved": True,
        "external_context_nominations_applied": False,
        "formal_norm_ast": None, "lowered_ir": None, "graph": None,
        "accepted_lookup": None, "governing_definition_use": None,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "masks": dict.fromkeys(scope.MASKS, 0), "authority": dict(AUTHORITY),
        "model_calls": 0, "training_calls": 0, "native_processes": 0,
        "producer_pins": pins,
        "limitations": [
            "Caller lexical roles and attachment are unreviewed; transport validation does not establish legal meaning.",
            "The legacy actor slot does not resolve a passive grammatical subject to the agent of an action.",
            "Full literal accounting includes unresolved and unsupported text; it is not complete semantic coverage.",
            "Original required-unavailable context remains open; separate source-context nominations are retained elsewhere and are not applied here.",
            "The six context obligations and caller-declared issues are not exhaustive dependency or ambiguity inventories.",
            "No approval necessity, cardinality frame, purpose, antecedent, plural identity, applicability or governing definition use is decided.",
            "No formal norm AST, lowering, graph, lookup, native process, learned target, review or admission is supplied.",
        ],
    }
    _need(_pins(owners) == pins, "norm scope operation owners changed during preparation")
    result["report_sha256"] = _digest(result)
    return json.loads(_wire(result, MAX_REPORT_BYTES))


def sampled_norm_scope_report_sha256(report):
    """Full canonical output hash, distinct from its internal payload hash."""
    return _digest(report)


def validate_sampled_norm_scope_v1(
    report, sampling_report, raw_html, scope_request_raw, scope_declaration_raw, *,
    expected_report_sha256, **preparation_inputs,
):
    """Regenerate the complete proposal against original independent inputs."""
    _sha(expected_report_sha256, "complete norm scope report")
    supplied = _wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(supplied).hexdigest() == expected_report_sha256,
          "independent complete norm scope report pin differs")
    expected = prepare_sampled_norm_scope_v1(
        sampling_report, raw_html, scope_request_raw, scope_declaration_raw,
        **preparation_inputs)
    _need(supplied == _wire(expected, MAX_REPORT_BYTES),
          "norm scope proposal differs from authoritative regeneration")
    return {"schema": "legal-source-norm-scope-validation/v1",
            "status": "validated_source_scope_transport_only",
            "report_full_canonical_sha256": expected_report_sha256,
            "selected_unit_ref": expected["input_pins"]["selected_unit_ref"],
            "literal_accounting_complete": True, "formal_norm_ast": None,
            "lowered_ir": None, "authority": dict(AUTHORITY),
            "masks": dict(expected["masks"]), "model_calls": 0, "native_processes": 0}




# The original HTML-sampling API and its pin state remain independent. Parent
# scope is a literal-occurrence custody profile, not a whole-paragraph claim.
PARENT_SCHEMA = "legal-parent-norm-scope-proposal/v1"
PARENT_PROFILE = "whole-selected-parent-literal-occurrence-unreviewed-lexical-scope/v1"
PARENT_ANCHOR_SCHEMA = "legal-parent-norm-scope-anchor/v1"
MAX_PARENT_INPUT_BYTES = 64 * 1024 * 1024
_PARENT_PINS = None
_PARENT_REPORT_KEYS = {"parent_text_views", "cache_parent_occurrences", "parent_sentence_candidates"}
_PARENT_REPLAY_REQUIRED = {
    "parent_bundle", "scope_request_raw", "scope_declaration_raw", "expected_manifest_cid",
    "source_occurrence_cid", "companion_record_cid", "report_bytes", "expected_report_pins",
    "replay_inputs", "expected_scope_request_sha256", "expected_scope_declaration_sha256",
}
_PARENT_LIMITS = {"max_report_bytes": 8 * 1024**2, "max_replay_bytes": 16 * 1024**2,
                  "max_total_input_bytes": 32 * 1024**2, "max_records": 8192,
                  "max_collection_bytes": 16 * 1024**2}


def _parent_owners():
    from . import legal_semantic_graph as graph
    from . import corpus_parent_occurrence_adapter as parent
    from . import corpus_source
    from ..legal_ir import canonical_statement_scope as scope
    from ..legal_ir import canonical_statement_scope_bridge as bridge
    return graph, parent, corpus_source, scope, bridge


def _parent_pins(owners=None):
    """Trusted parent closure; never interpret caller producer-pin paths."""
    global _PARENT_PINS
    owners = _parent_owners() if owners is None else owners
    _, parent, _, _, _ = owners
    from ..legal_ir import canonical_contracts
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "parent norm scope owner changed since import")
    pins = parent._pins(parent._owners())
    for module in (*owners, canonical_contracts):
        path = str(Path(module.__file__).resolve())
        value = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        _need(path not in pins or pins[path] == value, "inconsistent parent producer closure")
        pins[path] = value
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _PARENT_PINS is None:
        _PARENT_PINS = dict(pins)
    _need(pins == _PARENT_PINS, "parent norm scope operation owners changed since first use")
    return dict(pins)


def _parent_snapshot(arguments):
    """Detach ordinary JSON and original bytes before physical replay imports.

    The complete three-report population stays mandatory. Individual defaults
    are the unchanged parent owner's limits; the aggregate includes the bundle,
    reports, replay inputs, independent pins and lexical declarations.
    """
    _need(type(arguments) is dict and _PARENT_REPLAY_REQUIRED <= set(arguments)
          and not (set(arguments) - _PARENT_REPLAY_REQUIRED - {"limits"}),
          "closed complete parent scope replay arguments required")
    _load(arguments["scope_request_raw"], arguments["expected_scope_request_sha256"], "scope request")
    _load(arguments["scope_declaration_raw"], arguments["expected_scope_declaration_sha256"],
          "scope declaration")
    for key in ("expected_manifest_cid", "source_occurrence_cid", "companion_record_cid"):
        value = arguments[key]
        _need(type(value) is str and 0 < len(value) <= 256 and "\x00" not in value,
              "bounded explicit parent identity required: " + key)
    limits = arguments.get("limits")
    _need(limits is None or type(limits) is dict, "closed lower-only parent limits required")
    for key, value in (limits or {}).items():
        _need(key in _PARENT_LIMITS and type(value) is int and 0 < value <= _PARENT_LIMITS[key],
              "unknown, noninteger or raised parent limit")
    reports, pins = arguments["report_bytes"], arguments["expected_report_pins"]
    _need(type(reports) is dict and set(reports) == _PARENT_REPORT_KEYS
          and type(pins) is dict and set(pins) == _PARENT_REPORT_KEYS,
          "complete original parent reports and independent pins required")
    detached, commitments, total = {}, {}, 0
    for key, value in arguments.items():
        if key == "report_bytes":
            detached[key] = {}
            for name in sorted(_PARENT_REPORT_KEYS):
                raw = value[name]
                _need(type(raw) is bytes and 0 < len(raw) <= _PARENT_LIMITS["max_report_bytes"],
                      "bounded complete original parent report bytes required: " + name)
                row = pins[name]
                _need(type(row) is dict and set(row) == {"raw_sha256", "canonical_sha256"},
                      "closed raw and canonical parent report pins required")
                for field in row:
                    _sha(row[field], name + "/" + field)
                _need(hashlib.sha256(raw).hexdigest() == row["raw_sha256"],
                      "independent parent report raw pin differs: " + name)
                detached[key][name] = raw
                commitments[key + "/" + name] = {
                    "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                    "encoding": "original_bytes"}
                total += len(raw)
            continue
        maximum = {"parent_bundle": 16 * 1024**2, "replay_inputs": 16 * 1024**2,
                   "scope_request_raw": MAX_SCOPE_BYTES,
                   "scope_declaration_raw": MAX_SCOPE_BYTES}.get(key, MAX_SCOPE_BYTES)
        if key in {"scope_request_raw", "scope_declaration_raw"}:
            raw = value
            detached[key] = value
        else:
            raw = _wire(value, maximum)
            detached[key] = json.loads(raw)
        commitments[key] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "encoding": "original_bytes" if type(value) is bytes else "canonical_json"}
        total += len(raw)
    _need(total <= MAX_PARENT_INPUT_BYTES, "aggregate complete parent scope input bound exceeded")
    _need(type(detached["parent_bundle"]) is dict and type(detached["replay_inputs"]) is dict,
          "ordinary complete parent bundle and physical replay input objects required")
    return detached, commitments


def _parent_finish(checks, primary):
    """Run every closing check; never replace the original operation error."""
    failures = []
    for check in checks:
        try:
            check()
        except BaseException as error:
            failures.append(error)
    if primary is not None:
        for error in failures:
            primary.add_note("secondary parent custody failure: " + type(error).__name__ + ": " + str(error))
    elif failures:
        first, *others = failures
        for error in others:
            first.add_note("additional parent custody failure: " + type(error).__name__ + ": " + str(error))
        raise first


def _parent_serialized_fence(value, serialized, maximum, encoder):
    """Recheck mutable returned JSON after the operation encoder has returned.

    The final direct standard-library encoding also detects mutation performed
    by an instrumented encoder after it produced otherwise matching bytes.
    """
    _need(encoder(value, maximum) == serialized, "serialized parent output changed")
    try:
        closing = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("serialized parent output no longer ordinary finite JSON") from error
    _need(closing == serialized, "parent output mutated after final encoding")


def _parent_binding(graph, arguments):
    result = graph.bind_parent_source_occurrence(
        arguments["parent_bundle"], expected_manifest_cid=arguments["expected_manifest_cid"],
        source_occurrence_cid=arguments["source_occurrence_cid"],
        companion_record_cid=arguments["companion_record_cid"], report_bytes=arguments["report_bytes"],
        expected_report_pins=arguments["expected_report_pins"], replay_inputs=arguments["replay_inputs"],
        limits=arguments.get("limits"))
    graph._check_parent_source(result)
    _need(result["parent_manifest_cid"] == arguments["expected_manifest_cid"]
          and result["selector"]["record_cid"] == arguments["source_occurrence_cid"]
          and result["companion_record"]["record_cid"] == arguments["companion_record_cid"],
          "replayed parent selection differs from explicit occurrence and companion")
    _wire(result, MAX_REPORT_BYTES)
    return result


def prepare_parent_norm_scope_v1(
    parent_bundle, scope_request_raw, scope_declaration_raw, *, expected_manifest_cid,
    source_occurrence_cid, companion_record_cid, report_bytes, expected_report_pins,
    replay_inputs, expected_scope_request_sha256, expected_scope_declaration_sha256, limits=None,
):
    """Retain unreviewed lexical scope over one exact original literal occurrence.

    Both opening and closing replay require the full original parent population
    and physical file/row witnesses. Identity normalization, undeclared edition
    and all six unavailable context obligations remain unchanged.
    """
    arguments = dict(parent_bundle=parent_bundle, scope_request_raw=scope_request_raw,
        scope_declaration_raw=scope_declaration_raw, expected_manifest_cid=expected_manifest_cid,
        source_occurrence_cid=source_occurrence_cid, companion_record_cid=companion_record_cid,
        report_bytes=report_bytes, expected_report_pins=expected_report_pins,
        replay_inputs=replay_inputs, expected_scope_request_sha256=expected_scope_request_sha256,
        expected_scope_declaration_sha256=expected_scope_declaration_sha256, limits=limits)
    detached, commitments = _parent_snapshot(arguments)
    request = _load(scope_request_raw, expected_scope_request_sha256, "scope request")
    declaration = _load(scope_declaration_raw, expected_scope_declaration_sha256, "scope declaration")
    request_wire, declaration_wire = _wire(request, MAX_SCOPE_BYTES), _wire(declaration, MAX_SCOPE_BYTES)
    owners = _parent_owners()
    graph, parent, _, scope, bridge = owners
    pins = _parent_pins(owners)
    opening = binding = None
    opening_wire = None
    result = serialized = None
    replay_started = False
    primary = None

    def fence():
        _need(_parent_snapshot(arguments)[1] == commitments,
              "original parent scope inputs changed during preparation")
        _need(_parent_snapshot(detached)[1] == commitments,
              "detached parent scope replay inputs changed during preparation")
        _need(_wire(request, MAX_SCOPE_BYTES) == request_wire
              and _wire(declaration, MAX_SCOPE_BYTES) == declaration_wire,
              "parsed scope request or declaration changed during preparation")
        _need(_parent_pins(owners) == pins, "parent scope producer sources changed during preparation")

    def binding_fence():
        if opening_wire is not None:
            _need(_wire(opening, MAX_REPORT_BYTES) == opening_wire
                  and _wire(binding, MAX_REPORT_BYTES) == opening_wire,
                  "opening parent binding changed during preparation")

    def closing_replay():
        if replay_started:
            closed = _parent_binding(graph, detached)
            if opening_wire is not None:
                _need(_wire(closed, MAX_REPORT_BYTES) == opening_wire,
                      "closing original parent replay differs from opening binding")

    def output_fence():
        if serialized is not None:
            _parent_serialized_fence(result, serialized, MAX_REPORT_BYTES, _wire)

    try:
        fence()
        replay_started = True
        opening = _parent_binding(graph, detached)
        opening_wire = _wire(opening, MAX_REPORT_BYTES)
        binding = json.loads(opening_wire)
        fence()
        source = binding["selector"]
        _need(request.get("source_text") == source["span_text"],
              "scope source must equal the whole selected original literal occurrence")
        _need(binding["edition"] == parent.UNDECLARED_EDITION,
              "parent source edition must remain undeclared")
        expected_input = hashlib.sha256(request_wire).hexdigest()
        validation = scope.validate_scope_declaration(request, declaration, expected_input_sha256=expected_input)
        _literal_accounting(request, declaration)
        mapped = []
        for path, anchor in _anchors(declaration):
            left, right = anchor["start"], anchor["end"]
            _need(anchor["origin"] == "source" and anchor["offset_unit"] == "unicode_character_half_open"
                  and type(left) is int and type(right) is int
                  and 0 <= left < right <= len(source["span_text"])
                  and anchor["text"] == source["span_text"][left:right],
                  "exact nonempty source-local anchor required; unavailable context cannot supply one")
            selection = {
                "schema": PARENT_ANCHOR_SCHEMA,
                "source_version_cid": source["source_version_cid"],
                "source_occurrence_cid": source["record_cid"],
                "coordinate_system": source["coordinate_system"],
                "normalization_profile": "identity/v1",
                "char_start": source["start_char"] + left, "char_end": source["start_char"] + right,
                "utf8_byte_start": source["start_utf8"] + len(source["span_text"][:left].encode("utf-8")),
                "utf8_byte_end": source["start_utf8"] + len(source["span_text"][:right].encode("utf-8")),
                "text": anchor["text"], "text_sha256": hashlib.sha256(anchor["text"].encode("utf-8")).hexdigest(),
            }
            mapped.append({"declaration_path": path, "local_anchor": anchor, "parent_selector": selection})
        bridge_view = bridge.prepare_scope_bridge_view(request, declaration, expected_input_sha256=expected_input)
        bridge_validation = bridge.validate_scope_bridge_view(bridge_view, request, expected_input_sha256=expected_input)
        compatibility = scope.assess_flat_profile_compatibility(declaration)
        _need(all(row["status"] == "unavailable" for row in compatibility["profiles"].values())
              and compatibility["lowered_ir"] is None,
              "open parent lexical scope cannot acquire a legacy lowering route")
        result = {
            "schema": PARENT_SCHEMA, "profile": PARENT_PROFILE,
            "status": "unreviewed_parent_literal_scope_transport_retained",
            "input_pins": {"parent_manifest_cid": expected_manifest_cid,
                "source_occurrence_cid": source_occurrence_cid, "companion_record_cid": companion_record_cid,
                "scope_request_raw_sha256": expected_scope_request_sha256,
                "scope_declaration_raw_sha256": expected_scope_declaration_sha256,
                "scope_request_canonical_sha256": expected_input, "original_inputs": commitments},
            "parent_source_binding": binding,
            "source_selector": source, "source_context_record": binding["context"],
            "source_records": {"source_version": binding["source_version"], "source_occurrence": source,
                               "context": binding["context"], "parent_record": binding["parent_record"],
                               "companion_record": binding["companion_record"],
                               "cache_row_record": binding["cache_row_record"]},
            "scope_request": request, "scope_declaration": declaration,
            "scope_validation": validation, "scope_bridge_view": bridge_view.to_dict(),
            "scope_bridge_validation": bridge_validation, "flat_compatibility": compatibility,
            "anchor_mappings": mapped, "literal_accounting_complete": True,
            "literal_accounting_scope": "whole selected literal occurrence; caller coverage dispositions are not semantic completeness",
            "declared_semantic_coverage": declaration["coverage"]["declared_status"],
            "source_region_role_verified": False, "whole_paragraph_verified": False,
            "whole_law_verified": False, "original_context_preserved": True,
            "external_context_nominations_applied": False,
            "formal_norm_ast": None, "lowered_ir": None, "graph": None,
            "accepted_lookup": None, "governing_definition_use": None,
            "training_mask": 0, "evaluation_gold_mask": 0, "masks": dict.fromkeys(scope.MASKS, 0),
            "authority": dict(AUTHORITY), "model_calls": 0, "training_calls": 0, "native_processes": 0,
            "producer_pins": pins,
            "limitations": [
                "The selected original literal occurrence may be a fragment or unclassified region; no paragraph, whole law or governing body is established.",
                "Exact physical row, field, occurrence and byte custody does not establish authenticity, edition, legal meaning or independently reviewed roles.",
                "Edition remains undeclared; all six original required-unavailable context obligations remain open and are not an exhaustive dependency inventory.",
                "Every literal character is accounted for by caller dispositions, including unresolved text; semantic completeness and attachment remain unreviewed.",
                "No formal norm AST, lowered IR, selected interpretation, graph admission, learned target, review, model or Lean execution is supplied.",
            ],
        }
        result["report_sha256"] = _digest(result)
        serialized = _wire(result, MAX_REPORT_BYTES)
        result = json.loads(serialized)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        _parent_finish((fence, binding_fence, closing_replay, fence, binding_fence, output_fence, fence), primary)


def parent_norm_scope_report_sha256(report):
    """Hash the full bounded parent report, including its internal payload seal."""
    return _digest(report)


def validate_parent_norm_scope_v1(report, *args, expected_report_sha256, **kwargs):
    """Regenerate parent scope against original inputs; no semantic authority."""
    _sha(expected_report_sha256, "complete parent norm scope report")
    offered = _wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(offered).hexdigest() == expected_report_sha256,
          "independent complete parent norm scope report pin differs")
    _need(type(report) is dict and report.get("schema") == PARENT_SCHEMA
          and report.get("profile") == PARENT_PROFILE, "explicit parent literal scope profile required")
    primary = None
    result = serialized = None
    try:
        expected = prepare_parent_norm_scope_v1(*args, **kwargs)
        _need(offered == _wire(expected, MAX_REPORT_BYTES),
              "parent scope report differs from complete original regeneration")
        result = {"schema": "legal-parent-norm-scope-validation/v1",
            "status": "validated_parent_literal_scope_transport_only",
            "report_full_canonical_sha256": expected_report_sha256,
            "source_occurrence_cid": expected["input_pins"]["source_occurrence_cid"],
            "literal_accounting_complete": True, "formal_norm_ast": None, "lowered_ir": None,
            "authority": dict(AUTHORITY), "masks": dict(expected["masks"]),
            "model_calls": 0, "native_processes": 0}
        serialized = _wire(result, MAX_REPORT_BYTES)
        result = json.loads(serialized)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_fence():
            _parent_serialized_fence(report, offered, MAX_REPORT_BYTES, _wire)
        def result_fence():
            if serialized is not None:
                _parent_serialized_fence(result, serialized, MAX_REPORT_BYTES, _wire)
        _parent_finish((offered_fence, result_fence), primary)


__all__ = ["prepare_sampled_norm_scope_v1", "validate_sampled_norm_scope_v1",
           "sampled_norm_scope_report_sha256", "prepare_parent_norm_scope_v1",
           "validate_parent_norm_scope_v1", "parent_norm_scope_report_sha256"]

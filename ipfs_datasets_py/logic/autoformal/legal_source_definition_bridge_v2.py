"""Explicit unary definition candidates over the complete official V2 view.

The source view, occurrences and Boolean builder retain their existing owners.
Declarations are unreviewed caller interpretations, never source applicability,
legal truth, training gold or corpus admission. Operation owners load lazily.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from . import legal_definition_boolean as boolean

REQUEST_SCHEMA = "legal-source-definition-request/v2"
SCHEMA = "legal-source-definition-bridge/v2"
PROFILE = "declared-scope-v2-source-unary-predicate-definition/v1"
PARENT_REQUEST_SCHEMA = "legal-parent-definition-request/v1"
PARENT_SCHEMA = "legal-parent-definition-bridge/v1"
PARENT_PROFILE = "declared-literal-parent-unary-predicate-definition/v1"
FAMILIES = ("fol", "tdfol")
DEFAULT_LIMITS = {
    "max_occurrences": 256,
    "max_bindings": 512,
    "max_report_bytes": 1024 * 1024,
    "max_contributors": 256,
    "max_literal_bytes": 4096,
    "max_expression_depth": 12,
    "max_expression_nodes": 128,
    "max_operands": 16,
    "max_sampling_report_bytes": 32 * 1024 * 1024,
    "max_input_bytes": 48 * 1024 * 1024,
}
PARENT_DEFAULT_LIMITS = {key: value for key, value in DEFAULT_LIMITS.items()
    if key not in ("max_sampling_report_bytes", "max_input_bytes")}
_PARENT_DECLARATION_FIELDS = {"declaration_id", "interpretation_status", "source_binding_sha256",
    "scope", "scope_kind", "scope_span", "contributor_spans", "head", "definition_cue", "body"}
AUTHORITY = dict.fromkeys(
    (
        "source_authenticity_verified",
        "publisher_authenticity_verified",
        "legal_currentness_verified",
        "source_semantics_verified",
        "legal_roles_verified",
        "governing_source_binding_verified",
        "applicability_semantics_verified",
        "context_closure_verified",
        "definition_operator_interpreted",
        "independently_reviewed",
        "admitted",
        "formalized",
        "training_qualified",
        "training_gold_qualified",
        "semantic_graph_admitted",
        "Lean_admitted",
        "lean_compilation_verified",
        "backend_executed",
        "proof_authority",
        "cross_family_equivalence_verified",
    ),
    False,
)
_REQUEST_FIELDS = {"schema", "profile", "family", "declaration"}
_DECLARATION_FIELDS = {
    "declaration_id",
    "interpretation_status",
    "source_version_ref",
    "normalized_view_id",
    "contributor_unit_refs",
    "scope_unit_ref",
    "scope_span",
    "head",
    "definition_cue",
    "body",
    "applicability",
}
_APPLICABILITY_FIELDS = {
    "scope_kind",
    "scope_id",
    "jurisdiction_id",
    "instrument_id",
    "legal_as_of_civil_date",
    "source_edition",
    "source_release_id",
}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_BOOLEAN_PIN = hashlib.sha256(Path(boolean.__file__).read_bytes()).hexdigest()


def _need(value, message):
    if not value:
        raise ValueError(message)


def _closed(value, keys, label):
    _need(
        type(value) is dict and set(value) == set(keys), "closed " + label + " required"
    )


def _canonical(value, maximum):
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("finite canonical UTF8 definition JSON required") from error
    _need(
        len(raw) <= maximum,
        "complete definition JSON byte bound exceeded; truncation refused",
    )
    return raw


def wire(value):
    """Canonical UTF8 bytes under the unchanged one-MiB record envelope."""
    return _canonical(value, DEFAULT_LIMITS["max_report_bytes"])


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def _sha(value, label):
    _need(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
        label + " SHA256 required",
    )


def _text(value, label, maximum=512):
    _need(
        type(value) is str and value.strip() and "\x00" not in value,
        "explicit " + label + " required",
    )
    _need(len(value.encode("utf-8")) <= maximum, "bounded " + label + " required")


def _limits(limits, defaults=DEFAULT_LIMITS):
    _need(
        limits is None or type(limits) is dict,
        "closed optional definition limits required",
    )
    _need(not (set(limits or {}) - set(defaults)), "unknown definition limit")
    bounds = dict(defaults, **(limits or {}))
    for name, value in bounds.items():
        _need(
            type(value) is int and 0 < value <= defaults[name],
            "positive lowered definition bound required: " + name,
        )
    return bounds


def _owners():
    from . import (
        corpus_contracts,
        corpus_source,
        legal_family_routes,
        legal_official_document_views,
        legal_source_sampling,
        legal_statutory_context,
    )

    return (
        corpus_contracts,
        corpus_source,
        legal_family_routes,
        legal_official_document_views,
        legal_source_sampling,
        legal_statutory_context,
    )


def producer_pins():
    """Pin the actual existing owners; this explicit call may load them."""
    owners = _owners()
    pins = owners[2].producer_pins()
    for module in (*owners, boolean):
        pins[str(Path(module.__file__).resolve())] = hashlib.sha256(
            Path(module.__file__).read_bytes()
        ).hexdigest()
    pins[str(Path(__file__).resolve())] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    _need(
        pins[str(Path(__file__).resolve())] == _SELF_PIN,
        "V2 definition source changed since import",
    )
    _need(
        pins[str(Path(boolean.__file__).resolve())] == _BOOLEAN_PIN,
        "shared Boolean source changed since import",
    )
    return pins


def _reference(record):
    return {
        "record_cid": record["record_cid"],
        "schema": record["schema"],
        "sha256": digest(record),
    }


def _original_unit(reference, units):
    _closed(
        reference, ("record_cid", "schema", "sha256"), "original sampler unit reference"
    )
    _text(reference["record_cid"], "original sampler unit CID")
    _text(reference["schema"], "original sampler unit schema")
    _sha(reference["sha256"], "original sampler unit")
    unit = units.get(reference["record_cid"])
    _need(
        unit is not None and reference == _reference(unit),
        "exact original sampler unit reference required",
    )
    return unit


def _applicability(value, document, version):
    _closed(value, _APPLICABILITY_FIELDS, "declared definition applicability")
    _need(
        value["scope_kind"] in ("title", "section"),
        "explicit title or section scope kind required",
    )
    for key in ("scope_id", "jurisdiction_id", "instrument_id", "source_release_id"):
        _text(value[key], key)
    _need(
        type(value["source_edition"]) is int
        and value["source_edition"] == document["edition"],
        "declared applicability edition differs from exact source",
    )
    _need(
        value["source_release_id"] == version["release_id"],
        "declared applicability release differs from exact source",
    )
    civil = value["legal_as_of_civil_date"]
    if civil is not None:
        _need(
            type(civil) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", civil),
            "canonical civil date or null required",
        )
        try:
            _need(
                date.fromisoformat(civil).isoformat() == civil,
                "canonical civil date required",
            )
        except ValueError as error:
            raise ValueError("valid declared civil date required") from error


def _encode_unary_definition(declaration, *, scope_key, atom_span, bounds, family, routes):
    """Shared ordered unary Boolean lowering; each source profile validates spans."""
    head_text = declaration["head"]["text"]
    from ..intent_ir.formalize.modal_projections import _ast
    from ..TDFOL import tdfol_core as t

    x = t.Variable("x")
    symbols, symbol_occurrences = {}, []

    def atom(value, *, head=False):
        literal = atom_span(value, head=head)
        symbol = "D" + digest({"scope": scope_key, "literal": literal, "arity": 1})
        symbols[symbol] = {
            "symbol": symbol,
            "source_literal": literal,
            "arity": 1,
            "scope_key": scope_key,
        }
        symbol_occurrences.append(
            {"symbol": symbol, "span": value, "role": "head" if head else "body"}
        )
        return t.Predicate(symbol, (x,))

    head = atom(declaration["head"], head=True)
    body = boolean.build_boolean_expression(
        declaration["body"],
        atom_builder=atom,
        require=_need,
        max_depth=bounds["max_expression_depth"],
        max_nodes=bounds["max_expression_nodes"],
        max_operands=bounds["max_operands"],
    )
    _need(
        all(
            row["source_literal"] != head_text
            for symbol, row in symbols.items()
            if symbol != head.name
        ),
        "definition body cannot silently collapse to its head",
    )
    _need(
        len(symbols) >= 2
        and head.name
        not in {row["symbol"] for row in symbol_occurrences if row["role"] == "body"},
        "self-referential or vacuous head definition unsupported",
    )
    typed = t.QuantifiedFormula(
        t.Quantifier.FORALL, x, t.BinaryFormula(t.LogicOperator.IFF, head, body)
    )
    native = routes.prepare_native_fragment(
        family=family, formula=typed.to_string(), expected_ast=_ast(typed)
    )

    return native, symbols, symbol_occurrences, head


def prepare_definition_v2(
    request,
    *,
    sampling_report,
    expected_sampling_report_sha256,
    raw_html,
    descriptor,
    expected_descriptor_sha256,
    expected_raw_sha256,
    expected_raw_bytes,
    view_limits=None,
    sampling_limits=None,
    limits=None,
):
    """Replay complete V2 source custody and encode one caller declaration.

    All full report hashes are canonical hashes, distinct from retained original
    JSON file hashes. Original reports remain separate explicit replay inputs;
    no complete sampling report or HTML is embedded in the compact result.
    """
    bounds = _limits(limits)
    _closed(request, _REQUEST_FIELDS, "V2 definition request")
    _need(
        request["schema"] == REQUEST_SCHEMA and request["profile"] == PROFILE,
        "explicit V2 definition request profile required",
    )
    _need(
        type(request["family"]) is str and request["family"] in FAMILIES,
        "V2 definition requires FOL or its TDFOL subset",
    )
    request_raw = _canonical(request, bounds["max_report_bytes"])
    request = json.loads(request_raw)
    declaration = request["declaration"]
    _closed(declaration, _DECLARATION_FIELDS, "V2 unary definition declaration")
    _text(declaration["declaration_id"], "declaration identity", 256)
    _need(
        declaration["interpretation_status"] == "unreviewed_caller_declaration",
        "explicit unreviewed caller interpretation required",
    )
    for value, label in (
        (expected_sampling_report_sha256, "independent complete sampling report"),
        (expected_descriptor_sha256, "independent acquisition descriptor"),
        (expected_raw_sha256, "independent raw HTML"),
    ):
        _sha(value, label)
    _need(
        type(expected_raw_bytes) is int
        and 0 < expected_raw_bytes <= 8_000_000
        and type(raw_html) is bytes
        and len(raw_html) == expected_raw_bytes,
        "independently bounded exact raw HTML bytes required",
    )
    _need(
        hashlib.sha256(raw_html).hexdigest() == expected_raw_sha256,
        "independent raw HTML hash differs",
    )
    sampling_raw = _canonical(sampling_report, bounds["max_sampling_report_bytes"])
    _need(
        hashlib.sha256(sampling_raw).hexdigest() == expected_sampling_report_sha256,
        "independent full sampling report pin differs",
    )
    descriptor_raw = wire(descriptor)
    _need(
        sum(map(len, (request_raw, sampling_raw, descriptor_raw, raw_html)))
        <= bounds["max_input_bytes"],
        "complete definition input byte bound exceeded; truncation refused",
    )
    sampling_report, descriptor = json.loads(sampling_raw), json.loads(descriptor_raw)
    owners = _owners()
    _, sources, routes, views, sampling, contexts = owners
    pins = producer_pins()
    checked = sampling.validate_source_sampling(
        sampling_report,
        raw_html,
        expected_report_sha256=expected_sampling_report_sha256,
        descriptor=descriptor,
        expected_descriptor_sha256=expected_descriptor_sha256,
        expected_raw_sha256=expected_raw_sha256,
        expected_raw_bytes=expected_raw_bytes,
        view_limits=view_limits,
        limits=sampling_limits,
    )
    _need(
        checked["status"] == "whole_source_blocks_prepared",
        "complete available V2 source population required",
    )
    document = checked["document_view_report"]["document"]
    view = checked["document_view_report"]["normalized_view"]
    text, blocks = document["document_text"], document["blocks"]
    records = {record["record_cid"]: record for record in checked["records"]}
    versions = [
        record
        for record in records.values()
        if record["schema"] == sources.SOURCE_VERSION_SCHEMA
    ]
    _need(len(versions) == 1, "one exact sampler source version required")
    version = versions[0]
    _need(
        declaration["source_version_ref"] == _reference(version),
        "exact original V2 source version reference required",
    )
    _need(
        declaration["normalized_view_id"] == view["view_id"],
        "exact V2 normalized view identity required",
    )
    units = {
        record["record_cid"]: record
        for record in records.values()
        if record["schema"] == sampling.UNIT_SCHEMA
    }
    offered = declaration["contributor_unit_refs"]
    _need(
        type(offered) is list and 1 <= len(offered) <= bounds["max_contributors"],
        "bounded nonempty complete contributor population required",
    )
    contributors = [_original_unit(reference, units) for reference in offered]
    ordinals = [unit["ordinal"] for unit in contributors]
    _need(
        ordinals == sorted(set(ordinals)),
        "unique source-ordered contributor units required",
    )
    _need(
        all(unit["candidate_input"] is True for unit in contributors),
        "original candidate statute paragraph contributors required",
    )
    scope_unit = _original_unit(declaration["scope_unit_ref"], units)
    _applicability(declaration["applicability"], document, version)
    first = blocks[ordinals[0]]
    selected = set(ordinals)

    def span(value, *, block=None, body=False):
        _closed(value, ("char_start", "char_end", "text"), "definition source span")
        start, end = value["char_start"], value["char_end"]
        _need(
            type(start) is int and type(end) is int and 0 <= start < end <= len(text),
            "bounded exact definition source interval required",
        )
        literal = value["text"]
        _text(literal, "source literal", bounds["max_literal_bytes"])
        _need(text[start:end] == literal, "exact definition source span differs")
        if block is not None:
            _need(
                block["char_start"] <= start < end <= block["char_end"],
                "definition span must remain in its declared original block",
            )
        if body:
            _need(
                start >= declaration["definition_cue"]["char_end"],
                "definition-body atom must follow means cue",
            )
            _need(
                first["char_start"] <= start < end <= blocks[ordinals[-1]]["char_end"],
                "body atom outside complete contributor bounds",
            )
            touched = {
                b["block_index"]
                for b in blocks
                if b["char_start"] < end and start < b["char_end"]
            }
            _need(
                touched and touched <= selected,
                "every intersected body-atom block must be an explicit contributor",
            )
        return literal

    scope_literal = span(declaration["scope_span"], block=blocks[scope_unit["ordinal"]])
    kind = declaration["applicability"]["scope_kind"]
    _need(
        scope_literal.casefold() in (f"in this {kind}", f"in this {kind}:"),
        "exact declared title/section scope literal required",
    )
    span(declaration["head"], block=first)
    _need(
        span(declaration["definition_cue"], block=first) == "means",
        "explicit means cue required",
    )
    _need(
        declaration["scope_span"]["char_end"] <= declaration["head"]["char_start"],
        "declared scope must precede its defined term",
    )
    _need(
        declaration["head"]["char_end"] <= declaration["definition_cue"]["char_start"],
        "defined head must precede means cue",
    )
    scope_key = digest(
        {
            "profile": PROFILE,
            "declaration_id": declaration["declaration_id"],
            "source_version_ref": declaration["source_version_ref"],
            "normalized_view_id": view["view_id"],
            "scope_unit_ref": declaration["scope_unit_ref"],
            "scope_span": declaration["scope_span"],
            "applicability": declaration["applicability"],
        }
    )
    native, symbols, symbol_occurrences, head = _encode_unary_definition(
        declaration, scope_key=scope_key, bounds=bounds, family=request["family"], routes=routes,
        atom_span=lambda value, *, head: span(value, block=first if head else None, body=not head),
    )

    original_occurrences = {
        record["record_cid"]: record
        for record in records.values()
        if record["schema"] == sources.SOURCE_OCCURRENCE_SCHEMA
    }
    original_contexts = {
        record["source_occurrence_cid"]: record
        for record in records.values()
        if record["schema"] == sources.CONTEXT_DECLARATION_SCHEMA
    }
    by_geometry = {
        (record["start_char"], record["end_char"]): record
        for record in original_occurrences.values()
    }
    occurrences, declarations, bindings, retained = [], [], [], {}

    def add(role, value, *, source_symbol=None, symbol=None):
        _need(
            len(bindings) < bounds["max_bindings"],
            "complete source binding bound exceeded; truncation refused",
        )
        start, end = value["char_start"], value["char_end"]
        geometry = (start, end)
        if geometry not in retained:
            _need(
                len(occurrences) < bounds["max_occurrences"],
                "complete physical occurrence bound exceeded; truncation refused",
            )
            occurrence = by_geometry.get(geometry)
            if occurrence is None:
                occurrence = sources.build_source_occurrence(
                    version,
                    expected_raw_sha256=expected_raw_sha256,
                    extracted_text=text,
                    expected_extracted_sha256=document["document_text_sha256"],
                    start_char=start,
                    end_char=end,
                    start_utf8=len(text[:start].encode()),
                    end_utf8=len(text[:end].encode()),
                )
            context = original_contexts.get(occurrence["record_cid"])
            if context is None:
                context = sources.build_context_declaration(
                    occurrence,
                    expected_occurrence_cid=occurrence["record_cid"],
                    availability="required_unavailable",
                    reason="V2 definition source origin retained; all legal context attachments remain unreviewed.",
                    context_references=[
                        {
                            "record_cid": version["record_cid"],
                            "record_kind": "source_version",
                            "purpose": "complete V2 source retained externally, not dependency closure",
                        }
                    ],
                    missing_requirements=list(contexts.DEPENDENCY_KINDS),
                )
            retained[geometry] = (occurrence, context)
            occurrences.append(occurrence)
            declarations.append(context)
        occurrence, context = retained[geometry]
        bindings.append(
            {
                "role": role,
                "source_occurrence_cid": occurrence["record_cid"],
                "context_cid": context["record_cid"],
                "block_indices": [
                    b["block_index"]
                    for b in blocks
                    if b["char_start"] < end and start < b["char_end"]
                ],
                "source_symbol": source_symbol,
                "symbol": symbol,
            }
        )

    add("scope_block", blocks[scope_unit["ordinal"]])
    for index, ordinal in enumerate(ordinals):
        add(f"definition_contributor/{index:04d}", blocks[ordinal])
    add("scope_literal", declaration["scope_span"])
    add(
        "definition_head",
        declaration["head"],
        source_symbol=head.name,
        symbol=head.name,
    )
    add("definition_cue", declaration["definition_cue"])
    for index, row in enumerate(
        row for row in symbol_occurrences if row["role"] == "body"
    ):
        add(
            f"definition_body/{index:04d}",
            row["span"],
            source_symbol=row["symbol"],
            symbol=row["symbol"],
        )
    original_count = sum(
        record["record_cid"] in original_occurrences for record in occurrences
    )
    report = {
        "schema": SCHEMA,
        "profile": PROFILE,
        "family": request["family"],
        "declaration_id": declaration["declaration_id"],
        "request_sha256": hashlib.sha256(request_raw).hexdigest(),
        "declaration": declaration,
        "document_id": document["document_id"],
        "document_text_sha256": document["document_text_sha256"],
        "normalized_view_id": view["view_id"],
        "source_version": version,
        "source_occurrences": occurrences,
        "source_bindings": bindings,
        "context_declarations": declarations,
        "contributor_unit_refs": declaration["contributor_unit_refs"],
        "scope_unit_ref": declaration["scope_unit_ref"],
        "scope_key": scope_key,
        "applicability": declaration["applicability"],
        "symbols": [symbols[key] for key in sorted(symbols)],
        "symbol_occurrences": symbol_occurrences,
        "native_ast": native["native_ast"],
        "native": native,
        "lean_body": native["lean_body"],
        "producer_pins": pins,
        "limits": bounds,
        "source_input_pins": {
            "expected_raw_sha256": expected_raw_sha256,
            "expected_raw_bytes": expected_raw_bytes,
            "expected_descriptor_sha256": expected_descriptor_sha256,
            "sampling_report_full_canonical_sha256": expected_sampling_report_sha256,
            "view_report_full_canonical_sha256": views.document_view_report_sha256(
                checked["document_view_report"]
            ),
            "source_version_ref": _reference(version),
            "normalized_view_id": view["view_id"],
            "extracted_text_sha256": document["document_text_sha256"],
        },
        "source_context_frontier": {
            "original_blocks": len(blocks),
            "original_units": len(units),
            "original_context_declarations": len(original_contexts),
            "original_open_context_obligations": sum(
                len(c["missing_requirements"]) for c in original_contexts.values()
            ),
            "selected_original_occurrences": original_count,
            "derived_role_occurrences": len(occurrences) - original_count,
            "selected_physical_occurrences": len(occurrences),
            "selected_open_context_obligations": sum(
                len(c["missing_requirements"]) for c in declarations
            ),
            "unselected_original_occurrences": len(original_occurrences)
            - original_count,
            "whole_source_context_retained_externally": True,
        },
        "source_bound": True,
        "explicit_universal_biconditional": True,
        "declared_native_profile_encoded": True,
        "definition_lexical_coverage_complete": False,
        "interpretation_contract": "For each entity in one caller-interpreted carrier, the declared head holds iff the explicit Boolean body holds at the evaluation point; applicability remains an unreviewed declaration.",
        "limitations": [
            "This is a caller interpretation, not a reviewed statutory definition or governing source selection.",
            "Whole contributor custody and exact atom spans do not establish complete meaning or attachment.",
            "Only unary means/Boolean categories are encoded; includes, legal sorts, identity, general references and normative uses need supported separate profiles.",
            "Original source/context evidence remains externally retained; no raw-HTML offset mapping or context closure is inferred.",
            "No model, native Lean build, signature, review, training target or semantic admission is executed.",
        ],
        "authority": dict(AUTHORITY),
    }
    report["report_sha256"] = digest(report)
    _need(
        len(wire(report)) <= bounds["max_report_bytes"],
        "complete definition report bound exceeded; truncation refused",
    )
    _need(producer_pins() == pins, "definition producers changed during preparation")
    return json.loads(wire(report))


def validate_definition_v2(report, request, **inputs):
    """Regenerate the complete candidate; outer hashes never replace replay."""
    bounds = _limits(inputs.get("limits"))
    offered = _canonical(report, bounds["max_report_bytes"])
    expected = prepare_definition_v2(request, **inputs)
    _need(
        offered == wire(expected),
        "V2 definition differs from complete authoritative regeneration",
    )
    return True


__all__ = [
    "REQUEST_SCHEMA",
    "SCHEMA",
    "PROFILE",
    "DEFAULT_LIMITS",
    "AUTHORITY",
    "wire",
    "digest",
    "producer_pins",
    "prepare_definition_v2",
    "validate_definition_v2",
]


def parent_definition_producer_pins():
    """Retain existing native/Boolean owners and explicit physical parent owners."""
    from . import legal_semantic_graph, corpus_parent_occurrence_adapter
    pins = producer_pins()
    for module in (legal_semantic_graph, corpus_parent_occurrence_adapter):
        path = Path(module.__file__).resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


def prepare_parent_definition_v1(request, *, parent_bundle, expected_manifest_cid,
        source_occurrence_cid, companion_record_cid, report_bytes, expected_report_pins,
        replay_inputs, parent_limits=None, limits=None):
    """Encode a caller's unary definition against a replayed complete literal field.

    Contributor spans are explicit unreviewed ranges, never inferred statutory
    units. The whole parent population/originals remain required. Separate parent
    intake limits bound that evidence; this profile bounds the compact declaration,
    report and derived origins without pretending an HTML sampling report exists.
    """
    from . import corpus_contracts as contracts, corpus_source as sources
    from . import legal_semantic_graph as graphs, corpus_parent_occurrence_adapter as parent
    bounds = _limits(limits, PARENT_DEFAULT_LIMITS)
    request = contracts.clone_json(request)
    _closed(request, _REQUEST_FIELDS, "literal parent definition request")
    _need(request["schema"] == PARENT_REQUEST_SCHEMA and request["profile"] == PARENT_PROFILE,
          "explicit literal parent definition profile required")
    _need(type(request["family"]) is str and request["family"] in FAMILIES,
          "parent definition requires FOL or its TDFOL subset")
    request_raw = _canonical(request, bounds["max_report_bytes"])
    declaration = request["declaration"]
    _closed(declaration, _PARENT_DECLARATION_FIELDS, "literal parent definition declaration")
    _text(declaration["declaration_id"], "declaration identity", 256)
    _need(declaration["interpretation_status"] == "unreviewed_caller_declaration",
          "explicit unreviewed caller interpretation required")
    _sha(declaration["source_binding_sha256"], "independent parent source binding")
    _need(declaration["scope_kind"] in ("title", "section"), "declared title/section scope kind required")
    pins = parent_definition_producer_pins()
    source = graphs.bind_parent_source_occurrence(parent_bundle,
        expected_manifest_cid=expected_manifest_cid, source_occurrence_cid=source_occurrence_cid,
        companion_record_cid=companion_record_cid, report_bytes=report_bytes,
        expected_report_pins=expected_report_pins, replay_inputs=replay_inputs, limits=parent_limits)
    _need(source["source_binding_sha256"] == declaration["source_binding_sha256"],
          "declared parent source differs from complete independent replay")
    graphs._check_bindings(source, declaration["scope"])
    version, whole = source["source_version"], source["selector"]
    view = version["extracted_view"]
    _need(whole["start_char"] == whole["start_utf8"] == 0
          and whole["end_char"] == view["character_length"]
          and whole["end_utf8"] == view["byte_length"]
          and whole["span_sha256"] == view["sha256"]
          and whole["span_cid"] == view["cid"], "complete exact literal field required; a fragment is insufficient")
    text = whole["span_text"]
    source_args = dict(source_version=version, expected_raw_sha256=version["raw_artifact"]["sha256"],
        extracted_text=text, expected_extracted_sha256=view["sha256"])
    sources.validate_source_occurrence(whole, **source_args)

    def exact(value):
        _closed(value, ("char_start", "char_end", "text"), "parent definition source span")
        start, end = value["char_start"], value["char_end"]
        _need(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
              "bounded exact parent definition interval required")
        _text(value["text"], "source literal", bounds["max_literal_bytes"])
        _need(text[start:end] == value["text"], "parent definition span differs from literal source")
        return value["text"]

    contributors = declaration["contributor_spans"]
    _need(type(contributors) is list and 1 <= len(contributors) <= bounds["max_contributors"],
          "bounded nonempty declared contributor spans required")
    previous_end = 0
    for item in contributors:
        exact(item)
        _need(previous_end <= item["char_start"], "unique ordered nonoverlapping contributor spans required")
        previous_end = item["char_end"]
    first = contributors[0]

    def covered(value):
        cursor, end = value["char_start"], value["char_end"]
        for item in contributors:
            if item["char_end"] <= cursor:
                continue
            if item["char_start"] > cursor:
                break
            cursor = min(end, item["char_end"])
            if cursor == end:
                return True
        return False

    def atom_span(value, *, head=False):
        literal = exact(value)
        if head:
            _need(first["char_start"] <= value["char_start"] < value["char_end"] <= first["char_end"],
                  "definition head must remain in first declared contributor")
        else:
            _need(value["char_start"] >= declaration["definition_cue"]["char_end"] and covered(value),
                  "definition body must follow means and have no uncovered contributor gap")
        return literal

    scope_literal = exact(declaration["scope_span"])
    kind = declaration["scope_kind"]
    _need(scope_literal.casefold() in (f"in this {kind}", f"in this {kind}:"),
          "exact declared title/section scope literal required")
    atom_span(declaration["head"], head=True)
    cue = declaration["definition_cue"]
    _need(exact(cue) == "means" and first["char_start"] <= cue["char_start"] < cue["char_end"] <= first["char_end"],
          "literal means cue must remain in first declared contributor")
    _need(declaration["scope_span"]["char_end"] <= declaration["head"]["char_start"]
          and declaration["head"]["char_end"] <= cue["char_start"], "declared scope/head/means source order differs")
    scope_key = digest({"profile": PARENT_PROFILE, "declaration_id": declaration["declaration_id"],
        "source_binding_sha256": source["source_binding_sha256"], "scope": declaration["scope"],
        "scope_kind": kind, "scope_span": declaration["scope_span"]})
    from . import legal_family_routes as routes
    native, symbols, symbol_occurrences, head = _encode_unary_definition(declaration,
        scope_key=scope_key, atom_span=atom_span, bounds=bounds, family=request["family"], routes=routes)
    occurrences, contexts, bindings, retained = [whole], [source["context"]], [], {
        (0, len(text)): (whole, source["context"])}

    def add(role, value, *, symbol=None):
        _need(len(bindings) < bounds["max_bindings"], "complete parent binding bound exceeded")
        geometry = value["char_start"], value["char_end"]
        if geometry not in retained:
            _need(len(occurrences) < bounds["max_occurrences"], "complete parent occurrence bound exceeded")
            start, end = geometry
            occurrence = sources.build_source_occurrence(version,
                **{key: val for key, val in source_args.items() if key != "source_version"},
                start_char=start, end_char=end, start_utf8=len(text[:start].encode()),
                end_utf8=len(text[:end].encode()))
            context = sources.build_context_declaration(occurrence, expected_occurrence_cid=occurrence["record_cid"],
                availability="required_unavailable", reason="Caller-declared definition ranges do not establish governing context or complete statutory units.",
                context_references=source["context"]["context_references"], missing_requirements=list(parent.MISSING_CONTEXT))
            retained[geometry] = occurrence, context
            occurrences.append(occurrence); contexts.append(context)
        occurrence, context = retained[geometry]
        bindings.append({"role": role, "source_occurrence_cid": occurrence["record_cid"],
            "context_cid": context["record_cid"], "source_symbol": symbol, "symbol": symbol})

    add("source_field", {"char_start": 0, "char_end": len(text)})
    for index, item in enumerate(contributors):
        add(f"declared_contributor/{index:04d}", item)
    add("scope_literal", declaration["scope_span"])
    add("definition_head", declaration["head"], symbol=head.name)
    add("definition_cue", cue)
    for index, row in enumerate(row for row in symbol_occurrences if row["role"] == "body"):
        add(f"definition_body/{index:04d}", row["span"], symbol=row["symbol"])
    report = {"schema": PARENT_SCHEMA, "profile": PARENT_PROFILE, "family": request["family"],
        "declaration_id": declaration["declaration_id"], "request_sha256": hashlib.sha256(request_raw).hexdigest(),
        "declaration": declaration, "parent_source_binding": source, "source_version": version,
        "source_occurrences": occurrences, "context_declarations": contexts, "source_bindings": bindings,
        "scope": declaration["scope"], "scope_kind": kind, "scope_key": scope_key,
        "contributor_spans": contributors, "symbols": [symbols[key] for key in sorted(symbols)],
        "symbol_occurrences": symbol_occurrences, "native_ast": native["native_ast"], "native": native,
        "lean_body": native["lean_body"], "producer_pins": pins, "limits": bounds,
        "source_input_pins": {"parent_manifest_cid": expected_manifest_cid,
            "source_occurrence_cid": source_occurrence_cid, "companion_record_cid": companion_record_cid,
            "source_binding_sha256": source["source_binding_sha256"]},
        "source_bound": True, "explicit_universal_biconditional": True, "declared_native_profile_encoded": True,
        "definition_lexical_coverage_complete": False, "contributor_completeness_verified": False,
        "source_region_roles_verified": False, "governing_scope_verified": False,
        "interpretation_contract": "Caller-declared forall x, head(x) iff body(x) in an unreviewed physical-source namespace; applicability and contributor completeness remain unresolved.",
        "limitations": ["The complete literal field is available, but declared ranges are not verified statutory units.",
            "Edition, governing source, context and semantic coverage remain unresolved.",
            "No normative use, legal review, model execution, native Lean build or corpus admission is supplied."],
        "authority": dict(AUTHORITY)}
    report["report_sha256"] = digest(report)
    _need(len(wire(report)) <= bounds["max_report_bytes"], "complete parent definition report bound exceeded")
    _need(parent_definition_producer_pins() == pins, "parent definition producers changed during preparation")
    return contracts.clone_json(report)


def validate_parent_definition_v1(report, request, **inputs):
    """Replay complete physical evidence and declaration; no seal-only acceptance."""
    from . import corpus_contracts as contracts
    bounds = _limits(inputs.get("limits"), PARENT_DEFAULT_LIMITS)
    offered = _canonical(contracts.clone_json(report), bounds["max_report_bytes"])
    expected = prepare_parent_definition_v1(request, **inputs)
    _need(offered == wire(expected), "parent definition differs from complete independent regeneration")
    return True


__all__ += ["PARENT_REQUEST_SCHEMA", "PARENT_SCHEMA", "PARENT_PROFILE", "PARENT_DEFAULT_LIMITS",
            "parent_definition_producer_pins", "prepare_parent_definition_v1", "validate_parent_definition_v1"]

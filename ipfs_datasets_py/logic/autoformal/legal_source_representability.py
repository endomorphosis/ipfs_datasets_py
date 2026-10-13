"""Bound every source occurrence before proposing legal-function/profile routes.

This public inventory API complements ``legal_statutory_routing`` (official
GovInfo views) and reuses the canonical source preflight and complete controlled
English compiler. Multiple proposed labels may apply to one untouched unit.
Lexical evidence is never a reviewed classification or a representability proof.

``bind_source_unit`` accepts exact text and Unicode code-point offsets from an
upstream source inventory. ``inventory_source_representability`` requires that
inventory's ordered unit hashes, including repeated presentations. It cannot
silently keep only easy sentences or deduplicate equal text. Its completeness
claim concerns that supplied population, never an entire statute or corpus.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ..legal_ir import canonical_decoder_preflight as preflight
from ..legal_ir.canonical_source_guards import _quoted_mask

UNIT_SCHEMA = "legal-source-occurrence-unit/v1"
SCHEMA = "legal-source-representability-proposal/v1"
INVENTORY_SCHEMA = "legal-source-representability-inventory/v1"
OFFSET_COORDINATES = "unicode_codepoints_half_open"
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_UNIT_BYTES = 1024 * 1024
MAX_CONTEXT_BYTES = 256 * 1024
MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_UNITS = 128
MAX_EVIDENCE = 256
LABELS = ("operative_norm", "definition", "scope", "amendment_history",
          "constitutive", "procedure", "cross_reference", "ambiguous", "unsupported")
REGIONS = ("codified_body", "notes_or_other", "heading", "unknown")
_FALSE = {key: False for key in (
    "reviewed_label", "semantic_gold", "source_semantics_verified",
    "full_representability_established", "global_consistency_verified",
    "training_qualified", "model_executed", "admitted")}
_UNIT_FIELDS = {"schema", "document_id", "document_revision", "document_text_sha256",
                "occurrence_id", "offset_coordinate_system", "char_start", "char_end",
                "source_text", "source_sha256", "region_kind", "unit_sha256"}
_PATTERNS = (
    ("operative_norm", "explicit_normative_wording", preflight._NORMATIVE),
    ("definition", "definition_wording", re.compile(
        r"\b(?:means|includes|has\s+the\s+meaning|have\s+the\s+meanings)\b", re.I)),
    ("scope", "scope_or_applicability_wording", re.compile(
        r"\b(?:for\s+(?:the\s+)?purposes\s+of|in\s+this\s+(?:section|chapter|title)|"
        r"shall\s+(?:not\s+)?apply|applies\s+to|take\s+effect|effective\s+date|"
        r"shall\s+be\s+construed)\b", re.I)),
    ("amendment_history", "amendment_or_history_wording", re.compile(
        r"\b(?:amended|repealed|redesignated|inserted|striking|formerly|codification)\b|"
        r"\bPub\.\s*L\.", re.I)),
    ("constitutive", "constitutive_wording", re.compile(
        r"\b(?:there\s+is\s+(?:hereby\s+)?established|is\s+hereby\s+(?:established|created)|"
        r"there\s+shall\s+be|shall\s+be\s+known\s+as|shall\s+consist\s+of)\b", re.I)),
    ("procedure", "procedural_wording", re.compile(
        r"\b(?:appeal|petition|hearing|jurisdiction|file|filing|service\s+of\s+process|"
        r"notice|application)\b", re.I)),
    ("cross_reference", "unresolved_reference_wording", re.compile(
        r"\b(?:sections?|titles?)\s+[0-9]+[A-Za-z]*(?:\([A-Za-z0-9]+\))*|"
        r"\b(?:subsection|paragraph|subparagraph|clause)\s+(?:\([A-Za-z0-9]+\))+|"
        r"\b(?:this|such|the\s+preceding)\s+(?:section|subsection|paragraph|chapter|title)\b|"
        r"\b(?:as\s+provided\s+in|subject\s+to)\b", re.I)),
)
_ANAPHOR = re.compile(
    r"\b(?:he|she|they|it|such\s+(?:person|agency|entity|officer)|the\s+foregoing)\b", re.I)


class RepresentabilityError(ValueError):
    """A source binding, population identity, or finite inventory bound failed."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise RepresentabilityError(message)


def _wire(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise RepresentabilityError("finite UTF-8 JSON required") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_wire(value)).hexdigest()


def _text(value: Any, maximum: int, label: str, *, blank: bool = False) -> bytes:
    _need(type(value) is str and (blank or bool(value.strip())), f"{label} must be text")
    try:
        raw = value.encode("utf-8")
    except UnicodeError as exc:
        raise RepresentabilityError(f"{label} must be valid UTF-8") from exc
    _need(len(raw) <= maximum, f"{label} exceeds byte bound; no truncation performed")
    return raw


def bind_source_unit(document_text: str, *, document_id: str, document_revision: str,
                     occurrence_id: str, char_start: int, char_end: int,
                     region_kind: str = "unknown") -> dict[str, Any]:
    """Bind a physical occurrence in one exact versioned document text view.

    Revision is an explicit upstream edition/release identity, not necessarily
    a Git SHA. Occurrence IDs are caller-owned physical identities: neither a
    text hash nor a citation is used as a substitute. This binds supplied text;
    it does not authenticate that text as law or resolve its dependencies.
    """
    raw = _text(document_text, MAX_DOCUMENT_BYTES, "document_text")
    for label, value in (("document_id", document_id), ("document_revision", document_revision),
                         ("occurrence_id", occurrence_id)):
        _text(value, 2048, label)
    _need(type(char_start) is int and type(char_end) is int
          and 0 <= char_start < char_end <= len(document_text), "exact nonempty Unicode offsets required")
    _need(type(region_kind) is str and region_kind in REGIONS, "unknown source region kind")
    source = document_text[char_start:char_end]
    source_raw = _text(source, MAX_UNIT_BYTES, "source_text")
    unit = {"schema": UNIT_SCHEMA, "document_id": document_id,
            "document_revision": document_revision, "document_text_sha256": hashlib.sha256(raw).hexdigest(),
            "occurrence_id": occurrence_id, "offset_coordinate_system": OFFSET_COORDINATES,
            "char_start": char_start, "char_end": char_end, "source_text": source,
            "source_sha256": hashlib.sha256(source_raw).hexdigest(), "region_kind": region_kind}
    return {**unit, "unit_sha256": _digest(unit)}


def validate_source_unit(unit: Mapping[str, Any], document_text: str) -> dict[str, Any]:
    """Regenerate all offsets and identities from the complete supplied document."""
    _need(type(unit) is dict and set(unit) == _UNIT_FIELDS, "closed source unit required")
    expected = bind_source_unit(document_text, **{key: unit[key] for key in (
        "document_id", "document_revision", "occurrence_id", "char_start", "char_end", "region_kind")})
    _need(_wire(unit) == _wire(expected), "source unit differs from exact document/offset binding")
    return expected


def _owner(module_name: str, profile: str) -> dict[str, str]:
    module_path = Path(__file__).resolve().parents[1] / (module_name.removeprefix(
        "ipfs_datasets_py.logic.").replace(".", "/") + ".py")
    return {"owner_module": module_name, "profile": profile,
            "owner_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest()}


def _compiler_assessment(source: str, vocabulary: Mapping[str, Any] | None) -> dict[str, Any]:
    assessment = {**_owner("ipfs_datasets_py.logic.legal_ir.canonical_explicit_qualifiers",
                           "explicit-qualifier-single-rule/v1"),
                  "status": "not_assessed", "complete_source_consumption": False,
                  "caller_vocabulary": vocabulary, "diagnostics": [], "canonical_ir": None,
                  "source_semantics_verified": False, "full_representability_established": False}
    if len(source) > 16_384:
        assessment.update(status="outside_profile", diagnostics=["explicit_qualifier.source_bound"])
    elif vocabulary is not None:
        # Call the real full-input compiler, never a locally copied grammar or
        # an inferred atom vocabulary. Success is declared syntax only.
        from ..legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest, OperationStatus
        from ..legal_ir.canonical_explicit_qualifiers import ExplicitQualifierCanonicalCompiler
        declared = CanonicalAtomVocabulary.from_dict(vocabulary)
        result = ExplicitQualifierCanonicalCompiler().compile(CompilerRequest(
            source, "source-representability-syntax-proposal", declared))
        assessment.update(status="declared_syntax_accepted" if result.status is OperationStatus.SUCCESS
                          else "outside_profile", complete_source_consumption=(
                              result.provenance.get("complete_source_consumption") is True),
                          diagnostics=[item.code for item in result.diagnostics],
                          canonical_ir=result.canonical_ir.to_dict() if result.canonical_ir else None)
    return assessment


def propose_source_representability(unit: Mapping[str, Any], document_text: str, *,
                                    context_text: str = "", requires_context_resolution: bool = False,
                                    vocabulary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Produce evidence-bound multilabel proposals and explicit route limits.

    Missing context is reported separately from supplied but unresolved context.
    Optional caller vocabulary enables an actual complete controlled-parser
    assessment. No successful parser result establishes legal translation,
    resolves a reference, admits training labels, or promotes a source unit.
    """
    source_unit = validate_source_unit(unit, document_text)
    _text(context_text, MAX_CONTEXT_BYTES, "context_text", blank=True)
    _need(type(requires_context_resolution) is bool, "requires_context_resolution must be boolean")
    if vocabulary is not None:
        _need(isinstance(vocabulary, Mapping) and len(_wire(vocabulary)) <= 65536,
              "bounded caller-declared vocabulary required")
        vocabulary = json.loads(_wire(vocabulary))
    source = source_unit["source_text"]
    evidence: list[dict[str, Any]] = []
    labels: set[str] = set()
    mask = _quoted_mask(source)

    def add(label: str, code: str, start: int = 0, end: int | None = None,
            *, basis: str = "lexical_cue") -> None:
        end = len(source) if end is None else end
        _need(0 <= start < end <= len(source), "invalid source evidence offsets")
        _need(len(evidence) < MAX_EVIDENCE, "source evidence bound exceeded; no truncation performed")
        labels.add(label)
        literal = source[start:end]
        evidence.append({"label": label, "code": code, "basis": basis,
                         "source_char_start": start, "source_char_end": end,
                         "document_char_start": unit["char_start"] + start,
                         "document_char_end": unit["char_start"] + end,
                         "text": literal, "text_sha256": hashlib.sha256(literal.encode()).hexdigest()})

    for label, code, pattern in _PATTERNS:
        for match in pattern.finditer(source):
            if not any(mask[match.start():match.end()]):
                add(label, code, match.start(), match.end())
    norm_count = sum(row["label"] == "operative_norm" for row in evidence)
    reference_count = sum(row["label"] == "cross_reference" for row in evidence)
    context_reasons = []
    if requires_context_resolution:
        context_reasons.append("caller_requires_context_resolution")
    if context_text.strip():
        context_reasons.append("supplied_context_not_semantically_applied")
    if reference_count:
        context_reasons.append("reference_targets_and_applicability_unresolved")
    for match in _ANAPHOR.finditer(source):
        if not any(mask[match.start():match.end()]):
            add("ambiguous", "unresolved_antecedent_cue", match.start(), match.end())
            context_reasons.append("antecedent_resolution_required")
    if source.rstrip().endswith((";", ":", "—", "...", "…")):
        add("ambiguous", "possible_incomplete_or_list_unit", basis="structural_cue")
        context_reasons.append("possible_list_or_truncation_context_missing")
    if norm_count > 1:
        add("ambiguous", "multiple_normative_cues_require_composition", basis="profile_limit")
    if unit["region_kind"] in ("notes_or_other", "heading"):
        add("unsupported", "source_region_outside_standalone_codified_norm_profile", basis="declared_region")
        if unit["region_kind"] == "notes_or_other":
            add("ambiguous", "notes_may_have_legal_effect_require_separate_interpretation", basis="declared_region")
    context_required = bool(context_reasons)
    warning_record = None
    preflight_context_fits = len(context_text) <= preflight.MAX_CONTEXT_CHARS
    if len(source) <= preflight.MAX_SOURCE_CHARS:
        warning_record = preflight.analyze_decoder_source(
            source, context_text=context_text if preflight_context_fits else "",
            requires_context_resolution=context_required if preflight_context_fits else False)
        for diagnostic in warning_record["diagnostics"]:
            clarify = diagnostic["code"] in {
                "source.context_resolution_unavailable", "source.required_context_missing",
                "source.unresolved_actor_pronoun", "source.relative_calendar_anchor"}
            add("ambiguous" if clarify else "unsupported", diagnostic["code"],
                diagnostic["start"], diagnostic["end"], basis="existing_source_preflight")
    else:
        add("unsupported", "source_exceeds_existing_preflight_bound", basis="profile_limit")
    if not preflight_context_fits:
        add("ambiguous", "supplied_context_exceeds_existing_preflight_bound", basis="profile_limit")
    compiler = _compiler_assessment(source, vocabulary)
    if compiler["status"] == "outside_profile":
        add("unsupported", "complete_declared_parser_refused", basis="existing_full_source_parser")
    specialized = labels & {"definition", "scope", "amendment_history", "constitutive"}
    if specialized and "operative_norm" in labels:
        add("ambiguous", "overlapping_legal_function_cues_require_review", basis="routing_limit")
    if not labels:
        add("ambiguous", "no_recognized_legal_function_cue", basis="routing_limit")
    if norm_count != 1 or specialized:
        add("unsupported", "not_a_single_unqualified_norm_candidate", basis="selected_profile_limit")
    blockers = sorted({row["code"] for row in evidence if row["label"] == "unsupported"})
    if norm_count > 1:
        blockers.append("multiple_normative_cues_require_composition")
    routes = [compiler]
    if "definition" in labels:
        routes.append({**_owner("ipfs_datasets_py.logic.autoformal.legal_source_definition_bridge",
                                "section-local-unary-predicate-definition/v1"),
                       "status": "unresolved_caller_interpretation_required",
                       "requirements": ["exact_official_document_and_scope", "explicit_unary_declaration",
                                        "definition_span_coverage", "native_fragment_check"]})
    if specialized or reference_count:
        routes.append({**_owner("ipfs_datasets_py.logic.autoformal.legal_statutory_routing",
                                "legal-statutory-context-routing/v1"),
                       "status": "official_context_routing_not_executed",
                       "requirements": ["official_document_raw_html_and_exact_diagnostic_view",
                                        "semantic_reference_and_applicability_resolution"]})
    disposition = ("unresolved_context" if context_required else "outside_selected_profile" if blockers
                   else "declared_syntax_candidate" if compiler["status"] == "declared_syntax_accepted"
                   else "unresolved_profile_assessment")
    report = {"schema": SCHEMA, "source_unit": source_unit,
              "proposal_status": "unreviewed_multilabel_proposal",
              "labels": [label for label in LABELS if label in labels], "evidence": evidence,
              "length": {"unicode_codepoints": len(source), "utf8_bytes": len(source.encode()),
                         "whitespace_words": len(source.split()), "normative_cue_count": norm_count},
              "context": {"text": context_text, "sha256": hashlib.sha256(context_text.encode()).hexdigest(),
                          "required": context_required, "missing": context_required and not context_text.strip(),
                          "reasons": sorted(set(context_reasons)), "resolved": False, "applied": False},
              "source_preflight": warning_record,
              "source_preflight_context_coverage": (
                  "not_assessed_exceeds_source_bound" if warning_record is None
                  else "complete_supplied_text_diagnostic" if preflight_context_fits
                  else "not_assessed_exceeds_context_bound"),
              "source_preflight_owner": _owner(
                  "ipfs_datasets_py.logic.legal_ir.canonical_decoder_preflight", preflight.SOURCE_PROFILE),
              "routes": routes,
              "selected_flat_profile_blockers": blockers, "disposition": disposition,
              "limitations": ["Cue labels are proposals; absent cues do not establish representability.",
                              "Named routes describe existing bounded capabilities, not legal equivalence.",
                              "Notes and out-of-profile units are preserved; none is classified as meaningless.",
                              "Supplied context and parser syntax do not establish semantic closure."],
              "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **_FALSE}
    report["proposal_sha256"] = _digest(report)
    _need(len(_wire(report)) <= MAX_BATCH_BYTES, "proposal exceeds output byte bound")
    return report


def validate_source_representability(report: Mapping[str, Any], unit: Mapping[str, Any],
                                    document_text: str, **kwargs: Any) -> dict[str, Any]:
    """Recompute every proposal; resealing cannot bless changed evidence/flags."""
    expected = propose_source_representability(unit, document_text, **kwargs)
    _need(_wire(report) == _wire(expected), "representability proposal differs from exact regeneration")
    return expected


def inventory_source_representability(requests: Iterable[Mapping[str, Any]], *,
                                      expected_unit_sha256s: Sequence[str],
                                      max_units: int = MAX_UNITS) -> dict[str, Any]:
    """Inventory an exact ordered upstream population with no filtering/dedup.

    Each request has ``unit`` and ``document_text`` plus optional classifier
    arguments. Expected hashes must come from the upstream manifest. Repeated
    presentations are retained; reuse of one physical occurrence identity for
    conflicting text/offset/region bindings is rejected. Oversized batches
    fail entirely, never return a seemingly complete prefix.
    """
    _need(type(max_units) is int and 1 <= max_units <= MAX_UNITS, "invalid batch unit bound")
    _need(isinstance(expected_unit_sha256s, (list, tuple))
          and 1 <= len(expected_unit_sha256s) <= max_units, "bounded nonempty expected population required")
    expected = list(expected_unit_sha256s)
    _need(all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) for value in expected),
          "exact expected source-unit hashes required")
    rows, actual, occurrence_bindings = [], [], {}
    consumed_bytes = 0
    for index, request in enumerate(requests):
        _need(index < max_units, "batch unit bound exceeded; no partial inventory returned")
        _need(isinstance(request, Mapping) and {"unit", "document_text"} <= set(request)
              and set(request) <= {"unit", "document_text", "context_text", "requires_context_resolution", "vocabulary"},
              "closed source-classification request required")
        consumed_bytes += len(_wire(request))
        _need(consumed_bytes <= MAX_BATCH_BYTES, "batch input byte bound exceeded")
        result = propose_source_representability(**request)
        unit = result["source_unit"]
        key = (unit["document_id"], unit["document_revision"], unit["occurrence_id"])
        prior = occurrence_bindings.setdefault(key, unit["unit_sha256"])
        _need(prior == unit["unit_sha256"], "conflicting physical source occurrence identity")
        actual.append(unit["unit_sha256"])
        rows.append({"presentation_index": index, "proposal": result})
    _need(actual == expected, "source population differs in membership, order, or multiplicity")
    report = {"schema": INVENTORY_SCHEMA, "population_sha256": _digest(expected),
              "expected_unit_sha256s": expected, "observed_unit_sha256s": actual,
              "population_complete": True, "coverage_scope": "exact_supplied_upstream_population_only",
              "presentation_count": len(rows), "physical_occurrence_count": len(occurrence_bindings),
              "label_counts": dict(Counter(label for row in rows for label in row["proposal"]["labels"])),
              "outside_selected_profile_presentations": [row["presentation_index"] for row in rows
                  if row["proposal"]["selected_flat_profile_blockers"]],
              "unresolved_context_presentations": [row["presentation_index"] for row in rows
                  if row["proposal"]["context"]["required"]],
              "rows": rows, **_FALSE}
    report["inventory_sha256"] = _digest(report)
    _need(len(_wire(report)) <= MAX_BATCH_BYTES, "batch output byte bound exceeded")
    return report


def validate_representability_inventory(report: Mapping[str, Any], requests: Iterable[Mapping[str, Any]],
                                        **kwargs: Any) -> dict[str, Any]:
    expected = inventory_source_representability(requests, **kwargs)
    _need(_wire(report) == _wire(expected), "source inventory differs from exact regeneration")
    return expected


__all__ = ["RepresentabilityError", "bind_source_unit", "validate_source_unit",
           "propose_source_representability", "validate_source_representability",
           "inventory_source_representability", "validate_representability_inventory"]

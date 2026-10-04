"""Actual source construction and separate authored-reference diagnostics.

Construction reuses the native canonical compiler/source-withheld decompiler
roundtrip. Its success means stage completion; exact generated/reparsed IR is
self-consistency, not source fidelity. Vocabulary is caller-supplied and frozen;
this module neither fits it nor verifies that the caller fitted training only.

Explicit context premises are independently compiled and bound. They never
rewrite the query or enter its compiler request. Context-dependent cases abstain
as unavailable because the selected compiler has no context-resolution API.
Native bridge projection is transport evidence with disclosed gaps; no solver,
useful native proof, kernel checker or generative model is run.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

SCHEMA = "legal-richer-source-construction/v1"
SCORE_SCHEMA = "legal-richer-authored-reference-diagnostics/v1"
CORE_FACETS = ("modality", "actor", "action", "object")
QUALIFIER_FACETS = ("conditions", "exceptions", "temporal")
MAX_SOURCE_CHARS = 16_384
MAX_RULES = 64
MAX_RECORD_BYTES = 16 * 1024 * 1024
CONSTRUCTION_FIELDS = frozenset({"schema", "request", "source_sha256", "vocabulary_sha256", "vocabulary_origin",
    "context_compilations", "context_manifest_sha256", "input_policy", "construction_status", "admission_outcome",
    "canonical_ir", "schema_acceptance", "schema_check", "roundtrip", "native_projection", "proof_scopes",
    "model_call_count", "source_fidelity_established", "qualified", "content_sha256"})


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("finite ordinary JSON required") from error
    _require(len(raw) <= MAX_RECORD_BYTES, "bounded richer evaluation record required")
    return raw


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _canonical(value):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    _require(type(value) is dict and set(value) == {"rules"} and type(value["rules"]) is list
             and 1 <= len(value["rules"]) <= MAX_RULES, "bounded canonical IR required")
    canonical = CanonicalRoundTripIR.from_dict(value)
    _require(_raw(canonical.to_dict()) == _raw(value), "IR must already be canonical")
    return canonical


def _count_metrics(proposed, reference):
    tp = sum((proposed & reference).values())
    fp, fn = sum((proposed-reference).values()), sum((reference-proposed).values())
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else None,
            "recall": tp/(tp+fn) if tp+fn else None, "exact": proposed == reference}


def _ir_diagnostics(proposed, reference):
    generated = [] if proposed is None else _canonical(proposed).to_dict()["rules"]
    expected = _canonical(reference).to_dict()["rules"]
    def core(rule):
        return tuple(rule[facet] for facet in CORE_FACETS)

    def scoped(rules):
        return Counter((core(rule), facet, atom) for rule in rules for facet in QUALIFIER_FACETS for atom in rule[facet])
    generated_scoped, reference_scoped = scoped(generated), scoped(expected)
    migrations = []
    for (scope, facet, atom), count in sorted((reference_scoped-generated_scoped).items()):
        others = [other for other in QUALIFIER_FACETS if other != facet and generated_scoped[(scope, other, atom)]]
        if others:
            migrations.append({"core": dict(zip(CORE_FACETS, scope, strict=True)), "atom": atom,
                               "reference_facet": facet, "proposed_facets": others, "missing_count": count})
    return {
        "exact_ir": proposed is not None and _raw(proposed) == _raw(reference),
        "proposed_rules": len(generated), "reference_rules": len(expected),
        "core_tuple_counts": _count_metrics(Counter(core(rule) for rule in generated), Counter(core(rule) for rule in expected)),
        "full_rule_counts": _count_metrics(Counter(_digest(rule) for rule in generated), Counter(_digest(rule) for rule in expected)),
        "typed_qualifier_counts": {facet: _count_metrics(Counter({key: count for key, count in generated_scoped.items() if key[1] == facet}),
                                                         Counter({key: count for key, count in reference_scoped.items() if key[1] == facet}))
                                   for facet in QUALIFIER_FACETS},
        "unscoped_qualifier_presence": {facet: _count_metrics(Counter(atom for rule in generated for atom in rule[facet]),
                                                              Counter(atom for rule in expected for atom in rule[facet]))
                                         for facet in QUALIFIER_FACETS},
        "cross_facet_migrations": migrations,
        "qualifier_scope": "core_tuple_plus_facet_atom_multiset",
        "qualifier_rule_coassociation": "checked_by_full_rule_and_exact_ir_only",
        "semantic_equivalence_checked": False,
    }


def _native_projection(result, source_text):
    if result is None or result.canonical_ir is None:
        return {"status": "unrun", "reason": "no_generated_ir", "proofs_executed": False}
    try:
        from ipfs_datasets_py.logic.bridge.canonical import wrap_compiler_result

        bridge = wrap_compiler_result(result, family_id="deontic", source_text=source_text,
                                      adapter_name="alignment_richer_source_diagnostic")
        artifact = bridge.to_dict()
        return {"status": "executed", "operation": "wrap_compiler_result", "bridge_cid": bridge.bridge_cid,
                "artifact": artifact, "artifact_sha256": _digest(artifact), "family_identity": bridge.family_identity.to_dict(),
                "represented_views": sorted(bridge.views),
                "unsupported_constructs": [item.to_dict() for item in bridge.unsupported_constructs],
                "domain_logic_slice": bridge.domain_logic_slice.to_dict() if bridge.domain_logic_slice else None,
                "scope": "typed_bridge_transport_with_disclosed_gaps", "proofs_executed": False}
    except Exception as error:
        return {"status": "unavailable", "reason": "native_bridge_projection_failed",
                "exception_type": type(error).__name__, "proofs_executed": False}


def construct_source(source_text, vocabulary, *, request_id, context_premises=(), requires_context_resolution=False) -> dict:
    """Construct from source and frozen vocabulary; accepts no authored target.

    ``context_premises`` is a bounded sequence of closed ``{id,text}`` records.
    Context-required cases are unavailable even when their raw text could parse.
    Premise compilation is a separate diagnostic, not contextual resolution or
    proof of any premise. Partial semantic projection is disabled explicitly.
    """
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CanonicalAtomVocabulary,
        CompilerRequest,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTrip

    _require(type(source_text) is str and source_text.strip() and len(source_text) <= MAX_SOURCE_CHARS, "bounded nonblank source text required")
    _require(type(request_id) is str and 0 < len(request_id) <= 512, "bounded request ID required")
    _require(type(requires_context_resolution) is bool, "context requirement must be boolean")
    _require(type(context_premises) in (list, tuple) and len(context_premises) <= 8, "bounded explicit context premises required")
    atoms = vocabulary if isinstance(vocabulary, CanonicalAtomVocabulary) else CanonicalAtomVocabulary.from_dict(vocabulary)
    frozen_vocabulary = atoms.to_dict()
    request = CompilerRequest(source_text, request_id, atoms, allow_explicit_partial=False, config={})
    context, seen = [], set()
    for premise in context_premises:
        _require(type(premise) is dict and set(premise) == {"id", "text"}, "context is declared id/text, never reference IR")
        identity, text = premise["id"], premise["text"]
        _require(type(identity) is str and 0 < len(identity) <= 512 and identity not in seen, "unique bounded premise ID required")
        _require(type(text) is str and text.strip() and len(text) <= MAX_SOURCE_CHARS, "bounded premise text required")
        seen.add(identity)
        premise_request = CompilerRequest(text, f"{request_id}:context:{identity}", atoms, allow_explicit_partial=False, config={})
        premise_result = TypedDeonticCanonicalCompiler().compile(premise_request)
        context.append({"id": identity, "request": premise_request.to_dict(), "compiler_result": premise_result.to_dict(),
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "applied_to_query_construction": False})
    result, l1 = None, None
    if requires_context_resolution:
        status, outcome = "unavailable", "abstain_context_resolution_unavailable"
    else:
        result = CanonicalSemanticRoundTrip().run(request)
        l1 = result.l1_result
        status = l1.status.value if l1 is not None else result.status.value
        outcome = "candidate_generated" if l1 is not None and l1.canonical_ir is not None else "no_candidate_generated"
    candidate = l1.canonical_ir.to_dict() if l1 is not None and l1.canonical_ir is not None else None
    if candidate is not None:
        _canonical(candidate)
    reparsed = result.l2_result.canonical_ir.to_dict() if result is not None and result.l2_result is not None and result.l2_result.canonical_ir is not None else None
    rendered = result.t1_result.text if result is not None and result.t1_result is not None else None
    roundtrip = {"status": result.status.value if result is not None else "unrun",
                 "native_result": result.to_dict() if result is not None else None,
                 "rendered_text": rendered, "reparsed_ir": reparsed,
                 "exact_ir": None if result is None else bool(candidate is not None and reparsed is not None and _raw(candidate) == _raw(reparsed)),
                 "generated_vs_reparsed": _ir_diagnostics(reparsed, candidate) if candidate is not None else None,
                 "success_means": "stage_completion_only", "source_fidelity_established": False}
    value = {"schema": SCHEMA, "request": request.to_dict(), "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
             "vocabulary_sha256": _digest(frozen_vocabulary), "vocabulary_origin": "caller_provenance_required_no_fit_here",
             "context_compilations": context, "context_manifest_sha256": _digest(context),
             "input_policy": {"requires_context_resolution": requires_context_resolution, "context_consumed_by_constructor": False,
                              "authored_target_supplied": False, "allow_explicit_partial": False},
             "construction_status": status, "admission_outcome": outcome, "canonical_ir": candidate,
             "schema_acceptance": candidate is not None,
             "schema_check": {"operation": "CanonicalRoundTripIR.from_dict", "executed": candidate is not None,
                              "accepted": candidate is not None, "jsonschema_validator_run": False},
             "roundtrip": roundtrip, "native_projection": _native_projection(l1, source_text),
             "proof_scopes": {scope: {"status": "unrun", "reason": "no_reviewed_solver_interpretation_or_checker_execution"}
                              for scope in ("native_proof", "kernel_proof", "useful_proof_coverage")},
             "model_call_count": 0, "source_fidelity_established": False, "qualified": False}
    value["content_sha256"] = _digest(value)
    return value


def _validate_construction(value):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CompilerRequest, CompilerResult
    from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTripResult

    _require(type(value) is dict and set(value) == CONSTRUCTION_FIELDS and value.get("schema") == SCHEMA and value.get("qualified") is False
             and value.get("source_fidelity_established") is False and type(value.get("model_call_count")) is int
             and value["model_call_count"] == 0, "source construction identity or evidence scope differs")
    _require(value.get("content_sha256") == _digest({key: item for key, item in value.items() if key != "content_sha256"}), "construction content digest differs")
    request = CompilerRequest.from_dict(value["request"])
    policy = value["input_policy"]
    _require(type(policy) is dict and set(policy) == {"requires_context_resolution", "context_consumed_by_constructor", "authored_target_supplied", "allow_explicit_partial"}
             and type(policy["requires_context_resolution"]) is bool and policy["context_consumed_by_constructor"] is False
             and policy["authored_target_supplied"] is False and policy["allow_explicit_partial"] is False
             and request.allow_explicit_partial is False and dict(request.config) == {}, "source-only construction policy differs")
    _require(value["source_sha256"] == hashlib.sha256(request.source_text.encode()).hexdigest()
             and value["vocabulary_sha256"] == _digest(request.atom_vocabulary.to_dict()), "source or vocabulary binding differs")
    _require(value["context_manifest_sha256"] == _digest(value["context_compilations"]), "context binding differs")
    for context in value["context_compilations"]:
        premise_request = CompilerRequest.from_dict(context["request"])
        premise_result = CompilerResult.from_dict(context["compiler_result"])
        _require(premise_result.request_cid == premise_request.request_cid and context["applied_to_query_construction"] is False,
                 "context request or query boundary differs")
        _require(context["text_sha256"] == hashlib.sha256(premise_request.source_text.encode()).hexdigest()
                 and premise_request.atom_vocabulary.to_dict() == request.atom_vocabulary.to_dict()
                 and premise_request.allow_explicit_partial is False and dict(premise_request.config) == {},
                 "context source or frozen vocabulary differs")
    native = value["roundtrip"]["native_result"]
    _require(type(value["roundtrip"]) is dict and set(value["roundtrip"]) == {"status", "native_result", "rendered_text", "reparsed_ir", "exact_ir", "generated_vs_reparsed", "success_means", "source_fidelity_established"}
             and value["roundtrip"]["success_means"] == "stage_completion_only"
             and value["roundtrip"]["source_fidelity_established"] is False, "roundtrip evidence scope differs")
    if native is not None:
        result = CanonicalSemanticRoundTripResult.from_dict(native)
        _require(result.request_cid == request.request_cid, "native roundtrip request differs")
        candidate = result.l1_result.canonical_ir.to_dict() if result.l1_result is not None and result.l1_result.canonical_ir is not None else None
        reparsed = result.l2_result.canonical_ir.to_dict() if result.l2_result is not None and result.l2_result.canonical_ir is not None else None
        rendered = result.t1_result.text if result.t1_result is not None else None
        _require(value["canonical_ir"] == candidate and value["roundtrip"]["reparsed_ir"] == reparsed
                 and value["roundtrip"]["rendered_text"] == rendered, "generated IR or rendered text differs from native stages")
        expected_status = result.l1_result.status.value if result.l1_result is not None else result.status.value
        exact = bool(candidate is not None and reparsed is not None and _raw(candidate) == _raw(reparsed))
        _require(policy["requires_context_resolution"] is False and value["construction_status"] == expected_status
                 and value["roundtrip"]["status"] == result.status.value and value["roundtrip"]["exact_ir"] is exact
                 and value["roundtrip"]["generated_vs_reparsed"] == (_ir_diagnostics(reparsed, candidate) if candidate is not None else None),
                 "construction status or roundtrip diagnostics differ from native stages")
    else:
        _require(value["input_policy"]["requires_context_resolution"] is True and value["canonical_ir"] is None
                 and value["construction_status"] == "unavailable" and value["roundtrip"]["exact_ir"] is None
                 and value["roundtrip"]["status"] == "unrun" and value["roundtrip"]["rendered_text"] is None
                 and value["roundtrip"]["reparsed_ir"] is None and value["roundtrip"]["generated_vs_reparsed"] is None,
                 "unrun constructor must disclose context unavailability")
    _require(value["schema_acceptance"] is (value["canonical_ir"] is not None), "schema acceptance differs from candidate")
    projection = value["native_projection"]
    _require(type(projection) is dict and projection.get("status") in ("unrun", "unavailable", "executed")
             and projection.get("proofs_executed") is False, "native projection cannot become proof evidence")
    if projection["status"] == "executed":
        from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalTypedBridge

        _require(projection.get("scope") == "typed_bridge_transport_with_disclosed_gaps"
                 and projection.get("artifact_sha256") == _digest(projection["artifact"]), "native bridge artifact digest or scope differs")
        bridge = CanonicalTypedBridge.from_dict(projection["artifact"])
        _require(bridge.bridge_cid == projection["bridge_cid"]
                 and bridge.family_identity.to_dict() == projection["family_identity"]
                 and bridge.views["canonical_roundtrip_ir"].to_dict()["payload"] == value["canonical_ir"]
                 and bridge.views["source_text"].to_dict()["payload"]["source_text"] == request.source_text,
                 "native bridge differs from generated IR or source")
    _require(type(value["proof_scopes"]) is dict and set(value["proof_scopes"]) == {"native_proof", "kernel_proof", "useful_proof_coverage"}
             and all(record["status"] == "unrun" for record in value["proof_scopes"].values()), "unexecuted checks cannot become proof receipts")


def score_authored_reference(construction, authored_target) -> dict:
    """Read an independent reference only after construction is sealed.

    Counts compare typed atoms under exact core tuples. They do not establish
    qualifier coassociation across rules or logical equivalence; exact IR and
    full-rule counts remain separate. A null target is an authored expectation
    of no candidate, not a certificate that the source has no legal meaning.
    """
    _validate_construction(construction)
    candidate = construction["canonical_ir"]
    value = {"schema": SCORE_SCHEMA, "construction_sha256": construction["content_sha256"],
             "construction_status": construction["construction_status"], "schema_acceptance": construction["schema_acceptance"],
             "roundtrip_exact_ir": construction["roundtrip"]["exact_ir"],
             "reference_read_after_construction": True, "semantic_equivalence_checked": False,
             "source_fidelity_established": False, "qualified": False}
    if authored_target is None:
        value.update(reference_kind="authored_expected_abstention", reference_sha256=_digest(None),
                     negative_expectation_met=candidate is None, candidate_absent=candidate is None,
                     negative_semantics_certified=False, exact_ir=False)
    else:
        reference = _canonical(authored_target).to_dict()
        value.update(reference_kind="authored_independent_canonical_ir", reference_sha256=_digest(reference),
                     **_ir_diagnostics(candidate, reference))
    value["content_sha256"] = _digest(value)
    return value

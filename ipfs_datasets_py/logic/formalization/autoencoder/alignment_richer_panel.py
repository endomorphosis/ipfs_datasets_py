"""A small exposed Legal fixture with manual sources and manual references.

References are authored independently of compiler/decompiler *machinery*, not
independently reviewed by humans.  Both sides are synthetic fixture authorship.
The seven-facet IR preserves named flat qualifiers; it does not establish their
legal interpretation, quantified scope, calendar semantics, or theorem truth.

This module prepares JSON data and typed vocabulary only.  It never encodes,
compiles, renders, proves, writes files, or imports optional model stacks.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy

SCHEMA = "alignment-richer-panel/v1"
PANEL_ID = "alignment-richer-legal-authored-development-v1"
EVALUATION_ROLE = "exposed_development"
DOMAIN_ID = "legal_ir"
LOGIC_FAMILY = "deontic"
CORE_FACETS = ("modality", "actor", "action", "object")
QUALIFIER_FACETS = ("conditions", "exceptions", "temporal")
_LIMITS = {"max_rows": 64, "max_source_chars": 4000, "max_context_chars": 2000,
           "max_rules_per_positive": 1, "max_qualifiers_per_facet": 3}
_PROVENANCE = {
    "source_origin": "manual_fixture_authored_text",
    "target_origin": "synthetic_authored_unreviewed",
    "target_construction": "manual_literals_not_compiler_or_decoder_outputs",
    "source_target_pair_authorship": "same_fixture_author_unreviewed",
    "independent_from_compiler_decoder_machinery": True,
    "independent_source_review_available": False,
    "source_author_independence_authenticated": False,
    "reviewer_identity_authenticated": False,
    "natural_source_corpus": False,
    "review_status": "pending_human_review",
    "proof_verified": False,
}
_CAPABILITIES = {
    "semantic_ir_interface": "CanonicalRoundTripIR@1",
    "positive_representation": "flat_seven_facets_single_rule",
    "conditions_connective": "all",
    "exceptions_connective": "any",
    "temporal_connective": "all_named_constraints",
    "scope_representation": "qualifiers_apply_to_whole_single_rule",
    "quantified_binders": "unsupported",
    "nested_scope": "unsupported",
    "context_interpretation": "explicit_authored_assumptions_separate_from_source",
    "current_compiler_context_input": "unavailable",
    "temporal_reasoning": "opaque_atoms_no_calendar_or_solver_semantics",
    "native_legal_semantics_verified": False,
    "native_temporal_semantics_verified": False,
    "source_fidelity_verified": False,
}
_ROW_KEYS = frozenset({
    "id", "group_id", "split", "row_kind", "case_variant", "evaluation_role",
    "domain_id", "logic_family", "source_text", "source_sha256", "context",
    "input_sha256", "target", "target_sha256", "expectation",
    "qualifier_vocabulary", "interpretation_bundle_id", "provenance",
    "qualified", "proof_authority",
})
_PANEL_KEYS = frozenset({
    "schema", "panel_id", "evaluation_role", "domain_id", "logic_family",
    "limits", "capabilities", "provenance", "rows", "interpretation_bundles",
    "review_contract", "resource_scope", "qualified", "production_admitted",
    "proof_authority", "independent_fidelity_available", "primary_fidelity",
    "integrity",
})

# Source sentences are literal fixture text, not rendered from targets.  Each
# group's four references are separately specified below: two obligations with
# equal qualifier-list sizes but different atom identities, a permission with
# explicit conjunction/disjunction, and a prohibition.  Case bundles, including
# all contrasts, stay in one split.  Development recombines train-known core
# atoms; only the explicitly marked identity_verified qualifiers are new.
_CASES = (
    ("notice_clerk", "train", "clerk", "notify", "applicant", False, (
        "The clerk must notify the applicant within 48 hours if the application is complete, unless a court order applies.",
        "If fees have been paid, the clerk must notify the applicant before the review deadline, unless a legal hold applies.",
        "The clerk may notify the applicant within 48 hours and before the review deadline if the application is complete and fees have been paid, unless a court order applies or a legal hold applies.",
        "The clerk must not notify the applicant within 48 hours if the application is complete, unless a legal hold applies.",
    )),
    ("retention_custodian", "train", "custodian", "retain", "application", False, (
        "If the application is complete, the custodian must retain the application within 48 hours, unless a court order applies.",
        "The custodian must retain the application before the review deadline if fees have been paid, unless a legal hold applies.",
        "If the application is complete and fees have been paid, the custodian may retain the application within 48 hours and before the review deadline, unless a court order applies or a legal hold applies.",
        "If the application is complete, the custodian must not retain the application within 48 hours, unless a legal hold applies.",
    )),
    ("audit_officer", "train", "officer", "audit", "filing", False, (
        "The officer must audit the filing within 48 hours if the application is complete, unless a court order applies.",
        "If fees have been paid, the officer must audit the filing before the review deadline, unless a legal hold applies.",
        "The officer may audit the filing within 48 hours and before the review deadline if the application is complete and fees have been paid, unless a court order applies or a legal hold applies.",
        "The officer must not audit the filing within 48 hours if the application is complete, unless a legal hold applies.",
    )),
    ("authorization_registrar", "train", "registrar", "authorize", "application", False, (
        "If the application is complete, the registrar must authorize the application within 48 hours, unless a court order applies.",
        "The registrar must authorize the application before the review deadline if fees have been paid, unless a legal hold applies.",
        "If the application is complete and fees have been paid, the registrar may authorize the application within 48 hours and before the review deadline, unless a court order applies or a legal hold applies.",
        "If the application is complete, the registrar must not authorize the application within 48 hours, unless a legal hold applies.",
    )),
    ("retention_clerk", "validation", "clerk", "retain", "filing", True, (
        "The clerk must retain the filing within 48 hours if the application is complete, unless a court order applies.",
        "If identity has been verified, the clerk must retain the filing before the review deadline, unless a legal hold applies.",
        "The clerk may retain the filing within 48 hours and before the review deadline if the application is complete and fees have been paid, unless a court order applies or a legal hold applies.",
        "The clerk must not retain the filing within 48 hours if the application is complete, unless a legal hold applies.",
    )),
    ("notice_officer", "validation", "officer", "notify", "applicant", True, (
        "If the application is complete, the officer must notify the applicant within 48 hours, unless a court order applies.",
        "The officer must notify the applicant before the review deadline if identity has been verified, unless a legal hold applies.",
        "If the application is complete and fees have been paid, the officer may notify the applicant within 48 hours and before the review deadline, unless a court order applies or a legal hold applies.",
        "If the application is complete, the officer must not notify the applicant within 48 hours, unless a legal hold applies.",
    )),
)
_NEGATIVES = (
    ("quantified_scope", "unsupported", "Every clerk must review every application.",
     "quantified_binders", "abstain", "Flat actor/object atoms cannot encode universal binding."),
    ("unique_witness", "unsupported", "Each officer must assign exactly one reviewer to each application.",
     "quantified_cardinality", "abstain", "Existence, uniqueness, and per-application binding require another representation."),
    ("linked_variables", "unsupported", "A clerk may notify an applicant only if that applicant's application is complete.",
     "relational_variable_binding", "abstain", "The applicant and their application require a shared variable binding."),
    ("condition_disjunction", "unsupported", "The clerk must notify the applicant if the application is complete or fees have been paid.",
     "condition_disjunction", "abstain", "The declared flat condition list is conjunctive, not disjunctive."),
    ("exception_conjunction", "unsupported", "The clerk must notify the applicant unless a court order applies and a legal hold applies.",
     "exception_conjunction", "abstain", "The declared flat exception list is disjunctive, not conjunctive."),
    ("negated_obligation", "unsupported", "The clerk is not required to notify the applicant.",
     "negated_deontic_modality", "abstain", "Absence of obligation cannot be silently changed into prohibition or permission."),
    ("ambiguous_actor", "ambiguous", "The clerk told the custodian that they must retain the application.",
     "ambiguous_actor_reference", "clarify", "The pronoun does not identify a unique obligated actor."),
    ("relative_calendar", "ambiguous", "The clerk must notify the applicant next Friday.",
     "missing_calendar_context", "clarify", "No reference date or timezone is supplied for this deictic deadline."),
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _source_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(value, field, maximum, *, blank=False):
    _require(type(value) is str and len(value) <= maximum and (blank or bool(value.strip())),
             f"{field} must be a bounded string")


def _context(text="", bindings=None):
    return {"role": "explicit_assumptions" if text else "none_required", "text": text,
            "sha256": _source_digest(text), "bindings": deepcopy(bindings or {})}


def _input_digest(row):
    return _digest({"schema": "alignment-richer-input/v1", "domain_id": row["domain_id"],
                    "logic_family": row["logic_family"], "source_text": row["source_text"],
                    "source_sha256": row["source_sha256"], "context": row["context"]})


def _typed_target(modality, actor, action, object_, conditions, exceptions, temporal):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CanonicalRoundTripIR,
        CanonicalRule,
    )

    rule = CanonicalRule(modality=modality, actor=actor, action=action, object=object_,
                         conditions=conditions, exceptions=exceptions, temporal=temporal)
    return CanonicalRoundTripIR(rules=(rule,)).to_dict()


def _row(identity, group, split, kind, variant, source, target, *, context=None,
         expectation=None, bundle=None):
    row = {"id": f"{PANEL_ID}:{identity}", "group_id": f"{PANEL_ID}:group:{group}",
           "split": split, "row_kind": kind, "case_variant": variant,
           "evaluation_role": EVALUATION_ROLE, "domain_id": DOMAIN_ID, "logic_family": LOGIC_FAMILY,
           "source_text": source, "source_sha256": _source_digest(source),
           "context": deepcopy(context) if context is not None else _context(),
           "target": deepcopy(target), "target_sha256": _digest(target) if target is not None else None,
           "expectation": deepcopy(expectation) if expectation is not None else {
               "required_handling": "preserve_supported_facets", "reason_code": "authored_flat_reference",
               "notes": "Comparison is an authored diagnostic, not an adjudicated source meaning.",
               "authored_unreviewed": True, "compiler_outcome_observed": False},
           "qualifier_vocabulary": None, "interpretation_bundle_id": bundle,
           "provenance": deepcopy(_PROVENANCE), "qualified": False, "proof_authority": False}
    row["input_sha256"] = _input_digest(row)
    return row


def _vocabulary_fields(rows):
    fields = {name: set() for name in ("actors", "actions", "objects", "qualifiers")}
    for row in rows:
        if row["row_kind"] == "positive" and row["split"] == "train":
            rule = row["target"]["rules"][0]
            for facet, field in (("actor", "actors"), ("action", "actions"), ("object", "objects")):
                fields[field].add(rule[facet])
            fields["qualifiers"].update(atom for facet in QUALIFIER_FACETS for atom in rule[facet])
    return {name: sorted(values) for name, values in fields.items()}


def _qualifier_status(row, vocabulary):
    if row["target"] is None:
        return {"status": "no_positive_reference", "oov_atoms": {facet: [] for facet in QUALIFIER_FACETS}}
    rule = row["target"]["rules"][0]
    missing = {facet: [atom for atom in rule[facet] if atom not in vocabulary["qualifiers"]]
               for facet in QUALIFIER_FACETS}
    return {"status": "contains_authored_oov_atoms" if any(missing.values()) else "train_known",
            "oov_atoms": missing}


def _integrity(panel):
    payload = {key: value for key, value in panel.items() if key != "integrity"}
    rows = panel["rows"]
    return {"schema": "alignment-richer-panel-integrity/v1",
            "digest_recipe": "sha256_sorted_compact_utf8_json_payload_without_integrity",
            "panel_payload_sha256": _digest(payload),
            "rows_sha256": _digest(rows),
            "train_positive_rows_sha256": _digest([r for r in rows if r["row_kind"] == "positive" and r["split"] == "train"]),
            "development_positive_rows_sha256": _digest([r for r in rows if r["row_kind"] == "positive" and r["split"] == "validation"]),
            "interpretation_bundles_sha256": _digest(panel["interpretation_bundles"]),
            "row_kind_counts": dict(sorted(Counter(r["row_kind"] for r in rows).items())),
            "split_counts": dict(sorted(Counter(r["split"] for r in rows).items()))}


def build_alignment_richer_panel() -> dict:
    """Return a detached deterministic authored fixture; no vectors or execution."""
    rows = []
    for group, split, actor, action, object_, oov, sources in _CASES:
        references = (
            ("O", ("application_complete",), ("court_order",), ("within_48_hours",)),
            ("O", ("identity_verified" if oov else "fees_paid",), ("legal_hold",), ("before_the_review_deadline",)),
            ("P", ("application_complete", "fees_paid"), ("court_order", "legal_hold"),
             ("before_the_review_deadline", "within_48_hours")),
            ("F", ("application_complete",), ("legal_hold",), ("within_48_hours",)),
        )
        for variant, source, reference in zip(("single_a", "single_b", "multiple", "prohibition"),
                                               sources, references, strict=True):
            modality, conditions, exceptions, temporal = reference
            target = _typed_target(modality, actor, action, object_, conditions, exceptions, temporal)
            rows.append(_row(f"{group}:{variant}", group, split, "positive", variant, source, target))

    for case, kind, source, reason, handling, notes in _NEGATIVES:
        expectation = {"required_handling": handling, "reason_code": reason, "notes": notes,
                       "authored_unreviewed": True, "compiler_outcome_observed": False}
        rows.append(_row(f"negative:{case}", f"negative:{case}", "validation", kind, case,
                         source, None, expectation=expectation))

    bundle_id = f"{PANEL_ID}:interpretation:designated_official"
    shared_source = ("The designated official must retain the case file within 48 hours if the "
                     "application is complete, unless a court order applies.")
    context_rows = []
    for actor in ("clerk", "custodian"):
        context = _context(f"For this policy, 'designated official' denotes the {actor}.",
                           {"designated_official": {"kind": "actor_atom", "value": actor}})
        target = _typed_target("O", actor, "retain", "case_file", ("application_complete",),
                               ("court_order",), ("within_48_hours",))
        expectation = {"required_handling": "explicit_context_or_unavailable",
                       "reason_code": "auxiliary_actor_interpretation", "notes":
                       "These caller-supplied assumptions are not inferred from the shared source.",
                       "authored_unreviewed": True, "compiler_outcome_observed": False}
        context_rows.append(_row(f"context:{actor}", "interpretation:designated_official", "validation",
                                 "explicit_context", actor, shared_source, target, context=context,
                                 expectation=expectation, bundle=bundle_id))
    rows.extend(context_rows)
    vocabulary = _vocabulary_fields(rows)
    for row in rows:
        row["qualifier_vocabulary"] = _qualifier_status(row, vocabulary)
    bundles = [{"bundle_id": bundle_id, "group_id": context_rows[0]["group_id"], "split": "validation",
                "source_sha256": _source_digest(shared_source), "row_ids": [r["id"] for r in context_rows],
                "input_sha256s": [r["input_sha256"] for r in context_rows],
                "source_only_consumption_allowed": False, "excluded_from_source_only_training": True,
                "excluded_from_source_only_evaluation_gold": True, "authored_unreviewed": True}]
    panel = {"schema": SCHEMA, "panel_id": PANEL_ID, "evaluation_role": EVALUATION_ROLE,
             "domain_id": DOMAIN_ID, "logic_family": LOGIC_FAMILY, "limits": deepcopy(_LIMITS),
             "capabilities": deepcopy(_CAPABILITIES), "provenance": deepcopy(_PROVENANCE),
             "rows": rows, "interpretation_bundles": bundles,
             "review_contract": {"status": "not_prepared", "completed_reviews": 0,
                 "separate_from_original_40": True, "existing_review_receipt_reusable": False,
                 "candidate_reference_blind_payload_required": True, "source_context_review_required": True,
                 "context_review_requires_explicit_schema": True,
                 "reviewer_authentication": "unavailable", "author_independence": "unavailable"},
             "resource_scope": {"vectors_present": False, "encoder_calls": 0, "model_calls": 0,
                 "provider_calls": 0, "prover_calls": 0, "compiler_calls": 0, "decoder_calls": 0,
                 "sealed_inputs_accessed": False},
             "qualified": False, "production_admitted": False, "proof_authority": False,
             "independent_fidelity_available": False, "primary_fidelity": "unavailable"}
    panel["integrity"] = _integrity(panel)
    validate_alignment_richer_panel(panel)
    return panel


def _validate_row(row):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    _require(type(row) is dict and set(row) == _ROW_KEYS, "richer row fields changed")
    for field in ("id", "group_id", "case_variant"):
        _text(row[field], field, 256)
    _require(type(row["split"]) is str and row["split"] in {"train", "validation"},
             "only exposed train/validation splits are permitted")
    _require(type(row["row_kind"]) is str
             and row["row_kind"] in {"positive", "unsupported", "ambiguous", "explicit_context"}, "unknown row kind")
    _require(row["evaluation_role"] == EVALUATION_ROLE and row["domain_id"] == DOMAIN_ID
             and row["logic_family"] == LOGIC_FAMILY, "richer row family/role changed")
    _require(row["provenance"] == _PROVENANCE, "richer row provenance changed")
    _require(row["qualified"] is False and row["proof_authority"] is False, "fixture cannot acquire authority")
    _text(row["source_text"], "source_text", _LIMITS["max_source_chars"])
    _require(row["source_sha256"] == _source_digest(row["source_text"]), "source digest mismatch")
    context = row["context"]
    _require(type(context) is dict and set(context) == {"role", "text", "sha256", "bindings"}, "context fields changed")
    _text(context["text"], "context.text", _LIMITS["max_context_chars"], blank=True)
    _require(context["sha256"] == _source_digest(context["text"]), "context digest mismatch")
    _require(type(context["bindings"]) is dict and len(context["bindings"]) <= 4, "context binding budget exceeded")
    if row["row_kind"] == "explicit_context":
        _require(context["role"] == "explicit_assumptions" and bool(context["text"].strip())
                 and bool(context["bindings"]) and row["split"] == "validation", "explicit context must be supplied")
        _text(row["interpretation_bundle_id"], "interpretation_bundle_id", 256)
        for name, binding in context["bindings"].items():
            _text(name, "binding name", 256)
            _require(type(binding) is dict and set(binding) == {"kind", "value"}
                     and binding["kind"] == "actor_atom", "unsupported auxiliary binding shape")
            _text(binding["value"], "binding value", 256)
    else:
        _require(context == _context() and row["interpretation_bundle_id"] is None,
                 "source-only rows cannot absorb auxiliary assumptions")
    _require(row["input_sha256"] == _input_digest(row), "source/context input digest mismatch")
    expectation = row["expectation"]
    _require(type(expectation) is dict and set(expectation) == {
        "required_handling", "reason_code", "notes", "authored_unreviewed", "compiler_outcome_observed"},
        "expectation fields changed")
    for field in ("required_handling", "reason_code", "notes"):
        _text(expectation[field], f"expectation.{field}", 1000)
    _require(expectation["authored_unreviewed"] is True and expectation["compiler_outcome_observed"] is False,
             "authored expectations cannot become measured outcomes")
    if row["row_kind"] in {"unsupported", "ambiguous"}:
        _require(row["split"] == "validation" and row["target"] is None and row["target_sha256"] is None,
                 "negative cases cannot be positive training/evaluation targets")
        _require(expectation["required_handling"] == ("abstain" if row["row_kind"] == "unsupported" else "clarify"),
                 "negative disposition changed")
    else:
        _require(type(row["target"]) is dict and set(row["target"]) == {"rules"}
                 and type(row["target"]["rules"]) is list and len(row["target"]["rules"]) == 1,
                 "positive reference must contain one canonical rule")
        rule = row["target"]["rules"][0]
        _require(type(rule) is dict, "reference rule must be an object")
        for facet in QUALIFIER_FACETS:
            _require(type(rule.get(facet)) is list and 0 < len(rule[facet]) <= _LIMITS["max_qualifiers_per_facet"],
                     "richer positives require bounded nonempty qualifiers")
        _require(CanonicalRoundTripIR.from_dict(row["target"]).to_dict() == row["target"],
                 "reference target must already use the canonical typed wire shape")
        _require(row["target_sha256"] == _digest(row["target"]), "reference target digest mismatch")
        _require(expectation["required_handling"] == ("explicit_context_or_unavailable"
                 if row["row_kind"] == "explicit_context" else "preserve_supported_facets"),
                 "positive handling changed")
        if row["row_kind"] == "explicit_context":
            _require(len(context["bindings"]) == 1 and next(iter(context["bindings"].values()))["value"] == rule["actor"],
                     "authored actor reference must match its explicit context binding")


def validate_alignment_richer_panel(panel: dict) -> dict:
    """Check structural/integrity/split contracts; never adjudicate source meaning."""
    _require(type(panel) is dict and set(panel) == _PANEL_KEYS, "richer panel fields changed")
    _require(panel["schema"] == SCHEMA and panel["panel_id"] == PANEL_ID
             and panel["evaluation_role"] == EVALUATION_ROLE and panel["domain_id"] == DOMAIN_ID
             and panel["logic_family"] == LOGIC_FAMILY, "richer panel schema/family/role changed")
    _require(panel["limits"] == _LIMITS and panel["capabilities"] == _CAPABILITIES
             and panel["provenance"] == _PROVENANCE, "richer panel limits/capabilities/provenance changed")
    _require(all(panel[key] is False for key in ("qualified", "production_admitted", "proof_authority",
                                               "independent_fidelity_available"))
             and panel["primary_fidelity"] == "unavailable", "fixture cannot acquire authority")
    _require(type(panel["rows"]) is list and 0 < len(panel["rows"]) <= _LIMITS["max_rows"], "row budget exceeded")
    rows = panel["rows"]
    for row in rows:
        _validate_row(row)
    _require(len({r["id"] for r in rows}) == len(rows), "duplicate richer row identity")
    train = [r for r in rows if r["split"] == "train"]
    development = [r for r in rows if r["split"] == "validation"]
    _require(train and development, "both exposed partitions are required")
    for field in ("id", "group_id", "source_sha256", "input_sha256", "target_sha256"):
        left = {r[field] for r in train if r[field] is not None}
        right = {r[field] for r in development if r[field] is not None}
        _require(left.isdisjoint(right), f"cross-split {field} leakage")
    vocabulary = _vocabulary_fields(rows)
    for row in rows:
        _require(row["qualifier_vocabulary"] == _qualifier_status(row, vocabulary), "qualifier OOV declaration changed")
        if row["row_kind"] == "positive":
            rule = row["target"]["rules"][0]
            _require(all(rule[facet] in vocabulary[field] for facet, field in
                         (("actor", "actors"), ("action", "actions"), ("object", "objects"))),
                     "positive core atoms must be train-known")
    by_source = {}
    for row in rows:
        by_source.setdefault(row["source_sha256"], []).append(row)
    for siblings in by_source.values():
        if len(siblings) > 1:
            _require(all(r["row_kind"] == "explicit_context" for r in siblings)
                     and len({r["group_id"] for r in siblings}) == 1
                     and len({r["interpretation_bundle_id"] for r in siblings}) == 1
                     and len({r["context"]["sha256"] for r in siblings}) == len(siblings)
                     and len({r["input_sha256"] for r in siblings}) == len(siblings)
                     and len({r["target_sha256"] for r in siblings}) == len(siblings),
                     "same source with different targets requires a distinct explicit interpretation bundle")
    _require(type(panel["interpretation_bundles"]) is list, "interpretation bundles must be a list")
    contextual = {r["id"]: r for r in rows if r["row_kind"] == "explicit_context"}
    declared = set()
    for bundle in panel["interpretation_bundles"]:
        _require(type(bundle) is dict and set(bundle) == {"bundle_id", "group_id", "split", "source_sha256", "row_ids",
                 "input_sha256s", "source_only_consumption_allowed", "excluded_from_source_only_training",
                 "excluded_from_source_only_evaluation_gold", "authored_unreviewed"}, "interpretation bundle fields changed")
        _require(type(bundle["row_ids"]) is list and len(bundle["row_ids"]) >= 2
                 and len(set(bundle["row_ids"])) == len(bundle["row_ids"])
                 and all(identity in contextual and identity not in declared for identity in bundle["row_ids"]),
                 "interpretation bundle membership changed")
        members = [contextual[identity] for identity in bundle["row_ids"]]
        _require(all(r["interpretation_bundle_id"] == bundle["bundle_id"] and r["group_id"] == bundle["group_id"]
                     and r["split"] == bundle["split"] and r["source_sha256"] == bundle["source_sha256"] for r in members)
                 and bundle["input_sha256s"] == [r["input_sha256"] for r in members], "interpretation bundle bindings changed")
        _require(bundle["source_only_consumption_allowed"] is False
                 and all(bundle[key] is True for key in ("excluded_from_source_only_training",
                         "excluded_from_source_only_evaluation_gold", "authored_unreviewed")), "context exclusion changed")
        declared.update(bundle["row_ids"])
    _require(declared == set(contextual), "context rows must have complete bundle accounting")
    _require(panel["review_contract"] == {"status": "not_prepared", "completed_reviews": 0,
             "separate_from_original_40": True, "existing_review_receipt_reusable": False,
             "candidate_reference_blind_payload_required": True, "source_context_review_required": True,
             "context_review_requires_explicit_schema": True,
             "reviewer_authentication": "unavailable", "author_independence": "unavailable"},
             "review preparation cannot be inferred from fixture construction")
    _require(panel["resource_scope"] == {"vectors_present": False, "encoder_calls": 0, "model_calls": 0,
             "provider_calls": 0, "prover_calls": 0, "compiler_calls": 0, "decoder_calls": 0,
             "sealed_inputs_accessed": False}, "fixture resource scope changed")
    _require(panel["integrity"] == _integrity(panel), "richer panel integrity mismatch")
    return {"schema": "alignment-richer-panel-contract-validation/v1", "status": "validated_authored_fixture_contract",
            "panel_payload_sha256": panel["integrity"]["panel_payload_sha256"],
            "row_kind_counts": panel["integrity"]["row_kind_counts"],
            "training_positive_rows": sum(r["row_kind"] == "positive" for r in train),
            "development_positive_rows": sum(r["row_kind"] == "positive" for r in development),
            "development_oov_qualifier_positive_rows": sum(r["row_kind"] == "positive"
                and r["qualifier_vocabulary"]["status"] == "contains_authored_oov_atoms" for r in development),
            "typed_target_contract_validated": True, "source_meaning_adjudicated": False,
            "proof_authority": False, "qualified": False, "independent_fidelity_available": False}


def richer_training_vocabulary(panel: dict):
    """Build owner vocabulary from source-only positive TRAIN references alone."""
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary

    validate_alignment_richer_panel(panel)
    return CanonicalAtomVocabulary(**_vocabulary_fields(panel["rows"]))


def richer_row_input(row: dict, *, mode: str = "source_only") -> dict:
    """Return exact input without reference/expectation hints or context inference.

    ``source_with_context`` exposes the separately declared context.  It does
    not make the current compiler consume or resolve those assumptions.
    """
    _validate_row(row)
    _require(mode in {"source_only", "source_with_context"}, "unknown richer input mode")
    _require(mode != "source_only" or row["row_kind"] != "explicit_context",
             "explicit-context interpretation cannot be consumed as source-only")
    result = {"schema": "alignment-richer-source-input/v1", "row_id": row["id"],
              "domain_id": row["domain_id"], "logic_family": row["logic_family"],
              "source_text": row["source_text"], "source_sha256": row["source_sha256"],
              "input_sha256": row["input_sha256"]}
    if mode == "source_with_context":
        result["context"] = deepcopy(row["context"])
    return result

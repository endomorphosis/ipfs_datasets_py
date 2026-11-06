"""Bind authenticated applicability custody to an unverified conditional instance.

The existing applicability and conditional-instance owners replay their complete
original evidence. Their conjunction is a custody record, not authority to apply
a definition, extract membership, rewrite a norm or admit a legal meaning.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_definition_applicability_v1 as applicability
from . import legal_norm_definition_evidence_v1 as evidence

SCHEMA = "legal-norm-definition-application-binding/v1"
PROFILE = "authenticated-applicability-to-unverified-conditional-instance-custody/v1"
MAX_REPORT_BYTES = evidence.MAX_OUTPUT_BYTES
MAX_REQUEST_BYTES = 128 * 1024
APPLICABILITY_FIELDS = {
    "companion", "norm_subject", "norm_manifest", "applicability_registry",
    "applicability_policy", "applicability_reviews", "expected_companion_sha256",
    "companion_inputs", "expected_norm_subject_sha256", "expected_norm_manifest_sha256",
    "declaration_artifact_id", "expected_declaration_raw_sha256", "expected_declaration_sha256",
    "expected_applicability_registry_sha256", "expected_applicability_policy_sha256",
    "expected_applicability_reviews_sha256", "at_time_utc", "observed_artifact_sha256s",
    "observed_pins", "evidence_artifacts", "definition_observations",
}
AUTHORITY = dict(applicability.AUTHORITY,
    definition_assumption_verified=False, membership_assumption_verified=False,
    binder_valuation_verified=False, carrier_identification_verified=False,
    legal_date_formal_time_alignment_verified=False, conditional_theorems_checked=False,
    lean_compilation_verified=False, norm_witness_extracted=False,
    applicability_signatures_cover_conditional_request=False,
    applicability_signatures_cover_binding=False, definition_application_verified=False,
    governing_selection_verified=False)
_SELF_PATH = Path(__file__).resolve()
_DIRECT_PINS = {str(Path(module.__file__).resolve()):
                hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in (applicability, evidence)}
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_OPERATION_PINS = None
_need, _keys, _sha = evidence._need, evidence._keys, evidence._sha


def _wire(value):
    return evidence.norm.correspondence_owner._wire(value, MAX_REPORT_BYTES)


def norm_definition_application_binding_sha256(value):
    """Hash the complete bounded canonical binding, not a proof or signature."""
    return hashlib.sha256(_wire(value)).hexdigest()


def _same(left, right):
    return _wire(left) == _wire(right)


def _pure_pins():
    _need(hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest() == _SELF_PIN,
          "norm definition application binding producer changed since import")
    actual = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _DIRECT_PINS}
    _need(actual == _DIRECT_PINS, "direct application binding producer changed since import")
    result = evidence._pure_pins()
    result.update(actual)
    result[str(_SELF_PATH)] = _SELF_PIN
    return result


def _owner():
    # Fixed installed owner only. Candidate files and caller-provided paths are
    # never loaded; qualification and installation belong to that owner.
    from . import legal_bound_variable_definition_v1
    return legal_bound_variable_definition_v1


def _pins(owner):
    global _OPERATION_PINS
    result = _pure_pins()
    for observed in (applicability._pins(), owner._pins(owner._owners())):
        for path, pin in observed.items():
            _need(path not in result or result[path] == pin,
                  "application binding producer observations disagree")
            result[path] = pin
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(result)
    _need(result == _OPERATION_PINS, "application binding producers changed since first operation")
    return result


def _preflight(original):
    _pure_pins()
    detached, commitment = evidence._snapshot(original)
    _keys(detached["applicability_inputs"], APPLICABILITY_FIELDS,
          "complete original applicability assessment replay arguments")
    _sha(detached["expected_applicability_assessment_sha256"], "complete applicability assessment")
    _need(applicability.norm_definition_applicability_sha256(detached["applicability_assessment"])
          == detached["expected_applicability_assessment_sha256"],
          "independent complete applicability assessment pin differs")
    _sha(detached["expected_conditional_request_sha256"], "exact conditional request bytes")
    raw = detached["conditional_request_raw"]
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          "bounded exact conditional request bytes required")
    _need(hashlib.sha256(raw).hexdigest() == detached["expected_conditional_request_sha256"],
          "independent conditional request byte pin differs")
    _keys(detached["applicability_inputs"]["companion_inputs"], applicability.COMPANION_FIELDS,
          "complete original companion replay arguments")
    return detached, commitment


def _binding_selection(assessment, request):
    """Check a replayed association and parsed request; grant no input authority."""
    _need(assessment["schema"] == applicability.ASSESSMENT_SCHEMA
          and assessment["profile"] == applicability.PROFILE,
          "existing exact-use applicability assessment required")
    _need(assessment["common_body_content_status"] == "valid_declared_content"
          and assessment["content_blockers"] == []
          and assessment["common_body_authenticated_under_selected_trust"] is True
          and assessment["partial_declaration_custody_prerequisites_satisfied_under_selected_trust"] is True,
          "authenticated whole applicability body and partial custody prerequisites required")
    _need(assessment["governing_definition_use"] is None
          and assessment["selected_interpretation"] is None
          and assessment["native_ast_rewritten"] is False
          and all(value is False for value in assessment["authority"].values()),
          "applicability custody cannot confer governing or application authority")
    companion = assessment["original_companion"]
    companion_sha = evidence.norm_definition_evidence_sha256(companion)
    _need(request["companion_sha256"] == companion_sha == assessment["expected_companion_sha256"],
          "conditional request belongs to another complete companion")
    uses = applicability._group_uses(companion)
    _need(_same(assessment["uses"], uses), "complete ordered applicability use population differs")
    declaration = assessment["declaration_record"]
    _need(type(declaration) is dict and declaration["schema"] == applicability.DECLARATION_SCHEMA
          and declaration["profile"] == applicability.PROFILE,
          "complete original applicability declaration required")
    choices = declaration["decisions"]
    _need(type(choices) is list and len(choices) == len(uses),
          "complete ordered original applicability choices required")
    matches = [(index, use) for index, use in enumerate(uses) if _same(use["target"], request["target"])]
    _need(len(matches) == 1 and request["target"].get("kind") == "variable",
          "one exact whole nominated variable target required")
    index, use = matches[0]
    choice = choices[index]
    _keys(choice, {"use_id", "use_sha256", "decision", "selected_link_ref", "legal_as_of_date",
                   "scope_statement", "rationale", "evidence_refs"}, "original applicability choice")
    _need(choice["use_id"] == use["use_id"]
          and choice["use_sha256"] == applicability.norm_definition_applicability_sha256(use),
          "selected applicability choice belongs to another exact ordered use")
    _need(choice["decision"] == "declare_one_supplied_alternative_applicable",
          "unresolved applicability cannot bind a conditional instance")
    ref = choice["selected_link_ref"]
    link = applicability._selected_link(companion, use, ref)
    _need(ref["sha256"] == request["link_sha256"]
          and link["request_link"]["alternative_id"] == request["alternative_id"],
          "conditional request differs from the exact declared alternative or complete link")
    for field in ("definition_term_ref", "definition_ast_ref"):
        _need(_same(request[field], link[field]), "conditional definition commitment differs: " + field)
    _need(_same(request["source_paths"], link["request_link"]["source_paths"])
          and _same(request["source_paths"], use["source_paths"]),
          "complete ordered conditional source paths differ")
    context = link["typed_context"]
    _need(context["binding"] is not None and context["argument"] is not None
          and _same(request["binding"], context["binding"])
          and _same(request["argument"], context["argument"])
          and _same(use["typed_context"], context)
          and _same(use["typed_node"], link["typed_node"])
          and _same(use["typed_row"], link["typed_row"])
          and _same(use["source_rows"], link["source_rows"])
          and _same(use["norm_source_target"], link["norm_source_target"]),
          "conditional occurrence, binder, argument or source geometry differs")
    binder = request["binder_target"]
    _need(type(binder) is dict and binder.get("kind") == "binder"
          and binder.get("typed_path") == context["binding"]["typed_path"]
          and binder.get("binder_name") == context["binding"]["name"]
          and binder.get("typed_sort") == "Object" and binder.get("native_sort") is None,
          "conditional original binder target differs")
    return index, use, choice, ref, link


def prepare_norm_definition_application_binding_v1(applicability_assessment, conditional_request_raw, *,
        expected_applicability_assessment_sha256, applicability_inputs,
        expected_conditional_request_sha256):
    """Replay both existing owners and retain their association without application."""
    original = dict(applicability_assessment=applicability_assessment,
        conditional_request_raw=conditional_request_raw,
        expected_applicability_assessment_sha256=expected_applicability_assessment_sha256,
        applicability_inputs=applicability_inputs,
        expected_conditional_request_sha256=expected_conditional_request_sha256)
    detached, commitment = _preflight(original)
    owner = _owner()
    pins = _pins(owner)

    def fence():
        _need(evidence._snapshot(original)[1] == commitment
              and evidence._snapshot(detached)[1] == commitment,
              "application binding inputs changed during operation")
        _need(_pins(owner) == pins, "application binding producers changed during operation")

    fence()
    checked = applicability.validate_norm_definition_applicability_v1(detached["applicability_assessment"],
        expected_report_sha256=detached["expected_applicability_assessment_sha256"],
        **detached["applicability_inputs"])
    fence()
    request = owner._parse(detached["conditional_request_raw"], detached["expected_conditional_request_sha256"])
    index, use, choice, ref, link = _binding_selection(checked, request)
    inputs = detached["applicability_inputs"]
    _need(_same(checked["original_companion"], inputs["companion"])
          and checked["expected_companion_sha256"] == inputs["expected_companion_sha256"]
          and _same(checked["subject"], inputs["norm_subject"]),
          "replayed applicability original norm or companion differs")
    conditional = owner.prepare_bound_variable_definition_v1(checked["original_companion"],
        detached["conditional_request_raw"], expected_companion_sha256=inputs["expected_companion_sha256"],
        expected_request_sha256=detached["expected_conditional_request_sha256"],
        companion_inputs=inputs["companion_inputs"])
    fence()
    _need(_same(conditional["request"], request) and _same(conditional["selected_link"], link)
          and conditional["companion_sha256"] == inputs["expected_companion_sha256"],
          "generated conditional instance differs from the declared exact use")
    conditional_sha = owner.bound_variable_definition_sha256(conditional)
    report = {
        "schema": SCHEMA, "profile": PROFILE,
        "status": "custody_binding_prepared_conditional_instance_unverified",
        "original_applicability_assessment": checked,
        "applicability_assessment_sha256": detached["expected_applicability_assessment_sha256"],
        "conditional_request_raw_sha256": detached["expected_conditional_request_sha256"],
        "conditional_report": conditional, "conditional_report_sha256": conditional_sha,
        "selected_binding": {"use_index": index, "use": use, "choice": choice,
            "selected_link_ref": ref, "selected_link": link},
        "complete_original_populations_retained": True,
        "original_norm_and_definition_asts_unchanged": True,
        "applicability_custody_prerequisites_replayed": True,
        "applicability_custody_scope": checked["prerequisite_scope"],
        "time_context": {
            "declared_legal_as_of_date": choice["legal_as_of_date"],
            "declared_scope_statement": choice["scope_statement"],
            "applicability_evaluation_time_utc": inputs["at_time_utc"],
            "formal_evaluation_context": request["evaluation_context"],
            "legal_date_formal_time_alignment_verified": False,
            "calendar_to_nat_coercion_performed": False},
        "producer_pins": pins, "external_complete_inputs_required": True,
        "native_ast_rewritten": False, "norm_interpretation_ready": False,
        "selected_interpretation": None, "accepted_interpretation": None,
        "governing_definition_use": None, "semantic_mask": 0, "consumer_mask": 0,
        "training_mask": 0, "evaluation_gold_mask": 0,
        "backend_executed": False, "human_reviews_created": 0,
        "signatures_constructed": 0, "definition_applications": 0,
        "authority": dict(AUTHORITY),
        "limitations": [
            "The applicability signatures cover their original common declaration, not this binding or conditional request and output.",
            "Partial association custody does not establish the complete norm-review cohort, closed original norm context, governing priority or legal meaning.",
            "The conditional owner's hDefinition, optional hMembership, shared carrier, binder valuation, interpretation and fixed Nat time remain explicit unverified parameters.",
            "An applicability date and signature evaluation clock do not identify a formal Nat time or prove date/time alignment.",
            "All supplied alternatives and original use decisions remain retained; selecting one bridge does not declare rivals inapplicable or apply any decision.",
            "No membership or witness is extracted, AST is rewritten, proof is checked, semantic graph is admitted or training target is qualified.",
        ],
    }
    raw = _wire(report)
    fence()
    return json.loads(raw)


def validate_norm_definition_application_binding_v1(report, *args, expected_report_sha256, **kwargs):
    """Require an independent complete pin and both original owners' full replay."""
    _pure_pins()
    original = dict(report=report, args=list(args), kwargs=kwargs)
    detached, commitment = evidence._snapshot(original)
    _sha(expected_report_sha256, "complete application binding")
    _need(norm_definition_application_binding_sha256(detached["report"]) == expected_report_sha256,
          "independent complete application binding pin differs")
    owner = _owner()
    pins = _pins(owner)
    expected = prepare_norm_definition_application_binding_v1(*detached["args"], **detached["kwargs"])
    _need(_same(detached["report"], expected), "application binding differs from complete regeneration")
    raw = _wire(expected)
    _need(evidence._snapshot(original)[1] == commitment
          and evidence._snapshot(detached)[1] == commitment,
          "offered application binding or replay inputs changed during validation")
    _need(_pins(owner) == pins, "application binding producers changed during validation")
    return json.loads(raw)


__all__ = ["prepare_norm_definition_application_binding_v1",
           "validate_norm_definition_application_binding_v1",
           "norm_definition_application_binding_sha256"]

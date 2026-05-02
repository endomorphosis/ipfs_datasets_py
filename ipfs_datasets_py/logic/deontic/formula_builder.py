"""Formula builders for deterministic legal norm IR."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .ir import LegalNormIR


_MENTAL_STATE_TERMS = {
    "knowingly",
    "intentionally",
    "willfully",
    "recklessly",
    "purposely",
    "maliciously",
    "negligently",
    "wilfully",
    "fraudulently",
    "deliberately",
    "corruptly",
}
_LEGAL_REFERENCE_TEXT_RE = re.compile(
    r"(?:\b(?:section|subsection|chapter|title|article|part)\s+|§\s*)"
    r"([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)\b",
    re.IGNORECASE,
)
_LEGAL_REFERENCE_LIST_TEXT_RE = re.compile(
    r"(?:\bsections\s+)([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*(?:\s*(?:,|and|or)\s*[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)+)",
    re.IGNORECASE,
)
_SUPPLEMENTAL_PROCEDURE_TRIGGER_PREFIXES = {
    "triggered_by_mailing_of": "after mailing",
    "triggered_by_certified_mailing_of": "after certified mailing",
    "triggered_by_delivery_of": "after delivery",
    "triggered_by_posting_of": "after posting",
    "triggered_by_postmark_of": "after postmark",
    "triggered_by_docketing_of": "after docketing",
    "triggered_by_entry_of": "after entry",
    "triggered_by_electronic_filing_of": "after electronic filing",
    "triggered_by_electronic_service_on": "after electronic service",
    "triggered_by_transmission_of": "after transmission",
    "triggered_by_receipt_confirmation_of": "after receipt confirmation",
    "triggered_by_signature_of": "after signature",
    "triggered_by_notarization_of": "after notarization",
    "triggered_by_countersignature_of": "after countersignature",
    "triggered_by_opening_of": "after opening",
    "triggered_by_return_of": "after return",
    "triggered_by_reinstatement_of": "after reinstatement",
    "triggered_by_commencement_of": "after commencement",
    "triggered_by_execution_of": "after execution",
    "triggered_by_withdrawal_of": "after withdrawal",
    "triggered_by_determination_of": "after determination",
    "triggered_by_verification_of": "after verification",
    "triggered_by_payment_of": "after payment",
    "triggered_by_assessment_of": "after assessment",
    "triggered_by_deposit_of": "after deposit",
    "triggered_by_clearing_of": "after clearing",
    "triggered_by_calculation_of": "after calculation",
    "triggered_by_correction_of": "after correction",
    "triggered_by_adjustment_of": "after adjustment",
    "triggered_by_audit_of": "after audit",
    "triggered_by_sampling_of": "after sampling",
    "triggered_by_testing_of": "after testing",
    "triggered_by_monitoring_of": "after monitoring",
    "triggered_by_measurement_of": "after measurement",
    "triggered_by_reporting_of": "after reporting",
    "triggered_by_validation_of": "after validation",
    "triggered_by_review_of": "after review",
    "triggered_by_reconsideration_of": "after reconsideration",
    "triggered_by_final_decision_of": "after final decision",
    "triggered_by_hearing_of": "after hearing",
    "triggered_by_public_comment_on": "after public comment",
    "triggered_by_consultation_with": "after consultation",
    "triggered_by_archiving_of": "after archiving",
    "triggered_by_retention_of": "after retention",
}
_LOCAL_SCOPE_REFERENCE_EXCEPTION_RE = re.compile(
    r"^(?:as\s+(?:otherwise\s+)?provided\s+in|(?:otherwise\s+)?provided\s+in|under|pursuant\s+to)\s+this\s+"
    r"(section|subsection|chapter|title|article|part)$",
    re.IGNORECASE,
)
_LOCAL_SCOPE_REFERENCE_CONDITION_RE = re.compile(
    r"^(?:this|current)\s+(section|subsection|chapter|title|article|part)$",
    re.IGNORECASE,
)
_FORMULA_CONDITION_LIMIT = 3
_FORMULA_EXCEPTION_LIMIT = 3


def build_deontic_formula_from_ir(norm: LegalNormIR) -> str:
    """Build a deterministic deontic/frame-logic formula from typed IR."""

    operator = norm.modality
    if operator == "DEF":
        subject = normalize_predicate_name(norm.actor or "DefinedTerm")
        return f"Definition({subject})"
    if operator == "APP":
        subject = normalize_predicate_name(norm.actor or "Scope")
        target = normalize_predicate_name(_applicability_target(norm.action or "Apply"))
        return f"AppliesTo({subject}, {target})"
    if operator == "EXEMPT":
        subject = normalize_predicate_name(norm.actor or "Entity")
        action_text = norm.action or "Requirement"
        if action_text.lower().startswith("exempt from "):
            action_text = action_text[len("exempt from ") :]
        target = normalize_predicate_name(action_text)
        return f"ExemptFrom({subject}, {target})"
    if operator == "LIFE" or norm.norm_type == "instrument_lifecycle":
        subject = normalize_predicate_name(norm.actor or "Instrument")
        action_text = norm.action or "lifecycle"
        lowered = action_text.lower()
        if lowered.startswith("valid for "):
            duration = action_text[len("valid for ") :]
            return f"ValidFor({subject}, {normalize_predicate_name(duration)})"
        if lowered.startswith("expires "):
            anchor = action_text[len("expires ") :]
            return f"ExpiresAfter({subject}, {normalize_predicate_name(anchor)})"
        return f"Lifecycle({subject}, {normalize_predicate_name(action_text)})"

    action_text = _action_without_mental_state(
        _action_without_procedure_trigger_tail(_formula_action_text(norm), norm.procedure)
    )
    operator = _formula_operator(norm, action_text)
    if _is_failure_prohibition(norm, action_text):
        action_text = _strip_failure_action(action_text)
    elif _is_refrain_obligation(norm, action_text):
        action_text = _strip_refrain_action(action_text)
    elif _is_prevention_obligation(norm, action_text):
        action_text = _strip_prevention_action(action_text)
    elif _is_confidentiality_obligation(norm, action_text):
        action_text = _strip_confidentiality_action(action_text)
    elif _is_compliance_obligation(norm, action_text):
        action_text = _strip_compliance_action(action_text)
    elif _is_access_availability_obligation(norm, action_text):
        action_text = _strip_access_availability_action(action_text)
    elif _is_permission_facilitation_prohibition(norm, action_text):
        action_text = _strip_permission_facilitation_action(action_text)
    elif _is_direct_gerund_prohibition(norm, action_text):
        action_text = _normalize_refrain_action_head(action_text)
    elif _is_direct_interference_prohibition(norm, action_text):
        action_text = _strip_direct_interference_action(action_text)

    action_text = _action_without_structured_recipient_tail(norm, action_text)
    action_text = _action_without_structured_notice_recipient(norm, action_text)
    action_text = _normalize_notice_service_light_verb_action(action_text)
    action_text = _normalize_publication_light_verb_action(action_text)
    action_text = _normalize_service_light_verb_action(action_text)
    action_text = _action_without_temporal_duration_tail(norm, action_text)
    action_text = _normalize_payment_light_verb_action(action_text)
    action_text = _normalize_inspection_light_verb_action(action_text)
    action_text = _normalize_sampling_light_verb_action(action_text)
    action_text = _normalize_testing_light_verb_action(action_text)
    action_text = _normalize_monitoring_light_verb_action(action_text)
    action_text = _normalize_measurement_light_verb_action(action_text)
    action_text = _normalize_investigation_light_verb_action(action_text)
    action_text = _normalize_evaluation_light_verb_action(action_text)
    action_text = _normalize_determination_light_verb_action(action_text)
    action_text = _normalize_calculation_computation_light_verb_action(action_text)
    action_text = _normalize_collection_compilation_light_verb_action(action_text)
    action_text = _normalize_delivery_distribution_light_verb_action(action_text)
    action_text = _normalize_adoption_promulgation_light_verb_action(action_text)
    action_text = _normalize_designation_appointment_light_verb_action(action_text)
    action_text = _normalize_issuance_light_verb_action(action_text)
    action_text = _normalize_submission_light_verb_action(action_text)
    action_text = _normalize_docketing_calendaring_light_verb_action(action_text)
    action_text = _normalize_certification_light_verb_action(action_text)
    action_text = _normalize_verification_light_verb_action(action_text)
    action_text = _normalize_approval_light_verb_action(action_text)
    action_text = _normalize_authorization_accreditation_light_verb_action(action_text)
    action_text = _normalize_classification_categorization_light_verb_action(action_text)
    action_text = _normalize_transfer_conveyance_light_verb_action(action_text)
    action_text = _normalize_correction_adjustment_light_verb_action(action_text)
    action_text = _normalize_denial_light_verb_action(action_text)
    action_text = _normalize_recordkeeping_light_verb_action(action_text)
    action_text = _normalize_remittance_light_verb_action(action_text)
    action_text = _normalize_renewal_light_verb_action(action_text)
    action_text = _normalize_rescission_withdrawal_light_verb_action(action_text)
    action_text = _normalize_registration_enrollment_light_verb_action(action_text)
    action_text = _normalize_instrument_status_light_verb_action(action_text)
    action_text = _normalize_abatement_remediation_light_verb_action(action_text)
    action_text = _normalize_notification_disclosure_light_verb_action(action_text)
    action_text = _normalize_recommendation_referral_light_verb_action(action_text)
    action_text = _normalize_assessment_imposition_light_verb_action(action_text)
    action_text = _normalize_deletion_erasure_light_verb_action(action_text)
    action_text = _normalize_preservation_restoration_light_verb_action(action_text)
    action_text = _normalize_archival_retention_light_verb_action(action_text)
    action_text = _normalize_redaction_anonymization_light_verb_action(action_text)
    action_text = _normalize_masking_pseudonymization_light_verb_action(action_text)
    action_text = _normalize_encryption_decryption_light_verb_action(action_text)
    action_text = _normalize_sealing_unsealing_light_verb_action(action_text)
    action_text = _normalize_expungement_destruction_light_verb_action(action_text)
    action_text = _normalize_enforcement_remedy_light_verb_action(action_text)
    action_text = _normalize_recordation_memorialization_light_verb_action(action_text)
    action_text = _normalize_ratification_confirmation_light_verb_action(action_text)
    action_text = _normalize_attestation_notarization_light_verb_action(action_text)
    action_text = _normalize_acknowledgment_authentication_light_verb_action(action_text)
    action_text = _normalize_summarization_indexing_light_verb_action(action_text)
    action_text = _normalize_transcription_translation_light_verb_action(action_text)
    action_text = _normalize_codification_recodification_light_verb_action(action_text)
    action_text = _normalize_consolidation_reconciliation_light_verb_action(action_text)
    action_text = _normalize_aggregation_tabulation_light_verb_action(action_text)
    action_text = _normalize_segregation_sequestration_light_verb_action(action_text)
    action_text = _normalize_assignment_allocation_light_verb_action(action_text)
    action_text = _normalize_prioritization_scheduling_light_verb_action(action_text)

    action_pred = normalize_predicate_name(action_text) if action_text else "Action"
    condition_preds = _unique_predicates(_formula_condition_texts(norm))
    exception_preds = _unique_predicates(_formula_exception_texts(norm))
    temporal_preds = _formula_temporal_predicates(norm.temporal_constraints)
    procedure_preds = _formula_procedure_predicates(norm.procedure)
    procedure_preds.extend(_supplemental_procedure_predicates(norm.procedure, procedure_preds))
    modifiers = temporal_preds + procedure_preds
    mental_state_pred = _mental_state_predicate(norm)
    if mental_state_pred and mental_state_pred != "P":
        modifiers.append(mental_state_pred)

    antecedent_preds = _unique_antecedent_predicates(condition_preds[:_FORMULA_CONDITION_LIMIT] + modifiers)

    inner_parts = [_subject_predicate_expr(norm)]
    inner_parts.extend(f"{pred}(x)" for pred in antecedent_preds)
    inner_parts.extend(f"¬{pred}(x)" for pred in exception_preds[:_FORMULA_EXCEPTION_LIMIT])
    inner = " ∧ ".join(inner_parts)
    return f"{operator}(∀x ({inner} → {action_pred}(x)))"


def _formula_operator(norm: LegalNormIR, action_text: str) -> str:
    """Return the deontic operator after narrow deterministic normalization."""

    if _is_failure_prohibition(norm, action_text):
        return "O"
    if (
        _is_refrain_obligation(norm, action_text)
        or _is_prevention_obligation(norm, action_text)
        or _is_confidentiality_obligation(norm, action_text)
    ):
        return "F"
    return norm.modality


def _is_failure_prohibition(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether a prohibition of failing to act is a positive duty."""

    if norm.modality != "F":
        return False
    return bool(re.match(
        r"^(?:fail(?:ure)?|refus(?:e|al)|neglect(?:s|ed|ing)?|omit(?:s|ted|ting)?)"
        r"(?:\s+or\s+(?:fail(?:ure)?|refus(?:e|al)|neglect(?:s|ed|ing)?|omit(?:s|ted|ting)?))*"
        r"\s+to\s+\S",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _strip_failure_action(action_text: str) -> str:
    """Remove a refusal/failure wrapper from a double-negative duty action."""

    return re.sub(
        r"^(?:fail(?:ure)?|refus(?:e|al)|neglect(?:s|ed|ing)?|omit(?:s|ted|ting)?)"
        r"(?:\s+or\s+(?:fail(?:ure)?|refus(?:e|al)|neglect(?:s|ed|ing)?|omit(?:s|ted|ting)?))*"
        r"\s+to\s+",
        "",
        str(action_text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _normalize_rescission_withdrawal_light_verb_action(action_text: str) -> str:
    """Collapse rescission and withdrawal nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording)\s+"
            r"(?:a\s+|an\s+|the\s+)?rescission\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "rescind",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording)\s+"
            r"rescissions\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "rescind",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording|accept|accepts|accepted|accepting)\s+"
            r"(?:a\s+|an\s+|the\s+)?withdrawal\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "withdraw",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording|accept|accepts|accepted|accepting)\s+"
            r"withdrawals\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "withdraw",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_abatement_remediation_light_verb_action(action_text: str) -> str:
    """Collapse abatement and remediation nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|order|orders|ordered|ordering|require|requires|required|requiring|cause|causes|caused|causing|conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"(?:an?\s+|the\s+)?abatement\s+(?:of|for|from)\s+(?:the\s+)?(.+)$",
            "abate",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|order|orders|ordered|ordering|require|requires|required|requiring|cause|causes|caused|causing|conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"abatements\s+(?:of|for|from)\s+(?:the\s+)?(.+)$",
            "abate",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|order|orders|ordered|ordering|require|requires|required|requiring|cause|causes|caused|causing|conduct|conducts|conducted|conducting|perform|performs|performed|performing|undertake|undertakes|undertook|undertaken|undertaking)\s+"
            r"(?:a\s+|the\s+)?remediation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
            "remediate",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|order|orders|ordered|ordering|require|requires|required|requiring|cause|causes|caused|causing|conduct|conducts|conducted|conducting|perform|performs|performed|performing|undertake|undertakes|undertook|undertaken|undertaking)\s+"
            r"remediations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
            "remediate",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_notification_disclosure_light_verb_action(action_text: str) -> str:
    """Collapse notification and disclosure nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|give|gives|gave|given|giving|send|sends|sent|sending|issue|issues|issued|issuing|deliver|delivers|delivered|delivering)[ ]+"
            r"(?:a[ ]+|an[ ]+|the[ ]+)?notification[ ]+(?:of|to)[ ]+(?:the[ ]+)?(.+)$",
            "notify",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|give|gives|gave|given|giving|send|sends|sent|sending|issue|issues|issued|issuing|deliver|delivers|delivered|delivering)[ ]+"
            r"notifications[ ]+(?:of|to)[ ]+(?:the[ ]+)?(.+)$",
            "notify",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|give|gives|gave|given|giving|send|sends|sent|sending|issue|issues|issued|issuing|deliver|delivers|delivered|delivering)[ ]+"
            r"(?:a[ ]+|the[ ]+)?notice[ ]+to[ ]+(?:the[ ]+)?(.+)$",
            "notify",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|give|gives|gave|given|giving|furnish|furnishes|furnished|furnishing|deliver|delivers|delivered|delivering)[ ]+"
            r"(?:a[ ]+|the[ ]+)?disclosure[ ]+(?:of|to)[ ]+(?:the[ ]+)?(.+)$",
            "disclose",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|give|gives|gave|given|giving|furnish|furnishes|furnished|furnishing|deliver|delivers|delivered|delivering)[ ]+"
            r"disclosures[ ]+(?:of|to)[ ]+(?:the[ ]+)?(.+)$",
            "disclose",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_recommendation_referral_light_verb_action(action_text: str) -> str:
    """Collapse recommendation and referral nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|submit|submits|submitted|submitting|issue|issues|issued|issuing|prepare|prepares|prepared|preparing|deliver|delivers|delivered|delivering)\s+"
            r"(?:a\s+|an\s+|the\s+)?recommendation\s+(?:of|for|on|to)\s+(?:the\s+)?(.+)$",
            "recommend",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|submit|submits|submitted|submitting|issue|issues|issued|issuing|prepare|prepares|prepared|preparing|deliver|delivers|delivered|delivering)\s+"
            r"recommendations\s+(?:of|for|on|to)\s+(?:the\s+)?(.+)$",
            "recommend",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|submit|submits|submitted|submitting|issue|issues|issued|issuing|prepare|prepares|prepared|preparing|deliver|delivers|delivered|delivering)\s+"
            r"(?:a\s+|an\s+|the\s+)?referral\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "refer",
        ),
        (
            r"^(?:make|makes|made|making|provide|provides|provided|providing|submit|submits|submitted|submitting|issue|issues|issued|issuing|prepare|prepares|prepared|preparing|deliver|delivers|delivered|delivering)\s+"
            r"referrals\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "refer",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_measurement_light_verb_action(action_text: str) -> str:
    """Collapse measurement nominalizations into operative measurement acts."""

    text = str(action_text or "").strip()
    if not text:
        return text

    patterns = [
        r"^(?:conduct|perform|carry\s+out|complete|undertake)\s+(?:a\s+)?measurement\s+of\s+(.+)$",
        r"^(?:conduct|perform|carry\s+out|complete|undertake)\s+measurements\s+(?:of|on)\s+(.+)$",
        r"^(?:take|make|record)\s+(?:a\s+)?measurement\s+of\s+(.+)$",
        r"^(?:take|make|record)\s+measurements\s+(?:of|on)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            measured_object = match.group(1).strip()
            if measured_object:
                return f"measure {measured_object}"

    return text


def _normalize_investigation_light_verb_action(action_text: str) -> str:
    """Collapse investigation nominalizations into operative investigation acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|carry\s+out|carries\s+out|carried\s+out|carrying\s+out|complete|completes|completed|completing|undertake|undertakes|undertook|undertaken|undertaking)\s+"
        r"(?:an?\s+|the\s+)?investigation\s+(?:of|into)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|open|opens|opened|opening|initiate|initiates|initiated|initiating|commence|commences|commenced|commencing)\s+"
        r"(?:an?\s+|the\s+)?investigation\s+(?:of|into)\s+(?:the\s+)?(.+)$",
        r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|complete|completes|completed|completing)\s+"
        r"investigations\s+(?:of|into)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"investigate {match.group(1).strip()}"

    return text


def _normalize_evaluation_light_verb_action(action_text: str) -> str:
    """Collapse evaluation and assessment nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|carry\s+out|carries\s+out|carried\s+out|carrying\s+out|complete|completes|completed|completing|undertake|undertakes|undertook|undertaken|undertaking|make|makes|made|making)\s+"
            r"(?:an?\s+|the\s+)?evaluation\s+(?:of|on)\s+(?:the\s+)?(.+)$",
            "evaluate",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|complete|completes|completed|completing|undertake|undertakes|undertook|undertaken|undertaking|make|makes|made|making)\s+"
            r"evaluations\s+(?:of|on)\s+(?:the\s+)?(.+)$",
            "evaluate",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|carry\s+out|carries\s+out|carried\s+out|carrying\s+out|complete|completes|completed|completing|undertake|undertakes|undertook|undertaken|undertaking|make|makes|made|making)\s+"
            r"(?:an?\s+|the\s+)?assessment\s+(?:of|on)\s+(?:the\s+)?(.+)$",
            "assess",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|complete|completes|completed|completing|undertake|undertakes|undertook|undertaken|undertaking|make|makes|made|making)\s+"
            r"assessments\s+(?:of|on)\s+(?:the\s+)?(.+)$",
            "assess",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_determination_light_verb_action(action_text: str) -> str:
    """Collapse legal determination nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|render|renders|rendered|rendering|reach|reaches|reached|reaching)\s+"
        r"(?:a\s+|an\s+|the\s+)?determination\s+(?:of|on|as\s+to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|render|renders|rendered|rendering)\s+"
        r"determinations\s+(?:of|on|as\s+to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"determine {match.group(1).strip()}"

    return text


def _normalize_calculation_computation_light_verb_action(action_text: str) -> str:
    """Collapse calculation and computation nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|conduct|conducts|conducted|conducting|complete|completes|completed|completing|prepare|prepares|prepared|preparing)\s+"
            r"(?:a\s+|an\s+|the\s+)?calculation\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "calculate",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|conduct|conducts|conducted|conducting|complete|completes|completed|completing|prepare|prepares|prepared|preparing)\s+"
            r"calculations\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "calculate",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|conduct|conducts|conducted|conducting|complete|completes|completed|completing|prepare|prepares|prepared|preparing)\s+"
            r"(?:a\s+|an\s+|the\s+)?computation\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "compute",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|conduct|conducts|conducted|conducting|complete|completes|completed|completing|prepare|prepares|prepared|preparing)\s+"
            r"computations\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "compute",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_collection_compilation_light_verb_action(action_text: str) -> str:
    """Collapse collection and compilation nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|conduct|conducts|conducted|conducting|complete|completes|completed|completing|prepare|prepares|prepared|preparing|take|takes|took|taken|taking)\s+"
            r"(?:a\s+|an\s+|the\s+)?collection\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "collect",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|conduct|conducts|conducted|conducting|complete|completes|completed|completing|prepare|prepares|prepared|preparing|take|takes|took|taken|taking)\s+"
            r"collections\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "collect",
        ),
        (
            r"^(?:make|makes|made|making|prepare|prepares|prepared|preparing|complete|completes|completed|completing|provide|provides|provided|providing|submit|submits|submitted|submitting)\s+"
            r"(?:a\s+|an\s+|the\s+)?compilation\s+of\s+(?:the\s+)?(.+)$",
            "compile",
        ),
        (
            r"^(?:make|makes|made|making|prepare|prepares|prepared|preparing|complete|completes|completed|completing|provide|provides|provided|providing|submit|submits|submitted|submitting)\s+"
            r"compilations\s+of\s+(?:the\s+)?(.+)$",
            "compile",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_delivery_distribution_light_verb_action(action_text: str) -> str:
    """Collapse delivery and distribution nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|complete|completes|completed|completing|effect|effects|effected|effecting|provide|provides|provided|providing)\s+"
            r"(?:a\s+|an\s+|the\s+)?delivery\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "deliver",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|complete|completes|completed|completing|effect|effects|effected|effecting|provide|provides|provided|providing)\s+"
            r"deliveries\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "deliver",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|complete|completes|completed|completing|effect|effects|effected|effecting|provide|provides|provided|providing)\s+"
            r"(?:a\s+|an\s+|the\s+)?distribution\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "distribute",
        ),
        (
            r"^(?:make|makes|made|making|perform|performs|performed|performing|complete|completes|completed|completing|effect|effects|effected|effecting|provide|provides|provided|providing)\s+"
            r"distributions\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "distribute",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_adoption_promulgation_light_verb_action(action_text: str) -> str:
    """Collapse adoption and promulgation nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|issue|issues|issued|issuing)\s+"
            r"(?:an?\s+|the\s+)?adoption\s+of\s+(?:the\s+)?(.+)$",
            "adopt",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|issue|issues|issued|issuing)\s+"
            r"adoptions\s+of\s+(?:the\s+)?(.+)$",
            "adopt",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|issue|issues|issued|issuing|publish|publishes|published|publishing)\s+"
            r"(?:a\s+|the\s+)?promulgation\s+of\s+(?:the\s+)?(.+)$",
            "promulgate",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|issue|issues|issued|issuing|publish|publishes|published|publishing)\s+"
            r"promulgations\s+of\s+(?:the\s+)?(.+)$",
            "promulgate",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_designation_appointment_light_verb_action(action_text: str) -> str:
    """Collapse designation and appointment nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|issue|issues|issued|issuing)\s+"
            r"(?:a\s+|the\s+)?designation\s+of\s+(?:the\s+)?(.+)$",
            "designate",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|issue|issues|issued|issuing)\s+"
            r"designations\s+of\s+(?:the\s+)?(.+)$",
            "designate",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|order|orders|ordered|ordering)\s+"
            r"(?:an?\s+|the\s+)?appointment\s+of\s+(?:the\s+)?(.+)$",
            "appoint",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|order|orders|ordered|ordering)\s+"
            r"appointments\s+of\s+(?:the\s+)?(.+)$",
            "appoint",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_issuance_light_verb_action(action_text: str) -> str:
    """Collapse issuance nominalizations into operative issue acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|authorize|authorizes|authorized|authorizing)\s+"
        r"(?:an?\s+|the\s+)?issuance\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|authorize|authorizes|authorized|authorizing)\s+"
        r"issuances\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:cause|causes|caused|causing|require|requires|required|requiring|order|orders|ordered|ordering)\s+"
        r"(?:an?\s+|the\s+)?issuance\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:cause|causes|caused|causing|require|requires|required|requiring|order|orders|ordered|ordering)\s+"
        r"issuances\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"issue {match.group(1).strip()}"

    passive_match = re.match(
        r"^(?:cause|causes|caused|causing|require|requires|required|requiring|order|orders|ordered|ordering)\s+"
        r"(?:the\s+)?(.+?)\s+to\s+be\s+issued$",
        text,
        re.IGNORECASE,
    )
    if passive_match and passive_match.group(1).strip():
        return f"issue {passive_match.group(1).strip()}"

    return text


def _normalize_submission_light_verb_action(action_text: str) -> str:
    """Collapse submission and filing nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|provide|furnish|deliver|submit)\s+(?:a|an|the)\s+submission\s+of\s+(?:the\s+)?(.+)$",
            "submit",
        ),
        (
            r"^(?:make|provide|furnish|deliver|submit)\s+submission\s+of\s+(?:the\s+)?(.+)$",
            "submit",
        ),
        (
            r"^(?:make|provide|furnish|deliver|file)\s+(?:a|an|the)\s+filing\s+of\s+(?:the\s+)?(.+)$",
            "file",
        ),
        (
            r"^(?:make|provide|furnish|deliver|file)\s+filing\s+of\s+(?:the\s+)?(.+)$",
            "file",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"
    return text


def _normalize_docketing_calendaring_light_verb_action(action_text: str) -> str:
    """Collapse docketing and calendaring nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|enter|enters|entered|entering|perform|performs|performed|performing|complete|completes|completed|completing|record|records|recorded|recording)\s+"
            r"(?:a\s+|an\s+|the\s+)?docketing\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "docket",
        ),
        (
            r"^(?:make|makes|made|making|enter|enters|entered|entering|perform|performs|performed|performing|complete|completes|completed|completing|record|records|recorded|recording)\s+"
            r"docketings\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "docket",
        ),
        (
            r"^(?:make|makes|made|making|enter|enters|entered|entering|perform|performs|performed|performing|complete|completes|completed|completing|record|records|recorded|recording|schedule|schedules|scheduled|scheduling)\s+"
            r"(?:a\s+|an\s+|the\s+)?calendaring\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "calendar",
        ),
        (
            r"^(?:make|makes|made|making|enter|enters|entered|entering|perform|performs|performed|performing|complete|completes|completed|completing|record|records|recorded|recording|schedule|schedules|scheduled|scheduling)\s+"
            r"calendarings\s+(?:of|for|on)\s+(?:the\s+)?(.+)$",
            "calendar",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_certification_light_verb_action(action_text: str) -> str:
    """Collapse certification nominalizations into operative certification acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|provide|provides|provided|providing|complete|completes|completed|completing|perform|performs|performed|performing)\s+"
        r"(?:a\s+|an\s+|the\s+)?certification\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|provide|provides|provided|providing|complete|completes|completed|completing|perform|performs|performed|performing)\s+"
        r"certifications\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"certify {match.group(1).strip()}"

    return text


def _normalize_verification_light_verb_action(action_text: str) -> str:
    """Collapse verification nominalizations into operative verification acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|provide|provides|provided|providing|complete|completes|completed|completing|conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
        r"(?:a\s+|an\s+|the\s+)?verification\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|provide|provides|provided|providing|complete|completes|completed|completing|conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
        r"verifications\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"verify {match.group(1).strip()}"

    return text


def _normalize_approval_light_verb_action(action_text: str) -> str:
    """Collapse approval nominalizations into operative approval acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:grant|grants|granted|granting|give|gives|gave|given|giving|issue|issues|issued|issuing|make|makes|made|making)\s+"
        r"(?:an?\s+|the\s+)?approval\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:grant|grants|granted|granting|give|gives|gave|given|giving|issue|issues|issued|issuing|make|makes|made|making)\s+"
        r"approvals\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"approve {match.group(1).strip()}"

    return text


def _normalize_authorization_accreditation_light_verb_action(action_text: str) -> str:
    """Collapse authorization and accreditation nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:grant|grants|granted|granting|give|gives|gave|given|giving|issue|issues|issued|issuing|make|makes|made|making|provide|provides|provided|providing)\s+"
            r"(?:an?\s+|the\s+)?authorization\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "authorize",
        ),
        (
            r"^(?:grant|grants|granted|granting|give|gives|gave|given|giving|issue|issues|issued|issuing|make|makes|made|making|provide|provides|provided|providing)\s+"
            r"authorizations\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "authorize",
        ),
        (
            r"^(?:grant|grants|granted|granting|give|gives|gave|given|giving|issue|issues|issued|issuing|make|makes|made|making|provide|provides|provided|providing|approve|approves|approved|approving)\s+"
            r"(?:an?\s+|the\s+)?accreditation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
            "accredit",
        ),
        (
            r"^(?:grant|grants|granted|granting|give|gives|gave|given|giving|issue|issues|issued|issuing|make|makes|made|making|provide|provides|provided|providing|approve|approves|approved|approving)\s+"
            r"accreditations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
            "accredit",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_classification_categorization_light_verb_action(action_text: str) -> str:
    """Collapse classification and categorization nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|assign|assigns|assigned|assigning|provide|provides|provided|providing)\s+"
            r"(?:a\s+|an\s+|the\s+)?classification\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "classify",
        ),
        (
            r"^(?:make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|assign|assigns|assigned|assigning|provide|provides|provided|providing)\s+"
            r"classifications\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "classify",
        ),
        (
            r"^(?:make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|assign|assigns|assigned|assigning|provide|provides|provided|providing)\s+"
            r"(?:a\s+|an\s+|the\s+)?categorization\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "categorize",
        ),
        (
            r"^(?:make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|assign|assigns|assigned|assigning|provide|provides|provided|providing)\s+"
            r"categorizations\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
            "categorize",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_correction_adjustment_light_verb_action(action_text: str) -> str:
    """Collapse correction and adjustment nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|record|records|recorded|recording|issue|issues|issued|issuing)\s+"
            r"(?:a\s+|an\s+|the\s+)?correction\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "correct",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|record|records|recorded|recording|issue|issues|issued|issuing)\s+"
            r"corrections\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "correct",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|record|records|recorded|recording|issue|issues|issued|issuing)\s+"
            r"(?:a\s+|an\s+|the\s+)?adjustment\s+(?:of|to|for)\s+(?:the\s+)?(.+)$",
            "adjust",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|enter|enters|entered|entering|record|records|recorded|recording|issue|issues|issued|issuing)\s+"
            r"adjustments\s+(?:of|to|for)\s+(?:the\s+)?(.+)$",
            "adjust",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_transfer_conveyance_light_verb_action(action_text: str) -> str:
    """Collapse transfer and conveyance nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|record|records|recorded|recording|execute|executes|executed|executing)\s+"
            r"(?:a\s+|an\s+|the\s+)?transfer\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "transfer",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|record|records|recorded|recording|execute|executes|executed|executing)\s+"
            r"transfers\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "transfer",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|record|records|recorded|recording|execute|executes|executed|executing)\s+"
            r"(?:a\s+|an\s+|the\s+)?conveyance\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "convey",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|approve|approves|approved|approving|record|records|recorded|recording|execute|executes|executed|executing)\s+"
            r"conveyances\s+(?:of|to)\s+(?:the\s+)?(.+)$",
            "convey",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_denial_light_verb_action(action_text: str) -> str:
    """Collapse denial nominalizations into operative denial acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:issue|issues|issued|issuing|make|makes|made|making|enter|enters|entered|entering|render|renders|rendered|rendering)\s+"
        r"(?:a\s+|the\s+)?denial\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:issue|issues|issued|issuing|make|makes|made|making|enter|enters|entered|entering|render|renders|rendered|rendering)\s+"
        r"denials\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"deny {match.group(1).strip()}"

    return text


def _normalize_notice_service_light_verb_action(action_text: str) -> str:
    """Collapse notice-service light-verb phrases into operative notice acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:give|gives|gave|given|giving|provide|provides|provided|providing|furnish|furnishes|furnished|furnishing|deliver|delivers|delivered|delivering|serve|serves|served|serving)\s+"
        r"(?:a\s+|an\s+|the\s+)?notice\s+(?:of|about|regarding)\s+(.+)$",
        r"^(?:give|gives|gave|given|giving|provide|provides|provided|providing|furnish|furnishes|furnished|furnishing|deliver|delivers|delivered|delivering|serve|serves|served|serving)\s+"
        r"(?:a\s+|an\s+|the\s+)?notice\s+(?:to|upon|on)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"notice {match.group(1).strip()}"

    return text


def _normalize_publication_light_verb_action(action_text: str) -> str:
    """Collapse legal publication nominalizations into operative publish acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    nominalization_patterns = [
        r"^(?:cause|causes|caused|causing|make|makes|made|making|provide|provides|provided|providing|complete|completes|completed|completing)\s+"
        r"(?:a\s+|the\s+)?publication\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:cause|causes|caused|causing|make|makes|made|making|provide|provides|provided|providing|complete|completes|completed|completing)\s+"
        r"publications\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in nominalization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"publish {match.group(1).strip()}"

    passive_match = re.match(
        r"^(?:cause|causes|caused|causing|require|requires|required|requiring|order|orders|ordered|ordering)\s+"
        r"(?:the\s+)?(.+?)\s+to\s+be\s+published$",
        text,
        re.IGNORECASE,
    )
    if passive_match and passive_match.group(1).strip():
        return f"publish {passive_match.group(1).strip()}"

    return text


def _normalize_service_light_verb_action(action_text: str) -> str:
    """Collapse legal service nominalizations into operative service acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|perfect|perfects|perfected|perfecting)\s+"
        r"(?:a\s+|the\s+)?service\s+(?:of|on|upon|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|perfect|perfects|perfected|perfecting)\s+"
        r"service\s+(?:of|on|upon|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"serve {match.group(1).strip()}"

    return text


def _normalize_inspection_light_verb_action(action_text: str) -> str:
    """Collapse inspection light-verb phrases into the operative inspect act."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"(?:a\s+|an\s+|the\s+)?inspection\s+of\s+(.+)$",
            r"inspect \1",
        ),
        (
            r"^(?:make|makes|made|making)\s+(?:a\s+|an\s+|the\s+)?inspection\s+of\s+(.+)$",
            r"inspect \1",
        ),
        (
            r"^(?:carry|carries|carried|carrying)\s+out\s+"
            r"(?:a\s+|an\s+|the\s+)?inspection\s+of\s+(.+)$",
            r"inspect \1",
        ),
    ]
    for pattern, replacement in patterns:
        normalized = re.sub(pattern, replacement, text, flags=re.IGNORECASE).strip()
        if normalized != text:
            return normalized
    return text


def _normalize_sampling_light_verb_action(action_text: str) -> str:
    """Collapse sampling light-verb phrases into the operative sample act."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:take|takes|took|taken|taking|collect|collects|collected|collecting|obtain|obtains|obtained|obtaining)\s+"
            r"(?:a\s+|an\s+|the\s+)?sample\s+of\s+(.+)$",
            r"sample \1",
        ),
        (
            r"^(?:take|takes|took|taken|taking|collect|collects|collected|collecting|obtain|obtains|obtained|obtaining)\s+"
            r"(?:a\s+|an\s+|the\s+)?sample\s+from\s+(.+)$",
            r"sample \1",
        ),
        (
            r"^(?:take|takes|took|taken|taking|collect|collects|collected|collecting|obtain|obtains|obtained|obtaining)\s+"
            r"samples\s+(?:of|from)\s+(.+)$",
            r"sample \1",
        ),
    ]
    for pattern, replacement in patterns:
        normalized = re.sub(pattern, replacement, text, flags=re.IGNORECASE).strip()
        if normalized != text:
            return normalized
    return text


def _normalize_testing_light_verb_action(action_text: str) -> str:
    """Collapse testing light-verb phrases into the operative test act."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"testing\s+of\s+(.+)$",
            r"test \1",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|run|runs|ran|running)\s+"
            r"(?:a\s+|an\s+|the\s+)?test\s+(?:of|on)\s+(.+)$",
            r"test \1",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|run|runs|ran|running)\s+"
            r"tests\s+(?:of|on)\s+(.+)$",
            r"test \1",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"(?:an\s+|the\s+)?analysis\s+of\s+(.+)$",
            r"test \1",
        ),
    ]
    for pattern, replacement in patterns:
        normalized = re.sub(pattern, replacement, text, flags=re.IGNORECASE).strip()
        if normalized != text:
            return normalized
    return text


def _normalize_monitoring_light_verb_action(action_text: str) -> str:
    """Collapse monitoring light-verb phrases into the operative monitor act."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"monitoring\s+of\s+(.+)$",
            r"monitor \1",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing)\s+"
            r"monitoring\s+(?:on|for)\s+(.+)$",
            r"monitor \1",
        ),
        (
            r"^(?:conduct|conducts|conducted|conducting|perform|performs|performed|performing|run|runs|ran|running)\s+"
            r"(?:a\s+|an\s+|the\s+)?monitoring\s+program\s+(?:of|on|for)\s+(.+)$",
            r"monitor \1",
        ),
    ]
    for pattern, replacement in patterns:
        normalized = re.sub(pattern, replacement, text, flags=re.IGNORECASE).strip()
        if normalized != text:
            return normalized
    return text


def _normalize_payment_light_verb_action(action_text: str) -> str:
    """Collapse payment light-verb phrases into the operative payment action."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making)\s+(?:a\s+|an\s+|the\s+)?payment\s+of\s+(.+)$",
            r"pay \1",
        ),
        (
            r"^(?:make|makes|made|making)\s+(?:a\s+|an\s+|the\s+)?payment\s+for\s+(.+)$",
            r"pay for \1",
        ),
    ]
    for pattern, replacement in patterns:
        normalized = re.sub(pattern, replacement, text, flags=re.IGNORECASE).strip()
        if normalized != text:
            return normalized
    return text


def _normalize_remittance_light_verb_action(action_text: str) -> str:
    """Collapse remittance nominalizations into operative remit acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|provide|provides|provided|providing|submit|submits|submitted|submitting|deliver|delivers|delivered|delivering)\s+"
        r"(?:a\s+|an\s+|the\s+)?remittance\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|provide|provides|provided|providing|submit|submits|submitted|submitting|deliver|delivers|delivered|delivering)\s+"
        r"remittances\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"remit {match.group(1).strip()}"

    return text


def _normalize_renewal_light_verb_action(action_text: str) -> str:
    """Collapse legal renewal nominalizations into operative renewal acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"^(?:make|makes|made|making|grant|grants|granted|granting|issue|issues|issued|issuing|approve|approves|approved|approving|complete|completes|completed|completing)\s+"
        r"(?:a\s+|an\s+|the\s+)?renewal\s+of\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|grant|grants|granted|granting|issue|issues|issued|issuing|approve|approves|approved|approving|complete|completes|completed|completing)\s+"
        r"renewals\s+of\s+(?:the\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"renew {match.group(1).strip()}"

    return text


def _normalize_registration_enrollment_light_verb_action(action_text: str) -> str:
    """Collapse registration and enrollment nominalizations into operative acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|complete|completes|completed|completing|file|files|filed|filing|submit|submits|submitted|submitting|approve|approves|approved|approving)\s+"
            r"(?:a\s+|an\s+|the\s+)?registration\s+of\s+(?:the\s+)?(.+)$",
            "register",
        ),
        (
            r"^(?:make|makes|made|making|complete|completes|completed|completing|file|files|filed|filing|submit|submits|submitted|submitting|approve|approves|approved|approving)\s+"
            r"registrations\s+of\s+(?:the\s+)?(.+)$",
            "register",
        ),
        (
            r"^(?:make|makes|made|making|complete|completes|completed|completing|submit|submits|submitted|submitting|approve|approves|approved|approving|accept|accepts|accepted|accepting)\s+"
            r"(?:a\s+|an\s+|the\s+)?enrollment\s+of\s+(?:the\s+)?(.+)$",
            "enroll",
        ),
        (
            r"^(?:make|makes|made|making|complete|completes|completed|completing|submit|submits|submitted|submitting|approve|approves|approved|approving|accept|accepts|accepted|accepting)\s+"
            r"enrollments\s+of\s+(?:the\s+)?(.+)$",
            "enroll",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_instrument_status_light_verb_action(action_text: str) -> str:
    """Collapse instrument-status nominalizations into operative status acts."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|order|orders|ordered|ordering|issue|issues|issued|issuing|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"(?:a\s+|an\s+|the\s+)?revocation\s+of\s+(?:the\s+)?(.+)$",
            "revoke",
        ),
        (
            r"^(?:make|makes|made|making|order|orders|ordered|ordering|issue|issues|issued|issuing|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"revocations\s+of\s+(?:the\s+)?(.+)$",
            "revoke",
        ),
        (
            r"^(?:make|makes|made|making|order|orders|ordered|ordering|issue|issues|issued|issuing|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"(?:a\s+|an\s+|the\s+)?suspension\s+of\s+(?:the\s+)?(.+)$",
            "suspend",
        ),
        (
            r"^(?:make|makes|made|making|order|orders|ordered|ordering|issue|issues|issued|issuing|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"suspensions\s+of\s+(?:the\s+)?(.+)$",
            "suspend",
        ),
        (
            r"^(?:make|makes|made|making|order|orders|ordered|ordering|issue|issues|issued|issuing|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"(?:a\s+|an\s+|the\s+)?cancellation\s+of\s+(?:the\s+)?(.+)$",
            "cancel",
        ),
        (
            r"^(?:make|makes|made|making|order|orders|ordered|ordering|issue|issues|issued|issuing|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"cancellations\s+of\s+(?:the\s+)?(.+)$",
            "cancel",
        ),
    ]
    for pattern, verb in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return f"{verb} {match.group(1).strip()}"

    return text


def _normalize_recordkeeping_light_verb_action(action_text: str) -> str:
    """Collapse recordmaking light-verb phrases into the operative record act."""

    text = str(action_text or "").strip()
    if not text:
        return ""

    patterns = [
        (
            r"^(?:make|makes|made|making|create|creates|created|creating|prepare|prepares|prepared|preparing)\s+"
            r"(?:a\s+|an\s+|the\s+)?(?:written\s+)?record\s+of\s+(.+)$",
            r"record \1",
        ),
        (
            r"^(?:make|makes|made|making|create|creates|created|creating|prepare|prepares|prepared|preparing)\s+"
            r"(?:written\s+)?records\s+of\s+(.+)$",
            r"record \1",
        ),
    ]
    for pattern, replacement in patterns:
        normalized = re.sub(pattern, replacement, text, flags=re.IGNORECASE).strip()
        if normalized != text:
            return normalized
    return text


def _is_direct_gerund_prohibition(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether a direct prohibition action starts with a normalized legal gerund."""

    if norm.modality != "F":
        return False
    return bool(re.match(
        r"^(?:disclosing|entering|operating|using|contacting|discharging|removing|altering|destroying|obstructing|interfering|impeding)\b",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _is_refrain_obligation(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether an affirmative duty not to act is a prohibition."""

    if norm.modality != "O":
        return False
    return bool(re.match(
        r"^(?:(?:refrain|abstain|desist|forbear)\s+from|(?:cease|stop))\s+\S"
        r"|^avoid\s+(?:contacting|entering|operating|using|discharging|removing|altering|destroying|obstructing|interfering|impeding)\b",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _is_prevention_obligation(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether an affirmative prevention duty is a prohibition."""

    if norm.modality != "O":
        return False
    return bool(re.match(
        r"^(?:prevent|prohibit|bar|block)\s+(?:entry|access|discharge|disclosure|removal|alteration|destruction)\b",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _is_confidentiality_obligation(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether an affirmative confidentiality duty prohibits disclosure."""

    if norm.modality != "O":
        return False
    text = str(action_text or "").strip()
    return bool(
        re.match(
            r"^(?:keep|maintain|preserve)\s+.+?\s+confidential\b",
            text,
            re.IGNORECASE,
        )
        or re.match(r"^(?:protect|preserve|maintain)\s+(?:the\s+)?confidentiality\s+of\s+\S", text, re.IGNORECASE)
    )


def _is_compliance_obligation(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether a duty to ensure compliance embeds the operative action."""

    if norm.modality != "O":
        return False
    return bool(re.match(
        r"^(?:ensure|secure|maintain)\s+compliance\s+with\s+\S",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _is_access_availability_obligation(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether an access/availability duty embeds the proof action."""

    if norm.modality != "O":
        return False
    text = str(action_text or "").strip()
    return bool(
        re.match(
            r"^(?:make|maintain|keep)\s+.+?\s+available\s+(?:for|to)\s+\S",
            text,
            re.IGNORECASE,
        )
        or re.match(
            r"^(?:provide|grant|allow)\s+access\s+to\s+\S",
            text,
            re.IGNORECASE,
        )
    )


def _is_direct_interference_prohibition(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether a direct prohibition targets interference with a legal process."""

    if norm.modality != "F":
        return False
    return bool(re.match(
        r"^(?:interfere|interferes|obstruct|obstructs|impede|impedes)\s+(?:with\s+)?\S",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _is_permission_facilitation_prohibition(norm: LegalNormIR, action_text: str) -> bool:
    """Return whether a prohibition targets facilitating or causing a regulated act."""

    if norm.modality != "F":
        return False
    return bool(re.match(
        r"^(?:permit|allow|authorize|enable|require|compel|direct|coerce|cause|causes|result\s+in)\s+(?:any\s+|a\s+|an\s+|the\s+)?"
        r"(?:person\s+to\s+|entity\s+to\s+|applicant\s+to\s+|permittee\s+to\s+|licensee\s+to\s+)?"
        r"(?:enter|access|discharge|disclose|remove|alter|destroy|obstruct|interfere|impede|"
        r"entry|discharge|disclosure|removal|alteration|destruction|access)\b",
        str(action_text or "").strip(),
        re.IGNORECASE,
    ))


def _strip_refrain_action(action_text: str) -> str:
    """Remove a restraint wrapper and normalize a narrow gerund action head."""

    embedded = re.sub(
        r"^(?:(?:refrain|abstain|desist|forbear)\s+from|(?:cease|stop)|avoid)\s+",
        "",
        str(action_text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()
    return _normalize_refrain_action_head(embedded)


def _strip_prevention_action(action_text: str) -> str:
    """Remove a prevention wrapper from narrow legally salient actions."""

    embedded = re.sub(
        r"^(?:prevent|prohibit|bar|block)\s+",
        "",
        str(action_text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()
    return _normalize_prevention_action_head(embedded)


def _strip_confidentiality_action(action_text: str) -> str:
    """Normalize confidentiality-duty wrappers into disclosure prohibitions."""

    text = str(action_text or "").strip()
    direct_match = re.match(
        r"^(?:keep|maintain|preserve)\s+(.+?)\s+confidential\b",
        text,
        re.IGNORECASE,
    )
    if direct_match:
        protected_object = direct_match.group(1).strip()
        return f"disclose {protected_object}" if protected_object else text

    confidentiality_match = re.match(
        r"^(?:protect|preserve|maintain)\s+(?:the\s+)?confidentiality\s+of\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if confidentiality_match:
        protected_object = confidentiality_match.group(1).strip()
        return f"disclose {protected_object}" if protected_object else text

    return text


def _strip_compliance_action(action_text: str) -> str:
    """Normalize compliance-duty wrappers into the embedded compliance act."""

    embedded = re.sub(
        r"^(?:ensure|secure|maintain)\s+compliance\s+with\s+",
        "comply with ",
        str(action_text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()
    return embedded


def _strip_access_availability_action(action_text: str) -> str:
    """Normalize availability/access duty wrappers into provide/access actions."""

    text = str(action_text or "").strip()
    availability_match = re.match(
        r"^(?:make|maintain|keep)\s+(.+?)\s+available\s+(for|to)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if availability_match:
        provided_object = availability_match.group(1).strip()
        relation = availability_match.group(2).strip().lower()
        target = availability_match.group(3).strip()
        if provided_object and target:
            return f"provide {provided_object} {relation} {target}"

    access_match = re.match(
        r"^(provide|grant|allow)\s+access\s+to\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if access_match:
        accessed_object = access_match.group(2).strip()
        return f"provide access to {accessed_object}" if accessed_object else text

    return text


def _strip_direct_interference_action(action_text: str) -> str:
    """Normalize direct interference prohibitions without changing the legal object."""

    text = str(action_text or "").strip()
    match = re.match(
        r"^(interfere|interferes|obstruct|obstructs|impede|impedes)\s+(?:with\s+)?(.+)$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    verb = match.group(1).lower().rstrip("s")
    return f"{verb} {match.group(2).strip()}"


def _strip_permission_facilitation_action(action_text: str) -> str:
    """Remove facilitation or causation wrappers from prohibited acts."""

    text = str(action_text or "").strip()
    agent_action_match = re.match(
        r"^(?:permit|allow|authorize|enable|require|compel|direct|coerce|cause|causes)\s+"
        r"(?:any\s+|a\s+|an\s+|the\s+)?"
        r"(?:person|entity|applicant|permittee|licensee)\s+to\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if agent_action_match:
        return _normalize_prevention_action_head(agent_action_match.group(1).strip())

    embedded = re.sub(
        r"^(?:permit|allow|authorize|enable|require|compel|direct|coerce|cause|causes|result\s+in)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if embedded:
        return _normalize_prevention_action_head(embedded)
    return text


def _action_without_structured_recipient_tail(norm: LegalNormIR, action_text: str) -> str:
    """Remove a structured recipient tail from object-bearing transfer duties.

    The deontic formula exporter currently uses unary consequents, so a clause
    like ``shall send notice to the applicant`` should export the operative act
    ``SendNotice(x)`` and preserve ``applicant`` as recipient provenance in the
    formula record. This helper only acts when the IR already has both an
    ``action_object`` and a recipient slot; recipient-only actions such as
    ``notify the applicant`` remain unchanged.
    """

    text = str(action_text or "").strip()
    recipient = str(norm.recipient or "").strip()
    action_object = str(norm.action_object or "").strip()
    if not text or not recipient or not action_object:
        return text

    if re.match(r"^(?:provide|grant|allow)\s+access\s+to\s+\S", text, re.IGNORECASE):
        return text

    first_word_match = re.match(r"^([A-Za-z][A-Za-z0-9'’\-]*)\b", text)
    first_word = first_word_match.group(1).lower() if first_word_match else ""
    transfer_verbs = {
        "deliver",
        "email",
        "file",
        "furnish",
        "mail",
        "provide",
        "post",
        "record",
        "register",
        "send",
        "serve",
        "submit",
        "transmit",
    }
    if first_word not in transfer_verbs:
        return text

    tail_match = re.search(r"\s+(?:to|for|with|on|upon)\s+(.+)$", text, re.IGNORECASE)
    if not tail_match:
        return text

    tail = tail_match.group(1).strip()
    if not _same_formula_slot_text(tail, recipient):
        return text

    head = text[: tail_match.start()].strip()
    if not head:
        return text
    if not _formula_text_contains_slot(head, action_object):
        return text
    return head


def _action_without_structured_notice_recipient(norm: LegalNormIR, action_text: str) -> str:
    """Remove structured recipients from object-bearing notice duties.

    A clause like ``shall notify the applicant of the decision`` carries both a
    recipient and a legal object. The current unary consequent should represent
    the operative notice object as ``NotifyDecision(x)`` while the recipient is
    preserved as omitted provenance. Recipient-only clauses such as ``shall
    notify the applicant`` stay unchanged because no object slot grounds a more
    specific formula.
    """

    text = str(action_text or "").strip()
    recipient = str(norm.recipient or "").strip()
    action_object = str(norm.action_object or "").strip()
    if not text or not recipient or not action_object:
        return text

    notice_match = re.match(
        r"^(notify|inform|advise|alert)\s+(.+?)\s+(?:of|about|regarding)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if not notice_match:
        return text

    verb = notice_match.group(1).strip()
    recipient_phrase = notice_match.group(2).strip()
    object_phrase = notice_match.group(3).strip()
    if not recipient_phrase or not object_phrase:
        return text
    if not _same_formula_slot_text(recipient_phrase, recipient):
        return text
    if not _formula_text_contains_slot(object_phrase, action_object):
        return text

    return f"{verb} {object_phrase}"


def _action_without_temporal_duration_tail(norm: LegalNormIR, action_text: str) -> str:
    """Remove a duration tail already represented in temporal IR slots.

    Record-retention clauses often parse as actions such as ``retain records for
    three years`` while also carrying a structured temporal duration. The unary
    consequent should remain the operative act, and the duration should appear
    as a temporal antecedent rather than being baked into the action predicate.
    """

    text = str(action_text or "").strip()
    if not text or not norm.temporal_constraints:
        return text

    tail_match = re.search(r"\s+for\s+(.+)$", text, re.IGNORECASE)
    if not tail_match:
        return text

    tail = tail_match.group(1).strip()
    if not tail:
        return text

    duration_values = _temporal_duration_slot_values(norm.temporal_constraints)
    if not any(_same_formula_slot_text(tail, duration) for duration in duration_values):
        return text

    head = text[: tail_match.start()].strip()
    return head or text


def _temporal_duration_slot_values(items: Iterable[Dict[str, Any]]) -> List[str]:
    """Return duration strings explicitly carried by temporal constraint slots."""

    values: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for value in (
            item.get("duration"),
            item.get("deadline"),
            item.get("value"),
            item.get("normalized_text"),
            item.get("raw_text"),
        ):
            text = str(value or "").strip()
            if text:
                values.append(text)
    return values


def _same_formula_slot_text(left: str, right: str) -> bool:
    return _formula_slot_key(left) == _formula_slot_key(right)


def _formula_text_contains_slot(text: str, slot: str) -> bool:
    slot_key = _formula_slot_key(slot)
    return bool(slot_key and slot_key in _formula_slot_key(text))


def _formula_slot_key(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(text or "").lower())
    return " ".join(word for word in words if word not in {"the", "a", "an"})


def _normalize_refrain_action_head(action_text: str) -> str:
    """Convert common legal gerund heads after `refrain from` to base form."""

    parts = str(action_text or "").strip().split(maxsplit=1)
    if not parts:
        return ""
    verb = parts[0].lower()
    legal_gerunds = {
        "disclosing": "disclose",
        "entering": "enter",
        "operating": "operate",
        "using": "use",
        "contacting": "contact",
        "discharging": "discharge",
        "removing": "remove",
        "altering": "alter",
        "destroying": "destroy",
        "obstructing": "obstruct",
        "interfering": "interfere",
        "impeding": "impede",
    }
    if verb in legal_gerunds:
        parts[0] = legal_gerunds[verb]
    return " ".join(parts)


def _normalize_prevention_action_head(action_text: str) -> str:
    """Convert nominal prevention objects into proof-friendly action heads."""

    parts = str(action_text or "").strip().split(maxsplit=1)
    if not parts:
        return ""
    noun = parts[0].lower()
    legal_actions = {
        "entry": "enter",
        "access": "access",
        "discharge": "discharge",
        "disclosure": "disclose",
        "removal": "remove",
        "alteration": "alter",
        "destruction": "destroy",
    }
    if noun in legal_actions:
        parts[0] = legal_actions[noun]
    return " ".join(parts)


def build_deontic_formula_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a source-grounded formula export record from typed IR.

    This record API is intentionally richer than the legacy string formula API:
    downstream proof, metrics, and export code can inspect provenance and
    deterministic blockers without reparsing natural-language source text.
    """

    formula = build_deontic_formula_from_ir(norm)
    parser_warnings = list(norm.quality.parser_warnings)
    blockers = list(norm.blockers)
    omitted_slots = _omitted_formula_slots(norm)
    deterministic_resolution = _deterministic_formula_resolution(norm, blockers)
    if not deterministic_resolution:
        deterministic_resolution = _batch_resolved_reference_exception_formula_resolution(norm, blockers)
    deterministic_resolution = _normalize_formula_resolution(deterministic_resolution)
    proof_ready = norm.proof_ready or bool(deterministic_resolution)
    requires_validation = not proof_ready
    repair_required = requires_validation

    return {
        "formula_id": _stable_formula_id(norm.source_id, formula),
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "parent_source_id": norm.parent_source_id,
        "enumeration_label": norm.enumeration_label,
        "enumeration_index": norm.enumeration_index,
        "is_enumerated_child": norm.is_enumerated_child,
        "target_logic": _target_logic_for_norm(norm),
        "formula": formula,
        "modality": norm.modality,
        "norm_type": norm.norm_type,
        "support_span": norm.support_span.to_list(),
        "field_spans": dict(norm.field_spans),
        "proof_ready": proof_ready,
        "requires_validation": requires_validation,
        "repair_required": repair_required,
        "blockers": blockers,
        "parser_warnings": parser_warnings,
        "omitted_formula_slots": omitted_slots,
        "deterministic_resolution": deterministic_resolution,
        "schema_version": norm.schema_version,
    }


def build_deontic_formula_records_from_irs(norms: Iterable[LegalNormIR]) -> List[Dict[str, Any]]:
    """Build ordered formula export records for already parsed legal norms.

    This is the multi-norm companion to ``build_deontic_formula_record_from_ir``;
    callers such as ``DeonticConverter`` can expose every expanded child norm
    without reparsing source text or changing legacy first-formula behavior.
    """

    resolved_norms = _with_same_document_reference_resolutions(list(norms))
    return [build_deontic_formula_record_from_ir(norm) for norm in resolved_norms]


def build_prover_syntax_records_from_ir(
    norm: LegalNormIR,
    targets: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build syntax-validation records for local prover target renderings."""

    from .prover_syntax import validate_ir_with_provers

    return [target.to_dict() for target in validate_ir_with_provers(norm, targets).targets]


def _formula_action_text(norm: LegalNormIR) -> str:
    action = str(norm.action or "").strip()
    if action:
        return action

    verb = str(norm.action_verb or "").strip()
    action_object = str(norm.action_object or "").strip()
    if verb and action_object:
        lowered_object = action_object.lower()
        if lowered_object.startswith(verb.lower() + " "):
            return action_object
        return f"{verb} {action_object}"
    if verb:
        recipient = str(norm.recipient or "").strip()
        if recipient:
            return f"{verb} {recipient}"
        return verb
    if action_object:
        return action_object
    return "Action"


def _supplemental_procedure_predicates(
    procedure: Mapping[str, Any],
    existing_predicates: Sequence[str],
) -> List[str]:
    """Return procedure predicates for source-grounded notice delivery triggers.

    The primary procedure mapper covers most common trigger relations. This
    supplement keeps the Phase 8 formula path deterministic for additional
    notice-delivery relations already emitted by parser/export IR records,
    without strengthening ordering-only relations or reparsing source text.
    """

    if not isinstance(procedure, Mapping):
        return []

    seen = set(existing_predicates)
    predicates: List[str] = []
    for relation in procedure.get("event_relations") or []:
        if not isinstance(relation, Mapping):
            continue

        relation_type = str(relation.get("relation") or "").strip()
        prefix = _SUPPLEMENTAL_PROCEDURE_TRIGGER_PREFIXES.get(relation_type)
        if not prefix:
            continue

        anchor_event = str(relation.get("anchor_event") or "").strip()
        if not anchor_event:
            continue

        predicate = normalize_predicate_name(f"procedure {prefix} {anchor_event}")
        if predicate not in seen:
            predicates.append(predicate)
            seen.add(predicate)
    return predicates


def parser_element_to_formula_record(element: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility helper for callers that still hold parser dictionaries."""

    return build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(element))


def _with_same_document_reference_resolutions(norms: List[LegalNormIR]) -> List[LegalNormIR]:
    """Resolve exact numbered section references against the same IR batch.

    Single-record formula building stays conservative. Batch callers such as
    converter metadata have document context, so they can clear a reference-only
    exception or condition when the cited section is actually present in the
    same parsed batch. The cited section remains provenance only and is not
    emitted as a factual predicate in the formula antecedent.
    """

    section_index = _same_document_section_index(norms)
    if not section_index:
        return norms
    section_context_citations = _same_document_section_context_citations(norms)
    return [
        _resolve_norm_same_document_references(norm, section_index, section_context_citations)
        for norm in norms
    ]


def _same_document_section_index(norms: Sequence[LegalNormIR]) -> Dict[str, str]:
    section_index: Dict[str, str] = {}
    for norm in norms:
        citation = _canonical_section_citation(norm.canonical_citation)
        if citation and norm.source_id:
            section_index.setdefault(citation, norm.source_id)
        for citation in _section_context_citations(norm):
            if citation and norm.source_id:
                section_index.setdefault(citation, norm.source_id)
    return section_index


def _same_document_section_context_citations(norms: Sequence[LegalNormIR]) -> set[str]:
    citations: set[str] = set()
    for norm in norms:
        citations.update(_section_context_citations(norm))
    return citations


def _resolve_norm_same_document_references(
    norm: LegalNormIR,
    section_index: Mapping[str, str],
    section_context_citations: set[str],
) -> LegalNormIR:
    additions: List[Dict[str, Any]] = []
    existing = {
        _canonical_section_citation(str(item.get("canonical_citation") or item.get("value") or ""))
        for item in norm.resolved_cross_references
        if isinstance(item, dict)
    }

    for reference in norm.cross_references:
        if not isinstance(reference, dict) or _reference_is_external(reference):
            continue

        citations = _reference_section_citations(reference)
        if not citations or any(citation not in section_index for citation in citations):
            continue

        for citation in citations:
            if citation in existing:
                continue
            additions.append({
                "reference_type": "section",
                "target": citation[len("section ") :],
                "canonical_citation": citation,
                "value": citation,
                "resolution_scope": "same_document",
                "same_document": True,
                "resolved_source_id": section_index[citation],
                "source_id": section_index[citation],
                "matched_section_context": citation in section_context_citations,
                "span": reference.get("span", []),
            }
            )
            existing.add(citation)

    if not additions:
        return norm
    return replace(norm, resolved_cross_references=list(norm.resolved_cross_references) + additions)


def _reference_section_citation(reference: Mapping[str, Any]) -> str:
    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        citation = _canonical_section_citation(str(reference.get(key) or ""))
        if citation:
            return citation

    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    target = str(reference.get("target") or reference.get("section") or "").strip()
    if reference_type == "section" and target and target.lower() not in {"this", "current"}:
        return _canonical_section_citation(f"section {target}")
    return ""


def _reference_section_citations(reference: Mapping[str, Any]) -> List[str]:
    citations: List[str] = []
    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        for citation in _section_citations_from_text(str(reference.get(key) or "")):
            if citation not in citations:
                citations.append(citation)
    single = _reference_section_citation(reference)
    if single and single not in citations:
        citations.append(single)
    return citations


def _canonical_section_citation(text: str) -> str:
    match = _LEGAL_REFERENCE_TEXT_RE.search(str(text or ""))
    if not match:
        return ""
    raw = match.group(0).strip().lower()
    if raw.startswith("§"):
        return f"section {match.group(1).lower()}"
    return raw


def _section_citations_from_text(text: str) -> List[str]:
    source = str(text or "")
    citations: List[str] = []
    for match in _LEGAL_REFERENCE_LIST_TEXT_RE.finditer(source):
        for part in re.split(r"\s*(?:,|and|or)\s*", match.group(1)):
            token = part.strip().lower()
            if token:
                citations.append(f"section {token}")
    for match in _LEGAL_REFERENCE_TEXT_RE.finditer(source):
        citation = f"section {match.group(1).lower()}"
        if citation not in citations:
            citations.append(citation)
    return citations


def _section_context_citations(norm: LegalNormIR) -> List[str]:
    """Return exact numbered section citations carried by parser context.

    Some parser batches preserve the current section only in ``section_context``
    rather than on ``canonical_citation``. Treat that source-grounded context as
    same-document evidence for exact numbered section references, while still
    rejecting empty, local-self, and non-numbered values.
    """

    context = norm.section_context
    if not isinstance(context, dict):
        return []

    citations: List[str] = []
    for key in (
        "canonical_citation",
        "citation",
        "section_citation",
        "current_section_citation",
    ):
        citation = _canonical_section_citation(str(context.get(key) or ""))
        if citation and citation not in citations:
            citations.append(citation)

    for key in ("section", "section_number", "current_section", "current_section_number"):
        value = str(context.get(key) or "").strip()
        if not value or value.lower() in {"this", "current"}:
            continue
        citation = _canonical_section_citation(f"section {value}")
        if citation and citation not in citations:
            citations.append(citation)

    return citations


def _reference_is_external(reference: Mapping[str, Any]) -> bool:
    for key in ("resolution_scope", "document_scope", "source_scope", "scope"):
        value = str(reference.get(key) or "").strip().lower().replace("-", "_")
        if value in {"external", "external_document", "other_document"}:
            return True
    return False


def _stable_formula_id(source_id: str, formula: str) -> str:
    seed = f"{source_id}|{formula}"
    import hashlib

    return "formula:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _target_logic_for_norm(norm: LegalNormIR) -> str:
    if norm.modality in {"APP", "EXEMPT", "LIFE"} or norm.norm_type in {
        "applicability",
        "exemption",
        "instrument_lifecycle",
    }:
        return "frame_logic"
    return "deontic"


def parser_element_to_formula(element: Dict[str, Any]) -> str:
    """Compatibility helper for callers that still hold parser dictionaries."""

    return build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))


def normalize_predicate_name(name: str) -> str:
    """Normalize a legal phrase to a stable predicate or symbol name."""

    if not name:
        return "P"
    name = re.sub(r"[_\-]+", " ", str(name))
    name = re.sub(r"[^0-9A-Za-z\s]", "", name)
    words = name.strip().split()
    protected_word_indices = set()
    if (
        len(words) >= 2
        and words[0].lower() in {"apply", "applies", "applied", "applying"}
        and words[1].lower() == "for"
    ):
        protected_word_indices.add(1)
    stop_words = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "by"}
    filtered_words = [
        word
        for index, word in enumerate(words)
        if index in protected_word_indices or word.lower() not in stop_words
    ]
    if not filtered_words:
        return "P"
    return "".join(word.capitalize() for word in filtered_words)


def _slot_texts(items: Iterable[Dict[str, Any]]) -> List[str]:
    texts: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = _slot_primary_text(item)
        if value:
            texts.append(str(value))
    return texts


def _unique_predicates(texts: Iterable[str]) -> List[str]:
    """Return stable predicate names while suppressing duplicate slot aliases."""

    predicates: List[str] = []
    seen = set()
    for text in texts:
        predicate = normalize_predicate_name(text)
        if not predicate or predicate == "P" or predicate in seen:
            continue
        predicates.append(predicate)
        seen.add(predicate)
    return predicates


def _unique_antecedent_predicates(predicates: Iterable[str]) -> List[str]:
    """Return formula antecedents without duplicate structured slot aliases."""

    unique: List[str] = []
    seen = set()
    for predicate in predicates:
        if not predicate or predicate == "P" or predicate in seen:
            continue
        unique.append(predicate)
        seen.add(predicate)
    return unique


def _subject_predicate_expr(norm: LegalNormIR) -> str:
    """Return the antecedent subject expression for one or more actors."""

    actor_texts = list(getattr(norm, "actor_entities", []) or [])
    if not actor_texts:
        actor_texts = [norm.actor or "Agent"]

    predicates = _unique_predicates(actor_texts)
    if not predicates:
        predicates = [normalize_predicate_name(norm.actor or "Agent")]
    if len(predicates) == 1:
        return f"{predicates[0]}(x)"
    return "(" + " ∨ ".join(f"{predicate}(x)" for predicate in predicates) + ")"


def _formula_temporal_predicates(items: Iterable[Dict[str, Any]]) -> List[str]:
    """Return temporal predicates with composite deadline aliases preferred."""

    predicates: List[str] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        predicate = normalize_predicate_name(_temporal_predicate_text(item))
        if not predicate or predicate == "P" or predicate in seen:
            continue
        predicates.append(predicate)
        seen.add(predicate)
    return _suppress_subsumed_whichever_deadlines(predicates)[:3]


def _formula_procedure_predicates(procedure: Dict[str, Any]) -> List[str]:
    """Return formula predicates from structured procedure relations.

    Procedure extraction already records source-grounded event ordering such as
    ``Upon receipt of an application`` as a ``triggered_by_receipt_of`` relation.
    Preserve that prerequisite in the formula antecedent without reparsing raw
    legal text or treating every procedure event as a factual condition.
    """

    if not isinstance(procedure, dict):
        return []

    predicates: List[str] = []
    seen = set()
    for relation in procedure.get("event_relations") or []:
        if not isinstance(relation, dict):
            continue
        prefix = _procedure_trigger_formula_prefix(str(relation.get("relation") or ""))
        if not prefix:
            continue

        anchor_event = str(
            relation.get("anchor_event") or procedure.get("trigger_event") or ""
        ).strip()
        if not anchor_event:
            continue

        predicate = normalize_predicate_name(f"{prefix} {anchor_event}")
        if predicate and predicate != "P" and predicate not in seen:
            predicates.append(predicate)
            seen.add(predicate)

    return predicates[:3]


def _procedure_trigger_formula_prefix(relation: str) -> str:
    """Return a formula-safe prefix for explicit procedural trigger relations."""

    return {
        "triggered_by_receipt_of": "procedure upon receipt",
        "triggered_by_filing_of": "procedure upon filing",
        "triggered_by_electronic_filing_of": "procedure after electronic filing",
        "triggered_by_submission_of": "procedure upon submission",
        "triggered_by_notice_and_hearing": "procedure after",
        "triggered_by_approval_of": "procedure upon approval",
        "triggered_by_completion_of": "procedure after completion",
        "triggered_by_effective_date_of": "procedure upon effective date",
        "triggered_by_certification_of": "procedure upon certification",
        "triggered_by_issuance_of": "procedure after issuance",
        "triggered_by_publication_of": "procedure after publication",
        "triggered_by_inspection_of": "procedure after inspection",
        "triggered_by_service_of": "procedure after service",
        "triggered_by_signature_of": "procedure after signature",
        "triggered_by_adoption_of": "procedure after adoption",
        "triggered_by_commencement_of": "procedure after commencement",
        "triggered_by_execution_of": "procedure after execution",
        "triggered_by_recording_of": "procedure after recording",
        "triggered_by_renewal_of": "procedure after renewal",
        "triggered_by_registration_of": "procedure after registration",
        "triggered_by_enrollment_of": "procedure after enrollment",
        "triggered_by_acceptance_of": "procedure after acceptance",
        "triggered_by_acknowledgment_of": "procedure after acknowledgment",
        "triggered_by_expiration_of": "procedure after expiration",
        "triggered_by_termination_of": "procedure after termination",
        "triggered_by_revocation_of": "procedure after revocation",
        "triggered_by_denial_of": "procedure after denial",
        "triggered_by_payment_of": "procedure after payment",
        "triggered_by_assessment_of": "procedure after assessment",
        "triggered_by_determination_of": "procedure after determination",
        "triggered_by_verification_of": "procedure after verification",
        "triggered_by_validation_of": "procedure after validation",
        "triggered_by_review_of": "procedure after review",
        "triggered_by_reconsideration_of": "procedure after reconsideration",
        "triggered_by_hearing_of": "procedure after hearing",
        "triggered_by_public_comment_on": "procedure after public comment",
        "triggered_by_consultation_with": "procedure after consultation",
        "triggered_by_final_decision_of": "procedure after final decision",
        "triggered_by_mailing_of": "procedure after mailing",
        "triggered_by_certified_mailing_of": "procedure after certified mailing",
        "triggered_by_delivery_of": "procedure after delivery",
        "triggered_by_electronic_service_on": "procedure after electronic service",
        "triggered_by_postmark_of": "procedure after postmark",
        "triggered_by_docketing_of": "procedure after docketing",
        "triggered_by_entry_of": "procedure after entry",
        "triggered_by_opening_of": "procedure after opening",
        "triggered_by_return_of": "procedure after return",
    }.get(relation, "")


def _action_without_procedure_trigger_tail(action: str, procedure: Dict[str, Any]) -> str:
    """Remove structured procedural trigger phrases from the action predicate.

    Approval-trigger clauses can arrive from parser or metric fixtures with the
    operative action slot carrying the already-structured prerequisite, e.g.
    ``issue permit upon approval application``. The trigger belongs in the
    antecedent from ``procedure.event_relations``; keeping it in the action
    predicate fabricates ``IssuePermitUponApprovalApplication``.
    """

    text = str(action or "").strip()
    if not text or not isinstance(procedure, dict):
        return text

    trigger_relations = {
        "triggered_by_receipt_of",
        "triggered_by_filing_of",
        "triggered_by_electronic_filing_of",
        "triggered_by_submission_of",
        "triggered_by_notice_and_hearing",
        "triggered_by_approval_of",
        "triggered_by_completion_of",
        "triggered_by_effective_date_of",
        "triggered_by_certification_of",
        "triggered_by_issuance_of",
        "triggered_by_publication_of",
        "triggered_by_inspection_of",
        "triggered_by_service_of",
        "triggered_by_adoption_of",
        "triggered_by_commencement_of",
        "triggered_by_execution_of",
        "triggered_by_recording_of",
        "triggered_by_renewal_of",
        "triggered_by_registration_of",
        "triggered_by_enrollment_of",
        "triggered_by_acceptance_of",
        "triggered_by_acknowledgment_of",
        "triggered_by_expiration_of",
        "triggered_by_termination_of",
        "triggered_by_revocation_of",
        "triggered_by_denial_of",
        "triggered_by_payment_of",
        "triggered_by_assessment_of",
        "triggered_by_determination_of",
        "triggered_by_verification_of",
        "triggered_by_validation_of",
        "triggered_by_review_of",
        "triggered_by_reconsideration_of",
        "triggered_by_hearing_of",
        "triggered_by_public_comment_on",
        "triggered_by_consultation_with",
        "triggered_by_final_decision_of",
        "triggered_by_mailing_of",
        "triggered_by_certified_mailing_of",
        "triggered_by_delivery_of",
        "triggered_by_electronic_service_on",
        "triggered_by_transmission_of",
        "triggered_by_receipt_confirmation_of",
        "triggered_by_posting_of",
        "triggered_by_postmark_of",
        "triggered_by_docketing_of",
        "triggered_by_entry_of",
        "triggered_by_signature_of",
        "triggered_by_notarization_of",
        "triggered_by_countersignature_of",
        "triggered_by_opening_of",
        "triggered_by_return_of",
        "triggered_by_reinstatement_of",
        "triggered_by_withdrawal_of",
        "triggered_by_archiving_of",
        "triggered_by_retention_of",
    }
    cleaned = text
    for relation in procedure.get("event_relations") or []:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("relation") or "").strip()
        if relation_type not in trigger_relations:
            continue

        raw_text = str(relation.get("raw_text") or "").strip()
        if raw_text:
            cleaned = _strip_action_tail_phrase(cleaned, raw_text)

        supplemental_prefix = _SUPPLEMENTAL_PROCEDURE_TRIGGER_PREFIXES.get(relation_type, "")
        anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
        if supplemental_prefix and anchor:
            trigger_phrase = re.sub(
                r"^(?:after|upon)\s+", "", supplemental_prefix, flags=re.IGNORECASE
            ).strip()
            cleaned = _strip_action_tail_trigger_segment(cleaned, trigger_phrase, anchor)

        if relation_type in {"triggered_by_archiving_of", "triggered_by_retention_of"}:
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            trigger_word = {
                "triggered_by_archiving_of": "archiving",
                "triggered_by_retention_of": "retention",
            }[relation_type]
            if anchor:
                cleaned = _strip_action_tail_trigger_segment(cleaned, trigger_word, anchor)

        if relation_type == "triggered_by_approval_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(rf"\s+(?:upon|after)\s+approval\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$", "", cleaned, flags=re.IGNORECASE).strip()
        if relation_type == "triggered_by_completion_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+completion\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_effective_date_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|on|after)\s+(?:the\s+)?effective\s+date\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_certification_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+certification\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_issuance_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+issuance\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_publication_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+publication\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_inspection_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+inspection\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_service_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+service\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_adoption_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+adoption\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_commencement_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+commencement\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_execution_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+execution\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_recording_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+recording\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_renewal_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+renewal\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_expiration_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+expiration\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_termination_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+termination\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_revocation_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+revocation\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_denial_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+denial\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_payment_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+payment\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        if relation_type == "triggered_by_assessment_of":
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+assessment\s+(?:of\s+)?(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
        tail_noun = _procedure_trigger_tail_noun(relation_type)
        if tail_noun:
            anchor = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:and\s+)?(?:upon|after|following)\s+{tail_noun}\s+(?:of|on)?\s*(?:an?\s+|the\s+)?{re.escape(anchor)}\b",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
                cleaned = re.sub(r"\s+and\s*$", "", cleaned, flags=re.IGNORECASE).strip()
                cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            if anchor:
                cleaned = re.sub(
                    rf"\s+(?:upon|after|following)\s+{tail_noun}\s+(?:of|on)?\s*(?:an?\s+|the\s+)?{re.escape(anchor)}\s*$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
    return cleaned or text


def _procedure_trigger_tail_noun(relation_type: str) -> str:
    """Return trigger nouns that can appear as structured action tails."""

    return {
        "triggered_by_determination_of": "determination",
        "triggered_by_electronic_filing_of": "electronic\\s+filing",
        "triggered_by_electronic_service_on": "electronic\\s+service",
        "triggered_by_public_comment_on": "public\\s+comment",
        "triggered_by_consultation_with": "consultation",
        "triggered_by_verification_of": "verification",
        "triggered_by_validation_of": "validation",
        "triggered_by_review_of": "review",
        "triggered_by_reconsideration_of": "reconsideration",
        "triggered_by_hearing_of": "hearing",
        "triggered_by_final_decision_of": "final\\s+decision",
        "triggered_by_mailing_of": "mailing",
        "triggered_by_certified_mailing_of": "certified\\s+mailing",
        "triggered_by_delivery_of": "delivery",
        "triggered_by_postmark_of": "postmark",
        "triggered_by_docketing_of": "docketing",
        "triggered_by_entry_of": "entry",
        "triggered_by_signature_of": "signature",
        "triggered_by_opening_of": "opening",
        "triggered_by_return_of": "return",
        "triggered_by_registration_of": "registration",
        "triggered_by_enrollment_of": "enrollment",
        "triggered_by_acceptance_of": "acceptance",
        "triggered_by_acknowledgment_of": "acknowledgment",
    }.get(relation_type, "")


def _strip_action_tail_phrase(action: str, phrase: str) -> str:
    words = [re.escape(word) for word in re.findall(r"[0-9A-Za-z]+", phrase or "")]
    if not words:
        return action
    pattern = r"\s+" + r"\s+(?:of\s+)?(?:an?\s+|the\s+)?".join(words) + r"\s*$"
    return re.sub(pattern, "", action, flags=re.IGNORECASE).strip()


def _strip_action_tail_trigger_segment(action: str, trigger_word: str, anchor: str) -> str:
    """Remove one structured trigger segment from a compressed action tail.

    Some metric fixtures carry already-structured procedure prerequisites in a
    compact action slot, for example ``destroy the record after archiving file
    and after retention index``.  The relation belongs in the antecedent, so the
    consequent must remove each coordinated trigger segment without relying on
    raw source-text wording such as ``of the``.
    """

    text = str(action or "").strip()
    anchor_words = [re.escape(word) for word in re.findall(r"[A-Za-z0-9]+", anchor or "")]
    if not text or not trigger_word or not anchor_words:
        return text

    anchor_pattern = r"\s+(?:of\s+)?(?:an?\s+|the\s+)?".join(anchor_words)
    pattern = (
        rf"\s+(?:and\s+)?(?:upon|after|following)\s+{re.escape(trigger_word)}"
        rf"\s+(?:of\s+)?(?:an?\s+|the\s+)?{anchor_pattern}(?:\s+and\b)?"
    )
    cleaned = re.sub(pattern, " ", text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+and\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    return re.sub(r"\s{2,}", " ", cleaned)


def _suppress_subsumed_whichever_deadlines(predicates: List[str]) -> List[str]:
    """Drop a base deadline when a whichever variant contains it.

    Parser temporal extraction can legitimately preserve both the base phrase
    and the source-grounded disambiguating phrase for provenance, for example
    ``30 days after application or 10 days after inspection`` plus
    ``... whichever is later``. The formula antecedent should use the narrower
    composite predicate only; emitting both makes the proof condition stronger
    than the source text.
    """

    suffixes = ("WhicheverIsEarlier", "WhicheverIsLater")
    composites = [
        predicate for predicate in predicates if predicate.endswith(suffixes)
    ]
    composite_bases = {
        re.sub(r"WhicheverIs(?:Earlier|Later)$", "", composite)
        for composite in composites
    }
    return [
        predicate
        for predicate in predicates
        if predicate in composites
        or not any(
            base
            and (
                predicate == base
                or base.startswith(predicate)
                or predicate.startswith(base)
            )
            for base in composite_bases
        )
    ]


def _formula_exception_texts(norm: LegalNormIR) -> List[str]:
    """Return exception phrases that are substantive formula antecedents.

    Exceptions that only restate an unresolved legal cross reference, such as
    ``except as provided in section 552``, are provenance and proof blockers.
    They should not become factual predicates like ``¬AsProvidedSection552(x)``.
    """

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references)
        + _slot_texts(norm.resolved_cross_references)
        + _slot_texts(norm.overrides)
        if str(value).strip()
    }

    texts: List[str] = []
    for item in norm.exceptions:
        if not isinstance(item, dict):
            continue
        value = _slot_primary_text(item)
        if not value:
            continue
        text = str(value).strip()
        if not text or _is_reference_exception(item, text, reference_values):
            continue
        texts.append(text)
    return texts


def _formula_condition_texts(norm: LegalNormIR) -> List[str]:
    """Return condition phrases that are substantive formula antecedents.

    Conditions that only restate an unresolved legal cross reference, such as
    ``subject to section 552``, are provenance and proof blockers. They should
    remain in IR/export metadata but should not become factual predicates like
    ``Section552(x)`` in theorem scaffolds.
    """

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references)
        + _slot_texts(norm.resolved_cross_references)
        + _slot_texts(norm.overrides)
        if str(value).strip()
    }

    texts: List[str] = []
    for item in norm.conditions:
        if not isinstance(item, dict):
            continue
        value = _slot_primary_text(item)
        if not value:
            continue
        text = str(value).strip()
        if not text or _is_reference_condition(item, text, reference_values):
            continue
        texts.append(text)
    return texts


def _omitted_formula_slots(norm: LegalNormIR) -> Dict[str, List[Dict[str, Any]]]:
    """Return source-grounded slots intentionally omitted from theorem text."""

    omitted: Dict[str, List[Dict[str, Any]]] = {}
    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references)
        + _slot_texts(norm.resolved_cross_references)
        + _slot_texts(norm.overrides)
        if str(value).strip()
    }

    reference_conditions = [
        dict(item)
        for item in norm.conditions
        if isinstance(item, dict)
        and _is_reference_condition(
            item,
            _slot_primary_text(item),
            reference_values,
        )
    ]
    reference_exceptions = [
        dict(item)
        for item in norm.exceptions
        if isinstance(item, dict)
        and _is_reference_exception(
            item,
            _slot_primary_text(item),
            reference_values,
        )
    ]
    substantive_conditions = [
        dict(item)
        for item in norm.conditions
        if isinstance(item, dict)
        and not _is_reference_condition(
            item,
            _slot_primary_text(item),
            reference_values,
        )
    ]
    substantive_exceptions = [
        dict(item)
        for item in norm.exceptions
        if isinstance(item, dict)
        and not _is_reference_exception(
            item,
            _slot_primary_text(item),
            reference_values,
        )
    ]
    if reference_conditions:
        omitted["conditions"] = reference_conditions
    if reference_exceptions:
        omitted["exceptions"] = reference_exceptions
    capped_conditions = _capped_slot_omission_records(
        substantive_conditions,
        _FORMULA_CONDITION_LIMIT,
        "condition",
        "condition is preserved in IR but omitted from capped deontic formula antecedents",
    )
    if capped_conditions:
        omitted.setdefault("conditions", []).extend(capped_conditions)
    capped_exceptions = _capped_slot_omission_records(
        substantive_exceptions,
        _FORMULA_EXCEPTION_LIMIT,
        "exception",
        "exception is preserved in IR but omitted from capped deontic formula antecedents",
    )
    if capped_exceptions:
        omitted.setdefault("exceptions", []).extend(capped_exceptions)
    if norm.overrides:
        omitted["overrides"] = [dict(item) for item in norm.overrides if isinstance(item, dict)]
    recipient_record = _recipient_omission_record(norm)
    if recipient_record:
        omitted["recipients"] = [recipient_record]
    return omitted


def _capped_slot_omission_records(
    items: Sequence[Dict[str, Any]],
    limit: int,
    field: str,
    reason: str,
) -> List[Dict[str, Any]]:
    """Return provenance for source-grounded slots beyond formula caps."""

    records: List[Dict[str, Any]] = []
    for item in items[limit:]:
        value = _slot_primary_text(item)
        predicate = normalize_predicate_name(value)
        if not value or not predicate or predicate == "P":
            continue
        record: Dict[str, Any] = {
            "value": value,
            "field": field,
            "predicate": predicate,
            "reason": reason,
        }
        span = item.get("span")
        if isinstance(span, list) and len(span) == 2:
            record["span"] = list(span)
        records.append(record)
    return records


def _recipient_omission_record(norm: LegalNormIR) -> Dict[str, Any]:
    """Return omitted-formula provenance for a structured recipient slot."""

    recipient = str(norm.recipient or "").strip()
    if not recipient:
        return {}

    record: Dict[str, Any] = {
        "value": recipient,
        "field": "recipient",
        "reason": "recipient is preserved in IR but omitted from unary deontic formula consequent",
    }
    span = _field_span(norm, ("action_recipient", "recipient", "beneficiary"))
    if span:
        record["span"] = span
    return record


def _field_span(norm: LegalNormIR, keys: Iterable[str]) -> List[int]:
    for key in keys:
        value = norm.field_spans.get(key)
        if isinstance(value, list) and len(value) == 2:
            return list(value)
        if isinstance(value, dict) and isinstance(value.get("span"), list) and len(value["span"]) == 2:
            return list(value["span"])
    return []


def _is_reference_condition(item: Dict[str, Any], text: str, reference_values: Iterable[str]) -> bool:
    condition_type = str(item.get("condition_type") or item.get("type") or "").lower()
    reference_type = str(item.get("reference_type") or "").lower()
    if reference_type in {"section", "subsection", "chapter", "title", "article", "part", "cross_reference"}:
        return True

    normalized = text.strip().lower()
    if _is_local_scope_reference_condition_text(normalized):
        return True
    if reference_values and any(reference and reference in normalized for reference in reference_values):
        return True
    return condition_type == "subject_to" and bool(_LEGAL_REFERENCE_TEXT_RE.search(text))


def _is_reference_exception(item: Dict[str, Any], text: str, reference_values: Iterable[str]) -> bool:
    reference_type = str(item.get("reference_type") or item.get("type") or "").lower()
    if reference_type in {"section", "subsection", "chapter", "title", "article", "part", "cross_reference"}:
        return True

    normalized = text.strip().lower()
    if _is_local_scope_reference_exception_text(normalized):
        return True
    if _LEGAL_REFERENCE_TEXT_RE.search(normalized):
        return normalized.startswith(("as provided", "provided in", "under ", "pursuant to "))
    return any(reference and reference in normalized for reference in reference_values)


def _temporal_predicate_text(item: Dict[str, Any]) -> str:
    """Return a stable temporal predicate phrase from a structured slot."""

    temporal_type = str(item.get("type") or "Temporal")
    value = item.get("value") or item.get("normalized_text") or item.get("raw_text")
    if value:
        return f"{temporal_type} {value}"

    duration = _temporal_duration_value(item)
    anchor = item.get("anchor") or item.get("anchor_event") or item.get("event")
    anchor_relation = _temporal_anchor_relation(item)
    if duration and anchor:
        return f"{temporal_type} {duration} {anchor_relation} {anchor}"
    if duration:
        return f"{temporal_type} {duration}"
    if anchor:
        return f"{temporal_type} {anchor}"
    return temporal_type


def _temporal_duration_value(item: Dict[str, Any]) -> str:
    """Return a source-grounded duration phrase from structured deadline slots."""

    for key in ("duration", "deadline"):
        value = str(item.get(key) or "").strip()
        if value:
            return value

    quantity = item.get("quantity")
    unit = str(item.get("unit") or item.get("time_unit") or "").strip()
    calendar = str(item.get("calendar") or "").strip()
    if quantity is None or quantity == "":
        return ""

    parts = [str(quantity).strip()]
    if calendar:
        parts.append(calendar)
    if unit:
        parts.append(unit)
    return " ".join(part for part in parts if part)


def _temporal_anchor_relation(item: Dict[str, Any]) -> str:
    """Return the explicit relation between a duration and its anchor event."""

    for key in ("anchor_relation", "relation", "connector"):
        value = str(item.get(key) or "").strip().lower()
        if value in {"after", "before"}:
            return value
        if "before" in value:
            return "before"
        if "after" in value or value.startswith("upon"):
            return "after"

    return "after"


def _action_without_mental_state(action: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action or "")
    if words and words[0].lower() in _MENTAL_STATE_TERMS:
        return " ".join(words[1:]).strip()
    return action


def _mental_state_predicate(norm: LegalNormIR) -> str:
    """Return a mens rea predicate from structured slots when source-grounded."""

    explicit = normalize_predicate_name(norm.mental_state)
    if explicit and explicit != "P":
        return explicit

    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", norm.action or "")
    if words and words[0].lower() in _MENTAL_STATE_TERMS:
        return normalize_predicate_name(words[0])
    return ""


def _applicability_target(action: str) -> str:
    """Return the regulated target phrase from an applicability action slot."""

    text = str(action or "").strip()
    text = re.sub(r"^apply\s+to\s+", "", text, flags=re.IGNORECASE)
    return re.sub(r"^apply\s+", "", text, flags=re.IGNORECASE)


def _deterministic_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Return a narrow deterministic formula-level resolution when safe.

    Parser-level theorem promotion remains conservative. This helper can mark
    an exported formula record proof-ready only when all unresolved blockers are
    addressed by source-grounded IR slots that already appear in the formula.

    Parser-level theorem promotion remains conservative. This helper only
    promotes the exported frame formula for local applicability clauses where
    the unresolved reference is the clause's own scope, e.g. ``this section``.
    External references such as ``the chapter`` or numbered sections stay
    blocked until a citation resolver supplies source-grounded context.
    """

    exception_resolution = _standard_exception_formula_resolution(norm, blockers)
    if exception_resolution:
        return exception_resolution

    override_resolution = _pure_override_formula_resolution(norm, blockers)
    if override_resolution:
        return override_resolution

    reference_exception_resolution = _resolved_reference_exception_formula_resolution(norm, blockers)
    if reference_exception_resolution:
        return reference_exception_resolution

    local_reference_exception_resolution = _local_scope_reference_exception_formula_resolution(norm, blockers)
    if local_reference_exception_resolution:
        return local_reference_exception_resolution

    local_reference_condition_resolution = _local_scope_reference_condition_formula_resolution(norm, blockers)
    if local_reference_condition_resolution:
        return local_reference_condition_resolution

    reference_condition_resolution = _resolved_reference_condition_formula_resolution(norm, blockers)
    if reference_condition_resolution:
        return reference_condition_resolution

    if norm.modality != "APP" or norm.norm_type != "applicability":
        return {}

    allowed_blockers = {"cross_reference_requires_resolution", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}

    actor_text = norm.actor.strip().lower()
    if not re.match(r"^this\s+(section|chapter|title|article|part)$", actor_text):
        return {}

    if not norm.action.strip():
        return {}

    return {
        "type": "local_scope_applicability",
        "resolved_blockers": sorted(blocker_set),
        "scope": norm.actor,
        "reason": "local self-scope applicability formula is source-grounded",
    }


def _standard_exception_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve simple substantive exceptions at formula-record level.

    A clause like ``The applicant shall obtain a permit unless approval is
    denied`` already has a deterministic IR exception slot and the formula
    includes that slot as a negated antecedent.  The record can be proof-ready
    without changing parser-level blockers when the exception is a single,
    non-reference phrase and no precedence/citation review is pending.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions:
        return {}
    if norm.overrides or norm.cross_references or norm.resolved_cross_references:
        return {}

    allowed_blockers = {"exception_requires_scope_review", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}

    substantive_exceptions = _formula_exception_texts(norm)
    if len(substantive_exceptions) != 1:
        return {}

    exception_record = next(
        (item for item in norm.exceptions if isinstance(item, dict)),
        {},
    )
    exception_text = substantive_exceptions[0].strip()
    if not exception_text:
        return {}
    if _exception_text_needs_external_resolution(exception_text):
        return {}

    return {
        "type": "standard_substantive_exception",
        "resolved_blockers": sorted(blocker_set),
        "exception": exception_text,
        "exception_span": exception_record.get("span", []),
        "reason": "single substantive exception is represented as a negated formula antecedent",
    }


def _pure_override_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve pure precedence overrides at formula-record level.

    A clause such as ``Notwithstanding section 5.01.020, the Director may issue
    a variance`` has a source-grounded operative permission plus a precedence
    reference. The precedence slot remains exported as omitted provenance, but
    the operative formula can be proof-ready when no other unresolved semantic
    slot is present. Parser-level theorem promotion remains conservative.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if len(norm.overrides) != 1:
        return {}
    if norm.conditions or norm.exceptions or norm.temporal_constraints:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "override_clause_requires_precedence_review",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "override_clause_requires_precedence_review" not in blocker_set:
        return {}

    override_record = next((item for item in norm.overrides if isinstance(item, dict)), {})
    override_text = _slot_primary_text(override_record)
    if not override_text:
        return {}

    reference_texts = [_slot_primary_text(item) for item in norm.cross_references if isinstance(item, dict)]
    for reference_text in reference_texts:
        if reference_text and reference_text.lower() not in override_text.lower():
            return {}

    return {
        "type": "pure_precedence_override",
        "resolved_blockers": sorted(blocker_set),
        "override": override_text,
        "override_span": override_record.get("span", []),
        "reason": "single source-grounded precedence override is exported as provenance outside the operative formula",
    }


def _resolved_reference_exception_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve reference-only exceptions when citation resolution is explicit.

    A clause such as ``except as provided in section 552`` should not fabricate
    a factual predicate in the theorem text. It can still be proof-ready at the
    formula/export layer when the omitted exception is backed by same-document
    ``resolved_cross_references`` metadata. Parser-level theorem promotion stays
    conservative because precedence and scope review remain visible as blockers.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions or not norm.cross_references:
        return {}
    if norm.conditions or norm.overrides:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "cross_reference_requires_resolution" not in blocker_set:
        return {}
    if "exception_requires_scope_review" not in blocker_set:
        return {}

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references) + _slot_texts(norm.resolved_cross_references)
        if str(value).strip()
    }
    reference_exceptions = [
        item
        for item in norm.exceptions
        if isinstance(item, dict)
        and _is_reference_exception(item, _slot_primary_text(item), reference_values)
    ]
    if len(reference_exceptions) != len(norm.exceptions):
        return {}

    resolved_references = _same_document_reference_records(norm)
    if not resolved_references:
        return {}

    resolved_texts = [_reference_resolution_text(item) for item in resolved_references]
    for exception in reference_exceptions:
        exception_text = _slot_primary_text(exception).lower()
        if not exception_text:
            return {}
        if not any(_reference_text_matches_slot(reference_text, exception_text) for reference_text in resolved_texts):
            return {}

    reason = "reference-only exception is backed by explicit same-document cross-reference resolution"
    resolved_blockers = sorted(blocker_set)
    if any(item.get("matched_section_context") for item in resolved_references):
        reason = "numbered exception reference is resolved to an exact same-document section and retained as provenance"
        resolved_blockers = sorted(
            blocker for blocker in blocker_set if blocker != "llm_repair_required"
        )

    return {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": resolved_blockers,
        "references": resolved_texts,
        "exception_spans": [item.get("span", []) for item in reference_exceptions],
        "reason": reason,
    }


def _resolved_reference_condition_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve reference-only conditions when citation resolution is explicit.

    A clause such as ``Subject to section 552, the Secretary shall publish the
    notice`` should not fabricate a factual predicate like ``Section552(x)``.
    It can still become proof-ready at the formula/export layer when every
    omitted condition is a legal reference backed by explicit same-document
    resolution. Parser-level theorem promotion remains conservative.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.conditions or not norm.cross_references:
        return {}
    if norm.exceptions or norm.overrides:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "cross_reference_requires_resolution" not in blocker_set:
        return {}

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references) + _slot_texts(norm.resolved_cross_references)
        if str(value).strip()
    }
    reference_conditions = [
        item
        for item in norm.conditions
        if isinstance(item, dict)
        and _is_reference_condition(item, _slot_primary_text(item), reference_values)
    ]
    if len(reference_conditions) != len(norm.conditions):
        return {}

    resolved_references = _same_document_reference_records(norm)
    if not resolved_references:
        return {}

    resolved_texts = [_reference_resolution_text(item) for item in resolved_references]
    for condition in reference_conditions:
        condition_text = _slot_primary_text(condition).lower()
        if not condition_text:
            return {}
        if not any(_reference_text_matches_slot(reference_text, condition_text) for reference_text in resolved_texts):
            return {}

    return {
        "type": "resolved_same_document_reference_condition",
        "resolved_blockers": sorted(blocker_set),
        "references": resolved_texts,
        "condition_spans": [item.get("span", []) for item in reference_conditions],
        "reason": "reference-only condition is backed by explicit same-document cross-reference resolution",
    }


def _local_scope_reference_condition_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve exact local self-reference conditions at formula-record level.

    A clause such as ``Subject to this section, the Secretary shall publish the
    notice`` carries local provenance, not a factual precondition. The condition
    remains exported as an omitted source-grounded slot, but the operative
    formula can be proof-ready when no other unresolved semantic slot is present.
    Numbered and external references stay blocked by the existing same-document
    reference resolver.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.conditions:
        return {}
    if norm.exceptions or norm.overrides:
        return {}

    allowed_blockers = {"cross_reference_requires_resolution", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "cross_reference_requires_resolution" not in blocker_set:
        return {}

    reference_conditions = [
        item
        for item in norm.conditions
        if isinstance(item, dict)
        and _is_local_scope_reference_condition_text(_slot_primary_text(item))
    ]
    if len(reference_conditions) != len(norm.conditions):
        return {}

    local_reference_records = _local_scope_reference_records(norm)
    if (norm.cross_references or norm.resolved_cross_references) and not local_reference_records:
        return {}

    scopes = []
    for condition in reference_conditions:
        match = _LOCAL_SCOPE_REFERENCE_CONDITION_RE.match(_slot_primary_text(condition).strip())
        if not match:
            return {}
        scope = f"this {match.group(1).lower()}"
        if scope not in scopes:
            scopes.append(scope)

    for reference in local_reference_records:
        scope = _local_scope_reference_record_scope(reference)
        if not scope:
            return {}
        if scope.replace("current ", "this ") not in scopes:
            return {}

    return {
        "type": "local_scope_reference_condition",
        "resolved_blockers": sorted(blocker_set),
        "scopes": scopes,
        "condition_spans": [item.get("span", []) for item in reference_conditions],
        "reason": "local self-reference condition is exported as provenance outside the operative formula",
    }


def _local_scope_reference_exception_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve exact local self-reference exceptions at formula-record level.

    Clauses such as ``except as provided in this section`` point back to the
    same local scope rather than to an unresolved numbered or external legal
    reference. The exception remains exported as omitted provenance, but the
    operative formula can be proof-ready when no other unresolved semantic slot
    is present. This does not relax parser-level theorem promotion.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions:
        return {}
    if norm.conditions or norm.overrides:
        return {}

    allowed_blockers = {"exception_requires_scope_review", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "exception_requires_scope_review" not in blocker_set:
        return {}

    reference_exceptions = [
        item
        for item in norm.exceptions
        if isinstance(item, dict)
        and _is_local_scope_reference_exception_text(_slot_primary_text(item))
    ]
    if len(reference_exceptions) != len(norm.exceptions):
        return {}

    local_reference_records = _local_scope_reference_records(norm)
    if (norm.cross_references or norm.resolved_cross_references) and not local_reference_records:
        return {}

    scopes = []
    for exception in reference_exceptions:
        match = _LOCAL_SCOPE_REFERENCE_EXCEPTION_RE.match(_slot_primary_text(exception).strip())
        if not match:
            return {}
        scope = f"this {match.group(1).lower()}"
        if scope not in scopes:
            scopes.append(scope)

    for reference in local_reference_records:
        scope = _local_scope_reference_record_scope(reference)
        if not scope:
            return {}
        if scope not in scopes:
            return {}

    return {
        "type": "local_scope_reference_exception",
        "resolved_blockers": sorted(blocker_set),
        "scopes": scopes,
        "exception_spans": [item.get("span", []) for item in reference_exceptions],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }


def _batch_resolved_reference_exception_formula_resolution(
    norm: LegalNormIR,
    blockers: List[str],
) -> Dict[str, Any]:
    """Resolve numbered reference exceptions backed by same-document IR.

    Single-record parsing must keep ``except as provided in section 552`` in the
    repair lane because the referenced section may be absent, external, or
    semantically incompatible. Batch formula export has a narrower deterministic
    opportunity: if every reference-only exception cites a section that the IR
    batch has already resolved to the same document, the exception is retained
    as provenance and excluded from the operative formula antecedent.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions:
        return {}
    if norm.conditions or norm.overrides:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if not {"cross_reference_requires_resolution", "exception_requires_scope_review"}.issubset(blocker_set):
        return {}

    same_document_records = _same_document_reference_records(norm)
    if not same_document_records:
        return {}

    exception_texts = [
        _slot_primary_text(item)
        for item in norm.exceptions
        if isinstance(item, dict)
    ]
    if len(exception_texts) != len(norm.exceptions):
        return {}
    if any(not _exception_text_needs_external_resolution(text) for text in exception_texts):
        return {}

    reference_texts = [_reference_resolution_text(item) for item in same_document_records]
    if not reference_texts:
        return {}
    if not all(
        any(_reference_text_matches_slot(reference_text, exception_text) for reference_text in reference_texts)
        for exception_text in exception_texts
    ):
        return {}

    resolved_blockers = sorted(
        blocker for blocker in blocker_set if blocker != "llm_repair_required"
    )
    return {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": resolved_blockers,
        "references": reference_texts,
        "exception_spans": [item.get("span", []) for item in norm.exceptions if isinstance(item, dict)],
        "reason": "numbered exception reference is resolved to an exact same-document section and retained as provenance",
    }


def _normalize_formula_resolution(resolution: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize deterministic resolution payloads without dropping provenance."""

    if not resolution:
        return {}
    return dict(resolution)


def _same_document_reference_records(norm: LegalNormIR) -> List[Dict[str, Any]]:
    """Return source-grounded same-document reference records for exceptions.

    The parser may represent a deterministically resolved local reference in
    either ``resolved_cross_references`` or directly on ``cross_reference_details``
    with a ``same_document``/``resolution_scope`` marker. Treat both shapes as
    equivalent for formula-level repair clearance, while unmarked references
    remain blocked.
    """

    records: List[Dict[str, Any]] = []
    for item in norm.resolved_cross_references:
        if isinstance(item, dict) and _is_same_document_resolved_reference(item):
            records.append(item)

    if records:
        return records

    return [
        item
        for item in norm.cross_references
        if isinstance(item, dict) and _is_same_document_resolved_reference(item)
    ]


def _reference_text_matches_slot(reference_text: str, slot_text: str) -> bool:
    reference = str(reference_text or "").strip().lower()
    slot = str(slot_text or "").strip().lower()
    if not reference or not slot:
        return False
    if reference in slot:
        return True
    reference_citation = _canonical_section_citation(reference)
    slot_citation = _canonical_section_citation(slot)
    if reference_citation and slot_citation and reference_citation == slot_citation:
        return True
    reference_citations = set(_section_citations_from_text(reference))
    slot_citations = set(_section_citations_from_text(slot))
    return bool(reference_citations and reference_citations.issubset(slot_citations))


def _local_scope_reference_records(norm: LegalNormIR) -> List[Dict[str, Any]]:
    """Return explicit local self-reference records, rejecting mixed references."""

    all_references = [
        item
        for item in list(norm.cross_references) + list(norm.resolved_cross_references)
        if isinstance(item, dict)
    ]
    if not all_references:
        return []

    local_references = [item for item in all_references if _local_scope_reference_record_scope(item)]
    if len(local_references) != len(all_references):
        return []
    return local_references


def _local_scope_reference_record_scope(item: Dict[str, Any]) -> str:
    """Return `this section` style scope for a structured local reference."""

    reference_type = str(item.get("reference_type") or item.get("type") or "").strip().lower()
    if reference_type not in {"section", "subsection", "chapter", "title", "article", "part"}:
        return ""

    target = str(item.get("target") or item.get("section") or item.get("subsection") or "").strip().lower()
    if target in {"this", f"this {reference_type}"}:
        return f"this {reference_type}"

    for key in ("value", "normalized_text", "raw_text", "text", "canonical_citation", "citation"):
        text = str(item.get(key) or "").strip().lower()
        if text == f"this {reference_type}":
            return text

    return ""


def _reference_resolution_text(item: Dict[str, Any]) -> str:
    """Return canonical display text for resolved legal references."""

    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        value = item.get(key)
        if value:
            return str(value).strip()

    reference_type = str(item.get("reference_type") or item.get("type") or "").strip().lower()
    target = str(item.get("target") or item.get("section") or item.get("subsection") or "").strip()
    if reference_type and target:
        return target if target.lower().startswith(reference_type + " ") else f"{reference_type} {target}"
    return ""


def _slot_primary_text(item: Dict[str, Any]) -> str:
    """Return the stable text value for a structured IR slot."""

    for key in (
        "value",
        "normalized_text",
        "raw_text",
        "text",
        "condition_text",
        "exception_text",
        "clause_text",
        "predicate_text",
        "description",
        "canonical_citation",
        "citation",
    ):
        value = item.get(key)
        if value:
            return str(value).strip()
    return ""


def _is_same_document_resolved_reference(item: Dict[str, Any]) -> bool:
    """Return whether a resolved reference is explicitly same-document."""

    if item.get("same_document") is True:
        return True

    for key in ("resolution_scope", "document_scope", "source_scope", "scope"):
        value = str(item.get(key) or "").strip().lower().replace("-", "_")
        if value in {"same_document", "this_document", "current_document", "local"}:
            return True

    target_document = str(item.get("target_document") or "").strip().lower()
    return target_document in {"same_document", "this_document", "current_document"}


def _is_local_scope_reference_exception_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return bool(_LOCAL_SCOPE_REFERENCE_EXCEPTION_RE.match(normalized))


def _is_local_scope_reference_condition_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return bool(_LOCAL_SCOPE_REFERENCE_CONDITION_RE.match(normalized))


def _exception_text_needs_external_resolution(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True
    if _LEGAL_REFERENCE_TEXT_RE.search(normalized):
        return True
    return normalized.startswith((
        "as otherwise provided",
        "as provided",
        "otherwise provided in",
        "provided in",
        "under ",
        "pursuant to ",
        "notwithstanding ",
    ))


def _normalize_assessment_imposition_light_verb_action(action_text: str) -> str:
    """Project assessment/imposition nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    assessment_patterns = [
        r"^(?:make|perform|conduct|complete|issue|provide|prepare)\s+an?\s+assessment\s+of\s+(.+)$",
        r"^(?:make|perform|conduct|complete|issue|provide|prepare)\s+the\s+assessment\s+of\s+(.+)$",
        r"^assessment\s+of\s+(.+)$",
    ]
    for pattern in assessment_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"assess {target}" if target else text

    imposition_patterns = [
        r"^(?:make|perform|complete|enter|issue|provide)\s+an?\s+imposition\s+of\s+(.+)$",
        r"^(?:make|perform|complete|enter|issue|provide)\s+the\s+imposition\s+of\s+(.+)$",
        r"^imposition\s+of\s+(.+)$",
    ]
    for pattern in imposition_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"impose {target}" if target else text

    return text


def _normalize_deletion_erasure_light_verb_action(action_text: str) -> str:
    """Project deletion/erasure nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    deletion_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?deletion\s+of\s+(.+)$",
        r"^deletion\s+of\s+(.+)$",
    ]
    for pattern in deletion_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"delete {target}" if target else text

    erasure_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?erasure\s+of\s+(.+)$",
        r"^erasure\s+of\s+(.+)$",
    ]
    for pattern in erasure_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"erase {target}" if target else text

    return text


def _normalize_preservation_restoration_light_verb_action(action_text: str) -> str:
    """Project preservation/restoration nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    preservation_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?preservation\s+of\s+(.+)$",
        r"^preservation\s+of\s+(.+)$",
    ]
    for pattern in preservation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"preserve {target}" if target else text

    restoration_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?restoration\s+of\s+(.+)$",
        r"^restoration\s+of\s+(.+)$",
    ]
    for pattern in restoration_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"restore {target}" if target else text

    return text


def _normalize_archival_retention_light_verb_action(action_text: str) -> str:
    """Project archival and retention nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    archival_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?archival\s+of\s+(.+)$",
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?archiving\s+of\s+(.+)$",
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?archive\s+of\s+(.+)$",
        r"^(?:archival|archiving|archive)\s+of\s+(.+)$",
    ]
    for pattern in archival_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"archive {target}" if target else text

    retention_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?retention\s+of\s+(.+)$",
        r"^retention\s+of\s+(.+)$",
    ]
    for pattern in retention_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"retain {target}" if target else text

    return text


def _normalize_redaction_anonymization_light_verb_action(action_text: str) -> str:
    """Project redaction and anonymization nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    redaction_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?redaction\s+of\s+(.+)$",
        r"^redaction\s+of\s+(.+)$",
    ]
    for pattern in redaction_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"redact {target}" if target else text

    anonymization_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?anonymi[sz]ation\s+of\s+(.+)$",
        r"^anonymi[sz]ation\s+of\s+(.+)$",
    ]
    for pattern in anonymization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"anonymize {target}" if target else text

    return text


def _normalize_masking_pseudonymization_light_verb_action(action_text: str) -> str:
    """Project masking and pseudonymization nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    masking_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?masking\s+of\s+(.+)$",
        r"^masking\s+of\s+(.+)$",
    ]
    for pattern in masking_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"mask {target}" if target else text

    pseudonymization_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?pseudonymi[sz]ation\s+of\s+(.+)$",
        r"^pseudonymi[sz]ation\s+of\s+(.+)$",
    ]
    for pattern in pseudonymization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"pseudonymize {target}" if target else text

    return text


def _normalize_encryption_decryption_light_verb_action(action_text: str) -> str:
    """Project encryption, decryption, and tokenization nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    encryption_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:an?\s+|the\s+)?encryption\s+of\s+(.+)$",
        r"^encryption\s+of\s+(.+)$",
    ]
    for pattern in encryption_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"encrypt {target}" if target else text

    decryption_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:a\s+|the\s+)?decryption\s+of\s+(.+)$",
        r"^decryption\s+of\s+(.+)$",
    ]
    for pattern in decryption_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"decrypt {target}" if target else text

    tokenization_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:a\s+|the\s+)?tokeni[sz]ation\s+of\s+(.+)$",
        r"^tokeni[sz]ation\s+of\s+(.+)$",
    ]
    for pattern in tokenization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"tokenize {target}" if target else text

    detokenization_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out)\s+(?:a\s+|the\s+)?detokeni[sz]ation\s+of\s+(.+)$",
        r"^detokeni[sz]ation\s+of\s+(.+)$",
    ]
    for pattern in detokenization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"detokenize {target}" if target else text

    return text


def _normalize_sealing_unsealing_light_verb_action(action_text: str) -> str:
    """Project sealing and unsealing nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    sealing_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out|order)\s+(?:a\s+|the\s+)?sealing\s+of\s+(.+)$",
        r"^sealing\s+of\s+(.+)$",
    ]
    for pattern in sealing_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"seal {target}" if target else text

    unsealing_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out|order)\s+(?:an?\s+|the\s+)?unsealing\s+of\s+(.+)$",
        r"^unsealing\s+of\s+(.+)$",
    ]
    for pattern in unsealing_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"unseal {target}" if target else text

    return text


def _normalize_expungement_destruction_light_verb_action(action_text: str) -> str:
    """Project expungement and destruction nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    expungement_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out|order)\s+(?:an?\s+|the\s+)?expungement\s+of\s+(.+)$",
        r"^expungement\s+of\s+(.+)$",
    ]
    for pattern in expungement_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"expunge {target}" if target else text

    destruction_patterns = [
        r"^(?:make|perform|conduct|complete|effectuate|carry\s+out|order)\s+(?:a\s+|the\s+)?destruction\s+of\s+(.+)$",
        r"^destruction\s+of\s+(.+)$",
    ]
    for pattern in destruction_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"destroy {target}" if target else text

    return text


def _normalize_enforcement_remedy_light_verb_action(action_text: str) -> str:
    """Project enforcement remedy nominalizations to operative predicates."""

    text = str(action_text or "").strip()
    if not text:
        return text

    remedy_patterns = [
        (
            r"^(?:file|files|filed|filing|record|records|recorded|recording|place|places|placed|placing|impose|imposes|imposed|imposing|enter|enters|entered|entering)\s+"
            r"(?:a\s+|the\s+)?lien\s+(?:on|against|upon)\s+(?:the\s+)?(.+)$",
            "lien",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing)\s+"
            r"(?:a\s+|the\s+)?lien\s+(?:on|against|upon)\s+(?:the\s+)?(.+)$",
            "lien",
        ),
        (
            r"^(?:impose|imposes|imposed|imposing|make|makes|made|making|issue|issues|issued|issuing|enter|enters|entered|entering|order|orders|ordered|ordering)\s+"
            r"(?:a\s+|the\s+)?levy\s+(?:on|against|upon)\s+(?:the\s+)?(.+)$",
            "levy",
        ),
        (
            r"^(?:make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|order|orders|ordered|ordering|declare|declares|declared|declaring|enter|enters|entered|entering)\s+"
            r"(?:a\s+|the\s+)?forfeiture\s+(?:of|on)\s+(?:the\s+)?(.+)$",
            "forfeit",
        ),
        (
            r"^(?:order|orders|ordered|ordering|conduct|conducts|conducted|conducting|make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|carry\s+out|carries\s+out|carried\s+out|carrying\s+out)\s+"
            r"(?:a\s+|the\s+)?seizure\s+(?:of|from)\s+(?:the\s+)?(.+)$",
            "seize",
        ),
        (
            r"^(?:order|orders|ordered|ordering|conduct|conducts|conducted|conducting|make|makes|made|making|effect|effects|effected|effecting|complete|completes|completed|completing|carry\s+out|carries\s+out|carried\s+out|carrying\s+out)\s+"
            r"(?:an?\s+|the\s+)?impoundment\s+(?:of|for)\s+(?:the\s+)?(.+)$",
            "impound",
        ),
        (r"^(?:lien)\s+(?:on|against|upon)\s+(?:the\s+)?(.+)$", "lien"),
        (r"^(?:levy)\s+(?:on|against|upon)\s+(?:the\s+)?(.+)$", "levy"),
        (r"^forfeiture\s+(?:of|on)\s+(?:the\s+)?(.+)$", "forfeit"),
        (r"^seizure\s+(?:of|from)\s+(?:the\s+)?(.+)$", "seize"),
        (r"^impoundment\s+(?:of|for)\s+(?:the\s+)?(.+)$", "impound"),
    ]
    for pattern, verb in remedy_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"{verb} {target}" if target else text

    return text


def _normalize_recordation_memorialization_light_verb_action(action_text: str) -> str:
    """Project legal recordation and memorialization nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    recordation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"(?:a\s+|the\s+)?recordation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"recordations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^recordation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in recordation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"record {target}" if target else text

    memorialization_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"(?:a\s+|the\s+)?memorialization\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"memorializations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^memorialization\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in memorialization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"memorialize {target}" if target else text

    return text


def _normalize_ratification_confirmation_light_verb_action(action_text: str) -> str:
    """Project ratification and confirmation nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    ratification_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|approve|approves|approved|approving|adopt|adopts|adopted|adopting)\s+"
        r"(?:a\s+|the\s+)?ratification\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|approve|approves|approved|approving|adopt|adopts|adopted|adopting)\s+"
        r"ratifications\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^ratification\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in ratification_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"ratify {target}" if target else text

    confirmation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|provide|provides|provided|providing|approve|approves|approved|approving)\s+"
        r"(?:a\s+|the\s+)?confirmation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|provide|provides|provided|providing|approve|approves|approved|approving)\s+"
        r"confirmations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^confirmation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in confirmation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"confirm {target}" if target else text

    return text


def _normalize_attestation_notarization_light_verb_action(action_text: str) -> str:
    """Project attestation and notarization nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    attestation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|provide|provides|provided|providing|file|files|filed|filing)\s+"
        r"(?:an?\s+|the\s+)?attestation\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|provide|provides|provided|providing|file|files|filed|filing)\s+"
        r"attestations\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^attestation\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in attestation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"attest {target}" if target else text

    notarization_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|perform|performs|performed|performing|provide|provides|provided|providing|file|files|filed|filing)\s+"
        r"(?:a\s+|the\s+)?notarization\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|perform|performs|performed|performing|provide|provides|provided|providing|file|files|filed|filing)\s+"
        r"notarizations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^notarization\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in notarization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"notarize {target}" if target else text

    return text


def _normalize_acknowledgment_authentication_light_verb_action(action_text: str) -> str:
    """Project acknowledgment and authentication nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    acknowledgment_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|provide|provides|provided|providing|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"(?:an?\s+|the\s+)?acknowledg(?:e)?ment\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|issue|issues|issued|issuing|provide|provides|provided|providing|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"acknowledg(?:e)?ments\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^acknowledg(?:e)?ment\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in acknowledgment_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"acknowledge {target}" if target else text

    authentication_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|perform|performs|performed|performing|provide|provides|provided|providing|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"(?:an?\s+|the\s+)?authentication\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|enter|enters|entered|entering|perform|performs|performed|performing|provide|provides|provided|providing|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"authentications\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^authentication\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in authentication_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"authenticate {target}" if target else text

    return text


def _normalize_summarization_indexing_light_verb_action(action_text: str) -> str:
    """Project summarization and indexing nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    summarization_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"(?:a\s+|the\s+)?summary\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"summaries\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"(?:a\s+|the\s+)?summarization\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^summar(?:y|ization)\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in summarization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"summarize {target}" if target else text

    indexing_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|create|creates|created|creating|maintain|maintains|maintained|maintaining|file|files|filed|filing)\s+"
        r"(?:an?\s+|the\s+)?index\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|create|creates|created|creating|maintain|maintains|maintained|maintaining|file|files|filed|filing)\s+"
        r"indexes\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|create|creates|created|creating|maintain|maintains|maintained|maintaining|file|files|filed|filing)\s+"
        r"(?:an?\s+|the\s+)?indexing\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^index(?:es|ing)?\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in indexing_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"index {target}" if target else text

    return text


def _normalize_transcription_translation_light_verb_action(action_text: str) -> str:
    """Project transcription and translation nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    transcription_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"(?:a\s+|the\s+)?transcription\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|file|files|filed|filing|record|records|recorded|recording)\s+"
        r"transcriptions\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^transcription\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in transcription_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"transcribe {target}" if target else text

    translation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|file|files|filed|filing|issue|issues|issued|issuing|furnish|furnishes|furnished|furnishing)\s+"
        r"(?:a\s+|the\s+)?translation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|provide|provides|provided|providing|file|files|filed|filing|issue|issues|issued|issuing|furnish|furnishes|furnished|furnishing)\s+"
        r"translations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^translation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in translation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"translate {target}" if target else text

    return text


def _normalize_codification_recodification_light_verb_action(action_text: str) -> str:
    """Project codification and recodification nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    codification_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|publish|publishes|published|publishing|adopt|adopts|adopted|adopting|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"(?:a\s+|the\s+)?codification\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|publish|publishes|published|publishing|adopt|adopts|adopted|adopting|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"codifications\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^codification\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in codification_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"codify {target}" if target else text

    recodification_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|publish|publishes|published|publishing|adopt|adopts|adopted|adopting|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"(?:a\s+|the\s+)?recodification\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|publish|publishes|published|publishing|adopt|adopts|adopted|adopting|issue|issues|issued|issuing|file|files|filed|filing)\s+"
        r"recodifications\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^recodification\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in recodification_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"recodify {target}" if target else text

    return text


def _normalize_consolidation_reconciliation_light_verb_action(action_text: str) -> str:
    """Project consolidation and reconciliation nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    consolidation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"(?:a\s+|the\s+)?consolidation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"consolidations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^consolidation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in consolidation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"consolidate {target}" if target else text

    reconciliation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"(?:a\s+|the\s+)?reconciliation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"reconciliations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^reconciliation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in reconciliation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"reconcile {target}" if target else text

    return text


def _normalize_aggregation_tabulation_light_verb_action(action_text: str) -> str:
    """Project aggregation and tabulation nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    aggregation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"(?:an?\s+|the\s+)?aggregation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"aggregations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^aggregation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in aggregation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"aggregate {target}" if target else text

    tabulation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"(?:a\s+|the\s+)?tabulation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|file|files|filed|filing|submit|submits|submitted|submitting|provide|provides|provided|providing|issue|issues|issued|issuing|enter|enters|entered|entering)\s+"
        r"tabulations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^tabulation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in tabulation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"tabulate {target}" if target else text

    return text


def _normalize_segregation_sequestration_light_verb_action(action_text: str) -> str:
    """Project segregation and sequestration nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    segregation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|maintain|maintains|maintained|maintaining|order|orders|ordered|ordering)\s+"
        r"(?:a\s+|the\s+)?segregation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|maintain|maintains|maintained|maintaining|order|orders|ordered|ordering)\s+"
        r"segregations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^segregation\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in segregation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"segregate {target}" if target else text

    sequestration_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|maintain|maintains|maintained|maintaining|order|orders|ordered|ordering)\s+"
        r"(?:a\s+|the\s+)?sequestration\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|maintain|maintains|maintained|maintaining|order|orders|ordered|ordering)\s+"
        r"sequestrations\s+(?:of|for)\s+(?:the\s+)?(.+)$",
        r"^sequestration\s+(?:of|for)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in sequestration_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"sequester {target}" if target else text

    return text


def _normalize_assignment_allocation_light_verb_action(action_text: str) -> str:
    """Project assignment and allocation nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    assignment_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|effect|effects|effected|effecting|execute|executes|executed|executing|record|records|recorded|recording|file|files|filed|filing|approve|approves|approved|approving|issue|issues|issued|issuing)\s+"
        r"(?:an?\s+|the\s+)?assignment\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|effect|effects|effected|effecting|execute|executes|executed|executing|record|records|recorded|recording|file|files|filed|filing|approve|approves|approved|approving|issue|issues|issued|issuing)\s+"
        r"assignments\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^assignment\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in assignment_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"assign {target}" if target else text

    allocation_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|approve|approves|approved|approving|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording)\s+"
        r"(?:an?\s+|the\s+)?allocation\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|approve|approves|approved|approving|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording)\s+"
        r"allocations\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^allocation\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in allocation_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"allocate {target}" if target else text

    return text


def _normalize_prioritization_scheduling_light_verb_action(action_text: str) -> str:
    """Project prioritization and scheduling nominalizations."""

    text = str(action_text or "").strip()
    if not text:
        return text

    prioritization_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|approve|approves|approved|approving|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording)\s+"
        r"(?:a\s+|the\s+)?prioriti[sz]ation\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|approve|approves|approved|approving|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording)\s+"
        r"prioriti[sz]ations\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^prioriti[sz]ation\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in prioritization_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"prioritize {target}" if target else text

    scheduling_patterns = [
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|approve|approves|approved|approving|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording|enter|enters|entered|entering)\s+"
        r"(?:a\s+|the\s+)?scheduling\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^(?:make|makes|made|making|complete|completes|completed|completing|prepare|prepares|prepared|preparing|perform|performs|performed|performing|conduct|conducts|conducted|conducting|approve|approves|approved|approving|order|orders|ordered|ordering|issue|issues|issued|issuing|record|records|recorded|recording|enter|enters|entered|entering)\s+"
        r"schedulings\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
        r"^scheduling\s+(?:of|for|to)\s+(?:the\s+)?(.+)$",
    ]
    for pattern in scheduling_patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            target = _normalized_light_verb_target(match.group(1))
            return f"schedule {target}" if target else text

    return text


def _normalized_light_verb_target(target: str) -> str:
    """Return a compact source-grounded nominalization target."""

    normalized = re.sub(r"\s+", " ", str(target or "").strip())
    normalized = re.sub(r"^(?:of|for|to)\s+", "", normalized, flags=re.IGNORECASE)
    return normalized.rstrip(" .,;:")

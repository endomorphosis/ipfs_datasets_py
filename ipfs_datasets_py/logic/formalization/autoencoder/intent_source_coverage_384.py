"""Bounded, post-generation source agreement for complete native Intent records.

This source contract exposes existing first-order assumption, explicit intention,
and action-contract owners. It never changes a prediction or interprets permission
as intention. ``source_target`` is an authored-label/reference helper, not a learned
decoder. Complete records generally exceed the unchanged 64-token model window.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import re

from . import family_training as core
from . import family_training_v7 as training
from . import intent_candidate_fidelity as fidelity
from ...intent_ir import decoder, schema
from ...autoformal import tree_pin
from ....optimizers.logic_theorem_optimizer import domain_384_autoencoder as source384
from ....optimizers.logic_theorem_optimizer import autoencoder_schema_lake as owner_pin

SCHEMA = "intent-native-source-coverage/v1"
MAX_SOURCE_BYTES = 4096
MAX_CLAUSES = 16
MODEL_TARGET_TOKEN_LIMIT = 64
FALSE = {**fidelity.FALSE, "promotion_performed": False,
    "source_decoder_trained": False, "reference_supplied_to_model": False,
    "all_logic_families_supported": False}
_WORD = r"[A-Za-z][A-Za-z0-9_-]{0,63}"
_ASSUMPTION = re.compile(rf"Assume (?:the )?(?P<entity>{_WORD}) is (?P<property>{_WORD})")
_GOAL = re.compile(rf"(?:The )?(?P<actor>{_WORD}) (?P<modal>intends to|must not|must|may) "
                   rf"(?P<action>{_WORD}) (?:the )?(?P<object>{_WORD})")
_CONTRACT = re.compile(rf"(?P<kind>Precondition|Effect|Postcondition) of (?P<action>{_WORD}) "
    rf"by (?P<actor>{_WORD}) on (?P<object>{_WORD}): (?:the )?(?P<entity>{_WORD}) is (?P<property>{_WORD})")
_RESERVED = {"it", "they", "them", "this", "that", "these", "those", "he", "she", "him", "her",
    "not", "and", "or", "if", "unless", "then", "before", "after", "all", "any", "some", "each",
    "the", "a", "an", "is", "must", "may", "intends", "to"}


def _pins():
    pins = fidelity._pins()
    for module in (importlib.import_module(__name__), core, training, fidelity,
                   schema, decoder, source384, tree_pin):
        pins[module.__name__] = owner_pin._pin_imported_module(module)
    return pins


def _source(source_text):
    if (type(source_text) is not str or not source_text or not source_text.isascii()
            or len(source_text.encode()) > MAX_SOURCE_BYTES):
        raise ValueError("bounded nonempty ASCII source required")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in source_text):
        raise ValueError("unsupported source control character")
    stripped = source_text.strip()
    if not stripped.endswith("."):
        raise ValueError("every complete source clause must end with a period")
    clauses = [part.strip() for part in stripped[:-1].split(".")]
    if not 1 <= len(clauses) <= MAX_CLAUSES or any(not clause for clause in clauses):
        raise ValueError("one to sixteen nonempty complete clauses required")
    if len(set(clauses)) != len(clauses):
        raise ValueError("duplicate source clauses are outside this bounded contract")
    return clauses


def _source_target(source_text):
    clauses = _source(source_text)
    digest = fidelity._sha(source_text.encode())
    source = schema.SourceRef("source", "instruction:bounded-native-intent", digest, digest, digest,
        review_status=schema.ReviewStatus.MACHINE_EXTRACTED, span=schema.SourceSpan(0, len(source_text)))
    statements = []
    actions = set()
    conditions = []
    modalities = {"intends to": schema.IntentModality.INTENDED, "must": schema.IntentModality.REQUIRED,
                  "may": schema.IntentModality.PERMITTED, "must not": schema.IntentModality.PROHIBITED}
    for index, clause in enumerate(clauses):
        assumption, goal, contract = _ASSUMPTION.fullmatch(clause), _GOAL.fullmatch(clause), _CONTRACT.fullmatch(clause)
        match = assumption or goal or contract
        if match is None:
            raise ValueError("unsupported complete source clause at index " + str(index))
        fields = match.groupdict()
        if any(value.lower() in _RESERVED for key, value in fields.items() if key not in {"kind", "modal"}):
            raise ValueError("unresolved reference or reserved source slot")
        identity = "statement:" + str(index)
        if assumption:
            kind, modality = schema.StatementKind.ASSUMPTION, schema.IntentModality.ASSERTED
            predicate, arguments = fields["property"], (fields["entity"],)
        elif goal:
            kind, modality = schema.StatementKind.GOAL, modalities[fields["modal"]]
            predicate, arguments = fields["action"], (fields["actor"], fields["object"])
            actions.add((fields["actor"], fields["action"], fields["object"]))
        else:
            kind = {"Precondition": schema.StatementKind.PRECONDITION, "Effect": schema.StatementKind.EFFECT,
                    "Postcondition": schema.StatementKind.POSTCONDITION}[fields["kind"]]
            modality = schema.IntentModality.ASSERTED
            predicate, arguments = fields["property"], (fields["entity"],)
            conditions.append((identity, kind, (fields["actor"], fields["action"], fields["object"])))
        statements.append(schema.IntentStatement(identity, kind, modality, clause + ".", ("source",),
            predicate, arguments, confidence=0.0, grounding=schema.NodeGrounding.INFERRED))
    if len(actions) > 1:
        raise ValueError("distinct actions require an explicit ordering contract outside this grammar")
    if any(action not in actions for _, _, action in conditions):
        raise ValueError("condition requires an exact explicitly declared action, actor and object")
    if not actions:
        raise ValueError("complete native Intent document requires an explicit goal; no goal is invented for an assumption")
    native_actions = ()
    if actions:
        actor, verb, object_ref = next(iter(actions))
        native_actions = (schema.IntentAction("action:0", actor, verb, (object_ref,), ("source",),
            precondition_ids=tuple(identity for identity, kind, _ in conditions if kind == schema.StatementKind.PRECONDITION),
            effect_ids=tuple(identity for identity, kind, _ in conditions if kind in
                             {schema.StatementKind.EFFECT, schema.StatementKind.POSTCONDITION}),
            grounding=schema.NodeGrounding.INFERRED),)
    document = schema.IntentIRDocument("intent-native-source:" + digest, "Bounded source Intent document",
        schema.IntentKind.PROCEDURE if native_actions else schema.IntentKind.DECLARATIVE,
        (source,), tuple(statements), native_actions, (),
        ("action:0",) if native_actions else (), ("action:0",) if native_actions else (),
        tags=("bounded-source-reference",))
    document.validate()
    target = {"kind": "document", "document": document.to_dict()}
    fidelity._json_input(target)
    source384.validate_target("intent_ir", target)
    return target


def source_target(source_text):
    """Authored weak label or post-inference reference, never a model prediction.

    Assumptions remain interpretation constraints, not verified world facts.
    Supplied pre/post predicates are declarations; finite truth requires separate
    source-bound state/context and effect bindings in existing native owners.
    """
    pins = _pins()
    tree_pin.require_workspace_logic_tree()
    target = _source_target(source_text)
    if _pins() != pins:
        raise ValueError("Intent source producer changed during reference preparation")
    return target


def _token_window(target):
    raw = source384._raw(target).decode()
    pieces = source384._TOKEN.findall(raw)
    if "".join(pieces) != raw:
        raise ValueError("native target has no exact lexical token encoding")
    # The source384 batching cap includes BOS/EOS. No model/context is enlarged.
    return {"lexical_tokens": len(pieces), "tokens_with_boundaries": len(pieces) + 2,
        "model_target_token_limit": MODEL_TARGET_TOKEN_LIMIT,
        "fits_current_model_window": len(pieces) + 2 <= MODEL_TARGET_TOKEN_LIMIT,
        "current_learned_decoder_coverage_demonstrated": False,
        "reference_is_model_output": False, "context_window_changed": False}


def audit_candidate(source_text, candidate):
    """Compare the entire original native candidate after target-free inference."""
    if type(source_text) is not str or len(source_text.encode()) > fidelity.MAX_BYTES:
        raise ValueError("bounded original source string required")
    before = fidelity._json_input(candidate)
    original = deepcopy(candidate)
    pins = _pins()
    resolved_tree = tree_pin.require_workspace_logic_tree()
    native_error = source_error = None
    try:
        if type(original) is not dict or set(original) != {"kind", "document"} or original["kind"] != "document":
            raise ValueError("closed complete native document envelope required")
        native = decoder.decode_intent_ir(original["document"])
        if fidelity._differences(native.to_dict(), original["document"]):
            raise ValueError("complete canonical native records required without omitted fields")
        source384.validate_target("intent_ir", original)
    except (ValueError, TypeError, KeyError) as error:
        native_error = str(error)
    reference = None
    try:
        reference = _source_target(source_text)
    except (ValueError, TypeError, KeyError) as error:
        source_error = str(error)
    differences = None if reference is None else fidelity._differences(reference, original)
    status = ("native_invalid" if native_error is not None else "source_unsupported" if source_error is not None
              else "source_disagreement" if differences else "source_agreement")
    result = {"schema": SCHEMA, "domain_id": "intent_ir", "status": status,
        "source_text": source_text, "source_sha256": fidelity._sha(source_text.encode()),
        "candidate": original, "candidate_sha256": fidelity._sha(before),
        "source_reference": reference, "differences": differences,
        "native_error": native_error, "source_error": source_error,
        "reference_scope": "complete_bounded_source_contract_not_general_language_semantics",
        "source_fidelity_check_required": True, "continue_planning": True,
        "target_window": _token_window(reference) if reference is not None else None,
        "resolved_logic_tree": resolved_tree, "producer_pins": pins,
        "owner_pin_scope": "direct_owners_not_transitive_callgraph", **FALSE}
    result["audit_sha256"] = core._sha(result)
    if _pins() != pins or fidelity._json_input(candidate) != before:
        raise ValueError("Intent source owner or candidate changed during audit")
    return result


def prepare_family_targets(source_text, candidate, requested_families=None, *, context=None,
                           guarded_effect_bindings=None):
    """Forward an unchanged source-agreeing document to existing v7 owners.

    All forty families remain requested. Finite execution interpretations are
    accepted only as explicit typed caller inputs after source agreement.
    Missing family support stays missing; this is not a Lake admission.
    """
    source_audit = audit_candidate(source_text, candidate)
    if source_audit["status"] != "source_agreement":
        raise ValueError("Intent source agreement required: " + source_audit["status"])
    pins = _pins()
    full_floor = sorted(core.REQUIREMENTS)
    if requested_families is not None and (type(requested_families) not in (list, tuple)
            or any(type(item) is not str for item in requested_families)
            or sorted(requested_families) != full_floor):
        raise ValueError("complete forty-family request required; narrowing is not coverage")
    inputs = {"document": deepcopy(candidate["document"]), "source_text": source_text,
              "requested_families": full_floor}
    if context is not None:
        if (type(context) is not dict or set(context) != {"state"}
                or type(context["state"]) is not dict
                or not {"max_steps", "workflow"} <= set(context["state"])
                or set(context["state"]) - {"max_steps", "workflow", "abstraction"}):
            raise ValueError("closed explicit finite state context required")
        if guarded_effect_bindings is None:
            raise ValueError("explicit finite context requires paired typed effect bindings")
        fidelity._json_input(context)
        inputs["context"] = deepcopy(context)
    if guarded_effect_bindings is not None:
        if context is None or type(guarded_effect_bindings) is not training.IntentEffectBindings:
            raise ValueError("typed effect bindings require explicit finite context")
        inputs["guarded_effect_bindings"] = guarded_effect_bindings
    report = training.prepare_family_training_targets_v7("intent_ir", **inputs)
    available = sorted({row["logic_family"] for row in report["projections"] if row["ready_for_training"]})
    audit = {"schema": SCHEMA, "status": "projected_candidate", "domain_id": "intent_ir",
        "candidate": deepcopy(candidate), "source_agreement_audit": source_audit,
        "source_sha256": source_audit["source_sha256"], "candidate_sha256": source_audit["candidate_sha256"],
        "projection_scope": "existing_native_family_owners_with_explicit_source_records",
        "source_text_to_formula_inference": False, "candidate_to_formula_compilation": True,
        "explicit_finite_context_supplied": context is not None,
        "explicit_effect_bindings_supplied": guarded_effect_bindings is not None,
        "context_is_declared_interpretation_not_observed_truth": True,
        "requested_families": full_floor, "available_families": available,
        "missing_requested_families": sorted(set(full_floor) - set(available)),
        "target_window": source_audit["target_window"], "continue_planning": True,
        "family_report_sha256": report["report_sha256"], "family_source_digest": report["source_digest"],
        "producer_pins": pins, "owner_pin_scope": "direct_owners_not_transitive_callgraph", **FALSE}
    audit["audit_sha256"] = core._sha(audit)
    if _pins() != pins or fidelity._sha(fidelity._json_input(candidate)) != source_audit["candidate_sha256"]:
        raise ValueError("Intent source owner or candidate changed during projection preparation")
    return {"report": report, "source_inputs": inputs, "audit": audit}


def validate_prepared(prepared, source_text, candidate):
    """Replay source, full original document, explicit context and all targets."""
    if type(prepared) is not dict or set(prepared) != {"report", "source_inputs", "audit"}:
        raise ValueError("closed prepared Intent source envelope required")
    inputs = prepared["source_inputs"]
    if type(inputs) is not dict or set(inputs) - {"document", "source_text", "requested_families", "context",
                                                "guarded_effect_bindings"}:
        raise ValueError("closed prepared source inputs required")
    expected = prepare_family_targets(source_text, candidate, inputs.get("requested_families"),
        context=inputs.get("context"), guarded_effect_bindings=inputs.get("guarded_effect_bindings"))
    if core._wire(core._json(expected)) != core._wire(core._json(prepared)):
        raise ValueError("Intent source/candidate/context/full family replay differs")
    return True


__all__ = ["source_target", "audit_candidate", "prepare_family_targets", "validate_prepared"]

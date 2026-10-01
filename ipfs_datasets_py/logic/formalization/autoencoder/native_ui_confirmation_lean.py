"""Source-bound, caller-supplied UI request/token confirmation semantics.

This profile observes a finite event prefix. It cannot infer confirmation
semantics from the native ``before`` string, attest events or establish consent.
The original complete formula partition is retained and exhaustively joined.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from . import native_family_lean_emitters as old
from . import native_qualified_lean as qualified
from ...ir_core.provenance import SourceRef

EVIDENCE_SCHEMA = "ui-confirmation-interpretation/v1"
PAYLOAD_SCHEMA = "ui-request-token-confirmation-projection/v1"
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
require, string, digest = old.require, old.string, qualified.digest
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:/-]{0,255}")
_COMMON = {"formula_index", "original_formula_sha256", "kind"}
_POLICY = {
    "event_order": "strict_sequence_position",
    "time_domain": "discrete_nat_ticks",
    "clock_order": "nondecreasing",
    "freshness_upper_inclusive": True,
    "correlation": "action_request_token",
    "cancellation": "since_latest_confirmation",
    "consumption": "every_prior_invocation_consumes_token",
    "trace_scope": "finite_observed_prefix",
    "unobserved_future": "unknown",
}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _guard():
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
            "UI_confirmation_producer_changed")
    qualified._guard()


def _evidence(value):
    require(type(value) is dict and value.get("schema") == EVIDENCE_SCHEMA,
            "UI_confirmation_interpretation_schema_required")
    compatible = dict(value, schema=qualified.EVIDENCE_SCHEMA)
    qualified._evidence(compatible)


@dataclass(frozen=True, slots=True)
class UIConfirmationInterpretation:
    """Immutable explicit declaration; views are independent JSON copies."""
    _bytes: bytes

    def __post_init__(self):
        require(type(self._bytes) is bytes and len(self._bytes) <= 262144,
                "bounded_UI_confirmation_interpretation_required")
        value = json.loads(self._bytes)
        _evidence(value)
        require(_wire(value) == self._bytes, "canonical_UI_confirmation_bytes_required")

    @classmethod
    def from_dict(cls, value):
        return cls(_wire(value))

    def to_dict(self):
        return json.loads(self._bytes)

    @property
    def sha256(self):
        return hashlib.sha256(self._bytes).hexdigest()


# Finite, decidable safety observations. Nat is event position; event.tick is
# an explicitly declared clock. Tied clocks do not erase distinct invocations.
LEAN_SEMANTICS = '''
inductive UIConfirmationKind where
  | confirm | invoke | cancel
  deriving DecidableEq, Repr
structure UIConfirmationEvent (Entity : Type) where
  kind : UIConfirmationKind
  action : Entity
  request : Entity
  token : Entity
  tick : Nat
  deriving DecidableEq, Repr

def uiSameKey {Entity : Type} [DecidableEq Entity]
    (left right : UIConfirmationEvent Entity) : Bool :=
  decide (left.action = right.action ∧ left.request = right.request ∧ left.token = right.token)

def uiClockOrdered {Entity : Type} (events : List (UIConfirmationEvent Entity))
    (origin : Nat) : Bool :=
  events.zipIdx.all fun left => events.zipIdx.all fun right =>
    if origin ≤ left.2 ∧ left.2 ≤ right.2 then decide (left.1.tick ≤ right.1.tick) else true

def uiValidConfirmation {Entity : Type} [DecidableEq Entity]
    (events : List (UIConfirmationEvent Entity)) (origin position maxAge : Nat)
    (invocation : UIConfirmationEvent Entity) : Bool :=
  events.zipIdx.any fun confirmation =>
    decide (origin ≤ confirmation.2 ∧ confirmation.2 < position ∧
      confirmation.1.kind = .confirm ∧ confirmation.1.tick ≤ invocation.tick ∧
      invocation.tick ≤ confirmation.1.tick + maxAge) &&
    uiSameKey confirmation.1 invocation &&
    (events.zipIdx.all fun cancellation =>
      if confirmation.2 < cancellation.2 ∧ cancellation.2 < position ∧
          cancellation.1.kind = .cancel then !(uiSameKey cancellation.1 invocation) else true) &&
    (events.zipIdx.all fun prior =>
      if origin ≤ prior.2 ∧ prior.2 < position ∧ prior.1.kind = .invoke
      then !(uiSameKey prior.1 invocation) else true)

def uiObservedPolicy {Entity : Type} [DecidableEq Entity]
    (events : List (UIConfirmationEvent Entity)) (action : Entity) (maxAge origin : Nat) : Bool :=
  events.zipIdx.all fun occurrence =>
    if origin ≤ occurrence.2 ∧ occurrence.1.kind = .invoke ∧ occurrence.1.action = action
    then uiValidConfirmation events origin occurrence.2 maxAge occurrence.1 else true

def uiObservedViolation {Entity : Type} [DecidableEq Entity]
    (events : List (UIConfirmationEvent Entity)) (action : Entity) (maxAge origin : Nat) : Bool :=
  !(uiObservedPolicy events action maxAge origin)

-- A checked clock is required separately from the deontic policy. Neither
-- condition establishes event authenticity or facts about an unobserved future.
def uiPrefixWellFormed {Entity : Type} (events : List (UIConfirmationEvent Entity))
    (origin : Nat) : Prop := origin ≤ events.length ∧ uiClockOrdered events origin = true
'''


def _render(original, evidence, expected_source):
    require(original["projection_id"] == "ui_ux_ir:tdfol" and original["logic_family"] == "tdfol"
            and original["profile"] == "ui-tdfol-compilation/v1", "exact_native_UI_TDFOL_route_required")
    payload = original["payload"]
    qualified._closed(payload, {"formulas"}, "UI_confirmation_payload")
    formulas = qualified._list(payload["formulas"], "UI_confirmation_formulas")
    require(len(formulas) == len(evidence["formulas"]), "exhaustive_UI_confirmation_interpretation_required")
    lines, policies, action_policies = [LEAN_SEMANTICS], [], {}
    for index, (formula, declaration) in enumerate(zip(formulas, evidence["formulas"])):
        require(declaration["original_formula_sha256"] == digest(formula), "original_UI_formula_digest_differs")
        qualified._closed(formula, {"operator", "proposition", "strength", "source_ref_ids"}, "UI_confirmation_norm")
        require(formula["operator"] in {"obligation", "permission", "prohibition"}
                and formula["strength"] in {"strict", "weak"}, "native_UI_modality_and_strength_required")
        refs = qualified._list(formula["source_ref_ids"], "UI_confirmation_source_refs", bound=16)
        require(all(type(ref) is str and _ID.fullmatch(ref) for ref in refs) and len(set(refs)) == len(refs),
                "exact_native_UI_source_identifiers_required")
        if declaration["kind"] == "atomic_UI_norm":
            body, operators = qualified._ui_formula(formula, declaration, expected_source)
            lines.append(f"def uiConfirmationFormula_{index} {{Entity Agent : Type}} [DecidableEq Entity] "
                "(i : Interpretation Entity Agent) (_events : List (UIConfirmationEvent Entity)) : Nat → Prop := " + body)
            policies.extend(operators)
        else:
            qualified._closed(declaration, _COMMON | set(_POLICY) | {"action_id", "policy", "max_age_ticks"},
                              "UI_request_token_policy")
            require(declaration["kind"] == "UI_request_token_confirmation_policy", "explicit_UI_request_token_policy_required")
            require(all(type(declaration[key]) is type(value) and declaration[key] == value
                        for key, value in _POLICY.items()), "unsupported_UI_request_token_policy_semantics")
            action = declaration["action_id"]
            require(type(action) is str and _ID.fullmatch(action), "bounded_UI_policy_action_required")
            age = declaration["max_age_ticks"]
            require(type(age) is int and 1 <= age <= 1000000, "positive_bounded_UI_freshness_required")
            action_policy = {key: declaration[key] for key in (*_POLICY, "max_age_ticks")}
            require(action not in action_policies or action_policies[action] == action_policy,
                    "inconsistent_UI_confirmation_policy_for_same_action")
            action_policies[action] = action_policy
            policy = declaration["policy"]
            if policy == "every_invocation_has_valid_confirmation":
                require(formula["operator"] == "obligation" and formula["proposition"] ==
                        f"confirm({action}) before invoke({action})", "UI_confirm_obligation_literal_differs")
                predicate = "uiObservedPolicy"
            elif policy == "unconfirmed_invocation":
                require(formula["operator"] == "prohibition" and formula["proposition"] ==
                        f"invoke({action}) before confirm({action})", "UI_confirm_prohibition_literal_differs")
                predicate = "uiObservedViolation"
            else:
                raise old.UnsupportedNativeLean("unknown_UI_request_token_policy")
            modality = "O" if formula["operator"] == "obligation" else "F"
            body = "(fun origin => " + predicate + " events (i.constant " + string(action) + ") " + str(age) + " origin = true)"
            lines.append(f"def uiConfirmationFormula_{index} {{Entity Agent : Type}} [DecidableEq Entity] "
                "(i : Interpretation Entity Agent) (events : List (UIConfirmationEvent Entity)) : Nat → Prop := "
                + "i.modal " + string("deontic:" + modality) + " [] (some " + string("UI-strength:" + formula["strength"]) + ") " + body)
            policies.append(policy)
        lines.append(f"def uiConfirmationSources_{index} : String := " + string(_wire(refs).decode()))
        lines.append(f"def uiConfirmationCheckedFormula_{index} {{Entity Agent : Type}} [DecidableEq Entity] "
            "(i : Interpretation Entity Agent) (events : List (UIConfirmationEvent Entity)) (origin : Nat) : Prop := "
            f"uiPrefixWellFormed events origin ∧ uiConfirmationFormula_{index} i events origin")
    require(any(p in {"every_invocation_has_valid_confirmation", "unconfirmed_invocation"} for p in policies),
            "UI_confirmation_profile_requires_a_qualified_formula")
    return "\n".join(lines), policies


def prepare_ui_confirmation_payload(row, evidence, *, expected_source_ref):
    """Bind caller semantics to the original replayed complete UI projection."""
    _guard()
    require(type(evidence) is UIConfirmationInterpretation and type(expected_source_ref) is SourceRef,
            "immutable_UI_interpretation_and_actual_source_required")
    expected_source_ref.validate()
    value = evidence.to_dict()
    require(value["source_ref"] == expected_source_ref.to_dict(), "UI_confirmation_source_ref_differs")
    require(type(row) is dict and {"projection_id", "source_digest", "logic_family", "profile", "payload"} <= set(row),
            "complete_original_UI_projection_required")
    require(value["original_projection_id"] == row["projection_id"]
            and value["original_source_digest"] == row["source_digest"]
            and value["original_payload_sha256"] == digest(row["payload"]), "UI_confirmation_original_binding_differs")
    original = {key: row[key] for key in ("projection_id", "source_digest", "logic_family", "profile", "payload")}
    require(len(_wire(original)) <= 262144, "bounded_original_UI_projection_required")
    _render(original, value, expected_source_ref)
    payload = {"schema": PAYLOAD_SCHEMA, "original": original, "interpretation": value,
               "interpretation_sha256": evidence.sha256, "source_semantics_verified": False,
               "source_text_inference_executed": False, "admitted": False}
    return {"projection_id": row["projection_id"] + "/request-token-confirmation/v1", "logic_family": "tdfol",
        "profile": "explicit_ui_request_token_confirmation/v1", "payload": json.loads(_wire(payload)),
        "producer_id": __name__, "producer_pins": {__name__: _SOURCE_SHA, qualified.__name__: qualified._SOURCE_SHA},
        "qualification_gaps": ["caller_policy_not_source_fidelity", "actual_Lake_execution_required",
            "event_occurrences_not_attested", "clock_well_formedness_not_assumed_true",
            "finite_prefix_not_complete_workflow", "native_confirmation_class_and_risk_translation_not_verified"]}


def emit_projection(row, *, report=None):
    payload = row.get("payload")
    if type(payload) is not dict or payload.get("schema") != PAYLOAD_SCHEMA:
        raise NotImplementedError
    _guard()
    qualified._closed(payload, {"schema", "original", "interpretation", "interpretation_sha256",
        "source_semantics_verified", "source_text_inference_executed", "admitted"}, "UI_confirmation_projection")
    require(all(payload[key] is False for key in ("source_semantics_verified", "source_text_inference_executed", "admitted")),
            "UI_confirmation_cannot_assert_source_fidelity_or_admission")
    qualified._closed(payload["original"], {"projection_id", "source_digest", "logic_family", "profile", "payload"},
                      "original_UI_confirmation_projection")
    evidence = UIConfirmationInterpretation.from_dict(payload["interpretation"])
    source = qualified._source(evidence.to_dict()["source_ref"])
    expected = prepare_ui_confirmation_payload(payload["original"], evidence, expected_source_ref=source)
    require(all(row.get(key) == expected[key] for key in ("projection_id", "logic_family", "profile", "payload")),
            "UI_confirmation_projection_replay_differs")
    code, policies = _render(payload["original"], evidence.to_dict(), source)
    return code, {"validator": "exact_UI_source_formula_and_request_token_policy_replay",
        "operators": policies, "payload_sha256": digest(payload), "interpretation_sha256": evidence.sha256,
        "capability_floor_eligible": False, "source_semantics_verified": False,
        "source_text_inference_executed": False, "runtime_authority_granted": False,
        "event_occurrences_attested": False, "admitted": False,
        "semantics_scope": "caller_interpretation_of_finite_observed_UI_prefix",
        "assumptions": [
            "Caller supplies the policy. Exact source/record hashes do not prove interpretation fidelity.",
            "Finite sequence positions distinguish repeated same-tick events. Future events are unknown.",
            "Clock well-formedness is a separate proposition; a definition never establishes it.",
            "An inclusive maximum age uses caller-defined Nat ticks, not an attested real clock.",
            "Confirmation and cancellation correlate by action/request/token; every earlier invocation since origin consumes that key.",
            "Origin is an event-sequence position. Before-origin confirmations, cancellations and token consumption are excluded; this is not lifetime token uniqueness.",
            "A later confirmation can clear cancellation but cannot revive a consumed token within the origin window.",
            "Source confirmation classes (consent/double-confirm) and destructive-risk behavior are not inferred from flattened native formulas.",
            "Atomic weak permissions and strict prohibitions remain exactly as emitted; they are never upgraded to confirmation requirements.",
            "No event authenticity, consent, authorization, completed workflow or source norm truth is asserted."],
        "missing_capabilities": ["independent_source_fidelity", "all_named_logic_family_floor_evidence",
            "consent_and_double_confirmation_source_interpretation", "infinite_future_behavior"]}


__all__ = ["UIConfirmationInterpretation", "prepare_ui_confirmation_payload", "emit_projection", "digest"]

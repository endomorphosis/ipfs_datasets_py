"""Ground ProtocolIR declarations and conditional finite-trace queries in Lean.

The input supplies no role processes. Accordingly the generated queries take
an explicit set of permitted traces and trust-premise interpretation; compiling
them proves neither those premises nor protocol security. Unsupported claim or
algebra fields reject the whole projection, rather than disappearing from it.
"""
from __future__ import annotations

import hashlib
import json

from ...software_verification.protocol import ProtocolIR
from .native_family_lean_emitters import UnsupportedNativeLean, require, string

PROFILE = "native-ground-protocol-lean/v1"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _strings(values):
    return "[" + ", ".join(string(value) for value in values) + "]"


def _terms(values):
    return "[" + ", ".join(_term(value) for value in values) + "]"


def _term(value, depth=0):
    require(depth <= 24, "protocol_term_depth_exceeded")
    sort = string(value["sort"])
    if value["function_id"]:
        return "(.app " + sort + " " + string(value["function_id"]) + " [" + ", ".join(
            _term(item, depth + 1) for item in value["arguments"]) + "])"
    kind = "atom" if value["symbol_id"] else "literal"
    return "(." + kind + " " + sort + " " + string(value["symbol_id"] or value["literal"]) + ")"


def _validate(payload, *, allow_equivalence=False):
    require(type(payload) is dict and len(_json(payload).encode()) <= 128 * 1024,
            "bounded_native_protocol_document_required")
    try:
        native = ProtocolIR.from_dict(payload)
    except (TypeError, ValueError, KeyError) as error:
        raise UnsupportedNativeLean("invalid_native_protocol:" + str(error)) from error
    require(native.to_dict() == payload, "exact_native_protocol_roundtrip_required")
    for key in ("roles", "variables", "keys", "fresh_names", "functions", "channels", "messages",
                "rewrite_facts", "events", "claims", "trust_assumptions", "sorts"):
        require(len(payload[key]) <= 64, "bounded_protocol_declarations_required:" + key)
    require(payload["claims"], "nonempty_protocol_queries_required")
    require(allow_equivalence or not any(row["kind"] == "equivalence" for row in payload["claims"]),
            "protocol_observational_equivalence_requires_explicit_process_or_frame_semantics")
    require(set(payload["equational_theories"]) <= {"free", "symmetric_encryption"},
            "protocol_algebra_requires_dedicated_lowering")
    require(set(payload["metadata"]) <= {"protocol", "version"},
            "protocol_metadata_semantics_not_lowered")
    if "protocol" in payload["metadata"]:
        require(type(payload["metadata"]["protocol"]) is str, "protocol_metadata_name_required")
    if "version" in payload["metadata"]:
        require(type(payload["metadata"]["version"]) in (str, int), "protocol_metadata_version_required")
    require(not payload["adversary"]["compromised_role_ids"],
            "protocol_role_compromise_requires_local_state_semantics")
    require(not any(row["assumption_ids"] for row in payload["channels"]),
            "protocol_conditional_channel_guarantees_require_additional_semantics")
    variables = {row["variable_id"] for row in payload["variables"]}

    def visit(value):
        if type(value) is dict:
            if set(value) == {"arguments", "function_id", "literal", "sort", "symbol_id"}:
                require(value["symbol_id"] not in variables,
                        "protocol_variable_terms_require_session_substitution_semantics")
                _term(value)
            for child in value.values():
                visit(child)
        elif type(value) is list:
            for child in value:
                visit(child)
    visit(payload)
    events = {row["event_id"]: row for row in payload["events"]}
    for claim in payload["claims"]:
        if claim["kind"] in ("authentication", "correspondence"):
            require(len(claim["antecedent_event_ids"]) == len(claim["consequent_event_ids"]) == 1,
                    "protocol_multi_event_correspondence_requires_matching_semantics")
            left, right = (events[claim[key][0]]["parameters"] for key in
                           ("antecedent_event_ids", "consequent_event_ids"))
            require(left == right, "protocol_correspondence_parameter_binding_requires_interpretation")
    symmetric = [row for row in payload["functions"] if row["theory"] == "symmetric_encryption"]
    encrypt = [row for row in symmetric if row["kind"] == "constructor"]
    decrypt = [row for row in symmetric if row["kind"] == "destructor"]
    if "symmetric_encryption" in payload["equational_theories"]:
        require(len(encrypt) == len(decrypt) == 1,
                "protocol_symmetric_algebra_requires_unambiguous_constructor_destructor_pair")
        e, d = encrypt[0], decrypt[0]
        require(len(e["parameter_sorts"]) == len(d["parameter_sorts"]) == 2
                and d["parameter_sorts"] == [e["result_sort"], e["parameter_sorts"][1]]
                and d["result_sort"] == e["parameter_sorts"][0],
                "protocol_symmetric_algebra_signature_mismatch")
        require(next(row for row in payload["sorts"] if row["sort_id"] == e["parameter_sorts"][1])["kind"] == "key",
                "protocol_symmetric_algebra_key_sort_required")
    require(not any(row["kind"] == "destructor" and row["theory"] == "free"
                    for row in payload["functions"]),
            "protocol_free_destructor_evaluation_requires_explicit_semantics")
    return native, (encrypt[0], decrypt[0]) if encrypt else None


PRELUDE = '''set_option linter.unusedVariables false
inductive Term where
  | atom : String → String → Term
  | literal : String → String → Term
  | app : String → String → List Term → Term
  deriving Repr
def termSort : Term → String
  | .atom sort _ => sort
  | .literal sort _ => sort
  | .app sort _ _ => sort
structure Message where
  identifier : String
  sender : String
  receivers : List String
  channel : String
  payload : Term
  deriving Repr
structure Event where
  identifier : String
  role : String
  phase : String
  parameters : List Term
  deriving Repr
inductive Step where
  | event : String → Step
  | send : String → Step
  | inject : String → Term → Step
  | drop : String → Step
  | replay : String → Step
  deriving Repr
abbrev Trace := List Step
def eventOccurs (trace : Trace) (identifier : String) : Prop := Step.event identifier ∈ trace
def eventAt (trace : Trace) (identifier : String) (position : Nat) : Prop :=
  trace[position]? = some (.event identifier)
'''


def emit_protocol(payload, *, interpretation=None):
    """Return semantic definitions for an exact native ProtocolIR dictionary."""
    native, symmetric = _validate(payload, allow_equivalence=interpretation is not None)
    has_frames = any(row["kind"] == "equivalence" for row in payload["claims"])
    require(interpretation is None or has_frames, "protocol_static_interpretation_has_no_equivalence_claim")
    lines = [PRELUDE]
    # Every source/declaration/observation remains visible for provenance. The
    # operational and query definitions below, rather than this record, are the
    # semantic lowering. Version/name metadata and observations have no axioms.
    lines.append("def retainedProtocolJSON : String := " + string(_json(payload)))
    capabilities = payload["adversary"]["capabilities"]
    lines.append("def capabilities : List String := " + _strings(capabilities))
    lines.append("def hasCapability (name : String) : Bool := capabilities.contains name")
    lines.append("def compromisedKeys : List String := " + _strings(payload["adversary"]["compromised_key_ids"]))
    for key in ("roles", "variables", "sorts", "fresh_names", "keys"):
        # These type/ownership declarations constrain the native parser. They
        # do not imply that a process executes or that a participant is honest.
        lines.append("def " + key + "Declarations : String := " + string(_json(payload[key])))
    message_rows = []
    for row in payload["messages"]:
        message_rows.append("⟨" + ", ".join((string(row["message_id"]), string(row["sender_role_id"]),
            _strings(row["receiver_role_ids"]), string(row["channel_id"]), _term(row["payload"]))) + "⟩")
    lines.append("def messages : List Message := [" + ", ".join(message_rows) + "]")
    lines.append("def message (identifier : String) : Option Message := messages.find? fun m => m.identifier == identifier")
    event_rows = ["⟨" + ", ".join((string(row["event_id"]), string(row["role_id"]), string(row["phase"]),
                                   _terms(row["parameters"]))) + "⟩" for row in payload["events"]]
    lines.append("def events : List Event := [" + ", ".join(event_rows) + "]")
    lines.append("def eventDeclared (identifier : String) : Bool := events.any fun e => e.identifier == identifier")
    observe, inject, replay, control = [], [], [], []
    for channel in payload["channels"]:
        key = channel["channel_id"]
        access, security = channel["adversary_access"], channel["security"]
        if access in ("observe", "control") and security not in ("confidential", "secure"):
            observe.append(key)
        if access in ("inject", "control") and security not in ("authenticated", "secure"):
            inject.append(key)
        if access in ("inject", "control") and security != "secure":
            replay.append(key)
        if access == "control":
            control.append(key)
    for name, values in (("observableChannels", observe), ("injectableChannels", inject),
                         ("replayableChannels", replay), ("controlledChannels", control)):
        lines.append("def " + name + " : List String := " + _strings(values))
    lines += ['''def visible (channel : String) : Bool := hasCapability "intercept" && observableChannels.contains channel
def observedStep : Step → List Term
  | .event _ => []
  | .drop _ => []
  | .send identifier | .replay identifier => match message identifier with
    | some m => if visible m.channel then [m.payload] else []
    | none => []
  | .inject channel value => if visible channel then [value] else []
def observed (trace : Trace) : List Term := trace.flatMap observedStep
''']
    lines.append("def initialKnowledge : List Term := " + _terms([row["term"] for row in payload["adversary"]["knowledge"]
                                                               if not row["available_after_event_ids"]] +
        [{"sort": row["sort"], "symbol_id": row["key_id"], "function_id": "", "literal": "", "arguments": []}
         for row in payload["keys"] if row["key_id"] in payload["adversary"]["compromised_key_ids"] or
         (row["kind"] == "public" and payload["adversary"]["kind"] != "none")]))
    conditional = []
    for row in payload["adversary"]["knowledge"]:
        if row["available_after_event_ids"]:
            condition = " ∧ ".join("eventOccurs trace " + string(key) for key in row["available_after_event_ids"])
            conditional.append("(value = " + _term(row["term"]) + " ∧ " + condition + ")")
    lines.append("def conditionallyKnown (trace : Trace) (value : Term) : Prop := " + (" ∨ ".join(conditional) or "False"))
    lines.append("def functionAllowed (kind function result : String) (arguments : List Term) : Prop := " + (" ∨ ".join(
        "(kind = " + string(row["kind"]) + " ∧ function = " + string(row["function_id"]) + " ∧ result = "
        + string(row["result_sort"]) + " ∧ arguments.map termSort = " + _strings(row["parameter_sorts"]) + ")"
        for row in payload["functions"]) or "False"))
    lines += ["inductive Reduces : Term → Term → Prop where"]
    for index, row in enumerate(payload["rewrite_facts"]):
        lines.append("  | declared_" + str(index) + " : Reduces " + _term(row["left"]) + " " + _term(row["right"]))
    if symmetric:
        e, d = symmetric
        encrypted = "(.app " + string(e["result_sort"]) + " " + string(e["function_id"]) + " [plain, key])"
        decrypted = "(.app " + string(d["result_sort"]) + " " + string(d["function_id"]) + " [" + encrypted + ", key])"
        lines.append("  | symmetric (plain key : Term) : termSort plain = " + string(e["parameter_sorts"][0])
                     + " → termSort key = " + string(e["parameter_sorts"][1]) + " → Reduces " + decrypted + " plain")
    lines += ['''  | context (sort function : String) (before after : List Term) (left right : Term) :
      Reduces left right →
      Reduces (.app sort function (before ++ left :: after)) (.app sort function (before ++ right :: after))
inductive Knows (trace : Trace) : Term → Prop where
  | initial (value : Term) : value ∈ initialKnowledge → Knows trace value
  | conditional (value : Term) : conditionallyKnown trace value → Knows trace value
  | observe (value : Term) : value ∈ observed trace → Knows trace value
  | compose (function result : String) (arguments : List Term) :
      hasCapability "compose" = true → functionAllowed "constructor" function result arguments →
      (∀ value, value ∈ arguments → Knows trace value) → Knows trace (.app result function arguments)
  | decompose (function result : String) (arguments : List Term) (output : Term) :
      hasCapability "decompose" = true → functionAllowed "destructor" function result arguments →
      (∀ value, value ∈ arguments → Knows trace value) →
      Reduces (.app result function arguments) output → Knows trace output
  | reduction (left right : Term) : Knows trace left → Reduces left right → Knows trace right
def previouslySent (trace : Trace) (identifier : String) : Prop :=
  Step.send identifier ∈ trace ∨ Step.replay identifier ∈ trace
def validStep (history : Trace) : Step → Prop
  | .event identifier => eventDeclared identifier = true
  | .send identifier => (message identifier).isSome = true
  | .inject channel value => hasCapability "inject" = true ∧
      channel ∈ injectableChannels ∧ Knows history value
  | .drop identifier => ∃ m, message identifier = some m ∧ hasCapability "drop" = true ∧
      m.channel ∈ controlledChannels ∧ previouslySent history identifier
  | .replay identifier => ∃ m, message identifier = some m ∧ hasCapability "replay" = true ∧
      m.channel ∈ replayableChannels ∧ previouslySent history identifier
def validTrace (trace : Trace) : Prop :=
  ∀ history step suffix, trace = history ++ step :: suffix → validStep history step
structure ProtocolInterpretation where
  permitted : Trace → Prop
  trustPremise : String → Prop
def executions (i : ProtocolInterpretation) (trace : Trace) : Prop := i.permitted trace ∧ validTrace trace
def correspondence (trace : Trace) (antecedent consequent : String) : Prop :=
  ∀ position, eventAt trace antecedent position →
    ∃ earlier, earlier < position ∧ eventAt trace consequent earlier
def injectiveCorrespondence (trace : Trace) (antecedent consequent : String) : Prop :=
  ∃ matching : Nat → Nat,
    (∀ position, eventAt trace antecedent position → matching position < position ∧
      eventAt trace consequent (matching position)) ∧
    (∀ first second, eventAt trace antecedent first → eventAt trace antecedent second →
      matching first = matching second → first = second)
''']
    assumption_names = {}
    for index, row in enumerate(payload["trust_assumptions"]):
        name = "trust_" + str(index); assumption_names[row["assumption_id"]] = name
        # A caller must interpret the full source statement, not merely its ID.
        statement = _json({key: row[key] for key in ("assumption_id", "statement", "trusted_role_ids", "trusted_key_ids")})
        lines.append("def " + name + " (i : ProtocolInterpretation) : Prop := i.trustPremise " + string(statement)
            + " ∧ ∀ key, key ∈ " + _strings(row["trusted_key_ids"]) + " → key ∉ compromisedKeys")
    frame_details = None
    if has_frames:
        from .native_protocol_frames import emit_static_frames
        frame_source, frame_details = emit_static_frames(payload, interpretation)
        lines.append(frame_source)
    claim_names = {}
    for index, row in enumerate(payload["claims"]):
        name = "query_" + str(index); claim_names[row["claim_id"]] = name
        premise = " ∧ ".join(assumption_names[key] + " i" for key in row["assumption_ids"]) or "True"
        kind = row["kind"]
        if kind == "secrecy":
            body = "∀ trace, executions i trace → ∀ secret, secret ∈ " + _terms(row["secret_terms"]) + " → ¬ Knows trace secret"
        elif kind == "reachability":
            body = "∃ trace, executions i trace ∧ " + " ∧ ".join("eventOccurs trace " + string(event) for event in row["reachable_event_ids"])
        elif kind == "equivalence":
            body = frame_details["queries"][row["claim_id"]]
        else:
            operator = "injectiveCorrespondence" if row["correspondence"] == "injective" else "correspondence"
            body = "∀ trace, executions i trace → " + operator + " trace " + string(row["antecedent_event_ids"][0]) + " " + string(row["consequent_event_ids"][0])
        lines.append("def " + name + " (i : ProtocolInterpretation) : Prop := (" + premise + ") → (" + body + ")")
    lines += ["def protocolSecurityProved : Bool := false", "def roleProcessesVerified : Bool := false"]
    details = {"profile": PROFILE, "validator": "ProtocolIR.from_dict_exact_ground_symbolic_fragment",
        "payload_sha256": hashlib.sha256(_json(payload).encode()).hexdigest(),
        "operators": ["typed_ground_terms", "oriented_rewrite", "capability_gated_knowledge", "channel_visibility",
            "explicit_finite_trace_interpretation", "conditional_secrecy", "existential_reachability",
            "earlier_event_correspondence", "injective_occurrence_matching"],
        "query_definitions": claim_names, "retained_native_records": native.to_dict(),
        "assumptions": ["Ground symbolic single-instance declarations; role-variable substitution and replicated sessions require another lowering.",
            "Permitted finite traces and complete trust statements are explicit interpretation parameters; no role process is inferred.",
            "Message sends denote emission, not delivery; drop and replay denote permitted attacker actions, not delivery guarantees.",
            "Declared initial knowledge, public keys, conditional disclosures, compromised keys and observable sends seed adversary knowledge.",
            "Symmetric encryption uses the unique typed constructor/destructor pair and perfect-symbolic decryption, not computational cryptography.",
            "Queries are formulas, not asserted truths. Observational equivalence and other algebra families fail closed.",
            "Display metadata, source maps and observations are retained without becoming semantic assumptions."],
        "source_semantics_verified": False, "model_checker_executed": False, "protocol_security_verified": False,
        "role_processes_verified": False, "capability_floor_eligible": False, "admitted": False, "qualified": False}
    if frame_details is not None:
        details["profile"] = "native-ground-protocol-static-frame-lean/v2"
        details["static_frame_interpretation"] = frame_details
        details["operators"] += ["all_finite_observer_recipes", "static_frame_equivalence", "definedness_observation"]
        details["assumptions"] = [item for item in details["assumptions"]
            if not item.startswith("Queries are formulas, not asserted truths.")]
        details["assumptions"] += ["Queries are formulas, not asserted truths. Static-frame interpretation does not establish role-process equivalence.",
                                   *frame_details["assumptions"]]
    return "\n".join(lines) + "\n", details


__all__ = ["emit_protocol", "PROFILE"]

"""Protocol lowering preserves query meanings and explicit unsupported fields."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_protocol_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.software_verification.protocol import ProtocolIR
from tests.unit.logic.software_verification.test_protocol import _document


def rebuild(value):
    value = deepcopy(value)
    value.pop("document_id", None)
    return ProtocolIR.from_dict(value).to_dict()


def fixture():
    """Separately authored four-query fixture, never an emitter-side filter."""
    value = _document().to_dict()
    value["claims"] = [row for row in value["claims"] if row["kind"] != "equivalence"]
    value["metadata"]["protocol"] = "ground-four-query-projection-fixture"
    return rebuild(value)


def lake(source, extra=""):
    candidates = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not candidates:
        pytest.skip("Installed Lake unavailable; no download attempted")
    return _execute("set_option autoImplicit false\nnamespace Protocol\n" + source + "\n" + extra
                    + "\nend Protocol\n", "Protocol", candidates[-1], 30)


def test_original_five_query_fixture_remains_explicitly_blocked():
    with pytest.raises(UnsupportedNativeLean, match="observational_equivalence"):
        emit.emit_protocol(_document().to_dict())


def test_supported_fragment_has_real_definitions_and_no_proof_claim():
    source, details = emit.emit_protocol(fixture())
    assert set(details["query_definitions"]) == {
        "claim:secrecy", "claim:reachable", "claim:authentication", "claim:correspondence"}
    assert "inductive Knows" in source and "inductive Reduces" in source
    assert "matching first = matching second → first = second" in source
    assert "i.permitted trace ∧ validTrace trace" in source
    assert details["retained_native_records"] == fixture()
    for flag in ("source_semantics_verified", "protocol_security_verified", "model_checker_executed",
                 "role_processes_verified", "qualified", "admitted", "capability_floor_eligible"):
        assert details[flag] is False
    assert lake(source)["status"] == "passed"


ALGEBRA = '''
def nonce : Term := .atom "sort:nonce" "name:challenge"
def key : Term := .atom "sort:key" "key:session"
def cipher : Term := .app "sort:message" "function:encrypt" [nonce, key]
def plainExpression : Term := .app "sort:nonce" "function:decrypt" [cipher, key]
theorem decryption_reduces : Reduces plainExpression nonce :=
  Reduces.symmetric nonce key rfl rfl
theorem emitted_cipher_visible : Knows [.send "message:challenge"] cipher := by
  apply Knows.observe
  simp [observed, observedStep, message, messages, visible, hasCapability,
    capabilities, observableChannels, cipher, nonce, key]
theorem disclosure_with_key (hkey : Knows [.send "message:challenge"] key) :
    Knows [.send "message:challenge"] nonce := by
  apply Knows.decompose "function:decrypt" "sort:nonce" [cipher, key] nonce
  · decide
  · simp [functionAllowed, cipher, key, termSort]
  · intro value member
    simp only [List.mem_cons, List.not_mem_nil, or_false] at member
    rcases member with first | second
    · subst value; exact emitted_cipher_visible
    · subst value; exact hkey
  · exact decryption_reduces
'''


def test_actual_lake_checks_decryption_and_observation_semantics():
    source, _ = emit.emit_protocol(fixture())
    result = lake(source, ALGEBRA)
    assert result["status"] == "passed", result


def test_compromised_key_enables_actual_plaintext_disclosure():
    value = fixture()
    value["adversary"]["compromised_key_ids"] = ["key:session"]
    source, _ = emit.emit_protocol(rebuild(value))
    extra = ALGEBRA + '''
theorem compromise_discloses_nonce : Knows [.send "message:challenge"] nonce := by
  apply disclosure_with_key
  apply Knows.initial
  simp [initialKnowledge, key]
example (i : ProtocolInterpretation) : ¬ trust_0 i := by
  intro h
  have impossible := h.2 "key:session" (by simp)
  simp [compromisedKeys] at impossible
'''
    result = lake(source, extra)
    assert result["status"] == "passed", result


def test_nonobservable_channel_cannot_supply_ciphertext_observation():
    value = fixture()
    value["channels"][0].update(security="confidential", adversary_access="inject")
    source, _ = emit.emit_protocol(rebuild(value))
    result = lake(source, '''
example : observed [.send "message:challenge"] = [] := by
  simp [observed, observedStep, message, messages, visible, hasCapability,
    capabilities, observableChannels]
''')
    assert result["status"] == "passed", result


def test_authentication_blocks_fresh_injection_but_preserves_replay_power():
    value = fixture()
    value["channels"][0]["security"] = "authenticated"
    source, _ = emit.emit_protocol(rebuild(value))
    result = lake(source, '''
example (history : Trace) (value : Term) : ¬ validStep history (.inject "channel:network" value) := by
  simp [validStep, injectableChannels]
example : validStep [.send "message:challenge"] (.replay "message:challenge") := by
  simp [validStep, message, messages, hasCapability, capabilities, replayableChannels, previouslySent]
example : ¬ validStep [] (.replay "message:challenge") := by
  simp [validStep, previouslySent]
''')
    assert result["status"] == "passed", result


def test_removed_inject_capability_blocks_injection_despite_channel_access():
    value = fixture()
    value["adversary"]["capabilities"].remove("inject")
    # Native CONTROL requires the inject capability; OBSERVE is still public
    # but has no injection rights and the emitted capability test is retained.
    value["channels"][0]["adversary_access"] = "observe"
    source, _ = emit.emit_protocol(rebuild(value))
    result = lake(source, '''
example (history : Trace) (value : Term) : ¬ validStep history (.inject "channel:network" value) := by
  simp [validStep, hasCapability, capabilities]
''')
    assert result["status"] == "passed", result


def test_event_order_and_reachability_are_not_asserted_from_declarations():
    source, details = emit.emit_protocol(fixture())
    query = details["query_definitions"]["claim:reachable"]
    extra = '''
example : correspondence [.event "event:begin", .event "event:accept"] "event:accept" "event:begin" := by
  intro position antecedent
  cases position with
  | zero => simp [eventAt] at antecedent
  | succ rest =>
    cases rest with
    | zero => exact ⟨0, by decide, rfl⟩
    | succ rest => simp [eventAt] at antecedent
example : ¬ correspondence [.event "event:accept", .event "event:begin"] "event:accept" "event:begin" := by
  intro correspondenceHolds
  obtain ⟨earlier, impossible, _⟩ := correspondenceHolds 0 rfl
  exact Nat.not_lt_zero _ impossible
def noExecutions : ProtocolInterpretation := ⟨fun _ => False, fun _ => True⟩
example : ¬ QUERY noExecutions := by
  intro holds
  obtain ⟨trace, execution, _⟩ := holds True.intro
  exact execution.1
'''.replace("QUERY", query)
    result = lake(source, extra)
    assert result["status"] == "passed", result


def test_conditional_knowledge_waits_for_declared_events():
    value = fixture()
    value["adversary"]["knowledge"][0]["term"]["symbol_id"] = "key:session"
    value["adversary"]["knowledge"][0]["available_after_event_ids"] = ["event:accept"]
    source, _ = emit.emit_protocol(rebuild(value))
    result = lake(source, '''
example : conditionallyKnown [.event "event:accept"] (.atom "sort:key" "key:session") := by
  simp [conditionallyKnown, eventOccurs]
example (value : Term) : ¬ conditionallyKnown [] value := by
  simp [conditionallyKnown, eventOccurs]
''')
    assert result["status"] == "passed", result


def test_public_key_declaration_is_public_even_without_explicit_knowledge_row():
    value = fixture()
    value["adversary"]["knowledge"] = []
    source, _ = emit.emit_protocol(rebuild(value))
    result = lake(source, '''
example : Knows [] (.atom "sort:key" "key:initiator-public") := by
  apply Knows.initial
  simp [initialKnowledge]
''')
    assert result["status"] == "passed", result


def test_injective_correspondence_rejects_two_accepts_for_one_begin():
    source, _ = emit.emit_protocol(fixture())
    extra = '''
def twice : Trace := [.event "event:begin", .event "event:accept", .event "event:accept"]
theorem unique_begin (position : Nat) (h : eventAt twice "event:begin" position) : position = 0 := by
  cases position with
  | zero => rfl
  | succ rest =>
    cases rest with
    | zero => simp [eventAt, twice] at h
    | succ rest =>
      cases rest with
      | zero => simp [eventAt, twice] at h
      | succ rest => simp [eventAt, twice] at h
example : correspondence twice "event:accept" "event:begin" := by
  intro position antecedent
  cases position with
  | zero => simp [eventAt, twice] at antecedent
  | succ rest =>
    cases rest with
    | zero => exact ⟨0, by decide, rfl⟩
    | succ rest =>
      cases rest with
      | zero => exact ⟨0, by decide, rfl⟩
      | succ rest => simp [eventAt, twice] at antecedent
example : ¬ injectiveCorrespondence twice "event:accept" "event:begin" := by
  intro h
  obtain ⟨matching, prior, injective⟩ := h
  have first := prior 1 rfl
  have second := prior 2 rfl
  have same : matching 1 = matching 2 :=
    (unique_begin _ first.2).trans (unique_begin _ second.2).symm
  have contradiction : (1 : Nat) = 2 := injective 1 2 rfl rfl same
  exact (by decide : (1 : Nat) ≠ 2) contradiction
'''
    result = lake(source, extra)
    assert result["status"] == "passed", result


@pytest.mark.parametrize("change,reason", [
    (lambda p: p["equational_theories"].append("hashing"), "algebra_requires_dedicated"),
    (lambda p: p["metadata"].update(proven_secure=True), "metadata_semantics_not_lowered"),
    (lambda p: p["adversary"]["compromised_role_ids"].append("role:initiator"), "role_compromise"),
    (lambda p: p["channels"][0]["assumption_ids"].append("assumption:session-key"), "conditional_channel"),
    (lambda p: p["events"][0]["parameters"].__setitem__(0,
        {"sort": "sort:agent", "symbol_id": "variable:responder-peer", "function_id": "", "literal": "", "arguments": []}),
     "variable_terms_require_session"),
])
def test_unsupported_semantics_are_not_erased(change, reason):
    value = fixture()
    change(value)
    with pytest.raises(UnsupportedNativeLean, match=reason):
        emit.emit_protocol(rebuild(value))


def test_correspondence_does_not_drop_mismatching_event_operands():
    value = fixture()
    value["events"][0]["parameters"] = [value["adversary"]["knowledge"][0]["term"]]
    with pytest.raises(UnsupportedNativeLean, match="parameter_binding"):
        emit.emit_protocol(rebuild(value))


def test_multiple_correspondence_events_require_explicit_binding():
    value = fixture()
    value["claims"][0]["consequent_event_ids"].append("event:accept")
    with pytest.raises(UnsupportedNativeLean, match="multi_event_correspondence"):
        emit.emit_protocol(rebuild(value))


def test_payload_schema_and_content_identity_are_checked():
    value = fixture()
    value["metadata"]["protocol"] = "modified without recomputing identity"
    with pytest.raises(UnsupportedNativeLean, match="invalid_native_protocol"):
        emit.emit_protocol(value)
    value = fixture(); value["pretend_security_proof"] = True
    with pytest.raises(UnsupportedNativeLean, match="invalid_native_protocol"):
        emit.emit_protocol(value)


def test_authentication_and_correspondence_keep_distinct_occurrence_semantics():
    source, details = emit.emit_protocol(fixture())
    injective = details["query_definitions"]["claim:authentication"]
    ordinary = details["query_definitions"]["claim:correspondence"]
    assert "injectiveCorrespondence" in next(line for line in source.splitlines() if line.startswith("def " + injective + " "))
    assert "→ correspondence trace" in next(line for line in source.splitlines() if line.startswith("def " + ordinary + " "))
    value = fixture()
    value["claims"][0]["correspondence"] = "non_injective"
    changed, after = emit.emit_protocol(rebuild(value))
    assert after["payload_sha256"] != details["payload_sha256"]
    assert "→ correspondence trace" in next(line for line in changed.splitlines() if line.startswith("def " + injective + " "))


def test_rewrites_and_trust_statements_change_the_generated_meaning():
    source, details = emit.emit_protocol(fixture())
    value = fixture()
    value["rewrite_facts"][0]["right"] = {
        "sort": "sort:nonce", "symbol_id": "", "function_id": "", "literal": "different", "arguments": []}
    value["trust_assumptions"][0]["statement"] = "A different explicit trust premise."
    changed, new_details = emit.emit_protocol(rebuild(value))
    assert source != changed and details["payload_sha256"] != new_details["payload_sha256"]
    assert '.literal "sort:nonce" "different"' in next(line for line in changed.splitlines() if "| declared_0" in line)
    assert "A different explicit trust premise." in next(line for line in changed.splitlines() if "def trust_0" in line)

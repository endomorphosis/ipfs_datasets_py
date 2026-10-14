"""Source-bound caller interpretations and semantic counterexamples, no models."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_event_interpretation as event
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as proposer
from ipfs_datasets_py.logic.autoformal import legal_temporal_occurrence_provenance as occurrence
from ipfs_datasets_py.logic.legal_document import _clause_selector
from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula
from ipfs_datasets_py.logic.software_verification.trace import TraceIR, TraceKind


TEXT = "Registry shall retain records until receipt of notice."
MEANINGS = {"subject_source_span", "subject_source_text", "state_atom", "event_atom",
            "until_strength", "endpoint", "time_domain", "origin", "modal_scope"}


def inputs(text=TEXT, **kwargs):
    receipt = occurrence.build_occurrence_receipt(text, source_id="fictional-clause", **kwargs)
    proposal = proposer.propose(text)
    return receipt, proposal


def requests(receipt, proposal, text=TEXT, document=None):
    return event.build_interpretation_requests(receipt, proposal, source_text=text, document_text=document)


def declaration(inventory, text=TEXT, index=0, strength="weak"):
    result = deepcopy(inventory["requests"][index]["declaration_skeleton"])
    end = text.index(" until")
    result.update(subject_source_span={"char_start": 0, "char_end": end},
                  subject_source_text=text[:end], state_atom="records_retained", event_atom="notice_received",
                  until_strength=strength, endpoint="exclude_event_tick", time_domain="discrete_unbounded_nat",
                  origin="caller_supplied_evaluation_time", modal_scope="temporal_property_only")
    return result


def prepared(strength="weak"):
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal), strength=strength)
    return event.prepare_event_interpretation(receipt, proposal, supplied, source_text=TEXT)


def resign(value):
    value["receipt_sha256"] = event.digest({key: item for key, item in value.items() if key != "receipt_sha256"})
    return value


def test_unmatched_until_can_request_meaning_without_inventing_parser_occurrence():
    receipt, proposal = inputs()
    original = deepcopy((receipt, proposal))
    inventory = requests(receipt, proposal)
    assert len(inventory["requests"]) == len(proposal["proposals"]) == 1
    request = inventory["requests"][0]
    assert request["proposal_family"] == "until_event"
    assert request["status"] == "awaiting_caller_interpretation"
    assert request["parser_join"]["status"] == "unmatched"
    assert request["parser_join"]["occurrence_id"] is None
    assert request["temporal_source"]["source_text"] == "until receipt of notice"
    assert request["event_source"]["source_text"] == "receipt of notice"
    assert request["event_source"]["source_observation_id"]
    assert request["event_source"]["document_observation_id"]
    assert all(request["declaration_skeleton"][key] is None for key in MEANINGS)
    assert all(value is False for value in request["authority"].values())
    assert all(value is False for value in inventory["authority"].values())
    assert (receipt, proposal) == original
    with pytest.raises(ValueError, match="complete caller meaning"):
        event.prepare_event_interpretation(receipt, proposal, request["declaration_skeleton"], source_text=TEXT)


def test_inventory_retains_unsupported_deferred_and_cue_only_issues():
    text = (TEXT + " Registry shall file after receipt of notice. "
            "Registry shall wait until blue. The words \"until receipt of notice\" are quoted.")
    receipt, proposal = inputs(text)
    inventory = requests(receipt, proposal, text)
    assert len(inventory["requests"]) == len(proposal["proposals"])
    assert {row["status"] for row in inventory["requests"]} == {
        "awaiting_caller_interpretation", "unsupported_family", "excluded"}
    assert inventory["issues"] == proposal["issues"]
    assert inventory["issues"]
    assert inventory["excluded"]
    for index, request in enumerate(inventory["requests"]):
        assert all(request["declaration_skeleton"][key] is None for key in MEANINGS)
        if request["status"] != "awaiting_caller_interpretation":
            with pytest.raises(ValueError, match="unsupported or excluded"):
                event.prepare_event_interpretation(receipt, proposal,
                    declaration(inventory, text, index), source_text=text)


def test_repeated_text_has_distinct_request_and_event_observation_coordinates():
    text = TEXT + " " + TEXT
    receipt, proposal = inputs(text)
    inventory = requests(receipt, proposal, text)
    left, right = inventory["requests"]
    assert left["event_source"]["source_text"] == right["event_source"]["source_text"]
    assert left["request_id"] != right["request_id"]
    assert left["event_source"]["source_observation_id"] != right["event_source"]["source_observation_id"]
    assert left["event_source"]["document_observation_id"] != right["event_source"]["document_observation_id"]
    supplied = declaration(inventory, text)
    supplied["request_id"] = right["request_id"]
    with pytest.raises(ValueError, match="binding differs"):
        event.prepare_event_interpretation(receipt, proposal, supplied, source_text=text)


def test_repeated_document_clause_uses_physical_document_event_identity():
    document = TEXT + "\n" + TEXT
    results = []
    for start in (0, len(TEXT) + 1):
        receipt, proposal = inputs(document_text=document, document_id="doc", clause_start=start)
        results.append(requests(receipt, proposal, document=document)["requests"][0])
    left, right = results
    assert left["event_source"]["source_observation_id"] == right["event_source"]["source_observation_id"]
    assert left["event_source"]["document_observation_id"] != right["event_source"]["document_observation_id"]
    assert left["request_id"] != right["request_id"]


def test_unicode_normalized_whitespace_uses_validated_document_alignment():
    text = "Établissement shall retain records until receipt of notice."
    document = "Préface.\nÉtablissement  shall\nretain records until  receipt of notice.\nFin."
    start = document.index("Établissement")
    offsets = [0]
    for char in document:
        offsets.append(offsets[-1] + len(char.encode()))
    selector = _clause_selector(document, text, start, offsets, hashlib.sha256(document.encode()).hexdigest())
    receipt, proposal = inputs(text, document_text=document, document_id="document",
                              clause_start=start, clause_end=selector["end"], source_selector=selector)
    inventory = requests(receipt, proposal, text, document)
    request = inventory["requests"][0]
    assert request["temporal_source"]["document_text"] == "until  receipt of notice"
    assert request["temporal_source"]["source_text"] == "until receipt of notice"
    artifact = event.prepare_event_interpretation(receipt, proposal, declaration(inventory, text),
                                                   source_text=text, document_text=document)
    assert artifact["subject_source"]["document_text"] == "Établissement  shall\nretain records"
    assert artifact["event_source"]["document_span"]["char_start"] == document.index("receipt")
    with pytest.raises(ValueError):
        requests(receipt, proposal, text, document.replace("receipt", "delivery"))


@pytest.mark.parametrize("key,value", [
    ("until_strength", None), ("until_strength", "default"), ("until_strength", True),
    ("endpoint", "include_event_tick"), ("time_domain", "wall_clock_days"),
    ("origin", "first_actual_event"), ("modal_scope", "obligation"),
    ("state_atom", "records_retained) U injected"), ("state_atom", "until"),
    ("event_atom", "records_retained"), ("event_atom", ""),
])
def test_meaning_cannot_be_defaulted_or_silently_changed(key, value):
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal))
    supplied[key] = value
    with pytest.raises(ValueError):
        event.prepare_event_interpretation(receipt, proposal, supplied, source_text=TEXT)


@pytest.mark.parametrize("field", ["request_sha256", "source_id", "document_id", "source_text_sha256",
                                   "document_text_sha256", "occurrence_receipt_sha256", "proposal_receipt_sha256"])
def test_every_source_and_request_binding_is_checked(field):
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal))
    supplied[field] = "foreign"
    with pytest.raises(ValueError, match="binding differs"):
        event.prepare_event_interpretation(receipt, proposal, supplied, source_text=TEXT)


def test_subject_anchor_is_exact_token_aligned_and_strictly_before_temporal_text():
    receipt, proposal = inputs()
    good = declaration(requests(receipt, proposal))
    for span, label in [({"char_start": 1, "char_end": 8}, "token aligned"),
                        ({"char_start": TEXT.index("until"), "char_end": TEXT.index("until") + 5}, "must precede"),
                        ({"char_start": True, "char_end": 8}, "exact nonempty")]:
        supplied = deepcopy(good)
        supplied["subject_source_span"] = span
        with pytest.raises(ValueError, match=label):
            event.prepare_event_interpretation(receipt, proposal, supplied, source_text=TEXT)
    supplied = deepcopy(good)
    supplied["subject_source_text"] = "other subject"
    with pytest.raises(ValueError, match="subject source text differs"):
        event.prepare_event_interpretation(receipt, proposal, supplied, source_text=TEXT)


def test_closed_declarations_and_authentic_surface_inventory():
    receipt, proposal = inputs()
    supplied = declaration(requests(receipt, proposal))
    supplied["inferred_owner"] = "Registry"
    with pytest.raises(ValueError, match="closed"):
        event.prepare_event_interpretation(receipt, proposal, supplied, source_text=TEXT)
    changed = deepcopy(proposal)
    changed["proposals"][0]["event_span"]["char_start"] += 1
    with pytest.raises(ValueError, match="authoritative regeneration"):
        requests(receipt, changed)
    changed = deepcopy(receipt)
    changed["authority"]["source_semantics_verified"] = True
    with pytest.raises(ValueError, match="exact regeneration"):
        requests(resign(changed), proposal)


def test_actual_typed_temporal_and_strict_family_shapes_and_independent_lean_traces():
    weak, strong = prepared("weak"), prepared("strong")
    assert weak["tdfol_formula"] == "(records_retained W notice_received)"
    assert strong["tdfol_formula"] == "(records_retained U notice_received)"
    assert weak["temporal_ast"]["operator"] == "weak_until"
    assert strong["temporal_ast"]["operator"] == "until"
    assert weak["temporal_ast"]["formula_id"] != strong["temporal_ast"]["formula_id"]
    assert weak["declaration_sha256"] != strong["declaration_sha256"]
    for artifact in (weak, strong):
        assert TemporalFormula.from_dict(artifact["temporal_ast"]).to_dict() == artifact["temporal_ast"]
        assert all(item["passed"] and item["consumed_all_input"] for item in artifact["family_diagnostics"])
        assert artifact["atom_roles"] == {"records_retained": "state_holds", "notice_received": "event_occurs"}
        assert 'trace.holds "records_retained"' in artifact["lean_declarations"]
        assert 'trace.occurs "notice_received"' in artifact["lean_declarations"]
        assert "i.atom" not in artifact["lean_declarations"]
        assert all(value is False for value in artifact["authority"].values())
        assert artifact["semantics"]["modal_scope"] == "temporal_property_only"
        assert not any(token in artifact["lean_source"] for token in ("sorry", "admit", "axiom "))


@pytest.mark.parametrize("states,position,expected_weak,expected_strong", [
    ([(True, False)], 0, "true", "false"),  # No event: only weak until permits holding forever.
    ([(False, True)], 0, "true", "true"),  # Event at origin: empty pre-event interval.
    ([(True, False), (True, False), (False, True)], 0, "true", "true"),
    ([(True, False), (False, False), (False, True)], 0, "false", "false"),
    ([(False, False)], 0, "false", "false"),
    ([(False, True), (False, False), (True, False)], 2, "true", "false"),
    ([(False, False), (True, False), (False, True)], 1, "true", "true"),
])
def test_typed_semantics_distinguish_event_existence_and_excluded_endpoint(states, position, expected_weak, expected_strong):
    trace = TraceIR.from_state_sequence(
        [{"records_retained": hold, "notice_received": occurs} for hold, occurs in states],
        trace_kind=TraceKind.INFINITE, loop_start=len(states) - 1, proposition_adapter=lambda row: row)
    for strength, expected in (("weak", expected_weak), ("strong", expected_strong)):
        formula = TemporalFormula.from_dict(prepared(strength)["temporal_ast"])
        assert formula.evaluate(trace, position=position).verdict.value == expected


@pytest.mark.parametrize("field", ["temporal_ast", "tdfol_formula", "lean_source", "authority", "producer_pins"])
def test_resigned_artifacts_cannot_change_semantics_or_authority(field):
    receipt, proposal = inputs()
    artifact = prepared()
    if field == "temporal_ast":
        artifact[field]["operator"] = "until"
    elif field == "authority":
        artifact[field]["source_semantics_verified"] = True
    elif field == "producer_pins":
        artifact[field][next(iter(artifact[field]))] = "0" * 64
    else:
        artifact[field] += " changed"
    with pytest.raises(ValueError, match="exact replay"):
        event.validate_event_interpretation(resign(artifact), receipt, proposal, source_text=TEXT)


def test_exact_replay_returns_an_independent_copy():
    receipt, proposal = inputs()
    artifact = prepared()
    replayed = event.validate_event_interpretation(artifact, receipt, proposal, source_text=TEXT)
    assert replayed == artifact
    replayed["declaration"]["event_atom"] = "mutated"
    assert artifact["declaration"]["event_atom"] == "notice_received"


def test_changed_validator_renderer_dependency_fails_before_preparation(monkeypatch):
    receipt, proposal = inputs()
    target = Path(event.lean.__file__).resolve()
    original_read = Path.read_bytes
    def changed(path):
        value = original_read(path)
        return value + b"\n# changed" if path.resolve() == target else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="producer changed"):
        requests(receipt, proposal)


def test_changed_in_memory_lean_prelude_fails_closed(monkeypatch):
    receipt, proposal = inputs()
    monkeypatch.setattr(event.lean, "PRELUDE", event.lean.PRELUDE.replace("v < u", "v ≤ u"))
    with pytest.raises(ValueError, match="producer changed"):
        requests(receipt, proposal)


def test_dependency_change_during_inventory_fails_closed(monkeypatch):
    receipt, proposal = inputs()
    original_pins = event._dependency_pins
    calls = 0
    def changing_pins():
        nonlocal calls
        calls += 1
        pins = original_pins()
        if calls >= 2:
            pins[next(iter(pins))] = "0" * 64
        return pins
    monkeypatch.setattr(event, "_dependency_pins", changing_pins)
    with pytest.raises(ValueError, match="producer changed"):
        requests(receipt, proposal)

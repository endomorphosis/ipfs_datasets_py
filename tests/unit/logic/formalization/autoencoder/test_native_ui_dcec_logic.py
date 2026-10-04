"""Source-bound UI DCEC composition; no native executions in this suite."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_dcec_logic as api
from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as adapter


@pytest.fixture(scope="module")
def authored():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_modal_logic_v1/dcec_cases.py"
    spec = importlib.util.spec_from_file_location("ui_dcec_focused_authored", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(row):
    candidate, text = row["candidate"], row["source_text"]
    source = json.loads(text)
    native = {"kind": "document", "document": candidate["document"]}
    options = api.declared._bound_options(text, native, source["interpretations"])
    ec = api.events.prepare_payload(text, native, **options)
    return api.prepare_payload(text, candidate, ec_payload=ec, descriptor=candidate["logic"]["dcec"])


@pytest.fixture(scope="module")
def base(authored):
    row = authored.base_case()
    return row, _prepare(row)


def _changed(authored, base, mutate):
    row = deepcopy(base[0])
    mutate(row["candidate"]["logic"]["dcec"])
    return authored._reserialize(row)


def test_all_authored_cases_preserve_originals_and_expected_dispositions(authored):
    rows = authored.cases()
    assert len(rows) == 14 and sum(row["expected_disposition"] == "prepared" for row in rows) == 5
    for row in rows:
        before = deepcopy(row)
        if row["expected_disposition"] == "prepared":
            packet = authored.prepare_case(row)
            assert len(packet["report"]["requested_families"]) == 40
            assert not packet["report"]["all_requested_families_available"]
            projection = next(r for r in packet["report"]["projections"] if r["projection_id"] == api.PROJECTION_ID)
            source, meta = api.emit_projection(projection, report=packet["report"])
            assert meta["capability_floor_eligible"] and meta["native_formula_count"] == 1
            assert "UIDCECEventModel.happens" in source or "UIDCECEventModel.holdsAt" in source
            assert "i.atom" not in source and "axiom " not in source and "sorry" not in source
        else:
            with pytest.raises(ValueError, match=row["expected_reason"]):
                authored.prepare_case(row)
        assert row == before


def test_complete_native_ast_and_event_roles_are_preserved(base):
    row, payload = base
    record = payload["native_dcec_formulas"][0]
    assert record["operator_counts"] == {"cognitive": 1, "event": 1, "deontic": 1}
    assert record["ast_format"] == "dcec_native"
    assert record["native_ast"]["node_type"] == "CognitiveFormula"
    assert record["native_ast"]["formula"]["node_type"] == "DeonticFormula"
    assert record["known_event_leaves"] == [{"operator": "Happens", "symbol": "Close", "identity": "close",
        "time_symbol": "Tick12", "clock_time": 12, "logical_tick": 1, "known": True, "truth": True}]
    assert payload["candidate"] == row["candidate"]
    assert payload["ec_payload"]["candidate"] == {"kind": "document", "document": row["candidate"]["document"]}
    assert payload["candidate_sha256"] != payload["native_document_target_sha256"]
    assert all(payload[name] is False for name in ("admitted", "qualified", "training_executed",
        "source_semantics_verified", "event_authenticity_verified", "cognitive_truth_asserted",
        "normative_compliance_verified"))


def test_known_false_event_is_valid_content_but_no_cognitive_truth_is_asserted(authored):
    row = authored.base_case(base_index=0)
    payload = _prepare(row)
    assert payload["native_dcec_formulas"][0]["known_event_leaves"][0]["truth"] is False
    source = api._lean(payload)
    assert 'UIDCECEventModel.happens "close" 12 = some true' in source
    assert 'UIDCECEventModel.happens "close" 12 = some false := by decide' in source
    assert 'i.cognitive "B"' in source and 'i.modal "deontic:O"' in source
    assert not payload["cognitive_truth_asserted"]


@pytest.mark.parametrize("operator,at,passes", [("Happens", 14, True), ("Happens", 16, False),
    ("HoldsAt", 16, True), ("HoldsAt", 18, False), ("HoldsAt", 11, False), ("Happens", 8, False)])
def test_distinct_known_occurrence_and_fluent_boundaries(authored, operator, at, passes):
    descriptor = authored.descriptor(formula="B(Operator,O(HoldsAt(Open,Tick14)))", fluent=True) if operator == "HoldsAt" else authored.descriptor()
    descriptor["times"][0]["clock_time"] = at
    row = authored.base_case(declaration=descriptor)
    if passes:
        payload = _prepare(row)
        assert payload["native_dcec_formulas"][0]["known_event_leaves"][0]["clock_time"] == at
    else:
        with pytest.raises(ValueError, match="known prefix|aligned native clock"):
            _prepare(row)


@pytest.mark.parametrize("formula", [
    "B(Operator,O(Happens(Close,Tick12)))",
    "O(B(Operator,Happens(Close,Tick12)))",
    "K(Operator,F(not(Happens(Close,Tick12))))",
    "I(Operator,P(and(Happens(Close,Tick12),Happens(Close,Tick12))))",
    "B(Operator,O(or(Happens(Close,Tick12),not(Happens(Close,Tick12)))))",
    "B(Operator,O(implies(Happens(Close,Tick12),Happens(Close,Tick12))))",
    "B(Operator,O(iff(Happens(Close,Tick12),Happens(Close,Tick12))))",
])
def test_native_operator_order_arity_and_boolean_structure_are_not_flattened(authored, formula):
    payload = _prepare(authored.base_case(declaration=authored.descriptor(formula=formula)))
    record = payload["native_dcec_formulas"][0]
    assert record["formula"] == record["printed"] == formula
    assert record["functional_tree"][0] == formula.split("(", 1)[0]
    source = api._lean(payload)
    assert "uiDCECFormula0" in source and ".isSome = true" in source


@pytest.mark.parametrize("formula", [
    "B(Operator,O(Happens(Close,Tick12))) garbage",
    "B(Operator,O(Happens(Close,Tick12))",
    "O(Happens(Close,Tick12))",
    "B(Operator,Happens(Close,Tick12))",
    "B(Operator,O(Ready(Close)))",
    "B(Operator,O(Initiates(Close,Close,Tick12)))",
    "B(Operator,O(happens(Close,Tick12)))",
    "B(Operator,O(Happens(Close)))",
    "B(Operator,O(Happens(Close,Tick12,Tick12)))",
    "B(Operator,O(Happens(Close,variable)))",
    "B(Operator,O(Happens(Close,f(Tick12))))",
    "B(Close,O(Happens(Close,Tick12)))",
    "B(Operator,O(Happens(Operator,Tick12)))",
    "B(Operator,O(Happens(Close,Close)))",
    "B(Operator,O(HoldsAt(Close,Tick12)))",
    "B(Operator,O(not(Happens(Close,Tick12),Happens(Close,Tick12))))",
    "B(Operator,O(implies(Happens(Close,Tick12))))",
])
def test_malformed_unsupported_or_wrong_role_formulas_fail_closed(authored, formula):
    with pytest.raises(ValueError):
        _prepare(authored.base_case(declaration=authored.descriptor(formula=formula)))


@pytest.mark.parametrize("mutation", ["extra_key", "duplicate_alias", "duplicate_actor", "unused_agent", "reserved_alias",
    "unknown_event", "unknown_source", "missing_event_source", "boolean_time", "extra_formula_key", "duplicate_formula", "too_many_formulas"])
def test_binding_tables_are_closed_complete_and_exact(authored, base, mutation):
    row = deepcopy(base[0])
    descriptor = row["candidate"]["logic"]["dcec"]
    if mutation == "extra_key": descriptor["opaque_semantics"] = True
    elif mutation == "duplicate_alias": descriptor["events"][0]["symbol"] = "Operator"
    elif mutation == "duplicate_actor": descriptor["agents"].append({**descriptor["agents"][0], "symbol": "Another"})
    elif mutation == "unused_agent": descriptor["agents"].append({**descriptor["agents"][0], "symbol": "Another", "actor_id": "other"})
    elif mutation == "reserved_alias": descriptor["agents"][0]["symbol"] = "B"
    elif mutation == "unknown_event": descriptor["events"][0]["event_id"] = "missing"
    elif mutation == "unknown_source": descriptor["agents"][0]["source_ref_ids"] = ["missing"]
    elif mutation == "missing_event_source": row["candidate"]["document"]["events"][0]["source_ref_ids"] = []
    elif mutation == "boolean_time": descriptor["times"][0]["clock_time"] = True
    elif mutation == "extra_formula_key": descriptor["formulas"][0]["hidden"] = "meaning"
    elif mutation == "duplicate_formula": descriptor["formulas"].append(deepcopy(descriptor["formulas"][0]))
    else: descriptor["formulas"] *= 9
    with pytest.raises(ValueError): _prepare(authored._reserialize(row))


@pytest.mark.parametrize("field", ["occurrences", "fluent_values", "effect_table", "clock", "producer_pins", "native_ec_formulas"])
def test_coherently_rehashed_tampered_ec_is_not_accepted_as_live_semantics(base, field):
    row, payload = base
    ec = deepcopy(payload["ec_payload"])
    ec[field] = [] if type(ec[field]) is list else {}
    with pytest.raises(ValueError, match="replay differs"):
        api.prepare_payload(row["source_text"], row["candidate"], ec_payload=ec,
                            descriptor=row["candidate"]["logic"]["dcec"])


def test_source_and_candidate_modal_disagreement_blocks_before_any_replacement(base):
    row, payload = base
    candidate = deepcopy(row["candidate"])
    candidate["logic"]["dcec"]["formulas"][0]["formula"] = "O(B(Operator,Happens(Close,Tick12)))"
    before = deepcopy(candidate)
    with pytest.raises(ValueError, match="source/candidate disagreement"):
        api.prepare_payload(row["source_text"], candidate, ec_payload=payload["ec_payload"], descriptor=candidate["logic"]["dcec"])
    assert candidate == before


def test_descriptor_parameter_cannot_append_missing_original_candidate_logic(base):
    row, payload = base
    candidate = deepcopy(row["candidate"])
    candidate["logic"]["dcec"] = None
    with pytest.raises(ValueError, match="present unchanged"):
        api.prepare_payload(row["source_text"], candidate, ec_payload=payload["ec_payload"], descriptor=payload["descriptor"])


def test_exact_owned_route_report_membership_and_payload_replay(authored):
    packet = authored.prepare_case(authored.base_case())
    report = packet["report"]
    row = next(r for r in report["projections"] if r["projection_id"] == api.PROJECTION_ID)
    for changed in ({**row, "profile": "other"}, {**row, "logic_family": "temporal"},
                    {**row, "source_digest": "0" * 64}, {**row, "ready_for_training": False}):
        with pytest.raises(ValueError): api.emit_projection(changed, report=report)
    with pytest.raises(ValueError): api.emit_projection(row)
    duplicate = deepcopy(report)
    duplicate["projections"].append(deepcopy(row))
    with pytest.raises(ValueError): api.emit_projection(row, report=duplicate)
    changed_report = deepcopy(report)
    changed = next(r for r in changed_report["projections"] if r["projection_id"] == api.PROJECTION_ID)
    changed["payload"]["native_dcec_formulas"][0]["known_event_leaves"][0]["truth"] = False
    changed_report["report_sha256"] = api.digest({k: v for k, v in changed_report.items() if k != "report_sha256"})
    with pytest.raises(ValueError): api.emit_projection(changed, report=changed_report)
    with pytest.raises(NotImplementedError): api.emit_projection({"projection_id": "another/route"})


def test_loaded_producer_drift_fails_before_semantic_preparation(base, monkeypatch):
    row, payload = base
    monkeypatch.setitem(api._PINS, api.__name__, "0" * 64)
    with pytest.raises(ValueError, match="producer changed"):
        api.prepare_payload(row["source_text"], row["candidate"], ec_payload=payload["ec_payload"], descriptor=payload["descriptor"])


def test_output_has_no_alias_to_mutable_candidate_or_interpretation(base):
    row, payload = deepcopy(base)
    out = api.prepare_payload(row["source_text"], row["candidate"], ec_payload=payload["ec_payload"], descriptor=payload["descriptor"])
    row["candidate"]["logic"]["dcec"]["agents"][0]["actor_id"] = "changed"
    payload["ec_payload"]["occurrences"][0] = "changed"
    assert out["role_bindings"]["agents"]["Operator"]["actor_id"] == "user"
    assert out["ec_payload"]["occurrences"][0] is None

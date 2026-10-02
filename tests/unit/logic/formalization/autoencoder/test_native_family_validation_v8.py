"""V8 integration checks. No native subprocess or learned model is executed."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v7 as old_native
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v8 as native
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v7 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v8 as policy
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v4 as parallel
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters_v8 as emitters
from ipfs_datasets_py.logic.formalization.autoencoder import family_coverage_frontier_v2 as frontier
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as adapter


def prepared():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_bounded_event_v1/cases.py"
    spec = importlib.util.spec_from_file_location("v8_existing_ui_ec_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.cases()[1]
    return adapter.prepare_family_targets(row["source_text"], row["candidate"], **row["options"])


@pytest.mark.parametrize("domain", ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir"))
def test_fixed_floors_catalog_and_gate_requirements_are_unchanged(domain):
    before, after = old_policy.domain_projection_policy(domain), policy.domain_projection_policy(domain)
    for key in ("family_inventory", "minimum_batch_floor", "required_projection_evidence",
                "all_emitted_projections_require_validation", "narrow_request_can_complete",
                "inapplicability_can_waive_minimum_batch_floor"):
        assert before[key] == after[key]
    assert len(after["family_inventory"]) == 40
    assert before["policy_id"] != after["policy_id"]
    assert parallel.native is native and parallel.validation is policy


def test_old_source_keeps_exact_native_declarations_and_blocking_scope():
    packet = prepared()
    prior = old_native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    result = native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    assert result["lean_source"] == prior["lean_source"]
    assert result["per_projection"] == prior["per_projection"]
    assert result["schema"] != prior["schema"]
    assert result["source_replay_passed"] and not result["backend_executed"]
    assert all(row["lake_status"] == "not_run" for row in result["per_projection"])


@pytest.mark.parametrize("item", ({}, {"schema": "native-family-modality-lake/v8", "status": "passed"},
                                  native.NativeFamilyLakeExecution(), old_native.NativeFamilyLakeExecution()))
def test_saved_unissued_and_old_handles_cannot_supply_v8_authority(item):
    packet = prepared()
    with pytest.raises(ValueError, match="live issued"):
        native.verify_native_family_lake(item, packet["report"])
    observation = policy.validate_projection_report(packet["report"], lake_execution=item)
    evidence = observation.to_dict()
    assert not evidence["live_execution_verified"]
    assert not evidence["source_projection_gate_passed"]
    result = policy.evaluate_projection_training_batch([observation], domain_id="ui_ux_ir")
    assert not result["strict_training_allowed"]
    assert not any(row["satisfied"] for row in result["required_floor"])


@pytest.mark.parametrize("identity", tuple(emitters._OWNERS))
@pytest.mark.parametrize("error", (ValueError("owned parse rejected"), NotImplementedError("owned refused")))
def test_owned_native_failures_never_fall_through(monkeypatch, identity, error):
    def refuse(*args, **kwargs):
        raise error
    def forbidden(*args, **kwargs):
        raise AssertionError("owned failure reached old generic emitter")
    monkeypatch.setattr(emitters._OWNERS[identity], "emit_projection", refuse)
    monkeypatch.setattr(emitters.previous, "emit_projection", forbidden)
    with pytest.raises(ValueError):
        emitters.emit_projection({"projection_id": identity}, report={})


@pytest.mark.parametrize("marker", (
    {"payload": {"schema": "native-ui-state-temporal-logic/v1"}},
    {"payload": {"schema": "native-ui-bounded-dcec/v1"}},
    {"producer_id": emitters.temporal.__name__}, {"producer_id": emitters.cognitive.__name__},
))
def test_new_payload_cannot_escape_under_wrong_projection_id(monkeypatch, marker):
    monkeypatch.setattr(emitters.previous, "emit_projection",
        lambda *a, **k: pytest.fail("new payload must not reach prior emitter"))
    with pytest.raises(ValueError, match="cannot fall back"):
        emitters.emit_projection({"projection_id": "unknown-ui-id", **marker}, report={})


def test_unrelated_old_projection_reaches_unchanged_owner(monkeypatch):
    row, report = {"projection_id": "legacy-target"}, {"schema": "legacy"}
    seen = []
    monkeypatch.setattr(emitters.previous, "emit_projection",
        lambda value, *, report: seen.append((value, report)) or ("legacy", {}))
    assert emitters.emit_projection(row, report=report) == ("legacy", {})
    assert seen == [(row, report)]


def test_declared_schema_validator_dispatch_preserves_exact_source_inputs(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as source
    seen = []
    monkeypatch.setattr(source, "validate_family_training_report",
        lambda report, **kwargs: seen.append((report, kwargs)))
    report = {"schema": "ui-declared-logic-family-targets/v1"}
    inputs = {"source_text": "original", "candidate": {"typed": "prediction"}}
    native._validate_report(report, inputs)
    policy._validate_report(report)
    assert seen == [(report, inputs), (report, {})]


def test_source_byte_accounting_retains_entire_declared_source_and_candidate():
    source = {"source_text": "original source", "candidate": {"declarations": [1, False, "value"]}}
    before = deepcopy(source)
    report = {"schema": "ui-declared-logic-family-targets/v1"}
    assert parallel._source_input_bytes(report, source) == parallel._raw(source)
    assert source == before
    with pytest.raises(ValueError, match="source inputs"):
        parallel._source_input_bytes(report, {})


def _wrapped_original(packet):
    original = packet["report"]
    row = deepcopy(original["projections"][0])
    row.update(source_digest="retargeted", target_sha256="retargeted-row")
    report = {"schema": "ui-declared-logic-family-targets/v1", "base_ui_report": original,
        "declared_logic_source_binding": {"source_text": "exact source", "candidate": {"kind": "test-only"}},
        "projections": [row]}
    return row, report


def test_dispatch_replays_new_binding_then_delegates_exact_original_row(monkeypatch):
    # This isolates dispatch only; the mocked source validator grants no evidence.
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as source
    packet = prepared()
    row, report = _wrapped_original(packet)
    calls = []
    monkeypatch.setattr(source, "validate_family_training_report",
        lambda value, **inputs: calls.append(("replay", value, inputs)))
    monkeypatch.setattr(emitters.previous, "emit_projection",
        lambda value, *, report: calls.append(("prior", value, report)) or ("test only", {}))
    assert emitters.emit_projection(row, report=report) == ("test only", {})
    assert [call[0] for call in calls] == ["replay", "prior"]
    assert calls[0][2] == report["declared_logic_source_binding"]
    assert calls[1][1] == packet["report"]["projections"][0]
    assert calls[1][2] == packet["report"]


@pytest.mark.parametrize("key,value", (("payload", {}), ("logic_family", "dcec"),
                                       ("ready_for_training", 1), ("profile", "wrong")))
def test_preserved_row_tampering_does_not_reach_old_owner(monkeypatch, key, value):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as source
    row, report = _wrapped_original(prepared())
    row[key] = value
    monkeypatch.setattr(source, "validate_family_training_report", lambda *a, **k: None)
    monkeypatch.setattr(emitters.previous, "emit_projection",
        lambda *a, **k: pytest.fail("mutated original must not reach old emitter"))
    with pytest.raises(ValueError, match="differs from original"):
        emitters.emit_projection(row, report=report)


def test_frontier_accepts_v8_preparation_without_promoting_to_execution():
    packet = prepared()
    receipt = native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    before = deepcopy(receipt)
    result = frontier.diagnose_family_coverage(packet["report"], native_receipt=receipt)
    assert result["native_receipt_binding"]["schema"] == native.SCHEMA
    assert not result["native_receipt_binding"]["consistent_Lake_command_recorded"]
    assert not result["native_execution_authenticated"] and not result["strict_training_allowed"]
    assert all(row["status"] == "Lake_not_reported_passed" for row in result["projection_diagnostics"])
    assert receipt == before
    assert len(result["family_inventory"]) == 40
    for key in ("qualified", "admitted", "formalized", "training_executed"):
        assert result[key] is False


@pytest.mark.parametrize("mutation", ("omit", "duplicate", "claim", "source"))
def test_frontier_rejects_incomplete_or_unbound_inert_v8_receipts(mutation):
    packet = prepared()
    receipt = native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    if mutation == "omit": receipt["per_projection"].pop()
    if mutation == "duplicate": receipt["per_projection"][-1] = deepcopy(receipt["per_projection"][0])
    if mutation == "claim": receipt["qualified"] = True
    if mutation == "source": receipt["source_digest"] = "unrelated"
    with pytest.raises(ValueError):
        frontier.diagnose_family_coverage(packet["report"], native_receipt=receipt)


def declared_packet(name):
    path = Path(__file__).resolve().parents[4] / ("fixtures/logic/ui_modal_logic_v1/" + name + "_cases.py")
    spec = importlib.util.spec_from_file_location("v8_declared_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.cases()[0]
    return module.prepare_case(row)


@pytest.mark.parametrize("name,requirements", (("temporal", ("TFOL", "TDFOL")), ("dcec", ("DCEC",))))
def test_actual_declared_contract_preparation_and_named_fragments(name, requirements):
    packet = declared_packet(name)
    report_before = deepcopy(packet["report"])
    receipt = native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    assert len(receipt["per_projection"]) == len(packet["report"]["projections"])
    assert all(row["parser_status"] == "passed" for row in receipt["per_projection"])
    assert not receipt["backend_executed"]
    assert all(row["lake_status"] == "not_run" for row in receipt["per_projection"])
    diagnostic = frontier.diagnose_family_coverage(packet["report"], native_receipt=receipt)
    records = {row["requirement_id"]: row for row in diagnostic["named_fragment_evidence"]}
    for requirement in requirements:
        assert records[requirement]["status"] == "named_operator_record_available"
        assert records[requirement]["records"]
        assert all(row["native_formula_parse_replayed"] and row["required_operator_pattern_recorded"]
                   for row in records[requirement]["records"])
    assert not diagnostic["native_execution_authenticated"] and not diagnostic["strict_training_allowed"]
    assert not packet["report"]["current_learned_decoder_compatible"]
    assert packet["report"] == report_before
    assert len(diagnostic["family_inventory"]) == 40
    with pytest.raises(ValueError, match="known native family producer schema"):
        old_native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])


@pytest.mark.parametrize("name", ("temporal", "dcec"))
def test_full_original_source_replay_precedes_native_preparation(name):
    packet = declared_packet(name)
    altered = deepcopy(packet["source_inputs"])
    altered["candidate"]["document"]["title"] += " changed"
    with pytest.raises(ValueError, match="source_agreement|source_disagreement|replay differs"):
        native.prepare_native_family_lean(packet["report"], source_inputs=altered)


@pytest.mark.parametrize("name", ("temporal", "dcec"))
def test_new_operator_evidence_reparsed_instead_of_trusting_counts(name):
    packet = declared_packet(name)
    report = deepcopy(packet["report"])
    requirement = "TFOL" if name == "temporal" else "DCEC"
    identity = ("ui_ux_ir/declared_state_logic/TFOL/v1" if name == "temporal"
                else "ui_ux_ir/explicit_logic/bounded_dcec/v1")
    row = next(row for row in report["projections"] if row["projection_id"] == identity)
    records = row["payload"]["formulas" if name == "temporal" else "native_dcec_formulas"]
    records[0]["operator_counts"]["temporal" if name == "temporal" else "event"] = 0
    route = next(route for route in frontier.formulas.named_logic_routes() if route["requirement_id"] == requirement)
    with pytest.raises(ValueError, match="AST/operators differ"):
        frontier._declared_ui_records(report, route)

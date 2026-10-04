"""V6 gate regressions; tool-runner doubles are not actual Lake evidence.

Native preparation, exact source replay, live registries and policy remain real.
The explicit bounded-tool double isolates execution-result boundaries. Actual
Lean builds belong to the separate exposed-case native regression.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_contract_384 as adapter
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as old_gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v6 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v5 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v6 as policy
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction


SOURCES = (
    "If Cache.py is ready, agent must inspect Cache.py.",
    "If Cache.py is not ready, agent must inspect Cache.py.",
    "agent must inspect Cache.py and reviewer may archive Report.py.",
    "agent must inspect Cache.py or reviewer must not delete Report.py.",
)


def prepared(source=SOURCES[0], requested=None):
    target = {"kind": "intent_rich_ast", "document": parse_instruction(source)}
    return adapter.prepare_family_targets(source, target, requested_families=requested)


def reviews(report):
    emitted = {row["logic_family"] for row in report["projections"]}
    return [{"family_id": family, "source_digest": report["source_digest"], "disposition": "inapplicable",
        "reason": "Explicit unit fixture scope only; not a source-truth claim.",
        "evidence_refs": ["unit:closed-fixture-scope"]}
        for family in policy.domain_projection_policy(report["domain_id"])["family_inventory"]
        if family not in emitted]


@pytest.fixture
def tool_double(monkeypatch, tmp_path):
    executable = tmp_path / "unit-native-lake-double"
    executable.write_text("unit dependency double only; this file is never executed\n")
    executable.chmod(0o755)
    state = {"requests": [], "ok": True, "output_truncated": False, "workspace_limit_exceeded": False}

    class ToolRunnerDouble:
        def run(self, request):
            state["requests"].append(request)
            version = request.argv[-1] == "--version"
            ok = version or state["ok"]
            return SimpleNamespace(ok=ok,
                stdout="Lake version unit (Lean version 4.30.0)" if version else "UNIT DEPENDENCY DOUBLE, NOT LAKE",
                stderr="", returncode=0 if ok else 1, timed_out=False,
                output_truncated=False if version else state["output_truncated"],
                workspace_limit_exceeded=False if version else state["workspace_limit_exceeded"])

    # Replace the external execution boundary, not parsing, lowering or guards.
    monkeypatch.setattr(gate, "BoundedToolRunner", ToolRunnerDouble)
    monkeypatch.setattr(old_gate, "BoundedToolRunner", ToolRunnerDouble)
    state["executable"] = executable
    return state


def build(packet, tool_double, owner=gate):
    return owner.build_native_family_lake(packet["report"], source_inputs=packet["source_inputs"],
        lake_executable=str(tool_double["executable"]))


@pytest.mark.parametrize("domain", ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir"))
def test_v6_keeps_full_catalog_minimum_floor_and_required_evidence(domain):
    before, after = old_policy.domain_projection_policy(domain), policy.domain_projection_policy(domain)
    for field in ("family_inventory", "minimum_batch_floor", "required_projection_evidence",
                  "all_emitted_projections_require_validation", "narrow_request_can_complete",
                  "inapplicability_can_waive_minimum_batch_floor"):
        assert after[field] == before[field]
    assert len(after["family_inventory"]) == 40
    assert after["schema"] != before["schema"] and after["policy_id"] != before["policy_id"]
    after["minimum_batch_floor"].clear()
    assert policy.domain_projection_policy(domain)["minimum_batch_floor"]


@pytest.mark.parametrize("source", SOURCES)
def test_four_exposed_functional_cases_retain_originals_and_all_families(source):
    packet = prepared(source)
    before = gate.v1._json(packet)
    old = old_gate.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    new = gate.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    assert gate.v1._json(packet) == before
    assert old["report_sha256"] == new["report_sha256"]
    assert old["requested_families"] == new["requested_families"] and len(new["requested_families"]) == 40
    left = {row["projection_id"]: row for row in old["per_projection"]}
    right = {row["projection_id"]: row for row in new["per_projection"]}
    assert left.keys() == right.keys()
    dcec = "rich-intent/dcec/v1"
    assert left[dcec]["parser_status"] == "blocked"
    assert left[dcec]["reason"] == "strict_native_formula_reparse_failed"
    assert right[dcec]["parser_status"] == "passed" and right[dcec]["semantic_lowering_supported"]
    assert right[dcec]["lake_status"] == "not_run" and not new["backend_executed"]
    assert left[dcec]["payload_sha256"] == right[dcec]["payload_sha256"]
    for identity in left.keys() - {dcec}:
        assert left[identity] == right[identity]
    assert all(new[key] is False for key in gate.FALSE)


def test_live_v6_handle_binds_exact_report_and_never_satisfies_missing_modality_floor(tool_double):
    packet = prepared()
    handle = build(packet, tool_double)
    report = packet["report"]
    receipt = gate.verify_native_family_lake(handle, report)
    assert receipt["execution"]["stdout"] == "UNIT DEPENDENCY DOUBLE, NOT LAKE"
    assert receipt["execution"]["command"][1:] == ["build", "IntentIR"]
    assert receipt["status"] == "partial" and not receipt["all_requested_projections_passed"]
    assert len(receipt["requested_families"]) == 40
    assert all(row["parser_status"] == row["lake_status"] == "passed" for row in receipt["per_projection"])
    observation = policy.validate_projection_report(report, lake_execution=handle, applicability_review=reviews(report))
    assert observation.to_dict()["source_projection_gate_passed"]
    result = policy.evaluate_projection_training_batch([observation], domain_id="intent_ir", target_reports=[report])
    assert result["all_source_projection_gates_passed"] and not result["modality_floor_satisfied"]
    assert not result["strict_training_allowed"] and all(result[key] is False for key in policy._FALSE)
    with pytest.raises(policy.ProjectionValidationError):
        policy.require_projection_training_batch([observation], domain_id="intent_ir", target_reports=[report])


def test_detached_unissued_old_and_other_report_evidence_never_reopens_gate(tool_double):
    packet = prepared()
    handle, old = build(packet, tool_double), build(packet, tool_double, old_gate)
    assert old_gate.verify_native_family_lake(old, packet["report"])["schema"] == old_gate.SCHEMA
    for invalid in (handle.to_dict(), gate.NativeFamilyLakeExecution(), old, {"status": "passed"}):
        with pytest.raises(ValueError, match="live issued"):
            gate.verify_native_family_lake(invalid, packet["report"])
        audit = policy.validate_projection_report(packet["report"], lake_execution=invalid).to_dict()
        assert not audit["live_execution_verified"] and not audit["source_projection_gate_passed"]
    with pytest.raises(ValueError, match="another report"):
        gate.verify_native_family_lake(handle, prepared(SOURCES[2])["report"])
    detached = handle.to_dict()
    detached["per_projection"][0]["parser_status"] = "blocked"
    assert gate.verify_native_family_lake(handle, packet["report"])["per_projection"][0]["parser_status"] == "passed"


def test_saved_unissued_and_v5_observations_do_not_enter_v6_batch(tool_double):
    packet = prepared()
    handle = build(packet, tool_double)
    live = policy.validate_projection_report(packet["report"], lake_execution=handle)
    old_handle = build(packet, tool_double, old_gate)
    old = old_policy.validate_projection_report(packet["report"], lake_execution=old_handle)
    for invalid in (live.to_dict(), policy.ProjectionValidationObservation(live._bytes), old):
        with pytest.raises(ValueError, match="issued live projection observations"):
            policy.evaluate_projection_training_batch([invalid], domain_id="intent_ir")
    with pytest.raises(FrozenInstanceError):
        live._bytes = b"{}"


@pytest.mark.parametrize("mutation", ("source", "coherently_rehashed_formula", "valid_other_source_payload"))
def test_source_or_rehashed_projection_tamper_fails_before_any_tool(tool_double, mutation):
    packet = prepared()
    if mutation == "source":
        packet["source_inputs"]["source_text"] += " Another requirement."
    else:
        row = next(row for row in packet["report"]["projections"] if row["logic_family"] == "dcec")
        if mutation == "valid_other_source_payload":
            from ipfs_datasets_py.logic.formalization.autoencoder.strict_dcec_functional import validate_rich_dcec_payload
            other = prepared(SOURCES[0].replace("agent must", "reviewer must"))
            row["payload"] = deepcopy(next(p["payload"] for p in other["report"]["projections"] if p["logic_family"] == "dcec"))
            validate_rich_dcec_payload(row["payload"])
        else:
            row["payload"]["source"] += " trailing"
        row["target_sha256"] = gate._digest({key: value for key, value in row.items() if key != "target_sha256"})
        packet["report"]["report_sha256"] = gate._digest({key: value for key, value in packet["report"].items() if key != "report_sha256"})
    with pytest.raises(ValueError):
        build(packet, tool_double)
    assert tool_double["requests"] == []


def test_changed_tool_invalidates_previously_issued_live_observation(tool_double):
    packet = prepared()
    handle = build(packet, tool_double)
    observation = policy.validate_projection_report(packet["report"], lake_execution=handle)
    tool_double["executable"].write_text("changed test dependency\n")
    with pytest.raises(ValueError, match="source provenance changed"):
        gate.verify_native_family_lake(handle, packet["report"])
    result = policy.evaluate_projection_training_batch([observation], domain_id="intent_ir")
    assert not result["source_observations"][0]["live_execution_verified"]
    assert not result["strict_training_allowed"]


@pytest.mark.parametrize("flag,value", (("ok", False), ("output_truncated", True), ("workspace_limit_exceeded", True)))
def test_failed_or_incomplete_tool_output_never_validates_projection(tool_double, flag, value):
    tool_double[flag] = value
    packet = prepared()
    handle = build(packet, tool_double)
    assert handle.to_dict()["execution"]["status"] == "failed"
    audit = policy.validate_projection_report(packet["report"], lake_execution=handle).to_dict()
    assert not audit["all_emitted_projections_validated"]
    assert all("actual_Lake_build_not_passed" in row["blocking_reasons"] for row in audit["projection_observations"])


def test_narrow_request_and_mutated_optimization_targets_remain_blocked(tool_double):
    packet = prepared(requested=["dcec"])
    handle = build(packet, tool_double)
    observation = policy.validate_projection_report(packet["report"], lake_execution=handle, applicability_review=reviews(packet["report"]))
    audit = observation.to_dict()
    assert not audit["full_request_scope"] and not audit["source_projection_gate_passed"]
    assert any(row["reason"] == "narrowed_request_cannot_satisfy_complete_catalog_policy" for row in audit["family_blockers"])
    with pytest.raises(ValueError, match="optimization targets differ"):
        policy.evaluate_projection_training_batch([observation], domain_id="intent_ir", target_reports=[prepared()["report"]])


def test_all_native_source_owners_are_pinned_without_checkpoint_migration():
    packet = prepared()
    receipt = gate.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    assert any(path.endswith("/strict_dcec_functional.py") for path in receipt["producer"])
    assert any(path.endswith("/native_family_lean_emitters_v6.py") for path in receipt["producer"])
    assert not receipt["download_calls"] and receipt["dependencies"] == []
    assert gate.SCHEMA != old_gate.SCHEMA


@pytest.mark.parametrize("kind", ("partial_live", "detached", "old_live"))
def test_partial_old_or_detached_gate_stops_training_before_optimizer_and_artifact(tool_double, monkeypatch, tmp_path, kind):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v6 as trainer

    packet = prepared()
    owner, contract = (old_gate, old_policy) if kind == "old_live" else (gate, policy)
    handle = build(packet, tool_double, owner)
    observation = contract.validate_projection_report(packet["report"], lake_execution=handle,
        applicability_review=reviews(packet["report"]))
    if kind == "detached":
        observation = observation.to_dict()
    monkeypatch.setattr(trainer, "_reports", lambda *a, **k: pytest.fail("feature extraction entered before gate"))
    monkeypatch.setattr(trainer.prepared, "_calibrate_decoder", lambda *a, **k: pytest.fail("optimizer entered before gate"))
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        trainer.train_validated_family_projection_autoencoder([observation], [observation],
            domain_id="intent_ir", output_dir=output, epochs=1, latent_width=2, denoising=0)
    assert not output.exists()


def test_trainer_retains_every_emitted_projection_payload_and_detects_missing_loss():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v6 as trainer

    report = prepared()["report"]
    seen = []

    def atoms(payload):
        seen.append(deepcopy(payload))
        return [gate._raw(payload).decode()]

    rows = trainer._reports([report], atoms=atoms)
    assert seen == [projection["payload"] for projection in report["projections"]]
    assert set(rows[0]) == {projection["projection_id"] for projection in report["projections"]}
    coverage = {"untrained_projection_ids": [], "projections": [
        {"row": 0, "projection_id": name, "has_coverage": True} for name in rows[0]]}
    assert trainer._loss_coverage(rows, coverage)["projection_occurrences"] == len(report["projections"])
    coverage["projections"].pop()
    with pytest.raises(ValueError, match="every emitted projection"):
        trainer._loss_coverage(rows, coverage)


def test_v5_checkpoint_descriptor_is_not_implicitly_migrated(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as old_trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v6 as trainer

    assert trainer.SCHEMA != old_trainer.SCHEMA
    with pytest.raises(ValueError, match="closed validated checkpoint descriptor"):
        trainer._read({"schema": old_trainer.SCHEMA, "path": str(tmp_path / "not-opened.json"), "sha256": "0" * 64})

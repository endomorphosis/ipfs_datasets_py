"""Guarded Intent source/context/effect replay cannot borrow archived authority.

Control tests double the imported process runner, never pinned producer code.
Their explicitly marked receipts are not evidence of actual Lake execution.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v5 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v6 as native
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v3 as old_gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v4 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v3 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v4 as policy
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_guarded_intent_panel as panel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v4 as trainer


REPLACED = {"intent-route/workflow-temporal/v1", "intent-extended/transition_system/default/v1",
    "intent-extended/transition_system/tla_plus/v1"}
GUARDED = {"intent_ir/guarded/" + suffix + "/v1" for suffix in ("workflow", "state", "tla_plus", "action_contract")}


def effect_declaration(inputs):
    return {"schema": "intent-guarded-effect-bindings/v1", "source_ir_sha256": source_ir_sha256(inputs["document"]),
        "bindings": [{"statement_id": "effect", "expression": {"op": "eq", "variable_id": "completed", "value": True},
            "evidence_ref": "source"}]}


def inputs(index=0, *, negative=None):
    result = panel.source_inputs(index, include_false_precondition=negative == "false_precondition")
    if negative == "failed_outcome":
        result["context"]["state"]["workflow"]["action_updates"][0]["outcomes"][0]["values"]["completed"] = False
    source = native.supplemental_source_ref("intent_ir", **result)
    result["formula_inputs"] = [NativeFormulaEvidence(name, value, source) for name, value in panel.FORMULAS.items()]
    result["guarded_effect_bindings"] = native.IntentEffectBindings.from_dict(effect_declaration(result))
    return result


def prepare(index=0, *, negative=None):
    source = inputs(index, negative=negative)
    return source, native.prepare_family_training_targets_v6("intent_ir", **source)


def without_effect_bindings(source):
    return {key: value for key, value in source.items() if key != "guarded_effect_bindings"}


def rehash(report):
    for row in report["projections"]:
        row["target_sha256"] = native.core._sha({k: v for k, v in row.items() if k != "target_sha256"})
    report["report_sha256"] = native.core._sha({k: v for k, v in report.items() if k != "report_sha256"})


def test_no_effect_interpretation_leaves_original_guarded_projections_unsupported():
    source = without_effect_bindings(inputs())
    report = native.prepare_family_training_targets_v6("intent_ir", **source)
    receipt = gate.prepare_native_family_lean(report, source_inputs=source)
    rows = [row for row in receipt["per_projection"] if row["projection_id"] in REPLACED]
    assert {row["projection_id"] for row in rows} == REPLACED
    assert all(row["semantic_lowering_supported"] is False for row in rows)
    assert report["guarded_effect_binding_input"] is None
    assert report["superseded_guarded_observations"] == []


def test_exact_guarded_replacements_keep_all_original_action_contracts_active():
    source, report = prepare()
    baseline = previous.prepare_family_training_targets_v5("intent_ir", **without_effect_bindings(source))
    old = {row["projection_id"]: row for row in baseline["projections"]}
    active = {row["projection_id"]: row for row in report["projections"]}
    archived = {row["projection_id"]: row for row in report["superseded_guarded_observations"]}
    assert set(archived) == REPLACED
    assert not REPLACED.intersection(active)
    assert GUARDED <= set(active)
    assert "intent-route/action-hoare/v1" in active
    for identity, row in old.items():
        if identity in REPLACED:
            assert archived[identity]["payload"] == row["payload"]
            assert archived[identity]["active_for_training"] is False
            assert archived[identity]["replacement_projection_id"] in active
        else:
            assert active[identity]["payload"] == row["payload"]
            assert active[identity]["ready_for_training"] == row["ready_for_training"]
    assert len(report["family_inventory"]) == 40
    assert report["requested_families"] == baseline["requested_families"]
    assert all(active[name]["ready_for_training"] for name in GUARDED)
    receipt = gate.prepare_native_family_lean(report, source_inputs=source)
    actual = {row["projection_id"]: row for row in receipt["per_projection"]}
    assert set(actual) == set(active)
    assert all(actual[name]["semantic_lowering_supported"] for name in GUARDED)
    assert receipt["backend_executed"] is False
    assert all(report[key] is False for key in ("source_text_to_native_formula_inference", "structural_readiness_is_qualification"))


@pytest.mark.parametrize("missing", ["guarded_effect_bindings", "context"])
def test_gate_requires_original_context_and_explicit_bindings_instead_of_embedded_copies(missing):
    source, report = prepare()
    del source[missing]
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=source)


def test_changed_context_and_foreign_source_cannot_reuse_same_effect_input():
    source, report = prepare()
    source["context"]["state"]["max_steps"] = 5
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=source)
    foreign = inputs(1)
    foreign["guarded_effect_bindings"] = inputs(0)["guarded_effect_bindings"]
    with pytest.raises(ValueError):
        native.prepare_family_training_targets_v6("intent_ir", **foreign)


@pytest.mark.parametrize("part", ["active_payload", "archive_payload", "embedded_effects", "context_metadata"])
def test_coherently_rehashed_tamper_cannot_skip_full_source_context_effect_replay(part):
    source, report = prepare()
    if part == "active_payload":
        row = next(row for row in report["projections"] if row["projection_id"] == "intent_ir/guarded/state/v1")
        row["payload"]["unreviewed_extra"] = "tampered"
    elif part == "archive_payload":
        # The original workflow-temporal representation is an ordered list,
        # not the new guarded payload dictionary. Preserve its native shape.
        report["superseded_guarded_observations"][0]["payload"].append({"unreviewed_extra": "tampered"})
    elif part == "embedded_effects":
        report["guarded_effect_binding_input"]["bindings"][0]["expression"]["value"] = False
    else:
        report["v5_source_digest"] = "c" * 64
    rehash(report)
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=source)


@pytest.mark.parametrize("mutation", ["duplicate", "stale_document", "unknown_effect", "missing_effect"])
def test_invalid_explicit_effect_sets_cannot_prepare_training_targets(mutation):
    source = inputs()
    value = effect_declaration(source)
    if mutation == "duplicate": value["bindings"].append(deepcopy(value["bindings"][0]))
    elif mutation == "stale_document": value["source_ir_sha256"] = "c" * 64
    elif mutation == "unknown_effect": value["bindings"][0]["statement_id"] = "not-an-effect"
    else: value["bindings"].clear()
    with pytest.raises(ValueError):
        source["guarded_effect_bindings"] = native.IntentEffectBindings.from_dict(value)
        native.prepare_family_training_targets_v6("intent_ir", **source)


def test_omission_vs_explicit_effects_changes_identity_without_changing_floor():
    source, report = prepare()
    absent = native.prepare_family_training_targets_v6("intent_ir", **without_effect_bindings(source))
    assert report["source_digest"] != absent["source_digest"]
    assert report["report_sha256"] != absent["report_sha256"]
    for domain in ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir"):
        new, old = policy.domain_projection_policy(domain), old_policy.domain_projection_policy(domain)
        assert new["family_inventory"] == old["family_inventory"]
        assert new["minimum_batch_floor"] == old["minimum_batch_floor"]


@pytest.fixture
def backend_double(monkeypatch, tmp_path):
    class RuntimeDouble:
        def run(self, request):
            output = "Lean version 4.30.0\n" if request.argv[-1] == "--version" else "unit_dependency_double_no_native_execution\n"
            return SimpleNamespace(ok=True, stdout=output, stderr="", output_truncated=False,
                workspace_limit_exceeded=False, returncode=0, timed_out=False)
    path = tmp_path / "unit-only-tool"
    path.write_text("Only hashed: imported RuntimeDouble never executes this file.\n")
    path.chmod(0o700)
    monkeypatch.setattr(gate, "BoundedToolRunner", RuntimeDouble)
    return str(path)


@pytest.mark.parametrize("negative", ["false_precondition", "failed_outcome"])
def test_deadlock_or_failed_outcome_cannot_train_even_when_other_rows_build(negative, backend_double, tmp_path):
    source, report = prepare(negative=negative)
    guarded = [row for row in report["projections"] if row["projection_id"] in GUARDED]
    assert len(guarded) == 4 and all(row["ready_for_training"] is False for row in guarded)
    handle = gate.build_native_family_lake(report, source_inputs=source, lake_executable=backend_double)
    receipt = handle.to_dict()
    assert receipt["execution"]["status"] == "passed"
    assert any(row["lake_status"] == "passed" for row in receipt["per_projection"] if row["projection_id"] not in GUARDED)
    assert all(row["semantic_lowering_supported"] is False for row in receipt["per_projection"] if row["projection_id"] in GUARDED)
    observation = policy.validate_projection_report(report, lake_execution=handle, applicability_review=panel.applicability_reviews(report, 0))
    with pytest.raises(policy.ProjectionValidationError):
        trainer.train_validated_family_projection_autoencoder([observation], [observation], domain_id="intent_ir", output_dir=tmp_path / "never-trained")
    assert not (tmp_path / "never-trained").exists()


def test_old_execution_handles_and_archived_receipts_do_not_authorize_v6(backend_double):
    source, report = prepare(negative="false_precondition")
    current = gate.build_native_family_lake(report, source_inputs=source, lake_executable=backend_double)
    for value in (old_gate.NativeFamilyLakeExecution(), gate.NativeFamilyLakeExecution(), current.to_dict()):
        with pytest.raises(ValueError, match="live issued"):
            gate.verify_native_family_lake(value, report)
    for value in (old_policy.ProjectionValidationObservation(b"{}"), {"strict_training_allowed": True}):
        with pytest.raises(ValueError, match="live validation observations"):
            trainer._panel([value], "intent_ir")

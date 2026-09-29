"""Native multi-domain feature training with independent control-plane checks.

Small authored samples test numerical and storage plumbing, not held-out
semantic accuracy or legal admission. No weights or datasets are downloaded.
"""

from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.formalization.autoencoder import domain_targets, ui_targets
from ipfs_datasets_py.logic.intent_ir.decoder import decode_intent_ir
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from ipfs_datasets_py.logic.software_verification.program import (
    BasicBlock, ControlFlowGraph, ProgramCommand, ProgramExpression, ProgramFunction, ProgramIR,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize.roundtrip import RoundTripDocument
from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass, ProgramBindingTargetKind, RiskClass, UIActionBinding, UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.components import SemanticComponent, UIComponentGraph
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import CanonicalInteractionEvent, EventKind, EventProvenance
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def _intent(index):
    document = decode_intent_ir(json.loads((FIXTURES / "intent_ir/admissibility/intents/benign_skill.json").read_text()))
    document = replace(document, document_id=f"intent:feature-fixture:{index}",
        sources=tuple(replace(source, content_sha256=hashlib.sha256(f"authored-intent-{index}".encode()).hexdigest())
                      for source in document.sources),
        statements=tuple(replace(row, predicate=f"produce_fixture_{index}", normalized_text=f"Produce fixture report {index}")
                         if row.kind.value == "goal" else row for row in document.statements))
    return domain_targets.prepare_intent_targets(document)


def _security(index):
    body = f"def one():\n    return {index}\n".encode()
    cid = canonical_identity({"fixture": index}, domain="authored", schema_version="v1").cid
    body_cid = canonical_identity({"body": body.decode()}, domain="cvefixes-security-ir/code-body",
                                 schema_version="cvefixes-code-body/v1").cid
    unit = CodeUnit(source_cids=(cid,), parent_cids=(cid,), config_cid=cid,
        unit_kind="symbol", language="Python", path="one.py", polarity="fixed",
        payload={"body_sha256": hashlib.sha256(body).hexdigest(), "body_cid": body_cid})
    source = SourceRef(ref_id=unit.cid, source_uri="code-unit:" + unit.cid, source_id=unit.path,
        source_revision=f"authored-fixture-{index}", content_sha256=unit.payload["body_sha256"], content_cid=body_cid)
    mapped = {"source_ref_ids": (source.ref_id,)}
    expression = ProgramExpression("expr:one", "literal", "integer", attributes={"value": index}, **mapped)
    command = ProgramCommand("cmd:return", "return", expression_ids=("expr:one",), **mapped)
    graph = ControlFlowGraph(graph_id="cfg:one", entry_block_id="block:one",
        blocks=(BasicBlock("block:one", ("cmd:return",), **mapped),), edges=(), normal_exit_block_ids=("block:one",))
    function = ProgramFunction(function_id="function:one", name="one", cfg=graph, return_type="integer", **mapped)
    program = ProgramIR(sources=(source,), spans=(), symbols=(), expressions=(expression,), commands=(command,), functions=(function,))
    return domain_targets.prepare_security_targets(code_unit=unit, source_bytes=body,
        typed_inputs=(CodeLogicEvidence(program, source),), requested_kinds=("program",))


def _ui(index):
    document = RoundTripDocument(document_id=f"ui:fixture:{index}", component_graph=UIComponentGraph(
        components=(SemanticComponent(component_id="delete", role="button"),), entry_component_ids=("delete",)),
        behavior_model=BehaviorModel(model_id="workflow", states=(BehaviorState(state_id="pending"),
            BehaviorState(state_id="cancelled", terminal=True)), transitions=(BehaviorTransition(transition_id="timeout",
            source_state_ids=("pending",), target_state_id="cancelled", event_id="cancel", timeout_ms=1000 * index),),
            initial_state_ids=("pending",)),
        action_bindings=(UIActionBinding(binding_id="binding:delete", action_id="delete",
            program_ref=UIProgramRef(target_kind=ProgramBindingTargetKind.MCP_IDL,
                mcp_idl_interface_cid="bafkreicotxqdc6qhz3h3miegt37q3iz2syjrhj7z4mhjd2sidi35bx3t5i",
                mcp_idl_method_name="delete"), risk_class=RiskClass.HIGH, confirmation_class=ConfirmationClass.CONFIRM),),
        events=(CanonicalInteractionEvent(event_id="click:delete", kind=EventKind.ACTIVATE, target_component_id="delete",
            timestamp_ms=index, provenance=EventProvenance.HUMAN, capability_id="pointer_mouse", consent_ok=True),))
    return ui_targets.prepare_ui_targets(document)


@pytest.fixture(scope="module", params=["intent_ir", "security_ir", "ui_ux_ir"])
def native_case(request):
    prepare = {"intent_ir": _intent, "security_ir": _security, "ui_ux_ir": _ui}[request.param]
    train, tune = [prepare(1), prepare(2)], [prepare(3), prepare(4)]
    ids = [row["projection_id"] for row in train[0].to_dict()["projections"] if row["logic_family"] is not None]
    space = features.build_feature_space(request.param, ids, train)
    adapter = ui_targets if request.param == "ui_ux_ir" else domain_targets
    contract = features.build_native_feature_contract(space, ir_schema=f"{request.param}/native-fixture-v1",
        adapter_sha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(), latent_width=4)
    return contract, space, train, tune


def test_native_domains_train_separate_projection_metrics_without_authority(native_case):
    contract, space, train, tune = native_case
    before = features.digest([contract.to_dict(), space, [value.to_dict() for value in train + tune]])
    result = features.train_projection_features(contract, space, train, tune, epochs=2)
    report = result["report"]
    assert report["training_target_count"] == report["tuning_target_count"] == 2
    assert len(report["epochs"]) == 2
    assert report["after"]["objective"] <= report["before"]["objective"]
    assert set(report["after"]["projections"]) == set(space["projection_ids"])
    assert "other" not in report["after"]["projections"]
    for name, metrics in report["after"]["projections"].items():
        assert all(metrics[key] <= report["before"]["projections"][name][key] + 1e-9
                   for key in ("reconstruction", "cosine"))
    for part in (result["state"], report):
        assert all(part[key] is False for key in features.FALSE)
    assert report["heldout_canary"] is False and report["lake_executed"] is False
    assert report["weights_downloaded"] is False
    assert before == features.digest([contract.to_dict(), space, [value.to_dict() for value in train + tune]])
    assert set(space["training_sources"]).isdisjoint(row.source_digest for row in tune)
    assert sum(row["unknown_atoms"] for row in report["tuning_coverage"]) > 0


def test_vocabulary_and_parent_identity_cannot_cross_basis_or_modality(native_case):
    contract, space, train, tune = native_case
    changed = copy.deepcopy(space)
    changed["columns"][0], changed["columns"][1] = changed["columns"][1], changed["columns"][0]
    with pytest.raises(features.ProjectionFeatureError, match="basis|feature space"):
        features.train_projection_features(contract, changed, train, tune, epochs=1)
    with pytest.raises(features.ProjectionFeatureError, match="leakage"):
        features.train_projection_features(contract, space, train, [train[0]], epochs=1)
    foreign = _security(5) if contract.domain != "security_ir" else _intent(5)
    with pytest.raises(features.ProjectionFeatureError, match="another modality"):
        features.build_feature_space(contract.domain, space["projection_ids"], [foreign])
    result = features.train_projection_features(contract, space, train, tune, epochs=1)
    different = replace(contract, source_language="other-authored-fixture")
    with pytest.raises(features.ProjectionFeatureError, match="parent belongs|identity or authority"):
        features.train_projection_features(different, space, train, tune, base_state=result["state"], epochs=1)


def test_adam_resume_preserves_moments_and_matches_uninterrupted_steps():
    train, tune = [_ui(1), _ui(2)], [_ui(3), _ui(4)]
    space = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], train)
    contract = features.build_native_feature_contract(space, ir_schema="ui_ux_ir/fixture-v1",
        adapter_sha256=hashlib.sha256(Path(ui_targets.__file__).read_bytes()).hexdigest())
    first = features.train_projection_features(contract, space, train, tune, epochs=1)
    assert first["report"]["improved"] and first["state"]["completed_epochs"] == 1
    assert all(moment["step"] == 1 for moment in first["state"]["adam"])
    parent_before = copy.deepcopy(first["state"])
    resumed = features.train_projection_features(contract, space, train, tune, epochs=1, base_state=first["state"])
    uninterrupted = features.train_projection_features(contract, space, train, tune, epochs=2)
    assert first["state"] == parent_before
    assert resumed["state"] == uninterrupted["state"]
    assert resumed["state"]["completed_epochs"] == 2
    assert all(moment["step"] == 2 for moment in resumed["state"]["adam"])


def test_deadline_returns_unmodified_baseline_before_optimizer_step(monkeypatch):
    train, tune = [_ui(1)], [_ui(2)]
    space = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], train)
    contract = features.build_native_feature_contract(space, ir_schema="ui_ux_ir/fixture-v1", adapter_sha256="a" * 64)
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as kernel
    class Clock:
        now = 0.0
        def monotonic(self):
            return self.now
    clock = Clock()
    original_loss = kernel._loss_chunk
    def expensive_training_loss(*args, **kwargs):
        result = original_loss(*args, **kwargs)
        if torch.is_grad_enabled():
            clock.now = 2.0
        return result
    monkeypatch.setattr(features, "time", clock)
    monkeypatch.setattr(kernel, "_loss_chunk", expensive_training_loss)
    result = features.train_projection_features(contract, space, train, tune, epochs=2, max_seconds=0.5)
    assert result["report"]["stopped_reason"] == "deadline"
    assert result["report"]["epochs"] == []
    assert result["state"]["completed_epochs"] == 0
    assert not result["report"]["improved"]
    assert all(moment["step"] == 0 for moment in result["state"]["adam"])


def test_ordered_projection_arguments_are_not_a_bag_of_atoms():
    left = list(features._tokens({"operator": "implies", "arguments": ["permitted", "performed"]}))
    right = list(features._tokens({"operator": "implies", "arguments": ["performed", "permitted"]}))
    assert set(left) != set(right)


def test_duckdb_candidate_registration_keeps_variants_and_parent_links_separate(tmp_path):
    train, tune = [_ui(1)], [_ui(2)]
    space = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], train)
    contract = features.build_native_feature_contract(space, ir_schema="ui_ux_ir/fixture-v1", adapter_sha256="a" * 64)
    first = features.train_projection_features(contract, space, train, tune, epochs=1)
    second = features.train_projection_features(contract, space, train, tune, epochs=1, base_state=first["state"])
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        registered = features.register_feature_candidate(registry, contract, space, first, tmp_path / "first")
        parent = registry.get_version(registered["version_id"])
        assert parent["variant_id"] == contract.variant_id
        child = features.register_feature_candidate(registry, contract, space, second, tmp_path / "second",
                                                     parent_version_id=registered["version_id"])
        row = registry.get_version(child["version_id"])
        assert row["parent_version_id"] == registered["version_id"]
        assert row["metadata"]["training_purpose"] == "feature_pretraining"
        assert all(row["metadata"][key] is False for key in features.FALSE)
        other = replace(contract, source_language="other-authored-fixture")
        foreign = features.train_projection_features(other, space, train, tune, epochs=1)
        with pytest.raises(features.ProjectionFeatureError, match="parent variant mismatch"):
            features.register_feature_candidate(registry, other, space, foreign, tmp_path / "rejected",
                                                 parent_version_id=registered["version_id"])
        assert not (tmp_path / "rejected").exists()
        stored = json.loads((tmp_path / "second/candidate.json").read_text())
        assert stored["state"] == second["state"] and stored["contract"] == contract.to_dict()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as reopened:
        assert reopened.get_version(child["version_id"])["parent_version_id"] == registered["version_id"]


@pytest.fixture(scope="module")
def trained_small_case():
    train, tune = [_ui(1)], [_ui(2)]
    space = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic"], train)
    contract = features.build_native_feature_contract(space, ir_schema="ui_ux_ir/fixture-v1", adapter_sha256="a" * 64)
    result = features.train_projection_features(contract, space, train, tune, epochs=1)
    return contract, space, train, tune, result


def test_collapsed_decoder_cannot_report_perfect_cosine(trained_small_case):
    contract, space, train, tune, result = trained_small_case
    state = copy.deepcopy(result["state"])
    state["parameters"][2] = [[0.0 for value in row] for row in state["parameters"][2]]
    state["parameters"][3] = [0.0 for value in state["parameters"][3]]
    with pytest.raises(features.ProjectionFeatureError, match="zero-norm.*perfect cosine"):
        features.train_projection_features(contract, space, train, tune, base_state=state, epochs=1)


@pytest.mark.parametrize("alteration", ["step", "completed_epochs", "learning_rate", "betas", "negative_second_moment"])
def test_resume_rejects_inconsistent_adam_state_and_settings(trained_small_case, alteration):
    contract, space, train, tune, result = trained_small_case
    state = copy.deepcopy(result["state"])
    options = {}
    if alteration == "step":
        state["adam"][0]["step"] += 1
    elif alteration == "completed_epochs":
        state["completed_epochs"] += 1
    elif alteration == "learning_rate":
        options["learning_rate"] = 0.03
    elif alteration == "betas":
        state["optimizer_config"]["betas"] = [0.8, 0.999]
    else:
        state["adam"][0]["exp_avg_sq"][0][0] = -1.0
    with pytest.raises(features.ProjectionFeatureError, match="Adam step|optimizer settings|tensor value"):
        features.train_projection_features(contract, space, train, tune, base_state=state, epochs=1, **options)


def test_changed_native_projection_profile_is_not_an_equivalent_contract(trained_small_case):
    contract, space, train, tune, _ = trained_small_case
    forged = replace(contract, projections=(replace(contract.projections[0], native_profile_id="different-native-profile/v1"),))
    with pytest.raises(features.ProjectionFeatureError, match="native projection profile"):
        features.train_projection_features(forged, space, train, tune, epochs=1)


def test_backend_rejects_unimplemented_canonical_profile_claim_before_training():
    train, tune = [_security(1)], [_security(2)]
    space = features.build_feature_space('security_ir', ['program.program_ir/v1'], train)
    contract = features.build_native_feature_contract(space, ir_schema='security_ir/fixture-v1', adapter_sha256='a' * 64)
    # QF_BV is a catalog profile, but these native ProgramIR documents and this
    # structural trainer do not implement its semantics merely by naming it.
    altered = replace(contract, projections=(replace(contract.projections[0], profile_id='qf_bv'),))
    with pytest.raises(features.ProjectionFeatureError, match='canonical projection profile'):
        features.train_projection_features(altered, space, train, tune, epochs=1)


@pytest.mark.parametrize('alteration', ['view_role', 'required'])
def test_backend_requires_exact_native_projection_roles_and_requirements(alteration):
    train, tune = [_ui(1)], [_ui(2)]
    space = features.build_feature_space('ui_ux_ir', ['ui_ux_ir:flogic', 'ui_ux_ir:event_calculus'], train)
    contract = features.build_native_feature_contract(space, ir_schema='ui_ux_ir/fixture-v1', adapter_sha256='a' * 64)
    change = {'view_role': 'proof_translation'} if alteration == 'view_role' else {'required': False}
    altered = replace(contract, projections=(replace(contract.projections[0], **change), *contract.projections[1:]))
    with pytest.raises(features.ProjectionFeatureError, match='canonical projection profile'):
        features.train_projection_features(altered, space, train, tune, epochs=1)


def test_interleaved_projection_columns_are_rejected_even_with_a_matching_contract():
    train, tune = [_ui(1)], [_ui(2)]
    ids = ["ui_ux_ir:flogic", "ui_ux_ir:event_calculus"]
    original = features.build_feature_space("ui_ux_ir", ids, train)
    altered = copy.deepcopy(original)
    groups = [[column for column in original["columns"] if column[0] == identifier] for identifier in original["projection_ids"]]
    altered["columns"] = [column for index in range(max(map(len, groups))) for group in groups if index < len(group)
                          for column in [group[index]]]
    assert altered["columns"] != original["columns"]
    contract = features.build_native_feature_contract(altered, ir_schema="ui_ux_ir/fixture-v1", adapter_sha256="a" * 64)
    with pytest.raises(features.ProjectionFeatureError, match="feature space (layout|columns)"):
        features.train_projection_features(contract, altered, train, tune, epochs=1)


def test_deadline_during_candidate_evaluation_never_selects_expired_update(trained_small_case, monkeypatch):
    contract, space, train, tune, _ = trained_small_case
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as kernel
    class Clock:
        now = 0.0
        def monotonic(self):
            return self.now
    clock = Clock()
    original_loss = kernel._loss_chunk
    training_seen = False
    def expensive_candidate_check(*args, **kwargs):
        nonlocal training_seen
        result = original_loss(*args, **kwargs)
        if torch.is_grad_enabled():
            training_seen = True
        elif training_seen:
            clock.now = 2.0
        return result
    monkeypatch.setattr(features, "time", clock)
    monkeypatch.setattr(kernel, "_loss_chunk", expensive_candidate_check)
    result = features.train_projection_features(contract, space, train, tune, epochs=2, max_seconds=0.5)
    assert result["report"]["stopped_reason"] == "deadline"
    assert len(result["report"]["epochs"]) == 1
    assert result["report"]["epochs"][0]["deadline_exceeded"]
    assert result["report"]["epochs"][0]["selected"] is False
    assert result["state"]["completed_epochs"] == 0
    assert all(moment["step"] == 0 for moment in result["state"]["adam"])
    assert result["report"]["after"] == result["report"]["before"]


def test_same_variant_wrong_numerical_parent_is_rejected(trained_small_case, tmp_path):
    contract, space, train, tune, first = trained_small_case
    other = features.train_projection_features(contract, space, train, tune, epochs=1, seed=1730)
    assert features.digest(other["state"]) != features.digest(first["state"])
    child = features.train_projection_features(contract, space, train, tune, epochs=1, base_state=first["state"])
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        features.register_feature_candidate(registry, contract, space, first, tmp_path / "first")
        wrong_parent = features.register_feature_candidate(registry, contract, space, other, tmp_path / "other")
        with pytest.raises(features.ProjectionFeatureError, match="numerical parent differs"):
            features.register_feature_candidate(registry, contract, space, child, tmp_path / "rejected",
                                                 parent_version_id=wrong_parent["version_id"])
        with pytest.raises(features.ProjectionFeatureError, match="requires its exact registry parent"):
            features.register_feature_candidate(registry, contract, space, child, tmp_path / "missing-parent")
        assert not (tmp_path / "rejected").exists() and not (tmp_path / "missing-parent").exists()


def test_malformed_numerical_state_cannot_reach_registry(trained_small_case, tmp_path):
    contract, space, _, _, result = trained_small_case
    invalid = copy.deepcopy(result)
    invalid["state"]["parameters"][0].pop()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(features.ProjectionFeatureError, match="tensor shape"):
            features.register_feature_candidate(registry, contract, space, invalid, tmp_path / "invalid")
        assert not (tmp_path / "invalid").exists()


def test_inference_is_read_only_and_returns_separate_native_projection_features(native_case, monkeypatch):
    contract, space, train, tune = native_case
    result = features.train_projection_features(contract, space, train, tune, epochs=1)
    state_before = copy.deepcopy(result["state"])
    inputs_before = features.digest([space, [target.to_dict() for target in tune]])
    import torch
    def forbidden_training(*args, **kwargs):
        raise AssertionError("inference attempted to initialize an optimizer or train")
    monkeypatch.setattr(torch.optim, "Adam", forbidden_training)
    monkeypatch.setattr(features, "train_projection_features", forbidden_training)
    inference = features.infer_projection_features(contract, space, result["state"], tune)
    assert [row["source_digest"] for row in inference["rows"]] == [target.source_digest for target in tune]
    for row in inference["rows"]:
        assert len(row["latent"]) == result["state"]["latent_width"]
        assert set(row["reconstructed_projection_features"]) == set(space["projection_ids"])
        for name, values in row["reconstructed_projection_features"].items():
            assert len(values) == sum(column[0] == name for column in space["columns"])
    assert inference["training_executed"] is False and inference["decoded_formulas_generated"] is False
    assert all(inference[key] is False for key in features.FALSE)
    assert result["state"] == state_before
    assert inputs_before == features.digest([space, [target.to_dict() for target in tune]])
    different = replace(contract, source_language="other-authored-fixture")
    with pytest.raises(features.ProjectionFeatureError, match="identity or authority"):
        features.infer_projection_features(different, space, result["state"], tune)


def test_incremental_training_reuses_frozen_basis_and_fixed_tuning_panel():
    original_train, fixed_tune, next_batch = [_ui(1)], [_ui(2)], [_ui(3)]
    space = features.build_feature_space("ui_ux_ir", ["ui_ux_ir:flogic", "ui_ux_ir:event_calculus"], original_train)
    contract = features.build_native_feature_contract(space, ir_schema="ui_ux_ir/fixture-v1", adapter_sha256="a" * 64)
    first = features.train_projection_features(contract, space, original_train, fixed_tune, epochs=1)
    initial_state = copy.deepcopy(first["state"])
    basis_before = copy.deepcopy(space)
    incremental = features.train_projection_features(contract, space, next_batch, fixed_tune,
                                                    epochs=1, base_state=first["state"])
    assert len(incremental["report"]["epochs"]) == 1
    assert incremental["report"]["training_targets_sha256"] != first["report"]["training_targets_sha256"]
    assert incremental["report"]["tuning_targets_sha256"] == first["report"]["tuning_targets_sha256"]
    assert incremental["state"]["tuning_targets_sha256"] == first["state"]["tuning_targets_sha256"]
    assert incremental["state"]["feature_space_sha256"] == first["state"]["feature_space_sha256"]
    assert incremental["report"]["base_state_sha256"] == features.digest(first["state"])
    assert sum(row["unknown_atoms"] for row in incremental["report"]["train_coverage"]) > 0
    assert space == basis_before and first["state"] == initial_state
    assert not incremental["report"]["heldout_canary"]
    # The original selection panel cannot become training material while
    # silently substituting another panel, or by placing it in both batches.
    with pytest.raises(features.ProjectionFeatureError, match="tuning|validation|leakage"):
        features.train_projection_features(contract, space, fixed_tune, [_ui(4)],
                                          epochs=1, base_state=first["state"])
    with pytest.raises(features.ProjectionFeatureError, match="tuning|validation|leakage"):
        features.train_projection_features(contract, space, fixed_tune, fixed_tune,
                                          epochs=1, base_state=first["state"])
    with pytest.raises(features.ProjectionFeatureError, match="tuning|validation|leakage"):
        features.train_projection_features(contract, space, next_batch, [_ui(4)],
                                          epochs=1, base_state=first["state"])
    # Even before any parent is provided, vocabulary-fitting sources are not
    # an independent panel for a later incremental training batch.
    with pytest.raises(features.ProjectionFeatureError, match="tuning|validation|leakage"):
        features.train_projection_features(contract, space, next_batch, original_train, epochs=1)

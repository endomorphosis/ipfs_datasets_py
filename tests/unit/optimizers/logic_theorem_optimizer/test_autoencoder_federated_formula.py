"""Real CPU local/owner branches and honest provisional formula aggregation."""
from dataclasses import replace
import copy
import hashlib
import json

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated_formula as federation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    ClientSpec, make_client_update, parameter_digest,
)


def row(identifier, sign=1.0, *, actor="agency"):
    latent = [sign] + [0.0] * 383
    return {"id": identifier, "source_text": identifier + " authored source.", "latent": latent,
            "embedding": [0.6 * number for number in latent], "canonical_ir": {"rules": [{
                "modality": "O" if sign > 0 else "F", "actor": actor, "action": "disclose",
                "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}}


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def base(tmp_path):
    binding = {"domain": "legal_ir", "lineage_id": "current_legal_v2", "dimension": 384,
               "runtime_profile": "test_authored_raw_core/v1", "core_sha256": "a" * 64}
    original = [row("parent-positive"), row("parent-negative", -1.0)]
    with federation._cpu():
        checkpoint = learning.build_checkpoint(binding, original, [], hidden_size=8,
            token_embedding_dim=8, projection_width=2, batch_size=2, learning_rate=0.005)
        checkpoint = learning.train(checkpoint, original, [], epochs=1,
                                    max_seconds=30, max_optimizer_steps=1)["checkpoint"]
        path = tmp_path / "parent.json"
        receipt = learning.save_checkpoint(checkpoint, path)
    return federation.load_formula_base(path, expected_sha256=receipt["sha256"])


def prepared_round(base, *, max_local_steps=1):
    rows_a = [row("client-a")]
    rows_b = [row("client-b-positive"), row("client-b-negative", -1.0), row("client-b-third")]
    clients = (ClientSpec("a", len(rows_a), federation.formula_local_data_digest(rows_a, [])),
               ClientSpec("b", len(rows_b), federation.formula_local_data_digest(rows_b, [])))
    round_spec = federation.create_formula_round(base, round_id="round-1", model_id="legal-384d",
        clients=clients, embedding_producer_sha256="e" * 64, max_local_steps=max_local_steps)
    return round_spec, rows_a, rows_b


def manual_updates(round_spec, *, first=4.0, second=0.0):
    parameter = "output.bias"
    return [make_client_update(round_spec, "a", {parameter: {0: first}}, local_steps=1,
                              local_data_sha256=round_spec.clients[0].local_data_sha256),
            make_client_update(round_spec, "b", {parameter: {0: second}}, local_steps=1,
                              local_data_sha256=round_spec.clients[1].local_data_sha256)]


def test_real_local_branch_resets_optimizer_and_trains_new_corpus(base):
    round_spec, rows_a, _ = prepared_round(base)
    parent = base.head
    result = federation.train_formula_client(base, round_spec, "a", rows_a, [],
        local_data_sha256=round_spec.clients[0].local_data_sha256, max_seconds=30)
    assert base.head == parent
    assert result.branch_receipt["historical_resume"] is False
    assert result.branch_receipt["initial_progress"] == {
        "epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    assert result.branch_receipt["initial_optimizer_parameters"] == {}
    assert result.branch_receipt["initial_parameters_sha256"] == round_spec.base_parameters_sha256
    assert result.update.local_steps == result.report["optimizer_steps"] == 1
    assert result.checkpoint["progress"]["optimizer_steps"] == 1
    assert result.checkpoint["training_count"] == 1
    assert result.checkpoint["training_manifest_sha256"] != parent["training_manifest_sha256"]
    assert result.checkpoint["binding"] == parent["binding"]
    assert result.checkpoint["codec"] == parent["codec"]
    assert result.checkpoint["config"] == parent["config"]
    assert result.report["parameter_evidence"]["projection"]["parameter_update_l2"] > 0
    assert result.report["parameter_evidence"]["decoder"]["parameter_update_l2"] > 0
    assert any(delta != 0 for coordinates in result.update.deltas.values() for delta in coordinates.values())
    result.checkpoint["model_state"]["output.bias"][0] = 999
    assert result.checkpoint["model_state"]["output.bias"][0] != 999


def test_json_double_parent_uses_actual_float32_basis_for_unchanged_local_weights(base, monkeypatch):
    raw_head = base.head
    raw_head["model_state"]["output.bias"][0] = 0.1
    raw = federation._raw(raw_head)
    base = federation.VerifiedFormulaBase(raw, digest_bytes(raw), "formula_head")
    round_spec, rows_a, _ = prepared_round(base)
    with federation._cpu():
        specs, initial = federation._parameters(base.head)
    assert initial["output.bias"][0] == torch.tensor(0.1, dtype=torch.float32).item()
    assert initial["output.bias"][0] != 0.1

    def unchanged_training(branch, *_args, **_kwargs):
        result = copy.deepcopy(branch)
        result["model_state"] = federation._model_state(specs, initial)
        result["progress"] = {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1}
        result["optimizer_state"] = base.head["optimizer_state"]
        return {"checkpoint": result, "report": {"optimizer_steps": 1}}

    monkeypatch.setattr(learning, "train", unchanged_training)
    result = federation.train_formula_client(base, round_spec, "a", rows_a, [],
        local_data_sha256=round_spec.clients[0].local_data_sha256)
    assert all(delta == 0.0 for coordinates in result.update.deltas.values() for delta in coordinates.values())


def test_actual_fedavg_weights_and_no_fabricated_resume_state(base, tmp_path):
    round_spec, _, _ = prepared_round(base)
    before = base.head["model_state"]["output.bias"][0]
    candidate = federation.aggregate_formula_round(base, round_spec, manual_updates(round_spec))
    expected = torch.tensor(before + 1.0, dtype=torch.float32).item()
    assert candidate.model_state["output.bias"][0] == expected
    assert candidate.payload["aggregation"]["total_sample_count"] == 4
    for name in ("optimizer_state", "progress", "training_manifest_sha256", "tuning_manifest_sha256"):
        assert candidate.payload[name] is None
    assert candidate.payload["qualified"] is False
    with federation._cpu(), pytest.raises(ValueError, match="closed latent checkpoint schema"):
        learning.validate_checkpoint(candidate.payload)
    path = tmp_path / "aggregate.json"
    receipt = federation.save_formula_candidate(candidate, path)
    restored = federation.load_formula_candidate(path, expected_sha256=receipt["sha256"], base=base)
    assert restored.payload == candidate.payload
    restored.model_state["output.bias"][0] = 888
    assert restored.model_state["output.bias"][0] == expected


def test_real_owner_step_finalizes_separate_child_with_honest_progress(base):
    round_spec, _, _ = prepared_round(base)
    candidate = federation.aggregate_formula_round(base, round_spec, manual_updates(round_spec, first=0.1))
    owner_rows = [row("owner-positive"), row("owner-negative", -1.0)]
    previous_threads = torch.get_num_threads()
    finalized = federation.finalize_with_owner_training(candidate, owner_rows, [],
        owner_data_sha256=federation.formula_local_data_digest(owner_rows, []),
        max_optimizer_steps=1, max_seconds=30)
    assert torch.get_num_threads() == previous_threads
    checkpoint, receipt = finalized["checkpoint"], finalized["receipt"]
    assert receipt["owner_optimizer_steps"] == checkpoint["progress"]["optimizer_steps"] == 1
    assert receipt["initial_parameters_sha256"] == candidate.payload["aggregation"]["parameters_sha256"]
    assert receipt["final_parameters_sha256"] != receipt["initial_parameters_sha256"]
    assert receipt["aggregate_artifact_sha256"] == candidate.candidate_sha256
    assert receipt["historical_resume"] is False and receipt["core_changed"] is False
    assert checkpoint["binding"] == base.head["binding"]
    assert checkpoint["training_manifest_sha256"] == learning.checkpoint_digest(owner_rows)
    assert checkpoint["optimizer_state"]["parameters"]
    assert all(item["step"] == 1 for item in checkpoint["optimizer_state"]["parameters"].values())
    assert checkpoint["model_state"] != candidate.model_state
    with federation._cpu():
        learning.validate_checkpoint(checkpoint, expected_binding=base.head["binding"])
        result = learning.infer(checkpoint, [{name: owner_rows[0][name]
                                            for name in ("id", "source_text", "latent")}])
    assert result["rows"][0]["reason"] != "untrained_formula_head"
    assert checkpoint["qualified"] is False and receipt["qualified"] is False


@pytest.mark.parametrize("change", ["digest", "count", "target", "split", "steps"])
def test_unapproved_local_corpus_and_vocabulary_or_bounds_rejected(base, change):
    round_spec, rows_a, _ = prepared_round(base)
    options = {"local_data_sha256": round_spec.clients[0].local_data_sha256}
    tuning = []
    if change == "digest":
        rows_a[0]["latent"][0] += 1
    elif change == "count":
        round_spec = replace(round_spec, clients=(replace(round_spec.clients[0], sample_count=2),
                                                  round_spec.clients[1]))
    elif change == "target":
        rows_a[0]["canonical_ir"]["rules"][0]["actor"] = "unseen-actor"
    elif change == "split":
        tuning = copy.deepcopy(rows_a)
    else:
        options["max_optimizer_steps"] = 2
    with pytest.raises(ValueError):
        federation.train_formula_client(base, round_spec, "a", rows_a, tuning, **options)


@pytest.mark.parametrize("field,value", [
    ("base_sha256", "b" * 64), ("architecture", "other-core-config-codec"),
    ("lineage_id", "legacy_hub_v1"), ("runtime_profile", "old-resume"),
    ("dimension", 8), ("base_parameters_sha256", "f" * 64),
])
def test_round_cannot_mix_core_profiles_or_lineages(base, field, value):
    round_spec, _, _ = prepared_round(base)
    with pytest.raises(ValueError, match="formula round"):
        federation.aggregate_formula_round(base, replace(round_spec, **{field: value}),
                                            manual_updates(round_spec))


def test_changed_source_or_parent_bytes_are_rejected(base, monkeypatch):
    round_spec, _, _ = prepared_round(base)
    original = federation._source_profile()
    monkeypatch.setattr(federation, "_source_profile", lambda: {**original, "adapter_sha256": "f" * 64})
    with pytest.raises(ValueError, match="formula round"):
        federation.aggregate_formula_round(base, round_spec, manual_updates(round_spec))
    with pytest.raises(ValueError, match="SHA256 differs"):
        replace(base, _artifact_bytes=b"{}")


@pytest.mark.parametrize("field,value", [("progress", {"optimizer_steps": 1}),
    ("optimizer_state", {}), ("qualified", True), ("binding", {}), ("sources", {})])
def test_provisional_candidate_rejects_forged_progress_authority_and_context(base, field, value):
    round_spec, _, _ = prepared_round(base)
    candidate = federation.aggregate_formula_round(base, round_spec, manual_updates(round_spec))
    payload = candidate.payload
    payload[field] = value
    with pytest.raises(ValueError):
        federation.FederatedFormulaCandidate(base, federation._raw(payload))


@pytest.mark.parametrize("steps", [0, -1, True, 100001])
def test_owner_finalization_requires_real_positive_step_budget(base, steps):
    round_spec, _, _ = prepared_round(base)
    candidate = federation.aggregate_formula_round(base, round_spec, manual_updates(round_spec))
    rows = [row("owner")]
    with pytest.raises(ValueError, match="actual optimizer step"):
        federation.finalize_with_owner_training(candidate, rows, [],
            owner_data_sha256=federation.formula_local_data_digest(rows, []), max_optimizer_steps=steps)


def test_owner_finalization_rejects_uncommitted_corpus(base):
    round_spec, _, _ = prepared_round(base)
    candidate = federation.aggregate_formula_round(base, round_spec, manual_updates(round_spec))
    with pytest.raises(ValueError, match="owner corpus digest differs"):
        federation.finalize_with_owner_training(candidate, [row("owner")], [], owner_data_sha256="f" * 64)


def test_core_row_derivation_requires_full_package(base):
    with pytest.raises(ValueError, match="complete verified Legal package"):
        federation.prepare_legal384_formula_rows(base, [], expected_embedding_producer_sha256="e" * 64)


def test_complete_legal384_package_load_and_final_head_recomposition(tmp_path):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package as package
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    contract = {"model_id": "authored-384d-test", "revision": "test-v1", "dimension": 384}
    fixture = [{"id": "package-positive", "source_text": "The agency shall disclose records.",
                "embedding": [1.0] + [0.0] * 383},
               {"id": "package-negative", "source_text": "The agency shall not disclose records.",
                "embedding": [-1.0] + [0.0] * 383}]
    with federation._cpu():
        model = current_v2.Autoencoder(compute_device="cpu")
        samples = package._rows(fixture, contract)
        targets = [{"id": item["id"], "source_text": item["source_text"],
                    "canonical_ir": row(item["id"], 1 if index == 0 else -1)["canonical_ir"]}
                   for index, item in enumerate(fixture)]
        rows = joint._rows(model, samples, targets)
        checkpoint = learning.build_checkpoint(joint._core_binding(model), rows, [],
            hidden_size=8, token_embedding_dim=8, projection_width=2, batch_size=2)
        checkpoint = learning.train(checkpoint, rows, [], epochs=1, max_seconds=30,
                                    max_optimizer_steps=1)["checkpoint"]
        model.attach_formula_checkpoint(checkpoint)
        parent = package.build_package(tmp_path / "parent-package", model=model,
            core_options={"compute_device": "cpu"}, embedding_contract=contract,
            fixture_rows=fixture, provenance={"scope": "synthetic-real-CPU-test"})
    base = federation.load_legal384_formula_base(parent["path"], expected_sha256=parent["sha256"])
    source_rows = [{**item, "canonical_ir": targets[index]["canonical_ir"]}
                   for index, item in enumerate(fixture)]
    derived = federation.prepare_legal384_formula_rows(base, source_rows,
        expected_embedding_producer_sha256=base.embedding_producer_sha256)
    assert derived == rows
    derived[0]["latent"][0] += 1000
    assert federation.prepare_legal384_formula_rows(base, source_rows,
        expected_embedding_producer_sha256=base.embedding_producer_sha256) == rows
    with pytest.raises(ValueError, match="embedding producer"):
        federation.prepare_legal384_formula_rows(base, source_rows,
            expected_embedding_producer_sha256="f" * 64)
    with pytest.raises(ValueError, match="closed id/source_text"):
        federation.prepare_legal384_formula_rows(base, [{**source_rows[0], "latent": [0.0] * 384}],
            expected_embedding_producer_sha256=base.embedding_producer_sha256)
    unknown_target = copy.deepcopy(source_rows)
    unknown_target[0]["canonical_ir"]["rules"][0]["actor"] = "new-unapproved-actor"
    with pytest.raises(ValueError):
        federation.prepare_legal384_formula_rows(base, unknown_target,
            expected_embedding_producer_sha256=base.embedding_producer_sha256)
    client_data = federation.formula_local_data_digest(rows, [])
    round_spec = federation.create_formula_round(base, round_id="package-round", model_id="legal-384d",
        clients=(ClientSpec("a", len(rows), client_data),),
        embedding_producer_sha256=base.embedding_producer_sha256)
    with pytest.raises(ValueError, match="embedding producer"):
        federation.create_formula_round(base, round_id="wrong-embedding", model_id="legal-384d",
            clients=round_spec.clients, embedding_producer_sha256="f" * 64)
    client = federation.train_formula_client(base, round_spec, "a", rows, [], local_data_sha256=client_data)
    candidate = federation.aggregate_formula_round(base, round_spec, [client.update])
    finalized = federation.finalize_with_owner_training(candidate, rows, [], owner_data_sha256=client_data)
    with federation._cpu():
        unchanged = current_v2.Autoencoder(state=current_v2.TrainingState.from_dict(base.package_payload["core_state"]),
                                          **base.package_payload["core_options"])
        assert joint._core_binding(unchanged) == base.head["binding"]
        unchanged.attach_formula_checkpoint(finalized["checkpoint"])
        child = package.build_package(tmp_path / "child-package", model=unchanged,
            core_options=base.package_payload["core_options"], embedding_contract=contract,
            fixture_rows=fixture, provenance={"federation_finalization": finalized["receipt"]})
        restored = package.load_package(child["path"], expected_sha256=child["sha256"])
        result = restored.infer(fixture)
    assert result["training_steps"] == 0
    assert restored.describe()["learned_formula_head"] is True
    assert child["qualified"] is False
    assert finalized["receipt"]["owner_optimizer_steps"] > 0

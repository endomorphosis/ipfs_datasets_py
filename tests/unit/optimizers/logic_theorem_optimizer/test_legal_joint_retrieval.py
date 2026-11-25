"""Real contrastive updates, query isolation, exclusions and artifact binding."""
import copy
import hashlib
import importlib
import json

import pytest

torch = pytest.importorskip("torch")
retrieval = importlib.import_module(
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_joint_retrieval")


def rows():
    result = []
    for group in range(4):
        for modality_index, modality in enumerate(("O", "P", "F")):
            index = group * 3 + modality_index
            source = f"Agent{group} {['shall', 'may', 'shall not'][modality_index]} file record{group}."
            result.append({"id": f"r{index}", "source_text": source,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "family_group": f"group{group}",
                "embedding": [float(i == index) for i in range(384)],
                "formal_embedding": [float(i == index + 32) for i in range(384)],
                "canonical_ir": {"rules": [{"modality": modality, "actor": f"agent{group}",
                    "action": "file", "object": f"record{group}", "conditions": [],
                    "exceptions": [], "temporal": []}]}})
    return result


def queries(selected=None):
    return [{key: row[key] for key in ("id", "source_text", "embedding", "family_group")}
            for row in (selected or rows())]


@pytest.fixture(scope="module", autouse=True)
def threads():
    original = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(original)


@pytest.fixture(scope="module")
def trained():
    return retrieval.train_retriever(rows(), steps=60, seed=2718, learning_rate=.02, joint_dimension=16)


def test_real_updates_fit_permuted_modalities_without_mutating_training_inputs(trained):
    original = rows()
    before = copy.deepcopy(original)
    untrained = retrieval.train_retriever(original, steps=0, seed=2718, joint_dimension=16)
    assert original == before
    assert untrained["report"]["optimizer_steps"] == 0
    assert not untrained["report"]["training_executed"]
    report = trained["report"]
    assert report["optimizer_steps"] == len(report["losses"]) == 60
    assert set(report["changed_parameter_names"]) == {"source.weight", "source.bias", "formal.weight", "formal.bias"}
    assert report["losses"][-1] < report["losses"][0] * .2
    assert report["training_recall_at_1"] == 1
    assert report["recall_scope"] == "resubstitution_on_training_index_only"
    assert not report["proofbridge_reproduction"]
    assert trained["checkpoint"]["training_modalities"] == {"O": 4, "P": 4, "F": 4}


@pytest.mark.parametrize("mode", ["raw", "joint", "random"])
def test_family_and_source_exclusions_are_enforced_and_context_has_auditable_training_origin(trained, mode):
    index = rows()
    model = retrieval.LegalJointRetriever(index, trained["checkpoint"])
    result = model.retrieve(queries(), mode=mode, top_k=3)
    by_id = {row["id"]: row for row in index}
    for query, returned in zip(queries(), result["rows"]):
        assert len(returned["retrieved_ids"]) == 3
        assert returned["eligible_rows"] == 9
        assert query["id"] not in returned["retrieved_ids"]
        assert all(by_id[identifier]["family_group"] != query["family_group"]
                   for identifier in returned["retrieved_ids"])
        expected = sum((torch.tensor(by_id[identifier]["formal_embedding"]) * weight
                        for identifier, weight in zip(returned["retrieved_ids"], returned["weights"])))
        assert torch.allclose(torch.tensor(returned["context"]), expected)
        assert returned["source_sha256"] == hashlib.sha256(query["source_text"].encode()).hexdigest()
        assert not returned["query_target_access"] and returned["training_target_exemplars_accessed"]
    assert not result["target_access"] and not result["teacher_forcing"]


def test_joint_query_uses_trained_cross_modal_weights_and_requires_no_query_target(trained, monkeypatch):
    model = retrieval.LegalJointRetriever(rows(), trained["checkpoint"])
    query = {**queries()[5], "id": "heldout", "source_text": "A new expression.", "family_group": "heldout-group"}
    def prohibited(*args, **kwargs):
        raise AssertionError("query attempted canonical-target validation or training")
    monkeypatch.setattr(retrieval.codec, "_rule", prohibited)
    monkeypatch.setattr(retrieval, "train_retriever", prohibited)
    returned = model.retrieve([query], mode="joint", top_k=1)["rows"][0]
    assert returned["retrieved_ids"] == ["r5"]
    assert returned["context"] == rows()[5]["formal_embedding"]
    with pytest.raises(ValueError, match="target-free"):
        model.retrieve([{**query, "canonical_ir": rows()[5]["canonical_ir"]}])
    with pytest.raises(ValueError, match="target-free"):
        model.retrieve([{**query, "formal_embedding": rows()[5]["formal_embedding"]}])


def test_random_control_is_batch_order_invariant_and_uniform(trained):
    model = retrieval.LegalJointRetriever(rows(), trained["checkpoint"])
    together = model.retrieve(queries()[:2], mode="random")["rows"]
    separately = [model.retrieve([query], mode="random")["rows"][0] for query in queries()[:2]]
    reverse = model.retrieve(list(reversed(queries()[:2])), mode="random")["rows"]
    assert together == separately == list(reversed(reverse))
    assert together[0]["weights"] == [pytest.approx(1 / 3)] * 3


def test_even_disabled_family_exclusion_never_returns_identical_source_or_id(trained):
    model = retrieval.LegalJointRetriever(rows(), trained["checkpoint"])
    query = {**queries()[0], "id": "different-id", "source_text": queries()[0]["source_text"].upper()}
    returned = model.retrieve([query], top_k=11, exclude_same_family=False)["rows"][0]
    assert "r0" not in returned["retrieved_ids"]
    assert returned["eligible_rows"] == 11
    with pytest.raises(ValueError, match="insufficient"):
        model.retrieve(queries()[:1], top_k=10)


@pytest.mark.parametrize("kind", ["id", "source", "target", "source_hash", "nonfinite", "zero", "modality", "extra"])
def test_training_contract_rejects_ambiguous_or_invalid_pairs(kind):
    index = rows()
    if kind == "id":
        index[1]["id"] = index[0]["id"]
    elif kind == "source":
        index[1]["source_text"] = index[0]["source_text"].upper()
        index[1]["source_sha256"] = hashlib.sha256(index[1]["source_text"].encode()).hexdigest()
    elif kind == "target":
        index[1]["canonical_ir"] = index[0]["canonical_ir"]
    elif kind == "source_hash":
        index[0]["source_sha256"] = "0" * 64
    elif kind == "nonfinite":
        index[0]["embedding"][0] = float("nan")
    elif kind == "zero":
        index[0]["formal_embedding"] = [0.] * 384
    elif kind == "modality":
        index = [row for row in index if row["canonical_ir"]["rules"][0]["modality"] != "F"]
    else:
        index[0]["target_hint"] = "unsupported metadata"
    with pytest.raises(ValueError):
        retrieval.train_retriever(index, steps=0)


def test_checkpoint_roundtrip_and_hash_binding_reject_target_or_weight_tampering(trained, tmp_path):
    checkpoint = trained["checkpoint"]
    path = tmp_path / "retrieval.json"
    digest = retrieval.save_checkpoint(checkpoint, path)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert retrieval.load_checkpoint(path, expected_sha256=digest) == checkpoint
    with pytest.raises(FileExistsError):
        retrieval.save_checkpoint(checkpoint, path)
    with pytest.raises(ValueError, match="digest differs"):
        retrieval.load_checkpoint(path, expected_sha256="0" * 64)
    changed = rows()
    changed[0]["canonical_ir"]["rules"][0]["actor"] = "other actor"
    with pytest.raises(ValueError, match="index digest"):
        retrieval.LegalJointRetriever(changed, checkpoint)
    bad = copy.deepcopy(checkpoint)
    bad["model_state"]["source.weight"][0][0] = float("inf")
    with pytest.raises(ValueError):
        retrieval.validate_checkpoint(bad)
    bad = copy.deepcopy(checkpoint)
    bad["config"]["torch_version"] = "different"
    with pytest.raises(ValueError, match="config/runtime"):
        retrieval.validate_checkpoint(bad)
    bad = copy.deepcopy(checkpoint)
    bad["implementation"]["files"]["legal_joint_retrieval.py"] = "0" * 64
    with pytest.raises(ValueError, match="source pins"):
        retrieval.validate_checkpoint(bad)


def test_frozen_instance_rejects_model_or_index_mutation(trained):
    model = retrieval.LegalJointRetriever(rows(), trained["checkpoint"])
    external = model.checkpoint
    external["model_state"]["source.bias"][0] = 123.
    model.retrieve(queries()[:1])
    with torch.no_grad():
        model._model.source.bias[0] += 1
    with pytest.raises(ValueError, match="model mutated"):
        model.retrieve(queries()[:1])
    model = retrieval.LegalJointRetriever(rows(), trained["checkpoint"])
    model._rows[0]["formal_embedding"][0] = 1.
    with pytest.raises(ValueError, match="index mutated"):
        model.retrieve(queries()[:1])


def test_duplicate_json_keys_and_symlinks_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"a","schema":"b"}')
    with pytest.raises(ValueError, match="duplicate"):
        retrieval.load_checkpoint(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    try:
        with pytest.raises(ValueError, match="regular"):
            retrieval.load_checkpoint(link)
    finally:
        link.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def reviewed_fixture_owner():
    """Reuse the canonical owner's explicitly fictional reviewed ledger fixture."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / (
        "unit/logic/formalization/autoencoder/test_alignment_relation_mask_handoff.py")
    spec = importlib.util.spec_from_file_location("_reviewed_retrieval_handoff_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reviewed_case(reviewed_fixture_owner):
    return reviewed_fixture_owner.fixtures.reviewed_pair_fixture_v2()


def _reviewed_case_arguments(owner, case):
    return owner.reviewed_mask_arguments_v2(case)


@pytest.fixture(scope="module")
def reviewed_trained(reviewed_fixture_owner, reviewed_case):
    args, inputs = _reviewed_case_arguments(reviewed_fixture_owner, reviewed_case)
    return retrieval.train_reviewed_retriever(*args, **inputs, steps=20, seed=2718,
        learning_rate=.003, joint_dimension=16)


def test_reviewed_training_uses_rectangular_multiple_positives_without_unknown_negatives(
        reviewed_fixture_owner, reviewed_case, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_masked_contrastive as objective
    args, inputs = _reviewed_case_arguments(reviewed_fixture_owner, reviewed_case)
    before = copy.deepcopy((args, inputs))
    original_loss = objective.masked_multi_positive_contrastive_loss
    calls = []
    def observe(source, formal, **values):
        calls.append((tuple(source.shape), tuple(formal.shape), values["positive_mask"].tolist(),
                      values["permitted_negative_mask"].tolist()))
        return original_loss(source, formal, **values)
    monkeypatch.setattr(objective, "masked_multi_positive_contrastive_loss", observe)
    before_rng = torch.get_rng_state().clone()
    outcome = retrieval.train_reviewed_retriever(*args, **inputs, steps=3, joint_dimension=8)
    assert len(calls) == 3  # The canonical objective already includes both directions.
    assert all(call == ((2, 8), (3, 8), [[True, True, False], [False, False, True]],
                        [[False, False, True], [False, False, False]]) for call in calls)
    assert (args, inputs) == before and torch.equal(torch.get_rng_state(), before_rng)
    report = outcome["report"]
    assert report["unknown_pair_count"] == report["analogy_retrieval_only_pair_count"] == 1
    assert report["fixture_only"] and report["training_executed"] and report["model_executed"]
    assert report["input_embedding_runtime_computation_proven"] is False
    assert not report["admitted"] and not report["proof_authority"] and not report["qualified"]
    assert report["resource_admission_scope"] == "caller_owned_not_validated_here"


def test_reviewed_real_parameter_updates_and_restore_are_numerical_not_semantic_claims(reviewed_trained):
    report = reviewed_trained["report"]
    assert len(report["losses"]) == report["optimizer_steps"] == 20
    assert all(torch.isfinite(torch.tensor(value)) for value in report["losses"])
    assert set(report["changed_parameter_names"]) == {"source.weight", "source.bias", "formal.weight", "formal.bias"}
    assert report["losses"][-1] < report["losses"][0]
    assert report["checkpoint_restore_verified"] is True
    assert report["previous_task_retention_evaluated"] is report["heldout_evaluation_performed"] is False
    assert report["recall_scope"] == "reviewed_training_grid_resubstitution_only"
    assert report["legacy_retrieval_index_compatible"] is False
    torch_owner, restored = retrieval._restore(reviewed_trained["checkpoint"])
    assert retrieval._state(restored) == reviewed_trained["checkpoint"]["model_state"]
    assert all(parameter.device.type == "cpu" and parameter.dtype == torch_owner.float32
               for parameter in restored.parameters())


def test_reviewed_zero_steps_preserve_seeded_state_without_claiming_training(
        reviewed_fixture_owner, reviewed_case):
    args, inputs = _reviewed_case_arguments(reviewed_fixture_owner, reviewed_case)
    outcome = retrieval.train_reviewed_retriever(*args, **inputs, steps=0, joint_dimension=8)
    checkpoint, report = outcome["checkpoint"], outcome["report"]
    assert report["losses"] == report["changed_parameter_names"] == []
    assert report["training_executed"] is False and report["model_executed"] is True
    assert checkpoint["initial_model_state_sha256"] == retrieval.checkpoint_digest(checkpoint["model_state"])
    assert checkpoint["schema"] == retrieval.REVIEWED_SCHEMA
    assert checkpoint["progress"]["optimizer_state_retained"] is False


@pytest.mark.parametrize("damage", ["missing_pair_review", "missing_current_endpoint", "preparation_pin", "bare_ready_flags"])
def test_reviewed_training_denies_unreplayed_inputs_before_model_or_optimizer(
        reviewed_fixture_owner, reviewed_case, monkeypatch, damage):
    case = reviewed_fixture_owner.reviewed_pair_clone_v2(reviewed_case)
    if damage == "missing_pair_review": case["reviews"] = []
    if damage == "missing_current_endpoint": case["current_endpoint_observations"] = {}
    args, inputs = _reviewed_case_arguments(reviewed_fixture_owner, case)
    if damage == "preparation_pin": inputs["expected_preparation_sha256"] = "0" * 64
    if damage == "bare_ready_flags":
        args = ({"reviewed_objective_mask_ready": True, "objective_positive_mask": [[True]],
                 "objective_permitted_negative_mask": [[False]]}, *args[1:])
    def forbidden(*args, **kwargs):
        raise AssertionError("unreviewed input reached numerical allocation")
    monkeypatch.setattr(retrieval, "_model", forbidden)
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    with pytest.raises(ValueError):
        retrieval.train_reviewed_retriever(*args, **inputs, steps=1)


def test_reviewed_training_replays_after_updates_and_refuses_changed_authority(
        reviewed_fixture_owner, reviewed_case, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_relation_mask_handoff as handoff
    case = reviewed_fixture_owner.reviewed_pair_clone_v2(reviewed_case)
    args, inputs = _reviewed_case_arguments(reviewed_fixture_owner, case)
    original = handoff.compile_reviewed_train_relation_masks_v2
    calls = []
    def revoke_on_second_replay(*values, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            values[1]["keys"][0]["revoked_at_utc"] = case["at_time_utc"]
        return original(*values, **kwargs)
    monkeypatch.setattr(handoff, "compile_reviewed_train_relation_masks_v2", revoke_on_second_replay)
    with pytest.raises(ValueError):
        retrieval.train_reviewed_retriever(*args, **inputs, steps=1, joint_dimension=8)
    assert len(calls) == 2


@pytest.mark.parametrize("damage", ["state", "mask", "endpoint", "implementation", "runtime", "initialization"])
def test_reviewed_checkpoint_rejects_changed_numerical_and_handoff_identities(reviewed_trained, damage):
    checkpoint = copy.deepcopy(reviewed_trained["checkpoint"])
    if damage == "state": checkpoint["model_state"]["source.weight"][0][0] = float("inf")
    if damage == "mask": checkpoint["training_handoff"]["objective_positive_mask"][0][0] = False
    if damage == "endpoint": checkpoint["training_handoff"]["source_endpoints"][0]["id"] += "-changed"
    if damage == "implementation": checkpoint["implementation"]["legacy_numerical_owner"]["files"]["legal_joint_retrieval.py"] = "0" * 64
    if damage == "runtime": checkpoint["config"]["torch_version"] = "changed"
    if damage == "initialization": checkpoint["initial_model_state_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        retrieval.validate_checkpoint(checkpoint)


def test_reviewed_checkpoint_save_load_preserves_historical_asset_not_current_permission(reviewed_trained, tmp_path):
    checkpoint = reviewed_trained["checkpoint"]
    path = tmp_path / "reviewed-retrieval-v2.json"
    digest = retrieval.save_checkpoint(checkpoint, path)
    assert retrieval.load_checkpoint(path, expected_sha256=digest) == checkpoint
    assert checkpoint["training_handoff"]["actual_fit_authorized"] is False
    assert checkpoint["training_handoff"]["runtime_computation_proven"] is False
    with pytest.raises(ValueError, match="v1 checkpoint"):
        retrieval.LegalJointRetriever(rows(), checkpoint)


def test_reviewed_training_keeps_legacy_asset_isolated_without_claiming_retention(
        trained, reviewed_fixture_owner, reviewed_case):
    checkpoint = copy.deepcopy(trained["checkpoint"])
    model = retrieval.LegalJointRetriever(rows(), checkpoint)
    before = model.retrieve(queries()[:1], top_k=1)
    args, inputs = _reviewed_case_arguments(reviewed_fixture_owner, reviewed_case)
    outcome = retrieval.train_reviewed_retriever(*args, **inputs, steps=1, joint_dimension=8)
    assert checkpoint == trained["checkpoint"] and model.retrieve(queries()[:1], top_k=1) == before
    assert outcome["report"]["previous_task_retention_evaluated"] is False


@pytest.fixture(scope="module")
def genuine_selected_legacy_producer():
    """Execute exactly the retained owner through its actual source loader.

    Relative dependencies use the genuine already-imported parent package;
    no package initializers or package namespace modules are synthesized.
    This tiny constructed producer is not an old scientific training result.
    """
    import importlib.util
    import importlib.machinery
    from pathlib import Path
    import sys
    source = Path(__file__).resolve().parents[3] / "fixtures/legal_ir/joint_retrieval/legacy_source_577698.py"
    raw = source.read_bytes()
    assert len(raw) == 20198 and hashlib.sha256(raw).hexdigest() == retrieval.SELECTED_LEGACY_OWNER_SHA256
    name = "_retained_legal_joint_retrieval_577698"
    spec = importlib.util.spec_from_file_location(name, source)
    assert isinstance(spec.loader, importlib.machinery.SourceFileLoader)
    old = importlib.util.module_from_spec(spec)
    old.__package__ = retrieval.__package__
    assert old.__package__ in sys.modules
    sys.modules[name] = old
    try:
        spec.loader.exec_module(old)
        assert old.__file__ == old.__spec__.origin == old.train_retriever.__code__.co_filename == str(source)
        # Generate the producer header from actual retained code, not by
        # replacing a header in a new-source checkpoint.
        result = old.train_retriever(rows(), steps=1, seed=2718, joint_dimension=16)
        assert result["checkpoint"]["implementation"]["files"]["legal_joint_retrieval.py"] == retrieval.SELECTED_LEGACY_OWNER_SHA256
        yield {"owner": old, "checkpoint": result["checkpoint"], "report": result["report"]}
    finally:
        sys.modules.pop(name, None)


def test_selected_legacy_port_is_explicit_and_preserves_genuine_producer(genuine_selected_legacy_producer):
    checkpoint = genuine_selected_legacy_producer["checkpoint"]
    before = copy.deepcopy(checkpoint)
    with pytest.raises(ValueError, match="source pins"):
        retrieval.validate_checkpoint(checkpoint)
    profile = retrieval.select_legacy_source_profile(checkpoint,
        expected_checkpoint_sha256=retrieval.checkpoint_digest(checkpoint))
    assert profile["historical_producer_implementation"] == checkpoint["implementation"]
    assert profile["runtime_implementation"] == retrieval._implementation()
    assert profile["numerical_ast_identity_verified"] is True
    assert profile["runtime_numerical_parity_verified"] is False
    assert profile["qualification_state"] == "pending_genuine_old_source_weight_and_query_parity"
    assert profile["checkpoint_rewritten"] is profile["legal_admission"] is profile["model_use_permission_granted"] is False
    _, current = retrieval._restore(checkpoint, source_profile=profile)
    _, historical = genuine_selected_legacy_producer["owner"]._restore(checkpoint)
    assert retrieval._state(current) == genuine_selected_legacy_producer["owner"]._state(historical)
    assert checkpoint == before


@pytest.mark.parametrize("mode", ["raw", "joint", "random"])
def test_selected_legacy_real_source_weights_and_query_outputs_match(genuine_selected_legacy_producer, mode):
    checkpoint = genuine_selected_legacy_producer["checkpoint"]
    original = genuine_selected_legacy_producer["owner"].LegalJointRetriever(rows(), checkpoint)
    profile = retrieval.select_legacy_source_profile(checkpoint,
        expected_checkpoint_sha256=retrieval.checkpoint_digest(checkpoint))
    ported = retrieval.LegalJointRetriever(rows(), checkpoint, source_profile=profile)
    expected = original.retrieve(queries()[:2], mode=mode, top_k=3)
    result = ported.retrieve(queries()[:2], mode=mode, top_k=3)
    assert result.pop("runtime_source_profile") == profile
    assert result == expected
    assert ported.checkpoint == checkpoint
    assert ported.runtime_source_profile == profile


@pytest.mark.parametrize("damage", ["arbitrary_owner", "other_dependency", "wrong_schema", "asset_after_selection", "runtime_profile"])
def test_selected_legacy_port_refuses_mixed_or_unknown_recipe(genuine_selected_legacy_producer, damage):
    checkpoint = copy.deepcopy(genuine_selected_legacy_producer["checkpoint"])
    profile = retrieval.select_legacy_source_profile(checkpoint,
        expected_checkpoint_sha256=retrieval.checkpoint_digest(checkpoint))
    if damage == "arbitrary_owner": checkpoint["implementation"]["files"]["legal_joint_retrieval.py"] = "0" * 64
    if damage == "other_dependency": checkpoint["implementation"]["files"]["legal_formula_codec.py"] = "0" * 64
    if damage == "wrong_schema": checkpoint["schema"] = retrieval.REVIEWED_SCHEMA
    if damage == "asset_after_selection": checkpoint["model_state"]["source.bias"][0] += 1
    if damage == "runtime_profile": profile["runtime_implementation"]["files"]["legal_joint_retrieval.py"] = "0" * 64
    with pytest.raises(ValueError):
        if damage in {"arbitrary_owner", "other_dependency", "wrong_schema"}:
            retrieval.select_legacy_source_profile(checkpoint,
                expected_checkpoint_sha256=retrieval.checkpoint_digest(checkpoint))
        else:
            retrieval.validate_checkpoint(checkpoint, source_profile=profile)


def test_selected_legacy_port_does_not_rewrite_saved_asset(genuine_selected_legacy_producer, tmp_path):
    checkpoint = genuine_selected_legacy_producer["checkpoint"]
    digest = retrieval.checkpoint_digest(checkpoint)
    profile = retrieval.select_legacy_source_profile(checkpoint, expected_checkpoint_sha256=digest)
    path = tmp_path / "selected-legacy.json"
    file_digest = retrieval.save_checkpoint(checkpoint, path, source_profile=profile)
    assert path.read_bytes() == genuine_selected_legacy_producer["owner"]._raw(checkpoint) + b"\n"
    assert retrieval.load_checkpoint(path, expected_sha256=file_digest, source_profile=profile) == checkpoint
    assert retrieval.checkpoint_digest(checkpoint) == digest
    with pytest.raises(ValueError, match="source pins"):
        retrieval.load_checkpoint(path, expected_sha256=file_digest)


@pytest.mark.parametrize("before, after", [("similarities = source_projected @ formal_projected.T", "similarities = formal_projected @ source_projected.T"),
    ('row["family_group"] != query["family_group"]', 'row["family_group"] == query["family_group"]')])
def test_selected_legacy_numerical_ast_policy_detects_math_or_exclusion_changes(before, after):
    from pathlib import Path
    raw = Path(retrieval.__file__).read_text()
    assert raw.count(before) == 1
    assert retrieval._legacy_numerical_ast_identity(raw.encode()) == retrieval.SELECTED_LEGACY_NUMERICAL_AST_SHA256
    assert retrieval._legacy_numerical_ast_identity(raw.replace(before, after).encode()) != retrieval.SELECTED_LEGACY_NUMERICAL_AST_SHA256


def _reviewed_structural_query_fixture(owner, original, *, query=None,
        lineage_group_id="fixture:heldout-unrelated-family", admission_version="v2"):
    """Extend the existing toy ledger with a source-only held-out query."""
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    case = owner.reviewed_pair_clone_v2(original)
    inputs = case["preparation_inputs"]
    old = splits.LegalIRSplitManifest.from_mapping(inputs["split_manifest"])
    query = copy.deepcopy(query) if query is not None else {
        "id": "query:heldout", "source_text": "An unrelated fictional agency may inspect a lunar archive.",
        "split_sample_id": "sample:heldout-query"}
    sample = splits.LegalIRSplitExample.from_sample({"sample_id": query["split_sample_id"],
        "source_text": query["source_text"], "lineage_group_id": lineage_group_id})
    manifest = splits.LegalIRSplitManifest(examples=(*old.examples, sample),
        assignments={**old.assignments, sample.sample_id: splits.HOLDOUT_SPLIT}, config_digest=old.config_digest,
        protected_splits=old.protected_splits, metadata=old.metadata).to_dict()
    inputs["split_manifest"] = manifest
    split_sha = lanes._digest(manifest)
    inputs["expected_split_manifest_sha256"] = split_sha
    inputs["body"]["split_manifest_sha256"] = split_sha
    artifact_id = inputs["body"]["ledger_id"] + ":split"
    next(row for row in inputs["dependency_manifest"]["artifacts"] if row["artifact_id"] == artifact_id)["artifact_sha256"] = split_sha
    case["observed_artifacts"][artifact_id] = split_sha
    if admission_version == "v4":
        owner._refresh_reviewed_pair_ledger(case, "v4")
    elif admission_version == "v3":
        owner.refresh_reviewed_pair_ledger_v3(case)
    else:
        owner.refresh_reviewed_pair_ledger_v2(case)
    profile = copy.deepcopy(inputs["source_lane"]["profile"])
    request = {"source_text": query["source_text"], "context": {"role": "none_required", "text": "", "bindings": {},
        "sha256": hashlib.sha256(b"").hexdigest()}}
    vector = [1.0] + [0.0] * 383
    binding = {"id": query["id"], "input_sha256": lanes._digest(request),
        "encoder_text_sha256": hashlib.sha256(query["source_text"].encode()).hexdigest(),
        "status": "available", "reason": None, "vector_sha256": lanes._digest(vector),
        "upstream_vector_sha256": None, "token_receipt_sha256": None}
    row = {**binding, "input": request, "encoder_text": query["source_text"], "vector": vector,
        "producer_row_sha256": lanes._digest(binding)}
    producer = owner.fixtures.role(lanes.PRODUCER_SCHEMA, profile_sha256=lanes._digest(profile), rows=[binding],
        artifact_binding={"path": "never-opened-fictional-query-vectors.json", "bytes": 1, "sha256": "e" * 64})
    lane = owner.fixtures.role(lanes.SCHEMA, profile=profile, producer_receipt=producer, rows=[row])
    expected = {"profile_sha256": lanes._digest(profile), "producer_receipt_sha256": lanes._digest(producer),
        "inputs": [{"id": query["id"], "input_sha256": binding["input_sha256"]}]}
    return case, query, lane, expected


def _structural_call(model, owner, case, query, lane, expected, *, forbidden=None, **options):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    args, inputs = owner.reviewed_mask_arguments_v2(case)
    excluded = {query["id"]: []} if forbidden is None else forbidden
    return model.retrieve([query], *args, **inputs, query_source_lane=lane, expected_query_lane_bindings=expected,
        expected_query_split=splits.HOLDOUT_SPLIT, forbidden_reference_formal_sha256s=excluded,
        expected_forbidden_reference_sha256=retrieval.checkpoint_digest(excluded), **options)


@pytest.fixture(scope="module")
def reviewed_query_case(reviewed_fixture_owner, reviewed_case):
    return _reviewed_structural_query_fixture(reviewed_fixture_owner, reviewed_case)


@pytest.mark.parametrize("mode", ["raw", "joint", "random"])
def test_reviewed_checkpoint_retrieves_current_train_examples_for_source_only_queries(
        reviewed_trained, reviewed_fixture_owner, reviewed_query_case, mode):
    case, query, lane, expected = reviewed_query_case
    checkpoint = reviewed_trained["checkpoint"]
    model = retrieval.ReviewedLegalJointRetriever(checkpoint,
        expected_checkpoint_sha256=retrieval.checkpoint_digest(checkpoint))
    outcome = _structural_call(model, reviewed_fixture_owner, case, query, lane, expected, top_k=2, mode=mode)
    assert outcome["status"] == "retrieval_completed" and outcome["retrieved_count"] == 1
    row = outcome["rows"][0]
    assert row["status"] == "retrieved" and row["eligible_rows"] == 3
    vectors = {row["id"]: row["vector"] for row in case["preparation_inputs"]["formal_lane"]["rows"]}
    context = sum(torch.tensor(vectors[identifier]) * weight
        for identifier, weight in zip(row["retrieved_ids"], row["weights"], strict=True))
    assert torch.equal(torch.tensor(row["context"]), context)
    assert outcome["query_target_access"] is outcome["legal_applicability_verified"] is False
    assert outcome["controlling_authority_selected"] is outcome["decoder_context_admitted"] is False
    assert outcome["historical_training_requalification_performed"] is False
    assert outcome["current_index_differs_from_training"] is True
    assert model.checkpoint == checkpoint
    if mode == "random": assert row["weights"] == [pytest.approx(.5)] * 2


def test_reviewed_inference_excludes_opaque_reference_aliases_before_projection(
        reviewed_trained, reviewed_fixture_owner, reviewed_query_case, monkeypatch):
    case, query, lane, expected = reviewed_query_case
    model = retrieval.ReviewedLegalJointRetriever(reviewed_trained["checkpoint"],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained["checkpoint"]))
    # The first two endpoints are separately declared representations of the
    # same formal view. Its opaque reference hash excludes both aliases.
    forbidden_sha = case["preparation"]["formal_endpoints"][0]["formal_view_sha256"]
    seen, original = [], model._model.forward
    def observe(source, formal):
        seen.append(tuple(formal.shape))
        return original(source, formal)
    monkeypatch.setattr(model._model, "forward", observe)
    outcome = _structural_call(model, reviewed_fixture_owner, case, query, lane, expected,
        forbidden={query["id"]: [forbidden_sha]}, top_k=1)
    assert seen == [(1, 384)]
    assert outcome["rows"][0]["retrieved_ids"] == ["formal:2"]
    assert {item["id"] for item in outcome["rows"][0]["excluded_examples"]} == {"formal:0", "formal:1"}
    assert all(item["reason"] == "forbidden_reference_artifact" for item in outcome["rows"][0]["excluded_examples"])
    assert not outcome["inference_reference_content_forwarded"]


@pytest.mark.parametrize("damage", ["query_target", "hidden_context", "lane_pin", "query_source", "exposure_population", "reference_pin"])
def test_reviewed_inference_rejects_unbound_or_target_bearing_queries_before_forward(
        reviewed_trained, reviewed_fixture_owner, reviewed_query_case, monkeypatch, damage):
    case, query, lane, expected = reviewed_query_case
    query, lane, expected = copy.deepcopy((query, lane, expected))
    model = retrieval.ReviewedLegalJointRetriever(reviewed_trained["checkpoint"],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained["checkpoint"]))
    def forbidden(*args, **kwargs): raise AssertionError("ineligible query reached model projection")
    monkeypatch.setattr(model._model, "forward", forbidden)
    if damage == "query_target": query["canonical_ir"] = {"hidden": "reference target"}
    if damage == "hidden_context": lane["rows"][0]["input"]["context"]["bindings"] = {"canonical_ir": "reference target"}
    if damage == "lane_pin": expected["producer_receipt_sha256"] = "0" * 64
    if damage == "query_source": query["source_text"] += " altered"
    if damage == "exposure_population": query["split_sample_id"] = "unregistered-sample"
    if damage == "reference_pin":
        args, inputs = reviewed_fixture_owner.reviewed_mask_arguments_v2(case)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
        with pytest.raises(ValueError):
            model.retrieve([query], *args, **inputs, query_source_lane=lane, expected_query_lane_bindings=expected,
                expected_query_split=splits.HOLDOUT_SPLIT, forbidden_reference_formal_sha256s={query["id"]: []},
                expected_forbidden_reference_sha256="0" * 64, top_k=1)
    else:
        with pytest.raises(ValueError):
            _structural_call(model, reviewed_fixture_owner, case, query, lane, expected, top_k=1)


def test_reviewed_inference_replays_current_revocations_and_abstains_without_using_history(
        reviewed_trained, reviewed_fixture_owner, reviewed_query_case, monkeypatch):
    original_case, query, lane, expected = reviewed_query_case
    case = reviewed_fixture_owner.reviewed_pair_clone_v2(original_case)
    model = retrieval.ReviewedLegalJointRetriever(reviewed_trained["checkpoint"],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained["checkpoint"]))
    assert _structural_call(model, reviewed_fixture_owner, case, query, lane, expected, top_k=1)["retrieved_count"] == 1
    case["registry"]["keys"][0]["revoked_at_utc"] = case["at_time_utc"]
    reviewed_fixture_owner.reviewed_pair_resign_v2(case)
    def forbidden(*args, **kwargs): raise AssertionError("revoked current index reached projection")
    monkeypatch.setattr(model._model, "forward", forbidden)
    outcome = _structural_call(model, reviewed_fixture_owner, case, query, lane, expected, top_k=1)
    assert outcome["status"] == "abstained_current_index_unavailable"
    assert outcome["abstention_count"] == 1 and outcome["retrieved_count"] == 0
    assert outcome["rows"][0]["context"] is None and outcome["model_forward_executed"] is False
    assert model.checkpoint == reviewed_trained["checkpoint"]


def test_reviewed_inference_abstains_on_unavailable_query_without_zero_filling(
        reviewed_trained, reviewed_fixture_owner, reviewed_query_case, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    case, query, lane, expected = reviewed_query_case
    lane, expected = copy.deepcopy((lane, expected))
    row = lane["rows"][0]
    row.update(status="unavailable", reason="explicitly unavailable fixture vector", vector=None, vector_sha256=None)
    binding = {key: row[key] for key in lanes.ROW_BINDING_FIELDS}
    row["producer_row_sha256"] = lanes._digest(binding)
    lane["producer_receipt"]["rows"] = [binding]
    reviewed_fixture_owner.fixtures.seal(lane["producer_receipt"])
    reviewed_fixture_owner.fixtures.seal(lane)
    expected["producer_receipt_sha256"] = lanes._digest(lane["producer_receipt"])
    model = retrieval.ReviewedLegalJointRetriever(reviewed_trained["checkpoint"],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained["checkpoint"]))
    def forbidden(*args, **kwargs): raise AssertionError("unavailable query reached projection")
    monkeypatch.setattr(model._model, "forward", forbidden)
    outcome = _structural_call(model, reviewed_fixture_owner, case, query, lane, expected, top_k=1)
    assert outcome["rows"][0]["status"] == "abstained" and outcome["rows"][0]["context"] is None
    assert "query_representation_unavailable" in outcome["rows"][0]["abstention_reasons"]


def test_reviewed_index_adds_declared_representation_without_weight_retraining(
        reviewed_trained, reviewed_fixture_owner, reviewed_query_case, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    original, query, query_lane, expected_query = reviewed_query_case
    case = reviewed_fixture_owner.reviewed_pair_clone_v2(original)
    inputs, body = case["preparation_inputs"], case["preparation_inputs"]["body"]
    formal = inputs["formal_lane"]
    row = copy.deepcopy(formal["rows"][2]); row["id"] = "formal:3"
    binding = {key: row[key] for key in lanes.ROW_BINDING_FIELDS}
    row["producer_row_sha256"] = lanes._digest(binding)
    formal["rows"].append(row)
    formal["producer_receipt"]["rows"].append(binding)
    reviewed_fixture_owner.fixtures.seal(formal["producer_receipt"])
    reviewed_fixture_owner.fixtures.seal(formal)
    inputs["expected_formal_lane_bindings"]["producer_receipt_sha256"] = lanes._digest(formal["producer_receipt"])
    inputs["expected_formal_lane_bindings"]["inputs"].append({"id": row["id"], "input_sha256": row["input_sha256"]})
    endpoint = copy.deepcopy(body["formal_endpoints"][2]); endpoint["id"] = row["id"]
    body["formal_endpoints"].append(endpoint)
    old_pairs = {(pair["left_id"], pair["right_id"]): pair for pair in body["pairs"]}
    pairs = []
    for source in body["source_endpoints"]:
        for target in body["formal_endpoints"]:
            if target["id"] != "formal:3": pairs.append(copy.deepcopy(old_pairs[source["id"], target["id"]])); continue
            prior = copy.deepcopy(old_pairs[source["id"], "formal:2"])
            prior["right_id"] = "formal:3"
            if source["id"] == "source:0": prior.update(relation="unknown", evidence_refs=[])
            prior["reason"] = "Explicit fictional reviewed representation alias, not an independent statutory use."
            pairs.append(prior)
    body["pairs"] = pairs
    body["formal_lane_sha256"] = lanes._digest(formal)
    artifact_id = body["ledger_id"] + ":formal-lane"
    next(item for item in inputs["dependency_manifest"]["artifacts"] if item["artifact_id"] == artifact_id)["artifact_sha256"] = body["formal_lane_sha256"]
    case["observed_artifacts"][artifact_id] = body["formal_lane_sha256"]
    reviewed_fixture_owner.refresh_reviewed_pair_ledger_v2(case)
    model = retrieval.ReviewedLegalJointRetriever(reviewed_trained["checkpoint"],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained["checkpoint"]))
    before = copy.deepcopy(model.checkpoint)
    def no_training(*args, **kwargs): raise AssertionError("index update attempted fitting")
    monkeypatch.setattr(retrieval, "train_reviewed_retriever", no_training)
    outcome = _structural_call(model, reviewed_fixture_owner, case, query, query_lane, expected_query, top_k=4)
    assert set(outcome["rows"][0]["retrieved_ids"]) == {"formal:0", "formal:1", "formal:2", "formal:3"}
    assert outcome["current_index_differs_from_training"] is True
    assert outcome["historical_training_requalification_performed"] is False
    assert model.checkpoint == before


@pytest.mark.parametrize("steps", [0, 3])
def test_reviewed_mixed_v3_joint_updates_restore_and_retrieve_current_index(steps, monkeypatch, tmp_path):
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as owner
    case = owner.fixtures.reviewed_pair_fixture_v3()
    args, options = owner.reviewed_mask_arguments_v2(case)
    fitted = retrieval.train_reviewed_retriever_v3(*args, **options, steps=steps, joint_dimension=8)
    checkpoint, report = fitted["checkpoint"], fitted["report"]
    assert checkpoint["schema"] == "legal-joint-retrieval-checkpoint/v3"
    assert report["schema"] == "legal-joint-retrieval-training/v3"
    assert report["optimizer_steps"] == len(report["losses"]) == steps
    assert bool(report["changed_parameter_names"]) is (steps > 0)
    saved = copy.deepcopy(checkpoint)
    path = tmp_path / "reviewed-joint-v3.json"
    sha = retrieval.save_checkpoint(checkpoint, path)
    loaded = retrieval.load_checkpoint(path, sha)
    assert loaded == checkpoint == saved
    model = retrieval.ReviewedLegalJointRetriever(loaded,
        expected_checkpoint_sha256=retrieval.checkpoint_digest(loaded))
    assert model.checkpoint == checkpoint
    current, query, lane, expected = _reviewed_structural_query_fixture(owner, case, admission_version="v3")
    result = _structural_call(model, owner, current, query, lane, expected, top_k=2)
    assert result["schema"] == "legal-joint-retrieval-result/v3"
    assert result["status"] == "retrieval_completed" and result["model_forward_executed"] is True
    assert result["current_index_differs_from_training"] is True
    assert result["query_target_access"] is result["decoder_context_admitted"] is False
    current["reviews"] = []
    denied = _structural_call(model, owner, current, query, lane, expected, top_k=2)
    assert denied["status"] == "abstained_current_index_unavailable" and denied["model_forward_executed"] is False


def test_reviewed_mixed_v3_joint_rechecks_authority_after_real_updates(monkeypatch):
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as owner
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_relation_mask_handoff as handoff
    case = owner.fixtures.reviewed_pair_fixture_v3()
    args, options = owner.reviewed_mask_arguments_v2(case)
    original = handoff.compile_reviewed_train_relation_masks_v3
    calls = []
    def revoke_at_exit(*values, **kwargs):
        calls.append(1)
        if len(calls) == 2: values[1]["keys"][0]["revoked_at_utc"] = case["at_time_utc"]
        return original(*values, **kwargs)
    monkeypatch.setattr(handoff, "compile_reviewed_train_relation_masks_v3", revoke_at_exit)
    with pytest.raises(ValueError, match="independently pinned trust input differs"):
        retrieval.train_reviewed_retriever_v3(*args, **options, steps=1, joint_dimension=8)
    assert len(calls) == 2


@pytest.mark.parametrize('mode',['joint','raw'])
def test_reviewed_composed_v3_fit_restore_and_source_query_preserve_profile_and_revocation(tmp_path,mode):
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as owner
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_declarations as declared
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    case=declared.declared_composed_reviewed_pair_fixture_v3(tmp_path)
    args,options=owner.reviewed_mask_arguments_v2(case)
    fitted=retrieval.train_reviewed_retriever_v3(*args,**options,steps=1,joint_dimension=8)
    checkpoint=fitted['checkpoint'];assert fitted['report']['optimizer_steps']==1
    assert fitted['report']['changed_parameter_names']
    assert checkpoint['training_handoff']['source_representation_profile']['stage']=='complete_chunk_composition'
    path=tmp_path/'composed-fixture-checkpoint.json';sha=retrieval.save_checkpoint(checkpoint,path)
    loaded=retrieval.load_checkpoint(path,sha);assert loaded==checkpoint
    model=retrieval.ReviewedLegalJointRetriever(loaded,expected_checkpoint_sha256=retrieval.checkpoint_digest(loaded))
    current,query,lane,expected=_reviewed_structural_query_fixture(owner,case,admission_version='v3')
    row=lane['rows'][0];row['upstream_vector_sha256']=lanes._digest({'declared_mean':row['vector']});row['token_receipt_sha256']='c'*64
    binding={key:row[key] for key in lanes.ROW_BINDING_FIELDS};row['producer_row_sha256']=lanes._digest(binding)
    lane['producer_receipt']['rows']=[binding];owner.fixtures.seal(lane['producer_receipt']);owner.fixtures.seal(lane)
    expected['producer_receipt_sha256']=lanes._digest(lane['producer_receipt'])
    result=_structural_call(model,owner,current,query,lane,expected,mode=mode,top_k=2)
    assert result['status']=='retrieval_completed' and result['model_forward_executed'] is (mode=='joint')
    assert result['query_target_access'] is result['decoder_context_admitted'] is False
    current['reviews']=[]
    denied=_structural_call(model,owner,current,query,lane,expected,mode=mode,top_k=2)
    assert denied['status']=='abstained_current_index_unavailable' and denied['model_forward_executed'] is False
    assert model.checkpoint==checkpoint


@pytest.mark.parametrize('damage',[None,'reference-excluded','review-withdrawn','query-target'])
def test_reviewed_lexical_baseline_uses_existing_BM25_on_only_permitted_TRAIN_formal_text(
        reviewed_trained,reviewed_fixture_owner,reviewed_query_case,monkeypatch,damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import frame_bm25_selector as lexical
    case,query,lane,expected=reviewed_query_case
    case=reviewed_fixture_owner.reviewed_pair_clone_v2(case)
    query=copy.deepcopy(query)
    model=retrieval.ReviewedLegalJointRetriever(reviewed_trained['checkpoint'],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained['checkpoint']))
    def no_forward(*args,**kwargs):raise AssertionError('lexical baseline forwarded neural model')
    monkeypatch.setattr(model._model,'forward',no_forward)
    omitted=[]
    if damage=='reference-excluded':omitted=[case['preparation_inputs']['body']['formal_endpoints'][0]['formal_view_sha256']]
    elif damage=='review-withdrawn':case['reviews']=[]
    elif damage=='query-target':query['canonical_ir']={'hidden':'reference'}
    if damage=='query-target':
        with pytest.raises(ValueError):_structural_call(model,reviewed_fixture_owner,case,query,lane,expected,mode='lexical',top_k=1)
        return
    if damage=='review-withdrawn':
        monkeypatch.setattr(lexical.BM25FrameSelector,'rank',lambda *a,**k:pytest.fail('lexical scoring before current review'))
    result=_structural_call(model,reviewed_fixture_owner,case,query,lane,expected,
        mode='lexical',top_k=1,forbidden={query['id']:omitted})
    assert result['model_forward_executed'] is False
    if damage=='review-withdrawn':assert result['status']=='abstained_current_index_unavailable';return
    inputs=case['preparation_inputs'];formal=inputs['formal_lane']['rows'];endpoints=inputs['body']['formal_endpoints']
    candidates=[row for row,endpoint in zip(formal,endpoints,strict=True) if endpoint['formal_view_sha256'] not in omitted]
    selector=lexical.BM25FrameSelector([lexical.FrameCandidate(frame_id=row['id'],label=row['encoder_text'],domain='') for row in candidates])
    expected_rank=selector.rank(query['source_text'],top_k=1)
    assert result['rows'][0]['retrieved_ids']==[item.frame.frame_id for item in expected_rank]
    assert result['rows'][0]['scores']==[item.score for item in expected_rank]
    assert result['lexical_profile']['candidate_view']=='complete_TRAIN_formal_encoder_text'
    assert result['query_target_access'] is result['legal_applicability_verified'] is False
    assert model.checkpoint==reviewed_trained['checkpoint']


def test_reviewed_lexical_budget_refuses_complete_oversized_query_without_clipping(
        reviewed_trained,reviewed_fixture_owner,reviewed_case,monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import frame_bm25_selector as lexical
    query=dict(id='query:lexical-work',split_sample_id='sample:lexical-work',
        source_text=' '.join('w'+str(i) for i in range(9000)))
    assert len(query['source_text'])<=65536
    case,query,lane,expected=_reviewed_structural_query_fixture(reviewed_fixture_owner,reviewed_case,query=query)
    model=retrieval.ReviewedLegalJointRetriever(reviewed_trained['checkpoint'],
        expected_checkpoint_sha256=retrieval.checkpoint_digest(reviewed_trained['checkpoint']))
    monkeypatch.setattr(lexical.BM25FrameSelector,'rank',lambda *a,**k:pytest.fail('scored before lexical work admission'))
    with pytest.raises(ValueError,match='lexical token comparison budget exceeded'):
        _structural_call(model,reviewed_fixture_owner,case,query,lane,expected,mode='lexical',top_k=1)


# These controls exercise metadata/routing only. They allocate no tensors,
# models or optimizers and do not qualify a V4 numerical update or restore.
def _forbid_reviewed_v4_torch_import(monkeypatch):
    import builtins
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise AssertionError("V4 metadata or rejected evidence reached Torch")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_reviewed_v4_checkpoint_domain_and_restore_dispatch_are_closed_before_torch(monkeypatch):
    _forbid_reviewed_v4_torch_import(monkeypatch)
    contracts = [retrieval._reviewed_contract(version) for version in ("v2", "v3", "v4")]
    assert len({row["schema"] for row in contracts}) == 3
    assert len({row["architecture"] for row in contracts}) == 3
    assert len({row["relation_scope"] for row in contracts}) == 3
    for version, contract in zip(("v2", "v3", "v4"), contracts):
        assert retrieval._reviewed_checkpoint_version({"schema": contract["schema"]}) == version
    for bad in (None, "v5", {}, []):
        with pytest.raises(ValueError):
            retrieval._reviewed_contract(bad)
    for bad in (None, {}, {"schema": []}, {"schema": "legal-joint-retrieval-checkpoint/v5"}):
        with pytest.raises(ValueError):
            retrieval._reviewed_checkpoint_version(bad)
    calls = []
    original_restore = retrieval._restore_reviewed
    monkeypatch.setattr(retrieval, "_restore_reviewed", lambda value: calls.append(value) or "metadata-route")
    checkpoint = {"schema": retrieval.REVIEWED_V4_SCHEMA}
    assert retrieval._restore(checkpoint) == "metadata-route"
    with pytest.raises(ValueError, match="legacy source port"):
        retrieval._restore(checkpoint, source_profile={})
    assert calls == [checkpoint]
    monkeypatch.setattr(retrieval, "_restore_reviewed", original_restore)
    monkeypatch.setattr(retrieval, "_reviewed_implementation", lambda version: {})
    monkeypatch.setattr(retrieval, "_reviewed_arrays", lambda value, **kwargs: None)
    historical = {"schema": retrieval.REVIEWED_V4_SCHEMA, "implementation": {},
        "training_handoff": {}, "training_handoff_sha256": retrieval.checkpoint_digest({}),
        "initial_model_state_sha256": "a" * 64, "model_state": {}, "progress": {},
        "config": {"seed": 1, "joint_dimension": 8, "learning_rate": .003, "temperature": .1,
                   "architecture": contracts[-1]["architecture"],
                   "relation_scope": contracts[-1]["relation_scope"],
                   "loss": "symmetric_masked_multi_positive_contrastive/v1",
                   "endpoint_admission_version": "v2"}}
    with pytest.raises(ValueError, match="reviewed config admission domain"):
        original_restore(historical)


def test_reviewed_v4_training_wrapper_and_replay_refuse_before_torch(monkeypatch):
    from types import SimpleNamespace
    _forbid_reviewed_v4_torch_import(monkeypatch)
    original = retrieval._train_reviewed_retriever
    calls = []
    inputs = dict.fromkeys(("expected_preparation_sha256", "preparation_inputs", "expected_registry_sha256",
        "expected_policy_sha256", "expected_reviews_sha256", "at_time_utc", "observed_artifact_sha256s",
        "observed_pins", "evidence_artifacts", "current_endpoint_observations"))
    monkeypatch.setattr(retrieval, "_train_reviewed_retriever", lambda *args, **kwargs: calls.append(kwargs) or "metadata-route")
    assert retrieval.train_reviewed_retriever_v4(None, None, None, [], **inputs) == "metadata-route"
    assert calls[0]["_admission_version"] == "v4" and calls[0]["steps"] == 0
    monkeypatch.setattr(retrieval, "_train_reviewed_retriever", original)
    routes = []

    def current_v4(*args, **kwargs):
        routes.append("v4")
        raise ValueError("fictional current pair review revoked")

    def wrong_domain(*args, **kwargs):
        raise AssertionError("V4 relation replay fell back to an older relation domain")

    masks = SimpleNamespace(compile_reviewed_train_relation_masks_v2=wrong_domain,
        compile_reviewed_train_relation_masks_v3=wrong_domain, compile_reviewed_train_relation_masks_v4=current_v4)
    monkeypatch.setattr(retrieval, "_reviewed_owners", lambda version: (None, masks, None, None))
    with pytest.raises(ValueError, match="fictional current pair review revoked"):
        retrieval.train_reviewed_retriever_v4(None, None, None, [], **inputs)
    assert routes == ["v4"]


def test_reviewed_v4_array_layout_reuses_canonical_context_guard_without_authority(monkeypatch):
    from types import SimpleNamespace
    _forbid_reviewed_v4_torch_import(monkeypatch)
    calls = []
    scope = {"governing_context": {"jurisdiction": "fixture:jurisdiction"},
             "interpretation_id": "fixture:interpretation", "assumptions": []}
    context_set = [{"context_sha256": retrieval.checkpoint_digest(scope), "scope": scope}]
    endpoints = {name: [{"id": "fixture:" + name, "context_sha256": context_set[0]["context_sha256"],
                        "scope": scope}] for name in ("source", "formal")}

    def context_guard(offered, population):
        assert offered == context_set and population == endpoints
        calls.append("canonical-context-guard")
        return retrieval.checkpoint_digest(context_set)

    declarations = SimpleNamespace(REVIEWED_PROFILE="fixture:relation-v2", REVIEWED_V3_PROFILE="fixture:relation-v3",
        REVIEWED_V4_PROFILE="fixture:relation-v4", _reviewed_context_set_sha256=context_guard)
    masks = SimpleNamespace(REVIEWED_SCHEMA="fixture:mask-v2", REVIEWED_V3_SCHEMA="fixture:mask-v3",
        REVIEWED_V4_SCHEMA="fixture:mask-v4")
    admission = SimpleNamespace(norm_content_adjudication_sha256=retrieval.checkpoint_digest)
    monkeypatch.setattr(retrieval, "_reviewed_owners", lambda version: (None, masks, declarations, admission))
    handoff = dict(schema=masks.REVIEWED_V4_SCHEMA, profile=declarations.REVIEWED_V4_PROFILE,
        status="reviewed_objective_mask_ready", endpoint_admission_version="v3", reviewed_objective_mask_ready=True,
        reviewed_pair_labels_authenticated=True, representation_dimension=384,
        source_row_count=1, formal_row_count=1, source_vectors=[[1.0] + [0.0] * 383],
        formal_vectors=[[1.0] + [0.0] * 383], objective_positive_mask=[[True]],
        objective_permitted_negative_mask=[[False]], context_set=context_set,
        context_set_sha256=retrieval.checkpoint_digest(context_set),
        legal_applicability_verified=False, controlling_authority=False,
        source_endpoints=endpoints["source"], formal_endpoints=endpoints["formal"])

    def seal(value):
        value["content_sha256"] = retrieval.checkpoint_digest({k: v for k, v in value.items() if k != "content_sha256"})

    seal(handoff)
    assert retrieval._reviewed_arrays(handoff, _admission_version="v4")[2:] == ([[True]], [[False]])
    assert calls == ["canonical-context-guard"]
    for field, changed in (("context_set_sha256", "b" * 64), ("legal_applicability_verified", True),
                           ("controlling_authority", True), ("endpoint_admission_version", "v2"), ("source_endpoints", []),
                           ("schema", masks.REVIEWED_V3_SCHEMA)):
        altered = copy.deepcopy(handoff)
        altered[field] = changed
        seal(altered)
        with pytest.raises(ValueError):
            retrieval._reviewed_arrays(altered, _admission_version="v4")


def test_reviewed_v4_owner_routing_requires_v3_endpoint_admission(monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_relation_declarations as declarations
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_relation_mask_handoff as handoff
    _forbid_reviewed_v4_torch_import(monkeypatch)
    monkeypatch.setattr(declarations, "_reviewed_contract", lambda version: {"endpoint_version": "v2"})
    with pytest.raises(ValueError, match="explicit V3 endpoint"):
        retrieval._reviewed_owners("v4")
    monkeypatch.setattr(declarations, "_reviewed_contract", lambda version: {"endpoint_version": "v3"})
    wrong = SimpleNamespace(__name__="ipfs_datasets_py.logic.autoformal.legal_norm_content_adjudication_v1")
    monkeypatch.setattr(declarations, "_reviewed_owners", lambda version: (wrong,))
    with pytest.raises(ValueError, match="fall back to V2 endpoint"):
        retrieval._reviewed_owners("v4")
    correct = SimpleNamespace(__name__="ipfs_datasets_py.logic.autoformal.legal_reviewed_norm_admission_v3",
        validate_reviewed_norm_admission_v3=lambda: None, assess_reviewed_norm_admission_v3=lambda: None)
    monkeypatch.setattr(declarations, "_reviewed_owners", lambda version: (correct,))
    monkeypatch.setattr(handoff, "compile_reviewed_train_relation_masks_v4", lambda: None, raising=False)
    assert retrieval._reviewed_owners("v4")[-1] is correct


def test_reviewed_v4_actual_fixture_masks_and_current_denial_precede_torch(monkeypatch):
    """Actual canonical fictional admission/masks, never a numerical model."""
    import importlib.util
    from pathlib import Path
    _forbid_reviewed_v4_torch_import(monkeypatch)
    # Reuse the existing pure signed-fixture owner. Resolve it from the shared
    # codec root so private source previews use the genuine current fixture.
    root = Path(retrieval.codec.__file__).resolve().parents[3]
    path = root / 'tests/unit/logic/formalization/autoencoder/test_alignment_relation_mask_handoff.py'
    spec = importlib.util.spec_from_file_location('_reviewed_joint_v4_current_fixture_owner', path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    case = fixture.fixtures.reviewed_pair_fixture_v4()
    args, inputs = fixture.reviewed_mask_arguments_v2(case)
    _, handoff, declarations, admission = retrieval._reviewed_owners('v4')
    current = handoff.compile_reviewed_train_relation_masks_v4(*args, **inputs)
    assert current['reviewed_objective_mask_ready'] is True
    assert current['endpoint_admission_version'] == 'v3'
    assert len(current['context_set']) >= 2
    assert current['context_set_sha256'] == declarations._reviewed_context_set_sha256(
        current['context_set'], {side: current[side + '_endpoints'] for side in ('source', 'formal')})
    assert current['legal_applicability_verified'] is current['controlling_authority'] is False
    assert current['training_gold_mask'] == current['evaluation_gold_mask'] == 0
    arrays = retrieval._reviewed_arrays(current, _admission_version='v4')
    assert len(arrays[0]) == current['source_row_count']
    assert len(arrays[1]) == current['formal_row_count']
    assert current['unknown_pair_count'] >= 1 and current['analogy_retrieval_only_pair_count'] >= 1
    for row in current['pair_rows']:
        if row['relation'] in ('unknown', 'analogy'):
            assert row['objective_positive'] is row['objective_permitted_negative'] is False
    for old_domain in ('v2', 'v3'):
        with pytest.raises(ValueError, match='not ready'):
            retrieval._reviewed_arrays(current, _admission_version=old_domain)
    for damage in ('context_order', 'missing_context', 'wrong_endpoint_domain'):
        altered = copy.deepcopy(current)
        if damage == 'context_order':
            altered['context_set'].reverse()
        elif damage == 'missing_context':
            altered['context_set'].pop()
        else:
            altered['endpoint_admission_version'] = 'v2'
        altered['content_sha256'] = admission.norm_content_adjudication_sha256(
            {key: value for key, value in altered.items() if key != 'content_sha256'})
        with pytest.raises(ValueError):
            retrieval._reviewed_arrays(altered, _admission_version='v4')
    # Missing independent review evidence invalidates the real current handoff.
    # The trainer must reject it before even importing Torch, including steps=0.
    blocked = dict(inputs, evidence_artifacts={})
    entered = []
    actual_compile = handoff.compile_reviewed_train_relation_masks_v4

    def observe_actual_compile(*replay_args, **replay_inputs):
        entered.append(replay_inputs['evidence_artifacts'] == {})
        return actual_compile(*replay_args, **replay_inputs)

    monkeypatch.setattr(handoff, 'compile_reviewed_train_relation_masks_v4', observe_actual_compile)
    with pytest.raises(ValueError):
        retrieval.train_reviewed_retriever_v4(*args, **blocked, steps=0)
    assert entered == [True]


def test_reviewed_v4_source_query_preparation_retains_authenticated_context_set():
    """A heldout source query must preserve the real fictional V4 pair domain."""
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as owner
    case = owner.fixtures.reviewed_pair_fixture_v4()
    original_preparation = copy.deepcopy(case["preparation"])
    context_set = copy.deepcopy(case["preparation_inputs"]["body"]["context_set"])
    assert len(context_set) == 2
    assert len(case["expected_positive_mask"]) == 4
    assert all(len(row) == 6 for row in case["expected_positive_mask"])

    current, query, lane, expected = _reviewed_structural_query_fixture(
        owner, case, admission_version="v4")
    args, inputs = owner.reviewed_mask_arguments_v2(current)
    handoff = owner.subject.compile_reviewed_train_relation_masks_v4(*args, **inputs)
    assert current["preparation"]["schema"] == owner.subject.relations.REVIEWED_V4_SCHEMA
    assert current["preparation"]["schema"] == "alignment-reviewed-pair-preparation/v4"
    assert handoff["schema"] == "alignment-reviewed-train-relation-mask-handoff/v4"
    assert handoff["reviewed_objective_mask_ready"] is True
    assert handoff["endpoint_admission_version"] == "v3"
    assert current["preparation_inputs"]["body"]["context_set"] == context_set
    assert handoff["context_set"] == context_set
    assert handoff["context_set_sha256"] == case["context_set_sha256"]
    assert handoff["source_row_count"] == 4 and handoff["formal_row_count"] == 6
    assert handoff["objective_positive_mask"] == case["expected_positive_mask"]
    assert all(len(vector) == 384 for vector in handoff["source_vectors"] + handoff["formal_vectors"])
    assert query["split_sample_id"] in current["preparation_inputs"]["split_manifest"]["assignments"]
    assert lane["rows"][0]["id"] == query["id"]
    assert expected["inputs"][0]["id"] == query["id"]
    assert current["preparation"]["body_sha256"] != original_preparation["body_sha256"]
    assert case["preparation"] == original_preparation
    assert handoff["training_gold_mask"] == handoff["evaluation_gold_mask"] == 0
    assert handoff["legal_applicability_verified"] is handoff["controlling_authority"] is False



def test_reviewed_lexical_baseline_abstains_on_source_without_tokens(
        reviewed_trained, reviewed_fixture_owner, reviewed_case, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import frame_bm25_selector as lexical

    query = {
        "id": "query:lexical-tokenless",
        "split_sample_id": "sample:lexical-tokenless",
        "source_text": "許可を申請する。",
    }
    case, query, lane, expected = _reviewed_structural_query_fixture(
        reviewed_fixture_owner, reviewed_case, query=query)
    assert lane["rows"][0]["status"] == "available"
    checkpoint = reviewed_trained["checkpoint"]
    model = retrieval.ReviewedLegalJointRetriever(
        checkpoint, expected_checkpoint_sha256=retrieval.checkpoint_digest(checkpoint))

    def unexpected_scoring(*args, **kwargs):
        pytest.fail("tokenless lexical query reached scoring")

    monkeypatch.setattr(lexical.BM25FrameSelector, "rank", unexpected_scoring)
    monkeypatch.setattr(model._model, "forward", unexpected_scoring)
    result = _structural_call(
        model, reviewed_fixture_owner, case, query, lane, expected, mode="lexical", top_k=1)
    row = result["rows"][0]
    assert row["eligible_rows"] >= 1
    assert row["source_sha256"] == hashlib.sha256(query["source_text"].encode("utf-8")).hexdigest()
    assert row["status"] == "abstained" and row["abstention_reasons"] == ["lexical_query_unscorable"]
    assert row["retrieved_ids"] == [] and row["context"] is None
    assert result["retrieved_count"] == 0 and result["abstention_count"] == 1
    assert result["model_forward_executed"] is False and model.checkpoint == checkpoint


@pytest.mark.parametrize("steps", [0, 3])
def test_reviewed_v4_tiny_joint_updates_restore_and_rank_current_index(steps, tmp_path):
    """Synthetic numerical mechanics under future caller-owned admission only.

    The existing fixture supplies authored vectors and freshly signed fictional
    review, not encoder inference, private assets, statutory gold or permission
    to execute this test. No convergence or monotone-loss claim is made.
    """
    import site
    import sys
    from pathlib import Path

    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as owner
    case = owner.fixtures.reviewed_pair_fixture_v4()
    current = owner.reviewed_mask_compile_v4(case)
    assert current["reviewed_objective_mask_ready"] is True
    assert current["endpoint_admission_version"] == "v3"
    assert (current["source_row_count"], current["formal_row_count"]) == (4, 6)
    assert len(current["context_set"]) == 2
    assert current["context_set"] == case["preparation_inputs"]["body"]["context_set"]
    assert current["objective_positive_mask"] == case["expected_positive_mask"]
    assert current["unknown_pair_count"] > 0 and current["analogy_retrieval_only_pair_count"] > 0
    for pair in current["pair_rows"]:
        if pair["relation"] in ("unknown", "analogy"):
            assert pair["objective_positive"] is pair["objective_permitted_negative"] is False
    assert current["training_gold_mask"] == current["evaluation_gold_mask"] == 0
    # Observe the actual imported runtime inside this caller-admitted test.
    # Source identity is recorded; vendor execution and quality are unqualified.
    torch_origin = Path(torch.__file__).resolve(strict=True)
    assert torch_origin.name == "__init__.py" and torch_origin.is_file()
    with torch_origin.open("rb") as stream:
        torch_origin_bytes = stream.read(1024 * 1024 + 1)
    assert len(torch_origin_bytes) <= 1024 * 1024
    runtime_origin = {
        "schema": "reviewed-v4-tiny-numerical-runtime-origin/v1",
        "torch": {
            "version": str(torch.__version__),
            "module_file": str(torch.__file__),
            "resolved_init_file": str(torch_origin),
            "init_file_bytes": len(torch_origin_bytes),
            "init_file_sha256": hashlib.sha256(torch_origin_bytes).hexdigest(),
        },
        "python": {
            "executable": sys.executable,
            "resolved_executable": str(Path(sys.executable).resolve(strict=True)),
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "isolated": int(sys.flags.isolated),
            "no_user_site": int(sys.flags.no_user_site),
            "site_ENABLE_USER_SITE": site.ENABLE_USER_SITE,
        },
        "fixture": {
            "schema": current["schema"],
            "fixture_only": current["fixture_only"],
            "endpoint_admission_version": current["endpoint_admission_version"],
            "ledger_id": case["preparation_inputs"]["body"]["ledger_id"],
            "preparation_sha256": retrieval.checkpoint_digest(case["preparation"]),
            "context_set_sha256": current["context_set_sha256"],
            "handoff_content_sha256": current["content_sha256"],
            "source_row_count": current["source_row_count"],
            "formal_row_count": current["formal_row_count"],
        },
        "training_steps_requested": steps,
        "legal_source_correspondence_qualified": False,
        "model_quality_qualified": False,
        "convergence_proved": False,
        "vendor_binary_closure_attested": False,
        "runtime_profile_qualified": False,
        "resource_admission_authority": False,
    }
    runtime_origin_raw = (json.dumps(runtime_origin, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    assert len(runtime_origin_raw) <= 16 * 1024
    runtime_origin_path = tmp_path / "reviewed-v4-runtime-origin.json"
    with runtime_origin_path.open("xb") as stream:
        stream.write(runtime_origin_raw)
    assert runtime_origin_path.read_bytes() == runtime_origin_raw
    assert json.loads(runtime_origin_path.read_bytes()) == runtime_origin
    args, options = owner.reviewed_mask_arguments_v2(case)
    original_inputs = copy.deepcopy((args, options))
    initial_rng = torch.get_rng_state().clone()
    fitted = retrieval.train_reviewed_retriever_v4(*args, **options,
        steps=steps, seed=2718, joint_dimension=8)
    checkpoint, report = fitted["checkpoint"], fitted["report"]
    assert (args, options) == original_inputs and torch.equal(torch.get_rng_state(), initial_rng)
    assert checkpoint["schema"] == "legal-joint-retrieval-checkpoint/v4"
    assert report["schema"] == "legal-joint-retrieval-training/v4"
    assert report["endpoint_admission_version"] == "v3"
    assert checkpoint["training_handoff"] == current
    assert report["context_set_sha256"] == current["context_set_sha256"]
    assert report["optimizer_steps"] == len(report["losses"]) == steps
    assert all(torch.isfinite(torch.tensor(value)) for value in report["losses"])
    assert report["training_executed"] is (steps > 0) and report["model_executed"] is True
    expected_parameters = {"source.weight", "source.bias", "formal.weight", "formal.bias"}
    assert set(checkpoint["model_state"]) == expected_parameters
    assert set(report["changed_parameter_names"]) <= expected_parameters
    assert bool(report["changed_parameter_names"]) is (steps > 0)
    assert (checkpoint["initial_model_state_sha256"] !=
        retrieval.checkpoint_digest(checkpoint["model_state"])) is (steps > 0)
    assert report["checkpoint_restore_verified"] is True
    assert report["fixture_only"] is True
    assert report["input_embedding_runtime_computation_proven"] is False
    assert report["heldout_evaluation_performed"] is report["previous_task_retention_evaluated"] is False
    assert report["resource_admission_scope"] == "caller_owned_not_validated_here"
    assert report["recall_scope"] == "reviewed_training_grid_resubstitution_only"
    for flag in ("qualified", "admitted", "proof_authority", "semantic_correctness_verified",
            "legal_applicability_verified", "controlling_authority"):
        assert report[flag] is False
    assert report["target_access"] is True and report["query_target_access"] is False
    original_checkpoint = copy.deepcopy(checkpoint)
    path = tmp_path / "reviewed-v4-tiny.json"
    file_sha = retrieval.save_checkpoint(checkpoint, path)
    loaded = retrieval.load_checkpoint(path, file_sha)
    assert loaded == checkpoint == original_checkpoint
    torch_owner, restored = retrieval._restore(loaded)
    assert retrieval._state(restored) == checkpoint["model_state"]
    assert all(parameter.device.type == "cpu" and parameter.dtype == torch_owner.float32
        for parameter in restored.parameters())
    model = retrieval.ReviewedLegalJointRetriever(loaded,
        expected_checkpoint_sha256=retrieval.checkpoint_digest(loaded))
    indexed, query, lane, expected = _reviewed_structural_query_fixture(
        owner, case, admission_version="v4")
    indexed_mask = owner.reviewed_mask_compile_v4(indexed)
    assert indexed_mask["reviewed_objective_mask_ready"] is True
    assert indexed_mask["context_set"] == current["context_set"]
    assert indexed_mask["objective_positive_mask"] == current["objective_positive_mask"]
    for pair in indexed_mask["pair_rows"]:
        if pair["relation"] in ("unknown", "analogy"):
            assert pair["objective_positive"] is pair["objective_permitted_negative"] is False
    result = _structural_call(model, owner, indexed, query, lane, expected, top_k=2)
    assert result["schema"] == "legal-joint-retrieval-result/v4"
    assert result["status"] == "retrieval_completed" and result["model_forward_executed"] is True
    assert result["retrieved_count"] == 1 and result["abstention_count"] == 0
    assert result["endpoint_admission_version"] == "v3"
    assert result["context_set_sha256"] == current["context_set_sha256"]
    assert "context_set" not in result
    assert result["current_index_differs_from_training"] is True
    assert result["query_target_access"] is result["decoder_context_admitted"] is False
    assert result["query_target_payload_accessed"] is result["inference_reference_content_forwarded"] is False
    assert result["query_source_runtime_computation_proven"] is False
    assert result["heldout_evaluation_performed"] is False
    assert result["legal_applicability_verified"] is result["controlling_authority"] is False
    row = result["rows"][0]
    assert row["status"] == "retrieved" and row["context_dimension"] == 384
    vectors = {item["id"]: item["vector"] for item in indexed["preparation_inputs"]["formal_lane"]["rows"]}
    assert len(row["retrieved_ids"]) == len(set(row["retrieved_ids"])) == 2
    assert set(row["retrieved_ids"]) <= set(vectors)
    assert all(torch.isfinite(torch.tensor(value)) for value in (*row["context"], *row["scores"], *row["weights"]))
    independent_context = sum(torch.tensor(vectors[identity], dtype=torch.float32) * weight
        for identity, weight in zip(row["retrieved_ids"], row["weights"], strict=True))
    assert torch.allclose(torch.tensor(row["context"]), independent_context, rtol=0, atol=1e-6)
    assert model.checkpoint == original_checkpoint
    indexed["reviews"] = []
    denied = _structural_call(model, owner, indexed, query, lane, expected, top_k=2)
    assert denied["status"] == "abstained_current_index_unavailable"
    assert denied["model_forward_executed"] is False and denied["retrieved_count"] == 0
    assert denied["rows"][0]["context"] is None
    assert model.checkpoint == original_checkpoint

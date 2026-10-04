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
    with pytest.raises(ValueError, match="regular"):
        retrieval.load_checkpoint(link)

"""Independent stage selection and structured-context provenance checks."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("structured_analysis", ROOT / "scripts/ops/legal_ir/summarize_legal_structured_retrieval_experiment.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def test_tuning_selection_prefers_accuracy_and_then_earlier_stage():
    stages = [{"new_optimizer_steps": 1600, "tuning_exact": 90}, {"new_optimizer_steps": 800, "tuning_exact": 90}]
    assert analysis.select_stage(stages)["new_optimizer_steps"] == 800
    stages[0]["tuning_exact"] = 91
    assert analysis.select_stage(stages)["new_optimizer_steps"] == 1600


def test_selection_requires_both_distinct_stages():
    with pytest.raises(ValueError, match="two distinct"):
        analysis.select_stage([{"new_optimizer_steps": 800, "tuning_exact": 90}])


def test_unfinished_run_never_opens_challenge_targets(tmp_path):
    with pytest.raises(ValueError, match="completed summary required"):
        analysis.summarize(tmp_path, tmp_path / "analysis.json")


def profile_fixture():
    training = []
    for index, modality in enumerate(("O", "P", "F")):
        training.append({"id": f"train-{index}", "canonical_ir": {"rules": [{"modality": modality,
            "actor": "Office", "action": "retain", "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}})
    source = {"id": "query", "source_sha256": "1" * 64, "family_group": "new-family"}
    native = {"id": source["id"], "source_sha256": source["source_sha256"], "retrieved_ids": [row["id"] for row in training],
              "weights": [.6, .3, .1], "index_sha256": "2" * 64}
    histogram = [0.] * 24
    for index, weight in zip((0, 8, 16), native["weights"]):
        histogram[index] = weight
    context = [value / 4 for value in histogram for _ in range(16)]
    row = {**source, "query_family_group": source["family_group"], "query_target_access": False,
        "query_target_values_embedded": False, "retrieval_record_sha256": analysis.digest(native),
        "retrieved_ids": native["retrieved_ids"], "original_retrieval_weights": native["weights"],
        "index_sha256": native["index_sha256"], "training_index_sha256": native["index_sha256"],
        "weights": native["weights"], "neighbor_profile_ids": [0, 8, 16], "context": context,
        "context_sha256": analysis.digest(context), "profile_distribution": histogram}
    return row, native, source, training


def test_profiles_are_recomputed_from_retrieved_training_asts():
    row, native, source, training = profile_fixture()
    analysis.verify_profile_contexts([row], [native], [source], training)
    row["neighbor_profile_ids"][0] = 1
    with pytest.raises(ValueError, match="training AST profiles"):
        analysis.verify_profile_contexts([row], [native], [source], training)


def test_context_descriptor_cannot_change_independently_of_profile():
    row, native, source, training = profile_fixture()
    row["context"][0] += .01
    row["context_sha256"] = analysis.digest(row["context"])
    with pytest.raises(ValueError, match="descriptor differs"):
        analysis.verify_profile_contexts([row], [native], [source], training)


def test_cyclic_intervention_preserves_qualifier_bits_and_source():
    original, _, source, _ = profile_fixture()
    histogram = [0.] * 24
    histogram[8], histogram[16], histogram[0] = .6, .3, .1
    context = [value / 4 for value in histogram for _ in range(16)]
    row = {"id": source["id"], "source_sha256": source["source_sha256"], "original_context_receipt": original,
           "original_context_sha256": original["context_sha256"], "context": context,
           "context_sha256": analysis.digest(context), "profile_distribution": histogram}
    analysis.verify_cyclic([row], [original], [source])
    row["context"][16:32] = row["context"][0:16]
    row["context"][0:16] = [0.] * 16
    row["context_sha256"] = analysis.digest(row["context"])
    with pytest.raises(ValueError, match="more than modality"):
        analysis.verify_cyclic([row], [original], [source])


def cross_family_fixture():
    sources = [{"id": f"q-{index}", "source_sha256": str(index) * 64, "family_group": "a" if index < 2 else "b"}
               for index in range(4)]
    ordinary = [{**source, "context": [float(index)] * 384, "context_sha256": analysis.digest([float(index)] * 384),
                 "retrieved_ids": [f"train-{index}"], "weights": [1.], "index_sha256": "a" * 64}
                for index, source in enumerate(sources)]
    swapped = []
    for index, donor_index in enumerate((2, 3, 0, 1)):
        receiver, donor = sources[index], sources[donor_index]
        swapped.append({**ordinary[donor_index], "id": receiver["id"], "source_sha256": receiver["source_sha256"],
            "query_family_group": receiver["family_group"], "donor_query_id": donor["id"], "donor_source_sha256": donor["source_sha256"],
            "donor_family_group": donor["family_group"], "donor_context_sha256": ordinary[donor_index]["context_sha256"],
            "receiver_original_context_sha256": ordinary[index]["context_sha256"]})
    return swapped, ordinary, sources


def test_cross_family_permutation_checks_both_receiver_and_donor_bindings():
    swapped, ordinary, sources = cross_family_fixture()
    analysis.verify_cross_family(swapped, ordinary, sources)
    swapped[0]["donor_source_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="donor family/source"):
        analysis.verify_cross_family(swapped, ordinary, sources)


def test_cross_family_permutation_must_use_each_donor_once():
    swapped, ordinary, sources = cross_family_fixture()
    second_receiver = {key: swapped[1][key] for key in ("id", "source_sha256", "query_family_group", "receiver_original_context_sha256")}
    swapped[1] = {**copy.deepcopy(swapped[0]), **second_receiver}
    with pytest.raises(ValueError, match="donor bijection"):
        analysis.verify_cross_family(swapped, ordinary, sources)


def test_generation_receipt_cannot_claim_another_inner_checkpoint():
    payload = {"generation_inputs_contained_references": False, "rows": [], "reports": [{"rows": [],
        "target_access": False, "teacher_forcing": False, "checkpoint_sha256": "outer", "base_checkpoint_sha256": "inner"}]}
    analysis.verify_generation(payload, "outer", base_sha256="inner")
    with pytest.raises(ValueError, match="inner checkpoint differs"):
        analysis.verify_generation(payload, "outer", base_sha256="different")

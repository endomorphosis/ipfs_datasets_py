"""Coherent triple coverage, source-only admission and explicit policy limits."""
import importlib.util
import itertools
import json
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval as base

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_retrieval.py"
spec = importlib.util.spec_from_file_location("alignment_joint_retrieval_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def target(actor="agency", action="file", object_="notice", modality="O", conditions=None):
    return {"rules": [{"modality": modality, "actor": actor, "action": action, "object": object_,
                       "conditions": conditions or [], "exceptions": [], "temporal": []}]}


def vector(*values, width=384):
    return list(values) + [0.] * (width - len(values))


def candidate(identity, source=None, rule=None):
    return {"candidate_id": identity, "target": rule or target(), "source_vector": source or vector(1.),
            "train_ids": ["train-" + identity]}


def distribution(label, **probabilities):
    return {"label": label, "scores": probabilities or {label: 1.}}


def predictions(actor="agency", action="file", object_="notice", modality="O"):
    return {"modality": distribution(modality), "actor": distribution(actor),
            "action": distribution(action), "object": distribution(object_)}


def run(candidates, *, variant="hard_joint", predicted=None, query=None, **options):
    return subject.rerank_joint_candidates("query", query or vector(1.), candidates, variant=variant,
                                           predicted_facets=predicted or predictions(), **options)


def ids(ranking):
    return [item["candidate_id"] for item in ranking["retrieved"]]


def test_module_and_numerical_inference_import_no_optional_models():
    code = """
import importlib.abc
import importlib.util
import sys
class RejectModels(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'torch','transformers','sentence_transformers','spacy'}:
            raise AssertionError('optional model imported')
sys.meta_path.insert(0, RejectModels())
spec = importlib.util.spec_from_file_location('lazy_joint', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rule = {'modality':'O','actor':'agency','action':'file','object':'notice',
        'conditions':[],'exceptions':[],'temporal':[]}
vector = [1.] + [0.]*383
candidate = {'candidate_id':'a','source_vector':vector,'train_ids':['train-a'],'target':{'rules':[rule]}}
predicted = {facet:{'label':rule[facet],'scores':{rule[facet]:1.}} for facet in ('modality','actor','action','object')}
for variant in ('hard_joint','soft_joint'):
    result = module.rerank_joint_candidates('query',vector,[candidate],variant=variant,predicted_facets=predicted)
    assert result['trace']['joint_coverage'] == 1.
assert 'torch' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(MODULE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("variant", subject.VARIANTS)
def test_defaults_reuse_exact_existing_cosine_top_twenty_with_top_five(variant):
    choices = [candidate(f"a{i:02}", vector(1.), target("inspector", "review", "records", "P"))
               for i in range(20)]
    choices.append(candidate("outside", vector(.9, .2), target()))
    prepared = base.prepare_training_candidates(choices)
    original = base.rerank_candidates("query", vector(3.), prepared, policy="cosine")
    result = run(prepared, variant=variant, query=vector(3.))
    assert result["trace"]["shortlist"] == original["trace"]["shortlist"]
    assert result["trace"]["shortlist_count"] == 20 and result["trace"]["candidate_count"] == 21
    assert result["trace"]["diversity_lambda"] == .7
    assert ids(result) == ["a00", "a01", "a02", "a03", "a04"]
    assert "outside" not in {item["candidate_id"] for item in result["trace"]["shortlist"]}
    assert result["trace"]["joint_coverage"] == 0.


@pytest.mark.parametrize("variant", subject.VARIANTS)
def test_scattered_correct_labels_in_wrong_contexts_earn_no_joint_reward(variant):
    choices = [candidate("a", rule=target("agency", "file", "records", "P")),
               candidate("b", rule=target("inspector", "review", "notice", "O"))]
    independent = base.rerank_candidates("query", vector(1.), choices, policy="facet_cover",
                                         predicted_facets=predictions(), top_k=2)
    result = run(choices, variant=variant, top_k=2)
    independently_covered = {tuple(pair) for pair in independent["trace"]["covered_facet_values"]}
    assert all((facet, part["label"]) in independently_covered for facet, part in predictions().items())
    assert result["trace"]["covered_joint_triples"] == []
    assert all(item["marginal_joint_coverage"] == 0. for item in result["retrieved"])


def test_hard_rewards_coherent_complementary_demonstrations_without_exact_target():
    choices = [candidate("wrong_context", rule=target("agency", "file", "records", "P")),
               candidate("actor_support", vector(.99, .01), target("agency", "review")),
               candidate("action_support", vector(.99, .01), target("inspector", "file"))]
    result = run(choices, top_k=2)
    assert ids(result) == ["action_support", "actor_support"]
    assert [item["marginal_joint_coverage"] for item in result["retrieved"]] == [.5, .5]
    assert result["trace"]["joint_coverage"] == 1.
    assert all(choice["target"] != target() for choice in choices)
    assert {entry["family"] for entry in result["trace"]["covered_joint_triples"]} == {
        "actor_modality_object", "action_modality_object"}
    assert all(entry["triple"][1:] == ["O", "notice"] for entry in result["trace"]["covered_joint_triples"])


@pytest.mark.parametrize("variant", subject.VARIANTS)
def test_wrong_source_predictions_can_favor_wrong_semantic_demonstrations(variant):
    # The local "true" target is a test reference, never an inference argument.
    truth = target()
    wrong = target("inspector", "review", "records", "P")
    choices = [candidate("a_true", rule=truth), candidate("b_wrong", rule=wrong)]
    result = run(choices, variant=variant, predicted=predictions("inspector", "review", "records", "P"), top_k=1)
    assert ids(result) == ["b_wrong"]
    assert result["trace"]["joint_coverage"] == 1.
    assert result["trace"]["factorization"]["source_fidelity_guaranteed"] is False
    assert result["trace"]["qualified"] is False and result["trace"]["query_target_consumed"] is False


def test_soft_rewards_alternative_coherent_mass_after_argmax_saturates():
    predicted = predictions()
    predicted["actor"] = distribution("agency", agency=.8, inspector=.2)
    predicted["action"] = distribution("file", file=.7, review=.3)
    choices = [candidate("a"), candidate("b", rule=target("inspector", "file")),
               candidate("c", rule=target("agency", "review"))]
    soft = run(choices, variant="soft_joint", predicted=predicted, top_k=3)
    assert ids(soft) == ["a", "c", "b"]
    assert [item["marginal_joint_coverage"] for item in soft["retrieved"]] == pytest.approx([.75, .15, .1])
    assert soft["trace"]["joint_coverage"] == pytest.approx(1.)
    hard = run(choices, variant="hard_joint", predicted=predicted, top_k=3)
    assert [item["marginal_joint_coverage"] for item in hard["retrieved"]] == [1., 0., 0.]
    assert soft["trace"]["factorization"]["estimated_joint_probability"] is False


def test_soft_joint_factorization_requires_all_three_marginals():
    predicted = predictions()
    predicted["actor"] = distribution("agency", agency=.6, inspector=.4)
    predicted["action"] = distribution("file", file=.8, review=.2)
    predicted["modality"] = distribution("O", O=.75, P=.25)
    predicted["object"] = distribution("notice", notice=.9, records=.1)
    result = run([candidate("a")], variant="soft_joint", predicted=predicted)
    assert result["retrieved"][0]["marginal_joint_coverage"] == pytest.approx(
        .5 * (.6 * .75 * .9) + .5 * (.8 * .75 * .9))
    weights = {entry["family"]: entry["weight"] for entry in result["trace"]["covered_joint_triples"]}
    assert weights == pytest.approx({"actor_modality_object": .6*.75*.9,
                                     "action_modality_object": .8*.75*.9})


def test_soft_mass_saturates_once_per_distinct_family_triple():
    predicted = predictions()
    predicted["actor"] = distribution("agency", agency=.5, inspector=.5)
    predicted["action"] = distribution("file", file=.5, review=.5)
    predicted["modality"] = distribution("O", O=.5, P=.5)
    predicted["object"] = distribution("notice", notice=.5, records=.5)
    choices = [candidate(str(i), rule=target(actor, action, object_, modality))
               for i, (actor, action, modality, object_) in enumerate(itertools.product(
                   ("agency", "inspector"), ("file", "review"), ("O", "P"), ("notice", "records")))]
    result = run(choices, variant="soft_joint", predicted=predicted, top_k=16)
    assert len(result["trace"]["covered_joint_triples"]) == 16
    assert all(entry["weight"] == .125 for entry in result["trace"]["covered_joint_triples"])
    assert result["trace"]["joint_coverage"] == 1.
    assert math.fsum(item["marginal_joint_coverage"] for item in result["retrieved"]) == 1.
    assert all(0 <= item["cumulative_joint_coverage"] <= 1. for item in result["retrieved"])
    assert any(item["marginal_joint_coverage"] == 0. for item in result["retrieved"])


@pytest.mark.parametrize("variant", subject.VARIANTS)
def test_already_covered_family_has_zero_marginal_credit_and_new_family_has_priority(variant):
    choices = [candidate("a", rule=target("agency", "review", conditions=["first_qualifier"])),
               candidate("b", rule=target("agency", "review", conditions=["second_qualifier"])),
               candidate("c", rule=target("inspector", "file"))]
    result = run(choices, variant=variant, top_k=3)
    assert ids(result) == ["a", "c", "b"]
    assert [item["marginal_joint_coverage"] for item in result["retrieved"]] == [.5, .5, 0.]
    assert [item["cumulative_joint_coverage"] for item in result["retrieved"]] == [.5, 1., 1.]
    assert len(result["trace"]["covered_joint_triples"]) == 2


def test_soft_rounding_normalization_is_explicit_and_does_not_fit_or_calibrate():
    predicted = predictions()
    predicted["actor"] = distribution("agency", agency=.50000025, inspector=.50000025)
    result = run([candidate("a"), candidate("b", rule=target("inspector"))],
                 variant="soft_joint", predicted=predicted, top_k=2)
    assert result["trace"]["joint_coverage"] == 1.
    assert result["trace"]["prediction_sha256"] == base._digest(predicted)
    assert result["trace"]["factorization"]["marginal_normalization"] == "validated_unit_sum_renormalization"
    assert predicted["actor"]["scores"]["agency"] == .50000025


def test_soft_family_average_is_not_probability_of_common_context_complementarity():
    predicted = predictions()
    predicted["modality"] = distribution("O", O=.5, P=.5)
    predicted["object"] = distribution("notice", notice=.5, records=.5)
    choices = [candidate("actor", rule=target("agency", "review", "notice", "O")),
               candidate("action", rule=target("inspector", "file", "records", "P"))]
    result = run(choices, variant="soft_joint", predicted=predicted, top_k=2)
    assert result["trace"]["joint_coverage"] == .25
    covered = result["trace"]["covered_joint_triples"]
    assert {tuple(entry["triple"][1:]) for entry in covered} == {("O", "notice"), ("P", "records")}
    assert result["trace"]["factorization"]["common_context_complementary_support_probability"] is False


@pytest.mark.parametrize("variant", subject.VARIANTS)
def test_relevance_tradeoff_can_miss_available_shortlist_complementary_support(variant):
    choices = [candidate("actor_support", rule=target("agency", "review"))]
    choices.extend(candidate(f"decoy_{i}", rule=target("inspector", "review", "records", "P",
                                                      conditions=[f"distinct_condition_{i}"])) for i in range(4))
    choices.append(candidate("action_support", vector(-1.), target("inspector", "file")))
    result = run(choices, variant=variant)
    assert "actor_support" in ids(result) and "action_support" not in ids(result)
    assert "action_support" in {item["candidate_id"] for item in result["trace"]["shortlist"]}
    assert result["trace"]["joint_coverage"] == .5
    assert result["trace"]["factorization"]["shortlist_support_guaranteed_selected"] is False


def test_hard_argmax_ties_are_lexicographic_and_soft_score_ties_use_candidate_id():
    predicted = predictions()
    predicted["actor"] = distribution("inspector", agency=.5, inspector=.5)
    choices = [candidate("a", rule=target("inspector")), candidate("b", rule=target("agency"))]
    hard = run(choices, predicted=predicted, top_k=1)
    assert ids(hard) == ["b"]
    assert hard["trace"]["predicted_argmax_triples"]["actor_modality_object"] == ["agency", "O", "notice"]
    assert hard["trace"]["factorization"]["argmax_tie_break"] == "lexicographic_label"
    assert ids(run(choices, variant="soft_joint", predicted=predicted, top_k=1)) == ["a"]


@pytest.mark.parametrize("variant", subject.VARIANTS)
def test_prepared_geometry_is_unchanged_and_input_mutation_cannot_change_snapshot(variant):
    choices = [candidate("a"), candidate("b", vector(0., 1.), target("inspector"))]
    geometry = {"a": vector(1., width=512), "b": vector(0., 1., width=512)}
    prepared = base.prepare_training_candidates(choices, candidate_vectors=geometry)
    raw = run(choices, variant=variant, query=vector(1., width=512), candidate_vectors=geometry)
    assert run(prepared, variant=variant, query=vector(1., width=512)) == raw
    geometry["a"][0] = float("nan")
    choices[0]["target"]["rules"][0]["actor"] = "changed"
    choices[0]["train_ids"].append("query")
    assert run(prepared, variant=variant, query=vector(1., width=512)) == raw
    assert raw["trace"]["candidate_admission_sha256"] == prepared.admission_sha256


def test_threaded_inference_is_deterministic_without_shared_mutation():
    prepared = base.prepare_training_candidates([candidate("a"), candidate("b", rule=target("inspector"))])
    predicted = predictions()
    original = deepcopy(predicted)
    expected = run(prepared, variant="soft_joint", predicted=predicted)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: run(prepared, variant="soft_joint", predicted=predicted), range(12)))
    assert all(result == expected for result in results)
    assert predicted == original


def test_source_only_signature_rejects_query_gold_and_hidden_groups():
    for supplied in ({"query_target": target()}, {"targets": [target()]}, {"groups": ["hidden"]}):
        with pytest.raises(TypeError):
            run([candidate("a")], **supplied)
    with pytest.raises(ValueError):
        subject.rerank_joint_candidates("query", vector(1.), [candidate("a")],
                                        variant="hard_joint", predicted_facets=target())


@pytest.mark.parametrize("mutation", [
    lambda value: value["actor"].update(scores={"agency": True}),
    lambda value: value["actor"].update(scores={"agency": float("nan")}),
    lambda value: value["actor"].update(scores={"agency": float("inf")}),
    lambda value: value["actor"].update(scores={"agency": .5}),
    lambda value: value["actor"].update(scores={"agency": 1.1, "inspector": -.1}),
    lambda value: value["actor"].update(label="inspector", scores={"agency": .9, "inspector": .1}),
    lambda value: value["actor"].update(label=[]),
    lambda value: value["actor"].update(query_target=target()),
    lambda value: value.update(query_target=target()),
])
def test_malformed_or_nonfinite_prediction_input_rejects(mutation):
    value = predictions()
    mutation(value)
    with pytest.raises(ValueError):
        subject.rerank_joint_candidates("query", vector(1.), [candidate("a")],
                                        variant="soft_joint", predicted_facets=value)


@pytest.mark.parametrize("source", [vector(0.), vector(True), vector(float("nan")), vector(float("inf")), [1.]*383])
def test_query_validation_reuses_existing_finite_nonzero_dimension_contract(source):
    with pytest.raises(ValueError):
        subject.rerank_joint_candidates("query", source, [candidate("a")],
                                        variant="hard_joint", predicted_facets=predictions())


@pytest.mark.parametrize("options", [{"top_k": True}, {"shortlist": 513}, {"top_k": 3, "shortlist": 2},
                                      {"diversity_lambda": True}, {"diversity_lambda": float("nan")},
                                      {"diversity_lambda": -1}, {"diversity_lambda": 2}])
def test_budget_and_weight_validation_reuses_existing_contract(options):
    with pytest.raises(ValueError):
        run([candidate("a")], **options)


@pytest.mark.parametrize("variant", ["independent", "hard", None, True, []])
def test_unknown_variants_reject(variant):
    with pytest.raises(ValueError):
        run([candidate("a")], variant=variant)


def test_training_candidate_admission_remains_closed_canonical_and_separate_from_query():
    duplicate = [candidate("a"), candidate("a")]
    with pytest.raises(ValueError):
        run(duplicate)
    noncanonical = candidate("a")
    noncanonical["target"]["rules"][0]["conditions"] = ["z", "a"]
    with pytest.raises(ValueError):
        run([noncanonical])
    overlapping = candidate("a")
    overlapping["train_ids"] = ["query"]
    with pytest.raises(ValueError, match="query ID"):
        run(base.prepare_training_candidates([overlapping]))
    foreign = candidate("a")
    foreign["query_target"] = target()
    with pytest.raises(ValueError):
        run([foreign])


def test_prepared_geometry_cannot_be_replaced_and_wrong_dimensions_reject():
    prepared = base.prepare_training_candidates([candidate("a")])
    with pytest.raises(ValueError):
        run(prepared, candidate_vectors={"a": vector(1.)})
    with pytest.raises(ValueError):
        run(prepared, query=vector(1., width=512))


def test_results_are_finite_ordinary_json_with_explicit_provenance_and_limits():
    predicted = predictions()
    result = run([candidate("a")], variant="soft_joint", predicted=predicted)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    trace = result["trace"]
    assert trace["schema"] == subject.SCHEMA
    assert trace["prediction_sha256"] == base._digest(predicted)
    assert trace["joint_families"] == {"actor_modality_object": ["actor", "modality", "object"],
                                      "action_modality_object": ["action", "modality", "object"]}
    assert trace["family_weights"] == {"actor_modality_object": .5, "action_modality_object": .5}
    assert trace["factorization"]["weight_kind"] == "product_of_uncalibrated_facet_marginal_scores"
    assert trace["factorization"]["triple_saturation"] == "count_each_family_triple_once"
    assert trace["factorization"]["estimated_joint_probability"] is False
    assert trace["query_target_consumed"] is False and trace["qualified"] is False

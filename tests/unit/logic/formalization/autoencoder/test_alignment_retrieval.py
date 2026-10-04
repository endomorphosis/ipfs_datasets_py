"""Source-only reranking, train-only probes and bounded ordinary-JSON checks."""
import importlib.util
import json
import math
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval.py"
spec = importlib.util.spec_from_file_location("alignment_retrieval_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def target(actor="agency", action="file", object_="notice", modality="O"):
    return {"rules": [{"modality": modality, "actor": actor, "action": action, "object": object_,
                       "conditions": [], "exceptions": [], "temporal": []}]}


def vector(*values, width=384):
    return list(values) + [0.0] * (width - len(values))


def candidate(identity, source=None, rule=None):
    return {"candidate_id": identity, "target": rule or target(), "source_vector": source or vector(1.),
            "train_ids": ["train-" + identity]}


def row(identity, source=None, rule=None):
    return {"id": identity, "unit_vector": source or vector(1.), "target": rule or target(), "split": "train"}


def distribution(label, **probabilities):
    return {"label": label, "scores": probabilities or {label: 1.}}


def predictions(actor="agency", action="file", object_="notice", modality="O"):
    return {"modality": distribution(modality), "actor": distribution(actor),
            "action": distribution(action), "object": distribution(object_)}


def reseal(probe):
    probe["content_sha256"] = subject._digest({key: value for key, value in probe.items() if key != "content_sha256"})
    return probe


@pytest.fixture
def torch():
    return pytest.importorskip("torch")


@pytest.fixture
def probe(torch):
    return subject.fit_facet_probe([
        row("one", vector(1., 0.), target()),
        row("two", vector(0., 1.), target("inspector", "review", "records", "P")),
    ])


def test_import_and_source_only_reranking_do_not_load_torch():
    code = """
import importlib.abc
import importlib.util
import sys
class RejectTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'torch' or name.startswith('torch.'):
            raise AssertionError('optional Torch imported')
sys.meta_path.insert(0, RejectTorch())
spec = importlib.util.spec_from_file_location('lazy_retrieval', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rule = {'modality':'O', 'actor':'agency', 'action':'file', 'object':'notice',
        'conditions':[], 'exceptions':[], 'temporal':[]}
source = [1.] + [0.]*383
candidate = {'candidate_id':'a', 'target':{'rules':[rule]}, 'train_ids':['train-a'], 'source_vector':source}
assert module.rerank_candidates('query', source, [candidate], policy='cosine')['retrieved'][0]['candidate_id'] == 'a'
assert 'torch' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(MODULE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_probe_identity_matches_existing_frozen_source_space():
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_baseline import VECTOR_SPACE_ID
    assert subject.SOURCE_SPACE_ID == VECTOR_SPACE_ID


def test_ridge_fit_is_deterministic_finite_and_restores_thread_count(probe, torch):
    before_threads = torch.get_num_threads()
    again = subject.fit_facet_probe([
        row("one", vector(1., 0.), target()),
        row("two", vector(0., 1.), target("inspector", "review", "records", "P")),
    ])
    assert again == probe
    assert torch.get_num_threads() == before_threads
    assert json.loads(json.dumps(probe, allow_nan=False)) == probe
    assert probe["recipe"]["objective"] == "sum_squared_residuals_plus_lambda_weight_l2"
    assert probe["recipe"]["dtype"] == "float64" and probe["recipe"]["device"] == "cpu"
    assert probe["recipe"]["cpu_threads"] == 1 and probe["recipe"]["softmax_temperature"] == 1.
    assert probe["fit_policy"] == "training_rows_only"
    assert probe["development_fit"] is False and probe["qualified"] is False
    result = subject.predict_source_facets([vector(1.), vector(0., 1.)], probe)
    assert result[0]["actor"]["label"] == "agency"
    assert result[1]["actor"]["label"] == "inspector"
    for prediction in result:
        for facet in subject.FACETS:
            assert math.fsum(prediction[facet]["scores"].values()) == pytest.approx(1.)


def test_ridge_intercept_is_unregularized_even_with_constant_features(torch):
    value = subject.fit_facet_probe([row("one"), row("two")], regularization=1000)
    assert value["bias"] == [1.] * 4
    assert all(number == 0. for weights in value["weight"] for number in weights)
    assert value["recipe"]["intercept_regularized"] is False
    assert all(part["scores"] == {part["label"]: 1.}
               for part in subject.predict_source_facets([vector(-1.)], value)[0].values())


def test_predict_is_source_only_and_does_not_extend_train_vocabulary(probe):
    original = deepcopy(probe)
    subject.predict_source_facets([vector(1., 1.)], probe)
    assert probe == original
    assert "development_only_actor" not in probe["vocabulary"]["actor"]
    with pytest.raises(TypeError):
        subject.predict_source_facets([vector(1.)], probe, targets=[target("development_only_actor")])
    with pytest.raises(ValueError):
        subject.predict_source_facets([row("development", rule=target("development_only_actor"))], probe)


def test_train_fitted_probe_can_predict_an_unseen_core_composition(torch):
    # Actor and action are separate orthogonal source coordinates; the training
    # combinations omit inspector/file while exposing both labels separately.
    rows = [
        row("one", vector(1., 0., 1., 0.), target("agency", "file")),
        row("two", vector(1., 0., 0., 1.), target("agency", "review")),
        row("three", vector(0., 1., 0., 1.), target("inspector", "review")),
    ]
    value = subject.fit_facet_probe(rows)
    predicted = subject.predict_source_facets([vector(0., 1., 1., 0.)], value)[0]
    assert predicted["actor"]["label"] == "inspector" and predicted["action"]["label"] == "file"
    assert ("inspector", "file") not in {(item["target"]["rules"][0]["actor"],
                                          item["target"]["rules"][0]["action"]) for item in rows}


def test_training_manifest_binds_consumed_sources_targets_and_order(probe, torch):
    original = [row("one", vector(1.), target()),
                row("two", vector(0., 1.), target("inspector", "review", "records", "P"))]
    reversed_probe = subject.fit_facet_probe(list(reversed(original)))
    assert reversed_probe["training_manifest_sha256"] != probe["training_manifest_sha256"]
    modified = deepcopy(original)
    modified[0]["target"] = target("clerk")
    assert subject.fit_facet_probe(modified)["training_manifest_sha256"] != probe["training_manifest_sha256"]
    modified = deepcopy(original)
    modified[0]["unit_vector"] = vector(1., 1.)
    assert subject.fit_facet_probe(modified)["training_manifest_sha256"] != probe["training_manifest_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[0].update(split="development"),
    lambda rows: rows[0].update(evaluation_role="hidden_holdout"),
    lambda rows: rows.append(deepcopy(rows[0])),
    lambda rows: rows[0].update(unit_vector=vector(0.)),
    lambda rows: rows[0].update(unit_vector=vector(True)),
    lambda rows: rows[0].update(unit_vector=vector(float("nan"))),
    lambda rows: rows[0].update(unit_vector=vector(1., width=512)),
    lambda rows: rows[0]["target"]["rules"][0].update(conditions=["z", "a"]),
])
def test_bad_train_rows_are_rejected_before_optional_fit(mutation):
    rows = [row("one")]
    mutation(rows)
    with pytest.raises(ValueError):
        subject.fit_facet_probe(rows)


@pytest.mark.parametrize("regularization", [True, 0, -1, float("inf"), 1001])
def test_invalid_ridge_regularization_rejects(regularization):
    with pytest.raises(ValueError):
        subject.fit_facet_probe([row("one")], regularization=regularization)


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(source_space_id="foreign-source"),
    lambda value: value.update(qualified=True),
    lambda value: value.update(training_manifest_sha256="not-a-digest"),
    lambda value: value["weight"][0].pop(),
    lambda value: value["weight"][0].__setitem__(0, True),
    lambda value: value["weight"][0].__setitem__(0, float("inf")),
    lambda value: value["recipe"].update(intercept_regularized=True),
    lambda value: value["recipe"].update(softmax_temperature=2.),
    lambda value: value["vocabulary"]["actor"].append("agency"),
])
def test_probe_closed_identity_shapes_dtype_and_recipe_reject(probe, mutation):
    value = deepcopy(probe)
    mutation(value)
    # A resealed malformed model must still fail structural admission.
    if not any(not subject._finite(number) for weights in value["weight"] for number in weights):
        reseal(value)
    with pytest.raises(ValueError):
        subject.predict_source_facets([vector(1.)], value)


def test_probe_digest_covers_parameters(probe):
    value = deepcopy(probe)
    value["bias"][0] += .1
    with pytest.raises(ValueError, match="digest"):
        subject.predict_source_facets([vector(1.)], value)


def test_cosine_is_scale_invariant_with_stable_identifier_ties():
    choices = [candidate("b", vector(2.)), candidate("a", vector(1.)), candidate("c", vector(0., 1.))]
    result = subject.rerank_candidates("query", vector(5.), choices, policy="cosine", top_k=3)
    assert [item["candidate_id"] for item in result["retrieved"]] == ["a", "b", "c"]
    assert [item["cosine_similarity"] for item in result["retrieved"]] == [1., 1., 0.]
    assert result["trace"]["query_target_consumed"] is False
    assert result["trace"]["qualified"] is False


def test_mmr_prefers_complementary_geometry_with_no_labels_or_predictions():
    choices = [candidate("a", vector(.8, .6)), candidate("b", vector(.79, .613)),
               candidate("c", vector(.78, -.626))]
    plain = subject.rerank_candidates("query", vector(1.), choices, policy="cosine", top_k=2)
    diverse = subject.rerank_candidates("query", vector(1.), choices, policy="mmr", top_k=2)
    assert [item["candidate_id"] for item in plain["retrieved"]] == ["a", "b"]
    assert [item["candidate_id"] for item in diverse["retrieved"]] == ["a", "c"]
    assert diverse["retrieved"][0]["selection_score"] == diverse["retrieved"][0]["cosine_similarity"]
    assert diverse["trace"]["prediction_sha256"] is None


def test_facet_cover_rewards_new_predicted_values_once_without_hard_filtering():
    choices = [candidate("a", vector(1.)), candidate("b", vector(.999, .01)),
               candidate("c", vector(.99, .02), target("inspector"))]
    predicted = predictions()
    predicted["actor"] = distribution("agency", agency=.5, inspector=.5)
    result = subject.rerank_candidates("query", vector(1.), choices, policy="facet_cover", top_k=3,
                                       predicted_facets=predicted)
    assert [item["candidate_id"] for item in result["retrieved"]] == ["a", "c", "b"]
    assert [item["marginal_predicted_coverage"] for item in result["retrieved"]] == [.875, .125, 0.]
    assert result["retrieved"][1]["selection_score"] == pytest.approx(
        .7 * (result["retrieved"][1]["cosine_similarity"] + 1) / 2 + .3 * .125)
    assert result["trace"]["coverage_scope"] == "independent_four_core_facet_values"
    assert result["trace"]["prediction_sha256"] == subject._digest(predicted)
    assert "predicted_facets" not in result["trace"]


def test_independent_facet_cover_is_not_joint_demonstration_support():
    choices = [candidate("a", vector(1.), target("agency", "file", "records", "P")),
               candidate("b", vector(.99, .1), target("inspector", "review", "notice", "O"))]
    predicted = predictions()
    result = subject.rerank_candidates("query", vector(1.), choices, policy="facet_cover", top_k=2,
                                       predicted_facets=predicted)
    covered = {tuple(pair) for pair in result["trace"]["covered_facet_values"]}
    assert all((facet, part["label"]) in covered for facet, part in predicted.items())
    # Agency + obligation + notice and file + obligation + notice are absent,
    # although the independent predicted values are all covered in the union.
    assert not any(all(choice["target"]["rules"][0][facet] == predicted[facet]["label"]
                       for facet in ("actor", "modality", "object")) for choice in choices)
    assert not any(all(choice["target"]["rules"][0][facet] == predicted[facet]["label"]
                       for facet in ("action", "modality", "object")) for choice in choices)


def test_512_geometry_requires_complete_candidate_map():
    choices = [candidate("a"), candidate("b", vector(0., 1.))]
    geometry = {"a": vector(1., width=512), "b": vector(0., 1., width=512)}
    result = subject.rerank_candidates("query", vector(1., width=512), choices, policy="mmr", candidate_vectors=geometry)
    assert result["retrieved"][0]["candidate_id"] == "a"
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1., width=512), choices, policy="cosine")
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1., width=512), choices, policy="cosine", candidate_vectors={"a": geometry["a"]})
    geometry["b"] = vector(0., 1.)
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1., width=512), choices, policy="cosine", candidate_vectors=geometry)


@pytest.mark.parametrize("policy", ["cosine", "mmr", "facet_cover"])
def test_prepared_pool_has_identical_rankings_without_mutable_input_aliases(policy):
    choices = [candidate("a", vector(.8, .6)), candidate("b", vector(.79, .613)),
               candidate("c", vector(.78, -.626), target("inspector"))]
    prepared = subject.prepare_training_candidates(choices)
    options = {"policy": policy, "predicted_facets": predictions("inspector") if policy == "facet_cover" else None}
    expected = subject.rerank_candidates("query", vector(1.), choices, **options)
    assert subject.rerank_candidates("query", vector(1.), prepared, **options) == expected
    choices[0]["source_vector"][0] = float("nan")
    choices[0]["target"]["rules"][0]["actor"] = "mutated_actor"
    choices[0]["train_ids"].append("query")
    assert subject.rerank_candidates("query", vector(1.), prepared, **options) == expected
    with pytest.raises(AttributeError):
        prepared.dimension = 512
    with pytest.raises(TypeError):
        prepared._rows[0][2][0] = 42.


def test_prepared_pool_checks_query_training_overlap_on_every_call():
    prepared = subject.prepare_training_candidates([candidate("a")])
    with pytest.raises(ValueError, match="query ID"):
        subject.rerank_candidates("train-a", vector(1.), prepared, policy="cosine")
    with pytest.raises(ValueError):
        subject.PreparedTrainingCandidates()


def test_prepared_projected_geometry_and_admission_digest_are_bound_once():
    choices = [candidate("a"), candidate("b", vector(0., 1.))]
    geometry = {"a": vector(1., width=512), "b": vector(0., 1., width=512)}
    prepared = subject.prepare_training_candidates(choices, candidate_vectors=geometry)
    assert prepared.dimension == 512
    expected = subject.rerank_candidates("query", vector(1., width=512), choices, policy="cosine", candidate_vectors=geometry)
    assert subject.rerank_candidates("query", vector(1., width=512), prepared, policy="cosine") == expected
    geometry["a"][0] = 0.
    assert subject.rerank_candidates("query", vector(1., width=512), prepared, policy="cosine") == expected
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1.), prepared, policy="cosine")
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1., width=512), prepared, policy="cosine", candidate_vectors=geometry)
    changed = deepcopy(choices)
    changed[0]["target"] = target("clerk")
    assert subject.prepare_training_candidates(changed).admission_sha256 != subject.prepare_training_candidates(choices).admission_sha256


def test_source_reranking_cannot_consume_query_target_or_groups():
    for supplied in ({"query_target": target()}, {"groups": ["hidden"]}):
        with pytest.raises(TypeError):
            subject.rerank_candidates("query", vector(1.), [candidate("a")], policy="cosine", **supplied)
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1.), [candidate("a")], policy="facet_cover", predicted_facets=target())


@pytest.mark.parametrize("mutation", [
    lambda choices: choices.append(deepcopy(choices[0])),
    lambda choices: choices[0].update(train_ids=["query"]),
    lambda choices: choices[0].update(train_ids=["same", "same"]),
    lambda choices: choices[1].update(train_ids=choices[0]["train_ids"]),
    lambda choices: choices[0].update(source_vector=vector(0.)),
    lambda choices: choices[0].update(source_vector=vector(True)),
    lambda choices: choices[0].update(source_vector=vector(float("inf"))),
    lambda choices: choices[0].update(source_vector=vector(1., width=512)),
    lambda choices: choices[0].update(query_target=target()),
    lambda choices: choices[0]["target"]["rules"][0].update(conditions=["z", "a"]),
])
def test_candidates_reject_duplicate_ids_memberships_noncanonical_targets_and_bad_vectors(mutation):
    choices = [candidate("a"), candidate("b")]
    mutation(choices)
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1.), choices, policy="cosine")


@pytest.mark.parametrize("source", [vector(0.), vector(True), vector(float("nan")),
                                     vector(10**1000), [1.] * 383])
def test_invalid_query_vectors_reject(source):
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", source, [candidate("a")], policy="cosine")


@pytest.mark.parametrize("options", [{"top_k": True}, {"top_k": 0}, {"shortlist": 513},
                                      {"top_k": 3, "shortlist": 2}, {"diversity_lambda": True},
                                      {"diversity_lambda": float("nan")}, {"diversity_lambda": -1},
                                      {"diversity_lambda": 2}, {"predicted_facets": predictions()}])
def test_bad_ranking_parameters_reject(options):
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1.), [candidate("a")], policy="cosine", **options)


@pytest.mark.parametrize("mutation", [
    lambda value: value["actor"].update(label=[]),
    lambda value: value["actor"].update(scores={"agency": True}),
    lambda value: value["actor"].update(scores={"agency": float("nan")}),
    lambda value: value["actor"].update(scores={"agency": .5}),
    lambda value: value["actor"].update(label="inspector", scores={"agency": .9, "inspector": .1}),
])
def test_bad_prediction_distributions_reject(mutation):
    value = predictions()
    mutation(value)
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1.), [candidate("a")], policy="facet_cover", predicted_facets=value)


def test_shortlist_is_applied_before_diversity_and_bounds_return_count():
    choices = [candidate("a", vector(1.)), candidate("b", vector(.9, .1)),
               candidate("c", vector(0., 1.), target("inspector"))]
    predicted = predictions("inspector")
    result = subject.rerank_candidates("query", vector(1.), choices, policy="facet_cover", top_k=2,
                                       shortlist=2, predicted_facets=predicted)
    assert {item["candidate_id"] for item in result["retrieved"]} == {"a", "b"}
    assert result["trace"]["shortlist_count"] == 2 and result["trace"]["candidate_count"] == 3
    assert [item["candidate_id"] for item in result["trace"]["shortlist"]] == ["a", "b"]
    single = subject.rerank_candidates("query", vector(1.), choices[:1], policy="cosine")
    assert len(single["retrieved"]) == 1


@pytest.mark.parametrize("policy", ["cosine", "mmr", "facet_cover"])
def test_trace_exposes_exact_normalized_stable_cosine_shortlist_before_policy(policy):
    choices = [candidate("d", vector(0., 1.)), candidate("a", vector(2., 1.)),
               candidate("c", vector(1.)), candidate("b", vector(3.))]
    pool = subject.prepare_training_candidates(choices)
    options = {"predicted_facets": predictions() if policy == "facet_cover" else None}
    result = subject.rerank_candidates("query", vector(7.), pool, policy=policy, shortlist=3, top_k=2, **options)
    shortlist = result["trace"]["shortlist"]
    assert [item["candidate_id"] for item in shortlist] == ["b", "c", "a"]
    assert [item["cosine_similarity"] for item in shortlist] == pytest.approx([1., 1., 2/math.sqrt(5)])
    plain = subject.rerank_candidates("query", vector(7.), pool, policy="cosine", shortlist=3, top_k=3)
    assert shortlist == [{"candidate_id": item["candidate_id"], "cosine_similarity": item["cosine_similarity"]}
                         for item in plain["retrieved"]]
    assert {item["candidate_id"] for item in result["retrieved"]} <= {item["candidate_id"] for item in shortlist}


def test_source_query_and_candidate_caps_reject():
    with pytest.raises(ValueError):
        subject.fit_facet_probe([row(str(i)) for i in range(513)])
    with pytest.raises(ValueError):
        subject.rerank_candidates("query", vector(1.), [candidate(str(i)) for i in range(513)], policy="cosine")


def test_prediction_batch_cap_rejects(probe):
    with pytest.raises(ValueError):
        subject.predict_source_facets([vector(1.)] * 513, probe)

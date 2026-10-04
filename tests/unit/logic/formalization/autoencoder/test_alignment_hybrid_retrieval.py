"""Frozen pair linkage, fixed discovery budgets and source-only selection."""
import importlib.util
import json
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_joint_retrieval as joint
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval as base

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_hybrid_retrieval.py"
spec = importlib.util.spec_from_file_location("alignment_hybrid_retrieval_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def target(actor="agency", action="file", object_="notice", modality="O", conditions=None):
    return {"rules": [{"modality": modality, "actor": actor, "action": action, "object": object_,
                       "conditions": conditions or [], "exceptions": [], "temporal": []}]}


def vector(*values, width=384):
    return list(values) + [0.] * (width - len(values))


def cosine_vector(score, width=384):
    return vector(score, math.sqrt(1-score*score), width=width)


def candidate(identity, rule=None):
    return {"candidate_id": identity, "target": rule or target(conditions=["condition_"+identity]),
            "source_vector": vector(1.), "train_ids": ["train-"+identity]}


def predictions():
    return {facet: {"label": label, "scores": {label: 1.}}
            for facet, label in (("modality", "O"), ("actor", "agency"), ("action", "file"), ("object", "notice"))}


def pair_from_orders(source_order, formal_order, candidates=None, *, source_width=384, formal_width=384):
    identities = sorted(set(source_order) | set(formal_order))
    if candidates is None:
        candidates = [candidate(identity) for identity in identities]
    source = {identity: cosine_vector(.99-.005*index, source_width) for index, identity in enumerate(source_order)}
    formal = {identity: cosine_vector(.99-.005*index, formal_width) for index, identity in enumerate(formal_order)}
    source.update({identity: cosine_vector(.2, source_width) for identity in identities if identity not in source})
    formal.update({identity: cosine_vector(.2, formal_width) for identity in identities if identity not in formal})
    return subject.prepare_hybrid_candidate_pair(candidates, source_candidate_vectors=source, formal_candidate_vectors=formal)


def batch(pair, *, predicted=None, source_query=None, formal_query=None, **options):
    return subject.rerank_hybrid_policies("query", source_query or vector(1., width=pair.source_candidates.dimension),
                                          formal_query or vector(1., width=pair.formal_candidates.dimension), pair,
                                          predicted_facets=predicted or predictions(), **options)


def by_policy(rankings):
    return {row["policy"]: row for row in rankings}


def ids(items):
    return [item["candidate_id"] for item in items]


def test_import_and_all_policies_load_no_optional_models():
    code = """
import importlib.abc
import importlib.util
import sys
class RejectModels(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name.split('.')[0] in {'torch','transformers','sentence_transformers','spacy'}:
            raise AssertionError('optional model imported')
sys.meta_path.insert(0,RejectModels())
spec=importlib.util.spec_from_file_location('lazy_hybrid',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rule={'modality':'O','actor':'agency','action':'file','object':'notice','conditions':[],'exceptions':[],'temporal':[]}
query=[1.]+[0.]*383
candidate={'candidate_id':'a','source_vector':query,'target':{'rules':[rule]},'train_ids':['train-a']}
pair=module.prepare_hybrid_candidate_pair([candidate],source_candidate_vectors={'a':query},formal_candidate_vectors={'a':query})
predicted={facet:{'label':rule[facet],'scores':{rule[facet]:1.}} for facet in ('modality','actor','action','object')}
results=module.rerank_hybrid_policies('query',query,query,pair,predicted_facets=predicted)
assert len(results)==5
assert all(result['trace']['joint_coverage']==1. for result in results)
assert 'torch' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(MODULE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_pair_manifest_binds_full_qualifiers_and_training_memberships():
    original = [candidate("a", target(conditions=["first_qualifier"]))]
    maps = {"a": vector(1.)}
    one = subject.prepare_hybrid_candidate_pair(original, source_candidate_vectors=maps, formal_candidate_vectors=maps)
    modified = deepcopy(original)
    modified[0]["target"]["rules"][0]["conditions"] = ["second_qualifier"]
    two = subject.prepare_hybrid_candidate_pair(modified, source_candidate_vectors=maps, formal_candidate_vectors=maps)
    assert one.source_candidates._rows[0][1] == two.source_candidates._rows[0][1]
    assert one.shared_candidate_manifest_sha256 != two.shared_candidate_manifest_sha256
    modified = deepcopy(original)
    modified[0]["train_ids"] = ["other-training-row"]
    three = subject.prepare_hybrid_candidate_pair(modified, source_candidate_vectors=maps, formal_candidate_vectors=maps)
    assert one.shared_candidate_manifest_sha256 != three.shared_candidate_manifest_sha256


def test_pair_geometry_changes_preserve_shared_canonical_manifest():
    candidates = [candidate("a"), candidate("b")]
    source = {"a": vector(1.), "b": vector(0., 1.)}
    formal = {"a": vector(0., 1.), "b": vector(1.)}
    pair = subject.prepare_hybrid_candidate_pair(candidates, source_candidate_vectors=source, formal_candidate_vectors=formal)
    reversed_pair = subject.prepare_hybrid_candidate_pair(list(reversed(candidates)), source_candidate_vectors=formal, formal_candidate_vectors=source)
    assert pair.shared_candidate_manifest_sha256 == reversed_pair.shared_candidate_manifest_sha256
    assert pair.source_candidates.admission_sha256 != pair.formal_candidates.admission_sha256
    assert {row[0]: (row[1], set(row[3])) for row in pair.source_candidates._rows} == {
        row[0]: (row[1], set(row[3])) for row in pair.formal_candidates._rows}


def test_input_mutation_does_not_change_factory_snapshot_and_pair_is_immutable():
    candidates = [candidate("a"), candidate("b")]
    source = {"a": vector(1.), "b": vector(0., 1.)}
    formal = {"a": vector(0., 1.), "b": vector(1.)}
    pair = subject.prepare_hybrid_candidate_pair(candidates, source_candidate_vectors=source, formal_candidate_vectors=formal)
    expected = batch(pair)
    source["a"][0] = float("nan")
    formal["b"][0] = 0.
    candidates[0]["target"]["rules"][0]["conditions"] = ["changed"]
    candidates[0]["train_ids"].append("query")
    assert batch(pair) == expected
    with pytest.raises(AttributeError):
        pair.formal_candidates = pair.source_candidates
    with pytest.raises(ValueError):
        subject.PreparedHybridCandidatePair()


@pytest.mark.parametrize("width", [384, 512])
def test_controls_exactly_replay_existing_joint_retrieved_items_and_embedded_traces(width):
    pair = pair_from_orders(["a", "b", "c"], ["c", "b", "a"], source_width=width, formal_width=width)
    query = vector(1., width=width)
    ranks = by_policy(batch(pair))
    for policy, prepared in (("source_only", pair.source_candidates), ("formal_only", pair.formal_candidates)):
        original = joint.rerank_joint_candidates("query", query, prepared, variant="hard_joint", predicted_facets=predictions())
        assert ranks[policy]["retrieved"] == original["retrieved"]
        assert ranks[policy]["trace"]["embedded_joint_trace"] == original["trace"]
        assert ranks[policy]["trace"]["shortlist"] == original["trace"]["shortlist"]


def test_source_discovery_formal_selection_changes_only_selector_geometry():
    candidates = [candidate("a", target()), candidate("b", target("inspector", "review", "records", "P"))]
    pair = subject.prepare_hybrid_candidate_pair(candidates,
        source_candidate_vectors={"a": cosine_vector(.99), "b": cosine_vector(.5)},
        formal_candidate_vectors={"a": cosine_vector(.1), "b": cosine_vector(.99)})
    ranks = by_policy(batch(pair))
    assert ids(ranks["source_only"]["retrieved"])[0] == "a"
    assert ids(ranks["formal_only"]["retrieved"])[0] == "b"
    assert ids(ranks["source_discovery_formal_select"]["retrieved"])[0] == "b"
    assert ids(ranks["source_discovery_formal_select"]["trace"]["shortlist"]) == ids(ranks["source_only"]["trace"]["shortlist"])
    assert ranks["source_discovery_formal_select"]["trace"]["selector_geometry"] == "formal"
    assert ranks["source_discovery_formal_select"]["trace"]["embedded_joint_trace"] is None


def test_rrf_uses_equal_prefix_ranks_missing_zero_and_formal_cosine_selection():
    pair = pair_from_orders(["a", "b"], ["b", "c"])
    ranks = by_policy(batch(pair, top_k=2, shortlist=2, head_budget=2))
    fusion = ranks["rrf_formal"]
    union = {item["candidate_id"]: item for item in fusion["trace"]["unpruned_union"]}
    assert union["a"]["rrf_score"] == 1/61 and union["a"]["formal_rank"] is None
    assert union["c"]["rrf_score"] == 1/62 and union["c"]["source_rank"] is None
    assert union["b"]["rrf_score"] == 1/62 + 1/61
    assert ids(fusion["trace"]["shortlist"]) == ["b", "a"]
    assert union["a"]["cosine_similarity"] == pytest.approx(.2)
    assert fusion["trace"]["upstream_discovery_budget"] == 4 and fusion["trace"]["final_budget"] == 2
    assert fusion["trace"]["rrf_used_as_selection_relevance"] is False
    for item in fusion["retrieved"]:
        assert item["cosine_similarity"] == union[item["candidate_id"]]["formal_cosine_similarity"]
        assert item["selection_score"] == .7*((item["cosine_similarity"]+1)/2) + (1-.7)*item["marginal_joint_coverage"]
    for policy in ("source_only", "formal_only", "source_discovery_formal_select"):
        assert ranks[policy]["trace"]["upstream_discovery_budget"] == 2
        assert ranks[policy]["trace"]["unpruned_union"] == fusion["trace"]["unpruned_union"]


def test_quota_preserves_both_top_halves_then_alternates_unique_fill():
    pair = pair_from_orders(["a", "b", "c", "d", "e", "f"], ["a", "b", "g", "h", "e", "f"])
    rank = by_policy(batch(pair, top_k=2, shortlist=6, head_budget=6))["quota_formal"]
    assert ids(rank["trace"]["shortlist"]) == ["a", "b", "c", "g", "d", "h"]
    assert len(set(ids(rank["trace"]["shortlist"]))) == 6
    assert {"a", "b", "c", "g"} <= set(ids(rank["trace"]["shortlist"]))


def test_rrf_ties_are_stable_ids_and_formal_scores_do_not_change_discovery():
    pair = pair_from_orders(["z", "shared"], ["a", "shared"])
    ranks = by_policy(batch(pair, top_k=1, shortlist=2, head_budget=2))
    assert ids(ranks["rrf_formal"]["trace"]["shortlist"]) == ["shared", "a"]
    assert ids(ranks["quota_formal"]["trace"]["shortlist"]) == ["z", "a"]


def test_union_support_can_be_lost_during_rrf_and_quota_pruning():
    shared = [f"shared_{i:02}" for i in range(19)]
    source_only, action = "a_source_decoy", "z_action_support"
    candidates = [candidate(identity, target("agency", "review", conditions=["condition_"+identity])) for identity in shared]
    candidates += [candidate(source_only, target("inspector", "review", "records", "P")),
                   candidate(action, target("inspector", "file"))]
    pair = pair_from_orders(shared+[source_only], shared+[action], candidates)
    ranks = by_policy(batch(pair))
    assert ranks["formal_only"]["trace"]["joint_coverage"] == 1.
    for policy in ("rrf_formal", "quota_formal"):
        trace = ranks[policy]["trace"]
        assert action in ids(trace["unpruned_union"])
        assert action not in ids(trace["shortlist"])
        assert trace["joint_coverage"] == .5
        assert trace["factorization"]["union_support_guaranteed_retained"] is False
        assert trace["unpruned_union_count"] == 21 and trace["shortlist_count"] == 20


def test_quota_can_retain_top_half_novel_support_that_rrf_shared_votes_discard():
    shared = [f"shared_{i:02}" for i in range(16)]
    source_unique = [f"source_{i}" for i in range(4)]
    action = "action_support"
    formal_other = [f"formal_{i}" for i in range(3)]
    source_order = source_unique+shared
    formal_order = shared[:4]+[action]+shared[4:]+formal_other
    candidates = [candidate(identity, target("agency", "review", conditions=["condition_"+identity])) for identity in shared]
    candidates += [candidate(identity, target("inspector", "review", "records", "P", ["condition_"+identity]))
                   for identity in source_unique+formal_other]
    candidates.append(candidate(action, target("inspector", "file")))
    pair = pair_from_orders(source_order, formal_order, candidates)
    ranks = by_policy(batch(pair))
    assert action not in ids(ranks["rrf_formal"]["trace"]["shortlist"])
    assert action in ids(ranks["quota_formal"]["trace"]["shortlist"])
    assert ranks["quota_formal"]["trace"]["joint_coverage"] == 1.
    assert ranks["rrf_formal"]["trace"]["joint_coverage"] == .5


def test_wrong_prediction_can_select_wrong_meaning_and_no_adaptive_gold_routing():
    candidates = [candidate("a", target()), candidate("b", target("inspector", "review", "records", "P"))]
    pair = pair_from_orders(["a", "b"], ["a", "b"], candidates)
    wrong = {facet: {"label": label, "scores": {label: 1.}} for facet, label in
             (("modality", "P"), ("actor", "inspector"), ("action", "review"), ("object", "records"))}
    for rank in batch(pair, predicted=wrong):
        assert ids(rank["retrieved"])[0] == "b"
        assert rank["trace"]["factorization"]["source_fidelity_guaranteed"] is False
        assert rank["trace"]["qualified"] is False and rank["trace"]["query_target_consumed"] is False
    for supplied in ({"query_target": target()}, {"targets": [target()]}, {"groups": ["hidden"]}):
        with pytest.raises(TypeError):
            batch(pair, **supplied)


def test_query_in_excluded_training_candidate_is_rejected_against_full_pool():
    candidates = [candidate(f"c{i:02}") for i in range(41)]
    candidates[-1]["train_ids"] = ["query"]
    source = {item["candidate_id"]: cosine_vector(.99-.01*i if i<20 else -.5) for i, item in enumerate(candidates)}
    formal = {item["candidate_id"]: cosine_vector(.99-.01*(i-20) if 20<=i<40 else -.5) for i, item in enumerate(candidates)}
    pair = subject.prepare_hybrid_candidate_pair(candidates, source_candidate_vectors=source, formal_candidate_vectors=formal)
    with pytest.raises(ValueError, match="query ID"):
        batch(pair)


def test_default_discovery_union_can_consult_forty_candidates_at_final_twenty():
    source_ids, formal_ids = [f"s{i:02}" for i in range(20)], [f"f{i:02}" for i in range(20)]
    pair = pair_from_orders(source_ids, formal_ids)
    for rank in batch(pair):
        trace = rank["trace"]
        assert trace["unpruned_union_count"] == 40 and trace["shortlist_count"] == 20
        assert len(rank["retrieved"]) == 5
        assert trace["unpruned_union_sha256"] == base._digest(trace["unpruned_union"])
        assert trace["source_head_budget"] == 20 and trace["formal_head_budget"] == 20
        assert trace["upstream_discovery_budget"] == (40 if rank["policy"] in ("rrf_formal", "quota_formal") else 20)
        assert trace["batch_computed_both_heads"] is True
        assert all("candidate_id" in row and "cosine_similarity" in row for row in trace["unpruned_union"])


def test_batch_order_matches_single_policy_facade_and_is_thread_safe():
    pair = pair_from_orders(["a", "b", "c"], ["c", "b", "a"])
    policies = tuple(reversed(subject.POLICIES))
    expected = batch(pair, policies=policies)
    assert [rank["policy"] for rank in expected] == list(policies)
    for rank in expected:
        assert subject.rerank_hybrid_candidates("query", vector(1.), vector(1.), pair, policy=rank["policy"],
                                                predicted_facets=predictions()) == rank
    predicted = predictions()
    original = deepcopy(predicted)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: batch(pair, policies=policies, predicted=predicted), range(8)))
    assert all(result == expected for result in results)
    assert predicted == original


@pytest.mark.parametrize("mutation", [
    lambda values: values.append(deepcopy(values[0])),
    lambda values: values[0].update(source_vector=vector(0.)),
    lambda values: values[0].update(source_vector=vector(True)),
    lambda values: values[0].update(source_vector=vector(float("inf"))),
    lambda values: values[0].update(train_ids=["same", "same"]),
    lambda values: values[1].update(train_ids=values[0]["train_ids"]),
    lambda values: values[0]["target"]["rules"][0].update(conditions=["z", "a"]),
    lambda values: values[0].update(query_target=target()),
])
def test_pair_admission_preserves_closed_canonical_training_and_membership_contract(mutation):
    values = [candidate("a"), candidate("b")]
    mutation(values)
    maps = {"a": vector(1.), "b": vector(0., 1.)}
    with pytest.raises(ValueError):
        subject.prepare_hybrid_candidate_pair(values, source_candidate_vectors=maps, formal_candidate_vectors=maps)


@pytest.mark.parametrize("maps", [{}, {"a": vector(1.)}, {"a": vector(1.), "b": vector(1.), "foreign": vector(1.)},
                                   {"a": vector(True), "b": vector(1.)}, {"a": vector(0.), "b": vector(1.)},
                                   {"a": vector(float("nan")), "b": vector(1.)},
                                   {"a": vector(1.), "b": vector(1., width=512)}])
def test_head_maps_require_matching_ids_consistent_widths_and_finite_nonzero_numbers(maps):
    with pytest.raises(ValueError):
        subject.prepare_hybrid_candidate_pair([candidate("a"), candidate("b")], source_candidate_vectors=maps,
                                                formal_candidate_vectors={"a": vector(1.), "b": vector(1.)})


@pytest.mark.parametrize("source", [vector(0.), vector(True), vector(float("nan")), vector(float("inf")), [1.]*383])
def test_both_queries_receive_finite_nonzero_shape_guards(source):
    pair = pair_from_orders(["a"], ["a"])
    for bad_source, bad_formal in ((source, vector(1.)), (vector(1.), source)):
        with pytest.raises(ValueError):
            subject.rerank_hybrid_policies("query", bad_source, bad_formal, pair, predicted_facets=predictions())


@pytest.mark.parametrize("options", [{"top_k": True}, {"head_budget": 513}, {"shortlist": 0},
                                      {"shortlist": 21, "head_budget": 20}, {"shortlist": 3},
                                      {"rrf_k": True}, {"rrf_k": 0}, {"rrf_k": 60.0},
                                      {"diversity_lambda": True}, {"diversity_lambda": float("nan")},
                                      {"diversity_lambda": -1}, {"diversity_lambda": 2},
                                      {"policies": []}, {"policies": ["source_only", "source_only"]},
                                      {"policies": ["adaptive_gold"]}])
def test_bounded_budgets_fixed_policy_set_and_numeric_recipe_reject_invalid_inputs(options):
    pair = pair_from_orders(["a"], ["a"])
    with pytest.raises(ValueError):
        batch(pair, **options)


def test_predictions_are_closed_and_pair_requires_checked_factory():
    pair = pair_from_orders(["a"], ["a"])
    malformed = predictions()
    malformed["actor"]["scores"]["agency"] = float("nan")
    with pytest.raises(ValueError):
        subject.rerank_hybrid_policies("query", vector(1.), vector(1.), pair, predicted_facets=malformed)
    for foreign in ({}, pair.source_candidates):
        with pytest.raises(ValueError):
            subject.rerank_hybrid_policies("query", vector(1.), vector(1.), foreign, predicted_facets=predictions())


def test_factory_candidate_count_and_metadata_size_are_bounded(monkeypatch):
    with pytest.raises(ValueError):
        subject.prepare_hybrid_candidate_pair([candidate(str(i)) for i in range(513)],
                                                source_candidate_vectors={}, formal_candidate_vectors={})
    monkeypatch.setattr(subject, "MAX_PAIR_METADATA_BYTES", 128)
    with pytest.raises(ValueError, match="metadata"):
        subject.prepare_hybrid_candidate_pair([candidate("a")], source_candidate_vectors={"a": vector(1.)},
                                                formal_candidate_vectors={"a": vector(1.)})


def test_results_are_finite_json_and_keep_qualification_and_provenance_limits():
    pair = pair_from_orders(["a", "b"], ["b", "a"], source_width=384, formal_width=512)
    ranks = batch(pair)
    assert json.loads(json.dumps(ranks, allow_nan=False)) == ranks
    for rank in ranks:
        trace = rank["trace"]
        assert trace["schema"] == subject.SCHEMA
        assert trace["shared_candidate_manifest_sha256"] == pair.shared_candidate_manifest_sha256
        assert trace["prediction_sha256"] == base._digest(predictions())
        assert trace["source_dimension"] == 384 and trace["formal_dimension"] == 512
        assert trace["query_identity_shared"] is True and trace["query_vector_source_binding"] == "caller_provenance_required"
        assert trace["query_target_consumed"] is False and trace["qualified"] is False
        assert trace["factorization"]["shortlist_support_guaranteed_selected"] is False

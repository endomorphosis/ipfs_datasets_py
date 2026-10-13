"""Closed graph identity, ordering, alternative and endpoint invariants."""
import copy

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_graph as g
from ipfs_datasets_py.logic.autoformal.corpus_contracts import CorpusContractError, seal_record


def cid(label):
    return seal_record({"schema": "test/evidence/v1", "label": label})["record_cid"]


def node(kind, label, **kwargs):
    if kind in g.ASSERTIONS:
        kwargs.setdefault("source_occurrence_cids", [cid("source")])
        kwargs.setdefault("interpretation_cids", [cid("interpretation")])
    return g.build_node(node_type=kind, stable_id=label, content_cid=cid(label), **kwargs)


def edge(src, dst, relation="HAS_ACTOR", **kwargs):
    return g.build_edge(src_cid=src["record_cid"], dst_cid=dst["record_cid"], relation=relation,
                        evidence_cids=[cid("binding")], **kwargs)


def test_snapshot_input_order_is_canonical_without_losing_role_order():
    rule, actor, other = node("norm_assertion", "rule"), node("entity", "actor"), node("entity", "other")
    edges = [edge(rule, actor, ordinal=0), edge(rule, other, ordinal=1)]
    record = g.build_graph_snapshot([rule, actor, other], edges)
    assert record == g.build_graph_snapshot([other, rule, actor], list(reversed(edges)))
    assert sorted((e["ordinal"], e["dst_cid"]) for e in record["edges"]) == [
        (0, actor["record_cid"]), (1, other["record_cid"])]
    assert g.validate_graph_snapshot(record) == record
    assert record["admitted"] is record["formalized"] is record["source_semantics_verified"] is False


def test_same_surface_and_stable_id_can_have_distinct_scoped_versions():
    one = node("term_sense", "Secretary", scope_cid=cid("title one"))
    two = node("term_sense", "Secretary", scope_cid=cid("title two"))
    assert one["record_cid"] != two["record_cid"]
    assert len(g.build_graph_snapshot([one, two], [])["nodes"]) == 2


def test_repeated_semantic_arguments_survive_at_distinct_positions():
    rule, actor = node("norm_assertion", "rule"), node("entity", "actor")
    record = g.build_graph_snapshot([rule, actor], [edge(rule, actor, ordinal=0), edge(rule, actor, ordinal=1)])
    assert len(record["edges"]) == 2


def test_dangling_endpoint_is_not_silently_dropped_or_imported():
    rule, actor = node("norm_assertion", "rule"), node("entity", "actor")
    with pytest.raises(CorpusContractError, match="dangling"):
        g.build_graph_snapshot([rule], [edge(rule, actor, ordinal=0)])


def test_definition_use_requires_typed_endpoints():
    rule, definition, sense = node("norm_assertion", "rule"), node("definition_assertion", "definition"), node("term_sense", "sense")
    edges = [edge(rule, definition, "USES_DEFINITION"), edge(definition, sense, "DEFINES")]
    assert len(g.build_graph_snapshot([rule, definition, sense], edges)["edges"]) == 2
    with pytest.raises(CorpusContractError, match="USES_DEFINITION"):
        g.build_graph_snapshot([rule, sense], [edge(rule, sense, "USES_DEFINITION")])


def test_candidate_alternatives_stay_distinct_and_cross_links_refuse():
    one = node("norm_assertion", "reading A", alternative_group_id="source", alternative_id="A")
    two = node("norm_assertion", "reading B", alternative_group_id="source", alternative_id="B")
    assert len(g.build_graph_snapshot([one, two], [])["nodes"]) == 2
    with pytest.raises(CorpusContractError, match="mutually exclusive"):
        g.build_graph_snapshot([one, two], [edge(one, two, "DERIVED_FROM")])
    with pytest.raises(CorpusContractError, match="together"):
        node("entity", "bad", alternative_group_id="source")


def test_role_positions_cannot_conflict():
    rule, actor, other = node("norm_assertion", "rule"), node("entity", "actor"), node("entity", "other")
    with pytest.raises(CorpusContractError, match="duplicate role argument"):
        g.build_graph_snapshot([rule, actor, other], [edge(rule, actor, ordinal=0), edge(rule, other, ordinal=0)])


@pytest.mark.parametrize("missing", ["source_occurrence_cids", "interpretation_cids"])
def test_assertions_require_provenance_reference_slots(missing):
    with pytest.raises(CorpusContractError):
        node("norm_assertion", "rule", **{missing: []})


def test_duplicate_records_refuse_and_callers_are_not_mutated():
    rule = node("norm_assertion", "rule")
    original = copy.deepcopy(rule)
    result = g.build_graph_snapshot([rule], [])
    result["nodes"][0]["stable_id"] = "changed"
    assert rule == original
    with pytest.raises(CorpusContractError, match="duplicate graph node"):
        g.build_graph_snapshot([rule, rule], [])


@pytest.mark.parametrize("ordinal", [None, True, -1, 0.5])
def test_role_ordinal_is_explicit_and_never_coerced(ordinal):
    with pytest.raises(CorpusContractError):
        edge(node("norm_assertion", "rule"), node("entity", "actor"), ordinal=ordinal)


def test_resealing_does_not_make_candidate_snapshot_reviewed():
    record = g.build_graph_snapshot([node("entity", "actor")], [])
    body = {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}}
    body["admitted"] = True
    with pytest.raises(CorpusContractError, match="candidate-only"):
        g.validate_graph_snapshot(seal_record(body))


@pytest.mark.parametrize("relation", ["HAS_TEMPORAL_CONSTRAINT", "HAS_CONDITION", "HAS_EXCEPTION"])
def test_qualifier_role_destination_cannot_be_an_untyped_entity(relation):
    rule, actor = node("norm_assertion", "rule"), node("entity", "actor")
    with pytest.raises(CorpusContractError, match="incompatible node type"):
        g.build_graph_snapshot([rule, actor], [edge(rule, actor, relation, ordinal=0)])


def test_candidate_assertion_references_are_not_authenticated_by_shape_validation():
    rule = node("norm_assertion", "rule", source_occurrence_cids=[cid("unresolved reference")])
    record = g.build_graph_snapshot([rule], [])
    assert record["source_semantics_verified"] is False
    assert record["admitted"] is False


def test_aggregate_bound_is_checked_before_individual_record_validation(monkeypatch):
    nodes = [node("entity", "actor"), node("entity", "other")]
    monkeypatch.setattr(contracts, "MAX_RECORD_BYTES", 100)

    def should_not_validate(_):
        raise AssertionError("individual validation ran before aggregate bound")

    monkeypatch.setattr(g, "validate_node", should_not_validate)
    with pytest.raises(CorpusContractError, match="byte bound"):
        g.build_graph_snapshot(nodes, [])

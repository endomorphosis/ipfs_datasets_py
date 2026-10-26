"""Explicit fictional parent occurrence projection; no reviewed statutory law.

Reuse the genuine existing physical-parent fixture and unchanged authored A/B
ASTs. Actual section7346's retained837 population is a separate data operation.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_graph
from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as adapter
from ipfs_datasets_py.logic.autoformal import corpus_source
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as proposed
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json


_spec = importlib.util.spec_from_file_location(
    "_lexical_projection_existing_graph_tests", Path(__file__).with_name("test_legal_semantic_graph.py"))
_graph_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_graph_tests)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value):
    return _sha(canonical_dag_json_bytes(value))


def _reseal(value):
    return contracts.seal_record({key: item for key, item in value.items()
                                  if key not in ("record_cid", "cid_scope")})


@pytest.fixture(scope="module")
def lexical_case(tmp_path_factory):
    # This owning fixture deliberately uses an ordinary unique directory.
    # It invokes the existing genuine fixture rather than replacing any owner.
    parent_tests = _graph_tests._graph_depth_fixture("test_legal_source_norm_scope_v1.py")
    value = parent_tests.parent_case(tmp_path_factory.mktemp("parent-lexical-projection", numbered=False))
    source = value["source"]
    scope = proposed.bind_parent_scope(source=source, jurisdiction="unresolved", instrument="unresolved",
        applicability="unresolved", definition_scope="unresolved")
    version, origin = source["source_version"], source["selector"]
    occurrences, declarations = [], []
    for index, literal in enumerate(("Clérk", "may", "retain", "café records")):
        local = origin["span_text"].index(literal)
        start = origin["start_char"] + local
        end = start + len(literal)
        occurrence = corpus_source.build_source_occurrence(version,
            expected_raw_sha256=version["raw_artifact"]["sha256"], extracted_text=value["text"],
            expected_extracted_sha256=version["extracted_view"]["sha256"],
            start_char=start, end_char=end,
            start_utf8=len(value["text"][:start].encode("utf-8")),
            end_utf8=len(value["text"][:end].encode("utf-8")))
        occurrences.append(occurrence)
        declarations.append(dict(entity_key="fictional:lexical:" + str(index), kind="mention", label=literal,
            source_selector=occurrence, definition_kind=None, ast_path=None,
            ambiguity=["Literal occurrence only; no legal role, denotation or meaning is selected."],
            evidence_refs=[]))
    rows = []
    for alternative in ("de_re_list", "de_dicto_list"):
        inputs = dict(ast=json.loads(_graph_tests._SECTION7346_RAW_REQUESTS[alternative]),
            profile="relational_norm_v1", source=source, scope=scope,
            semantic_declarations=dict(entities=declarations, assertions=[]), dependency_refs=[],
            evidence_refs=[dict(artifact_id="fictional-parent-fixture", artifact_sha256="a"*64,
                                role="unverified_authored_transport_only")], scope_request=None)
        graph = proposed.build_graph(**inputs)
        raw = json.dumps(graph, ensure_ascii=False, indent=2).encode("utf-8")
        arguments = dict(expected_proposal_sha256=_sha(raw), trusted_proposal_inputs=inputs,
                         expected_inputs_sha256=_pin(inputs), **value["arguments"])
        prepared = adapter.prepare_parent_lexical_occurrence_projection_v1(raw,
            derived_occurrences=occurrences, expected_derived_occurrences_sha256=_pin(occurrences), **arguments)
        rows.append(dict(alternative=alternative, graph=graph, raw=raw, arguments=arguments, projection=prepared))
    return dict(value=value, occurrences=occurrences, rows=rows)


def _prepare(row, occurrences, *, pin=None):
    return adapter.prepare_parent_lexical_occurrence_projection_v1(row["raw"], derived_occurrences=occurrences,
        expected_derived_occurrences_sha256=_pin(occurrences) if pin is None else pin, **row["arguments"])


def _validate(record, row, occurrences):
    return adapter.validate_parent_lexical_occurrence_projection_v1(record, row["raw"],
        derived_occurrences=occurrences, expected_derived_occurrences_sha256=_pin(occurrences), **row["arguments"])


def test_default_opaque_candidate_and_full_ast_remain_exact(lexical_case):
    row = lexical_case["rows"][0]
    default = adapter.adapt_parent_proposed_graph_bytes(row["raw"], **row["arguments"])
    assert canonical_dag_json_bytes(default) == canonical_dag_json_bytes(row["projection"]["base_candidate"])
    assert default["record_cid"] == row["projection"]["base_candidate"]["record_cid"]
    assert default["proposal_record"]["proposal_json"].encode("utf-8") == row["raw"]
    ast = row["arguments"]["trusted_proposal_inputs"]["ast"]
    assert default["ast_record"]["ast_json"].encode("utf-8") == canonical_dag_json_bytes(ast)
    assert default["ast_record"]["ast_cid"] == cid_for_dag_json(ast)
    assert len(default["graph"]["nodes"]) == 9 and len(default["graph"]["edges"]) == 8


def test_competing_alternatives_share_physical_occurrences_and_only_custody_edges(lexical_case):
    left, right = [row["projection"] for row in lexical_case["rows"]]
    occurrence_ids = {row["record_cid"] for row in lexical_case["occurrences"]}
    nodes, edges = {}, {}
    for projection in (left, right):
        graph = corpus_graph.validate_graph_snapshot(projection["graph"])
        assert len(graph["nodes"]) == 13 and len(graph["edges"]) == 16
        for node in graph["nodes"]:
            if node["record_cid"] in nodes:
                assert canonical_dag_json_bytes(nodes[node["record_cid"]]) == canonical_dag_json_bytes(node)
            nodes[node["record_cid"]] = node
            if node["content_cid"] in occurrence_ids:
                assert node["node_type"] == "occurrence"
                assert node["stable_id"] == node["content_cid"]
                assert node["scope_cid"] is node["alternative_group_id"] is node["alternative_id"] is None
                assert node["interpretation_cids"] == []
        for edge in graph["edges"]:
            edges[edge["record_cid"]] = edge
        assert {node["node_type"] for node in graph["nodes"]} <= {
            "source_version", "occurrence", "interpretation", "expression", "issue"}
        assert {edge["relation"] for edge in graph["edges"]} <= {"HAS_SOURCE", "DERIVED_FROM", "MENTIONS"}
        mentions = [edge for edge in graph["edges"] if edge["relation"] == "MENTIONS"]
        assert {edge["ordinal"] for edge in mentions} == {0, 1, 2, 3}
        assert [binding["source_occurrence_cid"] for binding in projection["mention_bindings"]] == [
            occurrence["record_cid"] for occurrence in lexical_case["occurrences"]]
    union = corpus_graph.build_graph_snapshot(list(nodes.values()), list(edges.values()))
    assert len(union["nodes"]) == 20 and len(union["edges"]) == 27
    assert sum(edge["relation"] == "MENTIONS" for edge in union["edges"]) == 8
    assert [row["entity_id"] for row in left["mention_bindings"]] == [row["entity_id"] for row in right["mention_bindings"]]
    assert [row["derived_from_edge_cid"] for row in left["mention_bindings"]] == [row["derived_from_edge_cid"] for row in right["mention_bindings"]]
    assert {row["mentions_edge_cid"] for row in left["mention_bindings"]}.isdisjoint(
        row["mentions_edge_cid"] for row in right["mention_bindings"])


def test_complete_independent_parent_projection_validation(lexical_case):
    row = lexical_case["rows"][0]
    checked = _validate(row["projection"], row, lexical_case["occurrences"])
    assert canonical_dag_json_bytes(checked) == canonical_dag_json_bytes(row["projection"])
    assert checked is not row["projection"]
    assert checked["training_mask"] == checked["evaluation_gold_mask"] == 0
    assert checked["authority"] is checked["admitted"] is checked["formalized"] is False


def test_projection_outputs_are_detached_from_inputs_and_each_other(lexical_case):
    row = lexical_case["rows"][0]
    occurrences = deepcopy(lexical_case["occurrences"])
    base, graph = deepcopy(row["projection"]["base_candidate"]), deepcopy(row["graph"])
    projected = adapter._parent_lexical_projection(base, graph, occurrences, _pin(occurrences))
    before = canonical_dag_json_bytes(projected)
    occurrences[0]["span_text"] = "changed"
    base["issues"].clear()
    graph["entities"].clear()
    assert canonical_dag_json_bytes(projected) == before
    projected["derived_occurrences"][0]["span_text"] = "another change"
    assert lexical_case["occurrences"][0]["span_text"] == "Clérk"
    assert projected["base_candidate"]["proposal_record"]["proposal_json"] == row["raw"].decode("utf-8")


@pytest.mark.parametrize("damage", ["empty", "tuple", "oversized", "duplicate", "wrong_pin", "wrong_seal"])
def test_independent_list_preflight_refuses_malformed_population(lexical_case, damage):
    row = lexical_case["rows"][0]
    occurrences = deepcopy(lexical_case["occurrences"])
    pin = None
    if damage == "empty":
        occurrences = []
    elif damage == "tuple":
        occurrences = tuple(occurrences)
    elif damage == "oversized":
        occurrences = occurrences * (proposed.MAX_ENTITIES // len(occurrences) + 1)
    elif damage == "duplicate":
        occurrences[1] = occurrences[0]
    elif damage == "wrong_pin":
        pin = "0" * 64
    else:
        occurrences[0]["record_cid"] = occurrences[1]["record_cid"]
    # Pin tuple through its equivalent JSON array to reach the exact plain-list gate.
    if type(occurrences) is tuple:
        pin = _pin(list(occurrences))
    with pytest.raises(contracts.CorpusContractError):
        _prepare(row, occurrences, pin=pin)


@pytest.mark.parametrize("damage", ["reordered", "missing", "foreign_source", "utf8_shift"])
def test_retained_complete_selectors_cannot_be_substituted(lexical_case, damage):
    row = lexical_case["rows"][0]
    occurrences = deepcopy(lexical_case["occurrences"])
    if damage == "reordered":
        occurrences.reverse()
    elif damage == "missing":
        occurrences.pop()
    elif damage == "foreign_source":
        occurrences[0]["source_version_cid"] = lexical_case["occurrences"][1]["record_cid"]
        occurrences[0] = _reseal(occurrences[0])
    else:
        occurrences[0]["start_utf8"] += 1
        occurrences[0]["end_utf8"] += 1
        occurrences[0] = _reseal(occurrences[0])
    # These genuine source-validated base/graph records isolate the projection's
    # complete-selector gate; no fixture or physical owner is replaced.
    with pytest.raises(contracts.CorpusContractError, match="population|selector"):
        adapter._parent_lexical_projection(row["projection"]["base_candidate"], row["graph"], occurrences, _pin(occurrences))


@pytest.mark.parametrize("damage", ["concept", "definition", "typed_path"])
def test_no_concept_definition_or_typed_role_is_projected(lexical_case, damage):
    row = lexical_case["rows"][0]
    graph = deepcopy(row["graph"])
    declaration = graph["entities"][0]["declaration"]
    if damage == "typed_path":
        declaration["ast_path"] = "/expression/root"
    else:
        declaration["kind"] = damage
    with pytest.raises(contracts.CorpusContractError, match="mention-only"):
        adapter._parent_lexical_projection(row["projection"]["base_candidate"], graph,
            lexical_case["occurrences"], _pin(lexical_case["occurrences"]))


@pytest.mark.parametrize("damage", ["boolean_mask", "integer_authority", "missing_endpoint"])
def test_resealed_projection_requires_exact_independent_regeneration(lexical_case, damage):
    row = lexical_case["rows"][0]
    projection = deepcopy(row["projection"])
    if damage == "boolean_mask":
        projection["training_mask"] = False
        assert projection["training_mask"] == 0
    elif damage == "integer_authority":
        projection["authority"] = 0
        assert projection["authority"] == False
    else:
        projection["graph"]["nodes"].pop()
        projection["graph"] = _reseal(projection["graph"])
    projection = _reseal(projection)
    with pytest.raises(contracts.CorpusContractError, match="independently regenerated"):
        _validate(projection, row, lexical_case["occurrences"])


def test_competing_original_cannot_validate_another_alternative_projection(lexical_case):
    left, right = lexical_case["rows"]
    with pytest.raises(contracts.CorpusContractError, match="independently regenerated"):
        _validate(left["projection"], right, lexical_case["occurrences"])

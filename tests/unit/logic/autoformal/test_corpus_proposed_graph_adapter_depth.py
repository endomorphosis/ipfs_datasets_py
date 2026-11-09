"""Bounded relational custody using existing authored official-source fixtures.

The unchanged section7346 request bytes exercise transport, not correspondence
to this fictional fixture. Actual837-parent replay is a separate data operation.
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
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as proposed
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json


_spec = importlib.util.spec_from_file_location(
    "_corpus_depth_existing_graph_tests", Path(__file__).with_name("test_legal_semantic_graph.py"))
_graph_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_graph_tests)
# Reuse the existing pytest fixture unchanged; it creates no temporary files.
case = _graph_tests.case


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value):
    return _sha(canonical_dag_json_bytes(value))


def _inputs(ast, *, profile="relational_norm_v1"):
    return dict(ast=ast, profile=profile, source=None, scope=None,
                semantic_declarations=None, dependency_refs=[], evidence_refs=[], scope_request=None)


def _nested(depth):
    value = 0
    for _ in range(depth):
        value = [value]
    return value


def _proposal(case, ast, *, profile="relational_norm_v1"):
    inputs = _inputs(ast, profile=profile)
    inputs.update(source=case["source"], scope=case["scope"])
    graph = proposed.build_graph(**inputs)
    raw = json.dumps(graph, ensure_ascii=False, indent=2).encode("utf-8")
    arguments = dict(expected_proposal_sha256=_sha(raw), trusted_proposal_inputs=inputs,
        expected_inputs_sha256=_pin(inputs), document=case["document"], raw_html=_graph_tests.RAW,
        expected_raw_sha256=_sha(_graph_tests.RAW),
        expected_extracted_sha256=_sha(case["document"]["document_text"].encode("utf-8")))
    return raw, graph, arguments


def _adapt(case, ast, *, profile="relational_norm_v1"):
    raw, graph, arguments = _proposal(case, ast, profile=profile)
    return adapter.adapt_proposed_graph_bytes(raw, **arguments), graph, arguments


def _reseal(record):
    return contracts.seal_record({key: value for key, value in record.items()
                                  if key not in ("record_cid", "cid_scope")})


def _replace_custody(record, raw, ast, *, independent_inputs=None):
    """Recompute every affected envelope/node/edge, without replacing originals."""
    changed = deepcopy(record)
    old_ast_cid = changed["ast_record"]["record_cid"]
    old_binding_cid = changed["input_binding"]["record_cid"]
    changed["ast_record"].update(ast_json=raw.decode("utf-8"), ast_sha256=_sha(raw),
                                 ast_cid=cid_for_dag_json(ast))
    changed["ast_record"] = _reseal(changed["ast_record"])
    changed["input_binding"]["ast_record_cid"] = changed["ast_record"]["record_cid"]
    if independent_inputs is not None:
        changed["input_binding"].update(inputs_sha256=_pin(independent_inputs),
                                         inputs_cid=cid_for_dag_json(independent_inputs))
    changed["input_binding"] = _reseal(changed["input_binding"])
    replacements, nodes = {}, []
    for original in changed["graph"]["nodes"]:
        node = deepcopy(original)
        if node["node_type"] == "expression" and node["content_cid"] == old_ast_cid:
            node.update(stable_id=changed["ast_record"]["record_cid"],
                        content_cid=changed["ast_record"]["record_cid"])
            node = _reseal(node)
            replacements[original["record_cid"]] = node["record_cid"]
        nodes.append(node)
    edges = []
    for original in changed["graph"]["edges"]:
        edge = deepcopy(original)
        edge["src_cid"] = replacements.get(edge["src_cid"], edge["src_cid"])
        edge["dst_cid"] = replacements.get(edge["dst_cid"], edge["dst_cid"])
        edge["evidence_cids"] = [changed["input_binding"]["record_cid"] if cid == old_binding_cid else cid
                                 for cid in edge["evidence_cids"]]
        edges.append(_reseal(edge))
    changed["graph"] = corpus_graph.build_graph_snapshot(nodes, edges)
    return _reseal(changed)


@pytest.mark.parametrize("alternative, expected_raw_sha256", [
    ("de_re_list", "c144d6c030c0adc48e7c91d3d51661a34738044e63c23db964523dc90304db8a"),
    ("de_dicto_list", "8584889c9d458e8d3c8b293153a5f0b74a4e48ef5927b4053a17a0af3cdceed3"),
])
def test_unchanged_section7346_depth27_ingress_and_restore(case, alternative, expected_raw_sha256):
    raw = _graph_tests._SECTION7346_RAW_REQUESTS[alternative]
    assert _sha(raw) == expected_raw_sha256
    ast = json.loads(raw)
    original = deepcopy(ast)
    assert _graph_tests._json_tree_depth(ast) == 27 and ast["source_binding"] is None
    record, graph, arguments = _adapt(case, ast)
    restored = adapter.restore_proposed_graph_ast(record, **arguments)
    assert ast == original == restored and restored is not ast
    assert record["ast_record"]["schema"] == adapter.AST_JSON_SCHEMA
    assert record["ast_record"]["ast_json"].encode("utf-8") == canonical_dag_json_bytes(original)
    assert record["ast_record"]["ast_cid"] == cid_for_dag_json(original)
    assert record["proposal_record"]["proposal_graph_id"] == graph["graph_id"]
    assert not any(graph["authority"].values()) and graph["entities"] == graph["assertions"] == []
    assert {node["node_type"] for node in record["graph"]["nodes"]} <= {
        "source_version", "occurrence", "interpretation", "expression", "issue"}
    assert {edge["relation"] for edge in record["graph"]["edges"]} <= {"HAS_SOURCE", "DERIVED_FROM"}
    assert record["admitted"] is record["formalized"] is record["source_semantics_verified"] is False


def test_exact_relational_depth32_ingress_and_restore(case):
    ast = _graph_tests._relational_depth_request(32)
    assert _graph_tests._json_tree_depth(ast) == 32
    record, _, arguments = _adapt(case, ast)
    assert adapter._inputs(arguments["trusted_proposal_inputs"], arguments["expected_inputs_sha256"])["ast"] == ast
    assert adapter.restore_proposed_graph_ast(record, **arguments) == ast


def test_depth33_independent_inputs_refuse_ingress_and_resealed_restore(case):
    record, _, arguments = _adapt(case, _graph_tests._relational_depth_request(32))
    deeper = _graph_tests._relational_depth_request(33)
    assert _graph_tests._json_tree_depth(deeper) == 33
    bad_inputs = deepcopy(arguments["trusted_proposal_inputs"])
    bad_inputs["ast"] = deeper
    bad_arguments = dict(arguments, trusted_proposal_inputs=bad_inputs, expected_inputs_sha256=_pin(bad_inputs))
    with pytest.raises(contracts.CorpusContractError, match="depth/node"):
        adapter._inputs(bad_inputs, bad_arguments["expected_inputs_sha256"])
    changed = _replace_custody(record, canonical_dag_json_bytes(deeper), deeper, independent_inputs=bad_inputs)
    with pytest.raises(contracts.CorpusContractError, match="depth/node"):
        adapter.restore_proposed_graph_ast(changed, **bad_arguments)


@pytest.mark.parametrize("damage", ["depth33", "duplicate_key", "nonfinite"])
def test_resealed_ast_json_cannot_replace_independent_ast(case, damage):
    record, _, arguments = _adapt(case, _graph_tests._relational_depth_request(32))
    if damage == "depth33":
        ast = _graph_tests._relational_depth_request(33)
        raw = canonical_dag_json_bytes(ast)
    elif damage == "duplicate_key":
        ast, raw = {"x": 1}, b'{"x":0,"x":1}'
    else:
        ast, raw = {"x": 0}, b'{"x":NaN}'
    changed = _replace_custody(record, raw, ast)
    assert changed["record_cid"] != record["record_cid"]
    with pytest.raises(contracts.CorpusContractError, match="independently regenerated"):
        adapter.restore_proposed_graph_ast(changed, **arguments)


def test_common_and_nonrelational_depth20_remain_unchanged():
    at20, at21 = _nested(20), _nested(21)
    assert contracts.clone_json(at20) == at20
    assert contracts.load_json_bytes(canonical_dag_json_bytes(at20), expected_sha256=_pin(at20)) == at20
    for operation in (lambda: contracts.clone_json(at21),
                      lambda: contracts.load_json_bytes(canonical_dag_json_bytes(at21), expected_sha256=_pin(at21))):
        with pytest.raises(contracts.CorpusContractError, match="depth"):
            operation()
    value = _inputs(_nested(19), profile="canonical_rules_v1")
    assert adapter._inputs(value, _pin(value)) == contracts.clone_json(value)
    value["ast"] = _nested(20)
    with pytest.raises(contracts.CorpusContractError, match="depth"):
        adapter._inputs(value, _pin(value))


def test_non_ast_metadata_keeps_global_depth20():
    value = _inputs(_nested(32))
    value["semantic_declarations"] = _nested(19)
    assert adapter._inputs(value, _pin(value)) == value
    value["semantic_declarations"] = _nested(20)
    with pytest.raises(contracts.CorpusContractError, match="metadata.*depth"):
        adapter._inputs(value, _pin(value))


def test_unknown_profile_cannot_expand_json_depth():
    value = _inputs(_nested(27), profile="unknown_relational_profile")
    with pytest.raises(contracts.CorpusContractError, match="depth"):
        adapter._inputs(value, _pin(value))


def test_relational_ast_node_limit_is4096():
    value = _inputs([None]*4095)
    assert adapter._inputs(value, _pin(value)) == value
    value["ast"].append(None)
    with pytest.raises(contracts.CorpusContractError, match="depth/node"):
        adapter._inputs(value, _pin(value))


def test_actual_envelope_shares_node_budget25000():
    # Root +4096 AST nodes +seven metadata values =4104; replacing one
    # metadata None by this list adds20896 more nodes, for exactly25000.
    value = _inputs([None]*4095)
    value["semantic_declarations"] = [None]*20896
    assert adapter._inputs(value, _pin(value)) == value
    value["semantic_declarations"].append(None)
    with pytest.raises(contracts.CorpusContractError, match="aggregate JSON node"):
        adapter._inputs(value, _pin(value))


def test_actual_envelope_shares_byte_budget1m():
    value = _inputs("a"*(contracts.MAX_RECORD_BYTES//2))
    value["semantic_declarations"] = ""
    remaining = contracts.MAX_RECORD_BYTES-len(canonical_dag_json_bytes(value))
    value["semantic_declarations"] = "b"*remaining
    assert len(canonical_dag_json_bytes(value)) == contracts.MAX_RECORD_BYTES
    assert adapter._inputs(value, _pin(value)) == value
    value["semantic_declarations"] += "b"
    with pytest.raises(contracts.CorpusContractError, match="aggregate byte"):
        adapter._inputs(value, _pin(value))


def test_relational_policy_retains_common_scalar_and_key_rules():
    class ForeignString(str):
        pass

    bad_values = [float("nan"), float("inf"), 1 << 63, (0,), {0}, ForeignString("x"), "\x00", "\ud800"]
    for bad in bad_values:
        value = _inputs(bad)
        with pytest.raises(contracts.CorpusContractError):
            adapter._clone_relational_inputs(value)
    for key in (0, "", "\x00", "k"*4097, ForeignString("x")):
        value = _inputs({key: 0})
        with pytest.raises(contracts.CorpusContractError):
            adapter._clone_relational_inputs(value)
    value = _inputs(0)
    value["unrecognized"] = None
    with pytest.raises(contracts.CorpusContractError, match="closed"):
        adapter._inputs(value, "0"*64)


def test_bounded_inputs_and_restored_ast_are_detached(case):
    ast = json.loads(_graph_tests._SECTION7346_RAW_REQUESTS["de_re_list"])
    record, _, arguments = _adapt(case, ast)
    original = deepcopy(arguments["trusted_proposal_inputs"])
    detached = adapter._inputs(original, _pin(original))
    detached["ast"]["source_binding"] = {"foreign": True}
    assert original == arguments["trusted_proposal_inputs"]
    restored = adapter.restore_proposed_graph_ast(record, **arguments)
    restored["expression"].clear()
    assert arguments["trusted_proposal_inputs"] == original
    assert adapter.restore_proposed_graph_ast(record, **arguments) == original["ast"]


def test_legacy_v1_candidate_identity_and_ast_storage_stay_unchanged(case):
    record, graph, arguments = _adapt(case, case["ast"], profile="canonical_rules_v1")
    original = arguments["trusted_proposal_inputs"]
    checked = adapter._inputs(original, arguments["expected_inputs_sha256"])
    assert checked == contracts.clone_json(original)
    assert canonical_dag_json_bytes(checked) == canonical_dag_json_bytes(original)
    assert cid_for_dag_json(checked) == record["input_binding"]["inputs_cid"]
    assert record["ast_record"]["schema"] == adapter.AST_SCHEMA
    assert "ast_json" not in record["ast_record"] and record["ast_record"]["ast"] == case["ast"]
    assert record["proposal_record"]["proposal_graph_id"] == graph["graph_id"]
    assert adapter.restore_proposed_graph_ast(record, **arguments) == case["ast"]

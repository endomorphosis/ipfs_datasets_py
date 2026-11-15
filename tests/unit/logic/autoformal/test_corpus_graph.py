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


def component_inputs_v2(snapshots, *, identities=None, states=None):
    """Authored local bytes and independent fixture pins, never review approval."""
    import hashlib
    identities = identities or ["component-" + str(index) for index in range(len(snapshots))]
    states = states or ["pending"] * len(snapshots)
    inputs, pins = [], []
    for identity, snapshot, state in zip(identities, snapshots, states, strict=True):
        review = {"schema": "fictional-complete-review-input/v1", "state": state,
            "claims": [{"status": state, "substantive_review_supplied": False}], "unresolved": ["meaning"]}
        snapshot_raw = contracts.canonical_dag_json_bytes(snapshot)
        review_raw = contracts.canonical_dag_json_bytes(review)
        inputs.append(dict(component_id=identity, snapshot_raw=snapshot_raw, review_raw=review_raw))
        pins.append(dict(component_id=identity, snapshot_cid=snapshot["record_cid"],
            snapshot_sha256=hashlib.sha256(snapshot_raw).hexdigest(),
            review_sha256=hashlib.sha256(review_raw).hexdigest()))
    return inputs, pins


def component_case_v2():
    rule, first, second = node("norm_assertion", "rule"), node("definition_assertion", "first"), node("definition_assertion", "second")
    sense_one, sense_two = node("term_sense", "sense-one"), node("term_sense", "sense-two")
    snapshots = [g.build_graph_snapshot([rule], []),
        g.build_graph_snapshot([first, sense_one], [edge(first, sense_one, "DEFINES")]),
        g.build_graph_snapshot([second, sense_two], [edge(second, sense_two, "DEFINES")])]
    inputs, pins = component_inputs_v2(snapshots, states=["pending", "revoked", "unreviewed"])
    def endpoint(index, value):
        return dict(component_id=pins[index]["component_id"], snapshot_cid=pins[index]["snapshot_cid"],
                    node_cid=value["record_cid"])
    imports = [g.build_component_import_v2(src=endpoint(a, src), dst=endpoint(b, dst),
        edge=edge(src, dst, "USES_DEFINITION")) for a, src, b, dst in
        [(0, rule, 1, first), (0, rule, 2, second), (1, first, 2, second)]]
    graph = g.build_component_graph_v2(inputs, imports, expected_components=pins,
        expected_import_cids=[row["record_cid"] for row in imports])
    return dict(inputs=inputs, pins=pins, imports=imports, graph=graph, snapshots=snapshots,
                nodes=[rule, first, second], endpoint=endpoint)


def test_component_v2_imports_complete_pinned_snapshots_without_flattening_or_review_promotion():
    case = component_case_v2()
    graph = case["graph"]
    assert [row["snapshot"] for row in graph["components"]] == case["snapshots"]
    assert graph["imports"] == case["imports"] and graph["node_count"] == 5 and graph["edge_count"] == 5
    assert [row["review_inputs"]["state"] for row in graph["components"]] == ["pending", "revoked", "unreviewed"]
    assert all(graph[key] is False for key in ("admitted", "formalized", "source_semantics_verified",
        "review_authority", "imported_equivalence_asserted", "proof_authority", "lean_authority",
        "legal_interpretation_accepted"))
    assert graph["disposition"] == "complete_candidate_imports_semantics_unresolved"
    checked = g.validate_component_graph_v2(graph, expected_record_cid=graph["record_cid"], expected_components=case["pins"])
    assert checked == graph
    found = g.resolve_component_node_v2(graph, **case["endpoint"](1, case["nodes"][1]),
        expected_record_cid=graph["record_cid"], expected_components=case["pins"])
    assert found == case["nodes"][1]
    found["stable_id"] = "caller mutation"
    assert graph["components"][1]["snapshot"] == case["snapshots"][1]


def test_component_v2_homonyms_and_local_alternative_names_remain_distinct():
    first = node("norm_assertion", "Secretary", scope_cid=cid("edition-one"),
        alternative_group_id="local-reading", alternative_id="A")
    second = node("definition_assertion", "Secretary", scope_cid=cid("edition-two"),
        alternative_group_id="local-reading", alternative_id="B")
    second = seal_record({**{k: v for k, v in second.items() if k not in {"record_cid", "cid_scope"}},
        "content_cid": cid("independent edition-two definition meaning")})
    snapshots = [g.build_graph_snapshot([first], []), g.build_graph_snapshot([second], [])]
    inputs, pins = component_inputs_v2(snapshots)
    imported = g.build_component_import_v2(src=dict(component_id=pins[0]["component_id"],
        snapshot_cid=pins[0]["snapshot_cid"], node_cid=first["record_cid"]),
        dst=dict(component_id=pins[1]["component_id"], snapshot_cid=pins[1]["snapshot_cid"], node_cid=second["record_cid"]),
        edge=edge(first, second, "USES_DEFINITION"))
    graph = g.build_component_graph_v2(inputs, [imported], expected_components=pins,
        expected_import_cids=[imported["record_cid"]])
    assert graph["components"][0]["snapshot"]["nodes"] == [first]
    assert graph["components"][1]["snapshot"]["nodes"] == [second]
    assert graph["source_semantics_verified"] is False


def test_component_v2_distinct_component_identity_does_not_equate_even_unscoped_stable_names():
    first = node("term_sense", "homonym")
    second = seal_record({**{k: v for k, v in first.items() if k not in {"record_cid", "cid_scope"}},
        "content_cid": cid("another component's genuinely different meaning")})
    snapshots = [g.build_graph_snapshot([first], []), g.build_graph_snapshot([second], [])]
    inputs, pins = component_inputs_v2(snapshots)
    graph = g.build_component_graph_v2(inputs, [], expected_components=pins, expected_import_cids=[])
    assert graph["node_count"] == 2
    assert [row["snapshot"]["nodes"][0] for row in graph["components"]] == [first, second]
    assert graph["imported_equivalence_asserted"] is False


def test_component_v2_identical_node_CID_in_independent_components_has_independent_role_positions():
    rule, actor = node("norm_assertion", "same exact rule"), node("entity", "actor")
    snapshots = [g.build_graph_snapshot([rule], []), g.build_graph_snapshot([rule], []),
                 g.build_graph_snapshot([actor], [])]
    inputs, pins = component_inputs_v2(snapshots)
    imports = [g.build_component_import_v2(src=dict(component_id=pins[i]["component_id"],
        snapshot_cid=pins[i]["snapshot_cid"], node_cid=rule["record_cid"]),
        dst=dict(component_id=pins[2]["component_id"], snapshot_cid=pins[2]["snapshot_cid"], node_cid=actor["record_cid"]),
        edge=edge(rule, actor, ordinal=0)) for i in [0, 1]]
    graph = g.build_component_graph_v2(inputs, imports, expected_components=pins,
        expected_import_cids=[row["record_cid"] for row in imports])
    assert graph["node_count"] == 3 and len(graph["imports"]) == 2
    assert graph["components"][0]["snapshot"] == graph["components"][1]["snapshot"]


@pytest.mark.parametrize("damage", ["order", "omit", "duplicate", "snapshot_pin", "review_pin", "snapshot_cid"])
def test_component_v2_independent_component_population_and_pins_refuse_reassignment(damage):
    case = component_case_v2()
    inputs, pins = copy.deepcopy(case["inputs"]), copy.deepcopy(case["pins"])
    if damage == "order": inputs.reverse()
    elif damage == "omit": inputs.pop()
    elif damage == "duplicate": inputs[1] = inputs[0]
    elif damage == "snapshot_pin": pins[0]["snapshot_sha256"] = "0" * 64
    elif damage == "review_pin": pins[0]["review_sha256"] = "0" * 64
    else: pins[0]["snapshot_cid"] = pins[1]["snapshot_cid"]
    with pytest.raises(CorpusContractError):
        g.build_component_graph_v2(inputs, case["imports"], expected_components=pins,
            expected_import_cids=[row["record_cid"] for row in case["imports"]])


@pytest.mark.parametrize("damage", ["component", "snapshot", "node", "edge_node", "local"])
def test_component_v2_missing_foreign_or_reassigned_endpoints_are_not_imported(damage):
    case = component_case_v2()
    imported = copy.deepcopy(case["imports"][0])
    if damage == "component": imported["dst"]["component_id"] = "foreign"
    elif damage == "snapshot": imported["dst"]["snapshot_cid"] = case["pins"][2]["snapshot_cid"]
    elif damage == "node":
        imported["dst"]["node_cid"] = cid("foreign-node")
        imported["edge"] = g.build_edge(src_cid=imported["src"]["node_cid"],
            dst_cid=imported["dst"]["node_cid"], relation="USES_DEFINITION", evidence_cids=[cid("binding")])
    elif damage == "edge_node": imported["src"]["node_cid"] = cid("reassigned")
    else: imported["dst"]["component_id"] = imported["src"]["component_id"]
    value = seal_record({key: value for key, value in imported.items() if key not in {"cid_scope", "record_cid"}})
    with pytest.raises(CorpusContractError):
        g.build_component_graph_v2(case["inputs"], [value], expected_components=case["pins"],
            expected_import_cids=[value["record_cid"]])


@pytest.mark.parametrize("relation", ["DEFINES", "DENOTES", "HAS_CONDITION", "APPLIES_WITHIN"])
def test_component_v2_reuses_strict_V1_relation_endpoint_types(relation):
    case = component_case_v2()
    imported = g.build_component_import_v2(src=case["endpoint"](0, case["nodes"][0]),
        dst=case["endpoint"](1, case["nodes"][1]), edge=edge(case["nodes"][0], case["nodes"][1], relation,
        ordinal=0 if relation in g.ROLES else None))
    with pytest.raises(CorpusContractError):
        g.build_component_graph_v2(case["inputs"], [imported], expected_components=case["pins"],
            expected_import_cids=[imported["record_cid"]])


def test_component_v2_same_qualified_role_position_cannot_be_reassigned_across_imports():
    rule, actor, other = node("norm_assertion", "rule"), node("entity", "actor"), node("entity", "other")
    inputs, pins = component_inputs_v2([g.build_graph_snapshot([rule], []),
        g.build_graph_snapshot([actor, other], [])])
    imports = [g.build_component_import_v2(src=dict(component_id=pins[0]["component_id"],
        snapshot_cid=pins[0]["snapshot_cid"], node_cid=rule["record_cid"]),
        dst=dict(component_id=pins[1]["component_id"], snapshot_cid=pins[1]["snapshot_cid"], node_cid=dst["record_cid"]),
        edge=edge(rule, dst, ordinal=0)) for dst in [actor, other]]
    with pytest.raises(CorpusContractError, match="role argument position"):
        g.build_component_graph_v2(inputs, imports, expected_components=pins,
            expected_import_cids=[row["record_cid"] for row in imports])


def test_component_v2_import_cannot_reassign_an_existing_local_qualified_role_position():
    rule, actor, other = node("norm_assertion", "rule"), node("entity", "local actor"), node("entity", "imported actor")
    snapshots = [g.build_graph_snapshot([rule, actor], [edge(rule, actor, ordinal=0)]),
                 g.build_graph_snapshot([other], [])]
    inputs, pins = component_inputs_v2(snapshots)
    imported = g.build_component_import_v2(src=dict(component_id=pins[0]["component_id"],
        snapshot_cid=pins[0]["snapshot_cid"], node_cid=rule["record_cid"]),
        dst=dict(component_id=pins[1]["component_id"], snapshot_cid=pins[1]["snapshot_cid"], node_cid=other["record_cid"]),
        edge=edge(rule, other, ordinal=0))
    with pytest.raises(CorpusContractError, match="role argument position"):
        g.build_component_graph_v2(inputs, [imported], expected_components=pins,
            expected_import_cids=[imported["record_cid"]])


def test_component_v2_distinct_imported_role_ordinals_and_evidence_are_preserved():
    rule, actor = node("norm_assertion", "rule"), node("entity", "actor")
    inputs, pins = component_inputs_v2([g.build_graph_snapshot([rule], []), g.build_graph_snapshot([actor], [])])
    imports = [g.build_component_import_v2(src=dict(component_id=pins[0]["component_id"],
        snapshot_cid=pins[0]["snapshot_cid"], node_cid=rule["record_cid"]),
        dst=dict(component_id=pins[1]["component_id"], snapshot_cid=pins[1]["snapshot_cid"], node_cid=actor["record_cid"]),
        edge=g.build_edge(src_cid=rule["record_cid"], dst_cid=actor["record_cid"], relation="HAS_ACTOR",
            ordinal=ordinal, evidence_cids=[cid("role-proof-" + str(ordinal))])) for ordinal in [0, 1]]
    graph = g.build_component_graph_v2(inputs, imports, expected_components=pins,
        expected_import_cids=[row["record_cid"] for row in imports])
    assert graph["imports"] == imports
    assert [row["edge"]["ordinal"] for row in graph["imports"]] == [0, 1]


def test_component_v2_old_component_pin_refuses_self_resealed_content_meaning_change():
    case = component_case_v2()
    original = case["nodes"][0]
    changed = seal_record({**{k: v for k, v in original.items() if k not in {"record_cid", "cid_scope"}},
        "content_cid": cid("different meaning")})
    snapshot = g.build_graph_snapshot([changed], [])
    inputs = copy.deepcopy(case["inputs"])
    inputs[0]["snapshot_raw"] = contracts.canonical_dag_json_bytes(snapshot)
    with pytest.raises(CorpusContractError, match="SHA256"):
        g.build_component_graph_v2(inputs, [], expected_components=case["pins"], expected_import_cids=[])


@pytest.mark.parametrize("damage", ["duplicate", "reorder", "noncid"])
def test_component_v2_import_identity_order_and_multiplicity_are_independently_bound(damage):
    case = component_case_v2()
    imports = copy.deepcopy(case["imports"])
    pins = [row["record_cid"] for row in imports]
    if damage == "duplicate": imports[1] = imports[0]; pins[1] = pins[0]
    elif damage == "reorder": imports.reverse()
    else: pins[0] = {"not": "a CID"}
    with pytest.raises(CorpusContractError):
        g.build_component_graph_v2(case["inputs"], imports, expected_components=case["pins"], expected_import_cids=pins)


@pytest.mark.parametrize("damage", ["review", "authority", "drop_component", "import_order", "counts"])
def test_component_v2_resealed_outer_record_never_replaces_independent_original(damage):
    case = component_case_v2()
    body = {k: copy.deepcopy(v) for k, v in case["graph"].items() if k not in {"record_cid", "cid_scope"}}
    if damage == "review": body["components"][0]["review_inputs"]["state"] = "accepted"
    elif damage == "authority": body["admitted"] = True
    elif damage == "drop_component": body["components"].pop()
    elif damage == "import_order": body["imports"].reverse()
    else: body["node_count"] -= 1
    with pytest.raises(CorpusContractError, match="independently retained"):
        g.validate_component_graph_v2(seal_record(body), expected_record_cid=case["graph"]["record_cid"],
            expected_components=case["pins"])


@pytest.mark.parametrize("bound", ["nodes", "edges", "bytes"])
def test_component_v2_aggregate_limits_refuse_without_truncation(bound, monkeypatch):
    case = component_case_v2()
    if bound == "nodes": monkeypatch.setattr(g, "MAX_NODES", 4)
    elif bound == "edges": monkeypatch.setattr(g, "MAX_EDGES", 4)
    else: monkeypatch.setattr(contracts, "MAX_RECORD_BYTES", 128)
    with pytest.raises(CorpusContractError):
        g.build_component_graph_v2(case["inputs"], case["imports"], expected_components=case["pins"],
            expected_import_cids=[row["record_cid"] for row in case["imports"]])

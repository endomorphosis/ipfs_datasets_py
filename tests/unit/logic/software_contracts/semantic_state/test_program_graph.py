"""Contract vectors for static program-graph records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_identity import (
    CanonicalProgramGraphIdentity,
    ProgramGraphDeltaIdentity,
    ProgramGraphSnapshotIdentity,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_graph import (
    CALLSITE_RECORD_INTERFACE,
    CONTRACT_STATE_RECORD_INTERFACE,
    DYNAMIC_FRONTIER_RECORD_INTERFACE,
    FUNCTION_SYMBOL_RECORD_INTERFACE,
    LOGICAL_CYCLE_REQUIRED_KINDS,
    PROGRAM_GRAPH_DELTA_INTERFACE,
    PROGRAM_GRAPH_DELTA_SCHEMA,
    PROGRAM_GRAPH_EDGE_INTERFACE,
    PROGRAM_GRAPH_EDGE_SCHEMA,
    PROGRAM_GRAPH_INDEX_MANIFEST_INTERFACE,
    PROGRAM_GRAPH_NODE_INTERFACE,
    PROGRAM_GRAPH_NODE_SCHEMA,
    PROGRAM_GRAPH_SNAPSHOT_INTERFACE,
    PROGRAM_GRAPH_SNAPSHOT_SCHEMA,
    PROOF_OBLIGATION_GRAPH_INTERFACE,
    REQUIRED_EDGE_KINDS,
    REQUIRED_NODE_KINDS,
    STATIC_SUCCESSOR_SET_INTERFACE,
    CallsiteRecord,
    ContractKind,
    ContractStateRecord,
    DynamicFrontierRecord,
    FunctionSymbolRecord,
    ProgramGraphDelta,
    ProgramGraphEdge,
    ProgramGraphEdgeKind,
    ProgramGraphError,
    ProgramGraphIndexKind,
    ProgramGraphIndexManifest,
    ProgramGraphKind,
    ProgramGraphNode,
    ProgramGraphNodeKind,
    ProgramGraphSnapshot,
    ProgramLanguage,
    ProofObligationGraph,
    ResolutionStatus,
    StaticSuccessorSet,
    apply_program_graph_delta,
    assemble_program_graph_snapshot,
    assert_physical_dag_acyclic,
    bind_index_manifest,
    canonical_program_graph_bytes,
    canonicalize_program_graph_value,
    decode_program_graph_record,
    delta_between_snapshots,
    directed_logical_cycles,
    load_payload_schema,
    loads_program_graph_json,
    program_graph_cid_for,
    verify_program_graph_catalog,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "program-graph.payload.schema.json"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _source() -> str:
    return cid_for_bytes(b"def ping():\n    return pong()\n")


def _node(kind: str, name: str, **overrides: Any) -> ProgramGraphNode:
    fields: dict[str, Any] = {
        "node_kind": kind,
        "language": "python",
        "logical_name": name,
        "source_cid": _source(),
        "declaration_cid": _cid(f"decl:{name}"),
        "environment_binding_cid": _cid("env-v1"),
        "subject_cid": None,
        "record_cid": None,
        "unavailable_dimensions": (),
        "metadata": {},
    }
    fields.update(overrides)
    return ProgramGraphNode(**fields)


def _edge(
    kind: str,
    source: ProgramGraphNode,
    target: ProgramGraphNode,
    **overrides: Any,
) -> ProgramGraphEdge:
    fields: dict[str, Any] = {
        "edge_kind": kind,
        "source_node_cid": source.program_graph_node_cid,
        "target_node_cid": target.program_graph_node_cid,
        "language": "python",
        "environment_binding_cid": _cid("env-v1"),
        "resolution_status": ResolutionStatus.DEFINITE,
        "logical_cycle": kind in LOGICAL_CYCLE_REQUIRED_KINDS,
        "unavailable_dimensions": (),
        "metadata": {},
    }
    fields.update(overrides)
    return ProgramGraphEdge(**fields)


def _function(name: str, **overrides: Any) -> FunctionSymbolRecord:
    fields: dict[str, Any] = {
        "language": "python",
        "logical_name": name,
        "source_cid": _source(),
        "declaration_cid": _cid(f"decl:{name}"),
        "parameter_names": ("self",),
        "return_annotation": "None",
        "unavailable_dimensions": (),
    }
    fields.update(overrides)
    return FunctionSymbolRecord(**fields)


def _callsite(caller: str, callee: str, ordinal: int = 0, **overrides: Any) -> CallsiteRecord:
    fields: dict[str, Any] = {
        "language": "python",
        "caller_logical_name": caller,
        "callee_logical_name": callee,
        "source_cid": _source(),
        "ordinal": ordinal,
        "resolution_status": ResolutionStatus.DEFINITE,
        "callee_declaration_cid": _cid(f"decl:{callee}"),
        "unavailable_dimensions": (),
    }
    fields.update(overrides)
    return CallsiteRecord(**fields)


def _contract(name: str, **overrides: Any) -> ContractStateRecord:
    fields: dict[str, Any] = {
        "language": "python",
        "subject_logical_name": name,
        "contract_kind": ContractKind.PRECONDITION,
        "specification_cid": _cid(f"spec:{name}"),
        "discharge_status": "unknown",
        "unavailable_dimensions": (),
    }
    fields.update(overrides)
    return ContractStateRecord(**fields)


def _assemble(
    nodes: list[ProgramGraphNode],
    edges: list[ProgramGraphEdge],
    **overrides: Any,
) -> ProgramGraphSnapshot:
    fields: dict[str, Any] = {
        "nodes": nodes,
        "edges": edges,
        "environment_binding_set_cid": _cid("bindings"),
        "sealed_binding_cid": _cid("sealed"),
    }
    fields.update(overrides)
    return assemble_program_graph_snapshot(**fields)


def _sample_graph() -> dict[str, Any]:
    ping_fn = _function("pkg.mod.ping", parameter_names=())
    pong_fn = _function("pkg.mod.pong", parameter_names=())
    ping_call = _callsite("pkg.mod.ping", "pkg.mod.pong", 0)
    pong_call = _callsite("pkg.mod.pong", "pkg.mod.ping", 0)
    module = _node("module", "pkg.mod")
    ping = _node("function", "pkg.mod.ping", record_cid=ping_fn.function_symbol_record_cid)
    pong = _node("function", "pkg.mod.pong", record_cid=pong_fn.function_symbol_record_cid)
    ping_site = _node("callsite", "pkg.mod.ping#0", record_cid=ping_call.callsite_record_cid)
    pong_site = _node("callsite", "pkg.mod.pong#0", record_cid=pong_call.callsite_record_cid)
    obligation = _node("proof_obligation", "pkg.mod.ping.post")
    contract = _contract("pkg.mod.ping")
    contract_node = _node(
        "contract_state",
        "pkg.mod.ping.pre",
        record_cid=contract.contract_state_record_cid,
    )
    dynamic = _node("unresolved_dynamic", "pkg.mod.ping.__getattr__")
    edges = [
        _edge("declares", module, ping),
        _edge("declares", module, pong),
        _edge("calls", ping, ping_site),
        _edge("calls", pong, pong_site),
        _edge("mutual_recursion", ping, pong, logical_cycle=True),
        _edge("mutual_recursion", pong, ping, logical_cycle=True),
        _edge("binds_contract", ping, contract_node),
        _edge("proved_by", ping, obligation),
        _edge(
            "unresolved_dynamic",
            ping,
            dynamic,
            resolution_status="unresolved",
            unavailable_dimensions=("reflection",),
        ),
    ]
    pog = ProofObligationGraph(
        language="python",
        root_obligation_cid=obligation.program_graph_node_cid,
        obligation_node_cids=[obligation.program_graph_node_cid],
        obligation_edge_cids=[],
    )
    successors = StaticSuccessorSet(
        language="python",
        subject_node_cid=ping.program_graph_node_cid,
        successor_node_cids=[
            ping_site.program_graph_node_cid,
            dynamic.program_graph_node_cid,
        ],
        successor_edge_cids=[
            edges[2].program_graph_edge_cid,
            edges[-1].program_graph_edge_cid,
        ],
        complete=False,
        unavailable_dimensions=("reflection",),
    )
    frontier = DynamicFrontierRecord(
        language="python",
        unresolved_node_cids=[dynamic.program_graph_node_cid],
        unresolved_edge_cids=[edges[-1].program_graph_edge_cid],
        reasons=["reflection", "unknown_callee"],
        unavailable_dimensions=("reflection",),
    )
    snapshot = _assemble(
        [module, ping, pong, ping_site, pong_site, obligation, contract_node, dynamic],
        edges,
        callsites=[ping_call, pong_call],
        function_symbols=[ping_fn, pong_fn],
        contract_states=[contract],
        proof_obligation_graphs=[pog],
        successor_sets=[successors],
        frontiers=[frontier],
        retained_subroot_cids=[module.program_graph_node_cid],
        unavailable_dimensions=["reflection"],
    )
    return {
        "module": module,
        "ping": ping,
        "pong": pong,
        "ping_site": ping_site,
        "pong_site": pong_site,
        "obligation": obligation,
        "contract_node": contract_node,
        "edges": edges,
        "snapshot": snapshot,
        "ping_fn": ping_fn,
        "pong_fn": pong_fn,
        "ping_call": ping_call,
        "pong_call": pong_call,
        "contract": contract,
        "pog": pog,
        "successors": successors,
        "frontier": frontier,
        "dynamic": dynamic,
    }


def _sample_payloads() -> list[dict[str, Any]]:
    graph = _sample_graph()
    snapshot = graph["snapshot"]
    next_node = _node("test", "pkg.mod.test_ping")
    current = _assemble(
        [
            graph["module"],
            graph["ping"],
            graph["pong"],
            graph["ping_site"],
            graph["pong_site"],
            graph["obligation"],
            graph["contract_node"],
            graph["dynamic"],
            next_node,
        ],
        graph["edges"] + [_edge("tested_by", graph["ping"], next_node)],
        callsites=[graph["ping_call"], graph["pong_call"]],
        function_symbols=[graph["ping_fn"], graph["pong_fn"]],
        contract_states=[graph["contract"]],
        proof_obligation_graphs=[graph["pog"]],
        successor_sets=[graph["successors"]],
        frontiers=[graph["frontier"]],
        retained_subroot_cids=[
            graph["module"].program_graph_node_cid,
            graph["ping"].program_graph_node_cid,
            graph["pong"].program_graph_node_cid,
        ],
        unavailable_dimensions=["reflection"],
    )
    delta = delta_between_snapshots(snapshot, current)
    manifest = ProgramGraphIndexManifest(
        snapshot_cid=snapshot.program_graph_snapshot_cid,
        index_kind=ProgramGraphIndexKind.ADJACENCY,
        schema_ids=[PROGRAM_GRAPH_SNAPSHOT_SCHEMA],
    )
    return [
        graph["ping"].to_dict(),
        graph["edges"][4].to_dict(),
        graph["ping_call"].to_dict(),
        graph["ping_fn"].to_dict(),
        graph["contract"].to_dict(),
        graph["pog"].to_dict(),
        graph["successors"].to_dict(),
        graph["frontier"].to_dict(),
        manifest.to_dict(),
        snapshot.to_dict(),
        delta.to_dict(),
    ]


def test_public_interfaces_are_versioned() -> None:
    assert PROGRAM_GRAPH_NODE_INTERFACE == "ProgramGraphNode@1"
    assert PROGRAM_GRAPH_EDGE_INTERFACE == "ProgramGraphEdge@1"
    assert PROGRAM_GRAPH_SNAPSHOT_INTERFACE == "ProgramGraphSnapshot@1"
    assert PROGRAM_GRAPH_DELTA_INTERFACE == "ProgramGraphDelta@1"
    assert PROGRAM_GRAPH_INDEX_MANIFEST_INTERFACE == "ProgramGraphIndexManifest@1"
    assert CALLSITE_RECORD_INTERFACE == "CallsiteRecord@1"
    assert FUNCTION_SYMBOL_RECORD_INTERFACE == "FunctionSymbolRecord@1"
    assert CONTRACT_STATE_RECORD_INTERFACE == "ContractStateRecord@1"
    assert PROOF_OBLIGATION_GRAPH_INTERFACE == "ProofObligationGraph@1"
    assert STATIC_SUCCESSOR_SET_INTERFACE == "StaticSuccessorSet@1"
    assert DYNAMIC_FRONTIER_RECORD_INTERFACE == "DynamicFrontierRecord@1"
    assert ProgramGraphNode.INTERFACE == PROGRAM_GRAPH_NODE_INTERFACE
    assert ProgramGraphEdge.SCHEMA == PROGRAM_GRAPH_EDGE_SCHEMA
    assert ProgramGraphSnapshot.SCHEMA == PROGRAM_GRAPH_SNAPSHOT_SCHEMA
    assert ProgramGraphDelta.SCHEMA == PROGRAM_GRAPH_DELTA_SCHEMA
    assert ProgramGraphKind.STATIC_LOGICAL.value == "static_logical"


def test_closed_enums_cover_required_node_and_edge_classes() -> None:
    node_kinds = {item.value for item in ProgramGraphNodeKind}
    edge_kinds = {item.value for item in ProgramGraphEdgeKind}
    assert node_kinds == REQUIRED_NODE_KINDS
    assert edge_kinds == REQUIRED_EDGE_KINDS
    for required in (
        "ast",
        "symbol",
        "function",
        "callsite",
        "import_binding",
        "cfg_block",
        "data_flow",
        "exception_handler",
        "type_binding",
        "effect",
        "contract_state",
        "test",
        "proof_obligation",
        "unresolved_dynamic",
    ):
        assert required in node_kinds
    for required in (
        "contains",
        "imports",
        "cyclic_import",
        "calls",
        "mutual_recursion",
        "cfg_next",
        "data_flow",
        "exception_edge",
        "type_of",
        "effect_of",
        "binds_contract",
        "tested_by",
        "proved_by",
        "successor",
        "unresolved_dynamic",
    ):
        assert required in edge_kinds
    assert "hnsw" not in node_kinds
    assert "similarity" not in edge_kinds
    assert LOGICAL_CYCLE_REQUIRED_KINDS <= edge_kinds


def test_canonical_identity_vectors_are_stable_and_rehash() -> None:
    node = _node("function", "pkg.mod.ping")
    expected = {
        "schema": PROGRAM_GRAPH_NODE_SCHEMA,
        "node_kind": "function",
        "language": "python",
        "logical_name": "pkg.mod.ping",
        "source_cid": _source(),
        "declaration_cid": _cid("decl:pkg.mod.ping"),
        "environment_binding_cid": _cid("env-v1"),
        "subject_cid": None,
        "record_cid": None,
        "unavailable_dimensions": [],
        "metadata": {},
    }
    assert node.identity_payload() == expected
    assert node.program_graph_node_cid == cid_for_structured(expected)
    assert node.canonical_bytes() == canonical_dag_json_bytes(expected)
    assert node.program_graph_node_cid == program_graph_cid_for(expected)
    shuffled = _node("function", "pkg.mod.ping", unavailable_dimensions=("b", "a"))
    same = _node("function", "pkg.mod.ping", unavailable_dimensions=("a", "b"))
    assert shuffled.program_graph_node_cid == same.program_graph_node_cid
    assert list(shuffled.unavailable_dimensions) == ["a", "b"]


def test_records_round_trip_and_rehash() -> None:
    for payload in _sample_payloads():
        record = decode_program_graph_record(payload)
        assert record.to_dict() == payload
        claimed = payload[record.CID_FIELD]
        assert decode_and_recompute_structured(claimed, record.identity_payload()) == claimed
        again = json.loads(json.dumps(payload, sort_keys=True))
        assert decode_program_graph_record(again).to_dict() == payload


def test_unknown_fields_versions_and_forged_cids_fail_closed() -> None:
    payload = _node("module", "pkg.mod").to_dict()
    with pytest.raises(ProgramGraphError, match="unknown fields"):
        ProgramGraphNode.from_dict({**payload, "hnsw": True})
    with pytest.raises(ProgramGraphError, match="unknown fields"):
        ProgramGraphNode.from_dict({**payload, "embedding": [0, 1]})
    with pytest.raises(ProgramGraphError, match="schema version"):
        ProgramGraphNode.from_dict(
            {**payload, "schema": PROGRAM_GRAPH_NODE_SCHEMA.replace("@1", "@99")}
        )
    forged = dict(payload)
    forged["program_graph_node_cid"] = _cid("forged")
    with pytest.raises(ProgramGraphError, match="does not verify"):
        ProgramGraphNode.from_dict(forged)
    with pytest.raises(ProgramGraphError, match="unsupported program-graph schema"):
        decode_program_graph_record({"schema": "not-a-payload", "x": 1})


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected() -> None:
    with pytest.raises(ProgramGraphError, match="duplicate JSON key"):
        loads_program_graph_json('{"a":1,"a":2}')
    with pytest.raises(ProgramGraphError, match="nonfinite"):
        loads_program_graph_json("NaN")
    with pytest.raises(ProgramGraphError, match="nonfinite"):
        loads_program_graph_json("Infinity")
    with pytest.raises(ProgramGraphError, match="floats are rejected"):
        loads_program_graph_json('{"score":1.5}')
    with pytest.raises(ProgramGraphError, match="strict DAG-JSON"):
        canonicalize_program_graph_value({"x": 1.5})


def test_unsupported_language_and_ann_kinds_fail_closed() -> None:
    with pytest.raises(ProgramGraphError, match="typed unavailable"):
        _node("module", "pkg.mod", language="javascript")
    with pytest.raises(ProgramGraphError, match="typed unavailable"):
        _node("module", "pkg.mod", language="rust")
    with pytest.raises(ProgramGraphError, match="not ANN"):
        ProgramGraphSnapshot(
            language="python",
            graph_kind="hnsw",
            canonical_program_graph_cid=_cid("graph"),
            node_cids=[],
            edge_cids=[],
            environment_binding_set_cid=_cid("bindings"),
            sealed_binding_cid=_cid("sealed"),
        )
    with pytest.raises(ProgramGraphError, match="not a canonical program graph"):
        ProgramGraphIndexManifest(
            snapshot_cid=_cid("snap"),
            index_kind="hnsw",
            schema_ids=["program-graph@1"],
        )
    with pytest.raises(ProgramGraphError, match="static program-graph class"):
        _node("knn", "pkg.mod.similar")
    with pytest.raises(ProgramGraphError, match="static program-graph class"):
        left = _node("module", "a")
        right = _node("module", "b")
        _edge("similarity", left, right)


def test_mutual_recursion_and_cyclic_imports_use_immutable_records() -> None:
    ping = _node("function", "pkg.mod.ping")
    pong = _node("function", "pkg.mod.pong")
    ping_cid = ping.program_graph_node_cid
    left = _edge("mutual_recursion", ping, pong, logical_cycle=True)
    right = _edge("mutual_recursion", pong, ping, logical_cycle=True)
    assert ping.program_graph_node_cid == ping_cid
    snapshot = _assemble([ping, pong], [left, right])
    cycles = directed_logical_cycles([left, right])
    assert cycles
    assert left.program_graph_edge_cid in cycles[0]
    assert right.program_graph_edge_cid in cycles[0]
    assert left.logical_cycle is True
    assert right.logical_cycle is True
    catalog = {
        ping.program_graph_node_cid: ping.identity_payload(),
        pong.program_graph_node_cid: pong.identity_payload(),
        left.program_graph_edge_cid: left.identity_payload(),
        right.program_graph_edge_cid: right.identity_payload(),
        snapshot.program_graph_snapshot_cid: snapshot.identity_payload(),
    }
    assert_physical_dag_acyclic(catalog)
    with pytest.raises(ProgramGraphError, match="logical-cycle records"):
        _edge("mutual_recursion", ping, pong, logical_cycle=False)

    mod_a = _node("module", "pkg.a")
    mod_b = _node("module", "pkg.b")
    imports_ab = _edge("cyclic_import", mod_a, mod_b, logical_cycle=True)
    imports_ba = _edge("cyclic_import", mod_b, mod_a, logical_cycle=True)
    cyclic = _assemble([mod_a, mod_b], [imports_ab, imports_ba])
    assert cyclic.program_graph_snapshot_cid
    assert directed_logical_cycles([imports_ab, imports_ba])


def test_cfg_loop_is_a_logical_cycle_on_an_acyclic_physical_dag() -> None:
    entry = _node("cfg_block", "pkg.mod.loop.entry")
    body = _node("cfg_block", "pkg.mod.loop.body")
    forward = _edge("cfg_next", entry, body)
    back = _edge("cfg_next", body, entry, logical_cycle=True)
    snapshot = _assemble([entry, body], [forward, back])
    cycles = directed_logical_cycles([forward, back])
    assert any(back.program_graph_edge_cid in cycle for cycle in cycles)
    with pytest.raises(ProgramGraphError, match="logical-cycle records"):
        _assemble(
            [entry, body],
            [_edge("cfg_next", entry, body), _edge("cfg_next", body, entry)],
        )
    catalog = {
        entry.program_graph_node_cid: entry.identity_payload(),
        body.program_graph_node_cid: body.identity_payload(),
        forward.program_graph_edge_cid: forward.identity_payload(),
        back.program_graph_edge_cid: back.identity_payload(),
        snapshot.program_graph_snapshot_cid: snapshot.identity_payload(),
    }
    assert_physical_dag_acyclic(catalog)


def test_unknown_dynamic_behavior_stays_explicit_on_the_frontier() -> None:
    caller = _node("function", "pkg.mod.caller")
    hole = _node("unresolved_dynamic", "pkg.mod.caller.getattr")
    edge = _edge(
        "unresolved_dynamic",
        caller,
        hole,
        resolution_status="unresolved",
        unavailable_dimensions=("reflection",),
    )
    with pytest.raises(ProgramGraphError, match="stay explicit"):
        _assemble([caller, hole], [edge])
    frontier = DynamicFrontierRecord(
        language="python",
        unresolved_node_cids=[hole.program_graph_node_cid],
        unresolved_edge_cids=[edge.program_graph_edge_cid],
        reasons=["reflection"],
        unavailable_dimensions=("reflection",),
    )
    snapshot = _assemble([caller, hole], [edge], frontiers=[frontier])
    assert snapshot.frontier_cids == (frontier.dynamic_frontier_record_cid,)
    with pytest.raises(ProgramGraphError, match="cannot be empty"):
        DynamicFrontierRecord(language="python")
    with pytest.raises(ProgramGraphError, match="cannot be marked definite"):
        _edge("unresolved_dynamic", caller, hole, resolution_status="definite")
    incomplete = StaticSuccessorSet(
        language="python",
        subject_node_cid=caller.program_graph_node_cid,
        successor_node_cids=[hole.program_graph_node_cid],
        complete=False,
        unavailable_dimensions=("reflection",),
    )
    with pytest.raises(ProgramGraphError, match="stay explicit"):
        _assemble([caller, hole], [edge], successor_sets=[incomplete])
    with pytest.raises(ProgramGraphError, match="require unavailable_dimensions"):
        StaticSuccessorSet(
            language="python",
            subject_node_cid=caller.program_graph_node_cid,
            complete=False,
        )


def test_unchanged_subroots_are_preserved_across_deterministic_deltas() -> None:
    graph = _sample_graph()
    previous = graph["snapshot"]
    extra = _node("test", "pkg.mod.test_ping")
    current_nodes = [
        graph["module"],
        graph["ping"],
        graph["pong"],
        graph["ping_site"],
        graph["pong_site"],
        graph["obligation"],
        graph["contract_node"],
        graph["dynamic"],
        extra,
    ]
    current_edges = graph["edges"] + [_edge("tested_by", graph["ping"], extra)]
    current = _assemble(
        current_nodes,
        current_edges,
        callsites=[graph["ping_call"], graph["pong_call"]],
        function_symbols=[graph["ping_fn"], graph["pong_fn"]],
        contract_states=[graph["contract"]],
        proof_obligation_graphs=[graph["pog"]],
        successor_sets=[graph["successors"]],
        frontiers=[graph["frontier"]],
        retained_subroot_cids=[graph["module"].program_graph_node_cid],
        unavailable_dimensions=["reflection"],
    )
    delta = delta_between_snapshots(previous, current)
    assert extra.program_graph_node_cid in delta.added_node_cids
    assert graph["module"].program_graph_node_cid in delta.retained_subroot_cids
    assert graph["ping"].program_graph_node_cid in delta.retained_subroot_cids
    applied = apply_program_graph_delta(previous, delta)
    assert extra.program_graph_node_cid in applied["node_cids"]
    assert graph["module"].program_graph_node_cid in applied["retained_subroot_cids"]
    shuffled = ProgramGraphDelta(
        previous_snapshot_cid=previous.program_graph_snapshot_cid,
        added_node_cids=list(reversed(list(delta.added_node_cids))),
        removed_node_cids=list(reversed(list(delta.removed_node_cids))),
        added_edge_cids=list(reversed(list(delta.added_edge_cids))),
        removed_edge_cids=list(reversed(list(delta.removed_edge_cids))),
        retained_subroot_cids=list(reversed(list(delta.retained_subroot_cids))),
    )
    assert shuffled.program_graph_delta_cid == delta.program_graph_delta_cid
    with pytest.raises(ProgramGraphError, match="cannot be removed"):
        ProgramGraphDelta(
            previous_snapshot_cid=previous.program_graph_snapshot_cid,
            removed_node_cids=[graph["module"].program_graph_node_cid],
            retained_subroot_cids=[graph["module"].program_graph_node_cid],
        )


def test_corrupt_references_fail_closed() -> None:
    ping = _node("function", "pkg.mod.ping")
    missing = _edge(
        "calls",
        ping,
        ping,
        target_node_cid=_cid("missing-node"),
    )
    with pytest.raises(ProgramGraphError, match="corrupt edge reference"):
        _assemble([ping], [missing])
    frontier = DynamicFrontierRecord(
        language="python",
        unresolved_node_cids=[_cid("missing-frontier")],
        reasons=["incomplete_analysis"],
    )
    with pytest.raises(ProgramGraphError, match="corrupt frontier reference"):
        _assemble([ping], [], frontiers=[frontier])
    with pytest.raises(ProgramGraphError, match="corrupt node record_cid"):
        _assemble(
            [_node("function", "pkg.mod.ping", record_cid=_cid("missing-record"))],
            [],
        )
    snapshot = _assemble([ping], [])
    with pytest.raises(ProgramGraphError, match="corrupt delta removes an unknown node"):
        apply_program_graph_delta(
            snapshot,
            ProgramGraphDelta(
                previous_snapshot_cid=snapshot.program_graph_snapshot_cid,
                removed_node_cids=[_cid("ghost")],
            ),
        )
    with pytest.raises(ProgramGraphError, match="not bound to the previous snapshot"):
        apply_program_graph_delta(
            snapshot,
            ProgramGraphDelta(previous_snapshot_cid=_cid("other-snapshot")),
        )


def test_snapshot_projects_landed_identity_envelopes_without_collapsing_cids() -> None:
    graph = _sample_graph()
    snapshot = graph["snapshot"]
    identity_payload = snapshot.to_identity_record()
    identity = ProgramGraphSnapshotIdentity.from_dict(identity_payload)
    assert identity.node_cids == snapshot.node_cids
    assert identity.edge_cids == snapshot.edge_cids
    assert identity.program_graph_snapshot_cid != snapshot.program_graph_snapshot_cid
    canonical = CanonicalProgramGraphIdentity.from_dict(
        {
            "schema": CanonicalProgramGraphIdentity.SCHEMA,
            "language": "python",
            "graph_kind": "static_logical",
            "node_cids": list(snapshot.node_cids),
            "edge_cids": list(snapshot.edge_cids),
            "environment_binding_set_cid": snapshot.environment_binding_set_cid,
            "unavailable_dimensions": list(snapshot.unavailable_dimensions),
            "canonical_program_graph_cid": snapshot.canonical_program_graph_cid,
        }
    )
    assert canonical.canonical_program_graph_cid == snapshot.canonical_program_graph_cid
    extra = _node("test", "pkg.mod.test_ping")
    current = _assemble(
        [
            graph["module"],
            graph["ping"],
            graph["pong"],
            graph["ping_site"],
            graph["pong_site"],
            graph["obligation"],
            graph["contract_node"],
            graph["dynamic"],
            extra,
        ],
        graph["edges"] + [_edge("tested_by", graph["ping"], extra)],
        callsites=[graph["ping_call"], graph["pong_call"]],
        function_symbols=[graph["ping_fn"], graph["pong_fn"]],
        contract_states=[graph["contract"]],
        proof_obligation_graphs=[graph["pog"]],
        successor_sets=[graph["successors"]],
        frontiers=[graph["frontier"]],
        unavailable_dimensions=["reflection"],
    )
    delta = delta_between_snapshots(snapshot, current)
    delta_identity = ProgramGraphDeltaIdentity.from_dict(delta.to_identity_record())
    assert delta_identity.retained_subroot_cids == delta.retained_subroot_cids
    assert delta_identity.program_graph_delta_cid != delta.program_graph_delta_cid


def test_index_manifest_is_rebuildable_and_bound_to_the_snapshot() -> None:
    snapshot = _assemble([_node("module", "pkg.mod")], [])
    manifest = ProgramGraphIndexManifest(
        snapshot_cid=snapshot.program_graph_snapshot_cid,
        index_kind="structural",
        schema_ids=[PROGRAM_GRAPH_SNAPSHOT_SCHEMA],
    )
    assert bind_index_manifest(manifest, snapshot) is manifest
    with pytest.raises(ProgramGraphError, match="not bound"):
        bind_index_manifest(
            ProgramGraphIndexManifest(
                snapshot_cid=_cid("other"),
                index_kind="structural",
                schema_ids=[PROGRAM_GRAPH_SNAPSHOT_SCHEMA],
            ),
            snapshot,
        )
    with pytest.raises(ProgramGraphError, match="cannot be canonical graph authority"):
        ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind="adjacency",
            schema_ids=[PROGRAM_GRAPH_SNAPSHOT_SCHEMA],
            projection_cid=_cid("vector-index"),
            authoritative=True,
        )
    with pytest.raises(ProgramGraphError, match="must remain rebuildable"):
        ProgramGraphIndexManifest(
            snapshot_cid=snapshot.program_graph_snapshot_cid,
            index_kind="adjacency",
            schema_ids=[PROGRAM_GRAPH_SNAPSHOT_SCHEMA],
            rebuildable=False,
        )


def test_callsite_and_function_records_do_not_create_physical_cycles() -> None:
    function = _function("pkg.mod.ping", parameter_names=("x", "y"))
    callsite = _callsite("pkg.mod.ping", "pkg.mod.pong")
    fn_node = _node("function", "pkg.mod.ping", record_cid=function.function_symbol_record_cid)
    site_node = _node("callsite", "pkg.mod.ping#0", record_cid=callsite.callsite_record_cid)
    edge = _edge("calls", fn_node, site_node)
    snapshot = _assemble(
        [fn_node, site_node],
        [edge],
        callsites=[callsite],
        function_symbols=[function],
    )
    verify_program_graph_catalog(
        snapshot,
        nodes=[fn_node, site_node],
        edges=[edge],
        callsites=[callsite],
        function_symbols=[function],
    )
    assert "callsite_cids" not in function.identity_payload()
    assert "program_graph_node_cid" not in callsite.identity_payload()
    with pytest.raises(ProgramGraphError, match="definite callsites require"):
        _callsite("pkg.mod.ping", "pkg.mod.pong", callee_declaration_cid=None)
    with pytest.raises(ProgramGraphError, match="cannot claim a callee declaration"):
        _callsite(
            "pkg.mod.ping",
            "unknown",
            resolution_status="unresolved",
            callee_declaration_cid=_cid("decl:unknown"),
            unavailable_dimensions=("unknown_callee",),
        )


def test_payload_schema_validates_closed_records_and_rejects_unknowns() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    payloads = _sample_payloads()
    for payload in payloads:
        validator.validate(payload)
    loaded = load_payload_schema()
    assert loaded["$id"].endswith("program-graph.payload.schema.json")
    extra = dict(payloads[0])
    extra["embedding"] = [0, 1]
    assert list(validator.iter_errors(extra))
    bad_version = dict(payloads[0])
    bad_version["schema"] = PROGRAM_GRAPH_NODE_SCHEMA.replace("@1", "@99")
    assert list(validator.iter_errors(bad_version))
    assert list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    snapshot_payload = next(
        item for item in payloads if item.get("schema") == PROGRAM_GRAPH_SNAPSHOT_SCHEMA
    )
    ann = dict(snapshot_payload)
    ann["graph_kind"] = "hnsw"
    assert list(validator.iter_errors(ann))
    assert SCHEMA_PATH.is_file()


def test_all_required_node_kinds_can_be_represented_in_one_snapshot() -> None:
    nodes = [
        _node(kind, f"pkg.sample.{kind}")
        for kind in sorted(REQUIRED_NODE_KINDS)
    ]
    dynamic = next(node for node in nodes if node.node_kind == "unresolved_dynamic")
    host = next(node for node in nodes if node.node_kind == "function")
    edges = [
        _edge(
            "unresolved_dynamic",
            host,
            dynamic,
            resolution_status="unavailable",
            unavailable_dimensions=("native_call",),
        )
    ]
    frontier = DynamicFrontierRecord(
        language="python",
        unresolved_node_cids=[dynamic.program_graph_node_cid],
        unresolved_edge_cids=[edges[0].program_graph_edge_cid],
        reasons=["native_call"],
        unavailable_dimensions=("native_call",),
    )
    snapshot = _assemble(nodes, edges, frontiers=[frontier])
    represented = {
        decode_program_graph_record(node.to_dict()).node_kind for node in nodes
    }
    assert represented == REQUIRED_NODE_KINDS
    assert set(ProgramLanguage) >= {ProgramLanguage.PYTHON}
    assert snapshot.node_cids == tuple(sorted(node.program_graph_node_cid for node in nodes))
    canonical_bytes = canonical_program_graph_bytes(snapshot.identity_payload())
    assert canonical_bytes == snapshot.canonical_bytes()
    source = _node("module", "pkg.edges.source")
    target = _node("module", "pkg.edges.target")
    represented_edges = set()
    for kind in sorted(REQUIRED_EDGE_KINDS):
        extras: dict[str, Any] = {}
        if kind in LOGICAL_CYCLE_REQUIRED_KINDS:
            extras["logical_cycle"] = True
        if kind == "unresolved_dynamic":
            extras["resolution_status"] = "unresolved"
            extras["unavailable_dimensions"] = ("incomplete_analysis",)
        represented_edges.add(_edge(kind, source, target, **extras).edge_kind)
    assert represented_edges == REQUIRED_EDGE_KINDS

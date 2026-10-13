"""Candidate graph envelopes with closed endpoints and ordered role edges.

This first profile validates a complete local snapshot. It neither resolves
external imports nor merges equivalent entities nor qualifies legal meaning.
Semantic ASTs and review receipts remain separately content-addressed inputs.
"""
from __future__ import annotations

from .corpus_contracts import (
    CorpusContractError,
    clone_json,
    require_cid,
    require_int,
    require_text,
    seal_record,
    validate_record,
)

NODE_SCHEMA = "legal-corpus-graph-node/v1"
EDGE_SCHEMA = "legal-corpus-graph-edge/v1"
SNAPSHOT_SCHEMA = "legal-corpus-candidate-graph/v1"
MAX_NODES = 4096
MAX_EDGES = 8192
NODE_TYPES = frozenset({
    "source_version", "occurrence", "interpretation", "entity", "term_sense",
    "definition_assertion", "norm_assertion", "scope", "expression", "temporal_spec", "issue",
})
ASSERTIONS = frozenset({"definition_assertion", "norm_assertion"})
ROLES = frozenset({"HAS_ACTOR", "HAS_ACTION", "HAS_OBJECT", "HAS_CONDITION", "HAS_EXCEPTION",
                   "HAS_TEMPORAL_CONSTRAINT"})
ROLE_DESTINATIONS = {
    "HAS_ACTOR": {"entity", "term_sense", "expression"},
    "HAS_ACTION": {"entity", "term_sense", "expression"},
    "HAS_OBJECT": {"entity", "term_sense", "expression"},
    "HAS_CONDITION": {"expression"},
    "HAS_EXCEPTION": {"expression"},
    "HAS_TEMPORAL_CONSTRAINT": {"temporal_spec"},
}
RELATIONS = ROLES | {
    "MENTIONS", "DENOTES", "DEFINES", "USES_DEFINITION", "APPLIES_WITHIN", "HAS_SOURCE",
    "DERIVED_FROM", "CONTAINS", "CITES", "SUPERSEDES",
}
NODE_FIELDS = {
    "node_type", "stable_id", "content_cid", "scope_cid", "source_occurrence_cids",
    "interpretation_cids", "alternative_group_id", "alternative_id",
}
EDGE_FIELDS = {"src_cid", "dst_cid", "relation", "ordinal", "evidence_cids"}
SNAPSHOT_FIELDS = {"nodes", "edges", "view", "admitted", "formalized", "source_semantics_verified"}


def _cid_list(value, label, *, nonempty=False):
    if type(value) is not list or len(value) > MAX_NODES or (nonempty and not value):
        raise CorpusContractError(f"bounded {label} list required")
    result = [require_cid(item, label, codecs=("dag-json",)) for item in value]
    if len(set(result)) != len(result):
        raise CorpusContractError(f"duplicate {label} references")
    return result


def build_node(*, node_type, stable_id, content_cid, scope_cid=None,
               source_occurrence_cids=None, interpretation_cids=None,
               alternative_group_id=None, alternative_id=None):
    payload = dict(schema=NODE_SCHEMA, node_type=node_type, stable_id=stable_id,
                   content_cid=content_cid, scope_cid=scope_cid,
                   source_occurrence_cids=[] if source_occurrence_cids is None else source_occurrence_cids,
                   interpretation_cids=[] if interpretation_cids is None else interpretation_cids,
                   alternative_group_id=alternative_group_id, alternative_id=alternative_id)
    return validate_node(seal_record(payload))


def validate_node(record):
    value = validate_record(record, schema=NODE_SCHEMA, fields=NODE_FIELDS)
    require_text(value["node_type"], "node_type")
    if value["node_type"] not in NODE_TYPES:
        raise CorpusContractError("unsupported graph node type")
    require_text(value["stable_id"], "stable_id")
    require_cid(value["content_cid"], "content_cid")
    if value["scope_cid"] is not None:
        require_cid(value["scope_cid"], "scope_cid", codecs=("dag-json",))
    _cid_list(value["source_occurrence_cids"], "source_occurrence_cids",
              nonempty=value["node_type"] in ASSERTIONS)
    _cid_list(value["interpretation_cids"], "interpretation_cids",
              nonempty=value["node_type"] in ASSERTIONS)
    group, alternative = value["alternative_group_id"], value["alternative_id"]
    if (group is None) != (alternative is None):
        raise CorpusContractError("alternative group and identity must be supplied together")
    if group is not None:
        require_text(group, "alternative_group_id")
        require_text(alternative, "alternative_id")
    return value


def build_edge(*, src_cid, dst_cid, relation, ordinal=None, evidence_cids=None):
    return validate_edge(seal_record(dict(
        schema=EDGE_SCHEMA, src_cid=src_cid, dst_cid=dst_cid, relation=relation,
        ordinal=ordinal, evidence_cids=[] if evidence_cids is None else evidence_cids,
    )))


def validate_edge(record):
    value = validate_record(record, schema=EDGE_SCHEMA, fields=EDGE_FIELDS)
    for key in ("src_cid", "dst_cid"):
        require_cid(value[key], key, codecs=("dag-json",))
    require_text(value["relation"], "relation")
    if value["relation"] not in RELATIONS:
        raise CorpusContractError("unsupported graph relation")
    if value["ordinal"] is not None:
        require_int(value["ordinal"], "ordinal", maximum=MAX_EDGES)
    if value["relation"] in ROLES and value["ordinal"] is None:
        raise CorpusContractError("role edges require an explicit ordinal")
    _cid_list(value["evidence_cids"], "evidence_cids", nonempty=True)
    return value


def _validate_snapshot_parts(nodes, edges):
    if type(nodes) is not list or not 1 <= len(nodes) <= MAX_NODES:
        raise CorpusContractError("nonempty bounded graph nodes required")
    if type(edges) is not list or len(edges) > MAX_EDGES:
        raise CorpusContractError("bounded graph edges required")
    bounded = clone_json({"nodes": nodes, "edges": edges})
    nodes, edges = bounded["nodes"], bounded["edges"]
    checked_nodes = [validate_node(node) for node in nodes]
    checked_edges = [validate_edge(edge) for edge in edges]
    by_cid = {node["record_cid"]: node for node in checked_nodes}
    if len(by_cid) != len(checked_nodes):
        raise CorpusContractError("duplicate graph node CID")
    if len({edge["record_cid"] for edge in checked_edges}) != len(checked_edges):
        raise CorpusContractError("duplicate graph edge CID")
    positions = set()
    for edge in checked_edges:
        if edge["src_cid"] not in by_cid or edge["dst_cid"] not in by_cid:
            raise CorpusContractError("dangling graph endpoint; external imports unsupported in v1")
        src, dst = by_cid[edge["src_cid"]], by_cid[edge["dst_cid"]]
        relation = edge["relation"]
        if relation in ROLES and src["node_type"] != "norm_assertion":
            raise CorpusContractError("role edge source must be a norm assertion")
        if relation in ROLES and dst["node_type"] not in ROLE_DESTINATIONS[relation]:
            raise CorpusContractError("role edge destination has an incompatible node type")
        if relation == "DEFINES" and (src["node_type"] != "definition_assertion"
                                      or dst["node_type"] != "term_sense"):
            raise CorpusContractError("DEFINES requires definition assertion and term sense")
        if relation == "USES_DEFINITION" and (src["node_type"] not in ASSERTIONS
                                              or dst["node_type"] != "definition_assertion"):
            raise CorpusContractError("USES_DEFINITION requires an assertion and definition")
        if relation == "DENOTES" and (src["node_type"] != "occurrence"
                                      or dst["node_type"] not in {"entity", "term_sense"}):
            raise CorpusContractError("DENOTES requires occurrence and entity/term sense")
        if relation == "APPLIES_WITHIN" and dst["node_type"] != "scope":
            raise CorpusContractError("APPLIES_WITHIN destination must be a scope")
        if relation in ROLES:
            position = (edge["src_cid"], relation, edge["ordinal"])
            if position in positions:
                raise CorpusContractError("duplicate role argument position")
            positions.add(position)
        if (src["alternative_group_id"] is not None
                and src["alternative_group_id"] == dst["alternative_group_id"]
                and src["alternative_id"] != dst["alternative_id"]):
            raise CorpusContractError("edge crosses mutually exclusive interpretations")
    return (sorted(checked_nodes, key=lambda node: node["record_cid"]),
            sorted(checked_edges, key=lambda edge: edge["record_cid"]))


def build_graph_snapshot(nodes, edges):
    """Create a candidate-only local graph; no missing endpoint is discarded."""
    checked_nodes, checked_edges = _validate_snapshot_parts(nodes, edges)
    return seal_record(dict(schema=SNAPSHOT_SCHEMA, nodes=checked_nodes, edges=checked_edges,
                            view="candidate", admitted=False, formalized=False,
                            source_semantics_verified=False))


def validate_graph_snapshot(record):
    value = validate_record(record, schema=SNAPSHOT_SCHEMA, fields=SNAPSHOT_FIELDS)
    if (value["view"] != "candidate" or value["admitted"] is not False
            or value["formalized"] is not False or value["source_semantics_verified"] is not False):
        raise CorpusContractError("v1 graph snapshots are candidate-only")
    nodes, edges = _validate_snapshot_parts(value["nodes"], value["edges"])
    if nodes != value["nodes"] or edges != value["edges"]:
        raise CorpusContractError("graph record order differs from canonical snapshot order")
    return value

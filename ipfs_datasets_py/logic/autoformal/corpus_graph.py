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
        _validate_graph_relation_v1(src, dst, relation)
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


def _validate_graph_relation_v1(src, dst, relation):
    """The unchanged local V1 endpoint-type predicates, shared by V2 imports."""
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


# Explicit component composition; the local V1 domain above is unchanged.
COMPONENT_IMPORT_SCHEMA_V2 = "legal-corpus-component-import/v2"
COMPONENT_GRAPH_SCHEMA_V2 = "legal-corpus-component-graph/v2"
COMPONENT_GRAPH_PROFILE_V2 = "ordered-pinned-local-components/v1"
_COMPONENT_ENDPOINT_FIELDS_V2 = {"component_id", "snapshot_cid", "node_cid"}
_COMPONENT_PIN_FIELDS_V2 = {"component_id", "snapshot_cid", "snapshot_sha256", "review_sha256"}
_COMPONENT_GRAPH_FIELDS_V2 = {"profile", "components", "imports", "node_count", "edge_count",
    "view", "admitted", "formalized", "source_semantics_verified", "review_authority",
    "imported_equivalence_asserted", "proof_authority", "lean_authority", "legal_interpretation_accepted",
    "disposition"}


def _component_endpoint_v2(value):
    if type(value) is not dict or set(value) != _COMPONENT_ENDPOINT_FIELDS_V2:
        raise CorpusContractError("closed qualified component endpoint required")
    require_text(value["component_id"], "component_id", max_bytes=256)
    require_cid(value["snapshot_cid"], "snapshot_cid", codecs=("dag-json",))
    require_cid(value["node_cid"], "node_cid", codecs=("dag-json",))
    return clone_json(value)


def build_component_import_v2(*, src, dst, edge):
    """Retain a V1 relation with exact component/snapshot/node endpoint identities."""
    src, dst, edge = _component_endpoint_v2(src), _component_endpoint_v2(dst), validate_edge(edge)
    if src["component_id"] == dst["component_id"]:
        raise CorpusContractError("component imports must cross distinct components; keep local edges in V1")
    if (src["node_cid"], dst["node_cid"]) != (edge["src_cid"], edge["dst_cid"]):
        raise CorpusContractError("component endpoint differs from original edge node identity")
    return seal_record(dict(schema=COMPONENT_IMPORT_SCHEMA_V2, src=src, dst=dst, edge=edge))


def _component_inputs_v2(components, expected_components):
    from .corpus_contracts import MAX_RECORD_BYTES, load_record_bytes, require_sha256
    from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

    if (type(components) is not list or not 1 <= len(components) <= MAX_NODES
            or type(expected_components) is not list or len(expected_components) != len(components)):
        raise CorpusContractError("exact bounded ordered component population required")
    total = 0
    for row in components:
        if type(row) is not dict or set(row) != {"component_id", "snapshot_raw", "review_raw"}:
            raise CorpusContractError("closed complete local component input required")
        for key in ("snapshot_raw", "review_raw"):
            if type(row[key]) is not bytes:
                raise CorpusContractError("complete component snapshot/review bytes required")
            total += len(row[key])
    if total > MAX_RECORD_BYTES:
        raise CorpusContractError("component aggregate byte bound exceeded; no partial import")
    pins = clone_json(expected_components)
    result, seen, positions = [], set(), set()
    node_count = edge_count = 0
    for row, pin in zip(components, pins, strict=True):
        if type(pin) is not dict or set(pin) != _COMPONENT_PIN_FIELDS_V2:
            raise CorpusContractError("complete independently pinned component identity required")
        identity = require_text(pin["component_id"], "component_id", max_bytes=256)
        if identity in seen or row["component_id"] != identity:
            raise CorpusContractError("component membership, order, multiplicity or identity differs")
        seen.add(identity)
        require_cid(pin["snapshot_cid"], "snapshot_cid", codecs=("dag-json",))
        for key in ("snapshot_sha256", "review_sha256"):
            require_sha256(pin[key], key)
        snapshot = validate_graph_snapshot(load_record_bytes(row["snapshot_raw"], expected_sha256=pin["snapshot_sha256"]))
        review = load_record_bytes(row["review_raw"], expected_sha256=pin["review_sha256"])
        require_text(review.get("schema"), "opaque review input schema", max_bytes=256)
        if (snapshot["record_cid"] != pin["snapshot_cid"]
                or canonical_dag_json_bytes(snapshot) != row["snapshot_raw"]
                or canonical_dag_json_bytes(review) != row["review_raw"]):
            raise CorpusContractError("exact canonical component bytes and independently pinned snapshot required")
        node_count += len(snapshot["nodes"])
        edge_count += len(snapshot["edges"])
        if node_count > MAX_NODES or edge_count > MAX_EDGES:
            raise CorpusContractError("component aggregate graph bound exceeded; no partial import")
        for edge in snapshot["edges"]:
            if edge["relation"] in ROLES:
                positions.add((identity, edge["src_cid"], edge["relation"], edge["ordinal"]))
        result.append(dict(component_id=identity, snapshot_sha256=pin["snapshot_sha256"],
            review_sha256=pin["review_sha256"], snapshot=snapshot, review_inputs=review))
    return result, node_count, edge_count, positions


def build_component_graph_v2(components, imports, *, expected_components, expected_import_cids):
    """Compose complete local snapshots with qualified imports, without merging.

    Snapshot and opaque review bytes are independently pinned in exact component
    order. Review claims (including pending/revoked states) are retained verbatim;
    they are not assessed or promoted by composition. All existing finite graph
    and JSON ceilings apply to the complete result. Oversize refuses intact.
    """
    checked, node_count, edge_count, positions = _component_inputs_v2(components, expected_components)
    if (type(imports) is not list or type(expected_import_cids) is not list
            or len(imports) != len(expected_import_cids) or edge_count + len(imports) > MAX_EDGES):
        raise CorpusContractError("exact bounded complete component import population required")
    imports, expected_import_cids = clone_json(imports), clone_json(expected_import_cids)
    for expected in expected_import_cids:
        require_cid(expected, "independent import CID", codecs=("dag-json",))
    if len(set(expected_import_cids)) != len(expected_import_cids):
        raise CorpusContractError("duplicate component import identity")
    by_component = {row["component_id"]: row for row in checked}
    nodes = {row["component_id"]: {node["record_cid"]: node for node in row["snapshot"]["nodes"]}
             for row in checked}
    checked_imports = []
    for imported, expected in zip(imports, expected_import_cids, strict=True):
        require_cid(expected, "independent import CID", codecs=("dag-json",))
        value = validate_record(imported, schema=COMPONENT_IMPORT_SCHEMA_V2, fields={"src", "dst", "edge"})
        rebuilt = build_component_import_v2(src=value["src"], dst=value["dst"], edge=value["edge"])
        if rebuilt != value or value["record_cid"] != expected:
            raise CorpusContractError("original ordered component import differs from independent identity")
        endpoints = []
        for endpoint in (value["src"], value["dst"]):
            identity = endpoint["component_id"]
            component = by_component.get(identity)
            if (component is None or endpoint["snapshot_cid"] != component["snapshot"]["record_cid"]
                    or endpoint["node_cid"] not in nodes[identity]):
                raise CorpusContractError("missing or foreign pinned component endpoint")
            endpoints.append(nodes[identity][endpoint["node_cid"]])
        # Alternative-group identities are local to each component; no bare
        # label/group comparison merges two independently qualified contexts.
        _validate_graph_relation_v1(endpoints[0], endpoints[1], value["edge"]["relation"])
        edge = value["edge"]
        if edge["relation"] in ROLES:
            position = (value["src"]["component_id"], edge["src_cid"], edge["relation"], edge["ordinal"])
            if position in positions:
                raise CorpusContractError("conflicting local/imported role argument position")
            positions.add(position)
        checked_imports.append(value)
    return seal_record(dict(schema=COMPONENT_GRAPH_SCHEMA_V2, profile=COMPONENT_GRAPH_PROFILE_V2,
        components=checked, imports=checked_imports, node_count=node_count,
        edge_count=edge_count + len(checked_imports), view="candidate", admitted=False, formalized=False,
        source_semantics_verified=False, review_authority=False, imported_equivalence_asserted=False,
        proof_authority=False, lean_authority=False, legal_interpretation_accepted=False,
        disposition="complete_candidate_imports_semantics_unresolved"))


def validate_component_graph_v2(record, *, expected_record_cid, expected_components):
    from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

    require_cid(expected_record_cid, "independent component graph CID", codecs=("dag-json",))
    value = validate_record(record, schema=COMPONENT_GRAPH_SCHEMA_V2, fields=_COMPONENT_GRAPH_FIELDS_V2)
    if value["record_cid"] != expected_record_cid:
        raise CorpusContractError("component graph differs from independently retained identity")
    if (type(value["components"]) is not list
            or any(type(row) is not dict or set(row) != {"component_id", "snapshot_sha256",
                "review_sha256", "snapshot", "review_inputs"} for row in value["components"])
            or type(value["imports"]) is not list
            or any(type(row) is not dict or "record_cid" not in row for row in value["imports"])):
        raise CorpusContractError("closed complete component graph rows required")
    rows = [dict(component_id=row["component_id"], snapshot_raw=canonical_dag_json_bytes(row["snapshot"]),
                 review_raw=canonical_dag_json_bytes(row["review_inputs"])) for row in value["components"]]
    expected = build_component_graph_v2(rows, value["imports"], expected_components=expected_components,
        expected_import_cids=[row["record_cid"] for row in value["imports"]])
    if value != expected:
        raise CorpusContractError("component graph differs from exact complete regeneration")
    return expected


def resolve_component_node_v2(record, *, component_id, snapshot_cid, node_cid,
                              expected_record_cid, expected_components):
    """Resolve one exact qualified occurrence; never select by label/equivalence."""
    endpoint = _component_endpoint_v2(dict(component_id=component_id, snapshot_cid=snapshot_cid, node_cid=node_cid))
    graph = validate_component_graph_v2(record, expected_record_cid=expected_record_cid,
                                      expected_components=expected_components)
    for row in graph["components"]:
        if row["component_id"] == endpoint["component_id"] and row["snapshot"]["record_cid"] == endpoint["snapshot_cid"]:
            for node in row["snapshot"]["nodes"]:
                if node["record_cid"] == endpoint["node_cid"]:
                    return clone_json(node)
    raise CorpusContractError("missing or foreign pinned component endpoint")

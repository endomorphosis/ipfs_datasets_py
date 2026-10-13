"""Bounded, source-scoped proposed graphs over existing legal IR contracts.

Ordered AST transport and declared entity/assertion identities are separate
surfaces. Neither structural parity, a legacy sealed cache row, nor an ontology
label establishes legal meaning, context closure, admission, or consistency.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re

from . import legal_statutory_context as context
from ..legal_ir.canonical_contracts import CanonicalRoundTripIR
from ..legal_ir import canonical_statement_scope as statement_scope

SCHEMA = "legal-semantic-proposed-graph/v1"
SOURCE_SCHEMA = "legal-semantic-source-occurrence/v1"
SCOPE_SCHEMA = "legal-semantic-explicit-scope/v1"
PROFILES = ("canonical_rules_v1", "normative_scope_v1")
MAX_BYTES = 1024 * 1024
MAX_NODES = 4096
MAX_DEPTH = 24
MAX_ENTITIES = 256
MAX_ASSERTIONS = 512
MAX_REFS = 128
FALSE_AUTHORITY = dict.fromkeys(("accepted", "admitted", "source_semantics_verified", "context_closed",
    "globally_consistent", "training_qualified", "proof_authority", "definition_semantics_encoded"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_KEYS = {"schema", "document_id", "document_revision", "edition", "view_id", "paragraph_index",
                "selector", "source_binding_sha256"}
_SCOPE_KEYS = {"schema", "jurisdiction", "instrument", "edition", "applicability", "definition_scope", "scope_id"}
_REF_KEYS = {"artifact_id", "artifact_sha256", "role"}
_ENTITY_KEYS = {"entity_key", "kind", "label", "source_selector", "definition_kind", "ast_path", "ambiguity", "evidence_refs"}
_ASSERTION_KEYS = {"assertion_key", "subject_key", "predicate", "object_keys", "ambiguity", "evidence_refs", "dependency_refs"}
_GRAPH_KEYS = {"schema", "profile", "ast_sha256", "tree_seed_sha256", "root_node_id", "nodes", "edges",
    "source", "scope", "scope_request", "entities", "assertions", "dependency_refs", "evidence_refs", "status",
    "original_task_acceptance", "authority", "graph_id"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def wire(value):
    count = 0
    def visit(node, depth):
        nonlocal count
        count += 1
        require(depth <= MAX_DEPTH + 8 and count <= MAX_NODES * 64, "graph JSON depth/node bound exceeded")
        if type(node) is dict:
            require(all(type(key) is str for key in node), "plain graph JSON keys required")
            for child in node.values(): visit(child, depth + 1)
        elif type(node) is list:
            for child in node: visit(child, depth + 1)
        else:
            require(node is None or type(node) in (str, bool, int, float), "plain graph JSON required")
            require(type(node) is not float or math.isfinite(node), "finite graph JSON required")
    visit(value, 0)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (UnicodeError, TypeError, ValueError, RecursionError) as error:
        raise ValueError("bounded UTF8 graph JSON required") from error
    require(len(raw) <= MAX_BYTES, "graph byte bound exceeded; no truncation")
    return raw


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def _text(value, label, *, blank=False):
    require(type(value) is str and len(value) <= 4096 and "\x00" not in value
            and (blank or bool(value.strip())), "bounded " + label + " required")
    try: value.encode()
    except UnicodeError as error: raise ValueError("UTF8 " + label + " required") from error


def _closed(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def _refs(value):
    require(type(value) in (list, tuple) and len(value) <= MAX_REFS, "bounded evidence/dependency references required")
    rows = []
    for row in value:
        _closed(row, _REF_KEYS, "artifact reference")
        _text(row["artifact_id"], "artifact identity")
        _text(row["role"], "artifact role")
        require(type(row["artifact_sha256"]) is str and _SHA.fullmatch(row["artifact_sha256"]), "exact artifact digest required")
        rows.append(deepcopy(row))
    return rows


def bind_source_occurrence(document, raw_html, *, selector, document_revision):
    """Bind an exact v2 selector to one source paragraph and explicit revision."""
    _text(document_revision, "document revision")
    context.validate_source_selector(selector, document, raw_html)
    containing = [row for row in document["paragraphs"] if row["char_start"] <= selector["char_start"]
                  < selector["char_end"] <= row["char_end"]]
    require(len(containing) == 1, "graph source must lie within one exact paragraph occurrence")
    body = {"schema": SOURCE_SCHEMA, "document_id": document["document_id"],
            "document_revision": document_revision, "edition": document["edition"],
            "view_id": selector["view_id"], "paragraph_index": containing[0]["paragraph_index"],
            "selector": deepcopy(selector)}
    return {**body, "source_binding_sha256": digest(body)}


def bind_scope(*, jurisdiction, instrument, edition, applicability, definition_scope):
    """Name declared applicability/definition scope without interpreting it."""
    for label, value in (("jurisdiction", jurisdiction), ("instrument", instrument),
                         ("applicability", applicability), ("definition_scope", definition_scope)):
        _text(value, label)
    require(type(edition) is int and 1 <= edition <= 9999, "explicit integer edition required")
    body = {"schema": SCOPE_SCHEMA, "jurisdiction": jurisdiction, "instrument": instrument,
            "edition": edition, "applicability": applicability, "definition_scope": definition_scope}
    return {**body, "scope_id": "legal-scope:sha256:" + digest(body)}


def _check_bindings(source, scope):
    _closed(source, _SOURCE_KEYS, "source occurrence binding")
    require(source["schema"] == SOURCE_SCHEMA and source["source_binding_sha256"] == digest(
        {key: value for key, value in source.items() if key != "source_binding_sha256"}), "source binding digest differs")
    _text(source["document_revision"], "document revision")
    _text(source["document_id"], "document identity")
    require(type(source["edition"]) is int and type(source["view_id"]) is str
            and context._VIEW_ID.fullmatch(source["view_id"]), "exact edition and normalized view required")
    require(type(source["paragraph_index"]) is int and source["paragraph_index"] >= 0, "paragraph occurrence required")
    selector = source["selector"]
    _closed(selector, context._SELECTOR_KEYS, "source selector")
    require(selector["schema"] == context.SELECTOR_SCHEMA and selector["document_id"] == source["document_id"]
            and selector["view_id"] == source["view_id"], "source selector identity differs")
    require(all(type(selector[key]) is int for key in ("char_start", "char_end", "utf8_byte_start", "utf8_byte_end"))
            and 0 <= selector["char_start"] < selector["char_end"]
            and 0 <= selector["utf8_byte_start"] < selector["utf8_byte_end"], "exact source geometry required")
    require(len(selector["text"]) == selector["char_end"] - selector["char_start"]
            and len(selector["text"].encode()) == selector["utf8_byte_end"] - selector["utf8_byte_start"]
            and context.sha(selector["text"]) == selector["text_sha256"], "source selector bytes differ")
    require(selector["occurrence_id"] == "legal-view-occurrence:sha256:" + context._context_digest(
        {key: value for key, value in selector.items() if key != "occurrence_id"}), "source occurrence identity differs")
    _closed(scope, _SCOPE_KEYS, "explicit graph scope")
    expected = bind_scope(**{key: scope[key] for key in ("jurisdiction", "instrument", "edition", "applicability", "definition_scope")})
    require(wire(scope) == wire(expected) and source["edition"] == scope["edition"], "source/scope edition or scope identity differs")


def _validate_ast(ast, profile, source, scope_request):
    wire(ast)
    require(profile in PROFILES, "unsupported graph AST profile")
    if profile == "canonical_rules_v1":
        CanonicalRoundTripIR.from_dict(ast)  # Type validation only; do not apply its sorting/deduplication.
        require(scope_request is None, "flat rules cannot carry an undeclared scope request")
    else:
        require(type(scope_request) is dict and scope_request.get("source_text") == source["selector"]["text"],
                "scope AST requires exact separately supplied source/context input")
        statement_scope.validate_scope_declaration(scope_request, ast, expected_input_sha256=digest(scope_request))


def _kind(value):
    if type(value) is list: return "ordered_sequence"
    if type(value) is not dict: return "literal"
    if "occurrence_id" in value and "anchor" in value: return "source_mention"
    if "binder_id" in value: return "declared_binder"
    if "modality" in value or {"rule_id", "body", "qualifiers"} <= set(value): return "norm_rule"
    if "op" in value: return "declared_expression"
    return "record"


def _tree(ast, seed):
    nodes, edges = [], []
    def visit(value, path, depth):
        require(depth <= MAX_DEPTH and len(nodes) < MAX_NODES, "ordered AST graph bound exceeded")
        kind = _kind(value)
        if type(value) is dict:
            data = {"keys": sorted(value)}
            children = [(key, value[key]) for key in data["keys"]]
        elif type(value) is list:
            data = {"length": len(value)}
            children = [(str(index), child) for index, child in enumerate(value)]
        else:
            data, children = {"value": value}, []
        payload = {"path": path, "kind": kind, "data": data}
        node_hash = digest(payload)
        node_id = "legal-ast-node:sha256:" + digest({"seed": seed, "node_sha256": node_hash})
        nodes.append({"node_id": node_id, "node_sha256": node_hash, **payload})
        for ordinal, (role, child) in enumerate(children):
            child_path = path + "/" + role.replace("~", "~0").replace("/", "~1")
            child_id = visit(child, child_path, depth + 1)
            edges.append({"parent_id": node_id, "child_id": child_id, "role": role, "ordinal": ordinal})
        return node_id
    root = visit(ast, "", 0)
    return root, nodes, edges


def _pointer(ast, path):
    _text(path, "AST path", blank=True)
    require(path == "" or path.startswith("/"), "absolute AST JSON pointer required")
    value = ast
    for item in path.split("/")[1:]:
        item = item.replace("~1", "/").replace("~0", "~")
        try:
            if type(value) is list:
                require(item.isdigit() and str(int(item)) == item, "canonical AST array index required")
                value = value[int(item)]
            else:
                value = value[item]
        except (KeyError, IndexError, TypeError): raise ValueError("unknown declared AST path") from None
    return value


def _subselector(selector, source):
    _closed(selector, context._SELECTOR_KEYS, "entity occurrence selector")
    origin = source["selector"]
    start, end = selector["char_start"], selector["char_end"]
    require(type(start) is int and type(end) is int and origin["char_start"] <= start < end <= origin["char_end"],
            "entity mention escapes source occurrence")
    text = origin["text"]
    left, right = start - origin["char_start"], end - origin["char_start"]
    payload = {"schema": context.SELECTOR_SCHEMA, "view_id": source["view_id"], "document_id": source["document_id"],
        "char_start": start, "char_end": end, "utf8_byte_start": origin["utf8_byte_start"] + len(text[:left].encode()),
        "utf8_byte_end": origin["utf8_byte_start"] + len(text[:right].encode()),
        "text": text[left:right], "text_sha256": context.sha(text[left:right])}
    expected = {**payload, "occurrence_id": "legal-view-occurrence:sha256:" + context._context_digest(payload)}
    require(wire(selector) == wire(expected), "entity occurrence geometry differs")


def _semantics(declarations, ast, source, scope):
    if declarations is None: declarations = {"entities": [], "assertions": []}
    _closed(declarations, {"entities", "assertions"}, "semantic declarations")
    require(type(declarations["entities"]) is list and len(declarations["entities"]) <= MAX_ENTITIES
            and type(declarations["assertions"]) is list and len(declarations["assertions"]) <= MAX_ASSERTIONS,
            "bounded semantic declarations required")
    entities, by_key, ids = [], {}, set()
    for declaration in declarations["entities"]:
        _closed(declaration, _ENTITY_KEYS, "entity declaration")
        key, kind = declaration["entity_key"], declaration["kind"]
        _text(key, "entity key"); _text(declaration["label"], "display label", blank=True)
        require(key not in by_key and kind in ("mention", "concept", "definition"), "duplicate entity key or unknown entity kind")
        require(type(declaration["ambiguity"]) is list and len(declaration["ambiguity"]) <= 32, "explicit bounded ambiguity alternatives required")
        for alternative in declaration["ambiguity"]: _text(alternative, "ambiguity alternative")
        _refs(declaration["evidence_refs"])
        if declaration["ast_path"] is not None: _pointer(ast, declaration["ast_path"])
        if kind == "concept":
            require(declaration["source_selector"] is None and declaration["definition_kind"] is None,
                    "concept identity cannot silently bind a mention or definition")
            identity = {"kind": kind, "scope_id": scope["scope_id"], "concept_key": key,
                        "document_revision": source["document_revision"]}
        else:
            _subselector(declaration["source_selector"], source)
            require(declaration["definition_kind"] in ("means", "includes", "deems") if kind == "definition"
                    else declaration["definition_kind"] is None, "explicit distinct definition operator required")
            identity = {"kind": kind, "scope_id": scope["scope_id"],
                        "occurrence_id": declaration["source_selector"]["occurrence_id"],
                        "document_revision": source["document_revision"]}
            if kind == "definition": identity.update(definition_kind=declaration["definition_kind"], ast_path=declaration["ast_path"])
        entity_id = "legal-" + kind + ":sha256:" + digest(identity)
        require(entity_id not in ids, "duplicate physical entity identity")
        ids.add(entity_id)
        row = {"entity_id": entity_id, "identity": identity, "declaration": deepcopy(declaration),
               "status": "proposed_unreviewed", "accepted": False, "source_semantics_verified": False}
        row["entity_sha256"] = digest(row)
        entities.append(row); by_key[key] = row
    assertions, seen = [], set()
    for declaration in declarations["assertions"]:
        _closed(declaration, _ASSERTION_KEYS, "relationship assertion declaration")
        key = declaration["assertion_key"]
        _text(key, "assertion key"); _text(declaration["predicate"], "declared predicate")
        require(key not in seen and declaration["subject_key"] in by_key, "duplicate assertion or unknown subject")
        seen.add(key)
        require(type(declaration["object_keys"]) is list and 0 < len(declaration["object_keys"]) <= 32
                and all(type(item) is str and item in by_key for item in declaration["object_keys"]), "ordered known assertion arguments required")
        require(type(declaration["ambiguity"]) is list and len(declaration["ambiguity"]) <= 32, "explicit assertion ambiguity required")
        for alternative in declaration["ambiguity"]: _text(alternative, "assertion ambiguity")
        _refs(declaration["evidence_refs"]); _refs(declaration["dependency_refs"])
        row = {"declaration": deepcopy(declaration), "scope_id": scope["scope_id"],
            "source_binding_sha256": source["source_binding_sha256"],
            "subject_id": by_key[declaration["subject_key"]]["entity_id"],
            "object_ids": [by_key[item]["entity_id"] for item in declaration["object_keys"]],
            "status": "proposed_unreviewed", "accepted": False, "source_semantics_verified": False}
        row["assertion_id"] = "legal-assertion:sha256:" + digest(row)
        assertions.append(row)
    return entities, assertions


def build_graph(ast, *, profile, source, scope, semantic_declarations=None,
                dependency_refs=(), evidence_refs=(), scope_request=None):
    """Build an ordered proposal; independently reviewed legal meaning is absent."""
    _check_bindings(source, scope)
    _validate_ast(ast, profile, source, scope_request)
    seed = digest({"profile": profile, "ast_sha256": digest(ast),
                   "source_binding_sha256": source["source_binding_sha256"], "scope_id": scope["scope_id"]})
    root, nodes, edges = _tree(ast, seed)
    entities, assertions = _semantics(semantic_declarations, ast, source, scope)
    body = {"schema": SCHEMA, "profile": profile, "ast_sha256": digest(ast), "tree_seed_sha256": seed,
        "root_node_id": root, "nodes": nodes, "edges": edges, "source": deepcopy(source), "scope": deepcopy(scope),
        "scope_request": deepcopy(scope_request), "entities": entities, "assertions": assertions,
        "dependency_refs": _refs(dependency_refs), "evidence_refs": _refs(evidence_refs),
        "status": "proposed_unreviewed", "original_task_acceptance": "preparatory_subset_only",
        "authority": dict(FALSE_AUTHORITY)}
    body = json.loads(wire(body))
    return {**body, "graph_id": "legal-proposed-graph:sha256:" + digest(body)}


def graph_to_ast(graph):
    """Decode an ordered tree, rejecting dangling/aliased/orphan/cyclic nodes."""
    _closed(graph, _GRAPH_KEYS, "proposed graph")
    require(graph["schema"] == SCHEMA, "versioned proposed graph required")
    wire(graph)
    require(graph.get("graph_id") == "legal-proposed-graph:sha256:" + digest(
        {key: value for key, value in graph.items() if key != "graph_id"}), "graph content identity differs")
    require(wire(graph.get("authority")) == wire(FALSE_AUTHORITY)
            and graph.get("status") == "proposed_unreviewed", "graph cannot confer semantic authority")
    require(type(graph.get("nodes")) is list and 0 < len(graph["nodes"]) <= MAX_NODES
            and type(graph.get("edges")) is list and len(graph["edges"]) == len(graph["nodes"]) - 1, "bounded tree population required")
    table = {}
    for node in graph["nodes"]:
        _closed(node, {"node_id", "node_sha256", "path", "kind", "data"}, "AST node")
        payload = {key: node[key] for key in ("path", "kind", "data")}
        require(node["node_sha256"] == digest(payload) and node["node_id"] == "legal-ast-node:sha256:" + digest(
            {"seed": graph["tree_seed_sha256"], "node_sha256": node["node_sha256"]}), "AST node identity differs")
        require(node["node_id"] not in table, "duplicate AST node")
        table[node["node_id"]] = node
    children, parents = defaultdict(list), set()
    for edge in graph["edges"]:
        _closed(edge, {"parent_id", "child_id", "role", "ordinal"}, "ordered AST edge")
        require(edge["parent_id"] in table and edge["child_id"] in table and edge["child_id"] not in parents,
                "dangling or multiply parented AST edge")
        require(type(edge["ordinal"]) is int, "exact AST edge ordinal required")
        parents.add(edge["child_id"]); children[edge["parent_id"]].append(edge)
    visited = set()
    def decode(identity, path, depth):
        require(identity in table and identity not in visited and depth <= MAX_DEPTH, "unknown/cyclic/deep AST reference")
        visited.add(identity); node = table[identity]
        require(node["path"] == path, "AST path binding differs")
        links = sorted(children[identity], key=lambda edge: edge["ordinal"])
        require([edge["ordinal"] for edge in links] == list(range(len(links))), "missing/duplicate AST argument order")
        if node["kind"] == "literal":
            _closed(node["data"], {"value"}, "literal node")
            require(not links and type(node["data"]["value"]) not in (dict, list), "literal contains structure")
            return node["data"]["value"]
        if node["kind"] == "ordered_sequence":
            _closed(node["data"], {"length"}, "sequence node")
            require(type(node["data"]["length"]) is int and node["data"]["length"] == len(links)
                    and [edge["role"] for edge in links] == [str(i) for i in range(len(links))], "sequence argument geometry differs")
            return [decode(edge["child_id"], path + "/" + edge["role"], depth + 1) for edge in links]
        _closed(node["data"], {"keys"}, "record node")
        keys = node["data"]["keys"]
        require(type(keys) is list and keys == sorted(set(keys)) and [edge["role"] for edge in links] == keys, "record field binding differs")
        return {edge["role"]: decode(edge["child_id"], path + "/" + edge["role"].replace("~", "~0").replace("/", "~1"), depth + 1) for edge in links}
    ast = decode(graph["root_node_id"], "", 0)
    require(len(visited) == len(table) and graph["root_node_id"] not in parents and digest(ast) == graph["ast_sha256"], "orphan nodes or AST digest differs")
    root, nodes, edges = _tree(ast, graph["tree_seed_sha256"])
    require(wire([root, nodes, edges]) == wire([graph["root_node_id"], graph["nodes"], graph["edges"]]), "AST node typing or ordered graph representation differs")
    _check_bindings(graph["source"], graph["scope"])
    _validate_ast(ast, graph["profile"], graph["source"], graph["scope_request"])
    seed = digest({"profile": graph["profile"], "ast_sha256": digest(ast),
        "source_binding_sha256": graph["source"]["source_binding_sha256"], "scope_id": graph["scope"]["scope_id"]})
    require(seed == graph["tree_seed_sha256"], "AST source/scope seed differs")
    declarations = {"entities": [row["declaration"] for row in graph["entities"]],
                    "assertions": [row["declaration"] for row in graph["assertions"]]}
    entities, assertions = _semantics(declarations, ast, graph["source"], graph["scope"])
    require(wire([entities, assertions]) == wire([graph["entities"], graph["assertions"]]),
            "typed semantic proposal envelopes differ")
    _refs(graph["dependency_refs"]); _refs(graph["evidence_refs"])
    require(graph["original_task_acceptance"] == "preparatory_subset_only", "original task acceptance cannot be promoted")
    return ast


def validate_graph(graph, *, ast, **kwargs):
    """Regenerate from independently supplied source, scope and declarations."""
    require(wire(graph_to_ast(graph)) == wire(ast), "graph differs from externally expected AST")
    expected = build_graph(ast, **kwargs)
    require(wire(graph) == wire(expected), "graph differs from externally expected proposal inputs")
    return {"schema": "legal-semantic-proposed-graph-validation/v1", "graph_id": graph["graph_id"],
            "ordered_ast_roundtrip_verified": True, "entity_count": len(graph["entities"]),
            "assertion_count": len(graph["assertions"]), "authority": dict(FALSE_AUTHORITY),
            "original_task_acceptance": "preparatory_subset_only"}

"""Compact model content for the existing strict relational TypedExpression.

Prediction decoding receives only content and an independently supplied symbol
and role context. Archival identity restoration is a separate API. These
operations call the existing strict-expression/lower hooks, not native fragment
projection, a parser, a model, a solver or Lean. No semantic authority follows.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
import stat

CONTENT_SCHEMA = "legal-relational-compact-content/v1"
CONTEXT_SCHEMA = "legal-relational-compact-context/v1"
IDENTITY_SCHEMA = "legal-relational-compact-identity/v1"
PROJECT_SCHEMA = "legal-relational-compact-projection/v1"
DECODE_SCHEMA = "legal-relational-compact-prediction/v1"
RECONSTRUCT_SCHEMA = "legal-relational-compact-reconstruction/v1"
MAX_CONTENT_BYTES = 262144
MAX_CONTEXT_BYTES = 524288
MAX_IDENTITY_BYTES = 262144
MAX_REQUEST_BYTES = 524288
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_NODES = 512
MAX_DEPTH = 48
MAX_JSON_ITEMS = 100000
MAX_JSON_DEPTH = 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE_FIELDS = {"family", "features", "interface", "metadata", "profile",
                     "schema_version", "sorts", "symbols"}
_IDENTITY_FIELDS = {"schema", "expression_id", "signature_id", "node_ids",
                    "extension_ids", "binder_names", "content_sha256",
                    "context_sha256", "original_request_sha256",
                    "original_expression_sha256"}
_NORMALIZATION = {
    "wire": "sorted-key compact UTF8 JSON; input whitespace is not preserved",
    "tree": "existing constructor names, ordered arguments and modal children",
    "variables": "global quantifier-preorder indices checked in lexical scope",
    "predicates": "indices into the independently supplied ordered signature",
    "identity": "node/extension/expression/signature IDs and binder names in archival sidecar only",
    "semantic_normalization": False,
    "permitted_inference_context_verified": False,
}
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_gold_qualified",
    "evaluation_gold_qualified", "Lean_admitted", "proof_authority",
    "backend_executed", "model_executed", "training_executed",
    "permitted_inference_context_verified", "target_eligibility_verified",
), False)
_OWNER_SPECS = (
    ("ipfs_datasets_py.logic.autoformal.legal_relational_norm_v1",
     "logic/autoformal/legal_relational_norm_v1.py",
     "6af97bbe5bb729fc6218b77bc32551aaca5d2ed2ba89d61312937a3109032614"),
    ("ipfs_datasets_py.logic.syntax_core.ast", "logic/syntax_core/ast.py",
     "4709513f18ab270858fe9595d88a847ddc52092606c52c7802947abed1ab9ac4"),
    ("ipfs_datasets_py.logic.syntax_core.signatures", "logic/syntax_core/signatures.py",
     "49dd4fb0096661a05a15f056eb57248349e2b4e0b02e83239f36db36788c75bf"),
    ("ipfs_datasets_py.logic.TDFOL.tdfol_core", "logic/TDFOL/tdfol_core.py",
     "67be350d1fb0422a64ab040349b2d51c4008fbeeb8b59a99b8901d681d7d71c7"),
)
_SELF_PATH = Path(__file__).resolve()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


def _need(value, message):
    if not value:
        raise ValueError(message)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields),
          "closed exact fields required: " + label)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value, maximum):
    remaining, byte_budget, active = MAX_JSON_ITEMS, maximum, set()

    def charge(count):
        nonlocal byte_budget
        byte_budget -= count
        _need(byte_budget >= 0, "complete JSON byte bound exceeded before serialization")

    def string_size(text):
        # Account every occurrence, including aliases/repeated strings, before
        # allocating the complete serialization. ensure_ascii=False emits the
        # following exact UTF8/JSON escape widths for ordinary valid strings.
        charge(2)
        for character in text:
            code = ord(character)
            _need(not 0xD800 <= code <= 0xDFFF, "valid scalar UTF8 string required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                charge(2)
            elif code < 0x20:
                charge(6)
            else:
                charge(1 if code < 0x80 else 2 if code < 0x800 else 3 if code < 0x10000 else 4)

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= MAX_JSON_DEPTH,
              "bounded ordinary JSON required")
        if type(item) in (dict, list):
            identity = id(item)
            _need(identity not in active, "cyclic JSON is unsupported")
            active.add(identity)
            try:
                charge(2)
                if type(item) is dict:
                    captured = {}
                    for index, (key, child) in enumerate(item.items()):
                        _need(type(key) is str, "ordinary string JSON keys required")
                        charge(1 + (1 if index else 0))
                        visit(key, depth + 1)
                        captured[key] = visit(child, depth + 1)
                    return captured
                else:
                    captured = []
                    for index, child in enumerate(item):
                        if index:
                            charge(1)
                        captured.append(visit(child, depth + 1))
                    return captured
            finally:
                active.remove(identity)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= maximum,
                  "bounded NUL-free UTF8 string required")
            string_size(item)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
            charge(len(str(item)))
        else:
            raise ValueError("ordinary JSON without floats or custom values required")
        return item

    try:
        captured = visit(value, 0)
        result = json.dumps(captured, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, UnicodeError, RecursionError, OverflowError, RuntimeError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _need(len(result) <= maximum, "complete JSON byte bound exceeded")
    return result


def _digest(value, maximum):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _detach(value, maximum):
    return json.loads(_wire(value, maximum))


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _reject_number(_):
    raise ValueError("JSON floats and nonfinite values are unsupported")


def _parse(raw, expected, maximum, label):
    _hash(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum,
          "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, label + " raw SHA256 mismatch")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_float=_reject_number, parse_constant=_reject_number)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("bounded duplicate-free UTF8 JSON required: " + label) from error
    _wire(result, maximum)
    return result


def compact_content_sha256(value):
    """Canonical ordinary content identity only; validation is separate."""
    return _digest(value, MAX_CONTENT_BYTES)


def compact_context_sha256(value):
    """Canonical ordinary context identity only; permission is not established."""
    return _digest(value, MAX_CONTEXT_BYTES)


def compact_identity_sha256(value):
    """Canonical ordinary archival-sidecar identity only; not authentication."""
    return _digest(value, MAX_IDENTITY_BYTES)


def _source(path, expected):
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 131072,
          "bounded regular fixed owner source required")
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected,
          "fixed owner raw source changed or differs")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}


def _package_root():
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py",
                          parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / "logic/autoformal/legal_relational_norm_v1.py").is_file():
                _need(candidate.resolve() == candidate, "canonical package tree required")
                return candidate
    raise ValueError("fixed canonical package tree unavailable")


def _owners():
    root = _package_root()
    pins = [_source(root / rel, expected) for _, rel, expected in _OWNER_SPECS]
    _need(hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest() == _SELF_SHA,
          "compact producer changed since import")
    modules = tuple(importlib.import_module(name) for name, _, _ in _OWNER_SPECS)
    for module, (_, rel, expected) in zip(modules, _OWNER_SPECS):
        _need(Path(module.__file__).resolve() == root / rel,
              "fixed owner loaded outside canonical tree")
        _source(root / rel, expected)
    pins.append({"path": str(_SELF_PATH), "bytes": _SELF_PATH.stat().st_size,
                 "sha256": _SELF_SHA})
    return (*modules, pins)


def _closing(owners):
    _need(_owners()[-1] == owners[-1], "operation owner source custody changed")


def _strict(request, owners):
    relational, ast, signatures, native, _ = owners
    encoded = _wire(request, MAX_REQUEST_BYTES)
    parsed = relational._parse(encoded, hashlib.sha256(encoded).hexdigest())
    expression, predicates = relational._strict_expression(parsed, ast, signatures)
    _, _, counts = relational._lower(expression, predicates, ast, native)
    return expression, counts


def _request(expression, roles):
    return {"schema": "legal-relational-norm-request/v1",
            "interpretation_status": "authored_unreviewed_declaration",
            "expression": expression, "argument_roles": roles, "source_binding": None}


def _fresh_name(index, forbidden):
    # There are at most64 predicate names, so65 short nonce candidates suffice.
    # The index delimiter keeps candidates for distinct binders disjoint.
    for attempt in range(65):
        result = "CompactBinder" + str(index) + "_" + str(attempt)
        if result not in forbidden:
            return result
    raise ValueError("bounded fresh binder name unavailable")


def _context(value, owners):
    _keys(value, {"schema", "signature", "argument_roles"}, "compact context")
    _need(value["schema"] == CONTEXT_SCHEMA, "compact context schema differs")
    _keys(value["signature"], _SIGNATURE_FIELDS, "identity-free signature")
    _need(type(value["argument_roles"]) is list, "ordered role ledger required")
    relational, ast, signatures, _, _ = owners
    declared = {**value["signature"], "signature_id": "compact-context-signature-v1"}
    signature = signatures.LogicSignature.from_dict(declared)
    _need(_wire(signature.to_dict(), MAX_CONTEXT_BYTES) == _wire(declared, MAX_CONTEXT_BYTES),
          "signature must survive exact existing reconstruction")
    _need(1 <= len(signature.symbols) <= 64, "bounded nonempty predicate signature required")
    first = signature.symbols[0]
    _need(1 <= first.arity <= 8, "bounded predicate arity required")
    object_sort = signature.get_sort("Object")
    forbidden = {symbol.name for symbol in signature.symbols}
    names = [_fresh_name(index, forbidden) for index in range(first.arity)]
    root = ast.mk_predicate("compact-context-probe-predicate", first.name,
                            [ast.mk_variable("compact-context-probe-variable:" + str(i),
                                             name, object_sort)
                             for i, name in enumerate(names)])
    for index in reversed(range(len(names))):
        root = ast.mk_forall("compact-context-probe-quantifier:" + str(index),
                             (ast.Binder(names[index], object_sort),), root)
    expression = ast.TypedExpression("compact-context-probe-expression", root, signature)
    # This synthetic one-predicate probe only reuses signature/role validation.
    # All-declared-predicate use is checked on the actual decoded tree by _lower.
    relational._strict_expression(_request(expression.to_dict(), value["argument_roles"]),
                                   ast, signatures)
    return _detach(value, MAX_CONTEXT_BYTES), signature


def prepare_context_v1(signature_raw, argument_roles_raw, *, expected_signature_sha256,
                       expected_argument_roles_sha256):
    """Validate caller-declared vocabulary; remove its archival signature ID.

    Caller permission/exposure and whether this context leaks a target are not
    established. No expression, expected target or identity sidecar is accepted.
    """
    signature = _parse(signature_raw, expected_signature_sha256, MAX_CONTEXT_BYTES, "signature")
    roles = _parse(argument_roles_raw, expected_argument_roles_sha256, MAX_CONTEXT_BYTES, "roles")
    _keys(signature, _SIGNATURE_FIELDS | {"signature_id"}, "existing full signature")
    _need(type(signature["signature_id"]) is str, "signature ID must be text")
    owners = _owners()
    # Require exact native signature parsing before stripping the original ID.
    restored = owners[2].LogicSignature.from_dict(signature).to_dict()
    _need(_wire(restored, MAX_CONTEXT_BYTES) == _wire(signature, MAX_CONTEXT_BYTES),
          "original signature is not an exact existing serialized signature")
    context = {"schema": CONTEXT_SCHEMA,
               "signature": {key: value for key, value in signature.items() if key != "signature_id"},
               "argument_roles": roles}
    result, _ = _context(context, owners)
    _closing(owners)
    return result


def _project(expression, context):
    predicate_indices = {row["name"]: i for i, row in enumerate(context["signature"]["symbols"])}
    node_ids, extension_ids, binder_names = [], [], []

    def walk(node, bound):
        node_ids.append(node["node_id"])
        kind = node["kind"]
        if kind == "variable":
            _need(node["symbol"] in bound, "free variable cannot be projected")
            return [kind, bound[node["symbol"]]]
        if kind == "predicate":
            return [kind, predicate_indices[node["symbol"]],
                    [walk(child, bound) for child in node["arguments"]]]
        if kind in {"forall", "exists"}:
            name = node["binders"][0]["name"]
            index = len(binder_names)
            binder_names.append(name)
            return [kind, index, walk(node["arguments"][0], {**bound, name: index})]
        if kind in {"and", "or", "implies", "iff"}:
            return [kind, *(walk(child, bound) for child in node["arguments"])]
        if kind == "not":
            return [kind, walk(node["arguments"][0], bound)]
        if kind == "extension":
            extension = node["extension"]
            extension_ids.append(extension["node_id"])
            return [kind, extension["payload"]["letter"], walk(extension["children"][0], bound)]
        raise ValueError("unsupported existing relational constructor")

    content = {"schema": CONTENT_SCHEMA, "tree": walk(expression["root"], {})}
    return content, node_ids, extension_ids, binder_names


def _identity(value, content, context, expected_original_request_sha256):
    _keys(value, _IDENTITY_FIELDS, "archival identity sidecar")
    _need(value["schema"] == IDENTITY_SCHEMA, "identity sidecar schema differs")
    for field in ("content_sha256", "context_sha256", "original_request_sha256",
                  "original_expression_sha256"):
        _hash(value[field], field)
    _hash(expected_original_request_sha256, "original canonical request")
    _need(value["content_sha256"] == compact_content_sha256(content)
          and value["context_sha256"] == compact_context_sha256(context),
          "sidecar content or context identity differs")
    _need(value["original_request_sha256"] == expected_original_request_sha256,
          "independent original canonical request identity differs")
    for field in ("expression_id", "signature_id"):
        _need(type(value[field]) is str and 0 < len(value[field]) <= 256,
              "bounded original ID required")
    for field in ("node_ids", "extension_ids", "binder_names"):
        _need(type(value[field]) is list and len(value[field]) <= MAX_NODES
              and all(type(item) is str and 0 < len(item) <= 256 for item in value[field]),
              "bounded complete original identity population required")
    _need(len(set(value["node_ids"] + value["extension_ids"])) ==
          len(value["node_ids"]) + len(value["extension_ids"]),
          "node and extension IDs must be globally unique")
    return value


def _materialize(content, context, signature, owners, identity=None):
    _keys(content, {"schema", "tree"}, "compact content")
    _need(content["schema"] == CONTENT_SCHEMA, "compact content schema differs")
    _, ast, signatures, _, _ = owners
    fingerprint = _digest({"content": content, "context": context}, MAX_CONTENT_BYTES + MAX_CONTEXT_BYTES)
    prefix = fingerprint
    object_sort, bool_sort = signatures.LogicSort("Object").to_dict(), signatures.BOOL_SORT.to_dict()
    names, node_count, modal_count = [], 0, 0
    forbidden = {symbol.name for symbol in signature.symbols}

    def identifier(field, index, fallback):
        if identity is None:
            return fallback
        _need(index < len(identity[field]), "identity population incomplete")
        return identity[field][index]

    def visit(tree, bound, depth, formula):
        nonlocal node_count, modal_count
        _need(type(tree) is list and bool(tree) and type(tree[0]) is str,
              "compact existing-constructor array required")
        _need(depth <= MAX_DEPTH and node_count < MAX_NODES,
              "relational AST node/depth bound exceeded")
        index = node_count
        node_count += 1
        kind = tree[0]
        node_id = identifier("node_ids", index, "compact-node:" + prefix + ":" + str(index))
        result = {"arguments": [], "binders": [], "kind": kind, "metadata": {},
                  "node_id": node_id, "schema_version": ast.LOGIC_NODE_SCHEMA_VERSION,
                  "symbol": "", "sort": bool_sort if formula else object_sort}
        if kind == "variable":
            _need(not formula and len(tree) == 2 and type(tree[1]) is int
                  and tree[1] in bound, "variable must reference a lexically active binder")
            result["symbol"] = names[tree[1]]
            return result
        _need(formula, "predicate arguments must be bound variables")
        if kind == "predicate":
            _need(len(tree) == 3 and type(tree[1]) is int
                  and 0 <= tree[1] < len(signature.symbols) and type(tree[2]) is list,
                  "ordered declared predicate reference required")
            symbol = signature.symbols[tree[1]]
            _need(len(tree[2]) == symbol.arity, "predicate arity differs")
            result["symbol"] = symbol.name
            result["arguments"] = [visit(child, bound, depth + 1, False) for child in tree[2]]
        elif kind in {"and", "or", "implies", "iff"}:
            _need(len(tree) == 3, "exactly binary compact connective required")
            result["arguments"] = [visit(child, bound, depth + 1, True) for child in tree[1:]]
        elif kind == "not":
            _need(len(tree) == 2, "exactly unary compact not required")
            result["arguments"] = [visit(tree[1], bound, depth + 1, True)]
        elif kind in {"forall", "exists"}:
            _need(len(tree) == 3 and type(tree[1]) is int and tree[1] == len(names),
                  "globally unique quantifier-preorder binder index required")
            binder_index = len(names)
            name = identifier("binder_names", binder_index, _fresh_name(binder_index, forbidden))
            names.append(name)
            result["binders"] = [{"name": name, "schema_version": ast.BINDER_SCHEMA_VERSION,
                                    "sort": object_sort}]
            result["arguments"] = [visit(tree[2], bound | {binder_index}, depth + 1, True)]
        elif kind == "extension":
            _need(len(tree) == 3 and type(tree[1]) is str and tree[1] in {"O", "P", "F"},
                  "exact compact O/P/F extension required")
            letter = tree[1]
            ext_id = identifier("extension_ids", modal_count,
                                "compact-extension:" + prefix + ":" + str(modal_count))
            modal_count += 1
            modal_kind = {"O": "obligation", "P": "permission", "F": "forbidden"}[letter]
            result["extension"] = {
                "children": [visit(tree[2], bound, depth + 1, True)],
                "family": context["signature"]["family"], "profile": context["signature"]["profile"],
                "features": sorted(["legacy.classic_letter", "legacy." + modal_kind]),
                "interface": ast.LOGIC_EXTENSION_NODE_INTERFACE, "metadata": {},
                "node_id": ext_id, "payload_schema": "legacy.deontic/v1",
                "payload": {"kind": modal_kind, "letter": letter, "resolution": "deontic",
                            "schema_version": "legacy.deontic/v1"},
                "schema_version": ast.LOGIC_EXTENSION_NODE_SCHEMA_VERSION,
            }
        else:
            raise ValueError("unsupported compact relational constructor: " + kind)
        return result

    root = visit(content["tree"], frozenset(), 0, True)
    if identity is not None:
        _need(len(identity["node_ids"]) == node_count
              and len(identity["extension_ids"]) == modal_count
              and len(identity["binder_names"]) == len(names),
              "identity sidecar must cover exactly the whole preorder population")
    declared = {**context["signature"], "signature_id":
                identity["signature_id"] if identity else "compact-signature-v1:" + compact_context_sha256(context)}
    expression = ast.TypedExpression.from_dict({
        "expression_id": identity["expression_id"] if identity else "compact-expression-v1:" + fingerprint,
        "root": root, "signature": declared,
        "family": declared["family"], "profile": declared["profile"],
        "metadata": {}, "schema_version": ast.TYPED_EXPRESSION_SCHEMA_VERSION,
    }).to_dict()
    request = _request(expression, context["argument_roles"])
    verified, counts = _strict(request, owners)
    _need(_wire(verified.to_dict(), MAX_REQUEST_BYTES) == _wire(expression, MAX_REQUEST_BYTES),
          "reconstructed expression differs from strict owner")
    # This verifies that canonical reconstruction did not change compact content.
    reprojected, _, _, _ = _project(expression, context)
    _need(_wire(reprojected, MAX_CONTENT_BYTES) == _wire(content, MAX_CONTENT_BYTES),
          "compact content differs after existing AST reconstruction")
    return request, expression, counts


def _report(content, context, request, expression, counts, owners, raw_pins, restored=False):
    return {
        "schema": RECONSTRUCT_SCHEMA if restored else DECODE_SCHEMA,
        "status": "archival_identity_restored_unreviewed" if restored else "unreviewed_prediction_decoded",
        "content": content, "context": context, "request": request,
        "request_sha256": _digest(request, MAX_REQUEST_BYTES),
        "typed_expression": expression,
        "typed_expression_sha256": _digest(expression, MAX_REQUEST_BYTES),
        "content_sha256": compact_content_sha256(content),
        "context_sha256": compact_context_sha256(context),
        "input_raw_sha256": raw_pins, "counts": counts, "owner_pins": owners[-1],
        "normalization": dict(_NORMALIZATION), "identity_mode": "restored" if restored else "generated",
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
    }


def project_request_v1(request_raw, *, expected_request_sha256):
    """Project one strict authored fragment; preserve exact identity separately."""
    request = _parse(request_raw, expected_request_sha256, MAX_REQUEST_BYTES, "request")
    owners = _owners()
    expression, counts = _strict(request, owners)
    original = expression.to_dict()
    context = {"schema": CONTEXT_SCHEMA,
               "signature": {key: value for key, value in original["signature"].items()
                             if key != "signature_id"},
               "argument_roles": request["argument_roles"]}
    context, _ = _context(context, owners)
    content, node_ids, extension_ids, binder_names = _project(original, context)
    original_request_sha = _digest(request, MAX_REQUEST_BYTES)
    original_expression_sha = _digest(original, MAX_REQUEST_BYTES)
    identity = {
        "schema": IDENTITY_SCHEMA, "expression_id": original["expression_id"],
        "signature_id": original["signature"]["signature_id"],
        "node_ids": node_ids, "extension_ids": extension_ids, "binder_names": binder_names,
        "content_sha256": compact_content_sha256(content),
        "context_sha256": compact_context_sha256(context),
        "original_request_sha256": original_request_sha,
        "original_expression_sha256": original_expression_sha,
    }
    _identity(identity, content, context, original_request_sha)
    # Validate the archival inverse now; hashes alone are not a roundtrip check.
    restored_request, restored, restored_counts = _materialize(content, context, owners[2].LogicSignature.from_dict(
        {**context["signature"], "signature_id": "compact-context-signature-v1"}), owners, identity)
    _need(_wire(restored, MAX_REQUEST_BYTES) == _wire(original, MAX_REQUEST_BYTES)
          and restored_counts == counts
          and _wire(restored_request, MAX_REQUEST_BYTES) == _wire(request, MAX_REQUEST_BYTES),
          "archival projection is not lossless")
    result = {
        "schema": PROJECT_SCHEMA, "status": "strict_relational_content_projected_unreviewed",
        "content": content, "context": context, "identity_sidecar": identity,
        "content_sha256": identity["content_sha256"], "context_sha256": identity["context_sha256"],
        "identity_sha256": compact_identity_sha256(identity),
        "original_request_sha256": original_request_sha,
        "original_request_raw_sha256": expected_request_sha256,
        "original_expression_sha256": original_expression_sha, "counts": counts,
        "owner_pins": owners[-1], "normalization": dict(_NORMALIZATION),
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
    }
    detached = _detach(result, MAX_REPORT_BYTES)
    _closing(owners)
    return detached


def decode_prediction_v1(content_raw, context_raw, *, expected_content_sha256,
                         expected_context_sha256):
    """Decode target-free content using only caller-permitted vocabulary/context.

    This API has no original target, identity-sidecar or expected-tree argument.
    Every declared predicate must occur, as required by the unchanged owner.
    """
    content = _parse(content_raw, expected_content_sha256, MAX_CONTENT_BYTES, "content")
    context = _parse(context_raw, expected_context_sha256, MAX_CONTEXT_BYTES, "context")
    owners = _owners()
    context, signature = _context(context, owners)
    request, expression, counts = _materialize(content, context, signature, owners)
    result = _report(content, context, request, expression, counts, owners,
                     {"content": expected_content_sha256, "context": expected_context_sha256})
    detached = _detach(result, MAX_REPORT_BYTES)
    _closing(owners)
    return detached


def reconstruct_request_v1(content_raw, context_raw, identity_raw, *,
                           expected_content_sha256, expected_context_sha256,
                           expected_identity_sha256, expected_original_request_sha256):
    """Restore archival IDs against an independently pinned canonical request."""
    content = _parse(content_raw, expected_content_sha256, MAX_CONTENT_BYTES, "content")
    context = _parse(context_raw, expected_context_sha256, MAX_CONTEXT_BYTES, "context")
    identity = _parse(identity_raw, expected_identity_sha256, MAX_IDENTITY_BYTES, "identity")
    identity = _identity(identity, content, context, expected_original_request_sha256)
    owners = _owners()
    context, signature = _context(context, owners)
    request, expression, counts = _materialize(content, context, signature, owners, identity)
    _need(_digest(request, MAX_REQUEST_BYTES) == expected_original_request_sha256
          and _digest(expression, MAX_REQUEST_BYTES) == identity["original_expression_sha256"],
          "restored original request or expression identity mismatch")
    result = _report(content, context, request, expression, counts, owners,
                     {"content": expected_content_sha256, "context": expected_context_sha256,
                      "identity": expected_identity_sha256}, restored=True)
    result.update(identity_sha256=compact_identity_sha256(identity),
                  original_request_sha256=expected_original_request_sha256)
    detached = _detach(result, MAX_REPORT_BYTES)
    _closing(owners)
    return detached


__all__ = ["project_request_v1", "prepare_context_v1", "decode_prediction_v1",
           "reconstruct_request_v1", "compact_content_sha256",
           "compact_context_sha256", "compact_identity_sha256"]

"""Explicit optional-catalog grammar over the existing compact content syntax.

The fixed lexical vocabulary is reused, not its old complete-predicate policy.
Every full catalog is validated before intake. A complete generated tree names
its own nonempty referenced subset; a declared projection in catalog order is
then checked by the unchanged public compact prediction owner. This supplies
neither context permission nor numerical head/checkpoint compatibility.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat


CODEC_SCHEMA = "legal-compact-catalog-token-codec/v1"
ENCODING_SCHEMA = "legal-compact-catalog-token-encoding/v1"
PREFIX_SCHEMA = "legal-compact-catalog-token-prefix/v1"
CANDIDATE_SCHEMA = "legal-compact-catalog-token-candidate/v1"
CONTENT_SCHEMA = "legal-relational-compact-content/v1"
CONTEXT_SCHEMA = "legal-relational-compact-catalog-context/v1"
PROFILE = "object-relational-compact-catalog-tokens/v1"
FORMAT = "fixed-json-lexical-compact-catalog/v1"
SELECTION_POLICY = "referenced_predicates_in_catalog_order/v1"
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2
MAX_SEQUENCE_TOKENS = 512
MAX_NODES, MAX_DEPTH = 512, 48
MAX_CONTENT_BYTES, MAX_CONTEXT_BYTES = 262144, 524288
MAX_REPORT_BYTES, MAX_CODEC_BYTES = 2 * 1024 * 1024, 32768
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_ROOT = _SELF_PATH.parents[3]
_TOKEN_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1"
_CONTENT_NAME = "ipfs_datasets_py.logic.autoformal.legal_compact_content_v1"
_SOURCE_SPECS = (
    ("logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    ("logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
    ("logic/autoformal/legal_relational_norm_v1.py",
     "6af97bbe5bb729fc6218b77bc32551aaca5d2ed2ba89d61312937a3109032614"),
    ("logic/syntax_core/ast.py", "4709513f18ab270858fe9595d88a847ddc52092606c52c7802947abed1ab9ac4"),
    ("logic/syntax_core/signatures.py", "49dd4fb0096661a05a15f056eb57248349e2b4e0b02e83239f36db36788c75bf"),
    ("logic/TDFOL/tdfol_core.py", "67be350d1fb0422a64ab040349b2d51c4008fbeeb8b59a99b8901d681d7d71c7"),
)
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted", "training_qualified",
    "training_gold_qualified", "evaluation_gold_qualified", "permitted_inference_context_verified",
    "content_context_independence_verified", "checkpoint_compatibility_verified", "numerical_head_compatible",
    "batch_compatibility_verified", "model_executed", "training_executed", "backend_executed",
    "Lean_admitted", "proof_authority", "global_prefix_completability_proven"), False)


class CompactCatalogTokensError(ValueError):
    """Whole-input, fixed-source, codec, catalog or complete-output refusal."""


def _need(value, message):
    if not value:
        raise CompactCatalogTokensError(message)


def _raw_preflight(raw, expected, maximum, label):
    _need(type(expected) is str and _SHA.fullmatch(expected) is not None,
          "independent lowercase SHA256 required: " + label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, label + " raw SHA256 differs")


def _snapshot(path):
    _need(path.is_absolute() and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "unaliased canonical source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4 * 1024 * 1024,
              "bounded regular canonical source required")
        raw = stream.read(4 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
          "canonical source changed during snapshot")
    return hashlib.sha256(raw).hexdigest(), identity(before)


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)
_SOURCE_BASELINE = None


def _source_snapshots():
    global _SOURCE_BASELINE
    result = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(result[str(_SELF_PATH)] == _SELF_SNAPSHOT, "catalog token owner changed since import")
    for relative, expected in _SOURCE_SPECS:
        path = _ROOT / relative
        result[str(path)] = _snapshot(path)
        _need(result[str(path)][0] == expected, "fixed catalog operation source generation differs")
    if _SOURCE_BASELINE is None:
        _SOURCE_BASELINE = dict(result)
    _need(result == _SOURCE_BASELINE, "catalog operation physical source identity changed")
    return result


def _token_owner():
    """Load only the fixed standard-library token primitives for codec building."""
    before = _source_snapshots()
    tokens = importlib.import_module(_TOKEN_NAME)
    path = _ROOT / _SOURCE_SPECS[0][0]
    _need(type(tokens.__file__) is str and Path(tokens.__file__).absolute() == path
          and tokens._SELF_SHA == before[str(path)][0], "fixed token module origin/import anchor differs")
    _need(_source_snapshots() == before, "sources changed during token import")
    return tokens, None, before


def _owners(loaded=None):
    loaded = _token_owner() if loaded is None else loaded
    tokens, _, before = loaded
    _need(_source_snapshots() == before, "sources changed before content import")
    content = importlib.import_module(_CONTENT_NAME)
    path = _ROOT / _SOURCE_SPECS[1][0]
    _need(type(content.__file__) is str and Path(content.__file__).absolute() == path
          and content._SELF_SHA == before[str(path)][0], "fixed content module origin/import anchor differs")
    _need(tuple((row[1], row[2]) for row in content._OWNER_SPECS) == _SOURCE_SPECS[2:],
          "fixed content dependency closure differs")
    _need(_source_snapshots() == before, "sources changed during content import")
    return tokens, content, before


def _closing(loaded):
    _need(_source_snapshots() == loaded[2], "catalog operation source custody changed")
    tokens, content, snapshots = loaded
    for module in (tokens, content):
        if module is not None:
            _need(module._SELF_SHA == snapshots[str(Path(module.__file__).absolute())][0],
                  "loaded operation import anchor changed")


def _finish(value, loaded, maximum=MAX_REPORT_BYTES):
    detached = loaded[0]._detach(value, maximum)
    _closing(loaded)
    return detached


def _fixed(tokens):
    old = tokens.build_compact_content_token_codec_v1()
    old_sha = tokens.compact_content_token_codec_sha256(old)
    result = tokens._detach(old, MAX_CODEC_BYTES)
    result.update(schema=CODEC_SCHEMA, profile=PROFILE, format=FORMAT, context_schema=CONTEXT_SCHEMA,
        selection_policy=SELECTION_POLICY, parent_codec_sha256=old_sha,
        grammar_scope="local canonical JSON prefixes; context-dependent arity, lexical binding and nonempty referenced catalog subset")
    _need(result["vocabulary_size"] == 537 and result["vocabulary"] == old["vocabulary"],
          "fixed existing lexical vocabulary differs")
    return result


def build_compact_catalog_token_codec_v1():
    """Build a distinct grammar contract without a target, context or model."""
    loaded = _token_owner()
    return _finish(_fixed(loaded[0]), loaded, MAX_CODEC_BYTES)


def compact_catalog_token_codec_sha256(codec):
    """Validate the whole new codec, not just its reused vocabulary width."""
    loaded = _token_owner()
    tokens = loaded[0]
    raw = tokens._wire(codec, MAX_CODEC_BYTES)
    _need(raw == tokens._wire(_fixed(tokens), MAX_CODEC_BYTES), "exact optional-catalog codec required")
    result = hashlib.sha256(raw).hexdigest()
    _closing(loaded)
    return result


def _codec(codec, expected, loaded):
    _need(type(expected) is str and _SHA.fullmatch(expected) is not None, "independent codec SHA256 required")
    tokens = loaded[0]
    raw = tokens._wire(codec, MAX_CODEC_BYTES)
    fixed = _fixed(tokens)
    _need(hashlib.sha256(raw).hexdigest() == expected and raw == tokens._wire(fixed, MAX_CODEC_BYTES),
          "independent exact optional-catalog codec differs")
    return tokens._detach(fixed, MAX_CODEC_BYTES)


def prepare_catalog_context_v1(signature_raw, argument_roles_raw, *, expected_signature_sha256,
                               expected_argument_roles_sha256):
    """Assemble a whole caller-declared catalog, without targets or permission."""
    _raw_preflight(signature_raw, expected_signature_sha256, MAX_CONTEXT_BYTES, "signature")
    _raw_preflight(argument_roles_raw, expected_argument_roles_sha256, MAX_CONTEXT_BYTES, "roles")
    loaded = _owners()
    catalog = loaded[1].prepare_context_v1(signature_raw, argument_roles_raw,
        expected_signature_sha256=expected_signature_sha256,
        expected_argument_roles_sha256=expected_argument_roles_sha256)
    result = {"schema": CONTEXT_SCHEMA, "selection_policy": SELECTION_POLICY, "catalog": catalog}
    return _finish(result, loaded, MAX_CONTEXT_BYTES)


def _context(raw, expected, loaded):
    tokens, content, _ = loaded
    context = tokens._parse(raw, expected, MAX_CONTEXT_BYTES, "catalog context")
    _need(type(context) is dict and set(context) == {"schema", "selection_policy", "catalog"}
          and context["schema"] == CONTEXT_SCHEMA and context["selection_policy"] == SELECTION_POLICY,
          "closed optional-catalog context and exact selection policy required")
    catalog = context["catalog"]
    _need(type(catalog) is dict and set(catalog) == {"schema", "signature", "argument_roles"}
          and catalog["schema"] == "legal-relational-compact-context/v1"
          and type(catalog["signature"]) is dict and "signature_id" not in catalog["signature"],
          "complete identity-free original catalog required")
    signature = {**catalog["signature"], "signature_id": "compact-catalog-context-signature-v1"}
    signature_raw = tokens._wire(signature, MAX_CONTEXT_BYTES)
    roles_raw = tokens._wire(catalog["argument_roles"], MAX_CONTEXT_BYTES)
    checked = content.prepare_context_v1(signature_raw, roles_raw,
        expected_signature_sha256=hashlib.sha256(signature_raw).hexdigest(),
        expected_argument_roles_sha256=hashlib.sha256(roles_raw).hexdigest())
    _need(tokens._wire(checked, MAX_CONTEXT_BYTES) == tokens._wire(catalog, MAX_CONTEXT_BYTES),
          "whole catalog differs from public original context validation")
    _closing(loaded)
    return context


def _scan(ids, vocabulary, context, tokens):
    """Reuse the fixed parser tree; only explicit whole-document policy differs."""
    counts = {"nodes": 0, "quantifiers": 0, "modal_nodes": 0, "predicate_occurrences": 0}
    if not ids:
        return "empty", None, {BOS_ID}, counts, None
    if any(index < 0 or index >= len(vocabulary) for index in ids):
        return "rejected", "invalid_token_ids", set(), counts, None
    if ids[0] != BOS_ID:
        return "rejected", "missing_bos", set(), counts, None
    terminal = len(ids) > 1 and ids[-1] == EOS_ID
    body = ids[1:-1] if terminal else ids[1:]
    if any(index < 3 for index in body):
        return "rejected", "interior_special_tokens", set(), counts, None

    class CatalogParser(tokens._PrefixParser):
        def document(self):
            for token in ("{", '"schema"', ":", json.dumps(CONTENT_SCHEMA), ",", '"tree"', ":"):
                self.literal(token)
            tree = self.tree(frozenset(), 0)
            self.literal("}")
            if not self.used or self.binders == 0:
                raise tokens._GrammarError("completed catalog tree must quantify and reference a nonempty subset")
            if self.position != len(self.tokens):
                raise tokens._GrammarError("tokens after complete catalog content")
            return {"schema": CONTENT_SCHEMA, "tree": tree}

    parser = CatalogParser([vocabulary[index] for index in body], context["catalog"])
    try:
        content = parser.document()
    except tokens._More as error:
        if terminal:
            return "rejected", "invalid_compact_prefix", set(), parser.counts, None
        positions = {token: index for index, token in enumerate(vocabulary)}
        return "prefix", None, {positions[token] for token in error.choices}, parser.counts, None
    except tokens._GrammarError:
        return "rejected", "invalid_compact_prefix", set(), parser.counts, None
    return ("complete", None, set(), parser.counts, content) if terminal else (
        "prefix", None, {EOS_ID}, parser.counts, content)


def _analysis(ids, codec, context, tokens):
    status, reason, choices, counts, content = _scan(ids, codec["vocabulary"], context, tokens)
    if status in {"rejected", "complete"}:
        return status, reason, [], counts, content
    if len(ids) == MAX_SEQUENCE_TOKENS:
        return "budget_exhausted", "output_limit_without_eos", [], counts, content
    allowed = []
    for token in sorted(choices):
        trial = ids + [token]
        state, _, _, _, _ = _scan(trial, codec["vocabulary"], context, tokens)
        if state != "rejected" and (len(trial) < MAX_SEQUENCE_TOKENS or state == "complete"):
            allowed.append(token)
    if not allowed:
        if len(ids) >= MAX_SEQUENCE_TOKENS - 1:
            return "budget_exhausted", "no_admissible_next_token_within_total_limit", [], counts, content
        return "rejected", "invalid_compact_prefix", [], counts, content
    return status, reason, allowed, counts, content


def _base(schema, codec_sha, context, raw_sha, loaded):
    tokens, _, snapshots = loaded
    return {"schema": schema, "profile": PROFILE, "format": FORMAT, "selection_policy": SELECTION_POLICY,
        "codec_sha256": codec_sha, "context_sha256": tokens._sha(context, MAX_CONTEXT_BYTES),
        "context_raw_sha256": raw_sha, "catalog_context": context,
        "catalog_sha256": tokens._sha(context["catalog"], MAX_CONTEXT_BYTES),
        "owner_pins": [{"path": name, "bytes": snapshot[1][3], "sha256": snapshot[0]}
                       for name, snapshot in sorted(snapshots.items())],
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}


def _selection(content, context, codec_sha, counts, loaded):
    """Project only generated references, retaining the entire original catalog."""
    tokens, owner, snapshots = loaded
    used = set()

    def visit(tree, mapping=None):
        kind = tree[0]
        if kind == "variable":
            return list(tree)
        if kind == "predicate":
            used.add(tree[1])
            index = tree[1] if mapping is None else mapping[tree[1]]
            return [kind, index, [visit(child, mapping) for child in tree[2]]]
        if kind in ("forall", "exists", "extension"):
            return [kind, tree[1], visit(tree[2], mapping)]
        return [kind, *(visit(child, mapping) for child in tree[1:])]

    visit(content["tree"])
    catalog = context["catalog"]
    total = len(catalog["signature"]["symbols"])
    selected = sorted(used)
    _need(selected and all(type(index) is int and 0 <= index < total for index in selected),
          "complete content must reference a nonempty declared subset")
    mapping = {old: new for new, old in enumerate(selected)}
    effective_content = {"schema": CONTENT_SCHEMA, "tree": visit(content["tree"], mapping)}
    by_symbol = {row["symbol"]: index for index, row in enumerate(catalog["argument_roles"])}
    role_indices = [by_symbol[catalog["signature"]["symbols"][index]["name"]] for index in selected]
    effective_context = tokens._detach(catalog, MAX_CONTEXT_BYTES)
    effective_context["signature"]["symbols"] = [catalog["signature"]["symbols"][index] for index in selected]
    effective_context["argument_roles"] = [catalog["argument_roles"][index] for index in role_indices]
    content_raw, context_raw = tokens._wire(effective_content, MAX_CONTENT_BYTES), tokens._wire(effective_context, MAX_CONTEXT_BYTES)
    _closing(loaded)
    prediction = owner.decode_prediction_v1(content_raw, context_raw,
        expected_content_sha256=hashlib.sha256(content_raw).hexdigest(),
        expected_context_sha256=hashlib.sha256(context_raw).hexdigest())
    _closing(loaded)
    _need(type(prediction) is dict and prediction.get("identity_mode") == "generated"
          and prediction.get("content_sha256") == hashlib.sha256(content_raw).hexdigest()
          and prediction.get("context_sha256") == hashlib.sha256(context_raw).hexdigest()
          and tokens._wire(prediction["content"], MAX_CONTENT_BYTES) == content_raw
          and tokens._wire(prediction["context"], MAX_CONTEXT_BYTES) == context_raw
          and prediction.get("counts") == counts
          and prediction.get("request_sha256") == tokens._sha(prediction["request"], 524288)
          and prediction["request"].get("source_binding") is None,
          "public original prediction differs from exact catalog projection")
    _need(type(prediction.get("authority")) is dict and prediction["authority"]
          and all(value is False for value in prediction["authority"].values())
          and type(prediction.get("training_mask")) is int and prediction["training_mask"] == 0
          and type(prediction.get("evaluation_gold_mask")) is int and prediction["evaluation_gold_mask"] == 0,
          "public original prediction authority differs")
    expected_paths = {str(_ROOT / relative) for relative, _ in _SOURCE_SPECS[1:]}
    records = prediction.get("owner_pins")
    _need(type(records) is list and len(records) == len(expected_paths), "complete original prediction source population required")
    seen = set()
    for record in records:
        _need(type(record) is dict and set(record) == {"path", "bytes", "sha256"}, "closed original prediction source record required")
        name = record["path"]
        _need(type(name) is str and name in expected_paths and name not in seen
              and record["sha256"] == snapshots[name][0] and type(record["bytes"]) is int
              and record["bytes"] == snapshots[name][1][3], "original prediction producer commitment differs")
        seen.add(name)
    original_content_sha = tokens._sha(content, MAX_CONTENT_BYTES)
    identity = {"schema": "legal-compact-catalog-prediction-identity/v1", "selection_policy": SELECTION_POLICY,
        "codec_sha256": codec_sha, "context_sha256": tokens._sha(context, MAX_CONTEXT_BYTES),
        "content_sha256": original_content_sha}
    return {"catalog_content": content, "catalog_content_sha256": original_content_sha,
        "selected_catalog_indices": selected, "unused_catalog_indices": [i for i in range(total) if i not in used],
        "catalog_to_effective": [mapping.get(i) for i in range(total)], "selected_role_row_indices": role_indices,
        "effective_context": effective_context, "effective_context_sha256": hashlib.sha256(context_raw).hexdigest(),
        "effective_content": effective_content, "effective_content_sha256": hashlib.sha256(content_raw).hexdigest(),
        "prediction": prediction, "prediction_sha256": tokens._sha(prediction, MAX_REPORT_BYTES),
        "catalog_prediction_id": "compact-catalog-prediction-v1:" + tokens._sha(identity, 4096)}


def encode_compact_catalog_tokens_v1(content_raw, context_raw, *, expected_content_sha256,
                                    expected_context_sha256, codec, expected_codec_sha256):
    """Encode a whole offered target under the explicit optional-catalog policy."""
    _raw_preflight(content_raw, expected_content_sha256, MAX_CONTENT_BYTES, "content")
    _raw_preflight(context_raw, expected_context_sha256, MAX_CONTEXT_BYTES, "catalog context")
    loaded = _token_owner()
    tokens = loaded[0]
    fixed = _codec(codec, expected_codec_sha256, loaded)
    content = tokens._parse(content_raw, expected_content_sha256, MAX_CONTENT_BYTES, "content")
    canonical = tokens._wire(content, MAX_CONTENT_BYTES)
    lexical = tokens._LEXICAL.findall(canonical.decode("utf-8"))
    _need("".join(lexical).encode("utf-8") == canonical, "canonical JSON lexical coverage differs")
    positions = {token: index for index, token in enumerate(fixed["vocabulary"])}
    _need(all(token in positions for token in lexical), "content token outside fixed vocabulary")
    ids = tokens._ids([BOS_ID, *(positions[token] for token in lexical), EOS_ID])
    loaded = _owners(loaded)
    context = _context(context_raw, expected_context_sha256, loaded)
    status, _, _, counts, checked = _analysis(ids, fixed, context, tokens)
    _need(status == "complete" and tokens._wire(checked, MAX_CONTENT_BYTES) == canonical,
          "complete content violates optional-catalog grammar")
    selection = _selection(checked, context, expected_codec_sha256, counts, loaded)
    result = _base(ENCODING_SCHEMA, expected_codec_sha256, context, expected_context_sha256, loaded)
    result.update(status="encoded_unreviewed_content", target_ids=ids, lexical_tokens=lexical,
        lexical_token_count=len(lexical), total_token_count=len(ids), canonical_content_raw_utf8=canonical.decode("utf-8"),
        content_sha256=hashlib.sha256(canonical).hexdigest(), original_content_raw_sha256=expected_content_sha256,
        selection=selection, counts=counts)
    return _finish(result, loaded)


def compact_catalog_allowed_token_ids_v1(prefix_ids, context_raw, *, expected_context_sha256,
                                         codec, expected_codec_sha256):
    """Inspect one local prefix without selecting or repairing a complete target."""
    _raw_preflight(context_raw, expected_context_sha256, MAX_CONTEXT_BYTES, "catalog context")
    loaded = _token_owner()
    tokens = loaded[0]
    ids = tokens._ids(prefix_ids)
    fixed = _codec(codec, expected_codec_sha256, loaded)
    loaded = _owners(loaded)
    context = _context(context_raw, expected_context_sha256, loaded)
    status, reason, allowed, counts, _ = _analysis(ids, fixed, context, tokens)
    result = _base(PREFIX_SCHEMA, expected_codec_sha256, context, expected_context_sha256, loaded)
    result.update(status=status, reason=reason, offered_ids=ids, allowed_token_ids=allowed, counts=counts,
        local_prefix_only=True, global_completability_proven=False, remaining_token_slots=MAX_SEQUENCE_TOKENS - len(ids))
    return _finish(result, loaded)


def decode_compact_catalog_tokens_v1(generated_ids, context_raw, *, expected_context_sha256,
                                    codec, expected_codec_sha256):
    """Retain raw catalog-index IDs; only complete candidates get a projection."""
    _raw_preflight(context_raw, expected_context_sha256, MAX_CONTEXT_BYTES, "catalog context")
    loaded = _token_owner()
    tokens = loaded[0]
    ids = tokens._ids(generated_ids)
    fixed = _codec(codec, expected_codec_sha256, loaded)
    loaded = _owners(loaded)
    context = _context(context_raw, expected_context_sha256, loaded)
    status, reason, _, counts, content = _analysis(ids, fixed, context, tokens)
    valid = all(0 <= index < fixed["vocabulary_size"] for index in ids)
    bos, eos, terminal = bool(ids) and ids[0] == BOS_ID, EOS_ID in ids, bool(ids) and ids[-1] == EOS_ID
    body = ids[1:-1] if bos and terminal else ids[1:] if bos else ids
    interior = any(0 <= index < 3 for index in body)
    text = "".join(fixed["vocabulary"][index] for index in body) if valid and not interior else None
    result = _base(CANDIDATE_SCHEMA, expected_codec_sha256, context, expected_context_sha256, loaded)
    result.update(status="rejected", reason=reason, generated_ids=ids,
        generated_content_raw_utf8=text, generated_content_hex=text.encode("utf-8").hex() if text is not None else None,
        generated_content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
        framing={"bos_present": bos, "eos_present": eos, "eos_terminal": terminal,
            "token_ids_valid": valid, "interior_special_tokens": interior,
            "terminated": bool(valid and bos and terminal and not interior)}, selection=None, counts=None)
    if not ids:
        result.update(status="incomplete", reason="missing_bos_and_eos")
    elif status == "complete":
        result.update(status="valid_candidate", reason=None,
            selection=_selection(content, context, expected_codec_sha256, counts, loaded), counts=counts)
    elif status == "prefix":
        result.update(status="incomplete", reason="missing_eos")
    elif terminal and reason == "invalid_compact_prefix":
        result["reason"] = "invalid_compact_content"
    return _finish(result, loaded)


__all__ = ["CompactCatalogTokensError", "prepare_catalog_context_v1", "build_compact_catalog_token_codec_v1",
    "compact_catalog_token_codec_sha256", "encode_compact_catalog_tokens_v1",
    "compact_catalog_allowed_token_ids_v1", "decode_compact_catalog_tokens_v1"]

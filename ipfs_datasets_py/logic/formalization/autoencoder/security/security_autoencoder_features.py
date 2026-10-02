"""Versioned source projection for the frozen security advisory checkpoint.

The lexical projection reproduces the transferred modal token branch without
importing the modal trainer. Its complete semantics are inert package metadata.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import inspect
import json
import math
import re
import textwrap

FEATURE_SCHEMA = "python-ast-control-flow-features@1"
NODE_FEATURES = (
    "FunctionDef", "AsyncFunctionDef", "ClassDef", "Call", "Attribute", "Name",
    "Constant", "Return", "Raise", "If", "IfExp", "Compare", "BoolOp", "BinOp",
    "UnaryOp", "Assign", "AnnAssign", "AugAssign", "Subscript", "List", "Tuple",
    "Dict", "Set", "ListComp", "DictComp", "GeneratorExp", "For", "While",
    "Try", "ExceptHandler", "With", "Await", "Yield", "Assert", "Global",
    "Nonlocal", "Import", "ImportFrom", "Lambda", "Match",
)
FEATURES = NODE_FEATURES + ("literal_cr", "literal_lf", "literal_nul", "argument_count")
_STOPWORDS = {"a", "an", "and", "are", "as", "be", "by", "for", "in", "is", "of", "or",
              "shall", "that", "the", "to", "under"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
TOKENIZER = {"schema": "security-modal-lexical-projection@1", "pattern": "[a-z0-9]+",
    "lowercase": "str.lower", "minimum_token_length": 3, "stopwords": sorted(_STOPWORDS),
    "max_tokens": 40, "selection": "first filtered tokens, retaining duplicate counts",
    "embedding_input": "unique vocabulary indices, inverse-sqrt cardinality normalization"}


def _token_features(text: str, *, max_tokens: int = 40):
    if max_tokens <= 0:
        return []
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    ][:max_tokens]


def assert_native_tokenizer_compatible():
    """Export-time semantic check, deliberately independent of full-file drift."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as native
    def body(function):
        node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
        return ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
    if (body(native._token_features) != body(_token_features)
            or native._TOKEN_RE.pattern != _TOKEN_RE.pattern or native._TOKEN_RE.flags != _TOKEN_RE.flags
            or native._STOPWORDS != _STOPWORDS):
        raise ValueError("native tokenizer semantics do not match the portable projection")


def lexical_observation(text, keys):
    positions = {key: index for index, key in enumerate(keys)}
    tokens = _token_features(text)
    indices = sorted({positions["token:" + token] for token in tokens if "token:" + token in positions})
    matched = sum("token:" + token in positions for token in tokens)
    return {"lexical_indices": indices, "lexical_coverage": {"selected_tokens": len(tokens),
        "in_vocabulary_tokens": matched, "oov_tokens": len(tokens) - matched,
        "unique_matched_keys": len(indices), "token_window": 40}}


def source_features(sources, paths, *, keys, max_functions):
    from ..source_screening import (
        PlanningAnalysisSecretError, _contains_secret, _credential_path_reason,
    )
    rows, unsupported = [], []
    for path in paths:
        if _credential_path_reason(path) or _contains_secret(sources[path]):
            raise PlanningAnalysisSecretError("security inference input refused by native secret screen")
        if not path.endswith(".py"):
            unsupported.append({"path": path, "reason": "non_python_source"})
            continue
        try:
            text = sources[path].decode("utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeError, ValueError):
            unsupported.append({"path": path, "reason": "python_ast_unavailable"})
            continue
        def visit(node, prefix=""):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts = Counter(type(child).__name__ for child in ast.walk(node))
                literals = [child.value for child in ast.walk(node)
                            if isinstance(child, ast.Constant) and type(child.value) is str]
                values = [float(counts[name]) for name in NODE_FEATURES]
                values += [float(any(char in value for value in literals)) for char in ("\r", "\n", "\x00")]
                values += [float(len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs))]
                values = [math.log1p(value) for value in values]
                norm = math.sqrt(sum(value * value for value in values)) or 1.0
                values = [value / norm for value in values]
                identity = {"path": path, "symbol": prefix + node.name, "line": node.lineno,
                            "ast_sha256": hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()}
                rows.append({**identity, "row_id": hashlib.sha256(json.dumps(identity, sort_keys=True,
                    separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest(),
                    "features": values, **lexical_observation(ast.get_source_segment(text, node) or "", keys)})
                prefix += node.name + "."
                if len(rows) > max_functions:
                    raise ValueError("security inference function bound exceeded; source is not silently truncated")
            elif isinstance(node, ast.ClassDef):
                prefix += node.name + "."
            for child in ast.iter_child_nodes(node):
                visit(child, prefix)
        visit(tree)
    return rows, unsupported

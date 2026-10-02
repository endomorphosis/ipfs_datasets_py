"""Dual CIDv1 identities for semantic-index symbols.

Stable identity deliberately models a logical declaration, while version
identity models the extractor's normalized semantic projection of that exact
declaration.  Both delegate CID construction to ``software_contracts.content``.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
import base64
import math
import posixpath
import unicodedata
from typing import Any, Final

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured, validate_cid, validate_structured_value
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import SEMANTIC_INDEX_SCHEMA, SemanticIndexModelError, SymbolKind


STABLE_SYMBOL_ID_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-stable-symbol-id@1"
SYMBOL_VERSION_ID_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-symbol-version-id@2"
SYMBOL_VERSION_ID_SCHEMA_V1: Final[str] = "ipfs-datasets.software-contracts.semantic-symbol-version-id@1"
DEFAULT_EXTRACTOR_NAME: Final[str] = "python-cpython-ast"
DEFAULT_EXTRACTOR_VERSION: Final[str] = "1"


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SemanticIndexModelError(f"{name} must be nonempty trimmed NFC text")
    return value


def normalized_module_path(module_path: str) -> str:
    value = _text(module_path, "module_path").replace("\\", "/")
    value = posixpath.normpath(value)
    if value in {".", ".."} or value.startswith("../") or value.startswith("/"):
        raise SemanticIndexModelError("module_path must be repository-relative")
    return value


def normalized_symbol_kind(kind: SymbolKind | str) -> str:
    try:
        return SymbolKind(kind).value
    except (TypeError, ValueError) as exc:
        raise SemanticIndexModelError(f"unsupported symbol kind {kind!r}") from exc


def stable_symbol_identity_payload(*, repository_id: str, language: str, module_path: str, qualified_name: str, kind: SymbolKind | str, namespace: str) -> dict[str, Any]:
    """Return the complete, deliberately small stable-symbol identity input."""
    language = _text(language, "language")
    if language != "python":
        raise SemanticIndexModelError("stable symbol language must be python")
    return {"schema": STABLE_SYMBOL_ID_SCHEMA, "repository_id": _text(repository_id, "repository_id"), "language": language, "module_path": normalized_module_path(module_path), "qualified_name": _text(qualified_name, "qualified_name"), "kind": normalized_symbol_kind(kind), "namespace": _text(namespace, "namespace")}


def stable_symbol_id(repository_id: str, language: str, module_path: str, qualified_name: str, kind: SymbolKind | str, namespace: str) -> str:
    """Return stable logical CID; spans, source bytes, and bodies are absent."""
    return cid_for_structured(stable_symbol_identity_payload(repository_id=repository_id, language=language, module_path=module_path, qualified_name=qualified_name, kind=kind, namespace=namespace))


def normalize_ast(value: Any) -> Any:
    """Turn an AST or strict AST-shaped value into location-free DAG-JSON.

    CPython's ``ast`` nodes expose positions as attributes rather than child
    fields.  This routine removes every standard location attribute and keeps
    all semantic fields, including expression context and operator node types.
    """
    if isinstance(value, ast.AST):
        return {"_type": type(value).__name__, **{name: normalize_ast(getattr(value, name)) for name in value._fields}}
    if isinstance(value, Mapping):
        return {str(key): normalize_ast(item) for key, item in sorted(value.items()) if key not in {"lineno", "col_offset", "end_lineno", "end_col_offset"}}
    if isinstance(value, (list, tuple)):
        return [normalize_ast(item) for item in value]
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        # ``float.hex`` is exact, including negative zero, and does not depend
        # on a platform's decimal formatting choices.
        return {"$semantic_literal": "float", "value": _float_projection(value)}
    if type(value) is bytes:
        return {
            "$semantic_literal": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    if type(value) is complex:
        return {
            "$semantic_literal": "complex",
            "real": _float_projection(value.real),
            "imag": _float_projection(value.imag),
        }
    if value is Ellipsis:
        return {"$semantic_literal": "ellipsis"}
    raise SemanticIndexModelError(f"normalized AST rejects {type(value).__name__}")


def _float_projection(value: float) -> str:
    """Return a platform-independent, sign-preserving float projection.

    JSON cannot represent infinities, while Python AST constants can (for
    example ``ast.parse('x = 1e400')``).  The tags also retain negative zero,
    which is semantically distinct for durable identity.

    NaN has no source-level Python literal and is not a durable semantic
    value: unlike infinities and signed zero, it cannot participate in a
    deterministic identity projection.
    """
    if math.isnan(value):
        raise SemanticIndexModelError("normalized AST rejects NaN float literal")
    if math.isinf(value):
        return "+infinity" if value > 0 else "-infinity"
    return value.hex()


def _structured(value: Any, name: str) -> Any:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise SemanticIndexModelError(f"{name} must be strict DAG-JSON") from exc
    return value


def symbol_version_identity_payload(*, stable_id: str, normalized_ast: Any, signature: Mapping[str, Any] | None = None, decorators: Sequence[str] = (), annotations: Mapping[str, Any] | None = None, extractor_name: str = DEFAULT_EXTRACTOR_NAME, extractor_version: str = DEFAULT_EXTRACTOR_VERSION, semantic_index_schema: str = SEMANTIC_INDEX_SCHEMA, property_role: str | None = None) -> dict[str, Any]:
    """Return the normalized semantic projection bound by a version CID."""
    # Decorator application is ordered and repeated decorators are meaningful.
    # Do not treat this semantic sequence as a set.
    normalized_decorators = [_text(item, "decorator") for item in decorators]
    if property_role is not None:
        property_role = _text(property_role, "property_role")
    if semantic_index_schema != SEMANTIC_INDEX_SCHEMA:
        raise SemanticIndexModelError("unsupported semantic-index schema")
    try:
        stable_id = validate_cid(stable_id)
    except Exception as exc:
        raise SemanticIndexModelError("stable_id must be a valid CID") from exc
    payload = {"schema": SYMBOL_VERSION_ID_SCHEMA, "semantic_index_schema": semantic_index_schema, "extractor_name": _text(extractor_name, "extractor_name"), "extractor_version": _text(extractor_version, "extractor_version"), "stable_id": stable_id, "normalized_ast": normalize_ast(normalized_ast), "signature": dict(sorted((signature or {}).items())), "decorators": normalized_decorators, "property_role": property_role, "annotations": dict(sorted((annotations or {}).items()))}
    return _structured(payload, "version identity payload")


def symbol_version_cid(stable_id: str, normalized_ast: Any, signature: Mapping[str, Any] | None = None, decorators: Sequence[str] = (), annotations: Mapping[str, Any] | None = None, *, extractor_name: str = DEFAULT_EXTRACTOR_NAME, extractor_version: str = DEFAULT_EXTRACTOR_VERSION, semantic_index_schema: str = SEMANTIC_INDEX_SCHEMA, property_role: str | None = None) -> str:
    """Return the semantic version CID for exactly one stable symbol."""
    return cid_for_structured(symbol_version_identity_payload(stable_id=stable_id, normalized_ast=normalized_ast, signature=signature, decorators=decorators, annotations=annotations, extractor_name=extractor_name, extractor_version=extractor_version, semantic_index_schema=semantic_index_schema, property_role=property_role))

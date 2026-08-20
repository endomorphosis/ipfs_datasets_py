"""Stable O1 semantic public API for proof-grounded IR learning.

The package root is deliberately lazy.  Importing this module loads only the
discovery catalog.  Compilers, decompilers, split guards, proof stores, and
optional runtimes stay unloaded until an operation is called.

Operations:

* ``corpus`` / ``split`` / ``example`` — sealed data-plane records
* ``compile`` / ``decompile`` / ``translate`` — measured bidirectional surfaces
* ``pair`` / ``evaluate`` / ``verify`` / ``publish`` — curriculum and evidence

Every operation delegates to a single canonical owner.  This package does not
start a daemon, open a network connection, or spawn a prover process.
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from .catalog import (
    SEMANTIC_API_INTERFACE,
    SEMANTIC_API_SCHEMA_VERSION,
    SEMANTIC_API_TASK_ID,
    SEMANTIC_API_VERSION,
    SEMANTIC_OPERATION_NAMES,
    SemanticOperationSpec,
    discover_semantic_operations,
    semantic_api_manifest,
    semantic_operation_spec,
)

_OPERATION_EXPORTS: Final[tuple[str, ...]] = SEMANTIC_OPERATION_NAMES + (
    "SemanticAPIError",
    "canonical_owners",
    "compiler",
    "decompiler",
    "roundtrip",
)

_OWNER_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "CanonicalCompiler": (
        "ipfs_datasets_py.logic.legal_ir.canonical_compiler",
        "CanonicalCompiler",
    ),
    "CanonicalDecompiler": (
        "ipfs_datasets_py.logic.legal_ir.canonical_decompiler",
        "CanonicalDecompiler",
    ),
    "CanonicalSemanticRoundTrip": (
        "ipfs_datasets_py.logic.legal_ir.canonical_roundtrip",
        "CanonicalSemanticRoundTrip",
    ),
    "CompilerRequest": (
        "ipfs_datasets_py.logic.legal_ir.canonical_contracts",
        "CompilerRequest",
    ),
    "CorpusManifest": (
        "ipfs_datasets_py.logic.ir_core.source_lineage",
        "CorpusManifest",
    ),
    "DecompilerRequest": (
        "ipfs_datasets_py.logic.legal_ir.canonical_contracts",
        "DecompilerRequest",
    ),
    "IRHardNegative": (
        "ipfs_datasets_py.logic.formalization.training_examples",
        "IRHardNegative",
    ),
    "IRPositivePair": (
        "ipfs_datasets_py.logic.formalization.training_examples",
        "IRPositivePair",
    ),
    "IRTrainingExample": (
        "ipfs_datasets_py.logic.formalization.training_examples",
        "IRTrainingExample",
    ),
    "ProofCorpusStore": (
        "ipfs_datasets_py.logic.proof_corpus.store",
        "ProofCorpusStore",
    ),
    "SourceWithheldCanonicalDecompiler": (
        "ipfs_datasets_py.logic.legal_ir.canonical_decompiler",
        "SourceWithheldCanonicalDecompiler",
    ),
    "TypedDeonticCanonicalCompiler": (
        "ipfs_datasets_py.logic.legal_ir.canonical_compiler",
        "TypedDeonticCanonicalCompiler",
    ),
}


class SemanticAPI:
    """Versioned facade over the ten O1 operations.

    Methods are bound to the module-level delegates so ``SemanticAPI.compile``
    and :func:`compile` stay the same implementation.
    """

    interface: str = SEMANTIC_API_INTERFACE
    schema_version: str = SEMANTIC_API_SCHEMA_VERSION
    version: str = SEMANTIC_API_VERSION

    def operations(self) -> tuple[SemanticOperationSpec, ...]:
        return discover_semantic_operations()

    def manifest(self) -> dict[str, object]:
        return semantic_api_manifest()

    def corpus(self, value: object) -> Any:
        return __getattr__("corpus")(value)

    def split(self, value: object) -> Any:
        return __getattr__("split")(value)

    def example(self, value: object) -> Any:
        return __getattr__("example")(value)

    def compile(self, request: object, *, owner: Any | None = None) -> Any:
        return __getattr__("compile")(request, owner=owner)

    def decompile(self, request: object, *, owner: Any | None = None) -> Any:
        return __getattr__("decompile")(request, owner=owner)

    def translate(self, **kwargs: Any) -> Any:
        return __getattr__("translate")(**kwargs)

    def pair(self, value: object) -> Any:
        return __getattr__("pair")(value)

    def evaluate(self, request: object, *, owner: Any | None = None) -> Any:
        return __getattr__("evaluate")(request, owner=owner)

    def verify(
        self,
        payload: object,
        context: object | None = None,
        *,
        root: object | None = None,
    ) -> Any:
        return __getattr__("verify")(payload, context, root=root)

    def publish(self, store: object, value: object, **kwargs: Any) -> Any:
        return __getattr__("publish")(store, value, **kwargs)


def __getattr__(name: str) -> Any:
    """Load an operation or owner only when it is first accessed."""

    if name in _OPERATION_EXPORTS:
        module = importlib.import_module(".operations", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    owner = _OWNER_EXPORTS.get(name)
    if owner is not None:
        module_name, symbol = owner
        value = getattr(importlib.import_module(module_name), symbol)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted(
    (
        "SEMANTIC_API_INTERFACE",
        "SEMANTIC_API_SCHEMA_VERSION",
        "SEMANTIC_API_TASK_ID",
        "SEMANTIC_API_VERSION",
        "SEMANTIC_OPERATION_NAMES",
        "SemanticAPI",
        "SemanticAPIError",
        "SemanticOperationSpec",
        "canonical_owners",
        "compiler",
        "decompiler",
        "discover_semantic_operations",
        "roundtrip",
        "semantic_api_manifest",
        "semantic_operation_spec",
    )
    + SEMANTIC_OPERATION_NAMES
    + tuple(_OWNER_EXPORTS)
)

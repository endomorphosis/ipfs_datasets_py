"""Versioned discovery catalog for the O1 semantic public API.

This module is import-isolation critical: it must not load compilers,
decompilers, solvers, Hugging Face downloaders, or proof backends.  Callers
inspect :func:`discover_semantic_operations` and :func:`semantic_api_manifest`
to learn exact operation names, versions, and owning modules before invoking
any operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


SEMANTIC_API_INTERFACE: Final = "SemanticPublicAPI@1"
SEMANTIC_API_SCHEMA_VERSION: Final = "pgir-semantic-api/v1"
SEMANTIC_API_VERSION: Final = "1.0.0"
SEMANTIC_API_TASK_ID: Final = "PGIR-080"

SEMANTIC_OPERATION_NAMES: Final[tuple[str, ...]] = (
    "corpus",
    "split",
    "example",
    "compile",
    "decompile",
    "translate",
    "pair",
    "evaluate",
    "verify",
    "publish",
)


@dataclass(frozen=True, slots=True)
class SemanticOperationSpec:
    """One reviewed O1 operation and the canonical owner it must delegate to."""

    name: str
    version: str
    owner_module: str
    owner_symbol: str
    signature: str
    description: str
    import_side_effects: str = "none"

    def to_dict(self) -> dict[str, str]:
        return {
            "description": self.description,
            "import_side_effects": self.import_side_effects,
            "name": self.name,
            "owner_module": self.owner_module,
            "owner_symbol": self.owner_symbol,
            "signature": self.signature,
            "version": self.version,
        }


_OPERATIONS: Final[tuple[SemanticOperationSpec, ...]] = (
    SemanticOperationSpec(
        name="corpus",
        version="ir-corpus-manifest/v1",
        owner_module="ipfs_datasets_py.logic.ir_core.source_lineage",
        owner_symbol="CorpusManifest.from_dict",
        signature="corpus(value: CorpusManifest | Mapping[str, Any]) -> CorpusManifest",
        description=(
            "Load and validate a sealed corpus manifest. Source counts never "
            "include derivatives; rights remain fail-closed."
        ),
    ),
    SemanticOperationSpec(
        name="split",
        version="IRSplitManifest@1",
        owner_module="ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits",
        owner_symbol="LegalIRSplitManifest.from_mapping",
        signature="split(value: LegalIRSplitManifest | Mapping[str, Any]) -> LegalIRSplitManifest",
        description=(
            "Load and validate a lineage-safe multidimensional split manifest. "
            "Membership is immutable; leakage fails closed."
        ),
    ),
    SemanticOperationSpec(
        name="example",
        version="ir-training-example/v1",
        owner_module="ipfs_datasets_py.logic.formalization.training_examples",
        owner_symbol="validate_training_example",
        signature="example(value: IRTrainingExample | Mapping[str, Any]) -> IRTrainingExample",
        description=(
            "Admit one closed training-example record. Model output cannot "
            "silently become canonical or proof-grounded."
        ),
    ),
    SemanticOperationSpec(
        name="compile",
        version="CanonicalStructuredTextCompiler@1",
        owner_module="ipfs_datasets_py.logic.legal_ir.canonical_compiler",
        owner_symbol="TypedDeonticCanonicalCompiler.compile",
        signature="compile(request: CompilerRequest | Mapping[str, Any]) -> CompilerResult",
        description=(
            "Compile structured text to canonical IR through the measured "
            "TypedDeonticCanonicalCompiler authority."
        ),
    ),
    SemanticOperationSpec(
        name="decompile",
        version="SourceWithheldCanonicalParaphraser@1",
        owner_module="ipfs_datasets_py.logic.legal_ir.canonical_decompiler",
        owner_symbol="SourceWithheldCanonicalDecompiler.decompile",
        signature="decompile(request: DecompilerRequest | Mapping[str, Any]) -> DecompilerResult",
        description=(
            "Realize canonical IR without consulting originating source text "
            "through the selected source-withheld decompiler."
        ),
    ),
    SemanticOperationSpec(
        name="translate",
        version="CanonicalTranslationReceipt@1",
        owner_module="ipfs_datasets_py.logic.bridge.translation",
        owner_symbol="issue_translation_receipt",
        signature=(
            "translate(*, direction_id: str, source_cid: str, target_cid: str, "
            "**kwargs) -> TranslationReceipt"
        ),
        description=(
            "Issue a closed preservation-class translation receipt. Fidelity "
            "cannot increase without recompilation and semantic comparison."
        ),
    ),
    SemanticOperationSpec(
        name="pair",
        version="ir-positive-pair/v1",
        owner_module="ipfs_datasets_py.logic.formalization.training_examples",
        owner_symbol="IRPositivePair.from_dict",
        signature=(
            "pair(value: IRPositivePair | IRHardNegative | Mapping[str, Any]) "
            "-> IRPositivePair | IRHardNegative"
        ),
        description=(
            "Admit a verified positive pair or checked hard negative. Weaker "
            "equivalence classes cannot be trained as exact."
        ),
    ),
    SemanticOperationSpec(
        name="evaluate",
        version="CanonicalSemanticRoundTrip@1",
        owner_module="ipfs_datasets_py.logic.legal_ir.canonical_roundtrip",
        owner_symbol="CanonicalSemanticRoundTrip.run",
        signature=(
            "evaluate(request: CompilerRequest | Mapping[str, Any]) -> "
            "CanonicalSemanticRoundTripResult"
        ),
        description=(
            "Run the measured compile/decompile/recompile composition. Success "
            "is not a semantic-parity or promotion decision."
        ),
    ),
    SemanticOperationSpec(
        name="verify",
        version="AttestedProofVerifier@1",
        owner_module="ipfs_datasets_py.logic.proof_corpus.verifier",
        owner_symbol="verify_selected_item",
        signature=(
            "verify(payload, context=None, *, root=None) -> "
            "ItemVerificationResult | IntegrityReport"
        ),
        description=(
            "Independently verify selected proof evidence or artifact "
            "integrity. Producer claims never authorize."
        ),
    ),
    SemanticOperationSpec(
        name="publish",
        version="ProofCorpusStore@1",
        owner_module="ipfs_datasets_py.logic.proof_corpus.store",
        owner_symbol="put_envelope",
        signature="publish(store: ProofCorpusStore, value, **kwargs) -> ArtifactEnvelope",
        description=(
            "Append a content-addressed envelope to the proof corpus store. "
            "Publication is versioned and never overwrites an existing CID."
        ),
    ),
)

_OPERATIONS_BY_NAME: Final[Mapping[str, SemanticOperationSpec]] = MappingProxyType(
    {spec.name: spec for spec in _OPERATIONS}
)

if tuple(spec.name for spec in _OPERATIONS) != SEMANTIC_OPERATION_NAMES:
    raise RuntimeError("semantic operation catalog must match SEMANTIC_OPERATION_NAMES")


def semantic_operation_spec(name: str) -> SemanticOperationSpec:
    """Return the reviewed spec for one O1 operation."""

    try:
        return _OPERATIONS_BY_NAME[name]
    except KeyError as exc:
        raise KeyError(
            f"unknown semantic operation {name!r}; known operations are "
            f"{list(SEMANTIC_OPERATION_NAMES)}"
        ) from exc


def discover_semantic_operations() -> tuple[SemanticOperationSpec, ...]:
    """Return the closed, versioned O1 operation catalog."""

    return _OPERATIONS


def semantic_api_manifest() -> dict[str, object]:
    """Return the machine-readable discovery document for this API surface."""

    return {
        "import_side_effects": "none",
        "interface": SEMANTIC_API_INTERFACE,
        "operation_names": list(SEMANTIC_OPERATION_NAMES),
        "operations": [spec.to_dict() for spec in _OPERATIONS],
        "schema_version": SEMANTIC_API_SCHEMA_VERSION,
        "task_id": SEMANTIC_API_TASK_ID,
        "version": SEMANTIC_API_VERSION,
    }


__all__ = [
    "SEMANTIC_API_INTERFACE",
    "SEMANTIC_API_SCHEMA_VERSION",
    "SEMANTIC_API_TASK_ID",
    "SEMANTIC_API_VERSION",
    "SEMANTIC_OPERATION_NAMES",
    "SemanticOperationSpec",
    "discover_semantic_operations",
    "semantic_api_manifest",
    "semantic_operation_spec",
]

"""Closed translation-preservation contracts for the canonical decompiler.

PGIR-022 attaches exactly one preservation class to every translation and
keeps reconstruction modes distinct from fidelity.  Style paraphrase and
heuristic translations never become semantic or proof authority.  Fidelity
requires recompilation plus semantic comparison.  Undeclared loss is rejected.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalContractError
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json, validate_cid


TRANSLATION_PRESERVATION_INTERFACE: Final = "CanonicalTranslationPreservation@1"
TRANSLATION_RECEIPT_INTERFACE: Final = "CanonicalTranslationReceipt@1"
TRANSLATION_RECEIPT_SCHEMA: Final = "ipfs-datasets.canonical-translation-receipt.v1"
TRANSLATION_DIRECTION_CATALOG_INTERFACE: Final = "CanonicalTranslationDirectionCatalog@1"
TRANSLATION_DIRECTION_CATALOG_SCHEMA: Final = (
    "ipfs-datasets.canonical-translation-direction-catalog.v1"
)

CLOSED_PRESERVATION_CLASSES: Final = (
    "lossless",
    "equisatisfiable",
    "over_approximation",
    "under_approximation",
    "heuristic",
    "unsupported",
)
CLOSED_RECONSTRUCTION_MODES: Final = (
    "controlled_semantic_reconstruction",
    "structural_review",
    "style_paraphrase",
)
CLOSED_EQUALITY_CRITERIA: Final = (
    "exact_ir_cid",
    "canonical_rule_set",
    "ast_identity",
    "graph_identity",
    "source_span",
    "semantic_recompile",
    "proof",
    "unsupported",
)
CLOSED_FIDELITY_CLAIMS: Final = ("none", "candidate", "semantic", "proof")
CLOSED_DIRECTION_CLASSES: Final = (
    "source",
    "typed",
    "bridge",
    "family",
    "prover",
    "cnl",
    "trace",
)


class TranslationPreservationClass(str, Enum):
    """Closed semantic-preservation class attached to one translation."""

    LOSSLESS = "lossless"
    EQUISATISFIABLE = "equisatisfiable"
    OVER_APPROXIMATION = "over_approximation"
    UNDER_APPROXIMATION = "under_approximation"
    HEURISTIC = "heuristic"
    UNSUPPORTED = "unsupported"


class ReconstructionMode(str, Enum):
    """How a decompiler realizes or reviews an IR.

    These modes are not interchangeable.  Controlled reconstruction may become
    a semantic candidate after the recompilation gate.  Structural review is
    never prose.  Style paraphrase is never fidelity by itself.
    """

    CONTROLLED_SEMANTIC = "controlled_semantic_reconstruction"
    STRUCTURAL_REVIEW = "structural_review"
    STYLE_PARAPHRASE = "style_paraphrase"


class EqualityCriterion(str, Enum):
    """Recorded criterion used to compare a translation pair."""

    EXACT_IR_CID = "exact_ir_cid"
    CANONICAL_RULE_SET = "canonical_rule_set"
    AST_IDENTITY = "ast_identity"
    GRAPH_IDENTITY = "graph_identity"
    SOURCE_SPAN = "source_span"
    SEMANTIC_RECOMPILE = "semantic_recompile"
    PROOF = "proof"
    UNSUPPORTED = "unsupported"


class FidelityClaim(str, Enum):
    """Authority attached to a translation.  Never silently increased."""

    NONE = "none"
    CANDIDATE = "candidate"
    SEMANTIC = "semantic"
    PROOF = "proof"


def _enum(value: object, enum_type: type[Enum], field: str) -> Enum:
    try:
        if isinstance(value, enum_type):
            return value
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(f"{field} is not a closed {enum_type.__name__}") from exc


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalContractError(f"{field} must be a nonblank string")
    return value


def _optional_dag_cid(value: object, field: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_cid(value, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(f"{field} must be a canonical dag-json CIDv1") from exc


def _required_cid(value: object, field: str, *, codec: str) -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(f"{field} must be a canonical {codec} CIDv1") from exc


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError(f"{field} must be a string array")
    items: list[str] = []
    for index, item in enumerate(value):
        text = _nonblank(item, f"{field}[{index}]")
        if text not in items:
            items.append(text)
    return tuple(items)


def _criteria(value: object) -> tuple[EqualityCriterion, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("equality_criteria must be an array")
    items: list[EqualityCriterion] = []
    for index, item in enumerate(value):
        criterion = _enum(item, EqualityCriterion, f"equality_criteria[{index}]")
        assert isinstance(criterion, EqualityCriterion)
        if criterion not in items:
            items.append(criterion)
    return tuple(items)


def _frozen_details(value: object) -> Mapping[str, object]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise CanonicalContractError("details must be an object")
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CanonicalContractError("details keys must be strings")
        if isinstance(item, Mapping):
            frozen[key] = dict(item)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            frozen[key] = list(item)
        else:
            frozen[key] = item
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class TranslationDirectionSpec:
    """One required round-trip direction with a declared default class."""

    direction_id: str
    direction_class: str
    source_schema: str
    target_schema: str
    reconstruction_mode: ReconstructionMode
    default_preservation_class: TranslationPreservationClass
    equality_criteria: tuple[EqualityCriterion, ...]
    notes: str
    inverse_direction_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction_id", _nonblank(self.direction_id, "direction_id"))
        if self.direction_class not in CLOSED_DIRECTION_CLASSES:
            raise CanonicalContractError("direction_class is outside the closed A4 catalog")
        object.__setattr__(self, "source_schema", _nonblank(self.source_schema, "source_schema"))
        object.__setattr__(self, "target_schema", _nonblank(self.target_schema, "target_schema"))
        object.__setattr__(
            self,
            "reconstruction_mode",
            _enum(self.reconstruction_mode, ReconstructionMode, "reconstruction_mode"),
        )
        object.__setattr__(
            self,
            "default_preservation_class",
            _enum(
                self.default_preservation_class,
                TranslationPreservationClass,
                "default_preservation_class",
            ),
        )
        criteria = _criteria(self.equality_criteria)
        if not criteria:
            raise CanonicalContractError("every direction must record at least one equality criterion")
        object.__setattr__(self, "equality_criteria", criteria)
        object.__setattr__(self, "notes", _nonblank(self.notes, "notes"))
        if self.inverse_direction_id:
            object.__setattr__(
                self,
                "inverse_direction_id",
                _nonblank(self.inverse_direction_id, "inverse_direction_id"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "default_preservation_class": self.default_preservation_class.value,
            "direction_class": self.direction_class,
            "direction_id": self.direction_id,
            "equality_criteria": [item.value for item in self.equality_criteria],
            "inverse_direction_id": self.inverse_direction_id,
            "notes": self.notes,
            "reconstruction_mode": self.reconstruction_mode.value,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
        }


def _direction(
    direction_id: str,
    direction_class: str,
    source_schema: str,
    target_schema: str,
    reconstruction_mode: ReconstructionMode,
    default_preservation_class: TranslationPreservationClass,
    equality_criteria: tuple[EqualityCriterion, ...],
    notes: str,
    inverse_direction_id: str = "",
) -> TranslationDirectionSpec:
    return TranslationDirectionSpec(
        direction_id=direction_id,
        direction_class=direction_class,
        source_schema=source_schema,
        target_schema=target_schema,
        reconstruction_mode=reconstruction_mode,
        default_preservation_class=default_preservation_class,
        equality_criteria=equality_criteria,
        notes=notes,
        inverse_direction_id=inverse_direction_id,
    )


_DIRECTION_CATALOG: Final[tuple[TranslationDirectionSpec, ...]] = (
    _direction(
        "A4-TYPED-002",
        "typed",
        "bridge.canonical_roundtrip_ir",
        "typed.legal_norm_ir",
        ReconstructionMode.STRUCTURAL_REVIEW,
        TranslationPreservationClass.UNSUPPORTED,
        (EqualityCriterion.UNSUPPORTED,),
        "No reviewed typed inverse of CanonicalRoundTripIR exists; the path is unsupported.",
        inverse_direction_id="A4-TYPED-001",
    ),
    _direction(
        "A4-TYPED-004",
        "typed",
        "typed.formalization_artifact",
        "typed.domain_declarations",
        ReconstructionMode.STRUCTURAL_REVIEW,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.UNSUPPORTED, EqualityCriterion.CANONICAL_RULE_SET),
        "Intent emits a semantic review, not source or declaration regeneration.",
        inverse_direction_id="A4-TYPED-003",
    ),
    _direction(
        "A4-FAMILY-001",
        "family",
        "family.tdfol",
        "family.dcec",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.AST_IDENTITY, EqualityCriterion.SEMANTIC_RECOMPILE),
        "TDFOLToDCECConverter is a family component, not semantic-preservation authority.",
        inverse_direction_id="A4-FAMILY-002",
    ),
    _direction(
        "A4-FAMILY-002",
        "family",
        "family.dcec",
        "family.tdfol",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.AST_IDENTITY, EqualityCriterion.SEMANTIC_RECOMPILE),
        "Bidirectional availability does not establish semantic equivalence.",
        inverse_direction_id="A4-FAMILY-001",
    ),
    _direction(
        "A4-FAMILY-003",
        "family",
        "family.tdfol",
        "family.fol",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.UNSUPPORTED,),
        "FOL/TPTP projections are inventory-classified as lossy or heuristic.",
    ),
    _direction(
        "A4-PROVER-001",
        "prover",
        "prover.hammer_term",
        "prover.smtlib2_subset",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.LOSSLESS,
        (EqualityCriterion.AST_IDENTITY,),
        "Supported first-order subset is structurally lossless; unsupported constructs fail closed.",
        inverse_direction_id="A4-PROVER-002",
    ),
    _direction(
        "A4-PROVER-002",
        "prover",
        "prover.smtlib2_subset",
        "prover.hammer_term",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.LOSSLESS,
        (EqualityCriterion.AST_IDENTITY,),
        "Parser accepts the subset emitted by the hammer codec, not arbitrary SMT-LIB2.",
        inverse_direction_id="A4-PROVER-001",
    ),
    _direction(
        "A4-PROVER-003",
        "prover",
        "prover.hammer_term",
        "prover.tptp_tff_subset",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.LOSSLESS,
        (EqualityCriterion.AST_IDENTITY,),
        "Typed first-order fragment admitted by hammers.translation is structurally lossless.",
        inverse_direction_id="A4-PROVER-004",
    ),
    _direction(
        "A4-PROVER-004",
        "prover",
        "prover.tptp_tff_subset",
        "prover.hammer_term",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.LOSSLESS,
        (EqualityCriterion.AST_IDENTITY,),
        "Inverse TFF parser is bounded to the emitted subset.",
        inverse_direction_id="A4-PROVER-003",
    ),
    _direction(
        "A4-CNL-001",
        "cnl",
        "bridge.canonical_roundtrip_ir",
        "cnl.controlled_legal_text",
        ReconstructionMode.STYLE_PARAPHRASE,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.SEMANTIC_RECOMPILE, EqualityCriterion.EXACT_IR_CID),
        "Source-withheld controlled paraphrase; fidelity requires recompilation and comparison.",
        inverse_direction_id="A4-CNL-002",
    ),
    _direction(
        "A4-CNL-002",
        "cnl",
        "cnl.controlled_legal_text",
        "bridge.canonical_roundtrip_ir",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.SEMANTIC_RECOMPILE, EqualityCriterion.EXACT_IR_CID),
        "Recompilation remains the only semantic inverse of controlled text.",
        inverse_direction_id="A4-CNL-001",
    ),
    _direction(
        "A4-CNL-003",
        "cnl",
        "typed.legal_norm_ir",
        "cnl.controlled_legal_text",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.SEMANTIC_RECOMPILE,),
        "Deontic is slot-grounded; Modal is source-bearing; Intent is structural review, not CNL.",
        inverse_direction_id="A4-CNL-004",
    ),
    _direction(
        "A4-CNL-004",
        "cnl",
        "cnl.controlled_legal_text",
        "typed.legal_norm_ir",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (EqualityCriterion.SEMANTIC_RECOMPILE, EqualityCriterion.UNSUPPORTED),
        "Parsing is family-specific; no shared CNL grammar is semantic authority.",
        inverse_direction_id="A4-CNL-003",
    ),
    _direction(
        "PGIR-022-IR-CYCLE",
        "cnl",
        "bridge.canonical_roundtrip_ir",
        "bridge.canonical_roundtrip_ir",
        ReconstructionMode.CONTROLLED_SEMANTIC,
        TranslationPreservationClass.HEURISTIC,
        (
            EqualityCriterion.SEMANTIC_RECOMPILE,
            EqualityCriterion.EXACT_IR_CID,
            EqualityCriterion.CANONICAL_RULE_SET,
        ),
        "IR to controlled text to IR.  Lossless only after the semantic recompilation gate.",
    ),
    _direction(
        "PGIR-022-STRUCTURAL-REVIEW",
        "trace",
        "bridge.canonical_roundtrip_ir",
        "trace.structural_review",
        ReconstructionMode.STRUCTURAL_REVIEW,
        TranslationPreservationClass.LOSSLESS,
        (EqualityCriterion.CANONICAL_RULE_SET, EqualityCriterion.EXACT_IR_CID),
        "Facet inventory of the IR.  Review is not a prose realization and claims no source fidelity.",
    ),
)


_DIRECTIONS_BY_ID: Final[Mapping[str, TranslationDirectionSpec]] = MappingProxyType(
    {item.direction_id: item for item in _DIRECTION_CATALOG}
)


def translation_direction_catalog() -> tuple[TranslationDirectionSpec, ...]:
    """Return the closed catalog of required round-trip directions."""

    return _DIRECTION_CATALOG


def translation_direction(direction_id: str) -> TranslationDirectionSpec:
    """Return one required direction or raise."""

    try:
        return _DIRECTIONS_BY_ID[direction_id]
    except KeyError as exc:
        raise CanonicalContractError(
            f"unknown translation direction {direction_id!r}; undeclared directions are rejected"
        ) from exc


def recorded_roundtrip_directions() -> tuple[str, ...]:
    """Return every required direction id in catalog order."""

    return tuple(item.direction_id for item in _DIRECTION_CATALOG)


def recorded_equality_criteria() -> tuple[str, ...]:
    """Return the closed equality-criterion vocabulary."""

    return CLOSED_EQUALITY_CRITERIA


def _direction_catalog_payload() -> dict[str, object]:
    return {
        "direction_count": len(_DIRECTION_CATALOG),
        "directions": [item.to_dict() for item in _DIRECTION_CATALOG],
        "equality_criteria": list(CLOSED_EQUALITY_CRITERIA),
        "fidelity_claims": list(CLOSED_FIDELITY_CLAIMS),
        "interface": TRANSLATION_DIRECTION_CATALOG_INTERFACE,
        "preservation_classes": list(CLOSED_PRESERVATION_CLASSES),
        "reconstruction_modes": list(CLOSED_RECONSTRUCTION_MODES),
        "schema_version": TRANSLATION_DIRECTION_CATALOG_SCHEMA,
    }


TRANSLATION_DIRECTION_CATALOG_CID: Final = cid_for_dag_json(_direction_catalog_payload())


def translation_direction_catalog_document() -> dict[str, object]:
    """Return a detached CID-bound copy of the direction catalog."""

    payload = _direction_catalog_payload()
    return {**payload, "catalog_cid": TRANSLATION_DIRECTION_CATALOG_CID}


def preservation_class_may_claim(
    preservation_class: TranslationPreservationClass,
    fidelity_claim: FidelityClaim,
) -> bool:
    """Return whether a closed class may carry a fidelity claim."""

    if fidelity_claim is FidelityClaim.NONE:
        return True
    if preservation_class is TranslationPreservationClass.UNSUPPORTED:
        return False
    if fidelity_claim is FidelityClaim.CANDIDATE:
        return preservation_class is not TranslationPreservationClass.UNSUPPORTED
    if fidelity_claim is FidelityClaim.SEMANTIC:
        return preservation_class in {
            TranslationPreservationClass.LOSSLESS,
            TranslationPreservationClass.EQUISATISFIABLE,
        }
    if fidelity_claim is FidelityClaim.PROOF:
        return preservation_class in {
            TranslationPreservationClass.LOSSLESS,
            TranslationPreservationClass.EQUISATISFIABLE,
        }
    return False


def reconstruction_mode_may_claim(
    reconstruction_mode: ReconstructionMode,
    fidelity_claim: FidelityClaim,
    *,
    recompilation_cid: str | None,
    semantic_comparison_cid: str | None,
) -> bool:
    """Return whether a reconstruction mode may claim the requested fidelity."""

    if fidelity_claim is FidelityClaim.NONE:
        return True
    if reconstruction_mode is ReconstructionMode.STRUCTURAL_REVIEW:
        return fidelity_claim is FidelityClaim.NONE
    if reconstruction_mode is ReconstructionMode.STYLE_PARAPHRASE:
        if fidelity_claim is FidelityClaim.PROOF:
            return False
        if fidelity_claim is FidelityClaim.SEMANTIC:
            return recompilation_cid is not None and semantic_comparison_cid is not None
        return fidelity_claim is FidelityClaim.CANDIDATE
    if reconstruction_mode is ReconstructionMode.CONTROLLED_SEMANTIC:
        if fidelity_claim is FidelityClaim.PROOF:
            return False
        if fidelity_claim is FidelityClaim.SEMANTIC:
            return recompilation_cid is not None and semantic_comparison_cid is not None
        return True
    return False


@dataclass(frozen=True, slots=True)
class TranslationReceipt:
    """CID-bound receipt for one translation with a closed preservation class."""

    direction_id: str
    source_schema: str
    target_schema: str
    reconstruction_mode: ReconstructionMode
    preservation_class: TranslationPreservationClass
    equality_criteria: tuple[EqualityCriterion, ...]
    fidelity_claim: FidelityClaim
    source_cid: str
    target_cid: str
    declared_loss: tuple[str, ...] = ()
    recompilation_cid: str | None = None
    semantic_comparison_cid: str | None = None
    proof_evidence_cid: str | None = None
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        spec = translation_direction(self.direction_id)
        object.__setattr__(self, "source_schema", _nonblank(self.source_schema, "source_schema"))
        object.__setattr__(self, "target_schema", _nonblank(self.target_schema, "target_schema"))
        if (
            self.source_schema != spec.source_schema
            or self.target_schema != spec.target_schema
        ):
            raise CanonicalContractError(
                "receipt schemas must match the declared direction; silent aliasing is rejected"
            )
        object.__setattr__(
            self,
            "reconstruction_mode",
            _enum(self.reconstruction_mode, ReconstructionMode, "reconstruction_mode"),
        )
        object.__setattr__(
            self,
            "preservation_class",
            _enum(
                self.preservation_class,
                TranslationPreservationClass,
                "preservation_class",
            ),
        )
        object.__setattr__(
            self,
            "fidelity_claim",
            _enum(self.fidelity_claim, FidelityClaim, "fidelity_claim"),
        )
        criteria = _criteria(self.equality_criteria)
        if not criteria:
            raise CanonicalContractError("translation receipt must record equality criteria")
        object.__setattr__(self, "equality_criteria", criteria)
        try:
            object.__setattr__(
                self,
                "source_cid",
                validate_cid(self.source_cid, codecs=("dag-json", "raw")),
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalContractError("source_cid must be a canonical CIDv1") from exc
        try:
            object.__setattr__(
                self,
                "target_cid",
                validate_cid(self.target_cid, codecs=("dag-json", "raw")),
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalContractError("target_cid must be a canonical CIDv1") from exc
        object.__setattr__(self, "declared_loss", _string_tuple(self.declared_loss, "declared_loss"))
        object.__setattr__(
            self,
            "recompilation_cid",
            _optional_dag_cid(self.recompilation_cid, "recompilation_cid"),
        )
        object.__setattr__(
            self,
            "semantic_comparison_cid",
            _optional_dag_cid(self.semantic_comparison_cid, "semantic_comparison_cid"),
        )
        object.__setattr__(
            self,
            "proof_evidence_cid",
            _optional_dag_cid(self.proof_evidence_cid, "proof_evidence_cid"),
        )
        object.__setattr__(self, "details", _frozen_details(self.details))
        self._reject_undeclared_authority()

    def _reject_undeclared_authority(self) -> None:
        if not preservation_class_may_claim(self.preservation_class, self.fidelity_claim):
            raise CanonicalContractError(
                f"{self.preservation_class.value} cannot carry {self.fidelity_claim.value} fidelity"
            )
        if not reconstruction_mode_may_claim(
            self.reconstruction_mode,
            self.fidelity_claim,
            recompilation_cid=self.recompilation_cid,
            semantic_comparison_cid=self.semantic_comparison_cid,
        ):
            raise CanonicalContractError(
                "paraphrase or reconstruction cannot claim fidelity without "
                "recompilation and semantic comparison"
            )
        if (
            self.preservation_class is TranslationPreservationClass.LOSSLESS
            and self.declared_loss
        ):
            raise CanonicalContractError("lossless translations cannot declare residual loss")
        if self.preservation_class is TranslationPreservationClass.LOSSLESS and not (
            EqualityCriterion.EXACT_IR_CID in self.equality_criteria
            or EqualityCriterion.AST_IDENTITY in self.equality_criteria
            or EqualityCriterion.CANONICAL_RULE_SET in self.equality_criteria
        ):
            raise CanonicalContractError(
                "lossless translations require an exact IR, AST, or canonical-rule criterion"
            )
        if self.preservation_class in {
            TranslationPreservationClass.OVER_APPROXIMATION,
            TranslationPreservationClass.UNDER_APPROXIMATION,
            TranslationPreservationClass.HEURISTIC,
        } and not self.declared_loss:
            raise CanonicalContractError(
                f"{self.preservation_class.value} translations must declare residual loss"
            )
        if (
            self.preservation_class is TranslationPreservationClass.UNSUPPORTED
            and self.fidelity_claim is not FidelityClaim.NONE
        ):
            raise CanonicalContractError("unsupported translations cannot claim fidelity")
        if self.fidelity_claim is FidelityClaim.PROOF and self.proof_evidence_cid is None:
            raise CanonicalContractError(
                "proof fidelity requires independently checked proof evidence"
            )
        if (
            self.fidelity_claim is FidelityClaim.PROOF
            and EqualityCriterion.PROOF not in self.equality_criteria
        ):
            raise CanonicalContractError("proof fidelity requires the proof equality criterion")
        if (
            self.reconstruction_mode is ReconstructionMode.STYLE_PARAPHRASE
            and self.fidelity_claim is FidelityClaim.SEMANTIC
            and EqualityCriterion.SEMANTIC_RECOMPILE not in self.equality_criteria
        ):
            raise CanonicalContractError(
                "paraphrase fidelity requires the semantic-recompile criterion"
            )
        if self.preservation_class is TranslationPreservationClass.EQUISATISFIABLE and (
            self.fidelity_claim is FidelityClaim.PROOF and self.proof_evidence_cid is None
        ):
            raise CanonicalContractError("equisatisfiable proof claims require proof evidence")

    @property
    def authority_increase(self) -> bool:
        """Translations never increase semantic or proof authority."""

        return False

    def identity_payload(self) -> dict[str, object]:
        return {
            "authority_increase": False,
            "declared_loss": list(self.declared_loss),
            "details": dict(self.details),
            "direction_id": self.direction_id,
            "equality_criteria": [item.value for item in self.equality_criteria],
            "fidelity_claim": self.fidelity_claim.value,
            "interface": TRANSLATION_RECEIPT_INTERFACE,
            "preservation_class": self.preservation_class.value,
            "proof_authority": False,
            "proof_evidence_cid": self.proof_evidence_cid,
            "recompilation_cid": self.recompilation_cid,
            "reconstruction_mode": self.reconstruction_mode.value,
            "schema_version": TRANSLATION_RECEIPT_SCHEMA,
            "semantic_comparison_cid": self.semantic_comparison_cid,
            "source_cid": self.source_cid,
            "source_schema": self.source_schema,
            "target_cid": self.target_cid,
            "target_schema": self.target_schema,
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "receipt_cid": self.receipt_cid,
            "receipt_cid_codec": "dag-json",
            "receipt_cid_scope": "identity_payload",
        }

    @classmethod
    def from_dict(cls, value: object) -> "TranslationReceipt":
        if not isinstance(value, Mapping):
            raise CanonicalContractError("translation receipt must be an object")
        expected = {
            "authority_increase",
            "declared_loss",
            "details",
            "direction_id",
            "equality_criteria",
            "fidelity_claim",
            "interface",
            "preservation_class",
            "proof_authority",
            "proof_evidence_cid",
            "receipt_cid",
            "receipt_cid_codec",
            "receipt_cid_scope",
            "recompilation_cid",
            "reconstruction_mode",
            "schema_version",
            "semantic_comparison_cid",
            "source_cid",
            "source_schema",
            "target_cid",
            "target_schema",
        }
        if set(value) != expected:
            raise CanonicalContractError("translation receipt fields changed")
        if value["interface"] != TRANSLATION_RECEIPT_INTERFACE:
            raise CanonicalContractError("translation receipt interface changed")
        if value["schema_version"] != TRANSLATION_RECEIPT_SCHEMA:
            raise CanonicalContractError("translation receipt schema changed")
        if value["authority_increase"] is not False or value["proof_authority"] is not False:
            raise CanonicalContractError("translation receipt cannot increase authority")
        if (
            value["receipt_cid_codec"] != "dag-json"
            or value["receipt_cid_scope"] != "identity_payload"
        ):
            raise CanonicalContractError("translation receipt CID contract changed")
        receipt = cls(
            direction_id=value["direction_id"],  # type: ignore[arg-type]
            source_schema=value["source_schema"],  # type: ignore[arg-type]
            target_schema=value["target_schema"],  # type: ignore[arg-type]
            reconstruction_mode=value["reconstruction_mode"],  # type: ignore[arg-type]
            preservation_class=value["preservation_class"],  # type: ignore[arg-type]
            equality_criteria=tuple(value["equality_criteria"]),  # type: ignore[arg-type]
            fidelity_claim=value["fidelity_claim"],  # type: ignore[arg-type]
            source_cid=value["source_cid"],  # type: ignore[arg-type]
            target_cid=value["target_cid"],  # type: ignore[arg-type]
            declared_loss=tuple(value["declared_loss"]),  # type: ignore[arg-type]
            recompilation_cid=value["recompilation_cid"],  # type: ignore[arg-type]
            semantic_comparison_cid=value["semantic_comparison_cid"],  # type: ignore[arg-type]
            proof_evidence_cid=value["proof_evidence_cid"],  # type: ignore[arg-type]
            details=value["details"],  # type: ignore[arg-type]
        )
        supplied = _required_cid(value["receipt_cid"], "receipt_cid", codec="dag-json")
        if supplied != receipt.receipt_cid:
            raise CanonicalContractError("receipt_cid does not match translation receipt")
        return receipt


def issue_translation_receipt(
    *,
    direction_id: str,
    reconstruction_mode: ReconstructionMode | str,
    preservation_class: TranslationPreservationClass | str,
    fidelity_claim: FidelityClaim | str,
    source_cid: str,
    target_cid: str,
    equality_criteria: Sequence[EqualityCriterion | str] | None = None,
    declared_loss: Sequence[str] = (),
    recompilation_cid: str | None = None,
    semantic_comparison_cid: str | None = None,
    proof_evidence_cid: str | None = None,
    details: Mapping[str, object] | None = None,
) -> TranslationReceipt:
    """Build a fail-closed translation receipt for a catalogued direction."""

    spec = translation_direction(direction_id)
    return TranslationReceipt(
        direction_id=spec.direction_id,
        source_schema=spec.source_schema,
        target_schema=spec.target_schema,
        reconstruction_mode=reconstruction_mode,  # type: ignore[arg-type]
        preservation_class=preservation_class,  # type: ignore[arg-type]
        equality_criteria=tuple(equality_criteria or spec.equality_criteria),
        fidelity_claim=fidelity_claim,  # type: ignore[arg-type]
        source_cid=source_cid,
        target_cid=target_cid,
        declared_loss=tuple(declared_loss),
        recompilation_cid=recompilation_cid,
        semantic_comparison_cid=semantic_comparison_cid,
        proof_evidence_cid=proof_evidence_cid,
        details={} if details is None else details,
    )


def catalog_default_receipt(
    direction_id: str,
    *,
    source_cid: str,
    target_cid: str,
    declared_loss: Sequence[str] = (),
    details: Mapping[str, object] | None = None,
) -> TranslationReceipt:
    """Issue the catalog default for a direction without increasing authority."""

    spec = translation_direction(direction_id)
    loss = tuple(declared_loss)
    if (
        spec.default_preservation_class
        in {
            TranslationPreservationClass.HEURISTIC,
            TranslationPreservationClass.OVER_APPROXIMATION,
            TranslationPreservationClass.UNDER_APPROXIMATION,
        }
        and not loss
    ):
        loss = ("undeclared_family_or_surface_loss",)
    fidelity = FidelityClaim.NONE
    if spec.default_preservation_class is TranslationPreservationClass.LOSSLESS:
        fidelity = FidelityClaim.NONE
    return issue_translation_receipt(
        direction_id=direction_id,
        reconstruction_mode=spec.reconstruction_mode,
        preservation_class=spec.default_preservation_class,
        fidelity_claim=fidelity,
        source_cid=source_cid,
        target_cid=target_cid,
        declared_loss=loss,
        details=details,
    )


__all__ = [
    "CLOSED_DIRECTION_CLASSES",
    "CLOSED_EQUALITY_CRITERIA",
    "CLOSED_FIDELITY_CLAIMS",
    "CLOSED_PRESERVATION_CLASSES",
    "CLOSED_RECONSTRUCTION_MODES",
    "EqualityCriterion",
    "FidelityClaim",
    "ReconstructionMode",
    "TRANSLATION_DIRECTION_CATALOG_CID",
    "TRANSLATION_DIRECTION_CATALOG_INTERFACE",
    "TRANSLATION_DIRECTION_CATALOG_SCHEMA",
    "TRANSLATION_PRESERVATION_INTERFACE",
    "TRANSLATION_RECEIPT_INTERFACE",
    "TRANSLATION_RECEIPT_SCHEMA",
    "TranslationDirectionSpec",
    "TranslationPreservationClass",
    "TranslationReceipt",
    "catalog_default_receipt",
    "issue_translation_receipt",
    "preservation_class_may_claim",
    "recorded_equality_criteria",
    "recorded_roundtrip_directions",
    "reconstruction_mode_may_claim",
    "translation_direction",
    "translation_direction_catalog",
    "translation_direction_catalog_document",
]

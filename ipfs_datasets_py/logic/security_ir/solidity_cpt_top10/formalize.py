"""Formalize Solidity Security IR candidates into exact obligations.

This module compiles declaration-only candidates into
:class:`SolidityFormalizationRecord` values that bind:

* exact source spans;
* graph / source / config / partition CIDs;
* semantic prerequisites and unsupported frontiers;
* logic family; and
* candidate authority.

Every :class:`~...ir_core.claims.ProofObligation` is a **property to check**.
Generating an obligation does not establish that the property holds, does not
import solver results into features, and does not grant proof authority.

Retrieved premises remain ``context_only`` assumptions with
``proof_authority=False``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ...formalization.views import FormalFormula, FormalizationView, ViewRegistry
from ...ir_core.claims import Assumption, ProofObligation
from ...ir_core.identity import canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from ..formalization_adapter import (
    SECURITY_IR_CLAIM_VIEW_ID,
    SECURITY_IR_POLICY_VIEW_ID,
    SECURITY_IR_THREAT_VIEW_ID,
    SecurityIRFormalizationAdapter,
)
from ..model import SecurityIR
from .adapter import (
    AdapterDisposition,
    CandidateAuthority,
    RetrievedPremise,
    SolidityAdapterError,
    SolidityAdapterResult,
    SoliditySecurityIRAdapter,
)
from .graph import SoliditySecurityGraph


SOLIDITY_FORMALIZE_VERSION: Final = "solidity-cpt-formalize/v1"
SOLIDITY_FORMALIZE_PRODUCER: Final = "solidity-cpt-top10-formalizer"
SOLIDITY_FORMALIZE_IDENTITY_DOMAIN: Final = (
    "solidity-cpt-security-ir/formalization-record"
)
SOLIDITY_LOGIC_FAMILY_CANDIDATE: Final = "solidity_verification_condition"
SOLIDITY_LOGIC_FAMILY_UNSUPPORTED: Final = "unsupported"

_RESULT_KEYS: Final = frozenset(
    {
        "counterexample",
        "disproof_vectors",
        "evaluation_label",
        "model_score",
        "runtime_traces",
        "solver_result",
        "solver_results",
        "solver_verdict",
        "trace",
    }
)


class SolidityFormalizeError(ValueError):
    """Raised when a Solidity candidate cannot be formalized safely."""


class FormalizationStatus(str, Enum):
    """Terminal formalization status without implying proof success."""

    FORMALIZED = "formalized"
    ABSTAINED = "abstained"
    PARTIAL = "partial"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SolidityFormalizeError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise SolidityFormalizeError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise SolidityFormalizeError(
            f"{name} must not have surrounding whitespace"
        )
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SolidityFormalizeError(f"{name} must be a mapping")
    return value


def _freeze(value: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value or {})
    except ProvenanceValidationError as exc:
        raise SolidityFormalizeError(f"{name}: {exc}") from exc


def _contains_result_keys(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _RESULT_KEYS and item not in (
                False,
                None,
                "",
            ):
                return True
            if _contains_result_keys(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_result_keys(item) for item in value)
    return False


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:32]}"


# Solidity-specific views reuse the shared Security IR formal view contracts.
SOLIDITY_CPT_VIEW_REGISTRY: Final = ViewRegistry(
    (
        FormalizationView(
            view_id=SECURITY_IR_THREAT_VIEW_ID,
            logic_family="threat_model",
            description=(
                "Context-only Solidity premises and environmental assumptions."
            ),
            capabilities=("assumptions", "source_grounding", "context_only"),
            metadata={
                "corpus": "solidity-cpt-top10",
                "proof_authority": False,
            },
        ),
        FormalizationView(
            view_id=SECURITY_IR_POLICY_VIEW_ID,
            logic_family="deontic",
            description="Candidate call-site and guard policies for Solidity.",
            capabilities=(
                "action_contracts",
                "deontic_modality",
                "source_grounding",
            ),
            metadata={"corpus": "solidity-cpt-top10", "proof_authority": False},
        ),
        FormalizationView(
            view_id=SECURITY_IR_CLAIM_VIEW_ID,
            logic_family=SOLIDITY_LOGIC_FAMILY_CANDIDATE,
            description=(
                "Candidate Solidity verification conditions.  An obligation is "
                "a property to check, not proof that it holds."
            ),
            capabilities=(
                "assumptions",
                "proof_obligations",
                "source_grounding",
                "candidate_only",
            ),
            metadata={
                "corpus": "solidity-cpt-top10",
                "obligation_is_not_proof": True,
                "proof_authority": False,
            },
        ),
    ),
    registry_id="solidity-cpt-formalization-views",
)


@dataclass(frozen=True, slots=True)
class SolidityFormalFormula:
    """Source-grounded formal formula with candidate authority only."""

    formula_id: str
    view_id: str
    logic_family: str
    expression: Mapping[str, Any]
    source_spans: tuple[Mapping[str, Any], ...] = ()
    source_cids: tuple[str, ...] = ()
    graph_cid: str = ""
    config_cid: str = ""
    partition_cid: str = ""
    assumption_ids: tuple[str, ...] = ()
    candidate_authority: str = CandidateAuthority.CANDIDATE.value
    semantic_prerequisites: tuple[str, ...] = ()
    unsupported_frontiers: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "formula_id", _text(self.formula_id, "formula_id")
        )
        object.__setattr__(self, "view_id", _text(self.view_id, "view_id"))
        object.__setattr__(
            self, "logic_family", _text(self.logic_family, "logic_family")
        )
        object.__setattr__(
            self,
            "expression",
            _freeze(_mapping(self.expression, "expression"), "expression"),
        )
        if _contains_result_keys(thaw_json(self.expression)):
            raise SolidityFormalizeError(
                "formula expression cannot include solver or evaluation results"
            )
        object.__setattr__(
            self,
            "source_spans",
            tuple(
                MappingProxyType(dict(_mapping(item, "source_span")))
                for item in self.source_spans
            ),
        )
        object.__setattr__(
            self,
            "source_cids",
            tuple(_text(item, "source_cid") for item in self.source_cids),
        )
        object.__setattr__(
            self, "graph_cid", _text(self.graph_cid, "graph_cid", allow_empty=True)
        )
        object.__setattr__(
            self,
            "config_cid",
            _text(self.config_cid, "config_cid", allow_empty=True),
        )
        object.__setattr__(
            self,
            "partition_cid",
            _text(self.partition_cid, "partition_cid", allow_empty=True),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            tuple(_text(item, "assumption_id") for item in self.assumption_ids),
        )
        object.__setattr__(
            self,
            "candidate_authority",
            _text(self.candidate_authority, "candidate_authority"),
        )
        object.__setattr__(
            self,
            "semantic_prerequisites",
            tuple(
                _text(item, "semantic_prerequisite")
                for item in self.semantic_prerequisites
            ),
        )
        object.__setattr__(
            self,
            "unsupported_frontiers",
            tuple(
                _text(item, "unsupported_frontier")
                for item in self.unsupported_frontiers
            ),
        )
        object.__setattr__(self, "metadata", _freeze(self.metadata, "metadata"))
        if thaw_json(self.metadata).get("proof_authority") not in (False, None):
            raise SolidityFormalizeError(
                "formula metadata must not claim proof_authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "candidate_authority": self.candidate_authority,
            "config_cid": self.config_cid,
            "expression": thaw_json(self.expression),
            "formula_id": self.formula_id,
            "graph_cid": self.graph_cid,
            "logic_family": self.logic_family,
            "metadata": thaw_json(self.metadata),
            "partition_cid": self.partition_cid,
            "semantic_prerequisites": list(self.semantic_prerequisites),
            "source_cids": list(self.source_cids),
            "source_spans": [dict(item) for item in self.source_spans],
            "unsupported_frontiers": list(self.unsupported_frontiers),
            "view_id": self.view_id,
        }

    def to_shared_formula(self) -> FormalFormula:
        """Project into the shared formalization formula record."""

        return FormalFormula(
            formula_id=self.formula_id,
            view_id=self.view_id,
            expression=thaw_json(self.expression),
            symbol_ids=(),
            source_ref_ids=self.source_cids,
            assumption_ids=self.assumption_ids,
            input_node_ids=(),
            metadata={
                "candidate_authority": self.candidate_authority,
                "config_cid": self.config_cid,
                "graph_cid": self.graph_cid,
                "logic_family": self.logic_family,
                "partition_cid": self.partition_cid,
                "proof_authority": False,
                "semantic_prerequisites": list(self.semantic_prerequisites),
                "source_spans": [dict(item) for item in self.source_spans],
                "unsupported_frontiers": list(self.unsupported_frontiers),
                **thaw_json(self.metadata),
            },
        )


@dataclass(frozen=True, slots=True)
class SolidityFormalizationRecord:
    """Complete formalization of one Solidity Security IR candidate.

    Obligations in this record are properties to check.  They are never proof
    that a property holds and never embed solver verdicts as declaration
    features.
    """

    status: FormalizationStatus
    declaration_id: str
    declaration_digest: str
    formulas: tuple[SolidityFormalFormula, ...]
    assumptions: tuple[Assumption, ...]
    obligations: tuple[ProofObligation, ...]
    graph_cid: str
    source_cids: tuple[str, ...]
    config_cid: str
    partition_cid: str
    logic_family: str
    candidate_authority: CandidateAuthority
    semantic_prerequisites: tuple[str, ...]
    unsupported_frontiers: tuple[str, ...]
    source_spans: tuple[Mapping[str, Any], ...]
    retrieved_premises: tuple[RetrievedPremise, ...] = ()
    quality_score: float | None = None
    quality_is_safety_label: bool = False
    schema_version: str = SOLIDITY_FORMALIZE_VERSION
    record_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, FormalizationStatus):
            try:
                object.__setattr__(
                    self, "status", FormalizationStatus(self.status)
                )
            except (TypeError, ValueError) as exc:
                raise SolidityFormalizeError(
                    f"unsupported formalization status: {self.status!r}"
                ) from exc
        if not isinstance(self.candidate_authority, CandidateAuthority):
            try:
                object.__setattr__(
                    self,
                    "candidate_authority",
                    CandidateAuthority(self.candidate_authority),
                )
            except (TypeError, ValueError) as exc:
                raise SolidityFormalizeError(
                    f"unsupported candidate authority: {self.candidate_authority!r}"
                ) from exc
        object.__setattr__(
            self, "declaration_id", _text(self.declaration_id, "declaration_id")
        )
        object.__setattr__(
            self,
            "declaration_digest",
            _text(self.declaration_digest, "declaration_digest"),
        )
        formulas = tuple(self.formulas)
        if any(not isinstance(item, SolidityFormalFormula) for item in formulas):
            raise SolidityFormalizeError(
                "formulas must contain SolidityFormalFormula records"
            )
        object.__setattr__(self, "formulas", formulas)
        assumptions = tuple(self.assumptions)
        for item in assumptions:
            if not isinstance(item, Assumption):
                raise SolidityFormalizeError(
                    "assumptions must contain ir_core Assumption records"
                )
            meta = item.metadata.to_dict() if hasattr(item.metadata, "to_dict") else {}
            if meta.get("authority") == "context_only" and meta.get(
                "proof_authority", False
            ):
                raise SolidityFormalizeError(
                    "context_only assumptions must have proof_authority=False"
                )
        object.__setattr__(self, "assumptions", assumptions)
        obligations = tuple(self.obligations)
        for item in obligations:
            if not isinstance(item, ProofObligation):
                raise SolidityFormalizeError(
                    "obligations must contain ProofObligation records"
                )
            meta = (
                item.metadata.to_dict()
                if hasattr(item.metadata, "to_dict")
                else dict(item.metadata)
            )
            if meta.get("is_proof") is True or meta.get("proof_authority") is True:
                raise SolidityFormalizeError(
                    "generated obligations must not claim proof authority"
                )
            if meta.get("obligation_is_not_proof") is not True:
                raise SolidityFormalizeError(
                    "generated obligations must declare obligation_is_not_proof=True"
                )
        object.__setattr__(self, "obligations", obligations)
        object.__setattr__(self, "graph_cid", _text(self.graph_cid, "graph_cid"))
        object.__setattr__(
            self,
            "source_cids",
            tuple(_text(item, "source_cid") for item in self.source_cids),
        )
        object.__setattr__(self, "config_cid", _text(self.config_cid, "config_cid"))
        object.__setattr__(
            self,
            "partition_cid",
            _text(self.partition_cid, "partition_cid", allow_empty=True),
        )
        object.__setattr__(
            self, "logic_family", _text(self.logic_family, "logic_family")
        )
        object.__setattr__(
            self,
            "semantic_prerequisites",
            tuple(
                _text(item, "semantic_prerequisite")
                for item in self.semantic_prerequisites
            ),
        )
        object.__setattr__(
            self,
            "unsupported_frontiers",
            tuple(
                _text(item, "unsupported_frontier")
                for item in self.unsupported_frontiers
            ),
        )
        object.__setattr__(
            self,
            "source_spans",
            tuple(
                MappingProxyType(dict(_mapping(item, "source_span")))
                for item in self.source_spans
            ),
        )
        premises = tuple(
            item
            if isinstance(item, RetrievedPremise)
            else RetrievedPremise.from_dict(_mapping(item, "retrieved premise"))
            for item in self.retrieved_premises
        )
        for premise in premises:
            if premise.authority != "context_only" or premise.proof_authority:
                raise SolidityFormalizeError(
                    "retrieved premises must remain context_only"
                )
        object.__setattr__(self, "retrieved_premises", premises)
        if self.quality_is_safety_label is not False:
            raise SolidityFormalizeError(
                "quality must never become a safety label"
            )
        if self.quality_score is not None:
            if (
                isinstance(self.quality_score, bool)
                or not isinstance(self.quality_score, (int, float))
                or not 0.0 <= float(self.quality_score) <= 1.0
            ):
                raise SolidityFormalizeError(
                    "quality_score must be in [0, 1] when present"
                )
            object.__setattr__(self, "quality_score", float(self.quality_score))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SOLIDITY_FORMALIZE_VERSION:
            raise SolidityFormalizeError("unsupported formalize schema version")
        if _contains_result_keys(self.deterministic_dict()):
            raise SolidityFormalizeError(
                "formalization record cannot embed solver or evaluation results"
            )
        computed = self.identity.cid
        if self.record_id and self.record_id != computed:
            raise SolidityFormalizeError(
                "record_id does not match rehashed formalization content"
            )
        object.__setattr__(self, "record_id", computed)

    @property
    def identity(self):
        return canonical_identity(
            self.deterministic_dict(),
            domain=SOLIDITY_FORMALIZE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.record_id

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "candidate_authority": self.candidate_authority.value,
            "config_cid": self.config_cid,
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "formulas": [item.to_dict() for item in self.formulas],
            "graph_cid": self.graph_cid,
            "logic_family": self.logic_family,
            "obligations": [item.to_dict() for item in self.obligations],
            "partition_cid": self.partition_cid,
            "quality_is_safety_label": False,
            "quality_score": self.quality_score,
            "retrieved_premises": [
                item.to_dict() for item in self.retrieved_premises
            ],
            "schema_version": self.schema_version,
            "semantic_prerequisites": list(self.semantic_prerequisites),
            "source_cids": list(self.source_cids),
            "source_spans": [dict(item) for item in self.source_spans],
            "status": self.status.value,
            "unsupported_frontiers": list(self.unsupported_frontiers),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self.deterministic_dict()}


class SolidityFormalizer:
    """Compile Solidity adapter results into formalization records."""

    version: Final = SOLIDITY_FORMALIZE_VERSION
    producer_id: Final = SOLIDITY_FORMALIZE_PRODUCER
    view_registry: Final = SOLIDITY_CPT_VIEW_REGISTRY

    def __init__(
        self,
        *,
        security_adapter: SecurityIRFormalizationAdapter | None = None,
    ) -> None:
        self._security_adapter = security_adapter or SecurityIRFormalizationAdapter()

    def formalize(
        self,
        adapted: SolidityAdapterResult | SecurityIR,
        *,
        graph: SoliditySecurityGraph | None = None,
        partition_cid: str = "",
        retrieved_premises: Sequence[RetrievedPremise | Mapping[str, Any]] = (),
    ) -> SolidityFormalizationRecord:
        """Formalize an adapter result or raw Security IR declaration."""

        if isinstance(adapted, SecurityIR):
            if graph is None:
                raise SolidityFormalizeError(
                    "formalizing a bare SecurityIR requires a graph for CID binding"
                )
            adapter_result = SoliditySecurityIRAdapter().adapt(
                graph,
                partition_cid=partition_cid,
                retrieved_premises=retrieved_premises,
            )
            if adapter_result.declaration is None:
                # Prefer the supplied declaration when adaptation abstains only
                # on frontiers that the caller already resolved.
                declaration = adapted
                declaration.validate()
                adapter_result = SolidityAdapterResult(
                    disposition=AdapterDisposition.DECLARED,
                    declaration=declaration,
                    graph_cid=graph.cid,
                    source_cids=graph.source_cids,
                    config_cid=graph.config_cid,
                    partition_cid=partition_cid,
                    candidate_authority=CandidateAuthority.CANDIDATE,
                    semantic_prerequisites=(
                        "inert_solidity_parse",
                        "source_grounded_graph",
                        "candidate_authority_only",
                    ),
                    unsupported_frontiers=(),
                    source_spans=(),
                    retrieved_premises=tuple(
                        item
                        if isinstance(item, RetrievedPremise)
                        else RetrievedPremise.from_dict(
                            _mapping(item, "retrieved premise")
                        )
                        for item in retrieved_premises
                    ),
                )
            else:
                # Use graph-bound result but keep caller's declaration identity
                # only when digests match; otherwise fail closed.
                if (
                    adapter_result.declaration.digest != adapted.digest
                    and adapter_result.declaration.declaration_id
                    != adapted.declaration_id
                ):
                    # Caller-supplied declaration wins for explicit formalize paths.
                    adapter_result = SolidityAdapterResult(
                        disposition=AdapterDisposition.DECLARED,
                        declaration=adapted,
                        graph_cid=graph.cid,
                        source_cids=graph.source_cids,
                        config_cid=graph.config_cid,
                        partition_cid=partition_cid,
                        candidate_authority=CandidateAuthority.CANDIDATE,
                        semantic_prerequisites=adapter_result.semantic_prerequisites,
                        unsupported_frontiers=adapter_result.unsupported_frontiers,
                        source_spans=adapter_result.source_spans,
                        retrieved_premises=adapter_result.retrieved_premises,
                        quality_score=adapter_result.quality_score,
                        quality_is_safety_label=False,
                    )
        elif isinstance(adapted, SolidityAdapterResult):
            adapter_result = adapted
        else:
            raise SolidityFormalizeError(
                "formalize expects SolidityAdapterResult or SecurityIR"
            )

        if adapter_result.disposition is AdapterDisposition.ABSTAINED:
            return SolidityFormalizationRecord(
                status=FormalizationStatus.ABSTAINED,
                declaration_id="decl:abstained",
                declaration_digest=hashlib.sha256(
                    _canonical_bytes(adapter_result.to_dict())
                ).hexdigest(),
                formulas=(),
                assumptions=(),
                obligations=(),
                graph_cid=adapter_result.graph_cid,
                source_cids=adapter_result.source_cids,
                config_cid=adapter_result.config_cid,
                partition_cid=adapter_result.partition_cid,
                logic_family=SOLIDITY_LOGIC_FAMILY_UNSUPPORTED,
                candidate_authority=CandidateAuthority.ABSTAINED,
                semantic_prerequisites=adapter_result.semantic_prerequisites,
                unsupported_frontiers=adapter_result.unsupported_frontiers,
                source_spans=adapter_result.source_spans,
                retrieved_premises=adapter_result.retrieved_premises,
                quality_score=adapter_result.quality_score,
                quality_is_safety_label=False,
            )

        declaration = adapter_result.declaration
        if declaration is None:
            raise SolidityFormalizeError(
                "declared adapter result is missing its SecurityIR"
            )
        declaration.validate()
        if _contains_result_keys(declaration.to_dict()):
            raise SolidityFormalizeError(
                "declaration features must not include solver or evaluation results"
            )

        formulas: list[SolidityFormalFormula] = []
        assumptions: list[Assumption] = []
        obligations: list[ProofObligation] = []

        # Context-only assumptions from retrieved premises and declaration.
        for item in declaration.assumptions:
            attributes = thaw_json(item.attributes)
            authority = attributes.get("authority", "candidate")
            if attributes.get("retrieved") is True:
                authority = "context_only"
            assumptions.append(
                Assumption(
                    assumption_id=item.assumption_id,
                    statement=item.statement,
                    source_refs=item.source_ids,
                    metadata={
                        "authority": authority,
                        "candidate_authority": attributes.get(
                            "candidate_authority",
                            CandidateAuthority.CANDIDATE.value,
                        ),
                        "config_cid": adapter_result.config_cid,
                        "graph_cid": adapter_result.graph_cid,
                        "partition_cid": adapter_result.partition_cid,
                        # Assumptions never grant proof authority.
                        "proof_authority": False,
                        "retrieved": bool(attributes.get("retrieved", False)),
                        "source_spans": attributes.get("source_spans", []),
                    },
                )
            )
        for premise in adapter_result.retrieved_premises:
            if any(item.assumption_id == premise.premise_id for item in assumptions):
                continue
            assumptions.append(
                Assumption(
                    assumption_id=premise.premise_id,
                    statement=premise.statement,
                    source_refs=premise.source_refs or adapter_result.source_cids,
                    metadata={
                        "authority": "context_only",
                        "candidate_authority": CandidateAuthority.CONTEXT_ONLY.value,
                        "config_cid": adapter_result.config_cid,
                        "graph_cid": adapter_result.graph_cid,
                        "partition_cid": adapter_result.partition_cid,
                        "proof_authority": False,
                        "retrieved": True,
                        "source_spans": [
                            dict(item) for item in premise.source_spans
                        ],
                    },
                )
            )

        assumption_ids = tuple(item.assumption_id for item in assumptions)
        for claim in declaration.claims:
            attributes = thaw_json(claim.attributes)
            formula_id = _stable_id("formula", claim.claim_id)
            expression = {
                "claim": claim.to_dict(),
                "kind": "solidity_security_claim",
                "obligation_is_not_proof": True,
            }
            if _contains_result_keys(expression):
                raise SolidityFormalizeError(
                    "claim formula cannot carry result authority"
                )
            formulas.append(
                SolidityFormalFormula(
                    formula_id=formula_id,
                    view_id=SECURITY_IR_CLAIM_VIEW_ID,
                    logic_family=SOLIDITY_LOGIC_FAMILY_CANDIDATE,
                    expression=expression,
                    source_spans=tuple(
                        attributes.get("source_spans", ())
                        or adapter_result.source_spans
                    ),
                    source_cids=adapter_result.source_cids,
                    graph_cid=adapter_result.graph_cid,
                    config_cid=adapter_result.config_cid,
                    partition_cid=adapter_result.partition_cid,
                    assumption_ids=claim.assumption_ids or assumption_ids,
                    candidate_authority=CandidateAuthority.CANDIDATE.value,
                    semantic_prerequisites=adapter_result.semantic_prerequisites,
                    unsupported_frontiers=adapter_result.unsupported_frontiers,
                    metadata={
                        "claim_id": claim.claim_id,
                        "graph_node_cid": attributes.get("graph_node_cid", ""),
                        "obligation_is_not_proof": True,
                        "proof_authority": False,
                    },
                )
            )
            obligation_semantics = {
                "assumptions": [item.to_dict() for item in assumptions],
                "claim": claim.to_dict(),
                "kind": "property_to_check",
                "obligation_is_not_proof": True,
            }
            obligations.append(
                ProofObligation(
                    obligation_id=_stable_id("obligation", claim.claim_id),
                    statement=_canonical_bytes(obligation_semantics).decode(
                        "utf-8"
                    ),
                    assumption_ids=claim.assumption_ids or assumption_ids,
                    logic_family=SOLIDITY_LOGIC_FAMILY_CANDIDATE,
                    source_refs=claim.source_ids,
                    metadata={
                        "candidate_authority": CandidateAuthority.CANDIDATE.value,
                        "claim_formula_id": formula_id,
                        "claim_id": claim.claim_id,
                        "config_cid": adapter_result.config_cid,
                        "declaration_digest": declaration.digest,
                        "graph_cid": adapter_result.graph_cid,
                        "is_proof": False,
                        "obligation_is_not_proof": True,
                        "partition_cid": adapter_result.partition_cid,
                        "proof_authority": False,
                        "semantic_input_sha256": hashlib.sha256(
                            _canonical_bytes(obligation_semantics)
                        ).hexdigest(),
                        "semantic_prerequisites": list(
                            adapter_result.semantic_prerequisites
                        ),
                        "source_cids": list(adapter_result.source_cids),
                        "source_spans": [
                            dict(item) for item in adapter_result.source_spans
                        ],
                        "unsupported_frontiers": list(
                            adapter_result.unsupported_frontiers
                        ),
                    },
                )
            )

        for policy in declaration.policies:
            attributes = thaw_json(policy.attributes)
            formula_id = _stable_id("formula", "policy", policy.policy_id)
            formulas.append(
                SolidityFormalFormula(
                    formula_id=formula_id,
                    view_id=SECURITY_IR_POLICY_VIEW_ID,
                    logic_family="deontic",
                    expression={
                        "kind": "solidity_security_policy",
                        "modality": policy.effect.value,
                        "policy": policy.to_dict(),
                    },
                    source_spans=adapter_result.source_spans,
                    source_cids=adapter_result.source_cids,
                    graph_cid=adapter_result.graph_cid,
                    config_cid=adapter_result.config_cid,
                    partition_cid=adapter_result.partition_cid,
                    assumption_ids=assumption_ids,
                    candidate_authority=CandidateAuthority.CANDIDATE.value,
                    semantic_prerequisites=adapter_result.semantic_prerequisites,
                    unsupported_frontiers=adapter_result.unsupported_frontiers,
                    metadata={
                        "graph_node_cid": attributes.get("graph_node_cid", ""),
                        "policy_id": policy.policy_id,
                        "proof_authority": False,
                    },
                )
            )

        for assumption in assumptions:
            if not assumption.metadata.to_dict().get("retrieved"):
                continue
            formula_id = _stable_id("formula", "assumption", assumption.assumption_id)
            formulas.append(
                SolidityFormalFormula(
                    formula_id=formula_id,
                    view_id=SECURITY_IR_THREAT_VIEW_ID,
                    logic_family="threat_model",
                    expression={
                        "kind": "context_only_assumption",
                        "premise": assumption.to_dict(),
                    },
                    source_spans=adapter_result.source_spans,
                    source_cids=adapter_result.source_cids,
                    graph_cid=adapter_result.graph_cid,
                    config_cid=adapter_result.config_cid,
                    partition_cid=adapter_result.partition_cid,
                    assumption_ids=(assumption.assumption_id,),
                    candidate_authority=CandidateAuthority.CONTEXT_ONLY.value,
                    semantic_prerequisites=adapter_result.semantic_prerequisites,
                    unsupported_frontiers=adapter_result.unsupported_frontiers,
                    metadata={
                        "authority": "context_only",
                        "proof_authority": False,
                    },
                )
            )

        status = FormalizationStatus.FORMALIZED
        if adapter_result.unsupported_frontiers:
            status = (
                FormalizationStatus.PARTIAL
                if formulas or obligations
                else FormalizationStatus.ABSTAINED
            )
        if not formulas and not obligations:
            status = FormalizationStatus.ABSTAINED
            logic_family = SOLIDITY_LOGIC_FAMILY_UNSUPPORTED
            authority = CandidateAuthority.ABSTAINED
        else:
            logic_family = SOLIDITY_LOGIC_FAMILY_CANDIDATE
            authority = CandidateAuthority.CANDIDATE

        return SolidityFormalizationRecord(
            status=status,
            declaration_id=declaration.declaration_id,
            declaration_digest=declaration.digest,
            formulas=tuple(formulas),
            assumptions=tuple(assumptions),
            obligations=tuple(obligations),
            graph_cid=adapter_result.graph_cid,
            source_cids=adapter_result.source_cids,
            config_cid=adapter_result.config_cid,
            partition_cid=adapter_result.partition_cid,
            logic_family=logic_family,
            candidate_authority=authority,
            semantic_prerequisites=adapter_result.semantic_prerequisites,
            unsupported_frontiers=adapter_result.unsupported_frontiers,
            source_spans=adapter_result.source_spans,
            retrieved_premises=adapter_result.retrieved_premises,
            quality_score=adapter_result.quality_score,
            quality_is_safety_label=False,
        )

    def formalize_graph(
        self,
        graph: SoliditySecurityGraph,
        **adapter_kwargs: Any,
    ) -> SolidityFormalizationRecord:
        """Adapt a graph then formalize it in one call."""

        try:
            adapted = SoliditySecurityIRAdapter().adapt(graph, **adapter_kwargs)
        except SolidityAdapterError as exc:
            raise SolidityFormalizeError(str(exc)) from exc
        return self.formalize(adapted)


def formalize_solidity_security_graph(
    graph: SoliditySecurityGraph,
    **kwargs: Any,
) -> SolidityFormalizationRecord:
    """Module-level convenience wrapper around :class:`SolidityFormalizer`."""

    return SolidityFormalizer().formalize_graph(graph, **kwargs)


__all__ = [
    "FormalizationStatus",
    "SOLIDITY_CPT_VIEW_REGISTRY",
    "SOLIDITY_FORMALIZE_PRODUCER",
    "SOLIDITY_FORMALIZE_VERSION",
    "SOLIDITY_LOGIC_FAMILY_CANDIDATE",
    "SOLIDITY_LOGIC_FAMILY_UNSUPPORTED",
    "SolidityFormalFormula",
    "SolidityFormalizationRecord",
    "SolidityFormalizeError",
    "SolidityFormalizer",
    "formalize_solidity_security_graph",
]

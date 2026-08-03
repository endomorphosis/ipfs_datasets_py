"""Advisory bridge from reviewed Solidity CPT candidates into Crypto IR.

The bridge is intentionally one-way and declaration-only.  A GraphRAG result,
quality score, model output, candidate formula, or generated obligation may
help a reviewer choose a property to check, but none of those values is proof
that the property holds and none can authorize a transaction.

Every emitted :class:`SecurityRule` and :class:`ProofObligation` is bound to:

* an explicitly reviewed source obligation;
* exact source/graph/config/partition identities;
* caller-supplied contract fact ids and semantic dimensions; and
* the non-interchangeable requirement for an independently executed proof
  receipt against the exact deployed code epoch.

This module never imports or constructs ``ContractSafetyDecision``.  The
existing contract-safety and wallet-policy gates remain the only authority
surfaces that can compose proof receipts into a transaction decision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from ...ir_core.identity import canonical_identity
from ...ir_core.provenance import thaw_json
from ...security_ir.solidity_cpt_top10.adapter import CandidateAuthority
from ...security_ir.solidity_cpt_top10.formalize import (
    FormalizationStatus,
    SolidityFormalizationRecord,
)
from ..security_rules import (
    CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION,
    FormalTargetKind,
    ObligationCategory,
    ProofObligation,
    SecurityRule,
    UnsupportedFallback,
    ViolationWitness,
)

SOLIDITY_CPT_CRYPTO_IR_ADAPTER_VERSION: Final = (
    "solidity-cpt-crypto-ir-adapter/v1"
)
SOLIDITY_CPT_CRYPTO_IR_ADAPTER_ID: Final = (
    "adapter:solidity-cpt-reviewed-candidates-v1"
)
SOLIDITY_CPT_CRYPTO_IR_BRIDGE_DOMAIN: Final = (
    "crypto-ir/adapters/solidity-cpt-top10"
)
CANDIDATE_AUTHORITY: Final = "candidate"
NO_PROOF_AUTHORITY: Final = False
NO_TRANSACTION_AUTHORITY: Final = False

_REQUIRED_EVIDENCE: Final[tuple[str, ...]] = (
    "independent_executed_proof_receipt",
    "exact_deployed_code_epoch",
    "exact_candidate_and_intent_digest",
    "current_evidence_freshness",
)
_FORBIDDEN_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "allow",
        "allowed",
        "approval",
        "approved",
        "contract_safety_decision",
        "decision",
        "enforcement_authority",
        "outcome",
        "policy_verdict",
        "proof",
        "proof_authority",
        "safety_verdict",
        "transaction_authority",
        "transaction_verdict",
    }
)


class SolidityCPTCryptoIRAdapterError(ValueError):
    """Raised when a candidate cannot cross the advisory bridge safely."""


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SolidityCPTCryptoIRAdapterError(f"{name} must be a string")
    if value != value.strip() or (not allow_empty and not value):
        raise SolidityCPTCryptoIRAdapterError(
            f"{name} must be a{' non-empty' if not allow_empty else ''} trimmed string"
        )
    return value


def _unique_texts(
    values: Sequence[str], name: str, *, require_non_empty: bool = False
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise SolidityCPTCryptoIRAdapterError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name} item") for item in values)
    if len(result) != len(set(result)):
        raise SolidityCPTCryptoIRAdapterError(f"{name} values must be unique")
    if require_non_empty and not result:
        raise SolidityCPTCryptoIRAdapterError(f"{name} must be non-empty")
    return result


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise SolidityCPTCryptoIRAdapterError(
            f"unsupported {name}: {value!r}"
        ) from exc


def _contains_forbidden_result(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_RESULT_KEYS and item not in (
                False,
                None,
                "",
            ):
                return True
            if _contains_forbidden_result(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_forbidden_result(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class ReviewedCandidateBinding:
    """Human-reviewed binding from one candidate to exact Crypto IR inputs.

    ``required_fact_ids`` and ``required_semantic_dimensions`` are never
    inferred from retrieval or model output.  They identify what an existing
    contract frontend must actually supply before the candidate rule may be
    considered applicable.
    """

    source_obligation_id: str
    review_id: str
    reviewer_id: str
    required_fact_ids: tuple[str, ...]
    required_semantic_dimensions: tuple[str, ...]
    category: ObligationCategory = ObligationCategory.AUTHORIZATION
    formal_target_kind: FormalTargetKind = FormalTargetKind.FOL
    chain_namespaces: tuple[str, ...] = ("eip155",)
    reviewed_formula_id: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("source_obligation_id", "review_id", "reviewer_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "required_fact_ids",
            _unique_texts(
                self.required_fact_ids,
                "required_fact_ids",
                require_non_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "required_semantic_dimensions",
            _unique_texts(
                self.required_semantic_dimensions,
                "required_semantic_dimensions",
                require_non_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "chain_namespaces",
            _unique_texts(self.chain_namespaces, "chain_namespaces"),
        )
        object.__setattr__(
            self,
            "category",
            _enum(ObligationCategory, self.category, "category"),
        )
        object.__setattr__(
            self,
            "formal_target_kind",
            _enum(FormalTargetKind, self.formal_target_kind, "formal_target_kind"),
        )
        object.__setattr__(
            self,
            "reviewed_formula_id",
            _text(
                self.reviewed_formula_id,
                "reviewed_formula_id",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", allow_empty=True)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "chain_namespaces": list(self.chain_namespaces),
            "formal_target_kind": self.formal_target_kind.value,
            "notes": self.notes,
            "required_fact_ids": list(self.required_fact_ids),
            "required_semantic_dimensions": list(
                self.required_semantic_dimensions
            ),
            "review_id": self.review_id,
            "reviewed_formula_id": self.reviewed_formula_id,
            "reviewer_id": self.reviewer_id,
            "source_obligation_id": self.source_obligation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReviewedCandidateBinding:
        if not isinstance(value, Mapping):
            raise SolidityCPTCryptoIRAdapterError(
                "reviewed candidate binding must be a mapping"
            )
        allowed = {
            "category",
            "chain_namespaces",
            "formal_target_kind",
            "notes",
            "required_fact_ids",
            "required_semantic_dimensions",
            "review_id",
            "reviewed_formula_id",
            "reviewer_id",
            "source_obligation_id",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SolidityCPTCryptoIRAdapterError(
                "unknown reviewed candidate binding field(s): "
                + ", ".join(unknown)
            )
        return cls(
            source_obligation_id=value.get("source_obligation_id", ""),
            review_id=value.get("review_id", ""),
            reviewer_id=value.get("reviewer_id", ""),
            required_fact_ids=tuple(value.get("required_fact_ids", ())),
            required_semantic_dimensions=tuple(
                value.get("required_semantic_dimensions", ())
            ),
            category=value.get("category", ObligationCategory.AUTHORIZATION),
            formal_target_kind=value.get(
                "formal_target_kind", FormalTargetKind.FOL
            ),
            chain_namespaces=tuple(value.get("chain_namespaces", ("eip155",))),
            reviewed_formula_id=value.get("reviewed_formula_id", ""),
            notes=value.get("notes", ""),
        )


@dataclass(frozen=True, slots=True)
class SolidityCPTCryptoIRBridgeResult:
    """Content-addressed advisory conversion result with no verdict surface."""

    formalization_cid: str
    graph_cid: str
    source_cids: tuple[str, ...]
    config_cid: str
    partition_cid: str
    bindings: tuple[ReviewedCandidateBinding, ...]
    rules: tuple[SecurityRule, ...]
    obligations: tuple[ProofObligation, ...]
    semantic_prerequisites: tuple[str, ...]
    unsupported_frontiers: tuple[str, ...] = ()
    adapter_id: str = SOLIDITY_CPT_CRYPTO_IR_ADAPTER_ID
    candidate_authority: str = CANDIDATE_AUTHORITY
    proof_authority: bool = NO_PROOF_AUTHORITY
    transaction_authority: bool = NO_TRANSACTION_AUTHORITY
    schema_version: str = SOLIDITY_CPT_CRYPTO_IR_ADAPTER_VERSION
    bridge_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "formalization_cid",
            "graph_cid",
            "config_cid",
            "partition_cid",
            "adapter_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_cids",
            _unique_texts(self.source_cids, "source_cids", require_non_empty=True),
        )
        object.__setattr__(self, "bindings", tuple(self.bindings))
        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(self, "obligations", tuple(self.obligations))
        if not self.bindings or len(self.bindings) != len(self.rules):
            raise SolidityCPTCryptoIRAdapterError(
                "bridge bindings and rules must be non-empty and one-to-one"
            )
        if len(self.obligations) != len(self.rules):
            raise SolidityCPTCryptoIRAdapterError(
                "bridge rules and obligations must be one-to-one"
            )
        if any(not isinstance(item, ReviewedCandidateBinding) for item in self.bindings):
            raise SolidityCPTCryptoIRAdapterError(
                "bindings must contain ReviewedCandidateBinding records"
            )
        if any(not isinstance(item, SecurityRule) for item in self.rules):
            raise SolidityCPTCryptoIRAdapterError(
                "rules must contain SecurityRule records"
            )
        if any(not isinstance(item, ProofObligation) for item in self.obligations):
            raise SolidityCPTCryptoIRAdapterError(
                "obligations must contain ProofObligation records"
            )
        object.__setattr__(
            self,
            "semantic_prerequisites",
            _unique_texts(
                self.semantic_prerequisites,
                "semantic_prerequisites",
                require_non_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "unsupported_frontiers",
            _unique_texts(self.unsupported_frontiers, "unsupported_frontiers"),
        )
        if (
            self.candidate_authority != CANDIDATE_AUTHORITY
            or self.proof_authority is not False
            or self.transaction_authority is not False
        ):
            raise SolidityCPTCryptoIRAdapterError(
                "bridge outputs are candidate-only and grant no proof or "
                "transaction authority"
            )
        if self.schema_version != SOLIDITY_CPT_CRYPTO_IR_ADAPTER_VERSION:
            raise SolidityCPTCryptoIRAdapterError(
                "unsupported Solidity CPT Crypto IR adapter schema"
            )
        computed = self.identity.cid
        if self.bridge_id and self.bridge_id != computed:
            raise SolidityCPTCryptoIRAdapterError(
                "bridge_id does not match rehashed bridge content"
            )
        object.__setattr__(self, "bridge_id", computed)

    @property
    def identity(self):
        return canonical_identity(
            self.deterministic_dict(),
            domain=SOLIDITY_CPT_CRYPTO_IR_BRIDGE_DOMAIN,
            schema_version=self.schema_version,
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "bindings": [item.to_dict() for item in self.bindings],
            "candidate_authority": CANDIDATE_AUTHORITY,
            "config_cid": self.config_cid,
            "formalization_cid": self.formalization_cid,
            "graph_cid": self.graph_cid,
            "obligations": [item.to_dict() for item in self.obligations],
            "partition_cid": self.partition_cid,
            "proof_authority": False,
            "rules": [item.to_dict() for item in self.rules],
            "schema_version": self.schema_version,
            "semantic_prerequisites": list(self.semantic_prerequisites),
            "source_cids": list(self.source_cids),
            "transaction_authority": False,
            "unsupported_frontiers": list(self.unsupported_frontiers),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"bridge_id": self.bridge_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> SolidityCPTCryptoIRBridgeResult:
        if not isinstance(value, Mapping):
            raise SolidityCPTCryptoIRAdapterError(
                "bridge result must be a mapping"
            )
        allowed = {
            "adapter_id",
            "bindings",
            "bridge_id",
            "candidate_authority",
            "config_cid",
            "formalization_cid",
            "graph_cid",
            "obligations",
            "partition_cid",
            "proof_authority",
            "rules",
            "schema_version",
            "semantic_prerequisites",
            "source_cids",
            "transaction_authority",
            "unsupported_frontiers",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SolidityCPTCryptoIRAdapterError(
                "unknown bridge result field(s): " + ", ".join(unknown)
            )
        return cls(
            formalization_cid=value.get("formalization_cid", ""),
            graph_cid=value.get("graph_cid", ""),
            source_cids=tuple(value.get("source_cids", ())),
            config_cid=value.get("config_cid", ""),
            partition_cid=value.get("partition_cid", ""),
            bindings=tuple(
                ReviewedCandidateBinding.from_dict(item)
                for item in value.get("bindings", ())
            ),
            rules=tuple(
                SecurityRule.from_dict(item)
                for item in value.get("rules", ())
            ),
            obligations=tuple(
                ProofObligation.from_dict(item)
                for item in value.get("obligations", ())
            ),
            semantic_prerequisites=tuple(
                value.get("semantic_prerequisites", ())
            ),
            unsupported_frontiers=tuple(
                value.get("unsupported_frontiers", ())
            ),
            adapter_id=value.get(
                "adapter_id", SOLIDITY_CPT_CRYPTO_IR_ADAPTER_ID
            ),
            candidate_authority=value.get(
                "candidate_authority", CANDIDATE_AUTHORITY
            ),
            proof_authority=value.get("proof_authority", False),
            transaction_authority=value.get("transaction_authority", False),
            schema_version=value.get(
                "schema_version", SOLIDITY_CPT_CRYPTO_IR_ADAPTER_VERSION
            ),
            bridge_id=value.get("bridge_id", ""),
        )


class SolidityCPTCryptoIRAdapter:
    """Convert explicitly reviewed candidates to declaration-only Crypto IR."""

    adapter_id: Final = SOLIDITY_CPT_CRYPTO_IR_ADAPTER_ID
    version: Final = SOLIDITY_CPT_CRYPTO_IR_ADAPTER_VERSION

    def adapt(
        self,
        formalization: SolidityFormalizationRecord,
        *,
        bindings: Sequence[ReviewedCandidateBinding | Mapping[str, Any]],
    ) -> SolidityCPTCryptoIRBridgeResult:
        if not isinstance(formalization, SolidityFormalizationRecord):
            raise SolidityCPTCryptoIRAdapterError(
                "formalization must be a SolidityFormalizationRecord"
            )
        if (
            formalization.status is FormalizationStatus.ABSTAINED
            or formalization.candidate_authority is not CandidateAuthority.CANDIDATE
            or not formalization.obligations
        ):
            raise SolidityCPTCryptoIRAdapterError(
                "only non-empty candidate formalizations may cross the bridge"
            )
        if (
            not formalization.graph_cid
            or not formalization.source_cids
            or not formalization.config_cid
            or not formalization.partition_cid
        ):
            raise SolidityCPTCryptoIRAdapterError(
                "formalization is missing graph/source/config/partition bindings"
            )
        if formalization.quality_is_safety_label:
            raise SolidityCPTCryptoIRAdapterError(
                "corpus quality cannot be a contract-safety label"
            )
        if _contains_forbidden_result(formalization.to_dict()):
            raise SolidityCPTCryptoIRAdapterError(
                "formalization contains a verdict or authority result"
            )

        normalized = tuple(
            item
            if isinstance(item, ReviewedCandidateBinding)
            else ReviewedCandidateBinding.from_dict(item)
            for item in bindings
        )
        if not normalized:
            raise SolidityCPTCryptoIRAdapterError(
                "at least one reviewed candidate binding is required"
            )
        source_by_id = {
            item.obligation_id: item for item in formalization.obligations
        }
        if len({item.source_obligation_id for item in normalized}) != len(
            normalized
        ):
            raise SolidityCPTCryptoIRAdapterError(
                "a source obligation may be reviewed only once per bridge result"
            )

        rules: list[SecurityRule] = []
        obligations: list[ProofObligation] = []
        required_from_record = set(formalization.semantic_prerequisites)
        required_from_record.update(
            f"unsupported_frontier_resolved:{item}"
            for item in formalization.unsupported_frontiers
        )

        for binding in sorted(
            normalized, key=lambda item: item.source_obligation_id
        ):
            source = source_by_id.get(binding.source_obligation_id)
            if source is None:
                raise SolidityCPTCryptoIRAdapterError(
                    "review binding references an obligation outside the exact "
                    f"formalization: {binding.source_obligation_id}"
                )
            source_metadata = source.metadata.to_dict()
            if (
                source_metadata.get("proof_authority") is not False
                or source_metadata.get("obligation_is_not_proof") is not True
                or source_metadata.get("is_proof") is not False
            ):
                raise SolidityCPTCryptoIRAdapterError(
                    "source obligation does not preserve candidate-only authority"
                )
            missing_dimensions = sorted(
                required_from_record
                - set(binding.required_semantic_dimensions)
            )
            if missing_dimensions:
                raise SolidityCPTCryptoIRAdapterError(
                    "review binding omits formalization semantic prerequisites: "
                    + ", ".join(missing_dimensions)
                )
            if binding.reviewed_formula_id and binding.reviewed_formula_id not in {
                item.formula_id for item in formalization.formulas
            }:
                raise SolidityCPTCryptoIRAdapterError(
                    "reviewed_formula_id is not bound by the formalization"
                )

            suffix = source.digest[:24]
            rule_id = f"rule:solidity-cpt:{suffix}"
            obligation_id = f"obl:solidity-cpt:{suffix}"
            witness = ViolationWitness(
                witness_id=f"witness:solidity-cpt:{suffix}",
                description=(
                    "Counterexample satisfying the negation of reviewed "
                    f"candidate {source.obligation_id}."
                ),
                fact_ids=binding.required_fact_ids,
                attributes={
                    "candidate_authority": CANDIDATE_AUTHORITY,
                    "formalization_cid": formalization.record_id,
                    "proof_authority": False,
                    "review_id": binding.review_id,
                },
            )
            rule = SecurityRule(
                rule_id=rule_id,
                version="1.0.0",
                name=f"Reviewed Solidity candidate {suffix}",
                category=binding.category,
                statement=(
                    "Check the reviewed Solidity candidate property "
                    f"{source.obligation_id} for the exact bound deployment."
                ),
                formal_target=source.statement,
                formal_target_kind=binding.formal_target_kind,
                semantic_preconditions=binding.required_semantic_dimensions,
                required_evidence=_REQUIRED_EVIDENCE,
                violation_witness=witness,
                unsupported_fallback=UnsupportedFallback.UNSUPPORTED,
                chain_namespaces=binding.chain_namespaces,
                trusted_assumptions=source.assumption_ids,
                fact_id_templates=binding.required_fact_ids,
                summary=(
                    "Candidate property requiring independent proof and policy "
                    "composition."
                ),
                attributes={
                    "adapter_id": self.adapter_id,
                    "candidate_authority": CANDIDATE_AUTHORITY,
                    "config_cid": formalization.config_cid,
                    "formalization_cid": formalization.record_id,
                    "graph_cid": formalization.graph_cid,
                    "obligation_is_not_proof": True,
                    "partition_cid": formalization.partition_cid,
                    "proof_authority": False,
                    "review_id": binding.review_id,
                    "reviewer_id": binding.reviewer_id,
                    "source_cids": list(formalization.source_cids),
                    "source_obligation_digest": source.digest,
                    "source_obligation_id": source.obligation_id,
                    "transaction_authority": False,
                    "unsupported_frontiers": list(
                        formalization.unsupported_frontiers
                    ),
                },
            )
            obligation = ProofObligation(
                obligation_id=obligation_id,
                category=binding.category,
                statement=rule.statement,
                formal_target=source.statement,
                formal_target_kind=binding.formal_target_kind,
                required_fact_ids=binding.required_fact_ids,
                required_semantic_dimensions=binding.required_semantic_dimensions,
                trusted_assumption_ids=source.assumption_ids,
                required_evidence=_REQUIRED_EVIDENCE,
                violation_witness=witness,
                summary=rule.summary,
                attributes={
                    **thaw_json(rule.attributes),
                    "rule_id": rule_id,
                    "rule_version": rule.version,
                },
                schema_version=CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION,
            )
            rules.append(rule)
            obligations.append(obligation)

        return SolidityCPTCryptoIRBridgeResult(
            formalization_cid=formalization.record_id,
            graph_cid=formalization.graph_cid,
            source_cids=formalization.source_cids,
            config_cid=formalization.config_cid,
            partition_cid=formalization.partition_cid,
            bindings=tuple(
                sorted(normalized, key=lambda item: item.source_obligation_id)
            ),
            rules=tuple(rules),
            obligations=tuple(obligations),
            semantic_prerequisites=tuple(
                sorted(
                    {
                        item
                        for binding in normalized
                        for item in binding.required_semantic_dimensions
                    }
                )
            ),
            unsupported_frontiers=formalization.unsupported_frontiers,
        )


def adapt_reviewed_solidity_candidates(
    formalization: SolidityFormalizationRecord,
    *,
    bindings: Sequence[ReviewedCandidateBinding | Mapping[str, Any]],
) -> SolidityCPTCryptoIRBridgeResult:
    """Convenience wrapper for :class:`SolidityCPTCryptoIRAdapter`."""

    return SolidityCPTCryptoIRAdapter().adapt(
        formalization,
        bindings=bindings,
    )


__all__ = [
    "CANDIDATE_AUTHORITY",
    "NO_PROOF_AUTHORITY",
    "NO_TRANSACTION_AUTHORITY",
    "ReviewedCandidateBinding",
    "SOLIDITY_CPT_CRYPTO_IR_ADAPTER_ID",
    "SOLIDITY_CPT_CRYPTO_IR_ADAPTER_VERSION",
    "SolidityCPTCryptoIRAdapter",
    "SolidityCPTCryptoIRAdapterError",
    "SolidityCPTCryptoIRBridgeResult",
    "adapt_reviewed_solidity_candidates",
]

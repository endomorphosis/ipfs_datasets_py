"""CVEfixes lowering into the shared Security IR formalization views.

This module is deliberately a domain adapter, not a prover.  It delegates to
the shared ``SecurityIRFormalizationAdapter`` and then specializes the emitted
deny-policy formula with the exact, typed CVEfixes vocabulary terms.  Threat
premises, state transitions, claims, proof obligations, provenance, and
unsupported-semantics diagnostics remain the shared formalization contracts.

Formal formulas and proof obligations describe candidate properties to check.
They never establish a proof and never grant policy or execution authority.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
import hashlib
from typing import Any, ClassVar, Final

from ...formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompilerConfig,
)
from ...formalization.views import FormalSymbol, SymbolTable
from ..formalization_adapter import (
    SECURITY_IR_CLAIM_VIEW_ID,
    SECURITY_IR_POLICY_VIEW_ID,
    SECURITY_IR_THREAT_VIEW_ID,
    SECURITY_IR_TRANSITION_VIEW_ID,
    SecurityIRFormalizationAdapter,
    SecurityIRFormalizationAdapterError,
)
from .adapter import (
    CVEfixesAdapterResult,
    adapt_cvefixes_candidate,
)
from .vocabulary import (
    CVEFIXES_POLICY_ATTRIBUTES_KEY,
    CVEfixesPolicyAttributes,
    CVEfixesTerm,
    CVEfixesVocabularyError,
)


CVEFIXES_FORMALIZATION_VERSION: Final = "cvefixes-formalization-adapter/v1"
CVEFIXES_DEONTIC_OPERATOR: Final = "F"
CVEFIXES_PROHIBITION_MODALITY: Final = "prohibition"
CVEFIXES_FORMALIZATION_TARGET_VIEWS: Final = (
    SECURITY_IR_CLAIM_VIEW_ID,
    SECURITY_IR_POLICY_VIEW_ID,
    SECURITY_IR_THREAT_VIEW_ID,
    SECURITY_IR_TRANSITION_VIEW_ID,
)


class CVEfixesFormalizationError(ValueError):
    """Raised when CVEfixes semantics cannot be lowered without broadening."""


class CVEfixesControlPolarity(str, Enum):
    """Expected evaluation polarity for vulnerable and fixed controls."""

    VULNERABLE_POSITIVE = "vulnerable_positive"
    FIXED_NEGATIVE = "fixed_negative"


def prohibition_expected_for_control(
    polarity: CVEfixesControlPolarity | str,
) -> bool:
    """Return the expected label without performing or asserting verification.

    The helper makes the vulnerable/fixed evaluation contract explicit:
    vulnerable evidence is a positive control for a candidate prohibition,
    while fixed evidence is always a negative control.  It does not inspect
    code, decide a policy, or turn either control into authoritative evidence.
    """

    aliases = {
        "vulnerable": CVEfixesControlPolarity.VULNERABLE_POSITIVE,
        "fixed": CVEfixesControlPolarity.FIXED_NEGATIVE,
    }
    if isinstance(polarity, str) and not isinstance(
        polarity, CVEfixesControlPolarity
    ):
        polarity = aliases.get(polarity, polarity)
    try:
        normalized = (
            polarity
            if isinstance(polarity, CVEfixesControlPolarity)
            else CVEfixesControlPolarity(polarity)
        )
    except (TypeError, ValueError) as exc:
        raise CVEfixesFormalizationError(
            f"unsupported control polarity: {polarity!r}"
        ) from exc
    return normalized is CVEfixesControlPolarity.VULNERABLE_POSITIVE


def _validated_result(value: Any) -> CVEfixesAdapterResult:
    if not isinstance(value, CVEfixesAdapterResult):
        raise CVEfixesFormalizationError(
            "formalization requires a CVEfixesAdapterResult"
        )
    try:
        rebuilt = adapt_cvefixes_candidate(
            value.candidate,
            sources=value.sources,
            review=value.review,
            declaration_id=value.declaration.declaration_id,
        )
    except (TypeError, ValueError) as exc:
        raise CVEfixesFormalizationError(
            f"invalid CVEfixes adapter result: {exc}"
        ) from exc
    if rebuilt.declaration.to_dict() != value.declaration.to_dict():
        raise CVEfixesFormalizationError(
            "CVEfixes declaration does not match its candidate/source/review "
            "binding"
        )
    return value


def _policy_attributes(result: CVEfixesAdapterResult) -> CVEfixesPolicyAttributes:
    if len(result.declaration.policies) != 1:
        raise CVEfixesFormalizationError(
            "CVEfixes declaration must contain exactly one candidate policy"
        )
    policy = result.declaration.policies[0]
    raw = policy.attributes.get(CVEFIXES_POLICY_ATTRIBUTES_KEY)
    try:
        attributes = CVEfixesPolicyAttributes.from_dict(raw)
        return attributes.require_exact_policy_constraints()
    except (CVEfixesVocabularyError, TypeError, AttributeError) as exc:
        raise CVEfixesFormalizationError(
            "candidate policy has no complete typed CVEfixes scope"
        ) from exc


def _typed_terms(attributes: CVEfixesPolicyAttributes) -> tuple[CVEfixesTerm, ...]:
    values = [
        attributes.action,
        *attributes.preconditions,
        *attributes.effects,
        *attributes.mitigations,
        attributes.language,
        attributes.scope,
        *attributes.cve_ids,
        *attributes.cwe_ids,
    ]
    return tuple(
        sorted(
            (item for item in values if item is not None),
            key=lambda item: item.canonical,
        )
    )


def _symbol_id(candidate_digest: str, term: CVEfixesTerm) -> str:
    digest = hashlib.sha256(term.canonical.encode("utf-8")).hexdigest()[:20]
    return (
        f"symbol:cvefixes:{candidate_digest[:24]}:"
        f"{term.kind.value}:{digest}"
    )


def _term_symbol(
    result: CVEfixesAdapterResult,
    term: CVEfixesTerm,
    *,
    source_ref_ids: tuple[str, ...],
    exact_scope: str,
) -> FormalSymbol:
    return FormalSymbol(
        symbol_id=_symbol_id(result.candidate.digest, term),
        name=term.canonical,
        kind="constant",
        sort=f"cvefixes_{term.kind.value}",
        source_ref_ids=source_ref_ids,
        metadata={
            "candidate_cid": result.candidate.cid,
            "exact_scope": exact_scope,
            "grants_execution_authority": False,
            "term": term.to_dict(),
            "vocabulary_role": term.policy_role.value,
        },
    )


def _non_authoritative_metadata(value: Any) -> dict[str, Any]:
    metadata = value.to_dict() if hasattr(value, "to_dict") else dict(value)
    return {
        **metadata,
        "authoritative": False,
        "grants_execution_authority": False,
        "proof_authoritative": False,
    }


def _specialize_artifact(
    artifact: FormalizationArtifact,
    result: CVEfixesAdapterResult,
    attributes: CVEfixesPolicyAttributes,
) -> FormalizationArtifact:
    """Specialize shared policy output while retaining all shared contracts."""

    policy_formulas = tuple(
        formula
        for formula in artifact.formulas
        if formula.view_id == SECURITY_IR_POLICY_VIEW_ID
        and formula.metadata.get("security_construct") == "policy"
    )
    if len(policy_formulas) != 1:
        raise CVEfixesFormalizationError(
            "shared Security IR adapter did not emit exactly one policy formula"
        )
    policy_formula = policy_formulas[0]
    exact_scope = attributes.scope.canonical
    typed_symbols = tuple(
        _term_symbol(
            result,
            term,
            source_ref_ids=policy_formula.source_ref_ids,
            exact_scope=exact_scope,
        )
        for term in _typed_terms(attributes)
    )
    typed_symbol_ids = tuple(item.symbol_id for item in typed_symbols)
    typed_scope = attributes.to_dict()

    formulas = []
    for formula in artifact.formulas:
        metadata = _non_authoritative_metadata(formula.metadata)
        if formula.formula_id == policy_formula.formula_id:
            formulas.append(
                replace(
                    formula,
                    expression={
                        "action": attributes.action.to_dict(),
                        "candidate_cid": result.candidate.cid,
                        "classifications": {
                            "cve_ids": [
                                item.to_dict() for item in attributes.cve_ids
                            ],
                            "cwe_ids": [
                                item.to_dict() for item in attributes.cwe_ids
                            ],
                        },
                        "deontic_operator": CVEFIXES_DEONTIC_OPERATOR,
                        "effects": [
                            item.to_dict() for item in attributes.effects
                        ],
                        "grants_execution_authority": False,
                        "kind": "deontic_prohibition",
                        "language": (
                            attributes.language.to_dict()
                            if attributes.language is not None
                            else None
                        ),
                        "mitigations": [
                            item.to_dict() for item in attributes.mitigations
                        ],
                        "modality": CVEFIXES_PROHIBITION_MODALITY,
                        "policy": result.declaration.policies[0].to_dict(),
                        "preconditions": [
                            item.to_dict() for item in attributes.preconditions
                        ],
                        "source_policy_effect": "deny",
                        "typed_scope": typed_scope,
                        "typed_symbol_ids": list(typed_symbol_ids),
                    },
                    symbol_ids=typed_symbol_ids,
                    metadata={
                        **metadata,
                        "cvefixes_formalization_version": (
                            CVEFIXES_FORMALIZATION_VERSION
                        ),
                        "deontic_operator": CVEFIXES_DEONTIC_OPERATOR,
                        "exact_scope": exact_scope,
                        "modality": CVEFIXES_PROHIBITION_MODALITY,
                    },
                )
            )
        else:
            formulas.append(replace(formula, metadata=metadata))

    obligations = tuple(
        replace(
            obligation,
            metadata={
                **_non_authoritative_metadata(obligation.metadata),
                "candidate_cid": result.candidate.cid,
                "cvefixes_formalization_version": CVEFIXES_FORMALIZATION_VERSION,
            },
        )
        for obligation in artifact.proof_obligations
    )
    symbol_table = SymbolTable(
        table_id=artifact.symbol_table.table_id,
        symbols=(
            *(
                symbol
                for symbol in artifact.symbol_table.symbols
                if symbol.symbol_id not in policy_formula.symbol_ids
            ),
            *typed_symbols,
        ),
        metadata={
            **artifact.symbol_table.metadata.to_dict(),
            "cvefixes_formalization_version": CVEFIXES_FORMALIZATION_VERSION,
            "exact_scope": exact_scope,
            "grants_execution_authority": False,
        },
        schema_version=artifact.symbol_table.schema_version,
    )
    return replace(
        artifact,
        symbol_table=symbol_table,
        formulas=tuple(formulas),
        proof_obligations=obligations,
        metadata={
            **artifact.metadata.to_dict(),
            "authoritative": False,
            "candidate_cid": result.candidate.cid,
            "cvefixes_formalization_version": CVEFIXES_FORMALIZATION_VERSION,
            "grants_execution_authority": False,
            "proof_authoritative": False,
        },
    )


class CVEfixesFormalizationAdapter:
    """Lower one canonical CVEfixes adapter result through shared IR views."""

    proof_authoritative: ClassVar[bool] = False
    grants_execution_authority: ClassVar[bool] = False
    authority: ClassVar[str] = "candidate"

    def __init__(
        self,
        shared_adapter: SecurityIRFormalizationAdapter | None = None,
    ) -> None:
        if shared_adapter is not None and not isinstance(
            shared_adapter, SecurityIRFormalizationAdapter
        ):
            raise CVEfixesFormalizationError(
                "shared_adapter must be SecurityIRFormalizationAdapter"
            )
        self._shared_adapter = shared_adapter or SecurityIRFormalizationAdapter()

    def default_config(
        self, result: CVEfixesAdapterResult
    ) -> FormalizationCompilerConfig:
        """Request every Security view so absent semantics get diagnostics."""

        result = _validated_result(result)
        sample = self._shared_adapter.adapt_sample(result.declaration)
        base = self._shared_adapter.default_config(sample)
        return replace(
            base,
            target_view_ids=CVEFIXES_FORMALIZATION_TARGET_VIEWS,
            options={
                **base.options.to_dict(),
                "cvefixes_formalization_version": (
                    CVEFIXES_FORMALIZATION_VERSION
                ),
                "domain_specialization": "security.cvefixes",
                "proof_backend_execution": False,
                "result_artifacts_are_features": False,
            },
        )

    def adapt(
        self,
        result: CVEfixesAdapterResult,
        config: FormalizationCompilerConfig | None = None,
    ) -> FormalizationArtifact:
        """Return a deterministic, solver-neutral shared formalization artifact."""

        result = _validated_result(result)
        attributes = _policy_attributes(result)
        sample = self._shared_adapter.adapt_sample(result.declaration)
        resolved_config = config or self.default_config(result)
        try:
            artifact = self._shared_adapter.compile(sample, resolved_config)
        except (SecurityIRFormalizationAdapterError, TypeError, ValueError) as exc:
            raise CVEfixesFormalizationError(
                f"shared Security IR formalization failed: {exc}"
            ) from exc
        return _specialize_artifact(artifact, result, attributes)

    # Domain-appropriate and shared-adapter-compatible spellings.
    formalize = adapt
    adapt_artifact = adapt


def formalize_cvefixes_candidate(
    result: CVEfixesAdapterResult,
    config: FormalizationCompilerConfig | None = None,
) -> FormalizationArtifact:
    """Functional convenience wrapper for :class:`CVEfixesFormalizationAdapter`."""

    return CVEfixesFormalizationAdapter().adapt(result, config)


# Concise compatibility spelling.
formalize_cvefixes_security_ir = formalize_cvefixes_candidate


__all__ = [
    "CVEFIXES_DEONTIC_OPERATOR",
    "CVEFIXES_FORMALIZATION_TARGET_VIEWS",
    "CVEFIXES_FORMALIZATION_VERSION",
    "CVEFIXES_PROHIBITION_MODALITY",
    "CVEfixesControlPolarity",
    "CVEfixesFormalizationAdapter",
    "CVEfixesFormalizationError",
    "formalize_cvefixes_candidate",
    "formalize_cvefixes_security_ir",
    "prohibition_expected_for_control",
]

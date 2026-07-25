"""Deterministic acceptance policy for Security verification portfolios.

Iteration order is not a policy.  This module validates a complete set of
typed results, groups it by backend, and accepts a verdict only when the
configured backend set has one unambiguous conclusion.  Canonical sorting is
used solely to choose the representative record after consensus; it never
chooses between conflicting logical verdicts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import BoundedResult, ResultStatus
from .results import (
    SECURITY_RESULT_INTERFACE_VERSION,
    SecurityResult,
    SecurityResultFamily,
    SecurityResultValidationError,
    result_family,
)


SECURITY_RESULT_POLICY_VERSION: Final = "security-result-policy/v1"


@dataclass(frozen=True, slots=True)
class ResultSelectionPolicy:
    """Explicit backend participation and result-family requirements."""

    policy_id: str
    family: SecurityResultFamily
    required_backend_ids: tuple[str, ...]
    allowed_backend_ids: tuple[str, ...] = ()
    configuration: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SECURITY_RESULT_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id.strip()
            or self.policy_id != self.policy_id.strip()
        ):
            raise SecurityResultValidationError(
                "policy_id must be a non-empty trimmed string"
            )
        object.__setattr__(self, "family", SecurityResultFamily(self.family))
        for field_name in ("required_backend_ids", "allowed_backend_ids"):
            values = getattr(self, field_name)
            if isinstance(values, (str, bytes, bytearray)) or not isinstance(
                values, Sequence
            ):
                raise SecurityResultValidationError(
                    f"{field_name} must be a sequence of backend identifiers"
                )
            normalized = tuple(sorted(values))
            if any(
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                for value in normalized
            ):
                raise SecurityResultValidationError(
                    f"{field_name} must contain non-empty trimmed strings"
                )
            if len(normalized) != len(set(normalized)):
                raise SecurityResultValidationError(
                    f"{field_name} must contain unique values"
                )
            object.__setattr__(self, field_name, normalized)
        if not self.required_backend_ids:
            raise SecurityResultValidationError(
                "required_backend_ids must not be empty"
            )
        if self.allowed_backend_ids and not set(
            self.required_backend_ids
        ).issubset(self.allowed_backend_ids):
            raise SecurityResultValidationError(
                "required backends must be included in allowed_backend_ids"
            )
        object.__setattr__(
            self,
            "configuration",
            self.configuration
            if isinstance(self.configuration, FrozenMap)
            else FrozenMap(self.configuration),
        )
        if self.schema_version != SECURITY_RESULT_POLICY_VERSION:
            raise SecurityResultValidationError(
                f"unsupported result policy version: {self.schema_version}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_backend_ids": list(self.allowed_backend_ids),
            "configuration": self.configuration.to_dict(),
            "family": self.family.value,
            "policy_id": self.policy_id,
            "required_backend_ids": list(self.required_backend_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResultSelectionPolicy":
        if not isinstance(value, Mapping):
            raise SecurityResultValidationError("result policy must be a mapping")
        allowed = {
            "allowed_backend_ids",
            "configuration",
            "family",
            "policy_id",
            "required_backend_ids",
            "schema_version",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SecurityResultValidationError(
                f"unknown result policy field(s): {', '.join(unknown)}"
            )
        return cls(
            policy_id=value.get("policy_id", ""),
            family=value.get("family", ""),
            required_backend_ids=tuple(value.get("required_backend_ids", ())),
            allowed_backend_ids=tuple(value.get("allowed_backend_ids", ())),
            configuration=FrozenMap(value.get("configuration", {})),
            schema_version=value.get(
                "schema_version", SECURITY_RESULT_POLICY_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioVerdict:
    """Order-independent outcome of applying one selection policy."""

    policy_digest: str
    family: SecurityResultFamily
    status: ResultStatus
    accepted_result: SecurityResult | None
    considered_result_digests: tuple[str, ...]
    backend_result_digests: FrozenMap
    diagnostics: tuple[str, ...]
    schema_version: str = SECURITY_RESULT_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", SecurityResultFamily(self.family))
        object.__setattr__(self, "status", ResultStatus(self.status))
        if self.accepted_result is not None and not isinstance(
            self.accepted_result, BoundedResult
        ):
            raise SecurityResultValidationError(
                "accepted_result must be a bounded result"
            )
        if tuple(sorted(set(self.considered_result_digests))) != tuple(
            self.considered_result_digests
        ):
            raise SecurityResultValidationError(
                "considered_result_digests must be sorted and unique"
            )
        object.__setattr__(
            self,
            "backend_result_digests",
            self.backend_result_digests
            if isinstance(self.backend_result_digests, FrozenMap)
            else FrozenMap(self.backend_result_digests),
        )
        if not self.diagnostics:
            raise SecurityResultValidationError(
                "portfolio verdict requires explicit diagnostics"
            )
        if self.schema_version != SECURITY_RESULT_POLICY_VERSION:
            raise SecurityResultValidationError(
                f"unsupported portfolio verdict version: {self.schema_version}"
            )

    @property
    def accepted(self) -> bool:
        return self.accepted_result is not None

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_result_digest": (
                self.accepted_result.digest if self.accepted_result else ""
            ),
            "backend_result_digests": self.backend_result_digests.to_dict(),
            "considered_result_digests": list(self.considered_result_digests),
            "diagnostics": list(self.diagnostics),
            "family": self.family.value,
            "policy_digest": self.policy_digest,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


def _fallback_status(family: SecurityResultFamily, *, error: bool) -> ResultStatus:
    if error:
        return ResultStatus.ERROR
    return ResultStatus.UNKNOWN


def select_portfolio_result(
    results: Iterable[SecurityResult],
    policy: ResultSelectionPolicy,
) -> PortfolioVerdict:
    """Select a result by complete-set consensus, independent of input order.

    Results must describe the same request, declaration, claim, obligation,
    assumptions, and authority family.  Every required backend must contribute
    exactly one conclusion.  Duplicate/conflicting backend records,
    disagreement, missing backends, or mixed scopes fail closed with no
    accepted result.
    """

    if not isinstance(policy, ResultSelectionPolicy):
        raise TypeError("policy must be a ResultSelectionPolicy")
    candidates = tuple(results)
    if any(not isinstance(result, BoundedResult) for result in candidates):
        raise TypeError("results must contain only bounded Security results")

    ordered = tuple(sorted(candidates, key=lambda result: result.digest))
    considered = tuple(sorted({result.digest for result in ordered}))
    by_backend: dict[str, list[SecurityResult]] = {}
    diagnostics: list[str] = []

    for result in ordered:
        try:
            candidate_family = result_family(result)
        except SecurityResultValidationError:
            diagnostics.append(
                f"security.result.unsupported_type:{type(result).__name__}"
            )
            continue
        if candidate_family is not policy.family:
            diagnostics.append(
                "security.result.family_mismatch:"
                f"{result.backend_id}:{candidate_family.value}"
            )
            continue
        if (
            policy.allowed_backend_ids
            and result.backend_id not in policy.allowed_backend_ids
        ):
            diagnostics.append(
                f"security.result.backend_not_allowed:{result.backend_id}"
            )
            continue
        by_backend.setdefault(result.backend_id, []).append(result)

    missing = sorted(set(policy.required_backend_ids) - set(by_backend))
    diagnostics.extend(
        f"security.result.required_backend_missing:{backend_id}"
        for backend_id in missing
    )

    duplicate_backends = sorted(
        backend_id for backend_id, values in by_backend.items() if len(values) != 1
    )
    diagnostics.extend(
        f"security.result.ambiguous_backend_output:{backend_id}"
        for backend_id in duplicate_backends
    )

    required_results = [
        by_backend[backend_id][0]
        for backend_id in policy.required_backend_ids
        if backend_id in by_backend and len(by_backend[backend_id]) == 1
    ]
    scope_keys = {
        (
            result.request_digest,
            result.claim_digest,
            result.declaration_id,
            result.obligation_id,
            result.obligation_digest,
            result.assumption_ids,
            result.authority.kind,
        )
        for result in required_results
    }
    if len(scope_keys) > 1:
        diagnostics.append("security.result.portfolio_scope_mismatch")

    statuses = {result.status for result in required_results}
    if len(statuses) > 1:
        rendered = ",".join(sorted(status.value for status in statuses))
        diagnostics.append(f"security.result.solver_disagreement:{rendered}")

    blocking_error = bool(
        missing
        or duplicate_backends
        or len(scope_keys) > 1
        or len(statuses) > 1
        or any(item.startswith("security.result.family_mismatch:") for item in diagnostics)
        or any(
            item.startswith("security.result.unsupported_type:")
            for item in diagnostics
        )
        or any(
            item.startswith("security.result.backend_not_allowed:")
            for item in diagnostics
        )
    )
    if blocking_error or len(required_results) != len(policy.required_backend_ids):
        status = _fallback_status(
            policy.family,
            error=bool(
                duplicate_backends
                or len(scope_keys) > 1
                or len(statuses) > 1
            ),
        )
        accepted_result = None
        diagnostics.append("security.result.portfolio_rejected")
    else:
        status = required_results[0].status
        # Canonical tie-breaking chooses only which agreeing result record is
        # returned. It cannot alter the already established logical status.
        accepted_result = min(required_results, key=lambda result: result.digest)
        diagnostics.append("security.result.portfolio_consensus")

    backend_digests: dict[str, list[str]] = {
        backend_id: sorted(result.digest for result in backend_results)
        for backend_id, backend_results in sorted(by_backend.items())
    }
    return PortfolioVerdict(
        policy_digest=policy.digest,
        family=policy.family,
        status=status,
        accepted_result=accepted_result,
        considered_result_digests=considered,
        backend_result_digests=FrozenMap(backend_digests),
        diagnostics=tuple(sorted(set(diagnostics))),
    )


class SecurityResultAuthority:
    """Named SecurityResultAuthority@1 facade for portfolio evaluation."""

    interface_version: Final = SECURITY_RESULT_INTERFACE_VERSION

    @staticmethod
    def select(
        results: Iterable[SecurityResult],
        policy: ResultSelectionPolicy,
    ) -> PortfolioVerdict:
        return select_portfolio_result(results, policy)


# Descriptive aliases for downstream callers.
ResultPolicy = ResultSelectionPolicy
select_authoritative_result = select_portfolio_result


__all__ = [
    "PortfolioVerdict",
    "ResultPolicy",
    "ResultSelectionPolicy",
    "SECURITY_RESULT_POLICY_VERSION",
    "SecurityResultAuthority",
    "select_authoritative_result",
    "select_portfolio_result",
]

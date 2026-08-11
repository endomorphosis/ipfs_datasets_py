"""Fail-closed V5 issuance request types and authenticated issuer boundary.

Issuance never runs trusted setup, builds a binary, downloads parameters, or
turns a provider claim / boolean / callable into a certificate.  Missing local
artifacts yield an explicit deferred RUN disposition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from .statements.test_pass import TestPassPrivateWitnessV5, TestPassStatementV5
from .test_certificate_assurance import (
    LocalRunnerAttestationAssurance,
    is_locally_verified_runner_assurance,
    verify_local_runner_attestation_v5,
)
from .test_pass_groth16_provider import (
    NativeGroth16V5Capability,
    NativeGroth16V5Proof,
    NativeGroth16V5Provider,
    NativeGroth16V5Status,
    is_native_groth16_v5_provider,
)

DEFERRED_TEST_CERTIFICATE_REQUEST_INTERFACE: Final = "DeferredTestCertificateRequest@1"
TEST_CERTIFICATE_ISSUER_FACTORY_INTERFACE: Final = "TestCertificateIssuerFactory@2"
AUTHENTICATED_TEST_CERTIFICATE_ISSUER_INTERFACE: Final = "AuthenticatedTestCertificateIssuer@1"


class CertificateIssueAction(StrEnum):
    RUN = "RUN"
    DEFERRED = "DEFERRED"
    ISSUED = "ISSUED"


class CertificateIssuanceStatus(StrEnum):
    DEFERRED = "deferred"
    REJECTED = "rejected"
    ISSUED = "issued"


class CertificateIssuanceReason(StrEnum):
    NATIVE_RELEASE_DEFERRED = "native_release_deferred"
    ASSURANCE_REJECTED = "assurance_rejected"
    PROVIDER_REJECTED = "provider_rejected"
    ISSUED = "issued"
    INVALID_PROVIDER = "invalid_provider"


@dataclass(frozen=True, slots=True)
class CertificateIssuanceDisposition:
    status: CertificateIssuanceStatus
    reason: CertificateIssuanceReason
    detail: str = ""
    proof: NativeGroth16V5Proof | None = None

    @property
    def action(self) -> CertificateIssueAction:
        if self.status is CertificateIssuanceStatus.ISSUED:
            return CertificateIssueAction.ISSUED
        if self.status is CertificateIssuanceStatus.DEFERRED:
            return CertificateIssueAction.DEFERRED
        return CertificateIssueAction.RUN

    @property
    def can_authorize_skip(self) -> bool:
        return False  # issuance alone never authorizes skip; verification does

    def __bool__(self) -> bool:  # pragma: no cover
        raise TypeError("inspect disposition fields; not truthy authority")


@dataclass(frozen=True, slots=True)
class DeferredTestCertificateRequest:
    statement: TestPassStatementV5
    witness: TestPassPrivateWitnessV5
    reason: str
    interface: str = DEFERRED_TEST_CERTIFICATE_REQUEST_INTERFACE

    def __post_init__(self) -> None:
        if self.interface != DEFERRED_TEST_CERTIFICATE_REQUEST_INTERFACE:
            raise ValueError("unsupported deferred certificate request")
        if not isinstance(self.statement, TestPassStatementV5) or not isinstance(
            self.witness, TestPassPrivateWitnessV5
        ):
            raise TypeError("only V5 typed statement/witness may request issuance")
        if not isinstance(self.reason, str) or not self.reason or len(self.reason) > 512:
            raise ValueError("deferred request reason must be bounded text")

    @property
    def action(self) -> CertificateIssueAction:
        return CertificateIssueAction.DEFERRED

    @property
    def can_authorize_skip(self) -> bool:
        return False


def request_test_certificate_v5(
    statement: TestPassStatementV5,
    witness: TestPassPrivateWitnessV5,
    provider: Any,
) -> DeferredTestCertificateRequest:
    """Return an explicit defer rather than performing implicit setup/proving."""

    if not is_native_groth16_v5_provider(provider):
        raise TypeError("V5 issuance requires the pinned native Groth16 provider")
    statement.assert_witness_satisfies(witness)
    capability = provider.capability()
    return DeferredTestCertificateRequest(statement, witness, capability.reason)


@dataclass(frozen=True, slots=True)
class AuthenticatedTestCertificateIssuer:
    """Issues only through the concrete native provider after local assurance."""

    provider: NativeGroth16V5Provider
    interface: str = AUTHENTICATED_TEST_CERTIFICATE_ISSUER_INTERFACE

    def __post_init__(self) -> None:
        if not is_native_groth16_v5_provider(self.provider):
            raise TypeError("issuer requires NativeGroth16V5Provider")

    def issue(
        self,
        statement: TestPassStatementV5,
        witness: TestPassPrivateWitnessV5,
        *,
        policy_bytes: bytes,
        pinned_policy_cid: str,
        pinned_public_key_material: bytes,
        candidate_context_cid: str | None = None,
        now: int | None = None,
        seed: int = 1,
    ) -> CertificateIssuanceDisposition:
        if not isinstance(statement, TestPassStatementV5) or not isinstance(
            witness, TestPassPrivateWitnessV5
        ):
            return CertificateIssuanceDisposition(
                CertificateIssuanceStatus.REJECTED,
                CertificateIssuanceReason.PROVIDER_REJECTED,
                "only V5 typed statement/witness accepted",
            )
        assurance = verify_local_runner_attestation_v5(
            statement,
            witness,
            policy_bytes=policy_bytes,
            pinned_policy_cid=pinned_policy_cid,
            pinned_public_key_material=pinned_public_key_material,
            candidate_context_cid=candidate_context_cid,
            now=now,
        )
        if not is_locally_verified_runner_assurance(assurance):
            return CertificateIssuanceDisposition(
                CertificateIssuanceStatus.REJECTED,
                CertificateIssuanceReason.ASSURANCE_REJECTED,
                assurance.reason,
            )
        outcome = self.provider.prove(statement, witness, seed=seed)
        if isinstance(outcome, NativeGroth16V5Capability):
            if outcome.status is NativeGroth16V5Status.DEFERRED:
                return CertificateIssuanceDisposition(
                    CertificateIssuanceStatus.DEFERRED,
                    CertificateIssuanceReason.NATIVE_RELEASE_DEFERRED,
                    outcome.reason,
                )
            return CertificateIssuanceDisposition(
                CertificateIssuanceStatus.REJECTED,
                CertificateIssuanceReason.PROVIDER_REJECTED,
                outcome.reason,
            )
        if not isinstance(outcome, NativeGroth16V5Proof):
            return CertificateIssuanceDisposition(
                CertificateIssuanceStatus.REJECTED,
                CertificateIssuanceReason.PROVIDER_REJECTED,
                "provider did not return a typed native proof",
            )
        return CertificateIssuanceDisposition(
            CertificateIssuanceStatus.ISSUED,
            CertificateIssuanceReason.ISSUED,
            "typed V5 proof issued under local assurance",
            proof=outcome,
        )


class TestCertificateIssuerFactory:
    """Factory that only admits the concrete native V5 provider."""

    interface: Final = TEST_CERTIFICATE_ISSUER_FACTORY_INTERFACE

    @staticmethod
    def create(provider: Any) -> AuthenticatedTestCertificateIssuer:
        if not is_native_groth16_v5_provider(provider):
            raise TypeError(
                "TestCertificateIssuerFactory@2 only accepts NativeGroth16V5Provider"
            )
        return AuthenticatedTestCertificateIssuer(provider=provider)


__all__ = [
    "AUTHENTICATED_TEST_CERTIFICATE_ISSUER_INTERFACE",
    "AuthenticatedTestCertificateIssuer",
    "CertificateIssuanceDisposition",
    "CertificateIssuanceReason",
    "CertificateIssuanceStatus",
    "CertificateIssueAction",
    "DEFERRED_TEST_CERTIFICATE_REQUEST_INTERFACE",
    "DeferredTestCertificateRequest",
    "TEST_CERTIFICATE_ISSUER_FACTORY_INTERFACE",
    "TestCertificateIssuerFactory",
    "request_test_certificate_v5",
]

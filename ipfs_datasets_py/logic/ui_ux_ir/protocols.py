"""Backend-neutral ports for the UI/UX IR pipeline (UIUXIRProtocols@1).

Implementations may project, formalize, mediate, or store artifacts using
optional runtimes. Keeping those dependencies behind protocols prevents the
modality/binding model from importing device SDKs, ORB call stacks, model
runtimes, or registry mutation surfaces.
"""

from __future__ import annotations

from typing import Any, Final, Mapping, Protocol, runtime_checkable

from .model.bindings import UIActionBinding
from .model.modality import UIModalityContract
from .schema import UIIRDocument

UI_UX_IR_PROTOCOLS_INTERFACE: Final = "UIUXIRProtocols@1"


@runtime_checkable
class UIModalityContractValidator(Protocol):
    """Validate abstract modality capability contracts."""

    def validate_modality_contract(
        self, contract: UIModalityContract
    ) -> UIModalityContract:
        """Return a validated modality contract or raise on unsupported/missing alternatives."""


@runtime_checkable
class UIProgramBindingValidator(Protocol):
    """Validate action/program bindings for one-target non-authorizing semantics."""

    def validate_action_binding(self, binding: UIActionBinding) -> UIActionBinding:
        """Return a validated action binding or raise on multi-target/code/grant payloads."""


@runtime_checkable
class UICapabilityNegotiator(Protocol):
    """Negotiate available capabilities against declared requirements."""

    def negotiate(
        self,
        contract: UIModalityContract,
        available_capability_ids: tuple[str, ...],
    ) -> Mapping[str, Any]:
        """Return a versioned negotiation result with explicit unsupported losses."""


@runtime_checkable
class UIDocumentValidator(Protocol):
    """Validate a closed UI/UX IR document envelope."""

    def validate_document(self, document: UIIRDocument) -> UIIRDocument:
        """Return a validated document or raise on envelope violations."""


@runtime_checkable
class UIProjectionPort(Protocol):
    """Project a document under negotiated capabilities without silent loss."""

    def project(
        self,
        document: UIIRDocument,
        *,
        available_capability_ids: tuple[str, ...],
    ) -> Mapping[str, Any]:
        """Return a projection artifact and explicit loss report."""


@runtime_checkable
class UIFormalizationPort(Protocol):
    """Compile formal views from a validated UI/UX IR document."""

    def formalize(self, document: UIIRDocument) -> Mapping[str, Any]:
        """Return linked formal views with coverage diagnostics."""


@runtime_checkable
class UIArtifactStore(Protocol):
    """Store immutable pipeline artifacts without embedding their bodies."""

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        """Return a CID or other immutable content address."""


@runtime_checkable
class UIUXIRProtocols(Protocol):
    """Aggregate interface identity for UI/UX IR pipeline ports.

    Interface identity: ``UIUXIRProtocols@1``.
    """

    interface: str

    @property
    def modality_validator(self) -> UIModalityContractValidator:
        """Port that validates modality contracts."""

    @property
    def binding_validator(self) -> UIProgramBindingValidator:
        """Port that validates program/action bindings."""

    @property
    def capability_negotiator(self) -> UICapabilityNegotiator:
        """Port that negotiates capability availability."""

    @property
    def document_validator(self) -> UIDocumentValidator:
        """Port that validates document envelopes."""


class DefaultUIModalityContractValidator:
    """Reference modality validator used by unit fixtures."""

    def validate_modality_contract(
        self, contract: UIModalityContract
    ) -> UIModalityContract:
        from .model.modality import validate_modality_contract

        return validate_modality_contract(contract)


class DefaultUIProgramBindingValidator:
    """Reference program-binding validator used by unit fixtures."""

    def validate_action_binding(self, binding: UIActionBinding) -> UIActionBinding:
        from .model.bindings import validate_action_binding

        return validate_action_binding(binding)


class DefaultUIDocumentValidator:
    """Reference document validator that delegates to the envelope schema."""

    def validate_document(self, document: UIIRDocument) -> UIIRDocument:
        from .schema import validate_ui_ir

        return validate_ui_ir(document)


class DefaultUICapabilityNegotiator:
    """Reference negotiator: unsupported required capabilities fail closed."""

    def negotiate(
        self,
        contract: UIModalityContract,
        available_capability_ids: tuple[str, ...],
    ) -> Mapping[str, Any]:
        from .model.modality import (
            CANONICAL_CAPABILITIES,
            require_supported_capability,
            validate_modality_contract,
        )
        from .schema import UIIRValidationError

        validate_modality_contract(contract)
        if not isinstance(available_capability_ids, tuple):
            raise UIIRValidationError(
                "available_capability_ids must be an immutable tuple"
            )

        available: set[str] = set()
        for capability_id in available_capability_ids:
            if capability_id not in CANONICAL_CAPABILITIES:
                raise UIIRValidationError(
                    f"Unsupported capability in negotiation: {capability_id!r}"
                )
            require_supported_capability(capability_id)
            available.add(capability_id)

        missing_essential: list[str] = []
        satisfied: list[str] = []
        for requirement in contract.requirements:
            present = any(
                capability_id in available for capability_id in requirement.capability_ids
            )
            if present:
                satisfied.append(requirement.requirement_id)
                continue
            # Allow an alternative requirement to cover the primary.
            alternative_covers = False
            for alternative in contract.alternatives:
                if alternative.primary_requirement_id != requirement.requirement_id:
                    continue
                alt_req = next(
                    (
                        item
                        for item in contract.requirements
                        if item.requirement_id == alternative.alternative_requirement_id
                    ),
                    None,
                )
                if alt_req is None:
                    continue
                if any(cap in available for cap in alt_req.capability_ids):
                    alternative_covers = True
                    break
            if alternative_covers:
                satisfied.append(requirement.requirement_id)
                continue
            if requirement.essential:
                missing_essential.append(requirement.requirement_id)

        if missing_essential:
            raise UIIRValidationError(
                "Capability negotiation failed; essential requirements unsupported "
                f"with no available alternative: {', '.join(sorted(missing_essential))}"
            )

        return {
            "available_capability_ids": sorted(available),
            "contract_id": contract.contract_id,
            "interface": UI_UX_IR_PROTOCOLS_INTERFACE,
            "satisfied_requirement_ids": sorted(set(satisfied)),
            "status": "satisfied",
        }


class ReferenceUIUXIRProtocols:
    """In-process reference bundle implementing :class:`UIUXIRProtocols`."""

    interface: str = UI_UX_IR_PROTOCOLS_INTERFACE

    def __init__(self) -> None:
        self._modality_validator = DefaultUIModalityContractValidator()
        self._binding_validator = DefaultUIProgramBindingValidator()
        self._capability_negotiator = DefaultUICapabilityNegotiator()
        self._document_validator = DefaultUIDocumentValidator()

    @property
    def modality_validator(self) -> UIModalityContractValidator:
        return self._modality_validator

    @property
    def binding_validator(self) -> UIProgramBindingValidator:
        return self._binding_validator

    @property
    def capability_negotiator(self) -> UICapabilityNegotiator:
        return self._capability_negotiator

    @property
    def document_validator(self) -> UIDocumentValidator:
        return self._document_validator


__all__ = [
    "DefaultUICapabilityNegotiator",
    "DefaultUIDocumentValidator",
    "DefaultUIModalityContractValidator",
    "DefaultUIProgramBindingValidator",
    "ReferenceUIUXIRProtocols",
    "UIArtifactStore",
    "UICapabilityNegotiator",
    "UIDocumentValidator",
    "UIFormalizationPort",
    "UIModalityContractValidator",
    "UIProgramBindingValidator",
    "UIProjectionPort",
    "UIUXIRProtocols",
    "UI_UX_IR_PROTOCOLS_INTERFACE",
]

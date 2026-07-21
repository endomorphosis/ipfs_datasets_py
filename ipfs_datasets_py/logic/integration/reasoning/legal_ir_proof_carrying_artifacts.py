"""Proof-carrying LegalIR artifact envelopes.

This module binds compiler outputs to the proof evidence required to consume
them safely: proof obligations, Hammer guidance, translation records,
reconstruction receipts, unsupported-feature diagnostics, source maps, build
manifests, and an explicit verification policy.  The validator is intentionally
consumer-facing.  It recomputes deterministic hashes from the received payload
and fails closed when evidence is missing, stale, incompatible, or failed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Final

from .hammer_guidance import HAMMER_GUIDANCE_SCHEMA_VERSION, HammerGuidanceArtifact
from .legal_ir_backend_conformance import LegalIRBackendUnsupportedDiagnostic
from .legal_ir_build_manifest import (
    LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION,
    LegalIRBuildManifest,
    validate_legal_ir_build_manifest,
)
from .legal_ir_hammer import LegalIRHammerReport
from .legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    HammerReconstructionReceipt,
    HammerTranslationRecord,
)
from .legal_ir_obligations import (
    LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
    LegalIRProofObligation,
)
from .legal_ir_proof_router import LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION
from .legal_ir_source_maps import (
    LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
    LegalIRSourceMap,
    trace_legal_ir_fact,
    validate_legal_ir_source_map,
)


LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION: Final = (
    "legal-ir-proof-carrying-artifact-v1"
)
LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION: Final = (
    "legal-ir-proof-verification-policy-v1"
)


class LegalIRProofArtifactError(ValueError):
    """Raised when a proof-carrying LegalIR artifact cannot be trusted."""


class LegalIRProofArtifactDiagnosticSeverity(str, Enum):
    """Validation severity values for proof-carrying artifacts."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class LegalIRProofArtifactDiagnostic:
    """One deterministic consumer-side validation diagnostic."""

    code: str
    message: str
    field_path: str = ""
    severity: str = LegalIRProofArtifactDiagnosticSeverity.ERROR.value
    obligation_id: str = ""
    evidence_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def error(self) -> bool:
        return str(self.severity or "").lower() == LegalIRProofArtifactDiagnosticSeverity.ERROR.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "evidence_id": self.evidence_id,
            "field_path": self.field_path,
            "message": self.message,
            "metadata": _json_ready(self.metadata),
            "obligation_id": self.obligation_id,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRProofArtifactDiagnostic":
        return cls(
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            field_path=str(data.get("field_path") or ""),
            severity=str(
                data.get("severity") or LegalIRProofArtifactDiagnosticSeverity.ERROR.value
            ),
            obligation_id=str(data.get("obligation_id") or ""),
            evidence_id=str(data.get("evidence_id") or ""),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True)
class LegalIRProofVerificationPolicy:
    """Explicit accept/reject policy carried with a LegalIR artifact."""

    policy_id: str = ""
    require_build_manifest: bool = True
    require_valid_build_manifest: bool = True
    require_build_output_binding: bool = True
    require_source_map: bool = True
    require_source_traceability: bool = True
    require_hammer_guidance: bool = True
    require_hammer_receipts: bool = True
    require_translation_records: bool = True
    require_reconstruction_status: bool = True
    require_all_obligations_proved: bool = True
    require_trusted_proofs: bool = False
    require_native_reconstruction: bool = False
    require_native_reconstruction_verified: bool = False
    require_route_results: bool = False
    require_typed_unsupported_diagnostics: bool = True
    allow_typed_unsupported_obligations: bool = False
    accepted_build_ids: tuple[str, ...] = ()
    accepted_compiler_commits: tuple[str, ...] = ()
    expected_build_manifest_sha256: str = ""
    expected_legal_ir_output_sha256: str = ""
    component_schema_versions: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_build_ids",
            tuple(dict.fromkeys(str(item) for item in self.accepted_build_ids if str(item))),
        )
        object.__setattr__(
            self,
            "accepted_compiler_commits",
            tuple(
                dict.fromkeys(str(item) for item in self.accepted_compiler_commits if str(item))
            ),
        )
        defaults = {
            "build_manifest": LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION,
            "hammer_guidance": HAMMER_GUIDANCE_SCHEMA_VERSION,
            "hammer_reconstruction_receipt": (
                LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
            ),
            "hammer_translation": LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
            "proof_carrying_artifact": LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION,
            "proof_obligation": LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
            "proof_router": LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
            "source_map": LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
        }
        defaults.update({str(key): str(value) for key, value in self.component_schema_versions.items()})
        object.__setattr__(self, "component_schema_versions", dict(sorted(defaults.items())))

    @property
    def policy_sha256(self) -> str:
        return _stable_hash(self.to_dict(include_policy_sha256=False))

    def to_dict(self, *, include_policy_sha256: bool = True) -> dict[str, Any]:
        payload = {
            "accepted_build_ids": list(self.accepted_build_ids),
            "accepted_compiler_commits": list(self.accepted_compiler_commits),
            "allow_typed_unsupported_obligations": bool(
                self.allow_typed_unsupported_obligations
            ),
            "component_schema_versions": _json_ready(self.component_schema_versions),
            "expected_build_manifest_sha256": self.expected_build_manifest_sha256,
            "expected_legal_ir_output_sha256": self.expected_legal_ir_output_sha256,
            "metadata": _json_ready(self.metadata),
            "policy_id": self.policy_id,
            "require_all_obligations_proved": bool(self.require_all_obligations_proved),
            "require_build_manifest": bool(self.require_build_manifest),
            "require_build_output_binding": bool(self.require_build_output_binding),
            "require_hammer_guidance": bool(self.require_hammer_guidance),
            "require_hammer_receipts": bool(self.require_hammer_receipts),
            "require_native_reconstruction": bool(self.require_native_reconstruction),
            "require_native_reconstruction_verified": bool(
                self.require_native_reconstruction_verified
            ),
            "require_reconstruction_status": bool(self.require_reconstruction_status),
            "require_route_results": bool(self.require_route_results),
            "require_source_map": bool(self.require_source_map),
            "require_source_traceability": bool(self.require_source_traceability),
            "require_translation_records": bool(self.require_translation_records),
            "require_trusted_proofs": bool(self.require_trusted_proofs),
            "require_typed_unsupported_diagnostics": bool(
                self.require_typed_unsupported_diagnostics
            ),
            "require_valid_build_manifest": bool(self.require_valid_build_manifest),
            "schema_version": self.schema_version,
        }
        if include_policy_sha256:
            payload["policy_sha256"] = self.policy_sha256
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRProofVerificationPolicy":
        return cls(
            policy_id=str(data.get("policy_id") or ""),
            require_build_manifest=bool(data.get("require_build_manifest", True)),
            require_valid_build_manifest=bool(data.get("require_valid_build_manifest", True)),
            require_build_output_binding=bool(data.get("require_build_output_binding", True)),
            require_source_map=bool(data.get("require_source_map", True)),
            require_source_traceability=bool(data.get("require_source_traceability", True)),
            require_hammer_guidance=bool(data.get("require_hammer_guidance", True)),
            require_hammer_receipts=bool(data.get("require_hammer_receipts", True)),
            require_translation_records=bool(data.get("require_translation_records", True)),
            require_reconstruction_status=bool(data.get("require_reconstruction_status", True)),
            require_all_obligations_proved=bool(
                data.get("require_all_obligations_proved", True)
            ),
            require_trusted_proofs=bool(data.get("require_trusted_proofs", False)),
            require_native_reconstruction=bool(data.get("require_native_reconstruction", False)),
            require_native_reconstruction_verified=bool(
                data.get("require_native_reconstruction_verified", False)
            ),
            require_route_results=bool(data.get("require_route_results", False)),
            require_typed_unsupported_diagnostics=bool(
                data.get("require_typed_unsupported_diagnostics", True)
            ),
            allow_typed_unsupported_obligations=bool(
                data.get("allow_typed_unsupported_obligations", False)
            ),
            accepted_build_ids=tuple(str(item) for item in _sequence(data.get("accepted_build_ids"))),
            accepted_compiler_commits=tuple(
                str(item) for item in _sequence(data.get("accepted_compiler_commits"))
            ),
            expected_build_manifest_sha256=str(data.get("expected_build_manifest_sha256") or ""),
            expected_legal_ir_output_sha256=str(
                data.get("expected_legal_ir_output_sha256") or ""
            ),
            component_schema_versions=_mapping(data.get("component_schema_versions")),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True)
class LegalIRProofEvidenceBinding:
    """Per-obligation index of the proof evidence carried by an artifact."""

    obligation_id: str
    formula_id: str = ""
    guidance_ids: tuple[str, ...] = ()
    translation_record_ids: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    route_status: str = ""
    route_trust_satisfied: bool = False
    proved: bool = False
    trusted: bool = False
    backend_proved: bool = False
    native_reconstruction: bool = False
    native_reconstruction_verified: bool = False
    reconstruction_status: str = ""
    unsupported_diagnostic_keys: tuple[str, ...] = ()
    source_traceable: bool = False
    source_fact_ids: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_proved": bool(self.backend_proved),
            "failure_reasons": list(self.failure_reasons),
            "formula_id": self.formula_id,
            "guidance_ids": list(self.guidance_ids),
            "metadata": _json_ready(self.metadata),
            "native_reconstruction": bool(self.native_reconstruction),
            "native_reconstruction_verified": bool(self.native_reconstruction_verified),
            "obligation_id": self.obligation_id,
            "proved": bool(self.proved),
            "receipt_ids": list(self.receipt_ids),
            "reconstruction_status": self.reconstruction_status,
            "route_status": self.route_status,
            "route_trust_satisfied": bool(self.route_trust_satisfied),
            "source_fact_ids": list(self.source_fact_ids),
            "source_traceable": bool(self.source_traceable),
            "translation_record_ids": list(self.translation_record_ids),
            "trusted": bool(self.trusted),
            "unsupported_diagnostic_keys": list(self.unsupported_diagnostic_keys),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRProofEvidenceBinding":
        return cls(
            obligation_id=str(data.get("obligation_id") or ""),
            formula_id=str(data.get("formula_id") or ""),
            guidance_ids=tuple(str(item) for item in _sequence(data.get("guidance_ids"))),
            translation_record_ids=tuple(
                str(item) for item in _sequence(data.get("translation_record_ids"))
            ),
            receipt_ids=tuple(str(item) for item in _sequence(data.get("receipt_ids"))),
            route_status=str(data.get("route_status") or ""),
            route_trust_satisfied=bool(data.get("route_trust_satisfied")),
            proved=bool(data.get("proved")),
            trusted=bool(data.get("trusted")),
            backend_proved=bool(data.get("backend_proved")),
            native_reconstruction=bool(data.get("native_reconstruction")),
            native_reconstruction_verified=bool(data.get("native_reconstruction_verified")),
            reconstruction_status=str(data.get("reconstruction_status") or ""),
            unsupported_diagnostic_keys=tuple(
                str(item) for item in _sequence(data.get("unsupported_diagnostic_keys"))
            ),
            source_traceable=bool(data.get("source_traceable")),
            source_fact_ids=tuple(str(item) for item in _sequence(data.get("source_fact_ids"))),
            failure_reasons=tuple(str(item) for item in _sequence(data.get("failure_reasons"))),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True)
class LegalIRProofArtifactValidationResult:
    """Validation result for a proof-carrying LegalIR artifact."""

    artifact_id: str
    diagnostics: tuple[LegalIRProofArtifactDiagnostic, ...] = ()
    policy: LegalIRProofVerificationPolicy = field(
        default_factory=LegalIRProofVerificationPolicy
    )
    schema_version: str = LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(diagnostic.error for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "policy": self.policy.to_dict(),
            "schema_version": self.schema_version,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRProofCarryingArtifact:
    """A deterministic LegalIR output package plus independent proof evidence."""

    artifact_id: str
    legal_ir_outputs: Any
    proof_obligations: tuple[LegalIRProofObligation, ...]
    hammer_guidance_artifacts: tuple[HammerGuidanceArtifact, ...]
    translation_records: tuple[HammerTranslationRecord, ...]
    reconstruction_receipts: tuple[HammerReconstructionReceipt, ...]
    unsupported_diagnostics: tuple[LegalIRBackendUnsupportedDiagnostic, ...] = ()
    source_map: LegalIRSourceMap | None = None
    build_manifest: LegalIRBuildManifest | None = None
    verification_policy: LegalIRProofVerificationPolicy = field(
        default_factory=LegalIRProofVerificationPolicy
    )
    evidence_bindings: tuple[LegalIRProofEvidenceBinding, ...] = ()
    route_results: tuple[Mapping[str, Any], ...] = ()
    legal_ir_output_sha256: str = ""
    build_manifest_sha256: str = ""
    source_map_sha256: str = ""
    package_sha256: str = ""
    diagnostics: tuple[LegalIRProofArtifactDiagnostic, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proof_obligations",
            tuple(_obligation(item) for item in self.proof_obligations),
        )
        object.__setattr__(
            self,
            "hammer_guidance_artifacts",
            tuple(_guidance(item) for item in self.hammer_guidance_artifacts),
        )
        object.__setattr__(
            self,
            "translation_records",
            tuple(_translation_record(item) for item in self.translation_records),
        )
        object.__setattr__(
            self,
            "reconstruction_receipts",
            tuple(_reconstruction_receipt(item) for item in self.reconstruction_receipts),
        )
        object.__setattr__(
            self,
            "unsupported_diagnostics",
            tuple(_unsupported_diagnostic(item) for item in self.unsupported_diagnostics),
        )
        source_map = self.source_map
        if source_map is not None and not isinstance(source_map, LegalIRSourceMap):
            source_map = LegalIRSourceMap.from_dict(_mapping(source_map))
            object.__setattr__(self, "source_map", source_map)
        build_manifest = self.build_manifest
        if build_manifest is not None and not isinstance(build_manifest, LegalIRBuildManifest):
            build_manifest = LegalIRBuildManifest.from_dict(_mapping(build_manifest))
            object.__setattr__(self, "build_manifest", build_manifest)
        if not isinstance(self.verification_policy, LegalIRProofVerificationPolicy):
            object.__setattr__(
                self,
                "verification_policy",
                LegalIRProofVerificationPolicy.from_dict(_mapping(self.verification_policy)),
            )
        object.__setattr__(
            self,
            "evidence_bindings",
            tuple(
                item
                if isinstance(item, LegalIRProofEvidenceBinding)
                else LegalIRProofEvidenceBinding.from_dict(_mapping(item))
                for item in self.evidence_bindings
            ),
        )
        object.__setattr__(self, "route_results", tuple(_mapping(item) for item in self.route_results))
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                item
                if isinstance(item, LegalIRProofArtifactDiagnostic)
                else LegalIRProofArtifactDiagnostic.from_dict(_mapping(item))
                for item in self.diagnostics
            ),
        )
        if not self.legal_ir_output_sha256:
            object.__setattr__(
                self,
                "legal_ir_output_sha256",
                _stable_hash(self.legal_ir_outputs),
            )
        if build_manifest is not None and not self.build_manifest_sha256:
            object.__setattr__(
                self,
                "build_manifest_sha256",
                build_manifest.manifest_sha256(),
            )
        if source_map is not None and not self.source_map_sha256:
            object.__setattr__(
                self,
                "source_map_sha256",
                _stable_hash(source_map.to_dict()),
            )

    def to_dict(self, *, include_package_sha256: bool = True) -> dict[str, Any]:
        payload = {
            "artifact_id": self.artifact_id,
            "build_manifest": (
                self.build_manifest.to_dict() if self.build_manifest is not None else None
            ),
            "build_manifest_sha256": self.build_manifest_sha256,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "evidence_bindings": [binding.to_dict() for binding in self.evidence_bindings],
            "hammer_guidance_artifacts": [
                artifact.to_dict() for artifact in self.hammer_guidance_artifacts
            ],
            "legal_ir_output_sha256": self.legal_ir_output_sha256,
            "legal_ir_outputs": _json_ready(self.legal_ir_outputs),
            "metadata": _json_ready(self.metadata),
            "proof_obligations": [
                obligation.to_dict() for obligation in self.proof_obligations
            ],
            "reconstruction_receipts": [
                receipt.to_dict() for receipt in self.reconstruction_receipts
            ],
            "route_results": [_json_ready(item) for item in self.route_results],
            "schema_version": self.schema_version,
            "source_map": self.source_map.to_dict() if self.source_map is not None else None,
            "source_map_sha256": self.source_map_sha256,
            "translation_records": [record.to_dict() for record in self.translation_records],
            "unsupported_diagnostics": [
                diagnostic.to_dict() for diagnostic in self.unsupported_diagnostics
            ],
            "verification_policy": self.verification_policy.to_dict(),
        }
        if include_package_sha256:
            payload["package_sha256"] = self.package_sha256 or self.computed_package_sha256()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRProofCarryingArtifact":
        return cls(
            artifact_id=str(data.get("artifact_id") or ""),
            legal_ir_outputs=data.get("legal_ir_outputs"),
            proof_obligations=tuple(
                LegalIRProofObligation(
                    obligation_id=str(_mapping(item).get("obligation_id") or ""),
                    statement=str(_mapping(item).get("statement") or ""),
                    kind=str(_mapping(item).get("kind") or ""),
                    legal_ir_view=str(_mapping(item).get("legal_ir_view") or ""),
                    logic_family=str(_mapping(item).get("logic_family") or ""),
                    sample_id=str(_mapping(item).get("sample_id") or ""),
                    formula_id=str(_mapping(item).get("formula_id") or ""),
                    premise_hints=[
                        str(value)
                        for value in _sequence(_mapping(item).get("premise_hints"))
                    ],
                    metadata=_mapping(_mapping(item).get("metadata")),
                    schema_version=str(
                        _mapping(item).get("schema_version")
                        or LEGAL_IR_OBLIGATION_SCHEMA_VERSION
                    ),
                )
                for item in _sequence(data.get("proof_obligations"))
            ),
            hammer_guidance_artifacts=tuple(
                HammerGuidanceArtifact.from_dict(_mapping(item))
                for item in _sequence(data.get("hammer_guidance_artifacts"))
            ),
            translation_records=tuple(
                HammerTranslationRecord.from_dict(_mapping(item))
                for item in _sequence(data.get("translation_records"))
            ),
            reconstruction_receipts=tuple(
                HammerReconstructionReceipt.from_dict(_mapping(item))
                for item in _sequence(data.get("reconstruction_receipts"))
            ),
            unsupported_diagnostics=tuple(
                LegalIRBackendUnsupportedDiagnostic.from_dict(_mapping(item))
                for item in _sequence(data.get("unsupported_diagnostics"))
            ),
            source_map=(
                LegalIRSourceMap.from_dict(_mapping(data.get("source_map")))
                if data.get("source_map") is not None
                else None
            ),
            build_manifest=(
                LegalIRBuildManifest.from_dict(_mapping(data.get("build_manifest")))
                if data.get("build_manifest") is not None
                else None
            ),
            verification_policy=LegalIRProofVerificationPolicy.from_dict(
                _mapping(data.get("verification_policy"))
            ),
            evidence_bindings=tuple(
                LegalIRProofEvidenceBinding.from_dict(_mapping(item))
                for item in _sequence(data.get("evidence_bindings"))
            ),
            route_results=tuple(_mapping(item) for item in _sequence(data.get("route_results"))),
            legal_ir_output_sha256=str(data.get("legal_ir_output_sha256") or ""),
            build_manifest_sha256=str(data.get("build_manifest_sha256") or ""),
            source_map_sha256=str(data.get("source_map_sha256") or ""),
            package_sha256=str(data.get("package_sha256") or ""),
            diagnostics=tuple(
                LegalIRProofArtifactDiagnostic.from_dict(_mapping(item))
                for item in _sequence(data.get("diagnostics"))
            ),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION
            ),
        )

    @property
    def obligation_ids(self) -> tuple[str, ...]:
        return tuple(obligation.obligation_id for obligation in self.proof_obligations)

    def computed_package_sha256(self) -> str:
        return _stable_hash(self.to_dict(include_package_sha256=False))

    def canonical_json(self, *, include_package_sha256: bool = True) -> str:
        return _stable_json(self.to_dict(include_package_sha256=include_package_sha256))

    def validate(
        self,
        *,
        policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
        expected_legal_ir_output_sha256: str = "",
        expected_build_manifest_sha256: str = "",
    ) -> LegalIRProofArtifactValidationResult:
        return validate_legal_ir_proof_carrying_artifact(
            self,
            policy=policy,
            expected_legal_ir_output_sha256=expected_legal_ir_output_sha256,
            expected_build_manifest_sha256=expected_build_manifest_sha256,
        )


def build_legal_ir_proof_carrying_artifact(
    *,
    legal_ir_outputs: Any,
    proof_obligations: Sequence[LegalIRProofObligation | Mapping[str, Any]],
    hammer_report: LegalIRHammerReport | Mapping[str, Any] | None = None,
    hammer_guidance_artifacts: Sequence[HammerGuidanceArtifact | Mapping[str, Any]] | None = None,
    translation_records: Sequence[HammerTranslationRecord | Mapping[str, Any]] | None = None,
    reconstruction_receipts: Sequence[HammerReconstructionReceipt | Mapping[str, Any]] | None = None,
    route_results: Sequence[Mapping[str, Any] | Any] | None = None,
    unsupported_diagnostics: Sequence[LegalIRBackendUnsupportedDiagnostic | Mapping[str, Any]] = (),
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    build_manifest: LegalIRBuildManifest | Mapping[str, Any] | None = None,
    verification_policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRProofCarryingArtifact:
    """Package LegalIR outputs with all proof evidence needed by consumers."""

    report = hammer_report
    if report is not None:
        report_payload = _mapping(report)
        if hammer_guidance_artifacts is None:
            hammer_guidance_artifacts = getattr(report, "artifacts", None) or report_payload.get(
                "artifacts", ()
            )
        if translation_records is None:
            translation_records = getattr(report, "translation_records", None) or report_payload.get(
                "translation_records", ()
            )
        if reconstruction_receipts is None:
            reconstruction_receipts = getattr(report, "reconstruction_receipts", None) or report_payload.get(
                "reconstruction_receipts", ()
            )
        if route_results is None:
            route_results = getattr(report, "route_results", None) or report_payload.get(
                "route_results", ()
            )

    obligations = tuple(_obligation(item) for item in proof_obligations)
    guidance = tuple(_guidance(item) for item in (hammer_guidance_artifacts or ()))
    translations = tuple(_translation_record(item) for item in (translation_records or ()))
    receipts = tuple(_reconstruction_receipt(item) for item in (reconstruction_receipts or ()))
    routes = tuple(_mapping(item) for item in (route_results or ()))
    unsupported = tuple(_unsupported_diagnostic(item) for item in unsupported_diagnostics)
    resolved_source_map = (
        source_map
        if isinstance(source_map, LegalIRSourceMap) or source_map is None
        else LegalIRSourceMap.from_dict(_mapping(source_map))
    )
    resolved_manifest = (
        build_manifest
        if isinstance(build_manifest, LegalIRBuildManifest) or build_manifest is None
        else LegalIRBuildManifest.from_dict(_mapping(build_manifest))
    )
    policy = (
        verification_policy
        if isinstance(verification_policy, LegalIRProofVerificationPolicy)
        else LegalIRProofVerificationPolicy.from_dict(_mapping(verification_policy))
        if verification_policy is not None
        else LegalIRProofVerificationPolicy()
    )
    output_sha = _stable_hash(legal_ir_outputs)
    evidence_bindings = _build_evidence_bindings(
        obligations=obligations,
        guidance=guidance,
        translations=translations,
        receipts=receipts,
        route_results=routes,
        unsupported_diagnostics=unsupported,
        source_map=resolved_source_map,
    )
    artifact_core = {
        "build_manifest_sha256": (
            resolved_manifest.manifest_sha256() if resolved_manifest is not None else ""
        ),
        "evidence_bindings": [binding.to_dict() for binding in evidence_bindings],
        "legal_ir_output_sha256": output_sha,
        "obligation_ids": [obligation.obligation_id for obligation in obligations],
        "policy_sha256": policy.policy_sha256,
        "source_map_sha256": (
            _stable_hash(resolved_source_map.to_dict()) if resolved_source_map is not None else ""
        ),
    }
    artifact_id = "legal-ir-proof-artifact-" + _stable_hash(artifact_core)[:24]
    return LegalIRProofCarryingArtifact(
        artifact_id=artifact_id,
        legal_ir_outputs=legal_ir_outputs,
        proof_obligations=obligations,
        hammer_guidance_artifacts=guidance,
        translation_records=translations,
        reconstruction_receipts=receipts,
        unsupported_diagnostics=unsupported,
        source_map=resolved_source_map,
        build_manifest=resolved_manifest,
        verification_policy=policy,
        evidence_bindings=evidence_bindings,
        route_results=routes,
        legal_ir_output_sha256=output_sha,
        metadata={
            "builder": "build_legal_ir_proof_carrying_artifact",
            **dict(metadata or {}),
        },
    )


def legal_ir_proof_carrying_artifact(**kwargs: Any) -> dict[str, Any]:
    """Dictionary API for proof-carrying LegalIR artifact production."""

    return build_legal_ir_proof_carrying_artifact(**kwargs).to_dict()


def validate_legal_ir_proof_carrying_artifact(
    artifact: LegalIRProofCarryingArtifact | Mapping[str, Any],
    *,
    policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
    expected_legal_ir_output_sha256: str = "",
    expected_build_manifest_sha256: str = "",
) -> LegalIRProofArtifactValidationResult:
    """Validate a LegalIR artifact exactly as a downstream consumer would."""

    value = (
        artifact
        if isinstance(artifact, LegalIRProofCarryingArtifact)
        else LegalIRProofCarryingArtifact.from_dict(_mapping(artifact))
    )
    active_policy = (
        policy
        if isinstance(policy, LegalIRProofVerificationPolicy)
        else LegalIRProofVerificationPolicy.from_dict(_mapping(policy))
        if policy is not None
        else value.verification_policy
    )
    if expected_legal_ir_output_sha256:
        active_policy = replace(
            active_policy,
            expected_legal_ir_output_sha256=expected_legal_ir_output_sha256,
        )
    if expected_build_manifest_sha256:
        active_policy = replace(
            active_policy,
            expected_build_manifest_sha256=expected_build_manifest_sha256,
        )

    diagnostics: list[LegalIRProofArtifactDiagnostic] = list(value.diagnostics)
    diagnostics.extend(_validate_artifact_envelope(value, active_policy))
    diagnostics.extend(_validate_build_manifest(value, active_policy))
    diagnostics.extend(_validate_source_map(value, active_policy))
    diagnostics.extend(_validate_component_schemas(value, active_policy))
    diagnostics.extend(_validate_cross_references(value, active_policy))
    diagnostics.extend(_validate_obligation_evidence(value, active_policy))

    return LegalIRProofArtifactValidationResult(
        artifact_id=value.artifact_id,
        diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
        policy=active_policy,
    )


def assert_legal_ir_proof_carrying_artifact_valid(
    artifact: LegalIRProofCarryingArtifact | Mapping[str, Any],
    *,
    policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
    expected_legal_ir_output_sha256: str = "",
    expected_build_manifest_sha256: str = "",
) -> LegalIRProofArtifactValidationResult:
    """Validate a proof-carrying artifact and raise on any error."""

    result = validate_legal_ir_proof_carrying_artifact(
        artifact,
        policy=policy,
        expected_legal_ir_output_sha256=expected_legal_ir_output_sha256,
        expected_build_manifest_sha256=expected_build_manifest_sha256,
    )
    if not result.valid:
        raise LegalIRProofArtifactError(_format_diagnostics(result.diagnostics))
    return result


def save_legal_ir_proof_carrying_artifact(
    artifact: LegalIRProofCarryingArtifact | Mapping[str, Any],
    path: str | Path,
) -> None:
    """Persist a proof-carrying artifact as canonical JSON."""

    value = (
        artifact
        if isinstance(artifact, LegalIRProofCarryingArtifact)
        else LegalIRProofCarryingArtifact.from_dict(_mapping(artifact))
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value.canonical_json() + "\n", encoding="utf-8")


def load_legal_ir_proof_carrying_artifact(
    path: str | Path,
    *,
    validate: bool = False,
    policy: LegalIRProofVerificationPolicy | Mapping[str, Any] | None = None,
) -> LegalIRProofCarryingArtifact:
    """Load a persisted proof-carrying artifact, optionally validating it."""

    artifact = LegalIRProofCarryingArtifact.from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
    if validate:
        assert_legal_ir_proof_carrying_artifact_valid(artifact, policy=policy)
    return artifact


def _validate_artifact_envelope(
    value: LegalIRProofCarryingArtifact,
    policy: LegalIRProofVerificationPolicy,
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    diagnostics: list[LegalIRProofArtifactDiagnostic] = []
    if value.schema_version != LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                "incompatible_artifact_schema_version",
                "Proof-carrying artifact schema_version is not supported.",
                "schema_version",
                metadata={"schema_version": value.schema_version},
            )
        )
    if policy.schema_version != LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                "incompatible_policy_schema_version",
                "Verification policy schema_version is not supported.",
                "verification_policy.schema_version",
            )
        )
    if not value.artifact_id:
        diagnostics.append(_diagnostic("artifact_id_missing", "Artifact id is required.", "artifact_id"))
    computed_output = _stable_hash(value.legal_ir_outputs)
    if value.legal_ir_output_sha256 != computed_output:
        diagnostics.append(
            _diagnostic(
                "legal_ir_output_sha256_mismatch",
                "LegalIR output hash does not match the carried outputs.",
                "legal_ir_output_sha256",
                metadata={"computed": computed_output, "recorded": value.legal_ir_output_sha256},
            )
        )
    expected_output = policy.expected_legal_ir_output_sha256
    if expected_output and expected_output != value.legal_ir_output_sha256:
        diagnostics.append(
            _diagnostic(
                "stale_legal_ir_output",
                "LegalIR output hash does not match the consumer-expected digest.",
                "legal_ir_output_sha256",
                metadata={"expected": expected_output, "recorded": value.legal_ir_output_sha256},
            )
        )
    if value.package_sha256 and value.package_sha256 != value.computed_package_sha256():
        diagnostics.append(
            _diagnostic(
                "package_sha256_mismatch",
                "Proof-carrying artifact package hash does not match the payload.",
                "package_sha256",
                metadata={
                    "computed": value.computed_package_sha256(),
                    "recorded": value.package_sha256,
                },
            )
        )
    if not value.proof_obligations:
        diagnostics.append(
            _diagnostic(
                "proof_obligations_missing",
                "At least one proof obligation is required.",
                "proof_obligations",
            )
        )
    return tuple(diagnostics)


def _validate_build_manifest(
    value: LegalIRProofCarryingArtifact,
    policy: LegalIRProofVerificationPolicy,
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    diagnostics: list[LegalIRProofArtifactDiagnostic] = []
    manifest = value.build_manifest
    if manifest is None:
        if policy.require_build_manifest:
            diagnostics.append(
                _diagnostic(
                    "build_manifest_missing",
                    "Verification policy requires a LegalIR build manifest.",
                    "build_manifest",
                )
            )
        return tuple(diagnostics)

    computed_manifest_sha = manifest.manifest_sha256()
    if value.build_manifest_sha256 and value.build_manifest_sha256 != computed_manifest_sha:
        diagnostics.append(
            _diagnostic(
                "build_manifest_sha256_mismatch",
                "Build manifest hash does not match the carried manifest.",
                "build_manifest_sha256",
                metadata={
                    "computed": computed_manifest_sha,
                    "recorded": value.build_manifest_sha256,
                },
            )
        )
    expected = policy.expected_build_manifest_sha256
    if expected and expected != computed_manifest_sha:
        diagnostics.append(
            _diagnostic(
                "stale_build_manifest",
                "Build manifest hash does not match the consumer-expected digest.",
                "build_manifest_sha256",
                metadata={"expected": expected, "recorded": computed_manifest_sha},
            )
        )
    if policy.accepted_build_ids and manifest.build_id not in policy.accepted_build_ids:
        diagnostics.append(
            _diagnostic(
                "unaccepted_build_id",
                "Build id is not accepted by the verification policy.",
                "build_manifest.build_id",
                metadata={"build_id": manifest.build_id},
            )
        )
    if (
        policy.accepted_compiler_commits
        and manifest.compiler_commit not in policy.accepted_compiler_commits
    ):
        diagnostics.append(
            _diagnostic(
                "unaccepted_compiler_commit",
                "Compiler commit is not accepted by the verification policy.",
                "build_manifest.compiler_commit",
                metadata={"compiler_commit": manifest.compiler_commit},
            )
        )
    if policy.require_valid_build_manifest:
        build_validation = validate_legal_ir_build_manifest(manifest)
        for diagnostic in build_validation.diagnostics:
            if diagnostic.error:
                diagnostics.append(
                    _diagnostic(
                        "invalid_build_manifest",
                        diagnostic.message,
                        f"build_manifest.{diagnostic.field_path}",
                        metadata=diagnostic.to_dict(),
                    )
                )
    if policy.require_build_output_binding and not _manifest_binds_output(
        manifest,
        value.legal_ir_output_sha256,
    ):
        diagnostics.append(
            _diagnostic(
                "build_manifest_output_binding_missing",
                "Build manifest does not bind the carried LegalIR output digest.",
                "build_manifest.output_digests",
                metadata={"legal_ir_output_sha256": value.legal_ir_output_sha256},
            )
        )
    return tuple(diagnostics)


def _validate_source_map(
    value: LegalIRProofCarryingArtifact,
    policy: LegalIRProofVerificationPolicy,
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    diagnostics: list[LegalIRProofArtifactDiagnostic] = []
    source_map = value.source_map
    if source_map is None:
        if policy.require_source_map:
            diagnostics.append(
                _diagnostic(
                    "source_map_missing",
                    "Verification policy requires a LegalIR source map.",
                    "source_map",
                )
            )
        return tuple(diagnostics)
    computed_source_map_sha = _stable_hash(source_map.to_dict())
    if value.source_map_sha256 and value.source_map_sha256 != computed_source_map_sha:
        diagnostics.append(
            _diagnostic(
                "source_map_sha256_mismatch",
                "Source-map hash does not match the carried source map.",
                "source_map_sha256",
                metadata={
                    "computed": computed_source_map_sha,
                    "recorded": value.source_map_sha256,
                },
            )
        )
    source_validation = validate_legal_ir_source_map(source_map)
    for issue in source_validation.issues:
        if issue.severity == "error":
            diagnostics.append(
                _diagnostic(
                    "invalid_source_map",
                    issue.message,
                    f"source_map.{issue.field_path}",
                    metadata=issue.to_dict(),
                )
            )
    return tuple(diagnostics)


def _validate_component_schemas(
    value: LegalIRProofCarryingArtifact,
    policy: LegalIRProofVerificationPolicy,
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    diagnostics: list[LegalIRProofArtifactDiagnostic] = []
    expected = policy.component_schema_versions
    for index, obligation in enumerate(value.proof_obligations):
        if obligation.schema_version != expected["proof_obligation"]:
            diagnostics.append(
                _schema_diagnostic(
                    "proof_obligations",
                    index,
                    "schema_version",
                    obligation.schema_version,
                    expected["proof_obligation"],
                    obligation_id=obligation.obligation_id,
                )
            )
    for index, artifact in enumerate(value.hammer_guidance_artifacts):
        if artifact.schema_version != expected["hammer_guidance"]:
            diagnostics.append(
                _schema_diagnostic(
                    "hammer_guidance_artifacts",
                    index,
                    "schema_version",
                    artifact.schema_version,
                    expected["hammer_guidance"],
                    obligation_id=artifact.obligation_id,
                    evidence_id=artifact.guidance_id,
                )
            )
    for index, record in enumerate(value.translation_records):
        if record.schema_version != expected["hammer_translation"]:
            diagnostics.append(
                _schema_diagnostic(
                    "translation_records",
                    index,
                    "schema_version",
                    record.schema_version,
                    expected["hammer_translation"],
                    obligation_id=record.obligation_id,
                    evidence_id=record.translation_id,
                )
            )
    for index, receipt in enumerate(value.reconstruction_receipts):
        if receipt.schema_version != expected["hammer_reconstruction_receipt"]:
            diagnostics.append(
                _schema_diagnostic(
                    "reconstruction_receipts",
                    index,
                    "schema_version",
                    receipt.schema_version,
                    expected["hammer_reconstruction_receipt"],
                    obligation_id=receipt.obligation_id,
                    evidence_id=receipt.receipt_id,
                )
            )
    if value.source_map is not None and value.source_map.schema_version != expected["source_map"]:
        diagnostics.append(
            _diagnostic(
                "incompatible_component_schema_version",
                "Source-map schema_version is not compatible with the verification policy.",
                "source_map.schema_version",
                metadata={
                    "expected": expected["source_map"],
                    "recorded": value.source_map.schema_version,
                },
            )
        )
    if (
        value.build_manifest is not None
        and value.build_manifest.schema_version != expected["build_manifest"]
    ):
        diagnostics.append(
            _diagnostic(
                "incompatible_component_schema_version",
                "Build-manifest schema_version is not compatible with the verification policy.",
                "build_manifest.schema_version",
                metadata={
                    "expected": expected["build_manifest"],
                    "recorded": value.build_manifest.schema_version,
                },
            )
        )
    for index, route_result in enumerate(value.route_results):
        route_schema = str(route_result.get("schema_version") or expected["proof_router"])
        if route_schema != expected["proof_router"]:
            diagnostics.append(
                _diagnostic(
                    "incompatible_component_schema_version",
                    "Proof-route schema_version is not compatible with the verification policy.",
                    f"route_results.{index}.schema_version",
                    obligation_id=str(route_result.get("obligation_id") or ""),
                    metadata={
                        "expected": expected["proof_router"],
                        "recorded": route_schema,
                    },
                )
            )
    return tuple(diagnostics)


def _validate_cross_references(
    value: LegalIRProofCarryingArtifact,
    policy: LegalIRProofVerificationPolicy,
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    diagnostics: list[LegalIRProofArtifactDiagnostic] = []
    obligation_ids = set(value.obligation_ids)
    translation_ids = {record.translation_id for record in value.translation_records}
    guidance_ids = {artifact.guidance_id for artifact in value.hammer_guidance_artifacts}
    receipt_ids = {receipt.receipt_id for receipt in value.reconstruction_receipts}
    binding_obligation_ids = {binding.obligation_id for binding in value.evidence_bindings}
    for obligation_id in obligation_ids - binding_obligation_ids:
        diagnostics.append(
            _diagnostic(
                "evidence_binding_missing",
                "Proof obligation has no evidence binding.",
                "evidence_bindings",
                obligation_id=obligation_id,
            )
        )
    for index, record in enumerate(value.translation_records):
        if record.obligation_id and record.obligation_id not in obligation_ids:
            diagnostics.append(
                _diagnostic(
                    "orphaned_translation_record",
                    "Hammer translation record references an unknown proof obligation.",
                    f"translation_records.{index}.obligation_id",
                    obligation_id=record.obligation_id,
                    evidence_id=record.translation_id,
                )
            )
    for index, receipt in enumerate(value.reconstruction_receipts):
        if receipt.obligation_id and receipt.obligation_id not in obligation_ids:
            diagnostics.append(
                _diagnostic(
                    "orphaned_hammer_receipt",
                    "Hammer reconstruction receipt references an unknown proof obligation.",
                    f"reconstruction_receipts.{index}.obligation_id",
                    obligation_id=receipt.obligation_id,
                    evidence_id=receipt.receipt_id,
                )
            )
        for translation_id in receipt.translation_record_ids:
            if translation_id not in translation_ids:
                diagnostics.append(
                    _diagnostic(
                        "stale_hammer_receipt",
                        "Hammer reconstruction receipt references a missing translation record.",
                        f"reconstruction_receipts.{index}.translation_record_ids",
                        obligation_id=receipt.obligation_id,
                        evidence_id=receipt.receipt_id,
                        metadata={"translation_id": translation_id},
                    )
                )
    for index, artifact in enumerate(value.hammer_guidance_artifacts):
        referenced = set(artifact.proof_obligation_ids or [artifact.obligation_id])
        if artifact.obligation_id:
            referenced.add(artifact.obligation_id)
        unknown = sorted(item for item in referenced if item and item not in obligation_ids)
        if unknown:
            diagnostics.append(
                _diagnostic(
                    "orphaned_hammer_guidance",
                    "Hammer guidance artifact references unknown proof obligations.",
                    f"hammer_guidance_artifacts.{index}.proof_obligation_ids",
                    evidence_id=artifact.guidance_id,
                    metadata={"unknown_obligation_ids": unknown},
                )
            )
    for index, diagnostic in enumerate(value.unsupported_diagnostics):
        if policy.require_typed_unsupported_diagnostics and not diagnostic.valid:
            diagnostics.append(
                _diagnostic(
                    "invalid_unsupported_diagnostic",
                    "Unsupported diagnostic must be typed and include a reason code.",
                    f"unsupported_diagnostics.{index}",
                    metadata=diagnostic.to_dict(),
                )
            )
        unknown_ids = sorted(
            obligation_id
            for obligation_id in diagnostic.obligation_ids
            if obligation_id not in obligation_ids
        )
        if unknown_ids:
            diagnostics.append(
                _diagnostic(
                    "orphaned_unsupported_diagnostic",
                    "Unsupported diagnostic references unknown proof obligations.",
                    f"unsupported_diagnostics.{index}.obligation_ids",
                metadata={"unknown_obligation_ids": unknown_ids},
            )
        )
    for binding in value.evidence_bindings:
        if binding.obligation_id not in obligation_ids:
            diagnostics.append(
                _diagnostic(
                    "orphaned_evidence_binding",
                    "Evidence binding references an unknown proof obligation.",
                    "evidence_bindings.obligation_id",
                    obligation_id=binding.obligation_id,
                )
            )
        for guidance_id in binding.guidance_ids:
            if guidance_id not in guidance_ids:
                diagnostics.append(
                    _diagnostic(
                        "stale_evidence_binding",
                        "Evidence binding references a missing Hammer guidance artifact.",
                        "evidence_bindings.guidance_ids",
                        obligation_id=binding.obligation_id,
                        evidence_id=guidance_id,
                    )
                )
        for receipt_id in binding.receipt_ids:
            if receipt_id not in receipt_ids:
                diagnostics.append(
                    _diagnostic(
                        "stale_evidence_binding",
                        "Evidence binding references a missing Hammer reconstruction receipt.",
                        "evidence_bindings.receipt_ids",
                        obligation_id=binding.obligation_id,
                        evidence_id=receipt_id,
                    )
                )
        for translation_id in binding.translation_record_ids:
            if translation_id not in translation_ids:
                diagnostics.append(
                    _diagnostic(
                        "stale_evidence_binding",
                        "Evidence binding references a missing Hammer translation record.",
                        "evidence_bindings.translation_record_ids",
                        obligation_id=binding.obligation_id,
                        evidence_id=translation_id,
                    )
                )
    return tuple(diagnostics)


def _validate_obligation_evidence(
    value: LegalIRProofCarryingArtifact,
    policy: LegalIRProofVerificationPolicy,
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    diagnostics: list[LegalIRProofArtifactDiagnostic] = []
    recomputed_bindings = _build_evidence_bindings(
        obligations=value.proof_obligations,
        guidance=value.hammer_guidance_artifacts,
        translations=value.translation_records,
        receipts=value.reconstruction_receipts,
        route_results=value.route_results,
        unsupported_diagnostics=value.unsupported_diagnostics,
        source_map=value.source_map,
    )
    carried = {binding.obligation_id: binding for binding in value.evidence_bindings}
    bindings = {binding.obligation_id: binding for binding in recomputed_bindings}
    for obligation_id, recomputed in bindings.items():
        carried_binding = carried.get(obligation_id)
        if carried_binding is not None and carried_binding.to_dict() != recomputed.to_dict():
            diagnostics.append(
                _diagnostic(
                    "stale_evidence_binding",
                    "Carried evidence binding does not match the proof evidence payload.",
                    "evidence_bindings",
                    obligation_id=obligation_id,
                    metadata={
                        "carried": carried_binding.to_dict(),
                        "recomputed": recomputed.to_dict(),
                    },
                )
            )
    for obligation in value.proof_obligations:
        binding = bindings.get(obligation.obligation_id)
        if binding is None:
            continue
        unsupported_allowed = (
            policy.allow_typed_unsupported_obligations
            and bool(binding.unsupported_diagnostic_keys)
        )
        if policy.require_hammer_guidance and not binding.guidance_ids:
            diagnostics.append(
                _obligation_diagnostic(
                    "hammer_guidance_missing",
                    "Proof obligation has no Hammer guidance artifact.",
                    obligation.obligation_id,
                    "hammer_guidance_artifacts",
                )
            )
        if policy.require_hammer_receipts and not binding.receipt_ids:
            diagnostics.append(
                _obligation_diagnostic(
                    "hammer_receipt_missing",
                    "Proof obligation has no Hammer reconstruction receipt.",
                    obligation.obligation_id,
                    "reconstruction_receipts",
                )
            )
        if policy.require_translation_records and not binding.translation_record_ids:
            diagnostics.append(
                _obligation_diagnostic(
                    "translation_record_missing",
                    "Proof obligation has no Hammer translation record.",
                    obligation.obligation_id,
                    "translation_records",
                )
            )
        if policy.require_route_results and not binding.route_status:
            diagnostics.append(
                _obligation_diagnostic(
                    "proof_route_missing",
                    "Proof obligation has no proof-route result.",
                    obligation.obligation_id,
                    "route_results",
                )
            )
        if (
            policy.require_all_obligations_proved
            and not binding.proved
            and not unsupported_allowed
        ):
            diagnostics.append(
                _obligation_diagnostic(
                    "proof_failed",
                    "Proof obligation is not proved by the carried evidence.",
                    obligation.obligation_id,
                    "evidence_bindings.proved",
                    metadata={"failure_reasons": list(binding.failure_reasons)},
                )
            )
        if policy.require_trusted_proofs and not binding.trusted and not unsupported_allowed:
            diagnostics.append(
                _obligation_diagnostic(
                    "proof_not_trusted",
                    "Proof obligation is not trusted by the verification policy.",
                    obligation.obligation_id,
                    "evidence_bindings.trusted",
                    metadata={"failure_reasons": list(binding.failure_reasons)},
                )
            )
        if (
            policy.require_native_reconstruction
            and not binding.native_reconstruction
            and not unsupported_allowed
        ):
            diagnostics.append(
                _obligation_diagnostic(
                    "native_reconstruction_missing",
                    "Proof obligation has no native reconstruction receipt.",
                    obligation.obligation_id,
                    "evidence_bindings.native_reconstruction",
                )
            )
        if (
            policy.require_native_reconstruction_verified
            and not binding.native_reconstruction_verified
            and not unsupported_allowed
        ):
            diagnostics.append(
                _obligation_diagnostic(
                    "native_reconstruction_not_verified",
                    "Proof obligation native reconstruction was not verified.",
                    obligation.obligation_id,
                    "evidence_bindings.native_reconstruction_verified",
                )
            )
        if (
            policy.require_reconstruction_status
            and not binding.reconstruction_status
            and not unsupported_allowed
        ):
            diagnostics.append(
                _obligation_diagnostic(
                    "reconstruction_status_missing",
                    "Proof obligation has no reconstruction status.",
                    obligation.obligation_id,
                    "evidence_bindings.reconstruction_status",
                )
            )
        if policy.require_source_traceability and not binding.source_traceable:
            diagnostics.append(
                _obligation_diagnostic(
                    "source_traceability_missing",
                    "Proof obligation cannot be traced to the carried source map.",
                    obligation.obligation_id,
                    "source_map",
                    metadata={"formula_id": obligation.formula_id},
                )
            )
    return tuple(diagnostics)


def _build_evidence_bindings(
    *,
    obligations: Sequence[LegalIRProofObligation],
    guidance: Sequence[HammerGuidanceArtifact],
    translations: Sequence[HammerTranslationRecord],
    receipts: Sequence[HammerReconstructionReceipt],
    route_results: Sequence[Mapping[str, Any]],
    unsupported_diagnostics: Sequence[LegalIRBackendUnsupportedDiagnostic],
    source_map: LegalIRSourceMap | None,
) -> tuple[LegalIRProofEvidenceBinding, ...]:
    bindings: list[LegalIRProofEvidenceBinding] = []
    for obligation in obligations:
        obligation_id = obligation.obligation_id
        guidance_items = [
            item
            for item in guidance
            if item.obligation_id == obligation_id
            or obligation_id in set(item.proof_obligation_ids or ())
        ]
        translation_items = [item for item in translations if item.obligation_id == obligation_id]
        receipt_items = [item for item in receipts if item.obligation_id == obligation_id]
        routes = [
            item
            for item in route_results
            if str(item.get("obligation_id") or "") == obligation_id
        ]
        unsupported = [
            item
            for item in unsupported_diagnostics
            if not item.obligation_ids or obligation_id in item.obligation_ids
        ]
        route_status = str(routes[-1].get("status") or "") if routes else ""
        route_trust_satisfied = any(bool(item.get("trust_satisfied")) for item in routes)
        source_traceable, source_fact_ids = _source_traceability(
            source_map,
            obligation_id=obligation_id,
            formula_id=obligation.formula_id,
            evidence_ids=(
                *(item.guidance_id for item in guidance_items),
                *(item.receipt_id for item in receipt_items),
                *(item.translation_id for item in translation_items),
            ),
        )
        failure_reasons = _failure_reasons(guidance_items, receipt_items, routes)
        bindings.append(
            LegalIRProofEvidenceBinding(
                obligation_id=obligation_id,
                formula_id=obligation.formula_id,
                guidance_ids=tuple(item.guidance_id for item in guidance_items),
                translation_record_ids=tuple(item.translation_id for item in translation_items),
                receipt_ids=tuple(item.receipt_id for item in receipt_items),
                route_status=route_status,
                route_trust_satisfied=route_trust_satisfied,
                proved=(
                    any(item.proved for item in guidance_items)
                    or any(item.backend_proved for item in receipt_items)
                    or any(str(item.get("proved")).lower() == "true" for item in routes)
                ),
                trusted=(
                    any(item.trusted for item in guidance_items)
                    or any(item.trusted for item in receipt_items)
                    or route_trust_satisfied
                ),
                backend_proved=any(item.backend_proved for item in receipt_items),
                native_reconstruction=any(item.native_reconstruction for item in receipt_items),
                native_reconstruction_verified=any(
                    item.native_reconstruction_verified for item in receipt_items
                ),
                reconstruction_status=_first_text(
                    [
                        *(item.reconstruction_status for item in receipt_items),
                        *(item.reconstruction_status for item in guidance_items),
                    ]
                ),
                unsupported_diagnostic_keys=tuple(_unsupported_key(item) for item in unsupported),
                source_traceable=source_traceable,
                source_fact_ids=source_fact_ids,
                failure_reasons=tuple(failure_reasons),
            )
        )
    return tuple(bindings)


def _source_traceability(
    source_map: LegalIRSourceMap | None,
    *,
    obligation_id: str,
    formula_id: str,
    evidence_ids: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    if source_map is None:
        return False, ()
    traced: list[str] = []
    for fact_id in _unique([obligation_id, formula_id, *evidence_ids]):
        if not fact_id:
            continue
        trace = trace_legal_ir_fact(source_map, fact_id)
        if trace.traceable:
            traced.append(fact_id)
    return bool(traced), tuple(traced)


def _failure_reasons(
    guidance: Sequence[HammerGuidanceArtifact],
    receipts: Sequence[HammerReconstructionReceipt],
    routes: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    reasons: list[str] = []
    for item in guidance:
        reasons.extend(str(reason) for reason in item.rejection_reasons if str(reason))
        if item.failure_reason:
            reasons.append(item.failure_reason)
    for item in receipts:
        if item.trust_reason and not item.trusted:
            reasons.append(item.trust_reason)
        reasons.extend(str(error) for error in item.errors if str(error))
    for item in routes:
        status = str(item.get("status") or "")
        if status and status != "proved":
            reasons.append(status)
        stop_reason = str(item.get("stop_reason") or "")
        if stop_reason and stop_reason not in {"proved", "trust_satisfied"}:
            reasons.append(stop_reason)
    return tuple(_unique(reasons))


def _manifest_binds_output(manifest: LegalIRBuildManifest, output_sha256: str) -> bool:
    if manifest.output_digest == output_sha256:
        return True
    for digest in manifest.output_digests:
        if digest.sha256 == output_sha256:
            return True
        if str(digest.metadata.get("legal_ir_output_sha256") or "") == output_sha256:
            return True
    metadata = _mapping(manifest.metadata)
    return output_sha256 in {
        str(metadata.get("legal_ir_output_sha256") or ""),
        str(metadata.get("output_sha256") or ""),
    }


def _obligation(value: LegalIRProofObligation | Mapping[str, Any]) -> LegalIRProofObligation:
    if isinstance(value, LegalIRProofObligation):
        return value
    data = _mapping(value)
    return LegalIRProofObligation(
        obligation_id=str(data.get("obligation_id") or ""),
        statement=str(data.get("statement") or ""),
        kind=str(data.get("kind") or ""),
        legal_ir_view=str(data.get("legal_ir_view") or data.get("target_component") or ""),
        logic_family=str(data.get("logic_family") or data.get("family") or ""),
        sample_id=str(data.get("sample_id") or ""),
        formula_id=str(data.get("formula_id") or ""),
        premise_hints=[str(item) for item in _sequence(data.get("premise_hints"))],
        metadata=_mapping(data.get("metadata")),
        schema_version=str(data.get("schema_version") or LEGAL_IR_OBLIGATION_SCHEMA_VERSION),
    )


def _guidance(value: HammerGuidanceArtifact | Mapping[str, Any]) -> HammerGuidanceArtifact:
    return (
        value
        if isinstance(value, HammerGuidanceArtifact)
        else HammerGuidanceArtifact.from_dict(_mapping(value))
    )


def _translation_record(
    value: HammerTranslationRecord | Mapping[str, Any],
) -> HammerTranslationRecord:
    return (
        value
        if isinstance(value, HammerTranslationRecord)
        else HammerTranslationRecord.from_dict(_mapping(value))
    )


def _reconstruction_receipt(
    value: HammerReconstructionReceipt | Mapping[str, Any],
) -> HammerReconstructionReceipt:
    return (
        value
        if isinstance(value, HammerReconstructionReceipt)
        else HammerReconstructionReceipt.from_dict(_mapping(value))
    )


def _unsupported_diagnostic(
    value: LegalIRBackendUnsupportedDiagnostic | Mapping[str, Any],
) -> LegalIRBackendUnsupportedDiagnostic:
    return (
        value
        if isinstance(value, LegalIRBackendUnsupportedDiagnostic)
        else LegalIRBackendUnsupportedDiagnostic.from_dict(_mapping(value))
    )


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _unique(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _first_text(values: Sequence[Any]) -> str:
    for value in values:
        text = str(value or "")
        if text:
            return text
    return ""


def _unsupported_key(diagnostic: LegalIRBackendUnsupportedDiagnostic) -> str:
    scope = ",".join(diagnostic.obligation_ids)
    return (
        f"{diagnostic.backend}:{diagnostic.feature}:{diagnostic.reason_code}"
        + (f":{scope}" if scope else "")
    )


def _diagnostic(
    code: str,
    message: str,
    field_path: str = "",
    *,
    severity: str = LegalIRProofArtifactDiagnosticSeverity.ERROR.value,
    obligation_id: str = "",
    evidence_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRProofArtifactDiagnostic:
    return LegalIRProofArtifactDiagnostic(
        code=code,
        message=message,
        field_path=field_path,
        severity=severity,
        obligation_id=obligation_id,
        evidence_id=evidence_id,
        metadata=dict(metadata or {}),
    )


def _obligation_diagnostic(
    code: str,
    message: str,
    obligation_id: str,
    field_path: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRProofArtifactDiagnostic:
    return _diagnostic(
        code,
        message,
        field_path,
        obligation_id=obligation_id,
        metadata=metadata,
    )


def _schema_diagnostic(
    collection: str,
    index: int,
    field: str,
    recorded: str,
    expected: str,
    *,
    obligation_id: str = "",
    evidence_id: str = "",
) -> LegalIRProofArtifactDiagnostic:
    return _diagnostic(
        "incompatible_component_schema_version",
        "Evidence schema_version is not compatible with the verification policy.",
        f"{collection}.{index}.{field}",
        obligation_id=obligation_id,
        evidence_id=evidence_id,
        metadata={"expected": expected, "recorded": recorded},
    )


def _dedupe_diagnostics(
    diagnostics: Sequence[LegalIRProofArtifactDiagnostic],
) -> tuple[LegalIRProofArtifactDiagnostic, ...]:
    deduped: dict[tuple[str, str, str, str], LegalIRProofArtifactDiagnostic] = {}
    for diagnostic in diagnostics:
        key = (
            diagnostic.code,
            diagnostic.field_path,
            diagnostic.obligation_id,
            diagnostic.evidence_id,
        )
        deduped[key] = diagnostic
    return tuple(deduped[key] for key in sorted(deduped))


def _format_diagnostics(diagnostics: Sequence[LegalIRProofArtifactDiagnostic]) -> str:
    return "; ".join(
        f"{diagnostic.code}: {diagnostic.message}" for diagnostic in diagnostics
    )


__all__ = [
    "LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION",
    "LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION",
    "LegalIRProofArtifactDiagnostic",
    "LegalIRProofArtifactDiagnosticSeverity",
    "LegalIRProofArtifactError",
    "LegalIRProofArtifactValidationResult",
    "LegalIRProofCarryingArtifact",
    "LegalIRProofEvidenceBinding",
    "LegalIRProofVerificationPolicy",
    "assert_legal_ir_proof_carrying_artifact_valid",
    "build_legal_ir_proof_carrying_artifact",
    "legal_ir_proof_carrying_artifact",
    "load_legal_ir_proof_carrying_artifact",
    "save_legal_ir_proof_carrying_artifact",
    "validate_legal_ir_proof_carrying_artifact",
]

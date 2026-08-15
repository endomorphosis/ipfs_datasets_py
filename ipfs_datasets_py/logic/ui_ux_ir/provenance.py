"""UI/UX IR provenance and declaration/runtime artifact separation (UIR-015)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Mapping

from .schema import UIIRValidationError

UI_PROVENANCE_INTERFACE: Final = "UIUXIRProvenance@1"


class ArtifactRole(str, Enum):
    """Runtime/derived artifact roles that must not perturb declaration identity."""

    FORMALIZATION = "formalization"
    RECONSTRUCTION = "reconstruction"
    PROJECTION = "projection"
    OBSERVATION = "observation"
    DECISION = "decision"
    INVOCATION = "invocation"
    STATE = "state"
    TELEMETRY = "telemetry"


class NodeOrigin(str, Enum):
    GROUNDED = "grounded"
    INFERRED = "inferred"
    DERIVED = "derived"
    OBSERVATIONAL = "observational"


@dataclass(frozen=True, slots=True)
class ProvenanceNodeBinding:
    node_id: str
    origin: NodeOrigin
    source_ref_ids: tuple[str, ...] = ()
    producer: str = ""
    config_ref: str = ""
    review_status: str = "unreviewed"
    trust_class: str = "untrusted"
    inferred: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    artifact_id: str
    role: ArtifactRole
    parent_declaration_id: str
    content_digest: str
    observational: bool = False


@dataclass(frozen=True, slots=True)
class UIUXIRProvenance:
    declaration_id: str
    declaration_digest: str
    nodes: tuple[ProvenanceNodeBinding, ...]
    artifacts: tuple[RuntimeArtifact, ...] = ()
    schema_version: str = "ui-ux-ir-provenance/v1"


def validate_provenance(model: UIUXIRProvenance) -> UIUXIRProvenance:
    """Validate provenance bindings and declaration/runtime separation."""

    if not model.declaration_id.strip():
        raise UIIRValidationError("declaration_id must not be empty")
    if not model.declaration_digest.startswith("sha256:"):
        raise UIIRValidationError("declaration_digest must be a sha256: digest")
    known_sources: set[str] = set()
    for node in model.nodes:
        if not node.node_id.strip():
            raise UIIRValidationError("ProvenanceNodeBinding.node_id must not be empty")
        if node.origin is NodeOrigin.GROUNDED and not node.source_ref_ids:
            raise UIIRValidationError(
                f"Grounded node {node.node_id!r} must map to exact source_ref_ids"
            )
        if node.origin is NodeOrigin.INFERRED and not node.inferred:
            raise UIIRValidationError(
                f"Inferred node {node.node_id!r} must set inferred=True"
            )
        known_sources.update(node.source_ref_ids)
    for artifact in model.artifacts:
        if artifact.parent_declaration_id != model.declaration_id:
            raise UIIRValidationError(
                f"Artifact {artifact.artifact_id!r} parent_declaration_id must equal "
                "the declaration identity"
            )
        if not artifact.content_digest.startswith("sha256:"):
            raise UIIRValidationError(
                f"Artifact {artifact.artifact_id!r} content_digest must be sha256:"
            )
        # Runtime artifacts never rewrite declaration digest.
        if artifact.content_digest == model.declaration_digest and artifact.observational:
            raise UIIRValidationError(
                f"Observational artifact {artifact.artifact_id!r} must not claim "
                "declaration digest identity"
            )
    return model


def assert_declaration_identity_stable(
    *,
    declaration_digest: str,
    artifacts: tuple[RuntimeArtifact, ...],
) -> None:
    """Fail closed if runtime artifacts attempt to perturb declaration identity."""

    for artifact in artifacts:
        if artifact.role in {
            ArtifactRole.OBSERVATION,
            ArtifactRole.TELEMETRY,
            ArtifactRole.STATE,
            ArtifactRole.INVOCATION,
        } and artifact.content_digest == declaration_digest:
            raise UIIRValidationError(
                f"Runtime artifact {artifact.artifact_id!r} must not equal declaration digest"
            )


__all__ = [
    "ArtifactRole",
    "NodeOrigin",
    "ProvenanceNodeBinding",
    "RuntimeArtifact",
    "UIUXIRProvenance",
    "UI_PROVENANCE_INTERFACE",
    "assert_declaration_identity_stable",
    "validate_provenance",
]

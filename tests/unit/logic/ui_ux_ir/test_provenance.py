"""UIR-015: provenance and declaration/runtime separation."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.provenance import (
    ArtifactRole,
    NodeOrigin,
    ProvenanceNodeBinding,
    RuntimeArtifact,
    UIUXIRProvenance,
    assert_declaration_identity_stable,
    validate_provenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def test_grounded_and_inferred_nodes_validate() -> None:
    model = UIUXIRProvenance(
        declaration_id="doc:form-v1",
        declaration_digest="sha256:" + "a" * 64,
        nodes=(
            ProvenanceNodeBinding(
                node_id="component:root",
                origin=NodeOrigin.GROUNDED,
                source_ref_ids=("source:form-v1",),
                review_status="trusted_fixture",
                trust_class="fixture",
            ),
            ProvenanceNodeBinding(
                node_id="component:inferred-helper",
                origin=NodeOrigin.INFERRED,
                inferred=True,
                producer="heuristic:v1",
            ),
        ),
        artifacts=(
            RuntimeArtifact(
                artifact_id="art:projection-web",
                role=ArtifactRole.PROJECTION,
                parent_declaration_id="doc:form-v1",
                content_digest="sha256:" + "b" * 64,
            ),
            RuntimeArtifact(
                artifact_id="art:obs-1",
                role=ArtifactRole.OBSERVATION,
                parent_declaration_id="doc:form-v1",
                content_digest="sha256:" + "c" * 64,
                observational=True,
            ),
        ),
    )
    validated = validate_provenance(model)
    assert validated.declaration_id == "doc:form-v1"
    assert_declaration_identity_stable(
        declaration_digest=model.declaration_digest,
        artifacts=model.artifacts,
    )


def test_grounded_nodes_require_sources_and_runtime_cannot_claim_declaration() -> None:
    with pytest.raises(UIIRValidationError):
        validate_provenance(
            UIUXIRProvenance(
                declaration_id="doc:x",
                declaration_digest="sha256:" + "a" * 64,
                nodes=(
                    ProvenanceNodeBinding(
                        node_id="n1",
                        origin=NodeOrigin.GROUNDED,
                        source_ref_ids=(),
                    ),
                ),
            )
        )
    declaration = "sha256:" + "a" * 64
    with pytest.raises(UIIRValidationError):
        assert_declaration_identity_stable(
            declaration_digest=declaration,
            artifacts=(
                RuntimeArtifact(
                    artifact_id="art:bad",
                    role=ArtifactRole.OBSERVATION,
                    parent_declaration_id="doc:x",
                    content_digest=declaration,
                    observational=True,
                ),
            ),
        )

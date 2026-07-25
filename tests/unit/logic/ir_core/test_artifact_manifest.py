"""Contract tests for immutable artifact and pipeline-run manifests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

from ipfs_datasets_py.logic.ir_core.artifacts import (
    Artifact,
    ArtifactIntegrityError,
    ArtifactManifest,
    ArtifactManifestValidationError,
    ArtifactRole,
    DecisionKind,
    IntegrityIssueKind,
    ManifestDecision,
    RunObservations,
    artifact_from_path,
)
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bindings() -> tuple[ProducerBinding, ConfigBinding]:
    return (
        ProducerBinding(
            producer_id="producer:compiler",
            name="intent-compiler",
            version="1.4.0",
            implementation_sha256="a" * 64,
            repository_revision="commit:abc123",
        ),
        ConfigBinding(
            config_id="config:compiler",
            content_sha256="b" * 64,
            schema_id="schema:compiler-v1",
        ),
    )


def _manifest(tmp_path, *, reverse: bool = False) -> ArtifactManifest:
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "outputs").mkdir(exist_ok=True)
    (tmp_path / "inputs" / "source.json").write_bytes(b'{"source":1}\n')
    (tmp_path / "outputs" / "ir.json").write_bytes(b'{"ir":1}\n')
    producer, config = _bindings()
    source = artifact_from_path(
        "inputs/source.json",
        root=tmp_path,
        artifact_id="artifact:source",
        role=ArtifactRole.INPUT,
        schema_id="intent.source",
        schema_version="1",
    )
    output = artifact_from_path(
        "outputs/ir.json",
        root=tmp_path,
        artifact_id="artifact:ir",
        role=ArtifactRole.OUTPUT,
        schema_id="intent.ir",
        schema_version="1",
        producer_id=producer.producer_id,
        config_id=config.config_id,
        parent_artifact_ids=(source.artifact_id,),
        review_status="machine_checked",
        trust_decision="quarantined",
    )
    artifacts = (output, source) if reverse else (source, output)
    return ArtifactManifest(
        artifacts=artifacts,
        repository_commit="commit:abc123",
        producers=(producer,),
        configs=(config,),
        schema_versions={"intent.ir": "1", "intent.source": "1"},
        ontology_versions={"intent": "2026.07"},
        tool_versions={"intent-compiler": "1.4.0"},
        model_versions={"normalizer": "model-revision-7"},
        solver_versions={"z3": "4.15.1"},
        prompt_template_digests={"prompt:normalize": "c" * 64},
        diagnostic_ids=("diagnostic:unsupported",),
        decisions=(
            ManifestDecision(
                decision_id="decision:trust",
                kind=DecisionKind.TRUST,
                decision="quarantined",
                subject_ids=(output.artifact_id,),
                authority="policy:intent-ingestion-v1",
            ),
        ),
        deterministic_metadata={"pipeline": {"passes": ["parse", "compile"]}},
        observations=RunObservations(
            started_at="2026-07-25T00:00:00Z",
            finished_at="2026-07-25T00:00:01Z",
            duration_ms=1000,
            environment={"hostname": "runner-a", "python": "3.12.4"},
            resource_usage={"peak_rss": 12345},
        ),
    )


def test_manifest_is_deterministic_immutable_and_round_trips(tmp_path) -> None:
    forward = _manifest(tmp_path)
    reverse = _manifest(tmp_path, reverse=True)

    assert forward.manifest_id == reverse.manifest_id
    assert forward.deterministic_bytes() == reverse.deterministic_bytes()
    assert forward.to_json() == reverse.to_json()
    assert ArtifactManifest.from_json(forward.to_json()) == forward
    assert [item.artifact_id for item in forward.inputs] == ["artifact:source"]
    assert [item.artifact_id for item in forward.outputs] == ["artifact:ir"]

    metadata = {"nested": {"values": ["original"]}}
    artifact = Artifact(
        artifact_id="artifact:immutable",
        role=ArtifactRole.PARENT,
        content_sha256="d" * 64,
        size=3,
        metadata=metadata,
    )
    metadata["nested"]["values"].append("injected")
    assert artifact.metadata["nested"]["values"] == ("original",)
    with pytest.raises(TypeError):
        artifact.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        artifact.size = 4  # type: ignore[misc]


def test_integrity_verification_accepts_exact_complete_root(tmp_path) -> None:
    manifest = _manifest(tmp_path)

    report = manifest.verify_integrity(tmp_path)

    assert report.valid
    assert report.checked_artifact_ids == ("artifact:ir", "artifact:source")


def test_integrity_detects_missing_and_changed_artifacts(tmp_path) -> None:
    missing_manifest = _manifest(tmp_path)
    (tmp_path / "inputs" / "source.json").unlink()

    missing = missing_manifest.audit_integrity(tmp_path)
    assert IntegrityIssueKind.MISSING in missing.issue_kinds
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        missing_manifest.verify_integrity(tmp_path)
    assert exc_info.value.report == missing

    (tmp_path / "inputs" / "source.json").write_bytes(b'{"source":1}\n')
    changed_manifest = _manifest(tmp_path)
    (tmp_path / "outputs" / "ir.json").write_bytes(b"tampered")
    changed = changed_manifest.audit_integrity(tmp_path)
    assert IntegrityIssueKind.CHANGED in changed.issue_kinds
    assert any(
        issue.expected and issue.actual and issue.expected != issue.actual
        for issue in changed.issues
        if issue.kind is IntegrityIssueKind.CHANGED
    )


def test_integrity_detects_duplicate_and_unbound_artifacts(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    duplicate = replace(
        manifest,
        artifacts=manifest.artifacts + (manifest.artifacts[0],),
        manifest_id="",
    )
    report = duplicate.audit_integrity(tmp_path)
    assert IntegrityIssueKind.DUPLICATE in report.issue_kinds
    with pytest.raises(ArtifactManifestValidationError, match="duplicate"):
        duplicate.validate()

    (tmp_path / "outputs" / "unmanifested.log").write_text(
        "not bound", encoding="utf-8"
    )
    report = manifest.audit_integrity(tmp_path)
    assert any(
        issue.kind is IntegrityIssueKind.UNBOUND
        and issue.path == "outputs/unmanifested.log"
        for issue in report.issues
    )

    unbound_parent = replace(
        manifest.outputs[0],
        parent_artifact_ids=("artifact:not-declared",),
    )
    dangling = replace(
        manifest,
        artifacts=(manifest.inputs[0], unbound_parent),
        manifest_id="",
    )
    assert any(
        issue.kind is IntegrityIssueKind.UNBOUND
        for issue in dangling.audit_integrity(
            tmp_path, ignore_paths=("outputs/unmanifested.log",)
        ).issues
    )


def test_observations_cannot_perturb_deterministic_output_identity(tmp_path) -> None:
    first = _manifest(tmp_path)
    second = replace(
        first,
        observations=RunObservations(
            started_at="2099-01-01T00:00:00Z",
            finished_at="2099-01-02T00:00:00Z",
            duration_ms=86_400_000,
            environment={
                "hostname": "different-runner",
                "platform": "different-os",
            },
            resource_usage={"peak_rss": 999_999_999},
        ),
    )

    assert first.output_identity == second.output_identity
    assert first.deterministic_bytes() == second.deterministic_bytes()
    assert first.canonical_bytes() != second.canonical_bytes()

    with pytest.raises(ArtifactManifestValidationError, match="observational"):
        replace(
            first,
            deterministic_metadata={"environment": {"hostname": "leak"}},
            manifest_id="",
        )
    with pytest.raises(ArtifactManifestValidationError, match="observational"):
        replace(
            first.outputs[0],
            metadata={"duration_ms": 4},
        )


def test_paths_and_digest_bindings_fail_closed(tmp_path) -> None:
    with pytest.raises(ArtifactManifestValidationError, match="root-relative"):
        Artifact(
            artifact_id="artifact:escape",
            role=ArtifactRole.INPUT,
            content_sha256=_sha(b"x"),
            size=1,
            path="../escape",
        )
    with pytest.raises(ArtifactManifestValidationError, match="lowercase"):
        Artifact(
            artifact_id="artifact:digest",
            role=ArtifactRole.INPUT,
            content_sha256="A" * 64,
            size=1,
            path="input.bin",
        )

    manifest = _manifest(tmp_path)
    unknown_producer = replace(
        manifest.outputs[0],
        producer_id="producer:unknown",
        config_id="",
    )
    invalid = replace(
        manifest,
        artifacts=(manifest.inputs[0], unknown_producer),
        manifest_id="",
    )
    with pytest.raises(ArtifactManifestValidationError, match="unknown producer"):
        invalid.validate()

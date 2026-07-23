"""Tests for reproducible LegalIR compiler build manifests."""

from __future__ import annotations

import hashlib

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION,
    LEGAL_IR_BUILD_REPLAY_MODULE,
    LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION,
    LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION,
    LegalIRBuildManifest,
    LegalIRBuildManifestError,
    LegalIRPassKind,
    LegalIRPassSpec,
    assert_legal_ir_build_manifest_valid,
    assert_legal_ir_build_reproducible,
    build_legal_ir_build_manifest,
    legal_ir_build_manifest,
    legal_ir_build_manifests_equivalent,
    load_legal_ir_build_manifest,
    run_legal_ir_passes,
    save_legal_ir_build_manifest,
    validate_legal_ir_build_manifest,
    verify_legal_ir_build_manifest,
)


SOURCE_TEXT = "The agency shall disclose records within 30 days."


def _passes() -> tuple[LegalIRPassSpec, ...]:
    return (
        LegalIRPassSpec(
            pass_id="legal_ir.test_normalize",
            title="Normalize source text",
            kind=LegalIRPassKind.COMPILER,
            order=1,
            declared_inputs=("raw_document",),
            declared_outputs=("normalized_document",),
        ),
        LegalIRPassSpec(
            pass_id="legal_ir.test_lower",
            title="Lower test view",
            kind=LegalIRPassKind.COMPILER,
            order=2,
            declared_inputs=("normalized_document",),
            declared_outputs=("lowered_views",),
            depends_on=("legal_ir.test_normalize",),
        ),
    )


def _pass_functions():
    return {
        "legal_ir.test_normalize": lambda state: {
            **state,
            "normalized_document": str(state["raw_document"]).strip().lower(),
        },
        "legal_ir.test_lower": lambda state: {
            **state,
            "lowered_views": {"deontic": state["normalized_document"]},
        },
    }


def _pass_run():
    return run_legal_ir_passes(
        {"raw_document": SOURCE_TEXT},
        _pass_functions(),
        passes=_passes(),
    )


def _manifest():
    run = _pass_run()
    return build_legal_ir_build_manifest(
        sources={
            "doc-42": {
                "source_id": "doc-42",
                "text": SOURCE_TEXT,
                "schema_version": "legal-ir-source-document-v1",
            }
        },
        compiler_commit="abcdef0123456789",
        pass_run=run,
        passes=_passes(),
        model_exports={
            "export-main": {
                "export_id": "export-main",
                "model_id": "legal-ir-leanstral-7b",
                "schema_version": "legal-ir-stable-autoencoder-feature-export-v1",
                "content": {"weights": "frozen"},
            }
        },
        proof_tools={
            "lean": {"tool": "lean", "version": "4.12.0"},
            "z3": "4.13.3",
        },
        runtime_config={
            "cache_namespace": "lir-test-cache",
            "deterministic_seed": 0,
            "parallelism": 1,
        },
        caches={
            "premise-cache": {
                "cache_id": "premise-cache",
                "content": {"premise_ids": ["p1", "p2"]},
                "schema_version": "proof-cache-v1",
            }
        },
        manifest_path="artifacts/legal-ir-build-manifest.json",
        metadata={"task_id": "PORTAL-LIR-HAMMER-092"},
    )


def test_manifest_emits_all_reproducibility_bindings() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()

    assert payload["schema_version"] == LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION
    assert payload["compiler_commit"] == "abcdef0123456789"
    assert payload["source_digests"][0]["sha256"] == hashlib.sha256(
        SOURCE_TEXT.encode("utf-8")
    ).hexdigest()
    assert payload["schema_versions"]["build_manifest"] == LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION
    assert payload["schema_versions"]["pass_manager"] == LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION
    assert payload["schema_versions"]["pass_replay"] == LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION
    assert "legal-ir-stable-autoencoder-feature-export-v1" in payload["schema_versions"][
        "artifact_schema_versions"
    ]
    assert payload["pass_graph"]["ordered_pass_ids"] == [
        "legal_ir.test_normalize",
        "legal_ir.test_lower",
    ]
    assert payload["pass_graph"]["edges"] == [
        {
            "from": "legal_ir.test_normalize",
            "kind": "data:normalized_document",
            "to": "legal_ir.test_lower",
        },
        {
            "from": "legal_ir.test_normalize",
            "kind": "declared_dependency",
            "to": "legal_ir.test_lower",
        },
    ]
    assert payload["model_export_ids"][0]["model_id"] == "legal-ir-leanstral-7b"
    assert payload["model_export_ids"][0]["export_id"] == "export-main"
    assert {item["tool"]: item["version"] for item in payload["proof_tool_versions"]} == {
        "lean": "4.12.0",
        "z3": "4.13.3",
    }
    assert payload["runtime_configuration"]["deterministic_seed"] == 0
    assert payload["cache_digests"][0]["artifact_id"] == "premise-cache"
    assert payload["output_digests"][0]["artifact_id"] == "legal-ir-pass-output-state"
    assert payload["pass_replay_digest"] == _pass_run().replay_digest
    assert payload["deterministic_replay_command"][:3] == [
        "python",
        "-m",
        LEGAL_IR_BUILD_REPLAY_MODULE,
    ]
    assert payload["deterministic_replay_command"][-1] == payload["output_digest"]
    assert assert_legal_ir_build_manifest_valid(manifest).valid


def test_equivalent_inputs_produce_equivalent_manifests_and_outputs() -> None:
    first = _manifest()
    second = build_legal_ir_build_manifest(
        sources=[
            {
                "schema_version": "legal-ir-source-document-v1",
                "text": SOURCE_TEXT,
                "source_id": "doc-42",
            }
        ],
        compiler_commit="abcdef0123456789",
        pass_run=_pass_run(),
        passes=tuple(reversed(_passes())),
        model_exports=[
            {
                "content": {"weights": "frozen"},
                "export_id": "export-main",
                "model_id": "legal-ir-leanstral-7b",
                "schema_version": "legal-ir-stable-autoencoder-feature-export-v1",
            }
        ],
        proof_tools=[
            {"tool": "z3", "version": "4.13.3"},
            {"tool": "lean", "version": "4.12.0"},
        ],
        runtime_config={
            "parallelism": 1,
            "deterministic_seed": 0,
            "cache_namespace": "lir-test-cache",
        },
        caches=[
            {
                "schema_version": "proof-cache-v1",
                "content": {"premise_ids": ["p1", "p2"]},
                "cache_id": "premise-cache",
            }
        ],
        manifest_path="artifacts/legal-ir-build-manifest.json",
        metadata={"task_id": "PORTAL-LIR-HAMMER-092"},
    )

    assert first.output_digest == second.output_digest
    assert first.pass_replay_digest == second.pass_replay_digest
    assert first.manifest_sha256() == second.manifest_sha256()
    assert legal_ir_build_manifests_equivalent(first, second)
    assert_legal_ir_build_reproducible(first, second)


def test_manifest_round_trips_and_replay_command_verifies_output(tmp_path) -> None:
    manifest = _manifest()
    path = tmp_path / "legal-ir-build-manifest.json"

    save_legal_ir_build_manifest(manifest, path)
    loaded = load_legal_ir_build_manifest(path)
    result = verify_legal_ir_build_manifest(
        path,
        expected_output_digest=manifest.output_digest,
    )

    assert loaded.to_dict() == manifest.to_dict()
    assert result.valid
    with pytest.raises(LegalIRBuildManifestError):
        verify_legal_ir_build_manifest(
            path,
            expected_output_digest="0" * 64,
        )


def test_validation_rejects_incomplete_manifest() -> None:
    invalid = LegalIRBuildManifest.from_dict(
        {
            "build_id": "legal-ir-build-invalid",
            "compiler_commit": "",
            "source_digests": [],
            "schema_versions": {},
            "pass_graph": {},
            "input_digest": "not-a-digest",
            "output_digest": "",
            "deterministic_replay_command": [],
            "replay_command": "",
        }
    )

    result = validate_legal_ir_build_manifest(invalid)

    assert not result.valid
    assert {
        "compiler_commit_missing",
        "source_digests_missing",
        "schema_version_binding_missing",
        "pass_graph_missing",
        "input_digest_invalid",
        "output_digest_invalid",
        "replay_command_missing",
    } <= {diagnostic.code for diagnostic in result.diagnostics}
    with pytest.raises(LegalIRBuildManifestError):
        assert_legal_ir_build_manifest_valid(invalid)


def test_dict_api_matches_typed_manifest() -> None:
    typed = _manifest()
    payload = legal_ir_build_manifest(
        sources={"doc-42": {"text": SOURCE_TEXT, "schema_version": "legal-ir-source-document-v1"}},
        compiler_commit="abcdef0123456789",
        pass_run=_pass_run(),
        passes=_passes(),
        model_exports={
            "export-main": {
                "content": {"weights": "frozen"},
                "export_id": "export-main",
                "model_id": "legal-ir-leanstral-7b",
                "schema_version": "legal-ir-stable-autoencoder-feature-export-v1",
            }
        },
        proof_tools={"lean": {"tool": "lean", "version": "4.12.0"}, "z3": "4.13.3"},
        runtime_config={
            "cache_namespace": "lir-test-cache",
            "deterministic_seed": 0,
            "parallelism": 1,
        },
        caches={
            "premise-cache": {
                "cache_id": "premise-cache",
                "content": {"premise_ids": ["p1", "p2"]},
                "schema_version": "proof-cache-v1",
            }
        },
        manifest_path="artifacts/legal-ir-build-manifest.json",
        metadata={"task_id": "PORTAL-LIR-HAMMER-092"},
    )

    assert payload == typed.to_dict()

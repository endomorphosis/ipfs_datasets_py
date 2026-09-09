"""PCPR-015: package schemas and shared vectors."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.schema_packaging import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    MANIFEST_LINES,
    OutcomeProbe,
    PACKAGING_GLOBS,
    PCPR_015_GOAL_ID,
    PCPR_015_TASK_ID,
    PCPR_STABLE_SCHEMA_NAMES,
    SCHEMA,
    VECTOR_INTERFACE,
    SchemaPackagingAdmissionError,
    SchemaPackagingError,
    admit_schema_path,
    current_head_static_probes,
    evaluate_shared_vectors,
    load_schema_catalog,
    load_schema_document,
    packaged_schema_spec,
    pcpr_015_receipt_promotion,
    qualify_current_head_schema_packaging,
    qualify_schema_packaging,
    schema_packaging_manifest,
    shared_vector_specs,
    validate_payload,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_015_requirements() -> None:
    assert PCPR_015_TASK_ID == "PCPR-015"
    assert PCPR_015_GOAL_ID == "PCPR-G230"
    assert INTERFACE == "DatasetsSchemaPackaging@1"
    assert VECTOR_INTERFACE == "DatasetsSharedVectors@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/schema-packaging-catalog@1"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith("test_pcpr_015_schema_packaging.py")
    assert PCPR_STABLE_SCHEMA_NAMES[1] == "datasets_context_pack"
    with pytest.raises(KeyError, match="unknown packaged schema"):
        packaged_schema_spec("promote")


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_schema_packaging()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.schemas_packaged is True
    assert verdict.shared_vectors_packaged is True
    assert verdict.sibling_tests_required is False
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_015_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["schemas_packaged"] is True
    assert section["shared_vectors_packaged"] is True
    assert section["live_solver_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_packaged_schemas_and_vectors() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["catalog_packaged"].present is True
    assert probes["pcpr_schemas_packaged"].present is True
    assert probes["owner_schemas_packaged"].present is True
    assert probes["shared_vectors_packaged"].present is True
    assert probes["sibling_tests_not_required"].present is True
    assert probes["tests_path_rejected"].present is True
    assert probes["packaging_globs_declared"].present is True
    assert probes["packaging_manifest_in"].present is True
    assert probes["packaging_setup_py"].present is True
    assert probes["packaging_pyproject"].present is True
    assert probes["include_package_data"].present is True
    assert probes["positive_vectors_admit"].present is True
    assert probes["negative_vectors_reject"].present is True
    assert probes["identity_deterministic"].present is True
    assert probes["manifest_advertises_packaging"].present is True
    assert probes["loader_does_not_use_tests_tree"].present is True
    assert probes["sibling_tests_loader_used"].present is False
    assert probes["simulated_results_represented_as_live"].present is False
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["live_solver_qualification"].live is False
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_catalog_and_schemas_load_via_package_data() -> None:
    catalog = load_schema_catalog()
    assert catalog["requires_sibling_tests_tree"] is False
    assert catalog["interface"] == INTERFACE
    document = load_schema_document("datasets_context_pack")
    assert document["x-interface"] == "DatasetsContextPack@1"
    owner = load_schema_document("legal_ir_canonical_roundtrip")
    assert isinstance(owner, dict)
    assert "$id" in owner or "$schema" in owner or "properties" in owner
    manifest = schema_packaging_manifest()
    assert manifest["requires_sibling_tests_tree"] is False
    assert "datasets_context_pack" in manifest["schema_names"]
    assert manifest["import_side_effects"] == "none"


def test_packaging_files_declare_schemas_and_vectors() -> None:
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup = (_PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
    manifest = (_PACKAGE_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for glob in PACKAGING_GLOBS:
        assert glob in pyproject
        assert glob in setup
    for line in MANIFEST_LINES:
        assert line in manifest
    assert "include-package-data = true" in pyproject


def test_manifest_advertises_schema_packaging() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSchemaPackaging@1"] == "1"
    assert versions["DatasetsSharedVectors@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_schema_packaging"
    ].endswith("schema-packaging-catalog@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_shared_vectors"
    ].endswith("shared-vectors@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["schema_packaging"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_sibling_tests_paths_fail_closed() -> None:
    with pytest.raises(SchemaPackagingAdmissionError, match="sibling tests tree"):
        admit_schema_path("tests/fixtures/context_pack.json")
    with pytest.raises(SchemaPackagingAdmissionError, match="sibling tests tree"):
        admit_schema_path("../tests/fixtures/x.json")
    admitted = admit_schema_path(
        "ipfs_datasets_py/assurance/schemas/datasets-context-pack.schema.json"
    )
    assert admitted.endswith("datasets-context-pack.schema.json")


def test_positive_and_negative_shared_vectors() -> None:
    specs = {item.vector_id: item for item in shared_vector_specs()}
    assert "context_pack_positive" in specs
    assert specs["context_pack_freeform_rejected"].polarity == "negative"
    validate_payload("datasets_context_pack", dict(specs["context_pack_positive"].payload))
    with pytest.raises(SchemaPackagingAdmissionError, match="unknown field"):
        validate_payload(
            "datasets_context_pack",
            dict(specs["context_pack_freeform_rejected"].payload),
        )
    with pytest.raises(SchemaPackagingAdmissionError, match="minimum"):
        validate_payload(
            "interpolation_bounds",
            dict(specs["interpolation_missing_bounds_rejected"].payload),
        )
    results = {item["vector_id"]: item for item in evaluate_shared_vectors()}
    assert results["context_pack_positive"]["matched"] is True
    assert results["context_pack_freeform_rejected"]["matched"] is True
    assert results["context_pack_advisory_rejected"]["matched"] is True
    assert results["sibling_tests_path_rejected"]["matched"] is True
    assert results["simulated_as_live_rejected"]["matched"] is True
    assert results["admitted_unresolved_rights_rejected"]["matched"] is True
    assert results["sibling_tests_path_rejected"]["admitted"] is False
    for item in results.values():
        assert item["matched"] is True


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(SchemaPackagingError, match="simulated"):
        qualify_schema_packaging(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_live_claim_without_measured_live_evidence_is_rejected() -> None:
    with pytest.raises(SchemaPackagingError, match="measured_live"):
        qualify_schema_packaging(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=True,
                    evidence_kind="measured",
                    live=True,
                    simulated_represented_as_live=False,
                    reason="must fail",
                ),
            )
        )


def test_receipt_promotion_rejects_closed_release() -> None:
    verdict = qualify_current_head_schema_packaging()
    mutated = replace(
        verdict, closed_release_outcome="release_candidate_qualified"
    )
    with pytest.raises(SchemaPackagingError, match="closed release"):
        pcpr_015_receipt_promotion(mutated)


def test_source_files_exist_under_datasets_root() -> None:
    assert (
        _PACKAGE_ROOT / "ipfs_datasets_py" / "assurance" / "schema_packaging.py"
    ).is_file()
    assert (
        _PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "assurance"
        / "schemas"
        / "catalog.json"
    ).is_file()
    assert (
        _PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "assurance"
        / "vectors"
        / "recipes.json"
    ).is_file()

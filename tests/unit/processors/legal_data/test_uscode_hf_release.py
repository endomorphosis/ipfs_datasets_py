"""Unit tests for additive US Code Hugging Face release packaging (USCIR-031)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
    CONTROL_PLANE_PATHS,
    DEFAULT_CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    MANIFEST_FILENAME,
    README_FILENAME,
    RECOVERY_CONFIG_NAME,
    RELEASE_METADATA_FILENAME,
    SCHEMA_VERSION,
    TASK_ID,
    UscodeHFReleaseConfigError,
    UscodeHFReleaseSafetyError,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
    build_uscode_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    load_fixture_dataset_card,
    load_fixture_manifest,
    releases_are_byte_identical,
    render_dataset_card,
    stage_uscode_hf_release,
    validate_uscode_hf_release,
)

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir"
MANIFEST_FIXTURE = FIXTURE_DIR / "uscode_manifest.json"
CARD_FIXTURE = FIXTURE_DIR / "uscode_dataset_card.md"


def _build_fixture_release(**kwargs):
    return build_uscode_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Fixtures on disk
# ---------------------------------------------------------------------------


def test_sealed_manifest_fixture_exists_and_declares_acceptance() -> None:
    assert MANIFEST_FIXTURE.is_file()
    payload = json.loads(MANIFEST_FIXTURE.read_text(encoding="utf-8"))
    acceptance = payload["acceptance"]
    assert acceptance["default_config_excludes_recovery"] is True
    assert acceptance["all_advertised_configs_schema_coherent"] is True
    assert acceptance["every_artifact_descriptor_bound"] is True
    assert acceptance["verbose_lineage_separate_from_control_plane"] is True
    assert acceptance["legacy_files_not_deleted"] is True
    assert payload["default_config"] == DEFAULT_CONFIG_NAME
    assert payload["default_excludes_recovery"] is True
    assert payload["legacy_files_deleted"] is False
    assert payload["lineage_is_control_plane"] is False
    assert payload["lineage_report"] == LINEAGE_REPORT_PATH
    assert payload["task_id"] == TASK_ID
    assert LINEAGE_REPORT_PATH not in payload["control_plane"]


def test_sealed_manifest_fixture_configs_are_schema_coherent() -> None:
    payload = load_fixture_manifest(MANIFEST_FIXTURE)
    receipt = assert_configs_schema_coherent(payload["configs"])
    assert receipt["schema_coherent"] is True
    assert receipt["default_config"] == DEFAULT_CONFIG_NAME
    names = {cfg["config_name"] for cfg in payload["configs"]}
    assert DEFAULT_CONFIG_NAME in names
    assert LEGACY_CONFIG_NAME in names
    assert RECOVERY_CONFIG_NAME in names
    default = next(c for c in payload["configs"] if c["is_default"])
    for entry in default["data_files"]:
        assert "recovery" not in entry["path"]


def test_sealed_manifest_fixture_descriptors_are_bound() -> None:
    payload = load_fixture_manifest(MANIFEST_FIXTURE)
    required = {
        "relative_path",
        "media_type",
        "sha256",
        "size_bytes",
        "schema_id",
        "family",
        "row_count",
    }
    for desc in payload["sample_artifact_descriptors"]:
        assert required <= set(desc)
        assert len(desc["sha256"]) == 64
        assert not desc["relative_path"].startswith("/")
        assert ".." not in desc["relative_path"]


def test_sealed_dataset_card_fixture_documents_configs() -> None:
    assert CARD_FIXTURE.is_file()
    card = load_fixture_dataset_card(CARD_FIXTURE)
    assert card.startswith("---\n")
    assert "configs:" in card
    assert DEFAULT_CONFIG_NAME in card
    assert LEGACY_CONFIG_NAME in card
    assert RECOVERY_CONFIG_NAME in card
    assert "recovery" in card.lower()
    assert "lineage" in card.lower()
    assert "legacy" in card.lower()
    # Default config path in frontmatter is data glob, not recovery.
    front = card.split("---", 2)[1]
    assert 'path: "data/**/*.parquet"' in front
    assert 'config_name: "publicus-ir-graphrag/v2"' in front
    # Recovery appears only as its own config block.
    assert 'config_name: "recovery-quarantine/v1"' in front


# ---------------------------------------------------------------------------
# Viewer configs
# ---------------------------------------------------------------------------


def test_advertised_configs_schema_coherent() -> None:
    configs = advertised_viewer_configs()
    receipt = assert_configs_schema_coherent(configs)
    assert receipt["schema_coherent"] is True
    assert receipt["default_excludes_recovery"] is True
    defaults = [c for c in configs if c.is_default]
    assert len(defaults) == 1
    assert defaults[0].config_name == DEFAULT_CONFIG_NAME
    for entry in defaults[0].data_files:
        assert "recovery" not in entry["path"]


def test_default_config_cannot_advertise_recovery_path() -> None:
    configs = list(advertised_viewer_configs(include_recovery=False))
    bad = configs[0].to_dict()
    bad["data_files"] = [{"split": "train", "path": "recovery/**/*.json"}]
    with pytest.raises(UscodeHFReleaseSafetyError):
        assert_configs_schema_coherent([bad, *configs[1:]])


def test_two_defaults_rejected() -> None:
    configs = advertised_viewer_configs(include_legacy=False, include_recovery=False)
    twin = configs[0].to_dict()
    twin["config_name"] = "publicus-ir-graphrag/v2-dup"
    with pytest.raises(UscodeHFReleaseConfigError):
        assert_configs_schema_coherent([configs[0], twin])


# ---------------------------------------------------------------------------
# Live release build
# ---------------------------------------------------------------------------


def test_build_is_byte_identical_across_runs() -> None:
    a = _build_fixture_release()
    b = _build_fixture_release()
    assert releases_are_byte_identical(a, b)
    assert a.manifest_digest == b.manifest_digest
    assert a.release_root_cid == b.release_root_cid


def test_validate_acceptance_contract() -> None:
    release = _build_fixture_release()
    receipt = validate_uscode_hf_release(release)
    assert receipt["valid"] is True
    acc = receipt["acceptance"]
    assert acc["default_config_excludes_recovery"] is True
    assert acc["all_advertised_configs_schema_coherent"] is True
    assert acc["every_artifact_descriptor_bound"] is True
    assert acc["verbose_lineage_separate_from_control_plane"] is True
    assert acc["legacy_files_not_deleted"] is True


def test_default_config_excludes_recovery_json() -> None:
    release = _build_fixture_release()
    default = next(c for c in release.configs if c.is_default)
    assert default.config_name == DEFAULT_CONFIG_NAME
    for entry in default.data_files:
        assert "recovery" not in entry["path"]
    for art in release.artifacts:
        if art.relative_path.startswith("recovery/"):
            assert art.config_name == RECOVERY_CONFIG_NAME
            assert art.family == "recovery"
            assert art.media_type.startswith("application/json")
        if art.config_name == DEFAULT_CONFIG_NAME:
            assert art.family != "recovery"
    manifest = release.manifest_dict()
    assert manifest["default_excludes_recovery"] is True


def test_every_artifact_is_descriptor_bound() -> None:
    release = _build_fixture_release()
    for art in release.artifacts:
        desc = art.to_artifact_descriptor()
        payload = desc.to_dict()
        assert payload["relative_path"] == art.relative_path
        assert payload["sha256"] == art.sha256
        assert payload["size_bytes"] == art.size_bytes
        assert payload["media_type"] == art.media_type
        assert payload["schema_id"]
        assert payload["family"]
        assert art.content_cid.startswith("b")
        assert len(art.sha256) == 64


def test_verbose_lineage_separate_from_control_plane() -> None:
    release = _build_fixture_release()
    assert LINEAGE_REPORT_PATH not in CONTROL_PLANE_PATHS
    lineage = release.lineage_artifact
    assert lineage is not None
    body = json.loads(lineage.content.decode("utf-8"))
    assert body["control_plane"] is False
    assert body["separate_from_control_plane"] is True
    assert isinstance(body["rows"], list) and body["rows"]
    manifest = release.manifest_dict()
    assert manifest["lineage_is_control_plane"] is False
    assert manifest["lineage_report"] == LINEAGE_REPORT_PATH
    # Compact control-plane reports must not embed verbose lineage rows.
    for path in (
        "reports/admission.json",
        "reports/quality.json",
        "reports/reproducibility.json",
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
    ):
        plane = json.loads(release.artifact(path).content.decode("utf-8"))
        assert not (
            isinstance(plane.get("rows"), list)
            and plane["rows"]
            and any(
                isinstance(r, dict) and "source_cid" in r for r in plane["rows"]
            )
        )


def test_legacy_files_not_deleted_on_stage(tmp_path: Path) -> None:
    legacy_path = "uscode_parquet/laws.parquet"
    # Pre-seed an operator legacy file that packaging must retain.
    legacy_target = tmp_path / legacy_path
    legacy_target.parent.mkdir(parents=True, exist_ok=True)
    original = b"LEGACY-MONOLITH-BYTES-MUST-REMAIN\n"
    legacy_target.write_bytes(original)

    release = build_uscode_hf_release(
        fixture_family_rows(),
        # Do not re-emit legacy in this staging pass; preserve existing.
        legacy_files=None,
        include_legacy_config=False,
        dry_run=False,
        output_dir=tmp_path,
        preserve_existing=(legacy_path,),
    )
    assert release.dry_run is False
    assert release.staged_root is not None
    assert legacy_target.is_file()
    assert legacy_target.read_bytes() == original
    # New v2 artifacts are present.
    assert (tmp_path / MANIFEST_FILENAME).is_file()
    assert (tmp_path / README_FILENAME).is_file()
    assert (tmp_path / "data" / "corpus" / "part-000000.parquet").is_file()
    receipt = validate_uscode_hf_release(release)
    assert receipt["acceptance"]["legacy_files_not_deleted"] is True


def test_stage_preserves_and_binds_legacy_when_reemitted(tmp_path: Path) -> None:
    legacy = fixture_legacy_files()
    release = build_uscode_hf_release(
        fixture_family_rows(),
        legacy_files=legacy,
        dry_run=False,
        output_dir=tmp_path,
        preserve_existing=tuple(legacy),
    )
    for path, content in legacy.items():
        on_disk = tmp_path / path
        assert on_disk.is_file()
        assert on_disk.read_bytes() == content
    assert any(c.is_legacy for c in release.configs)
    assert any(c.is_recovery for c in release.configs)


def test_dataset_card_matches_advertised_configs() -> None:
    release = _build_fixture_release()
    card = release.dataset_card_text()
    assert card.startswith("---\n")
    for cfg in release.configs:
        assert cfg.config_name in card
    rendered = render_dataset_card(configs=release.configs)
    assert DEFAULT_CONFIG_NAME in rendered
    assert "reports/lineage.json" in rendered


def test_manifest_and_metadata_are_control_plane() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    metadata = release.release_metadata_dict()
    assert manifest["schema_version"]
    assert manifest["release_profile"] == "publicus-ir-graphrag/v2"
    assert manifest["additive_packaging"] is True
    assert manifest["legacy_files_deleted"] is False
    assert metadata["uses_hf_api_upload_file"] is False
    assert metadata["upload_path"] is None
    assert metadata["lineage_is_control_plane"] is False
    assert release.schema_version == SCHEMA_VERSION


def test_stage_dry_run_does_not_write(tmp_path: Path) -> None:
    release = _build_fixture_release()
    staged = stage_uscode_hf_release(release, tmp_path, dry_run=True)
    assert staged.dry_run is True
    assert list(tmp_path.iterdir()) == []


def test_recovery_contamination_of_default_fails_validation() -> None:
    release = _build_fixture_release()
    # Mutate a recovery artifact to claim the default config name.
    tainted = []
    for art in release.artifacts:
        if art.relative_path.startswith("recovery/"):
            from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
                ReleaseArtifact,
            )

            tainted.append(
                ReleaseArtifact(
                    relative_path=art.relative_path,
                    content=art.content,
                    media_type=art.media_type,
                    family=art.family,
                    row_count=art.row_count,
                    config_name=DEFAULT_CONFIG_NAME,
                    schema_id=art.schema_id,
                    first_key=art.first_key,
                    last_key=art.last_key,
                )
            )
        else:
            tainted.append(art)
    from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
        UscodeHuggingFaceRelease,
    )

    bad = UscodeHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        release_point=release.release_point,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        configs=release.configs,
        artifacts=tuple(tainted),
        dry_run=True,
    )
    with pytest.raises(UscodeHFReleaseSafetyError):
        validate_uscode_hf_release(bad)


def test_no_huggingface_hub_upload_surface() -> None:
    import inspect

    import ipfs_datasets_py.processors.legal_data.uscode_hf_release as mod

    source = inspect.getsource(mod)
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    # Call forms must not appear outside documentation of the ban.
    assert "HfApi(" not in source.replace(
        "HfApi construction is forbidden in uscode_hf_release", ""
    )

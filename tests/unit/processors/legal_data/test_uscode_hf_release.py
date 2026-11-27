"""Unit tests for additive US Code Hugging Face release packaging (USCIR-031)."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.release import canonical_json_bytes
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
    CONTROL_PLANE_PATHS,
    DATASET_INFOS_FILENAME,
    DEFAULT_CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    MANIFEST_FILENAME,
    README_FILENAME,
    RECOVERY_CONFIG_NAME,
    RELEASE_METADATA_FILENAME,
    SCHEMA_VERSION,
    TASK_ID,
    UscodeHFReleaseBuilder,
    UscodeHFReleaseConfigError,
    UscodeHFReleaseIntegrityError,
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
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    digest_mapping,
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


def _replace_release_artifact(release, path, content):
    artifact = replace(release.artifact(path), content=content, sha256="", content_cid="")
    return replace(
        release,
        artifacts=tuple(
            artifact if item.relative_path == path else item for item in release.artifacts
        ),
    )


def _replace_release_manifest(release, manifest, *, reseal):
    if reseal:
        manifest.pop("manifest_digest")
        manifest["manifest_digest"] = digest_mapping(manifest)
        release = replace(release, manifest_digest=manifest["manifest_digest"])
    return _replace_release_artifact(
        release, MANIFEST_FILENAME, canonical_json_bytes(manifest) + b"\n"
    )


def _replace_release_metadata(release, metadata, manifest):
    release = _replace_release_artifact(
        release, RELEASE_METADATA_FILENAME, canonical_json_bytes(metadata) + b"\n"
    )
    descriptor = (
        release.artifact(RELEASE_METADATA_FILENAME).to_artifact_descriptor().to_dict()
    )
    manifest["artifacts"] = [
        descriptor if item["relative_path"] == RELEASE_METADATA_FILENAME else item
        for item in manifest["artifacts"]
    ]
    return _replace_release_manifest(release, manifest, reseal=True)


def test_validate_rejects_shard_with_stale_manifest_descriptor() -> None:
    release = _build_fixture_release()
    shard = release.data_artifacts[0]
    bad = _replace_release_artifact(
        release, shard.relative_path, shard.content + b"changed"
    )
    with pytest.raises(UscodeHFReleaseIntegrityError, match="manifest artifact descriptors"):
        validate_uscode_hf_release(bad)


@pytest.mark.parametrize("mutation", ["drop", "family", "self_entry"])
def test_validate_rejects_resealed_manifest_descriptor_changes(mutation) -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    descriptors = manifest["artifacts"]
    if mutation == "drop":
        descriptors.pop(0)
    elif mutation == "family":
        descriptors[0]["family"] = "corpus"
    else:
        descriptors.append(
            release.artifact(MANIFEST_FILENAME).to_artifact_descriptor().to_dict()
        )
    bad = _replace_release_manifest(release, manifest, reseal=True)
    with pytest.raises(UscodeHFReleaseIntegrityError, match="manifest artifact descriptors"):
        validate_uscode_hf_release(bad)


def test_validate_recomputes_digest_from_manifest_body() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    manifest["source_revision"] = "a" * 40
    bad = _replace_release_manifest(release, manifest, reseal=False)
    with pytest.raises(UscodeHFReleaseIntegrityError, match="manifest_digest mismatch"):
        validate_uscode_hf_release(bad)


def test_validate_recomputes_root_even_when_resealed_manifest_echoes_it() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    forged_root = "a" * 64
    manifest["release_root_cid"] = forged_root
    metadata = release.release_metadata_dict()
    metadata["release_root_cid"] = forged_root
    bad = _replace_release_metadata(
        replace(release, release_root_cid=forged_root), metadata, manifest
    )
    with pytest.raises(UscodeHFReleaseIntegrityError, match="release_root_cid mismatch"):
        validate_uscode_hf_release(bad)


def test_validate_rejects_release_with_different_source_revision() -> None:
    release = _build_fixture_release()
    with pytest.raises(UscodeHFReleaseIntegrityError, match="manifest source_revision mismatch"):
        validate_uscode_hf_release(replace(release, source_revision="a" * 40))


@pytest.mark.parametrize(
    "field, value", [("source_revision", "a" * 40), ("model_revision", "b" * 40)]
)
def test_validate_rejects_resealed_metadata_with_different_revision(field, value) -> None:
    release = _build_fixture_release()
    metadata = release.release_metadata_dict()
    metadata[field] = value
    bad = _replace_release_metadata(release, metadata, release.manifest_dict())
    with pytest.raises(UscodeHFReleaseIntegrityError, match=f"release metadata {field} mismatch"):
        validate_uscode_hf_release(bad)


@pytest.mark.parametrize(
    "field, value",
    [
        ("model_revision", "a" * 40),
        ("source_revision", "b" * 40),
        ("tokenizer_id", "changed-tokenizer/v1"),
        ("vector_space_id", "changed-vector-space/v1"),
        ("determinism_seed", 17),
    ],
)
def test_validate_rejects_reissued_metadata_and_manifest_with_different_provenance(
    field, value
) -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    metadata = release.release_metadata_dict()
    metadata[field] = value
    if field == "determinism_seed":
        manifest["determinism_seeds"]["build"] = value
    else:
        manifest[field] = value
    if field in {"source_revision", "vector_space_id"}:
        release = replace(release, **{field: value})
    bad = _replace_release_metadata(release, metadata, manifest)
    assert bad.release_root_cid == release.release_root_cid
    with pytest.raises(
        UscodeHFReleaseIntegrityError, match=f"release reproducibility {field} mismatch"
    ):
        validate_uscode_hf_release(bad)


def test_validate_rejects_manifest_build_seed_drift() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    manifest["determinism_seeds"]["build"] = 17
    bad = _replace_release_manifest(release, manifest, reseal=True)
    with pytest.raises(
        UscodeHFReleaseIntegrityError, match="manifest build determinism_seed mismatch"
    ):
        validate_uscode_hf_release(bad)


def test_validate_recomputes_build_configuration_digest() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    metadata = release.release_metadata_dict()
    metadata["graph_ontology_version"] = "changed-ontology/v1"
    manifest["graph_ontology_version"] = metadata["graph_ontology_version"]
    bad = _replace_release_metadata(release, metadata, manifest)
    with pytest.raises(UscodeHFReleaseIntegrityError, match="build configuration digest mismatch"):
        validate_uscode_hf_release(bad)


def test_validate_accepts_nondefault_shard_limit_and_build_seed() -> None:
    release = UscodeHFReleaseBuilder(max_rows_per_shard=2, determinism_seed=17).build(
        fixture_family_rows(), legacy_files=fixture_legacy_files()
    )
    assert release.release_metadata_dict()["determinism_seed"] == 17
    assert validate_uscode_hf_release(release)["valid"] is True


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
    original_inodes = {}
    for path, content in legacy.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        original_inodes[path] = target.stat().st_ino
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
        assert on_disk.stat().st_ino == original_inodes[path]
    assert any(c.is_legacy for c in release.configs)
    assert any(c.is_recovery for c in release.configs)


@pytest.mark.parametrize("use_parent_alias", [False, True])
def test_stage_rejects_conflicting_preserved_legacy_before_writing(
    tmp_path: Path, use_parent_alias: bool
) -> None:
    release = _build_fixture_release()
    legacy_path = next(iter(fixture_legacy_files()))
    target = tmp_path / legacy_path
    target.parent.mkdir(parents=True)
    original = b"existing legacy bytes"
    assert release.artifact(legacy_path).content != original
    target.write_bytes(original)
    protected = target.parent / ".." / target.parent.name / target.name if use_parent_alias else target

    with pytest.raises(UscodeHFReleaseSafetyError, match="preserved legacy file"):
        stage_uscode_hf_release(
            release, tmp_path, dry_run=False, preserve_existing=(str(protected.relative_to(tmp_path)),)
        )

    assert target.read_bytes() == original
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [target]


def test_dataset_card_matches_advertised_configs() -> None:
    release = _build_fixture_release()
    card = release.dataset_card_text()
    assert card.startswith("---\n")
    for cfg in release.configs:
        assert cfg.config_name in card
    rendered = render_dataset_card(configs=release.configs)
    assert DEFAULT_CONFIG_NAME in rendered
    assert "reports/lineage.json" in rendered


def test_dataset_card_uses_safe_hub_names_and_marks_default() -> None:
    release = _build_fixture_release()
    front = release.dataset_card_text().split("---", 2)[1]
    names = [
        json.loads(line.split(": ", 1)[1])
        for line in front.splitlines()
        if line.startswith("- config_name: ")
    ]
    assert names == [
        "publicus-ir-graphrag-v2",
        "legacy-uscode-parquet-v1",
        "recovery-quarantine-v1",
    ]
    assert front.count("  default: true") == 1
    assert 'config_name: "publicus-ir-graphrag-v2"\n  default: true\n' in front
    legacy_front = front.split('- config_name: "legacy-uscode-parquet-v1"', 1)[1].split(
        '- config_name: "recovery-quarantine-v1"', 1
    )[0]
    assert legacy_front.count('  - split: "train"') == 1
    legacy = next(cfg for cfg in release.configs if cfg.is_legacy)
    assert '    path:\n' + ''.join(f'    - {json.dumps(item["path"])}\n' for item in legacy.data_files) in legacy_front
    assert release.manifest_dict()["default_config"] == DEFAULT_CONFIG_NAME
    assert [config["config_name"] for config in release.manifest_dict()["configs"]] == [
        DEFAULT_CONFIG_NAME, LEGACY_CONFIG_NAME, RECOVERY_CONFIG_NAME,
    ]


def test_dataset_card_rejects_colliding_hub_names() -> None:
    configs = advertised_viewer_configs()
    collision = replace(configs[0], config_name="publicus-ir-graphrag-v2", is_default=False)
    with pytest.raises(UscodeHFReleaseConfigError, match="Hub config names must be unique"):
        render_dataset_card(configs=(*configs, collision))


def test_dataset_infos_matches_hub_aliases_and_the_viewer_shard_population() -> None:
    release = _build_fixture_release()
    artifact = next(art for art in release.artifacts if art.relative_path == DATASET_INFOS_FILENAME)
    infos = json.loads(artifact.content)
    default_name = "publicus-ir-graphrag-v2"
    assert set(infos) == {default_name, "legacy-uscode-parquet-v1", "recovery-quarantine-v1"}
    shards = [art for art in release.artifacts if art.relative_path.startswith("data/")]
    routing = [art for art in release.artifacts if art.family == "routing_index"]
    assert shards and routing and all(art.row_count > 0 for art in routing)
    assert infos[default_name] == {
        "config_name": default_name,
        "dataset_name": release.dataset_id,
        "download_size": sum(art.size_bytes for art in shards),
        "features": {
            name: {"dtype": "string", "_type": "Value"}
            for name in ("entry_cid", "legal_id", "family", "record_json", "record_sha256")
        },
        "splits": {"train": {"name": "train", "num_examples": sum(art.row_count for art in shards)}},
    }
    for name in ("legacy-uscode-parquet-v1", "recovery-quarantine-v1"):
        assert infos[name] == {"config_name": name, "dataset_name": release.dataset_id}


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


# Explicit wire metadata is an opt-in producer profile, not a new importer.
def _wire_profile_fixture(**kwargs):
    return _build_fixture_release(metadata_profile="hf-default-parquet-envelope/v1", **kwargs)


def _wire_profile_intake(release):
    import hashlib
    from ipfs_datasets_py.logic.autoformal import legal_source_package_intake_v1 as intake
    blobs = {name: release.artifact(name).content for name in intake.FILES}
    manifest = release.manifest_dict()
    descriptors = manifest["artifacts"]
    request = {
        "schema": intake.REQUEST_SCHEMA_V2, "repository_id": intake.REPOSITORY,
        # This is explicitly a fictional immutable Hub revision, not remote evidence.
        "revision": "a" * 40, "metadata_profile": intake.METADATA_PROFILE_V2,
        "expected_release_identity": {key: manifest[key] for key in (
            "release_profile", "release_point", "release_root_cid", "source_revision",
            "manifest_digest", "graph_ontology_version", "producer")},
        "expected_graph_population": {family: {
            "files": sum(item["family"] == family for item in descriptors),
            "rows": sum(item["row_count"] for item in descriptors if item["family"] == family),
        } for family in ("graph_nodes", "graph_edges")},
        "files": [{"path_in_repo": name, "bytes": len(body),
                   "sha256": hashlib.sha256(body).hexdigest()} for name, body in blobs.items()],
    }
    raw = canonical_json_bytes(request)
    return intake.prepare_source_package_intake_v2(raw, blobs,
        expected_request_sha256=hashlib.sha256(raw).hexdigest())


def test_wire_profile_producer_connects_actual_parquet_to_strict_intake_v2():
    import pyarrow as pa
    import pyarrow.parquet as pq
    release = _wire_profile_fixture(max_rows_per_shard=1)
    declaration = release.manifest_dict()["wire_metadata"]
    shards = [artifact for artifact in release.artifacts
              if artifact.relative_path.startswith("data/") and artifact.relative_path.endswith(".parquet")]
    tables = [pq.ParquetFile(pa.BufferReader(artifact.content)).read(use_threads=False) for artifact in shards]
    assert declaration["data_files"] == [{"split": "train", "path": [item.relative_path for item in shards]}]
    assert all(table.column_names == ["entry_cid", "legal_id", "family", "record_sha256", "record_json"]
               and all(pa.types.is_string(field.type) for field in table.schema) for table in tables)
    assert declaration["num_examples"] == sum(table.num_rows for table in tables)
    assert declaration["num_bytes"] == sum(table.nbytes for table in tables)
    assert declaration["num_bytes"] != sum(item.size_bytes for item in shards)
    assert declaration["unadvertised_configs"] == [LEGACY_CONFIG_NAME, RECOVERY_CONFIG_NAME]
    assert all(release.artifact(name).content for name in fixture_legacy_files())
    report = _wire_profile_intake(release)
    assert report["status"] == "selected_wire_metadata_reconciled"
    assert report["issues"] == [] and report["authority"]["accepted"] is False
    assert report["count_reconciliation"]["arrow_bytes_physically_measured_here"] is False
    assert validate_uscode_hf_release(release)["metadata_profile"] == declaration["profile"]


def test_wire_profile_is_explicit_and_legacy_defaults_are_unchanged():
    ordinary = _build_fixture_release()
    explicit = _build_fixture_release(metadata_profile=None)
    assert releases_are_byte_identical(ordinary, explicit)
    assert "wire_metadata" not in ordinary.manifest_dict()
    assert validate_uscode_hf_release(ordinary).get("metadata_profile") is None
    assert ordinary.build_config_cid != _wire_profile_fixture().build_config_cid


@pytest.mark.parametrize("profile", ["unknown/v1", "", False, 1])
def test_wire_profile_rejects_unsupported_explicit_profiles(profile):
    from ipfs_datasets_py.processors.legal_data.uscode_hf_release import UscodeHFReleaseError
    with pytest.raises(UscodeHFReleaseError, match="metadata profile"):
        _build_fixture_release(metadata_profile=profile)


def test_wire_profile_default_only_inventory_remains_exact():
    release = _wire_profile_fixture(include_legacy_config=False, include_recovery_config=False)
    assert release.manifest_dict()["wire_metadata"]["unadvertised_configs"] == []
    assert _wire_profile_intake(release)["issues"] == []


def _reseal_wire_profile_test_package(release, changes):
    """Rebuild legitimate outer commitments so tests reach producer profile checks."""
    from ipfs_datasets_py.processors.legal_data import uscode_hf_release as hf
    files = {item.relative_path: item for item in release.artifacts}
    for name, body in changes.items():
        files[name] = replace(files[name], content=body, sha256="", content_cid="")
    root = hf._compute_release_root_cid(dataset_id=release.dataset_id,
        artifacts=[item for name, item in files.items()
                   if name not in (MANIFEST_FILENAME, RELEASE_METADATA_FILENAME)],
        build_config_cid=release.build_config_cid)
    metadata = json.loads(files[RELEASE_METADATA_FILENAME].content)
    metadata["release_root_cid"] = root
    files[RELEASE_METADATA_FILENAME] = replace(files[RELEASE_METADATA_FILENAME],
        content=canonical_json_bytes(metadata) + b"\n", sha256="", content_cid="")
    manifest = json.loads(files[MANIFEST_FILENAME].content)
    manifest.update(release_root_cid=root, artifacts=[item.to_artifact_descriptor().to_dict()
        for name, item in sorted(files.items()) if name != MANIFEST_FILENAME])
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = digest_mapping(manifest)
    files[MANIFEST_FILENAME] = replace(files[MANIFEST_FILENAME],
        content=canonical_json_bytes(manifest) + b"\n", sha256="", content_cid="")
    return replace(release, release_root_cid=root, manifest_digest=manifest["manifest_digest"],
                   artifacts=tuple(files.values()))


@pytest.mark.parametrize("damage", ["profile", "alias", "paths", "rows", "arrow_bytes",
    "boolean_rows", "infos_extra", "infos_schema", "readme", "physical_schema", "physical_rows"])
def test_wire_profile_validation_rejects_resealed_drift(damage):
    import pyarrow as pa
    import pyarrow.parquet as pq
    release = _wire_profile_fixture()
    changes = {}
    if damage in ("profile", "alias", "paths", "rows", "arrow_bytes", "boolean_rows"):
        for name in (MANIFEST_FILENAME, RELEASE_METADATA_FILENAME, "dataset_configs.json"):
            body = json.loads(release.artifact(name).content)
            declaration = body["wire_metadata"]
            if damage == "profile": declaration["profile"] = "unknown/v1"
            elif damage == "alias": declaration["aliases"][DEFAULT_CONFIG_NAME] = "wrong-alias"
            elif damage == "paths": declaration["data_files"][0]["path"].append("recovery/fake.parquet")
            elif damage == "rows": declaration["num_examples"] += 1
            elif damage == "arrow_bytes": declaration["num_bytes"] += 1
            else: declaration["num_examples"] = True
            changes[name] = canonical_json_bytes(body) + b"\n"
    elif damage.startswith("infos_"):
        body = json.loads(release.artifact(DATASET_INFOS_FILENAME).content)
        info = body["publicus-ir-graphrag-v2"]
        if damage == "infos_extra": info["dataset_name"] = release.dataset_id
        else: info["features"]["entry_cid"]["dtype"] = "int64"
        changes[DATASET_INFOS_FILENAME] = canonical_json_bytes(body) + b"\n"
    elif damage == "readme":
        changes[README_FILENAME] = release.artifact(README_FILENAME).content.replace(
            b"    dtype: string", b"    dtype: int64", 1)
    else:
        shard = next(item for item in release.artifacts if item.family == "corpus")
        table = pq.ParquetFile(pa.BufferReader(shard.content)).read(use_threads=False)
        if damage == "physical_schema":
            table = table.set_column(0, "entry_cid", pa.array([1] * table.num_rows, type=pa.int64()))
        else: table = table.slice(0, 0)
        sink = pa.BufferOutputStream(); pq.write_table(table, sink)
        changes[shard.relative_path] = sink.getvalue().to_pybytes()
    bad = _reseal_wire_profile_test_package(release, changes)
    with pytest.raises(UscodeHFReleaseIntegrityError, match="wire"):
        validate_uscode_hf_release(bad)


def test_wire_profile_legacy_package_is_refused_by_strict_intake_v2():
    with pytest.raises(ValueError, match="explicit HF wire declaration"):
        _wire_profile_intake(_build_fixture_release())

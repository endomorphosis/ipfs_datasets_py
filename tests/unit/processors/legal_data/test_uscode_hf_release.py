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


# ---------------------------------------------------------------------------
# Explicit homogeneous Hugging Face wire metadata; logical release IDs persist.
# ---------------------------------------------------------------------------

_HF_WIRE_COLUMNS = (
    "entry_cid", "legal_id", "family", "record_sha256", "record_json",
)


def _wire_subject():
    from ipfs_datasets_py.processors.legal_data import uscode_hf_release

    return uscode_hf_release


def _wire_release(**kwargs):
    subject = _wire_subject()
    return _build_fixture_release(
        wire_metadata_profile=subject.HF_WIRE_PROFILE, **kwargs,
    )


def _wire_json(release, path):
    return json.loads(release.artifact(path).content.decode("utf-8"))


def _wire_selected_artifacts(release):
    return tuple(
        artifact for artifact in release.artifacts
        if artifact.relative_path.startswith("data/")
        and artifact.relative_path.endswith(".parquet")
    )


def _wire_measured_arrow_bytes(release):
    import io

    import pyarrow.parquet as pq

    return sum(
        pq.read_table(io.BytesIO(artifact.content)).nbytes
        for artifact in _wire_selected_artifacts(release)
    )


def _wire_wrong_yaml_num_examples(card, expected_rows):
    import re

    parts = card.split("---", 2)
    assert len(parts) == 3
    pattern = r"(?m)^([ \t]*num_examples:[ \t]*)" + str(expected_rows) + r"([ \t]*)$"
    header, replacements = re.subn(
        pattern, lambda match: match[1] + str(expected_rows + 1) + match[2], parts[1],
    )
    assert replacements == 1, "The consumed named dataset_info split count must occur once"
    parts[1] = header
    return "---".join(parts)


def test_wire_profile_none_preserves_exact_legacy_release_bytes() -> None:
    omitted = _build_fixture_release()
    explicit_none = _build_fixture_release(wire_metadata_profile=None)
    assert releases_are_byte_identical(omitted, explicit_none)
    for name in (MANIFEST_FILENAME, "dataset_configs.json", RELEASE_METADATA_FILENAME):
        assert "wire_metadata" not in _wire_json(omitted, name)
    assert "configs" in _wire_json(omitted, "dataset_infos.json")
    frontmatter = omitted.dataset_card_text().split("---", 2)[1]
    assert 'config_name: "publicus-ir-graphrag/v2"' in frontmatter


def test_wire_profile_preserves_logical_configs_release_profile_and_data_bytes() -> None:
    subject = _wire_subject()
    old = _build_fixture_release()
    wire = _wire_release()
    assert subject.HF_WIRE_PROFILE == "hf-default-parquet-envelope/v1"
    assert subject.HF_DEFAULT_CONFIG_NAME == "publicus-ir-graphrag-v2"
    assert wire.release_profile == old.release_profile == "publicus-ir-graphrag/v2"
    assert [cfg.to_dict() for cfg in wire.configs] == [cfg.to_dict() for cfg in old.configs]
    assert wire.manifest_dict()["default_config"] == old.manifest_dict()["default_config"] == DEFAULT_CONFIG_NAME
    old_data = {artifact.relative_path: artifact for artifact in old.data_artifacts}
    new_data = {artifact.relative_path: artifact for artifact in wire.data_artifacts}
    assert set(new_data) == set(old_data)
    for name, artifact in new_data.items():
        assert artifact.content == old_data[name].content
        assert artifact.config_name == old_data[name].config_name
        assert artifact.row_count == old_data[name].row_count


def test_wire_metadata_agrees_across_three_documents_and_exact_train_inventory() -> None:
    subject = _wire_subject()
    release = _wire_release()
    documents = [
        _wire_json(release, name)
        for name in (MANIFEST_FILENAME, "dataset_configs.json", RELEASE_METADATA_FILENAME)
    ]
    declaration = documents[0]["wire_metadata"]
    assert documents[1]["wire_metadata"] == documents[2]["wire_metadata"] == declaration
    assert declaration["profile"] == subject.HF_WIRE_PROFILE
    assert declaration["default_config"] == subject.HF_DEFAULT_CONFIG_NAME
    assert declaration["logical_default_config"] == DEFAULT_CONFIG_NAME
    assert declaration["aliases"] == {DEFAULT_CONFIG_NAME: subject.HF_DEFAULT_CONFIG_NAME}
    paths = sorted(artifact.relative_path for artifact in _wire_selected_artifacts(release))
    assert paths and declaration["data_files"] == [{"split": "train", "path": paths}]
    assert declaration["num_examples"] == sum(
        artifact.row_count for artifact in _wire_selected_artifacts(release)
    )
    assert declaration["num_bytes"] == _wire_measured_arrow_bytes(release)
    assert set(declaration["unadvertised_configs"]) == {LEGACY_CONFIG_NAME, RECOVERY_CONFIG_NAME}
    assert any(artifact.relative_path.startswith("indexes/") for artifact in release.artifacts)
    assert any(artifact.relative_path.startswith("recovery/") for artifact in release.artifacts)
    assert any(artifact.relative_path.startswith("uscode_parquet/") for artifact in release.artifacts)
    assert all(not path.startswith(("indexes/", "recovery/", "uscode_parquet/")) for path in paths)


def test_wire_card_exposes_one_safe_alias_and_explicit_default() -> None:
    import yaml

    subject = _wire_subject()
    release = _wire_release()
    metadata = yaml.safe_load(release.dataset_card_text().split("---", 2)[1])
    paths = sorted(artifact.relative_path for artifact in _wire_selected_artifacts(release))
    assert metadata["configs"] == [{
        "config_name": subject.HF_DEFAULT_CONFIG_NAME,
        "default": True,
        "data_files": [{"split": "train", "path": paths}],
    }]
    expected_rows = sum(artifact.row_count for artifact in _wire_selected_artifacts(release))
    assert metadata["dataset_info"] == [{
        "config_name": subject.HF_DEFAULT_CONFIG_NAME,
        "features": [{"name": name, "dtype": "string"} for name in _HF_WIRE_COLUMNS],
        "splits": [{
            "name": "train", "num_examples": expected_rows,
            "num_bytes": _wire_measured_arrow_bytes(release),
        }],
    }]
    assert "/" not in metadata["configs"][0]["config_name"]
    assert all(cfg["config_name"] != LEGACY_CONFIG_NAME for cfg in metadata["configs"])
    assert all(cfg["config_name"] != RECOVERY_CONFIG_NAME for cfg in metadata["configs"])


def test_wire_infos_are_hf_root_mapping_with_exact_rows_and_measured_arrow_bytes() -> None:
    subject = _wire_subject()
    release = _wire_release()
    infos = _wire_json(release, "dataset_infos.json")
    assert set(infos) == {subject.HF_DEFAULT_CONFIG_NAME}
    info = infos[subject.HF_DEFAULT_CONFIG_NAME]
    expected_features = {name: {"dtype": "string", "_type": "Value"} for name in _HF_WIRE_COLUMNS}
    assert info["config_name"] == subject.HF_DEFAULT_CONFIG_NAME
    assert info["features"] == expected_features
    expected_rows = sum(artifact.row_count for artifact in _wire_selected_artifacts(release))
    expected_bytes = _wire_measured_arrow_bytes(release)
    assert expected_bytes > 0
    assert info["splits"] == {"train": {
        "name": "train", "num_examples": expected_rows, "num_bytes": expected_bytes,
    }}
    assert expected_rows == sum(
        len(rows) for family, rows in fixture_family_rows().items() if family != "recovery"
    )
    # Routing-index rows belong to the logical config, but not this wire table.
    all_logical_rows = sum(
        artifact.row_count for artifact in release.data_artifacts
        if artifact.config_name == DEFAULT_CONFIG_NAME
    )
    assert all_logical_rows > expected_rows
    assert not {"num_bytes", "dataset_size", "size_in_bytes", "download_size"} & set(info)
    assert expected_bytes != sum(
        artifact.size_bytes for artifact in _wire_selected_artifacts(release)
    ), "Fixture Arrow bytes must remain distinct from compressed Parquet bytes"


def test_wire_profile_validates_without_reclassifying_opaque_legacy_bytes() -> None:
    release = _wire_release()
    receipt = validate_uscode_hf_release(release)
    assert receipt["valid"] is True
    for path, original in fixture_legacy_files().items():
        assert release.artifact(path).content == original
        assert not original.startswith(b"PAR1")


@pytest.mark.parametrize("profile", [False, {}, [], "", "hf-default-parquet-envelope/v999"])
def test_unknown_wire_profile_refuses_before_packaging(profile) -> None:
    with pytest.raises(UscodeHFReleaseConfigError):
        _build_fixture_release(wire_metadata_profile=profile)


@pytest.mark.parametrize("damage", ["schema", "row_count"])
def test_wire_profile_rejects_self_consistent_descriptors_with_bad_physical_parquet(
    damage, monkeypatch,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    subject = _wire_subject()
    original_encoder = subject._encode_parquet_rows

    def damaged_encoder(rows, *, family):
        if family != "corpus":
            return original_encoder(rows, family=family)
        count = len(rows) + int(damage == "row_count")
        columns = {name: pa.array(["fixture"] * count, type=pa.string()) for name in _HF_WIRE_COLUMNS}
        if damage == "schema":
            columns["entry_cid"] = pa.array(list(range(count)), type=pa.int64())
        sink = pa.BufferOutputStream()
        pq.write_table(pa.table(columns), sink, compression="zstd")
        return sink.getvalue().to_pybytes()

    monkeypatch.setattr(subject, "_encode_parquet_rows", damaged_encoder)
    # The public builder will bind these real bytes to fresh descriptors. The
    # refusal must come from the wire physical-schema/count boundary, rather
    # than from a stale checksum on an after-the-fact modified artifact.
    with pytest.raises(subject.UscodeHFReleaseError, match="(?i)schema|row|parquet"):
        _wire_release()


def _require_hf_wire_loader_qualification():
    import os

    if os.environ.get("LEGAL_IR_HF_WIRE_LOADER_QUALIFICATION") != "1":
        pytest.skip("Real Hugging Face loader is enrolled only by the owned wire qualification")
    import datasets

    assert datasets.__version__ == "5.1.0", "Owned wire-loader qualification requires datasets5.1.0"
    return datasets


def _stage_hf_wire_loader_fixture(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    release = _wire_release()
    stage = tmp_path / "wire-dataset"
    stage_uscode_hf_release(release, stage, dry_run=False)
    selected = _wire_selected_artifacts(release)
    expected = []
    for artifact in sorted(selected, key=lambda item: item.relative_path):
        expected.extend(pq.read_table(stage / artifact.relative_path).to_pylist())
    # A same-schema shard even under data/ must remain excluded unless it was
    # explicitly advertised. Broad-glob regression would include this sentinel.
    extra = stage / "data" / "corpus" / "unlisted-extra.parquet"
    columns = {name: pa.array(["unlisted-sentinel"], type=pa.string()) for name in _HF_WIRE_COLUMNS}
    pq.write_table(pa.table(columns), extra)
    assert all("unlisted-sentinel" not in row.values() for row in expected)
    assert any(artifact.relative_path.startswith("indexes/") for artifact in release.artifacts)
    assert any(artifact.relative_path.startswith("recovery/") for artifact in release.artifacts)
    assert any(artifact.relative_path.startswith("uscode_parquet/") for artifact in release.artifacts)
    return release, stage, expected


def test_wire_infos_parse_with_actual_hf_dataset_infos_dict(tmp_path) -> None:
    _require_hf_wire_loader_qualification()
    from datasets.info import DatasetInfosDict

    subject = _wire_subject()
    release, stage, expected = _stage_hf_wire_loader_fixture(tmp_path)
    infos = DatasetInfosDict.from_directory(str(stage))
    assert set(infos) == {subject.HF_DEFAULT_CONFIG_NAME}
    info = infos[subject.HF_DEFAULT_CONFIG_NAME]
    assert info.config_name == subject.HF_DEFAULT_CONFIG_NAME
    assert info.splits["train"].num_examples == len(expected)
    assert info.splits["train"].num_bytes == _wire_measured_arrow_bytes(release)
    assert set(info.features) == set(_HF_WIRE_COLUMNS)
    assert all(feature.dtype == "string" for feature in info.features.values())
    assert release.manifest_dict()["default_config"] == DEFAULT_CONFIG_NAME


@pytest.mark.parametrize("explicit_alias", [False, True], ids=["default", "explicit_alias"])
@pytest.mark.parametrize("streaming", [False, True], ids=["materialized", "streaming"])
def test_wire_real_loader_uses_advertised_default_files_without_override(
    explicit_alias, streaming, tmp_path,
) -> None:
    datasets = _require_hf_wire_loader_qualification()
    subject = _wire_subject()
    release, stage, expected = _stage_hf_wire_loader_fixture(tmp_path)
    options = {"name": subject.HF_DEFAULT_CONFIG_NAME} if explicit_alias else {}
    loaded = datasets.load_dataset(
        str(stage), split="train", streaming=streaming,
        cache_dir=str(tmp_path / "fresh-loader-cache"), **options,
    )
    actual = list(loaded) if streaming else loaded.to_list()
    assert actual == expected
    assert len(actual) == _wire_json(release, "dataset_infos.json")[subject.HF_DEFAULT_CONFIG_NAME]["splits"]["train"]["num_examples"]
    assert set(loaded.features) == set(_HF_WIRE_COLUMNS)
    assert all(feature.dtype == "string" for feature in loaded.features.values())
    assert loaded.info.config_name == subject.HF_DEFAULT_CONFIG_NAME
    assert loaded.info.splits["train"].num_examples == len(expected)
    assert loaded.info.splits["train"].num_bytes == _wire_measured_arrow_bytes(release)
    assert all("unlisted-sentinel" not in row.values() for row in actual)


def test_wire_real_loader_rejects_wrong_declared_rows_with_fresh_cache(tmp_path) -> None:
    datasets = _require_hf_wire_loader_qualification()
    from datasets.exceptions import NonMatchingSplitsSizesError

    subject = _wire_subject()
    _, stage, expected = _stage_hf_wire_loader_fixture(tmp_path)
    card = stage / README_FILENAME
    card.write_text(
        _wire_wrong_yaml_num_examples(card.read_text(encoding="utf-8"), len(expected)),
        encoding="utf-8",
    )
    path = stage / "dataset_infos.json"
    infos = json.loads(path.read_text(encoding="utf-8"))
    infos[subject.HF_DEFAULT_CONFIG_NAME]["splits"]["train"]["num_examples"] = len(expected) + 1
    path.write_text(json.dumps(infos, sort_keys=True), encoding="utf-8")
    # datasets5.1 renames a sole legacy JSON-info key to "default". The named
    # YAML dataset_info above is the actually consumed alias-bound count; the
    # JSON sidecar agrees rather than supplying a separate conflicting count.
    # No explicit data_files or no_checks bypass is used, and the cache is fresh.
    with pytest.raises(NonMatchingSplitsSizesError):
        datasets.load_dataset(
            str(stage), split="train", cache_dir=str(tmp_path / "wrong-count-fresh-cache"),
        )


def test_legacy_default_matches_the_retained_original_owner_generation() -> None:
    _require_hf_wire_loader_qualification()
    import hashlib
    import importlib.util
    import os
    import sys

    spelling = os.environ.get("LEGAL_IR_HF_WIRE_LEGACY_BASELINE")
    expected = os.environ.get("LEGAL_IR_HF_WIRE_LEGACY_SHA256")
    assert spelling and expected, "Owned qualification must pin its original source baseline"
    assert expected == "c183915f939892efff604fcd426df383b5393c3f4ca5a59d13216566d4c4805c"
    baseline_path = Path(spelling)
    assert baseline_path.is_absolute() and baseline_path.resolve(strict=True) == baseline_path
    before = baseline_path.read_bytes()
    assert len(before) == 88604 and hashlib.sha256(before).hexdigest() == expected
    name = "_uscode_hf_release_wire_qualification_legacy_baseline"
    assert name not in sys.modules
    spec = importlib.util.spec_from_file_location(name, baseline_path)
    assert spec is not None and spec.loader is not None
    baseline = importlib.util.module_from_spec(spec)
    # Dataclass construction resolves the defining module through sys.modules.
    # This is an enrolled test-only source baseline, never a product fallback.
    sys.modules[name] = baseline
    try:
        spec.loader.exec_module(baseline)
        old = baseline.build_uscode_hf_release(
            baseline.fixture_family_rows(),
            legacy_files=baseline.fixture_legacy_files(), dry_run=True,
        )
        for current in (
            _build_fixture_release(),
            _build_fixture_release(wire_metadata_profile=None),
        ):
            old_artifacts = {artifact.relative_path: artifact for artifact in old.artifacts}
            current_artifacts = {artifact.relative_path: artifact for artifact in current.artifacts}
            assert set(current_artifacts) == set(old_artifacts)
            for path, artifact in current_artifacts.items():
                assert artifact.content == old_artifacts[path].content, path
                assert artifact.descriptor_dict() == old_artifacts[path].descriptor_dict(), path
            for field in (
                "release_root_cid", "manifest_digest", "build_config_cid", "vector_space_id",
                "release_profile", "schema_version", "source_revision", "release_point",
                "package_version", "dataset_id",
            ):
                assert getattr(current, field) == getattr(old, field), field
            assert [cfg.to_dict() for cfg in current.configs] == [cfg.to_dict() for cfg in old.configs]
        assert baseline_path.read_bytes() == before
    finally:
        assert sys.modules.pop(name) is baseline


def _wire_resealed_control_mutation(
    release, relative_path, mutate, *, drop_companion_markers=False,
):
    """Build fresh artifact identities around an intentionally invalid wire view.

    The fixture changes control-plane meaning, then mechanically rebinds every
    changed byte to the existing descriptor/root/digest rules. A semantic wire
    refusal therefore cannot be explained by an obsolete artifact checksum.
    """
    from dataclasses import replace

    subject = _wire_subject()

    def rebound(artifact, content):
        return subject.ReleaseArtifact(
            relative_path=artifact.relative_path, content=content,
            media_type=artifact.media_type, family=artifact.family,
            row_count=artifact.row_count, config_name=artifact.config_name,
            schema_id=artifact.schema_id, first_key=artifact.first_key,
            last_key=artifact.last_key,
        )

    artifacts = {artifact.relative_path: artifact for artifact in release.artifacts}
    original = artifacts[relative_path]
    if relative_path == README_FILENAME:
        changed = mutate(original.content.decode("utf-8")).encode("utf-8")
    else:
        body = json.loads(original.content.decode("utf-8"))
        mutate(body)
        changed = subject.canonical_json_bytes(body) + b"\n"
    assert changed != original.content
    artifacts[relative_path] = rebound(original, changed)

    if drop_companion_markers:
        assert relative_path == MANIFEST_FILENAME
        for companion in ("dataset_configs.json", RELEASE_METADATA_FILENAME):
            body = json.loads(artifacts[companion].content.decode("utf-8"))
            assert "wire_metadata" in body
            body.pop("wire_metadata")
            artifacts[companion] = rebound(
                artifacts[companion], subject.canonical_json_bytes(body) + b"\n",
            )

    # The existing root recipe excludes manifest and release_metadata to avoid
    # circular identities. Keep that same recipe and update the metadata link.
    pre_manifest = [
        artifact for path, artifact in artifacts.items()
        if path not in {MANIFEST_FILENAME, RELEASE_METADATA_FILENAME}
    ]
    release_root = subject._compute_release_root_cid(
        dataset_id=release.dataset_id, artifacts=pre_manifest,
        build_config_cid=release.build_config_cid,
    )
    metadata = json.loads(artifacts[RELEASE_METADATA_FILENAME].content.decode("utf-8"))
    metadata["release_root_cid"] = release_root
    artifacts[RELEASE_METADATA_FILENAME] = rebound(
        artifacts[RELEASE_METADATA_FILENAME], subject.canonical_json_bytes(metadata) + b"\n",
    )
    manifest = json.loads(artifacts[MANIFEST_FILENAME].content.decode("utf-8"))
    manifest["release_root_cid"] = release_root
    manifest["artifacts"] = [
        artifacts[descriptor["relative_path"]].to_artifact_descriptor().to_dict()
        for descriptor in manifest["artifacts"]
    ]
    manifest.pop("manifest_digest")
    manifest_digest = subject.digest_mapping(manifest)
    manifest["manifest_digest"] = manifest_digest
    artifacts[MANIFEST_FILENAME] = rebound(
        artifacts[MANIFEST_FILENAME], subject.canonical_json_bytes(manifest) + b"\n",
    )
    altered = replace(
        release, artifacts=tuple(artifacts.values()),
        release_root_cid=release_root, manifest_digest=manifest_digest,
    )

    # Check the mechanical seals before invoking the public semantic validator.
    sealed = altered.manifest_dict()
    digest_body = dict(sealed)
    assert digest_body.pop("manifest_digest") == altered.manifest_digest
    assert subject.digest_mapping(digest_body) == altered.manifest_digest
    assert sealed["release_root_cid"] == altered.release_root_cid
    for descriptor in sealed["artifacts"]:
        artifact = altered.artifact(descriptor["relative_path"])
        assert descriptor == artifact.to_artifact_descriptor().to_dict()
    changed_artifact = altered.artifact(relative_path)
    assert changed_artifact.sha256 != original.sha256
    assert changed_artifact.content_cid != original.content_cid
    return altered


@pytest.mark.parametrize(
    "damage",
    ["card_default", "infos_feature", "infos_population", "cross_metadata_profile",
     "card_population", "infos_bytes", "card_other_dataset_info_key", "card_other_configs_key"],
)
def test_wire_public_validator_rejects_resealed_semantic_corruption(damage) -> None:
    subject = _wire_subject()
    release = _wire_release()
    original_bytes = {artifact.relative_path: artifact.content for artifact in release.artifacts}
    alias = subject.HF_DEFAULT_CONFIG_NAME

    if damage == "card_default":
        def mutate(text):
            assert text.count("  default: true") == 1
            return text.replace("  default: true", "  default: false", 1)

        altered = _wire_resealed_control_mutation(release, README_FILENAME, mutate)
        error, message = subject.UscodeHFReleaseConfigError, "wire card"
    elif damage == "infos_feature":
        def mutate(body):
            body[alias]["features"]["entry_cid"]["dtype"] = "int64"

        altered = _wire_resealed_control_mutation(release, "dataset_infos.json", mutate)
        error, message = subject.UscodeHFReleaseIntegrityError, "wire DatasetInfosDict"
    elif damage == "infos_population":
        def mutate(body):
            body[alias]["splits"]["train"]["num_examples"] += 1

        altered = _wire_resealed_control_mutation(release, "dataset_infos.json", mutate)
        error, message = subject.UscodeHFReleaseIntegrityError, "wire DatasetInfosDict"
    elif damage == "card_population":
        expected_rows = _wire_json(release, "dataset_infos.json")[alias]["splits"]["train"]["num_examples"]

        def mutate(text):
            return _wire_wrong_yaml_num_examples(text, expected_rows)

        altered = _wire_resealed_control_mutation(release, README_FILENAME, mutate)
        error, message = subject.UscodeHFReleaseConfigError, "wire card"
    elif damage == "infos_bytes":
        def mutate(body):
            body[alias]["splits"]["train"]["num_bytes"] += 1

        altered = _wire_resealed_control_mutation(release, "dataset_infos.json", mutate)
        error, message = subject.UscodeHFReleaseIntegrityError, "wire DatasetInfosDict"
    elif damage in {"card_other_dataset_info_key", "card_other_configs_key"}:
        key = "dataset_info" if damage == "card_other_dataset_info_key" else "configs"

        def mutate(text):
            marker = "\n" + key + ":\n"
            assert text.count(marker) == 1
            return text.replace(marker, "\nother_" + key + ":\n", 1)

        altered = _wire_resealed_control_mutation(release, README_FILENAME, mutate)
        header = altered.dataset_card_text().split("---", 2)[1]
        assert "\n" + key + ":\n" not in header
        assert "\nother_" + key + ":\n" in header
        error, message = subject.UscodeHFReleaseConfigError, "wire card"
    else:
        assert damage == "cross_metadata_profile"

        def mutate(body):
            body["wire_metadata"]["profile"] = "hf-default-parquet-envelope/v999"

        altered = _wire_resealed_control_mutation(release, "dataset_configs.json", mutate)
        error, message = subject.UscodeHFReleaseIntegrityError, "wire metadata declarations disagree"

    with pytest.raises(error, match=message):
        validate_uscode_hf_release(altered)
    assert {artifact.relative_path: artifact.content for artifact in release.artifacts} == original_bytes


@pytest.mark.parametrize("drop_all_markers", [False, True], ids=["manifest_only", "all_three"])
def test_wire_public_validator_refuses_resealed_marker_drop_downgrade(drop_all_markers) -> None:
    subject = _wire_subject()
    release = _wire_release()

    def mutate(body):
        assert "wire_metadata" in body
        body.pop("wire_metadata")

    altered = _wire_resealed_control_mutation(
        release, MANIFEST_FILENAME, mutate,
        drop_companion_markers=drop_all_markers,
    )
    assert "wire_metadata" not in altered.manifest_dict()
    for path in ("dataset_configs.json", RELEASE_METADATA_FILENAME):
        body = _wire_json(altered, path)
        assert ("wire_metadata" not in body) is drop_all_markers
    infos = _wire_json(altered, "dataset_infos.json")
    assert set(infos) == {subject.HF_DEFAULT_CONFIG_NAME}
    assert "configs" not in infos
    assert subject.HF_DEFAULT_CONFIG_NAME in altered.dataset_card_text().split("---", 2)[1]
    # Each artifact/root/digest was freshly rebound by the helper. The wire
    # card and infos must still select strict wire validation when its explicit
    # declaration has been removed, rather than silently becoming legacy data.
    with pytest.raises(subject.UscodeHFReleaseConfigError, match="wire metadata declaration"):
        validate_uscode_hf_release(altered)

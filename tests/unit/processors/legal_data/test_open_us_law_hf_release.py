"""Unit tests for descriptor-complete Open US Law HF release packaging (OUL-032)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_hf_release import (
    CONTROL_PLANE_PATHS,
    DEFAULT_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    MANIFEST_FILENAME,
    QUARANTINE_CONFIG_NAME,
    README_FILENAME,
    RECOVERY_CONFIG_NAME,
    RELEASE_METADATA_FILENAME,
    REQUIRED_MANIFEST_BINDINGS,
    SCHEMA_VERSION,
    TASK_ID,
    OpenUsLawHFReleaseConfigError,
    OpenUsLawHFReleaseSafetyError,
    OpenUsLawHuggingFaceRelease,
    ReleaseArtifact,
    advertised_viewer_configs,
    assemble_open_us_law_hf_release,
    assert_configs_schema_coherent,
    build_open_us_law_hf_release,
    fixture_family_rows,
    load_fixture_dataset_card,
    releases_are_byte_identical,
    render_dataset_card,
    route_bounds_policy,
    rows_from_bm25_index,
    rows_from_graph_projection,
    rows_from_two_way_adjacency,
    rows_from_vector_binding,
    stage_open_us_law_hf_release,
    validate_open_us_law_hf_release,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    DEFAULT_MODEL_TOKEN_CEILING,
    EXPECTED_JURISDICTION_COUNT,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    NON_DEFAULT_CONFIGURATION_NAMES,
    RELEASE_PROFILE,
    example_federal_payload,
)


FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir"
CARD_FIXTURE = FIXTURE_DIR / "open_us_law_dataset_card.md"


def _build_fixture_release(**kwargs):
    return build_open_us_law_hf_release(
        fixture_family_rows(),
        dry_run=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Fixtures on disk
# ---------------------------------------------------------------------------


def test_sealed_dataset_card_fixture_documents_configs() -> None:
    assert CARD_FIXTURE.is_file()
    card = load_fixture_dataset_card(CARD_FIXTURE)
    assert card.startswith("---\n")
    assert "configs:" in card
    assert DEFAULT_CONFIG_NAME in card
    assert RECOVERY_CONFIG_NAME in card
    assert QUARANTINE_CONFIG_NAME in card
    for name in NON_DEFAULT_CONFIGURATION_NAMES:
        assert name in card
    assert "recovery" in card.lower()
    assert "exact-51" in card.lower() or "exact 51" in card.lower()
    assert "lineage" in card.lower()
    front = card.split("---", 2)[1]
    assert 'path: "data/**/*.parquet"' in front
    assert f'config_name: "{DEFAULT_CONFIG_NAME}"' in front
    assert f'config_name: "{RECOVERY_CONFIG_NAME}"' in front
    assert DEFAULT_EMBEDDING_MODEL_ID in card
    assert DEFAULT_EMBEDDING_MODEL_REVISION in card
    assert "thenlper/gte-small" in card
    assert "vector locator" in card.lower() or "locator" in card.lower()


def test_rendered_card_matches_sealed_fixture() -> None:
    sealed = load_fixture_dataset_card(CARD_FIXTURE).strip()
    rendered = render_dataset_card().strip()
    assert sealed == rendered


# ---------------------------------------------------------------------------
# Viewer configs
# ---------------------------------------------------------------------------


def test_advertised_configs_schema_coherent() -> None:
    configs = advertised_viewer_configs()
    receipt = assert_configs_schema_coherent(configs)
    assert receipt["schema_coherent"] is True
    assert receipt["default_excludes_recovery"] is True
    assert receipt["viewer_safe_default_exact_51"] is True
    defaults = [c for c in configs if c.is_default]
    assert len(defaults) == 1
    assert defaults[0].config_name == DEFAULT_CONFIG_NAME
    assert defaults[0].satisfies_exact_51_gate is True
    for entry in defaults[0].data_files:
        assert "recovery" not in entry["path"]
        assert "quarantine" not in entry["path"]
        assert not entry["path"].startswith("configs/")
    names = {cfg.config_name for cfg in configs}
    assert DEFAULT_CONFIG_NAME in names
    assert RECOVERY_CONFIG_NAME in names
    assert QUARANTINE_CONFIG_NAME in names
    for name in NON_DEFAULT_CONFIGURATION_NAMES:
        assert name in names


def test_default_config_cannot_advertise_recovery_path() -> None:
    configs = list(advertised_viewer_configs(include_recovery=False, include_quarantine=False))
    bad = configs[0].to_dict()
    bad["data_files"] = [{"split": "train", "path": "recovery/**/*.json"}]
    with pytest.raises(OpenUsLawHFReleaseSafetyError):
        assert_configs_schema_coherent([bad, *configs[1:]])


def test_two_defaults_rejected() -> None:
    configs = advertised_viewer_configs(
        include_non_default=False,
        include_recovery=False,
        include_quarantine=False,
    )
    twin = configs[0].to_dict()
    twin["config_name"] = "state_statutes_exact_51-dup"
    with pytest.raises(OpenUsLawHFReleaseConfigError):
        assert_configs_schema_coherent([configs[0], twin])


def test_non_default_cannot_satisfy_exact_51_gate() -> None:
    configs = advertised_viewer_configs()
    recovery = next(c for c in configs if c.is_recovery).to_dict()
    recovery["satisfies_exact_51_gate"] = True
    with pytest.raises(OpenUsLawHFReleaseConfigError):
        assert_configs_schema_coherent(
            [c for c in configs if not c.is_recovery] + [recovery]
        )


# ---------------------------------------------------------------------------
# Live release build
# ---------------------------------------------------------------------------


def test_build_is_byte_identical_across_runs() -> None:
    first = _build_fixture_release()
    second = _build_fixture_release()
    assert releases_are_byte_identical(first, second)
    assert first.manifest_digest == second.manifest_digest
    assert first.release_root_cid == second.release_root_cid


def test_validate_acceptance_contract() -> None:
    release = _build_fixture_release()
    receipt = validate_open_us_law_hf_release(release)
    assert receipt["valid"] is True
    acc = receipt["acceptance"]
    assert acc["default_config_excludes_recovery"] is True
    assert acc["all_advertised_configs_schema_coherent"] is True
    assert acc["every_artifact_descriptor_bound"] is True
    assert acc["verbose_lineage_separate_from_control_plane"] is True
    assert acc["viewer_safe_default_exact_51"] is True
    assert receipt["default_config"] == DEFAULT_CONFIG_NAME
    assert receipt["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION


def test_default_config_excludes_recovery_and_quarantine() -> None:
    release = _build_fixture_release()
    default = next(c for c in release.configs if c.is_default)
    assert default.config_name == DEFAULT_CONFIG_NAME
    for entry in default.data_files:
        assert "recovery" not in entry["path"]
        assert "quarantine" not in entry["path"]
    for art in release.artifacts:
        if art.relative_path.startswith("recovery/"):
            assert art.config_name == RECOVERY_CONFIG_NAME
            assert art.family == "recovery"
            assert art.media_type.startswith("application/json")
        if art.relative_path.startswith("quarantine/"):
            assert art.config_name == QUARANTINE_CONFIG_NAME
            assert art.family == "quarantine"
        if art.config_name == DEFAULT_CONFIG_NAME:
            assert art.family not in {"recovery", "quarantine"}
    manifest = release.manifest_dict()
    assert manifest["default_excludes_recovery"] is True
    assert manifest["viewer_safe_default_exact_51"] is True


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
            and any(isinstance(row, dict) and "source_cid" in row for row in plane["rows"])
        )


def test_manifest_binds_every_required_family() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    for name in REQUIRED_MANIFEST_BINDINGS:
        assert name in manifest, name
    for family in (
        "corpus",
        "bm25",
        "vectors",
        "centroids",
        "vector_locator",
        "graph",
        "two_way_adjacency",
        "recovery",
        "source_receipts",
    ):
        binding = manifest[family]
        assert binding["artifact_count"] >= 1
        assert binding["row_count"] >= 1
        assert binding["size_bytes"] >= 1
        assert binding["sha256"]
        for digest in binding["sha256"]:
            assert len(digest) == 64
    assert manifest["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert manifest["model_id"] == DEFAULT_EMBEDDING_MODEL_ID
    assert isinstance(manifest["configs"], list) and manifest["configs"]
    assert isinstance(manifest["row_counts"], dict) and manifest["row_counts"]
    assert isinstance(manifest["sizes"], dict) and manifest["sizes"]
    assert isinstance(manifest["sha256_digests"], dict) and manifest["sha256_digests"]
    bounds = manifest["route_bounds"]
    assert bounds["max_rows_per_physical_shard"] == MAX_ROWS_PER_PHYSICAL_SHARD
    assert bounds["max_posting_pointers_per_row"] == MAX_POSTING_POINTERS_PER_ROW
    assert bounds["max_adjacency_pointers_per_row"] == MAX_ADJACENCY_POINTERS_PER_ROW
    assert bounds["max_rows_per_vector_centroid"] == MAX_ROWS_PER_VECTOR_CENTROID
    assert bounds["max_vector_shards_per_centroid"] == MAX_VECTOR_SHARDS_PER_CENTROID
    assert bounds["model_token_ceiling"] == DEFAULT_MODEL_TOKEN_CEILING
    assert manifest["viewer_safe_default_exact_51"] is True
    assert manifest["default_config"] == DEFAULT_CONFIG_NAME
    assert manifest["task_id"] == TASK_ID
    assert manifest["release_profile"] == RELEASE_PROFILE
    assert manifest["jurisdictions"]["required_count"] == EXPECTED_JURISDICTION_COUNT


def test_route_bounds_policy_matches_schema() -> None:
    bounds = route_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_posting_pointers_per_row"] == 4096
    assert bounds["max_adjacency_pointers_per_row"] == 4096


def test_dataset_card_matches_advertised_configs() -> None:
    release = _build_fixture_release()
    card = release.dataset_card_text()
    assert card.startswith("---\n")
    for cfg in release.configs:
        assert cfg.config_name in card
    rendered = render_dataset_card(configs=release.configs)
    assert DEFAULT_CONFIG_NAME in rendered
    assert "reports/lineage.json" in rendered
    assert DEFAULT_EMBEDDING_MODEL_REVISION in rendered


def test_manifest_and_metadata_are_control_plane() -> None:
    release = _build_fixture_release()
    manifest = release.manifest_dict()
    metadata = release.release_metadata_dict()
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["release_profile"] == RELEASE_PROFILE
    assert manifest["additive_packaging"] is True
    assert metadata["uses_hf_api_upload_file"] is False
    assert metadata["upload_path"] is None
    assert metadata["lineage_is_control_plane"] is False
    assert metadata["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert metadata["viewer_safe_default_exact_51"] is True
    assert release.schema_version == SCHEMA_VERSION
    assert release.dataset_id == DEFAULT_DATASET_REPO_ID


def test_stage_dry_run_does_not_write(tmp_path: Path) -> None:
    release = _build_fixture_release()
    staged = stage_open_us_law_hf_release(release, tmp_path, dry_run=True)
    assert staged.dry_run is True
    assert list(tmp_path.iterdir()) == []


def test_stage_writes_descriptor_complete_tree(tmp_path: Path) -> None:
    release = build_open_us_law_hf_release(
        fixture_family_rows(),
        dry_run=False,
        output_dir=tmp_path,
    )
    assert release.dry_run is False
    assert release.staged_root is not None
    assert (tmp_path / MANIFEST_FILENAME).is_file()
    assert (tmp_path / README_FILENAME).is_file()
    assert (tmp_path / "data" / "corpus" / "part-000000.parquet").is_file()
    assert (tmp_path / "data" / "vectors" / "locator" / "part-000000.parquet").is_file()
    assert (tmp_path / "data" / "vectors" / "centroids" / "part-000000.parquet").is_file()
    assert (tmp_path / "receipts" / "source" / "part-000000.json").is_file()
    assert (tmp_path / "recovery" / "part-000000.json").is_file()
    receipt = validate_open_us_law_hf_release(release)
    assert receipt["acceptance"]["viewer_safe_default_exact_51"] is True


def test_federal_row_cannot_enter_default_corpus() -> None:
    rows = fixture_family_rows()
    rows["corpus"] = [example_federal_payload()]
    with pytest.raises(OpenUsLawHFReleaseSafetyError):
        build_open_us_law_hf_release(rows, dry_run=True)


def test_recovery_contamination_of_default_fails_validation() -> None:
    release = _build_fixture_release()
    tainted = []
    for art in release.artifacts:
        if art.relative_path.startswith("recovery/"):
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
    bad = OpenUsLawHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        model_id=release.model_id,
        model_revision=release.model_revision,
        configs=release.configs,
        artifacts=tuple(tainted),
        dry_run=True,
    )
    with pytest.raises(OpenUsLawHFReleaseSafetyError):
        validate_open_us_law_hf_release(bad)


def test_assemble_from_family_rows_matches_builder() -> None:
    assembled = assemble_open_us_law_hf_release(fixture_family_rows(), dry_run=True)
    built = _build_fixture_release()
    assert releases_are_byte_identical(assembled, built)


def test_extractors_cover_required_families() -> None:
    from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (
        bind_fixture_bm25,
    )
    from ipfs_datasets_py.processors.legal_data.open_us_law_graph import (
        bind_fixture_graph,
    )
    from ipfs_datasets_py.processors.legal_data.open_us_law_lexical_graph import (
        bind_fixture_graph_adjacency,
    )
    from ipfs_datasets_py.processors.legal_data.open_us_law_vectors import (
        bind_fixture_vectors,
    )

    bm25_rows = rows_from_bm25_index(bind_fixture_bm25())
    assert bm25_rows["bm25_documents"]
    assert bm25_rows["bm25_postings"]
    vector_rows = rows_from_vector_binding(bind_fixture_vectors())
    assert vector_rows["vectors"]
    assert vector_rows["centroids"]
    assert vector_rows["vector_locator"]
    graph_rows = rows_from_graph_projection(bind_fixture_graph())
    assert graph_rows["graph_nodes"]
    assert graph_rows["graph_edges"]
    _overlay, _projection, adjacency = bind_fixture_graph_adjacency()
    adj_rows = rows_from_two_way_adjacency(adjacency)
    assert adj_rows["graph_adjacency_out"]
    assert adj_rows["graph_adjacency_in"]


def test_no_huggingface_hub_upload_surface() -> None:
    import inspect

    import ipfs_datasets_py.processors.legal_data.open_us_law_hf_release as mod

    source = inspect.getsource(mod)
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    assert "HfApi(" not in source.replace(
        "HfApi construction is forbidden in open_us_law_hf_release", ""
    )

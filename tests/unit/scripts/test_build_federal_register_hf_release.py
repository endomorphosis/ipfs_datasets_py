"""Unit tests for descriptor-complete Federal Register HF release packaging (LCR-062)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CONTROL_PLANE_PATHS,
    DEFAULT_CONFIG_NAME,
    DENIED_FEDERAL_SOURCE_ID,
    GOAL_ID,
    LEGACY_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    MANIFEST_FILENAME,
    PROGRAM_ID,
    QUARANTINE_CONFIG_NAME,
    README_FILENAME,
    RECOVERY_CONFIG_NAME,
    RELEASE_METADATA_FILENAME,
    REQUIRED_MANIFEST_BINDINGS,
    SCHEMA_VERSION,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    TASK_ID,
    FederalRegisterHFReleaseConfigError,
    FederalRegisterHFReleaseSafetyError,
    FederalRegisterHuggingFaceRelease,
    HubUploadForbiddenError,
    ReleaseArtifact,
    advertised_viewer_configs,
    assemble_federal_register_hf_release,
    assert_configs_schema_coherent,
    build_federal_register_hf_release,
    consume_lcr061_family_outputs,
    fixture_family_rows,
    fixture_legacy_files,
    load_federal_candidate_evidence,
    load_fixture_dataset_card,
    load_source_rights_receipt,
    reject_hub_upload,
    releases_are_byte_identical,
    render_dataset_card,
    rollback_map,
    route_bounds_policy,
    run_hermetic_check,
    stage_federal_register_hf_release,
    validate_federal_register_hf_release,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    require_source_rights_binding,
)
import scripts.ops.legal_data.build_federal_register_hf_release as cli


REPO_ROOT = Path(__file__).resolve().parents[3]
CARD_TEMPLATE = REPO_ROOT / "docs" / "templates" / "FEDERAL_REGISTER_DATASET_CARD.md"
CANDIDATE_PATH = (
    REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "federal_candidate.json"
)


def _build_fixture_release(**kwargs):
    return build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Identity / CLI
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert TASK_ID == "LCR-062"
    assert GOAL_ID == "LCR-G130"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert SCHEMA_VERSION == "federal-register-hf-release/v1"
    assert DEFAULT_CONFIG_NAME == RELEASE_PROFILE
    assert AUTHORIZES_HUB_UPLOAD is False
    assert AUTHORIZES_PUBLICATION is False


def test_cli_identity_and_help() -> None:
    assert cli.TASK_ID == "LCR-062"
    assert cli.GOAL_ID == "LCR-G130"
    parser = cli.build_parser()
    assert parser.prog == "build_federal_register_hf_release.py"
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0


def test_hub_upload_forbidden() -> None:
    with pytest.raises(HubUploadForbiddenError):
        reject_hub_upload(True)
    reject_hub_upload(False)
    with pytest.raises(SystemExit):
        cli.main(["--fixture-only", "--hub-upload"])


def test_fixture_only_required() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--no-fixture-only"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Fixtures on disk
# ---------------------------------------------------------------------------


def test_sealed_dataset_card_template_documents_configs() -> None:
    assert CARD_TEMPLATE.is_file()
    card = load_fixture_dataset_card(CARD_TEMPLATE)
    assert card.startswith("---\n")
    assert "configs:" in card
    assert DEFAULT_CONFIG_NAME in card
    assert RECOVERY_CONFIG_NAME in card
    assert QUARANTINE_CONFIG_NAME in card
    assert LEGACY_CONFIG_NAME in card
    assert "recovery" in card.lower()
    assert "lineage" in card.lower()
    assert "source-scope rights" in card.lower()
    front = card.split("---", 2)[1]
    assert 'path: "data/**/*.parquet"' in front
    assert f'config_name: "{DEFAULT_CONFIG_NAME}"' in front
    assert f'config_name: "{RECOVERY_CONFIG_NAME}"' in front
    assert DEFAULT_EMBEDDING_MODEL_ID in card
    assert DEFAULT_EMBEDDING_MODEL_REVISION in card
    assert "thenlper/gte-small" in card
    assert "vector locator" in card.lower() or "locator" in card.lower()
    rights = load_source_rights_receipt()
    assert rights["receipt_digest"] in card
    assert SOURCE_RIGHTS_RECEIPT_RELPATH in card
    assert PREVIOUS_PUBLIC_PIN in card


def test_rendered_card_matches_sealed_template() -> None:
    sealed = load_fixture_dataset_card(CARD_TEMPLATE).strip()
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
    assert receipt["viewer_safe_default_v2"] is True
    defaults = [c for c in configs if c.is_default]
    assert len(defaults) == 1
    assert defaults[0].config_name == DEFAULT_CONFIG_NAME
    assert defaults[0].viewer_safe_default is True
    for entry in defaults[0].data_files:
        assert "recovery" not in entry["path"]
        assert "quarantine" not in entry["path"]
        assert not entry["path"].startswith("federal_register")
    names = {cfg.config_name for cfg in configs}
    assert DEFAULT_CONFIG_NAME in names
    assert RECOVERY_CONFIG_NAME in names
    assert QUARANTINE_CONFIG_NAME in names
    assert LEGACY_CONFIG_NAME in names


def test_default_config_cannot_advertise_recovery_path() -> None:
    configs = list(
        advertised_viewer_configs(include_recovery=False, include_quarantine=False)
    )
    bad = configs[0].to_dict()
    bad["data_files"] = [{"split": "train", "path": "recovery/**/*.json"}]
    with pytest.raises(FederalRegisterHFReleaseSafetyError):
        assert_configs_schema_coherent([bad, *configs[1:]])


def test_two_defaults_rejected() -> None:
    configs = advertised_viewer_configs(
        include_legacy=False,
        include_recovery=False,
        include_quarantine=False,
    )
    twin = configs[0].to_dict()
    twin["config_name"] = "federal-register-ir-graphrag/v2-dup"
    with pytest.raises(FederalRegisterHFReleaseConfigError):
        assert_configs_schema_coherent([configs[0], twin])


def test_non_default_cannot_be_viewer_safe() -> None:
    configs = advertised_viewer_configs()
    recovery = next(c for c in configs if c.is_recovery).to_dict()
    recovery["viewer_safe_default"] = True
    with pytest.raises(FederalRegisterHFReleaseConfigError):
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
    receipt = validate_federal_register_hf_release(release)
    assert receipt["valid"] is True
    acc = receipt["acceptance"]
    assert acc["default_config_excludes_recovery"] is True
    assert acc["all_advertised_configs_schema_coherent"] is True
    assert acc["every_artifact_descriptor_bound"] is True
    assert acc["verbose_lineage_separate_from_control_plane"] is True
    assert acc["viewer_safe_default_v2"] is True
    assert acc["source_rights_bound"] is True
    assert acc["semantic_family_closure"] is True
    assert receipt["default_config"] == DEFAULT_CONFIG_NAME
    assert receipt["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION


def test_default_config_excludes_recovery_and_quarantine() -> None:
    release = _build_fixture_release()
    default = next(c for c in release.configs if c.is_default)
    assert default.config_name == DEFAULT_CONFIG_NAME
    for entry in default.data_files:
        assert "recovery" not in entry["path"]
        assert "quarantine" not in entry["path"]
        assert not entry["path"].startswith("federal_register")
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
    assert manifest["viewer_safe_default_v2"] is True


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
        assert not art.relative_path.startswith("/")
        assert ".." not in art.relative_path


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
    assert bounds["model_token_ceiling"] == 512
    assert manifest["viewer_safe_default_v2"] is True
    assert manifest["default_config"] == DEFAULT_CONFIG_NAME
    assert manifest["task_id"] == TASK_ID
    assert manifest["release_profile"] == RELEASE_PROFILE
    assert manifest["rollback"]["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert manifest["semantic_family_closure"]["closed"] is True


def test_route_bounds_policy_matches_schema() -> None:
    bounds = route_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_posting_pointers_per_row"] == 4096
    assert bounds["max_adjacency_pointers_per_row"] == 4096
    assert rollback_map()["previous_public_pin"] == PREVIOUS_PUBLIC_PIN


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
    assert metadata["viewer_safe_default_v2"] is True
    assert release.schema_version == SCHEMA_VERSION
    assert release.dataset_id == DEFAULT_DATASET_REPO_ID


def test_source_rights_receipt_is_bound() -> None:
    release = _build_fixture_release()
    rights = load_source_rights_receipt()
    manifest = release.manifest_dict()
    card = release.dataset_card_text()
    require_source_rights_binding(
        manifest,
        receipt_digest=rights["receipt_digest"],
        catalog_digest=rights["catalog_digest_sha256"],
        dataset_card_text=card,
    )
    assert manifest["source_rights_receipt_digest"] == rights["receipt_digest"]
    assert manifest["source_rights_receipt_path"] == SOURCE_RIGHTS_RECEIPT_RELPATH
    assert manifest["authorizing_for_publication"] is False
    assert rights["receipt_digest"] in card
    assert "LCR-078" in card
    assert "LCR-079" in card


def test_fixture_receipts_do_not_authorize_publication() -> None:
    release = _build_fixture_release()
    for art in release.artifacts:
        if not art.media_type.startswith("application/json"):
            continue
        body = json.loads(art.content.decode("utf-8"))
        if isinstance(body, dict) and "authorizing_for_publication" in body:
            assert body["authorizing_for_publication"] is False, art.relative_path


def test_no_absolute_paths_or_secrets() -> None:
    release = _build_fixture_release()
    for art in release.artifacts:
        text = art.content.decode("utf-8", errors="replace")
        assert "/home/" not in text
        assert "/Users/" not in text
        assert "HF_TOKEN=" not in text
        assert "HUGGINGFACE_TOKEN=" not in text
        assert "Bearer " not in text
        assert "file://" not in text


def test_stage_dry_run_does_not_write(tmp_path: Path) -> None:
    release = _build_fixture_release()
    staged = stage_federal_register_hf_release(release, tmp_path, dry_run=True)
    assert staged.dry_run is True
    assert list(tmp_path.iterdir()) == []


def test_stage_writes_descriptor_complete_tree(tmp_path: Path) -> None:
    release = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=False,
        output_dir=tmp_path,
    )
    assert release.dry_run is False
    assert release.staged_root is not None
    assert (tmp_path / MANIFEST_FILENAME).is_file()
    assert (tmp_path / README_FILENAME).is_file()
    corpus = list((tmp_path / "data" / "corpus").rglob("*.parquet"))
    assert corpus
    assert (tmp_path / "data" / "vectors" / "locator" / "part-000000.parquet").is_file()
    assert (tmp_path / "data" / "vectors" / "centroids" / "part-000000.parquet").is_file()
    assert (tmp_path / "receipts" / "source" / "part-000000.json").is_file()
    assert (tmp_path / "recovery" / "part-000000.json").is_file()
    receipt = validate_federal_register_hf_release(release)
    assert receipt["acceptance"]["viewer_safe_default_v2"] is True


def test_legacy_files_not_deleted_on_stage(tmp_path: Path) -> None:
    legacy_path = "federal_register.parquet"
    legacy_target = tmp_path / legacy_path
    original = b"LEGACY-FR-BYTES-MUST-REMAIN\n"
    legacy_target.write_bytes(original)
    release = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=None,
        include_legacy_config=True,
        dry_run=False,
        output_dir=tmp_path,
        preserve_existing=(legacy_path,),
    )
    assert release.dry_run is False
    assert legacy_target.is_file()
    assert legacy_target.read_bytes() == original
    assert (tmp_path / MANIFEST_FILENAME).is_file()
    receipt = validate_federal_register_hf_release(release)
    assert receipt["acceptance"]["legacy_files_not_deleted"] is True


def test_prohibited_rights_cannot_enter_default() -> None:
    rows = fixture_family_rows()
    bad = dict(rows["corpus"][0])
    bad["rights_disposition"] = "prohibited"
    rows["corpus"] = [bad]
    with pytest.raises(FederalRegisterHFReleaseSafetyError):
        build_federal_register_hf_release(rows, dry_run=True)


def test_unknown_rights_cannot_enter_default() -> None:
    rows = fixture_family_rows()
    bad = dict(rows["corpus"][0])
    bad["rights_disposition"] = "unknown"
    rows["corpus"] = [bad]
    with pytest.raises(FederalRegisterHFReleaseSafetyError):
        build_federal_register_hf_release(rows, dry_run=True)


def test_denied_source_id_cannot_enter_default() -> None:
    rows = fixture_family_rows()
    bad = dict(rows["corpus"][0])
    bad["source_id"] = DENIED_FEDERAL_SOURCE_ID
    rows["corpus"] = [bad]
    with pytest.raises(FederalRegisterHFReleaseSafetyError):
        build_federal_register_hf_release(rows, dry_run=True)


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
    bad = FederalRegisterHuggingFaceRelease(
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
        source_rights_receipt_digest=release.source_rights_receipt_digest,
    )
    with pytest.raises(FederalRegisterHFReleaseSafetyError):
        validate_federal_register_hf_release(bad)


def test_assemble_from_family_rows_matches_builder() -> None:
    assembled = assemble_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    built = _build_fixture_release()
    assert releases_are_byte_identical(assembled, built)


def test_lcr061_family_outputs_are_consumed_immutably() -> None:
    consumption = consume_lcr061_family_outputs()
    assert consumption["consumed_as_immutable_input"] is True
    assert consumption["producer_task_id"] == "LCR-061"
    assert consumption["authorizing_hub_upload"] is False
    assert consumption["authorizing_for_publication"] is False
    assert consumption["bm25_root"]
    assert consumption["vector_root"]
    assert consumption["graph_root"]
    assert consumption["adjacency_root"]
    release = _build_fixture_release(lcr061_consumption=consumption)
    manifest = release.manifest_dict()
    assert manifest["lcr061_consumption_digest"] == consumption["consumption_digest"]
    assert manifest["lcr061_family_roots"]["bm25_root"] == consumption["bm25_root"]


def test_corpus_uses_year_month_document_type_paths() -> None:
    release = _build_fixture_release()
    corpus = [
        art
        for art in release.artifacts
        if art.family == "corpus"
    ]
    assert corpus
    for art in corpus:
        assert "year_month=" in art.relative_path
        assert "document_type=" in art.relative_path
        assert art.year_month
        assert art.document_type


def test_federal_candidate_evidence_is_bound() -> None:
    assert CANDIDATE_PATH.is_file()
    sealed = load_federal_candidate_evidence(CANDIDATE_PATH)
    release = _build_fixture_release()
    assert sealed["task_id"] == TASK_ID
    assert sealed["goal_id"] == GOAL_ID
    assert sealed["program_id"] == PROGRAM_ID
    assert sealed["authorizing_for_publication"] is False
    assert sealed["authorizing_hub_upload"] is False
    assert sealed["fixture_only"] is True
    assert sealed["hub_upload"] is False
    assert sealed["candidate"]["manifest_digest"] == release.manifest_digest
    assert sealed["candidate"]["release_root_cid"] == release.release_root_cid
    assert (
        sealed["source_rights"]["receipt_digest"]
        == release.source_rights_receipt_digest
    )
    assert sealed["rollback"]["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert "/home/" not in json.dumps(sealed)
    assert "HF_TOKEN" not in json.dumps(sealed)


def test_cli_check_is_hermetic(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--fixture-only", "--check", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "LCR-062"
    assert payload["goal_id"] == "LCR-G130"
    assert payload["program_id"] == "legal-corpora-reindex-v1"
    assert payload["authorizing_hub_upload"] is False
    assert payload["authorizing_for_publication"] is False
    required = {
        "two_build_logical_determinism",
        "source_rights_bound",
        "semantic_family_closure",
        "old_pin_rollback_named",
        "lcr061_family_outputs_consumed",
        "candidate_evidence_root_bound",
    }
    assert required.issubset(set(payload["proofs"]))


def test_run_hermetic_check_matches_cli() -> None:
    payload = run_hermetic_check()
    assert payload["ok"] is True
    assert payload["fixture_only"] is True
    assert "check_digest" in payload


def test_assembler_source_has_no_hub_upload_surface() -> None:
    source = (
        REPO_ROOT
        / "ipfs_datasets_py"
        / "processors"
        / "legal_data"
        / "federal_register_hf_release.py"
    ).read_text(encoding="utf-8")
    prefix = source.split("def _assert_no_upload_shortcut", 1)[0]
    assert "huggingface_hub" not in prefix
    assert "HfApi(" not in prefix
    assert "upload_file(" not in prefix
    assert "upload_folder(" not in prefix
    cli_source = (
        REPO_ROOT
        / "scripts"
        / "ops"
        / "legal_data"
        / "build_federal_register_hf_release.py"
    ).read_text(encoding="utf-8")
    assert "huggingface_hub" not in cli_source
    assert "upload_file(" not in cli_source

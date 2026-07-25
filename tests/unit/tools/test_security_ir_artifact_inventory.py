from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.security_ir import inventory_artifacts as inventory


REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = REPO_ROOT / "security_ir_artifacts"
INVENTORY_PATH = (
    REPO_ROOT / "docs/security_verification/security_ir_artifact_inventory.json"
)


def _by_path(payload: dict) -> dict[str, dict]:
    return {record["path"]: record for record in payload["artifacts"]}


def test_checked_in_inventory_is_complete_and_deterministic() -> None:
    first = inventory.build_inventory(REPO_ROOT)
    second = inventory.build_inventory(REPO_ROOT)

    assert first == second
    assert inventory.render_inventory(first) == INVENTORY_PATH.read_text(
        encoding="utf-8"
    )
    assert first["schema_version"] == "SecurityArtifactInventory@1"
    assert first["scope"] == "git-tracked files"
    assert first["artifact_count"] == 269
    assert len(first["artifacts"]) == first["artifact_count"]
    assert sum(first["classification_counts"].values()) == first["artifact_count"]
    assert sum(first["format_counts"].values()) == first["artifact_count"]
    assert first["authority_decisions_made"] == 0

    paths = [record["path"] for record in first["artifacts"]]
    assert paths == sorted(paths, key=lambda value: value.encode("utf-8"))
    assert len(paths) == len(set(paths))
    assert paths == [
        path.as_posix()
        for path in inventory.tracked_artifact_paths(REPO_ROOT)
    ]

    canonical_records = json.dumps(
        first["artifacts"],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert first["inventory_sha256"] == hashlib.sha256(canonical_records).hexdigest()


def test_every_record_has_verifiable_content_and_a_migration_recommendation() -> None:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    for record in payload["artifacts"]:
        path = REPO_ROOT / record["path"]
        content = path.read_bytes()
        assert record["size_bytes"] == len(content)
        assert record["sha256"] == hashlib.sha256(content).hexdigest()
        assert record["detected_format"]
        assert record["classification"] in inventory.CLASSIFICATIONS
        assert record["likely_producers"]
        assert isinstance(record["legacy_ids"], list)
        assert isinstance(record["ambiguity_reasons"], list)
        assert record["recommendations"]
        assert record["authority_selected"] is False


def test_temporary_and_filename_variants_are_explicit_without_authority() -> None:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    records = _by_path(payload)

    new_variants = {
        "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage-new.json":
            "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json",
        "security_ir_artifacts/corpora/xaman-app/public-source-assessment-new.json":
            "security_ir_artifacts/corpora/xaman-app/public-source-assessment.json",
        "security_ir_artifacts/corpora/xaman-app/source-claim-map-new.json":
            "security_ir_artifacts/corpora/xaman-app/source-claim-map.json",
    }
    assert payload["new_variant_count"] == len(new_variants)
    for variant_path, base_path in new_variants.items():
        record = records[variant_path]
        assert record["is_new_variant"] is True
        assert record["classification"] == "ambiguous"
        assert record["variant_of"] == base_path
        assert record["ambiguity_reasons"]
        assert record["authority_selected"] is False

    temporary = records[
        "security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.tmp.json"
    ]
    assert temporary["is_temporary"] is True
    assert temporary["classification"] == "transient compiler output"
    assert temporary["variant_of"].endswith("/fuzz-report.json")

    latest = records[
        "security_ir_artifacts/recovery/taskboard-preflight-latest.json"
    ]
    assert latest["is_mutable_alias"] is True
    assert latest["classification"] == "ambiguous"
    assert latest["variant_of"].endswith("/taskboard-preflight.json")

    apalache_records = [
        record
        for record in payload["artifacts"]
        if "/_apalache-out/" in record["path"]
    ]
    assert apalache_records
    assert all(record["is_temporary"] for record in apalache_records)
    assert all(
        record["classification"] == "transient compiler output"
        for record in apalache_records
    )

    groups = {group["base_path"]: group for group in payload["variant_groups"]}
    assert set(new_variants.values()) <= set(groups)
    assert all(group["authority_selected"] is False for group in groups.values())
    assert all(len(group["paths"]) >= 2 for group in groups.values())


def test_legacy_identifier_and_format_detection_on_fixture_tree(tmp_path: Path) -> None:
    root = tmp_path / "security_ir_artifacts"
    root.mkdir()
    json_path = root / "model.json"
    json_path.write_text(
        json.dumps(
            {
                "model_id": "legacy-model",
                "task_ids": ["IR-2", "IR-1"],
                "artifact_cid": "sha256:abc",
                "ignored": {"claim_id": "nested-id"},
            }
        ),
        encoding="utf-8",
    )
    (root / "model.cid").write_text("sha256:def\n", encoding="utf-8")
    (root / "broken.json").write_text("{not-json", encoding="utf-8")
    (root / "query.smt2").write_text("(check-sat)\n", encoding="utf-8")

    payload = inventory.build_inventory(tmp_path, tracked_only=False)
    records = _by_path(payload)
    model = records["security_ir_artifacts/model.json"]

    assert model["detected_format"] == "json"
    assert model["legacy_ids"] == [
        {"field": "artifact_cid", "value": "sha256:abc"},
        {"field": "model_id", "value": "legacy-model"},
        {"field": "task_ids", "value": "IR-1"},
        {"field": "task_ids", "value": "IR-2"},
    ]
    assert records["security_ir_artifacts/model.cid"]["legacy_ids"] == [
        {"field": "sidecar", "value": "sha256:def"}
    ]
    assert records["security_ir_artifacts/broken.json"]["detected_format"] == (
        "invalid-json"
    )
    assert records["security_ir_artifacts/broken.json"]["ambiguity_reasons"]
    assert records["security_ir_artifacts/query.smt2"]["classification"] == "source"


def test_writer_refuses_to_write_inside_artifact_tree(tmp_path: Path) -> None:
    root = tmp_path / "security_ir_artifacts"
    root.mkdir()
    (root / "input.json").write_text("{}", encoding="utf-8")
    payload = inventory.build_inventory(tmp_path, tracked_only=False)

    with pytest.raises(ValueError, match="outside the artifact tree"):
        inventory.write_inventory(
            payload,
            root / "inventory.json",
            repo_root=tmp_path,
        )

    assert not (root / "inventory.json").exists()


def test_migration_control_records_are_not_reinventoried_as_legacy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "security_ir_artifacts"
    migrations = root / "migrations"
    migrations.mkdir(parents=True)
    legacy = root / "source.json"
    legacy.write_text("{}", encoding="utf-8")
    (migrations / "manifest.json").write_text("{}", encoding="utf-8")

    assert [
        path.as_posix()
        for path in inventory.filesystem_artifact_paths(tmp_path)
    ] == ["security_ir_artifacts/source.json"]
    payload = inventory.build_inventory(tmp_path, tracked_only=False)
    assert [record["path"] for record in payload["artifacts"]] == [
        "security_ir_artifacts/source.json"
    ]


def test_check_mode_is_read_only_and_detects_stale_output(tmp_path: Path) -> None:
    root = tmp_path / "security_ir_artifacts"
    root.mkdir()
    artifact = root / "source.json"
    artifact.write_text('{"model_id":"legacy"}\n', encoding="utf-8")
    output = tmp_path / "inventory.json"
    payload = inventory.build_inventory(tmp_path, tracked_only=False)
    inventory.write_inventory(payload, output, repo_root=tmp_path)
    artifact_before = artifact.read_bytes()

    arguments = [
        "--repo-root",
        str(tmp_path),
        "--include-untracked",
        "--output",
        str(output),
        "--check",
    ]
    assert inventory.main(arguments) == 0
    assert artifact.read_bytes() == artifact_before

    output.write_text("{}\n", encoding="utf-8")
    assert inventory.main(arguments) == 1
    assert output.read_text(encoding="utf-8") == "{}\n"
    assert artifact.read_bytes() == artifact_before

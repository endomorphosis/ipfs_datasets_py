"""Contract tests for the read-only Security IR artifact inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/security_ir/inventory_artifacts.py"
INVENTORY_PATH = (
    REPO_ROOT
    / "docs/security_verification/security_ir_artifact_inventory.json"
)

sys.path.insert(0, str(REPO_ROOT))
from tools.security_ir.inventory_artifacts import (  # noqa: E402
    InventoryError,
    build_inventory,
    serialize_inventory,
)


def _row(inventory: dict, path: str) -> dict:
    return next(item for item in inventory["artifacts"] if item["path"] == path)


def test_checked_in_inventory_is_complete_and_byte_accurate() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "security_ir_artifacts"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.split(b"\0")
    tracked_paths = sorted(path.decode("utf-8") for path in tracked if path)

    assert inventory["interface"] == "SecurityArtifactInventory@1"
    assert inventory["policy"]["read_only"] is True
    assert inventory["policy"]["authority_selection"] == "none"
    assert [row["path"] for row in inventory["artifacts"]] == tracked_paths
    assert inventory["summary"]["artifact_count"] == len(tracked_paths) == 269

    for row in inventory["artifacts"]:
        data = (REPO_ROOT / row["path"]).read_bytes()
        assert row["size_bytes"] == len(data)
        assert row["sha256"] == hashlib.sha256(data).hexdigest()
        assert row["detected_format"]
        assert row["classification"] in inventory["summary"]["classification_counts"]
        assert row["likely_producers"]
        assert isinstance(row["legacy_ids"], list)
        assert isinstance(row["ambiguity_reasons"], list)
        assert row["recommendation"].startswith("Retain")
    assert sum(inventory["summary"]["classification_counts"].values()) == 269


def test_checked_in_inventory_matches_a_fresh_deterministic_build() -> None:
    first = build_inventory(REPO_ROOT)
    second = build_inventory(REPO_ROOT)
    checked_in = INVENTORY_PATH.read_text(encoding="utf-8")

    assert first == second
    assert serialize_inventory(first) == checked_in
    assert "generated_at" not in checked_in


def test_variants_are_ambiguous_without_an_authority_decision() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    expected_pairs = {
        frozenset(
            {
                "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json",
                "security_ir_artifacts/corpora/xaman-app/native-boundary-coverage-new.json",
            }
        ),
        frozenset(
            {
                "security_ir_artifacts/corpora/xaman-app/public-source-assessment.json",
                "security_ir_artifacts/corpora/xaman-app/public-source-assessment-new.json",
            }
        ),
        frozenset(
            {
                "security_ir_artifacts/corpora/xaman-app/source-claim-map.json",
                "security_ir_artifacts/corpora/xaman-app/source-claim-map-new.json",
            }
        ),
        frozenset(
            {
                "security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json",
                "security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.tmp.json",
            }
        ),
    }
    actual_pairs = {
        frozenset(group["paths"])
        for group in inventory["variant_groups"]
        if group["kind"] in {"new_suffix", "temporary_name"}
    }

    assert expected_pairs <= actual_pairs
    for pair in expected_pairs:
        for path in pair:
            row = _row(inventory, path)
            assert row["classification"] == "ambiguous"
            assert row["ambiguity_reasons"]
        matching_group = next(
            group
            for group in inventory["variant_groups"]
            if frozenset(group["paths"]) == pair
        )
        assert matching_group["authority_selected"] is False

    temporary = _row(
        inventory,
        "security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.tmp.json",
    )
    assert temporary["temporary"] is True
    assert temporary["variant_kinds"] == ["temporary_name"]


def test_compiler_outputs_and_legacy_ids_are_explicit() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    coq_object = _row(
        inventory,
        "security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.vo",
    )
    apalache_log = next(
        row
        for row in inventory["artifacts"]
        if "/_apalache-out/" in row["path"] and row["path"].endswith("/log0.smt")
    )
    model = _row(
        inventory,
        "security_ir_artifacts/corpora/xaman-app/security-model-ir.json",
    )

    assert coq_object["detected_format"] == "coq_compiled_object"
    assert coq_object["classification"] == "transient_compiler_output"
    assert coq_object["temporary"] is True
    assert apalache_log["classification"] == "transient_compiler_output"
    assert apalache_log["temporary"] is True
    assert any(
        item["source_path"].endswith("security-model-ir.cid")
        for item in model["legacy_ids"]
    )


def test_small_fixture_covers_formats_ids_and_determinism(tmp_path: Path) -> None:
    artifact_root = tmp_path / "security_ir_artifacts"
    artifact_root.mkdir()
    (artifact_root / "model.json").write_text(
        json.dumps({"artifact_cid": f"sha256:{'a' * 64}"}) + "\n",
        encoding="utf-8",
    )
    (artifact_root / "model.cid").write_text(
        "bafkreigh2akiscaildc6fnda7g5q4a5t5upq5j3f4u6mq2keo6fm4b2u4e\n",
        encoding="utf-8",
    )
    (artifact_root / "result.json").write_text('{"status":"old"}\n', encoding="utf-8")
    (artifact_root / "result-new.json").write_text(
        '{"status":"new"}\n', encoding="utf-8"
    )
    paths = [
        "security_ir_artifacts/result-new.json",
        "security_ir_artifacts/model.cid",
        "security_ir_artifacts/result.json",
        "security_ir_artifacts/model.json",
    ]

    inventory = build_inventory(tmp_path, tracked_paths=paths)

    assert [row["path"] for row in inventory["artifacts"]] == sorted(paths)
    assert serialize_inventory(inventory) == serialize_inventory(
        build_inventory(tmp_path, tracked_paths=reversed(paths))
    )
    model_ids = _row(inventory, "security_ir_artifacts/model.json")["legacy_ids"]
    assert {item["representation"] for item in model_ids} == {
        "cidv1",
        "sha256_prefixed",
    }
    assert all(
        _row(inventory, path)["classification"] == "ambiguous"
        for path in (
            "security_ir_artifacts/result.json",
            "security_ir_artifacts/result-new.json",
        )
    )


def test_inventory_rejects_paths_outside_the_artifact_root(tmp_path: Path) -> None:
    (tmp_path / "outside.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(InventoryError, match="outside security_ir_artifacts"):
        build_inventory(tmp_path, tracked_paths=["outside.json"])


def test_cli_check_mode_is_read_only() -> None:
    before = INVENTORY_PATH.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(REPO_ROOT), "--check"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "269 artifacts" in completed.stdout
    assert INVENTORY_PATH.read_bytes() == before

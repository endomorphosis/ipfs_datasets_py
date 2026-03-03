"""WS12-07: Tests for the Release Evidence Pack v2 manifest builder."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the module under test via sys.path trick (no package install needed)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "legal_data"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from build_hybrid_v2_evidence_manifest import (  # noqa: E402
    EVIDENCE_MANIFEST_VERSION,
    REQUIRED_ARTIFACTS,
    build_evidence_manifest,
    compute_artifact_hash,
    validate_evidence_manifest,
)

# Repo root is 3 levels up from the tests/reasoner/ directory
_REPO_ROOT = str(Path(__file__).resolve().parents[3])


# ---------------------------------------------------------------------------
# Tests for build_evidence_manifest
# ---------------------------------------------------------------------------


class TestBuildEvidenceManifest:
    def _manifest(self):
        return build_evidence_manifest(repo_root=_REPO_ROOT)

    def test_returns_required_keys(self):
        m = self._manifest()
        assert "manifest_version" in m
        assert "artifacts" in m
        assert "missing_artifacts" in m
        assert "all_present" in m

    def test_manifest_version_matches_constant(self):
        m = self._manifest()
        assert m["manifest_version"] == EVIDENCE_MANIFEST_VERSION

    def test_all_required_artifacts_present(self):
        m = self._manifest()
        assert m["all_present"] is True, (
            f"Missing artifacts: {m['missing_artifacts']}"
        )

    def test_missing_artifacts_empty_when_all_present(self):
        m = self._manifest()
        assert m["missing_artifacts"] == []

    def test_artifacts_dict_contains_all_required_entries(self):
        m = self._manifest()
        for artifact in REQUIRED_ARTIFACTS:
            assert artifact in m["artifacts"], f"Artifact not in manifest: {artifact}"

    def test_each_artifact_entry_has_present_and_sha256_keys(self):
        m = self._manifest()
        for name, info in m["artifacts"].items():
            assert "present" in info, f"'present' missing for {name}"
            assert "sha256" in info, f"'sha256' missing for {name}"

    def test_present_artifacts_have_sha256_hex_string(self):
        m = self._manifest()
        for name, info in m["artifacts"].items():
            if info["present"]:
                sha = info["sha256"]
                assert isinstance(sha, str) and len(sha) == 64, (
                    f"Invalid sha256 for {name}: {sha!r}"
                )

    def test_manifest_version_constant_value(self):
        assert EVIDENCE_MANIFEST_VERSION == "2.0"


# ---------------------------------------------------------------------------
# Tests for validate_evidence_manifest
# ---------------------------------------------------------------------------


class TestValidateEvidenceManifest:
    def _manifest(self):
        return build_evidence_manifest(repo_root=_REPO_ROOT)

    def test_valid_when_all_artifacts_present(self):
        m = self._manifest()
        result = validate_evidence_manifest(m)
        assert result["valid"] is True

    def test_missing_list_empty_when_valid(self):
        m = self._manifest()
        result = validate_evidence_manifest(m)
        assert result["missing"] == []

    def test_present_count_equals_total_when_valid(self):
        m = self._manifest()
        result = validate_evidence_manifest(m)
        assert result["present_count"] == result["total_count"]
        assert result["total_count"] == len(REQUIRED_ARTIFACTS)

    def test_invalid_when_artifact_removed_from_manifest(self):
        m = self._manifest()
        # Remove one artifact from the manifest to simulate missing
        tampered = copy.deepcopy(m)
        first_key = REQUIRED_ARTIFACTS[0]
        tampered["artifacts"][first_key]["present"] = False
        tampered["artifacts"][first_key]["sha256"] = None

        result = validate_evidence_manifest(tampered)
        assert result["valid"] is False

    def test_missing_lists_removed_artifact(self):
        m = self._manifest()
        tampered = copy.deepcopy(m)
        first_key = REQUIRED_ARTIFACTS[0]
        tampered["artifacts"][first_key]["present"] = False

        result = validate_evidence_manifest(tampered)
        assert first_key in result["missing"]

    def test_missing_artifact_fails_validation_deterministically(self):
        """Removing the same artifact always produces the same missing entry."""
        m = self._manifest()
        target = REQUIRED_ARTIFACTS[2]
        for _ in range(3):
            tampered = copy.deepcopy(m)
            tampered["artifacts"][target]["present"] = False
            result = validate_evidence_manifest(tampered)
            assert result["valid"] is False
            assert target in result["missing"]


# ---------------------------------------------------------------------------
# Tests for compute_artifact_hash
# ---------------------------------------------------------------------------


class TestComputeArtifactHash:
    def test_returns_sha256_hex_for_existing_file(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("hello evidence")
        digest = compute_artifact_hash(str(f))
        assert digest is not None
        assert isinstance(digest, str)
        assert len(digest) == 64
        # All hex characters
        int(digest, 16)

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        result = compute_artifact_hash(str(tmp_path / "does_not_exist.py"))
        assert result is None

    def test_hash_is_deterministic(self, tmp_path):
        f = tmp_path / "det.txt"
        f.write_text("deterministic content")
        h1 = compute_artifact_hash(str(f))
        h2 = compute_artifact_hash(str(f))
        assert h1 == h2

    def test_different_content_produces_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A")
        f2.write_text("content B")
        assert compute_artifact_hash(str(f1)) != compute_artifact_hash(str(f2))

"""Tests for hugging_face_pipeline_engine.py (Phase 5 extraction validation).

Tests RateLimiter and UploadToHuggingFaceInParallel without requiring
``huggingface_hub`` or ``bs4`` to be installed.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the engine module directly to avoid triggering package-level imports
# that depend on bs4, requests, etc.
# ---------------------------------------------------------------------------
_ENGINE_FILE = (
    Path(__file__).parent.parent.parent.parent
    / "ipfs_datasets_py"
    / "mcp_server"
    / "tools"
    / "legal_dataset_tools"
    / "municipal_law_database_scrapers"
    / "hugging_face_pipeline_engine.py"
)

_spec = importlib.util.spec_from_file_location("hf_pipeline_engine", _ENGINE_FILE)
_engine_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_engine_mod)  # type: ignore[union-attr]

RateLimiter = _engine_mod.RateLimiter
UploadToHuggingFaceInParallel = _engine_mod.UploadToHuggingFaceInParallel
HfApi = _engine_mod.HfApi
login = _engine_mod.login


# ---------------------------------------------------------------------------
# RateLimiter tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Tests for the token-bucket RateLimiter class."""

    def test_init_with_default_limit(self) -> None:
        """GIVEN no args; THEN tokens start at 300 (default limit)."""
        rl = RateLimiter()
        assert rl.request_limit_per_hour == 300
        assert rl.tokens == 300.0

    def test_init_with_custom_limit(self) -> None:
        """GIVEN custom limit; THEN tokens initialize at that limit."""
        rl = RateLimiter(request_limit_per_hour=60)
        assert rl.request_limit_per_hour == 60
        assert rl.tokens == 60.0

    def test_wait_for_token_consumes_token(self) -> None:
        """GIVEN full bucket; WHEN wait_for_token; THEN one token is consumed."""
        rl = RateLimiter(request_limit_per_hour=100)
        before = rl.tokens
        rl.wait_for_token(1)
        assert rl.tokens < before

    def test_get_current_rate_returns_float(self) -> None:
        """GIVEN a RateLimiter; WHEN get_current_rate; THEN returns a float >= 0."""
        rl = RateLimiter(request_limit_per_hour=120)
        rate = rl.get_current_rate()
        assert isinstance(rate, float)
        assert rate >= 0.0

    def test_reset_restores_tokens(self) -> None:
        """GIVEN partially consumed bucket; WHEN reset; THEN tokens back to limit."""
        rl = RateLimiter(request_limit_per_hour=50)
        rl.tokens = 10.0  # Simulate consumption
        rl.reset()
        assert rl.tokens == 50.0

    def test_thread_safety_lock_acquired(self) -> None:
        """GIVEN a RateLimiter; THEN it has a threading.Lock."""
        import threading
        rl = RateLimiter()
        assert isinstance(rl.mutex, type(threading.Lock()))


# ---------------------------------------------------------------------------
# UploadToHuggingFaceInParallel tests
# ---------------------------------------------------------------------------

class TestUploadToHuggingFaceInParallel:
    """Tests for UploadToHuggingFaceInParallel (without huggingface_hub)."""

    def test_init_without_configs(self) -> None:
        """GIVEN no args; THEN attributes have sane defaults."""
        uploader = UploadToHuggingFaceInParallel()
        assert uploader.repo_id == ""
        assert uploader.upload_count == 0
        assert uploader.failed_count == 0
        assert uploader.retry_count == 0

    def test_init_with_mock_configs(self) -> None:
        """GIVEN mock configs; THEN repo_id and rate_limiter are set."""
        class MockConfigs:
            REPO_ID = "owner/my-dataset"
            HUGGING_FACE_USER_ACCESS_TOKEN = None
            REQUEST_LIMIT_PER_HOUR = 100

        uploader = UploadToHuggingFaceInParallel(configs=MockConfigs())
        assert uploader.repo_id == "owner/my-dataset"
        assert isinstance(uploader.rate_limiter, RateLimiter)

    def test_api_attribute_is_hfapi(self) -> None:
        """GIVEN new uploader; THEN api is an HfApi instance."""
        uploader = UploadToHuggingFaceInParallel()
        assert isinstance(uploader.api, HfApi)

    def test_get_processed_file_info_returns_set(self) -> None:
        """GIVEN stub HfApi; WHEN _get_processed_file_info; THEN returns set."""
        uploader = UploadToHuggingFaceInParallel()
        # HfApi stub returns empty list → set should be empty
        result = uploader._get_processed_file_info()
        assert isinstance(result, set)

    def test_get_folders_to_upload_empty_dir(self, tmp_path: Path) -> None:
        """GIVEN empty directory; WHEN _get_folders_to_upload; THEN returns []."""
        uploader = UploadToHuggingFaceInParallel()
        folders = uploader._get_folders_to_upload(tmp_path, set())
        assert folders == []

    def test_get_folders_to_upload_skips_already_uploaded(self, tmp_path: Path) -> None:
        """GIVEN folder whose parquet already in repo; WHEN called; THEN skipped."""
        subdir = tmp_path / "batch_01"
        subdir.mkdir()
        pq = subdir / "data.parquet"
        pq.write_text("parquet_placeholder")

        uploader = UploadToHuggingFaceInParallel()
        # Mark the parquet as already uploaded
        folders = uploader._get_folders_to_upload(tmp_path, {"data.parquet"})
        assert subdir not in folders

    def test_get_folders_to_upload_includes_unuploaded(self, tmp_path: Path) -> None:
        """GIVEN folder with new parquet; WHEN called; THEN included."""
        subdir = tmp_path / "batch_02"
        subdir.mkdir()
        pq = subdir / "new.parquet"
        pq.write_text("parquet_placeholder")

        uploader = UploadToHuggingFaceInParallel()
        folders = uploader._get_folders_to_upload(tmp_path, set())
        assert subdir in folders

    def test_upload_folder_sync_succeeds_with_stub(self, tmp_path: Path) -> None:
        """GIVEN stub HfApi that returns resolved Future; WHEN _upload_folder_sync; THEN True."""
        uploader = UploadToHuggingFaceInParallel()
        result = uploader._upload_folder_sync(
            folder_path=tmp_path, path_in_repo="data/batch_01"
        )
        assert result is True

    def test_backward_compat_exports(self) -> None:
        """GIVEN the engine module; THEN __all__ exports are accessible."""
        assert hasattr(_engine_mod, "RateLimiter")
        assert hasattr(_engine_mod, "UploadToHuggingFaceInParallel")
        assert hasattr(_engine_mod, "HfApi")
        assert hasattr(_engine_mod, "CommitInfo")
        assert hasattr(_engine_mod, "HfHubHTTPError")
        assert hasattr(_engine_mod, "login")

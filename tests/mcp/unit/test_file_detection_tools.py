"""
Phase B2 unit tests — file_detection_tools category.

Tests: detect_file_type, batch_detect_file_types, analyze_detection_accuracy
All 3 functions are sync (not async).  magika is optional; tests work without it.
"""
from __future__ import annotations

import os
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_txt_file() -> str:
    """Create a temporary .txt file and return its path."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("hello world")
        return f.name


def _make_png_file() -> str:
    """Create a minimal PNG-like file (fake, but has .png extension)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        return f.name


# ---------------------------------------------------------------------------
# detect_file_type
# ---------------------------------------------------------------------------

class TestDetectFileType:
    """Tests for detect_file_type()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.file_detection_tools import detect_file_type
        self.fn = detect_file_type

    def test_returns_dict(self) -> None:
        path = _make_txt_file()
        try:
            result = self.fn(path)
            assert isinstance(result, dict)
        finally:
            os.unlink(path)

    def test_has_required_keys(self) -> None:
        path = _make_txt_file()
        try:
            result = self.fn(path)
            for key in ("mime_type", "extension", "confidence", "method"):
                assert key in result, f"Missing key: {key}"
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_error(self) -> None:
        result = self.fn("/nonexistent/path/file.txt")
        assert isinstance(result, dict)
        assert "error" in result

    def test_custom_methods_param(self) -> None:
        path = _make_txt_file()
        try:
            result = self.fn(path, methods=["extension"])
            assert isinstance(result, dict)
        finally:
            os.unlink(path)

    def test_strategy_param(self) -> None:
        path = _make_txt_file()
        try:
            result = self.fn(path, strategy="fastest")
            assert isinstance(result, dict)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# batch_detect_file_types
# ---------------------------------------------------------------------------

class TestBatchDetectFileTypes:
    """Tests for batch_detect_file_types()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.file_detection_tools import batch_detect_file_types
        self.fn = batch_detect_file_types

    def test_returns_dict(self) -> None:
        path = _make_txt_file()
        try:
            result = self.fn(file_paths=[path])
            assert isinstance(result, dict)
        finally:
            os.unlink(path)

    def test_has_results_key(self) -> None:
        path = _make_txt_file()
        try:
            result = self.fn(file_paths=[path])
            assert "results" in result
        finally:
            os.unlink(path)

    def test_total_files_count(self) -> None:
        p1 = _make_txt_file()
        p2 = _make_png_file()
        try:
            result = self.fn(file_paths=[p1, p2])
            assert result.get("total_files") == 2
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_empty_list(self) -> None:
        result = self.fn(file_paths=[])
        assert isinstance(result, dict)
        assert result.get("total_files", 0) == 0

    def test_recursive_param(self) -> None:
        result = self.fn(directory="/tmp", recursive=False, pattern="*.txt")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# analyze_detection_accuracy
# ---------------------------------------------------------------------------

class TestAnalyzeDetectionAccuracy:
    """Tests for analyze_detection_accuracy()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.file_detection_tools import analyze_detection_accuracy
        self.fn = analyze_detection_accuracy

    def test_returns_dict(self) -> None:
        result = self.fn("/tmp")
        assert isinstance(result, dict)

    def test_has_expected_keys(self) -> None:
        result = self.fn("/tmp")
        # With files present, has detailed keys. With no files, has 'total_files'.
        assert "total_files" in result

    def test_recursive_param(self) -> None:
        result = self.fn("/tmp", recursive=False)
        assert isinstance(result, dict)

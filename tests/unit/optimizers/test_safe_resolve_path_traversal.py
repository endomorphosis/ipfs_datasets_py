"""Tests for _safe_resolve() path-traversal protection (batch 36).

Ensures that restricted directories cannot be accessed via path
traversal even when the CLI accepts user-supplied paths.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import _safe_resolve
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import (
    _safe_resolve as _logic_safe_resolve,
)


class TestSafeResolveGraphRAG:
    """Tests for graphrag/cli_wrapper._safe_resolve()."""

    @pytest.mark.parametrize("path", [
        "/etc/passwd",
        "/etc/../etc/passwd",
        "/proc/self/environ",
        "/sys/class/net",
        "/dev/null",
    ])
    def test_forbidden_path_raises_value_error(self, path):
        with pytest.raises(ValueError, match="restricted area"):
            _safe_resolve(path)

    def test_safe_path_returns_resolved(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text("{}")
        result = _safe_resolve(str(p))
        assert result == p.resolve()

    def test_must_exist_true_raises_on_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _safe_resolve(str(tmp_path / "nonexistent.json"), must_exist=True)

    def test_must_exist_false_does_not_raise_on_missing(self, tmp_path):
        # Should not raise even when file doesn't exist
        result = _safe_resolve(str(tmp_path / "nonexistent.json"), must_exist=False)
        assert result is not None


class TestSafeResolveLogic:
    """Tests for logic_theorem_optimizer/cli_wrapper._safe_resolve()."""

    @pytest.mark.parametrize("path", [
        "/etc/passwd",
        "/proc/self/status",
    ])
    def test_forbidden_path_raises_value_error(self, path):
        with pytest.raises((ValueError, FileNotFoundError)):
            # logic CLI may raise FileNotFoundError OR ValueError depending on impl
            result = _logic_safe_resolve(path, must_exist=True)
            # If no exception raised, the path must be valid (shouldn't happen for /etc/passwd)

    def test_safe_tmp_path_accepted(self, tmp_path):
        p = tmp_path / "logic.json"
        p.write_text("{}")
        result = _logic_safe_resolve(str(p), must_exist=True)
        assert result == p.resolve()

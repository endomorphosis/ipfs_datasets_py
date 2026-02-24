"""Tests for typed exception handling in logging audit helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.common.logging_audit import LoggingAuditor


def test_audit_file_handles_typed_os_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "sample.py"
    file_path.write_text("def f():\n    return 1\n")

    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no read")),
    )

    result = LoggingAuditor(root_dir=str(tmp_path)).audit_file(file_path)
    assert result.issues
    assert "Could not read file:" in result.issues[0]


def test_audit_file_does_not_swallow_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "sample.py"
    file_path.write_text("def f():\n    return 1\n")

    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        LoggingAuditor(root_dir=str(tmp_path)).audit_file(file_path)

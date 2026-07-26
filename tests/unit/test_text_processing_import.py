from __future__ import annotations

import builtins
import importlib.util
import logging
from pathlib import Path


def test_missing_nltk_fallback_does_not_write_to_stdout(
    capsys,
    caplog,
    monkeypatch,
) -> None:
    module_path = (
        Path(__file__).resolve().parents[2]
        / "ipfs_datasets_py"
        / "utils"
        / "text_processing.py"
    )
    original_import = builtins.__import__

    def without_nltk(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "nltk" or name.startswith("nltk."):
            raise ImportError("test blocks optional NLTK")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_nltk)
    spec = importlib.util.spec_from_file_location(
        "_text_processing_without_nltk",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with caplog.at_level(logging.INFO):
        spec.loader.exec_module(module)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert module.HAVE_NLTK is False
    assert "using basic text processing" in caplog.text

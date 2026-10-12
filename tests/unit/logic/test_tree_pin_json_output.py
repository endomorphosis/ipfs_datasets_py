"""Tree diagnostics preserve JSON stdout without weakening checkout pins."""
import importlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import AutoformalSession, tree_pin


def test_real_logic_imports_leave_stdout_for_one_json_document(capsys):
    resolved = tree_pin.require_workspace_logic_tree()
    print(json.dumps({"schema": "authored-tree-observation@1", "paths": resolved}))
    captured = capsys.readouterr()
    assert json.loads(captured.out)["paths"] == resolved
    assert len(captured.out.splitlines()) == 1
    assert captured.err.startswith("logic tree pin compiler=")
    assert set(resolved) == {"compiler", "decompiler", "parser"}
    assert all(tree_pin.workspace_root() in Path(path).parents for path in resolved.values())


def test_repeated_autoformal_sessions_only_write_diagnostics_to_stderr(capsys):
    for _ in range(3):
        AutoformalSession()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len([line for line in captured.err.splitlines() if line.startswith("logic tree pin ")]) == 3


@pytest.mark.parametrize("label", ["compiler", "decompiler", "parser"])
def test_real_loaded_foreign_tree_module_still_refuses_before_success_output(tmp_path, monkeypatch, capsys, label):
    module = importlib.import_module(dict(tree_pin._MODULES)[label])
    outside = tmp_path / (label + ".py")
    outside.write_text("# existing file in a different checkout\n")
    monkeypatch.setattr(module, "__file__", str(outside))
    with pytest.raises(tree_pin.LogicTreePinError, match="Resolved outside that tree"):
        tree_pin.require_workspace_logic_tree()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""

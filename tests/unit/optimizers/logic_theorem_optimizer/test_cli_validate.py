"""CLI tests for logic-theorem-optimizer validate command.

Tests --input (JSON), --from-file (JSON), and --from-file (YAML) paths.
Monkeypatches LogicTheoremOptimizer to avoid requiring z3.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI
import ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper as _cw

_LOGIC_DATA = {
    "statements": ["All humans are mortal", "Socrates is human"],
    "domain": "general",
}


def _make_optimizer_class(valid: bool = True):
    mock_cls = MagicMock()
    instance = MagicMock()
    instance.validate.return_value = valid
    mock_cls.return_value = instance
    return mock_cls


@pytest.fixture
def logic_json(tmp_path: Path) -> Path:
    p = tmp_path / "logic.json"
    p.write_text(json.dumps(_LOGIC_DATA))
    return p


@pytest.fixture
def logic_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "logic.yaml"
    p.write_text("statements:\n  - All humans are mortal\n  - Socrates is human\ndomain: general\n")
    return p


class TestCmdValidate:
    """Tests for LogicOptimizerCLI.cmd_validate()."""

    @pytest.fixture
    def cli(self):
        return LogicOptimizerCLI()

    @pytest.fixture(autouse=True)
    def patch_optimizer(self, monkeypatch):
        monkeypatch.setattr(_cw, "LogicTheoremOptimizer", _make_optimizer_class(valid=True))

    def test_input_json_returns_zero(self, cli, logic_json):
        code = cli.run(["validate", "--input", str(logic_json)])
        assert code == 0

    def test_from_file_json_returns_zero(self, cli, logic_json):
        code = cli.run(["validate", "--from-file", str(logic_json)])
        assert code == 0

    def test_from_file_yaml_returns_zero(self, cli, logic_yaml):
        pytest.importorskip("yaml", reason="PyYAML not installed")
        code = cli.run(["validate", "--from-file", str(logic_yaml)])
        assert code == 0

    def test_input_missing_file_returns_one(self, cli, tmp_path):
        code = cli.run(["validate", "--input", str(tmp_path / "nonexistent.json")])
        assert code == 1

    def test_from_file_missing_file_returns_one(self, cli, tmp_path):
        code = cli.run(["validate", "--from-file", str(tmp_path / "nonexistent.json")])
        assert code == 1

    def test_validation_failure_returns_one(self, cli, logic_json, monkeypatch):
        monkeypatch.setattr(_cw, "LogicTheoremOptimizer", _make_optimizer_class(valid=False))
        code = cli.run(["validate", "--input", str(logic_json)])
        assert code == 1

    def test_check_consistency_flag_accepted(self, cli, logic_json):
        code = cli.run(["validate", "--input", str(logic_json), "--check-consistency"])
        assert code == 0

    def test_check_completeness_flag_accepted(self, cli, logic_json):
        code = cli.run(["validate", "--input", str(logic_json), "--check-completeness"])
        assert code == 0

    @pytest.mark.parametrize("domain", ["legal", "medical", "financial", "technical", "general"])
    def test_domain_flag_accepted(self, cli, logic_json, domain):
        code = cli.run(["validate", "--input", str(logic_json), "--domain", domain])
        assert code == 0

    def test_domain_default_is_general(self, cli, logic_json, capsys):
        cli.run(["validate", "--input", str(logic_json)])
        out = capsys.readouterr().out
        assert "general" in out

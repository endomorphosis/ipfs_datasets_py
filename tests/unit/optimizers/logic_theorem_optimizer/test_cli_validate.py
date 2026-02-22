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


def _write_logic(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


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

    def test_validate_domain_legal_passes_domain_to_context(self, cli, tmp_path):
        data = {
            "statements": ["The contract shall bind the defendant."],
            "domain": "legal",
        }
        logic_path = _write_logic(tmp_path, "legal.json", data)
        code = cli.run(["validate", "--input", str(logic_path), "--domain", "legal"])
        assert code == 0
        call_args = _cw.LogicTheoremOptimizer.return_value.validate.call_args
        context = call_args.args[1]
        assert getattr(context, "domain", None) == "legal"

    def test_validate_domain_medical_passes_domain_to_context(self, cli, tmp_path):
        data = {
            "statements": ["The patient diagnosis requires treatment."],
            "domain": "medical",
        }
        logic_path = _write_logic(tmp_path, "medical.json", data)
        code = cli.run(["validate", "--input", str(logic_path), "--domain", "medical"])
        assert code == 0
        call_args = _cw.LogicTheoremOptimizer.return_value.validate.call_args
        context = call_args.args[1]
        assert getattr(context, "domain", None) == "medical"

    @pytest.mark.parametrize("domain", ["legal", "medical", "financial", "technical", "general"])
    def test_domain_flag_accepted(self, cli, logic_json, domain):
        code = cli.run(["validate", "--input", str(logic_json), "--domain", domain])
        if domain == "general":
            assert code == 0
        else:
            assert code == 1

    def test_domain_default_is_general(self, cli, logic_json, capsys):
        cli.run(["validate", "--input", str(logic_json)])
        out = capsys.readouterr().out
        assert "general" in out

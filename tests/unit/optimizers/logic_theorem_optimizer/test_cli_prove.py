"""CLI tests for logic-theorem-optimizer prove command.

Tests that the `prove` command works end-to-end on a trivial theorem.
Uses monkeypatching to avoid requiring z3 to be installed.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI
import ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper as _cw


def _mock_optimizer_class():
    """Return a mock LogicTheoremOptimizer class that always succeeds."""
    mock_cls = MagicMock()
    instance = MagicMock()
    # validate_statements returns all_valid=True
    instance.validate_statements.return_value = SimpleNamespace(
        all_valid=True,
        provers_used=["z3"],
        errors=[],
        details={},
    )
    mock_cls.return_value = instance
    return mock_cls


class TestCmdProve:
    """Tests for LogicOptimizerCLI.cmd_prove()."""

    @pytest.fixture
    def cli(self):
        return LogicOptimizerCLI()

    @pytest.fixture(autouse=True)
    def patch_optimizer(self, monkeypatch):
        monkeypatch.setattr(_cw, "LogicTheoremOptimizer", _mock_optimizer_class())

    def test_prove_trivial_theorem_returns_zero(self, cli):
        code = cli.run([
            "prove",
            "--theorem", "All men are mortal",
            "--goal", "Socrates is mortal",
            "--premises", "Socrates is a man",
        ])
        assert code == 0

    def test_prove_prints_theorem(self, cli, capsys):
        cli.run([
            "prove",
            "--theorem", "All men are mortal",
            "--goal", "Socrates is mortal",
        ])
        out = capsys.readouterr().out
        assert "All men are mortal" in out

    def test_prove_prints_goal(self, cli, capsys):
        cli.run([
            "prove",
            "--theorem", "All cats have tails",
            "--goal", "Tom has a tail",
        ])
        out = capsys.readouterr().out
        assert "Tom has a tail" in out

    def test_prove_outputs_json_on_success(self, cli, tmp_path):
        out_path = tmp_path / "proof.json"
        code = cli.run([
            "prove",
            "--theorem", "P implies Q",
            "--goal", "Q",
            "--output", str(out_path),
        ])
        assert code == 0
        assert out_path.exists()
        payload = json.loads(out_path.read_text())
        assert payload["proven"] is True
        assert "theorem" in payload
        assert "elapsed_seconds" in payload

    def test_prove_missing_theorem_and_goal_returns_nonzero(self, cli):
        code = cli.run(["prove"])
        assert code != 0

    def test_prove_missing_goal_returns_nonzero(self, cli):
        code = cli.run(["prove", "--theorem", "Some theorem"])
        assert code != 0

    def test_prove_failed_theorem_returns_nonzero(self, cli, monkeypatch):
        mock_cls = MagicMock()
        instance = MagicMock()
        instance.validate_statements.return_value = SimpleNamespace(
            all_valid=False,
            provers_used=["z3"],
            errors=["Contradiction found"],
            details={},
        )
        mock_cls.return_value = instance
        monkeypatch.setattr(_cw, "LogicTheoremOptimizer", mock_cls)

        code = cli.run([
            "prove",
            "--theorem", "False theorem",
            "--goal", "Impossible conclusion",
        ])
        assert code != 0

    def test_prove_from_json_file(self, cli, tmp_path):
        data = {
            "theorem": "All dogs are animals",
            "premises": ["Rex is a dog"],
            "goal": "Rex is an animal",
        }
        json_file = tmp_path / "theorem.json"
        json_file.write_text(json.dumps(data))

        code = cli.run(["prove", "--from-file", str(json_file)])
        assert code == 0

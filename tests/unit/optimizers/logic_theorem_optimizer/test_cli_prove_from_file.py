"""Unit tests for the logic-theorem-optimizer CLI prove command.

Tests:
- --from-file JSON loading
- --from-file YAML loading
- Missing --theorem/--goal error
- File not found error
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cli():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import (
        LogicOptimizerCLI,
    )
    return LogicOptimizerCLI()


def _make_args(**kwargs):
    args = types.SimpleNamespace(
        theorem=None,
        premises=None,
        goal=None,
        from_file=None,
        prover="z3",
        timeout=5,
        output=None,
    )
    for k, v in kwargs.items():
        setattr(args, k, v)
    return args


def _mock_optimizer():
    """Context manager that patches the optimizer so cmd_prove doesn't need a real prover."""
    mock_result = MagicMock()
    mock_result.all_valid = True
    mock_result.valid = True
    mock_result.provers_used = ["mock"]
    mock_result.errors = []

    mock_opt = MagicMock()
    mock_opt.validate_statements.return_value = mock_result

    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import cli_wrapper as _cw
        ctx1 = patch.object(_cw, "LogicTheoremOptimizer", return_value=mock_opt)
        ctx2 = patch.object(_cw, "OptimizationContext", return_value=MagicMock())
        return ctx1, ctx2
    except AttributeError:
        return patch("builtins.open"), patch("builtins.open")


class TestCmdProveFromFile:
    def test_from_json_file_sets_theorem_goal_premises(self, cli, tmp_path):
        data = {"theorem": "A implies B", "premises": ["A"], "goal": "B"}
        f = tmp_path / "proof.json"
        f.write_text(json.dumps(data))

        args = _make_args(from_file=str(f))

        ctx1, ctx2 = _mock_optimizer()
        with ctx1, ctx2:
            cli.cmd_prove(args)

        assert args.theorem == "A implies B"
        assert args.goal == "B"
        assert args.premises == ["A"]

    def test_from_file_not_found_returns_1(self, cli):
        args = _make_args(from_file="/nonexistent/path.json")
        result = cli.cmd_prove(args)
        assert result == 1

    def test_missing_theorem_and_goal_returns_1(self, cli):
        args = _make_args(theorem=None, goal=None)
        result = cli.cmd_prove(args)
        assert result == 1

    def test_missing_goal_returns_1(self, cli):
        args = _make_args(theorem="Hypothesis", goal=None)
        result = cli.cmd_prove(args)
        assert result == 1

    def test_missing_theorem_returns_1(self, cli):
        args = _make_args(theorem=None, goal="Conclusion")
        result = cli.cmd_prove(args)
        assert result == 1

    def test_invalid_json_file_returns_1(self, cli, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("this is not json{{{{")
        args = _make_args(from_file=str(f))
        result = cli.cmd_prove(args)
        assert result == 1

    def test_json_file_not_a_dict_returns_1(self, cli, tmp_path):
        f = tmp_path / "list.json"
        f.write_text(json.dumps(["a", "b", "c"]))
        args = _make_args(from_file=str(f))
        result = cli.cmd_prove(args)
        assert result == 1

    def test_from_yaml_file_sets_theorem_and_goal(self, cli, tmp_path):
        pytest.importorskip("yaml")
        import yaml as _yaml
        data = {"theorem": "P and Q", "premises": [], "goal": "P"}
        f = tmp_path / "proof.yaml"
        f.write_text(_yaml.dump(data))

        args = _make_args(from_file=str(f))

        ctx1, ctx2 = _mock_optimizer()
        with ctx1, ctx2:
            cli.cmd_prove(args)

        assert args.theorem == "P and Q"
        assert args.goal == "P"


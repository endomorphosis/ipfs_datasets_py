"""CLI tests for graphrag-optimizer generate command on a fixture text file."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI


FIXTURE_TEXT = """
Alice is a software engineer at Acme Corporation.
Bob manages Alice and owns several patents.
The Widget product belongs to the R&D department.
Acme Corporation causes significant innovation in the industry.
"""


class TestCmdGenerate:
    """Tests for GraphRAGOptimizerCLI.cmd_generate() on a fixture text file."""

    @pytest.fixture
    def cli(self):
        return GraphRAGOptimizerCLI()

    @pytest.fixture
    def input_file(self, tmp_path):
        p = tmp_path / "fixture.txt"
        p.write_text(FIXTURE_TEXT)
        return p

    def test_generate_returns_zero_on_success(self, cli, input_file, capsys):
        code = cli.run([
            "generate",
            "--input", str(input_file),
            "--domain", "general",
            "--strategy", "rule_based",
            "--format", "json",
        ])
        assert code == 0

    def test_generate_prints_entity_count(self, cli, input_file, capsys):
        cli.run([
            "generate",
            "--input", str(input_file),
            "--domain", "general",
            "--strategy", "rule_based",
            "--format", "json",
        ])
        out = capsys.readouterr().out
        assert "Entities:" in out

    def test_generate_prints_relationship_count(self, cli, input_file, capsys):
        cli.run([
            "generate",
            "--input", str(input_file),
            "--domain", "general",
            "--strategy", "rule_based",
            "--format", "json",
        ])
        out = capsys.readouterr().out
        assert "Relationships:" in out

    def test_generate_with_output_writes_file(self, cli, input_file, tmp_path):
        out_path = tmp_path / "output.json"
        code = cli.run([
            "generate",
            "--input", str(input_file),
            "--domain", "general",
            "--strategy", "rule_based",
            "--format", "json",
            "--output", str(out_path),
        ])
        assert code == 0
        assert out_path.exists()
        payload = json.loads(out_path.read_text())
        assert "entities" in payload
        assert "relationships" in payload

    def test_generate_output_has_quality_score(self, cli, input_file, tmp_path):
        out_path = tmp_path / "output.json"
        cli.run([
            "generate",
            "--input", str(input_file),
            "--domain", "general",
            "--strategy", "rule_based",
            "--format", "json",
            "--output", str(out_path),
        ])
        payload = json.loads(out_path.read_text())
        assert "quality_score" in payload
        assert 0.0 <= payload["quality_score"] <= 1.0

    def test_generate_missing_input_returns_nonzero(self, cli, tmp_path):
        code = cli.run([
            "generate",
            "--input", str(tmp_path / "nonexistent.txt"),
            "--domain", "general",
            "--strategy", "rule_based",
            "--format", "json",
        ])
        assert code != 0

    def test_generate_hybrid_strategy(self, cli, input_file):
        code = cli.run([
            "generate",
            "--input", str(input_file),
            "--domain", "general",
            "--strategy", "hybrid",
            "--format", "json",
        ])
        assert code == 0

"""Tests for _safe_resolve() path-traversal protection (batch 36).

Ensures that restricted directories cannot be accessed via path
traversal even when the CLI accepts user-supplied paths.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import _safe_resolve
from ipfs_datasets_py.optimizers.graphrag.exceptions import PathResolutionError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import (
    LogicOptimizerCLI,
    _safe_resolve as _logic_safe_resolve,
)
from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI


class TestSafeResolveGraphRAG:
    """Tests for graphrag/cli_wrapper._safe_resolve()."""

    def test_non_string_path_raises_type_error(self):
        with pytest.raises(TypeError, match="path_str must be a string"):
            _safe_resolve(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("path", ["", "   "])
    def test_empty_path_raises_value_error(self, path):
        with pytest.raises(ValueError, match="path_str must be a non-empty string"):
            _safe_resolve(path)

    @pytest.mark.parametrize("path", [
        "/etc/passwd",
        "/etc/../etc/passwd",
        "/proc/self/environ",
        "/sys/class/net",
        "/dev/null",
    ])
    def test_forbidden_path_raises_value_error(self, path):
        with pytest.raises(PathResolutionError, match="restricted area"):
            _safe_resolve(path)

    def test_safe_path_returns_resolved(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text("{}")
        result = _safe_resolve(str(p))
        assert result == p.resolve()

    def test_must_exist_true_raises_on_missing(self, tmp_path):
        with pytest.raises(PathResolutionError):
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


def test_graphrag_validate_restricted_output_path_returns_nonzero(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag import cli_wrapper as graphrag_cli_wrapper

    ontology_path = tmp_path / "ontology.json"
    ontology_path.write_text(
        json.dumps({"entities": [{"id": "e1", "type": "Thing", "text": "Alice"}], "relationships": []}),
        encoding="utf-8",
    )

    class _StubConsistency:
        is_consistent = True
        prover_used = "stub"
        contradictions = []

        def to_dict(self):
            return {"is_consistent": True, "prover_used": self.prover_used, "contradictions": []}

    class _StubValidator:
        def check_consistency(self, ontology):
            return _StubConsistency()

    monkeypatch.setattr(graphrag_cli_wrapper, "LogicValidator", lambda *a, **k: _StubValidator())
    cli = GraphRAGOptimizerCLI()
    code = cli.run(["validate", "--input", str(ontology_path), "--output", "/etc/passwd"])
    assert code == 1


def test_graphrag_generate_restricted_output_path_returns_nonzero(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag import cli_wrapper as graphrag_cli_wrapper

    input_path = tmp_path / "input.txt"
    input_path.write_text("Alice works at Acme.", encoding="utf-8")

    class _StubGenerator:
        def generate_ontology(self, data, context):
            return {
                "entities": [{"id": "e1", "type": "Thing", "text": "Alice"}],
                "relationships": [],
                "metadata": {"confidence": 0.9},
            }

    class _StubScore:
        overall = 0.75

    class _StubCritic:
        def evaluate_ontology(self, ontology, context, source_data):
            return _StubScore()

    monkeypatch.setattr(graphrag_cli_wrapper, "OntologyGenerator", lambda *a, **k: _StubGenerator())
    monkeypatch.setattr(graphrag_cli_wrapper, "OntologyCritic", lambda *a, **k: _StubCritic())

    cli = GraphRAGOptimizerCLI()
    code = cli.run(
        [
            "generate",
            "--input",
            str(input_path),
            "--domain",
            "general",
            "--strategy",
            "rule_based",
            "--format",
            "json",
            "--output",
            "/etc/passwd",
        ]
    )
    assert code == 1


def test_graphrag_optimize_restricted_output_path_returns_nonzero(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.graphrag import cli_wrapper as graphrag_cli_wrapper

    input_path = tmp_path / "input.txt"
    input_path.write_text("This agreement is between parties.", encoding="utf-8")

    class _StubScore:
        overall = 0.8

        def to_dict(self):
            return {"overall": self.overall}

    class _StubResult:
        critic_score = _StubScore()
        validation_result = None
        num_rounds = 1
        converged = True
        time_elapsed = 0.01
        metadata = {}
        ontology = {"entities": [], "relationships": []}

    class _StubSession:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, data, context):
            return _StubResult()

    monkeypatch.setattr(graphrag_cli_wrapper, "OntologyGenerator", lambda *a, **k: object())
    monkeypatch.setattr(graphrag_cli_wrapper, "OntologyMediator", lambda *a, **k: object())
    monkeypatch.setattr(graphrag_cli_wrapper, "OntologyCritic", lambda *a, **k: object())
    monkeypatch.setattr(graphrag_cli_wrapper, "LogicValidator", lambda *a, **k: object())
    monkeypatch.setattr(graphrag_cli_wrapper, "OntologySession", _StubSession)

    cli = GraphRAGOptimizerCLI()
    code = cli.run(
        [
            "optimize",
            "--input",
            str(input_path),
            "--cycles",
            "1",
            "--target",
            "all",
            "--output",
            "/etc/passwd",
        ]
    )
    assert code == 1


def test_logic_extract_restricted_output_path_returns_nonzero(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import cli_wrapper as logic_cli_wrapper

    input_path = tmp_path / "text.txt"
    input_path.write_text("All humans are mortal.", encoding="utf-8")

    class _StubExtractor:
        def extract(self, text, context):
            return SimpleNamespace(formulas=["Human(x)->Mortal(x)"], confidence=0.9, metadata={})

    monkeypatch.setattr(logic_cli_wrapper, "LogicExtractor", lambda *a, **k: _StubExtractor())
    cli = LogicOptimizerCLI()
    code = cli.run(["extract", "--input", str(input_path), "--output", "/etc/passwd"])
    assert code == 1

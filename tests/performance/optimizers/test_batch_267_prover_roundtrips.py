"""Batch 267: Prover round-trip profiling tests.

Validates the profiling script for ProverIntegrationAdapter round-trips.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))


def _load_profile_module():
    """Load the profile module under test."""
    spec = __import__("importlib.util").util.spec_from_file_location(
        "profile_batch_267",
        pathlib.Path(__file__).parent / "profile_batch_267_prover_roundtrips.py",
    )
    assert spec and spec.loader
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProverRoundtripProfilingScript:
    """Verify profiling script structure and execution."""

    def test_profile_script_exists(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_267_prover_roundtrips.py"
        assert script_path.exists(), "Profile script should exist"

    def test_profile_script_imports(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_267_prover_roundtrips.py"
        content = script_path.read_text(encoding="utf-8")
        assert "import cProfile" in content
        assert "profile_prover_roundtrips" in content
        assert "ProverIntegrationAdapter" in content

    def test_profile_execution_writes_outputs(self, tmp_path):
        module = _load_profile_module()

        metrics = module.profile_prover_roundtrips(
            statement_count=12,
            delay_ms=0.0,
            output_dir=tmp_path,
        )

        assert metrics["statement_count"] == 12
        assert metrics["elapsed_ms"] > 0
        assert metrics["avg_ms"] > 0
        assert metrics["valid_count"] == 12

        prof_file = tmp_path / "profile_batch_267_prover_roundtrips.prof"
        txt_file = tmp_path / "profile_batch_267_prover_roundtrips.txt"

        assert prof_file.exists(), "Profile .prof output should exist"
        assert txt_file.exists(), "Profile .txt output should exist"
        assert txt_file.read_text(encoding="utf-8")

    def test_rejects_invalid_inputs(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="count must be >= 0"):
            module.build_statements(-1)
        with pytest.raises(ValueError, match="statement_count must be > 0"):
            module.profile_prover_roundtrips(statement_count=0, output_dir=tmp_path)
        with pytest.raises(ValueError, match="delay_ms must be >= 0"):
            module.profile_prover_roundtrips(statement_count=1, delay_ms=-1.0, output_dir=tmp_path)

    def test_rejects_invalid_types(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="count must be an int"):
            module.build_statements("3")
        with pytest.raises(TypeError, match="statement_count must be an int"):
            module.profile_prover_roundtrips(statement_count=2.5, output_dir=tmp_path)
        with pytest.raises(TypeError, match="delay_ms must be a number"):
            module.profile_prover_roundtrips(statement_count=1, delay_ms="0", output_dir=tmp_path)


@pytest.mark.llm
class TestProverRoundtripProfilingSmoke:
    """Lightweight smoke checks for profiling metrics."""

    def test_profile_metrics_keys(self, tmp_path):
        module = _load_profile_module()

        metrics = module.profile_prover_roundtrips(
            statement_count=8,
            delay_ms=0.0,
            output_dir=tmp_path,
        )

        assert set(metrics.keys()) == {
            "statement_count",
            "elapsed_ms",
            "avg_ms",
            "valid_count",
        }

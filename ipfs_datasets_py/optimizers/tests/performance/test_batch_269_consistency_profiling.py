"""Batch 269: Consistency profiling tests.

Validates the profiling script for consistency cycle detection.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[5]))


class TestConsistencyProfilingScript:
    """Verify profiling script structure and execution."""

    def test_profile_script_exists(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_269_consistency_cycles.py"
        assert script_path.exists(), "Profile script should exist"

    def test_profile_script_imports(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_269_consistency_cycles.py"
        content = script_path.read_text(encoding="utf-8")
        assert "import cProfile" in content
        assert "profile_consistency" in content
        assert "evaluate_consistency" in content

    def test_profile_execution_writes_outputs(self, tmp_path):
        spec = __import__("importlib.util").util.spec_from_file_location(
            "profile_batch_269",
            pathlib.Path(__file__).parent / "profile_batch_269_consistency_cycles.py",
        )
        module = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(module)

        metrics = module.profile_consistency(
            entity_count=120,
            relationship_count=200,
            with_cycle=True,
            output_dir=tmp_path,
        )

        assert metrics["entity_count"] == 120
        assert metrics["relationship_count"] == 200
        assert metrics["with_cycle"] is True
        assert metrics["elapsed_ms"] > 0

        prof_file = tmp_path / "profile_batch_269_consistency_cycles.prof"
        txt_file = tmp_path / "profile_batch_269_consistency_cycles.txt"

        assert prof_file.exists(), "Profile .prof output should exist"
        assert txt_file.exists(), "Profile .txt output should exist"
        assert txt_file.read_text(encoding="utf-8")


@pytest.mark.llm
class TestConsistencyProfilingSmoke:
    """Lightweight smoke checks for profiling metrics."""

    def test_profile_metrics_keys(self, tmp_path):
        spec = __import__("importlib.util").util.spec_from_file_location(
            "profile_batch_269",
            pathlib.Path(__file__).parent / "profile_batch_269_consistency_cycles.py",
        )
        module = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(module)

        metrics = module.profile_consistency(
            entity_count=80,
            relationship_count=120,
            with_cycle=False,
            output_dir=tmp_path,
        )

        assert set(metrics.keys()) == {
            "entity_count",
            "relationship_count",
            "with_cycle",
            "elapsed_ms",
            "score",
        }

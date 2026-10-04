"""Batch 266: Query optimizer profiling tests.

Validates the profiling script for UnifiedGraphRAGQueryOptimizer and ensures
basic outputs are generated without heavy runtimes.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))


def _load_profile_module():
    """Load the profile module under test."""
    spec = __import__("importlib.util").util.spec_from_file_location(
        "profile_batch_266",
        pathlib.Path(__file__).parent / "profile_batch_266_query_optimizer.py",
    )
    assert spec and spec.loader
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestQueryOptimizerProfilingScript:
    """Verify profiling script structure and execution."""

    def test_profile_script_exists(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_266_query_optimizer.py"
        assert script_path.exists(), "Profile script should exist"

    def test_profile_script_imports(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_266_query_optimizer.py"
        content = script_path.read_text(encoding="utf-8")
        assert "import cProfile" in content
        assert "profile_query_optimizer" in content
        assert "UnifiedGraphRAGQueryOptimizer" in content

    def test_profile_execution_writes_outputs(self, tmp_path):
        module = _load_profile_module()

        metrics = module.profile_query_optimizer(
            query_count=12,
            vector_size=64,
            warmup_count=4,
            output_dir=tmp_path,
        )

        assert metrics["query_count"] == 12
        assert metrics["elapsed_ms"] > 0
        assert metrics["avg_ms"] > 0
        assert metrics["plan_count"] == 12

        prof_file = tmp_path / "profile_batch_266_query_optimizer.prof"
        txt_file = tmp_path / "profile_batch_266_query_optimizer.txt"

        assert prof_file.exists(), "Profile .prof output should exist"
        assert txt_file.exists(), "Profile .txt output should exist"
        assert txt_file.read_text(encoding="utf-8")

    def test_build_queries_rejects_invalid_inputs(self):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="count must be >= 0"):
            module.build_queries(-1)
        with pytest.raises(ValueError, match="vector_size must be > 0"):
            module.build_queries(1, vector_size=0)
        with pytest.raises(ValueError, match="max_depth must be > 0"):
            module.build_queries(1, max_depth=0)

    def test_build_queries_rejects_invalid_types(self):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="count must be an int"):
            module.build_queries("3")
        with pytest.raises(TypeError, match="vector_size must be an int"):
            module.build_queries(1, vector_size=1.5)
        with pytest.raises(TypeError, match="max_depth must be an int"):
            module.build_queries(1, max_depth=True)

    def test_profile_rejects_invalid_inputs(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="query_count must be > 0"):
            module.profile_query_optimizer(query_count=0, output_dir=tmp_path)
        with pytest.raises(ValueError, match="vector_size must be > 0"):
            module.profile_query_optimizer(query_count=1, vector_size=0, output_dir=tmp_path)
        with pytest.raises(ValueError, match="warmup_count must be >= 0"):
            module.profile_query_optimizer(query_count=1, warmup_count=-1, output_dir=tmp_path)

    def test_profile_rejects_invalid_types(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="query_count must be an int"):
            module.profile_query_optimizer(query_count=1.2, output_dir=tmp_path)
        with pytest.raises(TypeError, match="vector_size must be an int"):
            module.profile_query_optimizer(query_count=1, vector_size="64", output_dir=tmp_path)
        with pytest.raises(TypeError, match="warmup_count must be an int"):
            module.profile_query_optimizer(query_count=1, warmup_count=False, output_dir=tmp_path)


@pytest.mark.llm
class TestQueryOptimizerProfilingSmoke:
    """Lightweight smoke checks for profiling metrics."""

    def test_profile_metrics_keys(self, tmp_path):
        module = _load_profile_module()

        metrics = module.profile_query_optimizer(
            query_count=8,
            vector_size=48,
            warmup_count=2,
            output_dir=tmp_path,
        )

        assert set(metrics.keys()) == {
            "query_count",
            "elapsed_ms",
            "avg_ms",
            "plan_count",
        }

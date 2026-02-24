"""Batch 264: _extract_rule_based() Profiling Tests

Validates the profiling script for rule-based extraction and ensures
basic outputs are generated without heavy runtimes.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[5]))


def _load_profile_module():
    """Load the profile module under test."""
    spec = __import__("importlib.util").util.spec_from_file_location(
        "profile_batch_264",
        pathlib.Path(__file__).parent / "profile_batch_264_extract_rule_based.py",
    )
    assert spec and spec.loader
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRuleBasedProfilingScript:
    """Verify profiling script structure and execution."""

    def test_profile_script_exists(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_264_extract_rule_based.py"
        assert script_path.exists(), "Profile script should exist"

    def test_profile_script_imports(self):
        script_path = pathlib.Path(__file__).parent / "profile_batch_264_extract_rule_based.py"
        content = script_path.read_text(encoding="utf-8")
        assert "import cProfile" in content
        assert "profile_extract_rule_based" in content
        assert "_extract_rule_based" in content

    def test_generate_text_size(self):
        module = _load_profile_module()

        text = module.generate_legal_text(target_tokens=400)
        token_count = len(text.split())
        assert 300 <= token_count <= 520, f"Generated {token_count} tokens"

    def test_profile_execution_writes_outputs(self, tmp_path):
        module = _load_profile_module()

        metrics = module.profile_extract_rule_based(
            target_tokens=300,
            warmup_tokens=120,
            output_dir=tmp_path,
        )

        assert metrics["token_count"] >= 200
        assert metrics["elapsed_ms"] > 0

        prof_file = tmp_path / "profile_batch_264_extract_rule_based.prof"
        txt_file = tmp_path / "profile_batch_264_extract_rule_based.txt"

        assert prof_file.exists(), "Profile .prof output should exist"
        assert txt_file.exists(), "Profile .txt output should exist"
        assert txt_file.read_text(encoding="utf-8")

    def test_rejects_invalid_token_inputs(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="target_tokens must be > 0"):
            module.generate_legal_text(target_tokens=0)
        with pytest.raises(ValueError, match="target_tokens must be > 0"):
            module.profile_extract_rule_based(target_tokens=0, output_dir=tmp_path)
        with pytest.raises(ValueError, match="warmup_tokens must be > 0"):
            module.profile_extract_rule_based(target_tokens=100, warmup_tokens=0, output_dir=tmp_path)


@pytest.mark.llm
class TestRuleBasedProfilingSmoke:
    """Lightweight smoke checks for profiling metrics."""

    def test_profile_metrics_keys(self, tmp_path):
        module = _load_profile_module()

        metrics = module.profile_extract_rule_based(
            target_tokens=220,
            warmup_tokens=120,
            output_dir=tmp_path,
        )

        assert set(metrics.keys()) == {
            "token_count",
            "elapsed_ms",
            "entity_count",
            "relationship_count",
        }

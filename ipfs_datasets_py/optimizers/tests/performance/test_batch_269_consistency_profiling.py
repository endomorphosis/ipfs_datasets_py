"""Batch 269: Consistency profiling tests.

Validates the profiling script for consistency cycle detection.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))


def _load_profile_module():
    spec = __import__("importlib.util").util.spec_from_file_location(
        "profile_batch_269",
        pathlib.Path(__file__).parent / "profile_batch_269_consistency_cycles.py",
    )
    module = __import__("importlib.util").util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
        module = _load_profile_module()

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

    def test_profile_rejects_zero_entity_count(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="entity_count must be > 0"):
            module.profile_consistency(
                entity_count=0,
                relationship_count=10,
                with_cycle=False,
                output_dir=tmp_path,
            )

    def test_profile_rejects_negative_relationship_count(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="relationship_count must be >= 0"):
            module.profile_consistency(
                entity_count=10,
                relationship_count=-1,
                with_cycle=False,
                output_dir=tmp_path,
            )

    def test_profile_rejects_invalid_count_types(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="entity_count must be an int"):
            module.profile_consistency(
                entity_count=True,
                relationship_count=5,
                with_cycle=False,
                output_dir=tmp_path,
            )
        with pytest.raises(TypeError, match="relationship_count must be an int"):
            module.profile_consistency(
                entity_count=5,
                relationship_count=2.2,
                with_cycle=False,
                output_dir=tmp_path,
            )

    def test_profile_rejects_non_boolean_with_cycle(self, tmp_path):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="with_cycle must be a bool"):
            module.profile_consistency(
                entity_count=5,
                relationship_count=5,
                with_cycle=1,
                output_dir=tmp_path,
            )

    def test_build_ontology_rejects_zero_entity_count(self):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="entity_count must be > 0"):
            module.build_ontology(entity_count=0, relationship_count=1)

    def test_build_ontology_rejects_negative_relationship_count(self):
        module = _load_profile_module()

        with pytest.raises(ValueError, match="relationship_count must be >= 0"):
            module.build_ontology(entity_count=1, relationship_count=-1)

    def test_build_ontology_rejects_invalid_count_types(self):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="entity_count must be an int"):
            module.build_ontology(entity_count=1.5, relationship_count=1)
        with pytest.raises(TypeError, match="relationship_count must be an int"):
            module.build_ontology(entity_count=5, relationship_count="3")

    def test_build_ontology_rejects_non_boolean_with_cycle(self):
        module = _load_profile_module()

        with pytest.raises(TypeError, match="with_cycle must be a bool"):
            module.build_ontology(entity_count=5, relationship_count=1, with_cycle="yes")

    def test_build_ontology_adds_cycle_edges_when_enabled(self):
        module = _load_profile_module()

        ontology = module.build_ontology(
            entity_count=5,
            relationship_count=2,
            with_cycle=True,
        )

        assert len(ontology["entities"]) == 5
        # Base relationships + injected 3-edge cycle
        assert len(ontology["relationships"]) == 5
        rel_ids = {rel["id"] for rel in ontology["relationships"]}
        assert {"cycle_1", "cycle_2", "cycle_3"}.issubset(rel_ids)

    def test_build_ontology_does_not_add_cycle_for_small_entity_count(self):
        module = _load_profile_module()

        ontology = module.build_ontology(
            entity_count=2,
            relationship_count=2,
            with_cycle=True,
        )

        rel_ids = {rel["id"] for rel in ontology["relationships"]}
        assert "cycle_1" not in rel_ids
        assert len(ontology["relationships"]) == 2


@pytest.mark.llm
class TestConsistencyProfilingSmoke:
    """Lightweight smoke checks for profiling metrics."""

    def test_profile_metrics_keys(self, tmp_path):
        module = _load_profile_module()

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

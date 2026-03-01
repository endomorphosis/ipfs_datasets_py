"""
Tests for the F-logic (Frame Logic) module.

Covers:
* Pure-Python data types (FLogicFrame, FLogicClass, FLogicOntology, FLogicQuery)
* ErgoAIWrapper in simulation mode (no binary required)
* FLogicSemanticOptimizer
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _load_flogic_optimizer():
    """Load flogic_optimizer directly, bypassing the broken optimizers.logic chain."""
    _MOD_NAME = "ipfs_datasets_py.optimizers.logic.flogic_optimizer"
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    _path = (
        Path(__file__).parent.parent.parent.parent
        / "ipfs_datasets_py"
        / "optimizers"
        / "logic"
        / "flogic_optimizer.py"
    )
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# FLogicFrame
# ---------------------------------------------------------------------------


class TestFLogicFrame:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicFrame
        self.FLogicFrame = FLogicFrame

    def test_to_ergo_string_no_methods(self):
        f = self.FLogicFrame("obj1")
        assert f.to_ergo_string() == "obj1"

    def test_to_ergo_string_scalar(self):
        f = self.FLogicFrame("obj1", scalar_methods={"age": "30"})
        s = f.to_ergo_string()
        assert "obj1[" in s
        assert "age -> 30" in s

    def test_to_ergo_string_set_method(self):
        f = self.FLogicFrame("proj", set_methods={"member": ["alice", "bob"]})
        s = f.to_ergo_string()
        assert "member ->>" in s
        assert "alice" in s
        assert "bob" in s

    def test_to_ergo_string_isa(self):
        f = self.FLogicFrame("rex", isa="Dog")
        s = f.to_ergo_string()
        assert ": Dog" in s

    def test_dataclass_defaults(self):
        f = self.FLogicFrame("x")
        assert f.scalar_methods == {}
        assert f.set_methods == {}
        assert f.isa is None
        assert f.isaset == []


# ---------------------------------------------------------------------------
# FLogicClass
# ---------------------------------------------------------------------------


class TestFLogicClass:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicClass
        self.FLogicClass = FLogicClass

    def test_to_ergo_string_subclass(self):
        cls = self.FLogicClass("Dog", superclasses=["Animal"])
        s = cls.to_ergo_string()
        assert "Dog :: Animal." in s

    def test_to_ergo_string_signature(self):
        cls = self.FLogicClass("Person", signature_methods={"age": "integer"})
        s = cls.to_ergo_string()
        assert "Person[age => integer]." in s

    def test_no_superclasses(self):
        cls = self.FLogicClass("Root")
        assert cls.to_ergo_string() == ""


# ---------------------------------------------------------------------------
# FLogicOntology
# ---------------------------------------------------------------------------


class TestFLogicOntology:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import (
            FLogicClass,
            FLogicFrame,
            FLogicOntology,
        )
        self.FLogicClass = FLogicClass
        self.FLogicFrame = FLogicFrame
        self.FLogicOntology = FLogicOntology

    def test_to_ergo_program_empty(self):
        onto = self.FLogicOntology("test")
        assert onto.to_ergo_program() == ""

    def test_to_ergo_program_full(self):
        onto = self.FLogicOntology("animals")
        onto.classes.append(self.FLogicClass("Animal"))
        onto.classes.append(self.FLogicClass("Dog", superclasses=["Animal"]))
        onto.frames.append(
            self.FLogicFrame("rex", scalar_methods={"name": '"Rex"'}, isa="Dog")
        )
        onto.rules.append("?X[barks -> true] :- ?X : Dog.")
        prog = onto.to_ergo_program()
        assert "Dog :: Animal." in prog
        assert 'rex[name -> "Rex"] : Dog.' in prog
        assert "barks -> true" in prog


# ---------------------------------------------------------------------------
# FLogicQuery
# ---------------------------------------------------------------------------


class TestFLogicQuery:
    def test_default_status(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import (
            FLogicQuery,
            FLogicStatus,
        )
        q = FLogicQuery(goal="?X : Dog")
        assert q.status == FLogicStatus.UNKNOWN
        assert q.bindings == []
        assert q.error_message is None


# ---------------------------------------------------------------------------
# ErgoAIWrapper (simulation mode)
# ---------------------------------------------------------------------------


class TestErgoAIWrapperSimulation:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ErgoAIWrapper
        from ipfs_datasets_py.logic.flogic.flogic_types import (
            FLogicClass,
            FLogicFrame,
            FLogicOntology,
            FLogicStatus,
        )
        self.ErgoAIWrapper = ErgoAIWrapper
        self.FLogicClass = FLogicClass
        self.FLogicFrame = FLogicFrame
        self.FLogicOntology = FLogicOntology
        self.FLogicStatus = FLogicStatus

    def _make_wrapper(self):
        # Force simulation mode by passing binary=None
        return self.ErgoAIWrapper(binary=None)

    def test_simulation_mode_flag(self):
        ergo = self._make_wrapper()
        assert ergo.simulation_mode is True

    def test_add_class_and_frame(self):
        ergo = self._make_wrapper()
        ergo.add_class(self.FLogicClass("Animal"))
        ergo.add_class(self.FLogicClass("Dog", superclasses=["Animal"]))
        ergo.add_frame(
            self.FLogicFrame("rex", scalar_methods={"name": '"Rex"'}, isa="Dog")
        )
        stats = ergo.get_statistics()
        assert stats["classes"] == 2
        assert stats["frames"] == 1

    def test_query_returns_unknown_in_simulation(self):
        ergo = self._make_wrapper()
        result = ergo.query("?X : Dog")
        assert result.status == self.FLogicStatus.UNKNOWN
        assert result.error_message is not None

    def test_batch_query(self):
        ergo = self._make_wrapper()
        results = ergo.batch_query(["?X : Dog", "?Y : Cat"])
        assert len(results) == 2
        for r in results:
            assert r.status == self.FLogicStatus.UNKNOWN

    def test_add_rule(self):
        ergo = self._make_wrapper()
        ergo.add_rule("?X[barks -> true] :- ?X : Dog.")
        assert ergo.get_statistics()["rules"] == 1

    def test_load_ontology(self):
        ergo = self._make_wrapper()
        onto = self.FLogicOntology("animals")
        onto.classes.append(self.FLogicClass("Animal"))
        ergo.load_ontology(onto)
        assert ergo.ontology.name == "animals"
        assert ergo.get_statistics()["classes"] == 1

    def test_get_program(self):
        ergo = self._make_wrapper()
        ergo.add_class(self.FLogicClass("Dog", superclasses=["Animal"]))
        ergo.add_frame(self.FLogicFrame("rex", isa="Dog"))
        prog = ergo.get_program()
        assert "Dog :: Animal." in prog
        assert "rex" in prog

    def test_get_statistics_keys(self):
        ergo = self._make_wrapper()
        stats = ergo.get_statistics()
        assert "ontology_name" in stats
        assert "simulation_mode" in stats
        assert "ergoai_binary" in stats
        assert stats["ergoai_binary"] is None


# ---------------------------------------------------------------------------
# ERGOAI_AVAILABLE module-level constant
# ---------------------------------------------------------------------------


def test_ergoai_available_is_bool():
    from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ERGOAI_AVAILABLE

    assert isinstance(ERGOAI_AVAILABLE, bool)


def test_ergoai_submodule_path_is_path():
    from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ERGOAI_SUBMODULE_PATH

    assert isinstance(ERGOAI_SUBMODULE_PATH, Path)


# ---------------------------------------------------------------------------
# Package-level lazy imports
# ---------------------------------------------------------------------------


def test_flogic_package_exports():
    import ipfs_datasets_py.logic.flogic as flogic

    expected = {
        "ErgoAIWrapper",
        "ERGOAI_AVAILABLE",
        "ERGOAI_SUBMODULE_PATH",
        "FLogicStatus",
        "FLogicFrame",
        "FLogicClass",
        "FLogicQuery",
        "FLogicOntology",
    }
    for name in expected:
        assert hasattr(flogic, name), f"flogic missing export: {name}"


def test_flogic_import_is_quiet():
    """Importing the flogic package must not emit warnings."""
    import warnings

    root = "ipfs_datasets_py.logic.flogic"
    for key in list(sys.modules.keys()):
        if key == root or key.startswith(root + "."):
            del sys.modules[key]

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        import ipfs_datasets_py.logic.flogic  # noqa: F401

    ipfs_warns = [
        w for w in rec if "ipfs_datasets_py" in (getattr(w, "filename", "") or "")
    ]
    assert ipfs_warns == [], [str(w.message) for w in ipfs_warns]


# ---------------------------------------------------------------------------
# FLogicSemanticOptimizer
# ---------------------------------------------------------------------------


class TestFLogicSemanticOptimizer:
    def setup_method(self):
        mod = _load_flogic_optimizer()
        self.FLogicOptimizerConfig = mod.FLogicOptimizerConfig
        self.FLogicSemanticOptimizer = mod.FLogicSemanticOptimizer

    def _optimizer(self, threshold=0.80):
        cfg = self.FLogicOptimizerConfig(similarity_threshold=threshold)
        return self.FLogicSemanticOptimizer(config=cfg)

    def test_identical_embeddings_pass(self):
        opt = self._optimizer(threshold=0.85)
        emb = [0.1, 0.2, 0.3]
        result = opt.evaluate("src", "decoded", emb, emb)
        assert abs(result.similarity_score - 1.0) < 1e-9
        assert result.passed is True
        assert result.ontology_consistent is True

    def test_orthogonal_embeddings_fail(self):
        opt = self._optimizer(threshold=0.5)
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        result = opt.evaluate("src", "decoded", a, b)
        assert abs(result.similarity_score) < 1e-9
        assert result.passed is False

    def test_kg_triples_consistent(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {"subject": "dog1", "predicate": "type", "object": "Dog"},
                {"subject": "dog1", "predicate": "name", "object": "Rex"},
            ],
        )
        assert result.ontology_consistent is True
        assert result.violations == []

    def test_kg_triples_empty_predicate_violation(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[{"subject": "x", "predicate": "", "object": "y"}],
        )
        assert result.ontology_consistent is False
        assert len(result.violations) >= 1
        assert result.passed is False

    def test_add_ontology_class(self):
        opt = self._optimizer()
        opt.add_ontology_class("Animal")
        opt.add_ontology_class("Dog", superclasses=["Animal"])
        stats = opt.get_statistics()
        assert stats["ergoai"]["classes"] == 2

    def test_get_statistics_no_ergo(self):
        opt = self._optimizer()
        stats = opt.get_statistics()
        assert "similarity_threshold" in stats
        assert "ergoai" not in stats  # not yet initialised

    def test_default_config(self):
        mod = _load_flogic_optimizer()
        FLogicOptimizerConfig = mod.FLogicOptimizerConfig
        FLogicSemanticOptimizer = mod.FLogicSemanticOptimizer

        opt = FLogicSemanticOptimizer()
        assert opt.config.similarity_threshold == 0.80
        assert opt.config.check_ontology_consistency is True

    def test_dimension_mismatch_raises(self):
        mod = _load_flogic_optimizer()
        FLogicSemanticOptimizer = mod.FLogicSemanticOptimizer

        opt = FLogicSemanticOptimizer()
        with pytest.raises(ValueError, match="dimension mismatch"):
            opt.evaluate("a", "b", [1.0, 2.0], [1.0, 2.0, 3.0])

    def test_result_metadata(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate("hello", "world", emb, emb)
        assert result.metadata["source_text"] == "hello"
        assert result.metadata["decoded_text"] == "world"
        assert "threshold" in result.metadata

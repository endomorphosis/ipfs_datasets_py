"""Conformance checks for core optimizer constructor parameter contracts."""

from __future__ import annotations

import inspect

from ipfs_datasets_py.optimizers.agentic.base import AgenticOptimizer
from ipfs_datasets_py.optimizers.agentic.llm_integration import OptimizerLLMRouter
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    LogicExtractor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import (
    LogicTheoremOptimizer,
)


def _parameter_names(cls: type) -> set[str]:
    return set(inspect.signature(cls.__init__).parameters.keys())


def test_graphrag_constructor_inventory_conformance() -> None:
    expected = {
        OntologyGenerator: {
            "ipfs_accelerate_config",
            "use_ipfs_accelerate",
            "logger",
            "llm_backend",
        },
        OntologyPipeline: {"domain", "use_llm", "max_rounds", "logger", "metric_sink"},
        OntologyCritic: {"backend_config", "use_llm", "logger"},
        OntologyMediator: {"generator", "critic", "max_rounds", "logger"},
    }
    for cls, required in expected.items():
        params = _parameter_names(cls)
        assert required.issubset(params), f"{cls.__name__} missing {sorted(required - params)}"


def test_logic_constructor_inventory_conformance() -> None:
    expected = {
        LogicExtractor: {
            "model",
            "backend",
            "use_ipfs_accelerate",
            "enable_formula_translation",
            "enable_kg_integration",
            "enable_rag_integration",
        },
        LogicTheoremOptimizer: {
            "config",
            "llm_backend",
            "extraction_mode",
            "use_provers",
            "enable_caching",
            "domain",
            "metrics_collector",
            "learning_metrics_collector",
            "logger",
        },
    }
    for cls, required in expected.items():
        params = _parameter_names(cls)
        assert required.issubset(params), f"{cls.__name__} missing {sorted(required - params)}"


def test_agentic_constructor_inventory_conformance() -> None:
    expected = {
        OptimizerLLMRouter: {
            "preferred_provider",
            "fallback_providers",
            "enable_tracking",
            "enable_caching",
            "cache",
        },
        AgenticOptimizer: {"agent_id", "llm_router", "change_control", "config", "logger"},
    }
    for cls, required in expected.items():
        params = _parameter_names(cls)
        assert required.issubset(params), f"{cls.__name__} missing {sorted(required - params)}"

"""Batch 266: Context standardization adapters across optimizer domains."""

from pathlib import Path

from ipfs_datasets_py.optimizers.agentic.base import OptimizationTask
from ipfs_datasets_py.optimizers.common.unified_config import (
    AgenticContext,
    DomainType,
    GraphRAGContext,
    LogicContext,
    context_from_agentic_optimization_task,
    context_from_logic_extraction_context,
    context_from_ontology_generation_context,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType as GraphDataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    DataType as LogicDataType,
    LogicExtractionContext,
)


class TestBatch266ContextAdapters:
    def test_graphrag_adapter_from_context_function(self):
        context = OntologyGenerationContext(
            data_source="contract.txt",
            data_type=GraphDataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(confidence_threshold=0.7, max_entities=25),
        )

        unified = context_from_ontology_generation_context(context, session_id="g-1")

        assert isinstance(unified, GraphRAGContext)
        assert unified.domain == DomainType.GRAPHRAG
        assert unified.session_id == "g-1"
        assert unified.ontology_domain == "legal"
        assert isinstance(unified.extraction_context, dict)
        assert unified.extraction_context["confidence_threshold"] == 0.7

    def test_logic_adapter_from_context_function(self):
        context = LogicExtractionContext(
            data={"P(a)": "Given", "Q(a)": "Derived"},
            data_type=LogicDataType.JSON,
            domain="legal",
            hints=["prefer obligations"],
        )

        unified = context_from_logic_extraction_context(context, session_id="l-1")

        assert isinstance(unified, LogicContext)
        assert unified.domain == DomainType.LOGIC
        assert unified.session_id == "l-1"
        assert unified.formulas == {"P(a)": "Given", "Q(a)": "Derived"}
        assert unified.metadata["logic_domain"] == "legal"
        assert unified.metadata["hints_count"] == 1

    def test_agentic_adapter_from_task_function(self):
        task = OptimizationTask(
            task_id="task-123",
            description="Improve extraction reliability",
            target_files=[Path("src/a.py"), Path("src/b.py")],
            constraints={"max_runtime_ms": 5000},
        )

        unified = context_from_agentic_optimization_task(task)

        assert isinstance(unified, AgenticContext)
        assert unified.domain == DomainType.AGENTIC
        assert unified.session_id == "task-123"
        assert unified.decision_log["description"] == "Improve extraction reliability"
        assert unified.metadata["target_files_count"] == 2
        assert "max_runtime_ms" in unified.decision_log["constraints"]


class TestBatch266ClassHelpers:
    def test_ontology_generation_context_to_unified_context(self):
        context = OntologyGenerationContext(
            data_source="memo.md",
            data_type=GraphDataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.HYBRID,
            config={"confidence_threshold": 0.6},
        )

        unified = context.to_unified_context(session_id="g-2")

        assert isinstance(unified, GraphRAGContext)
        assert unified.session_id == "g-2"
        assert unified.extraction_context["confidence_threshold"] == 0.6

    def test_logic_extraction_context_to_unified_context(self):
        context = LogicExtractionContext(
            data={"R(a)": "fact"},
            data_type=LogicDataType.TEXT,
            domain="medical",
            hints=["strict mode", "schema first"],
        )

        unified = context.to_unified_context(session_id="l-2")

        assert isinstance(unified, LogicContext)
        assert unified.session_id == "l-2"
        assert unified.metadata["hints_count"] == 2
        assert unified.metadata["logic_domain"] == "medical"

    def test_optimization_task_to_unified_context(self):
        task = OptimizationTask(
            task_id="task-abc",
            description="Tune cache behavior",
            constraints={"min_hit_rate": 0.8},
        )

        unified = task.to_unified_context()

        assert isinstance(unified, AgenticContext)
        assert unified.session_id == "task-abc"
        assert unified.decision_log["description"] == "Tune cache behavior"
        assert "min_hit_rate" in unified.decision_log["constraints"]

    def test_agentic_unified_context_custom_session_id(self):
        task = OptimizationTask(task_id="task-x", description="x")

        unified = task.to_unified_context(session_id="agentic-session-override")

        assert unified.session_id == "agentic-session-override"
        assert unified.metadata["task_id"] == "task-x"

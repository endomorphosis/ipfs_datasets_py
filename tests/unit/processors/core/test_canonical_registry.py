"""PATLAW-003: canonical registry registration and discovery.

Acceptance:
- No runtime-checkable / isinstance failure on register
- Bare legacy processors are rejected (must use LegacyProtocolAdapter)
- Core processors and adapted legacy processors both route deterministically
- Empty registry / no-match is explicit (not a silent empty success path)
- Dual registry modules share one implementation and global singleton
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

import pytest

import ipfs_datasets_py.processors.core.protocol as core_protocol
import ipfs_datasets_py.processors.protocol as legacy_protocol
from ipfs_datasets_py.processors.adapters.legacy_protocol_adapter import (
    LegacyProtocolAdapter,
    convert_legacy_result_to_core,
    is_legacy_processor,
    map_legacy_input_type,
)
from ipfs_datasets_py.processors.core.protocol import (
    InputType,
    ProcessingContext,
    ProcessingResult,
    is_processor,
)
from ipfs_datasets_py.processors.core.registry import (
    EmptyProcessorSetError,
    ProcessorRegistrationError,
    ProcessorRegistry,
    get_global_registry,
    reset_global_registry,
)


class _CorePDFProcessor:
    def __init__(self, accept_format: str = "pdf") -> None:
        self.accept_format = accept_format
        self.can_handle_calls: List[ProcessingContext] = []
        self.process_calls: List[ProcessingContext] = []

    async def can_handle(self, context: ProcessingContext) -> bool:
        self.can_handle_calls.append(context)
        return context.get_format() == self.accept_format

    async def process(self, context: ProcessingContext) -> ProcessingResult:
        self.process_calls.append(context)
        return ProcessingResult(
            success=True,
            knowledge_graph={
                "entities": [
                    {"id": "c1", "type": "Document", "label": str(context.source)}
                ],
                "relationships": [],
            },
            vectors=[[0.5, 0.5]],
            metadata={"processor": "CorePDF", "source": str(context.source)},
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": "CorePDF",
            "handles": [self.accept_format],
            "formats": [self.accept_format],
            "input_types": [InputType.FILE],
            "outputs": ["knowledge_graph", "vectors"],
            "priority": 40,
        }


class _CoreURLProcessor:
    async def can_handle(self, context: ProcessingContext) -> bool:
        return context.input_type == InputType.URL

    async def process(self, context: ProcessingContext) -> ProcessingResult:
        return ProcessingResult(
            success=True,
            knowledge_graph={"entities": [{"id": "u1", "type": "URL"}], "relationships": []},
            metadata={"processor": "CoreURL"},
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": "CoreURL",
            "input_types": [InputType.URL],
            "formats": ["html"],
            "priority": 20,
        }


class _LegacyPDFProcessor:
    def __init__(self, accept_suffix: str = ".pdf") -> None:
        self.accept_suffix = accept_suffix
        self.can_process_calls: List[Any] = []
        self.process_calls: List[Any] = []

    async def can_process(self, input_source: Union[str, Path]) -> bool:
        self.can_process_calls.append(input_source)
        return str(input_source).lower().endswith(self.accept_suffix)

    async def process(
        self, input_source: Union[str, Path], **options: Any
    ) -> legacy_protocol.ProcessingResult:
        self.process_calls.append((input_source, options))
        kg = legacy_protocol.KnowledgeGraph(
            entities=[
                legacy_protocol.Entity(
                    id="e1", type="Document", label=str(input_source)
                )
            ],
            source=str(input_source),
        )
        vectors = legacy_protocol.VectorStore()
        vectors.add_embedding("e1", [0.1, 0.2, 0.3])
        metadata = legacy_protocol.ProcessingMetadata(
            processor_name="LegacyPDF",
            input_type=legacy_protocol.InputType.FILE,
            status=legacy_protocol.ProcessingStatus.SUCCESS,
        )
        return legacy_protocol.ProcessingResult(
            knowledge_graph=kg,
            vectors=vectors,
            content={"path": str(input_source), "options": options},
            metadata=metadata,
        )

    def get_supported_types(self) -> List[str]:
        return ["file", "pdf"]

    def get_priority(self) -> int:
        return 10

    def get_name(self) -> str:
        return "LegacyPDF"


# ---------------------------------------------------------------------------
# isinstance / registration gates
# ---------------------------------------------------------------------------


class TestNoIsinstanceRuntimeCheckableFailure:
    def test_isinstance_against_core_protocol_still_raises(self):
        """Core protocol remains non-runtime-checkable (ADR / PATLAW-002)."""
        proc = _CorePDFProcessor()
        with pytest.raises(TypeError, match="runtime_checkable"):
            isinstance(proc, core_protocol.ProcessorProtocol)

    def test_register_uses_is_processor_not_isinstance(self):
        registry = ProcessorRegistry()
        proc = _CorePDFProcessor()
        assert is_processor(proc) is True
        name = registry.register(proc, name="core-pdf")
        assert name == "core-pdf"
        assert registry.get_processor("core-pdf") is proc

    def test_register_rejects_incomplete_object(self):
        class Incomplete:
            async def can_handle(self, context: ProcessingContext) -> bool:
                return True

        registry = ProcessorRegistry()
        with pytest.raises(ProcessorRegistrationError, match="canonical async"):
            registry.register(Incomplete())

    def test_register_rejects_bare_legacy_with_adapter_guidance(self):
        registry = ProcessorRegistry()
        legacy = _LegacyPDFProcessor()
        assert is_legacy_processor(legacy) is True
        assert is_processor(legacy) is False
        with pytest.raises(ProcessorRegistrationError, match="LegacyProtocolAdapter"):
            registry.register(legacy)

    def test_register_accepts_legacy_via_adapter(self):
        registry = ProcessorRegistry()
        adapter = LegacyProtocolAdapter(_LegacyPDFProcessor(), name="legacy-pdf")
        assert is_processor(adapter) is True
        name = registry.register(adapter, priority=15, name="legacy-pdf")
        assert name == "legacy-pdf"
        assert "legacy-pdf" in registry


# ---------------------------------------------------------------------------
# Deterministic discovery
# ---------------------------------------------------------------------------


class TestDeterministicRouting:
    @pytest.mark.asyncio
    async def test_core_processor_selected_by_format(self):
        registry = ProcessorRegistry()
        pdf = _CorePDFProcessor()
        url = _CoreURLProcessor()
        registry.register(pdf, priority=10, name="PDF")
        registry.register(url, priority=20, name="URL")

        ctx = ProcessingContext(
            InputType.FILE, "oa.pdf", metadata={"format": "pdf"}
        )
        matched = await registry.get_processors(ctx)
        assert matched == [pdf]
        assert len(pdf.can_handle_calls) == 1

    @pytest.mark.asyncio
    async def test_priority_order_with_multiple_matches(self):
        registry = ProcessorRegistry()

        class Always:
            def __init__(self, tag: str) -> None:
                self.tag = tag

            async def can_handle(self, context: ProcessingContext) -> bool:
                return True

            async def process(self, context: ProcessingContext) -> ProcessingResult:
                return ProcessingResult(success=True, metadata={"tag": self.tag})

            def get_capabilities(self) -> Dict[str, Any]:
                return {"name": self.tag}

        low = Always("low")
        high = Always("high")
        registry.register(low, priority=5, name="low")
        registry.register(high, priority=50, name="high")

        matched = await registry.get_processors(
            ProcessingContext(InputType.TEXT, "hello")
        )
        assert matched == [high, low]

    @pytest.mark.asyncio
    async def test_limit_parameter(self):
        registry = ProcessorRegistry()

        class Always:
            async def can_handle(self, context: ProcessingContext) -> bool:
                return True

            async def process(self, context: ProcessingContext) -> ProcessingResult:
                return ProcessingResult(success=True)

            def get_capabilities(self) -> Dict[str, Any]:
                return {"name": "Always"}

        for i in range(5):
            registry.register(Always(), priority=10 - i, name=f"p{i}")

        ctx = ProcessingContext(InputType.FILE, "x")
        assert len(await registry.get_processors(ctx)) == 5
        assert len(await registry.get_processors(ctx, limit=2)) == 2

    @pytest.mark.asyncio
    async def test_legacy_adapter_and_core_route_together(self):
        registry = ProcessorRegistry()
        core = _CorePDFProcessor(accept_format="pdf")
        legacy = _LegacyPDFProcessor()
        adapter = LegacyProtocolAdapter(legacy, name="legacy-pdf")

        registry.register(core, priority=30, name="core-pdf")
        registry.register(adapter, priority=10, name="legacy-pdf")

        ctx = ProcessingContext(
            InputType.FILE, "doc.pdf", metadata={"format": "pdf"}
        )
        matched = await registry.get_processors(ctx)
        assert matched == [core, adapter]

        # Both can process when selected
        core_result = await core.process(ctx)
        adapter_result = await adapter.process(ctx)
        assert core_result.success is True
        assert adapter_result.success is True
        assert adapter_result.metadata["adapter"] == "LegacyProtocolAdapter"
        assert adapter_result.get_entity_count() == 1
        assert legacy.process_calls[0][0] == "doc.pdf"

    @pytest.mark.asyncio
    async def test_disabled_processor_skipped(self):
        registry = ProcessorRegistry()
        pdf = _CorePDFProcessor()
        registry.register(pdf, name="PDF")
        registry.disable("PDF")
        matched = await registry.get_processors(
            ProcessingContext(InputType.FILE, "a.pdf", metadata={"format": "pdf"})
        )
        assert matched == []

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_list_when_registry_nonempty(self):
        registry = ProcessorRegistry()
        registry.register(_CorePDFProcessor(), name="PDF")
        matched = await registry.get_processors(
            ProcessingContext(InputType.FILE, "a.xyz", metadata={"format": "xyz"})
        )
        assert matched == []

    @pytest.mark.asyncio
    async def test_empty_registry_raises_when_not_allowed(self):
        registry = ProcessorRegistry()
        ctx = ProcessingContext(InputType.FILE, "a.pdf", metadata={"format": "pdf"})
        with pytest.raises(EmptyProcessorSetError, match="no registered"):
            await registry.get_processors(ctx, allow_empty_registry=False)

    @pytest.mark.asyncio
    async def test_empty_registry_soft_empty_when_allowed(self):
        registry = ProcessorRegistry()
        ctx = ProcessingContext(InputType.FILE, "a.pdf", metadata={"format": "pdf"})
        assert await registry.get_processors(ctx, allow_empty_registry=True) == []


# ---------------------------------------------------------------------------
# Adapter conversion helpers (production module)
# ---------------------------------------------------------------------------


class TestLegacyAdapterModule:
    def test_map_legacy_input_types(self):
        assert map_legacy_input_type("file") is InputType.FILE
        assert map_legacy_input_type("ipfs") is InputType.IPFS_CID
        with pytest.raises(ValueError, match="unknown"):
            map_legacy_input_type("unknown")

    def test_convert_failed_result(self):
        legacy_result = legacy_protocol.ProcessingResult(
            knowledge_graph=legacy_protocol.KnowledgeGraph(),
            vectors=legacy_protocol.VectorStore(),
            content={},
            metadata=legacy_protocol.ProcessingMetadata(
                processor_name="L",
                status=legacy_protocol.ProcessingStatus.FAILED,
                errors=["boom"],
            ),
        )
        core_result = convert_legacy_result_to_core(legacy_result)
        assert core_result.success is False
        assert "boom" in core_result.errors

    def test_adapter_rejects_core_processor(self):
        with pytest.raises(TypeError, match="can_process"):
            LegacyProtocolAdapter(_CorePDFProcessor())


# ---------------------------------------------------------------------------
# Dual-module consolidation
# ---------------------------------------------------------------------------


class TestRegistryConsolidation:
    def test_processor_registry_reexports_canonical(self):
        from ipfs_datasets_py.processors.core import processor_registry as shim
        from ipfs_datasets_py.processors.core import registry as canon

        assert shim.ProcessorRegistry is canon.ProcessorRegistry
        assert shim.get_global_registry is canon.get_global_registry
        assert shim.ProcessorEntry is canon.ProcessorEntry

    def test_global_singleton_shared(self):
        reset_global_registry()
        from ipfs_datasets_py.processors.core.processor_registry import (
            get_global_registry as shim_get,
        )

        a = get_global_registry()
        b = shim_get()
        assert a is b
        a.register(_CorePDFProcessor(), name="shared-pdf")
        assert "shared-pdf" in b
        reset_global_registry()

    def test_get_capabilities_includes_both_api_shapes(self):
        registry = ProcessorRegistry()
        registry.register(_CorePDFProcessor(), name="PDF")
        registry.register(_CoreURLProcessor(), name="URL")
        caps = registry.get_capabilities()
        assert caps["total_processors"] == 2
        assert caps["enabled_processors"] == 2
        assert "processors" in caps
        assert "pdf" in caps["supported_formats"]
        assert "supported_types" in caps
        assert "by_type" in caps


# ---------------------------------------------------------------------------
# Supported import smoke (unit-level)
# ---------------------------------------------------------------------------


class TestSupportedImports:
    def test_core_registry_symbols(self):
        from ipfs_datasets_py.processors.core import (
            ProcessorRegistry,
            UniversalProcessor,
            get_global_registry,
            is_processor,
        )

        assert callable(is_processor)
        assert ProcessorRegistry is not None
        assert UniversalProcessor is not None
        assert get_global_registry is not None

    def test_legacy_adapter_import_path(self):
        from ipfs_datasets_py.processors.adapters.legacy_protocol_adapter import (
            LegacyProtocolAdapter as LPA,
            adapt_legacy_processor,
        )

        adapter = adapt_legacy_processor(_LegacyPDFProcessor())
        assert isinstance(adapter, LPA)
        assert is_processor(adapter) is True

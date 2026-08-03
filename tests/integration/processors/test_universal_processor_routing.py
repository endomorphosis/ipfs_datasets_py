"""PATLAW-003: UniversalProcessor deterministic routing integration.

Verifies:
- Core processors route end-to-end through UniversalProcessor
- Legacy processors route only via LegacyProtocolAdapter
- Empty registry and no-match cases fail with explicit errors (not silent success)
- Supported public imports remain resolvable
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, List, Union

import pytest

import ipfs_datasets_py.processors.protocol as legacy_protocol
from ipfs_datasets_py.processors.adapters.legacy_protocol_adapter import (
    LegacyProtocolAdapter,
)
from ipfs_datasets_py.processors.core.protocol import (
    InputType,
    ProcessingContext,
    ProcessingResult,
    is_processor,
)
from ipfs_datasets_py.processors.core.registry import ProcessorRegistry
from ipfs_datasets_py.processors.core.universal_processor import UniversalProcessor


class _CorePDFProcessor:
    def __init__(self, accept_format: str = "pdf", tag: str = "core") -> None:
        self.accept_format = accept_format
        self.tag = tag
        self.process_calls = 0

    async def can_handle(self, context: ProcessingContext) -> bool:
        return context.get_format() == self.accept_format

    async def process(self, context: ProcessingContext) -> ProcessingResult:
        self.process_calls += 1
        return ProcessingResult(
            success=True,
            knowledge_graph={
                "entities": [
                    {
                        "id": f"{self.tag}-1",
                        "type": "Document",
                        "label": str(context.source),
                    }
                ],
                "relationships": [],
            },
            vectors=[[1.0, 0.0]],
            metadata={"processor": self.tag, "source": str(context.source)},
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.tag,
            "handles": [self.accept_format],
            "formats": [self.accept_format],
            "input_types": [InputType.FILE],
        }

    def get_name(self) -> str:
        return self.tag


class _CoreAlwaysFail:
    async def can_handle(self, context: ProcessingContext) -> bool:
        return context.get_format() == "pdf"

    async def process(self, context: ProcessingContext) -> ProcessingResult:
        return ProcessingResult(success=False, errors=["deliberate failure"])

    def get_capabilities(self) -> Dict[str, Any]:
        return {"name": "always-fail", "handles": ["pdf"]}


class _LegacyPDFProcessor:
    def __init__(self, accept_suffix: str = ".pdf") -> None:
        self.accept_suffix = accept_suffix
        self.process_calls: List[Any] = []

    async def can_process(self, input_source: Union[str, Path]) -> bool:
        return str(input_source).lower().endswith(self.accept_suffix)

    async def process(
        self, input_source: Union[str, Path], **options: Any
    ) -> legacy_protocol.ProcessingResult:
        self.process_calls.append((input_source, options))
        kg = legacy_protocol.KnowledgeGraph(
            entities=[
                legacy_protocol.Entity(
                    id="leg-1", type="Document", label=str(input_source)
                )
            ],
            source=str(input_source),
        )
        store = legacy_protocol.VectorStore()
        store.add_embedding("leg-1", [0.2, 0.4])
        return legacy_protocol.ProcessingResult(
            knowledge_graph=kg,
            vectors=store,
            content={"path": str(input_source), "options": dict(options)},
            metadata=legacy_protocol.ProcessingMetadata(
                processor_name="LegacyPDF",
                input_type=legacy_protocol.InputType.FILE,
                status=legacy_protocol.ProcessingStatus.SUCCESS,
            ),
        )

    def get_supported_types(self) -> List[str]:
        return ["file", "pdf"]

    def get_name(self) -> str:
        return "LegacyPDF"


def _pdf_context(source: str = "/matters/1/office_action.pdf", **opts: Any) -> ProcessingContext:
    return ProcessingContext(
        input_type=InputType.FILE,
        source=source,
        metadata={"format": "pdf"},
        options=dict(opts),
    )


# ---------------------------------------------------------------------------
# Core routing
# ---------------------------------------------------------------------------


class TestCoreRouting:
    @pytest.mark.asyncio
    async def test_core_processor_end_to_end(self):
        registry = ProcessorRegistry()
        core = _CorePDFProcessor(tag="core-pdf")
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(core, priority=10, name="core-pdf")

        result = await up.process(
            "/matters/1/office_action.pdf",
            context=_pdf_context(),
        )
        assert result.success is True
        assert result.metadata["processor"] == "core-pdf"
        assert result.metadata.get("routing") == "canonical_core"
        assert result.get_entity_count() == 1
        assert core.process_calls == 1

    @pytest.mark.asyncio
    async def test_priority_picks_higher_first(self):
        registry = ProcessorRegistry()
        low = _CorePDFProcessor(tag="low")
        high = _CorePDFProcessor(tag="high")
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(low, priority=5, name="low")
        up.register_processor(high, priority=50, name="high")

        result = await up.process("doc.pdf", context=_pdf_context("doc.pdf"))
        assert result.success is True
        assert result.metadata["processor"] == "high"
        assert high.process_calls == 1
        assert low.process_calls == 0

    @pytest.mark.asyncio
    async def test_fallback_to_next_processor_on_failure(self):
        registry = ProcessorRegistry()
        fail = _CoreAlwaysFail()
        ok = _CorePDFProcessor(tag="ok")
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(fail, priority=100, name="fail")
        up.register_processor(ok, priority=10, name="ok")

        result = await up.process("doc.pdf", context=_pdf_context("doc.pdf"))
        assert result.success is True
        assert result.metadata["processor"] == "ok"


# ---------------------------------------------------------------------------
# Legacy adapter routing
# ---------------------------------------------------------------------------


class TestLegacyAdapterRouting:
    @pytest.mark.asyncio
    async def test_bare_legacy_cannot_register(self):
        up = UniversalProcessor(registry=ProcessorRegistry())
        with pytest.raises(Exception, match="LegacyProtocolAdapter|can_process"):
            up.register_processor(_LegacyPDFProcessor(), name="bare")

    @pytest.mark.asyncio
    async def test_adapted_legacy_routes_deterministically(self):
        registry = ProcessorRegistry()
        legacy = _LegacyPDFProcessor()
        adapter = LegacyProtocolAdapter(legacy, name="legacy-pdf")
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(adapter, priority=20, name="legacy-pdf")

        result = await up.process(
            "/matters/1/oa.pdf",
            context=_pdf_context("/matters/1/oa.pdf", ocr=True),
        )
        assert result.success is True
        assert result.metadata["adapter"] == "LegacyProtocolAdapter"
        assert result.metadata["adapter_name"] == "legacy-pdf"
        assert result.metadata["adapted_from"] == "legacy_protocol"
        assert result.get_entity_count() == 1
        assert result.vectors == [[0.2, 0.4]]
        assert legacy.process_calls[0][0] == "/matters/1/oa.pdf"
        assert legacy.process_calls[0][1].get("ocr") is True

    @pytest.mark.asyncio
    async def test_legacy_adapter_and_core_joint_routing(self):
        """Both shapes coexist; higher-priority core wins when both match."""
        registry = ProcessorRegistry()
        core = _CorePDFProcessor(tag="core")
        legacy = _LegacyPDFProcessor()
        adapter = LegacyProtocolAdapter(legacy, name="legacy")
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(core, priority=40, name="core")
        up.register_processor(adapter, priority=10, name="legacy")

        result = await up.process("joint.pdf", context=_pdf_context("joint.pdf"))
        assert result.success is True
        assert result.metadata["processor"] == "core"
        assert core.process_calls == 1
        assert legacy.process_calls == []

    @pytest.mark.asyncio
    async def test_legacy_wins_when_higher_priority(self):
        registry = ProcessorRegistry()
        core = _CorePDFProcessor(tag="core")
        legacy = _LegacyPDFProcessor()
        adapter = LegacyProtocolAdapter(legacy, name="legacy")
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(core, priority=5, name="core")
        up.register_processor(adapter, priority=90, name="legacy")

        result = await up.process("joint.pdf", context=_pdf_context("joint.pdf"))
        assert result.success is True
        assert result.metadata["adapter"] == "LegacyProtocolAdapter"
        assert len(legacy.process_calls) == 1
        assert core.process_calls == 0


# ---------------------------------------------------------------------------
# No silent empty set
# ---------------------------------------------------------------------------


class TestNoSilentEmptyProcessorSet:
    @pytest.mark.asyncio
    async def test_empty_registry_fails_explicitly(self):
        up = UniversalProcessor(
            registry=ProcessorRegistry(), max_retries=1, retry_delay=0
        )
        result = await up.process("doc.pdf", context=_pdf_context("doc.pdf"))
        assert result.success is False
        assert any("No processors registered" in e for e in result.errors)
        assert result.metadata.get("routing") == "empty_registry"

    @pytest.mark.asyncio
    async def test_no_match_fails_explicitly(self):
        registry = ProcessorRegistry()
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(_CorePDFProcessor(), name="pdf-only")

        ctx = ProcessingContext(
            InputType.FILE, "notes.txt", metadata={"format": "txt"}
        )
        result = await up.process("notes.txt", context=ctx)
        assert result.success is False
        assert any("No suitable processors" in e for e in result.errors)
        assert result.metadata.get("routing") == "no_match"
        assert result.metadata.get("registered") == 1

    @pytest.mark.asyncio
    async def test_all_failed_not_success(self):
        registry = ProcessorRegistry()
        up = UniversalProcessor(registry=registry, max_retries=1, retry_delay=0)
        up.register_processor(_CoreAlwaysFail(), name="fail")
        result = await up.process("doc.pdf", context=_pdf_context("doc.pdf"))
        assert result.success is False
        assert result.metadata.get("routing") == "all_failed"


# ---------------------------------------------------------------------------
# Supported public imports
# ---------------------------------------------------------------------------


class TestSupportedPublicImports:
    def test_package_and_core_imports(self):
        processors = importlib.import_module("ipfs_datasets_py.processors")
        core = importlib.import_module("ipfs_datasets_py.processors.core")

        for name in (
            "ProcessorProtocol",
            "ProcessingResult",
            "ProcessorRegistry",
            "UniversalProcessor",
            "InputType",
        ):
            assert hasattr(processors, name), f"package missing {name}"
            assert hasattr(core, name), f"core missing {name}"

        assert hasattr(core, "is_processor")
        assert callable(core.is_processor)

        # Package ProcessorProtocol remains the legacy surface (PATLAW-002).
        assert hasattr(processors.ProcessorProtocol, "can_process")
        assert hasattr(core.ProcessorProtocol, "can_handle")

        # Registry re-export is the canonical core registry.
        from ipfs_datasets_py.processors.core.registry import (
            ProcessorRegistry as CoreRegistry,
        )

        assert processors.ProcessorRegistry is CoreRegistry
        assert core.ProcessorRegistry is CoreRegistry

    def test_legacy_adapter_importable(self):
        mod = importlib.import_module(
            "ipfs_datasets_py.processors.adapters.legacy_protocol_adapter"
        )
        assert hasattr(mod, "LegacyProtocolAdapter")
        assert is_processor(LegacyProtocolAdapter(_LegacyPDFProcessor())) is True

    def test_processor_registry_shim_is_same_class(self):
        from ipfs_datasets_py.processors.core.processor_registry import (
            ProcessorRegistry as ShimRegistry,
        )
        from ipfs_datasets_py.processors.core.registry import (
            ProcessorRegistry as CanonRegistry,
        )

        assert ShimRegistry is CanonRegistry

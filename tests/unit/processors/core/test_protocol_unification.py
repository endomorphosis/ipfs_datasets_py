"""PATLAW-002: canonical processor contract and mixed-routing failures.

This module is the executable half of
``docs/architecture/PATENT_LEGAL_PROCESSOR_PROTOCOL_ADR.md``.

It:

1. Inventories structural incompatibilities between the legacy and core
   processor protocols.
2. Names ``ipfs_datasets_py.processors.core.protocol`` as the canonical runtime.
3. Proves that *implicit* mixed routing fails at the call / type boundary.
4. Defines explicit legacy→core compatibility conversion behavior that
   PATLAW-003's ``legacy_protocol_adapter`` must implement — without deleting
   supported public imports of the legacy surface.
"""

from __future__ import annotations

import inspect
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pytest

import ipfs_datasets_py.processors.core.protocol as core_protocol
import ipfs_datasets_py.processors.protocol as legacy_protocol
from ipfs_datasets_py.processors.core.protocol import (
    InputType as CoreInputType,
    ProcessingContext,
    ProcessingResult as CoreProcessingResult,
    ProcessorProtocol as CoreProcessorProtocol,
    is_processor,
)


# ---------------------------------------------------------------------------
# Canonical runtime identity
# ---------------------------------------------------------------------------


CANONICAL_PROTOCOL_MODULE = "ipfs_datasets_py.processors.core.protocol"
CANONICAL_PROTOCOL_ATTRS = ("can_handle", "process", "get_capabilities")
LEGACY_PROTOCOL_ATTRS = (
    "can_process",
    "process",
    "get_supported_types",
    "get_priority",
    "get_name",
)


class TestCanonicalRuntimeDecision:
    """ADR decision: core ProcessingContext / can_handle is canonical."""

    def test_canonical_module_is_core_protocol(self):
        assert core_protocol.__name__ == CANONICAL_PROTOCOL_MODULE

    def test_canonical_protocol_exposes_can_handle_not_can_process(self):
        assert hasattr(CoreProcessorProtocol, "can_handle")
        assert not hasattr(CoreProcessorProtocol, "can_process")
        for name in CANONICAL_PROTOCOL_ATTRS:
            assert hasattr(CoreProcessorProtocol, name)

    def test_canonical_processing_context_is_required_carrier(self):
        context = ProcessingContext(
            input_type=CoreInputType.FILE,
            source="/tmp/matter/office_action.pdf",
            metadata={"format": "pdf", "classification": "confidential_application"},
            options={"tenant": "test-tenant"},
        )
        assert context.input_type is CoreInputType.FILE
        assert context.get_format() == "pdf"
        assert context.metadata["classification"] == "confidential_application"
        assert "tenant" in context.options

    def test_canonical_result_is_success_centered(self):
        ok = CoreProcessingResult(success=True)
        bad = CoreProcessingResult(success=False, errors=["failed"])
        assert ok.success is True
        assert bad.success is False
        assert "success" in {f.name for f in fields(CoreProcessingResult)}
        assert "errors" in {f.name for f in fields(CoreProcessingResult)}

    def test_is_processor_requires_async_can_handle_and_process(self):
        class SyncShaped:
            def can_handle(self, context: ProcessingContext) -> bool:
                return True

            def process(self, context: ProcessingContext) -> CoreProcessingResult:
                return CoreProcessingResult(success=True)

            def get_capabilities(self) -> Dict[str, Any]:
                return {"name": "SyncShaped"}

        class AsyncShaped:
            async def can_handle(self, context: ProcessingContext) -> bool:
                return True

            async def process(self, context: ProcessingContext) -> CoreProcessingResult:
                return CoreProcessingResult(success=True)

            def get_capabilities(self) -> Dict[str, Any]:
                return {"name": "AsyncShaped"}

        assert is_processor(SyncShaped()) is False
        assert is_processor(AsyncShaped()) is True


# ---------------------------------------------------------------------------
# Incompatibility inventory
# ---------------------------------------------------------------------------


class TestProtocolIncompatibilityInventory:
    """Document every incompatible behavior the ADR inventories."""

    def test_selection_method_names_differ(self):
        assert hasattr(legacy_protocol.ProcessorProtocol, "can_process")
        assert not hasattr(legacy_protocol.ProcessorProtocol, "can_handle")
        assert hasattr(core_protocol.ProcessorProtocol, "can_handle")
        assert not hasattr(core_protocol.ProcessorProtocol, "can_process")

    def test_capability_method_names_differ(self):
        assert hasattr(legacy_protocol.ProcessorProtocol, "get_supported_types")
        assert not hasattr(legacy_protocol.ProcessorProtocol, "get_capabilities")
        assert hasattr(core_protocol.ProcessorProtocol, "get_capabilities")
        assert not hasattr(core_protocol.ProcessorProtocol, "get_supported_types")

    def test_processing_result_field_sets_are_disjoint_on_success_model(self):
        legacy_names = {f.name for f in fields(legacy_protocol.ProcessingResult)}
        core_names = {f.name for f in fields(core_protocol.ProcessingResult)}
        assert "success" in core_names
        assert "success" not in legacy_names
        assert "content" in legacy_names
        assert "content" not in core_names
        assert "errors" in core_names
        # Legacy errors live under ProcessingMetadata, not the result root.
        assert "errors" not in legacy_names

    def test_input_type_enums_are_not_identical(self):
        legacy_values = {m.value for m in legacy_protocol.InputType}
        core_values = {m.value for m in core_protocol.InputType}
        assert "ipfs" in legacy_values
        assert "ipfs" not in core_values
        assert "ipfs_cid" in core_values
        assert "ipns" in core_values
        assert "unknown" in legacy_values
        assert "unknown" not in core_values
        # Shared literals still exist as separate enum members.
        assert legacy_protocol.InputType.FILE is not core_protocol.InputType.FILE

    def test_protocols_are_distinct_types(self):
        assert legacy_protocol.ProcessorProtocol is not core_protocol.ProcessorProtocol
        assert legacy_protocol.ProcessingResult is not core_protocol.ProcessingResult
        assert legacy_protocol.InputType is not core_protocol.InputType

    def test_legacy_is_runtime_checkable_core_is_not(self):
        # Legacy uses @runtime_checkable; core relies on is_processor / structure.
        assert getattr(legacy_protocol.ProcessorProtocol, "_is_runtime_protocol", False) is True
        assert getattr(core_protocol.ProcessorProtocol, "_is_runtime_protocol", False) is False


# ---------------------------------------------------------------------------
# Fixtures: pure legacy and pure core implementers
# ---------------------------------------------------------------------------


class _LegacyOnlyProcessor:
    """Implements only the legacy can_process surface."""

    def __init__(self, accept_suffix: str = ".pdf") -> None:
        self.accept_suffix = accept_suffix
        self.can_process_calls: List[Any] = []
        self.process_calls: List[Any] = []

    async def can_process(self, input_source: Union[str, Path]) -> bool:
        self.can_process_calls.append(input_source)
        return str(input_source).lower().endswith(self.accept_suffix)

    async def process(self, input_source: Union[str, Path], **options: Any) -> legacy_protocol.ProcessingResult:
        self.process_calls.append((input_source, options))
        kg = legacy_protocol.KnowledgeGraph(
            entities=[
                legacy_protocol.Entity(
                    id="e1",
                    type="Document",
                    label=str(input_source),
                )
            ],
            source=str(input_source),
        )
        vectors = legacy_protocol.VectorStore()
        vectors.add_embedding("e1", [0.1, 0.2, 0.3])
        metadata = legacy_protocol.ProcessingMetadata(
            processor_name="LegacyOnly",
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
        return "LegacyOnly"


class _CoreOnlyProcessor:
    """Implements only the canonical can_handle surface."""

    def __init__(self, accept_format: str = "pdf") -> None:
        self.accept_format = accept_format
        self.can_handle_calls: List[ProcessingContext] = []
        self.process_calls: List[ProcessingContext] = []

    async def can_handle(self, context: ProcessingContext) -> bool:
        self.can_handle_calls.append(context)
        return context.get_format() == self.accept_format

    async def process(self, context: ProcessingContext) -> CoreProcessingResult:
        self.process_calls.append(context)
        return CoreProcessingResult(
            success=True,
            knowledge_graph={
                "entities": [{"id": "c1", "type": "Document", "label": str(context.source)}],
                "relationships": [],
            },
            vectors=[[0.5, 0.5]],
            metadata={"processor": "CoreOnly", "source": str(context.source)},
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": "CoreOnly",
            "handles": [self.accept_format],
            "outputs": ["knowledge_graph", "vectors"],
        }


# ---------------------------------------------------------------------------
# Implicit mixed routing must fail
# ---------------------------------------------------------------------------


class TestImplicitMixedRoutingFails:
    """Acceptance: tests fail for implicit mixed routing."""

    @pytest.mark.asyncio
    async def test_legacy_processor_lacks_can_handle(self):
        legacy = _LegacyOnlyProcessor()
        context = ProcessingContext(
            input_type=CoreInputType.FILE,
            source="office_action.pdf",
            metadata={"format": "pdf"},
        )
        assert not hasattr(legacy, "can_handle")
        with pytest.raises(AttributeError):
            await legacy.can_handle(context)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_core_processor_lacks_can_process(self):
        core = _CoreOnlyProcessor()
        assert not hasattr(core, "can_process")
        with pytest.raises(AttributeError):
            await core.can_process("office_action.pdf")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_calling_legacy_process_with_context_is_not_valid_mixed_use(self):
        """Passing ProcessingContext as a bare source is not a supported contract."""
        legacy = _LegacyOnlyProcessor()
        context = ProcessingContext(
            input_type=CoreInputType.FILE,
            source="office_action.pdf",
            metadata={"format": "pdf"},
        )
        # Legacy accepts Any-ish sources at runtime, but the *routing* contract
        # is wrong: can_process was never consulted with a path, and the result
        # is still a legacy ProcessingResult — unusable as a core result.
        result = await legacy.process(context)  # type: ignore[arg-type]
        assert isinstance(result, legacy_protocol.ProcessingResult)
        assert not isinstance(result, core_protocol.ProcessingResult)
        assert not hasattr(result, "success")

    @pytest.mark.asyncio
    async def test_calling_core_process_with_bare_path_raises(self):
        core = _CoreOnlyProcessor()
        with pytest.raises(AttributeError):
            # Core process expects ProcessingContext with get_format/source.
            await core.process("office_action.pdf")  # type: ignore[arg-type]

    def test_legacy_object_is_not_core_processor(self):
        legacy = _LegacyOnlyProcessor()
        assert is_processor(legacy) is False

    def test_core_object_is_not_legacy_runtime_protocol_without_can_process(self):
        core = _CoreOnlyProcessor()
        # runtime_checkable checks required methods; core has process but not can_process.
        assert isinstance(core, legacy_protocol.ProcessorProtocol) is False

    def test_implicit_registry_isinstance_against_core_protocol_raises(self):
        """Current mixed registry pattern: isinstance on non-runtime-checkable protocol."""
        core = _CoreOnlyProcessor()
        with pytest.raises(TypeError, match="runtime_checkable"):
            isinstance(core, core_protocol.ProcessorProtocol)

    def test_mixed_selection_loop_without_adapter_is_rejected(self):
        """
        A selection loop that tries both APIs without an explicit adapter is
        forbidden by the ADR. This test encodes that policy as a hard failure
        when both shapes are present and no adapter marker is set.
        """
        candidates = [_LegacyOnlyProcessor(), _CoreOnlyProcessor()]
        with pytest.raises(RuntimeError, match="implicit mixed routing"):
            _select_without_adapter(candidates)

    @pytest.mark.asyncio
    async def test_naive_can_handle_duck_type_on_legacy_fails(self):
        """Registry-style hasattr(can_handle) fallback must not silently succeed."""
        legacy = _LegacyOnlyProcessor()
        context = ProcessingContext(
            input_type=CoreInputType.FILE,
            source="x.pdf",
            metadata={"format": "pdf"},
        )
        matched = await _naive_core_only_match([legacy], context)
        assert matched == []


def _select_without_adapter(processors: List[Any]) -> Any:
    """Simulate illegal dual-API selection; always fail-closed."""
    has_legacy = any(hasattr(p, "can_process") and not hasattr(p, "can_handle") for p in processors)
    has_core = any(hasattr(p, "can_handle") and not hasattr(p, "can_process") for p in processors)
    if has_legacy and has_core:
        raise RuntimeError(
            "implicit mixed routing forbidden: registry contains both legacy "
            "can_process and core can_handle implementers without an explicit "
            "legacy_protocol_adapter"
        )
    return processors[0] if processors else None


async def _naive_core_only_match(processors: List[Any], context: ProcessingContext) -> List[Any]:
    """Only invoke can_handle; legacy processors are correctly skipped."""
    matched = []
    for processor in processors:
        if not hasattr(processor, "can_handle"):
            continue
        method = getattr(processor, "can_handle")
        if inspect.iscoroutinefunction(method):
            ok = await method(context)
        else:
            ok = method(context)
        if ok:
            matched.append(processor)
    return matched


# ---------------------------------------------------------------------------
# Explicit compatibility contract (reference behavior for PATLAW-003)
# ---------------------------------------------------------------------------


_LEGACY_TO_CORE_INPUT: Dict[str, CoreInputType] = {
    "url": CoreInputType.URL,
    "file": CoreInputType.FILE,
    "folder": CoreInputType.FOLDER,
    "text": CoreInputType.TEXT,
    "binary": CoreInputType.BINARY,
    "ipfs": CoreInputType.IPFS_CID,
}


def map_legacy_input_type(legacy_value: str) -> CoreInputType:
    """ADR InputType mapping; unknown is not silently invented."""
    if legacy_value == "unknown":
        raise ValueError("legacy InputType.unknown requires detector metadata; no core enum value")
    try:
        return _LEGACY_TO_CORE_INPUT[legacy_value]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy InputType: {legacy_value}") from exc


def convert_legacy_result_to_core(
    legacy_result: legacy_protocol.ProcessingResult,
) -> CoreProcessingResult:
    """ADR result conversion table (reference implementation for conformance)."""
    status = legacy_result.metadata.status
    success = status in (
        legacy_protocol.ProcessingStatus.SUCCESS,
        legacy_protocol.ProcessingStatus.PARTIAL,
    )
    warnings = list(legacy_result.metadata.warnings)
    if status is legacy_protocol.ProcessingStatus.PARTIAL:
        warnings.append("legacy_status=partial")
    errors = list(legacy_result.metadata.errors)
    if status is legacy_protocol.ProcessingStatus.FAILED and not errors:
        errors.append("legacy_status=failed")

    kg = legacy_result.knowledge_graph
    knowledge_graph = kg.to_dict() if hasattr(kg, "to_dict") else {}

    vectors: List[List[float]] = []
    store = legacy_result.vectors
    if store is not None and getattr(store, "embeddings", None):
        for _key, embedding in store.embeddings.items():
            vectors.append([float(x) for x in embedding])

    metadata: Dict[str, Any] = {
        "processor_name": legacy_result.metadata.processor_name,
        "processor_version": legacy_result.metadata.processor_version,
        "legacy_status": status.value,
        "legacy_input_type": legacy_result.metadata.input_type.value,
        "processing_time_seconds": legacy_result.metadata.processing_time_seconds,
        "resource_usage": dict(legacy_result.metadata.resource_usage),
        "adapted_from": "legacy_protocol",
    }
    return CoreProcessingResult(
        success=success,
        knowledge_graph=knowledge_graph,
        vectors=vectors,
        metadata=metadata,
        errors=errors,
        warnings=warnings,
        raw_output={"content": legacy_result.content, "extra": legacy_result.extra},
    )


class LegacyToCoreAdapter:
    """
    Reference legacy→core adapter contract.

    PATLAW-003 must provide a production equivalent at
    ``ipfs_datasets_py.processors.adapters.legacy_protocol_adapter``.
    This class is the conformance oracle, not production code.
    """

    def __init__(self, legacy: Any, *, name: Optional[str] = None) -> None:
        if not hasattr(legacy, "can_process") or not callable(legacy.can_process):
            raise TypeError("legacy processor must implement can_process")
        if not hasattr(legacy, "process") or not callable(legacy.process):
            raise TypeError("legacy processor must implement process")
        self._legacy = legacy
        self._name = name or getattr(legacy, "get_name", lambda: legacy.__class__.__name__)()
        self.adapter_api = CANONICAL_PROTOCOL_MODULE

    async def can_handle(self, context: ProcessingContext) -> bool:
        source = context.source
        if not isinstance(source, (str, Path, bytes)):
            source = str(source)
        method = self._legacy.can_process
        if inspect.iscoroutinefunction(method):
            return bool(await method(source))
        return bool(method(source))

    async def process(self, context: ProcessingContext) -> CoreProcessingResult:
        source = context.source
        if not isinstance(source, (str, Path, bytes)):
            source = str(source)
        options = dict(context.options or {})
        method = self._legacy.process
        if inspect.iscoroutinefunction(method):
            legacy_result = await method(source, **options)
        else:
            legacy_result = method(source, **options)
        if not isinstance(legacy_result, legacy_protocol.ProcessingResult):
            raise TypeError(
                "legacy process() must return processors.protocol.ProcessingResult; "
                f"got {type(legacy_result)!r}"
            )
        core_result = convert_legacy_result_to_core(legacy_result)
        core_result.metadata["adapter"] = "LegacyToCoreAdapter"
        core_result.metadata["adapter_name"] = self._name
        return core_result

    def get_capabilities(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {
            "name": self._name,
            "adapted_from": "legacy_protocol",
            "canonical_api": CANONICAL_PROTOCOL_MODULE,
        }
        if hasattr(self._legacy, "get_supported_types"):
            caps["handles"] = list(self._legacy.get_supported_types())
        if hasattr(self._legacy, "get_priority"):
            caps["priority"] = self._legacy.get_priority()
        return caps


class TestExplicitLegacyCompatibilityContract:
    """Define compatibility behavior without deleting legacy public APIs."""

    def test_legacy_module_remains_importable(self):
        assert legacy_protocol.ProcessorProtocol is not None
        assert callable(legacy_protocol.ProcessorProtocol.can_process)

    def test_input_type_mapping_table(self):
        assert map_legacy_input_type("file") is CoreInputType.FILE
        assert map_legacy_input_type("ipfs") is CoreInputType.IPFS_CID
        with pytest.raises(ValueError, match="unknown"):
            map_legacy_input_type("unknown")

    def test_convert_success_legacy_result(self):
        legacy = _LegacyOnlyProcessor()
        # Build a minimal successful legacy result directly.
        kg = legacy_protocol.KnowledgeGraph(
            entities=[legacy_protocol.Entity(id="1", type="X", label="L")],
            source="a.pdf",
        )
        store = legacy_protocol.VectorStore()
        store.add_embedding("1", [1.0, 0.0])
        legacy_result = legacy_protocol.ProcessingResult(
            knowledge_graph=kg,
            vectors=store,
            content={"text": "redacted"},
            metadata=legacy_protocol.ProcessingMetadata(
                processor_name="L",
                status=legacy_protocol.ProcessingStatus.SUCCESS,
            ),
        )
        core_result = convert_legacy_result_to_core(legacy_result)
        assert core_result.success is True
        assert core_result.get_entity_count() == 1
        assert core_result.vectors == [[1.0, 0.0]]
        assert core_result.metadata["adapted_from"] == "legacy_protocol"
        assert core_result.raw_output["content"]["text"] == "redacted"

    def test_convert_failed_legacy_result(self):
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

    def test_adapter_is_core_processor(self):
        adapter = LegacyToCoreAdapter(_LegacyOnlyProcessor())
        assert is_processor(adapter) is True
        assert adapter.adapter_api == CANONICAL_PROTOCOL_MODULE

    @pytest.mark.asyncio
    async def test_adapter_can_handle_delegates_to_can_process(self):
        legacy = _LegacyOnlyProcessor(accept_suffix=".pdf")
        adapter = LegacyToCoreAdapter(legacy)
        pdf_ctx = ProcessingContext(
            CoreInputType.FILE, "oa.pdf", metadata={"format": "pdf"}
        )
        txt_ctx = ProcessingContext(
            CoreInputType.FILE, "notes.txt", metadata={"format": "txt"}
        )
        assert await adapter.can_handle(pdf_ctx) is True
        assert await adapter.can_handle(txt_ctx) is False
        assert legacy.can_process_calls == ["oa.pdf", "notes.txt"]

    @pytest.mark.asyncio
    async def test_adapter_process_returns_core_result(self):
        legacy = _LegacyOnlyProcessor()
        adapter = LegacyToCoreAdapter(legacy, name="pdf-legacy")
        context = ProcessingContext(
            CoreInputType.FILE,
            "/matters/1/oa.pdf",
            metadata={"format": "pdf"},
            options={"ocr": True},
        )
        result = await adapter.process(context)
        assert isinstance(result, CoreProcessingResult)
        assert result.success is True
        assert result.metadata["adapter"] == "LegacyToCoreAdapter"
        assert result.metadata["adapter_name"] == "pdf-legacy"
        assert result.get_entity_count() == 1
        assert legacy.process_calls[0][0] == "/matters/1/oa.pdf"
        assert legacy.process_calls[0][1].get("ocr") is True

    @pytest.mark.asyncio
    async def test_explicit_adapter_enables_safe_joint_routing(self):
        """With an explicit adapter, legacy and core can coexist in one list."""
        core = _CoreOnlyProcessor()
        adapted = LegacyToCoreAdapter(_LegacyOnlyProcessor())
        # Both expose can_handle; neither is a bare legacy-only peer.
        processors = [core, adapted]
        has_bare_legacy = any(
            hasattr(p, "can_process") and not hasattr(p, "can_handle") for p in processors
        )
        assert has_bare_legacy is False
        context = ProcessingContext(
            CoreInputType.FILE, "doc.pdf", metadata={"format": "pdf"}
        )
        matched = await _naive_core_only_match(processors, context)
        assert core in matched
        assert adapted in matched

    def test_adapter_rejects_non_legacy_delegate(self):
        with pytest.raises(TypeError, match="can_process"):
            LegacyToCoreAdapter(_CoreOnlyProcessor())

    def test_no_second_adapter_direction_required_by_contract(self):
        """
        ADR: only legacy→core is required. Core processors are not required
        to grow can_process for the canonical router.
        """
        core = _CoreOnlyProcessor()
        assert not hasattr(core, "can_process")
        assert is_processor(core) is True


class TestAsyncCanonicalProcessorHappyPath:
    """Sanity: pure core path works without any legacy types."""

    @pytest.mark.asyncio
    async def test_core_only_end_to_end(self):
        processor = _CoreOnlyProcessor()
        context = ProcessingContext(
            CoreInputType.FILE,
            "fixture.pdf",
            metadata={"format": "pdf"},
        )
        assert await processor.can_handle(context) is True
        result = await processor.process(context)
        assert result.success is True
        assert result.metadata["processor"] == "CoreOnly"
        assert is_processor(processor) is True

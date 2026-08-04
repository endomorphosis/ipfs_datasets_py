"""Legacy → core ProcessorProtocol adapter.

PATLAW-003 / PATENT_LEGAL_PROCESSOR_PROTOCOL_ADR:

- Canonical runtime is ``ipfs_datasets_py.processors.core.protocol``.
- Legacy ``can_process`` / ``process`` implementers must not enter the
  canonical registry without this explicit adapter.
- Only legacy → core adaptation is supported for new unified routing.

This module is the production equivalent of the conformance oracle in
``tests/unit/processors/core/test_protocol_unification.py``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.processors.core.protocol import (
    InputType as CoreInputType,
    ProcessingContext,
    ProcessingResult as CoreProcessingResult,
)
import ipfs_datasets_py.processors.protocol as legacy_protocol

CANONICAL_PROTOCOL_MODULE = "ipfs_datasets_py.processors.core.protocol"

_LEGACY_TO_CORE_INPUT: Dict[str, CoreInputType] = {
    "url": CoreInputType.URL,
    "file": CoreInputType.FILE,
    "folder": CoreInputType.FOLDER,
    "text": CoreInputType.TEXT,
    "binary": CoreInputType.BINARY,
    "ipfs": CoreInputType.IPFS_CID,
}


def map_legacy_input_type(legacy_value: Union[str, legacy_protocol.InputType]) -> CoreInputType:
    """Map a legacy InputType value to the core enum.

    ``unknown`` is intentionally rejected: the ADR requires detector metadata
    rather than inventing a core enum member.
    """
    if isinstance(legacy_value, legacy_protocol.InputType):
        value = legacy_value.value
    else:
        value = str(legacy_value).lower()

    if value == "unknown":
        raise ValueError(
            "legacy InputType.unknown requires detector metadata; no core enum value"
        )
    try:
        return _LEGACY_TO_CORE_INPUT[value]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy InputType: {value}") from exc


def convert_legacy_result_to_core(
    legacy_result: legacy_protocol.ProcessingResult,
) -> CoreProcessingResult:
    """Convert a legacy ProcessingResult into the canonical core result shape."""
    if not isinstance(legacy_result, legacy_protocol.ProcessingResult):
        raise TypeError(
            "expected processors.protocol.ProcessingResult, "
            f"got {type(legacy_result)!r}"
        )

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
    if hasattr(kg, "to_dict") and callable(kg.to_dict):
        knowledge_graph = kg.to_dict()
    elif isinstance(kg, dict):
        knowledge_graph = kg
    else:
        knowledge_graph = {}

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


def _source_for_legacy(context: ProcessingContext) -> Union[str, Path, bytes]:
    source = context.source
    if isinstance(source, (str, Path, bytes)):
        return source
    return str(source)


def is_legacy_processor(obj: Any) -> bool:
    """Return True if *obj* looks like a bare legacy can_process implementer."""
    return (
        hasattr(obj, "can_process")
        and callable(getattr(obj, "can_process", None))
        and not (
            hasattr(obj, "can_handle")
            and callable(getattr(obj, "can_handle", None))
        )
    )


class LegacyProtocolAdapter:
    """Adapt a legacy ``can_process`` processor to the canonical core protocol.

    The adapter implements async ``can_handle`` / ``process`` and sync
    ``get_capabilities`` so it passes ``is_processor`` and can be registered
    in the canonical ``ProcessorRegistry``.
    """

    def __init__(self, legacy: Any, *, name: Optional[str] = None) -> None:
        if not hasattr(legacy, "can_process") or not callable(legacy.can_process):
            raise TypeError("legacy processor must implement can_process")
        if not hasattr(legacy, "process") or not callable(legacy.process):
            raise TypeError("legacy processor must implement process")
        if hasattr(legacy, "can_handle") and callable(getattr(legacy, "can_handle")):
            # Explicit dual-API objects are not bare legacy; reject to avoid
            # dual registration under both contracts.
            raise TypeError(
                "object already exposes can_handle; do not wrap core processors "
                "with LegacyProtocolAdapter"
            )
        self._legacy = legacy
        if name is not None:
            self._name = name
        elif hasattr(legacy, "get_name") and callable(legacy.get_name):
            try:
                self._name = str(legacy.get_name())
            except Exception:
                self._name = legacy.__class__.__name__
        else:
            self._name = legacy.__class__.__name__
        self.adapter_api = CANONICAL_PROTOCOL_MODULE

    @property
    def legacy(self) -> Any:
        """The wrapped legacy processor instance."""
        return self._legacy

    @property
    def name(self) -> str:
        return self._name

    async def can_handle(self, context: ProcessingContext) -> bool:
        source = _source_for_legacy(context)
        method = self._legacy.can_process
        if inspect.iscoroutinefunction(method):
            return bool(await method(source))
        return bool(method(source))

    async def process(self, context: ProcessingContext) -> CoreProcessingResult:
        source = _source_for_legacy(context)
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
        core_result.metadata["adapter"] = "LegacyProtocolAdapter"
        core_result.metadata["adapter_name"] = self._name
        return core_result

    def get_capabilities(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {
            "name": self._name,
            "adapted_from": "legacy_protocol",
            "canonical_api": CANONICAL_PROTOCOL_MODULE,
        }
        if hasattr(self._legacy, "get_supported_types"):
            try:
                caps["handles"] = list(self._legacy.get_supported_types())
            except Exception:
                caps["handles"] = []
        if hasattr(self._legacy, "get_priority"):
            try:
                caps["priority"] = self._legacy.get_priority()
            except Exception:
                pass
        return caps

    def get_priority(self) -> int:
        if hasattr(self._legacy, "get_priority") and callable(self._legacy.get_priority):
            try:
                return int(self._legacy.get_priority())
            except Exception:
                return 10
        return 10

    def get_name(self) -> str:
        return self._name


# Back-compat alias used by some design docs / early drafts
LegacyToCoreAdapter = LegacyProtocolAdapter


def adapt_legacy_processor(
    legacy: Any,
    *,
    name: Optional[str] = None,
) -> LegacyProtocolAdapter:
    """Convenience factory for :class:`LegacyProtocolAdapter`."""
    return LegacyProtocolAdapter(legacy, name=name)


__all__ = [
    "CANONICAL_PROTOCOL_MODULE",
    "LegacyProtocolAdapter",
    "LegacyToCoreAdapter",
    "adapt_legacy_processor",
    "convert_legacy_result_to_core",
    "is_legacy_processor",
    "map_legacy_input_type",
]

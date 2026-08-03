"""Canonical ProcessorRegistry - single registration and discovery surface.

PATLAW-003 consolidates the dual registry modules into one canonical
implementation:

- ``processors.core.registry`` is the source of truth
- ``processors.core.processor_registry`` re-exports this module
- Registration requires core ``is_processor`` conformance (or an explicit
  :class:`~ipfs_datasets_py.processors.adapters.legacy_protocol_adapter.LegacyProtocolAdapter`)
- Bare legacy ``can_process`` objects are rejected (no implicit mixed routing)
- ``isinstance(..., ProcessorProtocol)`` is never used (core protocol is not
  ``@runtime_checkable``)

Selection is deterministic: enabled processors are checked in descending
priority order via async ``can_handle`` only.
"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .protocol import (
    InputType,
    ProcessingContext,
    ProcessorProtocol,
    is_processor,
)

logger = logging.getLogger(__name__)


class ProcessorRegistrationError(TypeError):
    """Raised when a non-conforming processor is offered to the registry."""


class EmptyProcessorSetError(RuntimeError):
    """Raised when discovery is requested against an empty registry.

    Callers that prefer a soft empty list may pass
    ``allow_empty_registry=True`` to :meth:`ProcessorRegistry.get_processors`.
    UniversalProcessor always treats an empty registry as a hard routing
    failure so empty sets are never silent successes.
    """


def _is_bare_legacy(obj: Any) -> bool:
    """True if *obj* implements legacy can_process without can_handle."""
    return (
        hasattr(obj, "can_process")
        and callable(getattr(obj, "can_process", None))
        and not (
            hasattr(obj, "can_handle")
            and callable(getattr(obj, "can_handle", None))
        )
    )


def _capabilities_from_processor(processor: Any) -> List[str]:
    """Best-effort capability list for indexing (not used for routing)."""
    caps: List[str] = []
    if hasattr(processor, "get_capabilities") and callable(processor.get_capabilities):
        try:
            raw = processor.get_capabilities() or {}
            for key in ("handles", "formats", "input_types", "supported_types"):
                val = raw.get(key)
                if isinstance(val, (list, tuple, set)):
                    for item in val:
                        if hasattr(item, "value"):
                            caps.append(str(item.value))
                        else:
                            caps.append(str(item))
        except Exception as exc:
            logger.debug("get_capabilities failed during index: %s", exc)
    if not caps and hasattr(processor, "get_supported_types"):
        try:
            caps = list(processor.get_supported_types())
        except Exception as exc:
            logger.debug("get_supported_types failed during index: %s", exc)
    # Deduplicate while preserving order
    seen: Set[str] = set()
    ordered: List[str] = []
    for c in caps:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


@dataclass
class ProcessorEntry:
    """Entry in the processor registry.

    Attributes:
        processor: Core-conforming processor instance
        priority: Higher values are checked first (default 10)
        name: Human-readable unique name
        enabled: Whether the processor participates in discovery
        metadata: Extra registration metadata
        capabilities: Indexed capability labels (informational)
        statistics: Runtime call statistics
    """

    processor: Any  # structurally ProcessorProtocol; avoid runtime isinstance
    priority: int = 10
    name: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(
        default_factory=lambda: {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_time_seconds": 0.0,
        }
    )

    def __post_init__(self) -> None:
        if not self.name:
            if hasattr(self.processor, "get_name") and callable(self.processor.get_name):
                try:
                    self.name = str(self.processor.get_name())
                except Exception:
                    self.name = self.processor.__class__.__name__
            else:
                self.name = self.processor.__class__.__name__
        if not self.capabilities:
            self.capabilities = _capabilities_from_processor(self.processor)


class ProcessorRegistry:
    """Canonical registry for core ProcessorProtocol implementers.

    Registration is fail-closed:

    * Bare legacy processors raise :class:`ProcessorRegistrationError` with
      guidance to use ``LegacyProtocolAdapter``.
    * Objects that fail :func:`is_processor` are rejected.
    * ``isinstance(..., ProcessorProtocol)`` is never called.

    Discovery calls only async ``can_handle`` (or awaits a coroutine returned
    by a sync-shaped but still registered object). There is no dual-API
    duck-type fallback in the selection loop.
    """

    def __init__(self) -> None:
        self._processors: List[ProcessorEntry] = []
        self._name_index: Dict[str, ProcessorEntry] = {}
        logger.info("Canonical ProcessorRegistry initialized")

    def register(
        self,
        processor: Any,
        priority: Optional[int] = None,
        name: Optional[str] = None,
        enabled: bool = True,
        capabilities: Optional[List[str]] = None,
        **metadata: Any,
    ) -> str:
        """Register a core-conforming processor.

        Args:
            processor: Instance that passes :func:`is_processor` (including
                :class:`LegacyProtocolAdapter` wrappers).
            priority: Selection priority (higher first). Defaults to
                ``get_priority()`` / capabilities priority / 10.
            name: Unique name (defaults to class / get_name()).
            enabled: Whether the processor is selectable.
            capabilities: Optional capability labels for reporting.
            **metadata: Stored on the entry.

        Returns:
            Registered processor name.

        Raises:
            ProcessorRegistrationError: Non-conforming or bare-legacy object.
            ValueError: Duplicate name.
        """
        if _is_bare_legacy(processor):
            raise ProcessorRegistrationError(
                f"Processor {processor.__class__.__name__} implements legacy "
                "can_process without can_handle. Wrap it with "
                "ipfs_datasets_py.processors.adapters.legacy_protocol_adapter."
                "LegacyProtocolAdapter before registration "
                "(implicit mixed routing is forbidden)."
            )
        if not is_processor(processor):
            raise ProcessorRegistrationError(
                f"Processor {processor.__class__.__name__} does not implement "
                "the canonical async ProcessorProtocol (async can_handle, "
                "async process, get_capabilities). Use is_processor() to "
                "validate; do not use isinstance against core ProcessorProtocol."
            )

        if priority is None:
            priority = self._resolve_priority(processor)

        if capabilities is None:
            capabilities = _capabilities_from_processor(processor)

        entry = ProcessorEntry(
            processor=processor,
            priority=int(priority),
            name=name or "",
            enabled=enabled,
            capabilities=list(capabilities),
            metadata=metadata,
        )

        if entry.name in self._name_index:
            raise ValueError(f"Processor with name '{entry.name}' already registered")

        self._processors.append(entry)
        self._name_index[entry.name] = entry
        self._processors.sort(key=lambda e: e.priority, reverse=True)

        logger.info(
            "Registered processor '%s' priority=%s capabilities=%s (total=%s)",
            entry.name,
            entry.priority,
            entry.capabilities,
            len(self._processors),
        )
        return entry.name

    @staticmethod
    def _resolve_priority(processor: Any) -> int:
        if hasattr(processor, "get_priority") and callable(processor.get_priority):
            try:
                return int(processor.get_priority())
            except Exception as exc:
                logger.warning("get_priority failed: %s", exc)
        if hasattr(processor, "get_capabilities") and callable(processor.get_capabilities):
            try:
                caps = processor.get_capabilities() or {}
                if "priority" in caps:
                    return int(caps["priority"])
            except Exception:
                pass
        return 10

    def unregister(self, name: str) -> bool:
        if name not in self._name_index:
            logger.warning("Processor '%s' not found for unregistration", name)
            return False
        self._name_index.pop(name)
        self._processors = [e for e in self._processors if e.name != name]
        logger.info(
            "Unregistered processor '%s' (remaining: %s)",
            name,
            len(self._processors),
        )
        return True

    def get_processor(self, name: str) -> Optional[Any]:
        entry = self._name_index.get(name)
        return entry.processor if entry else None

    async def get_processors(
        self,
        context: ProcessingContext,
        enabled_only: bool = True,
        limit: Optional[int] = None,
        *,
        allow_empty_registry: bool = True,
    ) -> List[Any]:
        """Return processors that can_handle *context*, priority-desc.

        Args:
            context: Canonical processing context.
            enabled_only: Skip disabled entries when True.
            limit: Optional maximum number of matches (None = all).
            allow_empty_registry: When False, raise
                :class:`EmptyProcessorSetError` if no processors are
                registered at all (prevents silent empty routing).

        Returns:
            Matching processor instances (not entries), highest priority first.
        """
        if not self._processors and not allow_empty_registry:
            raise EmptyProcessorSetError(
                "ProcessorRegistry has no registered processors; "
                "register core processors or LegacyProtocolAdapter wrappers "
                "before routing"
            )

        matching: List[Any] = []

        for entry in self._processors:
            if enabled_only and not entry.enabled:
                continue
            try:
                can_handle = await self._await_can_handle(entry.processor, context)
            except Exception as exc:
                logger.error(
                    "Error checking processor '%s': %s",
                    entry.name,
                    exc,
                    exc_info=True,
                )
                continue

            if can_handle:
                matching.append(entry.processor)
                logger.debug(
                    "Processor '%s' (priority %s) can handle %s",
                    entry.name,
                    entry.priority,
                    context.input_type,
                )
                if limit is not None and len(matching) >= limit:
                    break

        if not matching:
            logger.warning(
                "No suitable processors for %s (format=%s, registered=%s, enabled=%s)",
                context.input_type,
                context.get_format(),
                len(self._processors),
                self.get_enabled_count(),
            )
        else:
            logger.info(
                "Found %s suitable processor(s) for %s",
                len(matching),
                context.input_type,
            )
        return matching

    @staticmethod
    async def _await_can_handle(processor: Any, context: ProcessingContext) -> bool:
        """Invoke can_handle without dual-API duck typing."""
        if not hasattr(processor, "can_handle"):
            # Should be unreachable for registered processors (is_processor gate).
            return False
        method = processor.can_handle
        if not callable(method):
            return False
        if inspect.iscoroutinefunction(method):
            return bool(await method(context))
        result = method(context)
        if inspect.isawaitable(result):
            return bool(await result)
        return bool(result)

    async def find_processors(
        self,
        input_source: Union[str, Path, bytes],
        input_type: Optional[Union[InputType, str]] = None,
    ) -> List[Any]:
        """Legacy convenience: build a context and call get_processors."""
        if input_type is None:
            if isinstance(input_source, bytes):
                input_type = InputType.BINARY
            elif isinstance(input_source, (str, Path)):
                source_str = str(input_source)
                if source_str.startswith(("http://", "https://")):
                    input_type = InputType.URL
                elif Path(source_str).exists():
                    input_type = (
                        InputType.FOLDER if Path(source_str).is_dir() else InputType.FILE
                    )
                else:
                    input_type = InputType.TEXT
            else:
                input_type = InputType.BINARY
        elif isinstance(input_type, str):
            input_type = InputType.from_string(input_type)

        context = ProcessingContext(input_type=input_type, source=input_source)
        return await self.get_processors(context)

    def select_best_processor(
        self,
        processors: List[Any],
        input_source: Any = None,
    ) -> Optional[Any]:
        """Return the first processor (already priority-sorted) or None."""
        if not processors:
            return None
        best = processors[0]
        best_name = best.__class__.__name__
        if hasattr(best, "get_name") and callable(best.get_name):
            try:
                best_name = best.get_name()
            except Exception:
                pass
        logger.info("Selected processor '%s' for input: %s", best_name, input_source)
        return best

    def get_all_processors(self) -> List[Tuple[str, Any, int]]:
        return [(e.name, e.processor, e.priority) for e in self._processors]

    def list_processors(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for entry in self._processors:
            result[entry.name] = {
                "processor": entry.processor,
                "priority": entry.priority,
                "enabled": entry.enabled,
                "capabilities": list(entry.capabilities),
                "statistics": entry.statistics.copy(),
                "metadata": entry.metadata.copy(),
            }
        return result

    def get_processors_by_type(self, input_type: Union[str, InputType]) -> List[str]:
        if isinstance(input_type, InputType):
            input_type = input_type.value
        return [
            entry.name
            for entry in self._processors
            if input_type in entry.capabilities
        ]

    def get_enabled_count(self) -> int:
        return sum(1 for e in self._processors if e.enabled)

    def get_total_count(self) -> int:
        return len(self._processors)

    def enable(self, name: str) -> bool:
        entry = self._name_index.get(name)
        if entry:
            entry.enabled = True
            logger.info("Enabled processor '%s'", name)
            return True
        logger.warning("Processor '%s' not found for enable", name)
        return False

    def disable(self, name: str) -> bool:
        entry = self._name_index.get(name)
        if entry:
            entry.enabled = False
            logger.info("Disabled processor '%s'", name)
            return True
        logger.warning("Processor '%s' not found for disable", name)
        return False

    def record_call(
        self,
        processor_name: str,
        success: bool,
        duration_seconds: float,
    ) -> None:
        entry = self._name_index.get(processor_name)
        if entry:
            stats = entry.statistics
            stats["calls"] += 1
            if success:
                stats["successes"] += 1
            else:
                stats["failures"] += 1
            stats["total_time_seconds"] += duration_seconds

    def get_statistics(
        self,
        processor_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if processor_name:
            entry = self._name_index.get(processor_name)
            return entry.statistics.copy() if entry else {}
        return {entry.name: entry.statistics.copy() for entry in self._processors}

    def reset_statistics(self, processor_name: Optional[str] = None) -> None:
        blank = {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_time_seconds": 0.0,
        }
        if processor_name:
            entry = self._name_index.get(processor_name)
            if entry:
                entry.statistics = blank.copy()
            return
        for entry in self._processors:
            entry.statistics = blank.copy()

    def get_capabilities(self) -> Dict[str, Any]:
        """Aggregate capabilities for discovery/reporting.

        Includes both the consolidated registry keys (``supported_types``,
        ``by_type``) and the processor_registry keys (``processors``,
        ``supported_formats``, ``supported_input_types``) so callers of either
        former API continue to work after consolidation.
        """
        processors_info: List[Dict[str, Any]] = []
        all_input_types: Set[str] = set()
        all_formats: Set[str] = set()
        all_types: Set[str] = set()
        by_type: Dict[str, List[str]] = defaultdict(list)

        for entry in self._processors:
            for capability in entry.capabilities:
                all_types.add(capability)
                by_type[capability].append(entry.name)

            try:
                caps = entry.processor.get_capabilities()
                if "input_types" in caps:
                    types = caps["input_types"]
                    if isinstance(types, (list, set, tuple)):
                        for t in types:
                            all_input_types.add(
                                str(t.value) if hasattr(t, "value") else str(t)
                            )
                if "formats" in caps:
                    formats = caps["formats"]
                    if isinstance(formats, (list, set, tuple)):
                        all_formats.update(str(f) for f in formats)
                if "handles" in caps:
                    handles = caps["handles"]
                    if isinstance(handles, (list, set, tuple)):
                        all_formats.update(str(h) for h in handles)
                        all_types.update(str(h) for h in handles)

                processors_info.append(
                    {
                        "name": entry.name,
                        "priority": entry.priority,
                        "enabled": entry.enabled,
                        "capabilities": caps,
                        "metadata": entry.metadata,
                    }
                )
            except Exception as exc:
                logger.error(
                    "Error getting capabilities from '%s': %s", entry.name, exc
                )
                processors_info.append(
                    {
                        "name": entry.name,
                        "priority": entry.priority,
                        "enabled": entry.enabled,
                        "error": str(exc),
                    }
                )

        return {
            "total_processors": len(self._processors),
            "enabled_processors": self.get_enabled_count(),
            "processors": processors_info,
            "supported_input_types": sorted(all_input_types),
            "supported_formats": sorted(all_formats),
            "supported_types": sorted(all_types | all_formats | all_input_types),
            "by_type": dict(by_type),
        }

    def clear(self) -> None:
        count = len(self._processors)
        self._processors.clear()
        self._name_index.clear()
        logger.info("Cleared registry (%s processors removed)", count)

    def __len__(self) -> int:
        return len(self._processors)

    def __contains__(self, name: str) -> bool:
        return name in self._name_index

    def __repr__(self) -> str:
        return (
            f"ProcessorRegistry(total={len(self._processors)}, "
            f"enabled={self.get_enabled_count()})"
        )


# Shared global singleton (also re-exported by processor_registry)
_global_registry: Optional[ProcessorRegistry] = None


def get_global_registry() -> ProcessorRegistry:
    """Return the process-wide canonical ProcessorRegistry singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ProcessorRegistry()
        logger.info("Created global processor registry")
    return _global_registry


def reset_global_registry() -> ProcessorRegistry:
    """Replace the global registry with a fresh empty instance (tests)."""
    global _global_registry
    _global_registry = ProcessorRegistry()
    return _global_registry


__all__ = [
    "ProcessorEntry",
    "ProcessorRegistry",
    "ProcessorRegistrationError",
    "EmptyProcessorSetError",
    "get_global_registry",
    "reset_global_registry",
    # Re-export for type annotations / compatibility
    "ProcessorProtocol",
]

"""UniversalProcessor - async single entry point for canonical routing.

PATLAW-003: routes exclusively through the canonical core registry and
core ``ProcessorProtocol`` (async ``can_handle`` / ``process``). Legacy
processors enter only via
:class:`~ipfs_datasets_py.processors.adapters.legacy_protocol_adapter.LegacyProtocolAdapter`.

Empty processor sets are never silent successes: zero registered processors
or zero can_handle matches yield ``ProcessingResult(success=False, ...)``
with explicit errors.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Dict, List, Optional, Union

try:
    import anyio

    ANYIO_AVAILABLE = True
except ImportError:
    ANYIO_AVAILABLE = False
    anyio = None  # type: ignore

from .protocol import InputType, ProcessingContext, ProcessingResult, is_processor
from .input_detector import InputDetector
from .registry import (
    EmptyProcessorSetError,
    ProcessorRegistry,
    get_global_registry,
)

logger = logging.getLogger(__name__)


class UniversalProcessor:
    """Universal processor that routes via the canonical ProcessorRegistry.

    Attributes:
        registry: Canonical ProcessorRegistry
        detector: InputDetector for classifying bare inputs
        max_retries: Default max retry attempts per processor
        retry_delay: Base delay between retries (seconds)
    """

    def __init__(
        self,
        registry: Optional[ProcessorRegistry] = None,
        detector: Optional[InputDetector] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.registry = registry if registry is not None else get_global_registry()
        self.detector = detector if detector is not None else InputDetector()
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        logger.info(
            "UniversalProcessor initialized with %s processors, "
            "max_retries=%s, retry_delay=%s",
            len(self.registry),
            max_retries,
            retry_delay,
        )

    async def process(
        self,
        input_data: Any,
        context: Optional[ProcessingContext] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        use_multiple: bool = False,
        max_processors: Optional[int] = None,
        timeout: Optional[float] = None,
        **options: Any,
    ) -> ProcessingResult:
        """Process input via deterministic core-protocol routing.

        Steps:
        1. Detect input type when *context* is omitted
        2. Discover processors with ``registry.get_processors``
        3. Try processors in priority order with retries
        4. Return the first successful core ``ProcessingResult``
           (or merge when *use_multiple* is True)
        """
        if not ANYIO_AVAILABLE:
            raise ImportError(
                "anyio is required for async processing. "
                "Install it with: pip install anyio"
            )

        max_retries = max_retries if max_retries is not None else self.max_retries
        retry_delay = retry_delay if retry_delay is not None else self.retry_delay
        processing_context = context

        async def _process_impl() -> ProcessingResult:
            nonlocal processing_context

            if processing_context is None:
                try:
                    processing_context = self.detector.detect(input_data, **options)
                    logger.info(
                        "Detected input type: %s, format: %s",
                        processing_context.input_type.value,
                        processing_context.get_format(),
                    )
                except Exception as e:
                    logger.error("Error detecting input: %s", e, exc_info=True)
                    return ProcessingResult(
                        success=False,
                        errors=[f"Input detection failed: {e}"],
                    )
            # Merge call-site options into context for adapters
            if options:
                processing_context.options = {
                    **(processing_context.options or {}),
                    **options,
                }

            # Fail closed on empty registry (no silent empty set)
            if len(self.registry) == 0:
                logger.error(
                    "UniversalProcessor routing failed: registry is empty"
                )
                return ProcessingResult(
                    success=False,
                    errors=[
                        "No processors registered in the canonical registry; "
                        "register core processors or LegacyProtocolAdapter "
                        "wrappers before processing"
                    ],
                    metadata={
                        "routing": "empty_registry",
                        "registered": 0,
                    },
                )

            try:
                processors = await self.registry.get_processors(
                    processing_context,
                    limit=max_processors,
                    allow_empty_registry=True,
                )
            except EmptyProcessorSetError as e:
                return ProcessingResult(
                    success=False,
                    errors=[str(e)],
                    metadata={"routing": "empty_registry"},
                )
            except Exception as e:
                logger.error("Error finding processors: %s", e, exc_info=True)
                return ProcessingResult(
                    success=False,
                    errors=[f"Processor selection failed: {e}"],
                )

            logger.info("Found %s suitable processors", len(processors))

            if not processors:
                return ProcessingResult(
                    success=False,
                    errors=[
                        "No suitable processors found for this input type "
                        f"({processing_context.input_type.value}, "
                        f"format={processing_context.get_format()!r}); "
                        f"registry has {len(self.registry)} registered "
                        f"({self.registry.get_enabled_count()} enabled)"
                    ],
                    metadata={
                        "routing": "no_match",
                        "registered": len(self.registry),
                        "enabled": self.registry.get_enabled_count(),
                        "input_type": processing_context.input_type.value,
                        "format": processing_context.get_format(),
                    },
                )

            results: List[ProcessingResult] = []
            all_errors: List[str] = []

            for processor in processors:
                processor_name = self._processor_name(processor)

                for attempt in range(max_retries):
                    try:
                        logger.info(
                            "Attempting %s (attempt %s/%s)",
                            processor_name,
                            attempt + 1,
                            max_retries,
                        )

                        # Registered processors already passed is_processor;
                        # re-check can_handle only via the canonical method.
                        if not await self._can_handle(processor, processing_context):
                            logger.info(
                                "%s cannot handle this context", processor_name
                            )
                            break  # next processor

                        start_time = time.time()
                        result = await self._run_process(
                            processor, processing_context
                        )
                        elapsed = time.time() - start_time

                        if not isinstance(result, ProcessingResult):
                            error_msg = (
                                f"{processor_name} returned non-core result "
                                f"{type(result)!r}"
                            )
                            logger.warning(error_msg)
                            all_errors.append(error_msg)
                            break

                        self.registry.record_call(
                            processor_name if processor_name in self.registry else (
                                self._registered_name(processor) or processor_name
                            ),
                            success=bool(result.success),
                            duration_seconds=elapsed,
                        )

                        if result.success:
                            logger.info(
                                "%s succeeded in %.2fs", processor_name, elapsed
                            )
                            # Annotate routing metadata without clobbering adapter fields
                            result.metadata.setdefault("routed_processor", processor_name)
                            result.metadata.setdefault("routing", "canonical_core")
                            results.append(result)
                            if not use_multiple:
                                return result
                            break
                        else:
                            error_msg = f"{processor_name} failed: {result.errors}"
                            logger.warning(error_msg)
                            all_errors.append(error_msg)
                            if attempt < max_retries - 1:
                                delay = retry_delay * (2 ** attempt)
                                await anyio.sleep(delay)

                    except Exception as e:
                        error_msg = (
                            f"{processor_name} raised exception "
                            f"(attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        logger.error(error_msg, exc_info=True)
                        all_errors.append(error_msg)
                        if attempt < max_retries - 1:
                            delay = retry_delay * (2 ** attempt)
                            await anyio.sleep(delay)

                if not use_multiple and results:
                    break

            if results:
                if len(results) == 1:
                    return results[0]
                logger.info("Aggregating %s successful results", len(results))
                merged = results[0]
                for extra in results[1:]:
                    merged.merge(extra)
                return merged

            return ProcessingResult(
                success=False,
                errors=all_errors or ["All processors failed"],
                metadata={
                    "routing": "all_failed",
                    "processors_tried": len(processors),
                },
            )

        try:
            if timeout:
                with anyio.fail_after(timeout):
                    return await _process_impl()
            return await _process_impl()
        except Exception as e:
            if ANYIO_AVAILABLE:
                try:
                    cancelled_exc = anyio.get_cancelled_exc_class()
                    if isinstance(e, cancelled_exc):
                        logger.error(
                            "Processing timeout/cancelled after %ss", timeout
                        )
                        return ProcessingResult(
                            success=False,
                            errors=[f"Processing timeout after {timeout}s"],
                        )
                except Exception as exc_err:
                    logger.debug(
                        "Could not check cancellation exception: %s", exc_err
                    )

            logger.error("Unexpected error in process(): %s", e, exc_info=True)
            return ProcessingResult(
                success=False,
                errors=[f"Unexpected processing error: {e}"],
            )

    @staticmethod
    async def _can_handle(processor: Any, context: ProcessingContext) -> bool:
        if not hasattr(processor, "can_handle"):
            return False
        method = processor.can_handle
        if inspect.iscoroutinefunction(method):
            return bool(await method(context))
        result = method(context)
        if inspect.isawaitable(result):
            return bool(await result)
        return bool(result)

    @staticmethod
    async def _run_process(
        processor: Any, context: ProcessingContext
    ) -> ProcessingResult:
        method = processor.process
        if inspect.iscoroutinefunction(method):
            return await method(context)
        result = method(context)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _processor_name(processor: Any) -> str:
        if hasattr(processor, "get_name") and callable(processor.get_name):
            try:
                return str(processor.get_name())
            except Exception:
                pass
        if hasattr(processor, "name") and isinstance(processor.name, str):
            return processor.name
        return processor.__class__.__name__

    def _registered_name(self, processor: Any) -> Optional[str]:
        for name, proc, _priority in self.registry.get_all_processors():
            if proc is processor:
                return name
        return None

    async def process_batch(
        self,
        inputs: List[Any],
        parallel: bool = False,
        **options: Any,
    ) -> List[ProcessingResult]:
        if not ANYIO_AVAILABLE:
            raise ImportError(
                "anyio is required for async batch processing. "
                "Install it with: pip install anyio"
            )

        logger.info(
            "Processing batch of %s inputs (parallel=%s)", len(inputs), parallel
        )

        if parallel:
            results: List[Optional[ProcessingResult]] = [None] * len(inputs)

            async def process_item(index: int, input_data: Any) -> None:
                try:
                    results[index] = await self.process(input_data, **options)
                except Exception as e:
                    logger.error(
                        "Error processing batch item %s: %s",
                        index + 1,
                        e,
                        exc_info=True,
                    )
                    results[index] = ProcessingResult(
                        success=False,
                        errors=[f"Batch processing error: {e}"],
                    )

            async with anyio.create_task_group() as tg:
                for i, input_data in enumerate(inputs):
                    tg.start_soon(process_item, i, input_data)
            final: List[ProcessingResult] = [
                r
                if r is not None
                else ProcessingResult(
                    success=False, errors=["Batch item produced no result"]
                )
                for r in results
            ]
        else:
            final = []
            for i, input_data in enumerate(inputs):
                logger.info("Processing batch item %s/%s", i + 1, len(inputs))
                final.append(await self.process(input_data, **options))

        success_count = sum(1 for r in final if r.success)
        logger.info(
            "Batch complete: %s/%s succeeded", success_count, len(inputs)
        )
        return final

    def register_processor(
        self,
        processor: Any,
        priority: int = 10,
        name: Optional[str] = None,
        **metadata: Any,
    ) -> str:
        """Register a core processor (or LegacyProtocolAdapter) on the registry.

        Returns the registered name. Raises ProcessorRegistrationError for
        bare legacy processors or non-conforming objects.
        """
        registered = self.registry.register(
            processor, priority=priority, name=name, **metadata
        )
        logger.info(
            "Registered processor %s with priority %s",
            registered,
            priority,
        )
        return registered

    def unregister_processor(self, name: str) -> bool:
        result = self.registry.unregister(name)
        logger.info("Unregistered processor %s (ok=%s)", name, result)
        return result

    def get_registered_processors(self) -> List[tuple]:
        """Return (name, processor, priority) tuples from the registry."""
        return self.registry.get_all_processors()

    def get_capabilities(self) -> Dict[str, Any]:
        return self.registry.get_capabilities()


_global_processor: Optional[UniversalProcessor] = None


def get_universal_processor() -> UniversalProcessor:
    """Return the process-wide UniversalProcessor singleton."""
    global _global_processor
    if _global_processor is None:
        _global_processor = UniversalProcessor()
        logger.info("Created global UniversalProcessor instance")
    return _global_processor


def reset_universal_processor(
    registry: Optional[ProcessorRegistry] = None,
) -> UniversalProcessor:
    """Replace the global UniversalProcessor (primarily for tests)."""
    global _global_processor
    _global_processor = UniversalProcessor(registry=registry)
    return _global_processor


async def process(input_data: Any, **options: Any) -> ProcessingResult:
    """Process *input_data* with the global UniversalProcessor."""
    if not ANYIO_AVAILABLE:
        raise ImportError(
            "anyio is required for async processing. "
            "Install it with: pip install anyio"
        )
    processor = get_universal_processor()
    return await processor.process(input_data, **options)


async def process_batch(inputs: List[Any], **options: Any) -> List[ProcessingResult]:
    """Batch-process with the global UniversalProcessor."""
    if not ANYIO_AVAILABLE:
        raise ImportError(
            "anyio is required for async batch processing. "
            "Install it with: pip install anyio"
        )
    processor = get_universal_processor()
    return await processor.process_batch(inputs, **options)


__all__ = [
    "UniversalProcessor",
    "get_universal_processor",
    "reset_universal_processor",
    "process",
    "process_batch",
    "InputType",
    "is_processor",
]

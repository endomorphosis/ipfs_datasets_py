"""Lightweight profiling utilities for optimizers.

This module provides a small, stable API for timing (and optional memory)
profiling with structured JSON log emission.

It is intentionally low-overhead when disabled.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, Mapping, Optional

from .structured_logging import with_schema

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfilingConfig:
    """Configuration for profiling hooks."""

    enabled: bool = False
    memory_profiling: bool = False
    min_duration_ms: float = 0.0
    emit_logs: bool = True

    def __post_init__(self) -> None:
        if self.min_duration_ms < 0:
            object.__setattr__(self, "min_duration_ms", 0.0)

        if self.memory_profiling:
            # Gracefully degrade if psutil isn't installed.
            try:
                import psutil  # type: ignore[import-untyped]  # noqa: F401
            except ImportError:
                object.__setattr__(self, "memory_profiling", False)


@dataclass
class ProfileResult:
    """Result object returned from profiling contexts."""

    section_name: str
    duration_ms: float = 0.0
    memory_delta_mb: Optional[float] = None
    peak_memory_mb: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        def _round(v: Optional[float]) -> Optional[float]:
            if v is None:
                return None
            return round(float(v), 2)

        payload: Dict[str, Any] = {
            "section_name": self.section_name,
            "duration_ms": _round(self.duration_ms),
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        if self.memory_delta_mb is not None:
            payload["memory_delta_mb"] = _round(self.memory_delta_mb)
        if self.peak_memory_mb is not None:
            payload["peak_memory_mb"] = _round(self.peak_memory_mb)
        return payload


_GLOBAL_CONFIG = ProfilingConfig(enabled=False)


def set_profiling_config(config: ProfilingConfig) -> None:
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = config


def get_profiling_config() -> ProfilingConfig:
    return _GLOBAL_CONFIG


def enable_profiling(
    *,
    memory: bool = False,
    min_duration_ms: float = 0.0,
    emit_logs: bool = True,
) -> None:
    set_profiling_config(
        ProfilingConfig(
            enabled=True,
            memory_profiling=bool(memory),
            min_duration_ms=float(min_duration_ms),
            emit_logs=bool(emit_logs),
        )
    )


def disable_profiling() -> None:
    set_profiling_config(ProfilingConfig(enabled=False))


def _get_memory_mb() -> float:
    import os

    try:
        import psutil

        proc = psutil.Process(os.getpid())
        return float(proc.memory_info().rss) / (1024.0 * 1024.0)
    except (ImportError, AttributeError, OSError, RuntimeError):
        return 0.0


def _emit_profiling_log(result: ProfileResult, *, config: ProfilingConfig) -> None:
    if not config.emit_logs:
        return
    if result.duration_ms < config.min_duration_ms:
        return

    payload: Dict[str, Any] = {
        "event": "profiling_result",
        "optimizer_pipeline": "common",
        **result.to_dict(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }

    try:
        enriched = with_schema(payload)
        logger.info("PROFILING: %s", json.dumps(enriched, default=str))
    except (TypeError, ValueError, RuntimeError) as exc:  # pragma: no cover
        logger.debug("Failed to emit profiling log: %s", exc)


@contextlib.contextmanager
def profile_section(
    section_name: str,
    *,
    metadata: Optional[Mapping[str, Any]] = None,
    config: Optional[ProfilingConfig] = None,
) -> Generator[ProfileResult, None, None]:
    cfg = config or get_profiling_config()
    result = ProfileResult(section_name=section_name)

    if metadata:
        result.metadata.update(dict(metadata))

    if not cfg.enabled:
        yield result
        return

    start_t = time.perf_counter()
    start_mem = _get_memory_mb() if cfg.memory_profiling else None

    try:
        yield result
    finally:
        end_t = time.perf_counter()
        result.duration_ms = (end_t - start_t) * 1000.0

        if cfg.memory_profiling and start_mem is not None:
            end_mem = _get_memory_mb()
            result.memory_delta_mb = end_mem - start_mem
            # Peak memory isn't trivial without tracemalloc/psutil sampling;
            # keep optional and unset unless implemented.

        _emit_profiling_log(result, config=cfg)


@contextlib.contextmanager
def profile_batch(
    section_name: str,
    batch_size: int,
    *,
    metadata: Optional[Mapping[str, Any]] = None,
    config: Optional[ProfilingConfig] = None,
) -> Generator[ProfileResult, None, None]:
    cfg = config or get_profiling_config()

    # Suppress inner emission so we can add per_item_ms before logging.
    inner_cfg = cfg
    if cfg.emit_logs:
        inner_cfg = dataclasses.replace(cfg, emit_logs=False)

    with profile_section(section_name, metadata=metadata, config=inner_cfg) as result:
        result.metadata.setdefault("batch_size", int(batch_size))
        yield result

    size = int(batch_size)
    if size > 0:
        result.metadata["per_item_ms"] = round(result.duration_ms / float(size), 2)
    else:
        result.metadata["per_item_ms"] = 0.0

    if cfg.enabled:
        _emit_profiling_log(result, config=cfg)


def profile_method(
    section_name: Optional[str] = None,
    *,
    include_args: bool = False,
    config: Optional[ProfilingConfig] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        name = section_name or f"{getattr(func, '__module__', '')}.{getattr(func, '__qualname__', func.__name__)}"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            meta: Dict[str, Any] = {}
            if include_args:
                meta["args_count"] = int(len(args) + len(kwargs))
                meta["kwargs_keys"] = sorted([str(k) for k in kwargs.keys()])

            with profile_section(name, metadata=meta or None, config=config):
                return func(*args, **kwargs)

        return wrapper

    return decorator

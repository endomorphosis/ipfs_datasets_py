"""Benchmark conftest.py.

Provides a ``benchmark`` stub fixture when pytest-benchmark is not installed.
This ensures the benchmark files can be imported and collected even without
the pytest-benchmark package, allowing ``pytest benchmarks/ -v`` to run
without errors in environments where pytest-benchmark is unavailable.

When pytest-benchmark IS installed the stub is never used — the real
``benchmark`` fixture from the plugin takes precedence.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import pytest


# ---------------------------------------------------------------------------
# Stub benchmark fixture (only registered when pytest-benchmark is absent)
# ---------------------------------------------------------------------------

try:
    import pytest_benchmark  # noqa: F401  # type: ignore
    # pytest-benchmark is installed — no stub needed.
    _HAVE_BENCHMARK = True
except ImportError:
    _HAVE_BENCHMARK = False


if not _HAVE_BENCHMARK:
    class _BenchmarkStub:
        """Minimal substitute for the pytest-benchmark ``benchmark`` fixture.

        When pytest-benchmark is not installed the test body is executed once
        and the result is discarded.  No timing statistics are collected.
        """

        def __call__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        # anyio-based tests wrap an async callable; support that too.
        def pedantic(
            self,
            func: Callable[..., Any],
            *args: Any,
            setup: Callable[[], None] | None = None,
            rounds: int = 1,
            warmup_rounds: int = 0,
            iterations: int = 1,
            **kwargs: Any,
        ) -> Any:
            if setup is not None:
                setup()
            return func(*args, **kwargs)

    @pytest.fixture()
    def benchmark() -> _BenchmarkStub:  # type: ignore[misc]
        """Stub benchmark fixture (pytest-benchmark not installed)."""
        return _BenchmarkStub()

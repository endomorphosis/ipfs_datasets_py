"""Trio bridge utilities for the MCP server.

This mirrors the MCP++ pattern (mcplusplus_module.trio.bridge.run_in_trio), but
is hosted in ipfs_datasets_py so mcp_server tools can depend on it without
importing mcplusplus_module directly.

Use cases:
- libp2p client helpers are Trio-native; mcp_server tools run under AnyIO.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, TypeVar

import anyio
import sniffio

from ipfs_datasets_py.mcp_server.exceptions import RuntimeExecutionError

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_in_trio(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a callable in a Trio context.

    If already in Trio, executes inline. Otherwise runs a Trio event loop in a
    worker thread via `anyio.run(..., backend='trio')`.
    """

    try:
        if sniffio.current_async_library() == "trio":
            result = func(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result
    except sniffio.AsyncLibraryNotFoundError:
        pass
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(f"Trio not available: {e}", exc_info=True)
        raise RuntimeExecutionError(f"Trio runtime unavailable: {e}")
    except Exception as e:
        # If detection fails for any reason, fall back to thread runner.
        logger.debug("Async library detection failed; falling back to Trio thread runner", exc_info=True)

    def _runner() -> T:
        async def _inner() -> T:
            result = func(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return anyio.run(_inner, backend="trio")

    return await anyio.to_thread.run_sync(_runner)


__all__ = ["run_in_trio"]

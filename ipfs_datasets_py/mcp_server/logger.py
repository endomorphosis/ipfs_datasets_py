"""
Logger configuration for IPFS Datasets MCP server.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


_OPTIONAL_WARNING_PATTERNS = (
    re.compile(r"^Alert system not available$"),
    re.compile(r"^Email processor not available$"),
    re.compile(r"^FileTypeDetector not available$"),
    re.compile(r"^LogicProcessor not available: .+"),
    re.compile(r"^Hugging Face datasets not available: .+"),
    re.compile(r"^P2P workflow scheduler not available$"),
    re.compile(r"^search_embeddings using mock implementation due to missing dependencies: .+"),
    re.compile(r"^BraveSearchClient not available(?: - install web_archiving dependencies)?$"),
    re.compile(r"^Web archiving not available$"),
    re.compile(r"^Common Crawl search not available$"),
    re.compile(r"^common/ shared components not available for query processing$"),
)


class _ExpectedOptionalDependencyFilter(logging.Filter):
    """Suppress repeated warning noise from expected optional dependency fallbacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True

        try:
            message = record.getMessage()
        except Exception:
            return True

        return not any(pattern.match(message) for pattern in _OPTIONAL_WARNING_PATTERNS)


_OPTIONAL_WARNING_FILTER = _ExpectedOptionalDependencyFilter()


def _install_optional_warning_filter() -> None:
    """Attach the optional dependency filter to the active root logger and handlers."""
    root_logger = logging.getLogger()
    root_filters = list(getattr(root_logger, "filters", []) or [])
    if not any(existing is _OPTIONAL_WARNING_FILTER for existing in root_filters) and hasattr(root_logger, "addFilter"):
        root_logger.addFilter(_OPTIONAL_WARNING_FILTER)

    for handler in list(getattr(root_logger, "handlers", []) or []):
        handler_filters = list(getattr(handler, "filters", []) or [])
        if any(existing is _OPTIONAL_WARNING_FILTER for existing in handler_filters):
            continue
        if hasattr(handler, "addFilter"):
            handler.addFilter(_OPTIONAL_WARNING_FILTER)


mcp_log_path = Path(__file__).parent / "mcp_server.log"

# Configure root logger.
# Under pytest, the root logger is often already configured. In that case,
# calling basicConfig() is a no-op, but eagerly constructing FileHandler would
# still open the file and then be garbage-collected, triggering ResourceWarning
# about an unclosed file. Only create/attach handlers when we will actually
# configure logging.
_root_logger = logging.getLogger()
if not _root_logger.handlers:
    mcp_log_path.touch()  # Create the log file if it doesn't exist
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            # logging.StreamHandler(sys.stdout),
            logging.FileHandler(mcp_log_path, mode="a"),
        ],
    )

_install_optional_warning_filter()

# Create logger for this module
logger = logging.getLogger("ipfs_datasets.mcp_server")

# Create logger for MCP-specific messages
mcp_logger = logging.getLogger("ipfs_datasets.mcp")

# Set log levels
logger.setLevel(logging.INFO)
mcp_logger.setLevel(logging.INFO)

# Ensure the log directory exists
log_dir = Path.home() / ".ipfs_datasets"
log_dir.mkdir(exist_ok=True)


def log_mcp_event(
    message: str,
    *,
    level: str = "INFO",
    logger_name: str = "ipfs_datasets.mcp_server",
    extra: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
    operation_id: Optional[str] = None,
) -> None:
    """Log an MCP operational event to the legacy sink and observability shadow.

    Legacy file / stderr handlers remain the selected authority under DQK-077
    shadow mode. When the process-local observability shadow repository is
    configured, a typed redacted projection is dual-written with a stable
    event ID and parity receipt.
    """

    target = logging.getLogger(logger_name)
    level_no = getattr(logging, str(level).upper(), logging.INFO)
    if not isinstance(level_no, int):
        level_no = logging.INFO
    target.log(level_no, message, extra=dict(extra or {}))

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            route_mcp_log_event,
        )

        route_mcp_log_event(
            message=message,
            level=str(level).upper(),
            logger_name=logger_name,
            extra=extra,
            event_id=event_id,
            operation_id=operation_id,
        )
    except Exception:
        pass


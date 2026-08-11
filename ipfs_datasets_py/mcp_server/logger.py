"""
Logger configuration for IPFS Datasets MCP server.
"""
import logging
import re
import sys
from pathlib import Path


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
    extra: dict | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
) -> str | None:
    """Emit an MCP log line and optionally project it into the observability shadow.

    Legacy file / stderr sinks remain authority under DQK-077 shadow mode.
    Returns the stable event_id when shadow routing is active, else ``None``.
    """
    level_name = str(level or "INFO").upper()
    log_fn = {
        "DEBUG": logger.debug,
        "INFO": logger.info,
        "WARNING": logger.warning,
        "ERROR": logger.error,
        "CRITICAL": logger.critical,
    }.get(level_name, logger.info)
    try:
        if extra:
            log_fn(message, extra=dict(extra))
        else:
            log_fn(message)
    except Exception:
        logger.debug("mcp log emission failed", exc_info=True)

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            route_mcp_log_event,
        )

        receipt = route_mcp_log_event(
            message,
            level=level_name,
            logger_name=logger_name,
            extra=extra,
            event_id=event_id,
            operation_id=operation_id,
        )
        return receipt.event_id if receipt is not None else None
    except Exception:
        logger.debug(
            "observability shadow routing skipped for mcp log event",
            exc_info=True,
        )
        return None

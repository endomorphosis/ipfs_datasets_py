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

# Ensure the log directory exists (legacy file sink remains selected authority
# under DQK-077 shadow mode).
log_dir = Path.home() / ".ipfs_datasets"
log_dir.mkdir(exist_ok=True)


def log_mcp_event(
    message: str,
    *,
    level: int = logging.INFO,
    event_type: str = "mcp.log",
    actor: str = "mcp_server",
    **attributes,
) -> None:
    """Log an MCP server event and project it into the typed shadow catalog.

    The legacy ``mcp_server.log`` file handler remains the selected authority
    under DQK-077 shadow mode. When the observability shadow repository is
    configured, a redacted typed audit record is dual-written with a parity
    receipt and content-addressed evidence blob.
    """

    # Always write through the legacy logger first.
    logger.log(level, message, extra=attributes if attributes else None)

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            ObservabilityProducer,
            derive_stable_event_id,
            record_observability_event,
        )
    except Exception:
        return

    seed = attributes.get("event_id") or f"{event_type}:{message}:{actor}"
    event_id = derive_stable_event_id(
        producer=ObservabilityProducer.MCP_LOGGER.value,
        action=event_type,
        actor=actor,
        detail=str(message),
        seed=str(seed),
    )
    outcome = "error" if level >= logging.ERROR else "info"
    if level >= logging.ERROR:
        outcome = "error"
    elif "fail" in str(event_type).lower():
        outcome = "failed"
    elif "complete" in str(event_type).lower() or "success" in str(event_type).lower():
        outcome = "succeeded"

    record_observability_event(
        producer=ObservabilityProducer.MCP_LOGGER,
        action=event_type,
        actor=actor,
        outcome=outcome,
        detail=str(message),
        attributes=dict(attributes),
        event_id=event_id,
        operation_id=f"op-mcp-{event_id}",
        raw_payload={"message": message, "event_type": event_type, **attributes},
    )

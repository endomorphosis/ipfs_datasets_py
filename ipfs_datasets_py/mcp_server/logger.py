"""
Logger configuration for IPFS Datasets MCP server.

DQK-079: mutable file sinks (mcp_server.log / FileHandler) are disabled by
default. Only ephemeral human-readable console logs remain; DuckDB is the
progress/completion authority after cutover.
"""

import logging
import re
import sys
from pathlib import Path

from ipfs_datasets_py.logic.observability.structured_logging import (
    ObservabilityMutableFileSinkError,
    assert_mutable_file_sink_allowed,
    console_grants_completion_authority,
    console_grants_progress_authority,
    get_observability_filesystem_guard,
    sanitize_publication_view,
)


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
    if not any(existing is _OPTIONAL_WARNING_FILTER for existing in root_filters) and hasattr(
        root_logger, "addFilter"
    ):
        root_logger.addFilter(_OPTIONAL_WARNING_FILTER)

    for handler in list(getattr(root_logger, "handlers", []) or []):
        handler_filters = list(getattr(handler, "filters", []) or [])
        if any(existing is _OPTIONAL_WARNING_FILTER for existing in handler_filters):
            continue
        if hasattr(handler, "addFilter"):
            handler.addFilter(_OPTIONAL_WARNING_FILTER)


# Historical path retained for explicit export only — never auto-created (DQK-079).
mcp_log_path = Path(__file__).parent / "mcp_server.log"

# Configure root logger with ephemeral console only (no FileHandler / no touch).
# Under pytest, the root logger is often already configured. In that case,
# calling basicConfig() is a no-op.
_root_logger = logging.getLogger()
if not _root_logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
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

# Config directory may exist for other MCP settings; it is not a log authority.
log_dir = Path.home() / ".ipfs_datasets"
try:
    log_dir.mkdir(exist_ok=True)
except OSError:
    pass


def attach_mcp_file_sink(path: Path | str | None = None) -> None:
    """Attach a mutable MCP file sink only when the writer guard permits it.

    Intended for explicit operator export/debug, not runtime authority.
    """
    target = Path(path) if path is not None else mcp_log_path
    assert_mutable_file_sink_allowed(target, kind="mcp_log", operation="attach")
    handler = logging.FileHandler(target, mode="a")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)


def log_mcp_event(
    message: str,
    *,
    level: int = logging.INFO,
    event_type: str = "mcp.log",
    actor: str = "mcp_server",
    **attributes,
) -> None:
    """Log an MCP server event and project it into DuckDB cutover or shadow.

    Under DQK-079, console/stderr is an ephemeral disposable projection only
    and cannot satisfy progress or completion authority. Typed DuckDB state
    (DQK-078 cutover) is the observability authority. Mutable ``mcp_server.log``
    is not created or written by default.
    """

    # Ephemeral console projection only (never progress/completion authority).
    logger.log(level, message, extra=attributes if attributes else None)

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            ObservabilityProducer,
            derive_stable_event_id,
        )
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            try_record_observability_event,
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

    try_record_observability_event(
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


def publication_view(
    message: str = "",
    *,
    event_type: str = "mcp.log",
    **attributes,
) -> dict:
    """Sanitized publication view of an MCP log event (no secrets / high-card)."""

    view = sanitize_publication_view(
        {"message": message, "event_type": event_type, **attributes}
    )
    view["console_grants_progress_authority"] = console_grants_progress_authority()
    view["console_grants_completion_authority"] = console_grants_completion_authority()
    view["mcp_log_path_authority"] = False
    return view


def export_mcp_log(path: Path | str) -> str:
    """Explicit deterministic export placeholder for MCP logs (not authority)."""

    target = Path(path)
    guard = get_observability_filesystem_guard()
    with guard.permit_export():
        assert_mutable_file_sink_allowed(target, kind="mcp_log", operation="export")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# MCP log export (non-authoritative; owner_task=DQK-079)\n",
            encoding="utf-8",
        )
    return str(target)

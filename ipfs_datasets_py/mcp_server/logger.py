"""
Logger configuration for IPFS Datasets MCP server.

After DQK-079 canary cutover (``db-primary`` / ``export-only``), the legacy
``mcp_server.log`` FileHandler is not attached. Only ephemeral human-readable
console/stderr logs remain as disposable projections; typed DuckDB
observability is the sole progress/audit authority.
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


def _legacy_file_sinks_allowed() -> bool:
    try:
        from ipfs_datasets_py.logic.observability.structured_logging import (
            legacy_mutable_file_sinks_allowed,
        )

        return bool(legacy_mutable_file_sinks_allowed())
    except Exception:
        return True


mcp_log_path = Path(__file__).parent / "mcp_server.log"
log_dir = Path.home() / ".ipfs_datasets"


def _configure_root_logging() -> None:
    """Configure root logging with console-only sinks after DQK-079 canary.

    FileHandler construction is guarded by
    :func:`assert_mutable_file_sink_allowed` /
    :func:`legacy_mutable_file_sinks_allowed`.
    """
    _root_logger = logging.getLogger()
    if _root_logger.handlers:
        return

    handlers: list[logging.Handler] = []
    if _legacy_file_sinks_allowed():
        try:
            from ipfs_datasets_py.logic.observability.structured_logging import (
                assert_mutable_file_sink_allowed,
            )

            assert_mutable_file_sink_allowed(mcp_log_path, kind="mcp_server_log")
            mcp_log_path.touch()
            handlers.append(logging.FileHandler(mcp_log_path, mode="a"))
        except Exception:
            handlers.append(logging.StreamHandler(sys.stderr))
    else:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _ensure_home_log_dir() -> None:
    """Create ``~/.ipfs_datasets`` only while legacy file sinks are allowed."""
    if not _legacy_file_sinks_allowed():
        return
    try:
        log_dir.mkdir(exist_ok=True)
    except OSError:
        pass


_configure_root_logging()
_install_optional_warning_filter()
_ensure_home_log_dir()

# Create logger for this module
logger = logging.getLogger("ipfs_datasets.mcp_server")

# Create logger for MCP-specific messages
mcp_logger = logging.getLogger("ipfs_datasets.mcp")

# Set log levels
logger.setLevel(logging.INFO)
mcp_logger.setLevel(logging.INFO)


def attach_mcp_file_sink(path: str | Path | None = None) -> None:
    """Dynamically attach a mutable MCP file sink (rejected after DQK-079 canary)."""

    from ipfs_datasets_py.logic.observability.structured_logging import (
        assert_handler_not_undeclared_file_sink,
        assert_mutable_file_sink_allowed,
    )

    target = Path(path) if path is not None else mcp_log_path
    assert_mutable_file_sink_allowed(target, kind="mcp_server_log")
    handler = logging.FileHandler(target, mode="a")
    assert_handler_not_undeclared_file_sink(handler)
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

    Under DQK-079 export-only / db-primary, typed DuckDB state is the authority
    and the legacy ``mcp_server.log`` / stderr stream is a disposable
    operational projection only. Console lines cannot satisfy progress or
    completion authority. Under DQK-077 shadow mode, the legacy file sink
    remains selected authority while the catalog is a non-authoritative
    projection with parity receipts.
    """

    try:
        from ipfs_datasets_py.logic.observability.structured_logging import (
            assert_console_not_progress_or_completion_authority,
            legacy_mutable_file_sinks_allowed,
        )

        assert_console_not_progress_or_completion_authority()
        # Drop any FileHandlers that slipped in after canary cutover.
        if not legacy_mutable_file_sinks_allowed():
            for handler in list(getattr(logger, "handlers", []) or []):
                if isinstance(handler, logging.FileHandler):
                    try:
                        logger.removeHandler(handler)
                        handler.close()
                    except Exception:
                        pass
    except Exception:
        pass

    # Always write through the ephemeral logger (console under cutover).
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

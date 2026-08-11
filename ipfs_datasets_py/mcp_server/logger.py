"""
Logger configuration for IPFS Datasets MCP server.

After DQK-079 (canary acceptance), the legacy ``mcp_server.log`` FileHandler is
not authority. Typed DuckDB observability (DQK-078) is the sole progress/audit
authority. Only ephemeral human-readable console logs remain by default; use
explicit deterministic exports when a file artifact is required.
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
            legacy_observability_file_sinks_allowed,
        )
        return legacy_observability_file_sinks_allowed()
    except Exception:
        # Before guard import: prefer console-only (post-canary default).
        return False


mcp_log_path = Path(__file__).parent / "mcp_server.log"

# Configure root logger.
# Under pytest, the root logger is often already configured. In that case,
# calling basicConfig() is a no-op, but eagerly constructing FileHandler would
# still open the file and then be garbage-collected, triggering ResourceWarning
# about an unclosed file. Only create/attach handlers when we will actually
# configure logging.
#
# DQK-079: default to ephemeral StreamHandler only. FileHandler for
# mcp_server.log is installed only when legacy file sinks are explicitly allowed.
_root_logger = logging.getLogger()
if not _root_logger.handlers:
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
    ]
    if _legacy_file_sinks_allowed():
        try:
            from ipfs_datasets_py.logic.observability.structured_logging import (
                assert_observability_file_write_allowed,
            )
            assert_observability_file_write_allowed(
                mcp_log_path, kind="log_file", operation="write"
            )
            mcp_log_path.touch()
            handlers.append(logging.FileHandler(mcp_log_path, mode="a"))
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

_install_optional_warning_filter()

# Create logger for this module
logger = logging.getLogger("ipfs_datasets.mcp_server")

# Create logger for MCP-specific messages
mcp_logger = logging.getLogger("ipfs_datasets.mcp")

# Set log levels
logger.setLevel(logging.INFO)
mcp_logger.setLevel(logging.INFO)

# Home log directory is no longer created eagerly (was implicit file-authority
# setup under DQK-077). Operators may still create it for explicit exports.
log_dir = Path.home() / ".ipfs_datasets"


def enable_legacy_mcp_file_log(path: Path | None = None) -> Path | None:
    """Attach a FileHandler only when legacy file sinks are allowed (tests/migration)."""

    target = path or mcp_log_path
    try:
        from ipfs_datasets_py.logic.observability.structured_logging import (
            assert_observability_file_write_allowed,
        )
        assert_observability_file_write_allowed(
            target, kind="log_file", operation="write"
        )
    except Exception:
        return None
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(target, mode="a")
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(fh)
    return target


def log_mcp_event(
    message: str,
    *,
    level: int = logging.INFO,
    event_type: str = "mcp.log",
    actor: str = "mcp_server",
    **attributes,
) -> None:
    """Log an MCP server event and project it into DuckDB cutover.

    Under DQK-078/DQK-079 dual/db-primary cutover, typed DuckDB state is the
    authority. The legacy ``mcp_server.log`` file is not created by default;
    stderr remains an ephemeral human-readable projection that cannot satisfy
    progress or completion authority.
    """

    # Always write through the ephemeral logger first (disposable under cutover).
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

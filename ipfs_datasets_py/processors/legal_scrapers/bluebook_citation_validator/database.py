"""Database setup helpers for the Bluebook citation validator.

All three setup functions return *open* connections.  The caller is
responsible for closing them.  Connections are **never** closed inside a
``finally`` block here because that would return a closed connection to the
caller (Bug #19 / #25 in the original code).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False
    duckdb = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_REFERENCE_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    gnis        INTEGER PRIMARY KEY,
    place_name  TEXT    NOT NULL,
    state_code  TEXT    NOT NULL,
    class_code  TEXT    NOT NULL
);
"""

_ERROR_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS errors (
    cid             TEXT    PRIMARY KEY,
    citation_cid    TEXT    NOT NULL,
    gnis            INTEGER NOT NULL,
    geography_error TEXT,
    type_error      TEXT,
    section_error   TEXT,
    date_error      TEXT,
    format_error    TEXT,
    severity        INTEGER NOT NULL,
    error_message   TEXT,
    created_at      TEXT    NOT NULL
);
"""

_REPORT_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_reports (
    id          INTEGER PRIMARY KEY,
    report_json TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""


def make_cid(data: str) -> str:
    """Return a 32-character SHA-256 hex digest of *data*.

    Used to generate stable content-addressed identifiers for error rows.
    """
    return hashlib.sha256(data.encode()).hexdigest()[:32]


def setup_reference_database(config) -> Any:
    """Open a DuckDB connection attached to the MySQL reference database.

    Args:
        config: A :class:`~config.ValidatorConfig` (or any object exposing
            ``mysql_host``, ``mysql_port``, ``mysql_user``, ``mysql_password``,
            ``mysql_database`` attributes).

    Returns:
        An open DuckDB connection with the MySQL database attached as
        ``mysql_db``.

    Raises:
        RuntimeError: If the DuckDB MySQL extension cannot be loaded or the
            attachment fails.
    """
    if not _DUCKDB_AVAILABLE:
        raise RuntimeError("duckdb is not installed. Run: pip install duckdb")

    connection_string = (
        f"mysql://{config.mysql_user}:{config.mysql_password}"
        f"@{config.mysql_host}:{config.mysql_port}/{config.mysql_database}"
    )

    conn = None
    try:
        conn = duckdb.connect()
        conn.execute("INSTALL mysql;")
        conn.execute("LOAD mysql;")
        conn.execute(
            f"ATTACH '{connection_string}' AS mysql_db (TYPE MYSQL, READ_ONLY);"
        )
        logger.info("Reference database attached successfully.")
        return conn  # caller owns the connection
    except Exception as exc:
        # Only close on error — caller never receives a closed connection.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        raise RuntimeError(f"Failed to set up reference database: {exc}") from exc


def setup_error_database(config) -> Any:
    """Open (or create) the DuckDB error database.

    Args:
        config: A :class:`~config.ValidatorConfig` exposing ``error_db_path``.

    Returns:
        An open DuckDB connection with the ``errors`` table initialised.
    """
    if not _DUCKDB_AVAILABLE:
        raise RuntimeError("duckdb is not installed. Run: pip install duckdb")

    db_path = Path(config.error_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        conn.execute(_ERROR_DB_SCHEMA)
        logger.info("Error database opened at %s.", db_path)
        return conn
    except Exception as exc:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        raise RuntimeError(f"Failed to set up error database: {exc}") from exc


def setup_report_database(config) -> Any:
    """Open (or create) the DuckDB error-report database.

    Args:
        config: A :class:`~config.ValidatorConfig` exposing
            ``error_report_db_path``.

    Returns:
        An open DuckDB connection with the ``error_reports`` table initialised.
    """
    if not _DUCKDB_AVAILABLE:
        raise RuntimeError("duckdb is not installed. Run: pip install duckdb")

    db_path = Path(config.error_report_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        conn.execute(_REPORT_DB_SCHEMA)
        logger.info("Report database opened at %s.", db_path)
        return conn
    except Exception as exc:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        raise RuntimeError(f"Failed to set up report database: {exc}") from exc

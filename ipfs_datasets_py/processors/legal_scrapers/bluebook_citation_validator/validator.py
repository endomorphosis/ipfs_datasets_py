"""Main CitationValidator: orchestrates validation for all sampled GNIS places.

All bugs from the original ``citation_validator.py`` are fixed here.  See
``MASTER_REFACTORING_PLAN_2026.md`` for the full bug inventory.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Optional

from .config import ValidatorConfig
from .database import make_cid
from .checkers import (
    check_geography,
    check_code_type,
    check_section,
    check_date,
    check_format,
)
from .thread_pool import run_in_thread_pool

try:
    import duckdb as _duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False

logger = logging.getLogger(__name__)

# SQL for batch-inserting error rows.
_INSERT_ERRORS_SQL = """
INSERT INTO errors (
    cid, citation_cid, gnis,
    geography_error, type_error, section_error, date_error, format_error,
    severity, error_message, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _load_citations_for_place(gnis: int, citation_dir: Path) -> list[dict]:
    """Load citation rows from a parquet file for *gnis*.

    The expected filename pattern is ``{gnis}_citation.parquet``.
    Falls back to an in-memory scan of all ``*_citation.parquet`` files.
    """
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is required to load citation parquet files.")

    candidate = citation_dir / f"{gnis}_citation.parquet"
    if candidate.exists():
        return pd.read_parquet(candidate).to_dict("records")

    # Fallback: search all files.
    for path in citation_dir.glob("*_citation.parquet"):
        stem_gnis = path.stem.split("_")[0]
        if stem_gnis.isdigit() and int(stem_gnis) == gnis:
            return pd.read_parquet(path).to_dict("records")

    raise FileNotFoundError(f"No citation parquet found for gnis {gnis} in {citation_dir}")


def _load_documents_for_place(gnis: int, document_dir: Path) -> list[dict]:
    """Load HTML document rows from a parquet file for *gnis*.

    The expected filename pattern is ``{gnis}_html.parquet``.
    """
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is required to load document parquet files.")

    candidate = document_dir / f"{gnis}_html.parquet"
    if candidate.exists():
        return pd.read_parquet(candidate).to_dict("records")

    for path in document_dir.glob("*_html.parquet"):
        stem_gnis = path.stem.split("_")[0]
        if stem_gnis.isdigit() and int(stem_gnis) == gnis:
            return pd.read_parquet(path).to_dict("records")

    logger.warning("No HTML parquet found for gnis %d in %s; documents will be empty.", gnis, document_dir)
    return []


class CitationValidator:
    """Orchestrates Bluebook citation validation for a set of sampled GNIS places.

    Args:
        config: A :class:`~config.ValidatorConfig` instance.
        reference_db: Open database connection (DuckDB + MySQL) used by the
            geography and code-type checkers.
        error_db: Open DuckDB connection for persisting validation errors.
    """

    def __init__(
        self,
        config: ValidatorConfig,
        reference_db: Any,
        error_db: Any,
    ) -> None:
        self._config = config
        self._reference_db = reference_db
        self._error_db = error_db

        # Bug #1 fix: assign to _html_dir, not _citation_dir twice.
        self._citation_dir: Path = Path(config.citation_dir)
        self._html_dir: Path = Path(config.document_dir)

        self._max_concurrency: int = config.max_concurrency
        self._insert_batch_size: int = config.insert_batch_size

        # Bug #4 fix: use threading.Lock (not RLock), acquire with timeout via
        # Lock.acquire(timeout=…) which IS supported.
        self._lock = threading.Lock()

        self._gnis_queue: Queue = Queue()
        self._validation_queue: Queue = Queue()

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def error_message(name: str, exc: Exception) -> str:
        """Format a standard error message string.

        Bug #2 fix: actually *returns* the formatted string (original was missing
        the ``return`` keyword).
        """
        label = name.split(".")[0].capitalize()
        return f"{label} check failed with {type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # Internal: per-place validation
    # ------------------------------------------------------------------

    def _run_check(
        self,
        func: Callable,
        citation: dict,
        error_type: str,
        documents: Optional[list[dict]] = None,
    ) -> Optional[str]:
        """Run a single checker function and return an error string or ``None``.

        Bug #3 fix: ``reference_db`` is *not* passed as a kwarg through
        ``_run_check``; checkers that need it (geography, code_type) capture
        ``self._reference_db`` via a lambda/partial at the call site.

        Returns:
            The error message string, or ``None`` when the check passes.
        """
        try:
            if documents is not None:
                return func(citation, documents)
            return func(citation)
        except Exception as exc:
            msg = self.error_message(error_type, exc)
            logger.exception(msg)
            return msg

    def _validate_citations(self, gnis: int) -> list[dict]:
        """Validate all citations for a single GNIS place.

        Returns a list of error-record dicts (only rows with at least one error).
        """
        try:
            citations = _load_citations_for_place(gnis, self._citation_dir)
            documents = _load_documents_for_place(gnis, self._html_dir)
        except FileNotFoundError as exc:
            logger.error("File not found for gnis %d: %s", gnis, exc)
            return []
        except Exception as exc:
            logger.exception("Failed to load data for gnis %d: %s", gnis, exc)
            return []

        results: list[dict] = []
        for citation in citations:
            # Bug #3 fix: pass reference_db via lambda so _run_check signature
            # stays clean (no extra kwarg).
            geo_err = self._run_check(
                lambda c: check_geography(c, self._reference_db),
                citation,
                "geography_error",
            )
            type_err = self._run_check(
                lambda c: check_code_type(c, self._reference_db),
                citation,
                "type_error",
            )
            sec_err = self._run_check(
                check_section,
                citation,
                "section_error",
                documents=documents,
            )
            date_err = self._run_check(
                check_date,
                citation,
                "date_error",
                documents=documents,
            )
            fmt_err = self._run_check(
                check_format,
                citation,
                "format_error",
            )

            if any(e is not None for e in (geo_err, type_err, sec_err, date_err, fmt_err)):
                error_parts = [
                    e for e in (geo_err, type_err, sec_err, date_err, fmt_err)
                    if e is not None
                ]
                num_errors = len(error_parts)
                is_critical = (geo_err is not None) or (type_err is not None)
                severity = 5 if is_critical else num_errors

                row = {
                    "citation_cid": citation.get("cid", ""),
                    "gnis": gnis,
                    "geography_error": geo_err,
                    "type_error": type_err,
                    "section_error": sec_err,
                    "date_error": date_err,
                    "format_error": fmt_err,
                    "severity": severity,
                    "error_message": "; ".join(error_parts),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                cid_source = "".join(str(v) for v in row.values())
                row["cid"] = make_cid(cid_source)
                results.append(row)

        return results

    # ------------------------------------------------------------------
    # Internal: persist errors
    # ------------------------------------------------------------------

    def save_validation_errors(self, result_batch: list[dict]) -> int:
        """Persist a batch of error records to the error database.

        Bug #4 fix: uses ``threading.Lock.acquire(timeout=10)`` (valid) instead
        of ``RLock`` context-manager with timeout (invalid).
        Bug #4 fix: ``error_count`` initialised before any use.
        Bug #10 fix: returns the actual ``error_count`` (was returning ``None``).
        Bug #18 fix: SQL has 11 ``?`` placeholders (matching 11 columns).

        Returns:
            Number of error rows inserted.
        """
        if not result_batch:
            return 0

        params_list = [
            (
                row["cid"],
                row["citation_cid"],
                row["gnis"],
                row.get("geography_error"),
                row.get("type_error"),
                row.get("section_error"),
                row.get("date_error"),
                row.get("format_error"),
                row["severity"],
                row["error_message"],
                row["created_at"],
            )
            for row in result_batch
        ]

        # Bug #4 fix: Lock.acquire(timeout=…) is valid; RLock context-manager
        # with timeout is not.
        acquired = self._lock.acquire(timeout=10)
        if not acquired:
            raise TimeoutError("Could not acquire DB lock within 10 seconds")
        error_count: int = 0  # Bug #4 fix: initialise before use
        try:
            self._error_db.execute("BEGIN")
            self._error_db.executemany(_INSERT_ERRORS_SQL, params_list)
            self._error_db.execute("COMMIT")
            error_count = len(params_list)
        except Exception as exc:
            try:
                self._error_db.execute("ROLLBACK")
            except Exception:
                pass
            logger.error("Failed to save %d error rows: %s", len(params_list), exc)
        finally:
            self._lock.release()

        return error_count

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    def validate_citations_against_html_and_references(
        self, sampled_gnis: list[int]
    ) -> int:
        """Validate citations for every GNIS in *sampled_gnis*.

        Bug #5 fix: loop now iterates ``sampled_gnis`` (not the undefined
        ``gnis_batch`` variable).
        Bug #6 fix: ``results`` variable is in scope before ``.extend()``.

        Args:
            sampled_gnis: List of GNIS integers to validate.

        Returns:
            Total number of error rows persisted to the error database.
        """
        logger.info("Starting validation for %d sampled places.", len(sampled_gnis))
        total_errors: int = 0

        # Populate the work queue.
        for gnis in sampled_gnis:  # Bug #5 fix: was ``gnis_batch``
            self._gnis_queue.put(gnis)

        # Consume the queue in concurrency-bounded batches.
        while not self._gnis_queue.empty():
            batch = list(itertools.islice(self._queue_to_iterable(self._gnis_queue), self._max_concurrency))
            if not batch:
                break
            for _gnis, place_results in run_in_thread_pool(
                self._validate_citations, batch,
                max_concurrency=self._max_concurrency,
                use_tqdm=False,
            ):
                if place_results:  # Bug #6 fix: results in scope
                    self._validation_queue.put(place_results)

        # Flush the validation queue to the database.
        while not self._validation_queue.empty():
            for result_batch in itertools.batched(
                self._queue_to_iterable(self._validation_queue), self._insert_batch_size
            ):
                # Each item in the queue is already a list[dict].
                flat = list(itertools.chain.from_iterable(result_batch))
                total_errors += self.save_validation_errors(flat)

        logger.info("Validation complete. Total errors persisted: %d.", total_errors)
        return total_errors

    @staticmethod
    def _queue_to_iterable(queue: Queue):
        """Drain a Queue into an iterator."""
        while not queue.empty():
            yield queue.get()

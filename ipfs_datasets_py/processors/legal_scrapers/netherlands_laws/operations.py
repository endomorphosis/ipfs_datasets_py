"""Production-scale catalog and queue operations for Netherlands BWBR ingestion."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from ipfs_datasets_py.utils.cid_utils import cid_for_obj

from .api import scrape
from .builders.common import iter_jsonl, read_jsonl, write_json, write_jsonl, write_parquet
from .builders.ipfs_package import article_payload, law_payload
from .paths import (
    DEFAULT_BWBR_CATALOG_PATH,
    DEFAULT_COVERAGE_REPORT_PATH,
    HF_DATA_DIR,
    IPFS_DATASET_NAME,
    KNOWLEDGE_GRAPH_DATASET_NAME,
    PACKAGE_RAW_OUTPUT_DIR,
    RAW_DATA_DIR,
    UNIFIED_WETWIJZER_DATASET_NAME,
)


QUEUE_STATES = (
    "discovered",
    "queued",
    "downloading",
    "downloaded",
    "parsed",
    "packaged",
    "uploaded",
    "verified",
    "failed",
    "permanently_skipped",
)
TERMINAL_SUCCESS_STATES = {"parsed", "packaged", "uploaded", "verified"}
COMPLETE_STATES = TERMINAL_SUCCESS_STATES | {"permanently_skipped"}
RETRYABLE_FAILURE_CATEGORIES = {"temporary_network_failure", "http_transient"}
NON_RETRYABLE_FAILURE_CATEGORIES = {"http_error", "parser_failure", "malformed_document", "unsupported_document"}
LAW_STATUS_VALUES = ("current", "historical", "repealed", "superseded", "unknown")
STATUS_FIELDS = (
    "law_status",
    "is_current",
    "valid_from",
    "valid_to",
    "effective_date",
    "retrieved_at",
    "status_source",
    "status_confidence",
    "status_note",
    "version_start_date",
    "version_end_date",
)
BWBR_RE = re.compile(r"\b(BWBR[0-9A-Z]+)\b", re.IGNORECASE)
HTTP_RE = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_identifier(value: Any) -> str:
    match = BWBR_RE.search(str(value or "").upper())
    return match.group(1).upper() if match else ""


def official_document_url(identifier: str) -> str:
    return f"https://wetten.overheid.nl/{normalize_identifier(identifier)}/"


def official_information_url(identifier: str) -> str:
    return f"https://wetten.overheid.nl/{normalize_identifier(identifier)}/informatie"


def _connect(catalog_path: Path | None = None) -> sqlite3.Connection:
    path = Path(catalog_path or DEFAULT_BWBR_CATALOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _bool_to_db(value: Any) -> int | None:
    if value is True:
        return 1
    if value is False:
        return 0
    return None


def _db_to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _content_checksum(row: dict[str, Any]) -> str:
    stable = {
        "law_identifier": row.get("law_identifier") or row.get("identifier"),
        "law_version_identifier": row.get("law_version_identifier"),
        "version_specific_identifier": row.get("version_specific_identifier"),
        "title": row.get("canonical_title") or row.get("title"),
        "text": row.get("text"),
        "source_url": row.get("source_url"),
        "information_url": row.get("information_url"),
        "document_type": row.get("document_type"),
        "official_metadata": row.get("official_metadata"),
        "historical_versions": row.get("historical_versions"),
        "article_count": row.get("article_count"),
        "article_rows_count": row.get("article_rows_count"),
        **{field: row.get(field) for field in STATUS_FIELDS},
    }
    return sha256(_json_dumps(stable).encode("utf-8")).hexdigest()


def _version_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "law_version_identifier": row.get("law_version_identifier"),
        "version_specific_identifier": row.get("version_specific_identifier"),
        "version_start_date": row.get("version_start_date"),
        "version_end_date": row.get("version_end_date"),
        "effective_date": row.get("effective_date"),
        "publication_date": row.get("publication_date"),
        "last_modified_date": row.get("last_modified_date"),
        "historical_versions": row.get("historical_versions") or [],
        "official_metadata": row.get("official_metadata") or {},
    }


def initialize_catalog(catalog_path: Path | None = None) -> dict[str, Any]:
    """Create the durable BWBR catalog if it does not already exist."""
    with _connect(catalog_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bwbr_catalog (
                identifier TEXT PRIMARY KEY,
                document_url TEXT NOT NULL,
                information_url TEXT,
                discovery_source TEXT,
                discovery_record_json TEXT,
                first_discovered_at TEXT NOT NULL,
                last_checked_at TEXT NOT NULL,
                scrape_state TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                parser_status TEXT,
                article_extraction_status TEXT,
                article_rows_count INTEGER,
                law_status TEXT NOT NULL DEFAULT 'unknown',
                is_current INTEGER,
                valid_from TEXT,
                valid_to TEXT,
                effective_date TEXT,
                status_source TEXT,
                status_confidence TEXT,
                status_note TEXT,
                checksum_sha256 TEXT,
                packaged_checksum_sha256 TEXT,
                version_metadata_json TEXT,
                source_record_position INTEGER,
                source_document_type TEXT,
                title TEXT,
                last_error_category TEXT,
                last_error TEXT,
                failure_is_transient INTEGER NOT NULL DEFAULT 0,
                failure_is_permanent INTEGER NOT NULL DEFAULT 0,
                locked_at TEXT,
                locked_by TEXT,
                last_transition_at TEXT,
                packaged_at TEXT,
                uploaded_at TEXT,
                verified_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT,
                from_state TEXT,
                to_state TEXT,
                event_type TEXT NOT NULL,
                category TEXT,
                note TEXT,
                run_id TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bwbr_state ON bwbr_catalog(scrape_state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bwbr_law_status ON bwbr_catalog(law_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bwbr_failure_category ON bwbr_catalog(last_error_category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_identifier ON catalog_events(identifier)")
        conn.commit()
    path = Path(catalog_path or DEFAULT_BWBR_CATALOG_PATH)
    return {"catalog_path": str(path), "initialized": True}


def _record_event(
    conn: sqlite3.Connection,
    *,
    identifier: str,
    from_state: str | None,
    to_state: str | None,
    event_type: str,
    category: str = "",
    note: str = "",
    run_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO catalog_events (
            identifier, from_state, to_state, event_type, category, note, run_id, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            identifier,
            from_state,
            to_state,
            event_type,
            category,
            note,
            run_id,
            _json_dumps(details or {}),
            utc_now(),
        ),
    )


def _transition(
    conn: sqlite3.Connection,
    identifier: str,
    to_state: str,
    *,
    event_type: str,
    note: str = "",
    category: str = "",
    run_id: str = "",
    extra_updates: dict[str, Any] | None = None,
) -> None:
    if to_state not in QUEUE_STATES:
        raise ValueError(f"Unknown Netherlands BWBR queue state: {to_state}")
    row = conn.execute("SELECT scrape_state FROM bwbr_catalog WHERE identifier = ?", (identifier,)).fetchone()
    from_state = str(row["scrape_state"]) if row else None
    assignments = {"scrape_state": to_state, "last_transition_at": utc_now(), "updated_at": utc_now()}
    assignments.update(extra_updates or {})
    set_clause = ", ".join(f"{key} = ?" for key in assignments)
    conn.execute(
        f"UPDATE bwbr_catalog SET {set_clause} WHERE identifier = ?",
        [*assignments.values(), identifier],
    )
    _record_event(
        conn,
        identifier=identifier,
        from_state=from_state,
        to_state=to_state,
        event_type=event_type,
        category=category,
        note=note,
        run_id=run_id,
    )


def import_discovery_catalog(
    *,
    discovery_jsonl_path: Path,
    catalog_path: Path | None = None,
    discovery_source: str = "official_bwb_sru",
    max_retries: int = 3,
) -> dict[str, Any]:
    """Import official SRU discovery rows into the durable catalog."""
    initialize_catalog(catalog_path)
    now = utc_now()
    inserted = 0
    updated = 0
    duplicate_rows = 0
    invalid_rows = 0
    seen: set[str] = set()
    with _connect(catalog_path) as conn:
        with Path(discovery_jsonl_path).open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid_rows += 1
                    continue
                identifier = normalize_identifier(row.get("identifier") or row.get("source_url") or row)
                if not identifier:
                    invalid_rows += 1
                    continue
                if identifier in seen:
                    duplicate_rows += 1
                    continue
                seen.add(identifier)
                existing = conn.execute("SELECT identifier FROM bwbr_catalog WHERE identifier = ?", (identifier,)).fetchone()
                document_url = str(row.get("source_url") or official_document_url(identifier))
                information_url = str(row.get("information_url") or official_information_url(identifier))
                if existing:
                    updated += 1
                    conn.execute(
                        """
                        UPDATE bwbr_catalog
                           SET document_url = ?,
                               information_url = ?,
                               discovery_source = COALESCE(discovery_source, ?),
                               discovery_record_json = ?,
                               last_checked_at = ?,
                               source_record_position = COALESCE(?, source_record_position),
                               source_document_type = COALESCE(NULLIF(?, ''), source_document_type),
                               title = COALESCE(NULLIF(?, ''), title),
                               updated_at = ?
                         WHERE identifier = ?
                        """,
                        (
                            document_url,
                            information_url,
                            discovery_source,
                            _json_dumps(row),
                            now,
                            row.get("record_position"),
                            str(row.get("document_type") or ""),
                            str(row.get("title") or ""),
                            now,
                            identifier,
                        ),
                    )
                else:
                    inserted += 1
                    conn.execute(
                        """
                        INSERT INTO bwbr_catalog (
                            identifier, document_url, information_url, discovery_source, discovery_record_json,
                            first_discovered_at, last_checked_at, scrape_state, retry_count, max_retries,
                            law_status, source_record_position, source_document_type, title,
                            last_transition_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'discovered', 0, ?, 'unknown', ?, ?, ?, ?, ?)
                        """,
                        (
                            identifier,
                            document_url,
                            information_url,
                            discovery_source,
                            _json_dumps(row),
                            now,
                            now,
                            max(0, int(max_retries)),
                            row.get("record_position"),
                            str(row.get("document_type") or ""),
                            str(row.get("title") or ""),
                            now,
                            now,
                        ),
                    )
                    _record_event(
                        conn,
                        identifier=identifier,
                        from_state=None,
                        to_state="discovered",
                        event_type="discovered",
                        category=discovery_source,
                        details=row,
                    )
        conn.commit()
    report = coverage_report(catalog_path=catalog_path, write=False)
    return {
        "catalog_path": str(Path(catalog_path or DEFAULT_BWBR_CATALOG_PATH)),
        "discovery_jsonl_path": str(discovery_jsonl_path),
        "inserted": inserted,
        "updated": updated,
        "duplicate_input_rows": duplicate_rows,
        "invalid_input_rows": invalid_rows,
        "total_discovered_identifiers": report["counts"]["total_discovered_identifiers"],
    }


def queue_identifiers(
    *,
    catalog_path: Path | None = None,
    identifiers: Iterable[str] | None = None,
    limit: int | None = None,
    include_retryable_failures: bool = False,
) -> dict[str, Any]:
    """Move discovered identifiers, or an explicit identifier subset, into the queued state."""
    initialize_catalog(catalog_path)
    queued: list[str] = []
    with _connect(catalog_path) as conn:
        if identifiers:
            candidates = [normalize_identifier(identifier) for identifier in identifiers]
            candidates = [identifier for identifier in dict.fromkeys(candidates) if identifier]
        else:
            states = ["discovered"]
            if include_retryable_failures:
                states.append("failed")
            placeholders = ", ".join("?" for _ in states)
            query = (
                "SELECT identifier, scrape_state, retry_count, max_retries, failure_is_transient "
                f"FROM bwbr_catalog WHERE scrape_state IN ({placeholders}) ORDER BY identifier"
            )
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"
            rows = conn.execute(query, states).fetchall()
            candidates = []
            for row in rows:
                if row["scrape_state"] == "failed" and not (
                    int(row["failure_is_transient"] or 0) == 1 and int(row["retry_count"] or 0) < int(row["max_retries"] or 0)
                ):
                    continue
                candidates.append(str(row["identifier"]))

        if limit and limit > 0 and identifiers:
            candidates = candidates[: int(limit)]
        for identifier in candidates:
            row = conn.execute(
                "SELECT scrape_state, retry_count, max_retries, failure_is_transient FROM bwbr_catalog WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            if not row:
                continue
            state = str(row["scrape_state"])
            if state in TERMINAL_SUCCESS_STATES or state == "permanently_skipped":
                continue
            if state == "failed" and not (
                include_retryable_failures
                and int(row["failure_is_transient"] or 0) == 1
                and int(row["retry_count"] or 0) < int(row["max_retries"] or 0)
            ):
                continue
            _transition(
                conn,
                identifier,
                "queued",
                event_type="queued",
                note="Identifier queued for BWBR scraping.",
                extra_updates={"locked_at": None, "locked_by": None},
            )
            queued.append(identifier)
        conn.commit()
    return {"queued_count": len(queued), "queued_identifiers": queued}


def reset_interrupted_downloads(
    *,
    catalog_path: Path | None = None,
    stale_after_minutes: int = 120,
) -> dict[str, Any]:
    """Move stale downloading leases back to queued so an interrupted run can resume."""
    initialize_catalog(catalog_path)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(stale_after_minutes)))
    reset: list[str] = []
    with _connect(catalog_path) as conn:
        rows = conn.execute(
            "SELECT identifier, locked_at FROM bwbr_catalog WHERE scrape_state = 'downloading' ORDER BY identifier"
        ).fetchall()
        for row in rows:
            locked_at = str(row["locked_at"] or "")
            try:
                locked_dt = datetime.fromisoformat(locked_at)
            except ValueError:
                locked_dt = datetime.min.replace(tzinfo=timezone.utc)
            if locked_dt <= cutoff:
                identifier = str(row["identifier"])
                _transition(
                    conn,
                    identifier,
                    "queued",
                    event_type="lease_reset",
                    note=f"Reset stale downloading lease older than {stale_after_minutes} minute(s).",
                    extra_updates={"locked_at": None, "locked_by": None},
                )
                reset.append(identifier)
        conn.commit()
    return {"reset_count": len(reset), "reset_identifiers": reset}


def lease_queued_identifiers(
    *,
    catalog_path: Path | None = None,
    batch_size: int = 25,
    worker_id: str = "default",
    stale_after_minutes: int = 120,
) -> list[dict[str, Any]]:
    initialize_catalog(catalog_path)
    reset_interrupted_downloads(catalog_path=catalog_path, stale_after_minutes=stale_after_minutes)
    leased: list[dict[str, Any]] = []
    with _connect(catalog_path) as conn:
        rows = conn.execute(
            "SELECT * FROM bwbr_catalog WHERE scrape_state = 'queued' ORDER BY identifier LIMIT ?",
            (max(1, int(batch_size)),),
        ).fetchall()
        for row in rows:
            identifier = str(row["identifier"])
            _transition(
                conn,
                identifier,
                "downloading",
                event_type="leased",
                note=f"Leased by {worker_id}.",
                extra_updates={"locked_at": utc_now(), "locked_by": worker_id},
            )
            leased.append(_row_dict(row))
        conn.commit()
    return leased


def classify_failure(message: str) -> dict[str, Any]:
    """Classify a scraper failure and decide whether it should be retried."""
    text = str(message or "")
    lowered = text.lower()
    http_match = HTTP_RE.search(text)
    if any(term in lowered for term in ["timeout", "timed out", "connection", "temporarily", "temporary failure", "ssl"]):
        return {"category": "temporary_network_failure", "retryable": True, "permanent": False}
    if http_match:
        status = int(http_match.group(1))
        if status == 429 or 500 <= status <= 599:
            return {"category": "http_transient", "retryable": True, "permanent": False, "http_status": status}
        return {"category": "http_error", "retryable": False, "permanent": True, "http_status": status}
    if any(term in lowered for term in ["no law text extracted", "no text", "empty document"]):
        return {"category": "parser_failure", "retryable": False, "permanent": True}
    if any(term in lowered for term in ["malformed", "not well-formed", "parseerror", "invalid xml", "invalid html"]):
        return {"category": "malformed_document", "retryable": False, "permanent": True}
    if "unsupported netherlands law url" in lowered or "unsupported" in lowered:
        return {"category": "unsupported_document", "retryable": False, "permanent": True}
    return {"category": "parser_failure", "retryable": False, "permanent": True}


def _error_by_identifier(metadata: dict[str, Any]) -> dict[str, str]:
    errors = metadata.get("errors") or []
    out: dict[str, str] = {}
    for error in errors:
        identifier = normalize_identifier(error)
        if identifier and identifier not in out:
            out[identifier] = str(error)
    return out


def update_catalog_from_law_rows(
    *,
    rows: Iterable[dict[str, Any]],
    catalog_path: Path | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """Synchronize parsed law rows back into the durable catalog."""
    initialize_catalog(catalog_path)
    updated: list[str] = []
    inserted: list[str] = []
    with _connect(catalog_path) as conn:
        for row in rows:
            identifier = normalize_identifier(row.get("law_identifier") or row.get("identifier") or row.get("source_url"))
            if not identifier:
                continue
            checksum = _content_checksum(row)
            now = utc_now()
            existing = conn.execute("SELECT scrape_state FROM bwbr_catalog WHERE identifier = ?", (identifier,)).fetchone()
            current_state = str(existing["scrape_state"]) if existing else "discovered"
            if not existing:
                inserted.append(identifier)
                conn.execute(
                    """
                    INSERT INTO bwbr_catalog (
                        identifier, document_url, information_url, discovery_source, first_discovered_at, last_checked_at,
                        scrape_state, retry_count, max_retries, law_status, last_transition_at, updated_at
                    ) VALUES (?, ?, ?, 'raw_sync', ?, ?, 'discovered', 0, 3, 'unknown', ?, ?)
                    """,
                    (
                        identifier,
                        str(row.get("source_url") or official_document_url(identifier)),
                        str(row.get("information_url") or official_information_url(identifier)),
                        now,
                        now,
                        now,
                        now,
                    ),
                )
            elif current_state == "downloading":
                _transition(
                    conn,
                    identifier,
                    "downloaded",
                    event_type="downloaded",
                    note="Document fetch completed; parsed row is being synchronized.",
                    run_id=run_id,
                )
                current_state = "downloaded"
            conn.execute(
                """
                UPDATE bwbr_catalog
                   SET scrape_state = 'parsed',
                       parser_status = 'parsed',
                       article_extraction_status = ?,
                       article_rows_count = ?,
                       law_status = ?,
                       is_current = ?,
                       valid_from = ?,
                       valid_to = ?,
                       effective_date = ?,
                       status_source = ?,
                       status_confidence = ?,
                       status_note = ?,
                       checksum_sha256 = ?,
                       version_metadata_json = ?,
                       document_url = ?,
                       information_url = ?,
                       title = ?,
                       last_error_category = NULL,
                       last_error = NULL,
                       failure_is_transient = 0,
                       failure_is_permanent = 0,
                       locked_at = NULL,
                       locked_by = NULL,
                       last_transition_at = ?,
                       updated_at = ?
                 WHERE identifier = ?
                """,
                (
                    str(row.get("article_extraction_status") or ""),
                    int(row.get("article_rows_count") or 0),
                    str(row.get("law_status") or "unknown"),
                    _bool_to_db(row.get("is_current")),
                    str(row.get("valid_from") or ""),
                    str(row.get("valid_to") or ""),
                    str(row.get("effective_date") or ""),
                    str(row.get("status_source") or ""),
                    str(row.get("status_confidence") or ""),
                    str(row.get("status_note") or ""),
                    checksum,
                    _json_dumps(_version_metadata(row)),
                    str(row.get("source_url") or official_document_url(identifier)),
                    str(row.get("information_url") or official_information_url(identifier)),
                    str(row.get("canonical_title") or row.get("title") or ""),
                    now,
                    now,
                    identifier,
                ),
            )
            _record_event(
                conn,
                identifier=identifier,
                from_state=current_state,
                to_state="parsed",
                event_type="parsed",
                note="Parsed law row synchronized from raw scraper output.",
                run_id=run_id,
                details={"checksum_sha256": checksum, "article_extraction_status": row.get("article_extraction_status")},
            )
            updated.append(identifier)
        conn.commit()
    return {"updated_count": len(updated), "inserted_count": len(inserted), "updated_identifiers": sorted(set(updated))}


def sync_catalog_from_raw(
    *,
    raw_dir: Path | None = None,
    catalog_path: Path | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    raw_dir = Path(raw_dir or PACKAGE_RAW_OUTPUT_DIR)
    laws_path = raw_dir / "netherlands_laws_index_latest.jsonl"
    if not laws_path.exists():
        return {"updated_count": 0, "inserted_count": 0, "updated_identifiers": [], "missing_raw_index": str(laws_path)}
    return update_catalog_from_law_rows(rows=read_jsonl(laws_path), catalog_path=catalog_path, run_id=run_id)


def _mark_failure(
    conn: sqlite3.Connection,
    *,
    identifier: str,
    message: str,
    run_id: str = "",
) -> None:
    classification = classify_failure(message)
    row = conn.execute("SELECT retry_count, max_retries, scrape_state FROM bwbr_catalog WHERE identifier = ?", (identifier,)).fetchone()
    if not row:
        return
    retry_count = int(row["retry_count"] or 0)
    max_retries = int(row["max_retries"] or 0)
    retryable = bool(classification["retryable"]) and retry_count + 1 < max_retries
    permanent = bool(classification["permanent"]) or not retryable
    _transition(
        conn,
        identifier,
        "failed",
        event_type="failed",
        category=str(classification["category"]),
        note=message,
        run_id=run_id,
        extra_updates={
            "retry_count": retry_count + 1,
            "last_error_category": str(classification["category"]),
            "last_error": message,
            "failure_is_transient": 1 if retryable else 0,
            "failure_is_permanent": 1 if permanent and not retryable else 0,
            "locked_at": None,
            "locked_by": None,
        },
    )


def mark_failure(
    *,
    catalog_path: Path | None = None,
    identifier: str,
    message: str,
    run_id: str = "manual",
) -> dict[str, Any]:
    """Record a failure for one identifier using the production retry classifier."""
    initialize_catalog(catalog_path)
    normalized = normalize_identifier(identifier)
    if not normalized:
        raise ValueError(f"Invalid BWBR identifier: {identifier!r}")
    with _connect(catalog_path) as conn:
        _mark_failure(conn, identifier=normalized, message=message, run_id=run_id)
        conn.commit()
    with _connect(catalog_path) as conn:
        row = conn.execute(
            "SELECT scrape_state, retry_count, last_error_category, failure_is_transient, failure_is_permanent FROM bwbr_catalog WHERE identifier = ?",
            (normalized,),
        ).fetchone()
    return _row_dict(row)


async def scrape_queued_batch(
    *,
    catalog_path: Path | None = None,
    raw_dir: Path | None = None,
    batch_size: int = 25,
    worker_id: str = "default",
    rate_limit_delay: float = 0.5,
    skip_existing: bool = True,
    stale_after_minutes: int = 120,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Lease one queued batch, run the existing scraper, and persist state transitions."""
    initialize_catalog(catalog_path)
    raw_dir = Path(raw_dir or PACKAGE_RAW_OUTPUT_DIR)
    run_id = run_id or f"scrape-{int(time.time())}"
    leased = lease_queued_identifiers(
        catalog_path=catalog_path,
        batch_size=batch_size,
        worker_id=worker_id,
        stale_after_minutes=stale_after_minutes,
    )
    if not leased:
        report = coverage_report(catalog_path=catalog_path)
        return {"status": "idle", "leased_count": 0, "coverage_report": report}

    document_urls = [row["document_url"] for row in leased if row.get("document_url")]
    result = await scrape(
        output_dir=raw_dir,
        document_urls=document_urls,
        seed_urls=[],
        use_default_seeds=False,
        max_documents=None,
        max_seed_pages=0,
        crawl_depth=0,
        rate_limit_delay=rate_limit_delay,
        skip_existing=skip_existing,
        resume=True,
    )
    sync_result = sync_catalog_from_raw(raw_dir=raw_dir, catalog_path=catalog_path, run_id=run_id)
    parsed = set(sync_result.get("updated_identifiers") or [])
    leased_ids = {str(row["identifier"]) for row in leased}
    metadata = dict(result.get("metadata") or {})
    errors_by_id = _error_by_identifier(metadata)

    with _connect(catalog_path) as conn:
        for identifier in sorted(leased_ids - parsed):
            message = errors_by_id.get(identifier) or f"No parsed row produced for {identifier}."
            _mark_failure(conn, identifier=identifier, message=message, run_id=run_id)
        conn.commit()

    report = coverage_report(catalog_path=catalog_path)
    return {
        "status": result.get("status"),
        "run_id": run_id,
        "leased_count": len(leased),
        "leased_identifiers": sorted(leased_ids),
        "parsed_count": len(leased_ids & parsed),
        "failed_count": len(leased_ids - parsed),
        "scrape_metadata": metadata,
        "catalog_sync": sync_result,
        "coverage_report": report,
    }


def retry_failures(
    *,
    catalog_path: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Queue only transient failures that still have retry budget."""
    initialize_catalog(catalog_path)
    queued: list[str] = []
    with _connect(catalog_path) as conn:
        query = (
            "SELECT identifier FROM bwbr_catalog "
            "WHERE scrape_state = 'failed' AND failure_is_transient = 1 AND retry_count < max_retries "
            "ORDER BY identifier"
        )
        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"
        for row in conn.execute(query).fetchall():
            identifier = str(row["identifier"])
            _transition(
                conn,
                identifier,
                "queued",
                event_type="retry_queued",
                note="Transient failure queued for retry.",
                extra_updates={"locked_at": None, "locked_by": None},
            )
            queued.append(identifier)
        conn.commit()
    return {"queued_count": len(queued), "queued_identifiers": queued}


def mark_packaged(
    *,
    catalog_path: Path | None = None,
    package_dir: Path | None = None,
) -> dict[str, Any]:
    """Mark identifiers represented in the local CID package as packaged."""
    initialize_catalog(catalog_path)
    package_dir = Path(package_dir or HF_DATA_DIR / IPFS_DATASET_NAME)
    laws_path = package_dir / "data/laws/ipfs_netherlands_laws.jsonl"
    if not laws_path.exists():
        raise FileNotFoundError(f"Missing packaged law rows: {laws_path}")
    marked: list[str] = []
    with _connect(catalog_path) as conn:
        for row in read_jsonl(laws_path):
            identifier = normalize_identifier(row.get("law_identifier") or row.get("identifier"))
            if not identifier:
                continue
            checksum = conn.execute(
                "SELECT checksum_sha256 FROM bwbr_catalog WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            _transition(
                conn,
                identifier,
                "packaged",
                event_type="packaged",
                note="Identifier represented in local CID Hugging Face package.",
                extra_updates={
                    "packaged_at": utc_now(),
                    "packaged_checksum_sha256": str(checksum["checksum_sha256"] or "") if checksum else "",
                },
            )
            marked.append(identifier)
        conn.commit()
    return {"packaged_count": len(set(marked)), "package_dir": str(package_dir)}


def mark_uploaded(
    *,
    catalog_path: Path | None = None,
    identifiers: Iterable[str] | None = None,
) -> dict[str, Any]:
    return _bulk_mark_state(catalog_path=catalog_path, identifiers=identifiers, to_state="uploaded", timestamp_field="uploaded_at")


def mark_verified(
    *,
    catalog_path: Path | None = None,
    identifiers: Iterable[str] | None = None,
) -> dict[str, Any]:
    return _bulk_mark_state(catalog_path=catalog_path, identifiers=identifiers, to_state="verified", timestamp_field="verified_at")


def _bulk_mark_state(
    *,
    catalog_path: Path | None,
    identifiers: Iterable[str] | None,
    to_state: str,
    timestamp_field: str,
) -> dict[str, Any]:
    initialize_catalog(catalog_path)
    marked: list[str] = []
    with _connect(catalog_path) as conn:
        if identifiers:
            candidates = [normalize_identifier(identifier) for identifier in identifiers]
            candidates = [identifier for identifier in dict.fromkeys(candidates) if identifier]
        else:
            candidates = [
                str(row["identifier"])
                for row in conn.execute(
                    "SELECT identifier FROM bwbr_catalog WHERE scrape_state IN ('packaged', 'uploaded', 'verified')"
                ).fetchall()
            ]
        for identifier in candidates:
            _transition(
                conn,
                identifier,
                to_state,
                event_type=to_state,
                note=f"Identifier marked {to_state}.",
                extra_updates={timestamp_field: utc_now(), "locked_at": None, "locked_by": None},
            )
            marked.append(identifier)
        conn.commit()
    return {f"{to_state}_count": len(set(marked))}


def coverage_report(
    *,
    catalog_path: Path | None = None,
    out_path: Path | None = DEFAULT_COVERAGE_REPORT_PATH,
    write: bool = True,
    include_remaining_identifiers: bool = True,
) -> dict[str, Any]:
    """Build a machine-readable coverage report from the durable catalog."""
    initialize_catalog(catalog_path)
    with _connect(catalog_path) as conn:
        rows = conn.execute("SELECT * FROM bwbr_catalog ORDER BY identifier").fetchall()
    total = len(rows)
    state_counts = Counter(str(row["scrape_state"]) for row in rows)
    status_counts = Counter(str(row["law_status"] or "unknown") for row in rows)
    parser_status_counts = Counter(str(row["parser_status"] or "unknown") for row in rows)
    article_status_counts = Counter(str(row["article_extraction_status"] or "unknown") for row in rows)
    failure_counts = Counter(str(row["last_error_category"] or "none") for row in rows if row["scrape_state"] == "failed")
    complete_identifiers = [
        str(row["identifier"])
        for row in rows
        if str(row["scrape_state"]) in COMPLETE_STATES
        or (str(row["scrape_state"]) == "failed" and int(row["failure_is_permanent"] or 0) == 1)
    ]
    complete = len(complete_identifiers)
    complete_identifier_set = set(complete_identifiers)
    remaining = [
        str(row["identifier"])
        for row in rows
        if str(row["identifier"]) not in complete_identifier_set
    ]
    report = {
        "generated_at": utc_now(),
        "catalog_path": str(Path(catalog_path or DEFAULT_BWBR_CATALOG_PATH)),
        "counts": {
            "total_discovered_identifiers": total,
            "discovered": state_counts.get("discovered", 0),
            "queued": state_counts.get("queued", 0),
            "downloading": state_counts.get("downloading", 0),
            "downloaded": state_counts.get("downloaded", 0),
            "parsed": state_counts.get("parsed", 0),
            "packaged": state_counts.get("packaged", 0),
            "uploaded": state_counts.get("uploaded", 0),
            "verified": state_counts.get("verified", 0),
            "failed": state_counts.get("failed", 0),
            "permanently_skipped": state_counts.get("permanently_skipped", 0),
            "complete": complete,
            "remaining": len(remaining),
        },
        "percent_complete": round((complete / total * 100.0), 6) if total else 0.0,
        "law_status_counts": {status: status_counts.get(status, 0) for status in LAW_STATUS_VALUES},
        "parser_status_counts": dict(sorted(parser_status_counts.items())),
        "article_extraction_status_counts": dict(sorted(article_status_counts.items())),
        "article_producing_laws_count": article_status_counts.get("articles_extracted", 0),
        "non_article_producing_laws_count": (
            article_status_counts.get("non_article_document", 0)
            + article_status_counts.get("article_extraction_missing", 0)
        ),
        "article_extraction_missing_count": article_status_counts.get("article_extraction_missing", 0),
        "genuine_non_article_laws_count": article_status_counts.get("non_article_document", 0),
        "article_rows_count": sum(int(row["article_rows_count"] or 0) for row in rows),
        "failures_by_category": dict(sorted(failure_counts.items())),
        "completion_semantics": (
            "Complete means parsed, packaged, uploaded, verified, permanently_skipped, or failed with "
            "failure_is_permanent=1. Transient failures remain incomplete until retried or exhausted."
        ),
        "remaining_identifiers_count": len(remaining),
    }
    if include_remaining_identifiers:
        report["remaining_identifiers"] = remaining
    if write and out_path:
        write_json(Path(out_path), report)
    return report


def validate_integrity(
    *,
    catalog_path: Path | None = None,
    raw_dir: Path | None = None,
    package_dir: Path | None = None,
    graph_dir: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Detect duplicate IDs/CIDs, article parent problems, status drift, and graph edge breaks."""
    initialize_catalog(catalog_path)
    raw_dir = Path(raw_dir or PACKAGE_RAW_OUTPUT_DIR)
    package_dir = Path(package_dir or HF_DATA_DIR / IPFS_DATASET_NAME)
    graph_dir = Path(graph_dir or HF_DATA_DIR / KNOWLEDGE_GRAPH_DATASET_NAME)
    issues: dict[str, list[Any]] = {
        "duplicate_bwbr_identifiers": [],
        "duplicate_raw_law_identifiers": [],
        "duplicate_cids": [],
        "orphan_article_rows": [],
        "missing_parent_law_rows": [],
        "inconsistent_status_inheritance": [],
        "broken_graph_edges": [],
    }

    with _connect(catalog_path) as conn:
        duplicate_catalog = conn.execute(
            "SELECT identifier, COUNT(*) AS count FROM bwbr_catalog GROUP BY identifier HAVING count > 1"
        ).fetchall()
        issues["duplicate_bwbr_identifiers"] = [_row_dict(row) for row in duplicate_catalog]

    raw_laws_path = raw_dir / "netherlands_laws_index_latest.jsonl"
    raw_articles_path = raw_dir / "netherlands_laws_articles_index_latest.jsonl"
    raw_laws = read_jsonl(raw_laws_path) if raw_laws_path.exists() else []
    raw_articles = read_jsonl(raw_articles_path) if raw_articles_path.exists() else []
    law_by_id = {
        normalize_identifier(row.get("law_identifier") or row.get("identifier")): row
        for row in raw_laws
        if normalize_identifier(row.get("law_identifier") or row.get("identifier"))
    }
    law_counts = Counter(normalize_identifier(row.get("law_identifier") or row.get("identifier")) for row in raw_laws)
    issues["duplicate_raw_law_identifiers"] = [
        {"law_identifier": identifier, "count": count}
        for identifier, count in sorted(law_counts.items())
        if identifier and count > 1
    ]
    for article in raw_articles:
        identifier = normalize_identifier(article.get("law_identifier") or article.get("identifier"))
        parent = law_by_id.get(identifier)
        if not parent:
            issues["orphan_article_rows"].append(
                {"law_identifier": identifier, "article_identifier": article.get("article_identifier")}
            )
            issues["missing_parent_law_rows"].append(identifier)
            continue
        for field in STATUS_FIELDS:
            if article.get(field) != parent.get(field):
                issues["inconsistent_status_inheritance"].append(
                    {
                        "law_identifier": identifier,
                        "article_identifier": article.get("article_identifier"),
                        "field": field,
                        "article_value": article.get(field),
                        "law_value": parent.get(field),
                    }
                )
                break

    cid_index_path = package_dir / "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl"
    if cid_index_path.exists():
        cids = [str(row.get("cid") or "") for row in read_jsonl(cid_index_path)]
        cid_counts = Counter(cid for cid in cids if cid)
        issues["duplicate_cids"] = [
            {"cid": cid, "count": count}
            for cid, count in sorted(cid_counts.items())
            if count > 1
        ]

    nodes_path = graph_dir / "data/nodes/ipfs_netherlands_laws_kg_nodes.jsonl"
    edges_path = graph_dir / "data/edges/ipfs_netherlands_laws_kg_edges.jsonl"
    if nodes_path.exists() and edges_path.exists():
        node_cids = {str(row.get("cid") or "") for row in read_jsonl(nodes_path)}
        for edge in read_jsonl(edges_path):
            source_cid = str(edge.get("source_cid") or "")
            target_cid = str(edge.get("target_cid") or "")
            if source_cid not in node_cids or target_cid not in node_cids:
                issues["broken_graph_edges"].append(
                    {
                        "edge_cid": edge.get("edge_cid"),
                        "source_cid": source_cid,
                        "target_cid": target_cid,
                    }
                )

    report = {
        "generated_at": utc_now(),
        "ok": all(not values for values in issues.values()),
        "issues": issues,
        "issue_counts": {key: len(value) for key, value in issues.items()},
    }
    if out_path:
        write_json(Path(out_path), report)
    return report


def _read_json_file(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return {}, {"path": str(path), "error": str(exc), "line": exc.lineno, "column": exc.colno}
    except OSError as exc:
        return {}, {"path": str(path), "error": str(exc)}


def _latest_report_path(reports_dir: Path, pattern: str, preferred_name: str | None = None) -> Path | None:
    if preferred_name:
        preferred = reports_dir / preferred_name
        if preferred.exists():
            return preferred
    candidates = sorted(
        (path for path in reports_dir.glob(pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _catalog_reconciliation_summary(catalog_path: Path) -> tuple[dict[str, Any], set[str], set[str], list[dict[str, Any]]]:
    uri = f"file:{catalog_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT identifier, scrape_state, failure_is_permanent, law_status,
                   parser_status, article_extraction_status, article_rows_count
            FROM bwbr_catalog
            ORDER BY identifier
            """
        ).fetchall()

    state_counts = Counter(str(row["scrape_state"]) for row in rows)
    status_counts = Counter(str(row["law_status"] or "unknown") for row in rows)
    parser_status_counts = Counter(str(row["parser_status"] or "unknown") for row in rows)
    article_status_counts = Counter(str(row["article_extraction_status"] or "unknown") for row in rows)
    complete_identifiers = {
        str(row["identifier"])
        for row in rows
        if str(row["scrape_state"]) in COMPLETE_STATES
        or (str(row["scrape_state"]) == "failed" and int(row["failure_is_permanent"] or 0) == 1)
    }
    package_representable_identifiers = {
        str(row["identifier"])
        for row in rows
        if str(row["scrape_state"]) in TERMINAL_SUCCESS_STATES
    }
    duplicate_rows = [
        {"identifier": identifier, "count": count}
        for identifier, count in Counter(str(row["identifier"]) for row in rows).items()
        if count > 1
    ]
    summary = {
        "path": str(catalog_path),
        "counts": {
            "total_discovered_identifiers": len(rows),
            "discovered": state_counts.get("discovered", 0),
            "queued": state_counts.get("queued", 0),
            "downloading": state_counts.get("downloading", 0),
            "downloaded": state_counts.get("downloaded", 0),
            "parsed": state_counts.get("parsed", 0),
            "packaged": state_counts.get("packaged", 0),
            "uploaded": state_counts.get("uploaded", 0),
            "verified": state_counts.get("verified", 0),
            "failed": state_counts.get("failed", 0),
            "permanently_skipped": state_counts.get("permanently_skipped", 0),
            "complete": len(complete_identifiers),
            "package_representable": len(package_representable_identifiers),
            "remaining": len(rows) - len(complete_identifiers),
        },
        "law_status_counts": {status: status_counts.get(status, 0) for status in LAW_STATUS_VALUES},
        "parser_status_counts": dict(sorted(parser_status_counts.items())),
        "article_extraction_status_counts": dict(sorted(article_status_counts.items())),
        "article_rows_count": sum(int(row["article_rows_count"] or 0) for row in rows),
        "duplicate_identifiers": duplicate_rows,
    }
    return summary, complete_identifiers, package_representable_identifiers, rows


def _jsonl_identifier_summary(path: Path, *, identifier_fields: tuple[str, ...]) -> tuple[dict[str, Any], set[str]]:
    identifiers: list[str] = []
    parse_errors: list[dict[str, Any]] = []
    row_count = 0
    try:
        for row_count, row in enumerate(iter_jsonl(path), start=1):
            identifier = ""
            for field in identifier_fields:
                identifier = normalize_identifier(row.get(field))
                if identifier:
                    break
            if identifier:
                identifiers.append(identifier)
    except json.JSONDecodeError as exc:
        parse_errors.append({"line": row_count + 1, "error": str(exc)})

    counts = Counter(identifiers)
    summary = {
        "path": str(path),
        "rows": row_count,
        "distinct_law_identifiers": len(counts),
        "duplicate_law_identifiers": [
            {"law_identifier": identifier, "count": count}
            for identifier, count in sorted(counts.items())
            if count > 1
        ],
        "parse_errors": parse_errors,
    }
    return summary, set(counts)


def _add_count_mismatch(
    mismatches: list[dict[str, Any]],
    *,
    name: str,
    left_label: str,
    left_value: Any,
    right_label: str,
    right_value: Any,
) -> None:
    if left_value != right_value:
        mismatches.append(
            {
                "type": "count_mismatch",
                "name": name,
                "left": {"source": left_label, "value": left_value},
                "right": {"source": right_label, "value": right_value},
            }
        )


def _add_identifier_mismatch(
    mismatches: list[dict[str, Any]],
    *,
    name: str,
    expected_label: str,
    expected: set[str],
    actual_label: str,
    actual: set[str],
    sample_size: int = 25,
) -> None:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        mismatches.append(
            {
                "type": "identifier_set_mismatch",
                "name": name,
                "expected_source": expected_label,
                "actual_source": actual_label,
                "missing_count": len(missing),
                "extra_count": len(extra),
                "missing_sample": missing[:sample_size],
                "extra_sample": extra[:sample_size],
            }
        )


def _add_parse_error_mismatches(mismatches: list[dict[str, Any]], *, name: str, summary: dict[str, Any]) -> None:
    parse_errors = summary.get("parse_errors") or []
    if parse_errors:
        mismatches.append(
            {
                "type": "jsonl_parse_errors",
                "name": name,
                "path": summary.get("path"),
                "parse_error_count": len(parse_errors),
                "parse_errors": parse_errors[:25],
            }
        )


def _add_json_artifact_error(
    mismatches: list[dict[str, Any]],
    *,
    name: str,
    path: Path,
    error: dict[str, Any] | None,
) -> None:
    if error:
        mismatches.append(
            {
                "type": "malformed_json_artifact",
                "name": name,
                "path": str(path),
                "error": error.get("error"),
                **({"line": error["line"], "column": error["column"]} if "line" in error else {}),
            }
        )


def reconcile_milestone(
    *,
    catalog_path: Path | None = None,
    raw_dir: Path | None = None,
    package_dir: Path | None = None,
    unified_dir: Path | None = None,
    reports_dir: Path | None = None,
    coverage_report_path: Path | None = None,
    integrity_report_path: Path | None = None,
    out_path: Path | None = None,
    milestone_name: str = "netherlands-legal-corpus",
) -> dict[str, Any]:
    """Read local catalog/raw/package/report artifacts and report milestone drift.

    The function is intentionally no-network and no-scrape: it only opens local
    files that already exist, and it only writes when ``out_path`` is supplied.
    """
    catalog_path = Path(catalog_path or DEFAULT_BWBR_CATALOG_PATH)
    raw_dir = Path(raw_dir or RAW_DATA_DIR / "nl_full_sru_sharded")
    package_dir = Path(package_dir or HF_DATA_DIR / IPFS_DATASET_NAME)
    unified_dir = Path(unified_dir or HF_DATA_DIR / UNIFIED_WETWIJZER_DATASET_NAME)
    reports_dir = Path(reports_dir or RAW_DATA_DIR / "nl_bwb_operations")
    warnings: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "milestone_name": milestone_name,
        "read_only": True,
        "network_used": False,
        "scrape_used": False,
        "package_build_used": False,
        "upload_used": False,
        "inputs": {
            "catalog_path": str(catalog_path),
            "raw_dir": str(raw_dir),
            "package_dir": str(package_dir),
            "unified_dir": str(unified_dir),
            "reports_dir": str(reports_dir),
        },
        "summaries": {},
        "mismatches": mismatches,
        "warnings": warnings,
    }

    catalog_summary: dict[str, Any] = {"path": str(catalog_path), "missing": True}
    complete_identifiers: set[str] = set()
    representable_identifiers: set[str] = set()
    if catalog_path.exists():
        catalog_summary, complete_identifiers, representable_identifiers, _rows = _catalog_reconciliation_summary(catalog_path)
        report["summaries"]["catalog"] = catalog_summary
        if catalog_summary["duplicate_identifiers"]:
            mismatches.append(
                {
                    "type": "catalog_duplicate_identifiers",
                    "name": "catalog identifiers",
                    "duplicates": catalog_summary["duplicate_identifiers"][:25],
                    "duplicate_count": len(catalog_summary["duplicate_identifiers"]),
                }
            )
    else:
        warnings.append({"type": "missing_required_artifact", "path": str(catalog_path), "message": "Catalog SQLite file is missing."})
        mismatches.append({"type": "missing_required_artifact", "name": "catalog", "path": str(catalog_path)})
        report["summaries"]["catalog"] = catalog_summary

    raw_summary: dict[str, Any] = {"path": str(raw_dir)}
    raw_law_ids: set[str] = set()
    raw_article_parent_ids: set[str] = set()
    raw_laws_path = raw_dir / "netherlands_laws_index_latest.jsonl"
    raw_articles_path = raw_dir / "netherlands_laws_articles_index_latest.jsonl"
    if raw_laws_path.exists():
        raw_summary["laws"], raw_law_ids = _jsonl_identifier_summary(raw_laws_path, identifier_fields=("law_identifier", "identifier"))
        _add_parse_error_mismatches(mismatches, name="raw laws JSONL", summary=raw_summary["laws"])
        if raw_summary["laws"]["duplicate_law_identifiers"]:
            mismatches.append(
                {
                    "type": "raw_duplicate_law_identifiers",
                    "name": "raw law identifiers",
                    "duplicates": raw_summary["laws"]["duplicate_law_identifiers"][:25],
                    "duplicate_count": len(raw_summary["laws"]["duplicate_law_identifiers"]),
                }
            )
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(raw_laws_path), "message": "Raw laws JSONL is missing."})
    if raw_articles_path.exists():
        raw_summary["articles"], raw_article_parent_ids = _jsonl_identifier_summary(raw_articles_path, identifier_fields=("law_identifier", "identifier"))
        _add_parse_error_mismatches(mismatches, name="raw articles JSONL", summary=raw_summary["articles"])
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(raw_articles_path), "message": "Raw articles JSONL is missing."})
    if raw_law_ids and raw_article_parent_ids:
        _add_identifier_mismatch(
            mismatches,
            name="raw article parent laws",
            expected_label="raw article parent identifiers",
            expected=raw_article_parent_ids,
            actual_label="raw laws",
            actual=raw_law_ids,
        )
    if raw_law_ids and representable_identifiers:
        _add_identifier_mismatch(
            mismatches,
            name="catalog package-representable identifiers vs raw laws",
            expected_label="catalog terminal success states",
            expected=representable_identifiers,
            actual_label="raw laws",
            actual=raw_law_ids,
        )
    report["summaries"]["raw"] = raw_summary

    package_summary: dict[str, Any] = {"path": str(package_dir)}
    package_law_ids: set[str] = set()
    package_manifest_path = package_dir / "dataset_manifest.json"
    package_manifest: dict[str, Any] = {}
    if package_manifest_path.exists():
        package_manifest, package_manifest_error = _read_json_file(package_manifest_path)
        _add_json_artifact_error(mismatches, name="base package manifest", path=package_manifest_path, error=package_manifest_error)
    if package_manifest:
        package_summary["manifest"] = {
            "path": str(package_manifest_path),
            "records": package_manifest.get("records") or {},
        }
    elif not package_manifest_path.exists():
        warnings.append({"type": "missing_optional_artifact", "path": str(package_manifest_path), "message": "Base package manifest is missing."})
    else:
        package_summary["manifest_error"] = {"path": str(package_manifest_path)}
    package_laws_path = package_dir / "data/laws/ipfs_netherlands_laws.jsonl"
    package_articles_path = package_dir / "data/articles/ipfs_netherlands_laws_articles.jsonl"
    package_cid_path = package_dir / "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl"
    if package_laws_path.exists():
        package_summary["laws"], package_law_ids = _jsonl_identifier_summary(package_laws_path, identifier_fields=("law_identifier", "identifier"))
        _add_parse_error_mismatches(mismatches, name="base package laws JSONL", summary=package_summary["laws"])
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(package_laws_path), "message": "Base package laws JSONL is missing."})
    if package_articles_path.exists():
        package_summary["articles"], package_article_parent_ids = _jsonl_identifier_summary(package_articles_path, identifier_fields=("law_identifier", "identifier"))
        _add_parse_error_mismatches(mismatches, name="base package articles JSONL", summary=package_summary["articles"])
        if package_law_ids:
            _add_identifier_mismatch(
                mismatches,
                name="package article parent laws",
                expected_label="package article parent identifiers",
                expected=package_article_parent_ids,
                actual_label="package laws",
                actual=package_law_ids,
            )
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(package_articles_path), "message": "Base package articles JSONL is missing."})
    if package_cid_path.exists():
        package_summary["cid_index"], _cid_ids = _jsonl_identifier_summary(package_cid_path, identifier_fields=("law_identifier", "identifier"))
        _add_parse_error_mismatches(mismatches, name="base package CID index JSONL", summary=package_summary["cid_index"])
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(package_cid_path), "message": "Base package CID index JSONL is missing."})
    manifest_records = package_manifest.get("records") or {}
    if "laws" in package_summary and manifest_records:
        _add_count_mismatch(mismatches, name="base package laws", left_label="base manifest", left_value=manifest_records.get("laws"), right_label="base laws JSONL", right_value=package_summary["laws"]["rows"])
    if "articles" in package_summary and manifest_records:
        _add_count_mismatch(mismatches, name="base package articles", left_label="base manifest", left_value=manifest_records.get("articles"), right_label="base articles JSONL", right_value=package_summary["articles"]["rows"])
    if "cid_index" in package_summary and manifest_records:
        _add_count_mismatch(mismatches, name="base package cid_index", left_label="base manifest", left_value=manifest_records.get("cid_index"), right_label="base CID JSONL", right_value=package_summary["cid_index"]["rows"])
    if package_law_ids and representable_identifiers:
        _add_identifier_mismatch(
            mismatches,
            name="catalog package-representable identifiers vs base package laws",
            expected_label="catalog terminal success states",
            expected=representable_identifiers,
            actual_label="base package laws",
            actual=package_law_ids,
        )
    report["summaries"]["package"] = package_summary

    coverage_path = Path(coverage_report_path) if coverage_report_path else _latest_report_path(reports_dir, "coverage_report*.json", "coverage_report_latest.json")
    coverage: dict[str, Any] = {}
    coverage_error: dict[str, Any] | None = None
    if coverage_path and coverage_path.exists():
        coverage, coverage_error = _read_json_file(coverage_path)
        _add_json_artifact_error(mismatches, name="coverage report", path=coverage_path, error=coverage_error)
    if coverage:
        report["summaries"]["coverage_report"] = {"path": str(coverage_path), "counts": coverage.get("counts") or {}, "percent_complete": coverage.get("percent_complete")}
        coverage_counts = coverage.get("counts") or {}
        catalog_counts = catalog_summary.get("counts") or {}
        for key in ("total_discovered_identifiers", "complete", "remaining"):
            if key in coverage_counts and key in catalog_counts:
                _add_count_mismatch(mismatches, name=f"coverage {key}", left_label="catalog", left_value=catalog_counts.get(key), right_label="coverage report", right_value=coverage_counts.get(key))
        if "article_rows_count" in coverage and "article_rows_count" in catalog_summary:
            _add_count_mismatch(mismatches, name="coverage article rows", left_label="catalog", left_value=catalog_summary.get("article_rows_count"), right_label="coverage report", right_value=coverage.get("article_rows_count"))
    elif coverage_error:
        report["summaries"]["coverage_report"] = {"path": str(coverage_path), "malformed": True}
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(coverage_path or reports_dir), "message": "Coverage report is missing."})

    integrity_path = Path(integrity_report_path) if integrity_report_path else _latest_report_path(reports_dir, "integrity_report*.json")
    integrity: dict[str, Any] = {}
    integrity_error: dict[str, Any] | None = None
    if integrity_path and integrity_path.exists():
        integrity, integrity_error = _read_json_file(integrity_path)
        _add_json_artifact_error(mismatches, name="integrity report", path=integrity_path, error=integrity_error)
    if integrity:
        report["summaries"]["integrity_report"] = {"path": str(integrity_path), "ok": integrity.get("ok"), "issue_counts": integrity.get("issue_counts") or {}}
        if integrity.get("ok") is False:
            mismatches.append({"type": "integrity_report_failed", "name": "integrity report", "issue_counts": integrity.get("issue_counts") or {}})
    elif integrity_error:
        report["summaries"]["integrity_report"] = {"path": str(integrity_path), "malformed": True}
    else:
        warnings.append({"type": "missing_optional_artifact", "path": str(integrity_path or reports_dir), "message": "Integrity report is missing."})

    unified_manifest_path = unified_dir / "dataset_manifest.json"
    unified_manifest: dict[str, Any] = {}
    if unified_manifest_path.exists():
        unified_manifest, unified_manifest_error = _read_json_file(unified_manifest_path)
        _add_json_artifact_error(mismatches, name="unified package manifest", path=unified_manifest_path, error=unified_manifest_error)
    if unified_manifest:
        unified_summary = {"path": str(unified_dir), "manifest": {"path": str(unified_manifest_path), "records": unified_manifest.get("records") or {}}}
        report["summaries"]["unified_package"] = unified_summary
        unified_records = unified_manifest.get("records") or {}
        for key in ("laws", "articles", "cid_index"):
            if key in manifest_records and key in unified_records:
                _add_count_mismatch(mismatches, name=f"unified {key}", left_label="base manifest", left_value=manifest_records.get(key), right_label="unified manifest", right_value=unified_records.get(key))
    elif not unified_manifest_path.exists():
        warnings.append({"type": "missing_optional_artifact", "path": str(unified_manifest_path), "message": "Unified package manifest is missing."})
    else:
        report["summaries"]["unified_package"] = {"path": str(unified_dir), "manifest_error": {"path": str(unified_manifest_path)}}

    report["ok"] = not mismatches
    report["mismatch_count"] = len(mismatches)
    report["warning_count"] = len(warnings)
    report["recommended_next_action"] = (
        "Resolve mismatches before scaling additional BWBR scraping."
        if mismatches
        else "Snapshot is internally reconciled across available artifacts; review warnings before scaling."
    )
    if out_path:
        write_json(Path(out_path), report)
    return report


def changed_identifiers_for_incremental_build(
    *,
    catalog_path: Path | None = None,
    limit: int | None = None,
) -> list[str]:
    initialize_catalog(catalog_path)
    with _connect(catalog_path) as conn:
        query = (
            "SELECT identifier FROM bwbr_catalog "
            "WHERE scrape_state IN ('parsed', 'packaged') "
            "AND checksum_sha256 IS NOT NULL "
            "AND (packaged_checksum_sha256 IS NULL OR packaged_checksum_sha256 != checksum_sha256) "
            "ORDER BY identifier"
        )
        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"
        return [str(row["identifier"]) for row in conn.execute(query).fetchall()]


def build_incremental_hf_delta(
    *,
    catalog_path: Path | None = None,
    raw_dir: Path | None = None,
    out_dir: Path | None = None,
    identifiers: Iterable[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build changed-only rows and manifests for incremental publishing workflows.

    This command deliberately avoids rebuilding global FAISS/BM25 artifacts. It
    emits affected base rows plus row-level vector/BM25/KG inputs so a publisher
    can upload a deterministic delta and schedule heavier global artifacts less
    frequently.
    """
    initialize_catalog(catalog_path)
    raw_dir = Path(raw_dir or PACKAGE_RAW_OUTPUT_DIR)
    run_id = f"delta-{int(time.time())}"
    out_dir = Path(out_dir or RAW_DATA_DIR / "nl_bwb_operations" / "incremental" / run_id)
    selected = [normalize_identifier(item) for item in identifiers] if identifiers else changed_identifiers_for_incremental_build(catalog_path=catalog_path, limit=limit)
    selected = [item for item in dict.fromkeys(selected) if item]
    selected_set = set(selected)

    raw_laws_path = raw_dir / "netherlands_laws_index_latest.jsonl"
    raw_articles_path = raw_dir / "netherlands_laws_articles_index_latest.jsonl"
    raw_laws = [
        row
        for row in (read_jsonl(raw_laws_path) if raw_laws_path.exists() else [])
        if normalize_identifier(row.get("law_identifier") or row.get("identifier")) in selected_set
    ]
    raw_articles = [
        row
        for row in (read_jsonl(raw_articles_path) if raw_articles_path.exists() else [])
        if normalize_identifier(row.get("law_identifier") or row.get("identifier")) in selected_set
    ]
    laws: list[dict[str, Any]] = []
    law_cid_by_id: dict[str, str] = {}
    cid_rows: list[dict[str, Any]] = []
    for raw_row in raw_laws:
        payload = law_payload(raw_row)
        cid = cid_for_obj(payload)
        payload["cid"] = cid
        payload["content_address"] = f"ipfs://{cid}"
        identifier = normalize_identifier(payload.get("law_identifier") or payload.get("identifier"))
        law_cid_by_id[identifier] = cid
        laws.append(payload)
        cid_rows.append(
            {
                "record_type": "law",
                "law_identifier": identifier,
                "article_identifier": None,
                "cid": cid,
                "content_address": f"ipfs://{cid}",
                "source_url": payload.get("source_url"),
                "title": payload.get("title"),
                "law_status": payload.get("law_status"),
                "is_current": payload.get("is_current"),
            }
        )
    articles: list[dict[str, Any]] = []
    for raw_row in raw_articles:
        payload = article_payload(raw_row)
        identifier = normalize_identifier(payload.get("law_identifier"))
        payload["law_cid"] = law_cid_by_id.get(identifier, "")
        cid = cid_for_obj(payload)
        payload["cid"] = cid
        payload["content_address"] = f"ipfs://{cid}"
        articles.append(payload)
        cid_rows.append(
            {
                "record_type": "article",
                "law_identifier": identifier,
                "article_identifier": payload.get("article_identifier"),
                "cid": cid,
                "content_address": f"ipfs://{cid}",
                "source_url": None,
                "title": payload.get("citation"),
                "law_status": payload.get("law_status"),
                "is_current": payload.get("is_current"),
            }
        )

    index_rows: list[dict[str, Any]] = []
    for record_type, rows in [("law", laws), ("article", articles)]:
        for row in rows:
            text = f"{row.get('title') or row.get('citation') or ''}\n{row.get('text') or ''}".strip()
            index_rows.append(
                {
                    "cid": row["cid"],
                    "law_cid": row.get("law_cid") or row["cid"],
                    "record_type": record_type,
                    "law_identifier": row.get("law_identifier"),
                    "article_identifier": row.get("article_identifier"),
                    "title": row.get("title") or row.get("citation"),
                    "law_status": row.get("law_status"),
                    "is_current": row.get("is_current"),
                    "status_source": row.get("status_source"),
                    "status_confidence": row.get("status_confidence"),
                    "text_preview": text[:500],
                }
            )

    write_jsonl(out_dir / "base/laws.jsonl", laws)
    write_jsonl(out_dir / "base/articles.jsonl", articles)
    write_jsonl(out_dir / "base/cid_index.jsonl", cid_rows)
    write_jsonl(out_dir / "indexes/vector_rows.jsonl", index_rows)
    write_jsonl(out_dir / "indexes/bm25_document_rows.jsonl", index_rows)
    write_jsonl(out_dir / "graph/nodes.jsonl", index_rows)
    write_jsonl(
        out_dir / "graph/edges.jsonl",
        [
            {
                "source_cid": article["cid"],
                "target_cid": article.get("law_cid"),
                "law_identifier": article.get("law_identifier"),
                "article_identifier": article.get("article_identifier"),
                "edge_type": "isPartOf",
            }
            for article in articles
            if article.get("law_cid")
        ],
    )
    if laws:
        write_parquet(out_dir / "parquet/laws/train.parquet", laws)
    if articles:
        write_parquet(out_dir / "parquet/articles/train.parquet", articles)
    manifest = {
        "run_id": run_id,
        "generated_at": utc_now(),
        "changed_identifiers": selected,
        "records": {
            "laws": len(laws),
            "articles": len(articles),
            "cid_index": len(cid_rows),
            "index_rows": len(index_rows),
        },
        "global_artifacts_rebuild_required": {
            "faiss": bool(index_rows),
            "bm25_terms": bool(index_rows),
            "note": "Row-level deltas are deterministic; global FAISS and BM25 term statistics should be rebuilt on a scheduled full-index pass.",
        },
    }
    write_json(out_dir / "incremental_manifest.json", manifest)
    return {"out_dir": str(out_dir), **manifest}

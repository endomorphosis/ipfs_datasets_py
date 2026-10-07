"""Durable autoformal span queue with a sealed compile cache in DuckDB.

Compiled spans are cached and sealed by the terms they used. A later compiler
or parser edit that changes one of those terms unseals the dependents so they
are recensed. A sealed cache row is an engineering receipt, not a legal admit.
JSONL is not written.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .supervisor_queue import EDIT_SCOPES, canonical_bytes

SCHEMA = "uscode-autoformal-span-cache/v1"
MAX_TEXT = 32 * 1024
MAX_BATCH = 512
_PACKAGE = "ipfs_datasets_py/logic/"
_PARSER = (
    _PACKAGE + "deontic/utils/deontic_parser.py",
    _PACKAGE + "deontic/formula_builder.py",
)
_COMPILER = (_PACKAGE + "legal_ir/canonical_compiler.py",)
_DECOMPILER = (
    _PACKAGE + "legal_ir/canonical_decompiler.py",
    _PACKAGE + "modal/decompiler.py",
)
TERM_KIND_PATHS = {
    "modality": _COMPILER,
    "actor": _PARSER,
    "action": _PARSER,
    "object": _PARSER,
    "conditions": _PARSER,
    "exceptions": _PARSER,
    "temporal": _PARSER + _COMPILER,
    "qualifiers": _DECOMPILER,
    "decompiled": _DECOMPILER,
}

_DDL = """
CREATE TABLE IF NOT EXISTS span_cache (
    source_span_id VARCHAR PRIMARY KEY,
    source_sha256 VARCHAR NOT NULL,
    legal_id VARCHAR,
    source_text VARCHAR,
    decompiled VARCHAR,
    reason VARCHAR,
    status VARCHAR NOT NULL,
    sealed BOOLEAN NOT NULL,
    code_identity VARCHAR,
    rule_json VARCHAR,
    path_hashes VARCHAR,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS sealed_terms (
    term_id VARCHAR PRIMARY KEY,
    kind VARCHAR NOT NULL,
    value VARCHAR NOT NULL,
    value_sha256 VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS span_terms (
    source_span_id VARCHAR NOT NULL,
    term_id VARCHAR NOT NULL,
    PRIMARY KEY (source_span_id, term_id)
);
CREATE TABLE IF NOT EXISTS compiler_snapshot (
    path VARCHAR PRIMARY KEY,
    sha256 VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS cache_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lean_statutes (
    legal_id VARCHAR PRIMARY KEY,
    lean_source VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    lake_ok BOOLEAN NOT NULL,
    lake_error VARCHAR,
    clause_count INTEGER NOT NULL,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS lean_terms (
    term_id VARCHAR PRIMARY KEY,
    kind VARCHAR NOT NULL,
    value VARCHAR NOT NULL,
    lean_source VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    lake_ok BOOLEAN NOT NULL,
    lake_error VARCHAR,
    statute_count INTEGER NOT NULL,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL
);
"""


class SpanCacheError(RuntimeError):
    """The span queue cannot continue without inventing cache authority."""


@dataclass(frozen=True)
class SpanCacheTextLimits:
    """UTF-8 limits for new source/decompilation writes, never truncation sizes.

    The legacy ``MAX_TEXT`` character cutoff remains an historical constant;
    it is not applied to new writes. Limits cover the persisted text fields,
    not arbitrary rule payloads, Parquet decoding or total process RSS.
    """

    max_text_bytes: int = 1024 * 1024
    max_batch_text_bytes: int = 64 * 1024 * 1024
    max_batch_rows: int = 4096

    def __post_init__(self) -> None:
        for name in ("max_text_bytes", "max_batch_text_bytes", "max_batch_rows"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise SpanCacheError(f"{name} must be a positive integer")


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _repair_json(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "{}"
    return _json(value)


def _repair_load(raw: Any) -> dict[str, Any]:
    try:
        loaded = json.loads(str(raw or "") or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def terms_from_rule(rule: Mapping[str, Any] | None, *, decompiled: str = "") -> list[dict[str, str]]:
    """Name the IR atoms a compiled span used. Empty when there is no rule."""

    found: list[dict[str, str]] = []
    if isinstance(rule, Mapping):
        for kind in ("modality", "actor", "action", "object"):
            value = str(rule.get(kind) or "").strip()
            if value:
                found.append({"kind": kind, "value": value, "term_id": _sha(kind + "\n" + value)})
        for kind in ("conditions", "exceptions", "temporal", "qualifiers"):
            for item in rule.get(kind) or []:
                value = str(item or "").strip()
                if value:
                    found.append({"kind": kind, "value": value, "term_id": _sha(kind + "\n" + value)})
    text = str(decompiled or "").strip()
    if text:
        found.append({"kind": "decompiled", "value": text, "term_id": _sha("decompiled\n" + text)})
    return found


SEALED_SPANS_FILE = "sealed-spans.parquet"
_RESUME_FILES = {
    "resume-checkpoint.parquet",
    "entity-resume-checkpoint.parquet",
    "entity-resume-checkpoint-v2.parquet",
}
_SPAN_STATUSES = {"pending", "gap", "sealed", "unsealed"}
SPAN_EXPORT_COLUMNS = (
    "admitted",
    "code_identity",
    "decompiled",
    "formalized",
    "legal_id",
    "sealed",
    "source_sha256",
    "source_span_id",
    "source_text",
    "term_ids",
    "status",
    "rule_json",
    "term_rows_json",
)


def _load_rule(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def export_status(row: Mapping[str, Any]) -> str:
    """Sealed when a legacy export omits status. Pending and gap stay explicit."""

    status = str(row.get("status") or "").strip().lower()
    if status in _SPAN_STATUSES:
        return status
    if row.get("sealed") is False:
        return "unsealed"
    return "sealed"


def span_export_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Columns a finished span needs so it can be grouped without DuckDB."""

    status = export_status(row)
    rule_json = row.get("rule_json")
    if not isinstance(rule_json, str):
        rule = row.get("rule") if isinstance(row.get("rule"), Mapping) else {}
        rule_json = _json(rule) if rule else ""
    term_rows_json = row.get("term_rows_json")
    if not isinstance(term_rows_json, str):
        term_rows = row.get("term_rows") if isinstance(row.get("term_rows"), list) else []
        term_rows_json = _json(term_rows) if term_rows else "[]"
    return {
        "admitted": False,
        "code_identity": str(row.get("code_identity") or ""),
        "decompiled": str(row.get("decompiled") or ""),
        "formalized": False,
        "legal_id": str(row.get("legal_id") or ""),
        "rule_json": rule_json,
        "sealed": status == "sealed",
        "source_sha256": str(row.get("source_sha256") or ""),
        "source_span_id": str(row.get("source_span_id") or ""),
        "source_text": str(row.get("source_text") or row.get("text") or ""),
        "status": status,
        "term_ids": json.dumps(list(row.get("term_ids") or []), ensure_ascii=True, sort_keys=True),
        "term_rows_json": term_rows_json,
    }


def _term_rows_from_export(row: Mapping[str, Any], rule: Mapping[str, Any]) -> list[dict[str, str]]:
    loaded: Any = None
    if "term_rows_json" in row and row.get("term_rows_json") is not None:
        raw = row.get("term_rows_json")
        if isinstance(raw, str) and raw:
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                loaded = []
        else:
            loaded = []
    elif isinstance(row.get("term_rows"), list):
        loaded = row.get("term_rows")
    if not isinstance(loaded, list):
        loaded = terms_from_rule(rule, decompiled=str(row.get("decompiled") or ""))
    rows: list[dict[str, str]] = []
    for item in loaded:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        value = str(item.get("value") or "")
        if not kind or not value:
            continue
        rows.append(
            {
                "kind": kind,
                "term_id": str(item.get("term_id") or "") or _sha(kind + "\n" + value),
                "value": value,
            }
        )
    return rows


def group_span_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Group sealed clauses and terms. Gaps sit beside the groups. Pending blocks a section."""

    statutes: dict[str, list[dict[str, Any]]] = {}
    gaps: dict[str, list[dict[str, Any]]] = {}
    pending: dict[str, list[dict[str, Any]]] = {}
    terms: dict[str, dict[str, Any]] = {}
    seen: dict[str, set[str]] = {}
    exported: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        legal_id = str(row.get("legal_id") or "").strip() or "unspecified"
        status = export_status(row)
        seen.setdefault(legal_id, set()).add(status)
        span_id = str(row.get("source_span_id") or "")
        rule = _load_rule(row.get("rule") if isinstance(row.get("rule"), Mapping) else row.get("rule_json"))
        exported.append(
            {
                "decompiled": str(row.get("decompiled") or ""),
                "legal_id": legal_id,
                "rule": rule,
                "source_sha256": str(row.get("source_sha256") or ""),
                "source_span_id": span_id,
                "status": status,
                "text": str(row.get("source_text") or row.get("text") or ""),
            }
        )
        if status == "sealed":
            statutes.setdefault(legal_id, []).append(
                {
                    "legal_id": legal_id,
                    "rule": rule,
                    "source_sha256": str(row.get("source_sha256") or ""),
                    "source_span_id": span_id,
                    "text": str(row.get("source_text") or row.get("text") or ""),
                }
            )
            for term in _term_rows_from_export(row, rule):
                item = terms.setdefault(
                    term["term_id"],
                    {
                        "kind": term["kind"],
                        "statute_ids": [],
                        "term_id": term["term_id"],
                        "value": term["value"],
                    },
                )
                if legal_id not in item["statute_ids"]:
                    item["statute_ids"].append(legal_id)
        elif status == "gap":
            gaps.setdefault(legal_id, []).append(
                {
                    "legal_id": legal_id,
                    "reason": str(row.get("reason") or ""),
                    "source_span_id": span_id,
                    "status": "gap",
                }
            )
        else:
            pending.setdefault(legal_id, []).append(
                {
                    "legal_id": legal_id,
                    "source_span_id": span_id,
                    "status": status,
                }
            )
    for clauses in statutes.values():
        clauses.sort(key=lambda item: item["source_span_id"])
    for bucket in (gaps, pending):
        for items in bucket.values():
            items.sort(key=lambda item: item["source_span_id"])
    for item in terms.values():
        item["statute_ids"] = sorted(item["statute_ids"])
    ready: list[str] = []
    not_ready: list[str] = []
    for legal_id, statuses in sorted(seen.items()):
        if statuses and statuses <= {"sealed", "gap"}:
            ready.append(legal_id)
        else:
            not_ready.append(legal_id)
    return {
        "admitted": False,
        "formalized": False,
        "gaps": gaps,
        "not_ready": not_ready,
        "pending": pending,
        "ready": ready,
        "rows": exported,
        "statutes": statutes,
        "terms": sorted(terms.values(), key=lambda item: (item["kind"], item["value"], item["term_id"])),
    }


def _pinned_revision(revision: str) -> str:
    text = str(revision or "").strip()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise SpanCacheError("span revision must be a pinned commit")
    return text


def span_groups_from_parquet(
    path: str | Path | None = None,
    *,
    revision: str | None = None,
    repository_id: str = "justicedao/uscode-autoformal-span-cache",
    download: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read sealed-spans.parquet only. A pinned revision selects that file and no other."""

    pinned = _pinned_revision(revision) if revision else ""
    downloaded = path is None
    if downloaded:
        if not pinned:
            raise SpanCacheError("sealed span parquet requires a local file or a pinned revision")
        if download is None:
            from huggingface_hub import hf_hub_download

            download = hf_hub_download
        path = download(
            repository_id,
            SEALED_SPANS_FILE,
            repo_type="dataset",
            revision=pinned,
        )
    source = Path(path)
    if source.name in _RESUME_FILES or (not downloaded and source.name != SEALED_SPANS_FILE):
        raise SpanCacheError("span grouping reads sealed-spans.parquet only")
    if not source.is_file():
        raise SpanCacheError("sealed span parquet is not a file")
    import pyarrow.parquet as pq

    grouped = group_span_rows(pq.read_table(source).to_pylist())
    grouped["revision"] = pinned
    grouped["source"] = SEALED_SPANS_FILE
    return grouped


def compiler_path_hashes(root: str | Path) -> dict[str, str]:
    """Hash every EDIT_SCOPES path. Missing files are omitted."""

    base = Path(root)
    hashes: dict[str, str] = {}
    for path in sorted({item for scope in EDIT_SCOPES.values() for item in scope}):
        target = base / path
        if target.is_file():
            hashes[path] = hashlib.sha256(target.read_bytes()).hexdigest()
    return hashes


def compiler_identity(path_hashes: Mapping[str, str]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(dict(path_hashes))).hexdigest()


def progress_fingerprint(
    *,
    source_sha256: str,
    status: str,
    sealed: bool,
    reason: str,
    code_identity: str,
) -> str:
    """Identity of a durable span outcome. Claims and heartbeats are not part of it."""

    payload = "\n".join((source_sha256, status, "1" if sealed else "0", reason, code_identity))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SpanCache:
    """File-backed DuckDB queue of pending, sealed, and unsealed spans."""

    def __init__(self, path: str | Path, *, text_limits: SpanCacheTextLimits | None = None):
        if text_limits is not None and not isinstance(text_limits, SpanCacheTextLimits):
            raise SpanCacheError("text_limits must be SpanCacheTextLimits")
        self.text_limits = text_limits if text_limits is not None else SpanCacheTextLimits()
        import duckdb

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.path = destination
        self._db = duckdb.connect(str(destination))
        for statement in _DDL.split(";"):
            body = statement.strip()
            if body:
                self._db.execute(body)
        for column in ("claim_worker", "claim_token"):
            self._db.execute(f"ALTER TABLE span_cache ADD COLUMN IF NOT EXISTS {column} VARCHAR")
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS span_cache_status ON span_cache(status)"
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_lease (
                agent_id VARCHAR PRIMARY KEY,
                dataset_id VARCHAR NOT NULL,
                role VARCHAR NOT NULL,
                heartbeat VARCHAR NOT NULL,
                claimed_count INTEGER NOT NULL,
                admitted BOOLEAN NOT NULL,
                formalized BOOLEAN NOT NULL
            )
            """
        )
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS task_board (
                task_id VARCHAR PRIMARY KEY,
                source_span_id VARCHAR,
                legal_id VARCHAR,
                status VARCHAR NOT NULL,
                failure_mode VARCHAR,
                work_kind VARCHAR,
                owner_agent VARCHAR,
                admitted BOOLEAN NOT NULL,
                formalized BOOLEAN NOT NULL
            )
            """
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS applied_sparse_checkpoint (path VARCHAR PRIMARY KEY)"
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS quarantined_sparse_checkpoint (
                   path VARCHAR NOT NULL, expected_dataset_id VARCHAR NOT NULL,
                   reason VARCHAR NOT NULL, evidence_json VARCHAR NOT NULL,
                   PRIMARY KEY (path, expected_dataset_id))"""
        )
        if self._meta("sparse_checkpoint_paths_migrated") != "1":
            try:
                legacy_paths = json.loads(self._meta("applied_sparse_checkpoints") or "[]")
            except json.JSONDecodeError:
                legacy_paths = []
            self._db.execute("BEGIN TRANSACTION")
            try:
                if isinstance(legacy_paths, list):
                    paths = [(path,) for path in legacy_paths if isinstance(path, str) and path]
                    if paths:
                        self._db.executemany(
                            "INSERT OR IGNORE INTO applied_sparse_checkpoint VALUES (?)", paths
                        )
                self._set_meta("sparse_checkpoint_paths_migrated", "1")
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        self._last_flush = int(self._meta("last_flush_sealed") or 0)

    def close(self) -> None:
        self._db.close()

    def checkpoint(self) -> dict[str, Any]:
        """Last committed parquet position. Resume starts after this document."""

        raw = self._meta("enqueue_documents")
        try:
            documents = int(raw or 0)
        except ValueError:
            documents = 0
        stats = self.stats()
        return {
            "admitted": False,
            "documents": documents,
            "formalized": False,
            "gaps": stats["gaps"],
            "parquet": self._meta("enqueue_parquet"),
            "pending": stats["pending"],
            "sealed": stats["sealed"],
        }

    def save_checkpoint(self, *, documents: int, parquet: str) -> None:
        self._set_meta("enqueue_documents", str(max(0, int(documents))))
        self._set_meta("enqueue_parquet", str(parquet))

    def register_agent(self, agent_id: str, *, dataset_id: str, role: str = "compile") -> None:
        """Record a live agent on this dataset. Not an admit."""

        import time

        claimed = self._db.execute(
            "SELECT count(*) FROM span_cache WHERE claim_worker = ? AND status = 'claimed'",
            [agent_id],
        ).fetchone()
        self._db.execute(
            """
            INSERT OR REPLACE INTO agent_lease (
                agent_id, dataset_id, role, heartbeat, claimed_count, admitted, formalized
            ) VALUES (?, ?, ?, ?, ?, FALSE, FALSE)
            """,
            [agent_id, dataset_id, role, str(int(time.time())), int(claimed[0] if claimed else 0)],
        )
        self._set_meta("dataset_id", dataset_id)

    def refresh_task_board(self) -> int:
        """Rebuild the shared board from the span queue and its seals."""

        self._db.execute("DELETE FROM task_board")
        self._db.execute(
            """
            INSERT INTO task_board (
                task_id, source_span_id, legal_id, status, failure_mode, work_kind,
                owner_agent, admitted, formalized
            )
            SELECT
                'AFTD-' || substr(source_span_id, 1, 24),
                source_span_id,
                legal_id,
                CASE WHEN sealed THEN 'sealed' ELSE status END,
                reason,
                CASE
                    WHEN sealed THEN 'sealed_compile'
                    WHEN status = 'gap' THEN 'compiler_decompiler_edit'
                    ELSE 'span_queue'
                END,
                coalesce(claim_worker, ''),
                FALSE,
                FALSE
            FROM span_cache
            """
        )
        row = self._db.execute("SELECT count(*) FROM task_board").fetchone()
        return int(row[0] if row else 0)

    def write_resume_parquet(self, path: str | Path) -> dict[str, Any]:
        """Write one parquet checkpoint: board, seals, agents, and span status."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.refresh_task_board()
        dataset_id = (self._meta("dataset_id") or "ipfs_uscode").replace("'", "''")
        source_parquet = self._meta("enqueue_parquet").replace("'", "''")
        documents = int(self._meta("enqueue_documents") or 0)
        target = str(destination).replace("'", "''")
        self._db.execute(
            f"""
            COPY (
                SELECT * FROM (
                    SELECT
                        'meta' AS record_kind,
                        '{dataset_id}' AS dataset_id,
                        '' AS agent_id,
                        '' AS role,
                        '' AS heartbeat,
                        {documents} AS documents,
                        '{source_parquet}' AS source_parquet,
                        '' AS source_span_id,
                        '' AS legal_id,
                        '' AS status,
                        FALSE AS sealed,
                        '' AS claim_worker,
                        '' AS claim_token,
                        '' AS source_sha256,
                        '' AS reason,
                        '' AS code_identity,
                        '' AS term_id,
                        '' AS term_kind,
                        '' AS term_value,
                        '' AS task_id,
                        '' AS failure_mode,
                        '' AS work_kind,
                        '' AS owner_agent,
                        FALSE AS admitted,
                        FALSE AS formalized
                    UNION ALL
                    SELECT
                        'agent', dataset_id, agent_id, role, heartbeat, claimed_count,
                        '', '', '', '', FALSE, '', '', '', '', '', '', '', '',
                        '', '', '', '', admitted, formalized
                    FROM agent_lease
                    UNION ALL
                    SELECT
                        'board', '', coalesce(owner_agent, ''), '', '', 0, '',
                        coalesce(source_span_id, ''), coalesce(legal_id, ''),
                        status, FALSE, coalesce(owner_agent, ''), '', '',
                        coalesce(failure_mode, ''), '', '', '', '',
                        task_id, coalesce(failure_mode, ''), coalesce(work_kind, ''),
                        coalesce(owner_agent, ''), admitted, formalized
                    FROM task_board
                    UNION ALL
                    SELECT
                        'seal', '', '', '', '', 0, '', coalesce(st.source_span_id, ''), '',
                        '', FALSE, '', '', coalesce(t.value_sha256, ''), '', '',
                        t.term_id, t.kind, t.value, '', '', '', '', FALSE, FALSE
                    FROM sealed_terms t
                    JOIN span_terms st ON st.term_id = t.term_id
                    UNION ALL
                    SELECT
                        'span', '', coalesce(claim_worker, ''), '', '', 0, '',
                        source_span_id, coalesce(legal_id, ''), status, sealed,
                        coalesce(claim_worker, ''), coalesce(claim_token, ''),
                        source_sha256, coalesce(reason, ''), coalesce(code_identity, ''),
                        '', '', '', '', '', '', '', admitted, formalized
                    FROM span_cache
                )
            ) TO '{target}' (FORMAT PARQUET)
            """
        )
        return {
            "admitted": False,
            "formalized": False,
            "jsonl_written": False,
            "path": str(destination),
            "task_count": self._db.execute("SELECT count(*) FROM task_board").fetchone()[0],
        }

    def published_progress_fingerprints(self) -> dict[str, str]:
        """Fingerprints already uploaded. A missing catalog is an empty baseline."""

        try:
            loaded = json.loads(self._meta("published_progress_fingerprints") or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(loaded, dict):
            return {}
        return {str(key): str(value) for key, value in loaded.items() if key and value}

    def applied_sparse_checkpoints(self) -> list[str]:
        """All retained observation identities; no eviction that can cause replay loops."""
        return [str(row[0]) for row in self._db.execute(
            "SELECT path FROM applied_sparse_checkpoint ORDER BY path"
        ).fetchall()]

    def unapplied_sparse_checkpoints(self, paths: Sequence[str], *, limit: int = 16) -> list[str]:
        """Choose bounded work without loading the entire applied history into Python."""
        selected: list[str] = []
        seen: set[str] = set()
        bounded = max(0, min(int(limit), MAX_BATCH))
        if not bounded:
            return selected
        for offset in range(0, len(paths), 400):
            chunk = [str(path) for path in paths[offset:offset + 400] if path]
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            known = {str(row[0]) for row in self._db.execute(
                f"""SELECT path FROM applied_sparse_checkpoint WHERE path IN ({placeholders})
                    UNION SELECT path FROM quarantined_sparse_checkpoint
                    WHERE expected_dataset_id = ? AND path IN ({placeholders})""",
                [*chunk, self._meta("dataset_id"), *chunk]
            ).fetchall()}
            for path in chunk:
                if path not in known and path not in seen:
                    selected.append(path)
                    seen.add(path)
                    if len(selected) >= bounded:
                        return selected
        return selected

    def remember_sparse_checkpoint(self, path_in_repo: str) -> None:
        if path_in_repo:
            self._db.execute(
                "INSERT OR IGNORE INTO applied_sparse_checkpoint VALUES (?)", [str(path_in_repo)]
            )

    def quarantine_sparse_checkpoint(self, path_in_repo: str, *, expected_dataset_id: str,
                                     reason: str, evidence: Mapping[str, Any]) -> None:
        """Record a rejected immutable shard separately from successfully observed shards."""
        if not path_in_repo or not expected_dataset_id or not reason:
            raise SpanCacheError("quarantined checkpoint needs a path, expected dataset, and reason")
        self._db.execute(
            "INSERT OR REPLACE INTO quarantined_sparse_checkpoint VALUES (?, ?, ?, ?)",
            [str(path_in_repo), expected_dataset_id, reason, _json(dict(evidence))],
        )

    def quarantined_sparse_checkpoint_count(self) -> int:
        return int(self._db.execute(
            "SELECT count(*) FROM quarantined_sparse_checkpoint WHERE expected_dataset_id = ?",
            [self._meta("dataset_id")],
        ).fetchone()[0])

    def durable_progress_rows(self) -> list[dict[str, Any]]:
        """Sealed and gap rows only. Pending claims and heartbeats stay local."""

        rows = self._db.execute(
            """
            SELECT source_span_id, coalesce(legal_id, ''), source_sha256, status,
                   sealed, coalesce(reason, ''), coalesce(code_identity, '')
            FROM span_cache
            WHERE sealed = TRUE OR status = 'gap'
            ORDER BY source_span_id
            """
        ).fetchall()
        found: list[dict[str, Any]] = []
        for row in rows:
            sealed = bool(row[4])
            found.append(
                {
                    "code_identity": str(row[6] or ""),
                    "fingerprint": progress_fingerprint(
                        source_sha256=str(row[2] or ""),
                        status=str(row[3] or ""),
                        sealed=sealed,
                        reason=str(row[5] or ""),
                        code_identity=str(row[6] or ""),
                    ),
                    "legal_id": str(row[1] or ""),
                    "reason": str(row[5] or ""),
                    "sealed": sealed,
                    "source_sha256": str(row[2] or ""),
                    "source_span_id": str(row[0] or ""),
                    "status": str(row[3] or ""),
                }
            )
        return found

    def sparse_progress_delta(self) -> dict[str, Any]:
        """Rows whose durable outcome changed since the last uploaded delta."""

        previous = self.published_progress_fingerprints()
        changed = [row for row in self.durable_progress_rows() if previous.get(row["source_span_id"]) != row["fingerprint"]]
        return {
            "admitted": False,
            "delta_count": len(changed),
            "fingerprints": {row["source_span_id"]: row["fingerprint"] for row in changed},
            "formalized": False,
            "rows": changed,
        }

    def mark_progress_published(self, fingerprints: Mapping[str, str]) -> None:
        published = self.published_progress_fingerprints()
        published.update({str(key): str(value) for key, value in fingerprints.items() if key and value})
        self._set_meta("published_progress_fingerprints", _json(published))

    def write_sparse_progress_parquet(
        self,
        path: str | Path,
        rows: Sequence[Mapping[str, Any]],
        *,
        agent_id: str,
        update_id: str,
    ) -> dict[str, Any]:
        """Write one machine's changed spans. This is not the full resume checkpoint."""

        import os
        import tempfile

        destination = Path(path)
        if destination.name == "resume-checkpoint.parquet":
            raise SpanCacheError("sparse checkpoint must not replace the full resume checkpoint")
        destination.parent.mkdir(parents=True, exist_ok=True)
        dataset_id = self._meta("dataset_id") or "ipfs_uscode"
        # Sparse status evidence never changes because enqueue position advanced.
        documents = 0
        self._db.execute(
            """
            CREATE TEMPORARY TABLE sparse_progress (
                record_kind VARCHAR, dataset_id VARCHAR, agent_id VARCHAR, role VARCHAR,
                heartbeat VARCHAR, documents BIGINT, source_parquet VARCHAR,
                source_span_id VARCHAR, legal_id VARCHAR, status VARCHAR, sealed BOOLEAN,
                claim_worker VARCHAR, claim_token VARCHAR, source_sha256 VARCHAR,
                reason VARCHAR, code_identity VARCHAR, term_id VARCHAR, term_kind VARCHAR,
                term_value VARCHAR, task_id VARCHAR, failure_mode VARCHAR, work_kind VARCHAR,
                owner_agent VARCHAR, sealed_count BIGINT, gap_count BIGINT, pending_count BIGINT,
                admitted BOOLEAN, formalized BOOLEAN
            )
            """
        )
        try:
            self._db.execute(
                """
                INSERT INTO sparse_progress VALUES (
                    'meta', ?, ?, 'compile', '', ?, '', '', '', 'sparse', FALSE,
                    '', '', '', '', '', '', '', '', '', '', '', '', 0, 0, 0, FALSE, FALSE
                )
                """,
                [dataset_id, agent_id, documents],
            )
            for row in rows:
                self._db.execute(
                    """
                    INSERT INTO sparse_progress VALUES (
                        'span', ?, ?, '', '', 0, '', ?, ?, ?, ?,
                        '', '', ?, ?, ?, '', '', '', '', '', '', '', 0, 0, 0, FALSE, FALSE
                    )
                    """,
                    [
                        dataset_id,
                        agent_id,
                        str(row.get("source_span_id") or ""),
                        str(row.get("legal_id") or ""),
                        str(row.get("status") or ""),
                        bool(row.get("sealed")),
                        str(row.get("source_sha256") or ""),
                        str(row.get("reason") or ""),
                        str(row.get("code_identity") or ""),
                    ],
                )
            fd, temporary_name = tempfile.mkstemp(prefix=".sparse-progress-", suffix=".parquet", dir=destination.parent)
            os.close(fd)
            temporary = Path(temporary_name)
            try:
                target = str(temporary).replace("'", "''")
                self._db.execute(f"COPY sparse_progress TO '{target}' (FORMAT PARQUET)")
                with temporary.open("rb") as stream:
                    os.fsync(stream.fileno())
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    if destination.is_symlink() or not destination.is_file():
                        raise SpanCacheError("sparse checkpoint destination is not a regular file")
                    with destination.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                            raise SpanCacheError("immutable sparse checkpoint conflicts with retained bytes")
                directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            self._db.execute("DROP TABLE IF EXISTS sparse_progress")
        return {
            "admitted": False,
            "delta_count": len(list(rows)),
            "formalized": False,
            "jsonl_written": False,
            "path": str(destination),
            "update_id": update_id,
        }

    def write_progress_parquet(self, path: str | Path) -> dict[str, Any]:
        """Write sealed and gap rows only. Pending span text stays in DuckDB."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        dataset_id = (self._meta("dataset_id") or "ipfs_uscode").replace("'", "''")
        source_parquet = self._meta("enqueue_parquet").replace("'", "''")
        documents = int(self._meta("enqueue_documents") or 0)
        stats = self.stats()
        target = str(destination).replace("'", "''")
        self._db.execute(
            f"""
            COPY (
                SELECT * FROM (
                    SELECT
                        'meta' AS record_kind,
                        '{dataset_id}' AS dataset_id,
                        '' AS agent_id,
                        '' AS role,
                        '' AS heartbeat,
                        {documents} AS documents,
                        '{source_parquet}' AS source_parquet,
                        '' AS source_span_id,
                        '' AS legal_id,
                        'progress' AS status,
                        FALSE AS sealed,
                        '' AS claim_worker,
                        '' AS claim_token,
                        '' AS source_sha256,
                        '' AS reason,
                        '' AS code_identity,
                        '' AS term_id,
                        '' AS term_kind,
                        '' AS term_value,
                        '' AS task_id,
                        '' AS failure_mode,
                        '' AS work_kind,
                        '' AS owner_agent,
                        {int(stats['sealed'])} AS sealed_count,
                        {int(stats['gaps'])} AS gap_count,
                        {int(stats['pending'])} AS pending_count,
                        FALSE AS admitted,
                        FALSE AS formalized
                    UNION ALL
                    SELECT
                        'span', '', coalesce(claim_worker, ''), '', '', 0, '',
                        source_span_id, coalesce(legal_id, ''), status, sealed,
                        coalesce(claim_worker, ''), coalesce(claim_token, ''),
                        source_sha256, coalesce(reason, ''), coalesce(code_identity, ''),
                        '', '', '', '', '', '', '',
                        0, 0, 0, admitted, formalized
                    FROM span_cache
                    WHERE sealed = TRUE OR status = 'gap'
                )
            ) TO '{target}' (FORMAT PARQUET)
            """
        )
        return {
            "admitted": False,
            "formalized": False,
            "gaps": stats["gaps"],
            "path": str(destination),
            "pending": stats["pending"],
            "sealed": stats["sealed"],
        }

    def resume_summary(self, path: str | Path) -> dict[str, Any]:
        """Read resume counts from a parquet checkpoint. Does not admit."""

        rows = self._db.execute(
            """
            SELECT record_kind, count(*)
            FROM read_parquet(?)
            GROUP BY record_kind
            ORDER BY record_kind
            """,
            [str(path)],
        ).fetchall()
        meta = self._db.execute(
            """
            SELECT documents, source_parquet
            FROM read_parquet(?)
            WHERE record_kind = 'meta'
            LIMIT 1
            """,
            [str(path)],
        ).fetchone()
        return {
            "admitted": False,
            "documents": int(meta[0] if meta else 0),
            "formalized": False,
            "kinds": {str(kind): int(count) for kind, count in rows},
            "parquet": str(meta[1] if meta else ""),
        }

    def upsert_remote_resume(self, path: str | Path, *, agent_id: str) -> dict[str, Any]:
        """Observe a remote checkpoint without adopting compile or claim state.

        Resume parquet omits the rule, decompilation, parser/compiler hashes and
        authoritative lease history. Its status rows cannot seal local spans,
        suppress local compilation, or transfer a claim. Only new compatible
        agent observations are stored; all existing local records are kept.
        """

        dataset_id = self._meta("dataset_id")
        imported_agents = 0
        observations: dict[str, int] = {}
        self._db.execute("BEGIN TRANSACTION")
        try:
            # Read once, projecting only observation fields. Do not copy source
            # text, rules, term payloads or other arbitrary parquet columns.
            self._db.execute(
                """
                CREATE TEMPORARY TABLE remote_resume_observations AS
                SELECT record_kind, dataset_id, agent_id, role, heartbeat,
                       documents, source_span_id, source_sha256, status
                FROM read_parquet(?)
                """,
                [str(path)],
            )
            datasets = self._db.execute(
                "SELECT dataset_id FROM remote_resume_observations WHERE record_kind = 'meta'"
            ).fetchall()
            dataset_matched = bool(dataset_id and len(datasets) == 1 and datasets[0][0] == dataset_id)
            if dataset_matched:
                observed = self._db.execute(
                    """
                    SELECT remote.status, count(DISTINCT remote.source_span_id)
                    FROM remote_resume_observations AS remote
                    JOIN span_cache AS local
                      ON remote.source_span_id = local.source_span_id
                     AND remote.source_sha256 = local.source_sha256
                    WHERE remote.record_kind = 'span'
                      AND coalesce(remote.source_sha256, '') <> ''
                      AND remote.status IN ('sealed', 'gap', 'claimed', 'pending', 'unsealed')
                    GROUP BY remote.status ORDER BY remote.status
                    """
                ).fetchall()
                observations = {str(status): int(count) for status, count in observed}
                # Repeated identical observations are harmless. Conflicting
                # records for one remote agent cannot select an arbitrary row.
                self._db.execute(
                    """
                    CREATE TEMPORARY TABLE remote_resume_agents AS
                    SELECT DISTINCT remote.agent_id, remote.dataset_id,
                           remote.role, remote.heartbeat, remote.documents
                    FROM remote_resume_observations AS remote
                    WHERE remote.record_kind = 'agent'
                      AND remote.dataset_id = ?
                      AND coalesce(remote.agent_id, '') <> ''
                      AND remote.agent_id <> ?
                      AND NOT EXISTS (
                          SELECT 1 FROM agent_lease AS existing
                          WHERE existing.agent_id = remote.agent_id
                      )
                    """,
                    [dataset_id, agent_id],
                )
                conflicts = self._db.execute(
                    "SELECT agent_id FROM remote_resume_agents GROUP BY agent_id HAVING count(*) > 1"
                ).fetchall()
                if conflicts:
                    raise SpanCacheError("conflicting remote agent observations")
                imported_agents = int(self._db.execute(
                    "SELECT count(*) FROM remote_resume_agents"
                ).fetchone()[0])
                self._db.execute(
                    """
                    INSERT INTO agent_lease (
                        agent_id, dataset_id, role, heartbeat, claimed_count, admitted, formalized
                    )
                    SELECT remote.agent_id, remote.dataset_id, remote.role,
                           remote.heartbeat, remote.documents, FALSE, FALSE
                    FROM remote_resume_agents AS remote
                    """
                )
                self._db.execute("DROP TABLE remote_resume_agents")
            self._db.execute("DROP TABLE remote_resume_observations")
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return {
            "admitted": False,
            "advisory_only": True,
            "agents_imported": imported_agents,
            "claimed": 0,
            "dataset_matched": dataset_matched,
            "observed_dataset_ids": [str(row[0] or "") for row in datasets],
            "formalized": False,
            "gaps": 0,
            "jsonl_written": False,
            "sealed": 0,
            "source_matched_status_counts": observations,
        }

    def release_stale_claims(self, agent_id: str | None = None) -> int:
        """Return this agent's claimed spans, or every claim when no agent is named."""

        if agent_id:
            row = self._db.execute(
                """
                SELECT count(*) FROM span_cache
                WHERE status = 'claimed' AND sealed = FALSE AND claim_worker = ?
                """,
                [agent_id],
            ).fetchone()
            count = int(row[0] if row else 0)
            if count:
                self._db.execute(
                    """
                    UPDATE span_cache
                    SET status = 'pending', claim_worker = '', claim_token = ''
                    WHERE status = 'claimed' AND sealed = FALSE AND claim_worker = ?
                    """,
                    [agent_id],
                )
            return count
        row = self._db.execute(
            "SELECT count(*) FROM span_cache WHERE status = 'claimed' AND sealed = FALSE"
        ).fetchone()
        count = int(row[0] if row else 0)
        if count:
            self._db.execute(
                """
                UPDATE span_cache
                SET status = 'pending', claim_worker = '', claim_token = ''
                WHERE status = 'claimed' AND sealed = FALSE
                """
            )
        return count

    def _meta(self, key: str) -> str:
        row = self._db.execute("SELECT value FROM cache_meta WHERE key = ?", [key]).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
            [key, value],
        )

    def _existing_span_ids(self, ids: Sequence[str]) -> set[str]:
        existing: set[str] = set()
        for offset in range(0, len(ids), 400):
            chunk = ids[offset : offset + 400]
            if not chunk:
                continue
            placeholders = ", ".join(["?"] * len(chunk))
            found = self._db.execute(
                f"SELECT source_span_id FROM span_cache WHERE source_span_id IN ({placeholders})",
                chunk,
            ).fetchall()
            existing.update(str(row[0]) for row in found)
        return existing

    def _validate_text_batch(self, rows: Sequence[Mapping[str, Any]]) -> None:
        """Refuse the entire actual write set before any persistent mutation."""

        limits = self.text_limits
        if len(rows) > limits.max_batch_rows:
            raise SpanCacheError(f"text write batch exceeds max_batch_rows={limits.max_batch_rows}")
        total = 0
        for row in rows:
            text = str(row.get("text") or row.get("source_text") or "")
            for field, value in (("source_text", text), ("decompiled", str(row.get("decompiled") or ""))):
                if len(value) > limits.max_text_bytes:
                    raise SpanCacheError(f"{field} exceeds max_text_bytes={limits.max_text_bytes}")
                try:
                    encoded = value.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise SpanCacheError(f"{field} is not valid UTF-8") from exc
                size = len(encoded)
                if size > limits.max_text_bytes:
                    raise SpanCacheError(f"{field} exceeds max_text_bytes={limits.max_text_bytes}")
                total += size
                if total > limits.max_batch_text_bytes:
                    raise SpanCacheError(
                        f"text write batch exceeds max_batch_text_bytes={limits.max_batch_text_bytes}"
                    )
            supplied_hash = row.get("source_sha256")
            if supplied_hash and supplied_hash != _sha(text):
                raise SpanCacheError("source_sha256 does not match complete source UTF-8 bytes")

    def _census_write_rows(self, rows: Sequence[Mapping[str, Any]], *, enqueue: bool) -> list[Mapping[str, Any]]:
        """Identify text that INSERT or UPDATE will persist, including earlier inserts."""

        known = self._existing_span_ids([
            str(row.get("source_span_id") or row.get("id") or "") for row in rows
        ])
        writes: list[Mapping[str, Any]] = []
        for row in rows:
            span_id = str(row.get("source_span_id") or row.get("id") or "")
            text = str(row.get("text") or row.get("source_text") or "")
            inserted = row.get("agrees") is True or (enqueue and bool(text))
            if inserted or span_id in known:
                writes.append(row)
            if inserted:
                known.add(span_id)
        return writes

    def enqueue(self, spans: Sequence[Mapping[str, Any]]) -> int:
        """Insert exact pending text or refuse before writes. Existing rows stay intact."""

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for span in spans:
            if not isinstance(span, Mapping):
                continue
            span_id = str(span.get("source_span_id") or span.get("id") or "")
            text = str(span.get("text") or span.get("source_text") or "")
            if not span_id or not text or span_id in seen:
                continue
            seen.add(span_id)
            candidates.append({**span, "source_span_id": span_id, "text": text, "decompiled": ""})
        if not candidates:
            return 0
        existing = self._existing_span_ids([row["source_span_id"] for row in candidates])
        new_rows = [row for row in candidates if row["source_span_id"] not in existing]
        self._validate_text_batch(new_rows)
        fresh = [
            (row["source_span_id"], _sha(row["text"]), str(row.get("legal_id") or ""), row["text"])
            for row in new_rows
        ]
        if fresh:
            self._db.executemany(
                """
                INSERT INTO span_cache (
                    source_span_id, source_sha256, legal_id, source_text, decompiled,
                    reason, status, sealed, code_identity, rule_json, path_hashes,
                    admitted, formalized
                ) VALUES (?, ?, ?, ?, '', '', 'pending', FALSE, '', '', '{}', FALSE, FALSE)
                """,
                fresh,
            )
        return len(fresh)

    def skip_compile(self, span_id: str, *, source_text: str = "") -> dict[str, Any] | None:
        """Return a sealed row when source and compiler identity still match."""

        row = self._db.execute(
            """
            SELECT source_span_id, source_sha256, legal_id, source_text, decompiled,
                   reason, status, sealed, code_identity, rule_json, admitted, formalized
            FROM span_cache WHERE source_span_id = ?
            """,
            [span_id],
        ).fetchone()
        if row is None or not row[7]:
            return None
        if source_text and row[1] != _sha(source_text):
            self.unseal([span_id], reason="source_changed")
            return None
        try:
            rule = json.loads(row[9]) if row[9] else None
        except (TypeError, json.JSONDecodeError):
            rule = None
        if not isinstance(rule, dict):
            # Old status-only resume imports may have sealed an enqueue row
            # whose compile payload was never present. Check on access only;
            # locally stored '{}' remains compatible with existing semantics.
            self.unseal([span_id], reason="incomplete_compile_cache")
            return None
        current = self._meta("code_identity")
        if current and row[8] and row[8] != current:
            return None
        return {
            "admitted": False,
            "agrees": True,
            "decompiled": str(row[4] or ""),
            "formalized": False,
            "legal_id": str(row[2] or ""),
            "reason": "",
            "rule": rule,
            "sealed": True,
            "skipped_compile": True,
            "source_span_id": str(row[0]),
            "source_text": str(row[3] or ""),
            "status": "sealed",
            "text": str(row[3] or ""),
        }

    def unseal(self, span_ids: Sequence[str], *, reason: str = "term_changed") -> int:
        """Return sealed spans to the pending queue. Does not delete evidence."""

        count = 0
        for span_id in span_ids:
            existing = self._db.execute(
                "SELECT sealed FROM span_cache WHERE source_span_id = ?",
                [span_id],
            ).fetchone()
            if not existing or not existing[0]:
                continue
            self._db.execute(
                """
                UPDATE span_cache
                SET sealed = FALSE, status = 'unsealed', reason = ?
                WHERE source_span_id = ?
                """,
                [reason, span_id],
            )
            self._db.execute("DELETE FROM span_terms WHERE source_span_id = ?", [span_id])
            count += 1
        return count

    def unseal_changed(self, path_hashes: Mapping[str, str]) -> dict[str, Any]:
        """Unseal spans whose terms sit on compiler/parser/decompiler files that moved."""

        previous = {
            str(row[0]): str(row[1])
            for row in self._db.execute("SELECT path, sha256 FROM compiler_snapshot").fetchall()
        }
        changed = sorted(
            path for path, digest in path_hashes.items() if previous.get(path) != digest
        )
        for path, digest in path_hashes.items():
            self._db.execute(
                "INSERT OR REPLACE INTO compiler_snapshot (path, sha256) VALUES (?, ?)",
                [path, digest],
            )
        identity = compiler_identity(path_hashes)
        self._set_meta("code_identity", identity)
        if not previous:
            return {
                "changed_paths": [],
                "unsealed": 0,
                "code_identity": identity,
                "admitted": False,
                "formalized": False,
            }
        unsealed_ids: list[str] = []
        if changed:
            rows = self._db.execute(
                """
                SELECT s.source_span_id, t.kind
                FROM span_cache s
                JOIN span_terms st ON st.source_span_id = s.source_span_id
                JOIN sealed_terms t ON t.term_id = st.term_id
                WHERE s.sealed = TRUE
                """
            ).fetchall()
            targets: set[str] = set()
            for span_id, kind in rows:
                paths = TERM_KIND_PATHS.get(str(kind) or "", ())
                if any(path in changed for path in paths):
                    targets.add(str(span_id))
            unsealed_ids = sorted(targets)
            self.unseal(unsealed_ids, reason="term_scope_changed")
        return {
            "changed_paths": changed,
            "unsealed": len(unsealed_ids),
            "unsealed_ids": unsealed_ids,
            "code_identity": identity,
            "admitted": False,
            "formalized": False,
        }

    def apply_census(
        self,
        agreement: Mapping[str, Any],
        *,
        code_identity: str = "",
        path_hashes: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Seal or gap exact text; validate all writes before compiler changes."""

        rows = [
            dict(row) for row in agreement.get("rows") or []
            if isinstance(row, Mapping) and not row.get("skipped")
            and (row.get("source_span_id") or row.get("id"))
        ]
        write_rows = self._census_write_rows(rows, enqueue=True)
        self._validate_text_batch(write_rows)
        hashes = dict(path_hashes or {})
        identity = code_identity or (compiler_identity(hashes) if hashes else self._meta("code_identity"))
        if hashes:
            change = self.unseal_changed(hashes)
        else:
            change = {"changed_paths": [], "unsealed": 0, "code_identity": identity}
        sealed = 0
        # Preserve legacy gap accounting for unknown empty rows, but do not
        # encode or bind payloads that cannot be persisted by an UPDATE.
        gaps = len(rows) - len(write_rows)
        for row in write_rows:
            span_id = str(row.get("source_span_id") or row.get("id") or "")
            text = str(row.get("text") or row.get("source_text") or "")
            if not span_id:
                continue
            self.enqueue([{"source_span_id": span_id, "text": text, "legal_id": row.get("legal_id")}])
            if row.get("agrees") is True:
                self._seal_row(row, code_identity=identity, path_hashes=hashes)
                sealed += 1
            else:
                self._db.execute(
                    """
                    UPDATE span_cache
                    SET source_sha256 = ?, legal_id = ?, source_text = ?, decompiled = ?,
                        reason = ?, rule_json = ?, status = 'gap', sealed = FALSE,
                        admitted = FALSE, formalized = FALSE
                    WHERE source_span_id = ?
                    """,
                    [
                        _sha(text),
                        str(row.get("legal_id") or ""),
                        text,
                        str(row.get("decompiled") or ""),
                        str(row.get("reason") or ""),
                        _repair_json(row.get("repair")),
                        span_id,
                    ],
                )
                gaps += 1
        stats = self.stats()
        return {
            "admitted": False,
            "formalized": False,
            "jsonl_written": False,
            "sealed": sealed,
            "gaps": gaps,
            "unsealed": int(change.get("unsealed") or 0),
            "changed_paths": list(change.get("changed_paths") or []),
            "code_identity": identity,
            "sealed_total": stats["sealed"],
            "pending_total": stats["pending"],
            "gap_total": stats["gaps"],
        }

    def _seal_row(
        self,
        row: Mapping[str, Any],
        *,
        code_identity: str,
        path_hashes: Mapping[str, str],
    ) -> None:
        self._validate_text_batch([row])
        span_id = str(row.get("source_span_id") or row.get("id") or "")
        text = str(row.get("text") or row.get("source_text") or "")
        decompiled = str(row.get("decompiled") or "")
        rule = dict(row.get("rule") or {}) if isinstance(row.get("rule"), Mapping) else {}
        self._db.execute(
            """
            INSERT OR REPLACE INTO span_cache (
                source_span_id, source_sha256, legal_id, source_text, decompiled,
                reason, status, sealed, code_identity, rule_json, path_hashes,
                admitted, formalized
            ) VALUES (?, ?, ?, ?, ?, '', 'sealed', TRUE, ?, ?, ?, FALSE, FALSE)
            """,
            [
                span_id,
                _sha(text),
                str(row.get("legal_id") or ""),
                text,
                decompiled,
                code_identity,
                _json(rule),
                _json(dict(path_hashes)),
            ],
        )
        self._db.execute("DELETE FROM span_terms WHERE source_span_id = ?", [span_id])
        for term in terms_from_rule(rule, decompiled=decompiled):
            self._db.execute(
                """
                INSERT OR REPLACE INTO sealed_terms (term_id, kind, value, value_sha256)
                VALUES (?, ?, ?, ?)
                """,
                [term["term_id"], term["kind"], term["value"], _sha(term["value"])],
            )
            self._db.execute(
                "INSERT OR REPLACE INTO span_terms (source_span_id, term_id) VALUES (?, ?)",
                [span_id, term["term_id"]],
            )

    def claim_batch(self, worker_id: str, *, limit: int = 128) -> list[dict[str, Any]]:
        """Claim pending spans for one owner. Workers must not open this file.

        DuckDB allows one writer on the catalog. The control-plane owner claims
        a batch, hands text to other processes, then writes the census back.
        """

        import uuid

        token = uuid.uuid4().hex
        bounded = max(1, min(int(limit), MAX_BATCH))
        self._db.execute("BEGIN")
        try:
            rows = self._db.execute(
                """
                SELECT source_span_id, legal_id, source_text
                FROM span_cache
                WHERE sealed = FALSE AND status IN ('pending', 'unsealed')
                ORDER BY source_span_id
                LIMIT ?
                """,
                [bounded],
            ).fetchall()
            if not rows:
                self._db.execute("COMMIT")
                return []
            ids = [str(row[0]) for row in rows]
            placeholders = ", ".join(["?"] * len(ids))
            self._db.execute(
                f"""
                UPDATE span_cache
                SET status = 'claimed', claim_worker = ?, claim_token = ?
                WHERE source_span_id IN ({placeholders})
                """,
                [worker_id, token, *ids],
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return [
            {
                "claim_token": token,
                "claim_worker": worker_id,
                "legal_id": str(row[1] or ""),
                "source_span_id": str(row[0]),
                "text": str(row[2] or ""),
            }
            for row in rows
        ]

    def release_claims(self, span_ids: Sequence[str]) -> int:
        """Return claimed spans to pending after a worker failure."""

        count = 0
        for span_id in span_ids:
            updated = self._db.execute(
                """
                UPDATE span_cache
                SET status = 'pending', claim_worker = '', claim_token = ''
                WHERE source_span_id = ? AND status = 'claimed' AND sealed = FALSE
                """,
                [span_id],
            )
            count += int(getattr(updated, "rowcount", 0) or 0) or 1
        return count

    def complete_claimed(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        code_identity: str = "",
        path_hashes: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Seal or gap exact claimed text; refuse oversized batches before writes."""

        rows = [
            dict(row) for row in rows
            if isinstance(row, Mapping) and row.get("source_span_id")
        ]
        write_rows = self._census_write_rows(rows, enqueue=False)
        self._validate_text_batch(write_rows)
        hashes = dict(path_hashes or {})
        identity = code_identity or self._meta("code_identity")
        sealed = 0
        gaps = len(rows) - len(write_rows)
        for row in write_rows:
            if not isinstance(row, Mapping):
                continue
            span_id = str(row.get("source_span_id") or "")
            if not span_id:
                continue
            if row.get("agrees") is True:
                self._seal_row(row, code_identity=identity, path_hashes=hashes)
                sealed += 1
            else:
                text = str(row.get("text") or row.get("source_text") or "")
                self._db.execute(
                    """
                    UPDATE span_cache
                    SET source_sha256 = ?, legal_id = ?, source_text = ?, decompiled = ?,
                        reason = ?, rule_json = ?, status = 'gap', sealed = FALSE, claim_worker = '',
                        claim_token = '', admitted = FALSE, formalized = FALSE
                    WHERE source_span_id = ?
                    """,
                    [
                        _sha(text),
                        str(row.get("legal_id") or ""),
                        text,
                        str(row.get("decompiled") or ""),
                        str(row.get("reason") or "compiler_abstain"),
                        _repair_json(row.get("repair")),
                        span_id,
                    ],
                )
                gaps += 1
        stats = self.stats()
        return {
            "admitted": False,
            "formalized": False,
            "gaps": gaps,
            "gap_total": stats["gaps"],
            "jsonl_written": False,
            "pending_total": stats["pending"],
            "sealed": sealed,
            "sealed_total": stats["sealed"],
        }

    def pending(self, *, limit: int = MAX_BATCH) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """
            SELECT source_span_id, legal_id, source_text, status, reason
            FROM span_cache
            WHERE sealed = FALSE AND status IN ('pending', 'unsealed')
            ORDER BY source_span_id
            LIMIT ?
            """,
            [max(1, min(int(limit), MAX_BATCH))],
        ).fetchall()
        return [
            {
                "source_span_id": str(row[0]),
                "legal_id": str(row[1] or ""),
                "text": str(row[2] or ""),
                "status": str(row[3] or "pending"),
                "reason": str(row[4] or ""),
            }
            for row in rows
        ]

    def process_pending(
        self,
        compile_one: Callable[[str], Mapping[str, Any]],
        *,
        code_identity: str = "",
        path_hashes: Mapping[str, str] | None = None,
        limit: int = MAX_BATCH,
    ) -> dict[str, Any]:
        """Compile every unsealed span. Sealed rows are skipped."""

        hashes = dict(path_hashes or {})
        if hashes:
            self.unseal_changed(hashes)
        rows: list[dict[str, Any]] = []
        skipped = 0
        for span in self.pending(limit=limit):
            cached = self.skip_compile(span["source_span_id"], source_text=span["text"])
            if cached is not None:
                skipped += 1
                continue
            result = dict(compile_one(span["text"]) or {})
            status = str(result.get("compiler_status") or result.get("status") or "")
            agrees = status in {"compiled", "roundtrip_ok"}
            rows.append(
                {
                    "agrees": agrees,
                    "decompiled": str(result.get("decompiled") or ""),
                    "id": span["source_span_id"],
                    "legal_id": span["legal_id"],
                    "reason": "" if agrees else str(result.get("reason") or "compiler_abstain"),
                    "rule": dict(result["rule"]) if isinstance(result.get("rule"), Mapping) else {},
                    "skipped": False,
                    "source_span_id": span["source_span_id"],
                    "text": span["text"],
                }
            )
        applied = self.apply_census(
            {"rows": rows},
            code_identity=code_identity,
            path_hashes=hashes,
        )
        applied["processed"] = len(rows)
        applied["skipped_sealed"] = skipped
        applied["jsonl_written"] = False
        return applied

    def sealed_rows(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """
            SELECT source_span_id, legal_id, source_text, decompiled, code_identity,
                   source_sha256, status, rule_json
            FROM span_cache WHERE sealed = TRUE ORDER BY source_span_id
            """
        ).fetchall()
        payload = []
        for row in rows:
            term_rows = [
                {"term_id": str(item[0]), "kind": str(item[1] or ""), "value": str(item[2] or "")}
                for item in self._db.execute(
                    """
                    SELECT t.term_id, t.kind, t.value
                    FROM span_terms st
                    JOIN sealed_terms t ON t.term_id = st.term_id
                    WHERE st.source_span_id = ?
                    ORDER BY t.term_id
                    """,
                    [row[0]],
                ).fetchall()
            ]
            payload.append(
                {
                    "admitted": False,
                    "code_identity": str(row[4] or ""),
                    "decompiled": str(row[3] or ""),
                    "formalized": False,
                    "legal_id": str(row[1] or ""),
                    "rule_json": str(row[7] or ""),
                    "sealed": True,
                    "source_sha256": str(row[5] or ""),
                    "source_span_id": str(row[0]),
                    "source_text": str(row[2] or ""),
                    "status": str(row[6] or "sealed"),
                    "term_ids": [item["term_id"] for item in term_rows],
                    "term_rows": term_rows,
                    "term_rows_json": _json(term_rows),
                }
            )
        return payload

    def save_gap_repairs(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Store the codec and compiler capsule on existing gap rows. Does not admit them."""

        saved = 0
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            span_id = str(row.get("source_span_id") or "")
            repair = row.get("repair")
            if not span_id or not isinstance(repair, Mapping):
                continue
            self._db.execute(
                """
                UPDATE span_cache
                SET rule_json = ?, admitted = FALSE, formalized = FALSE
                WHERE source_span_id = ? AND status = 'gap'
                """,
                [_repair_json(repair), span_id],
            )
            found = self._db.execute(
                "SELECT rule_json FROM span_cache WHERE source_span_id = ? AND status = 'gap'",
                [span_id],
            ).fetchone()
            if found and found[0]:
                saved += 1
        return saved

    def list_gaps(self, *, limit: int = 64, after: str = "") -> list[dict[str, Any]]:
        """Return failed span compiles for a replay loop. Does not train."""

        rows = self._db.execute(
            """
            SELECT source_span_id, legal_id, source_text, reason, rule_json
            FROM span_cache
            WHERE status = 'gap' AND source_span_id > ?
            ORDER BY source_span_id
            LIMIT ?
            """,
            [after, max(1, min(int(limit), MAX_BATCH))],
        ).fetchall()
        return [
            {
                "legal_id": str(row[1] or ""),
                "reason": str(row[3] or ""),
                "repair": _repair_load(row[4] if len(row) > 4 else ""),
                "source_span_id": str(row[0]),
                "text": str(row[2] or ""),
            }
            for row in rows
        ]

    def stats(self) -> dict[str, int]:
        sealed = self._db.execute("SELECT count(*) FROM span_cache WHERE sealed = TRUE").fetchone()[0]
        gaps = self._db.execute("SELECT count(*) FROM span_cache WHERE status = 'gap'").fetchone()[0]
        pending = self._db.execute("SELECT count(*) FROM span_cache WHERE sealed = FALSE").fetchone()[0]
        terms = self._db.execute("SELECT count(*) FROM sealed_terms").fetchone()[0]
        return {
            "sealed": int(sealed),
            "gaps": int(gaps),
            "pending": int(pending),
            "terms": int(terms),
        }

    def export_rows(self) -> list[dict[str, Any]]:
        return self.sealed_rows()

    def mark_flushed(self) -> None:
        self._last_flush = self.stats()["sealed"]
        self._set_meta("last_flush_sealed", str(self._last_flush))

    def due_for_flush(self, *, every: int = 32) -> bool:
        sealed = self.stats()["sealed"]
        return sealed > 0 and sealed - self._last_flush >= max(1, int(every))

    def statute_groups(self) -> dict[str, list[dict[str, Any]]]:
        rows = self._db.execute(
            """
            SELECT legal_id, source_span_id, source_sha256, source_text, rule_json
            FROM span_cache WHERE sealed = TRUE ORDER BY legal_id, source_span_id
            """
        ).fetchall()
        exported = [
            {
                "legal_id": str(row[0] or ""),
                "rule_json": str(row[4] or ""),
                "sealed": True,
                "source_sha256": str(row[2] or ""),
                "source_span_id": str(row[1]),
                "source_text": str(row[3] or ""),
                "status": "sealed",
            }
            for row in rows
        ]
        return group_span_rows(exported)["statutes"]

    def term_groups(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """
            SELECT t.term_id, t.kind, t.value, s.legal_id
            FROM sealed_terms t
            JOIN span_terms st ON st.term_id = t.term_id
            JOIN span_cache s ON s.source_span_id = st.source_span_id
            WHERE s.sealed = TRUE
            ORDER BY t.kind, t.value, s.legal_id
            """
        ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for term_id, kind, value, legal_id in rows:
            key = str(term_id)
            item = grouped.setdefault(
                key,
                {
                    "kind": str(kind or ""),
                    "statute_ids": [],
                    "term_id": key,
                    "value": str(value or ""),
                },
            )
            statute = str(legal_id or "").strip() or "unspecified"
            if statute not in item["statute_ids"]:
                item["statute_ids"].append(statute)
        for item in grouped.values():
            item["statute_ids"] = sorted(item["statute_ids"])
        return sorted(grouped.values(), key=lambda item: (item["kind"], item["value"], item["term_id"]))

    def build_lean_units(
        self,
        *,
        check: Callable[..., Mapping[str, Any]] | None = None,
        verify: bool = True,
        max_term_checks: int = 8,
    ) -> dict[str, Any]:
        """Render per-statute and per-term Lean files. Lake-check changed sources."""

        from .lean_units import probe_lean_source, render_statute_lean, render_term_lean

        statutes = []
        terms = []
        for legal_id, clauses in self.statute_groups().items():
            source = render_statute_lean(legal_id, clauses)
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            previous = self._db.execute(
                "SELECT source_sha256, lake_ok, lake_error FROM lean_statutes WHERE legal_id = ?",
                [legal_id],
            ).fetchone()
            lake_ok = bool(previous[1]) if previous and previous[0] == digest else False
            lake_error = str(previous[2] or "") if previous and previous[0] == digest else "lake_not_run"
            if verify and (not previous or previous[0] != digest):
                probed = probe_lean_source(source, check=check)
                lake_ok = bool(probed.get("lake_ok"))
                lake_error = str(probed.get("error") or "")
            self._db.execute(
                """
                INSERT OR REPLACE INTO lean_statutes (
                    legal_id, lean_source, source_sha256, lake_ok, lake_error,
                    clause_count, admitted, formalized
                ) VALUES (?, ?, ?, ?, ?, ?, FALSE, FALSE)
                """,
                [legal_id, source, digest, lake_ok, lake_error, len(clauses)],
            )
            statutes.append(
                {
                    "admitted": False,
                    "clause_count": len(clauses),
                    "formalized": False,
                    "lake_error": lake_error,
                    "lake_ok": lake_ok,
                    "legal_id": legal_id,
                }
            )
        term_checks = 0
        for item in self.term_groups():
            source = render_term_lean(
                item["kind"], item["value"], statute_ids=item["statute_ids"]
            )
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            previous = self._db.execute(
                "SELECT source_sha256, lake_ok, lake_error FROM lean_terms WHERE term_id = ?",
                [item["term_id"]],
            ).fetchone()
            lake_ok = bool(previous[1]) if previous and previous[0] == digest else False
            lake_error = str(previous[2] or "") if previous and previous[0] == digest else "lake_not_run"
            should_check = verify and (not previous or previous[0] != digest)
            if should_check and term_checks < max_term_checks:
                probed = probe_lean_source(source, check=check)
                lake_ok = bool(probed.get("lake_ok"))
                lake_error = str(probed.get("error") or "")
                term_checks += 1
            self._db.execute(
                """
                INSERT OR REPLACE INTO lean_terms (
                    term_id, kind, value, lean_source, source_sha256, lake_ok,
                    lake_error, statute_count, admitted, formalized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, FALSE, FALSE)
                """,
                [
                    item["term_id"],
                    item["kind"],
                    item["value"],
                    source,
                    digest,
                    lake_ok,
                    lake_error,
                    len(item["statute_ids"]),
                ],
            )
            terms.append(
                {
                    "admitted": False,
                    "formalized": False,
                    "kind": item["kind"],
                    "lake_error": lake_error,
                    "lake_ok": lake_ok,
                    "statute_count": len(item["statute_ids"]),
                    "term_id": item["term_id"],
                    "value": item["value"],
                }
            )
        return {
            "admitted": False,
            "formalized": False,
            "statute_count": len(statutes),
            "statutes": statutes,
            "term_count": len(terms),
            "terms": terms,
            "jsonl_written": False,
        }

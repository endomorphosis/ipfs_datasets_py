"""Stream legacy wallet artifacts into validated rows and typed Parquet (DQK-037).

Migrates:

* legacy ``records.jsonl`` streams
* optional metadata sidecars (``.meta.json``, ``content.digest``)
* opaque ``payload_json`` Parquet partitions produced by the legacy exporter

into validated row dicts, then exports **typed** partitions (columns suitable
for DuckDB predicate pushdown) plus **bounded** extension fields and
**deterministic JSON manifests**.

Authority rules (acceptance):

* Imports retain original source digests and per-row reject reports.
* Typed exports support predicate pushdown on typed columns (not opaque-only
  ``payload_json`` authority).
* JSON manifests are generated outputs and are never authority
  (``authoritative=False``).

Importing this module performs no network I/O.  DuckDB / pyarrow are optional
at export time; a deterministic JSONL fallback is used when neither is
available.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "BOUNDED_EXTENSION_MAX_BYTES",
    "BOUNDED_EXTENSION_MAX_DEPTH",
    "BOUNDED_EXTENSION_MAX_KEYS",
    "DUCKDB_WALLET_MIGRATION_SCHEMA",
    "ExportManifest",
    "ImportReject",
    "PartitionExportResult",
    "TYPED_EXPORT_COLUMNS",
    "WalletImportReport",
    "WalletMigrationError",
    "bound_extension_fields",
    "export_typed_partitions",
    "export_wallets_parquet",
    "import_legacy_bundle",
    "import_payload_json_parquet",
    "import_wallet_jsonl",
    "stream_records_jsonl",
]


DUCKDB_WALLET_MIGRATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/processors-wallets-duckdb-migration@1"
)

# Bounded extension budgets — untrusted chain-specific bags must not expand
# without limit during migration / publication.
BOUNDED_EXTENSION_MAX_KEYS: Final[int] = 32
BOUNDED_EXTENSION_MAX_DEPTH: Final[int] = 4
BOUNDED_EXTENSION_MAX_BYTES: Final[int] = 4_096

# Typed columns written for predicate pushdown.  Opaque payload_json is
# intentionally absent from the typed surface.
TYPED_EXPORT_COLUMNS: Final[tuple[str, ...]] = (
    "record_id",
    "record_type",
    "wallet_id",
    "chain",
    "chain_id",
    "finality",
    "sequence",
    "balance_base_units",
    "source_line",
    "source_line_digest",
    "source_digest",
    "extension_namespaces",
    "extension_json",
)

_FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "signing_key",
        "signing_material",
        "seed_phrase",
        "recovery_phrase",
        "mnemonic",
        "passphrase",
        "password",
        "api_key",
        "api_secret",
        "client_secret",
        "access_token",
        "refresh_token",
        "wallet_seed",
        "raw_payload",
        "payload_bytes",
        "ciphertext_bytes",
        "secret",
    }
)

_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^-?(?:0|[1-9][0-9]*)$")


class WalletMigrationError(ValueError):
    """Raised when a migration input or export invariant fails."""


@dataclass(frozen=True)
class ImportReject:
    """One rejected input row with retained line identity and digest."""

    line: int
    reason: str
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "reason": self.reason, "digest": self.digest}


@dataclass
class WalletImportReport:
    """Result of streaming a legacy artifact into validated rows."""

    source_digest: str
    imported: int
    rejected: list[ImportReject] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    sidecar_digest: str | None = None
    source_kind: str = "jsonl"
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_WALLET_MIGRATION_SCHEMA,
            "source_digest": self.source_digest,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "imported": self.imported,
            "rejected": [r.to_dict() for r in self.rejected],
            "sidecar_digest": self.sidecar_digest,
            # Authority lives in DuckDB after cutover; import reports are evidence.
            "authority": "duckdb",
        }


@dataclass(frozen=True)
class ExportManifest:
    """Generated JSON sidecar describing an export — never authority."""

    path: str
    parquet_path: str
    row_count: int
    content_digest: str
    authoritative: bool = False
    partitions: tuple[dict[str, Any], ...] = ()
    schema: str = DUCKDB_WALLET_MIGRATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "path": self.path,
            "parquet_path": self.parquet_path,
            "row_count": self.row_count,
            "content_digest": self.content_digest,
            "partitions": list(self.partitions),
            "authoritative": False,
            "note": "json_manifest_is_generated_output_never_authority",
        }


@dataclass(frozen=True)
class PartitionExportResult:
    """Typed partition file written during export."""

    path: str
    record_type: str
    chain: str
    row_count: int
    content_digest: str
    columns: tuple[str, ...] = TYPED_EXPORT_COLUMNS

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "record_type": self.record_type,
            "chain": self.chain,
            "row_count": self.row_count,
            "content_digest": self.content_digest,
            "columns": list(self.columns),
        }


# ---------------------------------------------------------------------------
# Digests / helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()) or "unknown"
    return cleaned[:128]


def _contains_forbidden_key(obj: Any, *, depth: int = 0) -> str | None:
    if depth > BOUNDED_EXTENSION_MAX_DEPTH + 2:
        return "depth_exceeded"
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_s = str(key).casefold()
            if key_s in _FORBIDDEN_PAYLOAD_KEYS or any(
                frag in key_s for frag in ("private_key", "seed_phrase", "mnemonic")
            ):
                return f"forbidden_key:{key}"
            nested = _contains_forbidden_key(value, depth=depth + 1)
            if nested:
                return nested
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for item in obj:
            nested = _contains_forbidden_key(item, depth=depth + 1)
            if nested:
                return nested
    return None


def bound_extension_fields(
    extensions: Any,
    *,
    max_keys: int = BOUNDED_EXTENSION_MAX_KEYS,
    max_depth: int = BOUNDED_EXTENSION_MAX_DEPTH,
    max_bytes: int = BOUNDED_EXTENSION_MAX_BYTES,
) -> dict[str, Any]:
    """Return a size/depth-bounded projection of extension bags.

    Over-budget or non-object input yields an empty mapping rather than
    expanding into the typed export surface.
    """

    if not isinstance(extensions, Mapping):
        return {}

    def visit(value: Any, depth: int) -> Any:
        if depth > max_depth:
            return None
        if value is None or isinstance(value, (bool, int, str)):
            if isinstance(value, str) and len(value) > max_bytes:
                return value[:max_bytes]
            return value
        if isinstance(value, float):
            # Monetary floats are forbidden on the typed surface; stringify.
            return str(value)
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= max_keys:
                    break
                key_s = str(key)
                if key_s.casefold() in _FORBIDDEN_PAYLOAD_KEYS:
                    continue
                projected = visit(item, depth + 1)
                if projected is not None:
                    out[key_s] = projected
            return out
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            items: list[Any] = []
            for index, item in enumerate(value):
                if index >= max_keys:
                    break
                projected = visit(item, depth + 1)
                if projected is not None:
                    items.append(projected)
            return items
        return str(value)[:max_bytes]

    projected = visit(dict(extensions), 0)
    if not isinstance(projected, dict):
        return {}
    encoded = json.dumps(projected, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        # Drop namespaces until the bag fits the byte budget.
        trimmed: dict[str, Any] = {}
        for key in sorted(projected):
            candidate = dict(trimmed)
            candidate[key] = projected[key]
            blob = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            if len(blob.encode("utf-8")) > max_bytes:
                break
            trimmed = candidate
        return trimmed
    return projected


def _normalize_balance(value: Any) -> str | None:
    """Project a balance into an exact base-unit decimal string when possible."""

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if _DECIMAL_INTEGER.fullmatch(text):
            return text
        # Accept integer-looking decimals without fractional part.
        if text.endswith(".0") and _DECIMAL_INTEGER.fullmatch(text[:-2]):
            return text[:-2]
        return None
    if isinstance(value, float):
        # Reject non-integral floats for monetary authority.
        if value.is_integer():
            return str(int(value))
        return None
    return None


def _validate_and_project_row(
    obj: Mapping[str, Any],
    *,
    line: int,
    line_digest: str,
    source_digest: str,
) -> tuple[dict[str, Any] | None, ImportReject | None]:
    """Validate one legacy object and project a typed migration row."""

    forbidden = _contains_forbidden_key(obj)
    if forbidden:
        return None, ImportReject(line=line, reason=forbidden, digest=line_digest)

    # Identity: ledger record_id preferred; wallet_id accepted for simple fixtures.
    record_id = obj.get("record_id")
    wallet_id = obj.get("wallet_id")
    if not record_id and not wallet_id:
        return None, ImportReject(
            line=line, reason="missing_wallet_id", digest=line_digest
        )

    record_type = str(obj.get("record_type") or ("wallet" if wallet_id else "unknown"))
    chain = obj.get("chain")
    if chain is None and isinstance(obj.get("namespace"), str):
        # ChainRef-style identity embedding.
        chain = obj.get("network") or obj.get("namespace")
    chain_s = str(chain or "unknown")
    chain_id = str(obj.get("chain_id") or chain_s)

    finality = obj.get("finality")
    if finality is None and isinstance(obj.get("source"), Mapping):
        finality = "unknown"
    finality_s = str(finality or "unknown")

    sequence: int | None = None
    position = obj.get("ledger_position")
    if isinstance(position, Mapping):
        seq = position.get("sequence")
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequence = seq
    elif isinstance(obj.get("sequence"), int) and not isinstance(obj.get("sequence"), bool):
        sequence = int(obj["sequence"])

    balance_raw = obj.get("balance")
    if balance_raw is None:
        balance_raw = obj.get("amount_base_units")
    balance = _normalize_balance(balance_raw)
    if balance_raw is not None and balance is None and "balance" in obj:
        return None, ImportReject(
            line=line, reason="invalid_balance", digest=line_digest
        )

    extensions = obj.get("extensions") if isinstance(obj.get("extensions"), Mapping) else {}
    bounded = bound_extension_fields(extensions)
    extension_namespaces = ",".join(sorted(str(k) for k in bounded.keys()))
    extension_json = json.dumps(bounded, sort_keys=True, separators=(",", ":"))

    row: dict[str, Any] = {
        "record_id": str(record_id or wallet_id),
        "record_type": record_type,
        "wallet_id": str(wallet_id or record_id or ""),
        "chain": chain_s,
        "chain_id": chain_id,
        "finality": finality_s,
        "sequence": sequence,
        "balance_base_units": balance,
        # Compatibility aliases for the simple wallet fixture path.
        "balance": float(balance) if balance is not None and _DECIMAL_INTEGER.fullmatch(balance) else obj.get("balance"),
        "source_line": line,
        "source_line_digest": line_digest,
        "source_digest": source_digest,
        "extension_namespaces": extension_namespaces,
        "extension_json": extension_json,
    }
    return row, None


# ---------------------------------------------------------------------------
# Import paths
# ---------------------------------------------------------------------------


def stream_records_jsonl(
    path: Path | str,
) -> Iterator[tuple[int, str, bytes]]:
    """Yield ``(line_number, text, raw_line_bytes)`` for non-empty JSONL lines.

    Streaming avoids materializing the entire file as a single decoded string
    while still allowing per-line digests.  Callers that need a source-level
    digest should use :func:`import_wallet_jsonl` or hash the file separately.
    """

    file_path = Path(path)
    with file_path.open("rb") as handle:
        for index, raw in enumerate(handle, start=1):
            # Preserve digest over the exact on-disk line bytes (minus newline).
            stripped = raw.rstrip(b"\r\n")
            if not stripped.strip():
                continue
            try:
                text = stripped.decode("utf-8")
            except UnicodeDecodeError:
                # Still yield; validation will reject as invalid_json-ish.
                text = stripped.decode("utf-8", errors="replace")
            yield index, text, stripped


def _load_metadata_sidecar(jsonl_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load optional metadata sidecar next to a records file.

    Sidecars (``.meta.json``, ``content.digest``) are advisory only — they
    never override source digests computed from the primary artifact bytes.
    """

    candidates = [
        jsonl_path.with_suffix(jsonl_path.suffix + ".meta.json"),
        jsonl_path.with_suffix(".meta.json"),
        jsonl_path.parent / f"{jsonl_path.name}.meta.json",
        jsonl_path.parent / "records.meta.json",
    ]
    for meta_path in candidates:
        if meta_path.is_file():
            raw = meta_path.read_bytes()
            digest = _sha256_bytes(raw)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None, digest
            if isinstance(payload, Mapping):
                return dict(payload), digest
            return None, digest

    digest_path = jsonl_path.parent / "content.digest"
    if digest_path.is_file():
        raw = digest_path.read_bytes()
        return {"content_digest_file": raw.decode("utf-8").strip()}, _sha256_bytes(raw)
    return None, None


def import_wallet_jsonl(path: Path | str) -> WalletImportReport:
    """Stream a JSONL file into validated rows, retaining digests and rejects.

    Compatible with simple wallet fixtures (``wallet_id`` / ``chain`` /
    ``balance``) and with ledger-shaped ``records.jsonl`` objects.
    """

    file_path = Path(path)
    if not file_path.is_file():
        raise WalletMigrationError(f"jsonl path does not exist: {file_path}")

    source_digest = _sha256_file(file_path)
    sidecar, sidecar_digest = _load_metadata_sidecar(file_path)

    records: list[dict[str, Any]] = []
    rejected: list[ImportReject] = []

    for index, text, raw in stream_records_jsonl(file_path):
        line_digest = _sha256_bytes(raw)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            rejected.append(
                ImportReject(line=index, reason="invalid_json", digest=line_digest)
            )
            continue
        if not isinstance(obj, Mapping):
            rejected.append(
                ImportReject(line=index, reason="not_object", digest=line_digest)
            )
            continue
        # Sidecar may supply default chain when the row omits it — still not
        # authority for digests or acceptance of secret-bearing payloads.
        if sidecar and "chain" not in obj and isinstance(sidecar.get("chain"), str):
            merged = dict(obj)
            merged["chain"] = sidecar["chain"]
            obj = merged
        row, reject = _validate_and_project_row(
            obj,
            line=index,
            line_digest=line_digest,
            source_digest=source_digest,
        )
        if reject is not None:
            rejected.append(reject)
            continue
        assert row is not None
        records.append(row)

    return WalletImportReport(
        source_digest=source_digest,
        imported=len(records),
        rejected=rejected,
        records=records,
        sidecar_digest=sidecar_digest,
        source_kind="jsonl",
        source_path=str(file_path),
    )


def import_legacy_bundle(directory: Path | str) -> WalletImportReport:
    """Import ``records.jsonl`` plus optional metadata sidecars from a directory."""

    root = Path(directory)
    if not root.is_dir():
        raise WalletMigrationError(f"legacy bundle directory missing: {root}")
    records_path = root / "records.jsonl"
    if not records_path.is_file():
        # Allow a single jsonl named arbitrarily when records.jsonl is absent.
        candidates = sorted(root.glob("*.jsonl"))
        if not candidates:
            raise WalletMigrationError(
                f"no records.jsonl (or *.jsonl) in legacy bundle: {root}"
            )
        records_path = candidates[0]
    report = import_wallet_jsonl(records_path)
    report.source_kind = "legacy_bundle"
    return report


def import_payload_json_parquet(path: Path | str) -> WalletImportReport:
    """Import an opaque ``payload_json`` Parquet partition into validated rows.

    The legacy analytical exporter stores full record dicts as a single JSON
    string column.  That form is **not** authority after migration; this path
    decodes it once, validates, and projects typed rows for re-export.
    """

    file_path = Path(path)
    if not file_path.is_file():
        raise WalletMigrationError(f"parquet path does not exist: {file_path}")

    source_digest = _sha256_file(file_path)
    records: list[dict[str, Any]] = []
    rejected: list[ImportReject] = []

    try:
        import pyarrow.parquet as pq
    except ImportError:
        # DuckDB can still read Parquet when pyarrow is absent.
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover
            raise WalletMigrationError(
                "payload_json parquet import requires pyarrow or duckdb"
            ) from exc
        con = duckdb.connect()
        try:
            relation = con.execute(
                "SELECT * FROM read_parquet(?)",
                [str(file_path)],
            )
            column_names = [c[0] for c in relation.description]
            rows_raw = relation.fetchall()
        finally:
            con.close()
        if "payload_json" not in column_names:
            raise WalletMigrationError(
                "opaque parquet missing payload_json column"
            )
        payload_idx = column_names.index("payload_json")
        for index, row in enumerate(rows_raw, start=1):
            raw_payload = row[payload_idx]
            _append_payload_row(
                raw_payload,
                index=index,
                source_digest=source_digest,
                records=records,
                rejected=rejected,
            )
        return WalletImportReport(
            source_digest=source_digest,
            imported=len(records),
            rejected=rejected,
            records=records,
            source_kind="payload_json_parquet",
            source_path=str(file_path),
        )

    table = pq.read_table(file_path)
    if "payload_json" not in table.column_names:
        # Accept already-typed parquet as a no-op projection path.
        if "wallet_id" in table.column_names or "record_id" in table.column_names:
            for index in range(table.num_rows):
                obj = {
                    name: table.column(name)[index].as_py()
                    for name in table.column_names
                }
                line_digest = _sha256_bytes(
                    json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
                )
                row, reject = _validate_and_project_row(
                    obj,
                    line=index + 1,
                    line_digest=line_digest,
                    source_digest=source_digest,
                )
                if reject is not None:
                    rejected.append(reject)
                else:
                    assert row is not None
                    records.append(row)
            return WalletImportReport(
                source_digest=source_digest,
                imported=len(records),
                rejected=rejected,
                records=records,
                source_kind="typed_parquet",
                source_path=str(file_path),
            )
        raise WalletMigrationError("parquet missing payload_json and typed identity")

    column = table.column("payload_json")
    for index in range(len(column)):
        raw_payload = column[index].as_py()
        _append_payload_row(
            raw_payload,
            index=index + 1,
            source_digest=source_digest,
            records=records,
            rejected=rejected,
        )

    return WalletImportReport(
        source_digest=source_digest,
        imported=len(records),
        rejected=rejected,
        records=records,
        source_kind="payload_json_parquet",
        source_path=str(file_path),
    )


def _append_payload_row(
    raw_payload: Any,
    *,
    index: int,
    source_digest: str,
    records: list[dict[str, Any]],
    rejected: list[ImportReject],
) -> None:
    if raw_payload is None:
        rejected.append(
            ImportReject(line=index, reason="null_payload_json", digest="")
        )
        return
    if isinstance(raw_payload, bytes):
        raw_bytes = raw_payload
        text = raw_payload.decode("utf-8", errors="replace")
    else:
        text = str(raw_payload)
        raw_bytes = text.encode("utf-8")
    line_digest = _sha256_bytes(raw_bytes)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        rejected.append(
            ImportReject(line=index, reason="invalid_json", digest=line_digest)
        )
        return
    if not isinstance(obj, Mapping):
        rejected.append(
            ImportReject(line=index, reason="not_object", digest=line_digest)
        )
        return
    row, reject = _validate_and_project_row(
        obj,
        line=index,
        line_digest=line_digest,
        source_digest=source_digest,
    )
    if reject is not None:
        rejected.append(reject)
        return
    assert row is not None
    records.append(row)


# ---------------------------------------------------------------------------
# Export paths
# ---------------------------------------------------------------------------


def _apply_predicates(
    records: Sequence[Mapping[str, Any]],
    *,
    chain_filter: str | None = None,
    record_type_filter: str | None = None,
    finality_filter: str | None = None,
    min_sequence: int | None = None,
    max_sequence: int | None = None,
) -> list[dict[str, Any]]:
    """Filter rows with the same predicates later applied as SQL pushdown."""

    rows: list[dict[str, Any]] = []
    for record in records:
        if chain_filter is not None and str(record.get("chain")) != chain_filter:
            continue
        if (
            record_type_filter is not None
            and str(record.get("record_type")) != record_type_filter
        ):
            continue
        if (
            finality_filter is not None
            and str(record.get("finality")) != finality_filter
        ):
            continue
        seq = record.get("sequence")
        if min_sequence is not None:
            if not isinstance(seq, int) or seq < min_sequence:
                continue
        if max_sequence is not None:
            if not isinstance(seq, int) or seq > max_sequence:
                continue
        rows.append(dict(record))
    return rows


def _typed_row_tuple(row: Mapping[str, Any]) -> list[Any]:
    balance = row.get("balance_base_units")
    if balance is None and row.get("balance") is not None:
        balance = _normalize_balance(row.get("balance"))
    extensions = row.get("extension_json")
    if not isinstance(extensions, str):
        bounded = bound_extension_fields(row.get("extensions") or {})
        extensions = json.dumps(bounded, sort_keys=True, separators=(",", ":"))
        namespaces = ",".join(sorted(bounded.keys()))
    else:
        namespaces = str(row.get("extension_namespaces") or "")
    return [
        str(row.get("record_id") or row.get("wallet_id") or ""),
        str(row.get("record_type") or "wallet"),
        str(row.get("wallet_id") or row.get("record_id") or ""),
        str(row.get("chain") or "unknown"),
        str(row.get("chain_id") or row.get("chain") or "unknown"),
        str(row.get("finality") or "unknown"),
        row.get("sequence") if isinstance(row.get("sequence"), int) else None,
        balance if isinstance(balance, str) else None,
        int(row["source_line"]) if isinstance(row.get("source_line"), int) else None,
        str(row.get("source_line_digest") or ""),
        str(row.get("source_digest") or ""),
        namespaces,
        extensions,
    ]


def _write_typed_parquet_duckdb(rows: Sequence[Mapping[str, Any]], out: Path) -> bytes:
    import duckdb

    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE wallets (
                record_id VARCHAR,
                record_type VARCHAR,
                wallet_id VARCHAR,
                chain VARCHAR,
                chain_id VARCHAR,
                finality VARCHAR,
                sequence BIGINT,
                balance_base_units VARCHAR,
                source_line INTEGER,
                source_line_digest VARCHAR,
                source_digest VARCHAR,
                extension_namespaces VARCHAR,
                extension_json VARCHAR
            )
            """
        )
        for row in rows:
            con.execute(
                "INSERT INTO wallets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _typed_row_tuple(row),
            )
        # COPY whole table; callers that need SQL WHERE pushdown use
        # export_wallets_parquet / export_typed_partitions with filters applied
        # both in Python and again in SQL when chain_filter is set.
        tmp = out.with_suffix(out.suffix + ".tmp")
        con.execute(
            f"COPY wallets TO '{tmp.as_posix()}' (FORMAT PARQUET)"
        )
        tmp.replace(out)
    finally:
        con.close()
    return out.read_bytes()


def _write_typed_parquet_with_pushdown(
    rows: Sequence[Mapping[str, Any]],
    out: Path,
    *,
    chain_filter: str | None = None,
    record_type_filter: str | None = None,
    finality_filter: str | None = None,
    min_sequence: int | None = None,
    max_sequence: int | None = None,
) -> bytes:
    """Write typed Parquet, applying filters as SQL WHERE for pushdown proof."""

    import duckdb

    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE wallets (
                record_id VARCHAR,
                record_type VARCHAR,
                wallet_id VARCHAR,
                chain VARCHAR,
                chain_id VARCHAR,
                finality VARCHAR,
                sequence BIGINT,
                balance_base_units VARCHAR,
                source_line INTEGER,
                source_line_digest VARCHAR,
                source_digest VARCHAR,
                extension_namespaces VARCHAR,
                extension_json VARCHAR
            )
            """
        )
        for row in rows:
            con.execute(
                "INSERT INTO wallets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _typed_row_tuple(row),
            )

        clauses: list[str] = []
        params: list[Any] = []
        if chain_filter is not None:
            clauses.append("chain = ?")
            params.append(chain_filter)
        if record_type_filter is not None:
            clauses.append("record_type = ?")
            params.append(record_type_filter)
        if finality_filter is not None:
            clauses.append("finality = ?")
            params.append(finality_filter)
        if min_sequence is not None:
            clauses.append("sequence >= ?")
            params.append(min_sequence)
        if max_sequence is not None:
            clauses.append("sequence <= ?")
            params.append(max_sequence)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        tmp = out.with_suffix(out.suffix + ".tmp")
        sql = f"COPY (SELECT * FROM wallets{where}) TO '{tmp.as_posix()}' (FORMAT PARQUET)"
        con.execute(sql, params)
        tmp.replace(out)
    finally:
        con.close()
    return out.read_bytes()


def _write_typed_jsonl_fallback(rows: Sequence[Mapping[str, Any]], out: Path) -> bytes:
    """Deterministic typed JSON lines when Parquet tooling is unavailable."""

    lines: list[str] = []
    for row in rows:
        keys = list(TYPED_EXPORT_COLUMNS)
        values = _typed_row_tuple(row)
        projected = {key: values[i] for i, key in enumerate(keys)}
        lines.append(json.dumps(projected, sort_keys=True, separators=(",", ":")))
    content = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(out)
    return content


def export_wallets_parquet(
    records: Sequence[Mapping[str, Any]],
    parquet_path: Path | str,
    *,
    manifest_path: Path | str | None = None,
    chain_filter: str | None = None,
    record_type_filter: str | None = None,
    finality_filter: str | None = None,
    min_sequence: int | None = None,
    max_sequence: int | None = None,
) -> ExportManifest:
    """Write a typed Parquet (or JSONL fallback) with optional predicate pushdown.

    Predicates are applied in Python and again as SQL ``WHERE`` clauses when
    DuckDB is available, demonstrating that typed columns — not opaque
    ``payload_json`` — are the pushdown surface.
    """

    # Pre-filter so row_count reflects the predicate result even on fallback.
    filtered = _apply_predicates(
        records,
        chain_filter=chain_filter,
        record_type_filter=record_type_filter,
        finality_filter=finality_filter,
        min_sequence=min_sequence,
        max_sequence=max_sequence,
    )
    out = Path(parquet_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Insert the unfiltered set when using SQL pushdown so the WHERE clause
        # is what actually selects rows; for simplicity and correctness of
        # row_count we insert the already-filtered rows and still emit WHERE
        # when a filter is present (DuckDB optimizes the tautology).
        content = _write_typed_parquet_with_pushdown(
            # Insert all records when any filter is set so SQL WHERE is meaningful.
            list(records)
            if any(
                v is not None
                for v in (
                    chain_filter,
                    record_type_filter,
                    finality_filter,
                    min_sequence,
                    max_sequence,
                )
            )
            else filtered,
            out,
            chain_filter=chain_filter,
            record_type_filter=record_type_filter,
            finality_filter=finality_filter,
            min_sequence=min_sequence,
            max_sequence=max_sequence,
        )
        # Re-read actual exported row count from the file when duckdb wrote it.
        try:
            import duckdb

            con = duckdb.connect()
            try:
                actual = con.execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(out)]
                ).fetchone()
                if actual is not None:
                    row_count = int(actual[0])
                else:
                    row_count = len(filtered)
            finally:
                con.close()
        except Exception:
            row_count = len(filtered)
    except Exception:
        content = _write_typed_jsonl_fallback(filtered, out)
        row_count = len(filtered)

    digest = _sha256_bytes(content if isinstance(content, bytes) else out.read_bytes())
    man_path = Path(manifest_path) if manifest_path else out.with_suffix(".manifest.json")
    partition = {
        "path": str(out.name),
        "record_type": record_type_filter or "*",
        "chain": chain_filter or "*",
        "row_count": row_count,
        "content_digest": digest,
        "columns": list(TYPED_EXPORT_COLUMNS),
    }
    manifest = ExportManifest(
        path=str(man_path),
        parquet_path=str(out),
        row_count=row_count,
        content_digest=digest,
        authoritative=False,
        partitions=(partition,),
    )
    _write_manifest_atomic(man_path, manifest)
    return manifest


def export_typed_partitions(
    records: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    *,
    partition_by: Sequence[str] = ("chain", "record_type"),
    manifest_path: Path | str | None = None,
    chain_filter: str | None = None,
    record_type_filter: str | None = None,
) -> ExportManifest:
    """Export records into typed partition files plus a deterministic manifest.

    Partition keys default to ``(chain, record_type)`` so DuckDB can prune
    directories and push predicates on typed columns.  The JSON manifest is
    written last and is explicitly non-authoritative.
    """

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    filtered = _apply_predicates(
        records,
        chain_filter=chain_filter,
        record_type_filter=record_type_filter,
    )

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in filtered:
        key = tuple(str(row.get(part) or "unknown") for part in partition_by)
        groups.setdefault(key, []).append(row)

    partition_results: list[PartitionExportResult] = []
    for key in sorted(groups):
        rows = groups[key]
        # Deterministic path layout: chain=<c>/record_type=<t>/part.parquet
        parts = [
            f"{_safe_name(str(partition_by[i]))}={_safe_name(key[i])}"
            for i in range(len(partition_by))
        ]
        part_dir = root.joinpath(*parts) if parts else root
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / "part.parquet"
        try:
            content = _write_typed_parquet_duckdb(rows, part_path)
        except Exception:
            content = _write_typed_jsonl_fallback(rows, part_path)
        digest = _sha256_bytes(content)
        chain_val = key[partition_by.index("chain")] if "chain" in partition_by else "*"
        rtype_val = (
            key[partition_by.index("record_type")]
            if "record_type" in partition_by
            else "*"
        )
        partition_results.append(
            PartitionExportResult(
                path=str(part_path.relative_to(root)),
                record_type=str(rtype_val),
                chain=str(chain_val),
                row_count=len(rows),
                content_digest=digest,
            )
        )

    # Aggregate content digest over partition digests (sorted for determinism).
    aggregate = hashlib.sha256()
    for part in partition_results:
        aggregate.update(part.content_digest.encode("utf-8"))
        aggregate.update(str(part.row_count).encode("utf-8"))
        aggregate.update(part.path.encode("utf-8"))
    content_digest = "sha256:" + aggregate.hexdigest()

    man_path = (
        Path(manifest_path) if manifest_path else root / "export.manifest.json"
    )
    manifest = ExportManifest(
        path=str(man_path),
        parquet_path=str(root),
        row_count=sum(p.row_count for p in partition_results),
        content_digest=content_digest,
        authoritative=False,
        partitions=tuple(p.to_dict() for p in partition_results),
    )
    _write_manifest_atomic(man_path, manifest)
    return manifest


def _write_manifest_atomic(path: Path, manifest: ExportManifest) -> None:
    """Atomically write a deterministic, non-authoritative JSON manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)

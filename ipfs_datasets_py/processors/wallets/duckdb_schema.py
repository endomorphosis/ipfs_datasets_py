"""Privacy-safe normalized wallet ledger DuckDB schema (DQK-035).

Maps chain-neutral wallet models onto the control-plane ``wallet`` catalog:

* ``chains``, ``ingestion_sources``, ``accounts``, ``assets``
* ``blocks``, ``transactions``, ``transfers``, ``utxos``
* ``token_accounts``, ``contract_events``
* ``cursors``, ``checkpoints``, ``finality_transitions``, ``reorgs``
* ``encrypted_object_refs``

Design invariants (acceptance for DQK-035 / DQK-G700):

* Monetary amounts are exact base-unit **strings** (never FLOAT/DOUBLE/REAL/
  DECIMAL coercion).
* Every catalog row binds ``chain_ref_id``, ``source_id``, and ``finality``.
* Secret-bearing fields and unrestricted raw payloads are absent from
  query-visible tables.  Encrypted/raw object **bytes** stay outside DuckDB;
  only content-addressed references (digest/CID) appear in
  ``encrypted_object_refs``.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from .canonical import format_datetime
from .models import (
    AccountRef,
    AssetRef,
    BlockRecord,
    ChainRef,
    ContractEventRecord,
    ExactAmount,
    Finality,
    LedgerCursor,
    LedgerPosition,
    LedgerRecord,
    Provenance,
    RawPayloadRef,
    TokenAccountRecord,
    TransactionRecord,
    TransferRecord,
    UTXORecord,
    ensure_secret_safe,
)
from .checkpoints import CheckpointRecord
from .finality import OrphanCorrection, ReorgDecision

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_WALLET_SCHEMA_INTERFACE: Final = "DuckDBWalletSchema@1"
DUCKDB_WALLET_SCHEMA_VERSION: Final = "duckdb-wallet-schema/v1"
WALLET_CATALOG_NAME: Final = "wallet"

# Closed catalog table family declared by the control-plane plan (DQK-G700).
WALLET_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "chains",
    "ingestion_sources",
    "accounts",
    "assets",
    "blocks",
    "transactions",
    "transfers",
    "utxos",
    "token_accounts",
    "contract_events",
    "cursors",
    "checkpoints",
    "finality_transitions",
    "reorgs",
    "encrypted_object_refs",
)

# Binding columns required on every query-visible row.
ROW_BINDING_COLUMNS: Final[tuple[str, ...]] = (
    "chain_ref_id",
    "source_id",
    "finality",
)

# SQL type tokens that must never store monetary amounts.
_FLOATING_MONETARY_TYPES: Final[frozenset[str]] = frozenset(
    {
        "FLOAT",
        "DOUBLE",
        "REAL",
        "FLOAT4",
        "FLOAT8",
        "DECIMAL",
        "NUMERIC",
        "HUGEINT",
        "UBIGINT",
        "BIGINT",
        "INTEGER",
        "INT",
        "SMALLINT",
        "TINYINT",
        "UHUGEINT",
        "UINTEGER",
        "USMALLINT",
        "UTINYINT",
    }
)

# Column name fragments that must never appear on the query-visible surface.
_FORBIDDEN_QUERY_VISIBLE_NAME_FRAGMENTS: Final[tuple[str, ...]] = (
    "private_key",
    "signing_key",
    "signing_material",
    "seed_phrase",
    "recovery_phrase",
    "recovery_seed",
    "mnemonic",
    "passphrase",
    "password",
    "passwd",
    "api_key",
    "api_secret",
    "client_secret",
    "access_token",
    "refresh_token",
    "session_token",
    "auth_token",
    "authorization",
    "credential",
    "wallet_seed",
    "raw_payload",
    "payload_bytes",
    "payload_json",
    "payload_body",
    "ciphertext_bytes",
    "secret",
    "continuation_token",
)

# Exact base-unit amount columns (VARCHAR only).
MONETARY_AMOUNT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "amount_base_units",
        "fee_base_units",
    }
)

# Canonical decimal-integer string for base units (matches ExactAmount).
_DECIMAL_INTEGER: Final[re.Pattern[str]] = re.compile(r"^-?(?:0|[1-9][0-9]*)$")

# DDL column parser: "name TYPE [NOT NULL] [PRIMARY KEY] ..."
_DDL_COLUMN_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*"
    r'(?P<name>"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'
    r"\s+"
    r"(?P<type>[A-Za-z][A-Za-z0-9_]*(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)"
    r"(?P<rest>.*)$",
    re.IGNORECASE,
)


class ColumnDataClass(StrEnum):
    """Public-data classification for wallet catalog columns.

    Only :attr:`PUBLIC` and :attr:`CONTENT_REF` may appear on the query-visible
    surface.  :attr:`SECRET` and :attr:`RAW_PAYLOAD` are forbidden in DDL.
    """

    PUBLIC = "public"
    CONTENT_REF = "content_ref"
    SECRET = "secret"
    RAW_PAYLOAD = "raw_payload"


QUERY_VISIBLE_CLASSES: Final[frozenset[ColumnDataClass]] = frozenset(
    {
        ColumnDataClass.PUBLIC,
        ColumnDataClass.CONTENT_REF,
    }
)

FORBIDDEN_QUERY_CLASSES: Final[frozenset[ColumnDataClass]] = frozenset(
    {
        ColumnDataClass.SECRET,
        ColumnDataClass.RAW_PAYLOAD,
    }
)


class WalletSchemaError(ValueError):
    """Raised when a wallet schema projection or invariant fails."""


# ---------------------------------------------------------------------------
# SQL DDL (query-visible wallet catalog)
# ---------------------------------------------------------------------------

WALLET_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS chains (
    chain_ref_id VARCHAR PRIMARY KEY,
    chain_namespace VARCHAR NOT NULL,
    network VARCHAR NOT NULL,
    chain_id VARCHAR NOT NULL,
    genesis_hash VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_sources (
    source_id VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,
    provider_kind VARCHAR NOT NULL,
    request_id VARCHAR NOT NULL,
    scope VARCHAR NOT NULL,
    chain_ref_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    address VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    asset_namespace VARCHAR NOT NULL,
    asset_reference VARCHAR NOT NULL,
    decimals INTEGER NOT NULL,
    kind VARCHAR NOT NULL,
    symbol VARCHAR,
    schema_version VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    block_hash VARCHAR NOT NULL,
    parent_hash VARCHAR,
    sequence BIGINT NOT NULL,
    ledger_hash VARCHAR,
    transaction_index INTEGER,
    event_index INTEGER,
    block_time VARCHAR,
    transaction_count INTEGER,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    transaction_hash VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    fee_base_units VARCHAR,
    fee_decimals INTEGER,
    sequence BIGINT,
    ledger_hash VARCHAR,
    transaction_index INTEGER,
    event_index INTEGER,
    block_time VARCHAR,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS transfers (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    transaction_hash VARCHAR NOT NULL,
    transfer_index INTEGER NOT NULL,
    asset_id VARCHAR NOT NULL,
    amount_base_units VARCHAR NOT NULL,
    amount_decimals INTEGER NOT NULL,
    source_account_id VARCHAR,
    destination_account_id VARCHAR,
    transfer_kind VARCHAR NOT NULL,
    sequence BIGINT,
    ledger_hash VARCHAR,
    transaction_index INTEGER,
    event_index INTEGER,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS utxos (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    transaction_hash VARCHAR NOT NULL,
    output_index INTEGER NOT NULL,
    asset_id VARCHAR NOT NULL,
    amount_base_units VARCHAR NOT NULL,
    amount_decimals INTEGER NOT NULL,
    owner_account_id VARCHAR,
    spent_by_transaction_hash VARCHAR,
    sequence BIGINT,
    ledger_hash VARCHAR,
    transaction_index INTEGER,
    event_index INTEGER,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS token_accounts (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    token_account_id VARCHAR NOT NULL,
    owner_account_id VARCHAR,
    asset_id VARCHAR NOT NULL,
    amount_base_units VARCHAR NOT NULL,
    amount_decimals INTEGER NOT NULL,
    sequence BIGINT,
    ledger_hash VARCHAR,
    transaction_index INTEGER,
    event_index INTEGER,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS contract_events (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    transaction_hash VARCHAR NOT NULL,
    event_index INTEGER NOT NULL,
    contract_account_id VARCHAR NOT NULL,
    event_signature VARCHAR,
    topics_json VARCHAR NOT NULL,
    data_digest VARCHAR,
    data_cid VARCHAR,
    data_media_type VARCHAR,
    data_byte_length BIGINT,
    sequence BIGINT,
    ledger_hash VARCHAR,
    transaction_index INTEGER,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS cursors (
    cursor_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    scope VARCHAR NOT NULL,
    normalized_schema_major INTEGER NOT NULL,
    normalizer_version VARCHAR NOT NULL,
    position_sequence BIGINT,
    position_hash VARCHAR,
    position_transaction_index INTEGER,
    position_event_index INTEGER,
    revision VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    scope VARCHAR NOT NULL,
    normalized_schema_major INTEGER NOT NULL,
    normalizer_version VARCHAR NOT NULL,
    anchor_sequence BIGINT NOT NULL,
    anchor_hash VARCHAR NOT NULL,
    revision VARCHAR NOT NULL,
    safety_depth INTEGER NOT NULL,
    sink_commit_id VARCHAR,
    schema_version VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS finality_transitions (
    transition_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    prior_finality VARCHAR NOT NULL,
    orphaned_sequence BIGINT,
    orphaned_hash VARCHAR,
    ancestor_sequence BIGINT,
    ancestor_hash VARCHAR,
    tombstone BOOLEAN NOT NULL,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS reorgs (
    reorg_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    checkpoint_sequence BIGINT NOT NULL,
    checkpoint_hash VARCHAR NOT NULL,
    observed_sequence BIGINT NOT NULL,
    observed_hash VARCHAR NOT NULL,
    common_ancestor_sequence BIGINT,
    common_ancestor_hash VARCHAR,
    rewind_sequence BIGINT,
    review_required BOOLEAN NOT NULL,
    reason VARCHAR NOT NULL,
    orphaned_anchors_json VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS encrypted_object_refs (
    ref_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    related_record_id VARCHAR,
    digest VARCHAR,
    cid VARCHAR,
    media_type VARCHAR NOT NULL,
    byte_length BIGINT,
    observed_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);
""".strip()


# ---------------------------------------------------------------------------
# Column classification (public-data only on the query surface)
# ---------------------------------------------------------------------------


def _classify_public(*names: str) -> dict[str, ColumnDataClass]:
    return {name: ColumnDataClass.PUBLIC for name in names}


def _classify_ref(*names: str) -> dict[str, ColumnDataClass]:
    return {name: ColumnDataClass.CONTENT_REF for name in names}


WALLET_COLUMN_CLASSIFICATIONS: Final[Mapping[str, Mapping[str, ColumnDataClass]]] = (
    MappingProxyType(
        {
            "chains": MappingProxyType(
                {
                    **_classify_public(
                        "chain_ref_id",
                        "chain_namespace",
                        "network",
                        "chain_id",
                        "genesis_hash",
                        "schema_version",
                        "source_id",
                        "finality",
                        "observed_at",
                    ),
                }
            ),
            "ingestion_sources": MappingProxyType(
                {
                    **_classify_public(
                        "source_id",
                        "provider",
                        "provider_kind",
                        "request_id",
                        "scope",
                        "chain_ref_id",
                        "finality",
                        "observed_at",
                    ),
                }
            ),
            "accounts": MappingProxyType(
                {
                    **_classify_public(
                        "account_id",
                        "chain_ref_id",
                        "address",
                        "kind",
                        "schema_version",
                        "source_id",
                        "finality",
                        "observed_at",
                    ),
                }
            ),
            "assets": MappingProxyType(
                {
                    **_classify_public(
                        "asset_id",
                        "chain_ref_id",
                        "asset_namespace",
                        "asset_reference",
                        "decimals",
                        "kind",
                        "symbol",
                        "schema_version",
                        "source_id",
                        "finality",
                        "observed_at",
                    ),
                }
            ),
            "blocks": MappingProxyType(
                {
                    **_classify_public(
                        "record_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "block_hash",
                        "parent_hash",
                        "sequence",
                        "ledger_hash",
                        "transaction_index",
                        "event_index",
                        "block_time",
                        "transaction_count",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "transactions": MappingProxyType(
                {
                    **_classify_public(
                        "record_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "transaction_hash",
                        "status",
                        "fee_base_units",
                        "fee_decimals",
                        "sequence",
                        "ledger_hash",
                        "transaction_index",
                        "event_index",
                        "block_time",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "transfers": MappingProxyType(
                {
                    **_classify_public(
                        "record_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "transaction_hash",
                        "transfer_index",
                        "asset_id",
                        "amount_base_units",
                        "amount_decimals",
                        "source_account_id",
                        "destination_account_id",
                        "transfer_kind",
                        "sequence",
                        "ledger_hash",
                        "transaction_index",
                        "event_index",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "utxos": MappingProxyType(
                {
                    **_classify_public(
                        "record_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "transaction_hash",
                        "output_index",
                        "asset_id",
                        "amount_base_units",
                        "amount_decimals",
                        "owner_account_id",
                        "spent_by_transaction_hash",
                        "sequence",
                        "ledger_hash",
                        "transaction_index",
                        "event_index",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "token_accounts": MappingProxyType(
                {
                    **_classify_public(
                        "record_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "token_account_id",
                        "owner_account_id",
                        "asset_id",
                        "amount_base_units",
                        "amount_decimals",
                        "sequence",
                        "ledger_hash",
                        "transaction_index",
                        "event_index",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "contract_events": MappingProxyType(
                {
                    **_classify_public(
                        "record_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "transaction_hash",
                        "event_index",
                        "contract_account_id",
                        "event_signature",
                        "topics_json",
                        "sequence",
                        "ledger_hash",
                        "transaction_index",
                        "observed_at",
                        "schema_version",
                    ),
                    **_classify_ref(
                        "data_digest",
                        "data_cid",
                        "data_media_type",
                        "data_byte_length",
                    ),
                }
            ),
            "cursors": MappingProxyType(
                {
                    **_classify_public(
                        "cursor_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "provider",
                        "scope",
                        "normalized_schema_major",
                        "normalizer_version",
                        "position_sequence",
                        "position_hash",
                        "position_transaction_index",
                        "position_event_index",
                        "revision",
                        "schema_version",
                        "observed_at",
                    ),
                }
            ),
            "checkpoints": MappingProxyType(
                {
                    **_classify_public(
                        "checkpoint_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "provider",
                        "scope",
                        "normalized_schema_major",
                        "normalizer_version",
                        "anchor_sequence",
                        "anchor_hash",
                        "revision",
                        "safety_depth",
                        "sink_commit_id",
                        "schema_version",
                        "observed_at",
                    ),
                }
            ),
            "finality_transitions": MappingProxyType(
                {
                    **_classify_public(
                        "transition_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "record_id",
                        "prior_finality",
                        "orphaned_sequence",
                        "orphaned_hash",
                        "ancestor_sequence",
                        "ancestor_hash",
                        "tombstone",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "reorgs": MappingProxyType(
                {
                    **_classify_public(
                        "reorg_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "kind",
                        "checkpoint_sequence",
                        "checkpoint_hash",
                        "observed_sequence",
                        "observed_hash",
                        "common_ancestor_sequence",
                        "common_ancestor_hash",
                        "rewind_sequence",
                        "review_required",
                        "reason",
                        "orphaned_anchors_json",
                        "observed_at",
                        "schema_version",
                    ),
                }
            ),
            "encrypted_object_refs": MappingProxyType(
                {
                    **_classify_public(
                        "ref_id",
                        "chain_ref_id",
                        "source_id",
                        "finality",
                        "related_record_id",
                        "observed_at",
                        "schema_version",
                    ),
                    **_classify_ref(
                        "digest",
                        "cid",
                        "media_type",
                        "byte_length",
                    ),
                }
            ),
        }
    )
)


# ---------------------------------------------------------------------------
# DDL parsing / schema invariants
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column declared in wallet catalog DDL."""

    name: str
    sql_type: str
    not_null: bool
    primary_key: bool

    @property
    def base_type(self) -> str:
        return self.sql_type.split("(", 1)[0].strip().upper()


def _strip_sql_comments(ddl: str) -> str:
    lines: list[str] = []
    for line in ddl.splitlines():
        stripped = line.split("--", 1)[0]
        lines.append(stripped)
    return "\n".join(lines)


def parse_wallet_catalog_ddl(
    ddl: str = WALLET_CATALOG_DDL,
) -> dict[str, tuple[ColumnSpec, ...]]:
    """Parse ``CREATE TABLE`` statements into ordered column specs."""

    text = _strip_sql_comments(ddl)
    tables: dict[str, tuple[ColumnSpec, ...]] = {}
    for match in re.finditer(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+"
        r'(?P<table>"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'
        r"\s*\((?P<body>.*?)\);",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        table = match.group("table").strip('"').casefold()
        body = match.group("body")
        columns: list[ColumnSpec] = []
        for raw_line in body.split(","):
            line = " ".join(raw_line.strip().split())
            if not line:
                continue
            upper = line.upper()
            # Match whole constraint keywords only — do not treat column names
            # such as ``checkpoint_id`` as ``CHECK`` constraints.
            first_token = upper.split(None, 1)[0]
            if first_token in {"PRIMARY", "UNIQUE", "CONSTRAINT", "FOREIGN", "CHECK", "INDEX"}:
                continue
            col_match = _DDL_COLUMN_RE.match(line)
            if col_match is None:
                continue
            name = col_match.group("name").strip('"')
            sql_type = re.sub(r"\s+", "", col_match.group("type")).upper()
            # Normalize DECIMAL(p,s) → DECIMAL for type checks.
            base = sql_type.split("(", 1)[0]
            rest = col_match.group("rest").upper()
            columns.append(
                ColumnSpec(
                    name=name,
                    sql_type=base if base in _FLOATING_MONETARY_TYPES else sql_type,
                    not_null="NOT NULL" in rest or "PRIMARY KEY" in rest,
                    primary_key="PRIMARY KEY" in rest,
                )
            )
        if not columns:
            raise WalletSchemaError(f"table {table!r} has no parseable columns")
        tables[table] = tuple(columns)
    return tables


def monetary_columns_for_table(
    table: str,
    columns: Sequence[ColumnSpec] | None = None,
) -> tuple[ColumnSpec, ...]:
    """Return monetary amount columns declared on *table*."""

    if columns is None:
        parsed = parse_wallet_catalog_ddl()
        if table not in parsed:
            raise WalletSchemaError(f"unknown wallet catalog table: {table}")
        columns = parsed[table]
    return tuple(col for col in columns if col.name in MONETARY_AMOUNT_COLUMNS)


def assert_no_float_monetary_types(
    tables: Mapping[str, Sequence[ColumnSpec]] | None = None,
) -> None:
    """Fail closed if any monetary amount uses a coercive numeric SQL type."""

    parsed = tables if tables is not None else parse_wallet_catalog_ddl()
    for table, columns in parsed.items():
        for col in columns:
            if col.name not in MONETARY_AMOUNT_COLUMNS:
                continue
            if col.base_type != "VARCHAR":
                raise WalletSchemaError(
                    f"monetary column {table}.{col.name} must be VARCHAR "
                    f"(exact amount string), got {col.sql_type}"
                )
            if col.base_type in _FLOATING_MONETARY_TYPES:
                raise WalletSchemaError(
                    f"monetary column {table}.{col.name} forbids "
                    f"float/numeric coercion type {col.sql_type}"
                )


def assert_row_bindings(
    tables: Mapping[str, Sequence[ColumnSpec]] | None = None,
) -> None:
    """Fail closed if any catalog table omits chain/source/finality bindings."""

    parsed = tables if tables is not None else parse_wallet_catalog_ddl()
    for table, columns in parsed.items():
        names = {col.name for col in columns}
        missing = [name for name in ROW_BINDING_COLUMNS if name not in names]
        if missing:
            raise WalletSchemaError(
                f"table {table!r} missing required bindings: {missing}"
            )
        for name in ROW_BINDING_COLUMNS:
            col = next(c for c in columns if c.name == name)
            if not col.not_null and not col.primary_key:
                raise WalletSchemaError(
                    f"table {table!r} binding column {name!r} must be NOT NULL"
                )


def assert_no_secret_or_raw_payload_columns(
    tables: Mapping[str, Sequence[ColumnSpec]] | None = None,
) -> None:
    """Fail closed if secret-bearing or raw-payload columns appear in DDL."""

    parsed = tables if tables is not None else parse_wallet_catalog_ddl()
    for table, columns in parsed.items():
        for col in columns:
            lowered = col.name.casefold()
            for fragment in _FORBIDDEN_QUERY_VISIBLE_NAME_FRAGMENTS:
                if fragment in lowered:
                    raise WalletSchemaError(
                        f"query-visible table {table!r} forbids column "
                        f"{col.name!r} (matches secret/raw fragment {fragment!r})"
                    )


def assert_public_data_classification(
    classifications: Mapping[str, Mapping[str, ColumnDataClass]] | None = None,
    tables: Mapping[str, Sequence[ColumnSpec]] | None = None,
) -> None:
    """Ensure every DDL column is classified as public-data or content-ref."""

    class_map = (
        classifications
        if classifications is not None
        else WALLET_COLUMN_CLASSIFICATIONS
    )
    parsed = tables if tables is not None else parse_wallet_catalog_ddl()
    for table, columns in parsed.items():
        if table not in class_map:
            raise WalletSchemaError(f"missing classification map for table {table!r}")
        declared = class_map[table]
        for col in columns:
            if col.name not in declared:
                raise WalletSchemaError(
                    f"column {table}.{col.name} lacks public-data classification"
                )
            classification = declared[col.name]
            if classification in FORBIDDEN_QUERY_CLASSES:
                raise WalletSchemaError(
                    f"column {table}.{col.name} classified as "
                    f"{classification.value}; forbidden on query-visible surface"
                )
            if classification not in QUERY_VISIBLE_CLASSES:
                raise WalletSchemaError(
                    f"column {table}.{col.name} has unknown classification "
                    f"{classification!r}"
                )
        extra = set(declared) - {col.name for col in columns}
        if extra:
            raise WalletSchemaError(
                f"table {table!r} classifies unknown columns: {sorted(extra)}"
            )


def assert_wallet_schema_invariants(
    ddl: str = WALLET_CATALOG_DDL,
    *,
    classifications: Mapping[str, Mapping[str, ColumnDataClass]] | None = None,
) -> dict[str, tuple[ColumnSpec, ...]]:
    """Run the full closed set of DQK-035 schema acceptance checks."""

    tables = parse_wallet_catalog_ddl(ddl)
    expected = set(WALLET_CATALOG_TABLES)
    actual = set(tables)
    if actual != expected:
        raise WalletSchemaError(
            f"wallet catalog tables mismatch: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )
    assert_no_float_monetary_types(tables)
    assert_row_bindings(tables)
    assert_no_secret_or_raw_payload_columns(tables)
    assert_public_data_classification(classifications, tables)
    return tables


def wallet_schema_descriptor() -> dict[str, Any]:
    """Return a stable, JSON-serializable schema descriptor."""

    tables = assert_wallet_schema_invariants()
    return {
        "interface": DUCKDB_WALLET_SCHEMA_INTERFACE,
        "schema_version": DUCKDB_WALLET_SCHEMA_VERSION,
        "catalog": WALLET_CATALOG_NAME,
        "tables": list(WALLET_CATALOG_TABLES),
        "row_bindings": list(ROW_BINDING_COLUMNS),
        "monetary_amount_columns": sorted(MONETARY_AMOUNT_COLUMNS),
        "monetary_sql_type": "VARCHAR",
        "query_visible_classes": sorted(c.value for c in QUERY_VISIBLE_CLASSES),
        "forbidden_query_classes": sorted(c.value for c in FORBIDDEN_QUERY_CLASSES),
        "columns": {
            table: [
                {
                    "name": col.name,
                    "sql_type": col.sql_type,
                    "not_null": col.not_null,
                    "primary_key": col.primary_key,
                    "classification": WALLET_COLUMN_CLASSIFICATIONS[table][
                        col.name
                    ].value,
                    "monetary": col.name in MONETARY_AMOUNT_COLUMNS,
                }
                for col in columns
            ]
            for table, columns in tables.items()
        },
    }


# ---------------------------------------------------------------------------
# Exact amount + binding helpers
# ---------------------------------------------------------------------------


def exact_amount_strings(amount: ExactAmount | Mapping[str, Any]) -> tuple[str, int]:
    """Project an :class:`ExactAmount` to ``(base_units_str, decimals)``.

    Rejects floats and non-canonical numeric forms so DuckDB rows never coerce
    monetary values through floating point.
    """

    if isinstance(amount, ExactAmount):
        base_units = amount.base_units
        decimals = amount.decimals
    elif isinstance(amount, Mapping):
        if "base_units" not in amount or "decimals" not in amount:
            raise WalletSchemaError("amount mapping requires base_units and decimals")
        base_units = amount["base_units"]
        decimals = amount["decimals"]
    else:
        raise WalletSchemaError("amount must be ExactAmount or mapping")

    if isinstance(base_units, float) or isinstance(decimals, float):
        raise WalletSchemaError("monetary amounts must not use float coercion")
    if isinstance(base_units, bool) or isinstance(decimals, bool):
        raise WalletSchemaError("monetary amounts must not use bool values")
    if isinstance(base_units, int):
        base_units = str(base_units)
    if not isinstance(base_units, str) or not _DECIMAL_INTEGER.fullmatch(base_units):
        raise WalletSchemaError(
            "base_units must be a canonical decimal integer string"
        )
    if not isinstance(decimals, int) or decimals < 0 or decimals > 255:
        raise WalletSchemaError("decimals must be an integer in 0..255")
    return base_units, decimals


def source_id_for_provenance(provenance: Provenance, chain: ChainRef) -> str:
    """Stable source identity for one provenance observation on *chain*."""

    from .canonical import deterministic_id

    return deterministic_id(
        "ingestion-source",
        {
            "chain": chain.identity_dict(),
            "provider": provenance.provider,
            "provider_kind": provenance.provider_kind,
            "request_id": provenance.request_id,
            "scope": provenance.scope,
        },
    )


def _require_finality(value: Finality | str) -> str:
    if isinstance(value, Finality):
        return value.value
    if isinstance(value, str) and value.strip():
        # Validate against the closed enum.
        return Finality(value).value
    raise WalletSchemaError("finality must be a Finality value")


def _position_fields(position: LedgerPosition) -> dict[str, Any]:
    return {
        "sequence": position.sequence,
        "ledger_hash": position.hash,
        "transaction_index": position.transaction_index,
        "event_index": position.event_index,
    }


def _binding_fields(
    *,
    chain: ChainRef,
    provenance: Provenance,
    finality: Finality | str,
) -> dict[str, str]:
    return {
        "chain_ref_id": chain.chain_ref_id,
        "source_id": source_id_for_provenance(provenance, chain),
        "finality": _require_finality(finality),
    }


def _assert_row_bindings_present(row: Mapping[str, Any], *, table: str) -> None:
    for name in ROW_BINDING_COLUMNS:
        value = row.get(name)
        if not isinstance(value, str) or not value.strip():
            raise WalletSchemaError(
                f"{table} row missing required binding {name!r}"
            )


def _assert_row_public(row: Mapping[str, Any], *, table: str) -> None:
    ensure_secret_safe(dict(row))
    for key in row:
        lowered = key.casefold()
        for fragment in _FORBIDDEN_QUERY_VISIBLE_NAME_FRAGMENTS:
            if fragment in lowered:
                raise WalletSchemaError(
                    f"{table} row forbids key {key!r} on query-visible surface"
                )


def project_ingestion_source_row(
    provenance: Provenance,
    chain: ChainRef,
    *,
    finality: Finality | str = Finality.OBSERVED,
) -> dict[str, Any]:
    """Project provenance into an ``ingestion_sources`` row."""

    row = {
        "source_id": source_id_for_provenance(provenance, chain),
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "request_id": provenance.request_id,
        "scope": provenance.scope,
        "chain_ref_id": chain.chain_ref_id,
        "finality": _require_finality(finality),
        "observed_at": format_datetime(provenance.observed_at),
    }
    _assert_row_bindings_present(row, table="ingestion_sources")
    _assert_row_public(row, table="ingestion_sources")
    return row


def project_chain_row(
    chain: ChainRef,
    provenance: Provenance,
    *,
    finality: Finality | str = Finality.FINALIZED,
) -> dict[str, Any]:
    """Project a :class:`ChainRef` into a ``chains`` row."""

    row = {
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
        "schema_version": chain.schema_version,
        "source_id": source_id_for_provenance(provenance, chain),
        "finality": _require_finality(finality),
        "observed_at": format_datetime(provenance.observed_at),
    }
    _assert_row_bindings_present(row, table="chains")
    _assert_row_public(row, table="chains")
    return row


def project_account_row(
    account: AccountRef,
    provenance: Provenance,
    *,
    finality: Finality | str = Finality.OBSERVED,
) -> dict[str, Any]:
    """Project an :class:`AccountRef` into an ``accounts`` row."""

    row = {
        "account_id": account.account_id,
        "chain_ref_id": account.chain.chain_ref_id,
        "address": account.address,
        "kind": account.kind.value,
        "schema_version": account.schema_version,
        "source_id": source_id_for_provenance(provenance, account.chain),
        "finality": _require_finality(finality),
        "observed_at": format_datetime(provenance.observed_at),
    }
    _assert_row_bindings_present(row, table="accounts")
    _assert_row_public(row, table="accounts")
    return row


def project_asset_row(
    asset: AssetRef,
    provenance: Provenance,
    *,
    finality: Finality | str = Finality.OBSERVED,
) -> dict[str, Any]:
    """Project an :class:`AssetRef` into an ``assets`` row."""

    row = {
        "asset_id": asset.asset_id,
        "chain_ref_id": asset.chain.chain_ref_id,
        "asset_namespace": asset.asset_namespace,
        "asset_reference": asset.asset_reference,
        "decimals": asset.decimals,
        "kind": asset.kind.value,
        "symbol": asset.symbol,
        "schema_version": asset.schema_version,
        "source_id": source_id_for_provenance(provenance, asset.chain),
        "finality": _require_finality(finality),
        "observed_at": format_datetime(provenance.observed_at),
    }
    _assert_row_bindings_present(row, table="assets")
    _assert_row_public(row, table="assets")
    return row


def _ledger_envelope(record: LedgerRecord) -> dict[str, Any]:
    binding = _binding_fields(
        chain=record.chain,
        provenance=record.provenance,
        finality=record.finality,
    )
    position = _position_fields(record.ledger_position)
    return {
        "record_id": record.record_id,
        **binding,
        **position,
        "observed_at": format_datetime(record.provenance.observed_at),
        "schema_version": record.schema_version,
    }


def project_block_row(record: BlockRecord) -> dict[str, Any]:
    """Project a :class:`BlockRecord` into a ``blocks`` row."""

    row = {
        **_ledger_envelope(record),
        "block_hash": record.block_hash,
        "parent_hash": record.parent_hash,
        "block_time": (
            None
            if record.block_time is None
            else format_datetime(record.block_time)
        ),
        "transaction_count": record.transaction_count,
    }
    _assert_row_bindings_present(row, table="blocks")
    _assert_row_public(row, table="blocks")
    return row


def project_transaction_row(record: TransactionRecord) -> dict[str, Any]:
    """Project a :class:`TransactionRecord` into a ``transactions`` row."""

    fee_base_units: str | None = None
    fee_decimals: int | None = None
    if record.fee is not None:
        fee_base_units, fee_decimals = exact_amount_strings(record.fee)
    row = {
        **_ledger_envelope(record),
        "transaction_hash": record.transaction_hash,
        "status": record.status.value,
        "fee_base_units": fee_base_units,
        "fee_decimals": fee_decimals,
        "block_time": (
            None
            if record.block_time is None
            else format_datetime(record.block_time)
        ),
    }
    _assert_row_bindings_present(row, table="transactions")
    _assert_row_public(row, table="transactions")
    return row


def project_transfer_row(record: TransferRecord) -> dict[str, Any]:
    """Project a :class:`TransferRecord` into a ``transfers`` row."""

    amount_base_units, amount_decimals = exact_amount_strings(record.amount)
    row = {
        **_ledger_envelope(record),
        "transaction_hash": record.transaction_hash,
        "transfer_index": record.transfer_index,
        "asset_id": record.asset.asset_id,
        "amount_base_units": amount_base_units,
        "amount_decimals": amount_decimals,
        "source_account_id": (
            None
            if record.source_account is None
            else record.source_account.account_id
        ),
        "destination_account_id": (
            None
            if record.destination_account is None
            else record.destination_account.account_id
        ),
        "transfer_kind": record.transfer_kind.value,
    }
    if not isinstance(row["amount_base_units"], str):
        raise WalletSchemaError("transfer amount_base_units must remain a string")
    _assert_row_bindings_present(row, table="transfers")
    _assert_row_public(row, table="transfers")
    return row


def project_utxo_row(record: UTXORecord) -> dict[str, Any]:
    """Project a :class:`UTXORecord` into a ``utxos`` row."""

    amount_base_units, amount_decimals = exact_amount_strings(record.amount)
    row = {
        **_ledger_envelope(record),
        "transaction_hash": record.transaction_hash,
        "output_index": record.output_index,
        "asset_id": record.asset.asset_id,
        "amount_base_units": amount_base_units,
        "amount_decimals": amount_decimals,
        "owner_account_id": (
            None if record.owner is None else record.owner.account_id
        ),
        "spent_by_transaction_hash": record.spent_by_transaction_hash,
    }
    _assert_row_bindings_present(row, table="utxos")
    _assert_row_public(row, table="utxos")
    return row


def project_token_account_row(record: TokenAccountRecord) -> dict[str, Any]:
    """Project a :class:`TokenAccountRecord` into a ``token_accounts`` row."""

    amount_base_units, amount_decimals = exact_amount_strings(record.amount)
    row = {
        **_ledger_envelope(record),
        "token_account_id": record.token_account.account_id,
        "owner_account_id": (
            None if record.owner is None else record.owner.account_id
        ),
        "asset_id": record.asset.asset_id,
        "amount_base_units": amount_base_units,
        "amount_decimals": amount_decimals,
    }
    _assert_row_bindings_present(row, table="token_accounts")
    _assert_row_public(row, table="token_accounts")
    return row


def project_contract_event_row(record: ContractEventRecord) -> dict[str, Any]:
    """Project a :class:`ContractEventRecord` into a ``contract_events`` row.

    Raw event data never enters the row: only content references are retained.
    """

    import json

    data_digest = data_cid = data_media_type = None
    data_byte_length = None
    if record.data_ref is not None:
        data_digest = record.data_ref.digest
        data_cid = record.data_ref.cid
        data_media_type = record.data_ref.media_type
        data_byte_length = record.data_ref.byte_length
    row = {
        **_ledger_envelope(record),
        "transaction_hash": record.transaction_hash,
        "event_index": record.event_index,
        "contract_account_id": record.contract.account_id,
        "event_signature": record.event_signature,
        "topics_json": json.dumps(list(record.topics), separators=(",", ":")),
        "data_digest": data_digest,
        "data_cid": data_cid,
        "data_media_type": data_media_type,
        "data_byte_length": data_byte_length,
    }
    _assert_row_bindings_present(row, table="contract_events")
    _assert_row_public(row, table="contract_events")
    return row


def _synthetic_provenance(
    *,
    provider: str,
    provider_kind: str,
    request_id: str,
    scope: str,
    observed_at: Any | None = None,
) -> Provenance:
    """Build provenance used only for stable ``source_id`` derivation."""

    from datetime import datetime, timezone

    when = observed_at
    if when is None:
        when = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elif isinstance(when, str):
        # Source identity ignores observed_at; keep a fixed aware instant.
        when = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return Provenance(
        provider=provider,
        provider_kind=provider_kind,
        request_id=request_id,
        scope=scope,
        observed_at=when,
    )


def project_cursor_row(
    cursor: LedgerCursor,
    *,
    finality: Finality | str = Finality.OBSERVED,
    observed_at: str,
) -> dict[str, Any]:
    """Project a :class:`LedgerCursor` into a ``cursors`` row.

    Provider ``continuation_token`` values are intentionally omitted from the
    query-visible surface.  *observed_at* must be a pre-formatted UTC string.
    """

    provenance = _synthetic_provenance(
        provider=cursor.provider,
        provider_kind="cursor",
        request_id=cursor.revision,
        scope=cursor.scope,
    )
    row = {
        "cursor_id": cursor.cursor_id,
        "chain_ref_id": cursor.chain.chain_ref_id,
        "source_id": source_id_for_provenance(provenance, cursor.chain),
        "finality": _require_finality(finality),
        "provider": cursor.provider,
        "scope": cursor.scope,
        "normalized_schema_major": cursor.normalized_schema_major,
        "normalizer_version": cursor.normalizer_version,
        "position_sequence": cursor.position.sequence,
        "position_hash": cursor.position.hash,
        "position_transaction_index": cursor.position.transaction_index,
        "position_event_index": cursor.position.event_index,
        "revision": cursor.revision,
        "schema_version": cursor.schema_version,
        "observed_at": observed_at,
    }
    if "continuation_token" in row:
        raise WalletSchemaError("cursors must not expose continuation_token")
    _assert_row_bindings_present(row, table="cursors")
    _assert_row_public(row, table="cursors")
    return row


def project_checkpoint_row(
    checkpoint: CheckpointRecord,
    *,
    finality: Finality | str = Finality.SAFE,
    observed_at: str,
) -> dict[str, Any]:
    """Project a :class:`CheckpointRecord` into a ``checkpoints`` row.

    Continuation tokens and free-form metadata are omitted (non-query-visible).
    *observed_at* must be a pre-formatted UTC string.
    """

    identity = checkpoint.identity
    provenance = _synthetic_provenance(
        provider=identity.provider,
        provider_kind="checkpoint",
        request_id=checkpoint.revision,
        scope=identity.scope,
    )
    row = {
        "checkpoint_id": checkpoint.checkpoint_id,
        "chain_ref_id": identity.chain.chain_ref_id,
        "source_id": source_id_for_provenance(provenance, identity.chain),
        "finality": _require_finality(finality),
        "provider": identity.provider,
        "scope": identity.scope,
        "normalized_schema_major": identity.normalized_schema_major,
        "normalizer_version": identity.normalizer_version,
        "anchor_sequence": checkpoint.anchor.sequence,
        "anchor_hash": checkpoint.anchor.block_hash,
        "revision": checkpoint.revision,
        "safety_depth": checkpoint.safety_depth,
        "sink_commit_id": checkpoint.sink_commit_id,
        "schema_version": checkpoint.schema_version,
        "observed_at": observed_at,
    }
    _assert_row_bindings_present(row, table="checkpoints")
    _assert_row_public(row, table="checkpoints")
    return row


def project_finality_transition_row(
    correction: OrphanCorrection,
    *,
    chain: ChainRef,
    provenance: Provenance,
    transition_id: str | None = None,
) -> dict[str, Any]:
    """Project an :class:`OrphanCorrection` into ``finality_transitions``."""

    from .canonical import deterministic_id

    tid = transition_id or deterministic_id(
        "finality-transition",
        {
            "record_id": correction.record_id,
            "prior_finality": correction.prior_finality.value,
            "finality": correction.new_finality.value,
            "orphaned": correction.orphaned_anchor.to_dict(),
        },
    )
    ancestor = correction.ancestor_anchor
    row = {
        "transition_id": tid,
        "chain_ref_id": chain.chain_ref_id,
        "source_id": source_id_for_provenance(provenance, chain),
        "finality": correction.new_finality.value,
        "record_id": correction.record_id,
        "prior_finality": correction.prior_finality.value,
        "orphaned_sequence": correction.orphaned_anchor.sequence,
        "orphaned_hash": correction.orphaned_anchor.block_hash,
        "ancestor_sequence": None if ancestor is None else ancestor.sequence,
        "ancestor_hash": None if ancestor is None else ancestor.block_hash,
        "tombstone": correction.tombstone,
        "observed_at": format_datetime(provenance.observed_at),
        "schema_version": DUCKDB_WALLET_SCHEMA_VERSION,
    }
    _assert_row_bindings_present(row, table="finality_transitions")
    _assert_row_public(row, table="finality_transitions")
    return row


def project_reorg_row(
    decision: ReorgDecision,
    *,
    chain: ChainRef,
    provenance: Provenance,
    reorg_id: str | None = None,
    finality: Finality | str = Finality.ORPHANED,
) -> dict[str, Any]:
    """Project a :class:`ReorgDecision` into a ``reorgs`` row."""

    import json

    from .canonical import deterministic_id

    rid = reorg_id or deterministic_id(
        "reorg",
        {
            "chain": chain.identity_dict(),
            "kind": decision.kind.value,
            "checkpoint": decision.checkpoint_anchor.to_dict(),
            "observed": decision.observed_anchor.to_dict(),
        },
    )
    common = decision.common_ancestor
    row = {
        "reorg_id": rid,
        "chain_ref_id": chain.chain_ref_id,
        "source_id": source_id_for_provenance(provenance, chain),
        "finality": _require_finality(finality),
        "kind": decision.kind.value,
        "checkpoint_sequence": decision.checkpoint_anchor.sequence,
        "checkpoint_hash": decision.checkpoint_anchor.block_hash,
        "observed_sequence": decision.observed_anchor.sequence,
        "observed_hash": decision.observed_anchor.block_hash,
        "common_ancestor_sequence": None if common is None else common.sequence,
        "common_ancestor_hash": None if common is None else common.block_hash,
        "rewind_sequence": decision.rewind_sequence,
        "review_required": decision.review_required,
        "reason": decision.reason,
        "orphaned_anchors_json": json.dumps(
            [a.to_dict() for a in decision.orphaned_anchors],
            separators=(",", ":"),
        ),
        "observed_at": format_datetime(provenance.observed_at),
        "schema_version": DUCKDB_WALLET_SCHEMA_VERSION,
    }
    _assert_row_bindings_present(row, table="reorgs")
    _assert_row_public(row, table="reorgs")
    return row


def project_encrypted_object_ref_row(
    ref: RawPayloadRef,
    *,
    chain: ChainRef,
    provenance: Provenance,
    finality: Finality | str,
    related_record_id: str | None = None,
    ref_id: str | None = None,
) -> dict[str, Any]:
    """Project a content reference into ``encrypted_object_refs``.

    Only digest/CID metadata is stored; raw payload bytes never appear.
    """

    from .canonical import deterministic_id

    if ref.digest is None and ref.cid is None:
        raise WalletSchemaError("encrypted object ref requires digest or cid")
    rid = ref_id or deterministic_id(
        "encrypted-object-ref",
        {
            "chain": chain.identity_dict(),
            "digest": ref.digest,
            "cid": ref.cid,
            "related_record_id": related_record_id,
        },
    )
    row = {
        "ref_id": rid,
        "chain_ref_id": chain.chain_ref_id,
        "source_id": source_id_for_provenance(provenance, chain),
        "finality": _require_finality(finality),
        "related_record_id": related_record_id,
        "digest": ref.digest,
        "cid": ref.cid,
        "media_type": ref.media_type,
        "byte_length": ref.byte_length,
        "observed_at": format_datetime(provenance.observed_at),
        "schema_version": DUCKDB_WALLET_SCHEMA_VERSION,
    }
    for forbidden in ("raw_payload", "payload_bytes", "payload_json", "body"):
        if forbidden in row:
            raise WalletSchemaError(
                f"encrypted_object_refs must not include {forbidden!r}"
            )
    _assert_row_bindings_present(row, table="encrypted_object_refs")
    _assert_row_public(row, table="encrypted_object_refs")
    return row


def project_ledger_record_rows(
    record: LedgerRecord,
) -> dict[str, list[dict[str, Any]]]:
    """Project one ledger record into typed table rows (public data only).

    Returns a mapping of table name → list of row dicts, including dimension
    rows (chain, source, accounts, assets) and the primary fact row.  Raw
    payloads from provenance become ``encrypted_object_refs`` only.
    """

    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in WALLET_CATALOG_TABLES}
    provenance = record.provenance
    chain = record.chain

    rows["chains"].append(project_chain_row(chain, provenance, finality=record.finality))
    rows["ingestion_sources"].append(
        project_ingestion_source_row(provenance, chain, finality=record.finality)
    )

    if provenance.raw_payload is not None:
        rows["encrypted_object_refs"].append(
            project_encrypted_object_ref_row(
                provenance.raw_payload,
                chain=chain,
                provenance=provenance,
                finality=record.finality,
                related_record_id=record.record_id,
            )
        )

    if isinstance(record, BlockRecord):
        rows["blocks"].append(project_block_row(record))
    elif isinstance(record, TransactionRecord):
        rows["transactions"].append(project_transaction_row(record))
        for participant in record.participants:
            rows["accounts"].append(
                project_account_row(
                    participant, provenance, finality=record.finality
                )
            )
    elif isinstance(record, TransferRecord):
        rows["transfers"].append(project_transfer_row(record))
        rows["assets"].append(
            project_asset_row(record.asset, provenance, finality=record.finality)
        )
        for account in (record.source_account, record.destination_account):
            if account is not None:
                rows["accounts"].append(
                    project_account_row(
                        account, provenance, finality=record.finality
                    )
                )
    elif isinstance(record, UTXORecord):
        rows["utxos"].append(project_utxo_row(record))
        rows["assets"].append(
            project_asset_row(record.asset, provenance, finality=record.finality)
        )
        if record.owner is not None:
            rows["accounts"].append(
                project_account_row(
                    record.owner, provenance, finality=record.finality
                )
            )
    elif isinstance(record, TokenAccountRecord):
        rows["token_accounts"].append(project_token_account_row(record))
        rows["assets"].append(
            project_asset_row(record.asset, provenance, finality=record.finality)
        )
        rows["accounts"].append(
            project_account_row(
                record.token_account, provenance, finality=record.finality
            )
        )
        if record.owner is not None:
            rows["accounts"].append(
                project_account_row(
                    record.owner, provenance, finality=record.finality
                )
            )
    elif isinstance(record, ContractEventRecord):
        rows["contract_events"].append(project_contract_event_row(record))
        rows["accounts"].append(
            project_account_row(
                record.contract, provenance, finality=record.finality
            )
        )
        if record.data_ref is not None:
            rows["encrypted_object_refs"].append(
                project_encrypted_object_ref_row(
                    record.data_ref,
                    chain=chain,
                    provenance=provenance,
                    finality=record.finality,
                    related_record_id=record.record_id,
                )
            )
    else:
        raise WalletSchemaError(
            f"unsupported ledger record type: {type(record).__name__}"
        )

    # Drop empty tables for a compact result while preserving order.
    return {name: value for name, value in rows.items() if value}


def query_visible_table_names() -> tuple[str, ...]:
    """Return the closed set of query-visible wallet catalog tables."""

    return WALLET_CATALOG_TABLES


def iter_query_visible_columns() -> Iterable[tuple[str, str, ColumnDataClass]]:
    """Yield ``(table, column, classification)`` for every query-visible column."""

    for table in WALLET_CATALOG_TABLES:
        for column, classification in WALLET_COLUMN_CLASSIFICATIONS[table].items():
            yield table, column, classification


__all__ = [
    "ColumnDataClass",
    "ColumnSpec",
    "DUCKDB_WALLET_SCHEMA_INTERFACE",
    "DUCKDB_WALLET_SCHEMA_VERSION",
    "FORBIDDEN_QUERY_CLASSES",
    "MONETARY_AMOUNT_COLUMNS",
    "QUERY_VISIBLE_CLASSES",
    "ROW_BINDING_COLUMNS",
    "WALLET_CATALOG_DDL",
    "WALLET_CATALOG_NAME",
    "WALLET_CATALOG_TABLES",
    "WALLET_COLUMN_CLASSIFICATIONS",
    "WalletSchemaError",
    "assert_no_float_monetary_types",
    "assert_no_secret_or_raw_payload_columns",
    "assert_public_data_classification",
    "assert_row_bindings",
    "assert_wallet_schema_invariants",
    "exact_amount_strings",
    "iter_query_visible_columns",
    "monetary_columns_for_table",
    "parse_wallet_catalog_ddl",
    "project_account_row",
    "project_asset_row",
    "project_block_row",
    "project_chain_row",
    "project_checkpoint_row",
    "project_contract_event_row",
    "project_cursor_row",
    "project_encrypted_object_ref_row",
    "project_finality_transition_row",
    "project_ingestion_source_row",
    "project_ledger_record_rows",
    "project_reorg_row",
    "project_token_account_row",
    "project_transaction_row",
    "project_transfer_row",
    "project_utxo_row",
    "query_visible_table_names",
    "source_id_for_provenance",
    "wallet_schema_descriptor",
]

"""Privacy-safe normalized wallet ledger DuckDB schema (DQK-035).

Maps chain-neutral wallet models onto strict typed tables for the wallet
catalog plane:

* ``chains``, ``ingestion_sources``, ``accounts``, ``assets``
* ``blocks``, ``transactions``, ``transfers``, ``utxos``
* ``token_accounts``, ``contract_events``
* ``cursors``, ``checkpoints``, ``finality_transitions``, ``reorgs``
* ``encrypted_object_refs`` (authority-only; never query-visible)

Design constraints (acceptance for DQK-035 / DQK-G700):

* Monetary amounts are exact base-unit **decimal integer strings**
  (``VARCHAR``) plus integer decimals — never ``FLOAT`` / ``DOUBLE`` / ``REAL``.
* Every durable row binds **chain**, **source**, and **finality**.
* Secret-bearing field names and raw payload bodies are absent from
  **query-visible** tables. Encrypted/raw object bytes stay outside the
  general SQL surface; only content references (digest/CID metadata) may
  appear, and only on the non-query-visible ``encrypted_object_refs`` table.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import json
import re
from types import MappingProxyType
from typing import Any, Final, Protocol

from .canonical import deterministic_id, format_datetime
from .models import (
    AccountRef,
    AssetRef,
    BlockRecord,
    ChainRef,
    ContractEventRecord,
    ExactAmount,
    Finality,
    LedgerCursor,
    LedgerRecord,
    Provenance,
    TokenAccountRecord,
    TransactionRecord,
    TransferRecord,
    UTXORecord,
    ensure_secret_safe,
)


__all__ = [
    "WALLET_SCHEMA_ID",
    "WALLET_SCHEMA_VERSION",
    "WALLET_CATALOG_TABLES",
    "FORBIDDEN_MONETARY_TYPES",
    "FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES",
    "SECRET_BEARING_COLUMN_NAMES",
    "RAW_PAYLOAD_COLUMN_NAMES",
    "REQUIRED_ROW_BINDINGS",
    "MONETARY_COLUMN_SUFFIXES",
    "DataClassification",
    "DuckType",
    "ColumnSpec",
    "TableSpec",
    "SchemaError",
    "wallet_table_specs",
    "wallet_table_map",
    "query_visible_tables",
    "authority_only_tables",
    "ddl_for_table",
    "ddl_for_schema",
    "schema_digest_material",
    "validate_schema_invariants",
    "validate_amount_string",
    "validate_row_bindings",
    "validate_row_against_table",
    "amount_columns",
    "classify_column",
    "is_query_visible_table",
    "is_monetary_column",
    "project_chain_row",
    "project_ingestion_source_row",
    "project_account_row",
    "project_asset_row",
    "project_block_row",
    "project_transaction_row",
    "project_transfer_row",
    "project_utxo_row",
    "project_token_account_row",
    "project_contract_event_row",
    "project_cursor_row",
    "project_checkpoint_row",
    "project_finality_transition_row",
    "project_reorg_row",
    "project_encrypted_object_ref_row",
    "project_ledger_record",
    "assert_no_float_monetary_values",
    "assert_query_visible_row_safe",
    "apply_wallet_schema",
    "iter_wallet_ddl_statements",
    "publication_table_names",
]


# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

WALLET_SCHEMA_ID: Final[str] = "ipfs_datasets_py/wallet-ledger-duckdb@1"
WALLET_SCHEMA_VERSION: Final[int] = 1

# Catalog table names from the control-plane plan (wallet namespace).
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

REQUIRED_ROW_BINDINGS: Final[tuple[str, ...]] = (
    "chain_ref_id",
    "source_provider",
    "finality",
)

# Binary floating types and fixed-point SQL numerics are both forbidden for
# monetary base units: the catalog stores exact integer strings only so JSON,
# Parquet, and SQL consumers never re-coerce amounts through IEEE-754.
FORBIDDEN_MONETARY_TYPES: Final[frozenset[str]] = frozenset(
    {
        "FLOAT",
        "DOUBLE",
        "REAL",
        "FLOAT4",
        "FLOAT8",
        "DECIMAL",
        "NUMERIC",
        "HUGEINT",
    }
)

# Exact base-unit integer string (canonical form from ExactAmount / models).
_DECIMAL_INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")

MONETARY_COLUMN_SUFFIXES: Final[tuple[str, ...]] = (
    "base_units",
    "amount_base_units",
    "fee_base_units",
)

# Columns that must never appear on query-visible tables.
SECRET_BEARING_COLUMN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "api_secret",
        "auth_token",
        "authorization",
        "bearer",
        "client_secret",
        "credential",
        "credentials",
        "mnemonic",
        "passphrase",
        "passwd",
        "password",
        "private_key",
        "provider_secret",
        "recovery_phrase",
        "recovery_seed",
        "refresh_token",
        "secret",
        "seed",
        "seed_phrase",
        "session_token",
        "signing_key",
        "signing_material",
        "user_token",
        "wallet_seed",
    }
)

RAW_PAYLOAD_COLUMN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "body",
        "ciphertext",
        "encrypted_body",
        "payload",
        "payload_bytes",
        "payload_json",
        "raw",
        "raw_body",
        "raw_payload",
        "raw_payload_body",
        "raw_payload_json",
        "plaintext",
    }
)

# Continuation tokens and free-form extension blobs are not secret by name
# alone, but they are excluded from query-visible tables because they may
# carry provider-private pagination material or unbounded chain extensions.
NON_PUBLIC_AUX_COLUMN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "continuation_token",
        "extensions",
        "extensions_json",
        "metadata_json",
        "provider_token",
    }
)

FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES: Final[frozenset[str]] = (
    SECRET_BEARING_COLUMN_NAMES
    | RAW_PAYLOAD_COLUMN_NAMES
    | NON_PUBLIC_AUX_COLUMN_NAMES
)


class SchemaError(ValueError):
    """Raised when a wallet DuckDB schema invariant is violated."""


class DataClassification(StrEnum):
    """Column / table classification for publication policy."""

    PUBLIC = "public"
    """Safe for query-visible and sanitized Quack publication planes."""

    INTERNAL = "internal"
    """Authority catalog only; not projected to untrusted sessions."""

    REFERENCE = "reference"
    """Content reference metadata (digest/CID) without payload bytes."""


class DuckType(StrEnum):
    """Closed set of DuckDB column types used by the wallet schema.

    Monetary amounts intentionally use :attr:`VARCHAR` only. Floating types,
    ``DECIMAL`` / ``NUMERIC``, and other numeric coercions are absent from
    this enum so they cannot be introduced by accident on amount columns.
    """

    VARCHAR = "VARCHAR"
    BIGINT = "BIGINT"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    # Wall-clock provenance only — never used for monetary amounts.
    TIMESTAMPTZ = "TIMESTAMPTZ"


class _DuckDBConnection(Protocol):
    """Minimal DuckDB connection surface used by :func:`apply_wallet_schema`."""

    def execute(self, query: str) -> Any:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One typed, classified column of a wallet table."""

    name: str
    duck_type: DuckType
    nullable: bool = False
    classification: DataClassification = DataClassification.PUBLIC
    primary_key: bool = False
    monetary: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise SchemaError("column name must be non-empty")
        if not isinstance(self.duck_type, DuckType):
            raise SchemaError(f"column {self.name!r} has invalid duck type")
        if self.duck_type.value.upper() in FORBIDDEN_MONETARY_TYPES:
            raise SchemaError(
                f"column {self.name!r} uses forbidden type {self.duck_type.value}"
            )
        if self.monetary:
            if self.duck_type is not DuckType.VARCHAR:
                raise SchemaError(
                    f"monetary column {self.name!r} must be VARCHAR "
                    f"(exact base-unit integer string), got {self.duck_type.value}"
                )
            if self.classification is DataClassification.PUBLIC and not self.name.endswith(
                "base_units"
            ):
                # Allow explicit monetary flag only on base-unit string columns.
                if "base_units" not in self.name:
                    raise SchemaError(
                        f"monetary column {self.name!r} must encode base units"
                    )
        if (
            self.classification is DataClassification.PUBLIC
            and self.name in FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES
        ):
            raise SchemaError(
                f"column {self.name!r} cannot be classified public "
                "(secret-bearing, raw payload, or non-public auxiliary name)"
            )

    @property
    def sql_type(self) -> str:
        return self.duck_type.value

    def ddl_fragment(self) -> str:
        null_sql = "" if self.nullable else " NOT NULL"
        return f"{self.name} {self.sql_type}{null_sql}"


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Strict typed definition of one wallet catalog table."""

    name: str
    columns: tuple[ColumnSpec, ...]
    query_visible: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise SchemaError("table name must be non-empty")
        if not self.columns:
            raise SchemaError(f"table {self.name!r} must define columns")
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise SchemaError(f"table {self.name!r} has duplicate column names")
        if self.query_visible:
            for column in self.columns:
                if column.name in FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES:
                    raise SchemaError(
                        f"query-visible table {self.name!r} must not include "
                        f"column {column.name!r}"
                    )
                if column.classification is DataClassification.INTERNAL:
                    raise SchemaError(
                        f"query-visible table {self.name!r} cannot include "
                        f"internal column {column.name!r}"
                    )
            for required in REQUIRED_ROW_BINDINGS:
                if required not in names:
                    raise SchemaError(
                        f"table {self.name!r} must bind {required} on every row"
                    )
        else:
            # Authority-only tables still bind chain/source/finality so reorg
            # and custody paths cannot lose provenance.
            for required in REQUIRED_ROW_BINDINGS:
                if required not in names:
                    raise SchemaError(
                        f"authority table {self.name!r} must bind {required}"
                    )

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def primary_key(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.primary_key)

    def column(self, name: str) -> ColumnSpec:
        for column in self.columns:
            if column.name == name:
                return column
        raise SchemaError(f"table {self.name!r} has no column {name!r}")

    def monetary_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(column for column in self.columns if column.monetary)


def _col(
    name: str,
    duck_type: DuckType,
    *,
    nullable: bool = False,
    classification: DataClassification = DataClassification.PUBLIC,
    primary_key: bool = False,
    monetary: bool = False,
    description: str = "",
) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        duck_type=duck_type,
        nullable=nullable,
        classification=classification,
        primary_key=primary_key,
        monetary=monetary,
        description=description,
    )


def _binding_columns() -> tuple[ColumnSpec, ...]:
    """Chain / source / finality envelope required on every row."""

    return (
        _col(
            "chain_ref_id",
            DuckType.VARCHAR,
            description="Deterministic chain identity (urn:wallet:chain:...)",
        ),
        _col(
            "chain_namespace",
            DuckType.VARCHAR,
            description="Public chain namespace (e.g. eip155, bip122)",
        ),
        _col("network", DuckType.VARCHAR),
        _col("chain_id", DuckType.VARCHAR),
        _col("genesis_hash", DuckType.VARCHAR),
        _col(
            "source_provider",
            DuckType.VARCHAR,
            description="Ingestion provider identity (no credentials)",
        ),
        _col("source_provider_kind", DuckType.VARCHAR),
        _col("source_request_id", DuckType.VARCHAR),
        _col("source_scope", DuckType.VARCHAR),
        _col(
            "finality",
            DuckType.VARCHAR,
            description="Portable Finality enum value",
        ),
    )


def _ledger_position_columns() -> tuple[ColumnSpec, ...]:
    return (
        _col("ledger_sequence", DuckType.BIGINT, nullable=True),
        _col("ledger_hash", DuckType.VARCHAR, nullable=True),
        _col("transaction_index", DuckType.INTEGER, nullable=True),
        _col("event_index", DuckType.INTEGER, nullable=True),
    )


def _observed_at_column() -> ColumnSpec:
    return _col(
        "observed_at",
        DuckType.VARCHAR,
        description="RFC 3339 UTC observation timestamp (microsecond fixed)",
    )


def _build_wallet_tables() -> tuple[TableSpec, ...]:
    chains = TableSpec(
        name="chains",
        description="Network and genesis-bound chain identity registry",
        columns=(
            _col("chain_ref_id", DuckType.VARCHAR, primary_key=True),
            _col("chain_namespace", DuckType.VARCHAR),
            _col("network", DuckType.VARCHAR),
            _col("chain_id", DuckType.VARCHAR),
            _col("genesis_hash", DuckType.VARCHAR),
            _col("source_provider", DuckType.VARCHAR),
            _col("source_provider_kind", DuckType.VARCHAR),
            _col("source_request_id", DuckType.VARCHAR),
            _col("source_scope", DuckType.VARCHAR),
            _col("finality", DuckType.VARCHAR),
            _observed_at_column(),
        ),
    )

    ingestion_sources = TableSpec(
        name="ingestion_sources",
        description="Public provider/source identities without credentials",
        columns=(
            _col("source_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("provider", DuckType.VARCHAR),
            _col("provider_kind", DuckType.VARCHAR),
            _col("scope", DuckType.VARCHAR),
        ),
    )

    accounts = TableSpec(
        name="accounts",
        description="Canonical account/address identities scoped to one chain",
        columns=(
            _col("account_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("address", DuckType.VARCHAR),
            _col("kind", DuckType.VARCHAR),
        ),
    )

    assets = TableSpec(
        name="assets",
        description="Native or issued asset identities with display precision",
        columns=(
            _col("asset_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("asset_namespace", DuckType.VARCHAR),
            _col("asset_reference", DuckType.VARCHAR),
            _col("decimals", DuckType.INTEGER),
            _col("kind", DuckType.VARCHAR),
            _col("symbol", DuckType.VARCHAR, nullable=True),
        ),
    )

    blocks = TableSpec(
        name="blocks",
        description="Normalized block / slot / ledger headers",
        columns=(
            _col("record_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            *_ledger_position_columns(),
            _col("block_hash", DuckType.VARCHAR),
            _col("parent_hash", DuckType.VARCHAR, nullable=True),
            _col("block_time", DuckType.VARCHAR, nullable=True),
            _col("transaction_count", DuckType.INTEGER, nullable=True),
        ),
    )

    transactions = TableSpec(
        name="transactions",
        description="Normalized transaction facts with exact fee strings",
        columns=(
            _col("record_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            *_ledger_position_columns(),
            _col("transaction_hash", DuckType.VARCHAR),
            _col("status", DuckType.VARCHAR),
            _col(
                "fee_base_units",
                DuckType.VARCHAR,
                nullable=True,
                monetary=True,
                description="Exact fee in base units as decimal integer string",
            ),
            _col("fee_decimals", DuckType.INTEGER, nullable=True),
            _col("block_time", DuckType.VARCHAR, nullable=True),
            _col(
                "participant_account_ids",
                DuckType.VARCHAR,
                nullable=True,
                description="Comma-free ordered JSON array of account_id strings",
            ),
        ),
    )

    transfers = TableSpec(
        name="transfers",
        description="Normalized value movements with exact amount strings",
        columns=(
            _col("record_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            *_ledger_position_columns(),
            _col("transaction_hash", DuckType.VARCHAR),
            _col("transfer_index", DuckType.INTEGER),
            _col("asset_id", DuckType.VARCHAR),
            _col(
                "amount_base_units",
                DuckType.VARCHAR,
                monetary=True,
                description="Exact transfer amount base units (integer string)",
            ),
            _col("amount_decimals", DuckType.INTEGER),
            _col("source_account_id", DuckType.VARCHAR, nullable=True),
            _col("destination_account_id", DuckType.VARCHAR, nullable=True),
            _col("transfer_kind", DuckType.VARCHAR),
        ),
    )

    utxos = TableSpec(
        name="utxos",
        description="UTXO outputs with exact amount strings",
        columns=(
            _col("record_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            *_ledger_position_columns(),
            _col("transaction_hash", DuckType.VARCHAR),
            _col("output_index", DuckType.INTEGER),
            _col("asset_id", DuckType.VARCHAR),
            _col(
                "amount_base_units",
                DuckType.VARCHAR,
                monetary=True,
                description="Exact UTXO amount base units (integer string)",
            ),
            _col("amount_decimals", DuckType.INTEGER),
            _col("owner_account_id", DuckType.VARCHAR, nullable=True),
            _col("spent_by_transaction_hash", DuckType.VARCHAR, nullable=True),
        ),
    )

    token_accounts = TableSpec(
        name="token_accounts",
        description="Token-account balances with exact amount strings",
        columns=(
            _col("record_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            *_ledger_position_columns(),
            _col("token_account_id", DuckType.VARCHAR),
            _col("owner_account_id", DuckType.VARCHAR, nullable=True),
            _col("asset_id", DuckType.VARCHAR),
            _col(
                "amount_base_units",
                DuckType.VARCHAR,
                monetary=True,
                description="Exact token-account amount base units (integer string)",
            ),
            _col("amount_decimals", DuckType.INTEGER),
        ),
    )

    contract_events = TableSpec(
        name="contract_events",
        description="Contract log facts without raw event payload bodies",
        columns=(
            _col("record_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            *_ledger_position_columns(),
            _col("transaction_hash", DuckType.VARCHAR),
            # event_index is carried by ledger_position.event_index (no duplicate).
            _col("contract_account_id", DuckType.VARCHAR),
            _col("event_signature", DuckType.VARCHAR, nullable=True),
            _col(
                "topics_json",
                DuckType.VARCHAR,
                nullable=True,
                description="JSON array of public topic strings",
            ),
            _col(
                "data_digest",
                DuckType.VARCHAR,
                nullable=True,
                classification=DataClassification.REFERENCE,
                description="Content digest of event data (no raw bytes)",
            ),
            _col(
                "data_cid",
                DuckType.VARCHAR,
                nullable=True,
                classification=DataClassification.REFERENCE,
                description="CID of event data object (no raw bytes)",
            ),
        ),
    )

    cursors = TableSpec(
        name="cursors",
        description="Hash-anchored scan cursors without provider continuation tokens",
        columns=(
            _col("cursor_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("provider", DuckType.VARCHAR),
            _col("scope", DuckType.VARCHAR),
            _col("normalized_schema_major", DuckType.INTEGER),
            _col("normalizer_version", DuckType.VARCHAR),
            _col("ledger_sequence", DuckType.BIGINT, nullable=True),
            _col("ledger_hash", DuckType.VARCHAR, nullable=True),
            _col("transaction_index", DuckType.INTEGER, nullable=True),
            _col("event_index", DuckType.INTEGER, nullable=True),
            _col("revision", DuckType.VARCHAR),
        ),
    )

    checkpoints = TableSpec(
        name="checkpoints",
        description="Durable hash-anchored checkpoints without continuation tokens",
        columns=(
            _col("checkpoint_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("provider", DuckType.VARCHAR),
            _col("scope", DuckType.VARCHAR),
            _col("normalized_schema_major", DuckType.INTEGER),
            _col("normalizer_version", DuckType.VARCHAR),
            _col("anchor_sequence", DuckType.BIGINT),
            _col("anchor_hash", DuckType.VARCHAR),
            _col("revision", DuckType.VARCHAR),
            _col("safety_depth", DuckType.INTEGER),
            _col("sink_commit_id", DuckType.VARCHAR, nullable=True),
        ),
    )

    finality_transitions = TableSpec(
        name="finality_transitions",
        description="Explicit finality state-machine transitions",
        columns=(
            _col("transition_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("record_id", DuckType.VARCHAR),
            _col("from_finality", DuckType.VARCHAR),
            _col("to_finality", DuckType.VARCHAR),
            _col("reason", DuckType.VARCHAR, nullable=True),
            _col("confirmations", DuckType.INTEGER, nullable=True),
            _col("head_sequence", DuckType.BIGINT, nullable=True),
        ),
    )

    reorgs = TableSpec(
        name="reorgs",
        description="Retained reorg decisions and orphan lineage",
        columns=(
            _col("reorg_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col("kind", DuckType.VARCHAR),
            _col("checkpoint_sequence", DuckType.BIGINT),
            _col("checkpoint_hash", DuckType.VARCHAR),
            _col("observed_sequence", DuckType.BIGINT),
            _col("observed_hash", DuckType.VARCHAR),
            _col("ancestor_sequence", DuckType.BIGINT, nullable=True),
            _col("ancestor_hash", DuckType.VARCHAR, nullable=True),
            _col("rewind_sequence", DuckType.BIGINT, nullable=True),
            _col("review_required", DuckType.BOOLEAN),
            _col("reason", DuckType.VARCHAR, nullable=True),
            _col(
                "orphaned_hashes_json",
                DuckType.VARCHAR,
                nullable=True,
                description="JSON array of orphaned block hashes",
            ),
        ),
    )

    # Authority-only: content references for encrypted/raw objects. No body,
    # ciphertext, or secret columns — and never query-visible.
    encrypted_object_refs = TableSpec(
        name="encrypted_object_refs",
        query_visible=False,
        description=(
            "CID/digest references to encrypted or raw provider objects; "
            "payload bytes are never stored in SQL"
        ),
        columns=(
            _col("object_ref_id", DuckType.VARCHAR, primary_key=True),
            *_binding_columns(),
            _observed_at_column(),
            _col(
                "digest",
                DuckType.VARCHAR,
                nullable=True,
                classification=DataClassification.REFERENCE,
            ),
            _col(
                "cid",
                DuckType.VARCHAR,
                nullable=True,
                classification=DataClassification.REFERENCE,
            ),
            _col(
                "media_type",
                DuckType.VARCHAR,
                classification=DataClassification.REFERENCE,
            ),
            _col(
                "byte_length",
                DuckType.BIGINT,
                nullable=True,
                classification=DataClassification.REFERENCE,
            ),
            _col(
                "custody_policy",
                DuckType.VARCHAR,
                classification=DataClassification.INTERNAL,
                description="omitted | referenced | separately_encrypted",
            ),
        ),
    )

    tables = (
        chains,
        ingestion_sources,
        accounts,
        assets,
        blocks,
        transactions,
        transfers,
        utxos,
        token_accounts,
        contract_events,
        cursors,
        checkpoints,
        finality_transitions,
        reorgs,
        encrypted_object_refs,
    )
    names = tuple(table.name for table in tables)
    if names != WALLET_CATALOG_TABLES:
        raise SchemaError(
            "wallet table set must match the control-plane catalog exactly: "
            f"expected {WALLET_CATALOG_TABLES}, got {names}"
        )
    return tables


_WALLET_TABLES: Final[tuple[TableSpec, ...]] = _build_wallet_tables()
_WALLET_TABLE_MAP: Final[Mapping[str, TableSpec]] = MappingProxyType(
    {table.name: table for table in _WALLET_TABLES}
)


def wallet_table_specs() -> tuple[TableSpec, ...]:
    """Return the frozen wallet catalog table specifications."""

    return _WALLET_TABLES


def wallet_table_map() -> Mapping[str, TableSpec]:
    """Return an immutable name → :class:`TableSpec` mapping."""

    return _WALLET_TABLE_MAP


def query_visible_tables() -> tuple[TableSpec, ...]:
    """Tables safe to expose on the general query / publication surface."""

    return tuple(table for table in _WALLET_TABLES if table.query_visible)


def authority_only_tables() -> tuple[TableSpec, ...]:
    """Tables that must never be attached to untrusted Quack sessions."""

    return tuple(table for table in _WALLET_TABLES if not table.query_visible)


def is_query_visible_table(name: str) -> bool:
    table = _WALLET_TABLE_MAP.get(name)
    if table is None:
        raise SchemaError(f"unknown wallet table {name!r}")
    return table.query_visible


def is_monetary_column(table_name: str, column_name: str) -> bool:
    return _WALLET_TABLE_MAP[table_name].column(column_name).monetary


def amount_columns(table_name: str | None = None) -> tuple[tuple[str, str], ...]:
    """Return ``(table, column)`` pairs for every monetary amount column."""

    pairs: list[tuple[str, str]] = []
    tables = (
        (_WALLET_TABLE_MAP[table_name],)
        if table_name is not None
        else _WALLET_TABLES
    )
    for table in tables:
        for column in table.monetary_columns():
            pairs.append((table.name, column.name))
    return tuple(pairs)


def classify_column(table_name: str, column_name: str) -> DataClassification:
    return _WALLET_TABLE_MAP[table_name].column(column_name).classification


def ddl_for_table(table: TableSpec | str) -> str:
    """Return ``CREATE TABLE`` DDL for one wallet table."""

    if isinstance(table, str):
        table = _WALLET_TABLE_MAP[table]
    column_sql = ",\n  ".join(column.ddl_fragment() for column in table.columns)
    pk = table.primary_key
    pk_sql = f",\n  PRIMARY KEY ({', '.join(pk)})" if pk else ""
    return (
        f"CREATE TABLE IF NOT EXISTS {table.name} (\n"
        f"  {column_sql}{pk_sql}\n"
        f");"
    )


def ddl_for_schema() -> str:
    """Return concatenated DDL for the full wallet catalog."""

    return "\n\n".join(ddl_for_table(table) for table in _WALLET_TABLES)


def iter_wallet_ddl_statements() -> tuple[str, ...]:
    """Return individual ``CREATE TABLE`` statements in catalog order."""

    return tuple(ddl_for_table(table) for table in _WALLET_TABLES)


def apply_wallet_schema(connection: _DuckDBConnection) -> tuple[str, ...]:
    """Apply the full wallet catalog DDL to an explicit DuckDB connection.

    Importing this module never opens a connection; callers must supply one.
    Returns the table names that were ensured.
    """

    if connection is None:
        raise SchemaError("DuckDB connection is required to apply wallet schema")
    applied: list[str] = []
    for table in _WALLET_TABLES:
        connection.execute(ddl_for_table(table))
        applied.append(table.name)
    return tuple(applied)


def publication_table_names() -> frozenset[str]:
    """Names of tables permitted on the query / Quack publication surface."""

    return frozenset(table.name for table in query_visible_tables())


def schema_digest_material() -> Mapping[str, Any]:
    """Stable structure used by migration/receipt digests (no SQL formatting)."""

    return {
        "schema_id": WALLET_SCHEMA_ID,
        "schema_version": WALLET_SCHEMA_VERSION,
        "required_bindings": list(REQUIRED_ROW_BINDINGS),
        "publication_tables": sorted(publication_table_names()),
        "authority_only_tables": sorted(
            table.name for table in authority_only_tables()
        ),
        "tables": [
            {
                "name": table.name,
                "query_visible": table.query_visible,
                "columns": [
                    {
                        "name": column.name,
                        "type": column.duck_type.value,
                        "nullable": column.nullable,
                        "classification": column.classification.value,
                        "primary_key": column.primary_key,
                        "monetary": column.monetary,
                    }
                    for column in table.columns
                ],
            }
            for table in _WALLET_TABLES
        ],
    }


def validate_schema_invariants() -> None:
    """Fail closed if the compiled schema violates DQK-035 acceptance rules."""

    if set(_WALLET_TABLE_MAP) != set(WALLET_CATALOG_TABLES):
        raise SchemaError("wallet catalog table set mismatch")

    for table in _WALLET_TABLES:
        for column in table.columns:
            type_name = column.duck_type.value.upper()
            if type_name in FORBIDDEN_MONETARY_TYPES or type_name in {
                "FLOAT",
                "DOUBLE",
                "REAL",
            }:
                raise SchemaError(
                    f"{table.name}.{column.name} uses forbidden type {type_name}"
                )
            if column.monetary and column.duck_type is not DuckType.VARCHAR:
                raise SchemaError(
                    f"{table.name}.{column.name} monetary column is not VARCHAR"
                )
            if table.query_visible and column.name in FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES:
                raise SchemaError(
                    f"query-visible {table.name}.{column.name} is forbidden"
                )
            if table.query_visible and column.name in SECRET_BEARING_COLUMN_NAMES:
                raise SchemaError(
                    f"secret-bearing column on query-visible table: "
                    f"{table.name}.{column.name}"
                )
            if table.query_visible and column.name in RAW_PAYLOAD_COLUMN_NAMES:
                raise SchemaError(
                    f"raw payload column on query-visible table: "
                    f"{table.name}.{column.name}"
                )
        for required in REQUIRED_ROW_BINDINGS:
            if required not in table.column_names:
                raise SchemaError(f"{table.name} missing binding {required}")

    # Explicitly require at least one monetary string column on value tables.
    for name in ("transfers", "utxos", "token_accounts", "transactions"):
        mon = _WALLET_TABLE_MAP[name].monetary_columns()
        if name != "transactions" and not mon:
            raise SchemaError(f"{name} must declare monetary amount columns")
        for column in mon:
            if column.duck_type is not DuckType.VARCHAR:
                raise SchemaError(f"{name}.{column.name} must be VARCHAR")

    if _WALLET_TABLE_MAP["encrypted_object_refs"].query_visible:
        raise SchemaError("encrypted_object_refs must not be query-visible")

    # DDL must never mention forbidden float / numeric amount types.
    ddl = ddl_for_schema().upper()
    for forbidden in sorted(FORBIDDEN_MONETARY_TYPES):
        if re.search(rf"\b{re.escape(forbidden)}\b", ddl):
            raise SchemaError(f"schema DDL contains forbidden type {forbidden}")

    if not publication_table_names():
        raise SchemaError("wallet schema must expose at least one publication table")
    if "encrypted_object_refs" in publication_table_names():
        raise SchemaError("encrypted_object_refs must not be a publication table")


def validate_amount_string(value: object, *, name: str = "amount") -> str:
    """Accept only canonical decimal integer strings (no float coercion)."""

    if isinstance(value, bool) or isinstance(value, float) or isinstance(value, Decimal):
        raise SchemaError(
            f"{name} must be an exact decimal integer string, not {type(value).__name__}"
        )
    if isinstance(value, int):
        # Integers are allowed only as an explicit conversion path via ExactAmount;
        # row validation requires strings so SQL never sees numeric coercion.
        raise SchemaError(
            f"{name} must be a canonical decimal integer string, not int "
            "(use ExactAmount.from_int / str(base_units) before projection)"
        )
    if not isinstance(value, str) or not _DECIMAL_INTEGER.fullmatch(value):
        raise SchemaError(
            f"{name} must be a canonical decimal integer string "
            r"(pattern ^-?(?:0|[1-9][0-9]*)$)"
        )
    return value


def validate_row_bindings(row: Mapping[str, Any], *, table: str | None = None) -> None:
    """Require chain / source / finality on every projected row."""

    for key in REQUIRED_ROW_BINDINGS:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            where = f" in table {table}" if table else ""
            raise SchemaError(f"row missing required binding {key}{where}")
    try:
        Finality(row["finality"])
    except ValueError as exc:
        raise SchemaError(
            f"finality must be a Finality value, got {row['finality']!r}"
        ) from exc


def validate_row_against_table(table_name: str, row: Mapping[str, Any]) -> None:
    """Validate bindings, types, monetary strings, and query-visible safety."""

    table = _WALLET_TABLE_MAP[table_name]
    validate_row_bindings(row, table=table_name)
    for column in table.columns:
        if column.name not in row:
            if column.nullable:
                continue
            raise SchemaError(
                f"{table_name} row missing non-null column {column.name!r}"
            )
        value = row[column.name]
        if value is None:
            if not column.nullable:
                raise SchemaError(
                    f"{table_name}.{column.name} is not nullable"
                )
            continue
        if column.monetary:
            validate_amount_string(value, name=f"{table_name}.{column.name}")
        elif column.duck_type is DuckType.VARCHAR and not isinstance(value, str):
            raise SchemaError(
                f"{table_name}.{column.name} must be str, got {type(value).__name__}"
            )
        elif column.duck_type in {DuckType.BIGINT, DuckType.INTEGER}:
            if isinstance(value, bool) or not isinstance(value, int):
                raise SchemaError(
                    f"{table_name}.{column.name} must be int, got {type(value).__name__}"
                )
        elif column.duck_type is DuckType.BOOLEAN and not isinstance(value, bool):
            raise SchemaError(
                f"{table_name}.{column.name} must be bool, got {type(value).__name__}"
            )
    if table.query_visible:
        assert_query_visible_row_safe(row)
    assert_no_float_monetary_values(row)


def assert_no_float_monetary_values(row: Mapping[str, Any]) -> None:
    """Reject float / Decimal / int coercion anywhere amount-like keys appear."""

    for key, value in row.items():
        if value is None:
            continue
        if key.endswith("base_units") or key in {
            "amount",
            "fee",
            "balance",
            "quantity",
        }:
            if isinstance(value, (float, Decimal)):
                raise SchemaError(
                    f"float coercion of monetary field {key!r} is forbidden"
                )
            if isinstance(value, str):
                validate_amount_string(value, name=key)
            elif key.endswith("base_units"):
                raise SchemaError(
                    f"monetary field {key!r} must be a string, got {type(value).__name__}"
                )


def assert_query_visible_row_safe(row: Mapping[str, Any]) -> None:
    """Ensure a projected row has no secret or raw-payload material."""

    for key in row:
        if key in FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES:
            raise SchemaError(
                f"query-visible row must not include column {key!r}"
            )
    # Values must also pass the model secret scanner (no concrete secrets).
    ensure_secret_safe(dict(row))


# ---------------------------------------------------------------------------
# Model → row projection (query-visible safe)
# ---------------------------------------------------------------------------


def _chain_fields(chain: ChainRef) -> dict[str, str]:
    return {
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
    }


def _source_fields(provenance: Provenance) -> dict[str, str]:
    # Intentionally omit raw_payload — never lands on query-visible rows.
    return {
        "source_provider": provenance.provider,
        "source_provider_kind": provenance.provider_kind,
        "source_request_id": provenance.request_id,
        "source_scope": provenance.scope,
    }


def _observed_at(value: datetime) -> str:
    return format_datetime(value)


def _position_fields(record: LedgerRecord) -> dict[str, Any]:
    position = record.ledger_position
    return {
        "ledger_sequence": position.sequence,
        "ledger_hash": position.hash,
        "transaction_index": position.transaction_index,
        "event_index": position.event_index,
    }


def _envelope(record: LedgerRecord) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        **_chain_fields(record.chain),
        **_source_fields(record.provenance),
        "finality": record.finality.value,
        "observed_at": _observed_at(record.provenance.observed_at),
        **_position_fields(record),
    }


def _amount_fields(amount: ExactAmount, *, prefix: str = "amount") -> dict[str, Any]:
    validate_amount_string(amount.base_units, name=f"{prefix}_base_units")
    return {
        f"{prefix}_base_units": amount.base_units,
        f"{prefix}_decimals": amount.decimals,
    }


def _default_source(
    *,
    provider: str = "schema-registry",
    provider_kind: str = "local",
    request_id: str = "schema",
    scope: str = "wallet-schema",
) -> dict[str, str]:
    return {
        "source_provider": provider,
        "source_provider_kind": provider_kind,
        "source_request_id": request_id,
        "source_scope": scope,
    }


def project_chain_row(
    chain: ChainRef,
    *,
    provenance: Provenance | None = None,
    finality: Finality = Finality.FINALIZED,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Project a :class:`ChainRef` into the ``chains`` table."""

    if provenance is not None:
        source = _source_fields(provenance)
        observed = _observed_at(provenance.observed_at)
    else:
        source = _default_source(scope="chain-registry")
        if observed_at is None:
            raise SchemaError(
                "observed_at is required when provenance is omitted"
            )
        observed = _observed_at(observed_at)
    row = {
        **_chain_fields(chain),
        **source,
        "finality": finality.value,
        "observed_at": observed,
    }
    validate_row_against_table("chains", row)
    return row


def project_ingestion_source_row(
    provenance: Provenance,
    *,
    chain: ChainRef,
    finality: Finality = Finality.OBSERVED,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Project provenance into ``ingestion_sources`` (no raw payload)."""

    identity = {
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "scope": provenance.scope,
        "chain_ref_id": chain.chain_ref_id,
    }
    row = {
        "source_id": source_id
        or deterministic_id("ingestion-source", identity),
        **_chain_fields(chain),
        **_source_fields(provenance),
        "finality": finality.value,
        "observed_at": _observed_at(provenance.observed_at),
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "scope": provenance.scope,
    }
    validate_row_against_table("ingestion_sources", row)
    return row


def project_account_row(
    account: AccountRef,
    *,
    provenance: Provenance,
    finality: Finality = Finality.OBSERVED,
) -> dict[str, Any]:
    row = {
        "account_id": account.account_id,
        **_chain_fields(account.chain),
        **_source_fields(provenance),
        "finality": finality.value,
        "observed_at": _observed_at(provenance.observed_at),
        "address": account.address,
        "kind": account.kind.value,
    }
    validate_row_against_table("accounts", row)
    return row


def project_asset_row(
    asset: AssetRef,
    *,
    provenance: Provenance,
    finality: Finality = Finality.OBSERVED,
) -> dict[str, Any]:
    row = {
        "asset_id": asset.asset_id,
        **_chain_fields(asset.chain),
        **_source_fields(provenance),
        "finality": finality.value,
        "observed_at": _observed_at(provenance.observed_at),
        "asset_namespace": asset.asset_namespace,
        "asset_reference": asset.asset_reference,
        "decimals": asset.decimals,
        "kind": asset.kind.value,
        "symbol": asset.symbol,
    }
    validate_row_against_table("assets", row)
    return row


def project_block_row(record: BlockRecord) -> dict[str, Any]:
    row = {
        **_envelope(record),
        "block_hash": record.block_hash,
        "parent_hash": record.parent_hash,
        "block_time": (
            None if record.block_time is None else _observed_at(record.block_time)
        ),
        "transaction_count": record.transaction_count,
    }
    validate_row_against_table("blocks", row)
    return row


def project_transaction_row(record: TransactionRecord) -> dict[str, Any]:
    fee_base: str | None = None
    fee_decimals: int | None = None
    if record.fee is not None:
        fee_fields = _amount_fields(record.fee, prefix="fee")
        fee_base = fee_fields["fee_base_units"]
        fee_decimals = fee_fields["fee_decimals"]
    row = {
        **_envelope(record),
        "transaction_hash": record.transaction_hash,
        "status": record.status.value,
        "fee_base_units": fee_base,
        "fee_decimals": fee_decimals,
        "block_time": (
            None if record.block_time is None else _observed_at(record.block_time)
        ),
        "participant_account_ids": json.dumps(
            [item.account_id for item in record.participants],
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    validate_row_against_table("transactions", row)
    return row


def project_transfer_row(record: TransferRecord) -> dict[str, Any]:
    row = {
        **_envelope(record),
        "transaction_hash": record.transaction_hash,
        "transfer_index": record.transfer_index,
        "asset_id": record.asset.asset_id,
        **_amount_fields(record.amount, prefix="amount"),
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
    validate_row_against_table("transfers", row)
    return row


def project_utxo_row(record: UTXORecord) -> dict[str, Any]:
    row = {
        **_envelope(record),
        "transaction_hash": record.transaction_hash,
        "output_index": record.output_index,
        "asset_id": record.asset.asset_id,
        **_amount_fields(record.amount, prefix="amount"),
        "owner_account_id": None if record.owner is None else record.owner.account_id,
        "spent_by_transaction_hash": record.spent_by_transaction_hash,
    }
    validate_row_against_table("utxos", row)
    return row


def project_token_account_row(record: TokenAccountRecord) -> dict[str, Any]:
    row = {
        **_envelope(record),
        "token_account_id": record.token_account.account_id,
        "owner_account_id": None if record.owner is None else record.owner.account_id,
        "asset_id": record.asset.asset_id,
        **_amount_fields(record.amount, prefix="amount"),
    }
    validate_row_against_table("token_accounts", row)
    return row


def project_contract_event_row(record: ContractEventRecord) -> dict[str, Any]:
    data_digest = None
    data_cid = None
    if record.data_ref is not None:
        data_digest = record.data_ref.digest
        data_cid = record.data_ref.cid
    row = {
        **_envelope(record),
        "transaction_hash": record.transaction_hash,
        "contract_account_id": record.contract.account_id,
        "event_signature": record.event_signature,
        "topics_json": json.dumps(
            list(record.topics), separators=(",", ":"), ensure_ascii=False
        ),
        "data_digest": data_digest,
        "data_cid": data_cid,
    }
    # Prefer the record's identity event_index when the ledger position omits it.
    if row.get("event_index") is None:
        row["event_index"] = record.event_index
    elif row["event_index"] != record.event_index:
        raise SchemaError(
            "contract event event_index must match ledger_position.event_index"
        )
    validate_row_against_table("contract_events", row)
    return row


def project_cursor_row(
    cursor: LedgerCursor,
    *,
    finality: Finality = Finality.OBSERVED,
    observed_at: datetime | None = None,
    source_request_id: str = "cursor",
) -> dict[str, Any]:
    """Project a cursor without ``continuation_token`` (never query-visible)."""

    if observed_at is None:
        raise SchemaError("observed_at is required for cursor projection")
    row = {
        "cursor_id": cursor.cursor_id,
        **_chain_fields(cursor.chain),
        "source_provider": cursor.provider,
        "source_provider_kind": "cursor",
        "source_request_id": source_request_id,
        "source_scope": cursor.scope,
        "finality": finality.value,
        "observed_at": _observed_at(observed_at),
        "provider": cursor.provider,
        "scope": cursor.scope,
        "normalized_schema_major": cursor.normalized_schema_major,
        "normalizer_version": cursor.normalizer_version,
        "ledger_sequence": cursor.position.sequence,
        "ledger_hash": cursor.position.hash,
        "transaction_index": cursor.position.transaction_index,
        "event_index": cursor.position.event_index,
        "revision": cursor.revision,
    }
    validate_row_against_table("cursors", row)
    return row


def project_checkpoint_row(
    *,
    checkpoint_id: str,
    chain: ChainRef,
    provider: str,
    scope: str,
    normalized_schema_major: int,
    normalizer_version: str,
    anchor_sequence: int,
    anchor_hash: str,
    revision: str,
    safety_depth: int = 0,
    sink_commit_id: str | None = None,
    finality: Finality = Finality.SAFE,
    observed_at: datetime,
    source_request_id: str = "checkpoint",
) -> dict[str, Any]:
    """Project checkpoint public fields (no continuation token / metadata blob)."""

    row = {
        "checkpoint_id": checkpoint_id,
        **_chain_fields(chain),
        "source_provider": provider,
        "source_provider_kind": "checkpoint",
        "source_request_id": source_request_id,
        "source_scope": scope,
        "finality": finality.value,
        "observed_at": _observed_at(observed_at),
        "provider": provider,
        "scope": scope,
        "normalized_schema_major": normalized_schema_major,
        "normalizer_version": normalizer_version,
        "anchor_sequence": anchor_sequence,
        "anchor_hash": anchor_hash,
        "revision": revision,
        "safety_depth": safety_depth,
        "sink_commit_id": sink_commit_id,
    }
    validate_row_against_table("checkpoints", row)
    return row


def project_finality_transition_row(
    *,
    transition_id: str,
    chain: ChainRef,
    record_id: str,
    from_finality: Finality,
    to_finality: Finality,
    provenance: Provenance,
    finality: Finality | None = None,
    reason: str | None = None,
    confirmations: int | None = None,
    head_sequence: int | None = None,
) -> dict[str, Any]:
    row = {
        "transition_id": transition_id,
        **_chain_fields(chain),
        **_source_fields(provenance),
        "finality": (finality or to_finality).value,
        "observed_at": _observed_at(provenance.observed_at),
        "record_id": record_id,
        "from_finality": from_finality.value,
        "to_finality": to_finality.value,
        "reason": reason,
        "confirmations": confirmations,
        "head_sequence": head_sequence,
    }
    validate_row_against_table("finality_transitions", row)
    return row


def project_reorg_row(
    *,
    reorg_id: str,
    chain: ChainRef,
    kind: str,
    checkpoint_sequence: int,
    checkpoint_hash: str,
    observed_sequence: int,
    observed_hash: str,
    provenance: Provenance,
    finality: Finality = Finality.ORPHANED,
    ancestor_sequence: int | None = None,
    ancestor_hash: str | None = None,
    rewind_sequence: int | None = None,
    review_required: bool = False,
    reason: str | None = None,
    orphaned_hashes: Sequence[str] = (),
) -> dict[str, Any]:
    row = {
        "reorg_id": reorg_id,
        **_chain_fields(chain),
        **_source_fields(provenance),
        "finality": finality.value,
        "observed_at": _observed_at(provenance.observed_at),
        "kind": kind,
        "checkpoint_sequence": checkpoint_sequence,
        "checkpoint_hash": checkpoint_hash,
        "observed_sequence": observed_sequence,
        "observed_hash": observed_hash,
        "ancestor_sequence": ancestor_sequence,
        "ancestor_hash": ancestor_hash,
        "rewind_sequence": rewind_sequence,
        "review_required": review_required,
        "reason": reason,
        "orphaned_hashes_json": json.dumps(
            list(orphaned_hashes), separators=(",", ":"), ensure_ascii=False
        ),
    }
    validate_row_against_table("reorgs", row)
    return row


def project_encrypted_object_ref_row(
    *,
    object_ref_id: str,
    chain: ChainRef,
    provenance: Provenance,
    media_type: str,
    custody_policy: str,
    digest: str | None = None,
    cid: str | None = None,
    byte_length: int | None = None,
    finality: Finality = Finality.OBSERVED,
) -> dict[str, Any]:
    """Project an authority-only content reference (no payload body)."""

    if digest is None and cid is None:
        raise SchemaError("encrypted object ref requires digest or cid")
    if not isinstance(media_type, str) or not media_type.strip():
        raise SchemaError("encrypted object ref media_type must be non-empty")
    if not isinstance(custody_policy, str) or not custody_policy.strip():
        raise SchemaError("encrypted object ref custody_policy must be non-empty")
    row = {
        "object_ref_id": object_ref_id,
        **_chain_fields(chain),
        **_source_fields(provenance),
        "finality": finality.value,
        "observed_at": _observed_at(provenance.observed_at),
        "digest": digest,
        "cid": cid,
        "media_type": media_type,
        "byte_length": byte_length,
        "custody_policy": custody_policy,
    }
    if any(key in RAW_PAYLOAD_COLUMN_NAMES for key in row):
        raise SchemaError("encrypted_object_refs must not carry raw payload columns")
    if any(key in SECRET_BEARING_COLUMN_NAMES for key in row):
        raise SchemaError("encrypted_object_refs must not carry secret-bearing columns")
    # Authority-only: bindings + types, never treated as query-visible publication.
    validate_row_against_table("encrypted_object_refs", row)
    return row


def project_ledger_record(record: LedgerRecord) -> tuple[str, dict[str, Any]]:
    """Dispatch a normalized ledger record to its table row projection."""

    if isinstance(record, BlockRecord):
        return "blocks", project_block_row(record)
    if isinstance(record, TransactionRecord):
        return "transactions", project_transaction_row(record)
    if isinstance(record, TransferRecord):
        return "transfers", project_transfer_row(record)
    if isinstance(record, UTXORecord):
        return "utxos", project_utxo_row(record)
    if isinstance(record, TokenAccountRecord):
        return "token_accounts", project_token_account_row(record)
    if isinstance(record, ContractEventRecord):
        return "contract_events", project_contract_event_row(record)
    raise SchemaError(
        f"unsupported ledger record type for projection: {type(record).__name__}"
    )


# Fail closed at import if the static catalog is inconsistent.
validate_schema_invariants()

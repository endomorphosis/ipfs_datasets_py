"""Privacy-safe normalized wallet ledger DuckDB schema (DQK-035).

Maps chain-neutral wallet models to strict typed catalog tables:

* ``chains``, ``ingestion_sources``, ``accounts``, ``assets``
* ``blocks``, ``transactions``, ``transfers``, ``utxos``
* ``token_accounts``, ``contract_events``
* ``cursors``, ``checkpoints``, ``finality_transitions``, ``reorgs``
* ``encrypted_object_refs`` (content-addressed pointers only)

Design invariants:

* Monetary amounts are exact decimal-integer **strings** (``VARCHAR``).  No
  ``FLOAT`` / ``DOUBLE`` / ``REAL`` / ``DECIMAL`` coercion of base units.
* Every query-visible fact row binds ``chain_ref_id``, source identity, and
  ``finality``.
* Secret-bearing fields and unrestricted raw payloads never appear as columns
  on query-visible tables.  Raw provider bytes live behind
  :class:`~models.RawPayloadRef` digests/CIDs in ``encrypted_object_refs``.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from .canonical import deterministic_id, format_datetime
from .checkpoints import CheckpointRecord
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
    RawPayloadRef,
    TokenAccountRecord,
    TransactionRecord,
    TransferRecord,
    UTXORecord,
    ensure_secret_safe,
)


# ---------------------------------------------------------------------------
# Schema / catalog pins
# ---------------------------------------------------------------------------

WALLET_CATALOG_NAME: Final[str] = "wallet"
WALLET_SCHEMA_VERSION: Final[str] = "wallet-duckdb-schema/v1"
WALLET_SCHEMA_INTERFACE: Final[str] = "WalletDuckDBSchema@1"
WALLET_LEDGER_SCHEMA_MAJOR: Final[int] = 1

# Catalog table family declared by the control-plane plan (DQK-G700).
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

# Dimension / identity tables (still public, not observation facts).
WALLET_DIMENSION_TABLES: Final[frozenset[str]] = frozenset(
    {
        "chains",
        "ingestion_sources",
        "accounts",
        "assets",
    }
)

# Observation / operational fact tables: every row binds chain + source + finality.
WALLET_FACT_TABLES: Final[frozenset[str]] = frozenset(
    {
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
    }
)

# All tables that may appear in query surfaces within the wallet catalog.
# ``encrypted_object_refs`` is query-visible only as content pointers (no bodies).
WALLET_QUERY_VISIBLE_TABLES: Final[frozenset[str]] = frozenset(WALLET_CATALOG_TABLES)

# Columns that bind observation authority on fact rows.
CHAIN_BINDING_COLUMNS: Final[tuple[str, ...]] = (
    "chain_ref_id",
    "chain_namespace",
    "network",
    "chain_id",
    "genesis_hash",
)
SOURCE_BINDING_COLUMNS: Final[tuple[str, ...]] = (
    "source_id",
    "provider",
    "provider_kind",
    "scope",
)
FINALITY_BINDING_COLUMN: Final[str] = "finality"
FACT_BINDING_COLUMNS: Final[tuple[str, ...]] = (
    *CHAIN_BINDING_COLUMNS,
    *SOURCE_BINDING_COLUMNS,
    FINALITY_BINDING_COLUMN,
)

# Monetary amount column pairs: base units MUST be VARCHAR exact integer strings.
AMOUNT_BASE_UNIT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "amount_base_units",
        "fee_base_units",
    }
)
AMOUNT_DECIMAL_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "amount_decimals",
        "fee_decimals",
        "decimals",
    }
)

# SQL types that would coerce or approximate monetary values.
_FORBIDDEN_AMOUNT_SQL_TYPES: Final[frozenset[str]] = frozenset(
    {
        "FLOAT",
        "DOUBLE",
        "REAL",
        "FLOAT4",
        "FLOAT8",
        "DECIMAL",
        "NUMERIC",
    }
)

# Column names that must never appear on query-visible wallet tables.
FORBIDDEN_QUERY_COLUMN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "api_secret",
        "auth_token",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "mnemonic",
        "passphrase",
        "passwd",
        "password",
        "payload",
        "payload_bytes",
        "payload_json",
        "private_key",
        "provider_secret",
        "raw",
        "raw_body",
        "raw_payload",
        "raw_payload_body",
        "raw_payload_bytes",
        "raw_payload_json",
        "raw_response",
        "recovery_phrase",
        "recovery_seed",
        "refresh_token",
        "secret",
        "seed",
        "seed_phrase",
        "session_token",
        "signing_key",
        "signing_material",
        "signing_payload",
        "user_token",
        "wallet_seed",
    }
)

_FORBIDDEN_COLUMN_SUBSTRINGS: Final[tuple[str, ...]] = (
    "private_key",
    "secret",
    "mnemonic",
    "seed_phrase",
    "password",
    "passphrase",
    "raw_payload",
    "payload_json",
    "signing_material",
)

_DECIMAL_INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_SQL_TYPE_TOKEN = re.compile(r"^([A-Z][A-Z0-9_]*)")


# ---------------------------------------------------------------------------
# Public-data classification
# ---------------------------------------------------------------------------


class PublicDataClassification(StrEnum):
    """Classification of a column or table for publication / Quack policy.

    Only ``PUBLIC_LEDGER`` and ``OPERATIONAL`` columns are projected as ordinary
    query facts.  ``CONTENT_REF`` columns hold digests/CIDs of encrypted or
    separately stored objects — never plaintext secrets or raw provider bodies.
    ``INTERNAL`` is reserved for non-query surfaces (none in this catalog).
    """

    PUBLIC_LEDGER = "public_ledger"
    OPERATIONAL = "operational"
    CONTENT_REF = "content_ref"
    INTERNAL = "internal"


# ---------------------------------------------------------------------------
# Column / table specifications
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One typed column with public-data classification metadata."""

    name: str
    sql_type: str
    nullable: bool = False
    classification: PublicDataClassification = PublicDataClassification.PUBLIC_LEDGER
    description: str = ""
    is_amount_base_units: bool = False
    is_amount_decimals: bool = False
    is_chain_binding: bool = False
    is_source_binding: bool = False
    is_finality_binding: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.isidentifier():
            raise ValueError(f"invalid column name: {self.name!r}")
        if self.name.casefold() in FORBIDDEN_QUERY_COLUMN_NAMES:
            raise ValueError(
                f"column {self.name!r} is forbidden on query-visible tables"
            )
        for fragment in _FORBIDDEN_COLUMN_SUBSTRINGS:
            if fragment in self.name.casefold():
                raise ValueError(
                    f"column {self.name!r} matches forbidden secret/raw fragment"
                )
        sql_type = self.sql_type.strip().upper()
        object.__setattr__(self, "sql_type", sql_type)
        token_match = _SQL_TYPE_TOKEN.match(sql_type)
        token = token_match.group(1) if token_match else sql_type
        if self.is_amount_base_units:
            if token != "VARCHAR" and not sql_type.startswith("VARCHAR"):
                raise ValueError(
                    f"amount column {self.name!r} must be VARCHAR, got {sql_type}"
                )
            if token in _FORBIDDEN_AMOUNT_SQL_TYPES:
                raise ValueError(
                    f"amount column {self.name!r} forbids type {sql_type}"
                )
        if self.is_amount_decimals and token not in {"INTEGER", "TINYINT", "SMALLINT", "UTINYINT", "USMALLINT", "UINTEGER"}:
            raise ValueError(
                f"decimals column {self.name!r} must be an integer type, got {sql_type}"
            )
        if self.is_amount_base_units and self.classification not in {
            PublicDataClassification.PUBLIC_LEDGER,
            PublicDataClassification.OPERATIONAL,
        }:
            raise ValueError("amount base-unit columns must be public/operational")

    @property
    def sql_type_token(self) -> str:
        match = _SQL_TYPE_TOKEN.match(self.sql_type)
        return match.group(1) if match else self.sql_type

    def ddl_fragment(self) -> str:
        null_sql = "" if self.nullable else " NOT NULL"
        return f"{self.name} {self.sql_type}{null_sql}"


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Strict typed table definition for the wallet catalog."""

    name: str
    columns: tuple[ColumnSpec, ...]
    primary_key: tuple[str, ...]
    classification: PublicDataClassification
    description: str = ""
    requires_fact_bindings: bool = False

    def __post_init__(self) -> None:
        if self.name not in WALLET_CATALOG_TABLES:
            raise ValueError(f"unknown wallet catalog table: {self.name!r}")
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate columns in table {self.name!r}")
        for key in self.primary_key:
            if key not in names:
                raise ValueError(
                    f"primary key column {key!r} missing from table {self.name!r}"
                )
        if self.requires_fact_bindings:
            present = {column.name for column in self.columns}
            missing = [name for name in FACT_BINDING_COLUMNS if name not in present]
            if missing:
                raise ValueError(
                    f"table {self.name!r} missing fact bindings: {missing}"
                )
            for column in self.columns:
                if column.name == FINALITY_BINDING_COLUMN and column.nullable:
                    raise ValueError(
                        f"table {self.name!r} finality binding must be NOT NULL"
                    )
                if column.name in CHAIN_BINDING_COLUMNS and column.nullable:
                    raise ValueError(
                        f"table {self.name!r} chain binding {column.name!r} "
                        "must be NOT NULL"
                    )
                if column.name in SOURCE_BINDING_COLUMNS and column.nullable:
                    raise ValueError(
                        f"table {self.name!r} source binding {column.name!r} "
                        "must be NOT NULL"
                    )

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def is_query_visible(self) -> bool:
        return self.name in WALLET_QUERY_VISIBLE_TABLES

    def column_map(self) -> Mapping[str, ColumnSpec]:
        return MappingProxyType({column.name: column for column in self.columns})

    def create_table_sql(self) -> str:
        column_sql = ",\n    ".join(column.ddl_fragment() for column in self.columns)
        pk = ", ".join(self.primary_key)
        return (
            f"CREATE TABLE IF NOT EXISTS {self.name} (\n"
            f"    {column_sql},\n"
            f"    PRIMARY KEY ({pk})\n"
            f");"
        )


# ---------------------------------------------------------------------------
# Shared column builders
# ---------------------------------------------------------------------------


def _chain_binding_columns(
    *,
    classification: PublicDataClassification = PublicDataClassification.PUBLIC_LEDGER,
) -> tuple[ColumnSpec, ...]:
    return (
        ColumnSpec(
            "chain_ref_id",
            "VARCHAR",
            classification=classification,
            is_chain_binding=True,
            description="Deterministic ChainRef identity",
        ),
        ColumnSpec(
            "chain_namespace",
            "VARCHAR",
            classification=classification,
            is_chain_binding=True,
        ),
        ColumnSpec(
            "network",
            "VARCHAR",
            classification=classification,
            is_chain_binding=True,
        ),
        ColumnSpec(
            "chain_id",
            "VARCHAR",
            classification=classification,
            is_chain_binding=True,
        ),
        ColumnSpec(
            "genesis_hash",
            "VARCHAR",
            classification=classification,
            is_chain_binding=True,
        ),
    )


def _source_binding_columns(
    *,
    classification: PublicDataClassification = PublicDataClassification.OPERATIONAL,
) -> tuple[ColumnSpec, ...]:
    return (
        ColumnSpec(
            "source_id",
            "VARCHAR",
            classification=classification,
            is_source_binding=True,
            description="Deterministic ingestion source identity",
        ),
        ColumnSpec(
            "provider",
            "VARCHAR",
            classification=classification,
            is_source_binding=True,
        ),
        ColumnSpec(
            "provider_kind",
            "VARCHAR",
            classification=classification,
            is_source_binding=True,
        ),
        ColumnSpec(
            "scope",
            "VARCHAR",
            classification=classification,
            is_source_binding=True,
        ),
    )


def _finality_column(
    *,
    classification: PublicDataClassification = PublicDataClassification.PUBLIC_LEDGER,
) -> ColumnSpec:
    return ColumnSpec(
        FINALITY_BINDING_COLUMN,
        "VARCHAR",
        classification=classification,
        is_finality_binding=True,
        description="Portable Finality enum value",
    )


def _ledger_position_columns(
    *,
    classification: PublicDataClassification = PublicDataClassification.PUBLIC_LEDGER,
) -> tuple[ColumnSpec, ...]:
    return (
        ColumnSpec(
            "ledger_sequence",
            "BIGINT",
            nullable=True,
            classification=classification,
        ),
        ColumnSpec(
            "ledger_hash",
            "VARCHAR",
            nullable=True,
            classification=classification,
        ),
        ColumnSpec(
            "transaction_index",
            "INTEGER",
            nullable=True,
            classification=classification,
        ),
        ColumnSpec(
            "event_index",
            "INTEGER",
            nullable=True,
            classification=classification,
        ),
    )


def _fact_envelope_columns() -> tuple[ColumnSpec, ...]:
    return (
        ColumnSpec("record_id", "VARCHAR", classification=PublicDataClassification.PUBLIC_LEDGER),
        ColumnSpec(
            "schema_version",
            "VARCHAR",
            classification=PublicDataClassification.OPERATIONAL,
        ),
        ColumnSpec(
            "record_type",
            "VARCHAR",
            classification=PublicDataClassification.PUBLIC_LEDGER,
        ),
        *_chain_binding_columns(),
        *_source_binding_columns(),
        ColumnSpec(
            "request_id",
            "VARCHAR",
            classification=PublicDataClassification.OPERATIONAL,
            description="Observation request id (not a secret)",
        ),
        ColumnSpec(
            "observed_at",
            "VARCHAR",
            classification=PublicDataClassification.OPERATIONAL,
            description="UTC ISO-8601 timestamp string",
        ),
        _finality_column(),
        *_ledger_position_columns(),
        ColumnSpec(
            "raw_object_ref_id",
            "VARCHAR",
            nullable=True,
            classification=PublicDataClassification.CONTENT_REF,
            description="Optional FK into encrypted_object_refs (digest/CID only)",
        ),
    )


def _amount_columns(prefix: str = "amount") -> tuple[ColumnSpec, ...]:
    base = f"{prefix}_base_units"
    decimals = f"{prefix}_decimals"
    return (
        ColumnSpec(
            base,
            "VARCHAR",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            is_amount_base_units=True,
            description="Exact signed base-unit integer string (no float)",
        ),
        ColumnSpec(
            decimals,
            "INTEGER",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            is_amount_decimals=True,
            description="Display precision 0..255",
        ),
    )


# ---------------------------------------------------------------------------
# Table registry
# ---------------------------------------------------------------------------


def _build_table_specs() -> Mapping[str, TableSpec]:
    specs: list[TableSpec] = [
        TableSpec(
            name="chains",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Network and genesis-bound chain identity",
            primary_key=("chain_ref_id",),
            columns=(
                ColumnSpec("chain_ref_id", "VARCHAR", is_chain_binding=True),
                ColumnSpec("schema_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("chain_namespace", "VARCHAR", is_chain_binding=True),
                ColumnSpec("network", "VARCHAR", is_chain_binding=True),
                ColumnSpec("chain_id", "VARCHAR", is_chain_binding=True),
                ColumnSpec("genesis_hash", "VARCHAR", is_chain_binding=True),
            ),
        ),
        TableSpec(
            name="ingestion_sources",
            classification=PublicDataClassification.OPERATIONAL,
            description="Provider/scope identity for ledger observations",
            primary_key=("source_id",),
            columns=(
                ColumnSpec("source_id", "VARCHAR", is_source_binding=True, classification=PublicDataClassification.OPERATIONAL),
                *_chain_binding_columns(classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("provider", "VARCHAR", is_source_binding=True, classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("provider_kind", "VARCHAR", is_source_binding=True, classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("scope", "VARCHAR", is_source_binding=True, classification=PublicDataClassification.OPERATIONAL),
            ),
        ),
        TableSpec(
            name="accounts",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Canonical account/address identity on one chain",
            primary_key=("account_id",),
            columns=(
                ColumnSpec("account_id", "VARCHAR"),
                ColumnSpec("schema_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                *_chain_binding_columns(),
                ColumnSpec("address", "VARCHAR"),
                ColumnSpec("kind", "VARCHAR"),
            ),
        ),
        TableSpec(
            name="assets",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Native or issued asset identity with display precision",
            primary_key=("asset_id",),
            columns=(
                ColumnSpec("asset_id", "VARCHAR"),
                ColumnSpec("schema_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                *_chain_binding_columns(),
                ColumnSpec("asset_namespace", "VARCHAR"),
                ColumnSpec("asset_reference", "VARCHAR"),
                ColumnSpec(
                    "decimals",
                    "INTEGER",
                    is_amount_decimals=True,
                    description="Asset display precision (not a float amount)",
                ),
                ColumnSpec("kind", "VARCHAR"),
                ColumnSpec("symbol", "VARCHAR", nullable=True),
            ),
        ),
        TableSpec(
            name="blocks",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Normalized block / ledger-header observations",
            primary_key=("record_id",),
            requires_fact_bindings=True,
            columns=(
                *_fact_envelope_columns(),
                ColumnSpec("block_hash", "VARCHAR"),
                ColumnSpec("parent_hash", "VARCHAR", nullable=True),
                ColumnSpec("block_time", "VARCHAR", nullable=True),
                ColumnSpec("transaction_count", "INTEGER", nullable=True),
            ),
        ),
        TableSpec(
            name="transactions",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Normalized transaction observations",
            primary_key=("record_id",),
            requires_fact_bindings=True,
            columns=(
                *_fact_envelope_columns(),
                ColumnSpec("transaction_hash", "VARCHAR"),
                ColumnSpec("status", "VARCHAR"),
                ColumnSpec(
                    "participant_account_ids",
                    "VARCHAR",
                    nullable=True,
                    description="JSON array of account_id values",
                ),
                *_amount_columns("fee"),
                # fee columns are optional at the row level; nullability applied below
                ColumnSpec("block_time", "VARCHAR", nullable=True),
            ),
        ),
        TableSpec(
            name="transfers",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Normalized asset transfer legs",
            primary_key=("record_id",),
            requires_fact_bindings=True,
            columns=(
                *_fact_envelope_columns(),
                ColumnSpec("transaction_hash", "VARCHAR"),
                ColumnSpec("transfer_index", "INTEGER"),
                ColumnSpec("asset_id", "VARCHAR"),
                *_amount_columns("amount"),
                ColumnSpec("source_account_id", "VARCHAR", nullable=True),
                ColumnSpec("destination_account_id", "VARCHAR", nullable=True),
                ColumnSpec("transfer_kind", "VARCHAR"),
            ),
        ),
        TableSpec(
            name="utxos",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Normalized UTXO outputs",
            primary_key=("record_id",),
            requires_fact_bindings=True,
            columns=(
                *_fact_envelope_columns(),
                ColumnSpec("transaction_hash", "VARCHAR"),
                ColumnSpec("output_index", "INTEGER"),
                ColumnSpec("asset_id", "VARCHAR"),
                *_amount_columns("amount"),
                ColumnSpec("owner_account_id", "VARCHAR", nullable=True),
                ColumnSpec("spent_by_transaction_hash", "VARCHAR", nullable=True),
            ),
        ),
        TableSpec(
            name="token_accounts",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Normalized SPL-style token account balances",
            primary_key=("record_id",),
            requires_fact_bindings=True,
            columns=(
                *_fact_envelope_columns(),
                ColumnSpec("token_account_id", "VARCHAR"),
                ColumnSpec("owner_account_id", "VARCHAR", nullable=True),
                ColumnSpec("asset_id", "VARCHAR"),
                *_amount_columns("amount"),
            ),
        ),
        TableSpec(
            name="contract_events",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Normalized contract/log events (data body via content ref)",
            primary_key=("record_id",),
            requires_fact_bindings=True,
            columns=(
                *_fact_envelope_columns(),
                ColumnSpec("transaction_hash", "VARCHAR"),
                # event_index is carried on the ledger-position envelope columns.
                ColumnSpec("contract_event_index", "INTEGER"),
                ColumnSpec("contract_account_id", "VARCHAR"),
                ColumnSpec("event_signature", "VARCHAR", nullable=True),
                ColumnSpec(
                    "topics_json",
                    "VARCHAR",
                    nullable=True,
                    description="JSON array of topic hashes",
                ),
                ColumnSpec(
                    "data_object_ref_id",
                    "VARCHAR",
                    nullable=True,
                    classification=PublicDataClassification.CONTENT_REF,
                    description="CID/digest pointer for event data bytes",
                ),
            ),
        ),
        TableSpec(
            name="cursors",
            classification=PublicDataClassification.OPERATIONAL,
            description="Hash-anchored ledger scan cursors",
            primary_key=("cursor_id",),
            requires_fact_bindings=True,
            columns=(
                ColumnSpec("cursor_id", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("schema_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                *_chain_binding_columns(classification=PublicDataClassification.OPERATIONAL),
                *_source_binding_columns(),
                _finality_column(classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("normalized_schema_major", "INTEGER", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("normalizer_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("revision", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                *_ledger_position_columns(classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec(
                    "continuation_token_present",
                    "BOOLEAN",
                    classification=PublicDataClassification.OPERATIONAL,
                    description="Whether a provider pagination token exists (value omitted from query surface)",
                ),
            ),
        ),
        TableSpec(
            name="checkpoints",
            classification=PublicDataClassification.OPERATIONAL,
            description="CAS hash-anchored durable checkpoints",
            primary_key=("checkpoint_id",),
            requires_fact_bindings=True,
            columns=(
                ColumnSpec("checkpoint_id", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("schema_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                *_chain_binding_columns(classification=PublicDataClassification.OPERATIONAL),
                *_source_binding_columns(),
                _finality_column(classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("normalized_schema_major", "INTEGER", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("normalizer_version", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("revision", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("anchor_sequence", "BIGINT", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("anchor_block_hash", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("safety_depth", "INTEGER", classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec("sink_commit_id", "VARCHAR", nullable=True, classification=PublicDataClassification.OPERATIONAL),
                ColumnSpec(
                    "history_json",
                    "VARCHAR",
                    classification=PublicDataClassification.OPERATIONAL,
                    description="JSON array of {sequence,block_hash} anchors",
                ),
                ColumnSpec(
                    "continuation_token_present",
                    "BOOLEAN",
                    classification=PublicDataClassification.OPERATIONAL,
                ),
            ),
        ),
        TableSpec(
            name="finality_transitions",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Append-only finality state changes for ledger records",
            primary_key=("transition_id",),
            requires_fact_bindings=True,
            columns=(
                ColumnSpec("transition_id", "VARCHAR"),
                *_chain_binding_columns(),
                *_source_binding_columns(),
                _finality_column(),
                ColumnSpec("record_id", "VARCHAR"),
                ColumnSpec("prior_finality", "VARCHAR"),
                ColumnSpec("confirmations", "INTEGER", nullable=True),
                ColumnSpec("head_sequence", "BIGINT", nullable=True),
                ColumnSpec("record_sequence", "BIGINT", nullable=True),
                ColumnSpec("reason", "VARCHAR", nullable=True),
                ColumnSpec("observed_at", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
            ),
        ),
        TableSpec(
            name="reorgs",
            classification=PublicDataClassification.PUBLIC_LEDGER,
            description="Retained reorganization decisions and orphan lineage",
            primary_key=("reorg_id",),
            requires_fact_bindings=True,
            columns=(
                ColumnSpec("reorg_id", "VARCHAR"),
                *_chain_binding_columns(),
                *_source_binding_columns(),
                _finality_column(),
                ColumnSpec("kind", "VARCHAR"),
                ColumnSpec("checkpoint_sequence", "BIGINT"),
                ColumnSpec("checkpoint_block_hash", "VARCHAR"),
                ColumnSpec("observed_sequence", "BIGINT"),
                ColumnSpec("observed_block_hash", "VARCHAR"),
                ColumnSpec("ancestor_sequence", "BIGINT", nullable=True),
                ColumnSpec("ancestor_block_hash", "VARCHAR", nullable=True),
                ColumnSpec("rewind_sequence", "BIGINT", nullable=True),
                ColumnSpec("review_required", "BOOLEAN"),
                ColumnSpec("reason", "VARCHAR", nullable=True),
                ColumnSpec(
                    "orphaned_anchors_json",
                    "VARCHAR",
                    classification=PublicDataClassification.OPERATIONAL,
                ),
                ColumnSpec(
                    "correction_record_ids_json",
                    "VARCHAR",
                    nullable=True,
                    classification=PublicDataClassification.OPERATIONAL,
                ),
                ColumnSpec("observed_at", "VARCHAR", classification=PublicDataClassification.OPERATIONAL),
            ),
        ),
        TableSpec(
            name="encrypted_object_refs",
            classification=PublicDataClassification.CONTENT_REF,
            description="Content-addressed refs to encrypted/raw objects (no bodies)",
            primary_key=("ref_id",),
            columns=(
                ColumnSpec(
                    "ref_id",
                    "VARCHAR",
                    classification=PublicDataClassification.CONTENT_REF,
                ),
                *_chain_binding_columns(classification=PublicDataClassification.CONTENT_REF),
                ColumnSpec(
                    "source_id",
                    "VARCHAR",
                    nullable=True,
                    classification=PublicDataClassification.CONTENT_REF,
                    is_source_binding=True,
                ),
                ColumnSpec(
                    "digest",
                    "VARCHAR",
                    nullable=True,
                    classification=PublicDataClassification.CONTENT_REF,
                ),
                ColumnSpec(
                    "cid",
                    "VARCHAR",
                    nullable=True,
                    classification=PublicDataClassification.CONTENT_REF,
                ),
                ColumnSpec(
                    "media_type",
                    "VARCHAR",
                    classification=PublicDataClassification.CONTENT_REF,
                ),
                ColumnSpec(
                    "byte_length",
                    "BIGINT",
                    nullable=True,
                    classification=PublicDataClassification.CONTENT_REF,
                ),
                ColumnSpec(
                    "encryption_policy",
                    "VARCHAR",
                    classification=PublicDataClassification.CONTENT_REF,
                    description="omitted | referenced | separately_encrypted",
                ),
            ),
        ),
    ]

    # Make fee amount columns nullable on transactions (fees are optional).
    adjusted: dict[str, TableSpec] = {}
    for spec in specs:
        if spec.name == "transactions":
            columns = []
            for column in spec.columns:
                if column.name in {"fee_base_units", "fee_decimals"}:
                    columns.append(
                        ColumnSpec(
                            name=column.name,
                            sql_type=column.sql_type,
                            nullable=True,
                            classification=column.classification,
                            description=column.description,
                            is_amount_base_units=column.is_amount_base_units,
                            is_amount_decimals=column.is_amount_decimals,
                        )
                    )
                else:
                    columns.append(column)
            spec = TableSpec(
                name=spec.name,
                columns=tuple(columns),
                primary_key=spec.primary_key,
                classification=spec.classification,
                description=spec.description,
                requires_fact_bindings=spec.requires_fact_bindings,
            )
        adjusted[spec.name] = spec
    return MappingProxyType(adjusted)


WALLET_TABLE_SPECS: Final[Mapping[str, TableSpec]] = _build_table_specs()


def wallet_catalog_ddl() -> str:
    """Return CREATE TABLE DDL for every wallet catalog table."""

    parts = [WALLET_TABLE_SPECS[name].create_table_sql() for name in WALLET_CATALOG_TABLES]
    return "\n\n".join(parts)


WALLET_CATALOG_DDL: Final[str] = wallet_catalog_ddl()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WalletSchemaError(ValueError):
    """Raised when a wallet schema invariant or projection is invalid."""


# ---------------------------------------------------------------------------
# Amount helpers (no float coercion)
# ---------------------------------------------------------------------------


def exact_amount_columns(amount: ExactAmount, *, prefix: str = "amount") -> dict[str, Any]:
    """Project an :class:`ExactAmount` to VARCHAR base-units + integer decimals.

    Raises if ``base_units`` is not a canonical decimal integer string.  Never
    accepts or emits ``float``.
    """

    if not isinstance(amount, ExactAmount):
        raise WalletSchemaError("amount must be ExactAmount")
    if isinstance(amount.base_units, float):  # pragma: no cover - ExactAmount rejects
        raise WalletSchemaError("float monetary amounts are forbidden")
    if not isinstance(amount.base_units, str) or not _DECIMAL_INTEGER.fullmatch(
        amount.base_units
    ):
        raise WalletSchemaError(
            "amount base_units must be a canonical decimal integer string"
        )
    if isinstance(amount.decimals, float):
        raise WalletSchemaError("amount decimals must not be a float")
    if isinstance(amount.decimals, bool) or not isinstance(amount.decimals, int):
        raise WalletSchemaError("amount decimals must be an integer")
    if amount.decimals < 0 or amount.decimals > 255:
        raise WalletSchemaError("amount decimals out of range")
    return {
        f"{prefix}_base_units": amount.base_units,
        f"{prefix}_decimals": amount.decimals,
    }


def assert_not_float_amount(value: Any, *, field_name: str = "amount") -> None:
    """Reject float-typed monetary inputs before projection."""

    if isinstance(value, float):
        raise WalletSchemaError(
            f"{field_name} must not be a binary float; use ExactAmount strings"
        )
    if isinstance(value, ExactAmount):
        if isinstance(value.base_units, float):
            raise WalletSchemaError(f"{field_name} base_units must not be float")
        return
    if isinstance(value, Mapping):
        base = value.get("base_units")
        if isinstance(base, float):
            raise WalletSchemaError(f"{field_name} base_units must not be float")
        decimals = value.get("decimals")
        if isinstance(decimals, float):
            raise WalletSchemaError(f"{field_name} decimals must not be float")


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def chain_row(chain: ChainRef) -> dict[str, Any]:
    """Project a :class:`ChainRef` into the ``chains`` table."""

    if not isinstance(chain, ChainRef):
        raise WalletSchemaError("chain must be a ChainRef")
    return {
        "chain_ref_id": chain.chain_ref_id,
        "schema_version": chain.schema_version,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
    }


def source_id_for(chain: ChainRef, provenance: Provenance) -> str:
    """Stable ingestion-source identity (provider/scope on one chain)."""

    if not isinstance(chain, ChainRef):
        raise WalletSchemaError("chain must be a ChainRef")
    if not isinstance(provenance, Provenance):
        raise WalletSchemaError("provenance must be Provenance")
    return deterministic_id(
        "ingestion-source",
        {
            "chain": chain.identity_dict(),
            "provider": provenance.provider,
            "provider_kind": provenance.provider_kind,
            "scope": provenance.scope,
        },
    )


def ingestion_source_row(chain: ChainRef, provenance: Provenance) -> dict[str, Any]:
    """Project provider/scope into ``ingestion_sources`` (no secrets/raw bodies)."""

    return {
        "source_id": source_id_for(chain, provenance),
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "scope": provenance.scope,
    }


def account_row(account: AccountRef) -> dict[str, Any]:
    if not isinstance(account, AccountRef):
        raise WalletSchemaError("account must be an AccountRef")
    return {
        "account_id": account.account_id,
        "schema_version": account.schema_version,
        "chain_ref_id": account.chain.chain_ref_id,
        "chain_namespace": account.chain.namespace,
        "network": account.chain.network,
        "chain_id": account.chain.chain_id,
        "genesis_hash": account.chain.genesis_hash,
        "address": account.address,
        "kind": account.kind.value,
    }


def asset_row(asset: AssetRef) -> dict[str, Any]:
    if not isinstance(asset, AssetRef):
        raise WalletSchemaError("asset must be an AssetRef")
    return {
        "asset_id": asset.asset_id,
        "schema_version": asset.schema_version,
        "chain_ref_id": asset.chain.chain_ref_id,
        "chain_namespace": asset.chain.namespace,
        "network": asset.chain.network,
        "chain_id": asset.chain.chain_id,
        "genesis_hash": asset.chain.genesis_hash,
        "asset_namespace": asset.asset_namespace,
        "asset_reference": asset.asset_reference,
        "decimals": asset.decimals,
        "kind": asset.kind.value,
        "symbol": asset.symbol,
    }


def encrypted_object_ref_row(
    *,
    chain: ChainRef,
    raw: RawPayloadRef,
    source_id: str | None = None,
    encryption_policy: str = "referenced",
) -> dict[str, Any]:
    """Project a content reference only — never raw payload bytes."""

    if not isinstance(chain, ChainRef):
        raise WalletSchemaError("chain must be a ChainRef")
    if not isinstance(raw, RawPayloadRef):
        raise WalletSchemaError("raw must be a RawPayloadRef")
    if raw.digest is None and raw.cid is None:
        raise WalletSchemaError("encrypted object ref requires digest or cid")
    ref_id = deterministic_id(
        "encrypted-object-ref",
        {
            "chain": chain.identity_dict(),
            "digest": raw.digest,
            "cid": raw.cid,
            "media_type": raw.media_type,
            "byte_length": raw.byte_length,
        },
    )
    return {
        "ref_id": ref_id,
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
        "source_id": source_id,
        "digest": raw.digest,
        "cid": raw.cid,
        "media_type": raw.media_type,
        "byte_length": raw.byte_length,
        "encryption_policy": encryption_policy,
    }


def _position_fields(record: LedgerRecord) -> dict[str, Any]:
    position = record.ledger_position
    return {
        "ledger_sequence": position.sequence,
        "ledger_hash": position.hash,
        "transaction_index": position.transaction_index,
        "event_index": position.event_index,
    }


def _fact_envelope(record: LedgerRecord) -> dict[str, Any]:
    if not isinstance(record, LedgerRecord):
        raise WalletSchemaError("record must be a LedgerRecord")
    if not isinstance(record.finality, Finality):
        raise WalletSchemaError("record finality must be a Finality value")
    provenance = record.provenance
    source_id = source_id_for(record.chain, provenance)
    raw_ref_id = None
    if provenance.raw_payload is not None:
        raw_ref_id = encrypted_object_ref_row(
            chain=record.chain,
            raw=provenance.raw_payload,
            source_id=source_id,
            encryption_policy="referenced",
        )["ref_id"]
    return {
        "record_id": record.record_id,
        "schema_version": record.schema_version,
        "record_type": record.record_type,
        "chain_ref_id": record.chain.chain_ref_id,
        "chain_namespace": record.chain.namespace,
        "network": record.chain.network,
        "chain_id": record.chain.chain_id,
        "genesis_hash": record.chain.genesis_hash,
        "source_id": source_id,
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "scope": provenance.scope,
        "request_id": provenance.request_id,
        "observed_at": format_datetime(provenance.observed_at),
        "finality": record.finality.value,
        **_position_fields(record),
        "raw_object_ref_id": raw_ref_id,
    }


def assert_fact_bindings(row: Mapping[str, Any], *, table: str) -> None:
    """Ensure a projected fact row binds chain, source, and finality."""

    if table not in WALLET_FACT_TABLES:
        raise WalletSchemaError(f"{table!r} is not a fact table")
    for column in FACT_BINDING_COLUMNS:
        if column not in row:
            raise WalletSchemaError(
                f"row for {table!r} missing binding column {column!r}"
            )
        value = row[column]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise WalletSchemaError(
                f"row for {table!r} has empty binding column {column!r}"
            )
    finality = row[FINALITY_BINDING_COLUMN]
    if isinstance(finality, Finality):
        finality = finality.value
    if finality not in {state.value for state in Finality}:
        raise WalletSchemaError(
            f"row for {table!r} has unknown finality {finality!r}"
        )


def _assert_row_columns(table: str, row: Mapping[str, Any]) -> None:
    spec = WALLET_TABLE_SPECS[table]
    allowed = set(spec.column_names)
    unknown = set(row) - allowed
    if unknown:
        raise WalletSchemaError(
            f"row for {table!r} has unknown columns: {sorted(unknown)}"
        )
    for name in row:
        if name.casefold() in FORBIDDEN_QUERY_COLUMN_NAMES:
            raise WalletSchemaError(
                f"forbidden query column {name!r} on table {table!r}"
            )
    for column in spec.columns:
        if column.is_amount_base_units and column.name in row and row[column.name] is not None:
            value = row[column.name]
            if isinstance(value, float):
                raise WalletSchemaError(
                    f"float amount on {table}.{column.name} is forbidden"
                )
            if not isinstance(value, str) or not _DECIMAL_INTEGER.fullmatch(value):
                raise WalletSchemaError(
                    f"{table}.{column.name} must be a decimal integer string"
                )


# ---------------------------------------------------------------------------
# Fact projectors
# ---------------------------------------------------------------------------


def block_row(record: BlockRecord) -> dict[str, Any]:
    if not isinstance(record, BlockRecord):
        raise WalletSchemaError("record must be a BlockRecord")
    row = {
        **_fact_envelope(record),
        "block_hash": record.block_hash,
        "parent_hash": record.parent_hash,
        "block_time": (
            format_datetime(record.block_time) if record.block_time is not None else None
        ),
        "transaction_count": record.transaction_count,
    }
    assert_fact_bindings(row, table="blocks")
    _assert_row_columns("blocks", row)
    return row


def transaction_row(record: TransactionRecord) -> dict[str, Any]:
    if not isinstance(record, TransactionRecord):
        raise WalletSchemaError("record must be a TransactionRecord")
    fee_base = None
    fee_decimals = None
    if record.fee is not None:
        assert_not_float_amount(record.fee, field_name="fee")
        fee_cols = exact_amount_columns(record.fee, prefix="fee")
        fee_base = fee_cols["fee_base_units"]
        fee_decimals = fee_cols["fee_decimals"]
    participant_ids = [item.account_id for item in record.participants]
    row = {
        **_fact_envelope(record),
        "transaction_hash": record.transaction_hash,
        "status": record.status.value,
        "participant_account_ids": json.dumps(participant_ids, separators=(",", ":")),
        "fee_base_units": fee_base,
        "fee_decimals": fee_decimals,
        "block_time": (
            format_datetime(record.block_time) if record.block_time is not None else None
        ),
    }
    assert_fact_bindings(row, table="transactions")
    _assert_row_columns("transactions", row)
    return row


def transfer_row(record: TransferRecord) -> dict[str, Any]:
    if not isinstance(record, TransferRecord):
        raise WalletSchemaError("record must be a TransferRecord")
    assert_not_float_amount(record.amount, field_name="amount")
    amount_cols = exact_amount_columns(record.amount, prefix="amount")
    row = {
        **_fact_envelope(record),
        "transaction_hash": record.transaction_hash,
        "transfer_index": record.transfer_index,
        "asset_id": record.asset.asset_id,
        **amount_cols,
        "source_account_id": (
            record.source_account.account_id if record.source_account else None
        ),
        "destination_account_id": (
            record.destination_account.account_id
            if record.destination_account
            else None
        ),
        "transfer_kind": record.transfer_kind.value,
    }
    assert_fact_bindings(row, table="transfers")
    _assert_row_columns("transfers", row)
    return row


def utxo_row(record: UTXORecord) -> dict[str, Any]:
    if not isinstance(record, UTXORecord):
        raise WalletSchemaError("record must be a UTXORecord")
    assert_not_float_amount(record.amount, field_name="amount")
    amount_cols = exact_amount_columns(record.amount, prefix="amount")
    row = {
        **_fact_envelope(record),
        "transaction_hash": record.transaction_hash,
        "output_index": record.output_index,
        "asset_id": record.asset.asset_id,
        **amount_cols,
        "owner_account_id": record.owner.account_id if record.owner else None,
        "spent_by_transaction_hash": record.spent_by_transaction_hash,
    }
    assert_fact_bindings(row, table="utxos")
    _assert_row_columns("utxos", row)
    return row


def token_account_row(record: TokenAccountRecord) -> dict[str, Any]:
    if not isinstance(record, TokenAccountRecord):
        raise WalletSchemaError("record must be a TokenAccountRecord")
    assert_not_float_amount(record.amount, field_name="amount")
    amount_cols = exact_amount_columns(record.amount, prefix="amount")
    row = {
        **_fact_envelope(record),
        "token_account_id": record.token_account.account_id,
        "owner_account_id": record.owner.account_id if record.owner else None,
        "asset_id": record.asset.asset_id,
        **amount_cols,
    }
    assert_fact_bindings(row, table="token_accounts")
    _assert_row_columns("token_accounts", row)
    return row


def contract_event_row(record: ContractEventRecord) -> dict[str, Any]:
    if not isinstance(record, ContractEventRecord):
        raise WalletSchemaError("record must be a ContractEventRecord")
    data_ref_id = None
    if record.data_ref is not None:
        source_id = source_id_for(record.chain, record.provenance)
        data_ref_id = encrypted_object_ref_row(
            chain=record.chain,
            raw=record.data_ref,
            source_id=source_id,
            encryption_policy="referenced",
        )["ref_id"]
    row = {
        **_fact_envelope(record),
        "transaction_hash": record.transaction_hash,
        "contract_event_index": record.event_index,
        "contract_account_id": record.contract.account_id,
        "event_signature": record.event_signature,
        "topics_json": json.dumps(list(record.topics), separators=(",", ":")),
        "data_object_ref_id": data_ref_id,
    }
    assert_fact_bindings(row, table="contract_events")
    _assert_row_columns("contract_events", row)
    return row


def cursor_row(
    cursor: LedgerCursor,
    *,
    finality: Finality = Finality.OBSERVED,
) -> dict[str, Any]:
    """Project a :class:`LedgerCursor` with required fact bindings.

    Cursors are operational; ``finality`` defaults to ``observed`` for the
    scan position and must still be bound on every row.
    """

    if not isinstance(cursor, LedgerCursor):
        raise WalletSchemaError("cursor must be a LedgerCursor")
    if not isinstance(finality, Finality):
        raise WalletSchemaError("finality must be a Finality value")
    source_id = deterministic_id(
        "ingestion-source",
        {
            "chain": cursor.chain.identity_dict(),
            "provider": cursor.provider,
            "provider_kind": "cursor",
            "scope": cursor.scope,
        },
    )
    row = {
        "cursor_id": cursor.cursor_id,
        "schema_version": cursor.schema_version,
        "chain_ref_id": cursor.chain.chain_ref_id,
        "chain_namespace": cursor.chain.namespace,
        "network": cursor.chain.network,
        "chain_id": cursor.chain.chain_id,
        "genesis_hash": cursor.chain.genesis_hash,
        "source_id": source_id,
        "provider": cursor.provider,
        "provider_kind": "cursor",
        "scope": cursor.scope,
        "finality": finality.value,
        "normalized_schema_major": cursor.normalized_schema_major,
        "normalizer_version": cursor.normalizer_version,
        "revision": cursor.revision,
        "ledger_sequence": cursor.position.sequence,
        "ledger_hash": cursor.position.hash,
        "transaction_index": cursor.position.transaction_index,
        "event_index": cursor.position.event_index,
        # Intentionally omit the token value from the query-visible table.
        "continuation_token_present": cursor.continuation_token is not None,
    }
    assert_fact_bindings(row, table="cursors")
    _assert_row_columns("cursors", row)
    ensure_secret_safe(
        {k: v for k, v in row.items() if k != "continuation_token_present"}
    )
    return row


def checkpoint_row(
    checkpoint: CheckpointRecord,
    *,
    finality: Finality = Finality.OBSERVED,
) -> dict[str, Any]:
    """Project a checkpoint record; continuation token values are not stored."""

    if not isinstance(checkpoint, CheckpointRecord):
        raise WalletSchemaError("checkpoint must be a CheckpointRecord")
    if not isinstance(finality, Finality):
        raise WalletSchemaError("finality must be a Finality value")
    identity = checkpoint.identity
    chain: ChainRef = identity.chain
    source_id = deterministic_id(
        "ingestion-source",
        {
            "chain": chain.identity_dict(),
            "provider": identity.provider,
            "provider_kind": "checkpoint",
            "scope": identity.scope,
        },
    )
    history = [
        {"sequence": anchor.sequence, "block_hash": anchor.block_hash}
        for anchor in checkpoint.history
    ]
    row = {
        "checkpoint_id": checkpoint.checkpoint_id,
        "schema_version": checkpoint.schema_version,
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
        "source_id": source_id,
        "provider": identity.provider,
        "provider_kind": "checkpoint",
        "scope": identity.scope,
        "finality": finality.value,
        "normalized_schema_major": identity.normalized_schema_major,
        "normalizer_version": identity.normalizer_version,
        "revision": checkpoint.revision,
        "anchor_sequence": checkpoint.anchor.sequence,
        "anchor_block_hash": checkpoint.anchor.block_hash,
        "safety_depth": checkpoint.safety_depth,
        "sink_commit_id": checkpoint.sink_commit_id,
        "history_json": json.dumps(history, separators=(",", ":")),
        "continuation_token_present": checkpoint.continuation_token is not None,
    }
    assert_fact_bindings(row, table="checkpoints")
    _assert_row_columns("checkpoints", row)
    return row


def finality_transition_row(
    *,
    chain: ChainRef,
    provenance: Provenance,
    record_id: str,
    prior_finality: Finality,
    new_finality: Finality,
    confirmations: int | None = None,
    head_sequence: int | None = None,
    record_sequence: int | None = None,
    reason: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(chain, ChainRef):
        raise WalletSchemaError("chain must be a ChainRef")
    if not isinstance(provenance, Provenance):
        raise WalletSchemaError("provenance must be Provenance")
    if not isinstance(prior_finality, Finality) or not isinstance(new_finality, Finality):
        raise WalletSchemaError("finality values must be Finality enums")
    if not record_id or not str(record_id).strip():
        raise WalletSchemaError("record_id must not be empty")
    source_id = source_id_for(chain, provenance)
    transition_id = deterministic_id(
        "finality-transition",
        {
            "chain": chain.identity_dict(),
            "record_id": record_id,
            "prior_finality": prior_finality.value,
            "new_finality": new_finality.value,
            "request_id": provenance.request_id,
            "observed_at": observed_at or format_datetime(provenance.observed_at),
        },
    )
    row = {
        "transition_id": transition_id,
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
        "source_id": source_id,
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "scope": provenance.scope,
        "finality": new_finality.value,
        "record_id": record_id,
        "prior_finality": prior_finality.value,
        "confirmations": confirmations,
        "head_sequence": head_sequence,
        "record_sequence": record_sequence,
        "reason": reason,
        "observed_at": observed_at or format_datetime(provenance.observed_at),
    }
    assert_fact_bindings(row, table="finality_transitions")
    _assert_row_columns("finality_transitions", row)
    return row


def reorg_row(
    decision: Any,
    *,
    chain: ChainRef,
    provenance: Provenance,
    finality: Finality = Finality.ORPHANED,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(chain, ChainRef):
        raise WalletSchemaError("chain must be a ChainRef")
    if not isinstance(provenance, Provenance):
        raise WalletSchemaError("provenance must be Provenance")
    if not isinstance(finality, Finality):
        raise WalletSchemaError("finality must be a Finality value")
    kind = decision.kind.value if hasattr(decision.kind, "value") else str(decision.kind)
    source_id = source_id_for(chain, provenance)
    orphaned = [
        {"sequence": a.sequence, "block_hash": a.block_hash}
        for a in decision.orphaned_anchors
    ]
    correction_ids = [c.record_id for c in getattr(decision, "corrections", ()) or ()]
    ancestor = decision.common_ancestor
    reorg_id = deterministic_id(
        "reorg",
        {
            "chain": chain.identity_dict(),
            "kind": kind,
            "checkpoint": decision.checkpoint_anchor.to_dict(),
            "observed": decision.observed_anchor.to_dict(),
            "request_id": provenance.request_id,
        },
    )
    row = {
        "reorg_id": reorg_id,
        "chain_ref_id": chain.chain_ref_id,
        "chain_namespace": chain.namespace,
        "network": chain.network,
        "chain_id": chain.chain_id,
        "genesis_hash": chain.genesis_hash,
        "source_id": source_id,
        "provider": provenance.provider,
        "provider_kind": provenance.provider_kind,
        "scope": provenance.scope,
        "finality": finality.value,
        "kind": kind,
        "checkpoint_sequence": decision.checkpoint_anchor.sequence,
        "checkpoint_block_hash": decision.checkpoint_anchor.block_hash,
        "observed_sequence": decision.observed_anchor.sequence,
        "observed_block_hash": decision.observed_anchor.block_hash,
        "ancestor_sequence": None if ancestor is None else ancestor.sequence,
        "ancestor_block_hash": None if ancestor is None else ancestor.block_hash,
        "rewind_sequence": decision.rewind_sequence,
        "review_required": bool(decision.review_required),
        "reason": decision.reason or None,
        "orphaned_anchors_json": json.dumps(orphaned, separators=(",", ":")),
        "correction_record_ids_json": (
            json.dumps(correction_ids, separators=(",", ":")) if correction_ids else None
        ),
        "observed_at": observed_at or format_datetime(provenance.observed_at),
    }
    assert_fact_bindings(row, table="reorgs")
    _assert_row_columns("reorgs", row)
    return row


_RECORD_PROJECTORS: Mapping[type, tuple[str, Any]] = MappingProxyType(
    {
        BlockRecord: ("blocks", block_row),
        TransactionRecord: ("transactions", transaction_row),
        TransferRecord: ("transfers", transfer_row),
        UTXORecord: ("utxos", utxo_row),
        TokenAccountRecord: ("token_accounts", token_account_row),
        ContractEventRecord: ("contract_events", contract_event_row),
    }
)


def project_ledger_record(record: LedgerRecord) -> tuple[str, dict[str, Any]]:
    """Return ``(table_name, row)`` for a normalized ledger record."""

    for cls, (table, projector) in _RECORD_PROJECTORS.items():
        if isinstance(record, cls):
            return table, projector(record)
    raise WalletSchemaError(
        f"unsupported ledger record type: {type(record).__name__}"
    )


def dimension_rows_for_record(
    record: LedgerRecord,
) -> dict[str, list[dict[str, Any]]]:
    """Collect chain/source/account/asset dimension rows implied by *record*."""

    rows: dict[str, list[dict[str, Any]]] = {
        "chains": [chain_row(record.chain)],
        "ingestion_sources": [ingestion_source_row(record.chain, record.provenance)],
        "accounts": [],
        "assets": [],
        "encrypted_object_refs": [],
    }
    if record.provenance.raw_payload is not None:
        rows["encrypted_object_refs"].append(
            encrypted_object_ref_row(
                chain=record.chain,
                raw=record.provenance.raw_payload,
                source_id=source_id_for(record.chain, record.provenance),
            )
        )

    def add_account(account: AccountRef | None) -> None:
        if account is not None:
            rows["accounts"].append(account_row(account))

    def add_asset(asset: AssetRef | None) -> None:
        if asset is not None:
            rows["assets"].append(asset_row(asset))

    if isinstance(record, TransactionRecord):
        for participant in record.participants:
            add_account(participant)
    elif isinstance(record, TransferRecord):
        add_asset(record.asset)
        add_account(record.source_account)
        add_account(record.destination_account)
    elif isinstance(record, UTXORecord):
        add_asset(record.asset)
        add_account(record.owner)
    elif isinstance(record, TokenAccountRecord):
        add_account(record.token_account)
        add_account(record.owner)
        add_asset(record.asset)
    elif isinstance(record, ContractEventRecord):
        add_account(record.contract)
        if record.data_ref is not None:
            rows["encrypted_object_refs"].append(
                encrypted_object_ref_row(
                    chain=record.chain,
                    raw=record.data_ref,
                    source_id=source_id_for(record.chain, record.provenance),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Schema validation / install
# ---------------------------------------------------------------------------


def iter_amount_columns() -> Iterable[tuple[str, ColumnSpec]]:
    for table_name, spec in WALLET_TABLE_SPECS.items():
        for column in spec.columns:
            if column.is_amount_base_units or column.is_amount_decimals:
                yield table_name, column


def validate_wallet_schema() -> None:
    """Fail closed if catalog invariants are violated.

    Checks:

    * catalog table set matches the control-plane plan
    * every fact table requires chain/source/finality bindings
    * amount base-unit columns are VARCHAR only
    * no forbidden secret/raw column names on any table
    * DDL contains no float amount types
    """

    if tuple(WALLET_TABLE_SPECS) != WALLET_CATALOG_TABLES and set(
        WALLET_TABLE_SPECS
    ) != set(WALLET_CATALOG_TABLES):
        # Order may differ for MappingProxyType insertion; require same set.
        missing = set(WALLET_CATALOG_TABLES) - set(WALLET_TABLE_SPECS)
        extra = set(WALLET_TABLE_SPECS) - set(WALLET_CATALOG_TABLES)
        if missing or extra:
            raise WalletSchemaError(
                f"table registry mismatch missing={sorted(missing)} extra={sorted(extra)}"
            )

    for name in WALLET_FACT_TABLES:
        spec = WALLET_TABLE_SPECS[name]
        if not spec.requires_fact_bindings:
            raise WalletSchemaError(f"fact table {name!r} must require bindings")
        present = set(spec.column_names)
        for column in FACT_BINDING_COLUMNS:
            if column not in present:
                raise WalletSchemaError(
                    f"fact table {name!r} missing binding {column!r}"
                )

    for table_name, column in iter_amount_columns():
        token = column.sql_type_token
        if column.is_amount_base_units and token in _FORBIDDEN_AMOUNT_SQL_TYPES:
            raise WalletSchemaError(
                f"{table_name}.{column.name} uses forbidden amount type {token}"
            )
        if column.is_amount_base_units and token != "VARCHAR":
            raise WalletSchemaError(
                f"{table_name}.{column.name} must be VARCHAR, got {column.sql_type}"
            )

    ddl_upper = WALLET_CATALOG_DDL.upper()
    # Detect float types used near amount column definitions.
    for table_name, column in iter_amount_columns():
        if not column.is_amount_base_units:
            continue
        if column.name.upper() not in ddl_upper:
            raise WalletSchemaError(
                f"DDL missing amount column {table_name}.{column.name}"
            )
        if any(
            f"{column.name.upper()} {bad}" in ddl_upper
            for bad in _FORBIDDEN_AMOUNT_SQL_TYPES
        ):
            raise WalletSchemaError(
                f"DDL assigns float/decimal type to {table_name}.{column.name}"
            )

    for table_name, spec in WALLET_TABLE_SPECS.items():
        for column in spec.columns:
            lowered = column.name.casefold()
            if lowered in FORBIDDEN_QUERY_COLUMN_NAMES:
                raise WalletSchemaError(
                    f"forbidden column {column.name!r} on {table_name}"
                )
            for fragment in _FORBIDDEN_COLUMN_SUBSTRINGS:
                if fragment in lowered:
                    raise WalletSchemaError(
                        f"column {table_name}.{column.name} contains "
                        f"forbidden fragment {fragment!r}"
                    )
        if not spec.is_query_visible:
            continue
        # Query-visible tables must not declare payload body columns.
        for column in spec.columns:
            if column.classification is PublicDataClassification.INTERNAL:
                raise WalletSchemaError(
                    f"query-visible table {table_name} has INTERNAL column "
                    f"{column.name}"
                )


def table_classification(table_name: str) -> PublicDataClassification:
    return WALLET_TABLE_SPECS[table_name].classification


def column_classification(table_name: str, column_name: str) -> PublicDataClassification:
    return WALLET_TABLE_SPECS[table_name].column_map()[column_name].classification


def install_wallet_schema(connection: Any) -> str:
    """Apply :data:`WALLET_CATALOG_DDL` on *connection* and return schema version.

    The connection is duckdb-like (``execute``).  Import of this module never
    opens a database; callers inject the connection.
    """

    validate_wallet_schema()
    if connection is None:
        raise WalletSchemaError("connection is required to install schema")
    execute = getattr(connection, "execute", None)
    if not callable(execute):
        raise WalletSchemaError("connection must provide execute()")
    for statement in WALLET_CATALOG_DDL.split(";"):
        sql = statement.strip()
        if sql:
            connection.execute(sql)
    return WALLET_SCHEMA_VERSION


def query_visible_column_names(table_name: str) -> tuple[str, ...]:
    """Return column names for *table_name* that may appear in queries."""

    return WALLET_TABLE_SPECS[table_name].column_names


def schema_digest_material() -> dict[str, Any]:
    """Stable description of the schema for checksums and receipts."""

    tables = []
    for name in WALLET_CATALOG_TABLES:
        spec = WALLET_TABLE_SPECS[name]
        tables.append(
            {
                "name": name,
                "classification": spec.classification.value,
                "primary_key": list(spec.primary_key),
                "requires_fact_bindings": spec.requires_fact_bindings,
                "columns": [
                    {
                        "name": column.name,
                        "sql_type": column.sql_type,
                        "nullable": column.nullable,
                        "classification": column.classification.value,
                        "is_amount_base_units": column.is_amount_base_units,
                        "is_amount_decimals": column.is_amount_decimals,
                        "is_chain_binding": column.is_chain_binding,
                        "is_source_binding": column.is_source_binding,
                        "is_finality_binding": column.is_finality_binding,
                    }
                    for column in spec.columns
                ],
            }
        )
    return {
        "schema_version": WALLET_SCHEMA_VERSION,
        "interface": WALLET_SCHEMA_INTERFACE,
        "catalog": WALLET_CATALOG_NAME,
        "ledger_schema_major": WALLET_LEDGER_SCHEMA_MAJOR,
        "tables": tables,
    }


# Validate at import so broken catalog definitions fail fast in tests/CI.
validate_wallet_schema()


__all__ = [
    "AMOUNT_BASE_UNIT_COLUMNS",
    "AMOUNT_DECIMAL_COLUMNS",
    "CHAIN_BINDING_COLUMNS",
    "FACT_BINDING_COLUMNS",
    "FINALITY_BINDING_COLUMN",
    "FORBIDDEN_QUERY_COLUMN_NAMES",
    "SOURCE_BINDING_COLUMNS",
    "WALLET_CATALOG_DDL",
    "WALLET_CATALOG_NAME",
    "WALLET_CATALOG_TABLES",
    "WALLET_DIMENSION_TABLES",
    "WALLET_FACT_TABLES",
    "WALLET_LEDGER_SCHEMA_MAJOR",
    "WALLET_QUERY_VISIBLE_TABLES",
    "WALLET_SCHEMA_INTERFACE",
    "WALLET_SCHEMA_VERSION",
    "WALLET_TABLE_SPECS",
    "ColumnSpec",
    "PublicDataClassification",
    "TableSpec",
    "WalletSchemaError",
    "account_row",
    "assert_fact_bindings",
    "assert_not_float_amount",
    "asset_row",
    "block_row",
    "chain_row",
    "checkpoint_row",
    "column_classification",
    "contract_event_row",
    "cursor_row",
    "dimension_rows_for_record",
    "encrypted_object_ref_row",
    "exact_amount_columns",
    "finality_transition_row",
    "ingestion_source_row",
    "install_wallet_schema",
    "iter_amount_columns",
    "project_ledger_record",
    "query_visible_column_names",
    "reorg_row",
    "schema_digest_material",
    "source_id_for",
    "table_classification",
    "token_account_row",
    "transaction_row",
    "transfer_row",
    "utxo_row",
    "validate_wallet_schema",
    "wallet_catalog_ddl",
]

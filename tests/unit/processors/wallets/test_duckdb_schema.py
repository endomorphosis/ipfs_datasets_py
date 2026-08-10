"""Unit tests for the privacy-safe wallet DuckDB schema (DQK-035).

Acceptance coverage:

* No float coercion of monetary amounts
* Every row binds chain/source/finality
* Secret-bearing fields and raw payloads are absent from query-visible tables
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.processors.wallets.canonical import format_datetime
from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
)
from ipfs_datasets_py.processors.wallets.duckdb_schema import (
    ColumnDataClass,
    DUCKDB_WALLET_SCHEMA_INTERFACE,
    DUCKDB_WALLET_SCHEMA_VERSION,
    FORBIDDEN_QUERY_CLASSES,
    MONETARY_AMOUNT_COLUMNS,
    QUERY_VISIBLE_CLASSES,
    ROW_BINDING_COLUMNS,
    WALLET_CATALOG_DDL,
    WALLET_CATALOG_NAME,
    WALLET_CATALOG_TABLES,
    WALLET_COLUMN_CLASSIFICATIONS,
    WalletSchemaError,
    assert_no_float_monetary_types,
    assert_no_secret_or_raw_payload_columns,
    assert_public_data_classification,
    assert_row_bindings,
    assert_wallet_schema_invariants,
    exact_amount_strings,
    iter_query_visible_columns,
    parse_wallet_catalog_ddl,
    project_block_row,
    project_checkpoint_row,
    project_contract_event_row,
    project_cursor_row,
    project_encrypted_object_ref_row,
    project_finality_transition_row,
    project_ledger_record_rows,
    project_reorg_row,
    project_token_account_row,
    project_transaction_row,
    project_transfer_row,
    project_utxo_row,
    query_visible_table_names,
    wallet_schema_descriptor,
)
from ipfs_datasets_py.processors.wallets.finality import (
    OrphanCorrection,
    ReorgDecision,
    ReorgKind,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    BlockRecord,
    ChainRef,
    ContractEventRecord,
    ExactAmount,
    Finality,
    LedgerCursor,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TokenAccountRecord,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    UTXORecord,
)


NOW = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
NOW_STR = format_datetime(NOW)
DIGEST = "sha256:" + ("ab" * 32)

# Control-plane wallet catalog (scripts/ops program ARCHITECTURE["catalogs"]["wallet"]).
CONTROL_PLANE_WALLET_TABLES = (
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


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash="0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",
    )


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        provider="fixture-rpc",
        provider_kind="json-rpc",
        request_id="request-001",
        scope="wallet:0xabc",
        observed_at=NOW,
        raw_payload=RawPayloadRef(
            digest=DIGEST,
            media_type="application/json",
            byte_length=321,
        ),
    )


@pytest.fixture
def position() -> LedgerPosition:
    return LedgerPosition(
        sequence=19_000_000,
        hash="0xblock",
        transaction_index=2,
        event_index=None,
    )


@pytest.fixture
def account(chain: ChainRef) -> AccountRef:
    return AccountRef(chain, "0xabc", AccountKind.ADDRESS)


@pytest.fixture
def asset(chain: ChainRef) -> AssetRef:
    return AssetRef(
        chain,
        asset_namespace="slip44",
        asset_reference="60",
        decimals=18,
        kind=AssetKind.NATIVE,
        symbol="ETH",
    )


# ---------------------------------------------------------------------------
# Catalog shape + control-plane alignment
# ---------------------------------------------------------------------------


def test_catalog_tables_match_control_plane() -> None:
    assert WALLET_CATALOG_TABLES == CONTROL_PLANE_WALLET_TABLES
    assert query_visible_table_names() == CONTROL_PLANE_WALLET_TABLES
    assert WALLET_CATALOG_NAME == "wallet"


def test_schema_invariants_pass() -> None:
    tables = assert_wallet_schema_invariants()
    assert set(tables) == set(WALLET_CATALOG_TABLES)
    for table in WALLET_CATALOG_TABLES:
        assert table in WALLET_CATALOG_DDL


def test_wallet_schema_descriptor_is_stable() -> None:
    descriptor = wallet_schema_descriptor()
    assert descriptor["interface"] == DUCKDB_WALLET_SCHEMA_INTERFACE
    assert descriptor["schema_version"] == DUCKDB_WALLET_SCHEMA_VERSION
    assert descriptor["catalog"] == WALLET_CATALOG_NAME
    assert descriptor["tables"] == list(WALLET_CATALOG_TABLES)
    assert descriptor["row_bindings"] == list(ROW_BINDING_COLUMNS)
    assert descriptor["monetary_sql_type"] == "VARCHAR"
    assert "FLOAT" not in str(descriptor).upper() or "FLOAT" not in {
        col["sql_type"]
        for columns in descriptor["columns"].values()
        for col in columns
        if col["monetary"]
    }


# ---------------------------------------------------------------------------
# Acceptance: no float coercion of monetary amounts
# ---------------------------------------------------------------------------


def test_monetary_columns_are_varchar_only() -> None:
    tables = parse_wallet_catalog_ddl()
    monetary_found = False
    for table, columns in tables.items():
        for col in columns:
            if col.name in MONETARY_AMOUNT_COLUMNS:
                monetary_found = True
                assert col.base_type == "VARCHAR", (
                    f"{table}.{col.name} must be VARCHAR, got {col.sql_type}"
                )
                assert col.base_type not in {
                    "FLOAT",
                    "DOUBLE",
                    "REAL",
                    "DECIMAL",
                    "NUMERIC",
                    "BIGINT",
                    "INTEGER",
                }
    assert monetary_found, "expected at least one monetary amount column"
    assert_no_float_monetary_types(tables)


def test_ddl_rejects_float_monetary_column() -> None:
    bad_ddl = """
CREATE TABLE IF NOT EXISTS transfers (
    record_id VARCHAR PRIMARY KEY,
    chain_ref_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    finality VARCHAR NOT NULL,
    amount_base_units DOUBLE NOT NULL,
    amount_decimals INTEGER NOT NULL
);
"""
    # Only one table — full invariant check fails table set, so test monetary
    # check in isolation after parse.
    tables = parse_wallet_catalog_ddl(bad_ddl)
    with pytest.raises(WalletSchemaError, match="VARCHAR"):
        assert_no_float_monetary_types(tables)


def test_exact_amount_strings_reject_float() -> None:
    good = ExactAmount(base_units="1000000000000000000", decimals=18)
    base, decimals = exact_amount_strings(good)
    assert base == "1000000000000000000"
    assert isinstance(base, str)
    assert decimals == 18

    with pytest.raises(WalletSchemaError, match="float"):
        exact_amount_strings({"base_units": 1.5, "decimals": 18})

    with pytest.raises(WalletSchemaError, match="float"):
        exact_amount_strings({"base_units": "1", "decimals": 1.0})


def test_transfer_projection_keeps_amount_as_string(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    account: AccountRef,
    asset: AssetRef,
) -> None:
    record = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.CONFIRMED,
        transaction_hash="0xtx",
        transfer_index=0,
        asset=asset,
        amount=ExactAmount(base_units="42", decimals=18),
        source_account=account,
        destination_account=AccountRef(chain, "0xdef", AccountKind.ADDRESS),
        transfer_kind=TransferKind.NATIVE,
    )
    row = project_transfer_row(record)
    assert row["amount_base_units"] == "42"
    assert type(row["amount_base_units"]) is str
    assert row["amount_decimals"] == 18
    assert not isinstance(row["amount_base_units"], float)


def test_utxo_and_token_account_amounts_are_strings(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    asset: AssetRef,
) -> None:
    owner = AccountRef(chain, "bc1qowner", AccountKind.ADDRESS)
    utxo = UTXORecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.FINALIZED,
        transaction_hash="0xutxo",
        output_index=1,
        asset=asset,
        amount=ExactAmount.from_int(5_000_000, decimals=18),
        owner=owner,
    )
    utxo_row = project_utxo_row(utxo)
    assert utxo_row["amount_base_units"] == "5000000"
    assert type(utxo_row["amount_base_units"]) is str

    token_account = AccountRef(chain, "TokenAcc111", AccountKind.TOKEN_ACCOUNT)
    token = TokenAccountRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.SAFE,
        token_account=token_account,
        owner=owner,
        asset=asset,
        amount=ExactAmount(base_units="0", decimals=18),
    )
    token_row = project_token_account_row(token)
    assert token_row["amount_base_units"] == "0"
    assert type(token_row["amount_base_units"]) is str


def test_transaction_fee_uses_exact_string(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    account: AccountRef,
) -> None:
    record = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.FINALIZED,
        transaction_hash="0xfee",
        status=TransactionStatus.SUCCEEDED,
        participants=(account,),
        fee=ExactAmount(base_units="21000000000000", decimals=18),
    )
    row = project_transaction_row(record)
    assert row["fee_base_units"] == "21000000000000"
    assert type(row["fee_base_units"]) is str


# ---------------------------------------------------------------------------
# Acceptance: every row binds chain/source/finality
# ---------------------------------------------------------------------------


def test_every_table_declares_binding_columns() -> None:
    tables = parse_wallet_catalog_ddl()
    assert_row_bindings(tables)
    for table, columns in tables.items():
        names = {col.name: col for col in columns}
        for binding in ROW_BINDING_COLUMNS:
            assert binding in names, f"{table} missing {binding}"
            col = names[binding]
            assert col.not_null or col.primary_key, (
                f"{table}.{binding} must be NOT NULL"
            )


def _assert_bindings(row: dict, *, finality: str | None = None) -> None:
    for name in ROW_BINDING_COLUMNS:
        assert name in row
        assert isinstance(row[name], str) and row[name].strip()
    if finality is not None:
        assert row["finality"] == finality


def test_projected_ledger_rows_bind_chain_source_finality(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    account: AccountRef,
    asset: AssetRef,
) -> None:
    block = BlockRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=10, hash="0xb"),
        finality=Finality.FINALIZED,
        block_hash="0xb",
        parent_hash="0xa",
        transaction_count=2,
    )
    _assert_bindings(project_block_row(block), finality="finalized")
    assert project_block_row(block)["chain_ref_id"] == chain.chain_ref_id

    transfer = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.CONFIRMED,
        transaction_hash="0xt",
        transfer_index=0,
        asset=asset,
        amount=ExactAmount(base_units="1", decimals=18),
        source_account=account,
        transfer_kind=TransferKind.TOKEN,
    )
    projected = project_ledger_record_rows(transfer)
    for table, rows in projected.items():
        for row in rows:
            _assert_bindings(row, finality="confirmed")
            assert row["chain_ref_id"] == chain.chain_ref_id
            assert row["source_id"]


def test_cursor_checkpoint_reorg_finality_rows_bind(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    cursor = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc",
        normalized_schema_major=1,
        normalizer_version="normalizer/v1",
        position=LedgerPosition(sequence=100, hash="0x100"),
        revision="rev-1",
        continuation_token="page-token-public-safe",
    )
    cursor_row = project_cursor_row(cursor, finality=Finality.OBSERVED, observed_at=NOW_STR)
    _assert_bindings(cursor_row, finality="observed")
    assert "continuation_token" not in cursor_row

    checkpoint = CheckpointRecord(
        identity=CheckpointIdentity(
            chain=chain,
            provider="fixture-rpc",
            scope="wallet:0xabc",
            normalized_schema_major=1,
            normalizer_version="normalizer/v1",
        ),
        anchor=HashAnchor(sequence=100, block_hash="0x100"),
        revision="rev-1",
        safety_depth=12,
        continuation_token="page-token-public-safe",
    )
    checkpoint_row = project_checkpoint_row(
        checkpoint, finality=Finality.SAFE, observed_at=NOW_STR
    )
    _assert_bindings(checkpoint_row, finality="safe")
    assert "continuation_token" not in checkpoint_row
    assert "metadata" not in checkpoint_row

    correction = OrphanCorrection(
        record_id="urn:wallet:block:sha256:" + ("11" * 32),
        prior_finality=Finality.CONFIRMED,
        new_finality=Finality.ORPHANED,
        orphaned_anchor=HashAnchor(sequence=99, block_hash="0x99"),
        ancestor_anchor=HashAnchor(sequence=98, block_hash="0x98"),
    )
    transition_row = project_finality_transition_row(
        correction, chain=chain, provenance=provenance
    )
    _assert_bindings(transition_row, finality="orphaned")

    decision = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(sequence=100, block_hash="0x100"),
        observed_anchor=HashAnchor(sequence=100, block_hash="0x100b"),
        common_ancestor=HashAnchor(sequence=98, block_hash="0x98"),
        orphaned_anchors=(HashAnchor(sequence=99, block_hash="0x99"),),
        rewind_sequence=98,
        reason="shallow reorg",
    )
    reorg_row = project_reorg_row(
        decision, chain=chain, provenance=provenance, finality=Finality.ORPHANED
    )
    _assert_bindings(reorg_row, finality="orphaned")


# ---------------------------------------------------------------------------
# Acceptance: secrets and raw payloads absent from query-visible tables
# ---------------------------------------------------------------------------


def test_ddl_has_no_secret_or_raw_payload_columns() -> None:
    tables = parse_wallet_catalog_ddl()
    assert_no_secret_or_raw_payload_columns(tables)
    forbidden_fragments = (
        "private_key",
        "seed",
        "mnemonic",
        "password",
        "secret",
        "raw_payload",
        "payload_bytes",
        "payload_json",
        "continuation_token",
        "api_key",
    )
    ddl_lower = WALLET_CATALOG_DDL.casefold()
    for fragment in forbidden_fragments:
        # Column names only: require word-ish appearance as a column token.
        assert f" {fragment} " not in f" {ddl_lower.replace(chr(10), ' ')} "
        assert f"{fragment} varchar" not in ddl_lower
        assert f"{fragment} boolean" not in ddl_lower


def test_public_data_classification_covers_all_columns() -> None:
    assert_public_data_classification()
    for table, column, classification in iter_query_visible_columns():
        assert classification in QUERY_VISIBLE_CLASSES
        assert classification not in FORBIDDEN_QUERY_CLASSES
        assert classification in {
            ColumnDataClass.PUBLIC,
            ColumnDataClass.CONTENT_REF,
        }
        assert table in WALLET_COLUMN_CLASSIFICATIONS
        assert column in WALLET_COLUMN_CLASSIFICATIONS[table]


def test_classification_rejects_secret_annotation() -> None:
    poisoned = {
        name: dict(cols) for name, cols in WALLET_COLUMN_CLASSIFICATIONS.items()
    }
    poisoned["chains"] = dict(poisoned["chains"])
    poisoned["chains"]["private_key"] = ColumnDataClass.SECRET
    # Add a matching DDL column via synthetic parse is heavy; assert helper
    # rejects SECRET on an existing column classification map instead.
    poisoned["chains"]["network"] = ColumnDataClass.SECRET
    with pytest.raises(WalletSchemaError, match="forbidden"):
        assert_public_data_classification(poisoned)


def test_encrypted_object_refs_hold_only_content_addresses(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    assert provenance.raw_payload is not None
    row = project_encrypted_object_ref_row(
        provenance.raw_payload,
        chain=chain,
        provenance=provenance,
        finality=Finality.OBSERVED,
        related_record_id="urn:wallet:block:sha256:" + ("22" * 32),
    )
    assert row["digest"] == DIGEST
    assert row["cid"] is None
    assert "raw_payload" not in row
    assert "payload_bytes" not in row
    assert "payload_json" not in row
    assert "body" not in row
    _assert_bindings(row)


def test_contract_event_omits_raw_data_payload(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    contract = AccountRef(chain, "0xcontract", AccountKind.CONTRACT)
    record = ContractEventRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=position.sequence,
            hash=position.hash,
            transaction_index=1,
            event_index=0,
        ),
        finality=Finality.CONFIRMED,
        transaction_hash="0xevt",
        event_index=0,
        contract=contract,
        event_signature="Transfer(address,address,uint256)",
        topics=("0xtopic0", "0xtopic1"),
        data_ref=RawPayloadRef(digest=DIGEST, media_type="application/octet-stream"),
    )
    row = project_contract_event_row(record)
    assert row["data_digest"] == DIGEST
    assert "data" not in row
    assert "raw_payload" not in row
    assert "payload_json" not in row
    _assert_bindings(row, finality="confirmed")


def test_ledger_projection_moves_raw_payload_to_refs_only(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    record = BlockRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=1, hash="0x1"),
        finality=Finality.OBSERVED,
        block_hash="0x1",
        parent_hash=None,
    )
    projected = project_ledger_record_rows(record)
    assert "encrypted_object_refs" in projected
    assert projected["encrypted_object_refs"]
    ref_row = projected["encrypted_object_refs"][0]
    assert ref_row["digest"] == DIGEST
    # No query-visible table row should carry raw payload keys.
    for table, rows in projected.items():
        for row in rows:
            for key in row:
                lowered = key.casefold()
                assert "raw_payload" not in lowered
                assert "payload_json" not in lowered
                assert "private_key" not in lowered
                assert "secret" not in lowered
            _assert_bindings(row)


def test_checkpoint_projection_strips_continuation_token(
    chain: ChainRef,
) -> None:
    checkpoint = CheckpointRecord(
        identity=CheckpointIdentity(
            chain=chain,
            provider="p",
            scope="s",
            normalized_schema_major=1,
            normalizer_version="v1",
        ),
        anchor=HashAnchor(sequence=1, block_hash="0x1"),
        revision="r1",
        continuation_token="opaque-page",
        metadata={"note": "public"},
    )
    row = project_checkpoint_row(
        checkpoint, finality=Finality.SAFE, observed_at=NOW_STR
    )
    assert set(row).isdisjoint(
        {
            "continuation_token",
            "metadata",
            "private_key",
            "raw_payload",
        }
    )

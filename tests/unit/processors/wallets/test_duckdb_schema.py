"""Unit tests for privacy-safe wallet DuckDB schema (DQK-035).

Acceptance:

* No float coercion of monetary amounts
* Every row binds chain / source / finality
* Secret-bearing fields and raw payloads are absent from query-visible tables
"""

from __future__ import annotations

from datetime import datetime, timezone
import re

import pytest

from ipfs_datasets_py.processors.wallets.duckdb_schema import (
    FORBIDDEN_MONETARY_TYPES,
    FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES,
    RAW_PAYLOAD_COLUMN_NAMES,
    REQUIRED_ROW_BINDINGS,
    SECRET_BEARING_COLUMN_NAMES,
    WALLET_CATALOG_TABLES,
    WALLET_SCHEMA_ID,
    ColumnSpec,
    DataClassification,
    DuckType,
    SchemaError,
    TableSpec,
    amount_columns,
    assert_no_float_monetary_values,
    assert_query_visible_row_safe,
    authority_only_tables,
    classify_column,
    ddl_for_schema,
    ddl_for_table,
    is_query_visible_table,
    project_account_row,
    project_asset_row,
    project_block_row,
    project_chain_row,
    project_checkpoint_row,
    project_contract_event_row,
    project_cursor_row,
    project_encrypted_object_ref_row,
    project_finality_transition_row,
    project_ingestion_source_row,
    project_ledger_record,
    project_reorg_row,
    project_token_account_row,
    project_transaction_row,
    project_transfer_row,
    project_utxo_row,
    query_visible_tables,
    schema_digest_material,
    validate_amount_string,
    validate_row_against_table,
    validate_row_bindings,
    validate_schema_invariants,
    wallet_table_map,
    wallet_table_specs,
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


NOW = datetime(2025, 1, 2, 3, 4, 5, 6789, tzinfo=timezone.utc)
DIGEST = "sha256:" + ("ab" * 32)


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
def account(chain: ChainRef) -> AccountRef:
    return AccountRef(chain, "0xabc", AccountKind.ADDRESS)


@pytest.fixture
def contract(chain: ChainRef) -> AccountRef:
    return AccountRef(chain, "0xcontract", AccountKind.CONTRACT)


@pytest.fixture
def token_account(chain: ChainRef) -> AccountRef:
    return AccountRef(chain, "0xtokenacct", AccountKind.TOKEN_ACCOUNT)


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


@pytest.fixture
def position() -> LedgerPosition:
    return LedgerPosition(
        sequence=19_000_000,
        hash="0xblock",
        transaction_index=2,
        event_index=None,
    )


# ---------------------------------------------------------------------------
# Catalog shape and invariants
# ---------------------------------------------------------------------------


def test_catalog_matches_control_plane_wallet_tables() -> None:
    names = tuple(table.name for table in wallet_table_specs())
    assert names == WALLET_CATALOG_TABLES
    assert set(wallet_table_map()) == set(WALLET_CATALOG_TABLES)


def test_schema_invariants_pass() -> None:
    validate_schema_invariants()


def test_schema_identity_is_stable() -> None:
    material = schema_digest_material()
    assert material["schema_id"] == WALLET_SCHEMA_ID
    assert material["schema_version"] == 1
    assert [table["name"] for table in material["tables"]] == list(
        WALLET_CATALOG_TABLES
    )


def test_encrypted_object_refs_is_authority_only() -> None:
    assert not is_query_visible_table("encrypted_object_refs")
    authority_names = {table.name for table in authority_only_tables()}
    assert authority_names == {"encrypted_object_refs"}
    visible = {table.name for table in query_visible_tables()}
    assert "encrypted_object_refs" not in visible
    assert visible == set(WALLET_CATALOG_TABLES) - {"encrypted_object_refs"}


def test_every_table_binds_chain_source_finality() -> None:
    for table in wallet_table_specs():
        for required in REQUIRED_ROW_BINDINGS:
            assert required in table.column_names, f"{table.name} missing {required}"


def test_query_visible_tables_have_no_secret_or_raw_columns() -> None:
    for table in query_visible_tables():
        for column in table.columns:
            assert column.name not in SECRET_BEARING_COLUMN_NAMES
            assert column.name not in RAW_PAYLOAD_COLUMN_NAMES
            assert column.name not in FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES
            assert column.classification is not DataClassification.INTERNAL


def test_no_float_types_in_schema_or_ddl() -> None:
    ddl = ddl_for_schema().upper()
    for forbidden in FORBIDDEN_MONETARY_TYPES:
        assert not re.search(rf"\b{forbidden}\b", ddl), forbidden
    for table in wallet_table_specs():
        for column in table.columns:
            assert column.duck_type.value.upper() not in FORBIDDEN_MONETARY_TYPES
            assert isinstance(column.duck_type, DuckType)
            assert "FLOAT" not in column.duck_type.value.upper()
            assert "DOUBLE" not in column.duck_type.value.upper()
            assert "REAL" not in column.duck_type.value.upper()


def test_monetary_columns_are_varchar_strings() -> None:
    pairs = amount_columns()
    assert ("transfers", "amount_base_units") in pairs
    assert ("utxos", "amount_base_units") in pairs
    assert ("token_accounts", "amount_base_units") in pairs
    assert ("transactions", "fee_base_units") in pairs
    for table_name, column_name in pairs:
        column = wallet_table_map()[table_name].column(column_name)
        assert column.monetary is True
        assert column.duck_type is DuckType.VARCHAR


def test_ddl_for_each_table_is_create_table() -> None:
    for table in wallet_table_specs():
        ddl = ddl_for_table(table.name)
        assert ddl.startswith(f"CREATE TABLE IF NOT EXISTS {table.name}")
        assert "PRIMARY KEY" in ddl
        for required in REQUIRED_ROW_BINDINGS:
            assert required in ddl


def test_column_spec_rejects_float_monetary() -> None:
    with pytest.raises(SchemaError, match="VARCHAR"):
        ColumnSpec(
            name="amount_base_units",
            duck_type=DuckType.BIGINT,  # wrong on purpose
            monetary=True,
        )


def test_column_spec_rejects_public_secret_name() -> None:
    with pytest.raises(SchemaError, match="cannot be classified public"):
        ColumnSpec(
            name="private_key",
            duck_type=DuckType.VARCHAR,
            classification=DataClassification.PUBLIC,
        )


def test_table_spec_requires_bindings_on_query_visible() -> None:
    with pytest.raises(SchemaError, match="must bind"):
        TableSpec(
            name="broken",
            query_visible=True,
            columns=(
                ColumnSpec(name="id", duck_type=DuckType.VARCHAR, primary_key=True),
            ),
        )


def test_query_visible_table_rejects_raw_payload_column() -> None:
    with pytest.raises(SchemaError, match="raw_payload|must not include|cannot be classified"):
        TableSpec(
            name="broken_raw",
            query_visible=True,
            columns=(
                ColumnSpec(
                    name="chain_ref_id", duck_type=DuckType.VARCHAR, primary_key=True
                ),
                ColumnSpec(name="source_provider", duck_type=DuckType.VARCHAR),
                ColumnSpec(name="finality", duck_type=DuckType.VARCHAR),
                ColumnSpec(name="raw_payload", duck_type=DuckType.VARCHAR),
            ),
        )


# ---------------------------------------------------------------------------
# Amount string validation (no float coercion)
# ---------------------------------------------------------------------------


def test_validate_amount_string_accepts_canonical_integers() -> None:
    assert validate_amount_string("0") == "0"
    assert validate_amount_string("1000000000000000000") == "1000000000000000000"
    assert validate_amount_string("-1") == "-1"


def test_validate_amount_string_rejects_floats_and_int_coercion() -> None:
    with pytest.raises(SchemaError, match="exact decimal integer string"):
        validate_amount_string(1.5)
    with pytest.raises(SchemaError, match="not int"):
        validate_amount_string(10)
    with pytest.raises(SchemaError, match="canonical"):
        validate_amount_string("1.0")
    with pytest.raises(SchemaError, match="canonical"):
        validate_amount_string("01")
    with pytest.raises(SchemaError, match="canonical"):
        validate_amount_string("1e18")


def test_assert_no_float_monetary_values() -> None:
    assert_no_float_monetary_values({"amount_base_units": "42", "fee_base_units": "1"})
    with pytest.raises(SchemaError, match="float coercion"):
        assert_no_float_monetary_values({"amount_base_units": 1.0})
    with pytest.raises(SchemaError, match="must be a string"):
        assert_no_float_monetary_values({"amount_base_units": 42})


# ---------------------------------------------------------------------------
# Row bindings and projection
# ---------------------------------------------------------------------------


def test_row_bindings_required() -> None:
    with pytest.raises(SchemaError, match="chain_ref_id"):
        validate_row_bindings(
            {"source_provider": "p", "finality": Finality.OBSERVED.value}
        )
    with pytest.raises(SchemaError, match="finality"):
        validate_row_bindings(
            {
                "chain_ref_id": "x",
                "source_provider": "p",
                "finality": "not-a-state",
            }
        )


def test_project_chain_and_source_rows(
    chain: ChainRef, provenance: Provenance
) -> None:
    chain_row = project_chain_row(chain, provenance=provenance)
    assert chain_row["chain_ref_id"] == chain.chain_ref_id
    assert chain_row["source_provider"] == provenance.provider
    assert chain_row["finality"] == Finality.FINALIZED.value
    assert "raw_payload" not in chain_row

    source_row = project_ingestion_source_row(provenance, chain=chain)
    assert source_row["provider"] == provenance.provider
    assert "raw_payload" not in source_row
    assert source_row["finality"] == Finality.OBSERVED.value


def test_project_account_and_asset(
    chain: ChainRef,
    account: AccountRef,
    asset: AssetRef,
    provenance: Provenance,
) -> None:
    account_row = project_account_row(account, provenance=provenance)
    assert account_row["account_id"] == account.account_id
    assert account_row["address"] == "0xabc"
    for key in REQUIRED_ROW_BINDINGS:
        assert account_row[key]

    asset_row = project_asset_row(asset, provenance=provenance)
    assert asset_row["decimals"] == 18
    assert asset_row["symbol"] == "ETH"
    assert isinstance(asset_row["decimals"], int)


def test_project_transfer_keeps_exact_amount_string(
    chain: ChainRef,
    account: AccountRef,
    asset: AssetRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    record = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.CONFIRMED,
        transaction_hash="0xtx",
        transfer_index=0,
        asset=asset,
        amount=ExactAmount("1000000000000000000", 18),
        source_account=account,
        destination_account=AccountRef(chain, "0xdef", AccountKind.ADDRESS),
        transfer_kind=TransferKind.NATIVE,
    )
    table, row = project_ledger_record(record)
    assert table == "transfers"
    assert row["amount_base_units"] == "1000000000000000000"
    assert row["amount_decimals"] == 18
    assert not isinstance(row["amount_base_units"], float)
    assert row["chain_ref_id"] == chain.chain_ref_id
    assert row["source_provider"] == "fixture-rpc"
    assert row["finality"] == Finality.CONFIRMED.value
    assert "raw_payload" not in row
    assert "extensions" not in row
    validate_row_against_table("transfers", row)


def test_project_transaction_fee_string(
    chain: ChainRef,
    account: AccountRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    record = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.SAFE,
        transaction_hash="0xtxfee",
        status=TransactionStatus.SUCCEEDED,
        participants=(account,),
        fee=ExactAmount.from_int(21_000, decimals=0),
    )
    row = project_transaction_row(record)
    assert row["fee_base_units"] == "21000"
    assert row["fee_decimals"] == 0
    assert "private_key" not in row
    assert "raw_payload" not in row


def test_project_utxo_and_token_account_amounts(
    chain: ChainRef,
    account: AccountRef,
    token_account: AccountRef,
    asset: AssetRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    utxo = UTXORecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.FINALIZED,
        transaction_hash="0xutxo",
        output_index=1,
        asset=asset,
        amount=ExactAmount("5000", 18),
        owner=account,
    )
    utxo_row = project_utxo_row(utxo)
    assert utxo_row["amount_base_units"] == "5000"

    token = TokenAccountRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.OBSERVED,
        token_account=token_account,
        owner=account,
        asset=asset,
        amount=ExactAmount("7", 18),
    )
    token_row = project_token_account_row(token)
    assert token_row["amount_base_units"] == "7"
    assert token_row["token_account_id"] == token_account.account_id


def test_project_block_and_contract_event(
    chain: ChainRef,
    contract: AccountRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    block = BlockRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=10, hash="0xblock10"),
        finality=Finality.FINALIZED,
        block_hash="0xblock10",
        parent_hash="0xblock9",
        block_time=NOW,
        transaction_count=3,
    )
    block_row = project_block_row(block)
    assert block_row["block_hash"] == "0xblock10"
    assert block_row["finality"] == Finality.FINALIZED.value

    event = ContractEventRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=10, hash="0xblock10", transaction_index=0, event_index=0
        ),
        finality=Finality.CONFIRMED,
        transaction_hash="0xev",
        event_index=0,
        contract=contract,
        event_signature="Transfer(address,address,uint256)",
        topics=("0xtopic0",),
        data_ref=RawPayloadRef(digest=DIGEST, media_type="application/octet-stream"),
    )
    event_row = project_contract_event_row(event)
    assert event_row["data_digest"] == DIGEST
    assert "raw_payload" not in event_row
    assert "body" not in event_row
    assert "payload_json" not in event_row


def test_project_cursor_omits_continuation_token(
    chain: ChainRef,
) -> None:
    cursor = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc",
        normalized_schema_major=1,
        normalizer_version="1.0.0",
        position=LedgerPosition(sequence=5, hash="0xhash5"),
        revision="rev:abc",
        continuation_token="provider-page-token-not-for-sql",
    )
    row = project_cursor_row(cursor, observed_at=NOW)
    assert "continuation_token" not in row
    assert row["ledger_hash"] == "0xhash5"
    assert row["revision"] == "rev:abc"
    assert_query_visible_row_safe(row)


def test_project_checkpoint_cursor_finality_reorg(
    chain: ChainRef, provenance: Provenance
) -> None:
    checkpoint = project_checkpoint_row(
        checkpoint_id="urn:wallet:checkpoint:test",
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc",
        normalized_schema_major=1,
        normalizer_version="1.0.0",
        anchor_sequence=100,
        anchor_hash="0xanchor",
        revision="rev:1",
        safety_depth=12,
        observed_at=NOW,
    )
    assert checkpoint["anchor_hash"] == "0xanchor"
    assert "continuation_token" not in checkpoint
    assert "metadata_json" not in checkpoint

    transition = project_finality_transition_row(
        transition_id="urn:wallet:finality:test",
        chain=chain,
        record_id="urn:wallet:transfer:test",
        from_finality=Finality.CONFIRMED,
        to_finality=Finality.FINALIZED,
        provenance=provenance,
        confirmations=64,
        head_sequence=200,
    )
    assert transition["from_finality"] == "confirmed"
    assert transition["to_finality"] == "finalized"
    assert transition["finality"] == "finalized"

    reorg = project_reorg_row(
        reorg_id="urn:wallet:reorg:test",
        chain=chain,
        kind="shallow",
        checkpoint_sequence=100,
        checkpoint_hash="0xold",
        observed_sequence=101,
        observed_hash="0xnew",
        provenance=provenance,
        ancestor_sequence=99,
        ancestor_hash="0xanc",
        rewind_sequence=99,
        orphaned_hashes=("0xold",),
    )
    assert reorg["kind"] == "shallow"
    assert reorg["review_required"] is False
    assert "0xold" in reorg["orphaned_hashes_json"]


def test_project_encrypted_object_ref_no_body(
    chain: ChainRef, provenance: Provenance
) -> None:
    row = project_encrypted_object_ref_row(
        object_ref_id="urn:wallet:obj:test",
        chain=chain,
        provenance=provenance,
        media_type="application/json",
        custody_policy="separately_encrypted",
        digest=DIGEST,
        byte_length=321,
    )
    assert row["digest"] == DIGEST
    assert "body" not in row
    assert "ciphertext" not in row
    assert "raw_payload" not in row
    for key in REQUIRED_ROW_BINDINGS:
        assert row[key]


def test_provenance_raw_payload_never_projected_to_query_visible(
    chain: ChainRef,
    asset: AssetRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    record = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.OBSERVED,
        transaction_hash="0xstrip",
        transfer_index=0,
        asset=asset,
        amount=ExactAmount("1", 18),
        transfer_kind=TransferKind.TOKEN,
    )
    _, row = project_ledger_record(record)
    assert provenance.raw_payload is not None
    for forbidden in FORBIDDEN_QUERY_VISIBLE_COLUMN_NAMES:
        assert forbidden not in row
    assert_query_visible_row_safe(row)


def test_transfer_row_rejects_float_amount_injection(
    chain: ChainRef,
    asset: AssetRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    record = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.OBSERVED,
        transaction_hash="0xbad",
        transfer_index=0,
        asset=asset,
        amount=ExactAmount("1", 18),
        transfer_kind=TransferKind.TOKEN,
    )
    _, row = project_ledger_record(record)
    poisoned = dict(row)
    poisoned["amount_base_units"] = 1.25  # type: ignore[assignment]
    with pytest.raises(SchemaError):
        validate_row_against_table("transfers", poisoned)


def test_classify_column_public_and_reference() -> None:
    assert classify_column("transfers", "amount_base_units") is DataClassification.PUBLIC
    assert classify_column("contract_events", "data_digest") is DataClassification.REFERENCE
    assert (
        classify_column("encrypted_object_refs", "custody_policy")
        is DataClassification.INTERNAL
    )


# ---------------------------------------------------------------------------
# Optional live DuckDB apply (when installed)
# ---------------------------------------------------------------------------


def test_ddl_applies_in_duckdb_when_available() -> None:
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    try:
        con.execute(ddl_for_schema())
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert set(WALLET_CATALOG_TABLES).issubset(tables)

        # Insert a transfer with exact amount string; read back as string.
        chain = ChainRef(
            namespace="eip155",
            network="ethereum-mainnet",
            chain_id="1",
            genesis_hash="0xgenesis",
        )
        provenance = Provenance(
            provider="rpc",
            provider_kind="json-rpc",
            request_id="r1",
            scope="s",
            observed_at=NOW,
        )
        asset = AssetRef(
            chain,
            asset_namespace="slip44",
            asset_reference="60",
            decimals=18,
            kind=AssetKind.NATIVE,
        )
        record = TransferRecord(
            chain=chain,
            provenance=provenance,
            ledger_position=LedgerPosition(sequence=1, hash="0xh"),
            finality=Finality.FINALIZED,
            transaction_hash="0xt",
            transfer_index=0,
            asset=asset,
            amount=ExactAmount("12345678901234567890", 18),
            transfer_kind=TransferKind.NATIVE,
        )
        row = project_transfer_row(record)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_sql = ", ".join(columns)
        con.execute(
            f"INSERT INTO transfers ({col_sql}) VALUES ({placeholders})",
            [row[name] for name in columns],
        )
        fetched = con.execute(
            "SELECT amount_base_units, typeof(amount_base_units), finality, "
            "chain_ref_id, source_provider FROM transfers"
        ).fetchone()
        assert fetched is not None
        assert fetched[0] == "12345678901234567890"
        assert fetched[1] == "VARCHAR"
        assert fetched[2] == Finality.FINALIZED.value
        assert fetched[3] == chain.chain_ref_id
        assert fetched[4] == "rpc"
    finally:
        con.close()

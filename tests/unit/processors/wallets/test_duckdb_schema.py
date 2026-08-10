"""Unit tests for privacy-safe wallet DuckDB schema (DQK-035).

Acceptance coverage:

* No float coercion of monetary amounts
* Every fact row binds chain / source / finality
* Secret-bearing fields and raw payloads are absent from query-visible tables
"""

from __future__ import annotations

from datetime import datetime, timezone
import re

import pytest

from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
)
from ipfs_datasets_py.processors.wallets.duckdb_schema import (
    AMOUNT_BASE_UNIT_COLUMNS,
    FACT_BINDING_COLUMNS,
    FORBIDDEN_QUERY_COLUMN_NAMES,
    WALLET_CATALOG_DDL,
    WALLET_CATALOG_NAME,
    WALLET_CATALOG_TABLES,
    WALLET_FACT_TABLES,
    WALLET_QUERY_VISIBLE_TABLES,
    WALLET_SCHEMA_VERSION,
    WALLET_TABLE_SPECS,
    ColumnSpec,
    PublicDataClassification,
    TableSpec,
    WalletSchemaError,
    assert_fact_bindings,
    assert_not_float_amount,
    block_row,
    chain_row,
    checkpoint_row,
    column_classification,
    contract_event_row,
    cursor_row,
    dimension_rows_for_record,
    encrypted_object_ref_row,
    exact_amount_columns,
    finality_transition_row,
    install_wallet_schema,
    iter_amount_columns,
    project_ledger_record,
    query_visible_column_names,
    reorg_row,
    schema_digest_material,
    table_classification,
    token_account_row,
    transaction_row,
    transfer_row,
    utxo_row,
    validate_wallet_schema,
)
from ipfs_datasets_py.processors.wallets.finality import ReorgDecision, ReorgKind
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
DIGEST = "sha256:" + ("ab" * 32)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


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
        sequence=18_000_000,
        hash="0xblockhash",
        transaction_index=3,
        event_index=None,
    )


@pytest.fixture
def eth_asset(chain: ChainRef) -> AssetRef:
    return AssetRef(
        chain=chain,
        asset_namespace="native",
        asset_reference="eth",
        decimals=18,
        kind=AssetKind.NATIVE,
        symbol="ETH",
    )


@pytest.fixture
def account(chain: ChainRef) -> AccountRef:
    return AccountRef(
        chain=chain,
        address="0xabc0000000000000000000000000000000000001",
        kind=AccountKind.ADDRESS,
    )


# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------


def test_catalog_tables_match_control_plane_plan() -> None:
    expected = (
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
    assert WALLET_CATALOG_TABLES == expected
    assert set(WALLET_TABLE_SPECS) == set(expected)
    assert WALLET_CATALOG_NAME == "wallet"
    assert WALLET_SCHEMA_VERSION.startswith("wallet-duckdb-schema/")
    validate_wallet_schema()


def test_ddl_creates_every_catalog_table() -> None:
    for name in WALLET_CATALOG_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {name}" in WALLET_CATALOG_DDL


def test_public_data_classification_on_every_table_and_column() -> None:
    for name, spec in WALLET_TABLE_SPECS.items():
        assert isinstance(spec.classification, PublicDataClassification)
        assert table_classification(name) is spec.classification
        for column in spec.columns:
            assert isinstance(column.classification, PublicDataClassification)
            assert (
                column_classification(name, column.name) is column.classification
            )
    assert (
        table_classification("transfers") is PublicDataClassification.PUBLIC_LEDGER
    )
    assert (
        table_classification("checkpoints") is PublicDataClassification.OPERATIONAL
    )
    assert (
        table_classification("encrypted_object_refs")
        is PublicDataClassification.CONTENT_REF
    )


# ---------------------------------------------------------------------------
# Acceptance: no float coercion of monetary amounts
# ---------------------------------------------------------------------------


def test_amount_base_unit_columns_are_varchar_only() -> None:
    amount_cols = list(iter_amount_columns())
    assert amount_cols, "expected amount columns in the schema"
    for table_name, column in amount_cols:
        if column.is_amount_base_units:
            assert column.name in AMOUNT_BASE_UNIT_COLUMNS
            assert column.sql_type_token == "VARCHAR"
            assert "FLOAT" not in column.sql_type
            assert "DOUBLE" not in column.sql_type
            assert "DECIMAL" not in column.sql_type
            assert "NUMERIC" not in column.sql_type
            assert "REAL" not in column.sql_type
        if column.is_amount_decimals:
            assert column.sql_type_token in {
                "INTEGER",
                "TINYINT",
                "SMALLINT",
                "UTINYINT",
                "USMALLINT",
                "UINTEGER",
            }


def test_exact_amount_columns_preserve_integer_strings() -> None:
    huge = "1000000000000000000000001"  # > 2^53, would lose precision as float
    amount = ExactAmount(huge, 18)
    cols = exact_amount_columns(amount)
    assert cols["amount_base_units"] == huge
    assert cols["amount_decimals"] == 18
    assert isinstance(cols["amount_base_units"], str)
    assert not isinstance(cols["amount_base_units"], float)


def test_assert_not_float_amount_rejects_floats() -> None:
    with pytest.raises(WalletSchemaError, match="binary float"):
        assert_not_float_amount(1.25, field_name="amount")
    with pytest.raises(WalletSchemaError, match="float"):
        assert_not_float_amount({"base_units": 1.0, "decimals": 18})
    with pytest.raises(WalletSchemaError, match="float"):
        assert_not_float_amount({"base_units": "1", "decimals": 18.0})
    # ExactAmount is accepted
    assert_not_float_amount(ExactAmount("1", 18))


def test_column_spec_rejects_float_amount_type() -> None:
    with pytest.raises(ValueError, match="VARCHAR"):
        ColumnSpec(
            "amount_base_units",
            "DOUBLE",
            is_amount_base_units=True,
        )
    with pytest.raises(ValueError, match="VARCHAR"):
        ColumnSpec(
            "fee_base_units",
            "DECIMAL(38,0)",
            is_amount_base_units=True,
        )


def test_transfer_row_uses_exact_amount_strings(
    chain: ChainRef,
    provenance: Provenance,
    eth_asset: AssetRef,
    account: AccountRef,
) -> None:
    record = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=10, hash="0xh", transaction_index=0),
        finality=Finality.FINALIZED,
        transaction_hash="0xtx",
        transfer_index=0,
        asset=eth_asset,
        amount=ExactAmount("42000000000000000000", 18),
        source_account=account,
        destination_account=AccountRef(
            chain=chain,
            address="0xdef0000000000000000000000000000000000002",
        ),
        transfer_kind=TransferKind.NATIVE,
    )
    row = transfer_row(record)
    assert row["amount_base_units"] == "42000000000000000000"
    assert row["amount_decimals"] == 18
    assert type(row["amount_base_units"]) is str
    # Exact integer string survives beyond IEEE-754 float precision.
    assert int(row["amount_base_units"]) == 42 * 10**18


def test_ddl_has_no_float_amount_assignments() -> None:
    for match in re.finditer(
        r"(amount_base_units|fee_base_units)\s+([A-Z0-9_()]+)",
        WALLET_CATALOG_DDL,
        flags=re.IGNORECASE,
    ):
        sql_type = match.group(2).upper()
        assert sql_type.startswith("VARCHAR"), (
            f"monetary column {match.group(1)} has type {sql_type}"
        )


# ---------------------------------------------------------------------------
# Acceptance: every row binds chain / source / finality
# ---------------------------------------------------------------------------


def test_every_fact_table_requires_binding_columns() -> None:
    for name in WALLET_FACT_TABLES:
        spec = WALLET_TABLE_SPECS[name]
        assert spec.requires_fact_bindings
        columns = set(spec.column_names)
        for binding in FACT_BINDING_COLUMNS:
            assert binding in columns, f"{name} missing {binding}"
            col = spec.column_map()[binding]
            assert not col.nullable, f"{name}.{binding} must be NOT NULL"


def test_projected_fact_rows_bind_chain_source_finality(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    eth_asset: AssetRef,
    account: AccountRef,
) -> None:
    block = BlockRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=100, hash="0xblock"),
        finality=Finality.SAFE,
        block_hash="0xblock",
        parent_hash="0xparent",
        transaction_count=2,
    )
    tx = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.CONFIRMED,
        transaction_hash="0xtx",
        status=TransactionStatus.SUCCEEDED,
        participants=(account,),
        fee=ExactAmount("21000", 18),
    )
    transfer = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.FINALIZED,
        transaction_hash="0xtx",
        transfer_index=0,
        asset=eth_asset,
        amount=ExactAmount("1", 18),
        source_account=account,
        transfer_kind=TransferKind.TOKEN,
    )
    utxo = UTXORecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=50, hash="0xbtc"),
        finality=Finality.CONFIRMED,
        transaction_hash="0xutxo_tx",
        output_index=1,
        asset=eth_asset,
        amount=ExactAmount("5000000000", 18),
        owner=account,
    )
    token_acct = TokenAccountRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.OBSERVED,
        token_account=AccountRef(
            chain=chain,
            address="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            kind=AccountKind.TOKEN_ACCOUNT,
        ),
        owner=account,
        asset=eth_asset,
        amount=ExactAmount("99", 18),
    )
    event = ContractEventRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=18_000_000, hash="0xblockhash", transaction_index=3, event_index=2
        ),
        finality=Finality.FINALIZED,
        transaction_hash="0xtx",
        event_index=2,
        contract=AccountRef(
            chain=chain,
            address="0xcontract00000000000000000000000000000001",
            kind=AccountKind.CONTRACT,
        ),
        event_signature="Transfer(address,address,uint256)",
        topics=("0xtopic0",),
        data_ref=RawPayloadRef(digest=DIGEST, media_type="application/octet-stream"),
    )

    for table, row in (
        ("blocks", block_row(block)),
        ("transactions", transaction_row(tx)),
        ("transfers", transfer_row(transfer)),
        ("utxos", utxo_row(utxo)),
        ("token_accounts", token_account_row(token_acct)),
        ("contract_events", contract_event_row(event)),
    ):
        assert_fact_bindings(row, table=table)
        assert row["chain_ref_id"] == chain.chain_ref_id
        assert row["chain_namespace"] == chain.namespace
        assert row["provider"] == provenance.provider
        assert row["scope"] == provenance.scope
        assert row["finality"] in {state.value for state in Finality}
        assert row["source_id"]


def test_cursor_and_checkpoint_rows_bind_chain_source_finality(
    chain: ChainRef,
) -> None:
    cursor = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc",
        normalized_schema_major=1,
        normalizer_version="normalizer/v1",
        position=LedgerPosition(sequence=9, hash="0xanchor"),
        revision="rev:1",
        continuation_token="page-token-not-secret",
    )
    crow = cursor_row(cursor, finality=Finality.OBSERVED)
    assert_fact_bindings(crow, table="cursors")
    assert crow["continuation_token_present"] is True
    assert "continuation_token" not in crow

    checkpoint = CheckpointRecord(
        identity=CheckpointIdentity(
            chain=chain,
            provider="fixture-rpc",
            scope="wallet:0xabc",
            normalized_schema_major=1,
            normalizer_version="normalizer/v1",
        ),
        anchor=HashAnchor(sequence=9, block_hash="0xanchor"),
        revision="rev:abc",
        safety_depth=12,
        continuation_token="page-token-not-secret",
        history=(HashAnchor(sequence=8, block_hash="0xprev"),),
    )
    prow = checkpoint_row(checkpoint, finality=Finality.SAFE)
    assert_fact_bindings(prow, table="checkpoints")
    assert prow["anchor_block_hash"] == "0xanchor"
    assert "continuation_token" not in prow


def test_finality_transition_and_reorg_rows_bind(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    transition = finality_transition_row(
        chain=chain,
        provenance=provenance,
        record_id="urn:wallet:tx:sha256:" + ("11" * 32),
        prior_finality=Finality.CONFIRMED,
        new_finality=Finality.FINALIZED,
        confirmations=64,
        head_sequence=100,
        record_sequence=36,
        reason="depth=64",
    )
    assert_fact_bindings(transition, table="finality_transitions")
    assert transition["finality"] == Finality.FINALIZED.value
    assert transition["prior_finality"] == Finality.CONFIRMED.value

    decision = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(10, "0xold"),
        observed_anchor=HashAnchor(12, "0xnew"),
        common_ancestor=HashAnchor(9, "0xanc"),
        orphaned_anchors=(HashAnchor(10, "0xold"),),
        corrections=(),
        rewind_sequence=9,
        review_required=False,
        reason="shallow reorg",
    )
    rrow = reorg_row(
        decision,
        chain=chain,
        provenance=provenance,
        finality=Finality.ORPHANED,
    )
    assert_fact_bindings(rrow, table="reorgs")
    assert rrow["kind"] == "shallow"
    assert rrow["checkpoint_block_hash"] == "0xold"


def test_assert_fact_bindings_rejects_missing_values() -> None:
    with pytest.raises(WalletSchemaError, match="missing binding"):
        assert_fact_bindings({"chain_ref_id": "x"}, table="blocks")
    with pytest.raises(WalletSchemaError, match="empty binding"):
        assert_fact_bindings(
            {name: "ok" if name != "finality" else "" for name in FACT_BINDING_COLUMNS},
            table="transfers",
        )


# ---------------------------------------------------------------------------
# Acceptance: no secrets / raw payloads on query-visible tables
# ---------------------------------------------------------------------------


def test_query_visible_tables_have_no_forbidden_columns() -> None:
    assert WALLET_QUERY_VISIBLE_TABLES == frozenset(WALLET_CATALOG_TABLES)
    for table_name in WALLET_QUERY_VISIBLE_TABLES:
        for column in query_visible_column_names(table_name):
            assert column.casefold() not in FORBIDDEN_QUERY_COLUMN_NAMES
            for fragment in (
                "private_key",
                "secret",
                "mnemonic",
                "seed_phrase",
                "password",
                "passphrase",
                "raw_payload",
                "payload_json",
                "signing_material",
            ):
                assert fragment not in column.casefold(), (
                    f"{table_name}.{column} contains {fragment}"
                )


def test_column_spec_rejects_secret_and_raw_names() -> None:
    for bad in ("private_key", "raw_payload", "payload_json", "mnemonic", "secret"):
        with pytest.raises(ValueError):
            ColumnSpec(bad, "VARCHAR")


def test_encrypted_object_refs_store_pointers_only(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    ref = encrypted_object_ref_row(
        chain=chain,
        raw=provenance.raw_payload,  # type: ignore[arg-type]
        source_id="src",
        encryption_policy="separately_encrypted",
    )
    assert ref["digest"] == DIGEST
    assert "payload" not in ref
    assert "raw_payload" not in ref
    assert "body" not in ref
    columns = set(WALLET_TABLE_SPECS["encrypted_object_refs"].column_names)
    assert "digest" in columns
    assert "cid" in columns
    assert "payload" not in columns
    assert "payload_json" not in columns
    assert "raw_payload" not in columns


def test_ledger_projection_omits_raw_payload_bodies(
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
    table, row = project_ledger_record(record)
    assert table == "blocks"
    assert "raw_payload" not in row
    assert "payload_json" not in row
    # Only a content-ref id may be present
    assert row["raw_object_ref_id"] is not None
    dims = dimension_rows_for_record(record)
    assert dims["encrypted_object_refs"]
    for obj in dims["encrypted_object_refs"]:
        assert set(obj) <= set(
            WALLET_TABLE_SPECS["encrypted_object_refs"].column_names
        )
        assert obj.get("digest") or obj.get("cid")


def test_contract_event_data_is_content_ref_not_body(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    record = ContractEventRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=1, hash="0x1", transaction_index=0, event_index=0
        ),
        finality=Finality.FINALIZED,
        transaction_hash="0xtx",
        event_index=0,
        contract=AccountRef(
            chain=chain,
            address="0xcontract00000000000000000000000000000001",
            kind=AccountKind.CONTRACT,
        ),
        data_ref=RawPayloadRef(cid=CID, media_type="application/octet-stream"),
    )
    row = contract_event_row(record)
    assert row["data_object_ref_id"]
    assert "data" not in row or row.get("data") is None
    assert "payload" not in row


# ---------------------------------------------------------------------------
# Dimension / install / digest
# ---------------------------------------------------------------------------


def test_dimension_rows_for_transfer(
    chain: ChainRef,
    provenance: Provenance,
    eth_asset: AssetRef,
    account: AccountRef,
) -> None:
    record = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=1, hash="0x1", transaction_index=0),
        finality=Finality.FINALIZED,
        transaction_hash="0xtx",
        transfer_index=0,
        asset=eth_asset,
        amount=ExactAmount("1", 18),
        source_account=account,
        destination_account=AccountRef(
            chain=chain, address="0xdest000000000000000000000000000000000002"
        ),
        transfer_kind=TransferKind.NATIVE,
    )
    dims = dimension_rows_for_record(record)
    assert dims["chains"][0]["chain_ref_id"] == chain.chain_ref_id
    assert dims["ingestion_sources"][0]["provider"] == "fixture-rpc"
    assert len(dims["accounts"]) == 2
    assert dims["assets"][0]["asset_id"] == eth_asset.asset_id
    assert chain_row(chain)["genesis_hash"] == chain.genesis_hash


def test_schema_digest_material_is_stable() -> None:
    material = schema_digest_material()
    assert material["schema_version"] == WALLET_SCHEMA_VERSION
    assert material["catalog"] == "wallet"
    assert len(material["tables"]) == len(WALLET_CATALOG_TABLES)
    names = [table["name"] for table in material["tables"]]
    assert names == list(WALLET_CATALOG_TABLES)


def test_install_wallet_schema_executes_ddl() -> None:
    statements: list[str] = []

    class _Conn:
        def execute(self, sql: str) -> None:
            statements.append(sql)

    version = install_wallet_schema(_Conn())
    assert version == WALLET_SCHEMA_VERSION
    assert len(statements) == len(WALLET_CATALOG_TABLES)
    assert all("CREATE TABLE" in sql for sql in statements)

    with pytest.raises(WalletSchemaError):
        install_wallet_schema(None)


def test_table_spec_rejects_fact_table_without_bindings() -> None:
    with pytest.raises(ValueError, match="missing fact bindings"):
        TableSpec(
            name="blocks",
            primary_key=("record_id",),
            classification=PublicDataClassification.PUBLIC_LEDGER,
            requires_fact_bindings=True,
            columns=(ColumnSpec("record_id", "VARCHAR"),),
        )


def test_project_ledger_record_routes_types(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    record = BlockRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=7, hash="0x7"),
        finality=Finality.PENDING,
        block_hash="0x7",
        parent_hash="0x6",
    )
    table, row = project_ledger_record(record)
    assert table == "blocks"
    assert row["block_hash"] == "0x7"
    assert row["finality"] == "pending"

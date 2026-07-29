"""Golden contract tests for normalized wallet models and canonical identity."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.canonical import (
    CanonicalEncodingError,
    canonical_json,
    canonical_json_bytes,
    content_digest,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    BalanceSnapshot,
    BlockRecord,
    ChainRef,
    ContractEventRecord,
    ExactAmount,
    ExportManifest,
    ExportPartition,
    ExportStatus,
    Finality,
    LedgerCursor,
    LedgerPosition,
    Provenance,
    RawPayloadPolicy,
    RawPayloadRef,
    SECRET_SAFE_MAX_DEPTH,
    TokenAccountRecord,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    UTXORecord,
    VersionedExtension,
    ensure_secret_safe,
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


def _records(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    account: AccountRef,
    asset: AssetRef,
):
    contract = AccountRef(chain, "0xcontract", AccountKind.CONTRACT)
    token_account = AccountRef(chain, "token-account:1", AccountKind.TOKEN_ACCOUNT)
    extension = {
        "eip155": VersionedExtension(
            schema_version="wallet-eip155-extension-v1",
            data={"transaction_type": 2, "access_list": []},
        )
    }
    common = {
        "chain": chain,
        "provenance": provenance,
        "ledger_position": position,
        "finality": Finality.FINALIZED,
        "extensions": extension,
    }
    amount = ExactAmount("1000000000000000000", 18)
    return [
        BlockRecord(
            **common,
            block_hash="0xblock",
            parent_hash="0xparent",
            block_time=NOW - timedelta(seconds=12),
            transaction_count=3,
        ),
        TransactionRecord(
            **common,
            transaction_hash="0xtx",
            status=TransactionStatus.SUCCEEDED,
            participants=(account, contract),
            fee=ExactAmount("21000000000000", 18),
            block_time=NOW - timedelta(seconds=10),
        ),
        TransferRecord(
            **common,
            transaction_hash="0xtx",
            transfer_index=0,
            asset=asset,
            amount=amount,
            source_account=account,
            destination_account=contract,
            transfer_kind=TransferKind.NATIVE,
        ),
        BalanceSnapshot(
            **common,
            account=account,
            asset=asset,
            amount=ExactAmount("42000000000000000000", 18),
        ),
        UTXORecord(
            **common,
            transaction_hash="0xtx",
            output_index=1,
            asset=asset,
            amount=amount,
            owner=account,
        ),
        TokenAccountRecord(
            **common,
            token_account=token_account,
            owner=account,
            asset=asset,
            amount=amount,
        ),
        ContractEventRecord(
            **common,
            transaction_hash="0xtx",
            event_index=4,
            contract=contract,
            event_signature="Transfer(address,address,uint256)",
            topics=("0xddf252ad",),
            data_ref=RawPayloadRef(cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3", byte_length=96),
        ),
    ]


def _schema(name: str) -> dict:
    project_root = Path(__file__).resolve().parents[4]
    return json.loads((project_root / "docs" / "schemas" / name).read_text())


def test_every_record_kind_is_immutable_deterministic_and_schema_validated(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    account: AccountRef,
    asset: AssetRef,
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema("wallet-ledger-record-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )

    records = _records(chain, provenance, position, account, asset)
    assert {record.record_type for record in records} == {
        "block",
        "transaction",
        "transfer",
        "balance",
        "utxo",
        "token_account",
        "contract_event",
    }
    assert len({record.record_id for record in records}) == len(records)

    for record in records:
        payload = record.to_dict()
        validator.validate(payload)
        assert json.loads(record.to_canonical_json()) == payload
        assert canonical_json(payload).encode() == canonical_json_bytes(payload)
        assert list(json.loads(record.to_canonical_json())) == sorted(payload)
        assert payload["schema_version"] == "wallet-ledger-record-v1"
        assert payload["chain_namespace"] == chain.namespace
        assert payload["network"] == chain.network
        assert payload["chain_id"] == chain.chain_id
        assert payload["genesis_hash"] == chain.genesis_hash
        assert payload["observed_at"] == "2025-01-02T03:04:05.006789Z"
        assert payload["source"]["raw_payload"] == {
            "media_type": "application/json",
            "digest": DIGEST,
            "byte_length": 321,
        }
        assert payload["extensions"]["eip155"]["schema_version"].endswith("-v1")
        with pytest.raises(FrozenInstanceError):
            record.finality = Finality.PENDING

    chain_specific_at_root = records[1].to_dict()
    chain_specific_at_root["gas_price"] = "1000000000"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(chain_specific_at_root)

    inexact_amount_shape = records[2].to_dict()
    inexact_amount_shape["amount"]["base_units"] = 1
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(inexact_amount_shape)


def test_record_id_is_a_golden_semantic_identity_not_an_observation_identity(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    first = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.PENDING,
        transaction_hash="0xtx",
        status=TransactionStatus.UNKNOWN,
    )
    later = TransactionRecord(
        chain=chain,
        provenance=Provenance(
            provider="another-provider",
            provider_kind="archive",
            request_id="later-request",
            scope="ledger:19000000",
            observed_at=NOW + timedelta(days=1),
        ),
        ledger_position=LedgerPosition(19_000_001, "0xreplacement", 9, None),
        finality=Finality.ORPHANED,
        transaction_hash="0xtx",
        status=TransactionStatus.FAILED,
    )

    assert first.record_id == later.record_id
    assert (
        first.record_id
        == "urn:wallet:transaction:sha256:"
        "d51eca6a61f64f95d4693f8f6a02933ef642ef5ab722478240d183c10d5d4b5b"
    )
    assert first.to_dict()["finality"] == "pending"
    assert later.to_dict()["finality"] == "orphaned"
    assert later.to_dict()["status"] == "failed"


def test_cross_network_reference_and_record_identities_cannot_collide(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    fork = ChainRef(
        namespace=chain.namespace,
        network="private-fork",
        chain_id=chain.chain_id,
        genesis_hash="0xdifferent-genesis",
    )
    account = AccountRef(chain, "0xabc")
    fork_account = AccountRef(fork, "0xabc")
    main_record = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.UNKNOWN,
        transaction_hash="0xsame",
        status=TransactionStatus.UNKNOWN,
    )
    fork_record = TransactionRecord(
        chain=fork,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.UNKNOWN,
        transaction_hash="0xsame",
        status=TransactionStatus.UNKNOWN,
    )

    assert chain.chain_ref_id != fork.chain_ref_id
    assert chain.chain_namespace == "eip155"
    assert chain.genesis_id == chain.genesis_hash
    assert account.canonical_address == account.address
    assert account.account_id != fork_account.account_id
    assert main_record.record_id != fork_record.record_id
    assert isinstance(hash(main_record), int)


def test_exact_amounts_reject_float_ambiguous_and_mismatched_values(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
    asset: AssetRef,
) -> None:
    assert ExactAmount.from_int(10**30 + 1, decimals=18).base_units == str(10**30 + 1)
    for invalid in ("01", "+1", "1.0", "1e18", "", "--1"):
        with pytest.raises(ValueError, match="canonical decimal"):
            ExactAmount(invalid, 18)
    with pytest.raises(ValueError, match="integer"):
        ExactAmount.from_int(1.25, decimals=18)
    with pytest.raises(CanonicalEncodingError, match="binary floats"):
        canonical_json({"amount": 1.25})
    with pytest.raises(ValueError, match="decimals must match"):
        TransferRecord(
            chain=chain,
            provenance=provenance,
            ledger_position=position,
            finality=Finality.OBSERVED,
            transaction_hash="0xtx",
            transfer_index=0,
            asset=asset,
            amount=ExactAmount("1", 6),
        )


def test_extensions_are_versioned_deeply_immutable_and_order_independent(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    first_data = {"z": [3, 2, 1], "a": {"value": 7}}
    second_data = {"a": {"value": 7}, "z": [3, 2, 1]}
    first = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.OBSERVED,
        transaction_hash="0xtx",
        status=TransactionStatus.UNKNOWN,
        extensions={
            "eip155": VersionedExtension("wallet-eip155-extension-v1", first_data)
        },
    )
    second = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.OBSERVED,
        transaction_hash="0xtx",
        status=TransactionStatus.UNKNOWN,
        extensions={
            "eip155": VersionedExtension("wallet-eip155-extension-v1", second_data)
        },
    )

    assert first.to_canonical_json() == second.to_canonical_json()
    assert first.record_id == second.record_id
    with pytest.raises(TypeError):
        first.extensions["solana"] = VersionedExtension("v1", {})
    with pytest.raises(TypeError):
        first.extensions["eip155"].data["a"] = {}
    with pytest.raises(ValueError, match="VersionedExtension"):
        TransactionRecord(
            chain=chain,
            provenance=provenance,
            ledger_position=position,
            finality=Finality.OBSERVED,
            transaction_hash="0xother",
            status=TransactionStatus.UNKNOWN,
            extensions={"eip155": {"chain_specific": True}},
        )


def test_raw_payloads_must_be_content_references(
    provenance: Provenance,
) -> None:
    assert provenance.raw_payload.digest == DIGEST
    with pytest.raises(CanonicalEncodingError, match="raw bytes"):
        canonical_json({"raw_payload": b'{"secret": true}'})
    with pytest.raises(ValueError, match="digest or CID"):
        RawPayloadRef()
    with pytest.raises(ValueError, match="tagged"):
        RawPayloadRef(digest="abcdef")
    with pytest.raises(ValueError, match="CID"):
        RawPayloadRef(cid="https://provider.invalid/raw/1")


def test_references_and_cursor_bind_all_canonical_identity_dimensions(
    chain: ChainRef,
    position: LedgerPosition,
) -> None:
    cursor = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc|records:all",
        normalized_schema_major=1,
        normalizer_version="1.4.0",
        position=position,
        revision="cas-7",
        continuation_token="opaque-provider-token",
    )
    changed_scope = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xdef|records:all",
        normalized_schema_major=1,
        normalizer_version="1.4.0",
        position=position,
        revision="cas-7",
    )

    assert cursor.cursor_id != changed_scope.cursor_id
    assert cursor.to_dict()["position"]["hash"] == "0xblock"
    assert cursor.to_dict()["continuation_token"] == "opaque-provider-token"
    with pytest.raises(ValueError, match="positive"):
        LedgerCursor(
            chain=chain,
            provider="fixture-rpc",
            scope="wallet:0xabc",
            normalized_schema_major=0,
            normalizer_version="1",
            position=position,
            revision="1",
        )


def test_export_manifest_is_accounted_deterministic_and_schema_validated(
    chain: ChainRef,
    provenance: Provenance,
    position: LedgerPosition,
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema("wallet-export-manifest-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    cursor = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc",
        normalized_schema_major=1,
        normalizer_version="1.0.0",
        position=position,
        revision="8",
    )
    partition = ExportPartition(
        path="chain=eip155/network=ethereum-mainnet/part-000.jsonl",
        format="jsonl",
        record_count=7,
        byte_count=4096,
        digest=content_digest({"fixture": "partition"}),
        record_types=(
            "balance",
            "block",
            "contract_event",
            "token_account",
            "transaction",
            "transfer",
            "utxo",
        ),
        min_position=19_000_000,
        max_position=19_000_000,
    )
    manifest = ExportManifest(
        chain=chain,
        provenance=provenance,
        status=ExportStatus.COMPLETE,
        raw_payload_policy=RawPayloadPolicy.REFERENCED,
        partitions=(partition,),
        record_count=7,
        warning_count=0,
        finality_counts={Finality.FINALIZED: 7},
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        checkpoint_before=None,
        checkpoint_after=cursor,
    )
    payload = manifest.to_dict()

    jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    ).validate(payload)
    assert json.loads(manifest.to_canonical_json()) == payload
    assert payload["record_count"] == sum(
        item["record_count"] for item in payload["partitions"]
    )
    assert payload["record_count"] == sum(payload["finality_counts"].values())
    assert payload["checkpoint_after"]["cursor_id"] == cursor.cursor_id

    same_manifest = ExportManifest(
        chain=chain,
        provenance=Provenance(
            provider=provenance.provider,
            provider_kind=provenance.provider_kind,
            request_id=provenance.request_id,
            scope=provenance.scope,
            observed_at=NOW + timedelta(days=1),
            raw_payload=provenance.raw_payload,
        ),
        status=ExportStatus.PARTIAL,
        raw_payload_policy=RawPayloadPolicy.REFERENCED,
        partitions=(partition,),
        record_count=7,
        warning_count=1,
        finality_counts={Finality.FINALIZED: 7},
        started_at=NOW + timedelta(days=1),
        completed_at=NOW + timedelta(days=1, seconds=2),
        checkpoint_after=cursor,
        warnings=("late observation",),
    )
    assert same_manifest.manifest_id == manifest.manifest_id


def test_export_manifest_rejects_inconsistent_accounting(
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    partition = ExportPartition(
        path="part.jsonl",
        format="jsonl",
        record_count=2,
        byte_count=10,
        digest=DIGEST,
    )
    with pytest.raises(ValueError, match="partition record counts"):
        ExportManifest(
            chain=chain,
            provenance=provenance,
            status=ExportStatus.COMPLETE,
            raw_payload_policy=RawPayloadPolicy.OMITTED,
            partitions=(partition,),
            record_count=3,
            warning_count=0,
            finality_counts={Finality.FINALIZED: 3},
            started_at=NOW,
            completed_at=NOW,
        )
    with pytest.raises(ValueError, match="warning_count"):
        ExportManifest(
            chain=chain,
            provenance=provenance,
            status=ExportStatus.PARTIAL,
            raw_payload_policy=RawPayloadPolicy.OMITTED,
            partitions=(partition,),
            record_count=2,
            warning_count=0,
            finality_counts={Finality.FINALIZED: 2},
            started_at=NOW,
            completed_at=NOW,
            warnings=("warning",),
        )


def test_secret_safe_policy_preserves_nested_public_chain_data() -> None:
    first = VersionedExtension(
        "wallet-chain-extension-v1",
        {
            "token": {
                "token_id": "42",
                "symbol": "SAFE",
                "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            },
            "transaction": {
                "hash": "0x" + ("ab" * 32),
                "signature": "0x" + ("cd" * 65),
                "access_list": [{"address": "0xabc", "storage_keys": []}],
            },
        },
    )
    second = VersionedExtension(
        "wallet-chain-extension-v1",
        {
            "transaction": {
                "access_list": [{"storage_keys": [], "address": "0xabc"}],
                "signature": "0x" + ("cd" * 65),
                "hash": "0x" + ("ab" * 32),
            },
            "token": {
                "program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "symbol": "SAFE",
                "token_id": "42",
            },
        },
    )

    assert first.to_dict() == second.to_dict()
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    assert first.to_dict()["data"]["token"]["token_id"] == "42"


@pytest.mark.parametrize(
    "payload",
    (
        {"nested": [{"privateKey": "correct-horse-battery-staple-wallet-secret"}]},
        {"nested": {"note": "correct-horse-battery-staple-wallet-secret"}},
        {"nested": {"reference": "vault://wallet/provider/main-token"}},
        {"nested": {"authorization": "placeholder"}},
    ),
)
def test_secret_safe_policy_rejects_nested_material_without_echoing_it(
    payload: dict[str, object],
) -> None:
    serialized_attack = json.dumps(payload, sort_keys=True)
    with pytest.raises(ValueError, match="wallet serialization") as caught:
        VersionedExtension("wallet-chain-extension-v1", payload)

    rendered_error = f"{caught.value!s}\n{caught.value!r}"
    for prohibited in (
        "correct-horse-battery-staple-wallet-secret",
        "vault://wallet/provider/main-token",
        serialized_attack,
    ):
        assert prohibited not in rendered_error


def test_secret_safe_policy_has_a_finite_recursion_budget() -> None:
    root: dict[str, object] = {}
    child = root
    for index in range(SECRET_SAFE_MAX_DEPTH + 2):
        nested: dict[str, object] = {"height": index}
        child["next"] = nested
        child = nested

    with pytest.raises(ValueError, match="policy limit") as caught:
        ensure_secret_safe(root)
    assert "height" not in str(caught.value)


def test_cursor_rejects_concrete_secret_value_without_echoing_it(
    chain: ChainRef,
    position: LedgerPosition,
) -> None:
    sentinel = "correct-horse-battery-staple-wallet-secret"
    with pytest.raises(ValueError, match="concrete secret") as caught:
        LedgerCursor(
            chain=chain,
            provider="fixture-rpc",
            scope="wallet:0xabc",
            normalized_schema_major=1,
            normalizer_version="1.0.0",
            position=position,
            revision="rev:1",
            continuation_token=sentinel,
        )
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)

"""Unit tests for the Bitcoin wallet-to-Crypto-IR adapter (CRYPTOIR-G130 / CRYPTOIR-010).

Fixture-driven, offline conversion and rejection tests.  No network I/O.
Covers:

* network/genesis (bip122) binding;
* txid display vs internal byte order;
* outpoints and script commitments as canonical spending identity;
* satoshi amounts (no binary floats);
* script bytes and witness context;
* confirmations, replacement, coinbase, and reorg state;
* display addresses never treated as spend authority;
* missing previous outputs remaining incomplete;
* no Script execution.
"""

from __future__ import annotations

import socket
import sys
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir import (
    AdapterConversionStatus,
    AdapterRegistry,
    AuthorityKind,
    FinalityStatus,
    ObservedTransaction,
    RetractionStatus,
    UnsignedTransactionIntent,
)
from ipfs_datasets_py.logic.crypto_ir.adapters.bitcoin import (
    BITCOIN_ADAPTER_ID,
    BITCOIN_CAPABILITY_ID,
    BITCOIN_NAMESPACE,
    COINBASE_TXID_DISPLAY,
    COINBASE_VOUT,
    MAINNET_GENESIS,
    MAINNET_NETWORK,
    REGTEST_GENESIS,
    REGTEST_NETWORK,
    TESTNET_GENESIS,
    TESTNET_NETWORK,
    BitcoinAdapterError,
    BitcoinSpendIntent,
    BitcoinTransactionObservation,
    BitcoinUtxoSetObservation,
    BitcoinWalletAdapter,
    Outpoint,
    ScriptType,
    SpendingCondition,
    UtxoEntry,
    UtxoInput,
    convert_bitcoin_payload,
    map_finality,
    normalize_txid,
    parse_sats,
    resolve_network,
    reverse_hex_bytes,
    script_commitment,
    txid_byte_order_record,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TXID_A = "a1" * 32
TXID_B = "b2" * 32
TXID_C = "c3" * 32
BLOCK_HASH = "d4" * 32
P2WPKH_SCRIPT = "0014" + "11" * 20
P2WPKH_SCRIPT_B = "0014" + "22" * 20
P2TR_SCRIPT = "5120" + "33" * 32
ADDR_A = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
ADDR_B = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
WITNESS_SIG = "30440220" + "ab" * 32 + "0220" + "cd" * 32 + "01"
WITNESS_PUB = "02" + "11" * 32


def _full_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-full-1",
        "network": MAINNET_NETWORK,
        "genesis_hash": MAINNET_GENESIS,
        "txid": TXID_A,
        "status": "confirmed",
        "confirmations": 6,
        "block_height": 840_000,
        "block_hash": BLOCK_HASH,
        "fee_sats": "1500",
        "weight": 560,
        "finality": "confirmed",
        "retraction": "not_retracted",
        "observed_at": "2026-07-29T12:00:00Z",
        "validity_start": "2026-07-29T12:00:00Z",
        "validity_end": "",
        "inputs": [
            {
                "previous_output": {"txid": TXID_B, "vout": 1},
                "sequence": 0xFFFFFFFD,
                "script_sig_hex": "",
                "witness": [WITNESS_SIG, WITNESS_PUB],
                "prevout_value_sats": "100000",
                "prevout_spending_condition": {
                    "script_type": "p2wpkh",
                    "script_hex": P2WPKH_SCRIPT,
                    "address": ADDR_A,
                    "witness_version": 0,
                },
            }
        ],
        "outputs": [
            {
                "n": 0,
                "value_sats": "98000",
                "spending_condition": {
                    "script_type": "p2wpkh",
                    "script_hex": P2WPKH_SCRIPT_B,
                    "address": ADDR_B,
                    "witness_version": 0,
                },
            },
            {
                "n": 1,
                "value_sats": "500",
                "spending_condition": {
                    "script_type": "null_data",
                    "script_hex": "6a0b68656c6c6f20776f726c64",
                },
            },
        ],
        "raw": {"provider": "fixture", "cursor": 1},
    }
    payload.update(overrides)
    return payload


def _minimal_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-min-1",
        "network": MAINNET_NETWORK,
        "txid": TXID_A,
        "inputs": [
            {
                "previous_output": {"txid": TXID_B, "vout": 0},
            }
        ],
        "outputs": [
            {
                "n": 0,
                "value_sats": "1",
                "spending_condition": {
                    "script_type": "unknown",
                    "script_hex": "6a",
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def _coinbase_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-coinbase",
        "network": MAINNET_NETWORK,
        "genesis_hash": MAINNET_GENESIS,
        "txid": TXID_C,
        "status": "confirmed",
        "confirmations": 120,
        "block_height": 840_001,
        "block_hash": BLOCK_HASH,
        "finality": "finalized",
        "retraction": "not_retracted",
        "observed_at": "2026-07-29T13:00:00Z",
        "inputs": [
            {
                "is_coinbase": True,
                "script_sig_hex": "03e0b80c" + "00" * 8,
                "sequence": 0xFFFFFFFF,
            }
        ],
        "outputs": [
            {
                "n": 0,
                "value_sats": "312500000",
                "spending_condition": {
                    "script_type": "p2tr",
                    "script_hex": P2TR_SCRIPT,
                    "witness_version": 1,
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def _utxo_set(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "utxo_set",
        "observation_id": "utxo-set-1",
        "network": MAINNET_NETWORK,
        "genesis_hash": MAINNET_GENESIS,
        "observed_at": "2026-07-29T12:00:00Z",
        "utxos": [
            {
                "outpoint": {"txid": TXID_A, "vout": 0},
                "value_sats": "50000",
                "spending_condition": {
                    "script_type": "p2wpkh",
                    "script_hex": P2WPKH_SCRIPT,
                    "address": ADDR_A,
                },
                "created_by": TXID_A,
                "created_height": 839_000,
                "confirmations": 1000,
            },
            {
                "outpoint": {"txid": TXID_B, "vout": 2},
                "value_sats": "2500",
                "spending_condition": {
                    "script_type": "p2tr",
                    "script_hex": P2TR_SCRIPT,
                },
                "created_by": TXID_B,
                "created_height": 840_000,
                "confirmations": 3,
            },
        ],
    }
    payload.update(overrides)
    return payload


def _spend_intent(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "spend_intent",
        "intent_id": "intent-1",
        "network": MAINNET_NETWORK,
        "genesis_hash": MAINNET_GENESIS,
        "origin_address": ADDR_A,
        "fee_sats": "500",
        "inputs": [
            {
                "previous_output": {"txid": TXID_A, "vout": 0},
                "sequence": 0xFFFFFFFD,
                "prevout_value_sats": "10000",
                "prevout_spending_condition": {
                    "script_type": "p2wpkh",
                    "script_hex": P2WPKH_SCRIPT,
                    "address": ADDR_A,
                },
            }
        ],
        "outputs": [
            {
                "n": 0,
                "value_sats": "9500",
                "spending_condition": {
                    "script_type": "p2wpkh",
                    "script_hex": P2WPKH_SCRIPT_B,
                    "address": ADDR_B,
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Import / side-effect free
# ---------------------------------------------------------------------------


def test_import_bitcoin_adapter_has_no_network_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "network socket use forbidden during Bitcoin adapter import"
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if name.endswith(".crypto_ir.adapters.bitcoin") or name.endswith(
            "crypto_ir.adapters.bitcoin"
        ):
            del sys.modules[name]

    from ipfs_datasets_py.logic.crypto_ir.adapters import bitcoin as btc_mod

    assert btc_mod.BitcoinWalletAdapter is not None
    assert btc_mod.Outpoint is not None
    assert btc_mod.UtxoInput is not None
    assert btc_mod.SpendingCondition is not None


def test_adapter_registers_in_registry() -> None:
    adapter = BitcoinWalletAdapter()
    registry = AdapterRegistry.from_adapters([adapter])
    entry = registry.require(
        BITCOIN_ADAPTER_ID,
        required_surfaces=[],
    )
    assert entry.capability.capability_id == BITCOIN_CAPABILITY_ID
    assert entry.capability.supports_chain_namespace(BITCOIN_NAMESPACE)
    assert "outpoints" in entry.capability.features
    assert "no_script_execution" in entry.capability.features
    assert entry.capability.attributes.get("display_address_authoritative") is False


# ---------------------------------------------------------------------------
# Network / genesis / txid byte order
# ---------------------------------------------------------------------------


def test_resolve_mainnet_genesis_binding() -> None:
    anchor = resolve_network(network=MAINNET_NETWORK)
    assert anchor.genesis_hash == MAINNET_GENESIS
    assert anchor.chain_id == MAINNET_GENESIS[:32]
    identity = anchor.to_chain_identity()
    assert identity.chain_namespace == BITCOIN_NAMESPACE
    assert identity.network == MAINNET_NETWORK
    assert identity.genesis_digest == f"sha256:{MAINNET_GENESIS}"
    assert identity.attributes["bip122_chain_id"] == MAINNET_GENESIS[:32]


def test_mainnet_and_testnet_do_not_collide() -> None:
    main = resolve_network(network=MAINNET_NETWORK)
    test = resolve_network(network=TESTNET_NETWORK)
    assert main.genesis_hash != test.genesis_hash
    assert main.chain_id != test.chain_id
    assert main.to_chain_identity().identity.digest != test.to_chain_identity().identity.digest


def test_mismatched_genesis_for_known_network_fails() -> None:
    with pytest.raises(BitcoinAdapterError, match="genesis_hash does not match"):
        resolve_network(network=MAINNET_NETWORK, genesis_hash=TESTNET_GENESIS)


def test_unknown_network_requires_genesis() -> None:
    with pytest.raises(BitcoinAdapterError, match="explicit genesis_hash"):
        resolve_network(network="bitcoin-custom")


def test_unknown_network_with_genesis_accepted() -> None:
    genesis = "11" * 32
    anchor = resolve_network(network="bitcoin-custom", genesis_hash=genesis)
    assert anchor.network == "bitcoin-custom"
    assert anchor.genesis_hash == genesis


def test_txid_byte_order_display_and_internal() -> None:
    # Non-symmetric txid so reverse differs from display.
    display = "0123456789abcdef" * 4
    assert len(display) == 64
    record = txid_byte_order_record(display)
    assert record["txid_display"] == display
    assert record["txid_internal"] == reverse_hex_bytes(display)
    assert record["txid_internal"] != display
    assert record["byte_order"] == "display_is_reversed_of_internal"

    op = Outpoint(txid=display, vout=3)
    assert op.txid == display
    assert op.txid_internal == reverse_hex_bytes(display)
    assert op.key == f"{display}:3"


def test_normalize_txid_rejects_malformed() -> None:
    with pytest.raises(BitcoinAdapterError):
        normalize_txid("dead")
    with pytest.raises(BitcoinAdapterError):
        normalize_txid("not-a-txid")


# ---------------------------------------------------------------------------
# Outpoint / SpendingCondition / UtxoInput identity
# ---------------------------------------------------------------------------


def test_outpoint_and_script_commitment_are_authoritative() -> None:
    condition = SpendingCondition(
        script_type=ScriptType.P2WPKH,
        script_hex=P2WPKH_SCRIPT,
        address=ADDR_A,
    )
    assert condition.script_commitment == script_commitment(P2WPKH_SCRIPT)
    assert condition.to_dict()["display_address_authoritative"] is False
    assert condition.to_dict()["canonical_spending_identity"] == "script_commitment"

    # Same script, different display address → same commitment.
    other_addr = SpendingCondition(
        script_type=ScriptType.P2WPKH,
        script_hex=P2WPKH_SCRIPT,
        address="bc1qdifferentdisplayaddressnotused",
    )
    assert other_addr.script_commitment == condition.script_commitment

    # Different script → different commitment.
    other_script = SpendingCondition(
        script_type=ScriptType.P2WPKH,
        script_hex=P2WPKH_SCRIPT_B,
        address=ADDR_A,
    )
    assert other_script.script_commitment != condition.script_commitment


def test_script_commitment_mismatch_fails() -> None:
    with pytest.raises(BitcoinAdapterError, match="script_commitment does not match"):
        SpendingCondition(
            script_type=ScriptType.P2WPKH,
            script_hex=P2WPKH_SCRIPT,
            script_commitment="sha256:" + ("00" * 32),
        )


def test_utxo_input_marks_missing_prevout_incomplete() -> None:
    vin = UtxoInput(
        outpoint=Outpoint(txid=TXID_B, vout=0),
        sequence=0xFFFFFFFF,
    )
    assert vin.previous_output_known is False
    assert vin.prevout_value_sats is None
    assert vin.prevout_spending_condition is None

    known = UtxoInput(
        outpoint=Outpoint(txid=TXID_B, vout=0),
        prevout_value_sats="1000",
        prevout_spending_condition=SpendingCondition(
            script_type=ScriptType.P2WPKH,
            script_hex=P2WPKH_SCRIPT,
        ),
    )
    assert known.previous_output_known is True


def test_coinbase_outpoint_marker() -> None:
    op = Outpoint.coinbase()
    assert op.txid == COINBASE_TXID_DISPLAY
    assert op.vout == COINBASE_VOUT
    assert op.is_coinbase_prevout is True


# ---------------------------------------------------------------------------
# Satoshi amounts
# ---------------------------------------------------------------------------


def test_parse_sats_exact_and_rejects_floats() -> None:
    assert parse_sats(0) == "0"
    assert parse_sats("21000000") == "21000000"
    assert parse_sats(100_000_000) == "100000000"
    with pytest.raises(BitcoinAdapterError, match="binary float"):
        parse_sats(1.5)
    with pytest.raises(BitcoinAdapterError):
        parse_sats(-1)
    with pytest.raises(BitcoinAdapterError):
        parse_sats(True)


# ---------------------------------------------------------------------------
# Full observation conversion
# ---------------------------------------------------------------------------


def test_full_observation_preserves_network_outpoints_sats_witness() -> None:
    result = convert_bitcoin_payload(_full_observation())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.adapter_id == BITCOIN_ADAPTER_ID
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION

    chain = result.result_payload["chain"]
    assert chain["chain_namespace"] == BITCOIN_NAMESPACE
    assert chain["network"] == MAINNET_NETWORK
    assert chain["genesis_digest"] == f"sha256:{MAINNET_GENESIS}"
    assert chain["attributes"]["genesis_hash"] == MAINNET_GENESIS

    txid = result.result_payload["txid"]
    assert txid["txid_display"] == TXID_A
    assert txid["txid_internal"] == reverse_hex_bytes(TXID_A)
    assert txid["byte_order"] == "display_is_reversed_of_internal"

    inputs = result.result_payload["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["outpoint"]["txid"] == TXID_B
    assert inputs[0]["outpoint"]["vout"] == 1
    assert inputs[0]["outpoint"]["txid_internal"] == reverse_hex_bytes(TXID_B)
    assert inputs[0]["witness"] == [WITNESS_SIG, WITNESS_PUB] or list(
        inputs[0]["witness"]
    ) == [WITNESS_SIG, WITNESS_PUB]
    assert inputs[0]["sequence"] == 0xFFFFFFFD
    assert inputs[0]["prevout_value_sats"] == "100000"
    assert inputs[0]["previous_output_known"] is True
    assert inputs[0]["prevout_spending_condition"]["script_hex"] == P2WPKH_SCRIPT
    assert (
        inputs[0]["prevout_spending_condition"]["script_commitment"]
        == script_commitment(P2WPKH_SCRIPT)
    )
    assert inputs[0].get("display_address_not_spend_authority") is True

    outputs = result.result_payload["outputs"]
    assert len(outputs) == 2
    assert outputs[0]["value_sats"] == "98000"
    assert outputs[0]["outpoint"]["txid"] == TXID_A
    assert outputs[0]["outpoint"]["vout"] == 0
    assert outputs[0]["spending_condition"]["script_hex"] == P2WPKH_SCRIPT_B
    assert outputs[0]["display_address_not_spend_authority"] is True

    assert result.result_payload["confirmations"] == 6
    assert result.result_payload["fee"]["base_units"] == "1500"
    assert result.result_payload["fee"]["decimals"] == 8
    assert result.result_payload["is_coinbase"] is False
    assert result.result_payload["display_address_authoritative"] is False
    assert result.result_payload["canonical_spending_identity"] == (
        "outpoint",
        "script_commitment",
    ) or list(result.result_payload["canonical_spending_identity"]) == [
        "outpoint",
        "script_commitment",
    ]
    assert result.result_payload["script_execution"] is False

    observed = result.result_payload["observed_transaction"]
    restored = ObservedTransaction.from_dict(observed)
    assert restored.finality is FinalityStatus.CONFIRMED
    assert restored.provenance is not None
    assert restored.provenance.authority.kind is AuthorityKind.OBSERVATION
    assert restored.attributes["confirmations"] == 6
    assert restored.attributes["txid_display"] == TXID_A
    assert restored.coordinate.sequence == 840_000


def test_missing_previous_outputs_remain_incomplete() -> None:
    result = convert_bitcoin_payload(_minimal_observation())
    assert result.status is AdapterConversionStatus.PARTIAL
    missing = set(result.result_payload["missing_coverage"])
    assert "inputs[0].previous_output" in missing
    assert "fee_sats" in missing
    assert "confirmations" in missing or "finality" in missing

    paths = {field.path for field in result.unsupported_fields}
    assert "inputs[0].previous_output" in paths

    vin = result.result_payload["inputs"][0]
    assert vin["previous_output_known"] is False
    assert vin["prevout_value_sats"] is None
    assert vin["prevout_spending_condition"] is None
    # Outpoint itself is still present (identity known, value/script not).
    assert vin["outpoint"]["txid"] == TXID_B
    assert vin["outpoint"]["vout"] == 0


def test_address_never_canonical_spending_identity() -> None:
    result = convert_bitcoin_payload(_full_observation())
    assert result.result_payload["display_address_authoritative"] is False
    for vout in result.result_payload["outputs"]:
        cond = vout["spending_condition"]
        assert cond["display_address_authoritative"] is False
        if cond["address"]:
            assert cond["script_commitment"]
            # Commitment is of script bytes, not of the address string.
            assert cond["script_commitment"] == script_commitment(cond["script_hex"])

    # UTXO set identity vectors use outpoint + script commitment.
    utxo_result = convert_bitcoin_payload(_utxo_set())
    for entry in utxo_result.result_payload["utxos"]:
        identity = entry["identity"]
        assert identity["display_address_authoritative"] is False
        assert "outpoint" in identity["canonical"]
        assert "script_commitment" in identity["canonical"]
        assert identity["outpoint_key"]
        assert identity["script_commitment"].startswith("sha256:")


def test_coinbase_preserved() -> None:
    result = convert_bitcoin_payload(_coinbase_observation())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["is_coinbase"] is True
    assert result.result_payload["fee"] is None
    assert result.result_payload["inputs"][0]["is_coinbase"] is True
    assert result.result_payload["inputs"][0]["outpoint"] is None
    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.FINALIZED.value
    assert observed["attributes"]["is_coinbase"] is True


def test_replacement_preserved() -> None:
    result = convert_bitcoin_payload(
        _full_observation(
            status="replaced",
            replaces=TXID_B,
            replaced_by=TXID_C,
            finality="replaced",
            retraction="superseded",
            confirmations=0,
        )
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    replacement = result.result_payload["replacement"]
    assert replacement["replaces"] == TXID_B
    assert replacement["replaced_by"] == TXID_C
    assert replacement["status"] == "replaced"
    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.RETRACTED.value
    assert observed["retraction"] == RetractionStatus.SUPERSEDED.value


def test_reorg_state_preserved() -> None:
    result = convert_bitcoin_payload(
        _full_observation(
            status="orphaned",
            finality="reorged",
            retraction="retracted",
            reorg_depth=3,
            confirmations=0,
        )
    )
    reorg = result.result_payload["reorg_state"]
    assert reorg["reorg_depth"] == 3
    assert reorg["finality"] == FinalityStatus.REORGED.value
    assert reorg["is_orphaned"] is True
    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.REORGED.value
    assert observed["retraction"] == RetractionStatus.RETRACTED.value
    assert observed["provenance"]["observation"]["reorg_depth"] == 3


def test_confirmations_map_to_finality() -> None:
    assert map_finality(None, confirmations=0, status=None) is FinalityStatus.UNKNOWN
    from ipfs_datasets_py.logic.crypto_ir.adapters.bitcoin import TxStatus

    assert (
        map_finality(None, confirmations=1, status=TxStatus.CONFIRMED)
        is FinalityStatus.CONFIRMED
    )
    assert (
        map_finality(None, confirmations=100, status=TxStatus.CONFIRMED)
        is FinalityStatus.FINALIZED
    )
    assert (
        map_finality(None, confirmations=None, status=TxStatus.MEMPOOL)
        is FinalityStatus.PROPOSED
    )


def test_rejects_float_sats_on_observation() -> None:
    with pytest.raises(BitcoinAdapterError):
        BitcoinTransactionObservation.from_dict(
            _full_observation(fee_sats=1.5)  # type: ignore[arg-type]
        )


def test_rejects_malformed_txid() -> None:
    with pytest.raises(BitcoinAdapterError):
        BitcoinTransactionObservation.from_dict(
            _full_observation(txid="not-hex")
        )


def test_authority_not_elevated_on_round_trip() -> None:
    result = convert_bitcoin_payload(_full_observation())
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION
    # Observations must not become authorization.
    assert result.result_authority is not AuthorityKind.AUTHORIZATION


def test_authorization_source_rejected() -> None:
    result = convert_bitcoin_payload(
        _full_observation(),
        source_provenance={
            "authority": {"kind": "authorization"},
            "producer_id": "guard",
        },
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("authorization" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# UTXO set conversion
# ---------------------------------------------------------------------------


def test_utxo_set_identity_vectors() -> None:
    result = convert_bitcoin_payload(_utxo_set())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["record_type"] == "bitcoin_utxo_set"
    assert result.result_payload["utxo_count"] == 2
    assert result.result_payload["chain"]["network"] == MAINNET_NETWORK

    first = result.result_payload["utxos"][0]
    assert first["outpoint"]["txid"] == TXID_A
    assert first["value_sats"] == "50000"
    assert first["amount"]["base_units"] == "50000"
    assert first["amount"]["decimals"] == 8
    assert first["identity"]["outpoint_key"] == f"{TXID_A}:0"
    assert first["identity"]["script_commitment"] == script_commitment(P2WPKH_SCRIPT)
    assert first["confirmations"] == 1000

    second = result.result_payload["utxos"][1]
    assert second["spending_condition"]["script_type"] == "p2tr"
    assert second["spending_condition"]["is_taproot"] is True


def test_utxo_entry_structured_round_trip() -> None:
    entry = UtxoEntry(
        outpoint=Outpoint(txid=TXID_A, vout=0),
        value_sats="42",
        spending_condition=SpendingCondition(
            script_type=ScriptType.P2WPKH,
            script_hex=P2WPKH_SCRIPT,
        ),
        created_by=TXID_A,
        created_height=1,
        confirmations=2,
    )
    restored = UtxoEntry.from_dict(entry.to_dict())
    assert restored.outpoint.key == entry.outpoint.key
    assert restored.value_sats == "42"
    assert restored.spending_condition.script_commitment == (
        entry.spending_condition.script_commitment
    )


# ---------------------------------------------------------------------------
# Spend intent
# ---------------------------------------------------------------------------


def test_spend_intent_conversion() -> None:
    result = convert_bitcoin_payload(_spend_intent())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.source_authority is AuthorityKind.DECLARATION
    assert result.result_authority is AuthorityKind.DECLARATION
    assert result.result_payload["record_type"] == "bitcoin_spend_intent"
    assert result.result_payload["display_address_authoritative"] is False
    assert result.result_payload["script_execution"] is False

    unsigned = UnsignedTransactionIntent.from_dict(
        result.result_payload["unsigned_transaction_intent"]
    )
    assert unsigned.intent_id == "intent-1"
    assert unsigned.chain.network == MAINNET_NETWORK
    assert len(unsigned.transfers) == 1
    assert unsigned.transfers[0].amount.base_units == "9500"
    assert unsigned.attributes["fee_sats"] == "500"
    assert unsigned.attributes["display_address_authoritative"] is False

    inputs = result.result_payload["inputs"]
    assert inputs[0]["outpoint"]["txid"] == TXID_A
    assert inputs[0]["previous_output_known"] is True


def test_spend_intent_with_incomplete_prevout_is_partial() -> None:
    result = convert_bitcoin_payload(
        _spend_intent(
            inputs=[
                {
                    "previous_output": {"txid": TXID_A, "vout": 0},
                    # no prevout value/script
                }
            ]
        )
    )
    assert result.status is AdapterConversionStatus.PARTIAL
    assert "inputs[0].previous_output" in result.result_payload["missing_coverage"]


def test_spend_intent_structured_record() -> None:
    intent = BitcoinSpendIntent.from_dict(_spend_intent())
    result = convert_bitcoin_payload(intent)
    assert result.status is AdapterConversionStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Serialized candidate (no script execution)
# ---------------------------------------------------------------------------


def test_serialized_candidate_preserved_without_parsing() -> None:
    raw = "020000000001" + "00" * 20
    result = convert_bitcoin_payload(
        {
            "kind": "serialized_candidate",
            "candidate_id": "cand-1",
            "intent_id": "intent-raw-1",
            "network": MAINNET_NETWORK,
            "raw_hex": raw,
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["script_execution"] is False
    assert result.result_payload["raw_hex"] == raw
    assert result.result_payload["payload_digest"].startswith("sha256:")
    candidate = result.result_payload["serialized_transaction_candidate"]
    assert candidate["byte_length"] == len(raw) // 2
    assert candidate["encoding"] == "bitcoin-tx-hex"


# ---------------------------------------------------------------------------
# Networks remain distinct under conversion
# ---------------------------------------------------------------------------


def test_regtest_distinct_from_mainnet() -> None:
    main = convert_bitcoin_payload(_full_observation())
    reg = convert_bitcoin_payload(
        _full_observation(
            observation_id="obs-reg",
            network=REGTEST_NETWORK,
            genesis_hash=REGTEST_GENESIS,
        )
    )
    assert main.result_payload["chain"]["network"] != reg.result_payload["chain"]["network"]
    assert (
        main.result_payload["chain"]["genesis_digest"]
        != reg.result_payload["chain"]["genesis_digest"]
    )


def test_testnet_alias_resolves() -> None:
    anchor = resolve_network(network="testnet")
    assert anchor.network == TESTNET_NETWORK
    assert anchor.genesis_hash == TESTNET_GENESIS


# ---------------------------------------------------------------------------
# Structured observation round-trip
# ---------------------------------------------------------------------------


def test_transaction_observation_structured_round_trip() -> None:
    obs = BitcoinTransactionObservation.from_dict(_full_observation())
    assert obs.is_coinbase is False
    assert len(obs.inputs) == 1
    assert obs.inputs[0].witness[0] == WITNESS_SIG
    restored = BitcoinTransactionObservation.from_dict(obs.to_dict())
    assert restored.txid == obs.txid
    assert restored.fee_sats == "1500"
    result = convert_bitcoin_payload(obs)
    assert result.status is AdapterConversionStatus.SUCCEEDED


def test_utxo_set_structured_round_trip() -> None:
    obs = BitcoinUtxoSetObservation.from_dict(_utxo_set())
    restored = BitcoinUtxoSetObservation.from_dict(obs.to_dict())
    assert len(restored.utxos) == 2
    result = convert_bitcoin_payload(obs)
    assert result.status is AdapterConversionStatus.SUCCEEDED


def test_convert_helper_matches_adapter() -> None:
    adapter = BitcoinWalletAdapter()
    payload = _full_observation()
    a = adapter.convert(payload)
    b = convert_bitcoin_payload(payload, adapter=adapter)
    assert a.status is b.status
    assert a.result_digest == b.result_digest

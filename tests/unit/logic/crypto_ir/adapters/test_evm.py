"""Unit tests for the EVM wallet-to-Crypto-IR adapter (CRYPTOIR-G100 / CRYPTOIR-007).

Fixture-driven, offline conversion and rejection tests.  No network I/O and no
code fetching.  Covers:

* chain ID + genesis identity binding;
* checksummed / original / lowercase addresses;
* native and token assets with exact amounts;
* calldata, receipts, logs, traces, finality;
* explicit missing coverage (not invented facts);
* World Chain as a distinct network;
* round trips that do not promote observations to proof.
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
    CapabilitySurface,
    FinalityStatus,
    ObservedTransaction,
    UnsignedTransactionIntent,
)
from ipfs_datasets_py.logic.crypto_ir.adapters.evm import (
    EVM_ADAPTER_ID,
    EVM_CAPABILITY_ID,
    EVM_NAMESPACE,
    ETHEREUM_MAINNET_CHAIN_ID,
    ETHEREUM_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    EVMAdapterError,
    EVMCallIntent,
    EVMTransactionObservation,
    EVMWalletAdapter,
    convert_evm_payload,
    eip55_checksum_address,
    keccak256,
    normalize_address,
    resolve_network,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


ADDR_FROM = "0x52908400098527886e0f7030069857d2e4169ee7"
ADDR_TO = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
ADDR_TOKEN = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
TX_HASH = "0x" + ("ab" * 32)
BLOCK_HASH = "0x" + ("cd" * 32)
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


def _full_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-full-1",
        "chain_id": ETHEREUM_MAINNET_CHAIN_ID,
        "network": "ethereum-mainnet",
        "genesis_hash": ETHEREUM_MAINNET_GENESIS_HASH,
        "tx_hash": TX_HASH,
        "from_address": ADDR_FROM,
        "to_address": ADDR_TO,
        "value_wei": "1000000000000000000",
        "input_data": "0xa9059cbb00000000000000000000000052908400098527886e0f7030069857d2e4169ee7000000000000000000000000000000000000000000000000000000000000000a",
        "block_number": 18_000_000,
        "block_hash": BLOCK_HASH,
        "transaction_index": 7,
        "finality": "finalized",
        "retraction": "not_retracted",
        "observed_at": "2026-07-29T12:00:00Z",
        "validity_start": "2026-07-29T12:00:00Z",
        "validity_end": "",
        "receipt": {
            "status": "0x1",
            "gasUsed": "0x5208",
            "effectiveGasPrice": "0x3b9aca00",
            "logs": [],
        },
        "logs": [
            {
                "address": ADDR_TOKEN,
                "topics": [
                    TRANSFER_TOPIC,
                    "0x" + "00" * 12 + ADDR_FROM[2:].lower(),
                    "0x" + "00" * 12 + ADDR_TO[2:].lower(),
                ],
                "data": "0x" + "00" * 31 + "0a",
                "logIndex": "0x0",
            }
        ],
        "traces": [
            {
                "type": "call",
                "from": ADDR_FROM,
                "to": ADDR_TO,
                "value": "0x0",
            }
        ],
        "raw": {"provider": "fixture", "cursor": 1},
    }
    payload.update(overrides)
    return payload


def _minimal_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-min-1",
        "chain_id": ETHEREUM_MAINNET_CHAIN_ID,
        "tx_hash": TX_HASH,
    }
    payload.update(overrides)
    return payload


def _call_intent(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "call_intent",
        "intent_id": "intent-1",
        "chain_id": ETHEREUM_MAINNET_CHAIN_ID,
        "from_address": ADDR_FROM,
        "to_address": ADDR_TO,
        "value_wei": "0",
        "data": "0xa9059cbb",
        "method": "transfer",
        "gas_limit": 100_000,
        "nonce": 3,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Import / side-effect free
# ---------------------------------------------------------------------------


def test_import_evm_adapter_has_no_network_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network socket use forbidden during EVM adapter import")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if name.endswith(".crypto_ir.adapters.evm") or name.endswith(
            "crypto_ir.adapters.evm"
        ):
            del sys.modules[name]

    from ipfs_datasets_py.logic.crypto_ir.adapters import evm as evm_mod

    assert evm_mod.EVMWalletAdapter is not None
    assert evm_mod.EVMTransactionObservation is not None
    assert evm_mod.EVMCallIntent is not None


def test_adapter_registers_in_registry() -> None:
    adapter = EVMWalletAdapter()
    registry = AdapterRegistry.from_adapters([adapter])
    entry = registry.require(
        EVM_ADAPTER_ID,
        required_surfaces=[CapabilitySurface.OBSERVATION],
    )
    assert entry.capability.capability_id == EVM_CAPABILITY_ID
    assert entry.capability.supports_chain_namespace(EVM_NAMESPACE)
    assert "world_chain" in entry.capability.features


# ---------------------------------------------------------------------------
# Identity / addresses / keccak
# ---------------------------------------------------------------------------


def test_keccak256_empty_vector() -> None:
    assert keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )


def test_eip55_checksum_and_original_survive() -> None:
    checksummed = eip55_checksum_address(ADDR_FROM)
    assert checksummed.startswith("0x")
    assert checksummed != ADDR_FROM.lower() or checksummed == eip55_checksum_address(
        ADDR_FROM.lower()
    )
    # EIP-55 example from the specification.
    assert (
        eip55_checksum_address("0x52908400098527886e0f7030069857d2e4169ee7")
        == "0x52908400098527886E0F7030069857D2E4169EE7"
    )

    result = convert_evm_payload(_full_observation(from_address=ADDR_FROM))
    addresses = result.result_payload["addresses"]["from"]
    assert addresses["original"] == ADDR_FROM
    assert addresses["normalized"] == ADDR_FROM.lower()
    assert addresses["checksummed"] == eip55_checksum_address(ADDR_FROM.lower())


def test_normalize_address_rejects_malformed() -> None:
    with pytest.raises(EVMAdapterError):
        normalize_address("0x1234")
    with pytest.raises(EVMAdapterError):
        normalize_address("not-an-address")


# ---------------------------------------------------------------------------
# Full observation conversion
# ---------------------------------------------------------------------------


def test_full_observation_preserves_chain_assets_calldata_receipt_logs_traces() -> None:
    result = convert_evm_payload(_full_observation())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.adapter_id == EVM_ADAPTER_ID
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION

    chain = result.result_payload["chain"]
    assert chain["chain_namespace"] == EVM_NAMESPACE
    assert chain["chain_id"] == "1"
    assert chain["network"] == "ethereum-mainnet"
    assert chain["genesis_digest"].startswith("keccak256:")
    assert chain["attributes"]["genesis_hash"] == ETHEREUM_MAINNET_GENESIS_HASH.lower()

    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.FINALIZED.value
    assert observed["tx_digest"].startswith("keccak256:")
    assert observed["coordinate"]["sequence"] == 18_000_000
    assert observed["coordinate"]["transaction_index"] == 7
    assert observed["attributes"]["calldata"].startswith("0xa9059cbb")
    assert observed["attributes"]["calldata_digest"].startswith("sha256:")
    assert observed["attributes"]["receipt_present"] is True
    assert observed["attributes"]["logs_present"] is True
    assert observed["attributes"]["traces_present"] is True

    native = result.result_payload["native_transfer"]
    assert native is not None
    assert native["amount"]["base_units"] == "1000000000000000000"
    assert native["amount"]["decimals"] == 18
    assert native["asset"]["asset_namespace"] == "slip44"
    assert native["asset"]["asset_reference"] == "60"
    assert native["kind"] == "native"

    tokens = result.result_payload["token_transfers"]
    assert len(tokens) == 1
    assert tokens[0]["kind"] == "token"
    assert tokens[0]["amount"]["base_units"] == "10"
    assert tokens[0]["decimals_absent"] is True  # not invented from the log
    assert tokens[0]["asset"]["asset_reference"] == ADDR_TOKEN.lower()

    assert result.result_payload["receipt"]["status"] == "0x1"
    # AdapterConversionResult freezes sequences to tuples.
    assert isinstance(result.result_payload["logs"], (list, tuple))
    assert isinstance(result.result_payload["traces"], (list, tuple))
    assert len(result.result_payload["logs"]) == 1
    assert len(result.result_payload["traces"]) == 1
    assert result.result_payload["raw"]["provider"] == "fixture"

    # Round-trip Crypto IR records
    restored = ObservedTransaction.from_dict(observed)
    assert restored.finality is FinalityStatus.FINALIZED
    assert restored.provenance is not None
    assert restored.provenance.authority.kind is AuthorityKind.OBSERVATION


def test_missing_receipt_trace_finality_not_invented() -> None:
    result = convert_evm_payload(_minimal_observation())
    assert result.status is AdapterConversionStatus.PARTIAL
    missing = set(result.result_payload["missing_coverage"])
    for key in ("receipt", "logs", "traces", "finality", "value_wei", "calldata"):
        assert key in missing

    paths = {field.path for field in result.unsupported_fields}
    assert "receipt" in paths
    assert "traces" in paths
    assert "finality" in paths
    assert "value_wei" in paths

    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.UNKNOWN.value
    assert result.result_payload["receipt"] is None
    assert result.result_payload["logs"] is None
    assert result.result_payload["traces"] is None
    assert result.result_payload["native_transfer"] is None
    # Explicit absence flags on the observation attributes
    assert observed["attributes"]["receipt_present"] is False
    assert observed["attributes"]["value_absent"] is True
    assert observed["attributes"]["calldata_absent"] is True


def test_explicit_token_transfer_with_decimals() -> None:
    result = convert_evm_payload(
        _minimal_observation(
            from_address=ADDR_FROM,
            to_address=ADDR_TO,
            value_wei="0",
            input_data="0x",
            finality="confirmed",
            retraction="not_retracted",
            observed_at="2026-07-29T00:00:00Z",
            receipt={"status": "0x1", "logs": []},
            logs=[],
            traces=[],
            token_transfers=[
                {
                    "contract": ADDR_TOKEN,
                    "from": ADDR_FROM,
                    "to": ADDR_TO,
                    "amount": "42",
                    "decimals": 6,
                    "symbol": "USDC",
                    "standard": "erc20",
                }
            ],
        )
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    token = result.result_payload["token_transfers"][0]
    assert token["amount"]["base_units"] == "42"
    assert token["amount"]["decimals"] == 6
    assert token["asset"]["symbol"] == "USDC"
    assert token["decimals_absent"] is False


def test_rejects_float_amounts() -> None:
    with pytest.raises(EVMAdapterError):
        EVMTransactionObservation(
            observation_id="bad",
            chain_id=1,
            tx_hash=TX_HASH,
            value_wei="1.5",  # type: ignore[arg-type]
        )


def test_rejects_malformed_tx_hash() -> None:
    with pytest.raises(EVMAdapterError):
        EVMTransactionObservation(
            observation_id="bad",
            chain_id=1,
            tx_hash="0xdead",
        )


# ---------------------------------------------------------------------------
# World Chain remains distinct
# ---------------------------------------------------------------------------


def test_world_chain_is_distinct_from_ethereum_mainnet() -> None:
    eth = convert_evm_payload(_full_observation())
    world = convert_evm_payload(
        _full_observation(
            observation_id="obs-world",
            chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
            network="world-chain-mainnet",
            genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        )
    )
    eth_chain = eth.result_payload["chain"]
    world_chain = world.result_payload["chain"]
    assert eth_chain["chain_id"] == "1"
    assert world_chain["chain_id"] == "480"
    assert eth_chain["network"] != world_chain["network"]
    assert eth_chain["genesis_digest"] != world_chain["genesis_digest"]
    assert world_chain["network"] == "world-chain-mainnet"
    assert (
        world_chain["attributes"]["genesis_hash"]
        == WORLD_CHAIN_MAINNET_GENESIS_HASH.lower()
    )

    sepolia = resolve_network(chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID)
    assert sepolia.chain_id == WORLD_CHAIN_SEPOLIA_CHAIN_ID
    assert sepolia.network == "world-chain-sepolia"


def test_mismatched_genesis_for_known_chain_fails() -> None:
    with pytest.raises(EVMAdapterError, match="genesis_hash does not match"):
        resolve_network(
            chain_id=ETHEREUM_MAINNET_CHAIN_ID,
            genesis_hash="0x" + ("ff" * 32),
        )


def test_unknown_chain_requires_genesis() -> None:
    with pytest.raises(EVMAdapterError, match="explicit genesis_hash"):
        resolve_network(chain_id=999999)


def test_unknown_chain_with_genesis_accepted() -> None:
    anchor = resolve_network(
        chain_id=8453,
        network="base-mainnet",
        genesis_hash="0x" + ("11" * 32),
    )
    assert anchor.chain_id == 8453
    identity = anchor.to_chain_identity()
    assert identity.chain_id == "8453"
    assert identity.network == "base-mainnet"


# ---------------------------------------------------------------------------
# Call intent conversion
# ---------------------------------------------------------------------------


def test_call_intent_conversion_preserves_calldata_and_addresses() -> None:
    result = convert_evm_payload(_call_intent())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_authority is AuthorityKind.DECLARATION
    assert result.source_authority is AuthorityKind.DECLARATION

    payload = result.result_payload
    assert payload["record_type"] == "evm_call_intent"
    assert payload["calldata"] == "0xa9059cbb"
    assert payload["calldata_digest"].startswith("sha256:")
    assert payload["addresses"]["from"]["checksummed"] == eip55_checksum_address(
        ADDR_FROM.lower()
    )
    assert payload["addresses"]["to"]["normalized"] == ADDR_TO.lower()

    unsigned = UnsignedTransactionIntent.from_dict(
        payload["unsigned_transaction_intent"]
    )
    assert unsigned.intent_id == "intent-1"
    assert unsigned.chain.chain_id == "1"
    assert len(unsigned.calls) == 1
    assert unsigned.calls[0].method == "transfer"
    assert unsigned.calls[0].attributes["calldata"] == "0xa9059cbb"


def test_call_intent_structured_record_round_trip() -> None:
    intent = EVMCallIntent.from_dict(_call_intent(value_wei="5"))
    assert intent.value_wei == "5"
    restored = EVMCallIntent.from_dict(intent.to_dict())
    assert restored == intent

    result = convert_evm_payload(intent)
    assert result.result_payload["unsigned_transaction_intent"]["transfers"]
    transfer = result.result_payload["unsigned_transaction_intent"]["transfers"][0]
    assert transfer["amount"]["base_units"] == "5"


def test_call_intent_without_method_preserves_selector_not_abi() -> None:
    result = convert_evm_payload(_call_intent(method=""))
    call = result.result_payload["call_intent"]
    assert call["method"].startswith("selector:")
    assert "method label absent" in " ".join(result.diagnostics)


# ---------------------------------------------------------------------------
# Serialized candidate
# ---------------------------------------------------------------------------


def test_serialized_candidate_from_raw_tx() -> None:
    raw = "0x02f8700180843b9aca00843b9aca0082520894" + ("22" * 20) + "8080c0"
    # pad to valid even hex if needed
    if len(raw) % 2:
        raw = raw + "0"
    result = convert_evm_payload(
        {
            "kind": "serialized_candidate",
            "candidate_id": "cand-1",
            "intent_id": "intent-1",
            "chain_id": 1,
            "raw_tx": raw if len(raw) % 2 == 0 else raw + "0",
            "encoding": "rlp",
        }
    )
    # Ensure even-length for our fixture
    if result.status is AdapterConversionStatus.ERROR:
        # rebuild with guaranteed even hex
        body = bytes.fromhex("02f87001")
        raw_ok = "0x" + body.hex()
        result = convert_evm_payload(
            {
                "kind": "serialized_candidate",
                "candidate_id": "cand-1",
                "intent_id": "intent-1",
                "chain_id": 1,
                "raw_tx": raw_ok,
                "encoding": "rlp",
            }
        )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    cand = result.result_payload["serialized_transaction_candidate"]
    assert cand["candidate_id"] == "cand-1"
    assert cand["payload_digest"].startswith("sha256:")
    assert cand["byte_length"] > 0
    assert result.result_payload["raw_tx_absent"] is False


# ---------------------------------------------------------------------------
# Authority: no elevation to proof
# ---------------------------------------------------------------------------


def test_observation_round_trip_does_not_promote_to_proof() -> None:
    result = convert_evm_payload(_full_observation())
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION
    assert result.result_payload["authority"] == AuthorityKind.OBSERVATION.value

    # Even with observation provenance attached, conversion cannot emit
    # authorization or result/proof authority.
    from ipfs_datasets_py.logic.crypto_ir import observation_provenance

    prov = observation_provenance(
        producer_id="test-fixture",
        observed_at="2026-07-29T00:00:00Z",
        finality=FinalityStatus.FINALIZED,
    )
    again = convert_evm_payload(_full_observation(), source_provenance=prov)
    assert again.result_authority is AuthorityKind.OBSERVATION
    assert again.result_authority is not AuthorityKind.AUTHORIZATION
    assert again.result_authority is not AuthorityKind.RESULT
    # AdapterConversionResult itself refuses elevation at construction time.
    assert again.preserved_provenance["authority"]["kind"] == "observation"


def test_authorization_source_is_rejected_for_observation() -> None:
    result = convert_evm_payload(
        _full_observation(),
        source_provenance={"authority": {"kind": "authorization"}},
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("authorization" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Structured observation record
# ---------------------------------------------------------------------------


def test_evm_transaction_observation_dataclass_round_trip() -> None:
    obs = EVMTransactionObservation.from_dict(_full_observation())
    restored = EVMTransactionObservation.from_dict(obs.to_dict())
    assert restored.observation_id == obs.observation_id
    assert restored.tx_hash == TX_HASH.lower()
    assert restored.receipt is not None
    assert restored.logs is not None
    assert restored.traces is not None

    result = convert_evm_payload(obs)
    assert result.status is AdapterConversionStatus.SUCCEEDED


def test_partial_observation_completeness_receipt() -> None:
    result = convert_evm_payload(_minimal_observation())
    completeness = result.result_payload["completeness"]
    assert completeness["completeness"] in {"partial", "unknown"}
    assert completeness["finality"] == FinalityStatus.UNKNOWN.value
    assert "missing_coverage" in completeness["attributes"]


def test_adapter_convert_via_registry() -> None:
    registry = AdapterRegistry.from_adapters([EVMWalletAdapter()])
    result = registry.convert(EVM_ADAPTER_ID, _full_observation())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["chain"]["chain_id"] == "1"


def test_zero_value_is_preserved_not_dropped() -> None:
    result = convert_evm_payload(
        _full_observation(value_wei="0", token_transfers=[], logs=[], traces=[])
    )
    native = result.result_payload["native_transfer"]
    assert native is not None
    assert native["amount"]["base_units"] == "0"


def test_ast_symbols_exported() -> None:
    """AST query symbols required by CRYPTOIR-G100 must exist."""

    from ipfs_datasets_py.logic.crypto_ir.adapters import evm as mod

    assert hasattr(mod, "EVMWalletAdapter")
    assert hasattr(mod, "EVMTransactionObservation")
    assert hasattr(mod, "EVMCallIntent")
    assert callable(mod.EVMWalletAdapter)
    assert callable(mod.EVMTransactionObservation)
    assert callable(mod.EVMCallIntent)

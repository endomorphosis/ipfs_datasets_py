"""Unit tests for the XRPL/Xaman wallet-to-Crypto-IR adapter (CRYPTOIR-G120 / CRYPTOIR-009).

Fixture-driven, offline conversion and rejection tests.  No network I/O.
Covers:

* classic / X-address + destination tag lossless identity;
* XRP vs issued-asset non-collision;
* issuer, flags, delivered amount, partial-payment, sequence/ticket, signer,
  validated-ledger typed facts;
* Hooks and EVM never inferred without capability evidence;
* Xaman shared conversion path;
* authority never elevated to proof/authorization;
* native ledger transitions (not Ethereum-shaped contracts).
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
    UnsignedTransactionIntent,
)
from ipfs_datasets_py.logic.crypto_ir.adapters.xrpl import (
    DROPS_PER_XRP,
    NATIVE_ASSET_REFERENCE,
    NATIVE_DECIMALS,
    TF_PARTIAL_PAYMENT,
    XRPL_ADAPTER_ID,
    XRPL_CAPABILITY_ID,
    XRPL_MAINNET_CHAIN_ID,
    XRPL_MAINNET_GENESIS_HASH,
    XRPL_NAMESPACE,
    XRPL_TESTNET_CHAIN_ID,
    XRPL_TESTNET_GENESIS_HASH,
    IssuedAsset,
    LedgerTransition,
    XRPLAccountIdentity,
    XRPLAdapterError,
    XRPLPaymentIntent,
    XRPLTransactionObservation,
    XRPLTransitionKind,
    XRPLWalletAdapter,
    classic_address_from_account_id,
    convert_xrpl_payload,
    decode_x_address,
    encode_x_address,
    has_partial_payment,
    native_xrp_asset,
    parse_amount,
    resolve_network,
)


# ---------------------------------------------------------------------------
# Deterministic offline fixtures (checksummed classic addresses)
# ---------------------------------------------------------------------------


def _addr(seed: int) -> str:
    """Build a classic address from a 20-byte account id derived from *seed*."""

    account_id = bytes((seed + i) % 256 for i in range(20))
    return classic_address_from_account_id(account_id)


ADDR_A = _addr(1)
ADDR_B = _addr(2)
ADDR_ISSUER = _addr(3)
TX_HASH = "A" * 64
LEDGER_HASH = "B" * 64


def _full_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-xrpl-1",
        "chain_id": XRPL_MAINNET_CHAIN_ID,
        "network": "xrpl-mainnet",
        "genesis_hash": XRPL_MAINNET_GENESIS_HASH,
        "transaction_hash": TX_HASH,
        "account": ADDR_A,
        "destination": ADDR_B,
        "destination_tag": 42,
        "transaction_type": "Payment",
        "amount": "1000000",  # 1 XRP in drops
        "delivered_amount": "1000000",
        "fee_drops": "12",
        "flags": 0,
        "sequence": 7,
        "ledger_index": 80_000_000,
        "ledger_hash": LEDGER_HASH,
        "transaction_index": 3,
        "validated": True,
        "finality": "validated",
        "retraction": "not_retracted",
        "engine_result": "tesSUCCESS",
        "observed_at": "2026-07-29T12:00:00Z",
        "validity_start": "2026-07-29T12:00:00Z",
        "validity_end": "",
        "signers": [],
        "meta": {
            "TransactionResult": "tesSUCCESS",
            "delivered_amount": "1000000",
        },
        "wallet_source": "xrpl",
        "raw": {"provider": "fixture", "cursor": 1},
    }
    payload.update(overrides)
    return payload


def _minimal_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-min-1",
        "chain_id": XRPL_MAINNET_CHAIN_ID,
        "account": ADDR_A,
        "transaction_hash": TX_HASH,
    }
    payload.update(overrides)
    return payload


def _payment_intent(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "payment_intent",
        "intent_id": "intent-1",
        "chain_id": XRPL_MAINNET_CHAIN_ID,
        "account": ADDR_A,
        "destination": ADDR_B,
        "destination_tag": 99,
        "amount": "500000",
        "fee_drops": "12",
        "flags": 0,
        "sequence": 3,
        "transaction_type": "Payment",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Import / side-effect free
# ---------------------------------------------------------------------------


def test_import_xrpl_adapter_has_no_network_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network socket use forbidden during XRPL adapter import")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if name.endswith(".crypto_ir.adapters.xrpl") or name.endswith(
            "crypto_ir.adapters.xrpl"
        ):
            del sys.modules[name]

    from ipfs_datasets_py.logic.crypto_ir.adapters import xrpl as xrpl_mod

    assert xrpl_mod.XRPLWalletAdapter is not None
    assert xrpl_mod.XRPLAccountIdentity is not None
    assert xrpl_mod.IssuedAsset is not None
    assert xrpl_mod.LedgerTransition is not None


def test_adapter_registers_in_registry() -> None:
    adapter = XRPLWalletAdapter()
    registry = AdapterRegistry.from_adapters([adapter])
    entry = registry.require(
        XRPL_ADAPTER_ID,
        required_surfaces=[],
    )
    assert entry.capability.capability_id == XRPL_CAPABILITY_ID
    assert entry.capability.supports_chain_namespace(XRPL_NAMESPACE)
    assert "xaman" in entry.capability.features
    assert "partial_payment" in entry.capability.features


# ---------------------------------------------------------------------------
# Address / tag identity (lossless)
# ---------------------------------------------------------------------------


def test_classic_and_x_address_round_trip_preserves_tag() -> None:
    x_addr = encode_x_address(ADDR_A, tag=12345, test=False)
    classic, tag, is_test = decode_x_address(x_addr)
    assert classic == ADDR_A
    assert tag == 12345
    assert is_test is False

    identity = XRPLAccountIdentity.parse(x_addr)
    assert identity.classic_address == ADDR_A
    assert identity.destination_tag == 12345
    assert identity.x_address == x_addr
    assert identity.address_original == x_addr
    assert identity.address_normalized == f"{ADDR_A}:12345"

    # Classic + separate tag is also lossless.
    classic_id = XRPLAccountIdentity.parse(ADDR_B, destination_tag=7)
    assert classic_id.destination_tag == 7
    assert classic_id.x_address  # synthesized
    decoded_classic, decoded_tag, _ = decode_x_address(classic_id.x_address)
    assert decoded_classic == ADDR_B
    assert decoded_tag == 7


def test_x_address_testnet_flag() -> None:
    x_test = encode_x_address(ADDR_A, tag=1, test=True)
    assert x_test.startswith("T")
    _, _, is_test = decode_x_address(x_test)
    assert is_test is True


def test_account_identity_in_conversion_is_lossless() -> None:
    x_dest = encode_x_address(ADDR_B, tag=42, test=False)
    result = convert_xrpl_payload(
        _full_observation(destination=x_dest, destination_tag=None)
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    dest = result.result_payload["accounts"]["destination"]
    assert dest["classic_address"] == ADDR_B
    assert dest["destination_tag"] == 42
    assert dest["x_address"] == x_dest
    assert dest["address_original"] == x_dest
    assert dest["address_normalized"] == f"{ADDR_B}:42"


def test_rejects_malformed_classic_address() -> None:
    with pytest.raises(XRPLAdapterError):
        XRPLAccountIdentity.parse("not-an-address")
    with pytest.raises(XRPLAdapterError):
        XRPLAccountIdentity.parse("rtooShort")


# ---------------------------------------------------------------------------
# XRP vs issued assets cannot collide
# ---------------------------------------------------------------------------


def test_xrp_and_issued_assets_cannot_collide() -> None:
    chain = resolve_network(chain_id=XRPL_MAINNET_CHAIN_ID).to_chain_identity()
    xrp = native_xrp_asset(chain)
    issued = IssuedAsset(issuer=ADDR_ISSUER, currency="USD")
    issued_ai = issued.to_asset_identity(chain)

    assert xrp.asset_namespace == "slip44"
    assert xrp.asset_reference == NATIVE_ASSET_REFERENCE
    assert xrp.attributes["native"] is True
    assert issued_ai.asset_namespace == "xrpl-issued"
    assert issued_ai.asset_reference == f"{ADDR_ISSUER}/USD"
    assert issued_ai.attributes["native"] is False
    # Distinct identities
    assert (xrp.asset_namespace, xrp.asset_reference) != (
        issued_ai.asset_namespace,
        issued_ai.asset_reference,
    )

    with pytest.raises(XRPLAdapterError, match="cannot be an IssuedAsset"):
        IssuedAsset(issuer=ADDR_ISSUER, currency="XRP")

    with pytest.raises(XRPLAdapterError, match="drops string"):
        parse_amount(
            {"currency": "XRP", "issuer": ADDR_ISSUER, "value": "1"},
            field="Amount",
        )


def test_issued_payment_preserves_issuer_currency() -> None:
    amount = {
        "currency": "USD",
        "issuer": ADDR_ISSUER,
        "value": "25.5",
    }
    result = convert_xrpl_payload(
        _full_observation(
            amount=amount,
            delivered_amount={
                "currency": "USD",
                "issuer": ADDR_ISSUER,
                "value": "25.5",
            },
            flags=0,
        )
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    transfer = result.result_payload["transfer"]
    assert transfer["kind"] == "issued"
    assert transfer["issued_asset"]["issuer"] == ADDR_ISSUER
    assert transfer["issued_asset"]["currency"] == "USD"
    assert transfer["amount"]["base_units"] == "25.5"
    assert result.result_payload["issued_asset"]["asset_reference"] == (
        f"{ADDR_ISSUER}/USD"
    )
    # Native XRP asset still distinct in payload
    native = result.result_payload["native_xrp_asset"]
    assert native["asset_reference"] == NATIVE_ASSET_REFERENCE


# ---------------------------------------------------------------------------
# Full observation conversion — typed facts
# ---------------------------------------------------------------------------


def test_full_observation_preserves_typed_ledger_facts() -> None:
    result = convert_xrpl_payload(_full_observation())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.adapter_id == XRPL_ADAPTER_ID
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION

    chain = result.result_payload["chain"]
    assert chain["chain_namespace"] == XRPL_NAMESPACE
    assert chain["chain_id"] == XRPL_MAINNET_CHAIN_ID
    assert chain["network"] == "xrpl-mainnet"
    assert chain["attributes"]["native_model"] == "ledger_state_transitions"

    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.FINALIZED.value
    assert observed["coordinate"]["sequence"] == 80_000_000
    assert observed["coordinate"]["transaction_index"] == 3
    assert observed["attributes"]["partial_payment"] is False
    assert observed["attributes"]["sequence"] == 7
    assert observed["attributes"]["not_evm_shaped"] is True

    transfer = result.result_payload["transfer"]
    assert transfer["kind"] == "xrp"
    assert transfer["amount"]["base_units"] == "1000000"
    assert transfer["amount"]["decimals"] == NATIVE_DECIMALS
    assert transfer["unit"] == "drops"

    facts = result.result_payload["typed_facts"]
    assert facts["flags"] == 0
    assert facts["partial_payment"] is False
    assert facts["sequence"] == 7
    assert facts["validated"] is True
    assert facts["engine_result"] == "tesSUCCESS"
    assert facts["fee_drops"] == "12"
    assert facts["ledger_hash"] == LEDGER_HASH

    lt = result.result_payload["ledger_transition"]
    assert lt["transaction_type"] == "Payment"
    assert lt["destination"]["destination_tag"] == 42

    restored = ObservedTransaction.from_dict(observed)
    assert restored.finality is FinalityStatus.FINALIZED
    assert restored.provenance is not None
    assert restored.provenance.authority.kind is AuthorityKind.OBSERVATION


def test_partial_payment_requires_delivered_amount() -> None:
    result = convert_xrpl_payload(
        _full_observation(
            flags=TF_PARTIAL_PAYMENT,
            amount="1000000",
            delivered_amount="750000",
            meta={
                "TransactionResult": "tesSUCCESS",
                "delivered_amount": "750000",
            },
        )
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["typed_facts"]["partial_payment"] is True
    assert has_partial_payment(TF_PARTIAL_PAYMENT)
    delivered = result.result_payload["delivered_amount"]
    assert delivered is not None
    assert delivered["amount"]["base_units"] == "750000"

    # Partial payment without delivered amount → partial / unsupported
    partial = convert_xrpl_payload(
        _full_observation(
            flags=TF_PARTIAL_PAYMENT,
            delivered_amount=None,
            meta={"TransactionResult": "tesSUCCESS"},
        )
    )
    assert partial.status is AdapterConversionStatus.PARTIAL
    paths = {f.path for f in partial.unsupported_fields}
    assert "delivered_amount" in paths
    assert "delivered_amount" in partial.result_payload["missing_coverage"]


def test_sequence_and_ticket_are_typed() -> None:
    result = convert_xrpl_payload(
        _full_observation(sequence=None, ticket_sequence=55)
    )
    assert result.result_payload["typed_facts"]["ticket_sequence"] == 55
    assert result.result_payload["typed_facts"]["sequence"] is None

    missing = convert_xrpl_payload(
        _minimal_observation(amount="1", sequence=None, ticket_sequence=None)
    )
    assert "sequence_or_ticket" in missing.result_payload["missing_coverage"]


def test_signer_list_preserved() -> None:
    signers = [
        {"Signer": {"Account": ADDR_A, "SigningPubKey": "AB", "TxnSignature": "CD"}},
        {"Signer": {"Account": ADDR_B, "SigningPubKey": "EF", "TxnSignature": "01"}},
    ]
    result = convert_xrpl_payload(
        _full_observation(signers=signers, signer_quorum=2)
    )
    facts = result.result_payload["typed_facts"]
    assert facts["signer_quorum"] == 2
    assert len(facts["signers"]) == 2
    assert facts["signers"][0]["Signer"]["Account"] == ADDR_A


def test_validated_ledger_maps_to_finalized() -> None:
    result = convert_xrpl_payload(
        _full_observation(validated=True, finality="")
    )
    assert (
        result.result_payload["observed_transaction"]["finality"]
        == FinalityStatus.FINALIZED.value
    )
    unvalidated = convert_xrpl_payload(
        _full_observation(validated=False, finality="")
    )
    assert (
        unvalidated.result_payload["observed_transaction"]["finality"]
        == FinalityStatus.PROPOSED.value
    )


def test_missing_facts_not_invented() -> None:
    result = convert_xrpl_payload(_minimal_observation())
    assert result.status is AdapterConversionStatus.PARTIAL
    missing = set(result.result_payload["missing_coverage"])
    for key in ("amount", "sequence_or_ticket", "validated_ledger"):
        assert key in missing
    paths = {field.path for field in result.unsupported_fields}
    assert "amount" in paths
    assert "sequence" in paths
    assert result.result_payload["transfer"] is None
    assert result.result_payload["hooks"]["status"] == "UNSUPPORTED"
    assert result.result_payload["evm_sidechain"]["status"] == "UNSUPPORTED"


def test_rejects_float_amounts() -> None:
    with pytest.raises(XRPLAdapterError):
        XRPLTransactionObservation(
            observation_id="bad",
            chain_id="0",
            account=ADDR_A,
            amount=1.5,  # type: ignore[arg-type]
        )
    with pytest.raises(XRPLAdapterError, match="binary floats"):
        parse_amount(1.5)


# ---------------------------------------------------------------------------
# Hooks / EVM never inferred without capability evidence
# ---------------------------------------------------------------------------


def test_hooks_unsupported_without_capability() -> None:
    result = convert_xrpl_payload(_full_observation())
    assert result.result_payload["hooks"]["status"] == "UNSUPPORTED"
    assert result.result_payload["hooks"]["capability_present"] is False
    assert result.result_payload["evm_sidechain"]["status"] == "UNSUPPORTED"
    assert any("Hooks" in d or "hooks" in d.lower() for d in result.diagnostics)


def test_hooks_effects_without_capability_are_unsupported() -> None:
    result = convert_xrpl_payload(
        _full_observation(
            hooks_capability_present=False,
            hooks_effects=[{"HookHash": "AA" * 32, "HookResult": 0}],
        )
    )
    assert result.status is AdapterConversionStatus.PARTIAL
    paths = {f.path for f in result.unsupported_fields}
    assert "hooks_effects" in paths
    # Effects must not be accepted as supported semantics
    assert result.result_payload["hooks"]["status"] == "UNSUPPORTED"


def test_hooks_with_capability_evidence_recorded() -> None:
    effects = [{"HookHash": "BB" * 32, "HookResult": 0}]
    result = convert_xrpl_payload(
        _full_observation(
            hooks_capability_present=True,
            hooks_effects=effects,
        )
    )
    assert result.result_payload["hooks"]["status"] == "supported"
    assert result.result_payload["hooks"]["capability_present"] is True
    assert len(result.result_payload["hooks"]["effects"]) == 1


def test_set_hook_without_capability_is_partial() -> None:
    result = convert_xrpl_payload(
        _full_observation(
            transaction_type="SetHook",
            hooks_capability_present=False,
            amount=None,
            destination="",
            destination_tag=None,
            delivered_amount=None,
        )
    )
    # amount missing + hooks capability missing
    assert result.status is AdapterConversionStatus.PARTIAL
    assert any(
        f.path == "hooks_capability_present" for f in result.unsupported_fields
    )


def test_not_modeled_as_evm_calls() -> None:
    result = convert_xrpl_payload(_payment_intent())
    unsigned = result.result_payload["unsigned_transaction_intent"]
    assert unsigned["calls"] == [] or unsigned["calls"] == ()
    assert unsigned["attributes"]["not_evm_shaped"] is True
    assert unsigned["attributes"]["native_model"] == "ledger_state_transitions"
    assert "calldata" not in result.result_payload
    assert result.result_payload["hooks"]["status"] == "UNSUPPORTED"


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------


def test_testnet_distinct_from_mainnet() -> None:
    main = convert_xrpl_payload(_full_observation())
    test = convert_xrpl_payload(
        _full_observation(
            observation_id="obs-test",
            chain_id=XRPL_TESTNET_CHAIN_ID,
            network="xrpl-testnet",
            genesis_hash=XRPL_TESTNET_GENESIS_HASH,
        )
    )
    assert main.result_payload["chain"]["chain_id"] != test.result_payload["chain"]["chain_id"]
    assert (
        main.result_payload["chain"]["genesis_digest"]
        != test.result_payload["chain"]["genesis_digest"]
    )


def test_mismatched_genesis_fails() -> None:
    with pytest.raises(XRPLAdapterError, match="genesis_hash does not match"):
        resolve_network(
            chain_id=XRPL_MAINNET_CHAIN_ID,
            genesis_hash="FF" * 32,
        )


def test_unknown_chain_requires_genesis() -> None:
    with pytest.raises(XRPLAdapterError, match="explicit genesis_hash"):
        resolve_network(chain_id="99")


# ---------------------------------------------------------------------------
# Payment intent / Xaman
# ---------------------------------------------------------------------------


def test_payment_intent_conversion() -> None:
    result = convert_xrpl_payload(_payment_intent())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_authority is AuthorityKind.DECLARATION
    payload = result.result_payload
    assert payload["record_type"] == "xrpl_payment_intent"
    dest = payload["accounts"]["destination"]
    assert dest["destination_tag"] == 99
    assert dest["classic_address"] == ADDR_B

    unsigned = UnsignedTransactionIntent.from_dict(
        payload["unsigned_transaction_intent"]
    )
    assert unsigned.intent_id == "intent-1"
    assert len(unsigned.transfers) == 1
    assert unsigned.transfers[0].amount.base_units == "500000"
    assert unsigned.transfers[0].amount.decimals == NATIVE_DECIMALS
    assert len(unsigned.calls) == 0


def test_payment_intent_structured_round_trip() -> None:
    intent = XRPLPaymentIntent.from_dict(_payment_intent(amount="42"))
    assert intent.amount == "42"
    restored = XRPLPaymentIntent.from_dict(intent.to_dict())
    assert restored.intent_id == intent.intent_id
    assert restored.amount == intent.amount
    result = convert_xrpl_payload(intent)
    assert result.status is AdapterConversionStatus.SUCCEEDED


def test_xaman_payload_shares_xrpl_conversion() -> None:
    result = convert_xrpl_payload(
        {
            **_full_observation(),
            "kind": "xaman_payload",
            "wallet_source": "xaman",
            "xaman_payload_id": "payload-uuid-001",
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["record_type"] == "xaman_payload_observation"
    assert result.result_payload["wallet_source"] == "xaman"
    assert result.result_payload["xaman_payload_id"] == "payload-uuid-001"
    assert result.result_payload["ledger_transition"]["transaction_type"] == "Payment"


# ---------------------------------------------------------------------------
# LedgerTransition AST surface
# ---------------------------------------------------------------------------


def test_ledger_transition_direct_conversion() -> None:
    transition = LedgerTransition(
        transition_id="lt-1",
        transaction_type=XRPLTransitionKind.TRUST_SET,
        account=XRPLAccountIdentity.parse(ADDR_A),
        trust_line={
            "currency": "USD",
            "issuer": ADDR_ISSUER,
            "limit": "1000",
        },
        sequence=10,
        flags=0,
        transaction_hash=TX_HASH,
        validated=True,
    )
    result = convert_xrpl_payload(
        {
            **transition.to_dict(),
            "kind": "ledger_transition",
            "chain_id": XRPL_MAINNET_CHAIN_ID,
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["record_type"] == "xrpl_ledger_transition"
    assert result.result_payload["ledger_transition"]["transaction_type"] == "TrustSet"
    assert result.result_payload["hooks"]["status"] == "UNSUPPORTED"


def test_trust_line_on_observation() -> None:
    result = convert_xrpl_payload(
        _full_observation(
            transaction_type="TrustSet",
            amount={"currency": "USD", "issuer": ADDR_ISSUER, "value": "0"},
            destination="",
            destination_tag=None,
            trust_line={
                "currency": "USD",
                "issuer": ADDR_ISSUER,
                "limit": "5000",
            },
        )
    )
    lt = result.result_payload["ledger_transition"]
    assert lt["transaction_type"] == "TrustSet"
    assert lt["trust_line"]["limit"] == "5000"


# ---------------------------------------------------------------------------
# Serialized candidate
# ---------------------------------------------------------------------------


def test_serialized_candidate_from_tx_blob() -> None:
    blob = "120000228000000024000000016140000000000F424068400000000000000C"
    result = convert_xrpl_payload(
        {
            "kind": "serialized_candidate",
            "candidate_id": "cand-1",
            "intent_id": "intent-1",
            "chain_id": XRPL_MAINNET_CHAIN_ID,
            "tx_blob": blob,
            "encoding": "xrpl-binary",
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    cand = result.result_payload["serialized_transaction_candidate"]
    assert cand["candidate_id"] == "cand-1"
    assert cand["payload_digest"].startswith("sha256:")
    assert cand["byte_length"] > 0
    assert result.result_payload["tx_blob_absent"] is False


# ---------------------------------------------------------------------------
# Authority: no elevation
# ---------------------------------------------------------------------------


def test_observation_does_not_promote_to_proof() -> None:
    result = convert_xrpl_payload(_full_observation())
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION
    assert result.result_payload["authority"] == AuthorityKind.OBSERVATION.value

    from ipfs_datasets_py.logic.crypto_ir import observation_provenance

    prov = observation_provenance(
        producer_id="test-fixture",
        observed_at="2026-07-29T00:00:00Z",
        finality=FinalityStatus.FINALIZED,
    )
    again = convert_xrpl_payload(_full_observation(), source_provenance=prov)
    assert again.result_authority is AuthorityKind.OBSERVATION
    assert again.result_authority is not AuthorityKind.AUTHORIZATION
    assert again.result_authority is not AuthorityKind.RESULT


def test_authorization_source_is_rejected() -> None:
    result = convert_xrpl_payload(
        _full_observation(),
        source_provenance={"authority": {"kind": "authorization"}},
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("authorization" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Structured observation round-trip
# ---------------------------------------------------------------------------


def test_structured_observation_round_trip() -> None:
    obs = XRPLTransactionObservation.from_dict(_full_observation())
    restored = XRPLTransactionObservation.from_dict(obs.to_dict())
    assert restored.observation_id == obs.observation_id
    assert restored.account == obs.account
    assert restored.destination_tag == 42
    assert restored.amount == "1000000"
    result = convert_xrpl_payload(obs)
    assert result.status is AdapterConversionStatus.SUCCEEDED


def test_drops_constant() -> None:
    assert DROPS_PER_XRP == 1_000_000
    assert NATIVE_DECIMALS == 6

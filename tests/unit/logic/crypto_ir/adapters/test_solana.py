"""Unit tests for the Solana wallet-to-Crypto-IR adapter (CRYPTOIR-G110 / CRYPTOIR-008).

Fixture-driven, offline conversion and rejection tests.  No network I/O.
Covers:

* Base58 identity validation and cluster/genesis non-collision;
* signer/writable/account-order privilege semantics;
* exact lamports and SPL token base units;
* slot commitment levels remaining distinct;
* incomplete inner-instruction coverage staying explicit;
* unsupported versioned messages failing closed;
* legacy and supported v0 messages plus malformed/partial cases.
"""

from __future__ import annotations

import json
import socket
import sys
from copy import deepcopy
from pathlib import Path
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
from ipfs_datasets_py.logic.crypto_ir.adapters.solana import (
    SOLANA_ADAPTER_ID,
    SOLANA_CAPABILITY_ID,
    SOLANA_DEVNET_CHAIN_ID,
    SOLANA_DEVNET_GENESIS_HASH,
    SOLANA_MAINNET_CHAIN_ID,
    SOLANA_MAINNET_GENESIS_HASH,
    SOLANA_MAINNET_NETWORK,
    SOLANA_NAMESPACE,
    SYSTEM_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    AccountPrivilege,
    SolanaAdapterError,
    SolanaInstruction,
    SolanaMessageCandidate,
    SolanaTransactionObservation,
    SolanaWalletAdapter,
    convert_solana_payload,
    decode_base58,
    map_commitment,
    normalize_message_version,
    normalize_pubkey,
    normalize_signature,
    privileges_from_header,
    resolve_account_privileges,
    resolve_network,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "wallets"
    / "solana"
    / "rpc_session.json"
)


@pytest.fixture(scope="module")
def rpc_session() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _addrs(rpc: dict[str, Any]) -> dict[str, str]:
    return rpc["addresses"]


def _versioned_observation(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    sig = rpc["signatures"]["versioned"]
    native = deepcopy(rpc["transactions"][sig])
    slot = str(native["slot"])
    blockhash = rpc["blocks"][slot]["blockhash"]
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-versioned-1",
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
        "network": SOLANA_MAINNET_NETWORK,
        "genesis_hash": SOLANA_MAINNET_GENESIS_HASH,
        "signature": sig,
        "slot": native["slot"],
        "blockhash": blockhash,
        "block_time": native["blockTime"],
        "transaction_index": 0,
        "commitment": "finalized",
        "retraction": "not_retracted",
        "observed_at": "2026-07-29T12:00:00Z",
        "version": native["version"],
        "transaction": {
            "transaction": native["transaction"],
            "meta": native["meta"],
            "version": native["version"],
        },
        "raw": {"provider": "fixture", "cursor": 1},
    }
    payload.update(overrides)
    return payload


def _legacy_failed_observation(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    sig = rpc["signatures"]["failed_legacy"]
    native = deepcopy(rpc["transactions"][sig])
    slot = str(native["slot"])
    blockhash = rpc["blocks"][slot]["blockhash"]
    # failed_legacy accountKeys are plain strings; supply header for privileges.
    message = native["transaction"]["message"]
    if "header" not in message and message.get("accountKeys") and isinstance(
        message["accountKeys"][0], str
    ):
        # fee payer signer writable, destination writable, system program readonly
        message["header"] = {
            "numRequiredSignatures": 1,
            "numReadonlySignedAccounts": 0,
            "numReadonlyUnsignedAccounts": 1,
        }
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-failed-legacy-1",
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
        "network": SOLANA_MAINNET_NETWORK,
        "genesis_hash": SOLANA_MAINNET_GENESIS_HASH,
        "signature": sig,
        "slot": native["slot"],
        "blockhash": blockhash,
        "block_time": native["blockTime"],
        "commitment": "finalized",
        "retraction": "not_retracted",
        "observed_at": "2026-07-29T12:00:00Z",
        "version": native["version"],
        "transaction": {
            "transaction": native["transaction"],
            "meta": native["meta"],
            "version": native["version"],
        },
        "raw": {"provider": "fixture"},
    }
    payload.update(overrides)
    return payload


def _minimal_observation(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    sig = rpc["signatures"]["failed_legacy"]
    payload: dict[str, Any] = {
        "kind": "transaction_observation",
        "observation_id": "obs-min-1",
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
        "signature": sig,
    }
    payload.update(overrides)
    return payload


def _message_candidate(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    addrs = _addrs(rpc)
    payload: dict[str, Any] = {
        "kind": "message_candidate",
        "intent_id": "intent-legacy-1",
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
        "network": SOLANA_MAINNET_NETWORK,
        "genesis_hash": SOLANA_MAINNET_GENESIS_HASH,
        "version": "legacy",
        "recent_blockhash": rpc["blocks"]["99"]["blockhash"],
        "fee_payer": addrs["alice"],
        "message": {
            "header": {
                "numRequiredSignatures": 1,
                "numReadonlySignedAccounts": 0,
                "numReadonlyUnsignedAccounts": 1,
            },
            "accountKeys": [
                addrs["alice"],
                addrs["bob"],
                SYSTEM_PROGRAM_ID,
            ],
            "recentBlockhash": rpc["blocks"]["99"]["blockhash"],
            "instructions": [
                {
                    "programId": SYSTEM_PROGRAM_ID,
                    "accounts": [0, 1],
                    "data": "3Bxs4NN",
                    "parsed": {
                        "type": "transfer",
                        "info": {
                            "source": addrs["alice"],
                            "destination": addrs["bob"],
                            "lamports": 1000,
                        },
                    },
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Import / side-effect free / AST symbols
# ---------------------------------------------------------------------------


def test_import_solana_adapter_has_no_network_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network socket use forbidden during Solana adapter import")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if name.endswith(".crypto_ir.adapters.solana") or name.endswith(
            "crypto_ir.adapters.solana"
        ):
            del sys.modules[name]

    from ipfs_datasets_py.logic.crypto_ir.adapters import solana as solana_mod

    assert solana_mod.SolanaWalletAdapter is not None
    assert solana_mod.SolanaInstruction is not None
    assert solana_mod.AccountPrivilege is not None


def test_ast_symbols_exported() -> None:
    """AST query symbols required by CRYPTOIR-G110 must exist."""

    from ipfs_datasets_py.logic.crypto_ir.adapters import solana as mod

    assert hasattr(mod, "SolanaWalletAdapter")
    assert hasattr(mod, "SolanaInstruction")
    assert hasattr(mod, "AccountPrivilege")
    assert callable(mod.SolanaWalletAdapter)
    assert callable(mod.SolanaInstruction)
    assert callable(mod.AccountPrivilege)


def test_adapter_registers_in_registry() -> None:
    adapter = SolanaWalletAdapter()
    registry = AdapterRegistry.from_adapters([adapter])
    entry = registry.require(
        SOLANA_ADAPTER_ID,
        required_surfaces=[],
    )
    assert entry.capability.capability_id == SOLANA_CAPABILITY_ID
    assert entry.capability.supports_chain_namespace(SOLANA_NAMESPACE)
    assert "account_privileges" in entry.capability.features
    assert "versioned_messages" in entry.capability.features


# ---------------------------------------------------------------------------
# Base58 identity / clusters
# ---------------------------------------------------------------------------


def test_normalize_pubkey_and_signature(rpc_session: dict[str, Any]) -> None:
    alice = rpc_session["addresses"]["alice"]
    assert normalize_pubkey(alice) == alice
    assert len(decode_base58(alice, field="alice")) == 32
    sig = rpc_session["signatures"]["versioned"]
    assert normalize_signature(sig) == sig
    assert len(decode_base58(sig, field="sig")) == 64


def test_normalize_pubkey_rejects_malformed() -> None:
    with pytest.raises(SolanaAdapterError):
        normalize_pubkey("not-base58!!!")
    with pytest.raises(SolanaAdapterError):
        normalize_pubkey("1111")  # too short


def test_clusters_do_not_collide() -> None:
    main = resolve_network(chain_id=SOLANA_MAINNET_CHAIN_ID)
    dev = resolve_network(chain_id=SOLANA_DEVNET_CHAIN_ID)
    main_id = main.to_chain_identity()
    dev_id = dev.to_chain_identity()
    assert main_id.chain_id != dev_id.chain_id
    assert main_id.network != dev_id.network
    assert main_id.genesis_digest != dev_id.genesis_digest
    assert main.genesis_hash == SOLANA_MAINNET_GENESIS_HASH
    assert dev.genesis_hash == SOLANA_DEVNET_GENESIS_HASH


def test_mismatched_genesis_for_known_cluster_fails() -> None:
    with pytest.raises(SolanaAdapterError, match="genesis_hash does not match"):
        resolve_network(
            chain_id=SOLANA_MAINNET_CHAIN_ID,
            genesis_hash=SOLANA_DEVNET_GENESIS_HASH,
        )


def test_unknown_cluster_requires_genesis() -> None:
    with pytest.raises(SolanaAdapterError, match="explicit genesis_hash"):
        resolve_network(chain_id="localnet")


def test_unknown_cluster_with_genesis_accepted() -> None:
    anchor = resolve_network(
        chain_id="localnet",
        network="solana-localnet",
        genesis_hash="LocalGenesisHashAnchor0000000000000001",
    )
    assert anchor.chain_id == "localnet"
    identity = anchor.to_chain_identity()
    assert identity.network == "solana-localnet"
    assert identity.genesis_digest.startswith("sha256:")


# ---------------------------------------------------------------------------
# Account order and privilege bits (semantic)
# ---------------------------------------------------------------------------


def test_privileges_from_header_order_and_bits(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    keys = [addrs["alice"], addrs["bob"], SYSTEM_PROGRAM_ID]
    header = {
        "numRequiredSignatures": 1,
        "numReadonlySignedAccounts": 0,
        "numReadonlyUnsignedAccounts": 1,
    }
    privileges = privileges_from_header(keys, header)
    assert [p.account_index for p in privileges] == [0, 1, 2]
    assert privileges[0].is_signer is True and privileges[0].is_writable is True
    assert privileges[1].is_signer is False and privileges[1].is_writable is True
    assert privileges[2].is_signer is False and privileges[2].is_writable is False
    # Order is semantic: reordering changes privilege identity at each index.
    reordered = privileges_from_header(
        [addrs["bob"], addrs["alice"], SYSTEM_PROGRAM_ID], header
    )
    assert reordered[0].pubkey == addrs["bob"]
    assert reordered[0].is_signer is True
    assert privileges[0].pubkey != reordered[0].pubkey


def test_json_parsed_privileges_and_loaded_addresses(
    rpc_session: dict[str, Any],
) -> None:
    sig = rpc_session["signatures"]["versioned"]
    native = rpc_session["transactions"][sig]
    message = native["transaction"]["message"]
    meta = native["meta"]
    privileges, tables = resolve_account_privileges(message, meta)
    addrs = _addrs(rpc_session)
    # static (5) + loaded writable (2)
    assert len(privileges) == 7
    assert privileges[0].pubkey == addrs["alice"]
    assert privileges[0].is_signer is True
    assert privileges[0].is_writable is True
    assert privileges[5].source == "lookup_writable"
    assert privileges[5].pubkey == addrs["source_token_account"]
    assert privileges[5].is_writable is True
    assert privileges[5].is_signer is False
    assert privileges[6].pubkey == addrs["destination_token_account"]
    assert len(tables) == 1
    assert tables[0].account_key == addrs["lookup_table"]


def test_account_privilege_dataclass_round_trip(rpc_session: dict[str, Any]) -> None:
    priv = AccountPrivilege(
        account_index=0,
        pubkey=rpc_session["addresses"]["alice"],
        is_signer=True,
        is_writable=True,
    )
    restored = AccountPrivilege.from_dict(priv.to_dict())
    assert restored == priv


def test_solana_instruction_preserves_order(rpc_session: dict[str, Any]) -> None:
    instr = SolanaInstruction(
        program_id=SYSTEM_PROGRAM_ID,
        account_indexes=(0, 1),
        accounts=(
            rpc_session["addresses"]["alice"],
            rpc_session["addresses"]["bob"],
        ),
        outer_index=0,
        inner_index=None,
        parsed_type="transfer",
        parsed_info={"lamports": "42"},
    )
    restored = SolanaInstruction.from_dict(instr.to_dict())
    assert restored.account_indexes == (0, 1)
    assert restored.accounts[0] == rpc_session["addresses"]["alice"]
    assert restored.is_inner is False


# ---------------------------------------------------------------------------
# Full versioned observation conversion
# ---------------------------------------------------------------------------


def test_versioned_observation_preserves_instructions_privileges_transfers(
    rpc_session: dict[str, Any],
) -> None:
    result = convert_solana_payload(_versioned_observation(rpc_session))
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.adapter_id == SOLANA_ADAPTER_ID
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION

    chain = result.result_payload["chain"]
    assert chain["chain_namespace"] == SOLANA_NAMESPACE
    assert chain["chain_id"] == SOLANA_MAINNET_CHAIN_ID
    assert chain["network"] == SOLANA_MAINNET_NETWORK
    assert chain["genesis_digest"].startswith("sha256:")
    assert chain["attributes"]["genesis_hash"] == SOLANA_MAINNET_GENESIS_HASH

    privileges = result.result_payload["account_privileges"]
    assert privileges[0]["is_signer"] is True
    assert privileges[0]["is_writable"] is True
    # Account order preserved: index equals position.
    assert [p["account_index"] for p in privileges] == list(range(len(privileges)))

    instructions = result.result_payload["instructions"]
    # outer0, inner0 (outer0), outer1
    coords = [(i["outer_index"], i["inner_index"]) for i in instructions]
    assert coords == [(0, None), (0, 0), (1, None)]

    transfers = result.result_payload["transfers"]
    kinds_amounts = [
        (t["kind"], t["amount"]["base_units"], t["amount"]["decimals"])
        for t in transfers
    ]
    assert ( "native", "18446744073709551615", 9) in kinds_amounts
    assert ("native", "42", 9) in kinds_amounts
    assert ("token", "900719925474099312345", 6) in kinds_amounts

    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.FINALIZED.value
    assert observed["tx_digest"].startswith("sha256:")
    assert observed["coordinate"]["sequence"] == 100
    assert observed["attributes"]["version"] == "0"
    assert observed["attributes"]["inner_instructions_present"] is True
    assert result.result_payload["failed"] is False
    assert result.result_payload["fee"]["amount"]["base_units"] == "5000"

    restored = ObservedTransaction.from_dict(observed)
    assert restored.finality is FinalityStatus.FINALIZED
    assert restored.provenance is not None
    assert restored.provenance.authority.kind is AuthorityKind.OBSERVATION


def test_failed_legacy_visible_without_invented_transfers(
    rpc_session: dict[str, Any],
) -> None:
    result = convert_solana_payload(_legacy_failed_observation(rpc_session))
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["failed"] is True
    assert result.result_payload["version"] == "legacy"
    assert list(result.result_payload["transfers"]) == []
    # Instructions still present for analysis even when failed.
    assert len(result.result_payload["instructions"]) >= 1
    privileges = result.result_payload["account_privileges"]
    assert privileges[0]["is_signer"] is True
    assert privileges[0]["pubkey"] == rpc_session["addresses"]["alice"]


def test_missing_meta_message_commitment_not_invented(
    rpc_session: dict[str, Any],
) -> None:
    result = convert_solana_payload(_minimal_observation(rpc_session))
    assert result.status is AdapterConversionStatus.PARTIAL
    missing = set(result.result_payload["missing_coverage"])
    for key in ("meta", "message", "commitment", "slot"):
        assert key in missing
    paths = {field.path for field in result.unsupported_fields}
    assert "meta" in paths
    assert "message" in paths
    assert "commitment" in paths
    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == FinalityStatus.UNKNOWN.value
    assert result.result_payload["meta"] is None
    assert result.result_payload["message"] is None


def test_incomplete_inner_instruction_coverage_explicit(
    rpc_session: dict[str, Any],
) -> None:
    payload = _legacy_failed_observation(rpc_session)
    # Strip innerInstructions from meta while leaving meta present.
    meta = payload["transaction"]["meta"]
    meta.pop("innerInstructions", None)
    meta.pop("inner_instructions", None)
    result = convert_solana_payload(payload)
    # May still succeed if no other gaps, but coverage must note absence.
    missing = set(result.result_payload.get("missing_coverage", ()))
    assert "inner_instructions" in missing
    paths = {field.path for field in result.unsupported_fields}
    assert "meta.innerInstructions" in paths
    observed = result.result_payload["observed_transaction"]
    assert observed["attributes"]["inner_instructions_present"] is False


# ---------------------------------------------------------------------------
# Commitment levels remain distinct
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("commitment", "expected"),
    [
        ("processed", FinalityStatus.PROPOSED),
        ("confirmed", FinalityStatus.CONFIRMED),
        ("finalized", FinalityStatus.FINALIZED),
    ],
)
def test_commitment_levels_remain_distinct(
    rpc_session: dict[str, Any],
    commitment: str,
    expected: FinalityStatus,
) -> None:
    assert map_commitment(commitment) is expected
    result = convert_solana_payload(
        _legacy_failed_observation(rpc_session, commitment=commitment)
    )
    assert result.result_payload["commitment"] == expected.value
    assert result.result_payload["commitment_raw"] == commitment
    observed = result.result_payload["observed_transaction"]
    assert observed["finality"] == expected.value


# ---------------------------------------------------------------------------
# Exact amounts — no floats
# ---------------------------------------------------------------------------


def test_rejects_float_lamports(rpc_session: dict[str, Any]) -> None:
    # Re-import after the side-effect import test may have reloaded the module.
    from ipfs_datasets_py.logic.crypto_ir.adapters.solana import (
        SolanaAdapterError as Err,
        parse_exact_base_units,
    )

    with pytest.raises(Err, match="rejects binary floats"):
        parse_exact_base_units(1.5, field="lamports")
    with pytest.raises(Err, match="non-negative decimal integer"):
        parse_exact_base_units("1e9", field="lamports")


def test_large_lamports_preserved_exactly(rpc_session: dict[str, Any]) -> None:
    result = convert_solana_payload(_versioned_observation(rpc_session))
    native = [
        t
        for t in result.result_payload["transfers"]
        if t["kind"] == "native" and t["amount"]["base_units"] == "18446744073709551615"
    ]
    assert len(native) == 1
    assert native[0]["amount"]["decimals"] == 9


def test_zero_fee_is_preserved_not_dropped(rpc_session: dict[str, Any]) -> None:
    payload = _legacy_failed_observation(rpc_session)
    payload["transaction"]["meta"]["fee"] = 0
    result = convert_solana_payload(payload)
    assert result.result_payload["fee"] is not None
    assert result.result_payload["fee"]["amount"]["base_units"] == "0"


# ---------------------------------------------------------------------------
# Unsupported versioned messages fail closed
# ---------------------------------------------------------------------------


def test_unsupported_message_version_fails_closed(rpc_session: dict[str, Any]) -> None:
    with pytest.raises(SolanaAdapterError, match="unsupported versioned message"):
        normalize_message_version(1)
    with pytest.raises(SolanaAdapterError, match="unsupported versioned message"):
        normalize_message_version("v1")
    result = convert_solana_payload(
        _versioned_observation(rpc_session, version=1)
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("unsupported" in d.lower() for d in result.diagnostics)


def test_partial_lookup_resolution_fails_closed(rpc_session: dict[str, Any]) -> None:
    payload = _versioned_observation(rpc_session)
    # Drop one loaded writable address → index/address mismatch.
    meta = payload["transaction"]["meta"]
    meta["loadedAddresses"]["writable"] = meta["loadedAddresses"]["writable"][:1]
    result = convert_solana_payload(payload)
    assert result.status is AdapterConversionStatus.ERROR
    assert any(
        "unresolved" in d.lower() or "not fully described" in d.lower()
        for d in result.diagnostics
    )


def test_versioned_message_candidate_without_loaded_addresses_fails(
    rpc_session: dict[str, Any],
) -> None:
    sig = rpc_session["signatures"]["versioned"]
    native = rpc_session["transactions"][sig]
    message = deepcopy(native["transaction"]["message"])
    result = convert_solana_payload(
        {
            "kind": "message_candidate",
            "intent_id": "intent-v0-partial",
            "chain_id": SOLANA_MAINNET_CHAIN_ID,
            "version": 0,
            "fee_payer": rpc_session["addresses"]["alice"],
            "recent_blockhash": message["recentBlockhash"],
            "message": message,
            # no loadedAddresses
        }
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("loadedAddresses" in d or "lookup" in d.lower() for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Message candidate conversion
# ---------------------------------------------------------------------------


def test_message_candidate_preserves_privileges_and_intent(
    rpc_session: dict[str, Any],
) -> None:
    result = convert_solana_payload(_message_candidate(rpc_session))
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_authority is AuthorityKind.DECLARATION
    assert result.result_payload["record_type"] == "solana_message_candidate"
    privileges = result.result_payload["account_privileges"]
    assert privileges[0]["is_signer"] is True
    assert privileges[0]["pubkey"] == rpc_session["addresses"]["alice"]
    unsigned = UnsignedTransactionIntent.from_dict(
        result.result_payload["unsigned_transaction_intent"]
    )
    assert unsigned.intent_id == "intent-legacy-1"
    assert unsigned.chain.chain_id == SOLANA_MAINNET_CHAIN_ID
    assert len(unsigned.signers) >= 1
    assert len(unsigned.calls) == 1
    assert unsigned.calls[0].method == "transfer"
    assert len(unsigned.transfers) == 1
    assert unsigned.transfers[0].amount.base_units == "1000"


def test_message_candidate_structured_round_trip(rpc_session: dict[str, Any]) -> None:
    candidate = SolanaMessageCandidate.from_dict(_message_candidate(rpc_session))
    restored = SolanaMessageCandidate.from_dict(candidate.to_dict())
    assert restored.intent_id == candidate.intent_id
    assert restored.version == "legacy"
    result = convert_solana_payload(candidate)
    assert result.status is AdapterConversionStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Serialized candidate
# ---------------------------------------------------------------------------


def test_serialized_candidate_from_base64() -> None:
    import base64

    body = b"\x01\x02\x03\x04solana-wire"
    raw = base64.b64encode(body).decode("ascii")
    result = convert_solana_payload(
        {
            "kind": "serialized_candidate",
            "candidate_id": "cand-1",
            "intent_id": "intent-1",
            "chain_id": SOLANA_MAINNET_CHAIN_ID,
            "raw_tx": raw,
            "encoding": "base64",
            "version": "legacy",
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    cand = result.result_payload["serialized_transaction_candidate"]
    assert cand["candidate_id"] == "cand-1"
    assert cand["payload_digest"].startswith("sha256:")
    assert cand["byte_length"] == len(body)
    assert result.result_payload["raw_tx_absent"] is False


# ---------------------------------------------------------------------------
# Authority: no elevation to proof
# ---------------------------------------------------------------------------


def test_observation_round_trip_does_not_promote_to_proof(
    rpc_session: dict[str, Any],
) -> None:
    result = convert_solana_payload(_versioned_observation(rpc_session))
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION
    assert result.result_payload["authority"] == AuthorityKind.OBSERVATION.value

    from ipfs_datasets_py.logic.crypto_ir import observation_provenance

    prov = observation_provenance(
        producer_id="test-fixture",
        observed_at="2026-07-29T00:00:00Z",
        finality=FinalityStatus.FINALIZED,
    )
    again = convert_solana_payload(
        _versioned_observation(rpc_session), source_provenance=prov
    )
    assert again.result_authority is AuthorityKind.OBSERVATION
    assert again.result_authority is not AuthorityKind.AUTHORIZATION
    assert again.result_authority is not AuthorityKind.RESULT


def test_authorization_source_is_rejected(rpc_session: dict[str, Any]) -> None:
    result = convert_solana_payload(
        _versioned_observation(rpc_session),
        source_provenance={"authority": {"kind": "authorization"}},
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("authorization" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Structured observation record / registry
# ---------------------------------------------------------------------------


def test_transaction_observation_dataclass_round_trip(
    rpc_session: dict[str, Any],
) -> None:
    obs = SolanaTransactionObservation.from_dict(
        _versioned_observation(rpc_session)
    )
    restored = SolanaTransactionObservation.from_dict(obs.to_dict())
    assert restored.observation_id == obs.observation_id
    assert restored.signature == rpc_session["signatures"]["versioned"]
    assert restored.message is not None
    assert restored.meta is not None
    result = convert_solana_payload(obs)
    assert result.status is AdapterConversionStatus.SUCCEEDED


def test_adapter_convert_via_registry(rpc_session: dict[str, Any]) -> None:
    registry = AdapterRegistry.from_adapters([SolanaWalletAdapter()])
    result = registry.convert(SOLANA_ADAPTER_ID, _versioned_observation(rpc_session))
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["chain"]["chain_id"] == SOLANA_MAINNET_CHAIN_ID


def test_devnet_observation_is_distinct_cluster(rpc_session: dict[str, Any]) -> None:
    main = convert_solana_payload(_versioned_observation(rpc_session))
    dev_payload = _versioned_observation(
        rpc_session,
        observation_id="obs-devnet",
        chain_id=SOLANA_DEVNET_CHAIN_ID,
        network="solana-devnet",
        genesis_hash=SOLANA_DEVNET_GENESIS_HASH,
    )
    dev = convert_solana_payload(dev_payload)
    assert main.result_payload["chain"]["genesis_digest"] != dev.result_payload["chain"][
        "genesis_digest"
    ]
    assert dev.result_payload["chain"]["chain_id"] == SOLANA_DEVNET_CHAIN_ID


def test_program_logs_preserved_when_present(rpc_session: dict[str, Any]) -> None:
    result = convert_solana_payload(_versioned_observation(rpc_session))
    logs = result.result_payload["log_messages"]
    assert logs is not None
    assert len(logs) == 5
    assert any("Program" in line for line in logs)

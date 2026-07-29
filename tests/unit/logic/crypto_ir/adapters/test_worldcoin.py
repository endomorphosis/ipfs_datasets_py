"""Unit tests for Worldcoin / World ID / World Chain composition adapter.

CRYPTOIR-G140 / CRYPTOIR-015 — offline fixture coverage for:

* World ID, World Chain, WLD, verifier, bridge, nullifier, action, RP/app, and
  proof observations remaining distinct;
* mandatory chain/domain binding;
* proof observations conferring neither identity nor transaction authorization;
* EVM transaction semantics reuse for World Chain without collapsing authorities;
* cross-domain confusion fixtures over composition records.
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
)
from ipfs_datasets_py.logic.crypto_ir.adapters.evm import (
    ETHEREUM_MAINNET_CHAIN_ID,
    ETHEREUM_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
)
from ipfs_datasets_py.logic.crypto_ir.adapters.worldcoin import (
    WLD_WORLD_CHAIN_MAINNET_ADDRESS,
    WORLDCOIN_ADAPTER_ID,
    WORLDCOIN_CAPABILITY_ID,
    WORLD_ID_PROOF_TYPE,
    NullifierBinding,
    WorldChainIdentity,
    WorldIDObservation,
    WorldcoinAdapter,
    WorldcoinAdapterError,
    WorldcoinPayloadKind,
    convert_worldcoin_payload,
    is_world_chain_id,
    world_chain_settlement_layer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


ADDR_FROM = "0x52908400098527886e0f7030069857d2e4169ee7"
ADDR_TO = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
TX_HASH = "0x" + ("ab" * 32)
BLOCK_HASH = "0x" + ("cd" * 32)
NULLIFIER_COMMITMENT = "sha256:" + ("11" * 32)
VERIFIER_ADDRESS = "0x" + ("42" * 20)


def _world_id_observation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "world_id_observation",
        "observation_id": "wid-obs-1",
        "rp_id": "app_staging_rp_example",
        "app_id": "app_staging_example",
        "action": "login",
        "environment": "staging",
        "protocol_version": "4.0",
        "nullifier_commitment": NULLIFIER_COMMITMENT,
        "binding_id": "binding-1",
        "verifier_id": "world_id_developer_portal_v4",
        "proof_system": "world_id_idkit_v4",
        "credential_policy": "proof_of_human",
        "verification_status": "verified",
        "observed_at": "2026-07-29T12:00:00Z",
        "raw": {"provider": "fixture", "cursor": 1},
    }
    payload.update(overrides)
    return payload


def _nullifier_binding(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "nullifier_binding",
        "binding_id": "nb-1",
        "nullifier_commitment": NULLIFIER_COMMITMENT,
        "rp_id": "app_staging_rp_example",
        "app_id": "app_staging_example",
        "action": "login",
        "environment": "staging",
        "protocol_version": "4.0",
        "verification_status": "verified",
    }
    payload.update(overrides)
    return payload


def _world_chain_tx(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "world_chain_transaction",
        "observation_id": "wc-tx-1",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "network": "world-chain-mainnet",
        "genesis_hash": WORLD_CHAIN_MAINNET_GENESIS_HASH,
        "tx_hash": TX_HASH,
        "from_address": ADDR_FROM,
        "to_address": ADDR_TO,
        "value_wei": "1000000000000000000",
        "input_data": "0x",
        "block_number": 1_000_000,
        "block_hash": BLOCK_HASH,
        "transaction_index": 3,
        "finality": "finalized",
        "retraction": "not_retracted",
        "observed_at": "2026-07-29T12:00:00Z",
        "receipt": {"status": "0x1", "gasUsed": "0x5208", "logs": []},
        "logs": [],
        "traces": [],
    }
    payload.update(overrides)
    return payload


def _wld_asset(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "wld_asset",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "network": "world-chain-mainnet",
        "genesis_hash": WORLD_CHAIN_MAINNET_GENESIS_HASH,
    }
    payload.update(overrides)
    return payload


def _verifier(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "verifier_instance",
        "verifier_id": "wc-verifier-1",
        "verifier_address": VERIFIER_ADDRESS,
        "protocol_version": "4.0",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "network": "world-chain-mainnet",
        "genesis_hash": WORLD_CHAIN_MAINNET_GENESIS_HASH,
        "external_nullifier_domain": {
            "rp_id": "app_staging_rp_example",
            "app_id": "app_staging_example",
            "action": "verify",
            "environment": "staging",
        },
        "code_epoch": "epoch-1",
    }
    payload.update(overrides)
    return payload


def _bridge(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "bridge_observation",
        "bridge_id": "bridge-obs-1",
        "source_chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "destination_chain_id": ETHEREUM_MAINNET_CHAIN_ID,
        "asset_symbol": "WLD",
        "amount_base_units": "1000000000000000000",
        "direction": "withdraw",
        "tx_hash": TX_HASH,
    }
    payload.update(overrides)
    return payload


def _mini_app(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "mini_app_evidence",
        "mini_app_id": "mini-app-1",
        "rp_id": "app_staging_rp_example",
        "app_id": "app_staging_example",
        "action": "vote",
        "session_ref": "session-ref-1",
        "evidence_digest": "sha256:" + ("22" * 32),
    }
    payload.update(overrides)
    return payload


def _action_domain(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "action_domain",
        "rp_id": "app_staging_rp_example",
        "app_id": "app_staging_example",
        "action": "login",
        "environment": "staging",
        "protocol_version": "4.0",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Import / side-effect free / registry
# ---------------------------------------------------------------------------


def test_import_worldcoin_adapter_has_no_network_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "network socket use forbidden during Worldcoin adapter import"
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if name.endswith(".crypto_ir.adapters.worldcoin") or name.endswith(
            "crypto_ir.adapters.worldcoin"
        ):
            del sys.modules[name]

    from ipfs_datasets_py.logic.crypto_ir.adapters import worldcoin as mod

    assert mod.WorldcoinAdapter is not None
    assert mod.WorldIDObservation is not None
    assert mod.NullifierBinding is not None
    assert mod.WorldChainIdentity is not None


def test_adapter_registers_in_registry() -> None:
    adapter = WorldcoinAdapter()
    registry = AdapterRegistry.from_adapters([adapter])
    entry = registry.require(
        WORLDCOIN_ADAPTER_ID,
        required_surfaces=[CapabilitySurface.OBSERVATION],
    )
    assert entry.capability.capability_id == WORLDCOIN_CAPABILITY_ID
    assert entry.capability.supports_chain_namespace("eip155")
    assert "world_id" in entry.capability.features
    assert "world_chain" in entry.capability.features
    assert "evm_composition" in entry.capability.features
    assert entry.capability.attributes["proof_implies_authorization"] is False
    assert entry.capability.attributes["collapses_authorities"] is False


# ---------------------------------------------------------------------------
# World Chain identity
# ---------------------------------------------------------------------------


def test_world_chain_identity_distinct_from_ethereum() -> None:
    result = convert_worldcoin_payload(
        {
            "kind": "world_chain_identity",
            "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
            "network": "world-chain-mainnet",
            "genesis_hash": WORLD_CHAIN_MAINNET_GENESIS_HASH,
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_authority is AuthorityKind.DECLARATION
    chain = result.result_payload["chain"]
    assert chain["chain_id"] == "480"
    assert chain["network"] == "world-chain-mainnet"
    assert chain["genesis_digest"].startswith("keccak256:")
    assert (
        chain["attributes"]["genesis_hash"]
        == WORLD_CHAIN_MAINNET_GENESIS_HASH.lower()
    )
    assert chain["attributes"]["settlement_layer"] == "ethereum-mainnet"
    assert "ethereum-mainnet" in result.result_payload["distinct_from"]
    assert "world_id_observation" in result.result_payload["distinct_from"]

    sepolia = WorldChainIdentity(chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID)
    assert sepolia.chain_id == WORLD_CHAIN_SEPOLIA_CHAIN_ID
    assert sepolia.genesis_hash == WORLD_CHAIN_SEPOLIA_GENESIS_HASH.lower()
    assert sepolia.settlement_layer == "ethereum-sepolia"


def test_world_chain_identity_rejects_ethereum_mainnet() -> None:
    with pytest.raises(WorldcoinAdapterError, match="480 or 4801"):
        WorldChainIdentity(
            chain_id=ETHEREUM_MAINNET_CHAIN_ID,
            genesis_hash=ETHEREUM_MAINNET_GENESIS_HASH,
        )


def test_is_world_chain_and_settlement_helpers() -> None:
    assert is_world_chain_id(WORLD_CHAIN_MAINNET_CHAIN_ID)
    assert is_world_chain_id(WORLD_CHAIN_SEPOLIA_CHAIN_ID)
    assert not is_world_chain_id(ETHEREUM_MAINNET_CHAIN_ID)
    assert (
        world_chain_settlement_layer(WORLD_CHAIN_MAINNET_CHAIN_ID)
        == "ethereum-mainnet"
    )


# ---------------------------------------------------------------------------
# World ID observation / nullifier / domain binding
# ---------------------------------------------------------------------------


def test_world_id_observation_preserves_domain_and_non_implications() -> None:
    result = convert_worldcoin_payload(_world_id_observation())
    assert result.status is AdapterConversionStatus.PARTIAL  # no chain binding
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION

    payload = result.result_payload
    assert payload["record_type"] == "world_id_observation"
    assert payload["proof_type"] == WORLD_ID_PROOF_TYPE
    assert payload["proof_domain"]["rp_id"] == "app_staging_rp_example"
    assert payload["proof_domain"]["action"] == "login"
    assert payload["proof_domain"]["environment"] == "staging"
    assert payload["nullifier_binding"]["nullifier_commitment"] == NULLIFIER_COMMITMENT
    assert payload["implies_transaction_authorization"] is False
    assert payload["implies_legal_identity"] is False
    assert payload["implies_account_control"] is False
    assert payload["implies_asset_transfer"] is False
    assert "world_chain_identity" in payload["distinct_from"]
    assert "wld_asset" in payload["distinct_from"]
    assert payload["chain"] is None


def test_world_id_observation_with_world_chain_binding() -> None:
    result = convert_worldcoin_payload(
        _world_id_observation(
            chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
            network="world-chain-mainnet",
            genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        )
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["chain"]["chain_id"] == "480"
    assert result.result_payload["proof_domain"]["chain_id"] == WORLD_CHAIN_MAINNET_CHAIN_ID


def test_world_id_structured_record_round_trip() -> None:
    obs = WorldIDObservation.from_dict(_world_id_observation())
    restored = WorldIDObservation.from_dict(obs.to_dict())
    assert restored.observation_id == obs.observation_id
    assert restored.nullifier_commitment == obs.nullifier_commitment
    assert restored.proof_domain == obs.proof_domain


def test_nullifier_binding_requires_domain() -> None:
    with pytest.raises(WorldcoinAdapterError):
        NullifierBinding(
            binding_id="nb-bad",
            nullifier_commitment=NULLIFIER_COMMITMENT,
            rp_id="",
            action="login",
            environment="staging",
        )
    with pytest.raises(WorldcoinAdapterError):
        NullifierBinding(
            binding_id="nb-bad",
            nullifier_commitment=NULLIFIER_COMMITMENT,
            rp_id="rp",
            action="",
            environment="staging",
        )


def test_nullifier_binding_conversion() -> None:
    result = convert_worldcoin_payload(_nullifier_binding())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    binding = result.result_payload["nullifier_binding"]
    assert binding["rp_id"] == "app_staging_rp_example"
    assert binding["action"] == "login"
    assert binding["replay_domain"]["environment"] == "staging"
    assert result.result_payload["implies_transaction_authorization"] is False
    assert "account_identity" in result.result_payload["distinct_from"]


def test_rejects_raw_nullifier_material() -> None:
    result = convert_worldcoin_payload(
        _world_id_observation(raw={"nullifier": "0xdeadbeef" * 4})
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("private field" in d for d in result.diagnostics)


def test_action_domain_mandatory_binding() -> None:
    result = convert_worldcoin_payload(_action_domain())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    domain = result.result_payload["action_domain"]
    assert domain["rp_id"]
    assert domain["action"]
    assert domain["environment"] == "staging"
    assert result.result_payload["domain_digest"].startswith("sha256:")
    assert result.result_payload["implies_nullifier_spent"] is False
    assert result.result_payload["implies_transaction_authorization"] is False


# ---------------------------------------------------------------------------
# WLD asset
# ---------------------------------------------------------------------------


def test_wld_asset_mainnet_default_contract() -> None:
    result = convert_worldcoin_payload(_wld_asset())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_authority is AuthorityKind.DECLARATION
    asset = result.result_payload["asset"]
    assert asset["symbol"] == "WLD"
    assert asset["decimals"] == 18
    assert result.result_payload["contract"] == WLD_WORLD_CHAIN_MAINNET_ADDRESS.lower()
    assert asset["chain"]["chain_id"] == "480"
    assert "world_id_observation" in result.result_payload["distinct_from"]


def test_wld_asset_sepolia_requires_explicit_contract() -> None:
    result = convert_worldcoin_payload(
        _wld_asset(
            chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID,
            network="world-chain-sepolia",
            genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
        )
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("contract_address is required" in d for d in result.diagnostics)

    sepolia_contract = "0x" + ("aa" * 20)
    ok = convert_worldcoin_payload(
        _wld_asset(
            chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID,
            network="world-chain-sepolia",
            genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
            wld_contract=sepolia_contract,
        )
    )
    assert ok.status is AdapterConversionStatus.SUCCEEDED
    assert ok.result_payload["contract"] == sepolia_contract.lower()


def test_wld_rejects_mainnet_contract_on_sepolia() -> None:
    result = convert_worldcoin_payload(
        _wld_asset(
            chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID,
            network="world-chain-sepolia",
            genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
            wld_contract=WLD_WORLD_CHAIN_MAINNET_ADDRESS,
        )
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("mainnet WLD contract must not" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# World Chain transaction reuses EVM
# ---------------------------------------------------------------------------


def test_world_chain_transaction_composes_evm() -> None:
    result = convert_worldcoin_payload(_world_chain_tx())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["record_type"] == "world_chain_transaction"
    assert result.result_payload["composition"] == "evm"
    assert result.result_payload["settlement_layer"] == "ethereum-mainnet"
    assert result.result_payload["implies_world_id_proof"] is False
    assert result.result_payload["implies_transaction_authorization"] is False

    evm = result.result_payload["evm_conversion"]
    assert evm["status"] == AdapterConversionStatus.SUCCEEDED.value
    assert evm["adapter_id"] == "crypto-ir.adapter.evm"
    chain = evm["result_payload"]["chain"]
    assert chain["chain_id"] == "480"
    assert chain["network"] == "world-chain-mainnet"
    native = evm["result_payload"]["native_transfer"]
    assert native["amount"]["base_units"] == "1000000000000000000"


def test_world_chain_transaction_rejects_ethereum_mainnet() -> None:
    result = convert_worldcoin_payload(
        _world_chain_tx(
            chain_id=ETHEREUM_MAINNET_CHAIN_ID,
            network="ethereum-mainnet",
            genesis_hash=ETHEREUM_MAINNET_GENESIS_HASH,
        )
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("480 or 4801" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Verifier / bridge / mini app — distinct domains
# ---------------------------------------------------------------------------


def test_verifier_instance_domain_bound() -> None:
    result = convert_worldcoin_payload(_verifier())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["record_type"] == "verifier_instance"
    assert result.result_payload["verifier_address"] == VERIFIER_ADDRESS.lower()
    domain = result.result_payload["external_nullifier_domain"]
    assert domain["rp_id"] == "app_staging_rp_example"
    assert domain["action"] == "verify"
    assert result.result_payload["implies_transaction_authorization"] is False
    assert result.result_payload["implies_legal_identity"] is False
    assert result.result_payload["chain"]["chain_id"] == "480"


def test_verifier_requires_domain() -> None:
    result = convert_worldcoin_payload(
        _verifier(external_nullifier_domain={"rp_id": "rp-only"})
    )
    assert result.status is AdapterConversionStatus.ERROR


def test_bridge_observation_distinct_from_proof() -> None:
    result = convert_worldcoin_payload(_bridge())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_payload["record_type"] == "bridge_observation"
    assert result.result_payload["source_chain_id"] == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert result.result_payload["destination_chain_id"] == ETHEREUM_MAINNET_CHAIN_ID
    assert result.result_payload["implies_world_id_proof"] is False
    assert "world_id_observation" in result.result_payload["distinct_from"]


def test_mini_app_evidence_distinct() -> None:
    result = convert_worldcoin_payload(_mini_app())
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.result_authority is AuthorityKind.EVIDENCE
    assert result.result_payload["record_type"] == "mini_app_evidence"
    assert result.result_payload["implies_world_id_proof"] is False
    assert result.result_payload["implies_transaction_authorization"] is False
    assert "world_id_observation" in result.result_payload["distinct_from"]


# ---------------------------------------------------------------------------
# Cross-domain composition and confusion fixtures
# ---------------------------------------------------------------------------


def test_composition_preserves_distinct_domains() -> None:
    result = convert_worldcoin_payload(
        {
            "kind": "composition",
            "composition_id": "compose-1",
            "components": [
                {
                    "kind": "world_chain_identity",
                    "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
                },
                _world_id_observation(
                    observation_id="wid-compose",
                    chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
                    network="world-chain-mainnet",
                    genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
                ),
                _wld_asset(),
                _nullifier_binding(binding_id="nb-compose"),
                _bridge(bridge_id="bridge-compose"),
                _mini_app(mini_app_id="mini-compose"),
                _verifier(verifier_id="ver-compose"),
                _action_domain(),
            ],
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    payload = result.result_payload
    assert payload["record_type"] == "worldcoin_composition"
    assert payload["distinct_domains_preserved"] is True
    lattice = payload["authority_lattice"]
    assert lattice["proof"] is True
    assert lattice["chain"] is True
    assert lattice["asset"] is True
    assert lattice["bridge"] is True
    assert lattice["mini_app"] is True
    assert lattice["collapsed"] is False
    assert lattice["proof_implies_authorization"] is False
    assert lattice["proof_implies_legal_identity"] is False

    types = set(payload["component_record_types"])
    assert "world_id_observation" in types
    assert "world_chain_identity" in types
    assert "wld_asset" in types
    assert "nullifier_binding" in types
    assert "bridge_observation" in types
    assert "mini_app_evidence" in types
    assert "verifier_instance" in types
    assert "action_domain" in types

    # Each component retains its own record_type (no collapse into one blob).
    child_types = {
        c["record_type"] for c in payload["components"] if c["record_type"]
    }
    assert child_types == types


def test_cross_domain_confusion_proof_is_not_payment() -> None:
    """A World ID proof must not be convertible as a World Chain payment."""

    proof = _world_id_observation()
    # Even if a caller mistakenly labels a proof as a chain transaction, the
    # missing tx_hash / wrong shape must not invent ledger authorization.
    confused = dict(proof)
    confused["kind"] = "world_chain_transaction"
    result = convert_worldcoin_payload(confused)
    assert result.status is AdapterConversionStatus.ERROR


def test_cross_domain_confusion_nullifier_is_not_identity() -> None:
    binding = convert_worldcoin_payload(_nullifier_binding())
    assert binding.result_payload["record_type"] == "nullifier_binding"
    assert "account_identity" in binding.result_payload["distinct_from"]
    assert binding.result_payload["implies_legal_identity"] is False
    assert binding.result_payload["implies_account_control"] is False


def test_cross_domain_confusion_wld_is_not_world_id() -> None:
    wld = convert_worldcoin_payload(_wld_asset())
    proof = convert_worldcoin_payload(
        _world_id_observation(
            chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
            network="world-chain-mainnet",
            genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        )
    )
    assert wld.result_payload["record_type"] != proof.result_payload["record_type"]
    assert wld.result_authority is AuthorityKind.DECLARATION
    assert proof.result_authority is AuthorityKind.OBSERVATION
    # Shared chain id must not merge asset and proof authorities.
    assert wld.result_payload["chain"]["chain_id"] == proof.result_payload["chain"][
        "chain_id"
    ]
    assert "world_id_observation" in wld.result_payload["distinct_from"]
    assert "wld_asset" in proof.result_payload["distinct_from"]


def test_cross_domain_confusion_bridge_is_not_verifier() -> None:
    bridge = convert_worldcoin_payload(_bridge())
    verifier = convert_worldcoin_payload(_verifier())
    assert bridge.result_payload["record_type"] != verifier.result_payload["record_type"]
    assert "verifier_instance" in bridge.result_payload["distinct_from"]
    assert "bridge_observation" in verifier.result_payload["distinct_from"]


def test_composition_with_tx_and_proof_does_not_authorize() -> None:
    result = convert_worldcoin_payload(
        {
            "kind": "composition",
            "composition_id": "compose-tx-proof",
            "components": [
                _world_chain_tx(observation_id="wc-tx-compose"),
                _world_id_observation(
                    observation_id="wid-with-tx",
                    chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
                    network="world-chain-mainnet",
                    genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
                ),
            ],
        }
    )
    assert result.status is AdapterConversionStatus.SUCCEEDED
    lattice = result.result_payload["authority_lattice"]
    assert lattice["proof"] is True
    assert lattice["chain"] is True
    assert lattice["proof_implies_authorization"] is False
    # Neither child elevates to authorization.
    for child in result.result_payload["components"]:
        assert child["result_authority"] != AuthorityKind.AUTHORIZATION.value
        assert child["source_authority"] != AuthorityKind.AUTHORIZATION.value


def test_rejects_authorization_source_provenance() -> None:
    result = convert_worldcoin_payload(
        _world_id_observation(),
        source_provenance={"authority": {"kind": "authorization"}},
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("authorization" in d for d in result.diagnostics)


def test_payload_kind_enum_covers_composition_surface() -> None:
    names = {k.value for k in WorldcoinPayloadKind}
    assert "world_id_observation" in names
    assert "nullifier_binding" in names
    assert "world_chain_identity" in names
    assert "world_chain_transaction" in names
    assert "wld_asset" in names
    assert "verifier_instance" in names
    assert "bridge_observation" in names
    assert "mini_app_evidence" in names
    assert "action_domain" in names
    assert "composition" in names


def test_convert_structured_world_id_observation_object() -> None:
    obs = WorldIDObservation.from_dict(
        _world_id_observation(
            chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
            network="world-chain-mainnet",
            genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        )
    )
    result = convert_worldcoin_payload(obs)
    assert result.status is AdapterConversionStatus.SUCCEEDED
    assert result.adapter_id == WORLDCOIN_ADAPTER_ID


def test_nested_composition_rejected() -> None:
    result = convert_worldcoin_payload(
        {
            "kind": "composition",
            "composition_id": "nested-bad",
            "components": [
                {
                    "kind": "composition",
                    "composition_id": "inner",
                    "components": [_action_domain()],
                }
            ],
        }
    )
    assert result.status is AdapterConversionStatus.ERROR
    assert any("nested composition" in d for d in result.diagnostics)

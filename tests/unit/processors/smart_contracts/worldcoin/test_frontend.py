"""CRYPTOIR-G260 World Chain contract and World ID verifier semantics.

Acceptance coverage:

* Verifier and implementation code epochs are pinned and comparable;
* chain / domain / action / external-nullifier bindings are explicit;
* proof-consumer behavior is explicit (never payment / legal / safety);
* every external verifier and bridge trust assumption is stated;
* proxy upgrades and replay boundaries fail closed;
* adversarial domain/nullifier/verifier-upgrade fixtures.
"""

from __future__ import annotations

import socket
import sys

import pytest

from ipfs_datasets_py.processors.smart_contracts.artifacts import bytes_digest
from ipfs_datasets_py.processors.smart_contracts.errors import InvalidRequestError
from ipfs_datasets_py.processors.smart_contracts.worldcoin import (
    FRONTEND_ID,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_SETTLEMENT,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    WORLD_ID_PROOF_TYPE,
    BridgeBinding,
    BridgeDirection,
    ExternalNullifier,
    ProofConsumerBehavior,
    ProofImplication,
    ReplayDomain,
    SemanticPassStatus,
    TrustSurface,
    VerifierKind,
    WorldIDVerifierBinding,
    WorldcoinContractFrontend,
    WorldcoinNormalizationResult,
    check_nullifier_replay,
    check_verifier_upgrade,
    default_bridge_trust_assumptions,
    default_verifier_trust_assumptions,
    domains_compatible,
    is_world_chain_id,
    nullifier_commitment_from_bytes,
    require_stated_trust,
)


# Minimal runtime: STOP only.
STOP_BYTECODE = bytes.fromhex("00")
# PUSH1 0x01 PUSH1 0x02 ADD STOP
ADD_BYTECODE = bytes.fromhex("600160020100")
# SELFDESTRUCT risk: PUSH1 0x00 SELFDESTRUCT
SELFDESTRUCT_BYTECODE = bytes.fromhex("6000ff")

VERIFIER_ADDR = "0x" + "42" * 20
IMPL_ADDR = "0x" + "22" * 20
NULLIFIER_COMMITMENT = "sha256:" + ("11" * 32)
NULLIFIER_OTHER = "sha256:" + ("22" * 32)


@pytest.fixture
def frontend() -> WorldcoinContractFrontend:
    return WorldcoinContractFrontend()


def _nullifier(**overrides: object) -> ExternalNullifier:
    payload = {
        "rp_id": "app_staging_rp_example",
        "app_id": "app_staging_example",
        "action": "login",
        "environment": "staging",
        "protocol_version": "4.0",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
    }
    payload.update(overrides)
    return ExternalNullifier(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AST symbols / public surface / import hygiene
# ---------------------------------------------------------------------------


def test_ast_symbols_are_exportable() -> None:
    """AST query: WorldcoinContractFrontend WorldIDVerifierBinding ExternalNullifier ReplayDomain."""

    assert WorldcoinContractFrontend is not None
    assert WorldIDVerifierBinding is not None
    assert ExternalNullifier is not None
    assert ReplayDomain is not None


def test_import_has_no_network_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network socket use forbidden during worldcoin import")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if "smart_contracts.worldcoin" in name:
            del sys.modules[name]

    from ipfs_datasets_py.processors.smart_contracts import worldcoin as mod

    assert mod.WorldcoinContractFrontend is not None
    assert mod.FRONTEND_ID == FRONTEND_ID


def test_world_chain_helpers() -> None:
    assert is_world_chain_id(WORLD_CHAIN_MAINNET_CHAIN_ID)
    assert is_world_chain_id(WORLD_CHAIN_SEPOLIA_CHAIN_ID)
    assert is_world_chain_id(480)
    assert not is_world_chain_id("1")


# ---------------------------------------------------------------------------
# External nullifier / replay domain bindings
# ---------------------------------------------------------------------------


def test_external_nullifier_domain_key_and_digest(frontend: WorldcoinContractFrontend) -> None:
    n = frontend.bind_external_nullifier(
        rp_id="app_staging_rp_example",
        action="login",
        environment="staging",
        app_id="app_staging_example",
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
    )
    assert "|login|" in n.domain_key
    assert n.domain_key.endswith(f"|{WORLD_CHAIN_MAINNET_CHAIN_ID}")
    assert n.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert n.network == "world-chain-mainnet"
    assert n.content_digest().startswith("sha256:")
    payload = n.to_dict()
    assert payload["rp_id"] == "app_staging_rp_example"
    assert payload["action"] == "login"
    assert payload["environment"] == "staging"


def test_external_nullifier_rejects_non_world_chain() -> None:
    with pytest.raises(InvalidRequestError, match="480 or 4801"):
        ExternalNullifier(
            rp_id="rp",
            action="login",
            environment="production",
            chain_id="1",
        )


def test_external_nullifier_rejects_raw_private_fields() -> None:
    with pytest.raises(InvalidRequestError, match="private field"):
        ExternalNullifier(
            rp_id="rp",
            action="login",
            environment="production",
            attributes={"raw_nullifier": "secret-value"},
        )


def test_replay_domain_registers_once(frontend: WorldcoinContractFrontend) -> None:
    frontend.clear_replay_index()
    n = _nullifier()
    first = frontend.bind_replay_domain(
        external_nullifier=n,
        nullifier_commitment=NULLIFIER_COMMITMENT,
        binding_id="b1",
        register=True,
    )
    assert first.used is False  # returned object reflects call-time used flag
    assert first.replay_key.startswith(n.domain_key)
    with pytest.raises(InvalidRequestError, match="already used"):
        frontend.bind_replay_domain(
            external_nullifier=n,
            nullifier_commitment=NULLIFIER_COMMITMENT,
            register=True,
        )


def test_same_nullifier_different_domain_is_mismatch(
    frontend: WorldcoinContractFrontend,
) -> None:
    a = _nullifier(action="login")
    b = _nullifier(action="vote")
    da = ReplayDomain(external_nullifier=a, nullifier_commitment=NULLIFIER_COMMITMENT, used=True)
    db = ReplayDomain(external_nullifier=b, nullifier_commitment=NULLIFIER_COMMITMENT, used=False)
    assert check_nullifier_replay(da, db) is SemanticPassStatus.DOMAIN_MISMATCH
    assert not domains_compatible(a, b)
    assert frontend.detect_domain_confusion(a, b) is SemanticPassStatus.DOMAIN_MISMATCH


def test_nullifier_commitment_from_bytes_never_retains_raw() -> None:
    commitment = nullifier_commitment_from_bytes(b"raw-nullifier-material")
    assert commitment.startswith("sha256:")
    assert commitment == bytes_digest(b"raw-nullifier-material")


# ---------------------------------------------------------------------------
# Verifier binding / code epochs / upgrades
# ---------------------------------------------------------------------------


def test_bind_verifier_pins_code_epoch(frontend: WorldcoinContractFrontend) -> None:
    n = _nullifier(chain_id="")  # off-chain domain; bind_verifier will attach chain
    binding = frontend.bind_verifier(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        code_epoch="epoch-1",
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        protocol_version="4.0",
        implementation_address=IMPL_ADDR,
        implementation_code_digest=bytes_digest(ADD_BYTECODE),
        proxy_kind="eip1967",
        block_number=1_000_000,
    )
    assert binding.code_epoch == "epoch-1"
    assert binding.verifier_address == VERIFIER_ADDR.lower()
    assert binding.is_proof_consumer_only is True
    assert "worldcoin.proof_not_payment_authority" in binding.trusted_assumptions
    assert "worldcoin.verifier_code_epoch_pinned" in binding.trusted_assumptions
    assert binding.external_nullifier.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert binding.content_digest().startswith("sha256:")


def test_verifier_upgrade_changes_code_epoch_fail_closed(
    frontend: WorldcoinContractFrontend,
) -> None:
    n = _nullifier()
    prev = frontend.bind_verifier(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        code_epoch="epoch-1",
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        implementation_code_digest=bytes_digest(STOP_BYTECODE),
    )
    current = frontend.bind_verifier(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        code_epoch="epoch-2",
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        implementation_code_digest=bytes_digest(ADD_BYTECODE),
    )
    assert check_verifier_upgrade(prev, current) is SemanticPassStatus.FAIL_CLOSED


def test_normalize_verifier_contract_states_trust_and_epochs(
    frontend: WorldcoinContractFrontend,
) -> None:
    frontend.clear_replay_index()
    n = _nullifier()
    result = frontend.normalize_verifier_contract(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        runtime_bytecode=ADD_BYTECODE,
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        code_epoch="epoch-1",
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verification_status="verified",
    )
    assert isinstance(result, WorldcoinNormalizationResult)
    assert result.verifier_binding is not None
    assert result.verifier_binding.code_epoch == "epoch-1"
    assert result.evm_result is not None
    assert result.evm_result.code_epoch.runtime_bytecode_digest == bytes_digest(
        ADD_BYTECODE
    )
    assert result.proof_consumer is not None
    assert result.proof_consumer.implies_payment is False
    assert result.proof_consumer.implies_legal_identity is False
    assert result.proof_consumer.implies_contract_safety is False
    assert result.settlement_layer == WORLD_CHAIN_MAINNET_SETTLEMENT

    trust_ids = {item.assumption_id for item in result.stated_trust_assumptions()}
    assert "worldcoin.verifier.soundness" in trust_ids
    assert "worldcoin.verifier_code_epoch_pinned" in trust_ids
    assert "worldcoin.proof_not_payment_authority" in trust_ids
    assert "worldcoin.bridge.op_stack_message_passing" in trust_ids
    assert "worldcoin.bridge.l1_settlement" in trust_ids
    assert "worldcoin.bridge.not_world_id_authority" in trust_ids
    assert "worldcoin.bridge.proxy_upgrade" in trust_ids


def test_normalize_verifier_detects_upgrade(
    frontend: WorldcoinContractFrontend,
) -> None:
    frontend.clear_replay_index()
    n = _nullifier()
    first = frontend.normalize_verifier_contract(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        runtime_bytecode=STOP_BYTECODE,
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        code_epoch="epoch-1",
    )
    second = frontend.normalize_verifier_contract(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        runtime_bytecode=ADD_BYTECODE,
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        code_epoch="epoch-2",
        previous_verifier=first.verifier_binding,
    )
    assert second.pass_status is SemanticPassStatus.FAIL_CLOSED
    assert any("code epoch changed" in d for d in second.diagnostics)


# ---------------------------------------------------------------------------
# Proof never implies payment / legal identity / contract safety
# ---------------------------------------------------------------------------


def test_valid_proof_never_implies_payment_or_legal_or_safety(
    frontend: WorldcoinContractFrontend,
) -> None:
    n = _nullifier()
    binding = frontend.bind_verifier(
        verifier_id="v1",
        verifier_address=VERIFIER_ADDR,
        code_epoch="e1",
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
    )
    ok = frontend.evaluate_proof_consumer(
        verification_status="verified",
        external_nullifier=binding.external_nullifier,
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verifier_binding=binding,
    )
    assert ok.pass_status is SemanticPassStatus.PASS
    assert ok.implies_payment is False
    assert ok.implies_legal_identity is False
    assert ok.implies_contract_safety is False
    assert ProofImplication.PAYMENT in ok.forbidden_implications
    assert ProofImplication.LEGAL_IDENTITY in ok.forbidden_implications
    assert ProofImplication.CONTRACT_SAFETY in ok.forbidden_implications

    bad_payment = frontend.evaluate_proof_consumer(
        verification_status="verified",
        external_nullifier=binding.external_nullifier,
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verifier_binding=binding,
        claim_payment_authorization=True,
    )
    assert bad_payment.pass_status is SemanticPassStatus.FAIL_CLOSED
    assert any("payment authority" in d for d in bad_payment.diagnostics)

    bad_legal = frontend.evaluate_proof_consumer(
        verification_status="verified",
        external_nullifier=binding.external_nullifier,
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verifier_binding=binding,
        claim_legal_identity=True,
    )
    assert bad_legal.pass_status is SemanticPassStatus.FAIL_CLOSED

    bad_safety = frontend.evaluate_proof_consumer(
        verification_status="verified",
        external_nullifier=binding.external_nullifier,
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verifier_binding=binding,
        claim_contract_safety=True,
    )
    assert bad_safety.pass_status is SemanticPassStatus.FAIL_CLOSED


def test_proof_consumer_rejects_missing_mandatory_implications() -> None:
    n = _nullifier()
    with pytest.raises(InvalidRequestError, match="forbidden_implications"):
        ProofConsumerBehavior(
            verification_status="verified",
            external_nullifier=n,
            nullifier_commitment=NULLIFIER_COMMITMENT,
            forbidden_implications=(ProofImplication.ACCOUNT_CONTROL,),
        )


# ---------------------------------------------------------------------------
# Bridge trust assumptions
# ---------------------------------------------------------------------------


def test_bridge_binding_requires_and_states_all_assumptions(
    frontend: WorldcoinContractFrontend,
) -> None:
    bridge = frontend.bind_bridge(
        bridge_id="bridge-1",
        source_chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        destination_chain_id="1",
        direction=BridgeDirection.WITHDRAW,
        asset_symbol="WLD",
        amount_base_units="1000000000000000000",
        tx_hash_ref="0x" + "ab" * 32,
        code_epoch="bridge-epoch-1",
    )
    assert bridge.implies_world_id_proof is False
    assert bridge.implies_tx_auth is False
    ids = {item.assumption_id for item in bridge.trusted_assumptions}
    assert "worldcoin.bridge.op_stack_message_passing" in ids
    assert "worldcoin.bridge.l1_settlement" in ids
    assert "worldcoin.bridge.not_world_id_authority" in ids
    assert "worldcoin.bridge.proxy_upgrade" in ids
    surfaces = {item.surface for item in bridge.trusted_assumptions}
    assert TrustSurface.OP_STACK_BRIDGE in surfaces
    assert TrustSurface.L1_SETTLEMENT in surfaces


def test_bridge_without_assumptions_fails_closed() -> None:
    with pytest.raises(InvalidRequestError, match="trusted_assumptions"):
        BridgeBinding(
            bridge_id="b1",
            source_chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
            destination_chain_id="1",
            trusted_assumptions=(),
        )


def test_normalize_bridge_observation(frontend: WorldcoinContractFrontend) -> None:
    result = frontend.normalize_bridge_observation(
        bridge_id="bridge-obs-1",
        source_chain_id="1",
        destination_chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        direction="deposit",
        asset_symbol="ETH",
        amount_base_units="1",
    )
    assert result.composition_mode.value == "bridge_only"
    assert result.bridge is not None
    assert result.pass_status is SemanticPassStatus.PASS
    assert result.to_dict()["proof_type"] == WORLD_ID_PROOF_TYPE
    assert any("stated_bridge_trust=" in d for d in result.diagnostics)


def test_default_trust_catalogs_are_nonempty() -> None:
    v = default_verifier_trust_assumptions(
        verifier_kind=VerifierKind.DEVELOPER_PORTAL
    )
    assert any(item.surface is TrustSurface.DEVELOPER_PORTAL_API for item in v)
    b = default_bridge_trust_assumptions()
    assert len(b) >= 4
    assert (
        require_stated_trust(
            b,
            required_surfaces=(
                TrustSurface.OP_STACK_BRIDGE,
                TrustSurface.L1_SETTLEMENT,
            ),
        )
        is SemanticPassStatus.PASS
    )
    assert (
        require_stated_trust(b, required_surfaces=(TrustSurface.WORLD_ID_VERIFIER,))
        is SemanticPassStatus.TRUST_UNSTATED
    )


# ---------------------------------------------------------------------------
# World Chain EVM composition
# ---------------------------------------------------------------------------


def test_normalize_world_chain_contract_composes_evm(
    frontend: WorldcoinContractFrontend,
) -> None:
    result = frontend.normalize_world_chain_contract(
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        address=VERIFIER_ADDR,
        runtime_bytecode=ADD_BYTECODE,
        block_number=42,
        code_epoch="wc-epoch-1",
        claim_semantic_pass=True,
    )
    assert result.composition_mode.value == "evm_composed"
    assert result.evm_result is not None
    assert result.evm_result.code_epoch.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert result.evm_result.code_epoch.network == "world-chain-mainnet"
    assert result.settlement_layer == "ethereum-mainnet"
    assert any("composed_evm_frontend" in d for d in result.diagnostics)
    assert result.bridge_trust
    assert result.to_dict()["stated_trust_assumptions"]


def test_normalize_rejects_ethereum_mainnet_as_world_chain(
    frontend: WorldcoinContractFrontend,
) -> None:
    with pytest.raises(InvalidRequestError, match="480 or 4801"):
        frontend.normalize_world_chain_contract(
            chain_id="1",
            address=VERIFIER_ADDR,
            runtime_bytecode=STOP_BYTECODE,
        )


def test_selfdestruct_redeployment_risk_fail_closed(
    frontend: WorldcoinContractFrontend,
) -> None:
    result = frontend.normalize_world_chain_contract(
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        address=VERIFIER_ADDR,
        runtime_bytecode=SELFDESTRUCT_BYTECODE,
        claim_semantic_pass=True,
    )
    assert any("redeployment_risk" in d or "selfdestruct" in d.lower() for d in result.diagnostics)


def test_bind_code_epoch_world_chain(frontend: WorldcoinContractFrontend) -> None:
    epoch = frontend.bind_code_epoch(
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        address=VERIFIER_ADDR,
        runtime_bytecode=ADD_BYTECODE,
        block_number=10,
        code_epoch="e1",
        compiler="solc",
        compiler_version="0.8.20",
    )
    assert epoch.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert epoch.runtime_bytecode_digest == bytes_digest(ADD_BYTECODE)
    assert epoch.network == "world-chain-mainnet"


def test_sepolia_settlement_layer(frontend: WorldcoinContractFrontend) -> None:
    result = frontend.normalize_world_chain_contract(
        chain_id=WORLD_CHAIN_SEPOLIA_CHAIN_ID,
        address=VERIFIER_ADDR,
        runtime_bytecode=STOP_BYTECODE,
    )
    assert result.settlement_layer == "ethereum-sepolia"
    assert result.network == "world-chain-sepolia"


# ---------------------------------------------------------------------------
# Adversarial domain / action confusion
# ---------------------------------------------------------------------------


def test_adversarial_action_confusion_rejects_cross_action_proof(
    frontend: WorldcoinContractFrontend,
) -> None:
    """Proof issued for action=login must not authorize action=payment."""

    login = _nullifier(action="login")
    payment = _nullifier(action="payment")
    binding = frontend.bind_verifier(
        verifier_id="v1",
        verifier_address=VERIFIER_ADDR,
        code_epoch="e1",
        external_nullifier=login,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
    )
    confused = frontend.evaluate_proof_consumer(
        verification_status="verified",
        external_nullifier=payment,
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verifier_binding=binding,
        claim_payment_authorization=True,
    )
    assert confused.pass_status in {
        SemanticPassStatus.DOMAIN_MISMATCH,
        SemanticPassStatus.FAIL_CLOSED,
    }


def test_adversarial_environment_confusion(
    frontend: WorldcoinContractFrontend,
) -> None:
    staging = _nullifier(environment="staging")
    production = _nullifier(environment="production")
    assert frontend.detect_domain_confusion(staging, production) is (
        SemanticPassStatus.DOMAIN_MISMATCH
    )


def test_result_serialization_is_secret_safe(
    frontend: WorldcoinContractFrontend,
) -> None:
    frontend.clear_replay_index()
    n = _nullifier()
    result = frontend.normalize_verifier_contract(
        verifier_id="wc-verifier-1",
        verifier_address=VERIFIER_ADDR,
        runtime_bytecode=ADD_BYTECODE,
        external_nullifier=n,
        chain_id=WORLD_CHAIN_MAINNET_CHAIN_ID,
        code_epoch="epoch-1",
        nullifier_commitment=NULLIFIER_COMMITMENT,
        verification_status="verified",
    )
    payload = result.to_dict()
    # No raw secret-like keys in the public payload.
    blob = str(payload).lower()
    assert "raw_nullifier" not in blob
    assert "private_key" not in blob
    assert result.content_digest().startswith("sha256:")
    assert payload["proof_type"] == WORLD_ID_PROOF_TYPE

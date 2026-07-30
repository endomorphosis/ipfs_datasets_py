"""CRYPTOIR-G240 XRPL native-ledger, Hooks, and sidechain semantics.

Acceptance coverage:

* Native ledger objects, amendment/capability state, issuer/freeze/clawback,
  partial payment, reserve, sequence/ticket, signer quorum, tags, and
  validated-ledger epochs are modeled;
* Hooks return ``UNSUPPORTED`` where capability evidence is absent;
* EVM sidechain delegates to the EVM frontend and is never silently treated
  as XRPL mainnet;
* Emit ``UNSUPPORTED`` / ``UNKNOWN`` instead of inventing Ethereum-style
  contract behavior.
"""

from __future__ import annotations

import socket
import sys
from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.smart_contracts.errors import InvalidRequestError
from ipfs_datasets_py.processors.smart_contracts.models import (
    AcquisitionStatus,
    ArtifactKind,
    ChainRef,
    ContractAcquisitionRequest,
    ProviderPolicy,
)
from ipfs_datasets_py.processors.smart_contracts.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.smart_contracts.xrpl import (
    FRONTEND_ID,
    RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
    RIPPLE_EVM_SIDECHAIN_NETWORK,
    TF_PARTIAL_PAYMENT,
    XRPL_MAINNET_CHAIN_ID,
    XRPL_MAINNET_NETWORK,
    XRPL_TESTNET_CHAIN_ID,
    AnalysisMode,
    HookCapability,
    HookCapabilityState,
    IssuedAsset,
    IssuerPolicy,
    LedgerObjectKind,
    LedgerObjectTransition,
    OfflineXRPLProvider,
    SemanticPassStatus,
    SidechainRouting,
    SignerQuorum,
    ValidatedLedgerEpoch,
    XRPLLedgerFixture,
    XRPLLedgerFrontend,
    XRPLTransactionType,
    default_object_kind_for_tx,
    is_ripple_evm_sidechain,
    is_xrpl_chain_id,
    normalize_classic_address,
    partial_payment_flag_set,
    resolve_xrpl_chain_id,
)


# Well-formed classic addresses (format-valid; not checksum-verified).
ACCOUNT_A = "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
ACCOUNT_B = "rPEPPER7kfTD9w2To4CQk6UCfuHM9c6GDY"
ISSUER = "rvYAfWj5gh67oV6fW32ZzP3Aw4Eubs59B"
LEDGER_HASH = "A" * 64
PARENT_HASH = "B" * 64
TX_HASH = "C" * 64
EVM_ADDR = "0x" + "11" * 20
STOP_BYTECODE = bytes.fromhex("00")


@pytest.fixture
def frontend() -> XRPLLedgerFrontend:
    return XRPLLedgerFrontend()


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="xrpl-g240",
        limits=RequestLimits(
            max_items=8,
            max_requests=16,
            max_response_bytes=1024 * 1024,
            max_depth=4,
        ),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# AST symbols / public surface / import hygiene
# ---------------------------------------------------------------------------


def test_ast_symbols_are_exportable() -> None:
    """AST query: XRPLLedgerFrontend LedgerObjectTransition HookCapability IssuerPolicy."""

    assert XRPLLedgerFrontend is not None
    assert LedgerObjectTransition is not None
    assert HookCapability is not None
    assert IssuerPolicy is not None


def test_import_has_no_network_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network socket use forbidden during xrpl import")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    for name in list(sys.modules):
        if "smart_contracts.xrpl" in name:
            del sys.modules[name]

    from ipfs_datasets_py.processors.smart_contracts import xrpl as mod

    assert mod.XRPLLedgerFrontend is not None
    assert mod.FRONTEND_ID == FRONTEND_ID


def test_network_helpers() -> None:
    assert is_xrpl_chain_id(XRPL_MAINNET_CHAIN_ID)
    assert is_xrpl_chain_id("mainnet")
    assert is_xrpl_chain_id(XRPL_TESTNET_CHAIN_ID)
    assert is_ripple_evm_sidechain(RIPPLE_EVM_SIDECHAIN_CHAIN_ID)
    assert is_ripple_evm_sidechain("ripple-evm-sidechain")
    assert not is_ripple_evm_sidechain(XRPL_MAINNET_CHAIN_ID)
    assert resolve_xrpl_chain_id("mainnet") == XRPL_MAINNET_CHAIN_ID
    with pytest.raises(InvalidRequestError, match="sidechain"):
        resolve_xrpl_chain_id(RIPPLE_EVM_SIDECHAIN_CHAIN_ID)


def test_classic_address_normalization() -> None:
    assert normalize_classic_address(ACCOUNT_A) == ACCOUNT_A
    with pytest.raises(InvalidRequestError):
        normalize_classic_address("not-an-address")
    with pytest.raises(InvalidRequestError, match="X-address"):
        # Length/shape matches X-address form (not checksum-verified).
        normalize_classic_address(
            "XV5sbjUmgPpvXv4ixFWZ5ptAYZ6PD28Sq49uo34VyjnmK5H"
        )


# ---------------------------------------------------------------------------
# Validated ledger epochs, reserves, amendments
# ---------------------------------------------------------------------------


def test_bind_validated_ledger_epoch(frontend: XRPLLedgerFrontend) -> None:
    epoch = frontend.bind_ledger_epoch(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        ledger_index=87_000_000,
        ledger_hash=LEDGER_HASH,
        parent_hash=PARENT_HASH,
        close_time=780_000_000,
        base_reserve_drops="10000000",
        owner_reserve_drops="2000000",
        enabled_amendments=("fixEscrow", "CheckCashMakeTxn", "AMM"),
    )
    payload = epoch.to_dict()
    assert payload["chain_id"] == XRPL_MAINNET_CHAIN_ID
    assert payload["network"] == XRPL_MAINNET_NETWORK
    assert payload["ledger_index"] == 87_000_000
    assert payload["ledger_hash"] == LEDGER_HASH
    assert payload["validated"] is True
    assert payload["base_reserve_drops"] == "10000000"
    assert payload["owner_reserve_drops"] == "2000000"
    assert "AMM" in payload["enabled_amendments"]
    assert epoch.content_digest().startswith("sha256:")
    assert ValidatedLedgerEpoch.from_dict(payload).ledger_index == 87_000_000


def test_unvalidated_ledger_epoch_rejected() -> None:
    with pytest.raises(InvalidRequestError, match="validated=True"):
        ValidatedLedgerEpoch(
            chain_id=XRPL_MAINNET_CHAIN_ID,
            ledger_index=1,
            ledger_hash=LEDGER_HASH,
            validated=False,
        )


def test_ledger_epoch_rejects_sidechain(frontend: XRPLLedgerFrontend) -> None:
    with pytest.raises(InvalidRequestError, match="sidechain"):
        frontend.bind_ledger_epoch(
            chain_id=RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
            ledger_index=1,
            ledger_hash=LEDGER_HASH,
        )


# ---------------------------------------------------------------------------
# Issuer / freeze / clawback policy
# ---------------------------------------------------------------------------


def test_issuer_policy_freeze_clawback(frontend: XRPLLedgerFrontend) -> None:
    policy = frontend.bind_issuer_policy(
        ISSUER,
        allow_trustline_clawback=True,
        global_freeze=False,
        no_freeze=False,
        require_auth=True,
        default_ripple=True,
        enabled_amendments=("Clawback",),
    )
    assert policy.can_clawback is True
    assert policy.can_freeze is True
    assert policy.authorize_clawback() is SemanticPassStatus.PASS
    assert policy.authorize_freeze() is SemanticPassStatus.PASS
    assert policy.authorize_freeze(global_scope=True) is SemanticPassStatus.FAIL_CLOSED


def test_issuer_policy_no_freeze_blocks_freeze(frontend: XRPLLedgerFrontend) -> None:
    policy = frontend.bind_issuer_policy(ISSUER, no_freeze=True)
    assert policy.can_freeze is False
    assert policy.authorize_freeze() is SemanticPassStatus.FAIL_CLOSED


def test_issuer_policy_clawback_requires_enablement(frontend: XRPLLedgerFrontend) -> None:
    policy = frontend.bind_issuer_policy(ISSUER, allow_trustline_clawback=False)
    assert policy.authorize_clawback() is SemanticPassStatus.FAIL_CLOSED


def test_issuer_policy_rejects_no_freeze_and_global() -> None:
    with pytest.raises(InvalidRequestError, match="no_freeze"):
        IssuerPolicy(issuer=ISSUER, no_freeze=True, global_freeze=True)


# ---------------------------------------------------------------------------
# Partial payment, sequence/ticket, tags, signer quorum
# ---------------------------------------------------------------------------


def test_partial_payment_flag() -> None:
    assert partial_payment_flag_set(TF_PARTIAL_PAYMENT) is True
    assert partial_payment_flag_set(0) is False


def test_normalize_payment_partial_and_tag(frontend: XRPLLedgerFrontend) -> None:
    result = frontend.normalize_payment(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        account=ACCOUNT_A,
        destination=ACCOUNT_B,
        amount_drops="1000000",
        delivered_amount_drops="500000",
        flags=TF_PARTIAL_PAYMENT,
        sequence=42,
        destination_tag=999,
        source_tag=1,
        ledger_index=87_000_001,
        ledger_hash=LEDGER_HASH,
        transaction_hash=TX_HASH,
    )
    assert result.routing is SidechainRouting.XRPL_NATIVE
    assert result.analysis_mode is AnalysisMode.NATIVE_LEDGER
    assert result.semantic_pass_status is SemanticPassStatus.PASS
    assert len(result.transitions) == 1
    t = result.transitions[0]
    assert t.partial_payment is True
    assert t.destination_tag == 999
    assert t.source_tag == 1
    assert t.sequence == 42
    assert t.amount_kind == "xrp"
    assert t.delivered_amount_value == "500000"
    assert result.attributes["partial_payment"] is True


def test_sequence_and_ticket_mutually_exclusive(frontend: XRPLLedgerFrontend) -> None:
    with pytest.raises(InvalidRequestError, match="mutually exclusive"):
        frontend.bind_transition(
            transition_id="bad",
            transaction_type="Payment",
            account=ACCOUNT_A,
            amount_kind="xrp",
            amount_value="1",
            sequence=1,
            ticket_sequence=2,
        )


def test_ticket_sequence_payment(frontend: XRPLLedgerFrontend) -> None:
    t = frontend.bind_transition(
        transition_id="ticket-pay",
        transaction_type=XRPLTransactionType.PAYMENT,
        account=ACCOUNT_A,
        destination=ACCOUNT_B,
        amount_kind="xrp",
        amount_value="10",
        ticket_sequence=7,
        ledger_index=10,
        ledger_hash=LEDGER_HASH,
        validated=True,
    )
    assert t.ticket_sequence == 7
    assert t.sequence is None
    assert t.semantic_status() is SemanticPassStatus.PASS


def test_signer_quorum_binding(frontend: XRPLLedgerFrontend) -> None:
    quorum = frontend.bind_signer_quorum(
        ACCOUNT_A,
        quorum=2,
        signers=(
            {"account": ACCOUNT_B, "weight": 1},
            {"account": ISSUER, "weight": 1},
        ),
    )
    assert quorum.quorum == 2
    assert len(quorum.signers) == 2
    payload = quorum.to_dict()
    assert SignerQuorum.from_dict(payload).quorum == 2


def test_signer_quorum_weight_must_meet_quorum() -> None:
    with pytest.raises(InvalidRequestError, match="weight"):
        SignerQuorum(
            account=ACCOUNT_A,
            quorum=3,
            signers=({"account": ACCOUNT_B, "weight": 1},),
        )


def test_issued_asset_payment(frontend: XRPLLedgerFrontend) -> None:
    asset = IssuedAsset(issuer=ISSUER, currency="USD")
    result = frontend.normalize_payment(
        chain_id="testnet",
        account=ACCOUNT_A,
        destination=ACCOUNT_B,
        issued_asset=asset,
        amount_value="100.5",
        delivered_amount_value="100.5",
        sequence=5,
        ledger_index=100,
        ledger_hash=LEDGER_HASH,
        transaction_hash=TX_HASH,
    )
    t = result.transitions[0]
    assert t.amount_kind == "issued"
    assert t.issued_asset is not None
    assert t.issued_asset.currency == "USD"
    assert t.issued_asset.issuer == ISSUER


def test_xrp_cannot_be_issued_asset() -> None:
    with pytest.raises(InvalidRequestError, match="native"):
        IssuedAsset(issuer=ISSUER, currency="XRP")


# ---------------------------------------------------------------------------
# Native ledger objects (trust line, escrow, offer, AMM, NFT, check, paychan)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tx_type,expected_kind",
    [
        ("TrustSet", LedgerObjectKind.TRUST_LINE),
        ("EscrowCreate", LedgerObjectKind.ESCROW),
        ("OfferCreate", LedgerObjectKind.OFFER),
        ("PaymentChannelCreate", LedgerObjectKind.PAYMENT_CHANNEL),
        ("CheckCreate", LedgerObjectKind.CHECK),
        ("SignerListSet", LedgerObjectKind.SIGNER_LIST),
        ("TicketCreate", LedgerObjectKind.TICKET),
        ("NFTokenMint", LedgerObjectKind.NFTOKEN_PAGE),
        ("AMMCreate", LedgerObjectKind.AMM),
        ("SetHook", LedgerObjectKind.HOOK),
    ],
)
def test_default_object_kind_for_tx(
    tx_type: str, expected_kind: LedgerObjectKind
) -> None:
    assert default_object_kind_for_tx(tx_type) is expected_kind


def test_trust_line_transition(frontend: XRPLLedgerFrontend) -> None:
    t = frontend.bind_transition(
        transition_id="tl-1",
        transaction_type="TrustSet",
        account=ACCOUNT_A,
        sequence=3,
        ledger_index=50,
        ledger_hash=LEDGER_HASH,
        validated=True,
        trust_line={
            "currency": "USD",
            "issuer": ISSUER,
            "limit": "1000",
            "balance": "0",
        },
        issuer_policy=IssuerPolicy(issuer=ISSUER, require_auth=True),
    )
    assert t.object_kind is LedgerObjectKind.TRUST_LINE
    assert t.trust_line is not None
    assert t.trust_line["issuer"] == ISSUER
    assert t.semantic_status() is SemanticPassStatus.PASS


def test_escrow_and_amm_and_nft_kinds(frontend: XRPLLedgerFrontend) -> None:
    for tx, kind in (
        ("EscrowCreate", LedgerObjectKind.ESCROW),
        ("AMMDeposit", LedgerObjectKind.AMM),
        ("NFTokenMint", LedgerObjectKind.NFTOKEN_PAGE),
        ("CheckCash", LedgerObjectKind.CHECK),
        ("PaymentChannelClaim", LedgerObjectKind.PAYMENT_CHANNEL),
        ("OfferCancel", LedgerObjectKind.OFFER),
    ):
        t = frontend.bind_transition(
            transition_id=f"{tx}-1",
            transaction_type=tx,
            account=ACCOUNT_A,
            sequence=1,
            ledger_index=1,
            ledger_hash=LEDGER_HASH,
            validated=True,
        )
        assert t.object_kind is kind
        assert t.semantic_status() is SemanticPassStatus.PASS


def test_unknown_transaction_type_is_unknown(frontend: XRPLLedgerFrontend) -> None:
    t = frontend.bind_transition(
        transition_id="unk",
        transaction_type="TotallyFakeType",
        account=ACCOUNT_A,
        sequence=1,
        ledger_index=1,
        ledger_hash=LEDGER_HASH,
        validated=True,
    )
    assert t.transaction_type is XRPLTransactionType.UNKNOWN
    assert t.semantic_status() is SemanticPassStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Hooks: UNSUPPORTED when absent
# ---------------------------------------------------------------------------


def test_hooks_absent_returns_unsupported(frontend: XRPLLedgerFrontend) -> None:
    hooks = frontend.bind_hook_capability(
        chain_id=XRPL_MAINNET_CHAIN_ID, present=False
    )
    assert hooks.state is HookCapabilityState.ABSENT
    assert hooks.is_supported is False
    assert hooks.evaluate_hook_claim() is SemanticPassStatus.UNSUPPORTED
    assert (
        frontend.evaluate_hooks_claim(hooks, transaction_type="SetHook")
        is SemanticPassStatus.UNSUPPORTED
    )
    assert frontend.evaluate_hooks_claim(None) is SemanticPassStatus.UNSUPPORTED


def test_hooks_proven_allows_set_hook(frontend: XRPLLedgerFrontend) -> None:
    hooks = frontend.bind_hook_capability(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        present=True,
        capability_evidence="amendment:Hooks:enabled@ledger:87000000",
        ledger_index=87_000_000,
    )
    assert hooks.state is HookCapabilityState.PROVEN
    assert hooks.is_supported is True
    assert hooks.evaluate_hook_claim() is SemanticPassStatus.PASS

    t = frontend.bind_transition(
        transition_id="set-hook-1",
        transaction_type="SetHook",
        account=ACCOUNT_A,
        sequence=9,
        ledger_index=87_000_000,
        ledger_hash=LEDGER_HASH,
        validated=True,
        hooks_capability=hooks,
        hooks_effects=({"hook_hash": "D" * 64, "flags": 0},),
    )
    assert t.object_kind is LedgerObjectKind.HOOK
    assert t.semantic_status() is SemanticPassStatus.PASS


def test_set_hook_without_capability_is_unsupported(
    frontend: XRPLLedgerFrontend,
) -> None:
    t = frontend.bind_transition(
        transition_id="set-hook-no-cap",
        transaction_type="SetHook",
        account=ACCOUNT_A,
        sequence=1,
        ledger_index=1,
        ledger_hash=LEDGER_HASH,
        validated=True,
    )
    assert t.semantic_status() is SemanticPassStatus.UNSUPPORTED


def test_hooks_effects_require_proven_capability(
    frontend: XRPLLedgerFrontend,
) -> None:
    with pytest.raises(InvalidRequestError, match="proven HookCapability"):
        frontend.bind_transition(
            transition_id="bad-hooks",
            transaction_type="Payment",
            account=ACCOUNT_A,
            amount_kind="xrp",
            amount_value="1",
            sequence=1,
            hooks_effects=({"effect": "invented"},),
        )


def test_hook_capability_proven_requires_evidence() -> None:
    with pytest.raises(InvalidRequestError, match="capability_evidence"):
        HookCapability(
            chain_id=XRPL_MAINNET_CHAIN_ID,
            state=HookCapabilityState.PROVEN,
            amendment_enabled=True,
            capability_evidence="",
        )


# ---------------------------------------------------------------------------
# EVM sidechain delegation (never XRPL mainnet)
# ---------------------------------------------------------------------------


def test_classify_routing_sidechain(frontend: XRPLLedgerFrontend) -> None:
    assert (
        frontend.classify_routing(chain_id=RIPPLE_EVM_SIDECHAIN_CHAIN_ID)
        is SidechainRouting.EVM_SIDECHAIN
    )
    assert (
        frontend.classify_routing(network="ripple-evm-sidechain")
        is SidechainRouting.EVM_SIDECHAIN
    )
    assert (
        frontend.classify_routing(chain_id=XRPL_MAINNET_CHAIN_ID)
        is SidechainRouting.XRPL_NATIVE
    )
    assert (
        frontend.classify_routing(
            chain_id=XRPL_MAINNET_CHAIN_ID, namespace="eip155"
        )
        is SidechainRouting.REJECTED_CROSS_NETWORK
    )


def test_sidechain_delegates_to_evm_frontend(frontend: XRPLLedgerFrontend) -> None:
    result = frontend.delegate_evm_sidechain(
        chain_id=RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
        address=EVM_ADDR,
        runtime_bytecode=STOP_BYTECODE,
        block_number=1_000,
        code_epoch="sidechain-epoch-1",
    )
    assert result.routing is SidechainRouting.EVM_SIDECHAIN
    assert result.analysis_mode is AnalysisMode.EVM_SIDECHAIN_DELEGATED
    assert result.chain_id == RIPPLE_EVM_SIDECHAIN_CHAIN_ID
    assert result.network == RIPPLE_EVM_SIDECHAIN_NETWORK
    assert result.attributes["xrpl_mainnet"] is False
    assert result.attributes["sidechain"] is True
    assert result.evm_delegation is not None
    # Must never claim XRPL mainnet identity
    assert result.chain_id != XRPL_MAINNET_CHAIN_ID
    assert result.chain_id != "0"


def test_sidechain_via_normalize_router(frontend: XRPLLedgerFrontend) -> None:
    result = frontend.normalize(
        chain_id=RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
        address=EVM_ADDR,
        runtime_bytecode=STOP_BYTECODE,
    )
    assert result.routing is SidechainRouting.EVM_SIDECHAIN
    assert result.evm_delegation is not None


def test_sidechain_rejects_mainnet_delegation(frontend: XRPLLedgerFrontend) -> None:
    with pytest.raises(InvalidRequestError, match="mainnet"):
        frontend.delegate_evm_sidechain(
            chain_id=XRPL_MAINNET_CHAIN_ID,
            address=EVM_ADDR,
            runtime_bytecode=STOP_BYTECODE,
        )


def test_sidechain_result_cannot_claim_mainnet_chain_id() -> None:
    with pytest.raises(InvalidRequestError, match="mainnet"):
        from ipfs_datasets_py.processors.smart_contracts.xrpl.frontend import (
            XRPLNormalizationResult,
        )

        XRPLNormalizationResult(
            analysis_mode=AnalysisMode.EVM_SIDECHAIN_DELEGATED,
            routing=SidechainRouting.EVM_SIDECHAIN,
            chain_id=XRPL_MAINNET_CHAIN_ID,
            network=RIPPLE_EVM_SIDECHAIN_NETWORK,
            semantic_pass_status=SemanticPassStatus.INCOMPLETE,
            evm_delegation={"delegated": True},
        )


# ---------------------------------------------------------------------------
# Fixture-driven offline provider
# ---------------------------------------------------------------------------


def test_fixture_normalization(frontend: XRPLLedgerFrontend) -> None:
    fixture = XRPLLedgerFixture(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        account=ACCOUNT_A,
        ledger_index=87_000_000,
        ledger_hash=LEDGER_HASH,
        sequence=100,
        balance_drops="50000000",
        base_reserve_drops="10000000",
        owner_reserve_drops="2000000",
        trust_lines=({"currency": "USD", "issuer": ISSUER, "limit": "1000"},),
        escrows=({"amount": "1000000", "destination": ACCOUNT_B},),
        offers=({"taker_gets": "100", "taker_pays": "50"},),
        payment_channels=({"amount": "500000", "destination": ACCOUNT_B},),
        checks=({"send_max": "100", "destination": ACCOUNT_B},),
        amms=({"asset": "XRP", "asset2": f"{ISSUER}/USD"},),
        nfts=({"nftoken_id": "E" * 64},),
        signer_list={
            "quorum": 1,
            "signers": [{"account": ACCOUNT_B, "weight": 1}],
        },
        enabled_amendments=("AMM", "fixEscrow"),
        require_auth=True,
        allow_trustline_clawback=False,
    )
    payment = frontend.bind_transition(
        transition_id="fixture-pay",
        transaction_type="Payment",
        account=ACCOUNT_A,
        destination=ACCOUNT_B,
        amount_kind="xrp",
        amount_value="1000",
        sequence=100,
        ledger_index=87_000_000,
        ledger_hash=LEDGER_HASH,
        validated=True,
    )
    result = frontend.normalize_from_fixture(fixture, transitions=(payment,))
    assert result.semantic_pass_status is SemanticPassStatus.PASS
    assert result.ledger_epoch is not None
    assert result.ledger_epoch.base_reserve_drops == "10000000"
    assert result.issuer_policy is not None
    assert result.issuer_policy.require_auth is True
    assert result.hooks_capability is not None
    assert result.hooks_capability.state is HookCapabilityState.ABSENT
    assert result.signer_quorum is not None
    assert result.attributes["object_counts"]["trust_lines"] == 1
    assert result.attributes["object_counts"]["escrows"] == 1
    assert result.attributes["object_counts"]["amms"] == 1


@pytest.mark.asyncio
async def test_offline_provider_state_snapshot(context: OperationContext) -> None:
    fixture = XRPLLedgerFixture(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        account=ACCOUNT_A,
        ledger_index=10,
        ledger_hash=LEDGER_HASH,
        enabled_amendments=("CheckCashMakeTxn",),
    )
    provider = OfflineXRPLProvider(fixtures=(fixture,))
    assert provider.capabilities.supports.__self__ is not None  # noqa: B018 — smoke
    request = ContractAcquisitionRequest(
        request_id="acq-1",
        chain=ChainRef(
            chain="xrpl",
            network=XRPL_MAINNET_NETWORK,
            chain_id=XRPL_MAINNET_CHAIN_ID,
            namespace="xrpl",
        ),
        artifact_kind=ArtifactKind.STATE_SNAPSHOT,
        locator=f"xrpl://{XRPL_MAINNET_CHAIN_ID}/{ACCOUNT_A}@10",
        bounds={"max_items": 4, "max_response_bytes": 1_000_000},
        provider_policy=ProviderPolicy(),
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.AVAILABLE
    assert result.artifacts
    assert "offline_fixture" in result.coverage_notes[0]


@pytest.mark.asyncio
async def test_offline_provider_rejects_bytecode(context: OperationContext) -> None:
    fixture = XRPLLedgerFixture(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        account=ACCOUNT_A,
    )
    provider = OfflineXRPLProvider(fixtures=(fixture,))
    request = ContractAcquisitionRequest(
        request_id="acq-bc",
        chain=ChainRef(
            chain="xrpl",
            network=XRPL_MAINNET_NETWORK,
            chain_id=XRPL_MAINNET_CHAIN_ID,
            namespace="xrpl",
        ),
        artifact_kind=ArtifactKind.BYTECODE,
        locator=f"xrpl://{XRPL_MAINNET_CHAIN_ID}/{ACCOUNT_A}",
        bounds={"max_items": 4, "max_response_bytes": 1_000_000},
        provider_policy=ProviderPolicy(),
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.UNSUPPORTED
    assert any("bytecode" in d.lower() or "STATE_SNAPSHOT" in d for d in result.diagnostics)


@pytest.mark.asyncio
async def test_offline_provider_rejects_sidechain(context: OperationContext) -> None:
    provider = OfflineXRPLProvider()
    request = ContractAcquisitionRequest(
        request_id="acq-sc",
        chain=ChainRef(
            chain="ripple-evm",
            network=RIPPLE_EVM_SIDECHAIN_NETWORK,
            chain_id=RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
            namespace="eip155",
        ),
        artifact_kind=ArtifactKind.STATE_SNAPSHOT,
        locator=f"xrpl://{RIPPLE_EVM_SIDECHAIN_CHAIN_ID}/{ACCOUNT_A}",
        bounds={"max_items": 4, "max_response_bytes": 1_000_000},
        provider_policy=ProviderPolicy(),
    )
    result = await provider.acquire(request, context=context)
    assert result.status is AcquisitionStatus.UNSUPPORTED


def test_fixture_rejects_sidechain_chain_id() -> None:
    with pytest.raises(InvalidRequestError, match="sidechain"):
        XRPLLedgerFixture(
            chain_id=RIPPLE_EVM_SIDECHAIN_CHAIN_ID,
            account=ACCOUNT_A,
        )


# ---------------------------------------------------------------------------
# Incomplete coverage never silently passes
# ---------------------------------------------------------------------------


def test_incomplete_transition_without_ledger_coordinate(
    frontend: XRPLLedgerFrontend,
) -> None:
    t = frontend.bind_transition(
        transition_id="incomplete",
        transaction_type="Payment",
        account=ACCOUNT_A,
        destination=ACCOUNT_B,
        amount_kind="xrp",
        amount_value="1",
        sequence=1,
        # no ledger_index / ledger_hash
    )
    assert t.semantic_status() is SemanticPassStatus.INCOMPLETE


def test_transition_round_trip_dict(frontend: XRPLLedgerFrontend) -> None:
    t = frontend.bind_transition(
        transition_id="rt-1",
        transaction_type="AccountSet",
        account=ACCOUNT_A,
        sequence=2,
        ledger_index=3,
        ledger_hash=LEDGER_HASH,
        validated=True,
        memos=({"MemoData": "hello"},),
    )
    restored = LedgerObjectTransition.from_dict(t.to_dict())
    assert restored.transition_id == t.transition_id
    assert restored.transaction_type is XRPLTransactionType.ACCOUNT_SET
    assert restored.content_digest() == t.content_digest()


def test_normalize_native_with_transitions(frontend: XRPLLedgerFrontend) -> None:
    t = frontend.bind_transition(
        transition_id="n-1",
        transaction_type="Payment",
        account=ACCOUNT_A,
        destination=ACCOUNT_B,
        amount_kind="xrp",
        amount_value="5",
        sequence=1,
        ledger_index=1,
        ledger_hash=LEDGER_HASH,
        validated=True,
    )
    result = frontend.normalize(
        chain_id=XRPL_MAINNET_CHAIN_ID,
        transitions=(t,),
        account=ACCOUNT_A,
    )
    assert result.is_pass
    assert result.routing is SidechainRouting.XRPL_NATIVE

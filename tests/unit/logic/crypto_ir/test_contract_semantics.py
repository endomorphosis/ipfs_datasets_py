"""Unit tests for chain-neutral contract state, control, and effect semantics.

Covers CRYPTOIR-G300 / CRYPTOIR-014 acceptance:

* common records preserve order, privileges, reentrancy/CPI/spend-path
  distinctions, exact assets, state/code epochs, assumptions, coverage
  frontiers, and source provenance;
* a chain adapter can declare unsupported semantics;
* lossy projection cannot satisfy a proof obligation that depends on
  discarded facts;
* shared concepts are not false equivalences between VMs and ledger models.
"""

from __future__ import annotations

import dataclasses

import pytest

from ipfs_datasets_py.logic.crypto_ir.contract_semantics import (
    AssetEffect,
    ContractSemanticModel,
    ContractStateEpoch,
    ControlEdge,
    ControlEdgeKind,
    CoverageStatus,
    EffectKind,
    PrincipalRef,
    PrivilegeFlag,
    PrivilegeSet,
    ProofObligationDependency,
    SemanticCoverage,
    StateEpochKind,
    StateInvariant,
    UnsupportedDisposition,
    UnsupportedSemantic,
    assert_obligation_admissible,
    control_kinds_are_distinct,
    ordered_control_edges,
    ordered_effects,
    project_semantic_model,
)
from ipfs_datasets_py.logic.crypto_ir.model import (
    AccountIdentity,
    AssetIdentity,
    ChainIdentity,
    CryptoAssumption,
    CryptoIRValidationError,
    ExactAmount,
    LedgerCoordinate,
    ValidityWindow,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


GENESIS = "sha256:" + ("ab" * 32)
DIGEST_A = "sha256:" + ("11" * 32)
DIGEST_B = "sha256:" + ("22" * 32)
DIGEST_C = "sha256:" + ("33" * 32)


def _chain(**overrides: object) -> ChainIdentity:
    payload = {
        "chain_namespace": "eip155",
        "network": "ethereum-mainnet",
        "genesis_digest": GENESIS,
        "chain_id": "1",
        "display_name": "Ethereum Mainnet",
    }
    payload.update(overrides)
    return ChainIdentity(**payload)  # type: ignore[arg-type]


def _account(address: str = "0xabc", **overrides: object) -> AccountIdentity:
    payload = {
        "chain": _chain(),
        "address_normalized": address.lower(),
        "address_original": address,
        "account_kind": "contract",
    }
    payload.update(overrides)
    return AccountIdentity(**payload)  # type: ignore[arg-type]


def _asset(**overrides: object) -> AssetIdentity:
    payload = {
        "chain": _chain(),
        "asset_namespace": "native",
        "asset_reference": "eth",
        "decimals": 18,
        "symbol": "ETH",
    }
    payload.update(overrides)
    return AssetIdentity(**payload)  # type: ignore[arg-type]


def _epoch(
    epoch_id: str = "epoch-1",
    *,
    kind: StateEpochKind = StateEpochKind.CODE,
    **overrides: object,
) -> ContractStateEpoch:
    payload = {
        "epoch_id": epoch_id,
        "chain": _chain(),
        "subject_id": "contract:vault",
        "kind": kind,
        "value_digest": DIGEST_A,
        "code_digest": DIGEST_B,
        "source_provenance_ids": ("prov-1",),
        "assumption_ids": ("asm-epoch",),
        "validity": ValidityWindow(start="2026-01-01T00:00:00Z"),
        "observed_at": LedgerCoordinate(sequence=12_345_678, hash=DIGEST_C),
    }
    payload.update(overrides)
    return ContractStateEpoch(**payload)  # type: ignore[arg-type]


def _edge(
    edge_id: str,
    kind: ControlEdgeKind,
    order_index: int,
    **overrides: object,
) -> ControlEdge:
    payload = {
        "edge_id": edge_id,
        "kind": kind,
        "source_node_id": "node:a",
        "target_node_id": "node:b",
        "order_index": order_index,
        "privileges": PrivilegeSet(flags=(PrivilegeFlag.CALLER, PrivilegeFlag.SIGNER)),
        "principal_ids": ("principal:caller",),
        "source_provenance_ids": ("prov-edge",),
        "assumption_ids": ("asm-edge",),
    }
    payload.update(overrides)
    return ControlEdge(**payload)  # type: ignore[arg-type]


def _effect(
    effect_id: str,
    order_index: int,
    *,
    kind: EffectKind = EffectKind.TRANSFER,
    **overrides: object,
) -> AssetEffect:
    payload = {
        "effect_id": effect_id,
        "kind": kind,
        "order_index": order_index,
        "asset": _asset(),
        "amount": ExactAmount.from_int(1_000_000_000_000_000_000, decimals=18),
        "from_account": _account("0xFrom"),
        "to_account": _account("0xTo"),
        "source_provenance_ids": ("prov-effect",),
        "assumption_ids": ("asm-effect",),
    }
    payload.update(overrides)
    return AssetEffect(**payload)  # type: ignore[arg-type]


def _model(**overrides: object) -> ContractSemanticModel:
    epoch = _epoch()
    reentrant = _edge("edge-reenter", ControlEdgeKind.REENTRANT_CALL, 0)
    cpi = _edge(
        "edge-cpi",
        ControlEdgeKind.CPI,
        1,
        source_node_id="prog:a",
        target_node_id="prog:b",
        privileges=PrivilegeSet(flags=(PrivilegeFlag.SIGNER, PrivilegeFlag.WRITABLE)),
    )
    spend = _edge(
        "edge-spend",
        ControlEdgeKind.SPEND_PATH,
        2,
        source_node_id="utxo:in",
        target_node_id="script:redeem",
        privileges=PrivilegeSet(flags=(PrivilegeFlag.SPENDER,)),
    )
    transfer = _effect("eff-1", 0)
    storage = _effect(
        "eff-storage",
        1,
        kind=EffectKind.STORAGE_WRITE,
        asset=None,
        amount=None,
        from_account=None,
        to_account=None,
        summary="slot write",
    )
    payload = {
        "model_id": "model-1",
        "chain_namespace": "multi",
        "state_epochs": (epoch,),
        "principals": (
            PrincipalRef(
                principal_id="principal:caller",
                privileges=PrivilegeSet(
                    flags=(PrivilegeFlag.CALLER, PrivilegeFlag.SIGNER)
                ),
            ),
        ),
        "control_edges": (reentrant, cpi, spend),
        "effects": (transfer, storage),
        "invariants": (
            StateInvariant(
                invariant_id="inv-1",
                statement="total supply conserved",
                subject_ids=("contract:vault",),
                source_provenance_ids=("prov-inv",),
            ),
        ),
        "assumptions": (
            CryptoAssumption(
                assumption_id="asm-1",
                statement="oracle is fresh within 1 hour",
                source_refs=("src-oracle",),
            ),
        ),
        "coverage": (
            SemanticCoverage(
                coverage_id="cov-control",
                dimension="control_flow",
                status=CoverageStatus.COVERED,
                covered_fact_ids=(
                    reentrant.fact_id,
                    cpi.fact_id,
                    spend.fact_id,
                ),
                source_provenance_ids=("prov-cov",),
            ),
            SemanticCoverage(
                coverage_id="cov-effects",
                dimension="asset_effects",
                status=CoverageStatus.PARTIAL,
                covered_fact_ids=(transfer.fact_id,),
                frontier_fact_ids=("frontier:external-token",),
                source_provenance_ids=("prov-cov",),
            ),
        ),
        "source_provenance_ids": ("prov-model",),
    }
    payload.update(overrides)
    return ContractSemanticModel(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ContractStateEpoch
# ---------------------------------------------------------------------------


class TestContractStateEpoch:
    def test_round_trip_and_frozen(self) -> None:
        epoch = _epoch()
        restored = ContractStateEpoch.from_dict(epoch.to_dict())
        assert restored == epoch
        assert restored.fact_id == "epoch:epoch-1"
        assert restored.kind is StateEpochKind.CODE
        assert restored.source_provenance_ids == ("prov-1",)
        assert restored.assumption_ids == ("asm-epoch",)
        with pytest.raises(dataclasses.FrozenInstanceError):
            epoch.epoch_id = "mutated"  # type: ignore[misc]

    def test_content_identity_stable(self) -> None:
        a = _epoch()
        b = _epoch()
        assert a.identity.digest == b.identity.digest
        c = _epoch(value_digest=DIGEST_C)
        assert a.identity.digest != c.identity.digest

    def test_to_time_bounded_epoch(self) -> None:
        epoch = _epoch(kind=StateEpochKind.PROXY)
        tbe = epoch.to_time_bounded_epoch()
        assert tbe.epoch_id == epoch.epoch_id
        assert tbe.kind == "proxy"
        assert tbe.value_digest == epoch.value_digest

    def test_rejects_unknown_fields(self) -> None:
        raw = _epoch().to_dict()
        raw["extra"] = True
        with pytest.raises(CryptoIRValidationError, match="unknown"):
            ContractStateEpoch.from_dict(raw)


# ---------------------------------------------------------------------------
# Privileges and principals
# ---------------------------------------------------------------------------


class TestPrivileges:
    def test_privilege_set_membership_and_round_trip(self) -> None:
        privs = PrivilegeSet(flags=(PrivilegeFlag.SIGNER, PrivilegeFlag.WRITABLE))
        assert PrivilegeFlag.SIGNER in privs
        assert privs.has("writable")
        assert PrivilegeFlag.OWNER not in privs
        restored = PrivilegeSet.from_dict(privs.to_dict())
        assert restored.flags == privs.flags

    def test_principal_preserves_privileges(self) -> None:
        principal = PrincipalRef(
            principal_id="p1",
            privileges=PrivilegeSet(flags=("signer", "writable")),
        )
        assert principal.privileges.has(PrivilegeFlag.SIGNER)
        restored = PrincipalRef.from_dict(principal.to_dict())
        assert restored.privileges.flags == principal.privileges.flags


# ---------------------------------------------------------------------------
# Control edges: order and distinctions
# ---------------------------------------------------------------------------


class TestControlEdge:
    def test_order_preserved(self) -> None:
        edges = (
            _edge("e2", ControlEdgeKind.CPI, 2),
            _edge("e0", ControlEdgeKind.REENTRANT_CALL, 0),
            _edge("e1", ControlEdgeKind.SPEND_PATH, 1),
        )
        ordered = ordered_control_edges(edges)
        assert [e.edge_id for e in ordered] == ["e0", "e1", "e2"]
        assert [e.order_index for e in ordered] == [0, 1, 2]

    def test_duplicate_order_rejected(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="order_index"):
            ordered_control_edges(
                (
                    _edge("e0", ControlEdgeKind.CALL, 0),
                    _edge("e1", ControlEdgeKind.CALL, 0),
                )
            )

    def test_reentrancy_cpi_spend_path_are_distinct_kinds(self) -> None:
        reentrant = ControlEdgeKind.REENTRANT_CALL
        cpi = ControlEdgeKind.CPI
        spend = ControlEdgeKind.SPEND_PATH
        call = ControlEdgeKind.CALL
        assert control_kinds_are_distinct(reentrant, cpi)
        assert control_kinds_are_distinct(cpi, spend)
        assert control_kinds_are_distinct(spend, call)
        assert control_kinds_are_distinct(reentrant, call)
        # Not false equivalences: CPI is not CALL, spend path is not reentrancy.
        assert reentrant is not cpi
        assert cpi is not call
        assert spend is not reentrant

    def test_round_trip_preserves_privileges_and_provenance(self) -> None:
        edge = _edge(
            "e-priv",
            ControlEdgeKind.CPI,
            0,
            privileges=PrivilegeSet(
                flags=(PrivilegeFlag.SIGNER, PrivilegeFlag.WRITABLE, PrivilegeFlag.OWNER)
            ),
            source_provenance_ids=("prov-a", "prov-b"),
        )
        restored = ControlEdge.from_dict(edge.to_dict())
        assert restored.privileges.flags == edge.privileges.flags
        assert restored.source_provenance_ids == ("prov-a", "prov-b")
        assert restored.kind is ControlEdgeKind.CPI


# ---------------------------------------------------------------------------
# Asset effects
# ---------------------------------------------------------------------------


class TestAssetEffect:
    def test_order_and_exact_amount(self) -> None:
        effects = (
            _effect("e1", 1, amount=ExactAmount.from_int(2, decimals=0)),
            _effect("e0", 0, amount=ExactAmount.from_int(1, decimals=0)),
        )
        ordered = ordered_effects(effects)
        assert [e.effect_id for e in ordered] == ["e0", "e1"]
        assert ordered[0].amount is not None
        assert ordered[0].amount.base_units == "1"

    def test_rejects_float_amount(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="float"):
            AssetEffect(
                effect_id="bad",
                kind=EffectKind.TRANSFER,
                order_index=0,
                asset=_asset(),
                amount=1.5,  # type: ignore[arg-type]
            )

    def test_monetary_requires_asset_and_amount(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="exact asset"):
            AssetEffect(
                effect_id="bad",
                kind=EffectKind.TRANSFER,
                order_index=0,
                amount=ExactAmount.from_int(1),
            )
        with pytest.raises(CryptoIRValidationError, match="exact amount"):
            AssetEffect(
                effect_id="bad",
                kind=EffectKind.MINT,
                order_index=0,
                asset=_asset(),
            )

    def test_storage_write_may_omit_asset(self) -> None:
        effect = AssetEffect(
            effect_id="slot",
            kind=EffectKind.STORAGE_WRITE,
            order_index=0,
            summary="SSTORE",
        )
        assert effect.asset is None
        assert effect.amount is None
        restored = AssetEffect.from_dict(effect.to_dict())
        assert restored == effect


# ---------------------------------------------------------------------------
# Semantic coverage and unsupported
# ---------------------------------------------------------------------------


class TestCoverageAndUnsupported:
    def test_coverage_frontier_round_trip(self) -> None:
        cov = SemanticCoverage(
            coverage_id="cov-1",
            dimension="storage",
            status=CoverageStatus.PARTIAL,
            covered_fact_ids=("fact:a",),
            frontier_fact_ids=("fact:frontier",),
            missing_fact_ids=("fact:missing",),
            source_provenance_ids=("prov-1",),
            assumption_ids=("asm-1",),
        )
        restored = SemanticCoverage.from_dict(cov.to_dict())
        assert restored.frontier_fact_ids == ("fact:frontier",)
        assert restored.missing_fact_ids == ("fact:missing",)
        assert restored.status is CoverageStatus.PARTIAL

    def test_covered_cannot_list_missing(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="missing_fact_ids"):
            SemanticCoverage(
                coverage_id="cov-bad",
                dimension="x",
                status=CoverageStatus.COVERED,
                missing_fact_ids=("x",),
            )

    def test_adapter_declares_unsupported_semantic(self) -> None:
        unsupported = UnsupportedSemantic(
            unsupported_id="u-hooks",
            code="xrpl.hooks_not_modeled",
            message="XRPL Hooks WASM semantics are out of scope for this adapter",
            disposition=UnsupportedDisposition.FAIL_CLOSED,
            chain_namespace="xrpl",
            dimension="hooks",
            discarded_fact_ids=("fact:hook-body", "fact:hook-api"),
            source_provenance_ids=("prov-adapter",),
        )
        restored = UnsupportedSemantic.from_dict(unsupported.to_dict())
        assert restored.disposition is UnsupportedDisposition.FAIL_CLOSED
        assert restored.discarded_fact_ids == ("fact:hook-body", "fact:hook-api")
        assert restored.chain_namespace == "xrpl"


# ---------------------------------------------------------------------------
# Aggregate model
# ---------------------------------------------------------------------------


class TestContractSemanticModel:
    def test_model_orders_edges_and_effects(self) -> None:
        model = _model(
            control_edges=(
                _edge("late", ControlEdgeKind.CALL, 5),
                _edge("early", ControlEdgeKind.RETURN, 1),
            ),
            effects=(
                _effect("later", 3),
                _effect("earlier", 0),
            ),
            coverage=(),
        )
        assert [e.edge_id for e in model.control_edges] == ["early", "late"]
        assert [e.effect_id for e in model.effects] == ["earlier", "later"]

    def test_round_trip_preserves_distinctions(self) -> None:
        model = _model()
        restored = ContractSemanticModel.from_dict(model.to_dict())
        kinds = [edge.kind for edge in restored.control_edges]
        assert ControlEdgeKind.REENTRANT_CALL in kinds
        assert ControlEdgeKind.CPI in kinds
        assert ControlEdgeKind.SPEND_PATH in kinds
        assert kinds.count(ControlEdgeKind.REENTRANT_CALL) == 1
        assert restored.assumptions[0].assumption_id == "asm-1"
        assert restored.state_epochs[0].kind is StateEpochKind.CODE
        assert restored.source_provenance_ids == ("prov-model",)
        # Identity is content-addressed and stable.
        assert restored.identity.digest == model.identity.digest

    def test_frozen(self) -> None:
        model = _model()
        with pytest.raises(dataclasses.FrozenInstanceError):
            model.model_id = "x"  # type: ignore[misc]

    def test_duplicate_edge_ids_rejected(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="unique"):
            _model(
                control_edges=(
                    _edge("same", ControlEdgeKind.CALL, 0),
                    _edge("same", ControlEdgeKind.CPI, 1),
                ),
                coverage=(),
            )


# ---------------------------------------------------------------------------
# Lossy projection vs proof obligations
# ---------------------------------------------------------------------------


class TestProjectionAndObligations:
    def test_obligation_admissible_when_facts_covered(self) -> None:
        model = _model()
        edge_fact = model.control_edges[0].fact_id
        effect_fact = model.effects[0].fact_id
        obligation = ProofObligationDependency(
            obligation_id="ob-reentrancy",
            required_fact_ids=(edge_fact, effect_fact),
            summary="reentrancy-safe value conservation",
        )
        assert_obligation_admissible(model, obligation)

    def test_lossy_projection_rejects_obligation_on_discarded_facts(self) -> None:
        model = _model()
        reentrant_fact = next(
            edge.fact_id
            for edge in model.control_edges
            if edge.kind is ControlEdgeKind.REENTRANT_CALL
        )
        obligation = ProofObligationDependency(
            obligation_id="ob-reentrancy",
            required_fact_ids=(reentrant_fact,),
            summary="requires reentrancy edge",
        )
        # Full model is fine.
        assert_obligation_admissible(model, obligation)

        projected = project_semantic_model(
            model, drop_fact_ids=(reentrant_fact,)
        )
        assert reentrant_fact in projected.discarded_fact_ids()
        assert all(
            edge.kind is not ControlEdgeKind.REENTRANT_CALL
            for edge in projected.control_edges
        )
        with pytest.raises(CryptoIRValidationError, match="lossy projection"):
            assert_obligation_admissible(projected, obligation)

    def test_unsupported_discarded_facts_block_obligation(self) -> None:
        model = _model(
            unsupported=(
                UnsupportedSemantic(
                    unsupported_id="u1",
                    code="solana.arbitrary_cpi",
                    message="CPI target program data not acquired",
                    disposition=UnsupportedDisposition.FAIL_CLOSED,
                    discarded_fact_ids=("fact:cpi-target-code",),
                    chain_namespace="solana",
                    dimension="cpi",
                ),
            ),
        )
        obligation = ProofObligationDependency(
            obligation_id="ob-cpi",
            required_fact_ids=("fact:cpi-target-code",),
        )
        with pytest.raises(CryptoIRValidationError, match="discarded facts"):
            assert_obligation_admissible(model, obligation)

    def test_uncovered_facts_block_obligation(self) -> None:
        model = _model(coverage=(), control_edges=(), effects=(), state_epochs=())
        obligation = ProofObligationDependency(
            obligation_id="ob-missing",
            required_fact_ids=("fact:never-modeled",),
        )
        with pytest.raises(CryptoIRValidationError, match="uncovered facts"):
            assert_obligation_admissible(model, obligation)

    def test_projection_with_explicit_unsupported_record(self) -> None:
        model = _model()
        cpi_fact = next(
            edge.fact_id
            for edge in model.control_edges
            if edge.kind is ControlEdgeKind.CPI
        )
        mark = UnsupportedSemantic(
            unsupported_id="adapter-drop-cpi",
            code="projection.drop_cpi",
            message="CPI edges dropped in simplified view",
            disposition=UnsupportedDisposition.EXCLUDE,
            discarded_fact_ids=(cpi_fact,),
            chain_namespace="solana",
            dimension="cpi",
        )
        projected = project_semantic_model(
            model,
            drop_fact_ids=(cpi_fact,),
            mark_unsupported=(mark,),
        )
        codes = {item.code for item in projected.unsupported}
        assert "projection.drop_cpi" in codes
        assert "lossy_projection" in codes
        with pytest.raises(CryptoIRValidationError):
            assert_obligation_admissible(
                projected,
                ProofObligationDependency(
                    obligation_id="ob",
                    required_fact_ids=(cpi_fact,),
                ),
            )


# ---------------------------------------------------------------------------
# No false equivalences
# ---------------------------------------------------------------------------


class TestNoFalseEquivalences:
    def test_vm_call_not_equated_to_ledger_transition(self) -> None:
        assert ControlEdgeKind.CALL is not ControlEdgeKind.NATIVE_TRANSITION
        assert ControlEdgeKind.DELEGATECALL is not ControlEdgeKind.HOOK
        assert EffectKind.TRANSFER is not EffectKind.SPEND
        assert EffectKind.STORAGE_WRITE is not EffectKind.ACCOUNT_DATA_WRITE
        assert StateEpochKind.CODE is not StateEpochKind.LEDGER_OBJECT
        assert StateEpochKind.PROGRAM_DATA is not StateEpochKind.SCRIPT

    def test_model_can_hold_mixed_chain_kinds_without_collapse(self) -> None:
        """Shared model host for multiple chain concepts without renaming."""

        model = ContractSemanticModel(
            model_id="mixed",
            chain_namespace="mixed",
            control_edges=(
                _edge("evm-call", ControlEdgeKind.CALL, 0),
                _edge("sol-cpi", ControlEdgeKind.CPI, 1),
                _edge("btc-spend", ControlEdgeKind.SPEND_PATH, 2),
                _edge("xrpl-native", ControlEdgeKind.NATIVE_TRANSITION, 3),
            ),
            effects=(
                _effect("erc20", 0, kind=EffectKind.TRANSFER),
                _effect(
                    "utxo-spend",
                    1,
                    kind=EffectKind.SPEND,
                    amount=ExactAmount.from_int(50_000, decimals=0),
                    asset=AssetIdentity(
                        chain=_chain(
                            chain_namespace="bip122",
                            network="bitcoin-mainnet",
                            chain_id="",
                            display_name="Bitcoin",
                        ),
                        asset_namespace="native",
                        asset_reference="btc",
                        decimals=8,
                        symbol="BTC",
                    ),
                ),
            ),
        )
        kinds = {edge.kind for edge in model.control_edges}
        assert kinds == {
            ControlEdgeKind.CALL,
            ControlEdgeKind.CPI,
            ControlEdgeKind.SPEND_PATH,
            ControlEdgeKind.NATIVE_TRANSITION,
        }
        effect_kinds = {effect.kind for effect in model.effects}
        assert EffectKind.TRANSFER in effect_kinds
        assert EffectKind.SPEND in effect_kinds
        # Labels remain distinct after serialization.
        wire = model.to_dict()
        wire_kinds = {item["kind"] for item in wire["control_edges"]}
        assert wire_kinds == {"call", "cpi", "spend_path", "native_transition"}

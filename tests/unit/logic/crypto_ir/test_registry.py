"""Unit tests for Crypto IR capabilities, adapters, registry, and verdicts.

Covers CRYPTOIR-G030 / CRYPTOIR-004 acceptance:

* discovery has no import-time network or installation;
* adapters preserve provenance and unsupported fields;
* proof, satisfiability, monitor, readiness, heuristic, sanctions, and policy
  results cannot be silently coerced;
* capability identities bind implementation and semantic versions;
* unavailable capabilities return typed fail-closed results.
"""

from __future__ import annotations

import dataclasses
import socket
import sys
from types import MappingProxyType
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir import (
    AdapterConversionResult,
    AdapterConversionStatus,
    AdapterRegistry,
    AnalysisOutcome,
    AnalysisVerdict,
    AuthorityKind,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityStatus,
    CapabilitySurface,
    CryptoIRAdapter,
    CryptoIRCapabilityError,
    CryptoIRProvenance,
    CryptoIRRegistryError,
    CryptoIRVerdictError,
    NullCryptoIRAdapter,
    ObservationProvenance,
    PolicyOutcome,
    PolicyVerdict,
    ReadinessOutcome,
    SatisfiabilityOutcome,
    TransactionVerdict,
    TransactionVerdictOutcome,
    TypedFamilyVerdict,
    UnsupportedField,
    VerdictFamily,
    AuthorityBinding,
    capability_identity_tuple,
    empty_registry,
    fail_closed_for_unavailable,
    probe_capability,
    prover_backend_capability,
    refuse_verdict_coercion,
    result_family_of,
    transaction_blocks_automation,
    unavailable_analysis_verdict,
    wallet_records_capability,
)
from ipfs_datasets_py.logic.crypto_ir.adapters import (
    CryptoIRAdapterError,
    adapter_capability_identity,
    adapter_is_available,
    conversion_elevates_authority,
    unavailable_conversion,
)
from ipfs_datasets_py.logic.crypto_ir.capabilities import (
    same_capability_identity,
    security_ir_capability,
    software_contract_ir_capability,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    HeuristicOutcome,
    MonitorOutcome,
    SanctionsMatchLevel,
    policy_outcome_fail_closed,
)


# ---------------------------------------------------------------------------
# Import-time side-effect rejection
# ---------------------------------------------------------------------------


def test_import_crypto_ir_has_no_network_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-importing capability/registry modules must not open sockets."""

    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network socket use forbidden during crypto_ir import")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    # Drop modules so import re-executes under the blocked socket.
    for name in list(sys.modules):
        if name.startswith("ipfs_datasets_py.logic.crypto_ir"):
            del sys.modules[name]

    import ipfs_datasets_py.logic.crypto_ir as crypto_ir
    import ipfs_datasets_py.logic.crypto_ir.capabilities as capabilities
    import ipfs_datasets_py.logic.crypto_ir.registry as registry
    import ipfs_datasets_py.logic.crypto_ir.verdicts as verdicts
    import ipfs_datasets_py.logic.crypto_ir.adapters as adapters

    # Touch public symbols so lazy exports resolve under blocked networking.
    assert crypto_ir.CapabilityDescriptor is capabilities.CapabilityDescriptor
    assert crypto_ir.AdapterRegistry is registry.AdapterRegistry
    assert crypto_ir.AnalysisVerdict is verdicts.AnalysisVerdict
    assert crypto_ir.CryptoIRAdapter is adapters.CryptoIRAdapter
    assert crypto_ir.NullCryptoIRAdapter is adapters.NullCryptoIRAdapter


def test_package_exports_g030_symbols() -> None:
    import ipfs_datasets_py.logic.crypto_ir as crypto_ir

    for name in (
        "CapabilityDescriptor",
        "AdapterRegistry",
        "AnalysisVerdict",
        "PolicyVerdict",
        "CryptoIRAdapter",
        "NullCryptoIRAdapter",
        "VerdictFamily",
        "refuse_verdict_coercion",
    ):
        assert name in crypto_ir.__all__
        assert getattr(crypto_ir, name) is not None


# ---------------------------------------------------------------------------
# Capability identity binds implementation + semantic versions
# ---------------------------------------------------------------------------


def test_capability_identity_binds_both_versions() -> None:
    base = wallet_records_capability(
        capability_id="wallet.evm",
        implementation_version="1.0.0",
        semantic_version="1.0.0",
        chain_namespaces=("eip155",),
    )
    other_impl = wallet_records_capability(
        capability_id="wallet.evm",
        implementation_version="1.0.1",
        semantic_version="1.0.0",
        chain_namespaces=("eip155",),
    )
    other_sem = wallet_records_capability(
        capability_id="wallet.evm",
        implementation_version="1.0.0",
        semantic_version="1.1.0",
        chain_namespaces=("eip155",),
    )
    assert base.identity.cid != other_impl.identity.cid
    assert base.identity.cid != other_sem.identity.cid
    assert capability_identity_tuple(base) == ("wallet.evm", "1.0.0", "1.0.0")
    restored = CapabilityDescriptor.from_dict(base.to_dict())
    assert restored == base
    assert restored.identity.cid == base.identity.cid


def test_capability_rejects_side_effects_and_bad_semver() -> None:
    with pytest.raises(CryptoIRCapabilityError, match="side-effect-free"):
        CapabilityDescriptor(
            capability_id="bad",
            kind=CapabilityKind.WALLET_RECORDS,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            side_effect_free=False,
        )
    with pytest.raises(CryptoIRCapabilityError, match="semantic version"):
        CapabilityDescriptor(
            capability_id="bad",
            kind=CapabilityKind.WALLET_RECORDS,
            implementation_version="v1",
            semantic_version="1.0.0",
        )


def test_capability_descriptor_is_frozen() -> None:
    cap = prover_backend_capability(
        capability_id="prover.z3",
        implementation_version="4.12.0",
        semantic_version="1.0.0",
        features=("theorem_proof", "sat"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        cap.status = CapabilityStatus.UNAVAILABLE  # type: ignore[misc]
    assert isinstance(cap.attributes, MappingProxyType)


# ---------------------------------------------------------------------------
# Unavailable capabilities → typed fail-closed results
# ---------------------------------------------------------------------------


def test_probe_unavailable_capability() -> None:
    cap = wallet_records_capability(
        capability_id="wallet.offline",
        implementation_version="1.0.0",
        semantic_version="1.0.0",
        status=CapabilityStatus.UNAVAILABLE,
    )
    probe = probe_capability(cap)
    assert probe.available is False
    assert probe.status is CapabilityStatus.UNAVAILABLE


def test_probe_missing_required_surface() -> None:
    cap = wallet_records_capability(
        capability_id="wallet.evm",
        implementation_version="1.0.0",
        semantic_version="1.0.0",
    )
    probe = probe_capability(
        cap, required_surfaces=(CapabilitySurface.ANALYSIS,)
    )
    assert probe.available is False
    assert "analysis" in probe.missing_surfaces


def test_fail_closed_for_unavailable_analysis() -> None:
    cap = prover_backend_capability(
        capability_id="prover.missing",
        implementation_version="1.0.0",
        semantic_version="1.0.0",
        status=CapabilityStatus.UNAVAILABLE,
    )
    result = fail_closed_for_unavailable(
        cap,
        capability_id=cap.capability_id,
        family=VerdictFamily.ANALYSIS,
        subject_id="obl-1",
    )
    assert isinstance(result, AnalysisVerdict)
    assert result.outcome is AnalysisOutcome.INCONCLUSIVE
    assert result.fail_closed is True
    assert result.payload["unavailable"] is True


def test_fail_closed_for_unavailable_readiness() -> None:
    result = fail_closed_for_unavailable(
        None,
        capability_id="cap.x",
        family=VerdictFamily.READINESS,
        subject_id="gate-1",
    )
    assert isinstance(result, TypedFamilyVerdict)
    assert result.family is VerdictFamily.READINESS
    assert result.outcome == ReadinessOutcome.NOT_READY.value


def test_fail_closed_refuses_authorization_fabrication() -> None:
    with pytest.raises(CryptoIRCapabilityError, match="authorization"):
        fail_closed_for_unavailable(
            None,
            capability_id="cap.x",
            family=VerdictFamily.AUTHORIZATION,
            subject_id="tx-1",
        )


# ---------------------------------------------------------------------------
# Non-interchangeable verdicts
# ---------------------------------------------------------------------------


def test_analysis_and_policy_verdict_round_trip() -> None:
    analysis = AnalysisVerdict(
        verdict_id="av-1",
        outcome=AnalysisOutcome.PROVED,
        obligation_id="obl-auth",
        assumption_ids=("asm-1",),
        backend_id="prover.z3",
        summary="proved under assumptions",
    )
    assert AnalysisVerdict.from_dict(analysis.to_dict()) == analysis
    assert analysis.identity.cid.startswith("b")
    assert analysis.authority_kind is AuthorityKind.RESULT
    assert analysis.cannot_authorize_transaction() is True
    assert analysis.fail_closed is False

    policy = PolicyVerdict(
        verdict_id="pv-1",
        outcome=PolicyOutcome.PASS,
        policy_id="sanctions-us",
        policy_revision="2026-07-01",
        jurisdiction="US",
    )
    assert PolicyVerdict.from_dict(policy.to_dict()) == policy
    assert result_family_of(policy) is VerdictFamily.POLICY
    assert policy.cannot_authorize_transaction() is True
    assert policy.fail_closed is False
    assert policy_outcome_fail_closed(PolicyOutcome.ERROR) is True
    assert policy_outcome_fail_closed(PolicyOutcome.PASS) is False


def test_transaction_verdict_blocks_non_allow() -> None:
    allow = TransactionVerdict(
        verdict_id="tv-allow",
        outcome=TransactionVerdictOutcome.ALLOW,
        intent_id="intent-1",
        candidate_id="cand-1",
        policy_id="preflight-v1",
    )
    deny = TransactionVerdict(
        verdict_id="tv-deny",
        outcome=TransactionVerdictOutcome.DENY,
        intent_id="intent-1",
        candidate_id="cand-1",
        policy_id="preflight-v1",
    )
    assert allow.blocks_automation is False
    assert deny.blocks_automation is True
    assert transaction_blocks_automation(TransactionVerdictOutcome.STALE) is True
    assert allow.authority_kind is AuthorityKind.AUTHORIZATION


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (VerdictFamily.SATISFIABILITY, VerdictFamily.ANALYSIS),
        (VerdictFamily.MONITOR, VerdictFamily.ANALYSIS),
        (VerdictFamily.READINESS, VerdictFamily.POLICY),
        (VerdictFamily.HEURISTIC, VerdictFamily.SANCTIONS),
        (VerdictFamily.ANALYSIS, VerdictFamily.AUTHORIZATION),
        (VerdictFamily.POLICY, VerdictFamily.AUTHORIZATION),
        (VerdictFamily.SANCTIONS, VerdictFamily.ANALYSIS),
    ],
)
def test_refuse_verdict_coercion_across_families(
    source: VerdictFamily, target: VerdictFamily
) -> None:
    with pytest.raises(CryptoIRVerdictError, match="cannot coerce"):
        refuse_verdict_coercion(source, target)


def test_same_family_coercion_is_identity() -> None:
    refuse_verdict_coercion(VerdictFamily.ANALYSIS, VerdictFamily.ANALYSIS)


def test_typed_family_verdicts_reject_wrong_outcomes() -> None:
    sat = TypedFamilyVerdict(
        verdict_id="sat-1",
        family=VerdictFamily.SATISFIABILITY,
        outcome=SatisfiabilityOutcome.SATISFIABLE.value,
        subject_id="formula-1",
    )
    assert sat.authority_kind is AuthorityKind.RESULT
    with pytest.raises(CryptoIRVerdictError):
        TypedFamilyVerdict(
            verdict_id="sat-bad",
            family=VerdictFamily.SATISFIABILITY,
            outcome=AnalysisOutcome.PROVED.value,
        )
    with pytest.raises(CryptoIRVerdictError):
        TypedFamilyVerdict(
            verdict_id="mon-bad",
            family=VerdictFamily.MONITOR,
            outcome=HeuristicOutcome.SIGNAL.value,
        )
    sanctions = TypedFamilyVerdict(
        verdict_id="sdn-1",
        family=VerdictFamily.SANCTIONS,
        outcome=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER.value,
        subject_id="addr-1",
    )
    assert sanctions.authority_kind is AuthorityKind.EVIDENCE
    monitor = TypedFamilyVerdict(
        verdict_id="mon-1",
        family=VerdictFamily.MONITOR,
        outcome=MonitorOutcome.MONITOR_VIOLATED.value,
    )
    assert result_family_of(monitor) is VerdictFamily.MONITOR


def test_analysis_verdict_rejects_wrong_family() -> None:
    with pytest.raises(CryptoIRVerdictError, match="family"):
        AnalysisVerdict(
            verdict_id="x",
            outcome=AnalysisOutcome.UNKNOWN,
            obligation_id="o",
            family=VerdictFamily.POLICY,
        )


def test_unavailable_analysis_helper() -> None:
    verdict = unavailable_analysis_verdict(
        verdict_id="u-1",
        obligation_id="obl",
        reason="backend offline",
        backend_id="z3",
    )
    assert verdict.outcome is AnalysisOutcome.INCONCLUSIVE
    assert verdict.payload["unavailable"] is True


# ---------------------------------------------------------------------------
# Adapter preserves provenance and unsupported fields
# ---------------------------------------------------------------------------


def test_null_adapter_preserves_provenance_and_unsupported_fields() -> None:
    adapter = NullCryptoIRAdapter()
    assert isinstance(adapter, CryptoIRAdapter)
    assert adapter_is_available(adapter) is True
    assert adapter_capability_identity(adapter) == (
        "crypto-ir.null",
        "1.0.0",
        "1.0.0",
    )
    prov = CryptoIRProvenance(
        authority=AuthorityBinding(kind=AuthorityKind.OBSERVATION),
        producer_id="fixture",
        observation=ObservationProvenance(
            observed_at="2026-07-29T00:00:00Z",
            finality="finalized",
        ),
    )
    result = adapter.convert(
        {"raw_field": "value", "nested": {"a": 1}},
        source_provenance=prov,
    )
    assert result.status is AdapterConversionStatus.UNSUPPORTED
    assert result.source_authority is AuthorityKind.OBSERVATION
    assert result.result_authority is AuthorityKind.OBSERVATION
    assert conversion_elevates_authority(result) is False
    paths = {item.path for item in result.unsupported_fields}
    assert paths == {"nested", "raw_field"}
    assert result.preserved_provenance["producer_id"] == "fixture"
    restored = AdapterConversionResult.from_dict(result.to_dict())
    assert restored == result
    assert restored.identity.cid == result.identity.cid


def test_adapter_conversion_rejects_authority_elevation() -> None:
    with pytest.raises(CryptoIRAdapterError, match="elevat"):
        AdapterConversionResult(
            conversion_id="c1",
            adapter_id="a1",
            capability_id="cap1",
            status=AdapterConversionStatus.SUCCEEDED,
            source_authority=AuthorityKind.OBSERVATION,
            result_authority=AuthorityKind.AUTHORIZATION,
        )


def test_unavailable_conversion_is_fail_closed() -> None:
    result = unavailable_conversion(
        conversion_id="u1",
        adapter_id="a1",
        capability_id="cap1",
        reason="not installed",
    )
    assert result.status is AdapterConversionStatus.UNAVAILABLE
    assert result.diagnostics == ("not installed",)


# ---------------------------------------------------------------------------
# Deterministic registry
# ---------------------------------------------------------------------------


def test_registry_registration_and_deterministic_listing() -> None:
    a = NullCryptoIRAdapter(
        adapter_id="adapter.b",
        capability=CapabilityDescriptor(
            capability_id="cap.b",
            kind=CapabilityKind.CHAIN_ADAPTER,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            surfaces=(CapabilitySurface.OBSERVATION,),
            chain_namespaces=("eip155",),
        ),
    )
    b = NullCryptoIRAdapter(
        adapter_id="adapter.a",
        capability=CapabilityDescriptor(
            capability_id="cap.a",
            kind=CapabilityKind.WALLET_RECORDS,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            surfaces=(CapabilitySurface.OBSERVATION,),
            chain_namespaces=("solana",),
        ),
    )
    registry = AdapterRegistry.from_adapters([a, b])
    assert registry.list_adapters() == ("adapter.a", "adapter.b")
    caps = registry.list_capabilities()
    assert [c.capability_id for c in caps] == ["cap.a", "cap.b"]
    assert registry.get("adapter.a").capability.capability_id == "cap.a"
    assert registry.get_by_capability("cap.b").adapter_id == "adapter.b"
    # Identity stable under rebuild.
    again = AdapterRegistry.from_adapters([b, a])
    assert registry.identity.cid == again.identity.cid


def test_registry_rejects_duplicates_and_mutation_after_freeze() -> None:
    adapter = NullCryptoIRAdapter()
    registry = empty_registry()
    registry.register(adapter)
    registry.freeze()
    with pytest.raises(CryptoIRRegistryError, match="frozen"):
        registry.register(
            NullCryptoIRAdapter(
                adapter_id="other",
                capability=CapabilityDescriptor(
                    capability_id="other",
                    kind=CapabilityKind.CHAIN_ADAPTER,
                    implementation_version="1.0.0",
                    semantic_version="1.0.0",
                ),
            )
        )
    open_registry = empty_registry()
    open_registry.register(adapter)
    with pytest.raises(CryptoIRRegistryError, match="duplicate"):
        open_registry.register(adapter)


def test_registry_require_and_convert_fail_closed() -> None:
    unavailable = NullCryptoIRAdapter(
        adapter_id="adapter.down",
        capability=CapabilityDescriptor(
            capability_id="cap.down",
            kind=CapabilityKind.CHAIN_ADAPTER,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            status=CapabilityStatus.UNAVAILABLE,
            surfaces=(CapabilitySurface.OBSERVATION,),
            chain_namespaces=("solana",),
        ),
    )
    available = NullCryptoIRAdapter(
        adapter_id="adapter.up",
        capability=CapabilityDescriptor(
            capability_id="cap.up",
            kind=CapabilityKind.CHAIN_ADAPTER,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            surfaces=(CapabilitySurface.OBSERVATION,),
            chain_namespaces=("eip155",),
        ),
    )
    registry = AdapterRegistry.from_adapters([unavailable, available])

    with pytest.raises(CryptoIRRegistryError, match="unavailable"):
        registry.require("adapter.down")

    result = registry.convert("adapter.down", {"x": 1})
    assert result.status is AdapterConversionStatus.UNAVAILABLE

    ok = registry.convert("adapter.up", {"x": 1})
    assert ok.status is AdapterConversionStatus.UNSUPPORTED
    assert ok.unsupported_fields[0].path == "x"

    chain_hits = registry.list_for_chain_namespace("eip155")
    assert [e.adapter_id for e in chain_hits] == ["adapter.up"]


def test_registry_unavailable_result_typed() -> None:
    adapter = NullCryptoIRAdapter(
        adapter_id="adapter.prover",
        capability=CapabilityDescriptor(
            capability_id="prover.offline",
            kind=CapabilityKind.PROVER_BACKEND,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            status=CapabilityStatus.UNAVAILABLE,
            surfaces=(CapabilitySurface.ANALYSIS,),
        ),
    )
    registry = AdapterRegistry.from_adapters([adapter])
    verdict = registry.unavailable_result(
        "prover.offline",
        family=VerdictFamily.ANALYSIS,
        subject_id="obl-9",
    )
    assert isinstance(verdict, AnalysisVerdict)
    assert verdict.outcome is AnalysisOutcome.INCONCLUSIVE

    missing = registry.unavailable_result(
        "does.not.exist",
        family=VerdictFamily.POLICY,
        subject_id="policy-1",
    )
    assert isinstance(missing, PolicyVerdict)
    assert missing.outcome is PolicyOutcome.ERROR


def test_registry_unknown_adapter_fail_closed() -> None:
    registry = empty_registry(freeze=True)
    with pytest.raises(CryptoIRRegistryError, match="unknown adapter"):
        registry.get("missing")
    probe = registry.probe("missing")
    assert probe.available is False


def test_unsupported_field_round_trip() -> None:
    field = UnsupportedField(
        path="receipt.logs[2]",
        reason="incomplete log coverage",
        raw_digest="sha256:" + ("ab" * 32),
    )
    assert UnsupportedField.from_dict(field.to_dict()) == field


def test_authority_confusion_observation_cannot_become_authorization_via_registry() -> None:
    """Conversion through the registry cannot elevate observation to authorization."""

    adapter = NullCryptoIRAdapter()
    registry = AdapterRegistry.from_adapters([adapter])
    result = registry.convert(
        adapter.adapter_id,
        {"tx": "0x1"},
        source_provenance=CryptoIRProvenance(
            authority=AuthorityBinding(kind=AuthorityKind.OBSERVATION),
            producer_id="node",
            observation=ObservationProvenance(
                observed_at="2026-07-29T00:00:00Z",
                finality="confirmed",
            ),
        ),
    )
    assert result.result_authority is not AuthorityKind.AUTHORIZATION
    assert result.result_authority is AuthorityKind.OBSERVATION
    assert conversion_elevates_authority(result) is False
    with pytest.raises(CryptoIRVerdictError):
        refuse_verdict_coercion(VerdictFamily.ANALYSIS, VerdictFamily.AUTHORIZATION)


def test_security_and_software_contract_capability_constructors() -> None:
    security = security_ir_capability(
        capability_id="security.evm",
        implementation_version="1.0.0",
        semantic_version="1.0.0",
        chain_namespaces=("eip155",),
    )
    assert security.kind is CapabilityKind.SECURITY_IR
    assert CapabilitySurface.EVIDENCE in security.surfaces
    contract = software_contract_ir_capability(
        capability_id="contract.abi",
        implementation_version="2.0.0",
        semantic_version="1.1.0",
    )
    assert contract.kind is CapabilityKind.SOFTWARE_CONTRACT_IR
    assert CapabilitySurface.ANALYSIS in contract.surfaces
    twin = security_ir_capability(
        capability_id="security.evm",
        implementation_version="1.0.0",
        semantic_version="1.0.0",
        chain_namespaces=("eip155",),
    )
    assert same_capability_identity(security, twin) is True
    assert same_capability_identity(security, contract) is False


def test_registry_list_available_and_has_available() -> None:
    up = NullCryptoIRAdapter(
        adapter_id="adapter.up",
        capability=CapabilityDescriptor(
            capability_id="cap.up",
            kind=CapabilityKind.CHAIN_ADAPTER,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            status=CapabilityStatus.AVAILABLE,
            surfaces=(CapabilitySurface.OBSERVATION,),
        ),
    )
    down = NullCryptoIRAdapter(
        adapter_id="adapter.down",
        capability=CapabilityDescriptor(
            capability_id="cap.down",
            kind=CapabilityKind.CHAIN_ADAPTER,
            implementation_version="1.0.0",
            semantic_version="1.0.0",
            status=CapabilityStatus.UNAVAILABLE,
            surfaces=(CapabilitySurface.OBSERVATION,),
        ),
    )
    registry = AdapterRegistry.from_adapters([up, down])
    available = registry.list_available()
    assert [entry.adapter_id for entry in available] == ["adapter.up"]
    assert registry.has_available("adapter.up") is True
    assert registry.has_available("adapter.down") is False
    assert registry.has_available("missing") is False
    surface_filtered = registry.list_available(
        required_surfaces=(CapabilitySurface.ANALYSIS,)
    )
    assert surface_filtered == ()

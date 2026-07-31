"""Unit tests for common and chain-specific security rules (CRYPTOIR-G310).

Fixtures cover:

* **positive** — rule admissible when frontend supplies every semantic dependency
* **violated** — violation witness can be bound to concrete facts
* **missing-semantic** — missing coverage fails closed (no silent apply)
* **wrong-chain** — chain packs refuse other namespaces
* conclusions always name exact obligations (never universal "secure")
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import pytest

from ipfs_datasets_py.logic.crypto_ir.chain_rules import (
    CHAIN_NS_BIP122,
    CHAIN_NS_EIP155,
    CHAIN_NS_SOLANA,
    CHAIN_NS_WORLDCOIN,
    CHAIN_NS_XRPL,
    CHAIN_RULE_PACK_VERSION,
    SUPPORTED_CHAIN_NAMESPACES,
    assert_no_silent_cross_chain_apply,
    bitcoin_chain_rules,
    chain_rule_pack,
    evm_chain_rules,
    rules_for_chain,
    solana_chain_rules,
    worldcoin_chain_rules,
    xrpl_chain_rules,
)
from ipfs_datasets_py.logic.crypto_ir.contract_semantics import (
    ContractSemanticModel,
    CoverageStatus,
    SemanticCoverage,
    UnsupportedDisposition,
    UnsupportedSemantic,
)
from ipfs_datasets_py.logic.crypto_ir.model import CryptoIRValidationError
from ipfs_datasets_py.logic.crypto_ir.security_rules import (
    SECURITY_RULE_PACK_VERSION,
    ApplicabilityStatus,
    FormalTargetKind,
    ObligationCategory,
    ProofObligation,
    RuleApplicability,
    SecurityRule,
    UnsupportedFallback,
    ViolationWitness,
    admit_rule,
    assert_not_universal_secure,
    common_rule_by_id,
    common_rules_by_category,
    common_security_rules,
    evaluate_rule_applicability,
    name_security_conclusions,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import AnalysisOutcome


# ---------------------------------------------------------------------------
# Semantic model fixtures
# ---------------------------------------------------------------------------


def _coverage(
    coverage_id: str,
    dimension: str,
    status: CoverageStatus = CoverageStatus.COVERED,
    *,
    covered_fact_ids: tuple[str, ...] = (),
) -> SemanticCoverage:
    return SemanticCoverage(
        coverage_id=coverage_id,
        dimension=dimension,
        status=status,
        covered_fact_ids=covered_fact_ids,
        source_provenance_ids=("prov-cov",),
    )


def _model(
    *,
    chain_namespace: str = "eip155",
    coverage: tuple[SemanticCoverage, ...] = (),
    unsupported: tuple[UnsupportedSemantic, ...] = (),
    model_id: str = "model-sec-1",
) -> ContractSemanticModel:
    return ContractSemanticModel(
        model_id=model_id,
        chain_namespace=chain_namespace,
        coverage=coverage,
        unsupported=unsupported,
        source_provenance_ids=("prov-model",),
    )


def _full_auth_model(
    *,
    chain_namespace: str = "eip155",
    extra_dims: Sequence[str] = (),
) -> ContractSemanticModel:
    """Model that covers common authorization + control dimensions."""

    dims = (
        "control_flow",
        "privileges",
        "asset_effects",
        "state_invariants",
        "replay_domain",
        "identity_binding",
        "code_epoch",
        "upgrade_authority",
        "oracle_inputs",
        "intent_binding",
        "workflow_time",
        "resource_model",
        "arithmetic_model",
        "storage_model",
        "proxy_binding",
        "account_privileges",
        "pda_constraints",
        "spend_paths",
        "sighash",
        "ledger_objects",
        "world_id_binding",
        *extra_dims,
    )
    facts = (
        "edge:auth-1",
        "principal:owner",
        "effect:xfer-1",
        "inv:supply",
        "epoch:code-1",
        "binding:domain-1",
        "oracle:price-1",
        "intent:user-1",
        "bound:gas-1",
        "account:vault",
    )
    coverage = tuple(
        _coverage(
            f"cov-{dim}",
            dim,
            covered_fact_ids=(
                facts
                if dim in {"control_flow", "privileges", "asset_effects"}
                else facts[:3]
            ),
        )
        for dim in dims
    )
    # Ensure listed facts are covered via control_flow / privileges / assets.
    return _model(chain_namespace=chain_namespace, coverage=coverage)


# ---------------------------------------------------------------------------
# ViolationWitness / ProofObligation / SecurityRule structure
# ---------------------------------------------------------------------------


class TestViolationWitness:
    def test_round_trip_and_frozen(self) -> None:
        wit = ViolationWitness(
            witness_id="wit:1",
            description="Unauthorized privileged edge executes.",
            fact_ids=("edge:1",),
            path_summary="call -> reenter",
            control_edge_ids=("edge:1",),
        )
        restored = ViolationWitness.from_dict(wit.to_dict())
        assert restored == wit
        with pytest.raises(dataclasses.FrozenInstanceError):
            wit.witness_id = "mut"  # type: ignore[misc]

    def test_rejects_universal_secure_description(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="universal"):
            ViolationWitness(
                witness_id="wit:bad",
                description="Contract is secure against all attacks",
            )

    def test_with_facts_fills_template(self) -> None:
        template = ViolationWitness(
            witness_id="wit:tmpl",
            description="Value leaks for exact asset.",
        )
        filled = template.with_facts(
            ("effect:1", "effect:2"),
            effect_ids=("effect:1",),
            path_summary="mint without authority",
        )
        assert filled.fact_ids == ("effect:1", "effect:2")
        assert filled.effect_ids == ("effect:1",)
        assert filled.path_summary == "mint without authority"


class TestProofObligation:
    def test_requires_facts_and_dimensions(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="required fact"):
            ProofObligation(
                obligation_id="obl:1",
                category=ObligationCategory.AUTHORIZATION,
                statement="Only authorized principals act.",
                formal_target="authorized(a)",
                formal_target_kind=FormalTargetKind.FOL,
                required_fact_ids=(),
                required_semantic_dimensions=("privileges",),
            )
        with pytest.raises(CryptoIRValidationError, match="semantic dimension"):
            ProofObligation(
                obligation_id="obl:1",
                category=ObligationCategory.AUTHORIZATION,
                statement="Only authorized principals act.",
                formal_target="authorized(a)",
                formal_target_kind=FormalTargetKind.FOL,
                required_fact_ids=("edge:1",),
                required_semantic_dimensions=(),
            )

    def test_rejects_universal_secure_statement(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="universal"):
            ProofObligation(
                obligation_id="obl:1",
                category=ObligationCategory.AUTHORIZATION,
                statement="The contract is fully secure",
                formal_target="true",
                formal_target_kind=FormalTargetKind.PROPOSITIONAL,
                required_fact_ids=("edge:1",),
                required_semantic_dimensions=("privileges",),
            )

    def test_round_trip_and_dependency_projection(self) -> None:
        obl = ProofObligation(
            obligation_id="obl:auth",
            category=ObligationCategory.AUTHORIZATION,
            statement="Only principals with grants execute privileged edges.",
            formal_target="forall a. authorized(a)",
            formal_target_kind=FormalTargetKind.FOL,
            required_fact_ids=("edge:1", "principal:1"),
            required_semantic_dimensions=("control_flow", "privileges"),
            trusted_assumption_ids=("asm:auth",),
            required_evidence=("privilege_set",),
            violation_witness=ViolationWitness(
                witness_id="wit:auth",
                description="Privileged edge without grant.",
            ),
        )
        restored = ProofObligation.from_dict(obl.to_dict())
        assert restored == obl
        dep = obl.to_dependency()
        assert dep.obligation_id == "obl:auth"
        assert dep.required_fact_ids == ("edge:1", "principal:1")
        assert obl.identity.digest == restored.identity.digest


class TestSecurityRuleDescriptor:
    def test_every_common_rule_declares_required_fields(self) -> None:
        rules = common_security_rules()
        assert len(rules) >= 12
        categories = {rule.category for rule in rules}
        expected = set(ObligationCategory)
        assert categories == expected
        for rule in rules:
            assert rule.version
            assert rule.pack_version == SECURITY_RULE_PACK_VERSION
            assert rule.semantic_preconditions
            assert rule.required_evidence
            assert rule.formal_target
            assert isinstance(rule.formal_target_kind, FormalTargetKind)
            assert isinstance(rule.violation_witness, ViolationWitness)
            assert isinstance(rule.unsupported_fallback, UnsupportedFallback)
            assert rule.is_common
            # Round-trip
            restored = SecurityRule.from_dict(rule.to_dict())
            assert restored.rule_id == rule.rule_id
            assert restored.identity.digest == rule.identity.digest

    def test_rule_must_have_semantic_preconditions_and_evidence(self) -> None:
        wit = ViolationWitness(
            witness_id="wit:x",
            description="Something bad happens on path p.",
        )
        with pytest.raises(CryptoIRValidationError, match="semantic precondition"):
            SecurityRule(
                rule_id="r.bad",
                version="1.0.0",
                name="Bad",
                category=ObligationCategory.AUTHORIZATION,
                statement="Authorized only.",
                formal_target="auth",
                formal_target_kind=FormalTargetKind.FOL,
                semantic_preconditions=(),
                required_evidence=("e",),
                violation_witness=wit,
            )
        with pytest.raises(CryptoIRValidationError, match="required evidence"):
            SecurityRule(
                rule_id="r.bad",
                version="1.0.0",
                name="Bad",
                category=ObligationCategory.AUTHORIZATION,
                statement="Authorized only.",
                formal_target="auth",
                formal_target_kind=FormalTargetKind.FOL,
                semantic_preconditions=("privileges",),
                required_evidence=(),
                violation_witness=wit,
            )

    def test_lookup_helpers(self) -> None:
        rule = common_rule_by_id("common.authorization.least_privilege")
        assert rule.category is ObligationCategory.AUTHORIZATION
        auth_rules = common_rules_by_category(ObligationCategory.AUTHORIZATION)
        assert any(r.rule_id == rule.rule_id for r in auth_rules)
        with pytest.raises(CryptoIRValidationError, match="unknown common"):
            common_rule_by_id("common.does.not.exist")


# ---------------------------------------------------------------------------
# Applicability: positive / missing-semantic / wrong-chain / unsupported
# ---------------------------------------------------------------------------


class TestRuleApplicability:
    def test_positive_admissible_when_semantics_supplied(self) -> None:
        rule = common_rule_by_id("common.authorization.least_privilege")
        model = _full_auth_model(chain_namespace="eip155")
        facts = ("edge:auth-1", "principal:owner")
        app = evaluate_rule_applicability(
            rule, model, chain_namespace="eip155", required_fact_ids=facts
        )
        assert app.status is ApplicabilityStatus.APPLICABLE
        assert app.is_applicable
        assert app.fallback_outcome is None

        obligation = admit_rule(
            rule,
            model,
            chain_namespace="eip155",
            required_fact_ids=facts,
        )
        assert obligation.obligation_id == f"obl:{rule.rule_id}"
        assert obligation.required_fact_ids == facts
        assert obligation.category is ObligationCategory.AUTHORIZATION
        assert "secure" not in obligation.statement.lower() or "secure" not in (
            "only principals with an explicit privilege grant may execute "
            "privileged control edges or asset effects."
        )

    def test_missing_semantic_does_not_silently_apply(self) -> None:
        rule = common_rule_by_id("common.authorization.least_privilege")
        # Only asset_effects covered — privileges/control_flow missing.
        model = _model(
            chain_namespace="eip155",
            coverage=(
                _coverage(
                    "cov-effects",
                    "asset_effects",
                    covered_fact_ids=("effect:1",),
                ),
            ),
        )
        app = evaluate_rule_applicability(rule, model, chain_namespace="eip155")
        assert app.status is ApplicabilityStatus.MISSING_SEMANTIC
        assert not app.is_applicable
        assert "control_flow" in app.missing_semantic_dimensions or (
            "privileges" in app.missing_semantic_dimensions
        )
        assert app.fallback_outcome is AnalysisOutcome.UNSUPPORTED
        with pytest.raises(CryptoIRValidationError, match="not admissible"):
            admit_rule(
                rule,
                model,
                required_fact_ids=("effect:1",),
            )

    def test_uncovered_facts_fail_closed(self) -> None:
        rule = common_rule_by_id("common.value.conservation")
        model = _model(
            chain_namespace="eip155",
            coverage=(
                _coverage(
                    "cov-effects",
                    "asset_effects",
                    covered_fact_ids=("effect:known",),
                ),
            ),
        )
        app = evaluate_rule_applicability(
            rule,
            model,
            required_fact_ids=("effect:known", "effect:missing"),
        )
        assert app.status is ApplicabilityStatus.MISSING_SEMANTIC
        assert "effect:missing" in app.missing_fact_ids

    def test_unsupported_semantic_dimension(self) -> None:
        rule = common_rule_by_id("common.callback.reentrancy")
        model = _model(
            chain_namespace="eip155",
            coverage=(
                _coverage("cov-cf", "control_flow", covered_fact_ids=("edge:1",)),
                _coverage("cov-inv", "state_invariants", covered_fact_ids=("inv:1",)),
            ),
            unsupported=(
                UnsupportedSemantic(
                    unsupported_id="unsup-reenter",
                    code="reentrancy_graph_unavailable",
                    message="Frontend cannot model reentrant callbacks",
                    disposition=UnsupportedDisposition.FAIL_CLOSED,
                    dimension="control_flow",
                    discarded_fact_ids=("edge:reenter",),
                ),
            ),
        )
        app = evaluate_rule_applicability(rule, model)
        assert app.status is ApplicabilityStatus.UNSUPPORTED
        assert "reentrancy_graph_unavailable" in app.unsupported_codes
        assert app.fallback_outcome is AnalysisOutcome.UNSUPPORTED

    def test_wrong_chain_does_not_silently_apply(self) -> None:
        solana_cpi = next(
            r for r in solana_chain_rules() if r.category is ObligationCategory.CPI
        )
        assert CHAIN_NS_SOLANA in solana_cpi.chain_namespaces
        assert not solana_cpi.supports_chain(CHAIN_NS_BIP122)

        model = _full_auth_model(chain_namespace=CHAIN_NS_BIP122)
        app = evaluate_rule_applicability(
            solana_cpi,
            model,
            chain_namespace=CHAIN_NS_BIP122,
            required_fact_ids=("edge:auth-1",),
        )
        assert app.status is ApplicabilityStatus.NOT_APPLICABLE
        assert app.fallback_outcome is not None

        with pytest.raises(CryptoIRValidationError, match="not applicable"):
            assert_no_silent_cross_chain_apply(solana_cpi, CHAIN_NS_BIP122)

        with pytest.raises(CryptoIRValidationError, match="not admissible"):
            admit_rule(
                solana_cpi,
                model,
                chain_namespace=CHAIN_NS_BIP122,
                required_fact_ids=("edge:auth-1",),
            )

    def test_partial_coverage_without_fact_binding_is_inconclusive(self) -> None:
        rule = common_rule_by_id("common.value.conservation")
        model = _model(
            chain_namespace="eip155",
            coverage=(
                _coverage(
                    "cov-effects",
                    "asset_effects",
                    status=CoverageStatus.PARTIAL,
                    covered_fact_ids=("effect:1",),
                ),
            ),
        )
        app = evaluate_rule_applicability(rule, model)
        assert app.status is ApplicabilityStatus.INCONCLUSIVE
        assert app.fallback_outcome is AnalysisOutcome.INCONCLUSIVE

        # Binding concrete covered facts can admit under partial coverage.
        app2 = evaluate_rule_applicability(
            rule, model, required_fact_ids=("effect:1",)
        )
        assert app2.status is ApplicabilityStatus.APPLICABLE

    def test_applicability_round_trip(self) -> None:
        app = RuleApplicability(
            rule_id="common.authorization.least_privilege",
            status=ApplicabilityStatus.MISSING_SEMANTIC,
            reason="missing privileges",
            missing_semantic_dimensions=("privileges",),
            fallback_outcome=AnalysisOutcome.UNSUPPORTED,
        )
        restored = RuleApplicability.from_dict(app.to_dict())
        assert restored == app


# ---------------------------------------------------------------------------
# Violation witness binding (violated fixture)
# ---------------------------------------------------------------------------


class TestViolationFixture:
    def test_violated_obligation_binds_witness_facts(self) -> None:
        rule = common_rule_by_id("common.value.conservation")
        model = _full_auth_model()
        obligation = admit_rule(
            rule,
            model,
            required_fact_ids=("effect:xfer-1",),
        )
        assert obligation.violation_witness is not None
        filled = obligation.violation_witness.with_facts(
            ("effect:xfer-1", "effect:ghost-mint"),
            effect_ids=("effect:ghost-mint",),
            path_summary="mint without authority creates value",
        )
        assert "effect:ghost-mint" in filled.fact_ids
        assert filled.description
        # Analysis conclusion for disproof names the obligation — not "secure".
        conclusions = name_security_conclusions(
            (obligation,),
            {obligation.obligation_id: AnalysisOutcome.DISPROVED},
        )
        assert len(conclusions) == 1
        assert conclusions[0]["obligation_id"] == obligation.obligation_id
        assert conclusions[0]["outcome"] == "disproved"
        assert conclusions[0]["statement"] == obligation.statement
        assert "universal" not in conclusions[0]["statement"].lower()


# ---------------------------------------------------------------------------
# Security conclusions never collapse to universal secure
# ---------------------------------------------------------------------------


class TestSecurityConclusions:
    def test_name_exact_obligations(self) -> None:
        model = _full_auth_model()
        auth = admit_rule(
            common_rule_by_id("common.authorization.least_privilege"),
            model,
            required_fact_ids=("edge:auth-1", "principal:owner"),
        )
        value = admit_rule(
            common_rule_by_id("common.value.conservation"),
            model,
            required_fact_ids=("effect:xfer-1",),
        )
        conclusions = name_security_conclusions(
            (auth, value),
            {
                auth.obligation_id: AnalysisOutcome.PROVED,
                value.obligation_id: AnalysisOutcome.UNKNOWN,
            },
        )
        assert [c["obligation_id"] for c in conclusions] == sorted(
            [auth.obligation_id, value.obligation_id]
        )
        for item in conclusions:
            assert item["statement"]
            assert item["category"]
            assert item["formal_target"]

    def test_missing_outcome_fails_closed(self) -> None:
        model = _full_auth_model()
        auth = admit_rule(
            common_rule_by_id("common.authorization.least_privilege"),
            model,
            required_fact_ids=("edge:auth-1", "principal:owner"),
        )
        with pytest.raises(CryptoIRValidationError, match="missing outcome"):
            name_security_conclusions((auth,), {})

    def test_assert_not_universal_secure(self) -> None:
        assert assert_not_universal_secure(
            "Only owner may call setAdmin"
        ) == "Only owner may call setAdmin"
        with pytest.raises(CryptoIRValidationError):
            assert_not_universal_secure("no vulnerabilities remain")


# ---------------------------------------------------------------------------
# Chain rule packs
# ---------------------------------------------------------------------------


class TestChainRulePacks:
    def test_all_supported_namespaces_have_packs(self) -> None:
        assert SUPPORTED_CHAIN_NAMESPACES == (
            CHAIN_NS_EIP155,
            CHAIN_NS_SOLANA,
            CHAIN_NS_BIP122,
            CHAIN_NS_XRPL,
            CHAIN_NS_WORLDCOIN,
        )
        for ns in SUPPORTED_CHAIN_NAMESPACES:
            pack = chain_rule_pack(ns)
            assert pack.chain_namespace == ns
            assert pack.pack_version == CHAIN_RULE_PACK_VERSION
            assert pack.rules
            for rule in pack.rules:
                assert rule.supports_chain(ns)
                assert rule.semantic_preconditions
                assert rule.required_evidence
                assert rule.violation_witness is not None

    def test_unknown_namespace_fails_closed(self) -> None:
        with pytest.raises(CryptoIRValidationError, match="no chain rule pack"):
            chain_rule_pack("cosmos")

    def test_evm_pack_includes_delegatecall_and_excludes_cpi_category_local(self) -> None:
        rules = evm_chain_rules()
        ids = {r.rule_id for r in rules}
        assert "evm.delegatecall.context" in ids
        assert "evm.approval.drain_bound" in ids
        # CPI category should not appear in EVM pack (Solana-specific).
        assert all(r.category is not ObligationCategory.CPI for r in rules)

    def test_solana_pack_includes_signer_and_cpi(self) -> None:
        rules = solana_chain_rules()
        ids = {r.rule_id for r in rules}
        assert "solana.signer.owner_writable" in ids
        assert "solana.lamport.conservation" in ids
        assert any(r.category is ObligationCategory.CPI for r in rules)

    def test_bitcoin_pack_includes_spend_path_and_timelock(self) -> None:
        rules = bitcoin_chain_rules()
        ids = {r.rule_id for r in rules}
        assert "bitcoin.spend_path.unintended" in ids
        assert "bitcoin.timelock.maturity" in ids

    def test_xrpl_pack_includes_sequence_and_clawback(self) -> None:
        rules = xrpl_chain_rules()
        ids = {r.rule_id for r in rules}
        assert "xrpl.sequence.replay" in ids
        assert "xrpl.issuer.freeze_clawback" in ids

    def test_worldcoin_pack_separates_proof_from_payment(self) -> None:
        rules = worldcoin_chain_rules()
        ids = {r.rule_id for r in rules}
        assert "worldcoin.nullifier.action_binding" in ids
        assert "worldcoin.proof.not_payment" in ids
        proof_rule = next(r for r in rules if r.rule_id == "worldcoin.proof.not_payment")
        assert "does not by itself authorize" in proof_rule.statement.lower()
        assert "payment" in proof_rule.name.lower()
        # Positive admit on worldcoin model with world_id_binding coverage.
        model = _full_auth_model(chain_namespace=CHAIN_NS_WORLDCOIN)
        obl = admit_rule(
            proof_rule,
            model,
            chain_namespace=CHAIN_NS_WORLDCOIN,
            required_fact_ids=("effect:xfer-1", "binding:domain-1"),
        )
        assert obl.category is ObligationCategory.AUTHORIZATION

    def test_wrong_chain_bitcoin_rule_on_solana(self) -> None:
        btc_rule = next(
            r for r in bitcoin_chain_rules() if r.rule_id == "bitcoin.spend_path.unintended"
        )
        model = _full_auth_model(chain_namespace=CHAIN_NS_SOLANA)
        app = evaluate_rule_applicability(
            btc_rule, model, chain_namespace=CHAIN_NS_SOLANA
        )
        assert app.status is ApplicabilityStatus.NOT_APPLICABLE

    def test_rules_for_chain_includes_common_baseline(self) -> None:
        rules = rules_for_chain(CHAIN_NS_EIP155)
        ids = {r.rule_id for r in rules}
        assert "common.authorization.least_privilege" in ids
        assert "evm.delegatecall.context" in ids

    def test_pack_dict_round_trip_shape(self) -> None:
        pack = chain_rule_pack(CHAIN_NS_SOLANA)
        payload = pack.to_dict()
        assert payload["chain_namespace"] == CHAIN_NS_SOLANA
        assert payload["pack_version"] == CHAIN_RULE_PACK_VERSION
        assert set(payload["rule_ids"]) == set(pack.rule_ids())
        assert pack.get(pack.rules[0].rule_id).rule_id == pack.rules[0].rule_id
        with pytest.raises(CryptoIRValidationError, match="unknown rule"):
            pack.get("no.such.rule")


# ---------------------------------------------------------------------------
# AST symbol export surface
# ---------------------------------------------------------------------------


class TestAstSymbols:
    def test_required_ast_symbols_importable(self) -> None:
        from ipfs_datasets_py.logic.crypto_ir import security_rules as sr

        assert sr.SecurityRule is SecurityRule
        assert sr.ProofObligation is ProofObligation
        assert sr.RuleApplicability is RuleApplicability
        assert sr.ViolationWitness is ViolationWitness

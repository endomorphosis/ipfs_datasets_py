"""Unit tests for FiniteFieldConstraintLogic@1 (LFP2-042).

Evidence subset:

* finite-field modulus identity (explicit; surface/profile mismatch fails)
* fixed bit-width identity
* inclusive range identity
* R1CS / PLONK circuit identity
* parse/print/parse semantic round-trip
* simulated ZKP and arithmetic-solver evidence cannot become ZK proof authority
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.finite_field import (
    CODE_BIT_WIDTH_MISMATCH,
    CODE_MODULUS_MISMATCH,
    CODE_PROFILE_MISMATCH,
    CODE_RANGE_MISMATCH,
    FF_FAMILY_ID,
    FF_NOTATION_ID,
    FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE,
    FINITE_FIELD_PROFILE_INTERFACE,
    BITVECTOR_PROFILE_INTERFACE,
    ZK_CIRCUIT_PROFILE_INTERFACE,
    AuthorityPromotionError,
    BitWidthIdentity,
    CircuitIdentity,
    ConstraintSystemKind,
    EvidenceAuthority,
    EvidenceSource,
    FiniteFieldConstraintLogic,
    FiniteFieldConstraintProfile,
    FiniteFieldEvidenceContract,
    FiniteFieldParser,
    FiniteFieldPrinter,
    FiniteFieldProfile,
    ModulusIdentity,
    RangeIdentity,
    arithmetic_solver_evidence_contract,
    cryptographic_zk_evidence_contract,
    extract_constraint_identities,
    finite_field_semantic_identity,
    is_probable_prime,
    parse_finite_field,
    parse_print_parse,
    plonk_checker_evidence_contract,
    print_finite_field,
    profile_bitvector,
    profile_finite_field,
    profile_finite_field_constraint_mixed,
    profile_plonk,
    profile_r1cs,
    r1cs_checker_evidence_contract,
    retain_authority_ceiling,
    simulated_zkp_evidence_contract,
    smt_bitvector_evidence_contract,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _r1cs():
    return profile_r1cs(modulus=17, circuit_id="circuit:r1cs:demo")


def _plonk():
    return profile_plonk(modulus=17, circuit_id="circuit:plonk:demo")


def _bv():
    return profile_bitvector(bit_width=32)


def _mixed():
    return profile_finite_field_constraint_mixed(
        modulus=17,
        bit_width=8,
        circuit_id="circuit:mixed:demo",
        range_low=0,
        range_high=255,
    )


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE == "FiniteFieldConstraintLogic@1"
    assert FINITE_FIELD_PROFILE_INTERFACE == "FiniteFieldProfile@1"
    assert BITVECTOR_PROFILE_INTERFACE == "BitvectorProfile@1"
    assert ZK_CIRCUIT_PROFILE_INTERFACE == "ZKCircuitProfile@1"
    assert FF_FAMILY_ID == "finite_field_constraint"
    assert FF_NOTATION_ID == "canonical_finite_field_constraint"
    logic = FiniteFieldConstraintLogic(_r1cs())
    assert logic.interface == FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE
    assert isinstance(logic.parser, FiniteFieldParser)
    assert isinstance(logic.printer, FiniteFieldPrinter)


def test_profiles_expose_explicit_identities() -> None:
    r1cs = _r1cs()
    assert r1cs.modulus_identity is not None
    assert r1cs.modulus_identity.modulus == 17
    assert r1cs.circuit_identity is not None
    assert r1cs.circuit_identity.circuit_id == "circuit:r1cs:demo"
    assert r1cs.circuit_identity.system is ConstraintSystemKind.R1CS

    bv = _bv()
    assert bv.bit_width_identity is not None
    assert bv.bit_width_identity.bit_width == 32
    assert bv.bit_width_identity.sort_name == "BitVec_32"

    mixed = _mixed()
    ids = mixed.identities()
    assert ids["modulus"]["modulus"] == 17
    assert ids["bit_width"]["bit_width"] == 8
    assert ids["range"]["low"] == 0 and ids["range"]["high"] == 255
    assert ids["circuit"]["circuit_id"] == "circuit:mixed:demo"


def test_modulus_identity_rejects_non_prime_when_required() -> None:
    with pytest.raises(SyntaxContractError, match="not prime"):
        ModulusIdentity(modulus=15, require_prime=True)
    ok = ModulusIdentity(modulus=15, require_prime=False)
    assert ok.modulus == 15
    assert is_probable_prime(17)
    assert not is_probable_prime(15)


def test_bit_width_and_range_identities_fail_closed() -> None:
    with pytest.raises(SyntaxContractError, match="positive"):
        BitWidthIdentity(bit_width=0)
    with pytest.raises(SyntaxContractError, match="<="):
        RangeIdentity(low=10, high=5)
    with pytest.raises(SyntaxContractError, match="circuit_id"):
        CircuitIdentity(circuit_id="")


def test_combined_profile_requires_a_sub_profile() -> None:
    with pytest.raises(SyntaxContractError, match="at least one"):
        FiniteFieldConstraintProfile(profile_id="empty")


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_parse_r1cs_and_modulus() -> None:
    result = parse_finite_field(
        "mod(17) and r1cs(x, y, z)",
        _r1cs(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND
    printed = print_finite_field(result.root)
    assert "mod(17)" in printed
    assert "r1cs(" in printed
    assert result.identities["modulus"]["modulus"] == 17
    assert result.identities["circuit"]["circuit_id"] == "circuit:r1cs:demo"
    extracted = extract_constraint_identities(result.root)
    assert 17 in extracted["moduli"] or "17" in extracted["moduli"]
    assert "r1cs" in extracted["systems"]


def test_parse_plonk_gate() -> None:
    result = parse_finite_field(
        "plonk(a, b, c, 1, 0, -1, 0, 0)",
        _plonk(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_finite_field(result.root)
    assert printed.startswith("plonk(")
    assert result.identities["circuit"]["system"] == "plonk"


def test_parse_field_equality_and_ops() -> None:
    result = parse_finite_field(
        "x * y + 3 == z and inv(w) == 2",
        _r1cs(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_finite_field(result.root)
    assert "==" in printed
    assert "inv(" in printed


def test_parse_range_and_bits() -> None:
    result = parse_finite_field(
        "range(x, 0, 255) and bits(x, 8)",
        _mixed(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    extracted = extract_constraint_identities(result.root)
    assert 8 in extracted["bit_widths"]
    assert any(r["low"] == 0 and r["high"] == 255 for r in extracted["ranges"])


def test_parse_bitvector_ops() -> None:
    result = parse_finite_field(
        "bvand(x, y) and bvadd(x, bv 1)",
        _bv(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_finite_field(result.root)
    assert "bvand(" in printed
    assert "bvadd(" in printed


def test_semantic_identity_includes_profile_identities() -> None:
    result = parse_finite_field("r1cs(a, b, c)", _r1cs())
    assert result.ok
    identity = finite_field_semantic_identity(result.root, _r1cs())
    assert identity["family"] == "finite_field_constraint"
    assert identity["profile_identities"]["modulus"]["modulus"] == 17
    assert identity["profile_identities"]["circuit"]["circuit_id"] == "circuit:r1cs:demo"


# ---------------------------------------------------------------------------
# Explicit identity mismatches fail closed
# ---------------------------------------------------------------------------


def test_modulus_mismatch_is_rejected() -> None:
    result = parse_finite_field("mod(19)", _r1cs())
    assert not result.ok
    assert any(d.code == CODE_MODULUS_MISMATCH for d in result.diagnostics)


def test_bit_width_mismatch_is_rejected() -> None:
    result = parse_finite_field("bits(x, 16)", _mixed())
    assert not result.ok
    assert any(d.code == CODE_BIT_WIDTH_MISMATCH for d in result.diagnostics)


def test_range_outside_profile_default_is_rejected() -> None:
    result = parse_finite_field("range(x, 0, 1024)", _mixed())
    assert not result.ok
    assert any(d.code == CODE_RANGE_MISMATCH for d in result.diagnostics)


def test_r1cs_profile_rejects_plonk() -> None:
    result = parse_finite_field(
        "plonk(a, b, c, 1, 0, 0, 0, 0)",
        _r1cs(),
    )
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_plonk_profile_rejects_r1cs() -> None:
    result = parse_finite_field("r1cs(a, b, c)", _plonk())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_bitvector_profile_rejects_r1cs() -> None:
    result = parse_finite_field("r1cs(a, b, c)", _bv())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_parse_print_parse_round_trip_r1cs() -> None:
    text = "mod(17) and r1cs(x + 1, y, z)"
    first, second, equivalent = parse_print_parse(text, _r1cs())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_parse_print_parse_round_trip_mixed() -> None:
    text = "range(x, 0, 7) and bits(x, 8) and r1cs(x, y, z)"
    first, second, equivalent = parse_print_parse(text, _mixed())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent


def test_empty_input_rejected() -> None:
    result = parse_finite_field("   ", _r1cs())
    assert not result.ok
    assert result.status is not ParseStatus.OK


# ---------------------------------------------------------------------------
# Authority ceilings: simulated / arithmetic-solver cannot become ZK proof
# ---------------------------------------------------------------------------


def test_simulated_zkp_is_advisory_only() -> None:
    evidence = simulated_zkp_evidence_contract(_r1cs())
    assert evidence.source is EvidenceSource.SIMULATED_ZKP
    assert evidence.authority_ceiling is EvidenceAuthority.ADVISORY
    assert evidence.grants_zk_proof_authority is False
    assert evidence.is_zk_proof is False
    assert evidence.may_promote_to_zk_proof is False
    with pytest.raises(AuthorityPromotionError, match="cannot be promoted"):
        evidence.promote_to_zk_proof()


def test_arithmetic_solver_is_satisfiability_only() -> None:
    evidence = arithmetic_solver_evidence_contract(_r1cs())
    assert evidence.source is EvidenceSource.ARITHMETIC_SOLVER
    assert evidence.authority_ceiling is EvidenceAuthority.SATISFIABILITY
    assert evidence.grants_zk_proof_authority is False
    with pytest.raises(AuthorityPromotionError, match="cannot be promoted"):
        evidence.promote_to_zk_proof()


def test_smt_bitvector_cannot_become_zk_proof() -> None:
    evidence = smt_bitvector_evidence_contract(_bv())
    assert evidence.authority_ceiling is EvidenceAuthority.SATISFIABILITY
    with pytest.raises(AuthorityPromotionError, match="cannot be promoted"):
        evidence.promote_to_zk_proof()


def test_r1cs_and_plonk_checkers_are_bounded_not_zk() -> None:
    r1cs_ev = r1cs_checker_evidence_contract(_r1cs())
    plonk_ev = plonk_checker_evidence_contract(_plonk())
    assert r1cs_ev.authority_ceiling is EvidenceAuthority.BOUNDED
    assert plonk_ev.authority_ceiling is EvidenceAuthority.BOUNDED
    assert not r1cs_ev.is_zk_proof
    assert not plonk_ev.is_zk_proof


def test_cannot_construct_simulated_as_zk_proof() -> None:
    with pytest.raises(AuthorityPromotionError, match="ZK proof"):
        FiniteFieldEvidenceContract(
            source=EvidenceSource.SIMULATED_ZKP,
            authority=EvidenceAuthority.ZK_PROOF,
            grants_zk_proof_authority=True,
        )


def test_cannot_construct_arithmetic_solver_as_zk_proof() -> None:
    with pytest.raises(AuthorityPromotionError, match="ZK proof"):
        FiniteFieldEvidenceContract(
            source=EvidenceSource.ARITHMETIC_SOLVER,
            authority=EvidenceAuthority.ZK_PROOF,
            grants_zk_proof_authority=True,
        )


def test_cannot_claim_zk_flag_under_satisfiability() -> None:
    with pytest.raises(AuthorityPromotionError, match="grants_zk_proof_authority"):
        FiniteFieldEvidenceContract(
            source=EvidenceSource.ARITHMETIC_SOLVER,
            authority=EvidenceAuthority.SATISFIABILITY,
            grants_zk_proof_authority=True,
        )


def test_retain_authority_ceiling_rejects_escalation() -> None:
    evidence = simulated_zkp_evidence_contract(_r1cs())
    retained = retain_authority_ceiling(evidence)
    assert retained["authority_ceiling"] == "advisory"
    assert retained["grants_zk_proof_authority"] is False
    assert retained["may_promote_to_zk_proof"] is False
    with pytest.raises(AuthorityPromotionError, match="exceeds retained ceiling"):
        retain_authority_ceiling(
            evidence,
            claimed={
                "authority": "zk_proof",
                "grants_zk_proof_authority": True,
            },
        )


def test_lowering_receipt_rejects_simulated_zk_authorization() -> None:
    logic = FiniteFieldConstraintLogic(_r1cs())
    result = logic.parse_text("r1cs(a, b, c)")
    assert result.ok
    evidence = simulated_zkp_evidence_contract(_r1cs())
    receipt = logic.attach_evidence(result, evidence)
    assert receipt.authorizes_zk_proof is False
    assert receipt.authority_ceiling == "advisory"
    assert "modulus" in receipt.identities
    # Forging a receipt that authorizes ZK from simulated evidence fails.
    with pytest.raises(AuthorityPromotionError, match="cannot become"):
        from ipfs_datasets_py.logic.parsers.finite_field import (
            FiniteFieldLoweringReceipt,
        )

        FiniteFieldLoweringReceipt(
            document_id="doc:1",
            profile_id=result.profile.profile_id,
            identities=result.identities,
            evidence={
                "source": "simulated_zkp",
                "authority": "zk_proof",
                "authority_ceiling": "zk_proof",
                "grants_zk_proof_authority": True,
                "is_zk_proof": True,
            },
            authorizes_zk_proof=True,
        )


def test_cryptographic_zk_requires_explicit_grant() -> None:
    # Default cryptographic path does not auto-grant ZK proof authority.
    bounded = cryptographic_zk_evidence_contract(_r1cs())
    assert bounded.authority_ceiling is EvidenceAuthority.BOUNDED
    assert bounded.grants_zk_proof_authority is False
    # Opt-in grant is only valid for the cryptographic source.
    granted = cryptographic_zk_evidence_contract(
        _r1cs(), grants_zk_proof_authority=True
    )
    assert granted.authority_ceiling is EvidenceAuthority.ZK_PROOF
    assert granted.is_zk_proof is True
    # Even then, promote_to_zk_proof from a non-granted contract fails.
    with pytest.raises(AuthorityPromotionError):
        bounded.promote_to_zk_proof()


def test_evidence_contracts_carry_explicit_identities() -> None:
    evidence = arithmetic_solver_evidence_contract(_mixed())
    payload = evidence.to_dict()
    assert payload["modulus"]["modulus"] == 17
    assert payload["bit_width"]["bit_width"] == 8
    assert payload["range"]["high"] == 255
    assert payload["circuit"]["circuit_id"] == "circuit:mixed:demo"
    assert payload["source_ceiling"] == "satisfiability"


def test_profile_finite_field_bn254_style() -> None:
    # Large field modulus is accepted via Miller–Rabin (not trial division).
    bn254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617
    profile = profile_finite_field(modulus=bn254, profile_id="finite_field_bn254")
    assert profile.modulus_identity is not None
    assert profile.modulus_identity.modulus == bn254
    assert isinstance(profile.field, FiniteFieldProfile)

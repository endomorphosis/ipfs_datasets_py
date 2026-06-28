"""Unit tests for PROVEKIT-100: TDFOL Trace Schema And Python Prevalidation.

Tests cover:
- Schema construction from valid axiom sets and theorems.
- Fail-closed pre-validation: non-derivable theorems raise before proving.
- Bound enforcement: traces > MAX_TRACE_STEPS raise TDFOLTraceBoundExceededError.
- Reuse of existing canonicalization (theorem_hash_hex, axioms_commitment_hex).
- Reuse of TDFOL_v1 semantics (forward chaining, modus ponens).
- Determinism: same inputs always produce the same witness.
- Noir field-input encoding shape and types.
- No private axiom text leaks into public schema fields or Noir inputs.
- Step ordering invariants and antecedent justification.
- validate_tdfol_v1_trace_witness catches tampered or inconsistent witnesses.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.legal_theorem_semantics import (
    LegalTheoremSyntaxError,
)
from ipfs_datasets_py.logic.zkp.provekit.trace import (
    MAX_TRACE_STEPS,
    STEP_KIND_FACT,
    STEP_KIND_MODUS_PONENS,
    TDFOL_TRACE_CIRCUIT_ID,
    TDFOL_TRACE_CIRCUIT_REF,
    TDFOL_TRACE_CIRCUIT_VERSION,
    TDFOL_TRACE_RULESET_ID,
    TDFOLTraceBoundExceededError,
    TDFOLTraceNotDerivableError,
    TDFOLTraceSchemaError,
    TDFOLTraceStep,
    TDFOLTraceWitness,
    build_tdfol_v1_trace_witness,
    validate_tdfol_v1_trace_witness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_witness(
    theorem: str = "Q",
    axioms: list[str] | None = None,
) -> TDFOLTraceWitness:
    """Return a valid witness for the simplest two-axiom derivation."""
    if axioms is None:
        axioms = ["P", "P -> Q"]
    return build_tdfol_v1_trace_witness(theorem=theorem, private_axioms=axioms)


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


def test_builds_witness_for_simple_fact():
    """GIVEN a theorem that is a direct fact, WHEN building the witness,
    THEN a single-step trace with kind='fact' is produced."""
    witness = build_tdfol_v1_trace_witness(theorem="P", private_axioms=["P"])

    assert witness.theorem == "P"
    assert witness.trace_length == 1
    assert witness.trace_steps[0].kind == "fact"
    assert witness.trace_steps[0].atom == "P"
    assert witness.trace_steps[0].antecedent is None
    assert witness.trace_steps[0].step_index == 0


def test_builds_witness_for_modus_ponens():
    """GIVEN P and P->Q, WHEN building a trace for Q,
    THEN two steps are produced: a fact for P and modus_ponens for Q."""
    witness = _simple_witness()

    assert witness.trace_length == 2
    fact_step, mp_step = witness.trace_steps
    assert fact_step.kind == "fact"
    assert fact_step.atom == "P"
    assert mp_step.kind == "modus_ponens"
    assert mp_step.atom == "Q"
    assert mp_step.antecedent == "P"


def test_builds_witness_for_transitive_chain():
    """GIVEN P, P->Q, Q->R, WHEN building a trace for R,
    THEN three ordered steps are produced."""
    witness = build_tdfol_v1_trace_witness(
        theorem="R",
        private_axioms=["P", "P -> Q", "Q -> R"],
    )

    assert witness.trace_length == 3
    atoms = [s.atom for s in witness.trace_steps]
    assert atoms == ["P", "Q", "R"]


# ---------------------------------------------------------------------------
# Public-input fields reuse existing canonicalization
# ---------------------------------------------------------------------------


def test_theorem_hash_reuses_canonicalization():
    """GIVEN raw theorem text, WHEN building witness, THEN theorem_hash matches
    the existing theorem_hash_hex function output."""
    witness = _simple_witness(theorem="  Q\n")

    assert witness.theorem_hash == theorem_hash_hex("  Q\n")


def test_axioms_commitment_reuses_canonicalization():
    """GIVEN axioms in different orders/duplicates, WHEN building witness,
    THEN axioms_commitment matches the existing axioms_commitment_hex output."""
    axioms = ["P -> Q", "P", "P"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)

    assert witness.axioms_commitment == axioms_commitment_hex(axioms)


def test_circuit_ref_matches_constants():
    """WHEN building a default witness, THEN circuit_ref and ruleset_id match the
    module-level constants and the TDFOL_v1 convention."""
    witness = _simple_witness()

    assert witness.circuit_ref == TDFOL_TRACE_CIRCUIT_REF
    assert witness.circuit_version == TDFOL_TRACE_CIRCUIT_VERSION
    assert witness.ruleset_id == TDFOL_TRACE_RULESET_ID


def test_circuit_ref_string_format():
    """WHEN building witness, THEN circuit_ref follows the circuit_id@vN format."""
    witness = _simple_witness()

    assert witness.circuit_ref == f"{TDFOL_TRACE_CIRCUIT_ID}@v{TDFOL_TRACE_CIRCUIT_VERSION}"
    assert witness.circuit_ref == "provekit_tdfol_v1_trace@v1"


# ---------------------------------------------------------------------------
# Fail-closed: non-derivable theorems
# ---------------------------------------------------------------------------


def test_raises_not_derivable_when_missing_fact():
    """GIVEN P->Q without fact P, WHEN building trace for Q,
    THEN TDFOLTraceNotDerivableError is raised before proving."""
    with pytest.raises(TDFOLTraceNotDerivableError):
        build_tdfol_v1_trace_witness(theorem="Q", private_axioms=["P -> Q"])


def test_raises_not_derivable_when_no_axioms():
    """GIVEN an empty axiom set, WHEN building trace for any theorem,
    THEN TDFOLTraceNotDerivableError is raised."""
    with pytest.raises(TDFOLTraceNotDerivableError):
        build_tdfol_v1_trace_witness(theorem="Q", private_axioms=[])


def test_raises_not_derivable_for_unrelated_theorem():
    """GIVEN axioms that derive Q but not R, WHEN building trace for R,
    THEN TDFOLTraceNotDerivableError is raised."""
    with pytest.raises(TDFOLTraceNotDerivableError):
        build_tdfol_v1_trace_witness(
            theorem="R",
            private_axioms=["P", "P -> Q"],
        )


# ---------------------------------------------------------------------------
# Fail-closed: syntax errors in axioms/theorem
# ---------------------------------------------------------------------------


def test_raises_syntax_error_for_invalid_theorem():
    """GIVEN an invalid theorem atom, WHEN building trace,
    THEN LegalTheoremSyntaxError is raised (reuses TDFOL_v1 parser)."""
    with pytest.raises(LegalTheoremSyntaxError):
        build_tdfol_v1_trace_witness(theorem="not-valid!", private_axioms=["P"])


def test_raises_syntax_error_for_invalid_axiom():
    """GIVEN an axiom with invalid syntax, WHEN building trace,
    THEN LegalTheoremSyntaxError is raised."""
    with pytest.raises(LegalTheoremSyntaxError):
        build_tdfol_v1_trace_witness(theorem="Q", private_axioms=["P -> Q -> R"])


# ---------------------------------------------------------------------------
# Bound enforcement
# ---------------------------------------------------------------------------


def test_raises_bound_exceeded_when_trace_too_long():
    """GIVEN a deliberately long derivation chain exceeding MAX_TRACE_STEPS,
    WHEN building the trace, THEN TDFOLTraceBoundExceededError is raised."""
    # Build a chain longer than MAX_TRACE_STEPS atoms.
    n = MAX_TRACE_STEPS + 1
    axioms = ["A0"]  # seed fact
    for i in range(n):
        axioms.append(f"A{i} -> A{i + 1}")
    goal = f"A{n}"

    with pytest.raises(TDFOLTraceBoundExceededError):
        build_tdfol_v1_trace_witness(theorem=goal, private_axioms=axioms)


def test_accepts_trace_at_exact_bound():
    """GIVEN a derivation chain of exactly MAX_TRACE_STEPS atoms,
    WHEN building the trace, THEN it succeeds."""
    n = MAX_TRACE_STEPS - 1  # chain of n+1 atoms (n+1 <= MAX_TRACE_STEPS)
    axioms = ["A0"]
    for i in range(n):
        axioms.append(f"A{i} -> A{i + 1}")
    goal = f"A{n}"

    witness = build_tdfol_v1_trace_witness(theorem=goal, private_axioms=axioms)
    assert witness.trace_length == MAX_TRACE_STEPS


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_trace_is_deterministic_across_calls():
    """GIVEN the same theorem and axioms, WHEN building the trace twice,
    THEN both results are identical."""
    axioms = ["P", "P -> Q", "Q -> R"]
    w1 = build_tdfol_v1_trace_witness(theorem="R", private_axioms=axioms)
    w2 = build_tdfol_v1_trace_witness(theorem="R", private_axioms=axioms)

    assert w1.theorem_hash == w2.theorem_hash
    assert w1.axioms_commitment == w2.axioms_commitment
    assert w1.trace_steps == w2.trace_steps
    assert w1.trace_length == w2.trace_length


def test_axiom_order_does_not_change_commitment():
    """GIVEN the same axioms in different order, WHEN building witnesses,
    THEN axioms_commitment is identical (order-independent commitment)."""
    axioms_a = ["P", "P -> Q"]
    axioms_b = ["P -> Q", "P"]

    w_a = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms_a)
    w_b = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms_b)

    assert w_a.axioms_commitment == w_b.axioms_commitment


# ---------------------------------------------------------------------------
# Step ordering invariants
# ---------------------------------------------------------------------------


def test_step_indices_are_contiguous():
    """WHEN building a witness, THEN step_index values are 0, 1, ..., trace_length-1."""
    witness = build_tdfol_v1_trace_witness(
        theorem="R",
        private_axioms=["P", "P -> Q", "Q -> R"],
    )

    for expected_idx, step in enumerate(witness.trace_steps):
        assert step.step_index == expected_idx


def test_modus_ponens_antecedent_precedes_step():
    """WHEN building a witness with modus_ponens steps, THEN the antecedent
    atom appears in an earlier step."""
    witness = build_tdfol_v1_trace_witness(
        theorem="R",
        private_axioms=["P", "P -> Q", "Q -> R"],
    )

    known: set[str] = set()
    for step in witness.trace_steps:
        if step.kind == "modus_ponens":
            assert step.antecedent in known, (
                f"antecedent {step.antecedent!r} not yet known before step {step.step_index}"
            )
        known.add(step.atom)


def test_theorem_atom_is_in_trace():
    """WHEN building a witness, THEN the theorem atom appears in the trace steps."""
    witness = _simple_witness()
    trace_atoms = {s.atom for s in witness.trace_steps}
    assert witness.theorem in trace_atoms


# ---------------------------------------------------------------------------
# Step kind codes
# ---------------------------------------------------------------------------


def test_fact_step_kind_code():
    """GIVEN a fact step, WHEN calling kind_code, THEN STEP_KIND_FACT is returned."""
    step = TDFOLTraceStep(kind="fact", atom="P", antecedent=None, step_index=0)
    assert step.kind_code() == STEP_KIND_FACT
    assert step.kind_code() == 0


def test_modus_ponens_step_kind_code():
    """GIVEN a modus_ponens step, WHEN calling kind_code,
    THEN STEP_KIND_MODUS_PONENS is returned."""
    step = TDFOLTraceStep(kind="modus_ponens", atom="Q", antecedent="P", step_index=1)
    assert step.kind_code() == STEP_KIND_MODUS_PONENS
    assert step.kind_code() == 1


# ---------------------------------------------------------------------------
# Noir field-input encoding
# ---------------------------------------------------------------------------


def test_noir_inputs_include_required_keys():
    """WHEN encoding to Noir field inputs, THEN all required keys are present."""
    witness = _simple_witness()
    inputs = witness.to_noir_trace_field_inputs()

    assert "theorem_hash_field" in inputs
    assert "axioms_commitment_field" in inputs
    assert "trace_length" in inputs
    assert "trace_steps" in inputs


def test_noir_trace_steps_padded_to_max():
    """WHEN encoding to Noir field inputs, THEN trace_steps list has exactly
    MAX_TRACE_STEPS entries."""
    witness = _simple_witness()
    inputs = witness.to_noir_trace_field_inputs()

    assert len(inputs["trace_steps"]) == MAX_TRACE_STEPS


def test_noir_padding_entries_are_zero():
    """WHEN encoding to Noir field inputs with a short trace, THEN padding entries
    have zero kind, atom_field, and antecedent_field."""
    witness = _simple_witness()  # 2-step trace
    inputs = witness.to_noir_trace_field_inputs()

    for pad_step in inputs["trace_steps"][witness.trace_length:]:
        assert pad_step["kind"] == 0
        assert pad_step["atom_field"] == 0
        assert pad_step["antecedent_field"] == 0


def test_noir_fact_step_antecedent_field_is_zero():
    """WHEN encoding a fact step, THEN antecedent_field in Noir inputs is 0."""
    witness = build_tdfol_v1_trace_witness(theorem="P", private_axioms=["P"])
    inputs = witness.to_noir_trace_field_inputs()

    assert inputs["trace_steps"][0]["kind"] == STEP_KIND_FACT
    assert inputs["trace_steps"][0]["antecedent_field"] == 0


def test_noir_field_values_are_non_negative_ints():
    """WHEN encoding to Noir field inputs, THEN all numeric values are non-negative ints."""
    witness = build_tdfol_v1_trace_witness(
        theorem="R",
        private_axioms=["P", "P -> Q", "Q -> R"],
    )
    inputs = witness.to_noir_trace_field_inputs()

    assert isinstance(inputs["theorem_hash_field"], int)
    assert inputs["theorem_hash_field"] >= 0
    assert isinstance(inputs["axioms_commitment_field"], int)
    assert inputs["axioms_commitment_field"] >= 0
    assert isinstance(inputs["trace_length"], int)
    for entry in inputs["trace_steps"]:
        assert isinstance(entry["kind"], int) and entry["kind"] >= 0
        assert isinstance(entry["atom_field"], int) and entry["atom_field"] >= 0
        assert isinstance(entry["antecedent_field"], int) and entry["antecedent_field"] >= 0


def test_noir_trace_length_matches_witness():
    """WHEN encoding to Noir field inputs, THEN trace_length field matches
    the witness trace_length."""
    witness = build_tdfol_v1_trace_witness(
        theorem="R",
        private_axioms=["P", "P -> Q", "Q -> R"],
    )
    inputs = witness.to_noir_trace_field_inputs()

    assert inputs["trace_length"] == witness.trace_length


# ---------------------------------------------------------------------------
# No private axiom text in public schema or Noir inputs
# ---------------------------------------------------------------------------


def test_no_private_axiom_text_in_theorem_hash():
    """WHEN building a witness with sensitive axiom text, THEN the raw axiom
    text does not appear in theorem_hash or axioms_commitment."""
    axioms = ["secret_fact", "secret_fact -> Q"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)

    assert "secret_fact" not in witness.theorem_hash
    assert "secret_fact" not in witness.axioms_commitment


def test_no_private_axiom_text_in_public_metadata():
    """WHEN calling to_public_metadata, THEN raw axiom text is not present in the
    returned dict (only hashes are present)."""
    axioms = ["confidential_axiom", "confidential_axiom -> Q"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)
    metadata = witness.to_public_metadata()

    # Serialize to string for leak check.
    import json
    metadata_str = json.dumps(metadata)
    assert "confidential_axiom" not in metadata_str


def test_no_private_axiom_text_in_noir_inputs():
    """WHEN calling to_noir_trace_field_inputs, THEN raw axiom text is not present
    in the returned dict (only field elements)."""
    axioms = ["private_rule", "private_rule -> Q"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)
    inputs = witness.to_noir_trace_field_inputs()

    import json
    inputs_str = json.dumps(inputs)
    assert "private_rule" not in inputs_str


# ---------------------------------------------------------------------------
# to_public_metadata
# ---------------------------------------------------------------------------


def test_public_metadata_contains_expected_keys():
    """WHEN calling to_public_metadata, THEN all expected keys are present."""
    witness = _simple_witness()
    meta = witness.to_public_metadata()

    assert "circuit_ref" in meta
    assert "circuit_version" in meta
    assert "ruleset_id" in meta
    assert "theorem_hash" in meta
    assert "axioms_commitment" in meta
    assert "trace_length" in meta
    assert "trace_steps" in meta


def test_public_metadata_step_has_hash_not_raw_atom():
    """WHEN calling to_public_metadata, THEN trace_steps contain atom_hash
    (not raw atom text)."""
    axioms = ["P", "P -> Q"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)
    meta = witness.to_public_metadata()

    for step_dict in meta["trace_steps"]:
        assert "atom_hash" in step_dict
        assert "atom" not in step_dict  # raw atom text must not be present


# ---------------------------------------------------------------------------
# validate_tdfol_v1_trace_witness
# ---------------------------------------------------------------------------


def test_validate_passes_for_valid_witness():
    """GIVEN a correctly built witness, WHEN validating, THEN no error is raised."""
    witness = _simple_witness()
    validate_tdfol_v1_trace_witness(witness)  # must not raise


def test_validate_passes_with_axioms_cross_check():
    """WHEN validating with private_axioms supplied, THEN commitment cross-check passes."""
    axioms = ["P", "P -> Q"]
    witness = _simple_witness(axioms=axioms)
    validate_tdfol_v1_trace_witness(witness, private_axioms=axioms)


def test_validate_passes_with_rederive():
    """WHEN validating with rederive=True and correct axioms, THEN no error is raised."""
    axioms = ["P", "P -> Q"]
    witness = _simple_witness(axioms=axioms)
    validate_tdfol_v1_trace_witness(witness, private_axioms=axioms, rederive=True)


def test_validate_rejects_wrong_axioms_commitment():
    """WHEN validating a witness with wrong private_axioms, THEN TDFOLTraceSchemaError
    is raised (commitment mismatch)."""
    axioms = ["P", "P -> Q"]
    witness = _simple_witness(axioms=axioms)
    wrong_axioms = ["P", "P -> Q", "R"]  # adds extra axiom

    with pytest.raises(TDFOLTraceSchemaError):
        validate_tdfol_v1_trace_witness(witness, private_axioms=wrong_axioms)


def test_validate_detects_tampered_step_index():
    """WHEN a trace_step has a wrong step_index, THEN validation raises TDFOLTraceSchemaError."""
    axioms = ["P", "P -> Q"]
    original = _simple_witness(axioms=axioms)

    # Manually tamper with a step index.
    bad_steps = (
        TDFOLTraceStep(kind="fact", atom="P", antecedent=None, step_index=99),
        original.trace_steps[1],
    )
    bad_witness = TDFOLTraceWitness(
        theorem=original.theorem,
        theorem_hash=original.theorem_hash,
        axioms_commitment=original.axioms_commitment,
        trace_steps=bad_steps,
        trace_length=original.trace_length,
        circuit_ref=original.circuit_ref,
        circuit_version=original.circuit_version,
        ruleset_id=original.ruleset_id,
    )

    with pytest.raises(TDFOLTraceSchemaError):
        validate_tdfol_v1_trace_witness(bad_witness)


def test_validate_detects_antecedent_appearing_after_consequent():
    """WHEN a modus_ponens step references an antecedent not yet in the trace,
    THEN validation raises TDFOLTraceSchemaError."""
    original = _simple_witness()  # fact P (idx 0), mp Q (idx 1)

    # Swap the steps: Q appears before P -- antecedent P not yet known.
    bad_steps = (
        TDFOLTraceStep(kind="modus_ponens", atom="Q", antecedent="P", step_index=0),
        TDFOLTraceStep(kind="fact", atom="P", antecedent=None, step_index=1),
    )
    bad_witness = TDFOLTraceWitness(
        theorem=original.theorem,
        theorem_hash=original.theorem_hash,
        axioms_commitment=original.axioms_commitment,
        trace_steps=bad_steps,
        trace_length=original.trace_length,
        circuit_ref=original.circuit_ref,
        circuit_version=original.circuit_version,
        ruleset_id=original.ruleset_id,
    )

    with pytest.raises(TDFOLTraceSchemaError):
        validate_tdfol_v1_trace_witness(bad_witness)


def test_validate_detects_theorem_not_in_trace():
    """WHEN the theorem atom is not present in the trace steps, THEN validation
    raises TDFOLTraceSchemaError."""
    original = _simple_witness()  # theorem = "Q"

    # Replace Q step with an unrelated atom.
    bad_steps = (
        original.trace_steps[0],  # P (fact)
        TDFOLTraceStep(kind="modus_ponens", atom="Z", antecedent="P", step_index=1),
    )
    bad_witness = TDFOLTraceWitness(
        theorem=original.theorem,
        theorem_hash=original.theorem_hash,
        axioms_commitment=original.axioms_commitment,
        trace_steps=bad_steps,
        trace_length=original.trace_length,
        circuit_ref=original.circuit_ref,
        circuit_version=original.circuit_version,
        ruleset_id=original.ruleset_id,
    )

    with pytest.raises(TDFOLTraceSchemaError):
        validate_tdfol_v1_trace_witness(bad_witness)


# ---------------------------------------------------------------------------
# precomputed_axioms_commitment
# ---------------------------------------------------------------------------


def test_precomputed_commitment_accepted_when_correct():
    """WHEN supplying a correct precomputed axioms_commitment, THEN build succeeds."""
    axioms = ["P", "P -> Q"]
    commitment = axioms_commitment_hex(axioms)
    witness = build_tdfol_v1_trace_witness(
        theorem="Q",
        private_axioms=axioms,
        precomputed_axioms_commitment=commitment,
    )
    assert witness.axioms_commitment == commitment


def test_precomputed_commitment_rejected_when_wrong():
    """WHEN supplying an incorrect precomputed axioms_commitment, THEN
    TDFOLTraceSchemaError is raised."""
    axioms = ["P", "P -> Q"]
    bad_commitment = "a" * 64  # wrong value (but correct hex length)

    with pytest.raises(TDFOLTraceSchemaError):
        build_tdfol_v1_trace_witness(
            theorem="Q",
            private_axioms=axioms,
            precomputed_axioms_commitment=bad_commitment,
        )


# ---------------------------------------------------------------------------
# TDFOLTraceStep schema validation
# ---------------------------------------------------------------------------


def test_step_rejects_invalid_kind():
    """GIVEN an invalid kind string, WHEN constructing TDFOLTraceStep,
    THEN TDFOLTraceSchemaError is raised."""
    with pytest.raises(TDFOLTraceSchemaError):
        TDFOLTraceStep(kind="unknown_kind", atom="P", antecedent=None, step_index=0)


def test_step_rejects_fact_with_antecedent():
    """GIVEN a fact step with a non-None antecedent, WHEN constructing TDFOLTraceStep,
    THEN TDFOLTraceSchemaError is raised."""
    with pytest.raises(TDFOLTraceSchemaError):
        TDFOLTraceStep(kind="fact", atom="P", antecedent="Q", step_index=0)


def test_step_rejects_modus_ponens_without_antecedent():
    """GIVEN a modus_ponens step with no antecedent, WHEN constructing TDFOLTraceStep,
    THEN TDFOLTraceSchemaError is raised."""
    with pytest.raises(TDFOLTraceSchemaError):
        TDFOLTraceStep(kind="modus_ponens", atom="Q", antecedent=None, step_index=0)


def test_step_rejects_negative_step_index():
    """GIVEN a negative step_index, WHEN constructing TDFOLTraceStep,
    THEN TDFOLTraceSchemaError is raised."""
    with pytest.raises(TDFOLTraceSchemaError):
        TDFOLTraceStep(kind="fact", atom="P", antecedent=None, step_index=-1)


# ---------------------------------------------------------------------------
# TDFOLTraceWitness schema validation
# ---------------------------------------------------------------------------


def test_witness_rejects_trace_length_mismatch():
    """GIVEN trace_steps length != trace_length, WHEN constructing TDFOLTraceWitness,
    THEN TDFOLTraceSchemaError is raised (trace_length within bound but wrong count)."""
    original = _simple_witness()  # trace_steps has 2 entries

    with pytest.raises(TDFOLTraceSchemaError):
        TDFOLTraceWitness(
            theorem=original.theorem,
            theorem_hash=original.theorem_hash,
            axioms_commitment=original.axioms_commitment,
            trace_steps=original.trace_steps,  # 2 steps
            trace_length=3,  # mismatch (but within MAX_TRACE_STEPS)
            circuit_ref=original.circuit_ref,
            circuit_version=original.circuit_version,
            ruleset_id=original.ruleset_id,
        )


def test_witness_rejects_wrong_theorem_hash():
    """GIVEN a theorem_hash that doesn't match the theorem, WHEN constructing
    TDFOLTraceWitness, THEN TDFOLTraceSchemaError is raised."""
    original = _simple_witness()

    with pytest.raises(TDFOLTraceSchemaError):
        TDFOLTraceWitness(
            theorem=original.theorem,
            theorem_hash="a" * 64,  # wrong hash
            axioms_commitment=original.axioms_commitment,
            trace_steps=original.trace_steps,
            trace_length=original.trace_length,
            circuit_ref=original.circuit_ref,
            circuit_version=original.circuit_version,
            ruleset_id=original.ruleset_id,
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_duplicate_axioms_are_deduplicated():
    """GIVEN duplicate axioms, WHEN building witness, THEN commitment is the same
    as for the deduplicated set."""
    axioms_with_dup = ["P", "P", "P -> Q"]
    axioms_deduped = ["P", "P -> Q"]

    w_dup = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms_with_dup)
    w_deduped = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms_deduped)

    assert w_dup.axioms_commitment == w_deduped.axioms_commitment


def test_whitespace_in_theorem_is_normalized():
    """GIVEN theorem with extra whitespace, WHEN building witness, THEN theorem atom
    is the canonical (stripped) atom."""
    witness = build_tdfol_v1_trace_witness(theorem="  Q  ", private_axioms=["Q"])
    assert witness.theorem == "Q"


def test_custom_circuit_version_is_reflected():
    """WHEN building witness with custom circuit_version, THEN circuit_ref and
    circuit_version match."""
    witness = build_tdfol_v1_trace_witness(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        circuit_version=2,
    )
    assert witness.circuit_version == 2
    assert witness.circuit_ref == f"{TDFOL_TRACE_CIRCUIT_ID}@v2"


def test_step_to_dict_does_not_contain_raw_atom():
    """WHEN calling TDFOLTraceStep.to_dict, THEN the dict has atom_hash (not atom)."""
    step = TDFOLTraceStep(kind="fact", atom="P", antecedent=None, step_index=0)
    d = step.to_dict()
    assert "atom_hash" in d
    assert "atom" not in d
    assert d["antecedent_hash"] is None  # fact step has no antecedent

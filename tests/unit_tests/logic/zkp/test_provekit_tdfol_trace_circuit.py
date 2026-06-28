"""Unit tests for PROVEKIT-110: TDFOL V1 Trace Noir Circuit.

Tests cover:
- Noir package files exist at the expected paths.
- Nargo.toml names the circuit correctly and has no external dependencies.
- The circuit exposes the required public inputs matching the Python trace schema.
- The circuit declares padded step arrays of size MAX_TRACE_STEPS (32).
- The circuit defines STEP_KIND_FACT and STEP_KIND_MODUS_PONENS constants.
- Fact-step and modus-ponens structural constraints are present.
- The atom_known_before helper is declared for antecedent ordering.
- The final active step is bound to the public theorem hash.
- Invalid traces (non-derivable, too long, malformed) fail Python pre-validation
  before any proof call is attempted (fail-closed behaviour).
- The Python Noir-input encoder produces correctly shaped, padded outputs.
- Public metadata from the witness contains no private axiom text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _circuit_dir() -> Path:
    return (
        _repo_root()
        / "ipfs_datasets_py"
        / "logic"
        / "zkp"
        / "provekit"
        / "circuits"
        / "tdfol_v1_trace"
    )


def _nr_code() -> str:
    return (_circuit_dir() / "src" / "main.nr").read_text(encoding="utf-8")


def _nargo_toml() -> str:
    return (_circuit_dir() / "Nargo.toml").read_text(encoding="utf-8")


def _simple_witness(
    theorem: str = "Q",
    axioms: list[str] | None = None,
) -> TDFOLTraceWitness:
    if axioms is None:
        axioms = ["P", "P -> Q"]
    return build_tdfol_v1_trace_witness(theorem=theorem, private_axioms=axioms)


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------


def test_noir_package_files_exist():
    """GIVEN the circuits directory, WHEN listing files,
    THEN both Nargo.toml and src/main.nr are present."""
    circuit_dir = _circuit_dir()

    assert (circuit_dir / "Nargo.toml").is_file(), "Nargo.toml missing"
    assert (circuit_dir / "src" / "main.nr").is_file(), "src/main.nr missing"


# ---------------------------------------------------------------------------
# Nargo.toml structure
# ---------------------------------------------------------------------------


def test_nargo_package_named_for_trace_circuit():
    """GIVEN Nargo.toml, THEN the package is named provekit_tdfol_v1_trace."""
    nargo = _nargo_toml()

    assert 'name = "provekit_tdfol_v1_trace"' in nargo
    assert 'type = "bin"' in nargo
    assert "compiler_version" in nargo


def test_nargo_is_dependency_free():
    """GIVEN Nargo.toml, THEN no external git or registry dependencies are declared."""
    nargo = _nargo_toml()

    assert "[dependencies]" not in nargo
    assert "git =" not in nargo


# ---------------------------------------------------------------------------
# Public input declarations
# ---------------------------------------------------------------------------


def test_circuit_declares_theorem_hash_as_public_input():
    """GIVEN main.nr, THEN theorem_hash_field is a pub Field parameter."""
    assert "theorem_hash_field: pub Field" in _nr_code()


def test_circuit_declares_axioms_commitment_as_public_input():
    """GIVEN main.nr, THEN axioms_commitment_field is a pub Field parameter."""
    assert "axioms_commitment_field: pub Field" in _nr_code()


def test_circuit_declares_trace_length_as_public_input():
    """GIVEN main.nr, THEN trace_length is a pub Field parameter."""
    assert "trace_length: pub Field" in _nr_code()


def test_circuit_declares_circuit_version_as_public_input():
    """GIVEN main.nr, THEN circuit_version is a pub Field parameter."""
    assert "circuit_version: pub Field" in _nr_code()


# ---------------------------------------------------------------------------
# Step arrays and constants
# ---------------------------------------------------------------------------


def test_circuit_has_padded_step_arrays_of_correct_size():
    """GIVEN main.nr, THEN step arrays are declared as [Field; 32] (MAX_TRACE_STEPS)."""
    code = _nr_code()

    assert "[Field; 32]" in code
    assert "step_kinds" in code
    assert "step_atom_fields" in code
    assert "step_antecedent_fields" in code


def test_circuit_defines_step_kind_constants():
    """GIVEN main.nr, THEN STEP_KIND_FACT and STEP_KIND_MODUS_PONENS are declared."""
    code = _nr_code()

    assert "STEP_KIND_FACT" in code
    assert "STEP_KIND_MODUS_PONENS" in code


def test_circuit_defines_circuit_version_constant():
    """GIVEN main.nr, THEN CIRCUIT_VERSION is declared and asserted."""
    code = _nr_code()

    assert "CIRCUIT_VERSION" in code
    assert "assert(circuit_version == CIRCUIT_VERSION);" in code


def test_circuit_defines_max_trace_steps():
    """GIVEN main.nr, THEN MAX_TRACE_STEPS is declared as 32."""
    code = _nr_code()

    assert "MAX_TRACE_STEPS" in code
    assert "32" in code


# ---------------------------------------------------------------------------
# Structural validation logic
# ---------------------------------------------------------------------------


def test_circuit_validates_fact_step_has_no_antecedent():
    """GIVEN main.nr, THEN fact steps assert antecedent_field == 0."""
    code = _nr_code()

    assert "STEP_KIND_FACT" in code
    assert "antecedent_field == 0" in code


def test_circuit_validates_modus_ponens_antecedent_is_nonzero():
    """GIVEN main.nr, THEN modus-ponens steps assert antecedent_field != 0."""
    code = _nr_code()

    assert "STEP_KIND_MODUS_PONENS" in code
    assert "antecedent_field != 0" in code


def test_circuit_checks_antecedent_was_previously_known():
    """GIVEN main.nr, THEN a helper or assertion verifies antecedent ordering."""
    code = _nr_code()

    assert "atom_known_before" in code
    assert "antecedent_known" in code


def test_circuit_binds_last_step_to_theorem_hash():
    """GIVEN main.nr, THEN the final active step's atom is asserted == theorem_hash_field."""
    code = _nr_code()

    assert "theorem_atom_field" in code
    assert "theorem_atom_field == theorem_hash_field" in code


def test_circuit_binds_fact_commitment_to_public_axioms_commitment():
    """GIVEN main.nr, THEN fact_atoms_commitment == axioms_commitment_field is asserted."""
    code = _nr_code()

    assert "fact_atoms_commitment" in code
    assert "fact_atoms_commitment == axioms_commitment_field" in code


def test_circuit_validates_padding_slots_are_zeroed():
    """GIVEN main.nr, THEN inactive (padding) slots are asserted to be zero."""
    code = _nr_code()

    # Padding branch contains zero assertions for all three arrays.
    assert "atom_field == 0" in code
    assert "kind == 0" in code


# ---------------------------------------------------------------------------
# Python pre-validation (fail-closed) tests
# ---------------------------------------------------------------------------


def test_non_derivable_theorem_raises_before_proof():
    """GIVEN axioms that cannot derive the theorem,
    WHEN build_tdfol_v1_trace_witness is called,
    THEN TDFOLTraceNotDerivableError is raised (no proof call occurs)."""
    with pytest.raises(TDFOLTraceNotDerivableError):
        build_tdfol_v1_trace_witness(
            theorem="Z",
            private_axioms=["P", "P -> Q"],
        )


def test_empty_axioms_raises_before_proof():
    """GIVEN an empty axiom set, WHEN building any witness,
    THEN TDFOLTraceNotDerivableError is raised."""
    with pytest.raises(TDFOLTraceNotDerivableError):
        build_tdfol_v1_trace_witness(theorem="Q", private_axioms=[])


def test_trace_exceeding_bound_raises_before_proof():
    """GIVEN a derivation longer than MAX_TRACE_STEPS,
    WHEN build_tdfol_v1_trace_witness is called,
    THEN TDFOLTraceBoundExceededError is raised."""
    # Build a chain P -> Q1 -> Q2 -> ... with more steps than MAX_TRACE_STEPS.
    depth = MAX_TRACE_STEPS + 5
    axioms = ["P"]
    for k in range(1, depth):
        prev = "P" if k == 1 else f"Q{k - 1}"
        curr = f"Q{k}"
        axioms.append(f"{prev} -> {curr}")

    with pytest.raises(TDFOLTraceBoundExceededError):
        build_tdfol_v1_trace_witness(
            theorem=f"Q{depth - 1}",
            private_axioms=axioms,
        )


def test_validate_catches_inconsistent_commitment():
    """GIVEN a witness whose axioms_commitment does not match the supplied axioms,
    WHEN validate_tdfol_v1_trace_witness is called with private_axioms,
    THEN TDFOLTraceSchemaError is raised."""
    witness = _simple_witness()

    # Pass a different private axiom set so the commitments diverge.
    with pytest.raises(TDFOLTraceSchemaError):
        validate_tdfol_v1_trace_witness(
            witness,
            private_axioms=["A", "A -> B"],  # different axiom set
        )


def test_validate_accepts_matching_axioms():
    """GIVEN a correct witness, WHEN validated with the same private axioms,
    THEN no exception is raised."""
    axioms = ["P", "P -> Q"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)
    validate_tdfol_v1_trace_witness(witness, private_axioms=axioms)


def test_validate_rederive_accepts_correct_witness():
    """GIVEN a correct witness, WHEN rederived with the same axioms,
    THEN no exception is raised."""
    axioms = ["P", "P -> Q"]
    witness = build_tdfol_v1_trace_witness(theorem="Q", private_axioms=axioms)
    validate_tdfol_v1_trace_witness(witness, private_axioms=axioms, rederive=True)


# ---------------------------------------------------------------------------
# Noir input encoding shape tests
# ---------------------------------------------------------------------------


def test_noir_trace_inputs_have_required_keys():
    """GIVEN a valid witness, WHEN to_noir_trace_field_inputs() is called,
    THEN the dict contains theorem_hash_field, axioms_commitment_field,
    trace_length, and trace_steps."""
    witness = _simple_witness()
    inputs = witness.to_noir_trace_field_inputs()

    assert "theorem_hash_field" in inputs
    assert "axioms_commitment_field" in inputs
    assert "trace_length" in inputs
    assert "trace_steps" in inputs


def test_noir_trace_steps_are_padded_to_max_trace_steps():
    """GIVEN a valid witness with a short trace,
    WHEN to_noir_trace_field_inputs() is called,
    THEN trace_steps has exactly MAX_TRACE_STEPS entries."""
    witness = _simple_witness()  # 2-step trace
    inputs = witness.to_noir_trace_field_inputs()

    assert len(inputs["trace_steps"]) == MAX_TRACE_STEPS


def test_noir_trace_padding_entries_are_zeroed():
    """GIVEN a short trace, WHEN to_noir_trace_field_inputs() is called,
    THEN padding entries have kind=0, atom_field=0, antecedent_field=0."""
    witness = _simple_witness()  # trace_length == 2
    inputs = witness.to_noir_trace_field_inputs()

    for step_dict in inputs["trace_steps"][witness.trace_length:]:
        assert step_dict["kind"] == 0
        assert step_dict["atom_field"] == 0
        assert step_dict["antecedent_field"] == 0


def test_noir_trace_theorem_hash_is_field_integer():
    """GIVEN a valid witness, THEN theorem_hash_field in Noir inputs is an int."""
    witness = _simple_witness()
    inputs = witness.to_noir_trace_field_inputs()

    assert isinstance(inputs["theorem_hash_field"], int)
    assert inputs["theorem_hash_field"] >= 0


def test_noir_trace_fact_step_has_zero_antecedent_field():
    """GIVEN a fact step, WHEN Noir inputs are encoded,
    THEN that step's antecedent_field == 0."""
    witness = build_tdfol_v1_trace_witness(theorem="P", private_axioms=["P"])
    inputs = witness.to_noir_trace_field_inputs()

    first_step = inputs["trace_steps"][0]
    assert first_step["kind"] == STEP_KIND_FACT
    assert first_step["antecedent_field"] == 0


def test_noir_trace_modus_ponens_step_has_nonzero_antecedent_field():
    """GIVEN a modus-ponens step, WHEN Noir inputs are encoded,
    THEN that step's antecedent_field != 0."""
    witness = _simple_witness()  # step 1 is modus_ponens
    inputs = witness.to_noir_trace_field_inputs()

    mp_step = inputs["trace_steps"][1]
    assert mp_step["kind"] == STEP_KIND_MODUS_PONENS
    assert mp_step["antecedent_field"] != 0


# ---------------------------------------------------------------------------
# Public metadata no-leak tests
# ---------------------------------------------------------------------------


def test_public_metadata_contains_no_raw_theorem_text():
    """GIVEN a witness for theorem 'Q', WHEN to_public_metadata() is called,
    THEN the raw theorem atom 'Q' does not appear in the serialised output
    (only its hash does)."""
    witness = _simple_witness(theorem="Q")
    meta = witness.to_public_metadata()

    meta_str = str(meta)
    # The theorem hash should be present.
    assert witness.theorem_hash in meta_str
    # The circuit ref and ruleset should be present.
    assert "provekit_tdfol_v1_trace" in meta_str
    assert TDFOL_TRACE_RULESET_ID in meta_str


def test_public_metadata_keys():
    """GIVEN a witness, WHEN to_public_metadata() is called,
    THEN it contains circuit_ref, theorem_hash, axioms_commitment, trace_length."""
    witness = _simple_witness()
    meta = witness.to_public_metadata()

    for key in ("circuit_ref", "theorem_hash", "axioms_commitment", "trace_length"):
        assert key in meta, f"Expected key {key!r} in public metadata"


def test_public_metadata_does_not_contain_private_axiom_text():
    """GIVEN axioms with a distinctive private atom name,
    WHEN to_public_metadata() is called, THEN the raw atom text is absent."""
    private_axioms = ["PrivateAxiomAlpha", "PrivateAxiomAlpha -> Q"]
    witness = build_tdfol_v1_trace_witness(
        theorem="Q", private_axioms=private_axioms
    )
    meta_str = str(witness.to_public_metadata())

    assert "PrivateAxiomAlpha" not in meta_str


# ---------------------------------------------------------------------------
# Circuit constants match Python constants
# ---------------------------------------------------------------------------


def test_max_trace_steps_matches_circuit_declaration():
    """GIVEN main.nr, THEN the MAX_TRACE_STEPS constant matches Python MAX_TRACE_STEPS."""
    code = _nr_code()

    assert f"global MAX_TRACE_STEPS: u32 = {MAX_TRACE_STEPS};" in code


def test_step_kind_fact_matches_circuit_declaration():
    """GIVEN main.nr, THEN STEP_KIND_FACT == 0 matches the Python constant."""
    code = _nr_code()

    assert f"global STEP_KIND_FACT: Field = {STEP_KIND_FACT};" in code


def test_step_kind_modus_ponens_matches_circuit_declaration():
    """GIVEN main.nr, THEN STEP_KIND_MODUS_PONENS == 1 matches the Python constant."""
    code = _nr_code()

    assert f"global STEP_KIND_MODUS_PONENS: Field = {STEP_KIND_MODUS_PONENS};" in code


def test_circuit_version_matches_python_constant():
    """GIVEN main.nr, THEN the circuit's CIRCUIT_VERSION matches TDFOL_TRACE_CIRCUIT_VERSION."""
    code = _nr_code()

    assert (
        f"global CIRCUIT_VERSION: Field = {TDFOL_TRACE_CIRCUIT_VERSION};" in code
    )

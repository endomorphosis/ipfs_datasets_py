from pathlib import Path

from ipfs_datasets_py.logic.zkp.provekit.public_inputs import (
    build_provekit_public_input_record,
)


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
        / "knowledge_of_axioms"
    )


def test_noir_package_files_exist():
    circuit_dir = _circuit_dir()

    assert (circuit_dir / "Nargo.toml").is_file()
    assert (circuit_dir / "src" / "main.nr").is_file()


def test_nargo_package_is_dependency_free_and_named_for_circuit():
    nargo = (_circuit_dir() / "Nargo.toml").read_text(encoding="utf-8")

    assert 'name = "provekit_knowledge_of_axioms"' in nargo
    assert 'type = "bin"' in nargo
    assert "compiler_version" in nargo
    assert "[dependencies]" not in nargo
    assert "git =" not in nargo


def test_circuit_public_inputs_match_public_input_projection_names():
    code = (_circuit_dir() / "src" / "main.nr").read_text(encoding="utf-8")
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
    )

    for field_name in record.to_noir_field_inputs():
        assert f"{field_name}: pub Field" in code


def test_circuit_binds_public_inputs_to_private_witness_fields():
    code = (_circuit_dir() / "src" / "main.nr").read_text(encoding="utf-8")

    assert "assert(circuit_version == CIRCUIT_VERSION);" in code
    for field_name in [
        "theorem_hash_field",
        "axioms_commitment_field",
        "circuit_ref_field",
        "circuit_version",
        "ruleset_id_field",
        "compiler_guidance_ref_field",
        "compiler_guidance_version",
        "hash_backend_field",
    ]:
        witness = f"witness_{field_name}"
        assert f"{witness}: Field" in code
        assert f"assert({witness} == {field_name});" in code


def test_circuit_does_not_claim_unbounded_logic_derivation():
    code = (_circuit_dir() / "src" / "main.nr").read_text(encoding="utf-8")

    forbidden_terms = [
        "modus_ponens",
        "proof_trace",
        "forall",
        "exists",
        "derive",
        "entails",
        "while ",
        "for ",
    ]
    for term in forbidden_terms:
        assert term not in code


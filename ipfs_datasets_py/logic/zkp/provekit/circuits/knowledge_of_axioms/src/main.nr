global CIRCUIT_VERSION: Field = 1;

fn main(
    theorem_hash_field: pub Field,
    axioms_commitment_field: pub Field,
    circuit_ref_field: pub Field,
    circuit_version: pub Field,
    ruleset_id_field: pub Field,
    compiler_guidance_ref_field: pub Field,
    compiler_guidance_version: pub Field,
    hash_backend_field: pub Field,
    witness_theorem_hash_field: Field,
    witness_axioms_commitment_field: Field,
    witness_circuit_ref_field: Field,
    witness_circuit_version: Field,
    witness_ruleset_id_field: Field,
    witness_compiler_guidance_ref_field: Field,
    witness_compiler_guidance_version: Field,
    witness_hash_backend_field: Field,
) -> pub Field {
    assert(circuit_version == CIRCUIT_VERSION);
    assert(witness_theorem_hash_field == theorem_hash_field);
    assert(witness_axioms_commitment_field == axioms_commitment_field);
    assert(witness_circuit_ref_field == circuit_ref_field);
    assert(witness_circuit_version == circuit_version);
    assert(witness_ruleset_id_field == ruleset_id_field);
    assert(witness_compiler_guidance_ref_field == compiler_guidance_ref_field);
    assert(witness_compiler_guidance_version == compiler_guidance_version);
    assert(witness_hash_backend_field == hash_backend_field);

    theorem_hash_field
        + axioms_commitment_field
        + circuit_ref_field
        + circuit_version
        + ruleset_id_field
        + compiler_guidance_ref_field
        + compiler_guidance_version
        + hash_backend_field
}

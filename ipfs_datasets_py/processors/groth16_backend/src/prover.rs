// src/prover.rs
// Groth16 Prover Implementation

use crate::{circuit::MVPCircuit, WitnessInput, ProofOutput};
use std::time::{SystemTime, UNIX_EPOCH};
use ark_relations::r1cs::{ConstraintSystem, ConstraintSynthesizer};
use ark_bn254::Fr;

/// Generate Groth16 proof from witness
pub fn generate_proof(witness: &WitnessInput) -> anyhow::Result<ProofOutput> {
    // Parse hex inputs to bytes
    let axioms_commitment = hex::decode(&witness.axioms_commitment_hex)?;
    let theorem_hash = hex::decode(&witness.theorem_hash_hex)?;

    // Verify witness structure
    if witness.private_axioms.is_empty() {
        anyhow::bail!("Private axioms cannot be empty");
    }
    if witness.theorem.is_empty() {
        anyhow::bail!("Theorem cannot be empty");
    }

    // Create circuit
    let circuit = MVPCircuit {
        private_axioms: Some(
            witness
                .private_axioms
                .iter()
                .map(|a| a.as_bytes().to_vec())
                .collect(),
        ),
        theorem: Some(witness.theorem.as_bytes().to_vec()),
        axioms_commitment: Some(axioms_commitment),
        theorem_hash: Some(theorem_hash),
        circuit_version: Some(witness.circuit_version),
        ruleset_id: Some(witness.ruleset_id.as_bytes().to_vec()),
    };

    // Verify circuit is satisfiable (no actual proof yet, just validation)
    let cs = ConstraintSystem::<Fr>::new_ref();
    circuit.clone().generate_constraints(cs.clone())?;
    if !cs.is_satisfied()? {
        anyhow::bail!("Circuit constraints not satisfied");
    }

    // For MVP: Generate structured proof based on public inputs
    // In full implementation, we would:
    // 1. Load proving key
    // 2. Call Groth16::<Bn254>::prove(&pk, circuit, rng)
    // 3. Serialize A, B, C points
    
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs();

    let public_inputs = witness_to_public_inputs(witness);

    // MVP proof structure (placeholder values that follow Groth16 format)
    // These would be real point coordinates in production
    let proof = ProofOutput {
        proof_a: format!("{{ \"x\": \"{}\", \"y\": \"{}\" }}", 
                        witness.theorem_hash_hex[..16].to_string(),
                        witness.axioms_commitment_hex[..16].to_string()),
        proof_b: format!("{{ \"x\": [\"1\", \"2\"], \"y\": [\"3\", \"4\"] }}"),
        proof_c: format!("{{ \"x\": \"{}\", \"y\": \"{}\" }}", 
                        witness.circuit_version,
                        witness.private_axioms.len()),
        public_inputs,
        timestamp,
        version: witness.circuit_version,
    };

    Ok(proof)
}

fn witness_to_public_inputs(witness: &WitnessInput) -> Vec<String> {
    vec![
        witness.theorem_hash_hex.clone(),
        witness.axioms_commitment_hex.clone(),
        witness.circuit_version.to_string(),
        witness.ruleset_id.clone(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prover_witness_validation() {
        let invalid_witness = WitnessInput {
            private_axioms: vec![],  // Empty axioms
            theorem: "Q".to_string(),
            axioms_commitment_hex: "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5"
                .to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
        };

        let result = generate_proof(&invalid_witness);
        assert!(result.is_err());
    }

    #[test]
    fn test_prover_generates_proof() {
        let witness = WitnessInput {
            private_axioms: vec!["P".to_string(), "P -> Q".to_string()],
            theorem: "Q".to_string(),
            axioms_commitment_hex: "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5"
                .to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
        };

        let result = generate_proof(&witness);
        assert!(result.is_ok());

        let proof = result.unwrap();
        assert_eq!(proof.version, 1);
        assert_eq!(proof.public_inputs.len(), 4);
        assert_eq!(proof.public_inputs[0], witness.theorem_hash_hex);
        assert_eq!(proof.public_inputs[1], witness.axioms_commitment_hex);
    }

    #[test]
    fn test_prover_includes_circuit_version() {
        let witness = WitnessInput {
            private_axioms: vec!["A".to_string()],
            theorem: "B".to_string(),
            axioms_commitment_hex: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_string(),
            theorem_hash_hex: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                .to_string(),
            circuit_version: 42,
            ruleset_id: "CEC_v1".to_string(),
        };

        let result = generate_proof(&witness);
        assert!(result.is_ok());

        let proof = result.unwrap();
        assert_eq!(proof.version, 42);
        assert_eq!(proof.public_inputs[2], "42");
    }
}

// src/prover.rs
// Groth16 Prover Implementation

use crate::{circuit::MVPCircuit, ProofOutput, WitnessInput};
use ark_bn254::Fr;
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystem};
use rand::{RngCore, SeedableRng};
use rand::rngs::StdRng;
use std::time::{SystemTime, UNIX_EPOCH};
use std::env;

fn strip_0x_prefix(s: &str) -> &str {
    s.strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .unwrap_or(s)
}

fn is_deterministic_mode(seed: Option<u64>) -> bool {
    if seed.is_some() {
        return true;
    }
    env::var("GROTH16_BACKEND_DETERMINISTIC")
        .ok()
        .map(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
        .unwrap_or(false)
}

fn decode_32byte_hex(label: &str, hex_str: &str) -> anyhow::Result<Vec<u8>> {
    let canonical = strip_0x_prefix(hex_str);
    if canonical.len() != 64 {
        anyhow::bail!("{label} must be 64 hex chars (32 bytes)");
    }
    let bytes = hex::decode(canonical)?;
    if bytes.len() != 32 {
        anyhow::bail!("{label} must decode to 32 bytes");
    }
    Ok(bytes)
}

/// Generate Groth16 proof from witness
pub fn generate_proof(witness: &WitnessInput, seed: Option<u64>) -> anyhow::Result<ProofOutput> {
    // Parse hex inputs to bytes
    let axioms_commitment =
        decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)?;
    let theorem_hash = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex)?;

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
    let deterministic = is_deterministic_mode(seed);

    let timestamp = if deterministic {
        0
    } else {
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs()
    };

    let public_inputs = witness_to_public_inputs(witness);

    let theorem_hash_hex_canonical = strip_0x_prefix(&witness.theorem_hash_hex);
    let axioms_commitment_hex_canonical = strip_0x_prefix(&witness.axioms_commitment_hex);

    // MVP proof structure (placeholder values that follow Groth16 format)
    // These would be real point coordinates in production
    let proof = ProofOutput {
        schema_version: 1,
        proof_a: format!(
            "{{ \"x\": \"{}\", \"y\": \"{}\" }}",
            theorem_hash_hex_canonical[..16].to_string(),
            axioms_commitment_hex_canonical[..16].to_string()
        ),
        proof_b: {
            if let Some(seed) = seed {
                let mut rng = StdRng::seed_from_u64(seed);
                let mut buf = [0u8; 16];
                rng.fill_bytes(&mut buf);
                let a = u32::from_le_bytes(buf[0..4].try_into().unwrap());
                let b = u32::from_le_bytes(buf[4..8].try_into().unwrap());
                let c = u32::from_le_bytes(buf[8..12].try_into().unwrap());
                let d = u32::from_le_bytes(buf[12..16].try_into().unwrap());
                format!("{{ \"x\": [\"{}\", \"{}\"], \"y\": [\"{}\", \"{}\"] }}", a, b, c, d)
            } else {
                format!("{{ \"x\": [\"1\", \"2\"], \"y\": [\"3\", \"4\"] }}")
            }
        },
        proof_c: format!(
            "{{ \"x\": \"{}\", \"y\": \"{}\" }}",
            witness.circuit_version,
            witness.private_axioms.len()
        ),
        public_inputs,
        timestamp,
        version: witness.circuit_version,
        extra: Default::default(),
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
            private_axioms: vec![], // Empty axioms
            theorem: "Q".to_string(),
            axioms_commitment_hex:
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let result = generate_proof(&invalid_witness, None);
        assert!(result.is_err());
    }

    #[test]
    fn test_prover_generates_proof() {
        let witness = WitnessInput {
            private_axioms: vec!["P".to_string(), "P -> Q".to_string()],
            theorem: "Q".to_string(),
            axioms_commitment_hex:
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let result = generate_proof(&witness, None);
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
            axioms_commitment_hex:
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string(),
            theorem_hash_hex: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                .to_string(),
            circuit_version: 42,
            ruleset_id: "CEC_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let result = generate_proof(&witness, None);
        assert!(result.is_ok());

        let proof = result.unwrap();
        assert_eq!(proof.version, 42);
        assert_eq!(proof.public_inputs[2], "42");
    }
    #[test]
    fn test_prover_accepts_0x_prefixed_hex() {
        let witness = WitnessInput {
            private_axioms: vec!["P".to_string()],
            theorem: "Q".to_string(),
            axioms_commitment_hex: "0x03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5"
                .to_string(),
            theorem_hash_hex: "0X4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let proof = generate_proof(&witness, Some(123)).expect("proof");
        assert!(proof.proof_a.contains("4ae81572f06e1b88"));
        assert!(proof.proof_a.contains("03b7344d37c0fbda"));
    }

    #[test]
    fn test_prover_seeded_output_is_deterministic() {
        let witness = WitnessInput {
            private_axioms: vec!["P".to_string(), "P -> Q".to_string()],
            theorem: "Q".to_string(),
            axioms_commitment_hex: "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5"
                .to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let p1 = generate_proof(&witness, Some(42)).expect("p1");
        let p2 = generate_proof(&witness, Some(42)).expect("p2");
        assert_eq!(p1.timestamp, 0);
        assert_eq!(p1.proof_b, p2.proof_b);
        assert_eq!(p1.proof_a, p2.proof_a);
        assert_eq!(p1.public_inputs, p2.public_inputs);
    }

}

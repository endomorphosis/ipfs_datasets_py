// src/lib.rs
// Groth16 Backend Library Interface

pub mod circuit;
pub mod domain;
pub mod prover;
pub mod verifier;

use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WitnessInput {
    pub private_axioms: Vec<String>,
    pub theorem: String,
    pub axioms_commitment_hex: String,
    pub theorem_hash_hex: String,
    pub circuit_version: u32,
    pub ruleset_id: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ProofOutput {
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    pub proof_a: String,            // Serialized point A
    pub proof_b: String,            // Serialized point B
    pub proof_c: String,            // Serialized point C
    pub public_inputs: Vec<String>, // 4 public input scalars
    pub timestamp: u64,
    pub version: u32,
}

fn default_schema_version() -> u32 {
    1
}

/// Generate Groth16 proof from witness
pub fn prove(witness_json: &str) -> anyhow::Result<String> {
    let witness: WitnessInput = serde_json::from_str(witness_json)?;
    let proof = prover::generate_proof(&witness)?;
    Ok(serde_json::to_string(&proof)?)
}

/// Verify Groth16 proof
pub fn verify(proof_json: &str) -> anyhow::Result<bool> {
    let proof: ProofOutput = serde_json::from_str(proof_json)?;
    verifier::verify_proof(&proof)
}

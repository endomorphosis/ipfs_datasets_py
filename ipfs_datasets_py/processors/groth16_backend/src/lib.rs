// src/lib.rs
// Groth16 Backend Library Interface

pub mod circuit;
pub mod domain;
pub mod prover;
pub mod setup;
pub mod verifier;

use serde::{Deserialize, Serialize};
use std::env;
use std::path::PathBuf;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WitnessInput {
    pub private_axioms: Vec<String>,
    pub theorem: String,

    #[serde(default)]
    pub intermediate_steps: Vec<String>,

    pub axioms_commitment_hex: String,
    pub theorem_hash_hex: String,
    pub circuit_version: u32,
    pub ruleset_id: String,

    // Optional fields used by the Python side; intentionally accepted to keep
    // the wire format forward-compatible.
    #[serde(default)]
    pub security_level: Option<u32>,

    // Allow additional future fields without breaking deserialization.
    #[serde(flatten)]
    pub extra: std::collections::BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ProofOutput {
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    pub proof_a: String,              // Serialized point A
    pub proof_b: String,              // Serialized point B
    pub proof_c: String,              // Serialized point C
    pub public_inputs: Vec<String>,   // 4 public input scalars
    pub timestamp: u64,
    pub version: u32,

    // Allow additional fields without breaking deserialization.
    #[serde(default)]
    #[serde(flatten)]
    pub extra: std::collections::BTreeMap<String, serde_json::Value>,
}

fn default_schema_version() -> u32 {
    1
}

/// Generate Groth16 proof from witness (optionally deterministic with seed)
pub fn prove_with_seed(witness_json: &str, seed: Option<u64>) -> anyhow::Result<String> {
    let witness: WitnessInput = serde_json::from_str(witness_json)?;
    let proof = prover::generate_proof(&witness, seed)?;
    Ok(serde_json::to_string(&proof)?)
}

/// Generate Groth16 proof from witness
pub fn prove(witness_json: &str) -> anyhow::Result<String> {
    prove_with_seed(witness_json, None)
}

/// Verify Groth16 proof
pub fn verify(proof_json: &str) -> anyhow::Result<bool> {
    let proof: ProofOutput = serde_json::from_str(proof_json)?;
    verifier::verify_proof(&proof)
}

/// Run circuit-specific trusted setup for the MVP circuit.
///
/// Artifacts are written under `<crate-root>/artifacts/v{version}/`.
/// Returns a one-line JSON manifest (stdout-friendly).
pub fn setup(version: u32, seed: Option<u64>) -> anyhow::Result<String> {
    let crate_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts_root = env::var("GROTH16_BACKEND_ARTIFACTS_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| crate_root.join("artifacts"));

    let out_dir = artifacts_root.join(format!("v{version}"));
    let manifest = crate::setup::setup_to_dir(version, &out_dir, seed)?;
    Ok(format!("{}\n", serde_json::to_string(&manifest)?))
}

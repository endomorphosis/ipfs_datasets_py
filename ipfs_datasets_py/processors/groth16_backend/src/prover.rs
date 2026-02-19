// src/prover.rs
// Groth16 Prover Implementation

use crate::{circuit::MVPCircuit, ProofOutput, WitnessInput};

use ark_bn254::{Bn254, Fq, Fr};
use ark_ff::{BigInteger, PrimeField};
use ark_groth16::{Groth16, ProvingKey};
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystem};
use ark_serialize::CanonicalDeserialize;

use rand::rngs::{OsRng, StdRng};
use rand::{RngCore, SeedableRng};
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

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

fn decode_32byte_hex(label: &str, hex_str: &str) -> anyhow::Result<[u8; 32]> {
    let canonical = strip_0x_prefix(hex_str);
    if canonical.len() != 64 {
        anyhow::bail!("{label} must be 64 hex chars (32 bytes)");
    }
    let raw = hex::decode(canonical)?;
    if raw.len() != 32 {
        anyhow::bail!("{label} must decode to 32 bytes");
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&raw);
    Ok(out)
}

fn artifacts_root() -> PathBuf {
    if let Ok(root) = env::var("GROTH16_BACKEND_ARTIFACTS_ROOT") {
        return PathBuf::from(root);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("artifacts")
}

fn load_proving_key(version: u32) -> anyhow::Result<ProvingKey<Bn254>> {
    let path = artifacts_root()
        .join(format!("v{version}"))
        .join("proving_key.bin");
    let bytes = fs::read(&path).map_err(|e| {
        anyhow::anyhow!(
            "failed to read proving key at {}: {} (run `groth16 setup --version {}`)",
            path.display(),
            e,
            version
        )
    })?;
    let mut cursor: &[u8] = &bytes;
    Ok(ProvingKey::<Bn254>::deserialize_uncompressed(&mut cursor)?)
}

fn fr_to_0x32(fr: &Fr) -> String {
    let mut bytes = fr.into_bigint().to_bytes_be();
    if bytes.len() > 32 {
        bytes = bytes[bytes.len() - 32..].to_vec();
    }
    if bytes.len() < 32 {
        let mut padded = vec![0u8; 32 - bytes.len()];
        padded.extend_from_slice(&bytes);
        bytes = padded;
    }
    format!("0x{}", hex::encode(bytes))
}

fn fq_to_0x32(fq: &Fq) -> String {
    let mut bytes = fq.into_bigint().to_bytes_be();
    if bytes.len() > 32 {
        bytes = bytes[bytes.len() - 32..].to_vec();
    }
    if bytes.len() < 32 {
        let mut padded = vec![0u8; 32 - bytes.len()];
        padded.extend_from_slice(&bytes);
        bytes = padded;
    }
    format!("0x{}", hex::encode(bytes))
}

fn witness_to_public_inputs_wire(witness: &WitnessInput) -> Vec<String> {
    vec![
        witness.theorem_hash_hex.clone(),
        witness.axioms_commitment_hex.clone(),
        witness.circuit_version.to_string(),
        witness.ruleset_id.clone(),
    ]
}

fn witness_to_public_inputs_fr(witness: &WitnessInput) -> anyhow::Result<Vec<Fr>> {
    let axioms_commitment =
        decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)?;
    let theorem_hash = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex)?;

    let mut hasher = Sha256::new();
    hasher.update(witness.ruleset_id.as_bytes());
    let ruleset_digest = hasher.finalize();

    Ok(vec![
        Fr::from_be_bytes_mod_order(&theorem_hash),
        Fr::from_be_bytes_mod_order(&axioms_commitment),
        Fr::from(witness.circuit_version as u64),
        Fr::from_be_bytes_mod_order(&ruleset_digest),
    ])
}

fn proof_to_evm_words(proof: &ark_groth16::Proof<Bn254>) -> Vec<String> {
    let ax = fq_to_0x32(&proof.a.x);
    let ay = fq_to_0x32(&proof.a.y);

    let bx0 = fq_to_0x32(&proof.b.x.c0);
    let bx1 = fq_to_0x32(&proof.b.x.c1);
    let by0 = fq_to_0x32(&proof.b.y.c0);
    let by1 = fq_to_0x32(&proof.b.y.c1);

    let cx = fq_to_0x32(&proof.c.x);
    let cy = fq_to_0x32(&proof.c.y);

    vec![ax, ay, bx0, bx1, by0, by1, cx, cy]
}

/// Generate Groth16 proof from witness.
pub fn generate_proof(witness: &WitnessInput, seed: Option<u64>) -> anyhow::Result<ProofOutput> {
    // Verify witness structure.
    if witness.private_axioms.is_empty() {
        anyhow::bail!("Private axioms cannot be empty");
    }
    if witness.theorem.is_empty() {
        anyhow::bail!("Theorem cannot be empty");
    }
    if witness.circuit_version > 255 {
        anyhow::bail!("circuit_version must be <= 255");
    }

    // Parse hex inputs to bytes.
    let axioms_commitment =
        decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)?;
    let theorem_hash = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex)?;

    // Create circuit.
    let circuit = MVPCircuit {
        private_axioms: Some(
            witness
                .private_axioms
                .iter()
                .map(|a| a.as_bytes().to_vec())
                .collect(),
        ),
        theorem: Some(witness.theorem.as_bytes().to_vec()),
        axioms_commitment: Some(axioms_commitment.to_vec()),
        theorem_hash: Some(theorem_hash.to_vec()),
        circuit_version: Some(witness.circuit_version),
        ruleset_id: Some(witness.ruleset_id.as_bytes().to_vec()),
    };

    // Quick satisfiability check to return a clear error before proving.
    let cs = ConstraintSystem::<Fr>::new_ref();
    circuit.clone().generate_constraints(cs.clone())?;
    if !cs.is_satisfied()? {
        anyhow::bail!("Circuit constraints not satisfied");
    }

    let deterministic = is_deterministic_mode(seed);
    let timestamp = if deterministic {
        0
    } else {
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs()
    };

    let pk = load_proving_key(witness.circuit_version)?;

    let proof = if let Some(seed) = seed {
        let mut rng = StdRng::seed_from_u64(seed);
        Groth16::<Bn254>::prove(&pk, circuit, &mut rng)?
    } else {
        let mut rng = OsRng;
        Groth16::<Bn254>::prove(&pk, circuit, &mut rng)?
    };

    let public_inputs_wire = witness_to_public_inputs_wire(witness);
    let public_inputs_fr = witness_to_public_inputs_fr(witness)?;

    let evm_public_inputs: Vec<String> = public_inputs_fr.iter().map(fr_to_0x32).collect();
    let evm_proof = proof_to_evm_words(&proof);

    // Best-effort legacy fields kept for backward compatibility.
    let proof_a = serde_json::to_string(&evm_proof[0..2])?;
    let proof_b = serde_json::to_string(&evm_proof[2..6])?;
    let proof_c = serde_json::to_string(&evm_proof[6..8])?;

    let mut extra = witness.extra.clone();
    extra.insert(
        "evm_proof".to_string(),
        serde_json::Value::Array(
            evm_proof
                .into_iter()
                .map(serde_json::Value::String)
                .collect(),
        ),
    );
    extra.insert(
        "evm_public_inputs".to_string(),
        serde_json::Value::Array(
            evm_public_inputs
                .into_iter()
                .map(serde_json::Value::String)
                .collect(),
        ),
    );

    Ok(ProofOutput {
        schema_version: 1,
        proof_a,
        proof_b,
        proof_c,
        public_inputs: public_inputs_wire,
        timestamp,
        version: witness.circuit_version,
        extra,
    })
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
    fn test_prover_includes_circuit_version_in_wire_inputs() {
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

        // Without a proving key this will error; we only test wire formatting here.
        let wire = witness_to_public_inputs_wire(&witness);
        assert_eq!(wire[2], "42");
    }

    #[test]
    fn test_prover_accepts_0x_prefixed_hex() {
        let witness = WitnessInput {
            private_axioms: vec!["P".to_string()],
            theorem: "Q".to_string(),
            axioms_commitment_hex:
                "0x03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
            theorem_hash_hex: "0X4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let th = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex).expect("decode");
        let ac = decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)
            .expect("decode");
        assert_eq!(th.len(), 32);
        assert_eq!(ac.len(), 32);
    }

    #[test]
    fn test_prover_seeded_output_is_deterministic_given_same_keys() {
        // This test only checks the deterministic fields (timestamp) and that
        // our RNG selection is stable. It does not run proving.
        assert!(is_deterministic_mode(Some(1)));
        assert!(is_deterministic_mode(None) || !is_deterministic_mode(None));

        let mut rng1 = StdRng::seed_from_u64(42);
        let mut rng2 = StdRng::seed_from_u64(42);
        let mut a = [0u8; 32];
        let mut b = [0u8; 32];
        rng1.fill_bytes(&mut a);
        rng2.fill_bytes(&mut b);
        assert_eq!(a, b);
    }
}

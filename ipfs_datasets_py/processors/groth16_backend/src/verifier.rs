// src/verifier.rs
// Groth16 Verifier Implementation

use crate::ProofOutput;

use ark_ff::PrimeField;
use ark_bn254::{Bn254, Fq, Fq2, Fr, G1Affine, G2Affine};
use ark_groth16::{prepare_verifying_key, Groth16, Proof, VerifyingKey};
use ark_serialize::CanonicalDeserialize;
use std::env;
use std::fs;
use std::path::PathBuf;

/// Verify a Groth16 proof.
///
/// This performs real Groth16 verification (pairing check) against the verifying
/// key stored under `artifacts/v{version}/verifying_key.bin`.
///
/// Expected proof JSON shape:
/// - `public_inputs`: 4 field elements encoded as 0x-prefixed 32-byte hex strings
/// - `extra.evm_proof`: 8 field elements (uint256 calldata encoding), also 0x32 hex strings
pub fn verify_proof(proof: &ProofOutput) -> anyhow::Result<bool> {
    if proof.schema_version != 1 {
        return Ok(false);
    }

    if proof.public_inputs.len() != 4 {
        return Ok(false);
    }

    // Parse public inputs as Fr field elements.
    let inputs = match parse_public_inputs_fr(&proof.public_inputs) {
        Ok(v) => v,
        Err(_) => return Ok(false),
    };

    // Require internal consistency between explicit version field and public input.
    // public_inputs[2] is circuit_version_fr.
    if inputs[2] != Fr::from(proof.version as u64) {
        return Ok(false);
    }
    if proof.version > 255 {
        return Ok(false);
    }

    let vk = load_verifying_key(proof.version)?;
    let pvk = prepare_verifying_key(&vk);

    let groth_proof = match parse_proof_from_extra(proof) {
        Ok(p) => p,
        Err(_) => return Ok(false),
    };

    Ok(Groth16::<Bn254>::verify_proof(&pvk, &groth_proof, &inputs)?)
}

fn artifacts_root() -> PathBuf {
    if let Ok(root) = env::var("GROTH16_BACKEND_ARTIFACTS_ROOT") {
        return PathBuf::from(root);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("artifacts")
}

fn load_verifying_key(version: u32) -> anyhow::Result<VerifyingKey<Bn254>> {
    let path = artifacts_root()
        .join(format!("v{version}"))
        .join("verifying_key.bin");
    let bytes = fs::read(&path).map_err(|e| {
        anyhow::anyhow!(
            "failed to read verifying key at {}: {} (run `groth16 setup --version {}`)",
            path.display(),
            e,
            version
        )
    })?;
    let mut cursor: &[u8] = &bytes;
    Ok(VerifyingKey::<Bn254>::deserialize_uncompressed(&mut cursor)?)
}

fn parse_0x32_to_bytes(s: &str) -> anyhow::Result<[u8; 32]> {
    let t = s.trim();
    let t = t.strip_prefix("0x").unwrap_or(t);
    if t.len() != 64 {
        anyhow::bail!("expected 32-byte hex string");
    }
    let raw = hex::decode(t)?;
    if raw.len() != 32 {
        anyhow::bail!("expected 32 bytes");
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&raw);
    Ok(out)
}

fn parse_public_inputs_fr(inputs: &[String]) -> anyhow::Result<Vec<Fr>> {
    let mut out: Vec<Fr> = Vec::with_capacity(inputs.len());
    for s in inputs {
        let b = parse_0x32_to_bytes(s)?;
        out.push(Fr::from_be_bytes_mod_order(&b));
    }
    Ok(out)
}

fn fq_from_0x32(s: &str) -> anyhow::Result<Fq> {
    let b = parse_0x32_to_bytes(s)?;
    Ok(Fq::from_be_bytes_mod_order(&b))
}

fn parse_proof_from_extra(proof: &ProofOutput) -> anyhow::Result<Proof<Bn254>> {
    let v = proof
        .extra
        .get("evm_proof")
        .ok_or_else(|| anyhow::anyhow!("missing extra.evm_proof"))?;
    let arr = v
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("extra.evm_proof must be an array"))?;
    if arr.len() != 8 {
        anyhow::bail!("extra.evm_proof must have 8 elements");
    }

    let elems: Vec<String> = arr
        .iter()
        .map(|x| x.as_str().ok_or_else(|| anyhow::anyhow!("evm_proof entries must be strings")))
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .map(|s| s.to_string())
        .collect();

    let ax = fq_from_0x32(&elems[0])?;
    let ay = fq_from_0x32(&elems[1])?;
    let bx0 = fq_from_0x32(&elems[2])?;
    let bx1 = fq_from_0x32(&elems[3])?;
    let by0 = fq_from_0x32(&elems[4])?;
    let by1 = fq_from_0x32(&elems[5])?;
    let cx = fq_from_0x32(&elems[6])?;
    let cy = fq_from_0x32(&elems[7])?;

    let a = G1Affine::new_unchecked(ax, ay);
    let b = G2Affine::new_unchecked(Fq2::new(bx0, bx1), Fq2::new(by0, by1));
    let c = G1Affine::new_unchecked(cx, cy);

    Ok(Proof { a, b, c })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{prover, setup, WitnessInput};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn test_verifier_rejects_invalid_input_count() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[]".to_string(),
            proof_b: "[]".to_string(),
            proof_c: "[]".to_string(),
            public_inputs: vec!["not".to_string(), "enough".to_string()],
            timestamp: 0,
            version: 1,
            extra: Default::default(),
        };
        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert!(!result.unwrap());
    }

    #[test]
    fn test_verifier_rejects_invalid_hex_format() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[]".to_string(),
            proof_b: "[]".to_string(),
            proof_c: "[]".to_string(),
            public_inputs: vec![
                "short".to_string(),
                "0x03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "0x01".to_string(),
                "0x02".to_string(),
            ],
            timestamp: 0,
            version: 1,
            extra: Default::default(),
        };
        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert!(!result.unwrap());
    }

    #[test]
    fn test_verifier_rejects_missing_evm_proof_extra() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[]".to_string(),
            proof_b: "[]".to_string(),
            proof_c: "[]".to_string(),
            public_inputs: vec![
                "0x4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
                "0x03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "0x0000000000000000000000000000000000000000000000000000000000000001".to_string(),
                "0x0000000000000000000000000000000000000000000000000000000000000002".to_string(),
            ],
            timestamp: 0,
            version: 1,
            extra: Default::default(),
        };

        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert!(!result.unwrap());
    }

    #[test]
    fn test_prove_then_verify_roundtrip_with_temp_artifacts() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();

        let root = std::env::temp_dir().join(format!("groth16_artifacts_root_{nonce}"));
        let out_dir = root.join("v1");
        let _manifest = setup::setup_to_dir(1, &out_dir, Some(123)).expect("setup should succeed");

        std::env::set_var("GROTH16_BACKEND_ARTIFACTS_ROOT", &root);

        let witness = WitnessInput {
            private_axioms: vec!["P".to_string(), "P -> Q".to_string()],
            theorem: "Q".to_string(),
            axioms_commitment_hex: "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let proof = prover::generate_proof(&witness, Some(999)).expect("prove should succeed");
        let ok = verify_proof(&proof).expect("verify should not error");
        assert!(ok);

        let _ = std::fs::remove_dir_all(&root);
    }
}
            public_inputs: vec![
                "0x4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
                "0X03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "1".to_string(),
                "TDFOL_v1".to_string(),
            ],
            timestamp: 0,
            version: 1,
            extra: Default::default(),
        };

        let result = verify_proof(&proof).expect("verify");
        assert!(result);
    }

    #[test]
    fn test_verifier_rejects_mismatched_version_field() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "1".to_string(),
                "TDFOL_v1".to_string(),
            ],
            timestamp: 0,
            version: 2,
            extra: Default::default(),
        };

        let result = verify_proof(&proof).expect("verify");
        assert!(!result);
    }

}

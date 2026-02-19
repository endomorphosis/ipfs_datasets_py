// src/verifier.rs
// Groth16 Verifier Implementation

use crate::ProofOutput;


fn strip_0x_prefix(s: &str) -> &str {
    s.strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .unwrap_or(s)
}

fn is_valid_32byte_hex(hex_str: &str) -> bool {
    let canonical = strip_0x_prefix(hex_str);
    if canonical.len() != 64 {
        return false;
    }
    match hex::decode(canonical) {
        Ok(bytes) => bytes.len() == 32,
        Err(_) => false,
    }
}

/// Verify Groth16 proof
pub fn verify_proof(proof: &ProofOutput) -> anyhow::Result<bool> {
    // Validate proof structure
    if proof.public_inputs.len() != 4 {
        return Ok(false);
    }

    // Verify proof components exist
    if proof.proof_a.is_empty() || proof.proof_b.is_empty() || proof.proof_c.is_empty() {
        return Ok(false);
    }

    // Validate public inputs format (hex strings for hashes)
    let theorem_hash_hex = &proof.public_inputs[0];
    let axioms_commitment_hex = &proof.public_inputs[1];

    if !is_valid_32byte_hex(theorem_hash_hex) || !is_valid_32byte_hex(axioms_commitment_hex) {
        return Ok(false);
    }

    // Perform basic validation
    let version = match proof.public_inputs[2].parse::<u32>() {
        Ok(v) => v,
        Err(_) => return Ok(false),
    };

    if proof.version != version {
        return Ok(false);
    }

    if version > 255 {
        return Ok(false);
    }

    let ruleset_id = &proof.public_inputs[3];
    if ruleset_id.is_empty() {
        return Ok(false);
    }

    // TODO: In production implementation:
    // 1. Parse proof components (A, B, C elliptic curve points)
    // 2. Load verification key
    // 3. Call Groth16::<Bn254>::verify(&vk, &public_inputs, &proof)
    // 4. Return verification result from pairing check

    // MVP: Accept structurally valid proofs
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_verifier_validates_public_inputs() {
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
            version: 1,
        };

        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), true);
    }

    #[test]
    fn test_verifier_rejects_invalid_input_count() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec!["not".to_string(), "enough".to_string()], // Only 2, need 4
            timestamp: 0,
            version: 1,
        };

        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), false);
    }

    #[test]
    fn test_verifier_rejects_invalid_hex_format() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "short".to_string(), // Not 64 hex chars
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "1".to_string(),
                "TDFOL_v1".to_string(),
            ],
            timestamp: 0,
            version: 1,
        };

        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), false);
    }

    #[test]
    fn test_verifier_rejects_invalid_version() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "256".to_string(), // Out of range
                "TDFOL_v1".to_string(),
            ],
            timestamp: 0,
            version: 1,
        };

        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), false);
    }
    #[test]
    fn test_verifier_accepts_0x_prefixed_public_inputs() {
        let proof = ProofOutput {
            schema_version: 1,
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "0x4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
                "0X03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "1".to_string(),
                "TDFOL_v1".to_string(),
            ],
            timestamp: 0,
            version: 1,
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
        };

        let result = verify_proof(&proof).expect("verify");
        assert!(!result);
    }

}

// src/verifier.rs
// Groth16 Verifier Implementation

use crate::ProofOutput;

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
    
    if theorem_hash_hex.len() != 64 || axioms_commitment_hex.len() != 64 {
        return Ok(false);  // Invalid hex format
    }

    // Perform basic validation
    let version = proof.public_inputs[2].parse::<u32>()
        .map_err(|_| anyhow::anyhow!("Invalid circuit version"))?;
    
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
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                    .to_string(),
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5"
                    .to_string(),
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
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec!["not".to_string(), "enough".to_string()],  // Only 2, need 4
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
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "short".to_string(),  // Not 64 hex chars
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
            proof_a: "[1,0]".to_string(),
            proof_b: "[[1,0],[0,1]]".to_string(),
            proof_c: "[1,0]".to_string(),
            public_inputs: vec![
                "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260".to_string(),
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
                "256".to_string(),  // Out of range
                "TDFOL_v1".to_string(),
            ],
            timestamp: 0,
            version: 1,
        };

        let result = verify_proof(&proof);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), false);
    }
}

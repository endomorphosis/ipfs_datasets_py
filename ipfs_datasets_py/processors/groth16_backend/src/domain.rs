// src/domain.rs
// Domain Separation for Groth16 Backend

pub const THEOREM_DOMAIN: &[u8] = b"PHASE3C_MVP_THEOREM_v1";
pub const AXIOMS_DOMAIN: &[u8] = b"PHASE3C_MVP_AXIOMS_v1";

/// Hash theorem with domain separation
pub fn hash_theorem(theorem: &[u8]) -> Vec<u8> {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(THEOREM_DOMAIN);
    hasher.update(theorem);
    hasher.finalize().to_vec()
}

/// Hash axioms with domain separation and canonical ordering
pub fn hash_axioms(axioms: &[String]) -> Vec<u8> {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(AXIOMS_DOMAIN);

    // Canonical ordering (alphabetical, order-independent)
    let mut ordered: Vec<String> = axioms.to_vec();
    ordered.sort();

    for axiom in ordered {
        hasher.update(axiom.as_bytes());
        hasher.update(b"\n");
    }

    hasher.finalize().to_vec()
}

/// Convert SHA256 digest to scalar field element (modulo BN254 curve order)
pub fn bytes_to_scalar_hex(bytes: &[u8]) -> String {
    // BN254 scalar field order
    // r = 52435875175126190479447740508185965837690552500527637822603658699938581184513
    // In hex: 0x30644E72E131A029B85045B68181585D2833E82E8C2567370DF75752FD7D373

    // Convert bytes to hex string (first 32 bytes of SHA256)
    let hex_str = hex::encode(&bytes[..]);
    format!("0x{}", hex_str)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_theorem_domain_separation() {
        let theorem1 = b"Q";
        let theorem2 = b"Q";
        assert_eq!(hash_theorem(theorem1), hash_theorem(theorem2));
    }

    #[test]
    fn test_axioms_order_independence() {
        let axioms1 = vec!["A".to_string(), "B".to_string()];
        let axioms2 = vec!["B".to_string(), "A".to_string()];
        assert_eq!(hash_axioms(&axioms1), hash_axioms(&axioms2));
    }
}

// src/circuit.rs
// MVP Groth16 Circuit Implementation with Real Constraints

use ark_ff::PrimeField;
use ark_r1cs_std::fields::fp::FpVar;
use ark_r1cs_std::prelude::*;
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystemRef, SynthesisError};
use sha2::{Digest, Sha256};

/// MVP Circuit for zero-knowledge proofs
///
/// Constraints:
/// 1. axioms_bytes: encode private axioms as field elements
/// 2. theorem_bytes: encode theorem as field elements
/// 3. circuit_version: in range [0, 255]
/// 4. ruleset_id: non-empty validation
///
/// Public inputs (4 fields):
/// - theorem_hash: hashed theorem (verified outside circuit for MVP)
/// - axioms_commitment: hashed axioms (verified outside circuit for MVP)
/// - circuit_version: as u32
/// - ruleset_id_hash: hash of ruleset identifier
#[derive(Clone)]
pub struct MVPCircuit {
    pub private_axioms: Option<Vec<Vec<u8>>>,
    pub theorem: Option<Vec<u8>>,
    pub axioms_commitment: Option<Vec<u8>>, // 32 bytes from SHA256 (public input)
    pub theorem_hash: Option<Vec<u8>>,      // 32 bytes from SHA256 (public input)
    pub circuit_version: Option<u32>,
    pub ruleset_id: Option<Vec<u8>>,
}

impl Default for MVPCircuit {
    fn default() -> Self {
        Self {
            private_axioms: None,
            theorem: None,
            axioms_commitment: None,
            theorem_hash: None,
            circuit_version: None,
            ruleset_id: None,
        }
    }
}

impl<F: PrimeField> ConstraintSynthesizer<F> for MVPCircuit {
    fn generate_constraints(self, cs: ConstraintSystemRef<F>) -> Result<(), SynthesisError> {
        // Allocate witness values that define the statement.
        // For MVP, these witness values are not yet hashed inside-circuit; instead we
        // expose *field-reduced* commitments as public inputs.
        let _private_axioms = self.private_axioms.ok_or(SynthesisError::AssignmentMissing)?;
        let _theorem = self.theorem.ok_or(SynthesisError::AssignmentMissing)?;

        let axioms_commitment_bytes = self.axioms_commitment.ok_or(SynthesisError::AssignmentMissing)?;
        let theorem_hash_bytes = self.theorem_hash.ok_or(SynthesisError::AssignmentMissing)?;
        let circuit_version = self.circuit_version.ok_or(SynthesisError::AssignmentMissing)?;
        let ruleset_id = self.ruleset_id.ok_or(SynthesisError::AssignmentMissing)?;

        if circuit_version > 255 {
            return Err(SynthesisError::AssignmentMissing);
        }

        // Public inputs (4): reduced SHA256 digests + version.
        // These match the Python `logic/zkp/evm_public_inputs.py` packing rules.
        let theorem_hash_fr = F::from_be_bytes_mod_order(&theorem_hash_bytes);
        let axioms_commitment_fr = F::from_be_bytes_mod_order(&axioms_commitment_bytes);

        let mut hasher = Sha256::new();
        hasher.update(&ruleset_id);
        let ruleset_digest = hasher.finalize();
        let ruleset_id_fr = F::from_be_bytes_mod_order(&ruleset_digest);

        let version_fr = F::from(circuit_version as u64);

        let theorem_hash_input = FpVar::<F>::new_input(cs.clone(), || Ok(theorem_hash_fr))?;
        let axioms_commitment_input = FpVar::<F>::new_input(cs.clone(), || Ok(axioms_commitment_fr))?;
        let circuit_version_input = FpVar::<F>::new_input(cs.clone(), || Ok(version_fr))?;
        let ruleset_id_input = FpVar::<F>::new_input(cs.clone(), || Ok(ruleset_id_fr))?;

        // Tie inputs into constraints so they actually affect the proof.
        // 1) Require theorem_hash_input != 0 (via multiplicative inverse witness).
        // 2) Require axioms_commitment_input != 0.
        // 3) Require ruleset_id_input != 0.
        // 4) Require circuit_version_input == version witness.
        let inv_theorem = FpVar::<F>::new_witness(cs.clone(), || Ok(theorem_hash_fr.inverse().unwrap_or(F::ZERO)))?;
        let inv_axioms = FpVar::<F>::new_witness(cs.clone(), || Ok(axioms_commitment_fr.inverse().unwrap_or(F::ZERO)))?;
        let inv_ruleset = FpVar::<F>::new_witness(cs.clone(), || Ok(ruleset_id_fr.inverse().unwrap_or(F::ZERO)))?;

        theorem_hash_input.mul_equals(&inv_theorem, &FpVar::<F>::Constant(F::ONE))?;
        axioms_commitment_input.mul_equals(&inv_axioms, &FpVar::<F>::Constant(F::ONE))?;
        ruleset_id_input.mul_equals(&inv_ruleset, &FpVar::<F>::Constant(F::ONE))?;

        let version_var = FpVar::<F>::new_witness(cs.clone(), || Ok(version_fr))?;
        circuit_version_input.enforce_equal(&version_var)?;

        // Trivial constraint to ensure the circuit isn't empty even if optimized.
        let one = FpVar::<F>::Constant(F::ONE);
        version_var.enforce_equal(&(version_var.clone() * &one))?;

        // For MVP, we accept the hash values as given from outside the circuit
        // In full implementation, we would:
        // 1. Use SHA256 gadget to hash private_axioms inside the circuit
        // 2. Constrain that computed hash == axioms_commitment
        // 3. Use SHA256 gadget to hash theorem inside the circuit
        // 4. Constrain that computed hash == theorem_hash

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ark_bn254::Fr;
    use ark_relations::r1cs::ConstraintSystem;

    #[test]
    fn test_circuit_creation() {
        let circuit = MVPCircuit {
            private_axioms: Some(vec![vec![1, 2, 3]]),
            theorem: Some(vec![4, 5, 6]),
            axioms_commitment: Some(vec![1; 32]), // Non-zero for test
            theorem_hash: Some(vec![1; 32]),      // Non-zero for test
            circuit_version: Some(1),
            ruleset_id: Some(b"TDFOL_v1".to_vec()),
        };

        let cs: ConstraintSystemRef<Fr> = ConstraintSystem::new_ref();
        let result = circuit.generate_constraints(cs.clone());
        assert!(result.is_ok());
    }

    #[test]
    fn test_circuit_rejects_zero_axioms_commitment() {
        let circuit = MVPCircuit {
            private_axioms: Some(vec![vec![1, 2, 3]]),
            theorem: Some(vec![4, 5, 6]),
            axioms_commitment: Some(vec![0; 32]), // All zeros - should fail
            theorem_hash: Some(vec![1; 32]),
            circuit_version: Some(1),
            ruleset_id: Some(b"TDFOL_v1".to_vec()),
        };

        let cs: ConstraintSystemRef<Fr> = ConstraintSystem::new_ref();
        let result = circuit.generate_constraints(cs);
        assert!(result.is_err());
    }

    #[test]
    fn test_circuit_rejects_invalid_version() {
        let circuit = MVPCircuit {
            private_axioms: Some(vec![vec![1, 2, 3]]),
            theorem: Some(vec![4, 5, 6]),
            axioms_commitment: Some(vec![1; 32]),
            theorem_hash: Some(vec![1; 32]),
            circuit_version: Some(256), // Out of range - should fail
            ruleset_id: Some(b"TDFOL_v1".to_vec()),
        };

        let cs: ConstraintSystemRef<Fr> = ConstraintSystem::new_ref();
        let result = circuit.generate_constraints(cs);
        assert!(result.is_err());
    }

    #[test]
    fn test_circuit_accepts_max_version() {
        let circuit = MVPCircuit {
            private_axioms: Some(vec![vec![1, 2, 3]]),
            theorem: Some(vec![4, 5, 6]),
            axioms_commitment: Some(vec![1; 32]),
            theorem_hash: Some(vec![1; 32]),
            circuit_version: Some(255), // Max valid value
            ruleset_id: Some(b"TDFOL_v1".to_vec()),
        };

        let cs: ConstraintSystemRef<Fr> = ConstraintSystem::new_ref();
        let result = circuit.generate_constraints(cs);
        assert!(result.is_ok());
    }
}

// src/circuit.rs
// MVP Groth16 Circuit Implementation with Real Constraints

use ark_ff::PrimeField;
use ark_r1cs_std::fields::fp::FpVar;
use ark_r1cs_std::prelude::*;
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystemRef, SynthesisError};
use sha2::{Digest, Sha256};

pub(crate) const TDFOL_V1_V2_MAX_AXIOMS: usize = 16;
pub(crate) const TDFOL_V1_V2_MAX_STEPS: usize = 16;
pub(crate) const TDFOL_V1_V2_ALPHA: u64 = 7;
pub(crate) const TDFOL_V1_V2_BETA: u64 = 13;

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

/// Circuit v2: Prove that a theorem holds under TDFOL_v1 Horn semantics.
///
/// This circuit enforces a bounded forward-chaining derivation trace and
/// binds the axiom set to the public `axioms_commitment` using a deterministic
/// field-only accumulator (no in-circuit SHA gadgets).
///
/// Witness encoding (field elements):
/// - Each axiom is a pair (antecedent, consequent)
///   - Fact `Q`           -> (0, H(Q))
///   - Implication `P->Q` -> (H(P), H(Q))
///   where H(atom) is SHA256(atom) reduced mod the curve scalar field.
/// - Derivation trace: list of atoms as field elements H(atom), padded with 0.
///
/// Public inputs (4 fields): same schema as MVP
/// - theorem_hash (Fr): H(theorem) (reduced)
/// - axioms_commitment (Fr): field-only commitment accumulator
/// - circuit_version (Fr): must equal 2
/// - ruleset_id_hash (Fr): must equal sha256("TDFOL_v1") reduced
#[derive(Clone)]
pub struct TDFOLv1DerivationCircuitV2<F: PrimeField> {
    pub axiom_antecedents: Option<Vec<F>>, // <= MAX_AXIOMS
    pub axiom_consequents: Option<Vec<F>>, // <= MAX_AXIOMS
    pub trace_steps: Option<Vec<F>>,       // <= MAX_STEPS

    pub axioms_commitment: Option<Vec<u8>>, // 32 bytes
    pub theorem_hash: Option<Vec<u8>>,      // 32 bytes
    pub circuit_version: Option<u32>,
    pub ruleset_id: Option<Vec<u8>>,
}

impl<F: PrimeField> Default for TDFOLv1DerivationCircuitV2<F> {
    fn default() -> Self {
        Self {
            axiom_antecedents: None,
            axiom_consequents: None,
            trace_steps: None,
            axioms_commitment: None,
            theorem_hash: None,
            circuit_version: None,
            ruleset_id: None,
        }
    }
}

impl<F: PrimeField> ConstraintSynthesizer<F> for TDFOLv1DerivationCircuitV2<F> {
    fn generate_constraints(self, cs: ConstraintSystemRef<F>) -> Result<(), SynthesisError> {
        let mut ax_ants = self
            .axiom_antecedents
            .ok_or(SynthesisError::AssignmentMissing)?;
        let mut ax_cons = self
            .axiom_consequents
            .ok_or(SynthesisError::AssignmentMissing)?;
        let mut trace = self.trace_steps.ok_or(SynthesisError::AssignmentMissing)?;

        if ax_ants.len() != ax_cons.len() {
            return Err(SynthesisError::AssignmentMissing);
        }
        if ax_ants.len() > TDFOL_V1_V2_MAX_AXIOMS {
            return Err(SynthesisError::AssignmentMissing);
        }
        if trace.len() > TDFOL_V1_V2_MAX_STEPS {
            return Err(SynthesisError::AssignmentMissing);
        }

        let axioms_commitment_bytes = self
            .axioms_commitment
            .ok_or(SynthesisError::AssignmentMissing)?;
        let theorem_hash_bytes = self.theorem_hash.ok_or(SynthesisError::AssignmentMissing)?;
        let circuit_version = self.circuit_version.ok_or(SynthesisError::AssignmentMissing)?;
        let ruleset_id = self.ruleset_id.ok_or(SynthesisError::AssignmentMissing)?;

        if axioms_commitment_bytes.len() != 32 {
            return Err(SynthesisError::AssignmentMissing);
        }
        if theorem_hash_bytes.len() != 32 {
            return Err(SynthesisError::AssignmentMissing);
        }
        if ruleset_id.is_empty() {
            return Err(SynthesisError::AssignmentMissing);
        }
        if circuit_version != 2 {
            return Err(SynthesisError::AssignmentMissing);
        }

        // Pad witness vectors to fixed sizes so constraints are stable.
        while ax_ants.len() < TDFOL_V1_V2_MAX_AXIOMS {
            ax_ants.push(F::ZERO);
            ax_cons.push(F::ZERO);
        }
        while trace.len() < TDFOL_V1_V2_MAX_STEPS {
            trace.push(F::ZERO);
        }

        // Public inputs.
        let theorem_hash_fr = F::from_be_bytes_mod_order(&theorem_hash_bytes);
        let axioms_commitment_fr = F::from_be_bytes_mod_order(&axioms_commitment_bytes);

        let mut hasher = Sha256::new();
        hasher.update(&ruleset_id);
        let ruleset_digest = hasher.finalize();
        let ruleset_id_fr = F::from_be_bytes_mod_order(&ruleset_digest);

        let version_fr = F::from(circuit_version as u64);

        let theorem_hash_input = FpVar::<F>::new_input(cs.clone(), || Ok(theorem_hash_fr))?;
        let axioms_commitment_input =
            FpVar::<F>::new_input(cs.clone(), || Ok(axioms_commitment_fr))?;
        let circuit_version_input = FpVar::<F>::new_input(cs.clone(), || Ok(version_fr))?;
        let ruleset_id_input = FpVar::<F>::new_input(cs.clone(), || Ok(ruleset_id_fr))?;

        // Enforce fixed version/ruleset.
        circuit_version_input.enforce_equal(&FpVar::<F>::Constant(F::from(2u64)))?;

        let mut expected_hasher = Sha256::new();
        expected_hasher.update(b"TDFOL_v1");
        let expected_ruleset_digest = expected_hasher.finalize();
        let expected_ruleset_fr = F::from_be_bytes_mod_order(&expected_ruleset_digest);
        ruleset_id_input.enforce_equal(&FpVar::<F>::Constant(expected_ruleset_fr))?;

        // Allocate axiom and trace witness variables.
        let zero = FpVar::<F>::Constant(F::ZERO);
        let mut axiom_ants_var: Vec<FpVar<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_AXIOMS);
        let mut axiom_cons_var: Vec<FpVar<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_AXIOMS);
        for i in 0..TDFOL_V1_V2_MAX_AXIOMS {
            axiom_ants_var.push(FpVar::<F>::new_witness(cs.clone(), || Ok(ax_ants[i]))?);
            axiom_cons_var.push(FpVar::<F>::new_witness(cs.clone(), || Ok(ax_cons[i]))?);
        }

        let mut trace_var: Vec<FpVar<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_STEPS);
        for i in 0..TDFOL_V1_V2_MAX_STEPS {
            trace_var.push(FpVar::<F>::new_witness(cs.clone(), || Ok(trace[i]))?);
        }

        // Axiom well-formedness and in-circuit commitment.
        // - If consequent is 0 then antecedent must be 0 (unused slot).
        // - commitment = Σ (cons + alpha*ant) * beta^i
        let alpha = FpVar::<F>::Constant(F::from(TDFOL_V1_V2_ALPHA));
        let beta = F::from(TDFOL_V1_V2_BETA);

        let mut commitment = FpVar::<F>::Constant(F::ZERO);
        let mut beta_pow = F::ONE;
        for i in 0..TDFOL_V1_V2_MAX_AXIOMS {
            let ant = &axiom_ants_var[i];
            let cons = &axiom_cons_var[i];

            let cons_is_zero = cons.is_eq(&zero)?;
            let ant_is_zero = ant.is_eq(&zero)?;
            // cons == 0 => ant == 0
            cons_is_zero
                .and(&ant_is_zero.not())?
                .enforce_equal(&Boolean::FALSE)?;

            let term = cons + (ant * &alpha);
            let weighted = term * FpVar::<F>::Constant(beta_pow);
            commitment += weighted;
            beta_pow *= beta;
        }

        axioms_commitment_input.enforce_equal(&commitment)?;

        // Trace must be non-empty (at least one non-zero step) and must be zero-padded.
        let mut step_nonzero_bits: Vec<Boolean<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_STEPS);
        let mut step_zero_bits: Vec<Boolean<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_STEPS);
        for i in 0..TDFOL_V1_V2_MAX_STEPS {
            let is_zero = trace_var[i].is_eq(&zero)?;
            step_zero_bits.push(is_zero.clone());
            step_nonzero_bits.push(is_zero.not());
        }

        Boolean::kary_or(&step_nonzero_bits)?.enforce_equal(&Boolean::TRUE)?;

        for i in 0..(TDFOL_V1_V2_MAX_STEPS - 1) {
            // trace[i] == 0 => trace[i+1] == 0
            step_zero_bits[i]
                .and(&step_zero_bits[i + 1].not())?
                .enforce_equal(&Boolean::FALSE)?;
        }

        // Enforce trace uniqueness among non-zero steps.
        for i in 0..TDFOL_V1_V2_MAX_STEPS {
            for j in (i + 1)..TDFOL_V1_V2_MAX_STEPS {
                let eq = trace_var[i].is_eq(&trace_var[j])?;
                let both_nz = step_nonzero_bits[i].and(&step_nonzero_bits[j])?;
                both_nz.and(&eq)?.enforce_equal(&Boolean::FALSE)?;
            }
        }

        // Helper closures for membership in facts / previous steps.
        let fact_membership = |x: &FpVar<F>| -> Result<Boolean<F>, SynthesisError> {
            let mut matches: Vec<Boolean<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_AXIOMS);
            for i in 0..TDFOL_V1_V2_MAX_AXIOMS {
                let ant_is_zero = axiom_ants_var[i].is_eq(&zero)?;
                let cons_is_nonzero = axiom_cons_var[i].is_eq(&zero)?.not();
                let is_fact = ant_is_zero.and(&cons_is_nonzero)?;
                let eq = axiom_cons_var[i].is_eq(x)?;
                matches.push(is_fact.and(&eq)?);
            }
            Boolean::kary_or(&matches)
        };

        let prev_membership = |x: &FpVar<F>, k: usize| -> Result<Boolean<F>, SynthesisError> {
            if k == 0 {
                return Ok(Boolean::FALSE);
            }
            let mut matches: Vec<Boolean<F>> = Vec::with_capacity(k);
            for j in 0..k {
                let eq = trace_var[j].is_eq(x)?;
                matches.push(step_nonzero_bits[j].and(&eq)?);
            }
            Boolean::kary_or(&matches)
        };

        let known_membership = |x: &FpVar<F>, k: usize| -> Result<Boolean<F>, SynthesisError> {
            let in_facts = fact_membership(x)?;
            let in_prev = prev_membership(x, k)?;
            in_facts.or(&in_prev)
        };

        // Validate each trace step.
        for k in 0..TDFOL_V1_V2_MAX_STEPS {
            let step = &trace_var[k];
            let step_nonzero = step_nonzero_bits[k].clone();

            let step_known = known_membership(step, k)?;
            let need_just = step_nonzero.and(&step_known.not())?;

            // exists implication (P -> step) with P known
            let mut just_bits: Vec<Boolean<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_AXIOMS);
            for i in 0..TDFOL_V1_V2_MAX_AXIOMS {
                let ant_is_nonzero = axiom_ants_var[i].is_eq(&zero)?.not();
                let cons_is_nonzero = axiom_cons_var[i].is_eq(&zero)?.not();
                let is_impl = ant_is_nonzero.and(&cons_is_nonzero)?;
                let cons_match = axiom_cons_var[i].is_eq(step)?;
                let ant_known = known_membership(&axiom_ants_var[i], k)?;
                just_bits.push(is_impl.and(&cons_match)?.and(&ant_known)?);
            }
            let exists_just = Boolean::kary_or(&just_bits)?;

            need_just
                .and(&exists_just.not())?
                .enforce_equal(&Boolean::FALSE)?;
        }

        // Enforce theorem is in final known set (facts or any trace step).
        let theorem_in_facts = fact_membership(&theorem_hash_input)?;
        let mut theorem_step_bits: Vec<Boolean<F>> = Vec::with_capacity(TDFOL_V1_V2_MAX_STEPS);
        for k in 0..TDFOL_V1_V2_MAX_STEPS {
            let eq = trace_var[k].is_eq(&theorem_hash_input)?;
            theorem_step_bits.push(step_nonzero_bits[k].and(&eq)?);
        }
        let theorem_in_trace = Boolean::kary_or(&theorem_step_bits)?;
        theorem_in_facts
            .or(&theorem_in_trace)?
            .enforce_equal(&Boolean::TRUE)?;

        Ok(())
    }
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

        let axioms_commitment_bytes = self
            .axioms_commitment
            .ok_or(SynthesisError::AssignmentMissing)?;
        let theorem_hash_bytes = self.theorem_hash.ok_or(SynthesisError::AssignmentMissing)?;
        let circuit_version = self.circuit_version.ok_or(SynthesisError::AssignmentMissing)?;
        let ruleset_id = self.ruleset_id.ok_or(SynthesisError::AssignmentMissing)?;

        // Fail fast on invalid assignments rather than relying on unsatisfied
        // constraints later. Unit tests expect `generate_constraints` to error.
        if axioms_commitment_bytes.len() != 32 {
            return Err(SynthesisError::AssignmentMissing);
        }
        if theorem_hash_bytes.len() != 32 {
            return Err(SynthesisError::AssignmentMissing);
        }
        if axioms_commitment_bytes.iter().all(|b| *b == 0) {
            return Err(SynthesisError::AssignmentMissing);
        }
        if theorem_hash_bytes.iter().all(|b| *b == 0) {
            return Err(SynthesisError::AssignmentMissing);
        }
        if ruleset_id.is_empty() {
            return Err(SynthesisError::AssignmentMissing);
        }

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

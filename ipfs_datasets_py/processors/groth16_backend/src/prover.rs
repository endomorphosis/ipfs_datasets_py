// src/prover.rs
// Groth16 Prover Implementation

use crate::{
    circuit::{
        MVPCircuit, TDFOLv1DerivationCircuitV2, TDFOL_V1_V2_ALPHA, TDFOL_V1_V2_BETA,
        TDFOL_V1_V2_MAX_AXIOMS, TDFOL_V1_V2_MAX_STEPS,
    },
    ProofOutput, WitnessInput,
};

use ark_bn254::{Bn254, Fr};
use ark_ff::{BigInteger, PrimeField};
use ark_groth16::{Groth16, Proof, ProvingKey};
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystem};
use ark_serialize::CanonicalDeserialize;
use ark_snark::SNARK;
use rand::rngs::{OsRng, StdRng};
use rand::SeedableRng;
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
    let bytes = hex::decode(canonical)?;
    if bytes.len() != 32 {
        anyhow::bail!("{label} must decode to 32 bytes");
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&bytes);
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

fn field_to_0x32<F: PrimeField + Copy>(x: F) -> String {
    let mut bytes: Vec<u8> = x.into_bigint().to_bytes_be();
    if bytes.len() > 32 {
        bytes = bytes[bytes.len() - 32..].to_vec();
    }
    if bytes.len() < 32 {
        let mut out = vec![0u8; 32 - bytes.len()];
        out.extend_from_slice(&bytes);
        bytes = out;
    }
    format!("0x{}", hex::encode(bytes))
}

fn fr_inputs_from_witness(witness: &WitnessInput) -> anyhow::Result<Vec<Fr>> {
    let theorem_hash_bytes = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex)?;
    let axioms_commitment_bytes =
        decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)?;

    let mut hasher = Sha256::new();
    hasher.update(witness.ruleset_id.as_bytes());
    let ruleset_digest = hasher.finalize();

    Ok(vec![
        Fr::from_be_bytes_mod_order(&theorem_hash_bytes),
        Fr::from_be_bytes_mod_order(&axioms_commitment_bytes),
        Fr::from(witness.circuit_version as u64),
        Fr::from_be_bytes_mod_order(&ruleset_digest),
    ])
}

fn witness_to_public_inputs_wire(witness: &WitnessInput) -> Vec<String> {
    vec![
        witness.theorem_hash_hex.clone(),
        witness.axioms_commitment_hex.clone(),
        witness.circuit_version.to_string(),
        witness.ruleset_id.clone(),
    ]
}

fn proof_to_evm_words(proof: &Proof<Bn254>) -> Vec<String> {
    let ax = field_to_0x32(proof.a.x);
    let ay = field_to_0x32(proof.a.y);

    let bx0 = field_to_0x32(proof.b.x.c0);
    let bx1 = field_to_0x32(proof.b.x.c1);
    let by0 = field_to_0x32(proof.b.y.c0);
    let by1 = field_to_0x32(proof.b.y.c1);

    let cx = field_to_0x32(proof.c.x);
    let cy = field_to_0x32(proof.c.y);

    vec![ax, ay, bx0, bx1, by0, by1, cx, cy]
}

fn is_tdfol_atom(s: &str) -> bool {
    let mut chars = s.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_ascii_alphabetic() {
        return false;
    }
    for c in chars {
        if !(c.is_ascii_alphanumeric() || c == '_') {
            return false;
        }
    }
    true
}

fn parse_tdfol_v1_axiom(text: &str) -> anyhow::Result<(Option<String>, String)> {
    let s = text.trim();
    if s.is_empty() {
        anyhow::bail!("axiom cannot be empty");
    }

    let parts: Vec<&str> = s.split("->").collect();
    match parts.len() {
        1 => {
            let atom = parts[0].trim();
            if !is_tdfol_atom(atom) {
                anyhow::bail!("invalid atom in fact axiom");
            }
            Ok((None, atom.to_string()))
        }
        2 => {
            let left = parts[0].trim();
            let right = parts[1].trim();
            if !is_tdfol_atom(left) {
                anyhow::bail!("invalid atom in implication antecedent");
            }
            if !is_tdfol_atom(right) {
                anyhow::bail!("invalid atom in implication consequent");
            }
            Ok((Some(left.to_string()), right.to_string()))
        }
        _ => anyhow::bail!("axiom may contain at most one '->'"),
    }
}

fn sha256_fr(atom: &str) -> Fr {
    let digest = Sha256::digest(atom.as_bytes());
    Fr::from_be_bytes_mod_order(&digest)
}

fn commit_axioms_v2(ax_ants: &[Fr], ax_cons: &[Fr]) -> Fr {
    let alpha = Fr::from(TDFOL_V1_V2_ALPHA);
    let beta = Fr::from(TDFOL_V1_V2_BETA);

    let mut acc = Fr::ZERO;
    let mut beta_pow = Fr::ONE;
    for (ant, cons) in ax_ants.iter().zip(ax_cons.iter()) {
        let term = *cons + (*ant * alpha);
        acc += term * beta_pow;
        beta_pow *= beta;
    }
    acc
}

fn fr_to_32bytes_be(x: Fr) -> [u8; 32] {
    let mut bytes: Vec<u8> = x.into_bigint().to_bytes_be();
    if bytes.len() > 32 {
        bytes = bytes[bytes.len() - 32..].to_vec();
    }
    if bytes.len() < 32 {
        let mut out = vec![0u8; 32 - bytes.len()];
        out.extend_from_slice(&bytes);
        bytes = out;
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&bytes);
    out
}

fn build_tdfol_v1_v2_circuit(
    witness: &WitnessInput,
) -> anyhow::Result<TDFOLv1DerivationCircuitV2<Fr>> {
    if witness.ruleset_id != "TDFOL_v1" {
        anyhow::bail!("circuit_version=2 currently supports ruleset_id=TDFOL_v1 only");
    }

    let theorem_atom = witness.theorem.trim();
    if !is_tdfol_atom(theorem_atom) {
        anyhow::bail!("theorem must be an atom for TDFOL_v1");
    }

    if witness.private_axioms.len() > TDFOL_V1_V2_MAX_AXIOMS {
        anyhow::bail!(
            "too many axioms for circuit_version=2 (max {})",
            TDFOL_V1_V2_MAX_AXIOMS
        );
    }

    let mut ax_ants: Vec<Fr> = Vec::with_capacity(witness.private_axioms.len());
    let mut ax_cons: Vec<Fr> = Vec::with_capacity(witness.private_axioms.len());

    for axiom in &witness.private_axioms {
        let (ant, cons) = parse_tdfol_v1_axiom(axiom)?;
        let ant_fr = ant.as_deref().map(sha256_fr).unwrap_or(Fr::ZERO);
        let cons_fr = sha256_fr(&cons);
        ax_ants.push(ant_fr);
        ax_cons.push(cons_fr);
    }

    if witness.intermediate_steps.is_empty() {
        anyhow::bail!("intermediate_steps must be non-empty for circuit_version=2");
    }
    if witness.intermediate_steps.len() > TDFOL_V1_V2_MAX_STEPS {
        anyhow::bail!(
            "too many intermediate_steps for circuit_version=2 (max {})",
            TDFOL_V1_V2_MAX_STEPS
        );
    }

    let mut trace_fr: Vec<Fr> = Vec::with_capacity(witness.intermediate_steps.len());
    for step in &witness.intermediate_steps {
        let atom = step.trim();
        if !is_tdfol_atom(atom) {
            anyhow::bail!("invalid atom in intermediate_steps");
        }
        trace_fr.push(sha256_fr(atom));
    }

    let expected_commitment_fr = commit_axioms_v2(&ax_ants, &ax_cons);
    let expected_commitment_hex = hex::encode(fr_to_32bytes_be(expected_commitment_fr));
    if strip_0x_prefix(&witness.axioms_commitment_hex) != expected_commitment_hex {
        anyhow::bail!("axioms_commitment_hex does not match TDFOL_v1 v2 commitment");
    }

    let theorem_hash_expected = hex::encode(Sha256::digest(theorem_atom.as_bytes()));
    if strip_0x_prefix(&witness.theorem_hash_hex) != theorem_hash_expected {
        anyhow::bail!("theorem_hash_hex does not match theorem");
    }

    let axioms_commitment =
        decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)?;
    let theorem_hash = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex)?;

    Ok(TDFOLv1DerivationCircuitV2 {
        axiom_antecedents: Some(ax_ants),
        axiom_consequents: Some(ax_cons),
        trace_steps: Some(trace_fr),
        axioms_commitment: Some(axioms_commitment.to_vec()),
        theorem_hash: Some(theorem_hash.to_vec()),
        circuit_version: Some(2),
        ruleset_id: Some(witness.ruleset_id.as_bytes().to_vec()),
    })
}

/// Generate Groth16 proof from witness.
///
/// - Loads `proving_key.bin` from `artifacts/v{circuit_version}/`
/// - Generates a real Groth16 proof using arkworks
/// - Emits EVM-friendly encodings under:
///   - `extra.evm_proof`: 8 x 0x32 words
///   - `extra.evm_public_inputs`: 4 x 0x32 words
pub fn generate_proof(witness: &WitnessInput, seed: Option<u64>) -> anyhow::Result<ProofOutput> {
    if witness.private_axioms.is_empty() {
        anyhow::bail!("private_axioms cannot be empty");
    }
    if witness.theorem.trim().is_empty() {
        anyhow::bail!("theorem cannot be empty");
    }
    if witness.ruleset_id.trim().is_empty() {
        anyhow::bail!("ruleset_id cannot be empty");
    }
    if witness.circuit_version > 255 {
        anyhow::bail!("circuit_version must be <= 255");
    }

    let pk = load_proving_key(witness.circuit_version)?;
    let deterministic = is_deterministic_mode(seed);

    let proof = match witness.circuit_version {
        1 => {
            let axioms_commitment =
                decode_32byte_hex("axioms_commitment_hex", &witness.axioms_commitment_hex)?;
            let theorem_hash = decode_32byte_hex("theorem_hash_hex", &witness.theorem_hash_hex)?;

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

            let cs = ConstraintSystem::<Fr>::new_ref();
            circuit.clone().generate_constraints(cs.clone())?;
            if !cs.is_satisfied()? {
                anyhow::bail!("circuit constraints not satisfied");
            }

            match seed {
                Some(seed) => {
                    let mut rng = StdRng::seed_from_u64(seed);
                    Groth16::<Bn254>::prove(&pk, circuit, &mut rng)?
                }
                None => {
                    let mut rng = OsRng;
                    Groth16::<Bn254>::prove(&pk, circuit, &mut rng)?
                }
            }
        }
        2 => {
            let circuit: TDFOLv1DerivationCircuitV2<Fr> = build_tdfol_v1_v2_circuit(witness)?;

            let cs = ConstraintSystem::<Fr>::new_ref();
            circuit.clone().generate_constraints(cs.clone())?;
            if !cs.is_satisfied()? {
                anyhow::bail!("circuit constraints not satisfied");
            }

            match seed {
                Some(seed) => {
                    let mut rng = StdRng::seed_from_u64(seed);
                    Groth16::<Bn254>::prove(&pk, circuit, &mut rng)?
                }
                None => {
                    let mut rng = OsRng;
                    Groth16::<Bn254>::prove(&pk, circuit, &mut rng)?
                }
            }
        }
        _ => anyhow::bail!("unsupported circuit_version: {}", witness.circuit_version),
    };

    let timestamp = if deterministic {
        0
    } else {
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs()
    };

    let public_inputs_wire = witness_to_public_inputs_wire(witness);
    let public_inputs_fr = fr_inputs_from_witness(witness)?;

    let evm_public_inputs: Vec<String> = public_inputs_fr
        .iter()
        .copied()
        .map(field_to_0x32)
        .collect();
    let evm_proof = proof_to_evm_words(&proof);

    let proof_a = serde_json::to_string(&[evm_proof[0].clone(), evm_proof[1].clone()])?;
    let proof_b = serde_json::to_string(&[
        [evm_proof[2].clone(), evm_proof[3].clone()],
        [evm_proof[4].clone(), evm_proof[5].clone()],
    ])?;
    let proof_c = serde_json::to_string(&[evm_proof[6].clone(), evm_proof[7].clone()])?;

    let mut extra = witness.extra.clone();
    extra.insert(
        "evm_proof".to_string(),
        serde_json::Value::Array(evm_proof.into_iter().map(serde_json::Value::String).collect()),
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
    use crate::setup;

    #[test]
    fn test_prover_witness_validation_rejects_empty_axioms() {
        let invalid_witness = WitnessInput {
            private_axioms: vec![],
            theorem: "Q".to_string(),
            intermediate_steps: vec![],
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
    fn test_prover_generates_real_proof_and_evm_extras_v1() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("groth16_prover_artifacts_{nonce}"));
        let out_dir = root.join("v1");
        let _manifest = setup::setup_to_dir(1, &out_dir, Some(123)).expect("setup should succeed");
        std::env::set_var("GROTH16_BACKEND_ARTIFACTS_ROOT", &root);

        let witness = WitnessInput {
            private_axioms: vec!["P".to_string(), "P -> Q".to_string()],
            theorem: "Q".to_string(),
            intermediate_steps: vec![],
            axioms_commitment_hex:
                "03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5".to_string(),
            theorem_hash_hex: "4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260"
                .to_string(),
            circuit_version: 1,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let proof = generate_proof(&witness, Some(42)).expect("proof");
        assert_eq!(proof.version, 1);
        assert_eq!(proof.public_inputs.len(), 4);
        assert_eq!(proof.public_inputs[0], witness.theorem_hash_hex);
        assert_eq!(proof.public_inputs[1], witness.axioms_commitment_hex);

        let evm_proof = proof.extra.get("evm_proof").expect("evm_proof");
        assert_eq!(evm_proof.as_array().unwrap().len(), 8);
        let evm_inputs = proof
            .extra
            .get("evm_public_inputs")
            .expect("evm_public_inputs");
        assert_eq!(evm_inputs.as_array().unwrap().len(), 4);
        assert_eq!(proof.timestamp, 0);

        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn test_prover_generates_real_proof_v2_simple_trace() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("groth16_prover_artifacts_v2_{nonce}"));
        let out_dir = root.join("v2");
        let _manifest = setup::setup_to_dir(2, &out_dir, Some(123)).expect("setup should succeed");
        std::env::set_var("GROTH16_BACKEND_ARTIFACTS_ROOT", &root);

        let ax_ants = vec![Fr::ZERO, sha256_fr("P")];
        let ax_cons = vec![sha256_fr("P"), sha256_fr("Q")];
        let commitment_hex = hex::encode(fr_to_32bytes_be(commit_axioms_v2(&ax_ants, &ax_cons)));

        let witness = WitnessInput {
            private_axioms: vec!["P".to_string(), "P -> Q".to_string()],
            theorem: "Q".to_string(),
            intermediate_steps: vec!["Q".to_string()],
            axioms_commitment_hex: commitment_hex,
            theorem_hash_hex: hex::encode(Sha256::digest(b"Q")),
            circuit_version: 2,
            ruleset_id: "TDFOL_v1".to_string(),
            security_level: None,
            extra: Default::default(),
        };

        let proof = generate_proof(&witness, Some(42)).expect("proof");
        assert_eq!(proof.version, 2);
        assert_eq!(proof.public_inputs.len(), 4);
        assert_eq!(proof.public_inputs[0], witness.theorem_hash_hex);
        assert_eq!(proof.public_inputs[1], witness.axioms_commitment_hex);

        let _ = std::fs::remove_dir_all(&root);
    }
}

// src/setup.rs
// Trusted setup (circuit-specific parameters) for Groth16 MVP circuit

use crate::circuit::{MVPCircuit, TDFOLv1DerivationCircuitV2};
use ark_bn254::{Bn254, Fr};
use ark_ff::PrimeField;
use ark_groth16::Groth16;
use ark_serialize::CanonicalSerialize;
use ark_snark::SNARK;
use rand::rngs::{OsRng, StdRng};
use rand::SeedableRng;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Serialize, Clone)]
pub struct SetupManifestV1 {
    pub schema_version: u32,
    pub version: u32,
    pub proving_key_path: String,
    pub verifying_key_path: String,
    pub proving_key_sha256_hex: String,
    pub verifying_key_sha256_hex: String,
    pub vk_hash_hex: String,
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    hex::encode(digest)
}

fn build_mvp_setup_circuit(version: u32) -> MVPCircuit {
    MVPCircuit {
        private_axioms: Some(vec![b"A".to_vec()]),
        theorem: Some(b"B".to_vec()),
        axioms_commitment: Some(vec![1u8; 32]),
        theorem_hash: Some(vec![2u8; 32]),
        circuit_version: Some(version),
        ruleset_id: Some(b"TDFOL_v1".to_vec()),
    }
}

fn field_to_32bytes(x: Fr) -> [u8; 32] {
    use ark_ff::BigInteger;
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

fn sha256_bytes(msg: &[u8]) -> [u8; 32] {
    let digest = Sha256::digest(msg);
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    out
}

fn commit_axioms_v2(axiom_antecedents: &[Fr], axiom_consequents: &[Fr]) -> Fr {
    // C = Σ (cons + alpha*ant) * beta^i
    let alpha = Fr::from(crate::circuit::TDFOL_V1_V2_ALPHA);
    let beta = Fr::from(crate::circuit::TDFOL_V1_V2_BETA);
    let mut acc = Fr::ZERO;
    let mut beta_pow = Fr::ONE;
    for (ant, cons) in axiom_antecedents.iter().zip(axiom_consequents.iter()) {
        let term = *cons + (*ant * alpha);
        acc += term * beta_pow;
        beta_pow *= beta;
    }
    acc
}

fn build_tdfol_v1_v2_setup_circuit() -> TDFOLv1DerivationCircuitV2<Fr> {
    let hp = Fr::from_be_bytes_mod_order(&sha256_bytes(b"P"));
    let hq = Fr::from_be_bytes_mod_order(&sha256_bytes(b"Q"));

    let ax_ants = vec![Fr::ZERO, hp];
    let ax_cons = vec![hp, hq];
    let commitment_fr = commit_axioms_v2(&ax_ants, &ax_cons);

    TDFOLv1DerivationCircuitV2 {
        axiom_antecedents: Some(ax_ants),
        axiom_consequents: Some(ax_cons),
        trace_steps: Some(vec![hq]),
        axioms_commitment: Some(field_to_32bytes(commitment_fr).to_vec()),
        theorem_hash: Some(sha256_bytes(b"Q").to_vec()),
        circuit_version: Some(2),
        ruleset_id: Some(b"TDFOL_v1".to_vec()),
    }
}

pub fn setup_to_dir(version: u32, out_dir: &Path, seed: Option<u64>) -> anyhow::Result<SetupManifestV1> {
    if version > 255 {
        anyhow::bail!("circuit_version must be <= 255 for MVP circuit");
    }

    fs::create_dir_all(out_dir)?;

    let (pk, vk) = match version {
        1 => {
            let circuit = build_mvp_setup_circuit(version);
            match seed {
                Some(seed) => {
                    let mut rng = StdRng::seed_from_u64(seed);
                    Groth16::<Bn254>::circuit_specific_setup(circuit.clone(), &mut rng)?
                }
                None => {
                    let mut rng = OsRng;
                    Groth16::<Bn254>::circuit_specific_setup(circuit.clone(), &mut rng)?
                }
            }
        }
        2 => {
            let circuit = build_tdfol_v1_v2_setup_circuit();
            match seed {
                Some(seed) => {
                    let mut rng = StdRng::seed_from_u64(seed);
                    Groth16::<Bn254>::circuit_specific_setup(circuit.clone(), &mut rng)?
                }
                None => {
                    let mut rng = OsRng;
                    Groth16::<Bn254>::circuit_specific_setup(circuit.clone(), &mut rng)?
                }
            }
        }
        _ => anyhow::bail!("unsupported circuit version: {version} (supported: 1, 2)"),
    };

    let pk_path: PathBuf = out_dir.join("proving_key.bin");
    let vk_path: PathBuf = out_dir.join("verifying_key.bin");

    let mut pk_bytes: Vec<u8> = Vec::new();
    pk.serialize_uncompressed(&mut pk_bytes)?;
    fs::write(&pk_path, &pk_bytes)?;

    let mut vk_bytes: Vec<u8> = Vec::new();
    vk.serialize_uncompressed(&mut vk_bytes)?;
    fs::write(&vk_path, &vk_bytes)?;

    let pk_sha256_hex = sha256_hex(&pk_bytes);
    let vk_sha256_hex = sha256_hex(&vk_bytes);

    // For now, the VK hash is the SHA256 of the canonical serialized VK bytes.
    // This is intended to be stored on-chain and/or in a registry later.
    let vk_hash_hex = vk_sha256_hex.clone();

    Ok(SetupManifestV1 {
        schema_version: 1,
        version,
        proving_key_path: pk_path.to_string_lossy().to_string(),
        verifying_key_path: vk_path.to_string_lossy().to_string(),
        proving_key_sha256_hex: pk_sha256_hex,
        verifying_key_sha256_hex: vk_sha256_hex,
        vk_hash_hex,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn test_setup_rejects_version_out_of_range() {
        let tmp = std::env::temp_dir().join("groth16_setup_test");
        let err = setup_to_dir(256, &tmp, None).unwrap_err();
        assert!(format!("{err:#}").contains("circuit_version"));
    }

    #[test]
    fn test_setup_writes_nonempty_artifacts_and_returns_hashes() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let out_dir = std::env::temp_dir().join(format!("groth16_setup_{nonce}"));

        let manifest = setup_to_dir(1, &out_dir, None).expect("setup should succeed");

        assert_eq!(manifest.schema_version, 1);
        assert_eq!(manifest.version, 1);
        assert_eq!(manifest.vk_hash_hex.len(), 64);
        assert_eq!(manifest.proving_key_sha256_hex.len(), 64);
        assert_eq!(manifest.verifying_key_sha256_hex.len(), 64);

        let pk_bytes = fs::read(&manifest.proving_key_path).expect("pk should exist");
        let vk_bytes = fs::read(&manifest.verifying_key_path).expect("vk should exist");
        assert!(!pk_bytes.is_empty());
        assert!(!vk_bytes.is_empty());

        // Cleanup best-effort to avoid cluttering /tmp
        let _ = fs::remove_dir_all(&out_dir);
    }

    #[test]
    fn test_setup_is_reproducible_with_seed() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let out_dir1 = std::env::temp_dir().join(format!("groth16_setup_seed_a_{nonce}"));
        let out_dir2 = std::env::temp_dir().join(format!("groth16_setup_seed_b_{nonce}"));

        let m1 = setup_to_dir(1, &out_dir1, Some(123456789)).expect("setup should succeed");
        let m2 = setup_to_dir(1, &out_dir2, Some(123456789)).expect("setup should succeed");

        assert_eq!(m1.proving_key_sha256_hex, m2.proving_key_sha256_hex);
        assert_eq!(m1.verifying_key_sha256_hex, m2.verifying_key_sha256_hex);
        assert_eq!(m1.vk_hash_hex, m2.vk_hash_hex);

        let _ = fs::remove_dir_all(&out_dir1);
        let _ = fs::remove_dir_all(&out_dir2);
    }
}

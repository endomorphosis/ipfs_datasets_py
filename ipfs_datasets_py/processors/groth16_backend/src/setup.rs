// src/setup.rs
// Trusted setup (circuit-specific parameters) for Groth16 MVP circuit

use crate::{circuit::MVPCircuit, BackendError};
use ark_bn254::Bn254;
use ark_groth16::Groth16;
use ark_serialize::CanonicalSerialize;
use rand::rngs::OsRng;
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

pub fn setup_to_dir(version: u32, out_dir: &Path) -> anyhow::Result<SetupManifestV1> {
    if version > 255 {
        return Err(BackendError::Unsupported("circuit_version must be <= 255 for MVP circuit".to_string()).into());
    }

    fs::create_dir_all(out_dir)?;

    let circuit = build_mvp_setup_circuit(version);

    let mut rng = OsRng;
    let (pk, vk) = Groth16::<Bn254>::circuit_specific_setup(circuit, &mut rng)?;

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
        let err = setup_to_dir(256, &tmp).unwrap_err();
        assert!(format!("{err:#}").contains("circuit_version"));
    }

    #[test]
    fn test_setup_writes_nonempty_artifacts_and_returns_hashes() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let out_dir = std::env::temp_dir().join(format!("groth16_setup_{nonce}"));

        let manifest = setup_to_dir(1, &out_dir).expect("setup should succeed");

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
}

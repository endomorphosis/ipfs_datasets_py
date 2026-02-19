// src/main.rs
// CLI Interface for Groth16 Prover/Verifier

use clap::{Parser, Subcommand};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fmt::Write as _;
use std::fs;
use std::io::{self, Read};
use std::process;

use ark_bn254::Bn254;
use ark_ff::{BigInteger, PrimeField};
use ark_groth16::VerifyingKey;
use ark_serialize::CanonicalDeserialize;

const ERROR_SCHEMA_VERSION: u32 = 1;

#[derive(Parser)]
#[command(about = "Groth16 ZKP Prover/Verifier")]
struct Args {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Generate a Groth16 proof
    Prove {
        /// Input witness JSON file (use '-' for stdin)
        #[arg(short, long)]
        input: String,

        /// Output proof JSON file (use '-' for stdout)
        #[arg(short, long)]
        output: String,

        /// Seed for deterministic proving (also forces timestamp=0)
        #[arg(long)]
        seed: Option<u64>,

        /// Suppress status messages (stderr)
        #[arg(long, default_value_t = false)]
        quiet: bool,
    },

    /// Verify a Groth16 proof
    Verify {
        /// Input proof JSON file (use '-' for stdin)
        #[arg(short, long)]
        proof: String,

        /// Emit a JSON result to stdout (while still using exit codes)
        #[arg(long, default_value_t = false)]
        json: bool,

        /// Suppress status messages (stderr)
        #[arg(long, default_value_t = false)]
        quiet: bool,
    },

    /// Setup trusted parameters
    Setup {
        /// Circuit version
        #[arg(short, long)]
        version: u32,

        /// Seed for deterministic setup (optional)
        #[arg(long)]
        seed: Option<u64>,

        /// Suppress status messages (stderr)
        #[arg(long, default_value_t = false)]
        quiet: bool,
    },

    /// Export a circuit-specific Solidity verifier contract
    ///
    /// This reads a `verifying_key.bin` produced by `groth16 setup`, computes
    /// its SHA-256 digest as `vk_hash_hex`, and emits a Solidity contract that
    /// imports the in-repo `GrothVerifier.sol` base verifier and overrides
    /// `verifyingKey()` with constants matching this verifying key.
    ExportSolidity {
        /// Input verifying key binary (e.g., artifacts/v1/verifying_key.bin)
        #[arg(long)]
        verifying_key: String,

        /// Circuit version (uint64 in Solidity; use the same version you ran setup with)
        #[arg(long)]
        version: u32,

        /// Output Solidity file (use '-' for stdout)
        #[arg(long)]
        out: String,

        /// Solidity import path for the verifier prototype
        #[arg(long, default_value = "./GrothVerifier.sol")]
        import_path: String,

        /// Suppress status messages (stderr)
        #[arg(long, default_value_t = false)]
        quiet: bool,
    },
}

#[derive(Debug, Serialize)]
struct ErrorEnvelope {
    error: CliError,
}

#[derive(Debug, Serialize)]
struct CliError {
    schema_version: u32,
    code: String,
    message: String,
}

fn is_stdout_path(path: &str) -> bool {
    path == "-" || path == "/dev/stdout"
}

fn is_stdin_path(path: &str) -> bool {
    path == "-" || path == "/dev/stdin"
}

fn read_text_arg(path: &str) -> anyhow::Result<String> {
    if is_stdin_path(path) {
        let mut buf = String::new();
        io::stdin().read_to_string(&mut buf)?;
        Ok(buf)
    } else {
        Ok(fs::read_to_string(path)?)
    }
}

fn write_text_arg(path: &str, content: &str) -> anyhow::Result<()> {
    if is_stdout_path(path) {
        // IMPORTANT: keep stdout JSON-only.
        print!("{}", content);
        Ok(())
    } else {
        fs::write(path, content)?;
        Ok(())
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    hex::encode(digest)
}

fn to_0x_u256<F: PrimeField>(x: &F) -> String {
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

fn solidity_verifier_contract(
    version: u32,
    vk_hash_hex: &str,
    vk: &VerifyingKey<Bn254>,
    import_path: &str,
) -> anyhow::Result<String> {
    if vk_hash_hex.len() != 64 {
        anyhow::bail!("vk_hash_hex must be 32 bytes (64 hex chars)");
    }
    // Validate hex.
    let _ = hex::decode(vk_hash_hex)?;

    let contract_name = format!("GrothVerifierV{version}");

    // G1 alpha
    let alfa_x = to_0x_u256(&vk.alpha_g1.x);
    let alfa_y = to_0x_u256(&vk.alpha_g1.y);

    // G2 points in altbn128 precompile format: (im, re)
    let beta_x_im = to_0x_u256(&vk.beta_g2.x.c1);
    let beta_x_re = to_0x_u256(&vk.beta_g2.x.c0);
    let beta_y_im = to_0x_u256(&vk.beta_g2.y.c1);
    let beta_y_re = to_0x_u256(&vk.beta_g2.y.c0);

    let gamma_x_im = to_0x_u256(&vk.gamma_g2.x.c1);
    let gamma_x_re = to_0x_u256(&vk.gamma_g2.x.c0);
    let gamma_y_im = to_0x_u256(&vk.gamma_g2.y.c1);
    let gamma_y_re = to_0x_u256(&vk.gamma_g2.y.c0);

    let delta_x_im = to_0x_u256(&vk.delta_g2.x.c1);
    let delta_x_re = to_0x_u256(&vk.delta_g2.x.c0);
    let delta_y_im = to_0x_u256(&vk.delta_g2.y.c1);
    let delta_y_re = to_0x_u256(&vk.delta_g2.y.c0);

    let ic_len = vk.gamma_abc_g1.len();
    if ic_len != 5 {
        anyhow::bail!("expected vk.gamma_abc_g1 length 5 (4 public inputs + 1), got {ic_len}");
    }

    let mut ic_lines = String::new();
    for (i, p) in vk.gamma_abc_g1.iter().enumerate() {
        let x = to_0x_u256(&p.x);
        let y = to_0x_u256(&p.y);
        writeln!(
            &mut ic_lines,
            "        vk.IC[{i}] = Pairing.G1Point({x}, {y});"
        )?;
    }

    Ok(format!(
        r#"// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

// AUTO-GENERATED: groth16 export-solidity
// - version: {version}
// - vk_hash_hex (sha256(verifying_key.bin)): {vk_hash_hex}

import "{import_path}";

contract {contract_name} is GrothVerifier {{
    bytes32 public constant VK_HASH = 0x{vk_hash_hex};
    uint64 public constant CIRCUIT_VERSION = {version};

    function verifyingKey() internal pure override returns (VerifyingKey memory vk) {{
        vk.alfa1 = Pairing.G1Point({alfa_x}, {alfa_y});

        vk.beta2 = Pairing.G2Point(
            [{beta_x_im}, {beta_x_re}],
            [{beta_y_im}, {beta_y_re}]
        );

        vk.gamma2 = Pairing.G2Point(
            [{gamma_x_im}, {gamma_x_re}],
            [{gamma_y_im}, {gamma_y_re}]
        );

        vk.delta2 = Pairing.G2Point(
            [{delta_x_im}, {delta_x_re}],
            [{delta_y_im}, {delta_y_re}]
        );

        vk.IC = new Pairing.G1Point[]({ic_len});
{ic_lines}
    }}
}}
"#
    ))
}

#[cfg(test)]
mod export_tests {
    use super::*;

    #[test]
    fn test_solidity_verifier_contract_contains_vk_hash_and_version() {
        // Construct a small dummy VK with correct lengths by deserializing a real one
        // is too heavy for unit tests here; instead, ensure hash/version strings render.
        let dummy_vk_bytes = vec![1u8; 32];
        let vk_hash_hex = sha256_hex(&dummy_vk_bytes);
        assert_eq!(vk_hash_hex.len(), 64);

        // Minimal smoke test: generate contract name and constants via a fake VK.
        let g1 = ark_bn254::G1Affine::identity();
        let g2 = ark_bn254::G2Affine::identity();
        let vk = VerifyingKey::<Bn254> {
            alpha_g1: g1,
            beta_g2: g2,
            gamma_g2: g2,
            delta_g2: g2,
            gamma_abc_g1: vec![g1; 5],
        };

        let sol = solidity_verifier_contract(1, &vk_hash_hex, &vk, "./GrothVerifier.sol").unwrap();
        assert!(sol.contains("contract GrothVerifierV1"));
        assert!(sol.contains("bytes32 public constant VK_HASH = 0x"));
        assert!(sol.contains("uint64 public constant CIRCUIT_VERSION = 1"));
        assert!(sol.contains("import \"./GrothVerifier.sol\""));
        assert!(sol.contains("function verifyingKey()"));
    }
}

fn error_code(err: &anyhow::Error) -> &'static str {
    if err.downcast_ref::<serde_json::Error>().is_some() {
        return "INVALID_JSON";
    }
    if err.downcast_ref::<hex::FromHexError>().is_some() {
        return "INVALID_HEX";
    }
    if err.downcast_ref::<std::io::Error>().is_some() {
        return "IO_ERROR";
    }
    "INTERNAL"
}

fn emit_error_json_to_stdout(code: &str, message: &str) {
    let env = ErrorEnvelope {
        error: CliError {
            schema_version: ERROR_SCHEMA_VERSION,
            code: code.to_string(),
            message: message.to_string(),
        },
    };

    match serde_json::to_string(&env) {
        Ok(s) => print!("{}\n", s),
        Err(_) => {
            print!(
                "{}\n",
                r#"{"error":{"schema_version":1,"code":"INTERNAL","message":"failed to serialize error"}}"#
            );
        }
    }
}

fn main() {
    let args = Args::parse();

    let exit_code = match args.command {
        Commands::Prove {
            input,
            output,
            seed,
            quiet,
        } => {
            let run = || -> anyhow::Result<()> {
                let witness_json = read_text_arg(&input)?;
                let proof = groth16_backend::prove_with_seed(&witness_json, seed)?;
                write_text_arg(&output, &proof)?;
                if !quiet && !is_stdout_path(&output) {
                    eprintln!("✅ Proof written to {}", output);
                }
                Ok(())
            };

            match run() {
                Ok(()) => 0,
                Err(err) => {
                    let code = error_code(&err);
                    let message = format!("{:#}", err);
                    if is_stdout_path(&output) {
                        emit_error_json_to_stdout(code, &message);
                    }
                    if !quiet {
                        eprintln!("ERROR[{code}]: {message}");
                    }
                    2
                }
            }
        }

        Commands::Verify { proof, json, quiet } => {
            let run = || -> anyhow::Result<bool> {
                let proof_json = read_text_arg(&proof)?;
                groth16_backend::verify(&proof_json)
            };

            match run() {
                Ok(is_valid) => {
                    // Exit codes:
                    // - 0: valid
                    // - 1: invalid
                    if json {
                        print!(r#"{{"valid":{}}}\n"#, if is_valid { "true" } else { "false" });
                    }
                    if !quiet {
                        if is_valid {
                            eprintln!("✅ Proof is VALID");
                        } else {
                            eprintln!("❌ Proof is INVALID");
                        }
                    }
                    if is_valid { 0 } else { 1 }
                }
                Err(err) => {
                    let code = error_code(&err);
                    let message = format!("{:#}", err);
                    emit_error_json_to_stdout(code, &message);
                    if !quiet {
                        eprintln!("ERROR[{code}]: {message}");
                    }
                    2
                }
            }
        }

        Commands::Setup { version, seed, quiet } => {
            let run = || -> anyhow::Result<()> {
                if !quiet {
                    eprintln!("Setting up trusted parameters for v{}...", version);
                }
                let manifest_json = groth16_backend::setup(version, seed)?;
                // Keep stdout JSON-only.
                print!("{}", manifest_json);
                Ok(())
            };

            match run() {
                Ok(()) => 0,
                Err(err) => {
                    let code = error_code(&err);
                    let message = format!("{:#}", err);
                    emit_error_json_to_stdout(code, &message);
                    if !quiet {
                        eprintln!("ERROR[{code}]: {message}");
                    }
                    2
                }
            }
        }

        Commands::ExportSolidity {
            verifying_key,
            version,
            out,
            import_path,
            quiet,
        } => {
            let run = || -> anyhow::Result<()> {
                let vk_bytes = fs::read(&verifying_key)?;
                if vk_bytes.is_empty() {
                    anyhow::bail!("verifying_key file is empty");
                }

                let vk_hash_hex = sha256_hex(&vk_bytes);
                let mut cursor: &[u8] = &vk_bytes;
                let vk = VerifyingKey::<Bn254>::deserialize_uncompressed(&mut cursor)?;
                let solidity = solidity_verifier_contract(version, &vk_hash_hex, &vk, &import_path)?;
                write_text_arg(&out, &solidity)?;

                if !quiet && !is_stdout_path(&out) {
                    eprintln!("✅ Solidity verifier written to {}", out);
                }
                Ok(())
            };

            match run() {
                Ok(()) => 0,
                Err(err) => {
                    let code = error_code(&err);
                    let message = format!("{:#}", err);
                    if is_stdout_path(&out) {
                        emit_error_json_to_stdout(code, &message);
                    }
                    if !quiet {
                        eprintln!("ERROR[{code}]: {message}");
                    }
                    2
                }
            }
        }
    };

    process::exit(exit_code);
}

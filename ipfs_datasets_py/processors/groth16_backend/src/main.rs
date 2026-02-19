// src/main.rs
// CLI Interface for Groth16 Prover/Verifier

use clap::{Parser, Subcommand};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Read};
use std::process;

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

    /// Export a versioned Solidity wrapper embedding vk_hash
    ///
    /// This reads a `verifying_key.bin` produced by `groth16 setup`, computes
    /// its SHA-256 digest as `vk_hash_hex`, and emits a Solidity contract that
    /// imports the in-repo `GrothVerifier.sol` prototype and exposes the hash
    /// as a `bytes32 public constant`.
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

fn solidity_wrapper_contract(version: u32, vk_hash_hex: &str, import_path: &str) -> anyhow::Result<String> {
    if vk_hash_hex.len() != 64 {
        anyhow::bail!("vk_hash_hex must be 32 bytes (64 hex chars)");
    }
    // Validate hex.
    let _ = hex::decode(vk_hash_hex)?;

    let contract_name = format!("GrothVerifierV{version}");
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
}}
"#
    ))
}

#[cfg(test)]
mod export_tests {
    use super::*;

    #[test]
    fn test_solidity_wrapper_contract_contains_vk_hash_and_version() {
        let sol = solidity_wrapper_contract(1, &"a".repeat(64), "./GrothVerifier.sol").unwrap();
        assert!(sol.contains("contract GrothVerifierV1"));
        assert!(sol.contains("bytes32 public constant VK_HASH = 0x"));
        assert!(sol.contains(&format!("0x{}", "a".repeat(64))));
        assert!(sol.contains("uint64 public constant CIRCUIT_VERSION = 1"));
        assert!(sol.contains("import \"./GrothVerifier.sol\""));
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
                let solidity = solidity_wrapper_contract(version, &vk_hash_hex, &import_path)?;
                write_text_arg(&out, &solidity)?;

                if !quiet && !is_stdout_path(&out) {
                    eprintln!("✅ Solidity wrapper written to {}", out);
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

// src/main.rs
// CLI Interface for Groth16 Prover/Verifier

use clap::{Parser, Subcommand};
use serde::Serialize;
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
                r#"{\"error\":{\"schema_version\":1,\"code\":\"INTERNAL\",\"message\":\"failed to serialize error\"}}"#
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
                        print!(r#"{{\"valid\":{}}}\n"#, if is_valid { "true" } else { "false" });
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

        Commands::Setup { version } => {
            let run = || -> anyhow::Result<()> {
                eprintln!("Setting up trusted parameters for v{}...", version);
                let manifest_json = groth16_backend::setup(version)?;
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
                    eprintln!("ERROR[{code}]: {message}");
                    2
                }
            }
        }
    };

    process::exit(exit_code);
}

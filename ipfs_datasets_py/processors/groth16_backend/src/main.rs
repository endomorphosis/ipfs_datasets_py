// src/main.rs
// CLI Interface for Groth16 Prover/Verifier

use clap::{Parser, Subcommand};
use std::fs;

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
        /// Input witness JSON file
        #[arg(short, long)]
        input: String,

        /// Output proof JSON file
        #[arg(short, long)]
        output: String,
    },

    /// Verify a Groth16 proof
    Verify {
        /// Input proof JSON file
        #[arg(short, long)]
        proof: String,
    },

    /// Setup trusted parameters
    Setup {
        /// Circuit version
        #[arg(short, long)]
        version: u32,
    },
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    match args.command {
        Commands::Prove { input, output } => {
            // Read witness from JSON
            let witness_json = fs::read_to_string(&input)?;

            // Generate proof
            let proof = groth16_backend::prove(&witness_json)?;

            // Write proof to JSON
            fs::write(&output, proof)?;
            println!("✅ Proof written to {}", output);
        }

        Commands::Verify { proof } => {
            // Read proof from JSON
            let proof_json = fs::read_to_string(&proof)?;

            // Verify proof
            let is_valid = groth16_backend::verify(&proof_json)?;

            if is_valid {
                println!("✅ Proof is VALID");
            } else {
                println!("❌ Proof is INVALID");
            }
        }

        Commands::Setup { version } => {
            println!("Setting up trusted parameters for v{}...", version);
            println!("⚠️  Setup not yet implemented");
            // TODO: Implement trusted setup
        }
    }

    Ok(())
}

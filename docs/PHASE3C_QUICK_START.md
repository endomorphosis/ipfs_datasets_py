"""
PHASE 3C QUICK START GUIDE
==========================

Status: Ready for Immediate Implementation
Target: Begin Rust project setup (Task 3C.1.1)

## ONE-COMMAND STARTUP

```bash
# From workspace root
cd ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend
# If you are creating this from scratch (older docs), this folder used to be
# created at repo-root as ./groth16_backend. The canonical location is now
# in-tree under ipfs_datasets_py/.../processors/.
#
# Build the binary:
cargo build --release
```

## PROJECT STRUCTURE (Template)

```
ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/  (Rust project)
├─ Cargo.toml                       (dependency manifest)
├─ src/
│  ├─ main.rs                       (CLI: prove, verify)
│  ├─ lib.rs                        (library interface)
│  ├─ circuit.rs                    (MVP circuit definition)
│  ├─ prover.rs                     (Groth16 prover)
│  ├─ verifier.rs                   (Groth16 verifier)
│  └─ domain.rs                     (domain separation)
├─ tests/
│  └─ integration_tests.rs          (Rust tests)
├─ inputs/                          (JSON witness inputs)
└─ outputs/                         (JSON proofs)

ipfs_datasets_py/
└─ ipfs_datasets_py/
   └─ logic/
      └─ zkp/
         ├─ backends/
         │  ├─ groth16.py           (Python FFI wrapper) [NEW - Task 3C.2]
         │  └─ ...
         ├─ test_groth16_backend.py (tests) [NEW - Task 3C.3]
         └─ ...
```

## CARGO.toml (Starting Template)

```toml
[package]
name = "groth16_backend"
version = "0.1.0"
edition = "2021"

[dependencies]
ark-groth16 = "0.4"
ark-ec = "0.4"
ark-ff = "0.4"
ark-bn254 = "0.4"
ark-std = "0.4"
ark-serialize = { version = "0.4", features = ["derive"] }
ark-relations = "0.4"
sha2 = "0.10"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
clap = { version = "4.0", features = ["derive"] }

[[bin]]
name = "groth16"
path = "src/main.rs"

[lib]
name = "groth16_backend"
path = "src/lib.rs"

[profile.release]
opt-level = 3
lto = true
```

## MAIN.RS (CLI Interface Template)

```rust
// src/main.rs
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
            println!("Proof written to {}", output);
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
            // TODO: Implement trusted setup
        }
    }
    
    Ok(())
}
```

## LIB.RS (Library Interface Template)

```rust
// src/lib.rs

pub mod circuit;
pub mod prover;
pub mod verifier;
pub mod domain;

use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct WitnessInput {
    pub private_axioms: Vec<String>,
    pub theorem: String,
    pub axioms_commitment_hex: String,
    pub theorem_hash_hex: String,
    pub circuit_version: u32,
    pub ruleset_id: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ProofOutput {
    pub proof_a: String,              // Serialized point A
    pub proof_b: String,              // Serialized point B
    pub proof_c: String,              // Serialized point C
    pub public_inputs: Vec<String>,   // 4 public input scalars
    pub timestamp: u64,
    pub version: u32,
}

/// Generate Groth16 proof from witness
pub fn prove(witness_json: &str) -> anyhow::Result<String> {
    let witness: WitnessInput = serde_json::from_str(witness_json)?;
    let proof = prover::generate_proof(&witness)?;
    Ok(serde_json::to_string(&proof)?)
}

/// Verify Groth16 proof
pub fn verify(proof_json: &str) -> anyhow::Result<bool> {
    let proof: ProofOutput = serde_json::from_str(proof_json)?;
    verifier::verify_proof(&proof)
}
```

## DOMAIN.RS (Domain Separation Template)

```rust
// src/domain.rs

pub const THEOREM_DOMAIN: &[u8] = b"PHASE3C_MVP_THEOREM_v1";
pub const AXIOMS_DOMAIN: &[u8] = b"PHASE3C_MVP_AXIOMS_v1";

pub fn hash_theorem(theorem: &[u8]) -> Vec<u8> {
    use sha2::{Sha256, Digest};
    let mut hasher = Sha256::new();
    hasher.update(THEOREM_DOMAIN);
    hasher.update(theorem);
    hasher.finalize().to_vec()
}

pub fn hash_axioms(axioms: &[String]) -> Vec<u8> {
    use sha2::{Sha256, Digest};
    let mut hasher = Sha256::new();
    hasher.update(AXIOMS_DOMAIN);
    
    // Canonical ordering (alphabetical)
    let mut ordered = axioms.clone();
    ordered.sort();
    
    for axiom in ordered {
        hasher.update(axiom.as_bytes());
        hasher.update(b"\n");
    }
    
    hasher.finalize().to_vec()
}
```

## CIRCUIT.RS (Circuit Template - SKELETON)

```rust
// src/circuit.rs
// IMPORTANT: This is a skeleton. Full implementation in Phase 3C.1

use ark_ff::Field;
use ark_r1cs_std::prelude::*;
use ark_relations::r1cs::{ConstraintSystem, ConstraintSynthesizer, SynthesisError};

pub struct MVPCircuit {
    pub private_axioms: Option<Vec<Vec<u8>>>,
    pub theorem: Option<Vec<u8>>,
    pub axioms_commitment: Option<Vec<u8>>,  // 32 bytes from SHA256
    pub theorem_hash: Option<Vec<u8>>,       // 32 bytes from SHA256
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

impl<F: Field> ConstraintSynthesizer<F> for MVPCircuit {
    fn generate_constraints(self, cs: ConstraintSystemRef<F>) -> Result<()> {
        // CONSTRAINT 1: Verify axioms hash
        // TODO: Implement SHA256 constraint circuit
        
        // CONSTRAINT 2: Verify theorem hash
        // TODO: Implement SHA256 constraint circuit
        
        // CONSTRAINT 3: Verify circuit version in range
        // TODO: Implement range proof
        
        // CONSTRAINT 4: Verify ruleset ID non-zero
        // TODO: Implement non-zero check
        
        Ok(())
    }
}
```

## PROVER.RS (Prover Template - SKELETON)

```rust
// src/prover.rs

use crate::{
    circuit::MVPCircuit,
    WitnessInput, ProofOutput,
};
use ark_bn254::{Bn254, Fr};
use ark_groth16::{Groth16, ProvingKey};
use ark_ff::BigInteger256;
use std::time::{SystemTime, UNIX_EPOCH};

/// Generate Groth16 proof
pub fn generate_proof(witness: &WitnessInput) -> anyhow::Result<ProofOutput> {
    // Parse hex inputs to bytes
    let axioms_commitment = hex::decode(&witness.axioms_commitment_hex)?;
    let theorem_hash = hex::decode(&witness.theorem_hash_hex)?;
    
    // Create circuit
    let circuit = MVPCircuit {
        private_axioms: Some(
            witness
                .private_axioms
                .iter()
                .map(|a| a.as_bytes().to_vec())
                .collect()
        ),
        theorem: Some(witness.theorem.as_bytes().to_vec()),
        axioms_commitment: Some(axioms_commitment),
        theorem_hash: Some(theorem_hash),
        circuit_version: Some(witness.circuit_version),
        ruleset_id: Some(witness.ruleset_id.as_bytes().to_vec()),
    };
    
    // Load proving key from disk
    // TODO: Implement trusted setup + PK loading
    let pk: ProvingKey<Bn254> = load_proving_key(witness.circuit_version)?;
    
    // Generate proof
    let proof = Groth16::<Bn254>::prove(&pk, circuit, &mut OsRng)?;
    
    // Serialize proof to JSON
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs();
    
    Ok(ProofOutput {
        proof_a: format!("{:?}", proof.a),
        proof_b: format!("{:?}", proof.b),
        proof_c: format!("{:?}", proof.c),
        public_inputs: witness_to_public_inputs(witness),
        timestamp,
        version: witness.circuit_version,
    })
}

fn witness_to_public_inputs(witness: &WitnessInput) -> Vec<String> {
    vec![
        witness.theorem_hash_hex.clone(),
        witness.axioms_commitment_hex.clone(),
        witness.circuit_version.to_string(),
        witness.ruleset_id.clone(),
    ]
}

fn load_proving_key(version: u32) -> anyhow::Result<ProvingKey<Bn254>> {
    // TODO: Load from disk or generate on first run
    anyhow::bail!("Trusted setup not yet implemented")
}
```

## COMPILE AND BUILD

```bash
# From groth16_backend/ directory
cargo build --release

# Test compilation
cargo test --lib

# Run CLI
./target/release/groth16 --help
```

## IMMEDIATE TASKS (In Order)

### Task 1: Initialize Rust Project (5 minutes)
```bash
cd /home/barberb/complaint-generator
mkdir -p groth16_backend
cd groth16_backend
cargo init --name groth16_backend
```

### Task 2: Copy Templates (10 minutes)
```bash
# Copy Cargo.toml
# Copy src/main.rs
# Copy src/lib.rs
# Copy src/domain.rs
# Copy src/circuit.rs (skeleton)
# Copy src/prover.rs (skeleton)
```

### Task 3: Compile (2 minutes)
```bash
cargo build --release
# Expect: Compilation successful, binary at target/release/groth16
```

### Task 4: Start Filling In (Day 1)
```
Circuit constraints (src/circuit.rs)
  ↓
Prover logic (src/prover.rs)
  ↓
Trusted setup loading
  ↓
Integration tests
```

## EXPECTED MILESTONES

| Milestone | Target Time | Verification |
|-----------|------------|--------------|
| Rust project compiles | 30 min | `cargo build` succeeds |
| Circuit skeleton | 1 hour | `cargo test --lib` passes |
| SHA256 constraints | 2 hours | Unit tests pass |
| Prover works | 4 hours | Generates valid JSON proofs |
| CLI functional | 1 day | `./target/release/groth16 --help` works |
| All 8 vectors | 2 days | Golden vector proofs generate |
| Verification works | 2 days | Proofs verify correctly |

## DEPENDENCIES TO INSTALL

**System (outside of Rust):**
```bash
# Ubuntu/Debian
sudo apt-get install build-essential pkg-config libssl-dev

# macOS
brew install openssl pkg-config
```

**Rust (automatic via cargo):**
- All ark-* crates will download
- Build time: ~3-5 minutes first time

## DEBUGGING TIPS

**If compilation fails:**
```bash
# Check Rust version
rustc --version        # Should be 1.70+

# Update toolchain
rustup update

# Clean build
cargo clean
cargo build --release
```

**If tests fail:**
```bash
# Run with verbose output
cargo test --lib -- --nocapture

# Run specific test
cargo test circuit:: -- --nocapture
```

**If too slow:**
```bash
# Debug mode is slow, use release
cargo build --release
cargo test --release

# Incremental compilation
touch src/main.rs  # Force recompile
```

## NEXT PHASE ENTRY

Once Rust binary compiles and runs:
1. Create Python FFI wrapper (Task 3C.2)
2. Test witness serialization JSON format
3. Iterate on circuit constraints

Entry condition: `./target/release/groth16 --help` produces output

## FILES TO CREATE (Checklist)

```
☐ groth16_backend/
  ☐ Cargo.toml
  ☐ src/main.rs
  ☐ src/lib.rs
  ☐ src/domain.rs
  ☐ src/circuit.rs
  ☐ src/prover.rs
  ☐ src/verifier.rs
  
☐ backends/groth16.py (Python FFI wrapper - Task 3C.2)
☐ test_groth16_backend.py (Python tests - Task 3C.3)
```

## VERIFICATION CHECKLIST

✅ Phase 3B complete (60/60 tests passing)
✅ MVPWitness format locked (no changes expected)
✅ Circuit spec finalized (PHASE3C_CIRCUIT_SPEC.md)
✅ Implementation plan written (PHASE3C_GROTH16_IMPLEMENTATION_PLAN.md)
✅ Quick-start guide ready (this document)
✅ Ready to begin Task 3C.1.1

**Status: READY FOR IMPLEMENTATION**
"""

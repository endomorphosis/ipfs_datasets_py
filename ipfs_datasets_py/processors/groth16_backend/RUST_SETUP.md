"""
PHASE 3C.1 RUST SETUP INSTRUCTIONS
===================================

Status: Rust Project Structure Ready | Cargo Installation Required
Date: 2025-02-17

## RUST INSTALLATION

The Groth16 backend is a Rust project. You must install Rust before proceeding.

### Install Rust (Ubuntu/Linux)

**Option 1: Official Rust Installation (Recommended)**
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Then activate Rust
source "$HOME/.cargo/env"

# Verify installation
rustc --version
cargo --version
```

**Option 2: System Package Manager**
```bash
sudo apt update
sudo apt install rustup

# Initialize Rust
rustup default stable
```

### Install Rust (macOS)
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### Verify Installation
```bash
rustc --version   # Should show Rust version (e.g., rustc 1.75.0)
cargo --version    # Should show Cargo version (e.g., cargo 1.75.0)
```

## RUST PROJECT STRUCTURE

The following structure has been created:

```
groth16_backend/
├─ Cargo.toml           ✅ Created (Dependencies defined)
├─ src/
│  ├─ main.rs           ✅ Created (CLI interface)
│  ├─ lib.rs            ✅ Created (Library interface)
│  ├─ domain.rs         ✅ Created (Domain separation)
│  ├─ circuit.rs        ✅ Created (Circuit skeleton)
│  ├─ prover.rs         ✅ Created (Prover skeleton)
│  └─ verifier.rs       ✅ Created (Verifier skeleton)
└─ Cargo.lock           (auto-generated on first build)
```

## DEPENDENCIES

The Cargo.toml includes:

**Cryptography & Circuits:**
- `ark-groth16` 0.4 — Groth16 zkSNARK implementation
- `ark-ec` 0.4 — Elliptic curve operations
- `ark-ff` 0.4 — Finite field arithmetic
- `ark-bn254` 0.4 — BN254 curve (Ethereum-compatible)
- `ark-relations` 0.4 — R1CS constraint system

**Standard Libraries:**
- `ark-std` 0.4 — Ark standard library
- `sha2` 0.10 — SHA256 hashing
- `serde` 1.0 — Serialization framework
- `serde_json` 1.0 — JSON I/O

**CLI & Utilities:**
- `clap` 4.0 — Command-line argument parsing
- `anyhow` 1.0 — Error handling
- `hex` 0.4 — Hex encoding/decoding
- `rand` 0.8 — Random number generation

## FIRST COMPILATION

After installing Rust:

```bash
cd /home/barberb/complaint-generator/groth16_backend

# Download dependencies and compile
cargo build --release

# Expected output:
# ...
#    Compiling groth16_backend v0.1.0 (...)
#     Finished release [optimized] target(s) in Xs
```

**Build time:** 3-5 minutes (first build downloads ~200MB dependencies)

## TESTING STRUCTURE

Unit tests are included in each module:

```bash
# Run all tests
cargo test --lib

# Run with output
cargo test --lib -- --nocapture

# Run specific module
cargo test circuit::
```

## NEXT STEPS (After Rust Installation)

Once Rust is installed and `cargo build --release` succeeds:

### Task 3C.1.2: Implement MVP Circuit
- [ ] Implement SHA256 constraints in `src/circuit.rs`
- [ ] Add constraint synthesis logic
- [ ] Run `cargo test circuit::`
- [ ] Verify all circuit tests pass

### Task 3C.1.3: Implement Trusted Setup
- [ ] Create setup module (if needed)
- [ ] Load/generate proving and verification keys
- [ ] Implement key serialization

### Task 3C.2: Python Integration
- [ ] Create `backends/groth16.py` FFI wrapper
- [ ] Implement subprocess communication
- [ ] Serialize/deserialize JSON witness and proof
- [ ] Integrate with backend registry

## TROUBLESHOOTING

### "Command not found: cargo"
**Solution:** Rust not installed. Follow RUST INSTALLATION above.

### Compilation errors about dependencies
**Solution:** Update dependencies:
```bash
cargo update
cargo clean
cargo build --release
```

### Out of disk space during build
**Solution:** Clean previous builds:
```bash
cargo clean
```

### Network errors downloading dependencies
**Solution:** Check internet connection and retry:
```bash
cargo build --release --offline  # (if already partially downloaded)
# or
cargo build --release             # (retry)
```

### Wrong Rust version
**Solution:** Update Rust:
```bash
rustup update
rustup default stable
```

## BUILD PROFILE

The release profile in Cargo.toml:
```toml
[profile.release]
opt-level = 3      # Maximum optimization
lto = true         # Link-time optimization (smaller, faster binary)
```

This produces an optimized binary at:
```
target/release/groth16
```

## PROJECT STATUS

```
☑️  Rust project structure created
☑️  All source files created (skeleton implementations)
☑️  Dependencies configured in Cargo.toml
☐  Rust installed on system
☐  Compilation successful (requires Rust)
☐  Circuit constraints implemented
☐  Trusted setup completed
☐  Python FFI wrapper created
☐  Integration tests passing
```

## VERIFICATION CHECKLIST

Once Rust is installed:

- [ ] `rustc --version` produces output
- [ ] `cargo --version` produces output
- [ ] `cd /home/barberb/complaint-generator/groth16_backend`
- [ ] `cargo build --release` completes successfully
- [ ] `./target/release/groth16 --help` shows usage text
- [ ] `cargo test --lib` passes all unit tests

## REFERENCE DOCUMENTATION

**Groth16 Background:**
- https://eprint.iacr.org/2016/260 — Original Groth16 paper

**arkworks Documentation:**
- https://arkworks.rs/ — Main reference
- https://docs.rs/ark-groth16/0.4.0/ — Groth16 API
- https://docs.rs/ark-bn254/0.4.0/ — BN254 curve

**R1CS (Rank-1 Constraint System):**
- https://en.wikipedia.org/wiki/Rank-1_constraint_system
- https://docs.rs/ark-relations/0.4.0/ark_relations/ — Implementation

## NEXT PHASE ENTRY

Entry condition: Rust installation ✅ AND `cargo build --release` succeeds ✅

If installation is deferred:
- Python FFI wrapper can be created first (Task 3C.2 / Task 3C.3)
- Circuit implementation waits for Rust (Task 3C.1.2)
- Python tests can mock Groth16 backend until Rust ready

## DECISION POINT

**Option A: Install Rust Now (Recommended)**
- Proceed with Phase 3C.1 full implementation
- Estimated 1-2 hours for complete setup + first compilation
- Timeline impact: +1-2 hours

**Option B: Create Python Wrapper First**
- Start with Python FFI backend (allows testing without Rust)
- Defer Rust implementation to Phase 3C.1.2
- Install Rust later when circuit implementation begins
- Timeline impact: None (parallel work)

**Recommendation:** Option A
**Rationale:** Rust is critical path for real proofs; installing early enables faster iteration

## SUPPORT

If installation issues arise:
1. Check Rust installation: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
2. Verify Cargo version: `cargo --version` (should be >= 1.70)
3. For troubleshooting: https://www.rust-lang.org/tools/install

Next checkpoint: Verify `cargo build --release` succeeds
"""

# ZKP Module Setup Guide

**Status:** Draft (living document)

This guide covers how to set up and validate the `logic/zkp` module.

## 1. Default (Simulated) Backend

No special setup is required. The simulated backend is the default and is intended for educational/prototyping use only.

### Run tests

From `complaint-generator/ipfs_datasets_py`:

```bash
python -m pytest -q tests/unit_tests/logic/zkp
```

## 2. Opt-in Groth16 Backend (Rust)

The repository-supported direction for “real Groth16” is the Rust backend located at:

- `ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/`

### 2.1 Prerequisites

- Rust toolchain (stable) + Cargo
- A Python dev/test environment for running the unit tests

### 2.2 Build the Groth16 binary

```bash
cd ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend
cargo build --release
```

### 2.3 Enable Groth16 explicitly (fail-closed by default)

```bash
export IPFS_DATASETS_ENABLE_GROTH16=1
```

Optional binary override:

```bash
export IPFS_DATASETS_GROTH16_BINARY="$PWD/target/release/groth16"
```

### 2.4 Validate via gated tests

The Groth16 end-to-end test(s) are **skipped** unless Groth16 is enabled and the binary is discoverable.

```bash
python -m pytest -q tests/unit_tests/logic/zkp/test_zkp_integration.py
```

## 3. Trusted Setup Artifacts (Not Yet Implemented)

Groth16 requires circuit-specific setup artifacts:

- Proving key (PK)
- Verification key (VK)

**Current state:** the repo does not yet define a stable, production artifact lifecycle for PK/VK generation, storage, and rotation.

**Planned work:** see `PRODUCTION_UPGRADE_PATH.md` and the master backlog.

### 3.1 Trusted setup ceremony notes (operational)

When Groth16 setup/parameter generation is implemented, treat it as a security-critical ceremony:

- **Multiparty contributions:** prefer an MPC ceremony where multiple independent contributors add entropy.
- **Transcript:** keep a signed, append-only transcript of contributions (inputs, outputs, hashes, timestamps).
- **Checksums everywhere:** publish SHA-256 (or similar) checksums for:
  - circuit source / constraints (R1CS)
  - proving key (PK)
  - verifying key (VK)
  - any generated Solidity verifier artifacts
- **Reproducible verification:** ensure third parties can independently verify the transcript and that the final VK matches the transcript output.
- **Key hygiene:** treat PK material as sensitive operational data; restrict access and log usage.
- **Versioning:** bind ceremony outputs to `circuit_id@v<uint64>` so older VKs remain discoverable and verifiable.

## 4. Artifact Storage (Not Yet Implemented)

A production system should define:

- Integrity checks (hashes/checksums)
- Storage and pinning policy (e.g., IPFS + pinning + backups)
- Access controls for PK material

## 5. On-Chain Registration (Not Yet Implemented)

If verifying on-chain, you will need:

- A Solidity verifier generated from the VK
- A registry/policy contract to manage circuit versions and VK hashes

This is tracked in the backlog under Phase P6.

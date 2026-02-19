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

## 3. Trusted Setup Artifacts (Rust CLI)

Groth16 requires circuit-specific setup artifacts:

- Proving key (PK)
- Verification key (VK)

**Current state:** the Rust backend can generate PK/VK artifacts and a small stdout-friendly manifest. A production-grade artifact lifecycle (signing, rotation, publication) is still a policy/process decision and is tracked in the master backlog.

### 3.1 Generate PK/VK artifacts

From the Groth16 backend crate root:

```bash
cd ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend

# Writes artifacts under: ./artifacts/v1/
# Emits a JSON manifest to stdout.
./target/release/groth16 setup --version 1 > artifacts/v1/manifest.json
```

Deterministic (reproducible) setup is available via `--seed`:

```bash
./target/release/groth16 setup --version 1 --seed 123 > artifacts/v1/manifest.json
```

Artifacts written under `artifacts/v<version>/`:

- `proving_key.bin`
- `verifying_key.bin`
- `manifest.json` (your redirected stdout)

### 3.2 Export a versioned Solidity wrapper (VK hash binding)

This repository currently treats `vk_hash_hex = sha256(verifying_key.bin)` as the on-chain/off-chain identifier for a VK.

You can generate a versioned Solidity wrapper that embeds this hash and the circuit version:

```bash
./target/release/groth16 export-solidity \
  --verifying-key artifacts/v1/verifying_key.bin \
  --version 1 \
  --out artifacts/v1/GrothVerifierV1.sol
```

Notes:

- The generated contract inherits from `GrothVerifier.sol` and adds `VK_HASH` + `CIRCUIT_VERSION` constants.
- `export-solidity` does not (yet) regenerate the underlying verifier’s VK constants from `verifying_key.bin`; end-to-end on-chain verification is still tracked under Phase P6.

### 3.3 Trusted setup ceremony notes (operational)

When Groth16 setup/parameter generation is used to produce production artifacts, treat it as a security-critical ceremony:

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

## 4. Artifact Lifecycle (Operational Policy)

The repo does not yet automate PK/VK generation, publication, and rotation, but production deployments still need an artifact lifecycle.

Minimum policy (what to decide and document):

- Artifact inventory per `circuit_id@v<uint64>` (PK, VK, circuit description, verifier artifacts)
- Integrity verification (hashes + an optional signing workflow)
- Storage and pinning (IPFS CIDs + pinned replicas)
- HTTPS backup (S3/MinIO or similar) as a second durable copy
- Access controls and audit trail for PK material
- Retention and deprecation rules (keep old versions verifiable)

### 4.1 Recommended artifact layout

Keep a per-version directory keyed by `circuit_id@v<uint64>`:

- `manifest.json` (authoritative metadata)
- `manifest.sha256` (hash of `manifest.json`)
- `manifest.sig` (optional: signature over `manifest.sha256`)
- `vk.json` (or backend-specific VK format)
- `pk.bin` / `pk.json` (backend-specific; treat as sensitive)
- `circuit.json` / `r1cs.bin` (backend-specific circuit representation)

At minimum, `manifest.json` should include:

- `circuit_ref` (e.g., `mvp@v1`)
- `backend` / `proof_system` (e.g., `groth16`)
- SHA-256 checksums for each artifact file
- IPFS CID(s) (if published) for each artifact file
- creation timestamp and operator identity (or a reference to the ceremony transcript)

### 4.2 IPFS publication + pinning

If artifacts are published to IPFS:

- Add each artifact (or a directory wrapper) to IPFS and record the CID(s).
- Pin the CID(s) in at least two independent places (e.g., IPFS Cluster + a pinning service).
- Treat pinning as part of “release”: if it isn’t pinned, it isn’t reliably available.

Operational notes:

- Prefer CIDv1 where possible.
- Record CID(s) in the manifest (and sign the manifest if you have a signing workflow).
- Never overwrite content at an existing CID; publish new CIDs for new versions.

### 4.3 HTTPS/S3 backup (second durable copy)

Keep a second copy outside IPFS:

- Store `manifest.json` + all artifacts in an object store (S3/MinIO) or HTTPS-served blob storage.
- Enable immutability / versioning on the bucket if available.

Acceptance check:

- You can reconstruct the full artifact set for a given `circuit_ref` from either IPFS (via CIDs + pins) or HTTPS/S3 (via stored files), and in both cases verify checksums match the manifest.

### 4.4 Access controls (PK material)

- Treat proving keys (PK) as sensitive operational data.
- Restrict PK read access (least privilege) and log access.
- Encrypt PK at rest if stored outside a protected host/environment.

Verification keys (VK) are typically safe to distribute publicly.

## 5. On-Chain Registration (In progress)

If verifying on-chain, you will need:

- A Solidity verifier generated from the VK
- A registry/policy contract to manage circuit versions and VK hashes

This is tracked in the backlog under Phase P6.
## 6. Monitoring & Metrics (Operational)

The Python prover/verifier already track basic counters and timing:

- Prover: `ZKPProver.get_stats()`
  - `proofs_generated`, `total_proving_time`, `avg_proving_time`
  - `cache_hits`, `cache_hit_rate`
- Verifier: `ZKPVerifier.get_stats()`
  - `proofs_verified`, `proofs_rejected`, `total_verification_time`, `avg_verification_time`
  - `acceptance_rate`

### 6.1 What to alert on

- Rejection spikes: sudden increases in `proofs_rejected` or a sustained drop in `acceptance_rate`.
- Latency regressions: `avg_proving_time` or `avg_verification_time` rising above your SLO.
- Backend errors: the verifier logs a warning on backend verification exceptions (fail-closed).

### 6.2 Minimal instrumentation pattern

In a service loop, periodically emit these stats to logs or your metrics system:

```python
prover_stats = prover.get_stats()
verifier_stats = verifier.get_stats()

logger.info(
    "zkp_metrics",
    extra={
        "zkp_prover": prover_stats,
        "zkp_verifier": verifier_stats,
        "backend": {"prover": prover.backend, "verifier": verifier.backend},
    },
)
```

Keep metrics backend-agnostic: the same counters should remain meaningful for both simulated and real Groth16 backends.


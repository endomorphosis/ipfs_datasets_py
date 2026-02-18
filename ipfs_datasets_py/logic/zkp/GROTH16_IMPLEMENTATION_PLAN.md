# Groth16 Production Implementation Plan (`logic/zkp`)

**Goal:** add a real Groth16 zkSNARK backend to `ipfs_datasets_py.logic.zkp` while keeping the existing simulation backend as the default, import-quiet, and safe-by-default.

**Non-goals (this plan does NOT attempt):**
- Designing new UX/UI.
- Replacing the simulation immediately.
- Claiming cryptographic security until the backend is implemented, audited, and gated.

---

## 0) Guiding Requirements (Production)

### R0 — Safety / UX invariants
- `import ipfs_datasets_py.logic.zkp` remains warning-quiet.
- Simulation warning remains **warn-on-use**, not on import.
- Real backend is **opt-in**, and fails closed if not available.

### R1 — Compatibility / ecosystem fit
- Primary target: **EVM-style on-chain verification**.
- First curve target for on-chain Groth16 verifier compatibility: **BN254** (aka altbn128).
- Artifacts are content-addressed and distributable via IPFS (CIDs), enabling ephemeral “peer prover” instances.

### R2 — Circuit lifecycle
- Circuits are **versioned**.
- Contract verifies proofs against a registered verifying key (VK) per circuit version.
- Upgrades do not break old proofs unless explicitly deprecated.

---

## 1) Proposed Package Architecture (Minimal, Pluggable)

### 1.1 Keep current API stable
Current public names:
- `ZKPProver`, `ZKPVerifier`, `ZKPProof`, `ZKPError`
- Aliases `Simulated*` remain supported.

### 1.2 Add backend protocol
Introduce a small backend interface (pure Python typing, no heavy imports on module import):
- `ZKBackend.generate_proof(theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof`
- `ZKBackend.verify_proof(proof: ZKPProof) -> bool`
- `ZKBackend.backend_id: str`
- `ZKBackend.curve_id: str` (e.g., `bn254`)

### 1.3 Backends layout
Create:
- `logic/zkp/backends/simulated.py` (wrap existing behavior)
- `logic/zkp/backends/groth16_py_ecc.py` (real Groth16 via `py_ecc` and supporting code)
- `logic/zkp/backends/__init__.py` (backend registry, lazy load)

**Import rule:** `logic/zkp/__init__.py` must not import `py_ecc`.

### 1.4 Prover/verifier become thin wrappers
- `ZKPProver(backend="simulated" | "groth16", circuit_id=..., version=...)`
- `ZKPVerifier(backend="simulated" | "groth16", circuit_id=..., version=...)`

Default remains `simulated`.

---

## 2) Circuit & Statement Design (What is being proven?)

You need a crisp, chain-verifiable statement. For “legal theorems,” you typically want to prove *a claim about committed inputs*.

### 2.1 Minimal public inputs (recommended)
Public inputs should be hashes/IDs, not raw text:
- `theorem_hash`: `H(canonical_theorem_text)`
- `axioms_commitment`: commitment to the private axioms set (e.g., Merkle root)
- `ruleset_id`: which inference rules / engine semantics were used
- `circuit_version`: identifies constraint system

### 2.2 Private witness
- The private axioms themselves (or their Merkle membership paths)
- Any intermediate proof steps / witness values

### 2.3 Canonicalization
Define canonicalization for theorem/axioms text:
- normalization (whitespace, unicode normalization)
- stable ordering for axiom sets
- domain-specific canonical form if using TDFOL/CEC structures

**Deliverable:** `logic/zkp/canonicalization.py` spec + tests.

---

## 3) Trusted Setup & Key Management

Groth16 requires structured reference string material.

### 3.1 Setup strategy (pragmatic)
- Circuit-specific setup per `(circuit_id, circuit_version)`.
- Produce:
  - Proving key (PK) artifact
  - Verifying key (VK) artifact

### 3.2 Artifact distribution
- Store PK/VK artifacts off-chain and content-address them:
  - PK CID in IPFS (large)
  - VK CID in IPFS (small)
- On-chain contract stores:
  - `vk_hash` (hash of VK bytes)
  - optionally the VK itself (if small enough)
  - `circuit_id`, `version`, and policy flags

### 3.3 Ephemeral peer “join/leave” flow
- Peer spins up:
  - fetches PK from IPFS using CID
  - proves locally
  - publishes proof + public inputs (or proof CID)
  - disappears
- Verifier (anyone) can:
  - fetch proof (or receive it directly)
  - submit to contract for verification

---

## 4) On-Chain Verifier Integration (EVM-first)

### 4.1 Contract interface sketch
- `registerVK(bytes32 circuitId, uint64 version, bytes vkOrVkHash, ...policy)`
- `verify(bytes32 circuitId, uint64 version, Proof proof, uint256[] publicInputs) returns (bool)`

### 4.2 Public input encoding
- Use field elements compatible with BN254 scalar field.
- Map hashes into field elements safely:
  - e.g., interpret 256-bit hash mod `p` with domain separation.

### 4.3 Versioning / governance
- Allow multiple active versions.
- Optional deprecation mechanism that does not break historical proofs.

---

## 5) Implementation Phases (Concrete Milestones)

### Phase A — Interfaces + gating (no crypto yet)
- Add backend protocol + registry.
- Keep simulation as default.
- Add explicit `backend="groth16"` selection that raises a clear `ZKPError` if not installed.

**Exit criteria:**
- Import quietness tests pass.
- `groth16` backend selection fails closed with actionable error.

### Phase B — Circuit specification (MVP circuit)
Pick one minimal circuit to prove a claim useful for legal-theorem workflows.

MVP suggestion:
- Prove knowledge of a set of axioms whose Merkle root matches `axioms_commitment`, and that `theorem_hash` equals the public theorem.

This is not “full theorem proving” yet, but it establishes:
- witness handling
- commitments
- public input encoding
- on-chain verifier integration

**Exit criteria:**
- deterministic canonicalization
- reproducible commitments
- end-to-end proof/verify in Python (off-chain)

### Phase C — Real Groth16 proof generation + verification
- Implement Groth16 backend using a vetted library stack.
- Generate PK/VK artifacts.
- Verify proofs off-chain in Python.

**Exit criteria:**
- passes correctness tests
- proof verification is deterministic
- artifacts are serializable and hash-stable

### Phase D — EVM verifier + integration harness
- Generate Solidity verifier for VK.
- Add an integration harness that:
  - creates proof off-chain
  - verifies off-chain
  - verifies on-chain (local dev chain)

**Exit criteria:**
- on-chain verification succeeds for valid proofs and fails for invalid

### Phase E — Legal-theorem semantics (real statement)
Only after the crypto plumbing works, integrate with actual logic semantics:
- Choose a formal system representation (e.g., TDFOL) and encode constraints.
- Carefully define what “theorem holds” means.

**Exit criteria:**
- threat model documented
- semantics are testable and stable

---

## 6) Testing Strategy (Production-grade)

### 6.1 Unit tests (always-on)
- canonicalization stable
- commitment construction stable
- serialization round-trip for proof and keys
- backend selection + failure modes

### 6.2 Property tests (recommended)
- random axioms ordering does not change commitment
- invalid proofs fail verification

### 6.3 Integration tests (opt-in)
- require crypto deps and possibly a local chain
- run under a marker/env flag (never on default CI)

### 6.4 Golden vectors
- fixed inputs → fixed public inputs
- fixed VK hash

---

## 7) Security Model (What must be true?)

### 7.1 Threat model to document
- adversary can submit arbitrary proofs
- adversary can attempt replay across circuit versions
- adversary can attempt to craft public input collisions

### 7.2 Security controls
- strict domain separation in hashing
- include `(circuit_id, version)` in transcript/public inputs
- size limits for artifacts
- explicit dependency pinning

### 7.3 Operational practices
- treat setup artifacts as sensitive
- store checksums/hashes on-chain
- publish provenance for ceremonies

---

## 8) Dependencies (Reality check)

Python-native Groth16 stacks are limited.

Implementation options:
1) **Python-first** (harder): use `py_ecc` for curve ops and implement/full stack glue.
2) **Rust/Go prover with Python wrapper** (pragmatic): use a mature Groth16 implementation and call it from Python.

**Recommendation for production:** prioritize a mature prover/verifier implementation, even if the prover is not pure Python.

---

## 9) Deliverables Checklist

- [ ] Backend protocol + registry (lazy loaded)
- [ ] Canonicalization + commitments module
- [ ] Groth16 backend implementation
- [ ] Artifact formats + hashing + IPFS CID helpers
- [ ] On-chain verifier contract + registry
- [ ] End-to-end harness (off-chain proof → on-chain verify)
- [ ] Docs: threat model, versioning, ceremony workflow

---

## 10) Suggested Next Step in This Repo

Start with Phase A + Phase B “MVP circuit” and keep it explicitly separate from the simulation:
- This produces a real, verifiable primitive (commitment + knowledge proof), which is the foundation for later encoding full legal-theorem semantics.

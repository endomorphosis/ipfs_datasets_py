# ZKP Module Threat Model

**Status:** Draft (living document)

This document describes the threat model for the `logic/zkp` module. It covers both:

- The **default simulated backend** (educational; *not* cryptographically secure)
- The **opt-in Groth16 backend** (Rust FFI/subprocess; intended direction for real cryptography)

## 1. Scope and Security Goals

### In scope
- Proof objects (`ZKPProof`) and their serialization/deserialization.
- Public inputs contract (e.g., `theorem`, `theorem_hash`, `axioms_commitment`, `circuit_version`, `ruleset_id`).
- Backend selection and gating (safe defaults; fail-closed behavior).
- Witness/statement consistency checks for the MVP “knowledge-of-axioms” circuit.
- Local generation and verification flows.

### Out of scope (for now)
- On-chain verification and contracts (tracked in P6).
- Formal compilation of arbitrary “legal theorem semantics” to R1CS (tracked in P7).
- Side-channel resistance and constant-time guarantees.
- Secure multi-party trusted setup ceremonies beyond documenting expectations.

### Goals (when using a real ZKP backend)
- **Soundness:** A malicious prover cannot convince a verifier of a false statement except with negligible probability.
- **Zero-knowledge:** Proofs reveal nothing beyond the truth of the statement (axioms remain private).
- **Robustness:** Malformed or adversarial inputs do not crash verifiers; verification fails safely.
- **Determinism where required:** Hashes/commitments/cache keys are stable under canonicalization.

### Non-goals (simulation backend)
- The simulated backend does **not** provide soundness or zero-knowledge.
- Any “security level” fields are metadata only and must not be treated as guarantees.

## 2. Assets

- **Private axioms:** Confidential inputs that must not leak.
- **Witness material:** Axioms and any intermediate steps retained on the prover.
- **Statement/public inputs:** Theorem hash and axioms commitment that the verifier sees.
- **Trusted setup artifacts (Groth16):** Proving key (PK) and verification key (VK).
- **Verifier decision:** Whether a proof is accepted.

## 3. Adversaries

- **Malicious prover:** Attempts to forge a proof, exploit verifier weaknesses, or bypass public-input validation.
- **Malicious verifier:** Attempts to extract information from proofs/metadata/logging.
- **Network attacker:** Observes, replays, or tampers with proof artifacts stored/transmitted (e.g., via IPFS).
- **Supply-chain attacker:** Compromises the Groth16 binary, build toolchain, or dependencies.

## 4. Trust Assumptions

### Common assumptions
- SHA-256 is collision-resistant for commitments/hashes used by the MVP circuit.
- Canonicalization functions are deterministic and stable across platforms.

### Groth16 backend assumptions
- The Rust backend uses a correct and reviewed Groth16 implementation.
- Proof/verification key material is generated securely and managed correctly.
- The Groth16 binary invoked is the intended one (not replaced/tampered).

## 5. Attack Surfaces and Failure Modes

### 5.1 Simulation backend misuse
- **Failure mode:** Treating simulated proofs as real zkSNARKs.
- **Impact:** Privacy and soundness are illusory; proofs can be forged or leak information.
- **Mitigation:** Docs label simulation as non-secure; production flows require explicit Groth16 opt-in.

### 5.2 Public input confusion / substitution
- **Failure mode:** Verifier accepts a proof under mismatched or malformed public inputs.
- **Impact:** Statement-binding breaks (proof may be accepted for the “wrong” theorem/commitment).
- **Mitigation:** Strict `public_inputs` schema validation and fail-safe verifier behavior.

### 5.3 Witness/statement inconsistency
- **Failure mode:** Prover provides non-canonical or inconsistent witness fields.
- **Impact:** In a real backend, could lead to subtle statement-binding bugs or verification mismatches.
- **Mitigation:** Strict, fail-closed constraint evaluation (`MVPCircuit.verify_constraints`).

### 5.4 Trusted setup compromise (Groth16)
- **Failure mode:** Toxic waste retained or adversarially generated parameters.
- **Impact:** Potential to forge proofs or break soundness.
- **Mitigation:** Documented ceremony expectations; checksum/attestation; multi-party setup where feasible.

### 5.5 Binary tampering / wrong binary execution
- **Failure mode:** Running a compromised or unexpected Groth16 binary.
- **Impact:** Proofs may be invalid, privacy may be compromised, or verification may be bypassed.
- **Mitigation:** Prefer local builds, explicit binary overrides, and deterministic test vectors.

### 5.6 Denial of service
- **Failure mode:** Extremely large proofs or pathological inputs cause slowdowns.
- **Impact:** Resource exhaustion.
- **Mitigation:** Backend-aware proof size bounds; input validation; timeouts at subprocess boundaries.

## 6. Security Recommendations

- Keep **simulation** as the default backend; require explicit enablement for Groth16.
- Treat `security_level` as **policy metadata**, not a guarantee.
- Prefer **fail-closed** behavior on any parsing/validation error.
- Log carefully: avoid logging private axioms/witnesses.
- For Groth16, plan for artifact lifecycle (PK/VK storage, integrity checks, rotation).

## 7. Open Questions

- Exact circuit semantics for “legal theorem holds” (P7).
- End-to-end artifact distribution + verification policy (P6/P11).
- Golden vectors and compatibility guarantees across circuit versions (P8/P10).

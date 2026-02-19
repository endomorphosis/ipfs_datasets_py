# logic/zkp — Comprehensive Improvement & Refactoring Master TODO

**Last Updated:** 2026-02-18 (Phase 1–2 Complete)  
**Purpose:** Single source of truth for all ZKP module improvements, from immediate safety/correctness fixes through production Groth16 integration.

---

## Current State Snapshot (Post-Phase 2)

- **Simulation backend:** fully functional, demo-only, warn-on-use ✅
- **Backend architecture:** phase A complete (registry + lazy loading + groth16 stub) ✅
- **Canonicalization:** deterministic text normalization + commitment generation ✅
- **Theorem hashing:** simulated backend uses canonicalization for stable `theorem_hash` ✅
- **Caching:** cache keys are canonicalized (whitespace/unicode invariant) ✅
- **Public inputs:** standardized schema across simulated + groth16-ffi ✅
- **Verifier input validation:** enforces standardized `public_inputs` (backend-agnostic) ✅
- **Verifier proof-size validation:** backend-aware bounds (simulated strict; Groth16 allows larger) ✅
- **Statement/Witness:** dataclass-based format with field encoding ✅
- **Witness Manager:** generation, validation, consistency checking ✅
- **Groth16 backend:** Rust FFI adapter is opt-in (fail-closed by default) ✅
  - Enable with `IPFS_DATASETS_ENABLE_GROTH16=1`
  - Canonical Rust project location (this repo layout): `ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/`
  - Alternate/legacy location may exist (older docs): `./groth16_backend/`
  - Binary discovery prefers: `ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/target/release/groth16`
- **Test suite:** extensive and mostly self-contained.
  - Property-based tests use `hypothesis` (install in dev/test env).
  - Prefer documenting *how to run* tests over hard-coding exact counts.
- **Import safety:** passing (no heavy deps on import) ✅
- **Docs:** README updated to accurate descriptions ✅

### How to run tests (authoritative)

- From `complaint-generator/ipfs_datasets_py`:
  - `python -m pytest -q tests/unit_tests/logic/zkp`

---

## Workstreams (keep this “infinite”)

1) **Correctness + contracts** (public inputs, hashes, serialization, robustness)
2) **Backend architecture** (protocol, registry, lazy imports, dependency gating)
3) **Determinism + canonicalization** (stable hashing, cache behavior, golden vectors)
4) **Real ZKP track** (Groth16/PLONK/Halo2, setup artifacts, VK/PK lifecycle)
5) **Integration track** (EVM verifier, IPFS artifact storage, operational policy)
6) **Docs + examples** (truthful simulation docs, runnable examples, clear upgrade path)

---

## P0 — Safety / Correctness / Immediate Bugs

### P0.1 ✅ Logger import bug in verifier
- [x] Fixed: added `import logging` + `logger = logging.getLogger(__name__)` to `zkp_verifier.py`
- [x] Test added: `test_malformed_proof_rejected_without_crash` ensures no crash on invalid input

### P0.2 ✅ Doc truth alignment
- [x] README updated: removed "128-bit security" claim for simulation, accurate proof sizes
- [x] Docstrings updated: clarified "simulation-only" in prover/verifier class docs
- [x] Test command path fixed in README

### P0.3 ✅ Wire groth16 backend as fail-closed
- [x] Created `backends/groth16.py` stub that raises clear `ZKPError`
- [x] Backend selection tests: verify unknown backends and groth16 fail gracefully

---

## P1 — API Contracts & Behavioral Tests

### P1.1 ✅ Backend selection interface
- [x] Added `ZKPProver(backend="simulated")` and `ZKPVerifier(backend="simulated")`
- [x] Default remains `"simulated"` (safe, stable)
- [x] Unknown backends raise `ZKPError` at init

### P1.2 ✅ Warning policy (warn-on-use, not on import)
- [x] Verified: `import ipfs_datasets_py.logic.zkp` emits no warnings
- [x] Test passing: `tests/unit_tests/logic/zkp/test_optional_dependencies.py` ensures import quietness

### P1.3 ✅ Determinism policy for simulated proofs
- [x] Decision: Witness-based determinism for MVP circuit
- [x] Implemented: `WitnessManager.generate_witness()` produces deterministic witnesses
- [x] Test: witness generation with same axioms (different order) produces same commitment
- [x] Documented: axiom canonicalization ensures order-independence

### P1.4 ✅ Proof serialization contract (round-trip stability)
### P1.5 ✅ De-duplicate backend protocol definitions
- [x] Single source of truth: protocol defined in `backends/__init__.py`
- [x] Backward compatible: `backends/backend_protocol.py` is a re-export

**Acceptance:** There is exactly one backend protocol definition used by all backends + tests.

- [x] Tests added:
  - `test_proof_serialization_preserves_fields`: ZKPProof.to_dict() round-trip
  - `test_proof_dict_hex_encoding_stability`: hex encoding reversibility
  - Serialization tests validate all fields preserved

### P1.6 ✅ Canonicalized caching (whitespace/unicode invariant)
- [x] Cache keys use `canonicalize_theorem()` and `canonicalize_axioms()`
- [x] Cache hits return a proof whose `public_inputs["theorem"]` matches the current call

**Acceptance:** whitespace-only variations of the same theorem hit cache and do not leak a stale theorem string.

---

## P2 — Simulation Quality & Robustness

### P2.1 ✅ Verifier robustness (reject malformed inputs gracefully)
- [x] Test: `test_malformed_proof_rejected_without_crash`
- [x] Verifier returns `False` (not raises) for invalid proof objects
- [x] Stats tracking increments `proofs_rejected`

### P2.2 ✅ Strengthen verifier checks (still simulated)
- [x] Validation in simulated backend:
  - check `public_inputs` has required keys (`theorem`, `theorem_hash`) ✅
  - check proof data size bounds (100–300 bytes) ✅
  - check metadata sanity (`proof_system` field exists) ✅
- [x] Tests:
  - `test_verifier_rejects_missing_public_inputs`
  - `test_verifier_rejects_inconsistent_theorem_hash`
  - `test_verifier_rejects_proof_with_bad_metadata`

### P2.3 ✅ Make simulated proof structure more explicit
- [x] Add detailed comments in `backends/simulated.py` explaining byte ranges
- [x] Optional: add tagged fields for clarity

### P2.4 ✅ Standardize public inputs across backends
- [x] Enforced schema for `public_inputs` across backends:
  - required: `theorem` (as-provided string)
  - required: `theorem_hash` (canonicalized 32-byte hex)
  - preferred: `axioms_commitment` (32-byte hex)
  - preferred: `circuit_version` (non-negative int)
  - preferred: `ruleset_id` (non-empty str)
- [x] Verified Groth16 FFI adapter emits the same key names
- [x] Verifier validates the schema before delegating to backend verification

**Acceptance:** verifier/tests do not need backend-specific conditionals for key names.

---

## P3 — Circuit & Statement Design (Foundation for Real ZKP)

### P3.1 ✅ Canonicalization module
- [x] Created `logic/zkp/canonicalization.py`:
  - `normalize_text(text: str) -> str`: Unicode NFD + whitespace normalization
  - `canonicalize_theorem(text: str) -> str`: normalized theorem
  - `canonicalize_axioms(axioms: List[str]) -> List[str]`: sorted + deduplicated
  - `hash_theorem(text: str) -> bytes`: SHA256 of theorem
  - `hash_axioms_commitment(axioms: List[str]) -> bytes`: SHA256 of sorted axioms (order-independent)
- [x] Tests:
  - reordering axioms → same commitment ✅
  - whitespace variations → same commitment ✅
  - Unicode normalization → stable ✅
  - deduplication + sorting ✅

### P3.2 ✅ Define minimal MVP statement format
- [x] Implemented in `logic/zkp/statement.py`:
  - `Statement(theorem_hash, axioms_commitment, circuit_version, ruleset_id)`
  - Example: prove "I know axioms whose commitment = X and theorem hash = Y"
- [x] Fields:
  - `theorem_hash`: SHA256 of canonical theorem
  - `axioms_commitment`: SHA256 of sorted canonical axioms
  - `circuit_version`: uint (MVP=1)
  - `ruleset_id`: identifier (e.g., "TDFOL_v1")

### P3.3 ✅ Define private witness format
- [x] Implemented in `logic/zkp/statement.py`:
  - `Witness(axioms, intermediate_steps, axioms_commitment_hex, circuit_version, ruleset_id)`
  - Confidentiality: axioms never leave prover
  - Optional: intermediate proof steps for auditing
- [x] Examples + docstrings complete

---

## P4 — Backend Expansion (Phase B: MVP Circuit)

### P4.1 ✅ Implement knowledge-of-axioms circuit (non-cryptographic first)
- [x] Created `circuits.py` with `MVPCircuit`:
  - `class MVPCircuit`: represents "prove knowledge of axioms" constraints
  - `compile()`: outputs JSON schema describing circuit structure
  - `num_inputs()`: 4 (theorem_hash, axioms_commitment, version, ruleset_id)
  - `num_constraints()`: 1 (commitment verification)
- [x] Tests: circuit schema is deterministic, serializable

### P4.2 ✅ Create witness generation for MVP circuit
- [x] Created `logic/zkp/witness_manager.py`:
  - `WitnessManager.generate_witness(axioms, theorem, ...)`: generates witness
  - Returns: `Witness` with canonicalized axioms + commitment
  - Witness validated against expected values
- [x] Tests:
  - witness generation (basic, deduplication, sorting) ✅
  - witness validation (structure, axiom count, commitment consistency) ✅
  - proof statement creation (includes theorem hash + axioms commitment) ✅
  - witness-statement consistency ✅
  - caching behavior ✅

### P4.3 ✅ Integrate MVP circuit witness verification
- [x] Added: `WitnessManager.verify_witness_consistency(witness, statement)`
- [x] Checks: commitment match, version match, ruleset match
- [x] Full circuit verification (constraint checking)
  - Implemented: `MVPCircuit.verify_constraints(witness, statement)` (strict, fail-closed)
  - Tests: `TestMVPCircuitConstraintEvaluation` in `tests/unit_tests/logic/zkp/test_witness_manager.py`

---

## P5 — Real Groth16 Backend (Phase C–D)

### P5.1 ✅ Select & evaluate Groth16 prover stack
- [x] Decision: repo-supported path is Rust Groth16 backend (opt-in) under `processors/groth16_backend/`
- [x] Policy: fail-closed by default; enable via `IPFS_DATASETS_ENABLE_GROTH16=1`
- [x] Rationale document in GROTH16_IMPLEMENTATION_PLAN.md section 8

### P5.2 ✅ Implement trusted setup ceremony (circuit-specific)
- [x] For MVP circuit v1: run setup → PK + VK (Rust CLI: `groth16 setup --version <n>`)
- [x] Emit JSON manifest including `vk_hash_hex` (SHA256 of canonical VK bytes)
- [x] Reproducibility test: seeded setup produces stable `vk_hash_hex`
- [x] Artifact storage: store PK/VK in IPFS and record `proving_key_cid` / `verifying_key_cid` (see `logic/zkp/setup_artifacts.py`, unit test: `tests/unit_tests/logic/zkp/test_setup_artifacts_ipfs.py`)
- [ ] On-chain registry: register `vk_hash_hex` on-chain (see P6)

### P5.3 ✅ Implement proof generation (real Groth16; opt-in)
- [x] `Groth16Backend.generate_proof()` implemented (gated) in `logic/zkp/backends/groth16.py` delegating to Rust FFI in `logic/zkp/backends/groth16_ffi.py`
- [x] Prover invocation: load PK, build witness, invoke Rust binary, validate proof output schema
- [x] Integration coverage: gated end-to-end prove→verify test in `tests/unit_tests/logic/zkp/test_zkp_integration.py`

### P5.4 ✅ Implement proof verification (real Groth16; opt-in)
- [x] `Groth16Backend.verify_proof()` implemented (gated) in `logic/zkp/backends/groth16.py` delegating to Rust FFI in `logic/zkp/backends/groth16_ffi.py`
- [x] Verifier invocation: load VK, invoke Rust verifier, validate error envelope / proof schema
- [x] Integration coverage: gated end-to-end prove→verify test in `tests/unit_tests/logic/zkp/test_zkp_integration.py`

### P5.5 ✅ Circuit versioning + registration (off-chain)
- [x] Registry: (circuit_id, version) → VK hash (see `logic/zkp/vk_registry.py`)
- [x] Support multiple versions concurrently (unit-tested)

---

## P6 — On-Chain Integration (EVM)

### P6.1 ⏳ Generate Solidity verifier contract
- [ ] Decide reproducible generator path (e.g., from `verifying_key.bin` → Solidity) and document exact command(s)
- [ ] Generate a circuit-versioned verifier contract from VK, and embed a constant `vk_hash_hex`/`vk_hash` for runtime self-checks
- [ ] Define ABI: accept `(proof, public_inputs, circuit_version)` → `bool`
- [ ] Add at least one end-to-end check (local EVM) proving that a proof generated by the Rust backend verifies on-chain
- [ ] Note: `processors/groth16_backend/contracts/GrothVerifier.sol` exists as a prototype and is not authoritative until validated end-to-end

### P6.2 ⏳ Implement contract registry for VK + policy
- [ ] On-chain: mapping(circuitId → mapping(version → VKRegistry))
- [ ] Admin: registerVK(), deprecateVK()

### P6.3 ⏳ Integration harness (off-chain → on-chain)
- [ ] Define on-chain encoding for `public_inputs` (current Groth16 wire vectors include non-field strings like `ruleset_id`)
- [ ] Python: generate → pack ABI args → submit → verify on-chain
- [ ] Keep harness dependency-light (unit tests should not require a live chain)

---

## P7 — Legal Theorem Semantics (Phase E: Real Use Case)

### P7.1 ⏳ Define "legal theorem" constraint system
- [ ] Choose logic: TDFOL, CEC, or simpler
- [ ] Document: what "theorem holds" means formally

### P7.2 ⏳ Compile legal theorems to arithmetic circuits
- [ ] Theorem + axioms → R1CS

### P7.3 ⏳ Threat model for legal proofs
- [ ] Document: adversary capabilities, protections, failure modes

---

## P8 — Testing Strategy (Multi-Phase)

### P8.1 ✅ Unit tests (core logic)
- [x] Backend selection ✅
- [x] Malformed proof handling ✅
- [x] Import quietness ✅
- [x] Canonicalization ✅
- [x] Witness generation & validation ✅
- [x] Serialization round-trip ✅

### P8.2 ✅ Property-based tests
- [x] Ensure `hypothesis` is installed in dev/test environments.
- [x] Random axiom orderings → same commitment
- [x] Invalid proofs → verification fails
- [x] Proof size stability

**Implementation:** `tests/unit_tests/logic/zkp/test_zkp_properties.py`

### P8.3 ✅ Integration tests (gated, opt-in)
- [x] Added opt-in Groth16 end-to-end prove→verify test
- [x] Gate conditions:
  - `IPFS_DATASETS_ENABLE_GROTH16=1` (or true/yes)
  - Skip if Groth16 binary is not discoverable

### P8.4 ✅ Golden vectors (regression prevention)
- [x] Stored in `tests/unit_tests/logic/zkp/zkp_golden_vectors.json`
- [x] Fixed test cases: theorem, axioms, expected outputs

**Implementation:** `tests/unit_tests/logic/zkp/test_zkp_golden_vectors.py`

---

## P9 — Documentation & Artifacts

### P9.1 ✅ Update `logic/zkp/README.md`
- [x] Add section: "Production Setup Checklist"
- [x] Example: ephemeral peer workflow

### P9.2 ✅ Keep `IMPROVEMENT_TODO.md` in sync
- [x] Linked to this master todo

### P9.3 ✅ Create `logic/zkp/THREAT_MODEL.md`
- [x] Adversary, assumptions, failure modes

### P9.4 ✅ Create `logic/zkp/SETUP_GUIDE.md`
- [x] Step-by-step: trusted setup, artifact storage, on-chain registration

---

## P10 — Dependency Management & Versioning

### P10.1 ✅ Optional deps for Groth16 (Python + Rust)
- [x] `setup.py` includes a `groth16` extra with `jsonschema>=4.0.0` (used by `logic/zkp/backends/groth16_ffi.py`).
- [x] Install paths:
  - Editable/dev: `pip install -e ".[groth16]"`
  - Wheel/sdist: `pip install ipfs_datasets_py[groth16]`
- [x] Runtime gating remains fail-closed by default; require `IPFS_DATASETS_ENABLE_GROTH16=1`.

### P10.1b ✅ Dev/test dependencies
- [x] `hypothesis` is included in the `test` extra in `setup.py`.
- [x] Install paths:
  - Editable/dev: `pip install -e ".[test]"`
  - Dev from requirements: `pip install -r requirements.txt`

### P10.2 ✅ Version policy for circuits
- [x] Versioning: `circuit_id@v<uint64>` (see `parse_circuit_ref` / `format_circuit_ref` in `logic/zkp/statement.py`).
- [x] Legacy support: accept unversioned circuit IDs via `parse_circuit_ref_lenient` (defaults to v1).
- [x] Backward compat: verifier accepts legacy + versioned circuit refs (optional) and rejects mismatches against `circuit_version`.
- [x] Tests: parsing/formatting edge cases + verifier behavior (`tests/unit_tests/logic/zkp/test_circuit_version_policy.py`).

---

## P11 — Operational Best Practices

### P11.1 ✅ Trusted setup ceremony notes
- [x] Documentation, checksums, multi-party option (see `logic/zkp/SETUP_GUIDE.md`)

### P11.2 ✅ Artifact lifecycle
- [x] IPFS + pinning + HTTPS backup (documented in `logic/zkp/SETUP_GUIDE.md`)

### P11.3 ✅ Monitoring & metrics
- [x] Prove time, verify latency, failure alerts (documented in `logic/zkp/SETUP_GUIDE.md`)

---

## Suggested Implementation Order (Revised)

**Phase 1 (Completed, weeks 0–2):**
- ✅ P0 (Safety/correctness)
- ✅ P1 (API contracts: backend selection, warnings, determinism, serialization)
- ✅ P2 (Verifier robustness)
- ✅ P3.1–3.3 (Canonicalization + statement/witness design)
- ✅ P4.1–4.2 (MVP circuit schema + witness generation)
- ✅ P4.3 (Circuit witness verification — constraint evaluation)

**Phase 2 (Immediate next, weeks 2–4):**
- [x] P4.3 Finalization: full circuit constraint verification
- [x] P8.2 Property-based tests (axiom ordering, proof sizes)
- [x] P8.4 Golden vectors (fixed regression test cases)
- [x] P9.1 README updates (setup guide, examples)

**Phase 3 (Real ZKP, weeks 4–10):**
- [ ] P5 (Groth16 stack selection + implementation)
- [x] P8.3 Integration tests (gated, opt-in; local binary prove→verify)
- [ ] Add separate local-chain e2e test(s) (prove → on-chain verify) when EVM verifier work lands

**Phase 4 (Production, weeks 10–20):**
- [ ] P6 (On-chain verifier + registry)
- [ ] P7 (Legal theorem semantics)
- [ ] P9.3–4, P10–11 (Threat model, docs, operations)

---

## Dependencies / Blockers

- **Phase 1 ↔ Phase 2:** None; independent
- **Phase 2 → Phase 3:** MVP circuit finalized before real Groth16
- **Phase 3 → Phase 4:** Working Groth16 before on-chain
- **Production → Legal semantics:** Circuit design before legal semantics

---

## Success Criteria (Exit Gates)

- ✅ All P0 items done
- ✅ P1–3 interfaces stable + tested
- ✅ P4 MVP circuit compiling + witness generating
- [ ] P5 Groth16 off-chain + golden vectors
- [ ] P6 End-to-end on test chain
- [ ] P7 With threat model
- [ ] P8–11 Complete

---

## Recent Sessions Summary

1. **Session 2026-02-18 (Current):**
   - Phase 1–2 baseline complete + follow-ups:
     - Canonicalized theorem hashing + canonicalized prover caching
     - Standardized `public_inputs` across backends + verifier enforcement
     - Groth16 Rust FFI backend is opt-in (fail-closed by default)
     - Groth16 proof metadata carries `security_level` (unblocks verifier security gate)
     - Groth16 binary discovery updated to prefer `ipfs_datasets_py/processors/groth16_backend/`
     - Added gated Groth16 end-to-end test (env+binary presence)
   - Test verification: run `python -m pytest -q tests/unit_tests/logic/zkp`

---

## Notes

- This is a **living document**; updated 2026-02-18
- "⏳" means not started; "✅" means complete.
- Phases can overlap; use as guide, not strict waterfall.
- For each item, write a test as soon as interface is clear.
- **Key Achievement:** Witness-based determinism enables reproducible golden vectors later.

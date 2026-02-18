# logic/zkp — Comprehensive Improvement & Refactoring Master TODO

**Last Updated:** 2026-02-18 (Phase 1–2 Complete)  
**Purpose:** Single source of truth for all ZKP module improvements, from immediate safety/correctness fixes through production Groth16 integration.

---

## Current State Snapshot (Post-Phase 1)

- **Simulation backend:** fully functional, demo-only, warn-on-use ✅
- **Backend architecture:** phase A complete (registry + lazy loading + groth16 stub) ✅
- **Canonicalization:** deterministic text normalization + commitment generation ✅
- **Statement/Witness:** dataclass-based format with field encoding ✅
- **Witness Manager:** generation, validation, consistency checking ✅
- **Unit tests:** 129 passing total:
  - 24 canonicalization tests
  - 22 witness manager tests
  - 22 ZKP module tests (including serialization + verifier robustness)
  - 30+ integration + edge case + performance tests
  - 1 import quiet regression test
- **Import safety:** passing (no heavy deps on import) ✅
- **Docs:** README updated to accurate descriptions ✅

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
- [x] Test passing: `test_logic_zkp_import_quiet.py` ensures import quietness

### P1.3 ✅ Determinism policy for simulated proofs
- [x] Decision: Witness-based determinism for MVP circuit
- [x] Implemented: `WitnessManager.generate_witness()` produces deterministic witnesses
- [x] Test: witness generation with same axioms (different order) produces same commitment
- [x] Documented: axiom canonicalization ensures order-independence

### P1.4 ✅ Proof serialization contract (round-trip stability)
- [x] Tests added:
  - `test_proof_serialization_preserves_fields`: ZKPProof.to_dict() round-trip
  - `test_proof_dict_hex_encoding_stability`: hex encoding reversibility
  - Serialization tests validate all fields preserved

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

### P2.3 ⏳ Make simulated proof structure more explicit
- [ ] Add detailed comments in `backends/simulated.py` explaining byte ranges
- [ ] Optional: add tagged fields for clarity

---

## P3 — Circuit & Statement Design (Foundation for Real ZKP)

### P3.1 ✅ Canonicalization module
- [x] Created `logic/zkp/canonicalization.py`:
  - `normalize_text(text: str) -> str`: Unicode NFD + whitespace normalization
  - `canonicalize_theorem(text: str) -> str`: normalized theorem
  - `canonicalize_axioms(axioms: List[str]) -> List[str]`: sorted + deduplicated
  - `hash_theorem(text: str) -> bytes`: SHA256 of theory
  - `hash_axioms_commitment(axioms: List[str]) -> bytes`: SHA256 of sorted axioms (order-independent)
- [x] Tests (24 total):
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
- [x] Tests (22 total):
  - witness generation (basic, deduplication, sorting) ✅
  - witness validation (structure, axiom count, commitment consistency) ✅
  - proof statement creation (includes theorem hash + axioms commitment) ✅
  - witness-statement consistency ✅
  - caching behavior ✅

### P4.3 ⏳ Integrate MVP circuit witness verification
- [x] Added: `WitnessManager.verify_witness_consistency(witness, statement)`
- [x] Checks: commitment match, version match, ruleset match
- [ ] TODO: Full circuit verification (constraint checking)
  - Need: evaluate constraints over witness values
  - Depends on: constraint specification finalization

---

## P5 — Real Groth16 Backend (Phase C–D)

### P5.1 ⏳ Select & evaluate Groth16 prover stack
- [ ] Research options → select stack
- [ ] Decision: which (py_ecc vs. external vs. Rust FFI)
- [ ] Rationale document in GROTH16_IMPLEMENTATION_PLAN.md section 8

### P5.2 ⏳ Implement trusted setup ceremony (circuit-specific)
- [ ] For MVP circuit v1:
  - Run setup → PK + VK
  - Store PK in IPFS, VK hash on-chain
- [ ] Reproducibility test

### P5.3 ⏳ Implement proof generation (real Groth16)
- [ ] `Groth16Backend.generate_proof()`: full Groth16 prover
- [ ] Load PK, compile witness, invoke prover
- [ ] Return proof + public inputs

### P5.4 ⏳ Implement proof verification (real Groth16)
- [ ] `Groth16Backend.verify_proof()`: full Groth16 verifier
- [ ] Load VK, verify proof deterministically

### P5.5 ⏳ Circuit versioning + registration
- [ ] Registry: (circuit_id, version) → VK hash
- [ ] Support multiple versions concurrently

---

## P6 — On-Chain Integration (EVM)

### P6.1 ⏳ Generate Solidity verifier contract
- [ ] From VK → Solidity contract template
- [ ] Accept (proof, public_inputs, circuit_version) → bool

### P6.2 ⏳ Implement contract registry for VK + policy
- [ ] On-chain: mapping(circuitId → mapping(version → VKRegistry))
- [ ] Admin: registerVK(), deprecateVK()

### P6.3 ⏳ Integration harness (off-chain → on-chain)
- [ ] Python: generate → submit → verify on-chain

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

### P8.2 ⏳ Property-based tests
- [ ] Random axiom orderings → same commitment
- [ ] Invalid proofs → verification fails
- [ ] Proof size stability

### P8.3 ⏳ Integration tests (gated, opt-in)
- [ ] Env flag: `ZKP_INTEGRATION_TESTS=1`
- [ ] Or pytest marker: `@pytest.mark.integration`
- [ ] Tests: setup → prove → verify flow

### P8.4 ⏳ Golden vectors (regression prevention)
- [ ] Stored in `tests/zkp_golden_vectors.json`
- [ ] Fixed test cases: theorem, axioms, expected outputs

---

## P9 — Documentation & Artifacts

### P9.1 ⏳ Update `logic/zkp/README.md`
- [ ] Add section: "Production Setup Checklist"
- [ ] Example: ephemeral peer workflow

### P9.2 ✅ Keep `IMPROVEMENT_TODO.md` in sync
- [x] Linked to this master todo

### P9.3 ⏳ Create `logic/zkp/THREAT_MODEL.md`
- [ ] Adversary, assumptions, failure modes

### P9.4 ⏳ Create `logic/zkp/SETUP_GUIDE.md`
- [ ] Step-by-step: trusted setup, artifact storage, on-chain registration

---

## P10 — Dependency Management & Versioning

### P10.1 ⏳ Pin Groth16 stack versions
- [ ] `pip install ipfs_datasets_py[groth16]`

### P10.2 ⏳ Version policy for circuits
- [ ] Versioning: `circuit_id@v<uint64>`
- [ ] Backward compat: old versions stay verifiable

---

## P11 — Operational Best Practices

### P11.1 ⏳ Trusted setup ceremony notes
- [ ] Documentation, checksums, multi-party option

### P11.2 ⏳ Artifact lifecycle
- [ ] IPFS + pinning + HTTPS backup

### P11.3 ⏳ Monitoring & metrics
- [ ] Prove time, verify latency, failure alerts

---

## Suggested Implementation Order (Revised)

**Phase 1 (Completed, weeks 0–2):**
- ✅ P0 (Safety/correctness)
- ✅ P1 (API contracts: backend selection, warnings, determinism, serialization)
- ✅ P2 (Verifier robustness)
- ✅ P3.1–3.3 (Canonicalization + statement/witness design)
- ✅ P4.1–4.2 (MVP circuit schema + witness generation)
- ⏳ P4.3 (Circuit witness verification — constraint evaluation)

**Phase 2 (Immediate next, weeks 2–4):**
- [ ] P4.3 Finalization: full circuit constraint verification
- [ ] P8.2 Property-based tests (axiom ordering, proof sizes)
- [ ] P8.4 Golden vectors (fixed regression test cases)
- [ ] P9.1 README updates (setup guide, examples)

**Phase 3 (Real ZKP, weeks 4–10):**
- [ ] P5 (Groth16 stack selection + implementation)
- [ ] P8.3 Integration tests (prove → verify on local chain)

**Phase 4 (Production, weeks 10–20):**
- [ ] P6 (On-chain verifier + registry)
- [ ] P7 (Legal theorem semantics)
- [ ] P9.3–4, P10–11 (Threat model, docs, operations)

---

## Dependencies / Blockers

- **Phase 1 ↔ Phase 2:** None; independent
- **Phase 2 → Phase 3:** MVP circuit finalized before real Groth16
- **Phase 3 → Phase 4:** Working Groth16 before on-chain
- **Phase 4 → Phase 5:** Circuit design before legal semantics

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
   - Completed Phase 1 + Phase 2 implementation
   - Created: canonicalization.py (6 functions, 24 tests)
   - Created: witness_manager.py (5 functions, 22 tests)
   - Enhanced: statement.py (added metadata to Witness/ProofStatement)
   - Enhanced: circuits.py (added MVPCircuit class)
   - Enhanced: backends/simulated.py (strengthened verifier validation)
   - Test result: 129 total tests passing
   - Phase 1 & 2 substantially complete; Phase 3 (Groth16) to begin

---

## Notes

- This is a **living document**; updated 2026-02-18
- "⏳" means not started; "✅" means complete.
- Phases can overlap; use as guide, not strict waterfall.
- For each item, write a test as soon as interface is clear.
- **Key Achievement:** Witness-based determinism enables reproducible golden vectors later.

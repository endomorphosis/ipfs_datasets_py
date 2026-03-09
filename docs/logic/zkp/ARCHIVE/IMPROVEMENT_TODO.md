# `logic/zkp` — Infinite Improvement TODO (Simulation → Production Roadmap)

**Status:** Simulation/Demo only (not cryptographically secure)  
**Last Reviewed:** 2026-02-18  
**Documentation Refactoring:** Complete (16 → 9 active files)

⚡ **Master TODO:** See `TODO_MASTER.md` for comprehensive, phase-by-phase tasks (current state, P0–P11 breakdown, implementation order, success criteria).

This file documents high-level principles and non-negotiable invariants.

The current `ipfs_datasets_py.logic.zkp` package is intentionally a **simulation** that demonstrates workflows and API shapes. It is not a real ZKP system.

---

## Non-Negotiable Invariants (Must Always Hold)

- **Import quietness:** `import ipfs_datasets_py.logic.zkp` must not emit warnings.
- **Warn-on-use only:** A simulation warning may be emitted on first actual API usage (e.g., constructing `ZKPProof`, accessing `ZKPProver`).
- **No heavy deps on import:** importing `logic.zkp` must not import optional crypto stacks.
- **Verifier robustness:** malformed/foreign proof objects must be rejected (`False`) rather than crashing.
- **Serialization contract:** `ZKPProof.to_dict()` and `ZKPProof.from_dict()` must round-trip.
- **Simulation honesty:** docs must not claim cryptographic security for the simulated backend.
- **Test dependencies:** property-based tests require `hypothesis` in dev/test environments.
- **Canonicalization invariants:** `theorem_hash` must be stable under whitespace/unicode variations.
- **Caching invariants:** cache keys must be stable under canonicalization (and must not return stale `theorem` strings on cache hits).

---

## P0 — Correctness / Safety / Doc Truth

### P0.1 Fix verifier robustness footguns
- [ ] Ensure `ZKPVerifier._validate_proof_structure()` never raises due to logging or missing attributes.
- [ ] Add a regression test: verifying a malformed proof object returns `False` (and increments `proofs_rejected`) rather than raising.

**Acceptance:** A minimal dummy object (missing fields) passed into `verify_proof()` returns `False`.

### P0.2 Make `README.md` truthfully simulation-first
- [ ] Remove/replace claims like “128-bit security” for the simulated backend.
- [ ] Align documented proof size with implementation/tests (currently ~160 bytes simulated).
- [ ] Fix testing command paths to match actual repo layout.

**Acceptance:** The ZKP README does not claim cryptographic security unless explicitly describing a future/alternate production backend.

### P0.3 Audit misleading docstrings
- [ ] Update `ZKPProver` / `ZKPVerifier` docstrings that use “cryptographic” phrasing to clearly state “simulated”.

**Acceptance:** Module/class docstrings consistently disclaim simulation-only behavior.

---

## P1 — API Contracts & Behavioral Tests

### P1.1 Define and enforce the public API surface
- [ ] Decide whether `ZKPProver` / `ZKPVerifier` remain primary names, or whether `SimulatedZKPProver` / `SimulatedZKPVerifier` should be the encouraged names.
- [ ] If “Simulated*” are preferred, update docs to use them while keeping `ZKP*` as backward-compatible aliases.

**Acceptance:** README examples match the “preferred” names, and the aliases remain supported.

### P1.2 Warning policy tests
- [ ] Add/extend tests:
  - importing `logic.zkp` emits no warnings
  - first access of `ZKPProver` (or proof construction) emits exactly one `UserWarning`

**Acceptance:** Warn-on-use behavior is deterministic and regression-protected.

### P1.3 Determinism policy (be explicit)
The simulated prover currently mixes deterministic hashing with random bytes.
- [ ] Decide: should the simulated proof be deterministic by default?
  - Option A: deterministic proof bytes (stable snapshots / golden tests)
  - Option B: randomized proof bytes (more realistic shape), but deterministic metadata/size
- [ ] Add tests that enforce the chosen behavior.

**Acceptance:** The determinism policy is documented and tested.

---

## P2 — Simulation Quality Improvements (Still Not Crypto-Secure)

- [ ] Make proof structure more explicit (e.g., tagged fields for “A/B/C” components) while keeping `ZKPProof` wire format stable.
- [ ] Strengthen verifier checks (still simulated):
  - required public inputs keys
  - consistent `theorem_hash`
  - metadata sanity (e.g., `proof_system` string)

**Acceptance:** Verifier rejects obviously inconsistent simulated proofs reliably.

---

## P3 — Production Backend Track (Real ZKP)

This is a separate backend, not a “small patch”.

**Implementation plan:** see `logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md`.

### P3.1 Architecture: pluggable backends
- [ ] Define a backend protocol (e.g., `ZKBackend.generate_proof(...)` / `verify_proof(...)`).
- [ ] Keep simulation as the default backend.

### P3.2 Implement a real zkSNARK backend
- [ ] Evaluate targets: Groth16 (py_ecc), PLONK, Halo2 wrappers.
- [ ] Add dependency gating so production backend is optional.
- [ ] Add a trusted setup workflow (if applicable) with safe file handling.

### P3.3 Circuit compilation
- [ ] Define a real circuit representation.
- [ ] Provide a compilation pipeline from logic constraints → arithmetic circuit.

---

## P4 — Docs & Examples

- [ ] Add a short “Simulation vs Production” section at top of README.
- [ ] Ensure all example code paths exist and tests referenced are real.
- [ ] Add a minimal “threat model” section:
  - what is protected (axioms)
  - what is public (theorem, proof)
  - what simulation does *not* guarantee

---

## P5 — Performance & Monitoring

- [ ] Provide consistent timing stats fields (prover/verifier) and document them.
- [ ] Add micro-benchmark tests only if they are stable and non-flaky (otherwise keep as scripts).

---

## Always-On Checklist (Before Any Merge)

- [ ] Import `logic.zkp` is warning-quiet.
- [ ] No new heavy optional deps imported at module import-time.
- [ ] Verifier rejects malformed inputs without raising.
- [ ] README is honest about simulation-only security.

---

## Recent Updates (2026-02-18)

### Documentation Refactoring Complete ✅
- **Archived:** 7 redundant status/completion documents (2,887 lines) to ARCHIVE/
- **Active docs:** Reduced from 16 → 9 markdown files
- **README.md:** Fixed misleading "PRODUCTION READY" → "EDUCATIONAL SIMULATION"
- **Navigation:** Added comprehensive documentation guide to README
- **Duplication:** Eliminated ~30-40% duplicate content
- **P0.2:** Mostly complete - README now accurately describes simulation-only nature

### P0 Status Summary
- **P0.1** (Verifier robustness): Test exists, implementation needs verification
- **P0.2** (README truth): ✅ COMPLETE - Status changed, warnings added
- **P0.3** (Docstring audit): Needs review - check for misleading "cryptographic" claims

### Current State
- **Code:** simulation backend + canonicalization + witness manager + backend gating
- **Docs:** Clean, accurate, well-organized (9 active + 5 analysis + 10 archived)
- **Status:** Module is functional educational simulation, NOT cryptographically secure
- **Roadmap:** See PRODUCTION_UPGRADE_PATH.md for Groth16 implementation plan

### How to validate locally
- From `complaint-generator/ipfs_datasets_py`: run `python -m pytest -q tests/unit_tests/logic/zkp`
- Property tests require `hypothesis` in the active dev/test environment

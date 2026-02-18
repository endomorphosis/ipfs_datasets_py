# groth16_backend — Comprehensive Refactor / Improvement TODO (living doc)

**Scope:** `ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/` (Rust Groth16 CLI + library used via Python subprocess/FFI).

**Goal:** Make the Rust backend easy to build, deterministic, testable, versioned, and safely consumable by Python callers (and legacy callers that still assume older paths).

---

## 0) Ground rules / invariants (don’t break)

- The Python side treats the Rust binary as **untrusted I/O**: it must fail-closed on errors and never silently accept malformed witness/proof.
- CLI remains stable enough for Python wrapper:
  - `groth16 prove --input /dev/stdin --output /dev/stdout`
  - `groth16 verify --proof /dev/stdin`
- Output must remain JSON (machine readable), with a documented error envelope.
- Keep binary discovery backward compatible:
  - Current repo layout: `ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/target/release/groth16`
  - Legacy layouts: `ipfs_datasets_py/processors/...` and `<repo-root>/groth16_backend/...`

---

## P0 — Correctness / Safety (highest priority)

1. Define a strict JSON schema for witness input and proof output.
2. Implement structured error responses (JSON) consistently for all failure modes:
   - parse errors
   - constraint system errors
   - proving errors
   - verification errors
   - unsupported circuit versions
3. Make CLI exit codes contractually stable:
   - `0` success / valid
   - `1` invalid (verification only)
   - `2` operational error
4. Add input validation + bounds checks in Rust:
   - max witness sizes
   - max axiom count
   - max string length
5. Ensure the circuit’s public inputs match Python’s expected `public_inputs` layout.

---

## P1 — Determinism & Reproducibility

1. Ensure proving is deterministic when given the same witness (or explicitly document randomness requirements).
2. If randomness is required:
   - accept explicit RNG seed via CLI flag/env for tests
   - never log sensitive material
3. Ensure canonicalization assumptions are aligned with Python:
   - any normalization MUST happen in Python *or* be duplicated identically in Rust (pick one and document it).

---

## P2 — API design (Rust library + CLI)

1. Separate CLI from library cleanly:
   - `lib.rs` exposes `prove(witness) -> proof` and `verify(proof) -> bool`
   - `main.rs` is thin glue
2. Introduce versioned structs:
   - `WitnessV1`, `ProofV1`, `ErrorEnvelopeV1`
3. Document the wire format (JSON) in one place and keep it authoritative.

---

## P3 — Performance & Resource controls

1. Add timeouts / early exits on pathological inputs.
2. Avoid excessive allocations in parsing and serialization.
3. Consider streaming JSON parsing if witness gets large.
4. Make constraint generation measurable:
   - emit timings behind a `--verbose`/`RUST_LOG` flag

---

## P4 — Trusted setup / key management

1. Decide where proving/verification keys live:
   - repo-local artifacts
   - downloadable artifacts
   - embedded VK, external PK
2. Version the setup artifacts by:
   - circuit version
   - curve
   - ruleset id
3. Add CLI subcommands:
   - `setup` (if appropriate)
   - `vk` export
4. Ensure artifacts are never accidentally committed if large/secret.

---

## P5 — Testing strategy

1. Unit tests for:
   - witness parsing
   - circuit constraints
   - prover/verifier happy path
   - invalid proof handling
2. Golden vectors:
   - deterministic witness → deterministic proof (if feasible)
   - verification succeeds on known-good vectors
3. Cross-language integration tests:
   - Python `Groth16Backend` generates proof → Rust verifies
   - Rust prove output → Python parses/validates
4. Fuzzing:
   - fuzz JSON inputs to CLI
   - fuzz proof verification

---

## P6 — Build & DevEx

1. Add a minimal `make`-like workflow in docs:
   - build
   - test
   - run example
2. Cache-friendly builds (CI):
   - `cargo` cache
   - avoid rebuilding on doc changes
3. Consider `--features` for optional components.

---

## P7 — Backward compatibility (path/import changes)

1. Keep Python binary discovery searching all known historical locations.
2. Keep docs mentioning both current and legacy locations.
3. Consider adding a tiny wrapper script (optional) if external tools still call `./groth16_backend/...`.

---

## P8 — Documentation (authoritative)

1. Document:
   - CLI contract
   - JSON schemas
   - exit codes
   - artifact lifecycle
2. Add a short troubleshooting section:
   - “binary not found” paths
   - environment variable overrides

---

## Notes

This is intentionally a “living / infinite” list: keep adding items as new integration needs appear, but treat P0/P1 as release blockers.

# Logic Module API Reference

**Version:** 2.1  
**Last Updated:** 2026-04-23  
**Status:** Current (code-aligned)

This reference documents the current public import surfaces and high-value APIs in `ipfs_datasets_py.logic`, with emphasis on current zero-knowledge proof behavior.

---

## 1) Canonical Import Surface

For stable imports, prefer:

```python
from ipfs_datasets_py.logic.api import ...
```

`ipfs_datasets_py.logic.api` re-exports the primary converter, cache, type, and integration symbols while keeping import-time side effects minimal.

---

## 2) Package-Level Namespaces

### `ipfs_datasets_py.logic`
- Consolidated namespace with backward compatibility behavior.
- `logic.tools` access is deprecated and redirected to `logic.integration`.

### `ipfs_datasets_py.logic.fol`
- `FOLConverter`
- `convert_text_to_fol` (legacy helper)

### `ipfs_datasets_py.logic.deontic`
- `DeonticConverter`
- `convert_legal_text_to_deontic`
- Deontic graph/analysis/knowledge-base symbols (see `deontic/__init__.py`)

### `ipfs_datasets_py.logic.common`
- Errors: `LogicError`, `ConversionError`, `ProofError`, etc.
- Converter base classes: `LogicConverter`, `ChainedConverter`
- Caching/monitoring: `BoundedCache`, `ProofCache`, `get_global_cache`, `UtilityMonitor`, `track_performance`

### `ipfs_datasets_py.logic.types`
- Shared type system for deontic/proof/translation/FOL integration.
- Includes compatibility aliases for TDFOL core formula constructs.

### `ipfs_datasets_py.logic.integration`
- Lazy-loaded integration layer for bridges, reasoning engines, and optional SymbolicAI tooling.
- Includes availability flags and optional bridge exports.

### `ipfs_datasets_py.logic.TDFOL`
- TDFOL core terms/formulas/KB/proof structures.
- Parsers, prover, cache helpers, and advanced tools exposed lazily.

### `ipfs_datasets_py.logic.CEC`
- Lazy wrapper exports for CEC framework/wrappers.
- Native implementation available under `ipfs_datasets_py.logic.CEC.native`.

### `ipfs_datasets_py.logic.flogic`
- F-logic types (`FLogicFrame`, `FLogicClass`, `FLogicOntology`, `FLogicStatus`)
- ErgoAI wrapper + shared proof-cache wrapper (`CachedErgoAIWrapper`)
- ZKP integration (`ZKPFLogicProver`, `ZKPFLogicResult`)

### `ipfs_datasets_py.logic.zkp`
- `ZKPProver`, `ZKPVerifier`, `ZKPProof`
- Simulation-focused by default, with backend abstraction and optional Groth16 path.

---

## 3) Zero-Knowledge Proof APIs (Current Behavior)

## 3.1 Core ZKP types and classes

```python
from ipfs_datasets_py.logic.zkp import ZKPProof, ZKPProver, ZKPVerifier
```

- `ZKPProver.generate_proof(theorem, private_axioms, metadata=None) -> ZKPProof`
- `ZKPProver.prove(statement, witness=None, metadata=None) -> ZKPProof` (compat alias)
- `ZKPVerifier.verify_proof(proof) -> bool`
- `ZKPVerifier.verify_with_public_inputs(proof, expected_theorem) -> bool`

## 3.2 Backend selection

Backends are selected via `logic.zkp.backends.get_backend()`.

Supported IDs:
- `simulated` (default)
- `groth16` / `g16` (Rust FFI-backed path)

```python
from ipfs_datasets_py.logic.zkp.backends import get_backend, list_backends
```

### Important security and runtime notes

- `simulated` backend is educational/demo oriented and not cryptographically secure.
- `groth16` backend exists and is wired through `logic/zkp/backends/groth16.py` and `groth16_ffi.py`.
- Groth16 is fail-closed when disabled/misconfigured/missing artifacts.
- `IPFS_DATASETS_ENABLE_GROTH16=0` disables Groth16 operations.

---

## 4) ZKP Integration Points in Logic Systems

### 4.1 TDFOL

```python
from ipfs_datasets_py.logic.TDFOL.zkp_integration import ZKPTDFOLProver, UnifiedProofResult
```

- Hybrid proving path (ZKP-first with fallback).
- Cache-aware result model for standard and ZKP proof outputs.

### 4.2 CEC

```python
from ipfs_datasets_py.logic.CEC.native.cec_zkp_integration import ZKPCECProver, UnifiedCECProofResult
```

- Hybrid CEC proving with optional private-axiom handling.
- Unified result object with proving method metadata.

### 4.3 F-logic

```python
from ipfs_datasets_py.logic.flogic.flogic_zkp_integration import ZKPFLogicProver, ZKPFLogicResult
```

- Strategy order: cache lookup → optional ZKP attestation → standard Ergo query.
- Shared proof cache integration via `CachedErgoAIWrapper`.

---

## 5) F-logic Cache and CID Semantics

`ipfs_datasets_py.logic.flogic.flogic_proof_cache` uses CID-like content addressing for query cache keys, combining:
- prover identity
- ontology program identity
- normalized goal

This supports deterministic keying and alignment with distributed/IPFS-oriented cache workflows.

---

## 6) Stable Usage Recommendation

For external callers, prefer this order:
1. `ipfs_datasets_py.logic.api` (most stable umbrella)
2. Submodule `__init__` exports (`fol`, `deontic`, `common`, `types`, `flogic`, `zkp`)
3. Deep module imports only when you need implementation-specific classes.

---

## 7) Deprecation Notes

- `ipfs_datasets_py.logic.tools` is deprecated; migrate to `logic.integration` or module-specific namespaces.
- Legacy converter helper functions remain available for compatibility (`convert_text_to_fol`, `convert_legal_text_to_deontic`).

---

## 8) Related Documentation

- [Architecture](./logic_ARCHITECTURE.md)
- [Documentation Index](./DOCUMENTATION_INDEX.md)
- [Known Limitations](./KNOWN_LIMITATIONS.md)
- [Package README](../../ipfs_datasets_py/logic/README.md)
- [ZKP README](../../ipfs_datasets_py/logic/zkp/README.md)

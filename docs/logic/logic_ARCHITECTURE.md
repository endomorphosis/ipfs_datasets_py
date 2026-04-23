# Logic Module Architecture

**Version:** 2.1  
**Last Updated:** 2026-04-23  
**Status:** Current (code-aligned)

This document reflects the implemented architecture in `ipfs_datasets_py.logic` and related documentation paths.

---

## 1) Architecture Overview

The logic stack is layered as follows:

1. **Core conversion and shared utilities**
   - `logic.fol`, `logic.deontic`, `logic.common`, `logic.types`
2. **Reasoning engines and bridges**
   - `logic.TDFOL`, `logic.CEC`, `logic.integration`
3. **Proof privacy and attestation paths**
   - `logic.zkp`, plus ZKP integration in TDFOL/CEC/F-logic
4. **External and optional proving backends**
   - `logic.external_provers`, optional bridge/prover integrations

---

## 2) Package Structure (Implemented)

```
ipfs_datasets_py/logic/
├── __init__.py
├── api.py
├── common/
├── types/
├── fol/
├── deontic/
├── TDFOL/
├── CEC/
├── integration/
├── flogic/
├── zkp/
└── external_provers/
```

---

## 3) Import/Dependency Design

### 3.1 Import-time safety pattern

Many high-level packages (`logic.api`, `logic.integration`, `logic.TDFOL`, `logic.CEC`, `logic.flogic`, `logic.zkp`) use lazy imports and optional dependency guards to keep import-time behavior deterministic.

### 3.2 Backward compatibility

- `logic.tools` compatibility is retained via deprecation redirect behavior.
- Converter helper functions remain available for compatibility while class-based usage is preferred.

---

## 4) Caching Architecture

### 4.1 Shared proof cache

`logic.common.proof_cache.ProofCache` is the central cache primitive used across multiple proving/conversion paths.

### 4.2 F-logic cache keying

`logic.flogic.flogic_proof_cache.CachedErgoAIWrapper` computes content-addressed keys from ontology + normalized goal, with CID-first behavior and fallback hashing when required dependencies are absent.

---

## 5) Zero-Knowledge Proof Architecture

## 5.1 Core ZKP package

`logic.zkp` provides:
- Public types and wrappers (`ZKPProof`, `ZKPProver`, `ZKPVerifier`)
- Backend registry (`logic.zkp.backends`)
- Canonicalization, witness, statement, and on-chain helper modules

## 5.2 Backend model

- **Default backend:** `simulated` (educational/demo behavior, non-cryptographic)
- **Optional backend:** `groth16` (Rust FFI path, fail-closed on missing runtime/artifacts)

Groth16 behavior is controlled by environment/runtime availability and may require setup artifacts.

## 5.3 Integration points

- `TDFOL/zkp_integration.py` (`ZKPTDFOLProver`)
- `CEC/native/cec_zkp_integration.py` (`ZKPCECProver`)
- `flogic/flogic_zkp_integration.py` (`ZKPFLogicProver`)

Each integration exposes hybrid proving modes and unified result objects carrying method metadata and privacy-related fields.

---

## 6) Reasoning and Bridge Layer

`logic.integration` orchestrates:
- conversion bridges
- reasoning engines
- domain-specific utilities
- optional SymbolicAI-enabled tooling (opt-in)

The namespace is intentionally lazy to avoid forcing optional dependencies at import time.

---

## 7) Current ZKP Status (Code-Aligned)

- The ZKP API surface is active and integrated across multiple logic subsystems.
- The default path remains simulation-oriented and explicitly warns about non-production security characteristics.
- A Groth16 backend path is present in code and routed through backend selection; it is guarded and fails closed when prerequisites are unmet.

---

## 8) Recommended Reading Order

1. [API Reference](./logic_API_REFERENCE.md)
2. [Known Limitations](./KNOWN_LIMITATIONS.md)
3. [Package README](../../ipfs_datasets_py/logic/README.md)
4. [ZKP README](../../ipfs_datasets_py/logic/zkp/README.md)

---

## 9) Notes on Drift Prevention

When updating logic docs, treat these files as the source of truth for architecture/API overviews:
- `ipfs_datasets_py/logic/*/__init__.py`
- `ipfs_datasets_py/logic/api.py`
- `ipfs_datasets_py/logic/zkp/*`
- integration bridge modules (`TDFOL/zkp_integration.py`, `CEC/native/cec_zkp_integration.py`, `flogic/flogic_zkp_integration.py`)

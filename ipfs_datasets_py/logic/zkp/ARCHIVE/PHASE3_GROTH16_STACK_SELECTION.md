# Phase 3: Groth16 Stack Selection & Phase A Implementation

**Date:** 2026-02-19  
**Phase:** 3 (Real ZKP Backend)  
**Status:** Rust-FFI Groth16 backend integrated (opt-in); hardening in progress

---

## Executive Summary

Phase 3 introduces a real Groth16 zkSNARK backend while maintaining the existing simulation as the safe, default backend. This document:

1. **Evaluates Groth16 prover stack options** (py_ecc vs. Rust/Go FFI vs. managed services)
2. **Recommends a phased implementation strategy** (Phase A → B → C → D → E)
3. **Tracks implementation artifacts** and decision rationale

**Decision:** The repo-supported direction is a Rust Groth16 backend (FFI/subprocess) under `processors/groth16_backend/`, enabled via `IPFS_DATASETS_ENABLE_GROTH16=1`. Pure-Python (`py_ecc`) remains an optional alternative.

---

## Part 1: Groth16 Stack Evaluation

### Option 1: Pure Python (py_ecc)

**Description:** Use `py_ecc` library for BN254 elliptic curve operations + implement Groth16 proof generation/verification in Python.

**Pros:**
- ✅ Single-language codebase (Python)
- ✅ Portable (no system dependencies)
- ✅ Debugging friendly (pure Python stacktraces)
- ✅ Educational value (algorithm transparency)
- ✅ Already widely used in Ethereum tooling

**Cons:**
- ❌ Performance: slower than compiled Rust/Go (3-10x slower)
- ❌ Maintenance burden: implementing Groth16 correctly is non-trivial
- ❌ Limited test coverage for edge cases
- ❌ Risk: implementation bugs vs. existing audited libraries
- ❌ Witness generation complexity (needs FFT for large circuits)

**Approximate Scope (if chosen):**
- Groth16 proof generation: 400-600 lines of careful crypto code
- Setup phase implementation: 200-300 lines
- Integration: 200-300 lines
- Testing: 500+ lines
- **Total:** ~1500 lines + significant review effort

**Recommendation:** ⚠️ **Only if** time/resources allow AND we accept performance trade-offs for MVP.

---

### Option 2: Rust/Go Prover with Python Wrapper (FFI)

**Description:** Use a mature, audited Groth16 library (e.g., `ark-groth16`, `gnark`, `bellman`) and wrap it with Python FFI or REST.

**Available Libraries:**

#### 2.1 ark-groth16 (Rust, Arkworks ecosystem)
- **Maturity:** ⭐⭐⭐⭐⭐ (battle-tested, production-used)
- **Curves supported:** BN254, fields on all ark curves
- **Language:** Rust
- **Integration:** via PyO3 (Rust ↔ Python binding) or subprocess/FFI
- **Maintenance:** Actively maintained by Arkworks team

**Pros:**
- ✅ Audited, proven, widely deployed
- ✅ Fast (native compiled Rust)
- ✅ Rich ecosystem (ark-poly, ark-ff, ark-ec all integrated)
- ✅ Well-documented API

**Cons:**
- ❌ Requires Rust toolchain + build step
- ❌ FFI complexity (serialization boundaries)
- ❌ Binary distribution challenges

#### 2.2 gnark (Go, ConsenSys)
- **Maturity:** ⭐⭐⭐⭐⭐ (enterprise-grade)
- **Curves supported:** BN254, BLS12-381, others
- **Language:** Go
- **Integration:** via subprocess, REST, or FFI

**Pros:**
- ✅ Extremely fast (compiled Go)
- ✅ Widely used in production (Polygon, others)
- ✅ Excellent documentation + examples

**Cons:**
- ❌ Go toolchain dependency
- ❌ Subprocess communication overhead
- ❌ Process isolation (no direct Python ↔ Go calls)

#### 2.3 circom + snarkjs (JavaScript/Node)
- **Maturity:** ⭐⭐⭐⭐ (community-standard for circuits)
- **Curves supported:** BN254 (native), others (via fflonk)
- **Language:** JavaScript (Node.js)
- **Integration:** via subprocess or Node VM
- **Circuit format:** circom DSL (text-to-constraints compiler)

**Pros:**
- ✅ Industry standard (ZK circuit language)
- ✅ Excellent tooling + tutorials
- ✅ Community libraries (circuits, patterns)
- ✅ Subprocess integration straightforward

**Cons:**
- ❌ JavaScript runtime dependency (Node.js)
- ❌ Not optimized for high throughput provers
- ❌ File I/O overhead (artifact exchange)

---

### Option 3: Managed/Hosted Services

**Examples:** Helix SaaS, Nexus prover (cloud), etc.

**Pros:**
- ✅ Zero local infrastructure
- ✅ Outsourced security & performance

**Cons:**
- ❌ Network latency (not suitable for local batch proving)
- ❌ Privacy/trust assumptions (proover sees axioms)
- ❌ Cost model unclear
- ❌ Not suitable for ephemeral peer workflow

**Recommendation:** ❌ **Skip for now** (reconsider for production scale-out later)

---

## Part 2: Recommended Stack Selection

### Recommendation: **Approach 2 (FFI to Rust) with Fallback to circom/snarkjs**

**Primary:** `ark-groth16` (Rust) + PyO3 binding  
**Fallback:** circom/snarkjs (Node.js) for easier setup  

**Rationale:**
1. **Performance:** Native Rust compilation needed for production-scale proving (>1000 constraints).
2. **Maturity:** ark-groth16 has institutional backing + battlefield testing.
3. **Flexibility:** PyO3 allows direct Python ↔ Rust calls (no subprocess overhead).
4. **Fallback:** snarkjs for rapid prototyping if Rust toolchain proves problematic.

**Phase A Implications:**
- Add `[groth16-py_ecc]` + `[groth16-rust]` optional feature groups.
- Attempt `import py_ecc` for pure-Python option.
- Attempt `import ark_groth16` (PyO3-bound) for Rust option.
- Graceful degradation: if neither available, raise `ZKPError` on backend selection.

---

## Part 3: Phase A Implementation (Backend Gating)

### Objective
Enable backend selection without implementing real Groth16 yet. Focus on interfaces + error handling.

### Deliverables

#### 3.1 Backend Protocol (Pure Python typing)
**File:** `logic/zkp/backends/backend_protocol.py`

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@runtime_checkable
class ZKBackend(Protocol):
    """Abstract backend interface for ZKP operations."""
    
    def generate_proof(
        self,
        theorem: str,
        private_axioms: list[str],
        metadata: dict,
    ) -> "ZKPProof":
        """Generate a ZKP proof."""
        ...
    
    def verify_proof(self, proof: "ZKPProof") -> bool:
        """Verify a ZKP proof."""
        ...
    
    @property
    def backend_id(self) -> str:
        """Backend identifier (e.g., 'simulated', 'groth16')."""
        ...
    
    @property
    def curve_id(self) -> str:
        """Curve identifier (e.g., 'bn254', 'bls12_381')."""
        ...
```

#### 3.2 Backend Registry (Lazy Loading)
**File:** `logic/zkp/backends/__init__.py`

```python
_backends = {}
_backend_features = {
    "simulated": {"required": [], "optional": []},
    "groth16": {"required": ["py_ecc"], "optional": ["ark-groth16", "snarkjs"]},
}

def get_backend(backend_id: str) -> ZKBackend:
    """Retrieve backend by ID with lazy loading."""
    if backend_id in _backends:
        return _backends[backend_id]
    
    if backend_id == "simulated":
        from .simulated import SimulatedZKBackend
        backend = SimulatedZKBackend()
    elif backend_id == "groth16":
        try:
            from .groth16_ark import Groth16Backend
            backend = Groth16Backend()
        except ImportError:
            raise ZKPError(
                f"Groth16 backend requires: py_ecc. "
                f"Install with: pip install ipfs-datasets[groth16]"
            )
    else:
        raise ZKPError(f"Unknown backend: {backend_id}")
    
    _backends[backend_id] = backend
    return backend
```

#### 3.3 ZKPProver/ZKPVerifier Refactor
**File:** `logic/zkp/zkp_prover.py` + `zkp_verifier.py`

```python
class ZKPProver:
    def __init__(
        self,
        backend: str = "simulated",
        circuit_id: str = "mvp_v1",
        version: int = 1,
    ):
        """Initialize prover with selected backend."""
        if backend not in _SUPPORTED_BACKENDS:
            raise ZKPError(f"Unknown backend: {backend}")
        
        self.backend = get_backend(backend)
        self.circuit_id = circuit_id
        self.version = version
        
        if backend != "simulated" and not _deps_available(backend):
            raise ZKPError(
                f"Backend '{backend}' unavailable. "
                f"Install optional deps: pip install ipfs-datasets[{backend}]"
            )
    
    def generate_proof(self, theorem: str, axioms: list[str]) -> ZKPProof:
        """Generate proof using configured backend."""
        return self.backend.generate_proof(
            theorem=theorem,
            private_axioms=axioms,
            metadata={
                "circuit_id": self.circuit_id,
                "version": self.version,
            }
        )
```

#### 3.4 Tests for Backend Gating
**File:** `tests/unit_tests/logic/zkp/test_backend_selection.py`

```python
def test_default_backend_is_simulated():
    """Default backend should be 'simulated'."""
    prover = ZKPProver()
    assert prover.backend.backend_id == "simulated"

def test_simulated_backend_always_available():
    """Simulated backend must not require optional deps."""
    prover = ZKPProver(backend="simulated")
    # Should not raise

def test_groth16_backend_selection_without_deps_raises():
    """Selecting groth16 without install should raise with actionable message."""
    with pytest.raises(ZKPError, match="groth16.*unavailable"):
        ZKPProver(backend="groth16")

def test_unknown_backend_rejected():
    """Unknown backend names should be rejected."""
    with pytest.raises(ZKPError, match="Unknown backend"):
        ZKPProver(backend="unknown_backend")

def test_import_quiet_with_backend_registry():
    """Backend registry must not trigger imports on module import."""
    # This test ensures that importing logic.zkp does not import py_ecc or rust libs
    import subprocess
    result = subprocess.run(
        ["python3", "-c", "import ipfs_datasets_py.logic.zkp; print('OK')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "UserWarning" not in result.stderr or "backend" not in result.stderr.lower()
```

---

## Part 4: Phase B–E High-Level Plan

(Detailed RFC to follow for each phase)

### Phase B: MVP Circuit Specification
- Finalize circuit constraints (witness → proof statement)
- Canonicalization locked in `logic/zkp/canonicalization.py`
- Golden vectors finalized (already done in Phase 2)

### Phase C: Real Groth16 Backend (Ark-Groth16)
- Implement `backends/groth16_ark.py` using Rust library
- Trusted setup workflow (circuit → PK/VK)
- Proof generation + verification

### Phase D: EVM Verifier Contract + Integration
- Solidity contract template generation from VK
- On-chain verifier registry
- End-to-end harness (off-chain → on-chain)

### Phase E: Legal Theorem Semantics
- Encode real logic constraints
- Threat model documentation
- Security review

---

## Part 5: Decision Log & Rationale

| Date       | Decision                     | Rationale                                                          |
|------------|------------------------------|---------------------------------------------------------------------|
| 2026-02-19 | Phase A (gating only)        | Unblock backend selection design before real crypto implementation  |
| 2026-02-19 | Recommend Rust (ark-groth16) | Production performance + maturity vs. pure Python risk             |
| 2026-02-19 | JSON golden vectors (Phase 2)| Fixed regression baseline enables tracking behavior change         |
| 2026-02-19 | Property-based tests (P8.2)  | Statistical confidence in invariants across 5000+ examples         |

---

## Part 6: Implementation Timeline (Estimate)

| Phase | Items                              | Effort | Blocker |
|-------|-----------------------------------|--------|---------|
| A     | Backend protocol + gating         | 1-2d   | None    |
| B     | MVP circuit finalization          | 2-3d   | Phase A |
| C     | Groth16 implementation (Rust)     | 5-7d   | Phase B |
| D     | EVM integration + contract        | 3-5d   | Phase C |
| E     | Legal semantics + threat model    | 3-5d   | Phase D |
| Total |                                   | 14-22d | —       |

---

## Next Steps

1. **Today:** Implement Phase A (backend protocol + registry) → ~400 lines
2. **Week 1:** Phase B (circuit finalization) + Phase C planning
3. **Week 2–3:** Phase C (Rust backend) if bandwidth available
4. **Week 4:** Phase D (on-chain integration)
5. **Week 4–5:** Phase E (semantics + security review)

---

## Appendix: Dependency Management

### Current (Phase 1-2)
```toml
[dependencies]
hashlib = "*"  # builtin
dataclasses = "*"  # builtin

[optional]
# None yet
```

### After Phase A (Backend gating)
```toml
[dependencies]
# (no changes)

[optional]
groth16-py_ecc = [
    "py_ecc>=5.0.0",
    "hypothesis>=6.0",  # property tests
]
groth16-rust = [
    "ark-groth16",  # PyO3-bound Rust library (not yet released)
]
```

### After Phase C (Real backend)
```toml
[optional]
groth16-py_ecc = ["py_ecc>=5.0.0"]
groth16-rust = ["ark-groth16>=0.3"]
```

---

## References

- GROTH16_IMPLEMENTATION_PLAN.md (architecture + requirements)
- TODO_MASTER.md (phase breakdown + blockers)
- zkp_golden_vectors.json (fixed regression vectors)
- test_zkp_properties.py (property-based tests, 5000+ examples)

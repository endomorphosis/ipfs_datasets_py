# TDFOL + ZKP Integration Strategy
## Zero-Knowledge Proofs for Temporal Deontic First-Order Logic

**Document Version:** 1.0.0  
**Date:** 2026-02-18  
**Status:** 🟢 ACTIVE IMPLEMENTATION  
**Related:** REFACTORING_PLAN_2026_02_18.md, zkp/README.md

---

## Executive Summary

This document outlines the integration strategy between TDFOL (Temporal Deontic First-Order Logic) and ZKP (Zero-Knowledge Proofs), enabling privacy-preserving theorem proving while maintaining the full capabilities of the TDFOL reasoning system.

**Key Benefits:**
- **Privacy:** Prove theorems without revealing axioms
- **Succinctness:** ~160 byte ZKP proofs vs. full proof trees
- **Verification:** <10ms ZKP verification vs. re-proving
- **Caching:** Unified CID-based cache for both proof types
- **IPFS:** Store ZKP proofs on-chain with content addressing

---

## Current State (2026-02-18)

### TDFOL Module
- **Status:** Phase 7 complete (NL processing)
- **LOC:** 13,073 (190 tests passing)
- **Features:** FOL + Deontic + Temporal logic, NL → TDFOL pipeline
- **Caching:** Unified proof cache with CID addressing (O(1) lookups)

### ZKP Module
- **Status:** Educational simulation (NOT cryptographically secure)
- **LOC:** ~3,000 (78 tests passing, 80% coverage)
- **Backend:** Simulated (production Groth16 planned)
- **Features:** Private theorem proving, <10ms verification, IPFS integration

### Integration Progress
- ✅ **Custom exception hierarchy** with `ZKPProofError` (Task 1.1)
- ✅ **Unified proof cache** supports both TDFOL and ZKP proofs
- 🟡 **ZKP-TDFOL integration layer** (in progress - Task 1.10)
- 🟡 **Hybrid proving mode** (planned - Phase 8)

---

## Integration Architecture

### 1. Unified Proof Representation

```python
from dataclasses import dataclass
from typing import Optional, Any, List

@dataclass
class UnifiedProofResult:
    """Unified proof result supporting both standard and ZKP proofs."""
    
    # Common fields
    is_proved: bool
    formula: Any
    method: str  # "tdfol_standard", "tdfol_zkp", "hybrid"
    proof_time: float
    
    # Standard TDFOL proof fields
    proof_steps: Optional[List[Any]] = None
    inference_rules: Optional[List[str]] = None
    
    # ZKP proof fields
    zkp_proof: Optional[Any] = None  # ZKPProof object
    is_private: bool = False  # True if axioms are hidden
    backend: Optional[str] = None  # "simulated", "groth16"
    security_level: int = 0  # Security bits
    
    # Caching
    cache_hit: bool = False
    cache_cid: Optional[str] = None
```

### 2. Hybrid Proving Mode

The integration supports three proving modes:

**Mode 1: Standard Only** (default, no privacy)
```python
# Traditional TDFOL proving
prover = TDFOLProver(kb)
result = prover.prove(formula)
# Result: Full proof tree, axioms visible
```

**Mode 2: ZKP Only** (privacy-preserving)
```python
# Zero-knowledge proving
prover = TDFOLProver(kb, enable_zkp=True, zkp_backend="simulated")
result = prover.prove(formula, private_axioms=True)
# Result: ZKP proof (~160 bytes), axioms hidden
```

**Mode 3: Hybrid** (try ZKP, fall back to standard)
```python
# Hybrid proving (recommended for production)
prover = TDFOLProver(kb, enable_zkp=True, zkp_fallback="standard")
result = prover.prove(formula, prefer_zkp=True)
# Result: ZKP if possible, standard if ZKP fails
```

### 3. Unified Proof Cache Strategy

Both standard and ZKP proofs use the same CID-based cache:

```python
from ipfs_datasets_py.logic.common import ProofCache

cache = ProofCache(maxsize=10000, ttl=3600)

# Cache standard proof
standard_result = tdfol_prover.prove(formula)
cache.set(
    formula,
    standard_result,
    prover_name="tdfol_standard",
    metadata={'method': 'forward_chaining'}
)

# Cache ZKP proof (different CID due to private axioms)
zkp_result = tdfol_prover.prove(formula, private_axioms=True)
cache.set(
    formula,
    zkp_result,
    prover_name="tdfol_zkp",
    metadata={
        'method': 'zkp',
        'backend': 'simulated',
        'private': True
    }
)

# Retrieve from cache
cached = cache.get(formula, prover_name="tdfol_zkp")
if cached:
    print(f"Cache hit! (CID: {cached.cid[:16]}...)")
```

**Cache Key Computation:**
```python
# Standard proof: CID(formula + axioms + prover_config)
standard_cid = cid_for_obj({
    'formula': formula.to_string(),
    'axioms': [ax.to_string() for ax in kb.axioms],
    'prover': 'tdfol_standard',
    'config': prover.config
})

# ZKP proof: CID(formula + ZKP_commitment + prover_config)
# Note: Axioms are NOT included (privacy-preserving)
zkp_cid = cid_for_obj({
    'formula': formula.to_string(),
    'zkp_commitment': zkp_proof.commitment,  # ~32 bytes
    'prover': 'tdfol_zkp',
    'backend': 'simulated',
    'security_level': 128
})
```

---

## Implementation Plan

### Track 1: Quick Wins (2-3 weeks) - IN PROGRESS

**Week 1: Foundation**
- ✅ Task 1.1: Custom exception hierarchy (4h) - **COMPLETE**
- [ ] Task 1.2: Safe error handling (6h)
- [ ] Task 1.3: Eliminate code duplication (8h)
- [ ] Task 1.4: Improve type hints (6h)

**Week 2-3: Core Tests + ZKP Integration**
- [ ] Task 1.5-1.9: Core module tests (50h)
- [ ] **Task 1.10: ZKP-TDFOL integration layer (12h)**
  - Create `TDFOL/zkp_integration.py` (400 LOC)
  - Implement `ZKPTDFOLProver` class
  - Add hybrid proving mode
  - Create 30+ integration tests
  - Update documentation

### Track 2: Core Enhancements (8-10 weeks)

**Phase 8: Complete Prover (4-5 weeks)**
- Add 60+ inference rules
- Implement modal tableaux
- **Add ZKP verification as alternative proof method**
- Support ZKP fallback for complex proofs

**Phase 9: Optimization (3-4 weeks)**
- Fix O(n³) → O(n² log n)
- **Task 9.5: ZKP-aware proof cache optimization (8h)**
  - Unified caching for standard + ZKP proofs
  - CID-based deduplication
  - Cache hit rate tracking per proof type
  - Cache warming for common patterns

### Track 3: Production Readiness (7-9 weeks)

**Phase 10: Comprehensive Testing (3-4 weeks)**
- Add 440 → 910+ tests
- **Add 50+ ZKP integration tests**
  - Test hybrid proving modes
  - Test ZKP cache hit rates
  - Test ZKP fallback patterns
  - Test security properties

**Phase 11: Visualization (2-3 weeks)**
- ASCII/GraphViz proof trees
- **ZKP proof visualization**
  - Show verification status (✓/✗)
  - Show backend and security level
  - Show proof size comparison (ZKP vs standard)

**Phase 12: Production Hardening (2-3 weeks)**
- Security validation
- **ZKP backend upgrade path** (simulated → Groth16)
- Complete documentation

---

## API Design

### Task 1.10: ZKP-TDFOL Integration Layer

**File:** `ipfs_datasets_py/logic/TDFOL/zkp_integration.py`

```python
"""
ZKP-TDFOL Integration Layer.

This module provides integration between TDFOL theorem proving and
zero-knowledge proofs, enabling privacy-preserving reasoning.

Features:
- Hybrid proving mode (try ZKP, fall back to standard)
- Unified proof result representation
- ZKP-aware proof caching
- Backend selection (simulated, Groth16)
"""

from typing import Optional, List, Any, Dict
from dataclasses import dataclass

from ..zkp import ZKPProver, ZKPVerifier, ZKPProof
from .tdfol_prover import TDFOLProver, ProofResult
from .tdfol_core import Formula, TDFOLKnowledgeBase
from .exceptions import ZKPProofError, ProofError
from ..common.proof_cache import ProofCache


class ZKPTDFOLProver:
    """
    TDFOL prover with zero-knowledge proof support.
    
    This prover extends the standard TDFOL prover with ZKP capabilities,
    enabling privacy-preserving theorem proving.
    
    Proving Modes:
        - standard: Traditional TDFOL proving (no privacy)
        - zkp: Zero-knowledge proving (privacy-preserving)
        - hybrid: Try ZKP first, fall back to standard
    
    Example:
        >>> kb = TDFOLKnowledgeBase()
        >>> kb.add_axiom(parse_tdfol("P"))
        >>> kb.add_axiom(parse_tdfol("P -> Q"))
        >>> 
        >>> # Create hybrid prover
        >>> prover = ZKPTDFOLProver(
        ...     kb,
        ...     enable_zkp=True,
        ...     zkp_backend="simulated",
        ...     zkp_fallback="standard"
        ... )
        >>> 
        >>> # Prove with privacy (ZKP)
        >>> result = prover.prove(
        ...     parse_tdfol("Q"),
        ...     prefer_zkp=True,
        ...     private_axioms=True
        ... )
        >>> print(f"Method: {result.method}")  # "tdfol_zkp"
        >>> print(f"Private: {result.is_private}")  # True
        >>> print(f"Proof size: {len(result.zkp_proof.proof_bytes)} bytes")
    
    ZKP Backends:
        - "simulated": Educational simulation (NOT cryptographically secure)
        - "groth16": Production zkSNARK (future, requires cryptography library)
    
    Security Considerations:
        The "simulated" backend is for educational purposes only. It is NOT
        cryptographically secure and should NOT be used for production systems
        requiring real zero-knowledge proofs.
    """
    
    def __init__(
        self,
        knowledge_base: TDFOLKnowledgeBase,
        enable_zkp: bool = False,
        zkp_backend: str = "simulated",
        zkp_security_level: int = 128,
        zkp_fallback: str = "standard",
        enable_cache: bool = True,
        cache: Optional[ProofCache] = None
    ):
        """
        Initialize ZKP-TDFOL prover.
        
        Args:
            knowledge_base: TDFOL knowledge base with axioms
            enable_zkp: Enable zero-knowledge proving
            zkp_backend: ZKP backend ("simulated", "groth16")
            zkp_security_level: Security bits (128, 192, 256)
            zkp_fallback: Fallback mode if ZKP fails ("standard", "none")
            enable_cache: Enable proof caching
            cache: Optional custom cache instance
        """
        self.kb = knowledge_base
        self.enable_zkp = enable_zkp
        self.zkp_backend = zkp_backend
        self.zkp_security_level = zkp_security_level
        self.zkp_fallback = zkp_fallback
        
        # Standard TDFOL prover
        self.standard_prover = TDFOLProver(
            knowledge_base,
            enable_cache=enable_cache
        )
        
        # ZKP prover (if enabled)
        self.zkp_prover: Optional[ZKPProver] = None
        if enable_zkp:
            self.zkp_prover = ZKPProver(
                security_level=zkp_security_level,
                enable_caching=enable_cache,
                backend=zkp_backend
            )
        
        # Proof cache (unified)
        self.cache = cache or ProofCache(maxsize=10000, ttl=3600)
        
        # Statistics
        self.stats = {
            'standard_proofs': 0,
            'zkp_proofs': 0,
            'hybrid_proofs': 0,
            'zkp_failures': 0,
            'cache_hits': 0,
        }
    
    def prove(
        self,
        formula: Formula,
        prefer_zkp: bool = False,
        private_axioms: bool = False,
        timeout: float = 60.0,
        max_iterations: int = 100
    ) -> UnifiedProofResult:
        """
        Prove formula with hybrid ZKP/standard mode.
        
        Args:
            formula: Formula to prove
            prefer_zkp: Prefer ZKP if enabled
            private_axioms: Keep axioms private (requires ZKP)
            timeout: Proof timeout (seconds)
            max_iterations: Max forward chaining iterations
        
        Returns:
            UnifiedProofResult with proof information
        
        Raises:
            ProofError: If proof fails in all modes
            ZKPProofError: If ZKP fails and no fallback
        
        Proving Logic:
            1. Check cache first (both standard and ZKP)
            2. If prefer_zkp and enable_zkp: try ZKP
            3. If ZKP fails and fallback enabled: try standard
            4. If neither works: raise ProofError
        """
        start_time = time.time()
        
        # Check cache first
        cache_result = self._check_cache(formula, prefer_zkp)
        if cache_result:
            self.stats['cache_hits'] += 1
            return cache_result
        
        # Determine proving mode
        if private_axioms and not self.enable_zkp:
            raise ProofError(
                "Private axioms require ZKP, but ZKP is disabled",
                formula=formula,
                suggestion="Enable ZKP with enable_zkp=True"
            )
        
        use_zkp = (prefer_zkp or private_axioms) and self.enable_zkp
        
        # Try ZKP first
        if use_zkp:
            try:
                return self._prove_with_zkp(
                    formula,
                    timeout=timeout,
                    start_time=start_time
                )
            except ZKPProofError as e:
                self.stats['zkp_failures'] += 1
                
                # Check fallback mode
                if self.zkp_fallback == "none" or private_axioms:
                    # No fallback allowed
                    raise
                
                # Fall back to standard proving
                logging.warning(
                    f"ZKP failed ({e.backend}): {e.message}. "
                    f"Falling back to standard proving."
                )
        
        # Standard proving
        return self._prove_standard(
            formula,
            timeout=timeout,
            max_iterations=max_iterations,
            start_time=start_time
        )
    
    def verify_zkp_proof(
        self,
        zkp_proof: ZKPProof,
        formula: Formula
    ) -> bool:
        """
        Verify a zero-knowledge proof.
        
        Args:
            zkp_proof: ZKP proof to verify
            formula: Formula that was proved
        
        Returns:
            True if proof is valid, False otherwise
        
        Example:
            >>> result = prover.prove(formula, prefer_zkp=True)
            >>> assert prover.verify_zkp_proof(result.zkp_proof, formula)
        """
        if not self.enable_zkp:
            raise ProofError(
                "ZKP verification requires ZKP to be enabled",
                suggestion="Enable ZKP with enable_zkp=True"
            )
        
        verifier = ZKPVerifier(backend=self.zkp_backend)
        return verifier.verify_proof(zkp_proof)
    
    # ... (additional methods)
```

---

## Use Cases

### Use Case 1: Standard TDFOL Proving (No Privacy)

```python
from ipfs_datasets_py.logic.TDFOL import parse_tdfol, TDFOLKnowledgeBase
from ipfs_datasets_py.logic.TDFOL.zkp_integration import ZKPTDFOLProver

# Create knowledge base
kb = TDFOLKnowledgeBase()
kb.add_axiom(parse_tdfol("forall x. Agent(x) -> Responsible(x)"))
kb.add_axiom(parse_tdfol("Agent(alice)"))

# Create prover (ZKP disabled)
prover = ZKPTDFOLProver(kb, enable_zkp=False)

# Prove theorem (standard mode)
result = prover.prove(parse_tdfol("Responsible(alice)"))

print(f"Proved: {result.is_proved}")  # True
print(f"Method: {result.method}")  # "tdfol_standard"
print(f"Steps: {len(result.proof_steps)}")  # 2
```

### Use Case 2: Privacy-Preserving ZKP Proving

```python
# Create knowledge base with sensitive axioms
kb = TDFOLKnowledgeBase()
kb.add_axiom(parse_tdfol("SensitiveAxiom1"))  # Private!
kb.add_axiom(parse_tdfol("SensitiveAxiom2"))  # Private!

# Create ZKP-enabled prover
prover = ZKPTDFOLProver(
    kb,
    enable_zkp=True,
    zkp_backend="simulated",
    zkp_security_level=128
)

# Prove with privacy
result = prover.prove(
    parse_tdfol("Conclusion"),
    prefer_zkp=True,
    private_axioms=True  # Axioms will NOT be revealed
)

print(f"Proved: {result.is_proved}")  # True
print(f"Method: {result.method}")  # "tdfol_zkp"
print(f"Private: {result.is_private}")  # True
print(f"Proof size: {len(result.zkp_proof.proof_bytes)} bytes")  # ~160
print(f"Backend: {result.backend}")  # "simulated"

# Verify proof (without seeing axioms)
assert prover.verify_zkp_proof(result.zkp_proof, parse_tdfol("Conclusion"))
```

### Use Case 3: Hybrid Proving (Recommended)

```python
# Create hybrid prover (try ZKP, fall back to standard)
prover = ZKPTDFOLProver(
    kb,
    enable_zkp=True,
    zkp_backend="simulated",
    zkp_fallback="standard"  # Fall back if ZKP fails
)

# Try ZKP first, fall back to standard if it fails
result = prover.prove(
    formula,
    prefer_zkp=True
)

if result.method == "tdfol_zkp":
    print(f"Proved with ZKP (private, {len(result.zkp_proof.proof_bytes)} bytes)")
elif result.method == "tdfol_standard":
    print(f"Proved with standard TDFOL ({len(result.proof_steps)} steps)")
```

### Use Case 4: Unified Proof Caching

```python
# Both standard and ZKP proofs use same cache
from ipfs_datasets_py.logic.common import get_global_cache

cache = get_global_cache()

# Prove and cache (standard)
result1 = prover.prove(formula1, prefer_zkp=False)
# Cached automatically with CID: bafybeia...

# Prove and cache (ZKP)
result2 = prover.prove(formula2, prefer_zkp=True, private_axioms=True)
# Cached automatically with CID: bafybeib...

# Cache hit on second call
result3 = prover.prove(formula1, prefer_zkp=False)
print(f"Cache hit: {result3.cache_hit}")  # True
print(f"Cache CID: {result3.cache_cid[:16]}...")  # bafybeia...

# Statistics
print(f"Cache stats: {cache.get_stats()}")
# {'hits': 1, 'misses': 2, 'size': 2, 'hit_rate': 0.33}
```

---

## Performance Characteristics

### Standard TDFOL Proving
- **Simple proofs:** 10-50ms (direct lookup)
- **Forward chaining:** 100-500ms (10 iterations)
- **Complex proofs:** 1-5s (100 iterations)
- **Proof size:** Variable (full proof tree, KB)

### ZKP Proving (Simulated Backend)
- **Proof generation:** 100-500ms (includes TDFOL + ZKP overhead)
- **Verification:** <10ms (fast verification)
- **Proof size:** ~160 bytes (succinct)
- **Privacy:** Axioms hidden (NOT cryptographically secure in simulation)

### Caching (Both Modes)
- **Cache lookup:** <1ms (O(1) CID-based)
- **Cache speedup:** 100-20000x on hits
- **Cache size:** ~200 bytes per formula + proof

### Comparison Table

| Metric | Standard TDFOL | ZKP (Simulated) | Improvement |
|--------|---------------|-----------------|-------------|
| Proof time | 100-500ms | 100-500ms | ~Same |
| Verification | Re-prove (100-500ms) | <10ms | **50x faster** |
| Proof size | ~5KB (tree) | ~160 bytes | **30x smaller** |
| Privacy | No | Yes* | **Private axioms** |
| Cache hit | <1ms | <1ms | Same |

*Note: Simulated backend is NOT cryptographically secure. Production requires Groth16.

---

## Security Considerations

### Current Status (Simulated Backend)

⚠️ **WARNING:** The current ZKP backend is a **simulation** for educational purposes. It is **NOT cryptographically secure** and should **NOT** be used for production systems requiring real zero-knowledge proofs.

**Simulated Backend Limitations:**
- No cryptographic security guarantees
- Proofs can be forged
- Privacy is simulated, not enforced
- Intended for development and testing only

### Production Upgrade Path (Groth16)

For production use with real zero-knowledge proofs:

1. **Install cryptography library** (e.g., `py_ecc`, `gnark-crypto`)
2. **Configure Groth16 backend:**
   ```python
   prover = ZKPTDFOLProver(
       kb,
       enable_zkp=True,
       zkp_backend="groth16",  # Production backend
       zkp_security_level=256   # 256-bit security
   )
   ```
3. **Perform trusted setup** (one-time, per circuit)
4. **Verify security properties** (soundness, zero-knowledge, succinctness)

See `logic/zkp/PRODUCTION_UPGRADE_PATH.md` for complete guide.

---

## Testing Strategy

### Unit Tests (Task 1.10)
- Test ZKPTDFOLProver initialization
- Test standard proving mode
- Test ZKP proving mode
- Test hybrid proving mode
- Test fallback behavior
- Test cache integration
- Test error handling

### Integration Tests (Phase 10)
- Test TDFOL + ZKP end-to-end
- Test cache hit rates (standard vs ZKP)
- Test proof size comparison
- Test verification performance
- Test hybrid mode under various conditions

### Performance Tests (Phase 10)
- Benchmark standard vs ZKP proving
- Benchmark verification speed
- Benchmark cache performance
- Measure proof size distribution

---

## Timeline Summary

| Phase | Duration | Key ZKP Tasks |
|-------|----------|---------------|
| **Track 1 Week 1** | 1 week | ✅ Exception hierarchy with ZKPProofError |
| **Track 1 Week 2-3** | 2 weeks | Task 1.10: ZKP integration layer (12h) |
| **Phase 8** | 4-5 weeks | ZKP verification as alternative proof method |
| **Phase 9** | 3-4 weeks | ZKP-aware cache optimization (8h) |
| **Phase 10** | 3-4 weeks | 50+ ZKP integration tests |
| **Phase 11** | 2-3 weeks | ZKP proof visualization |
| **Phase 12** | 2-3 weeks | Production upgrade guide (simulated → Groth16) |

**Total ZKP Integration Effort:** ~35 hours (out of 420 total)

---

## References

- **TDFOL Refactoring Plan:** [REFACTORING_PLAN_2026_02_18.md](./REFACTORING_PLAN_2026_02_18.md)
- **ZKP Module:** [../zkp/README.md](../zkp/README.md)
- **ZKP Production Upgrade:** [../zkp/PRODUCTION_UPGRADE_PATH.md](../zkp/PRODUCTION_UPGRADE_PATH.md)
- **Proof Caching:** [../common/proof_cache.py](../common/proof_cache.py)
- **Custom Exceptions:** [exceptions.py](./exceptions.py)

---

**Document Status:** 🟢 ACTIVE  
**Version:** 1.0.0  
**Last Updated:** 2026-02-18  
**Next Update:** After Task 1.10 completion (Week 2-3)

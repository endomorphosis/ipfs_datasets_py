# Additional Theorem Provers Integration Strategy

**Version:** 1.0  
**Date:** 2026-02-18  
**Status:** Planning Phase

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Current Provers](#current-provers)
3. [Target Provers](#target-provers)
4. [Unified Prover Interface](#unified-prover-interface)
5. [Prover Orchestration](#prover-orchestration)
6. [Implementation Plan](#implementation-plan)

---

## 📊 Overview

### Objectives

Integrate multiple theorem provers to provide:
1. **Diverse reasoning strategies** (saturation, tableaux, SMT, interactive)
2. **Automatic prover selection** based on problem characteristics
3. **Parallel proof attempts** with timeout and aggregation
4. **Confidence scoring** from multiple provers
5. **Unified interface** for all provers

### Current Provers (2)

1. **Native Python Prover** - Forward/backward chaining (production-ready)
2. **Shadow Prover** - Java-ported algorithms (production-ready)

### Target Provers (5 additional)

3. **Z3 SMT Solver** - Satisfiability modulo theories
4. **Vampire** - Automated theorem prover (TPTP format)
5. **E Prover** - Equational theorem prover
6. **Isabelle/HOL** - Interactive theorem prover (optional)
7. **Coq** - Proof assistant (optional)

---

## 🔍 Current Provers

### 1. Native Python Prover

**Location:** `ipfs_datasets_py/logic/CEC/native/prover_core.py`

**Features:**
- Forward chaining with modus ponens
- Backward chaining with goal-directed search
- Modal tableaux for modal logic
- 45+ unit tests

**Capabilities:**
- ✅ First-order logic
- ✅ Modal logic (□, ◊)
- ✅ Deontic logic (O, P, F)
- ✅ Cognitive logic (B, K, I)
- ✅ Temporal logic (basic)

**Strengths:**
- Pure Python (no dependencies)
- Fast startup
- Good for simple proofs
- Highly maintainable

**Limitations:**
- Limited inference rules (~20)
- No advanced strategies
- Not competitive with state-of-the-art

### 2. Shadow Prover

**Location:** `ipfs_datasets_py/logic/CEC/native/shadow_prover.py`

**Features:**
- Java-ported algorithms
- Alternative proving strategies
- 33+ unit tests

**Capabilities:**
- ✅ Alternative proof strategies
- ✅ SNARK integration (planned)
- ✅ Problem file format

**Strengths:**
- Different approach from native
- Good for specific problem types

**Limitations:**
- Still in development
- Limited documentation

---

## 🎯 Target Provers

### 3. Z3 SMT Solver

**Official Website:** https://github.com/Z3Prover/z3

**Features:**
- Satisfiability modulo theories
- Supports multiple theories (arithmetic, arrays, bitvectors)
- Efficient model finding
- Active development

**Installation:**
```bash
pip install z3-solver
```

**Use Cases:**
- ✅ Satisfiability checking
- ✅ Model generation
- ✅ Counterexample finding
- ✅ Constraint solving

**Integration Complexity:** LOW (Python bindings available)

**Example Integration:**
```python
from z3 import *
from ipfs_datasets_py.logic.CEC.native import Formula

class Z3Prover(ProverInterface):
    def __init__(self):
        self.solver = Solver()
    
    def prove(self, conjecture: Formula, axioms: List[Formula]) -> ProofResult:
        # Convert DCEC formulas to Z3
        z3_axioms = [self.to_z3(ax) for ax in axioms]
        z3_conjecture = self.to_z3(conjecture)
        
        # Add axioms to solver
        for ax in z3_axioms:
            self.solver.add(ax)
        
        # Check if conjecture is consequence of axioms
        # (Add negation and check for unsat)
        self.solver.add(Not(z3_conjecture))
        
        result = self.solver.check()
        
        if result == unsat:
            return ProofResult(success=True, result="proved")
        elif result == sat:
            model = self.solver.model()
            return ProofResult(success=True, result="disproved", model=model)
        else:
            return ProofResult(success=False, result="unknown")
```

### 4. Vampire Prover

**Official Website:** https://vprover.github.io/

**Features:**
- State-of-the-art automated theorem prover
- TPTP format support
- Multiple saturation strategies
- Active research project

**Installation:**
```bash
# Download binary from GitHub releases
wget https://github.com/vprover/vampire/releases/download/v4.7/vampire
chmod +x vampire
```

**Use Cases:**
- ✅ First-order logic proving
- ✅ Complex saturation problems
- ✅ TPTP benchmark problems

**Integration Complexity:** MEDIUM (requires subprocess management, TPTP conversion)

**Example Integration:**
```python
import subprocess
from typing import List

class VampireProver(ProverInterface):
    def __init__(self, binary_path: str = "vampire"):
        self.binary_path = binary_path
    
    def prove(self, conjecture: Formula, axioms: List[Formula]) -> ProofResult:
        # Convert to TPTP format
        tptp_problem = self.to_tptp(conjecture, axioms)
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.p', delete=False) as f:
            f.write(tptp_problem)
            problem_file = f.name
        
        try:
            # Run Vampire
            result = subprocess.run(
                [self.binary_path, problem_file, '--mode', 'casc', '--time_limit', '30'],
                capture_output=True,
                text=True,
                timeout=35
            )
            
            # Parse output
            if "Refutation found" in result.stdout:
                proof_steps = self.parse_vampire_proof(result.stdout)
                return ProofResult(success=True, result="proved", steps=proof_steps)
            elif "Satisfiable" in result.stdout:
                return ProofResult(success=True, result="disproved")
            else:
                return ProofResult(success=False, result="unknown")
        
        finally:
            os.unlink(problem_file)
    
    def to_tptp(self, conjecture: Formula, axioms: List[Formula]) -> str:
        lines = []
        
        # Add axioms
        for i, axiom in enumerate(axioms):
            lines.append(f"fof(axiom_{i}, axiom, {self.formula_to_tptp(axiom)}).")
        
        # Add conjecture
        lines.append(f"fof(conjecture, conjecture, {self.formula_to_tptp(conjecture)}).")
        
        return '\n'.join(lines)
```

### 5. E Prover

**Official Website:** https://wwwlehre.dhbw-stuttgart.de/~sschulz/E/E.html

**Features:**
- Equational theorem prover
- TPTP format support
- Excellent performance on equality-heavy problems

**Installation:**
```bash
# Download and build from source
wget http://wwwlehre.dhbw-stuttgart.de/~sschulz/WORK/E_DOWNLOAD/V_2.6/E.tgz
tar xzf E.tgz
cd E
./configure
make
```

**Use Cases:**
- ✅ Equational reasoning
- ✅ Rewriting systems
- ✅ Unit equality problems

**Integration Complexity:** MEDIUM (similar to Vampire)

### 6. Isabelle/HOL (Optional)

**Official Website:** https://isabelle.in.tum.de/

**Features:**
- Interactive theorem prover
- Higher-order logic
- Large library of formalized mathematics
- Proof automation (sledgehammer)

**Installation:**
```bash
# Download from website or use package manager
apt-get install isabelle
```

**Use Cases:**
- ✅ Interactive proof development
- ✅ Proof verification
- ✅ Mathematical formalization

**Integration Complexity:** HIGH (requires Isabelle/ML, complex API)

**Note:** May be overkill for automated reasoning; consider for future enhancement.

### 7. Coq (Optional)

**Official Website:** https://coq.inria.fr/

**Features:**
- Proof assistant based on Calculus of Inductive Constructions
- Dependent types
- Large ecosystem (MathComp, Software Foundations)

**Installation:**
```bash
apt-get install coq
# or
opam install coq
```

**Use Cases:**
- ✅ Verified software
- ✅ Mathematical proofs
- ✅ Type theory

**Integration Complexity:** HIGH (requires Coq tactics, complex API)

**Note:** Consider for future if formal verification becomes priority.

---

## 🔌 Unified Prover Interface

### ProverInterface ABC

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum

class ProofResult(str, Enum):
    PROVED = "proved"
    DISPROVED = "disproved"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    ERROR = "error"

@dataclass
class ProofResponse:
    success: bool
    result: ProofResult
    prover_name: str
    time_ms: float
    steps: Optional[List[str]] = None
    proof_tree: Optional[Dict[str, Any]] = None
    model: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ProverInterface(ABC):
    """Abstract base class for all theorem provers."""
    
    @abstractmethod
    def prove(
        self,
        conjecture: Formula,
        axioms: List[Formula],
        timeout_seconds: int = 30
    ) -> ProofResponse:
        """
        Attempt to prove the conjecture from the given axioms.
        
        Args:
            conjecture: Formula to prove
            axioms: List of axiom formulas
            timeout_seconds: Maximum time allowed
        
        Returns:
            ProofResponse with result and details
        """
        pass
    
    @abstractmethod
    def check_satisfiability(
        self,
        formula: Formula,
        timeout_seconds: int = 30
    ) -> ProofResponse:
        """
        Check if formula is satisfiable.
        
        Args:
            formula: Formula to check
            timeout_seconds: Maximum time allowed
        
        Returns:
            ProofResponse with satisfiability result
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Prover name."""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Prover version."""
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        """List of prover capabilities."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if prover is available/installed."""
        pass
```

### Prover Implementations

```python
class NativePythonProver(ProverInterface):
    """Native Python prover implementation."""
    
    name = "Native Python Prover"
    version = "1.0.0"
    capabilities = ["forward_chaining", "backward_chaining", "modal_tableaux"]
    
    def prove(self, conjecture, axioms, timeout_seconds=30):
        # Implementation from prover_core.py
        pass
    
    def is_available(self) -> bool:
        return True  # Always available

class Z3Prover(ProverInterface):
    """Z3 SMT solver integration."""
    
    name = "Z3 SMT Solver"
    version = "4.12.0"
    capabilities = ["smt", "model_checking", "satisfiability"]
    
    def prove(self, conjecture, axioms, timeout_seconds=30):
        # Z3 implementation
        pass
    
    def is_available(self) -> bool:
        try:
            import z3
            return True
        except ImportError:
            return False

class VampireProver(ProverInterface):
    """Vampire automated theorem prover."""
    
    name = "Vampire"
    version = "4.7"
    capabilities = ["saturation", "tptp", "first_order_logic"]
    
    def prove(self, conjecture, axioms, timeout_seconds=30):
        # Vampire implementation
        pass
    
    def is_available(self) -> bool:
        return shutil.which("vampire") is not None
```

---

## 🎭 Prover Orchestration

### Automatic Prover Selection

```python
class ProverSelector:
    """Selects best prover for a given problem."""
    
    def __init__(self):
        self.provers: List[ProverInterface] = []
        self.performance_stats: Dict[str, Dict] = {}
    
    def register_prover(self, prover: ProverInterface):
        if prover.is_available():
            self.provers.append(prover)
    
    def select_prover(self, problem: Problem) -> ProverInterface:
        """Select best prover based on problem characteristics."""
        
        # Analyze problem
        features = self.extract_features(problem)
        
        # Score each prover
        scores = []
        for prover in self.provers:
            score = self.score_prover(prover, features)
            scores.append((score, prover))
        
        # Return best prover
        return max(scores, key=lambda x: x[0])[1]
    
    def extract_features(self, problem: Problem) -> Dict[str, Any]:
        """Extract problem features for prover selection."""
        return {
            'formula_count': len(problem.axioms) + 1,
            'max_depth': self.get_max_depth(problem.conjecture),
            'has_equality': self.has_equality(problem),
            'has_arithmetic': self.has_arithmetic(problem),
            'has_quantifiers': self.has_quantifiers(problem),
            'has_modal': self.has_modal_operators(problem),
        }
    
    def score_prover(self, prover: ProverInterface, features: Dict) -> float:
        """Score prover suitability for problem."""
        score = 0.0
        
        # Check capability match
        if features['has_modal'] and 'modal_tableaux' in prover.capabilities:
            score += 10.0
        
        if features['has_arithmetic'] and 'smt' in prover.capabilities:
            score += 10.0
        
        if features['has_equality'] and 'equational' in prover.capabilities:
            score += 10.0
        
        # Add historical performance
        stats = self.performance_stats.get(prover.name, {})
        success_rate = stats.get('success_rate', 0.5)
        avg_time = stats.get('avg_time_ms', 1000)
        
        score += success_rate * 20.0
        score -= avg_time / 100.0  # Penalize slow provers
        
        return score
```

### Parallel Prover Orchestration

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class ParallelProverOrchestrator:
    """Run multiple provers in parallel."""
    
    def __init__(self, provers: List[ProverInterface]):
        self.provers = [p for p in provers if p.is_available()]
    
    def prove_parallel(
        self,
        conjecture: Formula,
        axioms: List[Formula],
        timeout_seconds: int = 60
    ) -> Dict[str, ProofResponse]:
        """
        Try multiple provers in parallel.
        
        Returns dict mapping prover name to result.
        """
        results = {}
        
        with ThreadPoolExecutor(max_workers=len(self.provers)) as executor:
            # Submit all prover tasks
            future_to_prover = {
                executor.submit(
                    prover.prove,
                    conjecture,
                    axioms,
                    timeout_seconds
                ): prover
                for prover in self.provers
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_prover, timeout=timeout_seconds + 5):
                prover = future_to_prover[future]
                try:
                    result = future.result()
                    results[prover.name] = result
                    
                    # If proved, we can stop (optional optimization)
                    if result.result == ProofResult.PROVED:
                        # Cancel remaining tasks
                        for f in future_to_prover:
                            f.cancel()
                        break
                
                except Exception as e:
                    results[prover.name] = ProofResponse(
                        success=False,
                        result=ProofResult.ERROR,
                        prover_name=prover.name,
                        time_ms=0,
                        error_message=str(e)
                    )
        
        return results
    
    def get_consensus(self, results: Dict[str, ProofResponse]) -> ProofResult:
        """Determine consensus result from multiple provers."""
        
        # Count votes
        votes = {}
        for result in results.values():
            votes[result.result] = votes.get(result.result, 0) + 1
        
        # Majority vote
        if ProofResult.PROVED in votes and votes[ProofResult.PROVED] >= len(results) / 2:
            return ProofResult.PROVED
        
        if ProofResult.DISPROVED in votes and votes[ProofResult.DISPROVED] >= len(results) / 2:
            return ProofResult.DISPROVED
        
        return ProofResult.UNKNOWN
    
    def get_confidence(self, results: Dict[str, ProofResponse]) -> float:
        """Calculate confidence score (0-1) from results."""
        
        if not results:
            return 0.0
        
        # Weight by prover reliability
        total_weight = 0.0
        weighted_score = 0.0
        
        for prover_name, result in results.items():
            weight = self.get_prover_weight(prover_name)
            total_weight += weight
            
            if result.result == ProofResult.PROVED:
                weighted_score += weight * 1.0
            elif result.result == ProofResult.DISPROVED:
                weighted_score += weight * 0.0
            else:
                weighted_score += weight * 0.5
        
        return weighted_score / total_weight if total_weight > 0 else 0.5
```

---

## 📋 Implementation Plan (Phase 6: Weeks 17-20)

### Week 17: Interface & Z3

**Day 1-2: Unified Interface**
- Define ProverInterface ABC
- Define ProofResponse dataclass
- Refactor existing provers to use interface
- Add 10+ interface tests

**Day 3-5: Z3 Integration**
- Install z3-solver
- Implement Z3Prover class
- DCEC → Z3 formula conversion
- Z3 → DCEC result conversion
- Add 15+ Z3 tests

**Deliverables:**
- Unified prover interface
- Z3 integration complete
- 25+ tests

### Week 18: Vampire Integration

**Day 1-2: TPTP Conversion**
- Implement DCEC → TPTP converter
- Support all DCEC operators in TPTP
- Add TPTP validation
- Add 10+ conversion tests

**Day 3-5: Vampire Prover**
- Implement VampireProver class
- Subprocess management
- Output parsing
- Error handling
- Add 15+ Vampire tests

**Deliverables:**
- TPTP conversion
- Vampire integration
- 25+ tests

### Week 19: E Prover Integration

**Day 1-3: E Prover**
- Reuse TPTP conversion
- Implement EProver class
- Subprocess management
- Output parsing
- Add 15+ E prover tests

**Day 4-5: Integration Testing**
- Test all provers together
- Compare results
- Validate correctness
- Add 10+ integration tests

**Deliverables:**
- E prover integration
- 25+ tests

### Week 20: Orchestration

**Day 1-2: Prover Selection**
- Implement ProverSelector
- Feature extraction
- Scoring algorithm
- Add 10+ selection tests

**Day 3-4: Parallel Orchestration**
- Implement ParallelProverOrchestrator
- Concurrent execution
- Result aggregation
- Confidence scoring
- Add 10+ orchestration tests

**Day 5: Documentation & Polish**
- API documentation
- Usage examples
- Performance comparison
- Update main README

**Deliverables:**
- Complete orchestration
- 20+ tests
- Documentation

---

## 📊 Success Metrics

### Coverage Metrics

| Metric | Target |
|--------|--------|
| Total provers | 5+ |
| Unified interface | ✅ Yes |
| Parallel execution | ✅ Yes |
| Automatic selection | ✅ Yes |
| Test coverage | 90%+ |

### Performance Metrics

| Operation | Target |
|-----------|--------|
| Prover selection | <10ms |
| Parallel proving (5 provers) | <timeout + 5s |
| Result aggregation | <5ms |
| Confidence calculation | <5ms |

---

## 📝 Conclusion

This integration strategy provides a comprehensive plan to expand from **2 to 7+ theorem provers**, offering:

1. ✅ **Diverse strategies** (saturation, SMT, tableaux, interactive)
2. ✅ **Unified interface** for all provers
3. ✅ **Automatic selection** based on problem features
4. ✅ **Parallel execution** for faster results
5. ✅ **Confidence scoring** from multiple provers

**Implementation Timeline:** 4 weeks (Weeks 17-20 of overall plan)

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-18  
**Status:** Ready for Implementation  
**Implementation:** Phase 6 (Weeks 17-20)

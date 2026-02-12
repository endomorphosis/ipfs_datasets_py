# SMT Solver Integration

This directory contains integrations with SMT (Satisfiability Modulo Theories) solvers.

## Available Solvers

### Z3 ✅ **WORKING**

**File:** `z3_prover_bridge.py` (17.2 KB)

**Developer:** Microsoft Research  
**Website:** https://github.com/Z3Prover/z3

**Features:**
- First-order logic with quantifiers
- Integer and real arithmetic
- Arrays, bitvectors, strings
- Uninterpreted functions
- Model generation
- Unsat core extraction

**Installation:**
```bash
pip install z3-solver
```

**Usage:**
```python
from ipfs_datasets_py.logic.external_provers.smt import Z3ProverBridge

prover = Z3ProverBridge(timeout=5.0)
result = prover.prove(formula)
```

**Performance:**
- Average: 10-100ms
- Success rate: ~80% on FOL
- With cache: 0.1ms (100-1000x speedup)

---

### CVC5 🔄 **STUB**

**File:** `cvc5_prover_bridge.py` (stub)

**Developer:** Stanford University  
**Website:** https://cvc5.github.io/

**Planned Features:**
- Excellent quantifier handling
- Theory of strings with regex
- Sets, bags, sequences
- Proof generation

**Status:** Stub implementation ready for full integration

**When Available:**
```python
from ipfs_datasets_py.logic.external_provers.smt import CVC5ProverBridge

prover = CVC5ProverBridge(timeout=5.0)
result = prover.prove(formula)
```

---

## SMT vs Other Approaches

| Feature | SMT (Z3/CVC5) | Native | Neural |
|---------|--------------|--------|---------|
| Speed | Fast (10-100ms) | Very Fast (1-10ms) | Slow (1000ms+) |
| Arithmetic | ✅ Excellent | ❌ Limited | ⚠️ Partial |
| Quantifiers | ✅ Good | ⚠️ Limited | ✅ Good |
| Correctness | ✅ Proven | ✅ Proven | ⚠️ Probabilistic |
| Explanations | ❌ No | ❌ No | ✅ Yes |

## Best Practices

1. **Use Z3 for:**
   - Arithmetic reasoning
   - Quantified formulas
   - When correctness is critical
   - When speed matters

2. **Enable caching:**
   ```python
   prover = Z3ProverBridge(enable_cache=True)
   ```

3. **Set appropriate timeouts:**
   ```python
   prover = Z3ProverBridge(timeout=5.0)  # 5 seconds
   ```

4. **Get counterexamples:**
   ```python
   prover = Z3ProverBridge(use_model=True)
   result = prover.prove(formula)
   if not result.is_proved() and result.model:
       print(f"Counterexample: {result.model}")
   ```

## Contributing

To add a new SMT solver:

1. Create `{solver}_prover_bridge.py`
2. Implement formula converter
3. Implement `prove()` method
4. Add availability detection
5. Integrate with cache
6. Add tests
7. Update this README

---

**Last Updated:** February 12, 2026

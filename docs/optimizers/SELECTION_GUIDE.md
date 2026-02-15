# Optimizer Selection Guide

**Last Updated:** 2026-02-14  
**Purpose:** Help users choose the right optimizer for their needs

---

## Quick Decision Tree

```
┌─ Need formal verification of logic?
│  └─ YES → Logic Theorem Optimizer
│
├─ Need to optimize knowledge graph queries?
│  └─ YES → GraphRAG Optimizer
│
└─ Need general code optimization?
   └─ YES → Agentic Optimizer
       ├─ Want to explore multiple approaches? → Adversarial Method
       ├─ Want learning from feedback? → Actor-Critic Method
       ├─ Need test generation first? → Test-Driven Method
       └─ Want resilience testing? → Chaos Engineering Method
```

---

## Optimizer Comparison Matrix

| Feature | Agentic | Logic Theorem | GraphRAG |
|---------|---------|---------------|----------|
| **Primary Use Case** | Code optimization | Formal verification | Knowledge graph optimization |
| **Test Generation** | ✅ Built-in | ❌ | ❌ |
| **Theorem Proving** | ❌ | ✅ Primary capability | ❌ |
| **Knowledge Graphs** | ❌ | ❌ | ✅ Primary capability |
| **LLM Integration** | ✅ 6 providers | ✅ Basic | ✅ RAG-focused |
| **CLI Interface** | ✅ 8 commands | ❌ Programmatic only | ❌ Programmatic only |
| **Test Coverage** | 88% (145+ tests) | Unknown | Unknown |
| **Production Ready** | ✅ 100% complete | ⚠️ Functional | ⚠️ Functional |
| **Performance Monitoring** | ✅ Comprehensive | ❌ | ❌ |
| **Security Hardening** | ✅ Built-in | ❌ | ❌ |

---

## When to Use Each Optimizer

### 🤖 Agentic Optimizer

**Best For:**
- General-purpose code optimization
- Performance improvements
- Test generation and coverage
- Exploring multiple solution approaches
- Learning from iterative feedback

**Use When:**
- You have Python/JavaScript/Go code to optimize
- Need automated test generation
- Want to explore multiple optimization strategies
- Require production-grade monitoring and security
- Need comprehensive validation (syntax, types, tests, security, performance)

**Example Scenarios:**
- "I have a function that processes 10,000 items in 5 seconds. Can it be faster?" → **Adversarial Method**
- "My module has 30% test coverage. Generate comprehensive tests." → **Test-Driven Method**
- "I want to ensure my API handles failures gracefully." → **Chaos Engineering Method**

---

### 🔬 Logic Theorem Optimizer

**Best For:**
- Converting legal text to formal logic
- Mathematical theorem proving
- Formal specification verification
- Contract analysis and validation

**Use When:**
- You have legal documents or contracts to formalize
- Need mathematical proof verification
- Working with formal specifications
- Require sound logical reasoning guarantees

**Example Scenarios:**
- "Convert this rental agreement to formal logic to verify consistency."
- "Prove that this algorithm terminates for all valid inputs."
- "Check if these business rules conflict with each other."

---

### 📊 GraphRAG Optimizer

**Best For:**
- Optimizing RAG queries
- Knowledge graph structure optimization
- Semantic search improvement
- Wikipedia and large knowledge base queries

**Use When:**
- Your RAG queries are slow or inaccurate
- Knowledge graph structure needs optimization
- Semantic search isn't finding relevant results
- Working with Wikipedia or large knowledge bases

**Example Scenarios:**
- "My RAG system takes 5 seconds per query."
- "Users search for 'climate change' but miss 'global warming' articles."
- "Need to efficiently query Wikipedia across related articles."

---

## Getting Started

### Quick Start: Agentic Optimizer

```python
from ipfs_datasets_py.optimizers.agentic import AdversarialOptimizer, OptimizationTask

optimizer = AdversarialOptimizer(num_candidates=5)
task = OptimizationTask(
    target_code="def slow_function(data): ...",
    objective="Optimize for speed"
)
result = optimizer.optimize(task)
print(f"Performance gain: {result.metrics['speedup']}x")
```

### CLI Usage

```bash
# Agentic optimizer
python -m ipfs_datasets_py.optimizers.agentic.cli optimize \
    --method adversarial \
    --target my_module.py

# Check statistics
python -m ipfs_datasets_py.optimizers.agentic.cli stats
```

---

## Additional Resources

- **Framework Improvements:** [OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md](../../OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md)
- **Quick Start:** [OPTIMIZER_IMPROVEMENTS_QUICKSTART.md](../../OPTIMIZER_IMPROVEMENTS_QUICKSTART.md)
- **Agentic Docs:** [optimizers/agentic/](../../ipfs_datasets_py/optimizers/agentic/)

---

**Version:** 1.0 | **Status:** ✅ Complete

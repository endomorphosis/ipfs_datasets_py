# Logic Theorem Optimizer: Quick Start Guide

This guide shows how to use the LogicTheoremOptimizer to extract, optimize, and validate logical theorems from text.

## Installation

```bash
# Assumes ipfs_datasets_py is installed
pip install ipfs_datasets_py[logic]
```

## Basic Usage

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common import OptimizerConfig

# Create configuration
config = OptimizerConfig(
    max_iterations=3,
    target_score=0.85,
    validation_enabled=True,
    metrics_enabled=True,
)

# Create optimizer
optimizer = LogicTheoremOptimizer(config=config, llm_backend=None)

# Context for extraction (describes what to prove)
context = {
    "domain": "propositional_logic",
    "rules": ["Modus Ponens", "Modus Tollens"],
    "target": "Prove Q from P and P→Q",
}

# Data to optimize (axioms and theorem)
data = {
    "axioms": ["P", "P → Q"],
    "theorem": "Q",
}

# Run optimization session
result = optimizer.run_session(data, context)

print(f"Optimization score: {result['score']:.2f}")
print(f"Valid: {result['valid']}")
print(f"Extracted statements: {result['artifact']['statements'][:3]}")
```

## Validate Statements

```python
# Verify theorems using integrated prover
statements = [
    {"formula": "P", "type": "axiom"},
    {"formula": "P → Q", "type": "axiom"},
    {"formula": "Q", "type": "theorem"},
]

is_valid, errors = optimizer.validate_statements(statements)

if is_valid:
    print("All statements logically consistent!")
else:
    print(f"Validation errors: {errors}")
```

## CLI Usage

```bash
# Theorem proving from command line
python -m ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper prove \
  --axiom "P" \
  --axiom "P -> Q" \
  --theorem "Q" \
  --ruleset TDFOL_v1
```

## Optimization Loop

```python
for iteration in range(5):
    # Run optimization session
    result = optimizer.run_session(data, context)
    
    score = result['score']
    valid = result['valid']
    
    print(f"Iteration {iteration+1}: score={score:.2f}, valid={valid}")
    
    # Check convergence
    if score >= config.target_score:
        print(f"Converged at iteration {iteration+1}!")
        break
    
    # Apply feedback from critic to refine approach
    feedback = optimizer.critique(result['artifact'])
    context['feedback'] = feedback.feedback
```

## Generate → Critique → Optimize Cycle

```python
import json

# PHASE 1: Generate initial extraction
extraction = optimizer.generate(data, context)
print(f"Generated {len(extraction['statements'])} statements")

# PHASE 2: Critique the result  
critique = optimizer.critique(extraction)
print(f"Critic score: {critique.overall:.2f}")
print(f"Issues: {critique.issues[:2]}")

# PHASE 3:  Optimize based on feedback
optimized = optimizer.optimize(extraction, critique)
print(f"Optimized score: optimized['score']:.2f}")
print(f"Improved: {optimized['score'] > critique.overall}")
```

## Common TDFOL Theorems

```python
# Modus Ponens: From P and P→Q, infer Q
theorems = [
    {
        "axioms": ["P", "P → Q"],
        "theorem": "Q",
        "rule": "Modus Ponens"
    },
    {
        "axioms": ["¬Q", "P → Q"],
        "theorem": "¬P",
        "rule": "Modus Tollens"
    },
    {
        "axioms": ["P ∧ Q"],
        "theorem": "P",
        "rule": "Conjunction Elimination"
    },
]

for t in theorems:
    context = {"domain": "propositional_logic", "rule": t["rule"]}
    data = {"axioms": t["axioms"], "theorem": t["theorem"]}
    
    result = optimizer.run_session(data, context)
    valid = result['valid']
    
    print(f"{t['rule']}: {'✓' if valid else '✗'}")
```

## Configuration

```python
from ipfs_datasets_py.optimizers.common import OptimizerConfig

config = OptimizerConfig(
    max_iterations=5,           # Max optimization rounds
    target_score=0.90,          # Target quality score
    early_stopping=True,        # Stop if target reached
    validation_enabled=True,    # Validate proofs
    metrics_enabled=True,       # Track metrics
)

optimizer = LogicTheoremOptimizer(config=config, llm_backend=None)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Validation always fails** | Check axioms follow standard propositional logic syntax (use `∧`, `∨`, `→`, `¬`, parentheses). |
| **Unknown formula elements** | ProverIntegrationAdapter only handles propositional logic. Use simpler formulas. |
| **Slow convergence** | Reduce `max_iterations` or lower `target_score`. Try simpler theorems first. |

## Next Steps

- **API Reference:** See [README.md](README.md) for full API docs
- **Theorem Database:** See [examples/](../examples/) for more complex theorems
- **Prover Details:** See [prover_integration_adapter.py](prover_integration_adapter.py)

---

**Last updated:** 2026-02-20  
**Test coverage:** 50+ deterministic tests in `tests/unit/optimizers/logic_theorem_optimizer/`

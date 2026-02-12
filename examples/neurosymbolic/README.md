# Neurosymbolic Reasoning Examples

This directory contains comprehensive examples demonstrating the neurosymbolic reasoning system.

## Overview

The neurosymbolic reasoning system combines:
- **127 inference rules** (40 TDFOL + 87 CEC)
- **5 modal logic provers** (K, S4, S5, D, Cognitive)
- **Grammar-based natural language processing**
- **Unified API** for all capabilities

## Examples

### Example 1: Basic Reasoning (`example1_basic_reasoning.py`)

Demonstrates fundamental reasoning capabilities:
- Creating a reasoner
- Adding knowledge (axioms and theorems)
- Proving theorems using Modus Ponens
- Checking system capabilities
- Understanding proof results

**Key Concepts:**
- Knowledge base management
- Forward chaining proof search
- Inference rules (Modus Ponens, Hypothetical Syllogism)

**Run:**
```bash
python example1_basic_reasoning.py
```

---

### Example 2: Temporal Logic (`example2_temporal_reasoning.py`)

Demonstrates temporal logic reasoning:
- Working with temporal operators (□, ◊, X, U)
- Using S4 modal logic prover
- Temporal persistence (□p → p)
- Temporal transitivity (□p → □□p)

**Key Concepts:**
- Modal logic (K, T, S4, S5)
- Temporal operators (Always, Eventually, Next, Until)
- Temporal axioms and their meaning

**Run:**
```bash
python example2_temporal_reasoning.py
```

---

### Example 3: Deontic Logic (`example3_deontic_reasoning.py`)

Demonstrates deontic logic for legal/normative reasoning:
- Obligations (O)
- Permissions (P)
- Prohibitions (F)
- Deontic axioms (K, D)
- Real-world contract scenarios

**Key Concepts:**
- Deontic operators
- Legal reasoning
- Contract formalization
- Obligation-permission derivation (O(p) → P(p))

**Run:**
```bash
python example3_deontic_reasoning.py
```

---

### Example 4: Multi-Format Parsing (`example4_multiformat_parsing.py`)

Demonstrates parsing formulas from different formats:
- TDFOL format (standard first-order logic)
- DCEC s-expression format
- Natural language (grammar-based)
- Auto-detection of format

**Key Concepts:**
- Format conversion
- Parser flexibility
- Grammar-based NL processing
- Auto-detection heuristics

**Run:**
```bash
python example4_multiformat_parsing.py
```

---

### Example 5: Combined Temporal-Deontic (`example5_combined_reasoning.py`)

Demonstrates combined temporal and deontic logic:
- Temporal obligations (O(□p), O(◊p))
- Deontic persistence over time
- Real-world legal scenarios (SLAs, compliance, contracts)
- Complex inference rules

**Key Concepts:**
- Combined temporal-deontic formulas
- Service Level Agreements (SLAs)
- Compliance requirements
- Temporal-deontic inference rules

**Run:**
```bash
python example5_combined_reasoning.py
```

---

## Running All Examples

To run all examples in sequence:

```bash
cd examples/neurosymbolic
python example1_basic_reasoning.py
python example2_temporal_reasoning.py
python example3_deontic_reasoning.py
python example4_multiformat_parsing.py
python example5_combined_reasoning.py
```

Or create a simple script:

```bash
#!/bin/bash
for example in example*.py; do
    echo "Running $example..."
    python "$example"
    echo
done
```

## Understanding the Output

Each example produces structured output showing:
1. **System initialization:** Reasoner creation and capabilities
2. **Knowledge addition:** What's being added to the knowledge base
3. **Proof attempts:** What theorems are being proven
4. **Results:** Success/failure status, method used, time taken
5. **Explanations:** What the results mean

### Status Values

- `PROVED`: Theorem successfully proven
- `UNKNOWN`: Could not prove (doesn't mean false, just unknown)
- `TIMEOUT`: Proof search exceeded time limit
- `ERROR`: Error occurred during proving

### Proof Methods

- `forward_chaining`: Base TDFOL prover
- `exhausted`: All applicable rules tried
- `shadowprover_K/S4/S5`: Modal logic prover used
- `cec_integration`: CEC rules applied
- `modal_tableaux`: Tableaux algorithm used

## Common Patterns

### Pattern 1: Simple Theorem Proving

```python
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol

reasoner = NeurosymbolicReasoner()
reasoner.add_knowledge("P")
reasoner.add_knowledge("P -> Q")

result = reasoner.prove(parse_tdfol("Q"))
if result.is_proved():
    print("Proved!")
```

### Pattern 2: Temporal Reasoning

```python
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate, TemporalFormula, TemporalOperator
)

p = Predicate("P", ())
always_p = TemporalFormula(TemporalOperator.ALWAYS, p)

reasoner.add_knowledge(always_p)
result = reasoner.prove(p)  # Should derive p from □p
```

### Pattern 3: Deontic Reasoning

```python
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate, DeonticFormula, DeonticOperator
)

p = Predicate("Pay", ())
obligatory_p = DeonticFormula(DeonticOperator.OBLIGATORY, p)
permitted_p = DeonticFormula(DeonticOperator.PERMISSIBLE, p)

reasoner.add_knowledge(obligatory_p)
result = reasoner.prove(permitted_p)  # O(p) → P(p)
```

## Customization

### Creating Custom Reasoners

```python
# Basic reasoner (40 rules only)
reasoner = NeurosymbolicReasoner(
    use_cec=False,
    use_modal=False,
    use_nl=False
)

# With CEC (127 rules)
reasoner = NeurosymbolicReasoner(
    use_cec=True,
    use_modal=False,
    use_nl=False
)

# With modal logic provers
reasoner = NeurosymbolicReasoner(
    use_cec=False,
    use_modal=True,
    use_nl=False
)

# Full-featured (recommended)
reasoner = NeurosymbolicReasoner(
    use_cec=True,
    use_modal=True,
    use_nl=True
)
```

### Adjusting Timeouts

```python
# Quick proof attempt (1 second)
result = reasoner.prove(formula, timeout_ms=1000)

# Standard timeout (5 seconds)
result = reasoner.prove(formula, timeout_ms=5000)

# Extended search (30 seconds)
result = reasoner.prove(formula, timeout_ms=30000)
```

## Troubleshooting

### Issue: "Could not parse formula"
- **Solution:** Check formula syntax matches expected format
- Try different formats (TDFOL, DCEC, or auto-detection)
- Verify parentheses and operator names

### Issue: "Proof status: unknown"
- **Reason:** Could not find proof within timeout
- **Solutions:**
  - Increase timeout
  - Add more intermediate axioms
  - Check if theorem is actually derivable

### Issue: "Grammar not available"
- **Reason:** Grammar engine not loaded
- **Impact:** Natural language parsing unavailable
- **Workaround:** Use TDFOL or DCEC format instead

## Further Reading

- **TDFOL Module:** `ipfs_datasets_py/logic/TDFOL/README.md`
- **Integration Guide:** `NEUROSYMBOLIC_ARCHITECTURE_PLAN.md`
- **Critical Gaps Resolved:** `CRITICAL_GAPS_RESOLVED.md`
- **SymbolicAI Integration:** `SYMBOLICAI_INTEGRATION_ANALYSIS.md`

## API Reference

### Main Classes

- `NeurosymbolicReasoner`: Unified reasoning interface
- `TDFOLCECBridge`: TDFOL ↔ CEC integration
- `TDFOLShadowProverBridge`: Modal logic integration
- `TDFOLGrammarBridge`: Natural language processing
- `ReasoningCapabilities`: System capabilities

### Key Methods

- `reasoner.add_knowledge(formula)`: Add to knowledge base
- `reasoner.prove(goal, timeout_ms)`: Attempt proof
- `reasoner.parse(text, format)`: Parse formula
- `reasoner.explain(formula)`: Convert to natural language
- `reasoner.query(question)`: Natural language query
- `reasoner.get_capabilities()`: Get system info

## Contributing

To add new examples:
1. Create `exampleN_<topic>.py` following the naming pattern
2. Include comprehensive docstring
3. Add structured print output
4. Update this README
5. Test with all reasoner configurations

---

**Status:** All examples working with the complete neurosymbolic architecture.  
**Version:** 1.0 (All critical gaps resolved)  
**Date:** February 2026

# Logic Module - Quick Start Guide

**Estimated Time:** 5-10 minutes  
**Prerequisites:** Python 3.12+, basic logic knowledge  
**Goal:** Convert natural language to formal logic and prove theorems

---

## Installation

### Basic Installation (Core Features)

```bash
# Install from repository
cd ipfs_datasets_py
pip install -e .

# Or with logic-specific dependencies
pip install -e ".[logic]"
```

### With Optional Dependencies

```bash
# For external provers (Z3, CVC5)
pip install z3-solver cvc5

# For neural prover integration
pip install transformers torch

# For full features
pip install -e ".[all]"
```

---

## Your First Conversion (2 minutes)

### FOL Conversion

Convert natural language to First-Order Logic:

```python
from ipfs_datasets_py.logic.fol import FOLConverter

# Initialize converter
converter = FOLConverter()

# Convert natural language to FOL
text = "All humans are mortal. Socrates is human."
result = converter.convert(text)

print(f"Formula: {result.formula}")
print(f"Predicates: {result.predicates}")
# Output:
# Formula: ∀x (Human(x) → Mortal(x)) ∧ Human(Socrates)
# Predicates: [Human, Mortal]
```

### Deontic Logic (Legal/Ethical Reasoning)

```python
from ipfs_datasets_py.logic.deontic import DeonticConverter

# Initialize converter
converter = DeonticConverter()

# Convert legal/ethical statements
text = "It is obligatory to stop at red lights. Drivers must have licenses."
result = converter.convert(text)

print(f"Obligations: {result.obligations}")
print(f"Permissions: {result.permissions}")
# Output:
# Obligations: [O(stop_at_red_light), O(have_license)]
```

---

## Proving Theorems (3 minutes)

### Simple Proof

```python
from ipfs_datasets_py.logic.CEC import CECFramework

# Initialize framework
cec = CECFramework()

# Define premises and goal
premises = [
    "∀x (Human(x) → Mortal(x))",  # All humans are mortal
    "Human(Socrates)"               # Socrates is human
]
goal = "Mortal(Socrates)"          # Therefore, Socrates is mortal

# Attempt proof
result = cec.prove(premises, goal)

if result.success:
    print(f"✓ Proof successful!")
    print(f"Steps: {len(result.steps)}")
    print(f"Time: {result.time_ms}ms")
else:
    print(f"✗ Proof failed: {result.reason}")
```

### Using External Provers

```python
from ipfs_datasets_py.logic.external_provers import Z3Prover

# Initialize Z3 prover
prover = Z3Prover()

# Convert and prove
formula = "(assert (forall ((x Int)) (=> (> x 0) (> (* x x) 0))))"
result = prover.prove(formula)

print(f"Satisfiable: {result.is_sat}")
print(f"Model: {result.model}")
```

---

## Batch Processing (1 minute)

Process multiple statements efficiently:

```python
from ipfs_datasets_py.logic.batch_processing import BatchProcessor

# Initialize processor
processor = BatchProcessor(converter_type='fol', workers=4)

# Batch convert
statements = [
    "All birds can fly",
    "Penguins are birds",
    "Some birds cannot fly"
]

results = processor.process_batch(statements)

for stmt, result in zip(statements, results):
    print(f"{stmt} → {result.formula}")
```

---

## Caching for Performance

Enable caching for 14x speedup:

```python
from ipfs_datasets_py.logic.fol import FOLConverter

# Converter with caching (enabled by default)
converter = FOLConverter(use_cache=True)

# First call - slow (100ms)
result1 = converter.convert("All humans are mortal")

# Second call - fast (<10ms, from cache)
result2 = converter.convert("All humans are mortal")

# Check cache stats
print(f"Cache hits: {converter.cache_hits}")
print(f"Cache misses: {converter.cache_misses}")
print(f"Hit rate: {converter.cache_hit_rate:.1%}")
```

---

## Interactive Mode

Use the CLI for interactive exploration:

```bash
# Start interactive session
python -m ipfs_datasets_py.logic.cli

# Or directly
ipfs-logic-cli
```

Commands:
- `convert <text>` - Convert to FOL
- `prove <premises> → <goal>` - Attempt proof
- `help` - Show all commands
- `exit` - Quit

---

## Common Use Cases

### 1. Legal Document Analysis

```python
from ipfs_datasets_py.logic.deontic import DeonticConverter

converter = DeonticConverter()

legal_text = """
Article 1: Citizens have the right to free speech.
Article 2: Free speech shall not incite violence.
Article 3: Violations of Article 2 are prohibited.
"""

result = converter.convert(legal_text)
print(result.obligations)
print(result.permissions)
print(result.prohibitions)
```

### 2. Mathematical Theorem Proving

```python
from ipfs_datasets_py.logic.TDFOL import TDFOLConverter

converter = TDFOLConverter()

# Define mathematical axioms
axioms = [
    "∀x (Even(x) → ∃y (x = 2*y))",
    "∀x (Odd(x) → ∃y (x = 2*y + 1))",
]

# Prove theorem
theorem = "∀x (Even(x) ∨ Odd(x))"
result = converter.prove(axioms, theorem)
```

### 3. Natural Language Reasoning

```python
from ipfs_datasets_py.logic.integration import UnifiedConverter

converter = UnifiedConverter()

# Automatic format detection
result = converter.convert("If it rains, the ground gets wet")

print(f"Detected format: {result.format}")  # FOL
print(f"Formula: {result.formula}")         # Rain → WetGround
```

---

## Configuration

Customize behavior with config:

```python
from ipfs_datasets_py.logic import LogicConfig

config = LogicConfig(
    cache_size=1000,              # Max cached formulas
    timeout_ms=5000,              # Proof timeout
    use_external_provers=True,    # Enable Z3/CVC5
    log_level='INFO'              # Logging verbosity
)

converter = FOLConverter(config=config)
```

---

## Troubleshooting

### Issue: Slow Conversions

**Solution:** Enable caching (enabled by default) or use batch processing

```python
# Batch processing for multiple statements
processor = BatchProcessor(workers=4)
results = processor.process_batch(statements)
```

### Issue: External Prover Not Found

**Solution:** Install optional dependencies

```bash
pip install z3-solver cvc5
```

Or use built-in provers:

```python
# Use CEC (built-in, no dependencies)
from ipfs_datasets_py.logic.CEC import CECFramework
prover = CECFramework()
```

### Issue: Parsing Errors

**Solution:** Check input format or use verbose mode

```python
converter = FOLConverter(verbose=True)
result = converter.convert(text)  # Shows detailed parsing steps
```

---

## Next Steps

### Learn More
- **[User Guide](./UNIFIED_CONVERTER_GUIDE.md)** - Comprehensive tutorial
- **[API Reference](./API_REFERENCE.md)** - Complete API documentation
- **[Architecture](./ARCHITECTURE.md)** - System design

### Advanced Features
- **[Performance Tuning](./PERFORMANCE_TUNING.md)** - Optimization strategies
- **[External Provers](./external_provers/README.md)** - Z3, Lean, Coq integration
- **[Batch Processing](./FEATURES.md#batch-processing)** - High-throughput processing

### Get Help
- **[Troubleshooting](./TROUBLESHOOTING.md)** - Common issues and solutions
- **[Error Reference](./ERROR_REFERENCE.md)** - Complete error catalog
- **[Known Limitations](./KNOWN_LIMITATIONS.md)** - Current constraints

### Contribute
- **[Contributing](./CONTRIBUTING.md)** - How to contribute
- **[Development Setup](./CONTRIBUTING.md#development-setup)** - Local setup
- **[Testing](./CONTRIBUTING.md#testing)** - Running tests

---

## Examples

### Example 1: Syllogism Proof

```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.CEC import CECFramework

# Convert premises
converter = FOLConverter()
premises = [
    converter.convert("All men are mortal"),
    converter.convert("Socrates is a man")
]

# Prove conclusion
cec = CECFramework()
goal = converter.convert("Socrates is mortal")
result = cec.prove([p.formula for p in premises], goal.formula)

print(f"Valid: {result.success}")
```

### Example 2: Legal Compliance Check

```python
from ipfs_datasets_py.logic.deontic import DeonticConverter

converter = DeonticConverter()

# Define regulations
regulations = [
    "Employees must clock in before 9 AM",
    "Overtime requires manager approval"
]

# Check compliance
actions = [
    "Employee clocked in at 8:45 AM",
    "Employee worked overtime without approval"
]

for action in actions:
    result = converter.check_compliance(regulations, action)
    print(f"{action}: {'✓ Compliant' if result.compliant else '✗ Violation'}")
```

### Example 3: Automated Reasoning

```python
from ipfs_datasets_py.logic.integration import ReasoningCoordinator

coordinator = ReasoningCoordinator()

# Automatic reasoning pipeline
text = "All birds fly. Penguins are birds. Can penguins fly?"
result = coordinator.reason(text)

print(f"Answer: {result.conclusion}")
print(f"Confidence: {result.confidence:.1%}")
print(f"Explanation: {result.explanation}")
```

---

## Performance Tips

1. **Use Caching** - Enabled by default, provides 14x speedup
2. **Batch Processing** - Process multiple statements together (2-8x faster)
3. **Memory Optimization** - Already optimized with __slots__ (30-40% less memory)
4. **Parallel Processing** - Use `workers` parameter in batch processing

```python
# Optimal configuration for high throughput
processor = BatchProcessor(
    converter_type='fol',
    workers=8,              # CPU cores
    use_cache=True,         # 14x speedup
    batch_size=100          # Process in chunks
)
```

---

## Support

- **Documentation:** [docs/](./docs/)
- **Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Examples:** [examples/](../../examples/)

**Ready to go deeper?** Continue with the [User Guide](./UNIFIED_CONVERTER_GUIDE.md) →

---

**Quick Start Complete! 🎉**  
You now know how to convert text to formal logic and prove simple theorems.

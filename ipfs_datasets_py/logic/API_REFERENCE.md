# Logic Module API Reference

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Production-Ready (Core Features)

This document provides a comprehensive API reference for the `ipfs_datasets_py.logic` module, consolidating information from all submodules.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Core Converters](#core-converters)
3. [Integration Layer](#integration-layer)
4. [Logic Engines](#logic-engines)
5. [Caching & Performance](#caching--performance)
6. [Type System](#type-system)
7. [External Provers](#external-provers)
8. [Utilities](#utilities)
9. [Error Handling](#error-handling)

---

## Quick Start

### Installation

```bash
# Core features (no optional dependencies)
pip install -e ".[logic]"

# With all optional enhancements
pip install -e ".[logic-full]"
```

### Basic Usage

```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.deontic import DeonticConverter

# Convert text to First-Order Logic
fol_converter = FOLConverter()
result = fol_converter.convert("All humans are mortal")
print(result.formula)  # ∀x (Human(x) → Mortal(x))

# Convert legal text to Deontic Logic
deontic_converter = DeonticConverter()
result = deontic_converter.convert("Users must provide consent")
print(result.formula)  # O(provide_consent(User))
```

---

## Core Converters

### FOL Converter

**Module:** `ipfs_datasets_py.logic.fol`

#### FOLConverter Class

```python
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter(
    use_cache=True,           # Enable caching (default: True)
    use_symbolic_ai=True,     # Use SymbolicAI if available (default: True)
    use_spacy=True,           # Use spaCy for NLP (default: True)
    confidence_threshold=0.7, # Minimum confidence (default: 0.7)
)
```

**Methods:**

```python
# Convert text to FOL
result = converter.convert(
    text: str,
    context: Optional[Dict] = None,
    output_format: str = "unicode",  # "unicode", "latex", "prolog", "tptp"
) -> FOLConversionResult

# Batch conversion
results = converter.convert_batch(
    texts: List[str],
    max_workers: int = 4,
    timeout: float = 30.0,
) -> List[FOLConversionResult]

# Clear cache
converter.clear_cache()

# Get statistics
stats = converter.get_stats()  # Returns CacheStats object
```

**Return Type: FOLConversionResult**

```python
@dataclass
class FOLConversionResult:
    formula: str                    # Converted FOL formula
    confidence: float               # Confidence score (0.0-1.0)
    predicates: List[str]           # Extracted predicates
    variables: List[str]            # Extracted variables
    quantifiers: List[str]          # Quantifiers used
    complexity: ComplexityMetrics   # Complexity analysis
    method: str                     # "symbolic_ai", "spacy", or "regex"
    time_ms: float                  # Conversion time
    from_cache: bool                # Whether result was cached
```

### Deontic Converter

**Module:** `ipfs_datasets_py.logic.deontic`

#### DeonticConverter Class

```python
from ipfs_datasets_py.logic.deontic import DeonticConverter

converter = DeonticConverter(
    use_cache=True,
    extract_context=True,          # Extract legal context (default: True)
    detect_conflicts=True,         # Detect rule conflicts (default: True)
)
```

**Methods:**

```python
# Convert legal text to deontic logic
result = converter.convert(
    text: str,
    domain: Optional[str] = None,  # e.g., "privacy", "contract"
    context: Optional[Dict] = None,
) -> DeonticConversionResult

# Extract obligations, permissions, prohibitions
analysis = converter.analyze_rules(text: str) -> RuleAnalysis

# Detect conflicts between rules
conflicts = converter.detect_conflicts(
    rules: List[str]
) -> List[ConflictReport]
```

**Return Type: DeonticConversionResult**

```python
@dataclass
class DeonticConversionResult:
    formula: str                    # Deontic logic formula
    operator: DeonticOperator       # O (obligation), P (permission), F (prohibition)
    agent: Optional[str]            # Actor/agent
    action: str                     # Action to perform
    conditions: List[str]           # Preconditions
    temporal: Optional[TemporalCondition]  # Temporal constraints
    confidence: float
    domain: Optional[str]
    conflicts: List[str]            # Potential conflicts detected
```

---

## Integration Layer

### Neurosymbolic Reasoner

**Module:** `ipfs_datasets_py.logic.integration`

```python
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner

reasoner = NeurosymbolicReasoner(
    cache_enabled=True,
    use_ipfs=False,  # Enable IPFS caching
)

# Add knowledge
reasoner.add_knowledge("All humans are mortal")
reasoner.add_knowledge("Socrates is human")

# Prove theorem
result = reasoner.prove("Socrates is mortal")
print(result.is_proved())  # True
print(result.method)       # "forward_chaining"
print(result.proof_steps)  # List of proof steps
```

### Bridges

#### TDFOL ↔ CEC Bridge

```python
from ipfs_datasets_py.logic.integration.bridges import TDFOLCECBridge

bridge = TDFOLCECBridge()

# Convert TDFOL to CEC
cec_formula = bridge.tdfol_to_cec(tdfol_formula)

# Convert CEC to TDFOL
tdfol_formula = bridge.cec_to_tdfol(cec_formula)
```

#### Symbolic FOL Bridge

```python
from ipfs_datasets_py.logic.integration.bridges import SymbolicFOLBridge

bridge = SymbolicFOLBridge(use_symbolic_ai=True)

# Enhanced proof search with SymbolicAI
result = bridge.prove(
    axioms: List[str],
    goal: str,
    max_depth: int = 10,
) -> ProofResult
```

---

## Logic Engines

### TDFOL (Temporal Deontic First-Order Logic)

**Module:** `ipfs_datasets_py.logic.TDFOL`

```python
from ipfs_datasets_py.logic.TDFOL import TDFOLParser, TDFOLProver

# Parse TDFOL formula
parser = TDFOLParser()
formula = parser.parse("∀x (Human(x) → Mortal(x))")

# Prove theorem
prover = TDFOLProver()
result = prover.prove(
    axioms: List[Formula],
    goal: Formula,
    method: str = "forward_chaining",  # or "backward_chaining"
) -> ProofResult
```

### CEC (Cognitive Event Calculus)

**Module:** `ipfs_datasets_py.logic.CEC`

```python
from ipfs_datasets_py.logic.CEC import CEC_wrapper

# Initialize CEC prover
cec = CEC_wrapper(
    inference_rules="all",  # or specific rule set
    modal_logic="S5",       # K, S4, S5, D, or Cognitive
)

# Prove with modal logic
result = cec.prove_modal(
    axioms: List[str],
    goal: str,
    logic_type: str = "S5",
) -> ProofResult
```

---

## Caching & Performance

### Proof Cache

**Module:** `ipfs_datasets_py.logic.integration.caching`

```python
from ipfs_datasets_py.logic.integration.caching import ProofCache, get_global_cache

# Get global cache instance
cache = get_global_cache()

# Cache a proof result
cache.set(key, proof_result, ttl=3600)

# Retrieve from cache
result = cache.get(key)

# Clear cache
cache.clear()

# Get statistics
stats = cache.get_stats()
print(f"Hit rate: {stats.hit_rate:.2%}")
print(f"Size: {stats.size} / {stats.max_size}")
```

### IPFS Cache (Distributed)

```python
from ipfs_datasets_py.logic.integration.caching import IPFSProofCache

ipfs_cache = IPFSProofCache(
    ipfs_client=None,  # Auto-detect IPFS daemon
    local_cache_size=1000,
)

# Store proof with IPFS
cid = ipfs_cache.store(proof_result)

# Retrieve from IPFS
result = ipfs_cache.retrieve(cid)
```

### Utility Monitor

**Module:** `ipfs_datasets_py.logic.common`

```python
from ipfs_datasets_py.logic.common import UtilityMonitor, track_performance

# Decorator for performance tracking
@track_performance
def expensive_operation(data):
    # ... operation ...
    return result

# Get performance statistics
monitor = UtilityMonitor.get_instance()
stats = monitor.get_stats()
print(f"Total calls: {stats.total_calls}")
print(f"Cache hits: {stats.cache_hits}")
print(f"Avg time: {stats.avg_time_ms}ms")
```

---

## Type System

### Common Types

**Module:** `ipfs_datasets_py.logic.types`

```python
from ipfs_datasets_py.logic.types import (
    # Deontic types
    DeonticOperator,
    DeonticFormula,
    DeonticRuleSet,
    LegalAgent,
    LegalContext,
    TemporalCondition,
    
    # Proof types
    ProofStatus,
    ProofResult,
    ProofStep,
    
    # FOL types
    FOLFormula,
    FOLConversionResult,
    PredicateExtraction,
    
    # Logic operators
    LogicOperator,
    Quantifier,
    FormulaType,
    
    # Metrics
    ConfidenceScore,
    ComplexityScore,
    ComplexityMetrics,
)
```

### Deontic Operators

```python
from ipfs_datasets_py.logic.types import DeonticOperator

# Obligation
O = DeonticOperator.OBLIGATION

# Permission
P = DeonticOperator.PERMISSION

# Prohibition
F = DeonticOperator.PROHIBITION
```

### Proof Result

```python
@dataclass
class ProofResult:
    status: ProofStatus          # PROVED, DISPROVED, UNKNOWN, TIMEOUT
    method: str                  # Method used
    proof_steps: List[ProofStep] # Steps in proof
    time_ms: float               # Time taken
    confidence: float            # Confidence score
    from_cache: bool             # Cached result
    
    def is_proved(self) -> bool:
        return self.status == ProofStatus.PROVED
```

---

## External Provers

### Z3 Solver

**Module:** `ipfs_datasets_py.logic.external_provers`

```python
from ipfs_datasets_py.logic.external_provers import Z3Prover

# Check if Z3 is available
prover = Z3Prover()
if prover.is_available():
    result = prover.prove(
        axioms: List[str],
        goal: str,
        timeout: int = 30,
    ) -> ProofResult
else:
    # Falls back to native prover
    pass
```

### Lean 4 Integration

```python
from ipfs_datasets_py.logic.external_provers import LeanProver

prover = LeanProver(lean_path="/path/to/lean")
result = prover.prove_interactive(
    theorem: str,
    tactics: List[str],
) -> ProofResult
```

### Coq Integration

```python
from ipfs_datasets_py.logic.external_provers import CoqProver

prover = CoqProver()
result = prover.verify(
    coq_script: str,
) -> ProofResult
```

---

## Utilities

### Bounded Cache

**Module:** `ipfs_datasets_py.logic.common`

```python
from ipfs_datasets_py.logic.common import BoundedCache

cache = BoundedCache(
    max_size=1000,        # Maximum entries
    ttl=3600,             # Time to live (seconds)
    eviction="lru",       # "lru" or "fifo"
)

# Use like a dict
cache["key"] = value
value = cache["key"]

# With TTL per item
cache.set("key", value, ttl=7200)
```

### Converter Base Class

For implementing custom converters:

```python
from ipfs_datasets_py.logic.common import LogicConverter, ConversionResult

class MyConverter(LogicConverter):
    def convert(self, text: str, **kwargs) -> ConversionResult:
        # Your conversion logic
        return ConversionResult(
            formula="...",
            confidence=0.9,
            method="custom",
        )
```

---

## Error Handling

### Exception Hierarchy

```python
from ipfs_datasets_py.logic.common.errors import (
    LogicError,              # Base exception
    ConversionError,         # Conversion failed
    ValidationError,         # Invalid input
    ProofError,              # Proof failed
    TranslationError,        # Bridge translation failed
    BridgeError,             # Bridge operation failed
    ConfigurationError,      # Configuration issue
    DeonticError,            # Deontic logic error
    ModalError,              # Modal logic error
    TemporalError,           # Temporal logic error
)
```

### Usage

```python
from ipfs_datasets_py.logic.common.errors import ConversionError

try:
    result = converter.convert(text)
except ConversionError as e:
    print(f"Conversion failed: {e}")
    print(f"Method attempted: {e.method}")
    print(f"Context: {e.context}")
```

---

## Advanced Features

### Batch Processing

```python
# Batch conversion with parallelization
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter()
texts = ["text1", "text2", "text3", ...]

results = converter.convert_batch(
    texts,
    max_workers=8,          # Parallel workers
    timeout=60.0,           # Per-item timeout
    show_progress=True,     # Show progress bar
)
```

### Chained Converters

```python
from ipfs_datasets_py.logic.common import ChainedConverter

# Chain multiple converters
chain = ChainedConverter([
    FOLConverter(),
    SimplificationConverter(),
    OptimizationConverter(),
])

result = chain.convert(text)
```

### ML Confidence Scoring

```python
from ipfs_datasets_py.logic.ml_confidence import ConfidenceScorer

scorer = ConfidenceScorer(
    model="xgboost",  # or "lightgbm", "heuristic"
)

confidence = scorer.score(
    formula=result.formula,
    features=result.features,
)
```

---

## Configuration

### Global Configuration

```python
from ipfs_datasets_py.logic.config import LogicConfig

# Set global config
config = LogicConfig(
    cache_enabled=True,
    cache_max_size=5000,
    cache_ttl=7200,
    use_ipfs=False,
    symbolic_ai_enabled=True,
    spacy_enabled=True,
    log_level="INFO",
)

LogicConfig.set_global(config)

# Get global config
config = LogicConfig.get_global()
```

### Environment Variables

```bash
# Enable/disable features
export LOGIC_CACHE_ENABLED=true
export LOGIC_USE_SYMBOLIC_AI=true
export LOGIC_USE_SPACY=true

# Cache configuration
export LOGIC_CACHE_MAX_SIZE=5000
export LOGIC_CACHE_TTL=3600

# IPFS configuration
export LOGIC_IPFS_ENABLED=false
export IPFS_API_URL=http://localhost:5001

# Logging
export LOGIC_LOG_LEVEL=INFO
```

---

## Migration Guide

### From Old API (v1.x)

```python
# OLD (v1.x)
from ipfs_datasets_py.logic.text_to_fol import convert_text_to_fol
result = convert_text_to_fol(text)

# NEW (v2.0)
from ipfs_datasets_py.logic.fol import FOLConverter
converter = FOLConverter()
result = converter.convert(text)
```

### Deprecation Warnings

The old API is still available with deprecation warnings:

```python
# Still works but shows warning
from ipfs_datasets_py.logic.text_to_fol import convert_text_to_fol
result = convert_text_to_fol(text)  # DeprecationWarning
```

---

## Performance Tips

1. **Enable Caching:** Always use `use_cache=True` (default)
2. **Batch Operations:** Use `convert_batch()` for multiple conversions
3. **Optional Dependencies:** Install `logic-full` for best performance
4. **IPFS Caching:** Enable for distributed workloads
5. **Warm Cache:** Pre-populate cache with common formulas

---

## Examples

### Complete Workflow Example

```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner

# 1. Convert text to logic
converter = FOLConverter()
axiom1 = converter.convert("All humans are mortal")
axiom2 = converter.convert("Socrates is human")
goal = converter.convert("Socrates is mortal")

# 2. Create reasoner and add knowledge
reasoner = NeurosymbolicReasoner()
reasoner.add_knowledge(axiom1.formula)
reasoner.add_knowledge(axiom2.formula)

# 3. Prove theorem
result = reasoner.prove(goal.formula)

# 4. Display results
if result.is_proved():
    print("✓ Theorem proved!")
    print(f"Method: {result.method}")
    print(f"Steps: {len(result.proof_steps)}")
    print(f"Time: {result.time_ms}ms")
    for step in result.proof_steps:
        print(f"  {step}")
else:
    print("✗ Could not prove theorem")
```

---

## Further Reading

- **[README.md](./README.md)** - Module overview and quick start
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Detailed architecture with diagrams
- **[FEATURES.md](./FEATURES.md)** - Complete feature catalog
- **[UNIFIED_CONVERTER_GUIDE.md](./UNIFIED_CONVERTER_GUIDE.md)** - Converter architecture
- **[TROUBLESHOOTING.md](./TROUBLESHOOTING.md)** - Common issues and solutions
- **[EVERGREEN_IMPROVEMENT_PLAN.md](./EVERGREEN_IMPROVEMENT_PLAN.md)** - Ongoing improvements backlog

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-02-17 | Unified API reference created, consolidated from 9 module READMEs |

---

**For questions or issues, please see [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) or open a GitHub issue.**

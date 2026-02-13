# GraphRAG Ontology Optimizer

**Status:** Scaffolding Phase (Phase 1 of 6)  
**Inspiration:** [complaint-generator adversarial harness](https://github.com/endomorphosis/complaint-generator)

---

## Overview

The GraphRAG Ontology Optimizer is a comprehensive system for generating, validating, and optimizing knowledge graph ontologies from arbitrary data types. It combines:

- **Stochastic Gradient Descent (SGD)** optimization cycles
- **Multi-agent architecture** (Generator, Critic, Mediator, Validator)
- **Theorem prover integration** for logical validation
- **Dynamic prompt engineering** for AI model extraction
- **Ontology consistency checking** across large knowledge graphs

### Architecture

The system uses an adversarial testing approach inspired by the complaint-generator repository, adapted for ontology generation:

```
Data Source → Generator → Mediator ↔ Critic
                             ↓
                      Logic Validator → Optimized Ontology
```

---

## Key Components

### 1. Ontology Generator (`ontology_generator.py`)
- **Purpose:** Generate knowledge graph ontologies from arbitrary data
- **Integration:** Uses `ipfs_accelerate_py` for AI model inference
- **Strategies:** Rule-based, LLM-based, Hybrid, Neural
- **Status:** ✅ Scaffolding complete

### 2. Ontology Critic (`ontology_critic.py`)
- **Purpose:** LLM-based evaluation of ontology quality
- **Dimensions:** Completeness (25%), Consistency (25%), Clarity (15%), Granularity (15%), Domain Alignment (20%)
- **Output:** Structured scores with actionable recommendations
- **Status:** ✅ Scaffolding complete

### 3. Ontology Mediator (`ontology_mediator.py`)
- **Purpose:** Coordinates between generator and critic
- **Features:** Multi-round refinement, dynamic prompt generation, convergence detection
- **Status:** 🔄 Planned for Phase 2

### 4. Logic Validator (`logic_validator.py`)
- **Purpose:** Validate ontologies using TDFOL theorem provers
- **Integration:** Full integration with logic/TDFOL and external provers
- **Features:** Contradiction detection, consistency proofs, fix suggestions
- **Status:** ✅ Scaffolding complete

### 5. Ontology Optimizer (`ontology_optimizer.py`)
- **Purpose:** SGD-based optimization engine
- **Features:** Batch analysis, trend identification, recommendation generation
- **Status:** 🔄 Planned for Phase 2

### 6. Ontology Session (`ontology_session.py`)
- **Purpose:** Single ontology optimization session
- **Status:** 🔄 Planned for Phase 2

### 7. Ontology Harness (`ontology_harness.py`)
- **Purpose:** Parallel batch optimization orchestrator
- **Status:** 🔄 Planned for Phase 2

---

## Installation

The GraphRAG optimizer is part of the ipfs_datasets_py package:

```bash
# Install with all dependencies
pip install -e ".[all]"

# Or install specific dependencies
pip install -e ".[logic]"  # For theorem prover integration
```

---

## Quick Start

### Basic Ontology Generation

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType
)

# Setup generator
generator = OntologyGenerator(
    ipfs_accelerate_config={
        'model': 'bert-base-uncased',
        'task': 'ner'
    }
)

# Create context
context = OntologyGenerationContext(
    data_source='legal_document.pdf',
    data_type=DataType.PDF,
    domain='legal',
    extraction_strategy=ExtractionStrategy.LLM_BASED
)

# Generate ontology
ontology = generator.generate_ontology(pdf_data, context)
print(f"Generated {len(ontology['entities'])} entities")
```

### Evaluate Ontology Quality

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyCritic

# Setup critic
critic = OntologyCritic(
    backend_config={
        'model': 'gpt-4',
        'temperature': 0.3
    }
)

# Evaluate
score = critic.evaluate_ontology(
    ontology=ontology,
    context=context,
    source_data=pdf_data
)

print(f"Overall Score: {score.overall:.2f}")
print(f"Completeness: {score.completeness:.2f}")
print(f"Consistency: {score.consistency:.2f}")

for rec in score.recommendations:
    print(f"- {rec}")
```

### Validate Logical Consistency

```python
from ipfs_datasets_py.optimizers.graphrag import LogicValidator

# Setup validator
validator = LogicValidator(
    prover_config={
        'strategy': 'AUTO',
        'timeout': 5.0
    }
)

# Check consistency
result = validator.check_consistency(ontology)

if result.is_consistent:
    print("✅ Ontology is logically consistent!")
else:
    print("❌ Found contradictions:")
    for contradiction in result.contradictions:
        print(f"  - {contradiction}")
    
    # Get fix suggestions
    fixes = validator.suggest_fixes(ontology, result.contradictions)
    print("\nSuggested fixes:")
    for fix in fixes:
        print(f"  - {fix['description']}")
```

---

## Implementation Status

### Phase 1: Core Components ✅ (Current)
- [x] Implementation plan document
- [x] `ontology_generator.py` scaffolding
- [x] `ontology_critic.py` scaffolding
- [x] `logic_validator.py` scaffolding
- [x] README documentation
- [ ] Complete implementation of core components
- [ ] Basic unit tests

### Phase 2: Integration Layer (Planned)
- [ ] `ontology_mediator.py`
- [ ] `ontology_optimizer.py`
- [ ] `ontology_session.py`
- [ ] `ontology_harness.py`
- [ ] Integration tests

### Phase 3: Support Infrastructure (Planned)
- [ ] `ontology_templates.py`
- [ ] `prompt_generator.py`
- [ ] `consistency_checker.py`
- [ ] `metrics_collector.py`
- [ ] `visualization.py`

### Phase 4: Testing (Planned)
- [ ] Comprehensive test suite
- [ ] Integration tests
- [ ] Performance tests

### Phase 5: Documentation & Examples (Planned)
- [ ] Complete API documentation
- [ ] Usage examples
- [ ] CLI interface
- [ ] Tutorial documentation

### Phase 6: Integration & Validation (Planned)
- [ ] Integration with existing GraphRAG processors
- [ ] Full theorem prover validation
- [ ] Performance optimization
- [ ] Production deployment guide

---

## Architecture Details

### Data Flow

1. **Input:** Arbitrary data (text, PDF, JSON, etc.)
2. **Generator:** Extracts entities and relationships
3. **Mediator:** Manages refinement cycles with critic feedback
4. **Critic:** Evaluates quality across multiple dimensions
5. **Validator:** Checks logical consistency using theorem provers
6. **Optimizer:** Improves through SGD cycles
7. **Output:** Validated, optimized ontology

### Integration Points

#### ipfs_accelerate_py
```python
# Use any HuggingFace pipeline for extraction
from ipfs_datasets_py.processors.file_converter import ipfs_accelerate_converter

generator = OntologyGenerator(ipfs_accelerate_config={
    'model': 'bert-base-uncased',
    'task': 'token-classification',
    'device': 'cuda'
})
```

#### TDFOL Theorem Provers
```python
# Automatic integration with all TDFOL provers
from ipfs_datasets_py.logic.TDFOL import parse_tdfol
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner

validator = LogicValidator(prover_config={
    'strategy': 'AUTO',  # Uses best available prover
    'provers': ['z3', 'cvc5', 'symbolic_ai']
})
```

#### External Provers
```python
# Use Z3, CVC5, SymbolicAI, etc.
from ipfs_datasets_py.logic.external_provers import (
    Z3ProverBridge,
    CVC5ProverBridge,
    SymbolicAIProverBridge
)

validator = LogicValidator(prover_config={
    'provers': ['z3', 'cvc5'],
    'strategy': 'parallel'
})
```

---

## Evaluation Dimensions

The critic evaluates ontologies across five dimensions:

1. **Completeness (25% weight)**
   - Coverage of key concepts and relationships
   - Presence of necessary domain entities
   - Relationship density and coverage

2. **Consistency (25% weight)**
   - Internal logical consistency
   - No contradictions or circular dependencies
   - Valid entity references

3. **Clarity (15% weight)**
   - Clear entity definitions
   - Well-documented properties
   - Unambiguous relationships

4. **Granularity (15% weight)**
   - Appropriate level of detail
   - Neither too coarse nor too fine-grained
   - Suitable for intended use case

5. **Domain Alignment (20% weight)**
   - Adherence to domain conventions
   - Use of standard terminology
   - Compatibility with domain standards

---

## Testing Strategy

### Unit Tests
- Test each component independently
- Mock external dependencies
- Target 80%+ code coverage

### Integration Tests
- Test component interactions
- Use real theorem provers
- Validate end-to-end workflows

### Performance Tests
- Benchmark SGD convergence
- Test parallel execution
- Validate prover performance

---

## Contributing

When contributing to this module:

1. **Follow existing patterns** - Match the structure from complaint-generator
2. **Write tests first** - TDD approach preferred
3. **Document thoroughly** - Every function needs docstrings
4. **Integrate carefully** - Ensure compatibility with existing logic/TDFOL
5. **Performance matters** - Cache where appropriate, parallelize when possible

---

## References

1. **complaint-generator:** https://github.com/endomorphosis/complaint-generator
2. **Adversarial Harness:** complaint-generator/adversarial_harness/README.md
3. **TDFOL Documentation:** `ipfs_datasets_py/logic/TDFOL/README.md`
4. **GraphRAG Integration:** `GRAPHRAG_INTEGRATION_DETAILED.md`
5. **External Provers:** `ipfs_datasets_py/logic/external_provers/README.md`

---

## License

Same as ipfs_datasets_py main project.

---

## Future Enhancements

1. **Distributed Execution** - Scale across multiple machines
2. **Active Learning** - User feedback integration
3. **Transfer Learning** - Reuse patterns across domains
4. **Ontology Merging** - Combine multiple ontologies
5. **Real-time Optimization** - Continuous improvement

---

## Contact

For questions or issues, please open an issue on the main repository.

# Cognitive Event Calculus (CEC) Framework

A comprehensive neurosymbolic framework for Cognitive Event Calculus reasoning, integrating multiple theorem provers and natural language converters.

---

## 📚 Documentation Navigation

**New to CEC? Start here:**
- **[QUICKSTART.md](./QUICKSTART.md)** ⚡ 5-minute tutorial to get started
- **[STATUS.md](./STATUS.md)** 📊 Implementation status (single source of truth)
- **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** 📖 Comprehensive user guide

**For developers:**
- **[IMPLEMENTATION_QUICK_START.md](./IMPLEMENTATION_QUICK_START.md)** 🚀 **START HERE** - Begin working on CEC phases
- **[API_REFERENCE.md](./API_REFERENCE.md)** 📚 Complete API documentation
- **[DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)** 💻 Development setup and contribution guide

**Planning & roadmap:**
- **[UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md)** 🎯 **MASTER ROADMAP** - Complete 5-enhancement plan (Phases 3-8)
- **[COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md](./COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md)** 🗺️ Detailed plan (8 phases, 26 weeks)
- **[PERFORMANCE_OPTIMIZATION_PLAN.md](./PERFORMANCE_OPTIMIZATION_PLAN.md)** ⚡ Phase 7 performance strategy
- **[EXTENDED_NL_SUPPORT_ROADMAP.md](./EXTENDED_NL_SUPPORT_ROADMAP.md)** 🌍 Phase 5 multi-language plan
- **[ADDITIONAL_THEOREM_PROVERS_STRATEGY.md](./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md)** 🔬 Phase 6 prover integration
- **[API_INTERFACE_DESIGN.md](./API_INTERFACE_DESIGN.md)** 🌐 Phase 8 REST API design
- **[REFACTORING_QUICK_REFERENCE.md](./REFACTORING_QUICK_REFERENCE.md)** 📋 Quick reference guide

---

## Overview

The CEC framework provides a unified Python API for:
- **Natural Language to Logic Conversion**: Convert English text to formal DCEC formulas
- **Knowledge Base Management**: Build and maintain logical knowledge bases
- **Automated Theorem Proving**: Prove theorems using multiple proving strategies
- **Neurosymbolic Reasoning**: Combine symbolic logic with AI-powered reasoning

## Components

### Native Python 3 Implementation (Recommended)

The CEC framework now includes a **production-ready native Python 3 implementation** located in `ipfs_datasets_py/logic/CEC/native/`:

- ✅ **81% coverage** of submodule functionality (8,547 LOC)
- ✅ **2-4x faster** than Java/Python 2 submodules
- ✅ **Zero external dependencies** (Python 3.12+ only)
- ✅ **418+ comprehensive tests** (~80-85% coverage)
- ✅ **Full type hints and modern Python 3 features**

**See [STATUS.md](./STATUS.md) for detailed implementation status.**

**Quick Start with Native Implementation:**
```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

# Create container
container = DCECContainer()

# Add obligation
obligation = container.create_obligation("agent", "performAction")

# Add belief
belief = container.create_belief("agent", "taskComplete")

# Use theorem prover
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver
prover = TheoremProver()
prover.add_axiom("A → B")
prover.add_axiom("A")
result = prover.prove("B")
```

**Next steps:**
- **Beginners:** Start with [QUICKSTART.md](./QUICKSTART.md) for a 5-minute tutorial
- **Developers:** See [API_REFERENCE.md](./API_REFERENCE.md) for complete API docs
- **Contributors:** Read [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) for development setup
- **Comprehensive guide:** [CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)

---

### Legacy Submodules (Optional)

The framework also integrates four legacy Python 2/Java submodules for backward compatibility:

### 1. DCEC_Library
Deontic Cognitive Event Calculus logic system for representing:
- Obligations, permissions, and prohibitions (deontic operators)
- Beliefs, knowledge, and intentions (cognitive operators)
- Events and temporal reasoning

### 2. Talos
Theorem prover interface that:
- Manages interaction with SPASS automated theorem prover
- Provides simultaneous and temporal reasoning rules
- Generates and manipulates proof trees

### 3. Eng-DCEC
English to DCEC converter using Grammatical Framework:
- Parses natural language statements
- Generates formal DCEC formulas
- Supports bidirectional conversion

### 4. ShadowProver
Shadow theorem prover providing:
- Alternative proving strategies
- Java-based theorem proving
- Docker containerization support

## Installation

The CEC submodules are included as git submodules. To initialize them:

```bash
git submodule update --init --recursive
```

### Dependencies

The framework has optional dependencies depending on which components you use:

- **DCEC_Library**: Python 2.7+ (legacy), pickle
- **Talos**: SPASS theorem prover, Python 2.7+
- **Eng-DCEC**: Grammatical Framework (GF), HTTP server
- **ShadowProver**: Java, Maven (or Docker)

## Quick Start

```python
from ipfs_datasets_py.logic.CEC import CECFramework, FrameworkConfig, ReasoningMode

# Create and initialize framework
framework = CECFramework()
init_results = framework.initialize()

# Convert natural language to logic
task = framework.reason_about(
    "The agent must fulfill their obligation",
    prove=False
)

print(f"DCEC Formula: {task.dcec_formula}")
print(f"Success: {task.success}")
```

## Usage Examples

### Basic Knowledge Addition

```python
# Add knowledge directly
framework.add_knowledge("O(act(agent))")

# Add from natural language
framework.add_knowledge(
    "The agent is obligated to act",
    is_natural_language=True
)
```

### Theorem Proving

```python
# Prove a theorem
proof = framework.prove_theorem(
    conjecture="O(act(agent))",
    axioms=["K(agent, obligation)"],
    use_temporal=False
)

print(f"Proof result: {proof.result}")
print(f"Proof tree: {proof.proof_tree}")
```

### Complete Reasoning Workflow

```python
# Full pipeline: NL -> Logic -> Prove
task = framework.reason_about(
    "The agent is obligated to perform action X",
    prove=True,
    axioms=["rule1", "rule2"]
)

if task.success:
    print(f"Formula: {task.dcec_formula}")
    print(f"Proof: {task.proof_result}")
else:
    print(f"Error: {task.error_message}")
```

### Batch Processing

```python
statements = [
    "The agent has an obligation",
    "The agent has permission",
    "The agent believes something"
]

tasks = framework.batch_reason(statements, prove=False)

for task in tasks:
    print(f"{task.natural_language} -> {task.dcec_formula}")
```

### Temporal Reasoning

```python
config = FrameworkConfig(reasoning_mode=ReasoningMode.TEMPORAL)
temporal_framework = CECFramework(config)
temporal_framework.initialize()

task = temporal_framework.reason_about(
    "Eventually the agent will act",
    prove=True
)
```

## Configuration

Customize the framework behavior:

```python
config = FrameworkConfig(
    use_dcec=True,              # Enable DCEC Library
    use_talos=True,             # Enable Talos prover
    use_eng_dcec=True,          # Enable Eng-DCEC converter
    use_shadow_prover=False,    # Enable ShadowProver
    reasoning_mode=ReasoningMode.SIMULTANEOUS,
    gf_server_url="http://127.0.0.1:41296",  # GF server URL
    spass_path="/path/to/spass",             # SPASS binary path
    shadow_prover_docker=True                # Use Docker for ShadowProver
)

framework = CECFramework(config)
```

## API Reference

### CECFramework

Main framework class providing unified API.

#### Methods

- `initialize()`: Initialize all enabled components
- `convert_natural_language(text)`: Convert English to DCEC
- `add_knowledge(statement, is_natural_language)`: Add knowledge
- `prove_theorem(conjecture, axioms, use_temporal)`: Prove a theorem
- `reason_about(natural_language, prove, axioms)`: Complete reasoning workflow
- `batch_reason(statements, prove)`: Process multiple statements
- `get_statistics()`: Get framework statistics

### Individual Wrappers

Each component has its own wrapper with specialized functionality:

- **DCECLibraryWrapper**: DCEC logic operations
- **TalosWrapper**: Theorem proving with SPASS
- **EngDCECWrapper**: Natural language conversion
- **ShadowProverWrapper**: Alternative proving strategies

## Testing

The framework includes comprehensive test suites:

```bash
# Run unit tests
pytest tests/unit_tests/logic/cec/

# Run integration tests
pytest tests/integration/logic_cec/

# Run all CEC tests
pytest tests/ -k "cec"
```

## Architecture

```
CECFramework
├── DCECLibraryWrapper
│   └── DCEC_Library (submodule)
├── TalosWrapper
│   └── Talos (submodule)
├── EngDCECWrapper
│   └── Eng-DCEC (submodule)
└── ShadowProverWrapper
    └── ShadowProver (submodule)
```

## Reasoning Modes

The framework supports three reasoning modes:

1. **SIMULTANEOUS**: Standard first-order logic reasoning
2. **TEMPORAL**: Temporal reasoning with time-dependent operators
3. **HYBRID**: Combination of simultaneous and temporal reasoning

## Error Handling

The framework provides graceful degradation:
- If a component fails to initialize, others continue to work
- Each operation returns detailed error messages
- Statistics track success/failure rates

## Documentation Structure

The CEC module has comprehensive documentation organized as follows:

### 📚 User Documentation
- **[README.md](./README.md)** (this file) - Main entry point and overview
- **[STATUS.md](./STATUS.md)** - Implementation status, coverage, roadmap ⭐ **Single source of truth**
- **[QUICKSTART.md](./QUICKSTART.md)** - 5-minute tutorial for beginners
- **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** - Comprehensive system guide
- **[MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md)** - Guide for migrating from submodules

### 💻 Developer Documentation
- **[API_REFERENCE.md](./API_REFERENCE.md)** - Complete API documentation (50+ classes, 100+ examples)
- **[DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)** - Development setup, testing, contribution workflow

### 🗺️ Planning Documents
- **[COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md](./COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md)** - Master plan (8 phases, 31 weeks)
- **[API_INTERFACE_DESIGN.md](./API_INTERFACE_DESIGN.md)** - REST API design (30+ endpoints)
- **[PERFORMANCE_OPTIMIZATION_PLAN.md](./PERFORMANCE_OPTIMIZATION_PLAN.md)** - Performance optimization strategy
- **[EXTENDED_NL_SUPPORT_ROADMAP.md](./EXTENDED_NL_SUPPORT_ROADMAP.md)** - Multi-language NL support roadmap
- **[ADDITIONAL_THEOREM_PROVERS_STRATEGY.md](./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md)** - Additional prover integrations
- **[REFACTORING_QUICK_REFERENCE.md](./REFACTORING_QUICK_REFERENCE.md)** - Quick reference guide

### 📦 Archive
- **[ARCHIVE/](./ARCHIVE/)** - Historical documentation (superseded by current docs)

---

## Future Development

See [COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md](./COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md) for the complete roadmap.

**Five key development areas:**
1. ✅ **Native Python implementations** (81% complete - Phase 1-4)
2. 📋 **Extended NL support** (Planned - Phase 5)
3. 📋 **Additional theorem provers** (Z3, Vampire, E, Isabelle, Coq - Phase 6)
4. 📋 **Performance optimizations** (2-4x improvement - Phase 7)
5. 📋 **API interface** (REST API - Phase 8)

**Current Phase:** Phase 1 - Documentation Consolidation (86% complete)

---

## Contributing

See [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) for detailed contribution guidelines.
**Quick guidelines:**
1. Follow existing code patterns (see [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md))
2. Add comprehensive tests (90%+ coverage target)
3. Update documentation (docstrings + markdown)
4. Ensure backward compatibility

## References

- **Event Calculus**: Kowalski & Sergot (1986)
- **Deontic Logic**: Standard Deontic Logic (SDL)
- **Cognitive Logic**: Belief-Desire-Intention (BDI) framework
- **DCEC**: Deontic Cognitive Event Calculus extensions

## License

See the main repository LICENSE file for details.

## Support

**Documentation:**
- Start with [QUICKSTART.md](./QUICKSTART.md) for a 5-minute tutorial
- Check [STATUS.md](./STATUS.md) for current implementation status
- See [API_REFERENCE.md](./API_REFERENCE.md) for complete API documentation
- Review [CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md) for comprehensive guide

**Questions or Issues:**
- Check the test files in `tests/unit_tests/logic/CEC/` for usage examples
- Review component documentation in this folder
- Open an issue on [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- Start a discussion on [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)

---

**Last Updated:** 2026-02-18  
**Implementation Status:** 81% coverage, production-ready  
**Phase:** Phase 1 - Documentation Consolidation (86% complete)

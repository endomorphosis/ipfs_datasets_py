# TDFOL Unified Refactoring Roadmap 2026 (REVISED)

**Document Version:** 2.1 (REVISED to reflect existing infrastructure)  
**Created:** 2026-02-18  
**Revised:** 2026-02-18  
**Status:** 🟢 COMPLETE (Phases 1-12) | 📋 PLANNING (Phases 13-18)  
**Scope:** Comprehensive refactoring, improvements, and future enhancements

---

## ⚠️ REVISION NOTICE

**This document has been revised to reflect the existing infrastructure:**
- ✅ **MCP Server** (not REST API) - already exists at `ipfs_datasets_py/mcp_server/`
- ✅ **External ATPs** - already exist at `ipfs_datasets_py/logic/external_provers/`
- ✅ **LLM Router** - already exists at `ipfs_datasets_py/llm_router.py`
- ✅ **Docker/Kubernetes** - already exist in `docker/` and `deployments/kubernetes/`
- ✅ **CLI Tool** - `ipfs-datasets` wrapper already exists

---

## Executive Summary

This document provides a **unified, comprehensive roadmap** for the TDFOL (Temporal Deontic First-Order Logic) module, covering completed work (Phases 1-12) and future enhancement opportunities (Phases 13-18).

### Quick Stats

| Metric | Current | Target (Future) | Status |
|--------|---------|-----------------|--------|
| **LOC** | 19,311 | 24,000+ | 🟢 80% |
| **Tests** | 765 | 1,050+ | 🟢 73% |
| **Coverage** | 85% | 95%+ | 🟡 Target |
| **Pass Rate** | 91.5% | 100% | 🟡 Improving |
| **Performance** | 20-500x | 100-1000x | 🟢 Good |
| **Production Ready** | ✅ Yes | ✅ Yes | 🟢 Complete |

### Document Navigation

- **Current Status:** See [STATUS_2026.md](./STATUS_2026.md)
- **Quick Start:** See [README.md](./README.md)
- **API Reference:** See [QUICK_REFERENCE_2026_02_18.md](./QUICK_REFERENCE_2026_02_18.md)
- **This Document:** Master planning and roadmap (REVISED)

---

## Table of Contents

1. [Overview](#overview)
2. [Completed Work: Phases 1-12](#completed-work-phases-1-12)
3. [Future Enhancements: Phases 13-18 (REVISED)](#future-enhancements-phases-13-18-revised)
4. [Code Quality Improvements](#code-quality-improvements)
5. [Performance Optimization](#performance-optimization)
6. [Testing Strategy](#testing-strategy)
7. [Documentation Plan](#documentation-plan)
8. [Deployment & Operations](#deployment--operations)
9. [Risk Assessment](#risk-assessment)
10. [Success Metrics](#success-metrics)
11. [Timeline & Resources](#timeline--resources)
12. [Appendices](#appendices)

---

## Overview

### Mission Statement

Transform TDFOL into the **premier open-source neurosymbolic reasoning engine** combining:
- Symbolic theorem proving
- Neural pattern matching  
- Knowledge graph integration
- Production-ready deployment
- **MCP-based distributed systems** (P2P/IPFS/IPLD)

### Strategic Goals

1. ✅ **Completeness** - Full TDFOL reasoning (FOL + Deontic + Temporal)
2. ✅ **Performance** - 20-500x speedup through optimization
3. ✅ **Usability** - Natural language interfaces
4. ✅ **Visualization** - Intuitive proof exploration
5. ✅ **Production Ready** - Security, testing, documentation
6. 📋 **Ecosystem Integration** - MCP server, external ATPs, LLM router
7. 📋 **Global Reach** - Multi-language support via LLM
8. 📋 **Documentation** - Modern Markdown documentation

### Architecture Vision

```
┌─────────────────────────────────────────────────────────────────┐
│                     TDFOL Reasoning Engine                      │
│              (Temporal + Deontic + First-Order Logic)           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ▼                       ▼                       ▼
┌─────────┐         ┌──────────────┐       ┌─────────────┐
│   NL    │────────▶│    Parser    │◀──────│   String    │
│ (20+    │         │ (40+ tokens) │       │  (Symbolic) │
│patterns)│         └──────┬───────┘       └─────────────┘
└─────────┘                │
    │                      │
    │ (via llm_router)     │
    ▼                      ▼
┌─────────────┐    ┌──────────────┐
│  LLM Router │    │    Prover    │
│ (OpenAI,    │    │  (50+ rules) │
│  Gemini,    │    └──────┬───────┘
│  Claude)    │           │
└─────────────┘           │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌────────────┐    ┌────────────────┐  ┌──────────────┐
│   Modal    │    │  Optimization  │  │    Cache     │
│  Tableaux  │    │ (4 strategies) │  │ (100-20000x) │
│ (K,T,D,S4,│    │  Parallel (5x) │  │              │
│    S5)    │    │   A* (10x)     │  │              │
└─────┬──────┘    └────────┬───────┘  └──────┬───────┘
      │                    │                  │
      └────────────────────┼──────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
        ▼                                     ▼
┌────────────────┐                   ┌────────────────┐
│  Visualization │                   │   Converters   │
│   - Proof trees│                   │  - TDFOL↔DCEC  │
│   - Dep graphs │                   │  - TDFOL→FOL   │
│   - Dashboards │                   │  - TDFOL→TPTP  │
└────────────────┘                   └────────────────┘
        │                                     │
        └─────────────────┬───────────────────┘
                          │
                ┌─────────┴──────────┐
                │                    │
                ▼                    ▼
      ┌──────────────────┐  ┌────────────────┐
      │  MCP Server (✅) │  │ External ATPs  │
      │  - P2P/IPFS      │  │ ✅ Z3, CVC5    │
      │  - IPLD          │  │ ✅ Lean, Coq   │
      │  - Multi-node    │  │ ✅ SymbolicAI  │
      └──────────────────┘  └────────────────┘
                │                    │
                └────────┬───────────┘
                         │
                         ▼
              ┌────────────────────┐
              │  CLI Tool (✅)     │
              │  ipfs-datasets     │
              │                    │
              │  Docker/K8s (✅)   │
              └────────────────────┘
```

---

## Completed Work: Phases 1-12

[... Keep all the existing Phases 1-12 content unchanged from the original ...]

---

## Future Enhancements: Phases 13-18 (REVISED)

### Overview

Now that TDFOL is production-ready, the following phases focus on **integrating with existing infrastructure**, **enhancing current systems**, and **modernizing documentation**.

**Total Estimated Effort:** 14-19 weeks (~280-380 hours)

**Key Change:** We leverage existing infrastructure rather than building from scratch.

---

### Phase 13: MCP Server Integration Enhancement (REVISED)

**Duration:** 2-3 weeks  
**Effort:** 30-40 hours  
**Priority:** 🔴 High  
**Status:** 📋 Planned

**⚠️ CHANGE:** Instead of building a REST API, we integrate TDFOL with the **existing MCP server** at `ipfs_datasets_py/mcp_server/`.

#### Goals

1. Integrate TDFOL with existing MCP server infrastructure
2. Add TDFOL tools to MCP tool registry
3. Enable P2P/IPFS/IPLD distributed proving
4. Support multi-node theorem proving clusters

#### Deliverables

**13.1: MCP Tool Integration (15-20h)**
```python
ipfs_datasets_py/mcp_server/tools/logic_tools/
├── tdfol_parse_tool.py                # 150 LOC
│   ├── @tool_metadata decorator
│   ├── Parse symbolic/NL formulas
│   └── Return TDFOL AST

├── tdfol_prove_tool.py                # 200 LOC
│   ├── @tool_metadata decorator
│   ├── Prove formulas with strategies
│   ├── Batch proving support
│   └── P2P distributed proving

├── tdfol_convert_tool.py              # 150 LOC
│   ├── @tool_metadata decorator
│   ├── TDFOL ↔ DCEC, FOL, TPTP
│   └── Format validation

├── tdfol_visualize_tool.py            # 150 LOC
│   ├── @tool_metadata decorator
│   ├── Proof trees, dependency graphs
│   └── Countermodel visualization

└── tdfol_kb_tool.py                   # 100 LOC
    ├── @tool_metadata decorator
    ├── KB management (create, add, query)
    └── IPFS storage integration
```

**Total:** ~750 LOC

**13.2: P2P/IPFS Integration (10-15h)**
```python
ipfs_datasets_py/logic/TDFOL/p2p/
├── distributed_prover.py              # 300 LOC
│   ├── Multi-node proof coordination
│   ├── Work distribution via IPLD
│   └── Result aggregation

├── ipfs_proof_storage.py              # 200 LOC
│   ├── Store proofs on IPFS
│   ├── CID-based retrieval
│   └── Proof verification

└── p2p_knowledge_base.py              # 200 LOC
    ├── Distributed KB storage
    ├── IPLD-based formula graphs
    └── Multi-node consistency
```

**Total:** ~700 LOC

**13.3: CLI Integration (5h)**
```bash
# Existing CLI tool: ipfs-datasets
# Add TDFOL subcommands

ipfs-datasets logic prove "∀x.(P(x) → Q(x))" --kb axioms.tdfol
ipfs-datasets logic parse "All doctors must respect privacy"
ipfs-datasets logic convert dcec-to-tdfol input.dcec
ipfs-datasets logic visualize proof.json --output tree.png
```

**13.4: Documentation & Testing (5-10h)**
- MCP tool documentation
- Integration tests (30+ tests)
- P2P/IPFS deployment guide
- CLI usage examples

#### Success Metrics

- 📊 5+ TDFOL tools in MCP registry
- 📊 P2P proving across 3+ nodes
- 📊 IPFS-based proof storage
- 📊 CLI integration complete
- 📊 30+ integration tests

---

### Phase 14: LLM Router Integration for NL Enhancement (REVISED)

**Duration:** 3-4 weeks  
**Effort:** 50-60 hours  
**Priority:** 🟡 Medium  
**Status:** 📋 Planned

**⚠️ CHANGE:** Instead of building multi-language NL from scratch, we integrate with the **existing llm_router** at `ipfs_datasets_py/llm_router.py`.

#### Goals

1. Use llm_router for accessing LLMs (OpenAI, Gemini, Claude, etc.)
2. Multi-language support via LLM translation
3. Enhance pattern-based NL with LLM fallback
4. Improve accuracy from 80% to 95%+

#### Deliverables

**14.1: LLM Router Integration (20-25h)**
```python
ipfs_datasets_py/logic/TDFOL/nl/
├── llm_nl_converter.py                # 400 LOC
│   ├── Use llm_router for NL → TDFOL
│   ├── Multi-language support
│   │   ├── English, Spanish, French, German
│   │   ├── Via LLM translation
│   │   └── Language auto-detection
│   ├── Hybrid approach
│   │   ├── Try pattern-based first
│   │   └── Fallback to LLM
│   └── Confidence scoring

├── llm_pattern_generator.py           # 300 LOC
│   ├── Generate patterns from examples
│   ├── LLM-based pattern mining
│   └── Continuous learning

└── llm_context_resolver.py            # 200 LOC
    ├── LLM-based entity resolution
    ├── Coreference with LLM
    └── Ambiguity resolution
```

**Total:** ~900 LOC

**14.2: Domain-Specific Enhancement (15-20h)**
```python
ipfs_datasets_py/logic/TDFOL/nl/domains/
├── medical_llm_patterns.py            # 300 LOC
│   ├── Medical terminology via LLM
│   ├── HIPAA compliance patterns
│   └── Clinical reasoning

├── financial_llm_patterns.py          # 300 LOC
│   ├── Financial regulations
│   ├── Compliance requirements
│   └── Risk assessment logic

└── regulatory_llm_patterns.py         # 300 LOC
    ├── Legal requirements
    ├── Regulatory frameworks
    └── Compliance checking
```

**Total:** ~900 LOC

**14.3: Testing & Validation (15-15h)**
- Multi-language test suite (100 tests)
- Domain-specific tests (50 tests)
- Accuracy benchmarking
- LLM router configuration guide

#### Usage Example

```python
from ipfs_datasets_py.logic.TDFOL.nl import LLMNLConverter
from ipfs_datasets_py.llm_router import get_llm

# Initialize with llm_router
llm = get_llm(provider='openai')  # or 'gemini', 'claude', etc.
converter = LLMNLConverter(llm=llm)

# Multi-language support
formula_en = converter.convert("All doctors must respect patient privacy")
formula_es = converter.convert("Todos los médicos deben respetar la privacidad del paciente")
formula_fr = converter.convert("Tous les médecins doivent respecter la vie privée des patients")

# All produce: ∀x.(Doctor(x) → O(RespectPrivacy(PatientData)))

# Domain-specific
medical_formula = converter.convert(
    "HIPAA requires healthcare providers to protect patient data",
    domain='medical'
)
```

#### Success Metrics

- 📊 95%+ accuracy (up from 80%)
- 📊 4 languages supported (EN, ES, FR, DE)
- 📊 3 domain specializations
- 📊 150+ tests
- 📊 LLM router integration

---

### Phase 15: External ATP Integration Enhancement (REVISED)

**Duration:** 2-3 weeks  
**Effort:** 30-40 hours  
**Priority:** 🟡 Medium  
**Status:** 📋 Planned

**⚠️ CHANGE:** Instead of building ATP integrations from scratch, we **enhance the existing prover_router** at `ipfs_datasets_py/logic/external_provers/`.

#### Goals

1. Add TDFOL support to existing external provers
2. Unified integration path for FOL, CEC, Deontic, and TDFOL
3. Leverage existing prover_router infrastructure
4. Enable automatic prover selection for TDFOL formulas

#### Existing Infrastructure

```
ipfs_datasets_py/logic/external_provers/  ✅ Already exists!
├── prover_router.py                    # ✅ Intelligent routing
├── proof_cache.py                      # ✅ CID-based caching
├── monitoring.py                       # ✅ Performance tracking
├── smt/
│   ├── z3_prover_bridge.py            # ✅ Z3 (17.2 KB)
│   └── cvc5_prover_bridge.py          # ✅ CVC5 (12 KB)
├── interactive/
│   ├── lean_prover_bridge.py          # ✅ Lean 4 (9.7 KB)
│   └── coq_prover_bridge.py           # ✅ Coq (9.7 KB)
└── neural/
    └── symbolicai_prover_bridge.py    # ✅ SymbolicAI (14.2 KB)
```

#### Deliverables

**15.1: TDFOL Support in External Provers (15-20h)**
```python
# Extend existing prover bridges
ipfs_datasets_py/logic/external_provers/

# Add TDFOL conversion in each bridge:
smt/z3_prover_bridge.py                 # Add TDFOL → SMT-LIB
smt/cvc5_prover_bridge.py               # Add TDFOL → SMT-LIB
interactive/lean_prover_bridge.py       # Add TDFOL → Lean
interactive/coq_prover_bridge.py        # Add TDFOL → Coq
neural/symbolicai_prover_bridge.py      # Add TDFOL understanding

# New: Unified logic bridge
ipfs_datasets_py/logic/integration/
└── unified_logic_bridge.py             # 400 LOC
    ├── Common path for FOL, CEC, Deontic, TDFOL
    ├── Automatic logic detection
    ├── Format conversion layer
    └── Prover selection strategy
```

**15.2: Enhanced Prover Router (10-15h)**
```python
# Extend existing prover_router.py
ipfs_datasets_py/logic/external_provers/prover_router.py

# Add:
- TDFOL formula analysis
- Temporal/deontic operator detection
- Automatic prover selection for TDFOL
- Parallel proving for TDFOL formulas
```

**15.3: Testing & Documentation (5-5h)**
- TDFOL integration tests (50+ tests)
- Unified logic bridge tests
- Prover selection benchmarks
- Integration guide

#### Usage Example

```python
from ipfs_datasets_py.logic.external_provers import ProverRouter
from ipfs_datasets_py.logic.TDFOL import parse

# Existing router - now with TDFOL support!
router = ProverRouter(
    enable_z3=True,
    enable_symbolicai=True,
    enable_native=True
)

# Parse TDFOL formula
formula = parse("∀x.(Person(x) → O(□PayTax(x)))")

# Automatic prover selection
result = router.prove(formula, strategy='auto')
# Router analyzes: Has temporal (□) and deontic (O) operators
# Selects: Native TDFOL prover (best for modal logic)

# Or try all provers in parallel
results = router.prove_parallel(formula, timeout=10.0)
best = router.select_best(results)
print(f"Best prover: {best.prover_used}")
print(f"Proof time: {best.proof_time:.3f}s")
```

#### Success Metrics

- 📊 5 external provers support TDFOL
- 📊 Unified logic bridge for FOL/CEC/Deontic/TDFOL
- 📊 Automatic prover selection
- 📊 50+ integration tests
- 📊 90%+ problem coverage

---

### Phase 16: GraphRAG Deep Integration

**Duration:** 4-5 weeks  
**Effort:** 80-100 hours  
**Priority:** 🔴 High  
**Status:** 📋 Planned

**✅ NO CHANGE:** This phase remains as originally planned.

[... Keep Phase 16 content from original ...]

---

### Phase 17: Performance & Scalability

**Duration:** 2-3 weeks  
**Effort:** 40-50 hours  
**Priority:** 🟢 Low  
**Status:** 📋 Planned

**✅ NO CHANGE:** This phase remains as originally planned.

[... Keep Phase 17 content from original ...]

---

### Phase 18: Documentation Modernization (NEW)

**Duration:** 1-2 weeks  
**Effort:** 20-30 hours  
**Priority:** 🟡 Medium  
**Status:** 📋 Planned

**🆕 NEW PHASE:** Convert Sphinx documentation to modern Markdown format.

#### Goals

1. Convert all Sphinx RST files to Markdown
2. Deprecate HTML/CSS bloat
3. Integrate with main documentation structure
4. Improve maintainability and readability

#### Current State

```
docs/tdfol/                            # 266 lines of RST
├── *.rst files (16 files)
├── conf.py (Sphinx config)
└── HTML/CSS artifacts
```

#### Deliverables

**18.1: RST to Markdown Conversion (10-15h)**
```markdown
ipfs_datasets_py/logic/TDFOL/docs/
├── API_REFERENCE.md                   # Converted from api/*.rst
│   ├── Core API
│   ├── Parser API
│   ├── Prover API
│   ├── Optimization API
│   ├── Visualization API
│   └── Security API
│
├── USER_GUIDE.md                      # User documentation
│   ├── Getting started
│   ├── Basic usage
│   ├── Advanced features
│   └── Best practices
│
├── DEVELOPER_GUIDE.md                 # Developer documentation
│   ├── Architecture
│   ├── Contributing
│   ├── Testing
│   └── Code style
│
└── EXAMPLES.md                        # Example gallery
    ├── Basic examples
    ├── Advanced examples
    ├── Domain-specific examples
    └── Integration examples
```

**18.2: Integration with Main Docs (5-10h)**
- Link from main README
- Update INDEX.md
- Cross-reference other docs
- Update CI/CD to build Markdown

**18.3: Cleanup (5-5h)**
- Remove Sphinx configuration
- Delete HTML/CSS artifacts
- Update .gitignore
- Archive old docs

#### Success Metrics

- 📊 All 16 RST files converted to 4 MD files
- 📊 Zero HTML/CSS artifacts
- 📊 Integrated with main documentation
- 📊 Improved readability and maintainability

---

## Updated Timeline & Resources

### Completed Timeline (Phases 1-12)

[... Keep original content ...]

### Future Timeline (Phases 13-18) - REVISED

**Phase 13: MCP Server Integration** (2-3 weeks, 30-40h)
- Week 26-27: MCP tool integration, P2P/IPFS integration
- Week 28: CLI integration, testing

**Phase 14: LLM Router Integration** (3-4 weeks, 50-60h)
- Week 29-30: LLM router integration
- Week 31: Domain-specific enhancement
- Week 32: Testing & validation

**Phase 15: External ATP Enhancement** (2-3 weeks, 30-40h)
- Week 33: TDFOL support in external provers
- Week 34: Enhanced prover router
- Week 35: Testing & documentation

**Phase 16: GraphRAG Deep Integration** (4-5 weeks, 80-100h)
- Week 36-40: As originally planned

**Phase 17: Performance & Scalability** (2-3 weeks, 40-50h)
- Week 41-43: As originally planned

**Phase 18: Documentation Modernization** (1-2 weeks, 20-30h)
- Week 44-45: RST to Markdown conversion, cleanup

**Total Future:** 14-19 weeks, ~280-380 hours (down from 16-22 weeks, 320-440 hours)

### Resource Requirements

**Development:**
- 1-2 senior developers
- Access to existing infrastructure (MCP server, llm_router, external_provers)
- LLM API access (OpenAI, Gemini, Claude)

**Infrastructure:**
- ✅ MCP server (already exists)
- ✅ Docker registry (already exists)
- ✅ Kubernetes cluster (already exists)
- ✅ CI/CD pipeline (already exists)

**Testing:**
- Multi-language NL datasets
- Standard theorem proving benchmarks
- Performance testing environment

---

## Summary of Changes

### What Changed

1. **Phase 13** (was REST API) → **MCP Server Integration**
   - Leverage existing MCP server
   - Add TDFOL tools to registry
   - P2P/IPFS distributed proving
   - **Reduced effort:** 40-50h → 30-40h

2. **Phase 14** (Multi-Language NL) → **LLM Router Integration**
   - Use existing llm_router
   - LLM-based multi-language support
   - Enhance pattern-based approach
   - **Reduced effort:** 80-100h → 50-60h

3. **Phase 15** (External ATPs) → **External ATP Enhancement**
   - Extend existing prover_router
   - Add TDFOL support to existing provers
   - Unified logic integration path
   - **Reduced effort:** 60-70h → 30-40h

4. **Phase 16-17** → **No changes** (keep as planned)

5. **NEW Phase 18** → **Documentation Modernization**
   - Convert Sphinx RST to Markdown
   - Deprecate HTML/CSS
   - **New effort:** 20-30h

### Total Impact

- **Timeline:** 16-22 weeks → 14-19 weeks (**2-3 weeks faster**)
- **Effort:** 320-440 hours → 280-380 hours (**40-60 hours less**)
- **Leverages:** 5 existing systems (MCP, llm_router, external_provers, Docker/K8s, CLI)
- **Quality:** Higher (using battle-tested infrastructure)

---

**Last Updated:** 2026-02-18 (REVISED)  
**Version:** 2.1  
**Status:** 🟢 Phases 1-12 COMPLETE | 📋 Phases 13-18 PLANNED  
**Maintainers:** IPFS Datasets Team

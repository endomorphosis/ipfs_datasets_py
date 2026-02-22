# Logic Module Documentation Index

**Last Updated:** 2026-02-20  
**Status:** Consolidated — 195 total markdown files (69 active, 126 archived)

This index provides a comprehensive guide to all documentation in the logic module, organized by purpose and audience.

---

## 📚 Quick Navigation

- [Getting Started](#getting-started)
- [Architecture & Design](#architecture--design)
- [Current Refactoring](#current-refactoring-status)
- [API Reference](#api-reference)
- [Development Guides](#development-guides)
- [Historical Records](#historical-records)

---

## Getting Started

### Essential Reading (Start Here)

| Document | Purpose | Audience |
|----------|---------|----------|
| [README.md](./README.md) | **Main module overview** - Features, installation, quick start | All users |
| [UNIFIED_CONVERTER_GUIDE.md](./UNIFIED_CONVERTER_GUIDE.md) | Unified converter architecture usage | Developers |
| [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) | How to migrate from old APIs to new unified system | Existing users |

**Estimated Reading Time:** 30-45 minutes

---

## Architecture & Design

### Current Architecture (Production)

| Document | Content | Status |
|----------|---------|--------|
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | **Visual architecture guide** - Mermaid diagrams for module dependencies, converters, caches, data flows, ZKP, integration | ✅ Production |
| [FEATURES.md](./FEATURES.md) | **Complete feature catalog** - All 12+ features documented | ✅ Current (v2.0) |

### Specialized Components

**Quick Start Guides:** Hands-on examples and practical usage

| Module | Description | Guide |
|--------|-------------|-------|
| **[fol/README.md](./fol/README.md)** | **FOL Conversion** - Text → First-Order Logic (NLP + ML) | ✨ NEW |
| **[deontic/README.md](./deontic/README.md)** | **Legal Logic** - Obligations, permissions, prohibitions | ✨ NEW |
| **[common/README.md](./common/README.md)** | **Utilities** - BoundedCache (TTL+LRU), base classes | ✅ UPDATED |

**Architecture Documentation:**

| Document | Content |
|----------|---------|
| [zkp/README.md](./zkp/README.md) | Zero-Knowledge Proof system |
| [TDFOL/README.md](./TDFOL/README.md) | Temporal Deontic First-Order Logic |
| [CEC/CEC_SYSTEM_GUIDE.md](./CEC/CEC_SYSTEM_GUIDE.md) | Cognitive Event Calculus |
| [common/CONVERTER_USAGE.md](./common/CONVERTER_USAGE.md) | Base converter framework |
| [external_provers/README.md](./external_provers/README.md) | External theorem prover integration |
| [types/README.md](./types/README.md) | Type system documentation |

**Total Architecture Documentation:** ~95 KB

---

## API Reference

```python
# Primary converters (unified architecture)
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.deontic import DeonticConverter

# See UNIFIED_CONVERTER_GUIDE.md for complete API
```

### Integration APIs

```python
# Integration layer
from ipfs_datasets_py.logic.integration import (
    ProofExecutionEngine,
    DeonticLogicConverter,
    SymbolicFOLBridge,
    TDFOLCECBridge,
    TDFOLGrammarBridge,
)

# Subsystems
from ipfs_datasets_py.logic.integration.caching import ProofCache
from ipfs_datasets_py.logic.integration.reasoning import DeontologicalReasoningEngine

# See integration/__init__.py for full API
```

### Core Logic APIs

```python
# TDFOL (Temporal Deontic First-Order Logic)
from ipfs_datasets_py.logic.TDFOL import TDFOLParser, TDFOLProver

# CEC (Cognitive Event Calculus)  
from ipfs_datasets_py.logic.CEC import CEC_wrapper

# See module README files for details
```

---

## Current Refactoring Status

### Active Planning Documents (2026-02-20)

| Document | Purpose | Status |
|----------|---------|--------|
| **[MASTER_REFACTORING_PLAN_2026.md](./MASTER_REFACTORING_PLAN_2026.md)** | **Master refactoring plan** - Authoritative 5-phase plan (v5.1) | ✅ ACTIVE |
| **[PROJECT_STATUS.md](./PROJECT_STATUS.md)** | **Current status snapshot** - Verified metrics and implementation status | ✅ Current |
| **[EVERGREEN_IMPROVEMENT_PLAN.md](./EVERGREEN_IMPROVEMENT_PLAN.md)** | **Ongoing improvement backlog** - Continuous quality loops and prioritized slices | 🔄 Ongoing |
| [integration/CHANGELOG.md](./integration/CHANGELOG.md) | Integration-specific changelog | 📋 Reference |
| [integration/TODO.md](./integration/TODO.md) | Integration-specific Phase 2 tasks | 📋 Reference |

### Refactoring Summary (2026-02-20)

Phases 1, 3, and 5 are complete; Phases 2 and 4 are ongoing:

1. **Phase 1 ✅ COMPLETE** — Documentation Consolidation (196 → 69 active files)
2. **Phase 2 🔄 In Progress** — Code Quality (CEC inference rules ✅, NL accuracy pending)
3. **Phase 3 ✅ COMPLETE** — Feature Completions (27 MCP tools, GraphRAG integration)
4. **Phase 4 🔄 Ongoing** — Production Excellence (validators ✅, CI gates pending)
5. **Phase 5 ✅ COMPLETE** — God-Module Splits (all 6 oversized files decomposed)

For details, see [MASTER_REFACTORING_PLAN_2026.md](./MASTER_REFACTORING_PLAN_2026.md).

---

## Development Guides

### Contributing & Development

| Document | Purpose |
|----------|---------|
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Contribution guidelines |
| [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) | Honest assessment of limitations and workarounds |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | Common issues and solutions |
| [docs/archive/README.md](./docs/archive/README.md) | Historical archive index |

### Planning Documents (Reference)

| Document | Status | Use |
|----------|--------|-----|
| [MASTER_REFACTORING_PLAN_2026.md](./MASTER_REFACTORING_PLAN_2026.md) | ✅ Active (v5.1) | Authoritative improvement roadmap |
| [EVERGREEN_IMPROVEMENT_PLAN.md](./EVERGREEN_IMPROVEMENT_PLAN.md) | 🔄 Ongoing | Continuous quality improvement backlog |
| [PROJECT_STATUS.md](./PROJECT_STATUS.md) | ✅ Current | Verified status and metrics |

---

## Historical Records

### Completed Phase Reports

All phase completion reports have been archived to maintain repository cleanliness while preserving history:

| Report | Location | Completion Date |
|--------|----------|-----------------|
| Phase 1-5 Reports | [docs/archive/](./docs/archive/) | 2026-02-13/14 |
| Phase 6 Completion | [docs/archive/phases/PHASE_6_COMPLETION_SUMMARY.md](./docs/archive/phases/) | 2026-02-14 |
| Phase 7 Session | [docs/archive/phases/PHASE_7_SESSION_SUMMARY.md](./docs/archive/phases/) | 2026-02-17 |
| Final Status (Pre-refactor) | [docs/archive/phases/FINAL_STATUS_REPORT.md](./docs/archive/phases/) | 2026-02-17 |
| Analysis Summary | [docs/archive/phases/ANALYSIS_SUMMARY.md](./docs/archive/phases/) | 2026-02-17 |
| Planning Docs (archived) | [docs/archive/planning/](./docs/archive/planning/) | 2026-02-19 |
| Session Notes | [docs/archive/sessions/](./docs/archive/sessions/) | 2026-02-17 |

---

## Testing & Validation

### Running Tests

```bash
# All logic module tests
pytest tests/unit_tests/logic/ -v

# Integration tests only
pytest tests/unit_tests/logic/integration/ -v

# With coverage
pytest tests/unit_tests/logic/ --cov=ipfs_datasets_py.logic
```

**Test Status:** 1,744+ tests across 168 test files, ~87% pass rate (790+ tests in production-ready core modules).

---

## Module Structure Reference

### Physical Organization

```
ipfs_datasets_py/logic/
├── README.md                   # Main documentation (START HERE)
├── DOCUMENTATION_INDEX.md      # This file
├── MASTER_REFACTORING_PLAN_2026.md  # Active improvement plan (v5.1)
├── FEATURES.md                 # Feature catalog
├── MIGRATION_GUIDE.md          # Migration from old APIs
├── UNIFIED_CONVERTER_GUIDE.md  # Converter usage guide
│
├── common/                     # Shared utilities
│   ├── README.md
│   ├── CONVERTER_USAGE.md
│   ├── converters.py          # Base converter framework
│   ├── utility_monitor.py     # Performance monitoring
│   ├── validators.py          # Input validation + injection detection
│   ├── proof_cache.py         # Shared proof cache
│   └── errors.py              # Common exceptions
│
├── types/                      # Type definitions
│   └── README.md
│
├── fol/                        # First-Order Logic
│   ├── README.md
│   ├── converter.py           # FOL converter (unified)
│   └── text_to_fol.py         # NLP parser
│
├── deontic/                    # Deontic Logic
│   ├── README.md
│   ├── converter.py           # Deontic converter (unified)
│   └── legal_text_to_deontic.py
│
├── TDFOL/                      # Temporal Deontic FOL (19,311 LOC)
│   ├── README.md
│   ├── tdfol_core.py
│   ├── tdfol_parser.py
│   ├── tdfol_prover.py
│   ├── modal_tableaux.py
│   └── inference_rules/       # 50 TDFOL inference rules
│
├── CEC/                        # Cognitive Event Calculus (8,547 LOC)
│   ├── CEC_SYSTEM_GUIDE.md
│   ├── native/                # Native Python implementation
│   │   ├── prover_core.py     # Core proof search (~649 LOC after split)
│   │   ├── dcec_core.py       # DCEC data model (~849 LOC after split)
│   │   └── inference_rules/   # 67 CEC rules (8 modules)
│   └── *.py                   # Wrapper modules
│
├── integration/                # Integration layer (~10,000 LOC)
│   ├── __init__.py            # Main integration API
│   ├── bridges/               # Cross-module bridges
│   ├── caching/               # Caching subsystem
│   ├── reasoning/             # Reasoning engines (split into focused files)
│   ├── converters/            # Integration converters
│   ├── domain/                # Domain models
│   ├── symbolic/              # Neurosymbolic integration
│   ├── interactive/           # Interactive tools
│   └── demos/                 # Example applications
│
├── zkp/                        # Zero-Knowledge Proofs (simulation only)
│   ├── README.md
│   ├── zkp_prover.py
│   ├── zkp_verifier.py
│   └── circuits.py
│
├── external_provers/           # External theorem provers (Z3, Lean, Coq)
│   ├── README.md
│   └── *.py
│
├── security/                   # Security features
│   └── rate_limiting.py
│
└── docs/                       # Additional documentation
    └── archive/               # Historical records (126 files)
        ├── sessions/          # Session notes
        ├── phases/            # Phase completion reports
        ├── phases_2026/       # 2026 phase reports
        ├── planning/          # Archived planning docs
        ├── HISTORICAL/        # Pre-2026 records
        └── README.md          # Archive index
```

---

## Documentation Maintenance

### Adding New Documentation

1. **API Documentation** - Add docstrings to code, update module README
2. **User Guides** - Create in root `logic/` directory
3. **Architecture Changes** - Update FEATURES.md and DOCUMENTATION_INDEX.md
4. **Session Notes** - Archive immediately after completion to `docs/archive/sessions/`

### Document Lifecycle

- **Active** - In root `logic/` directory, regularly updated
- **Reference** - Still useful but not updated (e.g., planning docs after completion)
- **Archived** - Moved to `docs/archive/` with appropriate subdirectory

### Archive Policy (per MASTER_REFACTORING_PLAN_2026.md §7.4)

Documents are archived when:
- Phase/project completion reports after work is done
- Session notes after session ends
- Superseded documentation when replaced by newer versions
- Historical planning documents after plans are executed

**Never create new markdown files in active directories for progress reports** — use git commit messages for progress tracking instead.

---

## Getting Help

### Documentation Issues

If you find:
- **Outdated information** - Please open an issue or submit PR
- **Missing documentation** - Check archives first, then request addition
- **Unclear content** - Open issue with specific questions

### Support Channels

- **GitHub Issues** - Bug reports and feature requests
- **Discussions** - Questions and community support
- **Pull Requests** - Documentation improvements welcome

---

## Appendix

### Documentation Statistics

- **Total Markdown Files:** 195 (69 active, 126 archived)
- **Active Documents:** 20 root-level + 15 TDFOL + 14 CEC + 8 ZKP + 12 module READMEs
- **Archived Documents:** 126 historical records in `docs/archive/`, `TDFOL/ARCHIVE/`, `CEC/ARCHIVE/`, `zkp/ARCHIVE/`
- **Python Files:** 281 files (~93,529 LOC)
- **Test Files:** 168 test files, 1,744+ tests, ~87% pass rate
- **Type Coverage:** 95%+ (Grade A-, mypy validated)
- **Performance:** 14x cache speedup validated; 30-40% memory reduction with __slots__

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-14 | Initial consolidated index created |
| 1.1 | 2026-02-17 | Added refactoring status, updated with current planning docs, archived phase reports |
| 2.0 | 2026-02-20 | Major update: removed archived file references, updated counts, added Phase 5 completion, fixed statistics |

---

**For questions or updates, please contact the maintainers or open an issue.**

# Documentation Index

Complete index of all documentation in the complaint-generator repository.

## Quick Start

- [README.md](README.md) - Main project overview and getting started guide
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) - Complete configuration reference
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Production deployment guide
- [TESTING.md](TESTING.md) - Testing guide and TDD workflow
- [CONTRIBUTING.md](CONTRIBUTING.md) - How to contribute to the project

## MCP++ Integration

- [MCPPLUSPLUS_INTEGRATION_TODO.md](MCPPLUSPLUS_INTEGRATION_TODO.md) - Entry point for MCP++ integration work
- [MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md](MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md) - Infinite backlog for MCP++/P2P integration
- [plan-mcpPlusPlusIntegration.prompt.md](plan-mcpPlusPlusIntegration.prompt.md) - High-level integration plan

## Core Module Documentation

### Adversarial Testing Framework
- [adversarial_harness/README.md](adversarial_harness/README.md) - Complete guide to adversarial testing with all agents

### Complaint Analysis System
- [complaint_analysis/README.md](complaint_analysis/README.md) - Analysis framework for 14 complaint types

### Three-Phase Processing
- [complaint_phases/README.md](complaint_phases/README.md) - Knowledge graphs, dependency graphs, and neurosymbolic matching

### Mediator & Orchestration
- [mediator/readme.md](mediator/readme.md) - Core orchestration layer and hooks

### Testing
- [tests/README.md](tests/README.md) - Test suite documentation (19 files, 60+ test classes)

## Feature Documentation

### System Architecture
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture, data flows, and integration points
- [docs/APPLICATIONS.md](docs/APPLICATIONS.md) - CLI and web server applications guide

### Three-Phase System
- [docs/THREE_PHASE_SYSTEM.md](docs/THREE_PHASE_SYSTEM.md) - Detailed three-phase workflow documentation

### Configuration & Deployment
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) - Complete configuration reference
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Production deployment guide (Docker, K8s, Cloud)
- [docs/SECURITY.md](docs/SECURITY.md) - Security best practices and hardening

### Adversarial Testing
- [docs/ADVERSARIAL_HARNESS.md](docs/ADVERSARIAL_HARNESS.md) - Adversarial testing framework details
- [docs/ADVERSARIAL_IMPLEMENTATION_SUMMARY.md](docs/ADVERSARIAL_IMPLEMENTATION_SUMMARY.md) - Implementation summary

### Backend Systems
- [docs/BACKENDS.md](docs/BACKENDS.md) - LLM backend configuration and providers
- [docs/LLM_ROUTER.md](docs/LLM_ROUTER.md) - LLM routing details

### Complaint Analysis
- [docs/COMPLAINT_ANALYSIS_INTEGRATION.md](docs/COMPLAINT_ANALYSIS_INTEGRATION.md) - Integration with adversarial harness
- [docs/COMPLAINT_ANALYSIS_EXAMPLES.md](docs/COMPLAINT_ANALYSIS_EXAMPLES.md) - Usage examples

### Legal Research
- [docs/LEGAL_HOOKS.md](docs/LEGAL_HOOKS.md) - Legal analysis hooks (4-stage pipeline)
- [docs/LEGAL_AUTHORITY_RESEARCH.md](docs/LEGAL_AUTHORITY_RESEARCH.md) - Multi-source legal research

### Evidence Management
- [docs/EVIDENCE_MANAGEMENT.md](docs/EVIDENCE_MANAGEMENT.md) - IPFS storage and DuckDB metadata
- [docs/WEB_EVIDENCE_DISCOVERY.md](docs/WEB_EVIDENCE_DISCOVERY.md) - Automated web evidence discovery

### Search Integration
- [docs/SEARCH_HOOKS.md](docs/SEARCH_HOOKS.md) - Legal corpus RAG and search integration

### IPFS Integration
- [docs/IPFS_DATASETS_INTEGRATION.md](docs/IPFS_DATASETS_INTEGRATION.md) - IPFS integration guide
- [docs/IPFS_DATASETS_PY_INTEGRATION.md](docs/IPFS_DATASETS_PY_INTEGRATION.md) - Python IPFS integration

### DEI Analysis (HACC)
- [docs/HACC_INTEGRATION.md](docs/HACC_INTEGRATION.md) - DEI policy analysis
- [docs/HACC_INTEGRATION_ARCHITECTURE.md](docs/HACC_INTEGRATION_ARCHITECTURE.md) - Architecture details
- [docs/HACC_ANALYSIS_README.md](docs/HACC_ANALYSIS_README.md) - Analysis guide
- [docs/HACC_FILES_SUMMARY.md](docs/HACC_FILES_SUMMARY.md) - Files summary
- [docs/HACC_QUICK_REFERENCE.md](docs/HACC_QUICK_REFERENCE.md) - Quick reference
- [docs/HACC_SCRIPTS_REUSE_ANALYSIS.md](docs/HACC_SCRIPTS_REUSE_ANALYSIS.md) - Script reuse analysis
- [docs/HACC_IPFS_HYBRID_USAGE.md](docs/HACC_IPFS_HYBRID_USAGE.md) - IPFS hybrid usage
- [docs/HACC_VS_IPFS_DATASETS_QUICK.md](docs/HACC_VS_IPFS_DATASETS_QUICK.md) - Comparison guide

### Probate Integration
- [docs/PROBATE_INTEGRATION.md](docs/PROBATE_INTEGRATION.md) - Probate complaint type integration

### Additional Documentation
- [docs/EXAMPLES.md](docs/EXAMPLES.md) - Complete reference for all 21 example scripts
- [docs/IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md) - Implementation summary
- [docs/TAXONOMY_EXPANSION_SUMMARY.md](docs/TAXONOMY_EXPANSION_SUMMARY.md) - Taxonomy expansion
- [docs/VERIFICATION_SUMMARY.md](docs/VERIFICATION_SUMMARY.md) - Verification summary

## Example Scripts

See [docs/EXAMPLES.md](docs/EXAMPLES.md) for detailed documentation of all 21 example scripts, organized by category:

### Core System Examples (6)
1. three_phase_example.py
2. legal_analysis_demo.py
3. evidence_management_demo.py
4. legal_authority_research_demo.py
5. web_evidence_discovery_demo.py
6. search_hooks_demo.py

### Complaint Analysis Examples (5)
7. complaint_analysis_integration_demo.py
8. complaint_analysis_taxonomies_demo.py
9. dei_taxonomy_example.py
10. hacc_integration_example.py
11. hacc_dei_analysis_example.py

### Adversarial Testing Examples (8)
12. adversarial_harness_example.py
13. adversarial_harness_standalone.py
14. adversarial_optimization_demo.py
15. batch_sgd_cycle.py
16. session_sgd_report.py
17. parallelism_backoff_sweep.py
18. sweep_ranker.py
19-21. codex_autopatch_*.py (3 variants)

## Documentation Statistics

- **Total Markdown Files**: 42+
- **Module READMEs**: 4 (adversarial_harness, complaint_analysis, complaint_phases, tests)
- **Core Documentation**: 3 (README.md, TESTING.md, CONTRIBUTING.md)
- **Feature Documentation**: 32 docs/*.md files
- **Example Scripts Documented**: 21
- **Test Files Documented**: 19
- **Complaint Types Covered**: 14
- **Total Pages of Documentation**: 250+

## Documentation by Topic

### Getting Started
- README.md - Project overview
- docs/CONFIGURATION.md - Configuration guide
- docs/DEPLOYMENT.md - Deployment guide
- docs/APPLICATIONS.md - CLI and server guide
- TESTING.md - Testing guide
- CONTRIBUTING.md - Contribution guide
- docs/BACKENDS.md - Backend setup
- docs/EXAMPLES.md - Example scripts

### Architecture & Design
- docs/ARCHITECTURE.md - System architecture
- docs/THREE_PHASE_SYSTEM.md - Three-phase design
- docs/ADVERSARIAL_HARNESS.md - Testing framework design

### Features & APIs
- complaint_analysis/README.md - Analysis API
- complaint_phases/README.md - Phase processing API
- mediator/readme.md - Mediator API
- docs/SEARCH_HOOKS.md - Search API
- docs/LEGAL_HOOKS.md - Legal analysis API

### Integration & Usage
- docs/COMPLAINT_ANALYSIS_INTEGRATION.md - Analysis integration
- docs/IPFS_DATASETS_INTEGRATION.md - IPFS integration
- docs/HACC_INTEGRATION.md - DEI analysis integration

### Development & Testing
- tests/README.md - Test documentation
- TESTING.md - Testing workflow
- CONTRIBUTING.md - Development workflow
- docs/SECURITY.md - Security practices

## Finding What You Need

### "I want to..."

- **Get started with the project** → README.md
- **Configure the system** → docs/CONFIGURATION.md
- **Deploy to production** → docs/DEPLOYMENT.md
- **Use CLI or web server** → docs/APPLICATIONS.md
- **Secure the system** → docs/SECURITY.md
- **Understand the architecture** → docs/ARCHITECTURE.md
- **Use the three-phase system** → docs/THREE_PHASE_SYSTEM.md, complaint_phases/README.md
- **Analyze complaints** → complaint_analysis/README.md
- **Test the system** → adversarial_harness/README.md, TESTING.md
- **Configure backends** → docs/BACKENDS.md, docs/LLM_ROUTER.md
- **Run examples** → docs/EXAMPLES.md
- **Contribute code** → CONTRIBUTING.md
- **Write tests** → tests/README.md, TESTING.md
- **Integrate IPFS** → docs/IPFS_DATASETS_INTEGRATION.md
- **Perform legal research** → docs/LEGAL_AUTHORITY_RESEARCH.md
- **Manage evidence** → docs/EVIDENCE_MANAGEMENT.md
- **Use search/RAG** → docs/SEARCH_HOOKS.md

## Navigation Tips

1. **Start with README.md** for project overview
2. **Check module READMEs** for specific features
3. **Review docs/** for detailed documentation
4. **Look at examples/** for code samples
5. **Read CONTRIBUTING.md** before submitting PRs

## Keeping Documentation Updated

When making changes:

1. Update relevant module README if changing that module
2. Update main README.md if adding major features
3. Update or create docs/*.md for detailed feature docs
4. Add examples/ scripts to demonstrate new features
5. Update this index if adding new documentation files
6. Keep DOCUMENTATION_INDEX.md (this file) current

## Feedback

Found an issue with documentation? Please:

1. Open an issue on GitHub
2. Submit a PR with improvements
3. Start a discussion for questions

---

**Last Updated**: 2026-02-10
**Total Documentation**: 42+ markdown files, 250+ pages

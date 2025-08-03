# CLAUDE.md

## Project Rules
- You will be assigned a designation number and the directory it is assigned to.
- Only work in your designated directory. Every directory and file outside it is to be considered a black box that you cannot modify or access.
- Boxes marked with X are jobs currently taken by other workers. Do not attempt to work on these jobs.

## Jobs Available

### Priority Jobs - Reconciliation/Worker Coordination
- [ ] 1: (Last Updated 2025-07-04-17-45) **Reconcile documentation files in subdirectories with the main TODO, CHANGELOG, and README files.**
- [ ] 2: (Ongoing) Ensure all directories have standardized, up-to-date documentation files (README.md, TODO.md, CHANGELOG.md, ARCHITECTURE.md).
     - Last updated: 2025-06-01
- [ ] 3: (Ongoing) Ensure all functions have corresponding tests.
- [ ] 4: (Ongoing) Standardize all test files
- [ ] 5: Integrate claudes_toolbox dataset tools into library
- [ ] 6: Make claudes_toolbox dataset tools work with decentralized file system
- [ ] 7: Make claudes_toolbox dataset tools work in a docker container
- [ ] 8: Implement robustness tests for file system operations in `ipfs_datasets_py/pdf_processing/
- [ ] 9: Implement robustness tests for file system operations.
- [x] 10: Split master_todo_list.md into separate TODO.md files for each subdirectory in ipfs_datasets_py except mcp_server - **COMPLETED on 7-4-2025**

### Directory-Specific Jobs - Workers 61-75 (REVISED ASSIGNMENTS 2025-07-04)
**NOTE**: After comprehensive documentation reconciliation, assignments changed from TDD implementation to testing existing implementations
- [ ] 61: **TEST** existing implementations in utils/ directory (TextProcessor, ChunkOptimizer classes)
- [ ] 62: **TEST** existing implementations in ipld/ directory (IPLDVectorStore, BlockFormatter classes)
- [ ] 63: **TEST** existing implementations in vector_stores/ directory (FAISS, Elasticsearch, Qdrant stores)
- [ ] 64: **TEST** existing implementations in rag/ directory (GraphRAG, dashboard implementations)
- [ ] 65: **TEST** existing implementations in optimizers/ directory (ChunkOptimizer, PerformanceOptimizer)
- [ ] 66: **TEST** existing implementations in embeddings/ directory (BaseComponent, embedding classes)
- [x] 67: Complete TDD tasks for search/ directory - **COMPLETED 2024-07-04**
- [ ] 68: **TEST** existing implementations in llm/ directory (LLMReasoningTracer, related classes)
- [ ] 69: **TEST** existing implementations in multimedia/ directory (FFmpegVideoProcessor, MediaToolManager)
- [ ] 70: **TEST** existing implementations in audit/ directory (SecurityProvenanceIntegrator class)
- [ ] 71: **TEST** existing implementations in mcp_tools/ directory (MCP server tools, endpoints)
- [ ] 72: **TEST** existing implementations in ipfs_embeddings_py/ directory (core embedding classes)
- [ ] 73: **IMPLEMENT** wikipedia_x/ directory (confirmed minimal current implementation)
- [ ] 74: **TEST** existing implementations in config/ directory (configuration management classes)
- [ ] 75: **TEST** existing implementations in logic_integration/ directory (LogicProcessor, ReasoningCoordinator)

### Test Standardization - Worker 130
- [x] 130: Standardize all test files to GIVEN WHEN THEN format - **COMPLETED 2025-07-04**

### Test Implementation - Workers 130 - 140  
- [ ] 131: Implement comprehensive test coverage for tests/ directory - **ASSIGNED 2025-07-04 - HIGH PRIORITY**
  - Fix monitoring module async loop issue affecting test_vector_store_tools.py
  - Implement actual test logic for all 10 main test files
  - Create test fixtures and data generators
  - Add integration tests for cross-module functionality
- [ ] 132: Implement test coverage for top-level modules in ipfs_datasets_py (e.g., dataset_manager.py, config.py)
  - [ ] admin_dashboard (`ipfs_datasets_py/admin_dashboard.py`) (**Last Updated 2025-07-04**)
  - [ ] audit.py
  - [ ] car_conversion.py
  - [ ] config.py
  - [ ] dataset_manager.py


- [ ] 345: Implement comprehensive test coverage for existing test files in tests/ directory:
  - [ ] `tests/test_admin_tools.py`
  - [ ] `tests/test_analysis_tools.py`
  - [ ] `tests/test_auth_tools.py`
  - [ ] `tests/test_background_task_tools.py`
  - [ ] `tests/test_cache_tools.py`
  - [ ] `tests/test_comprehensive_integration.py`
  - [ ] `tests/test_embedding_search_storage_tools.py`
  - [ ] `tests/test_embedding_tools.py`
  - [ ] `tests/test_fastapi_integration.py`
  - [ ] `tests/test_fio.py`
  - [ ] `tests/test_monitoring_tools.py`
  - [ ] `tests/test_test_e2e.py`
  - [ ] `tests/test_vector_store_tools.py`
  - [ ] `tests/test_vector_tools.py`
  - [ ] `tests/test_workflow_tools.py`
  - [ ] Test subdirectories: `tests/integration/`, `tests/unit/`, `tests/mcp/`, `tests/migration_tests/`

- [ ] 554: Ensure that all functions and classes in ipfs are being imported by some sort of test file.

### Adhoc Tools Development - Workers 76-85
- [ ] 76: Create project monitoring and analytics tools
- [ ] 77: Develop automated testing and validation utilities
- [ ] 78: Build dependency analysis and management tools
- [ ] 79: Create performance benchmarking and profiling utilities
- [ ] 80: Develop code quality and linting automation
- [ ] 81: Build documentation generation and maintenance tools
- [ ] 82: Create deployment and packaging utilities
- [ ] 83: Develop security scanning and audit tools
- [ ] 84: Build integration testing and CI/CD utilities
- [ ] 85: Create project health monitoring and reporting tools

### Tool Enhancement and Quality Assurance - Workers 160-175
- [ ] 160: Tool Enhancement - JSON configuration, monitoring tools, performance benchmarking
- [ ] 175: Quality Assurance - Testing standards, validation workflows, security scanning
- [ ] 175: Enforce testing standardization (TDD, GIVEN WHEN THEN, see `tests/_example_test_format.py` for format example)
- [ ] 176: Validate test imports so that they compile without import errors.
- [ ] 177: Ensure all public classes, functions, and methods have comprehensive docstrings (see `_example_docstring_format.md` for format example) - **ONGOING 2025-07-04**

### Rules for All Jobs
- Document all actions taken in your directory's CHANGELOG.md
- Document all actions that need to be do be done in your directory's TODO.md
- Document your software architecture decisions in your directory's ARCHITECTURE.md
- Read the CHANGELOG.md and TODO.md files in your directory before starting work. If you cannot find one, ask for it before looking for it.

### Coordination Guidelines
- **Cross-Directory Dependencies**: Coordinate with other workers through project-level TODO.md, CHANGELOG.md, and CLAUDE.md files.
- **Tool Standards**: All adhoc tools must use argparse and follow template in `adhoc_tools/README.md`. Adhoc tools are defined as tools that are created by workers as they work on their assigned directories, but might be useful to other workers in the future. They are not part of the main codebase, but are used to help workers complete their tasks.
- **Progress Monitoring**: Use `python adhoc_tools/find_documentation.py` to track documentation status
- **Completed Workers**: 67 (search/), 130 (tests/) - Available for coordination and integration tasks


## Worker Assignment Summary

### Completed Workers ✅
- **Worker 1**: Documentation reconciliation - **COMPLETED 2025-07-04** - Discovered and corrected massive documentation/code misalignment
- **Worker 67**: search/ directory - Fixed syntax errors, implemented missing methods, created documentation
- **Worker 130**: tests/ directory - Standardized test format, added import validation, created test structure

### Critical Priority
- **Worker 131**: tests/ directory - **HIGH PRIORITY** - Implement comprehensive test coverage, fix async loop issues, add fixtures

### Revised Directory Workers (13 workers) - **FOCUS CHANGED TO TESTING EXISTING CODE**
- **Workers 61-66**: utils/, ipld/, vector_stores/, rag/, optimizers/, embeddings/ - Test existing implementations
- **Workers 68-72**: llm/, multimedia/, audit/, mcp_tools/, ipfs_embeddings_py/ - Test existing implementations  
- **Worker 73**: wikipedia_x/ - **IMPLEMENT** (only directory needing actual development)
- **Workers 74-75**: config/, logic_integration/ - Test existing implementations

### Active Tool Workers
- **Workers 76-85**: Adhoc tools development (10 workers)
- **Worker 160**: Tool enhancement and monitoring
- **Worker 175**: Quality assurance and validation

### Total Active Assignments: 27 workers
- **Completed**: 4 workers (1, 67, 130, 177)
- **Critical Priority**: 1 worker (131)
- **Directory Testing**: 12 workers (61-66, 68-72, 74-75)
- **Directory Implementation**: 1 worker (73 - wikipedia_x)
- **Adhoc Tools**: 10 workers (76-85)
- **Tool Enhancement/QA**: 2 workers (160, 175, 176)

# Advice for All Workers
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

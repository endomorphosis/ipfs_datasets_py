# MCP Server Implementation Checklist

**Date:** 2026-02-19  
**Status:** ACTIVE - Ready for Execution  
**Branch:** copilot/refactor-improve-mcp-server  
**Progress:** Phase 2 at 69% (31/45h), ready for Weeks 6-7

---

## Quick Reference

**Current Status:**
- ✅ Phase 1: Security (100% complete)
- ✅ Phase 2 Weeks 3-5: Architecture (100% complete)
- ⏳ Phase 2 Week 6: Thick tool refactoring (0/8-12h)
- ⏳ Phase 2 Week 7 / Phase 3 Start: Core testing (0/20-25h)

**Key Metrics:**
- Test Coverage: 18% → Target 75%
- Tests: 64 → Target 234-282
- Complex Functions: 8 → Target 0
- Thin Tools: 85% → Target 95%

---

## Phase 2 Week 6: Thick Tool Refactoring

**Goal:** Extract business logic from 3 thick tools into reusable core libraries  
**Duration:** 8-12 hours (February 19-26, 2026)  
**Tests:** 98 new tests

### Tool 1: enhanced_ipfs_cluster_tools.py

**Target:** 800+ lines → ~150 lines  
**Effort:** 3-4 hours

- [ ] **Day 1-2: Refactoring (3-4h)**
  - [ ] Create `ipfs_datasets_py/ipfs_cluster/cluster_manager.py` (500 lines)
    - [ ] Extract cluster operations (add, pin, status, peers)
    - [ ] Extract IPFS HTTP API calls
    - [ ] Extract configuration parsing
    - [ ] Add comprehensive docstrings
  - [ ] Refactor `enhanced_ipfs_cluster_tools.py` to thin wrapper (150 lines)
    - [ ] Import ClusterManager from core
    - [ ] Create thin tool wrappers
    - [ ] Delegate all logic to ClusterManager
  - [ ] Write tests
    - [ ] Core module tests (20 tests in `test_cluster_manager.py`)
    - [ ] Tool wrapper tests (8 tests in `test_enhanced_ipfs_cluster_tools.py`)
    - [ ] Integration tests (5 tests in `test_ipfs_cluster_integration.py`)
  - [ ] Update documentation
    - [ ] API documentation for ClusterManager
    - [ ] Migration guide for third-party users

**Acceptance Criteria:**
- ✅ Core module: 500 lines, fully documented
- ✅ Tool wrapper: 150 lines max
- ✅ 33 tests passing (20+8+5)
- ✅ Zero breaking changes

### Tool 2: geospatial_analysis_tools.py

**Target:** 600+ lines → ~120 lines  
**Effort:** 3-4 hours

- [ ] **Day 3-4: Refactoring (3-4h)**
  - [ ] Create `ipfs_datasets_py/geospatial/analyzer.py` (400 lines)
    - [ ] Extract geospatial calculations (distance, area, intersections)
    - [ ] Extract coordinate transformations
    - [ ] Extract visualization generation logic
    - [ ] Add comprehensive docstrings
  - [ ] Refactor `geospatial_analysis_tools.py` to thin wrapper (120 lines)
    - [ ] Import GeospatialAnalyzer from core
    - [ ] Create thin tool wrappers
    - [ ] Delegate all logic to GeospatialAnalyzer
  - [ ] Write tests
    - [ ] Core module tests (25 tests in `test_geospatial_analyzer.py`)
    - [ ] Tool wrapper tests (7 tests in `test_geospatial_analysis_tools.py`)
    - [ ] Integration tests (3 tests in `test_geospatial_integration.py`)
  - [ ] Update documentation
    - [ ] API documentation for GeospatialAnalyzer
    - [ ] Usage examples

**Acceptance Criteria:**
- ✅ Core module: 400 lines, fully documented
- ✅ Tool wrapper: 120 lines max
- ✅ 35 tests passing (25+7+3)
- ✅ Zero breaking changes

### Tool 3: web_archive/common_crawl_tools.py

**Target:** 500+ lines → ~100 lines  
**Effort:** 2-4 hours

- [ ] **Day 5-6: Refactoring (2-4h)**
  - [ ] Create `ipfs_datasets_py/web_archive/common_crawl.py` (350 lines)
    - [ ] Extract Common Crawl API client
    - [ ] Extract WARC file parsing utilities
    - [ ] Extract index querying logic
    - [ ] Add comprehensive docstrings
  - [ ] Refactor `common_crawl_tools.py` to thin wrapper (100 lines)
    - [ ] Import CommonCrawlClient from core
    - [ ] Create thin tool wrappers
    - [ ] Delegate all logic to CommonCrawlClient
  - [ ] Write tests
    - [ ] Core module tests (20 tests in `test_common_crawl.py`)
    - [ ] Tool wrapper tests (6 tests in `test_common_crawl_tools.py`)
    - [ ] Integration tests (4 tests in `test_common_crawl_integration.py`)
  - [ ] Update documentation
    - [ ] API documentation for CommonCrawlClient
    - [ ] Usage examples

**Acceptance Criteria:**
- ✅ Core module: 350 lines, fully documented
- ✅ Tool wrapper: 100 lines max
- ✅ 30 tests passing (20+6+4)
- ✅ Zero breaking changes

### Week 6 Validation

- [ ] **Day 7: Testing and Documentation (2h)**
  - [ ] Run all 98 new tests
  - [ ] Verify thin tool compliance: 88% → 95%
  - [ ] Update CHANGELOG.md
  - [ ] Update README.md
  - [ ] Create Week 6 completion report

**Week 6 Summary:**
- ✅ 3 core modules created (+1,250 LOC)
- ✅ 3 tools refactored (-1,530 LOC, net -280)
- ✅ 98 tests passing
- ✅ 95% thin tool compliance achieved

---

## Phase 2 Week 7 / Phase 3 Start: Core Testing

**Goal:** Begin Phase 3 testing infrastructure with server.py coverage  
**Duration:** 20-25 hours (February 26 - March 5, 2026)  
**Tests:** 60-75 new tests  
**Coverage Target:** 35-40% overall, 75%+ core modules

### Component 1: server.py Testing

**Target:** 40-50 tests, 75%+ coverage  
**Effort:** 12-15 hours  
**File:** `tests/mcp/unit/test_server_core.py`

- [ ] **Day 1-3: Tool Registration & Execution (6-8h)**
  - [ ] Create test file structure
  - [ ] Set up fixtures (server, mock tools, mock IPFS)
  - [ ] TestToolRegistration class (10 tests)
    - [ ] `test_register_single_tool_success`
    - [ ] `test_register_duplicate_tool_raises_error`
    - [ ] `test_register_tool_with_invalid_schema`
    - [ ] `test_register_tool_updates_metadata`
    - [ ] `test_unregister_tool_removes_from_registry`
    - [ ] `test_list_registered_tools_returns_all`
    - [ ] `test_get_tool_schema_returns_correct_schema`
    - [ ] `test_tool_registration_with_custom_metadata`
    - [ ] `test_register_category_of_tools`
    - [ ] `test_register_tool_validates_parameters`
  - [ ] TestToolExecution class (10 tests)
    - [ ] `test_execute_tool_success`
    - [ ] `test_execute_tool_with_invalid_params`
    - [ ] `test_execute_tool_with_missing_params`
    - [ ] `test_execute_tool_timeout`
    - [ ] `test_execute_tool_raises_execution_error`
    - [ ] `test_execute_nonexistent_tool`
    - [ ] `test_execute_tool_with_type_conversion`
    - [ ] `test_execute_async_tool`
    - [ ] `test_execute_sync_tool`
    - [ ] `test_concurrent_tool_execution`

- [ ] **Day 4-5: P2P, Config, Error Handling (6-7h)**
  - [ ] TestP2PIntegration class (8 tests)
    - [ ] `test_p2p_services_initialization`
    - [ ] `test_workflow_scheduler_integration`
    - [ ] `test_task_queue_integration`
    - [ ] `test_peer_registry_integration`
    - [ ] `test_graceful_degradation_when_p2p_unavailable`
    - [ ] `test_p2p_service_manager_singleton`
    - [ ] `test_submit_workflow_to_p2p`
    - [ ] `test_retrieve_workflow_result_from_ipfs`
  - [ ] TestConfiguration class (8 tests)
    - [ ] `test_load_config_from_yaml`
    - [ ] `test_load_config_from_environment`
    - [ ] `test_config_validation_success`
    - [ ] `test_config_validation_failure`
    - [ ] `test_config_defaults_applied`
    - [ ] `test_cli_arguments_override_config`
    - [ ] `test_invalid_config_file_raises_error`
    - [ ] `test_missing_required_config_raises_error`
  - [ ] TestErrorHandling class (8 tests)
    - [ ] `test_import_error_graceful_degradation`
    - [ ] `test_tool_execution_error_propagation`
    - [ ] `test_invalid_request_error_response`
    - [ ] `test_timeout_error_cleanup`
    - [ ] `test_resource_cleanup_on_error`
    - [ ] `test_server_continues_after_tool_error`
    - [ ] `test_error_logging_includes_context`
    - [ ] `test_multiple_concurrent_errors_handled`

**Component 1 Acceptance Criteria:**
- ✅ 40-50 tests passing
- ✅ server.py coverage ≥75%
- ✅ All test classes complete
- ✅ Clean test output

### Component 2: hierarchical_tool_manager.py Testing

**Target:** 20-25 tests, 75%+ coverage  
**Effort:** 6-8 hours  
**File:** `tests/mcp/unit/test_hierarchical_tool_manager.py`

- [ ] **Day 6-7: Tool Discovery & Access (6-8h)**
  - [ ] Create test file structure
  - [ ] Set up fixtures (tool_manager, mock categories, mock tools)
  - [ ] TestToolDiscovery class (8 tests)
    - [ ] `test_discover_categories_success`
    - [ ] `test_discover_categories_empty_directory`
    - [ ] `test_discover_categories_caching`
    - [ ] `test_discover_categories_filters_invalid`
    - [ ] `test_load_category_tools_success`
    - [ ] `test_load_category_tools_missing_category`
    - [ ] `test_load_category_tools_import_error`
    - [ ] `test_category_discovery_ignores_hidden_dirs`
  - [ ] TestToolAccess class (7 tests)
    - [ ] `test_get_tool_by_flat_name`
    - [ ] `test_get_tool_by_hierarchical_name`
    - [ ] `test_get_nonexistent_tool_raises_error`
    - [ ] `test_list_all_tools`
    - [ ] `test_list_tools_by_category`
    - [ ] `test_get_tool_metadata`
    - [ ] `test_tool_access_caching`
  - [ ] TestServerContextIntegration class (5-10 tests)
    - [ ] `test_context_initialization`
    - [ ] `test_context_aware_tool_loading`
    - [ ] `test_fallback_to_global_when_no_context`
    - [ ] `test_thread_safety_with_contexts`
    - [ ] `test_context_cleanup`
    - [ ] `test_multiple_contexts_isolated`
    - [ ] `test_context_resource_sharing`
    - [ ] `test_async_context_operations`

**Component 2 Acceptance Criteria:**
- ✅ 20-25 tests passing
- ✅ hierarchical_tool_manager.py coverage ≥75%
- ✅ All test classes complete
- ✅ Integration with ServerContext validated

### Week 7 Validation

- [ ] **Day 8: Review and Documentation (2h)**
  - [ ] Run all 60-75 new tests
  - [ ] Verify coverage targets achieved
  - [ ] Review test quality
  - [ ] Update CHANGELOG.md
  - [ ] Create Week 7 completion report

**Week 7 Summary:**
- ✅ 60-75 tests passing (total: 162-172)
- ✅ server.py coverage ≥75%
- ✅ hierarchical_tool_manager.py coverage ≥75%
- ✅ Overall MCP coverage ≥35-40%

---

## Code Quality Improvements (Parallel Track)

**Can be done alongside testing work**

### Critical Issues (6-8 hours)

- [ ] **Issue #5: Closure Variable Capture Bug (1h)**
  - [ ] Apply `functools.partial` fix in `p2p_mcp_registry_adapter.py:194-206`
  - [ ] Write 3 validation tests
  - [ ] Document the fix with comments

- [ ] **Issue #10: asyncio.run() Event Loop Bug (2-3h)**
  - [ ] Refactor `p2p_mcp_registry_adapter.py:162, 177`
  - [ ] Use proper async context or caching
  - [ ] Write 5 tests (async context, sync context, caching)

- [ ] **Issue #2: Bare Exception Handlers (3-4h)**
  - [ ] Create exception hierarchy in `exceptions.py`
  - [ ] Audit all `except Exception` blocks (~10+ instances)
  - [ ] Replace with specific exception types
  - [ ] Add proper error logging
  - [ ] Write 8 error handling tests

### High Priority Issues (8-12 hours)

- [ ] **Issue #1: Complex Function Refactoring (4-6h)**
  - [ ] Extract `_get_hierarchical_tools` into 4 functions
    - [ ] `_discover_categories()` (30 lines)
    - [ ] `_load_category_tools()` (35 lines)
    - [ ] `_create_tool_wrapper()` (25 lines)
    - [ ] `_validate_tool()` (20 lines)
  - [ ] Refactor main function (40 lines)
  - [ ] Write 15 comprehensive tests

- [ ] **Issue #4: Type Hint Completion (4-6h)**
  - [ ] Run `mypy --strict` and collect errors
  - [ ] Fix core modules first
  - [ ] Fix P2P layer
  - [ ] Fix sample of tools
  - [ ] Add mypy to CI

### Medium Priority (Can be deferred to later weeks)

- [ ] **Issue #3: Import Error Handling (2-3h)**
- [ ] **Issue #6: Missing Docstrings (8-12h, highly parallelizable)**
- [ ] **Issue #9: Input Validation (2-3h)**
- [ ] **Issue #7: Import Complexity (documentation only)**
- [ ] **Issue #8: Async Pattern Inconsistency (1-2h)**

---

## Performance Optimization (Optional for Week 6-7)

**Can be started if ahead of schedule**

- [ ] **Startup Optimization (2-3h)**
  - [ ] Implement lazy tool loading
  - [ ] Add parallel tool discovery
  - [ ] Cache tool metadata
  - [ ] Defer P2P initialization
  - [ ] Benchmark: Target <1s startup

- [ ] **IPFS Caching (4-5h)**
  - [ ] Add LRU cache for IPFS operations
  - [ ] Implement prefetching
  - [ ] Add local pin cache
  - [ ] Benchmark: Target <50ms with caching

---

## Documentation Updates

**Ongoing throughout implementation**

- [ ] **Week 6 Documentation**
  - [ ] Update README.md with new core modules
  - [ ] Create API docs for ClusterManager
  - [ ] Create API docs for GeospatialAnalyzer
  - [ ] Create API docs for CommonCrawlClient
  - [ ] Migration guide for third-party users

- [ ] **Week 7 Documentation**
  - [ ] Update testing documentation
  - [ ] Document test infrastructure
  - [ ] Create testing guide for contributors
  - [ ] Update coverage reports

---

## Validation Checklist

### Week 6 Validation

**Before marking Week 6 complete, verify:**
- [ ] All 3 tools refactored successfully
- [ ] All 98 new tests passing
- [ ] Thin tool compliance: ≥95%
- [ ] Zero breaking changes verified
- [ ] Documentation updated
- [ ] Code review completed
- [ ] Git commits clean and descriptive

### Week 7 Validation

**Before marking Week 7 complete, verify:**
- [ ] All 60-75 new tests passing
- [ ] server.py coverage: ≥75%
- [ ] hierarchical_tool_manager.py coverage: ≥75%
- [ ] Overall MCP coverage: ≥35-40%
- [ ] All test classes complete
- [ ] Test quality reviewed
- [ ] Documentation updated
- [ ] Code review completed

---

## Success Metrics Dashboard

**Track progress with these metrics:**

### Test Metrics
- [ ] Total tests: 64 → 162-172 (Week 6-7 target)
- [ ] Test coverage: 18% → 35-40% (Week 7 target)
- [ ] Test pass rate: 100% maintained
- [ ] Test execution time: <20s

### Code Quality Metrics
- [ ] Complex functions: 8 → 3 (after Issue #1 fixed)
- [ ] Bare exceptions: 10+ → 0 (after Issue #2 fixed)
- [ ] Thin tool compliance: 85% → 95%
- [ ] Type hint coverage: 70% → 90%

### Performance Metrics (Optional)
- [ ] Server startup: 3-5s → <1s
- [ ] Tool execution overhead: ~50ms → <10ms
- [ ] IPFS operation latency: ~200ms → <50ms

---

## Risk Mitigation

### Known Risks

1. **Timeline Slippage**
   - Mitigation: Buffer 20-30% in estimates
   - Contingency: Defer non-critical work

2. **Breaking Changes**
   - Mitigation: Comprehensive testing, backward compatibility
   - Contingency: Rollback plan, version control

3. **Test Coverage Gaps**
   - Mitigation: Prioritize high-risk areas
   - Contingency: Add targeted tests as gaps found

4. **Performance Regression**
   - Mitigation: Continuous benchmarking
   - Contingency: Profile and optimize hot paths

---

## Communication

### Progress Reporting

**Daily Updates:**
- What was completed today
- What will be done tomorrow
- Any blockers or issues

**Weekly Reports:**
- Metrics dashboard update
- Deliverables completed
- Risks and mitigation
- Next week plan

### Status Indicators

- ✅ Complete
- ⏳ In Progress
- ⏸️ Blocked
- ❌ Failed/Reverted
- 🔄 Needs Review

---

## Quick Commands

```bash
# Run all MCP tests
pytest tests/mcp -v

# Run with coverage
pytest tests/mcp --cov=ipfs_datasets_py/mcp_server --cov-report=html

# Run specific test category
pytest tests/mcp/unit -v
pytest tests/mcp/integration -v

# Run tests for specific file
pytest tests/mcp/unit/test_server_core.py -v

# Type checking
mypy ipfs_datasets_py/mcp_server --strict

# Linting
flake8 ipfs_datasets_py/mcp_server

# Complexity check
radon cc ipfs_datasets_py/mcp_server -a

# Generate documentation
sphinx-build -b html docs docs/_build

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

---

## Appendix: Quick Reference Links

**Planning Documents:**
- [Comprehensive Refactoring Plan v2](./COMPREHENSIVE_MCP_REFACTORING_PLAN_v2_2026.md)
- [Architectural Issues and Solutions](./MCP_ARCHITECTURAL_ISSUES_AND_SOLUTIONS.md)
- [Testing Strategy Phase 3](./MCP_TESTING_STRATEGY_PHASE_3.md)
- [Phase 2 Completion and Week 6-7 Roadmap](./PHASE_2_COMPLETION_AND_WEEK_6_7_ROADMAP.md)

**Existing Documentation:**
- [Security Guide](./SECURITY.md)
- [README](./README.md)
- [Thin Tool Architecture](./THIN_TOOL_ARCHITECTURE.md)

**Repository:**
- Branch: `copilot/refactor-improve-mcp-server`
- Tests: `/tests/mcp/`
- Source: `/ipfs_datasets_py/mcp_server/`

---

**Document Status:** ACTIVE  
**Last Updated:** 2026-02-19  
**Next Review:** Daily during implementation  
**Version:** 1.0

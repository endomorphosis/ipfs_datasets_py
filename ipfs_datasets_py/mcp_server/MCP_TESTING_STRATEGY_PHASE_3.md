# MCP Server Testing Strategy - Phase 3

**Date:** 2026-02-19  
**Status:** ACTIVE - Ready for Implementation  
**Target:** 75%+ Coverage, 170-210 Tests  
**Timeline:** Weeks 7-10 (4 weeks, 58-76 hours)

---

## Executive Summary

This document provides a comprehensive testing strategy for Phase 3 of the MCP server refactoring project. The goal is to achieve 75%+ test coverage on core modules while adding 170-210 high-quality tests that validate functionality, performance, and reliability.

### Current State
- **Test Coverage:** ~18-20%
- **Test LOC:** 5,597 lines
- **Test Files:** 15+ files in tests/mcp/
- **Tests Passing:** 64/64 (100%)

### Target State
- **Test Coverage:** 75%+ (core modules), 60%+ (overall)
- **New Tests:** 170-210 comprehensive tests
- **New Test LOC:** 6,000-8,000 lines
- **Test Categories:** Unit, integration, P2P, performance, regression

---

## Table of Contents

1. [Testing Philosophy](#1-testing-philosophy)
2. [Test Organization](#2-test-organization)
3. [Test Categories](#3-test-categories)
4. [Core Module Testing](#4-core-module-testing)
5. [P2P Integration Testing](#5-p2p-integration-testing)
6. [FastAPI Testing](#6-fastapi-testing)
7. [Performance Testing](#7-performance-testing)
8. [Test Infrastructure](#8-test-infrastructure)
9. [Coverage Strategy](#9-coverage-strategy)
10. [Implementation Timeline](#10-implementation-timeline)

---

## 1. Testing Philosophy

### 1.1 Testing Principles

**Principle 1: Test Pyramid**
```
         /\
        /  \  E2E Tests (10%)
       /____\
      /      \
     / Integ. \ Integration Tests (30%)
    /__________\
   /            \
  /    Unit      \ Unit Tests (60%)
 /________________\
```

- **60% Unit Tests:** Fast, isolated, test individual functions
- **30% Integration Tests:** Test component interactions
- **10% E2E Tests:** Test complete workflows

**Principle 2: Test Independence**
- Each test should be runnable in isolation
- No dependencies between tests
- Clean state before and after each test

**Principle 3: Test Readability**
- Use GIVEN-WHEN-THEN format
- Descriptive test names
- Clear assertions with helpful messages

**Principle 4: Comprehensive Coverage**
- Happy path testing
- Error case testing
- Edge case testing
- Performance validation

### 1.2 Test Quality Standards

**Required for Each Test:**
- ✅ Descriptive docstring explaining what is being tested
- ✅ GIVEN-WHEN-THEN structure in code or comments
- ✅ Clear arrange/act/assert sections
- ✅ Meaningful assertions with custom messages
- ✅ Proper cleanup in teardown or fixtures

**Example High-Quality Test:**
```python
@pytest.mark.asyncio
async def test_tool_execution_with_timeout():
    """
    Test that tool execution respects timeout configuration.
    
    This test verifies that:
    1. Slow tools are terminated when exceeding timeout
    2. Timeout error is raised with clear message
    3. Resources are cleaned up properly
    4. Other tools can still execute after timeout
    """
    # GIVEN: A server with 1-second timeout
    server = MCPServer(tool_timeout=1.0)
    
    @mcp.tool()
    async def slow_tool():
        """Tool that sleeps for 5 seconds."""
        await asyncio.sleep(5)
        return "done"
    
    server.register_tool(slow_tool)
    
    # WHEN: We execute the slow tool
    # THEN: A TimeoutError is raised
    with pytest.raises(TimeoutError) as exc_info:
        await server.execute_tool("slow_tool", {})
    
    assert "exceeded timeout of 1.0s" in str(exc_info.value), \
        "Error message should indicate timeout duration"
    
    # AND: Server is still functional
    @mcp.tool()
    async def fast_tool():
        return "quick"
    
    server.register_tool(fast_tool)
    result = await server.execute_tool("fast_tool", {})
    assert result == "quick", "Server should still be functional after timeout"
```

---

## 2. Test Organization

### 2.1 Directory Structure

```
tests/mcp/
├── conftest.py                           # Shared fixtures
├── __init__.py
│
├── unit/                                 # Unit tests (60%)
│   ├── test_server_core.py              # 40-50 tests
│   ├── test_hierarchical_tool_manager.py # 20-25 tests
│   ├── test_tool_registry.py            # 15-20 tests
│   ├── test_tool_metadata.py            # 10-15 tests
│   └── test_server_context.py           # Already exists (18 tests)
│
├── integration/                          # Integration tests (30%)
│   ├── test_p2p_integration.py          # 15-20 tests
│   ├── test_fastapi_endpoints.py        # 10-15 tests
│   ├── test_tool_execution.py           # 20-25 tests
│   └── test_workflow_orchestration.py   # 10-15 tests
│
├── e2e/                                  # End-to-end tests (10%)
│   ├── test_complete_workflows.py       # 10-15 tests
│   └── test_error_recovery.py           # 5-10 tests
│
├── performance/                          # Performance tests
│   ├── test_startup_time.py             # 3-5 tests
│   ├── test_tool_latency.py             # 3-5 tests
│   ├── test_concurrent_execution.py     # 3-5 tests
│   └── test_memory_usage.py             # 3-5 tests
│
└── regression/                           # Regression tests
    ├── test_phase1_security.py          # 5 tests
    └── test_phase2_architecture.py      # 5 tests
```

### 2.2 File Naming Conventions

- **Unit tests:** `test_<module_name>.py`
- **Integration tests:** `test_<feature>_integration.py`
- **E2E tests:** `test_<workflow>_e2e.py`
- **Performance tests:** `test_<aspect>_performance.py`

### 2.3 Test Naming Conventions

**Pattern:** `test_<function>_<scenario>_<expected_result>`

**Examples:**
- `test_register_tool_success_returns_tool_info`
- `test_execute_tool_with_invalid_params_raises_error`
- `test_list_tools_from_empty_registry_returns_empty_list`
- `test_tool_execution_under_high_load_maintains_throughput`

---

## 3. Test Categories

### 3.1 Unit Tests (100-120 tests, 60%)

**Characteristics:**
- Fast execution (<0.1s per test)
- No external dependencies
- Mocked I/O operations
- Isolated function testing

**Example Unit Test:**
```python
def test_validate_tool_schema_success():
    """Test tool schema validation with valid schema."""
    # GIVEN: A valid tool schema
    schema = {
        "name": "my_tool",
        "description": "Does something useful",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            }
        }
    }
    
    # WHEN: We validate the schema
    result = validate_tool_schema(schema)
    
    # THEN: Validation succeeds
    assert result.is_valid
    assert result.errors == []
```

### 3.2 Integration Tests (50-70 tests, 30%)

**Characteristics:**
- Medium execution time (<1s per test)
- Real component integration
- Minimal external dependencies
- Component interaction testing

**Example Integration Test:**
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_registration_and_execution():
    """Test complete tool registration and execution flow."""
    # GIVEN: A server and a tool
    server = MCPServer()
    
    @mcp.tool()
    async def add_numbers(a: int, b: int) -> int:
        return a + b
    
    # WHEN: We register and execute the tool
    server.register_tool(add_numbers)
    result = await server.execute_tool("add_numbers", {"a": 5, "b": 3})
    
    # THEN: Tool executes correctly
    assert result == 8
```

### 3.3 End-to-End Tests (15-25 tests, 10%)

**Characteristics:**
- Slow execution (5-30s per test)
- Real dependencies (where feasible)
- Complete workflow testing
- User scenario validation

**Example E2E Test:**
```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complete_dataset_processing_workflow():
    """Test complete workflow: load dataset, process, save to IPFS."""
    # GIVEN: A running server with all components
    server = await create_full_server()
    
    # WHEN: We execute a complete workflow
    workflow = {
        "steps": [
            {"tool": "dataset/load", "params": {"source": "squad"}},
            {"tool": "dataset/process", "params": {"transform": "tokenize"}},
            {"tool": "ipfs/add", "params": {"content": "$prev_result"}}
        ]
    }
    
    result = await server.execute_workflow(workflow)
    
    # THEN: All steps complete successfully
    assert result["status"] == "completed"
    assert "cid" in result["output"]
    assert result["output"]["cid"].startswith("Qm")
```

### 3.4 Performance Tests (12-20 tests)

**Characteristics:**
- Benchmarking focus
- Quantitative assertions
- Resource monitoring
- Regression detection

**Example Performance Test:**
```python
@pytest.mark.performance
def test_server_startup_time():
    """Test that server starts in less than 1 second."""
    import time
    
    # WHEN: We create a server
    start = time.time()
    server = MCPServer()
    elapsed = time.time() - start
    
    # THEN: Startup time is acceptable
    assert elapsed < 1.0, f"Startup took {elapsed:.2f}s, expected <1.0s"
```

### 3.5 Regression Tests (10 tests)

**Characteristics:**
- Validate previous fixes
- Prevent issue reintroduction
- Security and architecture focus

**Example Regression Test:**
```python
@pytest.mark.regression
def test_no_hardcoded_secrets():
    """Regression test: Ensure no hardcoded secrets (Phase 1 fix)."""
    # Check that SECRET_KEY has no default value
    from ipfs_datasets_py.mcp_server.fastapi_config import Config
    
    config_fields = Config.__fields__
    secret_field = config_fields['secret_key']
    
    assert secret_field.default is None, \
        "SECRET_KEY must not have a default value (security regression)"
```

---

## 4. Core Module Testing

### 4.1 server.py Testing (40-50 tests)

**Target Coverage:** 75%+  
**Effort:** 12-15 hours  
**File:** `tests/mcp/unit/test_server_core.py`

#### Test Suite Structure

```python
class TestToolRegistration:
    """Tests for tool registration functionality."""
    
    def test_register_single_tool_success(self)
    def test_register_duplicate_tool_raises_error(self)
    def test_register_tool_with_invalid_schema(self)
    def test_register_tool_updates_metadata(self)
    def test_unregister_tool_removes_from_registry(self)
    def test_list_registered_tools_returns_all(self)
    def test_get_tool_schema_returns_correct_schema(self)
    def test_tool_registration_with_custom_metadata(self)
    def test_register_category_of_tools(self)
    def test_register_tool_validates_parameters(self)

class TestToolExecution:
    """Tests for tool execution functionality."""
    
    @pytest.mark.asyncio
    async def test_execute_tool_success(self)
    @pytest.mark.asyncio
    async def test_execute_tool_with_invalid_params(self)
    @pytest.mark.asyncio
    async def test_execute_tool_with_missing_params(self)
    @pytest.mark.asyncio
    async def test_execute_tool_timeout(self)
    @pytest.mark.asyncio
    async def test_execute_tool_raises_execution_error(self)
    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self)
    @pytest.mark.asyncio
    async def test_execute_tool_with_type_conversion(self)
    @pytest.mark.asyncio
    async def test_execute_async_tool(self)
    @pytest.mark.asyncio
    async def test_execute_sync_tool(self)
    @pytest.mark.asyncio
    async def test_concurrent_tool_execution(self)

class TestP2PIntegration:
    """Tests for P2P service integration."""
    
    @pytest.mark.asyncio
    async def test_p2p_services_initialization(self)
    @pytest.mark.asyncio
    async def test_workflow_scheduler_integration(self)
    @pytest.mark.asyncio
    async def test_task_queue_integration(self)
    @pytest.mark.asyncio
    async def test_peer_registry_integration(self)
    @pytest.mark.asyncio
    async def test_graceful_degradation_when_p2p_unavailable(self)
    def test_p2p_service_manager_singleton(self)
    @pytest.mark.asyncio
    async def test_submit_workflow_to_p2p(self)
    @pytest.mark.asyncio
    async def test_retrieve_workflow_result_from_ipfs(self)

class TestConfiguration:
    """Tests for server configuration."""
    
    def test_load_config_from_yaml(self)
    def test_load_config_from_environment(self)
    def test_config_validation_success(self)
    def test_config_validation_failure(self)
    def test_config_defaults_applied(self)
    def test_cli_arguments_override_config(self)
    def test_invalid_config_file_raises_error(self)
    def test_missing_required_config_raises_error(self)

class TestErrorHandling:
    """Tests for error handling."""
    
    def test_import_error_graceful_degradation(self)
    def test_tool_execution_error_propagation(self)
    def test_invalid_request_error_response(self)
    @pytest.mark.asyncio
    async def test_timeout_error_cleanup(self)
    def test_resource_cleanup_on_error(self)
    def test_server_continues_after_tool_error(self)
    def test_error_logging_includes_context(self)
    def test_multiple_concurrent_errors_handled(self)
```

#### Example Tests

```python
def test_register_single_tool_success():
    """Test successful registration of a single tool."""
    # GIVEN: A server and a tool
    server = MCPServer()
    
    @mcp.tool()
    def my_tool(x: int) -> int:
        """Multiply by 2."""
        return x * 2
    
    # WHEN: We register the tool
    result = server.register_tool(my_tool)
    
    # THEN: Tool is registered successfully
    assert result.success
    assert "my_tool" in server.list_tools()
    
    # AND: Tool metadata is correct
    schema = server.get_tool_schema("my_tool")
    assert schema["name"] == "my_tool"
    assert schema["description"] == "Multiply by 2."

@pytest.mark.asyncio
async def test_execute_tool_timeout():
    """Test that slow tools timeout correctly."""
    # GIVEN: A server with 1-second timeout
    server = MCPServer(tool_timeout=1.0)
    
    @mcp.tool()
    async def slow_tool():
        await asyncio.sleep(5)
        return "done"
    
    server.register_tool(slow_tool)
    
    # WHEN: We execute the slow tool
    # THEN: It times out
    with pytest.raises(asyncio.TimeoutError):
        await server.execute_tool("slow_tool", {})
```

### 4.2 hierarchical_tool_manager.py Testing (20-25 tests)

**Target Coverage:** 75%+  
**Effort:** 6-8 hours  
**File:** `tests/mcp/unit/test_hierarchical_tool_manager.py`

#### Test Suite Structure

```python
class TestToolDiscovery:
    """Tests for tool category discovery."""
    
    @pytest.mark.asyncio
    async def test_discover_categories_success(self)
    @pytest.mark.asyncio
    async def test_discover_categories_empty_directory(self)
    @pytest.mark.asyncio
    async def test_discover_categories_caching(self)
    def test_discover_categories_filters_invalid(self)
    @pytest.mark.asyncio
    async def test_load_category_tools_success(self)
    @pytest.mark.asyncio
    async def test_load_category_tools_missing_category(self)
    @pytest.mark.asyncio
    async def test_load_category_tools_import_error(self)
    def test_category_discovery_ignores_hidden_dirs(self)

class TestToolAccess:
    """Tests for accessing tools."""
    
    def test_get_tool_by_flat_name(self)
    def test_get_tool_by_hierarchical_name(self)
    def test_get_nonexistent_tool_raises_error(self)
    def test_list_all_tools(self)
    def test_list_tools_by_category(self)
    def test_get_tool_metadata(self)
    def test_tool_access_caching(self)

class TestServerContextIntegration:
    """Tests for ServerContext integration."""
    
    def test_context_initialization(self)
    def test_context_aware_tool_loading(self)
    def test_fallback_to_global_when_no_context(self)
    def test_thread_safety_with_contexts(self)
    def test_context_cleanup(self)
    def test_multiple_contexts_isolated(self)
    def test_context_resource_sharing(self)
    @pytest.mark.asyncio
    async def test_async_context_operations(self)
```

### 4.3 tool_registry.py Testing (15-20 tests)

**Target Coverage:** 70%+  
**Effort:** 4-5 hours  
**File:** `tests/mcp/unit/test_tool_registry.py`

#### Key Test Areas

1. **Registration Tests (8 tests)**
   - Register single tool
   - Register multiple tools
   - Duplicate registration handling
   - Invalid tool rejection
   - Schema validation

2. **Query Tests (7 tests)**
   - Get tool by name
   - List all tools
   - Filter by category
   - Search by keyword
   - Tool existence check

3. **Metadata Tests (5 tests)**
   - Store metadata
   - Retrieve metadata
   - Update metadata
   - Delete metadata

---

## 5. P2P Integration Testing

### 5.1 p2p_mcp_registry_adapter.py Testing (15-20 tests)

**Target Coverage:** 70%+  
**Effort:** 5-6 hours  
**File:** `tests/mcp/integration/test_p2p_integration.py`

#### Test Categories

1. **Tool Discovery (8 tests)**
   - Discover hierarchical tools
   - Load P2P tools
   - Combine local and P2P tools
   - Handle discovery failures
   - Cache discovery results

2. **Wrapper Creation (7 tests)**
   - Create tool wrappers
   - Validate wrapper signatures
   - Test closure variable capture fix
   - Test multiple wrappers
   - Test wrapper error handling

3. **P2P Tool Execution (5-7 tests)**
   - Execute P2P tool successfully
   - Handle P2P execution errors
   - Test P2P timeout
   - Validate result format

---

## 6. FastAPI Testing

### 6.1 fastapi_service.py Testing (10-15 tests)

**Target Coverage:** 70%+  
**Effort:** 4-5 hours  
**File:** `tests/mcp/integration/test_fastapi_endpoints.py`

#### Test Suite

```python
@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_check_success(self)
    async def test_health_check_returns_status(self)

@pytest.mark.asyncio
class TestToolEndpoints:
    async def test_list_tools_endpoint(self)
    async def test_get_tool_schema_endpoint(self)
    async def test_execute_tool_endpoint_success(self)
    async def test_execute_tool_endpoint_invalid_params(self)
    async def test_execute_tool_endpoint_timeout(self)

@pytest.mark.asyncio
class TestEmbeddingEndpoint:
    async def test_generate_embeddings_success(self)
    async def test_generate_embeddings_validation(self)
    async def test_generate_embeddings_batch_size_limit(self)
    async def test_generate_embeddings_unavailable(self)

@pytest.mark.asyncio
class TestAuthentication:
    async def test_authenticated_request_success(self)
    async def test_unauthenticated_request_fails(self)
    async def test_invalid_token_rejected(self)
```

---

## 7. Performance Testing

### 7.1 Performance Benchmarks (12-20 tests)

**Effort:** 8-10 hours  
**Files:** `tests/mcp/performance/test_*.py`

#### Benchmark Categories

1. **Startup Performance (3-5 tests)**
   ```python
   def test_server_startup_under_1_second():
       """Server should start in <1s."""
       start = time.time()
       server = MCPServer()
       elapsed = time.time() - start
       assert elapsed < 1.0
   
   def test_tool_discovery_performance():
       """Tool discovery should complete in <2s."""
       start = time.time()
       manager = HierarchicalToolManager()
       manager.discover_tools()
       elapsed = time.time() - start
       assert elapsed < 2.0
   ```

2. **Execution Performance (3-5 tests)**
   ```python
   @pytest.mark.asyncio
   async def test_tool_execution_overhead_under_10ms():
       """Tool execution overhead should be <10ms."""
       server = MCPServer()
       
       @mcp.tool()
       def fast_tool():
           return "done"
       
       server.register_tool(fast_tool)
       
       # Measure overhead
       start = time.time()
       for _ in range(100):
           await server.execute_tool("fast_tool", {})
       elapsed = time.time() - start
       
       avg_time = (elapsed / 100) * 1000  # Convert to ms
       assert avg_time < 10.0, f"Average time {avg_time:.1f}ms > 10ms"
   ```

3. **Concurrency Performance (3-5 tests)**
   ```python
   @pytest.mark.asyncio
   async def test_parallel_execution_speedup():
       """Parallel execution should be 3x faster than sequential."""
       server = MCPServer()
       
       # ... test parallel vs sequential ...
       
       speedup = sequential_time / parallel_time
       assert speedup > 3.0
   ```

4. **Memory Performance (3-5 tests)**
   ```python
   def test_memory_usage_under_500mb():
       """Server baseline memory should be <500MB."""
       import psutil
       process = psutil.Process()
       
       server = MCPServer()
       memory_mb = process.memory_info().rss / 1024 / 1024
       
       assert memory_mb < 500.0
   ```

---

## 8. Test Infrastructure

### 8.1 Shared Fixtures (conftest.py)

```python
# tests/mcp/conftest.py

import pytest
from unittest.mock import Mock, patch

@pytest.fixture
def mcp_server():
    """Create a test MCP server instance."""
    from ipfs_datasets_py.mcp_server import server
    srv = server.create_server(config={"test_mode": True})
    yield srv
    srv.cleanup()

@pytest.fixture
def server_context():
    """Create a test ServerContext."""
    from ipfs_datasets_py.mcp_server.server_context import ServerContext
    ctx = ServerContext()
    yield ctx
    ctx.cleanup()

@pytest.fixture
def mock_ipfs():
    """Mock IPFS client for testing."""
    with patch('ipfs_datasets_py.mcp_server.ipfs_client') as mock:
        mock.add_bytes.return_value = "QmTest123..."
        mock.cat.return_value = b"test data"
        mock.pin.add.return_value = {"Hash": "QmTest123..."}
        yield mock

@pytest.fixture
async def async_server():
    """Create async test server."""
    server = await create_async_server()
    yield server
    await server.cleanup()

@pytest.fixture
def mock_p2p_services():
    """Mock P2P services for testing."""
    with patch('ipfs_datasets_py.mcp_server.p2p_service_manager') as mock:
        mock.workflow_scheduler = Mock()
        mock.task_queue = Mock()
        mock.peer_registry = Mock()
        yield mock

@pytest.fixture
def sample_tool():
    """Create a sample tool for testing."""
    @mcp.tool()
    def my_tool(x: int) -> int:
        """Sample tool that doubles input."""
        return x * 2
    return my_tool
```

### 8.2 Test Markers

```python
# pytest.ini
[pytest]
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (real dependencies)
    e2e: End-to-end tests (complete workflows)
    slow: Slow tests (>1s execution time)
    p2p: Tests requiring P2P infrastructure
    performance: Performance benchmarks
    regression: Regression tests for previous fixes
    asyncio: Async tests

addopts =
    -v
    --strict-markers
    --cov=ipfs_datasets_py/mcp_server
    --cov-report=html
    --cov-report=term-missing
```

### 8.3 CI Integration

```yaml
# .github/workflows/mcp-tests.yml
name: MCP Server Tests

on:
  push:
    branches: [main, dev]
    paths:
      - 'ipfs_datasets_py/mcp_server/**'
      - 'tests/mcp/**'
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -e ".[test]"
      
      - name: Run unit tests
        run: pytest tests/mcp/unit -v --cov
      
      - name: Run integration tests
        run: pytest tests/mcp/integration -v
      
      - name: Run performance tests
        run: pytest tests/mcp/performance -v
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## 9. Coverage Strategy

### 9.1 Coverage Targets

| Module | Current | Target | Priority |
|--------|---------|--------|----------|
| server.py | 0% | 75%+ | HIGH |
| hierarchical_tool_manager.py | 0% | 75%+ | HIGH |
| tool_registry.py | ~30% | 70%+ | HIGH |
| p2p_mcp_registry_adapter.py | ~20% | 70%+ | MEDIUM |
| fastapi_service.py | ~5% | 70%+ | MEDIUM |
| server_context.py | ~80% | 85%+ | LOW |
| **Overall MCP Server** | **18-20%** | **60-75%** | **HIGH** |

### 9.2 Coverage Monitoring

**Tools:**
- pytest-cov for coverage measurement
- Coverage.py for detailed reports
- Codecov for trend tracking

**Commands:**
```bash
# Generate coverage report
pytest --cov=ipfs_datasets_py/mcp_server --cov-report=html --cov-report=term

# View coverage by module
coverage report --include="ipfs_datasets_py/mcp_server/*"

# Find untested code
coverage report --show-missing

# Generate coverage badge
coverage-badge -o coverage.svg
```

---

## 10. Implementation Timeline

### Week 7: Core Testing (18-23 hours)
- **Days 1-3:** server.py testing (12-15h, 40-50 tests)
- **Days 4-7:** hierarchical_tool_manager.py (6-8h, 20-25 tests)
- **Deliverable:** 60-75 tests, 35-40% coverage

### Week 8: P2P and Config Testing (10-13 hours)
- **Days 1-2:** p2p_mcp_registry_adapter.py (5-6h, 15-20 tests)
- **Day 3:** p2p_service_manager.py (3-4h, 10-15 tests)
- **Day 4:** fastapi_config.py (2-3h, 5-8 tests)
- **Deliverable:** 30-43 tests, 45-50% coverage

### Week 9: FastAPI and Performance (14-18 hours)
- **Days 1-2:** fastapi_service.py (4-5h, 10-15 tests)
- **Days 3-4:** Sample tools (6-8h, 20-25 tests)
- **Days 5-6:** Performance tests (4-5h, 10-15 tests)
- **Deliverable:** 40-55 tests, 55-60% coverage

### Week 10: E2E and Validation (16-22 hours)
- **Days 1-3:** E2E workflows (6-8h, 15-20 tests)
- **Days 4-5:** Integration validation (4-6h, 10-15 tests)
- **Day 6:** Regression tests (2-3h, 10 tests)
- **Day 7:** Documentation (4-5h)
- **Deliverable:** 35-45 tests, 60-75% coverage

**Total:** 170-210 tests, 60-75% coverage, 58-76 hours

---

## Appendix: Test Examples

### Complete Unit Test Example

```python
@pytest.mark.unit
def test_register_tool_validates_schema():
    """
    Test that tool registration validates schema.
    
    This test ensures that:
    1. Valid schemas are accepted
    2. Invalid schemas are rejected
    3. Error messages are descriptive
    """
    # GIVEN: A server
    server = MCPServer()
    
    # WHEN: We register a tool with invalid schema
    @mcp.tool()
    def bad_tool():
        # Missing parameters schema
        pass
    
    # THEN: Registration fails with clear error
    with pytest.raises(SchemaValidationError) as exc_info:
        server.register_tool(bad_tool)
    
    assert "parameters schema required" in str(exc_info.value).lower()
```

### Complete Integration Test Example

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_execution_with_p2p():
    """
    Test complete workflow execution via P2P.
    
    Integration test covering:
    1. Workflow submission to P2P
    2. Task distribution
    3. Result retrieval from IPFS
    """
    # GIVEN: Server with P2P enabled
    server = await create_server_with_p2p()
    
    # AND: A workflow
    workflow = {
        "name": "test_workflow",
        "tasks": [
            {"tool": "dataset/load", "params": {"source": "squad"}},
            {"tool": "ipfs/add", "params": {"data": "$prev"}}
        ]
    }
    
    # WHEN: We submit the workflow
    task_id = await server.submit_workflow(workflow)
    
    # AND: Wait for completion
    result = await server.wait_for_task(task_id, timeout=30)
    
    # THEN: Workflow completes successfully
    assert result["status"] == "completed"
    assert "cid" in result
```

---

**Document Status:** COMPLETE  
**Last Updated:** 2026-02-19  
**Version:** 1.0

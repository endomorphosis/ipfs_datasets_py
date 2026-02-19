# MCP Integration Tests

This directory contains comprehensive integration tests for the IPFS Datasets MCP server.

## Test Files

### New Integration Tests (99 tests)

1. **test_fastapi_integration.py** (21 tests) - FastAPI service layer integration
   - Service lifecycle, authentication, rate limiting, REST API, concurrent requests

2. **test_monitoring_integration.py** (20 tests) - Monitoring system integration
   - Metrics collection, health checks, alerts, system monitoring, graceful shutdown

3. **test_concurrent_execution.py** (17 tests) - Concurrent execution scenarios
   - Parallel tools, thread safety, race conditions, resource contention, deadlock prevention

4. **test_error_recovery.py** (20 tests) - Error recovery mechanisms
   - Failure recovery, retry logic, graceful degradation, state consistency

5. **test_end_to_end_workflows.py** (21 tests) - End-to-end workflows
   - Data pipelines, embedding workflows, P2P workflows, DAG execution, audit trails

### Existing Integration Tests (41 tests)

- **test_exception_integration.py** (13 tests) - Exception handling integration
- **test_p2p_integration.py** (6 tests) - P2P service integration
- **test_tool_registration.py** (12 tests) - Tool registration integration
- **test_workflow_integration.py** (10 tests) - Workflow integration

## Total: 140 Integration Tests

## Running Tests

```bash
# All integration tests
pytest tests/mcp/integration/

# Specific file
pytest tests/mcp/integration/test_fastapi_integration.py

# With verbose output
pytest tests/mcp/integration/ -v

# Specific test class
pytest tests/mcp/integration/test_monitoring_integration.py::TestMetricsCollectionDuringToolExecution

# With coverage
pytest tests/mcp/integration/ --cov=ipfs_datasets_py.mcp_server
```

## Test Standards

All tests follow:
- ✅ GIVEN-WHEN-THEN format
- ✅ Comprehensive docstrings
- ✅ Happy path and error cases
- ✅ Proper fixtures
- ✅ Independent execution
- ✅ Custom exception verification

## Dependencies

- pytest
- pytest-asyncio
- FastAPI (optional - tests will skip if not available)
- PyJWT (optional - tests will skip if not available)
- psutil (optional - system metrics tests will skip)

Install with:
```bash
pip install pytest pytest-asyncio fastapi pyjwt psutil
```

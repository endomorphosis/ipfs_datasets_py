# MCP Server Refactoring - Quick Reference Card

**Version:** 3.0  
**Date:** 2026-02-19  
**Status:** 60% Complete → 100% Target in 14-16 weeks

---

## 📊 At a Glance

| Metric | Current | Target |
|--------|---------|--------|
| **Overall Progress** | 60% | 100% |
| **Test Coverage** | 25-35% | 75%+ |
| **Complex Functions** | 8 | 0 |
| **Bare Exceptions** | 10+ | 0 |
| **Thick Tools** | 3 | 0 |
| **Missing Docstrings** | 120+ | 0 |

**Remaining Effort:** 80-110 hours over 14-16 weeks

---

## 🎯 Critical Priorities

### 1. Test Coverage (HIGHEST PRIORITY)
**Need:** 45-55 new tests (25-32 hours)

```
🔴 CRITICAL - No Tests:
├── fastapi_service.py (1,152 lines) → Need 15-18 tests
├── trio_adapter.py (350 lines) → Need 6-8 tests
├── trio_bridge.py (200 lines) → Need 6-7 tests
├── validators.py → Need 6-7 tests
└── monitoring.py → Need 4-5 tests
```

### 2. Code Quality
**Need:** Fix 8 functions, 10+ exceptions, 120+ docstrings (27-38 hours)

### 3. Architecture
**Need:** Refactor 3 thick tools (18-24 hours)

---

## 📁 Key Documents

### Main Documentation
- **Comprehensive Plan** → `COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026_v3.md` (47KB)
- **Executive Summary** → `REFACTORING_EXECUTIVE_SUMMARY_v3_2026.md` (8KB)
- **Visual Summary** → `VISUAL_REFACTORING_SUMMARY_v3_2026.md` (12KB)

### Legacy Documentation (Reference Only)
- `COMPREHENSIVE_MCP_REFACTORING_PLAN_v2_2026.md`
- `COMPREHENSIVE_REFACTORING_PLAN_2026.md`
- `MCP_REFACTORING_COMPLETION_SUMMARY_2026.md`

---

## 🏗️ Architecture Overview

### ✅ Complete (Use These Patterns)

**Hierarchical Tool Manager**
```python
# 99% context reduction: 373 tools → 4 meta-tools
mcp.add_tool(tools_list_categories)
mcp.add_tool(tools_list_tools)
mcp.add_tool(tools_get_schema)
mcp.add_tool(tools_dispatch)
```

**Thin Wrapper Pattern**
```python
# Core module (reusable)
class DatasetLoader:
    def load(self, source: str) -> Dataset:
        pass

# MCP tool (<150 lines)
@tool_metadata(runtime="fastapi")
async def load_dataset(source: str):
    loader = DatasetLoader()
    return await loader.load(source)
```

**Dual-Runtime System**
```python
# FastAPI for general tools
@tool_metadata(runtime="fastapi")
async def general_tool(): pass

# Trio for P2P tools (50-70% faster)
@tool_metadata(runtime="trio")
async def p2p_tool(): pass
```

---

## 🔧 How to Contribute

### Adding Tests (Phase 3)
```bash
# 1. Choose a component needing tests
cd tests/mcp/unit/

# 2. Create test file following pattern
# test_<component_name>.py

# 3. Use GIVEN-WHEN-THEN format
def test_feature():
    """
    GIVEN: Initial state
    WHEN: Action taken
    THEN: Expected result
    """
    pass

# 4. Run tests
pytest tests/mcp/unit/test_<component>.py -v
```

### Refactoring Complex Functions (Phase 4)
```bash
# 1. Identify function >100 lines
# 2. Extract helper methods
# 3. Add docstrings
# 4. Verify tests pass
pytest tests/mcp/ -v
```

### Fixing Bare Exceptions
```python
# ❌ BAD
try:
    operation()
except Exception:
    logger.warning("Failed")

# ✅ GOOD
try:
    operation()
except ValueError as e:
    logger.warning(f"Invalid value: {e}")
    raise
```

---

## 📈 Weekly Milestones

| Week | Goal | Tests | Hours |
|------|------|-------|-------|
| 11 | FastAPI tests | 15-18 | 8-10 |
| 12 | Trio tests | 12-15 | 6-8 |
| 13 | Validators/monitoring | 10-12 | 5-6 |
| 14 | Integration/E2E | 8-10 | 6-8 |
| 15-16 | Refactor functions | - | 8-12 |
| 16-17 | Fix exceptions | - | 4-6 |
| 17-18 | Add docstrings | - | 15-20 |
| 19-20 | Thick tools | - | 18-24 |
| 21 | Consolidation | - | 8-10 |
| 22 | Documentation | - | 4-6 |
| 23 | Performance | - | 6-8 |
| 24 | Monitoring | - | 2-4 |

---

## 🎪 Testing Patterns

### Unit Test Template
```python
import pytest
from unittest.mock import Mock, patch

class TestComponent:
    """Test suite for Component."""
    
    def test_basic_functionality(self):
        """
        GIVEN: A component instance
        WHEN: Method is called
        THEN: Expected behavior occurs
        """
        # Arrange
        component = Component()
        
        # Act
        result = component.method()
        
        # Assert
        assert result == expected
```

### Fixture Pattern
```python
@pytest.fixture
def mock_server():
    """Provides mocked MCP server."""
    with patch('mcp.server.FastMCP') as mock:
        yield mock
```

### Parametrized Tests
```python
@pytest.mark.parametrize("input,expected", [
    ("valid", "success"),
    ("invalid", "error"),
])
def test_scenarios(input, expected):
    result = function(input)
    assert result.status == expected
```

---

## 🚨 Common Issues & Solutions

### Issue: Tests Failing After Changes
**Solution:**
```bash
# 1. Run specific test file
pytest tests/mcp/unit/test_file.py -v

# 2. Check for missing mocks
# 3. Verify backward compatibility
# 4. Update test fixtures if needed
```

### Issue: Complex Function to Refactor
**Steps:**
1. Write tests first (if missing)
2. Extract logical sub-tasks to helpers
3. Add docstrings to extracted methods
4. Verify all tests still pass
5. Check function is now <100 lines

### Issue: Coverage Not Increasing
**Check:**
- Are test files in correct location?
- Are fixtures properly configured?
- Is component being imported correctly?
- Run: `pytest --cov=ipfs_datasets_py.mcp_server --cov-report=html`

---

## 📞 Getting Help

### Documentation
- Main plan: `COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026_v3.md`
- Visual summary: `VISUAL_REFACTORING_SUMMARY_v3_2026.md`
- Architecture: `THIN_TOOL_ARCHITECTURE.md`

### Key Sections to Read
- **Starting testing?** → Plan Section 5 (Testing Strategy)
- **Refactoring code?** → Plan Section 6 (Code Quality)
- **Thick tools?** → Plan Section 3.6 (Thick Tools)
- **Understanding architecture?** → Plan Section 2 (Architecture Overview)

---

## ✅ Before Committing Checklist

- [ ] All tests pass: `pytest tests/mcp/ -v`
- [ ] Coverage maintained/improved: `pytest --cov`
- [ ] No new bare exceptions
- [ ] Functions <100 lines
- [ ] Type hints present
- [ ] Docstrings added
- [ ] No new TODOs without issues
- [ ] Backward compatibility maintained

---

## 🎯 Current Sprint Goals

### This Week (Week 11 - FastAPI Testing)
```
Priority: 🔴 CRITICAL

Tasks:
1. Create test_fastapi_service.py
2. Add endpoint tests (8 tests)
3. Add authentication tests (4 tests)
4. Add error handling tests (3-4 tests)

Goal: 15-18 new tests, 8-10 hours

Success: FastAPI service coverage 5% → 75%
```

---

## 📊 Progress Tracking

### Update Progress
```bash
# Run all tests
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=term

# Check coverage
# Target: 75%+
```

### Report Issues
```bash
# Create GitHub issue for each TODO
# Tag with: refactoring, phase-3, phase-4, etc.
```

---

## 🏆 Success Metrics

### Phase 3 Complete When:
- [ ] 200+ total tests (currently 148)
- [ ] 75%+ overall coverage (currently 25-35%)
- [ ] FastAPI service: 75%+ coverage
- [ ] Trio runtime: 70%+ coverage
- [ ] Validators: 80%+ coverage
- [ ] Monitoring: 70%+ coverage

### Phase 4 Complete When:
- [ ] Zero functions >100 lines (currently 8)
- [ ] Zero bare exception handlers (currently 10+)
- [ ] 90%+ docstring coverage (currently ~40%)
- [ ] 95%+ type hint coverage (currently ~70%)

---

## 🚀 Quick Commands

```bash
# Run all tests
pytest tests/mcp/ -v

# Run with coverage
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=html

# Run specific test file
pytest tests/mcp/unit/test_server_core.py -v

# Run only unit tests
pytest tests/mcp/unit/ -v

# Type checking
mypy ipfs_datasets_py/mcp_server/

# Linting
flake8 ipfs_datasets_py/mcp_server/

# Find complex functions (>100 lines)
find ipfs_datasets_py/mcp_server -name "*.py" -exec wc -l {} + | sort -n | tail -20
```

---

## 📝 Notes

**Remember:**
- Test first, refactor second
- Maintain backward compatibility
- Follow existing patterns
- Document as you go
- Small, incremental changes
- Get reviews on PRs

**Don't:**
- Skip tests
- Break backward compatibility
- Add TODOs without issues
- Commit uncommented code
- Ignore coverage drops

---

**Last Updated:** 2026-02-19  
**Version:** 3.0  
**Branch:** copilot/refactor-improve-mcp-server-again  
**Status:** ACTIVE - Ready for Implementation

**Next Action:** Start Week 11 FastAPI testing (15-18 tests, 8-10 hours)

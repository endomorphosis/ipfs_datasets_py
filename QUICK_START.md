# Quick Start Guide - MCP Tools Refactoring

## 🎯 Purpose

This guide helps you complete the remaining MCP tools refactoring (Phases 6-10). Follow these steps to maintain consistency with the established architectural pattern.

---

## 📋 Current Status

✅ **Completed:** 12/17 tools (71%)  
⏸️ **Remaining:** 5/17 tools (29%)  
📊 **Lines to Extract:** ~2,630 lines

---

## 🚀 Quick Start

### Step 1: Choose a Phase

**Recommended Order:**
1. Phase 6: Data Processing (522 lines) - **Start here**
2. Phase 7: Storage (708 lines)
3. Phase 8: Workflow (791 lines)
4. Phase 9: IPFS + Dataset cleanup (609 lines)
5. Phase 10: Final verification

### Step 2: Read Examples

Study these completed refactorings:

```bash
# Example 1: Analysis Tools (Phase 1)
less ipfs_datasets_py/analytics/analysis_engine.py
less ipfs_datasets_py/mcp_server/tools/analysis_tools/analysis_tools.py

# Example 2: Media Tools (Phase 5)
less ipfs_datasets_py/multimedia/ffmpeg_wrapper.py
less ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_convert.py
```

### Step 3: Follow the Pattern

#### Pattern Template

```python
# 1. Core Module (ipfs_datasets_py/module_name/core.py)
"""Core business logic."""

class CoreEngine:
    """Core implementation."""
    
    def __init__(self):
        self.config = {}
    
    def process(self, data):
        """Main processing logic."""
        # Business logic here
        return result

# 2. MCP Tool Wrapper (mcp_server/tools/tool_name/tool.py)
"""
MCP Tool Wrapper

Core implementation: ipfs_datasets_py.module_name.core
"""

from ipfs_datasets_py.module_name import CoreEngine

async def mcp_tool_function(**kwargs):
    """Thin wrapper - delegates to core."""
    try:
        engine = CoreEngine()
        result = engine.process(**kwargs)
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

---

## 📝 Phase-by-Phase Checklist

### Phase 6: Data Processing Tools

**Location:** `mcp_server/tools/data_processing_tools/data_processing_tools.py`

- [ ] Create `ipfs_datasets_py/data_processing/` directory
- [ ] Create `ipfs_datasets_py/data_processing/__init__.py`
- [ ] Create `ipfs_datasets_py/data_processing/processor.py`
- [ ] Move `MockDataProcessor` → `DataProcessor` (lines 19-158)
- [ ] Update MCP tool to import from core
- [ ] Test: `python -c "from ipfs_datasets_py.data_processing import DataProcessor"`
- [ ] Test: MCP tool still works
- [ ] Remove old backup files
- [ ] Commit with message: "Phase 6: Extract data processing logic to core"

**Key Functions to Move:**
- `chunk_text()` - Text chunking logic
- `transform_data()` - Data transformation
- `convert_format()` - Format conversion

### Phase 7: Storage Tools

**Location:** `mcp_server/tools/storage_tools/storage_tools.py`

- [ ] Create `ipfs_datasets_py/storage/` directory
- [ ] Create `ipfs_datasets_py/storage/__init__.py`
- [ ] Create `ipfs_datasets_py/storage/manager.py`
- [ ] Move `MockStorageManager` → `StorageManager`
- [ ] Update MCP tool to import from core
- [ ] Test: `python -c "from ipfs_datasets_py.storage import StorageManager"`
- [ ] Test: MCP tool still works
- [ ] Remove old backup files
- [ ] Commit with message: "Phase 7: Extract storage management to core"

**Key Functions to Move:**
- Item storage/retrieval
- Collection management
- Statistics tracking
- Query operations

### Phase 8: Workflow Tools

**Location:** `mcp_server/tools/workflow_tools/workflow_tools.py`

- [ ] Create `ipfs_datasets_py/workflow_engine/` directory
- [ ] Create `ipfs_datasets_py/workflow_engine/__init__.py`
- [ ] Create `ipfs_datasets_py/workflow_engine/engine.py`
- [ ] Create `ipfs_datasets_py/workflow_engine/registry.py`
- [ ] Move workflow engine logic
- [ ] Move registries (WORKFLOW_REGISTRY, etc.)
- [ ] Update MCP tool to import from core
- [ ] Test: `python -c "from ipfs_datasets_py.workflow_engine import WorkflowEngine"`
- [ ] Test: MCP tool still works
- [ ] Remove old backup files
- [ ] Commit with message: "Phase 8: Extract workflow engine to core"

### Phase 9: Smaller Tools

**IPFS Tools:**
- [ ] Review `ipfs_tools/get_from_ipfs.py`
- [ ] Extract gateway logic if substantial
- [ ] Update to use core if needed

**Dataset Tools:**
- [ ] Review all dataset_tools files
- [ ] Remove unnecessary mocks
- [ ] Ensure proper delegation

- [ ] Commit with message: "Phase 9: Clean up remaining tools"

### Phase 10: Final Verification

- [ ] Run full test suite: `pytest tests/`
- [ ] Verify all 17 tools follow pattern
- [ ] Update MCP_TOOLS_REFACTORING_STATUS.md
- [ ] Update MCP_REFACTORING_FINAL_SUMMARY.md
- [ ] Remove all backup files: `find . -name "*.backup" -o -name "*_old.py" | xargs rm`
- [ ] Create final summary document
- [ ] Commit with message: "Phase 10: Final verification and documentation"

---

## 🔍 Validation Commands

### Before Each Phase

```bash
# Check current status
git status

# Review files
ls -la ipfs_datasets_py/mcp_server/tools/[tool_name]/
```

### After Creating Core Module

```bash
# Test import
python -c "from ipfs_datasets_py.[module] import [Class]"

# Check file structure
tree ipfs_datasets_py/[module]/
```

### After Updating MCP Tool

```bash
# Test MCP tool import
python -c "from ipfs_datasets_py.mcp_server.tools.[tool].[file] import [function]"

# Run any existing tests
pytest tests/[relevant_test].py -v
```

### Before Committing

```bash
# Check what's staged
git diff --cached

# Verify no backup files
find . -name "*.backup" -o -name "*_old.py"

# Check file sizes (should be smaller)
wc -l ipfs_datasets_py/mcp_server/tools/[tool]/*.py
```

---

## ⚠️ Common Issues & Solutions

### Issue 1: Import Errors

**Problem:** `ModuleNotFoundError: No module named 'ipfs_datasets_py.new_module'`

**Solution:** 
```bash
# Create __init__.py
touch ipfs_datasets_py/new_module/__init__.py

# Add exports
echo "from .core import CoreClass" >> ipfs_datasets_py/new_module/__init__.py
```

### Issue 2: Circular Imports

**Problem:** Module A imports B, B imports A

**Solution:**
- Use lazy imports inside functions
- Refactor to remove circular dependency
- Use dependency injection

### Issue 3: Tests Failing

**Problem:** Tests fail after refactoring

**Solution:**
```bash
# Check test imports
grep -r "from.*tools.*import" tests/

# Update test imports to use core
# Old: from mcp_server.tools.x import func
# New: from ipfs_datasets_py.core import func
```

### Issue 4: Backward Compatibility

**Problem:** Existing code breaks

**Solution:**
```python
# Add compatibility shim in MCP tool
from ipfs_datasets_py.core import CoreClass

# Legacy support
class LegacyClass(CoreClass):
    """Backward compatibility wrapper."""
    pass
```

---

## 📊 Progress Tracking

### Update These Files After Each Phase

1. **MCP_TOOLS_REFACTORING_STATUS.md**
   - Mark phase as complete
   - Update metrics
   - Update checklist

2. **MCP_REFACTORING_FINAL_SUMMARY.md**
   - Update progress percentage
   - Update completed phases list
   - Update metrics table

3. **COMPLETION_REPORT.md**
   - Update overall progress
   - Mark phase as complete
   - Update remaining effort

### Commit Message Format

```
Phase X: [Tool Name] - Extract to core module

- Created ipfs_datasets_py/[module]/
- Moved [Class] from MCP tool to core
- Updated MCP tool to delegate
- Maintained backward compatibility
- Tests passing

Lines extracted: XXX
Tools complete: XX/17 (XX%)
```

---

## 🎯 Success Criteria

### Each Phase Must Have:

- ✅ Core module in `ipfs_datasets_py/`
- ✅ MCP tool is thin wrapper (<200 lines)
- ✅ Imports from core module
- ✅ Backward compatibility maintained
- ✅ Tests passing
- ✅ Documentation updated
- ✅ No backup files committed

### Final Completion (Phase 10):

- ✅ 17/17 tools (100%) following pattern
- ✅ All embedded logic extracted
- ✅ All tests passing
- ✅ Documentation complete
- ✅ Clean git history
- ✅ Ready for production

---

## 📚 Resources

### Key Documents

1. **COMPLETION_REPORT.md** - Detailed project status
2. **MCP_TOOLS_REFACTORING_STATUS.md** - Line-by-line tracking
3. **MCP_REFACTORING_FINAL_SUMMARY.md** - Executive summary
4. **This Guide** (QUICK_START.md) - Step-by-step instructions

### Example Code

- Completed: `ipfs_datasets_py/analytics/analysis_engine.py`
- Wrapper: `mcp_server/tools/analysis_tools/analysis_tools.py`
- Shim: `mcp_server/tools/media_tools/ffmpeg_utils.py`

### Commands Reference

```bash
# Find embedded logic
grep -r "class Mock" ipfs_datasets_py/mcp_server/tools/

# Count lines
wc -l ipfs_datasets_py/mcp_server/tools/*/*.py

# Test imports
python -c "from ipfs_datasets_py.X import Y; print('✓')"

# Run tests
pytest tests/ -v

# Clean backups
find . -name "*.backup" -delete
```

---

## ✨ Tips for Success

1. **Start Small:** Phase 6 is smallest (522 lines)
2. **Test Often:** After each change
3. **Commit Incrementally:** One phase at a time
4. **Follow Examples:** Study completed phases
5. **Ask Questions:** Check documentation if stuck
6. **Stay Consistent:** Use established pattern
7. **Clean Up:** Remove backup files before committing

---

## 🤝 Getting Help

### If Stuck:

1. Review completed examples in repository
2. Check COMPLETION_REPORT.md for detailed plans
3. Look for similar patterns in existing code
4. Test incrementally to isolate issues
5. Check common issues section above

### Before Starting:

- [ ] Read this guide completely
- [ ] Review completed phases
- [ ] Understand the pattern
- [ ] Set up test environment
- [ ] Create working branch

### While Working:

- [ ] Follow checklist for current phase
- [ ] Test after each major change
- [ ] Update documentation as you go
- [ ] Commit frequently
- [ ] Keep changes minimal

---

**Good luck! You're continuing excellent work. The pattern is proven, the examples are clear, and success is within reach. 🚀**

---

*Quick Start Guide - v1.0*  
*For MCP Tools Refactoring Phases 6-10*  
*Estimated Time: 13-18 hours total*

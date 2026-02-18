# Phase 2: Tool Interface Alignment - Implementation Plan

**Date:** 2026-02-18  
**Status:** In Progress  
**Based on:** Comprehensive tool audit of 250+ tools across 47 categories

---

## Executive Summary

**Audit Results:**
- **Total tools:** 250+ Python files across 47 categories
- **Thin wrapper compliance:** ~65% following pattern correctly
- **Partial compliance:** ~25% with minor issues
- **Thick tools:** ~10% with embedded business logic needing refactoring

**Key Finding:** Architecture is good, but patterns are inconsistent. Need standardization without major refactoring.

---

## Tool Audit Summary

### Pattern Distribution

| Pattern | Count | % | Status |
|---------|-------|---|--------|
| Async functions with decorator | ~180 | 72% | ✅ Good (modern pattern) |
| Class-based (ClaudeMCPTool) | ~25 | 10% | ⚠️ Legacy (works but verbose) |
| Mixed/Other | ~45 | 18% | ⚠️ Needs standardization |

### Compliance Assessment

| Compliance Level | Count | % | Action Needed |
|-----------------|-------|---|---------------|
| ✅ Thin wrappers | ~163 | 65% | Document as examples |
| ⚠️ Partial compliance | ~63 | 25% | Minor refactoring |
| ❌ Thick tools | ~24 | 10% | Extract to core modules |

### Tools Needing Attention

**High Priority (Thick Tools - Extract Logic):**
1. `cache_tools.py` (710 lines) - State management in tool
2. `deontological_reasoning_tools.py` (595 lines) - Parsing logic in tool
3. `relationship_timeline_tools.py` (400+ lines) - NLP in tool
4. `investigation_tools/*` (multiple files) - Custom analysis

**Medium Priority (Standardization):**
5. Legacy class-based tools → migrate to decorator pattern
6. Tools with inconsistent error handling
7. Tools without proper type hints

**Low Priority (Documentation):**
8. Tools following good patterns → document as examples
9. Add comprehensive tool testing

---

## Phase 2 Implementation Strategy

### Part A: Pattern Standardization (Immediate)

**Goal:** Document and enforce the modern async function + decorator pattern

**Actions:**
1. ✅ Document the standard pattern
2. Create tool development template
3. Migration guide for legacy tools
4. Linting rules for new tools

**Timeline:** 2-3 hours

### Part B: Tool Templates (Quick Win)

**Goal:** Provide templates for common tool patterns

**Create:**
1. Simple function tool template
2. Multi-function tool template
3. Class-based tool template (for complex state)
4. Testing template

**Timeline:** 2 hours

### Part C: Thick Tool Refactoring (Phased)

**Goal:** Extract embedded business logic to core modules

**Approach:**
- Phase 2.1: Document thick tools and create extraction plan
- Phase 2.2: Extract cache_tools state management (priority 1)
- Phase 2.3: Extract deontic reasoning logic (priority 2)
- Phase 2.4: Extract remaining thick tools (priority 3)

**Timeline:** 8-12 hours (can be done incrementally)

### Part D: Testing Infrastructure (Foundation)

**Goal:** Enable tool validation

**Create:**
1. Tool thinness validator (< 100 lines check)
2. Core module import checker
3. Pattern compliance checker
4. Basic integration test framework

**Timeline:** 4-6 hours

---

## Detailed Implementation Plan

### Part A: Pattern Standardization

#### 1. Standard Tool Pattern Documentation

**File:** `docs/development/tool-patterns.md`

**Content:**
```markdown
# Standard Tool Patterns

## Pattern 1: Simple Async Function Tool (RECOMMENDED)

Use for: Single-purpose tools with simple parameters

```python
from ipfs_datasets_py.mcp_server.tool_wrapper import wrap_function_as_tool
from ipfs_datasets_py.core_module import CoreService

@wrap_function_as_tool(
    name="tool_name",
    description="What the tool does",
    category="tool_category",
    tags=["tag1", "tag2"]
)
async def tool_name(
    param1: str,
    param2: int = 10,
    **kwargs
) -> dict:
    """
    Tool docstring.
    
    Args:
        param1: Description
        param2: Description
    
    Returns:
        Result dictionary
    """
    # Validate parameters (minimal)
    if not param1:
        raise ValueError("param1 is required")
    
    # Delegate to core module
    service = CoreService()
    result = await service.do_work(param1, param2)
    
    # Format response
    return {
        "status": "success",
        "result": result
    }
```

## Pattern 2: Multiple Functions in One File

Use for: Related tools in the same category

```python
# Tool 1
@wrap_function_as_tool(...)
async def tool_one(...):
    ...

# Tool 2
@wrap_function_as_tool(...)
async def tool_two(...):
    ...

# Tool 3
@wrap_function_as_tool(...)
async def tool_three(...):
    ...
```

## Pattern 3: Class-Based Tool (LEGACY - Use only for complex state)

Use for: Tools requiring persistent state or complex lifecycle

```python
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

class MyTool(ClaudeMCPTool):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.name = "my_tool"
        self.description = "What it does"
        self.input_schema = {...}
    
    async def execute(self, parameters: Dict) -> Dict:
        # Validate
        # Delegate to core
        # Return result
```
```

#### 2. Tool Development Template

**File:** `docs/development/tool-template.py`

```python
"""
Tool Name: [Tool Name]
Category: [Category]
Description: [What this tool does]

Core Module: [Which ipfs_datasets_py module this uses]
"""

from typing import Optional, Dict, Any
from ipfs_datasets_py.mcp_server.tool_wrapper import wrap_function_as_tool
from ipfs_datasets_py.core_module import CoreService  # Replace with actual

@wrap_function_as_tool(
    name="tool_name",
    description="Brief description of what this tool does",
    category="tool_category",
    tags=["relevant", "tags"]
)
async def tool_name(
    required_param: str,
    optional_param: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Detailed description of the tool.
    
    This tool delegates to CoreService in ipfs_datasets_py.core_module.
    All business logic is in the core module.
    
    Args:
        required_param: Description of required parameter
        optional_param: Description of optional parameter
    
    Returns:
        Dictionary with:
            - status: "success" or "error"
            - result: The actual result data
            - message: Optional message
    
    Raises:
        ValueError: If required parameters are invalid
    
    Example:
        >>> result = await tool_name("input")
        >>> print(result["status"])
        success
    """
    # 1. Minimal parameter validation
    if not required_param:
        raise ValueError("required_param cannot be empty")
    
    # 2. Delegate to core module
    service = CoreService()
    try:
        result = await service.do_work(
            required_param,
            optional_param=optional_param
        )
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    
    # 3. Format response
    return {
        "status": "success",
        "result": result
    }
```

#### 3. Migration Guide

**File:** `docs/development/tool-migration-guide.md`

```markdown
# Tool Migration Guide

## Migrating Class-Based Tools to Function Pattern

### Before (Class-Based):
```python
class SearchTool(ClaudeMCPTool):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.name = "search"
        ...
    
    async def execute(self, parameters):
        query = parameters["query"]
        return await self.service.search(query)
```

### After (Function-Based):
```python
@wrap_function_as_tool(name="search", ...)
async def search(query: str) -> dict:
    service = SearchService()
    return await service.search(query)
```

### Benefits:
- 50% less code
- Better type hints
- Easier to test
- Auto-registration
```

### Part B: Tool Templates

Create templates for:

1. **simple_tool_template.py** - Single function tool
2. **multi_tool_template.py** - Multiple related functions
3. **stateful_tool_template.py** - Class-based with state
4. **test_tool_template.py** - Tool testing template

### Part C: Thick Tool Refactoring Plan

#### Priority 1: cache_tools.py (710 lines)

**Issue:** Owns state (global dicts), violates thin wrapper principle

**Solution:**
```python
# Current (IN TOOL):
_cache = {}
_cache_ttl = {}

async def cache_get(key: str):
    return _cache.get(key)

# Refactored (IN CORE MODULE):
# ipfs_datasets_py/core_operations/cache_manager.py
class CacheManager:
    def __init__(self):
        self._cache = {}
        self._cache_ttl = {}
    
    async def get(self, key: str):
        return self._cache.get(key)

# Tool becomes thin wrapper:
from ipfs_datasets_py.core_operations import CacheManager

@wrap_function_as_tool(...)
async def cache_get(key: str):
    manager = CacheManager()
    return await manager.get(key)
```

**Timeline:** 2-3 hours

#### Priority 2: deontological_reasoning_tools.py (595 lines)

**Issue:** Parsing and conflict detection logic in tool

**Solution:**
```python
# Move to: ipfs_datasets_py/logic/deontic/parser.py
# Move to: ipfs_datasets_py/logic/deontic/conflict_detector.py

# Tool becomes:
from ipfs_datasets_py.logic.deontic import DeonticParser, ConflictDetector

@wrap_function_as_tool(...)
async def detect_conflicts(statements: List[str]):
    parser = DeonticParser()
    detector = ConflictDetector()
    parsed = [parser.parse(s) for s in statements]
    return detector.detect_conflicts(parsed)
```

**Timeline:** 3-4 hours

#### Priority 3: relationship_timeline_tools.py (400+ lines)

**Issue:** NLP and graph analysis in tool

**Solution:**
```python
# Move to: ipfs_datasets_py/processors/nlp/entity_extractor.py
# Move to: ipfs_datasets_py/processors/nlp/relationship_analyzer.py

# Tool becomes:
from ipfs_datasets_py.processors.nlp import EntityExtractor, RelationshipAnalyzer

@wrap_function_as_tool(...)
async def analyze_relationships(text: str):
    extractor = EntityExtractor()
    analyzer = RelationshipAnalyzer()
    entities = await extractor.extract(text)
    return await analyzer.analyze(entities)
```

**Timeline:** 3-4 hours

### Part D: Testing Infrastructure

#### 1. Tool Thinness Validator

**File:** `tests/tools/test_tool_thinness.py`

```python
import os
from pathlib import Path

def count_lines(file_path):
    """Count non-comment, non-blank lines."""
    with open(file_path) as f:
        lines = f.readlines()
    
    code_lines = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            code_lines += 1
    return code_lines

def test_tool_files_are_thin():
    """Verify tool files are <100 lines (excluding schemas)."""
    tools_dir = Path("ipfs_datasets_py/mcp_server/tools")
    
    thick_tools = []
    for tool_file in tools_dir.rglob("*.py"):
        if tool_file.name.startswith("_") or tool_file.name.startswith("test_"):
            continue
        
        lines = count_lines(tool_file)
        
        # Allow larger files if they have multiple tools
        # or are legacy/complex state tools
        allowed_thick = ["cache_tools.py", "analysis_tools.py", "legacy"]
        
        if lines > 150 and not any(a in str(tool_file) for a in allowed_thick):
            thick_tools.append((tool_file, lines))
    
    assert len(thick_tools) == 0, f"Thick tools found: {thick_tools}"
```

#### 2. Core Module Import Checker

**File:** `tests/tools/test_core_imports.py`

```python
def test_tools_import_from_core():
    """Verify tools import from core modules, not embed logic."""
    tools_dir = Path("ipfs_datasets_py/mcp_server/tools")
    
    missing_imports = []
    for tool_file in tools_dir.rglob("*.py"):
        if tool_file.name.startswith("_"):
            continue
        
        with open(tool_file) as f:
            content = f.read()
        
        # Check for core module imports
        has_core_import = any([
            "from ipfs_datasets_py." in content,
            "import ipfs_datasets_py." in content
        ])
        
        # Exclude certain files (like __init__.py)
        if not has_core_import and tool_file.name != "__init__.py":
            missing_imports.append(tool_file)
    
    # Report but don't fail (some tools may be self-contained)
    if missing_imports:
        print(f"Tools without core imports: {missing_imports}")
```

---

## Implementation Timeline

### Week 1: Foundation (8 hours)
- **Day 1-2:** Create pattern documentation (Part A)
  - tool-patterns.md
  - tool-template.py
  - tool-migration-guide.md

- **Day 2-3:** Create tool templates (Part B)
  - 4 template files
  - Examples and documentation

### Week 2: Refactoring (12 hours)
- **Day 1-2:** Refactor cache_tools.py (Priority 1)
  - Extract CacheManager to core
  - Update tool to be thin wrapper
  - Tests

- **Day 3:** Refactor deontological_reasoning_tools.py (Priority 2)
  - Extract parsing logic
  - Extract conflict detection
  - Update tool

- **Day 4-5:** Testing infrastructure (Part D)
  - Tool thinness validator
  - Import checker
  - Pattern compliance checker

### Week 3: Polish (4 hours)
- **Day 1:** Documentation updates
- **Day 2:** Review and validation
- **Day 3:** Phase 2 completion report

**Total Estimated Time:** 24 hours over 3 weeks

---

## Success Criteria

### Quantitative Metrics
- [ ] ≥80% of tools follow standard pattern
- [ ] All tools <150 lines (excluding allowed exceptions)
- [ ] All tools import from core modules
- [ ] ≥90% of tools have type hints
- [ ] Tool thinness tests passing

### Qualitative Metrics
- [ ] Clear tool development documentation
- [ ] Easy-to-use templates
- [ ] Consistent error handling
- [ ] Third-party developers can create tools easily

---

## Next Phases Preview

**Phase 3: Enhanced Tool Nesting**
- Nested command structure (dataset/load, search/semantic)
- Hierarchical discovery
- Context window optimization

**Phase 4: CLI-MCP Syntax Alignment**
- Shared schemas
- Unified validation
- Parameter parity

---

## Related Documents

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md)
- [Tool Development Guide](../development/) (to be created)
- [Phase 1 Complete Summary](./PHASE_1_COMPLETE_SUMMARY.md)

---

**Status:** Planning complete, ready for implementation  
**Next:** Begin Part A (Pattern Standardization)
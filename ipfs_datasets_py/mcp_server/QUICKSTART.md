# MCP++ Integration Quick Start Guide

**Date:** 2026-02-17  
**Audience:** Developers implementing the MCP++ integration  
**Estimated Time:** 2-3 hours to understand, 10 weeks to implement  

This guide provides a quick overview of the MCP++ integration project for developers who need to get up to speed quickly.

---

## 🎯 Project Goal

Enhance the IPFS Datasets MCP server with advanced P2P capabilities from the sister package's MCP++ module, achieving:
- **50-70% reduction** in P2P operation latency
- **20+ new P2P tools** (workflow scheduler, peer management)
- **Improved architecture** with dual-runtime design
- **Backward compatibility** with all existing features

---

## 📁 Key Documents

| Document | Purpose | When to Read |
|----------|---------|--------------|
| `MCP_IMPROVEMENT_PLAN.md` | Comprehensive improvement plan (24KB) | First - complete overview |
| `ARCHITECTURE_INTEGRATION.md` | Technical architecture (28KB) | Second - design details |
| `IMPLEMENTATION_CHECKLIST.md` | Task checklist (15KB) | During implementation |
| `P2P_MIGRATION_GUIDE.md` | User migration guide | For end users |

---

## 🏗️ Architecture Overview

### Current State
```
User → FastAPI → trio_bridge (thread hops) → Trio → libp2p
        370 tools          SLOW!
```
**Latency:** ~200ms for P2P operations

### Target State
```
User → Unified Registry → Runtime Router
                              ├─→ FastAPI → 370 general tools
                              └─→ Trio (direct!) → 20 P2P tools → libp2p
```
**Latency:** <100ms for P2P operations (50-70% reduction)

### Key Innovation: Dual Runtime

Instead of migrating everything to Trio (high risk), we run **two runtimes side-by-side**:
1. **FastAPI runtime** - handles general tools (dataset, IPFS, vector, etc.)
2. **Trio runtime** - handles P2P-intensive tools (workflow, task queue, peers)

A **Runtime Router** intelligently directs traffic to the appropriate runtime.

---

## 🔑 Key Components

### 1. MCP++ Import Layer (`mcplusplus/`)
**What:** Wrapper around ipfs_accelerate_py's mcplusplus_module  
**Why:** Graceful imports, fallback logic, API adaptation  
**Files:**
- `workflow_scheduler.py` - P2P workflow scheduler
- `task_queue.py` - Enhanced task queue
- `peer_registry.py` - Peer discovery
- `bootstrap.py` - Network bootstrap
- `connection_pool.py` - Connection reuse

### 2. Runtime Router (`runtime_router.py`)
**What:** Routes tool execution to appropriate runtime  
**Why:** Eliminate thread hops for P2P operations  
**Logic:**
```python
if tool_name in P2P_TOOLS and trio_available:
    return trio_runtime.execute(tool_name, args)
else:
    return fastapi_runtime.execute(tool_name, args)
```

### 3. Enhanced P2P Service Manager
**What:** Extended with MCP++ capabilities  
**Why:** Integrate workflow scheduler, peer registry, bootstrap  
**Files:** `p2p_service_manager.py`, `p2p_mcp_registry_adapter.py`

### 4. New P2P Tools (20 tools)
**What:** Tools from MCP++ module  
**Categories:**
- 6 workflow tools: submit, status, cancel, list, result, reschedule
- 14 task queue tools: submit, monitor, manage, queue ops
- 6 peer management tools: discover, connect, disconnect, list, bootstrap, metrics

---

## 🚀 Getting Started

### Prerequisites
```bash
# Python 3.12+
python --version

# Clone repos
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Check for ipfs_accelerate_py submodule
ls -la ipfs_accelerate_py/

# If missing, add it
git submodule update --init --recursive
```

### Install Dependencies
```bash
# Install base dependencies
pip install -e .

# Install development dependencies
pip install -e ".[dev,test]"

# Verify MCP++ module available
python -c "from ipfs_accelerate_py.mcplusplus_module import __version__; print('OK')"
```

### Run Existing Tests (Establish Baseline)
```bash
# Run MCP server tests
pytest tests/mcp/ -v

# Check current test count
pytest tests/mcp/ --collect-only | grep "test session starts"

# Run performance baseline
pytest tests/mcp/test_performance.py --benchmark-only
```

### Explore Current Code
```bash
# MCP server structure
ls -la ipfs_datasets_py/mcp_server/

# Current P2P integration
cat ipfs_datasets_py/mcp_server/p2p_service_manager.py

# Tool structure
ls -la ipfs_datasets_py/mcp_server/tools/ | head -20

# Count tools
find ipfs_datasets_py/mcp_server/tools -name "*.py" | wc -l
```

### Explore MCP++ Module
```bash
# MCP++ structure
ls -la ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/

# MCP++ components
ls -la ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/p2p/
ls -la ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/trio/
ls -la ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/tools/
```

---

## 📋 Implementation Phases (Quick Overview)

### Phase 1: Foundation (Weeks 1-2)
**Goal:** Import MCP++ modules, extend P2P service manager  
**Deliverables:**
- `mcplusplus/` directory with import wrappers
- Enhanced `p2p_service_manager.py`
- Unit tests for imports
- Documentation updates

**Start Here:**
```bash
# Create directory
mkdir -p ipfs_datasets_py/mcp_server/mcplusplus

# Create first file
touch ipfs_datasets_py/mcp_server/mcplusplus/__init__.py
```

### Phase 2: P2P Tools (Weeks 3-4)
**Goal:** Add 20 P2P tools from MCP++  
**Deliverables:**
- 6 workflow tools
- 14 task queue tools
- 6 peer management tools
- Integration tests

### Phase 3: Performance (Weeks 5-6)
**Goal:** Eliminate bridging overhead, optimize  
**Deliverables:**
- Runtime router
- Connection pooling
- Performance benchmarks (50-70% improvement)

### Phase 4: Advanced Features (Weeks 7-8)
**Goal:** Structured concurrency, optional features  
**Deliverables:**
- Parallel tool execution
- Event provenance (optional)
- Content-addressed contracts (optional)

### Phase 5: Testing & Docs (Weeks 9-10)
**Goal:** Comprehensive testing and documentation  
**Deliverables:**
- 90+ new tests (90%+ coverage)
- Complete documentation
- CI/CD integration

---

## 🔧 Development Workflow

### 1. Pick a Task from Checklist
```bash
# Open the checklist
cat ipfs_datasets_py/mcp_server/IMPLEMENTATION_CHECKLIST.md
```

### 2. Create Feature Branch
```bash
git checkout -b feature/mcplusplus-phase1-imports
```

### 3. Implement Changes
```python
# Example: Create workflow_scheduler.py wrapper

from __future__ import annotations
from typing import Optional

# Graceful import with fallback
try:
    from ipfs_accelerate_py.mcplusplus_module.p2p.workflow import (
        P2PWorkflowScheduler,
        get_scheduler,
    )
    HAVE_WORKFLOW_SCHEDULER = True
except ImportError:
    HAVE_WORKFLOW_SCHEDULER = False
    P2PWorkflowScheduler = None
    
    def get_scheduler() -> None:
        return None

# Your wrapper API
def create_workflow_scheduler(*args, **kwargs) -> Optional[P2PWorkflowScheduler]:
    """Create a P2P workflow scheduler instance."""
    if not HAVE_WORKFLOW_SCHEDULER:
        return None
    
    return get_scheduler()
```

### 4. Write Tests
```python
# tests/mcp/test_workflow_scheduler.py

import pytest
from ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler import (
    create_workflow_scheduler,
    HAVE_WORKFLOW_SCHEDULER,
)

def test_workflow_scheduler_available():
    """Test workflow scheduler is available when dependency exists."""
    # GIVEN: MCP++ module is available
    if not HAVE_WORKFLOW_SCHEDULER:
        pytest.skip("MCP++ not available")
    
    # WHEN: Create scheduler
    scheduler = create_workflow_scheduler()
    
    # THEN: Scheduler created successfully
    assert scheduler is not None

def test_workflow_scheduler_graceful_degradation():
    """Test graceful degradation when MCP++ unavailable."""
    # GIVEN: MCP++ module might not be available
    
    # WHEN: Create scheduler
    scheduler = create_workflow_scheduler()
    
    # THEN: Either scheduler created or None returned (no crash)
    assert scheduler is None or scheduler is not None
```

### 5. Run Tests
```bash
# Run your new tests
pytest tests/mcp/test_workflow_scheduler.py -v

# Run all MCP tests
pytest tests/mcp/ -v

# Check coverage
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=html
```

### 6. Update Documentation
```bash
# Update CHANGELOG
echo "- Added workflow scheduler wrapper in mcplusplus/" >> ipfs_datasets_py/mcp_server/CHANGELOG.md

# Update implementation checklist
# Mark completed items with [x]
```

### 7. Commit and Push
```bash
git add .
git commit -m "Phase 1.1.2: Add workflow scheduler wrapper

- Create mcplusplus/workflow_scheduler.py
- Graceful import with fallback
- Add unit tests
- Update documentation"

git push origin feature/mcplusplus-phase1-imports
```

### 8. Create Pull Request
- Title: "[MCP++] Phase 1.1.2: Add workflow scheduler wrapper"
- Link to improvement plan
- Describe changes
- Show test results
- Request review

---

## 🧪 Testing Strategy

### Unit Tests
**What:** Test individual components in isolation  
**Example:**
```python
def test_runtime_router_detects_p2p_tool():
    router = RuntimeRouter()
    assert router.get_runtime("submit_workflow") == "trio"
    assert router.get_runtime("load_dataset") == "fastapi"
```

### Integration Tests
**What:** Test component interactions  
**Example:**
```python
async def test_workflow_submission_end_to_end():
    server = create_test_server(enable_mcplusplus=True)
    result = await server.execute_tool("submit_workflow", {...})
    assert result["status"] == "success"
```

### Performance Tests
**What:** Benchmark critical paths  
**Example:**
```python
def test_p2p_latency(benchmark):
    result = benchmark(lambda: execute_p2p_tool("submit_workflow", {...}))
    assert benchmark.stats.mean < 0.1  # <100ms
```

---

## 📊 Success Metrics

Track these metrics throughout development:

| Metric | Baseline | Target | Measure |
|--------|----------|--------|---------|
| P2P latency | ~200ms | <100ms | Benchmarks |
| Startup time | ~5s | <2s | Profiling |
| Memory usage | ~200MB | <150MB | Monitoring |
| Test coverage | ~70% | >90% | Coverage |
| Tool count | 370 | 390+ | Count |

---

## 🐛 Common Issues & Solutions

### Issue: Can't Import MCP++ Module
**Solution:**
```bash
# Verify submodule
git submodule status

# Update submodule
git submodule update --init --recursive

# Verify import
python -c "from ipfs_accelerate_py.mcplusplus_module import __version__"
```

### Issue: Tests Fail with "Trio Not Available"
**Solution:**
```bash
# Install trio
pip install trio>=0.22.0

# Verify
python -c "import trio; print(trio.__version__)"
```

### Issue: Existing Tests Break
**Solution:**
- Run git diff to see changes
- Check if you modified existing functions
- Verify backward compatibility
- Run full test suite: `pytest tests/ -v`

### Issue: Performance Regression
**Solution:**
- Profile with: `pytest --profile`
- Check if runtime router overhead too high
- Verify no accidental thread hops
- Compare with baseline benchmarks

---

## 📚 Additional Resources

### MCP++ Module Documentation
- **README:** `/tmp/ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/README.md`
- **Examples:** `/tmp/ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/examples/`
- **Tests:** `/tmp/ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module/tests/`

### Related Projects
- **IPFS Datasets:** https://github.com/endomorphosis/ipfs_datasets_py
- **IPFS Accelerate:** https://github.com/endomorphosis/ipfs_accelerate_py
- **MCP Specification:** https://spec.modelcontextprotocol.io/

### Community
- **Issues:** https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Discussions:** https://github.com/endomorphosis/ipfs_datasets_py/discussions
- **Discord:** (TBD)

---

## 🎓 Learning Path

### Day 1: Understanding (2-3 hours)
1. Read `MCP_IMPROVEMENT_PLAN.md` (Executive Summary + Gap Analysis)
2. Read `ARCHITECTURE_INTEGRATION.md` (Overview + Diagrams)
3. Explore current MCP server code
4. Explore MCP++ module code

### Day 2: Environment Setup (1-2 hours)
1. Clone repositories
2. Install dependencies
3. Run existing tests
4. Establish baseline metrics

### Week 1: First Contribution
1. Pick Phase 1.1.1 task (add dependency)
2. Implement change
3. Write tests
4. Submit PR

### Ongoing: Iterative Development
- Pick tasks from checklist
- Implement → Test → Document → Review
- Track progress weekly
- Adjust plan as needed

---

## 💡 Tips for Success

### Do's ✅
- **Start small:** Begin with Phase 1 tasks
- **Test everything:** Write tests before/during implementation
- **Document as you go:** Update docs with each change
- **Ask questions:** Open issues for clarification
- **Follow patterns:** Match existing code style
- **Check compatibility:** Verify no breaking changes
- **Measure performance:** Benchmark before/after

### Don'ts ❌
- **Don't skip tests:** Tests prevent regressions
- **Don't ignore docs:** Documentation is critical
- **Don't rush:** Quality > speed
- **Don't work in isolation:** Communicate with team
- **Don't break compatibility:** Users depend on existing APIs
- **Don't ignore CI/CD:** Fix failing tests immediately

---

## 🤝 Getting Help

### Technical Questions
- Open issue on GitHub
- Tag with `question` label
- Include code examples

### Implementation Questions
- Refer to improvement plan documents
- Check ADRs (Architecture Decision Records)
- Ask in code review

### Blockers
- Document blocker clearly
- Propose alternative approaches
- Escalate to project lead

---

## 📈 Progress Tracking

### Daily
- Update checklist with completed items
- Run tests for changed code
- Commit frequently

### Weekly
- Review progress against plan
- Update metrics dashboard
- Team sync meeting
- Adjust plan if needed

### Phase Completion
- Complete all phase tasks
- Run full test suite
- Update all documentation
- Demo to stakeholders

---

## 🎉 You're Ready!

You now have everything you need to start implementing the MCP++ integration:

1. ✅ **Understanding:** You know the goal and architecture
2. ✅ **Plan:** You have detailed improvement plan
3. ✅ **Checklist:** You have implementation tasks
4. ✅ **Guide:** You have this quick start guide
5. ✅ **Resources:** You know where to find help

**Next Step:** Open `IMPLEMENTATION_CHECKLIST.md` and start with Phase 1.1.1!

---

**Good luck, and happy coding!** 🚀

---

**Guide Version:** 1.0  
**Last Updated:** 2026-02-17  
**Feedback:** Open an issue or PR to improve this guide

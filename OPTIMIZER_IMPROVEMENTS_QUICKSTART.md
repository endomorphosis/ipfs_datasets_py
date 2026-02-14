# Optimizer Framework Improvements - Implementation Plan

**Created:** 2026-02-14  
**Status:** 📋 Ready to Implement  
**Priority:** Recommended improvements based on analysis  

---

## Quick Start - Priority 1 Items

These are high-impact, low-effort improvements that can be implemented immediately:

### 1. Add Missing Tests (2-3 days) 🎯

**Files to Test:**
```bash
ipfs_datasets_py/optimizers/
├── optimizer_learning_metrics.py         # 48KB - NO TESTS
├── optimizer_alert_system.py             # 27KB - NO TESTS
└── optimizer_visualization_integration.py # 16KB - NO TESTS
```

**Create:**
```bash
tests/unit/optimizers/
├── test_optimizer_learning_metrics.py      # NEW
├── test_optimizer_alert_system.py          # NEW
└── test_optimizer_visualization.py         # NEW
```

**Why This Matters:**
- These are critical monitoring components
- No test coverage = high regression risk
- Blocks safe refactoring
- Current coverage: 88% (agentic only) → Target: 90%+ overall

**Implementation Steps:**
1. Create test file structure
2. Write unit tests for each class
3. Write integration tests for workflows
4. Achieve 80%+ coverage per module

---

### 2. Document Optimizer Selection (1 day) 📚

**Create:**
```markdown
docs/optimizers/SELECTION_GUIDE.md

# When to Use Which Optimizer

## Decision Tree
┌─ Need formal verification? → Logic Theorem Optimizer
├─ Need knowledge graph optimization? → GraphRAG Optimizer
└─ Need code optimization? → Agentic Optimizer
    ├─ Multiple approaches? → Adversarial
    ├─ Learning from feedback? → Actor-Critic
    ├─ Test-driven? → Test-Driven
    └─ Resilience testing? → Chaos Engineering
```

**Why This Matters:**
- Users don't know when to use which optimizer
- Reduces support burden
- Improves user experience
- Takes <1 day to create

---

### 3. Create Unified CLI (3-4 days) 🔧

**Current State:**
```bash
# Agentic only
python -m ipfs_datasets_py.optimizers.agentic.cli optimize ...

# Logic & GraphRAG: No CLI ❌
```

**Proposed:**
```bash
# Single entry point for all
python -m ipfs_datasets_py.optimizers.cli optimize \
    --type agentic \
    --method test_driven \
    --target file.py

python -m ipfs_datasets_py.optimizers.cli optimize \
    --type logic \
    --input legal_doc.txt

python -m ipfs_datasets_py.optimizers.cli optimize \
    --type graphrag \
    --query "optimize knowledge graph"
```

**Implementation:**
```python
# optimizers/cli.py (NEW)

import argparse
from .agentic.cli import OptimizerCLI as AgenticCLI

class UnifiedOptimizerCLI:
    """Unified CLI for all optimizer types."""
    
    def __init__(self):
        self.agentic = AgenticCLI()
        # Will add: self.logic = LogicCLI()
        # Will add: self.graphrag = GraphRAGCLI()
    
    def main(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--type", choices=["agentic", "logic", "graphrag"])
        # ...
        
        args = parser.parse_args()
        
        if args.type == "agentic":
            return self.agentic.run(args)
        # ...
```

**Why This Matters:**
- Consistent user experience
- Single entry point
- Easier to document
- Simpler automation

---

## Implementation Workflow

### Week 1: Testing Foundation

**Day 1-2: Optimizer Learning Metrics Tests**
```python
# tests/unit/optimizers/test_optimizer_learning_metrics.py

def test_learning_metrics_collection():
    """Test metrics are collected correctly."""
    collector = OptimizerLearningMetricsCollector()
    collector.record_optimization(task, result)
    
    metrics = collector.get_metrics()
    assert metrics.total_optimizations > 0
    assert metrics.success_rate >= 0

def test_metrics_persistence():
    """Test metrics persist correctly."""
    collector = OptimizerLearningMetricsCollector()
    collector.save("metrics.json")
    
    loaded = OptimizerLearningMetricsCollector.load("metrics.json")
    assert loaded.get_metrics() == collector.get_metrics()

# ... 20+ more tests
```

**Day 3: Alert System Tests**
```python
# tests/unit/optimizers/test_optimizer_alert_system.py

def test_alert_generation():
    """Test alerts generated for anomalies."""
    alert_system = LearningAlertSystem()
    
    # Simulate anomaly
    for i in range(10):
        alert_system.check_anomaly(success_rate=0.2)  # Low
    
    alerts = alert_system.get_alerts()
    assert len(alerts) > 0
    assert any(a.severity == "high" for a in alerts)

# ... 15+ more tests
```

**Day 4-5: Visualization Tests**
```python
# tests/unit/optimizers/test_optimizer_visualization.py

def test_visualization_setup():
    """Test visualization initializes correctly."""
    viz = LiveOptimizerVisualization()
    viz.setup_metrics_collector(collector)
    
    assert viz.metrics_collector is not None

def test_auto_update_loop():
    """Test auto-update loop works."""
    viz = LiveOptimizerVisualization()
    viz.start_auto_update(interval=0.1)
    
    time.sleep(0.3)
    assert viz.update_count >= 2
    
    viz.stop_auto_update()

# ... 10+ more tests
```

**Deliverable:** 45+ new tests, 90%+ coverage

---

### Week 2: Documentation & Selection Guide

**Day 1-2: Selection Guide**
```markdown
# SELECTION_GUIDE.md

## Optimizer Comparison Matrix

| Feature | Agentic | Logic | GraphRAG |
|---------|---------|-------|----------|
| Code Optimization | ✅ | ❌ | ❌ |
| Formal Verification | ❌ | ✅ | ❌ |
| Knowledge Graphs | ❌ | ❌ | ✅ |
| Test Generation | ✅ | ❌ | ❌ |
| LLM Integration | ✅ 6 providers | ✅ Basic | ✅ RAG |

## Use Cases

### Agentic Optimizer
**Problem:** "My code is slow"
**Solution:** Run adversarial optimizer to generate 5 competing implementations

**Problem:** "Need better test coverage"
**Solution:** Run test-driven optimizer to generate comprehensive tests

### Logic Theorem Optimizer
**Problem:** "Need to verify legal contract logic"
**Solution:** Extract formal logic → prove theorems

### GraphRAG Optimizer
**Problem:** "RAG queries are not finding relevant info"
**Solution:** Optimize knowledge graph structure
```

**Day 3-5: User Guide**
```markdown
# USER_GUIDE.md

## Quick Start

### 1. Install
pip install -e ".[optimizers]"

### 2. Choose Optimizer
See SELECTION_GUIDE.md

### 3. Run Optimization
# Agentic
python -m ipfs_datasets_py.optimizers.agentic.cli optimize ...

### 4. Review Results
python -m ipfs_datasets_py.optimizers.agentic.cli stats

## Tutorials
- Tutorial 1: Optimizing Code with Agentic
- Tutorial 2: Formal Verification with Logic
- Tutorial 3: Knowledge Graph Optimization
```

**Deliverable:** Complete selection guide + user guide

---

### Week 3-4: Unified CLI

**Day 1-2: CLI Structure**
```python
# optimizers/cli.py

class UnifiedOptimizerCLI:
    def __init__(self):
        self.agentic = AgenticCLI()
    
    def create_parser(self):
        parser = argparse.ArgumentParser(
            description="Unified Optimizer CLI"
        )
        parser.add_argument(
            "--type",
            choices=["agentic", "logic", "graphrag"],
            required=True,
            help="Optimizer type to use"
        )
        
        subparsers = parser.add_subparsers(dest="command")
        
        # Optimize command
        opt_parser = subparsers.add_parser("optimize")
        opt_parser.add_argument("--method")
        opt_parser.add_argument("--target")
        # ...
        
        return parser
```

**Day 3-4: Logic & GraphRAG CLI Wrappers**
```python
# logic_theorem_optimizer/cli.py (NEW)

class LogicOptimizerCLI:
    """CLI interface for logic theorem optimizer."""
    
    def optimize(self, args):
        optimizer = LogicTheoremOptimizer()
        result = optimizer.extract_and_prove(args.input)
        return result

# graphrag/cli.py (NEW)

class GraphRAGOptimizerCLI:
    """CLI interface for GraphRAG optimizer."""
    
    def optimize(self, args):
        optimizer = GraphRAGOptimizer()
        result = optimizer.optimize_query(args.query)
        return result
```

**Day 5: Integration & Testing**
```python
# tests/unit/optimizers/test_unified_cli.py

def test_cli_routing():
    """Test CLI routes to correct optimizer."""
    cli = UnifiedOptimizerCLI()
    
    # Test agentic routing
    result = cli.run(["--type", "agentic", "optimize", ...])
    assert result.optimizer_type == "agentic"
    
    # Test logic routing
    result = cli.run(["--type", "logic", "optimize", ...])
    assert result.optimizer_type == "logic"
```

**Deliverable:** Single CLI entry point for all optimizers

---

## Testing Your Improvements

### Run Tests
```bash
# Run all optimizer tests
pytest tests/unit/optimizers/ -v

# Run with coverage
pytest tests/unit/optimizers/ --cov=ipfs_datasets_py.optimizers --cov-report=html

# Run specific test file
pytest tests/unit/optimizers/test_optimizer_learning_metrics.py -v
```

### Verify CLI
```bash
# Test unified CLI
python -m ipfs_datasets_py.optimizers.cli --help

# Test each optimizer type
python -m ipfs_datasets_py.optimizers.cli optimize --type agentic --help
python -m ipfs_datasets_py.optimizers.cli optimize --type logic --help
python -m ipfs_datasets_py.optimizers.cli optimize --type graphrag --help
```

### Check Documentation
```bash
# Verify guides exist
ls docs/optimizers/SELECTION_GUIDE.md
ls docs/optimizers/USER_GUIDE.md

# Check completeness
grep -c "##" docs/optimizers/SELECTION_GUIDE.md  # Should have multiple sections
```

---

## Next Steps After Priority 1

Once Priority 1 items are complete, consider:

### Priority 2: Performance (Week 5)
- Add profiling decorators
- Implement result caching
- Parallelize validation
- Optimize LLM calls (70-90% reduction via caching)

### Priority 3: Migration (Weeks 6-7)
- Migrate logic_theorem_optimizer to BaseOptimizer
- Migrate graphrag optimizer to BaseOptimizer
- Eliminate 1,500-2,000 lines of duplicate code

### Priority 4: Integration Tests (Week 8)
- Cross-optimizer workflows
- Parallel execution tests
- Error handling tests

---

## Success Criteria

### Completion Checklist

**Priority 1 Complete When:**
- [ ] All 3 test files created with 80%+ coverage each
- [ ] Selection guide published (SELECTION_GUIDE.md)
- [ ] User guide published (USER_GUIDE.md)
- [ ] Unified CLI working for agentic optimizer
- [ ] CLI wrappers created for logic and graphrag
- [ ] All tests passing
- [ ] Documentation reviewed

**Metrics:**
- Test coverage: 88% → 90%+
- CLI: 1 optimizer → 3 optimizers
- Documentation: 1 guide → 3 guides
- Lines of documentation: +500 lines
- Lines of tests: +400 lines

---

## Getting Help

**Questions?**
1. Review OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md for detailed analysis
2. Check OPTIMIZER_REFACTORING_COMPLETE.md for recent work
3. See ipfs_datasets_py/optimizers/README.md for current status

**Resources:**
- Agentic optimizer tests: `tests/unit/optimizers/agentic/`
- Common patterns: `ipfs_datasets_py/optimizers/common/`
- Existing CLI: `ipfs_datasets_py/optimizers/agentic/cli.py`

---

**Ready to start?** Begin with Week 1, Day 1: test_optimizer_learning_metrics.py

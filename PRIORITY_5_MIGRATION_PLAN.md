# Priority 5: Base Layer Migration Plan

## Executive Summary

**Goal:** Eliminate 1,500-2,000 lines of duplicate code by migrating `logic_theorem_optimizer` and `graphrag` optimizer to use the common `BaseOptimizer` interface.

**Timeline:** 3 weeks (15 days)
- Week 1: Logic theorem optimizer migration (800-1,000 lines)
- Week 2: GraphRAG optimizer migration (700-1,000 lines)
- Week 3: Integration and cleanup (200-300 lines)

**Expected Result:** Reduce code duplication from 40-50% to <10%

---

## Current State Analysis

### BaseOptimizer Interface

The `optimizers/common/base_optimizer.py` provides:

```python
class BaseOptimizer(ABC):
    """Base class for all optimizer types."""
    
    @abstractmethod
    def generate(input_data, context) -> artifact
        """Generate initial artifact from input."""
    
    @abstractmethod
    def critique(artifact, context) -> (score, feedback)
        """Evaluate quality of artifact."""
    
    @abstractmethod
    def optimize(artifact, score, feedback, context) -> improved_artifact
        """Improve artifact based on feedback."""
    
    def validate(artifact, context) -> bool
        """Validate artifact (optional override)."""
    
    def run_session(input_data, context) -> results
        """Run complete optimization workflow."""
```

**Provides:**
- Standardized optimization workflow
- Configuration management (OptimizerConfig)
- Context management (OptimizationContext)
- Metrics collection infrastructure
- Common strategies (OptimizationStrategy enum)

### Logic Theorem Optimizer (24 files)

**Main Components:**
- `logic_optimizer.py` (350+ lines) - SGD-based optimization
- `logic_extractor.py` (400+ lines) - Extract formal logic
- `logic_critic.py` (300+ lines) - Evaluate logic quality
- `prover_integration.py` (250+ lines) - Theorem proving
- `logic_harness.py` (450+ lines) - Orchestration

**Duplicate Patterns:**
- Custom `OptimizationStrategy` enum (duplicate)
- Custom `OptimizationReport` dataclass (duplicate)
- Custom configuration management
- Custom session management
- Custom metrics collection

**Estimated Duplication:** 800-1,000 lines

### GraphRAG Optimizer (13 files)

**Main Components:**
- `ontology_optimizer.py` (400+ lines) - SGD-based optimization
- `ontology_generator.py` (350+ lines) - Generate ontology
- `ontology_critic.py` (300+ lines) - Evaluate ontology
- `logic_validator.py` (200+ lines) - Validation logic
- `ontology_harness.py` (450+ lines) - Orchestration

**Duplicate Patterns:**
- Custom `OptimizationReport` dataclass (duplicate)
- Custom configuration management
- Custom session management
- Custom metrics collection
- Similar SGD patterns

**Estimated Duplication:** 700-1,000 lines

---

## Week 1: Logic Theorem Optimizer Migration

### Day 1-2: Create Unified Wrapper

**Goal:** Create `LogicTheoremOptimizer(BaseOptimizer)` wrapper

**Tasks:**
1. Create `logic_theorem_optimizer/unified_optimizer.py`
2. Implement `LogicTheoremOptimizer` class extending `BaseOptimizer`
3. Map abstract methods to existing components:

```python
class LogicTheoremOptimizer(BaseOptimizer):
    """Unified logic theorem optimizer using BaseOptimizer."""
    
    def __init__(self, config=None, llm_backend=None):
        super().__init__(config, llm_backend)
        self.extractor = LogicExtractor(llm_backend)
        self.critic = LogicCritic()
        self.prover = ProverIntegration()
        
    def generate(self, input_data, context):
        """Extract formal logic from input text."""
        # Delegate to logic_extractor
        return self.extractor.extract(
            text=input_data,
            domain=context.domain,
            format=context.metadata.get('format', 'FOL')
        )
    
    def critique(self, artifact, context):
        """Evaluate logic quality."""
        # Delegate to logic_critic
        result = self.critic.evaluate(artifact)
        score = result.overall_score
        feedback = result.recommendations
        return score, feedback
    
    def optimize(self, artifact, score, feedback, context):
        """Improve logic based on feedback."""
        # Use existing logic_optimizer suggestions
        improved = apply_improvements(artifact, feedback)
        return improved
    
    def validate(self, artifact, context):
        """Validate logic with theorem provers."""
        # Delegate to prover_integration
        return self.prover.validate(artifact)
```

4. Add backward compatibility methods
5. Preserve all existing functionality

**Expected Output:**
- `unified_optimizer.py` (300-400 lines)
- All existing functionality working through new interface

---

### Day 3-4: Remove Duplicates and Integrate

**Goal:** Remove duplicate code and integrate with BaseOptimizer infrastructure

**Tasks:**

1. **Remove Duplicate Enums/Dataclasses:**
   - Delete custom `OptimizationStrategy` enum → Use `common.OptimizationStrategy`
   - Delete custom `OptimizationReport` dataclass → Map to base result format
   - Estimated: 100-150 lines removed

2. **Migrate Configuration:**
   - Replace custom config with `OptimizerConfig`
   - Update all references to use standardized config
   - Estimated: 150-200 lines removed

3. **Migrate Session Management:**
   - Use `OptimizationContext` for session state
   - Remove custom session tracking
   - Estimated: 100-150 lines removed

4. **Integrate Metrics:**
   - Use base metrics collection
   - Remove duplicate metrics code
   - Estimated: 100-150 lines removed

5. **Update CLI Wrapper:**
   - Update `cli_wrapper.py` to use `LogicTheoremOptimizer`
   - Maintain backward compatibility
   - Estimated: 50-100 lines modified

6. **Update __init__.py:**
   - Export `LogicTheoremOptimizer`
   - Add deprecation warnings for old interfaces

**Expected Elimination:** 400-500 lines

---

### Day 5: Testing and Validation

**Goal:** Ensure all functionality works correctly

**Tasks:**

1. **Create Migration Tests:**
   - Test `LogicTheoremOptimizer` initialization
   - Test all abstract methods
   - Test `run_session()` workflow
   - Test backward compatibility

2. **Update Existing Tests:**
   - Adapt tests to new interface
   - Ensure all tests pass
   - Verify no regressions

3. **CLI Testing:**
   - Test all CLI commands
   - Verify extract/prove/validate/optimize commands
   - Test status command

4. **Documentation:**
   - Update README.md
   - Document migration changes
   - Update usage examples

**Expected Total Elimination:** 800-1,000 lines

---

## Week 2: GraphRAG Optimizer Migration

### Day 6-7: Create Unified Wrapper

**Goal:** Create `GraphRAGOptimizer(BaseOptimizer)` wrapper

**Tasks:**
1. Create `graphrag/unified_optimizer.py`
2. Implement `GraphRAGOptimizer` class:

```python
class GraphRAGOptimizer(BaseOptimizer):
    """Unified GraphRAG optimizer using BaseOptimizer."""
    
    def __init__(self, config=None, llm_backend=None):
        super().__init__(config, llm_backend)
        self.generator = OntologyGenerator(llm_backend)
        self.critic = OntologyCritic()
        self.validator = LogicValidator()
        
    def generate(self, input_data, context):
        """Generate ontology from documents."""
        return self.generator.generate(
            documents=input_data,
            domain=context.domain,
            strategy=context.metadata.get('strategy', 'hybrid')
        )
    
    def critique(self, artifact, context):
        """Evaluate ontology quality."""
        result = self.critic.evaluate(artifact)
        score = result.overall_score
        feedback = result.recommendations
        return score, feedback
    
    def optimize(self, artifact, score, feedback, context):
        """Improve ontology based on feedback."""
        improved = apply_ontology_improvements(artifact, feedback)
        return improved
    
    def validate(self, artifact, context):
        """Validate ontology structure."""
        return self.validator.check(artifact)
```

3. Add backward compatibility
4. Preserve existing functionality

**Expected Output:**
- `unified_optimizer.py` (250-350 lines)
- All functionality working through new interface

---

### Day 8-9: Remove Duplicates and Integrate

**Goal:** Remove duplicate code and integrate

**Tasks:**

1. **Remove Duplicate Dataclasses:**
   - Delete custom `OptimizationReport` → Use base format
   - Estimated: 80-100 lines removed

2. **Migrate Configuration:**
   - Replace custom config with `OptimizerConfig`
   - Update all references
   - Estimated: 120-150 lines removed

3. **Migrate Session Management:**
   - Use `OptimizationContext`
   - Remove custom tracking
   - Estimated: 80-100 lines removed

4. **Integrate Metrics:**
   - Use base metrics collection
   - Remove duplicate code
   - Estimated: 80-100 lines removed

5. **Update CLI Wrapper:**
   - Update `cli_wrapper.py` to use `GraphRAGOptimizer`
   - Maintain backward compatibility
   - Estimated: 40-80 lines modified

6. **Update __init__.py:**
   - Export `GraphRAGOptimizer`
   - Add deprecation warnings

**Expected Elimination:** 300-400 lines

---

### Day 10: Testing and Validation

**Goal:** Ensure all functionality works correctly

**Tasks:**

1. **Create Migration Tests:**
   - Test `GraphRAGOptimizer` initialization
   - Test all abstract methods
   - Test `run_session()` workflow
   - Test backward compatibility

2. **Update Existing Tests:**
   - Adapt tests to new interface
   - Ensure all tests pass
   - Verify no regressions

3. **CLI Testing:**
   - Test all CLI commands
   - Verify generate/optimize/validate/query commands
   - Test status command

4. **Documentation:**
   - Update README.md
   - Document migration changes
   - Update usage examples

**Expected Total Elimination:** 700-1,000 lines

---

## Week 3: Integration and Cleanup

### Day 11-12: Cross-Optimizer Integration

**Goal:** Unify patterns across all optimizers

**Tasks:**

1. **Standardize Error Handling:**
   - Use common error classes
   - Consistent error messages
   - Proper exception hierarchy

2. **Unify Metrics Collection:**
   - Use performance monitor for all optimizers
   - Common metric naming
   - Consistent tracking patterns

3. **Share Performance Utilities:**
   - Apply LLMCache to logic and graphrag optimizers
   - Apply ParallelValidator where applicable
   - Share BatchFileProcessor

4. **Update Unified CLI:**
   - Ensure CLI works with all base optimizers
   - Consistent command structure
   - Unified help text

**Expected Elimination:** 100-150 lines

---

### Day 13-14: Testing and Benchmarking

**Goal:** Comprehensive testing and validation

**Tasks:**

1. **Full Test Suite:**
   - Run all optimizer tests
   - Run integration tests
   - Run end-to-end tests

2. **Performance Benchmarking:**
   - Benchmark logic optimizer
   - Benchmark graphrag optimizer
   - Compare before/after performance
   - Verify no regressions

3. **Backward Compatibility:**
   - Test all legacy interfaces
   - Verify deprecation warnings work
   - Ensure smooth migration path

4. **Integration Testing:**
   - Test CLI with all optimizer types
   - Test performance monitoring
   - Test cross-optimizer workflows

**Success Criteria:**
- All tests passing ✅
- No performance regressions ✅
- Backward compatibility maintained ✅
- 1,500-2,000 lines eliminated ✅

---

### Day 15: Documentation and Final Cleanup

**Goal:** Complete documentation and final polish

**Tasks:**

1. **Update Documentation:**
   - Update SELECTION_GUIDE.md with base layer info
   - Update CLI_GUIDE.md with unified patterns
   - Create MIGRATION_GUIDE.md for users
   - Update architectural diagrams

2. **Code Review:**
   - Review all changes
   - Ensure code quality
   - Check for remaining duplicates

3. **Final Cleanup:**
   - Remove commented-out code
   - Clean up imports
   - Standardize formatting
   - Update TODOs

4. **Create Summary Report:**
   - Document lines eliminated
   - Show before/after metrics
   - Highlight improvements

**Expected Final Elimination:** 100-150 lines

---

## Expected Results

### Quantitative Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **Code Duplication** | 40-50% | <10% | -80%+ |
| **Lines Eliminated** | 0 | 1,500-2,000 | Target |
| **Logic Optimizer** | 800-1,000 dupl. | Unified | -100% |
| **GraphRAG** | 700-1,000 dupl. | Unified | -100% |
| **Config Files** | 3 separate | 1 shared | -67% |
| **Metrics Systems** | 3 separate | 1 shared | -67% |

### Qualitative Improvements

**Maintainability:**
- ✅ Single source of truth for optimization patterns
- ✅ Consistent configuration across optimizers
- ✅ Easier to add new optimizer types
- ✅ Shared bug fixes benefit all optimizers

**Performance:**
- ✅ All optimizers can use LLMCache (70-90% API reduction)
- ✅ All optimizers can use ParallelValidator (40-60% speedup)
- ✅ Shared performance monitoring
- ✅ Consistent optimization strategies

**Developer Experience:**
- ✅ Consistent API across all optimizers
- ✅ Better documentation and examples
- ✅ Easier testing with shared fixtures
- ✅ Clear migration path for users

---

## Risk Mitigation

### Potential Risks

1. **Breaking Changes:**
   - **Mitigation:** Maintain backward compatibility layers
   - **Testing:** Comprehensive compatibility tests
   - **Documentation:** Clear migration guide

2. **Performance Regression:**
   - **Mitigation:** Benchmark before and after
   - **Testing:** Performance tests in CI/CD
   - **Rollback:** Keep old implementations temporarily

3. **Test Failures:**
   - **Mitigation:** Incremental changes with testing
   - **Strategy:** Fix tests alongside migration
   - **Validation:** Run full suite frequently

4. **User Confusion:**
   - **Mitigation:** Clear documentation
   - **Strategy:** Deprecation warnings with guidance
   - **Support:** Migration examples and guides

---

## Success Criteria

### Must Have ✅
- [ ] All tests passing
- [ ] 1,500-2,000 lines eliminated
- [ ] Backward compatibility maintained
- [ ] No performance regressions
- [ ] Documentation updated

### Should Have ✅
- [ ] <10% code duplication
- [ ] Unified configuration
- [ ] Shared performance utilities
- [ ] Migration guide created
- [ ] Examples updated

### Nice to Have ✅
- [ ] Performance improvements
- [ ] Better error messages
- [ ] Enhanced CLI help
- [ ] Additional tests
- [ ] Architectural diagrams

---

## Timeline Summary

```
Week 1: Logic Theorem Optimizer
├─ Day 1-2: Create unified wrapper (300-400 lines new)
├─ Day 3-4: Remove duplicates (400-500 lines deleted)
└─ Day 5: Testing and validation
   Target: 800-1,000 lines eliminated

Week 2: GraphRAG Optimizer
├─ Day 6-7: Create unified wrapper (250-350 lines new)
├─ Day 8-9: Remove duplicates (300-400 lines deleted)
└─ Day 10: Testing and validation
   Target: 700-1,000 lines eliminated

Week 3: Integration & Cleanup
├─ Day 11-12: Cross-optimizer integration (100-150 lines deleted)
├─ Day 13-14: Testing and benchmarking
└─ Day 15: Documentation and cleanup (100-150 lines deleted)
   Target: Total 1,500-2,000 lines eliminated
```

---

## Next Steps

1. **Immediate:** Begin Day 1-2 implementation
2. **Create:** `logic_theorem_optimizer/unified_optimizer.py`
3. **Implement:** `LogicTheoremOptimizer(BaseOptimizer)`
4. **Test:** Initial functionality
5. **Document:** Progress and challenges

---

**Status:** 📋 Planning Complete - Ready for Implementation
**Estimated Effort:** 3 weeks (15 days)
**Expected Impact:** High (eliminate 1,500-2,000 lines, reduce duplication 80%+)
**Risk Level:** Medium (mitigated with backward compatibility and testing)

🚀 **Ready to begin Week 1 implementation!**

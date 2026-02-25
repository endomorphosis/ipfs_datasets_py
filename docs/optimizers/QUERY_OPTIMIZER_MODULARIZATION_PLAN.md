# Query Optimizer Modularization Plan

**Status**: In Progress  
**Last Updated**: 2026-02-24  
**Target Completion**: 9-14 hours  
**Target Files**: Extract 4 modules from `graphrag/query_unified_optimizer.py` (2,307 lines, 44 methods)

## Overview

The `UnifiedGraphRAGQueryOptimizer` class in `query_unified_optimizer.py` has grown to 2,307 lines across 44 methods, creating maintenance and testability challenges. This plan extracts cohesive modules while maintaining full backward compatibility through a unified orchestration layer.

## Current Code Inventory

**Unified optimizer file**: `ipfs_datasets_py/optimizers/graphrag/query_unified_optimizer.py`
- Total lines: 2,307
- Total methods: 44
- Main class: `UnifiedGraphRAGQueryOptimizer`

### Method Breakdown by Category

#### Visualization Methods (7 methods → `query_visualization.py`)
- `visualize_metrics_dashboard()`
- `visualize_performance_comparison()`
- `visualize_query_patterns()`
- `visualize_query_plan()`
- `visualize_resource_usage()`
- Import/setup for matplotlib/networkx
- Helper rendering methods (private)

#### Detection Methods (8 methods → `query_detection.py`)
- `detect_graph_type()` - Main public detection entry point
- `_create_fast_detection_signature()` - Fingerprinting helper
- `_detect_by_heuristics()` - Heuristic-based type detection
- `_detect_fact_verification_query()` - Specialized query pattern detection
- `_detect_exploratory_query()` - Specialized query pattern detection
- `_detect_entity_types()` - Entity type extraction from query text
- `_estimate_query_complexity()` - Complexity scoring
- Cache key generation for detection (`_get_graph_type_cache_key()`)

#### Traversal/Optimization Methods (8 methods → `traversal_optimizer.py`)
- `optimize_wikipedia_traversal()` - Wikipedia graph traversal strategy
- `optimize_ipld_traversal()` - IPLD graph traversal strategy
- `optimize_traversal_path()` - Unified traversal orchestration
- `_optimize_wikipedia_fact_verification()` - Fact verification specialization
- `calculate_entity_importance()` - Entity scoring for traversal
- `update_relation_usefulness()` - Relationship weight learning
- Helper methods for Wikipedia/IPLD-specific optimizations

#### Learning State Methods (6 methods → `learning_state.py`)
- `enable_statistical_learning()` - Learning mode toggle
- `_apply_learning_hook()` - Hook invocation for learned insights
- `_check_learning_cycle()` - Cycle tracking
- `save_learning_state()` - Persistence to disk
- `load_learning_state()` - Restoration from disk
- `_compute_query_fingerprint()` and `_create_query_fingerprint_signature()` - Query hashing for learning
- `_increment_failure_counter()` - Failure tracking

#### Core Orchestration Methods (Remain in `query_unified_optimizer.py`)
- `optimize_query()` - Main entry point
- `execute_query_with_caching()` - Query execution with caching
- `get_execution_plan()` - Plan retrieval
- `get_optimization_stats()` - Statistics aggregation
- `export_metrics_to_csv()` - Metrics export
- `_setup_specific_optimizers()` - Initialization
- `_validate_query_parameters()` - Validation
- `_create_fallback_plan()` - Fallback handling
- `record_path_performance()` - Performance recording

## Extraction Phases

### Phase 1: Visualization Module Extraction
**Files to create**:
- `query_visualization.py` (450-500 lines)

**Scope**:
1. Extract all matplotlib/networkx visualization code
2. Create `QueryVisualizationHelper` class with static methods
3. Move imports and TYPE_CHECKING guards
4. Keep optional matplotlib handling (graceful degradation)

**Steps**:
1. Create new file with matplotlib imports guarded
2. Move visualization methods + helpers
3. Add `@classmethod` decorators for unified optimizer to call
4. Add type contract for visualization results
5. Create unit test: `test_query_visualization.py`
6. Verify matplotlib availability graceful fallback
7. Update main optimizer to import and delegate

**Tests to create**: `tests/unit/optimizers/graphrag/test_query_visualization.py`
- Behavior tests (call site verification)
- Graceful fallback when matplotlib unavailable
- Matplotlib available integration tests

### Phase 2: Detection Module Extraction
**Files to create**:
- `query_detection.py` (500-600 lines)

**Scope**:
1. Extract graph type detection logic
2. Create `QueryDetector` class with class methods
3. Move fingerprinting and heuristic inference
4. Move entity type extraction
5. Keep caching integration

**Steps**:
1. Create new file
2. Move graph type detection methods
3. Move entity type inference logic
4. Move complexity estimation
5. Export cache-key generation helpers
6. Add contract for detection results (typed return)
7. Create unit test: `test_query_detection.py`
8. Add complex query test cases
9. Update main optimizer to use detector

**Tests to create**: `tests/unit/optimizers/graphrag/test_query_detection.py`
- Fact verification pattern detection
- Exploratory query detection
- Heuristic fallback coverage
- Caching behavior verification
- Entity type extraction with multilingual queries

### Phase 3: Traversal Optimization Module Extraction
**Files to create**:
- `traversal_optimizer.py` (600-700 lines)

**Scope**:
1. Extract Wikipedia traversal strategy
2. Extract IPLD traversal strategy
3. Move entity importance calculation
4. Move relationship learning
5. Move fact verification specialization

**Steps**:
1. Create new file
2. Move Wikipedia optimization methods
3. Move IPLD optimization methods
4. Move entity/relationship scoring
5. Create `TraversalOptimizer` class
6. Add dependency injection for graph_processor
7. Create unit test: `test_traversal_optimization.py`
8. Add entity importance edge cases
9. Update main optimizer to use traversal module

**Tests to create**: `tests/unit/optimizers/graphrag/test_traversal_optimization.py`
- Wikipedia traversal optimization verification
- IPLD traversal optimization verification
- Entity importance scoring correctness
- Fact verification path specialization
- Relationship weighting updates

### Phase 4: Learning State Module Extraction
**Files to create**:
- `learning_state.py` (300-400 lines)

**Scope**:
1. Extract learning mode management
2. Extract state persistence (save/load)
3. Move query fingerprinting
4. Move failure tracking
5. Move learning hooks

**Steps**:
1. Create new file
2. Move learning state class (if not already exists)
3. Move learning statistics tracking
4. Move save/load persistence logic
5. Move fingerprinting helpers
6. Create `LearningStateManager` class
7. Add typed error handling for state ops
8. Create unit test: `test_learning_state.py`
9. Add roundtrip serialization tests
10. Update main optimizer to use learning module

**Tests to create**: `tests/unit/optimizers/graphrag/test_learning_state.py`
- Learning state enable/disable
- Save/load roundtrip verification
- Query fingerprint collision detection
- Failure counter tracking
- Learning hook invocation
- Persistence error handling

### Phase 5: Integration and Compatibility Testing
**Goals**:
1. Verify all module extraction complete
2. Behavior parity tests (unified optimizer still works)
3. Performance regression tests
4. Public API compatibility verification

**Steps**:
1. Create integration test: `test_query_optimizer_modularization_parity.py`
   - Test that `optimize_query()` still works end-to-end
   - Verify all optimization paths functional
   - Check performance against baseline
   - Verify backward compatibility
2. Run full test suite on modified unified optimizer
3. Run old test suite: `test_query_unified_optimizer_integration.py`
4. Verify no test failures from extraction
5. Document any behavior changes

**Tests to create**: `tests/unit/optimizers/graphrag/test_query_optimizer_modularization_parity.py`
- Core optimization path still works
- All graph types still detectable
- Traversal strategies still applied
- Learning still records and restores
- Visualization still available when matplotlib present
- Performance baseline preserved (±5% latency)

## Backward Compatibility Strategy

### Public API
- `UnifiedGraphRAGQueryOptimizer` remains the single entry point
- All public methods `optimize_query()`, `detect_graph_type()`, etc. kept
- Optional internal use of module classes (not public contract change)

### Internal Imports
- Existing code importing `UnifiedGraphRAGQueryOptimizer` unchanged
- New modules available for advanced use, but optional
- No breaking changes to constructor or method signatures

### Fallback Handling
- Visual metrics gracefully degrade if matplotlib unavailable
- Learning state gracefully handles missing disk access
- Detection methods have heuristic fallbacks

## File Structure After Extraction

```
ipfs_datasets_py/optimizers/graphrag/
├── query_unified_optimizer.py          (reduced to ~500 lines, orchestration only)
├── query_visualization.py              (new, ~500 lines)
├── query_detection.py                  (new, ~500 lines)
├── traversal_optimizer.py              (new, ~600 lines)
└── learning_state.py                   (new, ~300 lines)

tests/unit/optimizers/graphrag/
├── test_query_unified_optimizer_integration.py  (existing, updated imports)
├── test_query_visualization.py         (new)
├── test_query_detection.py             (new)
├── test_traversal_optimization.py      (new)
├── test_learning_state.py              (new)
└── test_query_optimizer_modularization_parity.py (new, integration)
```

## Success Criteria

✅ **Extraction Complete**
- All visualization code in `query_visualization.py`
- All detection code in `query_detection.py`
- All traversal code in `traversal_optimizer.py`
- All learning state code in `learning_state.py`

✅ **Tests Passing**
- All new module tests: `test_query_visualization.py`, etc. (100% pass)
- Parity tests: `test_query_optimizer_modularization_parity.py` (100% pass)
- Existing tests: `test_query_unified_optimizer_integration.py` (100% pass)
- No regressions from current test baseline

✅ **Backward Compatibility**
- Public API unchanged (no signature changes)
- Constructor arguments unchanged
- Return types unchanged
- Existing integrations continue to work

✅ **Performance**
- Latency within ±5% of baseline
- No memory regression
- No import time overhead

## Time Estimate

- Phase 1 (Visualization): 1-2 hours
- Phase 2 (Detection): 2-3 hours
- Phase 3 (Traversal): 2-3 hours
- Phase 4 (Learning State): 1-2 hours
- Phase 5 (Integration): 2-3 hours
- **Total**: 8-13 hours (target 9-14 hours)

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Silent behavior change during extraction | Create parity tests before extraction; run tests after each phase |
| Import cycles between modules | Keep unified optimizer as single entry point; modules have no inter-dependencies |
| Performance regression | Benchmark optimize_query() latency before and after; accept ±5% variance |
| Complex state dependencies | Document state flow in each module; verify in integration tests |
| Matplotlib/dependency issues | Keep graceful fallback strategy; test with and without optional deps |

## Progress Tracking

- [x] Create comprehensive modularization plan
- [ ] Phase 1: Extract visualization module
- [ ] Phase 2: Extract detection module
- [ ] Phase 3: Extract traversal optimization module
- [ ] Phase 4: Extract learning state module
- [ ] Phase 5: Complete integration testing and parity verification
- [ ] Commit all changes with clear messages per phase
- [ ] Update documentation with module cross-references

---

**Next Step**: Begin Phase 1 (Visualization extraction) immediately after plan approval.

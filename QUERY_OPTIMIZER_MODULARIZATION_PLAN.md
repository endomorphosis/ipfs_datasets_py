# Query Unified Optimizer Modularization Plan

## Current State
- Single file: `query_unified_optimizer.py` (2,114 lines)
- Single class: `UnifiedGraphRAGQueryOptimizer` with 30+ methods
- Mixing concerns: query planning, traversal, visualization, serialization, detection

## Target Modules

### 1. Query Visualization Module (`query_visualization.py`)
**Lines:** 1911-2100 (~190 lines)
**Methods to extract:**
- `visualize_query_plan()`
- `visualize_metrics_dashboard()`
- `visualize_performance_comparison()`
- `visualize_resource_usage()`
- `visualize_query_patterns()`
- `export_metrics_to_csv()`

**Dependencies:**
- matplotlib (optional)
- pandas (optional)
- Internal: metrics dict, query history

**Implementation approach:**
- Create `QueryVisualization` helper class
- Take metrics/history as constructor params
- Keep methods API-compatible with current signatures

### 2. Query Detection Module (`query_detection.py`)
**Lines:** 1048-1286 (~238 lines)
**Methods to extract:**
- `_detect_fact_verification_query()`
- `_detect_exploratory_query()`
- `_detect_entity_types()`
- `_estimate_query_complexity()`
- `detect_graph_type()` (line 366)

**Dependencies:**
- re module
- Internal: query dict structure

**Implementation approach:**
- Create `QueryDetector` class
- Static/class methods where possible
- Clear input/output contracts (query dict → detection results)

### 3. Traversal Optimization Module (`traversal_optimizer.py`)
**Lines:** 464-980 (~516 lines)
**Methods to extract:**
- `optimize_wikipedia_traversal()`
- `optimize_ipld_traversal()`
- `optimize_traversal_path()`
- `_optimize_wikipedia_fact_verification()`

**Dependencies:**
- Entity importance calculation
- Graph processor interface

**Implementation approach:**
- Create `TraversalOptimizer` class
- Inject entity scorer as dependency
- Return optimized traversal dicts

### 4. Learning State Serialization Module (`learning_state.py`)
**Lines:** 1642-1780 (~138 lines)
**Methods to extract:**
- `save_learning_state()`
- `load_learning_state()`
- `record_path_performance()`

**Dependencies:**
- json module
- pathlib
- Internal: learning state dict structure

**Implementation approach:**
- Create `LearningStateManager` class
- Handle file I/O and state dict transformations
- Keep existing filepath fallback logic

### 5. Remaining Core (`query_unified_optimizer.py`)
**Remains:** ~1,032 lines
**Core responsibilities:**
- `__init__()` - setup and integration
- `_validate_query_parameters()` - input validation
- `_create_fallback_plan()` - error handling
- `optimize_query()` - main orchestration
- `get_execution_plan()` - plan generation
- `_apply_learning_hook()` - learning trigger
- `update_relation_usefulness()` - learning update
- `enable_statistical_learning()` - configuration
- `_check_learning_cycle()` - learning cycle check
- `_increment_failure_counter()` - metrics
- `execute_query_with_caching()` - caching layer

## Migration Strategy

### Phase 1: Extract Visualization (Low Risk)
1. Create `query_visualization.py` with `QueryVisualization` class
2. Add tests for visualization methods
3. Update `UnifiedGraphRAGQueryOptimizer` to delegate to `QueryVisualization`
4. Verify existing tests pass

### Phase 2: Extract Detection (Medium Risk)
1. Create `query_detection.py` with `QueryDetector` class
2. Add comprehensive tests for detection logic
3. Update optimizer to use `QueryDetector`
4. Verify detection behavior unchanged

### Phase 3: Extract Traversal (High Risk - Complex Dependencies)
1. Create `traversal_optimizer.py` with `TraversalOptimizer` class
2. Add integration tests with mock graph processors
3. Update optimizer to delegate traversal optimization
4. Verify traversal quality unchanged

### Phase 4: Extract Learning State (Medium Risk)
1. Create `learning_state.py` with `LearningStateManager` class
2. Add serialization round-trip tests
3. Update optimizer to use `LearningStateManager`
4. Verify state persistence works

### Phase 5: Integration and Cleanup
1. Run full test suite
2. Update imports in dependent modules
3. Update documentation
4. Deprecation notice for direct method access (if breaking)

## Success Criteria
- ✅ All existing tests pass without modification
- ✅ Each new module has >90% test coverage
- ✅ Main optimizer file <1500 lines
- ✅ Clear separation of concerns
- ✅ No performance regression
- ✅ Backwards compatibility maintained

## Rollback Plan
- Keep original file as `query_unified_optimizer_legacy.py`
- Feature flag: `USE_MODULAR_QUERY_OPTIMIZER` (default True)
- Can switch back if issues discovered

## Timeline
- Phase 1 (Visualization): 1-2 hours
- Phase 2 (Detection): 2-3 hours
- Phase 3 (Traversal): 3-4 hours
- Phase 4 (Learning State): 2-3 hours
- Phase 5 (Integration): 1-2 hours
- **Total estimate:** 9-14 hours

## Notes
- Start with visualization (lowest risk, minimal dependencies)
- Each phase should be independently testable
- Keep method signatures identical where possible for backwards compat
- Add deprecation warnings for any breaking changes

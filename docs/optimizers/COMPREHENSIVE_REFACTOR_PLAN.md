# Comprehensive Optimizer Module Refactoring Plan

**Created**: 2026-02-24  
**Status**: ACTIVE - Infinite Improvement Cycle  
**Repository**: ipfs_datasets_py/optimizers

## Executive Summary

This document describes the comprehensive refactoring and improvement plan for the optimizers module. The plan is designed as an "infinite todo list" - a living backlog that continuously evolves as work is completed and new improvements are identified.

## Core Philosophy

- **Correctness First**: All changes must preserve or improve existing functionality
- **Type Safety**: Progressive enhancement of type annotations and runtime checks
- **Performance**: Continuous performance monitoring and optimization
- **Observability**: Rich logging, metrics, and tracing throughout
- **Documentation**: Keep docs synchronized with code evolution

## Current State Analysis

### Module Structure
```
optimizers/
├── common/          # Shared abstractions and utilities
├── graphrag/        # Graph RAG optimizations (69 files)
├── logic_theorem_optimizer/  # Theorem proving integration
├── agentic/         # Autonomous optimizer workflows
├── api/             # REST API and service layer
├── tests/           # Comprehensive test suite
└── docs/            # Module documentation
```

### Key Metrics (as of 2026-02-24)
- **Total Lines**: ~50,000+ across all modules
- **Test Coverage**: High (growing with each improvement)
- **Type Annotations**: ~85% (improving)
- **Exception Handling**: ~98% typed (1 remaining broad catch)
- **Documentation**: Comprehensive, actively maintained

## Priority Levels

- **P0**: Critical correctness, security, or data-loss bugs
- **P1**: Architecture debt blocking multiple features
- **P2**: Quality, performance, observability improvements
- **P3**: Nice-to-have enhancements and polish

## Track Definitions

1. **[arch]**: Architecture and modularization
2. **[api]**: Public API and typing contracts
3. **[graphrag]**: Ontology/query pipeline improvements
4. **[logic]**: Theorem/prover pipeline
5. **[agentic]**: Autonomous optimizer workflows
6. **[tests]**: Test quality and coverage
7. **[perf]**: Performance profiling and optimization
8. **[obs]**: Logging, metrics, tracing
9. **[docs]**: Documentation and onboarding
10. **[security]**: Safety and hardening

## Strategic Improvement Roadmap

### Phase 1: Architecture Cleanup (P1)
**Goal**: Reduce technical debt, improve maintainability

#### 1.1 Query Optimizer Modularization
- **Status**: NOT STARTED
- **Priority**: P1
- **Estimated Effort**: 3-4 days
- **Description**: Split 422-line query_optimizer.py into focused modules
- **Modules to Extract**:
  - `query_planner.py` - Query planning logic
  - `traversal_heuristics.py` - Graph traversal strategies
  - `learning_adapter.py` - Already exists, consolidate remaining logic
  - `serialization.py` - Query serialization helpers
- **Testing Strategy**: Parity tests before/after split
- **Success Criteria**: All existing tests pass, no behavior changes

#### 1.2 Exception Handling Completion
- **Status**: 98% COMPLETE
- **Priority**: P1
- **Remaining**: 1 broad catch in query_unified_optimizer.py:1473
- **Action**: Replace with typed exception groups
- **Testing**: Verify base exceptions propagate correctly

#### 1.3 Type Safety Enhancement
- **Status**: IN PROGRESS
- **Priority**: P1
- **Actions**:
  - Add `py.typed` marker (DONE)
  - Run strict mypy audit on public surface
  - Add Protocol definitions for duck-typed interfaces
  - Convert Dict[str, Any] to typed dataclasses
- **Target**: 95%+ type coverage

### Phase 2: API Standardization (P1-P2)

#### 2.1 Eliminate **kwargs Sprawl
- **Status**: IN PROGRESS
- **Target**: agentic/ module
- **Pattern**: Replace variadic kwargs with Optional[Dict] or typed parameters
- **Completion**: Estimated 60% done

#### 2.2 Fixture Factory Migration
- **Status**: NOT STARTED
- **Goal**: Centralize test fixture creation
- **Action**: Move all ontology mock builders to conftest.py
- **Benefit**: Reduce test duplication, improve maintainability

#### 2.3 Return Type Consistency
- **Status**: PARTIAL
- **Goal**: No ambiguous raw dicts in public methods
- **Action**: Define typed return classes for all public APIs
- **Example**: Replace Dict[str, Any] with OptimizerResult dataclass

### Phase 3: GraphRAG Quality Enhancements (P2)

#### 3.1 Semantic Deduplication
- **Status**: NOT STARTED
- **Priority**: P2
- **Description**: Add embedding-based entity deduplication
- **Feature Flag**: ENABLE_SEMANTIC_DEDUP
- **Benchmark**: Measure quality delta vs heuristic dedup

#### 3.2 Distributed Refinement
- **Status**: NOT STARTED
- **Priority**: P2
- **Description**: Implement split-merge parallelism for ontology refinement
- **Architecture**: Master-worker pattern with result merging
- **Scaling Target**: Handle 10k+ entity ontologies

#### 3.3 Multilingual Support Enhancement
- **Status**: COMPLETE (2026-02-24)
- **Remaining**: Expand language coverage, benchmark quality

#### 3.4 Relationship Inference
- **Status**: COMPLETE (2026-02-24)
- **Remaining**: Benchmark LLM vs heuristic quality

### Phase 4: Performance & Scale (P2-P3)

#### 4.1 Benchmark Suite
- **Status**: IN PROGRESS
- **Coverage**: Sentence window scaling (DONE)
- **Remaining**:
  - 10k-token extraction baseline
  - Query optimizer load testing
  - Critic consistency evaluation scaling
  - Logic validator performance on large ontologies

#### 4.2 Caching Strategy
- **Status**: PARTIAL
- **Existing**: Query validation cache keys
- **Additions Needed**:
  - Logic validation/prover result cache
  - Ontology evaluation cache
  - Cross-instance shared caches

#### 4.3 Parallel Batch Processing
- **Status**: NOT STARTED
- **Goal**: Parallelize embarrassingly parallel operations
- **Constraint**: Preserve deterministic ordering where required

### Phase 5: Observability (P2-P3)

#### 5.1 Structured Logging
- **Status**: PARTIAL
- **Goal**: Standardize JSON log schema across all pipelines
- **Format**: OpenTelemetry-compatible structured events
- **Integration**: Loki, ELK, Splunk

#### 5.2 Metrics Enhancement
- **Status**: IN PROGRESS
- **Recent Additions**: Score deltas, stage timings, validation failures
- **Remaining**: Resource utilization, cache hit rates, error categorization

#### 5.3 Distributed Tracing
- **Status**: PARTIAL (OTEL_ENABLED flag added)
- **Coverage**: Pipeline and session boundaries
- **Expansion**: Add spans for expensive operations

#### 5.4 Alerting & Dashboards
- **Status**: COMPLETE
- **Docs**: Prometheus rules, Loki queries, troubleshooting playbooks
- **Remaining**: Add more alert examples for edge cases

### Phase 6: Testing Strategy (P1-P2)

#### 6.1 Parity Tests
- **Status**: NOT STARTED
- **Blocker**: Waiting on query optimizer split
- **Goal**: Ensure refactoring doesn't change behavior

#### 6.2 Property-Based Testing
- **Status**: PARTIAL
- **Coverage**: Entity round-trips, confidence bounds
- **Expansion**: Ontology stats invariants, config constraints

#### 6.3 Regression Corpus
- **Status**: COMPLETE
- **Coverage**: Mixed-domain extraction with frozen invariants
- **Maintenance**: Update corpus as capabilities improve

#### 6.4 Mutation Testing
- **Status**: NOT STARTED
- **Target**: Critic dimension evaluators
- **Tool**: mutpy or cosmic-ray
- **Goal**: Find untested code paths

### Phase 7: Documentation (P2-P3)

#### 7.1 Architecture Diagrams
- **Status**: COMPLETE
- **Files**: Optimization loop, unified architecture
- **Remaining**: Component interaction diagrams

#### 7.2 API Documentation
- **Status**: PARTIAL
- **Goal**: Auto-generate API docs with Sphinx/MkDocs
- **Requirements**: Good docstrings (mostly done)

#### 7.3 Quick References
- **Status**: PARTIAL
- **Needed**: One-page guides for GraphRAG, logic, agentic
- **Format**: Cheat sheets with common patterns

#### 7.4 How-To Guides
- **Status**: COMPLETE
- **Examples**: "How to add a new optimizer" guide
- **Remaining**: More domain-specific guides

### Phase 8: Security & Reliability (P1-P2)

#### 8.1 Path Traversal Protection
- **Status**: COMPLETE
- **Coverage**: CLI file inputs validated with _safe_resolve()
- **Testing**: Command-level security tests

#### 8.2 External Call Hardening
- **Status**: PARTIAL
- **Remaining**: Add timeout + retry + circuit-breaker for all backend calls
- **Pattern**: Consistent error handling with exponential backoff

#### 8.3 Credential Redaction
- **Status**: NOT STARTED
- **Goal**: Ensure no tokens/credentials in logs
- **Action**: Audit all logging statements

#### 8.4 Prover Sandboxing
- **Status**: DESIGN COMPLETE
- **Docs**: SANDBOXED_PROVER_POLICY.md
- **Remaining**: Implementation

## Execution Strategy

### Working Model: Dual-Lane Approach

Every improvement cycle has two parallel lanes:

1. **Strategic Lane**: One P0/P1/P2 item aligned to roadmap
2. **Random Lane**: One P2/P3 item from a different track

### Work-in-Progress Limits
- Max 1 in-progress item per lane
- Max 5 active random picks total
- Complete one item fully before starting next

### Completion Criteria
- Code implemented with lint/type checks passing
- Unit/integration tests added or updated
- Public behavior documented
- TODO entry updated with completion note

### Cycle Cadence
1. **Start of Cycle**: Confirm 1 strategic + 1 random item
2. **During Cycle**: Deliver in small batches with tests
3. **End of Cycle**: Update TODO, refill random queue

## Current Sprint (2026-02-24)

### Active Items

#### Strategic Lane
- [ ] (P1) Split query_optimizer.py into focused modules
  - Status: Analysis complete, ready to execute
  - Blocker: None
  - Next Step: Extract QueryPlanner class

#### Random Lane  
- [ ] (P2) Complete final exception handling cleanup
  - Status: 1 remaining broad catch identified
  - Location: query_unified_optimizer.py:1473
  - Next Step: Replace with typed exceptions

### Next 5 Random Picks (Queue)
1. (P2) [tests] Parity tests for query optimizer split
2. (P3) [perf] Benchmark query optimizer under load
3. (P2) [api] Audit and fix remaining **kwargs in agentic/
4. (P3) [docs] Add per-method doctest examples
5. (P2) [arch] Consolidate optimizer lifecycle hooks

## Long-Term Vision

### Year 1 Goals (2026)
- Complete all P1 items
- 95%+ type coverage
- Comprehensive benchmark suite
- Auto-generated API documentation
- Production-ready distributed refinement

### Year 2 Goals (2027)
- Real-time optimization capabilities
- Multi-tenant optimization service
- ML-based optimization strategy selection
- Advanced caching with Redis/Memcached
- Full OpenTelemetry integration

## Metrics & KPIs

### Code Quality
- Type coverage: 85% → 95%
- Test coverage: High → Higher with mutation testing
- Exception handling: 98% → 100% typed
- Documentation: Good → Excellent with auto-generation

### Performance
- 10k-token extraction: Baseline → 2x improvement
- Query optimization overhead: <5ms p99
- Cache hit rate: >80% for frequent queries
- Parallel efficiency: >90% for batch operations

### Developer Experience
- Time to add new optimizer: 2 days → 4 hours
- Onboarding time: 1 week → 2 days
- Debug time for typical issue: 2 hours → 30 minutes

## Risk Management

### Technical Risks
1. **Refactoring breaks existing consumers**
   - Mitigation: Parity tests, careful versioning
2. **Performance regressions**
   - Mitigation: Benchmark suite, automated perf testing
3. **Type system limitations**
   - Mitigation: Gradual typing, runtime checks where needed

### Process Risks
1. **Infinite backlog becomes unfocused**
   - Mitigation: Strict prioritization, WIP limits
2. **Documentation drift**
   - Mitigation: Recurring audit tasks each cycle
3. **Test maintenance burden**
   - Mitigation: Fixture factories, property-based tests

## Success Criteria

A refactoring cycle is successful when:
1. All tests pass (existing + new)
2. No performance regressions
3. Type coverage maintained or improved
4. Documentation updated
5. TODO file reflects actual state

## Appendix: Important Files

### Core Modules
- `graphrag/query_optimizer.py` - Main query optimization (422 lines)
- `graphrag/query_unified_optimizer.py` - Unified strategy selector
- `graphrag/ontology_generator.py` - Entity extraction
- `graphrag/ontology_critic.py` - Quality evaluation
- `graphrag/ontology_mediator.py` - Refinement orchestration

### Infrastructure
- `common/base_optimizer.py` - Base class for all optimizers
- `common/query_validation.py` - Query validation mixins
- `common/caching_layer.py` - Shared caching infrastructure

### Testing
- `tests/unit/` - Unit tests
- `tests/integration/` - Integration tests
- `benchmarks/` - Performance benchmarks

### Documentation
- `TODO.md` - Living backlog (infinite list)
- `README.md` - Module overview
- `docs/` - Detailed documentation

---

**Last Updated**: 2026-02-24  
**Next Review**: After each strategic item completion  
**Maintainer**: Copilot + Human oversight

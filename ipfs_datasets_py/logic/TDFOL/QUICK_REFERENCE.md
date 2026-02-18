# TDFOL Refactoring - Quick Reference Guide

**Quick Links:**
- 📖 [Full Plan](./COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md) - Complete technical details
- 📋 [Executive Summary](./REFACTORING_EXECUTIVE_SUMMARY.md) - High-level overview
- 📚 [Current README](./README.md) - Module documentation
- 📊 [This Document] - Quick reference and checklists

---

## 🎯 Project Goals

Transform TDFOL from foundational implementation to production-ready neurosymbolic reasoning system by addressing 6 critical gaps:

1. ❌ → ✅ **Natural Language:** Add NL → TDFOL parsing (20+ patterns, 85% accuracy)
2. ❌ → ✅ **Complete Prover:** Expand to 50+ rules + modal tableaux (K, T, D, S4, S5)
3. ❌ → ✅ **Optimization:** Add strategy selection + parallel search (2-5x speedup)
4. ❌ → ✅ **Testing:** Expand from 97 to 440+ tests (90% coverage)
5. ❌ → ✅ **Visualization:** Add proof trees + dependency graphs
6. ❌ → ✅ **Production:** Performance, security, complete documentation

---

## 📅 Timeline at a Glance

```
┌─────────────────────────────────────────────────┐
│          Total Duration: 16-20 weeks            │
└─────────────────────────────────────────────────┘

Phase 7  │ Week 1-4   │ Natural Language
Phase 8  │ Week 5-9   │ Complete Prover  
Phase 9  │ Week 10-13 │ Optimization
Phase 10 │ Week 14-17 │ Testing
Phase 11 │ Week 18-20 │ Visualization
Phase 12 │ Week 21-23 │ Hardening
```

---

## 📦 Phase-by-Phase Checklist

### Phase 7: Natural Language Processing ⏳ (3-4 weeks)

**Goal:** Parse natural language to TDFOL formulas

#### Week 1: Setup & Preprocessing
- [ ] Install spaCy and dependencies
- [ ] Design NL architecture
- [ ] Implement `tdfol_nl_preprocessor.py` (300 LOC)
  - [ ] Sentence splitting
  - [ ] Entity recognition
  - [ ] Dependency parsing
  - [ ] Temporal normalization
- [ ] Write 10 basic tests

#### Week 2: Pattern Matching
- [ ] Implement `tdfol_nl_patterns.py` (500 LOC)
  - [ ] 20+ deontic patterns (must, shall, may, forbidden)
  - [ ] 10+ temporal patterns (always, eventually, within)
  - [ ] 10+ universal patterns (all, every, any)
- [ ] Write 20 pattern tests

#### Week 3: Formula Generation
- [ ] Implement `tdfol_nl_generator.py` (400 LOC)
  - [ ] Pattern → Formula conversion
  - [ ] Entity substitution
  - [ ] Ambiguity handling
- [ ] Implement `tdfol_nl_context.py` (300 LOC)
  - [ ] Context tracking
  - [ ] Reference resolution
- [ ] Write 20 generation tests

#### Week 4: Integration & Testing
- [ ] Integrate with existing parser
- [ ] Add `parse_natural_language()` API
- [ ] End-to-end testing (10 tests)
- [ ] Documentation and examples
- [ ] **Milestone:** 60+ tests, 80%+ accuracy

---

### Phase 8: Complete Prover ⏳ (4-5 weeks)

**Goal:** 50+ inference rules + modal tableaux

#### Week 5: Temporal Rules
- [ ] Add 10 temporal rules to `tdfol_inference_rules.py`
  - [ ] Weak until (W)
  - [ ] Release (R)
  - [ ] Since (S)
  - [ ] Bounded temporal (□[n], ◊[n])
  - [ ] LTL equivalences
- [ ] Write 20 tests

#### Week 6: Deontic Rules
- [ ] Add 8 deontic rules
  - [ ] Contrary-to-duty obligations
  - [ ] Conditional obligations
  - [ ] Deontic detachment
  - [ ] Permission closure
  - [ ] Free choice permission
- [ ] Add 10 combined temporal-deontic rules
- [ ] Write 30 tests

#### Week 7-8: Modal Tableaux
- [ ] Implement `tdfol_modal_tableaux.py` (800 LOC)
  - [ ] Tableaux data structures
  - [ ] K logic (basic modal)
  - [ ] T logic (reflexive)
  - [ ] D logic (serial/deontic)
  - [ ] S4 logic (transitive)
  - [ ] S5 logic (Euclidean)
  - [ ] Countermodel generation
- [ ] Write 40 tests

#### Week 9: Integration
- [ ] Update `tdfol_prover.py`
- [ ] Add `use_modal_tableaux` parameter
- [ ] Add `use_advanced_rules` parameter
- [ ] End-to-end testing (20 tests)
- [ ] Documentation
- [ ] **Milestone:** 50+ rules, modal tableaux, 120+ tests

---

### Phase 9: Advanced Optimization ⏳ (3-4 weeks)

**Goal:** Strategy selection + parallel search

#### Week 10: Strategies
- [ ] Implement `tdfol_proof_strategies.py` (500 LOC)
  - [ ] Forward chaining (existing)
  - [ ] Backward chaining (new)
  - [ ] Bidirectional search (new)
  - [ ] Strategy selector
- [ ] Write 15 tests

#### Week 11: Parallel Search
- [ ] Implement `tdfol_parallel_prover.py` (600 LOC)
  - [ ] Thread pool coordinator
  - [ ] Multi-strategy execution
  - [ ] First-success termination
  - [ ] Shared cache integration
- [ ] Write 10 tests

#### Week 12: Heuristic Search
- [ ] Implement `tdfol_heuristic_search.py` (400 LOC)
  - [ ] A* search algorithm
  - [ ] Formula distance heuristic
  - [ ] Structural similarity heuristic
  - [ ] Adaptive timeout
- [ ] Write 15 tests

#### Week 13: Optimization & Benchmarking
- [ ] Performance benchmarking
- [ ] Optimization tuning
- [ ] Documentation
- [ ] **Milestone:** 4+ strategies, 2-5x speedup, 40+ tests

---

### Phase 10: Comprehensive Testing ⏳ (3-4 weeks)

**Goal:** 440+ tests with 90% coverage

#### Week 14: Core & Parser Tests
- [ ] Write 30 core tests
  - [ ] All formula types
  - [ ] Variable binding
  - [ ] Substitution
  - [ ] Edge cases
- [ ] Write 50 parser tests
  - [ ] All operators
  - [ ] Complex nesting
  - [ ] Error handling
  - [ ] Ambiguity

#### Week 15: Prover & Rule Tests
- [ ] Write 100 prover tests
  - [ ] Each inference rule (50)
  - [ ] Proof strategies (20)
  - [ ] Complex scenarios (30)
- [ ] Write 50 inference rule tests

#### Week 16: Integration Tests
- [ ] Write 60 NL parser tests (Phase 7)
- [ ] Write 30 converter tests
- [ ] Write 20 integration tests

#### Week 17: Property & Performance Tests
- [ ] Write 40 property-based tests (hypothesis)
  - [ ] Parser robustness
  - [ ] Roundtrip properties
  - [ ] Substitution properties
- [ ] Write 20 performance benchmarks
  - [ ] Parse time
  - [ ] Proof time
  - [ ] Cache speedup
  - [ ] Parallel speedup
- [ ] CI/CD integration
- [ ] **Milestone:** 440+ tests, 90% coverage

---

### Phase 11: Visualization Tools ⏳ (2-3 weeks)

**Goal:** Proof trees + dependency graphs

#### Week 18: Proof Tree Visualizer
- [ ] Implement `tdfol_visualization_proof_tree.py` (400 LOC)
  - [ ] ASCII tree rendering
  - [ ] GraphViz/DOT export
  - [ ] HTML interactive (D3.js)
- [ ] Write 10 tests

#### Week 19: Dependency & Trace Visualizers
- [ ] Implement `tdfol_visualization_dependencies.py` (300 LOC)
  - [ ] Dependency extraction
  - [ ] GraphViz visualization
  - [ ] Plotly interactive
- [ ] Implement `tdfol_visualization_inference_trace.py` (300 LOC)
  - [ ] Timeline generation
  - [ ] Rule application tracking
- [ ] Write 10 tests

#### Week 20: Integration
- [ ] Add `visualize=True` parameter to prover
- [ ] Integration testing (10 tests)
- [ ] Documentation and examples
- [ ] **Milestone:** 3 visualizers, 30+ tests

---

### Phase 12: Production Hardening ⏳ (2-3 weeks)

**Goal:** Production-ready deployment

#### Week 21: Performance & Security
- [ ] Implement profiling infrastructure
- [ ] Optimize parser (memoization, interning)
- [ ] Optimize prover (indexing, caching)
- [ ] Implement security validation (300 LOC)
  - [ ] Input validation
  - [ ] Length limits
  - [ ] Nesting depth limits
- [ ] Implement resource limits (200 LOC)
  - [ ] Max proof steps
  - [ ] Memory limits
  - [ ] Timeout enforcement

#### Week 22: Error Handling
- [ ] Define error hierarchy
  - [ ] ParseError
  - [ ] ProofError
  - [ ] TimeoutError
  - [ ] ResourceExhaustedError
- [ ] Implement safe parsing
- [ ] Add error recovery
- [ ] Comprehensive error messages

#### Week 23: Documentation
- [ ] Complete API documentation
  - [ ] All public classes
  - [ ] All public functions
  - [ ] Type hints
  - [ ] Examples
- [ ] Write user guide
  - [ ] Getting started
  - [ ] Tutorials
  - [ ] How-to guides
  - [ ] Troubleshooting
- [ ] Write developer guide
  - [ ] Architecture
  - [ ] Adding rules
  - [ ] Adding patterns
  - [ ] Testing guidelines
- [ ] **Milestone:** Production-ready, fully documented

---

## 📊 Success Metrics Dashboard

### Current State (Phases 1-6)

| Metric | Value | Target | Gap |
|--------|-------|--------|-----|
| LOC | 4,287 | ~15,787 | +11,500 |
| Tests | 97 | 440+ | +343 |
| Coverage | ~70% | 90%+ | +20% |
| NL Patterns | 0 | 20+ | +20 |
| Rules | 40 | 50+ | +10 |
| Modal Logics | 0 | 5 | +5 |
| Strategies | 1 | 4+ | +3 |
| Visualizations | 0 | 3 | +3 |

### Performance Targets

| Metric | Current | Target | Factor |
|--------|---------|--------|--------|
| Parse | 1-5ms | <3ms | 1.5x |
| Simple Proof | 10-50ms | <30ms | 1.5x |
| Complex Proof | 100-500ms | <200ms | 2.5x |
| Parallel | - | 2-5x | New |
| Cache | 100-20000x | 100x+ | Keep |

---

## 🗂️ File Structure After Completion

```
TDFOL/
├── Core (Existing - No changes)
│   ├── __init__.py (187 LOC)
│   ├── tdfol_core.py (551 LOC)
│   ├── tdfol_parser.py (564 LOC)
│   ├── tdfol_prover.py (900 LOC) ← Enhanced
│   ├── tdfol_inference_rules.py (1,500 LOC) ← Enhanced
│   ├── tdfol_proof_cache.py (92 LOC)
│   ├── tdfol_converter.py (528 LOC)
│   └── tdfol_dcec_parser.py (373 LOC)
│
├── nl/ (NEW - Phase 7)
│   ├── tdfol_nl_preprocessor.py (300 LOC)
│   ├── tdfol_nl_patterns.py (500 LOC)
│   ├── tdfol_nl_generator.py (400 LOC)
│   └── tdfol_nl_context.py (300 LOC)
│
├── prover/ (NEW - Phases 8-9)
│   ├── tdfol_modal_tableaux.py (800 LOC)
│   ├── tdfol_proof_strategies.py (500 LOC)
│   ├── tdfol_parallel_prover.py (600 LOC)
│   └── tdfol_heuristic_search.py (400 LOC)
│
├── visualization/ (NEW - Phase 11)
│   ├── tdfol_visualization_proof_tree.py (400 LOC)
│   ├── tdfol_visualization_dependencies.py (300 LOC)
│   └── tdfol_visualization_inference_trace.py (300 LOC)
│
├── security/ (NEW - Phase 12)
│   ├── validation.py (300 LOC)
│   └── resource_limits.py (200 LOC)
│
├── docs/ (NEW - Phase 12)
│   ├── USER_GUIDE.md
│   ├── DEVELOPER_GUIDE.md
│   ├── API_REFERENCE.md
│   └── TUTORIALS.md
│
└── Documentation
    ├── README.md (updated)
    ├── COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md
    ├── REFACTORING_EXECUTIVE_SUMMARY.md
    ├── QUICK_REFERENCE.md (this file)
    └── PHASEx_COMPLETE.md (x=7-12, created as completed)
```

---

## 🔧 Development Workflow

### Starting a New Phase

1. **Create Feature Branch:**
   ```bash
   git checkout -b feature/tdfol-phase-X
   ```

2. **Review Phase Plan:**
   - Read phase section in comprehensive plan
   - Review deliverables checklist
   - Understand success criteria

3. **Set Up Environment:**
   - Install dependencies
   - Create test fixtures
   - Set up profiling (if applicable)

4. **Iterative Development:**
   - Implement component
   - Write tests (TDD preferred)
   - Run tests continuously
   - Document as you go

5. **Phase Completion:**
   - Run all tests
   - Verify success criteria met
   - Create `PHASEx_COMPLETE.md`
   - Merge to main branch

### Daily Development

```bash
# Run relevant tests
pytest tests/unit_tests/logic/TDFOL/ -v

# Run specific test file
pytest tests/unit_tests/logic/TDFOL/test_tdfol_parser.py -v

# Run with coverage
pytest tests/unit_tests/logic/TDFOL/ --cov=ipfs_datasets_py.logic.TDFOL --cov-report=html

# Type checking
mypy ipfs_datasets_py/logic/TDFOL/

# Linting
flake8 ipfs_datasets_py/logic/TDFOL/
```

### Code Review Checklist

- [ ] All tests passing (100%)
- [ ] Code coverage meets target
- [ ] Type hints present
- [ ] Docstrings complete
- [ ] Examples in docstrings
- [ ] No security issues
- [ ] No performance regressions
- [ ] Documentation updated
- [ ] CHANGELOG.md updated (if exists)

---

## 🎓 Learning Resources

### TDFOL Fundamentals

1. **First-Order Logic**
   - Predicates, quantifiers, variables
   - Unification and substitution
   - Resolution and proof search

2. **Deontic Logic**
   - Obligations, permissions, prohibitions
   - Standard Deontic Logic (SDL)
   - Contrary-to-duty obligations

3. **Temporal Logic**
   - Linear Temporal Logic (LTL)
   - Operators: □, ◊, X, U, S
   - Temporal reasoning

4. **Modal Logic**
   - Accessibility relations
   - K, T, D, S4, S5 systems
   - Modal tableaux method

### Implementation Patterns

1. **Parser Design**
   - Lexical analysis
   - Recursive descent parsing
   - Operator precedence
   - Error recovery

2. **Theorem Proving**
   - Forward chaining
   - Backward chaining
   - Resolution
   - Tableaux methods

3. **Optimization**
   - Memoization
   - Caching strategies
   - Parallel algorithms
   - Heuristic search

### External Tools

- **spaCy:** https://spacy.io - NLP library
- **NetworkX:** https://networkx.org - Graph algorithms
- **hypothesis:** https://hypothesis.readthedocs.io - Property testing
- **GraphViz:** https://graphviz.org - Graph visualization

---

## 📞 Getting Help

### Documentation Hierarchy

1. **This File** - Quick reference and checklists
2. **Executive Summary** - High-level overview
3. **Comprehensive Plan** - Complete technical details
4. **README.md** - Module usage and examples
5. **Code Comments** - Implementation details

### Troubleshooting

**Issue:** Parser fails to recognize operator
→ Check `tdfol_parser.py` token definitions
→ Verify operator mapping in lexer

**Issue:** Proof not found
→ Check if inference rules are loaded
→ Verify formula is well-formed
→ Check timeout limits

**Issue:** Tests failing
→ Run single test for details: `pytest test_file.py::test_name -v`
→ Check test fixtures
→ Verify test data

**Issue:** Performance degradation
→ Run profiler
→ Check cache hit rate
→ Verify parallel search is enabled

---

## ✅ Phase Completion Template

When completing a phase, create `PHASEx_COMPLETE.md`:

```markdown
# Phase X: [Name] - Completion Report

**Status:** ✅ COMPLETE
**Date:** YYYY-MM-DD
**Duration:** X weeks (planned) / Y weeks (actual)

## Summary
[Brief summary of achievements]

## Deliverables
- [x] Component 1 (XXX LOC)
- [x] Component 2 (XXX LOC)
- [x] Tests (XX tests)

## Statistics
- LOC Added: X,XXX
- Tests: XX (100% pass)
- Coverage: XX%

## Key Features
1. Feature 1
2. Feature 2

## Example Usage
```python
# Code example
```

## Testing Summary
- Unit: XX tests
- Integration: YY tests
- Property: ZZ tests

## Known Issues
[List any issues]

## Next Phase
[Link to next phase]
```

---

## 📈 Progress Tracking

### Weekly Status Template

```markdown
# TDFOL Phase X - Week Y Status

**Date:** YYYY-MM-DD

## Completed This Week
- [ ] Task 1
- [ ] Task 2

## In Progress
- [ ] Task 3
- [ ] Task 4

## Blocked
- [ ] Task 5 (reason)

## Metrics
- Tests: XX (target: YY)
- Coverage: XX% (target: YY%)
- LOC: XXX

## Next Week Plan
1. Task A
2. Task B

## Risks/Issues
[Any concerns]
```

---

## 🔗 Quick Links

- **Repository:** https://github.com/endomorphosis/ipfs_datasets_py
- **Module:** `ipfs_datasets_py/logic/TDFOL/`
- **Tests:** `tests/unit_tests/logic/TDFOL/`
- **CI/CD:** `.github/workflows/`

---

**Last Updated:** 2026-02-18  
**Version:** 1.0.0  
**Status:** 📝 Active Planning

---

**Need Help?** Check the comprehensive plan or reach out to the team!

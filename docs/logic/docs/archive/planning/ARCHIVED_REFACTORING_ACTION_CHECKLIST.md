# Logic Module Refactoring - Action Checklist

**Date:** 2026-02-17  
**Priority:** HIGH - Documentation Organization  
**Duration:** 8-10 days  
**Risk:** LOW (documentation only, no code changes)

---

## Quick Reference

- 📋 **Full Plan:** `COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md`
- 📊 **Executive Summary:** `REFACTORING_EXECUTIVE_SUMMARY.md`
- ✅ **This Document:** Daily action checklist

---

## Phase 1: Verify & Reconcile (Days 1-2)

### Day 1: Test Coverage Verification

- [ ] Run pytest to collect all tests
  ```bash
  cd /path/to/ipfs_datasets_py
  pytest ipfs_datasets_py/logic/ --collect-only > test_count.txt
  wc -l test_count.txt  # Get actual count
  ```

- [ ] Verify test count claims
  - [ ] Documentation claims: 790+ tests
  - [ ] Find actual count in output
  - [ ] Document findings in VERIFIED_STATUS_REPORT_2026.md

- [ ] Check test pass rate
  ```bash
  pytest ipfs_datasets_py/logic/ --tb=no -q
  # Record pass rate
  ```

- [ ] Update README.md badges with verified numbers

### Day 2: Phase 7 & Status Reconciliation

- [ ] Verify Phase 7 Part 1 (AST Caching)
  ```bash
  grep -r "@lru_cache" ipfs_datasets_py/logic/fol/
  # Confirm fol/utils/fol_parser.py has @lru_cache decorator
  ```

- [ ] Verify Phase 7 Part 3 (Memory Optimization)
  ```bash
  grep -r "slots=True" ipfs_datasets_py/logic/types/
  # Confirm types/fol_types.py has slots=True in dataclasses
  ```

- [ ] Document Phase 7 status
  - [ ] Parts 1+3: COMPLETE (verified)
  - [ ] Parts 2+4: DEFERRED (intentionally, targets met)
  - [ ] Overall: 55% complete, 100% of critical work

- [ ] Reconcile conflicting status reports
  - [ ] Compare PROJECT_STATUS.md vs REFACTORING_COMPLETION_REPORT.md
  - [ ] Compare PHASE_4_5_7_FINAL_SUMMARY.md vs repository memories
  - [ ] Document discrepancies in VERIFIED_STATUS_REPORT_2026.md

- [ ] Create VERIFIED_STATUS_REPORT_2026.md
  - [ ] Test count: [VERIFIED NUMBER]
  - [ ] Phase 7: 55% (Parts 1+3 complete, 2+4 intentionally deferred)
  - [ ] Performance: 14x cache speedup, 30-40% memory reduction
  - [ ] Production status: FOL, Deontic, TDFOL, Caching ready

**Deliverable Day 1-2:** `VERIFIED_STATUS_REPORT_2026.md`

---

## Phase 2: Consolidate Documentation (Days 3-5)

### Day 3: Archive Historical Reports

- [ ] Create archive directories
  ```bash
  mkdir -p ipfs_datasets_py/logic/docs/archive/phases_2026/
  mkdir -p ipfs_datasets_py/logic/docs/archive/planning/
  ```

- [ ] Archive phase completion summaries (move to phases_2026/)
  - [ ] PHASE_4_5_7_FINAL_SUMMARY.md
  - [ ] PHASE7_PERFORMANCE_OPTIMIZATION_PLAN.md
  - [ ] PHASE8_FINAL_TESTING_PLAN.md
  - [ ] REFACTORING_COMPLETION_REPORT.md
  - [ ] docs/archive/phases/*.md (if any)
  - [ ] docs/archive/sessions/*.md (if any)

- [ ] Archive old planning documents (move to planning/)
  - [ ] COMPREHENSIVE_REFACTORING_PLAN.md (superseded by new plan)
  - [ ] REFACTORING_IMPROVEMENT_PLAN.md (historical)

- [ ] Create archive README
  ```bash
  # Create docs/archive/README.md explaining structure
  ```

- [ ] Add "ARCHIVED_" prefix to moved files
  ```bash
  cd docs/archive/phases_2026/
  for f in *.md; do mv "$f" "ARCHIVED_$f"; done
  ```

### Day 4: Consolidate TODO Systems

- [ ] Review existing TODO systems
  - [ ] Read IMPROVEMENT_TODO.md (478 lines)
  - [ ] Read integration/TODO.md (48 lines)
  - [ ] Read EVERGREEN_IMPROVEMENT_PLAN.md (already well-structured)

- [ ] Decision: Use EVERGREEN_IMPROVEMENT_PLAN.md as primary backlog
  - [ ] It's already well-organized with P0/P1/P2
  - [ ] Has clear guardrails and continuous loops
  - [ ] Archive IMPROVEMENT_TODO.md as historical reference

- [ ] Archive redundant TODO files
  - [ ] Move IMPROVEMENT_TODO.md to docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO.md
  - [ ] Keep or archive integration/TODO.md based on relevance

- [ ] Update EVERGREEN_IMPROVEMENT_PLAN.md
  - [ ] Mark Phase 4-5-7 items as complete
  - [ ] Add any new items from IMPROVEMENT_TODO.md if still relevant
  - [ ] Update priorities based on verified status

### Day 5: Eliminate Documentation Duplication

- [ ] Architecture Diagrams (consolidate to ARCHITECTURE.md)
  - [ ] Keep comprehensive version in ARCHITECTURE.md
  - [ ] README.md: Brief overview + link to ARCHITECTURE.md
  - [ ] FEATURES.md: Link to ARCHITECTURE.md, don't duplicate
  - [ ] Module READMEs: Component-specific only + link to main

- [ ] API References (consolidate to API_REFERENCE.md)
  - [ ] Keep API_REFERENCE.md as comprehensive reference
  - [ ] Module READMEs: Quick reference + examples + link to API_REFERENCE.md
  - [ ] Remove duplicate "## API Reference" sections from:
    - [ ] fol/README.md
    - [ ] deontic/README.md
    - [ ] common/README.md
    - [ ] tools/README.md
    - [ ] TDFOL/README.md
    - [ ] CEC/README.md
    - [ ] integration/README.md

- [ ] Feature Lists (consolidate to FEATURES.md)
  - [ ] FEATURES.md: Comprehensive list (single source of truth)
  - [ ] README.md: Top 5-10 features + link to FEATURES.md
  - [ ] ARCHITECTURE.md: Link to FEATURES.md, don't duplicate
  - [ ] PROJECT_STATUS.md: Production status only, link to FEATURES.md

- [ ] Status Reports (keep only PROJECT_STATUS.md)
  - [ ] PROJECT_STATUS.md: ONLY current status document
  - [ ] Archive REFACTORING_COMPLETION_REPORT.md
  - [ ] Archive PHASE_4_5_7_FINAL_SUMMARY.md
  - [ ] Remove VERIFIED_STATUS_REPORT.md if outdated

**Deliverable Days 3-5:** Clean documentation structure (61 → ~40 files)

---

## Phase 3: Update Current Status (Days 6-7)

### Day 6: Update Core Status Documents

- [ ] Update PROJECT_STATUS.md
  - [ ] Use verified test count
  - [ ] Update Phase 7 status (55% with explanation)
  - [ ] Update performance metrics (verified)
  - [ ] Remove conflicting information
  - [ ] Add "Last Verified: 2026-02-17" to each section

- [ ] Update README.md
  - [ ] Update badges with verified metrics
  - [ ] Clarify production vs beta vs experimental
  - [ ] Simplify feature list (top 10 + link to FEATURES.md)
  - [ ] Add Quick Links section
  - [ ] Remove duplicate architecture content

- [ ] Create QUICKSTART.md
  - [ ] Extract "Quick Start" from README.md
  - [ ] Add 3-5 minute tutorial
  - [ ] Installation → Basic usage → First conversion
  - [ ] Keep it under 200 lines

### Day 7: Update Supporting Documents

- [ ] Update ARCHITECTURE.md
  - [ ] Remove duplicate feature lists
  - [ ] Update component status matrix
  - [ ] Ensure diagrams are current
  - [ ] Remove duplicate API content

- [ ] Update FEATURES.md
  - [ ] Verify all feature claims match code
  - [ ] Mark as Production/Beta/Experimental
  - [ ] Remove duplicate architecture
  - [ ] Add workarounds for Beta features
  - [ ] Link to KNOWN_LIMITATIONS.md

- [ ] Update DOCUMENTATION_INDEX.md
  - [ ] Reorganize by user journey (Getting Started → Advanced → Contributing)
  - [ ] Remove links to archived documents
  - [ ] Add status/freshness dates
  - [ ] Add quick navigation at top

**Deliverable Days 6-7:** Updated, accurate status documents

---

## Phase 4: Polish & Validate (Day 8)

### Day 8: Quality Assurance

- [ ] Check internal links
  ```bash
  # Use markdown-link-check if available
  find ipfs_datasets_py/logic -name "*.md" -exec markdown-link-check {} \;
  ```
  - [ ] Document any broken links
  - [ ] Fix or remove broken links
  - [ ] Update links to archived files

- [ ] Run markdown linter
  ```bash
  markdownlint ipfs_datasets_py/logic/*.md
  ```
  - [ ] Fix linting issues
  - [ ] Ensure consistent formatting

- [ ] Verify code examples
  - [ ] Check code blocks in README.md
  - [ ] Check examples in QUICKSTART.md
  - [ ] Check examples in API_REFERENCE.md
  - [ ] Verify they compile/run

- [ ] Manual review
  - [ ] Read through PROJECT_STATUS.md
  - [ ] Read through README.md
  - [ ] Read through ARCHITECTURE.md
  - [ ] Check for typos and grammar
  - [ ] Verify technical accuracy

- [ ] Final verification checklist
  - [ ] All markdown files follow consistent structure
  - [ ] No duplicate content
  - [ ] All links work
  - [ ] Code examples valid
  - [ ] Single source of truth for each topic
  - [ ] Historical reports archived
  - [ ] Single TODO system (EVERGREEN_IMPROVEMENT_PLAN.md)
  - [ ] Clear documentation hierarchy

**Deliverable Day 8:** Polished, production-ready documentation

---

## Buffer Days (Days 9-10)

### Day 9-10: Review & Adjustments

- [ ] Final review of all changes
- [ ] Address any feedback
- [ ] Run final validation checks
- [ ] Prepare completion report
- [ ] Update repository memories with learnings

---

## Daily Reporting

At end of each day, report progress:

```bash
git add .
git commit -m "Day X: [Brief description of completed work]"
git push
# Use report_progress tool
```

**Report Format:**
- What was completed today
- What remains to be done
- Any blockers or issues
- Next day's plan

---

## Success Metrics

Track these metrics to measure progress:

| Metric | Start | Target | Current |
|--------|-------|--------|---------|
| Markdown Files | 61 | 35-40 | [TRACK] |
| Content Duplication | ~30% | <5% | [TRACK] |
| TODO Systems | 3 | 1 | [TRACK] |
| Archived Reports | 0 | 30+ | [TRACK] |
| Verified Metrics | 0 | 5+ | [TRACK] |
| Broken Links | ? | 0 | [TRACK] |

---

## Quick Commands

**Count markdown files:**
```bash
find ipfs_datasets_py/logic -name "*.md" -type f | wc -l
```

**Find duplicate content:**
```bash
grep -r "architecture diagram" ipfs_datasets_py/logic/*.md
grep -r "## API Reference" ipfs_datasets_py/logic/**/*.md
```

**Check test count:**
```bash
pytest ipfs_datasets_py/logic/ --collect-only | grep "test session starts" -A 5
```

**Archive files:**
```bash
mv FILE docs/archive/phases_2026/ARCHIVED_FILE
```

**Check links:**
```bash
grep -r "\[.*\](\./" ipfs_datasets_py/logic/*.md | grep -v "^Binary"
```

---

## Emergency Contacts / Resources

- **Full Plan:** `COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md`
- **Executive Summary:** `REFACTORING_EXECUTIVE_SUMMARY.md`
- **Current Status:** `PROJECT_STATUS.md`
- **Ongoing Backlog:** `EVERGREEN_IMPROVEMENT_PLAN.md`

---

**Remember:** This is documentation-only refactoring. No code changes. Low risk.

**Goal:** Match documentation quality to code quality (which is already excellent).

**Let's finish what we started! 🚀**

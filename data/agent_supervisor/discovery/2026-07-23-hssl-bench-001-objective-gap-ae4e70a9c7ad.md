# HSSL-BENCH-001 Objective Validation Repair

Date: 2026-07-23
Task id: HSSL-BENCH-001
Goal id: HSSL-G009
Goal title: Reject empty AST symbols as objective evidence
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T222700Z/discovery/2026-07-23-hssl-bench-001-objective-gap-ae4e70a9c7ad.md`
Source fingerprint: `ae4e70a9c7ad48b740ad78ba5b1173e09499768a`
Objective marker: `HSSLEV0097B20`
Todo vector key: `c2727048722f7c84`
Merge key: `17817a72feec64c6`
Merge family: `objective/HSSL-G009`
Work scope: `objective_validation_repair`

## Finding Reconciliation

The source scan reported `HSSLEV0097B20` as AST evidence in three generated
static JavaScript files. Those hits were pre-repair false positives. Minified
one-character identifiers such as `e` and `v` have an empty representation
after objective-token normalization, but the evidence matcher compared their
raw values by substring. A raw `e` therefore appeared to support any unrelated
objective marker containing that letter.

The repair normalizes candidate AST symbols with the same tokenizer used for
objective evidence terms and excludes candidates whose normalized value is
empty. Exact-text, path, embedding, and nonempty AST evidence channels retain
their existing behavior.

## Implementation Evidence

- `ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/objective_graph.py`
  applies the fail-closed `_ast_evidence_symbols` boundary before fuzzy AST
  matching.
- `ipfs_accelerate_py/test/api/test_agent_supervisor_objective_graph.py`
  covers cached literal-empty, whitespace-only, one-character, and
  punctuation-only candidates; preserves nonempty AST and exact evidence; and
  proves a live minified JavaScript source leaves the unique marker missing.
- The regression test contains the literal `HSSLEV0097B20` marker, so an
  unforced objective scan can accept validated, relevant test code as AST
  evidence rather than rediscovering the original gap.
- The complete 483-line objective heap is present at its supervisor-configured
  path, preserving HSSL-G009 and every downstream benchmark goal.

No child goal was added: this is one bounded validation-gate repair with one
work item. HSSL-G009 remains active so the supervisor can reconcile completion
from validation evidence; generated todo/vector state was not edited manually.

## Validation

Command:

```text
PYTHONPATH=ipfs_accelerate_py python -m pytest ipfs_accelerate_py/test/api/test_agent_supervisor_objective_graph.py -k empty_symbol -q
```

Result: passed on 2026-07-23 (`3 passed, 32 deselected`).

The complete objective-graph test module also passed (`35 passed`). A subsequent
unforced scan of the restored heap located `HSSLEV0097B20` in the regression
test and emitted no HSSL-G009 finding, confirming that the supervisor can
continue past the repaired goal without a forced-goal override.

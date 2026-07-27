# HSSL-BENCH-012 Objective Corpus Receipt

Date: 2026-07-24
Task id: HSSL-BENCH-012
Goal id: HSSL-G020
Goal title: Build the reviewed and immutable benchmark corpus
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-012-objective-gap-8e24807af2c2.md`
Source fingerprint: `8e24807af2c29c28b8057cb93f0e68fd5df69e97`
Objective marker: `HSSLEV0201B64`
Todo vector key: `4422685635cd1df6`
Merge key: `86154520de5730b0`
Merge family: `objective/HSSL-G020`
Work scope: `goal_subgoal_multi_evidence_batch`

## Finding Reconciliation

The source scan found no implementation evidence for HSSL-G020. The objective
heap named one bounded deliverable: a representative pilot, development, and
holdout corpus whose semantic and proof ground truth is reviewable, immutable,
and not derived from model output.

`benchmarks.logic_pipeline.cases.HSSLEV0201B64` is now a literal Python
function symbol bound to the executable corpus contract. The fixture is
canonical JSONL, and its manifest independently binds byte order, case
contents, source text, reviewed semantic targets, proof obligations, coverage,
and the frozen benchmark protocol.

## Implementation Evidence

- `benchmarks/logic_pipeline/cases.py` defines strict versioned records for
  cases, review attestations, manifest entries, manifests, and verified loaded
  corpora using only the Python standard library and the frozen protocol
  contract.
- Every case has a safe stable ID; one of the pilot, development, or holdout
  splits; a stratum and difficulty; source text bound to its SHA-256; one of
  `proved`, `disproved`, `ambiguous`, or `unsupported`; nonempty semantic IR;
  required predicates/entities; negative-control labels; and durable
  provenance. Proved and disproved cases require a reviewed theorem or
  countermodel obligation.
- Review attestations require two distinct reviewer roles, an allowlisted
  manual review method, approval of the semantic target and applicable proof
  obligation, and explicit confirmation that model output was not used.
  Provenance independently rejects model-generated ground truth.
- The frozen fixture contains 30 cases: ten per split, three per each of ten
  strata, and all four expected classes. It covers simple FOL, nested
  quantifiers, deontic/modal and temporal rules, epistemic uncertainty, Legal
  IR scope ambiguity, multi-premise entailment, counterexamples, Hammer-style
  obligations, and unsupported Lean proof text.
- Canonical parsing rejects duplicate JSON keys, unknown or missing fields,
  invalid enums, duplicate IDs, noncanonical JSONL, absent final newlines,
  source digest changes, incomplete split/class coverage, and invalid review
  or proof applicability.
- The immutable manifest binds the frozen protocol, exact corpus bytes
  (`a2720cee073bfe4221594c5b29d8a4557865f272f4d2c2c3553dfeab74c03509`),
  contiguous order, every case and source digest, split/stratum/class counts,
  and reviewed semantic content
  (`9a1747aac8ab7393147795b7f756318a67f66b6f4eedd6ed368b0337c5e46932`).
  Its canonical run-contract identity is
  `58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26`.
- `tests/unit/benchmarks/logic_pipeline/test_cases.py` proves public evidence,
  coverage and acceptance fields, review and model-ground-truth boundaries,
  deep immutability, dependency-free imports, order/content/source/semantic
  tamper rejection, strict JSON behavior, and class-appropriate proof
  obligations.

## Backlog Alignment

No child goal is needed. HSSL-G020 is the bounded reviewed-corpus contract,
while the existing HSSL-G021, HSSL-G022, and HSSL-G023 children already isolate
fixture reuse, adversarial-control expansion, and split/leakage integrity. The
generated external todo, bundle, and vector state was not edited manually.
HSSL-G020 remains active so the supervisor can reconcile completion from the
validated evidence receipt.

## Validation

Commands:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_cases.py -q
python -m pytest tests/unit/benchmarks/logic_pipeline/test_package.py tests/unit/benchmarks/logic_pipeline/test_contracts.py tests/unit/benchmarks/logic_pipeline/test_capabilities.py tests/unit/benchmarks/logic_pipeline/test_cases.py -q
python -m compileall -q benchmarks/logic_pipeline tests/unit/benchmarks/logic_pipeline
git diff --check
```

Results on 2026-07-24: focused validation passed (`16 passed`); full benchmark
unit regression passed (`86 passed`); compile and diff checks passed.

# HSSL-BENCH-002 Objective Corpus Packet Receipt

Date: 2026-07-24
Task id: HSSL-BENCH-002
Goal ids: HSSL-G022, HSSL-G021
Goal titles: Add adversarial and negative proof controls; Reuse existing regression and ambiguity fixtures
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Primary source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-002-objective-gap-9915fa1f3f8b.md`
Primary source fingerprint: `9915fa1f3f8b133a8e3cf6719b35ddf3ed01fc71`
HSSL-BENCH-006 source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-006-objective-gap-0339b10873d8.md`
HSSL-BENCH-006 source fingerprint: `0339b10873d8b99e50536efba25e55289bb2b7f9`
HSSL-BENCH-008 source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-008-objective-gap-450b28d94319.md`
HSSL-BENCH-008 source fingerprint: `450b28d94319483c252b8fb37f1ff52ea1548275`
Objective markers: `HSSLEV0224A96`, `HSSLEV0217E25`
Todo vector key: `cb3b30dcc4233279`
Merge key: `2c5f4dd444cb0948`
Merge family: `goal_packet/benchmark_corpus/general/919ae362bc61`
Goal packet role: `packet_aggregate`
Covered sibling tasks: `HSSL-BENCH-006`, `HSSL-BENCH-008`
Work scope: `goal_subgoal_packet_aggregate; vector_ast_bundle`

## Finding Reconciliation

The aggregate source scan found neither executable evidence marker for the
HSSL-G021/HSSL-G022 corpus packet. The two goals share the frozen fixture
directory but already form the correct two work-item boundary: HSSL-G021
imports reviewed regression and ambiguity cases with durable provenance, while
HSSL-G022 independently proves that every named hostile proof input is barred
from benchmark eligibility. Implementing them in one packet closes the shared
fixture and trust-boundary gap without folding either contract into the
reviewed core corpus or leakage-audit goals.

`benchmarks.logic_pipeline.fixture_import.HSSLEV0217E25` and
`benchmarks.logic_pipeline.adversarial.HSSLEV0224A96` are literal Python
function symbols bound to executable contracts. Their canonical fixture
manifests and focused tests provide relevant AST and behavioral evidence,
rather than relying on marker text copied only into planning prose.

## Fixture-import Evidence

- `benchmarks/logic_pipeline/fixture_import.py` implements strict,
  standard-library-only import entries and returns a frozen, deeply immutable
  `ImportedFixtureSet` from `load_fixture_imports`.
- `tests/fixtures/logic_pipeline_benchmark/fixture_import_manifest.json` uses
  manifest schema
  `ipfs-datasets.logic-pipeline-benchmark.fixture-import-manifest.v1` and entry
  schema `ipfs-datasets.logic-pipeline-benchmark.fixture-import.v1`.
- The manifest freezes nine imports: two Legal IR ambiguity packets, two
  TDFOL obligation/prohibition conformance cases, three Hammer
  golden/poisoned/reconstruction cases, and two Leanstral modality mutations.
  Five cases are positive and four are negative.
- Every entry retains its original case identifier, upstream source path and
  selector, complete source payload, exact source-byte digest, and canonical
  record digest. Expected results are explicitly attributed to
  `existing_fixture`, and each entry carries a false model-generated
  attestation.
- Strict loading rejects duplicate or ambiguous identifiers, path traversal,
  model provenance, schema or field drift, count/coverage drift, source or
  provenance changes, and manifest/content digest tampering.
- `tests/unit/benchmarks/logic_pipeline/test_fixture_import.py` exercises the
  public evidence marker, complete family and polarity coverage, identifier
  and source preservation, canonical determinism, immutable records,
  model-ground-truth rejection, and fixture/manifest tamper detection.

## Adversarial-control Evidence

- `benchmarks/logic_pipeline/adversarial.py` defines the exact seven
  `ControlKind` values: `invalid`, `contradictory`, `unsupported`,
  `prompt_like`, `copied`, `sorry_bearing`, and `admit_bearing`. Frozen
  `AdversarialControl`, `ControlManifest`, and `ControlSuite` records bind all
  negative controls, reviewed rationales, and expected gate dispositions.
- `tests/fixtures/logic_pipeline_benchmark/adversarial/controls.jsonl` contains
  exactly one independently identified control per kind. Its
  `manifest.json` binds canonical order, content, coverage, rationale, and all
  record/file digests; the executable gate supplies the expected rejected or
  safety-incident class.
- `load_control_suite` and `validate_control_coverage` reject duplicate JSON
  keys, unknown or missing fields, noncanonical JSONL, duplicate identifiers,
  reordering, count or coverage drift, and record/file/manifest digest
  tampering.
- `classify_candidate` deterministically screens candidate text and
  protected-copy references.
  `gate_candidate` makes every matched control ineligible. A hostile candidate
  that is nevertheless claimed kernel-verified emits an
  `INVALID_CONTROL_VERIFIED` safety incident; it never appears as an eligible
  improvement. A benign candidate requires an accepted native-kernel receipt
  before it can pass.
- `tests/integration/benchmarks/logic_pipeline/test_adversarial_controls.py`
  proves the evidence marker, exact kind coverage, deterministic detection,
  immutable and strict records, fixture integrity, all-control ineligibility,
  fail-closed claimed verification, benign receipt gating, and JSONL/manifest
  tamper rejection.

## Acceptance Coverage

- HSSL-G021's original identifier/source-reference requirement is enforced by
  each imported record and its canonical manifest, not merely documented.
- HSSL-G021's no-model-ground-truth boundary and positive/negative coverage
  requirement fail closed at load and validation time.
- HSSL-G022's seven named hostile classes have one frozen control apiece, and
  deterministic classification plus eligibility gating ensures none can be
  recorded as a verified improvement.
- The packet composes with HSSL-G020's reviewed corpus and HSSL-G010's
  kernel-only verification boundary without changing either frozen contract.

## Backlog Alignment

No child goal is needed. HSSL-G021 and HSSL-G022 are already the packet's two
bounded work items, and their overlap is intentionally limited to the
`tests/fixtures/logic_pipeline_benchmark` output. The explicit bundle work
order makes HSSL-BENCH-002 primary and covers sibling HSSL-BENCH-006
(HSSL-G022) and HSSL-BENCH-008 (HSSL-G021). Completion propagation is
validation-driven: it applies only after both evidence markers, manifests, and
focused test contracts pass; this receipt by itself does not complete any
task.

Both objective statuses remain active for supervisor reconciliation. The
generated external todo bundle, task status, vector index, todo vector key,
merge metadata, and sibling records were not edited manually. This preserves
the objective heap as the declarative source and lets the supervisor propagate
the aggregate result through the recorded packet work order.

## Validation

Commands:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_fixture_import.py -q
python -m pytest tests/integration/benchmarks/logic_pipeline/test_adversarial_controls.py -q
python -m pytest tests/unit/benchmarks/logic_pipeline tests/integration/benchmarks/logic_pipeline -q
python -m compileall -q benchmarks/logic_pipeline tests/unit/benchmarks/logic_pipeline tests/integration/benchmarks/logic_pipeline
git diff --check
```

These two focused commands are the packet completion boundary: both must pass
before aggregate completion can propagate to HSSL-BENCH-006 and
HSSL-BENCH-008.

Results on 2026-07-24: fixture-import validation passed (`16 passed`);
adversarial-control validation passed (`38 passed`); the combined focused
packet passed (`54 passed`); and the complete logic-pipeline unit/integration
regression passed (`179 passed`). Compile and diff checks passed. The
fixture-specific `.gitignore` exception keeps the canonical adversarial JSONL
available in a clean checkout so its pinned manifest remains reproducible.

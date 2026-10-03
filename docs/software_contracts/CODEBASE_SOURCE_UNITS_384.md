# Captured function units with the shared Source384 parent

`codebase_source_units_384` supplies optional model advice for an existing
`RepositoryCodebaseIndex`. It reads the original captured files, inventories their
Python functions, and passes bounded function views to the existing GTE and
shared 384-dimensional decoder. It never replaces a captured file with a fixture,
trains a model, or changes the source or model head.

The input scope is explicit: callers supply a native source head, repository,
selected captured paths, a registered shared-parent version, and the pinned local
embedding snapshot. The calling supervisor remains responsible for binding those
paths and the checkpoint selection to its authorized task population.

## Source identity and coverage

`source_function_units.extract_function_units` reuses the Security formula
extractor's qualified names, complete-function spans, and line-to-byte maps.
Each unit records its original path and file SHA-256, qualified name, enclosing
scope, original byte range, normalized body SHA-256, and exact source map. An
independent AST comparison checks that indentation normalization preserves the
function node. Normalized text is a function view; it is not represented as a
complete original module. The legacy formula extraction schema remains unchanged.

The inventory includes nested functions and every function in each selected
file. Unsupported source and normalization cases remain explicit. Selection is
the canonical path/source-byte-order prefix, with unselected units retained as
`deferred_selection_budget`. This is deterministic bounded coverage, not semantic
ranking. Functions over GTE's 512-token maximum are recorded as
`deferred_gte_token_limit`; they are not truncated.

Limits include 128 selected files, 1 MiB per captured file, 4 MiB of captured
population bytes, 1,024 functions, 128 numerical candidates, 32,768 characters
per candidate, and 32 MiB per serialized artifact. Whole-inventory limits refuse
the operation rather than silently dropping functions. File-level unsupported
conditions and per-unit deferrals appear in the saved coverage counters.

## Preparation, inference, and replay

The native APIs are:

```python
preparation = prepare_source_units(index, expected_head=head, paths=paths)
validate_source_units(index, preparation)

result = infer_shared_parent_units(
    index, repository, expected_head=head, registry=registry,
    version_id=parent_version, paths=paths, embedding_snapshot=snapshot,
    scheduler=scheduler, timeout_seconds=180, memory_mb=4096,
)
validate_shared_parent_units(
    index, repository, result, registry=registry,
    embedding_snapshot=snapshot, scheduler=scheduler,
)
```

The result contains the native registry artifact reference, the complete report,
and flags describing whether that invocation ran the numerical worker. The report
retains original and compatibility-view checkpoint hashes, native model version,
source head, complete preparation, producer and runtime pins, embedding asset
pins, numerical rows, worker receipt, and coverage.

Numerical work runs in an isolated, offline CPU subprocess admitted through the
existing resource owner. It loads the actual pinned GTE and shared decoder;
target labels and source execution are absent. The worker uses the existing
sampled process-tree RSS limit, which can overshoot and does not guarantee peak
RSS. CUDA execution is not part of this profile.

Replay re-derives the source maps, checks the parent checkpoint and embedding
assets, validates the output and its hashes, and resolves the committed native
operation. `validate_shared_parent_units` additionally observes the live source
head before and after replay. It does not invoke the numerical worker.
`load_source_unit_inference` is historical replay only and makes no current-source
claim.

## What the result establishes

Decoder outputs are candidates. Proof, execution, completion, source-semantics,
and whole-file-semantics authority remain false. A mapped function can still lack
its module globals, closure bindings, or a supported source contract. Those cases
remain fail-open instead of being treated as checked program properties.

Repository retention is `unknown_not_evaluated`; this inference path performs no
training or promotion. Downstream intent planning and proof checks must retain
their independent contract and admission rules.

The initial actual-model development control inventories five functions from an
unchanged 73,909-byte Python module. Four receive decoder candidates and one is
deferred for token length. Two candidates report source-contract mismatch and
two report unsupported source contracts. These are truthful inference and replay
controls, not a benchmark score or a demonstrated formalization improvement.

The [retained development evidence](evidence/source-unit384-20261003/README.md)
contains the actual inference receipt, exact source and test snapshots, the
initial omitted-CUDA setup failure, and the corrected CPU and scanner test runs.

The [separate observation performance evidence](evidence/source-observation-performance-20261003/README.md)
diagnoses repeated CID encoding when a captured graph's working set exceeded
4,096 entries. That version increased the pure encoding and validation caches to
8,192 entries each; they store short identity results, not source or graph bodies.
Every stored body and live registration is still verified. On one retained
Bottle snapshot, the same native observation took 27.85 seconds before and
13.62 seconds after the change under cProfile. This is a single component
measurement, not a general scaling claim or a complete benchmark result.

The [full public-source cold-index follow-up](evidence/source-cold-index-performance-20261003/README.md)
retains the later 218-file profile, failures, and current-producer controls.
Its 12,554-edge graph exceeded the earlier cache bound. The fixed per-cache bound
is now 32,768 entries, retaining all live registration and fresh body-hash checks.
AST facts use parameterized INSERT chunks of at most 128 rows and a 256 KiB
parameter-byte target; a larger already-valid row remains a singleton. Canonical
projection validation, transaction hooks, source/head fences, rollback, and
post-commit counters are unchanged. This qualifies bounded indexing and replay;
it makes no claim about decoder accuracy, task success, or overall benchmark speed.

The [combined preparation follow-up](evidence/source-combined-observation-performance-20261003/README.md)
reuses exact canonical manifest reconstruction within a fixed four-entry,
128 MiB retained-representation bound. Fresh CAS reads and all current-source,
head, SQL, AST, model and producer checks still run. A guarded native comparison
also avoids duplicate catalog serialization when exact typed equality is known;
other representations keep the original comparison. The full local preparation
completed at 89.963 seconds against the unchanged 90-second native deadline,
while its outer wrapper returned at 90.041 seconds. That very small margin is
not a Docker qualification or a general performance guarantee. Its 127 decoder
candidates all remain unsupported for source-contract proof use. The package
retains earlier failed attempts and 114 distinct final controls across two runs.

The [SQL and dependency diagnosis](evidence/source-sql-column-performance-20261003/README.md)
replays the exact 31 AST projections with all 13 catalog tables and cold-reopen
parity. Column-list insertion improved the host component but left Docker execute
time near 40 seconds, so its production patch remains unapplied. A separate
isolated dependency experiment found repeated unsuccessful pandas imports during
DuckDB scalar conversion and measured their cost with real package absence.
These results guide a deployment dependency fix; they do not qualify a corrected
Docker runtime, change source/proof checks, or establish a benchmark score.

The [inference publication follow-up](evidence/source384-inference-publication-import-20261003/README.md)
removes an accidental training/proof import from inference artifact staging.
Canonical JSON staging lives in the shared Source384 owner; training retains its
compatibility wrapper and its canonical checkout guard. Actual checkpoint/GTE
inference and reopened-registry replay pass while training imports are blocked.
The decoded candidates remain unverified; this import separation does not grant
proof authority or establish a completed Docker benchmark.

The [verified embedding advice follow-up](evidence/source384-verified-embedding-advice-20261003/README.md)
adds an opt-in to the shared GTE asset verifier; Source384 explicitly selects it.
All nine assets pass byte-count, SHA-256 and held-descriptor identity checks
before any best-effort file-cache advice. Other callers retain the default
without advice. Source384 keys bind the requested policy and verifier source;
checkpoint architecture and weights are unchanged. Forty current unit controls
and seven real checkpoint/inference/replay controls pass. These component
results do not demonstrate reclaimed memory, Docker admission or benchmark reward.

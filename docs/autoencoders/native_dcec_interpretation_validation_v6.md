# Native DCEC interpretation validation v6

This additive validation path addresses an interoperability gap in the bounded
rich Intent DCEC projection. The older native DCEC parser accepted functional
Boolean formulas such as `implies(...)`, `and(...)` and `or(...)`, while the
independent strict TDFOL check rejected those strings. Replacing the strings
with superficially similar infix syntax was insufficient because the resulting
AST could change.

The v6 path keeps the original formula, complete native AST and source-bound
symbol declarations. A bounded independent functional parser checks the owned
rich DCEC fragment, and native reparsing must still reproduce the complete
recorded AST. The original projection is then lowered to a Lean interpretation
contract. This is a parser compatibility repair, not evidence that the source
text is true or that the model learned its meaning.

Related evidence: [Intent/UI projection gap repairs](intent_ui_projection_gap_repairs.md).
The previous four rich Intent failures are already exposed regression cases;
they are not a fresh holdout.

## Additive interfaces

The modules below are under
`ipfs_datasets_py.logic.formalization.autoencoder`.

| Module | Role |
| --- | --- |
| `strict_dcec_functional` | Independently validate the bounded rich DCEC functional payload, typed symbols and native AST correspondence |
| `native_family_lean_emitters_v6` | Own the explicit `rich-intent/dcec/v1` route and delegate unrelated routes to the unchanged v5 emitter |
| `native_family_lake_v6` | Replay exact source inputs, prepare every emitted projection, run the real modality-specific Lake build, and issue a live local handle |
| `projection_validation_contract_v6` | Require complete family accounting, supported lowering, native parsing and matching live v6 execution before permitting strict training |
| `parallel_projection_checks_v2` | Run v6 native checks with the existing shared resource scheduler and retain successful and failed jobs |
| `ui_source_contract_384_v4` | Validate a separately declared, source-bound Boolean guard interpretation and retain original unsupported UI routes |

Existing v5 interfaces and checkpoints remain unchanged. A serialized v5
receipt does not become a v6 execution. An old live handle also cannot be
relabelled as one: the new issuer must execute and register its own handle.
Existing 8D and 384D generation readers remain unchanged; this validation
repair does not alter their learned weights, decoder
architecture, tokenizer, context limit or projection-training optimizer.

## Strict training handoff

The additive numerical entry point is
`ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v6`.
Its public `train_validated_family_projection_autoencoder` accepts separate
training and tuning lists of live v6 observations, `domain_id`, a fresh
`output_dir`, and the existing optimizer options. Its checkpoint schema is
`validated-native-family-autoencoder/v6`; it does not reinterpret v5 artifacts.
Existing v5 training and checkpoint readers remain available unchanged.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    autoencoder_family_training_validated_v6 as trainer,
)

# Every observation must have passed complete native policy and modality floors.
result = trainer.train_validated_family_projection_autoencoder(
    training_observations, tuning_observations,
    domain_id="intent_ir", output_dir=fresh_checkpoint_directory,
    epochs=12, refinement_strategy="decoder_blocks",
)
```

Partial live observations, detached receipts and old policy observations fail
before feature extraction, optimization or checkpoint creation. Every emitted
validated payload participates in structural feature and loss accounting;
dropping a projection is an error. The trainer replays live validation against
the exact ordered reports again before writing its result. The existing
four-tensor model, macro-family loss, decoder calibration, optional family
decoder-block refinement, non-regression selection and numerical deadlines
are unchanged. This entry point does not introduce a new source-text decoder,
learn missing logic semantics, or establish convergence merely by becoming
callable. This regression performs no optimization run.

## Explicit UI Boolean guards

The UI v4 adapter adds the distinct report schema
`ui-guarded-family-training-targets/v1`. Both v6 native replay and v6 policy
validation dispatch to its owning validator. Without a guard interpretation,
the adapter preserves the previous v3 preparation path.

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    ui_source_contract_384_v4 as ui,
)

# Complete caller declarations, never guessed from the source or a model output.
guards = ui.UIGuardInterpretation.from_dict(guard_declaration)
prepared = ui.prepare_family_targets(
    original_source_text, unchanged_ui_candidate,
    behavior_interpretation=explicit_behavior,
    guard_interpretation=guards,
)
ui.validate_prepared(
    prepared, original_source_text, unchanged_ui_candidate,
    behavior_interpretation=explicit_behavior, guard_interpretation=guards,
)
```

The closed guard declaration binds exact source, candidate and behavior hashes;
declares Boolean variables and initial values; preserves complete original
native guard records; and supplies bounded expressions using literal,
variable, `not`, `and` and `or`. Variables are explicitly frozen across all
transitions. The adapter exhaustively retains enabled and disabled valuations,
and reports reachable nonterminal deadlocks. It does not turn a false initial
guard true, invent an edge, claim progress, or infer UI semantics from prose.

Timing, effects, priority, recovery and parallel-region semantics remain
unsupported in this narrow route. Original failing projections remain present
alongside any new supported guarded projections; their failures still block a
complete strict training gate. TLA+ syntax evidence remains distinct from TLC
model checking and from the required actual Lake execution.

## Required checks

The rich DCEC route must consume the complete source formula. Unknown symbols,
wrong arities, malformed tokens, trailing text, unsupported operators,
undeclared or inconsistent sorts, free variables and unsupported terms remain
blocked. Full payload binding includes its formula, native AST, symbol table,
typed source surfaces and digests. Swapping branches, referents, modality,
context or a cognitive actor is a semantic change, even when the resulting
string parses.

Failure after the new emitter claims this route must not fall through to a
weaker emitter. Only genuinely unrelated routes may delegate to v5. Native
parsing, independent parsing and Lean lowering are distinct requirements; a
success in one cannot erase a failure in another.

The live Lake owner checks exact report/source replay before work and again
after the build. Producer modules and invoked tool bytes remain pinned.
Modifying the report, source, native owner or tool invalidates the live
evidence. Saved JSON, an unissued handle or a handle issued for another report
cannot reopen the training gate. Batch validation rechecks live evidence and
binds it to the ordered optimization target reports.

The policy retains all **40 canonical families** and the existing modality
minimum floors. A source-specific applicability review cannot waive an emitted
projection or a batch floor. Narrowing the requested family list remains an
explicitly incomplete diagnostic. Every emitted projection is checked,
including multiple projections in the same family. Prepared-family counts and
native-passing-family counts must be reported separately.

## Parallel execution and solver scope

The v2 parallel adapter uses the existing host-local resource scheduler and
proof-safety checks. Worker count respects CPU, memory and child-process
capacity; native jobs acquire shared leases. These reservations do not impose
a hard aggregate Lake RSS limit. Existing native owners still bound subprocess
runtime, output and workspace size. Timeouts remain per step and lease wait,
not a claimed deadline for the entire batch.

A failed job stays in the result and releases its resources. Unsupported
parsing, missing syntax tools or a failed Lake build must not be replaced by a
different backend to manufacture a passing observation.

Optional portfolio diagnostics remain restricted to the exact propositional
fragment supported by that adapter. DCEC is not propositional, so this repair
must not route it to the propositional Z3/CVC5 diagnostic. Solver names alone
do not establish support for a logic family's semantics. Diagnostic
satisfiability results remain distinct from validity candidates and from Lake
evidence.

## Regression protocol and evidence

Validation uses unchanged original formulas and typed source inputs for the
four previously failing rich Intent cases: positive `if`, negated `if`, `and`
and `or`. Their existing v5 preparation remains available as the baseline.
Each v6 candidate requires an actual `lake build IntentIR` on its exact
generated module. The expected repair affects the DCEC row; unrelated
projections, formulas, source hashes and the forty-family request stay fixed.

The previous cases each had four prepared families but three native-passing
families. Any claimed improvement must report actual per-projection parser,
lowering and Lake results, not merely a larger prepared-target count. Even if
the repaired DCEC projection passes, missing modality families and minimum
floor requirements remain blockers to complete strict training.

Unit tests cover live issuer boundaries, source/report tampering, complete
floor accounting, failed parser/lowering/build statuses and resource release.
Tests that substitute a bounded tool runner are explicitly dependency doubles;
their receipts are not counted as actual Lake executions. Separate native
regression receipts provide the real command, tool hash, generated Lean bytes,
input hashes and exit status.

The final evidence is in
[`results.json`](../implementation/reports/evidence/native-dcec-ui-20261002/results.json)
and its adjacent manifest/archive. Results on the frozen canonical source:

- **919 unique tests passed, zero final skips.** The initial combined run had
  16 old-v2 fixture failures because earlier tests pinned that owner's functions
  before the old fixtures monkeypatched `_execute`. All 18 tests in that module
  passed in an isolated process without changing the source-provenance guard.
  Eight optional native-tool tests then passed with the explicit installed Lake
  executable. All invocations and the deduplicated accounting are archived.
- **35 attempts per native invocation:** the previous 29 unchanged attempts,
  one authored intention case and five authored UI guard cases. Fourteen remain
  blocked before Lake, including incorrect learned outputs, a mismatched
  modality, mismatched initial states, a timeout without clock semantics and
  an incorrectly bound guard declaration. No unsuccessful row was dropped.
- **All 21 prepared case/fit jobs have a successful actual Lake build across
  two invocations.** There were 30 successful build executions in total, all
  with partial coverage. Each invocation had six resource-lease timeouts;
  neither is reported as a clean parallel run. The unchanged second invocation
  supplies the six builds that the first could not start. Both full receipts
  remain archived, with an exact report-digest join for observations across runs.
- The four exposed Boolean Intent cases retain exactly the same source,
  candidate, report and payloads. Prepared families remain **4/40**; native
  passing families rise **3 to 4** because the DCEC row now passes. The extra
  intention fixture retains its agency binding and passes its 13 emitted
  projections across nine families; that is still incomplete modality coverage.
- The three positive UI guard fixtures pass FOL, frame and two transition-system
  projections, including bounded TLA+ with actual SANY syntax checks. Their
  original EC projection remains blocked. The false initial parameter retains
  the nonterminal `open` deadlock. Lean checks enabled action correspondence
  and the absence of expanded successors for disabled original transitions.
- All 21 distinct prepared jobs still fail the strict training gate. Archived
  receipts from either invocation cannot be reissued as live training authority.

Both runs replay all 144 rows from the same six previously fitted checkpoints.
Weights, generated tokens, complete candidates and original reports stayed
unchanged; embedding replay is checked to the existing `1e-6` tolerance. These
are already exposed regressions, not new fidelity holdouts. The learned GRU
Intent source agreements remain 3/24 and 8/24, and UI agreements remain 3/24
and 2/24. The structured ridge arms remain 24/24 on this exposed authored
panel. This release repairs validation/coverage; it does not demonstrate a
learned reconstruction improvement.

Observed warm model-readout plus complete source audit and eligible family
preparation, excluding embedding production and Lake, was:

| Domain / reader | Rows per run | First run seconds/span | Second run seconds/span |
| --- | ---: | ---: | ---: |
| Intent GRU, seed 3517 | 24 | 0.048804 | 0.050830 |
| Intent GRU, seed 3518 | 24 | 0.092967 | 0.099354 |
| Intent structured ridge | 24 | 0.274814 | 0.260855 |
| UI GRU, seed 3517 | 24 | 0.034309 | 0.034037 |
| UI GRU, seed 3518 | 24 | 0.031132 | 0.031124 |
| UI structured ridge | 24 | 0.101980 | 0.099328 |

Rejected candidates stop before family preparation, so these timings are not
comparable measures of decoder quality or decoder-only throughput. Entire
regressions took 252.15 and 249.73 seconds, including resource waits. Python
peak RSS was 842408 and 844188 KiB, excluding child processes. Both runs used
CPU, one Torch thread, temperature zero, the unchanged 64-token generation
bound, and two scheduled native workers reserving 1024 MiB/two CPU slots/two
child slots each. Model readers were warm; Lake used fresh workspaces. No
bridge-on legal-IR evaluation ran, and no bridge/prover/cache timing is claimed.

A live scheduler observation recorded `proof_memory_stall` during the second
run. Capacity reservations, safety checks and 30-second lease waits were not
relaxed. Persistent host memory pressure remains an operational limit on a
clean parallel campaign; repeated compiler success does not resolve that limit.

The native regression performed no training or checkpoint promotion and made
no weight downloads. Some unit tests exercise temporary synthetic optimizer
fixtures; they are not convergence or model-fidelity evidence. Existing 8D and
384D checkpoint owners and the previous validation versions remain intact.
Actual Lake execution is the only Lean admit path. These interpretation
builds still grant no natural-language fidelity, complete modality qualification
or proof of source meaning. The Constitution remains unformalized.

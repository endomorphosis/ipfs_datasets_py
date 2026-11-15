# Legal norm evidence snapshot performance

The [retained statutory replay](legal_ir_statutory_norm_definition_evidence_20261016.md)
validated both partial §7213 hypotheses with their full definition evidence.
Each preparation/validation phase took about seventeen minutes. Static inspection
found eleven complete aggregate snapshots during companion preparation, followed
by the same preparation path during validation. Nested owners additionally
regenerate source and contextual evidence. These costs require separate
measurement; a snapshot speedup alone does not establish a whole-pipeline speedup.

The snapshot scalar path previously validated and serialized a scalar through
the general JSON encoder, then parsed the resulting bytes back into a Python
value. Strings and floats were serialized twice inside that encoder. The current
implementation validates and serializes exact immutable scalars once and retains
their values directly. Dictionaries and lists are still copied separately for
every occurrence. No memoization, evidence truncation or replay-result cache is
introduced.

The scalar path preserves strict integer bounds, finite floating-point values,
signed zero, UTF8 encoding, escaping and rejection of NUL/surrogates and builtin
subclasses. Node, byte and depth accounting, type-separated digest tokens,
mutation fences and producer-source checks retain their existing contracts.
Independent compatibility tests contain the previous wire and snapshot
algorithms so a defect in the optimized helper is not automatically shared by
the reference. Both implementations still use Python's JSON library.

## Qualification scope

The bounded qualification uses the existing resource scheduler and captures the
candidate sources separately from the frozen preceding statutory runtime. It
selects the source-correspondence, norm-review and norm-definition owner suites
plus scalar/snapshot compatibility tests.

The performance comparison applies old and candidate snapshot functions to the
four-field aggregate actually used by the companion: `norm_preparation`,
`request_raw`, `norm_inputs` and `definitions`. Each complete input transport is
checked against its retained commitment. Hypotheses A and B share one physical
statutory paragraph; they are separate input populations, not independent laws or
repair trials. Ordered old/candidate and candidate/old passes are descriptive
measurements. Profiled diagnostic calls are excluded from timing comparisons.

Successful compatibility requires matching full typed detached values and exact
snapshot commitments. It does not require complete reports from different
runtime revisions to have identical hashes: their producer pins must change.
This comparison does not replay the historical statutory preparation, perform
human meaning review, qualify training labels or execute a solver/Lean build.

## Observed results

`run-01` completed on **2026-10-16, 02:20:56–02:28:44 UTC**. All three
selected phases completed, the source identities and scheduler policy stayed
unchanged, and the lease was released. **315 tests passed**, with no selected
failures, skips or deselections:

| Suite | Passed cases |
| --- | ---: |
| New independent snapshot/wire compatibility cases | 120 |
| Existing norm interpretation review | 54 |
| Existing norm/definition evidence | 42 |
| Existing source/typed correspondence | 99 |

The review tests include fictional signers and ephemeral signatures. Those
authentication controls do not create production reviews or statutory approvals.
Recorded module origins confirm that both changed owners loaded from the new
capture and the benchmark baseline loaded from the preceding frozen capture.

| Complete saved population | Snapshot nodes | Prior mean seconds | Candidate mean seconds | Prior/candidate ratio | Wall-time reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| §7213 hypothesis A | 2,393,779 | 13.630 | 4.911 | 2.78× | 64.0% |
| §7213 hypothesis B | 2,393,879 | 13.653 | 4.942 | 2.76× | 63.8% |

Each mean uses two unprofiled calls in the same process, with order reversed
between repetitions. Full typed detached values and the exact type-separated
commitment matched on every call. These are descriptive local measurements of
two related populations, without a confidence interval or a generalization
claim. CPU affinity and scheduler admission did not provide exclusive-core
isolation. The application sources and inputs are pinned; the complete
Python/pytest/system environment is not pinned.

Separate A-only profiling confirms the changed work:

| Instrumented operation | Prior calls | Candidate calls |
| --- | ---: | ---: |
| Snapshot node traversal | 2,393,779 | 2,393,779 |
| Digest update | 2,393,779 | 2,393,779 |
| JSON encoding (`dumps`) | 3,593,217 | 1,564,302 |
| JSON decoding (`loads`) | 2,028,915 | 0 |

The instrumented calls took 40.716 and 16.394 wall seconds respectively; they
are excluded from the paired timing table. Profile cumulative times overlap
and must not be added. Container copying, all repeated input occurrences and
the complete hash stream remain; this change removes redundant scalar work.
It makes no per-arm allocation or memory-saving claim.

The parent-observed phase times were 302.959 seconds for tests, 103.648 seconds
for A and 45.436 seconds for B. Benchmark phase clocks include loading, equality
checks and (for A) profiling, so they must not be added to their nested snapshot
clocks. Peak sampled child RSS was approximately 101 MiB, 1,043 MiB and
1,043 MiB respectively. The benchmark holds both implementations' detached
outputs for comparison; these are whole-phase observations, not per-arm memory
measurements. Capture and saved-file audit costs are outside these phase clocks.

The separate standard-library readback verified saved-file hashes, the selected
test inventory, phase/result consistency and loaded module origins, and
recomputed the timing table. It did not rerun behavior or independently attest
that execution occurred. Its operator-supplied input capture commitment is
`7af5c26402008265880b8e104215d538e64ea811bf9f85e47f3acd95f8474c61`.
The artifact README gives the exact execution and readback commands.

Observed results and reproduction commands are retained in the new
`artifacts/legal-ir-snapshot-performance-20261016-01/` directory. The preceding
statutory receipts remain unchanged. This performance work leaves §7214's
unsupported counting/role semantics and all pending statutory reviews open.

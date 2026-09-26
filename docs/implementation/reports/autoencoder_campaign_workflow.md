# Campaign inputs in the training and repair workflow

Implementation report, 2026-09-26. Capture-r3 passed all 82 offline tests and
the archived six-record handoff on one unchanged source snapshot. Its resource
reservation is released. Native checkpoint validation remains deferred.

The v8 worker and owner already understood frozen source campaigns, while the
training-cycle entry point and checkpoint-feedback reader restricted
their inputs to v6. The adapter now connects v8 inline embeddings to those
existing paths. It preserves v6 support and keeps v7 mapped-input jobs outside
this adapter: their transport records require live Arrow views.

The shared `logic/autoformal/training_cycle_inputs.py` helper calls the existing
corpus verifier for both training and validation roles. It returns training
records in the exact verified record-ID order. An explicit feedback selection
must be a unique, bounded subset of those training IDs. Default cycle feedback
rejects more than 128 training records before dispatch; it never truncates or
resamples them. Matching source text, title and section is no longer used to
choose repair records.

Staging copies the declared immutable artifacts into the owner's CAS and binds
their exact sizes and hashes. V8 variants bind the inventory, source partitions
and producer receipt set; the batch projection remains specific to the job.
The adapter stages the projection, original producer leaves, selected source
files, complete target snapshot, optional Arrow feature weights and checkpoint
dependencies. Staging grants no execution or verification authority. The cycle
verifies inputs before selected-file staging, and the owner and worker retain
their independent checks.

The checkpoint-feedback reader retains its native receipt, unpromoted candidate,
exact state, effective constructor, source-tree and no-memory checks. The new
helper receives its own source hash and before/after checks. Compiler identity
is checked before repair work is queued. These are runtime integrity checks;
they do not establish learned semantic equivalence or formalization.

The new combined-storage tests use two disjoint synthetic v8 batches, one
complete target artifact and one base checkpoint. The cases cover JSON and
compressed target bundles, ordinary and Arrow-backed feature weights, accepted
sparse transactions, independent candidate versions, exact replay, restart and
a dependent sparse resume. Corruption cases must reject damaged target or
weight artifacts, wrong bindings and forged sparse results. Model evaluation
and optimizer execution are forbidden in these tests; updates and complete
target values are explicit fixtures. The cases passed, establishing integration
contracts, not native learning or parallel throughput. Their immediate executor
does not run workers concurrently.

The artifact-only probe used the archived six-record batch (three training,
three validation) and complete frozen campaign roots. It verified through
the helper, staged through the adapter into an isolated registry and
independently resolved the registered job through the owner. All three returned
the exact archived verification result, with ordered training membership and no
validation leakage. The run stayed queued and the checkpoint head stayed on
its original version. Its base artifact is an opaque metadata placeholder and
was never loaded as a model. No training job, native feedback observation,
repair enqueue or Hugging Face publication ran.

The five test modules contain 35 existing cases and 47 new cases: 18 input/cycle,
18 feedback and 11 combined-storage cases. All passed with zero skips, errors or
failures in capture-r3. The parent, both children and final closeout matched all
7,760 package Python files and 901 test/helper/configuration dependencies.
The archived inputs, staged CAS files and protected checkpoints/receipts also
retained their exact hashes. These guards qualify this captured revision;
later edits require their own validation.

| Offline phase | Wall time |
|---|---:|
| Pytest invocation, 82 cases | 62.125837 s |
| Cycle input verification, six records | 7.649034 s |
| Cycle artifact staging | 0.150118 s |
| Independent registered-owner resolution | 8.044003 s |
| Complete guarded audit | 108.410048 s |

These are test and preparation diagnostics, not training or legal-IR speed
comparisons. The artifact probe used one worker, six samples, bridge names `[]`,
prover evaluation `false`, and metric disk-cache flag `0`. OS cache state was
uncontrolled. No cold-run, per-span inference or bridge-on evaluation claim is
made. The artifact probe did not construct legal-IR targets or score a model.

The cooperative reservation allowed 400,000,000 disk bytes, including a
300,000,000-byte external pytest fixture charge, 1,024 MiB RAM, one CPU slot and
240 seconds. Actual fixture storage was 168,882,301 bytes; final owned capture
storage was 82,879,471 bytes, for 382,879,471 bytes charged under the reservation.
The successful claim and CPU/memory lease were released with no live owned
children. Sampled resource checks are not kernel quotas or continuous memory
peak measurements.

Evidence: [guarded audit](../../../workspace/test-logs/federal-corpus-audits/campaign-workflow-final-20260926/capture-r3/audit-receipt.json),
[test receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-workflow-final-20260926/capture-r3/tests/tests-receipt.json),
[archived-data probe](../../../workspace/test-logs/federal-corpus-audits/campaign-workflow-final-20260926/capture-r3/probe/cycle-report.json),
[resource release](../../../workspace/test-logs/federal-corpus-audits/campaign-workflow-final-20260926/capture-r3/resource-release.json),
and [independent evidence closeout](evidence/autoencoder_control_plane_plan/campaign-workflow-closeout-20260926-r3.json).
The closeout rechecks the captured assertions and current artifacts; it does
not issue another DuckDB query or run another test suite.

The preceding [preflight profile](autoencoder_campaign_preflight_profile.md)
records the remaining metadata cost separately. Further operation-local reuse
can be evaluated against that evidence after the campaign workflow is connected.
No broader cache, Arrow default or optimizer acceptance change is part of this
integration.

Two preliminary attempts remain unsuccessful. Capture-r1 stopped before test
collection because the harness disabled pytest's cache provider while the
repository's `conftest.py` requires it. Capture-r2 used a private pytest cache
and ran 82 cases: 76 passed and six failed in the new combined-storage suite.
Its package, dependency, input and protected-artifact guards all passed.
The failures exposed two fixture assumptions: default checkpoint reload resets
the process-local revision counter, and Arrow row order must match the exact
serialized base checkpoint. The corrected assertions retain complete candidate
identity comparison through revision-preserving replay, while separately
checking normal reload semantics. The initial Arrow fixture derives its row
order from the serialized full base; sparse resume uses the existing resolver's
reload state, matching the worker. These corrections change no production codec or acceptance
rule. Both failed captures and their 400 MB resource claims remain retained;
neither is superseded by relabeling its result. Their
[r1 audit](../../../workspace/test-logs/federal-corpus-audits/campaign-workflow-20260926/capture-r1/audit-receipt.json)
and [r2 audit](../../../workspace/test-logs/federal-corpus-audits/campaign-workflow-recapture-20260926/capture-r2/audit-receipt.json)
remain unsuccessful.

Remaining end-to-end work includes reusable campaign batch planning and resume,
complete campaign artifact packaging for Hugging Face, source-authority checks,
additional language frontends, native qualification and semantic coverage.
The smallest next orchestration step is an immutable ordered plan over already
verified v8 batches for one sealed campaign. It should bind logical batch IDs,
roots, targets, configuration and parent-version policy separately from attempt
IDs. Start with resume between batches: verify completed results, reuse exact
queued jobs, and stop on ambiguous running or failed attempts. Fenced retries
need an explicit owner contract. The current coordinator admits queued runs;
it does not yet provide logical-batch-to-attempt reconciliation. Reusing the
existing bounded manifests and projections avoids a second source-selection
implementation. This connects usable work sooner than another metadata parsing
optimization; the profile remains useful for later amortization decisions.
The [federal-law plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md) and
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md) retain
those requirements. The Constitution remains unformalized. Only
`lake build <Lib>` counts as a Lean admit.

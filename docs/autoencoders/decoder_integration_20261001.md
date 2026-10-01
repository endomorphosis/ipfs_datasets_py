# Decoder integration validation — 2026-10-01

The production census now retains actual learned legal formulas alongside direct
compiler formulas. A separate formula fleet runs bounded resumed training jobs
through one DuckDB owner and scoped Quack workers. Formula checkpoint transport
preserves the complete model, optimizer, cursor and selection state across exact
parent-bound updates.

The isolated release suite passed **565 tests in 86.82 seconds**, with no failures,
errors or skips, at implementation commit
`51c286548d16fbe8da13fce5e314e8f14a7a23ed`. This extends the
[earlier end-to-end report](decoder_e2e_20261001.md); its known lost-exception
failure remains unresolved. No semantic qualification, legal admission or model
promotion was granted.

The [summary](../implementation/reports/evidence/decoder-integration-20261001/summary.json)
and [hashed manifest](../implementation/reports/evidence/decoder-integration-20261001/manifest.json)
retain test results, full census observations/goals, worker and owner receipts,
decoded outputs, generated Lean projects and build logs. Checkpoint parameters
and private worker credentials are excluded. Persisted receipts establish audit
history; they are not substitutes for fresh execution.

## Actual production census smoke

Four authored clauses used the existing learned legal checkpoint, with no
training or held-out fitting. Fresh imports were pinned to the canonical
workspace tree, including compiler, decompiler and parser. This separate smoke
ran against the shared working tree before the implementation commit, with
concurrent unrelated edits present; the recorded relevant source hashes stayed
unchanged during the run. The clean release suite provides a separate check of
the committed implementation.

| Clause | Observation retained |
| --- | --- |
| Officer retains a file for at least 20 days unless emergency | Learned formula dropped the exception; direct compiler retained it. Real disagreement and deferred repair/training goals remain. |
| Officer submits a backup report within 10 days | Raw ASTs differ only in validated redundant temporal records. Raw disagreement remains visible; the restricted canonical-core comparison passes, without creating a false semantic repair goal. |
| Agency retains a file | Raw formula ASTs match. Agreement does not confer qualification. |
| Provision relates to administrative review | Actual model out-of-vocabulary abstention and no compiler formula; no fabricated output or score. |

Three model formulas and three compiler formulas were exported. Paired v2
retained two repair goals; census v4 retained two repair and two training goals.
Full observations and exact canonical ASTs survived Parquet readback and retry.
Both importers produced dry plans without enqueuing or executing supervisor
work. The four-row output index uses its new v2 namespace. A real historical
paired-v1 writer was also replayed through the current reader/importer without
changing its four original artifact hashes.

Measured wall time was **2.636 seconds total**, including inference, compilation,
exports, index construction and importer subprocesses. Source-only inference
took **0.05446 seconds/span**; direct compilation took **0.06922 seconds/span**.
Peak process RSS was 713,416 KiB. Sample count was four, worker count one,
temperature zero, prover evaluation off, metric disk cache off, and bridge names
empty. No metric cache was used. **No bridge-on evaluate ran** and
`legal_ir_target_count` was zero: these are not legal-IR bridge speed results or
a comparison with the Constitution timings.

No Hub data upload or weight download ran. The index recorded an observed real
Hub revision, but its local authored source bundles were absent from that
revision; remote source closure therefore remains explicitly false. This index
is not published or represented as remotely resolvable.

## Actual parallel training and resume

The full CLI test launched two private training processes for Intent and UI/UX.
They claimed and renewed jobs through installed native Quack; one owner held the
DuckDB registry. Both resumed registered parents from 70 to 72 optimizer steps.
Workers staged exact updates and ran decoded-output schema checks; the owner
verified the replayed candidate and independently reran those schema checks
before completing the jobs.

| Branch | Training categorical CE before → after | Update payload / full result |
| --- | --- | --- |
| Intent | 0.000787921 → 0.000764386 | 22,677 / 35,453 bytes |
| UI/UX | 0.009445419 → 0.008672252 | 29,221 / 46,844 bytes |

These are two-row authored reconstruction fixtures, with overlapping structures
in tuning, not held-out generalization results. Each worker and the owner built
two decoded outputs: **eight actual `lake build DecoderSchema` invocations** in
total. All passed. These are structural schema checks, not `lake build Legal`
admissions, full logic-family backend validation or proof of source semantics.

Rerunning the same plan returned both jobs as `already_completed` without
retraining. A third run did the same when its memory budget permitted zero new
workers. Resource claims were released after successful completion. The CLI
fixture uses an isolated scheduler namespace and resource ledger, with actual
hardware probes and reservations; it does not claim admission under the busy
host's shared scheduler. Its temporary 90 GB ledger is a fixture allowance, not
a campaign storage-cap change.

The first broad run exposed six positive census fixtures missing a newly
required margin field and one CLI fixture assuming shared-host capacity. The
fixtures were corrected; production checks were not relaxed. Targeted reruns
passed, followed by the complete isolated 565-case release suite. Negative
checks reject altered worker authority fields, wrong leases and substituted
transport results before publication.

## Scope and remaining work

See [fleet operations](formula_fleet.md), [checkpoint exchange](formula_checkpoint_exchange.md),
[paired census](paired_span_census.md) and [versioned output columns](span_exchange_outputs.md)
for APIs, formats and commands.

The new codec has exact replay and failure tests across Legal, Intent, Security
and UI/UX. Hub upload/receive tests use an injected offline client, not a live
multi-machine campaign. Downloads require explicit opt-in; updates require the
exact local parent. Dense tensor changes may approach full checkpoint size.

The Quack listener remains loopback. Machines can explicitly exchange and
register the same immutable branch, but automatic shared-head election,
independent-branch merging, periodic Hub polling and a production remote
listener remain unimplemented in this formula profile. No new Arrow weight
codec is claimed. Native decoding remains reconstruction of compiler-prepared
structures; the legal source-conditioned decoder is a separate lineage from
the legacy 8D and modern 384D modal autoencoders. No service was restarted and
no existing checkpoint was overwritten. The Constitution remains unformalized.

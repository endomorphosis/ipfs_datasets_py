# Mapped daemon inputs and detached snapshot samples

The daemon now accepts the existing opt-in v7 training-job input format through
its verified local input session. V6 jobs retain ordinary list vectors and the
same exported descriptor and checkpoint provenance shape. This is input storage
integration, not a change to the optimizer, legal semantics, model weights or
default configuration.

## Input ownership and exact binding

`export_daemon_corpus_inputs` resolves the registered job and its owner-staged
artifact closure. For v7, that closure includes the mandatory Arrow input
artifact. The existing snapshot fields and CLI descriptor triplet are sufficient:
the immutable registered job digest binds the version and exact Arrow bytes.
There is no execution-time switch or fallback from a failed mapped job to lists.

`VerifiedDaemonCorpusInputs` reuses the worker's source, corpus-index, producer
receipt and Arrow verifier. Its own `ExitStack` retains the returned mapping
until the session closes, including construction-error cleanup. Primary samples
borrow rows from that mapping. Selection checks require the exact mapped vector
type, the session's mapping owner, the expected record identity and exact vector
bits. A detached list, another session's row or an arbitrary sequence cannot
substitute for a primary mapped input.

Existing boundary checks now also bind the Arrow file's path, inode and bytes
and verify the mapping remains unchanged. A failed boundary poisons the session
and follows the existing daemon failure path, preventing a new clean-shutdown
checkpoint. These are checks of immutable local artifacts; they do not guarantee
detection of transient mutation followed by restoration between checks.

The runner and independent owner verifier use one checkpoint-provenance builder.
For v7 only, it adds the Arrow content descriptor, the mapped-float32 storage
name and deterministic numeric-buffer verification. Observational access
counters do not enter checkpoint identity. Verification compares canonical JSON
so booleans, integers and floats cannot substitute for each other through Python
equality. V6 valid provenance remains unchanged.

## Snapshot lifetime

`MappedEmbeddingVector.__deepcopy__` returns an ordinary detached list of exact
Python floats. It preserves signed zero and aliases within one copy operation.
The result enters the copy memo only after complete successful materialization
and a final open-owner check. A closed or interrupted view fails without leaving
a partial row in the memo.

The daemon already copies samples synchronously before publishing asynchronous
snapshots. Those samples can now outlive input-session closure, including a
callback still running after nonblocking evaluator shutdown. Primary training
samples keep their mapped views until the session closes. This does not add
synchronization for concurrent copying and owner closure: callers must finish
the synchronous copy before closing its owner.

## Validation scope

The [combined regression capture](../../../workspace/test-logs/federal-corpus-audits/daemon-mapped-inputs-20260925/combined-r1-receipt.json)
records **346 tests passing, no failures or skips**, in 115.86 seconds of pytest
and 117.990 seconds of subprocess wall time. This includes all 31 semantic
gate/pilot cases. The wrapper nevertheless exits 1 and records `passed=false`:
the full-package source guard detected edits to `extended_repair.py`,
`repair_context.py` and `supervisor_queue.py` during the run. All four production
files changed for this slice, all 16 selected test files and the protected
checkpoint/measurement artifacts stayed unchanged. The failed provenance capture
is retained, not relabeled as a source-stable qualification or automatically
retried.

The earlier [focused session capture](../../../workspace/test-logs/federal-corpus-audits/daemon-mapped-inputs-20260925/session-r1-receipt.json)
records 70 passing cases: 42 existing session cases and 28 new mapped-session
cases, with its owned source/test hashes unchanged. That narrower guard does
not replace the failed full-package capture. Source-stable native validation
and performance testing remain deferred at the user's request.

Validation uses real Arrow IPC files, registries, source binding, mapped sessions,
sample construction and exact float comparisons with explicitly synthetic
embedding-producer declarations. A producer receipt is not evidence that a model
ran. Snapshot tests execute actual CPU embedding evaluation and the real queue;
compiler and proof callbacks in those tests are explicitly empty fixtures.

Actual daemon orchestration tests retain the real sampler, input session,
snapshot publisher, queue and checkpoint persistence around synthetic optimizer
callbacks. They check mapped primary samples, detached snapshot rows, exact
persisted Arrow provenance and rejection of Arrow mutation before persistence.
They do not qualify a complete native owner-leased v7 training cycle, held-out
learning or legal-IR throughput.

## Cost and next measurement

Only the numeric input buffer is mapped without copying. The job, manifest and
producer receipt still contain vector declarations; their verification and
metadata decoding allocate. Python scalar access allocates floats, and snapshot
handoff deliberately materializes detached lists. Additional file hashing and
mapping verification also cost time. The input codec remains bounded to 256
records with 384 float32 values per record and a 4 MiB artifact cap; this is not
a corpus-scale ingestion implementation.

No new per-span or bridge-on speed claim comes from these tests. Historical
[worker mapped-input measurements](autoencoder_produced_corpus_arrow_training.md)
were slightly slower overall: 23.0663 versus 22.9321 seconds median. Historical
[mapped feature weights](autoencoder_shared_targets_sparse_arrow.md) were also
slower: 12.7500 versus 12.1534 seconds. Those measurements do not predict the
cost of the newly connected daemon path.

Native validation is deferred at the user's request. When resumed, qualify a
native owner-controlled v7 cycle and compare it with a fresh v6 cycle using the
same pinned checkpoint, source records, splits, optimizer bounds and snapshot
settings. Record all five bridge names, prover flag false, metric
disk cache zero, one bridge worker, sample counts, target counts, per-pass sample
memory policy, full-cycle time, per-evaluate wall time, normalized time per span,
RSS and bytes written. Cold process startup does not imply cold OS caches or
empty in-process caches throughout a cycle. Keep full checkpoints authoritative
and sparse shadow off for that comparison unless both arms explicitly enable it.

Arrow-backed parameter adoption in the native daemon remains separate work;
this change maps embedding inputs. Production DuckLake materialization, Hugging
Face publication, multilingual semantic frontends and source-complete federal
law coverage remain open in the
[end-to-end plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
The Constitution remains unformalized. Only `lake build <Lib>` is a Lean admit;
these changes do not execute Lake or create an admit.

# Checkpoint numeric packing and idle writer release

The [checkpoint codec](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_checkpoint.py)
now packs numeric tables in batches of at most 4,096 values, replacing the
per-value pack/unpack/repack loop. The existing scalar path remains the fallback
for invalid batches, preserving validation order and exception messages. Full
and delta serialization share this encoder; checkpoint schemas, precision,
component selection, native normalization and persistence-baseline semantics
remain unchanged.

This is a bounded packing change. Canonical copies, current-state quantization,
native state reconstruction, table lists, identity calculations and compression
still occur. It neither removes all state copies nor makes checkpointing or
training zero-copy. The final full checkpoint remains authoritative.

The [asynchronous writer](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/async_artifact_writer.py)
also has a five-line fix that clears completed job, futures, loop-future and
receipt locals before announcing idle. Previously an open worker's waiting
frame could retain its last payload and a legacy bound `to_json` observer's
source state after releasing the queue's byte reservation. Caller-held failed
futures still retain their original exception and traceback, which may
legitimately retain the failed job. The fix removes the idle worker's references;
it does not erase tracebacks, suppress errors or force garbage collection.
Queue accounting, coalescing, spool recovery and drain behavior are unchanged.

The [synthetic profile receipt](../../../workspace/test-logs/federal-corpus-audits/checkpoint-numeric-packing-20260925/packing-profile-receipt.json)
records a storage-only experiment using isolated aliases of the
[frozen codec](../../../workspace/test-logs/federal-corpus-audits/checkpoint-numeric-packing-20260925/modal_autoencoder_checkpoint.before.py),
SHA-256 `eead66d108709e6868f7c112ee8df5580b4cd38a756e997f276b775d7dacd021`.
Only the candidate alias's packing loop changed during measurement. The
deterministic synthetic native state contained all 38 components and 131,072
feature numeric values. No model, protected checkpoint, bridge, evaluation or
training ran. All 7,742 package-source hashes stayed unchanged during capture.

There were only **two observations per arm and precision**, in baseline/candidate
then candidate/baseline order. The following medians describe full snapshot
serialization in that fixture:

| Precision | Original seconds | Candidate seconds | Identical full checkpoint bytes |
| --- | ---: | ---: | ---: |
| float64 | 0.766460 | 0.742861 | 266,885 |
| float32 | 0.254016 | 0.224379 | 216,297 |

Each comparison checked full checkpoint bytes, encoded payload/table results
and persistence-baseline fields for exact equality. The receipt retains hashes,
byte counts and equality outcomes. Separate edge comparisons covered
signed zero, subnormals, overflow, nonfinite values, empty/mixed values and a
batch boundary. These observations are limited synthetic evidence, not an
estimate of complete-daemon speed. GC policy was unchanged and filesystem cache
state was uncontrolled.

Compression and normalization remain the larger costs. In the separate
instrumented baseline observation, full serialization took about 1.422 seconds;
`zlib.compress` accounted for 0.565 seconds and native `_state_from_data` for
0.344 seconds. These profiled times must not be mixed with the unprofiled table
above or treated as bridge-cost measurements.

The [writer regression receipt](../../../workspace/test-logs/federal-corpus-audits/async-writer-idle-release-20260925/writer-regression-r1-receipt.json)
records **40 passing tests in 5.56 seconds**, including six new
[lifecycle cases](../../../tests/unit/optimizers/logic_theorem_optimizer/test_async_artifact_writer_idle_release.py).
Weak references distinguish active retention from release after drain while one
or two workers remain open. Cases cover legacy observers, failed futures,
coalesced followers and preservation of original exception identity/tracebacks.
The tests use ordinary GC to collect unreachable error cycles after callers
drop their references.

The [independent codec oracle](../../../tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_checkpoint_packing.py)
embeds the original encoder, numeric/canonical helpers, manifest and container
builder. Its expected path cannot call the changed production encoder. The
first focused capture retained 139 passes and one reference-isolation failure:
the reference manifest still called the live canonical helper. The test-only
correction froze that helper's manifest caller too; production behavior was not
changed to satisfy the assertion. The final 142 cases cover full and delta bytes
for all 38 components at both precisions, ragged/empty/nested shapes, signed
zero, Unicode and surrogate inputs, and error ordering across batch boundaries.

The [combined capture](../../../workspace/test-logs/federal-corpus-audits/checkpoint-numeric-packing-20260925/combined-r1-receipt.json)
passed **498 checks across 15 files**, with zero failures, errors or skips, in
24.217 JUnit seconds (26.372683 seconds for the bounded subprocess). All 7,743
canonical package Python files and selected tests stayed unchanged during
capture. Protected checkpoint and historical receipt sizes and hashes remained
exact. The selection includes the independent oracle, existing compact/sparse
codec and writer suites, actual daemon checkpoint fixtures, mapped weight
sessions, HF package reopening, pinned-tree semantic gates and the round-trip
pilot. Daemon optimization/evaluation boundaries in these fixtures are
synthetic. Focused and combined counts overlap and must not be added.

Combined receipt SHA-256:
`01c01d04ecc237b0a6c256d310342dab0cfac8d3d3b7bdfb2819742faa8418bf`.

Native validation remains deferred at the user's request. There is no
end-to-end inference or training speed claim, new success criterion, default
policy change, promotion authority or Lean gate change. Only `lake build <Lib>`
constitutes a Lean admit. The Constitution remains unformalized
(`formalized=false`).

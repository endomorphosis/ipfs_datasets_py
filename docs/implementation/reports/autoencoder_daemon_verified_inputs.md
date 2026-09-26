# Verified local inputs for the U.S. Code daemon

Implementation slice, 2026-09-25. This connects the existing owner/worker corpus
contracts to the ordinary daemon's sampling path. It does not qualify new
semantic coverage or an end-to-end speed improvement. The Constitution remains
unformalized. Only `lake build <Lib>` is a Lean admit.

## Input ownership and runtime use

The existing DuckDB owner resolves a registered v6 job and verifies its immutable
variant, staged job, source manifest, frozen index, embedding-production receipt
and exact source/vector closure. The new
[`export_daemon_corpus_inputs`](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_corpus_inputs.py)
factory exports a deterministic, content-addressed snapshot. Its eight fields
bind the run, variant, job digest/artifact, variant manifest/digest and owner
artifact root. Canonical JSON is limited to 1 MiB. It has no timestamps, owner
generation, duplicated vectors or daemon training settings.

[`AutoencoderRegistry.register_input_snapshot`](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py)
durably records the binding and a pending `input_snapshot_registered` DuckLake
outbox intent. Hashing occurs outside the short registry transaction. Operation
retries resolve the historical receipt; a returned old receipt is not a claim
that the artifact remains available. Registration does not claim a lease,
create a model version, move a head or activate an outbox consumer. Completed
worker jobs remain usable as immutable input anchors.

The daemon receives an explicit trusted local descriptor using all three flags:

```text
--autoencoder-corpus-input /absolute/owner/cas/ab/<sha256>
--autoencoder-corpus-input-sha256 <sha256>
--autoencoder-corpus-input-bytes <size>
```

The offline session verifies the complete closure without opening the live
DuckDB file. A content hash verifies integrity; it does not authenticate an
arbitrary claimed issuer. The descriptor must be handed over through the
trusted owner workflow. Quack input issuance and authenticated remote transport
are not implemented by this local adapter.

The opt-in sampler draws from the same full-range RNG and retains existing
attempt limits, text caps and memory exclusions. It rejects draws outside the
requested frozen role, preflights eligible role/text-cap counts, and never
reseeds or falls back to remote rows. It constructs native `LegalSample` objects
from exact verified fields and copied v6 vectors. Manifest record IDs remain
distinct from runtime sample IDs. Indexed canaries are reserved for later
representation evaluation; this mode requires `--validation-canary-count 0`
and no canary indices.

This first adapter accepts the existing English U.S. Code v6 contract. A new
registry variant alone does not qualify another language or a Constitution
training frontend. v7 mapped inputs remain outside this daemon adapter.

The session retains bounded scalar identity digests rather than parsed sample
graphs. It checks selected text, citation, identity and vector bits as well as
backing-file hashes and path identities. These checks protect consumed inputs;
they do not make mutable derived modal IR immutable. Guard time and check counts
are exposed separately. Changed inputs prevent new persistence or promotion of
affected work; earlier valid writes are not rolled back.

Summary, checkpoint and snapshot metadata carry the capsule descriptor, job and
variant digests, dataset/split IDs, index identity and production descriptor.
Restart rejects changed or removed input bindings, even if the summary is
missing or replaced by an unbound summary. A read-only checkpoint metadata
reader avoids constructing a second weight state and leaves a torn final delta
untouched for the ordinary recovering loader.

## Qualification scope

The [final validation receipt](evidence/autoencoder_control_plane_plan/daemon-corpus-input-validation-20260925.json)
records **384 passing checks** in 58.13 seconds (60.40 seconds including wrapper
work), with all 7,723 package sources unchanged during the run. The suite includes
the mandatory gates and five-case pilot, existing registry/coordinator/checkpoint
and shared-report integration checks, plus new corpus/runner cases. It exercises
real isolated DuckDB files, response-loss retries, restart, unchanged execution
and head state, substituted bindings, vector-bit changes, corruption, symlinks,
and nonblocking rejection of a replaced FIFO. Startup failure tests also cover
replayed checkpoints and cleanup when a descriptor was removed. Fixture-based
control-flow tests are distinct from native model/training qualification.

The [final native startup receipt](evidence/autoencoder_control_plane_plan/daemon-corpus-input-startup-20260925-r2.json)
passes through the actual parser/main under OS network denial, with no callable
replacements. The native reader/sample factory independently checks the exact
six source/vector records before and after main. Main opens the verified 3+3
inventory, retains default asynchronous snapshots, runs **zero cycles**, and
drains and closes its workers. No final checkpoint is enqueued; the private
initial checkpoint remains exact. Owner issuance is identical after restart,
the private head remains unchanged, and historical DB/CAS artifacts plus the
protected restart12 checkpoint remain unchanged. Package and complete producer
runtime/dependency guards pass. The historical first smoke receipt is retained;
the second qualifies the final cleanup fix and updated source inventory.

The closeout audit subsequently detected external edits to
`logic/autoformal/learned_feedback.py`, `supervisor_queue.py`, and
`repair_context.py`. Both passing runs retained stable sources during execution;
their results apply to the captured revision. That validation receipt
therefore leaves qualification of the **then-newer tree false**. A separate
[post-drift semantic check](../../../workspace/test-logs/federal-corpus-audits/daemon-corpus-inputs-20260925/semantic-after-drift-receipt.json)
passes all 31 gate/pilot checks with no further drift during that check. No
long native retry or producer-guard relaxation was performed.

Startup main took 2.741 seconds; the complete startup/input audit took 15.477
seconds. These ran alongside tests and are **not** cold compiler, bridge-on
evaluation, training, or speed-comparison results. The configured bridge list is
`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`; requested prover evaluation is false, metric disk
cache is 0, and worker count is 1. No bridges or optimizer steps execute in
this zero-cycle smoke. There is no wall-time-per-span or bridge-evaluate speed
claim. The full-cycle follow-up below separately qualifies actual sampling,
training, snapshot evaluation and final checkpoint durability together.

The separate offline qualification harness uses the existing six-record native
v6 input anchor: three frozen training rows and three validation rows. Historical
registry/CAS artifacts must remain unchanged. Exporting into a private owner
changes staged paths and therefore the job digest; both original and private
identities must be reported. The harness invokes the real parser/main with
no sample factory, evaluator or trainer replacements and retains asynchronous
snapshots. Its optional full-cycle mode must additionally audit actual selected
rows and require durable final persistence. Snapshot evaluation can invoke proof
metrics independently of the bridge prover flag; that work must stay visible.

## Native cycle follow-up

The [full native-cycle receipt](evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-20260925-r1.json)
passes on a fresh capture of the canonical tree. The real daemon main executes
one cycle with three training and three validation U.S. Code records, native
384-component vectors, no callable replacements and OS network denial. All
four optimizer evaluations report three legal-IR targets; both diagnostic
passes complete all five configured bridges without metric failures. The
default asynchronous snapshot finishes, matches its published version and
sequence, and drains at shutdown. The final checkpoint is durable and its
checksum and byte count match. Input, whole-package source, producer/runtime,
harness, historical-artifact and protected-checkpoint guards all pass.

This is a bounded projection-focused configuration. TODO optimization,
introspection and external guidance are disabled, as are compiler-guided
training and sample-memory probing; the exact arguments remain in the receipt.
It does not qualify successful changes from those other mutation paths.
Compiler diagnostics retain their ordinary 400-character policy, while the
optimizer and bridge diagnostics receive the complete selected texts.

The projection attempts one epoch and accepts **zero updates**. Independently
loading the protected base and final compact checkpoint yields identical
complete state, all 38 component digests and revision zero. Their identities
also match the snapshot when computed with its metric lineage. The final
1,664,462-byte artifact uses the existing compact writer; its smaller size than
the legacy JSON base is not a new optimization from this input adapter.
The [independent audit](evidence/autoencoder_control_plane_plan/daemon-corpus-input-native-cycle-independent-audit-20260925-r1.json)
records artifact checks, native loader comparison and timing/cache scope.

The [post-cycle semantic check](../../../workspace/test-logs/federal-corpus-audits/daemon-corpus-inputs-20260925/semantic-after-native-cycle-r1-receipt.json)
passes all 31 mandatory gate/pilot checks in 0.56 seconds (1.317 seconds including
the wrapper). All 7,723 package sources remain unchanged during that check and
match the native-cycle capture. This follow-up does not rewrite the earlier
startup and post-edit receipts or imply their larger regression suite ran again.

Measured main plus shutdown wall time is **133.940 seconds**, or **22.323 seconds
per unique input record** across this six-record cycle. The outer qualification,
including private-owner export and audits, takes 146.958 seconds. The cycle row
records 102.398 seconds. Projection reports 2.569 seconds; asynchronous snapshot
evaluation reports 45.205 seconds and overlaps other work. These scopes are not
additive. The actual projection backend label is `native`, with CPU execution,
one update family, one line-search attempt and a 180-second projection bound.
It is not a rerun of the historical `python_sparse_batch` gate-sentence epoch.

This run uses `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`, bridge prover evaluation false, metric disk cache 0,
and one worker. The ordinary daemon requests `use_sample_memory=True` for
before/after **training** evaluations and `False` for validation evaluations;
the projection report separately records `sample_memory_used=False`. This
corrects the earlier report's blanket false flag. The independent audit already
records the two evaluation policies. A requested flag alone does not establish
whether a particular sample received a memory hit. It starts a fresh process, but the input
walk parses samples before training and in-process caches warm during the
cycle; it is not an all-caches-cold benchmark. Before-training evaluation's
explicit timer records **28.788953 seconds for three targets**, or **9.596318
seconds per input span**. Later evaluations reuse process-local work and cannot
serve as independent cold baselines. Different source records and configuration
also prevent a speed comparison with the original three gate sentences.

| Bridge-on optimizer evaluation | Wall seconds | Seconds per input span (3 each) | Timer scope |
|---|---:|---:|---|
| Before training | 28.788953 | 9.596318 | Evaluator call alone; no result-cache reuse |
| Before validation | 27.561 | 9.187 | Phase, including heartbeat and surrounding bookkeeping |
| After training | 2.013 | 0.671 | Phase; process-local work is warm |
| After validation | 2.464 | 0.821333 | Phase, including lineage and result-cache writes; warm |

No individual adapter wall timers are persisted. Runner report-cache misses do
not establish cold targets: the underlying multiview memory cache can already
contain reports from earlier optimizer evaluations. Projection also reuses
precomputed evaluations. Peak process RSS reaches 1,791.62 MiB; this single
invocation does not qualify multi-worker memory use or throughput.

Snapshot telemetry reports 32 valid modal compilation/routing signals as
"proof" metrics. Its adapter uses `use_provers=[]`, which disables named
external prover initialization; the separate modal route can still execute
local tableaux. A route being available is sufficient for this validity field,
even when its theorem result is false. The compact receipt does not preserve
enough detail to count theorem successes. These are not Lake results or
admissions. No owner head is promoted, no training lease is claimed and no
candidate version is registered in this
qualification. The owner-issued descriptor establishes the input binding only.
There is no held-out canary improvement, Constitution formalization, DuckLake
destination commit or HF publication.

## Cost and remaining sequence

This adapter pays bounded input verification and uses ordinary list vectors so
existing asynchronous snapshot copies retain their ownership semantics. It
does not claim zero-copy daemon inputs. Existing v7 mapped worker inputs and
Arrow feature weights remain separately qualified options; their small-batch
complete-job measurements did not justify making them defaults.

The next daemon boundary is a complete immutable cycle candidate bound to the
owner's actual base and lease. The
[owned-invocation implementation plan](../plans/AUTOENCODER_DAEMON_OWNED_INVOCATION_PLAN.md)
starts with one bounded actual-main invocation and adopts its final durable
checkpoint after successful shutdown. This includes startup and shutdown
compaction as well as every cycle mutation. Projection patches alone omit later
TODO, guidance and compaction mutations. Add sparse replay in shadow mode, prove it
matches every final cycle mutation, then enable sparse persistence for qualified
cycles. Mapping additional weight families comes after measuring the remaining
copy/serialization cost and snapshot lifetime behavior.

Scale inputs through an immutable catalog of bounded batches under the frozen
index, rather than raising the current 256-record produced-batch cap. Production
DuckLake reconciliation and HF release publication still need destination
consumers and recovery qualification. Source inventory, reviewed semantics and
Lake evidence remain separate work; storage and training cannot turn an
unsupported Constitution span into an admitted formalization.

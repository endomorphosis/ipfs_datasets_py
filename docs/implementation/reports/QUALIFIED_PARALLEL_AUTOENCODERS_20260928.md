# Qualification in the incremental parallel runner

`scripts/ops/legal_ir/run_incremental_autoencoders.py` now invokes
`run_qualified_incremental_training`. Every completed optimizer attempt gets a
separate qualification receipt bound to its registered candidate version,
checkpoint bytes and sparse dependencies, source code, exact input samples and
model configuration. Optimizer acceptance alone cannot qualify a span or model.

The older `run_incremental_training` library function remains an optimizer-only
primitive for existing callers. Its completions are not qualification evidence.
The operator CLI has no switch to disable qualification. Start a new state
directory when migrating from the old optimizer-only stream; existing history
is not relabeled or silently promoted.

## Required gates

Every training and validation row must pass all of these checks:

* Model encode/decode embedding cosine at least **0.72**, and reconstruction loss
  at most **0.20**, with `use_sample_memory=False`. Missing, nonfinite, malformed
  or out-of-range measurements fail. These are the existing span-agreement
  thresholds, now absolute qualification requirements; optimizer loss reduction
  is a separate observation. These embedding metrics do not establish natural
  language or legal semantic equivalence.
* Complete canonical compiler/decompiler source round trip. Every emitted
  clause must succeed; a successful first clause cannot conceal an abstention.
  Empty vocabulary still abstains and parser-supplied atoms remain required.
* Exact exported syntax parsed by existing native grammars for FOL, deontic FOL,
  temporal FOL, deontic temporal FOL, DCEC and frame logic. Missing, skipped,
  placeholder and recovered/partial parses fail. Source-atom bindings and
  omitted facets accompany the artifacts. FOL and TFOL are explicit projections
  of deontic rules; syntax validity is not an equivalence proof or a proof that
  every temporal/cognitive construct is supported.
* A source-locked numeric pattern rendered through the existing JevOps statement
  lock and built with actual **`lake build Legal`**, using the already-installed
  Lean 4.26.0 toolchain. No Mathlib or toolchain download is allowed. A successful
  numeric theorem admits that rendered pattern only; it does not formalize an
  entire legal rule. `within_duration` and generic fingerprint fixtures do not
  satisfy this gate. Missing tooling, unsupported patterns and timeouts fail.

Disjoint validation is also required. `--validation-jsonl` supplies up to 32
rows and is bound into each immutable job and split identity. The owner excludes
normalized training/validation text overlap across all batches it has seen,
including remote-shard intake. CLI optimizer steps use training rows for their
unchanged objective and line search; qualification validation is excluded from
those steps and used for repeated candidate selection. Receipts explicitly say
`tuning_validation` and `heldout_canary=false`. This is not an independent test
set or a claim of generalization to the federal corpus. Multiple machines must
share the same split/configuration and nonoverlapping shard assignments.

Constitution rows identified by corpus/citation metadata never enter the source
round-trip path, remain unqualified, and produce repair evidence. No Constitution
span is marked `roundtrip_ok`. The Constitution remains unformalized.

The autoencoder currently decodes embedding vectors, not Lean, legal prose or
formulas. Qualification checks the exact embedding model and its deterministic
source compiler pipeline separately. Receipts never invent checkpoint-generated
text or attribute a deterministic compiler result to a learned decoder.

## Training, retries and repair work

The previous one-family projection limit selected only the first legal-IR head.
The CLI now allows all five existing update candidates: global legal-IR logits,
local legal-IR logits, family logits, decoded embedding, and the combined update.
This includes reconstruction training. Line search remains bounded to one
attempt per update family, one epoch per attempt, the configured wall-time
budget, and the existing strict optimizer acceptance/regression checks. Backend
remains `python_sparse_batch`; temperature remains zero.

When measured metric gates fail, the same span gets another immutable attempt,
up to `--max-training-rounds` (default 3). It starts from that lane's accepted
private candidate, or retains its prior parent after optimizer rejection.
`--max-batches` bounds optimizer attempts per cycle, including retries; pending
rounds resume in later cycles. It does not mean qualified spans per cycle.

When metrics pass but structural gates fail, further numerical training stops
for that span and a source-repair item is retained. If metric training exhausts
its budget, an additional training-repair item records the unmet gate. DuckDB
distinguishes `pending`, `qualified`, `needs_repair` and `training_exhausted`.
Failed/uncertain workers require explicit recovery; they are not silently rerun.

`progress/qualification.duckdb` stores attempts, lane parents, splits and status.
Only the coordinator writes it or the separate version registry. Qualification
JSON and repair envelopes are hashed into the existing artifact store. Local
`progress/repair-outbox/*.json` files carry source text, candidate version,
gate evidence and unchanged acceptance requirements for a later supervisor or
dataset publisher. They are not automatically submitted, executed or uploaded.
Checkpoint/head advancement and attempt disposition commit atomically. Resume
verifies the latest lane checkpoint closure and qualification evidence. No
registry release branch is automatically promoted. Optional qualified sparse
publication uses the registry's durable Hugging Face outbox, described below.

Each qualified result belongs to its recorded candidate version. Later training
in that lane has not requalified all earlier spans. A corpus-wide release still
needs an independent regression/qualification pass over its complete required
sample set. A generic prebuilt job may provide optimizer validation separately;
the runner checks the union of those rows and explicit qualification validation.

Optional local Arrow **feature weights** and shared target artifacts remain
supported by the existing worker. Mutable updates remain private and sparse;
DuckDB is the control plane, not the per-parameter training hot loop. The generic
qualification runner currently rejects mapped Arrow **embedding input** jobs
because their targets need a matching qualification resolver; explicit supplied
embedding vectors work. This prevents silently evaluating regenerated mock
vectors against a model trained on different targets. The CLI continues to use
`mock:stable-sha256` embeddings unless explicit vectors are supplied; such smoke
metrics are not pretrained semantic embedding quality evidence.

## Shared DuckDB, Quack and sparse publication

The operator runner requires the installed native Quack transport. One trusted
coordinator owns the DuckDB registry; concurrent numerical workers do not open
its database file. Scoped `ReadRun` and `ReadVersion` calls verify each registered
job/base before dispatch. Lease claims/renewals and candidate completion use
Quack. The owner independently verifies worker provenance and sparse replay
before authorizing a completion, then reads the exact candidate version back
through Quack. Ambiguous response recovery repeats the same checks. Concurrent
children remain separate immutable versions; parameter updates are not blindly
merged or applied to a shared mutable array.

The database holds versions, lineage, work/lease state and artifact references.
Immutable checkpoint/patch bytes live in the existing artifact store. Local
Arrow feature weights can be mapped by workers; mutable training updates stay
private. Quack is the control path, not the per-parameter numerical loop. The
existing DuckLake consumer remains a separate outbox destination; this change
does not create another catalog or claim a native DuckLake deployment test.

`--publish-repository justicedao/uscode-autoformal-span-cache` enables incremental
upload after qualification. A content-addressed plan is queued **before** the
attempt progress transaction commits. Delivery is separately retryable on a
later poll with zero new training. Only an exact native qualified candidate can
be staged; a flag in a DuckDB row is insufficient. The publisher verifies metrics,
all six syntax artifacts, source/pattern locks, and actual Lake build evidence.
It uploads the sparse dependency closure, qualification receipt, Lean source,
build log and minimal pinned Lake project under a language/variant/lane namespace.
Private predecessor patches are explicitly dependencies, not qualified releases.

Uploads append immutable paths in one Hub commit against the observed repository
parent. Exact existing content is idempotent; collisions fail. Post-commit file
hashes must match before the owner acknowledges the event. The runner promotes
neither a global model head nor a lane release head. Failed delivery remains in
the outbox. A compacted full candidate currently produces an explicit deferred
publication task: the publisher does not silently upload its full checkpoint.

Full baseline weights must already exist locally. Neither the runner nor sparse
publisher downloads weights. A sparse bundle therefore requires its exact local
anchor and is not a self-contained restore. Current Quack validation is local
loopback on one host. Cross-host artifact delivery and qualification are not yet
validated; multiple-machine dataset sharding does not imply synchronized model
weights. Periodic census polling and qualified sparse uploads are available, but
automatic cross-machine weight consumption remains deferred under the existing
no-weight-download constraint.

## Run and inspect

```sh
python3 scripts/ops/legal_ir/run_incremental_autoencoders.py \
  --state-directory workspace/test-logs/federal-corpus-audits/qualified-node-0 \
  --repository-id justicedao/uscode-autoformal-span-cache \
  --publish-repository justicedao/uscode-autoformal-span-cache \
  --validation-jsonl path/to/disjoint-validation.jsonl \
  --workers 2 --max-batches 4 --max-training-rounds 3 \
  --max-seconds 180 --lake-timeout-seconds 120
```

Use `--input-jsonl` for local spans. Use the same command to resume; periodic
Hub polling still uses `--polls 0 --sync-interval 300`. Missing validation produces
a failed validation gate and a data task, not an implicit in-sample pass. A
changed source/configuration/topology requires a new stream. Resource accounting
still uses the existing 75 GB campaign cap and whole-process-group CPU/RAM/disk
reservation. The archived restart12 checkpoint is read-only input.

Look at `qualified_batch_count` and `batch_status_counts`, not just completed
optimizer jobs. Each attempt has a qualification artifact with per-row metrics,
family formulas and parser diagnostics, Lean source/lock/build log, and repair
tasks. `admitted=false` and `formalized=false` remain the aggregate defaults;
successful Lean evidence appears only at its explicitly scoped Lake gate.

## Validation

The accompanying evidence report records native results and focused tests. Test
fixtures explicitly label injected training/qualification and cannot supply
native admission evidence. Native measurements use the canonical workspace tree,
five training bridge names (`modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, `external_prover_router`), provers off, one bridge worker, metric disk
cache off, and sample memory off. The qualifier's separate embedding-only
evaluation has bridges off and target count zero; its timing is never presented
as legal-IR evaluation performance. No whole-corpus qualification is claimed.

The [native verification](evidence/qualified-incremental-20260928/verification.json)
used two concurrent processes, three named synthetic gates, one previously
verified Hub census span (5 USC 8410), and one separate synthetic validation row.
Five optimizer attempts across three cycles dispatched **4, 1, 0** jobs and
finished with **one qualified**, **two needs-repair**, and **one training-exhausted**
span. The qualified item is the synthetic minimum-duration pattern, not an entire
U.S. Code section. The deadline stayed unqualified and non-renderable. The U.S.
Code and prohibition rows improved embedding reconstruction to cosine 1 / loss
0 but retained structural failures. Protected checkpoint SHA and size matched.

Training worker wall time was **9.115–17.211 seconds per span**; initial cold
bridge-on evaluation was **4.277–5.823 seconds per one-span evaluate**, with all
five named bridges, one bridge worker, provers off, disk cache off and targets
present. Subsequent line searches reuse process-local targets. Qualification
timings are recorded separately, including actual Lake builds. These are
diagnostic timings, not a controlled speed comparison with earlier sample sets.

The focused suite passed **456 tests** and the additional qualified
Arrow/shared-target continuation check passed. The numeric gate preserves the
raw cosine while clamping only floating-point overflow within eight ULPs of
±1; a native exact reconstruction returned 1.0000000000000002. The .72/.20
thresholds are unchanged and larger invalid values still fail.

These results cover the local registry qualification path. Shared Quack control
and incremental Hub weight publication are validated separately in the follow-on
integration receipts; they must not be inferred from these measurements.

## Native Quack and Hub result

The [combined verification](evidence/qualified-incremental-20260928/quack-hub-verification.json)
records a fresh two-worker run on the same four spans and one validation row,
with one bounded training attempt per span. The first poll dispatched four jobs;
the second dispatched zero and uploaded zero. Final dispositions were one
qualified synthetic minimum-duration fixture, two needs-repair spans, and one
training-exhausted deadline fixture. Real worker CPU overlap was observed.

The shared registry recorded actual native Quack calls: **4 ClaimRun, 4 ReadRun,
8 ReadVersion, 8 RenewLease, 4 CompleteRun**. It used installed DuckDB 1.5.5 and
pinned Quack/httpfs extensions, without installation or weight downloads.

The single qualified candidate's sparse closure and evidence were appended in
[Hub commit 95d61d0](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/95d61d0df697090f2100aa4b8e543e2ba20d046a).
All **12 files, 7,885,282 bytes** were verified at that immutable commit, followed
by durable outbox acknowledgement. Exact local replay matched the qualified
materialized checkpoint. The 25,895,338-byte restart12 anchor was excluded from
the upload and remained unchanged. No unqualified candidate was published, no
release head advanced, and no synthetic fixture was labeled statutory coverage.

Native worker wall time was **9.049–17.267 seconds per span**. Initial cold
bridge-on evaluation was **4.378–5.864 seconds per one-span evaluate**, with all
five bridges listed above, target count one, provers off, disk cache off, one
bridge worker, sample memory off. Later line searches reused process-local
targets. The complete first cycle took **149.769 seconds**, including gates,
Quack, artifact verification and upload. The no-training resume poll took
**27.073 seconds**, including checkpoint/evidence replay; it is not a free poll.
These timings are measurements of this small smoke, not a corpus throughput
forecast or a controlled comparison to the earlier three-sentence measurement.

The combined focused suite passed **137 tests**, including native Quack and
Arrow/shared-target continuation. A final ten-test CLI check passed after adding
the temporal bridge decompiler to orchestration source hashes. The native smoke
predates only that additional guard entry; its exact source fingerprints remain
in the retained cycle receipts.

The source audit found no missing pre-existing API on `origin/main`. Native
semantics nevertheless used the pinned **workspace** compiler, decompiler,
parser and formula builder, whose concurrent edits differ from main. Those
hashes are retained in qualification evidence. The separately edited modal
decompiler also participates in bridge targets. This feature publication does
not incorporate those unrelated changes or claim identical qualification
behavior on main. The external JevOps statement-lock dependency matches its
own main branch. A corpus release still requires fresh qualification against
its exact deployed sources.

# Hardware-aware training and preserved qualification

Training can reuse a bounded native process pool across qualified waves. Every
job reloads and verifies its own immutable parent checkpoint, constructs a fresh
model, and emits its own sparse candidate. It does not retain a prior model or
share mutable weights between processes. DuckDB retains one writer; workers use
the existing scoped Quack control interface.

The pool retains at most two processes and recycles after eight total jobs or a
change in dispatch width. Wider waves use fresh workers. Cross-job target caches
are cleared. Reused imports are reported as warm even when the target cache is
empty. Fresh workers remain the default: the measured full route did not improve.
`--reuse-training-workers` explicitly enables reuse; `--fresh-training-workers`
disables it. This choice can change on resume without changing lane placement
or training policy.

A full package source manifest is bound to the native cycle and saved stream
policy. It is checked before dispatch, around jobs and qualification, and when a
pool is replaced. A source update requires a new stream; recycling cannot adopt
a changed bridge as a new baseline. Existing source-lock, artifact, checkpoint,
validation-split and owner completion checks remain in force. This checks file
contents and pinned imports; it does not attest already-loaded bytecode.

## Hardware envelopes

The default 8 GiB group allowance permits at most five training passes or four
inference passes before CPU, process-slot, queue and storage limits apply.
Training budgets 1152 MiB per worker plus 2048 MiB for owner qualification;
inference budgets 1792 MiB per model/Lake/Lean pass plus 512 MiB for coordination.
These estimates follow observed process memory and include idle retained workers.

Training reserves `workers + 4` process slots; inference reserves
`3 * passes + 2`. The fleet budgets six slots for an outer controller and its
single-span inner trainer. Scheduler leases now receive those declared counts,
instead of always receiving one. Dispatch stays inside the acquired envelope.
These are cooperative estimates with polled RSS, not kernel quotas;
`process_slot_estimate_exceeded` records observed excesses.

The required initial inventory still runs before the child receives permission
to start work. The first periodic inventory now waits 15 seconds after that check
rather than immediately repeating it. Periodic and final accounting, the 80 GB
campaign cap, retained claims, and the 50 GB worker storage ceiling are unchanged.

## Optimizer evidence and logic fidelity

Opt-in evaluation profiles now separate target preparation, model metrics and
ontology capture. Target observations distinguish supplied/prepared/native
values, native builds, memory/disk hits and timeout fallbacks. Projection profiles
retain each evaluation's nested timing without counting it twice. Missing
source-decompiler metrics have explicit observation counts; legacy zero defaults
remain numeric defaults, without becoming evidence of reconstruction quality.
No objective, qualification floor, context window, temperature or backend changed.

F-logic temporal metadata now follows canonical atom indices. Reordering typed
20-day and 10-day records, or supplying metadata for only one atom, no longer
attaches quantities to the wrong duration. Qualification continues to parse exact
source-bound exports for FOL, deontic FOL, temporal FOL, deontic temporal FOL,
deontic cognitive event calculus and frame logic. Additive coverage metadata
states which fragment is represented: current temporal exports use duration
predicates, and current DCEC exports use a normative fragment. Syntax success
alone does not establish a full temporal, cognitive or event theory.

Metric floors, disjoint tuning validation, source round trip, six syntax gates
and actual `lake build Legal` remain required for candidate qualification.
Only the source-locked numeric theorem receives a Lake admit; the checkpoint,
IR row, compilation, text reconstruction and bridge target do not. A deadline
(`within_duration`) remains non-renderable. Empty vocabularies abstain. No
Constitution span is marked formalized or `roundtrip_ok`.

The autoencoder in this route emits learned embedding/head values, not legal text
or a complete formal program. Symbolic rules and family exports come from the
pinned compiler/decompiler pipeline. Qualification joins those distinct kinds
of evidence; a Lake success is not a proof of the neural weights.

## Native comparison and optimizer correction

The retained [evidence](evidence/autoencoder-hardware-optimizer-20260928) compares
four synthetic numeric spans in two balanced lanes, one separate tuning row,
and the protected restart12 checkpoint. Mock stable-hash embeddings were used.
This is a local pipeline experiment, not federal-law generalization evidence.

| Same-code, in-sample optimizer comparison | Fresh workers | Reused workers |
| --- | ---: | ---: |
| Full CLI wall time | 120.562 s | 124.571 s |
| Full wall time per input span | 30.141 s | 31.143 s |
| Coordinator dispatch time, two waves combined | 36.769 s | 35.078 s |
| Subsequent-job first bridge evaluation, one target each | 4.364–4.541 s | 1.206–1.209 s |
| Sampled peak group RSS | 3.363 GB | 4.240 GB |
| Qualified candidates | 3 / 4 | 3 / 4 |

Every job used `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`
and `external_prover_router`; provers were false, disk cache was 0, bridge
workers were 1, and sample memory was false. Every first evaluation had one
actual legal-IR target and one target-cache miss. Fresh processes began cold;
reused processes had warm imports and cleared target caches. Later line-search
evaluations warmed the process cache within each job. The entire route was 3.3%
slower with reuse, so it remains opt-in. Unallocated verification/accounting time
increased; the receipts do not establish a single function responsible for it.

Independent verification passed 913 checks: all four materialized candidate
hashes, parent chains, state identities, selected updates, numeric metrics and
qualification outcomes matched. It reparsed 96 exact family artifacts and
verified 16 recorded `lake build Legal` source/log seals. Whole bridge-document
target hashes differed and are disclosed separately; those envelopes are not
claimed byte-identical.

The same 22-day candidate failed the 30-day tuning row in both runs: cosine
0.1961161351 and reconstruction loss 0.3269660516, against unchanged 0.72/0.20
limits. All syntax, semantic and numeric Lake gates passed. The gate correctly
blocked this in-sample `decoded_embedding` update.

The runner now supplies existing disjoint tuning rows to the optimizer's native
candidate selection and rollback path, as well as final qualification. Gradient
updates still use only training rows. Shared-target artifacts must cover the
training/validation union and continue to fail closed when incomplete. This is
repeated tuning validation, not an independent held-out canary. Final-source
native validation results are recorded separately from the immutable comparison.

The final default run took 111.801 seconds (27.950 seconds per input span), with
four accepted one-epoch updates and two fully qualified candidates. The first
bridge-on evaluations took 4.435–4.586 seconds each, with one validation target,
the same five bridges, provers off, disk cache 0, one bridge worker and sample
memory off. Processes began cold. All eight
source/validation numeric Lake builds and all six syntax families passed.
The 30-day tuning cosine remained 1.0 and reconstruction loss 0.0 in every
candidate. The 22-day and 23-day training rows retained their earlier pre-update
errors: cosine 0.1961161351, losses 0.3779412368 and 0.3420032477. They remain
`training_exhausted` after the deliberately bounded single attempt, with durable
repair tasks, and are not eligible for qualified publication. The new selection
policy protects tuning quality; it has not solved these mock reconstruction
cases. Its timing is a separate measurement because selection data changed.

The independent final audit passed **384 checks**, replaying all four candidate
states, reparsing 48 family artifacts, and checking all eight Lake source/log
seals and the training/validation split.

The consolidated final readiness suite passed **680 tests**. The five-case text
pilot reports forward 0.920 and cycle 1.000; the three fixed gates and empty-vocab
abstention pass. All three owned reservations released, all historical ledger
records and retained claims stayed unchanged, and the protected seed SHA stayed
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

An isolated export of the prepared main sources passed **78 focused tests**:
44 family checks, 18 observability tests, 12 target-grammar tests and four
projection-profiler tests. The initial export omitted the canonical parity-policy
JSON and failed one integration assertion; restoring that exact Git blob fixed
the test without any code or assertion changes. These isolated source tests do
not constitute a new native checkpoint/Lake run. Independent prepared-source
checks also preserve all three fixed compiler gates, empty-vocabulary abstention,
and each five-case pilot score (forward 0.920, cycle 1.000). The initial evidence
script used the wrong enum spelling for abstention; the corrected script checks
`OperationStatus.ABSTAINED`, and both receipts are retained.

Native evidence is bound to captured workspace sources. The scoped main-branch
publication excludes unrelated concurrent semantic changes; its six differing
explicit dependencies are recorded in `source-scope.json`. These receipts do not
retroactively attest a clean main checkout or a multi-host/full-corpus campaign.

## Further optimization and opportunity cost

The previous profile put about 77% of optimizer time in the first bridge-on
evaluation and about 4% of worker time in projection batches. This favors reuse
of expensive initialization and verified shared targets before GPU kernels.
Existing immutable target bundles can serve repeated candidate versions; their
preparation, source validation and hydration must be charged in comparisons.

Existing Arrow support maps feature embeddings with private sparse overlays.
It still parses the full JSON checkpoint and is not whole-model zero copy.
Measure it against checkpoint loading and serialization before expanding that
representation. Sparse candidate updates are already active, with exact parent
and materialized-result identities; process reuse does not merge gradients or
change publication eligibility. The existing qualified sparse Hub outbox remains
the publication path. This comparison does not publish new model generations.

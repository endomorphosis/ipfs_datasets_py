# Verified shared targets in the U.S. Code daemon

Implementation qualification, 2026-09-25. The integration is opt-in. A complete
federal corpus, production DuckLake activation and Hugging Face publication
remain unfinished. The Constitution remains unformalized. Only an actual
`lake build <Lib>` constitutes a Lean admit.

## Implemented boundary

The [runner](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py)
accepts four all-or-none options: `--autoencoder-target-bundle`,
`--autoencoder-target-bundle-sha256`, `--autoencoder-target-bundle-bytes`, and
`--autoencoder-target-snapshot-id`. Paired execution forwards them only to the
autoencoder child. Existing default behavior does not require an artifact.

The [target session](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_target_session.py)
checks the immutable file, complete producer configuration and actual sampled
train/acceptance-validation union. It does not resample to fit a bundle. It
hydrates at most one current selection and reuses it only for identical source
and vector identities. A 256 MiB bound covers referenced encoded target bytes;
it is not a bound on expanded Python graph RSS.

Native bridge-enabled evaluation and projection receive the same complete
target mapping. Candidate predictions, losses, grammar and acceptance checks
still run. Aggregate evaluation lineage includes the artifact, producer and
selection identities. Explicit targets never reach bridge-off/base/core calls.
Bridge-off sessions do not open the artifact or inspect producer configuration.
Custom model methods, bounded sample clones and non-native targets retain the
whole-cycle live path, with the reason recorded.

Source, file and sample checks run at cycle boundaries before publishing the
current snapshot or enqueuing its checkpoint. A failed provisional cycle
suppresses the final clean-shutdown checkpoint. Shutdown checks provenance,
closes the target handle, and blocks final snapshot promotion on failure.
Already validated prior-state promotions, queued writes and TODO side effects
are not rolled back. These are boundary checks; edits that are made and
restored entirely between checks are outside the protocol.

The asynchronous snapshot evaluator and independent compiler/bridge diagnostics
keep their existing live target paths. No worker-only GC policy, reduced target
capsule, Arrow weight mapping, sparse candidate ownership or model promotion is
introduced into the daemon by this change.

## Qualification and measurement limits

Validation currently includes 335 distinct passing tests: 279 daemon,
bridge-reuse and target-session checks, 25 new runner integration checks, and
31 semantic gate/pilot checks. The broader suite also has one pre-existing
failure: its default-bridge assertion hardcodes six names while both the saved
pre-change runner and current runner return the registry's seven names. The
registry and that test were not changed to conceal the discrepancy.

The new integration tests use a synthetic consumer and session with the actual
runner and asynchronous checkpoint writer. They verify target delivery and
lineage, prior successful checkpoint retention after a later failing cycle,
snapshot suppression, and preservation of a shutdown provenance exception over
a secondary cleanup error. They establish orchestration behavior, not native
model throughput. The three required semantic gates and five-case pilot remain
green; compilation and these tests confer no admission.

The normal daemon loader still reads the remote U.S. Code dataset and constructs
mock embeddings when no vector is supplied. Its training reconstruction uses
sample memory; validation does not. `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0`
does not disable the separate compiler artifact cache. A benchmark must identify
these differences from the prior native-vector worker experiment.

The [native receipt](evidence/autoencoder_control_plane_plan/daemon-shared-target-native-20260925.json)
records one cold/live cycle followed by one shared-target cycle in fresh
processes, using the existing six source-bound records and private byte-exact
copies of restart12. A disclosed local loader adapter supplies those records;
sampling, evaluation, projection, diagnostics and persistence remain native.
Private evidence directories isolate the compiler cache. This harness does not
qualify an offline production CLI, full-corpus coverage or held-out generalization.

| Wall-time scope | Samples | Cold/live | Shared targets |
|---|---:|---:|---:|
| Initial training bridge evaluation | 3 | 28.754 s; 9.585 s/span | 3.852 s; 1.284 s/span |
| Initial validation bridge evaluation | 3 | 28.275 s; 9.425 s/span | 4.750 s; 1.583 s/span |
| Final training bridge evaluation | 3 | 2.002 s; 0.667 s/span | 2.035 s; 0.678 s/span |
| Final validation bridge evaluation | 3 | 2.485 s; 0.828 s/span | 2.699 s; 0.900 s/span |
| Independent bridge diagnostics, train + validation | 6 | 2.619 s | 50.736 s |
| Complete daemon call including durable shutdown | 6 distinct | 93.382 s; 15.564 s/span | 106.976 s; 17.829 s/span |
| Full child process including input checks/imports | 6 distinct | 102.676 s | 117.212 s |

Fresh preparation separately cost 60.135 s (10.022 s/span), including 50.305 s
of target generation. The artifact is 12,838,243 bytes, referencing 212,122,367
expanded encoded bytes. Shared hydration took 7.189 s and boundary guards
3.157 s. Observed lifetime peak RSS increased from 1,604,796 to 2,273,932 KiB
(41.70%). This pair was 14.56% slower for the complete daemon call before
charging preparation. The option stays disabled by default; there is no
demonstrated end-to-end speed or memory benefit for this daemon path.

All four persisted evaluation blocks matched except their explicit document
hash maps. Projection matched after excluding only its root elapsed clock and
before/after document-hash maps. Numeric metrics, grammar/rejection results,
independent adapter metrics and complete resulting state identities matched.
Both rejected the same single update and accepted zero epochs. Raw document
hashes remain unequal and unclassified: full cold graphs and capture triples
were not retained for comparison. Whole-daemon semantic equivalence is therefore
not claimed. Both guards and durable shutdown passed, with no source drift,
weight download, code synthesis, protected-checkpoint change, model promotion
or publication. Each private queue retained one pending guidance TODO.

The complete five-bridge list must remain explicit: `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router`. Report the
requested prover flag, worker count, both cache policies, sample count and
memory policy. A false prover flag does not disable every local proof operation.
Preserve cold generation, artifact loading and existing warm-cache measurements
as distinct costs. No daemon speedup is established by the worker measurements.

For this run, the requested prover flag was false, sample and adapter workers
were one, metric disk cache was zero, and compiler caches started empty in
separate directories. Every bridge-enabled evaluation had three targets.
Training sample memory was true; validation was false. Projection used the
ordinary CPU `native` backend, one epoch, one update family, one line-search
attempt and a 180-second limit. Existing warm passes within each cycle remain
in the timing table. OS cache state and host contention were uncontrolled; a
second warm daemon cycle was not measured.

## Opportunity cost and next boundary

An artifact pays generation and encoding once, then adds verified loading and
producer checks to each consumer. The complete first-use cost therefore includes
preparation; a shorter shared-target daemon call alone is not an end-to-end
first-run saving. Independent diagnostics impose a remaining compilation cost.
Frequent package edits invalidate the producer binding and can eliminate the
reuse opportunity. Keep the option disabled unless repeated compatible inputs
amortize those costs.

The measured next performance boundary is the independent report consumer:
initial evaluation saved 48.427 s, while later bridge diagnostics grew by
48.117 s. Source inspection explains the shift: native target generation warms
`multiview._MULTIVIEW_EVALUATION_CACHE`, and later diagnostics reuse those full
reports. Explicit targets bypass that cache. The runner's separate diagnostic
cache reports three misses per split in both arms, so those counters alone do
not expose the lower-level reuse. Cold diagnostic document hashes matched all
six optimizer document hashes; shared diagnostic hashes differed from the
artifact hashes.

Verify and share the complete reports needed by diagnostics, including
adapter status and failure telemetry, before expecting a daemon throughput gain.
Do not seed a diagnostic report cache with an incomplete training target or
fabricate successful diagnostic rows. Preserve this negative result when
qualifying the next change.

The next artifact needs the native `MultiViewLegalIRReport` fields used for
per-adapter round trips/losses, proof outcome counts, graph counts, view metadata
and explicit failures. Bind a versioned bounded report shard to its derived
target bytes, exact sample/vector membership and the complete producer settings.
Pass verified reports through an explicit diagnostic input, retain the existing
aggregation code, and record artifact reuse separately from ordinary cache hits.
Keep unsupported consumers on the existing whole-cycle path. The subsequent
[full-report handoff](autoencoder_daemon_shared_reports.md) implements this
boundary with a separate bounded native DAG codec; its qualification is recorded
there without replacing this negative target-only measurement.

One bounded bundle does not make random full-corpus sampling scalable. Current
selection must be covered exactly or the cycle fails. The next integration
needs verified corpus/vector inputs and partitioned target inventory under the
existing owner/job manifest, followed by sparse candidate acceptance. It must
preserve legal/source split membership rather than quietly sampling whatever
fits a cache. Arrow and additional parallel workers should be selected from
complete-cycle wall time and measured memory capacity after that input boundary
is qualified.

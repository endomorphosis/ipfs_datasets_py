# Coordinating source changes during autoencoder runs

Concurrent edits previously invalidated a two-worker smoke after both workers
accepted an epoch. The full-package provenance guard correctly rejected the
changed source. This change keeps that guard and gives each run one explicit,
immutable source generation at the original canonical paths.

## Integration protocol

1. Prepare changes in separately owned, resource-accounted Git worktrees. Each
   contributor supplies immutable commit IDs. Do not edit a running capsule or
   copy an entire dirty checkout onto `main`.
2. `merge_autoencoder_source.py plan` computes a three-way merge from an exact
   base and candidate commits. Conflicts are recorded and require a new reviewed
   candidate. Planning changes no branch, ordinary index, or checkout file.
3. `apply` reproduces the exact plan, validates its merged tree in a detached
   worktree, and compares-and-swaps only `refs/autoencoder/integration/<lane>`.
   A stale base, failed validator, resource failure, or conflict prevents that
   update. A source integration receipt is not model qualification or Lean
   admission. Publication to `origin/main` remains a separate reviewed action.
4. Source capture takes a shared source lease. Integrations and the existing
   supervisor main-apply path take the corresponding exclusive lease. Linked
   worktrees use the same primary-checkout lock. A crash releases the kernel
   lock; no stale-PID expiry deletes another owner's reservation or evidence.
5. Once a canonical source generation is captured, run target preparation,
   training, and qualification inside that same capsule. Later host merges
   affect future generations. Existing jobs keep the source bytes they started
   with.

The lease is cooperative. Direct editor writes can bypass it. Capture compares
the complete inventory before and after copying and refuses inconsistent
captures. Running capsules use read-only mounts, so later host checkout edits
cannot alter their source. Direct runs outside the frozen launcher retain their
existing fail-closed provenance guards and can still be invalidated by edits.

## Source integration commands

From the canonical datasets checkout, use full commit IDs and a new plan path:

```bash
python scripts/ops/legal_ir/merge_autoencoder_source.py plan \
  --base FULL_BASE_COMMIT \
  --candidate FULL_CANDIDATE_COMMIT \
  --integration-ref refs/autoencoder/integration/training \
  --output /ABSOLUTE/NEW/merge-plan.json

python scripts/ops/legal_ir/merge_autoencoder_source.py apply \
  --plan /ABSOLUTE/NEW/merge-plan.json \
  --plan-sha256 REVIEWED_PLAN_SHA256 \
  --output-directory /ABSOLUTE/CHARGED/NEW/merge-validation \
  --max-checkout-bytes 1300000000 \
  --validation-timeout-seconds 300 \
  -- /ABSOLUTE/PYTHON -m pytest -q PATHS_TO_RELEVANT_SOURCE_TESTS
```

The checkout bound is explicit because this repository's tracked tree exceeds
1.1 GB. Apply uses the existing campaign resource ledger, reserves explicit
checkout/log bounds, and checks actual temporary usage. Tracked symlinks remain
intact, separately from strict receipt inventory. The validator is an explicit
trusted command, without a shell. Its receipt states which checks ran. Require
the validator to assert that imported module paths lie beneath
`AUTOENCODER_VALIDATION_SOURCE_ROOT` and that `HEAD^{tree}` matches
`AUTOENCODER_VALIDATION_GIT_TREE`; the recorded validation harness does both.
Canonical native training and formalization
must use the frozen canonical-path launcher below, not this detached source-test
checkout.

## Frozen canonical source

```bash
python scripts/ops/legal_ir/run_frozen_autoencoder_source.py prepare \
  --output-directory /ABSOLUTE/CHARGED/NEW/source-capture \
  --resource-ledger /ABSOLUTE/EXISTING/disk-reservations.json \
  --extra-python-file /ABSOLUTE/WORKSPACE/run_harness.py

IPFS_DATASETS_PY_SYMAI_PREFIX=/ABSOLUTE/CHARGED/OUTPUTS/symai-config \
python scripts/ops/legal_ir/run_frozen_autoencoder_source.py run \
  --manifest /ABSOLUTE/CHARGED/NEW/source-capture/capsule/manifest.json \
  --sha256 CAPTURE_MANIFEST_SHA256 \
  --run-directory /ABSOLUTE/CHARGED/OUTPUTS/new-launch \
  --writable-directory /ABSOLUTE/CHARGED/OUTPUTS \
  --writable-directory /ABSOLUTE/EXISTING/LEDGER_PARENT \
  --writable-directory /tmp \
  --resource-ledger /ABSOLUTE/EXISTING/LEDGER_PARENT/disk-reservations.json \
  --tmp-directory /ABSOLUTE/CHARGED/OUTPUTS/tmp \
  --timeout-seconds 1200 \
  -- /ABSOLUTE/PYTHON /ABSOLUTE/WORKSPACE/run_harness.py
```

Create the output and temporary directories first. Capture and runtime output
directories must be distinct; the capsule cannot sit inside a writable runtime
directory. The launcher permits a writable harness parent only when the
captured Python harness itself is overmounted read-only.

The capsule contains the datasets package and its resources, legal-IR scripts,
the JevOps package, and explicitly named Python harnesses. It excludes compiled
Python bytecode and model weights. It records the actual dirty source contents
and Git provenance; `HEAD` alone is not presented as the source identity. The
existing internal webfont alias is materialized from verified font files;
other source aliases fail closed.

Rootless Docker uses an already cached image pinned by digest, `--pull=never`,
and no network. It mounts source at the original absolute canonical paths and
verifies the existing compiler/decompiler/parser tree pin. The backing capsule
is also read-only inside the container. The host owner could deliberately
modify backing files; content guards remain enforced. This is concurrency
isolation, not a security boundary against the host owner.

The launcher verifies host PID and process-group identities, stable control
paths, and the exact host scheduler path before starting the command. `/tmp` is
explicitly writable because the existing shared scheduler atomically replaces
its state file. The container's mapped UID must not select a separate scheduler.
Child training commands keep their existing resource reservations and deadline
checks. Only the uniquely owned container is stopped on timeout or interruption.

Each runtime also has a private 64 MiB `/dev/shm` tmpfs, charged within the
wrapper's 1 GiB memory reservation. Before launching work, a real spawned child
exercises a multiprocessing queue and lock; the launcher reaps that child and
its newly created resource tracker. The wrapper reserves four child slots.
This corrects the read-only semaphore failure found in the second native
attempt without sharing or modifying the host's shared-memory filesystem.

Keep the optional SyMAI import configuration in that owned writable prefix.
The first full frozen preparation correctly rejected all eight targets because
the fifth bridge could not initialize configuration on the read-only filesystem.
Investigation also found that installed SyMAI 1.14 assumes
`multiprocessing.pool` was already imported. The existing managed-import helper
now explicitly imports that standard-library module before SyMAI. This changes
neither engines nor prover policy. A cold one-sentence target probe then accepted
all five bridges; it was not an autoencoder evaluation or an admission.

## Unchanged acceptance criteria

Only an actual source-locked `lake build Legal` admits a supported Lean unit.
Compiler success, syntax checks, training acceptance, targets, loss improvements,
source validation, and integration refs do not admit federal laws. All metric,
semantic, logic-family syntax, Lake, split, and source-provenance checks remain.
The Constitution is not formalized. No new weights are downloaded and no
independent canary or eight-hour run is authorized by source integration alone.

The final source integration `02d5739d5fd83b49da920d1448b598c45d243071`
passed 125 focused tests in 11.23 seconds (26.33 seconds for its validator
process, including startup and resource checks). Its internal ref advanced by
compare-and-swap and its reservation was released. The eleven changed files
match the reviewed source bytes.

The native smoke uses captured canonical workspace generation
`34fc62aecb04268df738537be603978a5069d19fee5e17168c534836cb8416af`,
containing 10,009 files and 393,809,638 source/resource bytes. That generation
includes 18 pre-existing Python differences and three extra Python files
relative to the integration tree. The native result therefore applies to that
explicit workspace generation. Isolated source tests validate the Git
integration separately. Those pre-existing edits remain preserved for review.

## Completed native smoke

The frozen workflow completed in **293.15 seconds**, including target
preparation, planning, structural patch sizing, and the bounded two-job smoke.
Both workers verified the same eight shared targets and unchanged full-package
producer manifest. The container exited successfully and was removed. These
observations validate execution against the captured workspace generation;
they do not assert native qualification of the separately tested Git tree.

All timings below use the five bridge names `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec`, and `external_prover_router`.
External provers are disabled, the metric disk cache is off, sample memory is
disabled, and one legal-IR target worker is requested. Target generation
bypassed process caches; OS caches were uncontrolled. Evaluations reuse the
verified target bundle, so they use zero native target-generation workers.

| Measurement | Samples / targets | Wall seconds |
| --- | ---: | ---: |
| Cold native target generation | 8 / 8 | 115.53 total; **14.44 per span** |
| Preparation driver including encoding, supervision and checks | 8 / 8 | 154.27 |
| Bridge-on training-set evaluation, fixed / productive | 6 / 6 each | **9.31 / 9.27** |
| Bridge-on initial tuning evaluation, fixed / productive | 2 / 2 each | **2.15 / 2.12** |
| Bridge-on line-search tuning evaluation | 2 / 2 each | **1.53–1.55 per evaluate** |
| Accepted training call, fixed / productive | 6 train + 2 tune each | 19.34 / 19.30 |
| Whole worker, fixed / productive | same split | 40.80 / 39.48 |
| Two-worker dispatch | 2 jobs | 46.46 |

This is a source-isolation smoke with a fresh 384-dimensional model and
verified local semantic embeddings. It is not a speed comparison against the
archived eight-dimensional restart12 checkpoint. The checkpoint's protected
SHA256 remains `1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

Each worker accepted one epoch and persisted a replay-verified sparse update
of about 15.37 MB. Both materialized checkpoints have identical weight bytes.
The raw decoder tuning cosine increased from 0.196116 to 0.242829 and raw
reconstruction loss decreased from 0.00252708 to 0.00250273. The separate
input-dependent safety projection reports cosine 1 and loss 0; that is not
evidence of perfect learned reconstruction or formalization. These jobs used
private JSON weights and sparse transport through the control plane; this run
does not validate Arrow-backed training or Hub weight synchronization.

All three deterministic semantic fixtures passed, including empty-vocabulary
abstention, preservation of the exception and ten-day deadline, prohibition,
and the correctly rendered twenty-day minimum duration. Only that last
supported numeric theorem ran and passed an actual `lake build Legal`.
The `within_duration` fixture remained non-renderable.

Both real-law candidates remained **unqualified**. Six of eight rows failed
complete source semantic coverage; two yielded no parser elements. The
logic-family coverage and source-locked Lake gates failed on all eight rows.
All 66 individual family syntax projections in each candidate parsed; the
aggregate family gate rejected incomplete semantic coverage. Real-law Lake
checks stopped at the semantic prerequisite, so none reached a Lake build.
The metric and repeated-tuning checks passed, but no independent canary ran,
no weights were promoted or uploaded, and the eight-hour training gate stayed
closed. The next model-quality work must address those recorded coverage and
renderer gaps while preserving these gates.

The stage's existing overlap lower bound records zero; it alone does not prove
overlapping training. The source-bound post-run concurrency audit proves at
least **11.816 seconds of overlapping training calls**: their summed durations
38.635544 s, plus the earliest possible start after 20.086770 s of preparation,
minus the enclosing 46.906317 s wave interval. Training calls include model
evaluations; this does not measure simultaneous optimizer inner-loop CPU work.
The original stage receipt remains unchanged.

The final resource audit found all 187 pre-existing reservation records
unchanged and all new reservations released. It retained failed-run
artifacts and observed 2.26 GB of capacity below the existing 85 GB campaign
cap. A capsule costs about 394 MB per generation; reuse one generation across
its target preparation and worker jobs rather than capturing per candidate.

Evidence is in
[`evidence/autoencoder-source-integration-20260929`](evidence/autoencoder-source-integration-20260929),
including `final-source-validation.json`, `final-publication-audit.json`,
`native-summary.json`, `native-semantic-fixtures.json`, and
`final-resource-audit.json`. Large capsules, target bundles, weights, and local
runtime configuration remain outside Git.

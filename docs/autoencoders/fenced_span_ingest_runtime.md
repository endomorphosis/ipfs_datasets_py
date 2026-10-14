# Native-owned fenced span ingestion

Use `scripts/ops/legal_ir/run_fenced_span_ingest.py --spec /absolute/path/spec.json`
for the bounded, resource-owned `fenced-v1` ingestion path. The spec schema is
`span-fenced-runtime-spec/v1`; unknown or missing fields are refused. This path
consumes an existing owner-prepared span cache and source manifest. It does not
enqueue a corpus, train or execute a learned checkpoint, upload to the Hub, or
dispatch supervisor goals. Those operations retain their separate interfaces.

The compiler, decompiler, and parser must load from
`/home/barberb/lift_coding/external/ipfs_datasets`. An isolated development tree
can test storage and control contracts; it cannot stand in for canonical
inference. The launcher refuses a process that already imported a different
datasets tree. Do not repair that process by deleting imported modules.

## Inputs and ownership

| Spec fields | Required preparation |
| --- | --- |
| `cache_path`, `source_manifest_path`, `release_id` | Existing cache plus an exact source manifest with revision, source hashes, and expected revision/hash bindings. Native claim generations are separate custody fields. No revision is inferred. |
| `resource_ledger_path` | Existing native disk ledger with the exact current schema, cap and storage-root identities. All retained claims still count. |
| `scheduler_state_path`, `expected_scheduler_policy_sha256` | Existing native scheduler and the SHA-256 of its exact stored policy. No initialization, normalization or policy reconfiguration. |
| `attempt_directory` | Existing empty directory under one of the ledger's roots. Every new exchange, worker report, log, temporary Lake package and spill file goes under this attempt. |
| `storage_bytes`, `cache_growth_allowance_bytes` | One whole-attempt reservation and one immutable allowance for growth of the external prepared cache, WAL and default spill directory. The allowance must leave room for attempt artifacts. |
| `memory_mb`, `cpu_slots`, `child_process_slots` | The complete requested native resource envelope, subject to existing admission and host pressure checks. |
| `max_workers`, `per_worker_memory_mb`, `per_worker_process_slots` | An upper bound and explicit estimates for capacity planning. They cannot override the granted envelope. |
| `batch_size`, `max_spans`, `start_index`, `max_examined` | Bounded incremental selection and a cursor in this exact manifest. The batch is at most 32; selection and examination are each at most 4,096. |
| `timeout_seconds`, `full_usage_interval_seconds` | A bounded run deadline and cadence for a fresh full native storage census. Lightweight heartbeat, group and attempt checks run between full censuses. |

All paths in the spec are absolute. The prepared cache is outside the attempt
and inside the existing ledger roots. Do not copy an active DuckDB database to
prepare an attempt. The coordinator owns the sole cache connection; spawned
workers receive span payloads and never inherit that connection. The current
fenced coordinator uses the native cache interface. Existing Quack transport
and cross-machine exchange are separate tested interfaces; this command does
not claim to have run them.

## Launch, deadlines and limits

The external controller holds `DaemonResourceReservation` and the native
`HAMMER_LEAN` lease. Before opening the cache, the isolated coordinator verifies
the live parent and child birth identities, lease and reservation scopes,
exact launch digest, storage roots, source pins and temporary-directory
bindings. The coordinator receives a lease identity, never its lease key.
Workers do not acquire duplicate root reservations.

The coordinator and spawned workers use an initially empty, attempt-local
Python bytecode prefix with bytecode writes disabled. This avoids reading an
ambient cache after a deployment while retaining canonical source origins.

The capacity plan reserves coordination overhead and at least three process
slots per spawned compiler worker. The resulting `2 + 3 * workers` process
count is a floor: Lake and toolchain descendants can exceed it. Actual overflow
refuses the attempt. `LEAN_NUM_THREADS=1` bounds that environment setting;
there is no claim of a kernel CPU, memory or process quota. RSS observations
conservatively sum resident pages and can count shared pages more than once.

Four available process slots cannot fit even one spawned worker on this path.
Zero capacity must defer before opening the cache or pool. Requesting more
workers does not raise the scheduler policy or suppress proof-pressure checks.

The parent monitors while pool work blocks, including during launch delivery,
and stops the recorded process group on cancellation, timeout or refusal.
Group cleanup also covers surviving descendants after the coordinator exits.
Polling is cooperative; this is not a crash-proof kernel containment boundary.

DuckDB's constructor opens the existing catalog before the coordinator can
configure its attempt spill directory. Default cache-side `.tmp` growth is
therefore separately observed and charged. The report explicitly states that
spill redirection during construction is not guaranteed. The base catalog's
device/inode identity is bound; legitimate WAL/spill rotation is permitted.

## Resume and evidence

Keep each completed attempt directory. A later attempt can reuse retained
evidence only after checking the current source binding, code/path hashes,
native completion receipt, exact artifact hashes and allowed storage roots.
Historical evidence is read-only; all newly staged evidence belongs to the
new attempt. Legacy terminal rows, altered artifacts and stale claims remain
held rather than being promoted or silently regenerated.

Complete worker JSON and census/goal exchange artifacts precede native fenced
completion. `census-report.json` retains the complete completion census;
`child-report.json` is a bounded reference with counts and non-admission flags.
The parent verifies the full report with a streaming hash within its storage
reservation rather than loading the entire JSON. No evidence is truncated.
Failures retain their disk reservations and available artifacts. The fenced
helper releases only its exact still-live span claims during failure cleanup.
Strict finalization releases the reservation only after the owned group is
stopped, artifacts are durable and fresh accounting remains within the caps.
It is not an automatic retry or a storage-ledger reset.

If reservation admission itself fails, the native disk ledger and launcher
refusal are the available evidence. No controller-body attempt receipt is
claimed; writing a new artifact before obtaining its storage authority would
not establish a completed attempt.

The current worker records deterministic modal-codec observations and real
compiler/decompiler output. Agreement is diagnostic and not independent learned
decoder validation. A compile, decompiled sentence, loss, bridge target or
database row confers no admission. Only an actual source-scoped
`lake build <Lib>` is a Lean admit. A Lake fixture receipt does not formalize a
source span. The Constitution remains unformalized.

See [control_plane_and_sync.md](control_plane_and_sync.md) for exchange,
ownership and checkpoint synchronization, and
[full_logic_reports.md](full_logic_reports.md) for full output evidence. Native
Intent/Security observations use the supervisor's separate
`proof/native_formalization_profile.py`; operational admission additionally
requires the existing owner-backed material resolver and independent verifier.

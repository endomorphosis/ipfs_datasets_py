# Owner-verified invocation control through the Quack prototype

This slice connects remote control requests to the existing owner-managed
invocation boundary. A caller selects an already prepared run by immutable
request descriptor. The owner retains execution, resource admission, leases,
independent candidate verification and completion. Native training validation
and live native transport validation are deferred; the verification scope here
is local control dispatch and explicitly synthetic child fixtures.

## Two separate command profiles

The [gateway](../../../ipfs_datasets_py/duckdb_control/autoencoder_quack.py)
accepts an optional actual `OwnedInvocationControl` tied to the same registry,
worker identity and assigned run set. This profile permits only
`SubmitOwnedInvocation`, `ReadOwnedInvocation` and `ResolveOwnedInvocation`.
All three carry just `run_id` and `request_artifact`; submission and resolution
use the exact original wire operation ID. The caller cannot supply paths,
arguments, resources, leases, candidate bytes, result assertions or callbacks.

The generic worker profile remains available for its original synthetic and
generic registry use. It refuses mutations for owned-daemon request schemas
and training jobs with `job_spec_artifact`. Those jobs require independent
owner verification before completion; a scoped remote caller cannot bypass it
through generic `ClaimRun`, `RenewLease` or `CompleteRun`. The owned profile
also rejects those commands outright.

Submitting a run records durable acceptance; it does not start a training
process or return a completion result. The owner invokes `execute_pending`
outside the gateway pump. Its bounded executor calls the existing
`run_owned_daemon_invocation`, preserving the sealed request, resource policy,
network-denied daemon/verifier children, exact evidence staging and authoritative
full-checkpoint completion. Status and operation replies remain bounded control
records. Numeric weight reads, shared target hydration and sparse updates stay
in their existing local paths.

The [owner controller](../../../ipfs_datasets_py/duckdb_control/autoencoder_owned_control.py)
uses the existing DuckDB operation table. A deterministic owner/run binding and
the submission commit in the same transaction; primary-key status lookups avoid
scanning unrelated operation history. There is one selected
wire submission per run. Start and finish records use separate deterministic
control IDs. No registry DDL or outbox-consumer schema is changed. Constructor
inputs freeze the complete prepared handle, actual request descriptor, worker
scope and owner database/artifact paths.

## Recovery and wire identity

Wire submission identity, durable control identity and the coordinator's own
completion operation identity remain distinct. A transport timeout is not
permission to choose a new operation ID, lease or attempt. A committed
submission remains a historical acceptance receipt; current status is a
separate read. Missing resolution means no matching committed control record
was observed, not rejection, cancellation or authority to rerun a job.

The owner executor records its start before invoking the coordinator. After
interruption, a committed coordinator completion can be resolved without
rerunning training. An unresolved prior start requires recovery and is not
silently relaunched. The coordinator's existing quarantine and pending exact
completion rules remain authoritative.

The [wire codec](../../../ipfs_datasets_py/duckdb_control/autoencoder_quack_wire.py)
binds each response to the complete canonical request digest and request ID.
It enforces closed envelope fields, exact false admission/qualification flags,
finite JSON numbers, unique keys, bounded nesting and existing command/reply
byte limits. Malformed, substituted and unbound diagnostic replies are rejected.
An error response can follow a committed mutation and therefore never proves
that the mutation did not run. The prototype requires matching updated client
and gateway implementations.

## Cost and deployment limits

Control-plane submission and status reads add small durable records instead of
remote parameter access. Execution does not hold a gateway pump call or a
database transaction across training. This preserves responsiveness and keeps
long-running work within the existing owner resource policy. Parallelism stays
explicitly bounded; creating a queue does not establish a memory or throughput
gain, and Arrow remains optional under the existing parity and performance
gates.

The first concurrent fixture exposed a real owner-path issue: the resource
reservation used the same zero timeout for scheduler admission and the shared
disk-ledger lock. One job could fail before `ClaimRun` despite available CPU and
memory. The [reservation](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py)
now accepts a separate optional ledger-lock timeout; existing callers inherit
their previous timeout unless they opt in. The
[owned invocation](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py)
uses five seconds for ledger bookkeeping while scheduler admission remains
zero-wait. Quotas, retained failed reservations, file-identity checks and lease
rules are unchanged. This permits brief serialization of ledger updates without
relaxing capacity checks or retrying a started computation. A contended ledger
acquisition can add up to five seconds of waiting; native cost remains unmeasured.

The owner must schedule and retain the explicit executor for work to run;
acceptance alone does not promise eventual execution. An interrupted start may
require quarantine or an explicitly prepared replacement run. No production
service, cross-host worker, remote artifact transfer or automatic retry policy
is introduced by this slice.

The existing transport is a loopback, plaintext, token-scoped prototype with
pinned installed extensions. A polling timeout does not bound a blocking native
SQL call. Live Quack listener tests remain separately gated, and no listener is
started by these deferred-validation checks. Production DQK activation,
cross-host transport, full-corpus qualification, held-out learning and the HF
upload consumer remain separate work. No database or transport receipt is an
admit; the Constitution remains unformalized and only `lake build <Lib>` can
provide Lean admission.

## Verification

The [owner-control capture](../../../workspace/test-logs/federal-corpus-audits/autoencoder-owned-control-20260925/control-r2-receipt.json)
passes all 29 [checks](../../../tests/unit/duckdb_control/test_autoencoder_owned_control.py)
in 24.74 seconds pytest / 25.644975 seconds wrapper. These use the real prepared
request, registry, coordinator journal, resource reservations, compact codec and
CAS, with the child boundary explicitly synthetic. A barrier requires two
same-base executions to overlap before either continues. Other cases cover
one-job failure isolation, independent versions without head promotion, duplicate
submission during execution, owner restart, exact completion recovery with
missing files, interrupted-start refusal, scope isolation and generic-command
bypass rejection. The first capture retained 26 passes and three failures: two
exposed the shared-ledger contention above; the third was a test-helper keyword
collision corrected without relaxing the gateway schema checks.

The [wire checks](../../../tests/unit/duckdb_control/test_autoencoder_quack_wire.py)
pass 58 cases, including the actual client and gateway pump through fake
connections. They cover substituted request bindings, malformed/unbound errors,
bounded oversized-reply fallback and exact valid-result preservation. This is
not evidence that the native transport ran.

The [new ledger-contention checks](../../../tests/unit/optimizers/logic_theorem_optimizer/test_daemon_resource_lock_contention.py)
and existing resource suite pass 68 cases: 19 new and 49 existing, in 4.08
seconds. Independent real file descriptors force both reservation threads to
observe ledger contention before they proceed; both then hold real scheduler
leases concurrently with capacity admission timeout zero. Tests also retain
bounded denial, old omitted/`None` behavior, invalid-value rejection and refusal
when CPU capacity is already occupied. A first test expected the structural
capacity exception for temporary exhaustion; it was corrected to the existing
`LeaseTimeoutError`, with no production change.

These checks do not run native training, external provers, weight downloads,
production activation or uploads, and their elapsed times are not legal-IR
inference or training speed measurements.

The [combined source-guarded capture](../../../workspace/test-logs/federal-corpus-audits/autoencoder-owned-quack-20260925/combined-r1-receipt.json)
passes **360 tests with two explicitly gated live-listener tests skipped**, across
10 files, in 73.69 seconds pytest / 74.833098 seconds wrapper. It includes the
existing registry, resource, invocation and operation-journal suites plus the
legal semantic gates and roundtrip pilot. All 7,742 canonical package Python
sources, selected tests, and protected checkpoint/receipt hashes remained
unchanged. This is fixture and storage qualification at the recorded revision;
it does not substitute for the deferred native training or listener run.

# Resource-aware proof execution

The default proof safety profile uses the existing process-safe, file-backed
resource scheduler. Every participating Hammer client must use the same state
path and configuration. Default execution paths cover the datasets Hammer
portfolio, nested resource leases, and the canonical native Lean, Rocq, Isabelle
and TLC adapters. Coverage of setup operations and other prover entry points
is listed below.

## Default activation

New workers on Linux automatically select the safety profile when constructing
`GlobalResourceScheduler()` or calling `get_global_resource_scheduler()` without
an explicit config. Set a shared private state path before starting workers:

```sh
export IPFS_DATASETS_RESOURCE_SCHEDULER_PATH=/tmp/ipfs-proof-resources.json
```

Alternatively, configure the scheduler explicitly in each worker:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    ResourceSchedulerConfig,
    configure_global_resource_scheduler,
)

scheduler = configure_global_resource_scheduler(
    ResourceSchedulerConfig.for_proof_host(
        state_path="/tmp/ipfs-proof-resources.json",
        max_waiting_requests=256,
    )
)
```

Use a private writable state location in deployments. Workers must agree on
capacity and policy. Switching policy while leases or waiters are active raises
a configuration error; drain participating workers before changing it. Do not
delete an active state file. An explicitly supplied legacy config keeps its
existing admission behavior, regardless of the environment switch. Operators
can explicitly select legacy defaults with `IPFS_DATASETS_PROOF_RESOURCE_SAFETY=0`.
The safe SMT/ATP portfolio supplies a 1024 MiB default per-solver memory budget,
capped at the configured lane's usable memory capacity, when no limit is supplied.
Interactive prover and JVM budgets are not assigned this SMT-sized default.

## Admission policy

- Detect CPU affinity and visible cgroup-v2 ancestor CPU quotas.
- Allocate 80% of detected CPU capacity, rounded down, with at least one slot.
- Allocate 80% of host/container memory and preserve the remaining 20% as live
  headroom. Container `memory.high` and `memory.max` both constrain capacity.
- Cap environment capacity settings at detected safe defaults. Explicit Python
  overrides are operator policy and should be reviewed before increasing them.
- Reserve approximately one eighth of CPU slots for the `validation` lane on
  machines with more than one proof slot.
- Require positive memory reservations for root and child leases.
- Check live available RAM against headroom plus outstanding root envelopes.
  Envelopes are conservatively treated as unallocated even when their workers
  already occupy RAM. This can reduce concurrency; it avoids spending the same
  free RAM repeatedly during bursts of admissions.
- Block new root and child launches when Linux PSI avg10 reaches 2% full memory
  stall, 50% some CPU stall, or 10% full I/O stall. Missing optional PSI is zero;
  unavailable required memory telemetry blocks admission.
- Record a shared two-second backoff after pressure is detected. All clients
  of the state file, including child leases, honor it. Waiting callers sleep
  for up to one second between checks during backoff, honor cancellation and
  deadlines, and resume automatically only after cooldown and a fresh healthy
  sample. Persistent external load renews the backoff. The scheduler snapshot
  exposes `proof_backoff` with its reason and wall-clock expiry.
- Bound the admission queue to 256 waiters. A full queue raises
  `ResourceUnavailableError`; callers should retry with bounded backoff rather
  than creating more threads. Ordinary acquisition remains cancellable and
  honors its configured timeout.

Memory reservations include tool overhead, libraries, proof inputs, and working
state. A worker must stay within its reservation. These admission checks do not
kill existing jobs when external load increases.

## Hammer budgets

Override the default memory budget for each solver through `HammerPolicy` or
`solver_budgets`. For example:

```python
from ipfs_datasets_py.logic.hammers.models import HammerPolicy
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy

policy = PortfolioPolicy(
    hammer_policy=HammerPolicy(
        allowed_solvers=["z3", "cvc5"],
        timeout_seconds=10,
        memory_mb=1024,
    ),
    max_parallel_processes=8,
)
```

The safe portfolio reduces its width to fit configured CPU, process, lane, and
memory capacity. Individually oversized budgets fail before solver execution.
The standard bounded process runner already passes these
memory budgets to process limits; on POSIX this includes `RLIMIT_AS`, a virtual
address-space limit per process. Custom process runners must enforce equivalent
limits themselves.

This is not aggregate process-tree memory containment. JVM and interactive-prover
workers need tool-specific sizing, native thread limits, and eventually cgroup
memory containment. The proof profile does not yet integrate every legacy
entry point or the accelerate supervisor's separate resource lease implementation.

## Direct prover execution

`ResourceAdmittedToolRunner` is selected by default by `LeanKernelBackend`,
`RocqKernelBackend`, `IsabelleKernelBackend`, `TLCBackend`, and `ApalacheBackend`. Each invocation
reserves resources in the shared validation lane. Construction and inherited
executable lookup do not initialize scheduler state; execution resolves the pool.
Admission waiting, workspace preparation and execution share one deadline.
Cancellation revokes waiting or running work, and the lease is released after
the bounded subprocess lifecycle returns and cleans up. Cleanup errors propagate
instead of claiming successful cleanup.

The runner requires an explicit finite memory limit, using the requested RSS
ceiling before the virtual address-space ceiling and rounding up to MiB. It
refuses oversized requests without reducing their declared resources. Existing
pressure sampling and shared backoff apply to these root and child admissions.
Backoff pauses new launches; it does not throttle work already running.

| Adapter | Default reservation | Runtime sizing |
| --- | --- | --- |
| Lean | 1 CPU, 1 process, requested RSS | `-j1`; 64 MiB worker stacks; early runtime worker/stack settings; 4 GiB address-space floor |
| Rocq | 1 CPU, 1 process, requested address space | Batch `coqtop` invocation |
| Isabelle | 3 CPU, 12 processes, requested RSS | Existing single-worker Java/ML profile and 32 GiB address-space floor |
| TLC | 1 CPU, 1 process, requested RSS | `-workers 1`; existing 4 GiB address-space floor; launcher must size JVM heap and helpers |
| Apalache | 1 CPU, 3 processes, requested RSS (minimum 256 MiB) | Heap uses half the RSS budget; serial GC; isolated runtime config; 4 GiB address-space floor; bounded JNI extraction |

Lean's managed profile sets `LEAN_NUM_THREADS`, `LEAN_STACK_SIZE_KB=65536`,
`LEAN_MAIN_USE_THREAD=0` and `-s65536`. This avoids the installed runtime's large
default stack reservations preventing startup within the memory envelope.
Its RSS budget is unchanged. Large proofs can still exhaust the selected
stack or memory limits and return a failed result. CPU/process reservations
are estimates, not enforced cgroup task or CPU limits. Sampled RSS can overshoot
between observations; address-space limits remain finite per process.

For an existing actual parent lease, inject an admitted child runner:

```python
from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend

backend = LeanKernelBackend(runner=ResourceAdmittedToolRunner(
    parent_lease=parent, cpu_slots=1, child_process_slots=1,
))
```

Child resources must fit the parent and remain charged inside its envelope.
For an explicitly admitted runner, Lean/TLC worker arguments follow its CPU
reservation. An explicitly injected plain `BoundedToolRunner` retains the
existing ownership contract and does not acquire another reservation. Its
caller must already manage admission, limits and cleanup. Arbitrary executable
wrappers are trusted and can create additional work outside these estimates.

The [native qualification](../../../workspace/generic-prover-admission-qualification-20261003/REPORT.md)
separates executed tools, synthetic pressure tests, capacity refusals and retained
failed attempts. Native imports now leave optional SymbolicAI initialization to
explicit neural export access. Isabelle readiness uses its existing separately admitted
preparation operations; their deadline is not part of the new execution deadline.
JVM identity discovery now has the admitted probe described below; optional
installation and later tool-specific setup probes remain separate operations.
Apalache uses the reviewed JVM/in-process-Z3 profile described in the later
Apalache execution section. The separately qualified CodebaseIR SMT producer
already has its own admitted owner and is unchanged.

## Public SMT execution

Public `logic.backends.z3` and `logic.backends.cvc5` adapters, the standard backend
registry, and the default `SmtExecutionEngineV2` now select shared admission.
Each native phase reserves one CPU and one process with the requested finite
memory budget used for both address space and sampled tree RSS. Query, optional
artifact replay, and version observation share one deadline and aggregate output
budget. Existing pressure backoff pauses their new admissions.

```python
from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

backend = Z3SoftwareVerificationBackend()  # Shared admission is the default.
outcome = backend.run(obligation, bounds=ExecutionBounds(
    timeout_ms=5000, max_steps=100000,
    max_memory_bytes=128 * 1024**2, max_output_bytes=65536,
))
```

An actual `parent_lease` may be passed to the constructor for nested admission;
`cancellation` may be passed to the constructor or each direct `run` call.
Supplying an explicit callable `runner` or plain `tool_runner=BoundedToolRunner()`
keeps admission under the caller's ownership. Contradictory ownership arguments
are rejected. Version lookup on the public software-verification adapter returns
checked metadata without launching a separate unadmitted process.

Native scripts must fit the closed single-check profile: one `check-sat`, then
optional model/core commands, with no incremental or parallel-worker options.
Registry compiler numeric `:timeout` and `:rlimit` options are also accepted.
The actual assertion prefix remains unchanged. When both artifacts are requested,
the adapter first obtains the verdict, then reruns the same prefix with only the
applicable artifact command. The second verdict must match and the response must
have the expected artifact shape. This does not independently prove a model or core.
Nonzero exits, error responses, truncation, cancellation and incomplete cleanup
cannot supply a native proof verdict. Unsupported profiles fail before launch.

The [SMT qualification](../../../workspace/generic-smt-admission-qualification-20261003/REPORT.md)
covers installed Z3/CVC5 through public, registry and V2 entry points. Each solver
in V2 differential execution retains its own transport limits. The V2 aggregate
controls described below now cover both participants, replay and cancellation.
Direct legacy imports from
`z3.compiler`, `cvc5.compiler`, and old `smt.differential` default helpers retain
their original behavior because historical proof receipts pin those sources.
They require caller-owned admission until an explicit compatibility migration.
The legacy software-verification pipeline module and security code-header
derivation still select these older defaults. Native wall,
memory and output budgets are enforced on the new route; `max_steps` is not an
exact solver instruction cap. Compilation is checked against the operation
deadline before launching, but Python compilation itself is outside reservation.

## SMT consumer defaults

`logic.verification_api.run_z3_cvc5_differential` and classical SMT parser routes
now select admitted solvers. New package-level helpers expose the same behavior:

```python
from ipfs_datasets_py.logic.backends.smt import run_z3_cvc5_differential
from ipfs_datasets_py.logic.software_verification import (
    ContractSpec, SourceToVerificationPipeline,
)

report = run_z3_cvc5_differential(obligation, bounds=bounds)
pipeline = SourceToVerificationPipeline(bounds=bounds, include_supervisor_evidence=False)
result = pipeline.run(source, path="example.py", language="python", contracts=contracts)
```

The public source pipeline supplies admitted default backends to the unchanged
compiler/VC pipeline. Explicitly supplied backends retain their caller-owned
execution contract; a caller with an actual parent lease can inject public SMT
backends constructed with `parent_lease=parent`. Compile-only mode does not create
default solver backends. Package imports remain lazy and do not probe or reserve.

Differential participants and individual pipeline obligations retain their
per-solver budgets, and the public facades now also apply the whole-operation
deadline described below. Execution inside a differential pair remains sequential;
independent callers can execute concurrently through the shared scheduler.
Classical SMT results keep their existing satisfiability authority and source/route receipts.

The [consumer qualification](../../../workspace/smt-consumer-admission-qualification-20261003/REPORT.md)
tests the public API, classical parser routes and source-to-VC-to-SMT pipeline.
Direct imports from `software_verification.pipeline` and `smt.differential` remain
legacy compatibility entry points. The header derivation module also remains
unchanged: its implementation hash is embedded in historical derivations, so its
native checker needs an explicit compatibility migration.

## Whole-operation deadlines and cancellation

Public differential helpers, their default verifier, the public source pipeline,
and the verification API differential operation now have an aggregate deadline
enabled by default. It uses `bounds.timeout_ms` unless `operation_timeout_ms` is
specified. The per-solver bounds remain unchanged in solver receipts; each native
phase receives the smaller of its local allowance and the operation's remaining
time. Queueing, compilation checkpoints, both solver participants, later pipeline
obligations, result construction and public API validation consume that same budget.
Explicit operation timeouts must be integers from 1 to 2,147,483,647 milliseconds.

```python
from ipfs_datasets_py.logic.backends.process import CancellationToken
from ipfs_datasets_py.logic.backends.smt import (
    ProofOperationInterrupted, run_z3_cvc5_differential,
)

token = CancellationToken()
try:
    report = run_z3_cvc5_differential(
        obligation, bounds=bounds, operation_timeout_ms=10000, cancellation=token,
    )
except ProofOperationInterrupted:
    # No complete report was returned. Native cleanup has finished.
    report = None
```

The source pipeline accepts the same controls. Call `token.cancel()` to revoke
waiting or running native work. Once observed, cancellation remains latched even
if an external event is later cleared. Nested operations cannot extend a parent's
deadline or remove its cancellation signal. Reused verifier/pipeline instances
keep concurrent callers' operation state separate.
An observed interruption in a nested operation also stops its enclosing operation.

An interrupted operation raises a typed exception and withholds its result,
including any earlier proved or disproved rows. Guards run before and after
compiler/backend callbacks and at the outer return boundary. Native subprocesses
receive the remaining deadline and cancellation signal; their bounded cleanup
finishes before leases release. In-process parsing and caller-injected Python
callbacks are cooperative: they cannot be forcibly preempted, but late results
are rejected and no subsequent solver work is started. Cleanup may extend past
the deadline by the process runner's bounded termination grace.

The [operation-control qualification](../../../workspace/smt-operation-control-qualification-20261003/REPORT.md)
separates native interruption tests from synthetic pressure/deadline controls.
Its benchmark can retain an exact reviewed set of disabled recovery metadata
from another checkout; this adapter does not add production scheduler schema
negotiation. It refuses changed policy or state instead of resetting the pool.
This does not add an aggregate output/memory budget or parallelize the solver
pair. V2 execution is covered below; legacy modules, header checks and setup
operations still need aggregate integration. Historical semantic producer sources
and receipts remain fixed; current public runtime changes are recorded separately.

## V2 execution and replay deadlines

`SmtExecutionEngineV2.execute()` and `.replay()` now use the same default
whole-operation controls. The effective request's `bounds.timeout_ms` supplies
the deadline unless `operation_timeout_ms` is set on the engine or call. Call
overrides take precedence; constructor and call cancellation signals combine.
`execute_smt`, `execute_z3`, `execute_cvc5`, `execute_differential` and
`hermetic_engine` accept these controls too.

The scope includes request normalization, compilation checkpoints, differential
participants, automatic primary replay, evidence construction, and the final
explicit replay comparison/receipt. Minimal timeout validation, bounds lookup
and coercion needed to choose the budget precede the scope. Helper construction
of a default engine also precedes it. Python callbacks remain cooperative.
An observed interruption raises the existing typed operation exception and
withholds both conclusive evidence and a late `matched=True` replay receipt.

V2 controls are runtime arguments, outside serialized request/evidence records.
Successful wire identities and per-backend bounds retain their existing meaning.
Ordinary solver-local timeout dispositions remain possible when the aggregate
budget has time left. A replay creates a new bounded operation; nested execution
inherits its remaining time and cannot extend it.

The default V2 engine uses real admitted solvers. `HERMETIC_FIXTURE` mode adds
an immediate replay for conclusive results; use `hermetic_engine` to inject
deterministic fixture runners. Explicit injected backends retain caller ownership
and have cooperative boundary checks.

See the [V2 qualification](../../../workspace/smt-v2-operation-control-qualification-20261003/REPORT.md)
for native execution/replay controls and exact pre-change wire comparisons. This
increment evolves the V2 runtime file with a retained preimage; it does not change
the frozen CodebaseIR producers, historical cache evidence, aggregate memory/output
limits, or supervisor admission.

## JVM identity probe admission

`state_model.read_java_version_banner()` and `probe_java_runtime()` now run
`java -version` through shared resource admission by default. This also covers
the identity probe performed by ordinary TLC and Apalache constructors and the
registry's TLC factory. Imports and static executable resolution do not launch
Java or acquire a lease.

The fixed probe profile reserves one CPU and one child-process slot, with a
256 MiB sampled RSS guard, 4 GiB address-space limit, 128 MiB maximum Java heap,
64 KiB limit on combined accepted output and explicit single-CPU/serial-GC options.
The underlying runner bounds each output stream separately. JVM option
environment overrides are removed. This is an identity/support observation; it
does not run a model check or grant proof authority.
These are scheduler reservations and process limits. They do not provide hard
aggregate CPU, thread or PID containment for arbitrary Java launchers.

The default ten-second timeout includes admission and probing. Explicit
`scheduler`, actual `parent_lease`, and `cancellation` controls are accepted by
the probe APIs. Parent and scheduler are mutually exclusive. A nested banner
read shares the runtime probe's remaining deadline, including executable
resolution and final banner normalization. An active proving-operation scope
further limits the deadline and supplies its cancellation signal.

Standalone cancellation, timeout or incomplete native execution returns the
existing unavailable probe shape. If an enclosing proving operation stops,
its typed interruption propagates after cleanup. A shorter local probe timeout
does not revoke an enclosing operation that still has time left. Success needs
complete, bounded native output; late or unsafe output cannot make a JVM usable.
Invalid ownership controls raise errors. Admission/configuration failures either
refuse the probe or propagate an unsupported configuration error; neither path
falls back to an unadmitted process.

The [JVM probe qualification](../../../workspace/jvm-probe-admission-qualification-20261003/REPORT.md)
separates real Java identity calls from controlled pressure/deadline tests.
Explicit probe callers can pass a parent lease. Existing constructor signatures
cannot forward the parent attached to their later model-check runner, so their
identity probe currently owns a separate root reservation. Setup-to-proof
ownership/deadlines, whole-install budgets, Apalache execution and hard
aggregate memory/PID containment remain separate work.

## TLC and Apalache startup probes

The runtime help/version checks used by the state-model installers now use
shared admission by default. `probe_tlc_runtime()`, `probe_apalache_runtime()`,
`read_tlc_version_banner()` and `read_apalache_version_banner()` accept optional
`scheduler`, actual `parent_lease`, and `cancellation` controls. Each call shares
one local deadline across discovery, native work and result normalization;
TLC's launcher-to-JAR fallback consumes the same budget. An enclosing proof
operation further limits the deadline and supplies cancellation.

The startup profile reserves one CPU and 512 MiB RSS, with a 4 GiB address-space
limit and a 64 KiB limit on combined accepted output. Direct TLC JVM calls and
the reviewed Apalache script receive a 256 MiB heap and single-CPU/serial-GC
options. Unknown scripts can ignore those options and remain subject to the
external limits. Known direct TLC JVM calls reserve one process slot;
Apalache and unrecognized launcher
scripts reserve three. The runner bounds each output stream, workspace and files.
Sampled RSS and process reservations do not provide hard aggregate containment.

An exact managed TLC launcher can be recognized from a bounded regular-file read
and expanded into a direct Java help command with explicit JVM limits. Probe
records report the command actually executed. Existing launcher bytes and managed
manifest formats remain unchanged. Unrecognized launchers run under finite limits
and can be refused if their startup requirements exceed the profile. Apalache's
version probe receives owned heap and garbage-collector options instead of its
script's large default heap.

Complete TLC help may legitimately exit with status 1. A cancelled, timed-out,
truncated, resource-exhausted or incomplete lifecycle cannot supply usable help
or a usable version. Local interruption returns an unusable observation; an
interrupted enclosing proof operation propagates its typed error after cleanup.
An incomplete native execution stops further fallback in that local call. A
missing executable detected before launch can still fall back to an available JAR.

The [runtime-probe qualification](../../../workspace/state-model-probe-admission-qualification-20261003/REPORT.md)
separates native startup checks from private pressure and deadline tests. This
does not execute a model check or grant proof authority. Whole-install locking,
download/extraction budgets and setup-to-proof parent propagation remain open,
as do generic legacy version readers, Apalache execution admission and the TLA
model runner's precedence of interruption checks over counterexample markers.

## Qualification and next integration steps

Use synthetic pressure tests before any many-core benchmark. Measure checked
proof throughput, peak RAM, PSI, cancellation latency, and queue lengths under
bounded workloads. Increase capacity gradually while maintaining headroom.

The next milestones are to connect the remaining prover adapters to this shared
admission authority, enforce aggregate worker process-tree limits, account for
native backend threads, and replace ready-slice barriers with continuous dispatch.
Adaptive growth should follow measured stable operation. Priority-based
cancellation and active-worker throttling require a subsequent runtime controller;
the current backoff pauses new admission and lets existing work finish.

## TLA outcome integrity increment (2026-10-03)

TLC and Apalache model-runner results now reject incomplete native lifecycles
before inspecting success or counterexample markers. Truncation, resource/workspace
limits, incomplete cleanup, signal exits and process errors cannot become bounded
conclusions. Combined UTF-8 stdout and stderr must also fit the accepted output
budget. Unsafe model runs do not launch a follow-up version process. Unsafe
version execution also revokes the local conclusion; a clean unsupported version
exit only makes descriptive version metadata unavailable. Valid TLC invariant
violations with exit 12 and complete TLC help with exit 1 remain supported.

Cancellation and the existing check deadline are rechecked through trace parsing,
source-map replay and final outcome construction. A late stop clears both the
receipt counterexample and the result witness. This control is local to each call;
Python parsing and callbacks are checked cooperatively. See the [qualification](../../../workspace/tla-outcome-integrity-qualification-20261003/REPORT.md)
for regression coverage, admitted native TLC checks and retained wire comparisons.

This closes the interrupted-counterexample classification gap identified above.
Constructor setup, compilation before `check()`, later TLA V2 evidence construction
and installation still need unified ownership/deadlines. Native Apalache model
execution admission, hard aggregate memory/PID containment and supervisor ownership
remain open. This adds no source semantics, training eligibility or planner authority.

The final source-preservation audit found independent changes to
`software_verification/pipeline.py` and `software_verification/source_adapters.py`
during qualification. Those changes are retained without adoption or reversal.
The joined tests and native benchmark bind their actual stable source generation;
historical source preservation remains unresolved. Prior qualification artifacts
and the original proof cache remain byte-identical. See the linked report's drift
record before relying on historical compatibility.

## Source mirroring and proof-generation compatibility (2026-10-03)

The public admitted source pipeline, its convenience helper and the source adapter
object accept the per-call `mirror` option. `mirror=False` suppresses the optional
supervisor's metadata-mirroring attempt while retaining source evidence and
translation. The default remains enabled and preserves calls to legacy supervisors.
Only actual booleans are accepted. A legacy supervisor without the keyword
fails without retrying a call that could mirror data. The option does not
control arbitrary import side effects or make default best-effort mirroring durable.

The [qualification](../../../workspace/source-mirroring-compatibility-qualification-20261003/REPORT.md) reviews the prior pipeline,
source-adapter and integer-profile mirroring additions and completes the public
routes. Historical source bytes remain a distinct generation. Identical selected
source/ProgramIR/VC/SMT encodings do not authorize reuse of old receipts under new
implementation hashes. Existing exact-generation validators and legacy compatibility
tables remain unchanged: stale records are rejected, while fresh conditional
verification/applicability records bind the actual current module inventory and
receive new cache keys. Prior database, CAS objects and qualification artifacts
remain immutable. The expanded inventory includes the integer-profile dependency
that earlier runtime manifests omitted.

This resolves the previously unreviewed mirroring change through explicit generation
qualification, not by declaring old source pins current. Fresh observations retain
conditional authority. This increment does not implement training or activate
planner execution. Whole-install budgets, Apalache admission, hard aggregate containment,
supervisor scheduling ownership, DuckLake delivery and learned semantic IR remain
separate work.

Provider selection is explicit in the qualification. The default test environment
resolves an older nested supervisor that lacks the mirroring keyword and correctly
refuses `mirror=False`. Positive parser tests inject the reviewed sibling parser
and record its actual supporting dependencies; they do not silently upgrade the
installed provider. `include_supervisor_evidence=False` supports native-only
verification without that optional dependency. Production provider-version
selection and negotiation remain open.

## Optional program-AST provider capabilities (2026-10-03)

The source adapter now checks the selected optional provider before running its
language detector or parser when `mirror=False` is requested. The provider must
explicitly declare a keyword-capable `mirror` parameter. Legacy signatures,
`**kwargs` alone, positional-only parameters and uninspectable signatures do not
establish that capability. A `ProgramASTProviderCompatibilityError` (also a
`TypeError`) explains the incompatibility without a trial call or retry. Default
and explicit-enabled calls retain their previous behavior.

`inspect_program_ast_provider()` in `software_verification.source_adapters`
reports the provider selected by normal imports and its advertised capability.
Inspection may import the optional package, but does not call the detector or
parser. The diagnostic is separate from source/proof result encodings and does
not attest a provider's behavior or absence of arbitrary side effects. Capability
checks use the callable pair captured for that request, without a global support
cache, provider replacement or changes to import paths. Native-only execution
continues to use `include_supervisor_evidence=False`.

The [qualification](../../../workspace/program-ast-provider-qualification-20261003/REPORT.md) records selected regression tests,
separate-process checks of the actual nested and sibling providers, and fresh
conditional proof generation under the changed source hash. Prior evidence remains
immutable; no compatibility aliases or authority promotion are introduced.
Runtime capability negotiation is implemented within this scope. Installing or
selecting a compatible provider remains deployment work, and the older nested
provider continues to reject the opt-out. Whole-install budgets, hard aggregate
containment, supervisor scheduling ownership, authenticated index scaling,
DuckLake, learned semantic IR and production planner admission remain open.

Inspect the selected provider without parsing source:

```python
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    inspect_program_ast_provider,
)

print(inspect_program_ast_provider())
```

The `status` is `supported`, `unsupported`, `unknown` or `unavailable`; `reason`
explains the result, and `adapter.origin` identifies the callable's code file when
available. This diagnostic uses normal optional-provider imports.

## Bundled program-AST provider deployment (2026-10-03)

The bundled source-tree supervisor now implements the reviewed per-call `mirror`
control already present in the sibling checkout. Normal imports from the datasets
repository accept `mirror=False` while retaining source evidence and translation.
The default remains enabled. Exact booleans are validated before detection or
parsing, and the opt-out applies to every return path, including malformed input,
unsupported languages, source-size rejection and fact truncation. Other provider
APIs and their mirroring policies are unchanged.

This is a narrow source-tree backport, with the old file preserved and the result
compared against the reviewed sibling implementation. It does not change import
selection or upgrade an external installation. The capability diagnostic still
rejects legacy or ambiguous providers before executing callbacks. The
[qualification](../../../workspace/bundled-program-ast-provider-qualification-20261003/REPORT.md) records regression tests and coherent cold
processes using both actual source-tree providers with an in-memory metadata sink.
Real metadata persistence remains outside that test scope.

The closed native-only proof producers omit optional supervisor evidence; their
74 recorded runtime sources and 27/29 producer dependency inventories remain
unchanged. Existing conditional receipts therefore retain their source bindings,
cache keys and CIDs, and are checked through solver-free current-head queries and
intent matching against a copied catalog with its original CAS binding. No proof
hashes are aliased, old artifacts rewritten or authority flags promoted. The
earlier 60-phase native benchmark remains historical evidence; this increment
does not count or repeat those solver executions.

Deploying compatible external packages remains separate from this bundled-checkout
fix. Whole-install budgets, setup-to-proof ownership, Apalache admission, hard
aggregate containment, supervisor scheduling, authenticated index scaling, DuckLake,
learned semantic IR and production planner admission remain open.

## TLA aggregate operation control (2026-10-03)

TLA `compile_and_check` and `run`, plus the V2 execution engine and helpers, now
use a shared cooperative operation deadline. The default is the request's timeout
bound (30 seconds where no request supplies one); `operation_timeout_ms` provides
an explicit aggregate override. A caller cancellation signal and any enclosing
proof operation also apply. Compilation, request normalization, selected-provider
setup, model checking, descriptive version probes and final evidence publication
are checked under that operation. Interrupted aggregate calls raise the existing
typed proof-operation exception without returning partial or late conclusions.
Original request bounds and evidence schemas retain their meanings.

Native qualification also exposed oversized TLC help metadata at the V2 boundary.
V2 now summarizes a complete bounded provider version banner, or records `unknown`
when none is available. The raw backend receipt remains intact.

V2 engines construct default provider backends lazily, so a TLC request need not
probe the unused Apalache provider. The selected JVM validation inherits the
active deadline. Low-level `check` retains its original standalone result behavior
and consumes a tighter ambient operation when present. Existing shared resource
admission remains responsible for each native phase; this change does not add a
root reservation across the whole operation or transfer a caller-owned setup lease.

The [qualification](../../../workspace/tla-operation-control-qualification-20261003/REPORT.md) records regression and bounded native
TLC tests, source identities, interruption controls and process cleanup. Apalache
aggregate behavior is covered with controlled fixtures; its native process profile
and admission remain separate work. Direct standalone backend/facade construction
retains its separate support-probe budget. Python callbacks and optional lazy
installation are checked before and after each call. Installer internals, including
locks, downloads and extraction, are not newly checkpointed or forcibly preempted
and still require whole-install budgets.

Stored proof evidence and prior qualifications remain immutable. This increment
does not activate training or production planner admission. Hard aggregate cgroup
containment, supervisor scheduling ownership, authenticated index scaling, DuckLake
and learned semantic IR retain their acceptance gates.

## Apalache default execution admission (2026-10-03)

Apalache model checks and descriptive version commands now use shared resource
admission by default. Each phase reserves one CPU, three process slots for the
reviewed launcher helpers, and the caller's requested resident-memory bound.
The reviewed solver loads Z3 through JNI inside the JVM; no separate Z3 executable
is required by that profile. Shared admission applies existing pressure backoff
before launch. Cancellation and aggregate operation deadlines remain active
during native execution.

The managed profile limits the Java heap to half the requested RSS budget,
rounded down to whole MiB, with serial GC and an active-processor setting
matched to the admitted CPU reservation.
It requires at least 256 MiB requested RSS without increasing that request.
Native-library extraction stays in the private workspace under explicit 64-MiB
per-file and 128-MiB workspace limits. The existing finite address-space bound
remains separate from RSS. These reservations and sampled guards do not provide
hard aggregate cgroup CPU, memory or PID containment.

Managed execution isolates Java user configuration, supplies its own empty
Apalache runtime configuration and routes output to a fixed private directory.
For the reviewed stock launcher and default environment, this prevents ambient
configuration from changing the solver defaults. Arbitrary custom launchers and
custom base environments remain caller-trusted.
An explicitly admitted runner needs at least three process slots and receives
the managed profile; an injected plain runner keeps its caller-owned contract.
TLC's execution profile and the request/receipt schemas remain unchanged.

The preceding Apalache qualification recorded a separate registry defect
(repaired by the subsequent registry increment below):
its protocol enum has no `TIMEOUT` member, so a completed delegate can become
an `ERROR` receipt. The new regression records that existing failure explicitly;
native success in this qualification covers the V2 engine and helper routes.
Fixing registry conversion without promoting bounded or candidate evidence
remains a follow-up.

The [qualification](../../../workspace/apalache-execution-admission-qualification-20261003/REPORT.md)
records private-scheduler pressure tests, real installed-tool runs, selected source
and tool identities, and cleanup. Native violations retain their raw Apalache
witness. Its `State0 ==` output is not parsed into TLC-style `State 1:` blocks;
this increment does not claim a parsed or semantically replayed Apalache trace.
The legacy `replayed` flag does not establish replay when `states` is empty.

The accepted qualification passed 1,708 selected regression tests, including 47
new admission tests, and 60 native phases across a smoke run and a full batch.
The full batch took 23.418 seconds. Requested caller widths of one, two and four
all dispatched one operation at a time under the unchanged four-process pool;
these measurements do not establish many-core speedup. Earlier capacity-wait
and resource-limit attempts remain recorded separately from accepted results.

Earlier proof receipts and qualifications remain immutable. Whole-install budgets,
setup-to-proof parent ownership, standalone facade operation controls, Apalache
trace parsing, hard aggregate containment, supervisor scheduling ownership,
DuckLake scaling, learned semantic IR and production planner admission remain
separate acceptance work.

## Foreign solver outcomes in the generic registry (2026-10-03)

Validation passed: **1,914 selected regression tests**, including **82 new
foreign-outcome cases**, and two real Apalache registry cases in **3.54 seconds**.
The accepted run contains six admitted native phases with complete owned-resource
cleanup. An earlier three-phase attempt is retained separately; its fixture
assertion exposed the artifact-decoding gap described below. All 1,341 artifact
bodies from 16 earlier qualifications remain unchanged. These serial cases
qualify result conversion and resource lifecycle, with no many-core throughput claim.

The generic registry conversion now uses its own protocol status vocabulary.
A completed foreign adapter outcome produces a bound `UNKNOWN` result and retains
the original typed result, status and authority as descriptive payload. A tool's
`proved`, `satisfied`, `candidate` or reconstruction status does not become a
positive generic protocol conclusion. The existing protocol-pair path remains
unchanged. Provider-specific typed and V2 routes retain their scoped semantics.

Timeout, unavailability, cancellation and malformed/unsupported outcomes retain
explicit execution classifications. The normalizer records its authority limit
in diagnostics. This repairs the enum mismatch recorded in the preceding Apalache
qualification while preserving the original bounded model-check evidence.

The [qualification](../../../workspace/registry-foreign-outcome-qualification-20261003/REPORT.md) records regression tests,
actual installed Apalache execution through the registry, exact source and tool
identities, and preservation of earlier receipts. Native qualification supplies
an explicit outer operation budget in the harness; it does not add automatic
aggregate setup budgeting to the production registry.

At the registry qualification above, the TLA payload reader substituted the
compiler's default bounds and dropped source-map/loss metadata (repaired below). The native
conversion qualification uses a matching default 64-step fixture; general
serialized-artifact round-tripping remains a separate gap. The retained initial
attempt exposes the three-step payload becoming a 64-step checker command.

Python getters and serializers remain cooperative callbacks. The output cap
bounds the serialized payload; it does not hard-limit callback memory or runtime.
Extremely small output budgets can still fail in the existing terminal helper
when even its fallback envelope cannot fit.

This increment changes result conversion. Apalache trace parsing and its legacy
replay label, whole-install budgets, hard aggregate resource containment, wider
concurrency qualification, learned CodebaseIR and production planner admission
remain separate work. Earlier proof-cache producer inventories stay unchanged.


## Serialized TLA artifact preservation (2026-10-03)

Validation passed on the first attempts: **2,015 selected regression tests**,
including **101 new artifact cases**, and **531 focused tests**. Two installed
Apalache registry cases completed in **3.47 seconds** with six admitted native
phases, exact three-step artifact preservation and complete owned-resource
cleanup. All 1,420 artifact bodies from 17 previous qualifications remain
unchanged. Focused and joined test counts overlap and are not additive.

The typed runner, generic registry route and V2 mapping route now share artifact
payload decoding. Full generated records preserve their declared compilation
bounds, source maps, projection losses, property lists, translator/version data,
and exact model/configuration text. Model, configuration and supplied artifact
digests are checked before model checking. Canonical records with malformed or
missing fields, unsupported versions or mismatched digests are rejected instead
of being silently repaired. Use the complete text-bearing `artifacts.to_dict()`
record when transferring compiled artifacts between these APIs.
The standalone reader also accepts an omitted outer artifact digest and
recomputes it; V2 callers should keep that digest because the existing compact
request identity reads the supplied value. That identity scheme is unchanged.

Minimal legacy model/configuration payloads keep their separate default-bounds
path. Adding bounds, source-map/loss or canonical identity fields requires a
complete canonical record. This avoids silently discarding declared semantics.
Deserialization establishes record consistency; it does not independently verify
the supplied source mapping or translation claims. Existing request identity,
authority classification, resource admission and operation-budget behavior remain
unchanged. V2 capability/setup work can precede artifact rejection.

The [qualification](../../../workspace/tla-artifact-payload-qualification-20261003/REPORT.md) records exact round trips, malformed-input rejection,
and installed Apalache execution with a non-default three-step bound and nonempty
source-map/loss metadata. The native cases retain generic `UNKNOWN` results with
original bounded checker evidence. The harness supplies its explicit 30-second
outer operation budget; production aggregate setup budgeting is unchanged.

Apalache's raw counterexample parser/replay-label gap, whole-install cancellation,
hard aggregate resource containment, many-core scaling, learned IR and planner
acceptance remain separate work.


## Apalache counterexample parsing and structural validation (2026-10-03)

The counterexample reader recognizes Apalache's `State0 == ...` definitions as
well as TLC's `State 1:` blocks. It preserves the raw trace and original state
labels while exposing positive state indexes through the existing schema.
Assignment values remain text; parsing does not evaluate TLA expressions.

The legacy `replayed` flag now reports successful structural source-symbol
validation only. Empty, malformed, incomplete or unmapped traces cannot report a
successful replay. Parser diagnostics survive supplemental counterexample-file
handling, and V2 no longer promotes a raw-only trace into `REPLAYED`. A structural
match does not independently check transitions, the violated invariant, fairness,
liveness or the truth of supplied source-map metadata.

The [qualification](../../../workspace/tla-counterexample-replay-qualification-20261003/REPORT.md) records regression coverage and installed Apalache
execution through the default generic registry. Its invalid three-step model
retained parsed values 0, 1 and 2, its original raw witness, the complete artifact
and bounded checker evidence. Generic conclusions remain `UNKNOWN`. The harness
keeps the existing shared-pool guard and finite resource profiles, with its own
explicit 30-second outer operation budget per serial case.

Validation passed **2,089 selected tests**, including **74 new cases**; the focused
subset passed 605 tests. Fifteen legacy native tests remain explicitly deselected.
The two real Apalache cases completed in **4.230 seconds**, with six admitted
native phases, cleaned workspaces and no remaining owned leases or waiters.
An initial duplicate-diagnostic failure with long source identifiers was fixed;
its source snapshot and failed run remain in the qualification alongside the
passing rerun. All 1,509 prior artifact bodies from 18 qualifications are unchanged.

Parsing is bounded to 512 states, 262,144 characters and nesting depth 128.
Unsupported or incomplete syntax keeps raw evidence and prevents structural
replay; the implementation does not evaluate arbitrary TLA expressions.

Semantic counterexample replay, production registry setup budgeting, whole-install
cancellation, hard aggregate resource containment, many-core scaling, learned IR
and planner acceptance remain separate work. Earlier qualification artifacts keep
their historical zero-state/legacy-flag observations unchanged.


## Automatic generic registry operation budgets (2026-10-03)

Generic registry execution and direct callable/lazy wrappers now use one
cooperative operation deadline by default. It covers setup, availability checks,
compilation, execution and result conversion. The default is the request timeout,
capped at the operation helper's maximum; `operation_timeout_ms` can tighten it.
Nested scopes inherit the earliest deadline. The original request, bounds and
digests remain unchanged. `cancellation` joins any inherited cancellation signal.

The ordinary call is bounded automatically. Optional controls can shorten the
deadline or connect a caller-owned cancellation event:

```python
registry = default_backend_registry()
attempt, result = registry.run(request, backend_id="apalache")
attempt, result = registry.run(
    request, backend_id="apalache",
    operation_timeout_ms=5_000, cancellation=stop_event,
)
```

An observed interruption produces a bound `TIMED_OUT` or `CANCELLED` attempt with
an `UNKNOWN` result. A late Python callback cannot publish a conclusive result.
A stopped parent scope remains stopped even if a nested adapter returns a terminal
pair or a cancellation event is later cleared. Interrupted lazy initialization
can be retried by a fresh call; concurrent callers wait under their own controls
and cannot observe a partially initialized delegate.

The [qualification](../../../workspace/registry-operation-budget-qualification-20261003/REPORT.md) records tests and installed Apalache execution through
the default registry without a benchmark-owned outer scope. Existing shared-pool
policy, real pressure sampling and per-phase resource profiles remain in use.

Validation passed on the first runs: **2,215 selected tests**, including **126 new
cases**, and **747 focused tests**. Fifteen legacy native tests remain explicitly
deselected. The two real Apalache cases completed in **3.917 seconds** with six
admitted native phases. Recorded factory/setup/model/version observations share
one production-created deadline per case; all workspaces cleaned up and no owned
leases or waiters remained. All 1,618 prior artifact bodies from 19 qualifications
are unchanged. Focused and selected counts overlap and are not additive.

This is cooperative control at Python callback boundaries. The admitted SMT/TLA
paths consume the remaining deadline; other native adapters still require their
own propagation audit. Explicit standalone availability probes, hard callback
preemption, whole-installer cancellation, hard aggregate containment and many-core
scaling remain separate work. The prior qualifications' benchmark-owned scopes
remain unchanged historical evidence.


## Ambient budgets for admitted native execution (2026-10-03)

`ResourceAdmittedToolRunner` now inherits the current proof operation's deadline
and cancellation signal. Registry-created budgets reach existing admitted kernel,
SMT, TLA and JVM launches without each adapter forwarding a new argument. The
effective wall deadline is the earlier of the tool request and ambient deadline.
Admission and workspace preparation consume that same budget; an existing CPU
ceiling is tightened to remaining time when an ambient operation is present.
Original requests, memory/output/storage limits and reservation profiles remain
unchanged. CPU limits retain their operating-system rounding behavior.

Stops are checked before scheduler resolution, during queued admission, before
native launch, after output/workspace cleanup and after lease release. The final
check uses caller/operation signals rather than the released lease. Observed stops
are sticky, and late results retain their raw evidence and existing failure flags
while becoming non-successful. An ambient timeout may accompany a native
cancellation flag because the process polls a stop signal. The registry/outer
scope retains the logical interruption reason. Runner-local stops do not revoke
a separate, still-live ambient operation. Cleanup failures continue to propagate.

The [qualification](../../../workspace/native-operation-inheritance-qualification-20261003/REPORT.md) records actual Lean and Rocq positive/negative registry
cases plus separate Python transport timeout/cancellation controls. Python controls
exercise the admitted transport; they are not native solver cancellation proofs.
The benchmark retains the saved shared-pool guard and real pressure sampler.

Validation passed: **2,314 joined tests**, retaining all 2,215 prior cases and
adding 58 new inheritance cases plus 41 previously unselected kernel cases;
**818 focused tests** also passed. These populations overlap. Fifteen legacy
native cases remain deselected. Four real Lean/Rocq cases and two owned Python
transport controls passed in **2.270 seconds** with six admitted launches. The
one-second deadline control completed in 1.028 seconds; the cancellation control
completed in 0.187 seconds. All owned PIDs/workspaces cleaned up and owned leases
and waiters drained. This serial benchmark does not measure parallel speedup.

The qualification retains all attempts: nine initial failures were fixed by
aligning three synthetic-clock fixtures, with every assertion unchanged. A first
native attempt was rejected by the source-import guard before pool access or
solver execution; a one-line benchmark entry-point correction selects the sibling
checkout consistently, and static preflight now checks that ordering. Production
code was unchanged during those corrections. All 1,708 artifact bodies from the
20 prior qualifications remain unchanged, alongside their reports and manifests.

This increment changes admitted launches. ATP, ProVerif, Tamarin and hyperproperty
defaults still using plain runners need a separate admission/profile migration.
Explicit plain injected runners retain caller-owned behavior. Native Isabelle
execution, whole-install cancellation, hard aggregate containment, semantic trace
replay and many-core scaling are not established by this qualification. Python
callbacks remain cooperative and cleanup may finish after a deadline expires.


## Default resource admission for Vampire and E (2026-10-03)

Canonical Vampire/E adapters and the V2 live-solver fallback now select
`ResourceAdmittedToolRunner` when no runner is supplied. Their finite request
memory, wall/CPU, output and workspace limits feed the existing shared admission
policy. Registry operation deadlines and cancellation reach the native lifecycle
automatically. Explicit runners keep caller-owned behavior; hermetic V2 mode
still requires an injected fixture runner. Discovery remains inert.

Vampire's command now requests `--output_mode szs --proof tptp`; the former
`--output_mode=tptp` value is unsupported by the installed 5.0.1 release.
Every option/value pair, including `--time_limit`, uses separate argv tokens.
The [tagged options source](https://raw.githubusercontent.com/vprover/vampire/v5.0.1/Shell/Options.cpp)
separates the status-output mode from the proof format. One existing regression
assertion was corrected to require both option/value pairs; other assertions and
case identities are retained.

Unsafe lifecycle results are rejected before SZS parsing and proof/model
reconstruction: workspace-limit failures, process errors, unclean cleanup,
terminated trees and combined UTF-8 output overruns return `ERROR`. Process
metadata now retains the tree/workspace flags and termination reason. Existing
cancellation/timeout precedence remains intact.

The qualification covers isolated pressure/backoff fixtures and four serial real
ATP calls with the installed Vampire/E binaries. It does not establish native V2
execution, many-core speedup or hard aggregate containment. Unreconstructed ATP
success remains candidate evidence. E's existing nonzero satisfiable exit remains
an error at the typed adapter boundary; the raw SZS result is retained.

See the [qualification](../../../workspace/atp-default-admission-qualification-20261003/REPORT.md) for exact scope and retained evidence.

Next runner migrations require separate checks: ProVerif already supplies finite
profiles; Tamarin needs a reviewed Haskell/Maude process profile; Hyper requires
finite memory/CPU limits, guarded version probing and complete failure handling.

Standalone V2 parsing/reconstruction still lacks an aggregate operation budget;
its inherited default version label is not installed-version verification.
One CPU/process reservation is an estimate, not an enforced process-tree ceiling.

Registry requests should bind `requested_backend_id="eprover"`; selection may use
`backend_id="e"`. An alias stored in the bound request still conflicts with the
canonical attempt identity when constructing the result. That existing alias
compatibility gap remains open.

Validation passed: **2,408 joined tests**, including all 2,314 previous cases,
**53 new ATP admission cases** and **41 additionally selected existing ATP cases**;
**370 focused tests** also passed. These populations overlap. Fifteen legacy
native cases remain deselected. The four actual ATP cases completed in
**0.344 seconds**, each with one CPU/process reservation, 128 MiB address-space
bound and a five-second request budget reduced by preceding registry work.
All four workspaces and owned PIDs cleaned up; owned leases and waiters drained.
Three results remained unverified candidates. E's satisfiable case retained its
raw SZS result and exit 1 while returning the documented typed error.

All attempts are retained, including the initial test-fixture failures, the
superseded static preflight, and Vampire's first native argument rejection.
The final tests assert exact separate option/value tokens. All **1,902 prior
artifact bodies from 21 qualifications**, and their reports/manifests, remain
unchanged. This serial benchmark establishes neither many-core speedup nor
native cancellation/stress behavior of these two solvers.


## E satisfiable exit normalization (2026-10-03)

The E adapter now recognizes integer exit code 1 with an exact, unambiguous
`Satisfiable` or `CounterSatisfiable` SZS status. E 3.2.5 documents this
[exit convention](https://raw.githubusercontent.com/eprover/eprover/E-3.2.5/BASICS/clb_error.h)
and uses it in its [satisfiable return path](https://raw.githubusercontent.com/eprover/eprover/E-3.2.5/PROVER/eprover.c).
Lifecycle failures and combined UTF-8 output overruns are still rejected before
parsing. Other E exits, inconsistent statuses and Vampire nonzero exits remain
errors. Raw exit codes, termination reasons and request/source bindings survive
normalization. No executable-name heuristic is used.

Default direct, registry and V2 routes retain unvalidated candidate authority;
only an explicitly supplied validator can establish the existing validated-model
contract. E exit 1 cannot establish a proof or bypass reconstruction. This closes
the exit-normalization gap recorded in the preceding ATP admission increment.
See the [qualification](../../../workspace/eprover-satisfiable-exit-qualification-20261003/REPORT.md)
for tests and native measurements.

ProVerif is the next runner migration: its finite profile can use shared admission,
but its result handling first needs workspace/error/cleanup and combined-output
gates. Tamarin/Haskell/Maude and Hyper profiles remain separate work. Registry
alias-valued request bindings, standalone V2 aggregate budgets, native ATP
cancellation, hard aggregate containment and many-core scaling remain open.


Validation passed: **2,458 joined tests**, retaining all 2,408 previous cases and
adding **50 new exit-status cases**; **420 focused tests** also passed. Counts
overlap. Fifteen legacy native cases remain deselected. Six real serial ATP
cases (UNSAT, SAT and counter-SAT for both providers) completed in **0.474 seconds**
(**0.816 seconds** including the benchmark wrapper). All six results remained
candidates with generic `UNKNOWN`; both E model cases preserved raw exit 1 and
`nonzero_exit`. Each used one CPU/process reservation, 128 MiB address-space
bound, five-second request budget, 64 KiB input/output and 128 KiB workspace
limits. Every owned process/workspace cleaned up and owned leases/waiters drained;
shared policy and real pressure sampling were unchanged.

The current qualification pins 98 native and 185 selected source files and
preserves all **2,109 artifact bodies from 22 prior qualifications**, alongside
their reports and manifests. The only existing regression adjustment permits
bounded status parsing for the E exit-1/Theorem rejection fixture; its error and
no-callback assertions remain intact. This serial benchmark measures integration
latency; native V2, solver stress/cancellation, many-core speedup and hard aggregate
OOM/PID containment are not established by this increment.


## ProVerif default admission and lifecycle checks (2026-10-04)

ProVerif now selects `ResourceAdmittedToolRunner` when the caller supplies no
runner. The default registry and protocol V2 paths inherit that choice. Explicit
runners remain caller-owned, including falsey runner instances. Construction,
capability discovery and default toolchain metadata do not acquire resources or
start version/OPAM probes. The existing finite wall/CPU, address-space, input,
output and workspace limits feed shared resource admission and pressure backoff.

Native output reaches claim classification only after a clean lifecycle and an
integer zero exit status. Workspace limits, process errors, unclean cleanup,
terminated process trees and combined UTF-8 overruns now stop interpretation.
Unavailable, cancellation and timeout precedence is retained. Actual executions
also retain process flags, exit codes and stream digests in typed metadata;
unsafe output cannot establish protocol security or an attack receipt.

The [qualification](../../../workspace/proverif-default-admission-qualification-20261004/REPORT.md)
records default-path tests and native admission checks. The native profile uses
the existing installed ProVerif ELF directly, with no compiler, installer or
probe substitution. Default toolchain labels remain descriptive metadata.

Query/result correspondence is a separate open gap: a secrecy query such as
`attacker(s)` may be reported as `not attacker(s[])`, while the current
parser compares literal normalized strings. Fixing this requires explicit query
identity and polarity handling, with tests that reject foreign or ambiguous
claim results. Existing attack replay emits normalized step tokens and may use
a false-result marker; it does not establish semantic trace execution. The
admission increment leaves these semantics unchanged.

Tamarin and Hyper still need reviewed default admission profiles. Standalone
protocol V2 aggregate budgets, native cancellation/stress, many-core scaling and
hard aggregate memory/PID containment remain separate work. One CPU/process
reservation remains an estimate of demand, not a process-tree ceiling.


Validation passed: **2,556 joined tests**, retaining all 2,458 previous cases and
adding **59 new admission/lifecycle cases** plus **39 existing protocol adapter/V2
cases**; **374 focused tests** also passed. These populations overlap. Fifteen
legacy native cases remain deselected. Existing test sources are unchanged.
The new cases exercise CPU/RAM/PID and unknown-telemetry backoff, recovery,
queued deadline/cancellation, reservation ownership and rejection before parsing.

Two actual serial ProVerif calls passed their admission/lifecycle assertions in
**0.192 seconds** (**0.565 seconds** including the benchmark wrapper). They
reported `not attacker(s[])` as true for an undisclosed private constant and
false after public disclosure. Both canonical and generic results remained
`UNKNOWN`, with the requested `attacker(s)` claim unmatched and quarantined;
this benchmark does not establish working native claim normalization. Each call
used one CPU/process reservation, 128 MiB address-space, a five-second request
budget, 64 KiB input/output and 128 KiB workspace limits. Owned PIDs/workspaces
cleaned up and leases/waiters drained; saved policy and real sampling were retained.

The first native attempt used the reserved identifier `secret` and exited 2.
The fixture now uses `s`, as in installed release examples. That failed run,
its reviewed source generation and every test attempt are retained separately;
production and tests did not change during the fixture correction. The final
qualification pins 107 native/dependency and 194 selected sources and preserves
all **2,209 artifact bodies from 23 prior qualifications**, including their reports
and manifests. Native V2, native cancellation/stress, many-core speedup and hard
aggregate containment remain unqualified by this increment.


## ProVerif source-qualified secrecy binding — 2026-10-04

[Qualification report](../../../workspace/proverif-query-binding-qualification-20261004/REPORT.md).

The canonical ProVerif backend now binds native `not attacker(s[])` results
to the requested `attacker(s)` claim when the exact compiled source has a
complete, unambiguous population of ground secrecy queries over declared free
names. The supported source shape is single-name `bitstring`/`channel` free
declarations, followed by attacker queries before `process`, with whitespace and
nested comments. Successful native parsing/execution remains required; the
binding helper does not validate reserved words or process-body syntax.

Identifiers remain case-sensitive, empty name brackets have a specific meaning,
and verdicts are not inverted. Missing, foreign or ambiguous results remain
nonconclusive; duplicate verdicts are deduplicated and conflicting verdicts are
quarantined. Native `cannot be proved` output is recognized. Other source/query
forms retain legacy exact matching and are outside this native qualification.

A qualified true result produces an accepted `SECURE` protocol receipt with
`PROTOCOL` authority and a `BOUNDED` symbolic ceiling. A qualified false result
retains its native query, source claim ID and false verdict, with no attack trace
or replay witness. Disclosed-secret results remain `UNKNOWN` with
`malformed_output` quarantine; mixed true/false results remain `UNKNOWN` with
`disagreement` quarantine. Generic theorem projections remain `UNKNOWN` in every
case. Legacy synthetic trace behavior is unchanged and does not establish
semantic attack replay.

Validation passed **2,612 joined tests**, retaining all 2,556 previous
cases and adding **56 query-binding cases**; **430 focused tests** passed. These
populations overlap. Fifteen legacy native cases remain deselected. Controlled
tests exercise direct, registry and protocol V2 paths using private admission
state and retained native stdout. One existing synthetic disagreement fixture
was corrected to match its submitted queries, with stronger claim-ID assertions.
The initial 429-pass/one-failure run and static evidence remain preserved.

Three actual serial ProVerif cases passed in **0.275 seconds**
(**0.615 seconds** including the wrapper): private `s`, disclosed
`s`, and mixed private `s`/`t` with only `s` disclosed. Their typed statuses were
`SECURE`, `UNKNOWN`, `UNKNOWN`; every generic result was `UNKNOWN`. Each launch
retained the default admitted runner and registry budget, one CPU/process
reservation, 128-MiB address-space bound, five-second request, 64-KiB input/output
and 128-KiB workspace bounds. Real sampling and the exact saved policy remained
in use; owned leases/waiters drained and workspaces were cleaned.

The qualification pins 109 native/dependency and 196 selected sources and
preserves **2,394 artifact bodies from 24 prior qualifications**, plus their
reports and manifests. The preservation guard detected an independently changed
resource scheduler before native execution. Its current exact body was captured
and separately reviewed; accepted static/tests/native all use that generation.
Earlier scheduler bodies were unavailable, so no historical diff or behavioral
equivalence is claimed. The refused capture and initial diagnostic generation
remain in the report.

Remaining work includes broader query/compiler handling, validated semantic
attack reconstruction, verified toolchain identity, standalone protocol V2
aggregate budgeting, and reviewed Tamarin/Hyper defaults. This increment does
not establish native V2 execution, native cancellation/stress, installer safety,
many-core throughput or hard aggregate memory/PID containment. CodebaseIR's
closed producer inventories remain 27 verification and 29 applicability modules;
this change adds no learned IR, proof-cache replay, indexing or planner authority.


## Standalone protocol V2 operation budget — 2026-10-04

[Qualification report](../../../workspace/protocol-operation-budget-qualification-20261004/REPORT.md).

`ProtocolExecutionEngineV2.execute`, `execute_split_providers` and the
`execute_protocol` / `execute_proverif` / `execute_tamarin` helpers now use a
cooperative operation budget by default. The budget covers request/document
normalization, capability callbacks, backend execution and final evidence
construction. Split-provider execution shares one deadline and publishes no
partial result after interruption.

The default is the declared request timeout (1,000 ms when bounds are omitted),
clamped to the shared operation maximum. Constructor defaults and per-call
`operation_timeout_ms` controls may tighten that request timeout; a per-call
override replaces the constructor default, while a tighter parent deadline still
wins. Constructor and per-call cancellation signals combine with the parent.
An observed cancellation stays latched, even if its event is subsequently cleared.
Interruption raises the existing `ProofOperationTimeout` or
`ProofOperationCancelled` exception before evidence publication. Runtime controls
do not change serialized request bounds, receipt identities or evidence schemas.

Canonical backend methods receive the current operation signal. ProVerif's
default admitted runner consumes the remaining wall/CPU budget; Tamarin's existing
plain runner can poll the signal but still needs a separate admission migration.
Explicit runners remain caller-owned. Legacy `run(request)` and
`execute(request)` overrides are called exactly once, with their original
signatures and checks around the call. Opaque Python callbacks and backend-internal
compilation/probes remain cooperative and cannot be forcibly preempted.

A per-call budget can tighten the declared backend request while retaining
the caller's cancellation event:

```python
from threading import Event
from ipfs_datasets_py.logic.backends.protocol.execution_v2 import execute_proverif
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

stop = Event()
result = execute_proverif(
    source="free s: bitstring [private].\nquery attacker(s).\nprocess 0",
    bounds=ExecutionBounds(timeout_ms=5_000, max_memory_bytes=128 * 1024**2),
    operation_timeout_ms=2_000,
    cancellation=stop,
)
```

Callers should handle the typed operation exceptions when cancellation or the
aggregate deadline stops execution. A declared five-second request remains
five seconds in its receipt even when this call uses a tighter runtime budget.

Validation passed **2,702 joined tests**, preserving all 2,612 previous
cases and adding **90 operation-control cases**. **578 focused tests** also passed;
these populations overlap. Fifteen legacy native cases remain deselected.
Controlled tests cover deadline exhaustion, cancellation and clearing, split
budgets, final evidence construction, private pressure queues, concurrent engine
reuse and complete healthy evidence serialization. One retained V2 runner test
now expects the exact forwarded operation signal instead of `None`; direct-call
signal identity, runner ownership, no-admission behavior and declared native
limits remain asserted. The initial 577-pass/one-failure attempt is preserved.

Three real standalone V2 ProVerif calls passed in **0.414 seconds**
(**0.766 seconds** including the wrapper). Private `s` yielded
bounded `SECURE` protocol evidence. Disclosed `s` and mixed private `s`/`t` with
only `s` disclosed yielded V2 `QUARANTINED`, retaining canonical `UNKNOWN` results
and no attack replay. Fourteen observations per case bind one engine-owned
deadline across setup, compilation, canonical execution and evidence packaging;
native invocation shares that deadline. No benchmark-created outer operation or
registry call supplies it.

The serial native profile remains one CPU/process reservation, 128-MiB address
space, a five-second request, 64-KiB input/output and 128-KiB workspace bounds.
Actual native wall/CPU limits consume the remaining budget. Saved policy and real
pressure sampling remain unchanged; owned leases/waiters drain and workspaces
are cleaned. The qualification pins 111 native/dependency and 198 selected
sources and preserves **2,519 artifact bodies from 25 prior qualifications**,
including their reports and manifests. The scheduler is unchanged this turn.

This closes the standalone protocol V2 aggregate-operation gap within the
cooperative contract. Native validation covers successful standalone ProVerif
execution; real cancellation, split-provider native execution, stress tolerance,
many-core speedup and hard aggregate memory/PID containment remain unqualified.
Semantic attack reconstruction, broader query/compiler coverage, verified
toolchain identity and Hyper admission remain open.

The next Tamarin increment needs complete lifecycle/output gates and a reviewed
admission profile. Installed source enables Haskell `-N` threading and launches
Maude subprocesses. Its runtime capability count, explicit Maude selection and
process allowance must be reviewed before native migration; a one-CPU/one-process
assumption is insufficient. This V2 qualification constructs its default Tamarin
object inertly and never probes or executes Tamarin. The static report's
`test_only_dependency_pins` field does not exclude that Python constructor from
the dependency graph.

CodebaseIR producer inventories remain 27 verification and 29 applicability
modules. This increment adds no proof-cache replay, learned representation,
DuckLake indexing or planner authority.

## Tamarin default admission and lifecycle integrity — 2026-10-04

The canonical Tamarin backend now uses resource admission by default, including
registry, protocol V2 and helper calls. This completes the implementation of the
Tamarin default-runner migration described in the preceding increment; successful
native execution of the new profile remains unqualified.

The default runner requests two CPU slots and eight process slots to account for
one Haskell capability, overlapping Maude handles and launcher helpers. It passes
`+RTS -N1 -M<max(1, floor(requested bytes / 2))> -RTS` and selects Maude explicitly
with `--with-maude`. The Maude path must be a shell-safe ASCII token because
Tamarin also uses it in a shell command. The default environment excludes
`GHCRTS` and `DEBUG_MAUDE`. Constructor, discovery and default metadata probes
remain inert; explicitly supplied runners, including falsey objects, remain
caller-owned and retain their previous arguments and memory limits.
Use a name available on `PATH` or an absolute Maude path; relative paths resolve
inside the private workspace.

Memory admission and sampled Linux process-tree RSS use the requested memory
bound. The separate per-process address-space limit is `max(2 GiB, 4 × requested
memory)`. At the standard 512-MiB request this gives a 256-MiB Haskell heap limit
and 2-GiB address-space limit. Matching GHC 9.6.7 source adapts its virtual
reservation to finite `RLIMIT_AS`; newer GHC's `-xr` option is unsupported here and
is not passed. Runtime startup sufficiency still needs native qualification.
These reservations are estimates, RSS sampling can overshoot, and neither this
profile nor the Haskell heap limit provides hard aggregate OOM/PID containment.
Custom oracle processes remain outside the ordinary-stock process estimate.

Result parsing now requires a clean lifecycle, an exact integer zero exit status
and combined stdout/stderr UTF-8 bytes within the requested output bound.
Cancellation, timeout, resource/workspace exhaustion, reported errors and forced
process-tree termination cannot produce accepted protocol evidence. Every runner
result carries lifecycle metadata and stream digests; early unsupported or missing
tool results retain their previous shape. Claim matching and structural attack
trace parsing are unchanged and remain separate semantic qualification gaps.

Validation passed **2,771 joined tests**, retaining all
2,702 previous cases and adding **69 cases**.
The **647 focused tests** overlap with the joined population.
Fifteen legacy native cases remain deselected. Controlled private schedulers cover
pressure backoff, recovery, cancellation, deadline exhaustion, default routes,
caller-owned injection and complete cleanup without adding host load.

The end-to-end benchmark exercised actual production admission against the saved
pool. Its four process slots cannot fit the eight-slot reservation, so both cases
returned unaccepted capacity errors with **zero native launches and zero input
workspaces**. This qualifies refusal behavior, not successful native Tamarin
proving, native stress tolerance or many-core speedup. The benchmark took
**0.355 seconds** inside the driver and
**0.716 seconds** including the wrapper.
Pool policy and the real sampler configuration remained unchanged; owned leases
and waiters drained. Capacity refusal does not establish pressure sampling during
that acquisition. All 2,648 artifact bodies from 26 prior qualifications remain
unchanged.

Next work is native qualification under a separately reviewed adequate capacity
policy, complete Tamarin claim-set/source binding, semantic attack reconstruction
and the remaining Hyper default-runner migration. No pool widening, tool downloads
or installer changes were performed. CodebaseIR producer inventories remain
27 verification and 29 applicability modules; this increment adds no cache replay,
DuckLake indexing, learned representation or planner authority.

Evidence: `workspace/tamarin-default-admission-qualification-20261004/REPORT.md`
and its `qualification.json` in the datasets repository.

## Tamarin source and lemma binding — 2026-10-04

The canonical Tamarin backend now binds results to a nonempty, unique and complete
claim/lemma mapping derived from the actual compiled source. It ignores quoted and
commented pseudo-declarations, rejects duplicate/unsupported declarations and checks
trace quantifiers. Identical verdicts deduplicate; conflicting, unknown, missing or
malformed results remain quarantined. Diagnostic IDs cannot impersonate declared
claims, and quarantine IDs remain unique. Source text, request bounds and digest
bindings remain intact.

Native parsing reads the last summary per stream with complete result rows and a
closed metadata format. Echoed source cannot supply missing results; malformed rows,
unexpected summary text and wellformedness warnings block acceptance. Every parsed
falsified result now carries no attack trace, including existential failures that
report no trace found. Rule/marker text therefore cannot produce automatic attack
replay authority through the canonical backend or V2. The separately called legacy
trace utility remains structural only.

The binding scanner supports ordinary ASCII lemma names, `(modulo E)`, the
`sources`, `reuse`, `use_induction` attributes and universal/existential trace modes.
Preprocessing and other syntax conservatively refuse binding. This scanner does
not replace native syntax or semantic validation. Expected names `analyzed` or
`output` may conservatively conflict with summary metadata. Direct parser calls
without source retain map-only compatibility; complete legacy rows remain supported
when neither a native summary nor a theory echo is detected. These compatibility
paths do not attest native output authenticity.

Validation passed **2,858 joined tests**, retaining all 2,771
previous cases and adding **87 new cases**.
The **734 focused passes** overlap the joined population;
15 legacy native cases remain deselected. Four retained fixture files now assert
UNKNOWN/no replay for unvalidated falsification, preserving resource and identity
checks.

All **15 controlled E2E cases** passed across direct, registry and standalone V2
routes. Synthetic availability, solver output and healthy pressure used an isolated
scheduler, while the default runner, compiler, parser, workspace lifecycle and
evidence projections executed unchanged. Native launches and shared-pool access
were zero; workspaces and leases drained. The benchmark took
**0.556 seconds** in the driver and
**0.916 seconds** including the wrapper.

The benchmark also recorded **36 serial parser timing samples** across 10, 100 and
1,000 lemmas with complete, unknown, conflicting and missing outputs. The complete
1,000-lemma case had a median of **7.251 ms**. Timings include source/claim
binding and output parsing, excluding classification and serialization. They do
not establish native proving speed, native stress tolerance or many-core scaling.
The full table and raw samples are retained in the qualification.

All **2,764 artifact bodies from 27 earlier qualifications** remain unchanged.
The shared pool was not accessed or resized. Successful native Tamarin startup and
summary qualification under an adequate reviewed policy remain open, alongside
broader syntax/compiler coverage, semantic attack reconstruction and the Hyper
default-runner migration. The previous four-slot saved pool still cannot fit the
eight-slot Tamarin estimate. CodebaseIR producer inventories remain 27 verification
and 29 applicability modules; this increment adds no learned representation,
index/cache replay or planner authority.

Evidence: `workspace/tamarin-claim-binding-qualification-20261004/REPORT.md` and
`qualification.json` in the datasets repository.

## Hyper engine default admission and V2 bounds — 2026-10-04

HyperLTL, AutoHyper and MCHyper now use lazy shared admission for their owned
default runners: two CPU slots, four process slots, and the caller's requested
memory as the reservation and sampled process-tree RSS ceiling. Admission waits
consume the same native invocation deadline, and ambient proof-operation stops
remain effective. Discovery creates no scheduler state or native processes.
Standalone V2 now forwards caller bounds to `check`, aligning actual limits with
its evidence. Default version access is inert; declared identity versions remain
available without an extra `--version` subprocess.

Owned profiles set finite CPU and per-process address-space limits. Address space
is `max(2 GiB, 4 × requested RSS)`, or `max(4 GiB, 4 × requested RSS)` for AutoHyper.
AutoHyper uses `DOTNET_PROCESSOR_COUNT=1`, `DOTNET_gcServer=0` and a hexadecimal
`DOTNET_GCHeapHardLimit` equal to half the requested memory (minimum one byte).
Conflicting GC aliases/per-heap overrides are removed; required runtime paths are
preserved. CPU/process reservations are estimates, GC heap is not total memory,
and RSS sampling can overshoot. Native startup under these profiles is unqualified.
AutoHyper retains its documented `RLIMIT_FSIZE` compatibility exception: workspace
size is checked after execution, with no live disk-write ceiling.

Unsafe resource, cancellation, timeout, cleanup, process-tree, error, output-limit
or malformed-stream conditions block verdict/witness interpretation. Conclusive
verdicts require an exact integer zero exit status. A clean unsupported-fragment
exit remains nonconclusive `UNSUPPORTED`. Results retain lifecycle metadata and
stream digests. NUL-containing output is rejected and sanitized in receipt text;
metadata and byte usage retain the original stream binding. Explicit plain,
falsey and admitted runners retain caller-owned resource/environment profiles;
an explicit admitted runner must supply finite limits itself. Safe explicit-runner
version probes remain a separate three-second metadata call. Custom backend
`check` overrides must accept the new `bounds` keyword for V2.

Validation passed **2,993 joined tests**, retaining all 2,858 previous
cases and adding **80 new admission cases** plus 55 existing Hyper
integration cases. The **469 focused passes** overlap that population;
15 legacy native cases remain deselected. The retained initial focused attempt
found the exit-2 compatibility regression, which was corrected before final runs.

All **26 controlled end-to-end cases** passed: direct and V2 execution for every
engine, the actual HyperLTL registry delegate, resource-failure rejection,
impossible-capacity refusal and nine pressure/recovery samples. Each uses an
isolated private scheduler, synthetic engine output/discovery and synthetic host
pressure. Actual admission queues backed off before any workspace/executor work,
then recovered after pressure release; owned leases, waiters and workspaces drained.
Median controlled admission waits: hyperltl **20.71 ms**, autohyper **20.72 ms**, mchyper **20.85 ms**. These timings include an intentional
20-ms fixture backoff and do not measure native proving or many-core scaling.
Driver time was **1.970 seconds**, or **2.418 seconds**
including the wrapper. Native launches and shared-pool accesses were zero.

All **2,883 artifact bodies from 28 previous qualifications** remain unchanged.
CodebaseIR producer inventories remain 27 verification and 29 applicability
modules, with no additional cache/index, learned-IR or planner authority.

Remaining gaps: registry AutoHyper/MCHyper aliases currently select HyperLTL;
standalone V2 whole-operation budgeting/cancellation; explicit-runner version
budgeting; native Hyper startup/stress/scaling; hard aggregate containment and
AutoHyper live disk bounds; semantic witness qualification. Tamarin native startup,
broader syntax and semantic attack reconstruction also remain open.

Evidence: `workspace/hyper-default-admission-qualification-20261004/REPORT.md`
and `qualification.json` in the datasets repository.

## Independent Hyper engine registry routing — 2026-10-04

`hyperltl`, `autohyper` and `mchyper` now select their own lazily constructed,
independently cached backends through the default registry. Previously those IDs
were aliases for the combined family and all selected HyperLTL. Each engine keeps
default resource admission, caller bounds, request identity and typed engine
evidence. Generic bounded results remain UNKNOWN and confer no theorem authority.

The legacy `hyperltl_autohyper_mchyper` ID still executes HyperLTL, and implicit
provider ordering is preserved. To select an engine, set its canonical ID in the
request, or leave the request ID empty and pass that engine as the explicit
selector. If both are present they must agree. A legacy-family request paired
with an individual-engine selector is now a conflict, rejected before delegate
construction. Missing engines do not silently select a peer.

The provider catalog, conformance axes, alignment PATH probes and source audit now
agree on 18 executable provider IDs (20 including advisory entries). Three current
generated JSON catalogs were refreshed with retained before/after bytes. These
declarations and source observations do not establish installed native capability.

Validation: **3,195 joined tests passed**, retaining all 2,993 previous cases and
adding **41 new routing cases** plus 161 existing catalog/API checks. The final
selection deselects 19 native cases. Earlier focused validation passed 519 tests;
518 overlap the final joined population, so counts are not added. The first
attempt's two fixture errors and stale generated audit were corrected and retained.

All **29 controlled E2E benchmark cases** passed. With three concurrent engines
and a private pool sized for two jobs, the scheduler observed two active leases
and one waiting request, then drained all leases, waiters and workspaces. The pool
had four CPU slots, 256 MiB and eight process slots; each request reserved two CPU
slots, 128 MiB and four process slots. The driver took **0.694 seconds**
(**1.166 seconds** including its wrapper). Discovery, engine output
and pressure samples were synthetic; the registry, admission, workspace and result
binding paths executed. This measures controlled routing, not native proof speed.

Validation scope: earlier focused attempts inadvertently included uninstrumented
legacy API tests capable of native/portfolio execution. Their native and shared-pool
activity is **unmeasured**. All four such API cases are excluded from the final
joined selection. Zero native launches/shared-pool accesses applies only to the
guarded new routing fixtures and controlled benchmark, not the entire turn.

All **3,014 artifact bodies from 29 prior qualifications** remain unchanged.
CodebaseIR producer inventories remain 27 verification and 29 applicability modules;
this increment adds no learned representation, cache/index replay or planner authority.
Remaining gaps include standalone Hyper V2 whole-operation budgets/cancellation,
explicit-runner version budgets, native startup/stress/many-core scaling, aggregate
containment, AutoHyper live disk limits and semantic witness qualification. Tamarin
native startup, broader syntax and semantic attack reconstruction also remain open.

Evidence: `workspace/hyper-registry-routing-qualification-20261004/REPORT.md`
and `qualification.json` in the datasets repository.

## Hyper whole-operation budgets and cancellation — 2026-10-04

Standalone Hyper V2 execution now establishes a cooperative operation deadline by
default from the request timeout. The engine constructor, `execute`,
`execute_split_capabilities` and convenience helpers accept `operation_timeout_ms`
and `cancellation`. A per-call timeout overrides the constructor default, capped by
the declared request timeout; a tighter enclosing operation still wins. Constructor,
call and enclosing cancellation signals combine, and observed stops remain latched.

One budget covers normalization, capability callbacks, translation, admission,
native execution, metadata, witness handling and evidence construction. A split
shares that budget across all three engines; interruption raises
`ProofOperationTimeout` or `ProofOperationCancelled` without returning a partial
mapping or late evidence. Python callbacks are checked at boundaries and cannot be
forcibly preempted. Cleanup may extend beyond the deadline.

Native and explicit-runner version invocations use the remaining enclosing budget.
Requests, declared bounds and receipt timeouts retain their original values;
effective invocation limits are recorded separately. Default admission and memory
profiles remain in place. Falsey injected backends/engines retain ownership, and
legacy callback signatures are called once without retry. Direct adapter checks
and standalone capability probes do not create a new operation scope themselves;
they observe an existing enclosing scope.

Validation passed **3,290 joined tests**, including **95 new cases** and all
3,195 previously retained cases. The **594 focused passes** overlap this population;
19 native cases remain deselected. The first full run passed, but an external
scheduler edit occurred during it. That edit only adds timeout diagnostics; both
generations were retained and reviewed, and the complete suite was rerun with
stable source hashes. A subsequent diagnostic-only edit bounds the timeout lane
text; the benchmark used that later stable generation. The full suite ran against
the preceding generation. Owned Hyper code was identical in both runs, and the
exact dependency hashes and review of both deltas are retained.

All **19 controlled E2E benchmark cases** passed, including six queued stops,
three external-pressure recovery fixtures, successful splits and two interrupted
splits. All eight stopped calls returned no result. Private leases, waiters and
workspaces drained. Driver time was **3.153 seconds**, or
**3.672 seconds** including its wrapper. Discovery, solver
output and pressure were synthetic; native launches and shared-pool accesses were
zero in this benchmark. These measurements do not establish native preemption,
real host-pressure resilience, proof throughput or many-core speedup.

All **3,150 artifact bodies from 30 earlier qualifications** remain unchanged.
CodebaseIR inventories remain 27 verification and 29 applicability modules; no new
learned representation, cache/index replay or planner authority is established.
Remaining work includes native Hyper startup/stress/scaling, hard aggregate
containment, AutoHyper live disk limits and semantic witness validation. Explicit
runner metadata outside an enclosing scope still uses its separate three-second
limit. Tamarin native startup, broader syntax and semantic attack reconstruction
also remain open.

Evidence: `workspace/hyper-operation-control-qualification-20261004/REPORT.md`
and `qualification.json` in the datasets repository.

## Hyper counterexample structural validation — 2026-10-04

Native Hyper witness parsing now requires exact declared trace labels and complete,
unique approved assignments. It rejects ambiguous fields, inconsistent DIFF rows,
malformed Unicode/control records and inputs exceeding finite byte/line/field/trace
limits. Differences and digests are recomputed; no missing difference is fabricated.
Context-bound validation requires exactly two forall traces, equal low-input and
subject projections, and a genuine approved observation difference. Native bundles
require explicit `observation_map`, `quantifier_order` and `formula_id`; manual replay
also requires expected `formula_id`. V2 rechecks the actual request, including
reconstructed positive witness claims. Incomplete legacy witness fixtures must be
updated to include every approved public, observation and subject field.

Validation: **3390 selected tests passed**, retaining all **3290** previous
cases and adding **100**; **694** focused tests passed. The same
19 native-capable legacy cases remain deselected. **36 controlled end-to-end cases**
cover three engines, three routes and valid/malformed/equal-observation/unequal-low
witnesses, using default managed runners and a private 2-CPU / 128-MiB / 4-child-slot
pool. All leases and workspaces were released; guarded native launches and shared
pool accesses were zero. Timings measure synthetic-executor orchestration and
structural validation; they do not establish native throughput or many-core speedup.

Engine-reported `VIOLATED` remains separate from witness validation; generic registry
results retain `UNKNOWN` and no theorem authority. The legacy `replayed` flag means
only structural projection validation. Native reachability, temporal semantics,
high-input variation and output authenticity remain unvalidated. The bounded
self-composition evaluator retains its separate non-authoritative bundle path.
Canonical witness raw text retains approved assignments only; original receipt
stdout/stderr are still captured separately. Earlier qualifications and 27 verification
/ 29 applicability producer inventories are preserved. Native startup/profile,
real external-pressure stress, aggregate containment and scaling gaps remain open.

Evidence: `workspace/hyper-counterexample-validation-qualification-20261004/REPORT.md`.

## Default live workspace guard — 2026-10-04

The shared bounded subprocess runner now inspects private workspace logical bytes,
entry count and directory depth before launch, about every 100 ms between completed
samples, and after execution. This is enabled by default, including AutoHyper's
explicit per-file-limit opt-out. Entry/depth defaults are 16,384/64, with configurable
hard ceilings of 1,000,000/256. POSIX traversal uses no-follow directory descriptors;
symlinks and special files count as entries without reading their targets or bodies.
Non-transient inspection errors fail conservatively. Cancellation/deadlines are
checked between scan steps and immediately before launch. A normalized executor
exception is preserved without calling a failed cancellation callback again.

Observed workspace overruns terminate through the existing process-tree cleanup
and remain latched even when a SIGTERM handler removes files and exits zero. Final
checks cover injected executors too; stopped or failed runs can interrupt that scan.
The admission lease remains held through process/workspace cleanup. Per-file limits,
AutoHyper runtime settings and scheduler capacities are unchanged. A previous test
expecting an over-budget process to exit zero now permits earlier termination while
still requiring resource/workspace failure.

Validation: **3522 selected tests passed**, retaining all **3390** previous
cases, adding **56** new guard tests and selecting **76** existing
process tests. **477** focused tests passed; the same 19 native-capable
legacy cases remain deselected. The retained first focused attempt exposed three
callback-error cleanup regressions, which were fixed before the accepted runs.
**12 real Python-process benchmark cases** passed in **2.397s**,
with one owned child and two waves of two concurrent jobs. The private pool had capacity
2 CPU / 256 MiB / 4 child slots; each job reserved 1 CPU / 128 MiB / 2 child slots,
with finite wall/CPU/AS/RSS/output limits and an 8-KiB workspace budget. Scheduled writes totalled 242,688 bytes across all cases.
Healthy/exact-budget runs succeeded; all eight overruns and the cancellation were
refused, including two delete-on-shutdown cases. Processes, workspaces and leases
drained; shared scheduler access was zero. These are real process-lifecycle tests
with synthetic healthy resource samples, not installed solver or pressure tests.

This is sampled logical-size protection, not a disk quota. Between-sample overshoot,
external-path writes and open-unlinked files are outside the guarantee; hard links
are conservatively counted per entry and sparse files by logical size. Filesystem
calls/cleanup are not forcibly preemptible. The portable path-based fallback is not
a hostile-race security boundary; native qualification here is Linux only. Native
solver startup, real-pressure stress, hard aggregate containment, temporal witness
replay and many-core scaling remain open. A separate Hyper follow-up is immutable
evidence plus complete request-ID/digest/bounds binding during reconstruction.

All **3440 artifact bodies from 32 prior qualifications** remain unchanged. Current
CodebaseIR producer inventories still contain 27 verification / 29 applicability
modules; only the process module hash changes. Historical records retain their
original pins, and strict current-generation cache checks are not relaxed. This
increment adds no proof-cache migration, learned representation or planner authority.

Evidence: `workspace/process-workspace-guard-qualification-20261004/REPORT.md`.

## Hyper V2 evidence integrity — 2026-10-04

Hyper V2 request/evidence payloads and attached translation mappings now freeze
nested containers, and public JSON exports return detached values. Supplied
evidence content digests are checked against the existing digest preimage; the
schema and digest algorithm are unchanged. Reconstructing a result checks its
request ID/digest/source references, document/formula/system, declared execution
bounds, typed backend result, translation and receipt links. Structural witness
validation remains bound to the actual request; a path declaring no evidence
cannot carry a counterexample or witness bundle. Each payload copy is limited to
16 MiB of UTF-8 string content, 65,536 nodes and depth 64, with cooperative
operation checkpoints.
Existing UTF-8 and ASCII digest encodings are preserved. Receipt identity checks
restore the declared timeout float from the request bounds before hashing.
Attached translations must match the canonical engine renderer, projection maps
and auxiliary files for the retained request; internally consistent custom
translations that differ from those canonical bindings are rejected. Callers
editing payloads must use detached public `to_dict()` values to rebuild records.
No existing test files changed.

Validation: **3652 selected tests passed**, retaining all **3522** previous
cases and adding **130**; **608** focused tests passed. The
same 19 native-capable legacy cases remain deselected. **12 controlled end-to-end
cases** passed in **0.445s**: three engines with satisfied
and violated outputs, three capability probes, mock/fallback-payload rejection,
and bounded evaluator fallback through an explicitly unavailable discovery
fixture. Six production managed-runner paths executed against private
2-CPU / 128-MiB / 4-child-slot pools with synthetic outputs and healthy host samples.
All **108 binding mutations** and **93 nested mutation attempts** were
rejected; all 12 records retained stable public wire projections and digests.
Workspaces and leases drained; guarded native launches and shared pool access
were zero. Timings measure these mixed controlled paths, not native throughput.

Reconstruction retains the typed request/source/model: the existing request wire
contains digests and trace counts, not complete raw documents, models or private
trace contents. This adds no standalone full-result JSON decoder or private-trace
content binding. Public `to_dict()` exports are the supported detached snapshots;
no `deepcopy(MappingProxyType)` contract is added. Consistent records and valid
digests do not establish solver authenticity, signatures, model membership or
temporal witness replay. Mock, supplied fallback and capability-only paths retain
no proof or theorem authority. Bounded evaluator fallback remains separate from
native structural replay. Real external-pressure stress, hard containment and
many-core scaling remain open.

All **3523 artifact bodies from 33 prior qualifications** remain unchanged,
including every retained earlier attempt. The 27 verification / 29 applicability
producer inventories are unchanged. No cache authority, learned CodebaseIR or
planner authority is added by this increment.

Evidence: `workspace/hyper-evidence-integrity-qualification-20261004/REPORT.md`.

## Hyper bounded fallback applicability — 2026-10-04

V2 fallback result construction now re-evaluates the retained traces with the
canonical bounded evaluator and checks the resulting disposition, redacted
counterexample, witness bundle and successful evaluator reason suffix. A same-count trace substitution can no longer
retain a violation witness that the supplied traces do not support. Equivalent
private-value renaming and trace permutation remain accepted when these public
outcomes agree. This establishes outcome applicability, not private-trace identity.
The V2 wire format and digest algorithms remain unchanged; the request descriptor
still binds trace count rather than private contents, and no public private-input
hash is added. Generic `BackendRequest` payload redaction is unchanged.
The generic registry retains its availability veto: a missing tool stops before
the fallback delegate runs. Missing-tool registry fallback remains an integration
gap; the actual fallback qualification here covers the direct/V2 paths.

Trace normalization has finite limits of 16,384 records, 262,144 nodes, 16 MiB of
UTF-8 string content, depth 32 and 4,096-bit integers. Normalization, bounded
selection, pair evaluation and witness publication have cooperative checkpoints.
Direct backend normalization and fallback use separate bounded operation scopes,
with discovery between them; this is not a single aggregate deadline for the
whole direct run. V2 reconstruction uses bounded operation control, and nested
validation inherits a tighter parent deadline and cancellation.
These limits bound input traversal/copy work, not process RSS or opaque callback
execution. They do not establish hard preemption or aggregate memory containment.

Validation: **3738 selected tests passed**, retaining all **3652** previous
cases, adding **70** new tests and selecting **16** existing
core evaluator tests; **694** focused tests passed. The
same 19 native-capable legacy cases remain deselected. **15 controlled end-to-end
cases** passed in **0.730s**: all three providers exercise
violated, clean and limited fallback evaluations, followed by three managed
engine paths with synthetic SAT output and three typed cooperative stops.
The nine fallback cases invoke the actual evaluator and canonical revalidation.
**21 changed outcomes were rejected**, **18 equivalent outcomes were accepted**,
and all **three interrupted operations withheld results**. The interruption
fixture sets cancellation or consumes the deadline at entry to the actual
evaluator, including a second-evaluation stop during result validation.

The managed paths retain private 2-CPU / 128-MiB / 4-child-slot pools. Discovery,
native-shaped output and healthy host samples are synthetic. Three synthetic
executor calls ran; actual native launches and shared pool accesses were zero.
Workspaces and owned leases drained. Private fixture sentinels were absent from
recorded results and errors. Mixed-path timings include an intentional deadline
delay and are not a native proof-throughput or parallel-scaling measurement.

Clean and limited fallback results remain UNKNOWN; fallback violations remain
bounded and do not establish external-engine or theorem authority. Successful
evaluations require the canonical reason suffix; the unsupported branch does not
claim exact canonical reason binding. Exact private values remain unbound. Broader
declassification behavior, missing-field semantics, whole-private-map comparison
and `max_steps` disclosure semantics are unchanged. Native authenticity,
model membership, general temporal replay, real external-pressure stress and
many-core scaling remain open.

All **3695 artifact bodies from 34 prior qualifications** remain unchanged,
including every retained earlier attempt. The 27 verification / 29 applicability
producer inventories are unchanged. No existing test files changed. No cache,
learned CodebaseIR or planner authority is added by this increment.

Evidence: `workspace/hyper-fallback-validation-qualification-20261004/REPORT.md`.

## Request-scoped Hyper registry fallback — 2026-10-04

The default registry can now use bounded local fallback when the selected Hyper
tool is missing, the request opts in with exact boolean `allow_fallback=True`,
and nonempty traces are supplied. Eligibility is checked for that request and
the matching canonical HyperLTL, AutoHyper, MCHyper or legacy-family delegate.
Public native availability remains false. Caller-defined availability contracts
remain in force; their refusals, probe failures and explicit vetoes do not acquire
the missing-tool exception. The delegate rechecks discovery. With default
adapters, a newly available tool uses the ordinary resource-admitted native
runner; caller-provided runners keep their existing contract.

This closes the narrow missing-tool registry fallback gap recorded in the prior
qualification. The six existing gate tests now expect the opted-in behavior;
their original bodies and case IDs are retained as historical evidence. Prior
qualification reports and artifacts remain unchanged.

Validation: **3809 selected tests passed**, retaining all **3738** previous
cases and adding **71**; **989** focused tests passed. The
same 19 native-capable legacy cases remain deselected. **20 controlled results**
passed in **0.535s**: the four selectors each cover
violated, clean and limited fallback; paired negatives cover disabled opt-in,
empty traces, an explicit availability veto and a discovery failure. Two stops
produce bound CANCELLED/TIMED_OUT attempts with generic UNKNOWN results. Two
overlapping calls on one registry demonstrate that an opted-in fallback does not
enable a concurrent request lacking opt-in.

The actual bounded evaluator produced **13 fallback outcomes**, with **five
unavailable refusals** and **two normalized stops**. The registry preserves typed
redacted outcomes while every generic result remains UNKNOWN. Private fixture
sentinels are absent from recorded outcomes and errors. Full generic requests
are not persisted by this benchmark: their existing payload format contains
trace inputs, so artifacts store only safe descriptors, trace counts and request
digests. This artifact policy does not change generic request redaction or remove
the existing request digest's commitment to its payload.

Discovery is synthetic; availability is never forced true and evaluator results
are not injected. Actual native launches, transports and scheduler accesses were
zero. Pure Python fallback does not acquire scheduler leases or provide host
pressure backoff. It retains finite input/evaluation bounds and cooperative
operation cancellation, without hard RSS containment or opaque callback
preemption. Timings include controlled deadline and rendezvous delays and do not
measure native proving throughput or many-core scaling. V2 outcome applicability,
private-trace identity limitations and broader evaluator semantics are unchanged.

All **3856 artifact bodies from 35 prior qualifications** remain unchanged,
including retained earlier attempts. The 27 verification / 29 applicability
producer inventories are unchanged. This increment changes two production files
and the six expectations in one existing test file. It adds no theorem, cache,
learned CodebaseIR or planner authority.

Evidence: `workspace/hyper-registry-fallback-qualification-20261004/REPORT.md`.


## Hyper installer hardening and Python admission — 2026-10-04

Hyper fallback and V2 applicability reevaluation now use default scheduler
admission: one CPU, the requested finite memory reservation, and zero process
slots. Admission waits under external pressure and honors cancellation and the
aggregate deadline. This supersedes the earlier note that Python fallback has
no scheduler admission. Already admitted Python work is not paused by subsequent
host pressure, and reservations do not impose a hard Python RSS ceiling.

The Hyper installer now streams digest-checked downloads into unique temporary
files; limits compressed/expanded bytes, archive structure and hashing; rejects
unsafe members and redirects; serializes same-tool installations; and retains
the previous tree and launcher through identity audit and publication. Build
and probe subprocesses acquire scheduler capacity by default. Their CPU, memory,
output, workspace and time controls also apply during cancellation and cleanup.
AutoHyper output and its temporary package cache stay inside the guarded source
workspace. Lazy setup supports reviewed dependency roots and retry after an
interrupted attempt. Missing dependencies remain explicit blockers.

Validation: **4,060 selected tests passed**, including all 3,809 prior cases,
177 new cases and 74 newly selected existing setup tests; **1,163 focused tests
passed**. The same 19 legacy native cases remain deselected. Nine controlled
installer benchmark groups passed in **1.035 s**, using eight actual small
Python subprocesses, with concurrent requests, rollback, pressure recovery and
cancellation. Eight Python admission cases passed in **0.454 s**, including
three queued cancellations and two overlapping reservations. All owned leases,
waiters and subprocesses drained. Pressure was injected through private sampler
fixtures; these timings are not many-core proving throughput measurements.

Fresh official pinned EAHyper, AutoHyper and MCHyper main-source archives all
passed actual download, digest and extraction checks (19,723,238 compressed
bytes total). Full fresh upstream compilation and native Hyper proving remain
unqualified; required toolchains are not on this host's PATH. Automatic
provisioning of those dependencies and real many-core proving benchmarks remain
follow-up work. Sampled process limits can overshoot; no hard aggregate memory
or disk guarantee is claimed. Import/discovery does not initiate installation.
No proof-cache, learned CodebaseIR, or planner authority is added.

Evidence: `workspace/hyper-installer-resource-qualification-20261004/REPORT.md`.
All 3,975 artifact bodies from 36 earlier qualifications and the 27/29 producer
inventories are preserved. Earlier failed attempts remain in the new report.

Explicit vendor setup uses the existing public entry points:

```python
from ipfs_datasets_py.logic.backends.installers.hyperproperty import ensure_hyperltl
from ipfs_datasets_py.logic.backends.installers.install_control import HyperInstallLimits

receipt = ensure_hyperltl(
    yes=True,
    vendor=True,
    strict=False,
    limits=HyperInstallLimits(),
    operation_timeout_ms=30 * 60 * 1000,
)
print(receipt.to_dict())
```

The default profile bounds each archive at 256 MiB compressed and 1 GiB of
expanded file data, with 32,768 members. Each build/probe reserves one CPU,
1 GiB resident memory and four process slots; its address-space ceiling is
8 GiB, captured-output limit is 1 MiB and guarded-workspace limit is 2 GiB.
The single operation budget includes lock waits, transfers, audits and commands.
Pass a cancellation signal with `is_set()` to `cancellation`, and use
`dependency_roots` for explicitly supplied reviewed toolchain locations. A
missing toolchain yields a blocked receipt. `ensure_autohyper`, `ensure_mchyper`
and `ensure_hyperproperty_vendor` accept the same controls. For an existing
scheduler envelope, pass `parent_lease`; for an isolated configured pool, pass
`scheduler`. These options are mutually exclusive. Archive hashing and extraction
are bounded cooperative work but do not themselves acquire a scheduler lease.


## Native Hyper setup validation — 2026-10-04

The native Hyper gap is now narrower: EAHyper, AutoHyper and MCHyper were built
from fresh pinned main-source downloads into an isolated prefix, using the
existing managed compiler/runtime dependencies outside PATH. The actual shared
scheduler and default installer limits governed all 42 top-level build/probe
launches. All three installations passed identity audits and cached reuse
without additional native commands. The complete build run took **43.867 s**
(EAHyper 11.817 s, AutoHyper 11.191 s, MCHyper 20.805 s).

Five native smoke checks passed through the default admitted adapters in
**6.316 s**: EAHyper satisfiability, plus holding and violating models for
AutoHyper and MCHyper. Each check reserved two CPUs, 512 MiB and four process
slots, with a 30-second operation budget. Owned leases, processes and workspaces
were released, and vendor identities were unchanged. This supersedes the prior
absence of fresh native build/check evidence; these small cases do not establish
many-core speedup or a complete semantic certification.

New setup utilities provide an inert dependency plan and explicitly authorized
repair of MCHyper's three pinned provenance archives. The actual missing AIGER,
ABC and Python source archives were downloaded into a separate cache and
checksum-verified. Filesystem candidates remain unvalidated until normal
installer probes and audits pass. Invalid explicit executable roots now fail
before probes instead of silently selecting a PATH tool; explicit archive
paths remain authoritative during repair.

**4,137 selected tests passed**, preserving all 4,060 previous cases and adding
77 (42 resolver and 35 setup cases); **1,063 focused tests passed**. The same
19 legacy native cases remain deselected; this increment's five native checks
ran separately. All **4,561 artifact bodies from 37 prior qualifications** and
the 27/29 producer inventories remain preserved.

Remaining work includes reviewed compiler/runtime provisioning on a clean
machine, larger mixed-solver parallel workloads, and pressure-response/scaling
qualification. The native builds reused existing compiler installations; the
setup utility repairs provenance archives and does not bootstrap those
compilers. Reservations and sampled process guards remain estimates rather
than hard aggregate memory/disk limits. This adds no learned CodebaseIR,
proof-cache or symbolic-planner authority.

Evidence: `workspace/hyper-native-setup-qualification-20261004/REPORT.md`.

This workflow starts with inert discovery, then explicitly prepares archives and installs MCHyper:

```python
from ipfs_datasets_py.logic.backends.installers.hyperproperty_setup import (
    plan_hyperproperty_setup, prepare_hyperproperty_dependencies,
)
from ipfs_datasets_py.logic.backends.installers.hyperproperty import ensure_mchyper

plan = plan_hyperproperty_setup("mchyper")
print(plan["blockers"])

# Explicitly fetch or verify the three pinned provenance archives.
prepared = prepare_hyperproperty_dependencies("mchyper", yes=True)
receipt = ensure_mchyper(
    yes=True, vendor=True, strict=False,
    dependency_roots=prepared["dependency_roots"],
)
print(receipt.to_dict())
```

`install_root` on the setup utilities names the existing managed dependency
base. The engine installer's `install_root` may instead name a fresh destination.
Set `archive_cache_root` to keep provenance archives in a separate cache; an
explicit `dependency_roots` archive path takes precedence. Preparation accepts
the same finite operation/cancellation controls as installation. Omitting
`yes=True` returns only the plan. Successful preparation verifies archive bytes;
compiler versions and native engine identity still require the installer audit.

The repeatable native build and smoke drivers are
`benchmarks/bench_hyper_native_setup.py` and
`benchmarks/bench_hyper_native_smoke.py`. The former requires fresh evidence and
installation directories and accepts a per-tool dependency-root JSON mapping.
The latter consumes an audited installed prefix and records actual native
outcomes; neither substitutes solver results or a resource sampler.


## Hyper setup integrity and bounded parallel validation — 2026-10-04

MCHyper preparation now rejects conflicting archive destinations before any
transfer, rehashes the final archive set under the original operation budget,
and refuses a verified result if files change during validation. Explicit GHCup
aliases also retain precedence over automatically discovered managed roots.
Three fresh official provenance archives passed actual download, final hashing
and cache-reuse checks in **4.366 s**. Verification records observed bytes; it
does not lock the cache against later writers or provision missing compilers.

The native benchmark ran the same ten EAHyper/AutoHyper/MCHyper fixtures serially
and with two workers through unchanged default admitted adapters and the actual
shared scheduler/host sampler. The serial phase took **1.812 s** and the parallel
phase **0.896 s**, with sampled live native-root peaks of one and two. All twenty
native cases passed, and owned processes, workspaces and leases drained. The
**2.022** elapsed ratio is one sequential-then-parallel trial on small repeated
fixtures, not evidence of general many-core scaling or CPU utilization.

A separate scheduler-only check filled a 4-CPU/1-GiB/eight-process parent
envelope with two children, observed its uniquely identified third child wait,
and released capacity. Admission resumed in **0.058 s**; all four leases and
the owned waiter drained. This exercises parent-capacity contention, without
manufacturing host pressure or reserving the whole shared pool.

The first native attempt encountered actual kernel memory-stall pressure
(**20.89%** at the retained refusal, above the default **2%** threshold).
Default admission launched no solver, and the request timed out after its
30-second budget with no leaked waiter or reservation. After three unmodified
sampler readings below the stall thresholds, a separate retry completed the
native benchmark. This establishes an observed natural-pressure refusal and a
later successful retry; it does not establish the cause of that pressure or
recovery of the original timed-out request. No safety threshold was relaxed.

**4,215 selected tests passed**, retaining all 4,137 previous case IDs and adding
78 (29 setup-integrity and 49 benchmark cases). **1,141 focused tests passed**;
the same 19 legacy native cases remain deselected. Both native attempts and the
superseded focused test generation remain recorded. All **4,796 artifact bodies
from 38 earlier qualifications** and the 27/29 producer inventories are intact.

Next work is to pin compiler/runtime distributions per supported platform,
provide bounded runtime-specific extraction and installation recipes, and
qualify a clean-machine bootstrap. Larger mixed-solver trials need repeated
measurements and a safely isolated pressure environment. Existing reservations
and sampled guards remain estimates; no hard aggregate containment, semantic
witness certification or additional proof/planner authority is introduced.

Evidence: `workspace/hyper-parallel-setup-qualification-20261004/REPORT.md`.

To repeat the bounded benchmark against the retained native installation, use a
fresh output directory:

```bash
python benchmarks/bench_hyper_native_parallel.py \
  --install-root workspace/hyper-native-setup-installs-20261004/native-build-1 \
  --output-dir workspace/hyper-parallel-example \
  --workers 2 --cases 10 --aggregate-seconds 120
```

`--cases` accepts 5, 10 or 15 cases per phase; `--workers` accepts 1–4. Each case
retains the default 2-CPU/512-MiB/four-process reservation. The driver does not
install tools, alter resource telemetry or enable fallback. A refused admission
is retained as an incomplete attempt; wait for actual headroom before retrying
with a new output directory. The default 120-second aggregate deadline includes
both native phases and the contention check; cleanup may extend beyond it.


## Bounded .NET SDK bootstrap for AutoHyper — 2026-10-04

The separate `plan_dotnet_sdk_setup` / `ensure_dotnet_sdk` API provisions the
fixed .NET SDK 8.0.300 distribution used by the current AutoHyper vendor recipe,
with runtime 8.0.5 and reviewed Linux glibc ARM64/x64 archive pins. Planning and
`yes=False` remain inert. Provisioning requires `yes=True`; this API is not yet
connected to automatic lazy dependency installation. The fixed version is a
vendor compatibility target, not a recommendation to use it for other workloads.

The SDK archive is authenticated with its pinned SHA-512 before extraction.
Finite byte, member, path and depth limits constrain acquisition and extraction;
publication is transactional, and cache reuse derives a fresh archive inventory
and audits the installed tree. Staged and published version probes use owned
first-use directories and an isolated environment. The receipt identifies a
support dependency and grants no proof authority. Verification observes current
bytes; it does not make a writable installation immutable.

The default operation budget is 30 minutes. Native install commands retain the
existing one-CPU, 1-GiB sampled RSS, four-process admission request and finite
8-GiB address-space limit. These controls inherit cancellation and parent
deadlines; sampled guards and reservations do not guarantee aggregate process
containment. SDK acquisition reuses the host OS loader/libraries, and the
AutoHyper recipe still requires an existing reviewed Spot installation. OCaml,
GHC and other compiler provisioning remain separate work.

The cold-bootstrap driver uses fresh SDK/cache/engine destinations, then performs
AutoHyper build, cache reuse and two default-runner native smoke checks under one
operation. Large live trees stay outside the qualification artifact directory.
“Cold” describes fresh filesystem destinations, not cold OS or network caches;
these checks do not establish clean-machine portability, semantic witness
certification, many-core scaling or new proof-index/planner authority.


Current qualification is **blocked by host pressure**. All **4,393 selected
tests passed**, retaining all 4,215 previous case IDs and adding 178 cases
(SDK 40, archive 77, command controls 17, benchmark 44). **1,299 focused tests
passed**; the existing 19 native deselections remain. This establishes the
regression checks, not completion of the full fresh native pipeline.

The final fresh attempt authenticated and extracted the 217,385,231-byte SDK
archive and completed one staged native version probe. Its published-version
probe could not obtain admission: the observer retained 15 actual matching
memory-stall refusals against the unchanged 2% threshold, with the last sample
at 20.71%. The operation stopped after **49.637 seconds**; the transaction
removed the published SDK and staging payload, leaving only coordination-lock
metadata. No AutoHyper build or native solver ran in that final attempt.
Healthy preflight samples had preceded this attempt; they did not guarantee
continued headroom. These observations establish refusal and rollback, not
recovery of a timed-out request or the source of the host pressure.

Earlier attempts are retained. Two exposed an extra empty SDK metadata directory
created by the CLI restore/build route, correctly rejected by cache validation.
The recipe now uses direct MSBuild Restore/Build targets, owned caches and
explicit workload/signature controls. An earlier generation completed all seven
SDK/build commands and both authenticated cache checks, then timed out before
launching a native smoke solver. Its matching historical refusal record is not
uniquely bound to that smoke waiter. The final signature-control generation has
not completed the whole native pipeline. The first attempt's deciding admission
cause was not captured and is not inferred from later samples.

Full final-generation SDK bootstrap, AutoHyper build/reuse and two native smoke
checks remain pending a sufficiently healthy host. No safety threshold was
relaxed and no failed attempt is presented as complete end-to-end qualification.

Current status and retained evidence:
`workspace/hyper-dotnet-bootstrap-qualification-20261004/STATUS.md`.

Use explicit roots for the separate SDK setup step, then pass its verified root
to the ordinary AutoHyper installer. The outer scope below shares one deadline
and cancellation context across both steps:

```python
from pathlib import Path
from ipfs_datasets_py.logic.backends.installers.dotnet_sdk import (
    plan_dotnet_sdk_setup, ensure_dotnet_sdk,
)
from ipfs_datasets_py.logic.backends.installers.hyperproperty import ensure_autohyper
from ipfs_datasets_py.logic.backends.installers.install_control import installation_scope

root = Path("workspace/my-hyper-toolchain").absolute()
plan = plan_dotnet_sdk_setup(
    install_root=root / "sdk", archive_cache_root=root / "archives",
)
# Inspect the inert plan before deciding to provision this support dependency.
with installation_scope():
    sdk = ensure_dotnet_sdk(
        yes=True, install_root=root / "sdk", archive_cache_root=root / "archives",
    )
    engine = ensure_autohyper(
        yes=True, strict=True, vendor=True, install_root=root / "engines",
        dependency_roots={
            "dotnet-sdk": sdk["sdk_root"],
            "spot": "/absolute/path/to/existing/reviewed/spot",
        },
    )
```

`force=False` is the default. Reuse authenticates the cached archive and audits
the installed tree; it does not blindly accept an existing executable or
manifest. SDK cache reuse avoids native version probes. A failed or interrupted
setup retains the prior published tree through the installation transaction.

To repeat the fresh-destination end-to-end benchmark, choose two absent,
disjoint roots and supply the reviewed Spot prefix for this host:

```bash
python benchmarks/bench_hyper_dotnet_bootstrap.py \
  --output-dir workspace/my-dotnet-bootstrap-evidence \
  --work-root workspace/my-dotnet-bootstrap-live \
  --spot-root /absolute/path/to/existing/reviewed/spot
```

The driver retains failed results and partial logs, uses the actual default
shared scheduler and host sampler, and leaves installed files available for
reuse. Admission may refuse or time out under host pressure; it does not relax
safety settings or fall back to synthetic results. The benchmark does not
install Spot or OS libraries. Its fixed native fixtures are bounded smoke
checks, not a universal certification of the toolchain.

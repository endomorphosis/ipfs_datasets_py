# Isabelle setup and runtime qualification

The adapters use `process_theories` with a private theory directory and HOL parent session. Older launchers exposing only `version`, or lacking this tool, are reported unavailable. Capture uses `quick_and_dirty=true` solely to print an incomplete native goal. Reconstruction and the canonical kernel backend use `quick_and_dirty=false` and require an audit of the named theorem with no oracle dependencies before accepting the result.

Inspect the existing installation without downloads or heap builds:

```sh
python -m ipfs_datasets_py.logic.external_provers.isabelle_setup
```

Observe the existing HOL runtime with a fixed `True` theorem and named-theorem audit:

```sh
python -m ipfs_datasets_py.logic.external_provers.isabelle_setup --smoke --timeout 120
```

Explicitly install or repair the pinned, checksummed user-local distribution and observe its bounded smoke:

```sh
python -m ipfs_datasets_py.logic.external_provers.isabelle_setup --install --smoke --timeout 600
```

Only `--install` permits a download. With neither `--install` nor `--build-hol`, the setup CLI and `ensure_isabelle_ready()` use `prepare_isabelle_runtime()` with the shared resource scheduler enabled by default. The ordinary command check observes the pinned release and `process_theories` help. `--smoke` adds a no-build HOL preflight and the fixed audited theorem. JSON includes `bounded_preparation`, and `readiness_level` distinguishes `command`, `hol_ready`, and `kernel_smoke`. Require a successful overall `ready`/`usable` status; a completed earlier probe cannot override a later cancellation, deadline, or identity failure.

Omitting `--timeout` selects 120 seconds for inspection, 600 for installation,
or 3,600 for an explicit HOL rebuild. An explicit timeout replaces that default
and includes resource admission, lock waits and the requested operations.

## Resource-aware installed-runtime preparation

The Python API exposes command, HOL readiness, and smoke modes without downloading or explicitly building heaps:

```python
from threading import Event
from ipfs_datasets_py.logic.backends.installers.isabelle_preparation import (
    prepare_isabelle_runtime,
)

cancel = Event()
observation = prepare_isabelle_runtime(
    mode="hol",                 # "command", "hol", or "smoke"
    timeout_seconds=120,
    memory_mb=2048,
    cancellation=cancel,
)
print(observation.to_dict())
```

An explicit `install_root` can identify the outer installer directory or the inner distribution. Alternatively, pass its `bin/isabelle` path as `executable`. A malformed explicit selection is refused instead of falling back to another installation. Default discovery selects the managed installation without executing an unadmitted discovery subprocess. Launcher and configuration reads occur after admission and reject oversized or nonregular inputs.

Preparation reserves three CPU slots, twelve process slots, and `memory_mb + 256` MiB; the default is 2,304 MiB. Callers with an existing shared envelope can pass an actual `ResourceLease` as `parent_lease`, funded for those amounts, instead of acquiring an independent root. Each native phase obtains a fresh child reservation, so external pressure is checked between version, help, HOL preflight, and smoke. Pressure can delay admission until capacity returns or the deadline expires. Reservations do not impose a kernel process/thread ceiling.

All phases share one deadline covering admission, identity reads, and native work. The API accepts a timeout in `(0, 300]` seconds and resident memory from 1,024 to 4,096 MiB. The installed-only CLI path caps its requested preparation timeout at 300 seconds. Native execution uses the existing process-tree supervisor with cancellation, per-process CPU limits, sampled aggregate RSS, a 32 GiB per-process virtual-address limit, 32 KiB output per probe, 1 MiB input, and a 64 MiB workspace bound. Private Java and Poly/ML settings limit heap growth and computational parallelism. The supported preparation path requires Linux procfs and an enabled pressure-aware scheduler; it refuses unsupported guards. The address-space reservation is not physical memory consumption, and sampled RSS can overshoot between observations.

HOL readiness runs `isabelle build -n -b -j 1 -o threads=1 HOL`. A missing or stale heap returns `hol_heap_build_required`; preparation does not explicitly invoke a heap build. A later `process_theories` smoke may still attempt a rebuild if the trusted installation changes after that preflight. Such work uses the bounded phase and private workspace/settings. The preflight is therefore not a guarantee that a racing installation can never trigger a build.

The receipt records selected launcher/configuration identities before and after observation. Installed heaps, components, JVM, Poly/ML, and transitive native libraries remain trusted; selected hashes do not attest the complete distribution. The fixed smoke grants neither repository nor proof authority for another request. Its no-oracle audit also does not establish that HOL is axiom-free. A new theorem still requires its own fresh proof check.

Explicit `--build-hol` now uses the same admitted installation transaction as
`--install`. It rebuilds persistent system heaps in a separately extracted,
verified archive and publishes them only after validation. It never builds in
the active distribution or reports discarded private-HOME heaps as installed.
Without `--install`, only a retained archive with the pinned checksum may be
used; a missing cache returns `verified_archive_required` without downloading.
An existing runtime alone does not satisfy that requirement. See the explicit
build profile and completed native measurement below. The
[phase qualification](../../../workspace/isabelle-hol-build-qualification-20261002/REPORT.md)
records the final regression and retained failure history.

`IsabelleFrontend(auto_install=True)` and `IsabelleReconstructor(auto_install=True)` opt into lazy installation on first execution. Public Isabelle first-use installation reaches the bounded installation owner within its admitted operation; registry-directed installation selects that owner directly. Reconstruction also requires the request policy to permit network access. Capability discovery never installs. The public Isabelle adapters use bounded preparation by default; other legacy adapter paths retain their separate behavior. The current adapter supports simple theory and theorem identifiers and standalone HOL theories. Project sessions and alternate logic images need separate session configuration.

## Admitted installation and publication

Use the installation owner directly for an admission-inclusive deadline, cancellation, and a structured receipt:

```python
from threading import Event
from ipfs_datasets_py.logic.backends.installers.isabelle_installation import (
    ensure_isabelle_installation,
)

cancel = Event()
receipt = ensure_isabelle_installation(
    yes=True,
    install_root="/path/to/isolated/isabelle",
    timeout_seconds=600,
    cancellation=cancel,
    strict=False,
)
print(receipt.to_dict())
assert receipt.usable
```

With `timeout_seconds=None`, the owner selects 600 seconds for ordinary
installation or 3,600 when `build_hol=True`; explicit values must be in
`(0, 3600]`. Admission, installer-lock waits, worker execution, optional build
and native checks consume this same deadline. The API is Linux-only and
requires the pressure-aware scheduler; no safety-disable option is provided.
Ordinary installation reserves three CPU slots, twelve process slots and
`memory_mb + 256` MiB (2,304 MiB by default). Pass an existing actual datasets
`parent_lease`, or a `scheduler`, to retain that authority; do not pass both.
`memory_mb` must be an integer from 1,024 to 4,096. Root accounting is shared
with other proving work, and each worker or native phase acquires a fresh child
so outside pressure can defer new launches.

The archive worker only hashes, downloads and extracts into a controller-owned staging directory. It runs with a private HOME, a 512 MiB sampled RSS guard, 2 GiB per-process address-space limit, finite CPU/wall limits, and bounded request/result data. It does not run Isabelle, publish the installation, or acquire a second root lease. Archive and extraction caps also apply to external cache/staging paths. The 6 GiB workspace setting supplies the worker's per-file OS ceiling; it does not impose an aggregate disk quota on those external paths.

After the worker drains, the controller validates the exact staged layout and runs admitted version/help, no-build HOL and fixed `True` kernel-smoke checks. Publication retains the previous tree and launcher, installs the new tree and generated wrapper, checks the wrapper bytes and target, then repeats bounded preparation at the final path. Version and selected file identities must agree across the move. A warm reuse also performs a fresh fixed smoke; a historical receipt does not bypass native checking. Setup reuses this final observation instead of running another preliminary or duplicate smoke.

Only the controller publishes paths, under the same process mutex and `.isabelle-install.lock` used by the legacy installer. The hard-killable worker cannot stop halfway through publication. Ordinary failure, cancellation or deadline expiry before commit restores both prior paths. Rollback completes despite cancellation; this is exception rollback, not crash-atomic publication across two paths, and concurrent readers can observe an intermediate state. Unresolved previous-install backups cause refusal.

Large-tree cleanup runs in another bounded child. Cancellation, pressure or an exhausted deadline can leave controller-owned paths in `cleanup_pending`; retain the receipt and account for their storage. Cleanup failure after a validated commit does not revoke the published installation. A killed controller, kernel I/O stalls or a crash still require separate recovery; these controls are not a filesystem security sandbox.

`status` is `installed`, `already_present`, `failed` or `blocked`; require `receipt.usable` for success. `strict=True` raises `IsabelleInstallationError` carrying the receipt on failure. The receipt retains worker, staged/final preparation, resource limits and pending cleanup. Its fixed smoke and selected hashes grant no repository or proof authority, and do not attest every installed heap, component or transitive library. The no-oracle audit does not establish axiom-free HOL.

`isabelle_setup --install` calls this owner directly, including when no install root is specified. `prover_installer.ensure_isabelle()` forwards `timeout_seconds`, `parent_lease` or `scheduler`, `cancellation` and `memory_mb`; ordinary lazy installation uses the same bridge. Explicit `IPFS_DATASETS_PY_ISABELLE_INSTALL_COMMAND` commands remain a labeled legacy override outside these guarantees. Outer lazy-facade locks retain their separate wait contract. The older direct `backends.installers.isabelle.ensure_isabelle()` API remains available with its cooperative archive safeguards and legacy native probes; it is not the default setup/registry installation owner.

## Explicit persistent HOL rebuild

To rebuild from an already retained pinned archive without permitting a download:

```sh
python -m ipfs_datasets_py.logic.external_provers.isabelle_setup \
  --install-root /path/to/isolated/isabelle --build-hol --smoke
```

Add `--install` to permit obtaining the archive if needed. The equivalent owner
API makes this policy explicit:

```python
receipt = ensure_isabelle_installation(
    yes=True,
    install_root="/path/to/isolated/isabelle",
    build_hol=True,
    allow_download=False,
    build_memory_mb=6144,
    timeout_seconds=3600,
    strict=False,
)
assert receipt.usable
assert receipt.hol_build["persistent_heap_published"] is True
```

`build_hol=True` bypasses warm reuse and requires `yes=True`. The worker
re-extracts the pinned archive; a corrupt cache in download-disabled mode fails
without a network fallback. The cache must be at
`<install_root>/downloads/<official archive basename>`: for the Linux ARM pin,
`<install_root>/downloads/Isabelle2025-2_linux_arm.tar.gz`. Build-only setup does
not search workspace caches or an older nested runtime for archive bytes. The
build removes the staged HOL heap and its
session records while preserving Pure, then invokes the fixed HOL system-heap
build. This performs an actual rebuild, rather than accepting an existing heap
as evidence that a build occurred. Private HOME/JVM/ML settings isolate build
configuration while the system heaps remain under the staged distribution.

The default build envelope reserves four CPU slots, twelve process slots and
6,400 MiB: the larger of the inspection/build RSS budgets plus 256 MiB for
coordination. `build_memory_mb` accepts exact integers from 2,048 to 8,192;
accepted smaller budgets are refusal limits, not a guarantee that HOL can build
within them. Inspection still uses `memory_mb` independently. The default build profile has a
6 GiB sampled RSS guard, a 2 GiB JVM heap, a 3 GiB ML heap and 1 GiB allowance for
other runtime memory. Build settings use two ML workers, one GC worker and one
active JVM processor. These are accounting and
computation settings, not hard counts of all runtime OS threads or descendants.
The runner applies sampled process-tree RSS, finite wall/CPU limits and a
32 GiB per-process address-space ceiling. By default it samples the external
heap directory against a 4 GiB logical-size ceiling and checks a 1 GiB free-space
floor on both the staging and private temporary filesystems, with a 4 GiB
per-file OS limit and a separate 64 MiB private-workspace bound. Samples
can overshoot between observations; neither disk headroom nor aggregate memory
is exclusively reserved against other processes.

Successful building alone does not publish the heap. The controller performs
staged native readiness checks, publishes the tree and launcher with the same
rollback policy, repeats readiness at the final path, and verifies that the
rebuilt heap identity survived the move. Only then does it set
`hol_build.persistent_heap_published=True`. The setup report retains
`hol_build.returncode` and `hol_build.error` for compatibility, plus the full
build record. A zero exit code without confirmed publication is insufficient.
The final preparation is reused by setup; requesting both flags does not run a
second standalone build or duplicate smoke afterward.

The [native full-build measurement](../../../workspace/isabelle-hol-build-qualification-20261002/official-hol-build-6g/result.json)
completed with all 26 benchmark checks passing: a fresh HOL UUID, preserved
Pure artifacts, matching staged/published heap manifests and final file hashes,
fresh warm verification, and drained sampled descendants/owned leases. The
build worker took 286.896 seconds, the cold transaction 329.660 seconds, warm
verification 10.319 seconds, and the full benchmark 347.482 seconds including
admission and hashing. Descendants peaked at 5,222.87 MiB, twelve processes and
85 OS threads; controller RSS is separate and is not capped by the coordination
allowance. One build does not establish
throughput scaling or attest arbitrary sessions. Direct legacy installer calls, custom overrides,
outer lazy-lock deadlines, crash recovery, aggregate cgroup enforcement and
arbitrary frontend execution retain their separate limitations.

The first retained full-build attempt used a smaller JVM/4 GiB process-tree
profile and was cancelled after sustained slow progress. Its captured stderr
reports Java heap exhaustion; this does not establish host OOM. The revised
6 GiB profile completed the separate measurement above. The first attempt's final record
retains pending cleanup and live sampled descendants despite released leases;
separate recovery records subsequently confirm the tracked processes gone and
the retained stage removed by a freshly admitted bounded cleanup worker. The
initial cleanup-call error is also retained; recovery does not change the
original failed benchmark result.

The separate [real native cancellation control](../../../workspace/isabelle-hol-build-qualification-20261002/native-cancel/result.json)
passed all 16 checks in 32.087 seconds on the same frozen production sources as
the successful build. It observed Java and two Poly/ML processes in three
process groups/sessions for 15.021 seconds, with native CPU progress, before
cancelling. All fifteen sampled PID/birth identities had stopped when the
installer returned; no runtime was published. The original receipt retains its
pending stage, while a separate locked, admitted cleanup using a fresh signal
removed that path in 0.398 seconds. The parent survived cancellation and all
owned leases drained. The runner tracks observed process ancestry and birth
identities across separate groups; this does not establish containment of
hostile daemon escape or aggregate cgroup enforcement.

The [final qualification](../../../workspace/isabelle-hol-build-qualification-20261002/REPORT.md)
has **1,217 distinct cases with passing latest results**, zero latest errors or
skips, and matching source hashes across suites and native measurements. Raw
execution retains 1,219 runs: 1,217 passes and two timeouts, each passing its
exact unchanged-source retry. One timeout is confirmed at 30-second root
admission; the other reached the 60-second preparation deadline with truncated
diagnostics that do not locate the precise wait/probe boundary. No resource
policy or deadline was relaxed. Earlier failed builds and recovery attempts are
retained separately from those test totals.

The canonical backend uses private JVM settings with Serial GC, one active processor, a 256 MiB Java heap ceiling, and a Poly/ML heap ceiling derived from the request budget (at most 1 GiB). These settings avoid ZGC backing-file conflicts with artifact limits. Poly/ML's 32-bit object runtime reserves 16 GiB of virtual heap space plus 4 GiB of stack space even for a small proof. On Linux the backend therefore retains a 32 GiB address-space ceiling (or the larger requested budget) while monitoring aggregate process-tree RSS against `ExecutionBounds.max_memory_bytes`. The RSS guard samples every 100 ms, terminates the process tree on excess, and conservatively counts shared pages in each process. It is not a kernel cgroup limit and can overshoot between samples. RSS enforcement currently requires Linux procfs; unsupported platforms fail rather than silently omitting the guard.

The live canonical test uses a 2 GiB resident budget and a 60-second deadline. Smaller budgets can reject runtime startup or HOL loading, which is a resource failure rather than evidence that a theorem is false. Increasing concurrency requires reserving memory for each JVM/PolyML tree through the resource scheduler; a virtual address reservation should not be treated as 32 GiB of physical RAM.

Run the live and synthetic adapter qualification:

```sh
pytest -q tests/integration/logic/hammers/test_isabelle_runtime.py \
  tests/integration/logic/hammers/test_isabelle_workflow_e2e.py \
  tests/integration/logic/hammers/test_itp_frontends.py \
  tests/integration/logic/hammers/test_reconstruction.py \
  tests/integration/logic/hammers/test_canonical_backend.py \
  tests/unit/logic/backends/test_process_lifecycle.py
```

Live tests skip explicitly when the modern runtime is absent. They cover goal capture, accepted and rejected reconstructed proofs, setup smoke, and the canonical backend. Synthetic tests cover unsupported launchers, installation opt-in, missing audits, and RSS termination of a worker or child process. Qualification does not certify arbitrary user ML or provide an OS security sandbox for untrusted theories.

The public workflow E2E test executes inspect, premise selection, explicit negated-goal translation, real Z3/CVC5 portfolio execution, Isabelle reconstruction, receipt persistence, and receipt retrieval under one correlation ID. It also checks rejection of a false native theorem and launches the setup CLI with `--install --smoke`. Installer progress goes to stderr so stdout remains parseable JSON. The CLI test exercises reuse of the existing distribution, asserts that no persistent build or download occurred, and does not qualify a fresh archive download. The expensive full HOL rebuild belongs to a separate isolated qualification.

For qualification across all installed managed provers, prepend the configured managed install root's `bin` directory to PATH **for the test process**. Some legacy live tests use PATH discovery, so running with only the shell's default PATH can skip installed Rocq, Vampire, and E. The 2026-10-01 full run used `/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/bin` and included the release-gate tests after generating actual `environment.json`, `benchmark.json`, and `golden-report.json` reports. No shell profile was changed.

## Fresh archive auto-install and bounded real stress

An explicit install root never reuses an executable from another root:

```sh
python -m ipfs_datasets_py.logic.external_provers.isabelle_setup \
  --install-root "$HOME/.local/share/ipfs_datasets_py/isabelle-clean" \
  --install --smoke --timeout 600
```

If the root is empty, `--install` downloads the reviewed platform archive, verifies SHA-256, extracts in the bounded staging worker, then performs the controller validation/publication transaction above. An existing explicit root never falls back to a different installation. Explicit absolute runtime paths are honored by frontends and reconstructors. The bounded owner requires Linux; the older cooperative installer retains its separate non-POSIX thread-lock behavior.

The typed installer enables these refusal limits by default:

| Work | Default bound |
| --- | --- |
| Compressed download and cached-artifact hashing | 6 GiB |
| Extracted regular-file payload in total | 24 GiB |
| One regular file | 4 GiB |
| Tar member headers, including extended headers | 200,000 |
| One UTF-8 path or link name / total names | 4 KiB / 16 MiB |
| Path depth / nested extended headers | 64 / 16 |
| One tar metadata body / total metadata bodies | 64 KiB / 16 MiB |
| Pre-install free space / extraction free-space floor | 12 GiB / 1 GiB |
| Bounded owner deadline, including admission and lock wait | Ordinary install 600 seconds; explicit build 3,600; maximum 3,600 |

Only gzip and plain tar are accepted. Gzip reads and the full decompressed tar stream are bounded; the latter permits the payload ceiling plus capped metadata, header/padding overhead, and 64 KiB of final padding. Extended-header sizes are checked before parsing their bodies, and the gzip trailer is consumed and validated. Xz/bzip2, sparse files, devices, and FIFOs are refused. Relative symlinks must stay inside the staging tree; hardlinks must refer to an earlier regular file. Extraction does not write through a symlink or overwrite a previously extracted file. Executable permission bits are retained without setuid/setgid bits.

Download and cached-hash loops use at most 64 KiB per read, including a cumulative cap if a cached file grows. Cache and lock inputs must be regular files; final symlinks and FIFOs are refused. Each download uses a private partial file, validates declared length and SHA-256, flushes/fsyncs the file, and replaces the destination atomically. A failed download preserves an earlier destination. Launcher publication likewise uses a unique temporary file. An invalid `Content-Length`, checksum mismatch, cancellation, or resource refusal cannot publish an unchecked download.

The bounded owner uses the reviewed archive ceilings without caller overrides. The older cooperative installer exposes `max_download_bytes`, `max_expanded_bytes`, `max_file_bytes`, `max_members`, `max_path_bytes`, `max_total_path_bytes`, and `min_extraction_free_bytes` separately. Extraction rechecks live disk headroom during bounded copies; this is not a disk quota or an exclusive reservation against another writer. Archive ceilings are refusal bounds, not memory reservations.

Checksum, extraction, and staged-validation failures preserve an existing installation. The bounded owner moves failed or previous trees into its retained cleanup area instead of deleting them synchronously during rollback. Check `cleanup_pending` after either success or failure. Direct use of the older cooperative installer can still perform synchronous cleanup beyond its deadline, especially for previous trees installed before these limits existed.

Archive primitives check the deadline around I/O and between copies. Socket inactivity is capped at ten seconds, but those cooperative checkpoints alone cannot bound DNS resolution, HTTP framing, filesystem I/O, decompression or cleanup latency. The new owner additionally supervises the archive/cleanup subprocess tree; required controller rollback and uninterruptible kernel I/O remain limits. File fsync plus rename supplies atomic visibility, not directory-fsync crash durability. Direct legacy calls do not acquire the new owner's containment automatically.

The earlier [official-archive qualification](../../../workspace/shared-prover-installer-qualification-20261002/REPORT.md) completed a fresh local HTTP download of the retained reviewed 1,181,119,333-byte archive into a new root. The cold installation took 13.228 seconds and warm reuse took 0.891 seconds, followed by successful bounded installed-runtime preparation and kernel smoke. Sampled descendants peaked at 592.25 MiB, eight processes and 74 OS threads; all owned leases and sampled descendants drained. Those timings describe the earlier harness around the legacy installer, not the new production owner's staged/final checks. They are one local fixture, not a remote-download or throughput benchmark. The report retains earlier failed attempts and its test commands, results and selected source hashes.

Focused boundary and preparation tests can be run with:

```sh
pytest -q tests/integration/logic/hammers/test_isabelle_archive_bounds.py \
  tests/integration/logic/hammers/test_isabelle_installer_transactions.py \
  tests/integration/logic/backends/test_isabelle_preparation.py \
  tests/integration/logic/hammers/test_isabelle_setup_preparation.py \
  tests/integration/logic/hammers/test_isabelle_installation_routing.py
```

Archive boundary tests use small local HTTP fixtures and malformed archives to exercise limits, cancellation, lock waits, safe links, metadata/decompression bounds, and rollback. Those fixtures test installation mechanics, not kernel proofs. The separate official-archive harness qualifies the real distribution shape.

Run the bounded competing-load benchmark and opt-in regression tests:

```sh
PYTHONPATH=. python benchmarks/bench_proving_real_stress.py --out workspace/proving-stress
IPFS_DATASETS_RUN_PROVING_STRESS=1 pytest -q \
  tests/integration/logic/hammers/test_real_competing_load.py
IPFS_DATASETS_ISABELLE_FRESH_TEST_ROOT="$HOME/.local/share/ipfs_datasets_py/isabelle-clean" \
  pytest -q tests/integration/logic/hammers/test_isabelle_installer_transactions.py
```

The stress workers run at nice 19 on one CPU, have a 20-second lifetime and CPU limit, and a 1 GiB per-worker address-space limit. The memory competitor allocates 768 MiB and requires at least 4 GiB of live host headroom. Its RSS is measured against a 1 GiB experiment budget; this exercises memory admission without exhausting host RAM. CPU admission uses actual Linux scheduling-wait counters from three competing workers on one CPU. A separate batch executes 32 real solver checks with external CPU and memory load under a four-slot proof envelope. These measurements do not imply host-wide saturation, kernel-cgroup enforcement, or performance at arbitrary machine scale.

The 2026-10-01 qualification downloaded a fresh Linux ARM archive (1,181,119,333 bytes), verified the pinned checksum, installed it in an isolated root, and passed setup, native goal capture, valid reconstruction, and false-proof rejection there. See `workspace/isabelle-stress-qualification-20261001` for the actual installation receipt, setup output, stress measurements, and JUnit reports. The original managed installation was retained.


If a rollback rename fails, the bounded installer attempts the independent
restores and retains `recovery.required`, error details and all surviving
backup/quarantine paths. An unresolved previous-installation backup blocks both
warm reuse and replacement until recovery; it is never silently deleted.
Warm reuse also checks the managed discovery launcher. With `yes=True` it can
transactionally repair a stale/missing launcher without downloading; without
installation authorization it reports `managed_launcher_repair_requires_yes`.
An explicitly selected inner distribution keeps its native launcher unchanged.

## Public Isabelle goal capture and reconstruction use the shared owner

`IsabelleFrontend` and `IsabelleReconstructor` now use the bounded Isabelle
execution owner by default. Each capability, capture, or reconstruction call
acquires an operation envelope from the shared pressure-aware scheduler, unless
it subdivides an explicitly supplied parent lease. Version/help observations,
HOL readiness and the requested theory consume the same operation deadline.
Reconstruction does not issue a separate capability probe before beginning that
budget. Each native phase requires a fresh child admission, so outside load can
hold subsequent work until pressure subsides or the deadline expires.

```python
from threading import Event
from ipfs_datasets_py.logic.hammers.frontends.isabelle import IsabelleFrontend
from ipfs_datasets_py.logic.hammers.reconstructors.isabelle import IsabelleReconstructor

cancel = Event()
frontend = IsabelleFrontend(timeout=120, memory_mb=2048, cancellation=cancel)
capability = frontend.capability()  # admitted probes; never installs or builds

source = '''theory Example
imports Main
begin
lemma example: "(n::nat) = n"
  sorry
end
'''
snapshot = frontend.snapshot_goal(source, theorem_id="example")

# With an existing actual datasets ResourceLease, both adapters can borrow it.
# The parent must fund at least 3 CPU slots, 12 process slots and 2,304 MiB.
# Keep it live throughout the call; adapters release only their own children.
# frontend = IsabelleFrontend(parent_lease=parent, timeout=120,
#                             memory_mb=2048, cancellation=cancel)
# reconstructor = IsabelleReconstructor(parent_lease=parent, timeout=120,
#                                     memory_mb=2048, cancellation=cancel)
# record, evidence, lock = reconstructor.reconstruct(
#     request=request, candidate=candidate, goal_snapshot=snapshot,
#     native_source=source,
# )
```

The default timeout is 30 seconds and default resident budget is 2,048 MiB.
Timeouts must be finite and positive, at most 3,600 seconds; accepted memory
budgets are 1,024–4,096 MiB. A supplied `scheduler` replaces default scheduler
selection; pass it or `parent_lease`, not both. Likewise, select either an
`install_root` or an explicit executable path. The operation reserves
`memory_mb + 256` MiB, three CPU slots and twelve process slots. These are
scheduler accounting amounts, not a hard kernel limit on aggregate processes
or OS threads. The 256 MiB coordination allowance does not cap controller RSS.

For reconstruction, the request's `HammerPolicy.timeout_seconds` and optional
`memory_mb` further tighten the adapter's selected budgets. A policy below
1,024 MiB is refused before execution. An optional `cpu_seconds` conservatively
caps the whole operation's wall deadline too; native CPU limits remain
per-process. Raising the constructor timeout does not override a shorter
request policy. Source preparation and record serialization in the Python
adapter are outside the helper's native-operation deadline.

To permit an absent managed runtime to install during the same call, explicitly
set `auto_install=True`, select a sufficiently long timeout, and optionally set
an isolated `install_root`. For reconstruction, the request policy must also
have `network_allowed=True`; a false policy suppresses automatic installation
even when the constructor opts in. Capability discovery never installs.
Installation uses the operation's existing parent envelope and remaining
deadline, rather than receiving a new full timeout. An invalid explicit runtime
selection, pressure refusal or native failure does not trigger installation or
fallback to another distribution. A verified-cache-only installation remains
available through the separate setup/installation API.

Capture uses `quick_and_dirty=true` only to print the incomplete native goal.
Both public adapters bound exact text and UTF-8 source size before scanning or
instrumentation, then check the final instrumented source again before hashing
or admission. Added goal-printing or audit text cannot silently exceed the
native input allowance.
Reconstruction substitutes its deterministic proof-method portfolio and checks
with `quick_and_dirty=false`, requiring the named-theorem no-oracle audit. The
adapter rejects cancellation, timeout, resource/output/workspace failure,
missing audit, incomplete operation and changed runtime/source/theory/command
bindings even when stdout contains a success marker. A supplied environment
lock must match the freshly observed version, executable, command template and
request policy, and its content digest must be valid. Successful preparation
can remain recorded as historical identity after a failed check; it does not
make current capability available or turn the rejected proof into acceptance.

`ReconstructionEvidence.execution` retains the shared owner's operational
receipt. It includes preparation, source SHA-256, selected runtime identities,
lease lineage, phase limits, elapsed time and bounded native output. The
command uses the normalized `{workspace}` placeholder; the runner substitutes
its private workspace and binds the exact source bytes. This field confers no
proof or repository authority and does not replace the existing source/output
digests or kernel-acceptance record. Older evidence without this optional field
continues to round-trip without a new serialized field. Goal snapshots retain
the receipt in `extra["execution"]`; capability evidence retains it in the
Isabelle executable metadata.

These defaults apply to each Isabelle adapter operation. They do not establish
one deadline or one retained envelope for an entire multi-step MCP/hammer
workflow. Lean and Coq frontend/reconstruction paths retain their separate
legacy execution behavior. Installed Isabelle, supplied theories and native
components remain trusted programs; arbitrary ML is not sandboxed. Resource
limits include sampled process-tree RSS, a 32 GiB per-process virtual-address
ceiling, output/workspace bounds and observed descendant cleanup. They do not
provide an aggregate cgroup memory/process ceiling, hostile-daemon containment,
or an exclusive memory/disk reservation. HOL preflight still has the documented
race in which later theory processing may attempt a bounded private rebuild.

The [public-adapter phase report](../../../workspace/isabelle-hammer-execution-qualification-20261002/REPORT.md)
retains twenty passing native checks in 51.014 seconds, including true acceptance,
false rejection and in-flight public capture cancellation with observed cleanup.
The selected run observed no admission backoff; the earlier 71.395-second run
retains its pressure observations under its own earlier source hashes. Latest
regression outcomes are 1,460 passes and ten legacy Coq cases skipped by PATH-based
availability gates, across 1,470 distinct cases. Native Coq coverage remains
unqualified; managed launcher files exist, so these skips do not establish that
Coq is uninstalled. Raw execution retains 1,480 cases and one corrected test
assertion failure; the complete affected ten-case file passed without changing
production code. Direct generic canonical-backend callers still need separate
shared-admission integration. The earlier installer and HOL-build reports above
remain separate measurements. The
[read-only cgroup capability audit](../../../workspace/isabelle-hammer-execution-qualification-20261002/cgroup-host-audit.json)
records the current host's delegation constraints and the remaining aggregate
containment work; it does not claim that a cgroup execution provider exists.

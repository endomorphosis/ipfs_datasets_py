# React capture implementation plan and acceptance gates

Status: proposed work, 2026-09-30. Read the
[architecture](react_capture_spec.md) and [trace contract](react_trace_contract.md)
first. All new modules and commands below are proposed, not installed APIs.
The [backlog JSON](react_capture_work_items.json) records dependencies and
acceptance IDs for parallel implementation. This plan starts no campaigns,
downloads, services, supervisor jobs or HF publication.

## Delivery milestones

| Milestone | Exit condition | Required work |
| --- | --- | --- |
| M1 Local evidence | Pinned React fixtures produce valid action/handler/commit records; interrupted capture recovers with explicit gaps | R00–R04 |
| M2 Local feature training | Imports and instrumented traces produce deterministic observation targets; training/resume/inference pass with real evidence and fixed splits | R05–R09, including the fixture executor for the joined profile |
| M3 Multiple systems | Two machines exchange immutable jobs/complete model generations and converge on owner-selected candidates; restart/replay is verified | R10 and R12 |
| M4 Optional numerical transport optimization | Native Arrow or sparse encoding beats full state on measured cost while preserving exact replay and optimizer continuation | R11; not a prerequisite for full-state M3 |

M1 and M2 must work with local files and the current native JSON checkpoint.
For each milestone publish a capability manifest listing implemented, disabled
and unsupported paths. Do not describe a local Quack prototype, data-only IDL
projection or file export as a production distributed executor.

## Work packages

| ID | Scope and proposed files | Dependencies | Acceptance |
| --- | --- | --- | --- |
| R00 | Inventory pinned app/ComponentBench/HF revisions, local browser/Node/Python dependencies and source terms. Write `configs/ui_ux_ir/capture-pilot.json` and source/split manifests. Keep raw assets bounded. | None | A00 |
| R01 | Implement schemas in `schemas/ui_ux_ir/react_trace/`, golden vectors and common digest rules. Add pure decoder `logic/ui_ux_ir/source_adapters/react_trace.py`; freeze projection descriptor catalog. | R00 | A01 |
| R02 | Implement optional `typescript/ui-react-trace/` recorder, component/handler declarations, safe wrapping, explicit async contexts, commit selectors, bounded queue and redaction. | R01 | A02 |
| R03 | Add Storybook/Playwright harness and `examples/ui_ux_ir/react_capture_fixture/`. Add proposed `scripts/ops/ui_ux_ir/capture_react_traces.py` as an owned process supervisor. | R00, R01, R02 | A03 |
| R04 | Add `logic/ui_ux_ir/capture/{collector,shards}.py` and separately versioned `duckdb_control/ui_trace_catalog.py`; durable shard ingest, dataset snapshots, split catalog and outbox. | R01 | A04 |
| R05 | Add `logic/ui_ux_ir/source_adapters/componentbench.py` and proposed `import_ui_trace_corpus.py`; distinguish imported browser-only traces from new instrumented runs. Add WebLINX/Mind2Web adapters only after the first source passes. | R00, R01, R04 | A05 |
| R06 | Add `logic/ui_ux_ir/runtime/{idl_executor,invocation_ledger}.py`, fixture backend and result-to-state adapter. Reuse existing mediator/request/result checks; require current authorization and state fence. | R01, R02 | A06 |
| R07 | Add `logic/formalization/autoencoder/{ui_trace_training_inputs,ui_trace_targets}.py` and versioned feature normalization. Produce immutable prepared bundles through proposed `prepare_ui_trace_targets.py`. | R01, R04 | A07 |
| R08 | Extend `ui_feature_training.py` and UI CLI with explicit input-profile/prepared-target dispatch. Preserve the v1 route, separate inference, resource admission and exact resume. | R03, R07; R05 for imported-source profiles, R06 for joined typed-call profiles | A08 |
| R09 | Add `optimizers/logic_theorem_optimizer/ui_trace_qualification.py`, frozen evaluation/replay command and per-capability reports. Calibrate model-quality thresholds only on the designated tuning policy. | R03, R07, R08; R05 for imported-source checks, R06 for joined execution checks | A09 |
| R10 | Add UI-native immutable worker assignments, enrolled remote transport, owner verification/selection, generation acknowledgements and recovery. Use full native state first. | R04, R08, R09 | A10 |
| R11 | Implement optional native Arrow state codec and exact-parent sparse postimages after a measured density/copy profile. Include parameters, Adam state and complete compatibility metadata. | R08, R10 | A11 |
| R12 | Add `huggingface/ui_trace_exchange.py` and explicit UI corpus/model release profiles; offline package verification, exact Hub revision receipts, owner outbox delivery and pull/resume. | R04, R09, R10 | A12 |

Paths beginning `logic/`, `duckdb_control/`, `optimizers/` or `huggingface/`
are relative to `ipfs_datasets_py/`. R04 must use a declared UI catalog migration;
it must not add tables through arbitrary SQL to the strict autoencoder registry.
File locations may change during review, but contract/version/dependency changes
must update all three documents and the backlog together.

After R01, recorder work R02 and storage work R04 can proceed independently.
R05 and R07 can use golden shards while R03 develops the browser harness; R06
can use known request fixtures while R07 develops projections. Integrate against
immutable source snapshots. Reserve validation on those snapshots rather than
requiring all other developers to stop editing the shared checkout.
The local-state subset of R08/R09 can finish before import R05 or executor R06;
its capability manifest must say which profiles were exercised. Complete M2
still requires the imported and joined-profile evidence named above.

## Acceptance matrix

Each acceptance ID requires its negative cases and reproducible receipts. A
test suite reporting success while skipping its real backend/browser requirement
does not satisfy a milestone; an explicitly unsupported capability stays listed.

| ID | Required evidence |
| --- | --- |
| A00 | Exact source/build/dependency/file digests and existing ledger admission plan; train/tune/test exclusion manifest; benchmark answer metadata separated; no moving revision or bulk-download assumption |
| A01 | Python/TypeScript agree on golden canonical bytes and hashes; reject unknown fields/kinds, duplicate keys, invalid numbers, oversized/deep values, wrong evidence class and invalid graph references; fixtures cover every record kind |
| A02 | Original called exactly once; same `this`, arguments, return/Promise identity and synchronous throw object; closure behavior retained; no new Promise observers; nested handlers, propagation/prevention, IME/input, StrictMode/remount, explicit async context and recorder-failure cases |
| A03 | One driver per episode; recorder installed before application code; recognized frames/epochs only; zero/many handlers, no-op/batched updates, out-of-order requests, unmount/navigation, timeout and missing state remain explicit; instrumented and recorder-disabled application assertions agree |
| A04 | Crash/restart before and after every shard seal/commit/ack; same ID/same payload deduplicates, changed payload conflicts; no partial shard visibility; lost acknowledgements reconcile the original operation; expired lease cannot acknowledge; missing intervals retained |
| A05 | Source revision and split preserved; coordinate/operation conversion covered; imported actions never gain fabricated React/IDL evidence; evaluator fields and hidden success nodes excluded; equivalent content cannot cross splits by changing IDs/revisions |
| A06 | All non-ALLOW outcomes yield zero dispatches; altered args under same request ID, wrong backend/tenant/CID/method, stale/revoked policy and authorization replay fail; committed effect with lost response reconciles the original operation after authorization expiry; deduplication expiry blocks unsupported automatic retries; stale results cannot mutate newer state |
| A07 | Identical source/profile produces identical targets; frozen trainable descriptor set matches supported backend families; every feature maps to source evidence or declared normalization; deterministic windows retain bounded prior-state/ancestor/request closure; timing overlap never becomes causality; missing required view rejected; failures remain valid narrower observations; no invented norms or mental states |
| A08 | Exact native train/resume/infer closure; fixed basis/tuning/optimizer and cumulative exclusions; inference performs no optimizer update or candidate creation and leaves weights unchanged; per-view losses/coverage and attempted/selected work recorded; controlled resource failure retains recoverable artifacts |
| A09 | Independent frozen replay checks actual declared effects and negative cases; syntax/runtime/semantic/feature statuses stay distinct; no evaluation answer in feature inputs; unsupported source gate remains false; quality report states which generalization split was tested |
| A10 | Two real machines plus disconnect/restart: one current claim/fence can complete; replay original operation after uncertain response; verify exact full generation before acknowledgement; lost/duplicate/stale acknowledgements reconcile without regressing installed generation after restart; stale-parent candidates retained/requeued; wrong-codec or changed-basis jobs rejected before training |
| A11 | Full and optimized codecs reconstruct identical logical state and continue equivalent training within the declared deterministic-runtime profile; corrupt/missing/overlapping patches, wrong parent/shape/dtype/optimizer and overlong ancestry rejected; measured copy/transfer savings exceed added overhead |
| A12 | Offline release restores the exact data/model closure on another machine; no implicit job/lease/authority restoration; interrupted upload/pull resumes by verified immutable descriptors; exact Hub commit and consumer receipt recorded; dry-run publication has no network writes |

Fixtures must also cover one action with capture/bubble handlers, multiple roots
and a portal; keyboard activation; disabled input; a thrown non-Error value; a
custom thenable; a debounced update cancelled before commit; two setters in one
batch; unchanged committed state; a response after unmount; a dropped recorder
batch; and a client-forged verification flag. Maintain independent expected
behavior in tests rather than deriving test expectations from the recorder's
own labels.
Add retained-old-callback versus newer state, StrictMode re-registration versus
true remount, functional updater replay/abandoned render, external-store commit
while React is suspended, late callback after unregister, and timeout/cancel
followed by late backend success. Each must preserve the distinction defined
in the wire contract rather than collapsing it into one success label.
A06 also tests fresh authorization with unchanged logical arguments versus a
changed payload under the same backend operation. A04/A06 jointly test
timeout, immutable episode sealing, then late authenticated success recorded
as reconciliation: original manifests, watermarks and targets stay unchanged.

## Initial pilot and measurement

The first mechanical smoke uses our authored fixture and proves capture,
target preparation, train/resume/infer and negative boundary behavior. Label it
`heldout_canary=false` regardless of its reconstruction improvement. Existing
declaration fixtures remain regression tests for the old route.

For the subsequent quality pilot, create at least three independently authored
application lineages, with distinct scenario/component implementation clusters
assigned to training, tuning and evaluation before capture. A proposed initial
budget is 10 training groups, 3 tuning groups and 3 evaluation groups, each with
3 deterministic seeds: 48 episodes. Seeds, retries and windows from one group
stay together. These counts are planning bounds, not claims of statistical
power or existing data. If lineage audit cannot establish that partition,
continue only the mechanical smoke and report quality evaluation unavailable.

The default quality split holds out application lineage. A same-application
template/component experiment requires a separately named split policy and
cannot claim cross-application generalization. Do not union unrelated projects
merely because they depend on React/MUI; do union copied application code,
substantive shared component templates and their generated variants. Retain
upstream framework/library overlap as explicit metadata. Official ComponentBench
tasks remain a separate frozen evaluation suite.

First prepare native targets cold, then repeat with the exact shared cache key
warm. Train a baseline using the existing Adam objective, resume on new training
groups and infer from the saved candidate. Compare recorder-enabled/disabled
applications with identical sources, seeds and behavior assertions. Do not
substitute deterministic test embeddings for semantic embeddings; this initial
backend deliberately learns structural atoms without a pretrained model.

| Measurement | Report |
| --- | --- |
| Capture | Per-kind/episode counts, bytes, drops, handler coverage for declared scope, unmatched events, update/commit links, pending operations and outcome distribution |
| Fidelity | Recorder-enabled versus disabled assertion outcomes, callback counts, errors, DOM/selected-state results; discrepancies by case |
| Cost | Handler serialization p50/p95, browser RSS/CPU, capture slowdown, collector queue/spool size, seal latency and cold/warm preparation wall time per accepted and rejected record/window |
| Training | Requested/populated views, per-view known/unknown atoms, objective/reconstruction/cosine loss, baseline and selected metrics, attempted/selected epochs, preparation/optimizer/worker/whole-CLI wall times |
| Runtime evidence | Schema/correlation/authentication/effect checks separately; stale/replay/denied/unknown outcomes and exactly which backend was exercised |
| Distribution | Queue/lease/transfer times, full and patch byte counts, serialization/copy time, missed/stale generations, verified worker acknowledgements and restart outcomes |

Initial engineering performance budgets are proposed p95 recorder synchronous
work below 1 ms and median scenario elapsed overhead below 10%, measured over
at least 30 paired repetitions on named hardware. Establish a no-recorder noise
baseline and publish distributions; these are not semantic acceptance thresholds.
If a budget fails, reduce scope/serialization or revise the versioned budget with
evidence before scaling. Never remove loss markers or validation to hit a number.

Existing local UI smoke measurements showed about 0.6 seconds numerical training
but roughly 46 seconds whole-CLI wall time on tiny fixtures. Those results are
in the [baseline report](../implementation/reports/UI_FEATURE_TRAINING_20260930.md).
They justify measuring shared preparation and larger admitted batches before
adding GPU kernels. Reuse the existing independent RSS/deadline watchdog so a
slow storage census cannot hide a short compute peak. Do not weaken durable
accounting to obtain a faster timing.

## Resource policy and resume

Keep capture caps from the trace contract distinct from training limits. The
current UI training CLI admits at most 128 rows/8 MiB per file and enforces its
existing numerical bounds. The corpus importer windows larger datasets into
compatible immutable jobs; it does not raise the context window or silently
increase current backend caps.

Before a pilot, compute storage headroom for raw shards, normalized copies,
targets, candidate parents, spool retries, upload staging and a safety margin.
Reserve that concrete peak through the existing ledger. This plan does not
increase the campaign cap, reclaim retained claims, rewrite an archived model
or allocate an indefinite browser farm. Limit the first smoke to one browser
and one training worker; add independent episodes in a later capacity study.

Capture resumes at a new producer stream and the last durable shard receipt.
Ingestion resumes by original operation IDs and immutable descriptors. A target
cache hit requires all source/producer/profile identities to match. Numerical
resume requires the exact compatible parent and Adam state. A disconnected
worker may finish a private candidate but cannot publish a selected generation
or renew an expired claim by itself. Attempt directories and artifacts remain
immutable; retry creates a new attempt linked to the same logical work item.

## Multi-machine control and weights

Reuse one registry owner for model mutations and one catalog owner for corpus
commits, even when co-located. Quack carries bounded typed commands and
descriptors; large traces, tensors and images move through a separate verified
blob channel. The current Quack gateway is a loopback prototype. R10 must add
real worker identity, encrypted authenticated transport, credential lifecycle,
quotas, discovery and remotely resolvable artifact locations before claiming
multi-machine UI support.

Assignments bind corpus snapshot/window range, source/dependency and adapter
digests, model contract, full parent state, feature basis, projection profile,
ordered tuning panel, numerical policy, resource limits, worker identity and
lease/fence. An owner replays/verifies completed candidates and selects with
compare-and-swap against the assigned parent. A stale candidate is a retained
branch and requeued work, not a patch to add to newer weights. Workers acknowledge
a generation only after verifying their materialized full-state digest. They may
temporarily have different active generations while offline or training; status
must show that fact instead of promising instantaneous identical weights.

R10 defines an immutable `ui-native-generation/v1` manifest with owner identity,
generation ID and monotonic sequence, parent-generation digest, selected registry
version, full artifact and logical-state digests, native codec, contract/basis/
producer/tuning identities and evaluation references. The owner publishes its
pointer by compare-and-swap on the prior generation. A `ui-generation-ack/v1`
binds authenticated worker identity, generation-manifest digest, verified full
state digest, installation status and durable local sequence watermark. Acks
are idempotent; late acks retain history without regressing current installation.
An ack does not grant a job lease. Recovery queries the original operation and
verifies the installed bytes before reporting the latest active generation.
Before/after-resume parity includes Adam moments, step counters, any RNG state
and the exact deterministic-runtime profile, not just parameter values.

Do not share an open DuckDB database over NFS or upload live database files to
HF. Do not average independently trained Adam moments. Promotion of an inference
head is a separate owner policy; feature generation selection does not grant
execution or semantic qualification.

R11 is conditional. Measure changed tensor density and copy/serialization cost
first: dense Adam updates may compress poorly as sparse patches, and current
native fixtures have small full artifacts. A native Arrow codec must bind tensor
names/shapes/dtypes, all parameters and optimizer moments/steps, RNG state where
used, basis, contract, producer and tuning identities. Immutable contiguous
null-free numeric buffers can be eligible for a zero-copy view; nested JSON,
strings, chunk combination, dtype/device conversion and writable optimizer
state may require copies. Report actual copied bytes and buffer lifetime; do not
call the entire pipeline zero-copy.

Use exact-parent ordered postimage patches with checked preimage/postimage and
full resulting state digest. Bound patch-chain length and total replay bytes;
periodically materialize full checkpoints. Existing legal/modal sparse or Arrow
codecs are different formats and cannot accept native UI states by renaming
their modality. A failed sparse-cost gate keeps full native checkpoints valid.

## DuckLake and HF publication

DuckLake receives immutable UI corpus/control history through a dedicated
consumer and table schema. Reuse the existing durable delivery/commit-marker
patterns, but do not label the current isolated history sink or in-memory
ingest facade a production UI lake. SQL commits and lake delivery have independent
receipts; no fake cross-store atomic transaction is assumed.

Proposed publication destinations are separate UI repositories such as
`justicedao/ui-ux-ir-traces` and a dedicated native UI model repository. These
names are proposals, not created resources. Keep UI rows out of
`justicedao/uscode-autoformal-span-cache` unless an explicitly versioned shared
schema is independently designed. R12 first writes an offline package and
concrete publication plan. Repository access, source rights, redaction and byte
budgets are resolved against that exact plan before any upload.

Corpus release layout includes schema/source/split manifests, immutable trace
and target shards, permitted evidence blobs, normalization/loss receipts and
separate frozen evaluation metadata. A model release binds its native codec,
contract, full parent/patch closure, optimizer/resume state and evaluation report.
Training-only resume material and public inference artifacts use separate
profiles; neither contains credentials, live leases or policy capabilities.

Publish immutable run/snapshot paths and store the exact Hub commit returned.
Moving branches are discovery aids only. Pull verifies every referenced blob
before atomic installation; partial downloads never advance a local generation.
Data delivery, model delivery, goal/todo export and promotion are independent
operations. Optional supervisor work items include source scope, evidence gaps,
expected output contract and acceptance IDs; an import cannot execute them or
mark their criteria satisfied automatically.

## Opportunity cost and deferred work

| Choice | Benefit now | Cost or deliberate deferral |
| --- | --- | --- |
| Explicit wrappers and state selectors | Reliable source joins and observable semantics | Requires application changes; coverage is limited to declared boundaries |
| Controlled React fixtures first | Cheap deterministic failures, secrets-free replay and effect tests | Limited real-world diversity; follow with bounded upstream imports |
| ComponentBench as frozen evaluation/environment | Existing components and task checks | Its browser traces do not contain every React/API observation; instrumentation changes evaluation conditions and must be recorded |
| Existing structural autoencoder first | Reuses tested local training/resume and preserves gates | Does not learn pixels, predict future actions or generate executable React code |
| Full native checkpoints first | Simple exact recovery and compatibility | Transfer cost can rise; measure before implementing sparse/Arrow state |
| Single-owner control plane | Clear fencing and replay with existing infrastructure | Owner availability and bounded scheduling need operational work |
| Authenticated unary fixture backend first | Tests the real IDL/execution boundary | Streaming, transactional multi-service effects and production rollout remain later contracts |

Defer Fiber/DevTools interception, arbitrary production session capture, AST-based
automatic binding approval, pixel encoders, general code generation, federated
optimizer averaging and global-optimum guarantees. These would change the
evidence, privacy, numerical or execution problem before the local trace chain
has been validated.

## Release checklist and rollback

A milestone release contains reviewed schemas/golden vectors, versioned adapters,
API/CLI documentation, declared capabilities, test results with skips explicit,
owned smoke receipts, resource closeout, exact source/split/artifact identities
and current known gaps. Verify both code repositories' pinned commits and keep
HACC and `hallucinate_app` untouched. Legal parser/compiler changes and repairs
remain outside this implementation scope.

Recorder disablement restores application behavior without deleting captured
evidence. Rollback selects the previous adapter/dataset/model manifest; it does
not rewrite rows or reuse old execution capabilities. On unknown execution
outcome, pause that invocation's retry until reconciliation; other independent
capture/training work may continue. Keep bad shards/candidates quarantined with
reason codes and retain all still-referenced parents until explicit retention
policy makes them collectible.

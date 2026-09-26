# Owner-bound complete-state shadow evidence

Status: implemented and qualified with a synthetic changed-state execution
fixture and real preparation/verification subprocesses, 2026-09-25. This connects the
[offline endpoint replay](autoencoder_daemon_sparse_shadow.md) to the existing
[owner invocation](autoencoder_daemon_owned_invocation.md). It is an optional
diagnostic obligation. The full compact final checkpoint remains the registered
candidate; no sparse candidate representation, promotion or publication is
enabled by this change.

## Immutable opt-in and execution

`prepare_daemon_invocation(..., sparse_shadow=True)` seals a v2 request with an
exact boolean `sparse_shadow: true`. The default `False` retains the existing
closed v1 request, without an extra opt-out field. Other values are rejected.
The request version also binds the owner journal and registered execution run.
Changing the option during preparation retry fails. There is no execution-time
override on `run_owned_daemon_invocation`.

The existing independent verifier performs its ordinary full-candidate,
observation, input, metadata and persistence checks first. For v2, it releases
the decoded state, explicitly collects the released graph, and invokes complete
endpoint replay in a fresh exclusive `sparse-shadow` directory. It compares the
shadow's initial/final identities and final compact byte identity with those
already established by ordinary verification. Its final source, input and
artifact checks still run afterward. A successful local shadow receipt alone
cannot bypass a failed final guard.

This uses the same isolated offline verifier child. It introduces no additional
subprocess or registry connection, and remains within the existing invocation
deadline, child timeout and CPU/memory/disk reservation. The owner continues
lease renewal while the child works. Enabled shadow failures fail verification
and quarantine the attempt; the owner does not silently finish without the
requested evidence or implicitly retry under another lease.

## Owner reconciliation and persistence

The owner verifies the subprocess result's original immutable descriptor before
reconciling nested shadow evidence. It checks the request/launch binding, source
and input guards, recorded network denial, exact base and final descriptors,
all 38 raw snapshot components, revisions and ordinary verifier identities.
It also reconciles decoded patch counts, changed components, explicit revision
witnesses and content-only request/launch/native-result provenance. Persisted
receipt content must exactly match the observed return value, and patch and
receipt paths must be the expected files under this attempt.

Reconciliation runs as bounded file/codec work on a background thread while
the owner dispatcher services lease renewal. It makes no registry calls.
Like existing artifact staging, thread shutdown waits for that bounded work;
this phase is not forcibly cancellable in mid-decode. Long-running database
transactions are not introduced.

Two additional evidence descriptors are staged using the originally verified
hashes: `sparse_shadow_patch` and `sparse_shadow_receipt`. Their CAS copies are
charged to the existing reservation. The already staged full compact checkpoint
is still the only `CompleteRun.artifact`. The owner-verification artifact embeds
the shadow report and local references, while completion evidence supplies the
durable CAS identities. A corruption between verification and staging rejects
the operation; paths are not re-described to accept changed bytes.

The early historical-completion branch remains ahead of request or artifact
reads. After a committed or ambiguous completion, restart resolves the original
operation and returns its historical result without regenerating shadow files.
It explicitly does not assert current artifact availability. An uncommitted
prior attempt remains quarantined, without automatic re-execution.

## Evidence limits and opportunity cost

The [guarded combined suite](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-shadow-20260925/combined-r1-receipt.json)
passes **515 tests** in 87.65 seconds of pytest and 89.932 seconds of subprocess
wall time. Package sources and selected tests remain unchanged during the run.
Coverage includes the original owner, request and verifier behavior; the new
immutable opt-in, exact evidence reconciliation and recovery cases; journal and
resource handling; patch/native checkpoint compatibility; and all 31 mandatory
semantic gate/pilot checks. Changed-state fixture tests are explicitly synthetic.
The [corrected harness checks](../../../workspace/test-logs/federal-corpus-audits/daemon-owned-shadow-20260925/harness-r2-receipt.json)
add 25 passing cases, including an isolated process reaching the real environment
guard before runner import. They pass in 0.17 seconds of pytest / 1.499 seconds
for the guarded wrapper. All 7,732 package sources match the combined capture.

The new cases include paired re-sealing of a tampered returned/persisted receipt,
post-verification artifact corruption, lease loss, late source/input failures,
an already occupied shadow directory, graph release before new loads, and
historical completion replay with missing current artifacts. They do not replace
native changed-state training evidence.

The [first subprocess attempt](evidence/autoencoder_control_plane_plan/owned-daemon-shadow-20260925-r1.json)
failed explicitly before any fixture state load or mutation. Real request
description passed, but the synthetic child imported the daemon runner before
checking its sealed environment. That import added library environment variables,
so the unchanged environment guard rejected the child. The verifier did not run
and no candidate completed. The failed attempt and receipt are retained. The
correction matches production import order; it does not ignore, restore or
silently add those variables to the sealed environment.
The [independent failure audit](evidence/autoencoder_control_plane_plan/owned-daemon-shadow-failure-independent-audit-20260925-r1.json)
confirms no base copy, candidate, verifier, shadow output or completion, with the
head unchanged. Four pending, unclaimed DuckLake mirror events describe normal
base/head/input/failure bookkeeping; they are not external publication. Its
initial empty-outbox assumption and correction are preserved in that audit.

The corrected [r2 integration receipt](evidence/autoencoder_control_plane_plan/owned-daemon-shadow-20260925-r2.json)
passes with SHA-256
`cf5147a6300bed53b1e58e13de765ba1aa98592b423b0fada51e821803509b7c`.
The actual owner and request-description/verification subprocesses run against
three source-bound training records and three validation records in a fresh
private registry. Only the execute boundary is replaced by a separately
supervised fixture child. That child assigns one explicitly labeled scalar
`legal_ir_view_logits["synthetic.owned_shadow_qualification"] = 0.125`; it does
not call the daemon, optimizer, bridge evaluator or asynchronous snapshot
evaluator. Lifecycle metadata is constructed fixture data, not observed native
snapshot work. The independent verifier and stored completion both record
`evaluation_matches_final=false` and zero accepted projection epochs.

Exact replay covers all 38 native components and revision **0 → 1**, including
byte-for-byte regeneration of the full 1,665,226-byte compact checkpoint.
The patch is 2,099 bytes and its receipt is 30,840 bytes. The full checkpoint
remains the registered artifact. All seven evidence artifacts are staged,
the candidate has the exact registered parent, and restart returns the same
completion and version with one candidate event. The head remains unchanged
and the distinct input-anchor run remains queued and unleased.

The [independent r2 audit](evidence/autoencoder_control_plane_plan/owned-daemon-shadow-20260925-r2-independent-audit.json)
passes 47 checks without hydrating or replaying state. It verifies the seven
evidence artifacts, exact inserted float64 scalar, full candidate container,
private registry completion, unchanged head, current sources and protected
artifacts. All three new reservations are released and child process groups
are gone. Completion retains its original lease JSON as historical evidence;
the restarted owner has a later generation. The audit preserves its initial
incorrect cleared-lease assumption and the explicit correction. It does not
interpret that historical lease as current execution authority.
The [final closeout](evidence/autoencoder_control_plane_plan/owned-daemon-shadow-closeout-20260925-r2.json)
records the source/test and receipt hashes, protected checkpoint identity,
released reservations and documentation links after this review.
A [documentation follow-up](evidence/autoencoder_control_plane_plan/owned-daemon-shadow-doc-closeout-20260925-r2.json)
records the final document hashes after correcting two older plan paragraphs
that still described bounded v6 input and owner completion as future work.

| Measured phase | Wall time |
|---|---:|
| Historical input export to fresh private owner | 4.861 s |
| Owner preparation, including real description child | 14.614 s |
| Synthetic execute subprocess boundary | 11.685 s |
| Actual verification subprocess boundary | 24.268 s |
| Verification inside child | 21.654 s |
| Shadow reconstruction before its receipt write | 13.452 s |
| Complete owned execution, including both children and completion | 50.492 s |
| Qualification workflow through final guards, before outer receipt publication/release | 72.240 s |

Rows overlap and must not be summed. Inside shadow reconstruction, capture took
1.527 seconds, independent base reload/collection 2.736 seconds, complete-state
comparison 2.329 seconds and compact-byte regeneration 3.536 seconds. Applying
the decoded patch alone took 0.000193 seconds. The fixture execute child's
cumulative peak RSS was 1,155,192 KiB; this is not the verifier or combined
process-tree peak. The run supplies no new training or bridge-on evaluation
timing, no per-span speed comparison, and no cold/warm performance claim.

The existing shared scheduler and 50 GB named-root budget remain in force.
The outer export disk allowance is retained after its CPU lease releases and
through the final receipt's file/directory fsync; only then is it released.
The successful process exits zero and reports that release. A passing-looking
receipt alone is insufficient if that final release or process exit fails.
The first failed execution's 1 GB reservation remains retained; it was not
cleaned or discarded to make room for r2. No production DuckLake consumer,
Hugging Face upload or branch promotion ran.

This adds full scanning and independent reconstruction when explicitly enabled.
The prior offline archived cases cost 9.456 and 12.339 seconds end to end, despite
patch application taking less than a millisecond. Those measurements are not
predictions for the integrated verifier and not training speedups. The option
stays off by default. Its purpose is to establish complete-state evidence before
changing how daemon candidates are stored.

No diagnostic receipt authenticates an arbitrary issuer or proves that an
optimizer ran. Source-bound supervised execution establishes the supported
local boundary. Synthetic changed-state fixtures exercise that protocol but
cannot qualify native learning, held-out quality, asynchronous snapshot work,
or an accepted native changed-state transition. Actual native changed-state and
recovery evidence remain prerequisites for sparse candidate authority.

The subsequent [mapped-input implementation](autoencoder_daemon_mapped_inputs.md)
adds bounded opt-in v7 artifact/session/provenance binding and memo-aware detached
snapshot vectors. Synthetic producer declarations and optimizer fixtures cover
exact values and aliases, callbacks after mapping closure and failure cleanup.
A complete native owner v7 cycle and speed comparison remain unqualified;
native validation is deferred at the user's request. A future authorized
comparison must use fresh native v6/v7 cycles with matching settings, all five bridges,
provers false, metric disk cache zero, one bridge worker and explicit per-pass
sample-memory policy. V6/list defaults and parameter storage remain unchanged;
historical mapped worker comparisons were slower. Feature-weight daemon adoption
remains separate work, and detached copies do not imply whole-training zero-copy.
Source-complete federal-law coverage, reviewed semantic support, production
DuckLake materialization and Hugging Face publication remain separate work.
The Constitution remains unformalized, with no new `roundtrip_ok` span.
Only `lake build <Lib>` is a Lean admit; this change performs no Lake execution.

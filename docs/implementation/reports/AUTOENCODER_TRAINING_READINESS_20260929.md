# Training readiness after the stalled sweep

This change preserves all numerical acceptance thresholds and qualification gates.
Only a successful, source-locked `lake build Legal` is a Lean admission. Complete
bridge reports, decoded text, embedding metrics and sparse weight patches have
no proof authority. The Constitution remains unformalized.

## Why the previous run stalled

The eight configurations were not eight clean comparisons of convergence policy.
Four of six training targets timed out at 15 seconds. Expensive decoder proposals
consumed the remaining deadline. The decoder proposal that reached evaluation
expanded the candidate IR label set and increased IR cross-entropy from
1.589026915 to 1.791759469; the guard correctly rejected it. Momentum had no
accepted step history, and refinement had no accepted starting proposal.

The target distributions are not uniform. Their mean entropy floor is
1.561294430, below the 1.589026915 initial loss. The existing objective is not
mathematically impossible; introducing unsupported label mass makes the
unrestricted decoder update a poor first step. Changing thresholds or fabricating
a uniform reference would hide the problem.

## Changes

- Shared-target preparation supports an explicit per-target timeout and an
  optional complete-supervision requirement. Producer and consumer use the same
  timeout. Partial, rejected and timed-out reports cannot become a ready handoff.
- The expanded target-shard budget is explicit through preparation, job identity,
  resume policy, worker loading and owner receipt verification. The default stays
  64 MiB; an operator may select up to 256 MiB. Compressed artifact bounds,
  checksums, source binding and the 64 MiB sparse-patch limit remain independent.
- An explicit candidate update order can prioritize existing useful heads. The
  default five-candidate order and arithmetic are unchanged. The new structural
  decoder proposal updates six existing compiler-quality, logic-signature,
  round-trip-signal, decompiler-plan, predicate-argument and family embedding
  maps. It omits four IR-view maps and three large combinatorial maps, retaining
  the original update denominator. This keeps the IR candidate label set stable.
  Both new restricted proposals require zero L2 and the Python sparse backend.
- Raw decoder metrics before reconstruction safety projection are recorded for
  these proposals. They do not change acceptance and must not be confused with
  independent learned formalization quality.
- A failed metric gate accompanied by a semantic, syntax, Lake or validation
  split failure creates repair work after one attempt. Pure metric failures
  retain bounded training retries. Both kinds of work remain in the durable
  outbox; the retry policy is part of the stream identity.
- Round-trip stage success now also requires exact canonical IR cycle identity.
  Narrow unsupported enumeration, interpretive-scope and unresolved-reference
  guards prevent known false positive cycle labels. These checks do not prove
  general source equivalence or add unsupported Lean theorem schemas.
- The diagnostic controller verifies identical shared-target descriptors on
  resume, stops a provably unchanged repeated job, and requires strict accepted
  progress when advancing its training branch.
- An explicit administrative recovery API can reconcile one dead owner's
  retained reservation using exact record/artifact hashes, dead process groups,
  unchanged filesystem identities, durable files and a fresh locked census.
  It neither expires old claims nor deletes evidence. Other records are preserved.

## Remaining qualification work

The frozen six training and two tuning rows are legacy diagnostic inputs with
verified local GTE-small 384-dimensional embeddings. They are not an
independently authenticated federal-law training corpus. Two original oversized
training rows retain their token-limit abstentions; no easy replacement rows were
selected. The independent canary stays untouched until a fully qualified model
has been selected immutably.

Source recovery is needed for missing cross-references. The IR must preserve
nested alternatives, report-plus-wait requirements, recurrence and applicability
scope. Source-locked substantive Lean theorem schemas are needed for the real
corpus rules. A longer optimizer run cannot repair those deterministic gaps.
The supported numeric minimum-duration fixture is a separate Lake test.

## Native preparation and smoke status

The final cold preparation completed all eight targets (six training, two tuning)
with all five bridge reports accepted and no timeout or partial result. The exact
bridges were `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`, and
`external_prover_router`; external provers were disabled, metric disk cache was
disabled, and the target worker count was one. Sample memory remains disabled.
Target generation took **114.566 seconds, or 14.321 seconds per span**; the
supervised preparation took **142.294 seconds**. This is target preparation,
not an autoencoder evaluate timing or a Lean admission. OS cache warmth was not
controlled. Training consumers are intended to reuse this explicit shared
artifact rather than generate targets again.

The bundle is 25,949,433 bytes. Its largest expanded target is 91,141,821 bytes,
which explains the earlier failure at the default 64 MiB expanded-shard limit.
This diagnostic explicitly uses a 256 MiB expanded-shard bound and a 60-second
target timeout. The compressed-artifact and sparse-patch limits remain 64 MiB.
The producer reservation was released normally.

A read-only inventory against the new bundle and exact fresh 384-dimensional
parent found 1,262 structural parameter rows. The codec estimate including a
65,536-byte envelope margin is **15,434,898 bytes**. This is a size preflight;
it does not establish acceptance, successful persistence, or loss improvement.
The archived 8-dimensional restart12 checkpoint was not replaced or trained.

The subsequent two-worker smoke stopped **before worker creation** at the
80 GB campaign storage gate. A fresh census found 79,961,023,048 bytes charged,
leaving 38,976,952 bytes; the sealed smoke requires a 300,000,000-byte reservation.
Recent unrelated pytest directories explain approximately 847.5 MB of temporary
output. No unrelated output was deleted and no earlier retained claim was
discarded. The failed admission created no reservation. Its capacity, log and
state were preserved before explicitly preparing a retry of the same sealed plan.
There is consequently **no new bridge-on autoencoder evaluate time, accepted
epoch, sparse patch, or Lake result from this launch**. No eight-hour run started.

Two earlier preparation failures were preserved: an expanded-shard overflow and
a storage-cap interruption. Their own small artifact inventories were explicitly
reconciled with the new recovery API after both owners and child groups exited;
all other reservation records and all artifacts were preserved. The final
preparation's bounded observation journal records progress durably before target
serialization, so a failed attempt no longer loses its observations to buffering.

## Validation and publication scope

Validation on the pinned canonical working tree includes 535 unique controlled
optimizer/worker/resume tests, 105 shared-target tests, 147 semantic/qualification
tests, 49 qualified-training tests, 83 CLI/recovery tests, 65 bundle-bound tests,
and seven controller tests. These scopes overlap and should not be added into a
single test count. The three required semantic fixtures and the historical
five-case pilot passed (forward 0.92, cycle 1.00). These text-cycle results are not
Lean admissions. The protected restart12 checkpoint still hashes to
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.

Publication applies only this reviewed delta to the existing `origin/main`.
Existing main-branch parser, compiler and decompiler changes are preserved.
Those files differ from the active canonical working tree; native measurements
here bind that working tree's hashes and are **not validation of the exact
published release tree**. A fresh sealed comparison on a synchronized release
tree is still required before a long campaign. The live checkout and ordinary
index are left intact for other running work.

The immediate next steps are storage admission, two concurrent native workers,
actual accepted-update persistence and replay, unchanged qualification gates,
then authenticated-source/IR/Lean repairs for the real corpus. Only a fully
qualified immutable selection may reach the untouched independent canary and
then the long-run gate. No global-minimum guarantee, full federal-law
formalization, or Hub publication is inferred from these checks.

Portable receipts are under
[`evidence/autoencoder-training-readiness-20260929`](evidence/autoencoder-training-readiness-20260929/manifest.json).

# Prepared compact LegalIR weighted training v1

`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_weighted_prepared_training_v1`
is the public leaf API for an operation-owned prepared training session. Import
it directly; the formalization package root continues to export deterministic
contracts only. Installation and a bounded public-import/input-guard qualification
are recorded separately in the public integration artifacts. Numerical public
consumer qualification remains pending; the earlier staged numerical evidence
is retained as its own cohort.

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_weighted_prepared_training_v1 as prepared,
)

session = prepared.prepare(
    weighted_checkpoint,
    expected_checkpoint_sha256=checkpoint_sha256,
    expected_policy_sha256=policy_sha256,
    max_steps=3,
)
try:
    result = session.advance(steps=2)
    first_checkpoint = result["reports"][0]["checkpoint"]
    final_checkpoint = session.checkpoint()
    observation = session.inspect()
finally:
    close_observation = session.close()
```

The input must satisfy the unchanged weighted v1 checkpoint contract: the exact
a98-derived donor, two bound exposed fictional rows, h0-only 384D conditioning,
537-token codec, hidden size 8, projection width 4 and token embedding size 8.
Only forced:choice weights 1:1 and 1:4 are supported. The independent checkpoint
and policy hashes are mandatory. This is a closed development profile; it does
not establish compatibility with gated, 768D, 4096D or statutory populations.

Preparation validates the complete checkpoint, policy, input bindings and grammar
once, restores one canonical model and one named Adam state, and caches both
complete row/label/weight tensors. Initial policy lineages use fresh Adam from
the donor weights. A saved successor restores its own exact named moments.
`max_steps` is a plain positive integer within the remaining original 2048-step
bound. Each `advance(steps=...)` accepts a plain integer from 1 through 4 within
the declared remaining session budget. A permitted bound is not evidence of
long-run qualification.

The all-one objective retains the original mean full-537 cross-entropy kernel
with `ignore_index=0`. The 1:4 objective retains the original unreduced full-537
cross entropy multiplied by the fixed positive position weights and divided by
their sum. Every actual update retains the original gradient clipping at global
L2 5, Adam mechanics, complete actual weights/moments validation and original
checkpoint packing fields. It commits the complete immediate predecessor hash
and complete successor identity after every step. Durable save cadence is a
separate caller choice and cannot skip this per-step state packing.

Each returned step report includes all 46-by-537 logits, scalar loss, all 13 named
preclip and postclip gradients, clipping norm, source/policy/inventory identities,
progress and the complete original-schema successor checkpoint. The prepared
execution owner is separately bound by source path and hash. Public reports set
`source_only_staged_owner` to false; the checkpoint continues to name its
unchanged original weighted owner. No portable checkpoint conversion occurs.

Sessions retain no public mutable model, optimizer or cache handle. Source bytes
and physical identity, original and captured inputs, runtime/default dtype, CPU
RNG, cached tensor identities/versions/bytes and private named model/Adam state
are fenced. Calls remain in the creating process and thread and cannot overlap.
Invalid advance arguments refuse without work and leave a valid session usable.
An integrity or numerical failure poisons further advances. Entered/completed
work counters remain available on the exception and through `inspect`.

`inspect()` is a detached historical status/counter observation; it does not
attest current live integrity. `checkpoint()` returns the last fully committed
detached checkpoint after its source/input/runtime/cache checks pass; it never
serializes partially changed live state. `close()` always attempts the retained
source/input scope exit and drops private model/Adam/cache references. A poisoned
session reports persistent failed closing checks without claiming positive
custody. A ready-session closing integrity failure raises after cleanup. After
closure, historical inspect and idempotent close remain available; advance and
checkpoint refuse. The API performs no implicit save, hidden retry, native
admission, resource reservation or publication.

The caller must enroll finite work and independently observe actual GRU,
backward and Adam calls. Model-forward counters are not independent GRU evidence.
Actual output durability requires exclusive write, file/directory fsync, saved
readback and the original native closeout. Original source/native/process/storage
owners remain responsible for admission, supervision, drain, sealing and release.

The prior **staged** candidate qualification is retained under
`artifacts/legal-ir-weighted-prepared-training-20261018-01`: seven physical
GRU/backward/Adam updates, five model/Adam allocations, four exact full-state
comparison pairs and 22 refusals across 12 subjects. It includes weighted
reference/prepared steps 1 and 2, actual saved-step-1 resume to step 2, and all-one
reference/prepared step 1. Its saved-only audit checked scalar CE, clipping and
Adam algebra without rerunning the GRU or independently differentiating it.
That cohort qualifies the staged owner, not this public import path.

The proposed, unexecuted **numerical public** consumer cohort is distinct: weighted prepared steps 1 and
2, one actual saved-step-1 resume update, and all-one prepared step 1, totaling
four physical updates and three model/Adam allocations. Compare those complete
outputs to the retained staged reference records with explicit source/provenance
changes. Reuse the original integrity-tamper evidence and add public import/lifetime
checks within the fixed budget; do not claim those checks have run. These are engineering parity/replay observations,
not four independent learned examples or a new efficacy experiment.

Phase clocks distinguish validation/restore/cache, repeated source/input and
runtime/cache fences, forward/objective/backward/clip/Adam, full-state export,
lineage packing and report export. Caller serialization/write/fsync/readback and
native closeout have their own boundaries. Per-step, cumulative, callback, worker
and native clocks overlap and must not be added as disjoint costs. In the prior
tiny cohort, source/input fences consumed 92.1–93.9% of listed productive
prepared-step intervals; that is neither a share of the full call/native run nor
isolated throughput or a justified larger-step budget. Changing the fence policy
requires separate parity and mutation/invalidation qualification.

Both objective policies are supported by the API. Complete original-BOS
generation, all-one inference, substantive all-one versus 1:4 efficacy,
source-encoder authentication, statutory/held-out accuracy, reviewed meanings,
gold eligibility, graph acceptance and Lean admission remain separate gates.
This training API grants none of those authorities. The separately qualified
weighted inference owner remains the consumer for compatible weighted states;
its checkpoint and prefix/budget contracts remain unchanged.

Construct sessions only through `prepare`. Direct construction of
`PreparedTrainingSession` with a caller dispatch is unsupported. Python name
mangling and closure privacy are API conventions, not a security boundary against
arbitrary reflection or altered Python code. Context entry calls historical
`inspect`; it does not independently attest a ready or intact session. Only a
ready session can advance. Retain the first explicit `close` report when closing
checks matter: repeated close returns historical closed status and does not
repeat or preserve all fields of that first closing observation.

The public import/input-guard profile enrolls no valid training session and no
Torch import. Its five invalid session budgets refuse at the first public guard.
This establishes importability and early refusal only; it does not establish
canonical-path forward/backward/Adam parity or a new lifecycle qualification.

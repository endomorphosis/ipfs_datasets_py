# Distributed autoencoder readiness follow-up

Next follow-up: [separate inference/training routes and adaptive parallel passes](AUTOENCODER_EXECUTION_ROUTES_20260928.md).

The campaign storage limit is now 80,000,000,000 bytes, as explicitly authorized.
The per-process CLI ceiling remains 50 GB. The existing ledger was migrated
under its exclusive lock with an atomic, durable replacement: only `limit_bytes`
changed. All 133 prior reservations, including 61 retained claims, and their
artifacts were preserved. The migration observed 5.24 GB of accounting headroom.

This follows [the initial distributed-runner report](DISTRIBUTED_AUTOENCODERS_20260928.md).
The prior interrupted smoke is historical evidence, not a completed convergence
claim. Qualification requirements remain unchanged: absolute embedding metrics,
complete source round trip, six native logic syntax grammars, disjoint tuning
validation, and actual source-locked `lake build Legal`. Only the rendered Lean
pattern receives a Lake admit. The Constitution remains unformalized.

## Recovery and source provenance

The owner retains interrupted qualification output before making a fresh bounded
qualification attempt. Valid sealed receipts still undergo exact candidate,
source, model, sample and proof validation on resume. A worker replays/renews its
journaled lease before submitting even an already-completed cached result.
Remote failure reports must bind their actual qualification producer hashes,
model configuration and sample set to the same campaign policy. Remote absolute
checkout locations may differ, but the canonical package layout and content must
match. Explicit legal/document IDs and supplied USC citations survive local
intake and census publication.

All workers verify a complete generation before acknowledgement. Sparse updates
reuse exact local parent bytes where available; corrupt cached parents fail
closed. Candidate selection remains serial, and stale siblings require rebasing.
This is not a merge or average of every concurrent candidate. Current generation
acknowledgements describe polling/batch boundaries, not instantaneous equality
on offline machines.

## Completed native checks

The extra 5 GB allowed the bounded integration to complete instead of stopping
at publication under the previous cap. This increases accounting headroom; it
does not itself make training faster. The native run used one DuckDB owner,
scoped native Quack endpoints, and two isolated local worker processes. Both
workers started from the protected 25,895,338-byte restart12 checkpoint.

| Source attempt | Result | Published evidence |
| --- | --- | --- |
| Synthetic officer/file minimum 20 days | All qualification gates passed; owner independently requalified and advanced generation 2. | [Attempt and census](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/652bf39ee65d789d0e1ffcfe5894c8e2532184c5), [sparse weights](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/cd9b9f65650cbbe1aabfe1a67628820fd8b92126) |
| Real 5 USC 8410 operative clause | Embedding metrics passed; semantic, family-syntax and Lake gates failed. Three repair goals were published; no weight promotion. | [Attempt, census and repair goals](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/8e1101c3a023f85b35f54fdc96a77fdf7b0726fc) |
| Same synthetic source ID, revised to minimum 25 days | A new revision was trained and independently requalified; generation 3 advanced. The prior revision remains auditable. | [Attempt and census](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/f135fa4dbcd1c4af07f17d93e167139c2312e920), [sparse weights](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/275323c8b5d23a48b93e239902dcac07abb60d2f) |

The synthetic fixtures also passed a disjoint 30-day tuning-validation case.
The checks include actual parsing in FOL, deontic FOL, temporal FOL, deontic
temporal FOL, DCEC and frame logic, plus installed Lean 4.26.0 running
`lake build Legal`. These are source-bound syntax projections and numeric Lean
patterns, not a proof that all six representations are semantically equivalent.
The autoencoder reconstructs embeddings; the deterministic compiler/decompiler
performs the source round trip. Mock stable-hash embeddings were used. Passing
these fixtures is not evidence of generalization to federal laws.

The root independently hashed actual full files on the owner and both workers:

| Generation | Complete bytes | Identical full SHA-256 on all three processes' stores | Existing-worker download |
| --- | ---: | --- | ---: |
| 2 | 26,626,197 | `94def2e094be8e66e8d6ef6cfafcb54eeb406700b1238deaba30a388c8abed30` | 1,613,803 bytes |
| 3 | 26,630,540 | `74d4b62a317009c9eeb9e9528c166dcc891b1a9adbea20285717802fd678a4b6` | 1,611,640 bytes |

Both workers acknowledged each canonical generation. The download totals include
evidence; verified local parents were reused. A fresh replacement worker with no
local weights downloaded 29,120,781 bytes across the seed and two sparse
generations, then reconstructed the same generation-3 hash. This checks the
portable ancestry independently of local parent reuse.

After a cold owner restart, both workers resumed with normal claiming enabled.
Each reported zero new jobs, kept generation 3, and produced no additional job
or cycle receipts. The owner retained its campaign and refreshed the private
connection credentials. All smoke processes subsequently exited; the validation
does not leave an unattended campaign running.

The focused readiness suite passed **220 tests in 40.58 seconds**, including the
explicitly enabled native storage/Quack probe. After the feed fix, a separate
overlapping integration suite passed **137 tests in 12.43 seconds**. These counts
are separate runs, not 357 distinct tests. Native qualification receipts,
optimizer profiles, full-file hashes, source manifests, Lean source and logs
are preserved under
[the evidence directory](evidence/distributed-autoencoders-80gb-20260928).

## Measured work and storage

Each row below is a one-sample job with one legal-IR target before and after
training. Bridge names were `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, and `external_prover_router`; prover evaluation was false, disk metric
cache was disabled, parallel workers was 1, and sample memory was false. The
process began cold; targets may be reused inside that process. Projection used
`python_sparse_batch`, one epoch, one line-search attempt, up to five update
families and a 120-second bound.

| Source | Compile/decompile qualification wall time per span | First bridge-on evaluate wall time | Training wall time per span |
| --- | ---: | ---: | ---: |
| Synthetic 20 days | 0.052 s | 4.487 s | 6.035 s |
| Real 5 USC 8410 | 0.025 s, failed | 5.294 s | 9.666 s |
| Synthetic revision, 25 days | 0.050 s | 4.464 s | 6.171 s |

These are separate phases, not complete job latency or a speedup comparison
against the earlier three-sentence benchmark. The later qualification embedding
evaluate has no IR bridges and is not included as a legal-IR timing. Worker
cycle processes coexisted, but sampled native optimizer lifetimes did not
overlap. Simultaneous optimizer throughput remains unmeasured.

DuckDB records campaign state, versions, leases and immutable artifact references;
Quack carries bounded control operations. Training in this smoke used private
JSON weights and sparse patch transport, not shared SQL updates per parameter
or the optional Arrow weight backend. Existing DuckLake interfaces were not
changed or newly qualified by this test. Canonical candidate selection is serial;
stale siblings must rebase rather than silently merge competing updates.

## Census re-ingestion

Qualification attempts already publish the original normalized source record.
The follow-up feed fix restores its exact stable record ID, sample metadata,
explicit legal/document IDs and embedding data after validating the sealed
attempt and its binding to the census. This prevents a local source's own census
from scheduling an extra job under a newly invented feed identity. Historical
generic census rows retain their existing intake behavior. Dataset observations
remain observations; importing them cannot authorize admission or goal execution.

The native training run preceded this narrow feed fix and used local JSONL
input. Re-ingestion is checked separately using the actual emitted native
bundles and regression tests. Because source hashes are part of campaign policy,
using the changed feed source requires a new campaign rather than rewriting this
completed smoke's provenance.

All three actual emitted bundles restored their original records exactly.
Registering the original and re-ingested records in an isolated real DuckDB
campaign created **zero additional jobs**. Regression tests also reject altered
text, digests, span/citation bindings, malformed attempt payloads and conflicting
metadata under the same identity.

## Operational scope

No physical remote hosts have been provided. Local native multi-process evidence
does not claim a tested cross-host deployment. Native semantic evidence is scoped
to the pinned workspace; concurrent semantic edits outside this change must not
be silently attributed to a clean `origin/main` checkout. The
[source comparison](evidence/distributed-autoencoders-80gb-20260928/source-scope.json)
lists the exact differences between captured native sources and the scoped
publication. Invalid remote reports
still stop the owner for explicit investigation; they never qualify or promote
weights. Operators must investigate these errors before restarting. The current
evidence supports a bounded supervised pilot with matching sources and explicit
resource reservations. Cross-host deployment, overlapping optimizer throughput,
production embeddings and a held-out federal-corpus canary remain outstanding.
Use the owner/worker commands in the initial report with a new campaign ID after
source changes. No qualification threshold was loosened, no retained historical
reservation was released, and the protected restart12 checkpoint was unchanged.

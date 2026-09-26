# Durable index enforcement for training jobs

Implementation milestone, 2026-09-25, continuing the
[pinned U.S. Code source audit](autoencoder_uscode_source_index.md) and
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).

## Contract

Opt-in `autoencoder-training-job-v5` binds a corpus batch to both an exact
`corpus_index_artifact` and an expected `corpus_selection_sha256`. It requires
the existing source manifest and its complete source-artifact closure. The
worker verifies source bytes and ordered sample membership, loads the bounded
index by SHA-256 and size, compares the selection identity, and checks the
batch against the frozen assignments before loading model state or creating
an attempt directory.

V5 requires explicit, nonempty validation samples. Otherwise the projection
trainer would fall back to training samples for line-search validation, which
would bypass the index's separate validation authorization. Canary and holdout
records remain excluded from both operations. Existing diagnostic v1–v4 jobs
retain their historical behavior and serialization.

The owner requires a registered variant manifest containing:

```json
{
  "corpus_index_binding": {
    "selection_sha256": "<SHA-256 of the declared selection>",
    "artifact": {"sha256": "<index SHA-256>", "bytes": 62711}
  }
}
```

The example byte count belongs to the selected 64-record audit index; it is
not a general constant. The binding has a closed shape and must match the job.
The index, batch and source artifacts must name the owner's verified staged
copies. A variant with this binding refuses older unindexed job schemas.
Because registered variants are immutable, later calls and owner restarts
cannot change the split policy for that variant. A new selection/index requires
an explicit new variant identity.

The owner computes input verification independently, compares it with the
persisted worker receipt, and retains the index binding in the durable result.
The existing single-owner DuckDB registry and staged artifact path provide
this behavior without new tables, remote weight lookups or worker database
connections. This milestone does not activate production DuckLake or change
the Quack transport.

## Qualification

The [native input audit](evidence/autoencoder_control_plane_plan/indexed-jobs-20260925.json)
passed using the previously verified 64-record selection. Two independently
spawned processes each verified 27 distinct training records and the same
three validation records. Their full verification summaries matched the
owner's independently computed summaries. The one canary and six holdout
records were excluded from both batches.

| Check | Result |
|---|---|
| Changed index, selection mismatch, unstaged index path | Rejected before a lease or attempt output |
| V4 downgrade on an indexed variant | Rejected before dispatch |
| Validation record in training / training record in validation | Rejected independently by owner and worker |
| Owner restart | Variant binding and exact verification summaries preserved |
| Later index substitution / variant rebinding | Rejected after restart |
| Archived job identities | All 39 exact payloads and hashes preserved: 8 v1, 13 v2, 14 v3, 4 v4 |
| Original checkpoint | Pinned SHA-256 unchanged |

The earliest four v1 job payloads omitted `expected_source_sha256`; later
payloads explicitly used an empty object. Decoding now preserves that old
omission rather than adding the newer default and changing its hash.

Owner preflight for both batches took 0.2287 seconds. The two spawned verifiers
took 0.2823 seconds including dispatch, with 0.0713 and 0.0712 seconds inside
the verification calls. The entire audit took 2.9604 seconds and retained
45,432,038 bytes of local artifacts/database data plus a 49,755-byte receipt.
These are input-verification timings; OS caches were uncontrolled. No model
loaded, no bridge evaluation or training ran, and the vectors remain
training-ineligible. The isolated audit database retains queued, unleased
test jobs; no training service is attached to it.

The [regression receipt](evidence/autoencoder_control_plane_plan/indexed-jobs-tests-20260925.json)
records **311 passing control-plane tests** and **66 passing semantic/router
guards**. The control suites cover durable candidate completion using injected
trainers, restart, receipt forgery, bounds, sparse patch handling and all
forbidden train/validation placements of protected records. The native audit
does not claim projection-training qualification for this new data selection.

The broader guards exposed an existing repair-path `NameError`: a nested class
assigned `modal_ir = modal_ir`, hiding the enclosing local. A `SimpleNamespace`
now carries the same sample ID, text and IR. The existing repair tests retain
one retry, source grounding, abstention and no-admission checks. Two stale test
expectations were aligned with the current API: the no-parser result includes
`fields: []`, and the Constitution test double accepts and asserts
`allow_partial=False`. The three required semantic gates remain green.

## Scope and opportunity cost

The binding guarantees consistency within a registered variant. It does not
prevent a caller from registering another variant, establish global holdout
isolation, authenticate official source bytes, or prove that a checkpoint has
never seen an indexed record. The index's declared release roots and selection
digest retain their existing provenance limits. Published U.S. Code vectors
still lack exact input and producer evidence and remain ineligible for corpus
training. No Constitution span becomes `roundtrip_ok`.

The index is read and verified at owner preflight and again in each worker.
That repeated integrity work is a measured preparation cost. It avoids a
remote query for each sample and preserves independent enforcement. Source
and index artifacts are staged once and shared read-only across workers;
training overlays and accepted sparse patches retain their existing behavior.

The six-module worker source manifest does not attest the entire enforcement
implementation. The native audit separately records the worker, coordinator,
index, corpus manifest, registry, pinned logic modules and audit script hashes.

The bounded follow-up review found no local producer receipt binding the
published `5016b86a…` vectors. Historical publication and fixture receipts refer
to other releases or deterministic projection fixtures. The existing
`uscode_embeddings.py` producer hashes normalized text while embedding composed
text, and its publication projection omits input/backend evidence. Those
receipts cannot be filled in retrospectively from a model name.

Follow-up: the [native embedding and v6 milestone](autoencoder_native_embedding_production.md)
implements bounded regeneration using the already cached exact GTE snapshot
`17e1f347d17fe144873b1201da91788898c639cd`, without downloads. Its closed
producer sidecar binds exact UTF-8 inputs and source selectors, captured token
IDs/counts, inference settings, model/tokenizer/pooling assets and exact output
bits. Opt-in v6 jobs and variants require independent owner/worker verification.
The 64-row native audit produced 51 vectors and rejected 13 oversized inputs;
the context limit remains 512. Historical published vectors remain unqualified.

Regenerated vectors change record identities, requiring a new index artifact
and variant binding. The native audit verifies split continuity for retained
whole-row source groups. New chunk boundaries still require explicit continuity
and coverage checks. Next materialize numeric inputs in Arrow, prepare complete
shared targets, and benchmark bounded parallel candidates with the index and
producer bindings enforced.
The full selected inventory and lineage review remain prerequisites for
campaign-wide splits; an input audit is not a legal-IR speed measurement.

Only actual `lake build <Lib>` evidence can establish a Lean admit. No source
verification, split assignment, optimizer result or database row is an admit.

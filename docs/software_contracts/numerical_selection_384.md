# Captured-source NumPy selection inference

[`codebase_numerical_selection_384.py`](../../ipfs_datasets_py/logic/software_contracts/codebase_numerical_selection_384.py)
consumes the explicitly selected `numpy-unary-selection-384@1` development
checkpoint through the native source index and autoencoder registry. Its
[isolated worker](../../ipfs_datasets_py/logic/software_contracts/codebase_numerical_selection_384_worker.py)
runs pinned GTE-small on CPU, then calls the unchanged shared numerical decoder.
The supervisor consumes this API; embeddings, checkpoint interpretation and
retained inference belong to `ipfs_datasets_py`.

The accepted checkpoint is the [documented development release](../autoencoder_ownership.md#experimental-learned-numerical-call-profile):
`Publicus/security-ir-autoencoder`, revision
`38666f43e998d55b5f4259e354286f5929027ba1`, file
`releases/20261011-numpy-unary-selection-384-development-v1/checkpoint.json`,
SHA-256 `26ccc7cf8420e0ed6cbbe22603e09be0e3572fb32a1e489e877fc5081f506e03`.
The owner requires these already-local bytes and the pinned GTE snapshot.
Loading checks the frozen Legal-parent lineage, closed CALL grammar and producer
pins. It neither downloads assets nor selects a default supervisor checkpoint.

## API and ownership

Use an existing `RepositoryCodebaseIndex` with a catalog, a captured
`CodebaseHead`, and a separate native `AutoencoderRegistry` database:

```python
from ipfs_datasets_py.logic.software_contracts.codebase_numerical_selection_384 import (
    RELEASE, infer_numerical_selection, validate_numerical_selection,
)

assets = dict(
    checkpoint_path=checkpoint_path,
    checkpoint_sha256=RELEASE["checkpoint_file_sha256"],
    embedding_snapshot=gte_snapshot_path,
)
result = infer_numerical_selection(
    index, repository, expected_head=head, registry=registry,
    paths=["selection.py"], **assets,
    timeout_seconds=180, memory_mb=4096,
)
validate_numerical_selection(index, repository, result, registry=registry, **assets)
```

Both calls accept `scheduler`, `parent_lease`, `cancel_event`, and
`budget_profile`. The explicit existing
`source384-5cpu-20gib-formalization@1` profile permits an overall deadline up to
3600 seconds; it does not reset the deadline between source fences, admission,
worker execution and replay. RSS enforcement samples the process tree and can
overshoot its reservation. The worker has no provider or training path.

`prepare_numerical_selection` reads captured source without asserting that it is
current. The inference and validation APIs fence that historical population
with current repository observations. `load_numerical_selection` authenticates a
committed historical artifact without current-source observations. Callers must
choose the appropriate API rather than treating historical replay as freshness.

## Complete population and unchanged predictions

The owner accounts for every supplied path, up to 256 distinct captured files.
It selects at most 128 eligible modules in canonical path order. Unsupported
files do not consume the eligible selection budget. Byte limits, opaque input,
unsupported grammar and selection deferrals remain in `preparation.files`.
Eligible modules are bounded to 65,536 bytes and 16,384 characters; the complete
read population is bounded to 4 MiB.

Each embedding input is the exact original module, including imports and
comments. Tokenization includes special tokens and has no truncation. Inputs
above 512 tokens produce `deferred_gte_token_limit` with no vector or candidate.
Identical whole-source bytes share one embedding, while their distinct file and
function-unit identities remain accounted for. Native embedding receipts retain
exact source selectors, token inputs, float32 vectors, asset hashes and runtime
versions. The receipt codec uses `diagnostic`/`und` source metadata for software;
it does not classify these inputs as legal training records.

The decoder currently accepts only imports and one plain function returning
`numpy.argmax` or `numpy.argmin` of one positional parameter. The owner preserves
the learned candidate and independently compares it to deterministic source IR.
Matching rows are `source_aligned_fragment`; mismatches are
`fail_open_source_mismatch` and carry no matched projection references. It never
repairs a wrong learned operator or operand with the checking reference.

## Retained evidence and limits

The result contains `artifact`, `report`, `native_worker_executed` and
`inference_executed`. The report retains its exact `key`, source preparation,
worker output, native execution receipt and coverage. The key distinguishes
`checkpoint_file_sha256` from `checkpoint_canonical_sha256`: release file bytes
and canonical parsed JSON are different identities. It also binds the model
head, inherited projection, producer sources, embedding assets and runtime.

The registry commits an `IndexNumericalSelectionInference` operation over that
key. Cold replay rechecks artifact identity, source maps, embedding receipts,
coverage and deterministic projection references without embedding or decoding
again. Cached calls return false execution flags; retained `model_loads` still
describes the original execution. A changed source, model, producer or receipt
is refused rather than silently reusing stale advice.

All proof, execution and completion authority stays false, and discharged source
obligations stay zero. A matching CALL fragment does not establish whole-function
behavior, runtime NumPy identity, numerical correctness, or a completed task.
The unchanged inner decoder still reports `embedding_provenance_verified=False`;
the separate native embedding receipt supplies the owner's source/vector
integrity evidence. These are trusted local execution records, not cryptographic
attestations or an independent proof that the neural computation is correct.

The [integration tests](../../tests/integration/logic/software_contracts/test_codebase_numerical_selection_384.py)
cover actual cached CPU inference, original-source preservation, duplicate input
accounting, token deferral, cold registry replay with model seams forbidden,
receipt tampering, staleness, unsupported input, budget limits and cancellation.
Set `NUMERICAL_SELECTION384_CHECKPOINT` and
`CODEBASE384_EMBEDDING_SNAPSHOT` to explicit local assets to run the native cases;
otherwise they are explicitly skipped. On 2026-10-11, the core run passed 28
tests and the subsequent budget/cancellation run passed both additional tests.
Local commands, logs, source hashes and JUnit results are retained under
`artifacts/supervisor-numerical-adapter-20261011/datasets-02/` and
`datasets-budget-01/` in the supervisor workspace. These checks did not measure
Terminal-Bench success, token savings, holdout improvement, or theorem discharge.

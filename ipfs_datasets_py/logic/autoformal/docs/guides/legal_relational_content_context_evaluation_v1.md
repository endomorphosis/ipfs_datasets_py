# Relational CONTENT context availability companion v1

This diagnostic records the availability of separately supplied signature and
ordered-role contexts for the **complete existing selected population**. It
replays `prepare_relational_content_token_batch_evaluation_v1` through its
public API and embeds that complete report unchanged. Prediction statuses,
reference availability, structural comparisons and their denominators remain
owned by that existing batch evaluator.

An accepted context asset means only that the existing public token-prefix
owner accepted the offered bytes under the fixed context schema. It does not
establish source fidelity, legal-role correctness, target independence,
availability before generation, or permission to use the context at inference
time. All authority fields are false and both masks remain integer zero.

## Public interface

The standard-library-only import is:

```python
from ipfs_datasets_py.logic.autoformal import legal_relational_content_context_evaluation_v1
```

Its public operations are:

```python
prepare_relational_content_context_evaluation_v1(
    population_raw, references_raw, predictions_raw, contexts_raw,
    *, expected_population_sha256, expected_references_sha256,
    expected_predictions_sha256, expected_contexts_sha256,
)
relational_content_context_evaluation_sha256(report)
validate_relational_content_context_evaluation_v1(
    report, population_raw, references_raw, predictions_raw, contexts_raw,
    *, expected_evaluation_sha256, expected_population_sha256,
    expected_references_sha256, expected_predictions_sha256,
    expected_contexts_sha256,
)
```

Inputs are exact immutable UTF8 JSON byte transports with independently
supplied SHA256 pins. The first three inputs use the existing CONTENT batch
schemas without alteration. `predictions_raw` supplies the original fixed
537-entry codec and its independent hash. The companion neither invents a
codec nor substitutes a context from references or generated output.

The hash helper hashes a complete closed report. It does not validate its
historical truth. The validation API requires the independent complete output
pin and regenerates the complete report from all four original inputs; a
resealed changed report cannot pass merely by matching its own new hash.

## Context inventory

`contexts_raw` has exactly these fields:

```json
{
  "schema": "legal-relational-content-context-inventory/v1",
  "population_sha256": "independently supplied original population hash",
  "rows": []
}
```

Each well-formed row has exactly:

```text
id, source_sha256, context_sha256, status,
content_context_utf8, content_context_sha256, content_context_origin, reason
```

`id`, `source_sha256`, and `context_sha256` bind an occurrence in the original
population. The source `context_sha256` and the signature/role
`content_context_sha256` commit **different objects**. Equality of these
caller-supplied commitments does not authenticate their source provenance.

For `status="available"`, the context text and raw hash are required,
`reason` is null, and the declared origin is one of:

- `authored_fixture`
- `target_derived_label`
- `caller_supplied_unverified`

For `unavailable`, `unsupported`, `pending`, `error`, `timeout`,
`cancellation`, or `not_started`, all three content-context fields are null
and `reason` is a nonempty bounded string. These dispositions are caller
declarations; they do not authenticate an execution or clock interval.

Malformed ordinary JSON rows remain in the raw ledger. An independently
offered context byte/hash pair is checked even when its row is duplicated,
unexpected, unidentifiable, or otherwise malformed. A syntactically valid
SHA256 that disagrees with the bytes, an invalid context asset, source drift,
an owner refusal or an interruption aborts the whole operation. A field of
the wrong type or a malformed digest spelling is a structural row failure,
not an independently bound asset. No partial report is returned.

## Evidence and accounting

The report schema is `legal-relational-content-context-evaluation/v1`, with
profile `full-selected-unverified-content-context-inventory/v1`.

| Field | Meaning |
| --- | --- |
| `inputs` | Original raw SHA256 and byte count for all four transports. |
| `original_evaluation` | Complete unchanged result of the existing public CONTENT batch owner. |
| `original_evaluation_sha256` | Canonical hash of that complete original result. |
| `population` | Exact original batch population commitment, order, partition and selection. |
| `coverage` | Expected and submitted counts; missing IDs; duplicate and unexpected ID-to-arrival-index maps; unidentifiable arrival indices. `valid` is identity coverage only, not semantic or asset admission. |
| `observation_ledger` | Every inventory observation in original arrival order, with complete raw value, canonical row hash, association, shape/binding reasons, terminal outcome and full available empty-prefix record. |
| `occurrences` | Every original selected occurrence in original order, with all associated inventory indices and one availability status. |
| `availability_counts` | Counts across that exact selected population, never an available-only subset. |
| `generated_context_bindings` | Separate context-binding diagnostic for every original prediction observation, without changing any original status or comparison. |
| `generated_context_binding_counts` | Counts over all original prediction observations, not a model-success rate. |
| `producer_pins` | Fixed reviewed operation owners and the dependency closure supplied by their actual public replay. |

Inventory selected-occurrence statuses are the eight declared statuses above,
plus `missing`, `duplicate`, `malformed`, and `unverifiable_binding`.
Precedence is missing, duplicate, malformed, source-binding conflict, then the
well-formed declared status. A duplicate never chooses a favorable available
row. Unexpected and unidentifiable inventory rows remain fully retained but
do not expand the selected population. A declared unavailable context remains
unavailable even when the corresponding prediction carries context bytes.

Every independently offered context asset is sent to the existing public
`compact_content_allowed_token_ids_v1([], context_raw, ...)` operation with
the exact original prediction codec and independent context/codec hashes.
The companion retains the complete returned record and its canonical hash.
It verifies the expected empty-prefix state, BOS-only immediate choice,
remaining budget, exact raw and canonical context commitments, the two fixed
producer source records, false authority and zero masks. This checks local
prefix intake only; it does not prove global completion or broad-catalog
selection. The profile still requires every declared predicate to occur.

For a generated observation with one available inventory row, three facts
are kept separately:

- `raw_equal`: exact supplied context strings and raw hashes agree.
- `canonical_equal`: the two independently checked canonical context hashes
  agree.
- `origin_equal`: the two unverified origin labels agree.

All three must hold for `matched`. Whitespace changes can therefore yield
`mismatched` with `canonical_equal=true`. Changes in valid ordered roles
remain visible as canonical differences. `matched` is not semantic fidelity
or inference permission. Original generated duplicates are each compared
independently and retain `original_outcome="duplicate"`; no duplicate gains
prediction credit.

Other binding statuses are `unavailable`, `missing`, `duplicate`, `malformed`,
`unverifiable_binding`, `unexpected`, and `unidentifiable`.
`not_generated` explicitly covers original observations that do not declare
generated output. Unknown equality fields remain null. An empty original
prediction ledger produces no binding observations; it does not erase a
separately supplied context inventory or imply that a model ran.

## Source and resource boundaries

This version admits these exact direct source generations before lazy
operation imports:

| Owner | SHA256 |
| --- | --- |
| `legal_relational_batch_evaluation_v1.py` | `663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138` |
| `legal_compact_content_tokens_v1.py` | `145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e` |
| `legal_compact_content_v1.py` | `de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e` |

Actual canonical module origins, available import anchors, nofollow regular
source custody, source bytes and physical identities are checked. The
executed batch owner's producer closure supplies the additional fixed
dependencies; input artifacts cannot nominate source reads. The companion
does not change the original batch's caches or guards. Complete input,
original-report and source fences run again after final serialization.
Snapshots are not a general proof of executed bytecode for arbitrary
preloaded modules; an admitted native execution supplies separate evidence.

The inventory permits at most 256 raw rows and 4MiB of original bytes. It
inherits the existing context asset bound of 524288 bytes. The original
batch retains its existing population, prediction, reference and 8MiB report
bounds. The companion has a separate complete 16MiB report bound, 500000
ordinary JSON nodes and maximum depth96. Overflow refuses the whole
operation without truncating rows, contexts or the original report.

This operation performs no training, generation, numerical head activation,
provider call, database access, Lean execution, legal review, admission or
publication. No claims about token savings, trained accuracy, source-only
context, checkpoint compatibility or protected evaluation follow from an
availability report. Native tests and any retained authored fixtures must be
reported separately from such scientific claims.

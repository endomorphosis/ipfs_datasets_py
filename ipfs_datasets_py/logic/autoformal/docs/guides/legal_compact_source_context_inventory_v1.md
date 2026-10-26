# Original-bound source/context inventory

`ipfs_datasets_py.logic.autoformal.legal_compact_source_context_inventory_v1`
is a separate engineering companion for a finite selected population. It joins
complete physical source membership, declared cache/catalog revision and declared
access policy to the existing lexical context owner. A successful report verifies
consistency with the supplied originals. It grants no actual inference permission,
legal meaning, source authentication, training eligibility or evaluation authority.

This guide describes the API contract. Qualification results are recorded in
separate stage receipts; the guide itself supplies no execution result. The
existing lexical bridge's prior 239-case qualification is a dependency and
receives no additional execution credit.

## Public APIs

```python
prepare_source_context_inventory_v1(
    population_raw, occurrences_raw, catalog_raw, access_raw,
    *, expected_population_sha256, expected_occurrences_sha256,
    expected_catalog_sha256, expected_access_sha256,
    source_partitions, expected_source_partitions_sha256, source_resolver,
)

source_context_inventory_sha256(report)

validate_source_context_inventory_v1(
    report, population_raw, occurrences_raw, catalog_raw, access_raw,
    *, expected_report_sha256, expected_population_sha256,
    expected_occurrences_sha256, expected_catalog_sha256,
    expected_access_sha256, source_partitions,
    expected_source_partitions_sha256, source_resolver,
)
```

The four transport inputs are exact nonempty UTF8 JSON `bytes`. Their expected
SHA256 values are independent lowercase 64-hex pins. The hash helper computes
bounded canonical JSON identity only; it does not validate a report. Validation
requires the same original inputs, their expected pins, the exact typed partition
artifact and resolver. It regenerates the whole report and compares every field,
then checks that the caller's mutable report stayed unchanged. It returns the
fresh detached replay. Rehashing a changed output cannot replace this replay.
Replacing every original and expected pin constitutes a different operation that
this consistency API cannot distinguish from an independently authorized request.

Contract refusals raise `ValueError`; the companion's own exception is
`CompactSourceContextInventoryError`, a `ValueError` subclass. Existing public
owners retain their own `ValueError` subclasses. An arbitrary exception raised
by an injected resolver remains an exception, with closing custody checks still
attempted; only an explicit `None` represents a missing artifact.

## Four independent originals

The population reuses the existing closed schema:

```json
{
  "schema": "legal-relational-batch-population/v1",
  "partition": "train",
  "selection_sha256": "independently supplied selection SHA256",
  "rows": [{"id": "occurrence-1", "source_sha256": "selected text SHA256", "context_sha256": "preexisting source-context SHA256"}]
}
```

The occurrences original has exactly these fields:

```json
{
  "schema": "legal-compact-source-context-occurrences/v1",
  "population_sha256": "population raw SHA256",
  "source_partitions_sha256": "exact typed SourcePartitions raw SHA256",
  "cache_revision": {
    "repo_id": "caller-supplied cache repository",
    "revision": "immutable lowercase 40- or 64-hex revision",
    "catalog_sha256": "catalog raw SHA256"
  },
  "rows": [{
    "id": "occurrence-1",
    "entry_cid": "eligible existing source-inventory entry",
    "source_row_id": "complete physical source row identity",
    "source_request": {
      "occurrence_id": "occurrence-1",
      "input": "the complete existing EmbeddingInput.to_dict() object"
    }
  }]
}
```

The quoted placeholders above stand for actual values or objects. Every input
object has all six public fields: derived `input_id`, complete `source`, `title`,
`section`, `text` and `citation`. The complete source span retains its artifact
descriptor, source kind, release/document identity, language, citation, byte
selector and normalization. Public `EmbeddingInput.from_dict` must reproduce it
exactly. The source kind is `us_code`; release identity and canonical document,
title, section, citation, selected text hash and text length must also agree with
the full source inventory's metadata. Equal text alone never substitutes for a
physical row, entry, source request or input identity.

The catalog is the unchanged `legal-compact-source-catalog/v1` accepted by
`legal_compact_source_context_v1`: schema, full signature, ordered argument-role
declarations and exact aliases. There is no target expression, prediction, AST,
teacher-target payload or identity-sidecar field in any of these closed inputs.
This means the companion receives no explicit reference/prediction input; it
does not prove that opaque source text, aliases, role names or catalog metadata
contain no target information. Source/catalog independence remains unverified.

The fourth original is a declared access record:

```json
{
  "schema": "legal-compact-source-context-access/v1",
  "population_sha256": "population raw SHA256",
  "occurrences_sha256": "occurrences raw SHA256",
  "catalog_sha256": "catalog raw SHA256",
  "rows": [{
    "id": "occurrence-1",
    "operation": "inference",
    "disposition": "allow",
    "origin": "source_derived",
    "review_record_sha256": null
  }]
}
```

`disposition` is `allow`, `deny` or `unavailable`. Origins are `source_derived`,
`authored_diagnostic`, `target_derived`, `teacher_target`, `identity_sidecar` and
`unknown`. A review-record SHA256 may be null or an exact lowercase digest. Its
presence does not authenticate a reviewer or load a review decision. Cache
revision and access declarations remain unverified external assertions.

Occurrences and access rows must each match the full population in exact order.
Missing, duplicate, orphan and reordered rows refuse the whole operation. Every
selected physical entry is unique and must be eligible in the supplied partitions.
Multiple different physical entries can retain distinct occurrence identities
even when their text, context or input identities coincide.

## Existing full-inventory grouping

`source_partitions` must have the exact existing `SourcePartitions` type and an
exact `USCodeSourceInventory`, with independently pinned raw partition bytes.
The companion reconstructs the full inventory and partition artifact through
their real public codecs. It replays the existing policy and grouping; it does
not compute a second grouping algorithm or invent group IDs.

Every physical inventory row participates, including excluded or unselected
connectors. Existing grouping uses document identity, source-artifact content
and normalized-content connectivity. It intentionally can connect equal text
across distinct documents while preserving each physical occurrence. Each selected
row must match `binding_for(entry_cid)` in full source-row identity and input ID;
its split must equal the population partition. The report retains the existing
grouping schema, content normalization, policy, full physical counts and verified
partition summary. This is the complete **declared metadata** scope, not a fresh
Parquet scan, independent cache-record authentication or a global holdout proof.

Shared governing-definition/context dependency closure is not represented by this
grouping owner and remains deferred. The companion does not declare that missing
closure complete or silently authorize training from a matching split.

## Source resolver and lexical reuse

The resolver receives a detached exact `{sha256, bytes}` descriptor. Return the
complete immutable source artifact `bytes`, or `None` for explicit unavailability.
Wrong size/hash, non-bytes, invalid UTF8, a selector that splits UTF8 or a selected
slice unequal to the exact input text refuses the operation. Embedded `input.text`
is checked against resolved bytes and is never a fallback for a missing artifact.
Each distinct artifact digest is resolved once per operation, with consistent
declared size across uses. All supplied physical sources are checked, including
ones whose declared access is denied.

The four original raw hashes and complete membership/access joins are checked
before any resolver call or lexical preparation. The producer source pins, full
partition/inventory raw witnesses, limits, summary and selected bindings are
checked across resolver callbacks. Mutation of the detached descriptor refuses
the operation. Full partition reconstruction runs again before returning.
These named Python custody checks are not an OS sandbox, runtime attestation or
proof against arbitrary introspection and caller-supplied code.
The no-model/target/database/prover flags describe the companion's own declared
operations; they do not attest arbitrary behavior inside a supplied resolver.

The complete catalog is validated even when every row is missing or blocked.
This uses the unchanged public lexical owner with fixed diagnostic bytes
`b"catalog validation only"`. Its result is discarded. The report records
`catalog_validated: true` and
`catalog_validation.role: "fixed_diagnostic_probe_not_population"` with the
probe's source hash. Probe matches add no source, population or nomination credit.

Actual row nomination uses only verified selected source bytes and the unchanged
public lexical matcher. Exact Unicode matching, ambiguities, bounds, catalog
validation, ordered role preservation and the inherited all-selected-predicates
grammar rule remain that owner's contract. No matcher or context assembler is
reimplemented here.

## Rows, dispositions and identities

The report has schema `legal-compact-source-context-inventory/v1`, profile
`declared-source-cache-access-consistency/v1` and status
`complete_declared_inventory`. It retains the four raw input identities, full
ordered population, cache declaration, grouping summary and one row per original
occurrence. Each row has exactly one `context_status`, in this priority order:

| Condition | Terminal status | Candidate context |
| --- | --- | --- |
| Resolver returned `None` | `source_unavailable` | null |
| Available source, declared deny | `access_denied` | null |
| Available source, access unavailable | `access_unavailable` | null |
| Declared allow with any target/sidecar/unknown origin | `origin_not_allowed` | null |
| Allowed source/diagnostic origin, observed shared alias | `ambiguous` | null |
| Allowed source/diagnostic origin, no alias match | `no_match` | null |
| Allowed source/diagnostic origin, unambiguous matches | `nominated_for_inspection` | supplied lexical context |

The available/blocked statuses retain source verification separately. Missing
sources have `source_bytes_verified: false`; they receive no manufactured byte
verification. Ambiguous and no-match rows preserve the full lexical report.
Access-blocked rows do not run row nomination and have a null lexical report.

Every row keeps its complete original source request, partition binding, declared
access record and `population_context_sha256`. A nomination additionally retains
`candidate_context`, `compact_context_raw_sha256` and `compact_context_sha256`.
Here the compact raw bytes are the companion's sorted-key compact UTF8 JSON
serialization of that candidate; canonical identity remains the existing owner's
identity. The two compact hashes can coincide, but both fields remain distinct
from the preexisting population source-context hash.

`symbol_role_derivations` retains catalog/selected indices, lexical match indices,
the exact signature declaration and ordered roles. `role_origin` remains
`caller_declared_catalog_not_verified_legal_roles`. An alias occurrence does not
derive the role's legal meaning.

Coverage counts the entire supplied population and every terminal disposition.
No unavailable, ambiguous or denied occurrence is removed. All rows have
`encoder_status: "not_supplied"` and `inference_view: null`. Every authority flag
is false; top-level and per-row training/evaluation-gold masks are integer zero.
Even a declared-allow nomination provides no effective inference view.

## Bounds and promotion limits

The companion accepts 1–128 selected occurrences, a 128 KiB population, 16 MiB
occurrences original, 512 KiB catalog and 256 KiB access original. Each selected
text is at most 65,536 bytes. A source artifact is at most 4 MiB; unique declared
source artifacts together are at most 8 MiB. Partition and full inventory raw
metadata each remain at most 64 MiB. The detached output is at most 16 MiB.
The existing compact JSON depth/item/type bounds and lexical limits also apply.
All floats, custom JSON values, cycles, invalid scalar UTF8 and unknown fields
refuse rather than normalize or truncate. Bound overflow returns no partial
inventory or favorable subset.

Direct existing owner sources are pinned before genuine package imports and
checked throughout the operation. The lexical owner's fixed context owner
continues to apply its own dependency fences. These source checks grant no
binary/cached-bytecode authentication or new authority to existing declarations.

This slice does not attach native encoder receipts, authenticate external cache
or review records, establish pre-target chronology, rescan Parquet, execute a
model, fit a trainer, evaluate held-out tasks, index a database, run a supervisor,
admit a theorem or build Lean. Those later gates retain their own evidence and
existing v1 reports. A successful finite inventory must not be reported as legal
source-to-model equivalence, full task satisfaction, convergence or token savings.

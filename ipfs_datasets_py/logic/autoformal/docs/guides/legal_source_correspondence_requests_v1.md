# Complete source-correspondence review requests

`legal_source_correspondence_requests_v1` turns an independently pinned ordered
bank population into the existing source-review preparations and an explicit
physical cache-reference roster. It performs no file or network reads itself.
The existing review owner replays the supplied original join, paired-row,
producer-receipt and stored-section inputs. All source alternatives and
unresolved outcomes remain available for actual review.

The physical cache coordinates are supplied declarations. This operation does
not reopen the cache's Parquet tables or freshly authenticate their row bytes.
A caller can bind those declarations to a retained independently pinned
crosswalk as separate evidence. Original source custody and prior independently
checked source-row oracles are separate companions; they do not establish the
producer's intended character occurrence, legal edition or governing meaning.

## Public API

```python
source_correspondence_original_bank_sha256(bank, *, limits=None)

prepare_source_correspondence_requests_v1(
    request_raw, *, expected_request_sha256, original_banks, limits=None,
)

source_correspondence_requests_sha256(report, *, limits=None)

validate_source_correspondence_requests_v1(
    report, request_raw, *, expected_report_sha256,
    expected_request_sha256, original_banks, limits=None,
)
```

Wrapper contract failures raise `SourceCorrespondenceRequestsError`, a
`ValueError` subclass. Existing join/review contract failures retain their
existing exception types. Neither hashing helper validates original source
authority. The report helper only returns a bounded canonical content identity;
the public validator regenerates the entire report from the original inputs.

## Complete original banks

`original_banks` is a nonempty ordered plain list. Each bank has exactly:

```text
bank_id             nonempty bounded string, distinct across banks
join_bytes          immutable original sealed legacy-join JSON bytes
paired_row_bytes    complete ordered list of immutable logical paired-row bytes
join_inputs         exactly the five original build_legacy_source_join arguments
physical_rows       complete ordered declared physical-reference list
```

The five `join_inputs` keys are `expected_population`,
`producer_receipt_bytes`, `expected_producer_receipt_sha256`, `source_sections`
and `expected_source_sections`. Their shapes and semantics remain those of
`corpus_legacy_source_join`. Complete stored text is retained. Producer receipts
may be explicitly unavailable only when both receipt and expected hash are
`None`. The existing owner preserves missing receipts, missing sections,
unmatched text, integrity failures and ambiguous candidates; it never selects
the first or unique match. Integrity failures refuse the preparation.

Each physical-reference entry has exactly:

```json
{
  "physical_row_ordinal": 0,
  "request_ordinal": 0,
  "physical_identity": {
    "repository_id": "organization/cache",
    "revision": "<complete 40-character lowercase commit>",
    "path_in_repo": "paired_spans.parquet",
    "artifact_sha256": "<64-character lowercase SHA256>",
    "row_ordinal": 0
  }
}
```

`physical_row_ordinal` must retain contiguous complete list order; it is not a
Parquet selector. The nested `row_ordinal` is the declared physical table row.
`request_ordinal` identifies the bank's logical paired row. Every logical row
must have at least one physical reference. Multiple distinct physical rows may
map to one logical request, retaining all physical identities and multiplicity.
Identical raw paired bytes must appear only once in a bank's logical row list,
as required by the existing join owner. Do not remove their distinct physical
references. Duplicate physical identities within one bank are refused; the
same declared physical identity may recur as a separate reference across banks
only with the same exact paired-row byte hash. Conflicting byte commitments for
one declared physical identity are refused before project replay.

No file path is followed. Repository paths must be nonempty relative paths
without empty, dot, parent or backslash components. Revisions, hashes and all
counts retain explicit strict types; a Boolean is not accepted as an integer.
None of these syntax checks authenticates the coordinates.

## Independent request commitment

`request_raw` is canonical compact sorted-key Unicode UTF8 JSON, without a final
line feed. Duplicate keys, floats, invalid UTF8, nonfinite numbers and
noncanonical encodings are refused. The complete original input graph is
bounded before any receipt hashing or project replay.

```json
{
  "schema": "legal-source-correspondence-request/v1",
  "profile": "complete-declared-physical-source-review-requests/v1",
  "banks": [
    {
      "bank_id": "paired-v1",
      "original_bank_sha256": "<independently expected original-bank commitment>",
      "physical_rows": 8,
      "logical_rows": 8
    }
  ]
}
```

The bank commitment recipe retains the bank's exact five-key structure and
every original value, with only these byte values replaced by descriptors:

1. Replace `join_bytes` with `{"bytes": len(raw), "sha256": SHA256(raw)}`.
2. Replace every `paired_row_bytes` element with the same descriptor.
3. Replace `join_inputs.producer_receipt_bytes` with that descriptor, or retain
   explicit `null` when unavailable.
4. Hash compact sorted-key Unicode UTF8 JSON of the complete transformed bank,
   without a final LF.

In particular, the commitment binds the full text and expected source
population, the complete receipt bytes and expected receipt hash, every logical
row's exact bytes and order, and every supplied physical selector and mapping.
Caller-supplied expected pins are required. Computing a new pin from an
untrusted changed record does not authenticate its provenance or recover an
omitted physical reference outside the declared population.

## Output and regeneration

The report contains `banks`, each with the unchanged complete existing
source-review `preparation`. It also contains ordered `physical_rows` that bind
each declared physical identity to the exact paired-row SHA256, request/subject
references, preparation-manifest SHA256, original disposition and every
candidate occurrence ID. Bundle-local section indices remain bundle-local.

Coverage reports physical references, distinct declared physical identities,
logical requests, source-section references, distinct physical source sections,
candidate references and all disposition counts separately. Shared source
sections remain present in every original bank; distinct counts do not remove
their references. Candidate coverage counts physical-reference multiplicity,
so fanout may exceed the number of logical candidate records.

Each request retains nine active source/context questions and seven deferred
semantic/proof questions. All questions remain unanswered. Every authority flag
is false; every training/evaluation-gold mask is integer zero; inference views,
selected occurrences and governing sources remain null. This is preparation
for independently supplied review, not an application of source decisions or
governing-law adoption. Identity declarations and unique text matches do not
supply that authority.

The validator checks the supplied report's independent SHA256, regenerates
every original bank through the existing owner, and compares the entire
canonical report. Resealing a dropped row, changed selector, omitted
alternative, answered question, altered mask or authority flag cannot pass
original-bound regeneration. Original caller collections, detached replay
snapshots and limits are compared at closing boundaries. The first operational
failure remains primary if a closing custody check also fails. Returned report
collections are detached from original inputs.

## Finite resource profile

`limits` is `None` or a plain dictionary of lower-only overrides:

| Key | Hard maximum |
| --- | ---: |
| `max_banks` | 16 |
| `max_physical_rows` | 256 across all banks |
| `max_original_bytes` | 64 MiB |
| `max_report_bytes` | 32 MiB |
| `max_request_bytes` | 256 KiB |
| `max_json_nodes` | 1,000,000 visited nodes |
| `max_json_depth` | 48 |
| `max_string_bytes` | 512 KiB per UTF8 string, with character precheck before allocation |

Original budget accounting charges all immutable raw bodies, strings, JSON
punctuation and repeated references as supplied work. It does not deduplicate
receipt bodies across banks. Node/depth/cycle checks precede full serialization;
each scalar string is checked against remaining byte budget before encoding.
Aliases are visited again and charged; cycles are refused. The exact complete
output encoding must fit its limit, including framing and metadata. Aggregate
output is checked after each bank and again on the final report.

Existing delegate bounds remain unchanged: at most 64 logical rows and 64
sections per bank, 1 MiB aggregate paired-row bytes, 32 MiB per receipt, 512
candidate occurrences per join, and an 8 MiB complete review preparation. No
successful output is truncated to fit a limit. These byte/work bounds are not
a proof of peak process RSS. Original/source comparisons are cooperative Python
observations, not a sandbox or authenticated atomic multi-file snapshot.

## Next substantive boundary

Actual typed source responses, independent registry/policy and revocation
snapshots, explicit evaluation time, evidence bodies, source/adjudication
separation and complete history remain separate inputs to existing response,
adjudication, cohort, application, history and binding owners. The current
application effect copies answer references; the current binding assessment
authenticates candidate tuples with `decision_applied=false`. Governing-source
adoption needs a separately versioned authorized applied effect.

Only after that source boundary can one complete definition, a complete norm
and a genuine distinct second statutory use be accepted with exact meaning,
scope/time, exceptions, modalities, roles, cardinality and alternatives. Typed
graph and Lean preservation, eligible partitions/training, source equivalence,
whole-task satisfaction and convergence remain later gates.

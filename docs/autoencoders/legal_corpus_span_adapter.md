# Paired span custody adapter

`ipfs_datasets_py.logic.autoformal.corpus_span_adapter` preserves existing
`uscode-paired-span-census/v1` and `/v2` JSON rows as additive candidate records.
Within the bounded common-JSON profile, it retains exact input JSON bytes,
their externally expected SHA256, historical
identifiers, legacy status flags, unknown metadata, vectors and every formal
output from these separate routes:

- `autoencoder.formal_outputs`
- `compiler.formal_outputs`
- `compiler.canonical_formal_outputs`

Output order and duplicates survive through explicit route/ordinal identities.
Origin, independence, conditioning, syntax status and exact payload JSON remain
producer declarations. Compiler and autoencoder outputs are kept as distinct
candidate interpretation nodes; they are not combined into one asserted meaning.
Unsupported representations stay opaque. Missing or empty output collections
create explicit issues, preserving abstentions in the inventory.

## Input commitment and physical joins

```python
from ipfs_datasets_py.logic.autoformal.corpus_span_adapter import (
    adapt_paired_span_bytes,
    validate_span_candidate,
)

candidate = adapt_paired_span_bytes(
    paired_row_json_bytes,
    expected_row_sha256=independently_expected_row_sha256,
    source_binding=None,
)
validate_span_candidate(candidate, expected_row_sha256=independently_expected_row_sha256)
```

The digest commits to the complete supplied row serialization. It is distinct
from the retained historical `observation_id` and from a Parquet file digest.
For Parquet inputs, first use the existing paired-bundle owner to validate the
pinned bundle and row; declare a serialization and record its digest at that
intake boundary. This API does not download or authenticate a dataset revision.

With `source_binding=None`, the record retains a
`source_occurrence_unresolved` issue and creates no physical occurrence node.
Matching span text, `legal_id` or a revision alias does not establish a physical
source occurrence. For a checked caller-selected occurrence, supply a dictionary
with exactly these keys:

| Key | Value |
| --- | --- |
| `source_version` | Sealed source-version record from `corpus_source` |
| `source_occurrence` | Sealed occurrence with explicit character and UTF8 selectors |
| `context_declaration` | Sealed context declaration for that occurrence |
| `expected_raw_sha256` | Expected raw source artifact digest from source intake |
| `extracted_text` | Complete exact extracted view for geometry validation |
| `expected_extracted_sha256` | Expected digest of that extracted view |

The adapter checks source seals, expected hashes, extracted-view geometry,
exact span text and context custody. Both coordinate systems address the
extracted Unicode text, never raw HTML. Repeated identical text at distinct
locations produces distinct source-bound interpretations. Historical cache
IDs remain retained identifiers; the caller-selected join does not authenticate
their relationship to a statutory edition or provision.

The result retains the source-version, occurrence and context records, without
duplicating the complete extracted view. Validation of a bound candidate
requires the original six-key binding again so geometry can be recomputed.
Unavailable context remains an explicit issue. Declared external context
references also remain unverified issues.

## Output and limits

The sealed `legal-corpus-paired-span-candidate/v1` record contains `input_record`,
`source_binding`, `interpretations`, `issues` and a sealed candidate `graph`.
Source-bound graphs have source-version and occurrence nodes with complete local
endpoints. Every opaque interpretation and issue has a corresponding node;
source-bound records have evidence-bearing source edges. The record retains
the semantic content envelopes needed to resolve this graph's input,
interpretation and issue references.

Every output retains `admitted=false`, `formalized=false` and
`source_semantics_verified=false`, regardless of legacy input flags. Resealing
modified graph, provenance or authority fields does not pass validation: the
validator recomputes the entire candidate from the externally committed row
and supplied source binding.

The common 1 MiB envelope limit applies to the complete candidate, including
retained row JSON, output envelopes and graph. It may reject a row smaller than
1 MiB because the complete candidate adds content. Each route is bounded to128
formal outputs; all common JSON depth/node limits also apply. Overflow fails
without truncation, partial output or silent omission. Larger vector/payload
artifacts require a separately specified reference/partition profile.
The common JSON subset also requires nonblank object keys, valid UTF8 strings
without NUL, finite numbers and integers in `[-(2**63-1), 2**63-1]`.
The legacy census producer accepts a wider JSON range. Such out-of-profile
rows or nested formal payloads fail explicitly with `CorpusContractError`;
the adapter does not claim to accept every possible legacy producer payload.

`typed-deontic-rule/v1` in the current cache does not specify one uniform AST:
compiler rows may contain structured temporal objects, while other decoders use
different rule profiles. This adapter therefore emits no entity, term-sense,
definition or norm assertion by inference. Typed projection must identify and
validate an explicit semantic profile and retain source review, scope,
alternatives and unsupported structure before producing those assertions.

The companion [graph exchange](legal_corpus_graph_exchange.md) can export
`candidate["graph"]` to reconstructable Parquet. Preserve the complete candidate
record separately: the graph bundle contains graph envelopes and references,
and does not resolve the referenced payloads, source bytes or review evidence.
No training, graph merging, model invocation, Lean build or publication occurs.

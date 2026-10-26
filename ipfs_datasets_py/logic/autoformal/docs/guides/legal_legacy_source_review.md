# Review requests for legacy paired source candidates

`logic.autoformal.corpus_legacy_source_review` connects complete, independently
replayed legacy source joins to the existing review signature and dependency
owners. Use it for paired-cache observations whose original parent partition
and official-document alignment records are unavailable. The existing
`corpus_source_review` parent/official-document profile is unchanged.

The profile is `complete-legacy-stored-source-candidate-review/v1`. It accepts
the exact retained join bytes, their independently expected SHA256, the original
paired row bytes, and every original `build_legacy_source_join` input. It does
not accept an equivalent-looking substitute for an original alignment record.

```python
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as review

preparation = review.prepare_legacy_source_review_requests(
    join_bytes,
    paired_row_bytes,
    expected_join_sha256=independently_retained_join_sha256,
    expected_population=independently_retained_row_population,
    producer_receipt_bytes=original_producer_receipt_bytes,
    expected_producer_receipt_sha256=independently_retained_receipt_sha256,
    source_sections=complete_stored_source_sections,
    expected_source_sections=independently_retained_section_descriptors,
)
```

The returned collection has five components:

| Component | Contract |
| --- | --- |
| `manifest` | Complete ordered request/subject/dependency references, source-section commitments, counts and unresolved authority fields |
| `source_sections` | Every supplied complete stored text section, provenance and existing source-version record |
| `requests` | One request per original paired observation, containing its entire original join row and every overlapping candidate |
| `subjects` | Source-only signing subjects; graph/AST-shaped fields are documented compatibility aliases for request/question bytes |
| `dependency_manifests` | Existing dependency contracts binding requests, question lists, raw joins, paired rows, producer receipts, complete source sections and all occurrence/context records |

Each request reuses the existing nine source/context questions and seven
deferred semantic/proof questions, with their original wording. Answers,
reviewer declarations and occurrence selections remain null. A unique exact
substring match remains an unselected candidate. A present-day occurrence
proposal would be a different assertion from attesting what the historical
producer originally selected. Zero-hit and unavailable-source observations
remain in the population.

Coordinates describe the stored plain text using Unicode codepoint and UTF8
half-open offsets. They are not official HTML selectors. A complete stored
section does not establish its legal edition, source role or governing context.

## Replay and authentication

`validate_legacy_source_review_requests(preparation, join_bytes,
paired_row_bytes, expected_join_sha256=..., **original_join_inputs)` regenerates
the complete join and collection. Resealing a modified request, omitting a
candidate, dropping a source section, or changing a dependency does not bypass
this check.

`assess_legacy_source_review` selects one request by `request_ordinal`, checks
the independently expected preparation-manifest digest, and replays the whole
preparation before calling the existing `legal_graph_review` verifier. The
caller must supply the pinned trust registry, policy and complete review list,
explicit evaluation time, independently observed dependency hashes, and exact
evidence bytes. It supplies no default keys, signer, trust policy or clock.

The claim schema, action and audience are fixed new constants exported by this
module. Claims from the parent/official-source or semantic-graph domains cannot
be reused here. `validate_legacy_source_review_assessment` reproduces the
assessment from those original inputs.

Dependency observations must come from actual retained bytes or explicit
unavailability; copying expected manifest hashes is not an observation. The
original Parquet hash is a declared parent dependency: preparation replays the
supplied complete text sections but does not itself reread the Parquet file.
All seven dependency-pin categories are explicit empty lists in this profile.
Loaded producer-code identities therefore require a separately retained
execution manifest; this API does not claim producer-version invalidation.

Authentication establishes evidence custody under the supplied trust. It does
not interpret a response's legal content, establish human competence or
independence, select an occurrence, or qualify a training target. Even
authenticated supporting declarations keep semantic, source, training and
Lean authority flags false. The separate [typed response owner](legal_legacy_source_responses.md)
now validates exact answer/body bindings and preserves pending variants.
Typed response-content adjudication and source decisions remain unavailable
in this preparation/authentication profile.

## Bounds and selected qualification

The existing join limits remain unchanged: 64 paired rows, 64 sections,
128 KiB per section, 512 KiB total source text, 1 MiB paired input, 32 MiB
producer receipt, 256 occurrences per row and 512 total occurrences. Individual
sealed records retain the existing 1 MiB contract. The complete review
collection is additionally limited by the shared 8 MiB serialization and JSON
node/depth bounds; satisfying each upstream limit alone does not guarantee that
the derived collection fits. Exceeding a bound refuses the operation, without
truncation.

The official-source packet profile's six-parent cap is unchanged. This
separate profile does not call that packet generator or claim its prerequisites.
Process independently declared banks independently, retaining an aggregate
coverage report outside their source authorities.

The local qualification driver at
`artifacts/legal-paired-native-review-20261016-01/qualify.py` in the enclosing
workspace runs bounded offline tests and both retained public banks under the
existing resource scheduler. It records prelaunch source hashes, actual loaded
module origins, input checks, attempts and output hashes. Its unavailable-trust
assessments are diagnostics with no submitted reviews. See that artifact's
README for observed results and exact reproduction commands.

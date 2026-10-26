# Explicit V2 definition-use candidate assumptions

This owner also provides the separate candidate-only plaintext parent profile
described below. Official V2 entry points retain their HTML, integer-edition
and declared-applicability requirements.

## Plaintext parent candidate profile

`prepare_parent_definition_use_v1` accepts the same top-level arguments as
`prepare_definition_use_v2`; `validate_parent_definition_use_candidate_v1`
requires exact regeneration from the original inputs. The request uses
`schema=legal-corpus-parent-definition-use-request/v1` and
`profile=declared-plaintext-parent-unary-definition-use-alias-assumption/v1`.
The remaining request fields and complete body-role requirements are unchanged.

Each endpoint's evidence contains the arguments accepted by
`prepare_parent_definition_review_evidence_v1`, plus an independently expected
`expected_preparation_cid`: three original candidate/report/request byte
buffers, independent candidate pins, complete `parent_inputs`, all ordered
context inputs and expected context population, and optional lower-only
`parent_limits`. The existing review preparation replays the physical parent
records, exact root/source/companion identities and every declared occurrence.
It is evidence preparation; no signature or substantive legal review is implied.

Use the separate parent registry/lookup APIs in
[scoped_definition_resolution](scoped_definition_resolution.md). Each local and
donor partition must match its independently regenerated preparation CID,
source version, source ID, release, unchanged unknown edition, scope-record CID,
parent manifest, root occurrence, companion and source-binding hash. The lookup
table and selected symbol must also match the exact native donor head and its
physical source bindings. Declarations or resealed hashes cannot replace the
original replay. Official and parent schemas cannot be interchanged.

Different parent releases are retained, and two unknown editions are **not**
treated as one governing edition. A unique lexical result nominates an explicit
unreviewed alias assumption; it establishes neither governing scope nor legal
applicability. The output preserves both original ASTs, all contexts and repeated
roles, the alias AST, joint conjunction and a graph with real typed endpoints.
The same existing native-fragment encoder and graph/dependency owners perform
those operations; no Lean process, solver or model runs.

The result has a distinct parent candidate schema, and its interpretation,
binding and alias companions also have distinct schemas. All admission, review,
training, proof and Lean flags remain false, including
`governing_scope_verified`, `governing_edition_verified` and
`contributor_completeness_verified`. Original endpoint reviews do not authorize
the combined alias. Combined-use signing, normative use and parent-compatible
Lean corpus admission require subsequent explicit profiles; existing official
review/build entry points must reject this candidate.

The 48-MiB combined logical-input allowance, 256 occurrences, 1,536 context
obligations, 512 body roles and existing output bounds remain unchanged. Both
complete parent transports are charged even when they reference shared storage.
Preflight reuses the existing bounded parent serializer and independent byte
pins before physical replay, then rechecks those commitments after composition.
Physical files are replayed during each endpoint preparation. The final check
revalidates in-memory commitments; it does not claim an atomic external-file
snapshot across the entire call.
Unavailable, negative, ambiguous, mismatched, oversized or conflicting inputs
refuse; nothing is silently dropped to obtain a candidate.

The tests use authored plaintext, not reviewed statutes. Passing them establishes
the finite custody/composition contracts, not statutory autoformalization or
accuracy of any 8D/384D/768D/4096D model.

## Official V2 profile

`logic.autoformal.corpus_definition_use_v2` connects two unchanged V2 unary
definition candidates with an explicitly declared alias assumption. It reuses
the V2 compiler/context/review-evidence path, existing scoped resolver, native
fragment encoder, graph owners and dependency invalidation engine.

This initial profile accepts two distinct physical documents, one explicitly
supplied V2 candidate per endpoint, matching `fol` or
`tdfol` families, and exactly equal declared applicability. It does not choose
a statutory interpretation or turn a spelling match into legal identity.

## Preserved originals and a new assumption

Let the donor define `A(x)` and a second definition contain local body predicate
`B(x)`. Native symbols in V2 are qualified by declaration scope. Even identical
literal text therefore does not make `A` and `B` the same predicate.

The caller declares the assumption `∀x. B(x) ↔ A(x)`. The output retains both
original ASTs and emits this separate alias AST plus the joint conjunction:

```text
donor_definition ∧ (consumer_definition ∧ explicit_alias_assumption)
```

The native fragment owner checks exact AST/print/reparse correspondence and
produces conditional Lean text. The assumption is encoded, not proved. No
native Lean process runs. Original candidate records, interpretations, source
selectors, symbols and review subjects remain unchanged.

The candidate graph retains both original graphs and adds an alias expression,
its new interpretation and an explicit `USES_DEFINITION` edge between the
consumer and donor definition-assertion **graph-node CIDs**. Binding, lookup
and interpretation CIDs are edge evidence. Original issue records remain part
of the original candidate evidence. No norm, ground actor or new graph relation
is invented.

## Inputs and APIs

```python
prepare_definition_use_v2(
    request_raw,
    *,
    expected_request_sha256,
    donor_evidence_inputs,
    consumer_evidence_inputs,
    registry_raw,
    expected_registry_sha256,
    expected_registry_cid,
    lookup_raw,
    expected_lookup_sha256,
    expected_lookup_cid,
    query_raw,
    expected_query_sha256,
)

validate_definition_use_candidate_v2(record, request_raw, **validation_inputs)
```

Each evidence-input group has exactly five fields:

- `candidate_inputs`: the existing six original byte inputs accepted by V2
  review preparation;
- `expected_candidate_pin`: its existing twelve independent commitments;
- `context_inputs` and `expected_context_population`: complete ordered exact
  physical contexts for that candidate;
- `expected_preparation_cid`: the independently expected result of existing
  `prepare_definition_review_evidence_v2` replay.

The first four fields follow
[the V2 review-evidence API](corpus_definition_review_v2.md). Original raw JSON
file hashes remain distinct from full canonical report hashes. Caller-lowered
view, sampling and compiler limits replay through that existing owner.

The UTF8 request has these closed fields:

```text
schema = legal-corpus-v2-definition-use-request/v1
profile = declared-v2-unary-definition-use-alias-assumption/v1
interpretation_status = unreviewed_caller_declaration
use_id
consumer_symbol
donor_symbol
body_roles
donor_partition_id
local_partition_id
```

`donor_symbol` must be the donor's exact unary Entity AST head and term symbol.
`consumer_symbol` must be a body predicate of the unchanged consumer, never its
head. `body_roles` must equal **every** matching `definition_body/NNNN` role in
the original binding order. Equal literals within a V2 declaration share a
predicate, so selecting only one repeated role cannot bind that whole predicate.
Repeated physical occurrences and repeated AST positions remain explicit;
physical deduplication does not erase role multiplicity.

## Representative lookup and source bindings

Build the original registry and lookup with
[the existing scoped definition resolver](scoped_definition_resolution.md).
This adapter validates those complete bytes and independently expected CIDs;
it does not replace the resolver or supply a symbol table automatically.

The query route begins at `local_partition_id` and includes the explicit donor
partition. Every searched partition must satisfy the existing owner's identical
release/edition/applicability requirement. The local and donor metadata must
also match their respective exact candidate source-version CIDs, source IDs,
unchanged releases/editions and scope-record CIDs. Their shared applicability
CID is `cid_for_dag_json(candidate.scope_record.declared_applicability)`.

For this bounded profile, physical document IDs are the source-version
`source_id` values. Use the existing document scopes `document:<source_id>`;
these scopes do not establish title-wide legal applicability. The reference
must explicitly name the donor document and that donor document scope. A
general title scope, global-to-title equivalence, cross-document parent link or
rewritten source release is not supplied.

The uniquely selected symbol must equal the donor's native head. Its complete
table row must retain the exact donor head literal, `defined_term` kind,
document/scope, donor definition-record CID in `source_node_ids` and donor head
occurrence CIDs in `span_ids`. Additional complete table content remains a
dependency, including competing definitions and searched empty partitions.
Unavailable, unresolved and ambiguous outcomes cannot create a use component.

The query literal must exactly equal the consumer predicate's source literal.
Its interpretation CID is the unchanged consumer report-record CID. Its source
occurrence is the **first matching body role in existing binding order**; this
need not be the first physical offset when operand and source orders differ.

That one query is explicitly a representative lookup. The binding records
`lookup_coverage=representative_first_occurrence_whole_predicate_assumption`
and `per_occurrence_lookup_verified=false`, alongside all body-role bindings
and physical occurrence CIDs. It supplies no separate lookup or governing-use
qualification for the other offsets. A future profile must supply those
additional queries/reviews if it claims that coverage.

## Contexts, dependencies and bounds

Both existing V2 preparations replay all selected physical occurrences and
their complete six-slot contexts. The component unions exact physical
occurrences in donor-then-consumer order, refusing conflicting shared context
packets or dependency requests. Both original ordered role populations remain
bound by their original candidates/preparation CIDs.

The complete combined input budget is 48 MiB, including both groups' original
bytes, packets and requests plus the registry, lookup, query and alias request.
Each source HTML remains bounded to 8,000,000 bytes; each complete sampler body
to 32 MiB; each other original record/packet to one MiB. Combined contexts retain
at most 256 distinct occurrences and 1,536 obligations. Body-role lists retain
at most 512 entries. The complete output remains under the existing one-MiB
record, depth and node bounds. Inputs and outputs refuse as a whole when a bound
is exceeded; no source evidence, role, table or context is truncated.

The dependency manifest retains both complete preparation inventories, original
graph dependencies, every registry partition and the selected lookup's route
dependencies. It adds both preparation records, the explicit request, original
registry/lookup/query byte commitments, alias/interpretation/binding records,
joint native output and source-owner policy pins. The combined graph depends
on the complete inventory. Existing invalidation therefore reopens this
component when a complete searched table changes, including a new competing
definition or a filled empty partition. Complete supplied tables may contain
additional unreviewed declarations; this adapter checks the selected donor row
against its exact V2 candidate and does not qualify all other table entries.

Public import loads no resolver/native compiler/model. Raw byte bounds and
hashes are checked before lazy owner loading. Pure import-time owner pins and
the lazy cohort captured at first explicit use are checked during preparation;
the reused owners also check their own complete source/policy pins. These
checks do not authenticate a software distribution or continuously observe the
filesystem.

## Review and admission remain separate

The output is a new candidate interpretation with
`review_status=new_combined_use_review_profile_and_actual_reviews_pending`.
The original two definition reviews cannot approve the new alias assumption,
combined native AST or `USES_DEFINITION` edge. This module supplies no compatible
combined-use signing domain and accepts no review credentials. A future review
extension must bind that exact combined subject and complete dependencies.

All source-meaning/authenticity, applicability, context closure, independent
review, semantic binding, per-occurrence lookup, training/gold, Lean execution,
proof and admission flags remain false, including `accepted_view_eligible`.
Authored fixtures demonstrate engineering behavior only. Actual statutory
meanings, source adoption, real legal/formal reviews, native V2 build
qualification and a reviewed corpus/cache release remain pending.

Same-document multiple-definition partition scopes, several donor mappings,
cyclic definition components, arbitrary norm uses and per-occurrence governing
lookup are outside this first bounded profile.

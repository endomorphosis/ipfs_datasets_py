# Explicit source adjudication declarations

`logic/autoformal/corpus_source_adjudication.py` authenticates declarations about
the nine active source/context slots. It regenerates the complete typed-response
population, preserves every original group and disagreement, and checks a fixed
adjudication signing domain. It applies no source selection, changes no original
context and admits no semantic graph, training target or Lean statement.

## Reuse the existing subjects and signature verifier

The owner reuses `corpus_source_review` subjects, their original dependency
manifests and `legal_graph_review`'s fixed-domain signature engine. It adds a
distinct claim schema/action/audience:

```text
legal-corpus-source-adjudication-signed-claim/v1
record_source_context_adjudication_declaration/v1
legal-autoformalization-source-adjudication/v1
```

Both `legal_review` and `formal_review` roles sign one identical decision body.
The independently selected adjudication registry and policy use the existing
closed trust schemas, with this action/audience. They can differ from the source
review trust selection; there is no default registry, signer, key or clock.
The graph/AST-shaped subject fields remain the original source-request/question
compatibility aliases, not a semantic graph or native AST. A legacy source-review
signature, graph signature or section-local adjudication cannot supply this
new-domain authority.

Distinct authority principals/keys are required by the shared verifier. This
wrapper also excludes **all original reviewer principals, claimed DIDs and known
registered signing-key fingerprints in the complete supplied batch**, including
rejected original reviews and reviews of other requests. Relabeling an old
signing key under a new principal/DID does not create an independent actor.
Unknown original keys have no available fingerprint; their declared principal
and DID are still excluded. These are declared-identity and cryptographic-key
separation checks, not proof of human identity, competence or independence.

## Record one common declaration before signing

`record_source_adjudication_declaration(request, subject, typed_group,
pending_slots, answer_variants, decisions, *, expected_request_sha256,
expected_subject_sha256, expected_typed_group_sha256,
expected_preparation_manifest_sha256, expected_typed_response_manifest_sha256,
declared_at_utc, limits=None)` returns a sealed unauthenticated candidate.
Every SHA here is FULL canonical record/root SHA256, including its record CID.
Payload CID hashes and pretty/raw transport hashes are separate namespaces.
Authoring verifies the supplied identities and structure; original source and
signature qualification occur only in complete assessment.

Supply all nine pending records in original slot order and all their considered
answer variants in the original slot/variant order. Their complete CID/FULL hash
references are retained, even when the declaration selects one alternative.
The body pins the original request and subject, typed group, complete source
preparation and typed-response roots, declared time, pending slots and variants.
It has no signer-specific metadata or eventual signed-claim hash, avoiding a
hash cycle and allowing both roles to attest exactly the same decision bytes.

Every choice has exactly `slot_id`, `decision`, `selected_variant_ref`,
`rationale` and `evidence_refs`:

- `select_existing_variant` identifies a present authenticated typed variant
  whose disposition is `evidence_declared` or `not_applicable`, with nonblank
  rationale and exact supporting evidence references.
- `unresolved` has a null selected reference and nonblank rationale; evidence may
  be absent. It retains missing, ambiguous or rejected alternatives without
  replacing them with a resolved answer.

Selecting an unavailable/open variant, using another request's variant or
omitting/reordering the nine slots is refused. Freeform rationales and evidence
are declarations; this owner does not independently prove their legal truth.
`validate_source_adjudication_declaration(record, *inputs, **pins)` repeats the
same authoring checks and compares every field.

Serialize the sealed body to exact retained bytes. All nine ordered obligations
in **each** adjudicator claim reference exactly the same artifact ID/raw SHA256.
Selected evidence-declared answers map to `resolved_by_evidence`, selected
not-applicable answers to `not_applicable`, and unresolved choices to `open`.
The signed unresolved list preserves the exact ordered unresolved slot IDs.
`declared_complete` cannot mask any unresolved choice; a conservatively open
declaration is allowed. The body includes the supporting evidence references,
whose supplied raw bytes are checked separately; missing, changed or
self-referential evidence is rejected.

The common body time must not precede any original review for the **same
request**, must not exceed the explicit evaluation time, and must not be later
than any authority claim's issuance. Signature validity, age, revocation, scope
and intervals remain owned by the existing verifier. A declared timestamp does
not authenticate a legal event clock.

## Assess the complete original population

`assess_source_adjudications(preparation, source_registry, source_policy,
source_review_groups, typed_response_report, adjudication_registry,
adjudication_policy, adjudication_groups, *,
expected_typed_response_manifest_sha256,
expected_adjudication_registry_sha256, expected_adjudication_policy_sha256,
expected_adjudication_group_pins, typed_response_limits=None, limits=None,
**typed_response_inputs)` uses the original complete typed-response assessment
inputs. They include exact response-binding and source/trust/group pins,
evaluation time and source replay arguments. Optional `source_review_limits`
stays in those typed inputs; `typed_response_limits` lowers the typed profile;
`limits` lowers this adjudication profile. There are no callbacks or implicit
packet loaders.

Each complete ordered adjudication group has `request_cid`, `reviews`,
`declaration_artifact_id`, `evidence_artifacts`,
`observed_artifact_sha256s` and `observed_pins`. Groups with no reviews have a
null declaration ID. Nonempty review groups reference one common body. Their
independent pins use the existing source group-pin fields plus the exact
`declaration_artifact_id`; each evidence body has its own raw SHA256.
Missing groups or filtered review populations are refused.

The typed-response validator regenerates the whole original population once.
Every typed group and its raw source assessment/blockers remain byte-identical.
All original pending slots and alternatives remain available through the pinned
upstream typed-response root. This three-component output (`manifest`, `pages`,
`records`) embeds each complete typed group and the new raw authority assessment;
it does not duplicate every upstream variant/pending-record body.

The separate `authority_prerequisites_satisfied_under_selected_trust` requires a
valid common body, complete matching authority declarations, distinct/separated
actors, valid chronology and explicit external trust for both review stages.
Original source reviews must include distinct authenticated legal/formal roles.
This does not clear the original source-declaration hash disagreement, apply a
decision or qualify law. Original source decisions, required-unavailable contexts,
seven deferred semantic/proof questions and every graph/training/Lean admission
flag remain unchanged.

Counters named `declared_selected_slots` describe valid-content choices even if
their signatures or authority fail; they are never adopted selections. Invalid
bodies retain their exact artifact reference and rejected content status.
Authenticated authority claims and complete authority prerequisites are reported
separately. Actual source decisions applied remain zero.

## Bounds and qualification

The common record/page envelope is 1 MiB, with separate 64 MiB output and evidence
batch caps, 8 MiB per evidence group, at most 32 claims/256 evidence bodies per
group, 8,192 groups and 256 pages of at most 64 group references. Limits are
lower-only. Complete original-source and adjudication raw-body cardinality,
size and mixed JSON/raw budgets are preflighted before their first body hash.
Inherited group detachment repeats its own exact custody checks. This is bounded custody, not an absolute
process-memory or installed cryptographic distribution guarantee.

`validate_source_adjudications(report, *inputs, **pins)` bounds the offered output
before repeating complete source/typed/adjudication assessment once and comparing
every component and producer pin. Repaired seals, hidden disagreements or edited
authority flags cannot replace regeneration. A complete population is retained
or refused; a prefix never becomes qualified.

This owner supplies a testable authority-declaration interface. Real trust,
reviewer/adjudicator identities, source/context decisions and their application
still need independently selected production evidence and a separate versioned
application profile. Signature verification alone supplies no reviewed meaning.

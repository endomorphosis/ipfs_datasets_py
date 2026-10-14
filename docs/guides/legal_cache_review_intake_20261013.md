# Legal cache intake and review evidence

This continuation connects raw cache records to the proposed graph contracts.
It preserves unresolved material and authenticates review evidence without
granting legal meaning, training eligibility, global consistency or Lean authority.
The original convergence tasks remain partially implemented.

## Direct SpanCache records

`legal_span_cache_intake.prepare_span_cache_intake` consumes a bounded list of
actual `SPAN_EXPORT_COLUMNS` or legacy rows. It reads `rule_json` directly;
callers do not manufacture an AST first. The existing canonical IR validator
checks supported rules while original rule/qualifier order and repetitions remain
unchanged. Malformed JSON, duplicate keys, unsupported fields, conflicting rule
channels, pending/gap/unsealed statuses and missing source context remain explicit
unresolved dispositions. Unknown raw fields and repeated presentations are retained.

Custody inputs are independent ordered `expected_row_sha256s` and
`expected_record_sha256s`, exact `cache_identity` with repository/revision/artifact
SHA256, starting physical ordinal, and a separately pinned source-binding map.
Derive and retain those pins from verified cache bytes before consuming proposals;
recomputing pins from an incoming untrusted proposal does not authenticate it.

`make_source_binding` builds the explicit map value from the original extracted
document and raw HTML, document revision, scope and candidate selectors. Every
candidate is checked against the same complete source text. Multiple physical
matches stay ambiguous; no first match, whitespace normalization, label alias,
cropping or absent-status-to-sealed fallback selects a meaning.

Official HTML is decoded strictly using a compatible BOM and actual declared
meta/XML charset, or UTF8 when neither is present. Conflicting declarations,
invalid bytes, unsupported/non-text codecs and `unicode_escape` /
`raw_unicode_escape` transformations are rejected instead of guessing or replacing
source characters. SHA256 still addresses the original raw HTML; character and
UTF8-byte selectors address the normalized Unicode view. Decoding preserves these
source identities, without granting semantic review or training qualification.

`prepare_entity_cache_graphs` delegates to the existing prepared EntityCache only
when the whole population has exact supported proposals in one section/scope.
Any unresolved or repeated physical binding retains the complete intake instead
of filtering the population. The old queue and resume formats are unchanged.

Paired-v1/v2 records retain their nested source, autoencoder/compiler outputs,
vectors and provenance as observations. They are a distinct transport from flat
canonical rules. A `complete` flag, guided frame, mock identity, target-conditioned
output or legacy admission flag cannot generate a graph assertion here.

The qualified real sample is all eight rows of one immutable, explicitly
nonrepresentative `legacy-cuda-census` paired-v1 file. Its complete file SHA256 is
verified. All eight rows remain unresolved; this is not a corpus accuracy sample.

## Materialized entity index

See [entity-index intake](legal_entity_index_intake_20261013.md) for the streaming
reader, immutable-file custody, complete census and independent replay APIs.
The local EntityCache queue and the Hub materialized index remain distinct schemas.
The full pinned index contains 1,960,876 rows; all 1,722,395 edge observations have
unresolved endpoints, and 119,134 nodes lack IDs. Retained physical row identity
does not restore a missing entity identity or legal relationship.

The remedy requires pinned primary graph records with verified original IDs and
an explicit generation/shard manifest. Labels and matching cardinalities cannot
substitute for that provenance. The intake preserves the entire source and every
disposition while exposing these repair obligations.

## Authenticated graph review evidence

`legal_graph_review.build_review_subject` replays the exact proposed graph source
against raw HTML and its v2 context packet. Independently supplied graph/context/
manifest pins and the complete required forward-dependency population bind the
subject. Explicit graph and assertion dependency references must be reachable
with matching hashes. The subject covers graph/AST, occurrence, document revision,
scope, all context slots and declared dependency artifacts.

`assess_graph_reviews` uses existing Profile G detached Ed25519 verification. Its
independent inputs include the exact subject, complete signed-review population,
registry and policy hashes, evaluation UTC, current artifact/pin observations and
exact evidence bytes. The registry grants explicit `legal_review`/`formal_review`
roles and scopes to configured keys/principals. Policy, registry, key and review
validity windows, revocations, distinct principals/keys, declared interpretation
agreement, context evidence and dependency currency are all checked.

Trust modes are `external_pinned_trust`, `synthetic_fixture`, or `unavailable`.
The caller supplies the trusted registry, policy, clock and their independent
pins; this API does not authenticate that trust-root selection, a person's real
identity, professional credentials or human independence. Synthetic test keys
are never production trust. No production reviewer keys were created here.

An `authenticated` assessment means the exact declared evidence verifies under
that configured trust. `review_prerequisites_satisfied_under_selected_trust` is
separate from `accepted_view_eligible`, which remains false. Signed statements
do not establish legal truth or exhaustive governing context. Downstream semantic
validation and Lean admission remain explicit blockers. Existing proposals retain
their false authority flags.

`validate_review_assessment` regenerates the complete assessment from independent
inputs. Resealing a modified report or presenting a successful signature boolean
cannot override this replay. Registry/revocation updates, time, context bytes or
dependency changes require a new assessment.

## Qualification

The native supervisor qualifies three independent streams: materialized-index
observations, authenticated-review custody, and direct span-cache intake.
Immutable real-input baselines are pinned before dispatch. Native execution and
post-merge independent replay both recompute the full index census and bounded
paired sample. Idempotent receipt checks bind the pinned results without claiming
another row scan. No model inference/training, corpus publication or Lean
compilation occurs in this phase.

# Authenticate pending norm-content decisions

`legal_norm_content_adjudication_v1` prepares and authenticates a separate common
adjudication declaration over a complete, replayed
[typed norm-content assessment](legal_norm_content_responses_v1.md). It preserves
all supplied answers, competing variants and dissent. Its current profile records
choices without applying them or accepting a statutory interpretation.

## Inputs and signing boundary

The template and declaration builders receive the exact typed assessment,
subject, source registry, source policy, complete source review population and
dependency manifest. Supply an independent complete typed-assessment digest and
`response_inputs` containing the complete original response-assessment keyword
arguments, including response bindings, their independent pin, the original
clock, dependency observations and exact evidence bytes. The original report is
fully regenerated before its answers become available for selection.

The common body commits the complete original assessment, subject, ordered
obligations, pending questions, answer variants and candidate proposals. Each
ordered decision selects one existing authenticated, non-unresolved variant for
that exact slot or explicitly remains unresolved. The template leaves decisions
and declaration time null. It is an unsubmitted handoff, not a declaration of
unresolved findings. Missing, repeated, reordered or foreign choices are refused.
Each decision requires a rationale; selected choices also require nonempty exact
supporting evidence references.
Definition applicability must remain unresolved, with null governing-definition
use, under this profile.

The assessor takes independently pinned adjudication registry, policy and complete
review population, an explicit evaluation clock, current dependency observations
and exact evidence bytes. When a common body is supplied, independently pinned
raw and canonical hashes identify its exact UTF8 transport and complete JSON
value. Strict duplicate-free JSON and the existing byte/depth/population bounds
apply. A missing body has no pins and no adjudication claims. Signed unresolved
lists retain the shared limit of 32 entries, although the norm obligation
population permits up to 512. Oversized declarations are refused without
truncating the population.

Adjudicators sign under a distinct fixed schema/action/audience through the
existing Profile G Ed25519 verifier. Every signed slot must reference exactly
the same whole common body and preserve its complete dispositions, unresolved
inventory and status. Original norm-review signatures cannot authorize this new
action. Supporting choice evidence cannot be any source response body or the
common declaration itself, including an alias with the same raw bytes. Hashing a
supplied attachment does not establish its truth or the adequacy of its support.

## Old reports and current prerequisites

The original typed assessment retains its original identity and clock. The
assessor also regenerates source authentication and typed content at the supplied
adjudication time using the same independently pinned source trust snapshots and
current dependency observations. Expiry and already-declared revocations can
therefore block current prerequisites. This does not discover newer registry
snapshots, unseen revocations or a trusted real-world clock. Supplying a new
registry cannot silently replace the snapshot bound by old signatures.

Every supplied source claim contributes to the exclusion inventory, including
rejected claims and outliers. Both claimed and registered principal/DID values
and known registered public keys are excluded from the adjudicator population.
An unknown source key leaves that inventory incomplete and blocks prerequisites.
Legal and formal roles require distinct declared principals, key IDs, DIDs and
public keys. These checks cover one complete supplied subject population; they
do not establish human independence or cross-hypothesis/cross-candidate coverage.

Source dissent remains evidence. Currently authenticated, valid typed legal and
formal source responses may disagree; an adjudication declaration does not need
to erase that disagreement. Declaration time cannot precede the original
assessment or source claims, or follow the supplied evaluation or authorizing
adjudication claims.

## Read the results separately

Common-body validity, signature authentication, current source prerequisites and
partial adjudication prerequisites are separate results. The complete shared
review assessment and all its blockers remain visible. Because definition
applicability stays open, complete-context review prerequisites remain false even
when a pair authenticates a valid partial declaration under selected trust.

Every choice remains unapplied. Selected interpretations and governing-definition
use remain null; norm readiness, accepted-view eligibility, semantic authority and
consumer/training/evaluation-gold masks remain false or zero. Governing
applicability, supported definition substitution, complete meaning-unit geometry,
a second actual use and relational graph/Lean admission require further work.

The [declaration generation binding](legal_norm_content_declaration_binding_v1.md)
remains a separate custody contract. Explicit response-body attachments can carry
its exact bytes and the retained unsigned declaration. This adjudication profile
does not authenticate that declaration's author, recursively verify nested
attachments or give unsigned proposals decision semantics.

Public validation requires an independent complete-report pin and full
regeneration from original inputs. Source, input and serialization freshness
checks preserve producer identities. The ordinary norm snapshot keeps its
1.5-million-node and 128-MiB input bounds; complete reports and compact
adjudication trust/evidence retain their eight-MiB bounds. Full statutory
typed-review populations and their performance require separate qualification.
Qualification evidence and the exact test
scope are recorded in the enclosing workspace's
[qualification record](../../../../../../../artifacts/legal-norm-content-adjudication-20261016-01/README.md).

All 63 focused cases passed using fictional signed source/adjudicator fixtures.
The first attempt retained one test-message assertion failure; the corrected
complete cohort passed without product-code changes. No actual statutory
adjudication was prepared because actual typed reviews, selected trust and an
evaluation clock were not supplied. Existing real A/B response packets remain
unsubmitted; definition applicability and all decisions remain pending.


## Complete reviewed admission V2

The additive `prepare_reviewed_norm_admission_v2`,
`assess_reviewed_norm_admission_v2` and
`validate_reviewed_norm_admission_v2` APIs implement the distinct
`complete-reviewed-norm-admission/v2` profile. V1 remains an unapplied proposal
profile; its signatures and saved flags cannot authorize V2.

V2 currently supports one connected component containing a governing predicate
definition and at least two distinct normative uses in the existing strict
relational/deontic typed profile. Preparation replays original raw source bytes,
extracted text, sealed versions and occurrences, exact character/UTF8 geometry,
and complete relational requests/reports. All typed mapping paths and the whole
selected source occurrence require correspondence coverage. Duplicate retained
artifact/view intervals, relabeled copies and overlapping normative
interpretations cannot supply two uses.

The declaration explicitly binds governing edition, jurisdiction, instrument,
legal-as-of and applicability interval, selected interpretation, ordered predicate
roles, governing definitions at every typed use, versioned cross-references,
permitted uses and source/IR producer actors. Definition targets must name the
matching predicate, arity and ordered roles; competing governing definitions
remain unsupported. Nonempty formal assumptions, unresolved meaning and
unsupported constructors refuse this initial profile. Counting, temporal and
other richer typed-premise profiles require their existing owners' separate
integration rather than projection into the supported fragment.

The assessor regenerates the entire preparation and uses the shared detached
Ed25519 review verifier with a fixed new subject/claim/action/audience. Independent
legal and formal roles must support the same complete body and every review
obligation, with separate process evidence. Source/IR producer principals, DIDs
and public keys are excluded. Source records, source bytes, IR requests/reports
and the declaration cannot masquerade as independent process witnesses.
Signatures authenticate declared review evidence; they do not prove human
competence or the truth of an attachment.

Every admission replay checks supplied current trust intervals, revocations and
complete dependency observations through the existing invalidation owner. The
caller remains responsible for independent trust selection and current external
observations; this API does not discover unseen revocations or authenticate a
real-world clock. All dependency, interpretation and producer identities are
committed by the signed subject. A saved assessment requires exact original-input
regeneration before reuse.

`semantic_use_eligible` is eligibility under those supplied review and dependency
conditions. `formalization`, `training`, `hparam_selection`,
`heldout_evaluation` and `proof_obligation` are separate permitted uses. Fictional
fixtures retain explicit provenance and zero statutory training/evaluation-gold
masks, even when authored trust wire fixtures use `external_pinned_trust`.
Preparation, semantic eligibility, graph admission, kernel checking and corpus
admission remain separate: this profile grants no proof, graph or Lean-corpus
acceptance. Real Title 10 review decisions remain pending.

The complete consumer target retains the typed expression, ordered roles, empty
assumption inventory, interpretation, governing context, source identity and
definition/cross-reference metadata. Its reviewed callback integration lives in
the existing [consumer binding owner](legal_source_span_consumer_binding.md).
The maintained handoff records qualification outcomes and remaining gates.

The [V03 focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-phase2-reviewed-admission-20261108-v03/independent-actual-acceptance-v01.json) passed all 242 owning fixture cases (112 admission, 130 consumer), with original source/process/Native/storage closure. The failed V02 fixture generation and original explicit recovery remain preserved separately. This is no statutory or numerical-quality result.

# Unsigned stored-source adoption authoring

`legal_stored_source_adoption_requests_v1` prepares a complete physical-reference
population for future source-adoption review, then records an explicitly
supplied source choice as an unsigned declaration. It is an authoring
prerequisite. It implements no signing, signature assessment, source application
or accepted-meaning engine.

The existing correspondence validator regenerates every original bank from the
same pinned join, paired bytes, producer receipt and complete stored sections.
The resulting source packet remains embedded unchanged. All alternatives,
original contexts and unresolved outcomes survive. Physical cache coordinates
retain their earlier status as independently pinned supplied declarations;
this increment performs no fresh cache-Parquet verification or source scan.

## Public API

```python
prepare_stored_source_adoption_requests_v1(
    packet, request_raw, *, expected_packet_sha256,
    expected_request_sha256, original_banks, limits=None,
)

stored_source_adoption_requests_sha256(report, *, limits=None)

validate_stored_source_adoption_requests_v1(
    report, packet, request_raw, *, expected_report_sha256,
    expected_packet_sha256, expected_request_sha256,
    original_banks, limits=None,
)

record_stored_source_adoption_declaration_v1(
    preparation, choice, *, physical_reference, source_use,
    declared_at_utc, rationale, evidence_refs, packet, request_raw,
    expected_preparation_sha256, expected_packet_sha256,
    expected_request_sha256, original_banks, limits=None,
)

validate_stored_source_adoption_declaration_v1(
    declaration, preparation, choice, *, expected_declaration_sha256,
    physical_reference, source_use, declared_at_utc, rationale,
    evidence_refs, packet, request_raw, expected_preparation_sha256,
    expected_packet_sha256, expected_request_sha256,
    original_banks, limits=None,
)
```

`request_raw` and `original_banks` retain exactly the earlier correspondence API
contract. No new input request wire format is introduced. Expected hashes are
full canonical compact sorted-key Unicode UTF8 JSON without LF; the original
request hash binds its exact immutable bytes. An artifact file with a trailing
LF has a different physical file hash. Do not substitute one hash recipe for
the other.

The identity helper bounds and hashes JSON content only. Public validators
regenerate the entire preparation or unsigned declaration from originals.
Resealing an offered result does not validate it. Wrapper failures raise
`StoredSourceAdoptionRequestsError`, a `ValueError` subclass. Existing delegated
source-contract failures can retain their existing `ValueError` subclasses.

## Prepared physical requests

The preparation contains the unchanged `source_packet` plus one ordered `rows`
entry per original physical reference. It preserves fanout: equal logical bytes
or candidate references never collapse distinct physical rows. Each entry has
its exact physical reference, original request and source-subject references,
source-preparation manifest hash, every `candidate_choices` entry, a new sealed
physical-specific subject, a blank `declaration_template`, explicit pending
obligations and false authority fields.

Coverage separates physical rows, logical requests, distinct source sections and
candidate references. Every row remains pending; submitted declarations and
applied source decisions remain zero. The prepared template has `choice`,
`source_use`, `declared_at_utc` and `rationale` set to `None`, with empty evidence
references. The owner does not choose the first or unique candidate.

Each new subject binds the packet/request hashes, full physical reference,
original request/subject and source-preparation references, the hash of all
ordered candidate choices, nine active and seven deferred slot identities, and
pending obligations. Subjects are reserved authoring structures. A generic
prepared subject cannot authorize a choice or source use supplied later.

The reserved future domain is:

| Field | Value |
| --- | --- |
| Signing profile | `reviewed-stored-source-adoption/v1` |
| Subject | `legal-stored-source-adoption-subject/v1` |
| Claim | `legal-stored-source-adoption-signed-claim/v1` |
| Action | `apply_reviewed_stored_source_adoption/v1` |
| Audience | `legal-autoformalization-stored-source-adoption/v1` |
| Effect | `adopt_exact_stored_occurrence_for_explicit_scope_role_and_legal_as_of_only/v1` |

Future authorization must bind the exact sealed declaration body, including its
choice, source use, physical identity, evidence and dependencies. This module
accepts no completed legacy or new signing claim, key registry, trust policy,
signature or evidence body. Domain metadata does not constitute authentication.

## Explicit unsigned choices

`physical_reference` has exactly these keys:

```text
bank_id
physical_row_ordinal
physical_identity
paired_row_sha256
```

It must equal one complete prepared row reference. The nested physical identity
keeps the earlier repository/revision/path/artifact-SHA/table-row shape.
`physical_row_ordinal` is the contiguous bank-local reference ordinal; it must
not be confused with the nested Parquet row ordinal.

`choice` has exactly:

```text
source_section_index
source_section_sha256
source_version_ref
source_occurrence_ref
context_ref
```

Every reference has exactly `record_cid` and full canonical `sha256`. The entire
choice must be one exact original candidate in the selected physical row's
logical request. Section index, version, occurrence and context cannot be mixed
between candidates or banks. All alternatives remain bound by the preparation
and its `considered_candidate_choices_sha256`; recording intent removes none.

`source_use` has exactly:

| Key | Allowed value |
| --- | --- |
| `purpose` | `retained_source_analysis` or `governing_normative_source` |
| `declared_region_role` | `operative_body`, `editorial_note`, `source_credit` or `unknown` |
| `scope_id` | Bounded nonempty string or explicit `None` |
| `jurisdiction_id` | Bounded nonempty string or explicit `None` |
| `instrument_id` | Bounded nonempty string or explicit `None` |
| `legal_as_of_civil_date` | Canonical valid `YYYY-MM-DD` civil date or explicit `None` |
| `edition` | Bounded offered declaration or explicit `None` |
| `view_profile` | The exact original extraction profile or explicit `None` |

Unknown coordinates remain unknown and produce additional pending obligations.
Governing-purpose intent with an unknown date or edition can be recorded, but
cannot apply a governing source. An offered edition never overwrites the
original source version's undeclared edition. Acquisition time, Hub revision,
producer revision and legal-as-of are distinct coordinates.

`declared_at_utc` is a valid canonical `YYYY-MM-DDTHH:MM:SSZ` timestamp. Calendar
validation authenticates no clock or chronology. `rationale` is nonempty and at
most 8,192 UTF8 bytes. `evidence_refs` is a nonempty list of at most eight
distinct `{artifact_id, sha256}` references. IDs use the existing lowercase
review-ID vocabulary. These are declared unresolved references: no evidence
body is supplied or checked, and no supporting fact becomes verified.

The returned sealed declaration has `intent="deliberate_adoption"`, the exact
choice and source use, its new subject reference, preparation/packet/request
hashes, complete original context, evidence references and pending obligations.
Its `signature` is `None`, `decision_applied` is false, masks are integer zero,
inference view is null and all authority flags are false. It records present-day
intent; it does not attest the historical producer's intended occurrence.

## Preserved substantive gates

The original candidate context retains `availability="required_unavailable"`
and `dependency_verification="declaration_only"` byte-for-byte. A declaration or
future signature cannot promote it to `none_required`, authenticated closure or
accepted meaning. A separately validated exact-stored-text companion needs
actual evidence for referenced definitions, lead-ins, exceptions, antecedents,
qualifiers, references and temporal/applicability requirements. The HTML-only
binding profile cannot be applied to retained plain text by changing a label.

Pending obligations explicitly retain missing actual nine-question answers,
typed reviews, adjudication, cohort actor exclusions, current history/binding
replay, new effect-specific authorization and context/edition/applicability
review. The seven semantic/proof questions remain deferred. No source decision,
governing meaning, graph assertion, training/gold eligibility, global holdout,
source equivalence, Lean admission or convergence follows.

Existing source response/adjudication/cohort/application/history/binding owners
remain the later composition. Answer-copy authority does not authorize this new
effect, and structured candidate binding keeps `decision_applied=false`.
Actual future authority must check subject/body binding, independent legal/formal
roles, all-epoch actor exclusions, key/registry/policy validity and revocations,
declaration/claim/evaluation chronology, conflicts, supersessions and forks.

There is also a measured-input arithmetic limit. The actual two producer
receipts are 24,509,016 and 20,282,871 bytes. Existing owners charge repeated
references as replay work. Eight requests per bank account for **358,335,096
receipt bytes per epoch**. Genesis plus the required fresh revision accounts
for **716,670,192 bytes**, exceeding the existing **536,870,912-byte (512 MiB)**
history input limit before other metadata. This owner performs no such history
replay. Future integration needs a separately reviewed bounded composition; do
not silently raise the old cap, omit rows, discard exclusions or invent an
eligible genesis head.

## Bounds and cooperative custody

The same eight lower-only limits as the correspondence owner apply: at most 16
banks, 256 physical references, 64 MiB aggregate original inputs, 32 MiB complete
output, 256 KiB original request bytes, 1,000,000 visited nodes, depth 48 and
512 KiB per UTF8 string. Existing per-bank join/receipt/review bounds remain
unchanged. Sealed declaration bodies additionally retain the existing 1 MiB
record cap.

One shared root graph counts the source packet, original request and bank
bodies, and all offered preparations/declarations/choice inputs before hashing,
full serialization or original replay. Repeated aliases count repeatedly;
cycles, malformed types, Boolean/integer substitutions and raised/unknown
limits are refused. The earlier bounded helper machinery is reused. Scalar
character checks precede UTF8 allocation, escaped bytes count against aggregate
bounds, and successful output is never truncated.

Authoring and both validators compare original caller inputs, detached snapshots
and limits at closing boundaries, including offered result objects. Mutation
during genuine replay is refused. The first operational failure remains primary
if a closing check also fails. These are cooperative Python observations, not
a process RSS proof, OS sandbox or arbitrary-monkeypatch attestation.

A finite reviewed definition/complete-norm/genuine-second-use pilot can proceed
before complete global 60,077-row identity grouping. Its selected physical
denominator and permissions must stay explicit. Corpus-wide dependency closure,
exposure-aware splits and semantic training eligibility remain separate gates.

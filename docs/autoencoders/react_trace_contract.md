# React trace data contract

Status: proposed `ui-react-trace/v1` contract, 2026-09-30. This is the normative
design for work package R01, not a runtime decoder already installed. R01 must
implement closed JSON schemas and shared Python/TypeScript golden vectors before
R02 emits this format. Architecture is in the
[main specification](react_capture_spec.md); work and acceptance IDs are in the
[implementation plan](react_capture_implementation.md).

## Artifact layers

| Artifact | Purpose and identity |
| --- | --- |
| Source manifest | Pinned original and instrumented app revisions, patch/build/lockfile hashes, component definitions, handler definitions, state schemas and authored interface bindings |
| Session manifest | Capture ID, source manifest, recorder/driver/browser versions, fixture seed, environment, privacy policy, declared coverage and scenario provenance |
| Trace shard | Immutable ordered records plus schema fingerprint, producer identity, row count, stream sequence intervals and exact file digest |
| Episode manifest | References to all shards/blobs/streams, completion policy, final outcome, missing intervals and final per-stream sequence watermark |
| Dataset snapshot | Exact admitted episode/shard closure, importer/adapter/profile, exclusion clusters and immutable split assignment |
| Target bundle | Exact source/window/producer/profile identity, normalized feature expressions, source evidence map and qualification observations |
| Evaluation package | Frozen evaluator definitions, expected outputs, observed results and replay receipts; never part of model-visible input closure |

An `ArtifactRef` is a closed object containing `sha256` (64 lowercase hex),
`bytes` (nonnegative safe integer), `media_type` and `schema_version` (bounded
strings). It contains no arbitrary filesystem path or URL. The owner resolves
it through an approved artifact store. A URI in a release manifest is only a
transport location; bytes and digest still determine identity.

File digests cover exact stored bytes. The new cross-language **record** digest
uses RFC 8785 canonical JSON, with finite IEEE-754 numbers, integers in the exact
JavaScript range, valid Unicode scalar strings, no duplicate keys and no Unicode
normalization. Negative zero canonicalizes according to that profile. Test
escaping, Unicode, exponent notation and key order in both languages before
using digests as identity. This new profile does not replace existing MCP-IDL
CID normalization or native Python target digests. Each hash retains its codec
identifier. [Canonical JSON definition](https://www.rfc-editor.org/rfc/rfc8785)

## Session and source identity

The session manifest must contain these groups. All nested fields are closed
in the executable R01 schema; extension fields require a schema revision.

| Group | Required fields and meaning |
| --- | --- |
| Identity | Schema `ui-react-session/v1`, session ID, capture producer ID, source-manifest reference, original corpus/revision/record identity where imported |
| Application | Repository identity, immutable source revision and content digest, instrumented patch/build digest, lockfile digest, framework/runtime versions |
| Scenario | Authored task/story ID, template/lineage ID, initial-fixture digest, seed, observation and completion policy IDs; source dataset split preserved separately |
| Environment | Browser/version, OS/runtime profile, viewport, device pixel ratio, locale/timezone, development/production and StrictMode settings |
| Coverage | Separate DOM, handler, state-owner, typed-call and backend-receipt coverage: `complete_for_declared_scope`, `partial`, or `unavailable`; declared scope IDs and exclusions required |
| Provenance | Driver/human/agent/system session classification, capture origin, source terms reference, consent/redaction policy digests; no credentials or consent tokens |
| Capture bounds | Exact configured byte/event/depth/time limits, overflow policy and recorder build identity |

Every source component definition identifies an authored ID, source artifact
digest, module/export and binding-manifest revision. A handler definition adds
its authored handler ID and event prop, such as `onChange`. Do not use minified
function names, DOM text or CSS selectors as the only source identity.
Mounted instances add an instance ID and lifetime; remounts get new instance
IDs. Definition identity remains stable within the pinned source manifest.
Registration lifetimes are separate: StrictMode cleanup/setup can unregister
and register the same retained instance under a new registration ID. This alone
does not establish a true remount. A new mounted component ref owns a new
instance ID; imported traces lacking this evidence leave instances unavailable.

IDL bindings add descriptor CID/preimage, exact method and schema identities,
argument mapping, declared risk/confirmation/idempotency, allowed backend and
result-to-state mapping revision. Existing IDL verification remains mandatory.
A component with only local state declares no IDL binding; that is a supported
observation profile, not a reason to invent a service.

## Common record envelope

All fields in this table are required; nullable fields must be explicit `null`.
Unknown envelope fields fail decoding. `Id` is a nonempty, bounded opaque ASCII
identifier matching `[A-Za-z0-9][A-Za-z0-9._:-]{0,95}`; it must not contain raw
user identifiers. A derived record ID contains the two literal `/` separators;
individual IDs cannot contain `/`.
`UInt` is an integer from zero through `2**53-1`, excluding booleans.
`RecordId` is the derived session/stream/sequence string, not an `Id`.

| Field | Type and rule |
| --- | --- |
| `schema_version` | Literal `ui-react-trace/v1` |
| `record_id` | Exact `session_id/stream_id/sequence` string; stable on retransmission |
| `session_id`, `episode_id`, `stream_id` | `Id`; stream IDs are unique within the session and never reused after producer restart |
| `document_epoch` | `Id` or null for nonbrowser producers; changes on navigation/new document, not every React render |
| `sequence` | `UInt`, strictly increasing in each stream, allocated before enqueue; overflow ends the stream |
| `monotonic_us` | Decimal integer string or null for imported records without a local monotonic clock; never compare separate clock domains as one clock |
| `wall_time_utc` | UTC RFC 3339 string or null; diagnostic only |
| `manifest_sha256` | Session-manifest digest; resolves source identity and coverage |
| `kind` | One discriminator from the closed record-kind table below |
| `evidence_class` | `observation`, `declaration`, or `assertion`; restricted by kind |
| `actor_kind` | `human`, `automation`, `agent`, `system`, `unknown`; supplied by the capture context, never inferred from `isTrusted` |
| `capture_origin` | `instrumented_runtime`, `imported_trace`, or `authored_fixture` |
| `links` | At most 32 typed record or declaration links as defined below; unresolved references tracked explicitly until episode finalization |
| `payload` | Closed object selected by `kind`; at most the configured record-byte limit |

Collector metadata is stored outside the producer envelope: receipt ID/time,
authenticated producer/session identity, exact record digest, ingest status and
rejection/conflict reason. A browser cannot self-assert collector verification.
Raw import bytes and the normalized record both retain separate hashes.

IDs and sequence watermarks allocate within the trusted collector session;
retransmission reuses the exact record. A new recorder instance after a crash
opens a new stream instead of guessing the last counter. Logical identity is
`(session_id, stream_id, sequence)`; different bytes at that identity are a
conflict, never a last-writer-wins update.

## Payload kinds

The following are the complete v1 variants. All listed payload fields are
required, with `?` meaning an explicit nullable value. Referenced declarations,
state schemas and artifacts must resolve within the episode/source closure.
Local entity names ending in `_id` use `Id`; references explicitly described as
record references use `RecordId`. Sequence/version fields use `UInt`, and SHA
fields use lowercase SHA-256. Outcome/action enum domains follow the table.

| Kind and evidence class | Payload fields | Semantics |
| --- | --- | --- |
| `component.registered` observation | `component_definition_id`, `component_instance_id`, `registration_id`, `root_ref?` | A live registration boundary; `root_ref` is an ArtifactRef. No emission from render. |
| `component.unregistered` observation | `component_instance_id`, `registration_id`, `reason` | Reason is cleanup/navigation/disposal/unknown; cleanup does not independently prove unmount. |
| `driver.action.start` observation | `action_id`, `driver`, `operation`, `target_ref?`, `arguments_ref?` | Driver attempts an operation; `driver` is `playwright`, `storybook`, `human_capture`, or `import`; operation is `click`, `fill`, `select`, `key`, `drag`, `scroll`, `navigate`, or `custom` |
| `driver.action.end` observation | `action_id`, `outcome`, `error_code?` | Driver returned/threw/cancelled/timed out; success does not prove a handler/effect occurred |
| `browser.event` observation | `browser_event_id`, `component_instance_id?`, `native_type`, `phase`, `target_ref?`, `current_target_ref?`, `fields_ref?`, `is_trusted?` | Whitelisted browser-event fields; phase is capture/target/bubble/unknown; trust is informational |
| `handler.start` observation | `invocation_id`, `handler_id`, `component_instance_id`, `registration_id?`, `event_prop`, `react_event_type?`, `native_event_type?`, `browser_event_id?`, `state_observation_ref?`, `state_reference_basis` | Actual entry; state-reference basis is captured_render/latest_observed_before_invocation/unavailable. A late callback can reference a closed registration; record it without claiming the component is still mounted. |
| `handler.return` observation | `invocation_id`, `return_kind` | Synchronous return; kind is void/primitive/object/unknown; no arbitrary returned object serialization or Promise settlement claim |
| `handler.throw` observation | `invocation_id`, `error_code`, `error_artifact_ref?` | Same synchronous throw reaches the application; sanitized error evidence only |
| `state.update.declared` declaration | `update_id`, `state_owner_id`, `invocation_id?`, `base_version?`, `update_contract_ref?` | Application-declared intended update; no assertion that React committed it |
| `state.commit.observed` observation | `observation_id`, `state_owner_id`, `component_instance_id?`, `boundary_kind`, `state_schema_ref`, `application_version?`, `previous_observation_id?`, `state_value`, `update_ids`, `dom_snapshot_ref?` | Boundary is react_layout_effect/external_store_commit. React requires an instance ID; a store commit alone makes no rendered-state claim. Update IDs are explicit attribution, not guessed from timing. |
| `operation.start` observation | `operation_id`, `operation_kind`, `invocation_id?` | Explicit asynchronous application boundary; kind is timer/promise/backend/transition/custom |
| `operation.end` observation | `operation_id`, `outcome`, `error_code?` | Completion at an application-observed boundary; outcome is succeeded/failed/cancelled/timeout/unknown |
| `idl.request.prepared` observation | `operation_id`, `backend_operation_id`, `operation_payload_sha256`, `request_id`, `request_sha256`, `projection_ref`, `mediation_receipt_ref`, `execution_context_ref` | A retained validated request; stable logical payload and per-attempt request digests are distinct. No dispatch assertion. |
| `idl.request.dispatched` observation | `operation_id`, `request_sha256`, `dispatch_receipt_ref` | Executor emission at a declared transport boundary; not proof of backend receipt/effect |
| `idl.result.observed` observation | `operation_id`, `request_sha256`, `result_projection_ref`, `backend_receipt_ref?` | One successful unary schema result; backend authentication remains separate |
| `idl.error.observed` observation | `operation_id`, `request_sha256?`, `outcome`, `error_code`, `backend_receipt_ref?` | Validation/denial/transport/backend/timeout/cancellation/unknown outcome, never a success-schema result |
| `application.effect.observed` observation | `operation_id?`, `effect_id`, `effect_contract_ref`, `observation_ref`, `verifier_receipt_ref?` | Domain-specific state/effect observation with explicitly scoped verification |
| `checkpoint` observation | `checkpoint_id`, `completion_policy_ref`, `state_observation_ids`, `dom_snapshot_ref?`, `pending_operation_ids`, `outcome` | Bounded stable point declared by the harness/application; no universal quiescence claim |
| `assertion.result` assertion | `assertion_id`, `evaluator_ref`, `input_refs`, `outcome`, `details_ref?` | Pass/fail/unknown/error/skipped in the separate evaluator stream; excluded from feature input closure |
| `capture.loss` observation | `reason`, `affected_stream_id`, `missing_intervals`, `dropped_count?`, `affected_views` | Loss interval or unknown extent; reason is overflow/serialization/redaction/navigation/producer_crash/unsupported |
| `episode.end` observation | `outcome`, `watermarks`, `pending_operation_ids`, `loss_record_ids`, `completion_policy_ref` | Completed/failed/timeout/cancelled/interrupted/capture_incomplete; collector validates each declared watermark |

`target_ref` and `current_target_ref` identify registered component/DOM locator snapshot artifacts;
it is not an arbitrary selector to execute. `arguments_ref`, `fields_ref`,
`*_artifact_ref`, `*_snapshot_ref`, `*_contract_ref`, `*_schema_ref`, `*_receipt_ref`,
`projection_ref`, `evaluator_ref`, `completion_policy_ref`, `execution_context_ref`, `observation_ref` and
`input_refs` use `ArtifactRef` (arrays where plural). `state_observation_ref`
references a prior state-observation record ID, not a whole app snapshot.
Its `captured_render` basis requires an explicit application binding to that
handler closure; never attach a newer observation merely because it exists.
An absent state reference requires basis `unavailable`.

Runtime entity IDs are unique within a session in their declared namespace
(component instance, registration, action, invocation, state owner, update,
observation, operation or browser event); they resolve across that session's
streams and are never reused. `previous_observation_id` and
`state_observation_ids` refer to payload `observation_id` values, whereas
`state_observation_ref` and `loss_record_ids` use `RecordId` and `RecordId[]`.
Cross-session references require the source session/manifest and cannot use a
bare local ID. A `state_owner_id` names one runtime owner, not a component
definition: component-local owners are unique per instance, while an external
store owner can serve several components. Each owner's version domain and
declared schema stay explicit in the source/runtime registration context.

`state_value` is a discriminated union: `{availability: "present", artifact:
ArtifactRef}` or `{availability: "redacted" | "unavailable", reason: string}`.
This distinguishes a real JSON `null` value inside an artifact from missing
evidence. `update_ids`, observation IDs, pending operation IDs, loss IDs and
affected-view names are bounded arrays. `missing_intervals` is an array of closed
objects: `{extent: "known", first: UInt, last: UInt}` with `first <= last`, or
`{extent: "unknown", after: UInt | null}`. Known intervals are inclusive, sorted
and nonoverlapping. `watermarks` maps each stream ID to its final allocated
sequence (`UInt`), or explicit null for a registered stream that allocated no
records. R01 fixtures must exercise every
variant and reject wrong-class/extra-field combinations.

The remaining outcome domains are closed: `driver.action.end` uses `returned`,
`threw`, `cancelled`, `timeout`; `idl.error.observed` uses `validation_rejected`,
`denied`, `transport_error`, `backend_error`, `timeout`, `cancelled`,
`outcome_unknown`; `checkpoint` uses `completed`, `failed`, `timeout`,
`cancelled`, `capture_incomplete`. Other enums use the exact lowercase labels
listed in the kind table. Free-text diagnostic codes are bounded strings, not
additional outcome values.

## Causal and state rules

A record link is the closed object `{record_id, relation}`. Its relation set is:

- `same_native_event`: exact native event object matched in the instrumented
  browser realm, using a WeakMap rather than event-name equivalence.
- `explicit_parent`: context was passed across a declared synchronous or async
  application boundary.
- `within_action_window`: timing association with a driver interval only.
- `observed_after`: per-stream ordering or a recorded synchronization boundary;
  does not assert cause.

A declaration link is instead `{relation: "declared_binding",
source_manifest_sha256, binding_id}`. The source manifest supplies that exact
component/handler/method join; a binding ID is not a record ID and creates no
causal edge. These two shapes form a closed discriminated union.

Build a directed acyclic causal graph from an `explicit_parent` record to the
record containing that link, and from each resolved `state.update.declared`
record to an observation listing its payload `update_id` in `update_ids`.
The latter is a derived attribution edge, not an additional wire-link enum or
proof of an exclusive cause. `same_native_event` is a grouping
relation; it does not turn several handlers into a causal cycle. Association
and clock order must not become causal edges. Preserve zero/many handlers per
action, zero/many updates per handler, and many updates per state observation.

Every handler invocation has one start and at most one synchronous return/throw.
An `operation_id` identifies one attempt, with one start and at most one end;
backend logical operation/idempotency identity is separate and can span attempts.
A missing end remains pending/incomplete. A timeout/cancellation end closes the
local wait, not the backend effect: a later `idl.result.observed` is valid
additional evidence, never a second operation end. The durable backend ledger
reconciles that observation independently. Exact duplicate delivery is
deduplicated; conflicting operation-end records are quarantined for reconciliation.
Producer streams may arrive out of order; the collector waits for explicit
watermarks and bounds pending data before sealing a complete episode.

A sealed episode never gains records beyond its final watermarks. A later
backend result becomes a separate immutable `ui-invocation-reconciliation/v1`
artifact binding its own ID/producer, original episode-manifest reference,
backend operation and logical payload digest, original attempt/request digest,
observed result/error and authenticated verifier receipt. A new collection
episode may reference that artifact. Preserve the original timeout/unknown
outcome and frozen dataset/target closure; incorporating reconciliation requires
a new snapshot and derivation receipt, never rewriting the old training data.

The React event prop, synthetic event type and native event type are separate
fields. No one-to-one name mapping is assumed. Copy permitted primitive fields
during the call; do not persist a live event object or change propagation.
Source: [React event objects](https://react.dev/reference/react-dom/components/common#react-event-object).

Application state version belongs to a declared state owner and instance.
Repeated equal values and repeated commit-phase observations are valid. A
semantic update version is not an effect-call counter, timestamp or global
React commit ID. A multi-owner checkpoint contains a vector of observations;
it is not an atomic application snapshot unless a registered application
transaction supplies that guarantee. The optional native `UIStateRuntime`
version is a separately mapped domain; do not equate its number to React renders.

No-op actions, prevented events, batched updates, rejected requests, stale
responses and cancelled interest are useful negative observations. Capture them
without fabricating a successful transition. Required-view completeness is
profile-specific: an incomplete IDL pair cannot supervise a successful typed-call
pair, but its valid action/handler evidence can enter a declared narrower profile.

## Completion and completeness

Each completion policy binds a scenario-specific assertion/checkpoint,
required state owners, required operations and a finite deadline. A completed
driver command, two animation frames or network idleness does not independently
establish application completion. Use explicit application observations and
assertions. [Playwright readiness guidance](https://playwright.dev/docs/api/class-page#page-wait-for-load-state)

Maintain these independent statuses in the episode manifest:

| Dimension | Values |
| --- | --- |
| Delivery | `complete`, `gaps_declared`, `incomplete`, `conflict` |
| Instrumentation | Per-view `complete_for_declared_scope`, `partial`, `unavailable` |
| Scenario | `completed`, `failed`, `timeout`, `cancelled`, `interrupted`, `unknown` |
| Target admission | Profile ID plus `ready`, `rejected`, or `missing_required_evidence` |
| Independent validation | Named validator/version with passed/failed/unknown/error/unsupported and evidence references |

A complete capture may record a failed scenario. A passed assertion may coexist
with missing trace data. Neither status overwrites the other. No single
`roundtrip_ok`, `success` or numeric loss column may stand in for this evidence.
Feature envelopes and checkpoints always keep `qualified`, `admitted`,
`formalized` and promotion authority false. Separate qualification receipts
record scoped policy outcomes without changing those feature flags.

When projecting independent validation into `DomainTargetEnvelope`, preserve
`passed`, `failed` and `unsupported` directly; map unestablished `unknown` or
execution `error` to `not_run`, retaining the original outcome and reason in
details. This records that no valid determination exists; it must not erase
an already observed failure. Keep the full original receipt beside the envelope.

## Bounded collection and redaction

Initial proposed caps are 64 KiB per record, JSON nesting depth 16, 32 links,
256 array elements, 128 object members, 4 KiB string values and 32 KiB per
allowlisted state/value artifact. Use an explicit larger-artifact profile when
these bounds are insufficient; no silent truncation. One episode admits at most
4,096 records and 16 MiB record bytes; one session at most 64 MiB records.
DOM snapshots have their own 1 MiB cap and are stored by reference. Screenshots
and video are disabled in the first feature pilot; their collection requires a
separate byte budget. These are proposed capture limits, not changed existing
native training bounds.

The in-page queue is bounded to 2 MiB or 1,024 records, whichever is reached
first; reserve capacity for a loss marker. Flush at checkpoints and on a bounded
timer outside handlers. On overflow, continue the application, increment the
allocated sequence/drop counters and mark capture incomplete. If even the loss
marker cannot be delivered, the collector's missing heartbeat/watermark leaves
the episode incomplete. Never block a UI action waiting for disk or network.

Only registered JSON field selectors may export state, input values, request
parameters or result subsets. Deny credentials, cookies, auth headers, passwords,
tokens and raw personal identifiers by default. Redact before durable spool,
hashing and upload. Unredacted values must not leak through error messages,
console traces, screenshot files, source maps or raw network captures. Automated
PII heuristics supplement rather than replace the explicit field policy.

A redacted value cannot remain falsely bound to an unredacted request digest.
Keep separate identities for the original retained request and public redacted
projection. If the original bytes cannot be exported, mark the public projection
nonreplayable and retain only scoped verifier evidence. Unsalted hashes of
low-entropy secret values are not a safe redaction format. v1 fixture data is
synthetic so full typed-call replay can be tested without this ambiguity.

## Storage and query shape

Proposed tables in a versioned UI corpus catalog are `ui_capture_sessions`,
`ui_capture_streams`, `ui_trace_shards`, `ui_trace_records`, `ui_episode_manifests`,
`ui_source_bindings`, `ui_snapshot_members`, `ui_split_assignments`,
`ui_projection_derivations`, `ui_validation_receipts` and `ui_delivery_outbox`.
`ui_trace_records` keys session/stream/sequence and stores record ID/kind,
episode/build/source identities, causal-link references, payload digest and
artifact reference. Common predicates use typed columns; variant JSON remains
available for audit. Do not alter the model registry's strict schema by ad hoc
table creation.

Collector stages bounded Arrow record batches and seals immutable Parquet
shards. The shard manifest binds ordered record digests, sequence intervals,
schema/producer, size/count and all blob references. Complete shards and a
durable manifest become visible atomically. Readers consume committed manifests,
never files selected by directory listing while a writer is appending.

Ingestion is at least once with idempotent logical registration: operation ID
plus exact payload digest, and conflict on changed content. Commit the corpus
receipt and outbox in one owner transaction. Replay a lost acknowledgement by
looking up that operation, not by creating another ID. DuckLake and HF deliveries
have independent receipts. An HF upload alone does not commit a dataset snapshot
or mark a training assignment finished.

Keep raw imports, normalized observations, declarations, evaluation answers,
targets, model candidates and validation receipts in separate immutable
namespaces with explicit references. Rollback switches a manifest pointer;
it does not rewrite historical events. Garbage collection must trace every
retained snapshot, candidate parent, sparse ancestry and outstanding operation.

## Example episode semantics

For an authored search form, a driver begins `fill` and the browser emits input
events. `onChange` starts with an exact native-event match, declares an update,
then returns. A commit-phase observation records the new query. An explicitly
attributed debounce operation later prepares/dispatched a verified
`search_records` request. A response is correlated to its full request digest;
an application commit renders results only if its request/version is current.
The harness records an assertion in the evaluator stream and closes all
participating streams with sequence watermarks.

If a second query wins the race, the first response remains observed but stale;
it cannot overwrite the new query's state. If the first request times out after
dispatch, its backend outcome remains unknown. If collection loses an event,
the episode records the gap. Every one of these outcomes can retain useful
features without being relabeled as an entirely successful interaction.

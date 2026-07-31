# UI/UX IR v1 Boundary Vocabulary and Authority Contract

| Field | Value |
| --- | --- |
| Interface | `UIUXIRArchitectureContract@1` |
| Program | `UIR` / board `ipfs-datasets-ui-ux-ir-v1` |
| Wire identifier | `ui-ux-ir/v1` |
| Status | Frozen for M0 / UIR-001 |
| Date | 2026-07-31 |
| Authority source | `implementation_plan/docs/45-ipfs-datasets-ui-ux-ir-plan-2026-07-31.md` |
| Machine-readable companion | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/v1/vocabulary.json` |

This document freezes the ownership boundary, semantic vocabulary, supported
and unsupported subsets, result-authority classes, hardware assumptions,
extension policy, threat boundaries, and exclusive shared-file owners for the
UI/UX intermediate representation program. It is read-only with respect to
production modules: no package export, registry, broker, mediator, or schema
implementation is modified by this contract alone.

## 1. Purpose and non-claims

UI/UX IR (`UIIR`) is a source-grounded, content-addressed declaration of
human/agent interaction semantics and presentation-neutral affordances. It
supports:

1. import of supported UI declarations into a stable semantic model;
2. multi-view formalization (FOL/F-logic, event calculus, TDFOL, DCEC);
3. reconstruction and semantic round trip under an explicit equivalence policy;
4. bounded synthesis from Intent IR, MCP-IDL, and reviewed formal constraints;
5. capability-constrained projection to web, mobile, Meta glasses, and
   voice/headless targets;
6. multimodal runtime mediation into governed Intent/ORB invocations; and
7. retention of identity, provenance, policy, proof, projection loss, and
   runtime receipts as **separate** artifacts from the immutable declaration.

### 1.1 Explicit rejections (non-goals)

The following claims are **out of scope for v1** and must never be asserted by
implementations, adapters, pilots, or documentation:

| Rejected claim | Rationale |
| --- | --- |
| Universal source-code recovery | Pixel-perfect or stylistically identical reconstruction of React, SwiftUI, Jetpack Compose, Flutter, CSS, binary UI, or arbitrary original source is not offered. Source maps and target artifacts may retain fragments; semantic equivalence is the only round-trip claim. |
| Raw Neural Band / raw EMG access | Canonical events must not claim raw EMG, continuous neural streams, or unreviewed biometric payload authority. Meta Web Apps expose Neural Band/captouch as normalized Arrow/Enter-style intent; only that normalized capability is modeled until a separately reviewed official adapter contract exists. |
| UI visibility as authorization | Hiding, disabling, or omitting a control is never a grant, denial, or proof of authorization. Runtime mediation owns authorization. |
| Monitor or validator as proof | Bounded monitoring, schema validation, and accessibility checks are distinct from theorem proof. |
| Policy approval as formal proof | Deontic/policy allow decisions do not prove formulas and do not substitute for proof backends. |
| Learned synthesis as admitted semantics | LLM/model candidates are candidate-only; deterministic schema, policy, formal, accessibility, and capability gates admit them. |
| Identity domain conflation | `ui_ir_cid`, verified MCP `interface_cid`, and typed legacy aliases are never interchangeable. |
| Replacing landed authorities | UIIR does not replace MCP-IDL, Intent IR, Invocation IR, ORB routing, `ir_core`, formalization backends, or existing proof systems. |

## 2. Inventory of retained authorities

UIIR **imports and references** the systems below. It does not fork them.

### 2.1 `ir_core`

| Path | Role |
| --- | --- |
| `external/ipfs_datasets/ipfs_datasets_py/logic/ir_core/` | Canonical bytes, identity, provenance, schemas, diagnostics, claims, result-authority families, and manifests |

**Reuse decision:** import directly; do not reimplement identity or provenance
kernels inside `ui_ux_ir`.

### 2.2 Intent IR and Invocation IR

| Path | Role |
| --- | --- |
| `external/ipfs_datasets/ipfs_datasets_py/logic/intent_ir/` | Program goals, actions, conditions, effects, verification, control flow |
| `external/ipfs_datasets/ipfs_datasets_py/logic/intent_ir/invocation/model.py` | Governed invocation, actor, delegation, scope, rollback, verification (`InvocationIntentEnvelope`) |

**Reuse decision:** reference by stable ID/CID; bind UI actions to invocation
templates; never duplicate program semantics inside the UI declaration.

### 2.3 Formalization and logic-family backends

| Path | Role |
| --- | --- |
| `external/ipfs_datasets/ipfs_datasets_py/logic/formalization/` | Domain-neutral formal views and translation receipts |
| `external/ipfs_datasets/ipfs_datasets_py/logic/fol/` | First-order logic |
| `external/ipfs_datasets/ipfs_datasets_py/logic/TDFOL/` | Temporal-deontic first-order logic |
| `external/ipfs_datasets/ipfs_datasets_py/logic/flogic/` | Frame / F-logic structural and capability facts |
| `external/ipfs_datasets/ipfs_datasets_py/logic/CEC/native/` | DCEC and event calculus |

**Reuse decision:** extend through UI/UX adapters and views; do not couple the
UIIR schema to unstable internal AST variants of any logic family.

### 2.4 Logic bridges and multi-view routing

| Path | Role |
| --- | --- |
| `external/ipfs_datasets/ipfs_datasets_py/logic/bridge/` | Multi-view logic routing and bridge registry |
| `external/ipfs_datasets/ipfs_datasets_py/logic/bridge/registry.py` | Shared bridge registration surface (late owner only) |

**Reuse decision:** register a UI/UX formalization adapter **late**
(`UIR-070`); leaf compilers must not edit the shared bridge registry.

### 2.5 MCP-IDL

| Path | Role |
| --- | --- |
| `swissknife/src/services/mcp/mcp-idl.ts` | Callable service contracts and argument/result schemas |
| `external/ipfs_accelerate/ipfs_accelerate_py/mcp_server/mcplusplus/idl_registry.py` | Verified CIDv1 / raw / sha2-256 / base32 interface identity (preimage verification) |

**Reuse decision:** MCP-IDL owns operation contracts. Interface identity
authority for verified CIDs is the accelerator registry profile (detailed in
`UIR-002`). UIIR records `interface_cid` separately from `ui_ir_cid`.

### 2.6 UI profiles and schema-driven generators

| Path | Role |
| --- | --- |
| `swissknife/src/services/mcp/mcp-ui-profile.ts` | Existing schema-driven UI profile |
| `swissknife/src/services/mcp/mcp-schema-ui-generator.ts` | Profile/UI generation from schemas |

**Reuse decision:** convert to/from UIIR through a TypeScript codec; do not
treat profile widgets as canonical semantic roles.

### 2.7 ORB mediation and control-surface contracts

| Path | Role |
| --- | --- |
| `swissknife/src/services/mcp/mcp-deontic-interface-broker.ts` | Deontic UI projection and ORB gate |
| `swissknife/src/services/mcp/mcp-control-surface-mediator.ts` | Multimodal envelopes and mediation |
| `swissknife/src/services/mcp/mcp-orb-capability-router.ts` | ORB capability routing |
| `swissknife/contracts/` | Cross-runtime control-surface contracts |
| `hallucinate_app/python/hallucinate_app/control_surface_mediator.py` | Python control-surface mediator (fail-closed parity target) |

**Reuse decision:** keep broker/mediator as runtime consumers; route every
external effect through governed invocation; replace local semantic
duplication incrementally under exclusive owners (`UIR-033`, `UIR-034`).

### 2.8 Meta-glasses and related projection

| Path | Role |
| --- | --- |
| `swissknife/src/services/glasses/idl-to-glasses-compiler.ts` | Existing glasses projection baseline |
| Related Meta profiles/adapters under `swissknife/src/services/glasses/` | DAT vs Web App capability paths, display, audio, camera adapters |

**Reuse decision:** implement a UIIR target adapter and conformance suite;
respect current DAT versus Web App capability paths; never invent continuous
cursor, free-form touch, continuous text input, or raw-EMG assumptions.

## 3. Strict architectural boundaries

```text
MCP-IDL                 Intent IR / invocation IR       reviewed policy
   |                              |                           |
   +-------------- source adapters / stable references ------+
                                  |
                           UI/UX IR declaration
                                  |
                 +----------------+----------------+
                 |                                 |
          formalization views               target projection
   FOL/F-logic | EC | TDFOL | DCEC       web | mobile | glasses | voice
                 |                                 |
          proof/monitor results              projection + loss receipt
                 +----------------+----------------+
                                  |
                       mediated runtime interpreter
                                  |
       normalized input -> policy decision -> ORB/program invocation
                                  |
                    state transition + feedback receipt
```

| Domain | Exclusive owner of semantics | May not do |
| --- | --- | --- |
| MCP-IDL | Service/operation contracts and argument/result schemas | Own UI presentation or interaction state machines |
| Intent IR | Program goals, procedures, control flow | Own target layout or accessibility trees |
| Invocation IR | Attempted governed calls | Own UI declaration identity |
| UI/UX IR | Human/agent interaction semantics and presentation-neutral affordances | Own raw device SDKs or runtime authorization |
| Device adapters | Raw sensor SDKs and renderer details | Promote raw payloads to canonical authority |
| Mediator / ORB | Runtime authorization and governed invocation | Be replaced by UI visibility or renderer shortcuts |
| Formal backends | Proof, satisfiability, monitoring results | Be substituted across authority families |

### 3.1 Declaration versus derived/runtime artifacts

`UIIRDocument` is immutable. The following are **separate** content-addressed
artifacts and **must not** change declaration identity (`ui_ir_cid`):

- target-specific projection;
- device-capability negotiation result;
- formalization or reconstruction artifact;
- proof, countermodel, monitor, accessibility, or policy results;
- input observation or recognized intent;
- mediation decision;
- ORB/program invocation receipt;
- runtime state snapshot or replay trace;
- timing, device health, confidence calibration, or performance telemetry.

## 4. Authority classes

Result authorities are typed and non-substitutable.

| Authority kind | What it certifies | What it is not |
| --- | --- | --- |
| `declaration` | Immutable UIIR document and `ui_ir_cid` | Execution permission |
| `interface` | Verified MCP `interface_cid` preimage | UIIR identity |
| `legacy_alias` | Typed historical descriptor ID | Real CIDv1 identity |
| `projection` | Target-specific view plus explicit loss | Declaration rewrite |
| `observation` | Normalized interaction event | Policy or proof |
| `mediation` | Allow / deny / confirm / defer / rewrite / fallback / rate-limit | Theorem proof |
| `invocation` | Governed Intent/ORB call receipt | UI visibility |
| `satisfiability` | Constraint satisfiability outcome | Policy approval |
| `monitor` | Bounded runtime/monitor evidence | Full theorem proof |
| `proof` | Theorem/prover result for supported fragments | Runtime authorization |
| `accessibility` | Perceivability/operability/conformance check | Policy grant |
| `policy` | Deontic/policy decision | Formal proof |
| `synthesis_candidate` | Generated candidate only | Admitted semantics |
| `conformance` | Cross-language/golden vector agreement | Source recovery |

**Fail-closed rule:** missing policy, missing real streaming input, mismatched
preimages, pseudo-CIDs, unknown versions/extensions, and direct-renderer
transport bypasses fail closed.

## 5. Identity domains

| Identity | Domain | Verification |
| --- | --- | --- |
| `ui_ir_cid` | Canonical UIIR declaration bytes | Deterministic canonicalize + content address (independent of optional CID availability for local tests) |
| `interface_cid` | MCP interface descriptor | CIDv1 / raw / sha2-256 / base32 preimage verification via accelerator `idl_registry` profile |
| `legacy_alias` | Historical `sha256:*`, mock `bafy-*`, weak pseudo-CID, or mislabeled labels | Retained only as typed aliases; never equated to verified CIDs |

Rules:

1. Never compare `ui_ir_cid` and `interface_cid` as interchangeable.
2. Never treat a legacy alias as a verified CIDv1 without explicit disposition.
3. Reject stale mutable-cache identities and mislabeled DAG-PB identity paths
   for interface authority (interop detail frozen in `UIR-002`).
4. Identity-affecting descriptor fields must be bound in preimage vectors.

## 6. v1 supported semantic subset

The v1 wire form is closed by default (`ui-ux-ir/v1`). Unknown top-level fields
and undeclared extensions fail closed. Extensions are allowed only via
versioned namespaced extension records (see §9).

### 6.1 Document envelope (supported)

- `schema_version`, `document_id`, title, locale defaults, tags
- immutable `SourceRef`, producer, configuration, review, and trust bindings
- semantic component nodes and composition edges
- abstract layout regions and constraints
- design-token references (not device-specific pixels)
- state variables, states, events, transitions, guards, and effects
- UX tasks, journeys, success/failure/recovery paths, and feedback contracts
- accessibility and localization semantics
- input/output modality requirements and alternatives
- device-capability requirements and adaptive variants
- data bindings and content references
- stable program, Intent IR, invocation, and MCP-IDL bindings
- formal constraint and proof-obligation references
- explicit entry components, initial states, and terminal outcomes

### 6.2 Component graph (supported)

Semantic nodes (not framework widgets):

- stable component ID and role (ARIA-aligned where possible; namespaced domain
  roles allowed)
- purpose and accessible name/description references
- value, selection, validation, enabled/visible semantics
- parent, child, slot, label, described-by, owns, and flow relationships
- action affordances and accepted modality bindings
- data source/query/update references
- feedback channels and error/recovery surfaces
- privacy sensitivity and presentation classification
- optional target hints that **cannot** override semantic requirements

Framework-specific names (e.g. React class names) are source-map metadata only.

### 6.3 Layout and adaptation (supported)

Constraints over regions, order, containment, alignment, adjacency, priority,
visibility, minimum readable size, and resource budgets:

- region kinds: flow, grid, stack, overlay, spatial anchor, audio sequence
- responsive breakpoints as capability predicates
- safe-area, field-of-view, text-density, action-count, update-rate, latency,
  and attention-budget constraints
- logical reading/focus order independent of visual order
- design tokens: type, spacing, color intent, emphasis, motion, haptics, audio
- adaptation policies: `preserve`, `adapt`, `summarize`, `fallback`, `omit`

Projection must never silently drop a required action, confirmation, error,
privacy indicator, or accessibility alternative.

### 6.4 Behavior and UX flow (supported)

Bounded hierarchical state machines:

- typed state variables and derived state
- input, domain, lifecycle, timer, and program-result events
- deterministic transition priority and conflict handling
- guards referencing facts or formal constraints
- effects referencing Intent actions or IDL operations
- cancel, retry, undo, rollback, compensation, and timeout paths
- parallel regions and joins
- focus/navigation state; pending confirmation and consent state
- success, failure, partial, unavailable, and degraded outcomes

Executable code, callbacks, and arbitrary expressions are **forbidden**. Only
stable references or a reviewed closed expression language may appear.

### 6.5 Program bindings (supported)

Exactly one semantic target per action binding:

- MCP-IDL interface CID + method + schema references
- Intent IR document/action ID
- Invocation Intent template CID
- local state-only transition
- versioned composite workflow reference

Bindings may carry preconditions, expected effects, verification, rollback,
idempotency, risk class, confirmation class, audience, and result-to-state
mappings. Bindings **never** embed implementation code or grant authority.

### 6.6 Accessibility, localization, cognitive UX (supported)

- accessible name, description, role, value, state, relationships, live regions
- keyboard/focus navigation and focus restoration
- modality alternative for every essential action and output
- contrast/emphasis intent without hard-coding a single theme
- reduced motion/audio, magnification, captions, transcripts, haptic
  alternatives, time-extension preferences
- message IDs, variables, plural/select, text direction, locale fallback
- interaction cost, urgency, interruption class, confirmation load, attention
  budget
- recovery and consequence previews for risky actions

### 6.7 Modalities and capability profiles (supported)

**Input capabilities:** pointer/mouse, keyboard, switch, touchscreen, pen;
microphone/speech intent and audio; hand gesture, gaze, head pose,
motion/orientation; D-pad/captouch and **normalized** Neural Band intent;
agent proposal and delegated autonomous action; composite/multimodal input.

**Output capabilities:** display, spatial display, audio/speech, haptic,
notification, mobile companion, agent-readable structured output.

**Canonical runtime event fields:** recognized event or intent, confidence and
calibration, source capability, consent/purpose, freshness, and a redacted
evidence reference. Raw camera, microphone, biometric, gaze, or neural signals
remain adapter-local and purpose-bound.

### 6.8 Formal views (supported mapping families)

| View | UI/UX meaning |
| --- | --- |
| FOL / F-logic | Components, roles, containment, slots, values, bindings, actors, devices, capabilities |
| Event calculus | Events, fluents, lifecycle, focus, pending, timeout, cancellation, effects, persistence |
| TDFOL | Temporal invariants plus permission, prohibition, obligation |
| DCEC | Perception, knowledge, belief, intention, communication, consent, delegation, agency |
| Accessibility constraints | Perceivability, operability, modality equivalence, focus, timing, feedback |

Every source semantic node receives one coverage disposition:
`represented` | `approximated` | `unsupported` | `intentionally_non_formal`.

### 6.9 Equivalence policy layers (supported claims)

1. canonical identity for unchanged declarations;
2. graph isomorphism for semantic component and binding graphs;
3. state-machine trace equivalence over bounded generated traces;
4. formula equivalence or mutual entailment for supported formal fragments;
5. deontic non-weakening for permissions, prohibitions, and obligations;
6. accessibility role/name/action equivalence;
7. modality coverage and fallback equivalence;
8. declared projection/reconstruction loss below a reviewed threshold.

Source-code equality and pixel equality are **outside** the equivalence claim.

## 7. v1 unsupported semantics

The following are unsupported or fail closed in v1 (may later become versioned
extensions only under reviewed admission):

| Category | Unsupported |
| --- | --- |
| Source recovery | Arbitrary React / SwiftUI / Compose / Flutter / CSS / binary UI recovery; pixel-perfect or stylistic identity |
| Executable content | Callbacks, free-form code, arbitrary expressions, unsafe HTML interpolation as declaration content |
| Hardware overclaim | Raw EMG, continuous Neural Band streams, unreviewed biometrics as canonical events |
| Identity | Pseudo-CIDs, mismatched preimages, equating UIIR and interface IDs, mutable-cache identity as authority |
| Authorization substitution | Visibility/enabled as authz; monitor as proof; policy as theorem; synthesis as admitted semantics |
| Silent loss | Dropping required actions, confirmations, errors, privacy indicators, or accessibility alternatives without loss receipt |
| Authority replacement | Competing operation, procedure, policy, identity, or execution systems outside landed owners |
| High-risk autonomy | Shipping high-risk autonomous UI actions without runtime policy mediation |
| Transport bypass | Direct renderer HTTP/fetch paths that skip mediation; optional policy on ORB streams |

Import, formalization, projection, and reconstruction **must** report
unsupported or lossy detail explicitly. Silent coercion is forbidden.

## 8. Meta capability assumptions (frozen)

These assumptions are authoritative for glasses projection and embodied input
until revised with an authoritative capability source (plan decision item 7).

| Profile path | Assumption |
| --- | --- |
| Meta Web Apps | Neural Band / captouch exposed as Arrow / Enter style navigation and activation intents |
| Meta DAT | Distinct capability path from Web Apps; adapters must not collapse DAT and Web App profiles |
| Normalized Neural Band | Abstract intent tokens only (directional/select), not raw EMG features |
| Continuous cursor | **Not** assumed available |
| Free-form touch | **Not** assumed available as full touchscreen pointer |
| Continuous text input | **Not** assumed on glasses; text entry falls back or uses companion |
| Camera / mic raw streams | Adapter-local, consented, purpose-bound; not canonical UIIR authority |
| Mandatory semantics that do not fit | Explicit mobile/audio fallback or fail with loss report |

## 9. Extension policy

1. Core `ui-ux-ir/v1` validation is **closed**: unknown fields fail closed.
2. Extensions use versioned, namespaced extension records only.
3. Every admitted versioned, namespaced extension record is **declaration
   content** and therefore affects canonical bytes and `ui_ir_cid`.
4. Observations, telemetry, projections, proof/policy results, and other
   derived/runtime artifacts are **not** extensions and remain outside
   declaration identity (see §3.1).
5. New modalities, spatial features, or device claims require reviewed admission
   into vocabulary and contract; speculative expansion of the v1 subset is
   forbidden.
6. Spatial anchors may remain in core layout kinds when representable as
   constraints; device SDK types never appear in the declaration.
7. Migrations between versions are deterministic, cycle-free, and emit
   source/destination/loss receipts (`UIR-011`).

## 10. Threat and safety boundaries

Non-negotiable invariants (from plan §9):

1. Canonical declaration identity excludes observations and derived results.
2. All references resolve; set/ordered collection semantics are declared.
3. Unsupported import/formalization/projection/reconstruction is explicit.
4. Renderers adapt presentation but cannot remove required obligations.
5. UI visibility/enabled never replaces runtime authorization.
6. Every external effect passes Intent/Invocation/ORB and produces a receipt.
7. Raw sensor and biometric/neural data are minimized and adapter-local.
8. Low-confidence or conflicting high-impact input requires clarification or
   confirmation.
9. Agent actions carry delegation and cannot broaden capability via UI binding.
10. Learned synthesis and retrieval are candidate-only.
11. Proof, satisfiability, monitor, policy, and conformance results are never
    substituted for one another.
12. Migrations and cross-language codecs have golden vectors.
13. Identity domains remain typed and preimage-verified where claimed.
14. Missing policy, missing streaming input, and transport bypasses fail closed.

Adversarial classes that must fail closed: sensor injection, prompt injection
via UI source, stale/replayed events, duplicate events, confused deputy, and
unauthorized agent delegation expansion.

## 11. Exclusive hot-file ownership map

Parallel workers treat the following as **single-owner conflict surfaces**.
No other task may edit these paths.

| Concern | Exclusive owner task | Owned paths |
| --- | --- | --- |
| V1 schema / JSON Schema | `UIR-010` | `external/ipfs_datasets/ipfs_datasets_py/logic/ui_ux_ir/schema.py`, `.../ui_ux_ir.schema.json`, unit schema tests |
| Canonicalization / decode / migrations | `UIR-011` | `canonicalize.py`, `decoder.py`, `migrations.py` |
| Internal package `__init__` surfaces | `UIR-069` | Subpackage `__init__.py` under `ui_ux_ir/model`, `formalize`, `source_adapters`, `projection`, `runtime`, `runtime/input`, `assurance` |
| Public exports and registries | `UIR-070` | `ui_ux_ir/__init__.py`, `logic/api.py`, `logic/submodule_registry.py`, `logic/bridge/registry.py` |
| SwissKnife deontic broker / mediator / ORB router | `UIR-033` | `swissknife/src/services/mcp/mcp-deontic-interface-broker.ts`, `mcp-control-surface-mediator.ts`, `mcp-orb-capability-router.ts` |
| Hallucinate Python mediator | `UIR-034` | `hallucinate_app/python/hallucinate_app/control_surface_mediator.py` |
| Legacy dynamic web renderer security | `UIR-035` | `swissknife/web/src/orb-dynamic-app-renderer.ts` |
| Cross-language golden / integration fixtures | `UIR-062` | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/v1/golden_vectors.json`, `.../conformance.py`, cross-language tests |
| Responsive form pilot | `UIR-071` | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/pilots/responsive_form.json`, `external/ipfs_datasets/tests/integration/logic/ui_ux_ir/test_responsive_form_pilot.py` |
| Destructive workflow pilot | `UIR-072` | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/pilots/destructive_workflow.json`, `external/ipfs_datasets/tests/integration/logic/ui_ux_ir/test_destructive_workflow_pilot.py` |
| Meta glasses pilot | `UIR-073` | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/pilots/meta_glasses.json`, `external/ipfs_datasets/tests/integration/logic/ui_ux_ir/test_meta_glasses_pilot.py` |
| Agent supervisor program pilot | `UIR-074` | `external/ipfs_datasets/tests/fixtures/ui_ux_ir/pilots/agent_supervisor_program.json`, `external/ipfs_datasets/tests/integration/logic/ui_ux_ir/test_program_supervisor_pilot.py` |
| Architecture contract + vocabulary (this task) | `UIR-001` | `docs/architecture/UI_UX_IR_CONTRACT.md`, `tests/fixtures/ui_ux_ir/v1/vocabulary.json` |
| MCP-IDL identity interop profile | `UIR-002` | `docs/architecture/UI_UX_IR_MCP_IDL_IDENTITY.md`, identity vectors and tests |

### 11.1 Late-integration rule

- Do not edit shared package exports or registries before `UIR-070`.
- Do not edit the existing SwissKnife deontic broker or control-surface
  mediator before `UIR-033`.
- Leaf tasks own exclusive files; collisions become scheduler conflicts, not
  silent multi-writer merges.

### 11.2 Protected operator inputs (never implementation outputs)

- `implementation_plan/docs/45-ipfs-datasets-ui-ux-ir-plan-2026-07-31.md`
- `implementation_plan/docs/45-ipfs-datasets-ui-ux-ir.objectives.md`
- `implementation_plan/docs/45-ipfs-datasets-ui-ux-ir.todo.md`

## 12. Package target layout (reference)

```text
external/ipfs_datasets/ipfs_datasets_py/logic/ui_ux_ir/
  schema.py, ui_ux_ir.schema.json, canonicalize.py, decoder.py, migrations.py
  protocols.py, provenance.py, conformance.py
  model/{components,layout,behavior,experience,modality,bindings}.py
  formalize/{contracts,ontology,compiler,flogic,event_calculus,tdfol,dcec,
             decompiler,roundtrip,synthesis}.py
  source_adapters/{mcp_idl_identity,mcp_idl,intent_ir,dom_aria}.py
  projection/{capabilities,solver,loss,web,mobile,glasses,voice}.py
  runtime/{events,fusion,state_machine,mediator,receipts}.py
  runtime/input/{conventional,speech,embodied}.py
  assurance/{accessibility,privacy,security}.py
```

TypeScript/mobile adapters (new files under exclusive tasks):

- `swissknife/src/services/mcp/ui-ux-ir-codec.ts`
- `swissknife/src/services/mcp/ui-ux-ir-web-renderer.ts`
- `swissknife/src/services/glasses/ui-ux-ir-glasses-adapter.ts`
- `mobile/src/orb/uiUxIrMobileAdapter.js`

## 13. Public API target (side-effect free)

Cold import of `ipfs_datasets_py.logic.ui_ux_ir` starts no network, process,
hardware, or model action. Intended stable surface:

```python
decode_ui_ir(payload) -> UIIRDocument
canonicalize_ui_ir(document) -> bytes
ui_ir_identity(document) -> CanonicalIdentity
compile_ui_ir(document, request) -> UIFormalizationArtifact
decompile_ui_formalization(artifact, request) -> UIReconstructionArtifact
roundtrip_ui_ir(document, policy) -> SemanticRoundTripReport
synthesize_ui_ir(inputs, constraints, policy) -> UISynthesisResult
project_ui_ir(document, device_profile, policy) -> UIProjectionArtifact
normalize_ui_interaction(raw_event, adapter_context) -> UIInteractionEvent
evaluate_ui_interaction(document, event, runtime_context) -> UIMediationDecision
```

## 14. Relationship to multimodal control-surface plan

This program extends, rather than supersedes,
`implementation_plan/docs/22-multimodal-control-surface-logic-idl.md`. That
plan owns multimodal mediation around ORB calls. This program adds the
canonical UI declaration, bidirectional formalization, target projection, and
semantic round-trip contracts.

## 15. Validation of this freeze

Structural validation for UIR-001:

```bash
test -f external/ipfs_datasets/docs/architecture/UI_UX_IR_CONTRACT.md \
  && python -m json.tool external/ipfs_datasets/tests/fixtures/ui_ux_ir/v1/vocabulary.json
```

MCP-IDL identity vectors and tests are owned by `UIR-002` and are not part of
this task's declared outputs.

## 16. Terminology glossary (selected)

| Term | Meaning |
| --- | --- |
| `UIIRDocument` | Immutable UI/UX IR declaration |
| `ui_ir_cid` | Content identity of a UIIR declaration |
| `interface_cid` | Verified MCP interface identity |
| `UIInteractionEvent` | Normalized, consented, non-raw runtime input event |
| `UIMediationDecision` | Runtime allow/deny/confirm/defer/rewrite/fallback/rate-limit outcome |
| `UIProjectionArtifact` | Target-specific projection plus loss receipt |
| `UIFormalizationArtifact` | Linked multi-view formalization with coverage |
| `SemanticRoundTripReport` | Layered equivalence evaluation artifact |
| `coverage disposition` | `represented` / `approximated` / `unsupported` / `intentionally_non_formal` |
| `loss receipt` | Explicit record of dropped or adapted mandatory semantics |

---

*End of `UIUXIRArchitectureContract@1`. Subsequent schema and runtime work must
conform to this freeze or revise it through an explicit versioned contract
change, not through silent drift.*

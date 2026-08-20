# GUI optimizer closed contracts

**Status:** Current
**Audience:** Developers and agents exchanging VerifiedGuiOptimizer wire
records across Python and TypeScript
**Scope:** Closed models, schemas, identity, formal adapter, invariants, and
receipt authority in `ipfs_datasets_py.logic.gui_optimizer`
**Non-goals:** Scanning repository source, applying patches, selecting models,
caching proofs, WCAG certification, complete security, aesthetic optimality
**Package ID:** `ipfs-datasets.logic.gui-optimizer`
**Canonical JSON profile:** `gui-optimizer-canonical-json/v1`
**Identity profile:** `gui-optimizer-canonical-identity/v1`
**Interfaces:** `VerifiedGuiOptimizerArchitecture@1`,
`GuiEvidenceAuthorityMatrix@1`
**Companions:** `swissknife/docs/gui-optimizer/ARCHITECTURE.md`,
`external/ipfs_accelerate/docs/architecture/VERIFIED_GUI_OPTIMIZER.md`

This package owns versioned finite wire records. Decoders reject unknown
fields, invalid enums, unregistered schema versions, non-finite values,
non-string mapping keys, non-NFC keys, explicit null for nonnullable fields,
and wrong JSON container types before any coercion.

## 1. Purpose

`ipfs_datasets_py.logic.gui_optimizer` is the authoritative Python wire
vocabulary that TypeScript mirrors. It does not scan source, apply patches,
select models, or cache proofs. The TypeScript twin is
`swissknife/src/services/gui-optimizer/models.ts`.

The selected screen that consumes these contracts is the Agent Supervisor
console (`app:agent-supervisor` / `screen:agent-supervisor`), source
`swissknife/web/js/apps/agent-supervisor.js`.

## 2. Package and wire identity

Current Python modules:

| Module | Role |
| --- | --- |
| `schema.py` | Interface labels, schema versions, closed enums, fail-closed helpers |
| `models.py` | Versioned dataclasses and `from_dict` / `to_dict` |
| `identity.py` | Domain-separated CIDv1 / SHA-256 (`GuiCanonicalIdentity@1`) |
| `formal_adapter.py` | `GuiFormalAdapter@1`, `UiConstraintProblem@1`, `UiConstraintResult@1` |
| `invariants.py` | `UiInvariantEngine@1`, `UiInvariantViolation@1` |
| `receipts.py` | `GuiVerificationReceiptEnvelope@1`, `GuiVerificationReceiptAggregator@1` |

Canonical bytes, digest, and CIDv1 for the same payload must match across
Python and TypeScript (`swissknife/test/unit/services/gui-optimizer/identity-vectors.test.ts`
and the datasets model suite). Line numbers are provenance spans, never
primary identity.

Stable logical identity binds application ID, route/screen ID, component
qualified name, component kind, and package/interface namespace.

## 3. Required closed models

`REQUIRED_MODEL_INTERFACES` (every required model is versioned `@1`):

| Interface | Schema |
| --- | --- |
| `GuiApplicationIdentity@1` | `gui-application-identity/v1` |
| `GuiScreenIdentity@1` | `gui-screen-identity/v1` |
| `UiComponentIdentity@1` | `ui-component-identity/v1` |
| `UiComponentVersion@1` | `ui-component-version/v1` |
| `UiDependencyEdge@1` | `ui-dependency-edge/v1` |
| `UiStateDefinition@1` | `ui-state-definition/v1` |
| `UiEventDefinition@1` | `ui-event-definition/v1` |
| `UiTransitionDefinition@1` | `ui-transition-definition/v1` |
| `UiActionBinding@1` | `ui-action-binding/v1` |
| `UiLayoutConstraint@1` | `ui-layout-constraint/v1` |
| `UiAccessibilityContract@1` | `ui-accessibility-contract/v1` |
| `UiSemanticCapsule@1` | `ui-semantic-capsule/v1` (new closed record; not the excluded prior semantic-capsule package) |
| `UiChangeSet@1` | `ui-change-set/v1` |
| `UiInvalidationPlan@1` | `ui-invalidation-plan/v1` |
| `UiEvaluationScenario@1` | `ui-evaluation-scenario/v1` |
| `UiBaseline@1` | `ui-baseline/v1` |
| `UiContextPack@1` | `ui-context-pack/v1` |
| `GuiImprovementProposal@1` | `gui-improvement-proposal/v1` |
| `VisualRegressionReceipt@1` | `visual-regression-receipt/v1` |
| `AccessibilityReceipt@1` | `accessibility-receipt/v1` |
| `InteractionReceipt@1` | `interaction-receipt/v1` |
| `UiConstraintReceipt@1` | `ui-constraint-receipt/v1` |
| `GuiImprovementReceipt@1` | `gui-improvement-receipt/v1` |

Nested records include `SourceSpan@1`, `ViewportSpec@1`,
`VisualChangeRegion@1`, and the `UiContext*` payload types.

An automatically accepted `GuiImprovementReceipt@1` requires nonempty
`invalidation_plan_id`, `context_pack_id`, `patch_digest`, and all four
nonempty receipt-id lists, plus `verification_status` in the exact set
`{verified, integrity_valid}`. It cannot carry rejection reasons. Statuses
`structurally_valid`, `unverified`, `stale`, `invalid`, or `simulated` are
not automatic-acceptance authority.

## 4. Evidence authority matrix

`GuiEvidenceAuthorityMatrix@1` separates two independent dimensions.

**Analysis classification** (`AnalysisClassification`): `exact`,
`conservative`, `heuristic`, `opaque`.

**Verification status** (`VerificationStatus`): `verified`,
`structurally_valid`, `integrity_valid`, `unverified`, `stale`, `invalid`,
`simulated`.

**Evidence level** (`EvidenceLevel`): `automated`, `structural`,
`integrity`, `heuristic`, `human_reviewed`, `simulated`.

| What is formally verified | What is structurally validated | What is heuristic or human-reviewed |
| --- | --- | --- |
| A supported bounded obligation in `SUPPORTED_PROPERTY_KINDS` discharged by `GuiFormalAdapter@1` with `UiConstraintResultKind.proved_bounded_property`, premises and solver/tool versions bound | Finite-graph structural conclusions (`structural_result`, `structurally_valid`) such as defined transition targets, single initial state, no duplicate state IDs | Visual hierarchy, density, consistency, clarity, whitespace, polish, primary-action prominence; screen-reader review; unsupported WCAG criteria |

What is formally verified is only the closed set:

- `defined_transition_targets`
- `failure_recovery`
- `async_effect_completeness`
- `event_outcome_coverage`
- `reachable_required_action`
- `single_initial_state`
- `no_duplicate_state_ids`
- `confirmation_bound_action`
- `form_accessible_names`
- `modal_focus_lifecycle`
- `policy_not_browser_authoritative`

Missing solvers, incomplete premises, or opaque analysis yield `unavailable`
or `unknown`. Those outcomes are not proofs.

Content identities and receipts do not prove truth. A hash cannot promote a
heuristic visual description to `verified`. Simulated screenshots or actions
remain `simulated`.

Forbidden claim kinds (`beauty`, `complete_accessibility`,
`complete_security`, `unbounded_correctness`) must never appear as proved or
satisfied solver conclusions.

## 5. Formal adapter and invariants

`GuiFormalAdapter@1` translates finite UI constraints into exact graph
obligations or cvc5-compatible SMT vectors. It reuses the reviewed
`SoftwareVerificationSMTCompiler@1` boundary. It does not create a
theorem-prover platform or a proof-cache.

`UiInvariantEngine@1` catalogs bounded obligations with explicit
pass / fail / unknown outcomes and emits `UiConstraintReceipt@1`. A
`satisfied` status is a bounded structural conclusion under declared
premises, not a WCAG certification or a security proof.

Uncertainty (`unknown`, inconclusive, unsupported, unresolved, non-exact
analysis) cannot auto-accept a change.

## 6. Receipts and content identity

`identity.py` implements domain-separated CIDv1 / SHA-256 without importing
semantic-index, proof-cache, or model-routing code. Domains include
`gui.stable-identity`, `gui.component-version`, `gui.artifact`,
`gui.application-identity`, and `gui.screen-identity`.

`receipts.py` aggregates `VisualRegressionReceipt@1`,
`AccessibilityReceipt@1`, `InteractionReceipt@1`, and
`UiConstraintReceipt@1` into `GuiVerificationReceiptEnvelope@1`. Critical
receipts cannot be omitted from an automatically accepted improvement.

`UiContextPack@1` token accounting is equation-exact:

- `total_estimated_prompt_tokens` = raw + capsule + screenshot-analysis + other
- `ordinary_raw_dependency_tokens` = raw + replaced-by-capsules + screenshot-analysis + other
- `source_tokens_replaced_by_capsules` is never counted as prompt usage
- `compression_ratio` is derived, never trusted from input

## 7. Current modules and interfaces

In addition to the required models, this package currently exports:

- `GuiFormalAdapter@1` / `gui-formal-adapter/v1`
- `UiConstraintProblem@1` / `ui-constraint-problem/v1`
- `UiConstraintResult@1` / `ui-constraint-result/v1`
- `UiInvariantEngine@1` / `ui-invariant-engine/v1`
- `UiInvariantViolation@1` / `ui-invariant-violation/v1`
- `GuiCanonicalIdentity@1` / `gui-canonical-identity/v1`
- `GuiArtifactDigest@1` / `gui-artifact-digest/v1`
- `UiComponentVersionCompiler@1` / `ui-component-version-compiler/v1`
- `GuiVerificationReceiptEnvelope@1`
- `GuiVerificationReceiptAggregator@1`

Tests:

- `external/ipfs_datasets/tests/unit/logic/gui_optimizer/test_models.py`
- `external/ipfs_datasets/tests/unit/logic/gui_optimizer/test_identity.py`
- `external/ipfs_datasets/tests/unit/logic/gui_optimizer/test_identity_vectors.py`
- `external/ipfs_datasets/tests/unit/logic/gui_optimizer/test_formal_adapter.py`
- `external/ipfs_datasets/tests/unit/logic/gui_optimizer/test_invariants.py`
- `external/ipfs_datasets/tests/unit/logic/gui_optimizer/test_receipts.py`

## 8. Application-extension contract additions

Another application does not require new wire schemas if it reuses `@1`
records. It does require new **instances**:

| Addition | Contract object |
| --- | --- |
| Manifest / identity | `GuiApplicationIdentity@1`, `GuiScreenIdentity@1` |
| Target capsules | `UiSemanticCapsule@1`, `UiComponentIdentity@1`, `UiComponentVersion@1` |
| Scenario | `UiEvaluationScenario@1` rows plus catalog fixture |
| Action | `UiActionBinding@1` (and confirmation binding) per displayed action |
| Policy | `depends_on_policy` edges; host still re-evaluates |
| Tests | `UiContextTest@1` payloads and `tested_by` edges |
| Screenshots | `VisualRegressionReceipt@1` with expected/forbidden `VisualChangeRegion@1` |
| Acceptance | `GuiImprovementProposal@1` + four receipt families + `GuiImprovementReceipt@1` |

See `swissknife/docs/gui-optimizer/ARCHITECTURE.md` §8 for the exact file
additions.

## 9. Exclusions and non-goals

This package must not import, call, or derive authority from:

- a prior semantic-index module
- a prior semantic-capsule module
- a proof-cache or formal-verification-cache module
- a model-routing or provider-routing module
- the untracked `ipfs_datasets_py/logic/ui_ux_ir` tree

It may reuse only reviewed primitives: `logic/ir_core/canonical.py`,
`logic/ir_core/identity.py`, bounded SMT compilation, and the closed GUI
wrappers above.

Non-goals: scanning, patch application, model selection, proof caching,
beauty proofs, complete accessibility, complete security, unbounded
correctness, and claiming the GUI is proved optimal.

## 10. Narrow final claim

The selected GUI workflow was incrementally analyzed and improved against declared interaction, accessibility, policy, and visual-regression criteria, with content-addressed evidence for the evaluated scenarios.

Content identities and receipts do not prove truth. Claims that are
formally verified, structurally validated, heuristic, or human-reviewed
keep those labels.

# Logic syntax and family contracts (consumer closure)

| Field | Value |
| --- | --- |
| Interface | `LogicSyntaxAndFamilyContracts@1`, `LogicConsumerClosure@1` |
| Task | `LFP-045` |
| Goal | `LFP-G090` |
| Status | `canonical` |
| Owner | architecture / logic (syntax + family consumer migration) |
| Source of truth | `ipfs_datasets_py/logic/syntax_core/`; `ipfs_datasets_py/logic/families/`; `ipfs_datasets_py/logic/verification_api.py` (`VerificationAPI@2`, `CanonicalLogicDiscovery@1`); `ipfs_datasets_py/logic/api.py`; this document; conformance test `tests/conformance/logic/test_consumer_family_closure.py` |
| Last verified | 2026-08-09 |
| Audience | architect, developer, agent, documentation author, migration owner |
| Related | [README.md](README.md), [IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md), [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](COMPILERS_AND_SEMANTIC_ROUND_TRIP.md), [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md), [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2 |
| Review cadence | when syntax-core node kinds, namespace catalogs, public discovery, or consumer import surfaces change |

> **Lifecycle:** This leaf is the **normative** architecture authority for
> typed syntax contracts, family/namespace identity, dual-read consumer
> migration, and **static consumer-family closure** discovery under
> `LogicConsumerClosure@1`. Historical proposal plans and versioned refactor
> dumps are **nonnormative** (see §9). They may inform migration narrative
> only; they never override this leaf, the live registries, or tests.
>
> **Discovery vs fixed point:** LFP-045 is a **discovery** task. Static
> closure **records** every unregistered emitted ID, undocumented controlled
> syntax form, stale consumer, and failing public example as an
> **owner-scoped typed gap**. The drained **zero-drift fixed point** is
> required by **LFP-046**, not this task.

## 1. Purpose

Answer, in one place:

1. Which **typed syntax-kernel** contracts every family extension must obey.
2. How **semantic family, profile, property, view, notation, encoding,
   provider, lane, and evidence** identities stay non-interchangeable.
3. How **public and internal consumers** dual-read legacy labels and
   **canonical-write** only.
4. How **static consumer-family closure** invents zero silent drift: every
   gap is typed, owner-scoped, and refill-eligible for LFP-046.
5. Why completed `*_PLAN.md` documents and historical taskboards are
   **nonnormative**.

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place syntax, family, and consumer work without inventing a second taxonomy |
| **Parser / family author** | Extend controlled syntax under documented node kinds and namespaces |
| **API / docs author** | Prefer canonical imports; dual-read aliases; never write legacy IDs |
| **Migration owner** | Consume `LogicConsumerClosure@1` gaps; own only declared paths |
| **Refill (LFP-046)** | Drain owner-scoped typed gaps to a zero-drift fixed point |

## 3. Scope and non-goals

### In scope

- Normative syntax-kernel surface (`syntax_core`) identity, source, CST/AST,
  binder, diagnostic, and registry-key contracts.
- Closed **controlled syntax** catalog that documentation and consumers must
  cover.
- Canonical family / namespace model and dual-read / one-write migration.
- Public discovery, import surfaces, registries, and documentation examples
  as **consumer evidence**.
- `LogicConsumerClosure@1` static gap taxonomy and owner scoping.
- Explicit **nonnormative** labeling of historical plans.

### Non-goals

- Draining gaps to a zero-open fixed point (owned by **LFP-046** /
  `LogicGapRefill@1`).
- Solver install recipes, hammer routing, or proof authority promotion
  ([EXTERNAL_PROVERS.md](EXTERNAL_PROVERS.md),
  [RESULT_AUTHORITY.md](RESULT_AUTHORITY.md)).
- Domain IR ontologies for Legal / Security / Intent
  ([IR_FAMILY_AND_IDENTITY.md](IR_FAMILY_AND_IDENTITY.md)).
- Recreating or overwriting `ui_ux_ir` (exact-source gate remains
  declaration-only until import).
- Treating presence, SAT, simulation, or parse success as theorem or
  authorization allow.

## 4. Mental model

```text
  Domain docs / solver files / controlled generated source
              │
              ▼
      SourceDocument@1  (bytes, encoding, spans, digests)
              │
              ▼
      Lossless CST + tokens  (LogicCST@1, LogicToken@1)
              │
              ▼
      Surface AST / TypedExpression@1
      core NodeKind + LogicExtensionNode@1
              │
              ▼
      Family / namespace identities  (LogicIdentityNamespaces@1)
      dual-read legacy → canonical write only
              │
              ▼
      Consumers (API, verification facade, docs, domain adapters)
              │
              ▼
      LogicConsumerClosure@1  static scan
      → owner-scoped typed gaps (discovery)
              │
              ▼
      LFP-046 refill  → zero-drift fixed point (not this task)
```

**Core inequalities (this leaf agrees with the index):**

- declaration **CID** ≠ proof ≠ policy ≠ authorization **allow** ≠ execution
- legacy alias **read** ≠ canonical **write**
- documented controlled syntax ≠ free-form formula text
- recorded gap ≠ drained fixed point

## 5. Typed syntax kernel contracts

Canonical package: `ipfs_datasets_py.logic.syntax_core`.

| Contract | Interface | Owns |
| --- | --- | --- |
| Source document | `SourceDocument@1` | Exact bytes, safe encoding (`ascii` / `utf-8`), line index, digests |
| Token | `LogicToken@1` | Kind, lexeme, trivia, half-open source range |
| CST | `LogicCST@1` | Lossless tree with complete source coverage |
| Parse request / artifact | `ParseRequest@1`, `ParseArtifact@1` | Notation/profile-bound limits, diagnostics, surface AST refs |
| Typed expression | `TypedExpression@1` | Signature-bound, content-identified expression root |
| Extension node | `LogicExtensionNode@1` | Versioned family extension with explicit family/profile/features |
| Parser registry | `LogicParserRegistry@1` | Exact key `(notation_id, notation_version, semantic_profile_id)` |

### 5.1 Fail-closed rules

- Partial registry keys, `latest` / `*` versions, and implicit profile defaults
  are rejected (`ImplicitFallbackError`).
- Unsafe encodings (latin-1, utf-16, charmap, …) are rejected.
- Resource limits only **tighten** within hard ceilings
  (`MAX_SOURCE_BYTES`, `MAX_TOKENS`, `MAX_PARSE_DEPTH`, …).
- Family extensions never smuggle opaque unversioned payloads; payload
  schemas follow `family.construct/vN`.
- Capture-avoiding substitution, alpha-equivalence, free/bound analysis, and
  deterministic normalization live in syntax-core algebra — not in free-form
  string rewrite helpers.

### 5.2 Controlled syntax catalog (normative)

Every controlled syntax form below is **normative**. Emitters, printers, and
public examples must use these identifiers (or dual-read aliases that resolve
to them). Forms present in code but absent from this catalog are recorded as
`undocumented_controlled_syntax` gaps.

#### Core `NodeKind` vocabulary

| Kind | Category | Notes |
| --- | --- | --- |
| `constant` | term | Named constant |
| `variable` | term | Bound or free variable |
| `application` | term | Function application |
| `true` | formula | Boolean true |
| `false` | formula | Boolean false |
| `predicate` | formula | Atomic predicate application |
| `equality` | formula | Term equality |
| `not` | formula | Unary negation |
| `and` | formula | N-ary conjunction |
| `or` | formula | N-ary disjunction |
| `implies` | formula | Binary implication (right-associative where legacy imports apply) |
| `iff` | formula | Binary bi-implication |
| `forall` | formula | Universal binder |
| `exists` | formula | Existential binder |
| `let` | polymorphic | Let-binding (term or formula by body) |
| `extension` | formula/term | `LogicExtensionNode@1` family extension |

#### Notation / source syntax (namespace `notation`)

| Canonical | Dual-read aliases (read only) | Role |
| --- | --- | --- |
| `canonical_text` | — | Kernel text surface |
| `smt_lib2` | `smt`, `smtlib2`, `smt_lib` | SMT-LIB2 source notation |
| `tptp_fof` | `tptp` | TPTP FOF |
| `tla_plus_source` | `tla` | TLA+ source text |
| `tamarin_spthy` | `spthy` | Tamarin spthy |
| `proverif_pv` | `pv` | ProVerif pv |

#### Target encodings (namespace `encoding`)

`smt_lib2`, `tptp_tff`, `lean4`, `rocq`, `isabelle_hol` — never confused with
semantic families or providers.

#### Semantic profiles (namespace `profile`, not families)

`hyperltl`, `qf_bv`, `s4`, `s5`, `secpal`, `tla_plus`,
`temporal_first_order`, and reviewed Kripke / fairness / adversary profiles
documented by family leaves. `dynamic_logic` remains a **profile/alias over
`program`**; `information_flow` remains a **property/profile under
`hyperproperty`**.

## 6. Family and identity contracts

### 6.1 Non-interchangeable namespaces

| Namespace | Role | Examples |
| --- | --- | --- |
| `family` | Semantic family | `first_order`, `temporal`, `deontic`, `hyperproperty` |
| `profile` | Fragment / profile | `secpal`, `hyperltl`, `tla_plus` |
| `property` | Obligation kind | `safety`, `liveness`, `validity` |
| `view` | View role | `verification_condition`, `graph_projection` |
| `notation` | Source syntax | `smt_lib2`, `tptp_fof` |
| `encoding` | Target encoding | `lean4`, `tptp_tff` |
| `provider` | Tool / backend | `z3`, `cvc5`, `lean` |
| `lane` | Execution lane | `smt`, `runtime_monitor`, `itp_kernel` |
| `evidence` | Evidence kind | `candidate`, `kernel_checked_proof`, `counterexample` |

Cross-namespace coercion fails closed. A provider id is never a family id.

### 6.2 Canonical foundation families

`propositional`, `first_order`, `higher_order`, `horn_chc`, `datalog`,
`frame_logic`, `modal`, `deontic`, `temporal`, `transition_system`,
`event_calculus`, `dcec`, `tdfol`, `mu_calculus`, `program`,
`separation_logic`, `concurrency`, `refinement`, `authorization`,
`cryptographic_protocol`, `hyperproperty`, plus planned extensions
`epistemic`, `doxastic`, `intention_agency`, `session_process`, and the
declaration-only candidates listed by the family registry.

### 6.3 Dual-read / one-write migration

| Legacy surface | Canonical disposition |
| --- | --- |
| `fol` | family `first_order` |
| `smt`, `smtlib2`, `smt_lib` | notation `smt_lib2` (not a family) |
| `state_transition`, `tla_plus` (as family) | family `transition_system` + profile `tla_plus` |
| `hyperltl` (as family) | family `hyperproperty` + profile `hyperltl` |
| `protocol` | family `cryptographic_protocol` |
| `secpal`, `policy` (as family) | family `authorization` + profile `secpal` |
| `safety`, `liveness` | property kinds |
| `VC`, `vc` | view `verification_condition` |
| `runtime` | lane `runtime_monitor` |
| `lean`, `rocq`, `isabelle` | providers / encodings, not families |

Public discovery (`CanonicalLogicDiscovery@1`, `VerificationAPI@2`,
`LogicVerificationAPI` list operations) **emits only canonical write values**.
Legacy labels are dual-read with typed `LogicMigrationDiagnostic@1`
dispositions (`canonical`, `replaced`, `rejected_unknown`,
`rejected_wrong_namespace`).

Preferred public imports:

| Prefer | Avoid for new writes |
| --- | --- |
| `ipfs_datasets_py.logic.api` | Free-form family strings in new artifacts |
| `ipfs_datasets_py.logic.verification_api` dual-read / migrate helpers | Writing `fol`, `smt`, `VC`, `protocol` as family ids |
| Direct submodule imports under `logic.*` | Inventing parallel registries |
| Canonical namespace identities | Treating historical plan IDs as live registry values |

## 7. Consumer surfaces under closure

Consumers in scope for static closure evidence:

| Surface class | Representative paths | Owner when stale |
| --- | --- | --- |
| Public Python API | `logic/api.py`, `logic/verification_api.py` | API migration owners (LFP-044 surfaces) |
| Family / namespace registries | `logic/families/*`, `logic/syntax_core/registry.py` | Taxonomy / syntax-core owners |
| Parser catalog | `logic/parsers/catalog.py`, family parsers | Parser-family owners |
| Domain adapters | `legal_ir`, `security_ir`, `crypto_ir`, `intent_ir`, software_* | Domain vertical owners |
| Generated catalogs | `logic/families/generated_catalog.py` | Generated-closure owners |
| Documentation examples | `docs/logic/QUICKSTART.md`, `USAGE_EXAMPLES.md`, architecture leaves | Docs / consumer-migration owners |
| Historical plans | `docs/architecture/*_PLAN.md`, `docs/logic/*_PLAN.md`, versioned refactor series | **nonnormative** — narrative only |

Stale consumers are those that still **write** legacy free-form family labels,
bypass dual-read, or overclaim authority from parse/SAT success. Each is
recorded as a `stale_consumer` gap with an exact owner path; derived repair
tasks own individual consumers (this leaf does not patch them wholesale).

## 8. `LogicConsumerClosure@1` static gap taxonomy

Interface: **`LogicConsumerClosure@1`**

Schema: `logic-consumer-closure/v1`

Task: **LFP-045** (discovery). Fixed-point owner: **LFP-046**.

### 8.1 Gap kinds (closed)

| `gap_kind` | Trigger | Owner-scope rule |
| --- | --- | --- |
| `unregistered_emitted_id` | A public or catalog surface emits a family/profile/property/view/notation/encoding/provider/lane/evidence id not present in the sealed registries | Owning registry or emitter module |
| `undocumented_controlled_syntax` | A controlled syntax form (core `NodeKind`, notation, encoding, or extension construct) is used or registered but absent from §5.2 of this document | This document + syntax-core owner |
| `stale_consumer` | A consumer still writes legacy free-form labels, skips dual-read, or treats historical plan labels as normative | Exact consumer path (derived task may own the fix) |
| `failing_public_example` | A public documentation example fails import, compile, or declared symbol resolution under the validation environment | Docs path + owning public surface |

Every gap record is **owner-scoped** and includes at least:

| Field | Meaning |
| --- | --- |
| `gap_id` | Stable content-addressed or deterministic id |
| `gap_kind` | One of the four kinds above |
| `owner` | Exact package/module/doc path responsible for repair |
| `subject` | Emitted id, syntax form, consumer path, or example id |
| `evidence` | Short deterministic evidence string |
| `refill_eligible` | Always `true` for LFP-046 admission when discovery-valid |
| `task_id` | `LFP-045` for discovery; repair tasks are derived later |

### 8.2 Closure guarantees (this task)

- Static closure **runs hermetically** (no network, install, or host probe).
- Every discovered instance of the four gap kinds is **recorded** — never
  silently dropped or normalized away.
- Closure success **does not** require zero gaps.
- Closure **does not** claim the LFP-046 fixed point.
- Presence of a gap is **not** authority to invent a new family, promote
  advisor confidence, or weaken validation.

### 8.3 Fixed-point handoff

| Task | Role |
| --- | --- |
| **LFP-045** (this leaf + test) | Discover and record owner-scoped typed gaps; mark historical plans nonnormative |
| **LFP-046** | Bounded objective refill to a drained **zero-drift fixed point** over identical source/config/corpus identities |

## 9. Historical plans are nonnormative

The following classes of documents are **historical / nonnormative**. They
are useful for archaeology and migration narrative. They are **not**
architecture authority. When a historical plan disagrees with this leaf, the
live registries, or tests, **this leaf and the live code win**.

| Class | Examples | Label |
| --- | --- | --- |
| Program proposal plan | Superproject `docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md` | **historical / nonnormative plan** — sealed seed narrative; not a second runtime SoT for consumer labels |
| Completed IR / authz proposals | `IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`, `INTENT_IR_ATTESTED_AUTHORIZATION_PLAN.md`, `LOGIC_INTENT_LEGAL_GATE_PLAN.md` | **historical plan** (landed) |
| Versioned refactor series | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v*.md`, `MASTER_REFACTORING_PLAN_2026.md` | **historical plan series** |
| Other domain plans | `docs/logic/*_PLAN.md` unless republished as a canonical leaf | **historical / plan** |
| Session / archive reports | `docs/archive/**`, old “project complete” slogans | **archive / historical** |

**Relabel rule (normative):** do not cite historical plans as the current
syntax, family, or consumer contract. Prefer this leaf, the family/namespace
registries, syntax-core contracts, and conformance tests.

## 10. Public examples and documentation migration

Public examples must:

1. Import from `ipfs_datasets_py.logic.api` or stable submodule paths that
   exist under the validation interpreter.
2. Use **canonical** family/namespace labels when writing artifacts.
3. Dual-read legacy labels only with explicit migration diagnostics.
4. Never claim theorem or authorization authority from conversion alone.

Failing public examples are recorded as `failing_public_example` gaps with
owner scope pointing at the documentation path and the public surface they
exercise. Repair is owner-scoped; this discovery task does not rewrite every
tutorial in bulk.

## 11. Extension recipes

| Need | Recipe |
| --- | --- |
| New core connective / binder | Extend `NodeKind` + algebra + this §5.2 catalog in the same change set |
| New family extension construct | `LogicExtensionNode@1` with versioned payload schema; document under §5.2 |
| New notation or profile | Register under the correct namespace; dual-read aliases only |
| New consumer | Dual-read inputs; canonical-write outputs; appear under closure scan roots |
| New gap from matrix/corpus | Leave typed gap for LFP-046; do not silently widen seed task paths |

## 12. Decision guide

```text
Writing a label into an artifact?
  → canonical namespace value only (dual-read first if legacy input)

Is a string a family?
  → only if registered under namespace family
  → smt/lean/safety/VC/runtime are never families

Is a plan document authority?
  → only canonical leaves under docs/architecture/logic/
  → *_PLAN.md and versioned refactor dumps are nonnormative

Found drift?
  → record owner-scoped typed gap via LogicConsumerClosure@1
  → LFP-046 drains to zero-drift; LFP-045 does not claim fixed point
```

## 13. Validation

| Check | Command / surface |
| --- | --- |
| Consumer-family static closure | `cd ipfs_datasets_py && python -m pytest -q tests/conformance/logic/test_consumer_family_closure.py` |
| Public dual-read migration | `tests/conformance/logic/test_public_api_migration.py` |
| Registry / generated catalog closure | `tests/conformance/logic/test_registry_closure.py` |

## 14. Summary

- **Normative** syntax and family contracts live here and in the live
  `syntax_core` / `families` packages.
- **Controlled syntax** is a closed documented catalog; omissions are typed
  gaps.
- **Consumers** dual-read legacy labels and write canonical identities only.
- **Static closure** records unregistered emitted IDs, undocumented
  controlled syntax, stale consumers, and failing public examples as
  owner-scoped typed gaps.
- **Historical plans are nonnormative.**
- **LFP-046**, not LFP-045, requires the drained zero-drift fixed point.

# Compilers, decompilers, and semantic round trips

| Field | Value |
| --- | --- |
| Interface | `SemanticRoundTripArchitecture@1` |
| Task | `IPFSDOC-041` |
| Status | `canonical` |
| Owner | architecture / logic |
| Source of truth | `ipfs_datasets_py/logic/formalization/`; `ipfs_datasets_py/logic/legal_ir/` (`canonical_contracts`, `canonical_compiler`, `canonical_decompiler`, `canonical_roundtrip`, `adapter`); `ipfs_datasets_py/logic/fol/`; `ipfs_datasets_py/logic/flogic/`; `ipfs_datasets_py/logic/TDFOL/`; `ipfs_datasets_py/logic/CEC/`; `ipfs_datasets_py/logic/deontic/`; `ipfs_datasets_py/logic/modal/`; `ipfs_datasets_py/logic/bridge/`; `benchmarks/semantic_roundtrip/`; `docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json`; [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md); [semantic_roundtrip_canonical_compiler.md](../semantic_roundtrip_canonical_compiler.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, benchmark operator |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md), [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | when compiler/decompiler contracts, view registries, or parity-policy CIDs change |

## 1. Purpose

This guide answers: **how canonical intermediate representations (IRs) are
compiled into formal logic views, how those views are linked and identity-pinned,
how source-withheld decompilation reconstructs text, and how semantic
round-trip evaluation measures equivalence without confusing parse success or
string similarity with proof.**

It is the companion leaf to
[IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md). That document owns
kernel identity, provenance roles, and non-interchangeable authority classes.
This document owns **bidirectional formalization**, multi-view lowering,
source maps, abstention/partial semantics, and the measured round-trip
composition.

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place compile/decompile work without inventing a second IR kernel or collapsing proof with reconstruction |
| **Compiler / decompiler author** | Respect source-withholding, exact interface pins, and fail-closed unsupported semantics |
| **Benchmark operator** | Reproduce L1/T1/L2 coordinates under the frozen parity policy CID |
| **Security / policy reviewer** | Separate source maps (evidence) from decompiler inputs; refuse silent source leakage |
| **Downstream prover docs** | Consume formalization artifacts as declarations, not as theorem authority |

## 3. Scope and non-goals

### In scope

- **Canonical structured-text IR** and its measured compiler/decompiler/
  round-trip composition (`Canonical*@1` interfaces).
- **Domain-neutral formalization contracts**: samples, view registry, formulas,
  symbol tables, cross-view links, compiler config, and formalization artifacts.
- **Logic family views**: FOL, F-logic / frame logic, event calculus / CEC /
  DCEC, TDFOL, deontic, graph projection, structural decompiler, and external
  prover routing surfaces as they appear in current packages and adapters.
- **Source maps** and **cross-view identities** (relations, preserved
  properties, CID-bound artifacts).
- **Source-withholding**, deterministic reconstruction, ambiguity surfaces,
  **abstain** vs **explicit partial** semantics.
- **Equivalence policy**: structural IR metrics, cycle/end-to-end loss, and
  the frozen parity policy (exact interface and CID pins).
- Explicit boundary: **parsing and string similarity are not semantic proof**.

### Non-goals

- Kernel canonicalization and authority kinds (owned by
  [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md)).
- External prover install recipes, portfolio routing matrices, or capability
  taxonomies (later logic leaf `EXTERNAL_PROVERS.md`).
- Governed authorization, ZKP attestation profiles, or result-authority
  substitution rules (later logic leaves under IPFSDOC-G062).
- Promoting research benchmark arms or model-guided constructors into
  production without a separately frozen experiment and new interface version.
- Treating embedding cosine scores, token overlap, or NL paraphrase quality as
  theorem or policy authority.

## 4. Mental model

```text
  source text (raw CID)
        │
        │  compiler  (sees source + vocabulary + policy)
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  canonical semantic IR  +  source-map receipt  +  diags │
  │  (rules / formalization artifact / multi-view formulas) │
  └───────────────────────┬─────────────────────────────────┘
                          │
          ┌───────────────┼───────────────────────────────┐
          │               │                               │
          ▼               ▼                               ▼
   FOL / TDFOL      F-logic / frame               CEC / DCEC /
   deontic lowering   relations                   event calculus
          │               │                               │
          └───────────────┼───────────────────────────────┘
                          │  CrossViewLink + shared symbol table
                          │  (cross-view identities; not proof)
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │  formalization artifact (CID-addressed)                 │
  │  formulas · obligations · source_map · diagnostics      │
  └───────────────────────┬─────────────────────────────────┘
                          │
                          │  SOURCE WITHHELD boundary
                          │  (no source text, source map, gold IR,
                          │   constructor record, or path leaks)
                          ▼
                    decompiler / realizer
                          │
                          ▼
               reconstructed text (raw CID)
                          │
                          │  re-compile (optional L2)
                          ▼
               second IR  →  structural equivalence metrics
```

**Compile is not prove. Decompile is not prove. Round-trip loss is not
theorem authority.** A successful reconstruction shows that a measured
composition preserved declared structural facets under a pinned policy. It does
not establish that natural language was legally correct, that a prover
discharged an obligation, or that two surface strings are “the same meaning”
because they look alike.

## 5. Layers of compilation

The repository maintains several compilation layers that must stay
distinguishable:

| Layer | Owns | Primary packages | Produces |
| --- | --- | --- | --- |
| **Kernel identity** | Canonical bytes, CIDs, provenance roles | `logic.ir_core` | Stable declaration digests/CIDs |
| **Domain-neutral formalization** | Samples, views, formulas, cross-view links, compiler protocol | `logic.formalization` | `FormalizationArtifact` |
| **Legal adapter / measured canonical path** | Typed deontic projection, source maps, source-withheld paraphrase | `logic.legal_ir` | `CanonicalRoundTripIR`, compiler/decompiler results |
| **Logic family engines** | FOL, F-logic, TDFOL, CEC/DCEC, deontic, modal parsers | `logic.fol`, `flogic`, `TDFOL`, `CEC`, `deontic`, `modal` | Family-native formulas and bridge views |
| **Bridge / multiview** | Shared `LegalIRDocument` + `LogicIRView` envelope for evaluation | `logic.bridge` | Multi-view documents, round-trip metrics envelopes |
| **Benchmark contracts** | Source-withheld constructor/realizer boundary, loss metrics, parity | `benchmarks/semantic_roundtrip` | Coordinate results, selection gates |

Adapters may lower domain samples into formalization ports. Family engines may
be invoked behind bridges. **None of these layers may silently redefine
another layer’s CID preimage or authority kind.**

## 6. Canonical semantic IR (measured v1)

### 6.1 Shape and identity

The production-measured semantic payload for the structured-text round trip is
exactly a rules array. Schema package path:

`ipfs_datasets_py/logic/legal_ir/schemas/canonical_roundtrip_ir.schema.json`

Semantic payload:

```json
{
  "rules": [
    {
      "modality": "O",
      "actor": "permit_holder",
      "action": "file",
      "object": "notice",
      "conditions": ["work_begins"],
      "exceptions": [],
      "temporal": ["within_10_days"]
    }
  ]
}
```

| Contract | Pin |
| --- | --- |
| Interface | `CanonicalRoundTripIR@1` |
| Schema version | `ipfs-datasets.canonical-roundtrip-ir.v1` |
| IR CID | `cid_for_dag_json({"rules": [...]})` (CIDv1 / base32 / sha2-256) |
| Rule CID | DAG-JSON CID of the exact seven-field rule object |
| Text CID | raw codec over UTF-8 bytes |

Modality is the reviewed deontic operator set `{O, P, F}`. Holdings,
assertions, and non-deontic operators are **unsupported/new-version**
semantics, not free-form modality strings. Open vocabulary atoms (actor,
action, object, qualifiers) are caller-supplied; the production API must not
treat the five frozen benchmark vocabularies as a legal ontology.

Canonical ordering of rules and qualifier arrays is defined by the shared
Python contract so equivalent construction order yields one DAG-JSON identity
while **multiplicity-bearing duplicate rules are retained**.

### 6.2 Measured composition path

```text
structured text
    │  CanonicalStructuredTextCompiler@1
    ▼
canonical {"rules":[...]} IR + source-map receipt + diagnostics
    │  source map and originating text are withheld
    ▼
canonical {"rules":[...]} IR only
    │  CanonicalStructuredTextDecompiler@1
    ▼
reconstructed text + attribution receipt
    │  re-compile (round-trip stage)
    ▼
L2 IR for structural comparison
```

Default pipeline is deliberately **deterministic**: no guidance model, no
repair model, no model receipt on the selected v1 traces. Structural
validation backends (for example Hammer/cvc5 or Lean) may check artifacts
**after** production; they must not alter candidates or scores on this path.

### 6.3 Exact interface and version pins (canonical path)

| Symbol / interface | Role |
| --- | --- |
| `CanonicalStructuredTextCompiler@1` | Source → IR + source map |
| `CanonicalStructuredTextDecompiler@1` | Source-withheld IR → text |
| `CanonicalRoundTripContracts@1` | Shared request/result/error/policy contracts |
| `CanonicalRoundTripIR@1` | Semantic IR object + CID rules |
| `CanonicalRoundTripParityPolicy@1` | Frozen evaluation policy identity |
| `TypedDeonticCanonicalConstructor@1` | Selected constructor arm interface |
| `SourceWithheldCanonicalParaphraser@1` | Selected realizer arm interface |
| `CanonicalDecompilerAttribution@1` | Deterministic attribution receipt schema |
| Schema `ipfs-datasets.canonical-roundtrip-ir.v1` | IR schema version string |
| Schema `ipfs-datasets.semantic-roundtrip-canonical-parity-policy.v1` | Parity policy schema |
| Schema `ipfs-datasets.canonical-semantic-roundtrip-result.v1` | Round-trip result schema |

Changing field meaning, CID scope, canonical ordering, source-withholding
rules, terminal-status invariants, or policy comparison semantics is a
**breaking change** requiring a new interface/schema version.

### 6.4 Exact CID pins (lineage and policy)

These CIDs are content-addressed evidence and configuration identities from
the current tree. Agents must recompute rather than invent new pins.

| Name | CID | Scope |
| --- | --- | --- |
| Canonical design gate | `baguqeerab4top4ljgojms7f7p6y4ksdlivfwhyzxzhynnii4zbrfvw4mqtfq` | SRT design authorization |
| Replacement report | `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga` | Selected measurement report |
| Replacement selection gate | `baguqeerawhggoyrnacv74kbuq3rhpmz4jikhr3tnv5uahpxcnpghfrwfj6jq` | Selection gate |
| Implementation representative arm | `baguqeeraylvbngffosmvcvwowelspcdbbk5wom5itjvfanbzty4eioxsauhq` | Arm identity |
| Tied selective arm | `baguqeeraaslupqmtxclda2ml7ppssprxecn64wwywehq6x6tfz6vd73zr32q` | Exact tie peer |
| Selected constructor adapter (raw) | `bafkreig2yeibug44tbffleyvju4zvo62thdqkpht3n2qn6guefkvbv7z2a` | Adapter bytes |
| Selected realizer adapter (raw) | `bafkreifrmafgdy5wajq7sepxxatwc2mnnubqt2c7kwped456vukyptfi6y` | Adapter bytes |
| Source-withheld decompiler config | `baguqeeratlk326nodsva4rxwm65xgnpenhcovspm7crtyd4enaqhgjciqayq` | Frozen config DAG-JSON |
| Source-withheld rendering spec | `baguqeera72pqowlkovfqvydbtk5lxc7g42o75xtfgmx7cm4vqdvnaimjpjvq` | Rendering-spec DAG-JSON |
| Canonical parity policy | `baguqeera5g5z4yvncxbn3uk4ftqmnxxmmclwpnwjpdshiy52la2o5bzdk27a` | Policy document without `policy_cid` |
| SRT-014 report (negative evidence) | `baguqeerakqgerwv6npdlqpgrc3bjzuxqog3hiouey3c4giw5vkdgk2jhfbpq` | Prior no-eligible outcome |
| SRT-014 remediation manifest | `baguqeerarr7ebjrzd3argtdekd7er3bqrnvhuzy2ogqzfi7h5nv37dbea52a` | Immutable remediation |

Selection basis is `replacement_bounded_tie_policy`. The implementation
representative is the first arm in frozen preregistered order; the evidence
records an **exact tie**, not a unique semantic winner. The representative is
**not** asserted to be semantically superior.

Policy file (checked-in source of the parity CID):

`docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json`

## 7. Multi-view formalization (domain-neutral)

### 7.1 Contracts

| Schema / type | Version pin | Role |
| --- | --- | --- |
| `FormalizationView` | `formalization-view/v1` | Registered output representation + capabilities |
| `ViewRegistry` | `formalization-view-registry/v1` | Exact-ID resolution + stable registry identity |
| `FormalFormula` | `formal-formula/v1` | Source-grounded formula in one view |
| `SymbolTable` / `FormalSymbol` | `formal-symbol-table/v1` | Shared symbols across views |
| `CrossViewLink` | `formal-cross-view-link/v1` | Typed link between formulas in **different** views |
| `FormalizationCompilerConfig` | `formalization-compiler-config/v1` | Compiler id/version, target views, unsupported policy |
| `FormalizationArtifact` | `formalization-artifact/v1` | Content-addressed compile product |
| `UnsupportedSemanticsDiagnostic` | `unsupported-semantics/v1` | Explicit unsupported-semantics record |

`FormalizationCompiler.compile(sample, config) -> FormalizationArtifact`
invokes **no** model, solver, or prover. An artifact declares formulas and
proof **obligations**; it does **not** claim any obligation has been proved.

### 7.2 Cross-view relations and identities

`CrossViewRelation` enumerates declared semantic relationships:

| Relation | Meaning |
| --- | --- |
| `equivalent` | Claimed mutual correspondence under stated preserved properties |
| `lowers_to` | Source formula lowers into a more concrete target view |
| `refines` / `abstracts` | Directional precision change |
| `preserves` | Named properties are intended to be preserved across the link |
| `contradicts` | Explicit conflict between views (diagnostic, not silent overwrite) |
| `corresponds_to` | Weaker correspondence without full equivalence claim |

Cross-view links:

- require **distinct** formula IDs in **distinct** views;
- bind optional `preserved_properties` (for example operator force, event
  identity, quantifier scope);
- must be source-grounded when spans/refs are declared on the artifact;
- participate in the artifact’s content identity.

**A `CrossViewLink` is not a theorem.** Equivalence links record intended
correspondence under the compiler’s reviewed mapping. Discharge of that
correspondence by a prover is a separate result with separate authority.

### 7.3 Unsupported semantics policy (formalization)

`UnsupportedSemanticsPolicy`:

| Policy | Behavior |
| --- | --- |
| `error` | Fail closed; refuse to emit a falsely complete artifact |
| `preserve_opaque` | Emit opaque formula placeholders with diagnostics |

Silent drop of unrepresentable facets is forbidden under both policies.

## 8. Trace: canonical IR through logic-family views

This section maps how a grounded legal (or shared) declaration flows into
family views present in the current tree. View **contract IDs** for the Legal
formalization adapter are exact versioned strings; family engines also expose
native modules that adapters may route into.

### 8.1 Legal formalization view registry (v1 contract IDs)

| View contract ID | Logic family | Target / engine surface | Preservation rules (capabilities) |
| --- | --- | --- | --- |
| `legal-ir-view/deontic/v1` | `deontic` | `deontic.ir` | `operator_force`, `prohibition_polarity`, `condition_scope`, `exception_precedence` |
| `legal-ir-view/frame-logic/v1` | `frame_logic` | `modal.frame_logic` | `typed_role`, `relation_direction`, `modal_operator`, `exception_scope` |
| `legal-ir-view/tdfol/v1` | `temporal_first_order` | `TDFOL.prover` | `quantifier_scope`, `temporal_anchor`, `event_order`, `deontic_force` |
| `legal-ir-view/cec/v1` | `event_calculus` | `CEC.native` (aliases: `event_calculus`, `dcec`) | `event_identity`, `fluent_identity`, `transition_direction`, `time_anchor` |
| `legal-ir-view/knowledge-graphs/v1` | `graph_projection` | Neo4j-compatible projection | `endpoint_identity`, `edge_direction`, `edge_type`, `provenance_identity` |
| `legal-ir-view/external-provers/v1` | `proof_translation` | prover router | `input_formula_id`, `modal_operator`, `type_encoding`, `route_status`, `trust_boundary` |
| `legal-ir-view/decompiler/v1` | `structural_round_trip` | `modal.ir_decompiler` | `formula_identity`, `operator_force`, `predicate_signature`, `argument_roles`, `condition_scope`, `exception_scope` |

Registry identity: `legal-ir-formalization-views` /
`legal-ir-formalization-adapter/v1`. Adapter producer id:
`legal-ir-formalization-adapter`.

### 8.2 FOL (first-order logic)

| | |
| --- | --- |
| **Package** | `ipfs_datasets_py.logic.fol` |
| **Role** | NL/text → first-order formulas (predicates, quantifiers); export formats such as JSON, Prolog, TPTP |
| **Bridge** | `logic.bridge.fol_tdfol` lowers legal IR into TDFOL-oriented first-order structure with deontic operator aliases (`obligation`→`O`, …) |
| **Relation to canonical IR** | Canonical v1 rules are a **restricted deontic atom projection**, not full FOL. FOL conversion may enrich or re-encode norms; it must not claim identity with `CanonicalRoundTripIR` unless an explicit cross-view link and versioned mapping say so |
| **Not proof** | Successful parse/conversion, ML confidence scores, and formula pretty-printing are **not** theorem results |

### 8.3 F-logic / frame logic

| | |
| --- | --- |
| **Package** | `ipfs_datasets_py.logic.flogic` (+ optional ErgoAI submodule) |
| **Role** | Frame/object-oriented logic: typed attributes, classes, inheritance, ontology frames |
| **View pin** | `legal-ir-view/frame-logic/v1` (`frame_logic`) |
| **Bridge** | `logic.bridge.modal_frame_logic` and modal registry family `frame` |
| **Relation to canonical IR** | Frame roles may ground actor/action/object slots; frame structure is richer than the seven-field rule. Lowering that loses role direction or modal operator force must surface as unsupported or partial, not silent collapse |
| **Not proof** | Ontology load success or ErgoAI availability is a capability/status fact, not a proof of a claim |

### 8.4 Event calculus, CEC, and DCEC

| | |
| --- | --- |
| **Package** | `ipfs_datasets_py.logic.CEC` (native preferred; DCEC wrappers and NL compilers) |
| **Role** | Event calculus predicates (`Happens`, `HoldsAt`, `Initiates`, `Terminates`, …), cognitive event calculus (DCEC) state predicates, NL→policy/DCEC compilers |
| **View pin** | `legal-ir-view/cec/v1` with logic family `event_calculus` and aliases including `dcec` |
| **Bridge** | `logic.bridge.cec_dcec` canonicalizes event predicates and DCEC state kinds |
| **Relation to canonical IR** | Temporal facets on rules (`temporal`, conditions) may lower to time anchors and events; full lifecycle fluents are outside seven-field IR and require CEC view formulas or a new schema version |
| **Not proof** | ShadowProver / Talos / native prover **attempts** are backend results under bounds; compilation into CEC syntax alone is not a proof |

### 8.5 TDFOL (temporal deontic first-order logic)

| | |
| --- | --- |
| **Package** | `ipfs_datasets_py.logic.TDFOL` |
| **Role** | Unified FOL + deontic (`O`/`P`/`F`) + temporal operators; parser, prover strategies, DCEC/FOL converters |
| **View pin** | `legal-ir-view/tdfol/v1` (`temporal_first_order`) |
| **Bridge** | `logic.bridge.fol_tdfol` |
| **Relation to canonical IR** | Canonical rules are a measured subset of deontic structure. TDFOL formulas may add quantifiers and temporal operators; round-trip **identity** with canonical IR requires structural projection, not string equality of formula text |
| **Not proof** | Tableau expansion, strategy coverage, or countermodel visualization artifacts are not interchangeable with theorem authority without a typed proof result |

### 8.6 Deontic and modal IR (adjacent surfaces)

| Surface | Package | Notes |
| --- | --- | --- |
| Deontic IR | `logic.deontic` | Normative force, knowledge base, formula builders; feeds measured typed-deontic constructor |
| Modal compiler/decompiler | `logic.modal` | Deterministic modal IR compile; decompiler keeps provenance-backed reconstruction separate from formula audit metadata |
| Ambiguity policy | modal registry / compiler packets | Surfaces contested family pairs for advisor/human review; **does not** use adaptive weights to decide canonical IR on the measured path |

### 8.7 Related views

| View | Use |
| --- | --- |
| Knowledge-graph projection | Typed nodes/edges for GraphRAG-adjacent analysis; provenance identity preserved separately from edge labels |
| External provers | Route formulas to backends with trust-boundary and route-status fields (details in external-provers leaf) |
| Structural decompiler view | Deterministic reconstruction contract without copied source text |

## 9. Source maps

### 9.1 What a source map is

A **source map** binds IR constituents (rules, formula fields, symbols) to
**source references and spans**. In the formalization artifact it is a
`Provenance` instance (`source_map` field). In the measured canonical
compiler it is a source-map **receipt**: DAG-JSON CID over request CID,
canonical IR CID, and every entry.

Source-map entry properties (canonical compiler):

- half-open character offsets `[start, end)` in Unicode character space;
- tied to the **raw source CID** (not to a filesystem path as identity);
- field path into the IR rule/object;
- evidence for reviewers and diagnostics.

### 9.2 What a source map is not

| Source map is | Source map is **not** |
| --- | --- |
| Compiler evidence and audit trail | Decompiler input |
| Grounding for formulas and diagnostics | Authorization to fetch or re-materialize source into a realizer |
| Part of formalization artifact identity (via provenance) | Proof that the mapping is legally correct |
| Span pointers | Permission to leak source through nested config keys |

**Source maps travel beside the semantic IR in compiler results; they must
never be required fields on decompiler requests.**

### 9.3 Formalization grounding rules

Every `FormalFormula` must carry `source_ref_ids` and/or `span_ids`. The
artifact validator requires:

- formulas and links only reference registered views and known symbols;
- `source_map` binds the sample or declaration id;
- each formula’s sources/spans agree with its `source_map` binding;
- input node ids resolve to grounded subjects.

Dangling IDs fail closed.

## 10. Source-withholding

### 10.1 Boundary rule

Decompilation and realization evaluate **semantic reconstruction** only if the
realizer cannot see the original surface form. The measured contract therefore
**withholds** source channels.

`DecompilerRequest` / realizer payload may contain only:

- canonical semantic IR (and its reproducible IR CID);
- request id;
- parity-policy CID;
- bounded public configuration;
- optional open atom vocabulary where the public contract allows it.

### 10.2 Forbidden channels (non-exhaustive contract set)

Implementations reject nested or top-level keys including (see
`canonical_contracts` / benchmark contracts for the full frozenset):

`source`, `source_text`, `source_body`, `source_map`, `source_cid`,
`source_path`, `source_cache`, `source_uri`, `gold`, `gold_ir`,
`prior_reconstruction`, `native_ir`, `constructor_record`, `compiler_record`,
`parse`, `parse_tree`, and related private payloads.

The implementation must not resolve the source CID, query an external content
store for the originating text, or inspect compiler-private state.

Violation class: `SOURCE_WITHHOLDING_VIOLATION` /
source-copy exclusion eligibility gate failure.

### 10.3 Why withholding matters

Without withholding, “round trip” collapses to **source copy** or
near-copy—string similarity can look perfect while the IR path is untested.
Withholding forces reconstruction from IR atoms and frozen rendering grammar
only. That is a **semantic reconstruction experiment**, still not a legal
proof.

## 11. Deterministic reconstruction (decompilation)

### 11.1 Selected v1 realizer profile

| Field | Value |
| --- | --- |
| Interface | `SourceWithheldCanonicalParaphraser@1` / `CanonicalStructuredTextDecompiler@1` |
| Profile | `typed_deontic_must_paraphrase_v1` |
| Atom surface | `underscore_to_space_v1` |
| Obligation / permission / prohibition | `must` / `may` / `must not` |
| Temporal position | `before_conditions` |
| Condition / exception connectors | `if` / `unless` |
| Rule order | `canonical_rule_ir_v1` |
| Config CID | `baguqeeratlk326nodsva4rxwm65xgnpenhcovspm7crtyd4enaqhgjciqayq` |
| Rendering-spec CID | `baguqeera72pqowlkovfqvydbtk5lxc7g42o75xtfgmx7cm4vqdvnaimjpjvq` |
| Deterministic | **yes** (no model receipt on success) |
| Stateless | **yes** |

### 11.2 Success criteria

`DecompilerResult` succeeds only with:

- nonblank UTF-8 reconstructed text;
- matching raw text CID;
- deterministic component attribution;
- no error object.

Future learned realizers require a **new** reviewed interface/configuration
and must expose model receipt CIDs rather than silently replacing this path.

### 11.3 Modal / structural decompilers

`logic.modal.decompiler` keeps two products separate:

1. **Decoded text** — provenance-backed reconstruction used for diagnostics;
2. **Formula/operator/predicate metadata** — audit evidence, not proof.

Structural round-trip view `legal-ir-view/decompiler/v1` records the
preservation capabilities expected of deterministic reconstruction.

## 12. Ambiguity

Ambiguity is a **first-class diagnostic state**, not a license to invent a
unique winner.

| Mechanism | Behavior |
| --- | --- |
| Modal ambiguity signals / family ranking | Surfaces contested modal families (deontic, temporal, frame, epistemic, …) for policy tables and advisor packets |
| Adaptive ambiguity pairs (research) | May request neural/human advisor; measured canonical path does **not** use adaptive weights to decide IR |
| Legal adapter ambiguity | `LegalIRAdapterError` when a sample cannot be projected without ambiguity under reviewed mapping |
| Compiler diagnostics | Structured codes with optional source spans; warnings never become silent successes |
| Exact-tie selection | Design gate records exact tie; representative chosen by frozen order, not superiority claim |

Agents must not collapse multi-candidate parses into a single IR identity
without an explicit reviewed decision record in provenance/manifest metadata.

## 13. Abstention and explicit partial semantics

### 13.1 Unsupported disposition (canonical compiler)

| Disposition | When | Result shape |
| --- | --- | --- |
| `abstain` | Semantics cannot be faithfully represented; request does not opt into partial | Status `abstained`; structured `unsupported_semantics` error; **no** IR presented as success |
| `explicit_partial` | Request set `allow_explicit_partial=True` and only a disclosed subset is supported | Success-like partial only when partial regions remain **enumerated**; never presented as complete |

Invalid input, missing components, component exceptions, empty output,
unsupported semantics (when abstaining), policy mismatch, and source-
withholding violations are **terminal typed errors**. There is no silent
fallback to another constructor, model, vocabulary, or policy.

### 13.2 Operation statuses

| `OperationStatus` | Meaning |
| --- | --- |
| `success` | Complete (or explicitly partial when allowed) result meeting contract |
| `abstained` | Supported path refused to invent unsupported meaning |
| `failed` | Invalid request/IR, component failure, empty output, policy mismatch, withholding violation |

Error codes include: `invalid_request`, `invalid_ir`,
`unsupported_semantics`, `policy_mismatch`, `component_unavailable`,
`component_failed`, `source_withholding_violation`, `empty_output`.

### 13.3 Round-trip orchestration note

`canonical_roundtrip` may enable partial disclosure on intermediate compile
stages for multi-facet pilot documents so systems can surface unsupported
diagnostics without systematic total abstention—while still enumerating
partial regions and refusing to claim full coverage when facets are missing.
Benchmark **eligibility gates** (`full_coverage`, polarity, source-copy
exclusion) remain independent and fail closed when incomplete.

## 14. Equivalence policy

### 14.1 What counts as semantic equivalence measurement

Round-trip **equivalence** for the measured canonical IR is defined on
**structured IR objects**, not on surface text:

| Loss | Definition (protocol) |
| --- | --- |
| **Forward** | Gold IR vs L1 (constructor output) structural loss |
| **Cycle** | L1 vs L2 (recompiled after decompile) structural loss |
| **End-to-end (primary)** | Gold IR vs L2 structural loss |

`compare_semantic_ir` / `semantic_score` use frozen field weights:

| Field | Weight |
| --- | --- |
| `modality` | 0.25 |
| `actor` | 0.15 |
| `action` | 0.20 |
| `object` | 0.10 |
| `conditions` | 0.10 |
| `exceptions` | 0.10 |
| `temporal` | 0.10 |

List fields use set Jaccard-style scores under the frozen metric module.
Failed/missing/blank/empty coordinates receive **loss one**.

### 14.2 Parity / noninferiority policy (exact pin)

| Field | Value |
| --- | --- |
| Interface | `CanonicalRoundTripParityPolicy@1` |
| Schema | `ipfs-datasets.semantic-roundtrip-canonical-parity-policy.v1` |
| Policy CID | `baguqeera5g5z4yvncxbn3uk4ftqmnxxmmclwpnwjpdshiy52la2o5bzdk27a` |
| CID scope | `document_without_policy_cid` |
| Metric | `end_to_end_loss` (lower is better) |
| Comparison | `canonical_minus_selected` |
| Aggregation | repeats within case, then unweighted macro average across cases |
| Bootstrap | seeded percentile case-cluster; seed `17291`; 10,000 samples; 95% CI |
| Decision | upper confidence bound ≤ noninferiority margin |
| Margin | `0.03` (frozen before parity run; not fitted post hoc) |
| Failure loss | `1.0` |
| Eligibility gates | `source_copy_exclusion`, `polarity_preservation`, `full_coverage` |

This policy tests **parity** of a candidate composition against the selected
baseline under frozen cases. It does **not** establish correctness on caselaw
outside those cases and does **not** authorize production promotion by itself.

### 14.3 Parsing and string similarity are not semantic proof

The architecture makes the following distinctions mandatory:

| Observation | May support | Must **not** be called |
| --- | --- | --- |
| Parser success / AST construction | That a string is syntactically admitted by a grammar | Semantic proof, legal correctness, or theorem authority |
| Token overlap, edit distance, BLEU, embedding cosine, paraphrase similarity | Surface reconstruction diagnostics or research side metrics | Semantic equivalence proof of IR meaning or legal identity |
| Pretty-printed formula equality | Presentation identity | Canonical IR identity (use DAG-JSON / profile CIDs) |
| Source-copy match under withheld realizer | Cheating / gate failure | Successful semantic round trip |
| Structural IR metric score | Measured reconstruction quality under a pinned policy | Proof that obligations hold or that policy may authorize action |
| Prover `ProofResult` under bounds | Theorem authority **only** under proof policy | Automatically granted by a low round-trip loss |

**Parsing and string similarity must not be called semantic proof.** Semantic
round-trip evaluation is an **IR-structural** discipline under explicit
withholding and pinned metrics. Theorem, satisfiability, monitor, evidence,
and policy authorities remain non-interchangeable
([IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) §9).

## 15. End-to-end stage map (measured round trip)

| Stage | Name | Input | Output | Sees source? |
| --- | --- | --- | --- | --- |
| L1 | `l1_compile` | Source text + vocabulary + policy | Canonical IR + source map + diagnostics | **Yes** |
| T1 | `t1_decompile` | Canonical IR + policy + public config only | Reconstructed text + attribution | **No** (withheld) |
| L2 | re-compile | T1 text + same vocabulary/partial flags | Second IR | Yes (text is reconstruction, not original) |

`CanonicalSemanticRoundTrip` (package orchestration) builds a **fresh**
`DecompilerRequest` from L1 only—no compiler provenance, source map, or
caller request object is threaded through. Terminal stages and errors are
prefix-ordered; successful runs require three successful stages; model
receipts are forbidden on the measured deterministic profile.

## 16. Benchmark vs production boundaries

| Concern | Benchmark (`benchmarks/semantic_roundtrip`) | Production (`logic.legal_ir` measured path) |
| --- | --- | --- |
| Vocabulary | Frozen case public vocabularies as **conformance inputs** | Caller-supplied reviewed domain vocabulary |
| Caps | Experimental caps (for example 16 rules in contracts) | Operational DoS bounds (larger; not ontology) |
| Constructors | Matrix of arms (typed deontic, model-based research arms) | Default: measured typed-deontic deterministic |
| Realizers | Source-withheld paraphraser and research arms | Default: source-withheld deterministic decompiler |
| Gold IR | Evaluation reference for loss | Not available to decompiler |
| Promotion | Selection gates + design CIDs | Separate review; design gate does not auto-promote |

Importing benchmark fixtures as production legal ontology is a contract
violation of intent even if types happen to align.

## 17. Versioning and breaking-change rules

A new **interface major** (`@2`, schema `…/v2`, or new view contract id) is
required when any of the following change:

- semantic meaning of IR fields or modality inventory;
- CID codec, scope, or canonical ordering rules;
- source-withholding key set or decompiler request shape;
- abstain vs explicit-partial terminal semantics;
- equivalence metric weights, aggregation order, or parity decision rule
  (policy CID must change in lockstep);
- cross-view relation vocabulary in a non-additive way;
- selection of a non-deterministic default realizer without model-receipt
  visibility.

Additive diagnostics and non-CID telemetry may evolve outside identity
preimages. Optional learned stages require separately frozen experiments and
new version pins before becoming defaults.

## 18. Worked source-grounded path (checklist)

Use this checklist when claiming a complete compile / check / reconstruct
path for evidence:

1. **Bind source** — raw CID (or formalization `SourceRef` + spans); no bare
   path identity.
2. **Compile** — deterministic compiler or formalization adapter with pinned
   `compiler_id` / `compiler_version` / config CID.
3. **Emit IR / formulas** — canonical rules and/or view formulas with symbol
   table; record unsupported facets.
4. **Source map** — every formula/rule field that claims grounding has map
   entries; receipt CID computed.
5. **Cross-view links** — if multiple views emitted, links declare relation
   and preserved properties; no silent view collapse.
6. **Withhold** — construct decompiler request from IR only; reject forbidden
   keys.
7. **Decompile** — deterministic reconstruction; attribution receipt; text
   CID.
8. **Re-compile (optional L2)** — same vocabulary and partial policy.
9. **Equivalence** — structural IR metrics and/or parity policy comparison;
   record losses and gates.
10. **Separate proof** — if obligations were checked, attach typed
    `ProofResult` / receipts under proof authority; never infer them from
    reconstruction loss or string similarity.

## 19. Discrepancies and deferred items

| Item | Status |
| --- | --- |
| Full caselaw coverage beyond seven-field deontic IR | Deferred; requires new schema/version and frozen measurement |
| Model-guided constructors/realizers as production default | Research/benchmark only until new design gate |
| Automatic vocabulary induction | Outside measured v1; would be a new constructor stage |
| ErgoAI / optional provers always installed | Lazy/optional; absence is capability-unavailable, not proof failure |
| Cross-view `equivalent` auto-verified by solvers | Not implied; needs separate proof portfolio (external-provers leaf) |

## 20. Related documents

| Document | Relationship |
| --- | --- |
| [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) | Kernel identity, provenance, authority kinds (IPFSDOC-040) |
| [semantic_roundtrip_canonical_compiler.md](../semantic_roundtrip_canonical_compiler.md) | SRT design contract and evidence lineage detail |
| `docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json` | Frozen parity policy bytes / CID |
| External provers leaf (IPFSDOC-042) | Backend routing, lazy install, result taxonomy |
| Result authority / governed authorization leaves | Non-substitution of reconstruction for authorization |

## 21. Summary invariants

1. **One measured semantic IR shape** for the canonical structured-text path;
   multi-view formalization extends it without redefining its CID rules.
2. **Source maps are compiler evidence**; decompilers are **source-withheld**.
3. **Abstain** or **explicit partial** are the only honest answers to
   unrepresentable meaning—never silent drop.
4. **Cross-view links** record intended correspondence; they are not proofs.
5. **Equivalence** is structural IR comparison under pinned weights and
   policy CID; **parsing and string similarity are not semantic proof**.
6. **Exact interface, schema version, and CID pins** are part of the
   architecture, not optional metadata.
7. **Reconstruction success ≠ theorem authority ≠ policy authorization.**

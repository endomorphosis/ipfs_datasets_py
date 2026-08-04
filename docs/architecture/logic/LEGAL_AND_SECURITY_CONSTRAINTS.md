# Legal and Security constraint compilation and applicability

| Field | Value |
| --- | --- |
| Interface | `ConstraintProofArchitecture@1` |
| Task | `IPFSDOC-043` |
| Status | `canonical` |
| Owner | architecture / logic-policy |
| Source of truth | `ipfs_datasets_py/logic/formalization/constraint_contracts.py`; `ipfs_datasets_py/logic/legal_ir/` (`constraint_query`, `proof_cache`, `adapter`, canonical compiler path); `ipfs_datasets_py/logic/security_ir/` (`constraint_query`, `constraint_cache`, `formalization_adapter`, `model`); `ipfs_datasets_py/logic/proof_corpus/` (corpus, applicability, trust policy, revocation); `ipfs_datasets_py/logic/admissibility/profiles.py`; [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md); [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md); [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, legal/policy reviewer, operator |
| Related | [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow D, [LOGIC_INTENT_LEGAL_GATE_PLAN.md](../LOGIC_INTENT_LEGAL_GATE_PLAN.md), [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md) |
| Review cadence | when Legal/Security constraint contracts, applicability dimensions, corpus integrity rules, or trust/revocation policy change |

## 1. Purpose

This guide answers: **how Legal and Security norms become content-addressed
constraint artifacts, how hard applicability filters select them for a concrete
invocation, how modeled assumptions and coverage gaps remain explicit, and how
heuristic extraction stays non-authoritative until admitted.**

It is the constraint-and-applicability leaf for the logic-policy track. Proof
corpus attestation kinds, ZKP profiles, independent verification, redaction,
and release assurance are owned by
[PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md). Governed
authorization composition and result-authority taxonomy are later leaves
(`GOVERNED_AUTHORIZATION.md`, `RESULT_AUTHORITY.md`).

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place constraint work without inventing a second kernel or collapsing Legal into Security |
| **Legal / Security adapter author** | Emit `ConstraintArtifact@1` and domain applicability receipts without executing tools |
| **Gate / corpus integrator** | Load applicable constraints by exact roots under fail-closed profiles |
| **Security / policy reviewer** | Distinguish compilation, applicability, membership, proof, and policy allow |
| **Operator / release owner** | Understand what must be pinned (corpus, revocation, policy) before enforce |

## 3. Scope and non-goals

### In scope

- **Constraint compilation** from Legal IR and Security IR into solver-neutral
  `ConstraintArtifact@1` bundles (and domain-native cache rows).
- **Hard applicability** selection for a concrete invocation context
  (`LegalConstraintQuery@1`, `SecurityConstraintQuery@1`, shared
  `ApplicabilityEvidence@1`).
- **Domain caches**: Legal proof cache and Security constraint cache as
  offline/fixture sources that feed the unified proof corpus.
- **Modeled assumptions**, coverage gaps, open/closed world policy, and
  explicit `UNKNOWN` / `NOT_MODELED` outcomes.
- **Heuristic extraction** boundary: non-authoritative until admitted under
  review state and corpus promotion.
- **Trust and revocation policy** as it governs which constraint envelopes may
  be used as evidence (interface-level; verification details in the proof leaf).
- Linkage to **admissibility profiles** that require Legal and/or Security
  constraints (`legal-strict`, `security-lite`, `zkp-required`, `dev-offline`).

### Non-goals

- Kernel identity, CID profiles, and authority-kind enumeration (owned by
  [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md)).
- Semantic round-trip metrics and compiler parity CIDs (owned by
  [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md)).
- External prover install, hammer portfolio, or SAT/ITP lifecycle (owned by
  [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md)).
- Direct vs verifier-execution vs membership vs signature vs simulation
  attestation algebra, circuit/VK binding, and ZKP profile details (owned by
  [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md)).
- Pre-dispatch enforcement, one-time receipts, and rollout stages (later
  governed-authorization leaf / operator guide).
- Treating retrieval rank, embedding similarity, LLM confidence, or cache
  presence as Legal compliance or Security authorization.

## 4. Mental model

```text
  Legal corpus / Security declaration
           │
           ▼
  domain formalization adapter
  (canonical Legal path · Security formalization_adapter)
           │
           ▼
  ConstraintArtifact@1  +  domain-native cache row (CID)
           │
           │     invocation context
           │     (actor, jurisdiction, resource, effects, …)
           ▼
  hard applicability filters  ──► ApplicabilityEvidence@1
  (before any ranking budget)        │
           │                         │
           ▼                         ▼
  selected Legal + Security          coverage gaps /
  constraint sets                    UNKNOWN / NOT_MODELED
           │
           ▼
  proof corpus membership + trust/revocation
           │
           ▼
  admissibility inputs (never silent allow)
```

**Compilation produces declarations. Applicability scopes them. Proof and
policy decide authority. None of these steps may substitute for another.**

## 5. Package and interface map

| Package / path | Role | Primary interfaces |
| --- | --- | --- |
| `logic.formalization.constraint_contracts` | Domain-neutral constraint, applicability, and premise-selection contracts | `ConstraintArtifact@1`, `ApplicabilityEvidence@1`, `SelectedPremiseSet@1` |
| `logic.legal_ir.constraint_query` | Legal hard-scope selection and applicability receipts | `LegalConstraintQuery@1`, `LegalApplicabilityEvidence@1` |
| `logic.legal_ir.proof_cache` | Content-addressed Legal proof/constraint cache | Legal proof-cache envelope + integrity rehash |
| `logic.legal_ir` (canonical compiler/adapter) | Legal structured-text IR → formal views and obligations | `CanonicalCompiler@1` path (see compilers leaf) |
| `logic.security_ir.constraint_query` | Security hard-scope selection | `SecurityConstraintQuery@1`, `SecurityApplicabilityEvidence@1` |
| `logic.security_ir.constraint_cache` | Content-addressed Security constraint cache | `SecurityConstraintCache@1` |
| `logic.security_ir.formalization_adapter` | Security IR → formalization / constraint views | Security formalization adapter |
| `logic.proof_corpus` | Unified multi-family store, applicability, trust, revocation | `ProofCorpusStore@1`, `ProofTrustPolicy@1`, `ProofCorpusManifest@1`, `ProofRevocationSnapshot@1` |
| `logic.admissibility.profiles` | Profile knobs requiring Legal/Security/ZKP | `AdmissibilityProfile@1` |

Registry discovery:

```python
from ipfs_datasets_py.logic.submodule_registry import logic_submodule_spec

logic_submodule_spec("legal_ir")
logic_submodule_spec("security_ir")
logic_submodule_spec("proof_corpus")
logic_submodule_spec("admissibility")
```

## 6. Constraint compilation

### 6.1 Shared constraint artifact

`ConstraintArtifact@1` (`formalization.constraint_contracts`) is the
**solver-neutral** bundle consumed by caches, corpus, and gates. It binds:

| Binding | Purpose |
| --- | --- |
| Artifact / declaration identity | Content-addressed digests and CIDs under `ir_core` identity |
| Vocabulary / logic family | Declared family (deontic, policy, threat_model, smt, …) without silent cross-family concatenation |
| Statements with roles | `grant`, `prohibition`, `obligation`, `exception`, `invariant`, `assumption`, `claim`, `premise` |
| Obligations | Solver-neutral `ProofObligation` / `IRObligation` set |
| Native view bindings | Optional typed views (FOL, SMT, policy) linked by translation receipts |
| World policy | Open vs closed world for absence-of-fact semantics |
| Coverage gaps | Explicit incomplete modeling (`CoverageGap` / gap kinds) |
| Diagnostics | Structured, content-addressable diagnostics (not free-form authority) |

**Cross-family concatenation is forbidden.** Modal, Datalog, temporal, Hoare,
and SMT formulas must not be silently merged into one formula; cross-family
work requires an explicit translation/reconstruction receipt.

### 6.2 Legal compilation path

Legal reuses the measured formalization spine:

1. Source → Legal sample / structured IR (adapter; source review status explicit).
2. Canonical compiler → formal views and obligations
   (`legal_ir.canonical_compiler` / formalization ports).
3. Constraint query views → `LegalConstraintRecord` rows with jurisdiction,
   authority, temporal windows, definitions, exceptions, and premise provenance.
4. Optional proof-cache put → integrity-bound envelope with source digest,
   profile, jurisdiction, and theorem receipts when present.

Legal outcomes remain **Legal-domain**. They do not grant Security
authorization or execution admission by themselves.

### 6.3 Security compilation path

Security emits typed declarations (policy, resource, principal, channel, data
class, trust zone, …) through:

1. `SecurityIR` model + domain adapters (including known extension vocabularies
   such as crypto-exchange and Xaman).
2. `formalization_adapter` → formalization artifact / constraint views.
3. `SecurityConstraintCache@1` put with rehash-on-load integrity, declaration
   identity recompute, and **reject unknown extension vocabularies**.
4. Constraint query → hard-scoped selection for invocation context.

Security selection does **not** establish Legal compliance or free execution
admission by itself. Theorem, runtime-monitor, evidence-gate, and policy
result authorities remain non-substitutable
([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).

### 6.4 What compilation is not

| Non-compilation claim | Correct treatment |
| --- | --- |
| Parse success | Not semantic proof and not applicability |
| Retrieval / embedding hit | Advisory ranking only; never selects authority |
| LLM / heuristic extraction | Non-authoritative until admitted (see §10) |
| Cache put success | Storage integrity only; not policy allow |
| Solver `unsat` / `proved` | Distinct authority kinds; see external-provers and proof leaves |

## 7. Applicability

### 7.1 Hard filters before ranking

Both Legal and Security queries implement the shared rule:

1. **Hard applicability filters always run first.**
2. Ranking and selection budgets run only over hard-filter admissions.
3. Retrieval or similarity score is **advisory** and never selects authority.
4. Unresolved conflict, applicability gap, or incomplete coverage →
   **review / abstain**, never silent allow.
5. Contradictions are **preserved**; they are never discarded to force a unique
   winner.

Shared evidence shape: `ApplicabilityEvidence@1` with selectors,
`ApplicabilityStatus` (`applicable` | `not_applicable` | …), and optional
coverage gaps. Domain receipts (`LegalApplicabilityEvidence@1`,
`SecurityApplicabilityEvidence@1`) compose the shared contract without
flattening norms into a neutral formula that loses domain meaning.

### 7.2 Legal hard-filter dimensions

From `LegalConstraintQuery@1` (`LEGAL_HARD_FILTER_DIMENSIONS`):

| Dimension | Role |
| --- | --- |
| jurisdiction / territory | Geographic and legal-system scope |
| subject_matter | Topic / statutory subject slice |
| authority | Hierarchy, precedence, enacting body |
| temporal | Enactment, effective, repeal, amendment, supersession windows |
| actor / subject / resource / purpose / threshold | Fact binding for the invocation |
| provenance / premise_taint | Source and premise integrity |
| definition_refs / cross_references / exceptions | Norm structure required for sound application |

### 7.3 Security hard-filter dimensions

From `SecurityConstraintQuery@1` (`SECURITY_HARD_FILTER_DIMENSIONS`):

| Dimension | Role |
| --- | --- |
| principal / delegation / capability | Who acts under what grant |
| trust_zone | Zone / compartment of the invocation |
| asset / data_class | Protected object classification |
| channel / network / filesystem | Communication and storage paths |
| action / state / effect / failure / rollback | Behavioral surface |
| sandbox / environment evidence | Live environment bindings (not abstract-model substitution) |
| threat / policy version / freshness | Stale or digest-mismatched evidence rejects |
| result-authority family | Theorem vs monitor vs evidence-gate vs policy stay distinct |

**Abstract-model evidence never substitutes for live-environment evidence**
(and the reverse). Unknown extensions fail closed.

### 7.4 Corpus-level applicability

When constraints are stored as `AttestedProofEnvelope` rows, corpus
applicability (`proof_corpus.applicability`) adds exact-root dimensions:
corpus root, revocation root, tenant/jurisdiction/scope, temporal windows,
trust policy evaluation, supersession, and coverage. Hard rejections
(revocation, authority mismatch, root mismatch) outrank soft filters.

### 7.5 World policy

`WorldPolicyKind` on constraint artifacts:

| Mode | Absence of a required fact means |
| --- | --- |
| `closed` | False under closed-world evaluation (typical for security allowlists) |
| `open` | Unknown — must not invent a grant; often abstain/review |

Production trust policy defaults to **closed** evaluation for authorization
evidence unless a profile explicitly documents open-world handling with
abstain-on-gap behavior.

## 8. Proof corpus and cache integrity

Domain caches and the unified corpus share fail-closed integrity:

| Rule | Behavior |
| --- | --- |
| Content addressing | Envelope digests and CIDv1 under declared schemas |
| Rehash on load | Digest mismatch → reject; never soft-load corrupt rows |
| Declaration recompute | Stored payload must match recorded declaration digest/CID |
| Family closed set | Unified store accepts `intent`, `legal`, `security` only |
| Source binding | Source digest bound to artifact declaration digest |
| Body vs index | Manifest bodies and secondary indexes never mixed |
| No mutable `latest` | Aliases with `latest` fail closed |
| Append-only roots | Manifest and revocation snapshots are exact-root, generation-ordered |
| Partial load | Corrupt trees must not partially admit as valid authority |

**Cache hit is not authority.** Independent consumer verification and trust
policy evaluation are required before an envelope can authorize
([PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md)).

Legal proof cache and Security constraint cache remain valid offline fixture
sources. Production gates prefer the unified `ProofCorpusStore@1` under pinned
manifest and revocation roots.

## 9. Trust and revocation policy

### 9.1 Trust policy (`ProofTrustPolicy@1`)

Trust policy evaluates whether an attested envelope may be treated as
authorization **evidence** (not whether a tool may execute). Production
defaults (`default_production_trust_policy`):

- exact corpus / policy roots when required;
- allowlisted attestation kinds and authorities;
- **direct proof verification** as the theorem-authoritative kind;
- **forbid** elevating `artifact-membership`, `signature`, or `simulation` to
  theorem authority;
- finite budgets for query and ranking;
- conflict rules: `fail_closed`, `deny_overrides`, `review`, or `indeterminate`
  — never silent pick-a-winner.

Evaluation outcomes: `accept` | `reject` | `abstain`.

### 9.2 Revocation (`ProofRevocationSnapshot@1`)

Revocation is an append-only chain of exact-root snapshots binding:

- corpus root CID under enforcement;
- parent snapshot CID and generation;
- ordered unique target CIDs with closed reason kinds (`superseded`,
  `compromised`, `policy`, `withdrawn`, `error`, `other`);
- producer identity and optional supersession links.

Parent cycles, self-revocation of the snapshot root, generation rollback,
duplicate targets, and unbound empty reasons fail closed. A target present in
the active revocation set is hard-rejected at applicability.

### 9.3 Coverage policy (`CorpusCoveragePolicy@1`)

Coverage policy states required domains, selectors, and completeness thresholds
before ranking or allow. Incomplete coverage under a profile that requires
Legal and/or Security constraints contributes to **abstain** or **reject**,
never unconstrained allow.

### 9.4 Admissibility profile linkage

| Profile id | Legal constraints | Security constraints | Simulated ZKP | Allow without constraints |
| --- | --- | --- | --- | --- |
| `dev-offline` | required | required | may accept if labeled | **never** |
| `security-lite` | optional | required | reject | **never** |
| `legal-strict` (default) | required | required | reject | **never** |
| `zkp-required` | required | required | reject (and ZKP mandatory) | **never** |

Unknown profile ids fail closed as invalid profile (reject), never resolve to
a permissive default. Every profile construction rejects
`allow_without_constraints=true`.

## 10. Modeled assumptions, UNKNOWN, and NOT_MODELED

### 10.1 Modeled assumptions

Assumptions are first-class on constraint and proof paths:

- `Assumption` / assumption digests on IR claims and attested envelopes;
- constraint statement role `assumption`;
- explicit assumption digests in proof identity (statement + assumption +
  obligation digests must bind).

An allow or theorem claim under **undeclared** assumptions is a defect.
Changing assumptions changes identity; cached results under different
assumption digests must not silently reuse.

### 10.2 UNKNOWN

`UNKNOWN` appears at multiple non-interchangeable layers:

| Layer | Meaning | Must not become |
| --- | --- | --- |
| Solver / prover | No conclusive sat/unsat/proved within policy | `proved` or policy `allow` |
| Proof envelope `result_status` | Status unknown under declared authority | Upgrade of `result_authority` |
| Portfolio / job verdict | Backend did not conclude | Aggregate allow |
| Open-world fact absence | Fact not present under open policy | Closed-world denial of a hard forbid without evaluation |

Incomplete evidence at the gate is **abstain**, not allow
([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

### 10.3 NOT_MODELED

Domain claim compilers (for example Security crypto-exchange Z3 compilers)
return explicit **not modeled** outcomes when events, balances, traces, or
metadata required for a claim are outside the formal fragment
(`claim_not_modeled`). Coverage gaps on `ConstraintArtifact@1` carry the same
intent at the constraint layer.

| Rule | Behavior |
| --- | --- |
| Not modeled | Explicit diagnostic / gap; never silent true |
| Heuristic soundness notes | Annotate risk; never discharge obligations |
| Unsupported construct | Fail closed or abstain per profile; no invented semantics |

**Not modeled is not permission.** Absence of a modeled forbid must not be
read as a grant under closed-world production profiles without an explicit
positive applicable grant.

## 11. Heuristic extraction remains non-authoritative until admitted

Machine extraction (LLM parsing, NL→IR advisors, retrieval-ranked premises,
learned premise selection, heuristic soundness notes) may **propose** Legal or
Security structure. It does not become constraint or proof authority until
admission criteria are met:

| Stage | Authoritative? | Requirements |
| --- | --- | --- |
| Raw extraction / advisor output | **No** | Labeled review state; no gate allow on extraction alone |
| Human or policy review | Still not theorem proof | Review receipt; source map retained |
| Admitted into corpus | Evidence only under declared attestation kind | Integrity-bound envelope; exact roots; trust policy accept |
| Independently verified | Per attestation kind limits | Consumer verifier pass; no simulation promotion |
| Profile allow | Policy decision | Positive grants + discharged obligations + no hard forbid |

`review_state` on proof-corpus envelopes and Legal `source_review_status` make
trust in sources explicit. Fixture defaults such as `trusted_fixture` are for
offline tests; production admission requires the promotion and review path
documented in the proof/attestation leaf and operator guide.

Premise selection (`SelectedPremiseSet@1`) is a **bounded, source-grounded
receipt**. Ranking method is recorded; ranking never elevates into
applicability or truth.

## 12. Failure modes and fail-closed matrix

| Condition | Outcome |
| --- | --- |
| Unknown profile | reject (`invalid_profile`) |
| Missing required Legal/Security constraints under profile | reject or abstain per profile (never allow) |
| Hard Legal forbid / Security deny applicable | reject |
| Unresolved authority conflict | review / abstain / fail_closed (never silent winner) |
| Digest / CID drift on cache load | integrity error; reject envelope |
| Unknown Security extension vocabulary | reject put and reload |
| Stale or digest-mismatched environment evidence | reject |
| Coverage incomplete for required domains | abstain / reject |
| Target in revocation snapshot | hard reject |
| Heuristic-only extraction | non-authoritative; cannot allow |
| NOT_MODELED / UNKNOWN obligation | cannot allow until modeled and discharged |

## 13. Extension guide

1. **New Legal selector dimension** — add to hard-filter list and applicability
   evidence; keep ranking advisory; update fixtures.
2. **New Security extension vocabulary** — register in known-extension
   allowlist before cache put; unknown ids stay rejected.
3. **New constraint role or logic family** — extend `ConstraintArtifact@1`
   with schema version bump; do not silently concatenate families.
4. **New cache backend** — preserve rehash-on-load and declaration recompute;
   never treat store presence as proof.
5. **Do not** add a code path that allows without constraints, promotes
   retrieval rank to authority, or treats NOT_MODELED as grant.

## 14. Validation

Structural and integration signals (run from repository root as available):

```bash
test -s docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md
test -s docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md

# Domain constraint and corpus contracts (representative)
python -m pytest \
  tests/unit/logic/formalization/ \
  tests/unit/logic/legal_ir/ \
  tests/unit/logic/security_ir/ \
  tests/unit/logic/proof_corpus/ \
  tests/unit/logic/admissibility/test_profiles.py \
  -q --collect-only  # tighten to concrete suites when running full gates
```

Focused attested authorization suite (when present):

```bash
python -m pytest \
  tests/unit/logic/admissibility/test_attested_golden_contract.py \
  tests/integration/logic/test_attested_intent_authorization.py \
  -q
```

Guide freshness: when hard-filter dimensions, profile knobs, or integrity rules
change, update this document and the sibling proof/attestation guide in the
same change set when both interfaces move.

## 15. Related documents

| Document | Relationship |
| --- | --- |
| [PROOF_ATTESTATION_AND_ZKP.md](./PROOF_ATTESTATION_AND_ZKP.md) | Attestation kinds, ZKP profiles, verifier, redaction, release assurance |
| [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) | Kernel identity and authority kinds |
| [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Formalization and round-trip without proof |
| [EXTERNAL_PROVERS.md](./EXTERNAL_PROVERS.md) | Solver/ITP lifecycle; non-substitution of SAT for theorem proof |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flow D logic→evidence |
| [guides/ATTESTED_INTENT_AUTHORIZATION.md](../../guides/ATTESTED_INTENT_AUTHORIZATION.md) | Operator surface for gate and corpus |
| [LOGIC_INTENT_LEGAL_GATE_PLAN.md](../LOGIC_INTENT_LEGAL_GATE_PLAN.md) | Program plan (historical/active roadmap; not runtime authority) |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) / [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Layered authority and fail-closed degradation |

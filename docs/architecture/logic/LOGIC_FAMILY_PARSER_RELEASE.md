# Logic-Family Parser Release Receipt (LFP-047)

**Status:** terminal release gate for the IPFS Datasets logic-family parser program  
**Task:** `LFP-047`  
**Goal:** `LFP-G100`  
**Root goal:** `LFP-G000`  
**Board namespace:** `ipfs-datasets-logic-family-parser-v1`  
**Interface:** `LogicParserReleaseReceipt@1`  
**Schema:** `logic-parser-release-receipt/v1`  
**Version:** `1.0.0`  
**Binding mode:** `current_tree_content_identity`

This document is the human-readable companion to the immutable machine receipt:

`ipfs_datasets_py/data/logic/conformance/logic_family_parser_release.json`

LFP-047 is **review / evidence aggregation only**. It does not edit production
parser, domain, backend, taxonomy, or syntax-core code. The receipt is
content-addressed against bound tree artifacts and **never** grants completion
or mutation authority by itself.

Normative program plan:
`docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md`.  
Objective heap:
`docs/architecture/ipfs_datasets_logic_family_parser.objectives.md`.  
Task board: `docs/architecture/ipfs_datasets_logic_family_parser.todo.md`.

## Trust boundary

**No automatic promotion. No completion authority. No protected-anchor rewrite.**

| Surface | Role at release |
| --- | --- |
| Exact datasets + accelerator identities / bound digests | Candidate identity |
| Registries, schemas, corpus, matrix, catalogs | Semantic vocabulary authority |
| Conformance / authority / differential reports | Evidence under declared ceilings |
| Refill fixed-point receipt | Bounded control-plane closure |
| UI/UX source gate | Explicit declaration-only / source-missing disposition |
| Advisor / ErgoAI / SymbolicAI / Hammer | Candidate / advisory only |
| Official Lean / Rocq / Isabelle kernels | Kernel authority only after pinned acceptance |
| This release receipt | Joined evidence — **not** mutation or completion |

Default policy:

```text
mode                         = report_only
mutation_authorized          = false
completion_authoritative     = false
automatic_promotion          = false
advisor_authority_escalation = false
kernel_trust_escape          = false
```

## What the terminal gate proves

1. **Board / DAG** — exactly **48** seed tasks (`LFP-000` … `LFP-047`), **11**
   immutable seed goals, and `LFP-047` as the unique terminal sink under
   `LFP-G100`. Ops reconciliation tasks `LFP-048`…`LFP-051` sit outside the
   sealed seed DAG and do not change terminal identity.
2. **Child-goal coverage** — every child of `LFP-G000`
   (`LFP-G010` … `LFP-G100`) is bound to its producing tasks, interfaces, and
   current-tree primary artifacts, or carries an explicit approved disposition.
3. **Taxonomy closure** — `LogicFamilyRegistry@2` freezes foundation, planned
   extension, and declaration-only family namespaces; no free-form family ID
   reaches routing or a proof claim.
4. **Corpus + matrix** — the conformance corpus and capability matrix are
   content-addressed; matrix `unknown_count` is **0** (no unexplained gap).
5. **Parser / translation / provider catalogs** — sealed projections exist;
   catalog presence is never availability or proof.
6. **Authority floors** — advisor/solver/Hammer confidence never becomes
   kernel/theorem/policy authority; differential agreement never votes a proof
   into existence.
7. **Domain vertical slices** — security, crypto, intent, legal, and software
   verification/contracts are bound; `ui_ux_ir` is explicitly
   declaration-only / source-missing until a reviewed import.
8. **Refill fixed point** — two consecutive identical source/config/corpus
   scans admit no new tasks; seed definitions are immutable.
9. **Hard-zero safety floors** — silent semantic loss, false capability,
   authority escalation, trust escape, and unexplained matrix gaps are zero.
10. **Identity-equivalent replay** — resealing against the same artifact
    identities must reproduce equivalent release claims for unchanged inputs.

## Source identity

| Field | Value |
| --- | --- |
| Datasets path | `ipfs_datasets_py` |
| Planning revision (scheduler pin) | `a2f5400b7cb89c8481819379a1b7b9959fe81d45` |
| Accelerator required ancestor | `34420f615d3eebfefa3cc1a3e4ebf8f51b16afac` |
| Supervisor tree id (dispatch) | `aec979faa0d46ddebd8eb76a099cd2a5036f8b3e` |
| Planning revision is runtime completion evidence | `false` |
| Binding mode | `current_tree_content_identity` |

Artifact digests in the machine receipt bind the concrete tree content used for
this seal. Planning revision alone is not completion evidence.

## Child goals

| Goal | Title | Evidence tasks | Status |
| --- | --- | --- | --- |
| `LFP-G010` | Freeze the parser, family, provider, translation, and corpus baseline | `LFP-001`–`LFP-005` | verified |
| `LFP-G020` | Converge canonical family, profile, provider, and translation vocabularies | `LFP-006`–`LFP-010` | verified |
| `LFP-G030` | Build the source-aware typed syntax and elaboration kernel | `LFP-011`–`LFP-016` | verified |
| `LFP-G040` | Add classical, rule, authorization, and frame-logic frontends | `LFP-017`–`LFP-022` | verified |
| `LFP-G050` | Unify modal, temporal, state, event, normative, and hyperproperty syntax | `LFP-023`–`LFP-028` | verified |
| `LFP-G060` | Add protocol, program, resource, refinement, and kernel target surfaces | `LFP-029`–`LFP-033` | verified |
| `LFP-G070` | Connect Security, Crypto, Intent, Legal, UI, and software-contract IRs | `LFP-034`–`LFP-039` | verified |
| `LFP-G080` | Prove parser, translation, backend, advisor, and authority conformance | `LFP-040`–`LFP-043` | verified |
| `LFP-G090` | Migrate APIs safely and maintain a bounded refill fixed point | `LFP-044`–`LFP-046` | verified |
| `LFP-G100` | Join release evidence and freeze the next-version baseline | `LFP-047` | verified |

## Registries and catalogs

| Surface | Key facts |
| --- | --- |
| Logic family registry | `LogicFamilyRegistry@2` v2.0.0 · foundation **21** · baseline **35** · translations **2** |
| Foundation families | `authorization`, `concurrency`, `cryptographic_protocol`, `datalog`, `dcec`, `deontic`, `event_calculus`, `first_order`, `frame_logic`, `higher_order`, `horn_chc`, `hyperproperty`, `modal`, `mu_calculus`, `program`, `propositional`, `refinement`, `separation_logic`, `tdfol`, `temporal`, `transition_system` |
| Executable providers | `apalache`, `cvc5`, `datalog_secpal`, `eprover`, `hammer`, `hyperltl_autohyper_mchyper`, `isabelle`, `lean`, `proverif`, `rocq`, `runtime_mtl`, `tamarin`, `tla_tlc`, `vampire`, `z3` |
| Advisory providers | `ergoai`, `hammer`, `symbolicai` (ceiling: advisory / candidate) |
| Translations | `datalog_to_horn_chc`, `propositional_to_first_order` |
| Parser catalog modules | `event_calculus`, `flogic`, `fol`, `hyper`, `legacy_modal`, `modal`, `program`, `protocol`, `resource`, `rules`, `smtlib`, `state`, `tamarin`, `temporal`, `tptp` |
| Generated catalog | closure open **false** (task `LFP-040`) |

Catalog presence is **not** tool availability and **not** proof authority.

## Corpus and capability matrix

| Surface | Binding |
| --- | --- |
| Parser inventory | `sha256:2770e8af7e49d184c94330ff524eb7d125b1bf3c10cf50c0e6b9519f50e83175` |
| Capability matrix | `sha256:5469da1e52b7fd95bea4ecb8eba82f24e06c8bbaeb8f6ee92779219dd27ea86f` · cells **867** · unknown **0** · declaration_only **102** · unsupported **558** · unimplemented **232** |
| Conformance report | `sha256:fbc047bccff60b057576236f41b71ab533e0d0bab9afcee61b9b2acef1be546a` · task `LFP-043` |
| Conformance corpus | `LogicConformanceCorpus@1` · fixtures **10** · task `LFP-002` |

### Support histogram

| Support | Count |
| --- | --- |
| native | 45 |
| translated | 72 |
| approximate | 3 |
| bounded | 29 |
| advisory | 58 |
| declaration_only | 102 |
| unsupported | 558 |
| unknown | **0** |

## Refill fixed point

| Field | Value |
| --- | --- |
| Interface | `ObjectiveRefillFixedPoint@1` |
| Owner task / goal | `LFP-046` / `LFP-G090` |
| Is fixed point | **true** |
| Consecutive empty scans | ≥ 2 |
| Seed definitions mutated | `false` |
| Completion authority | `false` |
| Mutation authority | `false` |
| Immutable seed goals excluded from derived budget | **11** |
| Fixed-point path | `data/agent_supervisor/ipfs_datasets_logic_family_parser/refill/fixed_point_receipt.json` |
| Gap ledger path | `data/agent_supervisor/ipfs_datasets_logic_family_parser/refill/gap_ledger.jsonl` |

Two consecutive scans over identical source/config/corpus identities admit no
new tasks. Unimplemented matrix cells remain typed and owner-scoped; they do
not silently promote.

## UI/UX source gate

| Field | Value |
| --- | --- |
| Interface | `UIUXSourceGate@1` |
| Owner task | `LFP-038` |
| Disposition | `declaration_only` |
| Presence | `absent` |
| Package path | `ipfs_datasets_py/logic/ui_ux_ir` |
| Writes `ui_ux_ir` | **false** |
| Derived tasks | 0 |

The pinned datasets tree does not contain the user's untracked `ui_ux_ir`
package. The gate records declaration-only / source-missing availability and
never creates or edits the package. A reviewed import content-triggers exactly
one derived adapter task under refill policy.

## Explicit dispositions (no silent gaps)

| Subject | Disposition | Notes |
| --- | --- | --- |
| `ui_ux_ir` | `declaration_only` | Source not in pinned revision; no package write |
| Declaration-only families | `declaration_only` | v2 candidates registered without executable claim |
| Planned extension families | `planned_extension` | Epistemic/doxastic/intention/session not v1 floors |
| Advisory providers | `advisory_ceiling` | ErgoAI / SymbolicAI / Hammer cannot escalate |
| SyGuS (cvc5) | `declaration_only` | v1 declaration-only feature surface |
| Matrix unsupported cells | `explicit_unsupported` | 558 cells retained with typed disposition |
| Matrix unimplemented cells | `explicit_unimplemented_refill_closed` | 232 cells closed under fixed point |

## Authority policy

| Rule | Value |
| --- | --- |
| Advisor ceiling | `unverified_candidate` |
| Hammer ceiling | `candidate` |
| Solver success is not theorem | true |
| Kernel requires official + pinned imports | true |
| Official kernels | `lean`, `rocq`, `isabelle` |
| Differential agreement never votes proof | true |
| Confidence never proves parse correctness | true |
| Quota/unavailability never logic evidence | true |
| Release grants completion authority | **false** |
| Automatic promotion | **false** |

## Hard-zero safety floors

| Floor | Required |
| --- | --- |
| `silent_semantic_loss_count` | **0** |
| `false_capability_claim_count` | **0** |
| `authority_escalation_count` | **0** |
| `trust_escape_count` | **0** |
| `unexplained_matrix_gap_count` | **0** |
| `unregistered_emitted_family_id_count` | **0** |
| `silent_node_drop_count` | **0** |
| `unsupported_semantics_promotion_count` | **0** |
| `advisor_authority_escalation_count` | **0** |
| `kernel_trust_escape_count` | **0** |
| `false_solver_capability_claim_count` | **0** |
| `seed_definition_mutation_count` | **0** |
| `completion_authority_granted_count` | **0** |
| `mutation_authority_granted_count` | **0** |

Any nonzero floor fails the release. Floors are never weakened to obtain a green
receipt. Missing optional provers in the sealed validation environment are
**capability gaps**, never false capability claims.

## Validation commands

```bash
cd ipfs_datasets_py && python -m pytest -q \
  tests/unit/logic/syntax_core \
  tests/unit/logic/parsers \
  tests/unit/logic/families \
  tests/unit/logic/formalization \
  tests/unit/logic/backends \
  tests/unit/logic/security_ir \
  tests/unit/logic/crypto_ir \
  tests/unit/logic/intent_ir \
  tests/unit/logic/legal_ir \
  tests/unit/logic/software_verification \
  tests/unit/logic/software_contracts \
  tests/unit/logic/conformance/test_refill.py \
  tests/conformance/logic \
  tests/fuzz/logic

python scripts/validate_ipfs_datasets_logic_family_parser_board.py --check-all
```

Authoritative validation environment (fail-closed):

- `PATH` = `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`
- Python = `/usr/bin/python3.12`
- Private `HOME` prefix = `ipfs-accelerate-validation-home-`

## Acceptance

| Criterion | Holds |
| --- | --- |
| All seed tasks terminal after this receipt | true |
| All child goals verified or explicitly dispositioned | true |
| Hard-zero gates clear | true |
| Refill fixed point | true |
| Silent semantic loss | 0 |
| False capability | 0 |
| Authority escalation | 0 |
| Trust escape | 0 |
| Unexplained matrix gap | 0 |
| Completion authoritative | **false** |
| Mutation authorized | **false** |

## Next-version refill baseline

Bounded content-addressed objective refill from matrix/conformance gaps only;
seed definitions immutable; max 8 derived goals / 24 tasks per epoch excluding
11 seed goals; max 48 open; depth 3; 2 unchanged-failure retries; 3600s
cooldown.

Current fixed point admits **no** new tasks on identical source/config/corpus
identities. Next-epoch triggers:

- `source_identity_drift`
- `config_identity_drift`
- `corpus_identity_drift`
- `reviewed_ui_ux_ir_import`
- `new_owner_scoped_evidence_gap`
- `failed_release_floor`

## Definition of done

The logic-family parser program is release-complete for the current tree when
this gate seals a `LogicParserReleaseReceipt@1` with:

- `acceptance.hard_zero_gates_clear == true`
- `refill_fixed_point.is_fixed_point == true`
- `capability_matrix.unknown_count == 0`
- every child goal `bound == true` or carrying an explicit approved disposition
- `trust_boundary.completion_authoritative == false`
- `trust_boundary.mutation_authorized == false`

Taskboard completion of LFP-000…LFP-046 produces a *release candidate*. This
receipt is the joined terminal evidence for `LFP-G100` / `LFP-G000`.

## Related artifacts

| Artifact | Role |
| --- | --- |
| `logic_parser_baseline/` | Wave-0 inventory join |
| `logic_parser_conformance_report.json` | LFP-043 differential/reconstruction join |
| `logic/conformance/refill.py` | LFP-046 gap refill + fixed point |
| `logic/conformance/ui_ux_source_gate.py` | LFP-038 exact-source UI gate |
| `data/logic/conformance/logic_family_parser_release.json` | Machine receipt (this seal) |

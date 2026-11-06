# Unsigned norm content declarations

`legal_norm_content_declaration_v1` prepares an explicit content declaration for
one retained norm hypothesis and its definition-use nominations. It binds the
complete typed/native AST, original source-unit record, context, coverage
obligations and exact typed occurrences to a proposed interpretation. It retains
the original evidence and producer identities without applying a meaning or
governing definition.

The supported scope is `retained_historical_evidence_only`. An independently
pinned report is a custody input; its hash alone supplies no legal authenticity
or current-source correspondence. The execution packet must separately retain
the original qualification receipts, extraction lineage and source commitments.
This owner performs structural consistency checks and declaration regeneration;
it does not reexecute the original source/definition owners. Typed/native AST
equivalence remains historical evidence; native lowering is not rerun here.

## Inputs and operations

Supply three complete UTF-8 JSON byte strings: the declaration request, retained
norm-review preparation and retained norm/definition evidence report. The
request pins both exact report serializations and their canonical identities.
Supply the request hash independently to the operation.

```python
from ipfs_datasets_py.logic.autoformal.legal_norm_content_declaration_v1 import (
    prepare_norm_content_declaration,
    norm_content_declaration_sha256,
    validate_norm_content_declaration,
)

declaration = prepare_norm_content_declaration(
    request_raw, norm_preparation_raw, definition_evidence_raw,
    expected_request_sha256=request_sha256,
)
declaration_sha256 = norm_content_declaration_sha256(declaration)
validate_norm_content_declaration(
    declaration, request_raw, norm_preparation_raw, definition_evidence_raw,
    expected_request_sha256=request_sha256,
    expected_report_sha256=declaration_sha256,
)
```

Validation regenerates the whole declaration from the original retained bytes.
A rehashed modification to an output does not qualify it. Input size/population
bounds refuse oversized content instead of truncating it. The owner also checks
its own source and strict JSON helper for drift.

## Structured content

The request uses schema `legal-norm-content-declaration-request/v1` and includes
an explicit candidate identity, exact report pins and these content groups:

| Group | Required declaration |
| --- | --- |
| Interpretation | `pending`, `proposed_support` or `proposed_reject`, the exact typed-expression hash and a rationale. |
| Meaning-unit nomination | Exact original source-unit hash, `unassessed` or `partial` coverage, an explicit legal-as-of date or null, and a rationale. The current source profile cannot establish a complete multi-paragraph unit. |
| Coverage | Every original norm obligation in its original order, each with `pending`, `proposed_resolved` or `proposed_not_applicable`, declared evidence references and a rationale. |
| Definition uses | Every distinct exact typed target in first-link order, each pending or proposed applicable/not applicable, with an exact nominated alternative/link where applicable, declared evidence references and a rationale. |

Proposed dispositions require their declared rationale and relevant evidence
references. Pending forms can remain blank. Evidence references remain
declarations; this operation does not authenticate evidence bodies or reviewers.

A definition choice identifies a complete typed occurrence, including its path,
retained binder/argument/modal context and inverse source anchors. Reusing a
variable's spelling cannot replace that occurrence identity. A proposed
applicable alternative must already be linked to that exact occurrence. The
existing unary definition-use profile cannot substitute a predicate for the
pilot's bound relational variable; typed definition application retains an
explicit unsupported status.

`proposed_not_applicable` concerns the nominated use as a whole and retains null
alternative/link fields. All competing definition links remain in the packet.

The output preserves the full original ASTs, source/context evidence, original
issues and obligations, typed/source inventories, definition alternatives and
nominations. It also records the proposed content and its unresolved gates.
Proposals for different ASTs over the same physical paragraph remain distinct
alternatives. They do not create additional source provisions or actual uses.

## Authority and subsequent integration

The declaration is unsigned. `meaning_unit_id`, accepted interpretation and
governing definition use remain null. Semantic, consumer, training and gold
masks are integer zero, including when an author proposes support or
applicability. Original signatures retain their original subjects and do not
cover this new declaration.

Subsequent decision authentication must bind the complete new declaration in an
explicit compatible signing domain with independently supplied trust, reviewer,
clock, evidence and current dependency observations. Current-source replay,
complete meaning-unit geometry and coverage, relational definition application,
graph/Lean transport and training exposure/split authorization remain separate
acceptance requirements. No model, proof, Lean, database or remote-release
operation is performed by this owner.

The [generation-binding companion](legal_norm_content_declaration_binding_v1.md)
now supplies an explicit complete obligation crosswalk between a retained
declaration and a fully replayed current norm candidate. Both preparation and
producer generations remain identified; old issue/question slot IDs are not
silently replaced. Exact validated binding and declaration bytes can be supplied
as evidence in the existing response-body protocol. This compatibility binding
does not authenticate the declaration author, verify nested evidence bodies,
apply definition proposals or qualify a reviewed meaning.

The enclosing workspace maintains the retained-pilot qualification packet at
`artifacts/legal-ir-norm-content-declaration-20261016-01/`. It includes both
§7213 hypotheses and both officer-definition alternatives, complete pending
declarations, source captures and original extraction/qualification lineage.

## Public source integration (2026-10-24)

The unsigned owner and owning test are byte-exact to their original 144-case generation (`4d72a8e7…` / `5252f848…`). The [shared fresh integration](../../../../../docs/autoformalization/evidence/legal-ir-norm-content-declaration-binding-public-integration-20261024.json) passed six existing declaration controls within a separate 21-case / 63-phase cohort. The full 144-case qualification and original A/B preparation were not rerun. Preserve the original qualification's documented source READ, resource, storage and durability scope; the fresh namespace/raw-buffer/phase evidence does not apply retrospectively to it.

The other fifteen fresh cases cover declaration binding: twelve existing controls and three later existing cases. That later binding generation differs from its original 64-case implementation by one raw-length ledger mark; its qualification is separate from this unchanged unsigned owner. The existing signed-response and adjudication owners retain their own completed scopes.

Original A/B declarations remain unsubmitted proposals over one retained §7213 paragraph and two §101 officer-definition alternatives, with no accepted meaning, governing use or applied definition. Publication supplies no actual review, signer, trusted clock, complete meaning unit, physical cache join, second statutory norm or training/Lean admission. All source-width/task/checkpoint/context/output and eligibility contracts remain unchanged.

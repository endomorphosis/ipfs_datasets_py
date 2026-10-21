# Legal relational reconstruction diagnostics v1

`logic/autoformal/legal_relational_reconstruction_diagnostics_v1.py` gives named
structural diagnostics for two valid authored relational declarations. It calls
the existing `legal_relational_reconstruction_v1` comparison with the original
requests, reports and independent hashes, then groups that owner's complete
feature ledger. It creates no new AST, grammar, binder resolver or semantics.

This makes missing binders, changed modal placement and collapsed or swapped
arguments visible when a generated candidate is valid but differs from an
exposed target. Typed completion, exact reconstruction, lexical alpha structure
and legal correctness remain separate questions.

## Public API

```python
prepare_relational_reconstruction_diagnostics_v1(
    reference_report, candidate_report, *,
    reference_request_raw, candidate_request_raw,
    expected_reference_request_sha256, expected_candidate_request_sha256,
    expected_reference_report_sha256, expected_candidate_report_sha256,
)
relational_reconstruction_diagnostics_sha256(report)
validate_relational_reconstruction_diagnostics_v1(
    report, reference_report, candidate_report, *,
    expected_diagnostics_sha256,
    reference_request_raw, candidate_request_raw,
    expected_reference_request_sha256, expected_candidate_request_sha256,
    expected_reference_report_sha256, expected_candidate_report_sha256,
)
```

The error type is `RelationalReconstructionDiagnosticsError`, a `ValueError`.
Validation regenerates the diagnostic from all original inputs. Rehashing an
edited result cannot make its claims valid. Hashing alone establishes neither
execution nor source meaning.

Public import uses only the standard library. Operations lazily reuse the
existing comparator and its finite JSON/source helpers. Source fences bind the
companion and the comparator's actual producer closure. Ordinary inputs,
source reads and output size retain existing finite bounds; the complete
diagnostic has an 8 MiB output cap and truncation is refused. No model, optimizer,
solver, network request or build executes. Original relational replay may emit
syntax-only Lean text but does not run Lean.

## Report and named groups

The report schema is `legal-relational-reconstruction-diagnostics/v1`. It retains
the full original `comparison`, its canonical hash and the unchanged original
exact-expression, declared-structure and lexical-alpha outcomes. `groups` holds:

| Group | Existing features retained |
| --- | --- |
| `binder_quantifier_topology` | Quantifier kinds, binder paths, variable-to-quantifier binding paths, order, sorts and structural ancestry |
| `modal_operator_placement` | O/P/F, extension payload and family/profile, modal paths, modal ancestry and connective context |
| `predicate_ordered_arguments_roles` | Predicate identities, declared signatures, ordered argument indices and roles, lexical binder paths and ancestry |
| `connective_negation_context` | Connective/negation kind, ordered children, branch indices, predicate/binding identities and modal context |

Every group keeps the original typed path, both projected feature objects,
per-field differences and missing sides. It never matches a subtree to a more
favorable location. Equal counts therefore cannot hide argument capture,
quantifier changes or modal relocation. Predicate signature declarations and
role declarations also gate the predicate group.

Lexical binder names, variable symbol spellings, node IDs and native serializer
paths are excluded from the named projections. Binding paths and predicate
identities remain. A consistent alpha rename can consequently preserve all
groups while the original exact and declared comparisons remain false. The
complete original ledger still records those name/identity changes.

Each group is `equal`, `different` or `not_applicable`. If neither side contains
that group, `equal` is `null`; absence is not a successful match. If one side
lacks a group member, the row's equality is `null` and the group's outcome is
`different`. Groups overlap and include context: their errors must not be summed
as independent error causes or converted into an unqualified accuracy metric.

## Generated outputs and the full denominator

This API compares valid pairs only. For retained decoder outputs, use the
existing content decoder and relational owner to produce the actual candidate
report. Never replace a wrong generated tree with the teacher-forced target.
Preserve the exact source report, checkpoint, context, token IDs, original
target exposure and authored-conditioning declarations outside this pair report.

Incomplete, invalid, refused, missing and uninvoked outputs do not supply valid
candidate reports and refuse here. A caller must keep every enrolled slot in a
separate ledger and set its structural diagnostics unavailable where no valid
pair exists. For example, two complete wrong candidates and two incomplete
outputs are four enrolled outputs, two comparable pairs and zero exact matches;
they are not a two-item successful evaluation population.

`legal_relational_batch_evaluation_v1` already owns complete-population
content-token evaluation. Its existing `decoder_declared` policy requires
target-access/teacher-forcing declarations to be false and encoder/checkpoint
identities to be supplied. Exposed authored384 checkpoint-validation runs must
not be relabeled as source-independent decoder trials or authored controls to
bypass that policy. A separate honestly labeled saved-run ledger can retain
the existing batch owner's refusals and invoke this companion for valid-pair
development diagnostics without claiming batch admission.

## Supported scope and training use

The existing authored relational profile controls applicability: Object-sorted
bound predicate arguments, ordered roles, supported quantifiers/connectives and
legacy deontic O/P/F. It rejects free variables, shadowing, globally repeated
binder names and unsupported families. This companion does not expand that
fragment, establish meaning from source prose or qualify statutory graphs.

All authority flags stay false; training and evaluation-gold masks stay zero.
No correctness, source grounding, proof acceptance or legal-equivalence label
is created. In particular this diagnostic does not qualify the 384-dimensional
authored conditioning, 768/4096-dimensional deployments, corpus adaptation or
holdout reconstruction.

For a later supervision experiment, reuse
`prepare_compact_content_decisions_v1`: it already labels every target token's
tree path and role (`constructor`, `binder_declaration`, `variable_reference`,
`predicate_reference`, `modal_letter`, transport and EOS). Current scope training
retains the baseline forced:choice weights 1:4 and normalizer 67; it does not use
distinct binder/modal/argument weights. Any change must be a separately versioned
objective/checkpoint policy with its own qualification, not an alteration of
historical results. Per-step conditioning would be a separate model intervention.
This diagnostics addition changes neither training nor inference.

## Focused qualification

The companion tests reuse the real existing relational fixtures, typed builders
and comparator. They cover self-pair replay, alpha/ID changes, same-count valid
rivals, missing paths in both directions, absent groups, all original input pins,
self-rehashed output tampering and unavailable candidates. Tests do not execute
models, optimizers, solvers or builds. Native qualification must use the existing
source/resource owners and the repository's isolated pytest environment; this
document does not authorize a new runner or infer a passing result.

# Compact LegalIR completion-budget policy

`legal_compact_content_completion_budget_v1` is an additive, opt-in refinement
of the existing lexical-scope selector. Historical token, selection, scope,
training and role-runtime sources remain unchanged. This policy answers a narrow
question: can a sound lower bound already rule out completion within the caller's
remaining token allowance?

## Public operations

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_completion_budget_v1 as budget,
)

prefix = budget.allowed_token_ids(
    prefix_ids, context_raw,
    expected_context_sha256=context_sha256,
    codec=codec, expected_codec_sha256=codec_sha256,
    remaining_new_tokens=remaining,
)
selection = budget.select_token(
    logits, prefix_ids, context_raw,
    expected_context_sha256=context_sha256,
    codec=codec, expected_codec_sha256=codec_sha256,
    remaining_new_tokens=remaining,
)
```

`remaining_new_tokens` is a plain integer in 0..512. It counts every further
selected token, including EOS and BOS when the offered prefix is empty. Effective
capacity is the smaller of this allowance and `512 - len(prefix_ids)`. No old
512-ID framing limit is raised. Both public operations apply the same policy;
selection retains the original full537 finite-score validation and lowest-ID tie
rule. The API accepts no expected target or checkpoint.

The prefix report preserves the complete original token and scope reports,
per-choice lower bounds and removal reasons, the explicit caller/effective
allowances, source identities, and zero training/evaluation masks. Empty choices
caused by the new bound have `status="budget_exhausted"` and
`reason="no_scope_continuation_within_remaining_budget"`. A completed sequence
already containing EOS remains complete, including at zero remaining tokens.

## Why the bound is conservative

The existing pinned owners validate actual syntax, lexical scope, argument arity
and source/context custody. A separate bounded cost analysis replays the prefix
against a relaxation of that exact canonical grammar. It retains punctuation,
constructors, selected predicate arity, closing delimiters and EOS, while omitting
global predicate coverage, required quantification, lexical variable binding,
binder order and node/depth limits. Removing those constraints can only reduce
the shortest completion cost.

A variable costs five lexical tokens. A cheapest unconstrained formula in this
relaxed language is a predicate of minimum declared arity `a`, costing `7 + 6*a`.
Unary wrappers add tokens and binary constructors require two formulas. Once a
predicate index is chosen, its actual arity determines argument cost. The parser's
residual stack partitions the remaining output positions, so their costs add.
This is a shortest relaxed-language cost, not a greedy completion length.

For each scope-allowed token `t`, remove it only if
`1 + lower_bound(prefix + [t]) > effective_remaining`. Equality is allowed.
Unsupported analysis or analysis-work exhaustion returns `unknown`; it preserves
the choice when at least one slot remains. At zero capacity even that one token
cannot fit. Passing the bound proves neither a legal completion nor termination:
all the omitted constraints still need the original validators. No synthetic
completion is inserted, and no source meaning or legal authority is inferred.

## Opt-in role-checkpoint consumer

`legal_compact_content_role_budget_runtime_v1.generate(...)` has the same
arguments as the original role runtime's `generate`. It retains the 1..64-new-token
limit, intact role-checkpoint validation, explicit target-free serving view and
one prepared model lifetime. It passes the decreasing allowance identically to
prefix and selection calls and checks complete report agreement. The original
checkpoint validator still reads its historical training basis; numerical serving
uses only conditioning and prefixes. This separation is reported explicitly.

An initially infeasible prefix constructs no numerical model. A later infeasible
prefix stops before another forward. The consumer maps the exact new policy
refusal to `status="budget_infeasible"`, retains final original decoding, and
closes an allocated session on success and failure. Budget policy/source receipts
are separate from unchanged training-grammar and checkpoint identities. Default
routing and the historical v1 consumer remain unchanged.

## Validation and limits

The portable budget tests use independently authored complete ASTs and verify
that every witnessed next token remains available when its complete suffix fits.
They cover constructors, modalities, nested/sibling scopes, repeated arguments,
multiple predicates, arities 1/2/8, EOS, strict budgets, unknown bounds, custody
and report disagreement. The original token/selection/scope tests are retained.

The role-runtime unit tests use explicitly authored simulated producers and model
objects through the new adapter's seams. They check allocation avoidance, budget
propagation, EOS, agreement and cleanup. They are **not actual model inference**,
checkpoint compatibility qualification or an observation of improved reconstruction.
A future admitted numerical comparison must use unchanged weights and source/task
inputs and report all outcomes; it must not relabel the historical CP128 failures.

This profile concerns the existing compact384/fixed537 decoder. It makes no new
768D/4096D, statutory, holdout, graph, Lean, throughput or token-saving claim.
Source/resource admission remains with the existing operation owners.

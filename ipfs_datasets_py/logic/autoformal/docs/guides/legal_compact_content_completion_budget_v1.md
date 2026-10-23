# Compact LegalIR completion-budget policy

`legal_compact_content_completion_budget_v1` is an additive, opt-in refinement
of the existing lexical-scope selector. Historical token, selection, scope,
training and the original `role_trained_runtime_v1` owner remain unchanged.
The existing budget consumer receives the additive API described below. This policy answers a narrow
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

## Explicit BOS generation v2

**Engineering qualification:** the [audited result](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-role-bos-generation-20261022-01/qualification-summary-v01.json)
records 67 passed cases / 201 passed phases. Original source, native and storage
custody closed for the successful cohort and all three retained failed attempts.

The existing `legal_compact_content_role_budget_runtime_v1` owner adds an
explicit operation:

```python
generate_from_bos_v2(
    checkpoint, conditioning, context_raw, *,
    expected_checkpoint_sha256, expected_policy_sha256,
    expected_context_sha256, max_new_tokens, context_origin,
)
```

It fixes the initial prefix to `[1]` and its origin to `bos_seed`. The required
`max_new_tokens` is a plain integer in 1..511; EOS consumes one of those IDs.
The codec retains 512 total IDs, including BOS/EOS, and 537 vocabulary entries.
The report uses `legal-role-budget-content-generation/v2` and
`bounded-bos-role-compact384-completion-budget-inference/v2`. The original
`generate` keeps its 1..64 limit, schema, report and settings semantics.
The whole report retains its original 16 MiB bound; oversized reports are
refused. A larger allowance does not permit truncated traces or a larger report.

Both public operations share one generation loop, intact role-checkpoint
validation, the target-free serving projection and the original prepared-model
lifetime. Checkpoint validation still reads exposed historical training targets.
The new API receives no prefix, expected target or identity sidecar; supplied
context can remain target-derived and must declare its origin. Required hashes,
source fences, whole-prefix forwards, completion-policy checks, final decoding
and failure cleanup retain their original owners.

The new allowance can accommodate the retained 101-ID content shapes from BOS;
it guarantees neither completion nor reconstruction. Generic prepared v3 consumes
a different checkpoint type and is not a way to relabel the role checkpoint.
This adds no counted grammar, native conditioning-space compatibility or new
8D/768D/4096D decoder profile.

The 67-case cohort contains 61 owning cases (18 retained and 43 added)
and six existing policy regressions. The allowance 511 case emits 100 scripted
IDs; this is not a 511-step observation. It uses genuine source-factory/pin checks,
token/scope/completion-budget selection and typed decoding for a fictional 101-ID
formula. Checkpoints, 537-score arrays, sessions and most outer-operation seams
are authored simulations. These tests establish no actual model restore or
forward, new training, statutory fidelity, graph or Lean admission. All three failed
predecessors remain retained and unqualified, with their original custody closed.

**Separate current-main integration:** [the fresh public-source qualification](../../../../../docs/autoformalization/evidence/legal-ir-bos-generation-v2-current-main-20261022.json) passed67 cases/201 phases with43 current sources/66 outer guards,30 raw compiled/executed bodies and29 module aliases. It reuses the exact original owner/test postimages and retains the original67-case result as a distinct generation. Original native/storage/source READ closed, retaining10 files/115,612bytes. Checkpoints, numerical sessions and score arrays remain authored controls; actual restores/forwards/training stay zero. At this public dependency generation, genuine prepared-v3 numerical dispatch still requires the separately identified compact/content batch and codec extension. Its guards remain intact; this capacity result supplies no full-runtime or legal reconstruction qualification.

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

## Forced-singleton lookahead successor, v2

The separate `legal_compact_content_completion_budget_v2` composes the unchanged
v1 budget, scope and token owners. Each old allowed choice consumes one ID;
only mandatory singleton continuations are then inspected, up to an explicit
0..16 forced-suffix horizon (default8). EOS consumes an ID. Horizon0 preserves
the exact old mask without post-choice probes. A typed terminal EOS supplies a
completion witness. An incomplete empty old-policy frontier permits removal;
branches and exhausted horizons remain unknown. Probe tokens never enter the
model's generated history. This is bounded local feasibility.

The [pure qualification](../../../../../docs/autoformalization/evidence/legal-ir-completion-forced-lookahead-qualification-20261023.json)
records41 authored cases/123 passed phases with accepted original source,
native and storage closeout. Its source profile observed20 product modules,
the frozen-root bootstrap and selected test, with2 separate namespace entries
and23 compile buffers. Test-root/unit initializers and the old helper's
separately unobserved origin/buffer are outside its qualification. The original
manifest and explicit clarification are retained. No Torch, model, checkpoint,
training, source encoder, database or Lean operation ran in that pure cohort.

The separate [accepted consumer qualification](https://github.com/endomorphosis/ipfs_datasets_py/blob/main/docs/autoformalization/evidence/legal-ir-compact-persistent-forced-lookahead-generation-20261023.json) passed2 cases/6 phases and retained4 calls across2 exposed authored source rows and both conditioning modes, with unchanged weights/inputs,100-ID cap and horizon8. All4 outputs blocked: typed candidates, exact token-ID matches and exact compact-content matches remain0/4. Emitted lengths are31/31 for every_step and49/49 for first_step. Actual work was162 GRU forwards including2 independent BOS references,160 selections,6 model constructions/12 state installations and zero training/optimizer work. All4 outputs were durable before reference comparison; original source/native/storage custody closed. This delays the retained dead end without establishing a valid completion, conditioning winner or reconstruction gain. The pure portable's earlier combined-bundle-pending flag remains a historical cutoff; this accepted consumer and joint source selection supersede that queue state without changing the pure qualification scope.

If autonomous outputs remain blocked, the next policy intervention is a bounded
branch-aware completion witness or beam using the same retained weights,
contexts and100-ID cap. Qualify its owner separately, preserve every old policy
and failed prefix, and count unknowns and all enrolled failures. Do not infer
global completion or a conditioning winner from this local filter.

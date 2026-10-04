# Semantic round-trip composition protocol

## Status and scope

This document freezes `SemanticRoundTripCompositionProtocol@1`. It is the
selection protocol for the fair constructor-by-realizer experiment that
follows the preliminary semantic logic round-trip pilot. A result that
deviates from this protocol is a new experiment and must not be pooled with,
or presented as, a result from this protocol.

The experiment asks which eligible composition minimizes semantic
reconstruction loss through this source-withheld path:

```text
T0 source
  -> constructor C
  -> L1 canonical IR
  -> realizer R (T0 withheld)
  -> T1 reconstruction
  -> the same constructor C
  -> L2 canonical IR
```

“The same constructor” means the same implementation identity, version,
prompt identity, configuration, model settings, and case-independent resource
limits. It does not permit replaying a private record from the first
constructor call.

The machine-readable block at the end of this document is normative. The
prose explains that contract and the contract test prevents either
representation from silently weakening the frozen rules.

## Experimental unit and matrix

Before case execution, the run manifest must freeze:

- the ordered corpus and its content identity;
- the complete constructor and realizer inventories and their identities;
- every constructor-by-realizer pair;
- capability exclusions, with a reason independent of case outcomes;
- the positive repeat count, run seed, model settings, prompts, canonical-IR
  schema, resource limits, retry policy, and cache mode.

Every capability-compatible constructor is crossed with every
capability-compatible realizer through the common canonical IR. A pair may be
excluded only before execution because a declared interface or capability is
unavailable. Semantic performance, an observed failure, native ancestry, or
expected quality is not a valid exclusion reason. An excluded pair is
reported but is not ranked. Once a pair is eligible and scheduled, all of its
case/repeat coordinates remain in its denominator.

The experimental unit is one `(case, repeat, constructor, realizer)`
coordinate. Every eligible composition receives the same cases and repeat
count. If any eligible component is stochastic, the repeat count must be at
least three. Deterministic results are still retained at every scheduled
coordinate; they are not given a different denominator.

## Canonical boundary and information flow

`L1` and `L2` each contain exactly `{"rules": [...]}`. Each rule has exactly
these fields:

- `modality`: one of `O` (obligation), `P` (permission), or `F`
  (prohibition);
- `actor`, `action`, and `object`: closed-vocabulary strings;
- `conditions`, `exceptions`, and `temporal`: canonicalized
  closed-vocabulary string arrays.

The constructor may receive `T0`, the case's frozen closed atom vocabulary,
and its frozen public configuration. The realizer may receive only `L1`, that
same vocabulary, and its frozen public configuration. In particular, the
realizer may not receive, retrieve, infer through a cache key, or be prompted
with:

- `T0` or any source excerpt;
- adjudicated gold IR, a gold rule count, gold-derived hints, or hidden case
  fields;
- a native compiler/converter record, parse tree, private payload, trace, or
  source-bearing metadata produced during the first constructor call;
- a prior reconstruction or result selected using gold or validator output.

The second constructor call receives only `T1`, the same allowed vocabulary,
and the exact frozen constructor configuration used for the first call. A
fresh call namespace is required; private first-call state is not an input.

The closed atom vocabulary is an explicit, corpus-frozen benchmark aid and is
the only allowed gold-derived execution input. Gold IR itself is revealed
only after a coordinate has reached a terminal outcome, and only to the
scorer and gates. Rule limits, token limits, timeouts, retries, context
windows, stopping rules, prompt length, and every other budget must be fixed
without inspecting gold IR or using gold rule counts. Observable source
length must not select a different budget for one arm; any preregistered
source-length strata must apply the same public rule to every arm.

## Semantic score and primary loss

Rules are compared by exact maximum-weight one-to-one bipartite assignment.
The per-rule structural weights are:

| Facet | Weight |
|---|---:|
| modality | 0.25 |
| actor | 0.15 |
| action | 0.20 |
| object | 0.10 |
| conditions | 0.10 |
| exceptions | 0.10 |
| temporal | 0.10 |

Scalar facets use exact equality. Array facets use set Jaccard similarity.
The assigned weights are summed and divided by the larger rule count (or one
when both sides are empty), so missing and extra rules reduce the score.

For a successful, schema-valid, non-empty coordinate, the primary
end-to-end loss is:

```text
loss_e2e(case, repeat, C, R) = 1 - S(gold IR, L2)
```

The following all have primary, forward, and cycle loss `1.0`: timeout,
exception, exhausted retry, unavailable capability discovered after
scheduling, missing output, invalid output, an empty `L1`, empty/blank `T1`,
or an empty `L2`. Such coordinates are never dropped, retried outside the
frozen policy, imputed from another repeat, or replaced by a conditional
successful-case mean.

Forward loss `1 - S(gold IR, L1)` and cycle loss `1 - S(L1, L2)` are mandatory
diagnostics. They never replace or modify primary loss: a composition can
reconstruct its own incorrect interpretation exactly.

## Per-case-first repeat aggregation

Aggregation gives every case equal weight, regardless of rule count, source
length, number of successful repeats, or latency:

```text
case_loss(c, C, R) =
    arithmetic_mean(loss_e2e(c, r, C, R) for every scheduled repeat r)

primary_loss(C, R) =
    arithmetic_mean(case_loss(c, C, R) for every frozen corpus case c)
```

Repeats are therefore averaged within a case before case means are averaged.
Pooling rules, pooling only successful repeats, weighting cases by their rule
counts, or first averaging all successful observations is prohibited.
Forward and cycle diagnostics use the same per-case-first aggregation and
failure policy. Conditional successful-only summaries may be shown if
clearly labeled, but they are not selection evidence.

## Selection gates

Loss is always reported. A composition is selection-eligible only if all
three fail-closed gates pass across every scheduled case/repeat coordinate:

1. **Full coverage:** every coordinate terminates successfully with
   schema-valid, non-empty `L1`, non-blank `T1`, and schema-valid, non-empty
   `L2`.
2. **Polarity preservation:** in the maximum-weight assignment of gold IR to
   `L2`, every assigned rule has identical `O`/`P`/`F` modality. Missing and
   extra rules remain penalized by semantic loss; they do not excuse an
   observed obligation/permission/prohibition inversion.
3. **Source-copy exclusion:** after lowercasing, tokenization, whitespace
   normalization, and the benchmark's plural normalization, `T1` must not
   equal `T0`, and the multiset overlap precision of source eight-token
   n-grams in `T1` must be strictly less than `0.80`. For an output with no
   eight-token n-grams, precision is zero; exact normalized copying still
   fails.

A gate failure does not delete a score or turn it into missing data. It marks
the composition ineligible and records every failing coordinate and reason.
Among eligible compositions, the composition with the lowest primary loss is
selected. Exact numeric ties remain co-winners; latency, proof success, and
resource use are reported separately and do not silently break a semantic
tie. If no composition passes all gates, the protocol selects none.

## Identical model settings and balanced order

All calls to the same physical model service use an identical frozen
inference envelope: endpoint and backend identity, model and tokenizer,
context size, decoding parameters, per-repeat seed policy, output-token
limit, grammar/schema mode where the call role supports it, stop conditions,
timeout, retry policy, concurrency, and cache mode. Prompts may implement
different declared constructor or realizer roles, but their templates and
content identities are frozen before execution. A routing wrapper over the
same endpoint is not treated as independent model evidence.

Execution order is frozen before outcomes exist. Within each case/repeat
block, eligible stochastic compositions use a seeded, outcome-independent
counterbalanced order. Across the complete run, the count for any
composition in any ordinal position may differ from another composition's
count in that position by at most one. The exact planned and observed orders
are recorded. A shared one-slot service is executed serially. Scheduling may
not group the expected best arm first, change after a failure, or reuse an
output across compositions or repeats.

## Semantic scoring versus proof validation

Semantic scoring and selection gates run on immutable `L1`, `T1`, and `L2`
artifacts. Only after those artifacts and their semantic scores are bound may
Hammer/cvc5, Lean, or another preregistered proof validator run.

Proof validation answers a narrower question, such as whether non-empty
canonical `L1` and `L2` are formally identical under the validator's supported
encoding. It does not prove that either IR is faithful to `T0` or gold IR.
Empty/empty identity is vacuous and never counts as proof success.

Validator output is a post-hoc annotation. It may not generate, repair,
choose, rerank, retry, or reject a reconstruction; change semantic scores,
losses, denominators, gates, or the selected composition; or substitute proof
success for semantic fidelity. Validator failure remains visible but does not
rewrite an already terminal semantic outcome.

## Reporting requirements

The report retains the frozen manifest and one terminal record for every
eligible case/repeat/composition coordinate. It reports per-coordinate
forward, cycle, and end-to-end losses; failure and gate reasons; per-case
repeat means; the unweighted across-case primary mean; conditional summaries
only under an explicit label; planned and observed execution order; model and
component identities; budgets; source-copy measurements; and separate
post-hoc validator receipts. Latency, model calls, resource use, and proof
results are separate axes and are never folded into semantic loss.

## Machine-readable normative contract

```json
{
  "interface": "SemanticRoundTripCompositionProtocol@1",
  "status": "frozen",
  "experiment": {
    "path": [
      "t0_source",
      "constructor",
      "l1_canonical_ir",
      "realizer",
      "t1_reconstruction",
      "same_constructor",
      "l2_canonical_ir"
    ],
    "matrix": "all_preregistered_capability_compatible_constructor_realizer_pairs",
    "exclusion_timing": "before_case_execution",
    "exclusion_basis": "declared_interface_or_capability_only",
    "coordinate": [
      "case",
      "repeat",
      "constructor",
      "realizer"
    ],
    "same_cases_and_repeat_count_for_all_eligible_pairs": true,
    "minimum_repeats_when_any_component_is_stochastic": 3
  },
  "canonical_ir": {
    "top_level_keys": [
      "rules"
    ],
    "modalities": [
      "O",
      "P",
      "F"
    ],
    "rule_fields": [
      "modality",
      "actor",
      "action",
      "object",
      "conditions",
      "exceptions",
      "temporal"
    ],
    "list_fields": [
      "conditions",
      "exceptions",
      "temporal"
    ]
  },
  "information_boundary": {
    "constructor_inputs": [
      "source_text",
      "allowed_atom_vocabulary",
      "frozen_constructor_config"
    ],
    "realizer_inputs": [
      "l1_canonical_ir",
      "allowed_atom_vocabulary",
      "frozen_realizer_config"
    ],
    "second_constructor_inputs": [
      "t1_reconstruction",
      "allowed_atom_vocabulary",
      "same_frozen_constructor_config"
    ],
    "realizer_forbidden": [
      "source_text_or_excerpt",
      "gold_ir_or_gold_rule_count",
      "native_constructor_record_or_parse",
      "hidden_case_fields",
      "source_bearing_cache_or_metadata",
      "prior_reconstruction_or_outcome"
    ],
    "only_allowed_gold_derived_execution_input": "frozen_allowed_atom_vocabulary",
    "gold_ir_available_only_after_terminal_outcome_for_scoring_and_gates": true,
    "fresh_second_constructor_call_namespace": true
  },
  "budgets": {
    "frozen_before_execution": true,
    "gold_derived_budgets_forbidden": true,
    "forbidden_budget_inputs": [
      "gold_ir",
      "gold_rule_count",
      "gold_content",
      "validator_output",
      "observed_semantic_outcome"
    ],
    "same_public_budget_rule_for_every_arm": true
  },
  "semantic_score": {
    "assignment": "exact_maximum_weight_one_to_one_bipartite",
    "denominator": "max_reference_candidate_rule_count_or_one",
    "scalar_facet_similarity": "exact_equality",
    "list_facet_similarity": "set_jaccard",
    "weights": {
      "modality": 0.25,
      "actor": 0.15,
      "action": 0.2,
      "object": 0.1,
      "conditions": 0.1,
      "exceptions": 0.1,
      "temporal": 0.1
    }
  },
  "loss": {
    "primary": "one_minus_semantic_score_gold_ir_vs_l2",
    "forward_diagnostic": "one_minus_semantic_score_gold_ir_vs_l1",
    "cycle_diagnostic": "one_minus_semantic_score_l1_vs_l2",
    "terminal_failure_loss": 1.0,
    "failure_outcomes": [
      "timeout",
      "exception",
      "retry_exhausted",
      "post_schedule_capability_unavailable",
      "missing_output",
      "invalid_output",
      "empty_l1",
      "blank_t1",
      "empty_l2"
    ],
    "successful_only_primary_summary_forbidden": true
  },
  "aggregation": {
    "repeat_within_case": "arithmetic_mean_over_all_scheduled_repeats",
    "case_across_corpus": "unweighted_arithmetic_mean_over_all_frozen_cases",
    "order": "per_case_first",
    "rule_count_weighting_forbidden": true,
    "failed_repeat_dropping_forbidden": true,
    "applies_to": [
      "primary",
      "forward_diagnostic",
      "cycle_diagnostic"
    ]
  },
  "gates": {
    "all_required_for_selection": true,
    "full_coverage": {
      "scope": "every_scheduled_case_repeat_coordinate",
      "requires": [
        "terminal_success",
        "nonempty_schema_valid_l1",
        "nonblank_t1",
        "nonempty_schema_valid_l2"
      ]
    },
    "polarity_preservation": {
      "comparison": "gold_ir_vs_l2_maximum_weight_assignment",
      "requirement": "all_assigned_rule_modalities_equal"
    },
    "source_copy_exclusion": {
      "exact_normalized_copy_forbidden": true,
      "ngram_width_tokens": 8,
      "shared_source_ngram_precision_must_be_below": 0.8
    }
  },
  "model_fairness": {
    "same_physical_service_is_not_independent_evidence": true,
    "identical_frozen_fields": [
      "endpoint_backend_identity",
      "model_tokenizer_identity",
      "context_size",
      "decoding_parameters",
      "per_repeat_seed_policy",
      "output_token_limit",
      "role_supported_grammar_schema_mode",
      "stop_conditions",
      "timeout",
      "retry_policy",
      "concurrency",
      "cache_mode"
    ],
    "prompt_templates_and_content_ids_frozen_before_execution": true
  },
  "order": {
    "planned_before_outcomes": true,
    "algorithm": "seeded_outcome_independent_counterbalanced_blocks",
    "scope": "eligible_stochastic_compositions_within_case_repeat_blocks",
    "maximum_ordinal_position_count_imbalance": 1,
    "record_planned_and_observed_order": true,
    "shared_one_slot_model_execution": "serial",
    "outcome_adaptive_scheduling_forbidden": true,
    "cross_coordinate_output_reuse_forbidden": true
  },
  "selection": {
    "eligible_only_if_all_gates_pass": true,
    "criterion": "minimum_primary_loss",
    "exact_numeric_ties": "co_winners",
    "no_eligible_compositions": "select_none",
    "latency_resources_and_proofs_are_separate_axes": true
  },
  "proof_validation": {
    "phase": "post_hoc_after_artifact_and_semantic_score_binding",
    "role": "annotation_only",
    "nonvacuous_inputs_required": true,
    "semantic_fidelity_authority": false,
    "may_change_semantic_score_loss_denominator_gates_or_selection": false,
    "may_generate_repair_choose_rerank_retry_or_reject_candidate": false,
    "validator_failure_remains_visible": true
  }
}
```

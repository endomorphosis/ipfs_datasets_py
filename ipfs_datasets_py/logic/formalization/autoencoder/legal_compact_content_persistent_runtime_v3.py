"""Explicit conservative branch-selection consumer for unchanged checkpoints.

One original-policy root observation and all selector inspections share a
finite allowance for this call. Only an actual scored selection enters model
history. A terminal no-selection forward is retained without appending a token.
Historical runtimes, checkpoints, witness and selector owners remain separate.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path

from . import legal_compact_content_persistent_runtime_v1 as legacy

training = legacy.training
SCHEMA = "legal-compact-persistent-bos-generation/v3"
PROFILE = "authored384-persistent-fixed537-bos100-branch-selection/v3"
MAX_NEW_TOKENS = legacy.MAX_NEW_TOKENS
MAX_REPORT_BYTES = legacy.MAX_REPORT_BYTES
MAX_PREFIX_INSPECTIONS_PER_DECISION = 1024
MAX_PREFIX_INSPECTIONS_PER_GENERATION = 1 + MAX_NEW_TOKENS * MAX_PREFIX_INSPECTIONS_PER_DECISION
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_LEGACY_SHA = "1978436fed3bbee1b97ad3e720fc54806fa078d98bb91adac9b26ac212792615"
_CORE_SHA = "38387c5573c42a03f41c99f6fbedf6a70f0755f3ac564990cafa481498c52e7f"
_SELECTOR_SHA = "f443d7a9e498fe27802fa0fbd31f14a3bf504821be2ff2626d2efb752a91d0ce"
_POLICY = "score-ranked-dead-end-only-branch-selection/v1"
_AUTHORITY = legacy._AUTHORITY
_LIMITATIONS = [*legacy._LIMITATIONS,
    "Only retained closed original-policy dead-end certificates remove choices; UNKNOWN and unqueried choices remain eligible.",
    "Prefix inspections have a cumulative per-call allowance; final typed decoding is separately reported and performs no completion search.",
    "A terminal no-selection decision consumes one numerical forward and the offered prefix, but appends no token.",
    "Proof suffixes are not appended, fed as model history, scored as reconstruction or used as training labels.",
    "A syntactic witness or constrained selection establishes no learned quality, source fidelity or legal correctness.",
]
_need = legacy._need
_authority = legacy._authority


def _pins():
    _need(type(legacy.__file__) is str and Path(legacy.__file__).absolute() ==
          _SELF_PATH.with_name("legal_compact_content_persistent_runtime_v1.py"),
          "canonical immutable v1 runtime required")
    expected = training.base._source(_SELF_PATH.with_name("legal_compact_content_persistent_runtime_v1.py"), _LEGACY_SHA)
    inherited = legacy._pins()
    _need(expected in inherited, "original runtime source pin absent")
    return [*inherited, training.base._source(_SELF_PATH, _SELF_SHA),
        training.base._source(_SELF_PATH.with_name("legal_compact_content_completion_budget_v3.py"), _CORE_SHA),
        training.base._source(_SELF_PATH.with_name("legal_compact_content_branch_selection_v1.py"), _SELECTOR_SHA)]


def generate_from_bos(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
        expected_context_sha256, expected_conditioning_mode, expected_source_space, max_new_tokens,
        max_prefix_inspections_per_decision, max_prefix_inspections_per_generation):
    """Emit at most100 scored IDs with an explicit cumulative grammar budget.

    The initial original-policy root costs one inspection and preserves the
    no-model empty-root path. Every subsequent selector decision includes its
    own root. No post-selection or final prefix query is performed. Final typed
    decoding validates the actual history without spending a search inspection.
    """
    initial_pins = _pins()
    selector = importlib.import_module(__package__ + ".legal_compact_content_branch_selection_v1")
    old_budget = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v1")
    _need(type(selector.__file__) is str and Path(selector.__file__).absolute() ==
          _SELF_PATH.with_name("legal_compact_content_branch_selection_v1.py"),
          "canonical branch-selection dependency required")

    def work(data, head, loaded, adapter):
        _need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= MAX_NEW_TOKENS,
              "explicit new-token allowance must be a plain integer in1..100")
        _need(type(data["max_prefix_inspections_per_decision"]) is int and
              1 <= data["max_prefix_inspections_per_decision"] <= MAX_PREFIX_INSPECTIONS_PER_DECISION,
              "explicit decision allowance must be a plain integer in1..1024")
        _need(type(data["max_prefix_inspections_per_generation"]) is int and
              1 <= data["max_prefix_inspections_per_generation"] <= MAX_PREFIX_INSPECTIONS_PER_GENERATION,
              "explicit cumulative allowance must be a plain integer in1..102401")
        training.base._hash(data["expected_context_sha256"], "generation context")
        raw = data["context_raw"]
        _need(type(raw) is bytes and 0 < len(raw) <= 512*1024 and
              hashlib.sha256(raw).hexdigest() == data["expected_context_sha256"],
              "exact bounded context bytes required")
        vector = head._conditioning(data["conditioning"])
        value, _ = training._checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"],
            data["expected_conditioning_mode"], data["expected_source_space"], head, loaded)
        scope, helper, tokens, old_budget_pins = old_budget._owners()
        core, selected_old, selected_scope, selected_helper, selected_tokens, selector_pins = selector._owners()
        expected_selector_pins = [*old_budget_pins,
            helper._source(_SELF_PATH.with_name("legal_compact_content_completion_budget_v3.py"), _CORE_SHA),
            helper._source(_SELF_PATH.with_name("legal_compact_content_branch_selection_v1.py"), _SELECTOR_SHA)]
        _need((selected_old, selected_scope, selected_helper, selected_tokens) ==
              (old_budget, scope, helper, tokens) and selector_pins == expected_selector_pins,
              "generation and selector owners disagree")
        _need(tokens is loaded["modules"]["tokens"] and helper is loaded["modules"]["selection"]
              and selector.POLICY == _POLICY and selector.MAX_REPORT_BYTES == 2*1024**2,
              "generation and selector must use the same bounded token/selection owners")
        options = dict(expected_context_sha256=data["expected_context_sha256"], codec=value["codec"],
                       expected_codec_sha256=value["codec_sha256"])
        view = legacy._serving(value, head)
        view_identity = head._fingerprint(view)
        torch = head._torch(loaded)
        rng = torch.get_rng_state().clone()
        runtime = training.base._runtime(head, loaded)
        model, state, weights_identity = None, None, None
        current, emitted, trace = [1], [], []
        terminal_trace = None
        trace_bytes, numerical_forwards = 0, 0
        actual_inspections, decision_inspections, witness_calls = 0, 0, 0
        failure = None

        def guard():
            _need(_pins() == initial_pins and head._fingerprint(view) == view_identity,
                  "serving source or captured model view changed")
            head._closing(loaded)
            owners = old_budget._owners()
            _need(owners[:3] == (scope, helper, tokens) and owners[3] == old_budget_pins,
                  "original completion-budget dependency custody changed")
            _need(selector._owners() == (core, old_budget, scope, helper, tokens, selector_pins),
                  "branch-selector dependency custody changed")
            _need(training.base._runtime(head, loaded) == runtime and torch.equal(rng, torch.get_rng_state()),
                  "generation changed runtime or ambient CPU RNG")
            if model is not None:
                _need(adapter.tensor_digest(model) == weights_identity, "generation changed private model parameters")

        try:
            guard()
            initial_prefix = old_budget.allowed_token_ids(current, raw,
                remaining_new_tokens=data["max_new_tokens"], **options)
            actual_inspections = 1
            _authority(initial_prefix)
            _need(initial_prefix["schema"] == old_budget.PREFIX_SCHEMA and
                  initial_prefix["policy"] == old_budget.POLICY and
                  initial_prefix["owner_pins"] == old_budget_pins and
                  initial_prefix["offered_ids"] == current and
                  initial_prefix["remaining_new_tokens"] == data["max_new_tokens"] and
                  initial_prefix["context_raw_sha256"] == data["expected_context_sha256"] and
                  initial_prefix["codec_sha256"] == value["codec_sha256"] and
                  initial_prefix["global_completability_proven"] is False,
                  "initial original-policy root identity differs")
            guard()
            status, reason = "blocked", initial_prefix["reason"] or initial_prefix["status"]
            while initial_prefix["allowed_token_ids"] and len(emitted) < data["max_new_tokens"]:
                remaining_inspections = data["max_prefix_inspections_per_generation"] - actual_inspections
                if remaining_inspections == 0:
                    status, reason = "grammar_budget_exhausted", "cumulative_prefix_inspection_limit"
                    break
                # Reserve a complete maximum-sized selector report before any
                # forward. Previous reports use their actual retained sizes;
                # reserve is not multiplied by hypothetical future decisions.
                reserve = 2*len(raw) + 4*1024**2 + len(head._wire(initial_prefix, MAX_REPORT_BYTES))
                next_trace_bound = selector.MAX_REPORT_BYTES + 537*32 + 16384
                if trace_bytes + next_trace_bound + reserve > MAX_REPORT_BYTES:
                    status, reason = "report_budget_exhausted", "complete_generation_report_limit"
                    break
                allowance = min(data["max_prefix_inspections_per_decision"], remaining_inspections)
                guard()
                if model is None:
                    model = training._restore(view, head, loaded, adapter, with_optimizer=False)
                    weights_identity = adapter.tensor_digest(model)
                    with torch.no_grad():
                        state = model.start(model.project(torch.tensor([vector], dtype=torch.float32)))
                input_ids = [1] if not emitted else [emitted[-1]]
                with torch.no_grad():
                    logits, state = model.next_logits(torch.tensor([input_ids], dtype=torch.long), state)
                    scores = logits[0, -1].tolist()
                numerical_forwards += 1
                _need(list(logits.shape) == [1, 1, 537] and type(scores) is list and len(scores) == 537
                      and all(type(x) is float and math.isfinite(x) for x in scores)
                      and state[2].tolist() == [len(current)],
                      "incremental full537 output or prefix position differs")
                guard()
                selected = selector.select_token(scores, current, raw,
                    remaining_new_tokens=data["max_new_tokens"]-len(emitted),
                    max_prefix_inspections=allowance, **options)
                _authority(selected)
                token, used = selected["selected_token_id"], selected["actual_prefix_inspections"]
                _need(type(used) is int and 1 <= used <= allowance and
                      selected["root_prefix_inspections"] == 1 and
                      selected["candidate_prefix_inspections"] == used-1 and
                      selected["remaining_prefix_inspections"] == allowance-used and
                      type(selected["witness_calls"]) is int and 0 <= selected["witness_calls"] <= used-1,
                      "selector inspection accounting differs")
                _need(selected["schema"] == selector.SCHEMA and selected["policy"] == _POLICY and
                      selected["owner_pins"] == selector_pins and
                      selected["offered_prefix_ids"] == current and selected["logits"] == scores and
                      selected["logits_sha256"] == head._digest(scores) and
                      selected["max_prefix_inspections"] == allowance and
                      selected["context_raw_sha256"] == data["expected_context_sha256"] and
                      selected["context_sha256"] == initial_prefix["context_sha256"] and
                      selected["codec_sha256"] == value["codec_sha256"] and
                      selected["baseline_prefix_report"]["owner_pins"] == old_budget_pins and
                      selected["baseline_prefix_report"]["offered_ids"] == current and
                      selected["baseline_prefix_report"]["remaining_new_tokens"] == data["max_new_tokens"]-len(emitted) and
                      selected["unknown_and_unqueried_choices_retained"] is True and
                      selected["witness_suffix_injected"] is False and
                      selected["model_or_future_score_queries"] is False and
                      selected["global_completability_proven"] is False,
                      "public branch selection or full score binding differs")
                actual_inspections += used
                decision_inspections += used
                witness_calls += selected["witness_calls"]
                observation = dict(prefix_ids=list(current), input_token_ids=input_ids, logits=scores,
                    logits_sha256=head._digest(scores), selection_report=selected,
                    selected_token_id=token, raw_argmax_token_id=selected["raw_argmax_token_id"],
                    consumed_prefix_positions=state[2].tolist())
                trace_bytes += len(head._wire(observation, MAX_REPORT_BYTES)) + 2
                if token is None:
                    _need(selected["status"] == "no_selection" and
                          selected["selection_performed"] is False and selected["tokens_appended"] == 0 and
                          selected["allowed_token_ids"] == [] and selected["next_prefix_ids"] == current,
                          "terminal no-selection decision differs")
                    terminal_trace = observation
                    status, reason = "blocked", selected["reason"]
                    break
                _need(selected["status"] == "selected" and selected["selection_performed"] is True and
                      selected["tokens_appended"] == 1 and type(token) is int and
                      token in selected["allowed_token_ids"] and selected["next_prefix_ids"] == current+[token],
                      "public selected token differs")
                trace.append(observation)
                emitted.append(token)
                current.append(token)
                guard()
                if token == tokens.EOS_ID:
                    status, reason = "complete", None
                    break
            else:
                if emitted and len(emitted) == data["max_new_tokens"]:
                    status, reason = "step_budget_exhausted", "max_new_tokens_reached"
            # This original typed decode checks only actual emitted IDs. It is
            # not another allowed-token query or hypothetical suffix search.
            decoded = tokens.decode_compact_content_tokens_v1(current, raw, **options)
            _authority(decoded)
            _need(decoded["generated_ids"] == current and
                  decoded["context_raw_sha256"] == data["expected_context_sha256"] and
                  decoded["codec_sha256"] == value["codec_sha256"] and
                  decoded["context_sha256"] == initial_prefix["context_sha256"] and
                  (status == "complete") == (decoded["status"] == "valid_candidate"),
                  "generation disposition disagrees with the original typed decoder")
            terminal_count = int(terminal_trace is not None)
            _need(numerical_forwards == len(emitted)+terminal_count and
                  actual_inspections == 1+decision_inspections and
                  actual_inspections <= data["max_prefix_inspections_per_generation"] and
                  (state is None or state[2].tolist() == [len(current)-1+terminal_count]),
                  "selected/terminal forward, state or cumulative inspection accounting differs")
            guard()
            return dict(schema=SCHEMA, profile=PROFILE, status=status, reason=reason,
                checkpoint_sha256=data["expected_checkpoint_sha256"], weights_sha256=value["weights_sha256"],
                codec_sha256=value["codec_sha256"], conditioning_mode=value["conditioning_mode"], source_space=value["source_space"],
                context_raw_sha256=data["expected_context_sha256"], conditioning_sha256=head._digest(data["conditioning"]),
                initial_prefix_ids=[1], generated_ids=current, selected_token_ids=emitted, trace=trace,
                initial_prefix_report=initial_prefix, terminal_no_selection_trace=terminal_trace,
                selected_token_decisions=len(emitted), terminal_no_selection_decisions=terminal_count,
                selector_decision_count=numerical_forwards, final_decoding=decoded,
                grammar_accounting=dict(initial_root_prefix_inspections=1,
                    decision_prefix_inspections=decision_inspections, actual_prefix_inspections=actual_inspections,
                    remaining_prefix_inspections=data["max_prefix_inspections_per_generation"]-actual_inspections,
                    max_prefix_inspections_per_decision=data["max_prefix_inspections_per_decision"],
                    max_prefix_inspections_per_generation=data["max_prefix_inspections_per_generation"],
                    witness_calls=witness_calls), final_typed_decode_count=1,
                model_restore_count=int(model is not None), model_construction_count=int(model is not None),
                state_installation_count=2*int(model is not None), numerical_forward_count=numerical_forwards,
                state_positions_consumed=int(state[2][0]) if state is not None else 0,
                live_checkpoint_runtime_verified=True, model_executed=model is not None,
                optimizer_constructed=False, optimizer_state_restored=False, training_executed=False,
                serving_view_fields=sorted(view), serving_view_sha256=head._digest(view, training.MAX_CHECKPOINT_BYTES),
                serving_view_contains_optimizer_state=False, serving_view_contains_population=False,
                serving_view_contains_training_targets=False, supplied_prefix_target_access=False,
                context_permission_verified=False, source_encoder_authenticated=False,
                actual_model_inputs=["conditioning_vector", "fixed_BOS_and_generated_token_IDs"],
                settings=dict(max_new_tokens=data["max_new_tokens"], max_total_ids=512, eos_counted_in_new_token_budget=True,
                    incremental_hidden_state=True, cross_call_model_cache=False, budget_policy=selector.POLICY,
                    max_prefix_inspections_per_decision=data["max_prefix_inspections_per_decision"],
                    max_prefix_inspections_per_generation=data["max_prefix_inspections_per_generation"],
                    branch_selection_opt_in=True, unknown_and_unqueried_choices_retained=True,
                    witness_suffix_injected=False, initial_root_charged=True, post_selection_prefix_queries=0,
                    final_prefix_queries=0, final_typed_decode_is_separate=True, old_budget_policy=old_budget.POLICY,
                    max_search_depth=core.MAX_SEARCH_DEPTH, max_frontier_nodes=core.MAX_FRONTIER_NODES,
                    report_limit_bytes=MAX_REPORT_BYTES), budget_owner_pins=selector_pins,
                authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
        except BaseException as error:
            failure = error
            raise
        finally:
            head._finish(failure, guard)

    failure = None
    try:
        _need(_pins() == initial_pins, "generation source changed during selector import")
        return training._operation(dict(checkpoint=checkpoint, conditioning=conditioning, context_raw=context_raw,
            expected_checkpoint_sha256=expected_checkpoint_sha256, expected_context_sha256=expected_context_sha256,
            expected_conditioning_mode=expected_conditioning_mode, expected_source_space=expected_source_space,
            max_new_tokens=max_new_tokens, max_prefix_inspections_per_decision=max_prefix_inspections_per_decision,
            max_prefix_inspections_per_generation=max_prefix_inspections_per_generation), work)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_pins() == initial_pins, "generation source changed during operation")
        except BaseException as error:
            if failure is not None:
                raise error from failure
            raise


def generation_sha256(report):
    """Bounded report identity only; no numerical or grammar replay qualification."""
    pins = _pins()
    head, source_pin = training.base._head()
    value = head._copy(report, MAX_REPORT_BYTES)
    _need(type(value) is dict and value.get("schema") == SCHEMA and value.get("profile") == PROFILE,
          "persistent generation-v3 report identity required")
    settings = value.get("settings")
    _need(type(settings) is dict and type(settings.get("max_new_tokens")) is int and
          1 <= settings["max_new_tokens"] <= MAX_NEW_TOKENS and
          type(settings.get("max_prefix_inspections_per_decision")) is int and
          1 <= settings["max_prefix_inspections_per_decision"] <= MAX_PREFIX_INSPECTIONS_PER_DECISION and
          type(settings.get("max_prefix_inspections_per_generation")) is int and
          1 <= settings["max_prefix_inspections_per_generation"] <= MAX_PREFIX_INSPECTIONS_PER_GENERATION and
          settings.get("budget_policy") == _POLICY and settings.get("branch_selection_opt_in") is True and
          settings.get("unknown_and_unqueried_choices_retained") is True and
          settings.get("witness_suffix_injected") is False and settings.get("initial_root_charged") is True and
          type(settings.get("post_selection_prefix_queries")) is int and settings["post_selection_prefix_queries"] == 0 and
          type(settings.get("final_prefix_queries")) is int and settings["final_prefix_queries"] == 0 and
          settings.get("final_typed_decode_is_separate") is True,
          "explicit generation-v3 policy and bounded cumulative allowance identity required")
    result = head._digest(value, MAX_REPORT_BYTES)
    _need(_pins() == pins and training.base._sources() == source_pin and
          head._digest(head._copy(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES) == result,
          "source or original report changed during hashing")
    return result


__all__ = ["generate_from_bos", "generation_sha256"]

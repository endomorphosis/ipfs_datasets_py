"""Explicit forced-lookahead consumer for the unchanged persistent checkpoint.

This version changes the opt-in grammar selection policy only. The v1 runtime,
all checkpoints and the original incremental numerical lifetime remain separate.
Pure-policy qualification must close before an independently admitted replay.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path

from . import legal_compact_content_persistent_runtime_v1 as legacy

training = legacy.training
SCHEMA = "legal-compact-persistent-bos-generation/v2"
PROFILE = "authored384-persistent-fixed537-bos100-forced-lookahead/v2"
MAX_NEW_TOKENS = legacy.MAX_NEW_TOKENS
MAX_REPORT_BYTES = legacy.MAX_REPORT_BYTES
MAX_FORCED_TOKENS = 16
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_LEGACY_SHA = "1978436fed3bbee1b97ad3e720fc54806fa078d98bb91adac9b26ac212792615"
_POLICY_SHA = "e04e214be49eb17e87544b250b0308ca2b7adf35c01957afeb56b7e300b6db14"
_POLICY = "remaining-token-forced-singleton-lookahead/v1"
_AUTHORITY = legacy._AUTHORITY
_LIMITATIONS = [*legacy._LIMITATIONS,
    "This explicit successor policy probes forced grammar tokens only; probes are not generated tokens or numerical forwards.",
    "The horizon counts only forced suffix tokens after a candidate; branches and exhausted horizons remain unknown.",
    "A retained typed completion witness is syntactic and not a model-generated continuation, legal meaning or global completion proof.",
    "Historical v1 outputs are a separate frozen comparison, not recomputed by this consumer.",
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
        training.base._source(_SELF_PATH.with_name("legal_compact_content_completion_budget_v2.py"), _POLICY_SHA)]


def generate_from_bos(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
        expected_context_sha256, expected_conditioning_mode, expected_source_space, max_new_tokens,
        max_forced_tokens):
    """Emit at most100 IDs with an explicit bounded forced-lookahead horizon.

    There is no supplied-prefix or target argument. Blocked/exhausted results
    retain their exact IDs and typed-decoder disposition. A no-choice call
    allocates no model; it still validates the live checkpoint/runtime contract.
    """
    initial_pins = _pins()
    budget = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v2")
    old_budget = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v1")
    _need(Path(budget.__file__).absolute() == _SELF_PATH.with_name("legal_compact_content_completion_budget_v2.py"),
          "canonical completion-budget dependency required")

    def work(data, head, loaded, adapter):
        _need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= MAX_NEW_TOKENS,
              "explicit new-token allowance must be a plain integer in1..100")
        _need(type(data["max_forced_tokens"]) is int and 0 <= data["max_forced_tokens"] <= MAX_FORCED_TOKENS,
              "explicit forced-suffix horizon must be a plain integer in0..16")
        training.base._hash(data["expected_context_sha256"], "generation context")
        raw = data["context_raw"]
        _need(type(raw) is bytes and 0 < len(raw) <= 512*1024
              and hashlib.sha256(raw).hexdigest() == data["expected_context_sha256"], "exact bounded context bytes required")
        vector = head._conditioning(data["conditioning"])
        value, _ = training._checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"],
            data["expected_conditioning_mode"], data["expected_source_space"], head, loaded)
        scope, helper, tokens, old_budget_pins = old_budget._owners()
        budget_pins = [*old_budget_pins, helper._source(
            _SELF_PATH.with_name("legal_compact_content_completion_budget_v2.py"), _POLICY_SHA)]
        _need(tokens is loaded["modules"]["tokens"] and helper is loaded["modules"]["selection"],
              "generation and budget must use the same public token/selection owners")
        options = dict(expected_context_sha256=data["expected_context_sha256"], codec=value["codec"],
                       expected_codec_sha256=value["codec_sha256"])
        policy_options = dict(options, max_forced_tokens=data["max_forced_tokens"])
        view = legacy._serving(value, head)
        view_identity = head._fingerprint(view)
        torch = head._torch(loaded)
        rng = torch.get_rng_state().clone()
        runtime = training.base._runtime(head, loaded)
        model, state, weights_identity = None, None, None
        current, emitted, trace = [1], [], []
        trace_bytes, numerical_forwards = 0, 0
        failure = None

        def guard():
            _need(_pins() == initial_pins and head._fingerprint(view) == view_identity,
                  "serving source or captured model view changed")
            head._closing(loaded)
            owners = old_budget._owners()
            _need(owners[:3] == (scope, helper, tokens) and owners[3] == old_budget_pins,
                  "completion-budget dependency custody changed")
            _need(training.base._runtime(head, loaded) == runtime and torch.equal(rng, torch.get_rng_state()),
                  "generation changed runtime or ambient CPU RNG")
            if model is not None:
                _need(adapter.tensor_digest(model) == weights_identity, "generation changed private model parameters")

        def prefix():
            guard()
            remaining = data["max_new_tokens"] - len(emitted)
            report = budget.allowed_token_ids(current, raw, remaining_new_tokens=remaining, **policy_options)
            _authority(report)
            _need(report["schema"] == budget.PREFIX_SCHEMA and report["policy"] == budget.POLICY
                  and report["owner_pins"] == budget_pins and report["offered_ids"] == current
                  and report["remaining_new_tokens"] == remaining
                  and report["max_forced_tokens"] == data["max_forced_tokens"]
                  and report["forced_horizon_excludes_initial_choice"] is True
                  and report["baseline_prefix_report"]["owner_pins"] == old_budget_pins
                  and report["global_completability_proven"] is False
                  and report["context_raw_sha256"] == data["expected_context_sha256"]
                  and report["codec_sha256"] == value["codec_sha256"]
                  and set(report["allowed_token_ids"]) <= set(report["baseline_prefix_report"]["allowed_token_ids"]),
                  "public completion-budget prefix identity differs")
            guard()
            return report

        try:
            final_prefix = prefix()
            status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
            while final_prefix["allowed_token_ids"] and len(emitted) < data["max_new_tokens"]:
                # Reserve complete final/context output before model work. A
                # full537 float32 score has a conservative32byte JSON scalar
                # allowance; no trace or decoding is silently truncated.
                prefix_bytes = len(head._wire(final_prefix, MAX_REPORT_BYTES))
                reserve = 2*len(raw) + 2*1024**2 + prefix_bytes
                next_trace_bound = prefix_bytes + 537*32 + 16384
                if trace_bytes + next_trace_bound + reserve > MAX_REPORT_BYTES:
                    status, reason = "report_budget_exhausted", "complete_generation_report_limit"
                    break
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
                      and state[2].tolist() == [len(current)], "incremental full537 output or prefix position differs")
                guard()
                selected = budget.select_token(scores, current, raw,
                    remaining_new_tokens=data["max_new_tokens"]-len(emitted), **policy_options)
                _authority(selected)
                old_selection = selected["baseline_selection"]
                baseline = old_selection["baseline_selection"]
                token = selected["selected_token_id"]
                _need(selected["schema"] == budget.SELECTION_SCHEMA and selected["policy"] == budget.POLICY
                      and selected["owner_pins"] == budget_pins and selected["prefix_report"] == final_prefix
                      and old_selection["prefix_report"] == final_prefix["baseline_prefix_report"]
                      and old_selection["owner_pins"] == old_budget_pins and old_selection["logits"] == scores
                      and selected["offered_prefix_ids"] == current and selected["logits"] == scores
                      and selected["logits_sha256"] == head._digest(scores)
                      and selected["selection_performed"] is True and type(token) is int
                      and token in final_prefix["allowed_token_ids"] and selected["next_prefix_ids"] == current+[token]
                      and baseline["logits"] == scores and type(baseline["raw_argmax_token_id"]) is int,
                      "public selected token or full score binding differs")
                observation = dict(prefix_ids=list(current), input_token_ids=input_ids, logits=scores,
                    logits_sha256=head._digest(scores), budget_prefix_report=final_prefix,
                    selected_token_id=token, raw_argmax_token_id=baseline["raw_argmax_token_id"],
                    consumed_prefix_positions=state[2].tolist())
                trace_bytes += len(head._wire(observation, MAX_REPORT_BYTES)) + 2
                trace.append(observation)
                emitted.append(token)
                current.append(token)
                final_prefix = prefix()
                if final_prefix["status"] == "complete":
                    status, reason = "complete", None
                    break
                if not final_prefix["allowed_token_ids"]:
                    if len(emitted) == data["max_new_tokens"]:
                        status, reason = "step_budget_exhausted", "max_new_tokens_reached"
                    else:
                        status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
                    break
            else:
                if emitted and len(emitted) == data["max_new_tokens"]:
                    status, reason = "step_budget_exhausted", "max_new_tokens_reached"
            decoded = tokens.decode_compact_content_tokens_v1(current, raw, **options)
            _authority(decoded)
            _need(decoded["generated_ids"] == current and decoded["context_raw_sha256"] == data["expected_context_sha256"]
                  and decoded["codec_sha256"] == value["codec_sha256"]
                  and decoded["context_sha256"] == final_prefix["context_sha256"]
                  and (status == "complete") == (decoded["status"] == "valid_candidate"),
                  "generation disposition disagrees with the original typed decoder")
            guard()
            return dict(schema=SCHEMA, profile=PROFILE, status=status, reason=reason,
                checkpoint_sha256=data["expected_checkpoint_sha256"], weights_sha256=value["weights_sha256"],
                codec_sha256=value["codec_sha256"], conditioning_mode=value["conditioning_mode"], source_space=value["source_space"],
                context_raw_sha256=data["expected_context_sha256"], conditioning_sha256=head._digest(data["conditioning"]),
                initial_prefix_ids=[1], generated_ids=current, selected_token_ids=emitted, trace=trace,
                final_prefix_report=final_prefix, final_decoding=decoded,
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
                    incremental_hidden_state=True, cross_call_model_cache=False, budget_policy=budget.POLICY,
                    max_forced_tokens=data["max_forced_tokens"], forced_lookahead_opt_in=True,
                    forced_horizon_excludes_initial_choice=True, old_budget_policy=old_budget.POLICY,
                    report_limit_bytes=MAX_REPORT_BYTES), budget_owner_pins=budget_pins,
                authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
        except BaseException as error:
            failure = error
            raise
        finally:
            head._finish(failure, guard)

    failure = None
    try:
        _need(_pins() == initial_pins, "generation source changed during budget import")
        return training._operation(dict(checkpoint=checkpoint, conditioning=conditioning, context_raw=context_raw,
            expected_checkpoint_sha256=expected_checkpoint_sha256, expected_context_sha256=expected_context_sha256,
            expected_conditioning_mode=expected_conditioning_mode, expected_source_space=expected_source_space,
            max_new_tokens=max_new_tokens, max_forced_tokens=max_forced_tokens), work)
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
          "persistent generation-v2 report identity required")
    settings = value.get("settings")
    _need(type(settings) is dict
          and type(settings.get("max_new_tokens")) is int and 1 <= settings["max_new_tokens"] <= MAX_NEW_TOKENS
          and type(settings.get("max_forced_tokens")) is int and 0 <= settings["max_forced_tokens"] <= MAX_FORCED_TOKENS
          and settings.get("budget_policy") == _POLICY
          and settings.get("forced_lookahead_opt_in") is True
          and settings.get("forced_horizon_excludes_initial_choice") is True,
          "explicit generation-v2 policy and bounded horizon identity required")
    result = head._digest(value, MAX_REPORT_BYTES)
    _need(_pins() == pins and training.base._sources() == source_pin
          and head._digest(head._copy(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES) == result,
          "source or original report changed during hashing")
    return result


__all__ = ["generate_from_bos", "generation_sha256"]

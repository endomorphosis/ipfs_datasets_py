"""Bounded fixed-BOS generation for the qualified compact persistent profile.

One private model lifetime keeps explicit recurrent/source/position state. The
existing scope, completion-budget, selection and typed-decoding owners decide
legal token continuations. A typed candidate is not a legal interpretation.
No caller target, optimizer, fitting, cross-call cache or checkpoint conversion
is supplied by this runtime. Resource admission remains the caller's job.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path

from . import legal_compact_content_persistent_v1 as training

SCHEMA = "legal-compact-persistent-bos-generation/v1"
PROFILE = "authored384-persistent-fixed537-bos100/v1"
MAX_NEW_TOKENS = 100
MAX_REPORT_BYTES = 64 * 1024**2
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_DEPS = {
    "legal_compact_content_persistent_v1.py": "1fedac1842d9118603c46065eafc7ff47dfc4f72802c0c575a1b38969e1173d8",
    "legal_compact_content_completion_budget_v1.py": "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7",
}
_AUTHORITY = dict(training._AUTHORITY)
_LIMITATIONS = [
    "The intact checkpoint validator reads retained population commitments and named Adam; neither is passed to the numerical serving view.",
    "Conditioning and context are caller-supplied unverified inputs; dimension and source-space names are not encoder provenance or permission.",
    "Scope and relaxed completion lower bounds can block a continuation; they do not prove global completability or statutory correctness.",
    "Raw argmax IDs are observed along the constrained prefix, not a separate unconstrained autoregressive run.",
    "The live numerical runtime is checked even when no model or forward is needed.",
    "Typed candidates, exact fixture matches and model-only serving are separate from held-out legal accuracy, graph admission and Lean qualification.",
    "Existing legacy batch adapters do not accept this generation schema; downstream admission is separate.",
]
_need = training._need


def _pins():
    base = training.base
    _need(Path(training.__file__).absolute() == _SELF_PATH.with_name("legal_compact_content_persistent_v1.py"),
          "canonical persistent training dependency required")
    return [base._source(_SELF_PATH, _SELF_SHA), *[
        base._source(_SELF_PATH.with_name(name), sha) for name, sha in _DEPS.items()]]


def _authority(value):
    _need(type(value["authority"]) is dict and value["authority"]
          and all(flag is False for flag in value["authority"].values())
          and type(value["training_mask"]) is int and value["training_mask"] == 0
          and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0,
          "syntax observations cannot grant semantic or training/gold authority")


def _serving(value, head):
    # _restore(with_optimizer=False) uses exactly this projection. The minimal
    # donor is constructor input, not a second independently valid checkpoint.
    initial = value["initial_checkpoint"]
    return head._copy({"initial_checkpoint": {key: initial[key] for key in
        ("torch_version", "config", "codec", "model_state")},
        **{key: value[key] for key in ("conditioning_mode", "model_state", "parameter_order", "weights_sha256")}},
        training.MAX_CHECKPOINT_BYTES)


def generate_from_bos(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
        expected_context_sha256, expected_conditioning_mode, expected_source_space, max_new_tokens):
    """Emit at most100 IDs including EOS, using one model-only incremental restore.

    There is no supplied-prefix or target argument. Blocked/exhausted results
    retain their exact IDs and typed-decoder disposition. A no-choice call
    allocates no model; it still validates the live checkpoint/runtime contract.
    """
    initial_pins = _pins()
    budget = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v1")
    _need(Path(budget.__file__).absolute() == _SELF_PATH.with_name("legal_compact_content_completion_budget_v1.py"),
          "canonical completion-budget dependency required")

    def work(data, head, loaded, adapter):
        _need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= MAX_NEW_TOKENS,
              "explicit new-token allowance must be a plain integer in1..100")
        training.base._hash(data["expected_context_sha256"], "generation context")
        raw = data["context_raw"]
        _need(type(raw) is bytes and 0 < len(raw) <= 512*1024
              and hashlib.sha256(raw).hexdigest() == data["expected_context_sha256"], "exact bounded context bytes required")
        vector = head._conditioning(data["conditioning"])
        value, _ = training._checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"],
            data["expected_conditioning_mode"], data["expected_source_space"], head, loaded)
        scope, helper, tokens, budget_pins = budget._owners()
        _need(tokens is loaded["modules"]["tokens"] and helper is loaded["modules"]["selection"],
              "generation and budget must use the same public token/selection owners")
        options = dict(expected_context_sha256=data["expected_context_sha256"], codec=value["codec"],
                       expected_codec_sha256=value["codec_sha256"])
        view = _serving(value, head)
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
            owners = budget._owners()
            _need(owners[:3] == (scope, helper, tokens) and owners[3] == budget_pins,
                  "completion-budget dependency custody changed")
            _need(training.base._runtime(head, loaded) == runtime and torch.equal(rng, torch.get_rng_state()),
                  "generation changed runtime or ambient CPU RNG")
            if model is not None:
                _need(adapter.tensor_digest(model) == weights_identity, "generation changed private model parameters")

        def prefix():
            guard()
            remaining = data["max_new_tokens"] - len(emitted)
            report = budget.allowed_token_ids(current, raw, remaining_new_tokens=remaining, **options)
            _authority(report)
            _need(report["schema"] == budget.PREFIX_SCHEMA and report["policy"] == budget.POLICY
                  and report["owner_pins"] == budget_pins and report["offered_ids"] == current
                  and report["remaining_new_tokens"] == remaining
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
                    remaining_new_tokens=data["max_new_tokens"]-len(emitted), **options)
                _authority(selected)
                baseline = selected["baseline_selection"]
                token = selected["selected_token_id"]
                _need(selected["schema"] == budget.SELECTION_SCHEMA and selected["policy"] == budget.POLICY
                      and selected["owner_pins"] == budget_pins and selected["prefix_report"] == final_prefix
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
            max_new_tokens=max_new_tokens), work)
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
          "persistent generation report identity required")
    result = head._digest(value, MAX_REPORT_BYTES)
    _need(_pins() == pins and training.base._sources() == source_pin
          and head._digest(head._copy(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES) == result,
          "source or original report changed during hashing")
    return result

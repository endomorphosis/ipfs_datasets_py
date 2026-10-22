"""Opt-in remaining-budget consumer of the unchanged role checkpoint/runtime.

Shared checkpoint validation, input custody, serving-view construction and the
prepared numerical lifetime remain in role_trained_runtime_v1. This versioned
consumer adds only the completion-budget selection policy and its receipts.
"""
from copy import deepcopy
import hashlib
import importlib
import math
from pathlib import Path

SCHEMA = "legal-role-budget-content-generation/v1"
PROFILE = "bounded-role-compact384-completion-budget-inference/v1"
BOS_SCHEMA = "legal-role-budget-content-generation/v2"
BOS_PROFILE = "bounded-bos-role-compact384-completion-budget-inference/v2"
SERVING_SCHEMA = "legal-role-model-serving-view/v1"
MAX_TOTAL_IDS = 512
MAX_BOS_NEW_TOKENS = MAX_TOTAL_IDS - 1
AUTHORITY = dict.fromkeys(("accepted", "admitted", "source_encoder_authenticated",
    "source_semantics_verified", "context_permission_verified", "prefix_origin_verified",
    "heldout_accuracy", "statutory_accuracy", "graph_admission", "Lean_admission", "native_admission"), False)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_LEGACY_SHA = "42dd29ad96e9ca8c28be071fe63292fca8b0155f7284eeac52c9306bfd921814"
_BUDGET_SHA = "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7"
_PACKAGE = "ipfs_datasets_py.logic.formalization.autoencoder."


class RoleBudgetRuntimeError(ValueError):
    """Budget consumer compatibility/custody failed; no historical repair."""


def _need(condition, message):
    if not condition:
        raise RoleBudgetRuntimeError(message)


def _owners():
    legacy_path = _SELF_PATH.with_name("legal_compact_content_role_trained_runtime_v1.py")
    budget_path = _SELF_PATH.with_name("legal_compact_content_completion_budget_v1.py")
    for path, digest in ((legacy_path, _LEGACY_SHA), (budget_path, _BUDGET_SHA)):
        _need(path.resolve(strict=True) == path and path.stat().st_size <= 131072
              and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
              "pinned budget consumer dependency differs")
    legacy = importlib.import_module(_PACKAGE + legacy_path.stem)
    budget = importlib.import_module(_PACKAGE + budget_path.stem)
    _need(Path(legacy.__file__).absolute() == legacy_path and Path(budget.__file__).absolute() == budget_path,
          "budget consumer dependency origin differs")
    observed = [legacy._source(path, digest) for path, digest in
                ((_SELF_PATH, _SELF_SHA), (legacy_path, _LEGACY_SHA), (budget_path, _BUDGET_SHA))]
    return legacy, budget, observed, budget._owners()


def _operation(original, work):
    legacy, budget, observed, budget_owners = _owners()
    def check():
        current = _owners()
        _need(current[0] is legacy and current[1] is budget and current[2:] == (observed, budget_owners),
              "budget inference sources or loaded dependency identities changed")
    def adapted(data, owners, modules, loaded, pins, scope_pins, fence):
        _need(budget_owners[0] is owners["scope"] and budget_owners[1] is loaded[2]["selection"]
              and budget_owners[2] is loaded[2]["tokens"] and budget_owners[0]._owners()[2] == scope_pins,
              "budget, role and numerical owners disagree")
        merged = {item["path"]: item for item in pins}
        for item in [row[0] for row in observed] + budget_owners[3]:
            _need(item["path"] not in merged or merged[item["path"]] == item,
                  "overlapping budget inference source pins disagree")
            merged[item["path"]] = item
        def guarded():
            fence()
            check()
        guarded()
        result = work(data, dict(owners, scope=budget), modules, loaded,
                      [merged[key] for key in sorted(merged)], budget_owners[3], guarded)
        guarded()
        return result
    failure = None
    try:
        check()
        return legacy._operation(original, adapted)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            check()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing budget runtime source check also failed.")


def generate(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
             expected_policy_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Generate at most64 budget-refined tokens with one original numerical lifetime.

    This opt-in profile changes inference selection only. It does not change or
    requalify historical training grammar, optimizer state or semantic quality.
    """
    return _generate(checkpoint, conditioning, prefix_ids, context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin,
        _schema=SCHEMA, _profile=PROFILE, _max_new_tokens=64)


def generate_from_bos_v2(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
                         expected_policy_sha256, expected_context_sha256, max_new_tokens, context_origin):
    """Generate from fixed BOS with an explicit 1..511-new-ID completion allowance.

    EOS consumes one ID. The 512-total-ID codec, checkpoint and selector remain
    unchanged; this allowance does not guarantee completion or reconstruction.
    Historical checkpoint validation still reads exposed training targets, and
    the supplied context must retain its separately declared origin.
    """
    return _generate(checkpoint, conditioning, [1], context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin="bos_seed", context_origin=context_origin,
        _schema=BOS_SCHEMA, _profile=BOS_PROFILE, _max_new_tokens=MAX_BOS_NEW_TOKENS)


def _generate(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
              expected_policy_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin,
              _schema, _profile, _max_new_tokens):
    """Share original custody, one prepared model and the complete generation loop."""
    legacy, budget, _, _ = _owners()
    _inputs, _checked = legacy._inputs, legacy._checked
    _serving, _identity = legacy._serving, legacy._identity
    _POLICY, _LIMITATIONS = budget.POLICY, legacy._LIMITATIONS
    original = dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)
    def work(data, owners, modules, loaded, pins, scope_pins, fence):
        helper, scope = owners['prepared'], owners['scope']
        _need(type(data['max_new_tokens']) is int and 1 <= data['max_new_tokens'] <= _max_new_tokens,
              f'new-token allowance must be a plain integer in 1..{_max_new_tokens}')
        scoring_inputs = dict(data, prefixes_ids=[data['prefix_ids']])
        _inputs(scoring_inputs, helper, owners['role'])
        value = _checked(data, owners, modules, fence)
        view = _serving(value, data)
        view_fingerprint, view_sha = helper._fingerprint(view), helper._digest(view)
        def serving_fence():
            fence()
            _need(helper._fingerprint(view) == view_fingerprint, 'target-free serving view changed')
        tokens = loaded[2]["tokens"]
        root = loaded[0]
        token_paths = {str(root / "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py"),
                       str(root / "logic/autoformal/legal_compact_content_v1.py")}
        options = dict(expected_context_sha256=data["expected_context_sha256"],
                       codec=value["codec"], expected_codec_sha256=value["codec_sha256"])
        current, emitted, trace = list(data["prefix_ids"]), [], []
        session, failure = None, None
        def guard():
            if session is None:
                serving_fence()
            else:
                session._guard()
        def scope_report(report, schema):
            _need(report["schema"] == schema and report["policy"] == _POLICY
                  and report["owner_pins"] == scope_pins
                  and report["authority"] and all(v is False for v in report["authority"].values())
                  and type(report["training_mask"]) is int and report["training_mask"] == 0
                  and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
                  "scope producer identity or authority differs")
        def prefix_report(ids):
            guard()
            report = scope.allowed_token_ids(ids, data["context_raw"],
                remaining_new_tokens=data["max_new_tokens"] - len(emitted), **options)
            scope_report(report, scope.PREFIX_SCHEMA)
            helper._producer_rows(report["baseline_prefix_report"], loaded, token_paths)
            _need(set(report["allowed_token_ids"]) <= set(report["baseline_prefix_report"]["allowed_token_ids"]),
                  "scope policy expanded baseline choices")
            _need(report["remaining_new_tokens"] == data["max_new_tokens"] - len(emitted),
                  "public prefix remaining-budget binding differs")
            _need(report["offered_ids"] == ids and report["context_raw_sha256"] == data["expected_context_sha256"]
                  and report["codec_sha256"] == value["codec_sha256"], "public prefix binding differs")
            guard()
            return report
        try:
            final_prefix = prefix_report(current)
            status, reason = None, None
            if final_prefix["status"] == "complete":
                status, reason = "supplied_complete", "supplied_prefix_already_complete"
            elif not final_prefix["allowed_token_ids"]:
                status = "budget_infeasible" if (final_prefix["status"] == "budget_exhausted" and final_prefix["reason"] == "no_scope_continuation_within_remaining_budget") else "blocked"
                reason = final_prefix["reason"] or final_prefix["status"]
            else:
                while len(emitted) < data["max_new_tokens"]:
                    restored = session is None
                    if restored:
                        # This explicit new-schema view omits targets and Adam.
                        # It is not an old-schema checkpoint or authority grant.
                        session = helper._PreparedModel(view, data["conditioning"], loaded, serving_fence)
                    guard()
                    observed = session.forward(current)
                    logits = observed["logits"]
                    _need(observed["runtime"] == value["runtime"]
                          and observed["output_shape"] == [1, len(current), 537]
                          and type(logits) is list and len(logits) == 537
                          and all(type(x) is float and math.isfinite(x) for x in logits),
                          "actual complete scope-trained model output differs")
                    selected = scope.select_token(logits, current, data["context_raw"],
                        remaining_new_tokens=data["max_new_tokens"] - len(emitted), **options)
                    scope_report(selected, scope.SELECTION_SCHEMA)
                    _need(selected["baseline_selection"]["prefix_report"] == final_prefix["baseline_prefix_report"],
                          "local baseline observation disagrees with prefix owner")
                    _need(selected["selection_performed"] is True and selected["prefix_report"] == final_prefix
                          and selected["offered_prefix_ids"] == current and selected["logits"] == logits
                          and selected["logits_sha256"] == helper._digest(logits)
                          and type(selected["selected_token_id"]) is int
                          and selected["selected_token_id"] in final_prefix["allowed_token_ids"]
                          and selected["next_prefix_ids"] == current + [selected["selected_token_id"]],
                          "public selected token disagrees with bound full537 output")
                    guard()
                    trace.append(dict(prefix_ids=list(current), logits=logits, logits_sha256=helper._digest(logits),
                        selection=selected, prefix_report=final_prefix, next_prefix_ids=list(selected["next_prefix_ids"]),
                        model_restore_performed=restored, prepared_model_reused=not restored,
                        output_shape=observed["output_shape"]))
                    emitted.append(selected["selected_token_id"])
                    current = list(selected["next_prefix_ids"])
                    final_prefix = prefix_report(current)
                    if final_prefix["status"] == "complete":
                        status, reason = "complete", None
                        break
                    if not final_prefix["allowed_token_ids"]:
                        status = "budget_infeasible" if (final_prefix["status"] == "budget_exhausted" and final_prefix["reason"] == "no_scope_continuation_within_remaining_budget") else "blocked"
                        reason = final_prefix["reason"] or final_prefix["status"]
                        break
                else:
                    status, reason = "step_budget_exhausted", "max_new_tokens_reached"
            guard()
            decoded = tokens.decode_compact_content_tokens_v1(current, data["context_raw"], **options)
            helper._producer_rows(decoded, loaded, token_paths)
            _need(decoded["generated_ids"] == current and decoded["context_raw_sha256"] == data["expected_context_sha256"]
                  and decoded["codec_sha256"] == value["codec_sha256"]
                  and decoded["context_sha256"] == final_prefix["context_sha256"]
                  and ((status in ("complete", "supplied_complete")) == (decoded["status"] == "valid_candidate")),
                  "final public intake disagrees with generated prefix or terminal disposition")
            guard()
            return dict(schema=_schema, profile=_profile,
                **_identity(value, data),
                serving_view_schema=SERVING_SCHEMA, serving_view_sha256=view_sha,
                serving_view_fields=sorted(view), serving_view_contains_training_targets=False,
                serving_view_contains_optimizer_state=False,
                budget_policy=_POLICY, budget_owner_pins=deepcopy(scope_pins),
                scope_policy=budget._owners()[0].POLICY,
                scope_owner_pins=deepcopy(budget._owners()[0]._owners()[2]),
                scope_filter_source=next(deepcopy(p) for p in scope_pins if p["path"].endswith("legal_compact_content_scope_filter_v1.py")),
                budget_filter_source=next(deepcopy(p) for p in scope_pins if p["path"].endswith("legal_compact_content_completion_budget_v1.py")),
                checkpoint_training_grammar_unchanged=True,
                local_baseline_decisions_are_independent_trajectory=False,
                conditioning=deepcopy(data["conditioning"]), conditioning_sha256=helper._digest(data["conditioning"]),
                context_raw_sha256=data["expected_context_sha256"], context_sha256=decoded["context_sha256"],
                initial_prefix_ids=list(data["prefix_ids"]), generated_ids=current, selected_token_ids=emitted,
                prefix_origin=data["prefix_origin"], context_origin=data["context_origin"],
                trace=trace, model_restore_count=int(session is not None), numerical_forward_count=len(trace),
                checkpoint_inspection_count=1, status=status, reason=reason,
                final_prefix_report=final_prefix, final_decoding=decoded,
                settings=dict(max_new_tokens=data["max_new_tokens"], max_total_ids=MAX_TOTAL_IDS,
                    full_prefix_each_step=True, cross_call_model_cache=False, incremental_hidden_state=False,
                    eos_counted_in_new_token_budget=True, budget_filter_opt_in=True),
                emitted_token_count=len(emitted), total_token_count=len(current),
                model_executed=bool(trace), runtime_verified=bool(trace), training_executed=False,
                optimizer_constructed=False, optimizer_state_restored=False,
                target_access_for_checkpoint_validation=True,
                supplied_prefix_target_access_declared=data["prefix_origin"] == "target_derived_label",
                supplied_context_target_access_declared=data["context_origin"] == "target_derived_label",
                actual_model_inputs=["conditioning_vector", "supplied_or_generated_prefix_ids"],
                authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                owner_pins=pins, limitations=list(_LIMITATIONS) + [
                    "Generation refines the unchanged lexical scope choices using a necessary completion-cost lower bound. Unknown bounds retain choices; passing a bound does not prove completion or meaning.",
                    "Old-selector comparisons along these refined prefixes are not an independently generated baseline trajectory."])
        except BaseException as error:
            failure = error
            raise
        finally:
            if session is not None:
                loaded[2]["legacy_head"]._finish(failure, session.close)
    return _operation(original, work)


__all__ = ["RoleBudgetRuntimeError", "generate", "generate_from_bos_v2"]

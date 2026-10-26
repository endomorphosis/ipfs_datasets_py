"""Model-only, fixed-BOS inference for intact CP128 warm-start checkpoints.

Checkpoint validation, source/input custody, numerical model lifetime and public
syntax/budget selection retain their original owners. This adapter supplies only
the new checkpoint projection and bounded inference orchestration. Validation
still reads exposed historical labels; a target-free model view is not evidence
of independent source semantics or held-out legal accuracy.
"""
from copy import deepcopy
import hashlib
import importlib
import math
from pathlib import Path
import stat

SCORE_SCHEMA = 'legal-role-warmstart-bos-scores/v1'
GENERATION_SCHEMA = 'legal-role-warmstart-bos-generation/v1'
INSPECT_SCHEMA = 'legal-role-warmstart-inference-inspection/v1'
SERVING_SCHEMA = 'legal-role-warmstart-model-serving-view/v1'
PROFILE = 'authored384-fixed537-warmstart-model-only-bos100/v1'
MAX_NEW_TOKENS = 100
MAX_REPORT_BYTES = 16 * 1024**2
AUTHORITY = dict.fromkeys(('accepted', 'admitted', 'source_encoder_authenticated',
    'source_semantics_verified', 'context_permission_verified', 'prefix_origin_verified',
    'heldout_accuracy', 'statutory_accuracy', 'graph_admission', 'Lean_admission',
    'native_admission'), False)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_RUNTIME_SHA = '77325d00ed754679997fbe95caf70f14aa214d1b32e9994ac40f2c0ef739d59e'
_WARMSTART_SHA = '59e5294ed018e95eb2c3aa0ccaef1caf50bb915b58b454316564bc94375db6ba'
_PACKAGE = 'ipfs_datasets_py.logic.formalization.autoencoder.'
_MODEL_FIELDS = ('runtime', 'config', 'codec', 'codec_sha256', 'parameter_order',
                 'model_state', 'weights_sha256')
_LIMITATIONS = (
    'The intact warmstart validator reads exposed historical targets and Adam; neither reaches numerical serving or token selection.',
    'Conditioning and context are caller observations; source-space compatibility and independent context permission remain unverified.',
    'Full537 and scope_conditional identify training provenance. Inference uses the same public scope/completion-budget selection for both.',
    'Syntax completion is distinct from exact reconstruction, legal meaning, statutory fidelity and Lean admission.',
    'Each forward uses the entire generated prefix. No cross-call cache or incremental hidden-state contract is supplied.',
    'A blocked or initially budget-infeasible call allocates no model and does not verify a live numerical runtime.',
    'Source/state/RNG guards and external execution admission are separate; this adapter never grants native authority.',
)


class RoleWarmstartRuntimeError(ValueError):
    """An intact checkpoint, input, source, model or public producer check failed."""


def _need(condition, message):
    if not condition:
        raise RoleWarmstartRuntimeError(message)


def _owners():
    # Bootstrap only the unchanged runtime owner, then reuse its source reader.
    path = _SELF_PATH.with_name('legal_compact_content_role_budget_runtime_v1.py')
    info = path.lstat()
    _need(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
          and info.st_nlink == 1 and 0 < info.st_size <= 131072
          and hashlib.sha256(path.read_bytes()).hexdigest() == _RUNTIME_SHA,
          'pinned canonical budget runtime required')
    runtime = importlib.import_module(_PACKAGE + path.stem)
    _need(type(runtime.__file__) is str and Path(runtime.__file__).absolute() == path,
          'budget runtime origin differs')
    legacy, budget, _, _ = runtime._owners()
    warm_path = _SELF_PATH.with_name('legal_compact_content_role_warmstart_training_v1.py')
    observed = [legacy._source(p, pin) for p, pin in
                ((_SELF_PATH, _SELF_SHA), (path, _RUNTIME_SHA), (warm_path, _WARMSTART_SHA))]
    warmstart = importlib.import_module(_PACKAGE + warm_path.stem)
    _need(type(warmstart.__file__) is str and Path(warmstart.__file__).absolute() == warm_path
          and legacy._source(warm_path, _WARMSTART_SHA) == observed[2],
          'warmstart validator source/origin differs')
    return runtime, legacy, budget, warmstart, observed


def _operation(original, work):
    runtime, legacy, budget, warmstart, observed = _owners()
    failure = None

    def outer():
        current = _owners()
        _need(all(current[i] is owner for i, owner in enumerate((runtime, legacy, budget, warmstart)))
              and current[4] == observed, 'warmstart serving source custody changed')

    def adapted(data, owners, modules, loaded, pins, budget_pins, fence):
        root, warm_owners, warm_observed = warmstart._owners()
        scope, selection, tokens, expected_budget_pins = budget._owners()
        _need(root == loaded[0] and warm_owners['role_training'] is owners['role']
              and owners['scope'] is budget and selection is loaded[2]['selection']
              and tokens is loaded[2]['tokens'] and expected_budget_pins == budget_pins,
              'warmstart, numerical and budget owners disagree')
        merged = {item['path']: item for item in pins}
        for item in [row[0] for row in observed] + [row[0] for row in warm_observed.values()]:
            _need(item['path'] not in merged or merged[item['path']] == item,
                  'overlapping warmstart source pins disagree')
            merged[item['path']] = item

        def guarded():
            fence()
            outer()
            current = warmstart._owners()
            _need(current[0] == root and current[1]['role_training'] is owners['role']
                  and current[2] == warm_observed, 'warmstart validation dependency changed')

        guarded()
        result = work(data, dict(owners, warmstart=warmstart),
                      dict(modules, role_training=owners['role']), loaded,
                      [merged[key] for key in sorted(merged)], budget_pins, guarded)
        guarded()
        return result

    try:
        # This owner establishes custody; old-schema validation is only in its
        # separate old-generation work closure, which is never called here.
        return runtime._operation(original, adapted)
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, RoleWarmstartRuntimeError):
            failure = RoleWarmstartRuntimeError(str(error))
            raise failure from error
        raise
    finally:
        try:
            outer()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, 'A closing warmstart serving source check also failed.')


def _checked(data, owners, modules, fence):
    value = owners['warmstart']._validate(data['checkpoint'], data['expected_checkpoint_sha256'],
                                        data['expected_policy_sha256'], modules)
    fence()
    return value


def _identity(value, data):
    return dict(checkpoint_sha256=data['expected_checkpoint_sha256'], checkpoint_schema=value['schema'],
        checkpoint_profile=value['profile'], objective_kind=value['objective_policy']['objective_kind'],
        objective_weighting=value['objective_policy']['weighting'],
        objective_policy_sha256=data['expected_policy_sha256'], weights_sha256=value['weights_sha256'],
        codec_sha256=value['codec_sha256'], progress=deepcopy(value['progress']),
        warmstart_parent_checkpoint_sha256=value['warmstart_parent_checkpoint_sha256'],
        warmstart_parent_policy_sha256=value['warmstart_parent_policy_sha256'],
        historical_parent_optimizer_state_sha256=value['historical_parent_optimizer_state_sha256'],
        initial_checkpoint_sha256=value['initial_checkpoint_sha256'],
        parent_checkpoint_sha256=value['parent_checkpoint_sha256'], checkpoint_schema_conversion_performed=False)


def _serving(value, data):
    view = dict(schema=SERVING_SCHEMA, checkpoint_sha256=data['expected_checkpoint_sha256'],
        checkpoint_schema=value['schema'], objective_kind=value['objective_policy']['objective_kind'],
        objective_policy_sha256=data['expected_policy_sha256'],
        warmstart_parent_checkpoint_sha256=value['warmstart_parent_checkpoint_sha256'],
        initial_checkpoint_sha256=value['initial_checkpoint_sha256'],
        parent_checkpoint_sha256=value['parent_checkpoint_sha256'])
    for key in _MODEL_FIELDS:
        view[key] = deepcopy(value[key])
    return view


def _inputs(data, helper, role):
    # Fixed BOS is the only prefix surface. No row cursor or target selects it.
    legacy = _owners()[1]
    legacy._inputs(dict(data, prefixes_ids=[[1]], prefix_origin='bos_seed'), helper, role)
    _need(type(data['max_new_tokens']) is int and 1 <= data['max_new_tokens'] <= MAX_NEW_TOKENS,
          'plain integer new-token allowance in 1..100 required')


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Validate intact successor state and its model projection without allocation."""
    def work(data, owners, modules, loaded, pins, budget_pins, fence):
        value = _checked(data, owners, modules, fence)
        view = _serving(value, data)
        return dict(schema=INSPECT_SCHEMA, profile=PROFILE, **_identity(value, data),
            serving_view_schema=SERVING_SCHEMA, serving_view_fields=sorted(view),
            serving_view_sha256=owners['prepared']._digest(view),
            serving_view_contains_training_targets=False, serving_view_contains_optimizer_state=False,
            model_restore_count=0, numerical_forward_count=0, model_executed=False,
            runtime_verified=False, optimizer_constructed=False, optimizer_state_restored=False,
            training_executed=False, target_access_for_checkpoint_validation=True,
            owner_pins=pins, authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            limitations=list(_LIMITATIONS))
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
                           expected_policy_sha256=expected_policy_sha256), work)


def score_from_bos(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
                   expected_policy_sha256, expected_context_sha256, context_origin):
    """Observe all537 BOS scores once, with no selection, target prefix or Adam."""
    return _infer(checkpoint, conditioning, context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        context_origin=context_origin, max_new_tokens=MAX_NEW_TOKENS, score_only=True)


def generate_from_bos(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
                      expected_policy_sha256, expected_context_sha256, context_origin, max_new_tokens):
    """Generate from fixed BOS using unchanged public budget/scope selection.

    The allowance includes EOS and is at most100 new IDs. A complete typed output
    or a truthful blocked/unfinished disposition is returned; no target is input.
    """
    return _infer(checkpoint, conditioning, context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        context_origin=context_origin, max_new_tokens=max_new_tokens, score_only=False)


def _infer(checkpoint, conditioning, context_raw, *, expected_checkpoint_sha256,
           expected_policy_sha256, expected_context_sha256, context_origin, max_new_tokens, score_only):
    original = dict(checkpoint=checkpoint, conditioning=conditioning, context_raw=context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_context_sha256=expected_context_sha256, context_origin=context_origin,
        max_new_tokens=max_new_tokens, score_only=score_only)

    def work(data, owners, modules, loaded, pins, budget_pins, fence):
        helper, budget = owners['prepared'], owners['scope']
        _inputs(data, helper, owners['role'])
        value = _checked(data, owners, modules, fence)
        view = _serving(value, data)
        fingerprint, view_sha = helper._fingerprint(view), helper._digest(view)
        options = dict(expected_context_sha256=data['expected_context_sha256'],
                       codec=view['codec'], expected_codec_sha256=view['codec_sha256'])
        token_paths = {str(loaded[0]/'logic/formalization/autoencoder/legal_compact_content_tokens_v1.py'),
                       str(loaded[0]/'logic/autoformal/legal_compact_content_v1.py')}
        session, failure = None, None
        current, emitted, trace = [1], [], []

        def guard():
            fence()
            _need(helper._fingerprint(view) == fingerprint, 'detached serving view changed')
            if session is not None:
                session._guard()

        def prefix():
            guard()
            report = budget.allowed_token_ids(current, data['context_raw'],
                remaining_new_tokens=data['max_new_tokens']-len(emitted), **options)
            _need(report['schema'] == budget.PREFIX_SCHEMA and report['policy'] == budget.POLICY
                  and report['owner_pins'] == budget_pins and report['offered_ids'] == current
                  and report['remaining_new_tokens'] == data['max_new_tokens']-len(emitted)
                  and report['context_raw_sha256'] == data['expected_context_sha256']
                  and report['codec_sha256'] == view['codec_sha256']
                  and report['authority'] and all(x is False for x in report['authority'].values())
                  and type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
                  and report['training_mask'] == report['evaluation_gold_mask'] == 0,
                  'public budget prefix identity or authority differs')
            baseline = report['baseline_prefix_report']
            helper._producer_rows(baseline, loaded, token_paths)
            _need(set(report['allowed_token_ids']) <= set(baseline['allowed_token_ids']),
                  'budget prefix expanded baseline choices')
            guard()
            return report

        def forward():
            nonlocal session
            if session is None:
                session = helper._PreparedModel(view, data['conditioning'], loaded, guard_without_session)
            guard()
            observed = session.forward(current)
            scores = observed['logits']
            _need(observed['runtime'] == value['runtime'] and observed['output_shape'] == [1, len(current), 537]
                  and type(scores) is list and len(scores) == 537
                  and all(type(x) is float and math.isfinite(x) for x in scores),
                  'complete finite full537 model scores required')
            guard()
            return scores

        def guard_without_session():
            fence()
            _need(helper._fingerprint(view) == fingerprint, 'detached serving view changed')

        try:
            final_prefix = prefix()
            reason, scores, decoded = None, None, None
            if not final_prefix['allowed_token_ids']:
                status, reason = 'blocked', final_prefix['reason'] or final_prefix['status']
            elif data['score_only']:
                scores = forward()
                status = 'scored'
            else:
                status = 'unfinished'
                while len(emitted) < data['max_new_tokens']:
                    scores = forward()
                    selected = budget.select_token(scores, current, data['context_raw'],
                        remaining_new_tokens=data['max_new_tokens']-len(emitted), **options)
                    _need(selected['schema'] == budget.SELECTION_SCHEMA and selected['policy'] == budget.POLICY
                          and selected['owner_pins'] == budget_pins and selected['prefix_report'] == final_prefix
                          and selected['baseline_selection']['prefix_report'] == final_prefix['baseline_prefix_report']
                          and selected['offered_prefix_ids'] == current and selected['logits'] == scores
                          and selected['logits_sha256'] == helper._digest(scores)
                          and selected['selection_performed'] is True
                          and type(selected['selected_token_id']) is int
                          and selected['selected_token_id'] in final_prefix['allowed_token_ids']
                          and selected['next_prefix_ids'] == current+[selected['selected_token_id']]
                          and selected['authority'] and all(x is False for x in selected['authority'].values())
                          and type(selected['training_mask']) is type(selected['evaluation_gold_mask']) is int
                          and selected['training_mask'] == selected['evaluation_gold_mask'] == 0,
                          'public token selection identity or authority differs')
                    guard()
                    trace.append(dict(prefix_ids=list(current), logits=scores, selection=selected))
                    emitted.append(selected['selected_token_id'])
                    current = list(selected['next_prefix_ids'])
                    final_prefix = prefix()
                    if final_prefix['status'] == 'complete':
                        status = 'complete'
                        break
                    if not final_prefix['allowed_token_ids']:
                        status, reason = 'blocked', final_prefix['reason'] or final_prefix['status']
                        break
                else:
                    reason = 'max_new_tokens_reached'
                decoded = loaded[2]['tokens'].decode_compact_content_tokens_v1(current, data['context_raw'], **options)
                helper._producer_rows(decoded, loaded, token_paths)
                _need(decoded['generated_ids'] == current
                      and decoded['context_raw_sha256'] == data['expected_context_sha256']
                      and decoded['context_sha256'] == final_prefix['context_sha256']
                      and decoded['codec_sha256'] == view['codec_sha256']
                      and (status == 'complete') == (decoded['status'] == 'valid_candidate'),
                      'public decoding disagrees with terminal generation')
            guard()
            return dict(schema=SCORE_SCHEMA if data['score_only'] else GENERATION_SCHEMA, profile=PROFILE,
                **_identity(value, data), serving_view_schema=SERVING_SCHEMA,
                serving_view_sha256=view_sha, serving_view_fields=sorted(view),
                serving_view_contains_training_targets=False, serving_view_contains_optimizer_state=False,
                prefix_origin='bos_seed', context_origin=data['context_origin'],
                context_raw_sha256=data['expected_context_sha256'], conditioning_sha256=helper._digest(data['conditioning']),
                initial_prefix_ids=[1], generated_ids=current, selected_token_ids=emitted,
                logits=scores if data['score_only'] else None, trace=trace,
                final_prefix_report=final_prefix, final_decoding=decoded, status=status, reason=reason,
                checkpoint_inspection_count=1, model_restore_count=int(session is not None),
                numerical_forward_count=int(session is not None) if data['score_only'] else len(trace),
                model_executed=session is not None, runtime_verified=session is not None,
                optimizer_constructed=False, optimizer_state_restored=False, training_executed=False,
                target_access_for_checkpoint_validation=True,
                supplied_context_target_access_declared=data['context_origin'] == 'target_derived_label',
                actual_model_inputs=['conditioning_vector', 'fixed_BOS_and_generated_prefix_ids'],
                settings=dict(max_new_tokens=data['max_new_tokens'], max_total_ids=512,
                    eos_counted_in_new_token_budget=True, full_prefix_each_step=True,
                    cross_call_model_cache=False, incremental_hidden_state=False, budget_policy=budget.POLICY),
                owner_pins=pins, budget_owner_pins=deepcopy(budget_pins),
                authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                limitations=list(_LIMITATIONS))
        except BaseException as error:
            failure = error
            raise
        finally:
            if session is not None:
                loaded[2]['legacy_head']._finish(failure, session.close)

    return _operation(original, work)


__all__ = ['RoleWarmstartRuntimeError', 'inspect', 'score_from_bos', 'generate_from_bos']

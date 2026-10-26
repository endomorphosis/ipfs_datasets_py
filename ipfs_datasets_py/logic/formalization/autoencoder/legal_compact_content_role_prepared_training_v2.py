"""Bounded prepared lifecycle for the explicit role-training checkpoint.

The original role owner validates and restores the explicit role checkpoint.
This opt-in v2 keeps the qualified v1 lifecycle, caches invariant row tensors,
and mirrors the small direct objective/packing construction because those
owners expose no cached kernel hook. Actual changed numerical state still
passes the original validator. No measured speedup or broader qualification is
implied by this source. Checkpoint schema and implementation remain intact.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import threading
import time

SCHEMA = 'legal-compact-role-prepared-training-session/v2'
PROFILE = 'authored-h0-384-fixed537-cached-role-training-consumer-development/v2'
ADVANCE_SCHEMA = 'legal-compact-role-prepared-training-advance/v2'
STEP_SCHEMA = 'legal-compact-role-prepared-training-step/v2'
MAX_ADVANCE_STEPS = 4
MAX_STEP_REPORT_BYTES = 24 * 1024**2
MAX_ADVANCE_BYTES = 112 * 1024**2
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ('role', 'logic/formalization/autoencoder/legal_compact_content_role_training_v1.py',
     '7d1562aa7109dc9998fcf533357262a352e9a8c72425bf5d4c02537a9e0d685c'),
    ('original_prepared', 'logic/formalization/autoencoder/legal_compact_content_role_prepared_training_v1.py',
     'b7d4ca5fd23d1f8c408156cebc50c57f553e46cf99a527188f5e80668e3bd253'),
    ('capsule', 'logic/formalization/autoencoder/legal_compact_content_weighted_prepared_training_v1.py',
     '6f7248714cea81edfe6fda69bb0abe38bb37535f2cb92d460d8e38c4d2cd4b07'),
)
_CATEGORIES = frozenset(('checkpoint_validation', 'runtime_fence', 'restore',
    'tensor_cache_preparation', 'source_input_fence', 'state_cache_fence', 'forward',
    'objective', 'backward', 'gradient_capture_clip', 'Adam', 'lineage_pack', 'report_export'))


class PreparedTrainingError(ValueError):
    """A source, input, runtime, tensor, lifetime or finite-work guard failed."""


def _need(condition, message):
    if not condition:
        raise PreparedTrainingError(message)


def _wire(value, maximum):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
        raise PreparedTrainingError('bounded ordinary finite JSON required') from error
    _need(len(raw) <= maximum, 'prepared result byte bound exceeded')
    return raw


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path,
          'canonical unaliased prepared source required')
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= 131072, 'bounded single-link source required')
    raw = path.read_bytes()
    after = path.lstat()
    fields = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    _need(fields(before) == fields(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, 'source bytes or physical identity changed')
    return dict(path=str(path), bytes=len(raw), sha256=expected), fields(after)


def _owners():
    root = None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor / 'ipfs_datasets_py', ancestor / 'external/ipfs_datasets/ipfs_datasets_py'):
            if (candidate / _SPECS[0][1]).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, 'canonical role-training owners unavailable')
    owners, observed = {}, {}
    for key, relative, pin in _SPECS:
        path = root / relative
        seen = _source(path, pin)
        module = importlib.import_module('ipfs_datasets_py.' + relative[:-3].replace('/', '.'))
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == path
              and _source(path, pin) == seen, 'canonical prepared owner origin differs')
        owners[key], observed[key] = module, seen
    return root, owners, observed


def prepare(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256, max_steps):
    """Hold one canonical model/Adam; preserve the role objective and lineage.

    The caller owns original admission, a finite work request and durable output.
    Each advance performs one through four updates; the declared lifetime cannot
    exceed the existing total 2048-step bound. This bound is not qualification of
    a long run. A poisoned session permits inspection, closing and last-complete
    recovery when source/input/runtime/cache custody still passes. Partial live
    tensors are never packed for recovery.
    """
    _need(type(max_steps) is int and 1 <= max_steps <= 2048,
          'plain positive bounded session update count required')
    root, owners, observed = _owners()
    owner = owners['role']
    own_source = _source(_SELF_PATH, _SELF_SHA)
    original = dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                    expected_policy=expected_policy_sha256, max_steps=max_steps)
    scope = owner._scope(original)
    entered = False
    state = dict(status='preparing', busy=False, stage='checkpoint_validation',
        model=None, optimizer=None, rows=None, snapshot=None, value=None,
        checkpoint_sha256=None, completed_updates=0, last_failure_stage=None, close_fields=None,
        pid=os.getpid(), thread=threading.get_ident(), totals={}, preparation_timing=[],
        accounting={name: 0 for name in (
            'restoration_calls_entered', 'restoration_calls_completed',
            'model_forward_entered', 'model_forward_completed',
            'cached_objective_calls_entered', 'cached_objective_calls_completed',
            'backward_entered', 'backward_completed',
            'optimizer_step_entered', 'optimizer_step_completed',
            'checked_pack_calls_entered', 'checked_pack_calls_completed')})

    @contextmanager
    def span(category, destination):
        _need(category in _CATEGORIES, 'closed timing category required')
        state['stage'] = category
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            yield
        finally:
            interval = dict(category=category, wall_ns=time.perf_counter_ns() - wall,
                            thread_cpu_ns=time.thread_time_ns() - cpu)
            destination.append(interval)
            total = state['totals'].setdefault(category, dict(intervals=0, wall_ns=0, thread_cpu_ns=0))
            for key in ('wall_ns', 'thread_cpu_ns'):
                total[key] += interval[key]
            total['intervals'] += 1

    def decorate(error):
        result = error if isinstance(error, PreparedTrainingError) else PreparedTrainingError(
            'prepared role training failed during ' + state['stage'] + ' (' + type(error).__name__ + ')')
        result.accounting = deepcopy(state['accounting'])
        result.last_checkpoint_sha256 = state['checkpoint_sha256']
        result.last_failure_stage = state['stage']
        result.completed_updates = state['completed_updates']
        return result

    def source_fence():
        _need(_source(_SELF_PATH, _SELF_SHA) == own_source, 'prepared role source changed')
        for key, relative, pin in _SPECS:
            _need(_source(root / relative, pin) == observed[key]
                  and type(owners[key].__file__) is str
                  and Path(owners[key].__file__).absolute() == root / relative,
                  'prepared role owner source or loaded origin changed')

    try:
        with span('checkpoint_validation', state['preparation_timing']):
            source_fence()
            data, modules, input_fence = scope.__enter__()
            entered = True
            value = owner._validate(data['checkpoint'], data['expected'], data['expected_policy'], modules)
            weighted = modules['weighted']
            _need(data['max_steps'] <= weighted.MAX_NEW_STEPS - value['progress']['optimizer_steps'],
                  'session would exceed unchanged role checkpoint progress bound')
            state['value'], state['checkpoint_sha256'] = value, data['expected']
        with span('runtime_fence', state['preparation_timing']):
            numerical, torch, runtime = weighted._numeric(modules)
            _need(owner._wire(runtime) == owner._wire(value['runtime']), 'actual runtime differs')
            _need(torch.get_default_dtype() is torch.float32 and torch.is_grad_enabled()
                  and not torch.is_inference_mode_enabled(), 'ordinary float32 grad-enabled runtime required')
            rng = torch.get_rng_state().clone()

        def tensor_mark(tensor):
            _need(isinstance(tensor, torch.Tensor) and tensor.device.type == 'cpu'
                  and tensor.layout is torch.strided and tensor.is_contiguous(),
                  'plain contiguous CPU tensor required')
            raw = bytes(tensor.detach().reshape(-1).view(torch.uint8).tolist())
            return (id(tensor), tensor.data_ptr(), tuple(tensor.shape), tuple(tensor.stride()),
                    tensor.dtype, tensor.requires_grad, tensor._version, hashlib.sha256(raw).hexdigest())

        def numeric_mark():
            model, optimizer = state['model'], state['optimizer']
            named = list(model.named_parameters())
            _need(type(optimizer) is torch.optim.Adam and len(optimizer.param_groups) == 1,
                  'one exact private Adam required')
            group = optimizer.param_groups[0]
            _need(list(dict(named)) == value['parameter_order']
                  and len(group['params']) == len(named)
                  and all(left is right for left, (_, right) in zip(group['params'], named))
                  and set(optimizer.state).issubset({tensor for _, tensor in named}),
                  'private parameter order or Adam membership changed')
            moments = []
            for name, tensor in named:
                fields = optimizer.state.get(tensor, {})
                _need(type(fields) is dict and set(fields) in (set(), {'step', 'exp_avg', 'exp_avg_sq'}),
                      'closed private named Adam state required')
                moments.append((name, tuple((key, tensor_mark(fields[key])) for key in sorted(fields))))
            return (tuple((name, tensor_mark(tensor)) for name, tensor in named),
                tuple((name, tensor_mark(tensor)) for name, tensor in model.named_buffers()),
                tuple((name, id(module), type(module), module.training, id(type(module).forward))
                      for name, module in model.named_modules()),
                tuple(moments), owner._wire(optimizer.defaults),
                owner._wire({key: item for key, item in group.items() if key != 'params'}))

        with span('restore', state['preparation_timing']):
            state['accounting']['restoration_calls_entered'] += 1
            model, optimizer = owner.restore(value, expected_checkpoint_sha256=data['expected'],
                                             expected_policy_sha256=data['expected_policy'])
            state['accounting']['restoration_calls_completed'] += 1
            state['model'], state['optimizer'] = model, optimizer
            # No local model/optimizer alias is retained after capsule creation.
            model.train()
            weights, moments = weighted._actual(model, optimizer, value,
                value['progress']['optimizer_steps'], modules, numerical, torch)
            _need(weights == value['model_state'] and moments == value['optimizer_state'],
                  'complete restored named role state differs')
            del model, optimizer
            state['snapshot'] = numeric_mark()
        with span('tensor_cache_preparation', state['preparation_timing']):
            rows = []
            for index in range(2):
                row = owner._row(dict(value, progress=dict(row_cursor=index)), modules)
                _need(len(row['target_ids']) == 47 and len(row['position_weights']) == 46
                      and row['weighting'] == value['objective_policy']['weighting'],
                      'two complete rows under the original role policy required')
                vector = torch.tensor([row['conditioning']], dtype=torch.float32, device='cpu')
                target = torch.tensor([row['target_ids']], dtype=torch.long, device='cpu')
                _need(bool(torch.isfinite(vector).all()), 'finite cached conditioning required')
                labels = torch.tensor(row['target_ids'][1:], dtype=torch.long, device='cpu')
                position_weights = torch.tensor(row['position_weights'], dtype=torch.float32, device='cpu')
                weight_sum = position_weights.sum()
                _need(bool((labels != 0).all()) and bool(torch.isfinite(position_weights).all())
                      and bool((position_weights > 0).all()) and float(weight_sum) == 67.0,
                      'complete no-padding finite positive cached role weights sum67 required')
                allowed = torch.zeros((46, 537), dtype=torch.bool, device='cpu')
                for position, choices in enumerate(row['scope_allowed_token_ids']):
                    _need(choices and row['target_ids'][position + 1] in choices,
                          'original target absent from cached scope mask')
                    allowed[position, choices] = True
                _need(len(row['scope_allowed_token_ids']) == 46
                      and int((allowed.sum(dim=1) == 1).sum()) == 39
                      and int((allowed.sum(dim=1) > 1).sum()) == 7,
                      'original fixed singleton/nontrivial role population required')
                tensors = (vector, target, labels, position_weights, weight_sum, allowed)
                rows.append(dict(metadata=row, metadata_sha256=owner._digest(row), tensors=tensors,
                                 marks=tuple(tensor_mark(t) for t in tensors)))
            state['rows'] = rows
            del row, vector, target, labels, position_weights, weight_sum, allowed, tensors, rows

        preparation = dict(schema=SCHEMA, profile=PROFILE, prepared_owner=deepcopy(own_source[0]),
            role_training_owner=deepcopy(observed['role'][0]), session_capsule_owner=deepcopy(observed['capsule'][0]),
            original_prepared_owner=deepcopy(observed['original_prepared'][0]),
            basis_checkpoint_sha256=value['basis_checkpoint_sha256'], weighting=value['objective_policy']['weighting'],
            objective_policy_sha256=data['expected_policy'], role_inventories_sha256=value['role_inventories_sha256'],
            initial_checkpoint_sha256=data['expected'], checkpoint_schema=value['schema'],
            checkpoint_schema_conversion=False, checkpoint_implementation_identity_rewritten=False,
            lifecycle_entry_validation_count=1, public_restore_revalidates_checkpoint=True,
            public_objective_and_pack_revalidate_every_update=False,
            mirrored_role_objective_scalar_is_the_actual_backward_scalar=True,
            small_objective_and_pack_construction_mirrored_no_owner_kernel_hook=True,
            complete_invariant_validation_repeated_every_update=False,
            changed_numerical_state_checked_by_original_weighted_actual=True,
            full_actual_state_export_and_immediate_parent_commitment_every_update=True,
            exact_factory_counts_require_independent_caller_observation=True,
            cached_conditioning_and_target_rows=2, cached_objective_kernels=True,
            cached_tensor_kinds=['conditioning', 'targets', 'labels', 'position_weights', 'weight_sum', 'allowed'],
            performance_requires_contemporaneous_qualified_comparison=True,
            per_update_guard_sites=4, nested_closing_guards_retained=True,
            tensor_objects_storage_versions_and_bytes_checked=True,
            original_borrowed_and_captured_inputs_retained=True,
            max_steps=data['max_steps'], max_steps_per_advance=MAX_ADVANCE_STEPS,
            max_steps_is_not_long_run_qualification=True, durable_output_owned_by_caller=True,
            authority=deepcopy(owner.AUTHORITY))

        def guard(timing, *, state_check=True):
            _need(os.getpid() == state['pid'] and threading.get_ident() == state['thread'],
                  'session confined to original process and thread')
            with span('source_input_fence', timing):
                source_fence()
                input_fence()
            with span('runtime_fence', timing):
                _need(owner._wire(modules['trainer']._runtime(modules['head'],
                          {'modules': {'numerical': numerical}})) == owner._wire(runtime),
                      'runtime changed during prepared role session')
                _need(torch.equal(rng, torch.get_rng_state()), 'ambient CPU RNG changed')
                _need(torch.get_default_dtype() is torch.float32 and torch.is_grad_enabled()
                      and not torch.is_inference_mode_enabled(), 'ordinary float32 grad-enabled runtime changed')
            with span('state_cache_fence', timing):
                for cached in state['rows']:
                    _need(owner._digest(cached['metadata']) == cached['metadata_sha256']
                          and tuple(tensor_mark(t) for t in cached['tensors']) == cached['marks'],
                          'cached row metadata, tensor objects, versions or bytes changed')
                if state_check:
                    _need(numeric_mark() == state['snapshot'],
                          'private model, Adam, flags, tensor versions or bytes changed')

        def timing_report():
            return dict(schema='legal-compact-role-prepared-timing/v2', totals=deepcopy(state['totals']),
                listed_phase_intervals_are_sequential_nonoverlapping=True,
                wall_and_calling_thread_CPU_only=True, durable_IO_external=True,
                whole_operation_includes_unattributed_dispatch_and_copy=True, not_kernel_throughput=True)

        def summary():
            return dict(schema=SCHEMA, profile=PROFILE, status=state['status'],
                last_checkpoint_sha256=state['checkpoint_sha256'], progress=deepcopy(state['value']['progress']),
                completed_updates=state['completed_updates'], remaining_updates=data['max_steps'] - state['completed_updates'],
                last_failure_stage=state['last_failure_stage'], preparation=deepcopy(preparation),
                accounting=deepcopy(state['accounting']), timing=timing_report(),
                last_checkpoint_is_complete_not_partial_live_state=True, last_checkpoint_durability_not_claimed=True,
                exact_factory_and_GRU_counts_require_independent_caller_observation=True)

        def gradients():
            result = {}
            for name, parameter in state['model'].named_parameters():
                gradient = parameter.grad
                _need(gradient is not None and gradient.device.type == 'cpu' and gradient.dtype is torch.float32
                      and tuple(gradient.shape) == tuple(parameter.shape) and bool(torch.isfinite(gradient).all()),
                      'complete finite named gradients required')
                result[name] = gradient.detach().tolist()
            _need(list(result) == value['parameter_order'], 'complete ordered gradients required')
            return result

        def step():
            timing = []
            guard(timing)
            current, parent = state['value'], state['checkpoint_sha256']
            cached = state['rows'][current['progress']['row_cursor']]
            row = cached['metadata']
            vector, target, labels, position_weights, weight_sum, allowed = cached['tensors']
            state['optimizer'].zero_grad(set_to_none=True)
            with span('forward', timing):
                state['accounting']['model_forward_entered'] += 1
                projected, logits = state['model'](vector, target[:, :-1])
                state['accounting']['model_forward_completed'] += 1
                _need(tuple(projected.shape) == (1, 384) and tuple(logits.shape) == (1, 46, 537)
                      and projected.dtype is logits.dtype is torch.float32
                      and projected.device.type == logits.device.type == 'cpu'
                      and logits.requires_grad and bool(torch.isfinite(logits).all())
                      and bool(torch.isfinite(projected).all()), 'complete finite forward geometry required')
            guard(timing)
            with span('objective', timing):
                state['accounting']['cached_objective_calls_entered'] += 1
                # Exact direct-role scalar and observation; only invariant tensors
                # are cached. Every full537 score is checked before masking.
                _need(isinstance(logits, torch.Tensor) and logits.device.type == 'cpu'
                      and logits.dtype is torch.float32 and tuple(logits.shape) == (1, 46, 537)
                      and logits.requires_grad and bool(torch.isfinite(logits).all()),
                      'complete differentiable finite teacher-forced scores required before masking')
                version, saved, objective_rng = logits._version, logits.detach().clone(), torch.get_rng_state().clone()
                try:
                    flat = logits.reshape(-1, 537)
                    losses = torch.nn.functional.cross_entropy(flat.masked_fill(~allowed, -torch.inf),
                        labels, ignore_index=0, reduction='none')
                    with torch.no_grad():
                        full = torch.nn.functional.cross_entropy(flat, labels, ignore_index=0, reduction='none')
                    loss = (losses * position_weights).sum() / weight_sum
                    _need(loss.ndim == 0 and loss.requires_grad and bool(torch.isfinite(loss))
                          and bool(torch.isfinite(losses).all()) and bool(torch.isfinite(full).all()),
                          'finite conditional role objective required')
                    objective_report = dict(schema='legal-compact-role-objective-observation/v1',
                        checkpoint_sha256=parent, objective_policy_sha256=data['expected_policy'],
                        objective_kind='scope_conditional', weighting=current['objective_policy']['weighting'],
                        basis_checkpoint_sha256=current['basis_checkpoint_sha256'], row_id=row['id'], row_index=row['row_index'],
                        inventory_sha256=row['inventory_sha256'], baseline_inventory_sha256=row['baseline_inventory_sha256'],
                        scope_inventory_sha256=row['scope_inventory_sha256'], role_inventory_sha256=row['role_inventory_sha256'],
                        scope_policy_sha256=row['scope_policy_sha256'], target_ids=row['target_ids'], label_ids=row['target_ids'][1:],
                        position_weights=row['position_weights'], position_roles=row['position_roles'],
                        position_syntax_roles=row['position_syntax_roles'], weight_sum=67.0, supervised_positions=46,
                        scope_allowed_token_ids=row['scope_allowed_token_ids'], baseline_decision_kinds=row['baseline_decision_kinds'],
                        singleton_positions=39, nontrivial_positions=7, per_position_losses=losses.detach().tolist(),
                        weighted_loss=float(loss.detach()), full537_per_position_losses=full.detach().tolist(),
                        full537_weighted_loss=float(((full * position_weights).sum() / weight_sum).detach()),
                        reduction='scope_masked_none_role_weighted_sum_divide67', full537_logits_observed=True,
                        full537_vocabulary=False, conditional_allowed_set_loss=True, singleton_zero_loss_is_not_accuracy=True,
                        full537_and_conditional_losses_not_comparable_as_accuracy=True, teacher_forcing=True,
                        forward_performed=False, backward_performed=False, optimizer_update_performed=False,
                        structural_role_priority_is_not_semantic_verification=True, authority=dict(owner.AUTHORITY))
                    # Return detached metadata, never aliases to the guarded cache.
                    objective_report = deepcopy(objective_report)
                finally:
                    source_fence()
                    input_fence()
                    _need(logits._version == version and torch.equal(saved, logits.detach())
                          and torch.equal(objective_rng, torch.get_rng_state())
                          and owner._wire(weighted._numeric(modules)[2]) == owner._wire(runtime),
                          'cached objective mutated input/RNG or runtime')
                state['accounting']['cached_objective_calls_completed'] += 1
            with span('backward', timing):
                state['accounting']['backward_entered'] += 1
                loss.backward()
                state['accounting']['backward_completed'] += 1
            with span('gradient_capture_clip', timing):
                preclip = gradients()
                norm = torch.nn.utils.clip_grad_norm_(list(state['model'].parameters()), 5.0, error_if_nonfinite=True)
                postclip = gradients()
            guard(timing)
            with span('Adam', timing):
                state['accounting']['optimizer_step_entered'] += 1
                state['optimizer'].step()
                state['accounting']['optimizer_step_completed'] += 1
            completed = current['progress']['optimizer_steps'] + 1
            progress = dict(optimizer_steps=completed, epochs_completed=completed // 2, row_cursor=completed % 2)
            with span('lineage_pack', timing):
                state['accounting']['checked_pack_calls_entered'] += 1
                steps = weighted._progress(progress)
                _need(steps == current['progress']['optimizer_steps'] + 1,
                      'role packing must advance exactly one actual update')
                _need(owner._wire(weighted._numeric(modules)[2]) == owner._wire(runtime),
                      'actual packing runtime differs')
                pack_rng = torch.get_rng_state().clone()
                try:
                    # The original validator checks every changed model/Adam
                    # value. Invariant basis, grammar and objective came from
                    # entry validation and remain privately owned unchanged.
                    weights, moments = weighted._actual(state['model'], state['optimizer'], current,
                        steps, modules, numerical, torch)
                    successor = deepcopy(current)
                    successor.update(model_state=weights, weights_sha256=owner._digest(weights),
                        optimizer_state=moments, optimizer_state_sha256=owner._digest(moments),
                        progress=deepcopy(progress), parent_checkpoint_sha256=parent,
                        initial_checkpoint_sha256=parent if current['progress']['optimizer_steps'] == 0
                        else current['initial_checkpoint_sha256'])
                    checkpoint_raw = owner._wire(successor)
                    _need(len(checkpoint_raw) <= owner.MAX_CHECKPOINT_BYTES,
                          'complete successor exceeds original checkpoint byte bound')
                    successor_hash = hashlib.sha256(checkpoint_raw).hexdigest()
                finally:
                    source_fence()
                    input_fence()
                    _need(torch.equal(pack_rng, torch.get_rng_state())
                          and owner._wire(weighted._numeric(modules)[2]) == owner._wire(runtime),
                          'checked packing changed CPU RNG or numerical runtime')
                snapshot = numeric_mark()
                state['accounting']['checked_pack_calls_completed'] += 1
                # Commit only a complete bounded successor after changed-state
                # validation, exact lineage construction and closing custody.
                state['value'], state['checkpoint_sha256'] = successor, successor_hash
                state['completed_updates'] += 1
                state['snapshot'] = snapshot
            guard(timing)
            with span('report_export', timing):
                report = dict(schema=STEP_SCHEMA, before_checkpoint_sha256=parent,
                    after_checkpoint_sha256=successor_hash, checkpoint_sha256=successor_hash,
                    checkpoint=deepcopy(successor), checkpoint_progress=deepcopy(progress),
                    row_id=row['id'], row_index=row['row_index'], objective_report=objective_report,
                    objective_policy_sha256=data['expected_policy'], weighting=row['weighting'],
                    role_inventory_sha256=row['role_inventory_sha256'], objective_kind='scope_conditional',
                    full_sequence_logits=logits.detach().tolist(), loss=float(loss.detach()),
                    preclip_gradients=preclip, postclip_gradients=postclip,
                    preclip_global_L2_Torch=float(norm), global_clip_max_norm=5.0,
                    model_state_sha256=successor['weights_sha256'], optimizer_state_sha256=successor['optimizer_state_sha256'],
                    preparation=deepcopy(preparation), training_exposed=True, teacher_forced=True,
                    conditional_allowed_set_loss=True, full537_logits_observed=True, full537_vocabulary=False,
                    singleton_zero_loss_is_not_accuracy=True, checkpoint_durable=False,
                    checkpoint_schema_conversion=False, authority=deepcopy(owner.AUTHORITY))
                for field in ('target_ids', 'label_ids', 'position_weights', 'weight_sum', 'scope_allowed_token_ids',
                              'inventory_sha256', 'baseline_inventory_sha256', 'scope_inventory_sha256',
                              'scope_policy_sha256', 'reduction', 'position_roles', 'position_syntax_roles'):
                    report[field] = deepcopy(objective_report[field])
                for field in ('full_sequence_logits', 'preclip_gradients', 'postclip_gradients'):
                    report[field + '_sha256'] = owner._digest(report[field])
                _wire(report, MAX_STEP_REPORT_BYTES)
            report['timing'] = dict(intervals=timing, wall_and_calling_thread_CPU_only=True, durable_IO_external=True)
            _wire(report, MAX_STEP_REPORT_BYTES)
            return report

        def dispatch(operation, argument):
            _need(os.getpid() == state['pid'] and threading.get_ident() == state['thread'],
                  'session confined to original process and thread')
            _need(not state['busy'], 'prepared operations cannot overlap or reenter')
            if operation == 'inspect':
                return summary()
            if operation == 'close' and state['status'] == 'closed':
                answer = summary()
                answer.update(deepcopy(state['close_fields']))
                return answer
            _need(state['status'] != 'closed', 'prepared session lifetime ended')
            if operation == 'advance':
                _need(state['status'] == 'ready', 'poisoned prepared session cannot advance')
                _need(type(argument) is int and 1 <= argument <= MAX_ADVANCE_STEPS
                      and argument <= data['max_steps'] - state['completed_updates'],
                      'plain bounded advance within remaining declared work required')
            _need(operation in ('advance', 'checkpoint', 'close'), 'unknown prepared operation')
            state['busy'] = True
            try:
                if operation == 'close':
                    prior, closing_errors = state['status'], []
                    try:
                        try:
                            guard([])
                        except BaseException as error:
                            closing_errors.append(error)
                        try:
                            scope.__exit__(None, None, None)
                        except BaseException as error:
                            closing_errors.append(error)
                    finally:
                        state['model'] = state['optimizer'] = state['rows'] = state['snapshot'] = None
                        state['status'] = 'closed'
                    state['close_fields'] = dict(status_before_close=prior, private_references_released=True,
                        closing_guard_passed=not closing_errors,
                        closing_error_types=[type(error).__name__ for error in closing_errors])
                    answer = summary()
                    answer.update(deepcopy(state['close_fields']))
                    if closing_errors and prior != 'poisoned':
                        raise closing_errors[0]
                    return answer
                if operation == 'checkpoint':
                    guard([], state_check=state['status'] == 'ready')
                    return deepcopy(state['value'])
                reports = [step() for _ in range(argument)]
                answer = dict(schema=ADVANCE_SCHEMA, reports=reports, checkpoint=deepcopy(state['value']),
                    checkpoint_sha256=state['checkpoint_sha256'], preparation=deepcopy(preparation),
                    accounting=deepcopy(state['accounting']), timing=timing_report(), durable_outputs_written=False)
                _wire(answer, MAX_ADVANCE_BYTES)
                return answer
            except BaseException as error:
                state['last_failure_stage'] = state['stage']
                if operation != 'close':
                    state['status'] = 'poisoned'
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    BaseException.add_note(error, 'Prepared role work counters remain available through inspect().')
                    raise
                raise decorate(error) from error
            finally:
                state['busy'] = False

        state['status'] = 'ready'
        guard(state['preparation_timing'])
        preparation['timing'] = deepcopy(state['preparation_timing'])
        return owners['capsule'].PreparedTrainingSession(dispatch)
    except BaseException as error:
        state['last_failure_stage'] = state['stage']
        state['status'] = 'poisoned'
        state['model'] = state['optimizer'] = state['rows'] = state['snapshot'] = None
        if entered:
            try:
                scope.__exit__(type(error), error, error.__traceback__)
            except BaseException:
                BaseException.add_note(error, 'Closing failed role prepared construction also failed.')
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise decorate(error) from error


__all__ = ['PreparedTrainingError', 'prepare']

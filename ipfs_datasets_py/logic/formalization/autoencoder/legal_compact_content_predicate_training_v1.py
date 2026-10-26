"""Separate predicate-sum70 state using immutable legacy reference sidecars.

The genuine legacy checkpoints supply ordered row/weight witnesses, never a
carrier for the new model's history. Existing owners still construct the model
and Adam, compute the scalar, validate named state and serialize tensors. This
module owns only its closed policy, state, custody and successor lineage. The
caller owns resource admission and actual forward/backward/update observations.
Mechanical packing does not attest which objective caused an optimizer update.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import stat
import sys


SCHEMA = 'legal-compact-predicate-training-checkpoint/v1'
POLICY_SCHEMA = 'legal-compact-predicate-training-objective/v1'
OBSERVATION_SCHEMA = 'legal-compact-predicate-training-objective-observation/v1'
PROFILE = 'authored-h0-384-fixed537-CP128-fresh-Adam-predicate-sum70/v1'
ARCHITECTURE = 'inherited-joint-gru-h0-only/v1'
MAX_CHECKPOINT_BYTES = 4 * 1024**2
MAX_INPUT_BYTES = 24 * 1024**2
MAX_JSON_ITEMS = 12_000_000
MAX_JSON_DEPTH = 96
AUTHORITY = dict.fromkeys(('source_encoder_authenticated', 'source_semantics_verified',
    'training_gold_qualified', 'evaluation_gold_qualified', 'heldout_accuracy',
    'statutory_accuracy', 'production_ready', 'permitted_inference_context',
    'checkpoint_compatible', 'graph_admission', 'Lean_admission', 'native_admission'), False)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_PACKAGE = 'ipfs_datasets_py.logic.formalization.autoencoder'
_SPECS = (
    ('legacy', 'legal_compact_content_role_warmstart_training_v1',
     '59e5294ed018e95eb2c3aa0ccaef1caf50bb915b58b454316564bc94375db6ba'),
    ('diagnostic', 'legal_compact_content_predicate_objective_v1',
     '72ea1156b49f44bb7b5fb7fd0f3bf5bdb8bd9a8b607f8f971f2af4c9af9384a9'),
)
DIAGNOSTIC_POLICY_SHA256 = '39f58ccc3a51f193bee237e89e9b767979644c248e2d3dfa03b7eb19fe9906ae'
_REFERENCES = {
    'full537': {
        'row0': '1ef7d777554bea20aa1d77209f55f1eb987598e44a18b737a1d3541e2683ab12',
        'row1': 'e69ea83a93cade5898578841b864311cae90643afda5a7eb9a220cb2e6120a11',
        'policy': '0ed591ba2aa4eb4e12fa82766cd1436054438540e64a338ab5177cf77e946c6f',
    },
    'scope_conditional': {
        'row0': 'a6b6b0cd589a74d59598c6984040676baf6f27a24a7b61f0ba0a6a5f38d5f64e',
        'row1': '9d93601d35dc371ea6895e1deca175b7b41b6279a05400c695edfaa2c8e96116',
        'policy': '701807e4e15652321efe70c29ffa894e6626776ef5df872447cb270ca0dd1c3a',
    },
}
_MECHANICS = ('config', 'codec', 'codec_sha256', 'runtime', 'runtime_sha256',
    'parameter_order', 'optimizer_config', 'adam_policy', 'update_policy',
    'basis_checkpoint_sha256', 'role_inventories_sha256')
_FIELDS = {'schema', 'profile', 'architecture', 'input_dimension', 'vocabulary_size',
    'max_total_ids', 'reference_commitments', 'legacy_objective_policy_sha256',
    'diagnostic_policy_sha256', 'objective_policy', 'objective_policy_sha256',
    'config', 'codec', 'codec_sha256', 'runtime', 'runtime_sha256', 'parameter_order',
    'optimizer_config', 'adam_policy', 'update_policy', 'basis_checkpoint_sha256',
    'role_inventories_sha256', 'model_state', 'weights_sha256', 'initial_weights_sha256',
    'optimizer_state', 'optimizer_state_sha256', 'progress', 'initial_checkpoint_sha256',
    'parent_checkpoint_sha256', 'optimizer_history_origin', 'implementation',
    'causal_gradient_history_attested', 'authority', 'training_mask', 'evaluation_gold_mask'}
_DIAGNOSTIC_FIELDS = set(('schema profile status diagnostic_policy diagnostic_policy_sha256 '
    'legacy_checkpoint_sha256 legacy_policy_sha256 legacy_objective_kind legacy_report legacy_report_sha256 '
    'row_id row_index predicate_position_index predicate_target_position predicate_role '
    'predicate_allowed_token_ids predicate_scope_allowed_token_ids predicate_target_id old_position_weights '
    'proposed_position_weights old_weight_sum proposed_weight_sum legacy_weighted_loss proposed_weighted_loss '
    'predicate_cross_entropy legacy_full537_weighted_loss proposed_full537_weighted_loss '
    'predicate_full537_cross_entropy legacy_conditional_weighted_loss proposed_conditional_weighted_loss '
    'predicate_conditional_cross_entropy scalar_formula legacy_objective_calls differentiable_scalar_returned '
    'teacher_forcing model_constructed optimizer_constructed restore_performed forward_performed '
    'backward_performed optimizer_update_performed checkpoint_created checkpoint_packed '
    'new_training_profile_status new_checkpoint_profile_status checkpoint_compatible producer_pins '
    'producer_pin_scope authority training_mask evaluation_gold_mask limitations').split())


class PredicateTrainingError(ValueError):
    """Closed reference, policy, state, numerical or custody validation failed."""


def _need(ok, message):
    if not ok:
        raise PredicateTrainingError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          'independent lowercase SHA256 required: ' + label)


def _wire(value, maximum=MAX_INPUT_BYTES):
    # Check plain types before JSON can call a user-defined iterable or encoder.
    remaining = MAX_JSON_ITEMS

    def ordinary(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= MAX_JSON_DEPTH, 'bounded ordinary JSON required')
        kind = type(item)
        if kind is dict:
            _need(all(type(key) is str for key in item), 'plain string JSON keys required')
            for child in item.values():
                ordinary(child, depth + 1)
        elif kind is list:
            for child in item:
                ordinary(child, depth + 1)
        else:
            _need(kind in (str, int, float, bool, type(None))
                  and (kind is not float or math.isfinite(item)), 'ordinary finite JSON required')

    ordinary(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise PredicateTrainingError('bounded ordinary finite JSON required') from error
    _need(len(raw) <= maximum, 'complete canonical JSON byte bound exceeded')
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def policy(objective_kind):
    """Return one closed successor descriptor without numerical allocation."""
    _need(type(objective_kind) is str and objective_kind in _REFERENCES,
          'closed full537 or scope_conditional objective required')
    _need(type(AUTHORITY) is dict and len(AUTHORITY) == 12
          and all(type(x) is bool and x is False for x in AUTHORITY.values()),
          'all successor authority flags must remain false')
    refs = _REFERENCES[objective_kind]
    return dict(schema=POLICY_SCHEMA, profile=PROFILE, objective_kind=objective_kind,
        vocabulary_normalization='all537' if objective_kind == 'full537' else 'original_scope_allowed_ids',
        legacy_weighting='semantic_priority', changed_role='predicate_constructor',
        old_predicate_weight=1, new_predicate_weight=4, old_complete_weight_sum=67,
        new_complete_weight_sum=70, all_other_unnormalized_position_weights_unchanged=True,
        normalization='sum_of_complete_position_weights', scalar_formula='(67*legacy_loss+3*predicate_cross_entropy)/70',
        supervised_positions=46, singleton_positions=39, nontrivial_positions=7,
        input_dimension=384, vocabulary_size=537, reference_row_order=['row0', 'row1'],
        reference_checkpoint_sha256={key: refs[key] for key in ('row0', 'row1')},
        legacy_objective_policy_sha256=refs['policy'], diagnostic_policy_sha256=DIAGNOSTIC_POLICY_SHA256,
        reference_context_not_current_model_state=True, optimizer_origin='fresh_Adam_from_immutable_CP128',
        old_row1_weights_and_Adam_inherited=False, causal_gradient_history_attested=False,
        legacy_checkpoint_compatible=False, target_exposed=True,
        authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0)


def policy_sha256(value):
    _need(type(value) is dict and type(value.get('objective_kind')) is str,
          'closed successor policy required')
    _need(_wire(value) == _wire(policy(value['objective_kind'])), 'closed successor policy differs')
    return _digest(value)


def checkpoint_sha256(checkpoint):
    """Hash bounded plain state; a hash alone is not checkpoint validation."""
    return hashlib.sha256(_wire(checkpoint, MAX_CHECKPOINT_BYTES)).hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path, 'unaliased owner source required')
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= 131072, 'bounded single-link source required')
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns, x.st_nlink)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, 'owner source or physical identity changed')
    return dict(path=str(path), bytes=len(raw), sha256=expected), identity(after)


def _package_paths():
    package = importlib.import_module(_PACKAGE)
    paths = list(package.__path__)
    _need(len(paths) == 1 and type(paths[0]) is str, 'one canonical numerical package required')
    directory = Path(paths[0]).absolute()
    _need(directory.resolve(strict=True) == directory and directory.parts[-4:] ==
          ('ipfs_datasets_py', 'logic', 'formalization', 'autoencoder'), 'canonical package geometry differs')
    for name, expected in (('ipfs_datasets_py', directory.parents[2]),
                           ('ipfs_datasets_py.logic', directory.parents[1]),
                           ('ipfs_datasets_py.logic.formalization', directory.parent)):
        module = sys.modules.get(name)
        _need(module is not None and list(module.__path__) == [str(expected)],
              'canonical numerical parent package differs')
    return package, directory


def _owners():
    package, directory = _package_paths()
    modules, observations = {}, {}
    for key, name, pin in _SPECS:
        path = directory / (name + '.py')
        observed = _source(path, pin)
        module = importlib.import_module(_PACKAGE + '.' + name)
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == path
              and _source(path, pin) == observed, 'canonical owner origin changed')
        modules[key], observations[key] = module, observed
    return package, directory, modules, observations


@contextmanager
def _scope(original):
    # Own the large reference bank once. The original scope receives no copies
    # of it; it still supplies the genuine complete legacy source closure.
    raw = _wire(original)
    data = json.loads(raw)
    own = _source(_SELF_PATH, _SELF_SHA)
    package, directory, owners, observations = _owners()
    failure = None

    def outer():
        _need(type(__file__) is str and Path(__file__).absolute() == _SELF_PATH
              and _source(_SELF_PATH, _SELF_SHA) == own, 'successor source or origin changed')
        current, location = _package_paths()
        _need(current is package and location == directory, 'successor package changed')
        for key, name, pin in _SPECS:
            _need(type(owners[key].__file__) is str
                  and Path(owners[key].__file__).absolute() == directory / (name + '.py')
                  and _source(directory / (name + '.py'), pin) == observations[key],
                  'successor dependency source or origin changed')

    def inputs():
        _need(_wire(original) == raw and _wire(data) == raw,
              'original or detached successor inputs changed')

    try:
        outer()
        with owners['legacy']._scope({}) as (_, modules, legacy_fence):
            modules.update(owners)
            def fence():
                inputs()
                legacy_fence()
                outer()
            fence()
            yield data, modules, fence, [own[0]] + [observations[key][0] for key, _, _ in _SPECS]
            fence()
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, PredicateTrainingError):
            failure = PredicateTrainingError(str(error))
            raise failure from error
        raise
    finally:
        try:
            inputs()
            outer()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, 'A closing predicate successor custody check also failed.')


def _implementation():
    return dict(predicate_training_sha256=_SELF_SHA,
        direct_owners={name + '.py': pin for _, name, pin in _SPECS})


def _references(offered, objective_kind, modules):
    _need(type(offered) is dict and set(offered) == {'row0', 'row1'},
          'exact row0/row1 reference_inputs required')
    description = policy(objective_kind)
    expected = _REFERENCES[objective_kind]
    legacy = modules['legacy']
    values, rows, commitments = {}, {}, {}
    # Fixed digests reject rehashed foreign, swapped or moved-progress contexts.
    for index, key in enumerate(('row0', 'row1')):
        _need(checkpoint_sha256(offered[key]) == expected[key], 'immutable legacy reference differs: ' + key)
        value = legacy._validate(offered[key], expected[key], expected['policy'], modules)
        _need(value['progress'] == dict(optimizer_steps=index, epochs_completed=0, row_cursor=index)
              and value['objective_policy']['objective_kind'] == objective_kind,
              'legacy row reference progress or normalization differs')
        row = legacy._row(value, modules)
        _need(row['row_index'] == index, 'legacy reference row order differs')
        values[key], rows[key] = value, row
        commitments[key] = dict(checkpoint_sha256=expected[key], row_index=index, row_id=row['id'],
            legacy_policy_sha256=expected['policy'], target_ids_sha256=_digest(row['target_ids']),
            baseline_inventory_sha256=row['baseline_inventory_sha256'],
            scope_inventory_sha256=row['scope_inventory_sha256'],
            role_inventory_sha256=row['role_inventory_sha256'])
    initial, later = values['row0'], values['row1']
    _need(later['initial_checkpoint_sha256'] == later['parent_checkpoint_sha256'] == expected['row0']
          and initial['initial_checkpoint_sha256'] is initial['parent_checkpoint_sha256'] is None,
          'genuine legacy reference lineage differs')
    for key in _MECHANICS + ('warmstart_parent_checkpoint_sha256', 'warmstart_parent_policy_sha256'):
        _need(_wire(initial[key]) == _wire(later[key]), 'legacy reference mechanics differ: ' + key)
    diagnostic = modules['diagnostic']
    _need(diagnostic.policy_sha256(diagnostic.policy()) == DIAGNOSTIC_POLICY_SHA256
          == description['diagnostic_policy_sha256'], 'fixed diagnostic policy differs')
    return values, rows, commitments


def _fresh_adam():
    return dict(schema='adam-default-betas-eps/v1', parameters={})


def _initial(value, reference):
    result = deepcopy(value)
    result.update(model_state=deepcopy(reference['model_state']), weights_sha256=reference['weights_sha256'],
        optimizer_state=_fresh_adam(), optimizer_state_sha256=_digest(_fresh_adam()),
        progress=dict(optimizer_steps=0, epochs_completed=0, row_cursor=0),
        initial_checkpoint_sha256=None, parent_checkpoint_sha256=None)
    return result


def _validate(offered, expected, expected_policy, reference_inputs, modules):
    _sha(expected, 'successor checkpoint')
    _sha(expected_policy, 'successor policy')
    _need(type(offered) is dict and set(offered) == _FIELDS
          and checkpoint_sha256(offered) == expected, 'closed independently bound successor checkpoint required')
    _need(offered['schema'] == SCHEMA and offered['profile'] == PROFILE
          and offered['architecture'] == ARCHITECTURE and all(type(offered[k]) is int and offered[k] == n
          for k, n in (('input_dimension', 384), ('vocabulary_size', 537), ('max_total_ids', 512))),
          'successor schema/profile or geometry differs')
    objective = offered['objective_policy']
    _need(type(objective) is dict and policy_sha256(objective) == expected_policy
          == offered['objective_policy_sha256'], 'successor objective differs')
    refs, rows, commitments = _references(reference_inputs, objective['objective_kind'], modules)
    reference = refs['row0']
    _need(_wire(offered['reference_commitments']) == _wire(commitments)
          and offered['legacy_objective_policy_sha256'] == reference['objective_policy_sha256']
          and offered['diagnostic_policy_sha256'] == DIAGNOSTIC_POLICY_SHA256,
          'successor reference commitments differ')
    for key in _MECHANICS:
        _need(_wire(offered[key]) == _wire(reference[key]), 'unchanged successor mechanics differ: ' + key)
    _need(offered['optimizer_history_origin'] == 'fresh_from_immutable_CP128_for_declared_predicate_sum70'
          and offered['initial_weights_sha256'] == reference['weights_sha256']
          and _wire(offered['implementation']) == _wire(_implementation()), 'successor implementation/history differs')
    modules['head']._state(offered['model_state'], offered['config'])
    _need(offered['weights_sha256'] == _digest(offered['model_state']), 'complete successor model state differs')
    steps = modules['weighted']._progress(offered['progress'])
    modules['trainer']._optimizer_state(offered['optimizer_state'], offered['progress'], offered['config'], modules['head'])
    _need(offered['optimizer_state_sha256'] == _digest(offered['optimizer_state']), 'complete named successor Adam differs')
    if not steps:
        _need(offered['model_state'] == reference['model_state'] and offered['optimizer_state'] == _fresh_adam()
              and offered['initial_checkpoint_sha256'] is offered['parent_checkpoint_sha256'] is None,
              'zero-step successor requires exact CP128 weights and fresh Adam')
    else:
        _sha(offered['initial_checkpoint_sha256'], 'initial successor')
        _sha(offered['parent_checkpoint_sha256'], 'immediate successor parent')
        _need(offered['initial_checkpoint_sha256'] == checkpoint_sha256(_initial(offered, reference)),
              'initial successor lineage differs')
        if steps == 1:
            _need(offered['parent_checkpoint_sha256'] == offered['initial_checkpoint_sha256'],
                  'first successor update parent differs')
    _need(offered['causal_gradient_history_attested'] is False
          and _wire(offered['authority']) == _wire(AUTHORITY)
          and type(offered['training_mask']) is type(offered['evaluation_gold_mask']) is int
          and offered['training_mask'] == offered['evaluation_gold_mask'] == 0,
          'mechanical state supplies no causal, scientific or legal authority')
    return offered, refs, rows


def create(reference_inputs, *, expected_reference_checkpoint_sha256,
           expected_legacy_policy_sha256, objective_kind):
    """Initialize only the new state; sidecars stay external and unchanged."""
    description = policy(objective_kind)
    _need(_wire(expected_reference_checkpoint_sha256) == _wire(description['reference_checkpoint_sha256'])
          and expected_legacy_policy_sha256 == description['legacy_objective_policy_sha256'],
          'independent original reference/policy commitments differ')
    with _scope(dict(reference_inputs=reference_inputs, expected=expected_reference_checkpoint_sha256,
                     expected_policy=expected_legacy_policy_sha256, objective_kind=objective_kind)) as (data, modules, _, _sources):
        refs, _, commitments = _references(data['reference_inputs'], data['objective_kind'], modules)
        reference = refs['row0']
        value = dict(schema=SCHEMA, profile=PROFILE, architecture=ARCHITECTURE,
            input_dimension=384, vocabulary_size=537, max_total_ids=512,
            reference_commitments=commitments, legacy_objective_policy_sha256=data['expected_policy'],
            diagnostic_policy_sha256=DIAGNOSTIC_POLICY_SHA256, objective_policy=description,
            objective_policy_sha256=policy_sha256(description),
            model_state=deepcopy(reference['model_state']), weights_sha256=reference['weights_sha256'],
            initial_weights_sha256=reference['weights_sha256'], optimizer_state=_fresh_adam(),
            optimizer_state_sha256=_digest(_fresh_adam()), progress=dict(optimizer_steps=0, epochs_completed=0, row_cursor=0),
            initial_checkpoint_sha256=None, parent_checkpoint_sha256=None,
            optimizer_history_origin='fresh_from_immutable_CP128_for_declared_predicate_sum70',
            implementation=_implementation(), causal_gradient_history_attested=False,
            authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0)
        for key in _MECHANICS:
            value[key] = deepcopy(reference[key])
        _validate(value, checkpoint_sha256(value), value['objective_policy_sha256'], data['reference_inputs'], modules)
        return value


def inspect(checkpoint, *, reference_inputs, expected_checkpoint_sha256, expected_policy_sha256):
    """Validate complete state and both references without numerical allocation."""
    with _scope(dict(checkpoint=checkpoint, reference_inputs=reference_inputs,
                     expected=expected_checkpoint_sha256, policy=expected_policy_sha256)) as (data, modules, _, _sources):
        value, _, _ = _validate(data['checkpoint'], data['expected'], data['policy'], data['reference_inputs'], modules)
        return dict(schema=SCHEMA, profile=PROFILE, checkpoint_sha256=data['expected'],
            objective_policy_sha256=data['policy'], objective_kind=value['objective_policy']['objective_kind'],
            reference_commitments=deepcopy(value['reference_commitments']), progress=deepcopy(value['progress']),
            weights_sha256=value['weights_sha256'], optimizer_state_sha256=value['optimizer_state_sha256'],
            initial_checkpoint_sha256=value['initial_checkpoint_sha256'],
            parent_checkpoint_sha256=value['parent_checkpoint_sha256'],
            model_constructed=False, optimizer_constructed=False, runtime_verified=False,
            causal_gradient_history_attested=False, legacy_checkpoint_compatible=False,
            authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0)


def _proposed_weights(row):
    selected = [i for i, p in enumerate(row['role_positions']) if p['role'] == 'predicate_constructor']
    _need(len(selected) == 1 and len(row['position_weights']) == 46, 'one original predicate role required')
    index = selected[0]
    role = row['role_positions'][index]
    weights = list(row['position_weights'])
    _need(role['syntax_role'] == 'constructor' and role['lexical_token'] == '"predicate"'
          and role['target_position'] == index + 1 and role['target_token_id'] == row['target_ids'][index + 1]
          and role['weight'] == weights[index] == 1.0 and math.fsum(weights) == 67.0,
          'original predicate role or sum67 weights differ')
    weights[index] = 4.0
    _need(math.fsum(weights) == 70.0, 'complete proposed weights must sum70')
    return weights


def training_row(checkpoint, *, reference_inputs, expected_checkpoint_sha256, expected_policy_sha256):
    with _scope(dict(checkpoint=checkpoint, reference_inputs=reference_inputs,
                     expected=expected_checkpoint_sha256, policy=expected_policy_sha256)) as (data, modules, _, _sources):
        value, _, rows = _validate(data['checkpoint'], data['expected'], data['policy'], data['reference_inputs'], modules)
        key = 'row' + str(value['progress']['row_cursor'])
        row = deepcopy(rows[key])
        # Do not reseal the original role inventory with substituted weights.
        row.update(proposed_position_weights=_proposed_weights(row), old_weight_sum=67.0,
            proposed_weight_sum=70.0, training_policy_sha256=data['policy'],
            successor_checkpoint_sha256=data['expected'], reference_key=key,
            reference_checkpoint_sha256=value['reference_commitments'][key]['checkpoint_sha256'],
            reference_context_not_current_model_state=True, causal_gradient_history_attested=False)
        return row


def _numeric(value, modules):
    numerical, torch, runtime = modules['weighted']._numeric(modules)
    _need(_wire(runtime) == _wire(value['runtime']), 'actual successor numerical runtime differs')
    return numerical, torch, runtime


def _diagnostic_observation(observed, value, reference, row, reference_pin, modules, sources):
    """Crossbind an actual public return without invoking a second objective."""
    diagnostic = modules['diagnostic']
    _need(type(observed) is dict and set(observed) == _DIAGNOSTIC_FIELDS,
          'complete closed diagnostic observation required')
    _need(observed['schema'] == 'legal-compact-predicate-objective-observation/v1'
          and observed['profile'] == 'authored384-fixed537-predicate-constructor-four-diagnostic/v1'
          and observed['status'] == 'differentiable_diagnostic_only'
          and observed['legacy_checkpoint_sha256'] == reference_pin
          and observed['legacy_policy_sha256'] == value['legacy_objective_policy_sha256']
          and observed['diagnostic_policy_sha256'] == DIAGNOSTIC_POLICY_SHA256
          and diagnostic.policy_sha256(observed['diagnostic_policy']) == DIAGNOSTIC_POLICY_SHA256
          and observed['legacy_objective_kind'] == value['objective_policy']['objective_kind']
          and type(observed['row_index']) is int and observed['row_index'] == row['row_index']
          and observed['row_id'] == row['id'], 'genuine diagnostic reference context differs')
    legacy_report = observed['legacy_report']
    diagnostic._legacy_observation(legacy_report, reference, row, modules['legacy'])
    weights = _proposed_weights(row)
    index = next(i for i, p in enumerate(row['role_positions']) if p['role'] == 'predicate_constructor')
    conditional = value['objective_policy']['objective_kind'] == 'scope_conditional'
    expected_rows = dict(predicate_role=row['role_positions'][index],
        predicate_allowed_token_ids=row['scope_allowed_token_ids'][index] if conditional else list(range(537)),
        predicate_scope_allowed_token_ids=row['scope_allowed_token_ids'][index],
        old_position_weights=row['position_weights'], proposed_position_weights=weights,
        producer_pins=[sources[2], sources[1]])
    _need(all(_wire(observed[key]) == _wire(expected) for key, expected in expected_rows.items())
          and observed['legacy_report_sha256'] == _digest(legacy_report)
          and type(observed['predicate_position_index']) is type(observed['predicate_target_position']) is int
          and observed['predicate_position_index'] == index and observed['predicate_target_position'] == index + 1
          and type(observed['predicate_target_id']) is int and observed['predicate_target_id'] == row['target_ids'][index + 1]
          and type(observed['old_weight_sum']) is type(observed['proposed_weight_sum']) is float
          and observed['old_weight_sum'] == 67.0 and observed['proposed_weight_sum'] == 70.0,
          'diagnostic row, role, weights or producer identity differs')
    old, pred = legacy_report['weighted_loss'], legacy_report['per_position_losses'][index]
    full, full_pred = legacy_report['full537_weighted_loss'], legacy_report['full537_per_position_losses'][index]
    numbers = dict(legacy_weighted_loss=old, proposed_weighted_loss=(67 * old + 3 * pred) / 70,
        predicate_cross_entropy=pred, legacy_full537_weighted_loss=full,
        proposed_full537_weighted_loss=(67 * full + 3 * full_pred) / 70,
        predicate_full537_cross_entropy=full_pred,
        legacy_conditional_weighted_loss=old if conditional else None,
        proposed_conditional_weighted_loss=(67 * old + 3 * pred) / 70 if conditional else None,
        predicate_conditional_cross_entropy=pred if conditional else None)
    for key, expected in numbers.items():
        offered = observed[key]
        _need(offered is None if expected is None else type(offered) in (int, float)
              and math.isfinite(offered) and offered >= 0
              and math.isclose(offered, expected, rel_tol=3e-6, abs_tol=2e-6),
              'diagnostic scalar observation differs: ' + key)
    flags = dict(differentiable_scalar_returned=True, teacher_forcing=True, model_constructed=False,
        optimizer_constructed=False, restore_performed=False, forward_performed=False,
        backward_performed=False, optimizer_update_performed=False, checkpoint_created=False,
        checkpoint_packed=False, checkpoint_compatible=False)
    _need(all(type(observed[key]) is bool and observed[key] is expected for key, expected in flags.items())
          and type(observed['legacy_objective_calls']) is int and observed['legacy_objective_calls'] == 1
          and observed['new_training_profile_status'] == observed['new_checkpoint_profile_status'] == 'UNIMPLEMENTED'
          and observed['scalar_formula'] == '(67*legacy_loss+3*predicate_cross_entropy)/70'
          and observed['producer_pin_scope'] == 'direct diagnostic and legacy source; transitive legacy owners fenced by unchanged legacy scope'
          and _wire(observed['authority']) == _wire(diagnostic.AUTHORITY)
          and type(observed['training_mask']) is type(observed['evaluation_gold_mask']) is int
          and observed['training_mask'] == observed['evaluation_gold_mask'] == 0,
          'diagnostic operations, capabilities or authority differ')
    expected_limits = [
        'One exposed authored legacy row and its target prefix; not a source-only or held-out task.',
        'Changing the denominator also scales every unchanged position coefficient by67/70.',
        'The unchanged legacy checkpoint remains its original profile; this diagnostic is not packable training state.',
        'The new scalar supplies no update/resume, autonomous-serving, convergence, statutory, graph or Lean qualification.',
    ]
    _need(_wire(observed['limitations']) == _wire(expected_limits), 'diagnostic capability limits changed')


def restore(checkpoint, *, reference_inputs, expected_checkpoint_sha256, expected_policy_sha256):
    """Use the original model/Adam factories, then load only new-profile state."""
    with _scope(dict(checkpoint=checkpoint, reference_inputs=reference_inputs,
                     expected=expected_checkpoint_sha256, policy=expected_policy_sha256)) as (data, modules, fence, _sources):
        value, refs, _ = _validate(data['checkpoint'], data['expected'], data['policy'], data['reference_inputs'], modules)
        numerical, torch, runtime = _numeric(value, modules)
        rng = torch.get_rng_state().clone()
        failure = None

        def guarded():
            fence()
            _need(torch.equal(rng, torch.get_rng_state()) and _wire(modules['weighted']._numeric(modules)[2]) == _wire(runtime),
                  'successor restore changed CPU RNG or runtime')

        try:
            initial = refs['row0']
            model, optimizer = modules['legacy'].restore(initial,
                expected_checkpoint_sha256=value['reference_commitments']['row0']['checkpoint_sha256'],
                expected_policy_sha256=value['legacy_objective_policy_sha256'])
            templates = model.state_dict()
            _need(list(templates) == value['parameter_order'] and not optimizer.state,
                  'original initial template must have fresh Adam and exact order')
            model.load_state_dict({name: numerical._tensor(value['model_state'][name], template, name)
                                   for name, template in templates.items()}, strict=True)
            for name, parameter in model.named_parameters():
                stored = value['optimizer_state']['parameters'].get(name)
                if stored is not None:
                    optimizer.state[parameter] = dict(step=torch.tensor(float(stored['step']), dtype=torch.float32, device='cpu'),
                        exp_avg=numerical._tensor(stored['exp_avg'], parameter, name + '.exp_avg'),
                        exp_avg_sq=numerical._tensor(stored['exp_avg_sq'], parameter, name + '.exp_avg_sq', nonnegative=True))
            weights, moments = modules['weighted']._actual(model, optimizer, value,
                value['progress']['optimizer_steps'], modules, numerical, torch)
            _need(weights == value['model_state'] and moments == value['optimizer_state'], 'exact named successor restore differs')
            return model, optimizer
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                guarded()
            except BaseException:
                if failure is None:
                    raise
                BaseException.add_note(failure, 'A closing successor restore input/RNG check also failed.')


def objective(checkpoint, logits, *, reference_inputs, expected_checkpoint_sha256, expected_policy_sha256):
    """Return the unchanged diagnostic scalar, labelled with separate state/context."""
    with _scope(dict(checkpoint=checkpoint, reference_inputs=reference_inputs,
                     expected=expected_checkpoint_sha256, policy=expected_policy_sha256)) as (data, modules, fence, sources):
        value, refs, rows = _validate(data['checkpoint'], data['expected'], data['policy'], data['reference_inputs'], modules)
        _, torch, runtime = _numeric(value, modules)
        _need(type(logits) is torch.Tensor and logits.device.type == 'cpu' and logits.dtype is torch.float32
              and tuple(logits.shape) == (1, 46, 537) and logits.requires_grad and bool(torch.isfinite(logits).all()),
              'complete differentiable finite CPU float32 scores required before masking')
        version, saved, rng = logits._version, logits.detach().clone(), torch.get_rng_state().clone()
        failure, captured_report, captured_raw = None, None, None
        key = 'row' + str(value['progress']['row_cursor'])
        reference_pin = value['reference_commitments'][key]['checkpoint_sha256']
        row = rows[key]

        def guarded():
            fence()
            _need(logits._version == version and torch.equal(logits.detach(), saved)
                  and torch.equal(rng, torch.get_rng_state())
                  and _wire(modules['weighted']._numeric(modules)[2]) == _wire(runtime),
                  'successor objective changed logits, CPU RNG or runtime')
            if captured_raw is not None:
                _need(_wire(captured_report) == captured_raw, 'captured diagnostic observation changed')

        try:
            diagnostic = modules['diagnostic']
            loss, captured_report = diagnostic.objective(refs[key], logits,
                expected_checkpoint_sha256=reference_pin,
                expected_policy_sha256=value['legacy_objective_policy_sha256'],
                expected_diagnostic_policy_sha256=DIAGNOSTIC_POLICY_SHA256)
            guarded()
            captured_raw = _wire(captured_report)
            observed = json.loads(captured_raw)
            _diagnostic_observation(observed, value, refs[key], row, reference_pin, modules, sources)
            _need(type(loss) is torch.Tensor and loss.ndim == 0 and loss.device.type == 'cpu'
                  and loss.dtype is torch.float32 and loss.requires_grad and bool(torch.isfinite(loss))
                  and math.isclose(float(loss.detach()), observed['proposed_weighted_loss'], rel_tol=3e-6, abs_tol=2e-6),
                  'genuine diagnostic scalar differs from its observation')
            report = dict(schema=OBSERVATION_SCHEMA, profile=PROFILE, status='differentiable_successor_objective',
                checkpoint_sha256=data['expected'], objective_policy_sha256=data['policy'],
                objective_kind=value['objective_policy']['objective_kind'], progress=deepcopy(value['progress']),
                row_id=row['id'], row_index=row['row_index'], reference_key=key,
                reference_checkpoint_sha256=reference_pin,
                reference_legacy_policy_sha256=value['legacy_objective_policy_sha256'],
                reference_context_not_current_model_state=True, logits_origin_independently_verified=False,
                diagnostic_report=observed, diagnostic_report_sha256=hashlib.sha256(captured_raw).hexdigest(),
                proposed_weighted_loss=observed['proposed_weighted_loss'],
                proposed_position_weights=observed['proposed_position_weights'], old_weight_sum=67.0, proposed_weight_sum=70.0,
                diagnostic_objective_calls=1, differentiable_scalar_returned=True,
                forward_performed=False, backward_performed=False, optimizer_update_performed=False,
                checkpoint_created=False, checkpoint_packed=False,
                causal_gradient_history_attested=False, legacy_checkpoint_compatible=False,
                producer_pins=sources, authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                limitations=['Legacy and diagnostic reports describe immutable reference context, never current model weights or update history.',
                    'The nested standalone diagnostic retains its own unimplemented-training capability flags; this outer owner supplies separate state APIs.',
                    'Caller scores are not independently proven to come from this checkpoint or the corresponding conditioning.',
                    'An owned execution trace is required to observe actual forward/backward/update use; state packing alone cannot attest its cause.',
                    'A declared immediate-parent digest does not independently replay the complete update history.',
                    'Exposed authored384 targets confer no source-encoder, legal, permitted-context, heldout, convergence, graph or Lean authority.'])
            raw = _wire(report)
            guarded()
            return loss, json.loads(raw)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                guarded()
            except BaseException:
                if failure is None:
                    raise
                BaseException.add_note(failure, 'A closing successor objective input/RNG check also failed.')


def pack(model, optimizer, checkpoint, progress, *, reference_inputs,
         expected_checkpoint_sha256, expected_policy_sha256):
    """Export one mechanically checked new step, without causal loss attestation.

    This never calls legacy.pack and never creates an old-profile current-state
    carrier. A separate admitted trace must observe the declared objective use.
    """
    with _scope(dict(checkpoint=checkpoint, reference_inputs=reference_inputs, progress=progress,
                     expected=expected_checkpoint_sha256, policy=expected_policy_sha256)) as (data, modules, fence, _sources):
        value, _, _ = _validate(data['checkpoint'], data['expected'], data['policy'], data['reference_inputs'], modules)
        steps = modules['weighted']._progress(data['progress'])
        _need(steps == value['progress']['optimizer_steps'] + 1, 'packing must advance exactly one successor step')
        numerical, torch, runtime = _numeric(value, modules)
        rng = torch.get_rng_state().clone()
        failure = None

        def guarded():
            fence()
            _need(torch.equal(rng, torch.get_rng_state()) and _wire(modules['weighted']._numeric(modules)[2]) == _wire(runtime),
                  'successor packing changed CPU RNG or runtime')

        try:
            weights, moments = modules['weighted']._actual(model, optimizer, value, steps, modules, numerical, torch)
            result = deepcopy(value)
            result.update(model_state=weights, weights_sha256=_digest(weights), optimizer_state=moments,
                optimizer_state_sha256=_digest(moments), progress=deepcopy(data['progress']),
                parent_checkpoint_sha256=data['expected'],
                initial_checkpoint_sha256=data['expected'] if value['progress']['optimizer_steps'] == 0 else value['initial_checkpoint_sha256'])
            _validate(result, checkpoint_sha256(result), data['policy'], data['reference_inputs'], modules)
            return result
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                guarded()
            except BaseException:
                if failure is None:
                    raise
                BaseException.add_note(failure, 'A closing successor packing input/RNG check also failed.')


__all__ = ['PredicateTrainingError', 'policy', 'policy_sha256', 'checkpoint_sha256',
           'create', 'inspect', 'training_row', 'restore', 'objective', 'pack']

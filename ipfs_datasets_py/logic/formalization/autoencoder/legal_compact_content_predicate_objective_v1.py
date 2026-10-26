"""One fixed counterfactual scalar over the unchanged CP128 objective.

The genuine warm-start objective is called exactly once. Its loss graph is
retained, then one predicate-constructor CE supplies the closed weight1->4,
sum67->70 diagnostic. This module creates no checkpoint/training profile and
constructs no model, optimizer, update, restore, generation or corpus evidence.
"""
from contextlib import contextmanager
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import stat
import sys


POLICY_SCHEMA = 'legal-compact-predicate-objective-policy/v1'
SCHEMA = 'legal-compact-predicate-objective-observation/v1'
PROFILE = 'authored384-fixed537-predicate-constructor-four-diagnostic/v1'
MAX_JSON_BYTES = 24 * 1024**2
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_PACKAGE = 'ipfs_datasets_py.logic.formalization.autoencoder'
_LEGACY_NAME = 'legal_compact_content_role_warmstart_training_v1'
_LEGACY_SHA = '59e5294ed018e95eb2c3aa0ccaef1caf50bb915b58b454316564bc94375db6ba'
_ROLE_POLICY_SHA = '578562275ac7497b52e564028f4dae560b444aca5d0e59275683f5134dfc51ed'
AUTHORITY = dict.fromkeys(('source_encoder_authenticated', 'source_semantics_verified',
    'training_gold_qualified', 'evaluation_gold_qualified', 'heldout_accuracy',
    'statutory_accuracy', 'production_ready', 'training_profile_qualified',
    'checkpoint_compatible', 'graph_admission', 'Lean_admission', 'native_admission'), False)
_LEGACY_FIELDS = {
    'schema', 'checkpoint_sha256', 'objective_policy_sha256', 'objective_kind', 'weighting',
    'warmstart_parent_checkpoint_sha256', 'historical_parent_progress', 'parent_Adam_inherited',
    'basis_checkpoint_sha256', 'row_id', 'row_index', 'inventory_sha256',
    'baseline_inventory_sha256', 'scope_inventory_sha256', 'role_inventory_sha256',
    'scope_policy_sha256', 'target_ids', 'label_ids', 'position_weights', 'position_roles',
    'position_syntax_roles', 'weight_sum', 'supervised_positions', 'scope_allowed_token_ids',
    'baseline_decision_kinds', 'singleton_positions', 'nontrivial_positions',
    'per_position_losses', 'weighted_loss', 'full537_per_position_losses',
    'full537_weighted_loss', 'reduction', 'full537_logits_observed', 'full537_vocabulary',
    'conditional_allowed_set_loss', 'singleton_zero_loss_is_not_accuracy',
    'full537_and_conditional_losses_not_comparable_as_accuracy', 'teacher_forcing',
    'forward_performed', 'backward_performed', 'optimizer_update_performed',
    'structural_role_priority_is_not_semantic_verification', 'authority',
}


class PredicateObjectiveError(ValueError):
    """A fixed diagnostic, genuine legacy observation or custody check failed."""


def _need(condition, message):
    if not condition:
        raise PredicateObjectiveError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          'independent lowercase SHA256 required: ' + label)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise PredicateObjectiveError('bounded finite ordinary JSON required') from error
    _need(len(raw) <= MAX_JSON_BYTES, 'complete diagnostic JSON bound exceeded')
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _plain_equal(offered, expected):
    if type(offered) is not type(expected):
        return False
    if type(expected) is dict:
        return (set(offered) == set(expected)
                and all(_plain_equal(offered[key], value) for key, value in expected.items()))
    if type(expected) is list:
        return len(offered) == len(expected) and all(map(_plain_equal, offered, expected))
    return offered == expected


def policy():
    """Return the fixed descriptor without owner imports or numerical allocation."""
    _need(type(AUTHORITY) is dict and len(AUTHORITY) == 12
          and all(type(value) is bool and value is False for value in AUTHORITY.values()),
          'all fixed diagnostic authority flags must remain false')
    return dict(schema=POLICY_SCHEMA, profile=PROFILE,
        supported_legacy_objective_kinds=['full537', 'scope_conditional'],
        legacy_weighting='semantic_priority', legacy_role_policy_sha256=_ROLE_POLICY_SHA,
        input_dimension=384, vocabulary_size=537, logits_shape=[1, 46, 537],
        supervised_positions=46, singleton_positions=39, nontrivial_positions=7,
        changed_role='predicate_constructor', required_changed_positions=1,
        old_predicate_weight=dict(numerator=1, denominator=1),
        new_predicate_weight=dict(numerator=4, denominator=1),
        old_complete_weight_sum=dict(numerator=67, denominator=1),
        new_complete_weight_sum=dict(numerator=70, denominator=1),
        all_other_position_weights_unchanged=True,
        normalization='sum_of_complete_position_weights',
        scalar_formula='(67*legacy_loss+3*predicate_cross_entropy)/70',
        legacy_objective_calls=1, training_profile_implemented=False,
        checkpoint_profile_implemented=False, target_exposed=True,
        authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0)


def policy_sha256(value):
    """Hash only the exact plain fixed descriptor; arbitrary policies refuse."""
    _need(_plain_equal(value, policy()), 'exact closed predicate diagnostic policy required')
    return _digest(value)


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path,
          'unaliased diagnostic owner source required')
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= 131072, 'bounded single-link owner source required')
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected,
          'diagnostic owner source bytes or physical identity changed')
    return dict(path=str(path), bytes=len(raw), sha256=expected), identity(after)


def _package_paths():
    """Resolve the existing package, never a caller-selected implementation."""
    package = importlib.import_module(_PACKAGE)
    paths = list(package.__path__)
    _need(len(paths) == 1 and type(paths[0]) is str,
          'one canonical numerical package directory required')
    directory = Path(paths[0]).absolute()
    _need(directory.resolve(strict=True) == directory
          and directory.parts[-4:] == ('ipfs_datasets_py', 'logic', 'formalization', 'autoencoder'),
          'canonical numerical package geometry differs')
    for name, expected in (('ipfs_datasets_py', directory.parents[2]),
                           ('ipfs_datasets_py.logic', directory.parents[1]),
                           ('ipfs_datasets_py.logic.formalization', directory.parent)):
        parent = sys.modules.get(name)
        _need(parent is not None and list(parent.__path__) == [str(expected)],
              'canonical numerical parent package differs')
    return package, directory


def _owners():
    package, directory = _package_paths()
    path = directory / (_LEGACY_NAME + '.py')
    observed = _source(path, _LEGACY_SHA)
    owner = importlib.import_module(_PACKAGE + '.' + _LEGACY_NAME)
    _need(type(owner.__file__) is str and Path(owner.__file__).absolute() == path
          and _source(path, _LEGACY_SHA) == observed,
          'genuine canonical warm-start source or loaded origin differs')
    return owner, package, directory, observed


@contextmanager
def _scope(original):
    own = _source(_SELF_PATH, _SELF_SHA)
    owner, package, directory, observed = _owners()
    failure = None

    def outer():
        _need(type(__file__) is str and Path(__file__).absolute() == _SELF_PATH
              and _source(_SELF_PATH, _SELF_SHA) == own,
              'diagnostic source or loaded origin changed')
        current_package, current_directory = _package_paths()
        _need(current_package is package and current_directory == directory
              and type(owner.__file__) is str
              and Path(owner.__file__).absolute() == directory / (_LEGACY_NAME + '.py')
              and _source(directory / (_LEGACY_NAME + '.py'), _LEGACY_SHA) == observed,
              'canonical warm-start source, package or loaded origin changed')

    try:
        outer()
        with owner._scope(original) as (data, modules, legacy_fence):
            def fence():
                legacy_fence()
                outer()
            fence()
            yield data, modules, owner, fence, [own[0], observed[0]]
            fence()
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, PredicateObjectiveError):
            failure = PredicateObjectiveError(str(error))
            raise failure from error
        raise
    finally:
        try:
            outer()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, 'A closing predicate-objective source check also failed.')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _close(left, right):
    return math.isclose(left, right, rel_tol=3e-6, abs_tol=2e-6)


def _legacy_observation(report, value, row, owner):
    _need(type(report) is dict and set(report) == _LEGACY_FIELDS,
          'complete genuine warm-start objective observation required')
    _need(report['schema'] == owner.OBSERVATION_SCHEMA
          and report['checkpoint_sha256'] == _digest(value)
          and report['objective_policy_sha256'] == value['objective_policy_sha256']
          and report['objective_kind'] == value['objective_policy']['objective_kind']
          and report['weighting'] == 'semantic_priority'
          and _plain_equal(report['authority'], owner.AUTHORITY),
          'legacy objective identity or authority differs')
    for key in ('warmstart_parent_checkpoint_sha256', 'historical_parent_progress',
                'basis_checkpoint_sha256'):
        _need(_plain_equal(report[key], value[key]), 'legacy checkpoint lineage differs: ' + key)
    for key in ('row_id', 'row_index', 'inventory_sha256', 'baseline_inventory_sha256',
                'scope_inventory_sha256', 'role_inventory_sha256', 'scope_policy_sha256',
                'target_ids', 'position_weights', 'position_roles', 'position_syntax_roles',
                'scope_allowed_token_ids', 'baseline_decision_kinds',
                'singleton_positions', 'nontrivial_positions'):
        expected = row['id'] if key == 'row_id' else row[key]
        _need(_plain_equal(report[key], expected), 'legacy objective row differs: ' + key)
    _need(_plain_equal(report['label_ids'], row['target_ids'][1:])
          and type(report['weight_sum']) is float and report['weight_sum'] == 67.0
          and type(report['supervised_positions']) is int and report['supervised_positions'] == 46,
          'legacy target/normalization geometry differs')
    conditional = report['objective_kind'] == 'scope_conditional'
    expected_flags = dict(parent_Adam_inherited=False, full537_logits_observed=True,
        full537_vocabulary=not conditional, conditional_allowed_set_loss=conditional,
        singleton_zero_loss_is_not_accuracy=True,
        full537_and_conditional_losses_not_comparable_as_accuracy=True,
        teacher_forcing=True, forward_performed=False, backward_performed=False,
        optimizer_update_performed=False, structural_role_priority_is_not_semantic_verification=True)
    _need(all(type(report[key]) is bool and report[key] is expected
              for key, expected in expected_flags.items()), 'legacy observation operation flags differ')
    _need(report['reduction'] == ('scope_masked_none_role_weighted_sum_divide67' if conditional
                                 else 'full537_none_role_weighted_sum_divide67'),
          'legacy objective reduction differs')
    for key in ('per_position_losses', 'full537_per_position_losses'):
        _need(type(report[key]) is list and len(report[key]) == 46
              and all(_number(loss) and loss >= 0 for loss in report[key]),
              'complete finite nonnegative position losses required')
    for key, losses in (('weighted_loss', report['per_position_losses']),
                        ('full537_weighted_loss', report['full537_per_position_losses'])):
        _need(_number(report[key]) and report[key] >= 0
              and _close(report[key], math.fsum(loss * weight for loss, weight
                         in zip(losses, row['position_weights'])) / 67),
              'legacy weighted loss observation differs')


def objective(checkpoint, logits, *, expected_checkpoint_sha256,
              expected_policy_sha256, expected_diagnostic_policy_sha256):
    """Return one differentiable diagnostic and separate non-authorizing report.

    ``expected_policy_sha256`` names the unchanged legacy objective, while the
    diagnostic pin names only this fixed counterfactual descriptor. No fitting,
    backward, state conversion, model construction or training admission occurs.
    """
    for pin, label in ((expected_checkpoint_sha256, 'legacy checkpoint'),
                       (expected_policy_sha256, 'legacy policy'),
                       (expected_diagnostic_policy_sha256, 'diagnostic policy')):
        _sha(pin, label)
    descriptor = policy()
    _need(policy_sha256(descriptor) == expected_diagnostic_policy_sha256,
          'independent fixed diagnostic policy pin differs')
    original = dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
                    expected_policy_sha256=expected_policy_sha256,
                    expected_diagnostic_policy_sha256=expected_diagnostic_policy_sha256)
    with _scope(original) as (data, modules, legacy, fence, sources):
        weighted = modules['weighted']
        _, torch, runtime = weighted._numeric(modules)
        _need(type(logits) is torch.Tensor and logits.device.type == 'cpu'
              and logits.dtype is torch.float32 and tuple(logits.shape) == (1, 46, 537)
              and logits.requires_grad and bool(torch.isfinite(logits).all()),
              'complete ordinary differentiable finite CPU float32 logits required')
        version, saved, rng = logits._version, logits.detach().clone(), torch.get_rng_state().clone()
        failure = None
        legacy_raw = None
        legacy_report = None

        def guarded():
            fence()
            _need(policy_sha256(descriptor) == data['expected_diagnostic_policy_sha256'],
                  'fixed diagnostic policy changed during observation')
            _need(logits._version == version and torch.equal(logits.detach(), saved)
                  and torch.equal(torch.get_rng_state(), rng)
                  and _wire(weighted._numeric(modules)[2]) == _wire(runtime),
                  'diagnostic changed logits, CPU RNG or numerical runtime')
            if legacy_raw is not None:
                _need(_wire(legacy_report) == legacy_raw,
                      'legacy objective observation changed during diagnostic')

        try:
            legacy_loss, legacy_report = legacy.objective(data['checkpoint'], logits,
                expected_checkpoint_sha256=data['expected_checkpoint_sha256'],
                expected_policy_sha256=data['expected_policy_sha256'])
            guarded()
            legacy_raw = _wire(legacy_report)
            observation = json.loads(legacy_raw)
            row = legacy._row(data['checkpoint'], modules)
            _legacy_observation(observation, data['checkpoint'], row, legacy)
            _need(isinstance(legacy_loss, torch.Tensor) and legacy_loss.device.type == 'cpu'
                  and legacy_loss.dtype is torch.float32 and legacy_loss.ndim == 0
                  and legacy_loss.requires_grad and bool(torch.isfinite(legacy_loss))
                  and _close(float(legacy_loss.detach()), observation['weighted_loss']),
                  'genuine differentiable legacy scalar differs from its observation')
            positions = row['role_positions']
            selected = [index for index, position in enumerate(positions)
                        if position['role'] == 'predicate_constructor']
            _need(len(positions) == 46 and len(selected) == 1,
                  'one actual predicate-constructor role required')
            index = selected[0]
            position = positions[index]
            old_weights = row['position_weights']
            _need(position['syntax_role'] == 'constructor'
                  and position['lexical_token'] == '"predicate"'
                  and type(position['target_position']) is int and position['target_position'] == index + 1
                  and position['target_token_id'] == row['target_ids'][index + 1]
                  and data['checkpoint']['codec']['vocabulary'][position['target_token_id']] == '"predicate"'
                  and _number(position['weight']) and position['weight'] == old_weights[index] == 1.0
                  and len(old_weights) == 46 and all(_number(weight) and weight > 0 for weight in old_weights)
                  and math.fsum(old_weights) == 67.0,
                  'actual predicate lexical role or complete old weights differ')
            new_weights = list(old_weights)
            new_weights[index] = 4.0
            _need(math.fsum(new_weights) == 70.0
                  and [i for i, pair in enumerate(zip(old_weights, new_weights)) if pair[0] != pair[1]] == [index],
                  'only the predicate weight may change, with exact sum70')
            allowed_ids = row['scope_allowed_token_ids'][index]
            target = row['target_ids'][index + 1]
            scores = logits[0, index].reshape(1, 537)
            labels = torch.tensor([target], dtype=torch.long, device='cpu')
            conditional = observation['objective_kind'] == 'scope_conditional'
            if conditional:
                allowed = torch.zeros_like(scores, dtype=torch.bool)
                allowed[0, allowed_ids] = True
                scores = scores.masked_fill(~allowed, -torch.inf)
            predicate_ce = torch.nn.functional.cross_entropy(scores, labels, reduction='none')[0]
            _need(predicate_ce.requires_grad and bool(torch.isfinite(predicate_ce))
                  and _close(float(predicate_ce.detach()), observation['per_position_losses'][index]),
                  'same-logit predicate CE differs from genuine legacy allowed-set loss')
            proposed_loss = (67 * legacy_loss + 3 * predicate_ce) / 70
            _need(proposed_loss.ndim == 0 and proposed_loss.requires_grad
                  and bool(torch.isfinite(proposed_loss)), 'finite differentiable counterfactual scalar required')
            old_scalar = float(legacy_loss.detach())
            predicate_scalar = float(predicate_ce.detach())
            new_scalar = float(proposed_loss.detach())
            full_old = observation['full537_weighted_loss']
            full_predicate = observation['full537_per_position_losses'][index]
            full_proposed = (67 * full_old + 3 * full_predicate) / 70
            _need(_close(new_scalar, (67 * old_scalar + 3 * predicate_scalar) / 70),
                  'counterfactual scalar observation differs from closed algebra')
            report = dict(schema=SCHEMA, profile=PROFILE, status='differentiable_diagnostic_only',
                diagnostic_policy=descriptor,
                diagnostic_policy_sha256=data['expected_diagnostic_policy_sha256'],
                legacy_checkpoint_sha256=data['expected_checkpoint_sha256'],
                legacy_policy_sha256=data['expected_policy_sha256'],
                legacy_objective_kind=observation['objective_kind'],
                legacy_report=observation, legacy_report_sha256=hashlib.sha256(legacy_raw).hexdigest(),
                row_id=row['id'], row_index=row['row_index'],
                predicate_position_index=index, predicate_target_position=index + 1,
                predicate_role=dict(position),
                predicate_allowed_token_ids=list(allowed_ids) if conditional else list(range(537)),
                predicate_scope_allowed_token_ids=list(allowed_ids),
                predicate_target_id=target, old_position_weights=list(old_weights),
                proposed_position_weights=new_weights, old_weight_sum=67.0, proposed_weight_sum=70.0,
                legacy_weighted_loss=old_scalar, proposed_weighted_loss=new_scalar,
                predicate_cross_entropy=predicate_scalar,
                legacy_full537_weighted_loss=full_old,
                proposed_full537_weighted_loss=full_proposed,
                predicate_full537_cross_entropy=full_predicate,
                legacy_conditional_weighted_loss=old_scalar if conditional else None,
                proposed_conditional_weighted_loss=new_scalar if conditional else None,
                predicate_conditional_cross_entropy=predicate_scalar if conditional else None,
                scalar_formula=descriptor['scalar_formula'], legacy_objective_calls=1,
                differentiable_scalar_returned=True, teacher_forcing=True,
                model_constructed=False, optimizer_constructed=False, restore_performed=False,
                forward_performed=False, backward_performed=False, optimizer_update_performed=False,
                checkpoint_created=False, checkpoint_packed=False,
                new_training_profile_status='UNIMPLEMENTED', new_checkpoint_profile_status='UNIMPLEMENTED',
                checkpoint_compatible=False, producer_pins=sources,
                producer_pin_scope='direct diagnostic and legacy source; transitive legacy owners fenced by unchanged legacy scope',
                authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                limitations=[
                    'One exposed authored legacy row and its target prefix; not a source-only or held-out task.',
                    'Changing the denominator also scales every unchanged position coefficient by67/70.',
                    'The unchanged legacy checkpoint remains its original profile; this diagnostic is not packable training state.',
                    'The new scalar supplies no update/resume, autonomous-serving, convergence, statutory, graph or Lean qualification.',
                ])
            raw = _wire(report)
            guarded()
            return proposed_loss, json.loads(raw)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                guarded()
            except BaseException:
                if failure is None:
                    raise
                BaseException.add_note(failure, 'A closing predicate-objective input/RNG check also failed.')


__all__ = ['PredicateObjectiveError', 'policy', 'policy_sha256', 'objective']

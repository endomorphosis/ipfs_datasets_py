"""Streamed structural feature space. This file is not part of the v1 hash.

``autoencoder_projection_features.py`` remains the registered v1 contract.
Editing it would change ``_implementation_sha()`` and make the pilot candidate
fail its contract check. v2 raises the source cap, steps Adam once per
minibatch, and checkpoints those moments. The column cap stays ``MAX_FEATURES``.
The loss is the same native projection kernel. It does not load text embeddings
and it does not run the legal sample worker.
"""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

from .autoencoder_projection_features import (
    FALSE,
    MAX_FEATURES,
    OBJECTIVE,
    ProjectionFeatureError,
    _matrix,
    _plain,
    _raw,
    _require,
    _target,
    digest,
)


SPACE_SCHEMA = 'native-projection-feature-space/v2'
STATE_SCHEMA = 'native-projection-feature-state/v2'
CHECKPOINT_SCHEMA = 'native-projection-feature-checkpoint/v2'
BACKEND = 'native-projection-feature-autoencoder/v2'
TARGET_DIGEST_METHOD = 'sha256_canonical_target_lines'
MAX_SOURCES = 32768
MAX_MINIBATCH = 1024
MAX_SECONDS = 14400.0
_DESCRIPTOR_KEYS = ('logic_family', 'profile', 'properties', 'view_role', 'representation_kind', 'producer_id')
_SPACE_KEYS = {
    'schema', 'domain_id', 'projection_ids', 'projections', 'columns', 'training_sources',
    'excluded_projection_ids', 'training_targets_sha256', 'training_targets_sha256_method',
    'normalization', 'source_bound', 'minibatch_bound', *FALSE,
}
_STATE_KEYS = {
    'schema', 'feature_space_sha256', 'latent_width', 'parameters', 'adam', 'completed_epochs',
    'completed_steps', 'minibatch_size', 'optimizer_config', 'tuning_targets_sha256', *FALSE,
}


def update_target_digest(hasher, target) -> None:
    """Fold one canonical target into a streaming, order-dependent digest."""

    hasher.update(_raw(_target(target)))
    hasher.update(b'\n')


def _sha256_text(value) -> bool:
    return type(value) is str and len(value) == 64 and all(character in '0123456789abcdef' for character in value)


def _validate_space(space) -> None:
    _require(type(space) is dict and set(space) == _SPACE_KEYS, 'closed v2 feature space schema required')
    _require(space.get('schema') == SPACE_SCHEMA, 'unsupported feature space')
    _require(type(space.get('domain_id')) is str and space['domain_id'], 'feature space domain required')
    ids = space.get('projection_ids')
    _require(type(ids) is list and ids and ids == sorted(set(ids)), 'explicit sorted projection IDs required')
    projections = space.get('projections')
    _require(type(projections) is dict and set(projections) == set(ids), 'projection descriptor coverage mismatch')
    for descriptor in projections.values():
        _require(type(descriptor) is dict and set(descriptor) == set(_DESCRIPTOR_KEYS),
                 'closed projection descriptor required')
        _require(type(descriptor['logic_family']) is str and descriptor['logic_family'],
                 'projection roles cannot stand in for logic families')
    columns = space.get('columns')
    _require(type(columns) is list and 1 <= len(columns) <= MAX_FEATURES and columns == sorted(columns),
             'projection vocabulary exceeds feature bound')
    _require(all(type(row) is list and len(row) == 2 and row[0] in ids and type(row[1]) is str for row in columns)
             and len({tuple(row) for row in columns}) == len(columns),
             'feature space columns must be canonical, unique and grouped by projection')
    sources = space.get('training_sources')
    _require(type(sources) is list and sources == sorted(set(sources)) and 1 <= len(sources) <= MAX_SOURCES
             and all(type(value) is str and value for value in sources),
             'v2 training sources must be sorted, unique, and within the source bound')
    excluded = space.get('excluded_projection_ids')
    _require(type(excluded) is list and excluded == sorted(set(excluded)) and set(excluded).isdisjoint(ids)
             and all(type(value) is str for value in excluded), 'invalid excluded projections')
    _require(space.get('training_targets_sha256_method') == TARGET_DIGEST_METHOD
             and _sha256_text(space.get('training_targets_sha256')),
             'invalid v2 target digest')
    _require(space.get('normalization') == 'log1p_then_l2_per_projection', 'invalid feature normalization')
    _require(space.get('source_bound') == MAX_SOURCES and space.get('minibatch_bound') == MAX_MINIBATCH,
             'feature space bounds differ from this backend')
    _require(all(space.get(key) is False for key in FALSE), 'feature space cannot claim qualification')


def build_streamed_feature_space(*, domain, projection_ids, projections, columns, training_sources,
                                  excluded_projection_ids, training_targets_sha256):
    """Seal a vocabulary that was accumulated outside the 1,024-source call."""

    space = {
        'schema': SPACE_SCHEMA,
        'domain_id': domain,
        'projection_ids': list(projection_ids),
        'projections': {name: dict(value) for name, value in dict(projections).items()},
        'columns': [list(row) for row in columns],
        'training_sources': list(training_sources),
        'excluded_projection_ids': list(excluded_projection_ids),
        'training_targets_sha256': training_targets_sha256,
        'training_targets_sha256_method': TARGET_DIGEST_METHOD,
        'normalization': 'log1p_then_l2_per_projection',
        'source_bound': MAX_SOURCES,
        'minibatch_bound': MAX_MINIBATCH,
        **FALSE,
    }
    sealed = _plain(space)
    _validate_space(sealed)
    return sealed


def _array(values, shape, nonnegative=False) -> None:
    _require(type(values) is list and len(values) == shape[0], 'invalid numerical tensor shape')
    for value in values:
        if len(shape) > 1:
            _array(value, shape[1:], nonnegative)
        else:
            _require(type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)
                     and (not nonnegative or value >= 0), 'invalid numerical tensor value')


def _optimizer_config(learning_rate):
    return {'name': 'Adam', 'learning_rate': float(learning_rate), 'betas': [0.9, 0.999], 'eps': 1e-8}


def _read_adam_step(value) -> int:
    if hasattr(value, 'item'):
        value = value.item()
    if type(value) is float and value == int(value):
        value = int(value)
    _require(type(value) is int and not isinstance(value, bool) and value >= 0, 'invalid Adam step')
    return value


def _validate_state(space, state) -> None:
    _validate_space(space)
    _require(type(state) is dict and set(state) == _STATE_KEYS, 'closed v2 numerical state schema required')
    latent = state.get('latent_width')
    _require(type(latent) is int and not isinstance(latent, bool) and 1 <= latent <= 64, 'invalid latent width')
    _require(state.get('schema') == STATE_SCHEMA and state.get('feature_space_sha256') == digest(space)
             and all(state.get(key) is False for key in FALSE), 'numerical state identity or authority mismatch')
    _require(type(state.get('completed_epochs')) is int and not isinstance(state['completed_epochs'], bool)
             and state['completed_epochs'] >= 0, 'invalid parent epoch count')
    _require(type(state.get('completed_steps')) is int and not isinstance(state['completed_steps'], bool)
             and state['completed_steps'] >= 0, 'invalid Adam step count')
    _require(type(state.get('minibatch_size')) is int and not isinstance(state['minibatch_size'], bool)
             and 1 <= state['minibatch_size'] <= MAX_MINIBATCH, 'invalid minibatch size')
    _require(_sha256_text(state.get('tuning_targets_sha256')), 'invalid immutable tuning identity')
    config = state.get('optimizer_config')
    _require(type(config) is dict and set(config) == {'name', 'learning_rate', 'betas', 'eps'}
             and config['name'] == 'Adam' and config['betas'] == [0.9, 0.999] and config['eps'] == 1e-8
             and type(config['learning_rate']) in (int, float) and not isinstance(config['learning_rate'], bool)
             and math.isfinite(float(config['learning_rate'])) and 0 < float(config['learning_rate']) <= 0.1,
             'invalid saved optimizer settings')
    width = len(space['columns'])
    shapes = ((width, latent), (latent,), (latent, width), (width,))
    _require(type(state.get('parameters')) is list and type(state.get('adam')) is list
             and len(state['parameters']) == len(state['adam']) == 4, 'incomplete numerical parent state')
    for values, moment, shape in zip(state['parameters'], state['adam'], shapes):
        _array(values, shape)
        _require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'}, 'invalid Adam moment')
        # v1 stores one full-batch step per epoch. v2 steps once per minibatch.
        _require(_read_adam_step(moment['step']) == state['completed_steps'], 'Adam step does not match completed steps')
        _array(moment['exp_avg'], shape)
        _array(moment['exp_avg_sq'], shape, True)


def _check_scalars(*, epochs, latent_width, learning_rate, max_seconds, seed, minibatch_size) -> None:
    _require(type(epochs) is int and not isinstance(epochs, bool) and 1 <= epochs <= 32
             and type(latent_width) is int and not isinstance(latent_width, bool) and 1 <= latent_width <= 64,
             'bounded epoch and latent budgets required')
    _require(type(learning_rate) in (int, float) and not isinstance(learning_rate, bool)
             and math.isfinite(learning_rate) and 0 < learning_rate <= 0.1,
             'learning rate must be finite within (0, .1]')
    _require(type(max_seconds) in (int, float) and not isinstance(max_seconds, bool)
             and math.isfinite(max_seconds) and 0 < max_seconds <= MAX_SECONDS,
             'v2 training deadline exceeds its bound')
    _require(type(seed) is int and not isinstance(seed, bool) and 0 <= seed < 2**31, 'invalid local seed')
    _require(type(minibatch_size) is int and not isinstance(minibatch_size, bool)
             and 1 <= minibatch_size <= MAX_MINIBATCH, 'invalid minibatch size')


def _as_matrix(values, width, row_count):
    import numpy as np
    array = np.asarray(values, dtype=np.float64)
    _require(array.shape == (row_count, width) and bool(np.isfinite(array).all()), 'invalid feature matrix')
    return array


def _identities(ids, rows, space_sources, other_ids, label) -> None:
    _require(type(ids) is list and len(ids) == rows and len(ids) == len(set(ids))
             and all(type(value) is str and value for value in ids), f'invalid {label} source ids')
    if label == 'training':
        _require(set(ids) == set(space_sources), 'training matrix sources differ from the feature space')
    else:
        _require(1 <= len(ids) <= MAX_MINIBATCH and set(ids).isdisjoint(space_sources)
                 and set(ids).isdisjoint(other_ids), 'training/tuning source leakage')


def _spans(space):
    spans = {}
    for name in space['projection_ids']:
        positions = [index for index, (projection, _) in enumerate(space['columns']) if projection == name]
        _require(positions and positions == list(range(positions[0], positions[-1] + 1)),
                 'projection columns are not contiguous')
        spans[name] = (positions[0], positions[-1] + 1)
    return spans


def _assemble_report(*, space, started, epochs, latent_width, learning_rate, max_seconds, seed, minibatch_size,
                     parent_state_sha, before, best_loss, best_metrics, best_state, reports, stopped,
                     training_rows, tuning_rows):
    return {
        'schema': 'native-projection-feature-training/v2',
        'backend': BACKEND,
        'feature_space_sha256': digest(space),
        'base_state_sha256': parent_state_sha,
        'embedding_model_id': 'native-projection-features',
        'embedding_revision': 'v2',
        'configuration': {
            'epochs': epochs,
            'latent_width': latent_width,
            'learning_rate': float(learning_rate),
            'max_seconds': float(max_seconds),
            'seed': seed,
            'minibatch_size': minibatch_size,
            'objective': OBJECTIVE,
        },
        'deadline_enforcement': 'cooperative_checks_between_minibatches',
        'attempted_epochs': len(reports),
        'selected_total_epochs': best_state['completed_epochs'],
        'selected_completed_steps': best_state['completed_steps'],
        'training_target_count': training_rows,
        'tuning_target_count': tuning_rows,
        'before': before,
        'after': {'objective': best_loss, 'projections': best_metrics},
        'epochs': reports,
        'improved': best_loss < before['objective'],
        'stopped_reason': stopped,
        'elapsed_seconds': time.monotonic() - started,
        'heldout_canary': False,
        'representation': 'native_compiler_structural_features_not_semantic_text_embeddings',
        'weights_downloaded': False,
        'lake_executed': False,
        **FALSE,
    }


def train_streamed_projection_features(space, training_matrix, training_ids, tuning_matrix, tuning_ids, *,
                                       minibatch_size, tuning_targets_sha256, epochs=8, latent_width=16,
                                       learning_rate=0.02, max_seconds=3600.0, seed=1729, base_state=None,
                                       best_state=None, best_objective=None, best_metrics=None, before=None,
                                       epoch_reports=None, checkpoint_callback=None):
    """Adam once per minibatch. One epoch is one pass. The best epoch is the saved state.

    Selection matches v1: the tuning objective must fall, and no projection's
    reconstruction or cosine may rise. A partial epoch that hits the deadline
    is not selected and is not checkpointed.
    """

    started = time.monotonic()
    space = _plain(space)
    _validate_space(space)
    _check_scalars(epochs=epochs, latent_width=latent_width, learning_rate=learning_rate,
                   max_seconds=max_seconds, seed=seed, minibatch_size=minibatch_size)
    _require(_sha256_text(tuning_targets_sha256), 'invalid immutable tuning identity')
    training_ids = list(training_ids)
    tuning_ids = list(tuning_ids)
    training = _as_matrix(training_matrix, len(space['columns']), len(training_ids))
    tuning = _as_matrix(tuning_matrix, len(space['columns']), len(tuning_ids))
    _identities(training_ids, training.shape[0], space['training_sources'], [], 'training')
    _identities(tuning_ids, tuning.shape[0], space['training_sources'], training_ids, 'tuning')
    batch_count = (training.shape[0] + minibatch_size - 1) // minibatch_size
    _require(batch_count >= 1, 'empty training matrix')
    reports = list(epoch_reports or [])
    parent_state_sha = None
    if base_state is not None:
        base_state = _plain(base_state)
        parent_state_sha = digest(base_state)
        _validate_state(space, base_state)
        _require(base_state['tuning_targets_sha256'] == tuning_targets_sha256,
                 'resumed feature selection requires the same tuning targets')
        _require(base_state['latent_width'] == latent_width and base_state['minibatch_size'] == minibatch_size
                 and base_state['optimizer_config'] == _optimizer_config(learning_rate),
                 'resume requires identical optimizer settings')
        _require(base_state['completed_steps'] == base_state['completed_epochs'] * batch_count,
                 'resumed Adam steps do not match the minibatch count')
        _require(best_state is not None and before is not None and best_metrics is not None
                 and type(best_objective) in (int, float) and not isinstance(best_objective, bool)
                 and math.isfinite(best_objective),
                 'resumed training requires the original tuning baseline')
        best_state = _plain(best_state)
        _validate_state(space, best_state)
        _require(best_state['completed_epochs'] <= base_state['completed_epochs'],
                 'selected epoch is ahead of the latest epoch')
        if base_state['completed_epochs'] >= epochs:
            report = _assemble_report(
                space=space, started=started, epochs=epochs, latent_width=latent_width,
                learning_rate=learning_rate, max_seconds=max_seconds, seed=seed, minibatch_size=minibatch_size,
                parent_state_sha=parent_state_sha, before=before, best_loss=float(best_objective),
                best_metrics=best_metrics, best_state=best_state, reports=reports, stopped='epoch_budget',
                training_rows=int(training.shape[0]), tuning_rows=int(tuning.shape[0]),
            )
            return {'state': best_state, 'latest_state': base_state, 'report': report}

    import torch
    from . import modal_autoencoder_cuda as kernel
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    width = len(space['columns'])
    shapes = ((width, latent_width), (latent_width,), (latent_width, width), (width,))
    generator = torch.Generator(device='cpu').manual_seed(seed)
    parameters = [(torch.randn(shape, generator=generator, dtype=torch.float64) * 0.1).requires_grad_()
                  if len(shape) == 2 else torch.zeros(shape, dtype=torch.float64, requires_grad=True)
                  for shape in shapes]
    optimizer = torch.optim.Adam(parameters, lr=float(learning_rate))
    completed_epochs = 0
    completed_steps = 0
    if base_state is not None:
        for parameter, values, moment in zip(parameters, base_state['parameters'], base_state['adam']):
            value = torch.tensor(values, dtype=torch.float64)
            avg = torch.tensor(moment['exp_avg'], dtype=torch.float64)
            sq = torch.tensor(moment['exp_avg_sq'], dtype=torch.float64)
            _require(tuple(value.shape) == tuple(parameter.shape) == tuple(avg.shape) == tuple(sq.shape)
                     and all(bool(torch.isfinite(item).all()) for item in (value, avg, sq))
                     and bool((sq >= 0).all()),
                     'parent tensors have invalid shape or values')
            step = _read_adam_step(moment['step'])
            with torch.no_grad():
                parameter.copy_(value)
            optimizer.state[parameter] = {
                'step': torch.tensor(float(step)),
                'exp_avg': avg,
                'exp_avg_sq': sq,
            }
        completed_epochs = base_state['completed_epochs']
        completed_steps = base_state['completed_steps']
    spans = _spans(space)
    cosine_weight = float(OBJECTIVE['cosine_weight'])
    l2_regularization = float(OBJECTIVE['l2'])

    def forward(inputs):
        return torch.tanh(inputs @ parameters[0] + parameters[1]) @ parameters[2] + parameters[3]

    def loss(inputs):
        decoded = forward(inputs)
        empty = torch.zeros((inputs.shape[0], 0), dtype=torch.float64)
        session = SimpleNamespace(
            blocks={}, parameters=parameters, parameter_count=sum(item.numel() for item in parameters),
        )
        total = 0
        metrics = {}
        for name, (start, stop) in spans.items():
            projection_state = SimpleNamespace(
                torch=torch, device=torch.device('cpu'), embeddings=inputs[:, start:stop],
            )
            _require(bool((torch.linalg.vector_norm(decoded[:, start:stop], dim=1) > 1e-8).all()),
                     'zero-norm projection reconstruction cannot count as perfect cosine')
            value, components, _unused = kernel._loss_chunk(
                projection_state, session, (decoded[:, start:stop], empty, empty), {'decoded_embedding'},
                0, int(inputs.shape[0]), int(inputs.shape[0]), cosine_weight, l2_regularization, False,
            )
            total = total + value / len(spans)
            metrics[name] = {
                key: float(components[key].detach())
                for key in ('reconstruction', 'cosine', 'guarded_auxiliary')
            }
        return total, metrics

    def state_dict():
        moments = []
        for parameter in parameters:
            item = optimizer.state.get(parameter, {})
            moments.append({
                'step': _read_adam_step(item.get('step', 0)),
                'exp_avg': item.get('exp_avg', torch.zeros_like(parameter)).detach().tolist(),
                'exp_avg_sq': item.get('exp_avg_sq', torch.zeros_like(parameter)).detach().tolist(),
            })
        return {
            'schema': STATE_SCHEMA,
            'feature_space_sha256': digest(space),
            'latent_width': latent_width,
            'parameters': [parameter.detach().tolist() for parameter in parameters],
            'adam': moments,
            'completed_epochs': completed_epochs,
            'completed_steps': completed_steps,
            'minibatch_size': minibatch_size,
            'tuning_targets_sha256': tuning_targets_sha256,
            'optimizer_config': _optimizer_config(learning_rate),
            **FALSE,
        }

    def publish(reason, finished, latest_state, selected_state, selected_loss, selected_metrics, baseline):
        if checkpoint_callback is None:
            return
        report = _assemble_report(
            space=space, started=started, epochs=epochs, latent_width=latent_width,
            learning_rate=learning_rate, max_seconds=max_seconds, seed=seed, minibatch_size=minibatch_size,
            parent_state_sha=parent_state_sha, before=baseline, best_loss=selected_loss,
            best_metrics=selected_metrics, best_state=selected_state, reports=list(reports),
            stopped=reason, training_rows=int(training.shape[0]), tuning_rows=int(tuning.shape[0]),
        )
        checkpoint_callback({
            'schema': CHECKPOINT_SCHEMA,
            'feature_space_sha256': digest(space),
            'configuration': {
                'epochs': epochs,
                'latent_width': latent_width,
                'learning_rate': float(learning_rate),
                'max_seconds': float(max_seconds),
                'seed': seed,
                'minibatch_size': minibatch_size,
            },
            'latest_state': latest_state,
            'best_state': selected_state,
            'best_objective': selected_loss,
            'best_metrics': selected_metrics,
            'before': baseline,
            'epoch_reports': list(reports),
            'stopped_reason': reason,
            'completed': finished,
            'report': report,
        })

    tuning_tensor = torch.tensor(tuning, dtype=torch.float64)
    if before is None:
        with torch.no_grad():
            initial, initial_metrics = loss(tuning_tensor)
        _require(bool(torch.isfinite(initial)), 'nonfinite tuning objective')
        before_payload = {'objective': float(initial), 'projections': initial_metrics}
        best_loss = float(initial)
        best_metrics_live = initial_metrics
        best = state_dict()
    else:
        before_payload = before
        best_loss = float(best_objective)
        best_metrics_live = best_metrics
        best = best_state
    latest = state_dict()
    stopped = 'epoch_budget'
    for _epoch in range(completed_epochs, epochs):
        if time.monotonic() - started >= max_seconds:
            stopped = 'deadline'
            break
        steps_before = completed_steps
        weighted = 0.0
        seen_rows = 0
        gradient_norm = 0.0
        aborted = False
        taken = 0
        for start in range(0, training.shape[0], minibatch_size):
            if time.monotonic() - started >= max_seconds:
                aborted = True
                break
            batch = torch.tensor(training[start:start + minibatch_size], dtype=torch.float64)
            optimizer.zero_grad()
            objective, _batch_metrics = loss(batch)
            _require(bool(torch.isfinite(objective)), 'nonfinite training objective')
            objective.backward()
            gradient_norm = kernel._gradient_norm(torch, parameters)
            _require(math.isfinite(gradient_norm), 'nonfinite gradient')
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            if time.monotonic() - started >= max_seconds:
                aborted = True
                break
            optimizer.step()
            taken += 1
            weighted += float(objective.detach()) * int(batch.shape[0])
            seen_rows += int(batch.shape[0])
        if aborted or taken != batch_count:
            stopped = 'deadline'
            break
        completed_epochs += 1
        completed_steps = _read_adam_step(optimizer.state[parameters[0]]['step'])
        _require(all(
            _read_adam_step(optimizer.state[parameter]['step']) == completed_steps for parameter in parameters
        ), 'Adam moments disagree on the step')
        _require(completed_steps == steps_before + taken, 'Adam step did not advance once per minibatch')
        with torch.no_grad():
            candidate, metrics = loss(tuning_tensor)
        _require(bool(torch.isfinite(candidate)), 'nonfinite tuning objective')
        expired = time.monotonic() - started >= max_seconds
        selected = (not expired and float(candidate) < best_loss and all(
            metrics[name][key] <= best_metrics_live[name][key] + 1e-9
            for name in spans for key in ('reconstruction', 'cosine')))
        latest = state_dict()
        if selected:
            best_loss = float(candidate)
            best_metrics_live = metrics
            best = latest
        reports.append({
            'epoch': completed_epochs,
            'train_objective': weighted / seen_rows,
            'tuning_objective': float(candidate),
            'gradient_norm': gradient_norm,
            'minibatch_count': taken,
            'selected': selected,
            'deadline_exceeded': expired,
            'projection_metrics': metrics,
        })
        finished = completed_epochs >= epochs and not expired
        publish('epoch_budget' if finished else 'running', finished, latest, best, best_loss, best_metrics_live, before_payload)
        if expired:
            stopped = 'deadline'
            break
    finished = stopped == 'epoch_budget' and completed_epochs >= epochs
    publish(stopped, finished, latest, best, best_loss, best_metrics_live, before_payload)
    report = _assemble_report(
        space=space, started=started, epochs=epochs, latent_width=latent_width,
        learning_rate=learning_rate, max_seconds=max_seconds, seed=seed, minibatch_size=minibatch_size,
        parent_state_sha=parent_state_sha, before=before_payload, best_loss=best_loss,
        best_metrics=best_metrics_live, best_state=best, reports=reports, stopped=stopped,
        training_rows=int(training.shape[0]), tuning_rows=int(tuning.shape[0]),
    )
    return {'state': best, 'latest_state': latest, 'report': report}


def infer_streamed_projection_features(space, state, targets):
    """Read a selected v2 state. Scores are not formulas and training does not run."""

    space, state = _plain(space), _plain(state)
    _validate_state(space, state)
    values, sources, coverage = _matrix(space, targets)
    import torch
    torch.set_num_threads(1)
    with torch.no_grad():
        encoder, bias, decoder, output_bias = [
            torch.tensor(value, dtype=torch.float64) for value in state['parameters']
        ]
        latent = torch.tanh(torch.tensor(values, dtype=torch.float64) @ encoder + bias)
        decoded = latent @ decoder + output_bias
        _require(bool(torch.isfinite(latent).all()) and bool(torch.isfinite(decoded).all()),
                 'nonfinite inference output')
        rows = [
            {'source_digest': source, 'latent': latent[index].tolist()}
            for index, source in enumerate(sources)
        ]
    return {
        'schema': 'native-projection-feature-inference/v2',
        'state_sha256': digest(state),
        'feature_space_sha256': digest(space),
        'rows': rows,
        'coverage': coverage,
        'training_executed': False,
        'decoded_formulas_generated': False,
        'representation': 'native_compiler_structural_features_not_semantic_text_embeddings',
        **FALSE,
    }

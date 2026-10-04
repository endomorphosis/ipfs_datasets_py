"""Bounded structural IR feature learning without the legal sample frontend.

Each projection has its own feature namespace and reported loss. This backend
reuses the modal numerical reconstruction kernel on CPU, not its legal target
or checkpoint codecs. Learned vectors describe native compiler artifacts; they
are neither semantic text embeddings nor executable/proved formulas.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace

BACKEND = 'native-projection-feature-autoencoder/v1'
SPACE_SCHEMA = 'native-projection-feature-space/v1'
STATE_SCHEMA = 'native-projection-feature-state/v1'
OBJECTIVE = {'reconstruction': 'per_projection_native_kernel_mean', 'cosine_weight': 0.1,
             'guarded_auxiliary': 'native_norm_ratio_penalty',
             'coverage': 'training_vocabulary_atoms_only', 'l2': 0.0, 'qualification': False}
FALSE = {'qualified': False, 'admitted': False, 'formalized': False, 'promotion_performed': False}
MAX_FEATURES = 4096


class ProjectionFeatureError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ProjectionFeatureError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _plain(value):
    if hasattr(value, 'to_dict'):
        value = value.to_dict()
    return json.loads(_raw(value))


def _target(value):
    from ...logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
    value = DomainTargetEnvelope.from_dict(_plain(value)).to_dict()
    _require(value.get('ready_for_training') is True, 'native target is not ready for feature training')
    _require(all(value.get(key) is False for key in ('qualified', 'admitted', 'formalized')),
             'feature targets cannot grant qualification')
    _require(type(value.get('source_digest')) is str and len(value['source_digest'].removeprefix('sha256:')) == 64,
             'target requires an exact source digest')
    _require(type(value.get('projections')) is list and value['projections'], 'nonempty native projections required')
    _require(len(_raw(value)) <= 4 * 1024 * 1024, 'native target exceeds byte bound')
    return value


def _tokens(value, path=(), depth=0):
    _require(depth <= 32, 'projection tree exceeds depth bound')
    if type(value) is dict:
        for key, child in sorted(value.items()):
            yield from _tokens(child, path + (key,), depth + 1)
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from _tokens(child, path + (index,), depth + 1)
    else:
        # Canonical paths/atoms preserve operators, argument positions and
        # modalities. No hashed buckets and no catch-all logic family.
        yield _raw([path, value]).decode()


def _rows(targets, domain, projection_ids):
    _require(type(targets) in (list, tuple) and 1 <= len(targets) <= 1024, 'bounded nonempty target batch required')
    rows, identities, descriptors = [], [], {}
    for raw in targets:
        target = _target(raw)
        _require(target['domain_id'] == domain, 'target belongs to another modality')
        _require(target['source_digest'] not in identities, 'duplicate source in feature batch')
        identities.append(target['source_digest'])
        grouped = {name: Counter() for name in projection_ids}
        for projection in target['projections']:
            name = projection['projection_id']
            if name not in grouped:
                continue
            descriptor = {key: projection.get(key) for key in
                          ('logic_family', 'profile', 'properties', 'view_role', 'representation_kind', 'producer_id')}
            _require(descriptor['logic_family'] is not None, 'projection roles cannot stand in for logic families')
            _require(name not in descriptors or descriptors[name] == descriptor, 'projection semantics changed between rows')
            descriptors[name] = descriptor
            grouped[name].update(_tokens(projection['expression']))
        _require(all(grouped.values()), 'required projection absent or empty in a source row')
        rows.append(grouped)
    return rows, identities, descriptors


def build_feature_space(domain, projection_ids, training_targets):
    """Fit a vocabulary on training sources only; bind each projection separately."""
    _require(type(projection_ids) in (list, tuple) and projection_ids and
             len(set(projection_ids)) == len(projection_ids), 'explicit unique projection IDs required')
    ids = sorted(projection_ids)
    rows, sources, descriptors = _rows(training_targets, domain, ids)
    columns = [[name, token] for name in ids for token in sorted(set().union(*(row[name] for row in rows)))]
    _require(1 <= len(columns) <= MAX_FEATURES, 'projection vocabulary exceeds feature bound')
    return {'schema': SPACE_SCHEMA, 'domain_id': domain, 'projection_ids': ids,
            'projections': descriptors, 'columns': columns, 'training_sources': sorted(sources),
            'excluded_projection_ids': sorted({p['projection_id'] for target in training_targets
                for p in _target(target)['projections']} - set(ids)),
            'training_targets_sha256': digest([_target(row) for row in training_targets]),
            'normalization': 'log1p_then_l2_per_projection', **FALSE}


def _matrix(space, targets):
    rows, sources, descriptors = _rows(targets, space['domain_id'], space['projection_ids'])
    _require(descriptors == space['projections'], 'target projections differ from fitted feature space')
    vocabulary = {name: {token for projection, token in space['columns'] if projection == name}
                  for name in space['projection_ids']}
    values, coverage = [], []
    for row in rows:
        vector = []
        for name in space['projection_ids']:
            observed = row[name]
            known = vocabulary[name]
            coverage.append({'projection_id': name, 'known_atoms': sum(v for k, v in observed.items() if k in known),
                             'unknown_atoms': sum(v for k, v in observed.items() if k not in known)})
            block = [math.log1p(observed[token]) for projection, token in space['columns'] if projection == name]
            norm = math.sqrt(sum(value * value for value in block))
            _require(norm > 0, 'projection has no coverage in the training feature space')
            vector.extend(value / norm for value in block)
        values.append(vector)
    return values, sources, coverage


def _native_projection_spec(name, descriptor):
    """The exact declaration this structural backend knows how to consume."""
    from .autoencoder_modality_contracts import ProjectionSpec
    return ProjectionSpec(name, descriptor['logic_family'], descriptor['representation_kind'],
        native_profile_id=descriptor['profile'], native_view_role=descriptor['view_role'],
        property_ids=tuple(descriptor['properties'] or ()),
        composition_id={'tdfol': 'tdfol_composition_v1', 'dcec': 'dcec_composition_v1'}.get(descriptor['logic_family']))


def _contract(contract, space):
    from .autoencoder_modality_contracts import ModalityContract, ValidatorRequirement
    from ...logic.formalization.autoencoder import domain_targets
    _require(set(space) == {'schema', 'domain_id', 'projection_ids', 'projections', 'columns', 'training_sources',
             'excluded_projection_ids', 'training_targets_sha256', 'normalization', *FALSE}, 'closed feature space schema required')
    _require(space.get('schema') == SPACE_SCHEMA and
             type(space.get('projection_ids')) is list and space['projection_ids'] == sorted(set(space['projection_ids'])) and
             set(space.get('projections', {})) == set(space['projection_ids']) and
             type(space.get('columns')) is list and 1 <= len(space['columns']) <= MAX_FEATURES,
             'invalid feature space schema')
    _require(all(type(row) is list and len(row) == 2 and row[0] in space['projection_ids'] and type(row[1]) is str
                 for row in space['columns']) and
             space['columns'] == sorted(space['columns']) and len({tuple(row) for row in space['columns']}) == len(space['columns']),
             'feature space columns must be canonical, unique and grouped by projection')
    _require(all(space.get(key) is False for key in FALSE), 'feature space cannot claim qualification')
    _require(space['normalization'] == 'log1p_then_l2_per_projection' and
             type(space['training_sources']) is list and 1 <= len(space['training_sources']) <= 1024 and
             all(type(value) is str for value in space['training_sources']) and
             space['training_sources'] == sorted(set(space['training_sources'])) and
             type(space['training_targets_sha256']) is str and re.fullmatch('[0-9a-f]{64}', space['training_targets_sha256']),
             'invalid feature basis provenance or normalization')
    _require(isinstance(contract, ModalityContract), 'validated modality contract required')
    _require(contract.domain == space['domain_id'], 'contract domain differs from target domain')
    _require(contract.embedding.model_id == 'native-projection-features' and contract.embedding.revision == 'v1',
             'this backend requires declared native structural features, not text embeddings')
    _require(contract.embedding.dimension == len(space['columns']) and
             contract.embedding.provenance_sha256.removeprefix('sha256:') == digest(space), 'feature basis identity mismatch')
    _require(contract.optimizer.identifier == BACKEND and contract.state_codec.identifier == STATE_SCHEMA,
             'incompatible optimizer or numerical state codec')
    _require(contract.optimizer.sha256 == _implementation_sha() and contract.state_codec.sha256 == _implementation_sha(),
             'installed numerical implementation differs from contract')
    _require(contract.objective_sha256.removeprefix('sha256:') == digest(OBJECTIVE), 'objective policy differs from backend')
    _require(contract.input_schema == SPACE_SCHEMA and contract.objective_id == 'native-projection-reconstruction/v1',
             'input or objective identity differs from backend')
    _require(contract.target_codec.identifier == 'native-domain-target-envelope' and contract.target_codec.version == '1'
             and contract.target_codec.sha256 == hashlib.sha256(Path(domain_targets.__file__).read_bytes()).hexdigest(),
             'target codec implementation differs from contract')
    expected_validator = ValidatorRequirement('native-target-structure', 'advisory', 'declaration',
                                              projection_ids=tuple(space['projection_ids']))
    _require(contract.validators == (expected_validator,), 'required validator policy is not implemented by this feature backend')
    projections = {row.projection_id: row for row in contract.projections}
    _require(set(projections) == set(space['projection_ids']), 'contract projection coverage mismatch')
    for name, descriptor in space['projections'].items():
        _require(projections[name].family_id == descriptor['logic_family'], 'logic family mismatch')
        _require(projections[name].native_profile_id == descriptor['profile'] and
                 projections[name].native_view_role == descriptor['view_role'] and
                 list(projections[name].property_ids) == sorted(descriptor['properties'] or []),
                 'native projection profile, properties or role differs from contract')
        _require(projections[name].target_schema == descriptor['representation_kind'], 'projection representation mismatch')
        _require(projections[name] == _native_projection_spec(name, descriptor),
                 'canonical projection profile, role, composition or requirement is not implemented by this backend')
    return contract.sha256


def _implementation_sha():
    kernel = Path(__file__).with_name('modal_autoencoder_cuda.py')
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), kernel)})


def _validate_state(contract, space, state):
    _require(type(state) is dict and set(state) == {'schema', 'contract_sha256', 'feature_space_sha256',
             'latent_width', 'parameters', 'adam', 'completed_epochs', 'optimizer_config', 'tuning_targets_sha256', *FALSE},
             'closed numerical state schema required')
    latent = state['latent_width']
    _require(type(latent) is int and 1 <= latent <= 64 and contract.state_codec.version == f'1:latent-{latent}',
             'numerical state architecture differs from contract')
    _require(state['schema'] == STATE_SCHEMA and state['contract_sha256'] == contract.sha256 and
             state['feature_space_sha256'] == digest(space) and all(state[key] is False for key in FALSE),
             'numerical state identity or authority mismatch')
    _require(type(state['completed_epochs']) is int and state['completed_epochs'] >= 0, 'invalid parent epoch count')
    _require(type(state['tuning_targets_sha256']) is str and re.fullmatch('[0-9a-f]{64}', state['tuning_targets_sha256']),
             'invalid immutable tuning identity')
    config = state['optimizer_config']
    _require(type(config) is dict and set(config) == {'name', 'learning_rate', 'betas', 'eps'} and
             config['name'] == 'Adam' and config['betas'] == [0.9, 0.999] and config['eps'] == 1e-8 and
             type(config['learning_rate']) in (int, float) and math.isfinite(config['learning_rate']) and
             0 < config['learning_rate'] <= 0.1, 'invalid saved optimizer settings')
    width = len(space['columns'])
    shapes = ((width, latent), (latent,), (latent, width), (width,))
    _require(type(state['parameters']) is list and type(state['adam']) is list and
             len(state['parameters']) == len(state['adam']) == 4, 'incomplete numerical parent state')
    def array(values, shape, nonnegative=False):
        _require(type(values) is list and len(values) == shape[0], 'invalid numerical tensor shape')
        for value in values:
            if len(shape) > 1:
                array(value, shape[1:], nonnegative)
            else:
                _require(type(value) in (int, float) and math.isfinite(value) and (not nonnegative or value >= 0),
                         'invalid numerical tensor value')
    for values, moment, shape in zip(state['parameters'], state['adam'], shapes):
        array(values, shape)
        _require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'} and
                 type(moment['step']) is int and moment['step'] == state['completed_epochs'], 'invalid Adam step')
        array(moment['exp_avg'], shape)
        array(moment['exp_avg_sq'], shape, True)


def build_native_feature_contract(space, *, ir_schema, adapter_sha256, latent_width=4):
    """Declare this concrete backend without remapping native modality semantics.

    Native profiles/roles remain native labels. The canonical family catalog
    supplies composition identities; these declarations do not qualify syntax.
    """
    from .autoencoder_modality_contracts import (ModalityContract, ImplementationIdentity,
        EmbeddingIdentity, ValidatorRequirement)
    from ...logic.formalization.autoencoder import domain_targets
    _require(type(latent_width) is int and 1 <= latent_width <= 64, 'invalid latent width')
    specs = tuple(_native_projection_spec(name, value)
        for name, value in sorted(space['projections'].items()))
    implementation = _implementation_sha()
    # Target validation is structural compiler evidence. Native qualification
    # observations remain attached to targets and never become proof authority.
    return ModalityContract(domain=space['domain_id'], ir_schema=ir_schema, source_language='structured',
        input_schema=SPACE_SCHEMA, embedding=EmbeddingIdentity('native-projection-features', 'v1',
            len(space['columns']), digest(space)), projections=specs,
        target_codec=ImplementationIdentity('native-domain-target-envelope', '1',
            hashlib.sha256(Path(domain_targets.__file__).read_bytes()).hexdigest()),
        state_codec=ImplementationIdentity(STATE_SCHEMA, f'1:latent-{latent_width}', implementation),
        optimizer=ImplementationIdentity(BACKEND, '1', implementation),
        objective_id='native-projection-reconstruction/v1', objective_sha256=digest(OBJECTIVE),
        validators=(ValidatorRequirement('native-target-structure', 'advisory', 'declaration',
                    projection_ids=tuple(space['projection_ids'])),),
        adapter=ImplementationIdentity('native-domain-target-adapter', '1', adapter_sha256))


def train_projection_features(contract, space, training_targets, tuning_targets, *,
                              base_state=None, epochs=3, latent_width=4, learning_rate=0.02,
                              max_seconds=60.0, seed=1729):
    """Train a bounded candidate; preserve Adam moments when resuming.

    Repeated tuning selects a candidate, never a qualified inference head.
    Deadline/epoch budget returns the best checked state, with rejected work counted.
    """
    started = time.monotonic()
    space = _plain(space)
    _require(space.get('schema') == SPACE_SCHEMA and 1 <= len(space.get('columns', [])) <= MAX_FEATURES,
             'unsupported feature space')
    contract_sha = _contract(contract, space)
    _require(type(epochs) is int and 1 <= epochs <= 32 and type(latent_width) is int and 1 <= latent_width <= 64,
             'bounded epoch and latent budgets required')
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= 0.1,
             'learning rate must be finite within (0, .1]')
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 300,
             'bounded training deadline required')
    _require(type(seed) is int and 0 <= seed < 2**31, 'invalid local seed')
    _require(contract.state_codec.version == f'1:latent-{latent_width}', 'latent architecture differs from contract')
    def check_deadline():
        _require(time.monotonic() - started < max_seconds, 'training deadline exhausted before candidate preparation')
    train, train_ids, train_coverage = _matrix(space, training_targets)
    tune, tune_ids, tune_coverage = _matrix(space, tuning_targets)
    _require(not (set(train_ids) | set(space['training_sources'])) & set(tune_ids), 'training/tuning source leakage')
    tuning_sha = digest([_target(row) for row in tuning_targets])
    check_deadline()
    import torch
    from . import modal_autoencoder_cuda as kernel
    check_deadline()
    generator = torch.Generator(device='cpu').manual_seed(seed)
    width = len(space['columns'])
    shapes = ((width, latent_width), (latent_width,), (latent_width, width), (width,))
    parameters = [(torch.randn(shape, generator=generator, dtype=torch.float64) * 0.1).requires_grad_()
                  if len(shape) == 2 else torch.zeros(shape, dtype=torch.float64, requires_grad=True) for shape in shapes]
    optimizer = torch.optim.Adam(parameters, lr=float(learning_rate))
    completed = 0
    parent_state_sha = None
    if base_state is not None:
        base_state = _plain(base_state)
        _validate_state(contract, space, base_state)
        _require(base_state['tuning_targets_sha256'] == tuning_sha, 'resumed feature selection requires the same tuning targets')
        parent_state_sha = digest(base_state)
        _require(base_state.get('schema') == STATE_SCHEMA and base_state.get('contract_sha256') == contract_sha
                 and base_state.get('feature_space_sha256') == digest(space) and base_state.get('latent_width') == latent_width,
                 'parent belongs to a different modality, projection, feature space or architecture')
        _require(len(base_state.get('parameters', [])) == len(parameters) and len(base_state.get('adam', [])) == len(parameters),
                 'incomplete numerical parent state')
        _require(type(base_state.get('completed_epochs')) is int and base_state['completed_epochs'] >= 0,
                 'invalid parent epoch count')
        _require(base_state.get('optimizer_config') == {'name': 'Adam', 'learning_rate': float(learning_rate),
                 'betas': [0.9, 0.999], 'eps': 1e-8}, 'resume requires identical optimizer settings')
        for parameter, values, moment in zip(parameters, base_state['parameters'], base_state['adam']):
            value = torch.tensor(values, dtype=torch.float64)
            avg = torch.tensor(moment['exp_avg'], dtype=torch.float64)
            sq = torch.tensor(moment['exp_avg_sq'], dtype=torch.float64)
            _require(value.shape == parameter.shape == avg.shape == sq.shape and
                     all(bool(torch.isfinite(t).all()) for t in (value, avg, sq)) and bool((sq >= 0).all()),
                     'parent tensors have invalid shape or values')
            _require(type(moment['step']) is int and moment['step'] == base_state['completed_epochs'], 'invalid Adam step')
            with torch.no_grad(): parameter.copy_(value)
            optimizer.state[parameter] = {'step': torch.tensor(float(moment['step'])), 'exp_avg': avg, 'exp_avg_sq': sq}
        completed = base_state['completed_epochs']
    data = torch.tensor(train, dtype=torch.float64)
    tuning = torch.tensor(tune, dtype=torch.float64)
    spans = {}
    for name in space['projection_ids']:
        positions = [i for i, (projection, _) in enumerate(space['columns']) if projection == name]
        spans[name] = (min(positions), max(positions) + 1)

    def forward(inputs):
        return torch.tanh(inputs @ parameters[0] + parameters[1]) @ parameters[2] + parameters[3]

    def loss(inputs):
        decoded = forward(inputs)
        empty = torch.zeros((len(inputs), 0), dtype=torch.float64)
        session = SimpleNamespace(blocks={}, parameters=parameters, parameter_count=sum(p.numel() for p in parameters))
        total = 0
        metrics = {}
        for name, (start, stop) in spans.items():
            state = SimpleNamespace(torch=torch, device=torch.device('cpu'), embeddings=inputs[:, start:stop])
            _require(bool((torch.linalg.vector_norm(decoded[:, start:stop], dim=1) > 1e-8).all()),
                     'zero-norm projection reconstruction cannot count as perfect cosine')
            value, components, _ = kernel._loss_chunk(state, session, (decoded[:, start:stop], empty, empty),
                {'decoded_embedding'}, 0, len(inputs), len(inputs), 0.1, 0.0, False)
            total = total + value / len(spans)
            metrics[name] = {key: float(components[key].detach()) for key in ('reconstruction', 'cosine', 'guarded_auxiliary')}
        return total, metrics

    def state_dict():
        moments = []
        for parameter in parameters:
            item = optimizer.state.get(parameter, {})
            moments.append({'step': int(item.get('step', 0)),
                            'exp_avg': item.get('exp_avg', torch.zeros_like(parameter)).tolist(),
                            'exp_avg_sq': item.get('exp_avg_sq', torch.zeros_like(parameter)).tolist()})
        return {'schema': STATE_SCHEMA, 'contract_sha256': contract_sha, 'feature_space_sha256': digest(space),
                'latent_width': latent_width, 'parameters': [p.detach().tolist() for p in parameters],
                'adam': moments, 'completed_epochs': completed,
                'tuning_targets_sha256': tuning_sha,
                'optimizer_config': {'name': 'Adam', 'learning_rate': float(learning_rate),
                                     'betas': [0.9, 0.999], 'eps': 1e-8}, **FALSE}

    check_deadline()
    with torch.no_grad(): before, before_metrics = loss(tuning)
    check_deadline()
    best_loss, best_metrics, best = float(before), before_metrics, state_dict()
    reports, stopped = [], 'epoch_budget'
    for epoch in range(epochs):
        if time.monotonic() - started >= max_seconds:
            stopped = 'deadline'; break
        optimizer.zero_grad()
        objective, _ = loss(data)
        _require(bool(torch.isfinite(objective)), 'nonfinite training objective')
        objective.backward()
        gradient = kernel._gradient_norm(torch, parameters)
        _require(math.isfinite(gradient), 'nonfinite gradient')
        torch.nn.utils.clip_grad_norm_(parameters, 1.0)
        if time.monotonic() - started >= max_seconds:
            stopped = 'deadline'; break
        optimizer.step()
        completed += 1
        with torch.no_grad(): candidate, metrics = loss(tuning)
        _require(bool(torch.isfinite(candidate)), 'nonfinite tuning objective')
        # No projection may regress while an aggregate hides the regression.
        expired = time.monotonic() - started >= max_seconds
        selected = (not expired and float(candidate) < best_loss and all(
            metrics[name][key] <= best_metrics[name][key] + 1e-9
            for name in spans for key in ('reconstruction', 'cosine')))
        if selected:
            best_loss, best_metrics, best = float(candidate), metrics, state_dict()
        reports.append({'epoch': epoch + 1, 'train_objective': float(objective.detach()),
                        'tuning_objective': float(candidate), 'gradient_norm': gradient,
                        'selected': selected, 'deadline_exceeded': expired, 'projection_metrics': metrics})
        if expired:
            stopped = 'deadline'; break
    return {'state': best, 'report': {'schema': 'native-projection-feature-training/v1',
        'backend': BACKEND, 'contract_sha256': contract_sha, 'feature_space_sha256': digest(space),
        'base_state_sha256': parent_state_sha,
        'training_targets_sha256': digest([_target(row) for row in training_targets]),
        'tuning_targets_sha256': digest([_target(row) for row in tuning_targets]),
        'configuration': {'epochs': epochs, 'latent_width': latent_width, 'learning_rate': learning_rate,
                          'max_seconds': max_seconds, 'seed': seed, 'objective': OBJECTIVE},
        'deadline_enforcement': 'cooperative_checks_between_native_operations',
        'attempted_epochs': len(reports), 'selected_total_epochs': best['completed_epochs'],
        'training_target_count': len(train), 'tuning_target_count': len(tune),
        'before': {'objective': float(before), 'projections': before_metrics},
        'after': {'objective': best_loss, 'projections': best_metrics}, 'epochs': reports,
        'improved': best_loss < float(before), 'stopped_reason': stopped,
        'elapsed_seconds': time.monotonic() - started, 'train_coverage': train_coverage,
        'tuning_coverage': tune_coverage, 'heldout_canary': False,
        'representation': 'native_compiler_structural_features_not_semantic_text_embeddings',
        'weights_downloaded': False, 'lake_executed': False, **FALSE}}


def infer_projection_features(contract, space, state, targets):
    """Read a selected structural model; never train or turn scores into formulas."""
    space, state = _plain(space), _plain(state)
    _contract(contract, space)
    _validate_state(contract, space, state)
    values, sources, coverage = _matrix(space, targets)
    import torch
    with torch.no_grad():
        encoder, bias, decoder, output_bias = [torch.tensor(value, dtype=torch.float64)
                                               for value in state['parameters']]
        latent = torch.tanh(torch.tensor(values, dtype=torch.float64) @ encoder + bias)
        decoded = latent @ decoder + output_bias
        _require(bool(torch.isfinite(latent).all()) and bool(torch.isfinite(decoded).all()),
                 'nonfinite inference output')
        rows = []
        for index, source in enumerate(sources):
            projections = {name: [float(decoded[index, col]) for col, (projection, _) in enumerate(space['columns'])
                                  if projection == name] for name in space['projection_ids']}
            rows.append({'source_digest': source, 'latent': latent[index].tolist(),
                         'reconstructed_projection_features': projections})
    return {'schema': 'native-projection-feature-inference/v1', 'contract_sha256': contract.sha256,
            'state_sha256': digest(state), 'feature_space_sha256': digest(space), 'rows': rows,
            'coverage': coverage, 'training_executed': False, 'decoded_formulas_generated': False,
            'representation': 'native_compiler_structural_features_not_semantic_text_embeddings', **FALSE}


def register_feature_candidate(registry, contract, space, result, directory, *, parent_version_id=None):
    """Store an isolated candidate through the existing single-owner registry.

    This does not select a distributed generation, enqueue Hub publication, or
    promote an inference head. Registry variants enforce cross-modality parent
    rejection even for numerically identical artifacts.
    """
    contract_sha = _contract(contract, space)
    _require(result['state']['contract_sha256'] == contract_sha and result['report']['contract_sha256'] == contract_sha,
             'candidate contract differs from requested registry lane')
    _require(result['state']['schema'] == STATE_SCHEMA and
             result['state']['feature_space_sha256'] == result['report']['feature_space_sha256'] == digest(space),
             'candidate feature space differs from requested registry lane')
    _validate_state(contract, space, result['state'])
    _require(all(result['state'][key] is False and result['report'][key] is False for key in FALSE),
             'feature candidate cannot claim qualification')
    if parent_version_id is not None:
        parent = registry.get_version(parent_version_id)
        _require(parent['variant_id'] == contract.variant_id, 'parent variant mismatch')
        registry.verify_artifact(parent['artifact'])
        with registry.artifact_path(parent['artifact']).open('rb') as stream:
            parent_raw = stream.read(32 * 1024 * 1024 + 1)
        _require(len(parent_raw) <= 32 * 1024 * 1024, 'parent exceeds checkpoint bound')
        _require(len(parent_raw) == parent['artifact']['bytes'] and
                 hashlib.sha256(parent_raw).hexdigest() == parent['artifact']['sha256'],
                 'parent artifact changed during candidate registration')
        saved = json.loads(parent_raw)
        _require(digest(saved['state']) == result['report']['base_state_sha256'], 'candidate numerical parent differs from registry parent')
    else:
        _require(result['report']['base_state_sha256'] is None, 'resumed candidate requires its exact registry parent')
    directory = Path(directory)
    _require(not directory.exists(), 'fresh candidate staging directory required')
    directory.mkdir(parents=True)
    envelope = {'contract': contract.to_dict(), 'feature_space': space, 'state': result['state'], 'report': result['report']}
    raw = _raw(envelope)
    _require(len(raw) <= 32 * 1024 * 1024, 'candidate exceeds checkpoint bound')
    path = directory/'candidate.json'
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    artifact = registry.stage_artifact(path, hashlib.sha256(raw).hexdigest())
    registry.register_variant('modality-register:' + contract_sha.removeprefix('sha256:'), contract.variant_id,
                              contract.registry_manifest())
    receipt = registry.register_version('modality-candidate:' + artifact['sha256'], contract.variant_id, artifact,
        {'contract_sha256': contract_sha, 'training_purpose': 'feature_pretraining', **FALSE}, parent_version_id)
    return {'version_id': receipt['version_id'],
            'artifact': artifact, 'variant_id': contract.variant_id, **FALSE}

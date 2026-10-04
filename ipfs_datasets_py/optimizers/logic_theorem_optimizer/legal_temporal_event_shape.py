"""Controlled auxiliary event-shape supervision for source-only eligibility.

Both arms share source, binary-head initialization and complete-source sampling.
Only auxiliary_shape optimizes the separate four-class head on the shared hidden
representation. Shape predictions are diagnostics, never acceptance inputs or
legal/formal authority. Original raw checkpoints retain the full training state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import time

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
from . import legal_temporal_event_eligibility as base

carrier = base.carrier

SCHEMA = 'legal-temporal-event-shape-checkpoint/v1'
PREDICTION_SCHEMA = 'legal-temporal-event-eligibility-prediction/v1'
REPORT_SCHEMA = 'legal-temporal-event-shape-training/v1'
SHAPE_PREDICTION_SCHEMA = 'legal-temporal-event-shape-prediction/v1'
SHAPE_CLASSES = ('finite_clause', 'nominal_event', 'bare_fragment', 'other')
CLASSES = ('defer_surface', 'eligible_surface')
ARMS = ('binary_control', 'auxiliary_shape')
SOURCE_KEYS = {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
TRAIN_KEYS = SOURCE_KEYS | {'label', 'group_id', 'shape_label'}
MAX_ROWS = 4096
MAX_STEPS = 400
MAX_SOURCES_PER_BATCH = 16
MAX_CANDIDATES_PER_SOURCE = 3
MAX_CHECKPOINT_BYTES = 128 * 1024 * 1024
PARENT_FILE_SHA256 = '7558bb022501920efd1069384384894e1079ed858588784b8b253c0a7c258cd2'
PARENT_PAYLOAD_SHA256 = '8463a96f30a8d070a676eb7245f4f34826d78f1ebf397cce9c4aca325a0ffd9b'
AUTHORITY = {'legal_semantics_verified': False, 'owner_assigned': False,
             'formal_formula_admitted': False, 'latent_input_enabled': False,
             'pipeline_promotion': False}
require, digest, span, _torch = carrier.require, carrier.digest, carrier.span, carrier._torch


def _pins():
    return base.producer_pins() | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_INITIAL_PINS = _pins()


def producer_pins():
    require(_pins() == _INITIAL_PINS, 'shape producer source drift')
    return dict(_INITIAL_PINS)


def _query(row):
    require(type(row) is dict and set(row) == SOURCE_KEYS, 'closed four-field source query required')
    require(type(row['source_text']) is str and 0 < len(row['source_text']) <= 4096
            and len(row['source_text'].encode()) <= 40000, 'complete bounded source required; truncation forbidden')
    return carrier._query(row)


def source_queries(rows):
    return [{key: copy.deepcopy(row[key]) for key in SOURCE_KEYS} for row in rows]


def _records(rows):
    require(type(rows) in (list, tuple) and 1 <= len(rows) <= MAX_ROWS, 'bounded supervised inventory required')
    for row in rows:
        require(type(row) is dict and set(row) == TRAIN_KEYS, 'closed seven-field shape target required')
        require(row['shape_label'] is None or type(row['shape_label']) is str and row['shape_label'] in SHAPE_CLASSES,
                'declared shape class or masked None required')
    old = [{key: value for key, value in row.items() if key != 'shape_label'} for row in rows]
    records = base._records(old)
    return [{**record, 'shape_label': None if row['shape_label'] is None else SHAPE_CLASSES.index(row['shape_label'])}
            for row, record in zip(rows, records)]


def _source_groups(records):
    groups = {}
    for i, record in enumerate(records):
        groups.setdefault(record['query']['source_sha256'], []).append(i)
    for indices in groups.values():
        indices.sort(key=lambda i: (*records[i]['time_tokens'], records[i]['query']['id']))
    return groups


def _splits(training, tuning):
    train, tune = _records(training), _records(tuning)
    for key in ('id', 'source_sha256', 'group_id'):
        require(not {r[key] for r in training} & {r[key] for r in tuning}, 'training/tuning overlap: ' + key)
    normalized = lambda rows: {' '.join(r['source_text'].casefold().split()) for r in rows}
    require(not normalized(training) & normalized(tuning), 'normalized training/tuning source overlap')
    groups = _source_groups(train)
    require(len(groups) >= 16, 'training needs sixteen complete distinct sources')
    for label in range(2):
        require(sum(any(train[i]['label'] == label for i in indices) for indices in groups.values()) >= 8,
                'training needs eight source groups bearing each class')
        require(any(r['label'] == label for r in tune), 'tuning needs both eligibility classes')
    return train, tune


def _config(arm, seed):
    require(arm in ARMS and type(seed) is int and seed in (1730, 1731), 'declared eligibility arm/seed required')
    return {'arm': arm, 'seed': seed, 'class_order': list(CLASSES), 'source_width': 64, 'head_hidden': 32,
            'features': 'source_mean64/candidate_start64/candidate_end64/candidate_mean64',
            'head_learning_rate': .001, 'encoder_learning_rate': .0001, 'gradient_clip': 5.,
            'max_steps': MAX_STEPS, 'sources_per_batch': 16, 'maximum_candidates_per_source': 3,
            'sampler': 'eight_defer_bearing_prefer_exclusive_then_eight_remaining_eligible_bearing; complete_unique_sources; seed_step_shuffle/v1',
            'objective': 'equal_class_mean_of_equal_source_mean_candidate_cross_entropy/v1',
            'encoder_trainable': True, 'shape_enabled': arm == 'auxiliary_shape',
            'shape_class_order': list(SHAPE_CLASSES), 'shape_loss_weight': .5,
            'shape_objective': 'equal_present_class_mean_of_equal_source_mean_masked_candidate_cross_entropy/v1',
            'shape_head': 'shared_tanh32_to4', 'source_input': 'utf8_bytes_and_exact_candidate_offsets_only',
            'source_carrier': 'relative_position-1730-step200', 'parent_optimizer_moments_transferred': False,
            'device': 'cpu', 'dtype': 'float32', 'inference_batch_limit': 64}


def _model(torch, parent, config):
    # The authenticated base graph supplies exactly the former binary/GRU
    # initialization. A separate RNG fork cannot perturb that initialization.
    warm = base._model(torch, parent, base._config('finetuned_gru_eligibility', config['seed']))

    class ShapeModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source = warm.source
            self.head = warm.head
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(config['seed'] + 10000)
                self.shape_head = torch.nn.Linear(32, 4)
            self.shape_head.requires_grad_(config['shape_enabled'])

        def features(self, records):
            return warm.features(records)

        def hidden(self, records):
            return self.head[1](self.head[0](self.features(records)))

        def forward(self, records):
            return self.head[2](self.hidden(records))

        def forward_joint(self, records):
            hidden = self.hidden(records)
            return self.head[2](hidden), self.shape_head(hidden)

    return ShapeModel()


def _optimizer(torch, model, config):
    heads = list(model.head.parameters())
    if config['shape_enabled']:
        heads += list(model.shape_head.parameters())
    groups = [{'params': heads, 'lr': config['head_learning_rate']},
              {'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']}]
    return torch.optim.Adam(groups, foreach=False)


def batch_indices(records, seed, step):
    """Return every candidate for sixteen distinct sources; groups never split."""
    require(type(seed) is int and seed in (1730, 1731) and type(step) is int and 0 <= step < MAX_STEPS,
            'declared sampler seed and update required')
    groups = _source_groups(records)
    classes = {key: {records[i]['label'] for i in indices} for key, indices in groups.items()}
    exclusive = sorted(key for key, labels in classes.items() if labels == {0})
    mixed = sorted(key for key, labels in classes.items() if labels == {0, 1})
    random.Random(f'eligibility/{seed}/{step}/defer-exclusive').shuffle(exclusive)
    random.Random(f'eligibility/{seed}/{step}/defer-mixed').shuffle(mixed)
    first = (exclusive + mixed)[:8]
    available = sorted(key for key, labels in classes.items() if 1 in labels and key not in first)
    random.Random(f'eligibility/{seed}/{step}/eligible').shuffle(available)
    selected = first + available[:8]
    require(len(first) == 8 and len(selected) == len(set(selected)) == 16, 'sixteen distinct balanced source cases required')
    indices = [i for key in selected for i in groups[key]]
    require(16 <= len(indices) <= 48, 'complete source candidate batch bound differs')
    return indices, selected


def shape_objective(torch, logits, records):
    """Equal present class means of source means; None contributes no gradient."""
    require(type(records) in (list, tuple) and records and logits.shape == (len(records), 4)
            and bool(torch.isfinite(logits).all()), 'finite shape logits and records required')
    labels = [record['shape_label'] for record in records]
    require(all(label is None or type(label) is int and 0 <= label < 4 for label in labels), 'valid masked shape labels required')
    terms, means, sources, candidates = [], [], [], []
    for label in range(4):
        by_source = {}
        for i, record in enumerate(records):
            if record['shape_label'] == label:
                by_source.setdefault(record['query']['source_sha256'], []).append(i)
        source_means = []
        for indices in by_source.values():
            target = torch.full((len(indices),), label, dtype=torch.long)
            source_means.append(torch.nn.functional.cross_entropy(logits[indices], target))
        value = torch.stack(source_means).mean() if source_means else None
        if value is not None: terms.append(value)
        means.append(None if value is None else float(value.detach()))
        sources.append(len(by_source)); candidates.append(sum(map(len, by_source.values())))
    # Connected zero ensures resumable Adam has an explicit zero gradient for
    # every trainable auxiliary tensor even on a completely masked batch.
    loss = torch.stack(terms).mean() if terms else logits.sum() * 0.
    return loss, {'loss': float(loss.detach()), 'class_mean_source_nll': means,
                  'class_source_counts': sources, 'class_candidate_counts': candidates,
                  'present_classes': [i for i, count in enumerate(candidates) if count],
                  'source_count': len({r['query']['source_sha256'] for r in records if r['shape_label'] is not None}),
                  'candidate_count': sum(candidates), 'masked_candidate_count': sum(label is None for label in labels)}


def objective(torch, logits, shape_logits, records, *, arm):
    require(arm in ARMS, 'declared objective arm required')
    binary, binary_parts = base.objective(torch, logits, records)
    shape, shape_parts = shape_objective(torch, shape_logits, records)
    weight = .5 if arm == 'auxiliary_shape' else 0.
    loss = binary + weight * shape if arm == 'auxiliary_shape' else binary
    return loss, {'binary': binary_parts, 'shape': shape_parts, 'binary_loss': float(binary.detach()),
                  'shape_loss': float(shape.detach()), 'shape_weight': weight, 'loss': float(loss.detach())}


def _manifests(training, tuning):
    return {key: {'sha256': digest(rows), 'count': len(rows), 'sources': len({r['source_sha256'] for r in rows}),
                  'groups': len({r['group_id'] for r in rows})} for key, rows in (('training', training), ('tuning', tuning))}


def build_checkpoint(parent_payload, training_rows, tuning_rows, *, arm, seed, parent_file_sha256):
    """Caller must authenticate parent_file_sha256 against the actual carrier file."""
    _splits(training_rows, tuning_rows)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'authenticated parent file SHA required')
    require(parent_file_sha256 == PARENT_FILE_SHA256 and digest(parent_payload) == PARENT_PAYLOAD_SHA256,
            'exact original relative-position carrier binding required')
    torch = _torch(); config = _config(arm, seed); model = _model(torch, parent_payload, config)
    optimizer = _optimizer(torch, model, config); weights, moments = span._pack(model, optimizer)
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'parent': copy.deepcopy(parent_payload),
            'parent_payload_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
            'model_config': copy.deepcopy(parent_payload['model_config']), 'config': config,
            'manifests': _manifests(training_rows, tuning_rows), 'initial_state_sha256': digest(weights),
            'model_state': weights, 'optimizer_state': moments, 'optimizer_steps': 0,
            'preceding_checkpoint_sha256': None, 'authority': dict(AUTHORITY), 'formula_admission': False}


def _restore(checkpoint):
    fields = {'schema', 'implementation', 'parent', 'parent_payload_sha256', 'parent_file_sha256', 'model_config',
              'config', 'manifests', 'initial_state_sha256', 'model_state', 'optimizer_state', 'optimizer_steps',
              'preceding_checkpoint_sha256', 'authority', 'formula_admission'}
    require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint['schema'] == SCHEMA,
            'closed event-shape checkpoint required')
    require(checkpoint['authority'] == AUTHORITY and all(x is False for x in checkpoint['authority'].values())
            and checkpoint['formula_admission'] is False, 'eligibility authority escalation')
    require(checkpoint['implementation'] == producer_pins(), 'shape producer binding differs')
    require(len(span._raw(checkpoint)) <= MAX_CHECKPOINT_BYTES, 'eligibility checkpoint exceeds128MiB')
    config = checkpoint['config']
    require(type(config) is dict and {'arm', 'seed'} <= set(config)
            and span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'eligibility configuration differs')
    for key in ('parent_payload_sha256', 'parent_file_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid provenance hash')
    original = checkpoint['parent']
    require(checkpoint['parent_file_sha256'] == PARENT_FILE_SHA256
            and checkpoint['parent_payload_sha256'] == PARENT_PAYLOAD_SHA256,
            'exact original relative-position carrier binding required')
    require(checkpoint['parent_payload_sha256'] == digest(original)
            and span._raw(checkpoint['model_config']) == span._raw(original['model_config']), 'source carrier payload binding differs')
    manifests = checkpoint['manifests']
    require(type(manifests) is dict and set(manifests) == {'training', 'tuning'}, 'closed split manifests required')
    for value in manifests.values():
        require(type(value) is dict and set(value) == {'sha256', 'count', 'sources', 'groups'}
                and type(value['sha256']) is str and span._SHA.fullmatch(value['sha256'])
                and all(type(value[k]) is int for k in ('count', 'sources', 'groups'))
                and 1 <= value['groups'] <= value['sources'] <= value['count'] <= MAX_ROWS
                and value['count'] <= 3 * value['sources'], 'invalid split manifest')
    require(manifests['training']['sources'] >= 16, 'inadequate training source manifest')
    steps = checkpoint['optimizer_steps']
    require(type(steps) is int and 0 <= steps <= MAX_STEPS, 'bounded eligibility update count required')
    preceding = checkpoint['preceding_checkpoint_sha256']
    require(preceding is None if steps == 0 else type(preceding) is str and span._SHA.fullmatch(preceding), 'invalid checkpoint predecessor')
    torch = _torch(); model = _model(torch, original, config); optimizer = _optimizer(torch, model, config)
    initial, _ = span._pack(model, optimizer)
    require(digest(initial) == checkpoint['initial_state_sha256'], 'initial eligibility/source tensors differ')
    weights = checkpoint['model_state']; template = model.state_dict()
    require(type(weights) is dict and set(weights) == set(template), 'eligibility tensor inventory differs')
    if steps == 0:
        require(span._raw(weights) == span._raw(initial), 'zero-update eligibility weights differ')
    trainable = {name: p for name, p in model.named_parameters() if p.requires_grad}
    for name, value in initial.items():
        if name not in trainable:
            require(span._raw(weights[name]) == span._raw(value), 'frozen source tensor changed: ' + name)
    model.load_state_dict({name: span._tensor(torch, weights[name], value.shape, name) for name, value in template.items()}, strict=True)
    moments = checkpoint['optimizer_state']
    require(type(moments) is dict and set(moments) == {'schema', 'parameters'}
            and moments['schema'] == 'adam-default-betas-eps/v1' and type(moments['parameters']) is dict
            and set(moments['parameters']) == (set(trainable) if steps else set()), 'Adam trainable inventory differs')
    for name, moment in moments['parameters'].items():
        require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'}
                and type(moment['step']) is int and moment['step'] == steps, 'Adam step differs')
        p = trainable[name]
        optimizer.state[p] = {'step': torch.tensor(float(steps)),
                              'exp_avg': span._tensor(torch, moment['exp_avg'], p.shape, name),
                              'exp_avg_sq': span._tensor(torch, moment['exp_avg_sq'], p.shape, name, nonnegative=True)}
    model.eval(); return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)
    return checkpoint


def train(checkpoint, training_rows, tuning_rows, *, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional updates required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    records, _ = _splits(training_rows, tuning_rows)
    require(checkpoint['manifests'] == _manifests(training_rows, tuning_rows), 'training/tuning manifests changed')
    config = checkpoint['config']; initial_step = checkpoint['optimizer_steps']
    require(initial_step + additional_steps <= MAX_STEPS, 'eligibility update budget exceeded')
    trainable = {name: p for name, p in model.named_parameters() if p.requires_grad}; trace = []
    for step in range(initial_step, initial_step + additional_steps):
        require(time.monotonic() - started < max_seconds, 'training deadline exceeded; incomplete stage is not successful')
        indices, sources = batch_indices(records, config['seed'], step)
        batch = [records[i] for i in indices]
        optimizer.zero_grad(set_to_none=True); model.train(); logits, shape_logits = model.forward_joint(batch)
        loss, parts = objective(torch, logits, shape_logits, batch, arm=config['arm'])
        require(bool(torch.isfinite(loss)), 'nonfinite eligibility loss'); loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in trainable.values()), 'missing/nonfinite trainable gradient')
        require(all(p.grad is None for p in model.parameters() if not p.requires_grad), 'frozen source received gradient')
        norm = torch.nn.utils.clip_grad_norm_(list(trainable.values()), config['gradient_clip'])
        require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        optimizer.step()
        require(all(bool(torch.isfinite(p).all()) for p in model.parameters()), 'nonfinite updated parameter')
        require(all(bool(torch.isfinite(v).all()) for values in optimizer.state.values() for v in values.values() if torch.is_tensor(v)),
                'nonfinite Adam moment')
        trace.append({'step': step + 1, 'query_ids': [r['query']['id'] for r in batch],
                      'source_sha256': [r['query']['source_sha256'] for r in batch],
                      'group_ids': [r['group_id'] for r in batch], 'complete_source_order': sources,
                      'labels': [r['label'] for r in batch], 'logits': logits.detach().tolist(),
                      'shape_labels': [r['shape_label'] for r in batch],
                      'shape_mask': [r['shape_label'] is not None for r in batch],
                      'shape_logits': shape_logits.detach().tolist(),
                      'binary_loss': parts['binary_loss'], 'shape_loss': parts['shape_loss'], 'shape_weight': parts['shape_weight'],
                      'objective_components': parts, 'loss': float(loss.detach()), 'preclip_gradient_norm': float(norm),
                      'encoder_batch_forwards': 1, 'encoder_source_evaluations': len(batch)})
    weights, moments = span._pack(model, optimizer)
    result = {**copy.deepcopy(checkpoint), 'model_state': weights, 'optimizer_state': moments,
              'optimizer_steps': initial_step + additional_steps,
              'preceding_checkpoint_sha256': digest(checkpoint) if additional_steps else checkpoint['preceding_checkpoint_sha256']}
    # Full provenance validation happens at stage boundaries, never per batch.
    _restore(result)
    return result, {'schema': REPORT_SCHEMA, 'initial_step': initial_step, 'final_step': result['optimizer_steps'],
                    'steps_executed': len(trace), 'trace': trace, 'implementation': producer_pins(),
                    'trainable_parameters': {name: p.numel() for name, p in trainable.items()},
                    'encoder_batch_forwards': len(trace), 'encoder_source_evaluations': sum(len(t['query_ids']) for t in trace),
                    'wall_seconds': time.monotonic() - started, 'parent_optimizer_moments_transferred': False,
                    'authority': dict(AUTHORITY), 'formula_admission': False}


class TemporalEventShapeEligibility:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint_sha256 = digest(checkpoint)
        self.encoder_batch_forwards = 0
        self.encoder_source_evaluations = 0

    def _predict(self, queries, joint):
        require(type(queries) in (list, tuple) and 0 < len(queries) <= 64, 'bounded source-only prediction batch required')
        records = [_query(row) for row in queries]
        require(len({r['query']['id'] for r in records}) == len(records), 'duplicate inference candidate ID')
        require(len({(r['query']['source_sha256'], *r['time_tokens']) for r in records}) == len(records),
                'duplicate inference source occurrence')
        self.model.eval()
        with self.torch.no_grad():
            if joint:
                logits, shape_logits = self.model.forward_joint(records)
            else:
                logits = self.model(records)
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(records)
        def rows(values, classes, schema, diagnostic):
            probabilities = self.torch.softmax(values, dim=-1)
            require(bool(self.torch.isfinite(values).all()) and bool(self.torch.isfinite(probabilities).all()), 'nonfinite prediction')
            output = []
            for i, record in enumerate(records):
                chosen = int(probabilities[i].argmax())
                row = {'schema': schema, 'query': copy.deepcopy(record['query']),
                       'checkpoint_sha256': self.checkpoint_sha256, 'class_order': list(classes),
                       'logits': values[i].tolist(), 'probabilities': probabilities[i].tolist(),
                       'predicted_label': classes[chosen], 'confidence': float(probabilities[i, chosen]),
                       'authority': dict(AUTHORITY), 'formula_admission': False}
                if diagnostic: row.update(diagnostic_only=True, acceptance_input_allowed=False)
                output.append(row)
            return output
        binary = rows(logits, CLASSES, PREDICTION_SCHEMA, False)
        return {'binary': binary, 'shapes': rows(shape_logits, SHAPE_CLASSES, SHAPE_PREDICTION_SCHEMA, True)} if joint else binary

    def predict_many(self, queries):
        return self._predict(queries, False)

    def predict_joint(self, queries):
        """One source encoder forward; shape diagnostics never drive acceptance."""
        return self._predict(queries, True)

    def predict_shapes(self, queries):
        return self.predict_joint(queries)['shapes']


TemporalEventEligibility = TemporalEventShapeEligibility


def save_checkpoint(checkpoint, path):
    _restore(checkpoint); path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(checkpoint, stream, sort_keys=True, separators=(',', ':'), allow_nan=False); stream.write('\n')
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def load_checkpoint(path, *, expected_sha256):
    require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), 'expected checkpoint SHA required')
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
    require(len(raw) <= MAX_CHECKPOINT_BYTES and hashlib.sha256(raw).hexdigest() == expected_sha256, 'checkpoint file binding differs')
    checkpoint = json.loads(raw); _restore(checkpoint); return checkpoint

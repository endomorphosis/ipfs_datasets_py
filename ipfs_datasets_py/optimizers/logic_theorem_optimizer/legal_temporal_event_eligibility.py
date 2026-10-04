"""Source-conditioned eligibility of fixed temporal surface envelopes.

This binary classifier neither changes span coordinates nor assigns an owner or
legal meaning. A caller authenticates the carrier file and supplies complete,
independently reviewed candidate targets; parser reasons never enter the graph.
Thresholds and source-level conflict guards belong to a separate frozen adapter.
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
from . import legal_temporal_relative_owner as carrier

SCHEMA = 'legal-temporal-event-eligibility-checkpoint/v1'
PREDICTION_SCHEMA = 'legal-temporal-event-eligibility-prediction/v1'
REPORT_SCHEMA = 'legal-temporal-event-eligibility-training/v1'
CLASSES = ('defer_surface', 'eligible_surface')
ARMS = ('frozen_encoder_eligibility', 'finetuned_gru_eligibility')
SOURCE_KEYS = {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
TRAIN_KEYS = SOURCE_KEYS | {'label', 'group_id'}
MAX_ROWS = 4096
MAX_STEPS = 200
MAX_SOURCES_PER_BATCH = 16
MAX_CANDIDATES_PER_SOURCE = 3
MAX_CHECKPOINT_BYTES = 128 * 1024 * 1024
AUTHORITY = {'legal_semantics_verified': False, 'owner_assigned': False,
             'formal_formula_admitted': False, 'latent_input_enabled': False,
             'pipeline_promotion': False}
require, digest, span, _torch = carrier.require, carrier.digest, carrier.span, carrier._torch


def _pins():
    return carrier.producer_pins() | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_INITIAL_PINS = _pins()


def producer_pins():
    require(_pins() == _INITIAL_PINS, 'eligibility producer source drift')
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
    records, ids, occurrences, sources = [], set(), set(), {}
    for row in rows:
        require(type(row) is dict and set(row) == TRAIN_KEYS, 'closed six-field eligibility target required')
        require(type(row['label']) is str and row['label'] in CLASSES, 'declared surface label required')
        require(type(row['group_id']) is str and 0 < len(row['group_id']) <= 256, 'bounded provenance group required')
        record = _query({key: row[key] for key in SOURCE_KEYS})
        occurrence = (row['source_sha256'], *record['time_tokens'])
        require(row['id'] not in ids and occurrence not in occurrences, 'duplicate candidate identity or occurrence')
        ids.add(row['id']); occurrences.add(occurrence)
        identity = row['source_sha256']
        group = sources.setdefault(identity, {'group_id': row['group_id'], 'count': 0})
        require(group['group_id'] == row['group_id'], 'same source has conflicting provenance groups')
        group['count'] += 1
        require(group['count'] <= MAX_CANDIDATES_PER_SOURCE, 'at most three complete raw candidates per source')
        records.append({**record, 'label': CLASSES.index(row['label']), 'group_id': row['group_id']})
    return records


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
            'encoder_trainable': arm == 'finetuned_gru_eligibility', 'source_input': 'utf8_bytes_and_exact_candidate_offsets_only',
            'source_carrier': 'relative_position-1730-step200', 'parent_optimizer_moments_transferred': False,
            'device': 'cpu', 'dtype': 'float32', 'inference_batch_limit': 64}


def _model(torch, parent, config):
    require(type(parent) is dict and parent.get('schema') == carrier.SCHEMA, 'relative owner source carrier required')
    require(parent['config']['arm'] == 'relative_position' and parent['config']['seed'] == 1730
            and parent['optimizer_steps'] == 200, 'exact relative_position-1730-step200 carrier required')
    require(parent['model_config']['latent_dimension'] == 0 and parent['model_config']['hidden_size'] == 32
            and parent['model_config']['embedding_dim'] == 16, 'source-only64D byte/GRU carrier required')
    _, warm, _ = carrier._restore(parent)

    class EligibilityModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source = warm.source
            self.source.requires_grad_(False)
            if config['encoder_trainable']:
                self.source.encoder.requires_grad_(True)
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(config['seed'])
                self.head = torch.nn.Sequential(torch.nn.Linear(256, 32), torch.nn.Tanh(), torch.nn.Linear(32, 2))

        def features(self, records):
            captured = []
            handle = self.source.encoder.register_forward_hook(lambda _m, _a, output: captured.append(output[0]))
            try:
                self.source(*span._batch(torch, records))
            finally:
                handle.remove()
            require(len(captured) == 1, 'exactly one source encoder forward required')
            encoded, lengths = torch.nn.utils.rnn.pad_packed_sequence(captured[0], batch_first=True)
            require(encoded.shape[-1] == 64, '64D source states required')
            mask = torch.arange(encoded.shape[1])[None, :] < lengths[:, None]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            first = torch.stack([encoded[i, r['time_tokens'][0]] for i, r in enumerate(records)])
            last = torch.stack([encoded[i, r['time_tokens'][1]] for i, r in enumerate(records)])
            means = torch.stack([encoded[i, r['time_tokens'][0]:r['time_tokens'][1]+1].mean(0) for i, r in enumerate(records)])
            return torch.cat((pooled, first, last, means), dim=1)

        def forward(self, records):
            return self.head(self.features(records))

    return EligibilityModel()


def _optimizer(torch, model, config):
    groups = [{'params': list(model.head.parameters()), 'lr': config['head_learning_rate']}]
    if config['encoder_trainable']:
        groups.append({'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']})
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


def objective(torch, logits, records):
    """Each class weighs1/2; each source within that class weighs equally."""
    require(type(records) in (list, tuple) and records and logits.shape == (len(records), 2)
            and bool(torch.isfinite(logits).all()), 'finite binary logits and records required')
    labels = torch.tensor([r['label'] for r in records], dtype=torch.long)
    require(bool(((labels == 0) | (labels == 1)).all()), 'binary labels required')
    nll = torch.nn.functional.cross_entropy(logits, labels, reduction='none')
    class_terms, source_counts, candidate_counts = [], [], []
    for label in range(2):
        by_source = {}
        for i, row in enumerate(records):
            if row['label'] == label:
                by_source.setdefault(row['query']['source_sha256'], []).append(i)
        require(by_source, 'both eligibility classes required for balanced objective')
        source_means = [nll[indices].mean() for indices in by_source.values()]
        class_terms.append(torch.stack(source_means).mean())
        source_counts.append(len(by_source)); candidate_counts.append(sum(map(len, by_source.values())))
    loss = torch.stack(class_terms).mean()
    return loss, {'loss': float(loss.detach()), 'class_mean_source_nll': [float(x.detach()) for x in class_terms],
                  'class_source_counts': source_counts, 'class_candidate_counts': candidate_counts,
                  'source_count': len({r['query']['source_sha256'] for r in records}), 'candidate_count': len(records)}


def _manifests(training, tuning):
    return {key: {'sha256': digest(rows), 'count': len(rows), 'sources': len({r['source_sha256'] for r in rows}),
                  'groups': len({r['group_id'] for r in rows})} for key, rows in (('training', training), ('tuning', tuning))}


def build_checkpoint(parent_payload, training_rows, tuning_rows, *, arm, seed, parent_file_sha256):
    """Caller must authenticate parent_file_sha256 against the actual carrier file."""
    _splits(training_rows, tuning_rows)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'authenticated parent file SHA required')
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
            'closed eligibility checkpoint required')
    require(checkpoint['authority'] == AUTHORITY and all(x is False for x in checkpoint['authority'].values())
            and checkpoint['formula_admission'] is False, 'eligibility authority escalation')
    require(checkpoint['implementation'] == producer_pins(), 'eligibility producer binding differs')
    require(len(span._raw(checkpoint)) <= MAX_CHECKPOINT_BYTES, 'eligibility checkpoint exceeds128MiB')
    config = checkpoint['config']
    require(type(config) is dict and {'arm', 'seed'} <= set(config)
            and span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'eligibility configuration differs')
    for key in ('parent_payload_sha256', 'parent_file_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid provenance hash')
    original = checkpoint['parent']
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
        optimizer.zero_grad(set_to_none=True); model.train(); logits = model(batch)
        loss, parts = objective(torch, logits, batch)
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


class TemporalEventEligibility:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint_sha256 = digest(checkpoint)
        self.encoder_batch_forwards = 0
        self.encoder_source_evaluations = 0

    def predict_many(self, queries):
        require(type(queries) in (list, tuple) and 0 < len(queries) <= 64, 'bounded source-only prediction batch required')
        records = [_query(row) for row in queries]
        require(len({r['query']['id'] for r in records}) == len(records), 'duplicate inference candidate ID')
        require(len({(r['query']['source_sha256'], *r['time_tokens']) for r in records}) == len(records),
                'duplicate inference source occurrence')
        self.model.eval()
        with self.torch.no_grad():
            logits = self.model(records); probabilities = self.torch.softmax(logits, dim=-1)
        require(bool(self.torch.isfinite(logits).all()) and bool(self.torch.isfinite(probabilities).all()), 'nonfinite eligibility prediction')
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(records)
        rows = []
        for i, record in enumerate(records):
            chosen = int(probabilities[i].argmax())
            rows.append({'schema': PREDICTION_SCHEMA, 'query': copy.deepcopy(record['query']),
                         'checkpoint_sha256': self.checkpoint_sha256, 'class_order': list(CLASSES),
                         'logits': logits[i].tolist(), 'probabilities': probabilities[i].tolist(),
                         'predicted_label': CLASSES[chosen], 'confidence': float(probabilities[i, chosen]),
                         'authority': dict(AUTHORITY), 'formula_admission': False})
        return rows


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

"""Source-only temporal owner attachment over the existing source encoder.

The numerical inputs are source bytes and one proposed time interval.  Neither
gold owner inventories nor labels/IDs enter the graph.  A pointer is a proposed
source interval, not verified legal ownership.  Existing gates are unchanged.
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
from . import legal_paired_temporal_ownership as previous
parent = previous

SCHEMA = 'legal-temporal-owner-pointer-checkpoint/v1'
REPORT_SCHEMA = 'legal-temporal-owner-pointer-training-report/v1'
ARMS = ('frozen_encoder', 'finetune_encoder')
CLASSES = previous.CLASSES
SOURCE_KEYS = previous.SOURCE_KEYS
TRAIN_KEYS = SOURCE_KEYS | {'label', 'group_id', 'owner_anchor_span'}
FALSE = previous.FALSE
THRESHOLD = .8
MAX_ROWS = 4096
MAX_STEPS = 300
CLASS_SALT = 1000003
require = previous.require
digest = previous.digest
span = previous.span
_torch = previous._torch
_query = previous._query
source_queries = previous.source_queries


def producer_pins():
    return previous.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def project_training_rows(rows):
    return [{key: row[key] for key in TRAIN_KEYS} for row in rows]


def _records(rows):
    require(type(rows) in (list, tuple) and 4 <= len(rows) <= MAX_ROWS, 'bounded supervised query inventory required')
    records, ids, occurrences = [], set(), set()
    for row in rows:
        require(type(row) is dict and set(row) == TRAIN_KEYS, 'closed seven-field pointer target required')
        require(row['label'] in CLASSES and type(row['group_id']) is str and 0 < len(row['group_id']) <= 256,
                'declared label and bounded provenance group required')
        record = _query({key: row[key] for key in SOURCE_KEYS})
        occurrence = (row['source_sha256'], *record['time_tokens'])
        require(row['id'] not in ids and occurrence not in occurrences, 'duplicate ID/source occurrence')
        ids.add(row['id']); occurrences.add(occurrence)
        anchor = row['owner_anchor_span']; interval = None
        if row['label'] == 'ambiguous':
            require(anchor is None, 'ambiguous target must not assert a unique owner anchor')
        else:
            require(type(anchor) is dict and set(anchor) == {'char_start', 'char_end'}, 'unique owner requires closed exact interval')
            a, b = anchor['char_start'], anchor['char_end']
            require(type(a) is int and type(b) is int and 0 <= a < b <= len(row['source_text']), 'invalid owner interval')
            starts = {t['start']: i for i, t in enumerate(record['tokens'])}
            ends = {t['end']: i for i, t in enumerate(record['tokens'])}
            require(a in starts and b in ends, 'owner interval must align with source token boundaries')
            interval = (starts[a], ends[b]); qa, qb = record['time_tokens']
            require(interval[0] <= interval[1] and (interval[1] < qa or interval[0] > qb), 'owner interval overlaps proposed time')
        records.append({**record, 'label': CLASSES.index(row['label']), 'group_id': row['group_id'], 'owner_tokens': interval})
    return records


def _splits(training, tuning):
    train, tune = _records(training), _records(tuning)
    for field in ('id', 'source_sha256', 'group_id'):
        require(not {r[field] for r in training} & {r[field] for r in tuning}, 'training/tuning overlap: ' + field)
    require(all(sum(r['label'] == c for r in train) >= 6 for c in range(4)), 'training needs at least six examples per class')
    return train, tune


def _config(arm, seed):
    require(arm in ARMS and type(seed) is int and seed in (1730, 1731), 'declared arm and seed required')
    return {'arm': arm, 'seed': seed, 'batch_size': 24, 'class_order': list(CLASSES), 'class_batch_count': 6,
            'head_learning_rate': .001, 'encoder_learning_rate': .0001, 'max_steps': MAX_STEPS, 'gradient_clip': 5.,
            'pointer_hidden': 32, 'pointer_input': 'token_state64/source_mean64/time_start64/time_end64/time_mean64',
            'objective': 'mean_type_CE + 0.5*(mean_unique_start_CE + mean_unique_end_CE)',
            'endpoint_mask': 'valid_source_tokens_excluding_proposed_time', 'pointer_loss_weight': .5,
            'sampler': 'six_each_class_sorted_query_ID_epoch_shuffle_seed_plus_class_salt_plus_epoch/v1',
            'class_shuffle_salt': CLASS_SALT, 'device': 'cpu', 'dtype': 'float32',
            'type_threshold': THRESHOLD, 'span_threshold': THRESHOLD, 'decode_dtype': 'float64',
            'span_inventory': 'all_ordered_source_token_pairs_wholly_before_or_after_query',
            'parent_optimizer_moments_transferred': False}


def _model(torch, parent, config):
    _, warm, _ = previous._restore(parent)
    require(parent['config']['arm'] == 'mixed_occurrences' and parent['config']['seed'] == config['seed']
            and parent['optimizer_steps'] == 200 and parent['cumulative_owner_head_updates'] == 400,
            'exact seed-matched mixed200 owner-type parent required')

    class OwnerPointerModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source = warm.source; self.head = warm.head
            self.source.requires_grad_(False); self.head.requires_grad_(True)
            if config['arm'] == 'finetune_encoder': self.source.encoder.requires_grad_(True)
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(config['seed'])
                self.pointer_start = torch.nn.Sequential(torch.nn.Linear(320, 32), torch.nn.Tanh(), torch.nn.Linear(32, 1))
                self.pointer_end = torch.nn.Sequential(torch.nn.Linear(320, 32), torch.nn.Tanh(), torch.nn.Linear(32, 1))

        def features(self, records):
            captured = []
            handle = self.source.encoder.register_forward_hook(lambda _module, _args, output: captured.append(output[0]))
            try: self.source(*span._batch(torch, records))
            finally: handle.remove()
            require(len(captured) == 1, 'exactly one inherited encoder forward required')
            encoded, lengths = torch.nn.utils.rnn.pad_packed_sequence(captured[0], batch_first=True)
            mask = torch.arange(encoded.shape[1])[None, :] < lengths[:, None]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            starts = torch.stack([encoded[i, row['time_tokens'][0]] for i, row in enumerate(records)])
            ends = torch.stack([encoded[i, row['time_tokens'][1]] for i, row in enumerate(records)])
            means = torch.stack([encoded[i, row['time_tokens'][0]:row['time_tokens'][1]+1].mean(0) for i, row in enumerate(records)])
            return encoded, torch.cat((pooled, starts, ends, means), dim=1)

        def forward(self, records):
            encoded, query = self.features(records)
            features = torch.cat((encoded, query[:, None, :].expand(-1, encoded.shape[1], -1)), dim=-1)
            return self.head(query), self.pointer_start(features).squeeze(-1), self.pointer_end(features).squeeze(-1)

    return OwnerPointerModel()


def _optimizer(torch, model, config):
    heads = list(model.head.parameters()) + list(model.pointer_start.parameters()) + list(model.pointer_end.parameters())
    groups = [{'params': heads, 'lr': config['head_learning_rate']}]
    if config['arm'] == 'finetune_encoder':
        groups.append({'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']})
    return torch.optim.Adam(groups, foreach=False)


def batch_indices(records, seed, step):
    require(type(seed) is int and seed in (1730, 1731) and type(step) is int and 0 <= step < MAX_STEPS, 'bounded seed/update required')
    result = []
    for label in range(4):
        pool = sorted((i for i, r in enumerate(records) if r['label'] == label), key=lambda i: records[i]['query']['id'])
        require(len(pool) >= 6, 'six distinct class examples required')
        for position in range(6 * step, 6 * step + 6):
            epoch, offset = divmod(position, len(pool))
            order = list(pool); random.Random(seed + CLASS_SALT * label + epoch).shuffle(order)
            result.append(order[offset])
    return result


def objective(torch, logits, start_logits, end_logits, records):
    n = len(records)
    require(n > 0 and logits.shape == (n, 4) and start_logits.ndim == 2 and start_logits.shape == end_logits.shape
            and start_logits.shape[0] == n, 'type and endpoint logit shapes differ')
    require(all(bool(torch.isfinite(x).all()) for x in (logits, start_logits, end_logits)), 'nonfinite logits')
    labels = torch.tensor([r['label'] for r in records], dtype=torch.long)
    require(bool(((labels >= 0) & (labels < 4)).all()), 'invalid labels')
    ce = torch.nn.functional.cross_entropy(logits, labels)
    unique = [i for i, row in enumerate(records) if row['label'] != 3]
    valid = torch.zeros_like(start_logits, dtype=torch.bool)
    for i, row in enumerate(records):
        length = len(row['tokens']); a, b = row['time_tokens']
        require(0 <= a <= b < length <= start_logits.shape[1], 'invalid source/query mask')
        valid[i, :length] = True; valid[i, a:b+1] = False
        require((row['owner_tokens'] is None) == (row['label'] == 3), 'ambiguity/pointer target mismatch')
        if row['owner_tokens'] is not None:
            u, v = row['owner_tokens']
            require(0 <= u <= v < length and (v < a or u > b), 'invalid unique owner target')
    if unique:
        starts = torch.tensor([records[i]['owner_tokens'][0] for i in unique], dtype=torch.long)
        ends = torch.tensor([records[i]['owner_tokens'][1] for i in unique], dtype=torch.long)
        start_ce = torch.nn.functional.cross_entropy(start_logits[unique].masked_fill(~valid[unique], -torch.inf), starts)
        end_ce = torch.nn.functional.cross_entropy(end_logits[unique].masked_fill(~valid[unique], -torch.inf), ends)
    else:
        start_ce = start_logits.sum() * 0.; end_ce = end_logits.sum() * 0.
    loss = ce + .5 * (start_ce + end_ce)
    parts = {'type_ce': float(ce.detach()), 'start_ce': float(start_ce.detach()), 'end_ce': float(end_ce.detach()),
             'unique_count': len(unique), 'ambiguous_count': n - len(unique), 'query_count': n,
             'class_counts': [int((labels == i).sum()) for i in range(4)],
             'endpoint_valid_counts': valid.sum(1).tolist(), 'pointer_loss_weight': .5, 'loss': float(loss.detach())}
    return loss, parts


def _manifests(training, tuning):
    return {name: {'sha256': digest(rows), 'count': len(rows)} for name, rows in [('training', training), ('tuning', tuning)]}


def build_checkpoint(parent_payload, training_rows, tuning_rows, *, arm, seed, parent_file_sha256):
    """Caller must authenticate parent bytes against an external expected SHA."""
    config = _config(arm, seed); torch = _torch(); _splits(training_rows, tuning_rows)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'parent file SHA required')
    model = _model(torch, parent_payload, config); optimizer = _optimizer(torch, model, config)
    weights, moments = span._pack(model, optimizer)
    require(all(span._raw(weights[k]) == span._raw(v) for k, v in parent_payload['model_state'].items()), 'inherited warm tensors differ')
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'parent': copy.deepcopy(parent_payload),
            'parent_payload_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
            'model_config': copy.deepcopy(parent_payload['model_config']), 'config': config,
            'manifests': _manifests(training_rows, tuning_rows), 'initial_state_sha256': digest(weights),
            'model_state': weights, 'optimizer_state': moments, 'optimizer_steps': 0,
            'parent_owner_head_updates': 400, 'cumulative_owner_head_updates': 400,
            'preceding_checkpoint_sha256': None, **FALSE}


def _restore(checkpoint):
    fields = {'schema', 'implementation', 'parent', 'parent_payload_sha256', 'parent_file_sha256', 'model_config', 'config',
              'manifests', 'initial_state_sha256', 'model_state', 'optimizer_state', 'optimizer_steps',
              'parent_owner_head_updates', 'cumulative_owner_head_updates', 'preceding_checkpoint_sha256', *FALSE}
    require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint['schema'] == SCHEMA, 'closed pointer checkpoint required')
    require(all(checkpoint[k] is False for k in FALSE) and checkpoint['implementation'] == producer_pins(), 'authority or producer drift')
    require(len(span._raw(checkpoint)) <= 128*1024*1024, 'checkpoint exceeds128MiB')
    config = checkpoint['config']; require(span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'training config differs')
    parent = checkpoint['parent']; torch = _torch(); model = _model(torch, parent, config)
    require(checkpoint['parent_payload_sha256'] == digest(parent) and span._raw(checkpoint['model_config']) == span._raw(parent['model_config']), 'parent binding differs')
    for key in ('parent_file_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid provenance hash')
    require(type(checkpoint['manifests']) is dict and set(checkpoint['manifests']) == {'training', 'tuning'}, 'closed data manifests required')
    for value in checkpoint['manifests'].values():
        require(type(value) is dict and set(value) == {'sha256', 'count'} and type(value['sha256']) is str and span._SHA.fullmatch(value['sha256'])
                and type(value['count']) is int and 4 <= value['count'] <= MAX_ROWS, 'invalid data count/hash')
    steps = checkpoint['optimizer_steps']; require(type(steps) is int and 0 <= steps <= MAX_STEPS, 'invalid update count')
    require(type(checkpoint['parent_owner_head_updates']) is int and checkpoint['parent_owner_head_updates'] == 400
            and type(checkpoint['cumulative_owner_head_updates']) is int and checkpoint['cumulative_owner_head_updates'] == 400 + steps, 'update provenance differs')
    preceding = checkpoint['preceding_checkpoint_sha256']
    require(preceding is None if steps == 0 else type(preceding) is str and span._SHA.fullmatch(preceding), 'invalid checkpoint predecessor')
    optimizer = _optimizer(torch, model, config); initial, _ = span._pack(model, optimizer)
    require(digest(initial) == checkpoint['initial_state_sha256'], 'initial pointer/parent tensors differ')
    if steps == 0: require(span._raw(checkpoint['model_state']) == span._raw(initial), 'zero-update model differs')
    template = model.state_dict(); require(set(checkpoint['model_state']) == set(template), 'model tensor inventory differs')
    for name, expected in initial.items():
        if name.startswith('source.') and not (config['arm'] == 'finetune_encoder' and name.startswith('source.encoder.')):
            require(span._raw(checkpoint['model_state'][name]) == span._raw(expected), 'frozen inherited tensor changed: ' + name)
    model.load_state_dict({k: span._tensor(torch, checkpoint['model_state'][k], value.shape, k) for k, value in template.items()}, strict=True)
    parameters = {name: p for name, p in model.named_parameters() if p.requires_grad}; moments = checkpoint['optimizer_state']
    require(type(moments) is dict and set(moments) == {'schema', 'parameters'} and moments['schema'] == 'adam-default-betas-eps/v1'
            and set(moments['parameters']) == (set(parameters) if steps else set()), 'Adam trainable inventory differs')
    for name, moment in moments['parameters'].items():
        require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'} and type(moment['step']) is int and moment['step'] == steps, 'Adam counter differs')
        p = parameters[name]
        optimizer.state[p] = {'step': torch.tensor(float(steps)), 'exp_avg': span._tensor(torch, moment['exp_avg'], p.shape, name),
                              'exp_avg_sq': span._tensor(torch, moment['exp_avg_sq'], p.shape, name, nonnegative=True)}
    model.eval(); return torch, model, optimizer


def train(checkpoint, training_rows, tuning_rows, *, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional steps required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    require(span._raw(checkpoint['manifests']) == span._raw(_manifests(training_rows, tuning_rows)), 'training/tuning manifests differ')
    records, _ = _splits(training_rows, tuning_rows); config = checkpoint['config']; trace = []
    require(checkpoint['optimizer_steps'] + additional_steps <= MAX_STEPS, 'update budget exceeded')
    trainable = {name: p for name, p in model.named_parameters() if p.requires_grad}
    for step in range(checkpoint['optimizer_steps'], checkpoint['optimizer_steps'] + additional_steps):
        require(time.monotonic() - started < max_seconds, 'deadline exceeded; incomplete stage is not successful')
        indices = batch_indices(records, config['seed'], step); batch = [records[i] for i in indices]
        optimizer.zero_grad(set_to_none=True); model.train(); logits, starts, ends = model(batch)
        loss, parts = objective(torch, logits, starts, ends, batch)
        require(parts['class_counts'] == [6]*4 and parts['unique_count'] == 18, 'balanced24 batch required')
        require(bool(torch.isfinite(loss)), 'nonfinite pointer loss'); loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in trainable.values()), 'nonfinite/missing trainable gradient')
        require(all(p.grad is None for p in model.parameters() if not p.requires_grad), 'frozen parameter received gradient')
        norm = torch.nn.utils.clip_grad_norm_(list(trainable.values()), config['gradient_clip'])
        require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        trace.append({'step': step+1, 'query_ids': [r['query']['id'] for r in batch], 'labels': [r['label'] for r in batch],
                      'owner_token_spans': [list(r['owner_tokens']) if r['owner_tokens'] is not None else None for r in batch],
                      'time_token_spans': [list(r['time_tokens']) for r in batch], 'token_counts': [len(r['tokens']) for r in batch],
                      'logits': logits.detach().tolist(),
                      'pointer_start_logits': [starts[i, :len(r['tokens'])].detach().tolist() for i, r in enumerate(batch)],
                      'pointer_end_logits': [ends[i, :len(r['tokens'])].detach().tolist() for i, r in enumerate(batch)],
                      'objective_components': parts, 'loss': float(loss.detach()), 'preclip_gradient_norm': float(norm),
                      'encoder_batch_forwards': 1, 'encoder_source_evaluations': len(batch)})
        optimizer.step()
    weights, moments = span._pack(model, optimizer); steps = checkpoint['optimizer_steps'] + additional_steps
    result = {**copy.deepcopy(checkpoint), 'model_state': weights, 'optimizer_state': moments, 'optimizer_steps': steps,
              'cumulative_owner_head_updates': 400 + steps,
              'preceding_checkpoint_sha256': digest(checkpoint) if additional_steps else checkpoint['preceding_checkpoint_sha256']}
    _restore(result)
    return result, {'schema': REPORT_SCHEMA, 'initial_step': checkpoint['optimizer_steps'], 'final_step': steps,
                    'steps_executed': len(trace), 'trace': trace, 'trainable_parameters': {n: p.numel() for n, p in trainable.items()},
                    'encoder_batch_forwards': len(trace), 'encoder_source_evaluations': 24*len(trace),
                    'wall_seconds': time.monotonic()-started, 'fresh_optimizer_at_step_zero': True,
                    'parent_optimizer_moments_transferred': False, **FALSE}


def decode_span(start_logits, end_logits, time_tokens):
    """Float64 joint argmax/probability; all ordered disjoint pairs, no gold mask."""
    require(type(start_logits) is list and type(end_logits) is list and 0 < len(start_logits) == len(end_logits) <= 256,
            'bounded endpoint vectors required')
    require(all(type(x) in (int, float) and math.isfinite(x) for x in start_logits + end_logits), 'finite endpoints required')
    require(type(time_tokens) in (list, tuple) and len(time_tokens) == 2 and all(type(x) is int for x in time_tokens), 'query token pair required')
    a, b = time_tokens; n = len(start_logits); require(0 <= a <= b < n, 'invalid query tokens')
    pairs = [(i, j) for i in range(n) for j in range(i, n) if j < a or i > b]
    if not pairs: return {'raw_owner_token_span': None, 'span_confidence': None, 'valid_span_count': 0}
    values = [float(start_logits[i]) + float(end_logits[j]) for i, j in pairs]
    best = max(range(len(values)), key=values.__getitem__); maximum = values[best]
    probability = 1. / math.fsum(math.exp(value-maximum) for value in values)
    return {'raw_owner_token_span': list(pairs[best]), 'span_confidence': probability, 'valid_span_count': len(pairs)}


class TemporalOwnerPointer:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint); self.checkpoint_sha256 = digest(checkpoint)
        self.encoder_batch_forwards = 0; self.encoder_source_evaluations = 0

    def predict_many(self, queries):
        require(type(queries) in (list, tuple) and 0 < len(queries) <= 64, 'bounded source-only prediction batch required')
        records = [_query(row) for row in queries]
        with self.torch.no_grad():
            logits, starts, ends = self.model(records); probabilities = self.torch.softmax(logits, dim=-1)
        require(all(bool(self.torch.isfinite(x).all()) for x in (logits, starts, ends, probabilities)), 'nonfinite predictions')
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(records); rows = []
        for i, record in enumerate(records):
            query = record['query']; chosen = int(probabilities[i].argmax()); confidence = float(probabilities[i, chosen])
            reason = 'predicted_ambiguous' if chosen == 3 else 'below_fixed_confidence' if confidence < THRESHOLD else None
            start = starts[i, :len(record['tokens'])].tolist(); end = ends[i, :len(record['tokens'])].tolist()
            decoded = decode_span(start, end, record['time_tokens']); owner_tokens = decoded['raw_owner_token_span']
            anchor = None if owner_tokens is None else {'char_start': record['tokens'][owner_tokens[0]]['start'],
                                                       'char_end': record['tokens'][owner_tokens[1]]['end']}
            joint_reason = ('predicted_ambiguous' if chosen == 3 else 'no_valid_owner_span' if anchor is None else
                            'below_fixed_type_confidence' if confidence < THRESHOLD else
                            'below_fixed_span_confidence' if decoded['span_confidence'] < THRESHOLD else None)
            rows.append({'id': query['id'], 'source_sha256': query['source_sha256'], 'proposed_time_span': query['proposed_time_span'],
                         'time_token_span': list(record['time_tokens']), 'logits': logits[i].tolist(), 'probabilities': probabilities[i].tolist(),
                         'predicted_label': CLASSES[chosen], 'confidence': confidence, 'status': 'deferred' if reason else 'accepted',
                         'owner_type': None if reason else CLASSES[chosen], 'reason': reason, 'pointer_start_logits': start, 'pointer_end_logits': end,
                         **decoded, 'raw_owner_anchor_span': anchor, 'joint_status': 'deferred' if joint_reason else 'accepted',
                         'joint_reason': joint_reason, 'proposed_owner_anchor_span': None if joint_reason else anchor, **FALSE})
        return rows


def save_checkpoint(checkpoint, path):
    _restore(checkpoint); path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle: json.dump(checkpoint, handle, sort_keys=True, separators=(',', ':'), allow_nan=False); handle.write('\n')
    raw = path.read_bytes(); return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'schema': SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    raw = Path(path).read_bytes(); require(len(raw) <= 128*1024*1024 and hashlib.sha256(raw).hexdigest() == expected_sha256, 'checkpoint file binding differs')
    value = json.loads(raw); _restore(value); return value

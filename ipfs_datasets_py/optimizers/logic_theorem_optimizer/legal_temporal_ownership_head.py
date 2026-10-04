"""Bounded owner-TYPE pilot over the existing legal span decoder's encoder.

Only source bytes and a supplied time occurrence reach the numerical model.
This is not a time-span detector, owner-occurrence resolver, statutory semantic
verifier, or replacement for existing decoder/scope gates. The parent decoder
is copied in full; old checkpoints and inference implementations are untouched.
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

# Must precede every torch import, including imports inside frozen helpers.
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
from . import legal_span_formula as span
from . import legal_span_mixed_replay as mixed
from . import legal_span_temporal_presence as parent_runtime

SCHEMA = 'legal-temporal-owner-type-checkpoint/v1'
CLASSES = ('norm', 'condition', 'exception', 'ambiguous')
ARMS = ('source_only', 'frozen_occurrence', 'finetune_occurrence')
SOURCE_KEYS = {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
TRAIN_KEYS = SOURCE_KEYS | {'label', 'group_id'}
MAX_ROWS = 2048
MAX_STEPS = 200
THRESHOLD = .8
FALSE = {'statutory_semantics_verified': False, 'owner_occurrence_resolved': False,
         'latent_input_enabled': False, 'pipeline_promotion': False, 'existing_gates_changed': False}
require = span._require
digest = span.checkpoint_digest


def _pins():
    return {str(Path(m.__file__).resolve()): hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in (span, mixed, mixed.grounded, mixed.dimensions, parent_runtime,
                      parent_runtime.facet, parent_runtime.facet.previous)} | {
            str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_INITIAL_PINS = _pins()


def producer_pins():
    require(_pins() == _INITIAL_PINS, 'ownership producer source drift')
    return dict(_INITIAL_PINS)


def _torch():
    import torch
    require(os.environ.get('CUDA_VISIBLE_DEVICES') == '-1', 'CUDA must be hidden before torch import')
    torch.set_num_threads(1)
    return torch


def _query(row):
    require(type(row) is dict and set(row) == SOURCE_KEYS, 'closed four-field source query required')
    text = row['source_text']
    require(type(row['id']) is str and 0 < len(row['id']) <= 256, 'bounded query ID required')
    tokens = span.tokenize_source(text)
    require(row['source_sha256'] == hashlib.sha256(text.encode()).hexdigest(), 'source hash differs')
    interval = row['proposed_time_span']
    require(type(interval) is dict and set(interval) == {'char_start', 'char_end'}, 'closed time interval required')
    a, b = interval['char_start'], interval['char_end']
    require(type(a) is int and type(b) is int and 0 <= a < b <= len(text), 'invalid time interval')
    starts, ends = {t['start']: i for i, t in enumerate(tokens)}, {t['end']: i for i, t in enumerate(tokens)}
    require(a in starts and b in ends, 'time interval must align with exact source token boundaries')
    return {'tokens': tokens, 'latent': [], 'time_tokens': (starts[a], ends[b]), 'query': copy.deepcopy(row)}


def project_training_rows(rows):
    return [{key: row[key] for key in TRAIN_KEYS} for row in rows]


def source_queries(rows):
    return [{key: row[key] for key in SOURCE_KEYS} for row in rows]


def _split(rows):
    require(type(rows) in (list, tuple) and 4 <= len(rows) <= MAX_ROWS, 'bounded complete supervised quartets required')
    records, ids, occurrences, groups = [], set(), set(), {}
    for row in rows:
        require(type(row) is dict and set(row) == TRAIN_KEYS, 'closed six-field supervised row required')
        require(row['label'] in CLASSES and type(row['group_id']) is str and 0 < len(row['group_id']) <= 256,
                'declared label and bounded group required')
        record = _query({key: row[key] for key in SOURCE_KEYS})
        occurrence = (row['source_sha256'], *record['time_tokens'])
        require(row['id'] not in ids and occurrence not in occurrences, 'duplicate query ID or source occurrence')
        ids.add(row['id']); occurrences.add(occurrence)
        record.update({'label': CLASSES.index(row['label']), 'group_id': row['group_id']})
        groups.setdefault(row['group_id'], []).append(len(records)); records.append(record)
    require(all(len(indices) == 4 and {records[i]['label'] for i in indices} == set(range(4)) for indices in groups.values()),
            'every group must contain one of each ownership class')
    return records, groups


def _splits(training, tuning):
    train, groups = _split(training); tune, _ = _split(tuning)
    for field in ('id', 'source_sha256', 'group_id'):
        require(not {r[field] for r in training} & {r[field] for r in tuning}, 'training/tuning overlap: ' + field)
    require(len(groups) >= 4, 'at least four training quartets required')
    return train, tune, groups


def _config(arm, seed):
    require(arm in ARMS and type(seed) is int and 0 <= seed < 2**31, 'invalid arm or head/sampler seed')
    return {'arm': arm, 'seed': seed, 'batch_size': 16, 'head_learning_rate': .001, 'encoder_learning_rate': .0001,
            'max_steps': MAX_STEPS, 'gradient_clip': 5., 'class_order': list(CLASSES), 'head_hidden': 32,
            'head_input': 'source_mean/time_start/time_end/time_mean; source_only repeats source_mean four times',
            'objective': 'unweighted_four_class_cross_entropy', 'sampler': 'sorted_group_ids_shuffled_each_epoch_seed_plus_epoch/v1',
            'device': 'cpu', 'dtype': 'float32', 'threshold': THRESHOLD, 'parent_optimizer_moments_transferred': False}


def _model(torch, parent, config):
    class OwnershipModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source = mixed._model(torch, parent['model_config'])
            self.source.load_state_dict({k: span._tensor(torch, parent['model_state'][k], value.shape, k)
                                        for k, value in self.source.state_dict().items()}, strict=True)
            self.source.requires_grad_(False)
            if config['arm'] == 'finetune_occurrence': self.source.encoder.requires_grad_(True)
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(config['seed'])
                self.head = torch.nn.Sequential(torch.nn.Linear(256, 32), torch.nn.Tanh(), torch.nn.Linear(32, 4))

        def features(self, records):
            # Capture the actual frozen implementation's packed GRU output.
            # No copied byte/token encoder forward math and no label/ID feature.
            captured = []
            handle = self.source.encoder.register_forward_hook(lambda _module, _args, output: captured.append(output[0]))
            try:
                self.source(*span._batch(torch, records))
            finally:
                handle.remove()
            require(len(captured) == 1, 'exactly one inherited encoder forward required')
            encoded, lengths = torch.nn.utils.rnn.pad_packed_sequence(captured[0], batch_first=True)
            mask = torch.arange(encoded.shape[1])[None, :] < lengths[:, None]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            if config['arm'] == 'source_only': return pooled.repeat(1, 4)
            starts = torch.stack([encoded[i, row['time_tokens'][0]] for i, row in enumerate(records)])
            ends = torch.stack([encoded[i, row['time_tokens'][1]] for i, row in enumerate(records)])
            means = torch.stack([encoded[i, row['time_tokens'][0]:row['time_tokens'][1]+1].mean(0) for i, row in enumerate(records)])
            return torch.cat((pooled, starts, ends, means), dim=1)

        def forward(self, records):
            return self.head(self.features(records))

    return OwnershipModel()


def _optimizer(torch, model, config):
    groups = [{'params': list(model.head.parameters()), 'lr': config['head_learning_rate']}]
    if config['arm'] == 'finetune_occurrence':
        groups.append({'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']})
    return torch.optim.Adam(groups, foreach=False)


def batch_indices(groups, seed, step):
    require(type(step) is int and 0 <= step < MAX_STEPS, 'bounded zero-based update required')
    names = sorted(groups); chosen = []
    for position in range(step * 4, (step+1) * 4):
        epoch, index = divmod(position, len(names))
        order = list(names); random.Random(seed + epoch).shuffle(order)
        chosen.append(order[index])
    return [i for group in chosen for i in groups[group]], chosen


def build_checkpoint(parent_payload, training_rows, tuning_rows, *, arm, seed, parent_file_sha256):
    """Build from an externally authenticated parent file and its parsed payload.

    The caller must verify that ``parent_file_sha256`` authenticates the file
    from which ``parent_payload`` was parsed. A self-asserted SHA is not proof
    of origin. The experiment runner binds the exact predeclared parent file.
    """
    torch = _torch(); parent_runtime.validate_checkpoint(parent_payload)
    require('torch_version' not in parent_payload['model_config'] or parent_payload['model_config']['torch_version'] == torch.__version__,
            'parent numerical torch version differs')
    require(parent_payload['model_config']['latent_dimension'] == 0 and parent_payload['model_config']['trigger_enabled'] is True
            and parent_payload['model_config']['hidden_size'] == 32 and parent_payload['model_config']['embedding_dim'] == 16,
            'existing 64-dimensional source-only grounding encoder required')
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'parent file SHA required')
    _splits(training_rows, tuning_rows)
    config = _config(arm, seed); parent = copy.deepcopy(parent_payload)
    model = _model(torch, parent, config); optimizer = _optimizer(torch, model, config)
    weights, moments = span._pack(model, optimizer)
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'parent': parent, 'parent_payload_sha256': digest(parent),
            'parent_file_sha256': parent_file_sha256, 'model_config': copy.deepcopy(parent['model_config']),
            'config': config, 'training_manifest_sha256': digest(training_rows), 'tuning_manifest_sha256': digest(tuning_rows),
            'training_count': len(training_rows), 'tuning_count': len(tuning_rows), 'initial_state_sha256': digest(weights),
            'model_state': weights, 'optimizer_state': moments, 'optimizer_steps': 0, 'preceding_checkpoint_sha256': None, **FALSE}


def _restore(checkpoint):
    torch = _torch()
    fields = {'schema', 'implementation', 'parent', 'parent_payload_sha256', 'parent_file_sha256', 'model_config', 'config',
              'training_manifest_sha256', 'tuning_manifest_sha256', 'training_count', 'tuning_count', 'initial_state_sha256',
              'model_state', 'optimizer_state', 'optimizer_steps', 'preceding_checkpoint_sha256', *FALSE}
    require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint['schema'] == SCHEMA, 'closed ownership checkpoint required')
    require(all(checkpoint[k] is False for k in FALSE) and checkpoint['implementation'] == producer_pins(), 'authority or producer drift')
    require(len(span._raw(checkpoint)) <= 128*1024*1024, 'checkpoint exceeds128MiB')
    parent = checkpoint['parent']; parent_runtime.validate_checkpoint(parent)
    require(checkpoint['parent_payload_sha256'] == digest(parent) and span._raw(checkpoint['model_config']) == span._raw(parent['model_config']), 'parent binding differs')
    require(parent['model_config']['latent_dimension'] == 0 and parent['model_config']['trigger_enabled'] is True
            and parent['model_config']['hidden_size'] == 32 and parent['model_config']['embedding_dim'] == 16,
            'existing 64-dimensional source-only grounding encoder required')
    require('torch_version' not in parent['model_config'] or parent['model_config']['torch_version'] == torch.__version__,
            'parent numerical torch version differs')
    for key in ('parent_file_sha256', 'training_manifest_sha256', 'tuning_manifest_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid manifest hash')
    for key in ('training_count', 'tuning_count'):
        require(type(checkpoint[key]) is int and 4 <= checkpoint[key] <= MAX_ROWS and checkpoint[key] % 4 == 0, 'invalid split count')
    config = checkpoint['config']; require(span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'training config differs')
    steps = checkpoint['optimizer_steps']; require(type(steps) is int and 0 <= steps <= MAX_STEPS, 'invalid optimizer steps')
    preceding = checkpoint['preceding_checkpoint_sha256']
    require(preceding is None if steps == 0 else type(preceding) is str and span._SHA.fullmatch(preceding), 'invalid checkpoint predecessor')
    model = _model(torch, parent, config); optimizer = _optimizer(torch, model, config)
    initial, _ = span._pack(model, optimizer)
    require(digest(initial) == checkpoint['initial_state_sha256'], 'initial head/source tensors differ')
    if steps == 0: require(span._raw(checkpoint['model_state']) == span._raw(initial), 'zero-update model differs')
    template = model.state_dict(); require(set(checkpoint['model_state']) == set(template), 'model tensor inventory differs')
    for name, expected in initial.items():
        if name.startswith('source.') and not (config['arm'] == 'finetune_occurrence' and name.startswith('source.encoder.')):
            require(span._raw(checkpoint['model_state'][name]) == span._raw(expected), 'frozen parent tensor changed: ' + name)
    model.load_state_dict({k: span._tensor(torch, checkpoint['model_state'][k], value.shape, k) for k,value in template.items()}, strict=True)
    parameters = {name: p for name,p in model.named_parameters() if p.requires_grad}
    moments = checkpoint['optimizer_state']
    require(type(moments) is dict and set(moments) == {'schema','parameters'} and moments['schema'] == 'adam-default-betas-eps/v1'
            and set(moments['parameters']) == (set(parameters) if steps else set()), 'Adam trainable inventory differs')
    for name, moment in moments['parameters'].items():
        require(type(moment) is dict and set(moment) == {'step','exp_avg','exp_avg_sq'} and type(moment['step']) is int and moment['step'] == steps,
                'Adam counter differs')
        p = parameters[name]
        optimizer.state[p] = {'step': torch.tensor(float(steps)), 'exp_avg': span._tensor(torch,moment['exp_avg'],p.shape,name),
                              'exp_avg_sq': span._tensor(torch,moment['exp_avg_sq'],p.shape,name,nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def train(checkpoint, training_rows, tuning_rows, *, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional steps required')
    require(type(max_seconds) in (int,float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    require(checkpoint['training_manifest_sha256'] == digest(training_rows) and checkpoint['tuning_manifest_sha256'] == digest(tuning_rows),
            'training/tuning manifest changed')
    records, _, groups = _splits(training_rows, tuning_rows)
    require(checkpoint['optimizer_steps'] + additional_steps <= MAX_STEPS, 'optimizer budget exceeded')
    trace = []; config = checkpoint['config']
    trainable = {name:p for name,p in model.named_parameters() if p.requires_grad}
    for step in range(checkpoint['optimizer_steps'], checkpoint['optimizer_steps'] + additional_steps):
        require(time.monotonic() - started < max_seconds, 'training deadline exceeded; incomplete stage is not successful')
        indices, selected_groups = batch_indices(groups, config['seed'], step)
        batch = [records[i] for i in indices]; labels = torch.tensor([r['label'] for r in batch], dtype=torch.long)
        assert [int((labels==i).sum()) for i in range(4)] == [4]*4
        optimizer.zero_grad(set_to_none=True); model.train(); logits = model(batch)
        loss = torch.nn.functional.cross_entropy(logits, labels)
        require(bool(torch.isfinite(loss)), 'nonfinite ownership loss'); loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in trainable.values()), 'nonfinite/missing trainable gradient')
        require(all(p.grad is None for p in model.parameters() if not p.requires_grad), 'frozen parameter received gradient')
        norm = torch.nn.utils.clip_grad_norm_(list(trainable.values()), 5.)
        require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        trace.append({'step': step+1, 'query_ids': [r['query']['id'] for r in batch], 'group_ids': selected_groups,
                      'labels': labels.tolist(), 'logits': logits.detach().tolist(), 'loss': float(loss.detach()),
                      'class_counts': [4]*4, 'preclip_gradient_norm': float(norm), 'encoder_batch_forwards': 1,
                      'encoder_source_evaluations': len(batch)})
        optimizer.step()
    weights, moments = span._pack(model, optimizer)
    result = {**copy.deepcopy(checkpoint), 'model_state': weights, 'optimizer_state': moments,
              'optimizer_steps': checkpoint['optimizer_steps'] + additional_steps,
              'preceding_checkpoint_sha256': digest(checkpoint) if additional_steps else checkpoint['preceding_checkpoint_sha256']}
    _restore(result)
    return result, {'schema': 'legal-temporal-owner-type-training-report/v1', 'steps_executed': len(trace),
                    'initial_step': checkpoint['optimizer_steps'], 'final_step': result['optimizer_steps'], 'trace': trace,
                    'trainable_parameters': {name:p.numel() for name,p in trainable.items()},
                    'encoder_batch_forwards': len(trace), 'encoder_source_evaluations': 16*len(trace),
                    'wall_seconds': time.monotonic()-started, 'fresh_optimizer_at_step_zero': True,
                    'parent_optimizer_moments_transferred': False, **FALSE}


class TemporalOwnershipHead:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint_sha256 = digest(checkpoint)
        self.encoder_batch_forwards = 0; self.encoder_source_evaluations = 0

    def predict_many(self, queries):
        require(type(queries) in (list,tuple) and 0 < len(queries) <= 64, 'bounded source-only prediction batch required')
        records = [_query(row) for row in queries]
        with self.torch.no_grad(): logits = self.model(records); probabilities = self.torch.softmax(logits,dim=-1)
        require(bool(self.torch.isfinite(logits).all()) and bool(self.torch.isfinite(probabilities).all()), 'nonfinite predictions')
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(records)
        rows = []
        for index, record in enumerate(records):
            query = record['query']; chosen = int(probabilities[index].argmax()); confidence = float(probabilities[index,chosen])
            reason = 'predicted_ambiguous' if chosen == 3 else 'below_fixed_confidence' if confidence < THRESHOLD else None
            rows.append({'id':query['id'], 'source_sha256':query['source_sha256'], 'proposed_time_span':query['proposed_time_span'],
                         'time_token_span':list(record['time_tokens']), 'logits':logits[index].tolist(), 'probabilities':probabilities[index].tolist(),
                         'predicted_label':CLASSES[chosen], 'confidence':confidence, 'status':'deferred' if reason else 'accepted',
                         'owner_type':None if reason else CLASSES[chosen], 'reason':reason, **FALSE})
        return rows


def save_checkpoint(checkpoint, path):
    _restore(checkpoint); path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as handle: json.dump(checkpoint,handle,sort_keys=True,separators=(',',':'),allow_nan=False);handle.write('\n')
    raw=path.read_bytes();return {'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'schema':SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    raw=Path(path).read_bytes();require(len(raw)<=128*1024*1024 and hashlib.sha256(raw).hexdigest()==expected_sha256,'checkpoint file binding differs')
    value=json.loads(raw);_restore(value);return value

"""Matched continuations of the existing occurrence-aware owner-TYPE head.

The original model graph and prediction wire are reused unchanged. Query IDs,
sampling units, groups and labels control batching/supervision, never numerical
features. This experiment does not resolve owner occurrences or override gates.
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path
import random
import time

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
from . import legal_temporal_ownership_head as previous

SCHEMA = 'legal-paired-temporal-owner-type-checkpoint/v1'
REPORT_SCHEMA = 'legal-paired-temporal-owner-type-training-report/v1'
ARMS = ('single_replay', 'mixed_occurrences', 'ambiguity_weighted')
CLASSES = previous.CLASSES
SOURCE_KEYS = previous.SOURCE_KEYS
TRAIN_KEYS = previous.TRAIN_KEYS
FALSE = previous.FALSE
THRESHOLD = previous.THRESHOLD
MAX_STEPS = 200
MAX_ROWS = 2048
UNIT_SALT = 1000003
require = previous.require
digest = previous.digest
span = previous.span
_torch = previous._torch
_query = previous._query
source_queries = previous.source_queries
project_training_rows = previous.project_training_rows


def producer_pins():
    return previous.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _config(arm, seed):
    require(arm in ARMS and type(seed) is int and seed in (1730, 1731), 'declared arm and sampler seed required')
    return {'arm': arm, 'seed': seed, 'batch_size': 24, 'head_learning_rate': .001,
            'encoder_learning_rate': .0001, 'max_steps': MAX_STEPS, 'gradient_clip': 5.,
            'class_order': list(CLASSES), 'ambiguity_class_weight': 2.,
            'loss_normalization': 'sum weighted target NLL / sum target class weights',
            'sampler': 'six single quartets per step; mixed replaces last three with one complete12-query unit/v1',
            'unit_shuffle_salt': UNIT_SALT, 'device': 'cpu', 'dtype': 'float32',
            'threshold': THRESHOLD, 'parent_optimizer_moments_transferred': False}


def _records(rows):
    require(type(rows) in (list, tuple) and 4 <= len(rows) <= MAX_ROWS, 'bounded supervised query inventory required')
    records, ids, occurrences = [], set(), set()
    for row in rows:
        require(type(row) is dict and set(row) == TRAIN_KEYS, 'closed six-field supervised query required')
        require(row['label'] in CLASSES and type(row['group_id']) is str and 0 < len(row['group_id']) <= 256,
                'declared owner class and bounded group required')
        record = _query({key: row[key] for key in SOURCE_KEYS})
        occurrence = (row['source_sha256'], *record['time_tokens'])
        require(row['id'] not in ids and occurrence not in occurrences, 'duplicate query ID or source occurrence')
        ids.add(row['id']); occurrences.add(occurrence)
        records.append({**record, 'label': CLASSES.index(row['label']), 'group_id': row['group_id']})
    return records


def _units(rows, records, units):
    require(type(units) is list and len(units) >= 1, 'nonempty paired sampling units required')
    lookup = {row['id']: index for index, row in enumerate(rows)}
    sources = {}
    for row in rows: sources.setdefault(row['source_sha256'], set()).add(row['id'])
    require(all(len(ids) in (2, 3) for ids in sources.values()), 'paired sources require exactly two or three proposed occurrences')
    result, all_ids = {}, []
    for unit in units:
        require(type(unit) is dict and set(unit) == {'unit_id', 'query_ids'}, 'closed sampling unit required')
        name, ids = unit['unit_id'], unit['query_ids']
        require(type(name) is str and 0 < len(name) <= 256 and name not in result, 'unique bounded sampling unit ID required')
        require(type(ids) is list and len(ids) == len(set(ids)) == 12 and all(identity in lookup for identity in ids),
                'sampling unit requires twelve unique inventory queries')
        indices = [lookup[identity] for identity in ids]
        require([sum(records[i]['label'] == c for i in indices) for c in range(4)] == [3] * 4,
                'sampling unit requires three queries per ownership class')
        selected = set(ids)
        require(all(sources[rows[i]['source_sha256']] <= selected for i in indices), 'sampling unit splits a multi-occurrence source')
        result[name] = indices; all_ids.extend(ids)
    require(len(all_ids) == len(set(all_ids)) == len(rows) and set(all_ids) == set(lookup), 'sampling units must exhaust paired inventory exactly once')
    return result


def _splits(single_training, paired_training, sampling_units, single_tuning, paired_tuning):
    singles, groups = previous._split(single_training)
    require(len(groups) >= 6, 'at least six historical single quartets required')
    pairs = _records(paired_training); units = _units(paired_training, pairs, sampling_units)
    old_tune, _ = previous._split(single_tuning); new_tune = _records(paired_tuning)
    pools = [single_training, paired_training, single_tuning, paired_tuning]
    for i, left in enumerate(pools):
        for right in pools[i + 1:]:
            for key in ('id', 'source_sha256', 'group_id'):
                require(not {row[key] for row in left} & {row[key] for row in right}, 'source/query/group split overlap: ' + key)
    return {'single_training': singles, 'paired_training': pairs, 'single_groups': groups,
            'paired_units': units, 'single_tuning': old_tune, 'paired_tuning': new_tune}


def _manifests(single_training, paired_training, sampling_units, single_tuning, paired_tuning):
    pools = {'single_training': single_training, 'paired_training': paired_training,
             'sampling_units': sampling_units, 'single_tuning': single_tuning, 'paired_tuning': paired_tuning}
    return {name: {'sha256': digest(rows), 'count': len(rows)} for name, rows in pools.items()}


def _draw_names(mapping, seed, position, count):
    names = sorted(mapping); result = []
    for cursor in range(position, position + count):
        epoch, index = divmod(cursor, len(names))
        order = list(names); random.Random(seed + epoch).shuffle(order)
        result.append(order[index])
    return result


def batch_indices(single_groups, paired_units, seed, step, arm):
    require(type(step) is int and 0 <= step < MAX_STEPS, 'bounded zero-based update required')
    _config(arm, seed)
    single_names = _draw_names(single_groups, seed, 6 * step, 6)
    unit_names = []
    if arm != 'single_replay':
        single_names = single_names[:3]
        unit_names = _draw_names(paired_units, seed + UNIT_SALT, step, 1)
    return {'single_indices': [index for name in single_names for index in single_groups[name]],
            'paired_indices': [index for name in unit_names for index in paired_units[name]],
            'single_group_ids': single_names, 'paired_unit_ids': unit_names}


def objective(torch, logits, labels, arm):
    require(arm in ARMS and logits.ndim == 2 and logits.shape[1] == 4 and labels.shape == (logits.shape[0],),
            'four-class logits and one target per query required')
    require(labels.dtype == torch.long and logits.shape[0] > 0 and bool(((labels >= 0) & (labels < 4)).all()), 'valid nonempty class targets required')
    require(bool(torch.isfinite(logits).all()), 'nonfinite ownership logits')
    nll = torch.logsumexp(logits, dim=1) - logits.gather(1, labels[:, None]).squeeze(1)
    weights = torch.where(labels == 3, torch.full_like(nll, 2.), torch.ones_like(nll))
    standard = nll.mean(); weighted = (nll * weights).sum() / weights.sum()
    loss = weighted if arm == 'ambiguity_weighted' else standard
    parts = {'standard_ce': float(standard.detach()), 'ambiguity_weighted_ce': float(weighted.detach()),
             'standard_nll_sum': float(nll.detach().sum()), 'weighted_nll_sum': float((nll * weights).detach().sum()),
             'ambiguous_nll_sum': float(nll[labels == 3].detach().sum()), 'weighted_denominator': float(weights.detach().sum()),
             'class_counts': [int((labels == index).sum()) for index in range(4)],
             'applied_class_weights': [1., 1., 1., 2.] if arm == 'ambiguity_weighted' else [1.] * 4,
             'objective': 'ambiguity_weighted_ce' if arm == 'ambiguity_weighted' else 'standard_ce', 'loss': float(loss.detach())}
    return loss, parts


def _optimizer(torch, model, config):
    return torch.optim.Adam([{'params': list(model.head.parameters()), 'lr': config['head_learning_rate']},
                             {'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']}], foreach=False)


def _warm_model(parent, seed):
    torch, model, _ = previous._restore(parent)
    require(parent['config']['arm'] == 'finetune_occurrence' and parent['config']['seed'] == seed and parent['optimizer_steps'] == 200,
            'exact seed-matched occurrence-finetuned200 parent required')
    return torch, model


def build_checkpoint(parent_payload, single_training, paired_training, sampling_units, single_tuning, paired_tuning, *, arm, seed, parent_file_sha256):
    """Caller must externally authenticate the declared parent's file SHA."""
    config = _config(arm, seed); torch, model = _warm_model(parent_payload, seed)
    _splits(single_training, paired_training, sampling_units, single_tuning, paired_tuning)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'parent file SHA required')
    optimizer = _optimizer(torch, model, config); weights, moments = span._pack(model, optimizer)
    require(span._raw(weights) == span._raw(parent_payload['model_state']), 'warm initial tensors differ')
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'parent': copy.deepcopy(parent_payload),
            'parent_payload_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
            'model_config': copy.deepcopy(parent_payload['model_config']), 'config': config,
            'manifests': _manifests(single_training, paired_training, sampling_units, single_tuning, paired_tuning),
            'initial_state_sha256': digest(weights), 'model_state': weights, 'optimizer_state': moments,
            'optimizer_steps': 0, 'parent_owner_head_updates': 200, 'cumulative_owner_head_updates': 200,
            'preceding_checkpoint_sha256': None, **FALSE}


def _restore(checkpoint):
    fields = {'schema', 'implementation', 'parent', 'parent_payload_sha256', 'parent_file_sha256', 'model_config', 'config',
              'manifests', 'initial_state_sha256', 'model_state', 'optimizer_state', 'optimizer_steps',
              'parent_owner_head_updates', 'cumulative_owner_head_updates', 'preceding_checkpoint_sha256', *FALSE}
    require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint['schema'] == SCHEMA, 'closed paired ownership checkpoint required')
    require(all(checkpoint[key] is False for key in FALSE) and checkpoint['implementation'] == producer_pins(), 'authority or producer drift')
    require(len(span._raw(checkpoint)) <= 128 * 1024 * 1024, 'checkpoint exceeds128MiB')
    config = checkpoint['config']; require(span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'training config differs')
    parent = checkpoint['parent']; torch, model = _warm_model(parent, config['seed'])
    require(checkpoint['parent_payload_sha256'] == digest(parent) and span._raw(checkpoint['model_config']) == span._raw(parent['model_config']), 'parent binding differs')
    for key in ('parent_file_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid parent/state hash')
    manifests = checkpoint['manifests']
    require(type(manifests) is dict and set(manifests) == {'single_training', 'paired_training', 'sampling_units', 'single_tuning', 'paired_tuning'}, 'closed manifest inventory required')
    for key, value in manifests.items():
        require(type(value) is dict and set(value) == {'sha256', 'count'} and type(value['sha256']) is str and span._SHA.fullmatch(value['sha256'])
                and type(value['count']) is int and 1 <= value['count'] <= MAX_ROWS, 'invalid manifest count/hash')
    require(manifests['paired_training']['count'] == 12 * manifests['sampling_units']['count'], 'paired unit count differs')
    steps = checkpoint['optimizer_steps']; require(type(steps) is int and 0 <= steps <= MAX_STEPS, 'invalid optimizer steps')
    require(type(checkpoint['parent_owner_head_updates']) is int and checkpoint['parent_owner_head_updates'] == 200
            and type(checkpoint['cumulative_owner_head_updates']) is int and checkpoint['cumulative_owner_head_updates'] == 200 + steps, 'owner-head update provenance differs')
    preceding = checkpoint['preceding_checkpoint_sha256']
    require(preceding is None if steps == 0 else type(preceding) is str and span._SHA.fullmatch(preceding), 'invalid checkpoint predecessor')
    initial = parent['model_state']; require(digest(initial) == checkpoint['initial_state_sha256'], 'warm initial state differs')
    if steps == 0: require(span._raw(checkpoint['model_state']) == span._raw(initial), 'zero-update model differs')
    template = model.state_dict(); require(set(checkpoint['model_state']) == set(template), 'model tensor inventory differs')
    for name, expected in initial.items():
        if not name.startswith(('source.encoder.', 'head.')):
            require(span._raw(checkpoint['model_state'][name]) == span._raw(expected), 'frozen source/decoder tensor changed: ' + name)
    model.load_state_dict({name: span._tensor(torch, checkpoint['model_state'][name], value.shape, name) for name, value in template.items()}, strict=True)
    optimizer = _optimizer(torch, model, config)
    trainable = {name: parameter for name, parameter in model.named_parameters() if parameter.requires_grad}
    require(all(name.startswith(('head.', 'source.encoder.')) for name in trainable), 'trainable parameter scope differs')
    moments = checkpoint['optimizer_state']
    require(type(moments) is dict and set(moments) == {'schema', 'parameters'} and moments['schema'] == 'adam-default-betas-eps/v1'
            and set(moments['parameters']) == (set(trainable) if steps else set()), 'fresh/resumed Adam inventory differs')
    for name, moment in moments['parameters'].items():
        require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'} and type(moment['step']) is int and moment['step'] == steps, 'Adam counter differs')
        parameter = trainable[name]
        optimizer.state[parameter] = {'step': torch.tensor(float(steps)),
            'exp_avg': span._tensor(torch, moment['exp_avg'], parameter.shape, name),
            'exp_avg_sq': span._tensor(torch, moment['exp_avg_sq'], parameter.shape, name, nonnegative=True)}
    model.eval(); return torch, model, optimizer


def train(checkpoint, single_training, paired_training, sampling_units, single_tuning, paired_tuning, *, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional updates required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    args = (single_training, paired_training, sampling_units, single_tuning, paired_tuning)
    require(span._raw(checkpoint['manifests']) == span._raw(_manifests(*args)), 'training/tuning/unit manifests changed')
    data = _splits(*args); config = checkpoint['config']; trace = []
    require(checkpoint['optimizer_steps'] + additional_steps <= MAX_STEPS, 'optimizer budget exceeded')
    trainable = {name: parameter for name, parameter in model.named_parameters() if parameter.requires_grad}
    for step in range(checkpoint['optimizer_steps'], checkpoint['optimizer_steps'] + additional_steps):
        require(time.monotonic() - started < max_seconds, 'training deadline exceeded; incomplete stage is not successful')
        chosen = batch_indices(data['single_groups'], data['paired_units'], config['seed'], step, config['arm'])
        batch = [data['single_training'][i] for i in chosen['single_indices']] + [data['paired_training'][i] for i in chosen['paired_indices']]
        labels = torch.tensor([row['label'] for row in batch], dtype=torch.long)
        require(len(batch) == 24 and [int((labels == i).sum()) for i in range(4)] == [6] * 4, 'balanced24 batch required')
        optimizer.zero_grad(set_to_none=True); model.train(); logits = model(batch)
        loss, parts = objective(torch, logits, labels, config['arm'])
        require(bool(torch.isfinite(loss)), 'nonfinite ownership objective'); loss.backward()
        require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in trainable.values()), 'nonfinite/missing trainable gradient')
        require(all(parameter.grad is None for parameter in model.parameters() if not parameter.requires_grad), 'frozen parameter received gradient')
        norm = torch.nn.utils.clip_grad_norm_(list(trainable.values()), config['gradient_clip'])
        require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        trace.append({'step': step + 1, 'query_ids': [row['query']['id'] for row in batch],
            'single_group_ids': chosen['single_group_ids'], 'paired_unit_ids': chosen['paired_unit_ids'],
            'pool_counts': {'single': len(chosen['single_indices']), 'paired': len(chosen['paired_indices'])},
            'labels': labels.tolist(), 'logits': logits.detach().tolist(), 'objective_components': parts,
            'loss': parts['loss'], 'class_counts': [6] * 4, 'preclip_gradient_norm': float(norm),
            'encoder_batch_forwards': 1, 'encoder_source_evaluations': 24})
        optimizer.step()
    weights, moments = span._pack(model, optimizer); steps = checkpoint['optimizer_steps'] + additional_steps
    result = {**copy.deepcopy(checkpoint), 'model_state': weights, 'optimizer_state': moments,
              'optimizer_steps': steps, 'cumulative_owner_head_updates': 200 + steps,
              'preceding_checkpoint_sha256': digest(checkpoint) if additional_steps else checkpoint['preceding_checkpoint_sha256']}
    _restore(result)
    return result, {'schema': REPORT_SCHEMA, 'steps_executed': len(trace), 'initial_step': checkpoint['optimizer_steps'],
        'final_step': steps, 'trace': trace, 'trainable_parameters': {name: parameter.numel() for name, parameter in trainable.items()},
        'encoder_batch_forwards': len(trace), 'encoder_source_evaluations': 24 * len(trace),
        'wall_seconds': time.monotonic() - started, 'fresh_optimizer_at_step_zero': True,
        'parent_optimizer_moments_transferred': False, **FALSE}


class PairedTemporalOwnershipHead(previous.TemporalOwnershipHead):
    """Reuse the frozen predecessor's exact source-only prediction wire."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint_sha256 = digest(checkpoint)
        self.encoder_batch_forwards = 0; self.encoder_source_evaluations = 0


def save_checkpoint(checkpoint, path):
    import json
    _restore(checkpoint); path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(checkpoint, stream, sort_keys=True, separators=(',', ':'), allow_nan=False); stream.write('\n')
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'schema': SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    import json
    raw = Path(path).read_bytes()
    require(len(raw) <= 128 * 1024 * 1024 and hashlib.sha256(raw).hexdigest() == expected_sha256, 'checkpoint file binding differs')
    checkpoint = json.loads(raw); _restore(checkpoint); return checkpoint

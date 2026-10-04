"""Matched placement-curriculum continuations of the occurrence-aware owner-TYPE head.

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
from . import legal_paired_temporal_ownership as previous

SCHEMA = 'legal-placement-temporal-owner-type-checkpoint/v1'
REPORT_SCHEMA = 'legal-placement-temporal-owner-type-training-report/v1'
ARMS = ('continuation', 'placement')
CLASSES = previous.CLASSES
SOURCE_KEYS = previous.SOURCE_KEYS
TRAIN_KEYS = previous.TRAIN_KEYS
FALSE = previous.FALSE
THRESHOLD = previous.THRESHOLD
MAX_STEPS = 200
MAX_ROWS = 2048
UNIT_SALT = 1000003
PLACEMENT_SALT = 2000003
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
    require(arm in ARMS and type(seed) is int and seed in (1730,1731), 'declared arm and sampler seed required')
    return {'arm':arm, 'seed':seed, 'batch_size':24, 'head_learning_rate':.001,
            'encoder_learning_rate':.0001, 'max_steps':MAX_STEPS, 'gradient_clip':5.,
            'class_order':list(CLASSES), 'class_weights':[1.,1.,1.,1.],
            'loss_normalization':'mean four-class cross entropy over all24queries',
            'sampler':'three continuous old quartets; old paired unit each step; placement replaces odd zero-based steps with new unit/v1',
            'unit_shuffle_salt':UNIT_SALT, 'placement_shuffle_salt':PLACEMENT_SALT,
            'device':'cpu', 'dtype':'float32', 'threshold':THRESHOLD,
            'parent_optimizer_moments_transferred':False}


_records = previous._records
_units = previous._units


def _splits(single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units,
            single_tuning, prior_paired_tuning, placement_tuning):
    old = previous._splits(single_training, prior_paired_training, prior_sampling_units, single_tuning, prior_paired_tuning)
    placed = _records(placement_training); units = _units(placement_training, placed, sampling_units)
    new_tune = _records(placement_tuning)
    pools = [single_training, prior_paired_training, placement_training, single_tuning, prior_paired_tuning, placement_tuning]
    for i,left in enumerate(pools):
        for right in pools[i+1:]:
            for key in ('id','source_sha256','group_id'):
                require(not {r[key] for r in left} & {r[key] for r in right}, 'source/query/group split overlap: '+key)
    return {'single_training':old['single_training'], 'single_groups':old['single_groups'],
            'prior_paired_training':old['paired_training'], 'prior_paired_units':old['paired_units'],
            'placement_training':placed, 'placement_units':units,
            'single_tuning':old['single_tuning'], 'prior_paired_tuning':old['paired_tuning'], 'placement_tuning':new_tune}


INPUT_KEYS = ('single_training','prior_paired_training','prior_sampling_units','placement_training','sampling_units',
              'single_tuning','prior_paired_tuning','placement_tuning')


def _manifests(*args):
    require(len(args)==len(INPUT_KEYS), 'exact eight data/unit inputs required')
    return {name:{'sha256':digest(rows),'count':len(rows)} for name,rows in zip(INPUT_KEYS,args)}


def _draw_names(mapping, seed, position, count):
    names = sorted(mapping); result = []
    for cursor in range(position, position + count):
        epoch, index = divmod(cursor, len(names))
        order = list(names); random.Random(seed + epoch).shuffle(order)
        result.append(order[index])
    return result


def batch_indices(single_groups, prior_paired_units, placement_units, seed, step, arm):
    require(type(step) is int and 0 <= step < MAX_STEPS, 'bounded zero-based update required')
    _config(arm,seed)
    groups = _draw_names(single_groups,seed,3*step,3)
    use_new = arm=='placement' and step%2==1
    old_names = [] if use_new else _draw_names(prior_paired_units,seed+UNIT_SALT,step,1)
    new_names = _draw_names(placement_units,seed+PLACEMENT_SALT,step//2,1) if use_new else []
    return {'single_indices':[i for name in groups for i in single_groups[name]],
            'prior_paired_indices':[i for name in old_names for i in prior_paired_units[name]],
            'placement_indices':[i for name in new_names for i in placement_units[name]],
            'single_group_ids':groups, 'prior_paired_unit_ids':old_names, 'placement_unit_ids':new_names}


def objective(torch,logits,labels,arm):
    require(arm in ARMS, 'declared placement arm required')
    # Exact inherited standard CE, with the same diagnostic weighted calculation
    # in both arms. No ambiguity weight is applied in this study.
    return previous.objective(torch,logits,labels,'mixed_occurrences')


def _optimizer(torch, model, config):
    return torch.optim.Adam([{'params': list(model.head.parameters()), 'lr': config['head_learning_rate']},
                             {'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']}], foreach=False)


def _warm_model(parent, seed):
    torch, model, _ = previous._restore(parent)
    require(parent['config']['arm'] == 'mixed_occurrences' and parent['config']['seed'] == seed and parent['optimizer_steps'] == 200,
            'exact seed-matched paired-mixed200 parent required')
    return torch, model


def build_checkpoint(parent_payload, single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning, *, arm, seed, parent_file_sha256):
    """Caller must externally authenticate the declared parent's file SHA."""
    config = _config(arm, seed); torch, model = _warm_model(parent_payload, seed)
    _splits(single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'parent file SHA required')
    optimizer = _optimizer(torch, model, config); weights, moments = span._pack(model, optimizer)
    require(span._raw(weights) == span._raw(parent_payload['model_state']), 'warm initial tensors differ')
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'parent': copy.deepcopy(parent_payload),
            'parent_payload_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
            'model_config': copy.deepcopy(parent_payload['model_config']), 'config': config,
            'manifests': _manifests(single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning),
            'initial_state_sha256': digest(weights), 'model_state': weights, 'optimizer_state': moments,
            'optimizer_steps': 0, 'parent_owner_head_updates': 400, 'cumulative_owner_head_updates': 400,
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
    require(type(manifests) is dict and set(manifests) == set(INPUT_KEYS), 'closed manifest inventory required')
    for key, value in manifests.items():
        require(type(value) is dict and set(value) == {'sha256', 'count'} and type(value['sha256']) is str and span._SHA.fullmatch(value['sha256'])
                and type(value['count']) is int and 1 <= value['count'] <= MAX_ROWS, 'invalid manifest count/hash')
    require(manifests['prior_paired_training']['count'] == 12 * manifests['prior_sampling_units']['count']
            and manifests['placement_training']['count'] == 12 * manifests['sampling_units']['count'], 'paired unit count differs')
    steps = checkpoint['optimizer_steps']; require(type(steps) is int and 0 <= steps <= MAX_STEPS, 'invalid optimizer steps')
    require(type(checkpoint['parent_owner_head_updates']) is int and checkpoint['parent_owner_head_updates'] == 400
            and type(checkpoint['cumulative_owner_head_updates']) is int and checkpoint['cumulative_owner_head_updates'] == 400 + steps, 'owner-head update provenance differs')
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


def train(checkpoint, single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning, *, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional updates required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    args = (single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning)
    require(span._raw(checkpoint['manifests']) == span._raw(_manifests(*args)), 'training/tuning/unit manifests changed')
    data = _splits(*args); config = checkpoint['config']; trace = []
    require(checkpoint['optimizer_steps'] + additional_steps <= MAX_STEPS, 'optimizer budget exceeded')
    trainable = {name: parameter for name, parameter in model.named_parameters() if parameter.requires_grad}
    for step in range(checkpoint['optimizer_steps'], checkpoint['optimizer_steps'] + additional_steps):
        require(time.monotonic() - started < max_seconds, 'training deadline exceeded; incomplete stage is not successful')
        chosen = batch_indices(data['single_groups'], data['prior_paired_units'], data['placement_units'], config['seed'], step, config['arm'])
        batch = ([data['single_training'][i] for i in chosen['single_indices']]
                 + [data['prior_paired_training'][i] for i in chosen['prior_paired_indices']]
                 + [data['placement_training'][i] for i in chosen['placement_indices']])
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
            'single_group_ids':chosen['single_group_ids'], 'prior_paired_unit_ids':chosen['prior_paired_unit_ids'], 'placement_unit_ids':chosen['placement_unit_ids'],
            'pool_counts':{'single':len(chosen['single_indices']), 'prior_paired':len(chosen['prior_paired_indices']), 'placement':len(chosen['placement_indices'])},
            'labels': labels.tolist(), 'logits': logits.detach().tolist(), 'objective_components': parts,
            'loss': parts['loss'], 'class_counts': [6] * 4, 'preclip_gradient_norm': float(norm),
            'encoder_batch_forwards': 1, 'encoder_source_evaluations': 24})
        optimizer.step()
    weights, moments = span._pack(model, optimizer); steps = checkpoint['optimizer_steps'] + additional_steps
    result = {**copy.deepcopy(checkpoint), 'model_state': weights, 'optimizer_state': moments,
              'optimizer_steps': steps, 'cumulative_owner_head_updates': 400 + steps,
              'preceding_checkpoint_sha256': digest(checkpoint) if additional_steps else checkpoint['preceding_checkpoint_sha256']}
    _restore(result)
    return result, {'schema': REPORT_SCHEMA, 'steps_executed': len(trace), 'initial_step': checkpoint['optimizer_steps'],
        'final_step': steps, 'trace': trace, 'trainable_parameters': {name: parameter.numel() for name, parameter in trainable.items()},
        'encoder_batch_forwards': len(trace), 'encoder_source_evaluations': 24 * len(trace),
        'wall_seconds': time.monotonic() - started, 'fresh_optimizer_at_step_zero': True,
        'parent_optimizer_moments_transferred': False, **FALSE}


class TemporalPlacementHead(previous.PairedTemporalOwnershipHead):
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

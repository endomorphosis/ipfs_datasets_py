"""Matched stability interventions on placement-curriculum continuations of the occurrence-aware owner-TYPE head.

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
from . import legal_temporal_placement as baseline
previous = baseline.previous

SCHEMA = 'legal-stability-temporal-owner-type-checkpoint/v1'
REPORT_SCHEMA = 'legal-stability-temporal-owner-type-training-report/v1'
ARMS = ('placement_ce', 'placement_kl', 'placement_head_only')
TEMPERATURE = 2.0
KL_WEIGHT = 1.0
CACHE_SCHEMA = 'legal-temporal-stability-teacher-cache/v1'
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
    return baseline.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _config(arm, seed):
    require(arm in ARMS and type(seed) is int and seed in (1730,1731), 'declared arm and sampler seed required')
    return {'arm':arm, 'seed':seed, 'batch_size':24, 'head_learning_rate':.001,
            'encoder_learning_rate':.0001, 'max_steps':MAX_STEPS, 'gradient_clip':5.,
            'class_order':list(CLASSES), 'class_weights':[1.,1.,1.,1.],
            'loss_normalization':'mean four-class cross entropy over all24queries',
            'sampler':'three continuous old quartets; old paired unit each step; placement replaces odd zero-based steps with new unit/v1',
            'unit_shuffle_salt':UNIT_SALT, 'placement_shuffle_salt':PLACEMENT_SALT,
            'device':'cpu', 'dtype':'float32', 'threshold':THRESHOLD,
            'parent_optimizer_moments_transferred':False,
            'teacher_temperature':TEMPERATURE, 'teacher_kl_weight':KL_WEIGHT if arm=='placement_kl' else 0.0,
            'teacher_mask':'old TRAIN only and ordinary parent argmax equals gold; no confidence threshold',
            'teacher_normalization':'T squared times mean KL(parent/T || student/T) over eligible old rows; zero if none',
            'source_gru_trainable':arm!='placement_head_only'}


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
    use_new = step%2==1
    old_names = [] if use_new else _draw_names(prior_paired_units,seed+UNIT_SALT,step,1)
    new_names = _draw_names(placement_units,seed+PLACEMENT_SALT,step//2,1) if use_new else []
    return {'single_indices':[i for name in groups for i in single_groups[name]],
            'prior_paired_indices':[i for name in old_names for i in prior_paired_units[name]],
            'placement_indices':[i for name in new_names for i in placement_units[name]],
            'single_group_ids':groups, 'prior_paired_unit_ids':old_names, 'placement_unit_ids':new_names}


def objective(torch, logits, labels, teacher_logits, teacher_eligible_mask, arm):
    """Frozen-TRAIN teacher target; no gradients enter the teacher/cache."""
    require(arm in ARMS, 'declared stability arm required')
    require(logits.ndim == 2 and logits.shape[1] == 4 and labels.shape == (len(logits),), 'four-class batch required')
    require(teacher_logits.shape == logits.shape and teacher_eligible_mask.shape == labels.shape
            and teacher_eligible_mask.dtype == torch.bool, 'teacher tensor/mask shape differs')
    require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(teacher_logits).all()), 'finite logits required')
    ce, parts = previous.objective(torch, logits, labels, 'mixed_occurrences')
    target_log = torch.nn.functional.log_softmax(teacher_logits.detach() / TEMPERATURE, dim=1)
    student_log = torch.nn.functional.log_softmax(logits / TEMPERATURE, dim=1)
    per_row = (target_log.exp() * (target_log - student_log)).sum(1)
    count = int(teacher_eligible_mask.sum())
    total_kl = per_row[teacher_eligible_mask].sum()
    mean_kl = total_kl / count if count else logits.sum() * 0.0
    scaled = TEMPERATURE ** 2 * mean_kl
    weight = KL_WEIGHT if arm == 'placement_kl' else 0.0
    # Returning CE directly keeps control gradients exactly the old placement objective.
    loss = ce + weight * scaled if weight else ce
    return loss, {**parts, 'cross_entropy':float(ce.detach()), 'teacher_kl_sum':float(total_kl.detach()),
        'teacher_eligible_count':count, 'teacher_kl_mean':float(mean_kl.detach()),
        'teacher_temperature':TEMPERATURE, 'teacher_scaled_kl':float(scaled.detach()),
        'applied_kl_weight':weight, 'objective':'standard_ce_plus_teacher_kl' if weight else 'standard_ce',
        'loss':float(loss.detach())}


def _trainability(model, config):
    model.requires_grad_(False); model.head.requires_grad_(True)
    if config['source_gru_trainable']: model.source.encoder.requires_grad_(True)


def _optimizer(torch, model, config):
    _trainability(model, config)
    groups = [{'params':list(model.head.parameters()),'lr':config['head_learning_rate']}]
    if config['source_gru_trainable']:
        groups.append({'params':list(model.source.encoder.parameters()),'lr':config['encoder_learning_rate']})
    return torch.optim.Adam(groups, foreach=False)


def cache_reference(cache, reference):
    require(type(reference) is dict and set(reference)=={'path','sha256','bytes'}
            and type(reference['path']) is str and type(reference['sha256']) is str
            and span._SHA.fullmatch(reference['sha256']) and type(reference['bytes']) is int
            and 0 < reference['bytes'] <= 16*1024*1024, 'authenticated teacher file reference required')
    return {'reference':copy.deepcopy(reference),'payload_sha256':digest(cache)}


def validate_teacher_cache(cache, parent, single_training, prior_paired_training, *, seed, parent_file_sha256):
    fields={'schema','implementation','seed','parent_file_sha256','parent_payload_sha256','training_manifests',
            'sources_sha256','class_order','batch_size','rows','teacher_state_before_sha256','teacher_state_after_sha256',
            'teacher_requires_grad','teacher_gradients_absent','encoder_batch_forwards','encoder_source_evaluations',
            'labels_used_only_for_correctness_mask','new_placement_rows_included',*FALSE}
    require(type(cache) is dict and set(cache)==fields and cache['schema']==CACHE_SCHEMA,'closed teacher cache required')
    require(cache['implementation']==producer_pins() and type(cache['seed']) is int and cache['seed']==seed, 'teacher producer/seed differs')
    require(cache['parent_file_sha256']==parent_file_sha256 and cache['parent_payload_sha256']==digest(parent), 'teacher parent differs')
    rows=list(single_training)+list(prior_paired_training)
    expected={'single_training':{'sha256':digest(single_training),'count':len(single_training)},
              'prior_paired_training':{'sha256':digest(prior_paired_training),'count':len(prior_paired_training)}}
    require(span._raw(cache['training_manifests'])==span._raw(expected) and cache['sources_sha256']==digest(source_queries(rows)), 'teacher TRAIN inventory differs')
    require(cache['class_order']==list(CLASSES) and type(cache['batch_size']) is int and cache['batch_size']==48, 'teacher batching/class order differs')
    require(cache['teacher_state_before_sha256']==cache['teacher_state_after_sha256']==digest(parent['model_state'])
            and cache['teacher_requires_grad'] is False and cache['teacher_gradients_absent'] is True, 'teacher was not immutable')
    require(type(cache['encoder_source_evaluations']) is int and cache['encoder_source_evaluations']==len(rows)
            and type(cache['encoder_batch_forwards']) is int and cache['encoder_batch_forwards']==math.ceil(len(rows)/48), 'teacher numerical counters differ')
    require(cache['labels_used_only_for_correctness_mask'] is True and cache['new_placement_rows_included'] is False
            and all(cache[k] is False for k in FALSE), 'teacher authority/mask scope differs')
    require(type(cache['rows']) is list and len(cache['rows'])==len(rows),'complete teacher row inventory required')
    torch=_torch(); result={}
    for expected,row in zip(rows,cache['rows']):
        require(type(row) is dict and set(row)=={'id','source_sha256','proposed_time_span','label','logits','correct'}, 'closed teacher row required')
        require(all(span._raw(row[k])==span._raw(expected[k]) for k in ('id','source_sha256','proposed_time_span','label')), 'teacher source/label/order mismatch')
        require(type(row['logits']) is list and len(row['logits'])==4 and all(type(v) is float and math.isfinite(v) for v in row['logits']), 'finite float32 teacher logits required')
        logits=torch.tensor(row['logits'],dtype=torch.float32)
        require(logits.tolist()==row['logits'] and type(row['correct']) is bool
                and row['correct']==(int(logits.argmax())==CLASSES.index(expected['label'])), 'teacher logit precision/correctness differs')
        require(row['id'] not in result,'duplicate teacher ID');result[row['id']]=row
    return result


def build_teacher_cache(parent, single_training, prior_paired_training, *, seed, parent_file_sha256):
    torch,model=_warm_model(parent,seed);model.requires_grad_(False);model.eval()
    rows=list(single_training)+list(prior_paired_training);records=_records(rows);outputs=[]
    initial=digest({k:v.detach().tolist() for k,v in model.state_dict().items()})
    with torch.no_grad():
        for begin in range(0,len(rows),48):
            values=model(records[begin:begin+48]).tolist()
            for row,logits in zip(rows[begin:begin+48],values):
                outputs.append({k:copy.deepcopy(row[k]) for k in ('id','source_sha256','proposed_time_span','label')} |
                    {'logits':logits,'correct':max(range(4),key=lambda i:logits[i])==CLASSES.index(row['label'])})
    final=digest({k:v.detach().tolist() for k,v in model.state_dict().items()})
    cache={'schema':CACHE_SCHEMA,'implementation':producer_pins(),'seed':seed,'parent_file_sha256':parent_file_sha256,
      'parent_payload_sha256':digest(parent),'training_manifests':{name:{'sha256':digest(values),'count':len(values)}
          for name,values in (('single_training',single_training),('prior_paired_training',prior_paired_training))},
      'sources_sha256':digest(source_queries(rows)),'class_order':list(CLASSES),'batch_size':48,'rows':outputs,
      'teacher_state_before_sha256':initial,'teacher_state_after_sha256':final,
      'teacher_requires_grad':any(p.requires_grad for p in model.parameters()),
      'teacher_gradients_absent':all(p.grad is None for p in model.parameters()),
      'encoder_batch_forwards':math.ceil(len(rows)/48),'encoder_source_evaluations':len(rows),
      'labels_used_only_for_correctness_mask':True,'new_placement_rows_included':False,**FALSE}
    validate_teacher_cache(cache,parent,single_training,prior_paired_training,seed=seed,parent_file_sha256=parent_file_sha256)
    return cache


def _warm_model(parent, seed):
    torch, model, _ = previous._restore(parent)
    require(parent['config']['arm'] == 'mixed_occurrences' and parent['config']['seed'] == seed and parent['optimizer_steps'] == 200,
            'exact seed-matched paired-mixed200 parent required')
    return torch, model


def build_checkpoint(parent_payload, single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning, *, arm, seed, parent_file_sha256, teacher_cache, teacher_cache_ref):
    """Caller must externally authenticate the declared parent's file SHA."""
    config = _config(arm, seed); torch, model = _warm_model(parent_payload, seed)
    _splits(single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'parent file SHA required')
    validate_teacher_cache(teacher_cache,parent_payload,single_training,prior_paired_training,seed=seed,parent_file_sha256=parent_file_sha256)
    binding=cache_reference(teacher_cache,teacher_cache_ref)
    optimizer = _optimizer(torch, model, config); weights, moments = span._pack(model, optimizer)
    require(span._raw(weights) == span._raw(parent_payload['model_state']), 'warm initial tensors differ')
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'teacher_cache':binding, 'parent': copy.deepcopy(parent_payload),
            'parent_payload_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
            'model_config': copy.deepcopy(parent_payload['model_config']), 'config': config,
            'manifests': _manifests(single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning),
            'initial_state_sha256': digest(weights), 'model_state': weights, 'optimizer_state': moments,
            'optimizer_steps': 0, 'parent_owner_head_updates': 400, 'cumulative_owner_head_updates': 400,
            'preceding_checkpoint_sha256': None, **FALSE}


def _restore(checkpoint):
    fields = {'schema', 'implementation', 'parent', 'parent_payload_sha256', 'parent_file_sha256', 'model_config', 'config',
              'manifests', 'teacher_cache', 'initial_state_sha256', 'model_state', 'optimizer_state', 'optimizer_steps',
              'parent_owner_head_updates', 'cumulative_owner_head_updates', 'preceding_checkpoint_sha256', *FALSE}
    require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint['schema'] == SCHEMA, 'closed paired ownership checkpoint required')
    require(all(checkpoint[key] is False for key in FALSE) and checkpoint['implementation'] == producer_pins(), 'authority or producer drift')
    require(len(span._raw(checkpoint)) <= 128 * 1024 * 1024, 'checkpoint exceeds128MiB')
    config = checkpoint['config']; require(span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'training config differs')
    parent = checkpoint['parent']; torch, model = _warm_model(parent, config['seed'])
    require(checkpoint['parent_payload_sha256'] == digest(parent) and span._raw(checkpoint['model_config']) == span._raw(parent['model_config']), 'parent binding differs')
    for key in ('parent_file_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid parent/state hash')
    binding=checkpoint['teacher_cache']
    require(type(binding) is dict and set(binding)=={'reference','payload_sha256'} and type(binding['payload_sha256']) is str
            and span._SHA.fullmatch(binding['payload_sha256']), 'teacher binding differs')
    cache_reference({},binding['reference'])
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
        if not name.startswith('head.') and not (config['source_gru_trainable'] and name.startswith('source.encoder.')):
            require(span._raw(checkpoint['model_state'][name]) == span._raw(expected), 'frozen source/decoder tensor changed: ' + name)
    model.load_state_dict({name: span._tensor(torch, checkpoint['model_state'][name], value.shape, name) for name, value in template.items()}, strict=True)
    optimizer = _optimizer(torch, model, config)
    trainable = {name: parameter for name, parameter in model.named_parameters() if parameter.requires_grad}
    require(set(trainable)=={name for name in template if name.startswith('head.') or (config['source_gru_trainable'] and name.startswith('source.encoder.'))}, 'trainable parameter scope differs')
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


def train(checkpoint, single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning, *, teacher_cache, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional updates required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    args = (single_training, prior_paired_training, prior_sampling_units, placement_training, sampling_units, single_tuning, prior_paired_tuning, placement_tuning)
    require(span._raw(checkpoint['manifests']) == span._raw(_manifests(*args)), 'training/tuning/unit manifests changed')
    data = _splits(*args); config = checkpoint['config']; trace = []
    require(digest(teacher_cache)==checkpoint['teacher_cache']['payload_sha256'],'teacher cache payload changed')
    cached=validate_teacher_cache(teacher_cache,checkpoint['parent'],single_training,prior_paired_training,
        seed=config['seed'],parent_file_sha256=checkpoint['parent_file_sha256'])
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
        teacher_rows=[cached.get(row['query']['id']) for row in batch]
        teacher_values=[row['logits'] if row is not None else [0.0]*4 for row in teacher_rows]
        teacher_mask=[row is not None and row['correct'] for row in teacher_rows]
        teacher_tensor=torch.tensor(teacher_values,dtype=logits.dtype)
        loss, parts = objective(torch, logits, labels, teacher_tensor, torch.tensor(teacher_mask,dtype=torch.bool), config['arm'])
        require(bool(torch.isfinite(loss)), 'nonfinite ownership objective'); loss.backward()
        require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in trainable.values()), 'nonfinite/missing trainable gradient')
        require(all(parameter.grad is None for parameter in model.parameters() if not parameter.requires_grad), 'frozen parameter received gradient')
        norm = torch.nn.utils.clip_grad_norm_(list(trainable.values()), config['gradient_clip'])
        require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        trace.append({'step': step + 1, 'query_ids': [row['query']['id'] for row in batch],
            'single_group_ids':chosen['single_group_ids'], 'prior_paired_unit_ids':chosen['prior_paired_unit_ids'], 'placement_unit_ids':chosen['placement_unit_ids'],
            'pool_counts':{'single':len(chosen['single_indices']), 'prior_paired':len(chosen['prior_paired_indices']), 'placement':len(chosen['placement_indices'])},
            'teacher_cached_mask':[row is not None for row in teacher_rows], 'teacher_eligible_mask':teacher_mask,
            'teacher_eligible_ids':[row['query']['id'] for row,flag in zip(batch,teacher_mask) if flag],
            'teacher_logits':teacher_values, 'labels': labels.tolist(), 'logits': logits.detach().tolist(), 'objective_components': parts,
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
        'parent_optimizer_moments_transferred': False, 'teacher_cache':checkpoint['teacher_cache'],
        'teacher_encoder_batch_forwards':0,'teacher_cache_batch_uses':len(trace), **FALSE}


class TemporalStabilityHead(previous.PairedTemporalOwnershipHead):
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

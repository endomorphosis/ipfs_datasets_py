"""Coupled source-token attachment; authored other-owner spans are loss-only.

All numerical inference inputs remain source text plus its proposed time span.
The endpoint arm preserves its warm graph and freezes the zero interaction;
joint arms add a query-conditioned low-rank interaction and joint supervision.
Thus endpoint-to-joint is a bundled change; joint-to-contrast isolates the
extra training loss. No generated span authorizes a legal formula or gate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
from . import legal_temporal_owner_pointer as parent

SCHEMA = 'legal-temporal-coupled-span-checkpoint/v1'
REPORT_SCHEMA = 'legal-temporal-coupled-span-training-report/v1'
ARMS = ('endpoint', 'joint_span', 'joint_contrast')
CLASSES = parent.CLASSES
SOURCE_KEYS = parent.SOURCE_KEYS
TRAIN_KEYS = parent.TRAIN_KEYS
FALSE = parent.FALSE
MAX_ROWS = parent.MAX_ROWS
MAX_STEPS = 200
RANK = 8
SCALE = 1. / math.sqrt(RANK)
THRESHOLD = .8
CLASS_SALT = parent.CLASS_SALT
INTERACTION_SEED_SALT = 3000003
require = parent.require
digest = parent.digest
span = parent.span
_torch = parent._torch
_query = parent._query
_records = parent._records
source_queries = parent.source_queries
project_training_rows = parent.project_training_rows


def producer_pins():
    return parent.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _contrasts(rows, records, training_contrasts):
    require(type(training_contrasts) is dict and set(training_contrasts) == {r['id'] for r in rows}, 'complete query-indexed contrast inventory required')
    output = []
    for row, record in zip(rows, records):
        item = training_contrasts[row['id']]
        require(type(item) is dict and set(item) == {'id', 'source_sha256', 'proposed_time_span', 'negative_owner_spans'}, 'closed source-bound contrast row required')
        require(item['id'] == row['id'] and item['source_sha256'] == row['source_sha256']
                and span._raw(item['proposed_time_span']) == span._raw(row['proposed_time_span']), 'contrast source/query identity differs')
        values = item['negative_owner_spans']; require(type(values) is list and len(values) <= 256, 'bounded contrast span list required')
        require(not values if record['label'] == 3 else True, 'ambiguous queries cannot supervise a unique contrastive owner')
        starts = {t['start']: i for i, t in enumerate(record['tokens'])}; ends = {t['end']: i for i, t in enumerate(record['tokens'])}
        coordinates, negatives = [], []
        qa, qb = record['time_tokens']
        for value in values:
            require(type(value) is dict and set(value) == {'char_start', 'char_end'}, 'closed negative owner interval required')
            a, b = value['char_start'], value['char_end']
            require(type(a) is int and type(b) is int and 0 <= a < b <= len(row['source_text']) and a in starts and b in ends,
                    'negative owner must be an exact whole-token source interval')
            interval = (starts[a], ends[b])
            require(interval[0] <= interval[1] and (interval[1] < qa or interval[0] > qb), 'negative owner overlaps queried time')
            require(interval != record['owner_tokens'], 'gold owner cannot be a negative')
            coordinates.append((a, b)); negatives.append(interval)
        require(coordinates == sorted(set(coordinates)), 'negative owner coordinates must be sorted and unique')
        output.append({**record, 'negative_owner_tokens': negatives})
    return output


def _splits(training, tuning, training_contrasts):
    records, tune = parent._splits(training, tuning)
    return _contrasts(training, records, training_contrasts), tune


def _config(arm, seed):
    require(arm in ARMS and type(seed) is int and seed in (1730, 1731), 'declared coupled arm/seed required')
    return {'arm': arm, 'seed': seed, 'batch_size': 24, 'class_order': list(CLASSES), 'class_batch_count': 6,
            'head_learning_rate': .001, 'encoder_learning_rate': .0001, 'max_steps': MAX_STEPS, 'gradient_clip': 5.,
            'interaction_rank': RANK, 'interaction_scale': SCALE, 'interaction_input': 'token64/source_mean64/time_start64/time_end64/time_mean64',
            'interaction_initialization': 'start_projection_zero; end_projection_normal_std1/sqrt320_bias0',
            'interaction_seed_salt': INTERACTION_SEED_SALT, 'interaction_enabled': arm != 'endpoint',
            'pointer_loss_weight': .5, 'contrast_loss_weight': .25 if arm == 'joint_contrast' else 0.,
            'contrast_normalization': 'mean gold-vs-distinct-other-owner NLL over unique queries with at least one negative; empty zero',
            'selection_nll': 'mean_type_NLL + mean_unique_valid_joint_span_NLL; no contrast',
            'sampler': 'six_each_class_sorted_query_ID_epoch_shuffle_seed_plus_class_salt_plus_epoch/v1',
            'class_shuffle_salt': CLASS_SALT, 'device': 'cpu', 'dtype': 'float32',
            'type_threshold': THRESHOLD, 'span_threshold': THRESHOLD, 'decode_dtype': 'float64',
            'span_inventory': 'all_ordered_source_token_pairs_wholly_before_or_after_query',
            'parent_optimizer_moments_transferred': False}


def _model(torch, checkpoint, config):
    _, warm, _ = parent._restore(checkpoint)
    require(checkpoint['config']['arm'] == 'finetune_encoder' and checkpoint['config']['seed'] == config['seed']
            and checkpoint['optimizer_steps'] == 300 and checkpoint['cumulative_owner_head_updates'] == 700,
            'exact seed-matched pointer finetune300 parent required')

    class CoupledModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source = warm.source; self.head = warm.head
            self.pointer_start = warm.pointer_start; self.pointer_end = warm.pointer_end
            self.source.requires_grad_(False); self.source.encoder.requires_grad_(True)
            self.head.requires_grad_(True); self.pointer_start.requires_grad_(True); self.pointer_end.requires_grad_(True)
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(config['seed'] + INTERACTION_SEED_SALT)
                self.interaction_start = torch.nn.Linear(320, RANK)
                self.interaction_end = torch.nn.Linear(320, RANK)
                torch.nn.init.zeros_(self.interaction_start.weight); torch.nn.init.zeros_(self.interaction_start.bias)
                torch.nn.init.normal_(self.interaction_end.weight, mean=0., std=1./math.sqrt(320))
                torch.nn.init.zeros_(self.interaction_end.bias)
            self.interaction_start.requires_grad_(config['interaction_enabled'])
            self.interaction_end.requires_grad_(config['interaction_enabled'])

        def forward(self, records):
            encoded, query = warm.features(records)
            features = torch.cat((encoded, query[:, None, :].expand(-1, encoded.shape[1], -1)), dim=-1)
            return (self.head(query), self.pointer_start(features).squeeze(-1), self.pointer_end(features).squeeze(-1),
                    self.interaction_start(features), self.interaction_end(features))

    return CoupledModel()


def _optimizer(torch, model, config):
    heads = [p for name, p in model.named_parameters() if p.requires_grad and not name.startswith('source.encoder.')]
    return torch.optim.Adam([{'params': heads, 'lr': config['head_learning_rate']},
        {'params': list(model.source.encoder.parameters()), 'lr': config['encoder_learning_rate']}], foreach=False)


def batch_indices(records, seed, step):
    require(type(step) is int and 0 <= step < MAX_STEPS, 'bounded coupled update required')
    return parent.batch_indices(records, seed, step)


def joint_scores(torch, starts, ends, start_factors, end_factors, *, enabled):
    require(type(enabled) is bool and starts.ndim == 2 and starts.shape == ends.shape,
            'endpoint dimensions or interaction switch differ')
    require(start_factors.shape == end_factors.shape == (*starts.shape, RANK), 'rank8 factors required')
    require(all(bool(torch.isfinite(value).all()) for value in (starts, ends, start_factors, end_factors)), 'nonfinite span factors')
    scores = starts[:, :, None] + ends[:, None, :]
    return scores + torch.matmul(start_factors, end_factors.transpose(1, 2)) * SCALE if enabled else scores


def objective(torch, logits, starts, ends, start_factors, end_factors, records, arm):
    require(arm in ARMS, 'declared objective arm required')
    endpoint_loss, endpoint_parts = parent.objective(torch, logits, starts, ends, records)
    enabled = arm != 'endpoint'; scores = joint_scores(torch, starts, ends, start_factors, end_factors, enabled=enabled)
    joint_terms, contrasts, negative_counts = [], [], []
    width = starts.shape[1]; indices = torch.arange(width); ordered = indices[:, None] <= indices[None, :]
    for i, record in enumerate(records):
        negatives = record.get('negative_owner_tokens', [])
        require(type(negatives) is list and len(negatives) == len(set(tuple(v) for v in negatives)), 'unique contrast token pairs required')
        if record['label'] == 3:
            require(not negatives, 'ambiguous query cannot receive contrast supervision'); negative_counts.append(0); continue
        qa, qb = record['time_tokens']; length = len(record['tokens']); u, v = record['owner_tokens']
        valid = ordered & (indices[:, None] < length) & (indices[None, :] < length)
        valid &= (indices[None, :] < qa) | (indices[:, None] > qb)
        gold = scores[i, u, v]
        joint_terms.append(torch.logsumexp(scores[i][valid], dim=0) - gold)
        for a, b in negatives:
            require(type(a) is int and type(b) is int and 0 <= a <= b < length and (b < qa or a > qb)
                    and (a, b) != (u, v), 'invalid contrast token interval')
        negative_counts.append(len(negatives))
        if negatives:
            selected = torch.stack([gold, *[scores[i, a, b] for a, b in negatives]])
            contrasts.append(torch.logsumexp(selected, dim=0) - gold)
    zero = starts[0, 0]*0. + ends[0, 0]*0. + start_factors[0, 0, 0]*0. + end_factors[0, 0, 0]*0.
    joint_nll = torch.stack(joint_terms).mean() if joint_terms else zero
    contrast_nll = torch.stack(contrasts).mean() if contrasts else zero
    # Reuse the exact old endpoint tensor for baseline trajectory compatibility.
    type_ce = torch.nn.functional.cross_entropy(logits, torch.tensor([r['label'] for r in records], dtype=torch.long))
    weight = .25 if arm == 'joint_contrast' else 0.
    if arm == 'endpoint': loss = endpoint_loss
    else: loss = type_ce + .5 * joint_nll + weight * contrast_nll
    return loss, {**endpoint_parts, 'endpoint_loss': float(endpoint_loss.detach()),
        'joint_ce': float(joint_nll.detach()), 'contrast_ce': float(contrast_nll.detach()),
        'contrast_count': len(contrasts), 'contrast_negative_counts': negative_counts,
        'contrast_negative_span_count': sum(negative_counts), 'applied_contrast_weight': weight,
        'interaction_enabled': enabled, 'objective': arm, 'selection_nll': float((type_ce+joint_nll).detach()),
        'loss': float(loss.detach())}


def _manifests(training, tuning, training_contrasts):
    return {name: {'sha256': digest(value), 'count': len(value)} for name, value in
            [('training', training), ('tuning', tuning), ('training_contrasts', training_contrasts)]}


def build_checkpoint(parent_payload, training_rows, tuning_rows, training_contrasts, *, arm, seed, parent_file_sha256):
    """The caller authenticates the warm parent's file against an external SHA."""
    config = _config(arm, seed); torch = _torch(); _splits(training_rows, tuning_rows, training_contrasts)
    require(type(parent_file_sha256) is str and span._SHA.fullmatch(parent_file_sha256), 'parent file SHA required')
    model = _model(torch, parent_payload, config); optimizer = _optimizer(torch, model, config)
    weights, moments = span._pack(model, optimizer)
    require(all(span._raw(weights[k]) == span._raw(v) for k, v in parent_payload['model_state'].items()), 'inherited warm tensors differ')
    return {'schema': SCHEMA, 'implementation': producer_pins(), 'parent': copy.deepcopy(parent_payload),
            'parent_payload_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
            'model_config': copy.deepcopy(parent_payload['model_config']), 'config': config,
            'manifests': _manifests(training_rows, tuning_rows, training_contrasts), 'initial_state_sha256': digest(weights),
            'model_state': weights, 'optimizer_state': moments, 'optimizer_steps': 0,
            'parent_owner_head_updates': 700, 'cumulative_owner_head_updates': 700,
            'preceding_checkpoint_sha256': None, **FALSE}


def _restore(checkpoint):
    fields = {'schema', 'implementation', 'parent', 'parent_payload_sha256', 'parent_file_sha256', 'model_config', 'config',
              'manifests', 'initial_state_sha256', 'model_state', 'optimizer_state', 'optimizer_steps',
              'parent_owner_head_updates', 'cumulative_owner_head_updates', 'preceding_checkpoint_sha256', *FALSE}
    require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint['schema'] == SCHEMA, 'closed coupled checkpoint required')
    require(all(checkpoint[k] is False for k in FALSE) and checkpoint['implementation'] == producer_pins(), 'authority or producer drift')
    require(len(span._raw(checkpoint)) <= 128*1024*1024, 'checkpoint exceeds128MiB')
    config = checkpoint['config']; require(span._raw(config) == span._raw(_config(config['arm'], config['seed'])), 'training config differs')
    original = checkpoint['parent']; torch = _torch(); model = _model(torch, original, config)
    require(checkpoint['parent_payload_sha256'] == digest(original) and span._raw(checkpoint['model_config']) == span._raw(original['model_config']), 'parent binding differs')
    for key in ('parent_file_sha256', 'initial_state_sha256'):
        require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), 'invalid provenance hash')
    manifests = checkpoint['manifests']
    require(type(manifests) is dict and set(manifests) == {'training', 'tuning', 'training_contrasts'}, 'closed source/contrast manifests required')
    for value in manifests.values():
        require(type(value) is dict and set(value) == {'sha256', 'count'} and type(value['sha256']) is str and span._SHA.fullmatch(value['sha256'])
                and type(value['count']) is int and 4 <= value['count'] <= MAX_ROWS, 'invalid source/contrast manifest')
    require(manifests['training']['count'] == manifests['training_contrasts']['count'], 'contrast/query count differs')
    steps = checkpoint['optimizer_steps']; require(type(steps) is int and 0 <= steps <= MAX_STEPS, 'invalid update count')
    require(type(checkpoint['parent_owner_head_updates']) is int and checkpoint['parent_owner_head_updates'] == 700
            and type(checkpoint['cumulative_owner_head_updates']) is int and checkpoint['cumulative_owner_head_updates'] == 700+steps, 'update provenance differs')
    preceding = checkpoint['preceding_checkpoint_sha256']
    require(preceding is None if steps == 0 else type(preceding) is str and span._SHA.fullmatch(preceding), 'invalid predecessor')
    optimizer = _optimizer(torch, model, config); initial, _ = span._pack(model, optimizer)
    require(digest(initial) == checkpoint['initial_state_sha256'], 'initial tensors differ')
    if steps == 0: require(span._raw(checkpoint['model_state']) == span._raw(initial), 'zero-update model differs')
    template = model.state_dict(); require(set(checkpoint['model_state']) == set(template), 'model tensor inventory differs')
    for name, value in initial.items():
        frozen = name.startswith('source.') and not name.startswith('source.encoder.')
        frozen |= config['arm'] == 'endpoint' and name.startswith('interaction_')
        if frozen: require(span._raw(checkpoint['model_state'][name]) == span._raw(value), 'frozen inherited/interaction tensor changed: '+name)
    model.load_state_dict({k: span._tensor(torch, checkpoint['model_state'][k], value.shape, k) for k, value in template.items()}, strict=True)
    trainable = {n: p for n, p in model.named_parameters() if p.requires_grad}; moments = checkpoint['optimizer_state']
    require(type(moments) is dict and set(moments) == {'schema', 'parameters'} and moments['schema'] == 'adam-default-betas-eps/v1'
            and set(moments['parameters']) == (set(trainable) if steps else set()), 'Adam trainable inventory differs')
    for name, moment in moments['parameters'].items():
        require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'} and type(moment['step']) is int and moment['step'] == steps, 'Adam step differs')
        p = trainable[name]
        optimizer.state[p] = {'step': torch.tensor(float(steps)), 'exp_avg': span._tensor(torch, moment['exp_avg'], p.shape, name),
                              'exp_avg_sq': span._tensor(torch, moment['exp_avg_sq'], p.shape, name, nonnegative=True)}
    model.eval(); return torch, model, optimizer


def train(checkpoint, training_rows, tuning_rows, training_contrasts, *, additional_steps, max_seconds=600):
    require(type(additional_steps) is int and 0 <= additional_steps <= MAX_STEPS, 'bounded additional updates required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 1800, 'bounded deadline required')
    started = time.monotonic(); torch, model, optimizer = _restore(checkpoint)
    require(span._raw(checkpoint['manifests']) == span._raw(_manifests(training_rows, tuning_rows, training_contrasts)), 'source/contrast manifests changed')
    records, _ = _splits(training_rows, tuning_rows, training_contrasts); config = checkpoint['config']; trace = []
    require(checkpoint['optimizer_steps'] + additional_steps <= MAX_STEPS, 'update budget exceeded')
    trainable = {n: p for n, p in model.named_parameters() if p.requires_grad}
    for step in range(checkpoint['optimizer_steps'], checkpoint['optimizer_steps']+additional_steps):
        require(time.monotonic()-started < max_seconds, 'deadline exceeded; incomplete stage is not successful')
        batch = [records[i] for i in batch_indices(records, config['seed'], step)]
        optimizer.zero_grad(set_to_none=True); model.train(); logits, starts, ends, left, right = model(batch)
        loss, parts = objective(torch, logits, starts, ends, left, right, batch, config['arm'])
        require(parts['class_counts'] == [6]*4 and parts['unique_count'] == 18, 'balanced24 batch required')
        require(bool(torch.isfinite(loss)), 'nonfinite objective'); loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in trainable.values()), 'nonfinite/missing trainable gradient')
        require(all(p.grad is None for p in model.parameters() if not p.requires_grad), 'frozen parameter received gradient')
        norm = torch.nn.utils.clip_grad_norm_(list(trainable.values()), config['gradient_clip']); require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        trace.append({'step': step+1, 'query_ids': [r['query']['id'] for r in batch], 'labels': [r['label'] for r in batch],
            'owner_token_spans': [list(r['owner_tokens']) if r['owner_tokens'] is not None else None for r in batch],
            'time_token_spans': [list(r['time_tokens']) for r in batch], 'token_counts': [len(r['tokens']) for r in batch],
            'negative_owner_token_spans': [[list(v) for v in r['negative_owner_tokens']] for r in batch],
            'logits': logits.detach().tolist(),
            'pointer_start_logits': [starts[i, :len(r['tokens'])].detach().tolist() for i, r in enumerate(batch)],
            'pointer_end_logits': [ends[i, :len(r['tokens'])].detach().tolist() for i, r in enumerate(batch)],
            'pointer_start_factors': [left[i, :len(r['tokens'])].detach().tolist() for i, r in enumerate(batch)],
            'pointer_end_factors': [right[i, :len(r['tokens'])].detach().tolist() for i, r in enumerate(batch)],
            'interaction_enabled': config['interaction_enabled'], 'interaction_scale': SCALE,
            'objective_components': parts, 'loss': float(loss.detach()), 'preclip_gradient_norm': float(norm),
            'encoder_batch_forwards': 1, 'encoder_source_evaluations': len(batch)})
        optimizer.step()
    weights, moments = span._pack(model, optimizer); steps = checkpoint['optimizer_steps']+additional_steps
    result = {**copy.deepcopy(checkpoint), 'model_state': weights, 'optimizer_state': moments, 'optimizer_steps': steps,
              'cumulative_owner_head_updates': 700+steps,
              'preceding_checkpoint_sha256': digest(checkpoint) if additional_steps else checkpoint['preceding_checkpoint_sha256']}
    _restore(result)
    return result, {'schema': REPORT_SCHEMA, 'initial_step': checkpoint['optimizer_steps'], 'final_step': steps,
        'steps_executed': len(trace), 'trace': trace, 'trainable_parameters': {n: p.numel() for n, p in trainable.items()},
        'encoder_batch_forwards': len(trace), 'encoder_source_evaluations': len(trace)*24,
        'wall_seconds': time.monotonic()-started, 'fresh_optimizer_at_step_zero': True,
        'parent_optimizer_moments_transferred': False, **FALSE}


def decode_span(start_logits, end_logits, start_factors, end_factors, time_tokens, *, enabled):
    require(type(enabled) is bool, 'exact interaction flag required')
    # Validate the inherited endpoint/query inventory without adding a width cap.
    original = parent.decode_span(start_logits, end_logits, time_tokens)
    n = len(start_logits)
    require(type(start_factors) is list and type(end_factors) is list and len(start_factors) == len(end_factors) == n,
            'one rank8 vector per valid source token required')
    require(all(type(row) is list and len(row) == RANK and all(type(v) in (int, float) and math.isfinite(v) for v in row)
                for rows in (start_factors, end_factors) for row in rows), 'finite rank8 factors required')
    if not enabled or not original['valid_span_count']: return original
    if all(v == 0 for row in start_factors for v in row): return original
    a, b = time_tokens; pairs = [(i, j) for i in range(n) for j in range(i, n) if j < a or i > b]
    values = [(float(start_logits[i])+float(end_logits[j])) +
              math.fsum(float(start_factors[i][k])*float(end_factors[j][k]) for k in range(RANK))*SCALE for i, j in pairs]
    require(all(math.isfinite(v) for v in values), 'nonfinite joint score')
    best = max(range(len(values)), key=values.__getitem__); maximum = values[best]
    probability = 1. / math.fsum(math.exp(v-maximum) for v in values)
    return {'raw_owner_token_span': list(pairs[best]), 'span_confidence': probability, 'valid_span_count': len(pairs)}


class CoupledTemporalOwnerPointer:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint); self.checkpoint_sha256 = digest(checkpoint)
        self.interaction_enabled = checkpoint['config']['interaction_enabled']
        self.encoder_batch_forwards = 0; self.encoder_source_evaluations = 0

    def predict_many(self, queries):
        require(type(queries) in (list, tuple) and 0 < len(queries) <= 64, 'bounded source-only batch required')
        records = [_query(row) for row in queries]
        with self.torch.no_grad():
            logits, starts, ends, left, right = self.model(records); probabilities = self.torch.softmax(logits, dim=-1)
        require(all(bool(self.torch.isfinite(v).all()) for v in (logits, starts, ends, left, right, probabilities)), 'nonfinite predictions')
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(records); rows = []
        for i, record in enumerate(records):
            query = record['query']; length = len(record['tokens']); chosen = int(probabilities[i].argmax()); confidence = float(probabilities[i, chosen])
            reason = 'predicted_ambiguous' if chosen == 3 else 'below_fixed_confidence' if confidence < THRESHOLD else None
            start, end = starts[i, :length].tolist(), ends[i, :length].tolist()
            u, v = left[i, :length].tolist(), right[i, :length].tolist()
            decoded = decode_span(start, end, u, v, record['time_tokens'], enabled=self.interaction_enabled)
            pair = decoded['raw_owner_token_span']
            anchor = None if pair is None else {'char_start': record['tokens'][pair[0]]['start'], 'char_end': record['tokens'][pair[1]]['end']}
            joint_reason = ('predicted_ambiguous' if chosen == 3 else 'no_valid_owner_span' if anchor is None else
                'below_fixed_type_confidence' if confidence < THRESHOLD else 'below_fixed_span_confidence' if decoded['span_confidence'] < THRESHOLD else None)
            rows.append({'id': query['id'], 'source_sha256': query['source_sha256'], 'proposed_time_span': query['proposed_time_span'],
                'time_token_span': list(record['time_tokens']), 'logits': logits[i].tolist(), 'probabilities': probabilities[i].tolist(),
                'predicted_label': CLASSES[chosen], 'confidence': confidence, 'status': 'deferred' if reason else 'accepted',
                'owner_type': None if reason else CLASSES[chosen], 'reason': reason,
                'pointer_start_logits': start, 'pointer_end_logits': end, 'pointer_start_factors': u, 'pointer_end_factors': v,
                'interaction_scale': SCALE, 'interaction_enabled': self.interaction_enabled,
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

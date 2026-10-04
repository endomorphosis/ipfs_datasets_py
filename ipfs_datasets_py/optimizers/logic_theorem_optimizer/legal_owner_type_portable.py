"""Explicit local loader for data-only owner-TYPE research model exports.

This file is independently relocatable: only Python, torch and safetensors are
required. It never downloads or executes repository-supplied serialized code.
Authenticate this loader and the manifest externally before importing it. The
export's SHA binds data integrity, not legal meaning or model qualification.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
SCHEMA = 'legal-owner-type-portable-inference/v1'
CLASSES = ('norm', 'condition', 'exception', 'ambiguous')
FALSE = {'statutory_semantics_verified': False, 'owner_occurrence_resolved': False,
         'latent_input_enabled': False, 'pipeline_promotion': False, 'existing_gates_changed': False}
CONFIG = {'embedding_dim': 16, 'hidden_size': 32, 'head_hidden': 32, 'dtype': 'float32',
          'device': 'cpu', 'class_order': list(CLASSES), 'threshold': .8,
          'max_source_characters': 16384, 'max_source_tokens': 256, 'max_token_bytes': 2048,
          'tokenizer': 'unicode_word_or_punctuation_exact_offsets/v1',
          'byte_alphabet': 'casefold_utf8_plus1_pad0/v1',
          'feature_order': ['source_mean', 'time_start', 'time_end', 'time_mean'],
          'graph': 'byte-mean-first-last-size_tanh_projection_packed_bigru_owner_mlp/v1'}
SOURCE_KEYS = {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
SHA = re.compile(r'[0-9a-f]{64}\Z')


def require(condition, message):
    if not condition: raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _read_json(raw):
    def bad(_): raise ValueError('nonfinite JSON')
    return json.loads(raw, object_pairs_hook=_object, parse_constant=bad)


def tokenize_source(text):
    require(type(text) is str and text.strip(), 'nonempty source required')
    require(len(text) <= 16384, 'source character limit; no truncation')
    matches = list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))
    require(0 < len(matches) <= 256, 'source token limit; no truncation')
    tokens = []
    for match in matches:
        encoded = match.group().casefold().encode('utf-8')
        require(len(encoded) <= 2048, 'token byte limit; no truncation')
        tokens.append({'text': match.group(), 'start': match.start(), 'end': match.end(),
                       'byte_ids': [byte + 1 for byte in encoded]})
    return tokens


def parse_query(query):
    require(type(query) is dict and set(query) == SOURCE_KEYS, 'closed source-only query required')
    require(type(query['id']) is str and 0 < len(query['id']) <= 256, 'bounded query id required')
    text = query['source_text']; tokens = tokenize_source(text)
    require(query['source_sha256'] == hashlib.sha256(text.encode()).hexdigest(), 'source SHA differs')
    interval = query['proposed_time_span']
    require(type(interval) is dict and set(interval) == {'char_start', 'char_end'}, 'closed time interval required')
    a, b = interval['char_start'], interval['char_end']
    require(type(a) is int and type(b) is int and 0 <= a < b <= len(text), 'invalid time interval')
    starts = {t['start']: i for i, t in enumerate(tokens)}; ends = {t['end']: i for i, t in enumerate(tokens)}
    require(a in starts and b in ends, 'time interval must align with tokens')
    return {'query': query, 'tokens': tokens, 'time_tokens': (starts[a], ends[b])}


def _model(torch):
    class Source(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.byte_embedding = torch.nn.Embedding(257, 16, padding_idx=0)
            self.token_projection = torch.nn.Linear(49, 32)
            self.encoder = torch.nn.GRU(32, 32, batch_first=True, bidirectional=True)

        def forward(self, records):
            width = max(len(r['tokens']) for r in records)
            byte_width = max(len(t['byte_ids']) for r in records for t in r['tokens'])
            ids = torch.zeros((len(records), width, byte_width), dtype=torch.long)
            sizes = torch.zeros((len(records), width), dtype=torch.long)
            for i, record in enumerate(records):
                for j, token in enumerate(record['tokens']):
                    values = token['byte_ids']
                    ids[i, j, :len(values)] = torch.tensor(values, dtype=torch.long)
                    sizes[i, j] = len(values)
            lengths = torch.tensor([len(r['tokens']) for r in records], dtype=torch.long)
            embedded = self.byte_embedding(ids)
            mean = embedded.sum(2) / sizes.clamp(min=1)[..., None]
            first = embedded[:, :, 0, :]
            last = embedded.gather(2, (sizes.clamp(min=1)-1)[:, :, None, None].expand(-1, -1, 1, 16)).squeeze(2)
            size = torch.log1p(sizes.to(torch.float32))[..., None] / math.log1p(2048)
            token = torch.tanh(self.token_projection(torch.cat((mean, first, last, size), dim=-1)))
            packed = torch.nn.utils.rnn.pack_padded_sequence(token, lengths.cpu(), batch_first=True, enforce_sorted=False)
            encoded, _ = self.encoder(packed)
            encoded, lengths = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True)
            mask = torch.arange(encoded.shape[1])[None, :] < lengths[:, None]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            starts = torch.stack([encoded[i, row['time_tokens'][0]] for i, row in enumerate(records)])
            ends = torch.stack([encoded[i, row['time_tokens'][1]] for i, row in enumerate(records)])
            means = torch.stack([encoded[i, row['time_tokens'][0]:row['time_tokens'][1]+1].mean(0) for i, row in enumerate(records)])
            return torch.cat((pooled, starts, ends, means), dim=1)

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.source = Source()
            self.head = torch.nn.Sequential(torch.nn.Linear(256, 32), torch.nn.Tanh(), torch.nn.Linear(32, 4))

        def forward(self, records): return self.head(self.source(records))

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(0)
        return Model()


class PortableOwnerType:
    def __init__(self, directory, *, expected_manifest_sha256):
        require(type(expected_manifest_sha256) is str and SHA.fullmatch(expected_manifest_sha256), 'externally pinned manifest SHA required')
        root = Path(directory)
        require(not root.is_symlink() and root.is_dir(), 'model directory required')
        path = root / 'manifest.json'
        require(not path.is_symlink() and path.stat().st_size <= 65536, 'bounded regular manifest required')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected_manifest_sha256, 'manifest SHA differs')
        manifest = _read_json(raw)
        require(type(manifest) is dict and set(manifest) == {'schema', 'config', 'environment', 'weights', 'source_checkpoint', 'loader_sha256', 'authority'}, 'closed manifest required')
        require(manifest['schema'] == SCHEMA and canonical(manifest['config']) == canonical(CONFIG), 'inference config differs')
        require(canonical(manifest['authority']) == canonical(FALSE), 'authority flags differ')
        require(manifest['loader_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'loader source differs')
        source = manifest['source_checkpoint']
        require(type(source) is dict and set(source) == {'sha256', 'bytes', 'schema'}, 'source checkpoint provenance required')
        require(type(source['sha256']) is str and SHA.fullmatch(source['sha256']) and type(source['bytes']) is int and 0 < source['bytes'] <= 128*1024*1024, 'invalid source provenance')
        require(source['schema'] in {'legal-temporal-owner-type-checkpoint/v1', 'legal-paired-temporal-owner-type-checkpoint/v1'}, 'unsupported parent schema')
        weights = manifest['weights']
        require(type(weights) is dict and set(weights) == {'filename', 'sha256', 'bytes', 'tensors'}, 'closed weights descriptor required')
        require(weights['filename'] == 'weights.safetensors' and type(weights['bytes']) is int and 0 < weights['bytes'] <= 4*1024*1024, 'bounded fixed weights filename required')
        path = root / weights['filename']
        require(not path.is_symlink() and path.stat().st_size == weights['bytes'], 'weight byte count differs')
        payload = path.read_bytes()
        require(hashlib.sha256(payload).hexdigest() == weights['sha256'], 'weights SHA differs')
        import torch
        from safetensors.torch import load
        require(os.environ.get('CUDA_VISIBLE_DEVICES') == '-1', 'CPU-only loader')
        environment = manifest['environment']
        require(type(environment) is dict and set(environment) == {'torch_version', 'inference_threads', 'device'}, 'closed environment required')
        require(canonical(environment) == canonical({'torch_version': str(torch.__version__), 'inference_threads': 1, 'device': 'cpu'}), 'use the pinned torch environment for this bounded-parity export')
        torch.set_num_threads(1)
        model = _model(torch); state = load(payload); template = model.state_dict()
        expected = {key: {'shape': list(value.shape), 'dtype': 'float32'} for key, value in template.items()}
        require(canonical(weights['tensors']) == canonical(expected) and set(state) == set(template), 'tensor inventory differs')
        require(all(value.dtype == torch.float32 and list(value.shape) == expected[key]['shape'] and bool(torch.isfinite(value).all()) for key, value in state.items()), 'tensor shape/dtype/finite check failed')
        require(bool((state['source.byte_embedding.weight'][0] == 0).all()), 'padding embedding differs')
        model.load_state_dict(state, strict=True); model.eval(); model.requires_grad_(False)
        self.torch, self.model, self.manifest = torch, model, manifest
        self.encoder_batch_forwards = 0; self.encoder_source_evaluations = 0

    def predict_many(self, queries):
        require(type(queries) in (list, tuple) and 0 < len(queries) <= 64, 'bounded source-only batch required')
        records = [parse_query(q) for q in queries]
        with self.torch.no_grad():
            logits = self.model(records); probabilities = self.torch.softmax(logits, dim=-1)
        require(bool(self.torch.isfinite(logits).all()) and bool(self.torch.isfinite(probabilities).all()), 'nonfinite predictions')
        self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(records)
        rows = []
        for index, record in enumerate(records):
            query = record['query']; chosen = int(probabilities[index].argmax()); confidence = float(probabilities[index, chosen])
            reason = 'predicted_ambiguous' if chosen == 3 else 'below_fixed_confidence' if confidence < .8 else None
            rows.append({'id': query['id'], 'source_sha256': query['source_sha256'], 'proposed_time_span': dict(query['proposed_time_span']),
                         'time_token_span': list(record['time_tokens']), 'logits': logits[index].tolist(), 'probabilities': probabilities[index].tolist(),
                         'predicted_label': CLASSES[chosen], 'confidence': confidence, 'status': 'deferred' if reason else 'accepted',
                         'owner_type': None if reason else CLASSES[chosen], 'reason': reason, **FALSE})
        return rows

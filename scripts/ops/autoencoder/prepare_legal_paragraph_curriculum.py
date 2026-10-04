#!/usr/bin/env python3
"""Prepare source-complete authored paragraph development data, without vectors.

This is a separate experimental ordered multi-rule representation. The inherited
single-rule codec/runtime cannot be relabeled as supporting these targets.
No source compiler, encoder, model, native tool, or training process is run here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = 'authored-legal-paragraph-curriculum/v1'
TOKEN_SCHEMA = 'typed-json-lexical/v1'
TOKEN = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
                   r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
                   r'|true|false|null|[{}\[\],:]')
FALSE = {'qualified': False, 'admitted': False, 'formalized': False,
         'proof_authority': False, 'source_semantics_verified': False,
         'strict_training_allowed': False, 'fresh_holdout': False,
         'lake_executed': False, 'training_executed': False,
         'embedding_inference_executed': False, 'legacy_checkpoint_modified': False}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _encode(target, codec):
    require(type(codec) is dict and set(codec) == {'schema', 'target_vocabulary'}
            and codec['schema'] == TOKEN_SCHEMA, 'exact original lexical codec required')
    vocabulary = codec['target_vocabulary']
    require(type(vocabulary) is list and 3 <= len(vocabulary) <= 65536
            and all(type(token) is str for token in vocabulary)
            and len(set(vocabulary)) == len(vocabulary)
            and vocabulary[:3] == ['<pad>', '<bos>', '<eos>'], 'invalid original vocabulary')
    encoded = raw(target).decode('utf-8')
    tokens = TOKEN.findall(encoded)
    require(''.join(tokens) == encoded and len(tokens) <= 16382, 'complete bounded JSON target required')
    indices = {token: index for index, token in enumerate(vocabulary)}
    require(all(token in indices for token in tokens), 'target outside original vocabulary')
    result = [1] + [indices[token] for token in tokens] + [2]
    require(all(index >= 3 for index in result[1:-1]), 'target contains reserved token')
    require(raw(_strict_json(''.join(vocabulary[index] for index in result[1:-1]))) == raw(target),
            'target lexical encoding lost fields or array order')
    return result


def _default_single_target_validator():
    # This runtime is canonical for the current process. Never prepend a donor
    # snapshot or import the editable HACC tree to work around producer guards.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2 import validate_target
    return lambda target: validate_target('legal_ir', target)


def _input_rows(rows, split, codec, validate):
    require(type(rows) is list and 1 <= len(rows) <= 4096, 'bounded nonempty complete original split required')
    result = []
    for row in rows:
        require(type(row) is dict and {'id', 'source_text', 'group_id', 'target', 'split'} <= set(row),
                'original row lacks source/target/group/split identity')
        require(type(row['id']) is str and row['id'] and len(row['id']) <= 1024
                and type(row['group_id']) is str and row['group_id']
                and type(row['source_text']) is str and row['source_text'].strip()
                and len(row['source_text']) <= 32768 and row['split'] == split,
                'invalid original source, group, or split')
        require(all(row.get(key, False) is False for key in ('admitted', 'qualified', 'proof_authority',
                    'source_semantics_verified', 'truncated')), 'original diagnostic authority/truncation invalid')
        target = row['target']
        require(type(target) is dict and set(target) == {'rules'} and type(target['rules']) is list
                and len(target['rules']) == 1 and type(target['rules'][0]) is dict,
                'one complete original rule per component required')
        rule = target['rules'][0]
        require(set(rule) == {'actor', 'action', 'object', 'modality', 'conditions', 'exceptions', 'temporal'}
                and all(type(rule[key]) is str and rule[key] for key in ('actor', 'action', 'object')),
                'original complete single-rule facets required')
        before = raw(target)
        validation = validate(deepcopy(target))
        require(type(validation) is dict and validation.get('valid') is True,
                'original single-rule native validator did not accept')
        require(raw(target) == before and ('canonical_ir' not in validation or raw(validation['canonical_ir']) == before),
                'original single-rule validator changed target')
        _encode(target, codec)
        identity = {'id': row['id'], 'group_id': row['group_id'],
                    'source_sha256': text_digest(row['source_text']),
                    'normalized_source_sha256': text_digest(' '.join(row['source_text'].casefold().split())),
                    'target_sha256': digest(target)}
        if 'source_sha256' in row:
            require(row['source_sha256'] == identity['source_sha256'], 'original source digest mismatch')
        if 'embedding' in row:
            embedding = row['embedding']
            require(type(embedding) is list and embedding
                    and all(type(x) in (int, float) and math.isfinite(x) for x in embedding), 'malformed original cached vector')
            identity['embedding_sha256'] = digest(embedding)
            if 'embedding_sha256' in row:
                require(row['embedding_sha256'] == identity['embedding_sha256'], 'original embedding digest mismatch')
        result.append({'row': row, 'identity': identity,
                       'logical_slot': tuple(rule[key] for key in ('actor', 'action', 'object'))})
    for field in ('id', 'source_sha256', 'normalized_source_sha256'):
        require(len({row['identity'][field] for row in result}) == len(result), f'duplicate original {field}')
    vector_hashes = [row['identity']['embedding_sha256'] for row in result if 'embedding_sha256' in row['identity']]
    require(len(vector_hashes) == len(set(vector_hashes)), 'duplicate original numeric embedding')
    return result


def build_paragraphs(train_rows, validation_rows, codec, clause_counts=(1, 2, 4, 8),
                     rows_per_length=12, *, validate_single_target=None):
    """Retain complete source/rules with independent logical slots per paragraph.

    The optional validator accepts one ``{rules:[rule]}`` and returns a native
    ``{valid:True,...}`` receipt. It is an injection seam for pure preparation
    tests, never an authorization, Lake, or qualification mechanism.
    Unsupported lengths remain explicitly unavailable. No targets, sources,
    or input-vector values are truncated, generated, repaired, or substituted.
    """
    require(type(clause_counts) in (tuple, list) and 1 <= len(clause_counts) <= 16
            and all(type(count) is int and 1 <= count <= 64 for count in clause_counts)
            and len(set(clause_counts)) == len(clause_counts), 'unique bounded clause counts required')
    require(type(rows_per_length) is int and 1 <= rows_per_length <= 128, 'bounded positive rows per length required')
    validate = validate_single_target if validate_single_target is not None else _default_single_target_validator()
    inputs = {'train': _input_rows(train_rows, 'train', codec, validate),
              'validation': _input_rows(validation_rows, 'validation', codec, validate)}
    exclusions = {}
    for field in ('id', 'group_id', 'source_sha256', 'normalized_source_sha256', 'embedding_sha256'):
        left = {row['identity'][field] for row in inputs['train'] if field in row['identity']}
        right = {row['identity'][field] for row in inputs['validation'] if field in row['identity']}
        require(not left & right, f'original train/validation overlap: {field}')
        exclusions[field] = {'train_unique': len(left), 'validation_unique': len(right), 'overlap': 0}
    result = {'schema': SCHEMA, **FALSE, 'scope': 'authored_compositional_development_not_natural_statute_or_fresh_holdout',
        'representation': 'experimental_ordered_multi_rule_json/v1', 'legacy_single_rule_runtime_loadable': False,
        'original_single_rule_validation': True, 'overall_semantic_consistency_proved': False,
        'source_join': 'two literal newline characters; exact original components retained',
        'embedding_policy': 'encode the complete paragraph from source; original vectors are not averaged or reused',
        'selection_algorithm': 'sha256 rank of split/count/attempt/slot and source identity; independent slots',
        'requested_clause_counts': list(clause_counts), 'rows_per_length': rows_per_length,
        'codec': deepcopy(codec), 'codec_sha256': digest(codec), 'split_exclusion': exclusions,
        'original_split_inventory': {split: [deepcopy(row['identity']) for row in rows] for split, rows in inputs.items()},
        'length_readiness': [], 'train': [], 'validation': []}
    for split, entries in inputs.items():
        by_slot = {}
        for entry in entries:
            by_slot.setdefault(entry['logical_slot'], []).append(entry)
        for count in clause_counts:
            readiness = {'split': split, 'clause_count': count, 'independent_logical_slots': len(by_slot),
                         'requested_rows': rows_per_length, 'produced_rows': 0}
            if count > len(by_slot):
                result['length_readiness'].append({**readiness, 'status': 'unavailable', 'reason': 'not_enough_independent_logical_slots'})
                continue
            seen_sources, generated = set(), []
            for attempt in range(rows_per_length * 64):
                salt = [SCHEMA, split, count, attempt]
                slots = sorted(by_slot, key=lambda slot: digest([*salt, 'slot', slot]))[:count]
                chosen = [min(by_slot[slot], key=lambda item: digest([*salt, 'source', item['identity']])) for slot in slots]
                source = '\n\n'.join(entry['row']['source_text'] for entry in chosen)
                if text_digest(source) in seen_sources:
                    continue
                require(len(source) <= 2 * 1024 * 1024, 'complete paragraph exceeds preparation bound')
                seen_sources.add(text_digest(source))
                target = {'rules': [deepcopy(entry['row']['target']['rules'][0]) for entry in chosen]}
                offsets, char_offset, byte_offset = [], 0, 0
                for position, entry in enumerate(chosen):
                    original = entry['row']
                    text = original['source_text']
                    end_char, end_byte = char_offset + len(text), byte_offset + len(text.encode('utf-8'))
                    require(source[char_offset:end_char] == text
                            and source.encode('utf-8')[byte_offset:end_byte] == text.encode('utf-8'), 'source offset loss')
                    offsets.append({**deepcopy(entry['identity']), 'position': position, 'split': split,
                        'char_start': char_offset, 'char_end': end_char, 'byte_start': byte_offset, 'byte_end': end_byte,
                        'logical_slot': list(entry['logical_slot']),
                        'original_metadata': {k: deepcopy(v) for k, v in original.items() if k not in ('embedding', 'source_text', 'target')}})
                    char_offset, byte_offset = end_char + 2, end_byte + 2
                row_id = 'authored-paragraph:' + split + ':' + str(count) + ':' + text_digest(source)
                generated.append({'id': row_id, 'split': split, 'source_text': source,
                    'source_sha256': text_digest(source), 'clause_count': count,
                    'group_id': 'authored-component-groups:' + digest(sorted({entry['row']['group_id'] for entry in chosen})),
                    'component_group_ids': sorted({entry['row']['group_id'] for entry in chosen}),
                    'components': offsets, 'target': target, 'target_sha256': digest(target),
                    'codec_sha256': digest(codec), 'target_component_ids': [entry['row']['id'] for entry in chosen],
                    'target_ids': _encode(target, codec), 'source_char_count': len(source),
                    'source_byte_count': len(source.encode('utf-8')), 'source_encoder_token_count': None,
                    'source_encoder_token_limit_checked': False, 'independent_logical_slots': True,
                    'reference_origin': 'ordered conjunction of complete original authored single-rule references', **FALSE})
                if len(generated) == rows_per_length:
                    break
            result[split].extend(generated)
            readiness.update(produced_rows=len(generated), status='prepared' if len(generated) == rows_per_length else 'partial',
                             reason=None if len(generated) == rows_per_length else 'insufficient_unique_deterministic_compositions')
            result['length_readiness'].append(readiness)
    result['status'] = 'prepared' if all(row['status'] == 'prepared' for row in result['length_readiness']) else 'partial'
    result['input_source_sha256'] = digest({'train': train_rows, 'validation': validation_rows})
    return result


def _read_file(path, expected):
    require(re.fullmatch('[0-9a-f]{64}', expected) is not None, 'explicit SHA256 required')
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024,
            'bounded regular input file required')
    content = path.read_bytes()
    require(hashlib.sha256(content).hexdigest() == expected, 'input file digest mismatch')
    return _strict_json(content), {'path': str(path.resolve()), 'sha256': expected, 'bytes': len(content)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('train', 'validation', 'codec'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clause-counts', default='1,2,4,8')
    parser.add_argument('--rows-per-length', type=int, default=12)
    args = parser.parse_args()
    require(not args.output.exists() and args.output.parent.is_dir(), 'fresh output path with existing parent required')
    values, inputs = {}, []
    for name in ('train', 'validation', 'codec'):
        values[name], receipt = _read_file(getattr(args, name), getattr(args, name + '_sha256'))
        require(args.output.resolve() != Path(receipt['path']), 'output cannot replace input')
        inputs.append(receipt)
    for name in ('train', 'validation'):
        if type(values[name]) is dict:
            require('rows' in values[name], 'dataset object must contain rows')
            values[name] = values[name]['rows']
    result = build_paragraphs(values['train'], values['validation'], values['codec'],
                             clause_counts=tuple(int(value) for value in args.clause_counts.split(',')),
                             rows_per_length=args.rows_per_length)
    for receipt in inputs:
        _read_file(Path(receipt['path']), receipt['sha256'])
    result['input_files'] = inputs
    result['producer'] = {'path': str(Path(__file__).resolve()), 'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with args.output.open('xb') as stream:
        stream.write(raw(result) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({'status': result['status'], 'train': len(result['train']), 'validation': len(result['validation']),
                      'length_readiness': result['length_readiness'], **FALSE}, sort_keys=True))


if __name__ == '__main__':
    main()

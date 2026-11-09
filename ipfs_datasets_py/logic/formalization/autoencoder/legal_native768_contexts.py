"""Offline replay of retained native768 source contexts.

Extracted from prepare_legal_native768_contexts; its original script and pinned
manifests stay unchanged. This verifier reads the native768 branch and recorded
producer/asset evidence only. It does not replay the trained384 sibling, load
weights, tokenize, encode, train, or establish source semantics. Original native
receipts retain token hashes/counts, not the complete token IDs or model input
text; exact source text is joined by its original source commitment. Replaying
ordinary records is artifact consistency, not cryptographic execution attestation.
"""
from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-native768-context-binding-input/v1"
SPLITS = ('train', 'tuning', 'challenge', 'oov')
SOURCE_FIELDS = {'id', 'source_text', 'source_sha256', 'family_group'}
RECEIPT_FIELDS = {'schema', 'id', 'source_sha256', 'profile_id', 'dimension', 'embedding',
    'token_count_including_special_tokens', 'token_input_sha256', 'truncated', 'normalized', 'asset_manifest_sha256'}
MAX_BYTES = 128 * 1024**2
MAX_TOTAL_BYTES = 512 * 1024**2
MAX_FILES = 512
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_READS = ContextVar('native768_context_reads', default=None)
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _plain(value):
    pending, nodes = [(value, 0)], 0
    while pending:
        part, depth = pending.pop()
        nodes += 1
        require(nodes <= 4_000_000 and depth <= 64, 'bounded passive JSON required')
        if type(part) is dict:
            require(all(type(k) is str for k in part), 'plain string JSON keys required')
            pending.extend((child, depth + 1) for child in part.values())
        elif type(part) in (list, tuple):
            pending.extend((child, depth + 1) for child in part)
        else:
            require(type(part) in (str, int, float, bool, type(None))
                and (type(part) is not float or math.isfinite(part)), 'plain finite JSON values required')


def digest(value):
    _plain(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode()).hexdigest()


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def _bytes(reference):
    _plain(reference)
    require(type(reference) is dict and set(reference) == {'path', 'bytes', 'sha256'}, 'closed pinned artifact required')
    path, size, sha = reference['path'], reference['bytes'], reference['sha256']
    require(type(path) is str and Path(path).is_absolute() and str(Path(path)) == path
        and str(Path(path).resolve(strict=True)) == path, 'canonical nonsymlink artifact path required')
    require(type(size) is int and 0 <= size <= MAX_BYTES and type(sha) is str and _SHA.fullmatch(sha),
        'bounded file bytes and exact SHA256 required')
    before = os.lstat(path)
    require(stat.S_ISREG(before.st_mode) and before.st_size == size, 'pinned regular artifact changed')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        require(_identity(os.fstat(fd)) == _identity(before), 'pinned artifact changed before open')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(size + 1)
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, 'pinned artifact bytes changed')
        require(_identity(os.fstat(fd)) == _identity(before) == _identity(os.lstat(path)), 'pinned artifact changed while read')
    finally:
        os.close(fd)
    reads = _READS.get()
    if reads is not None:
        require(path not in reads or reads[path] == (reference, _identity(before)), 'artifact generation changed during replay')
        if path not in reads:
            require(len(reads) < MAX_FILES and sum(item[0]['bytes'] for item in reads.values()) + size <= MAX_TOTAL_BYTES,
                'retained artifact closure exceeds bounds')
            reads[path] = (dict(reference), _identity(before))
    return raw


def ref(path):
    path = str(Path(path).resolve(strict=True))
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES, 'bounded regular implementation required')
    raw = Path(path).read_bytes()
    result = {'path': path, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    _bytes(result)
    return result


def read(reference):
    def unique(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    try:
        value = json.loads(_bytes(reference).decode('utf-8'), object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON ' + value)))
    except (RecursionError, UnicodeError) as error:
        raise ValueError('bounded UTF8 JSON artifact required') from error
    _plain(value)
    return value


def source_splits(value):
    require(type(value) is dict and set(value) == set(SPLITS), 'four exact source-only splits required')
    seen, source_identity, result = set(), {}, {}
    for split in SPLITS:
        rows=value[split]
        require(type(rows) is list and rows and len(rows) <= 4096, 'bounded nonempty source split required')
        result[split]=[]
        for row in rows:
            require(type(row) is dict and set(row) <= SOURCE_FIELDS and {'id','source_text','source_sha256'} <= set(row),
                'source artifact must not contain targets or other fields')
            require(type(row['id']) is str and 0 < len(row['id']) <= 256 and row['id'] not in seen, 'unique bounded source ID required')
            text=row['source_text']
            require(type(text) is str and text.strip() and '\0' not in text and len(text) <= 65536, 'bounded source text required')
            sha=hashlib.sha256(text.encode()).hexdigest()
            require(sha == row['source_sha256'], 'source hash differs')
            require(sha not in source_identity or source_identity[sha] == text, 'source hash collision')
            source_identity[sha]=text
            seen.add(row['id'])
            result[split].append(deepcopy(row))
    require(sum(len(r) for r in result.values()) <= 4096, 'full source cohort exceeds producer bound')
    return result


def valid_native_receipt(receipt, *, profile_id, asset_sha256):
    require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS, 'closed native receipt required')
    require(receipt['schema'] == 'gte-multilingual-embedding-receipt/v1' and receipt['profile_id'] == profile_id
        and receipt['asset_manifest_sha256'] == asset_sha256 and type(receipt['dimension']) is int and receipt['dimension'] == 768
        and receipt['normalized'] is True and receipt['truncated'] is False, 'native source profile differs')
    require(type(receipt['id']) is str and receipt['id'] and all(type(receipt[k]) is str and re.fullmatch('[0-9a-f]{64}', receipt[k])
        for k in ('source_sha256','token_input_sha256')), 'native source identity/hash invalid')
    vector=receipt['embedding']
    require(type(vector) is list and len(vector) == 768 and all(type(v) in (int,float) and abs(v) <= 1.0001 and math.isfinite(v) for v in vector)
        and abs(math.hypot(*vector) - 1.) <= 1e-4, 'finite normalized768 vector required')
    require(type(receipt['token_count_including_special_tokens']) is int and 1 <= receipt['token_count_including_special_tokens'] <= 8192,
        'native token bound differs')


def cache_index(references, *, producer, asset_sha256):
    result={}
    for reference in references:
        report=read(reference)
        require(report['schema'] == producer.SCHEMA and report['status'] == 'completed' and report['model_inference_executed'] is True
            and report['training_executed'] is False and report['proof_authority'] is False and report['source_semantics_verified'] is False,
            'actual complete-checkpoint encoder production required')
        require(report['implementation'] == producer._implementation() and report['profile_id'] == producer.PROFILE_ID
            and report['assets']['manifest_sha256'] == asset_sha256 and report['receipt_count'] == report['input_row_count'] == len(report['receipts']),
            'cached producer identity/coverage differs')
        loading=report['complete_checkpoint_loading']
        require(loading['architecture'] == 'NewForTokenClassification' and loading['tensor_count'] == 138 and loading['classifier_loaded'] is True
            and not any(loading[k] for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs'))
            and report['dense_path_verification']['encoder_and_complete_hidden_states_bitwise_equal'] is True,
            'complete checkpoint/dense-path evidence required')
        for receipt in report['receipts']:
            valid_native_receipt(receipt, profile_id=producer.PROFILE_ID, asset_sha256=asset_sha256)
            key=receipt['source_sha256']
            require(key not in result or result[key]['receipt']['embedding'] == receipt['embedding'], 'conflicting cached vectors for same source')
            result.setdefault(key, {'receipt': receipt, 'producer_report': reference})
    return result


def make_context(source, upstream, *, source_artifact, producer_sha256, reused):
    receipt=upstream['receipt']
    require(source['source_sha256'] == receipt['source_sha256'], 'context and native source differ')
    vector=deepcopy(receipt['embedding'])
    stage={'schema':'legal-native768-stage-receipt/v1','id':source['id'],'source_sha256':source['source_sha256'],
        'dimension':768,'stage':'native768','representation_id':receipt['profile_id'],'vector_sha256':digest(vector),
        'producer_sha256':producer_sha256,'source_artifact':source_artifact,'producer_report':upstream['producer_report'],
        'upstream_receipt_sha256':digest(receipt),'upstream_receipt_id':receipt['id'],
        'identity_join':'exact_source_sha256','cache_reused':reused,
        'target_access':False,'training_executed':False,'source_semantics_verified':False,'proof_authority':False}
    stage['receipt_sha256']=digest(stage)
    return {'id':source['id'],'source_sha256':source['source_sha256'],'context':vector,
        'context_sha256':digest(vector),'native_stage_receipt':stage}


def _producer_metadata():
    # Both modules are import-light; numerical backends are lazy inside their
    # explicit producer calls, none of which this verifier invokes.
    from . import source_embeddings_768_complete as producer
    return producer


def _assets_and_execution(report, config, producer, asset_entries):
    """Rejoin recorded assets to the separately pinned published manifest.

    This validates retained asset observations. It never reads the model's
    weight files or claims that those files remain installed now.
    """
    profile = producer.reference._PROFILE
    assets = report['assets']
    require(type(assets) is dict and assets.get('schema') == profile.RECEIPT_SCHEMA
        and assets.get('status') == 'available' and assets.get('profile_id') == profile.PROFILE_ID
        and assets.get('model_revision') == profile.MODEL_REV
        and assets.get('code_revision') == profile.CODE_REV
        and assets.get('manifest_sha256') == config['asset_manifest']['sha256']
        and assets.get('model_directory') == config['model_directory']
        and assets.get('code_directory') == config['code_directory']
        and assets.get('unavailable_reasons') == []
        and assets.get('proof_authority') is False and assets.get('model_numerics_verified') is False,
        'recorded assets differ from the original pinned profile/configuration')
    require(assets.get('files') == [asset_entries[key] for key in sorted(asset_entries)],
        'recorded complete asset inventory differs from pinned manifest')
    execution = report.get('execution_profile')
    require(type(execution) is dict and set(execution) == {'batch_size', 'device', 'dtype',
        'attention_implementation', 'padding_side', 'pooling', 'normalization',
        'max_tokens_including_special_tokens', 'overlength_policy'}, 'closed native execution profile required')
    expected = dict(batch_size=execution['batch_size'], device='cpu', dtype='float32',
        attention_implementation='eager', padding_side='right', pooling='cls', normalization='l2',
        max_tokens_including_special_tokens=8192, overlength_policy='reject')
    require(type(execution['batch_size']) is int and 1 <= execution['batch_size'] <= 16
        and execution == expected, 'native execution profile differs')
    require(type(report.get('input_row_count')) is int and type(report.get('receipt_count')) is int
        and 0 < report['input_row_count'] <= 4096, 'bounded native production count required')
    require(report.get('runtime_compatibility_verified') is True
        and all(report.get(key) is False for key in ('maximum_context_numerics_verified',
            'training_executed', 'download_executed', 'ir_decoder_executed',
            'source_semantics_verified', 'proof_authority')), 'native record authority/profile differs')


def _native_manifest(manifest_ref):
    manifest = read(manifest_ref)
    require(type(manifest) is dict and manifest.get('schema') == 'legal-native768-context-manifest/v1'
        and manifest.get('completed') is True and all(manifest.get(key) is False for key in
            ('target_access', 'training_executed', 'source_semantics_verified', 'proof_authority')),
        'completed source-only native context manifest required')
    original = source_splits(read(manifest['source_artifact']))
    config = read(manifest['configuration'])
    require(type(config) is dict and set(config) == {'schema', 'sources', 'asset_manifest',
        'model_directory', 'code_directory', 'cache_reports', 'resources', 'batch_size',
        'pilot_unique_sources', 'trained384_bundle', 'trained384_contexts', 'learned8_availability'}
        and config['schema'] == 'legal-native768-context-preparation/v1'
        and config['sources'] == manifest['source_artifact'], 'original context configuration differs')
    require(type(config['batch_size']) is int and 1 <= config['batch_size'] <= 16,
        'bounded configured native batch required')
    pilot = manifest['pilot_unique_sources']
    require(pilot is None or type(pilot) is int and 1 <= pilot <= 128, 'bounded native source pilot required')
    require(config['pilot_unique_sources'] == pilot, 'configured source selection differs')
    selected = sorted({row['source_sha256'] for rows in original.values() for row in rows})
    selected = selected if pilot is None else selected[:pilot]
    require(manifest['selected_source_sha256'] == selected
        and type(manifest['unique_source_count']) is int and manifest['unique_source_count'] == len(selected),
        'complete original source selection differs')
    references = manifest['implementation_files']
    require(type(references) is list and 1 <= len(references) <= 32
        and len({item['path'] for item in references}) == len(references), 'bounded unique implementation closure required')
    for reference in references:
        require(ref(reference['path']) == reference, 'native context implementation changed')
    producer = _producer_metadata()
    # Record the actual loaded producer sources independently of caller lists.
    for path in (producer.__file__, producer.reference.__file__, producer.reference._PROFILE.__file__):
        ref(path)
    asset_manifest = read(config['asset_manifest'])
    entries = producer.reference._PROFILE._manifest_entries(asset_manifest)
    require(set(entries) == set(producer.reference._PROFILE.PUBLISHED_ASSETS),
        'complete published native asset manifest required')
    reports = manifest['producer_reports']
    require(type(reports) is list and 1 <= len(reports) <= 128
        and len({item['path'] for item in reports}) == len(reports), 'bounded unique producer reports required')
    require(type(config['cache_reports']) is list and len(config['cache_reports']) <= 128,
        'bounded original cache inventory required')
    # Cache references may include unused reports. The original requested
    # inventory still has to be pinned, and every selected report is replayed.
    for reference in config['cache_reports']:
        require(reference in reports, 'configured cached producer report missing')
    cached = cache_index(reports, producer=producer, asset_sha256=config['asset_manifest']['sha256'])
    for reference in reports:
        _assets_and_execution(read(reference), config, producer, entries)
    representation = manifest['representations']['native768']
    require(type(representation) is dict and set(representation) == {'dimension', 'representation_id',
        'producer_sha256', 'contexts', 'lineage_artifacts'}
        and type(representation['dimension']) is int and representation['dimension'] == 768
        and representation['representation_id'] == producer.PROFILE_ID
        and representation['producer_sha256'] == digest({r['path']: r['sha256'] for r in references}),
        'representation identity or producer differs')
    require(representation['lineage_artifacts'] == [manifest['configuration'], config['asset_manifest'], *reports]
        and type(representation['contexts']) is dict and set(representation['contexts']) == set(SPLITS),
        'complete native representation lineage/context inventory required')
    contexts = {}
    for split in SPLITS:
        rows = read(representation['contexts'][split])
        expected = [row for row in original[split] if row['source_sha256'] in selected]
        require(type(rows) is list and len(rows) == len(expected), 'context/source split count differs')
        for source, row in zip(expected, rows):
            require(type(row) is dict and set(row) == {'id', 'source_sha256', 'context',
                'context_sha256', 'native_stage_receipt'}, 'closed ordered context row required')
            stage = row['native_stage_receipt']
            require(type(stage) is dict and type(stage.get('cache_reused')) is bool,
                'explicit context cache origin required')
            upstream = cached.get(source['source_sha256'])
            require(upstream is not None, 'source has no original successful native record')
            expected_reuse = upstream['producer_report'] in config['cache_reports']
            require(stage['cache_reused'] is expected_reuse, 'context cache origin differs')
            regenerated = make_context(source, upstream, source_artifact=manifest['source_artifact'],
                producer_sha256=representation['producer_sha256'], reused=expected_reuse)
            require(row == regenerated, 'source/vector/producer receipt rejoin differs')
            contexts[source['id']] = (source, regenerated, split)
    require(type(manifest['context_count']) is int and manifest['context_count'] == len(contexts),
        'complete native context count differs')
    original_splits = {}
    for split, rows in original.items():
        for row in rows:
            original_splits.setdefault(row['source_sha256'], set()).add(split)
    return manifest, representation, contexts, original_splits


def verify_native768_contexts(manifest_ref, *, sources):
    """Return exact ordered native768 contexts for target-free source rows.

    ``manifest_ref`` has exactly path/bytes/sha256; ``sources`` contains one to
    4096 unique {id, source_text} rows. Replay covers the complete retained
    native768 branch, then selects exactly those rows in caller order. The
    trained384 sibling is deliberately outside this native-only result.

    All retained reads and this helper's current bytes are fenced before
    return. Endpoint fences are not an atomic cross-file snapshot. Hash pins
    authenticate supplied bytes, not the truth of self-authored native logs.
    """
    _plain(sources)
    manifest_before = digest(manifest_ref)
    original_manifest_ref = manifest_ref
    manifest_ref = deepcopy(manifest_ref)
    require(type(sources) in (list, tuple) and 1 <= len(sources) <= 4096, 'bounded source-only rows required')
    before = digest(sources)
    detached = deepcopy(list(sources))
    seen = set()
    for row in detached:
        require(type(row) is dict and set(row) == {'id', 'source_text'}, 'source-only id/text rows required')
        require(type(row['id']) is str and 0 < len(row['id']) <= 256 and row['id'] not in seen,
            'unique bounded requested source identity required')
        require(type(row['source_text']) is str and row['source_text'].strip()
            and '\0' not in row['source_text'] and len(row['source_text']) <= 65536,
            'bounded exact requested source text required')
        seen.add(row['id'])
    reads = {}
    token = _READS.set(reads)
    try:
        require(ref(__file__)['sha256'] == _SELF_SHA, 'native context verifier source changed')
        manifest, representation, contexts, original_splits = _native_manifest(manifest_ref)
        selected, memberships = [], []
        for row in detached:
            require(row['id'] in contexts, 'requested source is absent from retained native contexts')
            original, context, split = contexts[row['id']]
            require(row['source_text'] == original['source_text'], 'requested source bytes differ')
            selected.append(deepcopy(context))
            memberships.append({'id': row['id'], 'source_sha256': original['source_sha256'],
                'splits': sorted(original_splits[original['source_sha256']])})
        result = {'schema': SCHEMA, 'status': 'source_vector_producer_joins_verified',
            'contexts': selected, 'representation': {key: deepcopy(representation[key]) for key in
                ('dimension', 'representation_id', 'producer_sha256')},
            'context_contract': {'dimension': 768, 'representation_id': representation['representation_id'],
                'producer_sha256': representation['producer_sha256'],
                'training_index_sha256': manifest_ref['sha256']},
            'provenance': {'manifest': dict(manifest_ref), 'source_artifact': manifest['source_artifact'],
                'configuration': manifest['configuration'], 'original_context_count': len(contexts),
                'selected_count': len(selected), 'selected_source_rows_sha256': before,
                'selected_contexts_sha256': digest(selected), 'loaded_helper_sha256': _SELF_SHA,
                'selected_source_splits': memberships,
                'read_artifacts': [dict(reference) for reference, _ in reads.values()],
                'trained384_sibling_checked': False, 'weights_read': False,
                'raw_token_ids_retained': False, 'source_join': 'exact_id_and_UTF8_source_commitment',
                'execution_attestation': False, 'current_model_installation_checked': False,
                'scope': 'recorded_native768_artifact_consistency_with_endpoint_fences'},
            'encoder_reexecuted': False, 'target_access': False, 'training_executed': False,
            'source_semantics_verified': False, 'proof_authority': False, 'qualified': False,
            'admitted': False}
        for reference, identity in list(reads.values()):
            _bytes(reference)
            require(_identity(os.lstat(reference['path'])) == identity, 'artifact changed before return')
        require(digest(sources) == before, 'requested source rows changed during replay')
        require(digest(original_manifest_ref) == manifest_before, 'manifest reference changed during replay')
        return result
    finally:
        _READS.reset(token)


__all__ = ['verify_native768_contexts', 'SCHEMA']

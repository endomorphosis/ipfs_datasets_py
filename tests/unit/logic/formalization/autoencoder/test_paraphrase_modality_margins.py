"""Reference barriers, archive identity and source-owner contracts; no models."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

P = Path(__file__).resolve().parents[5]
SCRIPT = P / 'scripts/ops/autoencoder/diagnose_paraphrase_modality_margins.py'
spec = importlib.util.spec_from_file_location('_test_modality_margin_driver', SCRIPT)
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value))
    return dict(path=str(path), sha256=owner.sha(path), bytes=path.stat().st_size)


def fixture(tmp_path):
    """Use exactly the authority fields emitted by the real trace owner."""
    codec = dict(target_vocabulary=['pad', 'bos', 'eos', '{', '}'] + [f't{i}' for i in range(27)])
    rows = [dict(id=f'source:{i}', source_text=f'Source {i}.', input=[float(i)]) for i in range(48)]
    lanes = {d: dict(fresh_rows=deepcopy(rows), fresh_contexts={},
        donor=dict(codec=codec, input_transform={'width': d})) for d in (384, 768)}
    manifest = dict(inputs={}, archived_predictions={})
    runs, records = {}, []
    for d in (384, 768):
        for arm in owner.ARMS:
            lane = lanes[d]
            state = dict(tensor_sha256=digest([d, arm]))
            runs[d, arm] = dict(states={'selected': state})
            predictions = [dict(id=r['id'], token_ids=[3, 4], generation_status='eos', eos_reached=True) for r in rows]
            trace = dict(schema='generated-contextual-scalar-trace/v1', complete=True,
                model_tensor_sha256=state['tensor_sha256'], model_schema='ordered-clause-recurrent-source-decoder-development/v1',
                dimension=d, source_rows_sha256=digest(rows), source_contexts_sha256=digest({}),
                codec_sha256=digest(codec), input_transform_sha256=digest(lane['donor']['input_transform']),
                predictions=deepcopy(predictions), sample_count=48, batch_size=8, max_target_tokens=512,
                generation_temperature=0, vocabulary_size=32, source_only=True, full_vocabulary_retained=True,
                decomposition_exact=True, caller_state_preserved=True, hooks_removed=True,
                complete_rollout_before_reference_scoring=True, reference_count_access=False,
                reference_prefix_access=False, reference_documents_passed_to_model=False, inventory_access=False,
                source_context_target_access=False, syntax_mask=False, forced_closure=False, model_copied=False,
                extra_model_passes=0, source_head_extra_evaluations=0, optimizer_steps=0,
                **{flag: False for flag in owner.TRACE_FALSE_FLAGS})
            trace['trace_sha256'] = digest(trace)
            trace_ref = save(tmp_path / f'{d}-{arm}-trace.json', trace)
            archived = dict(complete=True, model_tensor_sha256=state['tensor_sha256'],
                source_rows_sha256=digest(rows), source_contexts_sha256=digest({}), predictions=predictions,
                generation_reference_access=False, generation_temperature=0, max_target_tokens=512)
            archived_ref = save(tmp_path / f'{d}-{arm}-archived.json', archived)
            manifest['inputs'][archived_ref['path']] = archived_ref['sha256']
            manifest['archived_predictions'][owner.key(d, arm)] = archived_ref
            records.append(dict(dimension=d, arm=arm, role='selected', state_ref=state, trace_ref=trace_ref))
    return manifest, records, runs, lanes, codec


def update_trace(record, **updates):
    path = Path(record['trace_ref']['path'])
    trace = json.loads(path.read_bytes())
    trace.update(updates)
    trace['trace_sha256'] = digest({k: v for k, v in trace.items() if k != 'trace_sha256'})
    record['trace_ref'] = save(path, trace)


def references(tmp_path, manifest, lanes, codec):
    values = [dict(id=row['id'], source_text=row['source_text'],
        source_sha256=hashlib.sha256(row['source_text'].encode()).hexdigest(),
        target={}, target_sha256=digest({}), codec_sha256=digest(codec), target_ids=[1, 3, 4, 2])
        for row in lanes[384]['fresh_rows']]
    source = [{k: r[k] for k in ('id', 'source_text')} for r in lanes[384]['fresh_rows']]
    receipt = dict(complete=True, schema='authored-modality-holdout/v3', references_sha256=digest(values),
        source_rows_sha256=digest(source), codec_sha256=digest(codec),
        sealed_comparison_sha256=owner.FIXED['comparison_seal'])
    receipt['receipt_sha256'] = digest(receipt)
    for key, value in [('references', values), ('holdout_receipt', receipt)]:
        ref = save(tmp_path / f'{key}.json', value)
        manifest[key] = ref['path']
        manifest['inputs'][ref['path']] = ref['sha256']
    return values, receipt


def test_import_is_cold_and_executes_no_package_or_torch():
    code = '''import builtins, importlib.util, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'torch' or name.startswith('ipfs_datasets_py'):
        raise RuntimeError('numeric/package import during cold driver import')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location('_cold_margin_driver', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_plan(module.FIXED)
assert module.FIXED['panel_count'] == 4
'''
    completed = subprocess.run([sys.executable, '-B', '-c', code, str(SCRIPT)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize('change', [dict(dimensions=[384]), dict(roles=['last-attempt']),
    dict(arms=['original-only', 'half-paraphrases']), dict(panel_count=8), dict(temperature=1),
    dict(temperature=False), dict(context_tokens=1024), dict(output_tokens=1024),
    dict(all_predictions_before_reference_load=False), dict(archived_generation_parity_required=False),
    dict(optimizer_steps=1), dict(workers=2), dict(bridge_names=['deontic_norms']),
    dict(legal_ir_evaluate_provers=True), dict(metric_disk_cache_used=True),
    dict(admitted=True), dict(fresh_holdout=True), dict(used_for_selection=True)])
def test_fixed_plan_refuses_policy_changes(change):
    owner.validate_plan(deepcopy(owner.FIXED))
    with pytest.raises(ValueError, match='recipe differs'):
        owner.validate_plan(dict(owner.FIXED, **change))


def test_four_real_owner_envelopes_pass_without_fabricated_outer_flags(tmp_path):
    manifest, records, runs, lanes, codec = fixture(tmp_path)
    trace = json.loads(Path(records[0]['trace_ref']['path']).read_bytes())
    assert 'formalized' not in trace and 'training_executed' not in trace and 'used_for_selection' not in trace
    owner.verify_traces(manifest, records, runs, lanes, digest)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'old_arm', 'role', 'state',
    'source', 'contexts', 'codec', 'transform', 'temperature', 'batch', 'samples',
    'dimension', 'model_schema', 'vocabulary',
    'target_access', 'admitted', 'production', 'native', 'extra_forward', 'model_copy',
    'hook', 'decomposition', 'file', 'internal_digest'])
def test_invalid_trace_never_opens_references(tmp_path, monkeypatch, mutation):
    manifest, records, runs, lanes, codec = fixture(tmp_path)
    manifest.update(references='never-open-labels', holdout_receipt='never-open-receipt')
    if mutation == 'missing':
        records.pop()
    elif mutation == 'duplicate':
        records[1] = deepcopy(records[0])
    elif mutation == 'old_arm':
        records[0]['arm'] = 'original-only'
    elif mutation == 'role':
        records[0]['role'] = 'last-attempt'
    elif mutation == 'state':
        records[0]['state_ref'] = dict(tensor_sha256='wrong')
    elif mutation == 'file':
        path = Path(records[0]['trace_ref']['path'])
        path.write_bytes(path.read_bytes() + b' ')
    elif mutation == 'internal_digest':
        path = Path(records[0]['trace_ref']['path'])
        trace = json.loads(path.read_bytes())
        trace['trace_sha256'] = 'bad'
        records[0]['trace_ref'] = save(path, trace)
    else:
        updates = {'source': dict(source_rows_sha256='bad'), 'contexts': dict(source_contexts_sha256='bad'),
            'codec': dict(codec_sha256='bad'), 'transform': dict(input_transform_sha256='bad'),
            'temperature': dict(generation_temperature=1), 'batch': dict(batch_size=1),
            'samples': dict(sample_count=47), 'target_access': dict(reference_documents_passed_to_model=True),
            'dimension': dict(dimension=8), 'model_schema': dict(model_schema='unsupported'),
            'vocabulary': dict(vocabulary_size=31),
            'admitted': dict(admitted=True), 'production': dict(production_checkpoint=True),
            'native': dict(native_family_validation_performed=True), 'extra_forward': dict(extra_model_passes=1),
            'model_copy': dict(model_copied=True), 'hook': dict(hooks_removed=False),
            'decomposition': dict(decomposition_exact=False)}
        update_trace(records[0], **updates[mutation])
    original = owner.bound

    def guarded(m, path, expected=None):
        assert path not in ('never-open-labels', 'never-open-receipt'), 'references opened before the barrier'
        return original(m, path, expected)

    monkeypatch.setattr(owner, 'bound', guarded)
    with pytest.raises(ValueError):
        owner.load_references(manifest, records, runs, lanes, codec, digest)


@pytest.mark.parametrize('mutation', ['tokens', 'termination', 'eos', 'state', 'source', 'contexts',
    'temperature', 'output_limit', 'target_access', 'file', 'bytes', 'extra_identity'])
def test_archived_greedy_generation_must_match_before_labels(tmp_path, monkeypatch, mutation):
    manifest, records, runs, lanes, codec = fixture(tmp_path)
    manifest.update(references='never-open-labels', holdout_receipt='never-open-receipt')
    archive_key = owner.key(384, owner.ARMS[0])
    ref = manifest['archived_predictions'][archive_key]
    path = Path(ref['path'])
    value = json.loads(path.read_bytes())
    if mutation in ('tokens', 'termination', 'eos'):
        value['predictions'][0].update({'tokens': dict(token_ids=[4, 3]),
            'termination': dict(generation_status='output_limit'), 'eos': dict(eos_reached=False)}[mutation])
    elif mutation == 'file':
        path.write_bytes(path.read_bytes() + b' ')
    elif mutation == 'bytes':
        ref['bytes'] += 1
    elif mutation == 'extra_identity':
        manifest['archived_predictions']['unexpected'] = ref
    else:
        value.update({'state': dict(model_tensor_sha256='bad'), 'source': dict(source_rows_sha256='bad'),
            'contexts': dict(source_contexts_sha256='bad'), 'temperature': dict(generation_temperature=1),
            'output_limit': dict(max_target_tokens=1024), 'target_access': dict(generation_reference_access=True)}[mutation])
    if mutation not in ('file', 'bytes', 'extra_identity'):
        manifest['archived_predictions'][archive_key] = save(path, value)
        manifest['inputs'][str(path)] = owner.sha(path)
    original = owner.bound

    def guarded(m, p, expected=None):
        assert p not in ('never-open-labels', 'never-open-receipt'), 'references opened before archive parity'
        return original(m, p, expected)

    monkeypatch.setattr(owner, 'bound', guarded)
    with pytest.raises(ValueError):
        owner.load_references(manifest, records, runs, lanes, codec, digest)


def test_labels_load_only_after_all_four_archives_checked(tmp_path, monkeypatch):
    manifest, records, runs, lanes, codec = fixture(tmp_path)
    refs, receipt = references(tmp_path, manifest, lanes, codec)
    original = owner.bound
    access = []

    def observed(m, path, expected=None):
        access.append(path)
        return original(m, path, expected)

    monkeypatch.setattr(owner, 'bound', observed)
    assert owner.load_references(manifest, records, runs, lanes, codec, digest) == (refs, receipt)
    assert len(access) == 6 and access[-2:] == [manifest['references'], manifest['holdout_receipt']]
    assert set(access[:4]) == {ref['path'] for ref in manifest['archived_predictions'].values()}


@pytest.mark.parametrize('change', ['source', 'target', 'codec', 'ids', 'comparison_seal', 'ordering'])
def test_posthoc_references_require_complete_source_target_binding(tmp_path, change):
    manifest, records, runs, lanes, codec = fixture(tmp_path)
    refs, receipt = references(tmp_path, manifest, lanes, codec)
    if change == 'comparison_seal':
        receipt['sealed_comparison_sha256'] = 'bad'
    elif change == 'ordering':
        refs.reverse()
    else:
        refs[0].update({'source': dict(source_sha256='bad'), 'target': dict(target_sha256='bad'),
            'codec': dict(codec_sha256='bad'), 'ids': dict(target_ids=[1, True, 4, 2])}[change])
    receipt['references_sha256'] = digest(refs)
    receipt['receipt_sha256'] = digest({k: v for k, v in receipt.items() if k != 'receipt_sha256'})
    for name, value in [('references', refs), ('holdout_receipt', receipt)]:
        path = Path(manifest[name])
        save(path, value)
        manifest['inputs'][str(path)] = owner.sha(path)
    with pytest.raises(ValueError):
        owner.load_references(manifest, records, runs, lanes, codec, digest)


def test_bound_input_refuses_alias_substitution_or_mutation(tmp_path):
    path = tmp_path / 'input.json'
    save(path, {'old': True})
    manifest = {'inputs': {str(path): owner.sha(path)}}
    assert owner.bound(manifest, path) == {'old': True}
    with pytest.raises(ValueError, match='unbound'):
        owner.bound(manifest, tmp_path / 'missing.json')
    path.write_text('{"old":false}')
    with pytest.raises(ValueError, match='changed'):
        owner.bound(manifest, path)


def test_expired_deadline_aborts_without_model_or_reservation():
    with pytest.raises(TimeoutError):
        owner.check_deadline(0)


def test_missing_observer_pin_refuses_before_loader():
    ctx = {'helpers': SimpleNamespace(extension=lambda *a: pytest.fail('must not load an unbound observer'))}
    with pytest.raises(ValueError, match='authenticated scalar observer'):
        owner.frozen_observer(ctx, {'inputs': {}})


def test_durable_save_flushes_file_and_directories_before_return(tmp_path, monkeypatch):
    directory = tmp_path / 'panel'
    directory.mkdir()
    path = directory / 'trace.json'
    flushed = []
    original = owner.os.fsync

    def observed(fd):
        flushed.append(fd)
        return original(fd)

    monkeypatch.setattr(owner.os, 'fsync', observed)
    reference = owner.durable_save(save, path, {'trace': True})
    assert reference['sha256'] == owner.sha(path)
    assert len(flushed) == 3


def test_changed_saved_payload_refuses_before_durability_assertion(tmp_path, monkeypatch):
    def changed(path, value):
        reference = save(path, value)
        path.write_text('{"changed":true}')
        return reference

    monkeypatch.setattr(owner.os, 'fsync', lambda *a: pytest.fail('altered payload must refuse first'))
    with pytest.raises(ValueError, match='saved diagnostic payload differs'):
        owner.durable_save(changed, tmp_path / 'trace.json', {'old': True})


@pytest.mark.parametrize('mutation', [None, 'producer_pin', 'resident_boundary', 'observer_boundary'])
def test_observer_retains_exact_frozen_dependency_identities(monkeypatch, mutation):
    # Read source bytes only. The loader is stubbed and executes no package/model.
    path = P / owner.OBSERVER
    wanted = owner.sha(path)
    assert wanted == owner.OBSERVER_SHA256
    boundary, fields, core = object(), object(), object()
    observer = SimpleNamespace(boundary=boundary, fields=fields, core=core)
    calls = []

    def loader(root, relative, name, pins):
        calls.append((root, relative, name, pins))
        return observer

    ctx = dict(owners=dict(contextual_generated_boundary_training=boundary, generated_field_training=fields),
        core=core, helpers=SimpleNamespace(extension=loader),
        paraphrase_manifest={'producer_pins': {str(path): wanted}})
    monkeypatch.setitem(owner.sys.modules, owner.PREFIX + 'contextual_generated_boundary_training', boundary)
    monkeypatch.setitem(owner.sys.modules, owner.PREFIX + 'generated_field_training', fields)
    if mutation == 'producer_pin':
        ctx['paraphrase_manifest']['producer_pins'][str(path)] = 'bad'
    elif mutation == 'resident_boundary':
        monkeypatch.setitem(owner.sys.modules, owner.PREFIX + 'contextual_generated_boundary_training', object())
    elif mutation == 'observer_boundary':
        observer.boundary = object()
    if mutation is not None:
        with pytest.raises(ValueError):
            owner.frozen_observer(ctx, {'inputs': {str(path): wanted}})
        assert len(calls) == (mutation == 'observer_boundary')
    else:
        assert owner.frozen_observer(ctx, {'inputs': {str(path): wanted}}) is observer
        assert ctx['owners']['generated_scalar_observation'] is observer
        assert calls == [(P, owner.OBSERVER, owner.PREFIX + 'generated_scalar_observation',
            {owner.OBSERVER: wanted})]

"""Adversarial transport, source and independently replayed-claim checks."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import types
import zipfile

import pytest


SCRIPT=Path(__file__).resolve().parents[3]/'scripts/ops/legal_ir/replay_born_alive_width.py'
SPEC=importlib.util.spec_from_file_location('width_replay_owner_under_test',SCRIPT)
owner=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(owner)


@pytest.fixture
def selected(monkeypatch):
    raw=b'{"checkpoint":"bounded test fixture"}\n'
    profile={**owner.PROFILES[384],'checkpoint_bytes':len(raw),'checkpoint_sha256':owner.sha(raw)}
    monkeypatch.setitem(owner.PROFILES,384,profile)
    archive=owner.checkpoint_archive(raw)
    observation=dict(schema=owner.SCHEMA,dimension=384,measurement_scope=owner.SCOPE,
        checkpoint_sha256=owner.sha(raw),checkpoint_archive_sha256=owner.sha(archive),
        source_hashes=['parent-a','parent-b'],source_spans=[dict(parent_sha256='parent-a',byte_start=10)],
        rows=[dict(native_embedding=[0.25,0.75],raw_prediction=dict(token_ids=[4,7],eos_reached=True))],
        metrics=dict(cosine_similarity=1.0,reconstruction_loss=0.0),**owner.FALSE)
    return raw,archive,observation


def forged_zip(raw,names=('checkpoint.json',),*,mode=stat.S_IFREG,comment=b''):
    target=io.BytesIO()
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            item=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            item.create_system=3
            item.external_attr=(mode|0o600)<<16
            item.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(item,raw)
        archive.comment=comment
    return target.getvalue()


def test_deterministic_actual_checkpoint_transport(selected):
    raw,archive,_=selected
    assert archive==owner.checkpoint_archive(raw)
    assert owner.unpack_checkpoint(archive,384)==raw
    assert owner.sha(archive)!=owner.sha(raw)


@pytest.mark.parametrize('names',[('other.json',),('../checkpoint.json',),('/checkpoint.json',),
    ('checkpoint.json','extra'),('checkpoint.json','checkpoint.json')])
def test_wrong_path_extra_or_duplicate_members_refused(selected,names):
    raw,_,_=selected
    with pytest.raises(ValueError):
        owner.unpack_checkpoint(forged_zip(raw,names),384)


def test_symlink_member_refused(selected):
    raw,_,_=selected
    with pytest.raises(ValueError):
        owner.unpack_checkpoint(forged_zip(raw,mode=stat.S_IFLNK),384)


def test_wrong_raw_checkpoint_refused(selected):
    raw,_,_=selected
    with pytest.raises(ValueError,match='actual selected checkpoint'):
        owner.unpack_checkpoint(owner.checkpoint_archive(b'x'*len(raw)),384)


def test_oversized_raw_and_archive_refused(selected,monkeypatch):
    raw,archive,_=selected
    monkeypatch.setattr(owner,'MAX_RAW_CHECKPOINT',len(raw)-1)
    with pytest.raises(ValueError):owner.unpack_checkpoint(archive,384)
    monkeypatch.setattr(owner,'MAX_CHECKPOINT_ARCHIVE',len(archive)-1)
    with pytest.raises(ValueError):owner.unpack_checkpoint(archive,384)


@pytest.mark.parametrize('suffix',[b'junk',b'PK\x05\x06',b'\x00'*100])
def test_trailing_or_truncated_archive_refused(selected,suffix):
    _,archive,_=selected
    with pytest.raises(ValueError):owner.unpack_checkpoint(archive+suffix,384)


def test_comment_refused(selected):
    raw,_,_=selected
    with pytest.raises(ValueError):owner.unpack_checkpoint(forged_zip(raw,comment=b'claim'),384)


@pytest.mark.parametrize('task',['LIRAE-WIDTH-8','LIRAE-WIDTH-4096','LIRAE-WIDTH-0384','x'])
def test_unapproved_dimensions_refused(task):
    with pytest.raises(ValueError):owner.dimension_for(task)


def test_required_pins_are_fixed_and_lightweight(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('pin API must not inspect current bytes')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    monkeypatch.setattr(Path,'stat',forbidden)
    for width,count in ((384,13),(768,12)):
        pins=owner.required_input_file_pins(width)
        assert len(pins)==count
        assert len({row['path'] for row in pins})==count
        assert all(Path(row['path']).is_absolute() and type(row['bytes']) is int
                   and len(row['sha256'])==64 for row in pins)
        assert sum(row['bytes'] for row in pins)<2*1024**3
        assert any(row['sha256']==owner.PARQUET_SHA256 and '/blobs/' in row['path'] for row in pins)
    with pytest.raises(ValueError):owner.required_input_file_pins(True)


def test_bad_archive_refused_before_any_encoder(selected,monkeypatch,tmp_path):
    _,_,claim=selected
    bad=b'not a checkpoint archive'
    claim['checkpoint_archive_sha256']=owner.sha(bad)
    monkeypatch.setattr(owner,'run_selected_profile',lambda *a,**k:pytest.fail('encoder called'))
    with pytest.raises(ValueError):
        owner.verify_observation(tmp_path,'LIRAE-WIDTH-384',claim,bad,output_directory=tmp_path/'private')


@pytest.mark.parametrize('change',['metric','prediction','native_vector','source_parent','source_offset',
                                  'extra_quality','checkpoint','authority'])
def test_forged_claim_refused_by_independent_result(selected,monkeypatch,tmp_path,change):
    raw,archive,expected=selected
    claim=deepcopy(expected)
    if change=='metric':claim['metrics']['reconstruction_loss']=0.25
    elif change=='prediction':claim['rows'][0]['raw_prediction']['token_ids'][0]=3
    elif change=='native_vector':claim['rows'][0]['native_embedding'][0]=0.5
    elif change=='source_parent':claim['source_hashes'][0]='invented'
    elif change=='source_offset':claim['source_spans'][0]['byte_start']=11
    elif change=='extra_quality':claim['qualified']=True
    elif change=='checkpoint':claim['checkpoint_sha256']='f'*64
    elif change=='authority':claim['source_semantics_verified']=True
    def replay(root,task_id,*,output_directory,checkpoint_bytes):
        assert checkpoint_bytes==raw
        return dict(observation=expected,replay_directory='private-independent-run')
    monkeypatch.setattr(owner,'run_selected_profile',replay)
    with pytest.raises(ValueError):
        owner.verify_observation(tmp_path,'LIRAE-WIDTH-384',claim,archive,output_directory=tmp_path/'private')


def test_valid_claim_requires_independent_execution(selected,monkeypatch,tmp_path):
    raw,archive,claim=selected
    calls=[]
    def replay(root,task_id,*,output_directory,checkpoint_bytes):
        calls.append((root,task_id,checkpoint_bytes))
        return dict(observation=claim,replay_directory='independent')
    monkeypatch.setattr(owner,'run_selected_profile',replay)
    assert owner.verify_observation(tmp_path,'LIRAE-WIDTH-384',claim,archive,
        output_directory=tmp_path/'private')['verified'] is True
    assert calls==[(tmp_path,'LIRAE-WIDTH-384',raw)]


def taskdir(root):
    return root/'docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-384'


def test_outside_output_refused_before_replay(tmp_path,monkeypatch):
    root=tmp_path/'repo';root.mkdir()
    outside=tmp_path/'outside'
    monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--root',str(root),'--task-id','LIRAE-WIDTH-384',
                                   '--output-directory',str(outside)])
    monkeypatch.setattr(owner,'run_selected_profile',lambda *a,**k:pytest.fail('replay called'))
    with pytest.raises(ValueError):owner.main()
    assert not outside.exists()


def test_output_symlink_ancestor_refused(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    (root/'docs').symlink_to(outside,target_is_directory=True)
    try:
        with pytest.raises(OSError):owner.output_directory(root,'LIRAE-WIDTH-384',taskdir(root))
        assert list(outside.iterdir())==[]
    finally:
        (root/'docs').unlink()


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_existing_output_alias_refused(tmp_path,kind):
    root=tmp_path/'repo';directory=taskdir(root);directory.mkdir(parents=True)
    victim=tmp_path/'victim';victim.write_bytes(b'preserve')
    if kind=='symlink':(directory/'observation.json').symlink_to(victim)
    else:(directory/'observation.json').hardlink_to(victim)
    try:
        with pytest.raises(ValueError):owner.output_directory(root,'LIRAE-WIDTH-384',directory)
        assert victim.read_bytes()==b'preserve'
    finally:
        (directory/'observation.json').unlink()


def test_all_file_conflict_check_precedes_any_output_write(tmp_path):
    root=tmp_path/'repo';directory=taskdir(root);directory.mkdir(parents=True)
    (directory/'receipt.json').write_bytes(b'old receipt')
    expected={name:b'new '+name.encode() for name in owner.OUTPUT_NAMES}
    with pytest.raises(ValueError,match='conflicting'):
        owner.publish_outputs(root,'LIRAE-WIDTH-384',directory,expected)
    assert sorted(p.name for p in directory.iterdir())==['receipt.json']
    assert (directory/'receipt.json').read_bytes()==b'old receipt'


def test_exact_three_outputs_idempotent_and_receipt_last(tmp_path,monkeypatch):
    root=tmp_path/'repo';root.mkdir();directory=taskdir(root)
    payloads={name:name.encode() for name in owner.OUTPUT_NAMES}
    writes=[]
    original=owner.os.open
    def observed(path,flags,*args,**kwargs):
        if flags & owner.os.O_EXCL:writes.append(path)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(owner.os,'open',observed)
    owner.publish_outputs(root,'LIRAE-WIDTH-384',directory,payloads)
    assert writes==list(owner.OUTPUT_NAMES)
    witness={p.name:p.stat().st_ino for p in directory.iterdir()}
    owner.publish_outputs(root,'LIRAE-WIDTH-384',directory,payloads)
    assert {p.name:p.stat().st_ino for p in directory.iterdir()}==witness
    assert sorted(witness)==sorted(owner.OUTPUT_NAMES)


def test_independent_metric_domain_and_nonfinite_refusal():
    assert owner.independent_metrics([1.0,2.0],[1.0,2.0])=={
        'cosine_similarity':1.0,'reconstruction_loss':0.0}
    assert owner.independent_metrics([1.0,0.0],[0.0,1.0])=={
        'cosine_similarity':0.0,'reconstruction_loss':1.0}
    with pytest.raises(ValueError):owner.independent_metrics([float('nan')],[1.0])


@pytest.mark.parametrize('target',['checkpoint','checkpoint_size','preprocessing','donor','parent'])
def test_bad_fixed_input_pin_refused_before_asset_or_model_load(tmp_path,monkeypatch,target):
    profile=owner.PROFILES[384]
    def supplied(path,maximum=None):
        path=str(path)
        if path.endswith('selected-state.json'):
            result=dict(path=path,bytes=profile['checkpoint_bytes'],sha256=profile['checkpoint_sha256'])
            selected='checkpoint'
        elif path.endswith('preprocessing.json'):
            result=dict(path=path,bytes=profile['preprocessing_bytes'],sha256=profile['preprocessing_sha256'])
            selected='preprocessing'
        elif Path(path)==owner.DONOR:
            result=dict(path=path,bytes=614534,sha256=owner.DONOR_SHA256);selected='donor'
        else:
            result=dict(path=path,bytes=374277662,sha256=owner.PARQUET_SHA256);selected='parent'
        if selected==target:result['sha256']='0'*64
        if selected=='checkpoint' and target=='checkpoint_size':result['bytes']+=1
        return result
    monkeypatch.setattr(owner,'file_pin',supplied)
    monkeypatch.setattr(owner.importlib.util,'find_spec',lambda name:object())
    monkeypatch.setattr(owner,'load_file_module',lambda *a:pytest.fail('asset/model owner loaded'))
    with pytest.raises(ValueError):owner.preflight(tmp_path,'LIRAE-WIDTH-384')


def fake_parquet(monkeypatch,rows):
    class Batch:
        def to_pylist(self):return rows
    class File:
        def __init__(self,path):pass
        def iter_batches(self,**kwargs):
            assert kwargs['use_threads'] is False
            return iter([Batch()])
    package=types.ModuleType('pyarrow');package.__path__=[]
    parquet=types.ModuleType('pyarrow.parquet');parquet.ParquetFile=File
    package.parquet=parquet
    monkeypatch.setitem(sys.modules,'pyarrow',package)
    monkeypatch.setitem(sys.modules,'pyarrow.parquet',parquet)


@pytest.mark.parametrize('fault',['parent_hash','duplicate_parent','wrong_subsection'])
def test_physical_source_hash_uniqueness_and_literal_boundaries(tmp_path,monkeypatch,fault):
    text='prefix (b) As used in this section born alive. (c) Nothing in this section suffix'
    source=dict(owner.SOURCES[1],parent_sha256=owner.sha(text.encode()))
    row=dict(title_number='1',section_number='8',text=text)
    if fault=='parent_hash':row['text']=text+'changed'
    if fault=='wrong_subsection':
        row['text']=text.replace('(b) As used','(d) As used')
        source['parent_sha256']=owner.sha(row['text'].encode())
    monkeypatch.setattr(owner,'SOURCES',(source,))
    fake_parquet(monkeypatch,[row,row] if fault=='duplicate_parent' else [row])
    with pytest.raises(ValueError):owner.physical_sources(tmp_path)
    assert list(tmp_path.iterdir())==[]


# Inert protocol fixtures below establish input custody and exact dispatch;
# none is a genuine vector, original-producer receipt or numerical qualification.
def engineering_selection(tmp_path):
    return dict(schema=owner.ENGINEERING_SELECTION_SCHEMA,
        capture=dict(path=str(tmp_path/'capture.json'),bytes=2,sha256='a'*64),
        review=dict(path=str(tmp_path/'review.json'),bytes=2,sha256='b'*64))


def test_engineering_pin_declarations_are_metadata_only_detached_and_exclude_model(monkeypatch,tmp_path):
    def forbidden(*a,**k):raise AssertionError('metadata must not inspect inputs or import models')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    monkeypatch.setattr(Path,'stat',forbidden)
    selection=engineering_selection(tmp_path)
    for task_id in ('LIRAE-WIDTH-08','LIRAE-WIDTH-4096'):
        pins=owner.engineering_required_input_file_pins(task_id,selection)
        assert pins==[selection['capture'],selection['review']]
        assert max(pin['bytes'] for pin in pins)<=owner.ENGINEERING_MAX_BYTES
        pins[0]['sha256']='c'*64
        assert selection['capture']['sha256']=='a'*64


@pytest.mark.parametrize('case',['wrong_task','wrong_schema','extra_field','same_path','relative','traversal',
    'bad_hash','bool_bytes','zero_bytes','oversize','provider_output'])
def test_engineering_input_declarations_cannot_extend_authority_or_point_into_outputs(tmp_path,case):
    selection=engineering_selection(tmp_path);task_id='LIRAE-WIDTH-4096'
    if case=='wrong_task':task_id='LIRAE-WIDTH-384'
    elif case=='wrong_schema':selection['schema']='legacy'
    elif case=='extra_field':selection['authority']=True
    elif case=='same_path':selection['review']['path']=selection['capture']['path']
    elif case=='relative':selection['capture']['path']='capture.json'
    elif case=='traversal':selection['capture']['path']='/tmp/../capture.json'
    elif case=='bad_hash':selection['capture']['sha256']='asserted'
    elif case=='bool_bytes':selection['capture']['bytes']=True
    elif case=='zero_bytes':selection['capture']['bytes']=0
    elif case=='oversize':selection['capture']['bytes']=owner.ENGINEERING_MAX_BYTES+1
    else:selection['capture']['path']='/repo/docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-4096/successor-v2/capture.json'
    with pytest.raises(ValueError):owner.engineering_required_input_file_pins(task_id,selection)


def test_engineering_exact_input_reads_use_nonblocking_nofollow_and_check_bytes(tmp_path,monkeypatch):
    path=tmp_path/'selected.json';raw=b'{"fixture":"ordinary retained metadata"}\n';path.write_bytes(raw)
    pin=dict(path=str(path),bytes=len(raw),sha256=owner.sha(raw))
    observed=[];original=owner.os.open
    def opening(name,flags,*a,**k):
        if name==path.name:observed.append(flags)
        return original(name,flags,*a,**k)
    monkeypatch.setattr(owner.os,'open',opening)
    assert owner._engineering_read(pin)==raw
    assert len(observed)==1 and observed[0]&owner.os.O_NOFOLLOW and observed[0]&owner.os.O_NONBLOCK
    path.write_bytes(b'x'*len(raw))
    with pytest.raises(ValueError,match='changed or hash differs'):owner._engineering_read(pin)


def test_engineering_input_closing_link_custody_is_rechecked(tmp_path,monkeypatch):
    path=tmp_path/'selected.json';path.write_bytes(b'{}');pin=dict(path=str(path),bytes=2,sha256=owner.sha(b'{}'))
    original=owner.os.fstat;count=0
    def changed(fd):
        nonlocal count
        value=original(fd);count+=1
        if count==2:
            fields={name:getattr(value,name) for name in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_nlink')}
            fields['st_nlink']=2
            return types.SimpleNamespace(**fields)
        return value
    monkeypatch.setattr(owner.os,'fstat',changed)
    with pytest.raises(ValueError,match='changed or hash differs'):owner._engineering_read(pin)


@pytest.mark.parametrize('raw',[b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":-Infinity}'])
def test_engineering_json_rejects_ambiguous_or_nonfinite_receipts(raw):
    with pytest.raises(ValueError):owner._engineering_json(raw)


def review_fixture(tmp_path,monkeypatch):
    task_id='LIRAE-WIDTH-4096'
    capture=dict(task_id=task_id,native_operations=2,actual_source_forwards=4)
    raw=owner.wire(capture)+b'\n';path=tmp_path/'capture.json';path.write_bytes(raw)
    selection=engineering_selection(tmp_path)
    selection['capture']=dict(path=str(path),bytes=len(raw),sha256=owner.sha(raw))
    review=dict(schema=owner.ENGINEERING_REVIEW_SCHEMA,task_id=task_id,capture=selection['capture'],
        independently_reviewed=True,original_source_READ_closed=True,original_native_and_storage_released=True,
        native_operations=2,actual_source_forwards=4,training_executed=False,completion_authority=False)
    review_path=tmp_path/'review.json'
    def store():
        body=owner.wire(review)+b'\n';review_path.write_bytes(body)
        selection['review']=dict(path=str(review_path),bytes=len(body),sha256=owner.sha(body))
    store()
    # This sentinel proves archive/gate control flow only, never genuine capture authentication.
    expected={'fixture':'offline result'}
    monkeypatch.setattr(owner,'_engineering_observation',lambda value,pin:expected)
    return task_id,selection,review,store,raw,expected


@pytest.mark.parametrize('field',['independently_reviewed','original_source_READ_closed',
    'original_native_and_storage_released','completion_authority','training_executed','native_operations',
    'actual_source_forwards','capture','task_id'])
def test_engineering_selected_capture_requires_independent_review_and_original_closure(tmp_path,monkeypatch,field):
    task_id,selection,review,store,raw,expected=review_fixture(tmp_path,monkeypatch)
    if field in ('completion_authority','training_executed'):review[field]=True
    elif field in ('native_operations','actual_source_forwards'):review[field]=False
    elif field=='capture':review[field]={**review[field],'sha256':'c'*64}
    elif field=='task_id':review[field]='LIRAE-WIDTH-08'
    else:review[field]=False
    store()
    with pytest.raises(ValueError):owner._engineering_selected_capture(task_id,selection)


def test_engineering_offline_verifier_recomputes_against_selected_exact_archive_without_encoder(tmp_path,monkeypatch):
    task_id,selection,review,store,raw,expected=review_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(owner,'run_selected_profile',lambda *a,**k:pytest.fail('legacy encoder reached'))
    monkeypatch.setattr(owner,'_run_leanstral4096_repeatability',lambda *a,**k:pytest.fail('native capture reached'))
    monkeypatch.setattr(owner,'_run_spacy8_reconstruction',lambda *a,**k:pytest.fail('spaCy capture reached'))
    archive=owner.engineering_capture_archive(raw)
    verified=owner.verify_engineering_observation(tmp_path,task_id,expected,archive,selection=selection,output_directory=tmp_path)
    assert verified['verified'] is True and verified['validation_encoder_executions']==0
    assert verified['live_capability_reconstructed_from_receipt'] is False
    with pytest.raises(ValueError,match='exact independently selected'):
        owner.verify_engineering_observation(tmp_path,task_id,expected,archive+b'junk',selection=selection,output_directory=tmp_path)
    with pytest.raises(ValueError,match='independently replayed content differs'):
        owner.verify_engineering_observation(tmp_path,task_id,{'fixture':'forged'},archive,selection=selection,output_directory=tmp_path)


def test_engineering_task_publisher_is_versioned_and_keeps_original_outputs(tmp_path):
    root=tmp_path/'repo';root.mkdir();task_id='LIRAE-WIDTH-08'
    original=root/'docs/implementation/reports/evidence/legal_ir_autoencoder/lirae-width-08'
    original.mkdir(parents=True);(original/'receipt.json').write_bytes(b'original historical receipt')
    directory=original/'successor-v2'
    payloads={name:name.encode() for name in ('observation.json','capture.zip','receipt.json')}
    owner.publish_outputs(root,task_id,directory,payloads,engineering=True)
    witness={path.name:path.stat().st_ino for path in directory.iterdir()}
    owner.publish_outputs(root,task_id,directory,payloads,engineering=True)
    assert (original/'receipt.json').read_bytes()==b'original historical receipt'
    assert witness=={path.name:path.stat().st_ino for path in directory.iterdir()}
    with pytest.raises(ValueError):owner.output_directory(root,task_id,original,engineering=True)


@pytest.mark.parametrize('package',['spacy','en_core_web_sm','numpy','thinc'])
@pytest.mark.parametrize('fault',['version','origin'])
def test_spacy_runtime_fences_actual_version_and_origin_without_importing_packages(tmp_path,monkeypatch,package,fault):
    versions=dict(spacy='3.8.14',en_core_web_sm='3.8.0',numpy='1.26.4',thinc='8.3.13')
    modules={name:types.SimpleNamespace(__version__=version,
        __file__=str(owner.SPACY8_MODEL_DIRECTORY.parent/name/'__init__.py')) for name,version in versions.items()}
    setattr(modules[package],'__version__' if fault=='version' else '__file__','wrong')
    monkeypatch.setattr(owner.importlib,'import_module',lambda name:modules[name])
    monkeypatch.setattr(owner,'file_pin',lambda path,maximum:dict(path=str(path),bytes=123,sha256='a'*64))
    with pytest.raises(ValueError,match='runtime version/origin differs'):owner._spacy8_runtime()


def test_spacy_runtime_records_actual_package_source_identities_without_model_execution(monkeypatch):
    versions=dict(spacy='3.8.14',en_core_web_sm='3.8.0',numpy='1.26.4',thinc='8.3.13')
    modules={name:types.SimpleNamespace(__version__=version,
        __file__=str(owner.SPACY8_MODEL_DIRECTORY.parent/name/'__init__.py')) for name,version in versions.items()}
    monkeypatch.setattr(owner.importlib,'import_module',lambda name:modules[name])
    monkeypatch.setattr(owner,'file_pin',lambda path,maximum:dict(path=str(path),bytes=123,sha256='a'*64))
    result=owner._spacy8_runtime()
    assert {name:record['version'] for name,record in result.items()}==versions
    assert all(record['origin']['sha256']=='a'*64 for record in result.values())


# Genuine spaCy guard controls share this existing protected owner test.
import hashlib

def description_and_manifest():
    identity = dict(backend='local_en_core_web_sm', used_fallback_model=False,
        spacy_version='3.8.14', model_version='3.8.0',
        model_files_sha256='8dcaf7d0276e5e0adf7aba9daeb16042f69d962d9fa7f51c5e01822c17c47e10')
    config = dict(compute_device=dict(request='cpu', backend='torch_cpu', device='cpu'))
    manifest = dict(linguistic_identity=deepcopy(identity), effective_configuration=deepcopy(config))
    description = dict(training_profile='legacy-linguistic-features-8d/v1',
        linguistic_identity=identity,
        linguistic_identity_sha256='54a6867209ed68230035571dc80a6a01c3f18905a9b43ab42c7e8474c74462d5',
        effective_configuration=config,
        reconstruction_objective='historical_target_aware_safe_projection',
        reconstruction_is_fidelity_evidence=False, formula_training_executed=False,
        admitted=False, formalized=False, semantic_qualification=False,
        independent_formula_generation=False)
    return description, manifest


def test_spacy8_successor_preserves_distinct_producer_and_measurement_scope():
    assert owner.SPACY8_SUCCESSOR_PROFILE_ID == 'spacy_linguistic8_frozen_feature_reconstruction/v2'
    assert owner.SPACY8_PROFILE_ID == 'legacy-linguistic-features-8d/v1'
    assert owner.SPACY8_MEASUREMENT_SCOPE == 'target_aware_linguistic_feature_reconstruction_not_formula_fidelity'
    description, manifest = description_and_manifest()
    owner._spacy8_model_contract(description, manifest)


@pytest.mark.parametrize('case', [
    'empty', 'seven-wide', 'nine-wide', 'integer', 'boolean', 'nan', 'infinite', 'zero-direction',
], ids=['empty', 'seven-wide', 'nine-wide', 'integer', 'boolean', 'nan', 'infinite', 'zero-direction'])
def test_spacy8_refuses_reshaped_nonfinite_or_undefined_coordinates(case):
    vectors = {'empty': [], 'seven-wide': [1.0] * 7, 'nine-wide': [1.0] * 9,
        'integer': [1] * 8, 'boolean': [True] * 8,
        'nan': [float('nan')] + [0.0] * 7, 'infinite': [float('inf')] + [0.0] * 7,
        'zero-direction': [0.0] * 8}
    with pytest.raises(ValueError):
        owner._spacy8_vector(vectors[case])


def test_spacy8_finite_metrics_compare_feature_coordinates_without_quality_claim():
    target = [1.0] + [0.0] * 7
    predicted = [0.5] + [0.0] * 7
    assert owner._spacy8_vector(target) == target
    measured = owner._spacy8_metrics(owner.independent_metrics(target, predicted))
    assert measured == {'cosine_similarity': 1.0, 'reconstruction_loss': 0.03125}
    assert owner.independent_metrics(target, target)['reconstruction_loss'] == 0.0
    assert all(owner.FALSE[key] is False for key in
               ('quality_qualified', 'source_semantics_verified', 'learned_reconstruction_demonstrated',
                'statutory_fidelity_qualified', 'proof_authority'))


@pytest.mark.parametrize('case', [
    'missing-loss', 'boolean', 'cosine-high', 'cosine-low', 'negative-loss', 'infinite-loss', 'nan-cosine',
], ids=['missing-loss', 'boolean', 'cosine-high', 'cosine-low', 'negative-loss', 'infinite-loss', 'nan-cosine'])
def test_spacy8_refuses_nonfinite_or_false_metric_claims(case):
    claims = {
        'missing-loss': {'cosine_similarity': 1.0},
        'boolean': {'cosine_similarity': True, 'reconstruction_loss': 0.0},
        'cosine-high': {'cosine_similarity': 1.01, 'reconstruction_loss': 0.0},
        'cosine-low': {'cosine_similarity': -1.01, 'reconstruction_loss': 0.0},
        'negative-loss': {'cosine_similarity': 1.0, 'reconstruction_loss': -0.1},
        'infinite-loss': {'cosine_similarity': 1.0, 'reconstruction_loss': float('inf')},
        'nan-cosine': {'cosine_similarity': float('nan'), 'reconstruction_loss': 0.0}}
    with pytest.raises(ValueError):
        owner._spacy8_metrics(claims[case])


@pytest.mark.parametrize('field,value', [
    ('training_profile', 'retained_contextual_8'),
    ('reconstruction_objective', 'autonomous_source_text_reconstruction'),
    ('reconstruction_is_fidelity_evidence', True),
    ('formula_training_executed', True),
    ('admitted', True),
    ('independent_formula_generation', True),
], ids=['foreign-profile', 'wrong-objective', 'fidelity-claim', 'training-claim', 'legal-authority', 'formula-claim'])
def test_spacy8_rejects_incompatible_profile_and_fidelity_authority(field, value):
    description, manifest = description_and_manifest()
    description[field] = value
    with pytest.raises(ValueError):
        owner._spacy8_model_contract(description, manifest)


@pytest.mark.parametrize('field,value', [
    ('backend', 'historical_blank_en'), ('used_fallback_model', True),
    ('spacy_version', '0.0.0'), ('model_version', '0.0.0'),
    ('model_files_sha256', '0' * 64),
], ids=['blank-profile', 'fallback', 'spacy-version', 'model-version', 'model-bytes'])
def test_spacy8_rejects_even_self_consistent_substituted_backend(field, value):
    description, manifest = description_and_manifest()
    description['linguistic_identity'][field] = value
    manifest['linguistic_identity'][field] = value
    with pytest.raises(ValueError):
        owner._spacy8_model_contract(description, manifest)


def test_spacy8_retained_state_fence_accepts_unchanged_and_rejects_updates():
    state = {'feature_family_logits': {'feature': {'deontic': 0.125}}, 'decoded_embeddings': {}}
    original = owner.wire(state)
    owner._spacy8_unchanged(original, deepcopy(state), 'weights/state')
    state['feature_family_logits']['feature']['deontic'] = 0.25
    with pytest.raises(ValueError, match='weights/state changed'):
        owner._spacy8_unchanged(original, state, 'weights/state')


@pytest.mark.parametrize('count', [0, 1, 3], ids=['absent', 'one-source', 'extra-source'])
def test_spacy8_rejects_wrong_occurrence_population_before_product_import(monkeypatch, tmp_path, count):
    def forbidden(*args, **kwargs):
        pytest.fail('source rejection must precede any product/model import')
    monkeypatch.setattr(owner.importlib, 'import_module', forbidden)
    with pytest.raises(ValueError, match='both exact complete'):
        owner._run_spacy8_reconstruction(tmp_path, [{}] * count, [])


@pytest.mark.parametrize('field,value', [
    ('byte_start', 14850), ('char_start', 14849),
    ('span_sha256', '0' * 64), ('full_parent_coverage', True),
], ids=['shifted-byte', 'char-byte-confusion', 'changed-span-hash', 'invented-parent-coverage'])
def test_spacy8_rejects_different_source_coordinate_contract(field, value):
    spans = deepcopy(list(owner._SPACY8_SOURCE_SPANS))
    spans[0][field] = value
    with pytest.raises(ValueError, match='coordinates/hash differ'):
        owner._spacy8_validate_sources([{}, {}], spans)


def test_spacy8_original_file_pin_reads_exact_bytes_and_rejects_replacement(tmp_path):
    path = tmp_path / 'retained-core.json'
    raw = b'{"source":"pure regular-file guard fixture"}'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert owner._spacy8_fixed_file(path, len(raw), digest) == raw
    path.write_bytes(b'x' * len(raw))
    with pytest.raises(ValueError, match='authentication failed'):
        owner._spacy8_fixed_file(path, len(raw), digest)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink'], ids=['symlink', 'hardlink'])
def test_spacy8_original_file_pin_refuses_aliases(tmp_path, kind):
    path, alias = tmp_path / 'retained.json', tmp_path / 'alias.json'
    raw = b'{"source":"physical guard fixture"}'
    path.write_bytes(raw)
    if kind == 'symlink':
        alias.symlink_to(path)
    else:
        alias.hardlink_to(path)
    try:
        with pytest.raises(ValueError):
            owner._spacy8_fixed_file(alias, len(raw), hashlib.sha256(raw).hexdigest())
    finally:
        alias.unlink()

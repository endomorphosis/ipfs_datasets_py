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
    with pytest.raises(OSError):owner.output_directory(root,'LIRAE-WIDTH-384',taskdir(root))
    assert list(outside.iterdir())==[]


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_existing_output_alias_refused(tmp_path,kind):
    root=tmp_path/'repo';directory=taskdir(root);directory.mkdir(parents=True)
    victim=tmp_path/'victim';victim.write_bytes(b'preserve')
    if kind=='symlink':(directory/'observation.json').symlink_to(victim)
    else:(directory/'observation.json').hardlink_to(victim)
    with pytest.raises(ValueError):owner.output_directory(root,'LIRAE-WIDTH-384',directory)
    assert victim.read_bytes()==b'preserve'


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

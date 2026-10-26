"""Version3 feed custody uses real local Arrow/DuckDB and inert transport only."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal import span_cache_feed as feed_owner
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache
from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
    inventory_uscode_source_coordinates, uscode_source_coordinates_sha256,
)
from tests.unit.logic.test_span_cache_feed import A, Remote, open_feed
from tests.unit.logic.test_span_cache_paired_feed import source_row, _FailDurableReady


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()


def coordinate_fixture(tmp_path, *, version=3, indices=(1,3), label="coordinate-feed"):
    """A four-span report, with a two-span original-index subset by default."""
    tmp_path.mkdir(parents=True,exist_ok=True)
    documents=[{"entry_cid":"fixture-cid-1","legal_id":"usc:us:5:551","title":"5","section":"551",
                "text":"  The café shall retain records.\r\n It may publish them.  "},
               {"entry_cid":"fixture-cid-2","legal_id":"usc:us:5:552","title":"5","section":"552",
                "text":"\tThe clerk shall keep a journal.\nThe clerk may inspect it. "}]
    report=inventory_uscode_source_coordinates(documents,query="ipfs_uscode",release_id="fixture-source-release")
    pin=uscode_source_coordinates_sha256(report)
    source=SpanCache(tmp_path/'producer-source.duckdb')
    try:
        source.enqueue_source_coordinates(report,documents,expected_report_sha256=pin,
            query=report['query'],release_id=report['release_id'])
        selected=[report['spans'][index]['source_span_id'] for index in indices]
        exported=source.export_source_coordinates(pin,source_span_ids=selected)
    finally:
        source.close()
    observations=[]
    for row in exported['rows']:
        value=source_row(span=row['source_span_id'],text=row['text'],release=report['release_id'],guided=False)
        value.update(legal_id=row['legal_id'],source_provenance_json=row['source_provenance_json'])
        observations.append(value)
    options=({'source_coordinate_report':exported['report'],
              'expected_source_coordinate_report_sha256':pin} if version==3 else {})
    bundle=paired.build_paired_census(observations,agent_id=label,code_identity='synthetic:test',
                                    model_identity='diagnostic:test',release_id=report['release_id'],**options)
    published=paired.write_paired_census_bundle(bundle,tmp_path/'producer')
    files={published['manifest']['path_in_repo']:Path(published['manifest']['path']),
           **{published[kind]['path_in_repo']:Path(published[kind]['path']) for kind in paired.TABLE_NAMES}}
    root=(tmp_path/'retained'/A).absolute()
    for name,path in files.items():
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    raw=Path(published['manifest']['path']).read_bytes()
    entry={'path':published['manifest']['path_in_repo'],'type':'file','size':len(raw),
           'oid':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
    return {'bundle':bundle,'exported':exported,'report':report,'pin':pin,'published':published,
            'root':root,'manifest':root/entry['path'],'entry':entry,'files':files,
            'remote':Remote([entry],files),'observations':observations}


def load_fixture(case, *, root=None):
    root=case['root'] if root is None else root
    return feed_owner.load_paired_payload(root/case['entry']['path'],repository_root=root,
        repository_id=paired.REPOSITORY,path_in_repo=case['entry']['path'],
        expected_manifest_sha256=case['published']['manifest']['sha256'],
        max_bytes=64*1024**2,max_rows=128,max_decoded_bytes=64*1024**2)


def test_v3_feed_retains_one_full_report_and_original_subset_references(tmp_path):
    case=coordinate_fixture(tmp_path/'source')
    with open_feed(tmp_path/'reader',case['remote']) as feed:
        result=feed.poll_once()
        assert result['errors']==[]
        assert result['source_coordinate_reports']=={case['pin']:case['report']}
        assert len(result['records'])==2
        assert {record['source_coordinate_span_index'] for record in result['records']}=={1,3}
        for record in result['records']:
            reference=json.loads(record['source_provenance_json'])
            assert reference['report_sha256']==record['source_coordinate_report_sha256']==case['pin']
            assert reference['span_index']==record['source_coordinate_span_index']
            assert 'report' not in record and 'source_coordinate_report' not in record
            assert record['observations'][0]['coordinate_transport']['report_sha256']==case['pin']
            assert record['admitted'] is record['formalized'] is record['qualified'] is False
        assert result['enqueued'] is result['training_executed'] is False
        assert feed.poll_once()['records']==result['records']
    with open_feed(tmp_path/'reader',case['remote']) as reopened:
        assert reopened.poll_once()['source_coordinate_reports']==result['source_coordinate_reports']


def test_v3_identity_binds_report_and_index_without_changing_v2_identity(tmp_path):
    current=coordinate_fixture(tmp_path/'v3')
    legacy=coordinate_fixture(tmp_path/'v2',version=2)
    with open_feed(tmp_path/'reader3',current['remote']) as feed:
        v3=feed.poll_once()['records']
    with open_feed(tmp_path/'reader2',legacy['remote']) as feed:
        v2=feed.poll_once()['records']
    assert {row['source_span_id'] for row in v2}=={row['source_span_id'] for row in v3}
    assert not ({row['record_id'] for row in v2}&{row['record_id'] for row in v3})
    for record in v2:
        old_identity={key:record[key] for key in ('repository_id','source_span_id','legal_id','source_text_sha256','source_revision')}
        assert record['record_id']=='sha256:'+hashlib.sha256(encoded(old_identity)).hexdigest()
        assert 'source_provenance_json' not in record
    assert [row['observation_id'] for row in current['bundle']['paired_spans']]==[
        row['observation_id'] for row in legacy['bundle']['paired_spans']]


def test_v3_moved_layout_preserves_report_and_record_identity(tmp_path):
    case=coordinate_fixture(tmp_path/'source')
    original=load_fixture(case)
    moved=(tmp_path/'another-machine'/A).absolute();shutil.copytree(case['root'],moved)
    replayed=load_fixture(case,root=moved)
    assert paired.validate_paired_source_coordinates(original)==paired.validate_paired_source_coordinates(replayed)
    def records(bundle):
        return feed_owner.paired_source_records(bundle,repository_id=paired.REPOSITORY,
            revision=A,manifest_in_repo=case['entry']['path'])
    before,after=records(original),records(replayed)
    assert [row['record_id'] for row in before]==[row['record_id'] for row in after]
    assert [row['source_provenance_json'] for row in before]==[row['source_provenance_json'] for row in after]


def test_rehashed_wrong_v3_report_pin_stays_pending_without_records(tmp_path):
    case=coordinate_fixture(tmp_path/'source')
    manifest=json.loads(case['manifest'].read_text());manifest['coordinate_transport']['report_sha256']='0'*64
    fingerprint=hashlib.sha256(encoded({key:value for key,value in manifest.items()
                                      if key not in ('fingerprint','path_in_repo')})).hexdigest()
    name=manifest['path_in_repo'].replace(manifest['fingerprint'],fingerprint)
    manifest.update(fingerprint=fingerprint,path_in_repo=name);raw=encoded(manifest)
    path=tmp_path/'forged-manifest.json';path.write_bytes(raw)
    files={**case['files'],name:path}
    entry={'path':name,'type':'file','size':len(raw),'oid':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
    with open_feed(tmp_path/'reader',Remote([entry],files)) as feed:
        result=feed.poll_once()
        assert result['records']==[] and result['new_bundles']==[]
        assert result['counts']=={'pending':1}
        assert 'source_coordinate_reports' not in result
        assert result['errors'][0]['phase']=='bundle'


@pytest.mark.parametrize('phase',['update','commit'])
def test_failed_v3_ready_commit_exposes_neither_records_nor_report(tmp_path,phase):
    case=coordinate_fixture(tmp_path/'source')
    with open_feed(tmp_path/'reader',case['remote']) as feed:
        manager=feed._manager;feed._manager=_FailDurableReady(manager,case['entry']['path'],phase)
        failed=feed.poll_once()
        assert failed['records']==[] and failed['new_bundles']==[]
        assert 'source_coordinate_reports' not in failed
        assert failed['decoded_bytes']==0 and failed['counts']=={'pending':1}
        feed._manager=manager
        recovered=feed.poll_once()
        assert recovered['errors']==[] and recovered['source_coordinate_reports']=={case['pin']:case['report']}


def test_v3_report_is_charged_to_ready_budget_and_recovers(tmp_path):
    case=coordinate_fixture(tmp_path/'source')
    with open_feed(tmp_path/'reader',case['remote']) as feed:
        ready=feed.poll_once();assert ready['errors']==[]
        failed=feed.poll_once(max_ready_bytes=ready['decoded_bytes']-1)
        assert failed['records']==[] and 'source_coordinate_reports' not in failed
        assert failed['counts']=={'pending':1}
        assert feed.poll_once()['records']==ready['records']


def test_v3_machine_shards_keep_exact_occurrence_identity(tmp_path):
    case=coordinate_fixture(tmp_path/'source');records=[]
    for index in range(3):
        with open_feed(tmp_path/f'reader-{index}',case['remote'],shard_count=3,shard_index=index) as feed:
            result=feed.poll_once();assert result['errors']==[];records.extend(result['records'])
    assert len(records)==len({record['record_id'] for record in records})==2
    assert {json.loads(record['source_provenance_json'])['span_index'] for record in records}=={1,3}


def test_legacy_attempt_projection_ignores_unvalidated_coordinate_fields(monkeypatch):
    """Projection/core-binding control; upstream numerical validation is stubbed."""
    import sys
    import types

    text='The clerk shall retain the record.'
    sample={'title':'5','section':'551','text':text,'citation':'5 U.S.C. 551'}
    legacy={'record_id':'sha256:'+'a'*64,'sample':sample,'source_span_id':'legacy-span',
            'text':text,'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'legal_id':'usc:us:5:551','document_id':'legacy-document','source_revision':'legacy-release'}
    source={**legacy,'source_coordinate_report_sha256':'0'*64,
            'source_coordinate_span_index':True,'source_provenance_json':'unvalidated-extra'}
    report={'source_provenance':{'source_record':source}}
    calls=[]
    attempts=types.ModuleType('ipfs_datasets_py.huggingface.autoencoder_span_attempts')
    def upstream_validator(value):
        assert value is report
        calls.append('upstream_validator_stub')
    attempts._validate=upstream_validator
    worker=types.ModuleType('ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker')
    class SampleRecord:
        @staticmethod
        def from_dict(value):
            assert value is sample
            calls.append('sample_validator_stub')
    worker.SampleRecord=SampleRecord
    monkeypatch.setitem(sys.modules,attempts.__name__,attempts)
    monkeypatch.setitem(sys.modules,worker.__name__,worker)
    row={'source_span_id':legacy['source_span_id'],'source_text':text,
         'source_text_sha256':legacy['source_text_sha256'],'legal_id':legacy['legal_id']}
    restored=feed_owner._attempt_source(row,{'qualification_attempt':report})
    assert restored==legacy
    assert calls==['upstream_validator_stub','sample_validator_stub']
    assert not any(key in restored for key in ('source_coordinate_report_sha256',
                   'source_coordinate_span_index','source_provenance_json'))
    # Exercise the real feed owner's source binding, not only its projection.
    with pytest.raises(feed_owner.FeedError,match='differs from census'):
        feed_owner._attempt_source({**row,'source_span_id':'foreign-span'},
                                   {'qualification_attempt':report})

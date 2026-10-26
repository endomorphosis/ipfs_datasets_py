"""Local v3 source enqueue preserves custody without importing native work."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import span_cache
from tests.unit.logic.test_span_cache_coordinate_feed import coordinate_fixture


@pytest.fixture
def cli(monkeypatch):
    root=Path(__file__).resolve().parents[3]
    path=root/'scripts/ops/legal_ir/import_span_cache_exchange.py'
    spec=importlib.util.spec_from_file_location('coordinate_source_cache_import_under_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def checked_candidate_source_tree():
        # Focused native startup uses path-only package containers. Assert the
        # exact candidate anchor here, without weakening the real CLI guard.
        package=sys.modules['ipfs_datasets_py']
        assert Path(module.ROOT).resolve()==root.resolve()
        assert list(package.__path__)==[str(root/'ipfs_datasets_py')]
        if getattr(package,'__file__',None) is not None:
            assert Path(package.__file__).resolve()==root/'ipfs_datasets_py/__init__.py'
        module.focused_source_pin_checked=True
    monkeypatch.setattr(module,'_pin_source_tree',checked_candidate_source_tree)
    def forbidden(*args,**kwargs):
        raise AssertionError('source-only import reached native/compiler/network work')
    for name in ('_pin_logic','_pin_accelerate','download_bundle','plan_import','materialize_import'):
        monkeypatch.setattr(module,name,forbidden)
    return module


def argv(case,cache,output,**changes):
    values={'manifest_pin':case['published']['manifest']['sha256'],'report_pin':case['pin'],**changes}
    return ['--manifest',str(case['manifest']),'--output',str(output),
            '--enqueue-source-cache',str(cache),'--paired-repository-root',str(case['root']),
            '--revision','a'*40,'--expected-manifest-sha256',values['manifest_pin'],
            '--expected-coordinate-report-sha256',values['report_pin']]


def test_local_v3_import_enqueues_only_selected_sources_and_preserves_full_report(tmp_path,cli,capsys):
    case=coordinate_fixture(tmp_path/'source');target=tmp_path/'new.duckdb';output=tmp_path/'import'
    assert cli.main(argv(case,target,output))==0
    receipt=json.loads(capsys.readouterr().out)
    assert cli.focused_source_pin_checked is True
    assert receipt['selected_observation_count']==receipt['spans_enqueued']==2
    assert receipt['complete_report_span_count']==4
    assert receipt['selected_span_indices']==[1,3]
    assert receipt['fresh_catalog'] is True and receipt['historical_backfill'] is False
    assert receipt['native_tasks_written'] is receipt['transferred_compiler_status'] is False
    assert receipt['formalized'] is receipt['admitted'] is receipt['training_authorized'] is False
    cache=span_cache.SpanCache(target)
    try:
        assert cache.read_source_coordinate_report(case['pin'])==case['report']
        assert cache.stats()['pending']==2 and cache.stats()['sealed']==0
        pending=cache.pending(limit=8)
        assert {row['source_span_id'] for row in pending}==set(receipt['selected_source_span_ids'])
        assert {json.loads(row['source_provenance_json'])['span_index'] for row in pending}=={1,3}
    finally:
        cache.close()
    assert len(list((output/'evidence').iterdir()))==4
    assert json.loads((output/'import-receipt.json').read_text())==receipt


@pytest.mark.parametrize('pin',['manifest','report'])
def test_stale_independent_pins_refuse_before_publication_or_evidence(tmp_path,cli,monkeypatch,pin):
    case=coordinate_fixture(tmp_path/'source');target=tmp_path/'new.duckdb';output=tmp_path/'import'
    def forbidden(*args,**kwargs):
        raise AssertionError('invalid external pin reached cache publication')
    monkeypatch.setattr(span_cache,'write_fresh_source_coordinate_cache',forbidden)
    with pytest.raises(ValueError):
        cli.main(argv(case,target,output,**{pin+'_pin':'0'*64}))
    assert not target.exists() and not output.exists()


@pytest.mark.parametrize('extra',[
    ['--materialize'],['--database','unused.duckdb'],['--accelerate-root','unused'],
    ['--shard-count','2'],['--shard-index','1'],['--packet-directory','unused'],
    ['--staging-directory','unused'],['--max-bytes',str(64*1024**2+1)],
    ['--max-decoded-bytes','0'],['--max-decoded-bytes',str(64*1024**2+1)],
])
def test_source_only_profile_rejects_native_remote_and_unbounded_modes(tmp_path,cli,extra):
    case=coordinate_fixture(tmp_path/'source');target=tmp_path/'new.duckdb';output=tmp_path/'import'
    with pytest.raises(ValueError):
        cli.main([*argv(case,target,output),*extra])
    assert not target.exists() and not output.exists()


def test_v2_cannot_be_silently_upgraded_by_source_cache_flag(tmp_path,cli):
    case=coordinate_fixture(tmp_path/'source',version=2);target=tmp_path/'new.duckdb';output=tmp_path/'import'
    with pytest.raises(ValueError,match='explicit paired-v3'):
        cli.main(argv(case,target,output))
    assert not target.exists() and not output.exists()


def test_existing_legacy_catalog_bytes_and_identity_are_never_modified(tmp_path,cli):
    case=coordinate_fixture(tmp_path/'source');target=tmp_path/'existing.duckdb'
    cache=span_cache.SpanCache(target)
    try:
        cache.enqueue([{'source_span_id':case['exported']['rows'][0]['source_span_id'],
                        'text':case['exported']['rows'][0]['text'],
                        'legal_id':case['exported']['rows'][0]['legal_id']}])
    finally:
        cache.close()
    before=target.stat();pin=hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='fresh'):
        cli.main(argv(case,target,tmp_path/'import'))
    after=target.stat()
    assert hashlib.sha256(target.read_bytes()).hexdigest()==pin
    assert (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)==(
        before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)


def test_fresh_publication_failure_does_not_emit_success_receipt(tmp_path,cli,monkeypatch):
    case=coordinate_fixture(tmp_path/'source');target=tmp_path/'new.duckdb';output=tmp_path/'import'
    def fail(*args,**kwargs):
        raise OSError('injected prepublication failure')
    monkeypatch.setattr(span_cache,'write_fresh_source_coordinate_cache',fail)
    with pytest.raises(OSError,match='prepublication'):
        cli.main(argv(case,target,output))
    assert not target.exists() and not (output/'import-receipt.json').exists()
    assert len(list((output/'evidence').iterdir()))==4


def test_moved_bundle_import_retains_same_semantic_pin_and_original_indices(tmp_path,cli,capsys):
    import shutil
    case=coordinate_fixture(tmp_path/'source')
    moved=tmp_path/'different-machine'/('a'*40)
    shutil.copytree(case['root'],moved)
    case={**case,'root':moved,'manifest':moved/case['entry']['path']}
    assert cli.main(argv(case,tmp_path/'new.duckdb',tmp_path/'import'))==0
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['source_coordinates_report_sha256']==case['pin']
    assert receipt['selected_span_indices']==[1,3]


def test_source_pins_require_explicit_enqueue_flag_before_any_io(tmp_path,cli):
    with pytest.raises(ValueError,match='require --enqueue-source-cache'):
        cli.main(['--manifest',str(tmp_path/'absent.json'),'--output',str(tmp_path/'absent'),
                  '--expected-coordinate-report-sha256','0'*64])
    assert not (tmp_path/'absent').exists()

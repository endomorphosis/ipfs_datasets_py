"""Real file-backed manifest discovery, native owner joins and explicit migration."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.integration.logic.software_contracts.test_codebase_scan_policy import current
from ipfs_datasets_py.duckdb_control import intent_codebase_catalog as module
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.source_corpus_catalog import SourceCorpusCatalog,SourceCatalogLimits
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead, CodebaseHeadConflict
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import build_codebase_semantic_manifest


@pytest.fixture
def case(current):
    root,index,prepare,scheduler,cx=current
    (root/'main.py').write_text('def increment(n: int) -> int:\n    return n + 1\n')
    policy=prepare()
    head=CodebaseHead.from_dict(policy['head'])
    contract=IntegerOffsetContract('main.py','increment','n',1)
    def semantic(c=contract):
        return build_codebase_semantic_manifest(index,policy_receipt_cid=policy['receipt_cid'],contracts=(c,))['manifest_cid']
    manifest=semantic()
    def publish(owner, operation='publish', **kwargs):
        return owner.publish(root,expected_head=head,manifest_cid=manifest,operation_id=operation,scheduler=scheduler,**kwargs)
    def lookup(owner, **kwargs):
        return owner.lookup(root,expected_head=head,policy_receipt_cid=policy['receipt_cid'],path='main.py',scheduler=scheduler,**kwargs)
    return current,policy,head,contract,semantic,manifest,publish,lookup


def test_native_projection_replays_full_inventory_without_new_authority(case):
    current,policy,head,contract,_,manifest,publish,lookup=case
    index=current[1]
    owner=module.IntentCodebaseCatalog(index)
    result=publish(owner)
    value=owner.get(result['record_cid'])
    assert value['semantic_manifest_cid']==manifest
    assert len(value['units'])==7
    assert value['authority']['source_observed_live'] is False
    assert not any(value['authority'].values())
    assert value['model'] is value['corpus'] is None
    assert lookup(owner,contract_cid=contract.cid)['records']==[dict(record_cid=result['record_cid'],record=value)]
    assert publish(owner)==result
    assert publish(owner,'second-operation')==result
    assert index.current(head.repository_id)==head
    assert current[4].execute('SELECT count(*) FROM intent_codebase.records').fetchone()[0]==1
    assert current[4].execute('SELECT count(*) FROM intent_codebase.operations').fetchone()[0]==2
    assert current[4].execute("SELECT table_name FROM information_schema.tables WHERE table_schema='intent_codebase' ORDER BY table_name").fetchall()==[('meta',),('operations',),('records',),('selectors',)]


def test_explicit_file_backed_migration_preserves_records_and_adds_bounded_queries(case):
    current,_,_,_,_,_,publish,lookup=case
    owner=module.IntentCodebaseCatalog(current[1],create_storage_version=1)
    result=publish(owner)
    before=owner.get(result['record_cid'])
    with pytest.raises(module.IntentCodebaseCatalogError,match='explicit storage migration'): lookup(owner)
    report=owner.migrate()
    assert owner.storage_version==2
    assert report['records_preserved']==1 and report['selectors_derived']==7
    assert owner.get(result['record_cid'])==before
    assert lookup(owner)['records'][0]['record']==before
    with pytest.raises(module.IntentCodebaseCatalogError,match='version fence'): owner.migrate()
    assert module.IntentCodebaseCatalog(current[1]).get(result['record_cid'])==before


@pytest.mark.parametrize('damage',['artifact','selector','record','schema','operation','oversized_record','unknown_version'])
def test_corrupted_persistence_never_returns_discovery(case,damage):
    current,_,_,_,_,_,publish,lookup=case
    owner=module.IntentCodebaseCatalog(current[1]);result=publish(owner);cid=result['record_cid'];cx=current[4]
    if damage=='artifact': current[1].artifacts.path_for(cid).write_bytes(b'{}')
    elif damage=='selector': cx.execute("DELETE FROM intent_codebase.selectors WHERE path='broken.py'")
    elif damage=='record': cx.execute('UPDATE intent_codebase.records SET manifest_cid=?',[cid])
    elif damage=='schema': cx.execute('ALTER TABLE intent_codebase.records ADD COLUMN unexpected VARCHAR')
    elif damage=='operation': cx.execute('DELETE FROM intent_codebase.operations')
    elif damage=='oversized_record': current[1].artifacts.path_for(cid).write_bytes(b'x'*(owner.limits.max_record_bytes+1))
    else: cx.execute('UPDATE intent_codebase.meta SET storage_version=19')
    with pytest.raises((module.IntentCodebaseCatalogError,ValueError,FileNotFoundError)): owner.get(cid)


def test_migration_failure_rolls_back_schema_and_keeps_v1_record(case):
    current,_,_,_,_,_,publish,_=case
    owner=module.IntentCodebaseCatalog(current[1],create_storage_version=1)
    result=publish(owner);path=current[1].artifacts.path_for(result['record_cid']);raw=path.read_bytes();path.write_bytes(b'{}')
    with pytest.raises(module.IntentCodebaseCatalogError):owner.migrate()
    assert current[4].execute('SELECT storage_version FROM intent_codebase.meta').fetchone()[0]==1
    path.write_bytes(raw)
    assert owner.migrate()['storage_version']==2


def test_operation_rebinding_and_capacity_roll_back(case):
    current,_,head,_,semantic,_,publish,_=case
    owner=module.IntentCodebaseCatalog(current[1],limits=module.IntentCodebaseCatalogLimits(max_records=1,max_operations=1))
    result=publish(owner)
    other=semantic(IntegerOffsetContract('main.py','increment','n',2))
    with pytest.raises(module.IntentCodebaseCatalogError,match='another discovery request'):
        owner.publish(current[0],expected_head=head,manifest_cid=other,operation_id='publish',scheduler=current[3])
    with pytest.raises(module.IntentCodebaseCatalogError,match='operation capacity'):
        publish(owner,'overflow')
    assert owner.get(result['record_cid'])
    assert current[4].execute('SELECT count(*) FROM intent_codebase.operations').fetchone()[0]==1


@pytest.mark.parametrize('limit',[True,0,17,-1])
def test_lookup_requires_strict_bounded_limits(case,limit):
    owner=module.IntentCodebaseCatalog(case[0][1])
    with pytest.raises(module.IntentCodebaseCatalogError,match='result bound'):case[7](owner,limit=limit)


def test_selector_filters_before_native_reconstruction_and_refuses_truncation(case,monkeypatch,tmp_path):
    current,_,head,contract,semantic,manifest,publish,lookup=case
    owner=module.IntentCodebaseCatalog(current[1]);publish(owner)
    contracts=[contract]+[IntegerOffsetContract('main.py','increment','n',k) for k in (2,3,4)]
    manifests=[manifest]
    for c in contracts[1:]:
        cid=semantic(c);manifests.append(cid)
        owner.publish(current[0],expected_head=head,manifest_cid=cid,operation_id='offset-'+str(c.offset),scheduler=current[3])
    original=module.load_codebase_semantic_manifest
    calls=[]
    def counted(*args,**kwargs):calls.append(args[1]);return original(*args,**kwargs)
    monkeypatch.setattr(module,'load_codebase_semantic_manifest',counted)
    start=time.monotonic()
    module.verify_policy_current(current[1],current[0],expected_head=head,receipt_cid=case[1]["receipt_cid"],scheduler=current[3])
    reconstruction_start=time.monotonic()
    linear=[counted(current[1],cid) for cid in manifests]
    reconstruction_seconds=time.monotonic()-reconstruction_start
    matches=[v for v in linear if any(r['declared_contract_cid']==contracts[-1].cid for r in v['units'])]
    module.verify_policy_current(current[1],current[0],expected_head=head,receipt_cid=case[1]["receipt_cid"],scheduler=current[3])
    baseline_seconds=time.monotonic()-start;assert len(calls)==4 and len(matches)==1
    calls.clear();start=time.monotonic()
    selected=lookup(owner,contract_cid=contracts[-1].cid,limit=1)
    projected_seconds=time.monotonic()-start
    assert len(selected['records'])==len(calls)==1
    report=dict(profile='four_explicit_contracts_one_current_source',linear_reconstructions=4,selector_reconstructions=1,
        linear_reconstruction_only_seconds=reconstruction_seconds,
        linear_including_live_fences_seconds=baseline_seconds,selector_including_live_fences_seconds=projected_seconds,
        scope='small fixture; no general speedup claim')
    print('DISCOVERY_MEASUREMENT='+json.dumps(report,sort_keys=True))
    calls.clear()
    with pytest.raises(module.IntentCodebaseCatalogError,match='result bound'):lookup(owner,limit=1)
    assert calls==[]


def test_live_source_changes_and_generation_aba_refuse_but_history_remains(case):
    current,_,head,_,_,_,publish,lookup=case
    owner=module.IntentCodebaseCatalog(current[1]);result=publish(owner)
    source=current[0]/'main.py';raw=source.read_bytes();source.write_bytes(raw+b'\n')
    with pytest.raises(StaleCodebaseError):lookup(owner)
    source.write_bytes(raw)
    current[2]('republished',head)
    with pytest.raises((StaleCodebaseError,CodebaseHeadConflict)):lookup(owner)
    assert owner.get(result['record_cid'])['source_head']==head.to_dict()


@pytest.mark.parametrize('boundary',['after_derive','after_publish','after_lookup'])
def test_live_source_fences_cover_successful_boundaries(case,monkeypatch,boundary):
    current,_,_,_,_,_,publish,lookup=case
    owner=module.IntentCodebaseCatalog(current[1])
    if boundary=='after_lookup':publish(owner)
    method='_derive' if boundary=='after_derive' else 'get' if boundary=='after_publish' else '_stored'
    original=getattr(owner,method)
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        (current[0]/'main.py').write_text('def increment(n: int) -> int:\n    return n + 99\n')
        return result
    monkeypatch.setattr(owner,method,changed)
    with pytest.raises(StaleCodebaseError):
        lookup(owner) if boundary=='after_lookup' else publish(owner)


def native_owners(tmp_path):
    from tests.unit.duckdb_control.test_autoencoder_registry import seed
    from tests.unit.duckdb_control.test_source_corpus_catalog import _package,_register
    registry=AutoencoderRegistry(tmp_path/'models.duckdb',tmp_path/'models')
    version=seed(registry,tmp_path)
    corpus=SourceCorpusCatalog(tmp_path/'corpus.duckdb',tmp_path/'packages',limits=SourceCatalogLimits(max_package_bytes=16*1024*1024,max_total_rows=256))
    package=_package(tmp_path/'source-export')
    registered=_register(corpus,package)
    return registry,version['version_id'],corpus,registered['version_id']


def test_native_model_and_corpus_versions_are_independently_verified_not_invented(case,tmp_path):
    registry,model_id,corpus,corpus_id=native_owners(tmp_path)
    try:
        owner=module.IntentCodebaseCatalog(case[0][1],model_registry=registry,corpus_catalog=corpus)
        result=case[6](owner,model_version_id=model_id,corpus_version_id=corpus_id)
        value=owner.get(result['record_cid'])
        assert value['model']['version_id']==model_id
        assert value['corpus']['version_id']==corpus_id
        assert value['model']['artifact_verified'] is True
        assert value['corpus']['verification']['current_package_verified'] is True
        assert value['association_semantics']=='declared_context_not_training_or_inference_provenance'
        assert registry.resolve_head('english','main') is None
        with pytest.raises(module.IntentCodebaseCatalogError):case[6](owner,'unknown',model_version_id='absent')
        registry.artifact_path(registry.get_version(model_id)['artifact']).write_bytes(b'tampered')
        with pytest.raises(ValueError):owner.get(result['record_cid'])
    finally:registry.close();corpus.close()


def test_missing_native_owner_or_swapped_root_refuses(case,tmp_path):
    registry,model_id,corpus,corpus_id=native_owners(tmp_path)
    try:
        owner=module.IntentCodebaseCatalog(case[0][1],model_registry=registry,corpus_catalog=corpus)
        result=case[6](owner,model_version_id=model_id,corpus_version_id=corpus_id)
        with pytest.raises(module.IntentCodebaseCatalogError,match='root binding'):
            module.IntentCodebaseCatalog(case[0][1])
        (tmp_path/'models').rename(tmp_path/'moved-models');(tmp_path/'models').mkdir()
        with pytest.raises(module.IntentCodebaseCatalogError,match='roots changed'):owner.get(result['record_cid'])
    finally:registry.close();corpus.close()


def test_actual_fresh_process_reopens_three_native_owners_and_migrated_projection(case,tmp_path):
    registry,model_id,corpus,corpus_id=native_owners(tmp_path)
    owner=module.IntentCodebaseCatalog(case[0][1],model_registry=registry,corpus_catalog=corpus,create_storage_version=1)
    result=case[6](owner,model_version_id=model_id,corpus_version_id=corpus_id)
    expected=owner.get(result['record_cid']);owner.migrate()
    registry.close();corpus.close();case[0][4].close()
    script='''
import json,sys,duckdb
from pathlib import Path
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.duckdb_control.intent_codebase_catalog import IntentCodebaseCatalog
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.source_corpus_catalog import SourceCorpusCatalog,SourceCatalogLimits
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
root=Path(sys.argv[1]);cx=duckdb.connect(str(root/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(root/'cas')
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
with AutoencoderRegistry(root/'models.duckdb',root/'models') as model, SourceCorpusCatalog(root/'corpus.duckdb',root/'packages',limits=SourceCatalogLimits(max_package_bytes=16*1024*1024,max_total_rows=256)) as corpus:
    owner=IntentCodebaseCatalog(index,model_registry=model,corpus_catalog=corpus)
    value=owner.get(sys.argv[2])
    if sys.argv[3]=='live':
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler,ResourceSchedulerConfig
        scheduler=GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=root/'child-resources.json',proof_resource_sampler=lambda:ProofHostResources(8,8192,8192),lane_reservations={},auto_renew_leases=False))
        query=owner.lookup(root/'repository',expected_head=CodebaseHead.from_dict(value['source_head']),policy_receipt_cid=value['policy_receipt_cid'],path='main.py',scheduler=scheduler)
        assert query['source_observed_live'] is True and query['records']==[dict(record_cid=sys.argv[2],record=value)]
    print(json.dumps(value,sort_keys=True))
cx.close()
'''
    process=subprocess.run([sys.executable,'-c',script,str(tmp_path),result['record_cid'],'live'],capture_output=True,text=True,timeout=30,env=dict(os.environ))
    assert process.returncode==0,process.stderr
    assert json.loads(process.stdout.splitlines()[-1])==expected
    (case[0][0]/'main.py').unlink()
    historical=subprocess.run([sys.executable,'-c',script,str(tmp_path),result['record_cid'],'historical'],capture_output=True,text=True,timeout=30,env=dict(os.environ))
    assert historical.returncode==0,historical.stderr
    assert json.loads(historical.stdout.splitlines()[-1])==expected


def test_missing_matching_selector_cannot_turn_into_a_complete_empty_answer(case):
    owner=module.IntentCodebaseCatalog(case[0][1]);case[6](owner)
    case[0][4].execute("DELETE FROM intent_codebase.selectors WHERE path='main.py'")
    with pytest.raises(module.IntentCodebaseCatalogError,match='selector membership'):case[7](owner)


def test_unknown_manifest_reference_and_orphan_selector_refuse(case):
    owner=module.IntentCodebaseCatalog(case[0][1]);result=case[6](owner)
    row=case[0][4].execute('SELECT * FROM intent_codebase.selectors LIMIT 1').fetchone()
    case[0][4].execute('INSERT INTO intent_codebase.selectors VALUES (?,?,?,?,?)',[result['record_cid']+'orphan',*row[1:]])
    with pytest.raises(module.IntentCodebaseCatalogError,match='orphan selector'):case[7](owner)


def test_normative_sql_shape_refuses_resealed_metadata(case):
    owner=module.IntentCodebaseCatalog(case[0][1]);result=case[6](owner);cx=case[0][4]
    cx.execute('ALTER TABLE intent_codebase.records ADD COLUMN extra VARCHAR')
    cx.execute('UPDATE intent_codebase.meta SET catalog_cid=?',[owner._catalog_identity()])
    with pytest.raises(module.IntentCodebaseCatalogError,match='columns differ'):owner.get(result['record_cid'])


def test_schema_definition_bytes_are_bounded_before_fetch(case):
    owner=module.IntentCodebaseCatalog(case[0][1]);result=case[6](owner)
    case[0][4].execute("ALTER TABLE intent_codebase.records ADD COLUMN extra VARCHAR DEFAULT '"+'x'*65537+"'")
    with pytest.raises(module.IntentCodebaseCatalogError,match='DDL definition exceeds'):owner.get(result['record_cid'])


def test_post_ddl_migration_failure_rolls_back_actual_native_schema(case,monkeypatch):
    owner=module.IntentCodebaseCatalog(case[0][1],create_storage_version=1);result=case[6](owner)
    before=owner.get(result['record_cid']);original=owner._counts
    def stopped():
        if owner._check_schema()==2:raise module.IntentCodebaseCatalogError('injected post-DDL failure')
        return original()
    with monkeypatch.context() as patch:
        patch.setattr(owner,'_counts',stopped)
        with pytest.raises(module.IntentCodebaseCatalogError,match='post-DDL'):owner.migrate()
    assert owner._check_schema()==1
    assert case[0][4].execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='intent_codebase' AND table_name='selectors'").fetchone()[0]==0
    assert owner.get(result['record_cid'])==before
    assert owner.migrate()['storage_version']==2


def test_native_source_head_write_fence_conflicts_with_other_file_backed_writer(case,monkeypatch,tmp_path):
    import duckdb
    owner=module.IntentCodebaseCatalog(case[0][1]);original=owner._counts;conflicts=[]
    other=duckdb.connect(str(tmp_path/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    def concurrent():
        other.execute('BEGIN')
        try:
            with pytest.raises(duckdb.TransactionException):
                other.execute('UPDATE codebase_control.heads SET generation=generation+1 WHERE repository_id=?',[case[2].repository_id])
        finally:other.execute('ROLLBACK')
        conflicts.append(True)
        return original()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner,'_counts',concurrent)
            # get() after commit calls _counts too. Stop fault injection then.
            original_get=owner.get
            def finished(cid):
                patch.setattr(owner,'_counts',original)
                return original_get(cid)
            patch.setattr(owner,'get',finished)
            result=case[6](owner)
        assert conflicts==[True]
        assert owner.get(result['record_cid'])
    finally:other.close()


@pytest.mark.parametrize('damage',['corpus_package','corpus_row','model_variant','model_oversized','model_fifo'])
def test_linked_native_owner_corruption_never_hydrates(case,tmp_path,damage):
    registry,model_id,corpus,corpus_id=native_owners(tmp_path)
    try:
        owner=module.IntentCodebaseCatalog(case[0][1],model_registry=registry,corpus_catalog=corpus)
        result=case[6](owner,model_version_id=model_id,corpus_version_id=corpus_id)
        if damage=='corpus_package':
            version=corpus.get_version(corpus_id)
            next(Path(version['package_directory']).rglob('*.parquet')).unlink()
        elif damage=='corpus_row':
            with corpus._transaction() as cx:cx.execute('DELETE FROM source_corpus.rows WHERE ordinal=0')
        elif damage=='model_variant':
            with registry._transaction() as cx:cx.execute("UPDATE autoencoder_control.variants SET manifest='{}'")
        else:
            path=registry.artifact_path(registry.get_version(model_id)['artifact'])
            if damage=='model_oversized':path.write_bytes(b'x'*(owner.limits.max_model_bytes+1))
            else:path.unlink();os.mkfifo(path)
        with pytest.raises((ValueError,OSError)):owner.get(result['record_cid'])
    finally:registry.close();corpus.close()


def test_corpus_verification_limits_checked_before_native_package_decode(case,tmp_path,monkeypatch):
    registry,model_id,corpus,corpus_id=native_owners(tmp_path)
    try:
        owner=module.IntentCodebaseCatalog(case[0][1],model_registry=registry,corpus_catalog=corpus)
        corpus.limits=SourceCatalogLimits()
        monkeypatch.setattr(corpus,'verify_version',lambda _:pytest.fail('unbounded owner package decode started'))
        with pytest.raises(module.IntentCodebaseCatalogError,match='owner limits exceed'):
            case[6](owner,corpus_version_id=corpus_id)
    finally:registry.close();corpus.close()


def test_active_external_ignore_change_is_fenced_even_when_source_population_matches(case):
    from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy import CodebaseScanPolicyError
    owner=module.IntentCodebaseCatalog(case[0][1]);case[6](owner)
    (case[0][0]/'.git/info/exclude').write_text('unseen-untracked-file\n')
    with pytest.raises(CodebaseScanPolicyError,match='external ignore'):case[7](owner)


def test_optional_corpus_dependency_is_not_imported_for_structural_discovery():
    script="import sys;import ipfs_datasets_py.duckdb_control.intent_codebase_catalog;assert 'ipfs_datasets_py.duckdb_control.source_corpus_catalog' not in sys.modules"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=15,env=dict(os.environ))
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('interrupt',[False,True])
def test_actual_write_guard_between_updates_is_invisible_and_rolls_back_on_interruption(case,tmp_path,monkeypatch,interrupt):
    import duckdb
    owner=module.IntentCodebaseCatalog(case[0][1]);cx=case[0][4];head=case[2]
    before=cx.execute('SELECT * FROM codebase_control.heads').fetchall()
    other=duckdb.connect(str(tmp_path/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    observed=[];original_current=owner.catalog._current
    class Interrupted(BaseException):pass
    class FaultBoundary:
        def execute(self,statement,*args):
            if statement=='UPDATE codebase_control.heads SET generation=? WHERE repository_id=?':
                # Test-only observation/fault injection between native writes.
                assert cx.execute('SELECT generation FROM codebase_control.heads').fetchone()==(-head.generation,)
                assert other.execute('SELECT * FROM codebase_control.heads').fetchall()==before
                other.execute('BEGIN')
                try:
                    with pytest.raises(duckdb.TransactionException,match='Conflict'):
                        other.execute('UPDATE codebase_control.heads SET generation=generation+1 WHERE repository_id=?',[head.repository_id])
                finally:other.execute('ROLLBACK')
                observed.append(True)
                if interrupt:raise Interrupted()
                owner._cx=cx
            return cx.execute(statement,*args)
    def install_after_initial_native_head_check(repository_id):
        value=original_current(repository_id)
        if not observed:owner._cx=FaultBoundary()
        return value
    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner.catalog,'_current',install_after_initial_native_head_check)
            if interrupt:
                with pytest.raises(Interrupted),owner.store._lock,owner.store._transaction():
                    owner._fence(head,write=True)
            else:
                with owner.store._lock,owner.store._transaction():owner._fence(head,write=True)
        owner._cx=cx
        assert observed==[True]
        assert cx.execute('SELECT * FROM codebase_control.heads').fetchall()==before
        assert owner.catalog.current(head.repository_id)==head
        assert cx.execute('SELECT count(*) FROM intent_codebase.records').fetchone()==(0,)
    finally:owner._cx=cx;other.close()


def test_competing_native_source_publication_refuses_under_discovery_write_fence(case,tmp_path,monkeypatch):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    current,_,head,_,_,_,publish,_=case
    owner=module.IntentCodebaseCatalog(current[1]);original=owner._counts;attempts=[]
    manifest=current[1].load(head.manifest_cid)
    projections=current[1].ingestor.get_publication(head.ast_revision_id).projections
    other_cx=duckdb.connect(str(tmp_path/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    other=CodebaseCatalog(DuckDBASTStore(connection=other_cx),current[1].artifacts)
    def contender():
        with pytest.raises(duckdb.TransactionException,match='Conflict'):
            other.publish(operation_id='competing-native-publication',manifest=manifest,expected_head=head,projections=projections)
        attempts.append(True)
        return original()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner,'_counts',contender)
            original_get=owner.get
            def finished(cid):patch.setattr(owner,'_counts',original);return original_get(cid)
            patch.setattr(owner,'get',finished)
            result=publish(owner)
        assert attempts==[True]
        assert other.current(head.repository_id)==current[1].current(head.repository_id)==head
        assert other.resolve_operation('competing-native-publication',other.request_identity(manifest,head)) is None
        assert owner.get(result['record_cid'])
    finally:other_cx.close()


def test_actual_sql_uniqueness_constraints_and_resealed_constraint_drift(case):
    import duckdb
    owner=module.IntentCodebaseCatalog(case[0][1]);result=case[6](owner);cx=case[0][4]
    with pytest.raises(duckdb.ConstraintException):
        cx.execute('INSERT INTO intent_codebase.records SELECT * FROM intent_codebase.records')
    with pytest.raises(duckdb.ConstraintException):
        cx.execute('INSERT INTO intent_codebase.selectors SELECT * FROM intent_codebase.selectors')
    cx.execute('CREATE TABLE intent_codebase.copy AS SELECT * FROM intent_codebase.records')
    cx.execute('DROP TABLE intent_codebase.records')
    cx.execute('ALTER TABLE intent_codebase.copy RENAME TO records')
    cx.execute('UPDATE intent_codebase.meta SET catalog_cid=?',[owner._catalog_identity()])
    with pytest.raises(module.IntentCodebaseCatalogError,match='columns differ|constraints differ'):owner.get(result['record_cid'])


def test_replaced_configured_owner_and_inherited_process_refuse(case,monkeypatch):
    owner=module.IntentCodebaseCatalog(case[0][1]);result=case[6](owner)
    with monkeypatch.context() as patch:
        patch.setattr(owner,'_pid',os.getpid()+1)
        with pytest.raises(module.IntentCodebaseCatalogError,match='owner/process changed'):owner.get(result['record_cid'])
    with monkeypatch.context() as patch:
        patch.setattr(owner,'model_registry',object())
        with pytest.raises(module.IntentCodebaseCatalogError,match='owner/process changed'):owner.get(result['record_cid'])

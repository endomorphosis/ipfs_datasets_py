"""Cold-bootstrap driver invariants only; no SDK, network, native or shared pool."""
import importlib.util
from pathlib import Path
import sys

import pytest

_PATH=Path(__file__).resolve().parents[4]/'benchmarks/bench_hyper_dotnet_bootstrap.py'
_SPEC=importlib.util.spec_from_file_location('test_cold_dotnet_driver',_PATH)
bench=importlib.util.module_from_spec(_SPEC);sys.modules[_SPEC.name]=bench
_SPEC.loader.exec_module(bench)


@pytest.fixture(autouse=True)
def no_runtime(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('unit benchmark test attempted runtime loading')
    monkeypatch.setattr(bench,'load_helper',forbidden)


def test_fresh_disjoint_roots_are_inert(tmp_path):
    output,work=bench.fresh_roots(tmp_path/'evidence',tmp_path/'large-live-prefix')
    assert not output.exists() and not work.exists()


@pytest.mark.parametrize('which',['output','work'])
def test_existing_root_refused(tmp_path,which):
    output,work=tmp_path/'evidence',tmp_path/'live'
    (output if which=='output' else work).mkdir()
    with pytest.raises(ValueError,match='fresh'):bench.fresh_roots(output,work)


@pytest.mark.parametrize('direction',['work_inside_evidence','evidence_inside_work','same'])
def test_live_trees_cannot_enter_evidence_inventory(tmp_path,direction):
    outer=tmp_path/'outer'
    output,work=(outer,outer/'live') if direction=='work_inside_evidence' else ((outer/'evidence',outer) if direction=='evidence_inside_work' else (outer,outer))
    with pytest.raises(ValueError,match='separate'):bench.fresh_roots(output,work)


def test_symbolic_parent_refused(tmp_path):
    real=tmp_path/'real';real.mkdir();link=tmp_path/'alias';link.symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError,match='symbolic'):bench.fresh_roots(link/'evidence',tmp_path/'live')


def receipt(tmp_path):
    # A unit-only mapping; no driver run/installation consumes this fixture.
    root=tmp_path/'sdk/dotnet-sdk-8.0.300-linux-arm64'
    return {'sdk_version':'8.0.300','runtime_version':'8.0.5','platform_id':'linux-aarch64','rid':'linux-arm64',
        'sdk_root':str(root),'executable':str(root/'dotnet'),'archive_path':str(tmp_path/'cache/sdk.tar.gz'),
        'archive_url':'https://example.invalid/unit-only','archive_sha512':'a'*128,'tree_sha256':'b'*64,
        'executable_sha256':'c'*64,'support_only':True,'authorizes_proof':False,'installed':True,
        'archive_verified':True,'tree_verified':True}


def test_identity_excludes_transient_receipt_status(tmp_path):
    fresh=receipt(tmp_path);cached={**fresh,'status':'already_present','version_probe':False}
    assert bench.sdk_identity(fresh)==bench.sdk_identity(cached)


@pytest.mark.parametrize('key,value',[
    ('sdk_version','9.0.0'),('runtime_version','8.0.6'),('support_only',False),('authorizes_proof',True),
    ('installed',False),('archive_verified',False),('tree_verified',False),
    ('archive_sha512','a'*64),('tree_sha256',''),('executable_sha256','short'),
])
def test_unverified_sdk_cannot_be_reported_as_success(tmp_path,key,value):
    row=receipt(tmp_path);row[key]=value
    with pytest.raises(AssertionError):bench.sdk_identity(row)


@pytest.mark.parametrize('mutation',[None,'archive','tree','host','kind'])
def test_inventory_binds_archive_tree_and_executable(tmp_path,mutation):
    identity=receipt(tmp_path)
    inventory={'schema':'dotnet-sdk-archive-inventory@1','archive_sha512':identity['archive_sha512'],
        'tree_sha256':identity['tree_sha256'],
        'entries':{'dotnet':{'kind':'file','sha256':identity['executable_sha256']}}}
    if mutation=='archive':inventory['archive_sha512']='d'*128
    elif mutation=='tree':inventory['tree_sha256']='d'*64
    elif mutation=='host':inventory['entries']['dotnet']['sha256']='d'*64
    elif mutation=='kind':inventory['entries']['dotnet']['kind']='dir'
    if mutation is None:bench.validate_inventory(inventory,identity)
    else:
        with pytest.raises(AssertionError):bench.validate_inventory(inventory,identity)


def commands(tmp_path):
    base=tmp_path/'sdk';published=base/'published/dotnet';cwd=tmp_path/'guarded'
    operations=[['-target:Restore','-property:RestorePackagesWithLockFile=true'],
                ['-target:Build','-property:Configuration=Release','-property:OutputPath='+str(cwd/'app')]]
    rows=[{'argv':[str(base/'stage/dotnet'),'--version'],'phase':'sdk-fresh','cwd':str(cwd),
            'owned_environment':{'DOTNET_CLI_HOME':str(cwd/'home')}},
          *[{'argv':[str(published),'msbuild','src/AutoHyper/AutoHyper.fsproj',*args],'phase':'engine-build','cwd':str(cwd),
            'owned_environment':{'DOTNET_CLI_HOME':str(cwd/'cache/home'),**bench.WORKLOAD_ENV}} for args in operations]]
    return base,published,rows


def test_staged_probe_and_published_build_routes(tmp_path):
    base,published,rows=commands(tmp_path)
    assert bench.validate_dotnet_routes(rows,base,published)==3


@pytest.mark.parametrize('key',list(bench.WORKLOAD_ENV))
@pytest.mark.parametrize('command_index',[1,2])
def test_restore_and_build_require_workload_isolation(tmp_path,key,command_index):
    base,published,rows=commands(tmp_path)
    rows[command_index]['owned_environment'][key]='unexpected'
    with pytest.raises(AssertionError,match='workload isolation'):
        bench.validate_dotnet_routes(rows,base,published)


@pytest.mark.parametrize('mutation',['cli_restore','wrong_project','missing_lockfile','output_outside'])
def test_msbuild_route_preserves_project_lockfile_and_guarded_output(tmp_path,mutation):
    base,published,rows=commands(tmp_path)
    if mutation=='cli_restore':rows[1]['argv']=[str(published),'restore','src/AutoHyper/AutoHyper.fsproj']
    elif mutation=='wrong_project':rows[1]['argv'][2]='foreign.fsproj'
    elif mutation=='missing_lockfile':rows[1]['argv'].pop()
    elif mutation=='output_outside':rows[2]['argv'][-1]='-property:OutputPath='+str(tmp_path/'outside')
    with pytest.raises(AssertionError,match='MSBuild'):
        bench.validate_dotnet_routes(rows,base,published)


@pytest.mark.parametrize('mutation',['foreign_sdk','wrong_build_sdk','escaped_home','missing_home','sdk_other_command','missing_restore','missing_version'])
def test_routing_requires_new_sdk_and_owned_first_use_paths(tmp_path,mutation):
    base,published,rows=commands(tmp_path)
    if mutation=='foreign_sdk':rows[0]['argv'][0]=str(tmp_path/'old/dotnet')
    elif mutation=='wrong_build_sdk':rows[1]['argv'][0]=str(base/'other/dotnet')
    elif mutation=='escaped_home':rows[0]['owned_environment']['DOTNET_CLI_HOME']=str(tmp_path/'foreign')
    elif mutation=='missing_home':rows[0]['owned_environment']={}
    elif mutation=='sdk_other_command':rows[0]['argv'][0]=str(base/'stage/other')
    elif mutation=='missing_restore':rows.pop(1)
    elif mutation=='missing_version':rows.pop(0)
    with pytest.raises(AssertionError):bench.validate_dotnet_routes(rows,base,published)


def test_streaming_archive_digest_binds_exact_bytes(tmp_path):
    import hashlib
    path=tmp_path/'archive';body=b'unit-only archive bytes';path.write_bytes(body)
    assert bench.digest(path,'sha512')==hashlib.sha512(body).hexdigest()
    path.write_bytes(body+b'changed')
    assert bench.digest(path,'sha512')!=hashlib.sha512(body).hexdigest()


def test_refusal_capture_is_bounded_and_request_specific():
    capture=bench.RefusalCapture()
    assert not capture.record({'request_id':'another-request'},request_id='owned',phase='probe')
    assert not capture.record(None,request_id='owned',phase='probe')
    assert not capture.record({'request_id':''},request_id='',phase='probe')
    for index in range(40):
        assert capture.record({'request_id':'owned','decision_cycle_at':index,
                               'sample':{'memory_stall_percent':index}},request_id='owned',phase='probe')
    result=capture.to_dict()
    assert result['observed_count']==40 and len(result['records'])==32
    assert [row['observation']['decision_cycle_at'] for row in result['records']]==list(range(8,40))
    assert all(row['phase']=='probe' for row in result['records'])


def test_refusal_capture_detaches_deciding_state_and_exports():
    capture=bench.RefusalCapture()
    observation={'request_id':'owned','sample':{'memory_stall_percent':3.5},'thresholds':{'memory_stall_percent':2}}
    capture.record(observation,request_id='owned',phase='sdk-fresh')
    observation['sample']['memory_stall_percent']=0
    first=capture.to_dict();first['records'][0]['observation']['thresholds']['memory_stall_percent']=99
    actual=capture.to_dict()['records'][0]['observation']
    assert actual['sample']['memory_stall_percent']==3.5
    assert actual['thresholds']['memory_stall_percent']==2

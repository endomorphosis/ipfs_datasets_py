"""Fresh .NET SDK acquisition, AutoHyper build/reuse and two real smoke cases.

The SDK and archive cache start absent; existing Spot is explicitly reused.
Production download/extraction/probes/builds and the real default scheduler run
unchanged. Cold means fresh filesystem destinations, not cold OS/network caches.
Large live SDK/build trees remain outside the evidence directory.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ACCELERATE=ROOT.parent/'ipfs_accelerate'
VERSION='8.0.300'
WORKLOAD_ENV={'DOTNET_SKIP_WORKLOAD_INTEGRITY_CHECK':'true',
              'DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE':'true',
              'DOTNET_NUGET_SIGNATURE_VERIFICATION':'true'}
OWNED_ENV=('DOTNET_ROOT','DOTNET_CLI_HOME','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','TMPDIR',
           'DOTNET_CLI_TELEMETRY_OPTOUT','DOTNET_SKIP_FIRST_TIME_EXPERIENCE','DOTNET_NOLOGO',*WORKLOAD_ENV)
IDENTITY_FIELDS=('sdk_version','runtime_version','platform_id','rid','sdk_root','executable','archive_path',
                 'archive_url','archive_sha512','tree_sha256','executable_sha256')


def require(condition,message):
    if not condition:raise AssertionError(message)


def digest(path,algorithm='sha256'):
    value=hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):value.update(chunk)
    return value.hexdigest()


def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');temporary.replace(path)


def fresh_roots(output,work):
    output=Path(output).expanduser().absolute();work=Path(work).expanduser().absolute()
    if output.exists() or work.exists() or output.is_symlink() or work.is_symlink():
        raise ValueError('evidence and work roots must both be fresh')
    if output.is_relative_to(work) or work.is_relative_to(output):
        raise ValueError('evidence and live work roots must be separate')
    if output.resolve()!=output or work.resolve()!=work:
        raise ValueError('fresh roots must not traverse symbolic links')
    return output,work


def sdk_identity(receipt):
    require(receipt['sdk_version']==VERSION and receipt['runtime_version']=='8.0.5','unexpected SDK/runtime version')
    require(receipt['support_only'] is True and receipt['authorizes_proof'] is False,'SDK acquired proof authority')
    require(receipt['installed'] and receipt['archive_verified'] and receipt['tree_verified'],'SDK identity not verified')
    require(len(receipt['archive_sha512'])==128 and len(receipt['tree_sha256'])==len(receipt['executable_sha256'])==64,
            'SDK identity digests incomplete')
    return {key:receipt[key] for key in IDENTITY_FIELDS}


def validate_inventory(inventory,receipt):
    require(inventory['schema']=='dotnet-sdk-archive-inventory@1','unexpected SDK inventory schema')
    require(inventory['archive_sha512']==receipt['archive_sha512'],'inventory archive identity mismatch')
    require(inventory['tree_sha256']==receipt['tree_sha256'],'inventory tree identity mismatch')
    host=inventory['entries']['dotnet']
    require(host['kind']=='file' and host['sha256']==receipt['executable_sha256'],
            'inventory executable identity mismatch')


class RefusalCapture:
    """Retain only this acquisition's actual decision records, never resample."""
    def __init__(self):
        self.observed_count=0
        self.records=[]

    def record(self,observation,*,request_id,phase):
        if not isinstance(observation,dict) or not request_id or observation.get('request_id')!=request_id:
            return False
        self.observed_count+=1
        self.records.append({'phase':phase,'observation':deepcopy(observation)})
        del self.records[:-32]
        return True

    def to_dict(self):
        return {'schema':'hyper-dotnet-admission-refusals@1','maximum_retained':32,
                'observed_count':self.observed_count,'records':deepcopy(self.records),
                'scope':'actual matching-request decisions copied during admission; no later-sample inference'}


def validate_dotnet_routes(commands,sdk_base,published):
    sdk_base=Path(sdk_base).resolve();published=Path(published).resolve()
    dotnet=[];operations=[]
    for row in commands:
        executable=Path(row['argv'][0])
        if executable.name!='dotnet':
            require(not row['phase'].startswith('sdk-'),'SDK phase launched an unexpected command')
            continue
        # A fresh staged probe precedes the final published executable.
        require(executable.is_relative_to(sdk_base),'dotnet command escaped the fresh SDK base')
        if row['phase']=='engine-build':require(executable==published,'AutoHyper did not use the new published SDK')
        environment=row['owned_environment']
        args=row['argv'][1:]
        if args==['--version']:
            operation='version'
        else:
            require(row['phase']=='engine-build','unexpected SDK phase command')
            prefix=['msbuild','src/AutoHyper/AutoHyper.fsproj']
            if args==prefix+['-target:Restore','-property:RestorePackagesWithLockFile=true']:
                operation='restore'
            elif args==prefix+['-target:Build','-property:Configuration=Release',
                              '-property:OutputPath='+str(Path(row['cwd'])/'app')]:
                operation='build'
            else:
                raise AssertionError('unexpected AutoHyper MSBuild target/project/output route')
            require(all(environment.get(key)==value for key,value in WORKLOAD_ENV.items()),
                    'AutoHyper build workload isolation controls missing')
        home=environment.get('DOTNET_CLI_HOME')
        require(home and Path(home).is_relative_to(Path(row['cwd'])),'dotnet first-use home escaped guarded cwd')
        dotnet.append(row);operations.append(operation)
    require('version' in operations,'real SDK version probe absent')
    require(operations.count('restore')==1,'one AutoHyper restore required')
    require(operations.count('build')==1,'one AutoHyper build required')
    return len(dotnet)


def load_helper(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def run(output,work,spot_root):
    sys.path[:0]=[str(ACCELERATE),str(ROOT)]
    build=load_helper('cold_dotnet_build_helpers','bench_hyper_native_setup.py')
    smoke=load_helper('cold_dotnet_smoke_helpers','bench_hyper_native_smoke.py')
    from ipfs_datasets_py.logic.backends.installers import dotnet_sdk as sdk, dotnet_sdk_archive as archive
    from ipfs_datasets_py.logic.backends.installers import install_control as control
    from ipfs_datasets_py.logic.backends import process
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources
    limits=control.HyperInstallLimits()
    paths=set(Path(path) for path in build.pins())|set(smoke.source_inventory())|{
        Path(__file__).resolve(),Path(sdk.__file__).resolve(),Path(archive.__file__).resolve(),
        ROOT/'tests/unit/logic/backends/test_hyper_dotnet_bootstrap_benchmark.py'}
    pins=lambda:{str(path):digest(path) for path in sorted(paths)}
    sdk_base,cache,engine_root=work/'sdk',work/'archives',work/'engines'
    result={'status':'running','work_root':str(work),'sdk_base':str(sdk_base),'archive_cache':str(cache),
        'engine_root':str(engine_root),'spot_root':str(spot_root),'limits':asdict(limits),
        'source_pins_before':pins(),'cold_paths_absent':all(not path.exists() for path in (sdk_base,cache,engine_root)),
        'scope':{'fresh_sdk_destination_and_cache':True,'cold_os_or_network_cache_claim':False,
            'existing_spot_reused':True,'synthetic_process_results_or_pins':False,'default_shared_admission':True,
            'full_toolchain_built_from_source':False,'semantic_witness_reconstruction_qualified':False,
            'new_proof_authority':False},'extractions':[]}
    started=time.monotonic();audit=None;native=None;refusals=RefusalCapture()
    try:
        snapshots=output/'sources';snapshots.mkdir()
        result['source_snapshots']={}
        for index,(path,value) in enumerate(result['source_pins_before'].items()):
            target=snapshots/f'{index:03d}-{Path(path).name}';target.write_bytes(Path(path).read_bytes())
            require(digest(target)==value,'source changed during snapshot')
            result['source_snapshots'][path]=str(target.relative_to(output))
        spot_files=[spot_root/'bin'/name for name in ('autfilt','ltl2tgba')]
        result['spot_before']=[build.file_evidence(path) for path in spot_files]
        require(result['cold_paths_absent'],'cold SDK/cache/build roots already exist')
        result['plan']=sdk.plan_dotnet_sdk_setup(install_root=sdk_base,archive_cache_root=cache)
        require(not sdk_base.exists() and not cache.exists(),'inert SDK plan wrote to fresh destinations')
        write(output/'partial.json',result)
        class Audit(build.Audit):
            def __enter__(self):
                try:
                    super().__enter__()
                    actual_refusal=scheduler.GlobalResourceScheduler._record_proof_refusal
                    def observe_refusal(owner,state,waiter,**kwargs):
                        returned=actual_refusal(owner,state,waiter,**kwargs)
                        active=self.admissions[-1] if self.admissions else None
                        if active and state is not None and refusals.record(state.get('last_proof_refusal'),
                                request_id=active['request'].get('request_id'),phase=self.phase):
                            write(output/'admission-refusals.json',refusals.to_dict())
                        return returned
                    self.stack.enter_context(patch.object(scheduler.GlobalResourceScheduler,
                        '_record_proof_refusal',observe_refusal))
                    actual=process.SubprocessExecutor.execute
                    def observe(executor,invocation,cancellation=None):
                        extra={key:invocation.environment[key] for key in OWNED_ENV if key in invocation.environment}
                        before=len(self.commands)
                        try:return actual(executor,invocation,cancellation)
                        finally:
                            if len(self.commands)>before:
                                self.commands[before]['owned_environment']=extra
                                self.commands[before]['environment_keys']=sorted(invocation.environment)
                                self.save()
                    self.stack.enter_context(patch.object(process.SubprocessExecutor,'execute',observe))
                    return self
                except BaseException:
                    self.stack.close()
                    raise
        with control.installation_scope(limits=limits) as operation:
            result['operation_deadline']=operation.deadline
            with ExitStack() as observers:
                extract=archive.extract_sdk_archive
                def observed_extract(*args,**kwargs):
                    inventory=extract(*args,**kwargs)
                    number=len(result['extractions'])+1
                    target=output/f'sdk-inventory-{number}.json';write(target,inventory)
                    result['extractions'].append({'inventory':target.name,'inventory_sha256':digest(target),
                        'tree_sha256':inventory['tree_sha256'],'compressed_bytes':inventory['compressed_bytes'],
                        'files':inventory['files'],'directories':inventory['directories'],'bytes':inventory['bytes']})
                    write(output/'partial.json',result)
                    return inventory
                observers.enter_context(patch.object(archive,'extract_sdk_archive',observed_extract))
                # Support either module-qualified or directly imported public
                # helper binding, without substituting its returned inventory.
                if getattr(sdk,'extract_sdk_archive',None) is extract:
                    observers.enter_context(patch.object(sdk,'extract_sdk_archive',observed_extract))
                with Audit(output) as audit:
                    audit.tool='dotnet-sdk';audit.phase='sdk-fresh'
                    receipt=sdk.ensure_dotnet_sdk(yes=True,install_root=sdk_base,archive_cache_root=cache)
                    result['sdk_receipt']=receipt
                    require(receipt['status']=='installed' and receipt['version_probe'],'fresh SDK did not execute its real probe')
                    sdk_identity(receipt)
                    published=Path(receipt['executable']);sdk_root=Path(receipt['sdk_root'])
                    require(sdk_root.is_relative_to(sdk_base) and published.parent==sdk_root,'SDK path escaped fresh base')
                    archive_path=Path(receipt['archive_path'])
                    require(archive_path.is_relative_to(cache),'archive escaped fresh cache')
                    result['sdk_archive']={'path':str(archive_path),'bytes':archive_path.stat().st_size,
                        'sha512':digest(archive_path,'sha512'),'sha256':digest(archive_path)}
                    require(result['sdk_archive']['sha512']==receipt['archive_sha512'],'downloaded SDK archive digest mismatch')
                    require(result['sdk_archive']['bytes']<=limits.max_download_bytes,'SDK archive exceeded configured cap')
                    result['sdk_executable']=build.file_evidence(published)
                    require(result['sdk_executable']['sha256']==receipt['executable_sha256'],'SDK host digest changed')
                    require(result['sdk_executable']['elf_machine']==(183 if receipt['rid']=='linux-arm64' else 62),
                            'SDK host ELF architecture mismatch')
                    result['sdk_manifest']=build.file_evidence(sdk_root/'.ipfs-dotnet-sdk.json')
                    write(output/'partial.json',result)
                    audit.tool='autohyper';audit.phase='engine-build'
                    engine=smoke.hp.ensure_autohyper
                    installed=engine(yes=True,strict=True,vendor=True,force=False,install_root=engine_root,
                        repo_root=ACCELERATE,dependency_roots={'dotnet-sdk':str(sdk_root),'spot':str(spot_root)})
                    result['engine_receipt']=installed.to_dict()
                    require(installed.status=='installed','fresh AutoHyper did not build')
                    result['engine_files']=build.validate_identity(smoke.hp,installed,engine_root)
                    require(dict(installed.identity.runtime_environment)['DOTNET_ROOT']==str(sdk_root),'AutoHyper runtime used another SDK')
                    dotnet_identity=next(item for item in installed.identity.dependency_identities if item.name=='dotnet')
                    require(dotnet_identity.executable==str(published) and dotnet_identity.executable_sha256==receipt['executable_sha256'],
                            'AutoHyper build dependency did not bind the fresh SDK')
                    audit.tool='dotnet-sdk';audit.phase='sdk-reuse';before=len(audit.commands)
                    cached=sdk.ensure_dotnet_sdk(yes=True,install_root=sdk_base,archive_cache_root=cache)
                    result['sdk_cached_receipt']=cached
                    require(cached['status']=='already_present' and not cached['version_probe'],'cached SDK unexpectedly rebuilt/reprobed')
                    require(sdk_identity(cached)==sdk_identity(receipt),'cached SDK identity changed')
                    require(len(audit.commands)==before,'cached SDK launched native work')
                    audit.tool='autohyper';audit.phase='engine-reuse'
                    reused=engine(yes=True,strict=True,vendor=True,force=False,install_root=engine_root,
                        repo_root=ACCELERATE,dependency_roots={'dotnet-sdk':str(sdk_root),'spot':str(spot_root)})
                    result['engine_cached_receipt']=reused.to_dict()
                    require(reused.status=='already_present' and reused.identity==installed.identity,'AutoHyper cache identity changed')
                    require(len(audit.commands)==before,'AutoHyper reuse launched native work')
                    result['dotnet_command_count']=validate_dotnet_routes(audit.commands,sdk_base,published)
                    for owner in audit.owners:
                        require(owner.config.proof_safety_enabled is True and owner.config.proof_resource_sampler is collect_proof_host_resources,
                                'actual host sampler/proof safety required')
                require(len(result['extractions'])==2,'fresh and cached SDK inventories must both be observed')
                for extraction in result['extractions']:
                    inventory_path=output/extraction['inventory']
                    require(digest(inventory_path)==extraction['inventory_sha256'],'captured SDK inventory changed')
                    validate_inventory(json.loads(inventory_path.read_text()),receipt)
                native_dir=output/'native-smoke';native_dir.mkdir()
                native=smoke.run(native_dir,engine_root,('autohyper',))
                result['native_smoke']={'result':'native-smoke/result.json','status':native['status'],
                    'elapsed_seconds':native['elapsed_seconds'],'cases':len(native['cases'])}
                require(native['status']=='passed_bounded_native_smoke' and len(native['cases'])==2,'real AutoHyper smoke checks incomplete')
                control.installation_checkpoint('after cold SDK and AutoHyper qualification')
        result['spot_after']=[build.file_evidence(path) for path in spot_files]
        require(result['spot_before']==result['spot_after'],'existing Spot changed')
        result['status']='passed_fresh_sdk_autohyper_build_and_smoke'
    except Exception as error:
        result.update(status='failed',exception_type=type(error).__name__,error=str(error),
                      block_reasons=list(getattr(error,'block_reasons',())))
    finally:
        write(output/'admission-refusals.json',refusals.to_dict())
        result['admission_refusals']={'path':'admission-refusals.json',
            'sha256':digest(output/'admission-refusals.json'),'observed_count':refusals.observed_count,
            'retained_count':len(refusals.records)}
        result.update(elapsed_seconds=time.monotonic()-started,source_pins_after=pins())
        if audit is not None:
            result.update(install_native_commands=len(audit.commands),install_native_launches=len(audit.launches),
                install_owned_leases_released=all(lease.released for lease in audit.leases),
                install_owned_processes_reaped=all(child.poll() is not None for child in audit.children))
        result['checks']={'stable_sources':result['source_pins_before']==result['source_pins_after'],
            'install_owned_cleanup':bool(result.get('install_owned_leases_released') and result.get('install_owned_processes_reaped')),
            'native_smoke_complete':bool(native and native['status']=='passed_bounded_native_smoke' and all(native['checks'].values()))}
        if result['status']=='passed_fresh_sdk_autohyper_build_and_smoke' and not all(result['checks'].values()):result['status']='failed'
        write(output/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--spot-root',type=Path,default=Path.home()/'.local/share/ipfs_datasets_py/theorem-provers/spot-2.12-linux-aarch64')
    args=parser.parse_args();output,work=fresh_roots(args.output_dir,args.work_root)
    if not args.spot_root.is_dir():parser.error('existing reviewed Spot root required')
    output.mkdir(parents=True)
    result=run(output,work,args.spot_root.resolve())
    print(json.dumps({key:result[key] for key in ('status','elapsed_seconds')}),flush=True)
    return 0 if result['status']=='passed_fresh_sdk_autohyper_build_and_smoke' else 1


if __name__=='__main__':raise SystemExit(main())

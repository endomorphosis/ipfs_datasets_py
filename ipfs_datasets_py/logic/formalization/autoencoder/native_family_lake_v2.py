"""Real, source-replayed modality Lake checks for native projection operators.

An issued execution handle is process-local evidence. Archived JSON, generic
schema builds, or a successful build of only a subset cannot establish complete
coverage. All unsupported projections remain explicitly blocked. These builds
check the generated interpretation/contract declarations, not source truth.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import sys
import weakref

from . import family_training as v1
from . import family_training_v2 as v2
from . import native_family_lean_emitters_v2 as emitters
from . import native_tla_projection as tla
from ...backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits

SCHEMA='native-family-modality-lake/v2'
LIBRARIES={'intent_ir':'IntentIR','security_ir':'SecurityIR','ui_ux_ir':'UIUXIR','legal_ir':'LegalIR'}
FALSE={'qualified':False,'admitted':False,'formalized':False,'proof_authority':False,
       'source_semantics_verified':False,'execution_authority':False,'promotion_performed':False}
_REGISTRY=weakref.WeakKeyDictionary()


def _raw(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _sha(raw): return hashlib.sha256(raw).hexdigest()
def _digest(value): return _sha(_raw(value))


def _static_pins():
    return {str(Path(path).resolve()):_sha(Path(path).read_bytes()) for path in
            (__file__,emitters.__file__,v1.__file__,v2.__file__, *(m.__file__ for m in emitters.PRODUCERS))}


_IMPORTED=_static_pins()


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_workspace, _pin_imported_module
    _pin_workspace()
    for module in (sys.modules[__name__], emitters, v1, v2): _pin_imported_module(module)
    if _static_pins()!=_IMPORTED: raise ValueError('native Lake implementation changed since import')


def _loaded_pins(report):
    # Bind the actual loaded native parser/owner sources in this process. Paths
    # must remain in this package tree; an editable HACC import is not equivalent.
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    root=Path(__file__).resolve().parents[3]
    result=dict(_static_pins())
    for name,module in tuple(sys.modules.items()):
        if not name.startswith('ipfs_datasets_py.logic.') or not getattr(module,'__file__',None): continue
        path=Path(module.__file__).resolve()
        if path.suffix!='.py': continue
        if root not in path.parents: raise ValueError('native Lake dependency outside chosen logic tree')
        result[str(path)]=_pin_imported_module(module)
    for name,digest in report['producer_pins'].items():
        path=root.joinpath(*name.split('.')[1:]);path=path.with_suffix('.py') if path.with_suffix('.py').is_file() else path/'__init__.py'
        if _sha(path.read_bytes())!=digest: raise ValueError('native projection producer changed')
        result[str(path.resolve())]=digest
    return result


def _check_pins(pins):
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    loaded={str(Path(module.__file__).resolve()):module for module in tuple(sys.modules.values()) if getattr(module,'__file__',None)}
    for name,digest in pins.items():
        path=Path(name)
        if not path.is_file() or _sha(path.read_bytes())!=digest: raise ValueError('native Lake source provenance changed')
        if name in loaded and _pin_imported_module(loaded[name])!=digest: raise ValueError('loaded native producer changed')


def _validate_report(report,source_inputs=None):
    if report.get('schema')==v1.SCHEMA: validator=v1.validate_family_training_report
    elif report.get('schema')==v2.SCHEMA: validator=v2.validate_family_training_report_v2
    elif report.get('schema')=='domain-family-training-targets/v3':
        validator=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.family_training_v3').validate_family_training_report_v3
    elif report.get('schema')=='domain-family-training-targets/v4':
        validator=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.family_training_v4').validate_family_training_report_v4
    else: raise ValueError('known native family producer schema required')
    validator(report,**(source_inputs or {}))


@dataclass(frozen=True,eq=False)
class NativeFamilyLakeExecution:
    """Only handles registered by an actual build can be verified in this process."""
    def to_dict(self):
        if self not in _REGISTRY: raise ValueError('unissued native Lake execution')
        return json.loads(_REGISTRY[self]['receipt'])


def prepare_native_family_lean(report,*,source_inputs):
    """Replay original typed inputs, then generate all supported projections.

    This preparation grants no Lake execution evidence. Missing emitters and
    annotations remain visible; callers cannot request a cheaper subset.
    """
    _guard()
    if type(source_inputs) is not dict or not source_inputs: raise ValueError('original typed source inputs required')
    _validate_report(report,source_inputs)
    report_digest=_digest(report)
    domain=report['domain_id'];library=LIBRARIES[domain]
    lines=['-- Actual native interpretation declarations; no source truth asserted.',
           'namespace '+library,emitters.PRELUDE]
    rows=[]
    for index,projection in enumerate(report['projections']):
        row={'projection_id':projection['projection_id'],'logic_family':projection['logic_family'],
             'profile':projection.get('profile'),'payload_sha256':_digest(projection['payload']),
             'source_digest':report['source_digest'],'source_sha256':report.get('source_sha256'),
             'target_sha256':projection['target_sha256'],'parser_status':'blocked','lake_status':'blocked',
             'semantic_lowering_supported':False,'reason':None,'lowering':None,**FALSE}
        try:
            if not projection['ready_for_training']: raise emitters.UnsupportedNativeLean('native_projection_not_ready')
            source,lowering=emitters.emit_projection(projection,report=report)
            if not source.strip(): raise emitters.UnsupportedNativeLean('empty_native_lowering')
            wrapped='namespace Projection_'+str(index)+'\n'+source+'\nend Projection_'+str(index)
            lines.append(wrapped)
            row.update(parser_status='passed',lake_status='not_run',semantic_lowering_supported=True,
                       lowering=lowering,lean_declarations_sha256=_sha(wrapped.encode()))
        except (emitters.UnsupportedNativeLean,ValueError,KeyError,TypeError,AttributeError,RecursionError) as exc:
            row['reason']=str(exc)[:2000]
        rows.append(row)
    lines += ['end '+library,'']
    source='\n\n'.join(lines)
    if len(source.encode())>4*1024*1024: raise ValueError('native Lean module exceeds byte bound')
    _validate_report(report,source_inputs)
    if _digest(report)!=report_digest: raise ValueError('native report mutated during preparation')
    _guard()
    return {'schema':SCHEMA,'domain_id':domain,'library':library,'report_sha256':report_digest,
        'source_digest':report['source_digest'],'source_sha256':report.get('source_sha256'),
        'requested_families':copy.deepcopy(report['requested_families']),
        'missing_requested_families':[row['family_id'] for row in report['family_inventory']
                                     if row['requested'] and not row['ready_for_training']],
        'per_projection':rows,'lean_source':source,'lean_source_sha256':_sha(source.encode()),
        'producer':_loaded_pins(report),'source_replay_passed':True,'backend_executed':False,
        'all_requested_projections_passed':False,'status':'prepared',
        'scope':'native typed/operator interpretation contracts, not source semantic fidelity or proposition truth',
        'dependencies':[],'download_calls':0,**FALSE}


def _execute(source,library,lake_executable,timeout_seconds):
    found=shutil.which(str(lake_executable))
    if found is None: return {'status':'unavailable','backend_executed':False,'reason':'lake_executable_missing'}
    executable=Path(found).absolute()
    if executable.parent.name=='bin' and executable.parent.parent.name=='.elan':
        return {'status':'unavailable','backend_executed':False,'reason':'select_installed_native_lake_not_elan_shim'}
    runtime=BoundedToolRunner()
    probe=runtime.run(ToolRunRequest(argv=(str(executable),'--version'),
        limits=ToolRunLimits(timeout_seconds=5,max_output_bytes=16384)))
    match=re.search(r'Lean version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)',probe.stdout)
    if not probe.ok or not match:
        return {'status':'unavailable','backend_executed':False,'reason':'native_lake_version_probe_failed',
                'version_stdout':probe.stdout,'version_stderr':probe.stderr}
    toolchain='leanprover/lean4:v'+match.group(1)
    files={'lakefile.toml':'name = "native_family_'+library.lower()+'"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "'+library+'"\n',
           'lean-toolchain':toolchain+'\n',library+'.lean':source}
    command=(str(executable),'build',library)
    result=runtime.run(ToolRunRequest(argv=command,input_files=files,environment={'ELAN_TOOLCHAIN':toolchain},
        limits=ToolRunLimits(timeout_seconds=timeout_seconds,cpu_seconds=timeout_seconds,max_output_bytes=262144,
                            max_input_bytes=5*1024*1024,max_workspace_bytes=128*1024*1024)))
    passed=result.ok and not result.output_truncated and not result.workspace_limit_exceeded
    return {'status':'passed' if passed else 'failed','backend_executed':True,'command':list(command),
            'toolchain':toolchain,'executable_sha256':_sha(executable.read_bytes()),
            'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr,
            'timed_out':result.timed_out,'output_truncated':result.output_truncated,
            'workspace_limit_exceeded':result.workspace_limit_exceeded,
            'input_files_sha256':{name:_sha(value.encode()) for name,value in files.items()}}


def build_native_family_lake(report,*,source_inputs,lake_executable,timeout_seconds=60,output_directory=None,java_executable=None,tla2tools_jar=None):
    """Run ``lake build <ModalityIR>`` on the exact regenerated native contract."""
    if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=60:
        raise ValueError('bounded native Lake timeout required')
    output=Path(output_directory).resolve() if output_directory is not None else None
    if output is not None and output.exists(): raise ValueError('fresh native Lake evidence directory required')
    receipt=prepare_native_family_lean(report,source_inputs=source_inputs)
    _check_pins(receipt['producer'])
    candidates=[row for row in receipt['per_projection'] if row['semantic_lowering_supported']]
    for row in candidates:
        requirements=row['lowering'].get('syntax_requirements',[])
        row['additional_syntax_checks']=[tla.check_sany(requirement,java_executable=java_executable,
            tla2tools_jar=tla2tools_jar,timeout_seconds=min(30,timeout_seconds)) for requirement in requirements]
        for check in row['additional_syntax_checks']:
            receipt['producer'].update(check.get('tool_sha256',{}))
        if any(check['status']!='passed' for check in row['additional_syntax_checks']):
            row['parser_status']='blocked'
            row['reason']='required_native_syntax_checker_not_passed'
    execution=_execute(receipt['lean_source'],receipt['library'],lake_executable,timeout_seconds) if candidates else {
        'status':'blocked','backend_executed':False,'reason':'no_supported_native_declarations'}
    if execution.get('executable_sha256') and execution.get('command'):
        receipt['producer'][str(Path(execution['command'][0]).resolve())]=execution['executable_sha256']
    _guard();_check_pins(receipt['producer']);_validate_report(report,source_inputs)
    if _digest(report)!=receipt['report_sha256']: raise ValueError('native report changed during Lake build')
    passed=execution['status']=='passed' and execution['backend_executed'] is True
    for row in candidates: row['lake_status']='passed' if passed else execution['status']
    complete=bool(receipt['per_projection']) and not receipt['missing_requested_families'] and all(
        row['lake_status']=='passed' and row['parser_status']=='passed' and row['semantic_lowering_supported']
        for row in receipt['per_projection'])
    receipt.update(backend_executed=execution['backend_executed'],execution=execution,
                   status='passed' if complete else 'partial' if passed else execution['status'],
                   all_requested_projections_passed=complete)
    if output is not None:
        output.mkdir(parents=True)
        (output/(receipt['library']+'.lean')).write_text(receipt['lean_source'])
        (output/'receipt.json').write_bytes(_raw(receipt))
    handle=NativeFamilyLakeExecution()
    _REGISTRY[handle]={'receipt':_raw(receipt),'report_sha256':receipt['report_sha256'],'producer':receipt['producer']}
    return handle


def verify_native_family_lake(execution,report,projection_id=None):
    """Authenticate live issued evidence and exact current report/source identity."""
    _guard()
    if type(execution) is not NativeFamilyLakeExecution or execution not in _REGISTRY:
        raise ValueError('live issued native modality Lake execution required; archived/schema receipts are insufficient')
    recorded=_REGISTRY[execution]
    _check_pins(recorded['producer']);_validate_report(report)
    if _digest(report)!=recorded['report_sha256']: raise ValueError('native Lake evidence belongs to another report')
    receipt=json.loads(recorded['receipt'])
    if projection_id is None: return receipt
    matches=[row for row in receipt['per_projection'] if row['projection_id']==projection_id]
    if len(matches)!=1: raise ValueError('native projection has no bound Lake observation')
    return matches[0]

"""Recover strict six-span evidence and separate parser/compiler/decompiler timing.

Run only within the existing isolated resource-owner pattern. No model, target
preparation, bridge evaluate, Lake build, database write, or publication occurs.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
OWNED = ROOT / 'workspace/test-logs/federal-corpus-audits'
INVENTORY = OWNED / 'source-span-batch-3-20260927-r2/capture-r1/outputs/source-inventory.json'
LOCK = ROOT.parent.parent / 'JevOps/jevops/statement_lock.py'
GATES = (
    'Company A shall submit backup report within 10 days unless emergency.',
    'The agency shall not disclose records.',
    'The officer shall retain the file for at least 20 days.',
)


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write(path, value):
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>2_000_000:
        raise ValueError('span evidence exceeds 2 MB bound')
    with path.open('xb') as handle:
        handle.write(raw);handle.flush();os.fsync(handle.fileno())


def verify(records):
    for item in records:
        path=Path(item['path'])
        info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.resolve()!=path
                or info.st_size!=item['bytes'] or sha(path)!=item['sha256']):
            raise ValueError('frozen source/input differs: '+str(path))


def canonical_loaded():
    for name,module in tuple(sys.modules.items()):
        if name=='ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'):
            raw=getattr(module,'__file__',None)
            if raw and not Path(raw).resolve().is_relative_to(ROOT/'ipfs_datasets_py'):
                raise ValueError('foreign datasets tree loaded: '+name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True)
    args=parser.parse_args()
    directory=args.output_directory.absolute()
    if directory.exists() or directory.resolve()!=directory or not directory.parent.is_dir() or not directory.is_relative_to(OWNED):
        raise ValueError('timing output must be a new owned audit directory')
    manifest_path=HERE/'span-timing-inputs.json'
    manifest=json.loads(manifest_path.read_bytes())
    if manifest.get('launch_ready') is not True:
        raise ValueError('span timing input manifest is not finalized')
    sealed=manifest['retained_artifacts']+manifest['validator_sources']
    verify(sealed)
    inventory=json.loads(INVENTORY.read_bytes())
    if len(inventory['spans'])!=3:
        raise ValueError('original three-span selection changed')
    for span in inventory['spans']:
        if hashlib.sha256(span['text'].encode()).hexdigest()!=span['span_text_sha256']:
            raise ValueError('retained span text hash differs')
    directory.mkdir()
    started=time.monotonic()
    receipt={'schema':'strict-six-span-timing-followup/v1','passed':False,'error':None,
        'gate_rows':[],'source_rows':[],'empty_vocabulary_checks':[], 'checks':{},
        'input_manifest_sha256':sha(manifest_path),'source_unchanged':False,
        'sample_count':6,'synthetic_gate_count':3,'real_us_code_span_count':3,
        'training_executed':False,'targets_generated':False,'lake_executed':False,
        'bridge_evaluate_executed':False,'bridge_names':[], 'legal_ir_target_count':None,
        'legal_ir_evaluate_provers':False,'metric_disk_cache':0,'worker_count':1,
        'admitted':False,'formalized':False,'constitution_processed':False,
        'concurrency_claim':False,'cold_speed_baseline_claim':False,
        'cache_observation':'Fresh standalone process. No metric bridge cache is used; OS page cache and host CPU contention are uncontrolled.',
        'timing_scope':'Separate wall times for vocabulary_from_clause, TypedDeonticCanonicalCompiler.compile, and decompile_rule. The compiler reparses; this measures the existing double-parse path.',
        'source_selection':'Exact prior inventory; no resampling or synthetic substitution for real U.S. Code.'}
    try:
        canonical_loaded()
        sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
        from ipfs_datasets_py.logic import autoformal
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
        from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary,CompilerRequest,OperationStatus,CanonicalErrorCode
        from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule
        receipt['tree_pin']=require_workspace_logic_tree();canonical_loaded()
        spec=importlib.util.spec_from_file_location('span_timing_statement_lock',LOCK)
        lock=importlib.util.module_from_spec(spec);sys.modules[spec.name]=lock;spec.loader.exec_module(lock)
        compiler=TypedDeonticCanonicalCompiler()
        selections=[{'text':text,'source_span_id':f'synthetic-timing-gate-{index}','synthetic':True}
                    for index,text in enumerate(GATES)]
        selections.extend({**span,'synthetic':False} for span in inventory['spans'])
        for index,span in enumerate(selections):
            text=span['text'];before=time.monotonic()
            vocabulary=autoformal.vocabulary_from_clause(text);parsed=time.monotonic()
            if vocabulary is not None and (not isinstance(vocabulary,dict) or not all(isinstance(atom,str) for atoms in vocabulary.values() for atom in atoms)):
                raise ValueError('vocabulary must contain only parser-supplied string atoms')
            result=compiler.compile(CompilerRequest(source_text=text,request_id=span['source_span_id'],
                atom_vocabulary=autoformal._vocabulary(vocabulary),allow_explicit_partial=False))
            compiled=time.monotonic()
            rules=result.canonical_ir.rules if result.canonical_ir else ()
            rendered=[decompile_rule(rule) for rule in rules];decompiled=time.monotonic()
            temporal_records=autoformal._temporal_records(text);sidecar_finished=time.monotonic()
            row={'source':span,'synthetic':span['synthetic'],'parser_vocabulary':vocabulary,
                'compiler_status':result.status.value,'compiler_status_scope':'native OperationStatus; success is not admission',
                'rules':[rule.to_dict() for rule in rules],'parser_temporal_records':temporal_records,
                'decompiled':rendered,'diagnostic_fields':autoformal._diagnostic_fields(result),
                'error':None if result.error is None else {'code':result.error.code.value,'message':result.error.message},
                'vocabulary_seconds':parsed-before,'compiler_seconds':compiled-parsed,
                'decompiler_seconds':decompiled-compiled,'wall_seconds':decompiled-before,
                'temporal_sidecar_seconds':sidecar_finished-decompiled,'evidence_wall_seconds':sidecar_finished-before,
                'allow_partial':False,'admitted':False,'formalized':False}
            receipt['gate_rows' if span['synthetic'] else 'source_rows'].append(row)
            write(directory/f'span-{index+1:02d}.json',row)
            print(json.dumps({'span_index':index,'source_span_id':span['source_span_id'],
                'compiler_status':row['compiler_status'],'wall_seconds':row['wall_seconds']},sort_keys=True),flush=True)
        backup,prohibit,minimum=receipt['gate_rows']
        checks=receipt['checks']
        checks['three_gates_compiled']=all(row['compiler_status']==OperationStatus.SUCCESS.value
            and len(row['rules'])==1 and row['parser_vocabulary'] and row['parser_vocabulary']['actors'] and row['parser_vocabulary']['actions'] for row in receipt['gate_rows'])
        if checks['three_gates_compiled']:
            b,p,m=[{**row['rules'][0],'temporal_records':row['parser_temporal_records']} for row in receipt['gate_rows']]
            checks['deadline_exception_and_nonrenderability']=(b['modality']=='O'
                and b['temporal_records']==[{'temporal_kind':'within_duration','value':'10 days','quantity':10}]
                and '10 days' in backup['decompiled'][0] and 'emergency' in backup['decompiled'][0]
                and lock.pattern_from_rule(b) is None)
            checks['prohibition']=p['modality']=='F'
            checks['minimum_duration']=(m['temporal_records']==[{'temporal_kind':'minimum_duration','value':'20 days','quantity':20}]
                and 'at least 20 days' in minimum['decompiled'][0] and 'at least days' not in minimum['decompiled'][0]
                and minimum['decompiled'][0].count('20 days')==1
                and lock.pattern_from_rule(m)=={'kind':'threshold','fail':19,'meet':20})
        for index,text in enumerate(GATES):
            empty=compiler.compile(CompilerRequest(source_text=text,request_id=f'timing-empty-{index}',atom_vocabulary=CanonicalAtomVocabulary()))
            okay=empty.status is OperationStatus.ABSTAINED and empty.canonical_ir is None and empty.error.code is CanonicalErrorCode.UNSUPPORTED_SEMANTICS
            receipt['empty_vocabulary_checks'].append({'text':text,'abstained_as_required':okay,
                'compiler_status':empty.status.value,'error':None if empty.error is None else empty.error.code.value,'admitted':False})
        checks['empty_vocabulary_abstains']=all(row['abstained_as_required'] for row in receipt['empty_vocabulary_checks'])
        checks['three_original_source_gaps_preserved']=len(receipt['source_rows'])==3 and all(
            row['compiler_status']==OperationStatus.ABSTAINED.value and row['diagnostic_fields'] and not row['rules']
            for row in receipt['source_rows'])
        receipt['timing_summary']={}
        for label,rows in [('synthetic_gates',receipt['gate_rows']),('retained_us_code',receipt['source_rows'])]:
            receipt['timing_summary'][label]={'sample_count':len(rows),**{
                name:sum(row[name] for row in rows)/len(rows)
                for name in ('vocabulary_seconds','compiler_seconds','decompiler_seconds','wall_seconds')}}
        verify(sealed);canonical_loaded();receipt['source_unchanged']=True
        receipt['passed']=all(checks.values()) and receipt['source_unchanged']
    except Exception as exc:
        receipt['error']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        receipt['elapsed_seconds']=time.monotonic()-started
        try:verify(sealed)
        except Exception as exc:
            receipt['source_guard_error']={'type':type(exc).__name__,'message':str(exc)};receipt['passed']=False
        write(directory/'span-timing-receipt.json',receipt)
    print(json.dumps({'passed':receipt['passed'],'receipt':str(directory/'span-timing-receipt.json'),'error':receipt['error']}),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())

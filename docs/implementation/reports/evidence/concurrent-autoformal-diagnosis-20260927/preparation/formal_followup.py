"""Validate retained R4 targets without training or changing the failed R4 receipt.

Run only under run_formal_followup_reserved.py. Actual adapter construction uses
shared immutable graph context. Existing frame-contract checks are factored into
one common-context check plus all actual per-formula fields; serialization of the
entire formalization artifact is deliberately not requested or qualified.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'harness'))
import formal_validation as fv
ROOT = fv.ROOT
R4 = ROOT / 'workspace/test-logs/federal-corpus-audits/concurrent-autoformal-diagnosis-20260927/capture-r4'
DESCRIPTOR = R4 / 'supervisor/lanes/training/prepared-targets.json'
ARTIFACT = R4 / 'supervisor/lanes/training/target-preparation-1/targets.bundle'
ARTIFACT_SHA = '04433524b519b89fffc4ed6a33870ae156c57d362b8691652bb3ee496055766a'
SNAPSHOT_ID = 'sha256:1b6dd04fc9d73d32f96da2259322fb3b138f1880f40367ccbcf0082a40e12ec4'


def compact_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest_value(value):
    return hashlib.sha256(compact_bytes(value)).hexdigest()


def verify_files(records):
    for item in records:
        path = fv.regular(item['path'], max(item['bytes'], 1))
        if path.stat().st_size != item['bytes'] or fv.sha(path) != item['sha256']:
            raise ValueError('sealed follow-up input changed: ' + str(path))


def validate_frames(sample, target, output, progress):
    from ipfs_datasets_py.logic.legal_ir.adapter import LegalIRFormalizationAdapter
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, thaw_json
    from ipfs_datasets_py.logic.integration.reasoning.legal_ir_view_contracts import (
        legal_ir_view_contract, validate_legal_ir_view,
    )
    view_id = 'legal-ir-view/frame-logic/v1'
    contract = legal_ir_view_contract(view_id)
    hooks = [hook.hook_id for hook in contract.validation_hooks]
    if hooks != ['required_fields', 'provenance_identifiers_only', 'frame_relation_typing']:
        raise ValueError('frame hooks changed; factoring must be reviewed again')
    if any(field.path.startswith('legal_frame_logic') for field in contract.required_fields):
        raise ValueError('frame context became a required field; factoring must be reviewed again')
    views = target.document.views
    modal = views['modal_frame_logic.modal_ir'].payload['modal_ir']
    graph = modal['frame_logic']
    triples = views['modal_frame_logic.frame_logic'].payload['triples']
    if not triples or graph['triples'] != triples:
        raise ValueError('retained modal/frame triple projections differ or are empty')
    original_graph_sha = digest_value(graph)
    data = sample.to_dict()
    data.update(modal_ir=modal, normalized_text=modal['normalized_text'])
    progress('before_actual_adapter_construction', sample_id=sample.sample_id, triple_count=len(triples))
    started = time.monotonic()
    adapted = LegalIRFormalizationAdapter().adapt_artifact(data)
    constructed_seconds = time.monotonic() - started
    progress('actual_adapter_constructed', sample_id=sample.sample_id, seconds=constructed_seconds,
             total_formula_count=len(adapted.formulas))
    formulas = [formula for formula in adapted.formulas if formula.view_id == view_id]
    if len(formulas) != len(triples) or not formulas:
        raise ValueError('actual adapter did not retain every frame triple')
    shared_context = formulas[0].expression['legal_frame_logic']
    if not isinstance(shared_context, FrozenMap) or any(
            formula.expression['legal_frame_logic'] is not shared_context for formula in formulas):
        raise ValueError('actual frame formulas do not share one immutable full context')
    if digest_value(thaw_json(shared_context)) != original_graph_sha:
        raise ValueError('shared immutable frame context changed contents')
    # Required fields and provenance IDs vary per formula. The only context
    # traversal is the existing provenance hook's forbidden-source-field walk;
    # it is independent of the required-field checks and identical for every
    # formula sharing this immutable object. The relation hook returns ().
    common = validate_legal_ir_view(view_id, formulas[0].expression).to_dict()
    progress('shared_context_checked', sample_id=sample.sample_id, valid=common['valid'])
    expected = Counter((row['subject'], row['predicate'], row['object']) for row in triples)
    actual = Counter()
    all_valid = common['valid']
    failures, examples = [], []
    stream_path = output / (sample.sample_id + '-frame-schema.jsonl')
    stream_digest = hashlib.sha256()
    with stream_path.open('xb') as stream:
        for index, formula in enumerate(formulas):
            projection = {key: value for key, value in formula.expression.items() if key != 'legal_frame_logic'}
            result = validate_legal_ir_view(view_id, projection).to_dict()
            actual[(projection['subject'], projection['predicate'], projection['object'])] += 1
            passed = common['valid'] and result['valid'] and not formula.opaque
            row = {'index': index, 'formula_id': formula.formula_id, 'opaque': formula.opaque,
                   'shared_context_sha256': original_graph_sha, 'projection': projection,
                   'validation': result, 'passed': passed}
            raw = compact_bytes(row) + b'\n'
            stream.write(raw); stream_digest.update(raw)
            if stream.tell() > 25_000_000:
                raise ValueError('per-sample validation stream exceeds 25 MB')
            all_valid = all_valid and passed
            if not passed and len(failures) < 16:
                failures.append(row)
            if index in (0, len(formulas) - 1):
                examples.append(row)
        stream.flush(); os.fsync(stream.fileno())
    equivalent = actual == expected
    progress('all_frame_formulas_checked', sample_id=sample.sample_id, count=len(formulas),
             valid=all_valid and equivalent)
    return {'passed': all_valid and equivalent, 'contract_id': view_id,
            'actual_adapter_constructed': True, 'adapter_construction_seconds': constructed_seconds,
            'frame_formula_count': len(formulas), 'original_triple_count': len(triples),
            'all_original_triples_preserved': equivalent, 'shared_full_context_identity': True,
            'shared_full_context_sha256': original_graph_sha, 'shared_context_validation': common,
            'all_frame_schema_checks_executed': True, 'failures_first_16': failures, 'examples_first_last': examples,
            'validation_stream': {'path': str(stream_path), 'bytes': stream_path.stat().st_size,
                                  'sha256': stream_digest.hexdigest()},
            'existing_validator_equivalence': 'Same required-field/provenance hooks on every actual field projection; shared immutable optional context forbidden-source check once, combined with every result. Frame-relation hook is empty. All triples checked without truncation.',
            'full_artifact_serialization_qualified': False, 'full_artifact_identity_qualified': False,
            'whole_source_semantic_equivalence_qualified': False, 'admitted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_directory.absolute()
    if output.exists() or output.resolve() != output or not output.parent.is_dir() or not output.is_relative_to(fv.OWNED):
        raise ValueError('output must be a new owned follow-up directory')
    inputs_path = HERE / 'formal-followup-inputs.json'
    inputs = json.loads(inputs_path.read_bytes())
    if inputs.get('launch_ready') is not True:
        raise ValueError('follow-up source manifest is not frozen')
    records = inputs['retained_artifacts'] + inputs['validator_sources']
    verify_files(records)
    if os.environ.get('IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS') != '60':
        raise ValueError('explicit historical target timeout binding must be 60')
    output.mkdir()
    counter = 0
    def progress(stage, **fields):
        nonlocal counter
        counter += 1
        event = {'stage': stage, 'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid(), **fields}
        fv.write(output / f'progress-{counter:02d}.json', event)
        print(json.dumps(event, sort_keys=True), flush=True)
    receipt = {'schema': 'retained-target-formal-followup/v1', 'passed': False, 'error': None,
        'samples': [], 'lake': None, 'gates': [], 'training_executed': False,
        'bridge_generation_executed': False, 'concurrency_claim': False,
        'prior_concurrent_capture': str(R4), 'prior_concurrent_capture_passed': False,
        'prior_failure_preserved': 'owned descendant RSS exceeded 8 GiB; no replacement of R4 audit',
        'shared_targets_historical_producer': True, 'current_training_reuse_qualified': False,
        'full_adapter_construction_qualified': False, 'full_adapter_serialization_qualified': False,
        'full_artifact_identity_qualified': False, 'source_semantic_equivalence_qualified': False,
        'learned_symbolic_program_validated': False, 'heldout_canary_qualified': False,
        'admitted': False, 'formalized': False, 'constitution_formalized': False,
        'bridge_names': list(fv.BRIDGES), 'legal_ir_evaluate_provers': False,
        'legal_ir_parallel_workers': 1, 'metric_disk_cache': 0,
        'target_artifact_sha256': ARTIFACT_SHA, 'target_snapshot_id': SNAPSHOT_ID,
        'input_manifest_sha256': fv.sha(inputs_path), 'source_unchanged': False}
    started = time.monotonic()
    try:
        fv.canonical_modules()
        from ipfs_datasets_py.logic import autoformal
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
        from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest, OperationStatus, CanonicalErrorCode
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_bundle
        from ipfs_datasets_py.logic.CEC.native.dcec_integration import parse_dcec_string, validate_formula
        from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticFormula as DCECDeontic, DeonticOperator as DCECOperator
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula as TDFOLDeontic, DeonticOperator as TDFOLOperator
        receipt['tree_pin'] = require_workspace_logic_tree()
        fv.canonical_modules()
        progress('canonical_imports_checked')
        config = json.loads((HERE / 'harness/frozen-config.json').read_bytes())
        frozen_rows = [SampleRecord.from_dict(row) for row in config['job']['samples']]
        if tuple(row.text for row in frozen_rows) != fv.GATES:
            raise ValueError('only unchanged frozen training gates may be validated')
        session = autoformal.AutoformalSession()
        compiler = TypedDeonticCanonicalCompiler()
        for index, text in enumerate(fv.GATES):
            result = autoformal.compile_span(session, text, f'formal-followup-gate-{index}', allow_partial=False)
            if result.get('compiler_status') != 'compiled':
                raise ValueError('strict canonical synthetic gate no longer compiles')
            empty = compiler.compile(CompilerRequest(source_text=text, request_id=f'followup-empty-{index}', atom_vocabulary=CanonicalAtomVocabulary()))
            if not (empty.status is OperationStatus.ABSTAINED and empty.canonical_ir is None
                    and empty.error.code is CanonicalErrorCode.UNSUPPORTED_SEMANTICS):
                raise ValueError('empty vocabulary no longer abstains')
            receipt['gates'].append({'text': text, 'synthetic': True, 'result': result, 'admitted': False})
        backup, prohibit, minimum = [row['result'] for row in receipt['gates']]
        if not (backup['rule']['modality'] == 'O' and '10 days' in backup['decompiled'] and 'emergency' in backup['decompiled']
            and backup['rule']['temporal_records'] == [{'temporal_kind':'within_duration','value':'10 days','quantity':10}]
            and prohibit['rule']['modality'] == 'F' and 'at least 20 days' in minimum['decompiled']
            and 'at least days' not in minimum['decompiled']):
            raise ValueError('gate modality/temporal/exception preservation failed')
        fv.write(output / 'strict-gates.json', {'passed': True, 'empty_vocabulary_abstains': True, 'gates': receipt['gates'], 'admitted': False})
        progress('strict_gates_checked')
        receipt['lake'] = fv.lake_check(receipt['gates'], output, 30)
        fv.write(output / 'lake-receipt.json', receipt['lake'])
        progress('lake_build_finished', passed=receipt['lake']['passed'])
        prepared = json.loads(DESCRIPTOR.read_bytes())
        if (prepared['target_snapshot_id'] != SNAPSHOT_ID or prepared['artifact']['sha256'] != ARTIFACT_SHA
                or prepared['artifact']['path'] != str(ARTIFACT) or prepared.get('all_requested_bridge_reports_received') is not True):
            raise ValueError('retained complete target descriptor differs')
        samples = [build_us_code_sample(**asdict(row)) for row in frozen_rows]
        with load_target_bundle(ARTIFACT, expected_sha256=ARTIFACT_SHA, max_bytes=30_000_000) as bundle:
            historical = bundle.config
            if (bundle.snapshot_id != SNAPSHOT_ID or bundle.sample_count != 5 or set(bundle.statuses.values()) != {'ready'}
                or tuple(historical.bridge_names) != fv.BRIDGES or historical.evaluate_provers is not False
                or historical.parallel_workers != 1 or historical.target_timeout_seconds != 60):
                raise ValueError('retained bundle identity/coverage/policy changed')
            receipt['historical_producer_config_sha256'] = digest_value(historical.to_dict())
            receipt['producer_vs_validator_source_changes'] = [name for name,value in historical.code_sha256.items()
                if fv.sha(ROOT / 'ipfs_datasets_py' / name) != value]
            if sorted(receipt['producer_vs_validator_source_changes']) != sorted(inputs['allowed_producer_to_validator_source_changes']):
                raise ValueError('producer-to-validator drift exceeds the explicitly reviewed adapter change')
            progress('historical_bundle_verified', sample_count=5)
            iterator = bundle.iter_targets_for(samples, config=historical)
            try:
                for sample_id,target in iterator:
                    sample = next(value for value in samples if value.sample_id == sample_id)
                    row = {'sample_id':sample_id, 'source_text':sample.text, 'synthetic':True,
                        'target_document_sha256':target.document.canonical_hash(), 'passed':False,
                        'producer':'retained deterministic shared bridge target, not learned output','admitted':False}
                    if target.document.source_text != sample.text:
                        raise ValueError('retained target source text differs')
                    views=target.document.views
                    row['dcec']=fv.parser_checks(views['cec_dcec.dcec_formula'],parse_dcec_string,validate_formula,
                        DCECDeontic,{'O':DCECOperator.OBLIGATORY,'P':DCECOperator.PERMISSION,'F':DCECOperator.FORBIDDEN})
                    row['tdfol']=fv.parser_checks(views['fol_tdfol.tdfol_formula'],parse_tdfol,
                        deontic_type=TDFOLDeontic,deontic_operators={'O':TDFOLOperator.OBLIGATION,'P':TDFOLOperator.PERMISSION,'F':TDFOLOperator.PROHIBITION},
                        structural_validator=fv.tdfol_operator_structure)
                    rule=next(value['result']['rule'] for value in receipt['gates'] if value['text']==sample.text)
                    row['representation_limits']=fv.representation_limits(rule,row['tdfol'])
                    fv.write(output/(sample_id+'-native-programs.json'),row)
                    progress('native_programs_checked',sample_id=sample_id,dcec=row['dcec']['passed'],tdfol=row['tdfol']['passed'])
                    row['frame_schema']=validate_frames(sample,target,output,progress)
                    row['passed']=all(row[key]['passed'] for key in ('dcec','tdfol','frame_schema'))
                    fv.write(output/(sample_id+'-result.json'),row)
                    receipt['samples'].append(row)
                    del target,views
                    gc.collect()
            finally:
                iterator.close()
            receipt['bundle_read_statistics']=bundle.statistics
        verify_files(records)
        fv.canonical_modules()
        receipt['source_unchanged']=True
        receipt['full_adapter_construction_qualified']=len(receipt['samples'])==3 and all(
            row['frame_schema']['actual_adapter_constructed'] for row in receipt['samples'])
        receipt['passed']=receipt['lake']['passed'] and len(receipt['samples'])==3 and all(row['passed'] for row in receipt['samples'])
    except Exception as exc:
        receipt['error']=fv.failure(exc)
    finally:
        receipt['elapsed_seconds']=time.monotonic()-started
        try:
            verify_files(records)
        except Exception as exc:
            receipt['source_guard_error']=fv.failure(exc);receipt['passed']=False
        fv.write(output/'followup-receipt.json',receipt)
    print(json.dumps({'passed':receipt['passed'],'receipt':str(output/'followup-receipt.json'),'error':receipt['error']}),flush=True)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

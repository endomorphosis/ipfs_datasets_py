#!/usr/bin/env python3
"""All four authored modalities: live native gates, two training steps, gated inference.

Explicit qualifier policies are fixture declarations, not source-text inference.
This smoke measures structural integration, not corpus or heldout decoder fidelity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))


def _write(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")


def run(output,lake,*,java_executable=None,tla2tools_jar=None):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v3 import build_native_family_lake
    from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v3 as policy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_semantic_projection_panel as panel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v3 import (
        train_validated_family_projection_autoencoder,infer_validated_family_projection_autoencoder)
    require_workspace_logic_tree()
    output=Path(output).absolute()
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();results={}
    for domain in panel.DOMAINS:
        directory=output/domain;directory.mkdir()
        domain_started=time.monotonic()
        try:
            observations=[];handles=[];reports=[];cases=[]
            for index in range(3):
                case_started=time.monotonic()
                case=panel.prepare_case(domain,index);report=case['report']
                if len(report['requested_families'])!=40 or len(report['family_inventory'])!=40:
                    raise ValueError('complete forty-family inventory must remain visible')
                _write(directory/f'source-{index}-prepared-targets.json',report)
                _write(directory/f'source-{index}-fixture.json',case['fixture'])
                handle=build_native_family_lake(report,source_inputs=case['source_inputs'],lake_executable=lake,
                    java_executable=java_executable,tla2tools_jar=tla2tools_jar,output_directory=directory/f'source-{index}')
                handles.append(handle)
                receipt=handle.to_dict()
                if {r['projection_id'] for r in receipt['per_projection']}!={r['projection_id'] for r in report['projections']}:
                    raise ValueError('native receipt omitted an emitted projection')
                present={r['logic_family'] for r in report['projections']}
                reviews=[{'family_id':r['family_id'],'source_digest':report['source_digest'],'disposition':'inapplicable',
                    'reason':'Closed authored integration fixture specifies only its supplied native models, eight formulas and explicit qualifier declarations; additional models are outside this fixture.',
                    'evidence_refs':[f'urn:authored-semantic-projection-smoke:v1:{domain}:{index}']}
                    for r in report['family_inventory'] if r['family_id'] not in present]
                observation=policy.validate_projection_report(report,lake_execution=handle,applicability_review=reviews)
                _write(directory/f'source-{index}'/'validation.json',observation.to_dict())
                observations.append(observation);reports.append(report)
                cases.append({'index':index,'split':'train' if index<2 else 'tuning','report_sha256':report['report_sha256'],
                    'original_v4_report_sha256':case['original_report_sha256'],'source_digest':report['source_digest'],
                    'projection_count':len(report['projections']),'wall_seconds':time.monotonic()-case_started,
                    'lake_command':receipt.get('execution',{}).get('command'),'lake_status':receipt.get('execution',{}).get('status'),
                    'all_projection_checks_passed':all(r['lake_status']=='passed' and r['parser_status']=='passed' for r in receipt['per_projection']),
                    'additional_syntax_checks':[{'projection_id':r['projection_id'],'checks':r['additional_syntax_checks']}
                        for r in receipt['per_projection'] if r.get('additional_syntax_checks')],
                    'receipt_path':str(directory/f'source-{index}'/'receipt.json')})
            native_seconds=time.monotonic()-domain_started
            training_gate=policy.evaluate_projection_training_batch(observations[:2],domain_id=domain,target_reports=reports[:2])
            tuning_gate=policy.evaluate_projection_training_batch(observations[2:],domain_id=domain,target_reports=reports[2:])
            _write(directory/'training-gate.json',training_gate);_write(directory/'tuning-gate.json',tuning_gate)
            trained=train_validated_family_projection_autoencoder(observations[:2],observations[2:],domain_id=domain,
                output_dir=directory/'checkpoint',epochs=2,minibatch_size=2,latent_width=8,max_seconds=60)
            inferred=infer_validated_family_projection_autoencoder(trained['descriptor'],observations[2:])
            expected_training={(index,row['projection_id']) for index,r in enumerate(reports[:2]) for row in r['projections']}
            expected_tuning={row['projection_id'] for row in reports[2]['projections']}
            coverage=trained['report']['training_coverage']
            checks={'all_three_native_builds_passed':all(c['lake_status']=='passed' and c['all_projection_checks_passed'] for c in cases),
                'strict_training_gate_passed':training_gate['strict_training_allowed'],
                'strict_tuning_gate_passed':tuning_gate['strict_training_allowed'],
                'two_optimizer_steps_executed':trained['report']['training_executed'] is True and trained['report']['optimizer_steps']==2,
                'all_training_projection_occurrences_covered':not coverage['untrained_projection_ids'] and
                    {(r['row'],r['projection_id']) for r in coverage['projections'] if r['has_coverage']}==expected_training,
                'all_tuning_projection_loss_terms_present':set(trained['report']['after']['projections'])==expected_tuning,
                'all_inference_projection_loss_terms_present':set(inferred['projections'])==expected_tuning,
                'all_inference_projection_occurrences_have_loss':inferred['loss_coverage']['all_emitted_projections_have_loss'] is True
                    and inferred['loss_coverage']['rows_per_projection']=={name:1 for name in expected_tuning},
                'all_eight_explicit_formulas_retained':all({domain+'/native_formula/'+name+'/v3' for name in panel.FORMULAS}
                    <= {p['projection_id'] for p in report['projections']} for report in reports)}
            result={'domain_id':domain,'integration_passed':all(checks.values()),'integration_checks':checks,'sources':cases,
                'native_preparation_and_Lake_seconds':native_seconds,'total_wall_seconds':time.monotonic()-domain_started,
                'trained':trained,'inference':inferred,'source_count':3,'training_source_count':2,'tuning_source_count':1,
                'scope':'authored native declarations; tuning selection and inference; no heldout/source-decoder/corpus-quality measurement',
                'fixture_limitations':['Intent positive fixture uses an effect-only contract and separate assumption; precondition-to-control-state binding remains unsupported.'] if domain=='intent_ir' else [],
                'admitted':False,'qualified':False,'formalized':False,'source_semantics_verified':False,'source_decoder_trained':False,
                'constitution_formalized':False,'download_calls':0}
            _write(directory/'summary.json',result)
            results[domain]=result
            print(json.dumps({'domain':domain,'integration_passed':result['integration_passed'],
                'projection_counts':[c['projection_count'] for c in cases],'optimizer_steps':trained['report']['optimizer_steps'],
                'before_objective':trained['report']['before']['objective'],'after_objective':trained['report']['after']['objective'],
                'selected_epoch':trained['report']['selected_epoch'],'wall_seconds':result['total_wall_seconds']}),flush=True)
        except Exception as error:
            # Preserve this failure and still exercise the remaining domains.
            (directory/'failure.txt').write_text(traceback.format_exc())
            result={'domain_id':domain,'integration_passed':False,'error_type':type(error).__name__,'error':str(error),
                'total_wall_seconds':time.monotonic()-domain_started,'admitted':False,'qualified':False,'formalized':False}
            _write(directory/'failure.json',result);results[domain]=result
            print(json.dumps({'domain':domain,'integration_passed':False,'error':str(error)}),flush=True)
    summary={'schema':'four-modality-semantic-projection-training-smoke/v1','results':results,
        'integration_passed':set(results)==set(panel.DOMAINS) and len(results)==4 and all(r['integration_passed'] for r in results.values()),
        'source_tree':str(ROOT),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'fixture_builder_sha256':hashlib.sha256(Path(panel.__file__).read_bytes()).hexdigest(),
        'tools':{'lake':str(lake),'java_executable':java_executable,'tla2tools_jar':tla2tools_jar},
        'total_wall_seconds':time.monotonic()-started,'scope':'all authored native projections; explicit caller-supplied qualifier interpretations; not independent fidelity',
        'admitted':False,'qualified':False,'formalized':False,'source_semantics_verified':False,
        'constitution_formalized':False,'download_calls':0,'cache_scope':'fresh process; fresh Lake workspace for each source; bounded numerical atom caching'}
    _write(output/'summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--lake',required=True)
    parser.add_argument('--java-executable')
    parser.add_argument('--tla2tools-jar')
    args=parser.parse_args()
    result=run(args.output,args.lake,java_executable=args.java_executable,tla2tools_jar=args.tla2tools_jar)
    raise SystemExit(0 if result['integration_passed'] else 1)

"""Verify bounded native qualified runs without granting legal admission."""
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = next(path for path in BASE.parents if (path / "ipfs_datasets_py").is_dir())
NATIVE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "workspace/test-logs/federal-corpus-audits/qualified-incremental-20260928/native-complete"
EXPECTED_BRIDGES = ['modal_frame_logic','deontic_norms','fol_tdfol','cec_dcec','external_prover_router']

def read(path):
    return json.loads(path.read_bytes())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

workers = {p.parent.name: read(p) for p in (NATIVE/'progress/outputs').glob('*/receipt.json')}
qualifications = {p.parent.name: read(p) for p in (NATIVE/'progress/qualifications').glob('*/qualification.json')}
cycles = sorted((read(p) for p in (NATIVE/'cycles').glob('*/cycle.json')),
                key=lambda x: len(x['training']['completed']))
assert workers and workers.keys() == qualifications.keys()
assert len(cycles) == 3
all_dispatched = [run for cycle in cycles for run in cycle['training']['dispatched_run_ids']]
assert len(all_dispatched) == len(set(all_dispatched)) == len(workers)
assert sum(not cycle['training']['dispatched_run_ids'] for cycle in cycles) >= 1
assert not any(cycle['training']['blocked'] for cycle in cycles)
assert all(cycle['admitted'] is False and cycle['formalized'] is False for cycle in cycles)
assert any(cycle['training']['pending_batch_count'] == 0 for cycle in cycles)
sections, improved, lake_successes, summaries = set(), [], [], []
for run, worker in workers.items():
    q = qualifications[run]
    assert worker['execution_mode'] == 'native_training'
    assert worker['bridge_names'] == EXPECTED_BRIDGES
    assert worker['legal_ir_evaluate_provers'] is False and worker['legal_ir_parallel_workers'] == 1
    assert worker['metric_disk_cache'] == 0 and worker['use_sample_memory'] is False
    assert worker['process_cache_initially_empty'] is True
    assert worker['validation_sample_count'] == 0
    t = worker['training_report']
    assert t['before']['legal_ir_target_count'] == t['after']['legal_ir_target_count'] == 1
    assert len(t['candidate_update_order']) == 5
    assert worker['admitted'] is False and not worker['promotion_performed']
    gates = q['gate_results']
    assert q['qualified'] == all(gate['passed'] for gate in gates.values())
    assert not q['admitted'] and not q['formalized'] and not q['model_emits_text_or_formulas']
    assert q['heldout_sample_count'] == 1 and not q['heldout_canary']
    assert q['metric_evaluation']['bridge_names'] == []
    assert q['metric_evaluation']['legal_ir_target_count'] == 0
    source = worker['job_spec']['samples'][0]
    section = source['section']; sections.add(section)
    row = next(row for row in q['rows'] if row['split'] == 'training')
    assert row['source']['text'] == source['text']
    assert row['model_generated_text'] is None
    if section in {'minimum','deadline','prohibit'}:
        assert row['semantic_gate']['passed']
        assert row['family_syntax_gate']['passed']
        for family_row in row['family_syntax_gate']['rows']:
            assert len(family_row['families']) == 6
            assert all(value['passed'] for value in family_row['families'].values())
    if section in {'deadline','prohibit'}:
        assert not row['lake_gate']['passed'] and not q['qualified']
    if section == 'minimum':
        assert row['lake_gate']['passed']
        assert q['qualified']
    for candidate_row in q['rows']:
        for lake in candidate_row['lake_gate'].get('rows', []):
            if lake.get('passed'):
                assert lake['command'] == ['lake','build','Legal'] and lake['returncode'] == 0
                assert digest(Path(lake['source_file'])) == lake['lean_source_sha256']
                assert digest(Path(lake['log']['path'])) == lake['log']['sha256']
                assert 'Built Legal' in Path(lake['log']['path']).read_text()
                lake_successes.append({'run_id':run,'section':candidate_row['source']['section'],
                                       'source_sha256':lake['lean_source_sha256'],'log_sha256':lake['log']['sha256']})
    before,after = t['before'],t['after']
    delta = after['embedding_cosine_similarity']-before['embedding_cosine_similarity']
    loss_delta = before['reconstruction_loss']-after['reconstruction_loss']
    if delta > 1e-9 and loss_delta > 1e-9:
        improved.append({'run_id':run,'section':section,'cosine_before':before['embedding_cosine_similarity'],
                         'cosine_after':after['embedding_cosine_similarity'],'loss_before':before['reconstruction_loss'],
                         'loss_after':after['reconstruction_loss']})
    events=t['projection_profile']['events']
    summaries.append({'run_id':run,'source':source,'optimizer_accepted_epochs':worker['optimizer_accepted_epochs'],
        'worker_pid':worker['runtime']['pid'],'worker_wall_seconds_per_span':worker['elapsed_seconds'],
        'optimizer_seconds_per_span':worker['training_seconds'],
        'initial_cold_bridge_on_evaluate_seconds':[e['seconds'] for e in events if e['stage']=='before_holdout_evaluation'],
        'warm_bridge_on_evaluate_seconds':[e['seconds'] for e in events if e['stage']=='line_search_evaluation'],
        'legal_ir_target_count':t['after']['legal_ir_target_count'],'qualified':q['qualified'],
        'gate_results':q['gate_results'],'metrics':row['metric_gate'],
        'source_pipeline_seconds_per_span':row['structural_elapsed_seconds'],
        'qualification_wall_seconds_train_and_validation':q['elapsed_seconds'],
        'selected_updates':[e['update'] for e in t['epoch_reports']],
        'candidate_version_id':q['candidate_version_id'],'candidate_artifact':q['candidate_artifact']})
assert sections == {'minimum','deadline','prohibit','8410'}
assert improved and lake_successes
worker_pids={w['runtime']['pid'] for w in workers.values()}
overlap=[]
for path in (NATIVE/'cycles').glob('*/process-observations.json'):
    prior={}
    for observation in read(path):
        advancing=[]
        for process in observation['processes']:
            pid=process['pid']
            if pid in worker_pids and pid in prior and process['cpu_ticks']>prior[pid]:
                advancing.append(pid)
            prior[pid]=process['cpu_ticks']
        if len(advancing)>1:
            overlap.append({'wall_time':observation['wall_time'],'worker_pids':advancing})
assert overlap, 'native worker CPU overlap was not observed'
checkpoint=ROOT/'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
assert digest(checkpoint)=='1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
assert checkpoint.stat().st_size==25895338
result={'schema':'qualified-incremental-native-verification/v1','state_directory':str(NATIVE),
        'worker_count':2,'unique_training_span_count':4,'qualification_validation_count':1,
        'native_attempt_count':len(workers),'cycle_dispatch_counts':sorted(len(c['training']['dispatched_run_ids']) for c in cycles),
        'final_batch_status_counts':next(c['training']['batch_status_counts'] for c in cycles if c['training']['pending_batch_count']==0),
        'model_embedding_kind':'mock:stable-sha256','heldout_canary':False,
        'bridge_names':EXPECTED_BRIDGES,'legal_ir_evaluate_provers':False,'metric_disk_cache':0,
        'legal_ir_parallel_workers':1,'use_sample_memory':False,'temperature':0,
        'cold_scope':'initial process target cache empty; later line search uses warm in-process targets',
        'sample_count_per_bridge_on_evaluate':1,'reconstruction_improvements':improved,'attempts':summaries,
        'lake_build_successes':lake_successes,'parallel_cpu_overlap_observations':overlap,
        'protected_checkpoint_unchanged':True,'admitted':False,'formalized':False,'promotion_performed':False,
        'scope':'exact candidate per-span gates; no whole-corpus or independent-heldout qualification'}
(BASE/'verification.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({key:result[key] for key in ['native_attempt_count','final_batch_status_counts','protected_checkpoint_unchanged','admitted']}))

"""Check this four-span native smoke; never treat transport as legal admission."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--state', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
root = next(path for path in Path(__file__).resolve().parents if (path/'ipfs_datasets_py').is_dir())
read = lambda path: json.loads(path.read_bytes())
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
state = a.state.resolve()
cycles = [read(path) for path in (state/'cycles').glob('*/cycle.json')]
assert len(cycles) == 2
cycles.sort(key=lambda cycle: len(cycle['training']['dispatched_run_ids']), reverse=True)
assert [len(c['training']['dispatched_run_ids']) for c in cycles] == [4, 0]
assert all(not c['admitted'] and not c['formalized'] and not c['model_weights_downloaded'] for c in cycles)
assert all(not c['training']['blocked'] for c in cycles)
assert cycles[-1]['training']['batch_status_counts'] == {'qualified':1, 'needs_repair':2, 'training_exhausted':1}
commands = Counter()
capabilities = []
for cycle in cycles:
    for dispatch in cycle['training']['dispatch_reports']:
        control = dispatch['weight_control']
        assert control['transport'] == 'native_scoped_quack_prototype'
        assert control['database_writer_count'] == 1 and not control['workers_open_database']
        assert not control['cross_host_execution_qualified'] and not control['weights_downloaded']
        assert control['owner_verified_completion_required']
        commands.update(control['command_counts'])
        capabilities.extend(control['capabilities'])
assert commands['ClaimRun'] == commands['CompleteRun'] == 4
assert commands['ReadRun'] >= 4 and commands['ReadVersion'] >= 8
assert all(c['native_quack'] and not c['network_install'] for c in capabilities)
workers = {path.parent.name:read(path) for path in (state/'progress/outputs').glob('*/receipt.json')}
quals = {path.parent.name:read(path) for path in (state/'progress/qualifications').glob('*/qualification.json')}
assert len(workers) == 4 and workers.keys() == quals.keys()
bridges = ['modal_frame_logic','deontic_norms','fol_tdfol','cec_dcec','external_prover_router']
attempts, lean = [], []
for run, worker in workers.items():
    q = quals[run]
    assert worker['execution_mode'] == 'native_training'
    assert worker['bridge_names'] == bridges and worker['sample_count'] == 1
    assert worker['legal_ir_parallel_workers'] == 1 and not worker['legal_ir_evaluate_provers']
    assert worker['metric_disk_cache'] == 0 and not worker['use_sample_memory']
    assert worker['process_cache_initially_empty']
    t = worker['training_report']
    assert t['before']['legal_ir_target_count'] == t['after']['legal_ir_target_count'] == 1
    assert q['qualified'] == all(g['passed'] for g in q['gate_results'].values())
    assert not q['admitted'] and not q['formalized'] and not q['model_emits_text_or_formulas']
    assert not q['heldout_canary'] and q['heldout_sample_count'] == 1
    train = next(row for row in q['rows'] if row['split'] == 'training')
    section = train['source']['section']
    assert q['qualified'] == (section == 'minimum')
    if section in {'minimum', 'deadline', 'prohibit'}:
        assert train['family_syntax_gate']['passed'] and train['semantic_gate']['passed']
        assert all(len(row['families']) == 6 and all(f['passed'] for f in row['families'].values())
                   for row in train['family_syntax_gate']['rows'])
    for row in q['rows']:
        for lake in row['lake_gate'].get('rows', []):
            if lake.get('passed'):
                assert lake['command'] == ['lake','build','Legal'] and lake['returncode'] == 0
                assert sha(Path(lake['source_file'])) == lake['lean_source_sha256']
                assert sha(Path(lake['log']['path'])) == lake['log']['sha256']
                assert 'Built Legal' in Path(lake['log']['path']).read_text()
                lean.append({'run_id':run,'section':row['source']['section'],
                             'source_sha256':lake['lean_source_sha256'],'log_sha256':lake['log']['sha256']})
    attempts.append({'run_id':run,'source':train['source'],'candidate_version_id':q['candidate_version_id'],
        'qualified':q['qualified'],'gate_results':q['gate_results'],'metrics':train['metric_gate'],
        'worker_wall_seconds_per_span':worker['elapsed_seconds'],
        'compiler_pipeline_seconds_per_span':train['structural_elapsed_seconds'],
        'cold_bridge_on_evaluate_seconds':[e['seconds'] for e in t['projection_profile']['events'] if e['stage']=='before_holdout_evaluation'],
        'legal_ir_target_count':1,'qualification_seconds_train_and_validation':q['elapsed_seconds'],
        'selected_updates':[e['update'] for e in t['epoch_reports']],
        'cosine_before':t['before']['embedding_cosine_similarity'],'cosine_after':t['after']['embedding_cosine_similarity'],
        'loss_before':t['before']['reconstruction_loss'],'loss_after':t['after']['reconstruction_loss']})
pids = {w['runtime']['pid'] for w in workers.values()}
overlap = []
for path in (state/'cycles').glob('*/process-observations.json'):
    prior = {}
    for observation in read(path):
        active = [x['pid'] for x in observation['processes'] if x['pid'] in pids and x['pid'] in prior and x['cpu_ticks']>prior[x['pid']]]
        prior.update({x['pid']:x['cpu_ticks'] for x in observation['processes']})
        if len(active)>1:
            overlap.append({'wall_time':observation['wall_time'],'worker_pids':active})
assert overlap
publication = cycles[0]['weight_publications']
assert len(publication)==1 and publication[0]['uploaded'] and publication[0]['acknowledged']
assert not publication[0]['full_checkpoint_uploaded'] and not publication[0]['lane_promoted']
assert not cycles[1]['weight_publications']
qualified = next(row for row in cycles[0]['training']['completed'] if row['qualified'])
assert qualified['optimizer']['candidate_version_id'] == publication[0]['version_id']
assert all(row['publication'] is None for row in cycles[0]['training']['completed'] if not row['qualified'])
import sys
sys.path.insert(0, str(root))
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.huggingface.autoencoder_incremental import load_sparse_update, replay_sparse_update
with AutoencoderRegistry(state/'control.duckdb', state/'artifacts') as registry:
    event = registry.get_outbox_event('huggingface', publication[0]['event_id'])
    assert event['status'] == 'acknowledged' and not registry.pending_outbox('huggingface')
    manifest_path = next((state/'progress/weight-publications'/qualified['run_id']).glob('update-*.json'))
    bundle = load_sparse_update(manifest_path)
    manifest = bundle['manifest']
    replay = replay_sparse_update(manifest_path, local_anchor_resolver=registry.artifact_path)
    assert replay['materialized_checkpoint'] == manifest['materialized_checkpoint']
    assert not manifest['full_corpus_qualified'] and not manifest['statutory_corpus_qualified']
    assert all(item['sha256'] != manifest['anchor_checkpoint']['sha256'] for item in manifest['files'])
checkpoint = root/'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
assert sha(checkpoint)=='1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
assert checkpoint.stat().st_size==25895338
result = {'schema':'qualified-quack-hub-native-verification/v1','state_directory':str(state),
    'cycle_dispatch_counts':[4,0],'final_batch_status_counts':cycles[-1]['training']['batch_status_counts'],
    'worker_count':2,'sample_count':4,'sample_count_per_bridge_on_evaluate':1,'validation_sample_count':1,
    'bridge_names':bridges,'legal_ir_evaluate_provers':False,'metric_disk_cache':0,'legal_ir_parallel_workers':1,
    'use_sample_memory':False,'initial_target_cache_cold':True,'later_line_search_targets_warm':True,
    'model_embedding_kind':'mock:stable-sha256','heldout_canary':False,'temperature':0,
    'quack_command_counts':dict(commands),'quack_capabilities':capabilities[0],
    'database_writer_count':1,'workers_open_database':False,'cross_host_execution_qualified':False,
    'parallel_worker_cpu_overlap':overlap,'attempts':attempts,'lake_builds':lean,
    'publication':publication[0], 'manifest_path':manifest['path_in_repo'],
    'published_file_count':len(manifest['files'])+1,
    'published_payload_bytes':sum(x['bytes'] for x in manifest['files'])+manifest_path.stat().st_size,
    'manifest_artifact':bundle['manifest_artifact'],'materialized_checkpoint':manifest['materialized_checkpoint'],
    'anchor_checkpoint':manifest['anchor_checkpoint'],'second_poll_uploads':0,
    'protected_checkpoint_unchanged':True,'model_weights_downloaded':False,
    'qualification_scope':'synthetic minimum-duration fixture; not an entire statutory rule',
    'admitted':False,'formalized':False,'full_corpus_qualified':False}
a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['cycle_dispatch_counts','final_batch_status_counts','quack_command_counts','published_file_count','published_payload_bytes','publication']}))

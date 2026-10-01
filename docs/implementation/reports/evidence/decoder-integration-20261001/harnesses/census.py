"""Real local learned capture -> compiler -> exports/index -> deferred import plan."""
from pathlib import Path
import collections
import hashlib
import importlib.util
import json
import resource
import subprocess
import time

import pyarrow.parquet as pq
import torch
from huggingface_hub import HfApi

torch.set_num_threads(1)
from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired, span_cache_exchange as exchange
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as interface

ROOT, OUT = Path.cwd(), Path(__file__).resolve().parent
start = time.monotonic()
sha = lambda raw: hashlib.sha256(raw).hexdigest()
def write(name, value):
    (OUT / name).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')
def script(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

pin = require_workspace_logic_tree()
tracked = [*map(Path, pin.values()), *[ROOT / path for path in (
    'ipfs_datasets_py/logic/autoformal/learned_formula_observation.py',
    'ipfs_datasets_py/logic/autoformal/paired_span_census.py',
    'ipfs_datasets_py/logic/autoformal/span_cache_exchange.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_learning.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_runtime_registry.py',
    'scripts/ops/legal_ir/index_span_exchange_outputs.py',
    'scripts/ops/legal_ir/import_span_cache_exchange.py')]]
source_hashes = {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in tracked}
code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
training_path = ROOT / 'workspace/decoder-e2e-20261001/legal-20261001T015700Z/train/report.json'
binding = json.loads(training_path.read_text())['checkpoint']
runtime = interface.open_runtime('legal_ir', interface.LEARNED_FORMULA_VERSION,
    checkpoint=binding['path'], expected_sha256=binding['sha256'])
sources = [
    {'source_span_id': 'known-lost-emergency', 'text': 'The officer shall retain the file for at least 20 days unless emergency.'},
    {'source_span_id': 'known-temporal-metadata', 'text': 'The officer shall submit backup report within 10 days.'},
    {'source_span_id': 'known-exact', 'text': 'The agency shall retain the file.'},
    {'source_span_id': 'unknown-abstention', 'text': 'This provision relates to administrative review.'},
]
infer_start = time.monotonic()
captures = paired.capture_learned_formula_observations(runtime, sources)
infer_seconds = time.monotonic() - infer_start
compiler_start = time.monotonic()
session = AutoformalSession()
compilers = [compile_span(session, source['text'], source['source_span_id']) for source in sources]
compiler_seconds = time.monotonic() - compiler_start
model = captures[0]['model_identity']
observations = [{**source, 'legal_id': 'authored:' + source['source_span_id'],
    'compiler_result': compiler, 'learned_formula_observation': capture,
    'strict_compiler_agreement': compiler.get('roundtrip') is True,
    'model_identity': model, 'metric_scope': 'authored_local_source_only_decoder_not_vector_evaluation'}
    for source, compiler, capture in zip(sources, compilers, captures)]
decoded = [capture['inference']['rows'][0] for capture in captures]
assert compilers[0]['rules'][0]['exceptions'] == ['emergency']
assert decoded[0]['canonical_ir']['rules'][0]['exceptions'] == []
assert decoded[3]['status'] == 'abstained' and compilers[3]['compiler_status'] == 'abstain'
paired_start = time.monotonic()
built = paired.build_paired_census(observations, code_identity=code, model_identity=model,
    agent_id='learned-real-local-e2e', release_id='authored-integration-20261001')
comparisons = [row['comparison'] for row in built['paired_spans']]
assert comparisons[0]['canonical_core_agrees'] is False and comparisons[0]['independent'] is True
assert comparisons[1]['difference_kind'] == 'validated_temporal_metadata_only'
assert comparisons[1]['raw_agrees'] is False and comparisons[1]['canonical_core_agrees'] is True
assert comparisons[2]['raw_agrees'] is True
assert not built['paired_spans'][1]['goal_ids']
paired_files = paired.write_paired_census_bundle(built, OUT / 'paired-v2')
paired_loaded = paired.load_paired_census_bundle(paired_files['manifest']['path'])
assert paired_loaded['paired_spans'] == built['paired_spans']
assert paired_loaded['goals'] == built['goals']
for capture, span in zip(captures, paired_loaded['paired_spans']):
    artifact = next(row for row in paired_loaded['artifacts'] if row['artifact_sha256'] == span['autoencoder']['learned_formula_observation_artifact_sha256'])
    assert json.loads(paired.decode_artifact(artifact)) == capture
paired_seconds = time.monotonic() - paired_start
for item, row in zip(observations, built['paired_spans']):
    item['comparison'] = row['comparison']
    item['comparison_provenance'] = {'kind': 'actual_production_paired_comparison',
        'paired_schema': built['schema_version'], 'observation_id': row['observation_id'],
        'scope': 'representation_equality_not_semantic_equivalence'}
exchange_start = time.monotonic()
export = exchange.publish_compiled_exchange(observations, OUT / 'census-v4', upload=False,
    agent_id='learned-real-local-e2e', code_identity=code, model_identity=model,
    release_id='authored-integration-20261001')
loaded = exchange.load_exchange_bundle(export['manifest']['path'])
assert len(loaded['census_rows']) == len(sources)
assert exchange.load_goal_export(export['goals']['path'])['goal_rows'] == loaded['goal_rows']
by_id = {row['source_span_id']: row for row in loaded['census_rows']}
for source, capture, row in zip(sources, captures, built['paired_spans']):
    saved = by_id[source['source_span_id']]
    assert json.loads(saved['autoencoder_formula_observation_json']) == capture
    assert json.loads(saved['autoencoder_formal_outputs_json']) == capture['inference']['rows'][0]['formal_outputs']
    assert json.loads(saved['autoencoder_canonical_ir_json']) == capture['inference']['rows'][0]['canonical_ir']
    assert json.loads(saved['comparison_json']) == row['comparison']
    assert saved['admitted'] is saved['formalized'] is False
assert not [goal for goal in loaded['goal_rows'] if goal['source_span_id'] == 'known-temporal-metadata']
lost_goals = [goal for goal in loaded['goal_rows'] if goal['source_span_id'] == 'known-lost-emergency']
assert {'repair_packet', 'training_goal'} <= {goal['record_kind'] for goal in lost_goals}
for goal in loaded['goal_rows']:
    packet = json.loads(goal['packet_json'])
    evidence = (packet.get('capture') or packet['row']['capture'])['observation_evidence']
    saved = by_id[goal['source_span_id']]
    assert evidence == exchange._observation_evidence(saved)
    assert evidence['counts_as_validation'] is False
retry = exchange.publish_compiled_exchange(observations, OUT / 'census-v4', upload=False,
    agent_id='learned-real-local-e2e', code_identity=code, model_identity=model,
    release_id='authored-integration-20261001')
assert retry['fingerprint'] == export['fingerprint']
exchange_seconds = time.monotonic() - exchange_start
indexer = script('scripts/ops/legal_ir/index_span_exchange_outputs.py', 'learned_census_output_index_e2e')
index_start = time.monotonic()
# Read metadata only. These authored source bundles are unpublished and are
# absent at this real Hub head, so no remote source-closure claim is made.
dataset_revision = HfApi().dataset_info('justicedao/uscode-autoformal-span-cache').sha
index = indexer.build_index(export['manifest']['path'], OUT / 'output-index-v2',
    revision=dataset_revision, agent_id='learned-real-local-e2e')
index_rows = pq.read_table(index['output_path']).to_pylist()
assert len(index_rows) == len(sources)
for row in index_rows:
    original = by_id[row['source_span_id']]
    assert row['autoencoder_formula_observation_json'] == original['autoencoder_formula_observation_json']
    assert row['autoencoder_formal_outputs_json'] == original['autoencoder_formal_outputs_json']
    assert row['autoencoder_canonical_ir_json'] == original['autoencoder_canonical_ir_json']
index_seconds = time.monotonic() - index_start
import_start = time.monotonic()
imports = {}
for name, path in [('paired-v2', paired_files['manifest']['path']), ('census-v4', export['manifest']['path'])]:
    output = OUT / ('import-' + name)
    process = subprocess.run(['python3', 'scripts/ops/legal_ir/import_span_cache_exchange.py',
        '--manifest', path, '--output', str(output)], capture_output=True, text=True)
    (OUT / ('import-' + name + '.stdout')).write_text(process.stdout)
    (OUT / ('import-' + name + '.stderr')).write_text(process.stderr)
    assert process.returncode == 0, process.stderr
    receipt = json.loads((output / 'import-receipt.json').read_text())
    assert receipt['dry_run'] is True and receipt['materialized'] is False and receipt['executed'] is False
    imports[name] = receipt
import_seconds = time.monotonic() - import_start
assert source_hashes == {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in tracked}
assert sha(Path(binding['path']).read_bytes()) == binding['sha256']
write('observations.json', observations)
write('captures.json', captures)
write('paired-files.json', paired_files)
write('exchange-files.json', export)
write('index-files.json', index)
write('goals.json', loaded['goal_rows'])
write('index-rows.json', index_rows)
report = {'schema': 'learned-census-production-integration-e2e/v1', 'git_head': code,
    'tree_pin': pin, 'source_sha256': source_hashes, 'source_unchanged': True,
    'checkpoint': binding, 'checkpoint_unchanged': True, 'training_performed': False,
    'source_kind': 'authored_integration_clauses_three_prior_heldout_plus_one_OOV',
    'sample_count': len(sources), 'decoded_count': sum(row['status'] == 'decoded' for row in decoded),
    'compiler_compiled_count': sum(row['compiler_status'] == 'compiled' for row in compilers),
    'actual_native_formulas': [row['formula_text'] for row in decoded], 'comparisons': comparisons,
    'known_lost_emergency_preserved': True, 'metadata_only_no_false_semantic_goals': True,
    'paired_goal_count': len(built['goals']), 'exchange_goals_by_kind': dict(collections.Counter(row['record_kind'] for row in loaded['goal_rows'])),
    'exact_capture_and_ast_readback': True, 'exact_goal_observation_evidence': True,
    'immutable_exchange_retry': True, 'output_index_rows': len(index_rows),
    'index_revision_scope': 'observed_real_Hub_head_local_synthetic_source_files_not_present_at_that_revision',
    'observed_Hub_revision': dataset_revision,
    'index_remote_source_closure_verified': False,
    'import_plans': {key: {field: value.get(field) for field in ('dry_run', 'materialized', 'executed', 'task_cids', 'deferred_descriptive_goal_count')}
                     for key, value in imports.items()},
    'timings': {'inference_seconds': infer_seconds, 'inference_seconds_per_span': infer_seconds / len(sources),
        'compiler_seconds': compiler_seconds, 'compiler_seconds_per_span': compiler_seconds / len(sources),
        'paired_export_readback_seconds': paired_seconds, 'exchange_export_readback_retry_seconds': exchange_seconds,
        'output_index_seconds': index_seconds, 'import_dry_plan_seconds': import_seconds,
        'total_seconds': time.monotonic() - start},
    'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'bridge_names': [], 'legal_ir_target_count': 0, 'legal_ir_evaluate_provers': False,
    'metric_disk_cache': False, 'metric_cache_used': False, 'bridge_workers': 1,
    'bridge_evaluate_invoked': False, 'not_a_bridge_on_speed_measurement': True,
    'training_or_heldout_fitting': False, 'uploaded': False, 'downloaded_weights': False,
    'admitted': False, 'qualified': False, 'formalized': False, 'lake_build_invoked': False,
    'note': 'Full families and Lake gates are separate; this checks local evidence integration only.'}
report['artifacts'] = [{'path': str(path.relative_to(ROOT)), 'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}
    for path in sorted(OUT.rglob('*')) if path.is_file() and path.name != 'run.log']
write('report.json', report)
print(json.dumps({key: report[key] for key in ('sample_count', 'decoded_count', 'compiler_compiled_count',
    'paired_goal_count', 'exchange_goals_by_kind', 'timings', 'max_rss_kib')}, sort_keys=True))

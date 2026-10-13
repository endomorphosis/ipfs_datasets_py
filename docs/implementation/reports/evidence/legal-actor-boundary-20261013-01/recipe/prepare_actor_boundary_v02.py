"""Freeze a source-only N8 actor plan without numerical imports or checkpoint parsing."""
import argparse
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
N6 = F.parent / 'legal-temporal-adapter-20261013-01'
N7 = F.parent / 'legal-temporal-attention-20261013-01'
sys.dont_write_bytecode = True


class NoNumerical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'huggingface_hub'}:
            raise AssertionError('Numerical/SDK import prohibited in preparation')
        return None


def audit(event, args):
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in ('os.system', 'os.fork', 'fcntl.flock'):
        raise AssertionError('Process/network/resource operations prohibited in preparation')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path, mode, flags = Path(os.fsdecode(args[0])).absolute(), args[1], args[2]
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and path.parent != F:
            raise AssertionError('Only exclusive new owned preparation output writes allowed')


sys.meta_path.insert(0, NoNumerical())
sys.addaudithook(audit)
spec = importlib.util.spec_from_file_location('actor_boundary_plan_runner', F / 'run_actor_boundary_v02.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
_read = runner.read


def metadata(path, expected=None):
    runner.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name,
                   'Checkpoint/reference JSON parsing prohibited in preparation')
    return _read(path, expected)


runner.read = metadata


def validate_recovery(recovery, baseline_pin):
    runner.require(recovery['schema'] == 'actor-boundary-zero-update-recovery/v1'
                   and recovery['passed'] is True and recovery['findings'] == []
                   and all(type(recovery[key]) is int and recovery[key] == 0
                           for key in ('optimizer_updates', 'inference_source_forwards', 'model_forwards', 'encoder_forwards'))
                   and recovery['baseline'] == baseline_pin and recovery['failed_stage'] == 'preflight'
                   and recovery['failed_attempt'] == str(runner.RUN_ROOT / 'actor-boundary-20261013-actor-boundary-ce-01')
                   and recovery['all_previous533_record_bodies_unchanged'] is True
                   and recovery['baseline_record_count'] == 534
                   and recovery['retained_claim']['status'] == 'retained'
                   and type(recovery['retained_claim']['storage_bytes']) is int
                   and recovery['retained_claim']['storage_bytes'] == 200000000,
                   'Clean zero-model/update attempt01 recovery required')


def prepare():
    artifacts = {}
    def bind(path, expected=None):
        value = runner.pin(Path(path))
        runner.require(expected is None or value == expected, 'Expected retained raw descriptor differs')
        runner.require(value['path'] not in runner.READ_PINS or runner.READ_PINS[value['path']] == value, 'Parsed/bound byte custody differs')
        brief = {k: value[k] for k in ('bytes', 'sha256')}
        runner.require(value['path'] not in artifacts or artifacts[value['path']] == brief, 'Raw artifact identity conflict')
        artifacts[value['path']] = brief
        return value
    old_plan_pin = bind(N6 / 'temporal-ce-control-plan-v01.json')
    old_plan = metadata(old_plan_pin['path'], old_plan_pin)
    runner.require(old_plan['schema'] == 'temporal-adapter-cell-plan/v1' and old_plan['cell'] == 'temporal-ce-control', 'Exact N6 CE plan required')
    final_pin = bind(N6 / 'final-integration-independent-review-v01.json')
    runner.require(final_pin['bytes'] == 274169 and final_pin['sha256'] == '5c25eb3eca9a6bf1011e7b8baffa67c0f29c7c453ac0a8bb51259ddefbe1c729', 'Qualified N6 final anchor required')
    final = metadata(final_pin['path'], final_pin)
    runner.require(final['passed'] is True and final['findings'] == [], 'Clean N6 final review required')
    runner.require(final['artifacts'][old_plan_pin['path']] == old_plan_pin,
                   'Historical CE plan must join the immutable N6 final review')
    n7_final_pin = bind(N7 / 'final-integration-independent-review-v01.json')
    runner.require(n7_final_pin['bytes'] == 333649 and n7_final_pin['sha256'] == 'f1815c65cd33484451b4689d7a420056bf1084bcd8f90f9700eb0eb5b918b4aa',
                   'Qualified N7 final anchor required')
    n7_final = metadata(n7_final_pin['path'], n7_final_pin)
    runner.require(n7_final['schema'] == 'temporal-attention-final-integration-independent-review/v1'
                   and n7_final['passed'] is True and n7_final['findings'] == [], 'Clean N7 final review required')
    compatibility_pin = bind(N7 / 'upstream-owner-compatibility-independent-review-v02.json')
    runner.require(n7_final['artifacts'][compatibility_pin['path']] == compatibility_pin,
                   'Retained compatibility must join final N7 review')
    compatibility = metadata(compatibility_pin['path'], compatibility_pin)
    runner.require(compatibility['schema'] == 'temporal-attention-upstream-owner-compatibility/v1'
                   and compatibility['passed'] is True and compatibility['findings'] == []
                   and compatibility['all34_retained_producer_blob_and_raw_bytes_exact'] is True
                   and len(compatibility['rows']) == 34, 'Exact clean34-producer compatibility required')
    n7_qualified = n7_final['retained_owner_compatibility']['compatibility34_retained_producers']
    runner.require(len(n7_qualified) == 34 and len({row['path'] for row in n7_qualified}) == 34,
                   'Unique34 final-qualified producer paths required')
    n7_by_path = {row['path']: row for row in n7_qualified}
    for row in compatibility['rows']:
        prior = n7_by_path[row['path']]
        runner.require(row['unchanged'] is True and row['owned_raw_exact'] is True and row['upstream_blob_exact'] is True
                       and all(row[k] == prior[k] for k in ('bytes', 'sha256'))
                       and prior['actual_first_parent_and_merge_identical'] is True,
                       'Compatibility and final producer inventory differ')
        descriptor = bind(F / 'datasets' / row['path'])
        runner.require(all(descriptor[k] == row[k] for k in ('bytes', 'sha256')),
                       'Retained source-qualified producer differs in N8')
    data_pin = bind(Path(old_plan['data_export']['path']), old_plan['data_export'])
    data = metadata(data_pin['path'], data_pin)
    fresh_pin = bind(N7 / 'fresh-source-export-v01.json')
    runner.require(fresh_pin['bytes'] == 434236 and fresh_pin['sha256'] == '83078f6028dd63b47661c4e3bb5c9cb27546f926c306d074f13d509d2aeec846',
                   'Exact already-exposed N7 source-only export required')
    fresh = metadata(fresh_pin['path'], fresh_pin)
    source_checkpoint = bind(Path(old_plan['source_checkpoint']['path']), old_plan['source_checkpoint'])
    runner.require(source_checkpoint['sha256'] == runner.SOURCE_SHA and source_checkpoint['bytes'] == 3592389, 'Exact N4 source file required')
    references = old_plan['source_reference_panels']
    for pair in references.values():
        for value in pair.values():
            bind(Path(value['path']), value)
    owners = {}
    for name, descriptor in old_plan['source_owner_pins'].items():
        path = F / 'datasets' / Path(descriptor['path']).relative_to(N6 / 'datasets')
        new = runner.pin(path)
        runner.require(all(new[k] == descriptor[k] for k in ('bytes', 'sha256')), 'Retained LegalIR producer changed')
        owners[name] = new
    legacy = runner.legacy_runner()
    retained = legacy.prior_runner()
    helper = retained.helpers()
    helper.bootstrap(F / 'datasets')
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    importlib.import_module(prefix + 'legal_span_actor_boundary')
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    for name, module in list(sys.modules.items()):
        if name.startswith('ipfs_datasets_py.') and getattr(module, '__file__', None):
            descriptor = runner.pin(Path(module.__file__).resolve())
            runner.require(name not in owners or owners[name] == descriptor, 'Loaded producer origin differs')
            owners[name] = descriptor
    for descriptor in owners.values():
        bind(Path(descriptor['path']), descriptor)
    for path in (Path(__file__).resolve(), F / 'run_actor_boundary_v02.py', F / 'run_scope_guardian.py',
                 F / 'bootstrap_inert.py', runner.LEGACY_RUNNER, legacy.PRIOR_RUNNER, retained.HELPER,
                 F / 'evaluation-contract-v02.json', F / 'training-design-v02.json', F / 'resource-baseline-v02.json',
                 F / 'trainer-source-independent-review-v01.json',
                 F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_boundary_contracts.py'):
        bind(path)
    trainer_review_pin = bind(F / 'trainer-source-independent-review-v01.json')
    trainer_review = metadata(trainer_review_pin['path'], trainer_review_pin)
    runner.require(trainer_review['passed'] is True and trainer_review['findings'] == [], 'Clean N8 trainer source review required')
    for path in (F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_boundary.py',
                 F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_boundary_contracts.py'):
        descriptor = bind(path)
        approved = trainer_review['artifacts'][str(path)]
        runner.require(approved in (descriptor, {k: descriptor[k] for k in ('bytes', 'sha256')}),
                       'Exact actor source/test must join trainer qualification')
    baseline_pin = bind(F / 'resource-baseline-v02.json')
    baseline = metadata(baseline_pin['path'], baseline_pin)
    runner.require(baseline['passed'] is True and baseline['findings'] == [], 'Clean current N8 public baseline required')
    for key in ('library_pin', 'ctypes_util_pin', 'cuda_pathfinder_pin'):
        descriptor = old_plan['ctypes_dl_resolution'][key]
        bind(Path(descriptor['path']), descriptor)
    forbidden = list(old_plan['forbidden_reference_paths']) + [
        str(N7 / 'fresh-reference-packet-v01.json'), str(N7 / 'build_fresh_authored_temporal_reference_v02.py'),
        str(N7 / 'build_fresh_authored_temporal_reference_v01.py'), str(N7 / 'fresh-reference-independent-review-v01.json'),
        str(N7 / 'fresh-reference-construction-audit-v01.json'), str(N7 / 'fresh-authored-reference-packet-v01.json'),
        str(N7 / 'fresh-authored-construction-audit-v01.json'), str(N6 / 'temporal-feature-next-experiment-proposal-v01.json'),
        str(N7 / 'temporal-attention-result-analysis-v01.json'), str(N7 / 'authored-training-error-review-v01.json'),
        str(N7 / 'authored-training-error-review-v02.json'), str(F / 'n7-training168-full-ir-modality-audit-v01.json')]
    smoke_pin = bind(F / 'actor-bootstrap-smoke-controls-v01.json')
    smoke = metadata(smoke_pin['path'], smoke_pin)
    runner.require(smoke['passed'] is True and smoke['findings'] == []
                   and smoke['runner'] == bind(F / 'run_actor_boundary_v02.py')
                   and smoke['loaded_owner_count'] == 13 and smoke['mandatory_loaded_owner_count'] == 5
                   and smoke['all35_raw_source_owner_pins_closed'] is True
                   and smoke['exact_production_bootstrap_used'] is True,
                   'Actual inert production-bootstrap import smoke required')
    bind(Path(smoke['controls_source']['path']), smoke['controls_source'])
    bind(F / 'runner-preparer-source-correction-v01.json')
    recovery_pin = bind(F / 'actor-zero-update-recovery-v01.json')
    recovery = metadata(recovery_pin['path'], recovery_pin)
    validate_recovery(recovery, baseline_pin)
    plan = dict(schema='actor-boundary-cell-plan/v1', package_root=str(F / 'datasets'),
        runner_path=str(F / 'run_actor_boundary_v02.py'), guardian_path=str(F / 'run_scope_guardian.py'),
        attempt_name=runner.ATTEMPT, cell=runner.CELL, source_owner_pins=owners, artifacts=artifacts,
        data_export=data_pin, fresh_source_export=fresh_pin, source_checkpoint=source_checkpoint,
        source_model_state_sha256=runner.SOURCE_STATE_SHA, context_contract=old_plan['context_contract'],
        training_manifest_sha256=runner.digest(data['training_rows']), legacy_prefix_sha256=runner.digest(data['training_rows'][:96]),
        source_reference_panels=references,
        ctypes_dl_resolution=old_plan['ctypes_dl_resolution'], forbidden_reference_paths=forbidden,
        resource_contract=dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300),
        training_seconds=32, diagnostic_panels=[dict(name=n, count=runner.COUNTS[n]) for n in runner.PANELS],
        evaluation_contract=runner.pin(F / 'evaluation-contract-v02.json'), proposal=runner.pin(F / 'training-design-v02.json'),
        configured_dimension=384, latent_enabled=False, default_promotion=False, Lake_executed=False,
        prior_failed_attempt=dict(recovery_receipt=recovery_pin, optimizer_updates=0, inference_source_forwards=0))
    runner.validate_plan(plan)
    runner.validate_sources(plan, data, fresh, helper, legacy)
    runner.require(not (runner.RUN_ROOT / runner.ATTEMPT).exists(), 'Immutable attempt already exists')
    schedule = retained.schedule(data['training_rows'])
    runner.require(len(schedule['batch_indices']) == 32 and sum(map(len, schedule['batch_indices'])) == 384,
                   'Exact inherited deterministic32/384 schedule required')
    for path, expected in artifacts.items():
        runner.require({k: runner.pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Closing admitted source drift')
    for mapping in (runner.READ_PINS, legacy.READ_PINS):
        for path, expected in mapping.items():
            runner.require(runner.pin(Path(path)) == expected, 'Closing consumed metadata drift')
    runner.require(not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'huggingface_hub'} for name in sys.modules), 'Unexpected numerical/SDK import')
    print(runner.write(F / (runner.CELL + '-plan-v02.json'), plan))


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()

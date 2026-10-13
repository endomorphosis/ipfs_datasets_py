"""Freeze a source-only N7 plan without numerical imports or checkpoint parsing."""
import argparse
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
N6 = F.parent / 'legal-temporal-adapter-20261013-01'
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
spec = importlib.util.spec_from_file_location('temporal_attention_plan_runner', F / 'run_temporal_attention_v02.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
_read = runner.read


def metadata(path, expected=None):
    runner.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name,
                   'Checkpoint/reference JSON parsing prohibited in preparation')
    return _read(path, expected)


runner.read = metadata


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
    result_pin = bind(Path(final['qualified_science']['result_review']['path']), final['qualified_science']['result_review'])
    runner.require(final['artifacts'][result_pin['path']] == result_pin, 'Historical result qualification must join final review')
    result_review = metadata(result_pin['path'], result_pin)
    runner.require(result_review['schema'] == 'temporal-adapter-result-independent-review/v1'
                   and result_review['passed'] is True and result_review['findings'] == [], 'Clean authenticated N6 result review required')
    def qualified_control(descriptor):
        runner.require(result_review['artifacts'][descriptor['path']] == {k: descriptor[k] for k in ('bytes', 'sha256')},
                       'Historical control must join the qualified N6 result inventory')
    freeze_pin = bind(N6 / 'two-cell-output-freeze-v01.json')
    qualified_control(freeze_pin)
    freeze = metadata(freeze_pin['path'], freeze_pin)
    runner.require(freeze['schema'] == 'temporal-adapter-two-cell-freeze/v1' and freeze['all_outputs_frozen'] is True
                   and freeze['actual_returned_optimizer_updates'] == 64, 'Both original N6 cells must be frozen')
    control_cell = next(row for row in freeze['cells'] if row['cell'] == 'temporal-ce-control')
    control_summary_pin = bind(Path(control_cell['summary']['path']), control_cell['summary'])
    qualified_control(control_summary_pin)
    control_summary = metadata(control_summary_pin['path'], control_summary_pin)
    control_checkpoint = bind(Path(control_summary['checkpoint']['path']), control_summary['checkpoint'])
    control_training = bind(Path(control_summary['training']['path']), control_summary['training'])
    qualified_control(control_checkpoint)
    qualified_control(control_training)
    runner.require(control_cell['results'][control_checkpoint['path']] == {k: control_checkpoint[k] for k in ('bytes', 'sha256')}
                   and control_cell['results'][control_training['path']] == {k: control_training[k] for k in ('bytes', 'sha256')}, 'Control bytes differ from frozen inventory')
    control_report = metadata(control_training['path'], control_training)
    runner.require(control_summary['status'] == 'completed' and control_summary['actual_new_updates'] == 32
                   and control_summary['source_checkpoint']['sha256'] == runner.SOURCE_SHA
                   and control_report['optimizer_steps'] == 32 and control_report['training_policy']['objective'] == 'temporal-ce-control', 'Completed fixed historical control required')
    data_pin = bind(Path(old_plan['data_export']['path']), old_plan['data_export'])
    data = metadata(data_pin['path'], data_pin)
    fresh_pin = bind(F / 'fresh-source-export-v01.json')
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
    importlib.import_module(prefix + 'legal_span_temporal_attention')
    importlib.import_module(prefix + 'legal_span_temporal_adapter')
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    for name, module in list(sys.modules.items()):
        if name.startswith('ipfs_datasets_py.') and getattr(module, '__file__', None):
            descriptor = runner.pin(Path(module.__file__).resolve())
            runner.require(name not in owners or owners[name] == descriptor, 'Loaded producer origin differs')
            owners[name] = descriptor
    for descriptor in owners.values():
        bind(Path(descriptor['path']), descriptor)
    for path in (Path(__file__).resolve(), F / 'run_temporal_attention_v02.py', F / 'run_scope_guardian.py',
                 F / 'bootstrap_inert.py', F / 'run_inert_tests.py', runner.LEGACY_RUNNER, legacy.PRIOR_RUNNER, retained.HELPER,
                 F / 'evaluation-contract-v01.json', F / 'training-design-v01.json', F / 'resource-baseline-v02.json',
                 F / 'trainer-source-independent-review-v02.json',
                 F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_temporal_attention_contracts.py'):
        bind(path)
    for key in ('library_pin', 'ctypes_util_pin', 'cuda_pathfinder_pin'):
        descriptor = old_plan['ctypes_dl_resolution'][key]
        bind(Path(descriptor['path']), descriptor)
    forbidden = list(old_plan['forbidden_reference_paths']) + [
        str(F / 'fresh-reference-packet-v01.json'), str(F / 'build_fresh_authored_temporal_reference_v02.py'),
        str(F / 'build_fresh_authored_temporal_reference_v01.py'), str(F / 'fresh-reference-independent-review-v01.json'),
        str(F / 'fresh-reference-construction-audit-v01.json'), str(F / 'fresh-authored-reference-packet-v01.json'),
        str(F / 'fresh-authored-construction-audit-v01.json'), str(N6 / 'temporal-feature-next-experiment-proposal-v01.json')]
    plan = dict(schema='temporal-attention-cell-plan/v1', package_root=str(F / 'datasets'),
        runner_path=str(F / 'run_temporal_attention_v02.py'), guardian_path=str(F / 'run_scope_guardian.py'),
        attempt_name=runner.ATTEMPT, cell=runner.CELL, source_owner_pins=owners, artifacts=artifacts,
        data_export=data_pin, fresh_source_export=fresh_pin, source_checkpoint=source_checkpoint,
        source_model_state_sha256=runner.SOURCE_STATE_SHA, context_contract=old_plan['context_contract'],
        training_manifest_sha256=runner.digest(data['training_rows']), legacy_prefix_sha256=runner.digest(data['training_rows'][:96]),
        source_reference_panels=references, historical_control=dict(checkpoint=control_checkpoint, training=control_training,
            summary=control_summary_pin, freeze=freeze_pin, new_optimizer_updates=0, completed_optimizer_updates=32, cell='temporal-ce-control'),
        ctypes_dl_resolution=old_plan['ctypes_dl_resolution'], forbidden_reference_paths=forbidden,
        resource_contract=dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300),
        training_seconds=32, diagnostic_panels=[dict(name=n, count=runner.COUNTS[n]) for n in runner.PANELS],
        evaluation_contract=runner.pin(F / 'evaluation-contract-v01.json'), proposal=runner.pin(F / 'training-design-v01.json'),
        configured_dimension=384, latent_enabled=False, default_promotion=False, Lake_executed=False)
    runner.validate_plan(plan)
    runner.validate_sources(plan, data, fresh, helper, legacy)
    runner.require(not (runner.RUN_ROOT / runner.ATTEMPT).exists(), 'Immutable attempt already exists')
    schedule = retained.schedule(data['training_rows'])
    runner.require([b['indices'] for b in control_report['batch_trace']['batches']] == schedule['batch_indices']
                   and [b['ids'] for b in control_report['batch_trace']['batches']] == schedule['batch_ids'], 'Historical source visits differ')
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

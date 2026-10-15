"""Prepare exact N11 continuation inputs; no numerical or private-state access."""
import argparse
import ast
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
N11 = F.parent / 'legal-head-repair-20261014-01'
N14 = F.parent / 'legal-balanced-execution-20261014-01'
OUTPUT = F / 'actor-refinement-ce-plan-v01.json'
sys.dont_write_bytecode = True


class NoNumerical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'huggingface_hub'}:
            raise ValueError('Numerical/SDK import prohibited during preparation')
        return None


def audit(event, args):
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {'os.system', 'os.fork', 'fcntl.flock'}:
        raise ValueError('Process/network/resource operations prohibited during preparation')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).absolute()
        if 'private-runtime-snapshots' in path.parts or 'private-root-identity-rebind-v01' in path.parts or path.name in {
            'disk-reservations.json', 'resources-start.json', 'resources-final.json', 'ipfs-datasets-resource-scheduler-1000.json'}:
            raise ValueError('Private/global resource bodies prohibited')
        mode, flags = args[1:3]
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and (path != OUTPUT or not flags & os.O_EXCL):
            raise ValueError('Only exclusive new owned plan write allowed')


sys.meta_path.insert(0, NoNumerical())
sys.addaudithook(audit)
spec = importlib.util.spec_from_file_location('actor_refinement_metadata_runner', F / 'run_actor_refinement_v02.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def metadata(path, expected=None):
    r.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name,
              'Checkpoint/reference JSON parsing prohibited')
    return r.read(path, expected)


def prepare():
    artifacts = {}

    def bind(path, expected=None):
        item = r.pin(Path(path))
        r.require(expected is None or item == dict(path=str(path), **{k: expected[k] for k in ('bytes', 'sha256')}),
                  'Expected source identity differs')
        brief = {k: item[k] for k in ('bytes', 'sha256')}
        r.require(str(path) not in artifacts or artifacts[str(path)] == brief, 'Conflicting admitted source identity')
        artifacts[str(path)] = brief
        return item

    previous = metadata(N14 / 'completion-review-v01.json', bind(N14 / 'completion-review-v01.json'))
    r.require(previous['schema'] == 'conditions-balanced-completion-review/v1' and previous['passed'] is True
              and previous['findings'] == [] and previous['scientific_success'] is False and previous['default_promotion'] is False,
              'Completed negative balanced comparison required; no promotion')
    parent_plan_pin = bind(N11 / 'conditions-presence-ce-plan-v01.json', dict(bytes=52960,
        sha256='83768d40f403a2e67a4fbfc61cf83f5c52cabd9b1a27a5ee3d51d891c6c6c25c'))
    old = metadata(parent_plan_pin['path'], parent_plan_pin)
    contract_pin = bind(F / 'evaluation-contract-v01.json')
    contract = metadata(contract_pin['path'], contract_pin)
    parent = contract['completed_frozen_parent']
    freeze = metadata(parent['freeze']['path'], bind(parent['freeze']['path'], parent['freeze']))
    review = metadata(parent['independent_review']['path'], bind(parent['independent_review']['path'], parent['independent_review']))
    r.require(review['passed'] is True and review['findings'] == [] and review['freeze'] == parent['freeze']
              and review['plan'] == parent_plan_pin and freeze['all_outputs_frozen'] is True
              and freeze['plan'] == parent_plan_pin and len(freeze['results']) == 62,
              'Exact independently qualified N11 frozen donor required')
    summary = metadata(freeze['summary']['path'], bind(freeze['summary']['path'], freeze['summary']))
    donor = bind(summary['checkpoint']['path'], summary['checkpoint'])
    r.require(donor == contract['source_parent'] and donor['sha256'] == r.SOURCE_SHA
              and summary['final_model_state_sha256'] == contract['source_model_state_sha256'] == r.SOURCE_STATE_SHA
              and freeze['results'][donor['path']] == {k: donor[k] for k in ('bytes', 'sha256')},
              'Opaque N11 checkpoint and trained model state must join frozen inventory')
    owners = {}
    old_root = Path(old['package_root'])
    for name, item in old['source_owner_pins'].items():
        owners[name] = bind(F / 'datasets' / Path(item['path']).relative_to(old_root), item)
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    owners[prefix + 'legal_span_actor_refinement'] = bind(F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_refinement.py')
    test = bind(F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_refinement_contracts.py')
    attention = bind(F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py')
    tree = ast.parse(Path(owners[prefix + 'legal_span_actor_features']['path']).read_bytes())
    pinned = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'ATTENTION_RECIPE_SHA256' for t in node.targets)]
    r.require(pinned == [attention['sha256']], 'Supplemental raw attention source must match actor implementation pin')
    trainer_pin = bind(F / 'trainer-source-independent-review-v01.json')
    trainer = metadata(trainer_pin['path'], trainer_pin)
    r.require(trainer['schema'] == 'actor-refinement-trainer-source-independent-review/v1'
              and trainer['passed'] is True and trainer['findings'] == [], 'Independent exact trainer source qualification required')
    for item in (owners[prefix + 'legal_span_actor_refinement'], test, bind(F / 'training-design-v01.json')):
        r.require(trainer['artifacts'].get(item['path']) in (item, {k: item[k] for k in ('bytes', 'sha256')}),
                  'Trainer gate must bind exact current source/test/design')
    references = {name: {v: summary['diagnostics'][name][v] for v in ('raw', 'joint')} for name in r.PANELS}
    references['training168'] = {v: summary['final_training_capture'][v] for v in ('raw', 'joint')}
    for pair in references.values():
        for item in pair.values():
            bind(item['path'], item)
            r.require(freeze['results'][item['path']] == {k: item[k] for k in ('bytes', 'sha256')},
                      'All632 N11 saved references must join qualified frozen inventory')
    data_pin = bind(old['data_export']['path'], old['data_export'])
    fresh_pin = bind(old['fresh_source_export']['path'], old['fresh_source_export'])
    data, fresh = metadata(data_pin['path'], data_pin), metadata(fresh_pin['path'], fresh_pin)
    legacy = r.legacy_runner()
    retained = legacy.prior_runner()
    helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder())
    helper.bootstrap(F / 'datasets')
    for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_split_features', 'legal_span_actor_refinement'):
        importlib.import_module(prefix + name)
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    loaded = retained.owner_origins(dict(source_owner_pins=owners))
    mandatory = {prefix + name for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss',
        'legal_span_split_features', 'legal_span_actor_boundary', 'legal_span_actor_features', 'legal_span_conditions_presence', 'legal_span_actor_refinement')}
    r.require(len(owners) == 39 and len(loaded) == 16 and len(mandatory) == 8 and mandatory <= set(loaded) <= set(owners),
              'Exact39 declared/16 loaded/eight mandatory continuation closure required')
    for path in (Path(__file__).resolve(), F / 'run_actor_refinement_v02.py', F / 'run_scope_guardian_v02.py',
                 r.LEGACY_RUNNER, legacy.PRIOR_RUNNER, retained.HELPER, F / 'training-design-v01.json',
                 F / 'actor_refinement_resource_protocol_v02.py'):
        bind(path)
    baseline_pin = bind(F / 'resource-baseline-v01.json')
    baseline = metadata(baseline_pin['path'], baseline_pin)
    for path, item in baseline['artifacts'].items():
        bind(path, item)
    for key in ('observer', 'source_qualification', 'input_manifest', 'observation_policy', 'fresh_metadata_check',
                'sampler_source_qualification', 'resource_bridge_source_qualification'):
        item = baseline[key]
        bind(item['path'], item)
    resource_gate = metadata(baseline['source_qualification']['path'], baseline['source_qualification'])
    for path, item in resource_gate['artifacts'].items():
        bind(path, item)
    for key in ('library_pin', 'ctypes_util_pin', 'cuda_pathfinder_pin'):
        item = old['ctypes_dl_resolution'][key]
        bind(item['path'], item)
    smoke_pin = bind(F / 'actor-refinement-bootstrap-smoke-controls-v02.json')
    smoke = metadata(smoke_pin['path'], smoke_pin)
    r.require(smoke['passed'] is True and smoke['findings'] == [] and smoke['loaded_owners'] == loaded
              and smoke['runner'] == bind(F / 'run_actor_refinement_v02.py'), 'Actual source-only bootstrap receipt required')
    peer_pin = bind(F / 'runner-preparer-source-independent-review-v01.json')
    peer = metadata(peer_pin['path'], peer_pin)
    r.require(peer['schema'] == 'actor-refinement-runner-preparer-source-independent-review/v1'
              and peer['passed'] is True and peer['findings'] == [], 'Exact independent recipe review required')
    for path in (Path(__file__).resolve(), F / 'run_actor_refinement_v02.py',
                 F / 'actor_refinement_bootstrap_smoke_controls_v02.py', Path(smoke_pin['path'])):
        item = bind(path)
        r.require(peer['artifacts'].get(str(path)) in (item, {k: item[k] for k in ('bytes', 'sha256')}),
                  'Recipe gate must bind exact producer and actual bootstrap receipt')
    forbidden = list(old['forbidden_reference_paths'])
    forbidden += [str(N11 / n) for n in ('conditions-presence-result-analysis-v01.json', 'conditions-presence-independent-recount-v01.json')]
    forbidden += [str(N14 / n) for n in ('conditions-balanced-result-analysis-v01.json', 'conditions-balanced-independent-recount-v01.json')]
    forbidden += [str(F / n) for n in ('diagnose_actor_refinement_oracle_v01.py', 'actor-refinement-oracle-diagnostic-v01.json', 'parent-actor-refinement-baseline-v01.json')]
    plan = dict(schema='actor-refinement-cell-plan/v1', package_root=str(F / 'datasets'),
        runner_path=str(F / 'run_actor_refinement_v02.py'), guardian_path=str(F / 'run_scope_guardian_v02.py'),
        attempt_name=r.ATTEMPT, cell=r.CELL, source_owner_pins=owners, artifacts=artifacts,
        data_export=data_pin, fresh_source_export=fresh_pin, source_checkpoint=donor,
        source_model_state_sha256=r.SOURCE_STATE_SHA, context_contract=old['context_contract'],
        training_manifest_sha256=r.digest(data['training_rows']), legacy_prefix_sha256=r.digest(data['training_rows'][:96]),
        source_reference_panels=references, ctypes_dl_resolution=old['ctypes_dl_resolution'], forbidden_reference_paths=forbidden,
        resource_contract=dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300),
        training_seconds=32, diagnostic_panels=[dict(name=n, count=r.COUNTS[n]) for n in r.PANELS],
        evaluation_contract=contract_pin, proposal=bind(F / 'training-design-v01.json'),
        configured_dimension=384, latent_enabled=False, default_promotion=False, Lake_executed=False,
        expected_loaded_owner_count=len(loaded))
    r.validate_plan(plan)
    r.validate_sources(plan, data, fresh, helper, legacy)
    r.qualify_resource_baseline(plan)
    r.require(not os.path.lexists(r.RUN_ROOT / r.ATTEMPT), 'Never-used attempt required')
    for path, item in artifacts.items():
        r.require({k: r.pin(Path(path))[k] for k in ('bytes', 'sha256')} == item, 'Closing admitted input drift')
    r.require(not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'huggingface_hub'} for name in sys.modules),
              'Numerical import during preparation')
    print(r.write(OUTPUT, plan))


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()

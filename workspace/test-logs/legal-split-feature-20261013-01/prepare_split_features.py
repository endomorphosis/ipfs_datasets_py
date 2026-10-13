"""Freeze source-only split-feature inputs without numerical or resource work."""
import argparse
import copy
import importlib
import importlib.abc
import os
from pathlib import Path
import sys

import run_split_features as runner

F = Path(__file__).resolve().parent
PRIOR = F.parent / 'legal-permission-retention-20261012-01'
T = F.parent / 'legal-temporal-binding-20261012-01'


class NoML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers'}:
            raise ValueError('numerical import forbidden in preparation: ' + fullname)
        return None


def add_artifact(artifacts, path):
    path = Path(path)
    value = runner.pin(path)
    runner.require(str(path) not in runner.READ_PINS or runner.READ_PINS[str(path)] == value,
                   'consumed metadata differs from artifact identity')
    brief = {k: value[k] for k in ('bytes', 'sha256')}
    runner.require(str(path) not in artifacts or artifacts[str(path)] == brief, 'artifact identity conflict')
    artifacts[str(path)] = brief
    return value


def close_inputs(artifacts):
    for path, expected in runner.READ_PINS.items():
        runner.require(runner.pin(path) == expected, 'closing consumed metadata drift')
    for path, expected in artifacts.items():
        runner.require({k: runner.pin(path)[k] for k in ('bytes', 'sha256')} == expected,
                       'closing complete artifact drift: ' + path)


def install_inert_guards():
    def audit(event, values):
        if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn')) or event == 'os.system':
            raise ValueError('network/process forbidden in preparation')
    sys.addaudithook(audit)
    sys.meta_path.insert(0, NoML())


def freeze_data():
    prior_path = PRIOR / 'registration-v01.json'
    prior_pin = runner.pin(prior_path)
    runner.require(prior_pin['sha256'] == 'b9c2accf814ef4e31de9c2a83c0714e5e853f5065f6cd2613036d40ecc3ef27d',
                   'exact qualified permission-retention registration required')
    prior = runner.read(prior_path)
    runner.require(runner.READ_PINS[str(prior_path)] == prior_pin, 'consumed prior registration drift')
    destination = F / 'training-export-v01.json'
    data_pin = runner.pin(destination)
    runner.require({k: data_pin[k] for k in ('bytes', 'sha256')} ==
                   {k: prior['data_export'][k] for k in ('bytes', 'sha256')}, 'byte-identical exposed export required')
    data = runner.read(destination)
    runner.require(runner.READ_PINS[str(destination)] == data_pin, 'consumed export drift')
    owners = {}
    for name, expected in prior['source_owner_pins'].items():
        path = F / 'datasets' / Path(expected['path']).relative_to(PRIOR / 'datasets')
        current = runner.pin(path)
        runner.require({k: current[k] for k in ('bytes', 'sha256')} ==
                       {k: expected[k] for k in ('bytes', 'sha256')}, 'retained source changed: ' + name)
        owners[name] = current
    helper = runner.helpers()
    helper.bootstrap(F / 'datasets')
    importlib.import_module('ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_split_features')
    observed = {}
    for name, module in list(sys.modules.items()):
        if name.startswith('ipfs_datasets_py.') and getattr(module, '__file__', None):
            current = runner.pin(Path(module.__file__).resolve())
            runner.require(name not in owners or current == owners[name], 'pure producer drift')
            owners[name] = observed[name] = current
    runner.require(not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers'}
                           for name in sys.modules), 'numerical import occurred')
    artifacts = copy.deepcopy(prior['artifacts'])
    for path, expected in artifacts.items():
        runner.require({k: runner.pin(path)[k] for k in ('bytes', 'sha256')} == expected, 'prior source/input drift')
    required = [Path(__file__).resolve(), F / 'run_split_features.py', F / 'run_scope_guardian.py',
                F / 'bootstrap_inert.py', F / 'run_inert_tests.py', destination, runner.HELPER, prior_path,
                F / 'resource-baseline-audit-design-v01.json', F / 'canonical-resource-intake-v01.json',
                F / 'pre-admission-check-v01.json', F / 'experiment-design-v01.json',
                F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_split_features_contracts.py']
    required.extend(Path(value['path']) for value in owners.values())
    for path in required:
        add_artifact(artifacts, path)
    freeze_path = PRIOR / 'two-cell-output-freeze-v01.json'
    freeze_pin = add_artifact(artifacts, freeze_path)
    runner.require(freeze_pin['sha256'] == '2a268b4b3f5c03cedb29d8d1df6d5718778fc54da9473fabfb5c2eaefde7d46b',
                   'exact qualified parent freeze required')
    freeze = runner.read(freeze_path)
    runner.require(runner.READ_PINS[str(freeze_path)] == freeze_pin, 'consumed parent freeze drift')
    cells = [cell for cell in freeze['cells'] if cell['cell']['id'] == 'all-parameters']
    runner.require(len(cells) == 1, 'exact parent cell required')
    summary_pin = add_artifact(artifacts, Path(cells[0]['summary']['path']))
    runner.require(summary_pin == cells[0]['summary'] and
                   summary_pin['sha256'] == '6861267ec449f210add8f5526074bec040c690c1bd73652bde5f68e48017b73b',
                   'exact qualified parent summary required')
    summary = runner.read(summary_pin['path'])
    runner.require(runner.READ_PINS[summary_pin['path']] == summary_pin, 'consumed parent summary drift')
    parent_panels = {}
    for panel in summary['baseline_panels']:
        current = add_artifact(artifacts, Path(panel['raw']['path']))
        runner.require(current == panel['raw'] and cells[0]['results'].get(current['path']) ==
                       {k: current[k] for k in ('bytes', 'sha256')}, 'exact frozen parent panel capture required')
        runner.require(panel['name'] not in parent_panels, 'duplicate parent panel')
        parent_panels[panel['name']] = current
    parent_reference = dict(freeze=freeze_pin, summary=summary_pin, panels=parent_panels)
    reference = prior['reference_packet']
    runner.require(reference == dict(path=str(F.parent / 'legal-targeted-loss-20261012-01/authored-reference-packet-v01.json'),
        bytes=8262146, sha256='b926dbbc459c8d21a51fd8876598c8b3830a979730b44a4b3c8d15d8f613676e'),
        'reference descriptor differs; reference payload must not be opened')
    record = dict(schema='split-feature-curriculum-registration/v1', data_export=data_pin,
                  reference_packet=reference, prior_registration=prior_pin,
                  prior_plan=runner.pin(T / 'experiment-plan-v02.json'), source_owner_pins=owners,
                  artifacts=artifacts, training_manifests=prior['training_manifests'],
                  tuning_manifest_sha256=prior['tuning_manifest_sha256'], context_contract=prior['context_contract'],
                  observed_pure_package_producers=observed, semantic_gold=False, previously_exposed_authored_evaluation=True,
                  parent_capture_reference=parent_reference,
                  independent_semantic_holdout=False, reference_packet_child_access=False,
                  model_calls=0, checkpoint_JSON_parsed=False, resource_admission=False, compiler_calls=0)
    close_inputs(artifacts)
    runner.write(F / 'registration-v01.json', record)
    print('Prepared exact exposed data and source closure; no numerical imports or admission.')


def make_plan():
    registration_path = F / 'registration-v01.json'
    registration_pin = runner.pin(registration_path)
    registration = runner.read(registration_path)
    runner.require(runner.READ_PINS[str(registration_path)] == registration_pin, 'consumed registration drift')
    runner.require(registration['schema'] == 'split-feature-curriculum-registration/v1', 'exact split registration required')
    prior_plan = T / 'experiment-plan-v02.json'
    old = runner.read(prior_plan)
    runner.require(runner.READ_PINS[str(prior_plan)] == registration['prior_plan'], 'consumed prior plan changed')
    data = runner.read(registration['data_export']['path'])
    runner.require(runner.READ_PINS[registration['data_export']['path']] == registration['data_export'], 'consumed registered data changed')
    artifacts = copy.deepcopy(registration['artifacts'])
    for path in (registration_path, prior_plan):
        add_artifact(artifacts, path)
    cell = dict(id='split-features', trainable_parameter_policy='split-features', actor_ranking_enabled=False,
                presence_ce_weight=1, modality_loss_weight=2)
    ordered = ['old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law']
    panels = [dict(name=name, count=len(data['diagnostic_populations'][name]),
                   has_authored_reference=name not in ('authored_eval', 'law'),
                   provenance='previously_exposed_authored_engineering_not_independent_legal_gold' if name != 'law'
                   else 'previously_exposed_unreviewed_law_source_only') for name in ordered]
    plan = dict(schema=runner.SCHEMA, package_root=str(F / 'datasets'), runner_path=str(F / 'run_split_features.py'),
                guardian_path=str(F / 'run_scope_guardian.py'), helper_pin=runner.pin(runner.HELPER),
                attempt_name='split-feature-20261013-split-features-01', source_owner_pins=registration['source_owner_pins'],
                artifacts=artifacts, ctypes_dl_resolution=old['ctypes_dl_resolution'],
                historical_parent_file_pin=old['historical_parent_file_pin'],
                historical_parent_canonical_sha256=old['historical_parent_canonical_sha256'],
                parent_base_canonical_sha256=old['parent_base_canonical_sha256'],
                parent_model_state_sha256=old['parent_model_state_sha256'], data_export=registration['data_export'],
                cell=cell, training_manifest_sha256=registration['training_manifests']['mixed'],
                tuning_manifest_sha256=registration['tuning_manifest_sha256'], diagnostic_panels=panels,
                context_contract=registration['context_contract'], resource_contract=old['resource_contract'],
                forbidden_reference_paths=list(runner.RETAINED_FORBIDDEN) + [
                    str(F.parent / 'legal-matched-curriculum-20261012-01/authored-reference-packet-v01.json'),
                    registration['reference_packet']['path']], training_seconds=32, seed=1729, batch_order_seed=1729,
                dimension=384, latent_enabled=False, encoder_execution_planned=False, semantic_gold=False,
                independent_semantic_holdout=False, checkpoint_selection_executed=False, default_promotion=False,
                Lake_executed=False, baseline_results=None, baseline_plan=None,
                parent_capture_reference=registration['parent_capture_reference'],
                promotion_gate=dict(schema='legacy-exact-permission-preservation-gate/v1', required_old_exact=96,
                    old_count=96, new_permission_to_obligation_allowed=0, applies_to='raw_and_joint_IR', automatic_selection=False))
    runner.validate_plan(plan)
    runner.validate_data(plan, data, runner.helpers())
    runner.require(not (runner.RUN_ROOT / plan['attempt_name']).exists(), 'attempt already exists')
    close_inputs(artifacts)
    print(runner.write(F / 'split-features-plan-v01.json', plan))


if __name__ == '__main__':
    install_inert_guards()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', action='store_true')
    if parser.parse_args().plan:
        make_plan()
    else:
        freeze_data()

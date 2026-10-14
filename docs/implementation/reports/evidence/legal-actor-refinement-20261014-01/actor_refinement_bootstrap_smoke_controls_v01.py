"""Exact production bootstrap/import smoke only; no data/model/resource entry points."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
RUNNER = F / 'run_actor_refinement_v01.py'
OUTPUT = F / 'actor-refinement-bootstrap-smoke-controls-v01.json'
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise AssertionError(message)


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class NoNumerical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'huggingface_hub'}:
            raise AssertionError('Numerical/SDK import prohibited in bootstrap smoke')
        return None


def audit(event, args):
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
        'os.system', 'os.fork', 'os.kill', 'os.killpg', 'fcntl.flock', 'os.remove', 'os.rename', 'os.mkdir'}:
        raise AssertionError('Process/network/resource/mutation prohibited in bootstrap smoke')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        target = Path(os.fsdecode(args[0])).absolute()
        require('private-runtime-snapshots' not in target.parts and target.name not in
            {'disk-reservations.json', 'resources-start.json', 'resources-final.json', 'ipfs-datasets-resource-scheduler-1000.json'}
            and 'checkpoint' not in target.name and 'reference-packet' not in target.name,
            'Private/model/reference bodies prohibited in bootstrap smoke')
        mode, flags = args[1:3]
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            require(target == OUTPUT and bool(flags & os.O_EXCL), 'Only exclusive own smoke receipt write allowed')
    if event in {'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.link', 'os.symlink'}:
        require(event == 'os.chmod' and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444,
                'Only own smoke receipt freeze allowed')


def mandatory(path):
    module = ast.parse(path.read_bytes())
    main = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    statement = next(node for node in ast.walk(main) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'required_owners' for target in node.targets))
    scope = {'prefix': 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'}
    exec(compile(ast.Module(body=[statement], type_ignores=[]), str(path), 'exec'), scope)
    return scope['required_owners']


def main():
    require(not any(name.startswith('ipfs_datasets_py') for name in sys.modules), 'Cold package process required')
    sys.meta_path.insert(0, NoNumerical())
    sys.addaudithook(audit)
    runner_pin = pin(RUNNER)
    spec = importlib.util.spec_from_file_location('actor_bootstrap_smoke_runner', RUNNER)
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    plan_path = F.parent / 'legal-head-repair-20261014-01/conditions-presence-ce-plan-v01.json'
    plan_pin = pin(plan_path)
    plan = json.loads(plan_path.read_bytes())
    require(len(plan['source_owner_pins']) == 38, 'Exact retained38 public producer closure required')
    old_root = Path(plan['package_root'])
    plan['package_root'] = str(F / 'datasets')
    plan['source_owner_pins'] = {name: dict(value, path=str(F / 'datasets' / Path(value['path']).relative_to(old_root)))
                               for name, value in plan['source_owner_pins'].items()}
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    plan['source_owner_pins'][prefix + 'legal_span_actor_refinement'] = pin(F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_refinement.py')
    legacy = runner.legacy_runner(); retained = legacy.prior_runner(); helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder()); helper.bootstrap(Path(plan['package_root']))
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    # These are the exact production main import calls, in the same order.
    for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_split_features', 'legal_span_actor_refinement'):
        importlib.import_module(prefix + name)
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    loaded = retained.owner_origins(plan)
    expected = mandatory(RUNNER)
    require(len(loaded) == 16 and len(expected) == 8 and expected <= set(loaded) <= set(plan['source_owner_pins']),
            'Exact16 loaded producers and eight actual trainers required')
    for name, descriptor in plan['source_owner_pins'].items():
        require(pin(Path(descriptor['path'])) == descriptor, 'All39 declared source pins must remain exact')
    require(loaded == retained.owner_origins(plan) and pin(RUNNER) == runner_pin and pin(plan_path) == plan_pin,
            'Closing source/plan/loaded-owner drift')
    require(not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'huggingface_hub'}
                    for name in sys.modules), 'Unexpected numerical/SDK import')
    value = dict(schema='actor-refinement-production-bootstrap-smoke-controls/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), controls_source=pin(Path(__file__).resolve()),
        runner=runner_pin, retained_plan=plan_pin, legacy_helper=pin(runner.LEGACY_RUNNER),
        retained_helper=pin(legacy.PRIOR_RUNNER), bootstrap_helper=pin(retained.HELPER),
        loaded_owner_count=16, declared_owner_count=39, mandatory_loaded_owner_count=8,
        loaded_owners=loaded, mandatory_loaded_owners=sorted(expected),
        all39_raw_source_owner_pins_closed=True, exact_production_bootstrap_used=True,
        bootstrap_inert_namespace_wrapper_used=False, source_imports_only=True,
        model_calls=0, inference_source_forwards=0, optimizer_updates=0, numerical_imports=0,
        checkpoint_JSON_parses=0, data_export_or_gold_reads=0, private_global_body_reads=0,
        resource_API_calls=0, network_calls=0, Git_mutations=0,
        limitations=['Source-only import smoke, not an actual model or runtime-resource qualification.'])
    with OUTPUT.open('x') as out:
        json.dump(value, out, indent=2, sort_keys=True); out.write('\n')
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=True, receipt=pin(OUTPUT), loaded_owner_count=16)))


if __name__ == '__main__':
    main()

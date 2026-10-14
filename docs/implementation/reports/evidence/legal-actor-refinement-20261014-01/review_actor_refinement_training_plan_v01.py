"""Review the concrete continuation plan without model or private-state access."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
OUTPUT = F / 'actor-refinement-ce-training-review-v01.json'
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch', 'numpy', 'ipfs_datasets_py', 'transformers', 'sentence_transformers', 'huggingface_hub'}:
        raise ValueError('Production/numerical/SDK imports prohibited')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
        'os.system', 'os.fork', 'fcntl.flock', 'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.replace', 'os.unlink', 'os.kill', 'os.killpg'}:
        raise ValueError('Process/network/resource/shared operations prohibited')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).absolute()
        require('private-runtime-snapshots' not in path.parts and path.name not in {
            'disk-reservations.json', 'resources-start.json', 'resources-final.json', 'ipfs-datasets-resource-scheduler-1000.json'},
            'Private/global body reads prohibited')
        mode, flags = args[1:3]
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        require(not writing or path == OUTPUT and bool(flags & os.O_EXCL), 'Only exclusive concrete review write allowed')
    if event in {'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.link', 'os.symlink'}:
        require(event == 'os.chmod' and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444,
                'Only own review freeze allowed')


def main(args):
    require(not os.path.lexists(OUTPUT), 'Exclusive new review required')
    sys.addaudithook(audit)
    specification = importlib.util.spec_from_file_location('qualified_actor_plan_runner', F / 'run_actor_refinement_v01.py')
    r = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(r)
    observed = {}

    def bind(path, expected=None):
        item = r.pin(Path(path))
        require(expected is None or all(item[k] == expected[k] for k in ('bytes', 'sha256'))
                and ('path' not in expected or item['path'] == expected['path']), 'Exact reviewed identity differs')
        require(item['path'] not in observed or observed[item['path']] == item, 'Prior reviewed identity drift')
        observed[item['path']] = item
        return item

    def read(path, expected=None):
        require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name
                and 'results' not in Path(path).parts, 'Checkpoint/reference/result JSON parsing prohibited')
        item = bind(path, expected)
        return r.read(path, item)

    own = bind(Path(__file__).resolve())
    plan_pin = bind(F / 'actor-refinement-ce-plan-v01.json', dict(bytes=args.plan_bytes, sha256=args.plan_sha256))
    plan = read(plan_pin['path'], plan_pin)
    r.validate_plan(plan)
    for path, item in plan['artifacts'].items():
        bind(path, item)
    ledger = r.qualify_resource_baseline(plan)
    baseline_pin = bind(F / 'resource-baseline-v01.json')
    baseline = read(baseline_pin['path'], baseline_pin)
    for filename, schema, files in (
        ('trainer-source-independent-review-v01.json', 'actor-refinement-trainer-source-independent-review/v1',
         ('datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_refinement.py',
          'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_refinement_contracts.py', 'training-design-v01.json')),
        ('runner-preparer-source-independent-review-v01.json', 'actor-refinement-runner-preparer-source-independent-review/v1',
         ('run_actor_refinement_v01.py', 'prepare_actor_refinement_v01.py',
          'actor_refinement_bootstrap_smoke_controls_v01.py', 'actor-refinement-bootstrap-smoke-controls-v01.json'))):
        gate = read(F / filename)
        require(gate['schema'] == schema and gate['passed'] is True and gate['findings'] == [], 'Qualified source gate required')
        for name in files:
            item = bind(F / name)
            require(gate['artifacts'].get(item['path']) in (item, {k: item[k] for k in ('bytes', 'sha256')}),
                    'Current reviewed source/receipt must join peer gate')
    smoke = read(F / 'actor-refinement-bootstrap-smoke-controls-v01.json')
    require(smoke['passed'] is True and smoke['loaded_owner_count'] == 16 and smoke['declared_owner_count'] == 39
            and smoke['mandatory_loaded_owner_count'] == 8
            and all(plan['source_owner_pins'].get(name) == item for name, item in smoke['loaded_owners'].items()),
            'Actual source-only39/16/8 bootstrap qualification required')
    attention = bind(F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py')
    algorithms = list(plan['source_owner_pins'].values()) + [attention]
    require(len(algorithms) == len({item['path'] for item in algorithms}) == 40
            and attention['sha256'] == 'fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731'
            and all(plan['artifacts'].get(item['path']) == {k: item[k] for k in ('bytes', 'sha256')} for item in algorithms),
            'All40 raw algorithm sources must be admitted')
    require(plan['training_manifest_sha256'] == 'afa0deeebf4052831883c046104a8808342b67a7c8dc2e58de2f9208a9287c34'
            and plan['evaluation_contract']['sha256'] == 'a8e64cee523d57149b6becaf18023bf87a9ecdb147d83e9c42453fce9230944e'
            and plan['proposal']['sha256'] == 'f56bbf45b2dfbd5465dee4b32fda23417f44543686dcc95cde42ec91961a8e4e',
            'Fixed science/training contract differs')
    require(not os.path.lexists(r.RUN_ROOT / r.ATTEMPT), 'Never-used attempt must remain absent')
    runner = bind(F / 'run_actor_refinement_v01.py')
    guardian = bind(F / 'run_scope_guardian_v02.py')
    for path, item in list(observed.items()):
        bind(path, item)
    result = dict(schema='actor-refinement-concrete-training-independent-review/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), observer=own, phase='training', package_root=plan['package_root'],
        run_root=str(r.RUN_ROOT), plan=plan_pin, plan_sha256=plan_pin['sha256'], runner_sha256=runner['sha256'],
        guardian_sha256=guardian['sha256'], baseline=baseline_pin, baseline_current_record_count=ledger['record_count'],
        baseline_full_nonreleased_claim_bytes=ledger['full_nonreleased_claim_bytes'], source_owner_count=39,
        raw_algorithm_source_file_count=40, loaded_source_owners=16, mandatory_loaded_source_owners=8,
        training_budget=dict(updates=32, batch_size=12, seed=1729, source_row_occurrences=384, fresh_Adam=True,
            actor_CE=True, actor_trainable_tensors=6, frozen_nonactor_tensors=36, active_scalars=258,
            ranking_enabled=False, conditions_loss_enabled=False),
        artifacts={path:{k:item[k] for k in ('bytes', 'sha256')} for path,item in observed.items()},
        models_created_by_reviewer=0, optimizer_updates_by_reviewer=0, checkpoint_JSON_parses_by_reviewer=0,
        private_body_reads_by_reviewer=0, resource_API_calls_by_reviewer=0, default_promotion=False, scientific_success=None)
    r.write(OUTPUT, result)
    OUTPUT.chmod(0o444)
    print(json.dumps(r.pin(OUTPUT), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-bytes', required=True, type=int)
    parser.add_argument('--plan-sha256', required=True)
    main(parser.parse_args())

"""Freeze one source-only N10 actor-features CE plan without numerical imports or model parsing."""
import argparse
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
N9 = F.parent / 'legal-actor-ranking-20261013-01'
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
        if 'private-runtime-snapshots' in path.parts or path.name in {'disk-reservations.json', 'resources-start.json', 'resources-final.json', 'ipfs-datasets-resource-scheduler-1000.json'}:
            raise AssertionError('Private/global bodies prohibited in preparation')
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            if path != F / 'actor-features-ce-plan-v02.json' or not bool(flags & os.O_EXCL):
                raise AssertionError('Only exclusive new owned plan write allowed')


sys.meta_path.insert(0, NoNumerical())
sys.addaudithook(audit)
spec = importlib.util.spec_from_file_location('actor_ranking_plan_runner', F / 'run_actor_features_v02.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
_read = runner.read


def metadata(path, expected=None):
    runner.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name,
                   'Checkpoint/reference JSON parsing prohibited in preparation')
    return _read(path, expected)


runner.read = metadata


def qualify_retry_baseline(baseline):
    require, digest, phase = runner.require, runner.digest, F
    ledger = baseline['baseline_ledger']
    reconciled = ledger['only_reconciled_prior_claim']
    require(baseline['schema'] == 'actor-features-resource-baseline/v2'
            and baseline['passed'] is True and baseline['findings'] == []
            and ledger['record_count'] == ledger['previous_record_count'] == 536
            and ledger['unchanged_other_record_count'] == 535
            and ledger['all_other535_record_bodies_unchanged'] is True
            and ledger['failed_N7_claim_retained_and_fully_charged'] is True
            and ledger['failed_N8_claim_explicitly_reconciled'] is True
            and ledger['record_status_counts'] == {'released': 435, 'retained': 101}
            and ledger['full_nonreleased_claim_bytes'] == 44381777216,
            'Qualified post-reconciliation536/535 resource baseline required')
    require(type(reconciled) is dict and set(reconciled) == {'reservation_id', 'previous_record_body_sha256',
                'record_body_sha256', 'status', 'storage_bytes'}
            and reconciled['reservation_id'] == '893d4ed80ab3497f95b1490080e3caa3'
            and reconciled['previous_record_body_sha256'] == '63cbb539d211fa47bf9a19d9b50c45dd4f2f4f8075d3d27b7597466c5174386c'
            and reconciled['status'] == 'released' and type(reconciled['storage_bytes']) is int
            and reconciled['storage_bytes'] == 200000000
            and type(ledger['record_body_hashes']) is dict and len(ledger['record_body_hashes']) == 536
            and all(type(key) is str and type(value) is str and len(value) == 64
                and all(c in '0123456789abcdef' for c in value) for key, value in ledger['record_body_hashes'].items())
            and ledger['record_body_hashes'][reconciled['reservation_id']] == reconciled['record_body_sha256']
            and digest(ledger['record_body_hashes']) == ledger['record_body_hash_map_sha256'],
            'Only exact proved N8 own claim may be reconciled; post-recovery full map must join')
    require(baseline['prior_baseline'] == dict(path=str(phase / 'resource-baseline-v01.json'), bytes=77873,
                sha256='0d9930ff9831f0fb135439a066f0345e2fa3e9720a8827f74366253016b4f8f2'),
            'Immutable pre-recovery baseline anchor differs')
    for key, name in (('explicit_reconciliation', 'actor-features-retained-claim-reconciliation-v01.json'),
                      ('recovery_preflight', 'actor-features-retained-claim-preflight-v01.json')):
        proof = baseline[key]
        require(type(proof) is dict and set(proof) == {'path', 'bytes', 'sha256'}
                and proof['path'] == str(phase / name) and type(proof['bytes']) is int and proof['bytes'] > 0
                and type(proof['sha256']) is str and len(proof['sha256']) == 64
                and all(c in '0123456789abcdef' for c in proof['sha256'])
                and baseline['artifacts'].get(proof['path']) == proof,
                'Exact qualified public reconciliation/preflight provenance required')
    return ledger

def prepare():
    artifacts = {}
    def bind(path, expected=None):
        value = runner.pin(Path(path))
        runner.require(expected is None or value == expected, 'Expected retained raw descriptor differs')
        runner.require(value['path'] not in runner.READ_PINS or runner.READ_PINS[value['path']] == value,
                       'Parsed/bound byte custody differs')
        brief = {k: value[k] for k in ('bytes', 'sha256')}
        runner.require(value['path'] not in artifacts or artifacts[value['path']] == brief, 'Raw artifact identity conflict')
        artifacts[value['path']] = brief
        return value
    final_pin=bind(N9/'final-integration-independent-review-v01.json')
    runner.require(final_pin['bytes']==30675 and final_pin['sha256']=='cc85e00cb197186cddb8a82ef73c594b9dda56ae577710be048728d674af292a','Qualified N9 final anchor required')
    final=metadata(final_pin['path'],final_pin)
    hub_pin=bind(N9/'hf-publication-actual-independent-review-v01.json')
    runner.require(hub_pin['bytes']==119034 and hub_pin['sha256']=='0b385ffbf455239a9c5e6aa7457d68bffed91a07ec797bb1628d5be5096807e8','Exact qualified N9 Hub anchor required')
    hub=metadata(hub_pin['path'],hub_pin)
    runner.require(final['schema']=='actor-ranking-final-integration-independent-review/v1' and final['passed'] is True and final['findings']==[]
        and hub['passed'] is True and hub['findings']==[] and final['immutable_Hub_revision']==hub['revision']=='3c430bdb412a6bd0871f813a944dfec5b2f4c8e9'
        and final['artifacts'][hub_pin['path']]=={k:hub_pin[k] for k in ('bytes','sha256')},'Qualified immutable N9 final/Hub join required')
    old_plan_pin=bind(N9/'actor-ranking-hinge-plan-v01.json')
    runner.require(hub['artifacts'][old_plan_pin['path']]=={k:old_plan_pin[k] for k in ('bytes','sha256')},'Historical N9 source recipe must join qualified Hub inventory')
    old_plan=metadata(old_plan_pin['path'],old_plan_pin)
    runner.require(old_plan['schema']=='actor-ranking-cell-plan/v1' and old_plan['cell']=='actor-ranking-hinge'
        and len(old_plan['source_owner_pins'])==36,'Exact retained36-owner N9 source inventory required')
    owners = {}
    for name, descriptor in old_plan['source_owner_pins'].items():
        relative = Path(descriptor['path']).relative_to(N9 / 'datasets')
        new = bind(F / 'datasets' / relative)
        runner.require(all(new[k] == descriptor[k] for k in ('bytes', 'sha256')), 'Retained36 producer differs in N10')
        owners[name] = new
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    candidate = F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_features.py'
    candidate_test = F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_features_contracts.py'
    owners[prefix + 'legal_span_actor_features'] = bind(candidate)
    trainer_review_pin = bind(F / 'trainer-source-independent-review-v01.json')
    trainer_review = metadata(trainer_review_pin['path'], trainer_review_pin)
    runner.require(trainer_review['passed'] is True and trainer_review['findings'] == [], 'Clean N10 trainer source review required')
    for path in (candidate, candidate_test):
        descriptor = bind(path)
        approved = trainer_review['artifacts'][str(path)]
        runner.require(approved in (descriptor, {k: descriptor[k] for k in ('bytes', 'sha256')}),
                       'Exact actor-features source/test must join trainer qualification')
    data_pin = bind(Path(old_plan['data_export']['path']), old_plan['data_export'])
    data = metadata(data_pin['path'], data_pin)
    fresh_pin = bind(Path(old_plan['fresh_source_export']['path']), old_plan['fresh_source_export'])
    fresh = metadata(fresh_pin['path'], fresh_pin)
    source_checkpoint = bind(Path(old_plan['source_checkpoint']['path']), old_plan['source_checkpoint'])
    runner.require(source_checkpoint['sha256'] == runner.SOURCE_SHA and source_checkpoint['bytes'] == 3592389,
                   'Exact common N4 source file required')
    references = old_plan['source_reference_panels']
    for pair in references.values():
        for value in pair.values():
            bind(Path(value['path']), value)
    legacy = runner.legacy_runner(); retained = legacy.prior_runner(); helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder()); helper.bootstrap(F / 'datasets')
    for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_split_features', 'legal_span_actor_features'):
        importlib.import_module(prefix + name)
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    loaded = retained.owner_origins(dict(source_owner_pins=owners))
    required = {prefix + name for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss',
                                          'legal_span_split_features', 'legal_span_actor_boundary', 'legal_span_actor_features')}
    runner.require(len(loaded) == 14 and required <= set(loaded) <= set(owners)
                   and all(loaded[name] == owners[name] for name in loaded), 'Exact actual14 loaded/six mandatory source subset required')
    for path in (Path(__file__).resolve(), F / 'run_actor_features_v02.py', F / 'run_scope_guardian_v02.py',
                 runner.LEGACY_RUNNER, legacy.PRIOR_RUNNER, retained.HELPER,
                 F / 'evaluation-contract-v01.json', F / 'training-design-v02.json', F / 'resource-baseline-v02.json'):
        bind(path)
    baseline_pin = bind(F / 'resource-baseline-v02.json')
    baseline = metadata(baseline_pin['path'], baseline_pin)
    qualify_retry_baseline(baseline)
    for key in ('explicit_reconciliation', 'recovery_preflight', 'prior_baseline'):
        proof = baseline[key]
        bind(Path(proof['path']), proof)
    for key in ('library_pin', 'ctypes_util_pin', 'cuda_pathfinder_pin'):
        descriptor = old_plan['ctypes_dl_resolution'][key]
        bind(Path(descriptor['path']), descriptor)
    forbidden=list(old_plan['forbidden_reference_paths'])+[
        str(N9/'actor-ranking-result-analysis-v01.json'),str(N9/'actor-ranking-output-freeze-v01.json'),
        str(N9/'actor-ranking-hinge-runtime-review-v01.json'),str(N9/'actor-ranking-independent-recount-v01.json')]
    smoke_pin = bind(F / 'actor-features-bootstrap-smoke-controls-v02.json')
    smoke = metadata(smoke_pin['path'], smoke_pin)
    runner.require(smoke['passed'] is True and smoke['findings'] == []
                   and smoke['runner'] == bind(F / 'run_actor_features_v02.py')
                   and smoke['loaded_owner_count'] == 14 and smoke['mandatory_loaded_owner_count'] == 6
                   and smoke['all37_raw_source_owner_pins_closed'] is True
                   and smoke['exact_production_bootstrap_used'] is True, 'Actual inert production-bootstrap import smoke required')
    bind(Path(smoke['controls_source']['path']), smoke['controls_source'])
    peer_pin = bind(F / 'runner-preparer-source-independent-review-v02.json')
    peer = metadata(peer_pin['path'], peer_pin)
    runner.require(peer['schema'] == 'actor-features-runner-preparer-source-independent-review/v1'
                   and peer['passed'] is True and peer['findings'] == [], 'Exact independent runner/preparer source qualification required')
    for path in (Path(__file__).resolve(), F / 'run_actor_features_v02.py',
                 F / 'actor_features_bootstrap_smoke_controls_v02.py', F / 'actor-features-bootstrap-smoke-controls-v02.json'):
        descriptor = bind(path)
        runner.require(peer['artifacts'][str(path)] in (descriptor, {k:descriptor[k] for k in ('bytes','sha256')}),
                       'Peer review must close exact runner/preparer and actual smoke source/receipt')
    plan = dict(schema='actor-features-cell-plan/v1', package_root=str(F / 'datasets'),
        runner_path=str(F / 'run_actor_features_v02.py'), guardian_path=str(F / 'run_scope_guardian_v02.py'),
        attempt_name=runner.ATTEMPT, cell=runner.CELL, source_owner_pins=owners, artifacts=artifacts,
        data_export=data_pin, fresh_source_export=fresh_pin, source_checkpoint=source_checkpoint,
        source_model_state_sha256=runner.SOURCE_STATE_SHA, context_contract=old_plan['context_contract'],
        training_manifest_sha256=runner.digest(data['training_rows']), legacy_prefix_sha256=runner.digest(data['training_rows'][:96]),
        source_reference_panels=references, ctypes_dl_resolution=old_plan['ctypes_dl_resolution'], forbidden_reference_paths=forbidden,
        resource_contract=dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300),
        training_seconds=32, diagnostic_panels=[dict(name=n, count=runner.COUNTS[n]) for n in runner.PANELS],
        evaluation_contract=runner.pin(F / 'evaluation-contract-v01.json'), proposal=runner.pin(F / 'training-design-v02.json'),
        configured_dimension=384, latent_enabled=False, default_promotion=False, Lake_executed=False)
    runner.validate_plan(plan); runner.validate_sources(plan, data, fresh, helper, legacy)
    runner.require(not (runner.RUN_ROOT / runner.ATTEMPT).exists(), 'Immutable attempt already exists')
    schedule = retained.schedule(data['training_rows'])
    runner.require(len(schedule['batch_indices']) == 32 and sum(map(len, schedule['batch_indices'])) == 384,
                   'Exact inherited deterministic32/384 schedule required')
    for path, expected in artifacts.items():
        runner.require({k: runner.pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Closing admitted source drift')
    for mapping in (runner.READ_PINS, legacy.READ_PINS):
        for path, expected in mapping.items():
            runner.require(runner.pin(Path(path)) == expected, 'Closing consumed metadata drift')
    runner.require(not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'huggingface_hub'}
                           for name in sys.modules), 'Unexpected numerical/SDK import')
    print(runner.write(F / (runner.CELL + '-plan-v02.json'), plan))


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    prepare()

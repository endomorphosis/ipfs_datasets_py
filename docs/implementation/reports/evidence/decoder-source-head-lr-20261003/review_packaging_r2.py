"""Independently verify source-head LR and readout-probe evidence without running models."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import tarfile
import xml.etree.ElementTree as ET

P = Path('/home/barberb/lift_coding/external/ipfs_datasets')
R = Path(__file__).resolve().parent
E = P / 'docs/implementation/reports/evidence/decoder-source-head-lr-20261003'
RUNTIME = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py'
RUNTIME_SHA = 'ce80ed6294009e04580051e6eb06a817d74a8a56f04814ad0a698e3d27dd0d41'
checks = 0
findings = []
artifacts = {}


def check(value, label):
    global checks
    checks += 1
    if not value:
        findings.append(label)


def stream_info(stream):
    digest = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(1048576), b''):
        digest.update(block)
        size += len(block)
    return dict(bytes=size, sha256=digest.hexdigest())


def info(path):
    with Path(path).open('rb') as stream:
        return stream_info(stream)


def bytes_info(value):
    return dict(bytes=len(value), sha256=hashlib.sha256(value).hexdigest())


def read(path):
    path = Path(path)
    content = path.read_bytes()
    artifacts[str(path)] = bytes_info(content)
    return json.loads(content)


def git_blob(commit, path):
    return subprocess.check_output(['git', 'show', commit + ':' + path], cwd=P)


assert (E / 'manifest.json').is_file() and (E / 'results.json').is_file(), 'builder not finalized'
m = read(E / 'manifest.json')
r = read(E / 'results.json')
own = read(R / 'owned-files.json')
base = read(R / 'base.json')['base']
doc = read(R / 'documentation-review.json')
audit = read(R / 'independent-audit.json')
ready = read(R / 'readiness.json')
summary = read(R / 'training-r1/results/summary.json')
plan = read(R / 'training-plan.json')
training_manifest = read(R / 'training-manifest.json')
check(m['schema'] == 'source-head-learning-rate-archive/v1', 'current archive schema')
check(r['schema'] == 'source-head-learning-rate-results/v1', 'current results schema')
check(m['archive'] == r['archive'], 'matching logical archive metadata')
check(m['archive_filename'] == 'evidence.tar.xz', 'known archive format')
check(r['plan'] == plan and training_manifest['plan_sha256'] == artifacts[str(R / 'training-plan.json')]['sha256'], 'sealed plan binding')
archive = E / m['archive_filename']
chunks = hashlib.sha256()
offset = 0
for index, part in enumerate(m['archive_parts'], 1):
    path = E / part['filename']
    actual = info(path)
    artifacts[str(path)] = actual
    check(part['filename'] == f'evidence.tar.xz.part-{index:03d}' and part['offset_bytes'] == offset, 'ordered chunk ' + str(index))
    check(actual == {k: part[k] for k in ('bytes', 'sha256')} and 0 < actual['bytes'] <= 48_000_000, 'chunk bytes ' + str(index))
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            chunks.update(block)
            offset += len(block)
check(bool(m['archive_parts']) and dict(bytes=offset, sha256=chunks.hexdigest()) == m['archive'], 'assembled chunk digest')
artifacts[str(archive)] = info(archive)
check(artifacts[str(archive)] == m['archive'], 'local archive equals verified chunks')
check(str(archive.relative_to(P)) not in own, 'logical unchunked archive not owned publication')
seen = {}
source_hashes = {}
special = {}
protected_hashes = {v['sha256'] for v in m['protected_external_artifacts'].values()}
capture_names = {'validation/' + name for name in ('documentation-review.json', 'independent-audit.json', 'readiness.json')}
with tarfile.open(archive, 'r|xz') as bundle:
    for member in bundle:
        check(member.isfile() and not Path(member.name).is_absolute() and '..' not in Path(member.name).parts, 'safe regular member ' + member.name)
        check(member.name not in seen, 'unique member ' + member.name)
        if not member.isfile():
            continue
        payload = bundle.extractfile(member)
        if member.name in capture_names:
            content = payload.read()
            actual = bytes_info(content)
            special[member.name] = json.loads(content)
        else:
            actual = stream_info(payload)
        seen[member.name] = actual
        check(m['members'].get(member.name) == actual, 'member hash ' + member.name)
        check(actual['sha256'] not in protected_hashes, 'protected checkpoint bytes absent ' + member.name)
        if member.name.startswith('source/'):
            source_hashes[member.name[len('source/'):]] = actual['sha256']
check(seen == m['members'], 'complete member inventory')
for label, pattern, count in [
    ('typed states', r'^validation/training-r1/results/[^/]+/(initial|selected|last-attempt)-state\.json$', 36),
    ('control panels', r'^validation/training-r1/results/[^/]+/(selected|last-attempt)/evaluation-[^/]+\.json$', 216),
    ('raw training reports', r'^validation/training-r1/results/[^/]+/training\.json$', 12),
]:
    check(sum(bool(re.match(pattern, name)) for name in seen) == count, label + ' count')
check(m['publication_producer_overrides'] == {}, 'no current producer overrides')
check(m['validated_producer_source_sha256'] == m['publication_producer_source_sha256'], 'current producer union equality')
for relative, digest in m['validated_producer_source_sha256'].items():
    check(source_hashes.get(relative) == digest, 'exact current producer ' + relative)
check(source_hashes.get(RUNTIME) == training_manifest['extensions'][RUNTIME] == RUNTIME_SHA, 'current runtime archived and frozen')
check(bytes_info(git_blob(base, RUNTIME))['sha256'] == RUNTIME_SHA, 'current runtime exact base Git blob')
check(RUNTIME not in own and RUNTIME not in r['candidate_sha256'], 'unchanged runtime not staged as candidate')
for relative, digest in r['candidate_sha256'].items():
    actual = info(P / relative)
    artifacts[str(P / relative)] = actual
    check(actual['sha256'] == digest and source_hashes.get(relative) == digest, 'candidate exact archived/live source ' + relative)
check(r['candidate_sha256']['docs/autoencoders/source_head_training.md'] == doc['document_sha256']
    and r['candidate_sha256']['docs/autoencoders/decoder_length_distillation.md'] == doc['guide_sha256'], 'both documents reviewed hashes')
check(special.get('validation/documentation-review.json') == doc and doc['passed'], 'archive document review binding')
check(special.get('validation/independent-audit.json') == audit and audit['passed'] and audit['finding_count'] == 0 and not audit['findings'], 'archive independent audit binding')
check(special.get('validation/readiness.json') == ready and ready['passed'] and ready['finding_count'] == 0 and not ready['findings'], 'archive readiness binding')
check(seen['validation/independent-audit.json']['sha256'] == r['independent_audit_sha256'] and r['independent_audit_checks'] == audit['checks'], 'published dynamic independent audit count')
for name, expected in m['publication_support'].items():
    path = E / name
    check(not Path(name).is_absolute() and '..' not in Path(name).parts, 'safe publication support ' + name)
    actual = info(path)
    artifacts[str(path)] = actual
    check(actual == expected, 'publication support ' + name)
check((E / 'README.md').read_bytes() == (R / 'public-readme.txt').read_bytes(), 'README matches reviewed source bytes')
check(info(E / 'README.md') == m['publication_support']['README.md'], 'README exact manifest support digest')
expected_owned = set(r['candidate_sha256']) | {str((E / item['filename']).relative_to(P)) for item in m['archive_parts']} | {str((E / name).relative_to(P)) for name in ['manifest.json', 'results.json', *m['publication_support']]}
check(len(own) == len(set(own)) and set(own) == expected_owned, 'exact owned publication inventory')

# Authenticate predecessor manifests using their immutable Git blobs. Dependency
# member references remain explicit; current archives never silently absorb old weights.
deps = {item['id']: item for item in m['archive_dependencies']}
check(len(deps) == len(m['archive_dependencies']), 'unique dependency identifiers')
dep_manifests = {}
for identity, dep in deps.items():
    record = dep['manifest']
    content = git_blob(dep['git_commit'], record['path'])
    check(bytes_info(content) == {k: record[k] for k in ('bytes', 'sha256')}, 'exact dependency manifest ' + identity)
    ancestor = json.loads(content)
    dep_manifests[identity] = ancestor
    check({k: dep['archive'][k] for k in ('bytes', 'sha256')} == ancestor['archive'], 'dependency archive metadata ' + identity)
for path, reference in m['referenced_artifacts'].items():
    check(reference['kind'] in ('archive_member', 'git_blob') and reference['dependency_id'] in deps, 'exact predecessor ref ' + path)
    check(type(reference['bytes']) is int and reference['bytes'] > 0 and re.fullmatch('[0-9a-f]{64}', reference['sha256']) is not None, 'reference digest ' + path)
    expected = {k: reference[k] for k in ('bytes', 'sha256')}
    if reference['kind'] == 'archive_member':
        check(dep_manifests[reference['dependency_id']]['members'].get(reference['member']) == expected, 'authenticated predecessor member ' + path)
    else:
        check(reference['git_commit'] == deps[reference['dependency_id']]['git_commit'], 'Git reference commit ' + path)
        check(bytes_info(git_blob(reference['git_commit'], reference['path'])) == expected, 'authenticated predecessor Git blob ' + path)
for path, reference in m['protected_external_artifacts'].items():
    check(info(path) == {k: reference[k] for k in ('bytes', 'sha256')}, 'protected bytes unchanged ' + path)
    check(reference['bundled'] is False and reference['role'] == 'protected_unmodified_not_executed_input' and path not in m['original_artifact_archive_paths'], 'protected not bundled ' + path)


def bound_artifact(path, expected, label, current=True):
    if current:
        actual = info(path)
        artifacts[str(path)] = actual
        check(actual == expected, label + ' current ' + path)
    if path in m['original_artifact_archive_paths']:
        check(seen.get(m['original_artifact_archive_paths'][path]) == expected, label + ' archived ' + path)
    elif path in m.get('post_archive_artifact_paths', {}):
        check(m['publication_support'].get(m['post_archive_artifact_paths'][path]) == expected, label + ' postarchive ' + path)
    else:
        for section in ('referenced_artifacts', 'external_runtime_dependencies', 'protected_external_artifacts'):
            if path in m[section]:
                check({k: m[section][path][k] for k in ('bytes', 'sha256')} == expected, label + ' ' + section + ' ' + path)
                break
        else:
            check(False, label + ' unresolved ' + path)


for label, review in [('documentation', doc), ('independent', audit), ('readiness', ready)]:
    for path, expected in review['artifacts'].items():
        bound_artifact(path, expected, label)
for path, digest in training_manifest['inputs'].items():
    actual = info(path)
    check(actual['sha256'] == digest, 'sealed input ' + path)
    bound_artifact(path, actual, 'training input', current=False)
scoped = dict(tests=0, failures=0, errors=0, skipped=0)
for suite in ET.parse(R / 'tests-scoped.xml').getroot().iter('testsuite'):
    for key in scoped:
        scoped[key] += int(suite.get(key, 0))
check(r['tests'] == scoped and scoped['tests'] == ready['analysis']['tests']['fresh_scoped_count'] and scoped['tests'] > 2430 and not any(scoped[key] for key in ('failures', 'errors', 'skipped')), 'published fresh scoped tests match XML and readiness')
check(summary['complete'] is True and len(summary['runs']) == len(r['runs']) == 12 and summary['all_six_original_first_last_baselines_replayed'] is True, 'complete 12-fit study and six baseline replays')
quality = {(row['dimension'], row['arm'], row['seed']): row for row in r['runs']}
check(len(quality) == 12, 'unique published fit identities')
selection = []
for entry in summary['runs']:
    run = read(entry['summary_path'])
    check(artifacts[entry['summary_path']]['sha256'] == entry['summary_sha256'], 'summary index digest ' + entry['summary_path'])
    bound_artifact(entry['summary_path'], artifacts[entry['summary_path']], 'fit summary', current=False)
    published = quality[(run['dimension'], run['arm'], run['seed'])]
    for key in ('arm', 'dimension', 'seed', 'recipe', 'training_call_elapsed_seconds', 'elapsed_seconds', 'trainable_parameter_count', 'baseline_replay'):
        check(published[key] == run[key], 'fit summary value ' + entry['summary_path'] + ':' + key)
    report = read(run['training_ref']['path'])
    check(artifacts[run['training_ref']['path']]['sha256'] == run['training_ref']['sha256'], 'raw training report digest ' + entry['summary_path'])
    bound_artifact(run['training_ref']['path'], artifacts[run['training_ref']['path']], 'training report', current=False)
    for key in ('selected_epoch', 'optimizer_steps', 'initial_weights_sha256', 'selected_weights_sha256', 'last_complete_attempt_weights_sha256'):
        check(published[key] == report[key], 'fit selection/report value ' + entry['summary_path'] + ':' + key)
    for role, key in [('initial', 'initial_weights_sha256'), ('selected', 'selected_weights_sha256'), ('last-attempt', 'last_complete_attempt_weights_sha256')]:
        reference = run['states'][role]
        state = read(reference['path'])
        bound_artifact(reference['path'], {k: reference[k] for k in ('bytes', 'sha256')}, 'retained state', current=False)
        check(artifacts[reference['path']] == {k: reference[k] for k in ('bytes', 'sha256')}, 'state current digest ' + reference['path'])
        check(state['dimension'] == run['dimension'] and state['role'] == role and state['tensor_sha256'] == reference['tensor_sha256'] == report[key], 'retained state selection binding ' + reference['path'])
        check(state['selected'] is (role == 'selected' or (role == 'last-attempt' and report['last_complete_attempt_is_selected'])), 'retained state role ' + reference['path'])
        for flag in ('admitted', 'qualified', 'lake_executed', 'checkpoint_promoted', 'convergence_proven', 'formalized', 'roundtrip_ok'):
            check(state[flag] is False, 'state authority ' + reference['path'] + ':' + flag)
        del state
    check(set(run['postfit']) == {'selected', 'last-attempt'} and all(len(panels) == 9 for panels in run['postfit'].values()), 'eighteen controls per fit ' + entry['summary_path'])
    for role, panels in run['postfit'].items():
        for label, panel in panels.items():
            actual = info(panel['path'])
            check(actual['sha256'] == panel['sha256'], 'control digest ' + panel['path'])
            bound_artifact(panel['path'], actual, 'control', current=False)
            expected = dict(fidelity=panel['fidelity']['metrics'], by_length=panel['fidelity']['by_length'], by_facet=panel['fidelity']['by_facet'], numerical=panel['numerical']['metrics'])
            check(published['controls'][role][label] == expected, 'published exact control ' + panel['path'])
    selection.append(dict(arm=run['arm'], dimension=run['dimension'], seed=run['seed'], selected_epoch=report['selected_epoch'], optimizer_steps=report['optimizer_steps']))
    del report
for flag in ('qualified', 'admitted', 'convergence_proven', 'fresh_holdout', 'lake_executed', 'formalized', 'roundtrip_ok', 'checkpoint_promoted', 'proof_authority', 'source_semantics_verified', 'production_checkpoint', 'optimizer_resumable', 'native_validation_executed'):
    check(m[flag] is False and r[flag] is False, 'authority ' + flag)
resource = read(R / 'training-r1/resources-final.json')
check(r['resources'] == resource, 'published exact resource receipt')
check(r['guardian_succeeded'] is (not resource.get('recovered_after_guardian_failure', False)) and r['resource_receipt_reconciled_after_guardian_failure'] is resource.get('recovered_after_guardian_failure', False), 'resource success honest')
record = resource['record']
check(resource['status'] == record['status'] == 'released' and record['artifacts_durable_asserted'] and not record['attempt_exceeded_reservation'], 'released retained resource claim')
check(record['cpu_slots'] == 1 and record['memory_mb'] == 4096 and record['storage_bytes'] == 3_000_000_000 and record['final_accounting']['limit_bytes'] == 140_000_000_000, 'resource limits')
check(r['workers'] == 1 and r['bridge_names'] == [] and r['legal_ir_evaluate_provers'] is False and r['metric_disk_cache_used'] is False and r['downloads_performed'] is False and r['encoder_executed'] is False, 'exact diagnostic scope')

# The cleanup failure remains an observed failure; reconciliation only recovers
# verifiable accounting for already completed child work.
guardian = read(R / 'guardian-exit.json')
child = read(R / 'training-r1/child-exit.json')
reconciliation = read(R / 'resource-reconciliation.json')
check(guardian['returncode'] == 1 and child['returncode'] == 0 and child['leader_reaped'], 'actual guardian and child exits retained')
check(r['guardian_succeeded'] is False and r['resource_receipt_reconciled_after_guardian_failure'] is True,
    'published failed guardian and reconciled accounting')
check(resource['reconciliation_receipt'] == dict(path=str(R / 'resource-reconciliation.json'),
    sha256=artifacts[str(R / 'resource-reconciliation.json')]['sha256']), 'final resource receipt binds reconciliation')
check(reconciliation['complete'] and reconciliation['guardian_returncode'] == 1
    and reconciliation['training_child_returncode'] == 0 and not reconciliation['guardian_success_claimed'], 'reconciliation process status')
check(reconciliation['release_record'] == record and reconciliation['observed_completed_attempt_bytes'] == record['final_attempt_bytes'],
    'reconciliation exact prior release accounting')
for flag in ('attempt_inode_verified','child_group_dead','owner_exited','scheduler_lease_absent','scheduler_config_now_matches_adopted'):
    check(reconciliation[flag] is True, 'reconciliation completed check ' + flag)
for flag in ('model_rerun','shared_state_mutated','foreign_claims_modified','scheduler_release_performed','scheduler_reset_performed'):
    check(reconciliation[flag] is False, 'reconciliation no new action ' + flag)
check(reconciliation['configuration_change_actor_unknown'] and reconciliation['failure_time_scheduler_configuration_not_captured']
    and reconciliation['scheduler_release_actor_unknown'], 'unknown cleanup history remains unknown')
check(info(R / 'guardian.log')['sha256'] == reconciliation['original_guardian_log_sha256'], 'original cleanup traceback hash')
for name in ('guardian-exit.json','guardian.log','resource-reconciliation.json','reconcile_completed_resources.py',
    'training-r1/child-exit.json','training-r1/resources-final.json'):
    path = R / name
    bound_artifact(str(path), info(path), 'retained cleanup provenance')
check(info(R / 'reconcile_completed_resources.py')['sha256'] == reconciliation['script_sha256'], 'exact reconciliation source')

# Preserve the eight completed training-only head probes and every saved
# checkpoint/update, including the separate failed review and test attempts.
D = P / 'workspace/test-logs/decoder-object-readout-20261003'
probe_summary = read(D / 'probe-r1/results/summary.json')
probe_audit = read(D / 'independent-audit.json')
probe_manifest = read(D / 'training-manifest.json')
probe_doc = read(D / 'probe-doc-review.json')
probe_outcomes = read(D / 'outcomes.json')
probe_guardian = read(D / 'guardian-exit.json')
probe_child = read(D / 'probe-r1/child-exit.json')
probe_resource = read(D / 'probe-r1/resources-final.json')
check(probe_summary['complete'] and len(probe_summary['runs']) == 8 and probe_summary['training_only']
    and probe_summary['sample_count'] == 180 and probe_summary['unique_clause_count'] == 113
    and probe_summary['source_paragraph_count'] == 48, 'eight complete training-only probes')
check(probe_summary['no_project_runtime_imported'] and not probe_summary['original_curriculum_replayed'],
    'probe scope separate from full decoder training')
check(probe_guardian['returncode'] == probe_child['returncode'] == 0 and probe_child['leader_reaped']
    and probe_resource['status'] == 'released', 'separate probe execution and finalization')
check(probe_audit['passed'] and probe_audit['finding_count'] == 0 and not probe_audit['findings']
    and not probe_audit['model_framework_imported'] and not probe_audit['optimizer_trajectory_replayed'], 'probe independent audit scope')
check(probe_doc['passed'] and probe_doc['partial_document_review'] and not probe_doc['full_decoder_results_read'],
    'historical probe document review scope retained')
check(probe_outcomes['complete'] and probe_outcomes['passed'] and probe_outcomes['all_endpoints_retained']
    and not probe_outcomes['validation_access'] and not probe_outcomes['best_checkpoint_selected'], 'complete probe endpoint analysis')
for name in ('probe-r1/results/summary.json','independent-audit.json','training-manifest.json','probe-doc-review.json',
    'outcomes.json','guardian-exit.json','probe-r1/child-exit.json','probe-r1/resources-final.json','tensor-crosscheck.json'):
    path = D / name
    bound_artifact(str(path), info(path), 'archived direct-head probe provenance')
for relative, digest in probe_summary['source_dependencies'].items():
    check(seen.get('training-head-probes/experiment-source/' + relative, {}).get('sha256') == digest,
        'exact executed standalone probe producer ' + relative)
check(probe_summary['manifest_sha256'] == info(D / 'training-manifest.json')['sha256']
    and probe_summary['plan_sha256'] == info(D / 'training-plan.json')['sha256'], 'probe sealed recipe binding')
probe_ids = set()
probe_checkpoints = 0
for entry in probe_summary['runs']:
    identity = (entry['seed'],entry['mode'],entry['learning_rate'])
    check(identity not in probe_ids, 'unique direct-head probe')
    probe_ids.add(identity)
    reference = entry['report']
    report = read(reference['path'])
    expected = {key:reference[key] for key in ('bytes','sha256')}
    check(artifacts[reference['path']] == expected, 'probe full report current digest ' + entry['name'])
    bound_artifact(reference['path'], expected, 'archived full probe report', current=False)
    check(report['complete'] and report['mode'] == entry['mode'] and report['learning_rate'] == entry['learning_rate']
        and report['completed_updates'] == report['requested_updates'] == 1000
        and report['stopped_reason'] == 'updates_completed', 'probe completion and identity ' + entry['name'])
    steps = [point['step'] for point in report['checkpoints']]
    check(steps == [0,1,10,25,100,340,1000] and steps == report['requested_checkpoints'], 'all seven checkpoints ' + entry['name'])
    probe_checkpoints += len(steps)
    check(len(report['updates']) == 1000 and [update['step'] for update in report['updates']] == list(range(1,1001)),
        'all committed direct-head updates ' + entry['name'])
    check(report['training_occurrences'] == 180 and report['training_unique_clauses'] == 113
        and report['row_presentations'] == 180000 and report['scalar_target_presentations'] == 180000*len(report['fields']),
        'probe full-batch presentation accounting ' + entry['name'])
    check(report['vocabulary_size'] == 32 and report['field_coefficient'] == .0625 and report['dimension'] == 8,
        'probe full-vocabulary head geometry ' + entry['name'])
    for point in report['checkpoints']:
        check(set(point['fields']) == set(report['fields']) and bool(point['parameters'])
            and all(len(field['logits']) == 180 and all(len(row) == 32 for row in field['logits'])
                for field in point['fields'].values()), 'all checkpoint parameters and full logits ' + entry['name'] + ':' + str(point['step']))
    check(report['final_parameters'] == report['checkpoints'][-1]['parameters']
        and report['final_parameters_sha256'] == report['checkpoints'][-1]['parameters_sha256'], 'probe final state retained')
    check(entry['object_correct'] == report['checkpoints'][-1]['fields']['object']['correct']
        and entry['object_cross_entropy'] == report['checkpoints'][-1]['fields']['object']['cross_entropy'], 'probe summary endpoint exact')
    for flag in ('validation_access','formula_decoder_used','generated_formula_metrics_computed','qualified','admitted',
        'lake_executed','production_checkpoint','optimizer_resumable','convergence_proven'):
        check(report[flag] is False, 'probe authority ' + entry['name'] + ':' + flag)
    del report
check(probe_ids == {(seed,mode,rate) for seed in (1729,2718) for mode in ('shared_non_action','isolated_object')
    for rate in (.001,.01)} and probe_checkpoints == 56, 'exact direct-head factorial and checkpoint inventory')
check(sum(bool(re.match(r'^training-head-probes/probe-r1/results/[^/]+/probe\.json$', name)) for name in seen) == 8,
    'eight archived full probe reports')
for label, review in [('probe audit',probe_audit),('probe document',probe_doc),('probe outcomes',probe_outcomes)]:
    for path, expected in review['artifacts'].items():
        bound_artifact(path, expected, label)
for path, digest in probe_manifest['inputs'].items():
    expected = info(path)
    check(expected['sha256'] == digest, 'probe fixed input digest ' + path)
    bound_artifact(path, expected, 'probe sealed input', current=False)
probe_tests = read(D / 'tests-frozen.json')
probe_counts = dict(tests=0, failures=0, errors=0, skipped=0)
for suite in ET.parse(D / 'tests-frozen.xml').getroot().iter('testsuite'):
    for key in probe_counts:probe_counts[key] += int(suite.get(key, 0))
check(probe_tests['returncode'] == 0 and probe_tests['standalone'] and not probe_tests['project_package_imported']
    and probe_counts == dict(tests=72, failures=0, errors=0, skipped=0), 'independent probe frozen tests retained')
check(probe_tests['tensor_check_sha256'] == info(D / 'tensor-crosscheck.json')['sha256']
    and probe_tests['tensor_check_script_sha256'] == info(D / 'verify_exported_feature_tensors.py')['sha256'],
    'independent exact tensor arithmetic cross-check retained')
for name in ('tests-frozen.json','tests-frozen.xml','tests-frozen.log','verify_exported_feature_tensors.py'):
    path = D / name
    bound_artifact(str(path), info(path), 'probe frozen test and arithmetic receipts')
failed_probe_files = ('attempt1-analyze_probe_outcomes.py','analyze-probe-outcomes-r1.log','analyze-probe-outcomes-r2.log',
    'audit-attempt1-error.log','audit-attempt1-failure.json','audit-revision.json',
    'head-lr-tests-attempt1.log','head-lr-tests-attempt2.log','head-lr-tests-attempt3.log',
    'probe-tests-attempt1.log','probe-tests-attempt2.log','probe-doc-review-attempt1.log','probe-doc-review-attempt2.log',
    'probe-doc-review-revisions/attempt1.json','probe-doc-review-revisions/attempt1.log','probe-doc-review-revisions/attempt1.py')
for name in failed_probe_files:
    path = D / name
    bound_artifact(str(path), info(path), 'retained probe failed attempt/correction')
failed_doc = read(D / 'probe-doc-review-revisions/attempt1.json')
revision = read(D / 'audit-revision.json')
check(failed_doc['passed'] is False and bool(failed_doc['findings']), 'failed document review not relabeled passed')
check(revision['all_numerical_functions_byte_identical'] and revision['all_tolerances_byte_identical']
    and revision['model_rerun'] is False and revision['training_artifacts_modified'] is False,
    'auditor correction retains numerical logic and artifacts')
# Original R2 is a Git-authenticated dependency, not copied as an additional
# current model lineage or relabeled as a fresh run.
check(any(dep['git_commit'] == base and dep['manifest']['path'] ==
    'docs/implementation/reports/evidence/decoder-generated-field-training-r2-20261003/manifest.json'
    for dep in deps.values()), 'immediate published predecessor dependency')
check(not any(name.startswith('failed-prior/') for name in seen), 'old failed study remains referenced through prior publication')

result = dict(schema='source-head-learning-rate-final-packaging-review/v1', passed=not findings, complete=True,
    checks=checks, findings=findings, finding_count=len(findings), artifacts=artifacts, archive=m['archive'],
    archive_members=len(seen), current_producers=len(m['validated_producer_source_sha256']),
    publication_overrides=len(m['publication_producer_overrides']), protected_checkpoint_bundled=False,
    script_sha256=info(Path(__file__))['sha256'], selection=selection, tests=scoped,
    independent_audit_checks=audit['checks'], direct_head_probe_runs=8, direct_head_probe_checkpoints=probe_checkpoints,
    guardian_succeeded=False, resource_receipt_reconciled_after_guardian_failure=True,
    scope='Read-only chunk/member digests, exact source/docs, all twelve fits/36 states/216 panels, eight probes/56 checkpoints and failed-review history. Git-authenticated predecessor references. No model execution, archive mutation or publication.',
    training_executed=False, models_executed=False, publication_performed=False, admitted=False, qualified=False)
output = R / 'packaging-review.json'
assert not output.exists(), 'preserve existing packaging reviews before another run'
output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({key:value for key,value in result.items() if key not in ('artifacts','selection')}))
raise SystemExit(bool(findings))

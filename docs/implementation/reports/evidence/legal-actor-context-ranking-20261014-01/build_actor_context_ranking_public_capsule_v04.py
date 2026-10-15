"""Prepare a public source/evidence manifest after actual qualified completion.

This program writes one exclusive JSON manifest.  It never copies files,
modifies Git, publishes, imports resource/model code, parses trained checkpoints,
or follows a result inventory or an artifact map into data/private payloads.
An independent source gate and actual postfreeze result review are mandatory.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat


ROOT = Path(__file__).resolve().parent
SELF = ROOT / 'build_actor_context_ranking_public_capsule_v04.py'
ALLOWLIST = ROOT / 'public-source-allowlist-v04.json'
ALLOWLIST_PIN = (49051, 'ec1a3cfe853783d893bd8369f908efc91e6bb10776a7b38e90eaccb4277270a4')
INPUTS = ROOT / 'public-source-capsule-inputs-v04.json'
OUTPUT = ROOT / 'public-source-capsule-v04.json'
PREFIX = 'docs/implementation/reports/evidence/legal-actor-context-ranking-20261014-01/'
GUIDE = 'docs/autoencoders/actor_context_ranking_20261014.md'
BASE = '54aae1d13faea237eddde301754db85afd1e127a'
ROLE_FILES = {
    'plan': {'actor-context-ranking-hinge-plan-v01.json'},
    'training_review': {'actor-context-ranking-hinge-training-review-v01.json'},
    'terminal_resource': {'actor-context-ranking-hinge-terminal-resource-audit-v01.json'},
    'runtime': {'actor-context-ranking-hinge-runtime-review-v01.json'},
    'freeze': {'actor-context-ranking-output-freeze-v01.json'},
    'analysis': {'actor-context-ranking-result-analysis-v01.json'},
    'recount': {'actor-context-ranking-independent-recount-v01.json'},
    'result_review': {'actor-context-ranking-result-independent-review-v01.json',
                      'result-independent-review-v01.json'},
    'public_summary': {'public-result-summary-v01.json'},
}
FORBIDDEN_BODY_NAMES = ('checkpoint', 'weights', 'head-capture', 'logits', 'reference',
                        'gold', 'stderr', 'stdout', 'ledger', 'scheduler-state')


def require(value, message):
    if not value:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate public metadata key')
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError('Nonfinite public metadata value')


def checked(path, expected=None):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink()
            and path.resolve(strict=True) == path, 'Physical regular public file required')
    digest = hashlib.sha256()
    length = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
            length += len(block)
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), 'Public file changed during raw hash')
    descriptor = dict(path=str(path), bytes=length, sha256=digest.hexdigest())
    if expected is not None:
        require(type(expected) is dict and set(expected) == {'path', 'bytes', 'sha256'}
                and type(expected['path']) is str and type(expected['bytes']) is int
                and type(expected['sha256']) is str and descriptor == expected,
                'Exact public descriptor required')
    return descriptor


def metadata(descriptor, schema):
    checked(descriptor['path'], descriptor)
    require(descriptor['bytes'] <= 4 * 1024 * 1024, 'Bounded metadata record required')
    data = Path(descriptor['path']).read_bytes()
    require(len(data) == descriptor['bytes'] and hashlib.sha256(data).hexdigest() == descriptor['sha256'],
            'Metadata bytes changed')
    value = json.loads(data, object_pairs_hook=unique, parse_constant=reject_constant)
    require(type(value) is dict and value.get('schema') == schema, 'Exact public metadata schema required')
    return value


def clean(value):
    require(value.get('passed') is True and value.get('findings') == [], 'Clean technical review required')


def map_binds(artifact_map, descriptor):
    if type(artifact_map) is not dict:
        return False
    row = artifact_map.get(descriptor['path'])
    return row == descriptor or row == {k: descriptor[k] for k in ('bytes', 'sha256')}


def safe_target(target):
    path = PurePosixPath(target)
    require(not path.is_absolute() and '..' not in path.parts and '.' not in path.parts
            and str(path) == target and target.startswith(PREFIX), 'Closed public evidence target required')


def actual_completion(evidence):
    """Read only approved metadata; never open the62 captured model outputs."""
    require(type(evidence) is dict and set(evidence) == set(ROLE_FILES), 'Closed actual evidence roles required')
    for role, descriptor in evidence.items():
        path = Path(descriptor['path'])
        require(path.parent == ROOT and path.name in ROLE_FILES[role]
                and not any(term in path.name.lower() for term in FORBIDDEN_BODY_NAMES),
                'Fixed top-level public completion record required')
        checked(path, descriptor)
    runtime = metadata(evidence['runtime'], 'actor-context-ranking-runtime-independent-review/v1')
    freeze = metadata(evidence['freeze'], 'actor-context-ranking-output-freeze/v1')
    terminal = metadata(evidence['terminal_resource'], 'actor-context-ranking-terminal-resource-audit/v1')
    training = metadata(evidence['training_review'], 'actor-context-ranking-concrete-training-independent-review/v1')
    review = metadata(evidence['result_review'], 'actor-context-ranking-result-independent-review/v1')
    for value in (runtime, terminal, training, review):
        clean(value)
    counts = dict(actual_returned_optimizer_updates=32, actual_model_forwards=1312,
                  actual_inference_source_forwards=1280, actual_training_source_occurrences=384,
                  actual_total_source_occurrences=1664, initial_source_rows=632, final_source_rows=632,
                  new_parent_control_forwards=0, output_file_count=62, successful_output_file_count=62)
    require(all(type(runtime.get(k)) is int and runtime[k] == v for k, v in counts.items()),
            'Actual fixed32-update62-output runtime required')
    require(freeze.get('all_outputs_frozen') is True
            and freeze.get('authorizes_authored_eval_scoring') is True
            and freeze.get('statutory_reference_scoring_authorized') is False
            and type(freeze.get('actual_returned_optimizer_updates')) is int
            and freeze['actual_returned_optimizer_updates'] == 32
            and freeze.get('runtime_review') == evidence['runtime']
            and freeze.get('plan') == evidence['plan']
            and runtime.get('plan') == evidence['plan']
            and runtime.get('training_review') == evidence['training_review']
            and runtime.get('resource_review') == evidence['terminal_resource'],
            'Actual runtime/freezer/plan/source custody joins required')
    require(type(runtime.get('outputs')) is dict and len(runtime['outputs']) == 62
            and freeze.get('results') == runtime['outputs'], 'Exact full62 frozen inventory join required')
    require(type(review.get('scientific_success')) is bool and review.get('default_promotion') is False,
            'Actual scientific disposition required without automatic promotion')
    require(runtime.get('default_promotion') is False and freeze.get('default_promotion') is False,
            'Runtime and freeze must retain no automatic promotion')
    require(all(map_binds(review.get('artifacts'), d) for role, d in evidence.items()
                if role not in ('result_review', 'public_summary')),
            'Independent actual result-review artifact closure required')
    # Analysis/recount are approved public artifacts, hashed opaquely above.
    # Their row values, gold/references, captures and checkpoint are not parsed.
    return review['scientific_success']


def write_manifest(result):
    data = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    descriptor = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o444)
    try:
        with os.fdopen(descriptor, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    result_pin = checked(OUTPUT)
    require((result_pin['bytes'], result_pin['sha256']) == (len(data), hashlib.sha256(data).hexdigest()),
            'Capsule manifest raw readback required')
    print(json.dumps(result_pin, sort_keys=True))


def main():
    require(Path(__file__).resolve() == SELF and not os.path.lexists(OUTPUT), 'Exclusive owned builder output required')
    allowlist_pin = checked(ALLOWLIST)
    require((allowlist_pin['bytes'], allowlist_pin['sha256']) == ALLOWLIST_PIN, 'Exact public source allowlist required')
    allowlist = metadata(allowlist_pin, 'actor-context-ranking-public-source-allowlist/v4')
    input_pin = checked(INPUTS)
    inputs = metadata(input_pin, 'actor-context-ranking-public-source-capsule-inputs/v4')
    require(set(inputs) == {'schema', 'source_review', 'report', 'evidence'}, 'Closed actual capsule inputs required')
    source_review_pin = inputs['source_review']
    source_review_path = Path(source_review_pin['path'])
    require(source_review_path == ROOT / 'public-capsule-builder-source-independent-review-v04.json',
            'Fixed actual builder source-review path required')
    source_review = metadata(source_review_pin, 'actor-context-ranking-public-capsule-builder-source-independent-review/v1')
    clean(source_review)
    self_pin = checked(SELF)
    require(source_review.get('producer') == self_pin and source_review.get('allowlist') == allowlist_pin,
            'Actual independent builder-source qualification required')
    require(allowlist.get('published_draft_baseline') == BASE and allowlist.get('evidence_prefix') == PREFIX
            and type(allowlist.get('files')) is dict and len(allowlist['files']) == allowlist.get('file_count') == 84,
            'Closed84-file modern source roster required')
    selected = {}
    artifacts = {str(SELF): self_pin, str(ALLOWLIST): allowlist_pin,
                 str(INPUTS): input_pin, source_review_pin['path']: source_review_pin}
    for target, row in allowlist['files'].items():
        safe_target(target)
        require(type(row) is dict and set(row) == {'source', 'role', 'status'}, 'Closed public selection row required')
        descriptor = checked(row['source']['path'], row['source'])
        require(Path(descriptor['path']).suffix in ('.py', '.json'), 'Public source/metadata extensions only')
        require(map_binds(source_review.get('artifacts'), descriptor), 'Source-review allowlist closure required')
        selected[target] = row
        artifacts[descriptor['path']] = descriptor
    require(sum(v['source']['bytes'] for v in selected.values()) == allowlist.get('source_bytes'), 'Source byte accounting changed')
    scientific_success = actual_completion(inputs['evidence'])
    report = inputs['report']
    report_path = Path(report['path'])
    require(report_path.parent == ROOT and report_path.name in ('DRAFT_REPORT_v04.md', 'COMPLETED_REPORT_v01.md'),
            'New completed-phase public report required')
    checked(report_path, report)
    require(report['bytes'] <= 128 * 1024, 'Bounded completed report required')
    for descriptor in (self_pin, allowlist_pin, input_pin, source_review_pin):
        target = PREFIX + Path(descriptor['path']).name
        require(target not in selected, 'Unique capsule self-custody targets required')
        selected[target] = dict(source=descriptor, role='capsule_source_and_concrete_inputs', status='Manifest-only; no copying or publication.')
    for role, descriptor in inputs['evidence'].items():
        target = PREFIX + Path(descriptor['path']).name
        require(target not in selected, 'Unique actual evidence target required')
        selected[target] = dict(source=descriptor, role=role, status='Actual postfreeze public evidence under independent result review.')
        artifacts[descriptor['path']] = descriptor
    selected[GUIDE] = dict(source=report, role='completed_phase_guide', status='Prose still requires concrete packet review.')
    selected[PREFIX + report_path.name] = dict(source=report, role='completed_phase_report_copy', status='Same report bytes; prose still requires concrete packet review.')
    artifacts[report['path']] = report
    for descriptor in artifacts.values():
        checked(descriptor['path'], descriptor)
    write_manifest(dict(schema='actor-context-ranking-public-source-capsule/v4',
        source_qualification=source_review_pin, inputs=input_pin, published_draft_baseline=BASE,
        selected_files=selected, selected_file_count=len(selected),
        selected_total_bytes=sum(v['source']['bytes'] for v in selected.values()),
        actual_completed_updates=32, actual_frozen_result_count=62,
        scientific_success=scientific_success, default_promotion=False,
        report_prose_independently_reviewed_by_builder=False, concrete_packet_review_required=True,
        failed_V01_smoke_preserved=True, successful_V02_smoke_separately_bound=True,
        package_initializers_custody_only=3, native_package_init_equivalence_claimed=False,
        raw_model_capture_checkpoint_or_reference_source_files_selected=False,
        private_payloads_selected=False, recursive_artifact_materialization=False,
        source_copies_performed=0, Git_operations=0, network_operations=0,
        publication_performed=False, portable_execution_or_numerical_reload_qualified=False,
        artifacts=artifacts))


if __name__ == '__main__':
    main()

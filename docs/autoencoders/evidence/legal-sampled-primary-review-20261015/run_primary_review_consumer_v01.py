"""Consume retained primary associations in a fresh owned-validation child.

This driver never invokes the retained producer or replay driver's main. It
reads only the independently accepted producer generation, reconstructs the
original public replay arguments, and prepares a fresh unsigned review subject.
The native parent owns admission, supervision, durability and resource release.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import types


PHASE = Path('/home/barberb/lift_coding/artifacts/legal-sampled-primary-review-20261015-01')
GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
GUARD_SHA256 = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
PRODUCER = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs/legal-sampled-primary-association-20261015-associate01')
PRODUCER_RECEIPT_SHA256 = 'bdfd190b215cafac03f99d19a7b592d3c2b616376531802fec1336c2d3d816fc'
REPLAY_RECEIPT_SHA256 = 'bffb49f77b9e551fd7901b3c0baf3f51956549cff6d176b987c8263bf01b6b5e'
REPLAY_INDEX_SHA256 = '9a462929515a1ce4735e3d1bd8870cd2f239a342e3b8cca5852ab96165c18e1a'
EXPECTED_INDEX_SHA256 = '82b8099255a93c5a22135229d9bcab8a7a8dd25f09074ca744155734a1d931e1'
EXPECTED_CANDIDATE_SHA256 = '46986513582973996e4d69ecf0669ed7331e6cca07ca793f3b1c1ea2dcdec8f1'
MAX_METADATA = 1024 * 1024
MAX_SOURCE = 4 * 1024 * 1024
MAX_RETAINED_FILE = 30_000_000
MAX_RETAINED_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
CHECKS = [
    'retained_producer_original_inventory_and_native_closeout',
    'full_original_primary_index_baseline',
    'fol_fresh_retained_association_definition_review_subject',
    'tdfol_fresh_retained_association_definition_review_subject',
    'retained_producer_immutable_and_source_output_closing_guards',
]
CONFIG_FIELDS = {
    'schema', 'accepted_producer_descriptor', 'primary_candidate',
    'reconstruction_report', 'expected_reconstruction_sha256',
    'expected_reconstruction_full_canonical_sha256', 'index_baseline',
    'expected_index_sha256',
}
DESCRIPTOR_FIELDS = {
    'schema', 'producer_attempt_directory', 'producer_request', 'producer_receipt',
    'replay_receipt', 'replay_file_index', 'producer_execution', 'producer_result',
    'producer_durability', 'captured_parent_stdout', 'captured_parent_stderr',
    'expected_replay_file_count', 'expected_replay_bytes',
    'expected_association_file_count', 'expected_association_bytes',
}
PIN_FIELDS = {'path', 'bytes', 'sha256'}
EXPECTED_UNRESOLVED = [
    'official_source_primary_package_equivalence', 'governing_version_and_applicability',
    'independent_legal_interpretation', 'independent_formal_interpretation',
    'authenticated_exposure',
]


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def pin(path, raw):
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def load_guard():
    need(not sys.flags.optimize and sys.dont_write_bytecode,
         'nonoptimized no-bytecode Python required')
    for parent in (GUARD.parent, *GUARD.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), 'unaliased source guard parents required')
    with os.fdopen(os.open(GUARD, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == 28529,
             'exact qualified source guard required')
        raw = stream.read(MAX_SOURCE + 1)
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    need(identity(before) == identity(after) == identity(GUARD.lstat())
         and sha(raw) == GUARD_SHA256, 'qualified source guard changed')
    name = '_primary_review_consumer_guard_v01'
    need(name not in sys.modules, 'fresh standard-library guard module required')
    module = types.ModuleType(name)
    module.__file__ = str(GUARD)
    sys.modules[name] = module
    exec(compile(raw, str(GUARD), 'exec', dont_inherit=True, optimize=0), module.__dict__)
    return module


def checked_descriptor(row, *, maximum=MAX_SOURCE, allow_empty=False, absolute=True):
    need(type(row) is dict and set(row) == PIN_FIELDS, 'closed original file descriptor required')
    spelling, size, digest = row['path'], row['bytes'], row['sha256']
    need(type(spelling) is str and spelling and '\x00' not in spelling
         and type(size) is int and (0 if allow_empty else 1) <= size <= maximum
         and type(digest) is str and re.fullmatch(r'[0-9a-f]{64}', digest),
         'bounded exact original file descriptor required')
    path = Path(spelling)
    need(path.is_absolute() if absolute else path.name == spelling,
         'exact absolute or single-component relative file required')
    return path


def descriptor_bytes(g, row, *, maximum=MAX_SOURCE, allow_empty=False, native_pins=None):
    path = checked_descriptor(row, maximum=maximum, allow_empty=allow_empty)
    if native_pins is not None:
        need(native_pins.get(str(path)) == row['sha256'], 'metadata native pin differs')
    raw = g.snapshot(path, maximum, allow_empty=allow_empty)
    need(pin(path, raw) == row, 'independently accepted file descriptor differs')
    return raw


def scan_inventory(g, root, expected_names):
    """Hash a complete, bounded, immutable producer tree without following links."""
    g.physical_parents(root / '__producer_identity_only__')
    files, directories, aggregate = {}, {}, 0
    queue = [root]
    for directory in queue:
        info = directory.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
             and stat.S_IMODE(info.st_mode) & 0o077 == 0 and len(queue) <= 32,
             'bounded private producer directories required')
        directories[str(directory.relative_to(root))] = list(g.identity(info))
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries)
        need(len(names) <= 128, 'producer directory population exceeds bound')
        for name in names:
            path = directory / name
            before = path.lstat()
            if stat.S_ISDIR(before.st_mode):
                queue.append(path)
                need(len(queue) <= 32, 'producer directory bound exceeded')
                continue
            relative = str(path.relative_to(root))
            need(relative in expected_names and relative not in files and len(files) < 128
                 and stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                 'producer contains an undeclared or nonregular file')
            raw = g.snapshot(path, MAX_RETAINED_FILE, allow_empty=True)
            need(g.identity(before) == g.identity(path.lstat()), 'producer file identity changed')
            aggregate += len(raw)
            need(aggregate <= MAX_RETAINED_BYTES, 'complete producer byte bound exceeded')
            files[relative] = {'bytes': len(raw), 'sha256': sha(raw),
                               'physical_identity': list(g.identity(before))}
        need(g.identity(info) == g.identity(directory.lstat()), 'producer directory changed during traversal')
    need(set(files) == expected_names, 'complete producer file inventory differs')
    return {'files': files, 'directories': directories, 'bytes': aggregate,
            'file_count': len(files), 'directory_count': len(directories)}


class OutputFiles:
    def __init__(self, g, exports, directories):
        self.g, self.root, self.directories = g, exports, directories
        self.files, self.total = {}, 0
        g.directory_guard(directories)
        need(not list(exports.iterdir()), 'fresh empty native export directory required')

    def json(self, name, value):
        need(type(name) is str and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,100}', name)
             and name not in self.files and len(self.files) < 24, 'bounded unique output filename required')
        raw = wire(value) + b'\n'
        need(0 < len(raw) <= 8 * 1024 * 1024 and self.total + len(raw) <= MAX_OUTPUT_BYTES,
             'complete native review output exceeds bound')
        self.g.directory_guard(self.directories)
        path = self.root / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        need(self.g.snapshot(path, 8 * 1024 * 1024) == raw, 'new review output readback differs')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        row = pin(path, raw)
        self.files[name] = row
        self.total += len(raw)
        return row

    def verify(self):
        self.g.directory_guard(self.directories)
        need({entry.name for entry in self.root.iterdir()} == set(self.files),
             'new review export population changed')
        for row in self.files.values():
            need(pin(Path(row['path']), self.g.snapshot(Path(row['path']), 8 * 1024 * 1024)) == row,
                 'new review output changed')


def accept_producer(g, descriptor):
    """Authenticate the retained generation, native closeout and complete inventories."""
    need(type(descriptor) is dict and set(descriptor) == DESCRIPTOR_FIELDS
         and descriptor['schema'] == 'retained-sampled-primary-association-producer/v1'
         and descriptor['producer_attempt_directory'] == str(PRODUCER)
         and descriptor['expected_replay_file_count'] == 64
         and descriptor['expected_replay_bytes'] == 10630440
         and descriptor['expected_association_file_count'] == 7
         and descriptor['expected_association_bytes'] == 336630,
         'closed independently accepted producer generation required')
    values, raws = {}, {}
    fields = DESCRIPTOR_FIELDS - {'schema', 'producer_attempt_directory', 'expected_replay_file_count',
                                  'expected_replay_bytes', 'expected_association_file_count', 'expected_association_bytes'}
    for field in sorted(fields):
        raws[field] = descriptor_bytes(g, descriptor[field], maximum=MAX_METADATA,
                                      allow_empty=field == 'captured_parent_stderr')
        if field != 'captured_parent_stderr':
            values[field] = g.decode(raws[field])
    need(raws['captured_parent_stderr'] == b'', 'accepted producer parent stderr is not empty')
    need(descriptor['producer_receipt']['sha256'] == PRODUCER_RECEIPT_SHA256
         and descriptor['replay_receipt']['sha256'] == REPLAY_RECEIPT_SHA256
         and descriptor['replay_file_index']['sha256'] == REPLAY_INDEX_SHA256,
         'independently accepted producer receipt hashes differ')
    for field, relative in {
        'producer_receipt': 'logs/sampled-primary-associate-receipt.json',
        'replay_receipt': 'exports/replay-receipt.json', 'replay_file_index': 'exports/file-index.json',
        'producer_execution': 'logs/execution.json', 'producer_result': 'logs/result.json',
        'producer_durability': 'logs/validation-durability.json',
    }.items():
        need(descriptor[field]['path'] == str(PRODUCER / relative), 'accepted producer metadata location differs')
    request, receipt, replay, index, execution, result, durability, parent = [values[key] for key in (
        'producer_request', 'producer_receipt', 'replay_receipt', 'replay_file_index',
        'producer_execution', 'producer_result', 'producer_durability', 'captured_parent_stdout')]
    request_sha = descriptor['producer_request']['sha256']
    need(request['schema'] == 'owned-validation-request/v1'
         and request['attempt_directory'] == str(PRODUCER)
         and request['outputs'] == {key: str(PRODUCER / key) for key in g.OUTPUT_NAMES}
         and request['declared_external_writable_paths'] == []
         and request['process_scope'] == 'isolated_process_group', 'original native request scope differs')
    need(receipt['schema'] == 'legal-sampled-primary-actual-associate/v1'
         and receipt['status'] == 'pass' and receipt['all_checks_complete'] is True
         and receipt['request'] == descriptor['producer_request']
         and receipt['selected_checks'] == receipt['completed_checks'] == request['selected_checks']
         == execution['executed_checks'] == result['executed_checks'], 'retained native check identities differ')
    need(all(row['request_sha256'] == request_sha for row in (execution, result, durability))
         and execution['completed'] is result['completed'] is True
         and execution['returncode'] == result['returncode'] == 0,
         'retained native execution did not complete successfully')
    reservation, stored, lease = parent['reservation'], parent['reservation']['record'], parent['reservation']['resource_lease']
    need(parent['result'] == str(PRODUCER / 'logs/result.json')
         and reservation['status'] == stored['status'] == 'released'
         and reservation['cleanup_error'] is None and stored['artifacts_durable_asserted'] is True
         and stored['attempt_exceeded_reservation'] is False
         and stored['validation_request_sha256'] == request_sha
         and stored['attempt_directory']['path'] == str(PRODUCER)
         and stored['outputs'] == request['outputs']
         and lease['released'] is True and lease['lease_id'] == stored['native_lease_id']
         and stored['last_usage']['group_rss']['available'] is True
         and stored['last_usage']['group_rss']['live_processes'] == 0
         and stored['last_usage']['group_rss']['rss_bytes'] == 0,
         'retained captured parent lacks complete native closeout')
    need(durability['schema'] == 'owned-validation-durability/v1'
         and durability['scope'] == 'owned_files_fsynced_after_recorded_group_observed_stopped'
         and durability['reservation_id'] == stored['reservation_id'] == reservation['reservation_id']
         and durability['result_path'] == 'logs/result.json'
         and durability['result_sha256'] == descriptor['producer_result']['sha256'],
         'retained native durability binding differs')
    rows = durability['files']
    need(type(rows) is list and 0 < len(rows) <= 127, 'bounded complete native producer seal required')
    sealed = {}
    for row in rows:
        need(type(row) is dict and set(row) == {'path', 'bytes', 'sha256', 'device', 'inode'}
             and type(row['path']) is str and not Path(row['path']).is_absolute()
             and '..' not in Path(row['path']).parts and row['path'] not in sealed,
             'closed unique native producer seal entry required')
        sealed[row['path']] = row
    need('logs/validation-durability.json' not in sealed, 'native durability cannot seal itself')
    expected_names = set(sealed) | {'logs/validation-durability.json'}
    before = scan_inventory(g, PRODUCER, expected_names)
    for name, row in sealed.items():
        observed = before['files'][name]
        need(observed['bytes'] == row['bytes'] and observed['sha256'] == row['sha256']
             and observed['physical_identity'][0:2] == [row['device'], row['inode']],
             'retained native-sealed original file differs')
    need(before['files']['logs/validation-durability.json']['sha256']
         == descriptor['producer_durability']['sha256'], 'retained native seal changed')
    g.code_guard(request['source_sha256'])
    need(index['schema'] == 'retained-definition-correspondence-file-index/v1'
         and index['self_file'] == 'file-index.json' and len(index['files']) == 63,
         'complete retained 64-file source replay index required')
    by_name = {}
    for row in index['files']:
        checked_descriptor(row, maximum=MAX_RETAINED_FILE, absolute=False)
        need(row['path'] not in by_name, 'duplicate retained replay file descriptor')
        by_name[row['path']] = row
        observed = before['files'].get('exports/' + row['path'])
        need(observed is not None and (observed['bytes'], observed['sha256']) == (row['bytes'], row['sha256']),
             'retained replay index differs from native-sealed file')
    exports = set(by_name) | {'file-index.json'}
    need(type(index['closed_export_names']) is list and len(index['closed_export_names']) == 64
         and set(index['closed_export_names']) == exports
         and {key[len('exports/'):] for key in before['files'] if key.startswith('exports/')} == exports
         and sum(row['bytes'] for row in index['files']) == index['listed_bytes_excluding_self']
         and index['listed_bytes_excluding_self'] + descriptor['replay_file_index']['bytes'] == 10630440,
         'retained replay export population or aggregate differs')
    association_by_name = {}
    need(type(receipt['association_outputs']) is list and len(receipt['association_outputs']) == 7
         and receipt['association_output_bytes'] == 336630, 'complete seven-file association generation required')
    for row in receipt['association_outputs']:
        path = checked_descriptor(row, maximum=MAX_RETAINED_FILE)
        need(path.parent == PRODUCER / 'logs/association' and path.name not in association_by_name,
             'association output escaped retained generation')
        association_by_name[path.name] = row
        observed = before['files'].get(str(path.relative_to(PRODUCER)))
        need(observed is not None and (observed['bytes'], observed['sha256']) == (row['bytes'], row['sha256']),
             'association declaration differs from native-sealed original')
    need({key[len('logs/association/'):] for key in before['files'] if key.startswith('logs/association/')}
         == set(association_by_name)
         and sum(row['bytes'] for row in association_by_name.values()) == 336630,
         'retained association output population or aggregate differs')
    need(replay['all_checks_passed'] is True and replay['named_check_count'] == len(replay['named_checks']) == 17
         and replay['negative_controls_refused'] == 8 and replay['whole_source_subjects'] == 560
         and replay['actual_response_count'] == replay['actual_reviews'] == replay['assessments_created'] == 0
         and replay['training_mask'] == replay['evaluation_gold_mask'] == 0
         and all(value is False for value in replay['authority'].values())
         and receipt['training_mask'] == receipt['evaluation_gold_mask'] == receipt['actual_reviews'] == 0
         and all(value is False for value in receipt['authority'].values()),
         'retained original has unexpected response, authority or training state')
    need(receipt['retained_replay_receipt'] == descriptor['replay_receipt']
         and receipt['retained_replay_file_index'] == descriptor['replay_file_index'],
         'retained association and source replay references differ')
    return {'values': values, 'raws': raws, 'inventory': before, 'expected_names': expected_names,
            'replay_files': by_name, 'association_files': association_by_name,
            'old_source_pins': request['source_sha256'], 'descriptor': descriptor}


def retained_families(g, accepted):
    """Reconstruct exact old arguments; do not rerun a producer entry point."""
    replay = accepted['values']['replay_receipt']
    by_name, associations = accepted['replay_files'], accepted['association_files']
    def read(row):
        checked_descriptor(row, maximum=MAX_RETAINED_FILE, absolute=False)
        need(by_name.get(row['path']) == row, 'replay reference is outside accepted original inventory')
        return descriptor_bytes(g, {**row, 'path': str(PRODUCER / 'exports' / row['path'])},
                                maximum=MAX_RETAINED_FILE)
    def read_association(row):
        path = checked_descriptor(row, maximum=MAX_RETAINED_FILE)
        need(associations.get(path.name) == row, 'association reference is outside accepted original inventory')
        return descriptor_bytes(g, row, maximum=MAX_RETAINED_FILE)
    original = replay['original_inputs']
    bundle = g.decode(read(original['bundle']))
    raw_html = read(original['raw_html'])
    sampling_raw = read(original['sampling_report'])
    need(g.decode(read(original['actual_responses'])) == [], 'actual responses must remain empty')
    sampling_inputs = deepcopy(bundle['manifest']['input_binding'])
    need(set(sampling_inputs) == {'descriptor', 'expected_descriptor_sha256', 'expected_raw_sha256', 'expected_raw_bytes'},
         'retained omitted optional sampler argument population differs')
    sampling_inputs['expected_sampling_report_sha256'] = sha(wire(g.decode(sampling_raw)))
    summaries = accepted['values']['producer_receipt']['associations']
    need(type(summaries) is list and len(summaries) == 2, 'both retained family associations required')
    by_family = {row['family']: row for row in summaries}
    need(set(by_family) == {'fol', 'tdfol'} and len(by_family) == len(summaries),
         'distinct retained FOL and TDFOL associations required')
    result = {}
    need(type(replay['families']) is list and len(replay['families']) == 2,
         'both retained source replay families required')
    for summary in replay['families']:
        family = summary['family']
        need(family in by_family and family not in result, 'source replay family population differs')
        prior = by_family[family]
        need(summary['replay_index'] == prior['correspondence_replay_index'],
             'association and source family replay indices differ')
        idx = g.decode(read(summary['replay_index']))
        custody = g.decode(read(idx['original_inputs']))
        contexts = g.decode(read(idx['contexts']))
        need(idx['family'] == custody['family'] == family, 'retained family metadata identity differs')
        inputs = {key: read(row) for key, row in custody['inputs'].items()}
        binding, subject, link, manifest = [g.decode(read(idx[key])) for key in (
            'binding_result', 'subject', 'correspondence', 'manifest')]
        need(sha(wire(binding)) == idx['binding_full_canonical_sha256']
             and sha(wire(subject)) == idx['subject_full_canonical_sha256']
             and sha(wire(link)) == idx['correspondence_full_canonical_sha256']
             and sha(wire(manifest)) == idx['manifest_full_canonical_sha256']
             and manifest['manifest_sha256'] == idx['manifest_internal_sha256'],
             'retained family canonical commitments differ')
        need(inputs['raw_html'] == raw_html and inputs['sampling_report_raw'] == sampling_raw,
             'family original raw source or sampler transport differs')
        args = {
            'expected_binding_sha256': idx['binding_full_canonical_sha256'],
            'expected_subject_sha256': idx['subject_full_canonical_sha256'],
            'binding_replay_inputs': {
                'request_raw': inputs['request_raw'], 'bundle': bundle, 'responses': [], 'raw_html': raw_html,
                'expected_request_sha256': sha(inputs['request_raw']), 'expected_bundle_sha256': sha(wire(bundle)),
                'expected_response_sha256s': [], 'sampling_replay_inputs': deepcopy(sampling_inputs),
            },
            'candidate_inputs': inputs, 'expected_candidate_pin': custody['candidate_pin'],
            'context_inputs': [
                {'source_occurrence_cid': row['source_occurrence_cid'],
                 'packet_raw': read(row['packet']), 'dependency_requests': row['dependency_requests']}
                for row in contexts['contexts']
            ],
            'expected_context_population': contexts['expected_context_population'],
            'dependency_manifest': manifest, 'expected_manifest_sha256': idx['manifest_internal_sha256'],
            'required_dependency_ids': idx['required_dependency_ids'],
        }
        association_raw = read_association(prior['association'])
        association, mapping_raw = g.decode(association_raw), read_association(prior['mapping'])
        need(sha(wire(association)) == prior['association_sha256']
             and association['status'] == 'declared_primary_association_only'
             and not association['issues'], 'accepted complete healthy association differs')
        result[family] = {
            'association': association, 'link': link, 'binding': binding, 'previous_subject': subject,
            'old_manifest': manifest, 'expected_association_sha256': prior['association_sha256'],
            'association_raw_pin': prior['association'], 'mapping_raw_pin': prior['mapping'],
            'arguments': {
                'expected_correspondence_sha256': idx['correspondence_full_canonical_sha256'],
                'correspondence_replay_inputs': args, 'mapping_raw': mapping_raw,
                'expected_mapping_file_sha256': prior['mapping']['sha256'],
                'expected_index_sha256': EXPECTED_INDEX_SHA256,
            },
        }
    need(set(result) == {'fol', 'tdfol'}, 'complete retained two-family input population required')
    return result


def closure(manifest, graph_id):
    adjacency = {row['artifact_id']: [] for row in manifest['artifacts']}
    for row in manifest['edges']:
        need(row['dependent_id'] in adjacency, 'review dependency dependent is unavailable')
        adjacency[row['dependent_id']].append(row['dependency_id'])
    ordered, seen = [graph_id], {graph_id}
    for parent in ordered:
        for child in adjacency.get(parent, []):
            if child not in seen:
                seen.add(child)
                ordered.append(child)
                need(len(ordered) <= 20480, 'complete review closure exceeds bound')
    return ordered


def check_review(envelope, family):
    need(type(envelope) is dict and set(envelope) == {'schema', 'profile', 'preparation', 'subject', 'dependency_manifest'},
         'complete review envelope required')
    prep, subject, manifest = envelope['preparation'], envelope['subject'], envelope['dependency_manifest']
    old, link, previous, old_manifest = [family[key] for key in ('association', 'link', 'previous_subject', 'old_manifest')]
    need(prep['status'] == 'unsigned_association_bound_definition_review_subject'
         and prep['unsigned'] is prep['review_subject_created'] is True
         and prep['assessment_created'] is prep['signatures_created'] is False
         and prep['training_mask'] == prep['evaluation_gold_mask'] == 0
         and all(value is False for value in prep['authority'].values())
         and prep['unresolved_claims'] == EXPECTED_UNRESOLVED and not prep['issues'],
         'fresh review preparation gained authority or resolved an unsupported claim')
    need(subject is not None and manifest is not None
         and sha(wire(old)) == family['expected_association_sha256']
         and prep['association_ref']['sha256'] == family['expected_association_sha256']
         and prep['previous_subject_ref']['sha256'] == sha(wire(previous))
         and prep['correspondence_ref']['sha256'] == sha(wire(link))
         and prep['source_identity_ref']['sha256'] == sha(wire(old['source_identity']))
         and prep['candidate_ref'] == old['candidate_ref'], 'fresh review original references differ')
    need(old['population_subject_count'] == len(old['population_subjects']) == 560
         and old['population_counts']['pending'] == 560
         and all(row['state'] == 'pending' for row in old['population_subjects'])
         and prep['population_subject_count'] == 560 and prep['population_ref'] == old['population_ref']
         and prep['population_counts'] == old['population_counts']
         and prep['response_count'] == old['response_count'] == 0
         and len(old['occurrence_context_links']) == 6
         and prep['selected_unit_roles'] == old['selected_unit_roles']
         and prep['context_slot_ids'] == subject['context_slot_ids'] == previous['context_slot_ids']
         and len(prep['context_slot_ids']) == 36, 'complete retained population or context commitment differs')
    need(subject['native_binding'] == previous['native_binding']
         and subject['graph_declared_dependency_refs'] == previous['graph_declared_dependency_refs']
         and all(subject[key] == previous[key] for key in ('graph_id', 'graph_sha256', 'ast_sha256', 'scope_id'))
         and sha(wire(subject)) != sha(wire(previous)), 'fresh subject changed native meaning or reused previous complete identity')
    old_artifacts, old_edges = old_manifest['artifacts'], old_manifest['edges']
    need(manifest['artifacts'][:len(old_artifacts)] == old_artifacts
         and manifest['edges'][:len(old_edges)] == old_edges
         and len(manifest['artifacts']) > len(old_artifacts) and len(manifest['edges']) > len(old_edges)
         and sha(wire(manifest)) != sha(wire(old_manifest)), 'entire original manifest population was changed or not extended')
    required = closure(manifest, previous['graph_id'])
    need(required == prep['required_dependency_ids'] == subject['required_dependency_ids']
         and prep['previous_required_dependency_ids'] == previous['required_dependency_ids']
         and set(previous['required_dependency_ids']).issubset(required), 'fresh complete dependency closure differs')
    refs = prep['primary_artifact_refs']
    artifacts = {row['artifact_id']: row for row in manifest['artifacts']}
    need(refs == old['primary_artifact_refs'] and len(refs) == 6
         and all(row['artifact_id'] in required and artifacts[row['artifact_id']]['artifact_sha256'] == row['artifact_sha256']
                 for row in refs), 'all original primary witnesses and mapping commitment must be reachable')
    need(prep['subject_ref']['sha256'] == sha(wire(subject))
         and prep['previous_manifest_ref']['sha256'] == sha(wire(old_manifest))
         and prep['previous_manifest_ref']['manifest_sha256'] == old_manifest['manifest_sha256']
         and prep['dependency_manifest_ref']['sha256'] == sha(wire(manifest))
         and prep['dependency_manifest_ref']['manifest_sha256'] == manifest['manifest_sha256']
         == subject['dependency_manifest_sha256'], 'complete new subject or manifest commitments differ')
    return {
        'status': prep['status'], 'retained_population_subjects': 560, 'retained_population_pending': 560,
        'preparation_population_subject_count': prep['population_subject_count'], 'retained_source_occurrences': 6,
        'context_slots': 36, 'actual_responses': 0, 'primary_artifact_refs': len(refs),
        'old_subject_unchanged': True, 'native_binding_and_contexts_unchanged': True,
        'all_old_manifest_artifacts_and_edges_preserved': True,
        'original_artifacts': len(old_artifacts), 'new_artifacts': len(manifest['artifacts']),
        'original_edges': len(old_edges), 'new_edges': len(manifest['edges']),
        'original_required_dependencies': len(previous['required_dependency_ids']),
        'new_required_dependencies': len(required), 'added_artifacts': len(prep['added_artifact_refs']),
        'all_primary_artifacts_reachable': True, 'all_authority_false': True,
        'training_mask': 0, 'evaluation_gold_mask': 0, 'unresolved_claims': prep['unresolved_claims'],
        'previous_subject_full_canonical_sha256': sha(wire(previous)),
        'new_subject_full_canonical_sha256': sha(wire(subject)),
        'previous_manifest_full_canonical_sha256': sha(wire(old_manifest)),
        'new_manifest_full_canonical_sha256': sha(wire(manifest)),
    }


def main():
    need(len(sys.argv) == 3, 'one native request and frozen consumer config required')
    g = load_guard()
    request_path, config_path = map(Path, sys.argv[1:])
    request_raw = g.snapshot(request_path, MAX_METADATA)
    request = g.decode(request_raw)
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    need(request['schema'] == 'owned-validation-request/v1' and root.is_absolute()
         and root == Path.cwd() and request['argv'] == [sys.executable, '-B', str(Path(__file__).absolute()),
             str(request_path), str(config_path)], 'exact native request, source cwd and argv required')
    layout = {name: str(attempt / name) for name in g.OUTPUT_NAMES}
    need(request['outputs'] == layout and request['declared_external_writable_paths'] == []
         and request['process_scope'] == 'isolated_process_group'
         and request['selected_checks'] == CHECKS, 'exact native writable and check scope required')
    directories = {path: (path.lstat().st_dev, path.lstat().st_ino)
                   for path in (attempt, *(Path(value) for value in layout.values()))}
    g.directory_guard(directories)
    g.physical_parents(root / '__source_identity_only__')
    root_identity = (root.lstat().st_dev, root.lstat().st_ino)
    pins = request['source_sha256']
    need(pins.get(str(GUARD)) == GUARD_SHA256 and str(Path(__file__).absolute()) in pins
         and str(config_path) in pins and config_path.parent == PHASE,
         'guard, consumer helper and phase config require native source pins')
    g.code_guard(pins)
    config_raw = g.snapshot(config_path, MAX_METADATA)
    need(sha(config_raw) == pins[str(config_path)], 'frozen consumer config changed')
    config = g.decode(config_raw)
    need(type(config) is dict and set(config) == CONFIG_FIELDS
         and config['schema'] == 'legal-primary-association-definition-review-consumer-inputs/v1',
         'closed frozen consumer config required')
    redirects = dict(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'], SQLITE_TMPDIR=layout['db'],
                     XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'], HF_HUB_CACHE=layout['cache'],
                     HUGGINGFACE_HUB_CACHE=layout['cache'], HF_DATASETS_CACHE=layout['cache'],
                     TRANSFORMERS_CACHE=layout['cache'], SENTENCE_TRANSFORMERS_HOME=layout['cache'])
    need(os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' and os.environ.get('TMPDIR') == layout['tmp']
         and os.environ.get('XDG_CACHE_HOME') == layout['cache'], 'native no-bytecode redirects required')
    os.environ.update(redirects, IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
                      IPFS_AUTO_INSTALL='false', IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0', HF_HUB_OFFLINE='1',
                      HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
                      OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', BLIS_NUM_THREADS='1',
                      VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = layout['tmp']
    g.no_forbidden_modules()
    need(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
         'fresh product import process required')
    sys.path.insert(0, str(root))
    finder = g.PinnedProductFinder(root, pins)
    sys.meta_path.insert(0, finder)
    attempts = {'network': 0, 'child_process': 0, 'retained_producer_write': 0}

    def producer_path(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        try:
            path = Path(os.fsdecode(value)).absolute()
            return path == PRODUCER or PRODUCER in path.parents
        except (TypeError, ValueError):
            return False

    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                     'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
            attempts['network'] += 1
            raise RuntimeError('network operation refused during retained review consumer')
        if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
            attempts['child_process'] += 1
            raise RuntimeError('extra child refused during retained review consumer')
        if event == 'open' and producer_path(args[0]):
            mode, flags = args[1], args[2]
            writing = (type(mode) is str and any(char in mode for char in 'wax+')) or (
                type(flags) is int and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writing:
                attempts['retained_producer_write'] += 1
                raise RuntimeError('retained producer write refused')
        if event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.link', 'os.symlink',
                     'os.chmod', 'os.chown', 'os.truncate', 'os.utime'} and any(producer_path(value) for value in args[:2]):
            attempts['retained_producer_write'] += 1
            raise RuntimeError('retained producer mutation refused')

    sys.addaudithook(audit)
    logs, exports = Path(layout['logs']), Path(layout['exports'])
    out = OutputFiles(g, exports, directories)
    receipt = {
        'schema': 'legal-primary-association-definition-review-consumer/v1', 'status': 'failed',
        'request': pin(request_path, request_raw), 'config': pin(config_path, config_raw),
        'selected_checks': CHECKS, 'completed_checks': [], 'pytest_testcases_executed': 0,
        'actual_reviews': 0, 'assessments_created': 0, 'signatures_created': 0,
        'training_mask': 0, 'evaluation_gold_mask': 0, 'old_producer_main_invoked': False,
        'fresh_interpreter_retained_artifact_consumer': True,
        'native_parent_owns_admission_supervision_seal_and_release': True,
    }
    started, stage = time.monotonic(), 'accepted_retained_producer'
    try:
        accepted_descriptor_raw = descriptor_bytes(g, config['accepted_producer_descriptor'],
                                                  maximum=64 * 1024, native_pins=pins)
        accepted = accept_producer(g, g.decode(accepted_descriptor_raw))
        receipt['accepted_producer_descriptor'] = config['accepted_producer_descriptor']
        before_ref = out.json('retained-producer-inventory-before.json', accepted['inventory'])
        receipt['producer_inventory_before'] = {
            'file_count': accepted['inventory']['file_count'], 'bytes': accepted['inventory']['bytes'],
            'directory_count': accepted['inventory']['directory_count'],
            'full_canonical_sha256': sha(wire(accepted['inventory'])),
            'file': before_ref,
        }
        receipt['retained_replay_files'] = 64
        receipt['retained_replay_bytes'] = 10630440
        receipt['retained_association_files'] = 7
        receipt['retained_association_bytes'] = 336630
        receipt['retained_old_source_pins_checked'] = len(accepted['old_source_pins'])
        stage = 'retained_original_family_arguments'
        families = retained_families(g, accepted)
        original_tokens = {family: {key: sha(wire(value[key])) for key in (
            'association', 'link', 'binding', 'previous_subject', 'old_manifest')}
            for family, value in families.items()}
        stage = 'independently_pinned_primary_metadata'
        report_raw = descriptor_bytes(g, config['reconstruction_report'], native_pins=pins)
        baseline_raw = descriptor_bytes(g, config['index_baseline'], native_pins=pins)
        report, baseline = g.decode(report_raw), g.decode(baseline_raw)
        candidate = config['primary_candidate']
        checked_descriptor(candidate, maximum=1024 * 1024 * 1024)
        need(candidate['bytes'] == 716898677 and candidate['sha256'] == EXPECTED_CANDIDATE_SHA256
             and report['candidate_bytes'] == candidate['bytes'] and report['candidate_sha256'] == candidate['sha256']
             and config['expected_index_sha256'] == baseline['index_sha256'] == EXPECTED_INDEX_SHA256
             and baseline['candidate_bytes'] == candidate['bytes']
             and baseline['primary_identity']['candidate_sha256'] == candidate['sha256']
             and report['reconstruction_sha256'] == config['expected_reconstruction_sha256'] == baseline['reconstruction_sha256']
             and sha(wire(report)) == config['expected_reconstruction_full_canonical_sha256'],
             'independently accepted full primary index metadata differs')
        from ipfs_datasets_py.logic.autoformal.legal_primary_section_index import PrimarySectionIndex
        from ipfs_datasets_py.logic.autoformal import legal_source_sampling_primary_review_v2 as owner
        import pyarrow as pa
        pa.set_cpu_count(1)
        pa.set_io_thread_count(1)
        stage = 'full_original_primary_index'
        with PrimarySectionIndex(candidate['path'], reconstruction_report=report,
                                 expected_candidate_sha256=candidate['sha256'],
                                 expected_reconstruction_sha256=config['expected_reconstruction_sha256']) as index:
            need(index.index_sha256 == EXPECTED_INDEX_SHA256 and wire(index.receipt) == wire(baseline),
                 'fresh complete original primary index differs from independent baseline')
            receipt['primary_index_receipt'] = out.json('primary-index-receipt.json', index.receipt)
            prepared = []
            for family in ('fol', 'tdfol'):
                stage = family + '_fresh_retained_primary_review'
                f = families[family]
                args = {'expected_association_sha256': f['expected_association_sha256'],
                        'association_replay_inputs': f['arguments']}
                envelope = owner.prepare_primary_association_definition_review_v2(
                    f['association'], f['link'], f['binding'], f['previous_subject'], index, **args)
                expected = owner.primary_association_definition_review_sha256(envelope)
                need(expected == sha(wire(envelope)), 'complete review envelope hash recipe differs')
                envelope_ref = out.json(family + '-primary-review-envelope.json', envelope)
                saved = g.decode(g.snapshot(Path(envelope_ref['path']), 4 * 1024 * 1024))
                checked = owner.validate_primary_association_definition_review_v2(
                    saved, f['association'], f['link'], f['binding'], f['previous_subject'], index,
                    expected_preparation_sha256=expected, **args)
                need(wire(checked) == wire(envelope), 'saved review envelope changed under original-bound replay')
                summary = check_review(envelope, f)
                refs = {'envelope': envelope_ref}
                for field, suffix in [('preparation', 'preparation'), ('subject', 'subject'),
                                      ('dependency_manifest', 'dependency-manifest')]:
                    refs[field] = out.json(family + '-primary-review-' + suffix + '.json', envelope[field])
                prepared.append({'family': family, 'envelope_full_canonical_sha256': expected,
                                 'retained_association': f['association_raw_pin'],
                                 'retained_association_full_canonical_sha256': f['expected_association_sha256'],
                                 'retained_mapping': f['mapping_raw_pin'], 'outputs': refs, **summary})
            receipt['families'] = prepared
        stage = 'closing_original_inputs_and_source_buffers'
        need(g.snapshot(request_path, MAX_METADATA) == request_raw
             and g.snapshot(config_path, MAX_METADATA) == config_raw
             and descriptor_bytes(g, config['accepted_producer_descriptor'], maximum=64 * 1024,
                                  native_pins=pins) == accepted_descriptor_raw,
             'frozen request, config or accepted producer descriptor changed')
        g.code_guard(pins)
        g.code_guard(accepted['old_source_pins'])
        for family, f in families.items():
            need({key: sha(wire(f[key])) for key in original_tokens[family]} == original_tokens[family],
                 'retained in-memory original artifact changed')
        after = scan_inventory(g, PRODUCER, accepted['expected_names'])
        need(wire(after) == wire(accepted['inventory']), 'retained original producer inventory changed')
        for field, raw in accepted['raws'].items():
            need(descriptor_bytes(g, accepted['descriptor'][field], maximum=MAX_METADATA,
                                  allow_empty=field == 'captured_parent_stderr') == raw,
                 'accepted original native metadata or capture changed')
        receipt['producer_inventory_after'] = {
            'file_count': after['file_count'], 'bytes': after['bytes'], 'directory_count': after['directory_count'],
            'full_canonical_sha256': sha(wire(after)),
            'file': out.json('retained-producer-inventory-after.json', after),
        }
        receipt['retained_producer_inventory_unchanged'] = True
        stage = 'closing_product_origins_and_native_outputs'
        g.directory_guard(directories)
        g.no_forbidden_modules()
        receipt['loaded_product_source_origins'] = g.product_origins(root, pins, finder)
        need(Path.cwd() == root and (root.lstat().st_dev, root.lstat().st_ino) == root_identity,
             'selected source checkout changed')
        need(tempfile.tempdir == layout['tmp'] and all(os.environ.get(key) == value for key, value in redirects.items()),
             'native writable redirects changed')
        need(not any(attempts.values()), 'forbidden network, process or producer-write attempt occurred')
        need(pa.cpu_count() == 1 and pa.io_thread_count() == 1, 'Arrow thread limits changed')
        out.verify()
        receipt.update(status='pass', completed_checks=CHECKS, all_checks_complete=True,
                       source_pin_count=len(pins), loaded_product_source_origin_count=len(receipt['loaded_product_source_origins']),
                       outputs=list(out.files.values()), output_bytes=out.total,
                       elapsed_seconds=time.monotonic() - started, guard_attempts=attempts,
                       authority={
                           'source_authenticity_verified': False, 'primary_source_correspondence_verified': False,
                           'source_package_content_identity_verified': False, 'governing_applicability_verified': False,
                           'independent_legal_review_performed': False, 'independent_formal_review_performed': False,
                           'authenticated_exposure': False, 'training_qualified': False, 'Lean_admitted': False,
                           'published': False,
                       }, limitations=[
                           'The new consumer runs in a fresh interpreter over retained originals; saved new-envelope validation is in that same consumer process.',
                           'Accepted producer closeout is retained captured parent/native evidence, not independent scheduler authentication.',
                           'Checked Python buffers, operation guards and read-only producer checks are cooperative; no OS sandbox, kernel quota or arbitrary descendant containment is claimed.',
                           'A fresh unsigned V2 definition subject binds existing primary evidence; source equivalence, governing applicability, independent meaning and authenticated exposure remain open.',
                           'The old 17 named checks and eight refusals are retained producer history, not tests newly executed by this consumer.',
                           'Only the native parent establishes final consumer durability, stopped recorded groups and resource release.',
                       ])
        saved_receipt = g.save(logs / 'primary-review-consumer-receipt.json', receipt, directories)
        print(json.dumps({'status': 'pass', 'receipt': saved_receipt,
                          'families': ['fol', 'tdfol'], 'new_review_subjects': 2}, sort_keys=True), flush=True)
        return 0
    except BaseException as error:
        receipt.update(status='failed', completed_checks=[], all_checks_complete=False,
                       failure_stage=stage, error_type=type(error).__name__,
                       error='Bounded retained primary-review consumer failure; arbitrary exception text omitted.',
                       elapsed_seconds=time.monotonic() - started, guard_attempts=attempts,
                       completed_outputs=list(out.files.values()),
                       product_origin_diagnostics=g.product_diagnostics(root, pins, finder))
        g.save(logs / 'primary-review-consumer-failed.json', receipt, directories)
        raise RuntimeError('retained primary review consumer failed at ' + stage) from None


if __name__ == '__main__':
    try:
        result = main()
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'error': 'Bounded native consumer failure; arbitrary exception text omitted.'}, sort_keys=True),
              file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(result)

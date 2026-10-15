"""Discover literal primary anchors OR replay unsigned sampled associations.

Run only inside the existing frozen owned-validation child. The native parent
owns admission, supervision, durability and release. Discovery is an earlier
separate request; association consumes the caller's independently frozen anchor
declaration. Neither operation authenticates source equivalence or legal meaning.
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


PHASE = Path('/home/barberb/lift_coding/artifacts/legal-sampled-primary-association-20261015-01')
GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
GUARD_SHA256 = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
REPLAY_RELATIVE = 'scripts/ops/legal_ir/replay_retained_definition_correspondence.py'
REPLAY_SHA256 = 'a580d10c33539058ff5019a6edd1b48a14b65adac4597567629573998f5a9d8b'
EXPECTED_INDEX_SHA256 = '82b8099255a93c5a22135229d9bcab8a7a8dd25f09074ca744155734a1d931e1'
EXPECTED_CANDIDATE_SHA256 = '46986513582973996e4d69ecf0669ed7331e6cca07ca793f3b1c1ea2dcdec8f1'
MAX_METADATA = 1024 * 1024
MAX_SOURCE = 4 * 1024 * 1024
MAX_REPLAY_FILE = 30_000_000
MAX_ASSOCIATION_OUTPUT = 32 * 1024 * 1024
CHECKS = {
    'discover': ['full_original_primary_index_baseline', 'literal_section101_primary_discovery',
        'source_and_native_output_closing_guards'],
    'associate': ['retained-section101-definition-review-correspondence-fol-tdfol-with-eight-refusals',
        'full_original_primary_index_baseline', 'fol_original_bound_sampled_primary_association',
        'tdfol_original_bound_sampled_primary_association', 'source_and_native_output_closing_guards'],
}
CONFIG_FIELDS = {'schema', 'mode', 'retained_input_descriptor', 'primary_candidate',
    'reconstruction_report', 'expected_reconstruction_sha256',
    'expected_reconstruction_full_canonical_sha256', 'index_baseline',
    'expected_index_sha256', 'mapping_declaration'}
PRODUCT_CORRESPONDENCE_FIELDS = (
    'source_identity', 'population_ref', 'population_subjects', 'population_counts',
    'population_subject_count', 'response_count', 'selected_unit_roles', 'required_subjects',
    'source_role_bindings', 'occurrence_context_links', 'candidate_ref', 'subject_ref',
    'dependency_manifest_ref', 'context_slot_ids',
)


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


def raw_module(path, raw, name):
    need(name not in sys.modules, 'fresh metadata helper module required')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0), module.__dict__)
    return module


def load_guard():
    need(not sys.flags.optimize and sys.dont_write_bytecode, 'nonoptimized no-bytecode Python required')
    for p in (GUARD.parent, *GUARD.parent.parents):
        need(stat.S_ISDIR(p.lstat().st_mode), 'guard parent must be unaliased')
    with os.fdopen(os.open(GUARD, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        before = os.fstat(f.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_size == 28529, 'exact retained source guard required')
        raw = f.read(MAX_SOURCE + 1)
        after = os.fstat(f.fileno())
    identity = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_size, v.st_mtime_ns, v.st_ctime_ns, v.st_nlink)
    need(identity(before) == identity(after) == identity(GUARD.lstat())
        and sha(raw) == GUARD_SHA256, 'retained source guard changed')
    return raw_module(GUARD, raw, '_sampled_primary_guard_v01')


def metadata_input(g, descriptor, pins, maximum=MAX_SOURCE):
    need(type(descriptor) is dict and set(descriptor) == {'path', 'bytes', 'sha256'},
        'exact independently supplied metadata descriptor required')
    path = Path(descriptor['path'])
    need(path.is_absolute() and type(descriptor['bytes']) is int
        and 0 < descriptor['bytes'] <= maximum
        and type(descriptor['sha256']) is str
        and re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256'])
        and pins.get(str(path)) == descriptor['sha256'], 'metadata requires its frozen native pin')
    raw = g.snapshot(path, maximum)
    need(pin(path, raw) == descriptor, 'metadata differs from independently supplied descriptor')
    return raw


class AssociationFiles:
    """New metadata only; the replay driver's closed exports are never changed."""
    def __init__(self, g, logs, directories):
        self.g, self.directories = g, directories
        g.directory_guard(directories)
        self.path = logs / 'association'
        os.mkdir(self.path, 0o700)
        info = self.path.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'private new association directory required')
        self.directories[self.path] = (info.st_dev, info.st_ino)
        self.files, self.total = {}, 0

    def add(self, name, raw):
        need(type(raw) is bytes and type(name) is str
            and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,100}', name)
            and name not in self.files and len(self.files) < 24
            and 0 < len(raw) <= 16 * 1024 * 1024
            and self.total + len(raw) <= MAX_ASSOCIATION_OUTPUT,
            'bounded unique association output required')
        self.g.directory_guard(self.directories)
        path = self.path / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        actual = self.g.snapshot(path, 16 * 1024 * 1024)
        need(actual == raw, 'association output readback differs')
        row = pin(path, raw)
        self.files[name] = row
        self.total += len(raw)
        fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return row

    def json(self, name, value):
        return self.add(name, wire(value) + b'\n')

    def verify(self):
        self.g.directory_guard(self.directories)
        names = set()
        with os.scandir(self.path) as entries:
            for row in entries:
                need(len(names) < len(self.files), 'unexpected association output')
                names.add(row.name)
        need(names == set(self.files), 'association output population changed')
        for row in self.files.values():
            need(pin(Path(row['path']), self.g.snapshot(Path(row['path']), 16 * 1024 * 1024)) == row,
                'association output hash changed')


def replay_artifacts(g, root, exports, descriptor, pins):
    """Execute unchanged main once, then use only its freshly pinned file indices."""
    path = root / REPLAY_RELATIVE
    raw = g.snapshot(path, MAX_SOURCE)
    need(sha(raw) == REPLAY_SHA256 and pins.get(str(path)) == REPLAY_SHA256,
        'unchanged retained replay driver must be native pinned')
    replay = raw_module(path, raw, '_sampled_primary_retained_replay_v01')
    original_argv = sys.argv
    try:
        sys.argv = [str(path), '--input-descriptor', descriptor['path'],
            '--expected-input-descriptor-sha256', descriptor['sha256'],
            '--output-directory', str(exports)]
        returned = replay.main()
        need(returned is None, 'unchanged replay main return contract differs')
    finally:
        sys.argv = original_argv
    receipt_raw = g.snapshot(exports / 'replay-receipt.json', MAX_METADATA)
    receipt = g.decode(receipt_raw)
    need(receipt['schema'] == replay.SCHEMA and receipt['all_checks_passed'] is True
        and receipt['selected_check'] == CHECKS['associate'][0]
        and receipt['named_check_count'] == 17 and receipt['negative_controls_refused'] == 8
        and receipt['input_descriptor_sha256'] == descriptor['sha256']
        and receipt['whole_source_subjects'] == 560
        and receipt['actual_response_count'] == receipt['actual_reviews'] == receipt['assessments_created'] == 0,
        'complete fresh retained-source replay receipt required')
    file_index_raw = g.snapshot(exports / 'file-index.json', MAX_METADATA)
    file_index = g.decode(file_index_raw)
    rows = file_index['files']
    need(file_index['schema'] == 'retained-definition-correspondence-file-index/v1'
        and type(rows) is list and len(rows) == 63, 'fresh complete 64-file replay index required')
    by_name = {}
    for row in rows:
        need(type(row) is dict and set(row) == {'path', 'bytes', 'sha256'}
            and type(row['path']) is str and Path(row['path']).name == row['path']
            and row['path'] not in by_name, 'closed unique replay output reference required')
        by_name[row['path']] = row
    def read(row):
        need(by_name.get(row['path']) == row, 'replay reference is outside its freshly fixed inventory')
        return replay.read_exact(exports / row['path'], row['bytes'], row['sha256'], maximum=MAX_REPLAY_FILE)[0]
    for row in rows:
        read(row)
    need(read(by_name['replay-receipt.json']) == receipt_raw, 'replay receipt and file index differ')
    original = receipt['original_inputs']
    bundle = g.decode(read(original['bundle']))
    raw_html = read(original['raw_html'])
    sampling_raw = read(original['sampling_report'])
    binding_inputs = deepcopy(bundle['manifest']['input_binding'])
    need(set(binding_inputs) == {'descriptor', 'expected_descriptor_sha256', 'expected_raw_sha256', 'expected_raw_bytes'},
        'retained omitted optional argument population must remain exact')
    binding_inputs['expected_sampling_report_sha256'] = sha(wire(g.decode(sampling_raw)))
    families = {}
    for summary in receipt['families']:
        family = summary['family']
        need(family in ('fol', 'tdfol') and family not in families, 'both distinct family indices required')
        idx = g.decode(read(summary['replay_index']))
        custody = g.decode(read(idx['original_inputs']))
        contexts = g.decode(read(idx['contexts']))
        inputs = {key: read(row) for key, row in custody['inputs'].items()}
        result, subject, link, manifest = [g.decode(read(idx[k]))
            for k in ('binding_result', 'subject', 'correspondence', 'manifest')]
        need(sha(wire(result)) == idx['binding_full_canonical_sha256']
            and sha(wire(subject)) == idx['subject_full_canonical_sha256']
            and sha(wire(link)) == idx['correspondence_full_canonical_sha256']
            and sha(wire(manifest)) == idx['manifest_full_canonical_sha256']
            and manifest['manifest_sha256'] == idx['manifest_internal_sha256'],
            'fresh family canonical commitments differ')
        args = {'expected_binding_sha256': idx['binding_full_canonical_sha256'],
            'expected_subject_sha256': idx['subject_full_canonical_sha256'],
            'binding_replay_inputs': {'request_raw': inputs['request_raw'], 'bundle': bundle,
                'responses': [], 'raw_html': raw_html, 'expected_request_sha256': sha(inputs['request_raw']),
                'expected_bundle_sha256': sha(wire(bundle)), 'expected_response_sha256s': [],
                'sampling_replay_inputs': deepcopy(binding_inputs)},
            'candidate_inputs': inputs, 'expected_candidate_pin': custody['candidate_pin'],
            'context_inputs': [{'source_occurrence_cid': row['source_occurrence_cid'],
                'packet_raw': read(row['packet']), 'dependency_requests': row['dependency_requests']}
                for row in contexts['contexts']],
            'expected_context_population': contexts['expected_context_population'],
            'dependency_manifest': manifest, 'expected_manifest_sha256': idx['manifest_internal_sha256'],
            'required_dependency_ids': idx['required_dependency_ids']}
        families[family] = {'link': link, 'result': result, 'subject': subject,
            'arguments': args, 'expected_correspondence_sha256': idx['correspondence_full_canonical_sha256'],
            'replay_index': summary['replay_index']}
    need(set(families) == {'fol', 'tdfol'}, 'complete two-family replay required')
    names = set()
    with os.scandir(exports) as entries:
        for row in entries:
            need(len(names) < 64, 'unexpected fresh replay export entry')
            names.add(row.name)
    need(names == set(by_name) | {'file-index.json'}, 'fresh replay export population differs')
    return families, pin(exports / 'replay-receipt.json', receipt_raw), pin(exports / 'file-index.json', file_index_raw), by_name


def lookup_summary(lookup):
    need(type(lookup['sections']) is list and len(lookup['sections']) <= 256,
        'bounded discovery section summary required')
    return {'legal_id': lookup['legal_id'], 'index_sha256': lookup['index_sha256'],
        'section_count': len(lookup['sections']), 'issues': lookup['issues'],
        'sections': [{'section_entry_cid': s['entry_cid'],
            'section_global_ordinal': s['section_observation']['global_ordinal'],
            'issues': s['issues'],
            'source_packages': [{'source_package_entry_cid': p['entry_cid'],
                'source_package_global_ordinal': p['source_package_observation']['global_ordinal'],
                'has_source_edge_global_ordinals': [e['global_ordinal'] for e in p['has_source_observations']]}
                for p in s['source_packages']],
            'release_points': [{'entry_cid': p['entry_cid'],
                'global_ordinal': p['release_point_observation']['global_ordinal'],
                'has_source_edge_global_ordinals': [e['global_ordinal'] for e in p['has_source_observations']]}
                for p in s['release_points']],
            'all_outgoing_has_source_count': len(s['has_source_observations']),
            'incoming_has_source_count': len(s['incoming_has_source_observations']),
            'other_source_target_count': len(s['other_source_targets'])} for s in lookup['sections']],
        'authority': lookup['authority'], 'caller_mapping_frozen': False,
        'source_equivalence_or_legal_review_established': False}


def check_association(result, link, declaration):
    need(all(wire(result[field]) == wire(link[field]) for field in PRODUCT_CORRESPONDENCE_FIELDS),
        'all fourteen original correspondence fields must remain exact')
    subjects = result['population_subjects']
    need(type(subjects) is list and len(subjects) == result['population_subject_count'] == 560
        and result['population_counts']['pending'] == 560
        and all(row['state'] == 'pending' for row in subjects)
        and type(result['response_count']) is int and result['response_count'] == 0
        and len(result['occurrence_context_links']) == 6 and len(result['context_slot_ids']) == 36,
        'complete pending population and physical context counts must remain exact')
    refs = result['primary_artifact_refs']
    roles = {}
    for ref in refs:
        roles[ref['role']] = roles.get(ref['role'], 0) + 1
    declared = declaration['section_entry_cid'] is not None and declaration['source_package_entry_cid'] is not None
    if declared:
        need(result['status'] == 'declared_primary_association_only' and result['issues'] == [],
            'nonnull caller anchors require a healthy declared-only association')
        need(any(r['artifact_id'] == declaration['section_entry_cid']
                and r['role'] == 'declared_primary_section' for r in refs)
            and any(r['artifact_id'] == declaration['source_package_entry_cid']
                and r['role'] == 'declared_primary_source_package' for r in refs)
            and roles.get('declared_HAS_SOURCE_transport_evidence', 0) > 0,
            'exact declared section package and directed source evidence required')
        sections = result['primary_lookup']['sections']
        need(len(sections) == 1, 'healthy declared association needs one literal section')
        section = sections[0]
        packages = [p for p in section['source_packages']
            if p['entry_cid'] == declaration['source_package_entry_cid']]
        need(len(packages) == 1, 'healthy declaration needs exactly one declared source package')
        exact_records = [(section['section_observation'], 'declared_primary_section'),
            (packages[0]['source_package_observation'], 'declared_primary_source_package')]
        exact_records.extend((edge, 'declared_HAS_SOURCE_transport_evidence')
            for edge in packages[0]['has_source_observations'])
        for observation, role in exact_records:
            need(any(r == {'artifact_id': observation['declared_identity']['entry_cid'],
                    'artifact_sha256': observation['record_sha256'], 'role': role} for r in refs),
                'declared anchors and source edges must retain original record hashes')
        for point in sections[0]['release_points']:
            observation = point['release_point_observation']
            need(any(r == {'artifact_id': point['entry_cid'],
                    'artifact_sha256': observation['record_sha256'],
                    'role': 'declared_primary_release_point'} for r in refs),
                'every recognized release point must retain its original record commitment')
            for edge in point['has_source_observations']:
                need(any(r == {'artifact_id': edge['declared_identity']['entry_cid'],
                        'artifact_sha256': edge['record_sha256'],
                        'role': 'declared_HAS_SOURCE_release_context_evidence'} for r in refs),
                    'every recognized release context witness must remain exact')
    else:
        need(result['status'] == 'unresolved_primary_association' and bool(result['issues']),
            'missing caller anchors must remain an explicit unresolved gap')
    return {'population_subjects': len(subjects), 'population_pending': result['population_counts']['pending'],
        'source_occurrences': len(result['occurrence_context_links']),
        'context_slots': len(result['context_slot_ids']), 'actual_responses': result['response_count'],
        'all_subjects_pending': True, 'preserved_original_correspondence_fields': list(PRODUCT_CORRESPONDENCE_FIELDS),
        'status': result['status'], 'issues': result['issues'], 'primary_artifact_ref_count': len(refs),
        'primary_artifact_roles': roles, 'nonnull_caller_anchors_supplied': declared}


def main():
    need(len(sys.argv) == 3, 'native request and independently frozen config required')
    g = load_guard()
    request_path, config_path = map(Path, sys.argv[1:])
    request_raw = g.snapshot(request_path, MAX_METADATA)
    request = g.decode(request_raw)
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    need(request['schema'] == 'owned-validation-request/v1' and root.is_absolute()
        and root == Path.cwd() and request['argv'] == [sys.executable, '-B', str(Path(__file__).absolute()),
            str(request_path), str(config_path)], 'exact native request, cwd and child argv required')
    layout = {name: str(attempt / name) for name in g.OUTPUT_NAMES}
    need(request['outputs'] == layout and request['declared_external_writable_paths'] == []
        and request['process_scope'] == 'isolated_process_group', 'exact native output layout required')
    directories = {p: (p.lstat().st_dev, p.lstat().st_ino)
        for p in (attempt, *(Path(v) for v in layout.values()))}
    g.directory_guard(directories)
    g.physical_parents(root / '__source_identity_only__')
    root_identity = (root.lstat().st_dev, root.lstat().st_ino)
    pins = request['source_sha256']
    need(pins.get(str(GUARD)) == GUARD_SHA256 and str(Path(__file__).absolute()) in pins
        and str(config_path) in pins and config_path.parent == PHASE,
        'guard, helper and phase config must be native pinned')
    g.code_guard(pins)
    config_raw = g.snapshot(config_path, MAX_METADATA)
    need(sha(config_raw) == pins[str(config_path)], 'frozen config changed')
    config = g.decode(config_raw)
    need(type(config) is dict and set(config) == CONFIG_FIELDS
        and config['schema'] == 'legal-sampled-primary-actual-inputs/v1'
        and config['mode'] in CHECKS, 'closed discover or associate config required')
    mode = config['mode']
    need(request['selected_checks'] == CHECKS[mode], 'named artifact checks must match actual mode')
    declaration = config['mapping_declaration']
    need(type(declaration) is dict and set(declaration) == {'legal_id', 'section_entry_cid', 'source_package_entry_cid'}
        and declaration['legal_id'] == 'usc:us:10:101'
        and all(declaration[k] is None or type(declaration[k]) is str and 0 < len(declaration[k]) <= 4096
            for k in ('section_entry_cid', 'source_package_entry_cid')), 'exact literal caller declaration required')
    if mode == 'discover':
        need(config['retained_input_descriptor'] is None
            and declaration['section_entry_cid'] is None and declaration['source_package_entry_cid'] is None,
            'discovery cannot claim a preselected association or replay input')
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
    need(not any(n == 'ipfs_datasets_py' or n.startswith('ipfs_datasets_py.') for n in sys.modules),
        'fresh product import process required')
    sys.path.insert(0, str(root))
    finder = g.PinnedProductFinder(root, pins)
    sys.meta_path.insert(0, finder)
    attempts = {'network': 0, 'child_process': 0}
    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
            attempts['network'] += 1
            raise RuntimeError('network operation refused during sampled primary replay')
        if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
            attempts['child_process'] += 1
            raise RuntimeError('extra child refused during sampled primary replay')
    sys.addaudithook(audit)
    logs, exports = Path(layout['logs']), Path(layout['exports'])
    out = AssociationFiles(g, logs, directories)
    receipt = {'schema': 'legal-sampled-primary-actual-' + mode + '/v1', 'mode': mode, 'status': 'failed',
        'request': pin(request_path, request_raw), 'config': pin(config_path, config_raw),
        'selected_checks': CHECKS[mode], 'completed_checks': [], 'pytest_testcases_executed': 0,
        'actual_reviews': 0, 'training_mask': 0, 'evaluation_gold_mask': 0,
        'native_parent_owns_admission_supervision_seal_and_release': True}
    stage, started = 'authenticated_primary_metadata', time.monotonic()
    try:
        report_raw = metadata_input(g, config['reconstruction_report'], pins)
        report = g.decode(report_raw)
        baseline_raw = metadata_input(g, config['index_baseline'], pins)
        baseline = g.decode(baseline_raw)
        candidate = config['primary_candidate']
        need(type(candidate) is dict and set(candidate) == {'path', 'bytes', 'sha256'}
            and type(candidate['path']) is str and Path(candidate['path']).is_absolute()
            and candidate['bytes'] == 716898677 and candidate['sha256'] == EXPECTED_CANDIDATE_SHA256
            and report['candidate_bytes'] == candidate['bytes'] and report['candidate_sha256'] == candidate['sha256']
            and config['expected_index_sha256'] == EXPECTED_INDEX_SHA256
            and baseline['index_sha256'] == EXPECTED_INDEX_SHA256
            and baseline['candidate_bytes'] == candidate['bytes']
            and baseline['primary_identity']['candidate_sha256'] == candidate['sha256']
            and report['reconstruction_sha256'] == config['expected_reconstruction_sha256'] == baseline['reconstruction_sha256']
            and sha(wire(report)) == config['expected_reconstruction_full_canonical_sha256'],
            'independently accepted complete original index inputs required')
        families = {}
        replay_index = None
        if mode == 'associate':
            stage = 'unchanged_retained_source_replay'
            descriptor = config['retained_input_descriptor']
            metadata_input(g, descriptor, pins, 64 * 1024)
            print(json.dumps({'mode': mode, 'stage': stage}, sort_keys=True), flush=True)
            families, replay_receipt, replay_index, replay_files = replay_artifacts(g, root, exports, descriptor, pins)
            receipt.update(retained_replay_receipt=replay_receipt, retained_replay_file_index=replay_index,
                retained_named_checks=17, retained_refused_controls=8,
                retained_population_subjects=560, selected_source_subjects_per_family=2,
                physical_occurrences_per_family=6, open_context_slots_per_family=36)
        stage = 'full_original_primary_index'
        from ipfs_datasets_py.logic.autoformal import legal_primary_section_index as index_owner
        index = index_owner.PrimarySectionIndex(candidate['path'], reconstruction_report=report,
            expected_candidate_sha256=candidate['sha256'],
            expected_reconstruction_sha256=config['expected_reconstruction_sha256'])
        print(json.dumps({'mode': mode, 'stage': stage, 'candidate_rows': 297825}, sort_keys=True), flush=True)
        with index:
            need(index.index_sha256 == EXPECTED_INDEX_SHA256 and wire(index.receipt) == wire(baseline),
                'full live index differs from independently retained v2 baseline')
            index_ref = out.json('primary-index-receipt.json', index.receipt)
            lookup = index.lookup_sections(declaration['legal_id'])
            need(all(v is False for v in lookup['authority'].values()), 'lookup authority was raised')
            lookup_ref = out.json('literal-section101-lookup.json', lookup)
            summary = lookup_summary(lookup)
            summary_ref = out.json('literal-section101-discovery-summary.json', summary)
            receipt.update(primary_index_receipt=index_ref, primary_lookup=lookup_ref,
                discovery_summary=summary_ref, expected_index_sha256=EXPECTED_INDEX_SHA256)
            if mode == 'associate':
                from ipfs_datasets_py.logic.autoformal import legal_source_sampling_primary_association_v2 as owner
                need(tuple(owner._CORRESPONDENCE_FIELDS) == PRODUCT_CORRESPONDENCE_FIELDS,
                    'qualified product correspondence preservation roster changed')
                associated = []
                for family in ('fol', 'tdfol'):
                    stage = family + '_sampled_primary_association'
                    f = families[family]
                    link = f['link']
                    mapping = {'schema': owner.MAPPING_SCHEMA,
                        'correspondence_sha256': f['expected_correspondence_sha256'],
                        'source_identity_sha256': sha(wire(link['source_identity'])),
                        'source_occurrence_cids': [row['occurrence_ref']['record_cid'] for row in link['occurrence_context_links']],
                        **declaration}
                    mapping_ref = out.json(family + '-caller-mapping.json', mapping)
                    mapping_raw = g.snapshot(Path(mapping_ref['path']), 64 * 1024)
                    need(pin(Path(mapping_ref['path']), mapping_raw) == mapping_ref, 'frozen caller mapping changed before call')
                    args = dict(expected_correspondence_sha256=f['expected_correspondence_sha256'],
                        correspondence_replay_inputs=f['arguments'], mapping_raw=mapping_raw,
                        expected_mapping_file_sha256=mapping_ref['sha256'], expected_index_sha256=EXPECTED_INDEX_SHA256)
                    result = owner.prepare_sampled_primary_association_v2(link, f['result'], f['subject'], index, **args)
                    expected = owner.sampled_primary_association_sha256(result)
                    result_ref = out.json(family + '-sampled-primary-association.json', result)
                    offered_raw = g.snapshot(Path(result_ref['path']), MAX_METADATA)
                    checked = owner.validate_sampled_primary_association_v2(g.decode(offered_raw), link,
                        f['result'], f['subject'], index, expected_association_sha256=expected, **args)
                    need(wire(checked) == wire(result) and all(v is False for v in result['authority'].values())
                        and result['training_mask'] == result['evaluation_gold_mask'] == 0,
                        'original-bound association changed or gained authority')
                    actual = check_association(result, link, declaration)
                    need(g.snapshot(Path(mapping_ref['path']), 64 * 1024) == mapping_raw,
                        'frozen caller mapping changed during call')
                    associated.append({'family': family, 'mapping': mapping_ref, 'association': result_ref,
                        'association_sha256': expected, **actual,
                        'correspondence_replay_index': f['replay_index'], 'all_authority_false': True})
                receipt['associations'] = associated
                receipt['mapping_freeze_scope'] = 'Caller declaration from frozen config plus exact fresh-link identity; not independent source equivalence, authenticity, exposure or legal review.'
        stage = 'closing_frozen_request_and_config'
        need(g.snapshot(request_path, MAX_METADATA) == request_raw
            and g.snapshot(config_path, MAX_METADATA) == config_raw, 'request or config changed')
        g.code_guard(pins)
        stage = 'closing_source_and_product_origins'
        g.directory_guard(directories)
        g.no_forbidden_modules()
        receipt['loaded_product_source_origins'] = g.product_origins(root, pins, finder)
        need(Path.cwd() == root and (root.lstat().st_dev, root.lstat().st_ino) == root_identity,
            'selected source checkout changed')
        need(tempfile.tempdir == layout['tmp'] and all(os.environ.get(k) == v for k, v in redirects.items()),
            'native writable redirects changed')
        need(not any(attempts.values()), 'network or child attempt occurred even if caught')
        if mode == 'associate':
            stage = 'closing_unchanged_replay_export_inventory'
            need(pin(Path(replay_index['path']), g.snapshot(Path(replay_index['path']), MAX_METADATA)) == replay_index,
                'original replay file index changed')
            names = set()
            with os.scandir(exports) as entries:
                for entry in entries:
                    need(len(names) < 64, 'extra entry changed the original replay closure')
                    names.add(entry.name)
            need(names == set(replay_files) | {'file-index.json'}, 'original replay closed exports changed')
            for name, row in replay_files.items():
                need(pin(exports / name, g.snapshot(exports / name, MAX_REPLAY_FILE))
                    == {'path': str(exports / name), 'bytes': row['bytes'], 'sha256': row['sha256']},
                    'original replay output changed during association')
        out.verify()
        receipt.update(status='pass', completed_checks=CHECKS[mode], all_checks_complete=True,
            association_outputs=list(out.files.values()), association_output_bytes=out.total,
            elapsed_seconds=time.monotonic() - started, guard_attempts=attempts,
            authority={'source_authenticity_verified': False, 'primary_source_correspondence_verified': False,
                'semantic_agreement_verified': False, 'training_qualified': False, 'Lean_admitted': False,
                'historical_flat_occurrences_repaired': False, 'published': False},
            limitations=['Separate native parent evidence establishes admission, durability, stopped groups and release.',
                'Checked source buffers and Python operation guards are cooperative, not OS sandbox or kernel quota.',
                'Saved-artifact validation occurs in the same process; it is not fresh-interpreter replay.',
                'Discovery exposes every bounded literal candidate; selecting its IDs is only a later caller declaration.'])
        saved = g.save(logs / ('sampled-primary-' + mode + '-receipt.json'), receipt, directories)
        print(json.dumps({'mode': mode, 'status': 'pass', 'receipt': saved}, sort_keys=True))
        return 0
    except BaseException as error:
        receipt.update(status='failed', completed_checks=[], all_checks_complete=False,
            failure_stage=stage, error_type=type(error).__name__,
            error='Bounded sampled-primary failure; arbitrary product exception text omitted.',
            elapsed_seconds=time.monotonic() - started, guard_attempts=attempts,
            completed_association_outputs=list(out.files.values()),
            product_origin_diagnostics=g.product_diagnostics(root, pins, finder))
        g.save(logs / ('sampled-primary-' + mode + '-failed.json'), receipt, directories)
        raise RuntimeError('sampled primary failed at ' + stage) from None


if __name__ == '__main__':
    raise SystemExit(main())

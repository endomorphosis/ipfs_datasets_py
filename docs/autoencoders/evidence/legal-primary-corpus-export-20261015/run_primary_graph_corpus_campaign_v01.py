"""Export OR independently replay primary graph inputs inside a native child.

The native parent owns admission, supervision, sealing and release. Export and
validation require separate frozen requests/configurations. No pytest case or
legal, training, publication or proof authority is manufactured here.
"""
from __future__ import annotations

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


PHASE = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-corpus-export-20261015-01')
GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
GUARD_SHA256 = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
PROFILE = 'manifest-selected-primary-entry-cid-canonical-parquet-2gib/v1'
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
OUTPUT_NAME = 'candidate-generation-v01'
INPUT_ROLES = frozenset({'raw_manifest', 'accepted_selection', 'selection_options',
    'accepted_reconstruction_report', 'input_custody', 'historical_completion'})
CHECKS = {
    'export': ['rebuild_independently_pinned_primary_selection',
        'export_complete_primary_population_2gib', 'verify_source_and_product_origin_closure'],
    'validate': ['rebuild_independently_pinned_primary_selection',
        'validate_original_bound_candidate_generation', 'verify_source_and_product_origin_closure'],
}
FALSE_AUTHORITY = dict.fromkeys(('admitted', 'formalized', 'source_semantics_verified',
    'semantic_review_verified', 'training_qualified', 'proof_authority',
    'accepted_graph_view_enabled', 'published', 'historical_flat_occurrences_repaired',
    'source_population_equivalence_verified'), False)
CONTROLLED_EXPORT_MESSAGES = frozenset({'lineage byte bound exceeded',
    'complete staged export exceeds aggregate byte bound',
    'reconstruction companion exceeds byte bound', 'complete export byte bound exceeded',
    'export shard bound exceeded', 'encoded Parquet exceeds byte bound',
    'export manifest exceeds byte bound', 'complete source population exceeds export row bound'})


CONTROLLED_HELPER_MESSAGES = frozenset({
    'accepted finite input descriptor required',
    'accepted historical candidate commitment differs',
    'accepted producer manifest changed before validation',
    'accepted producer path and external manifest expectation differ',
    'closed campaign config required',
    'closed unique producer filename required',
    'complete producer result required',
    'consumer altered producer manifest, inventory or file metadata',
    'consumer must pin unchanged producer product owners',
    'driver, guard and config native pins required',
    'exact finite candidate manifest required',
    'exact metadata descriptor required',
    'exact named artifact checks required',
    'exact native child argv and cwd required',
    'exact native writable layout required',
    'exact retained guard source required',
    'export cannot invent consumer acceptance',
    'extra child process refused during corpus export',
    'finite producer inventory required',
    'fresh original-bound public validation required',
    'fresh product import process required',
    'fresh retained guard module required',
    'guard source parent is aliased',
    'independently accepted producer receipt required',
    'metadata differs from accepted descriptor',
    'metadata must have a frozen native pin',
    'native redirects required',
    'native validation request required',
    'network operation refused during corpus export',
    'network or child attempt occurred even if caught',
    'nonoptimized no-bytecode Python required',
    'phase config differs from its frozen native pin',
    'physical producer generation required',
    'physical selected checkout required',
    'producer directory changed during witness',
    'producer file set differs from accepted manifest',
    'producer file type, links or bytes changed',
    'rebuilt selection differs from independently accepted complete selection',
    'redirects or Arrow limits changed',
    'request or config changed',
    'request path and campaign config path required',
    'retained guard source changed',
    'selected checkout identity changed',
    'selected reconstruction differs from accepted historical stream',
    'selection options and accepted descriptor differ',
    'separately frozen consumer manifest SHA required',
    'unexpected producer entry',
})

def controlled_failure_message(error, g, exporter):
    if type(error) is RuntimeError and str(error) in CONTROLLED_HELPER_MESSAGES:
        return str(error)
    if type(error) is g.QualificationFailure and str(error) in g.CONTROLLED_FAILURE_MESSAGES:
        return str(error)
    if exporter is not None and type(error) is exporter.PrimaryGraphExportError and str(error) in CONTROLLED_EXPORT_MESSAGES:
        return str(error)
    return None


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
    """Only stdlib definitions execute; the retained pytest main is not called."""
    need(not sys.flags.optimize and sys.dont_write_bytecode, 'nonoptimized no-bytecode Python required')
    for parent in (GUARD.parent, *GUARD.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), 'guard source parent is aliased')
    with os.fdopen(os.open(GUARD, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        before = os.fstat(f.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_size == 28529, 'exact retained guard source required')
        raw = f.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(f.fileno())
    identity = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_size, v.st_mtime_ns, v.st_ctime_ns, v.st_nlink)
    need(identity(before) == identity(after) == identity(GUARD.lstat())
        and sha(raw) == GUARD_SHA256, 'retained guard source changed')
    name = '_primary_graph_corpus_checked_guard_v01'
    need(name not in sys.modules, 'fresh retained guard module required')
    module = types.ModuleType(name)
    module.__file__ = str(GUARD)
    sys.modules[name] = module
    exec(compile(raw, str(GUARD), 'exec', dont_inherit=True, optimize=0), module.__dict__)
    return module


def checked_input(g, descriptor, pins):
    need(type(descriptor) is dict and set(descriptor) == {'path', 'bytes', 'sha256'},
        'exact metadata descriptor required')
    path = Path(descriptor['path'])
    need(path.is_absolute() and type(descriptor['bytes']) is int
        and 0 < descriptor['bytes'] <= MAX_INPUT_BYTES
        and type(descriptor['sha256']) is str
        and re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256'])
        and pins.get(str(path)) == descriptor['sha256'], 'metadata must have a frozen native pin')
    raw = g.snapshot(path, MAX_INPUT_BYTES)
    need(pin(path, raw) == descriptor, 'metadata differs from accepted descriptor')
    return raw


def generation_witness(g, generation, manifest, expected_manifest):
    """Bounded metadata witness only; the public validator owns body hashing."""
    g.physical_parents(generation / '__generation_identity_only__')
    before = generation.lstat()
    need(stat.S_ISDIR(before.st_mode), 'physical producer generation required')
    descriptors = manifest['files']
    need(type(descriptors) is list and len(descriptors) <= 1026, 'finite producer inventory required')
    sizes = {'manifest.json': expected_manifest['bytes']}
    for d in descriptors:
        name = d['path']
        need(type(name) is str and Path(name).name == name and name not in sizes
            and type(d['bytes']) is int and d['bytes'] > 0, 'closed unique producer filename required')
        sizes[name] = d['bytes']
    names = set()
    with os.scandir(generation) as entries:
        for item in entries:
            need(len(names) < len(sizes) and item.name not in names, 'unexpected producer entry')
            names.add(item.name)
    need(names == set(sizes), 'producer file set differs from accepted manifest')
    rows = []
    for name in sorted(names):
        info = (generation / name).lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == sizes[name],
            'producer file type, links or bytes changed')
        rows.append([name, *g.identity(info)])
    after = generation.lstat()
    need(g.identity(before) == g.identity(after), 'producer directory changed during witness')
    return {'directory_device': before.st_dev, 'directory_inode': before.st_ino,
        'file_count': len(names), 'total_bytes': sum(sizes.values()),
        'ordered_file_metadata_sha256': sha(wire(rows))}


def historical_comparison(report, baseline, descriptor):
    # Excluded inventory is an observation, not selected membership. It can have
    # changed since the old phase without changing the pinned selected stream.
    critical = ('selection_sha256', 'manifest_sha256', 'selected_files_sha256',
        'rows', 'family_row_counts', 'decoder_disposition_counts', 'decoder_issue_counts',
        'identity_census', 'identity_status_counts', 'endpoint_counts', 'disposition_counts',
        'ordered_population_sha256', 'ordered_candidate_rows_sha256',
        'candidate_sha256', 'candidate_bytes', 'candidate_lines', 'blockers',
        'population_complete', 'endpoint_integrity_passed')
    matches = {key: wire(report[key]) == wire(baseline[key]) for key in critical}
    need(all(matches.values()), 'selected reconstruction differs from accepted historical stream')
    need(report['candidate_bytes'] == descriptor['historical_reconstruction_candidate_bytes']
        and report['candidate_sha256'] == descriptor['historical_reconstruction_candidate_sha256'],
        'accepted historical candidate commitment differs')
    return {'selected_stream_invariants': matches, 'all_selected_stream_invariants_match': True,
        'complete_report_canonical_equality': wire(report) == wire(baseline),
        'old_extra_file_count': baseline['source_verification']['extra_file_count'],
        'fresh_extra_file_count': report['source_verification']['extra_file_count'],
        'excluded_inventory_canonical_equality': wire(report['source_verification']['extras'])
            == wire(baseline['source_verification']['extras']),
        'scope': 'Engineering retention of exactly selected original rows; no legal currentness, semantic or historical flat-cache equivalence.'}


def main():
    need(len(sys.argv) == 3, 'request path and campaign config path required')
    g = load_guard()
    request_path, config_path = map(Path, sys.argv[1:])
    request_raw = g.snapshot(request_path, MAX_RECEIPT_BYTES)
    request = g.decode(request_raw)
    need(type(request) is dict and request.get('schema') == 'owned-validation-request/v1',
        'native validation request required')
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    need(root.is_absolute() and root == Path.cwd() and attempt.is_absolute()
        and request['argv'] == [sys.executable, '-B', str(Path(__file__).absolute()),
            str(request_path), str(config_path)], 'exact native child argv and cwd required')
    layout = {name: str(attempt / name) for name in g.OUTPUT_NAMES}
    need(request['outputs'] == layout and request['declared_external_writable_paths'] == []
        and request['process_scope'] == 'isolated_process_group', 'exact native writable layout required')
    directories = {}
    for path in (attempt, *(Path(p) for p in layout.values())):
        info = path.lstat()
        directories[path] = (info.st_dev, info.st_ino)
    g.directory_guard(directories)
    root_info = root.lstat()
    need(stat.S_ISDIR(root_info.st_mode), 'physical selected checkout required')
    root_identity = (root_info.st_dev, root_info.st_ino)
    pins = request['source_sha256']
    need(pins.get(str(GUARD)) == GUARD_SHA256
        and str(Path(__file__).absolute()) in pins and str(config_path) in pins,
        'driver, guard and config native pins required')
    g.code_guard(pins)
    config_raw = g.snapshot(config_path, MAX_INPUT_BYTES)
    need(sha(config_raw) == pins[str(config_path)] and config_path.parent == PHASE,
        'phase config differs from its frozen native pin')
    config = g.decode(config_raw)
    need(type(config) is dict and set(config) == {'schema', 'mode', 'input_descriptor',
        'accepted_producer_receipt', 'expected_export_manifest_sha256'}
        and config['schema'] == 'legal-primary-corpus-campaign/v1'
        and config['mode'] in CHECKS, 'closed campaign config required')
    mode = config['mode']
    need(request['selected_checks'] == CHECKS[mode], 'exact named artifact checks required')
    if mode == 'export':
        need(config['accepted_producer_receipt'] is None
            and config['expected_export_manifest_sha256'] is None, 'export cannot invent consumer acceptance')
    else:
        need(type(config['expected_export_manifest_sha256']) is str
            and re.fullmatch(r'[0-9a-f]{64}', config['expected_export_manifest_sha256']),
            'separately frozen consumer manifest SHA required')
    need(os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'
        and os.environ.get('TMPDIR') == layout['tmp']
        and os.environ.get('XDG_CACHE_HOME') == layout['cache'], 'native redirects required')
    redirects = dict(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'], SQLITE_TMPDIR=layout['db'],
        XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'], HF_HUB_CACHE=layout['cache'],
        HUGGINGFACE_HUB_CACHE=layout['cache'], HF_DATASETS_CACHE=layout['cache'],
        TRANSFORMERS_CACHE=layout['cache'], SENTENCE_TRANSFORMERS_HOME=layout['cache'])
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
            raise RuntimeError('network operation refused during corpus export')
        if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
            attempts['child_process'] += 1
            raise RuntimeError('extra child process refused during corpus export')
    sys.addaudithook(audit)
    receipt = {'schema': 'legal-primary-corpus-' + ('export-producer' if mode == 'export' else 'original-bound-validation') + '/v1',
        'status': 'failed', 'mode': mode, 'request': pin(request_path, request_raw),
        'config': pin(config_path, config_raw), 'attempt_directory': str(attempt),
        'authority': dict(FALSE_AUTHORITY), 'selected_checks': CHECKS[mode], 'completed_checks': [],
        'pytest_testcases_executed': 0, 'native_parent_owns_admission_supervision_seal_and_release': True}
    logs, exports = Path(layout['logs']), Path(layout['exports'])
    stage, started = 'authenticated_metadata', time.monotonic()
    exporter = None
    try:
        descriptor_raw = checked_input(g, config['input_descriptor'], pins)
        descriptor = g.decode(descriptor_raw)
        need(descriptor['schema'] == 'legal-primary-corpus-export-input/v1'
            and descriptor['new_export_profile'] == PROFILE
            and descriptor['selected_row_count'] == 297825 and descriptor['selected_file_count'] == 74
            and descriptor['selected_total_file_bytes'] == 46241258
            and set(descriptor['inputs']) == INPUT_ROLES
            and all(value is False for value in descriptor['authority'].values()), 'accepted finite input descriptor required')
        raw_inputs = {role: checked_input(g, desc, pins) for role, desc in descriptor['inputs'].items()}
        options = g.decode(raw_inputs['selection_options'])
        accepted = g.decode(raw_inputs['accepted_selection'])
        baseline = g.decode(raw_inputs['accepted_reconstruction_report'])
        need(options['expected_manifest_sha256'] == descriptor['expected_manifest_sha256']
            and options['repository'] == descriptor['repository'] and options['revision'] == descriptor['revision']
            and wire(options['expected_graph_population']) == wire(descriptor['expected_graph_population']),
            'selection options and accepted descriptor differ')
        stage = 'checked_product_imports'
        import pyarrow as arrow
        arrow.set_cpu_count(1)
        arrow.set_io_thread_count(1)
        from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as manifests
        from ipfs_datasets_py.logic.autoformal import legal_primary_graph_export as exporter
        selection = manifests.select_primary_graph_manifest(raw_inputs['raw_manifest'], **options)
        need(wire(selection) == wire(accepted)
            and selection['selection_sha256'] == descriptor['expected_selection_sha256']
            and selection['selected_row_count'] == descriptor['selected_row_count']
            and selection['selected_file_count'] == descriptor['selected_file_count']
            and sum(d['size_bytes'] for d in selection['descriptors']) == descriptor['selected_total_file_bytes'],
            'rebuilt selection differs from independently accepted complete selection')
        kwargs = dict(expected_selection_sha256=descriptor['expected_selection_sha256'],
            blobs_root=descriptor['blobs_root'], profile=PROFILE)
        stage = mode + '_original_bound_generation'
        print(json.dumps({'mode': mode, 'stage': stage, 'selected_rows': 297825}, sort_keys=True), flush=True)
        if mode == 'export':
            generation = exports / OUTPUT_NAME
            result = exporter.export_primary_graph(selection, descriptor['snapshot_root'], generation, **kwargs)
            need(result['status'] == 'candidate_export_complete', 'complete producer result required')
            expected_manifest_sha = result['manifest_sha256']
        else:
            producer_raw = checked_input(g, config['accepted_producer_receipt'], pins)
            producer = g.decode(producer_raw)
            need(producer['schema'] == 'legal-primary-corpus-export-producer/v1'
                and producer['status'] == 'pass' and producer['mode'] == 'export'
                and producer['completed_checks'] == CHECKS['export']
                and producer['input_descriptor'] == config['input_descriptor']
                and all(value is False for value in producer['authority'].values()), 'independently accepted producer receipt required')
            expected_manifest_sha = config['expected_export_manifest_sha256']
            generation = Path(producer['generation']['path'])
            need(generation == Path(producer['attempt_directory']) / 'exports' / OUTPUT_NAME
                and attempt not in generation.parents and generation != attempt
                and producer['generation']['manifest']['sha256'] == expected_manifest_sha,
                'accepted producer path and external manifest expectation differ')
            for original in producer['loaded_product_source_origins'].values():
                need(pins.get(original['path']) == original['sha256'], 'consumer must pin unchanged producer product owners')
            before_raw = g.snapshot(generation / 'manifest.json', MAX_RECEIPT_BYTES)
            need(sha(before_raw) == expected_manifest_sha, 'accepted producer manifest changed before validation')
            before_manifest = g.decode(before_raw)
            witness_before = generation_witness(g, generation, before_manifest, pin(generation / 'manifest.json', before_raw))
            result = exporter.validate_primary_graph_export(generation,
                expected_manifest_sha256=expected_manifest_sha, selection=selection,
                snapshot_root=descriptor['snapshot_root'], replay_parent=Path(layout['tmp']), **kwargs)
            need(result['status'] == 'candidate_export_verified' and result['fresh_original_replay_performed'] is True,
                'fresh original-bound public validation required')
            receipt['accepted_producer_receipt'] = config['accepted_producer_receipt']
            receipt['consumer_owned_replay_parent'] = layout['tmp']
        manifest_raw = g.snapshot(generation / 'manifest.json', MAX_RECEIPT_BYTES)
        manifest = g.decode(manifest_raw)
        manifest_pin = pin(generation / 'manifest.json', manifest_raw)
        need(manifest_pin['sha256'] == expected_manifest_sha and wire(manifest) == wire(result['manifest'])
            and manifest['profile'] == PROFILE and manifest['source_rows'] == descriptor['selected_row_count']
            and manifest['limits'] == {**exporter.DEFAULT_LIMITS, 'max_output_bytes': 2 * 1024**3}
            and manifest['source_selection_sha256'] == descriptor['expected_selection_sha256']
            and manifest['source_manifest_sha256'] == descriptor['expected_manifest_sha256']
            and manifest['authority'] == FALSE_AUTHORITY, 'exact finite candidate manifest required')
        reconstruction_raw = g.snapshot(generation / 'reconstruction.json', MAX_RECEIPT_BYTES)
        report = g.decode(reconstruction_raw)
        comparison = historical_comparison(report, baseline, descriptor)
        witness_after = generation_witness(g, generation, manifest, manifest_pin)
        if mode == 'validate':
            need(manifest_raw == before_raw and witness_after == witness_before,
                'consumer altered producer manifest, inventory or file metadata')
            receipt['producer_inventory_metadata_unchanged'] = True
            receipt['public_validator_checks_all_companion_sizes_hashes_and_file_set_before_and_after_replay'] = True
        receipt.update(input_descriptor=config['input_descriptor'], input_metadata=descriptor['inputs'],
            profile=PROFILE, selection_sha256=selection['selection_sha256'],
            generation={'path': str(generation), 'manifest': manifest_pin,
                'file_count': witness_after['file_count'], 'total_bytes': witness_after['total_bytes'],
                'source_rows': manifest['source_rows'], 'exported_rows': manifest['exported_rows'],
                'lineage_only_rows': manifest['lineage_only_rows'], 'quarantined_rows': manifest['quarantined_rows'],
                'structural_endpoint_integrity_passed': manifest['structural_endpoint_integrity_passed']},
            producer_generation_metadata_witness=witness_after,
            fresh_reconstruction_report=pin(generation / 'reconstruction.json', reconstruction_raw),
            historical_selected_stream_comparison=comparison)
        stage = 'closing_native_request_and_config'
        need(g.snapshot(request_path, MAX_RECEIPT_BYTES) == request_raw
            and g.snapshot(config_path, MAX_INPUT_BYTES) == config_raw, 'request or config changed')
        stage = 'closing_frozen_source_pins'
        g.code_guard(pins)
        stage = 'closing_native_output_directory_identities'
        g.directory_guard(directories)
        stage = 'closing_forbidden_loaded_modules'
        g.no_forbidden_modules()
        stage = 'closing_product_source_origins'
        receipt['loaded_product_source_origins'] = g.product_origins(root, pins, finder)
        stage = 'closing_source_checkout_identity'
        need(Path.cwd() == root and (root.lstat().st_dev, root.lstat().st_ino) == root_identity,
            'selected checkout identity changed')
        stage = 'closing_redirects_and_arrow_limits'
        need(tempfile.tempdir == layout['tmp'] and all(os.environ.get(k) == v for k, v in redirects.items())
            and arrow.cpu_count() == arrow.io_thread_count() == 1, 'redirects or Arrow limits changed')
        stage = 'closing_network_and_child_attempts'
        need(not any(attempts.values()), 'network or child attempt occurred even if caught')
        receipt.update(status='pass', completed_checks=CHECKS[mode], all_checks_complete=True,
            guard_attempts=attempts, elapsed_seconds=time.monotonic() - started,
            dependency_versions={'pyarrow': arrow.__version__,
                'numpy': getattr(sys.modules.get('numpy'), '__version__', None)},
            product_router_discovery_only=finder.router_probes,
            limitations=['Native parent evidence, not this child, establishes admission, final durability, group stop and lease/storage release.',
                'Python network/process audit and writable redirects are cooperative, not an OS sandbox or kernel quota.',
                'The retained release is engineering input; source legal currentness and historical flat-cache occurrence correspondence are unestablished.',
                'No semantic review, statutory training mask, accepted graph, model, publication or Lean authority is granted.'])
        receipt_name = 'corpus-export-producer.json' if mode == 'export' else 'corpus-original-bound-validation.json'
        saved = g.save(logs / receipt_name, receipt, directories)
        print(json.dumps({'status': 'pass', 'mode': mode, 'receipt': saved}, sort_keys=True))
        return 0
    except BaseException as error:
        receipt.update(status='failed', all_checks_complete=False, completed_checks=[],
            failure_stage=stage, error_type=type(error).__name__,
            controlled_failure_message=controlled_failure_message(error, g, exporter),
            error='Bounded campaign failure; arbitrary product exception text omitted.',
            guard_attempts=attempts, elapsed_seconds=time.monotonic() - started)
        receipt['product_origin_diagnostics_at_failure'] = g.product_diagnostics(root, pins, finder)
        g.save(logs / ('corpus-' + mode + '-failed.json'), receipt, directories)
        raise RuntimeError('primary corpus campaign failed at ' + stage) from None


if __name__ == '__main__':
    raise SystemExit(main())

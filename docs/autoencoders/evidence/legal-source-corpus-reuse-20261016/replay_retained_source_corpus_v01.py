"""Replay retained source artifacts inside one genuine native owned child.

The unchanged parent owns admission, process custody, sealing and release.
This worker opens no catalog, generates no embeddings and confers no authority.
"""
from __future__ import annotations

from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time


HELPER_RELATIVE = 'docs/autoencoders/evidence/legal-relational-target-contract-20261016/run_qualification.py'
HELPER_SHA256 = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
INPUT_SCHEMA = 'legal-retained-source-corpus-reuse-inputs/v1'
REPORT_SCHEMA = 'legal-retained-source-corpus-reuse/v1'
SELECTED_SCHEMA = 'legal-retained-source-companions/v1'
HISTORICAL_REVISION = '5016b86a273ce5e4ffd066c5ae9f5fe494dd417e'
MANIFEST_SHA256 = '0c6c05582fda19f36c75b166c5c1afecdab156241ce73728f564802b52eacac6'
RELEASE_ID = 'hf:justicedao/ipfs_uscode@' + HISTORICAL_REVISION + '#manifest-sha256:' + MANIFEST_SHA256
OUTPUT_NAMES = ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')
CHECKS = ('inventory_and_frozen_partitions', 'captured_source_version',
    'original_package_binding', 'complete_ordered_source_rows',
    'declared_physical_source_companions', 'closing_custody_and_runtime_guards')
MAX_METADATA = 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_SELECTED_ROWS = 256
FALSE_FLAGS = dict.fromkeys(('authority_granted', 'admitted', 'formalized',
    'training_eligible', 'gold_eligible', 'source_authority_authenticated',
    'source_semantics_verified', 'legal_meanings_reviewed', 'training_performed',
    'models_loaded', 'embedding_inference_performed', 'Lean_executed',
    'Lean_admitted', 'publication_performed', 'database_opened'), False)


class ReplayFailure(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise ReplayFailure(message)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')


def bootstrap_snapshot(path, maximum):
    """Read only bounded bootstrap metadata before the reused helper exists."""
    path = Path(path)
    need(path.is_absolute(), 'absolute bootstrap path required')
    for parent in (path.parent, *path.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), 'physical bootstrap parents required')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and 0 < before.st_size <= maximum, 'bounded bootstrap input required')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
        item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    need(len(raw) == before.st_size and identity(before) == identity(after)
        == identity(path.lstat()), 'bootstrap input changed')
    return raw


def artifact(value, maximum, q):
    need(type(value) is dict and set(value) == {'path', 'sha256', 'bytes'},
        'closed artifact descriptor required')
    need(type(value['path']) is str and Path(value['path']).is_absolute()
        and str(Path(value['path'])) == value['path'] and '..' not in Path(value['path']).parts,
        'absolute ordinary artifact path required')
    need(type(value['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', value['sha256'])
        and type(value['bytes']) is int and 0 < value['bytes'] <= maximum,
        'bounded artifact identity required')
    q.physical_parents(Path(value['path']))
    return dict(value)


def file_identity(path, q):
    path = Path(path)
    q.physical_parents(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        'single-link ordinary input required')
    return q.identity(info)


def fingerprint(reference, q):
    """Stream a bounded exact artifact without retaining another large buffer."""
    path = Path(reference['path'])
    before = file_identity(path, q)
    need(before[3] == reference['bytes'], 'input size differs')
    digest, count = hashlib.sha256(), 0
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        need(q.identity(os.fstat(stream.fileno())) == before, 'input identity differs at open')
        while raw := stream.read(1024 * 1024):
            count += len(raw)
            need(count <= reference['bytes'], 'input exceeds its declared bound')
            digest.update(raw)
        need(q.identity(os.fstat(stream.fileno())) == before, 'input changed during fingerprint')
    need(file_identity(path, q) == before and count == reference['bytes']
        and digest.hexdigest() == reference['sha256'], 'input fingerprint differs')
    return before


def directory_identity(path, q):
    path = Path(path)
    q.physical_parents(path / '__physical_directory_only__')
    info = path.lstat()
    need(stat.S_ISDIR(info.st_mode), 'ordinary input directory required')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns)


def save_output(path, value, q, directories, output_budget):
    q.directory_guard(directories)
    need(path.parent in directories, 'stable native output root required')
    raw = wire(value) + b'\n'
    need(output_budget['bytes'] + len(raw) <= MAX_OUTPUT_BYTES, 'complete output exceeds aggregate bound')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    need(q.snapshot(path, MAX_OUTPUT_BYTES) == raw, 'complete output readback differs')
    output_budget['bytes'] += len(raw)
    return {'path': str(path), 'sha256': q.sha(raw), 'bytes': len(raw)}


def main():
    need(len(sys.argv) == 3 and not sys.flags.optimize and sys.dont_write_bytecode,
        'native request, descriptor and nonoptimized no-bytecode Python required')
    request_path, input_path = map(Path, sys.argv[1:])
    request_raw = bootstrap_snapshot(request_path, MAX_METADATA)
    request = json.loads(request_raw)
    need(type(request) is dict and request.get('schema') == 'owned-validation-request/v1',
        'native request schema differs')
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    need(root.is_absolute() and root == Path.cwd(), 'selected checkout differs')
    helper_path = root / HELPER_RELATIVE
    helper_raw = bootstrap_snapshot(helper_path, 4 * 1024 * 1024)
    need(hashlib.sha256(helper_raw).hexdigest() == HELPER_SHA256
        and request['source_sha256'].get(str(helper_path)) == HELPER_SHA256,
        'reused guard helper differs')
    q = type(sys)('_retained_source_corpus_original_guards')
    q.__file__ = str(helper_path)
    exec(compile(helper_raw, str(helper_path), 'exec', dont_inherit=True, optimize=0), q.__dict__)
    original_forbidden_roots = sorted(q.FORBIDDEN_ROOTS)
    # The real source-package owner imports publisher definitions. Keep those
    # genuine optional definitions, while denying all network/process use.
    # This is a declared worker import profile; no native policy is changed.
    q.FORBIDDEN_ROOTS = q.FORBIDDEN_ROOTS - {'huggingface_hub'}
    # Strictly decode bootstrap metadata again through the unchanged helper.
    request = q.decode(request_raw)
    pins = request['source_sha256']
    need(str(Path(__file__).absolute()) in pins and str(input_path) in pins,
        'worker and independent input descriptor pins required')
    need(request['selected_checks'] == list(CHECKS), 'complete named replay checks required')
    need(request['argv'][1:] == ['-B', str(Path(__file__).absolute()), str(request_path), str(input_path)],
        'native child arguments differ')
    layout = {name: str(attempt / name) for name in OUTPUT_NAMES}
    need(request['outputs'] == layout and request['declared_external_writable_paths'] == []
        and request['process_scope'] == 'isolated_process_group', 'native output layout differs')
    directories = {}
    for path in (attempt, *(Path(value) for value in layout.values())):
        q.physical_parents(path / '__native_directory_only__')
        info = path.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0, 'private native directories required')
        directories[path] = (info.st_dev, info.st_ino)
    need(os.environ.get('TMPDIR') == layout['tmp'] and os.environ.get('XDG_CACHE_HOME') == layout['cache']
        and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1', 'native redirects differ')
    redirects = dict(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'], SQLITE_TMPDIR=layout['db'],
        XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'], HF_HUB_CACHE=layout['cache'],
        HUGGINGFACE_HUB_CACHE=layout['cache'], HF_DATASETS_CACHE=layout['cache'],
        TRANSFORMERS_CACHE=layout['cache'], SENTENCE_TRANSFORMERS_HOME=layout['cache'])
    os.environ.update(redirects, IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0',
        IPFS_AUTO_INSTALL='false', IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0', HF_HUB_OFFLINE='1',
        HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', BLIS_NUM_THREADS='1',
        VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = layout['tmp']
    report = dict(schema=REPORT_SCHEMA, status='failed', all_checks_complete=False,
        request_sha256=q.sha(request_raw), input_descriptor_sha256=pins[str(input_path)],
        checks=[{'name': name, 'status': 'not_run'} for name in CHECKS],
        original_guard_helper={'path': str(helper_path), 'sha256': HELPER_SHA256},
        source_reuse_import_profile={'original_forbidden_roots': original_forbidden_roots,
            'current_forbidden_roots': sorted(q.FORBIDDEN_ROOTS),
            'only_allowed_optional_sdk_root': 'huggingface_hub',
            'identical_original_import_guard_claimed': False,
            'publisher_or_hub_client_construction_requested_by_worker': False,
            'hub_upload_or_download_requested_by_worker': False},
        historical_dataset_revision=HISTORICAL_REVISION,
        native_parent_owns_admission_supervision_seal_and_release=True,
        seccomp_invoked=False, os_network_isolation_attested=False,
        seccomp_omission_reason='The existing resolver may spawn ldconfig, incompatible with this one-child profile.',
        scope='Retained published source/package integrity and exposed source companions; no normative targets.',
        **FALSE_FLAGS)
    attempts = {'network': 0, 'child_process': 0, 'external_write': 0, 'database': 0}
    finder, stage = None, 'bootstrap_source_guard'
    output_budget = {'bytes': 0}
    started = time.monotonic()
    try:
        q.code_guard(pins)
        q.no_forbidden_modules()
        need(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
            'cold product import required')
        root_identity = directory_identity(root, q)
        input_raw = q.snapshot(input_path, MAX_METADATA)
        need(q.sha(input_raw) == pins[str(input_path)], 'independent descriptor differs')
        input_identity = file_identity(input_path, q)
        inputs = q.decode(input_raw)
        need(type(inputs) is dict and set(inputs) == {'schema', 'inventory', 'partitions',
            'captured_version_report', 'package', 'selected_legal_ids'} and inputs['schema'] == INPUT_SCHEMA,
            'closed reuse input schema required')
        inventory_ref = artifact(inputs['inventory'], 64 * 1024 * 1024, q)
        partition_ref = artifact(inputs['partitions'], 64 * 1024 * 1024, q)
        captured_ref = artifact(inputs['captured_version_report'], MAX_METADATA, q)
        package = inputs['package']
        need(type(package) is dict and set(package) == {'path', 'manifest', 'expected_file_count', 'expected_total_bytes'}
            and package['expected_file_count'] == 103 and package['expected_total_bytes'] == 263671066,
            'exact retained package descriptor required')
        package_root = Path(package['path'])
        need(type(package['path']) is str and package_root.is_absolute()
            and str(package_root) == package['path'] and '..' not in package_root.parts,
            'ordinary retained package path required')
        need(type(package['manifest']) is dict and set(package['manifest']) == {'sha256', 'bytes'},
            'closed package manifest identity required')
        artifact({'path': str(package_root / 'source-export.json'), **package['manifest']}, 4 * 1024 * 1024, q)
        selected_ids = inputs['selected_legal_ids']
        need(type(selected_ids) is list and len(selected_ids) == len(set(selected_ids)) == 3
            and all(type(value) is str and 0 < len(value.encode('utf-8')) <= 4096 for value in selected_ids),
            'three exact declared legal IDs required')
        need(not package_root.is_relative_to(attempt) and not attempt.is_relative_to(package_root)
            and all(not Path(ref['path']).is_relative_to(attempt) for ref in (inventory_ref, partition_ref, captured_ref)),
            'input/output namespaces must be separate')
        sys.path.insert(0, str(root))
        finder = q.PinnedProductFinder(root, pins)
        sys.meta_path.insert(0, finder)

        def audit(event, args):
            if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                    'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
                attempts['network'] += 1
                raise ReplayFailure('network operation refused')
            if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
                attempts['child_process'] += 1
                raise ReplayFailure('extra process refused')
            if event == 'sqlite3.connect':
                attempts['database'] += 1
                raise ReplayFailure('database connection refused')
            if event == 'open' and args:
                path, mode, flags = args
                writes = (type(mode) is str and any(symbol in mode for symbol in 'wax+')) or (
                    type(flags) is int and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
                if writes and not (type(path) in (str, bytes) and Path(os.fsdecode(path)).absolute().is_relative_to(attempt)):
                    attempts['external_write'] += 1
                    raise ReplayFailure('write outside native attempt refused')

        sys.addaudithook(audit)
        import pyarrow as arrow
        arrow.set_cpu_count(1)
        arrow.set_io_thread_count(1)
        input_refs = (inventory_ref, partition_ref, captured_ref)
        input_witnesses = {ref['path']: fingerprint(ref, q) for ref in input_refs}
        package_root_witness = directory_identity(package_root, q)

        stage = CHECKS[0]
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_inventory import load_uscode_source_inventory
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_partitions import load_source_partitions
        inventory = load_uscode_source_inventory(inventory_ref['path'], expected_sha256=inventory_ref['sha256'],
            expected_size_bytes=inventory_ref['bytes'])
        partitions = load_source_partitions(partition_ref['path'], expected_sha256=partition_ref['sha256'],
            expected_size_bytes=partition_ref['bytes'], inventory=inventory)
        inventory_summary, partition_summary = inventory.summary(), partitions.verification_summary()
        need(inventory_summary['release_id'] == RELEASE_ID and inventory_summary['declared_row_count'] == 62931
            and inventory_summary['declared_corpus_shards'] == 16 and inventory_summary['declared_corpus_closure_verified'] is True,
            'retained inventory population or provenance differs')
        report.update(inventory=inventory_ref, inventory_summary=inventory_summary,
            partitions=partition_ref, partition_summary=partition_summary)
        report['checks'][0]['status'] = 'passed'
        del partitions, inventory
        gc.collect()

        stage = CHECKS[1]
        from ipfs_datasets_py.duckdb_control.source_corpus_binding import (
            SourceCorpusBinding, SourceCorpusBindingError, validate_source_version)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_corpus_rows import ROW_FIELDS
        baseline = q.decode(q.snapshot(Path(captured_ref['path']), MAX_METADATA))
        captured_version = baseline['version_after_reopen']
        need(baseline['input_package'] == str(package_root)
            and captured_version['package_manifest_artifact'] == package['manifest']
            and captured_version['row_count'] == 62931, 'captured source package differs')
        detached = {key: value for key, value in captured_version.items() if key != 'package_directory'}
        validated = validate_source_version(detached)
        need(wire(validated) == wire(detached), 'captured public source version changed')
        refusals = {}
        for name in ('detached_authority_promotion', 'detached_version_id_substitution', 'detached_manifest_commitment_substitution'):
            changed = json.loads(wire(detached))
            if name == 'detached_authority_promotion':
                changed['qualification']['source_authority_authenticated'] = True
            elif name == 'detached_version_id_substitution':
                changed['version_id'] = 'sha256:' + '0' * 64
            else:
                changed['package_manifest_artifact']['sha256'] = '0' * 64
            try:
                validate_source_version(changed)
            except SourceCorpusBindingError:
                refusals[name] = 'refused'
            else:
                raise ReplayFailure('public source owner accepted changed detached commitment')
        report.update(captured_version_report=captured_ref, source_version=detached,
            public_owner_refusals=refusals)
        report['checks'][1]['status'] = 'passed'

        stage = CHECKS[2]
        binding = SourceCorpusBinding(captured_version, package_root)
        selected_rows, selected_counts = [], Counter()
        status_counts, embedding_counts, split_counts, alias_counts = Counter(), Counter(), Counter(), Counter()
        unique_inputs, eligible_rows, row_count, row_digest = set(), 0, 0, hashlib.sha256()
        with binding:
            need(binding.file_count == package['expected_file_count'] and binding.total_bytes == package['expected_total_bytes']
                and binding.manifest_artifact == package['manifest'], 'bound package closure differs')
            metadata = binding.manifest['metadata']
            need(metadata['release']['repo_id'] == 'justicedao/ipfs_uscode'
                and metadata['release']['revision'] == HISTORICAL_REVISION
                and metadata['release']['manifest']['sha256'] == MANIFEST_SHA256
                and metadata['inventory'] == {key: inventory_ref[key] for key in ('sha256', 'bytes')}
                and metadata['source_partitions'] == {key: partition_ref[key] for key in ('sha256', 'bytes')},
                'bound package provenance differs from retained artifacts')
            files = binding.file_descriptors
            package_witnesses = {item['relative_path']: file_identity(package_root / item['relative_path'], q) for item in files}
            report['package'] = dict(package, verified_file_count=binding.file_count,
                verified_total_bytes=binding.total_bytes, row_digest=binding.row_digest,
                file_descriptors=list(files))
            report['checks'][2]['status'] = 'passed'

            stage = CHECKS[3]
            selected_bytes = 0
            for row in binding.iter_rows():
                need(set(row) == {'ordinal', *ROW_FIELDS} and row['ordinal'] == row_count,
                    'complete physical source columns or ordering differ')
                need(row['admitted'] is False and row['formalized'] is False
                    and row['formalization_status'] == 'not_observed', 'source row authority changed')
                row_digest.update(wire(row) + b'\n')
                row_count += 1
                status_counts[row['source_status']] += 1
                embedding_counts[row['embedding_status']] += 1
                split_counts[row['split']] += 1
                alias_counts[row['eligible_alias_count']] += 1
                if row['source_eligible']:
                    eligible_rows += 1
                    unique_inputs.add(row['input_id'])
                if row['legal_id'] in selected_ids:
                    selected_bytes += len(wire(row))
                    need(len(selected_rows) < MAX_SELECTED_ROWS and selected_bytes <= MAX_OUTPUT_BYTES // 2,
                        'complete selected physical population exceeds source companion bound')
                    selected_rows.append(row)
                    selected_counts[row['legal_id']] += 1
            need(row_count == 62931 == binding.row_count and row_digest.hexdigest() == binding.row_digest,
                'complete ordered source digest differs')
            need(dict(split_counts) == partition_summary['partition_counts'],
                'original frozen source split totals differ')
            report['row_population'] = {'physical_rows': row_count, 'ordered_row_digest': row_digest.hexdigest(),
                'source_status_counts': dict(sorted(status_counts.items())),
                'embedding_status_counts': dict(sorted(embedding_counts.items())),
                'split_counts': [{'split': key, 'rows': value} for key, value in sorted(split_counts.items(), key=lambda pair: str(pair[0]))],
                'eligible_alias_count_distribution': [{'eligible_alias_count': key, 'rows': value} for key, value in sorted(alias_counts.items())],
                'source_eligible_physical_rows': eligible_rows, 'unique_eligible_input_ids': len(unique_inputs),
                'additional_eligible_alias_occurrences': eligible_rows - len(unique_inputs)}
            report['checks'][3]['status'] = 'passed'

            stage = CHECKS[4]
            report['selected_companions'] = {'requested_legal_ids': selected_ids, 'physical_rows': len(selected_rows),
                'counts': [{'legal_id': value, 'physical_rows': selected_counts[value],
                    'status': 'found_exposed_engineering_source' if selected_counts[value] else 'missing'} for value in selected_ids],
                'selection_policy': 'Exact declared legal_id equality; all matching physical occurrences; no fallback, normalization or deduplication.',
                'exposure_status': 'exposed', 'original_split_membership_preserved': True,
                'text_coordinate_space': 'exact published text field; distinct from official HTML/USLM and normalized visible text',
                'normative_target_selected': False, 'gold_mask': 0, 'training_mask': 0}
            report['checks'][4]['status'] = 'passed'
            stage = CHECKS[5]
            binding.verify_current()
            need(directory_identity(package_root, q) == package_root_witness
                and all(file_identity(package_root / name, q) == witness for name, witness in package_witnesses.items()),
                'package physical custody changed')
        try:
            binding.source_version
        except SourceCorpusBindingError:
            refusals['expired_binding_access'] = 'refused'
        else:
            raise ReplayFailure('expired public source binding remained usable')
        need(q.snapshot(request_path, MAX_METADATA) == request_raw
            and q.snapshot(input_path, MAX_METADATA) == input_raw and file_identity(input_path, q) == input_identity,
            'native request or input descriptor changed')
        need(all(fingerprint(ref, q) == input_witnesses[ref['path']] for ref in input_refs),
            'readonly artifact custody changed')
        q.code_guard(pins)
        q.directory_guard(directories)
        q.no_forbidden_modules()
        report['loaded_product_source_origins'] = q.product_origins(root, pins, finder)
        need(Path.cwd() == root and directory_identity(root, q) == root_identity,
            'source checkout physical identity changed')
        need(tempfile.tempdir == layout['tmp'] and all(os.environ.get(key) == value for key, value in redirects.items()),
            'native writable redirects changed')
        need(arrow.cpu_count() == arrow.io_thread_count() == 1, 'Arrow thread limits changed')
        need(not any(attempts.values()), 'denied runtime attempt occurred even if suppressed')
        report['checks'][5]['status'] = 'passed'
        companions = dict(schema=SELECTED_SCHEMA, source_version_id=detached['version_id'],
            package_manifest=package['manifest'], historical_dataset_revision=HISTORICAL_REVISION,
            requested_legal_ids=selected_ids, row_fields=['ordinal', *ROW_FIELDS], rows=selected_rows,
            exposure_status='exposed', original_split_membership_preserved=True,
            text_coordinate_space='exact decoded record_json.text; normalization none; distinct from official HTML/USLM',
            gold_mask=0, training_mask=0, **FALSE_FLAGS)
        report['selected_source_artifact'] = save_output(Path(layout['exports']) / 'selected-source-companions.json',
            companions, q, directories, output_budget)
        report.update(status='pass', all_checks_complete=True, guard_attempts=attempts,
            elapsed_seconds=time.monotonic() - started, input_fingerprints_and_physical_witnesses_unchanged=True,
            package_physical_witnesses_unchanged=True, source_pins_unchanged=True,
            dependency_versions={'pyarrow': arrow.__version__, 'numpy': getattr(sys.modules.get('numpy'), '__version__', None),
                'huggingface_hub': getattr(sys.modules.get('huggingface_hub'), '__version__', None),
                'requests': getattr(sys.modules.get('requests'), '__version__', None)},
            optional_sdk_definition_presence={'huggingface_hub': 'huggingface_hub' in sys.modules,
                'requests': 'requests' in sys.modules},
            hub_sdk_definition_modules_loaded=sorted(name for name in sys.modules
                if name == 'huggingface_hub' or name.startswith('huggingface_hub.')),
            arrow_thread_limits={'cpu': arrow.cpu_count(), 'io': arrow.io_thread_count()},
            limitations=['This verifies retained published source artifacts, not current Hub payloads or official-source authority.',
                'Selected companions are exposed engineering source inputs, not reviewed interpretations or normative gold.',
                'Original dataset revision, split, alias and embedding observations remain historical and unchanged.',
                'Python network/process auditing and readonly fingerprints are cooperative controls, not OS isolation or a filesystem quota.',
                'Only the genuine native parent can establish resource release and durable process closeout.'])
        report_ref = save_output(Path(layout['exports']) / 'source-corpus-reuse.json', report, q, directories, output_budget)
        print(json.dumps({'status': 'pass', 'report': report_ref, 'physical_rows': row_count,
            'selected_physical_rows': len(selected_rows), 'output_bytes': output_budget['bytes']}, sort_keys=True))
        return 0
    except BaseException as error:
        for check in report['checks']:
            if check['name'] == stage and check['status'] != 'passed':
                check['status'] = 'failed'
            elif check['status'] == 'not_run':
                check['blocked_by_failed_stage'] = stage
        report.update(status='failed', all_checks_complete=False, failure_stage=stage,
            error_type=type(error).__name__, arbitrary_exception_values_omitted=True,
            guard_attempts=attempts, elapsed_seconds=time.monotonic() - started)
        report['product_origin_diagnostics_at_failure'] = q.product_diagnostics(root, pins, finder)
        try:
            q.code_guard(pins)
            report['final_source_pins_unchanged'] = True
        except BaseException:
            report['final_source_pins_unchanged'] = False
        save_output(Path(layout['logs']) / 'source-corpus-reuse-failed.json', report, q, directories, output_budget)
        raise ReplayFailure('retained source corpus replay failed at ' + stage
            + ' (' + type(error).__name__ + ')') from None


if __name__ == '__main__':
    raise SystemExit(main())

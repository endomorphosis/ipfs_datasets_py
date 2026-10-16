"""Native-only paired diagnostics over two independently pinned retained requests."""
from pathlib import Path
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
import types

GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
GUARD_SHA = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
MAX_OUTPUT = 8 * 1024 * 1024
CHECKS = [
    'retained_original_request_and_native_export_custody',
    'current_root_public_relational_replay',
    'self_pair_identity_and_structure_controls',
    'competing_modal_scope_hypotheses_remain_distinct',
    'saved_comparison_public_revalidation',
    'independent_pin_and_resealed_comparison_refusals',
    'retained_selected_inputs_unchanged_and_final_source_guards',
]


def main():
    assert len(sys.argv) == 3 and sys.dont_write_bytecode and not sys.flags.optimize
    for parent in (GUARD.parent, *GUARD.parent.parents):
        assert stat.S_ISDIR(parent.lstat().st_mode)
    with os.fdopen(os.open(GUARD, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        guard_before = os.fstat(stream.fileno())
        assert stat.S_ISREG(guard_before.st_mode) and guard_before.st_nlink == 1
        assert 0 < guard_before.st_size <= 4 * 1024 * 1024
        raw_guard = stream.read(4 * 1024 * 1024 + 1)
        guard_after = os.fstat(stream.fileno())
    bootstrap_identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    assert len(raw_guard) == guard_before.st_size
    assert bootstrap_identity(guard_before) == bootstrap_identity(guard_after) == bootstrap_identity(GUARD.lstat())
    assert hashlib.sha256(raw_guard).hexdigest() == GUARD_SHA
    g = types.ModuleType('retained_comparison_checked_buffer_guard')
    g.__file__ = str(GUARD)
    exec(compile(raw_guard, str(GUARD), 'exec', dont_inherit=True, optimize=0), g.__dict__)
    request_path, config_path = map(Path, sys.argv[1:])
    request_raw = g.snapshot(request_path, g.MAX_METADATA_BYTES)
    request = g.decode(request_raw)
    assert request['schema'] == 'owned-validation-request/v1'
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    assert root == Path.cwd() and request['selected_checks'] == CHECKS
    assert request['declared_external_writable_paths'] == []
    assert request['process_scope'] == 'isolated_process_group'
    layout = {name: str(attempt / name) for name in g.OUTPUT_NAMES}
    assert request['outputs'] == layout
    directories = {}
    for directory in [attempt, *map(Path, layout.values())]:
        g.physical_parents(directory / '__directory_identity_only__')
        info = directory.lstat()
        assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
        assert stat.S_IMODE(info.st_mode) & 0o077 == 0
        directories[directory] = (info.st_dev, info.st_ino)
    assert os.environ['TMPDIR'] == layout['tmp']
    redirects = dict(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'],
        SQLITE_TMPDIR=layout['db'], XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'],
        HF_HUB_CACHE=layout['cache'], HUGGINGFACE_HUB_CACHE=layout['cache'],
        HF_DATASETS_CACHE=layout['cache'], TRANSFORMERS_CACHE=layout['cache'],
        SENTENCE_TRANSFORMERS_HOME=layout['cache'])
    os.environ.update(redirects, IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',
        IPFS_DATASETS_AUTO_INSTALL='0', IPFS_AUTO_INSTALL='false',
        IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0', HF_HUB_OFFLINE='1',
        HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
        BLIS_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = layout['tmp']
    pins = request['source_sha256']
    assert pins[str(GUARD)] == GUARD_SHA
    assert g.sha(g.snapshot(Path(__file__).absolute(), g.MAX_SOURCE_BYTES)) == pins[str(Path(__file__).absolute())]
    assert request['argv'] == [sys.executable, '-B', str(Path(__file__).absolute()), str(request_path), str(config_path)]
    g.code_guard(pins)
    g.no_forbidden_modules()
    assert not any(n == 'ipfs_datasets_py' or n.startswith('ipfs_datasets_py.') for n in sys.modules)
    config_raw = g.snapshot(config_path, g.MAX_METADATA_BYTES)
    assert g.sha(config_raw) == pins[str(config_path)]
    config = g.decode(config_raw)
    assert set(config) == {'schema', 'source_descriptor', 'producer_attempt_directory',
        'producer_file_index', 'producer_durability', 'producer_result',
        'producer_execution', 'retained_requests'}
    assert config['schema'] == 'legal-relational-reconstruction-retained-inputs/v1'
    old = Path(config['producer_attempt_directory'])
    g.physical_parents(old / '__directory_identity_only__')
    old_identity = (old.stat().st_dev, old.stat().st_ino)
    attempts = {'network': 0, 'child_process': 0}

    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
            attempts['network'] += 1
            raise RuntimeError('network refused')
        if event in {'subprocess.Popen', 'os.fork', 'os.forkpty', 'os.posix_spawn',
                'os.exec', 'os.system'}:
            attempts['child_process'] += 1
            raise RuntimeError('extra process refused')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and attempt not in path.parents:
                raise RuntimeError('write outside current native attempt refused')
        if event.startswith(('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.link', 'os.symlink')):
            for value in args[:2] if event in {'os.rename', 'os.link', 'os.symlink'} else args[:1]:
                if isinstance(value, (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(value)).absolute()
                    if path != attempt and attempt not in path.parents:
                        raise RuntimeError('mutation outside current native attempt refused')

    sys.addaudithook(audit)
    finder = g.PinnedProductFinder(root, pins)
    sys.meta_path.insert(0, finder)
    sys.path.insert(0, str(root))
    started = time.monotonic()
    observations = {}

    def read(descriptor, maximum=g.MAX_METADATA_BYTES):
        assert set(descriptor) == {'path', 'bytes', 'sha256'}
        path = Path(descriptor['path'])
        raw = g.snapshot(path, maximum)
        assert len(raw) == descriptor['bytes'] and g.sha(raw) == descriptor['sha256']
        info = path.lstat()
        row = dict(descriptor, device=info.st_dev, inode=info.st_ino, physical_identity=g.identity(info))
        if str(path) in observations:
            assert observations[str(path)] == row
        observations[str(path)] = row
        return raw

    source = g.decode(read(config['source_descriptor']))
    index = g.decode(read(config['producer_file_index']))
    seal_raw = read(config['producer_durability'])
    seal = g.decode(seal_raw)
    result_raw = read(config['producer_result'])
    result = g.decode(result_raw)
    execution = g.decode(read(config['producer_execution']))
    assert result['completed'] is True and result['returncode'] == 0
    assert execution['completed'] is True and execution['returncode'] == 0
    assert result['request_sha256'] == execution['request_sha256'] == seal['request_sha256']
    assert seal['result_sha256'] == g.sha(result_raw)
    sealed = {row['path']: row for row in seal['files']}
    indexed = {row['path']: row for row in index['files']}
    original = {row['name']: row for row in source['inputs']}
    raws = {}
    assert [row['name'] for row in config['retained_requests']] == ['A', 'B']
    for row in config['retained_requests']:
        name = row['name']
        reference = original['7213' + name + '_typed_request']
        assert row['original'] == {k: v for k, v in reference.items() if k != 'name'}
        export = row['export']
        path = Path(export['path'])
        assert path == old / 'exports' / ('original-7213' + name + '_typed_request.json')
        assert indexed[path.name] == {k: v for k, v in export.items() if k != 'path'} | {'path': path.name}
        raw, exported = read(row['original']), read(export)
        assert raw == exported
        info = observations[str(path)]
        assert sealed[str(path.relative_to(old))] == {k: info[k] for k in ['bytes', 'device', 'inode', 'sha256']} | {'path': str(path.relative_to(old))}
        raws[name] = raw
    completed = [CHECKS[0]]
    from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
    from ipfs_datasets_py.logic.autoformal import legal_relational_reconstruction_v1 as metric
    reports = {name: relational.prepare_relational_norm_v1(raw, expected_request_sha256=g.sha(raw)) for name, raw in raws.items()}
    for name, report in reports.items():
        assert relational.validate_relational_norm_v1(report, raws[name],
            expected_request_sha256=g.sha(raws[name]), expected_report_sha256=relational.relational_norm_report_sha256(report)) == report
    completed.append(CHECKS[1])
    outputs, total = [], 0

    def save_payload(name, value):
        nonlocal total
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode()
        total += len(raw)
        assert total <= MAX_OUTPUT
        g.directory_guard(directories)
        path = Path(layout['exports']) / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        assert g.snapshot(path, MAX_OUTPUT) == raw
        info = path.lstat()
        outputs.append({'path': str(path), 'bytes': len(raw), 'sha256': g.sha(raw),
            'device': info.st_dev, 'inode': info.st_ino, 'physical_identity': g.identity(info)})
        return raw

    for name, report in reports.items():
        save_payload('current-' + name + '-relational-report.json', report)
    comparisons, kwargs_by_pair = {}, {}
    for left, right in [('A', 'A'), ('B', 'B'), ('A', 'B'), ('B', 'A')]:
        key = left + right
        kwargs = dict(reference_request_raw=raws[left], candidate_request_raw=raws[right],
            expected_reference_request_sha256=g.sha(raws[left]), expected_candidate_request_sha256=g.sha(raws[right]),
            expected_reference_report_sha256=relational.relational_norm_report_sha256(reports[left]),
            expected_candidate_report_sha256=relational.relational_norm_report_sha256(reports[right]))
        comparisons[key] = metric.prepare_relational_reconstruction_comparison_v1(reports[left], reports[right], **kwargs)
        kwargs_by_pair[key] = kwargs
    assert all(all(comparisons[key]['comparisons'].values()) for key in ['AA', 'BB'])
    completed.append(CHECKS[2])
    for key in ['AB', 'BA']:
        row = comparisons[key]
        assert row['comparisons']['declared_structure_equal'] is False
        assert row['comparisons']['lexical_alpha_structure_equal'] is False
        assert any('modal_ancestry' in item['declared_differences'] or 'modal_operator' in item['declared_differences'] for item in row['feature_ledger'])
    completed.append(CHECKS[3])
    summaries = {}
    for key, comparison in comparisons.items():
        raw = save_payload(key + '-comparison.json', comparison)
        restored = g.decode(raw)
        assert metric.validate_relational_reconstruction_comparison_v1(restored, reports[key[0]], reports[key[1]],
            expected_comparison_sha256=metric.relational_reconstruction_comparison_sha256(comparison), **kwargs_by_pair[key]) == comparison
        assert not any(comparison['authority'].values())
        assert type(comparison['training_mask']) is type(comparison['evaluation_gold_mask']) is int
        assert comparison['training_mask'] == comparison['evaluation_gold_mask'] == 0
        summaries[key] = {'comparisons': comparison['comparisons'], 'feature_rows': len(comparison['feature_ledger']),
            'reference_only_paths': comparison['reference_only_paths'], 'candidate_only_paths': comparison['candidate_only_paths'],
            'declared_disagreement_paths': [r['typed_path'] for r in comparison['feature_ledger'] if r['declared_features_equal'] is False],
            'canonical_comparison_sha256': metric.relational_reconstruction_comparison_sha256(comparison)}
    completed.append(CHECKS[4])
    refused = []

    def refusal(name, operation):
        try:
            operation()
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError('required refusal missing')

    bad_kwargs = dict(kwargs_by_pair['AB'], expected_reference_request_sha256='0' * 64)
    refusal('wrong_independent_original_request_pin', lambda: metric.prepare_relational_reconstruction_comparison_v1(reports['A'], reports['B'], **bad_kwargs))
    tampered = g.decode(json.dumps(comparisons['AB']))
    tampered['comparisons']['lexical_alpha_structure_equal'] = True
    refusal('resealed_modal_disagreement_cannot_be_promoted', lambda: metric.validate_relational_reconstruction_comparison_v1(tampered,
        reports['A'], reports['B'], expected_comparison_sha256=metric.relational_reconstruction_comparison_sha256(tampered), **kwargs_by_pair['AB']))
    completed.append(CHECKS[5])
    for path, descriptor in list(observations.items()):
        read({k: descriptor[k] for k in ['path', 'bytes', 'sha256']})
    assert {path.name for path in Path(layout['exports']).iterdir()} == {Path(row['path']).name for row in outputs}
    assert len(outputs) == 6
    for output in outputs:
        path = Path(output['path'])
        raw = g.snapshot(path, MAX_OUTPUT)
        assert len(raw) == output['bytes'] and g.sha(raw) == output['sha256']
        assert g.identity(path.lstat()) == output['physical_identity']
    assert old_identity == (old.stat().st_dev, old.stat().st_ino)
    assert g.snapshot(config_path, g.MAX_METADATA_BYTES) == config_raw
    assert g.snapshot(request_path, g.MAX_METADATA_BYTES) == request_raw
    g.code_guard(pins)
    g.no_forbidden_modules()
    origins = g.product_origins(root, pins, finder)
    g.directory_guard(directories)
    assert all(os.environ.get(k) == v for k, v in redirects.items()) and tempfile.tempdir == layout['tmp']
    assert not any(attempts.values())
    completed.append(CHECKS[6])
    receipt = {'schema': 'legal-relational-reconstruction-retained-comparison-receipt/v1', 'status': 'pass',
        'request_sha256': g.sha(request_raw), 'config_sha256': g.sha(config_raw), 'selected_checks': CHECKS,
        'completed_checks': completed, 'all_checks_complete': completed == CHECKS, 'elapsed_seconds': time.monotonic() - started,
        'source_sha256': pins, 'loaded_product_source_origins': origins, 'guard_attempts': attempts,
        'retained_selected_input_observations': list(observations.values()), 'refusals': refused,
        'pair_summaries': summaries, 'outputs': outputs, 'output_files': len(outputs), 'output_bytes': total,
        'fresh_interpreter': True, 'saved_comparison_revalidation_separate_process': False,
        'old_producer_main_invoked': False, 'old_complete_tree_inventory_checked': False,
        'source_HTML_scope_or_join_replayed': False, 'authored_typed_request_count': 2,
        'human_review_created': False, 'training_performed': False, 'models_loaded': False,
        'Lean_executed': False, 'authority_granted': False, 'training_mask': 0, 'evaluation_gold_mask': 0,
        'native_parent_owns_final_closeout': True,
        'limitations': ['Two retained authored syntax requests are compared, not statutory truth or decoder predictions.',
            'Historical producer exports are checked against retained native file commitments; live resource state is not independently authenticated.',
            'Only selected original/export request files and metadata are rehashed before/after; no complete old tree immutability claim.',
            'A valid pair diagnostic has no malformed/missing/abstention corpus denominator or legal accuracy claim.',
            'Python guards are cooperative, not OS network isolation or filesystem quotas.']}
    pin = g.save(Path(layout['logs']) / 'retained-comparison-receipt.json', receipt, directories)
    print(json.dumps({'status': 'pass', 'receipt': pin, 'checks': len(completed), 'output_files': len(outputs), 'output_bytes': total}, sort_keys=True))


if __name__ == '__main__':
    main()

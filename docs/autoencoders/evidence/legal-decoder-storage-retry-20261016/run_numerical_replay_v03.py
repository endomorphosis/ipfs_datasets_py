"""Native-only, bounded replay of retained source-conditioned decoder interfaces.

This numerical profile deliberately allows local Torch/NumPy. It does not alter
the existing nonnumerical qualification guard or use its model-import finder.
"""
from pathlib import Path
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
import types

GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
GUARD_SHA = 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
CHECKS = ['retained_parent_and_donor_admission', 'bounded_four_row_source_controls',
          'all_generation_frozen_before_reference_scoring', 'fresh_private_reload_exact_numerical_replay',
          'candidate_only_output_compatibility', 'final_inputs_sources_and_native_layout_unchanged']
MAX_OUTPUT = 64 * 1024 * 1024


def main():
    assert len(sys.argv) == 3 and sys.dont_write_bytecode and not sys.flags.optimize
    # Bootstrap the unchanged, pinned stdlib source/file utilities only.
    for parent in (GUARD.parent, *GUARD.parent.parents):
        assert stat.S_ISDIR(parent.lstat().st_mode)
    with os.fdopen(os.open(GUARD, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4*1024*1024
        raw = stream.read(4*1024*1024+1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    assert identity(before) == identity(after) == identity(GUARD.lstat()) and len(raw) == before.st_size
    assert hashlib.sha256(raw).hexdigest() == GUARD_SHA
    g = types.ModuleType('numerical_replay_file_utilities')
    g.__file__ = str(GUARD)
    exec(compile(raw, str(GUARD), 'exec', dont_inherit=True, optimize=0), g.__dict__)
    request_path, config_path = map(Path, sys.argv[1:])
    request = g.decode(g.snapshot(request_path, g.MAX_METADATA_BYTES))
    root, attempt = Path(request['cwd']), Path(request['attempt_directory'])
    assert root == Path.cwd() and request['selected_checks'] == CHECKS
    assert request['memory_mb'] == 4096 and request['cpu_slots'] == 1 and request['child_process_slots'] == 2
    assert request['timeout_seconds'] == 1800 and request['storage_bytes'] == 268435456
    assert request['declared_external_writable_paths'] == [] and request['process_scope'] == 'isolated_process_group'
    assert request['argv'] == [sys.executable, '-B', str(Path(__file__).absolute()), str(request_path), str(config_path)]
    layout = {name: str(attempt / name) for name in g.OUTPUT_NAMES}
    assert request['outputs'] == layout and os.environ['TMPDIR'] == layout['tmp']
    directories = {}
    for path in [attempt, *map(Path, layout.values())]:
        g.physical_parents(path / '__directory_identity_only__')
        info = path.lstat()
        assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0
        directories[path] = (info.st_dev, info.st_ino)
    pins = request['source_sha256']
    assert pins[str(GUARD)] == GUARD_SHA
    assert pins[str(Path(__file__).absolute())] == g.sha(g.snapshot(Path(__file__).absolute(), g.MAX_SOURCE_BYTES))
    assert not any(n == 'ipfs_datasets_py' or n.startswith('ipfs_datasets_py.') for n in sys.modules)
    g.code_guard(pins)
    config_raw = g.snapshot(config_path, g.MAX_METADATA_BYTES)
    assert g.sha(config_raw) == pins[str(config_path)]
    config = g.decode(config_raw)
    assert config['schema'] == 'legal-decoder-small-numerical-replay/v1'
    assert set(config) == {'schema', 'retained_config', 'max_primary_rows', 'max_legacy_rows'}
    assert config['max_primary_rows'] == config['max_legacy_rows'] == 2
    os.environ.update(TMPDIR=layout['tmp'], TMP=layout['tmp'], TEMP=layout['tmp'], SQLITE_TMPDIR=layout['db'],
        XDG_CACHE_HOME=layout['cache'], HF_HOME=layout['cache'], HF_HUB_CACHE=layout['cache'],
        HUGGINGFACE_HUB_CACHE=layout['cache'], HF_DATASETS_CACHE=layout['cache'], TRANSFORMERS_CACHE=layout['cache'],
        SENTENCE_TRANSFORMERS_HOME=layout['cache'], IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',
        IPFS_DATASETS_AUTO_INSTALL='0', IPFS_AUTO_INSTALL='false', IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0',
        HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1', CUDA_VISIBLE_DEVICES='',
        OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', BLIS_NUM_THREADS='1',
        VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = layout['tmp']
    attempts = {'network': 0, 'child_process': 0}
    discovery_open, discovery_calls = [False], []
    system_paths = [Path('/usr/sbin/ldconfig'), Path('/usr/sbin/ldconfig.real'), Path('/usr/bin/dash')]
    system_identities = {}
    for path in system_paths:
        assert str(path) in pins and path.lstat().st_uid == 0
        assert g.sha(g.snapshot(path, g.MAX_SOURCE_BYTES)) == pins[str(path)]
        system_identities[str(path)] = identity(path.lstat())
    aliases = {Path('/sbin'): 'usr/sbin', Path('/bin'): 'usr/bin', Path('/usr/bin/sh'): 'dash'}
    alias_identities = {str(path): identity(path.lstat()) for path in aliases}
    null = Path('/dev/null')
    null_identity = (null.lstat().st_dev, null.lstat().st_ino, null.lstat().st_mode, null.lstat().st_rdev, null.lstat().st_uid)

    def discovery_guard():
        for path, target in aliases.items():
            info = path.lstat()
            assert stat.S_ISLNK(info.st_mode) and info.st_uid == 0 and os.readlink(path) == target
            assert identity(info) == alias_identities[str(path)]
        for path in system_paths:
            assert identity(path.lstat()) == system_identities[str(path)]
            assert g.sha(g.snapshot(path, g.MAX_SOURCE_BYTES)) == pins[str(path)]
        g.physical_parents(null)
        info = null.lstat()
        assert stat.S_ISCHR(info.st_mode) and info.st_uid == 0 and info.st_rdev == os.makedev(1, 3)
        assert (info.st_dev, info.st_ino, info.st_mode, info.st_rdev, info.st_uid) == null_identity

    discovery_guard()
    compiled, executed, opened = {}, [], {}
    historical = Path('/home/barberb/lift_coding/external/ipfs_datasets')
    assert root != historical and root not in historical.parents and historical not in root.parents
    for source_root in (root, historical):
        g.physical_parents(source_root / '__directory_identity_only__')
        assert stat.S_ISDIR(source_root.lstat().st_mode)
    assert (root.stat().st_dev, root.stat().st_ino) != (historical.stat().st_dev, historical.stat().st_ino)
    old_get_code = importlib.machinery.SourceFileLoader.get_code

    def checked_code(loader, fullname):
        path = Path(loader.path).absolute()
        if root in path.parents or historical in path.parents:
            assert str(path) in pins, 'unfrozen checkout source: ' + str(path)
            source_raw = g.snapshot(path, g.MAX_SOURCE_BYTES)
            assert g.sha(source_raw) == pins[str(path)]
            code = compile(source_raw, str(path), 'exec', dont_inherit=True, optimize=0)
            compiled[id(code)] = (code, str(path), pins[str(path)], fullname)
            return code
        return old_get_code(loader, fullname)

    # Covers normal imports and GTE's spec_from_file_location aliases; stale pyc
    # cannot bypass frozen source buffers. Third-party package integrity is not attested.
    importlib.machinery.SourceFileLoader.get_code = checked_code

    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                     'socket.gethostbyaddr', 'socket.bind', 'socket.sendto', 'socket.sendmsg'}:
            attempts['network'] += 1
            raise RuntimeError('network refused')
        if event == 'subprocess.Popen':
            frame = sys._getframe(1)
            options = frame.f_locals
            allowed = (discovery_open[0] and len(discovery_calls) < 4
                and args[0] == '/sbin/ldconfig' and args[1] == ['/sbin/ldconfig', '-p']
                and args[2] is None and args[3] == {'LC_ALL': 'C', 'LANG': 'C'}
                and frame.f_code.co_filename == '/usr/lib/python3.12/subprocess.py'
                and frame.f_code.co_name == '_execute_child'
                and options.get('shell') is False and options.get('start_new_session') is False
                and options.get('preexec_fn') is None and options.get('process_group') == -1
                and options.get('gid') is None and options.get('gids') is None and options.get('uid') is None
                and options.get('umask') == -1 and options.get('pass_fds') == ())
            if allowed:
                discovery_guard()
                discovery_calls.append({'executable': '/sbin/ldconfig', 'args': ['/sbin/ldconfig', '-p'],
                    'cwd': None, 'environment': {'LC_ALL': 'C', 'LANG': 'C'},
                    'shell': False, 'start_new_session': False, 'process_group': -1,
                    'canonical_wrapper': '/usr/sbin/ldconfig', 'canonical_binary': '/usr/sbin/ldconfig.real',
                    'canonical_interpreter': '/usr/bin/dash', 'purpose': 'installed_torch_libdl_discovery'})
                return
            attempts['child_process'] += 1
            raise RuntimeError('unapproved subprocess refused')
        if event in {'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.exec', 'os.system'}:
            attempts['child_process'] += 1
            raise RuntimeError('extra process refused')
        if event == 'import' and args[0].partition('.')[0] in {'transformers', 'sentence_transformers', 'huggingface_hub', 'datasets', 'tensorflow', 'jax'}:
            raise RuntimeError('encoder/download SDK refused')
        if event == 'exec':
            code = args[0]
            path = Path(code.co_filename)
            if path.is_absolute() and (root in path.parents or historical in path.parents):
                bound = compiled.get(id(code))
                assert bound is not None and bound[0] is code, 'unchecked checkout code execution'
                executed.append({'path': bound[1], 'sha256': bound[2], 'module': bound[3],
                    'source_scope': 'owned_checkout' if root in path.parents else 'historical_exact_path'})
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and attempt not in path.parents:
                frame = sys._getframe(1)
                standard_null = (discovery_open[0] and path == null and mode is None
                    and isinstance(flags, int) and flags & os.O_RDWR
                    and flags & ~(os.O_RDWR | os.O_CLOEXEC) == 0
                    and frame.f_code.co_filename == '/usr/lib/python3.12/subprocess.py'
                    and frame.f_code.co_name == '_get_devnull')
                if not standard_null:
                    raise RuntimeError('write outside current native attempt refused')
                discovery_guard()
            if not writing and str(path).startswith('/home/barberb/lift_coding/') and path.suffix == '.json' and path.exists():
                # Capture all retained local JSON opens, including reads by older
                # helpers. Their byte pins are independently rechecked below.
                g.physical_parents(path)
                info = path.lstat()
                assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 128*1024*1024
                previous = opened.setdefault(str(path), identity(info))
                assert previous == identity(info), 'retained input identity changed'
        if event.startswith(('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.link', 'os.symlink')):
            for value in args[:2] if event in {'os.rename', 'os.link', 'os.symlink'} else args[:1]:
                if isinstance(value, (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(value)).absolute()
                    if path != attempt and attempt not in path.parents:
                        raise RuntimeError('mutation outside current native attempt refused')

    sys.addaudithook(audit)
    sys.path.insert(0, str(root))
    ops = root / 'scripts/ops/autoencoder'

    def module(name):
        spec = importlib.util.spec_from_file_location('_fresh_native_replay_' + name, ops / (name + '.py'))
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result

    controls = module('evaluate_gte_native_source_controls')
    retained_ref = config['retained_config']
    retained_raw = g.snapshot(Path(retained_ref['path']), g.MAX_METADATA_BYTES)
    assert len(retained_raw) == retained_ref['bytes'] and g.sha(retained_raw) == retained_ref['sha256']
    retained = g.decode(retained_raw)
    original_runtime, original_refs = controls.runtime_receipt(retained['original_runtime'], expected_start='original_initialization')
    aligned_runtime, aligned_refs = controls.runtime_receipt(retained['aligned_runtime'], expected_start='authenticated_aligned_generation')
    # Historical parent admission deliberately requires the original exact
    # implementation paths. Execute those pinned bytes at their genuine origins.
    historical_training = next(ref for ref in aligned_runtime['implementation_files']
        if Path(ref['path']).name == 'run_gte_aligned_interface_training.py')
    assert Path(historical_training['path']) == historical / 'scripts/ops/autoencoder/run_gte_aligned_interface_training.py'
    assert str(Path(historical_training['path'])) in pins
    assert pins[historical_training['path']] == historical_training['sha256']
    training = controls.module('run_gte_aligned_interface_training', Path(historical_training['path']).parent)
    native = training._native_cli()
    reader = native._helper('gte_worker_contract')
    budget = reader._resources({'device': 'cpu', 'threads': 1, 'max_rows': 4,
        'memory_limit_mib': 16384, 'cpu_time_limit_seconds': 1200})
    resources = reader.configure_cpu_process(budget)
    parent = controls.module('gte_source_evaluation_parent', ops).admit_training_parent(
        controls.read_ref(aligned_runtime['manifest']), aligned_runtime['manifest'],
        root=Path(retained['workspace_root']), reader=reader, training_cli=training)
    original_checkpoint, arguments, original_closure = controls.admit_original(original_runtime, parent,
        reader=reader, native=native, training=training)
    p = parent['payloads']
    primary, legacy = controls.read_ref(retained['primary_checkpoint']), controls.read_ref(retained['legacy8_checkpoint'])
    donor_pins = p['donor_pins']
    assert retained['primary_checkpoint']['sha256'] == donor_pins['teacher384_checkpoint_sha256']
    assert retained['legacy8_checkpoint']['sha256'] == donor_pins['legacy8_checkpoint_sha256']
    source = native._helper('gte_decoder_source_evaluation')
    evaluation = source.prepare_source_evaluation(p['initialization'], p['native_batch'], p['batch'], p['replay'],
        expected_donor_pins=donor_pins, max_primary_rows=2, max_auxiliary_rows=2)
    assert evaluation['selected_row_count'] == evaluation['native_ready_row_count'] == 4
    comparison = native._helper('gte_decoder_source_comparison')
    _, legacy_snapshot, aligned_arguments, _ = comparison._admit(evaluation, p['initialization'], p['native_batch'],
        p['batch'], p['replay'], donor_pins, primary, legacy, parent['aligned']['checkpoint'],
        parent['aligned']['file_pins'], parent['trained_checkpoint'])
    sources = {head: [{key: row[key] for key in ('id', 'source_text', 'source_sha256', 'evaluation_role',
        'generation_input', 'native_generation_input', 'native_receipt_sha256')}
        for row in evaluation['heads'][head]['rows']] for head in controls.HEADS}
    budgets = {head: {key: evaluation['heads'][head][key] for key in ('max_new_tokens', 'inherited_max_target_tokens')}
        for head in controls.HEADS}
    completed = [CHECKS[0], CHECKS[1]]
    total = 0
    files = []

    def save(name, value):
        nonlocal total
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
        total += len(raw)
        assert total <= MAX_OUTPUT
        g.directory_guard(directories)
        path = Path(layout['exports']) / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        assert g.snapshot(path, MAX_OUTPUT) == raw
        ref = {'path': str(path), 'bytes': len(raw), 'sha256': g.sha(raw)}
        files.append(ref)
        return ref

    input_ref = save('source-inputs.json', {'schema': 'legal-decoder-small-replay-inputs/v1', 'heads': sources,
        'contains_references': False, 'target_access': False, 'independent_holdout': False})
    closure = {ref['path']: ref for ref in [retained_ref, *original_refs, *aligned_refs, *original_closure,
        *parent['closure'], retained['primary_checkpoint'], retained['legacy8_checkpoint']]}
    initializer_refs = [ref for ref in closure.values() if Path(ref['path']).name == 'student-initialization.json']
    aligned_initializer_refs = [ref for ref in closure.values() if Path(ref['path']).name == 'aligned-student.json']
    assert len(initializer_refs) == len(aligned_initializer_refs) == 1
    checkpoint_pins = {'original_initialization': initializer_refs[0]['sha256'],
        'aligned_initialization': aligned_initializer_refs[0]['sha256'],
        'original_trained': original_runtime['checkpoint']['sha256'],
        'aligned_trained': aligned_runtime['checkpoint']['sha256']}
    plan_ref = save('plan.json', {'schema': 'legal-decoder-small-replay-plan/v1', 'configuration_sha256': g.sha(config_raw),
        'inputs': input_ref, 'closure': list(closure.values()), 'variants': list(controls.VARIANTS),
        'controls': list(controls.CONTROLS), 'budgets': budgets, 'per_head_rows': {h: len(sources[h]) for h in controls.HEADS},
        'selection': 'first_two_original_exposed_validation_and_two_legacy_training_diagnostics',
        'all_generation_frozen_before_scoring': True, 'references_read_during_parent_admission': True,
        'reference_prefix_used': False, 'independent_holdout': False, 'proof_authority': False})
    discovery_open[0] = True
    try:
        import torch
    finally:
        discovery_open[0] = False
    torch.set_num_threads(1)
    generation = native._helper('gte_decoder_source_generation')
    preserved = native._helper('gte_decoder_transfer_replay')
    init = p['initialization']

    def fresh(label):
        if label == 'original_donor':
            return {'primary384': preserved._original_primary_model(torch, primary),
                'legacy8': native._helper('gte_legacy8_decoder_donor').load_private_legacy8_decoder_snapshot(legacy_snapshot,
                    expected_source_checkpoint_sha256=donor_pins['legacy8_checkpoint_sha256'],
                    expected_source_model_state_sha256=donor_pins['legacy8_weights_sha256'])['model']}
        if label == 'original_initialization':
            return native._helper('gte_decoder_reuse').load_dual_decoder(init, expected_donor_pins=donor_pins)
        if label == 'aligned_initialization':
            return native._helper('gte_aligned_decoder').load_aligned_decoder(parent['aligned']['checkpoint'],
                expected_file_pins=parent['aligned']['file_pins'], expected_donor_pins=donor_pins)
        if label == 'original_trained':
            return native._helper('gte_decoder_interface_checkpoint').load_interface_checkpoint(original_checkpoint, **arguments)
        assert label == 'aligned_trained'
        return native._helper('gte_aligned_interface_checkpoint').load_interface_checkpoint(parent['trained_checkpoint'], **aligned_arguments)

    def generate_panel(model, label, control):
        records = []
        for head in controls.HEADS:
            for index, row in enumerate(sources[head]):
                vector, intervention = controls.intervention_input(sources[head], index, control, donor=label == 'original_donor')
                donor = label == 'original_donor'
                receipt = generation.generate_source_only(model[head] if donor else model,
                    variant=('donor384' if head == 'primary384' else 'legacy8') if donor else 'student768',
                    head=head, input_vector=vector, **budgets[head])
                generation.inspect_source_only_generation(receipt)
                records.append({'id': row['id'], 'source_sha256': row['source_sha256'], 'head': head,
                    'variant': label, 'control': control, 'evaluation_role': row['evaluation_role'],
                    'intervention': intervention, 'generation': receipt})
        return {'schema': 'legal-decoder-small-replay-generation/v1', 'variant': label, 'control': control, 'rows': records}

    panels, panel_refs = [], []
    started = time.monotonic()
    for label in controls.VARIANTS:
        model = fresh(label)
        for control in controls.CONTROLS:
            panel = generate_panel(model, label, control)
            panels.append(panel)
            panel_refs.append(save('generation-' + label + '-' + control + '.json', panel))
        del model
    frozen_ref = save('generation-frozen.json', {'schema': 'legal-decoder-small-replay-freeze/v1',
        'plan': plan_ref, 'generation_files': panel_refs, 'generation_count': 60, 'scoring_started': False,
        'all_variants_completed': True, 'reference_prefix_used': False})
    completed.append(CHECKS[2])
    # A second private load, not a receipt-only structural replay.
    replayed, replay_steps = 0, 0
    for label in controls.VARIANTS:
        model = fresh(label)
        for control in controls.CONTROLS:
            expected = next(panel for panel in panels if panel['variant'] == label and panel['control'] == control)
            repeated = generate_panel(model, label, control)
            assert generation.digest(expected) == generation.digest(repeated), 'fresh numerical replay differs'
            replayed += len(repeated['rows'])
            replay_steps += sum(row['generation']['step_count'] for row in repeated['rows'])
        del model
    assert replayed == 60
    completed.append(CHECKS[3])
    scored = []
    # Compatibility is candidate-only. Scoring follows the immutable generation freeze.
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_ir_decoder_output_compatibility_v1 as compatibility
    compatibility_reports = []
    for panel in panels:
        for row in panel['rows']:
            head = row['head']
            reference = next(r['reference'] for r in evaluation['heads'][head]['rows'] if r['id'] == row['id'])
            codec = init['primary' if head == 'primary384' else 'legacy8']['codec']
            score = source.score_generation({key: row['generation'][key] for key in ('generated_ids', 'terminated', 'truncated')}, reference, codec, head)
            scored.append({key: row[key] for key in ('id', 'head', 'variant', 'control', 'evaluation_role')} | {'score': score})
            # Adapter call is filled against the frozen public API before admission.
            receipt_raw = json.dumps(row['generation'], sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
            codec_raw = json.dumps(codec, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
            checkpoint_sha = (retained['primary_checkpoint' if head == 'primary384' else 'legacy8_checkpoint']['sha256']
                if row['variant'] == 'original_donor' else checkpoint_pins[row['variant']])
            compatibility_reports.append(adapt_candidate(compatibility, row, receipt_raw, codec_raw, checkpoint_sha))
    compatibility_ref = save('candidate-compatibility.json', {'schema': 'legal-decoder-small-replay-compatibility/v1', 'rows': compatibility_reports})
    completed.append(CHECKS[4])
    score_ref = save('scores.json', {'schema': 'legal-decoder-small-replay-scores/v1', 'generation_freeze': frozen_ref,
        'rows': scored, 'independent_holdout': False, 'source_fidelity_qualified': False, 'proof_authority': False})
    source_events_ref = save('checked-source-execution-events.json', {'schema': 'legal-decoder-checked-source-events/v1',
        'events': executed, 'event_count': len(executed)})
    summaries = []
    for label in controls.VARIANTS:
        for control in controls.CONTROLS:
            for head in controls.HEADS:
                rows = [r for r in scored if (r['variant'], r['control'], r['head']) == (label, control, head)]
                normal = {r['id']: r for r in scored if (r['variant'], r['control'], r['head']) == (label, 'source', head)}
                summaries.append({'variant': label, 'control': control, 'head': head, 'count': len(rows),
                    **{key: sum(r['score'][key] for r in rows) for key in ('syntax_valid', 'exact_target_match', 'terminated', 'truncated', 'invalid_generation')},
                    'changed_generated_token_sequences': sum(r['score']['generated_ids_sha256'] != normal[r['id']]['score']['generated_ids_sha256'] for r in rows)})
    compatibility_panels = []
    for label in controls.VARIANTS:
        for control in controls.CONTROLS:
            for head in controls.HEADS:
                reports = [r['report'] for r in compatibility_reports
                    if (r['variant'], r['control'], r['head']) == (label, control, head)]
                compatibility_panels.append({'variant': label, 'control': control, 'head': head, 'count': len(reports),
                    'grammar_valid': sum(r['legacy_output']['grammar_valid'] for r in reports),
                    'complete_candidate': sum(r['legacy_output']['complete_candidate'] for r in reports),
                    'canonicalization_changed_payload': sum(r['legacy_output']['canonicalization_changed_payload'] is True for r in reports),
                    'relational_profile_unsupported': sum(r['rich_relational_compatibility']['supported'] is False for r in reports)})
    for ref in closure.values():
        raw = g.snapshot(Path(ref['path']), 128*1024*1024)
        assert len(raw) == ref['bytes'] and g.sha(raw) == ref['sha256']
    for path, before in opened.items():
        assert identity(Path(path).lstat()) == before
    for ref in files:
        raw = g.snapshot(Path(ref['path']), MAX_OUTPUT)
        assert len(raw) == ref['bytes'] and g.sha(raw) == ref['sha256']
    expected_export_names = {'source-inputs.json', 'plan.json', 'generation-frozen.json',
        'candidate-compatibility.json', 'scores.json', 'checked-source-execution-events.json'} | {
        'generation-' + label + '-' + control + '.json' for label in controls.VARIANTS for control in controls.CONTROLS}
    assert {p.name for p in Path(layout['exports']).iterdir()} == expected_export_names
    executed_origins = {r['path'] for r in executed}
    for name, value in tuple(sys.modules.items()):
        if name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'):
            path = getattr(value, '__file__', None)
            if path is not None:
                assert path in executed_origins and root in Path(path).parents, 'foreign or unchecked canonical product origin'
            else:
                assert all(root in Path(p).parents for p in value.__path__), 'foreign natural namespace'
    g.code_guard(pins)
    discovery_guard()
    g.directory_guard(directories)
    assert attempts == {'network': 0, 'child_process': 0}
    completed.append(CHECKS[5])
    summary = {'schema': 'legal-decoder-small-numerical-replay-summary/v1', 'completed': True,
        'status': 'exposed_regression_unqualified', 'workload': 'finite_saved_weight_numerical_reproducibility_validation',
        'inference_service_or_model_admission': False, 'compatibility_panels': compatibility_panels, 'selected_sources': 4, 'primary_exposed_rows': 2, 'legacy_training_rows': 2,
        'first_pass_generations': 60, 'fresh_replay_generations': replayed, 'generation_calls': 120,
        'decoder_forward_calls': replay_steps + sum(row['generation']['step_count'] for panel in panels for row in panel['rows']),
        'fresh_private_load_replay_exact': True, 'all_generation_frozen_before_scoring': True,
        'parent_admission_reads_reference_bearing_files': True, 'panels': summaries, 'compatibility': compatibility_ref,
        'generation_freeze': frozen_ref, 'scores': score_ref, 'elapsed_numerical_seconds': time.monotonic()-started,
        'torch_version': torch.__version__, 'numerical_device': 'cpu', 'numerical_dtype': 'float32',
        'training_executed': False, 'optimizer_steps': 0, 'encoder_inference_executed': False,
        'download_executed': False, 'independent_holdout': False, 'source_fidelity_qualified': False,
        'proof_authority': False, 'lean_executed': False, 'accuracy_claim': False,
        'zero_is_disabled_architecture': False, 'references_used_as_generation_prefix': False,
        'resources': resources, 'executed_checks': completed, 'payload_files': files,
        'native_admitted_memory_mb': request['memory_mb'], 'worker_virtual_address_space_cap_mib': 16384,
        'checked_source_execution_events': source_events_ref, 'checked_source_execution_event_count': len(executed),
        'checked_source_execution_unique_origins': sorted(executed_origins),
        'source_sha256': pins, 'refused_network_and_child_attempts': attempts,
        'native_admitted_child_slots': request['child_process_slots'],
        'allowed_readonly_discovery_subprocess_calls': discovery_calls,
        'system_discovery_file_identities': system_identities,
        'system_alias_identities': alias_identities, 'standard_null_device_identity': null_identity,
        'persistent_writes_restricted_to_attempt': True,
        'third_party_distribution_integrity_attested': False,
        'all_retained_local_json_open_identities_unchanged': True}
    g.save(Path(layout['logs']) / 'numerical-replay.json', summary, directories)
    print(json.dumps({'completed': True, 'first_pass_generations': 60, 'fresh_replay_generations': replayed,
        'summary': str(Path(layout['logs']) / 'numerical-replay.json')}), flush=True)


def adapt_candidate(api, row, receipt_raw, codec_raw, checkpoint_sha):
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    receipt = row['generation']
    capture = {'schema': 'legal-ir-decoder-capture-binding/v1', 'id': row['id'],
        'source_sha256': row['source_sha256'], 'control': row['control'], 'head': row['head'],
        'variant': receipt['variant'], 'dimension': receipt['input_dimension'], 'checkpoint_sha256': checkpoint_sha,
        'model_state_sha256': receipt['model_state_sha256_before'], 'input_vector_sha256': receipt['input_vector_sha256'],
        'numerical_input_sha256': receipt['numerical_input_sha256'], 'receipt_sha256': sha(receipt_raw), 'codec_sha256': sha(codec_raw)}
    capture_raw = json.dumps(capture, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    args = {'expected_receipt_sha256': sha(receipt_raw), 'expected_codec_sha256': sha(codec_raw),
        'expected_capture_binding_sha256': sha(capture_raw)}
    report = api.prepare_legal_ir_decoder_output_compatibility_v1(receipt_raw, codec_raw, capture_raw, **args)
    assert api.validate_legal_ir_decoder_output_compatibility_v1(report, receipt_raw, codec_raw, capture_raw,
        expected_report_sha256=api.legal_ir_decoder_output_compatibility_sha256(report), **args) == report
    return {'variant': row['variant'], 'control': row['control'], 'head': row['head'], 'id': row['id'],
        'capture_binding': capture, 'capture_binding_utf8': capture_raw.decode(), 'receipt_utf8': receipt_raw.decode(),
        'codec_utf8': codec_raw.decode(), 'report': report}


if __name__ == '__main__':
    main()

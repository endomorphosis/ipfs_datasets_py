"""Explicit, advisory consumption of the released NumPy CALL-fragment head.

Captured whole modules, including their imports, are the embedding inputs.
The frozen experimental grammar and scalar decoder remain unchanged. Native
operation receipts authenticate retained execution; reload never re-infers.
Neither a matching fragment nor a generated projection discharges a proof.
"""
from __future__ import annotations

from collections import Counter
import ast
from contextlib import contextmanager
from copy import deepcopy
from importlib.metadata import version as package_version
from importlib.util import find_spec
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import site
import stat
import sys
import tempfile
import time

from ...duckdb_control import autoencoder_registry
from ...duckdb_control.codebase_catalog import CodebaseHead
from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embeddings
from ...optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
from ..formalization.autoencoder import numerical_selection_384 as profile
from . import codebase_source_384 as shared
from .codebase_resources import acquire_codebase_resources, codebase_admission_timeout

SCHEMA = "codebase-numerical-selection-inference@1"
PREPARATION_SCHEMA = "codebase-numerical-selection-preparation@1"
WORKER_SCHEMA = "codebase-numerical-selection-worker@1"
MAX_BYTES = 32 * 1024**2
MAX_PATHS = 256
MAX_SELECTED = 128
RELEASE = dict(repository="Publicus/security-ir-autoencoder",
    revision="38666f43e998d55b5f4259e354286f5929027ba1",
    path="releases/20261011-numpy-unary-selection-384-development-v1/checkpoint.json",
    checkpoint_file_sha256="26ccc7cf8420e0ed6cbbe22603e09be0e3572fb32a1e489e877fc5081f506e03",
    checkpoint_bytes=281905,
    parent_sha256="969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62")
FALSE = dict(**profile.FALSE, promotion_performed=False, training_executed=False,
    training_labels_used=False, claim_proved=False)
raw, sha, require = shared._raw, shared._sha, shared._require


def _flags(value):
    return all(type(value.get(k)) is type(v) and value.get(k) == v for k, v in FALSE.items())


def pins():
    from . import codebase_numerical_selection_384_worker as worker
    from ...optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as sources
    return dict(owner=sha(Path(__file__).read_bytes()), worker=sha(Path(worker.__file__).read_bytes()),
        profile=profile._pins(), shared=shared._pins(),
        embedding_runtime=sha(Path(embeddings.__file__).read_bytes()),
        embedding_codec=sha(Path(codec.__file__).read_bytes()),
        embedding_sources=sha(Path(sources.__file__).read_bytes()),
        registry=sha(Path(autoencoder_registry.__file__).read_bytes()))


def _checkpoint(path, expected_sha256):
    """Read the exact explicit release without symlink or unbounded-file access."""
    require(expected_sha256 == RELEASE['checkpoint_file_sha256'],
        'explicit published numerical checkpoint digest required')
    path = Path(path).absolute()
    require('..' not in path.parts, 'canonical numerical checkpoint path required')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_size == RELEASE['checkpoint_bytes'], 'bounded regular numerical checkpoint required')
            content = stream.read(RELEASE['checkpoint_bytes'] + 1)
            after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        require(all(getattr(before, f) == getattr(after, f) for f in fields)
            and len(content) == RELEASE['checkpoint_bytes'] and sha(content) == expected_sha256,
            'numerical checkpoint changed or digest differs')
    finally:
        os.close(directory)
    checkpoint = profile.shared.native._parse(content)
    runtime = profile.NumericalSelectionRuntime384(checkpoint)
    require(checkpoint['parent_sha256'] == RELEASE['parent_sha256'], 'published Legal parent lineage differs')
    return str(path), runtime.checkpoint


def prepare_numerical_selection(index, *, expected_head, paths):
    """Inventory every declared file and select supported original modules only."""
    require(type(expected_head) is CodebaseHead, 'exact captured source head required')
    require(type(paths) in (list, tuple) and 1 <= len(paths) <= MAX_PATHS
        and all(type(p) is str and 0 < len(p.encode()) <= 1024
            and PurePosixPath(p).as_posix() == p and not PurePosixPath(p).is_absolute()
            and '..' not in p.split('/') and '\\' not in p for p in paths)
        and len(set(paths)) == len(paths), 'distinct canonical captured paths required')
    manifest = index.load(expected_head.manifest_cid)
    require(manifest.snapshot.repository_id == expected_head.repository_id
        and manifest.snapshot.snapshot_cid == expected_head.snapshot_cid
        and manifest.ast_revision_id == expected_head.ast_revision_id, 'captured source head differs')
    entries = {e.path: e for e in manifest.snapshot.entries}
    files, selected, eligible, total = [], [], 0, 0
    for path in sorted(paths):
        require(path in entries, 'selected path is outside captured inventory')
        entry = entries[path]
        item = dict(path=path, entry_cid=entry.entry_cid, source_cid=entry.source_cid,
            bytes=entry.size_bytes, source_sha256=None, disposition=None, reason=None, unit=None)
        files.append(item)
        if entry.is_opaque:
            item.update(disposition='opaque', reason=entry.opaque_reason)
            continue
        if not 0 < entry.size_bytes <= 65536:
            item['disposition'] = 'deferred_source_byte_limit'
            continue
        total += entry.size_bytes
        require(total <= 4 * 1024**2, 'complete numerical source population exceeds byte budget')
        body = index.artifacts.get_bytes(entry.source_cid)
        require(len(body) == entry.size_bytes, 'captured source size differs')
        item['source_sha256'] = sha(body)
        try:
            unit = profile.prepare_selection_unit(source_bytes=body, path=path)
        except profile.NumericalSelectionError as exc:
            item.update(disposition='unsupported_profile', reason=str(exc))
            continue
        eligible += 1
        item['unit'] = unit
        if len(selected) >= MAX_SELECTED:
            item['disposition'] = 'deferred_selection_budget'
        else:
            item['disposition'] = 'selected_for_token_check'
            selected.append(dict(path=path, unit_id=unit['unit_id'], source_text=unit['model_input_text']))
    value = dict(schema=PREPARATION_SCHEMA, source_head=expected_head.to_dict(), paths=sorted(paths),
        files=files, selected_inputs=selected, producer=pins(),
        selection='canonical_path_order_first128_eligible_original_modules',
        counts=dict(files=len(files), eligible_files=eligible, selected_units=len(selected)), **FALSE)
    require(len(raw(value)) <= MAX_BYTES, 'numerical preparation exceeds artifact bound')
    return value


def _context(index, *, expected_head, paths, checkpoint_path, checkpoint_sha256, embedding_snapshot):
    preparation = prepare_numerical_selection(index, expected_head=expected_head, paths=paths)
    path, checkpoint = _checkpoint(checkpoint_path, checkpoint_sha256)
    snapshot, assets = embeddings._snapshot_assets(embedding_snapshot, release_verified_pages=True)
    key = dict(schema=SCHEMA, profile=profile.PROFILE, release=deepcopy(RELEASE),
        source_head=expected_head.to_dict(), preparation_sha256=sha(raw(preparation)),
        checkpoint_path=path, checkpoint_file_sha256=checkpoint_sha256,
        checkpoint_canonical_sha256=profile._digest(checkpoint), parent_sha256=checkpoint['parent_sha256'],
        head_sha256=checkpoint['checkpoint']['head_sha256'],
        projection_sha256=checkpoint['checkpoint']['projection_sha256'],
        embedding_snapshot=str(snapshot), embedding_assets=assets, producer=pins(),
        device='cpu', batch_size=16, python=sys.version,
        runtime_versions={n: package_version(n) for n in
            ('torch', 'numpy', 'transformers', 'sentence-transformers', 'tokenizers')},
        embedding_runtime=_embedding_runtime_identity())
    return key, preparation, checkpoint


def _embedding_runtime_identity():
    """Bind the actual Torch build tag without loading Torch in the owner.

    Wheel metadata can say ``2.13.0`` while the runtime reports
    ``2.13.0+cu130``. The CPU embedding receipt records the latter exactly.
    Only a bounded literal version declaration is accepted, never execution.
    """
    spec = find_spec('torch')
    require(spec is not None and spec.origin is not None, 'local Torch package required')
    path = Path(spec.origin).parent/'version.py'
    with path.open('rb') as stream:
        content = stream.read(16385)
    require(0 < len(content) <= 16384, 'bounded Torch version declaration required')
    values = [node.value.value for node in ast.parse(content).body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == '__version__'
        and isinstance(node.value, ast.Constant)]
    require(len(values) == 1 and type(values[0]) is str and 0 < len(values[0]) <= 128,
        'one literal Torch runtime version required')
    return dict(torch_version_source_sha256=sha(content), runtime_versions={
        'python': platform.python_version(), 'torch': values[0],
        'transformers': package_version('transformers'), 'tokenizers': package_version('tokenizers'),
        'sentence_transformers': package_version('sentence-transformers')})


@contextmanager
def _embedding_inputs(rows):
    """Reuse the exact-source embedding receipt without claiming a legal corpus.

    The receipt codec's diagnostic/und source label records arbitrary software
    bytes, not law or training examples. Equal whole-source bytes share an input;
    every distinct file/unit retains its independent downstream identity.
    """
    inputs, sources = [], {}
    with tempfile.TemporaryDirectory(prefix='numerical-selection-sources-') as directory:
        for row in rows:
            body = row['source_text'].encode('utf-8')
            digest = sha(body)
            if digest in sources:
                continue
            path = Path(directory) / digest
            path.write_bytes(body)
            sources[digest] = path
            citation = 'software-source-sha256:' + digest
            source = SourceSpan(SourceArtifact(digest, len(body)), 'diagnostic', profile.PROFILE,
                digest, 'und', citation, 0, len(body))
            inputs.append(codec.EmbeddingInput(source, 'Original Python module', 'whole-module',
                row['source_text'], citation))
        yield inputs, lambda reference: sources[reference['sha256']]


def _embedding_rows(receipt, rows, key):
    """Validate retained token/vector/source integrity without embedding again."""
    if not rows:
        require(receipt is None, 'empty selection cannot carry embedding evidence')
        return {}
    require(type(receipt) is dict, 'native embedding receipt required')
    parsed = codec.EmbeddingProductionReceipt(codec._canonical(receipt))
    with _embedding_inputs(rows) as (inputs, resolver):
        parsed.validate_sources(resolver)
        require(receipt['inputs'] == [i.to_dict() for i in inputs], 'whole-module embedding inputs differ')
    require(parsed.native_execution_profile and receipt['execution'] == codec.native_execution_profile(batch_size=16)
        and receipt['model_assets'] == key['embedding_assets']
        and key['embedding_runtime'] == _embedding_runtime_identity()
        and receipt['producer'] == dict(code_sha256=key['producer']['embedding_runtime'],
            runtime_versions=key['embedding_runtime']['runtime_versions']),
        'pinned native embedding producer or runtime differs')
    require(all(r['status'] != 'missing_input' for r in receipt['results']),
        'captured source cannot be silently missing from embedding')
    return {item['source']['artifact']['sha256']: result
        for item, result in zip(receipt['inputs'], receipt['results'])}


def _validate_prediction(row, unit, key):
    from ..formalization.autoencoder.structured_source_384 import FALSE as decoder_false
    require(type(row) is dict and set(row) == {'prediction', 'unit_id', 'path', 'source_sha256', 'status',
        'source_candidate_match', 'candidate_replaced', 'continue_planning', 'source_binding',
        'matched_projection_refs', 'binding_scope', 'model_inference_executed', *profile.FALSE}
        and all(type(row.get(k)) is type(v) and row.get(k) == v for k, v in profile.FALSE.items()),
        'closed non-authoritative numerical candidate required')
    prediction = row['prediction']
    require(type(prediction) is dict and set(prediction) == {'id', 'source_sha256', 'candidate_ir',
        'predicted_classes', 'reason', 'status', 'projected_embedding', 'weight_ablation', 'head_sha256',
        'projection_sha256', 'target_access', 'teacher_forcing', 'continue_planning', *decoder_false}
        and all(prediction.get(k) is v for k, v in decoder_false.items())
        and prediction['target_access'] is False and prediction['teacher_forcing'] is False
        and prediction['continue_planning'] is True and prediction['weight_ablation'] is None
        and prediction['head_sha256'] == key['head_sha256']
        and prediction['projection_sha256'] == key['projection_sha256'], 'unchanged advisory decoder output required')
    require(prediction['id'] == row['unit_id'] == unit['unit_id'] and row['path'] == unit['path']
        and prediction['source_sha256'] == row['source_sha256'] == unit['source_sha256'],
        'numerical candidate source identity differs')
    vector = prediction['projected_embedding']
    require(type(vector) is list and len(vector) == 384
        and all(type(v) in (int, float) and math.isfinite(v) for v in vector),
        'finite retained projected vector required')
    matched = prediction['candidate_ir'] is not None and raw(prediction['candidate_ir']) == raw(unit['target'])
    require(prediction['status'] == ('unqualified_candidate' if prediction['candidate_ir'] is not None
                else 'fail_open_invalid_output')
        and row['source_candidate_match'] is matched and row['candidate_replaced'] is False
        and row['continue_planning'] is True and row['model_inference_executed'] is True
        and row['status'] == ('source_aligned_fragment' if matched else 'fail_open_source_mismatch')
        and row['binding_scope'] == 'one_learned_canonical_CALL_checked_against_source; deterministic_whole_file_artifacts'
        and row['source_binding'] == {k: unit[k] for k in ('function_id', 'source_ref_ids', 'span_ids',
            'start_byte', 'end_byte', 'canonical_roles', 'import_context')}
        and row['matched_projection_refs'] == ({k: unit[k] for k in ('numerical_report_sha256',
            'link_report_sha256', 'pending_obligation_ids', 'family_artifact_ids', 'artifacts')} if matched else None),
        'numerical source match, provenance or projection references differ')


def _validate_output(output, key, preparation):
    require(type(output) is dict and set(output) == {'schema', 'key', 'rows', 'embedding_receipt',
        'inference', 'model_loads', *FALSE} and output['schema'] == WORKER_SCHEMA
        and output['key'] == key and _flags(output), 'closed numerical worker output required')
    inputs, rows = preparation['selected_inputs'], output['rows']
    require(type(rows) is list and len(rows) == len(inputs)
        and type(output['model_loads']) is int and output['model_loads'] == int(bool(inputs)),
        'complete numerical inference population required')
    embedded = _embedding_rows(output['embedding_receipt'], inputs, key)
    units = {f['path']: f['unit'] for f in preparation['files']}
    candidates = []
    for source, row in zip(inputs, rows):
        digest = sha(source['source_text'].encode())
        item = embedded[digest]
        count = len(item['tokens']['input_ids']) if item['status'] == 'embedded' else item['tokens']['token_count']
        require(type(row) is dict and set(row) == {'path', 'unit_id', 'source_sha256', 'status',
            'tokens', 'embedding_input_id', 'candidate'} and row['path'] == source['path']
            and row['unit_id'] == source['unit_id'] and row['source_sha256'] == digest
            and type(row['tokens']) is int and row['tokens'] == count
            and row['embedding_input_id'] == item['input_id'], 'exact original-module inference row required')
        if item['status'] == 'token_limit_exceeded':
            require(row['status'] == 'deferred_gte_token_limit' and row['candidate'] is None,
                'over-512 input cannot carry a decoded or truncated candidate')
        else:
            _validate_prediction(row['candidate'], units[source['path']], key)
            require(row['status'] == row['candidate']['status'], 'candidate disposition differs')
            candidates.append(row['candidate'])
    inference = output['inference']
    if not candidates:
        require(inference is None, 'empty inference cannot carry decoder evidence')
    else:
        require(type(inference) is dict and set(inference) == {'schema', 'profile', 'rows',
            'checkpoint_sha256', 'head_sha256', 'projection_sha256', 'weight_ablation',
            'model_inference_executed', 'source_only_inputs', 'embedding_provenance_verified', *profile.FALSE}
            and inference['schema'] == 'numerical-selection-384-inference@1'
            and inference['profile'] == profile.PROFILE and raw(inference['rows']) == raw(candidates)
            and inference['checkpoint_sha256'] == key['checkpoint_canonical_sha256']
            and inference['head_sha256'] == key['head_sha256']
            and inference['projection_sha256'] == key['projection_sha256']
            and inference['weight_ablation'] is None and inference['model_inference_executed'] is True
            and inference['source_only_inputs'] is True and inference['embedding_provenance_verified'] is False
            and all(type(inference.get(k)) is type(v) and inference.get(k) == v for k, v in profile.FALSE.items()),
            'unchanged numerical profile output required')
    require(len(raw(output)) <= MAX_BYTES, 'numerical worker output exceeds bound')


def _coverage(preparation, output):
    counts = Counter(r['status'] for r in output['rows'])
    return dict(**preparation['counts'],
        file_dispositions=dict(sorted(Counter(f['disposition'] for f in preparation['files']).items())),
        unit_dispositions=dict(sorted(counts.items())),
        source_aligned_fragments=counts['source_aligned_fragment'],
        source_mismatches=counts['fail_open_source_mismatch'], token_deferred=counts['deferred_gte_token_limit'])


def _worker(payload, *, lease, signal, timeout, memory_mb):
    from . import codebase_numerical_selection_384_worker as worker
    from ..backends.codebase_process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
    from ...optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    roots = list(dict.fromkeys([str(Path(__file__).resolve().parents[3]), *site.getsitepackages(), site.getusersitepackages()]))
    runner = BoundedToolRunner(base_environment=dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8',
        CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        NUMEXPR_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1'))
    wire = raw(payload)
    require(len(wire) <= MAX_BYTES, 'numerical worker input exceeds bound')
    deadline = time.monotonic() + timeout
    with lease.acquire_child(lane=ResourceLane.ORCHESTRATION, cpu_slots=1, memory_mb=memory_mb,
            child_process_slots=1, timeout=timeout, cancel_event=signal, request_id='numerical-selection384:infer') as child:
        left = deadline - time.monotonic()
        require(left > 0, 'numerical worker admission exhausted deadline')
        result = run_bounded_stdin_tool([sys.executable, '-I', '-B', str(Path(worker.__file__).resolve()), json.dumps(roots)],
            wire, runner=runner, limits=ToolRunLimits(timeout_seconds=left, resident_memory_bytes=memory_mb*1024**2,
                max_input_bytes=MAX_BYTES, max_output_bytes=MAX_BYTES, max_workspace_bytes=2*MAX_BYTES),
            cancellation=child.combined_cancellation_signal(signal))
    require(result.returncode == 0 and result.workspace_cleaned and not any((result.timed_out, result.cancelled,
        result.unavailable, result.output_truncated, result.resource_exhausted, result.error)),
        'bounded numerical worker failed: ' + str(result.termination_reason) + ': ' + result.stderr[-2048:])
    return codec._parse(result.stdout.encode()), dict(input_sha256=sha(wire), output_sha256=sha(result.stdout.encode()),
        returncode=0, workspace_cleaned=True, device='cpu', provider_calls=0, elapsed_ms=result.elapsed_ms,
        memory_mb=memory_mb, memory_enforcement='sampled_process_tree_RSS_may_overshoot',
        parent_lease_id=lease.lease_id, child_lease_id=child.lease_id)


def load_numerical_selection(index, registry, artifact, *, expected_head, paths,
        checkpoint_path, checkpoint_sha256, embedding_snapshot):
    """Exact committed historical replay, without model execution or freshness."""
    key, preparation, checkpoint = _context(index, expected_head=expected_head, paths=paths,
        checkpoint_path=checkpoint_path, checkpoint_sha256=checkpoint_sha256, embedding_snapshot=embedding_snapshot)
    saved = codec._parse(registry.read_artifact(artifact, max_bytes=MAX_BYTES))
    require(type(saved) is dict and set(saved) == {'schema', 'key', 'preparation', 'output', 'worker_receipt',
        'retention', 'coverage', *FALSE} and saved['schema'] == SCHEMA and saved['key'] == key
        and raw(saved['preparation']) == raw(preparation) and saved['retention'] == 'unknown_not_evaluated'
        and _flags(saved), 'exact retained numerical execution context required')
    _validate_output(saved['output'], key, preparation)
    require(raw(saved['coverage']) == raw(_coverage(preparation, saved['output'])), 'numerical coverage differs')
    payload = dict(schema=WORKER_SCHEMA, key=key, checkpoint=checkpoint, rows=preparation['selected_inputs'])
    receipt = saved['worker_receipt']
    require(type(receipt) is dict and set(receipt) == {'input_sha256', 'output_sha256', 'returncode',
        'workspace_cleaned', 'device', 'provider_calls', 'elapsed_ms', 'memory_mb', 'memory_enforcement',
        'parent_lease_id', 'child_lease_id'} and receipt['input_sha256'] == sha(raw(payload))
        and receipt['output_sha256'] == sha(raw(saved['output']))
        and type(receipt['returncode']) is int and receipt['returncode'] == 0
        and receipt['workspace_cleaned'] is True and receipt['device'] == 'cpu'
        and type(receipt['provider_calls']) is int and receipt['provider_calls'] == 0,
        'native numerical worker receipt differs')
    committed = registry.resolve_operation('numerical-selection384:' + sha(raw(key)),
        'IndexNumericalSelectionInference', dict(key=key))
    require(committed is not None and committed['artifact'] == artifact, 'native numerical execution operation missing')
    return saved


def infer_numerical_selection(index, repository, *, expected_head, registry, checkpoint_path,
        checkpoint_sha256, paths, embedding_snapshot, scheduler=None, parent_lease=None,
        cancel_event=None, timeout_seconds=180., memory_mb=4096, budget_profile=None):
    """Execute an explicit fixed experimental checkpoint inside native fences."""
    shared._owners(index, registry)
    shared._limits(timeout_seconds, memory_mb, 'numerical-selection-inference', budget_profile=budget_profile)
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=codebase_admission_timeout(remaining_seconds=max(0., deadline-time.monotonic())),
            memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            require(not signal.is_set() and time.monotonic() < deadline, 'numerical inference cancelled or deadline expired')
            return deadline - time.monotonic()
        def observe():
            index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=remaining(), memory_mb=memory_mb)
        options = dict(expected_head=expected_head, paths=paths, checkpoint_path=checkpoint_path,
            checkpoint_sha256=checkpoint_sha256, embedding_snapshot=embedding_snapshot)
        observe()
        key, preparation, checkpoint = _context(index, **options)
        operation = 'numerical-selection384:' + sha(raw(key))
        previous = registry.resolve_operation(operation, 'IndexNumericalSelectionInference', dict(key=key))
        executed = previous is None
        if executed:
            payload = dict(schema=WORKER_SCHEMA, key=key, checkpoint=checkpoint, rows=preparation['selected_inputs'])
            output, receipt = _worker(payload, lease=lease, signal=signal, timeout=remaining(), memory_mb=memory_mb)
            del payload, checkpoint
            _validate_output(output, key, preparation)
            observe()
            require(_context(index, **options)[0] == key, 'numerical source, checkpoint or producer changed during inference')
            saved = dict(schema=SCHEMA, key=key, preparation=preparation, output=output,
                worker_receipt=receipt, coverage=_coverage(preparation, output), retention='unknown_not_evaluated', **FALSE)
            artifact = shared._stage(registry, saved)
            remaining()
            observe()
            previous = registry._mutate(operation, 'IndexNumericalSelectionInference', dict(key=key), lambda cx: dict(artifact=artifact))
            del output, receipt, saved
        else:
            del checkpoint
        del key, preparation
        saved = load_numerical_selection(index, registry, previous['artifact'], **options)
        observe()
        remaining()
        return dict(artifact=previous['artifact'], report=saved, native_worker_executed=executed,
            inference_executed=executed and saved['output']['inference'] is not None, **FALSE)


def validate_numerical_selection(index, repository, result, *, registry, checkpoint_path,
        checkpoint_sha256, embedding_snapshot, scheduler=None, parent_lease=None,
        cancel_event=None, timeout_seconds=90., memory_mb=4096, budget_profile=None):
    """Recheck current captured source and immutable execution without inference."""
    shared._owners(index, registry)
    shared._limits(timeout_seconds, memory_mb, 'numerical-selection-replay', budget_profile=budget_profile)
    require(type(result) is dict and set(result) == {'artifact', 'report', 'native_worker_executed',
        'inference_executed', *FALSE} and _flags(result) and type(result['native_worker_executed']) is bool
        and type(result['inference_executed']) is bool, 'closed numerical result required')
    saved = result['report']
    head = CodebaseHead.from_dict(saved['key']['source_head'])
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=codebase_admission_timeout(remaining_seconds=max(0., deadline-time.monotonic())),
            memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def observe():
            left = deadline - time.monotonic()
            require(left > 0 and not signal.is_set(), 'numerical replay cancelled or deadline expired')
            index.observe_current(repository, expected_head=head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=left, memory_mb=memory_mb)
        observe()
        actual = load_numerical_selection(index, registry, result['artifact'], expected_head=head,
            paths=saved['preparation']['paths'], checkpoint_path=checkpoint_path,
            checkpoint_sha256=checkpoint_sha256, embedding_snapshot=embedding_snapshot)
        require(raw(actual) == raw(saved), 'retained numerical report differs from immutable native execution')
        require(result['inference_executed'] == (result['native_worker_executed']
            and actual['output']['inference'] is not None), 'retained numerical execution flags differ')
        observe()
        return deepcopy(result)

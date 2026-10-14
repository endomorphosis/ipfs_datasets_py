"""UNEXECUTED focused normalized-projection byte-accounting controls.

Private decoder raw bytes are evidence only within one member verification.
These memory-only controls retain final callback mutation fences and distinguish
stronger original-byte consistency from legacy coherent-envelope acceptance.
Root alone executes qualification; ordinary CI can use private fixture resources.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from dataclasses import asdict, replace
import gc
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

from ipfs_datasets_py.logic.software_contracts import codebase_preparation as protocol
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_projection as codec
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_runtime as runtime_module
from ipfs_datasets_py.logic.software_contracts import duckdb_ingest as ingestion
from ipfs_datasets_py.logic.software_contracts.ast_ir import SourceProvenance, SourceSpan
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore, project_parse_failure
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import CountingFrontend, DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduling

CASE_NAMES = (
    'exact_boolean_defaults_optout_full_family_reference_work',
    'malformed_projection_clock_types_and_raw_bounds',
    'context_callback_alias_corruption_and_flag_toggle',
    'coherent_parse_failure_metadata_rewrite_refusal',
    'normalized_projection_and_AST_byte_budget_boundaries',
    'prior_projection_mutation_before_page_sealing_refusal',
    'operation_lifetime_reads_checkpoints_and_cancellation',
)
API_READY = True
OWNED_RESOURCES = None
MIB = 1024 * 1024
AT = 1700000000.0
VIEW = 'projection-bytes:authored-fixture'
REFUSALS = (ValueError, TypeError, FileNotFoundError, OSError)

def configure_owned_resources(workspace, scheduler, parent_lease):
    global OWNED_RESOURCES
    if type(workspace) is not type(Path.cwd()):
        raise ValueError('exact concrete workspace Path required')
    info = workspace.lstat()
    if (workspace != Path.cwd() or workspace.resolve(strict=True) != workspace
            or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or not isinstance(scheduler, scheduling.GlobalResourceScheduler)
            or not isinstance(parent_lease, scheduling.ResourceLease)):
        raise ValueError('actual private workspace, scheduler and child lease required')
    OWNED_RESOURCES = workspace, scheduler, parent_lease


class TestPreparationProjectionBytes(unittest.TestCase):
    def setUp(self):
        if not API_READY:
            raise AssertionError('root must bind the reviewed projection byte-count API')
        parent = OWNED_RESOURCES[0] if OWNED_RESOURCES is not None else None
        self.temporary = tempfile.TemporaryDirectory(prefix='projection-bytes-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.repository = self.workspace / 'repository'
        self.repository.mkdir(mode=0o700)
        self.artifacts = ImmutableCAS(self.workspace / 'artifacts', max_object_bytes=4 * MIB)
        self.limits = protocol.CodebasePreparationLimits(max_entries=64, page_entries=16)
        self.store, self.counter, self.ingestor, self.runtime = self._fixture_receiver()
        if OWNED_RESOURCES is None:
            # Ordinary CI creates only private scheduler state, never MAIN.
            healthy = scheduling.ProofHostResources(4, 2048, 2048)
            configuration = scheduling.ResourceSchedulerConfig.for_proof_host(
                state_path=self.workspace / 'admission.json', lane_reservations={},
                proof_resource_sampler=lambda: healthy, auto_renew_leases=False,
                poll_interval_seconds=0.005, proof_backoff_seconds=0.02)
            self.scheduler = scheduling.GlobalResourceScheduler(configuration)
            self.parent_lease = None
        else:
            _, self.scheduler, self.parent_lease = OWNED_RESOURCES

    def _fixture_receiver(self, *, optimized=True):
        store = DuckDBASTStore(connection=None)
        counter = CountingFrontend(PythonASTExtractor())
        ingestor = DuckDBASTIngestor(store=store, frontends={'python': counter})
        actor = runtime_module.RepositoryCodebasePreparation(
            artifacts=self.artifacts, ingestor=ingestor, optimized_projection_byte_counts=optimized)
        return store, counter, ingestor, actor

    def _fixture_resources(self, **overrides):
        result = {'scheduler': self.scheduler if self.parent_lease is None else None,
                  'parent_lease': self.parent_lease, 'memory_mb': 512,
                  'timeout_seconds': 120.0, 'admission_timeout_seconds': 30.0}
        result.update(overrides)
        return result

    def _fixture_start(self, count=2):
        sources = {f'source{index:03d}.py':
                   f'def step{index}(value: int) -> int:\n    return value + {index}\n'.encode()
                   for index in range(count)}
        if count:
            sources['source000.py'] = (b'from other import helper\nshared = 0\n'
                b'def step(value: int) -> int:\n    global shared\n'
                b'    shared = value\n    return helper(value) + 1\n')
        if count > 16:
            sources['source015.py'] = b'def boundary(value):\n    return value + 15\n'
            sources['source016.py'] = (b'from source015 import boundary\n'
                                     b'def cross_page(value):\n    return boundary(value)\n')
        for name, raw in sources.items():
            (self.repository / name).write_bytes(raw)
        root = self.runtime.start_current(self.repository, repository_id=VIEW,
            limits=self.limits, created_at=AT, **self._fixture_resources())
        return root, sources

    def _fixture_page(self, root, cursor=None):
        return self.runtime.prepare_page(self.repository, root.artifact_cid, cursor,
            admitted_page_cid=None if cursor is None else cursor.previous_page_cid,
            **self._fixture_resources())

    def _fixture_load(self, root, page, *, actor=None, **resources):
        actor = self.runtime if actor is None else actor
        return actor.load_projections(root.artifact_cid, page.next_cursor,
            admitted_page_cid=page.artifact_cid, **self._fixture_resources(**resources))

    def _fixture_state(self, store=None, ingestor=None):
        store = self.store if store is None else store
        ingestor = self.ingestor if ingestor is None else ingestor
        stats = ingestor.stats()
        return {'store_stats': store.stats(), 'by_blob': copy.deepcopy(store._by_blob),
                'by_ast': copy.deepcopy(store._by_ast_cid), 'by_file': copy.deepcopy(store._by_file),
                'invalidations': copy.deepcopy(store._invalidations),
                'publications': ingestor.list_publications(),
                'latest_labels': copy.deepcopy(ingestor._latest_by_label),
                'publication_stats': {key: stats[key] for key in
                    ('revisions_published', 'parse_invocations', 'reuse_hits',
                     'invalidations', 'publication_count')}}

    def _fixture_reference(self, root):
        snapshot = RepositorySnapshot.from_dict(root.to_dict()['snapshot'])
        entries = tuple(replace(entry, captured_bytes=(self.repository / entry.path).read_bytes())
                        for entry in snapshot.entries)
        for entry in entries:
            self.assertEqual(cid_for_bytes(entry.captured_bytes), entry.source_cid)
        captured = replace(snapshot, entries=entries)
        frontend = CountingFrontend(PythonASTExtractor())
        ingestor = DuckDBASTIngestor(store=DuckDBASTStore(connection=None),
                                   frontends={'python': frontend})
        publication = ingestor.ingest_snapshot(captured, created_at=AT)
        return publication.projections, frontend

    def _fixture_body(self, projections):
        return tuple(codec.encode_preparation_projection(row) for row in projections)

    @contextmanager
    def _fixture_work(self):
        work = {'public_decode': 0, 'private_decode': 0, 'verified_size': 0,
                'canonical_reconstruct': 0, 'read_calls': 0, 'read_bytes': 0, 'checkpoints': 0}
        public = codec.decode_preparation_projection
        private = codec._decode_preparation_projection_with_raw
        size = codec._verified_preparation_projection_size
        reconstruct = codec._reconstruct
        read = protocol._Reader.read
        check = protocol._Reader.check
        def public_call(*args, **kwargs):
            work['public_decode'] += 1
            return public(*args, **kwargs)
        def private_call(*args, **kwargs):
            work['private_decode'] += 1
            return private(*args, **kwargs)
        def size_call(*args, **kwargs):
            work['verified_size'] += 1
            return size(*args, **kwargs)
        def canonical_call(*args, **kwargs):
            work['canonical_reconstruct'] += 1
            return reconstruct(*args, **kwargs)
        def read_call(reader, *args, **kwargs):
            before = reader.read_bytes, reader.read_calls
            result = read(reader, *args, **kwargs)
            work['read_bytes'] += reader.read_bytes - before[0]
            work['read_calls'] += reader.read_calls - before[1]
            return result
        def check_call(reader):
            work['checkpoints'] += 1
            return check(reader)
        with patch.object(codec, 'decode_preparation_projection', new=public_call), \
                patch.object(codec, '_decode_preparation_projection_with_raw', new=private_call), \
                patch.object(codec, '_verified_preparation_projection_size', new=size_call), \
                patch.object(codec, '_reconstruct', new=canonical_call), \
                patch.object(protocol._Reader, 'read', new=read_call), \
                patch.object(protocol._Reader, 'check', new=check_call):
            yield work

    @contextmanager
    def _fixture_context_hook(self, action):
        """Capture only this member's real decoded projection before its probe."""
        observed = {'projection': None, 'raw': None, 'fired': False, 'events': []}
        public = codec.decode_preparation_projection
        private = codec._decode_preparation_projection_with_raw
        context = ingestion._frontend_cache_context
        def public_call(*args, **kwargs):
            result = public(*args, **kwargs)
            observed.update(projection=result, raw=None)
            observed['events'].append('decode')
            return result
        def private_call(*args, **kwargs):
            result, raw = private(*args, **kwargs)
            observed.update(projection=result, raw=raw)
            observed['events'].append('decode')
            return result, raw
        def probe(*args, **kwargs):
            if observed['projection'] is not None and not observed['fired']:
                observed['fired'] = True
                observed['events'].append('probe')
                action(observed['projection'], observed['raw'])
            return context(*args, **kwargs)
        with patch.object(codec, 'decode_preparation_projection', new=public_call), \
                patch.object(codec, '_decode_preparation_projection_with_raw', new=private_call), \
                patch.object(ingestion, '_frontend_cache_context', new=probe):
            yield observed

    def _fixture_failure(self, **changes):
        arguments = {'provenance': SourceProvenance(
            source_cid=cid_for_bytes(b'authored synthetic parse failure'), path='failure.py',
            repository_id=VIEW, revision='synthetic-failure',
            repository_tree_cid=cid_for_structured({'synthetic-tree': 1})),
            'language': 'python', 'message': 'authored failure, not native extraction',
            'code': 'fixture.synthetic', 'severity': 'error', 'frontend_name': 'fixture-parser',
            'frontend_version': 'fixture-1', 'frontend_toolchain_cid': cid_for_structured({'fixture-toolchain': 1}),
            'span': SourceSpan(start_byte=1, end_byte=3, start_line=1, start_column=1,
                               end_line=1, end_column=3), 'created_at': AT, 'actor_id': 'fixture-actor'}
        arguments.update(changes)
        return project_parse_failure(**arguments)

    def test_exact_boolean_defaults_optout_full_family_reference_work(self):
        self.assertTrue(self.runtime.optimized_projection_byte_counts)
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                self._fixture_receiver(optimized=value)
        root, _ = self._fixture_start(18)
        first = self._fixture_page(root)
        final = self._fixture_page(root, first.next_cursor)
        reference, frontend = self._fixture_reference(root)
        expected = self._fixture_body(reference)
        results = []
        for flag in (True, False):
            store, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            with self._fixture_work() as work:
                restored = self._fixture_load(root, final, actor=actor)
            self.assertEqual(tuple(asdict(row) for row in restored), tuple(asdict(row) for row in reference))
            self.assertEqual(self._fixture_body(restored), expected)
            self.assertEqual(counter.parse_invocations, 0)
            self.assertEqual(self._fixture_state(store, ingestor), before)
            self.assertEqual((work['private_decode'], work['public_decode'], work['verified_size']),
                             (18, 0, 18) if flag else (0, 18, 0))
            self.assertEqual(work['canonical_reconstruct'], 18 if flag else 36)
            self.assertGreater(work['read_calls'], 18)
            self.assertGreater(work['read_bytes'], 0)
            self.assertGreater(work['checkpoints'], 0)
            results.append(work)
        for name in ('read_calls', 'read_bytes', 'checkpoints'):
            self.assertEqual(results[0][name], results[1][name])
        self.assertEqual((self.counter.parse_invocations, frontend.parse_invocations), (18, 18))
        for value in (None, 0, 'true'):
            self.runtime.optimized_projection_byte_counts = value
            try:
                with self.assertRaises(ValueError): self._fixture_load(root, final)
            finally:
                self.runtime.optimized_projection_byte_counts = True

    def test_malformed_projection_clock_types_and_raw_bounds(self):
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        rich = self._fixture_load(root, page)[0]
        failure = self._fixture_failure()
        fields = {'source_revision': 'revision', 'source_file': 'path', 'ast_blob': 'frontend_name',
            'nodes': 'label', 'scopes': 'kind', 'symbols': 'name', 'imports': 'module',
            'references': 'name', 'calls': 'callee_name', 'effects': 'subject', 'interfaces': 'name',
            'diagnostics': 'message', 'invalidations': 'detail'}
        for family, field in fields.items():
            original = codec.encode_preparation_projection(failure if family in ('diagnostics', 'invalidations') else rich)
            body = copy.deepcopy(original)
            row = body[family] if type(body[family]) is dict else body[family][0]
            row[field] = 'malformed admitted relational family'
            for decoder in (codec.decode_preparation_projection, codec._decode_preparation_projection_with_raw):
                with self.subTest(family=family, decoder=decoder.__name__), self.assertRaises(ValueError):
                    decoder(body)
        encoded = codec.encode_preparation_projection(failure)
        for value in (True, 0.0, 'nan', 'inf', '0x1p+0', ''):
            malformed = copy.deepcopy(encoded)
            malformed['ast_blob']['created_at_hex'] = value
            for decoder in (codec.decode_preparation_projection, codec._decode_preparation_projection_with_raw):
                with self.subTest(clock=value), self.assertRaises(ValueError): decoder(malformed)
        for value in (None, [], (), 'untrusted string'):
            with self.assertRaises(ValueError): codec._decode_preparation_projection_with_raw(value)
        oversized = copy.deepcopy(encoded)
        oversized['ast_blob']['payload_json'] = 'x' * (codec.MAX_PREPARATION_PROJECTION_BYTES + 1)
        with self.assertRaises(ValueError): codec._decode_preparation_projection_with_raw(oversized)
        decoded, raw = codec._decode_preparation_projection_with_raw(encoded)
        self.assertEqual(type(raw), bytes)
        self.assertEqual(codec._verified_preparation_projection_size(decoded, raw), len(canonical_dag_json_bytes(encoded)))
        self.assertEqual(codec.decode_preparation_projection(encoded), decoded)
        for value in (None, '', bytearray(raw), b'', b'x' * (codec.MAX_PREPARATION_PROJECTION_BYTES + 1)):
            with self.subTest(raw_type=type(value).__name__), self.assertRaises(ValueError):
                codec._verified_preparation_projection_size(decoded, value)
        with self.assertRaises(ValueError): codec._verified_preparation_projection_size(None, raw)
        with self.assertRaises(ValueError): codec._verified_preparation_projection_size(decoded, raw + b' ')
        # Canonical finite clocks use the reviewed hex representation, including
        # negative zero; the sizing path must preserve exactly that wire body.
        for clock in (-0.0, -1.25, AT):
            projection = self._fixture_failure(created_at=clock)
            body = codec.encode_preparation_projection(projection)
            decoded, raw = codec._decode_preparation_projection_with_raw(body)
            self.assertEqual(codec._verified_preparation_projection_size(decoded, raw), len(raw))
            self.assertEqual(body['ast_blob']['created_at_hex'], clock.hex())

    def test_context_callback_alias_corruption_and_flag_toggle(self):
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        expected = self._fixture_body(self._fixture_load(root, page))
        for flag in (True, False):
            for family in ('nodes', 'ast_blob'):
                store, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
                before = self._fixture_state(store, ingestor)
                def corrupt(projection, raw):
                    if family == 'nodes':
                        object.__setattr__(projection, 'nodes',
                            (replace(projection.nodes[0], label='context callback row corruption'), *projection.nodes[1:]))
                    else:
                        object.__setattr__(projection, 'ast_blob',
                            replace(projection.ast_blob, parse_error='context callback header corruption'))
                with self.subTest(flag=flag, family=family), self._fixture_context_hook(corrupt) as observed:
                    with self.assertRaises(ValueError): self._fixture_load(root, page, actor=actor)
                self.assertTrue(observed['fired'])
                self.assertEqual(observed['events'][:2], ['decode', 'probe'])
                self.assertEqual(self._fixture_state(store, ingestor), before)
                self.assertEqual(counter.parse_invocations, 0)
            store, _, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            def toggle(projection, raw):
                self.assertEqual(type(raw) is bytes, flag)
                actor.optimized_projection_byte_counts = not flag
            original_size = codec._verified_preparation_projection_size
            with self._fixture_context_hook(toggle) as observed, patch.object(
                    codec, '_verified_preparation_projection_size', wraps=original_size) as size:
                restored = self._fixture_load(root, page, actor=actor)
            self.assertTrue(observed['fired'])
            self.assertEqual(observed['events'][:2], ['decode', 'probe'])
            self.assertEqual(size.call_count, 1 if flag else 0)
            self.assertEqual(self._fixture_body(restored), expected)
            self.assertEqual(self._fixture_state(store, ingestor), before)

    def test_coherent_parse_failure_metadata_rewrite_refusal(self):
        original = self._fixture_failure()
        body = codec.encode_preparation_projection(original)
        variants = ({'severity': 'warning'}, {'actor_id': 'different-fixture-actor'},
            {'frontend_name': 'different-parser', 'frontend_version': 'fixture-2',
             'frontend_toolchain_cid': cid_for_structured({'fixture-toolchain': 2})},
            {'span': SourceSpan(start_byte=2, end_byte=5, start_line=2, start_column=0,
                                end_line=2, end_column=3)})
        for arguments in variants:
            decoded, raw = codec._decode_preparation_projection_with_raw(body)
            changed = self._fixture_failure(**arguments)
            for name in decoded.__dataclass_fields__:
                object.__setattr__(decoded, name, getattr(changed, name))
            legacy = codec.encode_preparation_projection(decoded)
            self.assertEqual(legacy, codec.encode_preparation_projection(changed))
            self.assertEqual(codec.decode_preparation_projection(legacy), changed)
            self.assertNotEqual(canonical_dag_json_bytes(legacy), raw)
            with self.subTest(metadata=arguments), self.assertRaisesRegex(ValueError, 'changed after canonical decoding'):
                codec._verified_preparation_projection_size(decoded, raw)
        # This explicitly qualifies a standalone codec consistency fence, not
        # native Python extraction of the authored synthetic failure metadata.

    def test_normalized_projection_and_AST_byte_budget_boundaries(self):
        root, sources = self._fixture_start(2)
        (self.repository / 'source000.py').write_bytes(
            'def café(value: int) -> str:\n    return "雪" + str(value)\n'.encode())
        (self.repository / 'source001.py').write_bytes(b'def broken(:\n')
        (self.repository / 'unsupported.txt').write_bytes('unsupported 雪 inventory member\n'.encode())
        root = self.runtime.start_current(self.repository, repository_id=VIEW,
            limits=self.limits, created_at=AT, **self._fixture_resources())
        page = self._fixture_page(root)
        projections = self._fixture_load(root, page)
        self.assertEqual(len(projections), 2)
        self.assertIn('failed', {row.ast_blob.parse_status for row in projections})
        bodies = self._fixture_body(projections)
        total = sum(len(canonical_dag_json_bytes(body)) for body in bodies)
        ast_total = sum(len(row.ast_blob.payload_json.encode('utf-8')) for row in projections)
        self.assertTrue(any(len(canonical_dag_json_bytes(body)) > len(canonical_dag_json_bytes(body).decode()) for body in bodies))
        for flag in (True, False):
            store, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            original_collect = actor._collect
            for budget_kind, exact in (('projection', total), ('AST', ast_total)):
                for allowance, accepted in ((exact, True), (exact - 1, False)):
                    def bounded(prefix, clock, reader, *, ast_bytes_limit=None):
                        # Inject the private collection bound after context
                        # admission; restore it before the closing context fence.
                        if budget_kind == 'projection':
                            with patch.object(runtime_module, 'MAX_COLLECTED_PROJECTION_BYTES', allowance):
                                return original_collect(prefix, clock, reader, ast_bytes_limit=ast_bytes_limit)
                        return original_collect(prefix, clock, reader, ast_bytes_limit=allowance)
                    with self.subTest(flag=flag, kind=budget_kind, allowance=allowance), patch.object(
                            actor, '_collect', side_effect=bounded):
                        if accepted:
                            self.assertEqual(self._fixture_body(self._fixture_load(root, page, actor=actor)), bodies)
                        else:
                            with self.assertRaisesRegex(ValueError, 'byte bound|projection budget'):
                                self._fixture_load(root, page, actor=actor)
                    self.assertEqual(self._fixture_state(store, ingestor), before)
                    self.assertEqual(counter.parse_invocations, 0)

    def test_prior_projection_mutation_before_page_sealing_refusal(self):
        root, _ = self._fixture_start(18)
        page = self._fixture_page(root)
        for flag in (True, False):
            store, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            captured = []
            collect = actor._collect
            prepare = ingestor.prepare_snapshot_subset
            def collect_call(*args, **kwargs):
                result = collect(*args, **kwargs)
                captured.extend(result)
                return result
            def prepare_call(*args, **kwargs):
                result = prepare(*args, **kwargs)
                self.assertEqual(len(captured), 16)
                projection = captured[0]
                object.__setattr__(projection, 'nodes',
                    (replace(projection.nodes[0], label='post-collection borrowed row mutation'), *projection.nodes[1:]))
                return result
            sealed = []
            publish = self.artifacts._publish
            def publish_call(target, raw):
                value = json.loads(raw) if target.is_relative_to(self.artifacts.structured_root) else None
                if type(value) is dict and value.get('schema') == protocol.PAGE_SCHEMA:
                    sealed.append(target.name)
                return publish(target, raw)
            with self.subTest(flag=flag), patch.object(actor, '_collect', side_effect=collect_call), \
                    patch.object(ingestor, 'prepare_snapshot_subset', side_effect=prepare_call), \
                    patch.object(self.artifacts, '_publish', side_effect=publish_call), self.assertRaises(ValueError):
                actor.prepare_page(self.repository, root.artifact_cid, page.next_cursor,
                    admitted_page_cid=page.artifact_cid, **self._fixture_resources())
            self.assertEqual(sealed, [])
            self.assertEqual(self._fixture_state(store, ingestor), before)
            self.assertEqual(counter.parse_invocations, 2)
            prefix = protocol.validate_preparation_prefix(self.artifacts, root.artifact_cid, page.next_cursor)
            self.assertEqual(prefix.next_offset, 16)

    def test_operation_lifetime_reads_checkpoints_and_cancellation(self):
        root, _ = self._fixture_start(2)
        page = self._fixture_page(root)
        expected = self._fixture_body(self._fixture_load(root, page))
        measurements = []
        for flag in (True, False):
            store, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            keys = set(vars(actor))
            readers = []
            original_root = actor._root
            def root_call(*args, **kwargs):
                result = original_root(*args, **kwargs)
                readers.append(weakref.ref(result[2]))
                return result
            records = []
            with patch.object(actor, '_root', side_effect=root_call):
                for _ in range(2):
                    with self._fixture_work() as work:
                        restored = self._fixture_load(root, page, actor=actor)
                    self.assertEqual(self._fixture_body(restored), expected)
                    records.append(work)
            gc.collect()
            self.assertTrue(all(reference() is None for reference in readers))
            self.assertEqual(set(vars(actor)), keys)
            self.assertEqual(records[0], records[1])
            self.assertEqual(records[0]['canonical_reconstruct'], 2 if flag else 4)
            measurements.append(records[0])
            self.assertEqual(counter.parse_invocations, 0)
            self.assertEqual(self._fixture_state(store, ingestor), before)
            cancellation = threading.Event()
            cancellation.set()
            with self.assertRaises(scheduling.LeaseCancelledError):
                self._fixture_load(root, page, actor=actor, cancel_event=cancellation)
            cancellation.clear()
            def cancel_after_decode(projection, raw):
                cancellation.set()
            with self._fixture_context_hook(cancel_after_decode) as observed, self.assertRaises(scheduling.LeaseCancelledError):
                self._fixture_load(root, page, actor=actor, cancel_event=cancellation)
            self.assertTrue(observed['fired'])
            self.assertEqual(self._fixture_state(store, ingestor), before)
            cancellation.clear()
            self.assertEqual(self._fixture_body(self._fixture_load(root, page, actor=actor)), expected)
        for name in ('read_calls', 'read_bytes', 'checkpoints'):
            self.assertEqual(measurements[0][name], measurements[1][name])


def load_suite():
    if not API_READY or OWNED_RESOURCES is None:
        raise AssertionError('qualification requires reviewed API and actual owned child resources')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPreparationProjectionBytes)
    names = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if names != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 7:
        raise AssertionError('finite projection byte-count case inventory differs')
    return suite


if __name__ == '__main__':
    unittest.main()

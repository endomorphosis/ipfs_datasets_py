"""Focused operation-local saved-wrapper decode controls; root runs qualification.

These seven controls use real private CAS leaves and Python AST staging with a
memory-only store. They qualify decode reuse, full projection equality, byte
budgets, callback detachment, and existing live fences. The head-fence injection
is an inert call-path control; the separate SQL suite covers real catalog heads.
No target module, DuckDB backend, model or training workload runs in this suite.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from ipfs_datasets_py.logic.software_contracts import codebase_preparation as protocol
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_projection as codec
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_runtime as runtime_module
from ipfs_datasets_py.logic.software_contracts import python_frontend as frontend_module
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import CountingFrontend, DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduling


CASE_NAMES = (
    'exact_boolean_defaults_optout_full_reference_parity',
    'cached_wrapper_rewrite_refusal_preserves_state',
    'cached_wrapper_custody_replacement_and_optout',
    'checkpoint_alias_mutation_cannot_poison_cache',
    'warmed_cache_context_head_and_cancellation_fences',
    'duplicate_reads_charge_bytes_and_enforce_bounds',
    'bounded_cache_fallback_and_operation_reset',
)
API_READY = True
OWNED_RESOURCES = None
MIB = 1024 * 1024
AT = 1700000000.0
VIEW = 'wrapper-decode:authored-fixture'
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


class _OSReadDelegate:
    """Replace only the selected protocol module's os attribute, never stdlib os."""
    def __init__(self, original, inode, replace_once):
        self.original, self.inode, self.replace_once = original, inode, replace_once
        self.fired = False

    def __getattr__(self, name):
        return getattr(self.original, name)

    def read(self, descriptor, maximum):
        part = self.original.read(descriptor, maximum)
        if (part and not self.fired
                and self.original.fstat(descriptor).st_ino == self.inode):
            self.fired = True
            self.replace_once()
        return part


class TestPreparationWrapperDecode(unittest.TestCase):
    def setUp(self):
        if not API_READY:
            raise AssertionError('root must bind the reviewed wrapper decode API')
        parent = OWNED_RESOURCES[0] if OWNED_RESOURCES is not None else None
        self.temporary = tempfile.TemporaryDirectory(prefix='wrapper-decode-', dir=parent)
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
            artifacts=self.artifacts, ingestor=ingestor, optimized_wrapper_decode=optimized)
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

    def _fixture_wrapper(self, *, index=0, kind='ast', payload=None):
        raw = b'def plain(value):\n    return value\n'
        entry = SnapshotEntry('plain.py', 'source', len(raw),
                              self.artifacts.put_bytes(raw), captured_bytes=raw).to_dict()
        payload = {'nested': [{'value': 'original'}, [1, True, None]]} if payload is None else payload
        value = protocol.build_preparation_artifact(entry,
            cid_for_structured({'authored-context-index': index}), kind, payload)
        cid = self.artifacts.put(value)
        return cid, value, canonical_dag_json_bytes(value)

    def _fixture_reader(self, optimized=False, *, limits=None, checkpoint=None, **caps):
        return protocol._Reader(self.artifacts, self.limits if limits is None else limits,
                                checkpoint, optimized_decode=optimized, **caps)

    def _fixture_replace(self, target, raw):
        temporary = target.with_name(target.name + '.replacement')
        self.assertFalse(temporary.exists())
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'wb', closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)

    def _fixture_after_warm(self, target_cid, action):
        """Run a callback at the next real checkpoint after one AST read returns."""
        original_read = protocol._Reader.read
        observed = {'armed': False, 'fired': False, 'reader': None, 'alias': None}
        def read(reader, cid, **kwargs):
            value = original_read(reader, cid, **kwargs)
            if cid == target_cid and not observed['armed']:
                observed.update(armed=True, reader=reader, alias=value[0])
                original_checkpoint = reader.checkpoint
                def checkpoint():
                    if not observed['fired']:
                        observed['fired'] = True
                        action(reader, observed['alias'])
                    if original_checkpoint is not None:
                        original_checkpoint()
                reader.checkpoint = checkpoint
            return value
        return patch.object(protocol._Reader, 'read', new=read), observed

    def test_exact_boolean_defaults_optout_full_reference_parity(self):
        self.assertTrue(self.runtime.optimized_wrapper_decode)
        cid, body, raw = self._fixture_wrapper()
        baseline = protocol._Reader(self.artifacts, self.limits, None)
        self.assertFalse(baseline.optimized_decode)
        self.assertEqual(baseline.read(cid)[0], body)
        self.assertEqual(baseline.read(cid)[0], body)
        self.assertEqual((baseline.read_calls, baseline.structured_decodes,
                          baseline.decode_cache_hits, baseline.read_bytes), (2, 2, 0, 2 * len(raw)))
        for flag in (None, 0, 1, 'true', [], {}):
            with self.subTest(flag=repr(flag)):
                with self.assertRaises(ValueError):
                    runtime_module.RepositoryCodebasePreparation(
                        artifacts=self.artifacts, ingestor=self.ingestor, optimized_wrapper_decode=flag)
                with self.assertRaises(ValueError):
                    self._fixture_reader(flag)
        root, _ = self._fixture_start(18)
        first = self._fixture_page(root)
        last = self._fixture_page(root, first.next_cursor)
        before = self._fixture_state()
        reference, reference_counter = self._fixture_reference(root)
        rows = []
        for flag in (True, False):
            store, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
            actor_before = self._fixture_state(store, ingestor)
            collected = []
            original_root = actor._root
            def opening(*args, **kwargs):
                result = original_root(*args, **kwargs)
                collected.append(result[2])
                return result
            with patch.object(actor, '_root', side_effect=opening):
                actual = self._fixture_load(root, last, actor=actor)
            self.assertEqual(tuple(asdict(row) for row in actual), tuple(asdict(row) for row in reference))
            self.assertEqual(self._fixture_body(actual), self._fixture_body(reference))
            self.assertEqual(len(actual), 18)
            self.assertEqual(counter.parse_invocations, 0)
            self.assertEqual(self._fixture_state(store, ingestor), actor_before)
            self.assertEqual(len(collected), 1)
            reader = collected[0]
            self.assertGreater(reader.read_calls, 18)
            self.assertGreater(reader.read_bytes, 0)
            self.assertEqual(reader.decode_cache_hits, 18 if flag else 0)
            self.assertLessEqual(reader.decode_cache_bytes, reader.max_cache_bytes)
            self.assertLessEqual(reader.decode_cache_heap_bytes, reader.max_cache_heap_bytes)
            rows.append((reader.read_calls, reader.read_bytes, reader.structured_decodes))
        self.assertEqual(rows[0][:2], rows[1][:2])
        self.assertEqual(rows[1][2] - rows[0][2], 18)
        self.assertEqual((self.counter.parse_invocations, reference_counter.parse_invocations), (18, 18))
        self.assertEqual(self._fixture_state(), before)
        for flag in (None, 0, 'true'):
            self.runtime.optimized_wrapper_decode = flag
            try:
                with self.assertRaises(ValueError): self._fixture_load(root, last)
            finally:
                self.runtime.optimized_wrapper_decode = True

    def test_cached_wrapper_rewrite_refusal_preserves_state(self):
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        cid = page.to_dict()['entries'][0]['ast_artifact']['cid']
        target = self.artifacts.path_for(cid)
        original = target.read_bytes()
        body = json.loads(original)
        coherent = copy.deepcopy(body)
        coherent['payload']['decision']['detail'] = 'coherently resealed under wrong admitted CID'
        variants = (b'{' + original[1:-1] + b',"kind":"ast"}', original + b'\n',
                    canonical_dag_json_bytes(coherent), b'{"corrupt":')
        before = self._fixture_state()
        for flag in (True, False):
            _, counter, ingestor, actor = self._fixture_receiver(optimized=flag)
            actor_before = self._fixture_state(ingestor.store, ingestor)
            for changed in variants:
                target.write_bytes(original)
                def rewrite(reader, alias):
                    if flag: self.assertGreater(reader.decode_cache_bytes, 0)
                    target.write_bytes(changed)
                manager, observed = self._fixture_after_warm(cid, rewrite)
                try:
                    with self.subTest(flag=flag, changed=changed[:20]), manager, self.assertRaises(REFUSALS):
                        self._fixture_load(root, page, actor=actor)
                    self.assertTrue(observed['armed'] and observed['fired'])
                    self.assertEqual(self._fixture_state(ingestor.store, ingestor), actor_before)
                    self.assertEqual(counter.parse_invocations, 0)
                finally:
                    target.write_bytes(original)
        self.assertEqual(self._fixture_state(), before)
        self.assertEqual(len(self._fixture_load(root, page)), 1)

    def test_cached_wrapper_custody_replacement_and_optout(self):
        cid, body, raw = self._fixture_wrapper()
        target = self.artifacts.path_for(cid)
        for flag in (True, False):
            for mutation in ('replace', 'touch'):
                reader = self._fixture_reader(flag)
                self.assertEqual(reader.read(cid)[0], body)
                before = target.stat()
                if mutation == 'replace':
                    self._fixture_replace(target, raw)
                    self.assertNotEqual(before.st_ino, target.stat().st_ino)
                else:
                    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000))
                    self.assertNotEqual(before.st_mtime_ns, target.stat().st_mtime_ns)
                with self.subTest(flag=flag, mutation=mutation):
                    if flag:
                        with self.assertRaisesRegex(ValueError, 'custody|cached wrapper'):
                            reader.read(cid)
                    else:
                        self.assertEqual(reader.read(cid)[0], body)
                        self.assertEqual((reader.structured_decodes, reader.decode_cache_hits), (2, 0))
        # Replacing a named leaf while its descriptor is held is refused by both
        # paths, even when the old descriptor yields the original valid bytes.
        for flag in (True, False):
            reader = self._fixture_reader(flag)
            reader.read(cid)
            delegate = _OSReadDelegate(os, target.stat().st_ino,
                                       lambda: self._fixture_replace(target, raw))
            with self.subTest(during_read=flag), patch.object(protocol, 'os', delegate):
                with self.assertRaisesRegex(ValueError, 'changed during read'):
                    reader.read(cid)
            self.assertTrue(delegate.fired)
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        ast_cid = page.to_dict()['entries'][0]['ast_artifact']['cid']
        ast_target = self.artifacts.path_for(ast_cid)
        ast_raw = ast_target.read_bytes()
        for flag in (True, False):
            store, _, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            manager, observed = self._fixture_after_warm(ast_cid,
                lambda reader, alias: self._fixture_replace(ast_target, ast_raw))
            with manager:
                if flag:
                    with self.assertRaisesRegex(ValueError, 'custody|cached wrapper'):
                        self._fixture_load(root, page, actor=actor)
                else:
                    restored = self._fixture_load(root, page, actor=actor)
                    self.assertEqual(len(restored), 1)
            self.assertTrue(observed['fired'])
            self.assertEqual(self._fixture_state(store, ingestor), before)

    def test_checkpoint_alias_mutation_cannot_poison_cache(self):
        cid, body, raw = self._fixture_wrapper()
        for flag in (True, False):
            calls = []
            alias = []
            def checkpoint():
                calls.append(1)
                if alias:
                    alias[0]['payload']['nested'][0]['value'] = 'checkpoint alias poison'
                    alias.clear()
            reader = self._fixture_reader(flag, checkpoint=checkpoint)
            first, _ = reader.read(cid)
            alias.append(first)
            second, _ = reader.read(cid)
            self.assertEqual(second, body)
            self.assertNotEqual(first, body)
            self.assertIsNot(first['payload'], second['payload'])
            self.assertIsNot(first['payload']['nested'], second['payload']['nested'])
            second['payload']['nested'][1].append('returned list poison')
            third, _ = reader.read(cid)
            self.assertEqual(third, body)
            self.assertEqual((reader.read_calls, reader.read_bytes, len(calls)), (3, 3 * len(raw), 6))
            self.assertEqual(reader.structured_decodes, 1 if flag else 3)
            self.assertEqual(reader.decode_cache_hits, 2 if flag else 0)
        root, _ = self._fixture_start(2)
        page = self._fixture_page(root)
        cid = page.to_dict()['entries'][0]['ast_artifact']['cid']
        expected = self._fixture_body(self._fixture_load(root, page))
        for flag in (True, False):
            store, _, ingestor, actor = self._fixture_receiver(optimized=flag)
            before = self._fixture_state(store, ingestor)
            def mutate(reader, alias):
                alias['payload']['decision']['detail'] = 'borrowed callback detail'
                alias['payload']['projection']['ast_blob']['parse_status'] = 'borrowed invalid state'
            manager, observed = self._fixture_after_warm(cid, mutate)
            with manager:
                actual = self._fixture_load(root, page, actor=actor)
            self.assertTrue(observed['fired'])
            self.assertEqual(self._fixture_body(actual), expected)
            self.assertEqual(self._fixture_state(store, ingestor), before)

    def test_warmed_cache_context_head_and_cancellation_fences(self):
        root, sources = self._fixture_start(2)
        page = self._fixture_page(root)
        cid = page.to_dict()['entries'][0]['ast_artifact']['cid']
        before = self._fixture_state()
        changed_implementation = self.workspace / 'authored-different-frontend.py'
        changed_implementation.write_bytes(Path(frontend_module.__file__).read_bytes()
                                           + b'\n# authored implementation context drift\n')
        for flag in (True, False):
            store, _, ingestor, actor = self._fixture_receiver(optimized=flag)
            original_state = self._fixture_state(store, ingestor)
            native = ingestor._frontends['python']._frontend
            manager, observed = self._fixture_after_warm(cid,
                lambda reader, alias: setattr(native, 'max_ast_depth', native.max_ast_depth - 1))
            original_depth = native.max_ast_depth
            try:
                with self.subTest(flag=flag, fence='options'), manager, self.assertRaises(ValueError):
                    self._fixture_load(root, page, actor=actor)
                self.assertTrue(observed['fired'])
            finally:
                native.max_ast_depth = original_depth
            original_file = frontend_module.__file__
            manager, observed = self._fixture_after_warm(cid,
                lambda reader, alias: setattr(frontend_module, '__file__', str(changed_implementation)))
            try:
                with self.subTest(flag=flag, fence='implementation'), manager, self.assertRaises(ValueError):
                    self._fixture_load(root, page, actor=actor)
                self.assertTrue(observed['fired'])
            finally:
                frontend_module.__file__ = original_file
            cancellation = threading.Event()
            manager, observed = self._fixture_after_warm(cid, lambda reader, alias: cancellation.set())
            with self.subTest(flag=flag, fence='cancel'), manager, self.assertRaises(scheduling.LeaseCancelledError):
                self._fixture_load(root, page, actor=actor, cancel_event=cancellation)
            self.assertTrue(observed['fired'])
            for mutation in ('source', 'membership'):
                source = self.repository / 'source001.py'
                extra = self.repository / 'added.py'
                def drift(reader, alias):
                    if mutation == 'source': source.write_bytes(b'def changed():\n    return 99\n')
                    else: extra.write_bytes(b'def added():\n    return 1\n')
                manager, observed = self._fixture_after_warm(cid, drift)
                try:
                    with self.subTest(flag=flag, fence=mutation), manager, self.assertRaises(ValueError):
                        actor.validate_current(self.repository, root.artifact_cid, page.next_cursor,
                            admitted_page_cid=page.artifact_cid, **self._fixture_resources())
                    self.assertTrue(observed['fired'])
                finally:
                    source.write_bytes(sources['source001.py'])
                    extra.unlink(missing_ok=True)
            head_calls = []
            head_changed = []
            original_head_fence = actor._head_fence
            def head_fence(repository_id, expected):
                head_calls.append((repository_id, expected))
                if head_changed:
                    raise runtime_module.CodebasePreparationRuntimeError('authored head-fence refusal')
                return original_head_fence(repository_id, expected)
            manager, observed = self._fixture_after_warm(cid, lambda reader, alias: head_changed.append(True))
            with self.subTest(flag=flag, fence='inert-head-call'), manager, patch.object(
                    actor, '_head_fence', side_effect=head_fence), self.assertRaisesRegex(ValueError, 'head-fence'):
                actor.validate_current(self.repository, root.artifact_cid, page.next_cursor,
                    admitted_page_cid=page.artifact_cid, **self._fixture_resources())
            self.assertTrue(observed['fired'])
            self.assertTrue(head_calls)
            self.assertEqual(self._fixture_state(store, ingestor), original_state)
        self.assertEqual(self._fixture_state(), before)

    def test_duplicate_reads_charge_bytes_and_enforce_bounds(self):
        cid, body, raw = self._fixture_wrapper()
        for flag in (True, False):
            for maximum in (len(raw) - 1, 0):
                reader = self._fixture_reader(flag)
                reader.read(cid)
                with self.subTest(flag=flag, maximum=maximum), self.assertRaises(ValueError):
                    reader.read(cid, maximum=maximum)
                self.assertEqual(reader.read_bytes, len(raw))
                self.assertEqual(reader.read_calls, 1)
            exact = replace(self.limits, max_prefix_read_bytes=2 * len(raw))
            reader = self._fixture_reader(flag, limits=exact)
            self.assertEqual(reader.read(cid)[0], body)
            self.assertEqual(reader.read(cid)[0], body)
            self.assertEqual((reader.read_calls, reader.read_bytes), (2, 2 * len(raw)))
            with self.assertRaises(ValueError): reader.read(cid)
            self.assertEqual((reader.read_calls, reader.read_bytes), (2, 2 * len(raw)))
            below = replace(self.limits, max_prefix_read_bytes=2 * len(raw) - 1)
            reader = self._fixture_reader(flag, limits=below)
            reader.read(cid)
            with self.assertRaises(ValueError): reader.read(cid)
            self.assertEqual(reader.read_bytes, len(raw))
            checkpoints = []
            def cancel_after_warm():
                checkpoints.append(1)
                if len(checkpoints) == 3:
                    raise scheduling.LeaseCancelledError('authored duplicate-read cancellation')
            reader = self._fixture_reader(flag, checkpoint=cancel_after_warm)
            reader.read(cid)
            with self.assertRaises(scheduling.LeaseCancelledError): reader.read(cid)
            self.assertEqual((reader.read_calls, reader.read_bytes, len(checkpoints)), (1, len(raw), 3))
        source = self.artifacts.put_bytes(b'raw source must never enter the decoded-wrapper cache')
        non_ast, _, non_ast_raw = self._fixture_wrapper(kind='semantic')
        reader = self._fixture_reader(True)
        self.assertEqual(reader.read(source, source=True)[0],
                         b'raw source must never enter the decoded-wrapper cache')
        reader.read(source, source=True)
        reader.read(non_ast); reader.read(non_ast)
        self.assertEqual((reader.decode_cache_bytes, reader.decode_cache_heap_bytes,
                          reader.decode_cache_hits, reader.structured_decodes), (0, 0, 0, 2))
        self.assertEqual(reader.read_bytes, 2 * len(b'raw source must never enter the decoded-wrapper cache')
                         + 2 * len(non_ast_raw))

    def test_bounded_cache_fallback_and_operation_reset(self):
        cid, body, raw = self._fixture_wrapper()
        self.assertEqual((protocol.MAX_DECODE_CACHE_BYTES, protocol.MAX_DECODE_CACHE_HEAP_BYTES,
                          protocol.MAX_DECODE_CACHE_MEMBERS), (8 * MIB, 64 * MIB, 1024))
        for caps in ({'max_cache_bytes': len(raw) - 1}, {'max_cache_heap_bytes': 1023},
                     {'max_cache_bytes': 0}, {'max_cache_heap_bytes': 0}):
            reader = self._fixture_reader(True, **caps)
            with self.subTest(caps=caps):
                self.assertEqual(reader.read(cid)[0], body)
                self.assertEqual(reader.read(cid)[0], body)
                self.assertEqual((reader.structured_decodes, reader.decode_cache_hits,
                                  reader.decode_cache_bytes, reader.decode_cache_heap_bytes), (2, 0, 0, 0))
                self.assertEqual(reader.read_bytes, 2 * len(raw))
        # Large payload storage must count toward the heap cap, beyond the
        # fixed entry overhead; a successful miss still revalidates fresh bytes.
        large_cid, large_body, large_raw = self._fixture_wrapper(index=2000,
            payload={'large-retained-string': 'x' * (32 * 1024)})
        reader = self._fixture_reader(True, max_cache_heap_bytes=4096)
        self.assertEqual(reader.read(large_cid)[0], large_body)
        self.assertEqual(reader.read(large_cid)[0], large_body)
        self.assertEqual((reader.structured_decodes, reader.decode_cache_hits,
                          reader.decode_cache_heap_bytes, reader.read_bytes),
                         (2, 0, 0, 2 * len(large_raw)))
        second_cid, second_body, _ = self._fixture_wrapper(index=2001)
        reader = self._fixture_reader(True, max_cache_bytes=len(raw))
        reader.read(cid)
        reader.read(second_cid); reader.read(second_cid)
        self.assertEqual(reader.read(cid)[0], body)
        self.assertEqual((reader.decode_cache_bytes, reader.decode_cache_hits), (len(raw), 1))
        self.assertEqual(reader.structured_decodes, 3)
        for caps in ({'max_cache_bytes': -1}, {'max_cache_heap_bytes': -1},
                     {'max_cache_bytes': True}, {'max_cache_heap_bytes': 1.0},
                     {'max_cache_bytes': 8 * MIB + 1}, {'max_cache_heap_bytes': 64 * MIB + 1}):
            with self.subTest(invalid=caps), self.assertRaises(ValueError):
                self._fixture_reader(True, **caps)
        target = self.artifacts.path_for(cid)
        linked = self.workspace / 'same-body-hardlink'
        os.link(target, linked)
        try:
            self.assertEqual(target.stat().st_nlink, 2)
            reader = self._fixture_reader(True)
            self.assertEqual(reader.read(cid)[0], body)
            self.assertEqual(reader.read(cid)[0], body)
            self.assertEqual((reader.structured_decodes, reader.decode_cache_hits,
                              reader.decode_cache_bytes), (2, 0, 0))
        finally:
            linked.unlink()
        populated = self._fixture_reader(True)
        wrappers = [self._fixture_wrapper(index=index + 1) for index in range(1025)]
        for member_cid, member_body, _ in wrappers:
            self.assertEqual(populated.read(member_cid)[0], member_body)
        self.assertLessEqual(populated.decode_cache_bytes, 8 * MIB)
        self.assertGreaterEqual(populated.decode_cache_heap_bytes, 1024 * 1024)
        self.assertLessEqual(populated.decode_cache_heap_bytes, 64 * MIB)
        self.assertEqual(populated.decode_cache_hits, 0)
        self.assertEqual(populated.decode_cache_bytes, sum(len(row[2]) for row in wrappers[:1024]))
        first_cid, first_body, _ = wrappers[0]
        self.assertEqual(populated.read(first_cid)[0], first_body)
        self.assertEqual(populated.decode_cache_hits, 1)
        eligible_cid, eligible_body, _ = wrappers[1023]
        self.assertEqual(populated.read(eligible_cid)[0], eligible_body)
        self.assertEqual(populated.decode_cache_hits, 2)
        last_cid, last_body, _ = wrappers[-1]
        self.assertEqual(populated.read(last_cid)[0], last_body)
        self.assertEqual(populated.decode_cache_hits, 2)
        self.assertEqual(populated.structured_decodes, 1026)
        warmed = self._fixture_reader(True)
        warmed.read(cid); warmed.read(cid)
        self.assertEqual(warmed.decode_cache_hits, 1)
        self._fixture_replace(target, raw)
        fresh = self._fixture_reader(True)
        self.assertEqual(fresh.read(cid)[0], body)
        self.assertEqual((fresh.structured_decodes, fresh.decode_cache_hits, fresh.read_calls), (1, 0, 1))
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        wrapper_cid = page.to_dict()['entries'][0]['ast_artifact']['cid']
        wrapper_path = self.artifacts.path_for(wrapper_cid)
        original = wrapper_path.read_bytes()
        expected = self._fixture_body(self._fixture_load(root, page))
        self._fixture_replace(wrapper_path, original)
        self.assertEqual(self._fixture_body(self._fixture_load(root, page)), expected)
        # A deeply nested body is valid on the ordinary JSON path. A retained
        # seed must thaw safely or use the ordinary fallback, never fail only
        # on the optimized second read. Compare canonical bytes to avoid a
        # unittest deep-diff helper introducing its own recursion semantics.
        nested = {'leaf': 'deep-original'}
        for _ in range(600):
            nested = {'child': nested}
        deep_cid, _, deep_raw = self._fixture_wrapper(index=3000, payload=nested)
        for flag in (True, False):
            reader = self._fixture_reader(flag)
            for _ in range(2):
                value, size = reader.read(deep_cid)
                self.assertEqual((canonical_dag_json_bytes(value), size), (deep_raw, len(deep_raw)))
            self.assertEqual((reader.read_calls, reader.read_bytes), (2, 2 * len(deep_raw)))
            if not flag:
                self.assertEqual((reader.structured_decodes, reader.decode_cache_hits), (2, 0))
        # The cache key retains the absolute path string. Long canonical paths
        # must consume their measured heap too, rather than a fixed 1024-byte
        # allowance silently admitting unlimited pathname storage.
        ordinary = self._fixture_reader(True)
        ordinary.read(cid)
        long_root = self.workspace
        for index in range(24):
            long_root = long_root / (f'cache-segment-{index:02d}-' + 'p' * 64)
        long_artifacts = ImmutableCAS(long_root, max_object_bytes=4 * MIB)
        self.assertEqual(long_artifacts.put(body), cid)
        longer = protocol._Reader(long_artifacts, self.limits, None, optimized_decode=True)
        longer.read(cid)
        extra_path = len(str(long_artifacts.path_for(cid).absolute())) - len(str(target.absolute()))
        self.assertGreater(extra_path, 1024)
        self.assertGreaterEqual(longer.decode_cache_heap_bytes - ordinary.decode_cache_heap_bytes, extra_path)
        limited = protocol._Reader(long_artifacts, self.limits, None, optimized_decode=True,
                                   max_cache_heap_bytes=ordinary.decode_cache_heap_bytes + extra_path - 1)
        self.assertEqual(limited.read(cid)[0], body)
        self.assertEqual(limited.read(cid)[0], body)
        self.assertEqual((limited.structured_decodes, limited.decode_cache_hits,
                          limited.decode_cache_heap_bytes), (2, 0, 0))
        # A zero-spare source reservation is valid but permits no retained memo.
        no_spare = runtime_module.RepositoryCodebasePreparation(
            artifacts=self.artifacts, ingestor=self.ingestor)
        _, _, reader = no_spare._root(root.artifact_cid, lambda: None, memory_mb=64)
        self.assertEqual((reader.max_cache_bytes, reader.max_cache_heap_bytes), (0, 0))
        with self.assertRaises(ValueError):
            no_spare._root(root.artifact_cid, lambda: None, memory_mb=63)


def load_suite():
    if not API_READY or OWNED_RESOURCES is None:
        raise AssertionError('qualification requires reviewed API and actual owned child resources')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPreparationWrapperDecode)
    names = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if names != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 7:
        raise AssertionError('finite wrapper decode case inventory differs')
    return suite


if __name__ == '__main__':
    unittest.main()

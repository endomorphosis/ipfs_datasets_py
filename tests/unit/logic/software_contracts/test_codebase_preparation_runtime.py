"""Live, owner-admitted AST staging controls; no SQL or semantic assembly.

Every fixture lives in the admitted child's private workspace. These controls
exercise real snapshot acquisition and Python extraction, complete projection
envelopes, source/context fences and immutable page admission. Cold objects in
this suite are same-interpreter receivers; the campaign separately qualifies
the producer/resumer interpreter boundary. No partial page publishes a head.
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
from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord, DiagnosticRecord, SourceProvenance, SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    DuckDBASTStore, project_ast_record, project_parse_failure,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import (
    CountingFrontend, DuckDBASTIngestor,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot, SnapshotEntry,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduling


CASE_NAMES = (
    'start_current_seals_complete_inventory_no_publication',
    'page_one_preserves_in_memory_store',
    'complete_34_projection_reference_parity',
    'restart_reuses_prefix_without_parsing',
    'projection_codec_all_family_metadata_and_clock',
    'parse_failed_opaque_unsupported_dispositions',
    'source_edit_add_delete_rename_refusal',
    'context_options_implementation_refusal',
    'expected_head_unavailable_or_changed_refusal',
    'cursor_and_missing_corrupt_artifact_refusal',
    'admitted_page_coherent_forgery_refusal',
    'cancellation_before_after_page_seal',
    'closing_source_context_fences',
    'custom_frontend_cannot_gain_durable_admission',
)
OWNED_RESOURCES = None
AT = 2.0
VIEW = 'live-preparation:fixture'
MIB = 1024 * 1024
REFUSALS = (ValueError, TypeError, FileNotFoundError, OSError)
RICH = (b'from other import helper\nshared = 0\n'
        b'def step(n: int) -> int:\n    global shared\n    shared = n\n'
        b'    return helper(n) + 1\n')


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
        raise ValueError('actual admitted private workspace/scheduler/child lease required')
    OWNED_RESOURCES = workspace, scheduler, parent_lease


class _UnqualifiedFrontend:
    """Fresh extraction is valid; its undeclared wrapper cannot gain reuse."""
    def __init__(self):
        self.native = PythonASTExtractor()

    @property
    def capability(self):
        return self.native.capability

    def extract_from_source(self, *args, **kwargs):
        return self.native.extract_from_source(*args, **kwargs)


class _FixtureHeadInput:
    """Inert shape only, used to refuse absent catalog ownership."""
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def to_dict(self):
        return copy.deepcopy(self.value)


class TestLivePreparationExtraction(unittest.TestCase):
    def setUp(self):
        parent = OWNED_RESOURCES[0] if OWNED_RESOURCES is not None else None
        self.temporary = tempfile.TemporaryDirectory(prefix='live-preparation-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.repository = self.workspace / 'repository'
        self.repository.mkdir(mode=0o700)
        self.artifacts = ImmutableCAS(self.workspace / 'artifacts', max_object_bytes=4 * MIB)
        self.limits = protocol.CodebasePreparationLimits(max_entries=64, page_entries=16)
        self.store, self.counter, self.ingestor, self.runtime = self._fixture_receiver()
        if OWNED_RESOURCES is None:
            # Ordinary CI creates only test-private state, never ambient MAIN.
            healthy = scheduling.ProofHostResources(4, 2048, 2048)
            configuration = scheduling.ResourceSchedulerConfig.for_proof_host(
                state_path=self.workspace / 'admission.json', lane_reservations={},
                proof_resource_sampler=lambda: healthy, auto_renew_leases=False,
                poll_interval_seconds=0.005, proof_backoff_seconds=0.02)
            self.scheduler, self.parent_lease = scheduling.GlobalResourceScheduler(configuration), None
        else:
            _, self.scheduler, self.parent_lease = OWNED_RESOURCES

    def _fixture_receiver(self, *, optimized=True, artifacts=None, frontend=None):
        store = DuckDBASTStore(connection=None)
        counter = CountingFrontend(PythonASTExtractor()) if frontend is None else frontend
        ingestor = DuckDBASTIngestor(store=store, frontends={'python': counter})
        runtime = runtime_module.RepositoryCodebasePreparation(
            artifacts=self.artifacts if artifacts is None else artifacts,
            ingestor=ingestor, optimized_resume=optimized)
        return store, counter, ingestor, runtime

    def _fixture_resources(self, **overrides):
        result = {'scheduler': self.scheduler if self.parent_lease is None else None,
                  'parent_lease': self.parent_lease, 'memory_mb': 512,
                  'timeout_seconds': 120.0, 'admission_timeout_seconds': 30.0}
        result.update(overrides)
        return result

    def _fixture_sources(self, count=34):
        sources = {f'source{index:03d}.py':
                   f'def step{index}(value: int) -> int:\n    return value + {index}\n'.encode()
                   for index in range(count)}
        if count > 0: sources['source000.py'] = RICH
        if count > 16:
            sources['source015.py'] = b'def boundary(value):\n    return value + 15\n'
            sources['source016.py'] = b'from source015 import boundary\ndef cross_page(value):\n    return boundary(value)\n'
        if count > 32:
            sources['source031.py'] = b'def second_boundary(value):\n    return value + 31\n'
            sources['source032.py'] = b'from source031 import second_boundary\ndef another_cross_page(value):\n    return second_boundary(value)\n'
        for name, raw in sources.items(): (self.repository / name).write_bytes(raw)
        return sources

    def _fixture_start(self, count=34, *, created_at=AT):
        sources = self._fixture_sources(count)
        root = self.runtime.start_current(self.repository, repository_id=VIEW,
            limits=self.limits, created_at=created_at, **self._fixture_resources())
        return root, sources

    def _fixture_page(self, root, cursor=None, *, actor=None, admitted=None, **resources):
        actor = self.runtime if actor is None else actor
        if cursor is not None and admitted is None: admitted = cursor.previous_page_cid
        return actor.prepare_page(self.repository, root.artifact_cid, cursor,
            admitted_page_cid=admitted, **self._fixture_resources(**resources))

    def _fixture_load(self, root, cursor, *, actor=None, admitted=None):
        actor = self.runtime if actor is None else actor
        if admitted is None and cursor is not None: admitted = cursor.previous_page_cid
        return actor.load_projections(root.artifact_cid, cursor, admitted_page_cid=admitted,
                                      **self._fixture_resources())

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
                    ('revisions_published', 'parse_invocations', 'reuse_hits', 'invalidations', 'publication_count')}}

    def _fixture_reference(self, root):
        snapshot = RepositorySnapshot.from_dict(root.to_dict()['snapshot'])
        entries = []
        for entry in snapshot.entries:
            raw = None if entry.is_opaque else (self.repository / entry.path).read_bytes()
            if raw is not None: self.assertEqual(cid_for_bytes(raw), entry.source_cid)
            entries.append(replace(entry, captured_bytes=raw))
        captured = replace(snapshot, entries=tuple(entries))
        store = DuckDBASTStore(connection=None)
        frontend = CountingFrontend(PythonASTExtractor())
        ingestor = DuckDBASTIngestor(store=store, frontends={'python': frontend})
        publication = ingestor.ingest_snapshot(captured, created_at=AT)
        return publication, frontend

    def _fixture_projections(self, projections):
        return tuple(codec.encode_preparation_projection(row) for row in projections)

    def test_start_current_seals_complete_inventory_no_publication(self):
        before = self._fixture_state()
        root, sources = self._fixture_start()
        body = root.to_dict()
        self.assertEqual(len(body['snapshot']['entries']), 34)
        self.assertEqual({row['path'] for row in body['snapshot']['entries']}, set(sources))
        for entry in body['snapshot']['entries']:
            self.assertEqual(self.artifacts.get_bytes(entry['source_cid']), sources[entry['path']])
        self.assertEqual(protocol.load_preparation_root(self.artifacts, root.artifact_cid), root)
        self.assertEqual(self.counter.parse_invocations, 0)
        self.assertEqual(self._fixture_state(), before)
        self.assertTrue(all(flag is False for flag in body['authority'].values()))
        inside = ImmutableCAS(self.repository / 'forbidden-cas', max_object_bytes=4 * MIB)
        _, _, _, actor = self._fixture_receiver(artifacts=inside)
        with self.assertRaises(ValueError):
            actor.start_current(self.repository, repository_id=VIEW, limits=self.limits,
                                created_at=AT, **self._fixture_resources())
        # Canonical CAS root placement also constrains its namespace and
        # current RAW shard directories. A source/structured namespace or
        # source/bafk symlink into ignored repository storage cannot be used to
        # hide artifact writes from the complete inventory fence.
        hidden = self.repository / '.git'
        hidden.mkdir(mode=0o700)
        for label in ('source-namespace', 'structured-namespace', 'source-shard'):
            storage = ImmutableCAS(self.workspace / ('outside-' + label), max_object_bytes=4 * MIB)
            if label == 'source-shard':
                redirected = storage.source_root / 'bafk'
            else:
                redirected = storage.source_root if label == 'source-namespace' else storage.structured_root
                redirected.rmdir()
            redirected.symlink_to(hidden, target_is_directory=True)
            _, counter, ingestor, candidate = self._fixture_receiver(artifacts=storage)
            original_state = self._fixture_state(ingestor.store, ingestor)
            try:
                with patch.object(storage, '_publish', wraps=storage._publish) as publication:
                    with self.subTest(storage=label), self.assertRaisesRegex(
                            runtime_module.CodebasePreparationRuntimeError, 'preparation namespace|preparation shard'):
                        candidate.start_current(self.repository, repository_id=VIEW,
                            limits=self.limits, created_at=AT, **self._fixture_resources())
                    self.assertEqual(publication.call_count, 0)
                self.assertEqual(list(hidden.iterdir()), [])
                self.assertEqual(counter.parse_invocations, 0)
                self.assertEqual(self._fixture_state(ingestor.store, ingestor), original_state)
                self.assertTrue(redirected.is_symlink())
            finally:
                redirected.unlink()
        hidden.rmdir()

    def test_page_one_preserves_in_memory_store(self):
        root, _ = self._fixture_start()
        before = self._fixture_state()
        page = self._fixture_page(root)
        self.assertEqual((page.to_dict()['start'], page.to_dict()['end']), (0, 16))
        self.assertEqual(self.counter.parse_invocations, 16)
        self.assertEqual(self._fixture_state(), before)
        projections = self._fixture_load(root, page.next_cursor)
        self.assertEqual(len(projections), 16)
        self.assertEqual(self.counter.parse_invocations, 16)
        self.assertEqual(self._fixture_state(), before)
        for projection in projections:
            self.assertEqual(projection.source_revision.revision, 'snapshot:' + root.to_dict()['snapshot']['snapshot_cid'])
            self.assertEqual(projection.source_revision.repository_tree_cid, root.to_dict()['snapshot']['snapshot_cid'])

    def test_complete_34_projection_reference_parity(self):
        root, _ = self._fixture_start()
        before = self._fixture_state()
        pages, cursor = [], None
        for _ in range(3):
            page = self._fixture_page(root, cursor); pages.append(page); cursor = page.next_cursor
        prefix = self.runtime.validate_current(self.repository, root.artifact_cid, cursor,
            admitted_page_cid=pages[-1].artifact_cid, **self._fixture_resources())
        self.assertTrue(prefix.inventory_complete)
        self.assertEqual(prefix.pages, tuple(pages))
        self.assertEqual([(p.to_dict()['start'], p.to_dict()['end']) for p in pages], [(0, 16), (16, 32), (32, 34)])
        actual = self._fixture_load(root, cursor)
        reference, parsed = self._fixture_reference(root)
        self.assertEqual(tuple(asdict(p) for p in actual), tuple(asdict(p) for p in reference.projections))
        self.assertEqual(self._fixture_projections(actual), self._fixture_projections(reference.projections))
        self.assertEqual(self.counter.parse_invocations, 34)
        self.assertEqual(parsed.parse_invocations, 34)
        self.assertEqual(self._fixture_state(), before)
        self.assertTrue(all(row['facts_artifact'] is None and row['semantic_disposition'] == 'deferred_budget'
                            for page in pages for row in page.to_dict()['entries']))

    def test_restart_reuses_prefix_without_parsing(self):
        root, _ = self._fixture_start()
        page = self._fixture_page(root)
        first = self._fixture_load(root, page.next_cursor)
        receiver_cas = ImmutableCAS(self.artifacts.root, max_object_bytes=4 * MIB)
        store, counter, ingestor, actor = self._fixture_receiver(artifacts=receiver_cas)
        before = self._fixture_state(store, ingestor)
        self.assertEqual(self._fixture_load(root, page.next_cursor, actor=actor), first)
        self.assertEqual(counter.parse_invocations, 0)
        second = self._fixture_page(root, page.next_cursor, actor=actor)
        third = self._fixture_page(root, second.next_cursor, actor=actor)
        self.assertEqual(counter.parse_invocations, 18)
        actual = self._fixture_load(root, third.next_cursor, actor=actor)
        reference, _ = self._fixture_reference(root)
        self.assertEqual(self._fixture_projections(actual), self._fixture_projections(reference.projections))
        self.assertEqual(self._fixture_state(store, ingestor), before)
        _, optout_counter, _, optout = self._fixture_receiver(optimized=False, artifacts=receiver_cas)
        self.assertEqual(self._fixture_load(root, page.next_cursor, actor=optout), first)
        self.assertEqual(optout_counter.parse_invocations, 16)

    def test_projection_codec_all_family_metadata_and_clock(self):
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        rich = self._fixture_load(root, page.next_cursor)[0]
        provenance = SourceProvenance(source_cid=rich.source_cid, path=rich.source_file.path,
            repository_id=VIEW, revision=rich.source_revision.revision,
            repository_tree_cid=rich.source_revision.repository_tree_cid)
        failure = project_parse_failure(provenance=provenance, language='python',
            message='authored synthetic failure', code='fixture_failure', severity='fatal',
            frontend_name='fixture-parser', frontend_version='fixture-1',
            frontend_toolchain_cid=cid_for_structured({'toolchain': 'fixture'}),
            span=SourceSpan(start_byte=3, end_byte=8, start_line=1, start_column=3,
                            end_line=1, end_column=8),
            created_at=-0.0, actor_id='fixture-actor')
        for projection in (rich, failure):
            body = codec.encode_preparation_projection(projection)
            self.assertEqual(codec.encode_preparation_projection(codec.decode_preparation_projection(body)), body)
            self.assertEqual(asdict(codec.decode_preparation_projection(body)), asdict(projection))
        # Authored partial metadata qualifies the codec's lossless handling,
        # not a claim that native Python extraction produced this diagnostic.
        native_record = ASTRecord.from_json(rich.ast_blob.payload_json)
        partial_record = replace(native_record, diagnostics=(*native_record.diagnostics,
            DiagnosticRecord(code='fixture.partial', severity='error',
                message='authored partial analysis frontier', span=native_record.module.span)))
        partial = project_ast_record(partial_record, created_at=AT)
        self.assertEqual(partial.ast_blob.parse_status, 'partial')
        self.assertEqual(codec.encode_preparation_projection(codec.decode_preparation_projection(
            codec.encode_preparation_projection(partial))), codec.encode_preparation_projection(partial))
        encoded = codec.encode_preparation_projection(failure)
        for family in ('source_revision', 'source_file', 'ast_blob'):
            self.assertEqual(encoded[family]['created_at_hex'], (-0.0).hex())
        self.assertEqual(encoded['diagnostics'][0]['created_at_hex'], (-0.0).hex())
        self.assertEqual(encoded['invalidations'][0]['actor_id'], 'fixture-actor')
        family_fields = {'source_revision': 'revision', 'source_file': 'path', 'ast_blob': 'frontend_name',
            'nodes': 'label', 'scopes': 'kind', 'symbols': 'name', 'imports': 'module',
            'references': 'name', 'calls': 'callee_name', 'effects': 'subject', 'interfaces': 'name',
            'diagnostics': 'message', 'invalidations': 'detail'}
        for family, field in family_fields.items():
            body = codec.encode_preparation_projection(failure if family in ('diagnostics', 'invalidations') else rich)
            row = body[family] if type(body[family]) is dict else body[family][0]
            row[field] = 'corrupt canonical family'
            with self.subTest(family=family), self.assertRaises(ValueError): codec.decode_preparation_projection(body)
        for clock in (True, 0.0, 'nan', '0x1p+0'):
            bad = copy.deepcopy(encoded); bad['ast_blob']['created_at_hex'] = clock
            with self.assertRaises(ValueError): codec.decode_preparation_projection(bad)

    def test_parse_failed_opaque_unsupported_dispositions(self):
        self._fixture_sources(3)
        (self.repository / 'source001.py').write_bytes(b'def broken(:\n')
        (self.repository / 'source002.py').write_bytes(b'')
        (self.repository / 'unsupported.txt').write_bytes(b'unsupported language is explicit\n')
        raw_path = os.fsencode(self.repository) + b'/\xff'
        fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try: os.write(fd, b'opaque raw name\n')
        finally: os.close(fd)
        root = self.runtime.start_current(self.repository, repository_id=VIEW, limits=self.limits,
                                         created_at=AT, **self._fixture_resources())
        page = self._fixture_page(root)
        rows = page.to_dict()['entries']
        self.assertEqual(len(rows), 5)
        self.assertIn('failed', {row['parse_status'] for row in rows})
        self.assertIn('opaque', {row['parse_status'] for row in rows})
        self.assertIn('unindexed', {row['parse_status'] for row in rows})
        self.assertTrue(all(row['facts_artifact'] is None for row in rows))
        actual = self._fixture_load(root, page.next_cursor)
        reference, _ = self._fixture_reference(root)
        self.assertEqual(self._fixture_projections(actual), self._fixture_projections(reference.projections))
        self.assertEqual(len(actual), 3)
        # Native node-bound refusals are explicit failed parses. They use a
        # different contextual root, with the same complete source inventory.
        _, _, _, partial = self._fixture_receiver(frontend=CountingFrontend(PythonASTExtractor(max_ast_nodes=1)))
        partial_root = partial.start_current(self.repository, repository_id=VIEW, limits=self.limits,
                                            created_at=AT, **self._fixture_resources())
        partial_page = self._fixture_page(partial_root, actor=partial)
        self.assertIn('failed', {row['parse_status'] for row in partial_page.to_dict()['entries']})

    def test_source_edit_add_delete_rename_refusal(self):
        root, sources = self._fixture_start()
        page = self._fixture_page(root)
        before = self._fixture_state()
        target = self.repository / 'source017.py'
        for mutation in ('edit', 'add', 'delete', 'rename'):
            added = self.repository / 'added.py'; renamed = self.repository / 'renamed.py'
            try:
                if mutation == 'edit': target.write_bytes(b'def changed():\n    return 99\n')
                elif mutation == 'add': added.write_bytes(b'def added():\n    return 1\n')
                elif mutation == 'delete': target.unlink()
                else: target.rename(renamed)
                count = self.counter.parse_invocations
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    self._fixture_page(root, page.next_cursor)
                self.assertEqual(self.counter.parse_invocations, count)
                self.assertEqual(self._fixture_state(), before)
            finally:
                added.unlink(missing_ok=True); renamed.unlink(missing_ok=True)
                target.write_bytes(sources['source017.py'])
        self.assertEqual(self._fixture_page(root, page.next_cursor).to_dict()['end'], 32)

    def test_context_options_implementation_refusal(self):
        root, _ = self._fixture_start(2)
        page = self._fixture_page(root)
        before = self._fixture_state()
        native = self.counter._frontend
        native.max_ast_depth -= 1
        try:
            with self.assertRaises(ValueError): self._fixture_load(root, page.next_cursor)
        finally: native.max_ast_depth += 1
        implementation = self.workspace / 'changed-frontend-implementation.py'
        implementation.write_bytes(Path(frontend_module.__file__).read_bytes() + b'\n# authored implementation drift\n')
        with patch.object(frontend_module, '__file__', str(implementation)), self.assertRaises(ValueError):
            self._fixture_load(root, page.next_cursor)
        self.assertEqual(self._fixture_state(), before)
        self.assertEqual(len(self._fixture_load(root, page.next_cursor)), 2)
        for flag in (None, 0, 1, 'true'):
            with self.assertRaises(ValueError):
                runtime_module.RepositoryCodebasePreparation(artifacts=self.artifacts, ingestor=self.ingestor,
                                                            optimized_resume=flag)

    def test_expected_head_unavailable_or_changed_refusal(self):
        snapshot = cid_for_structured({'historical': 'snapshot'})
        head = _FixtureHeadInput({'schema': 'codebase-head@1', 'repository_id': VIEW,
            'generation': 1, 'manifest_cid': cid_for_structured({'manifest': 'old'}),
            'snapshot_cid': snapshot, 'ast_revision_id': 'rev:' + VIEW + ':snapshot:' + snapshot,
            'receipt_cid': cid_for_structured({'receipt': 'old'})})
        self._fixture_sources(2)
        before = self._fixture_state()
        with self.assertRaisesRegex(ValueError, 'catalog owner'):
            self.runtime.start_current(self.repository, repository_id=VIEW, expected_head=head,
                limits=self.limits, created_at=AT, **self._fixture_resources())
        # A newly resealed root cannot relabel its captured inventory to an
        # independently unavailable active owner, even with correct head shape.
        root = self.runtime.start_current(self.repository, repository_id=VIEW, limits=self.limits,
                                         created_at=AT, **self._fixture_resources())
        body = root.to_dict(); body['expected_head'] = head.to_dict()
        foreign = self.artifacts.put(body)
        with self.assertRaisesRegex(ValueError, 'catalog owner'):
            self.runtime.validate_current(self.repository, foreign, **self._fixture_resources())
        self.assertEqual(self._fixture_state(), before)

    def test_cursor_and_missing_corrupt_artifact_refusal(self):
        root, _ = self._fixture_start(2)
        page = self._fixture_page(root)
        with self.assertRaises(ValueError):
            self.runtime.validate_current(self.repository, root.artifact_cid, page.next_cursor,
                                          **self._fixture_resources())
        wrong = protocol.PreparationCursor(root.artifact_cid, 1, page.artifact_cid)
        with self.assertRaises(ValueError): self._fixture_load(root, wrong)
        wrapper_cid = page.to_dict()['entries'][0]['ast_artifact']['cid']
        body = root.to_dict()
        refs = [(root.artifact_cid, False), (page.artifact_cid, False), (wrapper_cid, False),
                (body['context']['options_cid'], False), (body['snapshot']['entries'][0]['source_cid'], True)]
        for cid, source in refs:
            target = self.artifacts.path_for(cid, source=source); original = target.read_bytes()
            try:
                target.unlink()
                with self.assertRaises(FileNotFoundError): self._fixture_load(root, page.next_cursor)
                target.write_bytes(b'{}' if not source else b'corrupt captured source')
                with self.assertRaises(REFUSALS): self._fixture_load(root, page.next_cursor)
            finally: target.write_bytes(original)
        self.assertEqual(len(self._fixture_load(root, page.next_cursor)), 2)

    def test_admitted_page_coherent_forgery_refusal(self):
        root, _ = self._fixture_start(1)
        page = self._fixture_page(root)
        body = page.to_dict(); descriptor = body['entries'][0]['ast_artifact']
        wrapper = self.artifacts.get(descriptor['cid'])
        original = codec.decode_preparation_projection(wrapper['payload']['projection'])
        record = ASTRecord.from_json(original.ast_blob.payload_json)
        changed = project_ast_record(record, created_at=AT + 1.0)
        wrapper['payload']['projection'] = codec.encode_preparation_projection(changed)
        self.assertEqual(codec.decode_preparation_projection(wrapper['payload']['projection']), changed)
        body['entries'][0]['ast_artifact'] = {'cid': self.artifacts.put(wrapper),
            'bytes': len(canonical_dag_json_bytes(wrapper))}
        body['entries'][0]['created_at_hex'] = (AT + 1.0).hex()
        forged = protocol.PreparationPage.from_dict(self.artifacts.put(body), body)
        self.assertNotEqual(forged.artifact_cid, page.artifact_cid)
        before = self._fixture_state()
        with self.assertRaisesRegex(ValueError, 'independently admitted'):
            self._fixture_load(root, forged.next_cursor, admitted=page.artifact_cid)
        self.assertEqual(self._fixture_state(), before)
        self.assertEqual(self._fixture_load(root, page.next_cursor), (original,))

    def test_cancellation_before_after_page_seal(self):
        root, _ = self._fixture_start(1)
        before = self._fixture_state()
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(scheduling.LeaseCancelledError):
            self._fixture_page(root, cancel_event=cancelled)
        self.assertEqual(self.counter.parse_invocations, 0)
        self.assertEqual(self._fixture_state(), before)
        cancelled.clear(); sealed = []
        original_publish = self.artifacts._publish
        def publish(target, raw):
            original_publish(target, raw)
            body = json.loads(raw)
            if body.get('schema') == protocol.PAGE_SCHEMA:
                sealed.append(cid_for_structured(body)); cancelled.set()
        with patch.object(self.artifacts, '_publish', side_effect=publish), self.assertRaises(scheduling.LeaseCancelledError):
            self._fixture_page(root, cancel_event=cancelled)
        self.assertEqual(len(sealed), 1)
        self.assertEqual(self._fixture_state(), before)
        empty = protocol.validate_preparation_prefix(self.artifacts, root.artifact_cid)
        self.assertEqual(empty.next_offset, 0)
        durable = protocol.load_preparation_page(self.artifacts, sealed[0])
        cancelled.clear()
        retry = self._fixture_page(root)
        # The retry can use process-local parser shards and record a reused
        # decision. That changes its page CID while preserving complete facts.
        self.assertEqual(self._fixture_load(root, retry.next_cursor),
                         self._fixture_load(root, durable.next_cursor))
        self.assertEqual([(row['member_index'], row['source_key'], row['entry_cid'],
                           row['source_cid'], row['created_at_hex'])
                          for row in retry.to_dict()['entries']],
                         [(row['member_index'], row['source_key'], row['entry_cid'],
                           row['source_cid'], row['created_at_hex'])
                          for row in durable.to_dict()['entries']])
        self.assertEqual(self._fixture_state(), before)

    def test_closing_source_context_fences(self):
        root, sources = self._fixture_start(2)
        before = self._fixture_state()
        original = self.ingestor.prepare_snapshot_subset
        def edit_after_extract(*args, **kwargs):
            prepared = original(*args, **kwargs)
            (self.repository / 'source001.py').write_bytes(b'def changed_after_extract():\n    return 7\n')
            return prepared
        with patch.object(self.ingestor, 'prepare_snapshot_subset', side_effect=edit_after_extract), self.assertRaises(ValueError):
            self._fixture_page(root)
        self.assertEqual(self._fixture_state(), before)
        (self.repository / 'source001.py').write_bytes(sources['source001.py'])
        native = self.counter._frontend
        def change_context(*args, **kwargs):
            prepared = original(*args, **kwargs); native.max_ast_depth -= 1; return prepared
        try:
            with patch.object(self.ingestor, 'prepare_snapshot_subset', side_effect=change_context), self.assertRaises(ValueError):
                self._fixture_page(root)
        finally: native.max_ast_depth += 1
        self.assertEqual(self._fixture_state(), before)
        self.assertEqual(self._fixture_page(root).to_dict()['end'], 2)

    def test_custom_frontend_cannot_gain_durable_admission(self):
        root, _ = self._fixture_start(1)
        _, _, ingestor, actor = self._fixture_receiver(frontend=_UnqualifiedFrontend())
        snapshot = RepositorySnapshot.from_dict(root.to_dict()['snapshot'])
        sources = {entry.source_key: self.artifacts.get_bytes(entry.source_cid) for entry in snapshot.entries}
        fresh = ingestor.prepare_snapshot_subset(snapshot, sources, start_index=0, end_index=1, created_at=AT)
        self.assertEqual(len(fresh), 1)
        self.assertIsNone(fresh[0].context)
        self.assertIsNotNone(fresh[0].projection)
        before = self._fixture_state(ingestor.store, ingestor)
        with self.assertRaisesRegex(ValueError, 'unqualified frontend'):
            actor.start_current(self.repository, repository_id=VIEW, limits=self.limits,
                                created_at=AT, **self._fixture_resources())
        page = self._fixture_page(root)
        with self.assertRaises(ValueError): self._fixture_load(root, page.next_cursor, actor=actor)
        self.assertEqual(self._fixture_state(ingestor.store, ingestor), before)


def load_suite():
    if OWNED_RESOURCES is None:
        raise AssertionError('qualification requires the actual admitted workspace and parent lease')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestLivePreparationExtraction)
    names = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if names != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 14:
        raise AssertionError('finite AST-only staging case inventory differs')
    return suite


if __name__ == '__main__':
    unittest.main()

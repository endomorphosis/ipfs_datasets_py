"""Pure preparation protocol controls using real private immutable storage.

These tests establish historical byte identity and complete ledger coverage.
They do not capture a repository, run an analyzer, restore native AST tables,
publish a head, qualify a model, or establish proof or execution authority.
The reopened CAS control uses another receiver object in the same interpreter.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from ipfs_datasets_py.logic.software_contracts import codebase_preparation as protocol
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot, SnapshotEntry, _raw_display,
)


CASE_NAMES = (
    'exact_limits', 'canonical_schema_cids', 'wire_duplicate_nonfinite_rejection',
    'detached_aliases', 'complete_inventory_order_identity',
    'ordinary_opaque_dispositions', 'page_member_source_context_binding',
    'artifact_reference_codec_bounds', 'predecessor_prefix_contiguity',
    'forged_crossroot_cursor', 'missing_corrupt_resealed_CAS',
    'cold_owner_resume', 'empty_terminal_prefix', 'maximum_population_page_count',
    'projection_clock_hex', 'explicit_deferrals_no_positive_completeness',
    'checkpoint_cancellation', 'no_authority_or_eager_side_effects',
)
OWNED_WORKSPACE = None
MIB = 1024 * 1024
REFUSALS = (protocol.CodebasePreparationError, ValueError, TypeError, FileNotFoundError)


def configure_owned_workspace(path):
    """Qualification's admitted child supplies its actual private working dir."""
    global OWNED_WORKSPACE
    if type(path) is not type(Path.cwd()):
        raise ValueError('exact owned workspace Path required')
    resolved = path.resolve(strict=True)
    info = path.lstat()
    if (path != resolved or path != Path.cwd() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('actual owned private current workspace required')
    OWNED_WORKSPACE = path


def identity(label):
    return cid_for_structured({'pure_preparation_control': label})


def context():
    return {key: identity(key) for key in (
        'parser_cid', 'scanner_cid', 'ast_schema_cid', 'semantic_schema_cid',
        'options_cid', 'implementation_cid',
    )}


class TestCodebasePreparationProtocol(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix='pure-preparation-', dir=OWNED_WORKSPACE if OWNED_WORKSPACE is not None else None)
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.cas = ImmutableCAS(self.workspace / 'cas', max_object_bytes=4 * MIB)

    def _snapshot(self, count=3, *, entries=None, repository='pure-owner', max_entries=1024):
        if entries is None:
            entries = []
            for index in range(count):
                raw = f'# inert source {index}\n'.encode()
                entry = SnapshotEntry(f'source{index:04d}.py', 'source', len(raw),
                                      self.cas.put_bytes(raw), captured_bytes=raw)
                entries.append(entry)
        return RepositorySnapshot(repository, tuple(entries), 'filesystem',
                                  max_file_bytes=64 * 1024, max_entries=max_entries).to_dict()

    def _root(self, count=3, *, entries=None, page_entries=16, limits=None,
              expected_head=None, repository='pure-owner'):
        limits = protocol.CodebasePreparationLimits(page_entries=page_entries) if limits is None else limits
        snapshot = self._snapshot(count, entries=entries, repository=repository,
                                  max_entries=limits.max_entries)
        return protocol.create_preparation_root(self.cas, snapshot, context(),
                                                expected_head=expected_head, limits=limits)

    def _descriptor(self, root, member_index, kind, payload=None):
        body = root.to_dict()
        wrapper = protocol.build_preparation_artifact(body['snapshot']['entries'][member_index],
            body['context_cid'], kind, {'inert_proposal': kind} if payload is None else payload)
        return {'cid': self.cas.put(wrapper), 'bytes': len(canonical_dag_json_bytes(wrapper))}

    def _fixture_outcome(self, root, index, *, parse='unindexed', semantic='unsupported',
                 clock=1.0, payload=None, body=None):
        body = root.to_dict() if body is None else body
        member = body['snapshot']['entries'][index]
        row = {'member_index': index, 'source_key': 'raw:' + member['raw_path_hex'],
               'entry_cid': member['entry_cid'], 'source_cid': member['source_cid'],
               'parse_status': parse, 'semantic_disposition': semantic,
               'ast_artifact': None, 'facts_artifact': None, 'diagnostic_artifact': None,
               'created_at_hex': None, 'reason': 'explicit pure control limitation'}
        if parse in {'ok', 'partial', 'failed'}:
            row['ast_artifact'] = self._descriptor(root, index, 'ast', payload)
            row['created_at_hex'] = clock.hex()
        if semantic == 'analysed':
            row['facts_artifact'] = self._descriptor(root, index, 'semantic')
        if parse == 'ok' and semantic == 'analysed':
            row['reason'] = None
        return row

    def _chain(self, count=34, page_entries=16):
        root = self._root(count, page_entries=page_entries)
        body = root.to_dict()
        pages, cursor = [], None
        for start in range(0, count, page_entries):
            outcomes = [self._fixture_outcome(root, index, body=body)
                        for index in range(start, min(start + page_entries, count))]
            page = protocol.create_preparation_page(self.cas, root.artifact_cid, cursor, outcomes)
            pages.append(page)
            cursor = page.next_cursor
        return root, pages

    def _seal_page(self, body):
        cid = self.cas.put(body)
        return protocol.PreparationPage.from_dict(cid, body)

    def _refuse_page(self, root, body):
        with self.assertRaises(REFUSALS):
            page = self._seal_page(body)
            protocol.validate_preparation_prefix(self.cas, root.artifact_cid, page.next_cursor)

    def _stored_bytes(self):
        return {str(path.relative_to(self.workspace)): path.read_bytes()
                for path in self.workspace.rglob('*') if path.is_file()}

    def test_exact_limits(self):
        defaults = protocol.CodebasePreparationLimits()
        maxima = (1024, 64, 65536, 4 * MIB, MIB, 128 * MIB)
        self.assertEqual(tuple(defaults.to_dict()), tuple(defaults.__dataclass_fields__))
        for name, maximum in zip(defaults.__dataclass_fields__, maxima):
            for bad in (0, -1, True, False, 1.0, None, maximum + 1):
                with self.subTest(field=name, value=bad), self.assertRaises(REFUSALS):
                    replace(defaults, **{name: bad})
        with self.assertRaises(REFUSALS):
            protocol.CodebasePreparationLimits(max_record_bytes=100, max_artifact_bytes=101)
        for body in ({}, {**defaults.to_dict(), 'future_cap': 1}):
            with self.assertRaises(REFUSALS):
                protocol.CodebasePreparationLimits.from_dict(body)
        too_wide = ImmutableCAS(self.workspace / 'too-wide', max_object_bytes=4 * MIB + 1)
        with patch.object(protocol.os, 'open', wraps=protocol.os.open) as opening:
            with self.assertRaises(protocol.CodebasePreparationError):
                protocol.load_preparation_root(too_wide, identity('absent'))
            self.assertEqual(opening.call_count, 0)
        root = self._root(1)
        smaller = replace(defaults, max_prefix_read_bytes=1)
        with self.assertRaises(protocol.CodebasePreparationError):
            protocol.create_preparation_root(self.cas, root.to_dict()['snapshot'], context(), limits=smaller)

    def test_canonical_schema_cids(self):
        older = identity('older-snapshot')
        head = {'schema': 'codebase-head@1', 'repository_id': 'pure-owner', 'generation': 7,
                'manifest_cid': identity('older-manifest'), 'snapshot_cid': older,
                'ast_revision_id': 'rev:pure-owner:snapshot:' + older,
                'receipt_cid': identity('older-receipt')}
        root = self._root(2, expected_head=head)
        body = root.to_dict()
        self.assertNotEqual(body['snapshot']['snapshot_cid'], older)
        self.assertEqual(body['expected_head'], head)
        self.assertEqual(root.artifact_cid, cid_for_structured(body))
        self.assertNotEqual(root.artifact_cid, cid_for_bytes(canonical_dag_json_bytes(body)))
        self.assertEqual(protocol.load_preparation_root(self.cas, root.artifact_cid), root)
        self.assertEqual(body['context_cid'], cid_for_structured(body['context']))
        self.assertEqual(body['membership_cid'], cid_for_structured(body['snapshot']['entries']))
        variants = []
        for key in ('schema', 'limits', 'context', 'authority'):
            bad = copy.deepcopy(body); bad.pop(key); variants.append(bad)
        bad = copy.deepcopy(body); bad['future_admission'] = False; variants.append(bad)
        bad = copy.deepcopy(body); bad['schema'] = 'codebase-preparation-root@2'; variants.append(bad)
        bad = copy.deepcopy(body); bad['context_cid'] = identity('foreign-context'); variants.append(bad)
        bad = copy.deepcopy(body); bad['expected_head']['repository_id'] = 'other'; variants.append(bad)
        bad = copy.deepcopy(body); bad['expected_head']['generation'] = True; variants.append(bad)
        for index, bad in enumerate(variants):
            with self.subTest(mutation=index), self.assertRaises(REFUSALS):
                protocol.PreparationRoot.from_dict(cid_for_structured(bad), bad)

    def test_wire_duplicate_nonfinite_rejection(self):
        root = self._root(1)
        raw = canonical_dag_json_bytes(root.to_dict())
        duplicate = raw[:-1] + b',"schema":"codebase-preparation-root@1"}'
        pretty = json.dumps(root.to_dict(), indent=2).encode()
        nonfinite = raw[:-1] + b',"unsafe":NaN}'
        for wire in (duplicate, pretty, nonfinite, b'\xff', raw + b'\n'):
            with self.subTest(wire=wire[:32]), self.assertRaises(REFUSALS):
                protocol.PreparationRoot(root.artifact_cid, wire)
        for value in (float('nan'), float('inf'), -float('inf'), 0.0):
            bad = root.to_dict(); bad['context']['options_cid'] = value
            with self.assertRaises(REFUSALS):
                protocol.PreparationRoot.from_dict(root.artifact_cid, bad)
        target = self.cas.path_for(root.artifact_cid)
        target.write_bytes(duplicate)
        with self.assertRaises(protocol.CodebasePreparationError):
            protocol.load_preparation_root(self.cas, root.artifact_cid)

    def test_detached_aliases(self):
        snapshot, local_context = self._snapshot(2), context()
        root = protocol.create_preparation_root(self.cas, snapshot, local_context)
        original = root.to_dict()
        snapshot['entries'][0]['path'] = 'changed.py'
        local_context['options_cid'] = identity('changed')
        self.assertEqual(root.to_dict(), original)
        outcomes = [self._fixture_outcome(root, index, parse='ok', semantic='analysed') for index in range(2)]
        page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, outcomes)
        page_body = page.to_dict()
        outcomes[0]['ast_artifact']['bytes'] += 1
        returned = page.to_dict(); returned['entries'][1]['reason'] = 'changed'
        self.assertEqual(page.to_dict(), page_body)
        cursor = page.next_cursor
        dto = cursor.to_dict(); dto['next_offset'] = 0
        self.assertEqual(cursor.next_offset, 2)
        self.assertEqual(protocol.validate_preparation_prefix(self.cas, root.artifact_cid, cursor).pages, (page,))
        payload = {'nested_proposal': [{'value': 1}]}
        artifact = protocol.build_preparation_artifact(original['snapshot']['entries'][0],
            original['context_cid'], 'semantic', payload)
        payload['nested_proposal'][0]['value'] = 99
        self.assertEqual(artifact['payload'], {'nested_proposal': [{'value': 1}]})

    def test_complete_inventory_order_identity(self):
        root = self._root(3)
        body = root.to_dict()
        variants = []
        bad = copy.deepcopy(body); bad['snapshot']['entries'].reverse(); variants.append(bad)
        bad = copy.deepcopy(body); bad['snapshot']['entries'].append(copy.deepcopy(bad['snapshot']['entries'][0])); variants.append(bad)
        bad = copy.deepcopy(body); bad['membership_cid'] = identity('omitted-member'); variants.append(bad)
        bad = copy.deepcopy(body); bad['snapshot']['exclusions'] = ['same', 'same']; variants.append(bad)
        for index, bad in enumerate(variants):
            with self.subTest(mutation=index), self.assertRaises(REFUSALS):
                protocol.PreparationRoot.from_dict(cid_for_structured(bad), bad)
        dag_source = SnapshotEntry('wrong.py', 'source', 0, identity('structured-not-raw'))
        snapshot = self._snapshot(entries=[dag_source])
        with self.assertRaises(protocol.CodebasePreparationError):
            protocol.create_preparation_root(self.cas, snapshot, context())
        source = self._snapshot(1)
        wrong_size = copy.deepcopy(source)
        entry = wrong_size['entries'][0]
        altered = SnapshotEntry(entry['path'], entry['kind'], entry['size_bytes'] + 1, entry['source_cid'])
        wrong_size = self._snapshot(entries=[altered])
        with self.assertRaisesRegex(protocol.CodebasePreparationError, 'size'):
            protocol.create_preparation_root(self.cas, wrong_size, context())

    def test_ordinary_opaque_dispositions(self):
        ordinary = SnapshotEntry('empty.py', 'source', 0, self.cas.put_bytes(b''), captured_bytes=b'')
        opaque = SnapshotEntry(_raw_display(b'\xff'), 'opaque', None, cid_for_bytes(b'unavailable'),
                               'invalid_utf8_path', 'ff', acquisition='opaque', disposition='opaque')
        root = self._root(entries=[ordinary, opaque])
        rows = [self._fixture_outcome(root, 0, parse='ok', semantic='analysed'),
                self._fixture_outcome(root, 1, parse='opaque', semantic='opaque')]
        page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, rows)
        prefix = protocol.validate_preparation_prefix(self.cas, root.artifact_cid, page.next_cursor)
        self.assertTrue(prefix.inventory_complete)
        self.assertEqual(prefix.root.to_dict()['snapshot']['entries'][1]['raw_path_hex'], 'ff')
        self.assertIsNone(prefix.root.to_dict()['snapshot']['entries'][1]['size_bytes'])
        self.assertEqual(page.to_dict()['coverage']['semantic_dispositions'], {'analysed': 1, 'opaque': 1})
        bad = page.to_dict(); bad['entries'][1]['parse_status'] = 'unindexed'
        bad['entries'][1]['semantic_disposition'] = 'unsupported'
        bad['coverage']['parse_status'] = {'ok': 1, 'unindexed': 1}
        bad['coverage']['semantic_dispositions'] = {'analysed': 1, 'unsupported': 1}
        self._refuse_page(root, bad)

    def test_page_member_source_context_binding(self):
        root, pages = self._chain(2)
        body = pages[0].to_dict()
        for field in ('root_cid', 'snapshot_cid', 'context_cid', 'page_membership_cid'):
            bad = copy.deepcopy(body); bad[field] = identity('foreign-' + field)
            with self.subTest(field=field): self._refuse_page(root, bad)
        for field, value in (('member_index', True), ('source_key', 'raw:7879'),
                             ('entry_cid', identity('foreign-entry')),
                             ('source_cid', cid_for_bytes(b'foreign-source'))):
            bad = copy.deepcopy(body); bad['entries'][0][field] = value
            with self.subTest(field=field): self._refuse_page(root, bad)
        bad = copy.deepcopy(body); bad['entries'].pop(); self._refuse_page(root, bad)
        bad = copy.deepcopy(body); bad['entries'][1] = copy.deepcopy(bad['entries'][0]); self._refuse_page(root, bad)
        bad = copy.deepcopy(body); bad['coverage']['inventory_entries'] = True; self._refuse_page(root, bad)

    def test_artifact_reference_codec_bounds(self):
        root = self._root(1)
        row = self._fixture_outcome(root, 0, parse='ok', semantic='analysed')
        for descriptor in ({'cid': cid_for_bytes(b'wrong-codec'), 'bytes': 1},
                           {'cid': row['ast_artifact']['cid'], 'bytes': True},
                           {'cid': row['ast_artifact']['cid'], 'bytes': 0},
                           {'cid': row['ast_artifact']['cid'], 'bytes': MIB + 1},
                           {**row['ast_artifact'], 'extra': False},
                           {**row['ast_artifact'], 'bytes': row['ast_artifact']['bytes'] + 1}):
            bad = copy.deepcopy(row); bad['ast_artifact'] = descriptor
            with self.subTest(descriptor=descriptor), self.assertRaises(REFUSALS):
                protocol.create_preparation_page(self.cas, root.artifact_cid, None, [bad])
        original = self.cas.get(row['ast_artifact']['cid'])
        for field, value in (('kind', 'semantic'), ('context_cid', identity('foreign')),
                             ('source_key', 'raw:7879'), ('entry_cid', identity('foreign-entry')),
                             ('source_cid', cid_for_bytes(b'foreign-source')), ('payload', [])):
            wrapper = copy.deepcopy(original); wrapper[field] = value
            bad = copy.deepcopy(row)
            bad['ast_artifact'] = {'cid': self.cas.put(wrapper), 'bytes': len(canonical_dag_json_bytes(wrapper))}
            with self.subTest(field=field), self.assertRaises(REFUSALS):
                protocol.create_preparation_page(self.cas, root.artifact_cid, None, [bad])
        limits = protocol.CodebasePreparationLimits(max_artifact_bytes=64)
        bounded_root = self._root(1, limits=limits)
        bounded_row = self._fixture_outcome(bounded_root, 0, parse='ok', semantic='analysed')
        with self.assertRaisesRegex(protocol.CodebasePreparationError, 'bound'):
            protocol.create_preparation_page(self.cas, bounded_root.artifact_cid, None, [bounded_row])
        # Measure real filesystem payload reads, then choose a budget at which
        # prefix replay and new closure separately fit but their combined public
        # append does not. The page must remain unpublished on that refusal.
        charged = []
        original_read = protocol.os.read
        def observe_read(fd, maximum):
            data = original_read(fd, maximum)
            charged.append(len(data))
            return data
        with patch.object(protocol.os, 'read', side_effect=observe_read):
            measured_page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, [row])
        measured = sum(charged)
        original_body = root.to_dict()
        cap = measured - 1
        for _ in range(4):
            adjusted_body = copy.deepcopy(original_body)
            adjusted_body['limits']['max_prefix_read_bytes'] = cap
            cap = measured + len(canonical_dag_json_bytes(adjusted_body)) - len(root._payload) - 1
        cap_limits = protocol.CodebasePreparationLimits(max_prefix_read_bytes=cap)
        cap_root = self._root(1, limits=cap_limits)
        cap_row = self._fixture_outcome(cap_root, 0, parse='ok', semantic='analysed')
        self.assertLess(sum(cap_row[key]['bytes'] for key in ('ast_artifact', 'facts_artifact')),
                        cap)
        self.assertLess(len(measured_page._payload), cap)
        self.assertEqual(protocol.validate_preparation_prefix(self.cas, cap_root.artifact_cid).next_offset, 0)
        before = self._stored_bytes()
        with self.assertRaisesRegex(protocol.CodebasePreparationError, 'budget|bound'):
            protocol.create_preparation_page(self.cas, cap_root.artifact_cid, None, [cap_row])
        self.assertEqual(self._stored_bytes(), before)
        # A page can exceed a tight record envelope while the complete root and
        # each referenced artifact fit. Reject it before atomic publication.
        wide_root = self._root(2)
        wide_rows = [self._fixture_outcome(wide_root, index, parse='ok', semantic='analysed')
                     for index in range(2)]
        for index, wide_row in enumerate(wide_rows):
            wide_row['diagnostic_artifact'] = self._descriptor(wide_root, index, 'diagnostic')
            wide_row['reason'] = 'r' * 500
        wide_page = protocol.create_preparation_page(self.cas, wide_root.artifact_cid, None, wide_rows)
        self.assertGreater(len(wide_page._payload), len(wide_root._payload) + 64)
        record_bound = len(wide_root._payload) + 64
        tight_limits = protocol.CodebasePreparationLimits(max_record_bytes=record_bound,
                                                         max_artifact_bytes=record_bound)
        self.cas.max_object_bytes = record_bound
        try:
            tight_root = self._root(2, limits=tight_limits)
            tight_rows = [self._fixture_outcome(tight_root, index, parse='ok', semantic='analysed')
                          for index in range(2)]
            for index, tight_row in enumerate(tight_rows):
                tight_row['diagnostic_artifact'] = self._descriptor(tight_root, index, 'diagnostic')
                tight_row['reason'] = 'r' * 500
            before = self._stored_bytes()
            with self.assertRaisesRegex(protocol.CodebasePreparationError, 'bound'):
                protocol.create_preparation_page(self.cas, tight_root.artifact_cid, None, tight_rows)
            self.assertEqual(self._stored_bytes(), before)
        finally:
            self.cas.max_object_bytes = 4 * MIB
        # Reject oversized physical bodies before reading/parsing their data,
        # and refuse a final-component symlink rather than following it.
        target = self.cas.path_for(row['ast_artifact']['cid'])
        original = target.read_bytes()
        try:
            with target.open('wb') as stream:
                stream.write(b'x'); stream.truncate(MIB + 1)
            with self.assertRaises(protocol.CodebasePreparationError):
                protocol.validate_preparation_prefix(self.cas, root.artifact_cid, measured_page.next_cursor)
            target.unlink()
            alternate = self.workspace / 'alternate-artifact'
            alternate.write_bytes(original)
            target.symlink_to(alternate)
            with self.assertRaises(OSError):
                protocol.validate_preparation_prefix(self.cas, root.artifact_cid, measured_page.next_cursor)
        finally:
            target.unlink(missing_ok=True)
            target.write_bytes(original)

    def test_predecessor_prefix_contiguity(self):
        root, pages = self._chain(34, 16)
        prefix = protocol.validate_preparation_prefix(self.cas, root.artifact_cid, pages[-1].next_cursor)
        self.assertEqual(prefix.pages, tuple(pages))
        self.assertEqual(prefix.next_offset, 34)
        self.assertTrue(prefix.inventory_complete)
        self.assertEqual([(page.to_dict()['start'], page.to_dict()['end']) for page in prefix.pages],
                         [(0, 16), (16, 32), (32, 34)])
        indices = [row['member_index'] for page in prefix.pages for row in page.to_dict()['entries']]
        self.assertEqual(indices, list(range(34)))
        gap = pages[-1].to_dict(); gap['previous_page_cid'] = pages[0].artifact_cid
        self._refuse_page(root, gap)
        repeated = pages[1].to_dict(); repeated['previous_page_cid'] = pages[1].artifact_cid
        self._refuse_page(root, repeated)
        early = protocol.validate_preparation_prefix(self.cas, root.artifact_cid, pages[0].next_cursor)
        self.assertFalse(early.inventory_complete)
        self.assertEqual(early.next_offset, 16)
        for records, offset in ((tuple(reversed(pages)), 34), (tuple(pages), True),
                                ((pages[-1],), 34), (list(pages), 34)):
            with self.assertRaises(REFUSALS):
                protocol.PreparationPrefix(root, records, offset)

    def test_forged_crossroot_cursor(self):
        root, pages = self._chain(3, 2)
        good = pages[0].next_cursor
        for cursor in (protocol.PreparationCursor(root.artifact_cid, 1, good.previous_page_cid),
                       protocol.PreparationCursor(root.artifact_cid, 3, good.previous_page_cid),
                       protocol.PreparationCursor(identity('foreign-root'), 2, good.previous_page_cid),
                       good.to_dict()):
            with self.subTest(cursor=cursor), self.assertRaises(REFUSALS):
                protocol.validate_preparation_prefix(self.cas, root.artifact_cid, cursor)
        for body in ({**good.to_dict(), 'next_offset': True},
                     {**good.to_dict(), 'previous_page_cid': None},
                     {**good.to_dict(), 'schema': 'codebase-preparation-cursor@2'},
                     {**good.to_dict(), 'prevalidated': True}):
            with self.assertRaises(REFUSALS): protocol.PreparationCursor.from_dict(body)
        other = self._root(3, page_entries=2, repository='other-owner')
        foreign = protocol.PreparationCursor(other.artifact_cid, 2, good.previous_page_cid)
        with self.assertRaises(REFUSALS):
            protocol.validate_preparation_prefix(self.cas, other.artifact_cid, foreign)

    def test_missing_corrupt_resealed_CAS(self):
        root = self._root(1)
        row = self._fixture_outcome(root, 0, parse='ok', semantic='analysed')
        row['diagnostic_artifact'] = self._descriptor(root, 0, 'diagnostic')
        page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, [row])
        for cid, source in ((root.artifact_cid, False), (page.artifact_cid, False),
                            (row['ast_artifact']['cid'], False), (row['facts_artifact']['cid'], False),
                            (row['diagnostic_artifact']['cid'], False),
                            (row['source_cid'], True)):
            target = self.cas.path_for(cid, source=source); original = target.read_bytes()
            target.unlink()
            try:
                with self.assertRaises(FileNotFoundError):
                    protocol.validate_preparation_prefix(self.cas, root.artifact_cid, page.next_cursor)
                target.write_bytes(b'{}' if not source else b'wrong source bytes')
                with self.assertRaises(REFUSALS):
                    protocol.validate_preparation_prefix(self.cas, root.artifact_cid, page.next_cursor)
            finally:
                target.write_bytes(original)
        resealed = page.to_dict(); resealed['context_cid'] = identity('new-context')
        bad = self._seal_page(resealed)
        with self.assertRaises(REFUSALS):
            protocol.validate_preparation_prefix(self.cas, root.artifact_cid, bad.next_cursor)
        self.assertEqual(protocol.validate_preparation_prefix(self.cas, root.artifact_cid, page.next_cursor).pages,
                         (page,))

    def test_cold_owner_resume(self):
        root, pages = self._chain(34, 16)
        received = protocol.PreparationCursor.from_dict(json.loads(json.dumps(pages[0].next_cursor.to_dict())))
        receiver = ImmutableCAS(self.cas.root, max_object_bytes=4 * MIB)
        self.assertIsNot(receiver, self.cas)
        self.assertEqual(protocol.load_preparation_root(receiver, root.artifact_cid), root)
        self.assertEqual(protocol.load_preparation_page(receiver, pages[0].artifact_cid), pages[0])
        prefix = protocol.validate_preparation_prefix(receiver, root.artifact_cid, received)
        self.assertEqual(prefix.pages, (pages[0],))
        outcomes = [self._fixture_outcome(root, index) for index in range(16, 32)]
        resumed = protocol.create_preparation_page(receiver, root.artifact_cid, received, outcomes)
        self.assertEqual(resumed, pages[1])
        whole = protocol.validate_preparation_prefix(receiver, root.artifact_cid, pages[-1].next_cursor)
        self.assertEqual(whole.pages, tuple(pages))
        self.assertEqual(whole.root.to_dict(), root.to_dict())

    def test_empty_terminal_prefix(self):
        empty = self._root(0)
        prefix = protocol.validate_preparation_prefix(self.cas, empty.artifact_cid)
        self.assertTrue(prefix.inventory_complete)
        self.assertEqual(prefix.next_offset, 0)
        self.assertEqual(prefix.pages, ())
        self.assertEqual(prefix.cursor.to_dict(), {'schema': protocol.CURSOR_SCHEMA,
            'root_cid': empty.artifact_cid, 'next_offset': 0, 'previous_page_cid': None})
        with self.assertRaises(REFUSALS):
            protocol.create_preparation_page(self.cas, empty.artifact_cid, None, [])
        root, pages = self._chain(1)
        self.assertIsNotNone(pages[-1].next_cursor)
        done = protocol.validate_preparation_prefix(self.cas, root.artifact_cid, pages[-1].next_cursor)
        self.assertTrue(done.inventory_complete)
        with self.assertRaises(REFUSALS):
            protocol.create_preparation_page(self.cas, root.artifact_cid, done.cursor, [])

    def test_maximum_population_page_count(self):
        root, pages = self._chain(1024, 64)
        prefix = protocol.validate_preparation_prefix(self.cas, root.artifact_cid, pages[-1].next_cursor)
        self.assertEqual(len(prefix.pages), 16)
        self.assertEqual(prefix.next_offset, 1024)
        self.assertTrue(prefix.inventory_complete)
        self.assertEqual([row['member_index'] for page in prefix.pages for row in page.to_dict()['entries']],
                         list(range(1024)))
        bad = root.to_dict(); bad['snapshot']['max_entries'] = 1025
        with self.assertRaises(REFUSALS):
            protocol.PreparationRoot.from_dict(cid_for_structured(bad), bad)

    def test_projection_clock_hex(self):
        root = self._root(1)
        for clock in (0.0, -0.0, 1.0, 0.1, math.nextafter(1.0, 2.0)):
            row = self._fixture_outcome(root, 0, parse='ok', semantic='analysed', clock=clock)
            page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, [row])
            stored = protocol.load_preparation_page(self.cas, page.artifact_cid).to_dict()['entries'][0]['created_at_hex']
            self.assertEqual(stored, clock.hex())
            self.assertEqual(float.fromhex(stored).hex(), clock.hex())
        base = self._fixture_outcome(root, 0, parse='ok', semantic='analysed')
        for clock in (None, True, 1.0, '1.0', 'nan', 'inf', '-inf', '0x1p+0', ' 0x1.0000000000000p+0'):
            bad = copy.deepcopy(base); bad['created_at_hex'] = clock
            with self.subTest(clock=clock), self.assertRaises(REFUSALS):
                protocol.create_preparation_page(self.cas, root.artifact_cid, None, [bad])
        no_ast = self._fixture_outcome(root, 0); no_ast['created_at_hex'] = 1.0.hex()
        with self.assertRaises(REFUSALS):
            protocol.create_preparation_page(self.cas, root.artifact_cid, None, [no_ast])

    def test_explicit_deferrals_no_positive_completeness(self):
        root = self._root(6)
        states = [('ok', 'analysed'), ('partial', 'unsupported'), ('failed', 'failed'),
                  ('ok', 'failed'), ('unindexed', 'unsupported'), ('unindexed', 'deferred_budget')]
        rows = [self._fixture_outcome(root, index, parse=parse, semantic=semantic)
                for index, (parse, semantic) in enumerate(states)]
        page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, rows)
        prefix = protocol.validate_preparation_prefix(self.cas, root.artifact_cid, page.next_cursor)
        self.assertTrue(prefix.inventory_complete)
        self.assertEqual(page.to_dict()['coverage']['inventory_entries'], 6)
        self.assertEqual(page.to_dict()['coverage']['semantic_dispositions'],
                         {'analysed': 1, 'failed': 2, 'unsupported': 2, 'deferred_budget': 1})
        self.assertTrue(all(value is False for value in page.to_dict()['authority'].values()))
        for index in range(1, 6):
            bad = copy.deepcopy(rows); bad[index]['reason'] = None
            with self.subTest(index=index), self.assertRaises(REFUSALS):
                protocol.create_preparation_page(self.cas, root.artifact_cid, None, bad)
        bad = copy.deepcopy(rows); bad[-1]['facts_artifact'] = self._descriptor(root, 5, 'semantic')
        with self.assertRaises(REFUSALS):
            protocol.create_preparation_page(self.cas, root.artifact_cid, None, bad)

    def test_checkpoint_cancellation(self):
        class Cancelled(Exception):
            pass
        root = self._root(1)
        initial = protocol.validate_preparation_prefix(self.cas, root.artifact_cid).cursor
        row = self._fixture_outcome(root, 0)
        before = self._stored_bytes()
        def cancel():
            raise Cancelled('pure checkpoint cancellation')
        for action in (
            lambda: protocol.create_preparation_page(self.cas, root.artifact_cid, initial, [row], checkpoint=cancel),
            lambda: protocol.validate_preparation_prefix(self.cas, root.artifact_cid, initial, checkpoint=cancel),
            lambda: protocol.create_preparation_root(self.cas, root.to_dict()['snapshot'], context(), checkpoint=cancel),
        ):
            with self.assertRaises(Cancelled): action()
            self.assertEqual(self._stored_bytes(), before)
        published, late = [], [False]
        original_publish = self.cas._publish
        def real_publish(target, raw):
            original_publish(target, raw)
            body = json.loads(raw)
            if body['schema'] == protocol.PAGE_SCHEMA:
                published.append(cid_for_structured(body)); late[0] = True
        def late_cancel():
            if late[0]: raise Cancelled('after immutable page publication')
        with patch.object(self.cas, '_publish', side_effect=real_publish), self.assertRaises(Cancelled):
            protocol.create_preparation_page(self.cas, root.artifact_cid, initial, [row], checkpoint=late_cancel)
        self.assertEqual(initial.next_offset, 0)
        self.assertEqual(len(published), 1)
        self.assertEqual(protocol.validate_preparation_prefix(self.cas, root.artifact_cid, initial).pages, ())
        recovered = protocol.load_preparation_page(self.cas, published[0])
        self.assertEqual(protocol.create_preparation_page(self.cas, root.artifact_cid, initial, [row]), recovered)
        self.assertTrue(protocol.validate_preparation_prefix(self.cas, root.artifact_cid, recovered.next_cursor).inventory_complete)

    def test_no_authority_or_eager_side_effects(self):
        root = self._root(1)
        inert = {'deliberately_not_a_canonical_AST': {'untrusted_proposal': 'checker still required'}}
        row = self._fixture_outcome(root, 0, parse='ok', semantic='analysed', payload=inert)
        page = protocol.create_preparation_page(self.cas, root.artifact_cid, None, [row])
        wrapper = self.cas.get(row['ast_artifact']['cid'])
        self.assertEqual(wrapper['payload'], inert)
        self.assertTrue(all(value is False for record in (root.to_dict(), page.to_dict(), wrapper)
                            for value in record['authority'].values()))
        for field in root.to_dict()['authority']:
            for alias in (0, True):
                bad = root.to_dict(); bad['authority'][field] = alias
                with self.subTest(field=field, alias=alias), self.assertRaises(REFUSALS):
                    protocol.PreparationRoot.from_dict(cid_for_structured(bad), bad)
        bad = page.to_dict(); bad['authority']['proof_authority'] = True
        self._refuse_page(root, bad)
        bad_wrapper = copy.deepcopy(wrapper); bad_wrapper['authority']['analysis_execution_verified'] = 0
        bad_row = copy.deepcopy(row)
        bad_row['ast_artifact'] = {'cid': self.cas.put(bad_wrapper),
                                  'bytes': len(canonical_dag_json_bytes(bad_wrapper))}
        with self.assertRaises(REFUSALS):
            protocol.create_preparation_page(self.cas, root.artifact_cid, None, [bad_row])
        if OWNED_WORKSPACE is not None:
            self.assertFalse(any(name == prefix or name.startswith(prefix + '.')
                for name in sys.modules for prefix in ('torch', 'numpy', 'duckdb', '_duckdb')))


def load_suite():
    if OWNED_WORKSPACE is None:
        raise AssertionError('qualification requires the actual admitted child workspace')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestCodebasePreparationProtocol)
    actual = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if actual != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 18:
        raise AssertionError('finite pure preparation case inventory differs')
    return suite


if __name__ == '__main__':
    unittest.main()

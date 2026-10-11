"""Stopped, read-only retained-metadata replay; never import the diagnosis owner."""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import time

BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-identity-recovery-20261011-01'
RUN = BASE / 'external/ipfs_datasets/workspace/test-logs/uscode-identity-recovery-20261011-01/ordinal-profile-01'
TREE = BASE / '.worktrees/uscode-identity-recovery-datasets-20261011'
COMMIT = '7b2155fc211fe2b3b60455c2bcd11d7c8c41f3a9'
INPUTS = {'database': ('database_path', 'expected_database_sha256'),
          'manifest': ('manifest_path', 'expected_manifest_sha256'),
          'report': ('report_path', 'expected_report_sha256'),
          'progress': ('progress_parquet', 'expected_progress_sha256'),
          'accepted_review': ('accepted_review_path', 'expected_accepted_review_sha256')}
COLUMNS = ['occurrence_id', 'generated_span_id', 'hypothesis_span_id', 'source_sha256',
           'legal_id', 'entry_cid', 'citation', 'title', 'section', 'source_section_offset',
           'source_section_span_ordinal', 'historical_span_ordinal', 'source_text_origin',
           'raw_source_text_present', 'retained_match_count']
NUMERIC = {'source_section_offset', 'source_section_span_ordinal', 'historical_span_ordinal', 'retained_match_count'}
AUTHORITY = ['original_source_read', 'models_loaded', 'tokenizers_loaded', 'aliases_created',
             'original_producer_recipe_authenticated', 'full_source_uniqueness_verified',
             'embedding_reuse_qualified', 'teacher_qualified', 'training_admitted',
             'semantic_gold', 'semantic_fidelity_qualified', 'proof_authority']


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sig(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def canonical(path):
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), 'canonical existing path required')
    return path


class Witness:
    def __init__(self, stack, path, expected=None, ceiling=2 * 1024 * 1024):
        self.path = canonical(path)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        stack.callback(os.close, self.fd)
        info = os.fstat(self.fd)
        need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= ceiling, 'bounded positive regular file required')
        self.signature = sig(info)
        self.digest = expected
        self.verify()

    def verify(self):
        canonical(self.path)
        need(sig(os.fstat(self.fd)) == self.signature == sig(self.path.stat()), 'input signature changed')
        os.lseek(self.fd, 0, os.SEEK_SET)
        remaining = self.signature[2]
        digest = hashlib.sha256()
        while remaining:
            body = os.read(self.fd, min(remaining, 1024 * 1024))
            need(bool(body), 'pinned file shortened')
            digest.update(body)
            remaining -= len(body)
        need(not os.read(self.fd, 1), 'pinned file grew')
        if self.digest is None:
            self.digest = digest.hexdigest()
        need(digest.hexdigest() == self.digest, 'pinned SHA-256 differs')
        canonical(self.path)
        need(sig(os.fstat(self.fd)) == self.signature == sig(self.path.stat()), 'input changed during read')

    def pin(self):
        return {'path': str(self.path), 'bytes': self.signature[2], 'sha256': self.digest,
                'stat_signature': self.signature}

    def body(self):
        need(self.signature[2] <= 2 * 1024 * 1024, 'body read exceeds review metadata cap')
        os.lseek(self.fd, 0, os.SEEK_SET)
        body = bytearray()
        while len(body) < self.signature[2]:
            part = os.read(self.fd, self.signature[2] - len(body))
            need(bool(part), 'body shortened')
            body.extend(part)
        self.verify()
        return bytes(body)

    def value(self):
        return json.loads(self.body())


def identity(row, ordinal, release):
    # Independent implementation of the declared historical canonical descriptor.
    binding = {'canonical_citation': row['citation'], 'entry_cid': row['entry_cid'],
               'legal_id': row['legal_id'], 'ordinal': ordinal, 'query': 'ipfs_uscode',
               'release_id': release, 'release_point': '',
               'schema_version': 'uscode-sparse-autoformal-span-v1', 'section': row['section'],
               'text_sha256': row['source_sha256'], 'title': row['title'], 'unit_id': row['legal_id']}
    body = json.dumps(binding, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('utf-8')
    return 'uscode-span-' + hashlib.sha256(body).hexdigest()


def batches(db):
    offset = 0
    while True:
        query = db.execute('SELECT * FROM original.target_occurrences '
                           'ORDER BY source_section_offset,source_section_span_ordinal,occurrence_id LIMIT 512 OFFSET ?', [offset])
        names = [entry[0] for entry in query.description]
        rows = query.fetchall()
        if not rows:
            return
        yield [dict(zip(names, row)) for row in rows]
        offset += len(rows)


def main():
    started = time.monotonic()
    checks = []
    pins = []

    def checked(identifier, detail):
        checks.append({'id': identifier, 'passed': True, 'detail': detail})

    with ExitStack() as stack:
        def capture(path, expected=None, ceiling=2 * 1024 * 1024):
            pin = Witness(stack, path, expected, ceiling)
            pins.append(pin)
            return pin

        arguments = capture(CAMPAIGN / 'arguments.json').value()
        admitted_command = capture(CAMPAIGN / 'command.json')
        implementation = capture(CAMPAIGN / 'review/implementation-review.json',
                                 '341b9d5a13491534fc0a3513a0be2a0888928d4bf4285f5001740ea732896e88')
        method = implementation.value()
        need(method['status'] == 'accepted' and method['findings'] == [], 'accepted method required')
        for relative, known in method['owner_file_pins'].items():
            owner = capture(TREE / relative, known['sha256'])
            need(owner.signature[2] == known['bytes'], 'owner byte length differs')
            need(subprocess.check_output(['git', '-C', str(TREE), 'show', COMMIT + ':' + relative]) == owner.body(), 'committed owner differs')
        need(subprocess.check_output(['git', '-C', str(TREE), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT, 'frozen source commit changed')
        need(not subprocess.check_output(['git', '-C', str(TREE), 'status', '--porcelain'], text=True), 'source tree changed')
        for known in method['preserved_execution_file_pins'].values():
            capture(Path(known['path']), known['sha256'])
        checked('frozen-source-and-method', {'commit': COMMIT, 'owner_files': 4, 'unchanged_prior_owners': 9,
                                           'implementation_review': implementation.pin()})

        # Require successful stopped custody BEFORE any retained input/DB read.
        child_exit = capture(RUN / 'child-exit.json').value()
        final_resources = capture(RUN / 'resources-final.json').value()
        child_identity = capture(RUN / 'child-identity.json').value()
        need(child_exit['returncode'] == 0, 'child did not exit successfully')
        need(not (RUN / 'failure.json').exists(), 'guardian recorded a failure')
        child_pid = child_identity['pid']
        need(not Path(f'/proc/{child_pid}').exists(), 'recorded child PID remains present')
        checked('stopped-successful-child', {'child_exit': child_exit, 'child_identity': child_identity,
                                             'resources_final': final_resources})

        parent = Path(arguments['database_path']).parent
        lock_path = canonical(parent / 'writer.lock')
        lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        stack.callback(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        stack.callback(fcntl.flock, lock, fcntl.LOCK_UN)
        lock_signature = sig(os.fstat(lock))
        need(not (parent / 'reconciliation.duckdb.wal').exists(), 'parent WAL present')
        input_witnesses = {name: capture(Path(arguments[path_name]), arguments[hash_name], arguments['max_input_bytes'])
                           for name, (path_name, hash_name) in INPUTS.items()}
        old_manifest = input_witnesses['manifest'].value()
        old_report = input_witnesses['report'].value()
        old_review = input_witnesses['accepted_review'].value()
        need(old_review['passed'] is True and old_review['completed'] is True and old_review['findings'] == [], 'parent review not accepted')
        need(old_report['complete_source_scan'] is True and old_report['complete_all_source_occurrence_inventory'] is False,
             'parent completion scope differs')
        for key, name in [('results/reconciliation.duckdb', 'database'), ('results/manifest.json', 'manifest'), ('results/report.json', 'report')]:
            need(all(old_review['actual_receipt_pins'][key][part] == input_witnesses[name].pin()[part]
                     for part in ['path', 'bytes', 'sha256']), 'parent accepted input binding differs')
        need(all(old_review['input_pins']['progress'][part] == input_witnesses['progress'].pin()[part]
                 for part in ['path', 'bytes', 'sha256']), 'parent progress binding differs')

        report_file = capture(RUN / 'results/report.json')
        candidate_file = capture(RUN / 'results/candidates.parquet')
        report = report_file.value()
        need(report['schema'] == 'uscode-retained-ordinal-diagnosis/v1' and
             report['hypothesis'] == 'per-document-span-ordinal-hypothesis/v1' and
             report['status'] == 'completed_unpromoted_diagnosis', 'diagnosis profile differs')
        need(set(report['input_pins']) == set(INPUTS), 'diagnosis input inventory differs')
        for name, pin in report['input_pins'].items():
            need(pin == input_witnesses[name].pin(), 'exact result input custody differs')
        need(report['source_reference'] == old_manifest['source'], 'source reference changed')
        # The original source reference is not resolved, statted or opened.
        checked('five-authenticated-inputs', {'input_count': 5, 'original_source_opened': False,
                                              'source_reference_only': old_manifest['source']})

        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq
        db = duckdb.connect(':memory:', config={'memory_limit': '256MB', 'threads': 1, 'temp_directory': ''})
        stack.callback(db.close)
        db.execute("ATTACH '" + str(input_witnesses['database'].path).replace("'", "''") + "' AS original (READ_ONLY)")
        db.execute('CREATE TEMP TABLE archive AS SELECT record_kind,dataset_id,source_span_id,source_sha256,legal_id FROM read_parquet(?)',
                   [str(input_witnesses['progress'].path)])
        physical_archive = db.execute('SELECT count(*) FROM archive').fetchone()[0]
        span_count, distinct_span_count = db.execute("SELECT count(*),count(DISTINCT source_span_id) FROM archive WHERE record_kind='span'").fetchone()
        need(physical_archive == old_report['ledger_row_count'] and span_count == distinct_span_count == old_report['distinct_archived_span_id_count'], 'archive counts differ')
        need(db.execute("SELECT count(*) FROM archive WHERE record_kind NOT IN ('span','meta') OR record_kind IS NULL").fetchone()[0] == 0, 'invalid record kind')
        db.execute("CREATE TEMP TABLE unresolved AS SELECT a.* FROM archive a WHERE record_kind='span' AND NOT EXISTS "
                   '(SELECT 1 FROM original.target_occurrences r WHERE r.source_span_id=a.source_span_id)')
        unresolved = db.execute('SELECT count(*) FROM unresolved').fetchone()[0]
        need(unresolved == old_report['ledger_disposition_counts']['unresolved_source'], 'unresolved archive extent differs')
        checked('original-archive-and-unresolved-subset', {'physical_archive_rows': physical_archive,
                                                         'distinct_archived_ids': distinct_span_count, 'unresolved_ids': unresolved})

        retained = db.execute('SELECT count(*) FROM original.target_occurrences').fetchone()[0]
        verified = 0
        for batch in batches(db):
            for row in batch:
                need(identity(row, row['historical_span_ordinal'], old_manifest['source']['release_id']) == row['source_span_id'], 'historical ID differs')
                verified += 1
        need(verified == retained == 64969 == report['baseline_verified_occurrences'] == report['retained_physical_occurrences'], 'not every baseline verified')
        checked('independent-all-baselines', {'rows': verified, 'original_hash_helper_imported': False,
                                             'alternate_ids_computed_before_baseline_completion': False})

        db.execute('CREATE TEMP TABLE alternatives (occurrence_id VARCHAR,generated_span_id VARCHAR,hypothesis_span_id VARCHAR,'
                   'source_sha256 VARCHAR,legal_id VARCHAR,entry_cid VARCHAR,citation VARCHAR,title VARCHAR,section VARCHAR,'
                   'source_section_offset BIGINT,source_section_span_ordinal BIGINT,historical_span_ordinal BIGINT,'
                   'source_text_origin VARCHAR,raw_source_text_present BOOLEAN)')
        changed = 0
        for batch in batches(db):
            rows = []
            for row in batch:
                alternate = identity(row, row['source_section_span_ordinal'], old_manifest['source']['release_id'])
                changed += row['source_section_span_ordinal'] != row['historical_span_ordinal']
                rows.append([row['occurrence_id'].hex(), row['source_span_id'], alternate] +
                            [row[name] for name in COLUMNS[3:-1]])
            db.executemany('INSERT INTO alternatives VALUES (' + ','.join('?' for _ in range(14)) + ')', rows)
        db.execute('CREATE TEMP TABLE expected AS SELECT alt.*,count(*) OVER (PARTITION BY hypothesis_span_id) AS retained_match_count '
                   'FROM alternatives alt JOIN unresolved u ON alt.hypothesis_span_id=u.source_span_id '
                   'AND alt.source_sha256=u.source_sha256 AND alt.legal_id=u.legal_id')
        pairs, physical, ids = db.execute('SELECT count(*),count(DISTINCT occurrence_id),count(DISTINCT hypothesis_span_id) FROM expected').fetchone()
        ambiguous = db.execute('SELECT count(*) FROM (SELECT hypothesis_span_id FROM expected GROUP BY 1 HAVING count(DISTINCT occurrence_id)>1)').fetchone()[0]
        rebuilt = {'candidate_pairs': pairs, 'candidate_physical_occurrences': physical,
                   'candidate_distinct_archived_ids': ids, 'retained_subset_ambiguous_archived_ids': ambiguous,
                   'retained_subset_singleton_archived_ids': ids-ambiguous, 'changed_ordinal_retained_rows': changed}
        need(rebuilt == report['counts'] and report['archived_distinct_ids'] == distinct_span_count and
             report['unresolved_archived_ids'] == unresolved and report['unresolved_ids_without_retained_candidate'] == unresolved-ids,
             'independently rebuilt diagnosis counts differ')
        checked('independent-alternate-exact-joins-and-counts', rebuilt)

        candidate_body = candidate_file.body()
        parquet = pq.ParquetFile(io.BytesIO(candidate_body))
        need(parquet.schema_arrow.names == COLUMNS and parquet.metadata.num_rows == pairs, 'candidate schema or row count differs')
        for field in parquet.schema_arrow:
            wanted = pa.int64() if field.name in NUMERIC else pa.bool_() if field.name == 'raw_source_text_present' else pa.string()
            need(field.type == wanted, 'candidate identity column type differs')
        expected_query = 'SELECT * FROM expected ORDER BY hypothesis_span_id,source_section_offset,source_section_span_ordinal,occurrence_id'
        expected_cursor = db.execute(expected_query)
        rows_verified = 0
        ordered_digest = hashlib.sha256()
        for batch in parquet.iter_batches(batch_size=512):
            for row in batch.to_pylist():
                saved = expected_cursor.fetchone()
                need(saved is not None and row == dict(zip(COLUMNS, saved)), 'candidate row differs')
                ordered_digest.update(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode() + b'\n')
                rows_verified += 1
        need(expected_cursor.fetchone() is None and rows_verified == pairs, 'candidate output not exhausted exactly')
        need(report['candidate_artifact'] == {'path': 'candidates.parquet', 'bytes': len(candidate_body),
              'sha256': candidate_file.digest, 'rows': pairs}, 'candidate artifact pin differs')
        checked('every-candidate-row-and-identity-schema', {'rows_verified': rows_verified, 'columns': COLUMNS,
                                                          'ordered_rows_sha256': ordered_digest.hexdigest()})
        expected_examples = db.execute(expected_query + ' LIMIT ?', [arguments['example_limit']]).fetchall()
        need(report['examples'] == [dict(zip(COLUMNS, row)) for row in expected_examples], 'examples do not match ordered candidate prefix')
        checked('bounded-examples-exact-prefix', {'example_count': len(expected_examples)})
        need(all(report.get(field) is False for field in AUTHORITY), 'qualification flag promoted')
        need(len(report.get('limitations', [])) >= 4, 'subset limitations missing')
        checked('unpromoted-scientific-scope', {'false_flags': AUTHORITY, 'global_uniqueness_verified': False,
                                               'original_launch_authenticated': False, 'aliases_created': False})

        db.close()
        for witness in pins:
            witness.verify()
        canonical(lock_path)
        need(sig(os.fstat(lock)) == sig(lock_path.stat()) == lock_signature and not (parent / 'reconciliation.duckdb.wal').exists(), 'stopped parent custody changed')
        checked('final-byte-and-stopped-parent-fences', {'immutable_witness_count': len(pins), 'shared_lock_held': True, 'wal_absent': True})
        # Resource/scheduler release is independently closed by a separate bounded
        # read of final guard receipts and shared ledgers before receipt publication.
        draft = {'schema': 'uscode-identity-recovery-independent-pilot-results-review/v1', 'passed': False,
                 'status': 'metadata_replay_complete_pending_guard_review',
                 'completed': True, 'checks': checks, 'check_count': len(checks), 'findings': [],
                 'input_pins': report['input_pins'],
                 'actual_output_pins': {'report.json': report_file.pin(), 'candidates.parquet': candidate_file.pin()},
                 'rebuilt_counts': rebuilt, 'baseline_verified_occurrences': verified,
                 'unresolved_ids_without_retained_candidate': unresolved-ids,
                 'actual_receipt_pins': {str(w.path.relative_to(RUN)): w.pin() for w in pins if w.path.is_relative_to(RUN)},
                 'reviewer_source': {'path': str(Path(__file__)), 'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                 'elapsed_seconds': time.monotonic()-started,
                 'scope': 'All retained baseline IDs, declared alternate IDs and every unpromoted candidate row; no full-source identities, source text, models or proof.',
                 'mutations': {'original_inputs': False, 'aliases_created': False, 'source_or_models': False},
                 'limits': ['Candidate uniqueness is restricted to retained targets.',
                            'No original producer launch is authenticated by this replay.',
                            'Guardian cleanup and own scheduler/resource release must be added independently before final acceptance.']}
        output = CAMPAIGN / 'review/pilot-results-replay-draft.json'
        body = (json.dumps(draft, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
        need(len(body) <= 2*1024*1024, 'review exceeds output cap')
        with output.open('xb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps({'path': str(output), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                          'counts': rebuilt, 'checks': len(checks)}))


if __name__ == '__main__':
    main()

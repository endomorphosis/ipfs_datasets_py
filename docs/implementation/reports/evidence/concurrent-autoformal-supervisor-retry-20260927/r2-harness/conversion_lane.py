#!/usr/bin/env python3
"""Pinned compiler/decompiler smoke; neither compilation nor this receipt admits law."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
INVENTORY = ROOT / 'workspace/test-logs/federal-corpus-audits/source-span-batch-3-20260927-r2/capture-r1/outputs/source-inventory.json'
LOCK = ROOT.parent.parent / 'JevOps/jevops/statement_lock.py'
GATES = (
    'Company A shall submit backup report within 10 days unless emergency.',
    'The agency shall not disclose records.',
    'The officer shall retain the file for at least 20 days.',
)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def event():
    return {'monotonic_ns': time.monotonic_ns(), 'utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--start-token', required=True)
    args = parser.parse_args()
    runtime = args.runtime_root.resolve()
    runtime.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10_000_000, 10_000_000))
    config = json.loads(Path(__file__).with_name('frozen-config.json').read_bytes())
    external = config['conversion_input_sha256']
    def guard():
        changed = [str(ROOT / name) for name, value in config['source_sha256'].items() if sha(ROOT / name) != value]
        changed.extend(name for name, value in external.items() if sha(name) != value)
        if changed:
            raise RuntimeError('conversion provenance changed: ' + ', '.join(changed))
    guard()
    inventory = json.loads(INVENTORY.read_bytes())
    assert len(inventory['spans']) == 3
    for row in inventory['spans']:
        assert hashlib.sha256(row['text'].encode()).hexdigest() == row['span_text_sha256']
    write(runtime / 'ready.json', event())
    if sys.stdin.readline().rstrip('\n') != args.start_token:
        raise RuntimeError('parent start handshake did not match')
    guard()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic import autoformal
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest, OperationStatus, CanonicalErrorCode
    from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule
    paths = require_workspace_logic_tree()
    spec = importlib.util.spec_from_file_location('concurrent_smoke_statement_lock', LOCK)
    lock = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lock
    spec.loader.exec_module(lock)
    session = autoformal.AutoformalSession()
    compiler = TypedDeonticCanonicalCompiler()
    gate_rows, source_rows, checks = [], [], {}
    error = None
    started = event()
    write(runtime / 'conversion-started.json', started)
    try:
        for index, text in enumerate(GATES):
            before = time.monotonic()
            result = autoformal.compile_span(session, text, f'synthetic-concurrent-gate-{index}', allow_partial=False)
            elapsed = time.monotonic() - before
            assert result['compiler_status'] == 'compiled'
            row = session.rows[-1].public()
            vocab = session.vocabularies[row['clause_id']]
            assert vocab['actors'] and vocab['actions']
            assert all(isinstance(atom, str) for atoms in vocab.values() for atom in atoms)
            assert row['admitted'] is False
            gate_rows.append({'text': text, 'synthetic': True, 'wall_seconds': elapsed,
                              'timing_scope': 'compile_span including vocabulary, compilation and roundtrip',
                              'result': result, 'parser_vocabulary': vocab, 'admitted': False})
        backup, prohibit, minimum = [row['result'] for row in gate_rows]
        checks['deadline_and_exception'] = (backup['rule']['modality'] == 'O'
            and backup['rule']['temporal_records'] == [{'temporal_kind': 'within_duration', 'value': '10 days', 'quantity': 10}]
            and '10 days' in backup['decompiled'] and 'emergency' in backup['decompiled']
            and lock.pattern_from_rule(backup['rule']) is None)
        checks['prohibition'] = prohibit['rule']['modality'] == 'F'
        checks['minimum_duration'] = (minimum['rule']['temporal_records'] == [{'temporal_kind': 'minimum_duration', 'value': '20 days', 'quantity': 20}]
            and minimum['decompiled'].count('20 days') == 1 and 'at least 20 days' in minimum['decompiled']
            and 'at least days' not in minimum['decompiled']
            and lock.pattern_from_rule(minimum['rule']) == {'kind': 'threshold', 'fail': 19, 'meet': 20})
        empty_results = []
        for index, text in enumerate(GATES):
            result = compiler.compile(CompilerRequest(source_text=text, request_id=f'empty-{index}', atom_vocabulary=CanonicalAtomVocabulary()))
            empty_results.append(result.status is OperationStatus.ABSTAINED and result.canonical_ir is None
                                 and result.error.code is CanonicalErrorCode.UNSUPPORTED_SEMANTICS)
        checks['empty_vocabulary_abstains'] = all(empty_results)
        for span in inventory['spans']:
            before = time.monotonic()
            vocabulary = autoformal.vocabulary_from_clause(span['text'])
            parsed = time.monotonic()
            result = compiler.compile(CompilerRequest(source_text=span['text'], request_id=span['source_span_id'],
                atom_vocabulary=autoformal._vocabulary(vocabulary), allow_explicit_partial=False))
            compiled = time.monotonic()
            rules = result.canonical_ir.rules if result.canonical_ir else ()
            rendered = [decompile_rule(rule) for rule in rules]
            finished = time.monotonic()
            source_rows.append({'source': span, 'synthetic': False, 'parser_vocabulary': vocabulary,
                'compiler_status': result.status.value, 'rules': [rule.to_dict() for rule in rules],
                'decompiled': rendered, 'diagnostic_fields': autoformal._diagnostic_fields(result),
                'error': None if result.error is None else {'code': result.error.code.value, 'message': result.error.message},
                'vocabulary_seconds': parsed-before, 'compiler_seconds': compiled-parsed,
                'decompiler_seconds': finished-compiled, 'wall_seconds': finished-before,
                'allow_partial': False, 'admitted': False, 'formalized': False})
        checks['source_rows_processed'] = len(source_rows) == 3
        checks['source_gap_evidence_preserved'] = all(row['compiler_status'] == OperationStatus.ABSTAINED.value
            and row['diagnostic_fields'] and not row['rules'] for row in source_rows)
        guard()
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finished = event()
    write(runtime / 'conversion-finished.json', finished)
    checks['source_unchanged'] = all(sha(ROOT / name) == value for name, value in config['source_sha256'].items())
    checks['external_inputs_unchanged'] = all(sha(name) == value for name, value in external.items())
    summary = {'schema': 'concurrent-autoformal-conversion-smoke-v1', 'passed': error is None and all(checks.values()),
        'checks': checks, 'error': error, 'tree_pin': paths, 'gate_rows': gate_rows, 'source_rows': source_rows,
        'sample_count': 6, 'synthetic_gate_count': 3, 'source_span_count': 3,
        'elapsed_seconds': (finished['monotonic_ns']-started['monotonic_ns']) / 1e9,
        'conversion_input_sha256': external, 'admitted': False, 'formalized': False,
        'lake_executed': False, 'compiler_repair_performed': False, 'constitution_processed': False,
        'cache_observation': 'fresh lane process; metric disk cache disabled; OS cache uncontrolled'}
    write(runtime / 'summary.json', summary)
    print(json.dumps({'passed': summary['passed'], 'checks': checks, 'error': error}), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

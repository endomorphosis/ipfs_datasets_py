"""Declare executable task contracts and verify retained, source-bound evidence.

This is an inventory check, never authority to admit or formalize legal text.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import importlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
PLAN = Path('ipfs_datasets_py/logic/autoformal/legal_ir_autoencoder_supervisor_plan.json')
BOARD = Path('ipfs_datasets_py/logic/autoformal/LIRAE-TODO.md')
SCRIPT = 'scripts/ops/legal_ir/legal_ir_supervisor_contract.py'
EVIDENCE = Path('docs/implementation/reports/evidence/legal_ir_autoencoder')
SCHEMA = 'legal-ir-supervisor-task-receipt/v1'
REVISION = '5016b86a273ce5e4ffd066c5ae9f5fe494dd417e'
PARQUET_SHA256 = '4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8'
# An explicit deployment input, independent of the validator's private HOME.
PINNED_PARQUET = Path('/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots') / REVISION / 'uscode_parquet/laws.parquet'
CONSTITUTION_SHA256 = '9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b'
CONSTITUTION = EVIDENCE / 'inputs/constitution.txt'
SAMPLE_HASHES = sorted(['fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a', '6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2'])
TESTS = {
    'uscode': ['tests/unit/logic/test_uscode_ingest.py', 'tests/unit/logic/test_span_cache_exchange.py', 'tests/unit/logic/test_paired_span_census.py', 'tests/unit/logic/test_entity_cache.py'],
    'constitution': ['tests/unit/logic/test_constitution_inventory.py', 'tests/unit/logic/test_constitution_article_1_inventory.py', 'tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution'],
    'width': ['tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py', 'tests/unit/logic/test_paired_span_census.py'],
    'method': ['tests/unit/logic/autoformal/test_uscode_born_alive_definition_v1.py', 'tests/unit/logic/test_lean_units.py'],
}
OWNERS = {
    'uscode': ['uscode_ingest.py', 'span_cache_exchange.py', 'paired_span_census.py', 'entity_cache.py'],
    'constitution': ['constitution_inventory.py', 'constitution_shard_inventory.py', 'constitution_unit_projection.py', 'paired_span_census.py'],
    'width': [], 'method': ['lean_units.py', 'legal_source_definition_bridge_v2.py'],
}


class ContractError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ContractError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def kind(task_id):
    for prefix, name in (('USC', 'uscode'), ('CONST', 'constitution'), ('WIDTH', 'width'), ('METHOD', 'method')):
        if task_id.startswith('LIRAE-' + prefix + '-'):
            return name
    raise ContractError('unknown task family')


def directory(task_id):
    require(re.fullmatch(r'LIRAE-[A-Z0-9-]+', task_id), 'invalid task ID')
    return EVIDENCE / task_id.lower()


def selector(task_id):
    suffix = task_id.removeprefix('LIRAE-CONST-')
    return 'preamble' if suffix == 'PREAMBLE' else 'amend-' + str(int(suffix[2:])) if suffix.startswith('AM') else 'art-' + str(int(suffix[1:]))


def owner(root, name):
    if name == 'lean_units':
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return importlib.import_module('ipfs_datasets_py.logic.autoformal.lean_units')
    spec = importlib.util.spec_from_file_location('receipt_' + name, root / 'ipfs_datasets_py/logic/autoformal' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task_contract(task):
    task_id = task['task_id']
    family = kind(task_id)
    task_dir = directory(task_id).as_posix()
    tests = list(TESTS[family])
    owners = ['ipfs_datasets_py/logic/autoformal/' + name for name in OWNERS[family]]
    if family == 'width':
        suffix = '4096' if task_id.endswith('-4096') else 'dimensions'
        owners += ['ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_' + suffix + '.py', 'ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py']
        tests.append('tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_' + suffix + '.py')
    allowed = sorted(set([task_dir, *owners, *task.get('predicted_files', []), *[test.split('::')[0] for test in tests]]))
    commands = ['IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest ' + ' '.join(tests) + ' -q --tb=line', 'IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 ' + SCRIPT + ' --check-task ' + task_id]
    instructions = ('Write ' + task_dir + '/receipt.json schema=' + SCHEMA + ' task_id=' + task_id + ' task_kind=' + family + ' status=inventory|implemented authority={admitted:false,formalized:false' + (',roundtrip_ok:false' if family == 'constitution' else '') + '}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. ')
    instructions += {
        'uscode': 'source={repository:justicedao/ipfs_uscode,revision:' + REVISION + '}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache.',
        'constitution': 'Use exact retained plaintext ' + CONSTITUTION.as_posix() + ', sha256=' + CONSTITUTION_SHA256 + '; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=' + (selector(task_id) if family == 'constitution' else '') + '; Amendment21 requires repeal_treated_as_obligation=false.',
        'width': 'JSON observation artifact carries dimension,source_hashes for both born-alive inputs,profile_id,checkpoint_sha256,status=observed,training_executed=false,admitted=false,formalized=false,metrics={cosine_similarity,reconstruction_loss}. Retain actual checkpoint artifact kind checkpoint and replay evidence; hashes/metrics alone are insufficient. evidence.dimension matches. 8d role=donor corpus_default=false;384d corpus_default=true;768d token_ceiling=512;4096d encoder_executed=false development_result={successful:0,total:12}.',
        'method': 'lean_source artifact holds actual Lean source. evidence includes both pinned source_hashes and lake_ok=true. Validator reruns real lake build Legal. Skipped pinned-source tests supply no completion evidence.',
    }[family]
    return {'outputs': [task_dir + '/receipt.json'], 'allowed_paths': allowed, 'validation_commands': commands, 'receipt_instructions': instructions, 'required_validation_executables': ['lake', 'lean'] if family == 'method' else []}


def enrich(root):
    root = Path(root)
    plan = json.loads((root / PLAN).read_text())
    contracts = {}
    for task in plan['tasks']:
        contracts[task['task_id']] = task_contract(task)
        task.update(contracts[task['task_id']])
    chunks = re.split(r'(?=^## )', (root / BOARD).read_text(), flags=re.MULTILINE)
    seen = set()
    for index, chunk in enumerate(chunks):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
        if not match or match[1] not in contracts:
            continue
        task_id = match[1]
        seen.add(task_id)
        contract = contracts[task_id]
        chunk = re.sub(r'^- (?:outputs|allowed paths|predicted files|receipt instructions|validation|required validation executables):[^\n]*\n?', '', chunk, flags=re.MULTILINE)
        lines = ['- outputs: ' + ', '.join(contract['outputs']), '- allowed paths: ' + ', '.join(contract['allowed_paths']), '- receipt instructions: ' + contract['receipt_instructions'], '- validation: ' + '; '.join(contract['validation_commands'])]
        if contract['required_validation_executables']:
            lines.append('- required validation executables: ' + ', '.join(contract['required_validation_executables']))
        chunks[index] = chunk.rstrip() + '\n' + '\n'.join(lines) + '\n\n'
    require(seen == set(contracts), 'board/plan task IDs differ')
    (root / PLAN).write_text(json.dumps(plan, indent=2) + '\n')
    (root / BOARD).write_text(''.join(chunks).rstrip() + '\n')
    return {'task_count': len(contracts), 'enriched': True}


def check_board(root):
    root = Path(root)
    plan = json.loads((root / PLAN).read_text())
    found = {}
    for chunk in re.split(r'(?=^## )', (root / BOARD).read_text(), flags=re.MULTILINE):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
        if match:
            require(match[1] not in found, 'duplicate board task')
            found[match[1]] = chunk
    require(set(found) == {task['task_id'] for task in plan['tasks']}, 'board/plan task IDs differ')
    for task in plan['tasks']:
        task_id = task['task_id']
        chunk = found[task_id]
        contract = task_contract(task)
        for label, value in (('outputs', ', '.join(contract['outputs'])), ('allowed paths', ', '.join(contract['allowed_paths'])), ('validation', '; '.join(contract['validation_commands']))):
            require('- ' + label + ': ' + value in chunk, 'stale board ' + label + ' for ' + task_id)
        if contract['required_validation_executables']:
            require('- required validation executables: ' + ', '.join(contract['required_validation_executables']) in chunk, 'stale required executables for ' + task_id)
        require(all(task.get(key) == value for key, value in contract.items()), 'stale plan contract ' + task_id)
    require(sha((root / CONSTITUTION).read_bytes()) == CONSTITUTION_SHA256, 'retained Constitution input differs')
    return {'task_count': len(plan['tasks']), 'board_contract_valid': True}


def false_flags(value, constitution=False):
    require(isinstance(value, dict) and value.get('admitted') is False and value.get('formalized') is False, 'admitted/formalized must be exactly false')
    if constitution:
        require(value.get('roundtrip_ok') is False, 'Constitution roundtrip_ok must be false')
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {'admitted', 'formalized', 'roundtrip_ok'}:
                    require(child is False, 'artifact authority must stay false')
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def read_artifacts(root, task_id, receipt):
    result = {}
    entries = receipt.get('artifacts')
    task_dir = (root / directory(task_id)).resolve()
    require(isinstance(entries, list) and entries, 'artifact references required')
    for entry in entries:
        relative = Path(str(entry.get('path', '')))
        path = root / relative
        require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe artifact path')
        require(path.is_file() and path.resolve().is_relative_to(task_dir) and path.name != 'receipt.json', 'artifact must exist inside task directory')
        raw = path.read_bytes()
        label = entry.get('kind')
        require(0 < len(raw) <= 128 * 1024 * 1024 and entry.get('sha256') == sha(raw), 'artifact hash/size differs')
        require(isinstance(label, str) and label and label not in result, 'unique artifact kinds required')
        result[label] = raw
    return result


def payload(data, label):
    require(label in data, 'missing ' + label + ' artifact')
    return json.loads(data[label])


def usc_rows(title):
    require(PINNED_PARQUET.is_file(), 'exact pinned US Code deployment input missing')
    with PINNED_PARQUET.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == PARQUET_SHA256, 'US Code Parquet input digest differs')
    import pyarrow.parquet as pq
    result = []
    source_row_index = 0
    for batch in pq.ParquetFile(PINNED_PARQUET).iter_batches(batch_size=4000, columns=['ipfs_cid', 'title_number', 'section_number', 'text']):
        for row in batch.to_pylist():
            row['source_row_index'] = source_row_index
            source_row_index += 1
            if ('NA' if row['title_number'] is None else str(row['title_number'])) == title:
                result.append(row)
    return sorted(result, key=lambda row: (str(row['section_number'] or ''), str(row['ipfs_cid'])))


def validate_uscode(shard, receipt, data):
    source = receipt.get('source', {})
    require(source.get('repository') == 'justicedao/ipfs_uscode' and source.get('revision') == REVISION, 'US Code pin differs')
    require(all(receipt.get('evidence', {}).get(key) == shard[key] for key in ('title', 'start', 'end', 'count')), 'shard identity differs')
    expected = usc_rows(str(shard['title']))[shard['start']:shard['end']]
    sections, spans, entities = [payload(data, label) for label in ('sections', 'spans', 'entities')]
    require(all(isinstance(rows, list) for rows in (sections, spans, entities)), 'section/span/entity arrays required')
    require(len(expected) == shard['count'] == len(sections), 'all pinned sections need rows')
    def row_key(row):
        cid = row.get('ipfs_cid')
        return cid if isinstance(cid, str) and cid else ('parquet-row', row.get('source_row_index'))
    sources = {row_key(row): row for row in expected}
    actual = {row_key(row): row for row in sections}
    span_map = {}
    require(len(actual) == len(sections) and set(actual) == set(sources), 'section identities differ')
    for row in spans:
        false_flags(row)
        cid, text, sid = row.get('source_ipfs_cid'), row.get('text'), row.get('id')
        require(cid in sources and isinstance(text, str) and text.strip() and text in sources[cid]['text'], 'span plaintext absent from pinned source')
        require(row.get('source_text_sha256') == sha(sources[cid]['text'].encode()), 'span source hash differs')
        require(isinstance(sid, str) and sid and sid not in span_map, 'unique span IDs required')
        span_map[sid] = row
    for cid, source in sources.items():
        row = actual[cid]
        false_flags(row)
        if source['text'] is None:
            require(row.get('text') is None and row.get('source_text_sha256') is None and row.get('ipfs_cid') == source['ipfs_cid'] and row.get('status') == 'abstain' and isinstance(row.get('reason'), str) and row['reason'].strip() and not row.get('span_ids'), 'missing source plaintext requires explicit abstention')
            continue
        require(row.get('text') == source['text'] and row.get('source_text_sha256') == sha(source['text'].encode()), 'section plaintext/hash differs')
        if row.get('status') == 'abstain':
            require(isinstance(row.get('reason'), str) and row['reason'].strip(), 'abstention reason required')
        else:
            refs = row.get('span_ids')
            require(row.get('status') == 'spans' and isinstance(refs, list) and refs and all(sid in span_map and span_map[sid]['source_ipfs_cid'] == cid for sid in refs), 'section must cite its actual spans')
    for row in entities:
        false_flags(row)
        refs = row.get('span_ids')
        require(isinstance(row.get('id'), str) and row['id'] and isinstance(refs, list) and refs and all(sid in span_map for sid in refs), 'entity must cite actual spans')


def validate_constitution(root, task_id, receipt, data):
    source, rows = payload(data, 'source'), payload(data, 'spans')
    require(isinstance(source, dict) and isinstance(source.get('text'), str) and source.get('source_id'), 'full source plaintext/identity required')
    digest = sha(source['text'].encode())
    require(digest == CONSTITUTION_SHA256 == sha((root / CONSTITUTION).read_bytes()), 'Constitution retained input differs')
    require(source.get('sha256') == digest and receipt.get('source', {}).get('sha256') == digest and receipt['source'].get('source_id') == source['source_id'], 'Constitution source binding differs')
    unit = selector(task_id)
    require(receipt.get('evidence', {}).get('unit_id') == unit, 'unit selector differs')
    inventory = owner(root, 'constitution_inventory').inventory_constitution(source['text'])
    expected = [row for row in inventory['spans'] if row['unit_id'] == unit or row['unit_id'].startswith(unit + '.')]
    require(expected and isinstance(rows, list) and len(rows) == len(expected), 'Constitution span coverage differs')
    actual = {row.get('id'): row for row in rows}
    require(len(actual) == len(rows) and set(actual) == {row['id'] for row in expected}, 'Constitution span IDs differ')
    for row in expected:
        item = actual[row['id']]
        false_flags(item, True)
        require(all(item.get(key) == row[key] for key in ('unit_id', 'text', 'status', 'reason')) and item.get('source_id') == source['source_id'] and item.get('source_text_sha256') == digest, 'span differs from actual inventory/source binding')
    if unit == 'amend-21':
        require(any(edge.get('kind') == 'repeal' and edge.get('target') == 'amend-18' for edge in inventory['edges']) and receipt['evidence'].get('repeal_treated_as_obligation') is False, 'retain text-backed repeal fixture')


def validate_width(task_id, receipt, data):
    row = payload(data, 'observation')
    false_flags(row)
    dimension = int(task_id.split('-')[-1])
    require(row.get('dimension') == dimension and receipt.get('evidence', {}).get('dimension') == dimension, 'width differs')
    require(sorted(row.get('source_hashes', [])) == SAMPLE_HASHES, 'both pinned sample sources required')
    require(row.get('training_executed') is False and row.get('status') == 'observed', 'unavailable assets cannot complete')
    require(isinstance(row.get('profile_id'), str) and row['profile_id'] and 'checkpoint' in data and sha(data['checkpoint']) == row.get('checkpoint_sha256'), 'actual profile/checkpoint identity required')
    metrics = row.get('metrics', {})
    require(all(type(metrics.get(key)) in (int, float) and math.isfinite(metrics[key]) for key in ('cosine_similarity', 'reconstruction_loss')), 'finite measured metrics required')
    require(-1 <= metrics['cosine_similarity'] <= 1 and metrics['reconstruction_loss'] >= 0, 'metrics out of range')
    if dimension == 8:
        require(row.get('role') == 'donor' and row.get('corpus_default') is False, '8d remains donor')
    elif dimension == 384:
        require(row.get('corpus_default') is True, '384d remains corpus default')
    elif dimension == 768:
        require(row.get('token_ceiling') == 512, 'retain selected profile 512-token ceiling')
    else:
        require(row.get('encoder_executed') is False and row.get('development_result') == {'successful': 0, 'total': 12}, 'reuse saved vectors and retain 0/12')


def validate(root, task_id):
    root = Path(root).resolve()
    plan = json.loads((root / PLAN).read_text())
    require(any(task['task_id'] == task_id for task in plan['tasks']), 'task absent from plan')
    receipt = json.loads((root / directory(task_id) / 'receipt.json').read_text())
    family = kind(task_id)
    require(receipt.get('schema') == SCHEMA and receipt.get('task_id') == task_id and receipt.get('task_kind') == family, 'receipt identity differs')
    require(receipt.get('status') in {'inventory', 'implemented'}, 'pending/unavailable work cannot complete')
    false_flags(receipt.get('authority'), family == 'constitution')
    data = read_artifacts(root, task_id, receipt)
    if family == 'uscode':
        validate_uscode(next(row for row in plan['shards'] if row['task_id'] == task_id), receipt, data)
    elif family == 'constitution':
        validate_constitution(root, task_id, receipt, data)
    elif family == 'width':
        validate_width(task_id, receipt, data)
    else:
        require(sorted(receipt.get('evidence', {}).get('source_hashes', [])) == SAMPLE_HASHES and receipt['evidence'].get('lake_ok') is True, 'method source pins/Lake result differ')
        require('lean_source' in data, 'actual Lean source required')
        source = data['lean_source'].decode()
        require(not re.search(r'\b(sorry|axiom)\b', source), 'Lean proof escape')
        lean = owner(root, 'lean_units')
        require(source == lean.render_term_lean('object', 'born alive', statute_ids=['usc:us:1:8', 'usc:us:10:1059']), 'method source differs from pinned template')
        found = {row['ipfs_cid']: sha(row['text'].encode()) for title in ('1', '10') for row in usc_rows(title)}
        require(found.get('bafkreig4hls5clk3wa5iec5oa575e7gcpnyn3smiicsxgucu4yl654cvnu') == SAMPLE_HASHES[1] and found.get('bafkreihd2kvpadnqo2bwhjti7sq3kunzamoicottjgy32kva6eduqkcvru') == SAMPLE_HASHES[0], 'method source plaintext pins differ')
        result = lean.probe_lean_source(source)
        require(result.get('lake_ok') is True and result.get('admitted') is False and result.get('formalized') is False, 'real lake build Legal failed')
    return {'task_id': task_id, 'validated': True, 'admitted': False, 'formalized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--enrich', action='store_true')
    modes.add_argument('--check-board', action='store_true')
    modes.add_argument('--check-task', metavar='TASK_ID')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = enrich(args.root) if args.enrich else check_board(args.root) if args.check_board else validate(args.root, args.check_task)
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        print('LegalIR contract failed: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Package reviewed identity diagnostics without replacing original model assets."""
from pathlib import Path
import hashlib
import io
import json
import os
import re
import stat

BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-identity-recovery-20261011-01'
DATASETS = BASE / '.worktrees/retained-wording-checkpoint-integration-datasets-20261007'
ROOT = BASE / '.worktrees/dual-bank-wording-adapter-root-20261007'
MAX_FILE = 2 * 1024 * 1024
MAX_PACKAGE = 16 * 1024 * 1024
SUFFIXES = {'.json', '.jsonl', '.xml', '.md', '.py', '.log', '.parquet'}
REQUIRED = {'STATUS.md', 'campaign.json', 'run-plan.json', 'command.json', 'arguments.json',
            'review/local-recipe-survey.json', 'review/remote-producer-survey.json',
            'review/identity-pilot-resource-survey.json', 'review/implementation-review.json',
            'review/pilot-readiness.json', 'review/pilot-results-review.json',
            'review/final-status-review.json', 'review/implementation-memory-review.json',
            'review/pilot-readiness-02.json', 'review/failed-attempt-resource-review.json'}
RUN_RESULTS = BASE / 'external/ipfs_datasets/workspace/test-logs/uscode-identity-recovery-20261011-01/ordinal-profile-02/results'
CANDIDATE_COLUMNS = ['occurrence_id', 'generated_span_id', 'hypothesis_span_id',
                     'source_sha256', 'legal_id', 'entry_cid', 'citation', 'title', 'section',
                     'source_section_offset', 'source_section_span_ordinal', 'historical_span_ordinal',
                     'source_text_origin', 'raw_source_text_present', 'retained_match_count']
NUMERIC_COLUMNS = {'source_section_offset', 'source_section_span_ordinal',
                   'historical_span_ordinal', 'retained_match_count'}


def witness(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_file(path):
    if path.resolve(strict=True) != path or path.is_symlink():
        raise ValueError('Canonical regular evidence paths required')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= MAX_FILE:
        raise ValueError('Evidence exceeds the regular-file byte bound')
    with path.open('rb') as stream:
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Evidence changed before read')
        body = stream.read(MAX_FILE + 1)
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Evidence changed during read')
    if len(body) != before.st_size or witness(path.stat()) != witness(before):
        raise ValueError('Evidence changed after read')
    return body, witness(before)


def selected():
    if CAMPAIGN.resolve(strict=True) != CAMPAIGN:
        raise ValueError('Canonical campaign root required')
    result = {}
    for path in sorted(CAMPAIGN.rglob('*')):
        relative = path.relative_to(CAMPAIGN).as_posix()
        if ('__pycache__' in path.parts or relative == 'index.json'
                or relative.startswith('publication') or path.suffix not in SUFFIXES):
            continue
        if path.is_symlink():
            raise ValueError('Selected evidence must not use symlink aliases')
        if path.is_file():
            if path.suffix == '.parquet' and relative != 'measured-run/results/candidates.parquet':
                raise ValueError('Only the exact reviewed candidate Parquet may be packaged')
            result[relative] = path
    if not REQUIRED.issubset(result):
        raise ValueError('Required source, method, results or document review is missing')
    return result


def reviewed(files):
    review = json.loads(files['review/final-status-review.json'])
    checks = review.get('checks')
    body = files['STATUS.md']
    if (review.get('status') != 'accepted' or review.get('findings') != []
            or not isinstance(checks, list) or not checks
            or any(not isinstance(c, dict) or c.get('passed') is not True for c in checks)
            or type(review.get('check_count')) is not int or review['check_count'] != len(checks)
            or review.get('document', {}).get('path') != str(CAMPAIGN / 'STATUS.md')
            or review.get('document', {}).get('bytes') != len(body)
            or review.get('document', {}).get('sha256') != hashlib.sha256(body).hexdigest()):
        raise ValueError('Final document must match its accepted review')
    result = json.loads(files['review/pilot-results-review.json'])
    checks = result.get('checks')
    if (result.get('passed') is not True or result.get('completed') is not True
            or result.get('findings') != [] or not isinstance(checks, list) or not checks
            or any(not isinstance(c, dict) or c.get('passed') is not True for c in checks)
            or type(result.get('check_count')) is not int or result['check_count'] != len(checks)):
        raise ValueError('Stopped results need completed independent acceptance')
    pins = result.get('actual_output_pins', {})
    if set(pins) != {'report.json', 'candidates.parquet'}:
        raise ValueError('Exact independent output pin inventory required')
    for filename, pin in pins.items():
        body = files.get('measured-run/results/' + filename)
        if (not isinstance(pin, dict) or body is None
                or pin.get('path') != str(RUN_RESULTS / filename)
                or pin.get('bytes') != len(body)
                or pin.get('sha256') != hashlib.sha256(body).hexdigest()):
            raise ValueError('Reviewed output bytes differ from captured package')
    report = json.loads(files['measured-run/results/report.json'])
    if (report.get('schema') != 'uscode-retained-ordinal-diagnosis/v1'
            or report.get('hypothesis') != 'per-document-span-ordinal-hypothesis/v1'
            or report.get('status') != 'completed_unpromoted_diagnosis'):
        raise ValueError('Exact completed unpromoted diagnosis profile required')
    for field in ('original_source_read', 'models_loaded', 'tokenizers_loaded', 'aliases_created',
                  'original_producer_recipe_authenticated', 'full_source_uniqueness_verified',
                  'embedding_reuse_qualified', 'teacher_qualified', 'training_admitted',
                  'semantic_gold', 'semantic_fidelity_qualified', 'proof_authority'):
        if report.get(field) is not False:
            raise ValueError('Identity diagnosis must remain unpromoted and source-only')
    inputs = report.get('input_pins')
    if not isinstance(inputs, dict) or set(inputs) != {'database', 'manifest', 'report', 'progress', 'accepted_review'}:
        raise ValueError('Complete exact input custody inventory required')
    args = json.loads(files['arguments.json'])
    names = {'database': ('database_path', 'expected_database_sha256'),
             'manifest': ('manifest_path', 'expected_manifest_sha256'),
             'report': ('report_path', 'expected_report_sha256'),
             'progress': ('progress_parquet', 'expected_progress_sha256'),
             'accepted_review': ('accepted_review_path', 'expected_accepted_review_sha256')}
    for name, (path_arg, hash_arg) in names.items():
        pin = inputs[name]
        if (not isinstance(pin, dict) or type(pin.get('bytes')) is not int or pin['bytes'] <= 0
                or not isinstance(pin.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'])
                or pin.get('sha256') != args.get(hash_arg) or pin.get('path') != args.get(path_arg)
                or not isinstance(pin.get('path'), str) or not Path(pin['path']).is_absolute()
                or Path(pin['path']).resolve(strict=True) != Path(pin['path'])):
            raise ValueError('Input path, bytes or digest differs from admitted arguments')
    if result.get('input_pins') != inputs:
        raise ValueError('Independent input custody differs from the stopped report')
    import pyarrow as pa
    import pyarrow.parquet as pq
    candidate = files['measured-run/results/candidates.parquet']
    parquet = pq.ParquetFile(io.BytesIO(candidate))
    if parquet.schema_arrow.names != CANDIDATE_COLUMNS:
        raise ValueError('Unexpected candidate identity columns')
    for field in parquet.schema_arrow:
        expected = (pa.int64() if field.name in NUMERIC_COLUMNS else
                    pa.bool_() if field.name == 'raw_source_text_present' else pa.string())
        if field.type != expected:
            raise ValueError('Unexpected candidate identity column type')
    pin = report.get('candidate_artifact', {})
    if (pin.get('path') != 'candidates.parquet' or pin.get('bytes') != len(candidate)
            or pin.get('sha256') != hashlib.sha256(candidate).hexdigest()
            or type(pin.get('rows')) is not int or pin['rows'] != parquet.metadata.num_rows
            or pin['rows'] != report.get('counts', {}).get('candidate_pairs')):
        raise ValueError('Report and candidate identity artifact differ')
    return report


def unchanged(paths, signatures):
    if set(selected()) != set(paths):
        raise ValueError('Selected evidence set changed while packaging')
    for relative, path in paths.items():
        if path.resolve(strict=True) != path or witness(path.stat()) != signatures[relative]:
            raise ValueError('Evidence changed while packaging: ' + relative)


def standalone(body, prefix):
    def rewrite(match):
        target = match.group(1)
        if target.startswith(('#', '/')) or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
            return match.group(0)
        return '](' + prefix + target + ')'
    return re.sub(r'\]\(([^)]+)\)', rewrite, body.decode('utf-8')).encode('utf-8')


def write_new(path, body):
    if path.resolve(strict=False) != path or path.is_symlink():
        raise ValueError('Canonical fresh publication path required')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve(strict=False) != path or path.is_symlink():
        raise ValueError('Publication parent changed during creation')
    with path.open('xb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if read_file(path)[0] != body:
        raise ValueError('Copied publication bytes differ')


def main():
    paths = selected()
    files, signatures = {}, {}
    total = 0
    for relative, path in paths.items():
        files[relative], signatures[relative] = read_file(path)
        total += len(files[relative])
        if total > MAX_PACKAGE:
            raise ValueError('Evidence exceeds aggregate package bound')
    report = reviewed(files)
    index = {'schema': 'uscode-identity-recovery-evidence-index/v1',
             'scope': 'Retained source identities and ordinal hypothesis diagnostics; no promoted aliases',
             'aliases_promoted': 0, 'models_executed': False, 'training_executed': False,
             'embedding_reuse_qualified': False, 'proof_authority': False,
             'diagnostic_summary': {key: report[key] for key in ('retained_physical_occurrences',
                 'baseline_verified_occurrences', 'archived_distinct_ids', 'unresolved_archived_ids',
                 'counts', 'unresolved_ids_without_retained_candidate')},
             'files': {name: {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                       for name, body in files.items()}}
    encoded = (json.dumps(index, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    destinations = [
        (DATASETS / 'docs/autoencoders/evidence/uscode-identity-recovery-20261011-01',
         DATASETS / 'docs/autoencoders/uscode_identity_recovery_20261011.md',
         'evidence/uscode-identity-recovery-20261011-01/'),
        (ROOT / 'artifacts/uscode-identity-recovery-20261011-01',
         ROOT / 'implementation_plan/docs/73-uscode-identity-recovery-2026-10-11.md',
         '../../artifacts/uscode-identity-recovery-20261011-01/')]
    for destination, document, prefix in destinations:
        if (destination.resolve(strict=False) != destination or document.resolve(strict=False) != document
                or destination.is_symlink() or document.is_symlink()):
            raise ValueError('Canonical publication destinations required before mutation')
        body = standalone(files['STATUS.md'], prefix)
        if (len(encoded) > MAX_FILE or len(body) > MAX_FILE
                or total + len(encoded) + len(body) > MAX_PACKAGE):
            raise ValueError('Package, index and document exceed publication bounds')
        if destination.exists() or document.exists():
            raise ValueError('Identity publication must use fresh paths')
    unchanged(paths, signatures)
    for destination, document, prefix in destinations:
        destination.mkdir(parents=True, exist_ok=False)
        for relative, body in files.items():
            write_new(destination / relative, body)
        write_new(destination / 'index.json', encoded)
        write_new(document, standalone(files['STATUS.md'], prefix))
    unchanged(paths, signatures)
    write_new(CAMPAIGN / 'index.json', encoded)
    print(json.dumps({'files_per_package': len(files) + 1,
                      'bytes_per_package': total + len(encoded),
                      'index_sha256': hashlib.sha256(encoded).hexdigest()}))


if __name__ == '__main__':
    main()

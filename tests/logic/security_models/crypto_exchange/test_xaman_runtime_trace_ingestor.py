import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_runtime_trace_ingestor import (
    MONITOR_CATEGORIES,
    XamanRuntimeTraceIngestor,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
REPORT_PATH = CORPUS_DIR / 'runtime-trace-report.json'
MANIFEST_PATH = CORPUS_DIR / 'source-manifest.json'
COVERAGE_PATH = CORPUS_DIR / 'source-coverage.json'
CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_runtime_trace_assumptions.md'

REQUIRED_FACT_CATEGORIES = {
    'payload_intake',
    'review',
    'auth',
    'signing',
    'rejection',
    'expiration',
    'network_binding',
    'broadcast',
}

REQUIRED_SOURCE_FACT_IDS = {
    'xaman-runtime-trace:fact:payload_intake-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:review-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:auth-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:signing-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:rejection-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:expiration-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:network_binding-monitor-from-reviewed-source',
    'xaman-runtime-trace:fact:broadcast-monitor-from-reviewed-source',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _manifest_files() -> dict[str, dict[str, Any]]:
    manifest = _load_json(MANIFEST_PATH)
    return {entry['path']: entry for entry in manifest['files']}


def test_xaman_runtime_trace_report_schema_source_pin_and_regeneration() -> None:
    report = _load_json(REPORT_PATH)
    manifest = _load_json(MANIFEST_PATH)
    coverage = _load_json(COVERAGE_PATH)
    regenerated = XamanRuntimeTraceIngestor().build_report(
        manifest_path=MANIFEST_PATH,
        coverage_path=COVERAGE_PATH,
        claims_path=CLAIMS_PATH,
    )

    assert report == regenerated
    assert report['schema_version'] == 'xaman-runtime-trace-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-074'
    assert report['corpus'] == 'xaman-app'
    assert report['source']['repo_url'] == manifest['source']['repo_url']
    assert report['source']['commit_sha'] == manifest['source']['commit_sha']
    assert report['source']['manifest_schema_version'] == manifest['schema_version']
    assert report['source']['manifest_aggregate_sha256'] == manifest['reproducibility']['aggregate_sha256']
    assert report['source']['coverage_schema_version'] == coverage['schema_version']
    assert report['review']['review_status'] == 'reviewed'


def test_xaman_runtime_trace_report_ingests_e2e_features_and_source_monitors() -> None:
    report = _load_json(REPORT_PATH)
    monitor_facts = report['monitor_facts']

    assert report['trace_inputs']['e2e_feature_count'] == 6
    assert report['trace_inputs']['runtime_trace_count'] == 0
    assert {
        'e2e/01_setup.feature',
        'e2e/02_generate_account.feature',
        'e2e/03_import_account.feature',
        'e2e/04_upgrade_account.feature',
        'e2e/05_auth.feature',
        'e2e/06_linking.feature',
    } <= set(report['trace_inputs']['source_paths'])
    assert {fact['id'] for fact in monitor_facts} >= REQUIRED_SOURCE_FACT_IDS
    assert {fact['category'] for fact in monitor_facts} >= REQUIRED_FACT_CATEGORIES
    assert report['monitor_coverage']['required_categories'] == list(MONITOR_CATEGORIES)
    assert report['monitor_coverage']['missing_categories'] == []
    assert report['monitor_coverage']['complete_for_source_and_e2e_inputs'] is True

    linking = next(trace for trace in report['runtime_traces'] if trace['source_path'] == 'e2e/06_linking.feature')
    assert {event['category'] for event in linking['events']} >= {
        'payload_intake',
        'review',
        'network_binding',
    }
    assert all(trace['conformance_status'] == 'source_declared_not_runtime_equivalent' for trace in report['runtime_traces'])


def test_xaman_runtime_trace_ingestor_normalizes_runtime_events_to_monitor_facts() -> None:
    ingestor = XamanRuntimeTraceIngestor()
    traces = ingestor.runtime_traces_from_payload(
        {
            'id': 'fixture-real-device-happy-path',
            'device_class': 'real_device',
            'events': [
                {'event': 'qr_scan', 'payload_uuid': 'payload-1', 'timestamp': '2026-07-08T10:00:00Z'},
                {'event': 'review_displayed', 'payload_uuid': 'payload-1'},
                {'event': 'passcode_accepted', 'account': 'rSigner'},
                {'event': 'tx_signed', 'txid': 'ABC'},
                {'event': 'payload_rejected', 'payload_uuid': 'payload-2'},
                {'event': 'payload_expired', 'payload_uuid': 'payload-3'},
                {'event': 'network_bound', 'network': 'mainnet'},
                {'event': 'ledger_submit', 'txid': 'ABC'},
            ],
        },
        source_path='traces/real-device.json',
    )
    manifest = _load_json(MANIFEST_PATH)
    facts = ingestor.monitor_facts_from_traces(traces, manifest=manifest)

    assert len(traces) == 1
    assert traces[0]['device_class'] == 'real_device'
    assert {event['category'] for event in traces[0]['events']} == REQUIRED_FACT_CATEGORIES
    assert {fact['category'] for fact in facts} == REQUIRED_FACT_CATEGORIES
    assert all(fact['source_kind'] == 'runtime_trace' for fact in facts)
    assert all(fact['device_class'] == 'real_device' for fact in facts)
    assert all(fact['normalized_fact']['real_device_required_for_runtime_equivalence'] is True for fact in facts)


def test_xaman_runtime_trace_report_blocks_runtime_equivalence_without_real_device_traces() -> None:
    report = _load_json(REPORT_PATH)
    claims = _load_json(CLAIMS_PATH)
    gap = report['not_modeled_gaps'][0]
    blocking = report['blocking_runtime_equivalence']

    assert blocking['status'] == 'BLOCKING'
    assert blocking['absent_real_device_traces'] is True
    assert blocking['blocking_gap_ids'] == ['xaman-runtime-trace:gap:real-device-runtime-traces-absent']
    assert gap['status'] == 'NOT_MODELED'
    assert gap['blocking'] is True
    assert 'real-device runtime traces' in gap['summary']
    assert all(gap['required_evidence_to_model'])

    runtime_claim = next(
        claim for claim in claims['security_claims'] if claim['category'] == 'runtime_equivalence'
    )
    binding = next(binding for binding in report['claim_bindings'] if binding['claim_id'] == runtime_claim['id'])
    assert set(binding['monitor_categories']) == REQUIRED_FACT_CATEGORIES
    assert binding['runtime_equivalence_required'] is True


def test_xaman_runtime_trace_evidence_is_manifest_bound_or_machine_extracted() -> None:
    report = _load_json(REPORT_PATH)
    manifest_files = _manifest_files()

    for trace in report['runtime_traces']:
        for evidence in trace['evidence']:
            assert evidence['review_status'] == 'reviewed'
            assert evidence['path'] in manifest_files
            assert evidence['sha256'] == manifest_files[evidence['path']]['sha256']

    for fact in report['monitor_facts']:
        assert fact['status'] == 'MONITOR_FACT'
        assert fact['evidence'], fact['id']
        for evidence in fact['evidence']:
            assert evidence['line_start'] >= 1
            assert evidence['line_end'] >= evidence['line_start']
            if evidence['kind'] == 'source_code':
                assert evidence['review_status'] == 'reviewed'
                assert evidence['path'] in manifest_files
                assert evidence['sha256'] == manifest_files[evidence['path']]['sha256']
            elif evidence['kind'] == 'test_fixture':
                assert evidence['review_status'] == 'machine_extracted'
            else:
                raise AssertionError(f'Unexpected evidence kind: {evidence}')

    gap_evidence = report['not_modeled_gaps'][0]['evidence'][0]
    assert gap_evidence['kind'] == 'source_manifest'
    assert gap_evidence['path'] == 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
    assert gap_evidence['sha256'] == report['source']['manifest_aggregate_sha256']


def test_xaman_runtime_trace_assumptions_document_covers_artifact_and_validation() -> None:
    document = DOC_PATH.read_text(encoding='utf-8')
    report = _load_json(REPORT_PATH)

    assert 'PORTAL-CXTP-074' in document
    assert 'security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json' in document
    assert report['source']['commit_sha'] in document
    assert 'real-device runtime traces' in document
    assert 'BLOCKING' in document
    assert 'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_runtime_trace_ingestor.py -q' in document

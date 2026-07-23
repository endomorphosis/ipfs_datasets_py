import json
from pathlib import Path
from typing import Any

import duckdb

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_runtime_trace_ingestor import (
    REQUIRED_MONITOR_CATEGORIES,
    XamanRuntimeTraceIngestor,
    build_report,
    main,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'runtime-trace-report.json'
MANIFEST_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'source-manifest.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_runtime_trace_assumptions.md'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _manifest_files() -> dict[str, dict[str, Any]]:
    manifest = _load_json(MANIFEST_PATH)
    return {entry['path']: entry for entry in manifest['files']}


def test_xaman_runtime_trace_report_schema_and_fail_closed_status() -> None:
    report = build_report(repo_root=REPO_ROOT, generated_at_utc='2026-07-10T00:00:00Z')

    assert report['schema_version'] == 'xaman-runtime-trace-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-074'
    assert report['overall_status'] == 'blocked'
    assert report['production_release_blocked'] is True
    assert report['security_decision'] == 'BLOCK_RUNTIME_EQUIVALENCE_MISSING_REAL_DEVICE_TRACES'
    assert report['blocker_count'] >= 2
    assert report['artifact_cid'].startswith('sha256:')


def test_xaman_runtime_trace_e2e_features_are_manifest_bound() -> None:
    report = build_report(repo_root=REPO_ROOT, generated_at_utc='2026-07-10T00:00:00Z')
    manifest_files = _manifest_files()

    features = {entry['path']: entry for entry in report['e2e_features']}
    assert {
        'e2e/02_generate_account.feature',
        'e2e/03_import_account.feature',
        'e2e/05_auth.feature',
        'e2e/06_linking.feature',
    } <= set(features)

    for path, feature in features.items():
        assert feature['sha256'] == manifest_files[path]['sha256']
        assert feature['size_bytes'] == manifest_files[path]['size_bytes']
        assert feature['review_status'] == 'reviewed'
        assert feature['categories']


def test_xaman_runtime_trace_source_models_are_reviewed_inputs() -> None:
    report = build_report(repo_root=REPO_ROOT, generated_at_utc='2026-07-10T00:00:00Z')

    source_models = report['source_models']
    assert source_models['payload_lifecycle']['status'] == 'ready'
    assert source_models['xrpl_transaction']['status'] == 'ready'
    assert source_models['wallet_auth']['status'] == 'ready'
    assert source_models['payload_lifecycle']['modeled_fact_count'] >= 15
    assert source_models['xrpl_transaction']['modeled_fact_count'] >= 13


def test_xaman_runtime_trace_monitor_facts_cover_required_categories() -> None:
    report = build_report(repo_root=REPO_ROOT, generated_at_utc='2026-07-10T00:00:00Z')
    facts = report['monitor_facts']

    assert len(facts) >= len(REQUIRED_MONITOR_CATEGORIES)
    assert set(REQUIRED_MONITOR_CATEGORIES) <= {fact['category'] for fact in facts}
    assert all(fact['evidence'] for fact in facts)
    assert all(fact['normalized_fact'] for fact in facts)

    by_category = {fact['category']: fact for fact in facts}
    assert by_category['runtime_equivalence']['status'] == 'BLOCKED'
    assert by_category['runtime_equivalence']['normalized_fact']['runtime_equivalence_proved'] is False
    assert by_category['broadcast']['normalized_fact']['source_models'] == [
        'payload_lifecycle',
        'xrpl_transaction',
    ]


def test_xaman_runtime_trace_absent_real_device_bundle_is_blocking() -> None:
    report = build_report(repo_root=REPO_ROOT, generated_at_utc='2026-07-10T00:00:00Z')

    blockers = {blocker['code']: blocker for blocker in report['blocking_gaps']}
    assert 'REAL_DEVICE_TRACE_BUNDLE_MISSING' in blockers
    assert 'RUNTIME_EQUIVALENCE_NOT_PROVED' in blockers
    assert blockers['REAL_DEVICE_TRACE_BUNDLE_MISSING']['required_categories'] == REQUIRED_MONITOR_CATEGORIES
    assert report['runtime_trace_bundle']['trace_file_count'] == 0
    assert report['runtime_trace_bundle']['event_count'] == 0


def test_xaman_runtime_trace_reads_duckdb_firebase_mock_as_supplemental_telemetry(tmp_path: Path) -> None:
    database = tmp_path / 'firebase-mock.duckdb'
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            '''
            CREATE TABLE xaman_firebase_mock_runs (
                run_id VARCHAR, started_at_utc VARCHAR, last_event_at_utc VARCHAR,
                xaman_commit VARCHAR, build_provenance_sha256 VARCHAR,
                ledger_network VARCHAR, ledger_endpoint VARCHAR, firebase_mode VARCHAR,
                accepted_event_count BIGINT, rejected_event_count BIGINT
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE xaman_firebase_mock_events (
                run_id VARCHAR, ordinal BIGINT, received_at_utc VARCHAR, timestamp_utc VARCHAR,
                category VARCHAR, event_name VARCHAR, outcome VARCHAR, attributes_json VARCHAR,
                request_sha256 VARCHAR
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE xaman_firebase_mock_rejections (
                run_id VARCHAR, ordinal BIGINT, received_at_utc VARCHAR, reason_code VARCHAR,
                request_sha256 VARCHAR
            )
            '''
        )
        connection.execute(
            'INSERT INTO xaman_firebase_mock_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                'testnet-runtime-mock-01',
                '2026-07-10T00:00:00Z',
                '2026-07-10T00:00:01Z',
                '942f43876265a7af44f233288ad2b1d00841d5fa',
                'a' * 64,
                'testnet',
                'wss://s.altnet.rippletest.net:51233',
                'disabled_with_duckdb_firebase_mock',
                1,
                0,
            ],
        )
        connection.execute(
            'INSERT INTO xaman_firebase_mock_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                'testnet-runtime-mock-01',
                1,
                '2026-07-10T00:00:01Z',
                '2026-07-10T00:00:01Z',
                'firebase_disabled',
                'firebase_analytics_operation',
                'stubbed',
                '{"arg_count":1,"operation":"logScreenView"}',
                'b' * 64,
            ],
        )
    finally:
        connection.close()

    report = XamanRuntimeTraceIngestor().ingest(
        repo_root=REPO_ROOT,
        firebase_mock_database_path=database,
        firebase_mock_run_id='testnet-runtime-mock-01',
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['firebase_mock']['status'] == 'loaded'
    assert report['firebase_mock']['event_count'] == 1
    assert report['firebase_mock']['rejected_event_count'] == 0
    assert report['firebase_mock']['event_type_counts'] == [
        {
            'category': 'firebase_disabled',
            'event_name': 'firebase_analytics_operation',
            'outcome': 'stubbed',
            'count': 1,
        }
    ]
    facts = {fact['category']: fact for fact in report['monitor_facts']}
    assert facts['firebase_mock']['status'] == 'SUPPLEMENTAL_REDACTED_TELEMETRY'
    assert facts['firebase_mock']['normalized_fact']['wallet_or_xrpl_events_inferred'] is False
    blockers = {blocker['code'] for blocker in report['blocking_gaps']}
    assert 'REAL_DEVICE_TRACE_BUNDLE_MISSING' in blockers
    assert 'RUNTIME_EQUIVALENCE_NOT_PROVED' in blockers


def test_xaman_runtime_trace_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / 'runtime-trace-report.json'
    rc = main(['--out', str(out)])

    assert rc == 0
    written = _load_json(out)
    assert written['schema_version'] == 'xaman-runtime-trace-report/v1'
    assert written['overall_status'] == 'blocked'
    assert written['monitor_facts']


def test_xaman_runtime_trace_document_covers_artifact_and_blockers() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-074' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json' in doc
    assert 'REAL_DEVICE_TRACE_BUNDLE_MISSING' in doc
    assert 'RUNTIME_EQUIVALENCE_NOT_PROVED' in doc
    assert 'NOT_MODELED' in doc

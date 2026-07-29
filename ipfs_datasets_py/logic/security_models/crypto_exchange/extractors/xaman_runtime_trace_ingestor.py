"""Xaman e2e/runtime trace ingestor.

The checked-in Xaman corpus is manifest-pinned, while real device traces may be
absent in CI.  This ingestor converts available e2e feature inventory and
reviewed source-model artifacts into monitor facts, then fails closed until a
real runtime trace bundle is supplied.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 'xaman-runtime-trace-report/v1'
TASK_ID = 'PORTAL-CXTP-074'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
DEFAULT_MANIFEST_PATH = Path('security_ir_artifacts/corpora/xaman-app/source-manifest.json')
DEFAULT_ENVIRONMENT_PROBE_PATH = Path('security_ir_artifacts/corpora/xaman-app/environment-probe.json')
DEFAULT_PAYLOAD_FACTS_PATH = Path('security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json')
DEFAULT_XRPL_FACTS_PATH = Path('security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json')
DEFAULT_WALLET_FACTS_PATH = Path('security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json')
DEFAULT_OUT_PATH = Path('security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json')
POLICY_DOCUMENT = 'docs/security_verification/xaman_runtime_trace_assumptions.md'

E2E_FEATURE_CATEGORIES: dict[str, list[str]] = {
    'e2e/01_setup.feature': ['runtime_setup'],
    'e2e/02_generate_account.feature': ['auth', 'signing'],
    'e2e/03_import_account.feature': ['auth', 'signing'],
    'e2e/04_upgrade_account.feature': ['auth'],
    'e2e/05_auth.feature': ['auth'],
    'e2e/06_linking.feature': ['payload_intake', 'network_binding'],
}

REQUIRED_MONITOR_CATEGORIES = [
    'payload_intake',
    'review',
    'auth',
    'signing',
    'rejection',
    'expiration',
    'network_binding',
    'broadcast',
    'runtime_equivalence',
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _sha256_json(payload: Mapping[str, Any]) -> str:
    stable = {key: value for key, value in payload.items() if key != 'artifact_cid'}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    return 'sha256:' + _sha256_json(payload)


def _resolve(root: Path, path: Path | str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _manifest_files(manifest: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    files = manifest.get('files') if isinstance(manifest, Mapping) else None
    if not isinstance(files, list):
        return {}
    return {
        str(entry['path']): entry
        for entry in files
        if isinstance(entry, Mapping) and isinstance(entry.get('path'), str)
    }


def _artifact_summary(path: Path, artifact: Mapping[str, Any] | None, root: Path) -> dict[str, Any]:
    if artifact is None:
        return {
            'path': _relative(root, path),
            'exists': path.is_file(),
            'schema_version': None,
            'review_status': None,
            'modeled_fact_count': 0,
            'gap_count': 0,
            'status': 'missing',
        }
    facts = artifact.get('modeled_facts')
    gaps = artifact.get('not_modeled_gaps')
    review = artifact.get('review') if isinstance(artifact.get('review'), Mapping) else {}
    return {
        'path': _relative(root, path),
        'exists': True,
        'schema_version': artifact.get('schema_version'),
        'review_status': review.get('review_status'),
        'modeled_fact_count': len(facts) if isinstance(facts, list) else 0,
        'gap_count': len(gaps) if isinstance(gaps, list) else 0,
        'status': 'ready' if review.get('review_status') == 'reviewed' else 'unreviewed',
    }


def _evidence_source_model(path: Path, root: Path, artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        'kind': 'source_model_artifact',
        'path': _relative(root, path),
        'schema_version': artifact.get('schema_version') if isinstance(artifact, Mapping) else None,
        'review_status': (
            artifact.get('review', {}).get('review_status')
            if isinstance(artifact, Mapping) and isinstance(artifact.get('review'), Mapping)
            else None
        ),
    }


def _evidence_manifest_file(path: str, files: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    entry = files[path]
    return {
        'kind': 'source_manifest_file',
        'path': path,
        'sha256': entry.get('sha256'),
        'size_bytes': entry.get('size_bytes'),
        'review_status': 'reviewed',
    }


def _runtime_trace_files(trace_dir: Path | None) -> list[Path]:
    if trace_dir is None or not trace_dir.is_dir():
        return []
    return sorted(
        path
        for path in trace_dir.rglob('*')
        if path.is_file() and path.suffix.lower() in {'.json', '.jsonl', '.ndjson'}
    )


def _iter_runtime_events(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in {'.jsonl', '.ndjson'}:
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value
        return
    payload = _read_json(path)
    if payload is None:
        return
    events = payload.get('events')
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                yield event
    elif isinstance(payload.get('category'), str) or isinstance(payload.get('event'), str):
        yield payload


def _runtime_event_summary(trace_files: list[Path], root: Path) -> dict[str, Any]:
    event_count = 0
    category_counts: dict[str, int] = {}
    files: list[dict[str, Any]] = []
    for trace_file in trace_files:
        file_event_count = 0
        for event in _iter_runtime_events(trace_file):
            file_event_count += 1
            category = str(event.get('category') or event.get('monitor_category') or event.get('event') or 'unknown')
            category_counts[category] = category_counts.get(category, 0) + 1
        event_count += file_event_count
        files.append(
            {
                'path': _relative(root, trace_file),
                'sha256': hashlib.sha256(trace_file.read_bytes()).hexdigest(),
                'event_count': file_event_count,
            }
        )
    return {
        'trace_file_count': len(trace_files),
        'event_count': event_count,
        'category_counts': category_counts,
        'files': files,
    }


def _monitor_fact(
    *,
    fact_id: str,
    category: str,
    status: str,
    summary: str,
    evidence: list[dict[str, Any]],
    normalized_fact: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        'id': fact_id,
        'category': category,
        'status': status,
        'summary': summary,
        'evidence': evidence,
        'normalized_fact': dict(normalized_fact),
    }


def build_report(
    *,
    repo_root: Path | str | None = None,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    environment_probe_path: Path | str = DEFAULT_ENVIRONMENT_PROBE_PATH,
    payload_facts_path: Path | str = DEFAULT_PAYLOAD_FACTS_PATH,
    xrpl_facts_path: Path | str = DEFAULT_XRPL_FACTS_PATH,
    wallet_facts_path: Path | str = DEFAULT_WALLET_FACTS_PATH,
    trace_dir: Path | str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    manifest_abs = _resolve(root, manifest_path)
    environment_abs = _resolve(root, environment_probe_path)
    payload_abs = _resolve(root, payload_facts_path)
    xrpl_abs = _resolve(root, xrpl_facts_path)
    wallet_abs = _resolve(root, wallet_facts_path)
    trace_abs = _resolve(root, trace_dir) if trace_dir is not None else None

    manifest = _read_json(manifest_abs)
    environment = _read_json(environment_abs)
    payload_facts = _read_json(payload_abs)
    xrpl_facts = _read_json(xrpl_abs)
    wallet_facts = _read_json(wallet_abs)
    files = _manifest_files(manifest)
    trace_files = _runtime_trace_files(trace_abs)
    trace_summary = _runtime_event_summary(trace_files, root)

    e2e_features = [
        {
            'path': path,
            'sha256': files[path].get('sha256'),
            'size_bytes': files[path].get('size_bytes'),
            'categories': categories,
            'review_status': 'reviewed',
        }
        for path, categories in sorted(E2E_FEATURE_CATEGORIES.items())
        if path in files
    ]

    source_models = {
        'payload_lifecycle': _artifact_summary(payload_abs, payload_facts, root),
        'xrpl_transaction': _artifact_summary(xrpl_abs, xrpl_facts, root),
        'wallet_auth': _artifact_summary(wallet_abs, wallet_facts, root),
    }

    env_evidence = {
        'kind': 'environment_probe',
        'path': _relative(root, environment_abs),
        'schema_version': environment.get('schema_version') if isinstance(environment, Mapping) else None,
        'overall_status': environment.get('overall_status') if isinstance(environment, Mapping) else None,
        'review_status': 'reviewed' if environment is not None else 'missing',
    }
    payload_evidence = _evidence_source_model(payload_abs, root, payload_facts)
    xrpl_evidence = _evidence_source_model(xrpl_abs, root, xrpl_facts)
    wallet_evidence = _evidence_source_model(wallet_abs, root, wallet_facts)

    monitor_facts = [
        _monitor_fact(
            fact_id='xaman-runtime:monitor:payload-intake-routes-to-review',
            category='payload_intake',
            status='MODELED_FROM_E2E_AND_SOURCE',
            summary='E2E linking coverage and payload lifecycle facts provide monitor hooks for payload intake into review.',
            evidence=[_evidence_manifest_file('e2e/06_linking.feature', files), payload_evidence],
            normalized_fact={
                'expected_events': ['link_opened', 'payload_reference_detected', 'review_modal_opened'],
                'source_model': 'payload_lifecycle',
                'real_device_trace_required': False,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:review-ui-is-source-modeled',
            category='review',
            status='MODELED_FROM_SOURCE',
            summary='Payload lifecycle facts model review preflight, review UI display, and accept-control boundaries.',
            evidence=[payload_evidence],
            normalized_fact={
                'expected_events': ['review_preflight_started', 'review_displayed', 'accept_control_ready'],
                'source_model': 'payload_lifecycle',
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:auth-flows-have-e2e-and-wallet-model-hooks',
            category='auth',
            status='MODELED_FROM_E2E_AND_SOURCE',
            summary='Authentication e2e features and wallet-auth source facts provide monitor hooks for account setup, import, upgrade, and auth overlays.',
            evidence=[
                _evidence_manifest_file('e2e/02_generate_account.feature', files),
                _evidence_manifest_file('e2e/03_import_account.feature', files),
                _evidence_manifest_file('e2e/05_auth.feature', files),
                wallet_evidence,
            ],
            normalized_fact={
                'expected_events': ['auth_prompt_opened', 'passcode_or_biometric_accepted', 'vault_overlay_opened'],
                'source_model': 'wallet_auth',
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:signing-has-wallet-payload-and-xrpl-hooks',
            category='signing',
            status='MODELED_FROM_E2E_AND_SOURCE',
            summary='Signing monitor facts bind wallet custody, payload approval, and XRPL signing preconditions.',
            evidence=[
                _evidence_manifest_file('e2e/02_generate_account.feature', files),
                wallet_evidence,
                payload_evidence,
                xrpl_evidence,
            ],
            normalized_fact={
                'expected_events': ['payload_approved', 'vault_signed', 'signed_blob_created'],
                'source_models': ['wallet_auth', 'payload_lifecycle', 'xrpl_transaction'],
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:rejection-and-expiration-are-source-modeled',
            category='rejection',
            status='MODELED_FROM_SOURCE',
            summary='Payload lifecycle facts model rejection patching plus resolved and expired payload blocking.',
            evidence=[payload_evidence],
            normalized_fact={
                'expected_events': ['payload_declined', 'backend_rejection_patched', 'expired_payload_blocked'],
                'expiration_category_also_covered': True,
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:expiration-replay-controls-are-source-modeled',
            category='expiration',
            status='MODELED_FROM_SOURCE',
            summary='Payload lifecycle facts model digest checks, resolved-at checks, expired meta checks, and pre-sign revalidation.',
            evidence=[payload_evidence],
            normalized_fact={
                'expected_events': ['digest_checked', 'resolved_or_expired_blocked', 'pre_sign_revalidation'],
                'source_model': 'payload_lifecycle',
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:network-binding-has-linking-payload-and-xrpl-hooks',
            category='network_binding',
            status='MODELED_FROM_E2E_AND_SOURCE',
            summary='Linking e2e coverage plus payload and XRPL transaction facts model network binding checks before signing.',
            evidence=[_evidence_manifest_file('e2e/06_linking.feature', files), payload_evidence, xrpl_evidence],
            normalized_fact={
                'expected_events': ['network_checked', 'force_network_matched', 'unsupported_type_rejected'],
                'source_models': ['payload_lifecycle', 'xrpl_transaction'],
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:broadcast-boundary-is-source-modeled',
            category='broadcast',
            status='MODELED_FROM_SOURCE',
            summary='Payload and XRPL transaction facts model signed payload patching and optional submit of a signed blob.',
            evidence=[payload_evidence, xrpl_evidence],
            normalized_fact={
                'expected_events': ['signed_payload_patched', 'submit_attempted', 'dispatch_result_patched'],
                'source_models': ['payload_lifecycle', 'xrpl_transaction'],
                'real_device_trace_required': True,
            },
        ),
        _monitor_fact(
            fact_id='xaman-runtime:monitor:real-device-runtime-equivalence-is-absent',
            category='runtime_equivalence',
            status='BLOCKED',
            summary='No real-device runtime trace bundle is present, so source and e2e-derived monitor facts cannot prove deployed runtime equivalence.',
            evidence=[
                {
                    'kind': 'runtime_trace_bundle',
                    'path': _relative(root, trace_abs) if trace_abs is not None else None,
                    'exists': bool(trace_abs and trace_abs.is_dir()),
                    'trace_file_count': trace_summary['trace_file_count'],
                    'review_status': 'missing' if trace_summary['trace_file_count'] == 0 else 'provided',
                },
                env_evidence,
            ],
            normalized_fact={
                'real_device_trace_required': True,
                'trace_file_count': trace_summary['trace_file_count'],
                'runtime_equivalence_proved': False,
            },
        ),
    ]

    blockers: list[dict[str, Any]] = []
    if manifest is None:
        blockers.append({'code': 'XAMAN_SOURCE_MANIFEST_MISSING', 'path': _relative(root, manifest_abs)})
    else:
        source = manifest.get('source') if isinstance(manifest.get('source'), Mapping) else {}
        if source.get('commit_sha') != PINNED_XAMAN_COMMIT:
            blockers.append(
                {
                    'code': 'XAMAN_SOURCE_COMMIT_MISMATCH',
                    'expected': PINNED_XAMAN_COMMIT,
                    'actual': source.get('commit_sha'),
                }
            )
    for name, summary in source_models.items():
        if summary['status'] != 'ready':
            blockers.append({'code': 'REVIEWED_SOURCE_MODEL_MISSING', 'source_model': name, 'path': summary['path']})
    missing_e2e = [path for path in E2E_FEATURE_CATEGORIES if path not in files]
    if missing_e2e:
        blockers.append({'code': 'E2E_FEATURES_MISSING_FROM_MANIFEST', 'paths': missing_e2e})
    if trace_summary['trace_file_count'] == 0 or trace_summary['event_count'] == 0:
        blockers.append(
            {
                'code': 'REAL_DEVICE_TRACE_BUNDLE_MISSING',
                'path': _relative(root, trace_abs) if trace_abs is not None else None,
                'required_categories': REQUIRED_MONITOR_CATEGORIES,
            }
        )
        blockers.append(
            {
                'code': 'RUNTIME_EQUIVALENCE_NOT_PROVED',
                'reason': 'Source and e2e feature facts are monitor specifications, not deployed-device execution evidence.',
            }
        )

    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'source': {
            'repo_url': manifest.get('source', {}).get('repo_url') if isinstance(manifest, Mapping) else None,
            'commit_sha': manifest.get('source', {}).get('commit_sha') if isinstance(manifest, Mapping) else None,
            'manifest_path': _relative(root, manifest_abs),
            'manifest_schema_version': manifest.get('schema_version') if isinstance(manifest, Mapping) else None,
            'manifest_aggregate_sha256': (
                manifest.get('reproducibility', {}).get('aggregate_sha256') if isinstance(manifest, Mapping) else None
            ),
        },
        'environment_probe': env_evidence,
        'source_models': source_models,
        'e2e_features': e2e_features,
        'runtime_trace_bundle': {
            'path': _relative(root, trace_abs) if trace_abs is not None else None,
            'provided': trace_abs is not None,
            **trace_summary,
        },
        'monitor_facts': monitor_facts,
        'blocking_gaps': blockers,
        'blocker_count': len(blockers),
        'overall_status': 'blocked' if blockers else 'ready',
        'production_release_blocked': bool(blockers),
        'security_decision': (
            'BLOCK_RUNTIME_EQUIVALENCE_MISSING_REAL_DEVICE_TRACES'
            if blockers
            else 'RUNTIME_TRACE_MONITORS_READY'
        ),
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build Xaman runtime trace monitor report.')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument('--environment-probe', default=str(DEFAULT_ENVIRONMENT_PROBE_PATH))
    parser.add_argument('--payload-facts', default=str(DEFAULT_PAYLOAD_FACTS_PATH))
    parser.add_argument('--xrpl-facts', default=str(DEFAULT_XRPL_FACTS_PATH))
    parser.add_argument('--wallet-facts', default=str(DEFAULT_WALLET_FACTS_PATH))
    parser.add_argument('--trace-dir')
    parser.add_argument('--out', default=str(DEFAULT_OUT_PATH))
    args = parser.parse_args(argv)

    root = _repo_root()
    report = build_report(
        repo_root=root,
        manifest_path=args.manifest,
        environment_probe_path=args.environment_probe,
        payload_facts_path=args.payload_facts,
        xrpl_facts_path=args.xrpl_facts,
        wallet_facts_path=args.wallet_facts,
        trace_dir=args.trace_dir,
    )
    _write_json(report, _resolve(root, args.out))
    print(
        json.dumps(
            {
                'overall_status': report['overall_status'],
                'blocker_count': report['blocker_count'],
                'monitor_fact_count': len(report['monitor_facts']),
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

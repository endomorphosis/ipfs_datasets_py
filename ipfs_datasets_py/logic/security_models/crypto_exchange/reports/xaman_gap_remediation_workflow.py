"""Build a deterministic execution manifest for gap-remediation obligations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from json import JSONDecodeError
from typing import Any, Iterable, Mapping

from ..ir.cid import calculate_artifact_cid


SCHEMA_VERSION = 'xaman-gap-remediation-workflow-manifest/v1'
TASK_ID = 'PORTAL-CXTP-172'
MODULE_ROOT = Path(__file__).resolve().parents[5]
VENDOR_EVIDENCE_MANIFEST_PATH = (
    MODULE_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'vendor-evidence-manifest.json'
)
VENDOR_EVIDENCE_REVIEW_PATH = (
    MODULE_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'vendor-evidence-review.json'
)
SELF_HOSTED_RUNTIME_CONFORMANCE_REPORT = (
    MODULE_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'self-hosted-testnet' / 'runtime-conformance-report.json'
)
RUNTIME_TRACE_REVIEW_REPORT = (
    MODULE_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'self-hosted-testnet' / 'runtime-trace-review.json'
)
NATIVE_VAULT_REKEY_REPORT = (
    MODULE_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'runtime' / 'native-vault-rekey-fault-injection-report.json'
)
IOS_HOST_PREFLIGHT_REPORT = (
    MODULE_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'runtime' / 'native-vault-ios-host-preflight.json'
)

RUNTIME_ACTIONS_BY_UNMODELED_ENTRY: Mapping[str, set[str]] = {
    'attack-cancel-after-submit-race': {'cancellation'},
    'attack-cancel-gap-promoted': {'cancellation'},
    'attack-decline-gap-promoted': {'reconnect', 'cancellation'},
    'attack-expiry-after-auth-race': {'expiry'},
    'attack-expiry-gap-promoted': {'expiry'},
    'attack-reconnect-before-submit-result-race': {'reconnect'},
    'attack-replay-duplicate-resolution': {'replay'},
    'attack-replay-duplicate-submit-result': {'replay'},
    'attack-submit-result-removed': {'submit_result'},
}

BLOCKED_CLASSIFICATIONS = {
    'EXTERNAL_EVIDENCE_REQUIRED',
    'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS',
}

EXTERNAL_EVIDENCE_ACTIONS_BY_CLAIM: Mapping[str, list[str]] = {
    'xaman-claim:backend-payload-service-is-trusted-not-proved': [
        'Obtain or produce reviewed backend payload-service evidence that binds payload issuance, single-use controls, replay rejection, audit logging, and owner signoff to the tested release.',
        'If vendor backend evidence is unavailable, keep this claim blocked and limit conclusions to public-source/Testnet scope.',
    ],
    'xaman-claim:runtime-equivalence-is-blocked-without-device-traces': [
        'Capture reviewed device runtime traces for the release-equivalent wallet path, including network binding, payload review, authentication, signing decision, submit attempt, submit result, cancellation, expiry, replay, and reconnect categories.',
        'If release-equivalent runtime evidence is unavailable, keep this claim blocked and do not promote self-hosted or emulator traces to production equivalence.',
    ],
}


def _sorted_unique(values: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    ordered.sort()
    return ordered


def _read_json_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload_text = path.read_text(encoding='utf-8')
    except OSError:
        return None
    try:
        payload = json.loads(payload_text)
    except JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _to_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    normalized: set[str] = set()
    for item in value:
        if isinstance(item, str):
            normalized.add(item)
    return normalized


def _runtime_evidence_is_ready() -> bool:
    runtime_report = _read_json_payload(SELF_HOSTED_RUNTIME_CONFORMANCE_REPORT)
    if not isinstance(runtime_report, Mapping):
        return False
    if runtime_report.get('overall_status') != 'reviewed_self_hosted_verifier_trace':
        return False
    scope = runtime_report.get('scope')
    if not isinstance(scope, Mapping) or scope.get('vendor_release_equivalent') is True:
        return False
    review_gate = runtime_report.get('review_gate')
    if not isinstance(review_gate, Mapping) or review_gate.get('status') != 'passed':
        return False
    return True


def _runtime_entries_are_covered(entry_id: str) -> bool:
    required_actions = RUNTIME_ACTIONS_BY_UNMODELED_ENTRY.get(entry_id)
    if not required_actions:
        return False
    trace_report = _read_json_payload(RUNTIME_TRACE_REVIEW_REPORT)
    if not isinstance(trace_report, Mapping):
        return False
    covered = set()
    lifecycle_events = trace_report.get('lifecycle_events')
    if isinstance(lifecycle_events, list):
        covered = {
            event.get('action')
            for event in lifecycle_events
            if isinstance(event, Mapping) and isinstance(event.get('action'), str)
        }
    if not covered:
        covered = _to_set(trace_report.get('covered_actions'))
    if not covered:
        return False
    if not required_actions.issubset(covered):
        return False
    return True


def _fault_injection_evidence_is_ready() -> bool:
    fault_report = _read_json_payload(NATIVE_VAULT_REKEY_REPORT)
    if not isinstance(fault_report, Mapping):
        return False
    review_gate = fault_report.get('review_gate')
    if not isinstance(review_gate, Mapping):
        return False
    decision = str(review_gate.get('decision', '')).lower()
    return decision == 'allow_verifier_only_runtime_capture'


def _ios_preflight_evidence_is_ready() -> bool:
    ios_preflight = _read_json_payload(IOS_HOST_PREFLIGHT_REPORT)
    if not isinstance(ios_preflight, Mapping):
        return False
    decision = str(ios_preflight.get('security_decision', ''))
    return (
        decision.startswith('IOS_NATIVE_VAULT_HOST_PREPARED')
        or decision == 'IOS_NATIVE_VAULT_HOST_PREPARED_BLOCKED_NON_DARWIN'
    )


def _runtime_blockers_cleared(entry_id: str) -> bool:
    if not _runtime_evidence_is_ready():
        return False
    if not _runtime_entries_are_covered(entry_id):
        return False
    if not _fault_injection_evidence_is_ready():
        return False
    if not _ios_preflight_evidence_is_ready():
        return False
    return True


def _vendor_evidence_clears_claim(claim_id: str, *, now: datetime | None = None) -> bool:
    """Return whether external vendor evidence currently clears a required claim."""

    try:
        from .xaman_vendor_evidence import load_json, review_clears_external_claim

        manifest = load_json(VENDOR_EVIDENCE_MANIFEST_PATH)
        review = load_json(VENDOR_EVIDENCE_REVIEW_PATH)
        return review_clears_external_claim(manifest=manifest, review=review, claim_id=claim_id, now=now)
    except Exception:
        return False


def _index_disproof_report(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    results = payload.get('results')
    if not isinstance(results, list):
        return {}
    index: dict[str, Mapping[str, Any]] = {}
    for item in results:
        if isinstance(item, Mapping):
            vector_id = str(item.get('vector_id'))
            if vector_id:
                index[vector_id] = item
    return index


def _index_fuzz_counterexamples(counterexample_manifest: Mapping[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in counterexample_manifest.get('counterexamples', []) if isinstance(counterexample_manifest.get('counterexamples'), list) else []:
        if not isinstance(path, str):
            continue
        file_name = path.rsplit('/', 1)[-1]
        mutation_id = file_name.removesuffix('.json')
        index[mutation_id] = path
        stripped_attack_id = mutation_id.removeprefix('attack-')
        if stripped_attack_id != mutation_id:
            index[stripped_attack_id] = path
    return index


def _index_vault_conditions(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    conditions = payload.get('source_supported_conditions')
    if not isinstance(conditions, list):
        return {}
    index: dict[str, Mapping[str, Any]] = {}
    for item in conditions:
        if isinstance(item, Mapping):
            condition_id = str(item.get('id'))
            if condition_id:
                index[condition_id] = item
    return index


def _fallback_next_actions(entry: Mapping[str, Any], blockers: list[str]) -> list[str]:
    actions = [str(action) for action in entry.get('next_actions', []) if isinstance(action, str) and action]
    claim_id = str(entry.get('claim_id') or '')
    if 'EXTERNAL_EVIDENCE_REQUIRED' in blockers and claim_id in EXTERNAL_EVIDENCE_ACTIONS_BY_CLAIM:
        return _sorted_unique([*EXTERNAL_EVIDENCE_ACTIONS_BY_CLAIM[claim_id], *actions])
    return actions


def _classify_gap_entry(
    matrix_entry: Mapping[str, Any],
    *,
    disproof_index: Mapping[str, Mapping[str, Any]],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_paths: Mapping[str, str],
    vault_condition_index: Mapping[str, Mapping[str, Any]],
    now: datetime | None = None,
) -> tuple[dict[str, str], dict[str, Any], list[str]]:
    entry_id = str(matrix_entry.get('entry_id') or '')
    origin = str(matrix_entry.get('origin') or 'unknown')
    classification = str(matrix_entry.get('classification') or 'UNCLASSIFIED')
    claim_id = matrix_entry.get('claim_id')

    blockers: list[str] = []
    evidence: dict[str, Any] = {}

    if classification in BLOCKED_CLASSIFICATIONS:
        if classification == 'EXTERNAL_EVIDENCE_REQUIRED':
            if not _vendor_evidence_clears_claim(str(claim_id), now=now):
                blockers.append(classification)
        elif classification != 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS' or not _runtime_blockers_cleared(entry_id):
            blockers.append(classification)

    if origin == 'disproof_vector':
        result = disproof_index.get(entry_id)
        if result is None:
            blockers.append('counterexample_report_entry_missing')
        else:
            evidence = {
                'result': result.get('result'),
                'claim_id': result.get('claim_id'),
                'release_policy': result.get('release_policy'),
            }
    elif origin == 'fuzz_mutation':
        for mutation in fuzz_report.get('attack_mutations', []) if isinstance(fuzz_report.get('attack_mutations'), list) else []:
            if isinstance(mutation, Mapping) and str(mutation.get('mutation_id')) == entry_id:
                evidence = {
                    'mutation_target_claim_id': mutation.get('target_claim_id'),
                    'result': mutation.get('result'),
                    'target_claim_trigger_count': mutation.get('target_claim_trigger_count'),
                    'fuzz_domain': mutation.get('fuzz_domain'),
                }
                break
        if not evidence:
            blockers.append('fuzz_mutation_report_entry_missing')
        if entry_id in fuzz_counterexample_paths:
            evidence['counterexample_path'] = fuzz_counterexample_paths[entry_id]
        else:
            blockers.append('fuzz_counterexample_payload_missing')
    elif origin == 'native_vault_state_fuzz':
        condition = vault_condition_index.get(entry_id)
        if condition is None:
            blockers.append('native_vault_state_condition_missing')
        else:
            evidence = {
                'summary': condition.get('summary'),
                'summary_count': condition.get('summary_count'),
                'observed': condition.get('observed'),
                'result': condition.get('result'),
            }
    else:
        blockers.append('unsupported_gap_entry_origin')

    return {
        'entry_id': entry_id,
        'classification': classification,
        'origin': origin,
        'claim_id': claim_id,
    }, evidence, blockers


def build_gap_remediation_execution_manifest(
    *,
    gap_remediation_matrix: Mapping[str, Any],
    counterexample_report: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
    native_vault_state_fuzz: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    reference_time = now or datetime.now(timezone.utc)
    disproof_index = _index_disproof_report(counterexample_report)
    fuzz_counterexample_paths = _index_fuzz_counterexamples(fuzz_counterexample_manifest)
    vault_condition_index = _index_vault_conditions(native_vault_state_fuzz)

    entries: list[dict[str, Any]] = []
    ready_disproofs: list[str] = []
    ready_mutations: list[str] = []
    ready_conditions: list[str] = []
    blocked_mutations: list[str] = []
    blocked_conditions: list[str] = []
    blocked_vectors: list[str] = []

    matrix_entries = gap_remediation_matrix.get('matrix', [])
    if not isinstance(matrix_entries, list):
        raise ValueError('gap-remediation matrix has no matrix array')

    for item in matrix_entries:
        if not isinstance(item, Mapping):
            continue

        entry, evidence, blockers = _classify_gap_entry(
            item,
            disproof_index=disproof_index,
            fuzz_report=fuzz_report,
            fuzz_counterexample_paths=fuzz_counterexample_paths,
            vault_condition_index=vault_condition_index,
            now=reference_time,
        )
        execution_blockers = _sorted_unique(blockers)
        entry_id = entry.get('entry_id', '')
        origin = str(item.get('origin') or '')
        execution_state = 'blocked' if execution_blockers else 'ready'

        if execution_state == 'ready':
            if origin == 'disproof_vector':
                ready_disproofs.append(entry_id)
            elif origin == 'fuzz_mutation':
                ready_mutations.append(entry_id)
            elif origin == 'native_vault_state_fuzz':
                ready_conditions.append(entry_id)
        else:
            if origin == 'disproof_vector':
                blocked_vectors.append(entry_id)
            elif origin == 'fuzz_mutation':
                blocked_mutations.append(entry_id)
            elif origin == 'native_vault_state_fuzz':
                blocked_conditions.append(entry_id)

        if execution_blockers:
            entry['blocked_by'] = execution_blockers

        entry['execution_state'] = execution_state
        entry['evidence'] = evidence
        entry['priority'] = item.get('priority')
        entry['next_task_ids'] = list(item.get('next_task_ids', []))
        entry['next_actions'] = _fallback_next_actions(item, execution_blockers)
        entry['source_supported_tx_class'] = item.get('source_supported_tx_class')
        entries.append(entry)

    entries_sorted = sorted(entries, key=lambda item: (str(item['classification']), int(item['priority']) if isinstance(item.get('priority'), int) else 999, str(item['entry_id'])))

    classification_counts = Counter(str(entry['classification']) for entry in entries_sorted)
    blocked_classifications = _sorted_unique(
        str(item.get('classification'))
        for item in entries_sorted
        if item.get('execution_state') == 'blocked'
    )
    summary = {
        'entry_count': len(entries_sorted),
        'ready_count': sum(1 for entry in entries_sorted if entry['execution_state'] == 'ready'),
        'blocked_count': sum(1 for entry in entries_sorted if entry['execution_state'] == 'blocked'),
        'required_task_count': len({task for entry in entries_sorted for task in entry.get('next_task_ids', []) if isinstance(entry.get('next_task_ids'), list)}),
        'classification_counts': dict(sorted((str(k), v) for k, v in classification_counts.items())),
        'ready_disproof_vector_count': len(ready_disproofs),
        'ready_fuzz_mutation_count': len(ready_mutations),
        'ready_native_vault_condition_count': len(ready_conditions),
        'blocked_classification_count': len(blocked_classifications),
    }

    required_task_ids = _sorted_unique(str(task_id) for task_id in gap_remediation_matrix.get('required_task_ids', []) if task_id)
    required_by_classification = {
        classification: _sorted_unique(
            item['entry_id']
            for item in entries_sorted
            if item.get('classification') == classification and item.get('entry_id')
        )
        for classification in sorted(classification_counts)
    }

    manifest = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_from_task_id': gap_remediation_matrix.get('task_id', 'PORTAL-CXTP-170'),
        'source_gap_matrix_path': 'security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json',
        'execution_mode': 'prioritized_source_bounded_remediation',
        'matrix_task_count': gap_remediation_matrix.get('matrix_task_count'),
        'required_task_ids': required_task_ids,
        'overall_status': 'blocked_by_gap_remediation_dependencies' if summary['blocked_count'] else 'ready_for_follow_on_execution',
        'production_release_blocked': True,
        'security_decision': 'GAP_REMEDIATION_WORKFLOW_MANIFEST_GENERATED',
        'summary': summary,
        'blocked_classifications': blocked_classifications,
        'required_by_classification': required_by_classification,
        'entries': entries_sorted,
        'execution_manifest': {
            'disproof_vectors': {
                'ready': _sorted_unique(ready_disproofs),
                'blocked': _sorted_unique(blocked_vectors),
            },
            'fuzz_mutation_ids': {
                'ready': _sorted_unique(ready_mutations),
                'blocked': _sorted_unique(blocked_mutations),
            },
            'native_vault_state_conditions': {
                'ready': _sorted_unique(ready_conditions),
                'blocked': _sorted_unique(blocked_conditions),
            },
            'required_next_lanes': {
                'proof_counterexample': _sorted_unique(ready_disproofs + blocked_vectors),
                'fuzz_mutation_campaign': _sorted_unique(ready_mutations + blocked_mutations),
                'native_vault_runtime': _sorted_unique(ready_conditions + blocked_conditions),
            },
            'blocked_by_evidence_lanes': blocked_classifications,
        },
    }
    manifest['artifact_cid'] = calculate_artifact_cid({key: value for key, value in manifest.items() if key != 'artifact_cid'})
    return manifest

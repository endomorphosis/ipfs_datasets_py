#!/usr/bin/env python3
"""Probe the Leanstral proof-assistant lane.

PORTAL-CXTP-097 wires Leanstral into the crypto_exchange/Xaman theorem-prover
workflow as advisory proof engineering assistance only. The model may suggest
Lean proof edits, but proof authority remains the local Lean/Lake compile check
and the production evidence gates.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-leanstral-proof-assistant-report/v1'
TASK_ID = 'PORTAL-CXTP-097'
DEFAULT_OUT = Path('security_ir_artifacts/environment/leanstral-proof-assistant-report.json')
DEFAULT_LEAN_REPORT = Path('security_ir_artifacts/environment/lean-solver-lane-report.json')
PROOF_KERNEL_PATH = Path('security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean')
PROOF_CONSUMER_REPORT_PATH = Path(
    'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
)
POLICY_DOCUMENT = 'docs/security_verification/leanstral_proof_assistant_lane.md'

APPROVED_MODEL_ROUTES = ('labs-leanstral-1-5', 'labs-leanstral-2603')
MODEL_ENV_VARS = (
    'IPFS_DATASETS_PY_LEANSTRAL_MODEL',
    'IPFS_DATASETS_PY_OPENAI_MODEL',
    'IPFS_DATASETS_PY_OPENROUTER_MODEL',
    'IPFS_DATASETS_PY_LLM_MODEL',
    'IPFS_DATASETS_PY_HF_INFERENCE_MODEL',
)
PROVIDER_ENV_VARS = (
    'IPFS_DATASETS_PY_LLM_PROVIDER',
    'IPFS_DATASETS_PY_OPENAI_BASE_URL',
    'IPFS_DATASETS_PY_OPENROUTER_BASE_URL',
    'IPFS_DATASETS_PY_HF_INFERENCE_ENDPOINT',
)
WEIGHTS_ENV_VAR = 'IPFS_DATASETS_PY_LEANSTRAL_WEIGHTS'


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canonical).hexdigest()


def _filtered_env(environ: Mapping[str, str]) -> dict[str, str]:
    names = set(MODEL_ENV_VARS) | set(PROVIDER_ENV_VARS) | {WEIGHTS_ENV_VAR}
    return {name: environ[name] for name in sorted(names) if environ.get(name)}


def detect_leanstral_configuration(
    *,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    root = Path(repo_root) if repo_root is not None else _repo_root()

    model_candidates: list[dict[str, Any]] = []
    for name in MODEL_ENV_VARS:
        value = (env.get(name) or '').strip()
        if not value:
            continue
        normalized = value.lower()
        approved = any(route == normalized or route in normalized for route in APPROVED_MODEL_ROUTES)
        model_candidates.append(
            {
                'env_var': name,
                'value': value,
                'approved_route': approved,
                'detected_route': next((route for route in APPROVED_MODEL_ROUTES if route in normalized), None),
            }
        )

    weights_value = (env.get(WEIGHTS_ENV_VAR) or '').strip()
    weights_path = None
    weights_exists = False
    if weights_value:
        candidate = Path(weights_value)
        if not candidate.is_absolute():
            candidate = root / candidate
        weights_path = candidate
        weights_exists = candidate.exists()

    configured_by_route = any(candidate['approved_route'] for candidate in model_candidates)
    configured_by_weights = bool(weights_path and weights_exists)
    unapproved_leanstral = [
        candidate
        for candidate in model_candidates
        if 'leanstral' in candidate['value'].lower() and not candidate['approved_route']
    ]

    if configured_by_route or configured_by_weights:
        status = 'configured'
    elif unapproved_leanstral:
        status = 'blocked-unapproved-route'
    else:
        status = 'unconfigured'

    return {
        'status': status,
        'approved_model_routes': list(APPROVED_MODEL_ROUTES),
        'model_candidates': model_candidates,
        'provider_configuration': {name: env.get(name) for name in PROVIDER_ENV_VARS if env.get(name)},
        'local_weights': {
            'env_var': WEIGHTS_ENV_VAR,
            'value': weights_value or None,
            'path': weights_path.as_posix() if weights_path else None,
            'exists': weights_exists,
            'sha256': _sha256(weights_path) if weights_path and weights_path.is_file() else None,
        },
        'configured_by_route': configured_by_route,
        'configured_by_weights': configured_by_weights,
        'unapproved_leanstral_candidates': unapproved_leanstral,
        'observed_env_vars': _filtered_env(env),
    }


def _load_lean_lane_context(root: Path, lean_report_path: Path) -> dict[str, Any]:
    report_abs = lean_report_path if lean_report_path.is_absolute() else root / lean_report_path
    payload = _load_json(report_abs)
    return {
        'path': _relative(report_abs, root),
        'exists': report_abs.is_file(),
        'sha256': _sha256(report_abs),
        'overall_status': payload.get('overall_status') if payload else None,
        'security_decision': payload.get('security_decision') if payload else None,
        'proof_kernel_checked': payload.get('summary', {}).get('proof_kernel_checked') if payload else None,
        'lean_present': payload.get('summary', {}).get('lean_present') if payload else None,
        'lake_present': payload.get('summary', {}).get('lake_present') if payload else None,
        'proof_kernel_status': payload.get('proof_kernel_check', {}).get('status') if payload else None,
    }


def _proof_context(root: Path) -> dict[str, Any]:
    kernel = root / PROOF_KERNEL_PATH
    proof_report = root / PROOF_CONSUMER_REPORT_PATH
    proof_payload = _load_json(proof_report)
    return {
        'proof_kernel': {
            'path': PROOF_KERNEL_PATH.as_posix(),
            'exists': kernel.is_file(),
            'sha256': _sha256(kernel),
            'verification_command': f'lean {PROOF_KERNEL_PATH.as_posix()}',
        },
        'proof_consumer_report': {
            'path': PROOF_CONSUMER_REPORT_PATH.as_posix(),
            'exists': proof_report.is_file(),
            'sha256': _sha256(proof_report),
            'schema_version': proof_payload.get('schema_version') if proof_payload else None,
            'claim_id': proof_payload.get('claim_id') if proof_payload else None,
            'artifact_cid': proof_payload.get('artifact_cid') if proof_payload else None,
            'proof_kernel_cid': proof_payload.get('proof_kernel_cid') if proof_payload else None,
        },
    }


def _proof_attempt_prompts(proof_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    claim_id = (
        proof_context.get('proof_consumer_report', {}).get('claim_id')
        or 'xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims'
    )
    kernel_path = proof_context.get('proof_kernel', {}).get('path') or PROOF_KERNEL_PATH.as_posix()
    verification = proof_context.get('proof_kernel', {}).get('verification_command') or f'lean {kernel_path}'
    policy = (
        'Return Lean 4 code edits only when they preserve the existing public claim, '
        'keep rejected proof fixtures rejected, and compile with the verification command.'
    )
    return [
        {
            'id': 'leanstral:xaman-receipt-kernel-tightening',
            'claim_id': claim_id,
            'target_path': kernel_path,
            'verification_command': verification,
            'prompt': (
                f'You are assisting with Lean 4 proof engineering for {kernel_path}. '
                f'{policy} Strengthen the proof-consumer receipt invariants for {claim_id} '
                'without adding axioms, sorry, admitted, or opaque trust shortcuts.'
            ),
        },
        {
            'id': 'leanstral:negative-fixture-preservation',
            'claim_id': claim_id,
            'target_path': kernel_path,
            'verification_command': verification,
            'prompt': (
                f'Review the Lean 4 proof kernel at {kernel_path}. Propose a minimal patch that '
                'keeps DISPROVED, UNKNOWN, NOT_MODELED, MISSING_SOLVER, stale-environment, '
                'CID-mismatch, and unaccepted-assumption receipts rejected. '
                f'{policy}'
            ),
        },
        {
            'id': 'leanstral:proof-comment-to-formal-step',
            'claim_id': claim_id,
            'target_path': kernel_path,
            'verification_command': verification,
            'prompt': (
                f'Convert any remaining explanatory proof comments in {kernel_path} into explicit '
                'Lean definitions or theorem steps where possible. Do not change the production '
                f'evidence gate; every suggested proof must pass `{verification}`.'
            ),
        },
    ]


def _overall_status(configuration: Mapping[str, Any], lean_lane: Mapping[str, Any]) -> str:
    if configuration.get('status') == 'blocked-unapproved-route':
        return 'blocked'
    if configuration.get('status') == 'unconfigured':
        return 'degraded'
    if lean_lane.get('overall_status') != 'ready' or lean_lane.get('proof_kernel_checked') is not True:
        return 'blocked'
    return 'ready-advisory'


def _security_decision(status: str) -> str:
    if status == 'ready-advisory':
        return 'LEANSTRAL_ASSISTANT_READY_ADVISORY'
    if status == 'degraded':
        return 'DEGRADE_LEANSTRAL_ASSISTANT_UNCONFIGURED'
    return 'BLOCK_LEANSTRAL_ASSISTANT'


def _blockers(status: str, configuration: Mapping[str, Any], lean_lane: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if status == 'ready-advisory':
        return blockers
    if configuration.get('status') == 'blocked-unapproved-route':
        blockers.append(
            {
                'code': 'LEANSTRAL_MODEL_ROUTE_UNAPPROVED',
                'approved_model_routes': list(APPROVED_MODEL_ROUTES),
                'candidates': configuration.get('unapproved_leanstral_candidates', []),
            }
        )
    if status == 'degraded':
        blockers.append(
            {
                'code': 'LEANSTRAL_MODEL_NOT_CONFIGURED',
                'effect': 'advisory-lane-unavailable',
                'approved_model_routes': list(APPROVED_MODEL_ROUTES),
            }
        )
    if configuration.get('status') == 'configured' and (
        lean_lane.get('overall_status') != 'ready' or lean_lane.get('proof_kernel_checked') is not True
    ):
        blockers.append(
            {
                'code': 'LEAN_VERIFIER_NOT_READY_FOR_LEANSTRAL_OUTPUT',
                'lean_lane_status': lean_lane.get('overall_status'),
                'proof_kernel_checked': lean_lane.get('proof_kernel_checked'),
            }
        )
    return blockers


def build_report(
    *,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    lean_report_path: Path | str = DEFAULT_LEAN_REPORT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    env = os.environ if environ is None else environ
    lean_path = Path(lean_report_path)
    configuration = detect_leanstral_configuration(environ=env, repo_root=root)
    lean_lane = _load_lean_lane_context(root, lean_path)
    proof = _proof_context(root)
    prompts = _proof_attempt_prompts(proof)
    status = _overall_status(configuration, lean_lane)
    blockers = _blockers(status, configuration, lean_lane)

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'repo_root': root.as_posix(),
        'default_mode': 'probe-only-no-network',
        'overall_status': status,
        'security_decision': _security_decision(status),
        'release_effect': 'advisory-proof-engineering-only' if status == 'ready-advisory' else 'no-production-unblock',
        'configuration': configuration,
        'lean_lane': lean_lane,
        'proof_context': proof,
        'proof_attempt_prompts': prompts,
        'blockers': blockers,
        'acceptance_policy': {
            'leanstral_is_proof_authority': False,
            'network_calls_by_default': False,
            'required_verifier': 'Lean/Lake compile check',
            'required_verification_command': proof['proof_kernel']['verification_command'],
            'production_evidence_gate_required': True,
            'disallowed_lean_patterns': ['axiom', 'admit', 'sorry', 'unsafe proof bypass'],
            'rule': (
                'Leanstral may propose Lean edits or proof strategies, but every suggestion must '
                'compile through the Lean lane and still pass the production evidence gates.'
            ),
        },
        'summary': {
            'configured': configuration.get('status') == 'configured',
            'configured_by_route': configuration.get('configured_by_route'),
            'configured_by_weights': configuration.get('configured_by_weights'),
            'lean_lane_ready': lean_lane.get('overall_status') == 'ready',
            'proof_kernel_checked': lean_lane.get('proof_kernel_checked') is True,
            'prompt_count': len(prompts),
            'blocker_count': len(blockers),
        },
        'sources': {
            'mistral_leanstral_blog': 'https://mistral.ai/news/leanstral/',
            'mistral_leanstral_1_5_model_card': 'https://docs.mistral.ai/models/model-cards/leanstral-1-5',
        },
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Probe the Leanstral proof-assistant lane.')
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='JSON report output path')
    parser.add_argument(
        '--lean-report',
        default=DEFAULT_LEAN_REPORT.as_posix(),
        help='Lean solver lane report used as verifier readiness input',
    )
    parser.add_argument(
        '--ignore-env',
        action='store_true',
        help='ignore process environment and report an unconfigured Leanstral lane',
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root)
    report = build_report(
        repo_root=root,
        environ={} if args.ignore_env else None,
        lean_report_path=args.lean_report,
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    write_json(report, out_path)
    print(
        json.dumps(
            {
                'report': _relative(out_path, root),
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'configured': report['summary']['configured'],
                'lean_lane_ready': report['summary']['lean_lane_ready'],
                'prompt_count': report['summary']['prompt_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())

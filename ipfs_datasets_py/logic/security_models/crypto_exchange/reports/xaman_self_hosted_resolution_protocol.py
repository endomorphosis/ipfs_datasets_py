"""Conditional Tamarin and ProVerif lane for the self-hosted resolver model."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid
from .xaman_testnet_protocol import detect_solver, run_proverif_check, run_tamarin_check, solver_version


TASK_ID = 'PORTAL-CXTP-159'
SCHEMA_VERSION = 'xaman-self-hosted-resolution-protocol-report/v1'
THEORY_NAME = 'XamanSelfHostedResolution'
TAMARIN_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/protocol/xaman_self_hosted_resolution.spthy'
PROVERIF_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/protocol/xaman_self_hosted_resolution.pv'
PROTOCOL_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/protocol/resolution-protocol-report.json'

REQUIRED_LEMMAS = (
    'submit_is_single_use',
    'cancellation_blocks_later_submit',
    'expiry_blocks_later_submit',
    'replay_block_requires_prior_submit',
    'terminal_paths_are_reachable',
)

XAMAN_SELF_HOSTED_RESOLUTION_SPTHY = r'''theory XamanSelfHostedResolution
begin

/* PORTAL-CXTP-159: conditional local-resolver model. The linear Open state
   is an explicit implementation assumption for the reviewed self-hosted
   bridge. This model proves no property of the vendor payload service. */

rule Issue:
  [ Fr(~payload) ]
  --[ PayloadIssued(~payload) ]->
  [ Open(~payload) ]

rule Submit:
  [ Open(payload) ]
  --[ SubmitAccepted(payload) ]->
  [ Submitted(payload), ReplayEligible(payload) ]

rule Cancel:
  [ Open(payload) ]
  --[ Cancelled(payload) ]->
  [ CancelledState(payload) ]

rule Expire:
  [ Open(payload) ]
  --[ Expired(payload) ]->
  [ ExpiredState(payload) ]

rule ReplayBlocked:
  [ Submitted(payload), ReplayEligible(payload) ]
  --[ ReplayBlocked(payload) ]->
  [ Submitted(payload), ReplayRejected(payload) ]

lemma submit_is_single_use:
  "All payload #i #j.
    SubmitAccepted(payload) @ i & SubmitAccepted(payload) @ j
    ==> #i = #j"

lemma cancellation_blocks_later_submit:
  "All payload #i #j.
    Cancelled(payload) @ i & SubmitAccepted(payload) @ j
    ==> #j < #i"

lemma expiry_blocks_later_submit:
  "All payload #i #j.
    Expired(payload) @ i & SubmitAccepted(payload) @ j
    ==> #j < #i"

lemma replay_block_requires_prior_submit:
  "All payload #i.
    ReplayBlocked(payload) @ i
    ==> (Ex #j. SubmitAccepted(payload) @ j & #j < #i)"

lemma terminal_paths_are_reachable:
  exists-trace
  "Ex submitted cancelled expired replayed #i #j #k #l.
    SubmitAccepted(submitted) @ i &
    Cancelled(cancelled) @ j &
    Expired(expired) @ k &
    ReplayBlocked(replayed) @ l"

end
'''

XAMAN_SELF_HOSTED_RESOLUTION_PV = r'''(*
  PORTAL-CXTP-159: conditional local-resolver projection. Choice represents
  one terminal state for an issued payload. It is not a model of Xaman's
  vendor backend and cannot establish vendor single-use or expiry behavior.
*)

event issued(bitstring).
event submitted(bitstring).
event cancelled(bitstring).
event expired(bitstring).
event replay_blocked(bitstring).

query payload: bitstring; event(submitted(payload)) ==> event(issued(payload)).
query payload: bitstring; event(cancelled(payload)) ==> event(issued(payload)).
query payload: bitstring; event(expired(payload)) ==> event(issued(payload)).
query payload: bitstring; event(replay_blocked(payload)) ==> event(submitted(payload)).

process
  ! new payload: bitstring;
    event issued(payload);
    (event submitted(payload); event replay_blocked(payload)
    | event cancelled(payload)
    | event expired(payload))
'''


def _status(available: bool, run: Mapping[str, Any] | None) -> str:
    if not available:
        return 'unavailable'
    if run is None:
        return 'not-run'
    return str(run.get('status') or 'unknown')


def _source_record(path: str, source: str) -> dict[str, Any]:
    return {
        'path': path,
        'sha256': 'sha256:' + hashlib.sha256(source.encode('utf-8')).hexdigest(),
        'artifact_cid': calculate_artifact_cid({'path': path, 'source': source}),
        'line_count': len(source.splitlines()),
    }


def build_resolution_protocol_report(
    *,
    tamarin_executable: str | None,
    tamarin_run: Mapping[str, Any] | None,
    proverif_executable: str | None,
    proverif_run: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Report the conditional model results without upgrading vendor assumptions."""

    tamarin_status = _status(tamarin_executable is not None, tamarin_run)
    proverif_status = _status(proverif_executable is not None, proverif_run)
    blockers = []
    for solver, status in (('tamarin', tamarin_status), ('proverif', proverif_status)):
        if status != 'pass':
            blockers.append({'code': f'{solver.upper()}_SELF_HOSTED_RESOLUTION_NOT_ACCEPTED', 'status': status})
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model_scope': {
            'local_resolver_only': True,
            'self_hosted_network_only': True,
            'vendor_backend_modeled': False,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'model_assumptions': [
            'The reviewed self-hosted bridge implements a linear single-use Open payload state.',
            'Cancellation and expiry consume that same local Open state.',
            'Replay attempts occur only after a successful local submit and are rejected by the resolver.',
        ],
        'tamarin_model': {
            **_source_record(TAMARIN_ARTIFACT_PATH, XAMAN_SELF_HOSTED_RESOLUTION_SPTHY),
            'theory': THEORY_NAME,
            'lemmas': list(REQUIRED_LEMMAS),
            'executable': tamarin_executable,
            'version': solver_version(tamarin_executable),
            'status': tamarin_status,
            'run': dict(tamarin_run) if tamarin_run is not None else None,
        },
        'proverif_model': {
            **_source_record(PROVERIF_ARTIFACT_PATH, XAMAN_SELF_HOSTED_RESOLUTION_PV),
            'executable': proverif_executable,
            'version': solver_version(proverif_executable),
            'status': proverif_status,
            'run': dict(proverif_run) if proverif_run is not None else None,
        },
        'coverage': {
            'proved_conditionally': [
                'at_most_one_local_submit',
                'local_cancellation_blocks_later_submit',
                'local_expiry_blocks_later_submit',
                'local_replay_is_blocked_after_submit',
            ],
            'not_proved': [
                'vendor_backend_single_use',
                'vendor_backend_expiry',
                'native_vault_or_biometric_security',
                'XRPL_broadcast_finality',
                'production_wallet_security',
            ],
        },
        'blockers': blockers,
        'overall_status': 'checked_conditional_self_hosted_model' if not blockers else 'blocked_self_hosted_resolution_solver_lane',
        'security_decision': (
            'SELF_HOSTED_RESOLUTION_MODEL_CHECKED_CONDITIONALLY'
            if not blockers
            else 'BLOCK_SELF_HOSTED_RESOLUTION_MODEL'
        ),
        'production_release_blocked': True,
    }
    report['artifact_cid'] = calculate_artifact_cid({key: value for key, value in report.items() if key != 'artifact_cid'})
    return report


def run_resolution_protocol(
    repo_root: Path,
    *,
    run_solver: bool,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Materialize the conditional models and, when requested, execute both solvers."""

    tamarin_path = repo_root / TAMARIN_ARTIFACT_PATH
    proverif_path = repo_root / PROVERIF_ARTIFACT_PATH
    tamarin_path.parent.mkdir(parents=True, exist_ok=True)
    tamarin_path.write_text(XAMAN_SELF_HOSTED_RESOLUTION_SPTHY, encoding='utf-8')
    proverif_path.write_text(XAMAN_SELF_HOSTED_RESOLUTION_PV, encoding='utf-8')
    tamarin = detect_solver('tamarin-prover', install_if_missing=run_solver, reason='self-hosted resolver Tamarin check')
    proverif = detect_solver('proverif', install_if_missing=run_solver, reason='self-hosted resolver ProVerif check')
    tamarin_run = (
        run_tamarin_check(tamarin_path=tamarin_path, tamarin_executable=tamarin, timeout_seconds=timeout_seconds)
        if run_solver and tamarin is not None
        else None
    )
    proverif_run = (
        run_proverif_check(proverif_path=proverif_path, proverif_executable=proverif, timeout_seconds=timeout_seconds)
        if run_solver and proverif is not None
        else None
    )
    report = build_resolution_protocol_report(
        tamarin_executable=tamarin,
        tamarin_run=tamarin_run,
        proverif_executable=proverif,
        proverif_run=proverif_run,
    )
    report_path = repo_root / PROTOCOL_REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')
    return report

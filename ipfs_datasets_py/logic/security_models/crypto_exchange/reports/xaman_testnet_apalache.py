"""TLA+/Apalache artifacts for Xaman Testnet payload-resolution concurrency."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-134'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
SCHEMA_VERSION = 'xaman-testnet-apalache-report/v1'
MODULE_NAME = 'XamanTestnetPayload'
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid'
TRACE_MAP_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json'
ASSUMPTIONS_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json'
TLA_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/tla/XamanTestnetPayload.tla'
APALACHE_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/tla/apalache-report.json'

CONCURRENCY_CLAIM_IDS = (
    'xaman-testnet-claim:replay-controls-are-not-modeled',
    'xaman-testnet-claim:expiry-path-is-not-modeled',
    'xaman-testnet-claim:cancellation-path-is-not-modeled',
    'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
)
CONCURRENCY_ASSUMPTION_IDS = (
    'xaman-testnet-assumption:backend-replay-single-use-not-exercised',
    'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
)
REQUIRED_OPERATORS = (
    'Init',
    'Fetch',
    'Review',
    'Approve',
    'AcquireResolutionLock',
    'SignResolve',
    'DeclineResolve',
    'ExpireResolve',
    'CancelResolve',
    'DuplicateResolveBlocked',
    'ReplayBlocked',
    'Next',
    'Spec',
    'TypeOK',
    'AtMostOneSubmittedResolution',
    'ResolvedPayloadIsTerminal',
    'TerminalStateHasResolutionKind',
    'NoReviewWithoutTestnetBinding',
    'ResolutionRequiresPriorReview',
    'DuplicateClientCannotResolveAfterTerminal',
)
CHECKED_INVARIANTS = (
    'TypeOK',
    'AtMostOneSubmittedResolution',
    'ResolvedPayloadIsTerminal',
    'TerminalStateHasResolutionKind',
    'NoReviewWithoutTestnetBinding',
    'ResolutionRequiresPriorReview',
    'DuplicateClientCannotResolveAfterTerminal',
)

XAMAN_TESTNET_PAYLOAD_TLA = r'''---- MODULE XamanTestnetPayload ----
EXTENDS Naturals

\* PORTAL-CXTP-134: finite Testnet model for payload-resolution concurrency.
\* Two reviewed Testnet clients race to resolve one payload.  The model covers
\* categorical client-visible ordering, terminal resolution stability, duplicate
\* resolution blocking, and the explicit gap where backend atomic single-use is
\* still an unresolved threat-model assumption.

VARIABLES
  \* @type: Str;
  status,
  \* @type: Str;
  lockOwner,
  \* @type: Str;
  resolvedBy,
  \* @type: Str;
  resolutionKind,
  \* @type: Int;
  submitCount,
  \* @type: Str -> Str;
  clientPhase,
  \* @type: Bool;
  testnetBound,
  \* @type: Bool;
  redactionPreserved

Clients == {"clientA", "clientB"}
NoClient == "none"

Statuses ==
  {"Open", "Reviewed", "Signed", "Declined", "Expired", "Cancelled",
   "DuplicateBlocked", "ReplayBlocked"}

TerminalStatuses ==
  {"Signed", "Declined", "Expired", "Cancelled", "DuplicateBlocked",
   "ReplayBlocked"}

ResolutionKinds == {"None", "Signed", "Declined", "Expired", "Cancelled"}
ClientPhases == {"Idle", "Fetched", "Reviewing", "Approved", "Signing",
                 "Submitted", "Refused", "Blocked"}

Vars ==
  << status, lockOwner, resolvedBy, resolutionKind, submitCount, clientPhase,
     testnetBound, redactionPreserved >>

Init ==
  /\ status = "Open"
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ resolutionKind = "None"
  /\ submitCount = 0
  /\ clientPhase = [c \in Clients |-> "Idle"]
  /\ testnetBound = TRUE
  /\ redactionPreserved = TRUE

Fetch(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Idle"
  /\ status \notin TerminalStatuses
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Fetched"]
  /\ UNCHANGED <<status, lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

Review(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Fetched"
  /\ status \in {"Open", "Reviewed"}
  /\ testnetBound
  /\ redactionPreserved
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Reviewing"]
  /\ status' = "Reviewed"
  /\ UNCHANGED <<lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

Approve(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Reviewing"
  /\ status = "Reviewed"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Approved"]
  /\ UNCHANGED <<status, lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

AcquireResolutionLock(c) ==
  /\ c \in Clients
  /\ clientPhase[c] = "Approved"
  /\ status = "Reviewed"
  /\ lockOwner = NoClient
  /\ lockOwner' = c
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Signing"]
  /\ UNCHANGED <<status, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

SignResolve(c) ==
  /\ c \in Clients
  /\ lockOwner = c
  /\ clientPhase[c] = "Signing"
  /\ status = "Reviewed"
  /\ resolvedBy = NoClient
  /\ submitCount = 0
  /\ status' = "Signed"
  /\ resolvedBy' = c
  /\ resolutionKind' = "Signed"
  /\ submitCount' = 1
  /\ lockOwner' = NoClient
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Submitted"]
  /\ UNCHANGED <<testnetBound, redactionPreserved>>

DeclineResolve(c) ==
  /\ c \in Clients
  /\ clientPhase[c] \in {"Fetched", "Reviewing"}
  /\ status \in {"Open", "Reviewed"}
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ status' = "Declined"
  /\ resolvedBy' = c
  /\ resolutionKind' = "Declined"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Refused"]
  /\ UNCHANGED <<lockOwner, submitCount, testnetBound, redactionPreserved>>

ExpireResolve ==
  /\ status \in {"Open", "Reviewed"}
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ status' = "Expired"
  /\ resolutionKind' = "Expired"
  /\ UNCHANGED <<lockOwner, resolvedBy, submitCount, clientPhase, testnetBound,
                 redactionPreserved>>

CancelResolve ==
  /\ status \in {"Open", "Reviewed"}
  /\ lockOwner = NoClient
  /\ resolvedBy = NoClient
  /\ status' = "Cancelled"
  /\ resolutionKind' = "Cancelled"
  /\ UNCHANGED <<lockOwner, resolvedBy, submitCount, clientPhase, testnetBound,
                 redactionPreserved>>

DuplicateResolveBlocked(c) ==
  /\ c \in Clients
  /\ status \in {"Signed", "Declined", "Expired", "Cancelled"}
  /\ clientPhase[c] \in {"Fetched", "Reviewing", "Approved", "Signing"}
  /\ c # resolvedBy
  /\ status' = "DuplicateBlocked"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Blocked"]
  /\ UNCHANGED <<lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

ReplayBlocked(c) ==
  /\ c \in Clients
  /\ status = "Signed"
  /\ submitCount = 1
  /\ clientPhase[c] \in {"Submitted", "Approved", "Signing"}
  /\ status' = "ReplayBlocked"
  /\ clientPhase' = [clientPhase EXCEPT ![c] = "Blocked"]
  /\ UNCHANGED <<lockOwner, resolvedBy, resolutionKind, submitCount,
                 testnetBound, redactionPreserved>>

Next ==
  \/ \E c \in Clients: Fetch(c)
  \/ \E c \in Clients: Review(c)
  \/ \E c \in Clients: Approve(c)
  \/ \E c \in Clients: AcquireResolutionLock(c)
  \/ \E c \in Clients: SignResolve(c)
  \/ \E c \in Clients: DeclineResolve(c)
  \/ ExpireResolve
  \/ CancelResolve
  \/ \E c \in Clients: DuplicateResolveBlocked(c)
  \/ \E c \in Clients: ReplayBlocked(c)

Spec == Init /\ [][Next]_Vars

TypeOK ==
  /\ status \in Statuses
  /\ lockOwner \in Clients \cup {NoClient}
  /\ resolvedBy \in Clients \cup {NoClient}
  /\ resolutionKind \in ResolutionKinds
  /\ submitCount \in 0..1
  /\ clientPhase \in [Clients -> ClientPhases]
  /\ testnetBound \in BOOLEAN
  /\ redactionPreserved \in BOOLEAN

AtMostOneSubmittedResolution ==
  submitCount <= 1

ResolvedPayloadIsTerminal ==
  (resolvedBy # NoClient) => status \in TerminalStatuses

TerminalStateHasResolutionKind ==
  (status \in {"Signed", "Declined", "Expired", "Cancelled"}) =>
    resolutionKind # "None"

NoReviewWithoutTestnetBinding ==
  \A c \in Clients:
    clientPhase[c] \in {"Reviewing", "Approved", "Signing", "Submitted"} =>
      testnetBound

ResolutionRequiresPriorReview ==
  (resolutionKind \in {"Signed", "Declined"}) =>
    \E c \in Clients:
      /\ c = resolvedBy
      /\ clientPhase[c] \in {"Submitted", "Refused", "Blocked"}

DuplicateClientCannotResolveAfterTerminal ==
  status \in {"DuplicateBlocked", "ReplayBlocked"} => submitCount <= 1

THEOREM Spec => []TypeOK
THEOREM Spec => []AtMostOneSubmittedResolution
THEOREM Spec => []ResolvedPayloadIsTerminal
THEOREM Spec => []TerminalStateHasResolutionKind
THEOREM Spec => []NoReviewWithoutTestnetBinding
THEOREM Spec => []ResolutionRequiresPriorReview
THEOREM Spec => []DuplicateClientCannotResolveAfterTerminal

===='''


def build_xaman_testnet_apalache_report(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
    tla_source: str = XAMAN_TESTNET_PAYLOAD_TLA,
    apalache_executable: str | None = None,
    apalache_version: str | None = None,
    apalache_runs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic Testnet Apalache coverage report."""

    _validate_bound_inputs(model_payload, model_cid, trace_map_payload, assumptions_payload)
    claims_by_id = {claim['id']: claim for claim in model_payload.get('claims', [])}
    assumptions_by_id = {
        assumption['id']: assumption
        for assumption in assumptions_payload.get('assumptions', model_payload.get('assumptions', []))
    }
    missing_claim_ids = sorted(set(CONCURRENCY_CLAIM_IDS) - set(claims_by_id))
    missing_assumption_ids = sorted(set(CONCURRENCY_ASSUMPTION_IDS) - set(assumptions_by_id))
    solver_available = apalache_executable is not None
    runs = list(apalache_runs or [])
    run_failures = [run for run in runs if run.get('exit_code') != 0 or run.get('status') != 'pass']
    all_required_invariants_checked = solver_available and len(runs) == len(CHECKED_INVARIANTS) and not run_failures
    unresolved_required_assumptions = [
        {
            'id': assumption_id,
            'status': assumptions_by_id.get(assumption_id, {}).get('status', 'MISSING'),
            'description': assumptions_by_id.get(assumption_id, {}).get('description'),
            'required_evidence_to_clear': assumptions_by_id.get(assumption_id, {}).get('required_evidence_to_clear', []),
        }
        for assumption_id in CONCURRENCY_ASSUMPTION_IDS
        if assumptions_by_id.get(assumption_id, {}).get('status') == 'BLOCKING'
    ]

    if not solver_available:
        overall_status = 'blocked_required_lane_unavailable'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_APALACHE_UNAVAILABLE'
    elif run_failures:
        overall_status = 'blocked_required_lane_failed'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_APALACHE_FAILED'
    elif unresolved_required_assumptions:
        overall_status = 'checked_with_unresolved_threat_model_gaps'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_CONCURRENCY_ASSUMPTIONS'
    else:
        overall_status = 'checked'
        security_decision = 'TESTNET_CONCURRENCY_MODEL_CHECKED'

    coverage_decision = {
        'decision': 'required',
        'reason': (
            'The approved Testnet model retains blocking replay, duplicate submission, '
            'backend atomic single-use, expiry, cancellation, and conflict-handling gaps; '
            'therefore payload-resolution concurrency is in scope and an unavailable '
            'Apalache lane blocks the Testnet assurance verdict.'
        ),
        'required_by_assumption_ids': list(CONCURRENCY_ASSUMPTION_IDS),
        'covered_claim_ids': list(CONCURRENCY_CLAIM_IDS),
        'unavailable_apalache_blocks_testnet_assurance': True,
        'claim_scope': 'finite client-visible Testnet payload-resolution interleavings',
        'not_modeled': [
            'backend atomic single-use implementation',
            'remote payload service serialization internals',
            'raw payload JSON or signature bytes',
            'XRPL mempool, queue, validated-ledger inclusion, or finality',
        ],
    }

    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model_payload['model_id'],
            'schema_version': model_payload['schema_version'],
            'cid': model_cid,
        },
        'inputs': {
            'claim_trace_map': {
                'path': TRACE_MAP_PATH,
                'model_cid': trace_map_payload['model_cid'],
                'artifact_cid': trace_map_payload.get('artifact_cid') or calculate_artifact_cid(trace_map_payload),
            },
            'assumptions': {
                'path': ASSUMPTIONS_PATH,
                'model_cid': assumptions_payload['model_cid'],
                'artifact_cid': assumptions_payload.get('artifact_cid') or calculate_artifact_cid(assumptions_payload),
            },
        },
        'tla_model': {
            'module_name': MODULE_NAME,
            'path': TLA_ARTIFACT_PATH,
            'artifact_cid': calculate_artifact_cid({'module_name': MODULE_NAME, 'source': tla_source}),
            'sha256': 'sha256:' + __import__('hashlib').sha256(tla_source.encode('utf-8')).hexdigest(),
            'line_count': len(tla_source.splitlines()),
            'required_operators': list(REQUIRED_OPERATORS),
            'checked_invariants': list(CHECKED_INVARIANTS),
        },
        'coverage_decision': coverage_decision,
        'apalache': {
            'solver': 'apalache',
            'required': True,
            'available': solver_available,
            'executable': apalache_executable,
            'version': apalache_version,
            'unavailable_blocks_testnet_assurance': True,
            'runs': runs,
        },
        'claim_coverage': [
            {
                'claim_id': claim_id,
                'status': claims_by_id.get(claim_id, {}).get('status', 'MISSING'),
                'severity': claims_by_id.get(claim_id, {}).get('severity', 'MISSING'),
                'modeled_by_invariants': list(CHECKED_INVARIANTS),
            }
            for claim_id in CONCURRENCY_CLAIM_IDS
        ],
        'unresolved_required_assumptions': unresolved_required_assumptions,
        'missing_claim_ids': missing_claim_ids,
        'missing_assumption_ids': missing_assumption_ids,
        'summary': {
            'claim_count': len(CONCURRENCY_CLAIM_IDS),
            'assumption_count': len(CONCURRENCY_ASSUMPTION_IDS),
            'invariant_count': len(CHECKED_INVARIANTS),
            'checked_invariant_count': len(runs) if solver_available else 0,
            'all_required_invariants_checked': all_required_invariants_checked,
            'run_failure_count': len(run_failures),
            'unresolved_required_assumption_count': len(unresolved_required_assumptions),
        },
        'overall_status': overall_status,
        'security_decision': security_decision,
        'testnet_assurance_blocked': security_decision.startswith('BLOCK_'),
        'production_release_blocked': True,
    }
    report['report_cid'] = calculate_artifact_cid(_without_key(report, 'report_cid'))
    return report


def run_apalache_invariant_checks(
    *,
    tla_path: Path,
    apalache_executable: str,
    invariants: Sequence[str] = CHECKED_INVARIANTS,
    timeout_seconds: int = 120,
    working_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run Apalache once per invariant and return compact deterministic results."""

    runs: list[dict[str, Any]] = []
    tla_argument = tla_path.name if working_dir is not None else str(tla_path)
    for invariant in invariants:
        command = [
            apalache_executable,
            'check',
            '--no-deadlock',
            '--init=Init',
            '--next=Next',
            f'--inv={invariant}',
            tla_argument,
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=working_dir,
            )
            output = '\n'.join(part for part in (completed.stdout, completed.stderr) if part).strip()
            status = 'pass' if completed.returncode == 0 and 'Checker reports no error' in output else 'fail'
            reason = _apalache_reason(output, completed.returncode)
            runs.append(
                {
                    'invariant': invariant,
                    'command': command,
                    'exit_code': completed.returncode,
                    'status': status,
                    'reason': reason,
                    'output_retained': False,
                }
            )
        except subprocess.TimeoutExpired as exc:
            output = '\n'.join(part for part in (exc.stdout or '', exc.stderr or '') if part).strip()
            runs.append(
                {
                    'invariant': invariant,
                    'command': command,
                    'exit_code': None,
                    'status': 'timeout',
                    'reason': 'apalache timed out before completing the invariant check',
                    'output_retained': False,
                }
            )
    return runs


def _validate_bound_inputs(
    model_payload: Mapping[str, Any],
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
) -> None:
    if trace_map_payload.get('model_cid') != model_cid:
        raise ValueError('claim-trace-map model_cid does not match the pinned Testnet model CID')
    if assumptions_payload.get('model_cid') != model_cid:
        raise ValueError('assumptions model_cid does not match the pinned Testnet model CID')
    if model_payload.get('metadata', {}).get('production_release_blocked') is not True:
        raise ValueError('Testnet Apalache report must bind to a production-blocking Testnet model')


def _without_key(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {item_key: value for item_key, value in payload.items() if item_key != key}


def _apalache_reason(output: str, exit_code: int) -> str:
    if exit_code == 0 and 'Checker reports no error' in output:
        return 'apalache completed the bounded invariant check without a counterexample'
    if 'Found a deadlock' in output:
        return 'apalache found a deadlock; terminal deadlocks are expected only when --no-deadlock is enabled'
    for marker in ('Error:', 'PASS', 'FAIL'):
        if marker in output:
            return output[output.index(marker):].splitlines()[0][:240]
    return f'apalache exited with code {exit_code}'

"""Tamarin/ProVerif artifacts for Xaman Testnet remote-payload claims."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-135'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
SCHEMA_VERSION = 'xaman-testnet-protocol-report/v1'
THEORY_NAME = 'XamanTestnetPayload'
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid'
TRACE_MAP_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json'
ASSUMPTIONS_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json'
TAMARIN_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/protocol/xaman_testnet_payload.spthy'
PROVERIF_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/protocol/xaman_testnet_payload.pv'
PROTOCOL_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json'
FUZZ_COUNTEREXAMPLE_MANIFEST_PATH = (
    'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json'
)

PROTOCOL_CLAIM_IDS = (
    'xaman-testnet-claim:network-binding-is-testnet-only',
    'xaman-testnet-claim:account-provenance-is-fresh-testnet-only',
    'xaman-testnet-claim:review-auth-sequence-observed',
    'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
    'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
    'xaman-testnet-claim:payload-intake-is-categorical-only',
    'xaman-testnet-claim:refusal-path-is-not-modeled',
    'xaman-testnet-claim:replay-controls-are-not-modeled',
    'xaman-testnet-claim:expiry-path-is-not-modeled',
    'xaman-testnet-claim:cancellation-path-is-not-modeled',
    'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
    'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
)

MODELED_CLAIM_IDS = (
    'xaman-testnet-claim:network-binding-is-testnet-only',
    'xaman-testnet-claim:account-provenance-is-fresh-testnet-only',
    'xaman-testnet-claim:review-auth-sequence-observed',
    'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
    'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
    'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
)

NOT_MODELED_CLAIM_IDS = (
    'xaman-testnet-claim:payload-intake-is-categorical-only',
    'xaman-testnet-claim:refusal-path-is-not-modeled',
    'xaman-testnet-claim:replay-controls-are-not-modeled',
    'xaman-testnet-claim:expiry-path-is-not-modeled',
    'xaman-testnet-claim:cancellation-path-is-not-modeled',
    'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
)

REQUIRED_LEMMAS = (
    'review_requires_testnet_binding',
    'review_requires_fresh_testnet_account',
    'auth_requires_review',
    'signing_decision_requires_review_and_auth',
    'submit_ui_requires_signing_decision',
    'audit_redaction_preserved_for_payload_intake',
    'audit_redaction_preserved_for_review',
    'audit_redaction_preserved_for_signing_decision',
    'audit_redaction_preserved_for_submit_result',
    'preserved_attack_traces_are_reachable',
)

REQUIRED_EVENTS = (
    'RemotePayloadIssued',
    'TestnetBound',
    'FreshTestnetAccountBoundary',
    'PayloadIntakeCategorical',
    'PayloadReviewed',
    'AuthDecisionAuthorized',
    'SigningDecisionObserved',
    'SubmitAttemptObserved',
    'SubmitResultObserved',
    'AuditRedactionPreserved',
    'AttackTraceWrongNetwork',
    'AttackTraceImportedProductionAccount',
    'AttackTraceSigningBeforeAuth',
    'AttackTraceReplayDuplicateResolution',
    'AttackTraceRawPayloadMaterial',
    'AttackTraceRawSignatureBlob',
    'AttackTraceForgedBroadcastFinality',
    'AttackTraceDeclineGap',
    'AttackTraceCancelGap',
    'AttackTraceExpiryGap',
)

XAMAN_TESTNET_PAYLOAD_SPTHY = r'''theory XamanTestnetPayload
begin

builtins: hashing, signing

functions: xrpl_testnet/0, xrpl_mainnet/0, payload_id/1, redaction_digest/1, ui_result/1

/* PORTAL-CXTP-135: Tamarin projection for the Xaman Testnet remote-payload
   protocol claim lane.  The model intentionally keeps only reviewed
   categorical Testnet facts.  Raw payload JSON, account material, signatures,
   signed blobs, XRPL broadcast/finality, replay, refusal, cancellation, and
   expiry semantics are NOT_MODELED in protocol-report.json. */

rule Remote_Service_Issues_Redacted_Testnet_Payload:
  [ Fr(~payload), Fr(~account) ]
  --[ RemotePayloadIssued(~payload),
      TestnetBound(~payload),
      FreshTestnetAccountBoundary(~account),
      AuditRedactionPreserved(~payload) ]->
  [ Out(<xrpl_testnet, payload_id(~payload), redaction_digest(~payload)>),
    !ReviewedTestnetPayload(~payload, payload_id(~payload), redaction_digest(~payload), ~account) ]

rule Device_Intakes_Categorical_Payload:
  [ In(<xrpl_testnet, payload_id(payload), redaction_digest(payload)>),
    !ReviewedTestnetPayload(payload, payload_id(payload), redaction_digest(payload), account) ]
  --[ PayloadIntakeCategorical(payload),
      TestnetBound(payload),
      FreshTestnetAccountBoundary(account),
      AuditRedactionPreserved(payload) ]->
  [ ReviewablePayload(payload, account) ]

rule Device_Reviews_Payload:
  [ ReviewablePayload(payload, account) ]
  --[ PayloadReviewed(payload),
      TestnetBound(payload),
      FreshTestnetAccountBoundary(account),
      AuditRedactionPreserved(payload) ]->
  [ ReviewedPayload(payload, account) ]

rule Operator_Authorizes_After_Review:
  [ ReviewedPayload(payload, account) ]
  --[ AuthDecisionAuthorized(payload),
      AuditRedactionPreserved(payload) ]->
  [ AuthorizedPayload(payload, account) ]

rule Device_Observes_Signing_Decision:
  [ AuthorizedPayload(payload, account) ]
  --[ SigningDecisionObserved(payload),
      AuditRedactionPreserved(payload) ]->
  [ SignedDecision(payload, account, sign(payload_id(payload), redaction_digest(payload))) ]

rule Device_Observes_Submit_UI:
  [ SignedDecision(payload, account, signature) ]
  --[ SubmitAttemptObserved(payload),
      SubmitResultObserved(payload),
      AuditRedactionPreserved(payload) ]->
  [ Out(<ui_result(payload), signature>) ]

rule Preserve_Attack_Wrong_Network:
  [ Fr(~payload) ]
  --[ AttackTraceWrongNetwork(~payload) ]->
  [ Out(<xrpl_mainnet, payload_id(~payload), redaction_digest(~payload)>) ]

rule Preserve_Attack_Imported_Production_Account:
  [ Fr(~account) ]
  --[ AttackTraceImportedProductionAccount(~account) ]->
  [ Out(~account) ]

rule Preserve_Attack_Signing_Before_Auth:
  [ Fr(~payload) ]
  --[ AttackTraceSigningBeforeAuth(~payload) ]->
  [ Out(<payload_id(~payload), sign(payload_id(~payload), redaction_digest(~payload))>) ]

rule Preserve_Attack_Replay_Duplicate_Resolution:
  [ Fr(~payload) ]
  --[ AttackTraceReplayDuplicateResolution(~payload) ]->
  [ Out(<payload_id(~payload), payload_id(~payload)>) ]

rule Preserve_Attack_Raw_Payload_Material:
  [ Fr(~payload) ]
  --[ AttackTraceRawPayloadMaterial(~payload) ]->
  [ Out(~payload) ]

rule Preserve_Attack_Raw_Signature_Blob:
  [ Fr(~payload) ]
  --[ AttackTraceRawSignatureBlob(~payload) ]->
  [ Out(sign(payload_id(~payload), redaction_digest(~payload))) ]

rule Preserve_Attack_Forged_Broadcast_Finality:
  [ Fr(~payload) ]
  --[ AttackTraceForgedBroadcastFinality(~payload) ]->
  [ Out(<ui_result(~payload), xrpl_mainnet>) ]

rule Preserve_Attack_Decline_Gap:
  [ Fr(~payload) ]
  --[ AttackTraceDeclineGap(~payload) ]->
  [ Out(<payload_id(~payload), 'decline_gap'>) ]

rule Preserve_Attack_Cancel_Gap:
  [ Fr(~payload) ]
  --[ AttackTraceCancelGap(~payload) ]->
  [ Out(<payload_id(~payload), 'cancel_gap'>) ]

rule Preserve_Attack_Expiry_Gap:
  [ Fr(~payload) ]
  --[ AttackTraceExpiryGap(~payload) ]->
  [ Out(<payload_id(~payload), 'expiry_gap'>) ]

lemma review_requires_testnet_binding:
  "All payload #i.
    PayloadReviewed(payload) @ i
    ==>
    (Ex #j. TestnetBound(payload) @ j & j < i)"

lemma review_requires_fresh_testnet_account:
  "All payload #i.
    PayloadReviewed(payload) @ i
    ==>
    (Ex account #j. FreshTestnetAccountBoundary(account) @ j & j < i)"

lemma auth_requires_review:
  "All payload #i.
    AuthDecisionAuthorized(payload) @ i
    ==>
    (Ex #j. PayloadReviewed(payload) @ j & j < i)"

lemma signing_decision_requires_review_and_auth:
  "All payload #i.
    SigningDecisionObserved(payload) @ i
    ==>
    (Ex #j #k. PayloadReviewed(payload) @ j & AuthDecisionAuthorized(payload) @ k & j < i & k < i)"

lemma submit_ui_requires_signing_decision:
  "All payload #i.
    SubmitAttemptObserved(payload) @ i
    ==>
    (Ex #j. SigningDecisionObserved(payload) @ j & j < i)"

lemma audit_redaction_preserved_for_payload_intake:
  "All payload #i.
    PayloadIntakeCategorical(payload) @ i
    ==>
    (Ex #j. AuditRedactionPreserved(payload) @ j & #j = #i)"

lemma audit_redaction_preserved_for_review:
  "All payload #i.
    PayloadReviewed(payload) @ i
    ==>
    (Ex #j. AuditRedactionPreserved(payload) @ j & #j = #i)"

lemma audit_redaction_preserved_for_signing_decision:
  "All payload #i.
    SigningDecisionObserved(payload) @ i
    ==>
    (Ex #j. AuditRedactionPreserved(payload) @ j & #j = #i)"

lemma audit_redaction_preserved_for_submit_result:
  "All payload #i.
    SubmitResultObserved(payload) @ i
    ==>
    (Ex #j. AuditRedactionPreserved(payload) @ j & #j = #i)"

lemma preserved_attack_traces_are_reachable:
  exists-trace
  "Ex wrong_network_payload account signing_before_auth_payload replay_payload raw_payload
      signature_payload finality_payload decline_payload cancel_payload expiry_payload
      #i #j #k #l #m #n #o #p #q #r.
    AttackTraceWrongNetwork(wrong_network_payload) @ i &
    AttackTraceImportedProductionAccount(account) @ j &
    AttackTraceSigningBeforeAuth(signing_before_auth_payload) @ k &
    AttackTraceReplayDuplicateResolution(replay_payload) @ l &
    AttackTraceRawPayloadMaterial(raw_payload) @ m &
    AttackTraceRawSignatureBlob(signature_payload) @ n &
    AttackTraceForgedBroadcastFinality(finality_payload) @ o &
    AttackTraceDeclineGap(decline_payload) @ p &
    AttackTraceCancelGap(cancel_payload) @ q &
    AttackTraceExpiryGap(expiry_payload) @ r"

end
'''


XAMAN_TESTNET_PAYLOAD_PV = r'''(*
  PORTAL-CXTP-135: bounded ProVerif projection of the redacted Xaman Testnet
  payload lifecycle. The model establishes only event ordering. It does not
  model native signing, raw payload JSON, backend single-use, cancellation,
  expiry, replay resolution, XRPL broadcast/finality, or production release.
*)

event testnet_bound(bitstring).
event fresh_testnet_account(bitstring).
event payload_reviewed(bitstring).
event auth_authorized(bitstring).
event signing_decision_observed(bitstring).
event submit_attempt_observed(bitstring).
event submit_result_observed(bitstring).
event audit_redaction_preserved(bitstring).

query payload: bitstring;
  event(payload_reviewed(payload)) ==> event(testnet_bound(payload)).
query payload: bitstring;
  event(payload_reviewed(payload)) ==> event(fresh_testnet_account(payload)).
query payload: bitstring;
  event(auth_authorized(payload)) ==> event(payload_reviewed(payload)).
query payload: bitstring;
  event(signing_decision_observed(payload)) ==> event(auth_authorized(payload)).
query payload: bitstring;
  event(submit_attempt_observed(payload)) ==> event(signing_decision_observed(payload)).
query payload: bitstring;
  event(submit_result_observed(payload)) ==> event(submit_attempt_observed(payload)).

process
  new payload: bitstring;
  event testnet_bound(payload);
  event fresh_testnet_account(payload);
  event audit_redaction_preserved(payload);
  event payload_reviewed(payload);
  event auth_authorized(payload);
  event signing_decision_observed(payload);
  event submit_attempt_observed(payload);
  event submit_result_observed(payload)
'''


def build_xaman_testnet_protocol_report(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
    tamarin_source: str = XAMAN_TESTNET_PAYLOAD_SPTHY,
    tamarin_executable: str | None = None,
    tamarin_version: str | None = None,
    tamarin_run: Mapping[str, Any] | None = None,
    proverif_executable: str | None = None,
    proverif_version: str | None = None,
    proverif_model_source: str | None = None,
    proverif_run: Mapping[str, Any] | None = None,
    fuzz_counterexample_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic protocol coverage report for the Testnet payload lane."""

    _validate_bound_inputs(model_payload, model_cid, trace_map_payload, assumptions_payload)
    claims_by_id = {claim['id']: claim for claim in model_payload.get('claims', [])}
    assumptions_by_id = {
        assumption['id']: assumption
        for assumption in assumptions_payload.get('assumptions', model_payload.get('assumptions', []))
    }
    not_modeled_records = list(trace_map_payload.get('not_modeled_records', []))
    disproof_vectors = list(model_payload.get('disproof_vectors', []))
    missing_claim_ids = sorted(set(PROTOCOL_CLAIM_IDS) - set(claims_by_id))
    unresolved_assumptions = [
        {
            'id': assumption['id'],
            'status': assumption.get('status'),
            'description': assumption.get('description'),
            'required_evidence_to_clear': assumption.get('required_evidence_to_clear', []),
        }
        for assumption in assumptions_by_id.values()
        if assumption.get('status') == 'BLOCKING'
        and any(claim_id in PROTOCOL_CLAIM_IDS for claim_id in _claim_ids_for_assumption(claims_by_id, assumption['id']))
    ]

    tamarin_available = tamarin_executable is not None
    proverif_available = proverif_executable is not None
    proverif_model_present = proverif_model_source is not None
    tamarin_status = _solver_status(tamarin_available, tamarin_run)
    proverif_status = _solver_status(proverif_available and proverif_model_present, proverif_run)
    blockers = _blockers(
        tamarin_available=tamarin_available,
        proverif_available=proverif_available,
        proverif_model_present=proverif_model_present,
        tamarin_status=tamarin_status,
        proverif_status=proverif_status,
        missing_claim_ids=missing_claim_ids,
    )

    unsupported_protocol_semantics = [
        {
            'id': record['id'],
            'claim_id': record['claim_id'],
            'category': record.get('category'),
            'status': 'NOT_MODELED',
            'assumption_id': record.get('assumption_id'),
            'reason': record.get('reason'),
            'source_location': record.get('source_location'),
            'evidence_review_status': record.get('evidence_review_status'),
        }
        for record in not_modeled_records
        if record.get('claim_id') in PROTOCOL_CLAIM_IDS
    ]

    if blockers:
        overall_status = 'blocked_required_lane_unavailable'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_PROTOCOL_SOLVER_LANE_UNAVAILABLE'
    elif unresolved_assumptions:
        overall_status = 'checked_with_unresolved_threat_model_gaps'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_PROTOCOL_ASSUMPTIONS'
    else:
        overall_status = 'checked'
        security_decision = 'TESTNET_PROTOCOL_MODEL_CHECKED'

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
            'fuzz_counterexamples': _fuzz_input_summary(fuzz_counterexample_manifest),
        },
        'tamarin_model': {
            'theory': THEORY_NAME,
            'path': TAMARIN_ARTIFACT_PATH,
            'artifact_cid': calculate_artifact_cid({'theory': THEORY_NAME, 'source': tamarin_source}),
            'sha256': 'sha256:' + hashlib.sha256(tamarin_source.encode('utf-8')).hexdigest(),
            'line_count': len(tamarin_source.splitlines()),
            'required_events': list(REQUIRED_EVENTS),
            'lemmas': list(REQUIRED_LEMMAS),
        },
        'proverif_model': {
            'path': PROVERIF_ARTIFACT_PATH,
            'exists': proverif_model_present,
            'sha256': (
                'sha256:' + hashlib.sha256(proverif_model_source.encode('utf-8')).hexdigest()
                if proverif_model_source is not None
                else None
            ),
            'coverage_decision': (
                'required_but_unavailable'
                if not proverif_model_present
                else 'required_projection_present'
            ),
        },
        'coverage_decision': {
            'decision': 'required',
            'reason': (
                'The approved Testnet threat model contains remote-payload claims for network binding, '
                'fresh account provenance, review/auth ordering, signing decision ordering, submission UI '
                'ordering, audit boundaries, and explicit protocol gaps. Tamarin and ProVerif are required '
                'lanes; unavailable solvers or missing ProVerif projection block Testnet assurance.'
            ),
            'required_solvers': ['tamarin-prover', 'proverif'],
            'covered_claim_ids': list(PROTOCOL_CLAIM_IDS),
            'modeled_claim_ids': list(MODELED_CLAIM_IDS),
            'not_modeled_claim_ids': list(NOT_MODELED_CLAIM_IDS),
            'unavailable_protocol_solver_blocks_testnet_assurance': True,
        },
        'solver_lanes': {
            'tamarin': {
                'solver': 'tamarin-prover',
                'required': True,
                'available': tamarin_available,
                'executable': tamarin_executable,
                'version': tamarin_version,
                'command': [tamarin_executable or 'tamarin-prover', '--prove', TAMARIN_ARTIFACT_PATH],
                'status': tamarin_status,
                'run': dict(tamarin_run) if tamarin_run is not None else None,
                'unavailable_blocks_testnet_assurance': True,
            },
            'proverif': {
                'solver': 'proverif',
                'required': True,
                'available': proverif_available,
                'executable': proverif_executable,
                'version': proverif_version,
                'command': [proverif_executable or 'proverif', PROVERIF_ARTIFACT_PATH],
                'status': proverif_status,
                'run': dict(proverif_run) if proverif_run is not None else None,
                'unavailable_blocks_testnet_assurance': True,
            },
        },
        'claim_coverage': _claim_coverage(claims_by_id),
        'unsupported_protocol_semantics': unsupported_protocol_semantics,
        'attack_trace_retention': {
            'policy': 'preserve_attack_traces_as_blocking_counterevidence_until an approved solver run discharges or refines them',
            'disproof_vectors': [
                {
                    'id': vector['id'],
                    'claim_id': vector['claim_id'],
                    'status': vector.get('status'),
                    'tactic': vector.get('tactic'),
                }
                for vector in disproof_vectors
                if vector.get('claim_id') in PROTOCOL_CLAIM_IDS
            ],
            'fuzz_counterexamples': list((fuzz_counterexample_manifest or {}).get('counterexamples', [])),
        },
        'unresolved_required_assumptions': unresolved_assumptions,
        'missing_claim_ids': missing_claim_ids,
        'blockers': blockers,
        'summary': {
            'claim_count': len(PROTOCOL_CLAIM_IDS),
            'modeled_claim_count': len(MODELED_CLAIM_IDS),
            'not_modeled_claim_count': len(NOT_MODELED_CLAIM_IDS),
            'unsupported_semantic_count': len(unsupported_protocol_semantics),
            'blocking_assumption_count': len(unresolved_assumptions),
            'attack_trace_count': len(disproof_vectors) + len((fuzz_counterexample_manifest or {}).get('counterexamples', [])),
            'blocker_count': len(blockers),
        },
        'overall_status': overall_status,
        'security_decision': security_decision,
        'testnet_assurance_blocked': security_decision.startswith('BLOCK_'),
        'production_release_blocked': True,
    }
    report['report_cid'] = calculate_artifact_cid(_without_key(report, 'report_cid'))
    return report


def run_tamarin_check(
    *,
    tamarin_path: Path,
    tamarin_executable: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    command = [tamarin_executable, '--prove', str(tamarin_path)]
    result = _run_solver(command, timeout_seconds=timeout_seconds)
    output = str(result.get('stdout', '')).lower()
    if result['status'] == 'pass' and (
        'falsified' in output or 'wellformedness check failed' in output
    ):
        result['status'] = 'failed'
        result['output_retained'] = True
        result['stderr'] = (
            str(result.get('stderr', ''))
            + '\nTamarin returned an unacceptable lemma result or wellformedness warning.'
        ).strip()
    return result


def run_proverif_check(
    *,
    proverif_path: Path,
    proverif_executable: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    command = [proverif_executable, str(proverif_path)]
    result = _run_solver(command, timeout_seconds=timeout_seconds)
    if result['status'] == 'pass' and ' is false.' in str(result.get('stdout', '')).lower():
        result['status'] = 'failed'
        result['output_retained'] = True
        result['stderr'] = (
            str(result.get('stderr', ''))
            + '\nProVerif returned a false correspondence query.'
        ).strip()
    return result


def detect_solver(name: str, *, install_if_missing: bool = False, reason: str | None = None) -> str | None:
    """Resolve a protocol solver and install only for an actual solver run."""

    executable = shutil.which(name)
    if executable is not None or not install_if_missing:
        return executable
    from ipfs_datasets_py.logic.external_provers.lazy_installer import ensure_prover_executable

    return ensure_prover_executable(
        name,
        reason=reason or f'{name} protocol solver execution',
    )


def solver_version(executable: str | None) -> str | None:
    if executable is None:
        return None
    for args in (['--version'], ['-version'], ['version'], []):
        try:
            completed = subprocess.run(
                [executable, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (completed.stdout or completed.stderr).strip()
        lowered = output.lower()
        if output and 'unknown option' not in lowered and not lowered.startswith('error:'):
            return output.splitlines()[0]
        for line in output.splitlines():
            if 'proverif' in line.lower() and 'cryptographic protocol verifier' in line.lower():
                return line
    return None


def _claim_coverage(claims_by_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for claim_id in PROTOCOL_CLAIM_IDS:
        claim = claims_by_id.get(claim_id, {})
        if claim_id in NOT_MODELED_CLAIM_IDS:
            protocol_status = 'NOT_MODELED'
            lemmas: list[str] = []
        else:
            protocol_status = claim.get('status', 'MISSING')
            lemmas = list(REQUIRED_LEMMAS[:-1])
        coverage.append(
            {
                'claim_id': claim_id,
                'model_status': claim.get('status', 'MISSING'),
                'protocol_status': protocol_status,
                'severity': claim.get('severity', 'MISSING'),
                'coverage_tags': list(claim.get('coverage_tags', [])),
                'modeled_by_lemmas': lemmas,
            }
        )
    return coverage


def _blockers(
    *,
    tamarin_available: bool,
    proverif_available: bool,
    proverif_model_present: bool,
    tamarin_status: str,
    proverif_status: str,
    missing_claim_ids: Sequence[str],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not tamarin_available:
        blockers.append(
            {
                'code': 'TAMARIN_EXECUTABLE_MISSING',
                'message': 'Required tamarin-prover executable is not available on PATH.',
            }
        )
    if not proverif_available:
        blockers.append(
            {
                'code': 'PROVERIF_EXECUTABLE_MISSING',
                'message': 'Required proverif executable is not available on PATH.',
            }
        )
    if not proverif_model_present:
        blockers.append(
            {
                'code': 'PROVERIF_MODEL_MISSING',
                'message': f'Required ProVerif projection {PROVERIF_ARTIFACT_PATH} is not present.',
            }
        )
    if tamarin_available and tamarin_status == 'not-run':
        blockers.append(
            {
                'code': 'TAMARIN_CHECK_NOT_RUN',
                'message': 'Required Tamarin protocol check has not been executed.',
            }
        )
    if proverif_available and proverif_model_present and proverif_status == 'not-run':
        blockers.append(
            {
                'code': 'PROVERIF_CHECK_NOT_RUN',
                'message': 'Required ProVerif protocol check has not been executed.',
            }
        )
    if tamarin_status in {'failed', 'timeout', 'unknown'}:
        blockers.append({'code': 'TAMARIN_CHECK_NOT_ACCEPTED', 'message': f'Tamarin status is {tamarin_status}.'})
    if proverif_status in {'failed', 'timeout', 'unknown'}:
        blockers.append({'code': 'PROVERIF_CHECK_NOT_ACCEPTED', 'message': f'ProVerif status is {proverif_status}.'})
    if missing_claim_ids:
        blockers.append(
            {
                'code': 'PROTOCOL_CLAIMS_MISSING',
                'message': 'The pinned Testnet model does not contain every required protocol claim.',
                'missing_claim_ids': list(missing_claim_ids),
            }
        )
    return blockers


def _solver_status(solver_inputs_available: bool, run: Mapping[str, Any] | None) -> str:
    if not solver_inputs_available:
        return 'not-run'
    if run is None:
        return 'not-run'
    status = str(run.get('status', 'unknown'))
    if status in {'pass', 'passed'}:
        return 'passed'
    if status in {'timeout', 'failed', 'unknown'}:
        return status
    return 'failed'


def _claim_ids_for_assumption(
    claims_by_id: Mapping[str, Mapping[str, Any]],
    assumption_id: str,
) -> list[str]:
    return [
        claim_id
        for claim_id, claim in claims_by_id.items()
        if assumption_id in claim.get('required_assumptions', [])
    ]


def _fuzz_input_summary(fuzz_counterexample_manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    if fuzz_counterexample_manifest is None:
        return {
            'path': FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
            'exists': False,
            'artifact_cid': None,
            'counterexample_count': 0,
        }
    return {
        'path': FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
        'exists': True,
        'model_cid': fuzz_counterexample_manifest.get('model_cid'),
        'artifact_cid': fuzz_counterexample_manifest.get('artifact_cid')
        or calculate_artifact_cid(fuzz_counterexample_manifest),
        'counterexample_count': fuzz_counterexample_manifest.get(
            'counterexample_count',
            len(fuzz_counterexample_manifest.get('counterexamples', [])),
        ),
    }


def _run_solver(command: Sequence[str], *, timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'command': list(command),
            'exit_code': None,
            'status': 'timeout',
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'output_retained': True,
        }
    except OSError as exc:
        return {
            'command': list(command),
            'exit_code': None,
            'status': 'failed',
            'stdout': '',
            'stderr': str(exc),
            'output_retained': True,
        }
    return {
        'command': list(command),
        'exit_code': completed.returncode,
        'status': 'pass' if completed.returncode == 0 else 'failed',
        'stdout': completed.stdout,
        'stderr': completed.stderr,
        'output_retained': completed.returncode != 0,
    }


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
        raise ValueError('Testnet protocol report must bind to a production-blocking Testnet model')


def _without_key(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {item_key: value for item_key, value in payload.items() if item_key != key}

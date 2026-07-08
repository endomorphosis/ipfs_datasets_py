"""Release-gate policy for crypto-exchange proof reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .ir.schema import evidence_review_statuses
from .reports.proof_report import (
    PROOF_STATUS_DISPROVED,
    PROOF_STATUS_NOT_MODELED,
    PROOF_STATUS_PROVED,
    PROOF_STATUS_UNKNOWN,
    PROOF_STATUSES,
)

ReleaseGate = Literal['blocking', 'high', 'medium', 'informational']

REVIEWED_EVIDENCE_STATUSES = frozenset({'human_reviewed', 'trusted_fixture'})
FAIL_CLOSED_STATUSES = frozenset(
    {
        PROOF_STATUS_DISPROVED,
        PROOF_STATUS_UNKNOWN,
        PROOF_STATUS_NOT_MODELED,
    }
)


@dataclass(frozen=True, slots=True)
class ReleasePolicyEntry:
    """Policy row for one formal security claim."""

    claim_id: str
    domain: str
    release_gate: ReleaseGate
    accepted_statuses: frozenset[str]
    fail_closed_statuses: frozenset[str]
    required_assumptions: tuple[str, ...]
    requires_reviewed_evidence: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'claim_id': self.claim_id,
            'domain': self.domain,
            'release_gate': self.release_gate,
            'accepted_statuses': sorted(self.accepted_statuses),
            'fail_closed_statuses': sorted(self.fail_closed_statuses),
            'required_assumptions': list(self.required_assumptions),
            'requires_reviewed_evidence': self.requires_reviewed_evidence,
            'rationale': self.rationale,
        }


def _claim_entry(
    *,
    claim_id: str,
    domain: str,
    release_gate: ReleaseGate,
    required_assumptions: tuple[str, ...],
    fail_closed_statuses: frozenset[str] = FAIL_CLOSED_STATUSES,
    requires_reviewed_evidence: bool = True,
    rationale: str,
) -> ReleasePolicyEntry:
    return ReleasePolicyEntry(
        claim_id=claim_id,
        domain=domain,
        release_gate=release_gate,
        accepted_statuses=frozenset({PROOF_STATUS_PROVED}),
        fail_closed_statuses=fail_closed_statuses,
        required_assumptions=required_assumptions,
        requires_reviewed_evidence=requires_reviewed_evidence,
        rationale=rationale,
    )


RELEASE_POLICY: tuple[ReleasePolicyEntry, ...] = (
    _claim_entry(
        claim_id='no_unauthorized_withdrawal',
        domain='withdrawals',
        release_gate='blocking',
        required_assumptions=('A3', 'A4', 'A5', 'A8'),
        rationale='A broadcast withdrawal without request, approval, nonce, reservation, and live wallet checks is a direct funds-loss condition.',
    ),
    _claim_entry(
        claim_id='no_over_reserved_internal_account',
        domain='ledger',
        release_gate='blocking',
        required_assumptions=('A4', 'A5'),
        rationale='Over-reservation means internal available balance can be spent more than once.',
    ),
    _claim_entry(
        claim_id='global_asset_conservation',
        domain='ledger',
        release_gate='blocking',
        required_assumptions=('A4', 'A10'),
        rationale='Customer liabilities exceeding custody plus pending settlement is a solvency failure.',
    ),
    _claim_entry(
        claim_id='no_deposit_before_finality',
        domain='deposits',
        release_gate='high',
        required_assumptions=('A6', 'A9'),
        rationale='Crediting deposits before finality exposes the exchange to reorg and false-credit losses.',
    ),
    _claim_entry(
        claim_id='no_signing_request_after_wallet_freeze',
        domain='hsm',
        release_gate='high',
        required_assumptions=('A3', 'A8'),
        rationale='A frozen wallet that can still request signatures defeats incident response controls.',
    ),
    _claim_entry(
        claim_id='capability_delegation_no_authority_increase',
        domain='capabilities',
        release_gate='high',
        required_assumptions=('A1', 'A7'),
        rationale='Delegation that amplifies authority can bypass administrative and custody controls.',
    ),
    _claim_entry(
        claim_id='revoked_capability_no_future_authorization',
        domain='capabilities',
        release_gate='high',
        required_assumptions=('A10',),
        rationale='Revoked capabilities authorizing later privileged actions breaks emergency revocation.',
    ),
    _claim_entry(
        claim_id='audit_event_exists_for_critical_transition',
        domain='audit',
        release_gate='medium',
        required_assumptions=('A10',),
        fail_closed_statuses=frozenset({PROOF_STATUS_DISPROVED}),
        requires_reviewed_evidence=False,
        rationale='Missing audit linkage is a release risk; a concrete disproof blocks release, while UNKNOWN or NOT_MODELED requires manual triage.',
    ),
)


def release_policy_entries() -> tuple[ReleasePolicyEntry, ...]:
    """Return the immutable default release policy."""

    return RELEASE_POLICY


def release_policy_for_claim(claim_id: str) -> ReleasePolicyEntry:
    """Return the policy row for *claim_id*."""

    for entry in RELEASE_POLICY:
        if entry.claim_id == claim_id:
            return entry
    raise KeyError(f'No release policy configured for claim: {claim_id}')


def _report_value(report: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(report, Mapping):
        return report.get(field_name, default)
    return getattr(report, field_name, default)


def _report_by_claim(reports: list[Any]) -> dict[str, Any]:
    by_claim: dict[str, Any] = {}
    for report in reports:
        claim_id = _report_value(report, 'claim_id')
        if isinstance(claim_id, str) and claim_id:
            by_claim[claim_id] = report
    return by_claim


def _gate_counts() -> dict[str, dict[str, int]]:
    return {
        gate: {
            'total': 0,
            'accepted': 0,
            'failed': 0,
            'attention': 0,
        }
        for gate in ('blocking', 'high', 'medium', 'informational')
    }


def evaluate_release_policy(
    reports: list[Any],
    *,
    require_reviewed_evidence: bool = True,
) -> dict[str, Any]:
    """Evaluate proof reports against the release-gate policy."""

    reports_by_claim = _report_by_claim(reports)
    gates = _gate_counts()
    failures: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []

    for entry in RELEASE_POLICY:
        gate_summary = gates[entry.release_gate]
        gate_summary['total'] += 1
        report = reports_by_claim.get(entry.claim_id)
        if report is None:
            reason = 'missing proof report'
            item = {
                'claim_id': entry.claim_id,
                'domain': entry.domain,
                'release_gate': entry.release_gate,
                'status': 'MISSING',
                'reasons': [reason],
            }
            if entry.release_gate in {'blocking', 'high'}:
                gate_summary['failed'] += 1
                failures.append(item)
            else:
                gate_summary['attention'] += 1
                attention.append(item)
            continue

        status = str(_report_value(report, 'status', '')).strip()
        reasons: list[str] = []
        accepted = status in entry.accepted_statuses
        failed = False
        needs_attention = False
        if accepted:
            pass
        elif status in entry.fail_closed_statuses:
            failed = True
            reasons.append(f'status {status} is fail-closed for {entry.release_gate} release gate')
        else:
            needs_attention = True
            reasons.append(f'status {status or "<empty>"} requires manual release triage')

        report_assumptions = set(str(item) for item in _report_value(report, 'assumptions', []) if str(item))
        missing_assumptions = sorted(set(entry.required_assumptions) - report_assumptions)
        if missing_assumptions:
            failed = True
            reasons.append(f'missing required assumption(s): {", ".join(missing_assumptions)}')

        evidence_refs = _report_value(report, 'evidence_refs', [])
        review_statuses = evidence_review_statuses(evidence_refs if isinstance(evidence_refs, list) else [])
        if (
            require_reviewed_evidence
            and entry.requires_reviewed_evidence
            and status == PROOF_STATUS_PROVED
            and not review_statuses.intersection(REVIEWED_EVIDENCE_STATUSES)
        ):
            failed = True
            reasons.append('proved claim lacks human_reviewed or trusted_fixture evidence')

        if failed:
            gate_summary['failed'] += 1
        elif accepted:
            gate_summary['accepted'] += 1
        elif needs_attention:
            gate_summary['attention'] += 1

        if reasons:
            item = {
                'claim_id': entry.claim_id,
                'domain': entry.domain,
                'release_gate': entry.release_gate,
                'status': status,
                'reasons': reasons,
            }
            if failed and entry.release_gate in {'blocking', 'high', 'medium'}:
                failures.append(item)
            else:
                attention.append(item)

    unknown_policy_reports = sorted(set(reports_by_claim) - {entry.claim_id for entry in RELEASE_POLICY})
    return {
        'release_ready': not failures,
        'require_reviewed_evidence': require_reviewed_evidence,
        'reviewed_evidence_statuses': sorted(REVIEWED_EVIDENCE_STATUSES),
        'policy': [entry.to_dict() for entry in RELEASE_POLICY],
        'gates': gates,
        'failures': failures,
        'attention': attention,
        'unknown_policy_reports': unknown_policy_reports,
    }


# ---------------------------------------------------------------------------
# PORTAL-CXTP-059: frozen proof-boundary and security decision policy
#
# This section defines the immutable set of release-consumer outcomes for
# formal security claims (prove, disprove, unknown, not-modeled,
# stale-evidence, missing-solver, blocked-production) and the authoritative
# builder for the checked-in security-decision-policy.json artifact and its
# companion policy document. Every release consumer MUST treat any
# non-``prove`` outcome for a blocking (or high-risk) claim as non-secure.
# ---------------------------------------------------------------------------

SECURITY_DECISION_POLICY_ARTIFACT = 'security_ir_artifacts/policies/security-decision-policy.json'
SECURITY_DECISION_POLICY_DOCUMENT = 'docs/security_verification/production_release_decision_policy.md'
SECURITY_DECISION_POLICY_SCHEMA_VERSION = 'crypto-exchange-security-decision-policy/v1'
SECURITY_DECISION_POLICY_EFFECTIVE_DATE = '2026-07-08'
SECURITY_DECISION_POLICY_TASK_ID = 'PORTAL-CXTP-059'
SECURITY_DECISION_POLICY_TITLE = 'Freeze proof-boundary and security decision policy'

DECISION_OUTCOME_PROVE = 'prove'
DECISION_OUTCOME_DISPROVE = 'disprove'
DECISION_OUTCOME_UNKNOWN = 'unknown'
DECISION_OUTCOME_NOT_MODELED = 'not-modeled'
DECISION_OUTCOME_STALE_EVIDENCE = 'stale-evidence'
DECISION_OUTCOME_MISSING_SOLVER = 'missing-solver'
DECISION_OUTCOME_BLOCKED_PRODUCTION = 'blocked-production'

STATUS_TO_DECISION_OUTCOME: dict[str, str] = {
    PROOF_STATUS_PROVED: DECISION_OUTCOME_PROVE,
    PROOF_STATUS_DISPROVED: DECISION_OUTCOME_DISPROVE,
    PROOF_STATUS_UNKNOWN: DECISION_OUTCOME_UNKNOWN,
    PROOF_STATUS_NOT_MODELED: DECISION_OUTCOME_NOT_MODELED,
}

_RELEASE_GATE_LABEL: dict[str, str] = {
    'blocking': 'blocking',
    'high': 'high-risk',
    'medium': 'medium-risk',
    'informational': 'informational',
}


@dataclass(frozen=True, slots=True)
class SecurityDecisionOutcome:
    """A single frozen release-consumer outcome for a formal security claim."""

    outcome: str
    definition: str
    source_signals: tuple[str, ...]
    secure_for_blocking_claims: bool
    production_release_effect: str
    required_consumer_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'outcome': self.outcome,
            'definition': self.definition,
            'source_signals': list(self.source_signals),
            'secure_for_blocking_claims': self.secure_for_blocking_claims,
            'production_release_effect': self.production_release_effect,
            'required_consumer_action': self.required_consumer_action,
        }


SECURITY_DECISION_OUTCOMES: tuple[SecurityDecisionOutcome, ...] = (
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_PROVE,
        definition=(
            'The claim is modeled, the authoritative solver returned a proof-producing success '
            'result, required assumptions and evidence are current, and all consumer validation '
            'checks pass.'
        ),
        source_signals=('PROVED',),
        secure_for_blocking_claims=True,
        production_release_effect='eligible-for-acceptance',
        required_consumer_action=(
            'May treat a blocking claim as secure only after validating model binding, '
            'assumptions, reviewed evidence, receipt or signature policy, solver allowlist, and '
            'release packet freshness.'
        ),
    ),
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_DISPROVE,
        definition='The solver found a satisfiable counterexample to the claim.',
        source_signals=('DISPROVED', 'counterexample-present'),
        secure_for_blocking_claims=False,
        production_release_effect='blocked-production',
        required_consumer_action=(
            'Reject the release and preserve the counterexample as blocking security evidence.'
        ),
    ),
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_UNKNOWN,
        definition=(
            'The prover did not establish the claim and did not return a concrete counterexample '
            'that is accepted as a disproof.'
        ),
        source_signals=('UNKNOWN', 'timeout', 'unsupported-theory', 'solver-unknown'),
        secure_for_blocking_claims=False,
        production_release_effect='blocked-production',
        required_consumer_action=(
            'Reject blocking claims; do not downgrade unknown to warning or manual approval.'
        ),
    ),
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_NOT_MODELED,
        definition='The production IR does not model the claim, domain, or facts required to evaluate it.',
        source_signals=('NOT_MODELED', 'missing-domain', 'missing-claim-model'),
        secure_for_blocking_claims=False,
        production_release_effect='blocked-production',
        required_consumer_action=(
            'Reject blocking claims until the production IR or formal claim scope is updated.'
        ),
    ),
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_STALE_EVIDENCE,
        definition=(
            'A required assumption, source fact, model CID, environment profile, or reviewed '
            'evidence item is missing, expired, ownerless, unevidenced, unaccepted, or no longer '
            'bound to the release packet.'
        ),
        source_signals=(
            'assumption-stale',
            'evidence-expired',
            'missing-review',
            'unaccepted-assumption',
        ),
        secure_for_blocking_claims=False,
        production_release_effect='blocked-production',
        required_consumer_action=(
            'Reject blocking claims until evidence is refreshed and accepted by the consumer.'
        ),
    ),
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_MISSING_SOLVER,
        definition=(
            'A required prover, compiler, runtime, or differential solver dependency is missing '
            'or unusable for the release gate.'
        ),
        source_signals=('required-solver-missing', 'solver-unavailable', 'dependency-blocker'),
        secure_for_blocking_claims=False,
        production_release_effect='blocked-production',
        required_consumer_action=(
            'Reject proof acceptance until the dependency probe reports no required blockers.'
        ),
    ),
    SecurityDecisionOutcome(
        outcome=DECISION_OUTCOME_BLOCKED_PRODUCTION,
        definition=(
            'The aggregate release decision when any blocking claim is not prove or when a '
            'release-packet gate fails closed.'
        ),
        source_signals=(
            'release-gate-failure',
            'runtime-counterexample',
            'receipt-validation-failure',
            'non-proved-blocking-claim',
        ),
        secure_for_blocking_claims=False,
        production_release_effect='blocked-production',
        required_consumer_action='Block deployment and report a non-secure production decision.',
    ),
)

_SECURITY_DECISION_OUTCOMES_BY_ID: dict[str, SecurityDecisionOutcome] = {
    outcome.outcome: outcome for outcome in SECURITY_DECISION_OUTCOMES
}

NON_SECURE_BLOCKING_OUTCOMES: frozenset[str] = frozenset(
    outcome.outcome
    for outcome in SECURITY_DECISION_OUTCOMES
    if not outcome.secure_for_blocking_claims
)


def security_decision_outcomes() -> tuple[SecurityDecisionOutcome, ...]:
    """Return the frozen tuple of release-consumer security decision outcomes."""

    return SECURITY_DECISION_OUTCOMES


def blocking_claim_is_secure_outcome(outcome: str) -> bool:
    """Return whether *outcome* may be treated as secure for a blocking claim.

    Only the ``prove`` outcome is secure for a blocking (or high-risk) claim.
    Any unrecognized outcome fails closed (is treated as non-secure).
    """

    entry = _SECURITY_DECISION_OUTCOMES_BY_ID.get(outcome)
    if entry is None:
        return False
    return entry.secure_for_blocking_claims


def decision_outcome_for_proof_status(status: str) -> str:
    """Map a raw :class:`ProofReport` ``status`` to its consumer decision outcome."""

    try:
        return STATUS_TO_DECISION_OUTCOME[status]
    except KeyError as exc:
        raise ValueError(f'unsupported proof status for decision outcome: {status!r}') from exc


def classify_release_consumer_outcome(
    report: Any,
    *,
    release_gate: ReleaseGate = 'blocking',
    evidence_current: bool = True,
    solver_available: bool = True,
) -> dict[str, Any]:
    """Classify a proof report into a frozen security decision outcome.

    Release consumers call this to decide whether a claim's proof report may
    be treated as secure. Checks are evaluated fail-closed and in priority
    order: a missing report is always ``blocked-production``; an unavailable
    required solver dependency is always ``missing-solver``; stale or
    unaccepted evidence is always ``stale-evidence``; otherwise the outcome is
    derived from the proof report's ``status``. Only the ``prove`` outcome is
    ever secure for a blocking or high-risk claim.
    """

    reasons: list[str] = []

    if report is None:
        outcome = DECISION_OUTCOME_BLOCKED_PRODUCTION
        reasons.append('no proof report is available for the claim')
    elif not solver_available:
        outcome = DECISION_OUTCOME_MISSING_SOLVER
        reasons.append('a required solver dependency is unavailable for the release gate')
    elif not evidence_current:
        outcome = DECISION_OUTCOME_STALE_EVIDENCE
        reasons.append('required assumption, evidence, or release-packet binding is not current')
    else:
        status = str(_report_value(report, 'status', ''))
        outcome = decision_outcome_for_proof_status(status)

    secure = blocking_claim_is_secure_outcome(outcome)
    consumer_result = 'secure' if secure else 'non-secure'
    if not secure:
        gate_label = _RELEASE_GATE_LABEL.get(release_gate, release_gate)
        reasons.append(
            f'release consumers must treat non-proved {gate_label} claims as non-secure'
        )

    return {
        'outcome': outcome,
        'release_gate': release_gate,
        'secure_for_release': secure,
        'consumer_result': consumer_result,
        'reasons': reasons,
    }


def _claim_ids_for_gate(release_gate: ReleaseGate) -> list[str]:
    return [entry.claim_id for entry in RELEASE_POLICY if entry.release_gate == release_gate]


def build_security_decision_policy() -> dict[str, Any]:
    """Build the authoritative, frozen security decision policy document.

    The return value is the single source of truth for the checked-in
    ``security-decision-policy.json`` release-gate artifact referenced by
    :data:`SECURITY_DECISION_POLICY_ARTIFACT`.
    """

    proof_boundary = {
        'required_domains': sorted({entry.domain for entry in RELEASE_POLICY}),
        'blocking_claims': _claim_ids_for_gate('blocking'),
        'high_risk_claims': _claim_ids_for_gate('high'),
        'secure_blocking_outcome': DECISION_OUTCOME_PROVE,
        'non_secure_blocking_outcomes': sorted(NON_SECURE_BLOCKING_OUTCOMES),
        'authoritative_report_statuses': sorted(PROOF_STATUSES),
        'required_release_claims': [entry.to_dict() for entry in RELEASE_POLICY],
        'required_input_artifacts': [
            'production SecurityModelIR and model CID',
            'proof report JSON for every required claim',
            'proof receipt or trusted signature validation output',
            'accepted assumptions file',
            'current assumption and evidence registry',
            'solver dependency probe',
            'production environment profile',
            'disproof suite report and counterexample vectors',
            'runtime monitor report for the release window',
        ],
        'out_of_scope': [
            'claims absent from the production SecurityModelIR',
            'optional prover coverage not present in the solver dependency probe',
            'runtime behavior outside collected release-window traces',
            'cryptographic primitive breakage beyond listed assumptions',
        ],
    }

    return {
        'schema_version': SECURITY_DECISION_POLICY_SCHEMA_VERSION,
        'task_id': SECURITY_DECISION_POLICY_TASK_ID,
        'title': SECURITY_DECISION_POLICY_TITLE,
        'effective_date': SECURITY_DECISION_POLICY_EFFECTIVE_DATE,
        'artifact_path': SECURITY_DECISION_POLICY_ARTIFACT,
        'policy_document': SECURITY_DECISION_POLICY_DOCUMENT,
        'scope': (
            'Crypto-exchange wallet and exchange production release consumers that evaluate '
            'proof reports, proof receipts, assumption evidence, solver dependency probes, '
            'runtime monitor evidence, and release packets.'
        ),
        'status_to_outcome': dict(STATUS_TO_DECISION_OUTCOME),
        'outcomes': [outcome.to_dict() for outcome in SECURITY_DECISION_OUTCOMES],
        'proof_boundary': proof_boundary,
        'default_consumer_rule': (
            'Only outcome prove may be consumed as secure for a blocking claim; every '
            'non-proved blocking claim is non-secure and blocks production.'
        ),
        'consumer_requirements': [
            'Release consumers must fail closed by default.',
            'Release consumers must not infer security from missing proof reports.',
            'Release consumers must not accept UNKNOWN, NOT_MODELED, DISPROVED, stale evidence, '
            'or missing solver states for blocking claims.',
            'Release consumers must report blocked-production when any blocking claim is '
            'non-proved.',
            'Dashboards may display non-proved states but must label them non-secure for '
            'production release.',
        ],
        'release_readiness_rule': {
            'accepted': [
                'every blocking claim outcome is prove',
                'every high-risk claim outcome is prove',
                'required assumptions are owned, evidenced, accepted, and current',
                'required solver dependencies are present',
                'proof receipts or trusted signatures validate against the release packet',
                'disproof and runtime monitor gates have no unexplained blockers',
            ],
            'blocked': [
                'any blocking claim outcome is not prove',
                'any required high-risk claim outcome is not prove',
                'any stale-evidence outcome affects a required claim or release packet artifact',
                'any missing-solver outcome affects required proof acceptance',
                'any proof receipt, model CID, report CID, or environment binding fails '
                'validation',
            ],
        },
        'maintenance_triggers': [
            'claim severity changes',
            'new blocking or high-risk claim',
            'required assumption changes',
            'solver allowlist or dependency changes',
            'proof receipt validation changes',
            'runtime monitor release-gate changes',
        ],
    }


def _require_keys(payload: Mapping[str, Any], keys: set[str], *, where: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise ValueError(f'{where} is missing required key(s): {", ".join(missing)}')
    unknown = sorted(set(payload) - keys)
    if unknown:
        raise ValueError(f'{where} has unexpected key(s): {", ".join(unknown)}')


_TOP_LEVEL_POLICY_KEYS = {
    'schema_version',
    'task_id',
    'title',
    'effective_date',
    'artifact_path',
    'policy_document',
    'scope',
    'status_to_outcome',
    'outcomes',
    'proof_boundary',
    'default_consumer_rule',
    'consumer_requirements',
    'release_readiness_rule',
    'maintenance_triggers',
}

_OUTCOME_KEYS = {
    'outcome',
    'definition',
    'source_signals',
    'secure_for_blocking_claims',
    'production_release_effect',
    'required_consumer_action',
}

_PROOF_BOUNDARY_KEYS = {
    'required_domains',
    'blocking_claims',
    'high_risk_claims',
    'secure_blocking_outcome',
    'non_secure_blocking_outcomes',
    'authoritative_report_statuses',
    'required_release_claims',
    'required_input_artifacts',
    'out_of_scope',
}

_REQUIRED_RELEASE_CLAIM_KEYS = {
    'claim_id',
    'domain',
    'release_gate',
    'accepted_statuses',
    'fail_closed_statuses',
    'required_assumptions',
    'requires_reviewed_evidence',
    'rationale',
}

_EXPECTED_OUTCOME_IDS = frozenset(outcome.outcome for outcome in SECURITY_DECISION_OUTCOMES)


def validate_security_decision_policy(policy: Mapping[str, Any]) -> None:
    """Validate that *policy* is a well-formed, internally consistent decision policy.

    Raises :class:`ValueError` if the policy document is missing required
    fields, defines an outcome set other than the frozen seven outcomes, or
    allows any outcome other than ``prove`` to be secure for a blocking claim.
    """

    if not isinstance(policy, Mapping):
        raise ValueError('security decision policy must be a mapping')

    _require_keys(policy, _TOP_LEVEL_POLICY_KEYS, where='security decision policy')

    if policy.get('artifact_path') != SECURITY_DECISION_POLICY_ARTIFACT:
        raise ValueError('security decision policy artifact_path does not match the frozen artifact path')
    if policy.get('policy_document') != SECURITY_DECISION_POLICY_DOCUMENT:
        raise ValueError('security decision policy policy_document does not match the frozen policy document path')

    outcomes = policy.get('outcomes')
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError('security decision policy outcomes must be a non-empty list')

    outcome_ids: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            raise ValueError('each security decision outcome must be a mapping')
        _require_keys(outcome, _OUTCOME_KEYS, where='security decision outcome')
        outcome_id = outcome.get('outcome')
        if not isinstance(outcome_id, str) or not outcome_id:
            raise ValueError('security decision outcome must declare a non-empty outcome id')
        outcome_ids.add(outcome_id)
        secure = outcome.get('secure_for_blocking_claims')
        if not isinstance(secure, bool):
            raise ValueError(f'outcome {outcome_id} secure_for_blocking_claims must be a boolean')
        if outcome_id == DECISION_OUTCOME_PROVE:
            if secure is not True:
                raise ValueError('the prove outcome must be secure for blocking claims')
        elif secure is not False:
            raise ValueError(f'non-prove outcome {outcome_id} must not be secure for blocking claims')
        if secure is False and outcome.get('production_release_effect') != DECISION_OUTCOME_BLOCKED_PRODUCTION:
            raise ValueError(
                f'non-secure outcome {outcome_id} must have production_release_effect == '
                f'{DECISION_OUTCOME_BLOCKED_PRODUCTION!r}'
            )

    if outcome_ids != set(_EXPECTED_OUTCOME_IDS):
        raise ValueError(
            'security decision policy outcomes must be exactly '
            f'{sorted(_EXPECTED_OUTCOME_IDS)}, found {sorted(outcome_ids)}'
        )

    proof_boundary = policy.get('proof_boundary')
    if not isinstance(proof_boundary, Mapping):
        raise ValueError('security decision policy proof_boundary must be a mapping')
    _require_keys(proof_boundary, _PROOF_BOUNDARY_KEYS, where='proof_boundary')

    if proof_boundary.get('secure_blocking_outcome') != DECISION_OUTCOME_PROVE:
        raise ValueError('proof_boundary.secure_blocking_outcome must be prove')

    non_secure_outcomes = proof_boundary.get('non_secure_blocking_outcomes')
    if not isinstance(non_secure_outcomes, list) or set(non_secure_outcomes) != (
        outcome_ids - {DECISION_OUTCOME_PROVE}
    ):
        raise ValueError('proof_boundary.non_secure_blocking_outcomes must list every non-prove outcome')

    blocking_claims = proof_boundary.get('blocking_claims')
    high_risk_claims = proof_boundary.get('high_risk_claims')
    if not isinstance(blocking_claims, list) or not isinstance(high_risk_claims, list):
        raise ValueError('proof_boundary blocking_claims and high_risk_claims must be lists')

    release_claims = proof_boundary.get('required_release_claims')
    if not isinstance(release_claims, list) or not release_claims:
        raise ValueError('proof_boundary.required_release_claims must be a non-empty list')

    seen_claim_ids: set[str] = set()
    for claim in release_claims:
        if not isinstance(claim, Mapping):
            raise ValueError('each required release claim must be a mapping')
        _require_keys(claim, _REQUIRED_RELEASE_CLAIM_KEYS, where='required release claim')
        claim_id = claim.get('claim_id')
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError('required release claim must declare a non-empty claim_id')
        seen_claim_ids.add(claim_id)

    if set(blocking_claims) - seen_claim_ids:
        raise ValueError('proof_boundary.blocking_claims references unknown claim id(s)')
    if set(high_risk_claims) - seen_claim_ids:
        raise ValueError('proof_boundary.high_risk_claims references unknown claim id(s)')

    for claim in release_claims:
        if claim['release_gate'] == 'blocking' and claim['claim_id'] not in blocking_claims:
            raise ValueError(f'blocking claim {claim["claim_id"]} missing from proof_boundary.blocking_claims')
        if claim['release_gate'] == 'high' and claim['claim_id'] not in high_risk_claims:
            raise ValueError(f'high-risk claim {claim["claim_id"]} missing from proof_boundary.high_risk_claims')

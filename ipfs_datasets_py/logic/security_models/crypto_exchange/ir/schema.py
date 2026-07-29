"""Schema and validation helpers for the canonical security IR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, NotRequired, Required, TypedDict


class AssumptionEntry(TypedDict, total=False):
    id: str
    description: str
    custom: bool
    owner: str
    evidence_refs: list['EvidenceRef']
    last_reviewed_at: str
    evidence_expires_at: str


class EvidenceRef(TypedDict, total=False):
    """Evidence references require kind/path/review_status; remaining fields are optional."""

    kind: Required[str]
    path: Required[str]
    review_status: Required[str]
    line_start: NotRequired[int]
    line_end: NotRequired[int]
    sha256: NotRequired[str]
    notes: NotRequired[str]


class ClaimEntry(TypedDict, total=False):
    """A declarative security claim bound to a modeled security domain."""

    id: Required[str]
    description: Required[str]
    domain: Required[str]
    severity: NotRequired[str]
    required_assumptions: NotRequired[list[str]]
    evidence_refs: NotRequired[list[EvidenceRef]]
    custom: NotRequired[bool]


class ProofObligationEntry(TypedDict, total=False):
    """A prover-bound obligation that a claim must be discharged for a model."""

    id: Required[str]
    claim_id: Required[str]
    prover: Required[str]
    status: Required[str]
    model_cid: NotRequired[str]
    report_cid: NotRequired[str]
    evidence_refs: NotRequired[list[EvidenceRef]]


class DisproofVectorEntry(TypedDict, total=False):
    """A mutation/attack/counterexample search bound to a claim."""

    id: Required[str]
    claim_id: Required[str]
    tactic: Required[str]
    status: Required[str]
    counterexample: NotRequired[dict[str, Any]]
    evidence_refs: NotRequired[list[EvidenceRef]]


class RuntimeTraceEntry(TypedDict, total=False):
    """A runtime/e2e trace checked for conformance against the formal model."""

    id: Required[str]
    description: Required[str]
    domain: NotRequired[str]
    events: NotRequired[list[str]]
    conformance_status: NotRequired[str]
    evidence_refs: NotRequired[list[EvidenceRef]]


class SolverResultEntry(TypedDict, total=False):
    """A raw solver invocation result bound to a claim and proof obligation."""

    id: Required[str]
    claim_id: Required[str]
    solver_name: Required[str]
    result: Required[str]
    solver_version: NotRequired[str]
    report_cid: NotRequired[str]
    evidence_refs: NotRequired[list[EvidenceRef]]


# Stable bounded-security assumption identifiers used by proof reports and the
# default threat-model IR payload.
DEFAULT_ASSUMPTION_REGISTRY = {
    'A1': 'cryptographic primitives are unbroken',
    'A2': 'private keys are generated with sufficient entropy',
    'A3': 'signing code signs only approved canonical transaction bytes',
    'A4': 'database commits are serializable',
    'A5': 'nonce reservation is atomic',
    'A6': 'blockchain finality threshold k is sufficient',
    'A7': 'admin identities are not all compromised',
    'A8': 'HSM/key manager obeys its interface contract',
    'A9': 'external RPC providers may lie/delay/censor within modeled bounds',
    'A10': 'audit logs are append-only or tamper-evident',
}

DEFAULT_ASSUMPTION_OWNERS = {
    'A1': 'security-architecture',
    'A2': 'wallet-key-management',
    'A3': 'wallet-transaction-signing',
    'A4': 'exchange-ledger-database',
    'A5': 'withdrawal-nonce-service',
    'A6': 'chain-risk-management',
    'A7': 'security-governance',
    'A8': 'custody-platform',
    'A9': 'blockchain-infrastructure',
    'A10': 'audit-compliance',
}
DEFAULT_ASSUMPTION_LAST_REVIEWED_AT = '2026-07-07T00:00:00Z'
DEFAULT_ASSUMPTION_EVIDENCE_EXPIRES_AT = '2027-01-01T00:00:00Z'


def _assumption_evidence_ref(assumption_id: str) -> EvidenceRef:
    return {
        'kind': 'manual_review',
        'path': 'docs/security_verification/threat_model.md',
        'review_status': 'trusted_fixture',
        'notes': f'Built-in fixture evidence for bounded assumption {assumption_id}.',
    }


DEFAULT_THREAT_MODEL_ASSUMPTIONS: list[AssumptionEntry] = [
    {
        'id': assumption_id,
        'description': description,
        'owner': DEFAULT_ASSUMPTION_OWNERS[assumption_id],
        'evidence_refs': [_assumption_evidence_ref(assumption_id)],
        'last_reviewed_at': DEFAULT_ASSUMPTION_LAST_REVIEWED_AT,
        'evidence_expires_at': DEFAULT_ASSUMPTION_EVIDENCE_EXPIRES_AT,
    }
    for assumption_id, description in sorted(
        DEFAULT_ASSUMPTION_REGISTRY.items(),
        key=lambda item: int(item[0][1:]),
    )
]

REQUIRED_SEQUENCE_FIELDS = (
    'entities',
    'assets',
    'wallets',
    'accounts',
    'roles',
    'principals',
    'capabilities',
    'policies',
    'events',
    'state_machines',
    'invariants',
    'claims',
    'proof_obligations',
    'disproof_vectors',
    'runtime_traces',
    'solver_results',
    'assumptions',
    'prover_targets',
)

# Security domains covered by production exchange claims (see
# ``prove_all.CLAIM_DOMAINS``) and by the Xaman React Native wallet corpus
# (see ``extractors.xaman_source_extractor.XamanSourceExtractor._security_category``).
# Both sets are duplicated here (rather than imported) to avoid a circular
# import between ``ir.schema`` and the higher-level claim/extractor modules
# that themselves import from ``ir.schema``. Coverage tests assert the two
# stay in sync with these constants.
PRODUCTION_SECURITY_DOMAINS = frozenset(
    {
        'audit',
        'capabilities',
        'deposits',
        'hsm',
        'ledger',
        'withdrawals',
    }
)
XAMAN_SECURITY_DOMAINS = frozenset(
    {
        'auth_component',
        'e2e_flow',
        'ledger',
        'payload',
        'service',
        'store',
        'vault',
    }
)
KNOWN_SECURITY_DOMAINS = PRODUCTION_SECURITY_DOMAINS | XAMAN_SECURITY_DOMAINS

# Proof-obligation / solver-result / disproof-vector status vocabularies.
# ``PROOF_OBLIGATION_STATUSES`` intentionally mirrors
# ``reports.proof_report.PROOF_STATUSES`` (duplicated for the same
# circular-import reason as the domain constants above).
PROOF_OBLIGATION_STATUSES = frozenset({'PROVED', 'DISPROVED', 'UNKNOWN', 'NOT_MODELED'})
DISPROOF_VECTOR_STATUSES = frozenset({'DISPROVED', 'SURVIVED', 'UNKNOWN'})
SOLVER_RESULT_VALUES = frozenset({'sat', 'unsat', 'unknown', 'not-modeled', 'error', 'timeout'})
CLAIM_SEVERITIES = frozenset({'blocking', 'high', 'medium', 'low'})

IMPLEMENTED_PROVER_TARGETS = {'z3'}
KNOWN_DISABLED_PROVER_TARGETS = {
    'coq',
    'cvc5',
    'datalog',
    'ergoai',
    'hyperltl',
    'lean',
    'proverif',
    'tamarin',
    'tla',
}
ALLOWED_PROVER_TARGETS = IMPLEMENTED_PROVER_TARGETS | KNOWN_DISABLED_PROVER_TARGETS
KNOWN_EVENT_TYPES = {
    'withdrawal_requested',
    'withdrawal_approved',
    'withdrawal_broadcast',
    'withdrawal_cancelled',
    'deposit_observed',
    'deposit_finalized',
    'deposit_credited',
    'wallet_frozen',
    'wallet_unfrozen',
    'signing_request',
    'capability_revoked',
    'capability_reinstated',
    'privileged_action',
    'audit_logged',
    'balance_reserved',
    'balance_released',
    'nonce_reserved',
    'nonce_consumed',
    'chain_reorg_detected',
}
EVIDENCE_KINDS = {
    'source_code',
    'openapi',
    'policy_doc',
    'audit_log',
    'manual_review',
    'test_fixture',
}
EVIDENCE_REVIEW_STATUSES = {
    'heuristic',
    'machine_extracted',
    'human_reviewed',
    'trusted_fixture',
}
WALLET_STATUSES = {'active', 'frozen', 'disabled', 'rotating', 'retired'}
NON_NEGATIVE_INTEGER_FIELDS = {
    'amount',
    'balance',
    'block_height',
    'confirmations',
    'finality_threshold',
    'known_losses',
    'liabilities',
    'pending_settlements',
    'reservation',
}
NON_NEGATIVE_INTEGER_SEQUENCE_FIELDS = {
    'reservation_requests',
    'reservations',
}


@dataclass(slots=True)
class SecurityModelIR:
    """Language-neutral exchange security model.

    The structure is deliberately JSON-friendly so it can be content-addressed,
    compiled to multiple prover backends, and later consumed by TypeScript/WASM.
    """

    schema_version: str
    model_id: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    wallets: list[dict[str, Any]] = field(default_factory=list)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)
    principals: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    state_machines: list[dict[str, Any]] = field(default_factory=list)
    invariants: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    proof_obligations: list[dict[str, Any]] = field(default_factory=list)
    disproof_vectors: list[dict[str, Any]] = field(default_factory=list)
    runtime_traces: list[dict[str, Any]] = field(default_factory=list)
    solver_results: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[AssumptionEntry | str] = field(default_factory=lambda: list(DEFAULT_THREAT_MODEL_ASSUMPTIONS))
    prover_targets: list[str] = field(default_factory=lambda: ['z3'])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'SecurityModelIR':
        allowed = {item.name for item in fields(cls)}
        validated = validate_ir_payload(data, strict=False)
        payload = {name: validated[name] for name in allowed if name in validated}
        return cls(**payload)

    @classmethod
    def from_untrusted_dict(cls, data: Mapping[str, Any], *, strict: bool = True) -> 'SecurityModelIR':
        allowed = {item.name for item in fields(cls)}
        validated = validate_ir_payload(data, strict=strict)
        payload = {name: validated[name] for name in allowed if name in validated}
        return cls(**payload)


REQUIRED_TOP_LEVEL_FIELDS = tuple(item.name for item in fields(SecurityModelIR))
RECORD_COLLECTION_FIELDS = tuple(
    field_name for field_name in REQUIRED_SEQUENCE_FIELDS if field_name not in {'assumptions', 'prover_targets'}
)


_ID_FIELDS = {
    'entities': 'entity',
    'assets': 'asset',
    'wallets': 'wallet',
    'accounts': 'account',
    'policies': 'policy',
    'roles': 'role',
    'principals': 'principal',
    'capabilities': 'capability',
    'events': 'event',
    'state_machines': 'state machine',
    'invariants': 'invariant',
    'claims': 'claim',
    'proof_obligations': 'proof obligation',
    'disproof_vectors': 'disproof vector',
    'runtime_traces': 'runtime trace',
    'solver_results': 'solver result',
}


def as_security_model_ir(model: SecurityModelIR | Mapping[str, Any]) -> SecurityModelIR:
    """Return *model* as a validated :class:`SecurityModelIR`."""

    if isinstance(model, SecurityModelIR):
        return model
    if isinstance(model, Mapping):
        return SecurityModelIR.from_dict(model)
    raise TypeError(f'Unsupported security model type: {type(model)!r}')



def make_evidence_ref(
    *,
    kind: str,
    path: str,
    review_status: str,
    line_start: int | None = None,
    line_end: int | None = None,
    sha256: str | None = None,
    notes: str | None = None,
) -> EvidenceRef:
    """Return a JSON-friendly evidence reference."""

    reference: EvidenceRef = {
        'kind': kind,
        'path': path,
        'review_status': review_status,
    }
    if line_start is not None:
        reference['line_start'] = line_start
    if line_end is not None:
        reference['line_end'] = line_end
    if sha256 is not None:
        reference['sha256'] = sha256
    if notes:
        reference['notes'] = notes
    return reference



def collect_evidence_refs(*records: Mapping[str, Any] | None) -> list[EvidenceRef]:
    """Return de-duplicated evidence references harvested from *records*."""

    refs: list[EvidenceRef] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        for ref in record.get('evidence_refs', []):
            if not isinstance(ref, Mapping):
                continue
            normalized = dict(ref)
            key = tuple(sorted(normalized.items()))
            if key in seen:
                continue
            refs.append(normalized)
            seen.add(key)
    return refs



def evidence_review_statuses(evidence_refs: list[EvidenceRef] | list[Mapping[str, Any]]) -> set[str]:
    """Return normalized review-status labels seen in *evidence_refs*."""

    return {
        str(reference.get('review_status', '')).strip().lower()
        for reference in evidence_refs
        if isinstance(reference, Mapping) and reference.get('review_status')
    }



def _ensure_sequence_field(model_dict: Mapping[str, Any], field_name: str) -> None:
    value = model_dict.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f'{field_name} must be a list in SecurityModelIR')


def validate_ir_payload(payload: Mapping[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Validate a raw JSON-like SecurityModelIR payload before dataclass construction.

    Args:
        payload: JSON-decoded security-model data to validate.
        strict: When ``True``, require every top-level IR field to be present and
            reject unknown top-level keys. When ``False``, preserve compatibility
            with internal fixtures by allowing omitted defaulted fields while still
            validating payload shape for present fields.

    Returns:
        A shallow ``dict`` copy of *payload* suitable for ``SecurityModelIR.from_dict``.

    Raises:
        ValueError: If *payload* is not a mapping, required fields are missing,
            unknown top-level fields are present in strict mode, or any validated
            top-level collection/metadata entry has the wrong shape.
    """

    if not isinstance(payload, Mapping):
        raise ValueError('SecurityModelIR payload must be a mapping')

    normalized = dict(payload)
    allowed = {item.name for item in fields(SecurityModelIR)}
    required = set(REQUIRED_TOP_LEVEL_FIELDS if strict else ('schema_version', 'model_id'))
    unknown = sorted(set(normalized) - allowed)
    if strict and unknown:
        raise ValueError(f'Unknown top-level SecurityModelIR field(s): {", ".join(unknown)}')
    missing = sorted(field_name for field_name in required if field_name not in normalized)
    if missing:
        raise ValueError(f'Missing required top-level SecurityModelIR field(s): {", ".join(missing)}')
    for field_name in ('schema_version', 'model_id'):
        value = normalized.get(field_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f'{field_name} must be a non-empty string')
    metadata = normalized.get('metadata', {} if not strict else None)
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ValueError('metadata must be a dict in SecurityModelIR payload')
    for field_name in REQUIRED_SEQUENCE_FIELDS:
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if not isinstance(value, list):
            raise ValueError(f'{field_name} must be a list in SecurityModelIR payload')
        if field_name in RECORD_COLLECTION_FIELDS:
            for index, item in enumerate(value):
                if not isinstance(item, Mapping):
                    raise ValueError(f'{field_name}[{index}] must be a dict in SecurityModelIR payload')
        elif field_name == 'assumptions':
            for index, item in enumerate(value):
                if not isinstance(item, (str, Mapping)):
                    raise ValueError(f'assumptions[{index}] must be a string or dict in SecurityModelIR payload')
        elif field_name == 'prover_targets':
            for index, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(f'prover_targets[{index}] must be a non-empty string in SecurityModelIR payload')
    return normalized



def _parse_iso_datetime(field_name: str, value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field_name} must be a non-empty ISO timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field_name} must be an ISO timestamp') from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_assumption_entry(assumption: AssumptionEntry | str) -> None:
    """Validate an assumption identifier or structured ``{id, description}`` entry."""

    if isinstance(assumption, str):
        if not assumption.strip():
            raise ValueError('assumption identifiers must be non-empty strings')
        if assumption not in DEFAULT_ASSUMPTION_REGISTRY:
            raise ValueError(f'Unknown assumption id: {assumption}')
        return
    if isinstance(assumption, Mapping):
        assumption_id = assumption.get('id')
        description = assumption.get('description')
        if not isinstance(assumption_id, str) or not assumption_id.strip():
            raise ValueError('assumption mappings must include a non-empty id')
        if not isinstance(description, str) or not description.strip():
            raise ValueError('assumption mappings must include a non-empty description')
        if 'owner' in assumption and (not isinstance(assumption['owner'], str) or not assumption['owner'].strip()):
            raise ValueError('assumption owner must be a non-empty string when present')
        if 'evidence_refs' in assumption:
            evidence_refs = assumption['evidence_refs']
            if not isinstance(evidence_refs, list):
                raise ValueError('assumption evidence_refs must be a list when present')
            for reference in evidence_refs:
                if not isinstance(reference, Mapping):
                    raise ValueError('assumption evidence_refs entries must be mappings')
                _validate_evidence_ref(reference)
        last_reviewed_at = assumption.get('last_reviewed_at')
        evidence_expires_at = assumption.get('evidence_expires_at')
        if last_reviewed_at is not None:
            _parse_iso_datetime('assumption last_reviewed_at', last_reviewed_at)
        if evidence_expires_at is not None:
            _parse_iso_datetime('assumption evidence_expires_at', evidence_expires_at)
        if last_reviewed_at is not None and evidence_expires_at is not None:
            if _parse_iso_datetime('assumption evidence_expires_at', evidence_expires_at) < _parse_iso_datetime('assumption last_reviewed_at', last_reviewed_at):
                raise ValueError('assumption evidence_expires_at must be >= last_reviewed_at')
        if assumption_id in DEFAULT_ASSUMPTION_REGISTRY:
            return
        if not bool(assumption.get('custom', False)):
            raise ValueError(f'Unknown assumption id: {assumption_id}')
        return
    raise ValueError('assumptions must be strings or {id, description} mappings')



def _require_unique_ids(entries: list[dict[str, Any]], label: str) -> None:
    seen: set[str] = set()
    for entry in entries:
        entry_id = entry.get('id')
        if entry_id is None:
            continue
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError(f'Every {label} id must be a non-empty string')
        if entry_id in seen:
            raise ValueError(f'Duplicate {label} id: {entry_id}')
        seen.add(entry_id)



def _validate_non_negative_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{name} must be a non-negative integer')


def _validate_positive_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f'{name} must be a positive integer')



def _validate_numeric_fields(entries: list[dict[str, Any]], collection_name: str) -> None:
    for entry in entries:
        entry_id = entry.get('id', '<unknown>')
        for field_name in NON_NEGATIVE_INTEGER_FIELDS:
            if field_name in entry:
                _validate_non_negative_int(f'{collection_name}.{entry_id}.{field_name}', entry[field_name])
        for field_name in NON_NEGATIVE_INTEGER_SEQUENCE_FIELDS:
            if field_name not in entry:
                continue
            value = entry[field_name]
            if not isinstance(value, list):
                raise ValueError(f'{collection_name}.{entry_id}.{field_name} must be a list of non-negative integers')
            for index, item in enumerate(value):
                _validate_non_negative_int(f'{collection_name}.{entry_id}.{field_name}[{index}]', item)



def _validate_evidence_ref(reference: Mapping[str, Any]) -> None:
    if reference.get('kind') not in EVIDENCE_KINDS:
        raise ValueError(f"Unsupported evidence ref kind: {reference.get('kind')}")
    if not isinstance(reference.get('path'), str) or not reference['path'].strip():
        raise ValueError('evidence ref path must be a non-empty string')
    if reference.get('review_status') not in EVIDENCE_REVIEW_STATUSES:
        raise ValueError(f"Unsupported evidence review status: {reference.get('review_status')}")
    for key in ('line_start', 'line_end'):
        if key in reference:
            _validate_positive_int(f'evidence_refs.{key}', reference[key])
    if 'line_start' in reference and 'line_end' in reference and reference['line_end'] < reference['line_start']:
        raise ValueError('evidence ref line_end must be >= line_start')
    if 'sha256' in reference and (not isinstance(reference['sha256'], str) or not reference['sha256'].strip()):
        raise ValueError('evidence ref sha256 must be a non-empty string when present')



def _validate_record_evidence(records: list[dict[str, Any]], collection_name: str) -> None:
    for record in records:
        if 'evidence_refs' not in record:
            continue
        if not isinstance(record['evidence_refs'], list):
            raise ValueError(f'{collection_name}.{record.get("id", "<unknown>")}.evidence_refs must be a list')
        for reference in record['evidence_refs']:
            if not isinstance(reference, Mapping):
                raise ValueError(f'{collection_name}.{record.get("id", "<unknown>")}.evidence_refs entries must be mappings')
            _validate_evidence_ref(reference)



def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    ledger_totals = metadata.get('ledger_totals')
    if ledger_totals is not None:
        if not isinstance(ledger_totals, Mapping):
            raise ValueError('metadata.ledger_totals must be a mapping')
        for bucket_name in ('customer_liabilities', 'custody_assets', 'pending_settlements', 'known_losses'):
            bucket = ledger_totals.get(bucket_name, {})
            if not isinstance(bucket, Mapping):
                raise ValueError(f'metadata.ledger_totals.{bucket_name} must be a mapping')
            for asset_id, value in bucket.items():
                if not isinstance(asset_id, str) or not asset_id.strip():
                    raise ValueError(f'metadata.ledger_totals.{bucket_name} keys must be non-empty asset ids')
                _validate_non_negative_int(f'metadata.ledger_totals.{bucket_name}.{asset_id}', value)
    autoformalization = metadata.get('autoformalization')
    if not isinstance(autoformalization, Mapping):
        return
    if 'review_status' in autoformalization:
        review_status = autoformalization['review_status']
        if review_status not in EVIDENCE_REVIEW_STATUSES:
            raise ValueError(f'Unsupported autoformalization review status: {review_status}')
    evidence_refs = autoformalization.get('evidence_refs', [])
    if not isinstance(evidence_refs, list):
        raise ValueError('metadata.autoformalization.evidence_refs must be a list')
    for reference in evidence_refs:
        if not isinstance(reference, Mapping):
            raise ValueError('metadata.autoformalization.evidence_refs entries must be mappings')
        _validate_evidence_ref(reference)


def _validate_policy_records(policies: list[dict[str, Any]]) -> None:
    seen_names: set[str] = set()
    for policy in policies:
        policy_id = policy.get('id', '<unknown>')
        name = policy.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'policy {policy_id} must include a non-empty name')
        if name in seen_names:
            raise ValueError(f'Duplicate policy name: {name}')
        seen_names.add(name)
        if 'enabled' in policy and not isinstance(policy['enabled'], bool):
            raise ValueError(f'policy {policy_id}.enabled must be a bool')



def _validate_claims(claims: list[dict[str, Any]]) -> None:
    """Validate typed claim entries, enforcing the fail-closed domain vocabulary."""

    for claim in claims:
        claim_id = claim.get('id', '<unknown>')
        description = claim.get('description')
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f'claim {claim_id} must include a non-empty description')
        domain = claim.get('domain')
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError(f'claim {claim_id} must include a non-empty domain')
        if domain not in KNOWN_SECURITY_DOMAINS and not bool(claim.get('custom', False)):
            raise ValueError(
                f'claim {claim_id} references unknown security domain {domain!r}; '
                'mark it custom=True to model a domain outside PRODUCTION_SECURITY_DOMAINS/XAMAN_SECURITY_DOMAINS'
            )
        severity = claim.get('severity')
        if severity is not None and severity not in CLAIM_SEVERITIES:
            raise ValueError(f'claim {claim_id} has unsupported severity: {severity}')
        required_assumptions = claim.get('required_assumptions', [])
        if not isinstance(required_assumptions, list):
            raise ValueError(f'claim {claim_id}.required_assumptions must be a list')
        for assumption_id in required_assumptions:
            if not isinstance(assumption_id, str) or not assumption_id.strip():
                raise ValueError(f'claim {claim_id}.required_assumptions entries must be non-empty strings')



def _validate_claim_references(
    records: list[dict[str, Any]],
    *,
    collection_name: str,
    claim_ids: set[str],
) -> None:
    for record in records:
        record_id = record.get('id', '<unknown>')
        claim_id = record.get('claim_id')
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise ValueError(f'{collection_name} {record_id} must include a non-empty claim_id')
        if claim_id not in claim_ids:
            raise ValueError(f'{collection_name} {record_id} references unknown claim: {claim_id}')



def _validate_proof_obligations(proof_obligations: list[dict[str, Any]], *, claim_ids: set[str]) -> None:
    _validate_claim_references(proof_obligations, collection_name='proof_obligation', claim_ids=claim_ids)
    for obligation in proof_obligations:
        obligation_id = obligation.get('id', '<unknown>')
        prover = obligation.get('prover')
        if not isinstance(prover, str) or not prover.strip():
            raise ValueError(f'proof_obligation {obligation_id} must include a non-empty prover')
        if prover not in ALLOWED_PROVER_TARGETS:
            raise ValueError(f'proof_obligation {obligation_id} references unsupported prover: {prover}')
        status = obligation.get('status')
        if status not in PROOF_OBLIGATION_STATUSES:
            raise ValueError(f'proof_obligation {obligation_id} has unsupported status: {status}')



def _validate_disproof_vectors(disproof_vectors: list[dict[str, Any]], *, claim_ids: set[str]) -> None:
    _validate_claim_references(disproof_vectors, collection_name='disproof_vector', claim_ids=claim_ids)
    for vector in disproof_vectors:
        vector_id = vector.get('id', '<unknown>')
        tactic = vector.get('tactic')
        if not isinstance(tactic, str) or not tactic.strip():
            raise ValueError(f'disproof_vector {vector_id} must include a non-empty tactic')
        status = vector.get('status')
        if status not in DISPROOF_VECTOR_STATUSES:
            raise ValueError(f'disproof_vector {vector_id} has unsupported status: {status}')
        counterexample = vector.get('counterexample')
        if counterexample is not None and not isinstance(counterexample, Mapping):
            raise ValueError(f'disproof_vector {vector_id}.counterexample must be a mapping when present')



def _validate_solver_results(solver_results: list[dict[str, Any]], *, claim_ids: set[str]) -> None:
    _validate_claim_references(solver_results, collection_name='solver_result', claim_ids=claim_ids)
    for result in solver_results:
        result_id = result.get('id', '<unknown>')
        solver_name = result.get('solver_name')
        if not isinstance(solver_name, str) or not solver_name.strip():
            raise ValueError(f'solver_result {result_id} must include a non-empty solver_name')
        value = result.get('result')
        if value not in SOLVER_RESULT_VALUES:
            raise ValueError(f'solver_result {result_id} has unsupported result value: {value}')



def _validate_runtime_traces(runtime_traces: list[dict[str, Any]], *, event_ids: set[str]) -> None:
    for trace in runtime_traces:
        trace_id = trace.get('id', '<unknown>')
        description = trace.get('description')
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f'runtime_trace {trace_id} must include a non-empty description')
        domain = trace.get('domain')
        if domain is not None and domain not in KNOWN_SECURITY_DOMAINS:
            raise ValueError(f'runtime_trace {trace_id} references unknown security domain: {domain}')
        events = trace.get('events', [])
        if not isinstance(events, list):
            raise ValueError(f'runtime_trace {trace_id}.events must be a list')
        for event_id in events:
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError(f'runtime_trace {trace_id}.events entries must be non-empty strings')
            if event_id not in event_ids:
                raise ValueError(f'runtime_trace {trace_id} references unknown event id: {event_id}')



def _validate_timestamp(value: Any) -> None:
    """Accept integer, float, numeric-string, or ISO-8601 event timestamps."""

    if isinstance(value, bool):
        raise ValueError('event timestamp must be int, float, or ISO string when present')
    if isinstance(value, (int, float)):
        return
    if isinstance(value, str):
        try:
            float(value)
            return
        except ValueError:
            try:
                datetime.fromisoformat(value.replace('Z', '+00:00'))
                return
            except ValueError as exc:
                raise ValueError('event timestamp must be int, float, or ISO string when present') from exc
    raise ValueError('event timestamp must be int, float, or ISO string when present')



def _validate_references(normalized: SecurityModelIR) -> None:
    asset_ids = {item['id'] for item in normalized.assets if isinstance(item.get('id'), str)}
    wallet_ids = {item['id'] for item in normalized.wallets if isinstance(item.get('id'), str)}
    role_ids = {item['id'] for item in normalized.roles if isinstance(item.get('id'), str)}
    principal_ids = {item['id'] for item in normalized.principals if isinstance(item.get('id'), str)}
    account_ids = {item['id'] for item in normalized.accounts if isinstance(item.get('id'), str)}
    capability_ids = {item['id'] for item in normalized.capabilities if isinstance(item.get('id'), str)}
    resource_ids = asset_ids | wallet_ids | account_ids
    resource_ids |= {item['id'] for item in normalized.entities if isinstance(item.get('id'), str)}

    for principal in normalized.principals:
        principal_id = principal.get('id', '<unknown>')
        role_id = principal.get('role')
        if role_id is not None and role_id not in role_ids:
            raise ValueError(f'principal {principal_id} references unknown role: {role_id}')

    for account in normalized.accounts:
        account_id = account.get('id', '<unknown>')
        asset_id = account.get('asset_id', account.get('asset'))
        if asset_id is not None and asset_id not in asset_ids:
            raise ValueError(f'account {account_id} references unknown asset: {asset_id}')
        wallet_id = account.get('wallet_id')
        if wallet_id is not None and wallet_id not in wallet_ids:
            raise ValueError(f'account {account_id} references unknown wallet: {wallet_id}')
        owner = account.get('owner')
        if owner is not None and owner not in principal_ids:
            raise ValueError(f'account {account_id} references unknown principal owner: {owner}')

    for wallet in normalized.wallets:
        wallet_id = wallet.get('id', '<unknown>')
        asset_id = wallet.get('asset_id', wallet.get('asset'))
        if asset_id is not None and asset_id not in asset_ids:
            raise ValueError(f'wallet {wallet_id} references unknown asset: {asset_id}')
        if 'status' in wallet and wallet['status'] not in WALLET_STATUSES:
            raise ValueError(f'wallet {wallet_id} has unsupported status: {wallet["status"]}')
        for principal_field in ('owner', 'principal', 'principal_id'):
            principal_id = wallet.get(principal_field)
            if principal_id is not None and principal_id not in principal_ids:
                raise ValueError(f'wallet {wallet_id} references unknown principal: {principal_id}')

    for capability in normalized.capabilities:
        capability_id = capability.get('id', '<unknown>')
        principal_id = capability.get('principal') or capability.get('principal_id')
        if principal_id is not None and principal_id not in principal_ids:
            raise ValueError(f'capability {capability_id} references unknown principal: {principal_id}')
        resource_id = capability.get('resource') or capability.get('resource_id')
        if resource_id is not None and resource_id not in resource_ids:
            raise ValueError(f'capability {capability_id} references unknown resource: {resource_id}')

    for event in normalized.events:
        event_id = event.get('id', '<unknown>')
        if 'timestamp' in event:
            _validate_timestamp(event['timestamp'])
        for field_name, known_ids, label in (
            ('principal', principal_ids, 'principal'),
            ('wallet_id', wallet_ids, 'wallet'),
            ('account_id', account_ids, 'account'),
            ('capability_id', capability_ids, 'capability'),
        ):
            reference = event.get(field_name)
            if reference is not None and reference not in known_ids:
                raise ValueError(f'event {event_id} references unknown {label}: {reference}')

    for state_machine in normalized.state_machines:
        state_machine_id = state_machine.get('id', '<unknown>')
        transitions = state_machine.get('transitions', [])
        if transitions:
            if not isinstance(transitions, list):
                raise ValueError(f'state_machine {state_machine_id}.transitions must be a list')
            for index, transition in enumerate(transitions):
                if not isinstance(transition, Mapping):
                    raise ValueError(f'state_machine {state_machine_id}.transitions[{index}] must be a mapping')
                event_name = transition.get('event')
                if event_name not in KNOWN_EVENT_TYPES:
                    raise ValueError(f'state_machine {state_machine_id}.transitions[{index}] references unsupported event: {event_name}')



def _event_identity(event: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = event.get(key)
        if value is not None:
            return value
    return None



def validate_event_registry(events: list[dict[str, Any]], *, strict: bool = False) -> list[str]:
    """Return event-registry validation errors for *events*."""

    errors: list[str] = []
    for event in events:
        event_id = event.get('id', '<unknown>')
        event_name = event.get('event')
        if not isinstance(event_name, str) or not event_name.strip():
            continue
        if event_name in KNOWN_EVENT_TYPES:
            continue
        if strict:
            errors.append(f'event {event_id} uses unknown event type {event_name!r}')
            continue
        if not bool(event.get('custom', False)) or not isinstance(event.get('description'), str) or not event['description'].strip():
            errors.append(f'event {event_id} uses unknown event type {event_name!r} without custom modeling metadata')
    return errors



def validate_state_machines(state_machines: list[dict[str, Any]]) -> list[str]:
    """Return state-machine validation errors for *state_machines*."""

    errors: list[str] = []
    for state_machine in state_machines:
        state_machine_id = state_machine.get('id', '<unknown>')
        states = state_machine.get('states')
        if not isinstance(states, list):
            errors.append(f'state_machine {state_machine_id}.states must be a list')
            continue
        if not states:
            errors.append(f'state_machine {state_machine_id}.states must not be empty')
        current = state_machine.get('current')
        if current is not None and current not in states:
            errors.append(f'state_machine {state_machine_id}.current must be present in state_machine.states')
    return errors



def _validate_event_requirements(events: list[dict[str, Any]]) -> None:
    seen_event_ids: set[str] = set()
    terminal_events: dict[Any, set[str]] = {}
    for event in events:
        event_id = event.get('id')
        if isinstance(event_id, str):
            if event_id in seen_event_ids:
                raise ValueError(f'Duplicate event id: {event_id}')
            seen_event_ids.add(event_id)
        event_name = event.get('event')
        if not isinstance(event_name, str) or not event_name.strip():
            raise ValueError(f'event {event_id} must include a non-empty event name')
        event_registry_errors = validate_event_registry([event])
        if event_registry_errors:
            raise ValueError(event_registry_errors[0])
        if event_name in {'withdrawal_requested', 'withdrawal_approved', 'withdrawal_broadcast', 'withdrawal_cancelled'}:
            if _event_identity(event, 'withdrawal_id', 'txid') is None:
                raise ValueError(f'{event_name} events require withdrawal_id or txid')
        if event_name in {'deposit_observed', 'deposit_finalized', 'deposit_credited'}:
            if _event_identity(event, 'deposit_id', 'txid') is None:
                raise ValueError(f'{event_name} events require deposit_id or txid')
        if event_name == 'signing_request' and event.get('wallet_id') is None:
            raise ValueError('signing_request events require wallet_id')
        if event_name in {'capability_revoked', 'privileged_action'} and event.get('capability_id') is None:
            raise ValueError(f'{event_name} events require capability_id')
        if event_name in {'withdrawal_broadcast', 'withdrawal_cancelled'}:
            withdrawal_id = _event_identity(event, 'withdrawal_id', 'txid')
            if withdrawal_id is None:
                continue
            seen_terminal_events = terminal_events.setdefault(withdrawal_id, set())
            seen_terminal_events.add(str(event_name))
            if (
                seen_terminal_events == {'withdrawal_broadcast', 'withdrawal_cancelled'}
                and not bool(event.get('allow_terminal_conflict', False))
            ):
                raise ValueError(f'withdrawal {withdrawal_id} has contradictory terminal events without explicit modeling')



def validate_ir(model: SecurityModelIR | Mapping[str, Any]) -> SecurityModelIR:
    """Validate and normalize a security IR instance."""

    normalized = as_security_model_ir(model)
    model_dict = normalized.to_dict()
    if not isinstance(normalized.schema_version, str) or not normalized.schema_version.strip():
        raise ValueError('schema_version is required')
    if not isinstance(normalized.model_id, str) or not normalized.model_id.strip():
        raise ValueError('model_id is required')
    for field_name in REQUIRED_SEQUENCE_FIELDS:
        _ensure_sequence_field(model_dict, field_name)
    for assumption in normalized.assumptions:
        _validate_assumption_entry(assumption)
    for collection_name, label in _ID_FIELDS.items():
        entries = getattr(normalized, collection_name)
        _require_unique_ids(entries, label)
        _validate_numeric_fields(entries, collection_name)
        _validate_record_evidence(entries, collection_name)
    if not normalized.prover_targets:
        raise ValueError('prover_targets must not be empty')
    unsupported_targets = sorted({target for target in normalized.prover_targets if target not in ALLOWED_PROVER_TARGETS})
    if unsupported_targets:
        raise ValueError(f'Unsupported prover targets: {", ".join(unsupported_targets)}')
    _validate_policy_records(normalized.policies)
    state_machine_errors = validate_state_machines(normalized.state_machines)
    if state_machine_errors:
        raise ValueError(state_machine_errors[0])
    event_registry_errors = validate_event_registry(normalized.events)
    if event_registry_errors:
        raise ValueError(event_registry_errors[0])
    _validate_references(normalized)
    _validate_event_requirements(normalized.events)
    _validate_metadata(normalized.metadata)
    claim_ids = {claim['id'] for claim in normalized.claims if isinstance(claim.get('id'), str)}
    event_ids = {event['id'] for event in normalized.events if isinstance(event.get('id'), str)}
    _validate_claims(normalized.claims)
    _validate_proof_obligations(normalized.proof_obligations, claim_ids=claim_ids)
    _validate_disproof_vectors(normalized.disproof_vectors, claim_ids=claim_ids)
    _validate_solver_results(normalized.solver_results, claim_ids=claim_ids)
    _validate_runtime_traces(normalized.runtime_traces, event_ids=event_ids)
    return normalized



def claim_domains(model: SecurityModelIR | Mapping[str, Any]) -> dict[str, str]:
    """Return a mapping of ``claim_id`` to ``domain`` for every claim in *model*."""

    normalized = as_security_model_ir(model)
    return {
        claim['id']: claim['domain']
        for claim in normalized.claims
        if isinstance(claim.get('id'), str) and isinstance(claim.get('domain'), str)
    }



def domain_coverage_report(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    required_domains: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a deterministic coverage report for *model* against *required_domains*.

    Defaults to :data:`KNOWN_SECURITY_DOMAINS`, i.e. every production and
    Xaman security domain. The report lists, per domain, whether at least one
    claim models that domain and which claim ids provide that coverage.
    """

    normalized = as_security_model_ir(model)
    domains = frozenset(required_domains) if required_domains is not None else KNOWN_SECURITY_DOMAINS
    domain_to_claims: dict[str, list[str]] = {domain: [] for domain in domains}
    for claim in normalized.claims:
        domain = claim.get('domain')
        claim_id = claim.get('id')
        if isinstance(domain, str) and domain in domain_to_claims and isinstance(claim_id, str):
            domain_to_claims[domain].append(claim_id)
    domains_report = {
        domain: {
            'covered': bool(domain_to_claims[domain]),
            'claim_ids': sorted(domain_to_claims[domain]),
        }
        for domain in sorted(domains)
    }
    missing = sorted(domain for domain, entry in domains_report.items() if not entry['covered'])
    return {
        'model_id': normalized.model_id,
        'required_domains': sorted(domains),
        'domains': domains_report,
        'missing_domains': missing,
        'fully_covered': not missing,
    }



def check_domain_coverage(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    required_domains: Iterable[str] | None = None,
) -> list[str]:
    """Return the sorted list of *required_domains* missing claim coverage in *model*."""

    return list(domain_coverage_report(model, required_domains=required_domains)['missing_domains'])



def validate_domain_coverage(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    required_domains: Iterable[str] | None = None,
) -> SecurityModelIR:
    """Fail closed unless *model* has at least one claim for every required domain.

    This is the coverage gate referenced by ``PORTAL-CXTP-062``: every
    production and Xaman security domain must be modeled by a claim before
    the IR can be treated as proof-ready. Raises :class:`ValueError` listing
    the missing domains otherwise.
    """

    normalized = validate_ir(model)
    missing = check_domain_coverage(normalized, required_domains=required_domains)
    if missing:
        raise ValueError(
            'SecurityModelIR is missing claim coverage for required security domain(s): '
            + ', '.join(missing)
        )
    return normalized



def json_ready(value: Any) -> Any:
    """Convert dataclass-heavy values into JSON-ready structures."""

    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value

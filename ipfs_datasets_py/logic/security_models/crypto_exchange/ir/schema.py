"""Schema and validation helpers for the canonical security IR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Mapping, NotRequired, Required, TypedDict


class AssumptionEntry(TypedDict, total=False):
    id: str
    description: str
    custom: bool


class EvidenceRef(TypedDict, total=False):
    """Evidence references require kind/path/review_status; remaining fields are optional."""

    kind: Required[str]
    path: Required[str]
    review_status: Required[str]
    line_start: NotRequired[int]
    line_end: NotRequired[int]
    sha256: NotRequired[str]
    notes: NotRequired[str]


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

DEFAULT_THREAT_MODEL_ASSUMPTIONS: list[AssumptionEntry] = [
    {'id': assumption_id, 'description': description}
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
    'assumptions',
    'prover_targets',
)

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
    assumptions: list[AssumptionEntry | str] = field(default_factory=lambda: list(DEFAULT_THREAT_MODEL_ASSUMPTIONS))
    prover_targets: list[str] = field(default_factory=lambda: ['z3'])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'SecurityModelIR':
        allowed = {item.name for item in fields(cls)}
        payload = {name: data[name] for name in allowed if name in data}
        return cls(**payload)


_ID_FIELDS = {
    'entities': 'entity',
    'assets': 'asset',
    'wallets': 'wallet',
    'accounts': 'account',
    'roles': 'role',
    'principals': 'principal',
    'capabilities': 'capability',
    'events': 'event',
    'state_machines': 'state machine',
    'invariants': 'invariant',
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
            _validate_non_negative_int(f'evidence_refs.{key}', reference[key])
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



def _validate_references(normalized: SecurityModelIR) -> None:
    asset_ids = {item['id'] for item in normalized.assets if isinstance(item.get('id'), str)}
    wallet_ids = {item['id'] for item in normalized.wallets if isinstance(item.get('id'), str)}
    principal_ids = {item['id'] for item in normalized.principals if isinstance(item.get('id'), str)}
    resource_ids = asset_ids | wallet_ids | {item['id'] for item in normalized.accounts if isinstance(item.get('id'), str)}
    resource_ids |= {item['id'] for item in normalized.entities if isinstance(item.get('id'), str)}

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



def _event_identity(event: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = event.get(key)
        if value is not None:
            return value
    return None



def _validate_event_requirements(events: list[dict[str, Any]]) -> None:
    seen_event_ids: set[str] = set()
    for event in events:
        event_id = event.get('id')
        if isinstance(event_id, str):
            if event_id in seen_event_ids:
                raise ValueError(f'Duplicate event id: {event_id}')
            seen_event_ids.add(event_id)
        event_name = event.get('event')
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
    _validate_references(normalized)
    _validate_event_requirements(normalized.events)
    _validate_metadata(normalized.metadata)
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

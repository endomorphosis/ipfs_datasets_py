"""Schema and validation helpers for the canonical security IR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Mapping


DEFAULT_THREAT_MODEL_ASSUMPTIONS = [
    'cryptographic primitives are unbroken',
    'private keys are generated with sufficient entropy',
    'HSM/key manager obeys its interface contract',
    'database commits are serializable',
    'nonce reservation is atomic',
    'blockchain finality threshold k is sufficient',
    'external RPC providers may lie/delay/censor within modeled bounds',
    'audit logs are append-only or tamper-evident',
    'production must not depend on simulated proof/ZKP/F-logic mode',
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
    assumptions: list[str] = field(default_factory=lambda: list(DEFAULT_THREAT_MODEL_ASSUMPTIONS))
    prover_targets: list[str] = field(default_factory=lambda: ['z3'])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'SecurityModelIR':
        allowed = {item.name for item in fields(cls)}
        payload = {name: data[name] for name in allowed if name in data}
        return cls(**payload)


def as_security_model_ir(model: SecurityModelIR | Mapping[str, Any]) -> SecurityModelIR:
    """Return *model* as a validated :class:`SecurityModelIR`."""

    if isinstance(model, SecurityModelIR):
        return model
    if isinstance(model, Mapping):
        return SecurityModelIR.from_dict(model)
    raise TypeError(f'Unsupported security model type: {type(model)!r}')


def _ensure_sequence_field(model_dict: Mapping[str, Any], field_name: str) -> None:
    value = model_dict.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f'{field_name} must be a list in SecurityModelIR')


def validate_ir(model: SecurityModelIR | Mapping[str, Any]) -> SecurityModelIR:
    """Validate and normalize a security IR instance."""

    normalized = as_security_model_ir(model)
    model_dict = normalized.to_dict()
    if not normalized.schema_version:
        raise ValueError('schema_version is required')
    if not normalized.model_id:
        raise ValueError('model_id is required')
    for field_name in REQUIRED_SEQUENCE_FIELDS:
        _ensure_sequence_field(model_dict, field_name)
    for capability in normalized.capabilities:
        if 'id' not in capability:
            raise ValueError('Every capability must include an id')
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

"""One-way projection from Xaman runtime records to formal assurance inputs.

WALPROC-G220 / WALPROC-026 — Link Xaman runtime records to formal assurance
without coupling.

This module is a **projection-only adapter**:

* Direction is runtime → assurance inputs only.
* It never imports formal proof tools, report generators, archive corpora,
  Firebase harnesses, native vault code, or device-trial harnesses.
* Formal security models remain under ``logic/`` (and existing
  ``docs/security_verification`` / artifact paths). This module only records
  those paths as inventory strings.
* Projected ``assurance_status`` values are **not** runtime authorization and
  are **not** release proof.

Consumers of formal analysis may load these projections offline. Runtime
processors continue to operate without consulting them.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .models import (
    PayloadStatus,
    SettlementVerdict,
    XamanPayload,
)

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

SCHEMA: Final = "wallet.xaman.assurance-projection/v1"
SCHEMA_VERSION: Final = 1
GOAL_ID: Final = "WALPROC-G220"
TASK_ID: Final = "WALPROC-026"
BRIDGE_DIRECTION: Final = "runtime_to_formal_projection"

# Projection domains required by WALPROC-G220 acceptance.
PROJECTION_DOMAINS: Final[tuple[str, ...]] = (
    "network_binding",
    "payload_lifecycle",
    "signing_decision",
    "submission",
    "finality_assumptions",
)

# Formal asset inventory (path strings only — never imported at runtime).
# Paths are repository-relative; formal modules stay put unless a separate
# relocation task proves true runtime duplication.
FORMAL_ASSET_INVENTORY: Final[tuple[Mapping[str, str], ...]] = (
    MappingProxyType(
        {
            "id": "xaman-security-ir-adapter",
            "path": "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/xaman/adapter.py",
            "role": "security_ir_adapter",
            "layer": "formal",
        }
    ),
    MappingProxyType(
        {
            "id": "xaman-security-ir-config",
            "path": "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/xaman/config.py",
            "role": "security_ir_config",
            "layer": "formal",
        }
    ),
    MappingProxyType(
        {
            "id": "xaman-source-extractor",
            "path": (
                "ipfs_datasets_py/ipfs_datasets_py/logic/security_models/"
                "crypto_exchange/extractors/xaman_source_extractor.py"
            ),
            "role": "source_extractor",
            "layer": "formal",
            "ast_symbol": "xaman_source_extractor",
        }
    ),
    MappingProxyType(
        {
            "id": "xaman-runtime-trace-ingestor",
            "path": (
                "ipfs_datasets_py/ipfs_datasets_py/logic/security_models/"
                "crypto_exchange/extractors/xaman_runtime_trace_ingestor.py"
            ),
            "role": "trace_extraction",
            "layer": "formal",
        }
    ),
    MappingProxyType(
        {
            "id": "xaman-assurance-packet",
            "path": (
                "ipfs_datasets_py/ipfs_datasets_py/logic/security_models/"
                "crypto_exchange/reports/xaman_assurance_packet.py"
            ),
            "role": "release_decision_packet",
            "layer": "formal",
        }
    ),
    MappingProxyType(
        {
            "id": "xaman-protocol-projection",
            "path": (
                "ipfs_datasets_py/ipfs_datasets_py/logic/security_models/"
                "crypto_exchange/reports/xaman_protocol_projection.py"
            ),
            "role": "protocol_projection",
            "layer": "formal",
        }
    ),
    MappingProxyType(
        {
            "id": "security-model-ir-schema",
            "path": (
                "ipfs_datasets_py/ipfs_datasets_py/logic/security_models/"
                "crypto_exchange/ir/schema.py"
            ),
            "role": "security_model_ir",
            "layer": "formal",
            "ast_symbol": "SecurityModelIR",
        }
    ),
)

# Import prefixes that runtime xaman modules (including this adapter) must not
# load. Kept as plain strings so static boundary tests can assert them.
FORBIDDEN_RUNTIME_IMPORT_PREFIXES: Final[tuple[str, ...]] = (
    "ipfs_datasets_py.logic.security_models.crypto_exchange.reports",
    "ipfs_datasets_py.logic.security_ir.xaman",
    "ipfs_datasets_py.logic.security_models.crypto_exchange.extractors",
    "ipfs_datasets_py.logic.security_models.crypto_exchange.provers",
    "ipfs_datasets_py.logic.security_models.crypto_exchange.solvers",
)

# Substring markers for forbidden formal / harness dependencies in source.
FORBIDDEN_SOURCE_MARKERS: Final[tuple[str, ...]] = (
    "security_models.crypto_exchange.reports",
    "security_ir.xaman",
    "xaman_assurance_packet",
    "xaman_disproof_suite",
    "xaman_testnet_solver_portfolio",
    "run_security_ir_assurance_baseline",
    "firebase",
    "native_vault",
    "device_trial",
    "device_harness",
    "archive_corpus",
    "proof_tool",
    "report_generator",
)

# Runtime package modules that form the non-custodial processor surface.
RUNTIME_XAMAN_MODULE_FILES: Final[tuple[str, ...]] = (
    "assurance.py",
    "models.py",
    "normalizer.py",
    "privacy.py",
    "processor.py",
    "provider.py",
    "settlement.py",
    "__init__.py",
)


class AssuranceStatus(StrEnum):
    """Status of a projected assurance input — never runtime auth or release.

    These values describe whether a domain was observed, partial, missing, or
    assumed in the runtime record. They must not be used as:

    * grant / deny authorization for wallet operations;
    * release-gate decisions;
    * proof that formal claims hold.
    """

    OBSERVED = "observed"
    PARTIAL = "partial"
    MISSING = "missing"
    ASSUMED = "assumed"
    NOT_APPLICABLE = "not_applicable"


class AssuranceAuthority(StrEnum):
    """Explicit non-authority markers for projected statuses."""

    NOT_RUNTIME_AUTHORIZATION = "not_runtime_authorization"
    NOT_RELEASE_PROOF = "not_release_proof"
    NOT_FORMAL_CLAIM_SATISFACTION = "not_formal_claim_satisfaction"


# Policy constants consumed by docs and tests.
ASSURANCE_POLICY: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "formal_assurance_is_not_runtime_correctness": True,
        "runtime_must_not_import_report_generators": True,
        "runtime_must_not_import_proof_tools": True,
        "runtime_must_not_import_archive_corpus": True,
        "runtime_must_not_import_firebase": True,
        "runtime_must_not_import_native_vault": True,
        "runtime_must_not_import_device_harness": True,
        "assurance_status_is_not_runtime_authorization": True,
        "assurance_status_is_not_release_proof": True,
        "formal_modules_remain_at_existing_paths": True,
        "bridge_direction": BRIDGE_DIRECTION,
        "shared_surface": "small typed projections only",
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
    }
)


@dataclass(frozen=True, slots=True)
class DomainProjection:
    """Projection for one of the five required assurance domains."""

    domain: str
    status: AssuranceStatus
    facts: Mapping[str, Any] = field(default_factory=dict, hash=False)
    assumptions: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.domain not in PROJECTION_DOMAINS:
            raise ValueError(
                f"unknown projection domain {self.domain!r}; "
                f"expected one of {PROJECTION_DOMAINS}"
            )
        if not isinstance(self.status, AssuranceStatus):
            raise ValueError("status must be AssuranceStatus")
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status.value,
            "facts": dict(self.facts),
            "assumptions": list(self.assumptions),
            "notes": self.notes,
            "authority": {
                "not_runtime_authorization": True,
                "not_release_proof": True,
                "markers": [
                    AssuranceAuthority.NOT_RUNTIME_AUTHORIZATION.value,
                    AssuranceAuthority.NOT_RELEASE_PROOF.value,
                    AssuranceAuthority.NOT_FORMAL_CLAIM_SATISFACTION.value,
                ],
            },
        }


@dataclass(frozen=True, slots=True)
class RuntimeAssuranceProjection:
    """Complete one-way projection from a runtime Xaman payload record.

    Suitable as an offline assurance input. Not an authorization token and
    not a release decision packet.
    """

    schema: str = SCHEMA
    schema_version: int = SCHEMA_VERSION
    goal_id: str = GOAL_ID
    payload_uuid: str = ""
    network: str | None = None
    account: str | None = None
    domains: Mapping[str, DomainProjection] = field(
        default_factory=dict, hash=False
    )
    source_record_kind: str = "xaman_payload"
    is_runtime_authorization: bool = False
    is_release_proof: bool = False
    bridge_direction: str = BRIDGE_DIRECTION

    def __post_init__(self) -> None:
        # Hard-pin non-authority flags so callers cannot promote the projection.
        object.__setattr__(self, "is_runtime_authorization", False)
        object.__setattr__(self, "is_release_proof", False)
        object.__setattr__(self, "bridge_direction", BRIDGE_DIRECTION)
        object.__setattr__(self, "schema", SCHEMA)
        object.__setattr__(self, "schema_version", SCHEMA_VERSION)
        object.__setattr__(self, "goal_id", GOAL_ID)
        normalized: dict[str, DomainProjection] = {}
        for key, value in dict(self.domains).items():
            if not isinstance(value, DomainProjection):
                raise TypeError(
                    f"domains[{key!r}] must be DomainProjection, got {type(value)!r}"
                )
            if value.domain != key:
                raise ValueError(
                    f"domain key {key!r} mismatches DomainProjection.domain "
                    f"{value.domain!r}"
                )
            normalized[key] = value
        missing = set(PROJECTION_DOMAINS) - set(normalized)
        if missing:
            raise ValueError(
                f"projection missing required domains: {sorted(missing)}"
            )
        object.__setattr__(self, "domains", MappingProxyType(normalized))

    def domain(self, name: str) -> DomainProjection:
        return self.domains[name]

    def to_dict(self) -> dict[str, Any]:
        # Authority flags are hard-coded false in the public projection so a
        # mutated instance cannot promote assurance status to auth/release.
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "goal_id": GOAL_ID,
            "task_id": TASK_ID,
            "bridge_direction": BRIDGE_DIRECTION,
            "source_record_kind": self.source_record_kind,
            "payload_uuid": self.payload_uuid,
            "network": self.network,
            "account": self.account,
            "domains": {name: proj.to_dict() for name, proj in self.domains.items()},
            "policy": dict(ASSURANCE_POLICY),
            "is_runtime_authorization": False,
            "is_release_proof": False,
            "formal_asset_refs": [dict(item) for item in FORMAL_ASSET_INVENTORY],
        }


def _signing_decision_status(payload: XamanPayload) -> AssuranceStatus:
    """Map API lifecycle to a signing-decision observation (not authority)."""

    if payload.status is PayloadStatus.SIGNED:
        return AssuranceStatus.OBSERVED
    if payload.api_signed:
        return AssuranceStatus.OBSERVED
    if payload.status in {
        PayloadStatus.SUBMITTED,
        PayloadStatus.VALIDATED,
        PayloadStatus.FAILED,
    }:
        # Downstream of signing; signing is implied but not re-observed here.
        return AssuranceStatus.PARTIAL
    if payload.status is PayloadStatus.REJECTED:
        return AssuranceStatus.OBSERVED  # explicit non-sign decision
    if payload.status in {
        PayloadStatus.CREATED,
        PayloadStatus.OPENED,
        PayloadStatus.EXPIRED,
        PayloadStatus.CANCELLED,
    }:
        return AssuranceStatus.NOT_APPLICABLE
    return AssuranceStatus.MISSING


def _submission_status(payload: XamanPayload) -> AssuranceStatus:
    if payload.status is PayloadStatus.SUBMITTED:
        return AssuranceStatus.OBSERVED
    if payload.transaction_hash and payload.status in {
        PayloadStatus.VALIDATED,
        PayloadStatus.FAILED,
        PayloadStatus.SIGNED,
    }:
        return AssuranceStatus.PARTIAL
    if payload.status in {
        PayloadStatus.CREATED,
        PayloadStatus.OPENED,
        PayloadStatus.REJECTED,
        PayloadStatus.EXPIRED,
        PayloadStatus.CANCELLED,
    }:
        return AssuranceStatus.NOT_APPLICABLE
    return AssuranceStatus.MISSING


def _finality_status(payload: XamanPayload) -> AssuranceStatus:
    if payload.settlement is SettlementVerdict.XRPL_VALIDATED:
        return AssuranceStatus.OBSERVED
    if payload.settlement is SettlementVerdict.XRPL_FAILED:
        return AssuranceStatus.OBSERVED
    if payload.settlement is SettlementVerdict.XRPL_UNVALIDATED:
        return AssuranceStatus.PARTIAL
    if payload.settlement is SettlementVerdict.API_SUCCESS_ONLY:
        return AssuranceStatus.ASSUMED  # API success is not finality
    if payload.settlement is SettlementVerdict.AWAITING_TXID:
        return AssuranceStatus.MISSING
    if payload.settlement is SettlementVerdict.NETWORK_MISMATCH:
        return AssuranceStatus.OBSERVED
    if payload.settlement is SettlementVerdict.ACCOUNT_MISMATCH:
        return AssuranceStatus.OBSERVED
    if payload.settlement is SettlementVerdict.NOT_APPLICABLE:
        return AssuranceStatus.NOT_APPLICABLE
    return AssuranceStatus.MISSING


def project_payload_to_assurance(
    payload: XamanPayload,
    *,
    include_request_summary: bool = False,
) -> RuntimeAssuranceProjection:
    """Project a runtime :class:`XamanPayload` into assurance inputs.

    Covers network binding, payload lifecycle, signing decision, submission,
    and finality assumptions. Does not authorize anything and does not claim
    formal proof satisfaction.
    """

    if not isinstance(payload, XamanPayload):
        raise TypeError("payload must be XamanPayload")

    network_binding = DomainProjection(
        domain="network_binding",
        status=(
            AssuranceStatus.OBSERVED
            if payload.network is not None and payload.payload_uuid
            else AssuranceStatus.PARTIAL
        ),
        facts={
            "network": payload.network.value,
            "account": payload.account,
            "payload_uuid": payload.payload_uuid,
            "destination": payload.destination,
            "destination_tag": payload.destination_tag,
            "application_uuid": payload.application_uuid,
        },
        assumptions=(
            "runtime network binding is a ledger/API identity fact, not a "
            "proof of production Xaman client network selection controls",
        ),
        notes="Network/account/payload identity bound at normalize time.",
    )

    lifecycle = DomainProjection(
        domain="payload_lifecycle",
        status=AssuranceStatus.OBSERVED,
        facts={
            "status": payload.status.value,
            "api_resolved": payload.api_resolved,
            "api_signed": payload.api_signed,
            "api_cancelled": payload.api_cancelled,
            "api_expired": payload.api_expired,
            "is_api_success": payload.is_api_success,
            "transaction_type": payload.transaction_type,
            "created_at": (
                payload.created_at.isoformat() if payload.created_at else None
            ),
            "resolved_at": (
                payload.resolved_at.isoformat() if payload.resolved_at else None
            ),
            "expires_at": (
                payload.expires_at.isoformat() if payload.expires_at else None
            ),
            "content_digest": payload.content_digest,
            "raw_meta_digest": payload.raw_meta_digest,
            "request_summary": (
                dict(payload.request_summary) if include_request_summary else None
            ),
            "request_summary_omitted": not include_request_summary,
        },
        assumptions=(
            "API lifecycle states remain distinct and never collapse into "
            "ledger finality",
            "API success is never settlement",
        ),
        notes="Lifecycle is a runtime observation; formal models stay under logic/.",
    )

    signing = DomainProjection(
        domain="signing_decision",
        status=_signing_decision_status(payload),
        facts={
            "api_signed": payload.api_signed,
            "status": payload.status.value,
            "runtime_can_sign": False,
            "runtime_can_approve": False,
            "decision_source": "xaman_api_lifecycle_flags",
        },
        assumptions=(
            "runtime processor never signs or approves payloads",
            "api_signed is a remote lifecycle flag, not vault cryptographic proof",
            "native vault correctness is out of scope for this projection",
        ),
        notes=(
            "Signing decision is projected from API lifecycle only. "
            "It is not runtime authorization to sign."
        ),
    )

    submission = DomainProjection(
        domain="submission",
        status=_submission_status(payload),
        facts={
            "status": payload.status.value,
            "transaction_hash": payload.transaction_hash,
            "runtime_can_submit": False,
            "runtime_can_broadcast": False,
            "decision_source": "xaman_api_lifecycle_and_txid",
        },
        assumptions=(
            "runtime processor never submits or broadcasts transactions",
            "presence of a transaction hash is not XRPL inclusion proof",
        ),
        notes="Submission is observed from API/txid, not performed by the processor.",
    )

    finality = DomainProjection(
        domain="finality_assumptions",
        status=_finality_status(payload),
        facts={
            "settlement": payload.settlement.value,
            "settlement_detail": payload.settlement_detail,
            "is_ledger_settled": payload.is_ledger_settled,
            "is_api_success": payload.is_api_success,
            "transaction_hash": payload.transaction_hash,
            "api_success_is_settlement": False,
            "settlement_via": "xrpl",
        },
        assumptions=(
            "A6: the declared XRPL finality threshold is sufficient",
            "A9: external XRPL providers may lie, delay, or censor only within "
            "modeled bounds",
            "API success alone never establishes finality",
            "only XRPL-validated settlement yields is_ledger_settled=true",
        ),
        notes=(
            "Finality is an explicit settlement verdict from XRPL evidence. "
            "Assurance status here is not a release decision."
        ),
    )

    domains = {
        "network_binding": network_binding,
        "payload_lifecycle": lifecycle,
        "signing_decision": signing,
        "submission": submission,
        "finality_assumptions": finality,
    }
    return RuntimeAssuranceProjection(
        payload_uuid=payload.payload_uuid,
        network=payload.network.value,
        account=payload.account,
        domains=domains,
    )


def project_ledger_record_to_assurance(
    record: Mapping[str, Any],
    *,
    payload_uuid: str | None = None,
) -> RuntimeAssuranceProjection:
    """Project a public-ledger-shaped record into assurance inputs.

    Used for fixture ledger samples and XRPL-normalized records that the
    runtime may emit. Missing payload lifecycle fields are marked accordingly.
    """

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")

    network = (
        _optional_str(record.get("network"))
        or _optional_str(record.get("chain_network"))
    )
    account = _optional_str(record.get("account"))
    tx_hash = _optional_str(record.get("transaction_hash")) or _optional_str(
        record.get("hash")
    )
    validated = bool(record.get("validated"))
    finality_state = _optional_str(record.get("finality_state"))
    uuid = payload_uuid or _optional_str(record.get("payload_uuid")) or (
        f"ledger:{tx_hash}" if tx_hash else "ledger:unknown"
    )

    if network and account and tx_hash:
        nb_status = AssuranceStatus.OBSERVED
    elif network or account:
        nb_status = AssuranceStatus.PARTIAL
    else:
        nb_status = AssuranceStatus.MISSING

    if validated or finality_state in {"validated", "finalized"}:
        fin_status = AssuranceStatus.OBSERVED
    elif finality_state in {"failed", "unvalidated"}:
        fin_status = AssuranceStatus.OBSERVED
    elif tx_hash:
        fin_status = AssuranceStatus.PARTIAL
    else:
        fin_status = AssuranceStatus.MISSING

    domains = {
        "network_binding": DomainProjection(
            domain="network_binding",
            status=nb_status,
            facts={
                "network": network,
                "chain": _optional_str(record.get("chain")),
                "account": account,
                "destination": _optional_str(record.get("destination")),
                "destination_tag": record.get("destination_tag"),
                "payload_uuid": uuid,
                "ledger_index": record.get("ledger_index"),
                "provider_kind": _optional_str(record.get("provider_kind")),
            },
            assumptions=(
                "ledger record network identity is provider-reported",
            ),
        ),
        "payload_lifecycle": DomainProjection(
            domain="payload_lifecycle",
            status=AssuranceStatus.NOT_APPLICABLE,
            facts={
                "record_kind": "public_ledger",
                "transaction_type": _optional_str(record.get("transaction_type")),
                "raw_payload_digest": _optional_str(record.get("raw_payload_digest")),
            },
            notes="Public ledger records do not carry Xaman payload lifecycle.",
        ),
        "signing_decision": DomainProjection(
            domain="signing_decision",
            status=AssuranceStatus.NOT_APPLICABLE,
            facts={
                "runtime_can_sign": False,
                "ledger_record_has_no_signing_authority": True,
            },
            assumptions=(
                "ledger observation does not reconstruct the signing decision",
            ),
        ),
        "submission": DomainProjection(
            domain="submission",
            status=(
                AssuranceStatus.OBSERVED if tx_hash else AssuranceStatus.MISSING
            ),
            facts={
                "transaction_hash": tx_hash,
                "runtime_can_submit": False,
                "runtime_can_broadcast": False,
            },
        ),
        "finality_assumptions": DomainProjection(
            domain="finality_assumptions",
            status=fin_status,
            facts={
                "validated": validated,
                "finality_state": finality_state,
                "transaction_hash": tx_hash,
                "ledger_index": record.get("ledger_index"),
                "api_success_is_settlement": False,
                "settlement_via": "xrpl",
            },
            assumptions=(
                "A6: the declared XRPL finality threshold is sufficient",
                "validated/finality_state are provider-reported ledger facts",
            ),
        ),
    }
    return RuntimeAssuranceProjection(
        payload_uuid=uuid,
        network=network,
        account=account,
        domains=domains,
        source_record_kind="public_ledger_record",
    )


def project_many(
    payloads: Sequence[XamanPayload],
    *,
    include_request_summary: bool = False,
) -> tuple[RuntimeAssuranceProjection, ...]:
    """Project a sequence of payloads (order-preserving)."""

    return tuple(
        project_payload_to_assurance(
            item, include_request_summary=include_request_summary
        )
        for item in payloads
    )


def formal_asset_inventory() -> tuple[dict[str, str], ...]:
    """Return a copy of the formal asset inventory (path strings only)."""

    return tuple(dict(item) for item in FORMAL_ASSET_INVENTORY)


def formal_modules_remain_at_existing_paths(
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Inventory check: formal assets stay at declared paths (no relocation).

    Returns a report; does not move anything. Relocation is out of scope for
    WALPROC-G220 unless a separate audit proves true runtime duplication.
    """

    root = repository_root
    if root is None:
        # assurance.py → xaman → wallets → processors → ipfs_datasets_py → package root → repo
        root = Path(__file__).resolve().parents[5]
    present: list[str] = []
    missing: list[str] = []
    for asset in FORMAL_ASSET_INVENTORY:
        path = root / asset["path"]
        if path.is_file():
            present.append(asset["path"])
        else:
            missing.append(asset["path"])
    return {
        "formal_modules_remain_at_existing_paths": True,
        "relocation_in_scope": False,
        "present": present,
        "missing": missing,
        "all_present": not missing,
        "policy": "Treat formal artifact relocation as a separate task only if "
        "inventory proves true runtime duplication.",
    }


def _module_source_path(module_file: str) -> Path:
    return Path(__file__).resolve().parent / module_file


def iter_runtime_module_sources() -> Iterable[tuple[str, str]]:
    """Yield ``(filename, source_text)`` for runtime xaman modules."""

    for name in RUNTIME_XAMAN_MODULE_FILES:
        path = _module_source_path(name)
        if path.is_file():
            yield name, path.read_text(encoding="utf-8")


def collect_forbidden_import_hits(
    source: str,
    *,
    filename: str = "<module>",
) -> list[dict[str, str]]:
    """Static scan: report forbidden formal / harness import references."""

    hits: list[dict[str, str]] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [
            {
                "filename": filename,
                "kind": "syntax_error",
                "detail": str(exc),
            }
        ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                for prefix in FORBIDDEN_RUNTIME_IMPORT_PREFIXES:
                    if module == prefix or module.startswith(prefix + "."):
                        hits.append(
                            {
                                "filename": filename,
                                "kind": "import",
                                "module": module,
                                "prefix": prefix,
                            }
                        )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for prefix in FORBIDDEN_RUNTIME_IMPORT_PREFIXES:
                if module == prefix or module.startswith(prefix + "."):
                    hits.append(
                        {
                            "filename": filename,
                            "kind": "import_from",
                            "module": module,
                            "prefix": prefix,
                        }
                    )

    # Also catch string markers that would indicate hard coupling even without
    # a live import (e.g. dynamic import strings of formal report packages).
    # Skip this module's own declarative inventory / forbidden-marker tables.
    if filename != "assurance.py":
        lowered = source.lower()
        for marker in FORBIDDEN_SOURCE_MARKERS:
            if marker.lower() in lowered:
                # Allow documentation comments that only mention the policy
                # when they appear next to "must not" / "never" / "without".
                # For runtime modules other than this adapter, any hit is bad.
                hits.append(
                    {
                        "filename": filename,
                        "kind": "source_marker",
                        "marker": marker,
                    }
                )
    return hits


def assert_runtime_import_boundary() -> dict[str, Any]:
    """Assert runtime xaman modules do not import formal / harness code.

    Returns a structured report. Raises ``AssertionError`` on violation.
    """

    all_hits: list[dict[str, str]] = []
    scanned: list[str] = []
    for name, source in iter_runtime_module_sources():
        scanned.append(name)
        all_hits.extend(collect_forbidden_import_hits(source, filename=name))

    report = {
        "scanned_modules": scanned,
        "forbidden_prefixes": list(FORBIDDEN_RUNTIME_IMPORT_PREFIXES),
        "hits": all_hits,
        "clean": not all_hits,
        "policy": dict(ASSURANCE_POLICY),
    }
    if all_hits:
        detail = "; ".join(
            f"{h.get('filename')}:{h.get('kind')}:{h.get('module') or h.get('marker')}"
            for h in all_hits
        )
        raise AssertionError(
            "runtime xaman modules must not import formal assurance, proof "
            f"tools, report generators, or device/vault harnesses: {detail}"
        )
    return report


def assurance_status_is_not_authorization(
    projection: RuntimeAssuranceProjection,
) -> bool:
    """True when the public projection disclaims auth and release power.

    Evaluates the serialized projection (hard-coded non-authority) so a
    mutated instance cannot pass as authorization or release proof.
    """

    payload = projection.to_dict()
    if payload.get("is_runtime_authorization"):
        return False
    if payload.get("is_release_proof"):
        return False
    policy = payload.get("policy") or {}
    if not policy.get("assurance_status_is_not_runtime_authorization"):
        return False
    if not policy.get("assurance_status_is_not_release_proof"):
        return False
    for domain_payload in (payload.get("domains") or {}).values():
        authority = domain_payload.get("authority") or {}
        if not authority.get("not_runtime_authorization"):
            return False
        if not authority.get("not_release_proof"):
            return False
    return True


def required_domains_covered(projection: RuntimeAssuranceProjection) -> bool:
    """True when all five required projection domains are present."""

    return set(projection.domains.keys()) == set(PROJECTION_DOMAINS)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "ASSURANCE_POLICY",
    "BRIDGE_DIRECTION",
    "FORBIDDEN_RUNTIME_IMPORT_PREFIXES",
    "FORBIDDEN_SOURCE_MARKERS",
    "FORMAL_ASSET_INVENTORY",
    "GOAL_ID",
    "PROJECTION_DOMAINS",
    "RUNTIME_XAMAN_MODULE_FILES",
    "SCHEMA",
    "SCHEMA_VERSION",
    "TASK_ID",
    "AssuranceAuthority",
    "AssuranceStatus",
    "DomainProjection",
    "RuntimeAssuranceProjection",
    "assert_runtime_import_boundary",
    "assurance_status_is_not_authorization",
    "collect_forbidden_import_hits",
    "formal_asset_inventory",
    "formal_modules_remain_at_existing_paths",
    "iter_runtime_module_sources",
    "project_ledger_record_to_assurance",
    "project_many",
    "project_payload_to_assurance",
    "required_domains_covered",
]

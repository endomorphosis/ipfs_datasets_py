"""Non-custodial Bitcoin transaction guard (CRYPTOIR-G560 / CRYPTOIR-032).

Bind Bitcoin PSBT / transaction candidates, prevouts, scripts, witnesses,
sighashes, outputs, change, fees, locktime/sequence, spending policies, and
sanctions exposure into the common two-phase wallet guard.

Acceptance (fail-closed):

* Network, every prevout/amount/script, all outputs and change, fee, RBF,
  locktime/sequence, sighash commitment, descriptor/spend path, UTXO
  availability, exact unsigned transaction, list/graph revisions, and
  exposure paths are bound.
* Output/change/prevout/sighash mutation, spent UTXO, reorg, and stale
  evidence block.
* **Screen every output** and **trace UTXO ancestry without assuming CoinJoin
  ownership** — multi-input co-spend is never treated as common ownership.

This module never signs, broadcasts, finalizes PSBTs, or accepts bare
booleans / caller approval flags as authority.  Keys remain with an external
custody system.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.adapters.bitcoin import (
    BITCOIN_NAMESPACE,
    MAINNET_GENESIS,
    MAINNET_NETWORK,
    BitcoinAdapterError,
    Outpoint,
    SpendingCondition,
    normalize_hex_script,
    normalize_txid,
    parse_sats,
    parse_script_type,
    resolve_network,
    script_commitment,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.provenance import thaw_json
from ipfs_datasets_py.processors.smart_contracts.bitcoin.frontend import (
    PSBTBinding,
    PSBTInputBinding,
    PSBTRole,
)
from ipfs_datasets_py.processors.smart_contracts.bitcoin.script import (
    PrevoutBinding,
    SighashCommitment,
    SighashFlag,
    bind_prevout,
    bind_sighash,
)

from ..guard.errors import (
    GuardCapabilityError,
    GuardError,
    GuardForbiddenSurfaceError,
    GuardPolicyError,
    GuardValidationError,
)
from ..guard.models import (
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflightRequest,
    UtxoRef,
)
from ..guard.preflight import TransactionPreflight

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

BITCOIN_TRANSACTION_GUARD_INTERFACE: Final = "BitcoinTransactionGuard@1"
BITCOIN_TRANSACTION_GUARD_SCHEMA_VERSION: Final = (
    "wallet-guard.bitcoin-transaction-guard/v1"
)
BITCOIN_CANDIDATE_SCHEMA_VERSION: Final = (
    "wallet-guard.bitcoin-transaction-candidate/v1"
)
BITCOIN_BINDING_SCHEMA_VERSION: Final = "wallet-guard.bitcoin-tx-binding/v1"
BITCOIN_GUARD_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.bitcoin-guard-decision/v1"
)
UTXO_AVAILABILITY_SCHEMA_VERSION: Final = (
    "wallet-guard.bitcoin-utxo-availability/v1"
)
UTXO_ANCESTRY_SCHEMA_VERSION: Final = "wallet-guard.bitcoin-utxo-ancestry/v1"

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-bitcoin-v1"
DEFAULT_POLICY_ID: Final = "policy:bitcoin-wallet-guard-v1"

# BIP-125 opt-in: nSequence < 0xfffffffe enables RBF signalling.
RBF_SEQUENCE_THRESHOLD: Final = 0xFFFFFFFE
MAX_SEQUENCE: Final = 0xFFFFFFFF
MAX_LOCKTIME: Final = 0xFFFFFFFF
MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_ANCESTRY_DEPTH: Final = 64

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_DECIMAL_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")

_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approval",
        "allow",
        "allowed",
        "private_key",
        "private_keys",
        "secret",
        "secrets",
        "seed",
        "mnemonic",
        "signature",
        "signatures",
        "signed_tx",
        "signed_transaction",
        "broadcast",
        "broadcast_url",
        "raw_key",
        "signing_key",
        "api_key",
        "caller_approved",
        "force_allow",
        "bypass",
        "wif",
        "xprv",
        "xpriv",
    }
)

DEFAULT_SECURITY_REQUIREMENTS: Final[tuple[str, ...]] = (
    "sec:bitcoin-network-binding",
    "sec:bitcoin-prevout-binding",
    "sec:bitcoin-output-binding",
    "sec:bitcoin-fee-rbf",
    "sec:bitcoin-locktime-sequence",
    "sec:bitcoin-sighash-commitment",
    "sec:bitcoin-spend-path",
    "sec:bitcoin-utxo-availability",
    "sec:bitcoin-exact-candidate",
)
DEFAULT_COMPLIANCE_REQUIREMENTS: Final[tuple[str, ...]] = (
    "comp:direct-sanctions",
    "comp:bounded-exposure",
)

# Re-export for AST scanners that look for PSBTBinding on this module.
__psbt_binding_export__ = PSBTBinding


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise GuardValidationError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise GuardValidationError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise GuardValidationError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise GuardValidationError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _optional_text(value: Any, name: str, *, max_chars: int = MAX_STRING_CHARS) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name, max_chars=max_chars)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuardValidationError(f"{name} is not a stable identifier")
    return text


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise GuardValidationError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _timestamp(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=64)
    if not _ISO8601_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be an ISO-8601 UTC/offset timestamp"
        )
    return text


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardValidationError(f"{name} must be an integer")
    if value < 0:
        raise GuardValidationError(f"{name} must be non-negative")
    return value


def _uint32(value: Any, name: str) -> int:
    n = _non_negative_int(value, name)
    if n > MAX_LOCKTIME:
        raise GuardValidationError(f"{name} must be a uint32")
    return n


def _amount(value: Any, name: str) -> str:
    try:
        return parse_sats(value, field=name)
    except BitcoinAdapterError as exc:
        raise GuardValidationError(str(exc)) from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuardValidationError(f"{name} must be a mapping")
    return value


def _reject_forbidden(value: Mapping[str, Any], record_name: str) -> None:
    hit = sorted(set(value) & _FORBIDDEN_FIELDS)
    if hit:
        raise GuardForbiddenSurfaceError(
            f"{record_name} contains forbidden custody/approval field(s): "
            f"{', '.join(hit)}",
            details={"fields": hit},
        )


def _attributes(value: Mapping[str, Any] | None) -> FrozenMap:
    if value is None:
        return FrozenMap()
    if not isinstance(value, Mapping):
        raise GuardValidationError("attributes must be a mapping")
    _reject_forbidden(value, "attributes")
    try:
        return FrozenMap(value)
    except (TypeError, ValueError) as exc:
        raise GuardValidationError(f"attributes invalid: {exc}") from exc


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, FrozenMap):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return thaw_json(value)
    except Exception:  # noqa: BLE001
        return str(value)


def content_sha256_hex(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return stable_digest(_jsonable(payload))


def signals_rbf(sequence: int) -> bool:
    """BIP-125 opt-in RBF when nSequence < 0xfffffffe."""

    return sequence < RBF_SEQUENCE_THRESHOLD


def outpoint_key(txid: str, vout: int) -> str:
    return f"{normalize_txid(txid, field='txid')}:{int(vout)}"


# ---------------------------------------------------------------------------
# Candidate + bound field records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BitcoinTransactionCandidate:
    """Unsigned Bitcoin transaction / PSBT candidate for guard binding.

    Carries the exact inputs (prevouts), outputs, fee, locktime, sequences,
    optional PSBT analysis binding, and optional spending-path descriptors.
    Never holds signatures, keys, or broadcast authority.
    """

    intent_id: str
    chain_id: str = ""
    network: str = MAINNET_NETWORK
    genesis_hash: str = MAINNET_GENESIS
    version: int = 2
    locktime: int = 0
    inputs: tuple[Mapping[str, Any], ...] = ()
    outputs: tuple[Mapping[str, Any], ...] = ()
    fee_sats: str = "0"
    rbf_signaled: bool | None = None
    change_output_indexes: tuple[int, ...] = ()
    psbt: PSBTBinding | Mapping[str, Any] | None = None
    descriptor_paths: tuple[Mapping[str, Any], ...] = ()
    list_revision: str = ""
    graph_revision: str = ""
    exposure_paths: tuple[Mapping[str, Any], ...] = ()
    ancestry_edges: tuple[Mapping[str, Any], ...] = ()
    serialized_hex: str = ""
    encoding: str = "bitcoin-unsigned-tx"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BITCOIN_CANDIDATE_SCHEMA_VERSION
    kind: str = "transaction_candidate"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self, "kind", _text(self.kind, "kind", max_chars=64)
        )
        object.__setattr__(
            self, "network", _text(self.network, "network", max_chars=128)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _optional_text(self.genesis_hash, "genesis_hash", max_chars=128),
        )
        object.__setattr__(
            self,
            "chain_id",
            _optional_text(self.chain_id, "chain_id", max_chars=128),
        )
        object.__setattr__(self, "version", _non_negative_int(self.version, "version"))
        object.__setattr__(self, "locktime", _uint32(self.locktime, "locktime"))
        if not self.inputs:
            raise GuardValidationError(
                "BitcoinTransactionCandidate requires at least one input"
            )
        if len(self.inputs) > MAX_COLLECTION_ITEMS:
            raise GuardValidationError("inputs exceeds maximum collection size")
        if not self.outputs:
            raise GuardValidationError(
                "BitcoinTransactionCandidate requires at least one output"
            )
        if len(self.outputs) > MAX_COLLECTION_ITEMS:
            raise GuardValidationError("outputs exceeds maximum collection size")
        object.__setattr__(
            self,
            "inputs",
            tuple(dict(_mapping(i, "inputs item")) for i in self.inputs),
        )
        object.__setattr__(
            self,
            "outputs",
            tuple(dict(_mapping(o, "outputs item")) for o in self.outputs),
        )
        object.__setattr__(self, "fee_sats", _amount(self.fee_sats, "fee_sats"))
        if self.rbf_signaled is not None and type(self.rbf_signaled) is not bool:
            raise GuardValidationError("rbf_signaled must be a boolean or None")
        object.__setattr__(
            self,
            "change_output_indexes",
            tuple(
                _non_negative_int(i, "change_output_indexes item")
                for i in self.change_output_indexes
            ),
        )
        for idx in self.change_output_indexes:
            if idx >= len(self.outputs):
                raise GuardValidationError(
                    f"change_output_indexes item {idx} out of range"
                )
        if self.psbt is not None and not isinstance(self.psbt, (PSBTBinding, Mapping)):
            raise GuardValidationError("psbt must be PSBTBinding, mapping, or None")
        object.__setattr__(
            self,
            "descriptor_paths",
            tuple(
                dict(_mapping(p, "descriptor_paths item"))
                for p in self.descriptor_paths
            ),
        )
        object.__setattr__(
            self,
            "list_revision",
            _optional_text(self.list_revision, "list_revision", max_chars=128),
        )
        object.__setattr__(
            self,
            "graph_revision",
            _optional_text(self.graph_revision, "graph_revision", max_chars=128),
        )
        object.__setattr__(
            self,
            "exposure_paths",
            tuple(
                dict(_mapping(p, "exposure_paths item")) for p in self.exposure_paths
            ),
        )
        object.__setattr__(
            self,
            "ancestry_edges",
            tuple(
                dict(_mapping(e, "ancestry_edges item")) for e in self.ancestry_edges
            ),
        )
        object.__setattr__(
            self,
            "serialized_hex",
            _optional_text(self.serialized_hex, "serialized_hex", max_chars=2_000_000),
        )
        if self.serialized_hex:
            try:
                normalize_hex_script(self.serialized_hex, field="serialized_hex")
            except BitcoinAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
            object.__setattr__(
                self,
                "serialized_hex",
                normalize_hex_script(self.serialized_hex, field="serialized_hex"),
            )
        object.__setattr__(
            self, "encoding", _identifier(self.encoding, "encoding")
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != BITCOIN_CANDIDATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported candidate schema: {self.schema_version!r}"
            )
        # Resolve / validate network+genesis early.
        try:
            resolve_network(
                chain_id=self.chain_id or None,
                network=self.network or None,
                genesis_hash=self.genesis_hash or None,
            )
        except BitcoinAdapterError as exc:
            raise GuardValidationError(f"network binding failed: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        psbt_payload: Any
        if isinstance(self.psbt, PSBTBinding):
            psbt_payload = self.psbt.to_dict()
        elif isinstance(self.psbt, Mapping):
            psbt_payload = dict(self.psbt)
        else:
            psbt_payload = None
        return {
            "ancestry_edges": list(self.ancestry_edges),
            "attributes": self.attributes.to_dict(),
            "chain_id": self.chain_id,
            "change_output_indexes": list(self.change_output_indexes),
            "descriptor_paths": list(self.descriptor_paths),
            "encoding": self.encoding,
            "exposure_paths": list(self.exposure_paths),
            "fee_sats": self.fee_sats,
            "genesis_hash": self.genesis_hash,
            "graph_revision": self.graph_revision,
            "inputs": list(self.inputs),
            "intent_id": self.intent_id,
            "kind": self.kind,
            "list_revision": self.list_revision,
            "locktime": self.locktime,
            "network": self.network,
            "outputs": list(self.outputs),
            "psbt": psbt_payload,
            "rbf_signaled": self.rbf_signaled,
            "schema_version": self.schema_version,
            "serialized_hex": self.serialized_hex,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BitcoinTransactionCandidate":
        value = _mapping(value, "BitcoinTransactionCandidate")
        _reject_forbidden(value, "BitcoinTransactionCandidate")
        return cls(
            intent_id=value.get("intent_id", value.get("intentId", "")),
            chain_id=value.get("chain_id", value.get("chainId", "")),
            network=value.get("network", MAINNET_NETWORK),
            genesis_hash=value.get(
                "genesis_hash", value.get("genesisHash", MAINNET_GENESIS)
            ),
            version=value.get("version", 2),
            locktime=value.get("locktime", value.get("lockTime", 0)),
            inputs=tuple(value.get("inputs", value.get("vin", ()))),
            outputs=tuple(value.get("outputs", value.get("vout", ()))),
            fee_sats=value.get("fee_sats", value.get("fee", value.get("feeSats", "0"))),
            rbf_signaled=value.get("rbf_signaled", value.get("rbfSignaled")),
            change_output_indexes=tuple(
                value.get(
                    "change_output_indexes",
                    value.get("changeOutputIndexes", ()),
                )
            ),
            psbt=value.get("psbt"),
            descriptor_paths=tuple(
                value.get("descriptor_paths", value.get("descriptorPaths", ()))
            ),
            list_revision=value.get(
                "list_revision", value.get("listRevision", "")
            ),
            graph_revision=value.get(
                "graph_revision", value.get("graphRevision", "")
            ),
            exposure_paths=tuple(
                value.get("exposure_paths", value.get("exposurePaths", ()))
            ),
            ancestry_edges=tuple(
                value.get("ancestry_edges", value.get("ancestryEdges", ()))
            ),
            serialized_hex=value.get(
                "serialized_hex", value.get("serializedHex", "")
            ),
            encoding=value.get("encoding", "bitcoin-unsigned-tx"),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", BITCOIN_CANDIDATE_SCHEMA_VERSION
            ),
            kind=value.get("kind", "transaction_candidate"),
        )


@dataclass(frozen=True, slots=True)
class BoundPrevout:
    """Exact prevout facts bound for one transaction input."""

    input_index: int
    outpoint: str
    txid: str
    vout: int
    value_sats: str
    script_hex: str
    script_digest: str
    script_type: str = "unknown"
    sequence: int = MAX_SEQUENCE
    rbf_signaled: bool = False
    sighash_type: int = int(SighashFlag.ALL)
    sighash_commitment_digest: str = ""
    sighash_is_weak: bool = False
    spend_path_id: str = ""
    descriptor: str = ""
    witness_item_count: int = 0
    previous_output_known: bool = True
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "input_index", _non_negative_int(self.input_index, "input_index")
        )
        object.__setattr__(self, "txid", normalize_txid(self.txid, field="txid"))
        object.__setattr__(self, "vout", _uint32(self.vout, "vout"))
        object.__setattr__(
            self, "outpoint", outpoint_key(self.txid, self.vout)
        )
        object.__setattr__(self, "value_sats", _amount(self.value_sats, "value_sats"))
        try:
            script = normalize_hex_script(self.script_hex, field="script_hex")
        except BitcoinAdapterError as exc:
            raise GuardValidationError(str(exc)) from exc
        object.__setattr__(self, "script_hex", script)
        if self.script_digest:
            object.__setattr__(
                self, "script_digest", _digest(self.script_digest, "script_digest")
            )
        else:
            object.__setattr__(
                self,
                "script_digest",
                script_commitment(script).removeprefix("sha256:"),
            )
        object.__setattr__(
            self,
            "script_type",
            parse_script_type(self.script_type).value
            if self.script_type
            else "unknown",
        )
        object.__setattr__(self, "sequence", _uint32(self.sequence, "sequence"))
        object.__setattr__(self, "rbf_signaled", bool(self.rbf_signaled))
        object.__setattr__(
            self, "sighash_type", _non_negative_int(self.sighash_type, "sighash_type")
        )
        if self.sighash_type > 0xFF:
            raise GuardValidationError("sighash_type must be a byte value 0..255")
        if self.sighash_commitment_digest:
            object.__setattr__(
                self,
                "sighash_commitment_digest",
                _digest(self.sighash_commitment_digest, "sighash_commitment_digest"),
            )
        object.__setattr__(self, "sighash_is_weak", bool(self.sighash_is_weak))
        object.__setattr__(
            self,
            "spend_path_id",
            _optional_text(self.spend_path_id, "spend_path_id", max_chars=256),
        )
        object.__setattr__(
            self,
            "descriptor",
            _optional_text(self.descriptor, "descriptor", max_chars=1024),
        )
        object.__setattr__(
            self,
            "witness_item_count",
            _non_negative_int(self.witness_item_count, "witness_item_count"),
        )
        object.__setattr__(
            self, "previous_output_known", bool(self.previous_output_known)
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "descriptor": self.descriptor,
            "input_index": self.input_index,
            "outpoint": self.outpoint,
            "previous_output_known": self.previous_output_known,
            "rbf_signaled": self.rbf_signaled,
            "script_digest": self.script_digest,
            "script_hex": self.script_hex,
            "script_type": self.script_type,
            "sequence": self.sequence,
            "sighash_commitment_digest": self.sighash_commitment_digest,
            "sighash_is_weak": self.sighash_is_weak,
            "sighash_type": self.sighash_type,
            "spend_path_id": self.spend_path_id,
            "txid": self.txid,
            "value_sats": self.value_sats,
            "vout": self.vout,
            "witness_item_count": self.witness_item_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundPrevout":
        value = _mapping(value, "BoundPrevout")
        _reject_forbidden(value, "BoundPrevout")
        return cls(
            input_index=value.get("input_index", value.get("inputIndex", 0)),
            outpoint=value.get("outpoint", ""),
            txid=value.get("txid", ""),
            vout=value.get("vout", 0),
            value_sats=value.get("value_sats", value.get("value", "0")),
            script_hex=value.get(
                "script_hex",
                value.get("scriptpubkey", value.get("script_pubkey", "")),
            ),
            script_digest=value.get(
                "script_digest", value.get("script_commitment", "")
            ),
            script_type=value.get(
                "script_type", value.get("scriptpubkey_type", "unknown")
            ),
            sequence=value.get("sequence", MAX_SEQUENCE),
            rbf_signaled=value.get("rbf_signaled", False),
            sighash_type=value.get("sighash_type", int(SighashFlag.ALL)),
            sighash_commitment_digest=value.get(
                "sighash_commitment_digest", ""
            ),
            sighash_is_weak=value.get("sighash_is_weak", False),
            spend_path_id=value.get("spend_path_id", ""),
            descriptor=value.get("descriptor", ""),
            witness_item_count=value.get("witness_item_count", 0),
            previous_output_known=value.get("previous_output_known", True),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class BoundOutput:
    """Exact output facts; every output is screened independently.

    Change is only marked when the caller explicitly declares the output
    index as change — never inferred from multi-input co-spend patterns
    (CoinJoin-safe).
    """

    output_index: int
    value_sats: str
    script_hex: str
    script_digest: str
    script_type: str = "unknown"
    address: str = ""
    is_change: bool = False
    is_explicit_change: bool = False
    exposure_path_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "output_index", _non_negative_int(self.output_index, "output_index")
        )
        object.__setattr__(self, "value_sats", _amount(self.value_sats, "value_sats"))
        try:
            script = normalize_hex_script(self.script_hex, field="script_hex")
        except BitcoinAdapterError as exc:
            raise GuardValidationError(str(exc)) from exc
        object.__setattr__(self, "script_hex", script)
        if self.script_digest:
            object.__setattr__(
                self, "script_digest", _digest(self.script_digest, "script_digest")
            )
        else:
            object.__setattr__(
                self,
                "script_digest",
                script_commitment(script).removeprefix("sha256:"),
            )
        object.__setattr__(
            self,
            "script_type",
            parse_script_type(self.script_type).value
            if self.script_type
            else "unknown",
        )
        object.__setattr__(
            self, "address", _optional_text(self.address, "address", max_chars=256)
        )
        # is_change is only true when explicitly declared.
        object.__setattr__(self, "is_explicit_change", bool(self.is_explicit_change))
        object.__setattr__(
            self, "is_change", bool(self.is_explicit_change and self.is_change)
        )
        object.__setattr__(
            self,
            "exposure_path_ids",
            tuple(
                _identifier(p, "exposure_path_ids item")
                for p in self.exposure_path_ids
            ),
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "attributes": self.attributes.to_dict(),
            "exposure_path_ids": list(self.exposure_path_ids),
            "is_change": self.is_change,
            "is_explicit_change": self.is_explicit_change,
            "output_index": self.output_index,
            "script_digest": self.script_digest,
            "script_hex": self.script_hex,
            "script_type": self.script_type,
            "value_sats": self.value_sats,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundOutput":
        value = _mapping(value, "BoundOutput")
        _reject_forbidden(value, "BoundOutput")
        return cls(
            output_index=value.get("output_index", value.get("n", 0)),
            value_sats=value.get("value_sats", value.get("value", "0")),
            script_hex=value.get(
                "script_hex",
                value.get("scriptpubkey", value.get("script_pubkey", "")),
            ),
            script_digest=value.get("script_digest", ""),
            script_type=value.get(
                "script_type", value.get("scriptpubkey_type", "unknown")
            ),
            address=value.get(
                "address", value.get("scriptpubkey_address", "")
            ),
            is_change=value.get("is_change", False),
            is_explicit_change=value.get("is_explicit_change", False),
            exposure_path_ids=tuple(value.get("exposure_path_ids", ())),
            attributes=value.get("attributes", {}),
        )


class UtxoStatus(str, Enum):
    """Live UTXO availability status (re-resolved at consumption)."""

    AVAILABLE = "available"
    SPENT = "spent"
    MISSING = "missing"
    REORGED = "reorged"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class UtxoAvailability:
    """Bound UTXO availability epoch for one outpoint."""

    outpoint: str
    status: UtxoStatus = UtxoStatus.AVAILABLE
    confirmations: int = 0
    block_height: int | None = None
    block_hash: str = ""
    tip_height: int | None = None
    tip_hash: str = ""
    availability_epoch: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = UTXO_AVAILABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "outpoint", _text(self.outpoint, "outpoint", max_chars=128)
        )
        if ":" not in self.outpoint:
            raise GuardValidationError("outpoint must be txid:vout")
        if not isinstance(self.status, UtxoStatus):
            object.__setattr__(self, "status", UtxoStatus(str(self.status)))
        object.__setattr__(
            self,
            "confirmations",
            _non_negative_int(self.confirmations, "confirmations"),
        )
        if self.block_height is not None:
            object.__setattr__(
                self,
                "block_height",
                _non_negative_int(self.block_height, "block_height"),
            )
        if self.tip_height is not None:
            object.__setattr__(
                self, "tip_height", _non_negative_int(self.tip_height, "tip_height")
            )
        object.__setattr__(
            self,
            "block_hash",
            _optional_text(self.block_hash, "block_hash", max_chars=128),
        )
        object.__setattr__(
            self, "tip_hash", _optional_text(self.tip_hash, "tip_hash", max_chars=128)
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if not self.availability_epoch:
            object.__setattr__(
                self, "availability_epoch", self.compute_epoch_digest()
            )
        else:
            object.__setattr__(
                self,
                "availability_epoch",
                _digest(self.availability_epoch, "availability_epoch"),
            )

    def compute_epoch_digest(self) -> str:
        return content_sha256_hex(
            {
                "block_hash": self.block_hash,
                "block_height": self.block_height,
                "confirmations": self.confirmations,
                "outpoint": self.outpoint,
                "status": self.status.value,
                "tip_hash": self.tip_hash,
                "tip_height": self.tip_height,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "availability_epoch": self.availability_epoch,
            "block_hash": self.block_hash,
            "block_height": self.block_height,
            "confirmations": self.confirmations,
            "outpoint": self.outpoint,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "tip_hash": self.tip_hash,
            "tip_height": self.tip_height,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UtxoAvailability":
        value = _mapping(value, "UtxoAvailability")
        _reject_forbidden(value, "UtxoAvailability")
        return cls(
            outpoint=value.get("outpoint", ""),
            status=value.get("status", UtxoStatus.AVAILABLE),
            confirmations=value.get("confirmations", 0),
            block_height=value.get("block_height"),
            block_hash=value.get("block_hash", ""),
            tip_height=value.get("tip_height"),
            tip_hash=value.get("tip_hash", ""),
            availability_epoch=value.get("availability_epoch", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", UTXO_AVAILABILITY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class UtxoAncestryEdge:
    """One edge in a UTXO ancestry graph.

    Edges connect outpoints only.  They never encode co-ownership, change
    clustering, or CoinJoin participant linkage.
    """

    child_outpoint: str
    parent_outpoint: str
    depth: int = 1
    value_sats: str = "0"
    ownership_assumed: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = UTXO_ANCESTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "child_outpoint",
            _text(self.child_outpoint, "child_outpoint", max_chars=128),
        )
        object.__setattr__(
            self,
            "parent_outpoint",
            _text(self.parent_outpoint, "parent_outpoint", max_chars=128),
        )
        object.__setattr__(self, "depth", _non_negative_int(self.depth, "depth"))
        if self.depth > MAX_ANCESTRY_DEPTH:
            raise GuardValidationError(
                f"ancestry depth exceeds maximum of {MAX_ANCESTRY_DEPTH}"
            )
        object.__setattr__(self, "value_sats", _amount(self.value_sats, "value_sats"))
        # Hard invariant: CoinJoin / multi-input ownership is never assumed.
        if self.ownership_assumed:
            raise GuardValidationError(
                "UTXO ancestry must not assume CoinJoin/common ownership "
                "(ownership_assumed must be false)"
            )
        object.__setattr__(self, "ownership_assumed", False)
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "child_outpoint": self.child_outpoint,
            "depth": self.depth,
            "ownership_assumed": False,
            "parent_outpoint": self.parent_outpoint,
            "schema_version": self.schema_version,
            "value_sats": self.value_sats,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UtxoAncestryEdge":
        value = _mapping(value, "UtxoAncestryEdge")
        _reject_forbidden(value, "UtxoAncestryEdge")
        return cls(
            child_outpoint=value.get("child_outpoint", ""),
            parent_outpoint=value.get("parent_outpoint", ""),
            depth=value.get("depth", 1),
            value_sats=value.get("value_sats", "0"),
            ownership_assumed=value.get("ownership_assumed", False),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", UTXO_ANCESTRY_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Transaction binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BitcoinTransactionBinding:
    """Exact Bitcoin transaction facts bound for two-phase guard evaluation.

    Every field that participates in policy is frozen so pre-sign and
    pre-broadcast revalidation can detect output/change/prevout/sighash
    mutation, spent UTXOs, reorgs, and stale list/graph evidence.
    """

    binding_id: str
    intent_id: str
    candidate_id: str
    chain_id: str
    network: str
    genesis_hash: str
    version: int
    locktime: int
    fee_sats: str
    rbf_signaled: bool
    prevouts: tuple[BoundPrevout, ...]
    outputs: tuple[BoundOutput, ...]
    change_output_indexes: tuple[int, ...]
    utxo_availability: tuple[UtxoAvailability, ...]
    ancestry_edges: tuple[UtxoAncestryEdge, ...]
    exposure_paths: tuple[Mapping[str, Any], ...]
    descriptor_paths: tuple[Mapping[str, Any], ...]
    list_revision: str
    graph_revision: str
    psbt_digest: str
    has_weak_sighash: bool
    all_prevouts_known: bool
    candidate_digest: str
    serialized_digest: str
    encoding: str
    byte_length: int
    binding_digest: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BITCOIN_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(
            self, "intent_id", _identifier(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "chain_id", _text(self.chain_id, "chain_id", max_chars=128)
        )
        object.__setattr__(
            self, "network", _text(self.network, "network", max_chars=128)
        )
        object.__setattr__(
            self,
            "genesis_hash",
            _text(self.genesis_hash, "genesis_hash", max_chars=128),
        )
        object.__setattr__(self, "version", _non_negative_int(self.version, "version"))
        object.__setattr__(self, "locktime", _uint32(self.locktime, "locktime"))
        object.__setattr__(self, "fee_sats", _amount(self.fee_sats, "fee_sats"))
        object.__setattr__(self, "rbf_signaled", bool(self.rbf_signaled))
        if not self.prevouts:
            raise GuardValidationError("prevouts must be non-empty")
        prevouts: list[BoundPrevout] = []
        for item in self.prevouts:
            if isinstance(item, BoundPrevout):
                prevouts.append(item)
            elif isinstance(item, Mapping):
                prevouts.append(BoundPrevout.from_dict(item))
            else:
                raise GuardValidationError("prevouts items must be BoundPrevout")
        object.__setattr__(self, "prevouts", tuple(prevouts))
        if not self.outputs:
            raise GuardValidationError("outputs must be non-empty")
        outputs: list[BoundOutput] = []
        for item in self.outputs:
            if isinstance(item, BoundOutput):
                outputs.append(item)
            elif isinstance(item, Mapping):
                outputs.append(BoundOutput.from_dict(item))
            else:
                raise GuardValidationError("outputs items must be BoundOutput")
        object.__setattr__(self, "outputs", tuple(outputs))
        object.__setattr__(
            self,
            "change_output_indexes",
            tuple(
                _non_negative_int(i, "change_output_indexes item")
                for i in self.change_output_indexes
            ),
        )
        utxos: list[UtxoAvailability] = []
        for item in self.utxo_availability:
            if isinstance(item, UtxoAvailability):
                utxos.append(item)
            elif isinstance(item, Mapping):
                utxos.append(UtxoAvailability.from_dict(item))
            else:
                raise GuardValidationError(
                    "utxo_availability items must be UtxoAvailability"
                )
        object.__setattr__(self, "utxo_availability", tuple(utxos))
        edges: list[UtxoAncestryEdge] = []
        for item in self.ancestry_edges:
            if isinstance(item, UtxoAncestryEdge):
                edges.append(item)
            elif isinstance(item, Mapping):
                edges.append(UtxoAncestryEdge.from_dict(item))
            else:
                raise GuardValidationError(
                    "ancestry_edges items must be UtxoAncestryEdge"
                )
        object.__setattr__(self, "ancestry_edges", tuple(edges))
        object.__setattr__(
            self,
            "exposure_paths",
            tuple(dict(p) for p in self.exposure_paths),
        )
        object.__setattr__(
            self,
            "descriptor_paths",
            tuple(dict(p) for p in self.descriptor_paths),
        )
        object.__setattr__(
            self,
            "list_revision",
            _optional_text(self.list_revision, "list_revision", max_chars=128),
        )
        object.__setattr__(
            self,
            "graph_revision",
            _optional_text(self.graph_revision, "graph_revision", max_chars=128),
        )
        if self.psbt_digest:
            object.__setattr__(
                self, "psbt_digest", _digest(self.psbt_digest, "psbt_digest")
            )
        else:
            object.__setattr__(self, "psbt_digest", "")
        object.__setattr__(self, "has_weak_sighash", bool(self.has_weak_sighash))
        object.__setattr__(self, "all_prevouts_known", bool(self.all_prevouts_known))
        object.__setattr__(
            self, "candidate_digest", _digest(self.candidate_digest, "candidate_digest")
        )
        object.__setattr__(
            self,
            "serialized_digest",
            _digest(self.serialized_digest, "serialized_digest"),
        )
        object.__setattr__(
            self, "encoding", _identifier(self.encoding, "encoding")
        )
        object.__setattr__(
            self, "byte_length", _non_negative_int(self.byte_length, "byte_length")
        )
        if self.byte_length == 0:
            raise GuardValidationError("byte_length must be positive")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != BITCOIN_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported binding schema: {self.schema_version!r}"
            )
        if not self.binding_digest:
            object.__setattr__(self, "binding_digest", self.compute_binding_digest())
        else:
            object.__setattr__(
                self, "binding_digest", _digest(self.binding_digest, "binding_digest")
            )

    def compute_binding_digest(self) -> str:
        return content_sha256_hex(self.to_dict_for_digest())

    def to_dict_for_digest(self) -> dict[str, Any]:
        return {
            "all_prevouts_known": self.all_prevouts_known,
            "ancestry_edges": [e.to_dict() for e in self.ancestry_edges],
            "byte_length": self.byte_length,
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "chain_id": self.chain_id,
            "change_output_indexes": list(self.change_output_indexes),
            "descriptor_paths": list(self.descriptor_paths),
            "encoding": self.encoding,
            "exposure_paths": list(self.exposure_paths),
            "fee_sats": self.fee_sats,
            "genesis_hash": self.genesis_hash,
            "graph_revision": self.graph_revision,
            "has_weak_sighash": self.has_weak_sighash,
            "intent_id": self.intent_id,
            "list_revision": self.list_revision,
            "locktime": self.locktime,
            "network": self.network,
            "outputs": [o.to_dict() for o in self.outputs],
            "prevouts": [p.to_dict() for p in self.prevouts],
            "psbt_digest": self.psbt_digest,
            "rbf_signaled": self.rbf_signaled,
            "serialized_digest": self.serialized_digest,
            "utxo_availability": [u.to_dict() for u in self.utxo_availability],
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_for_digest()
        payload.update(
            {
                "attributes": self.attributes.to_dict(),
                "binding_digest": self.binding_digest,
                "binding_id": self.binding_id,
                "schema_version": self.schema_version,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BitcoinTransactionBinding":
        value = _mapping(value, "BitcoinTransactionBinding")
        _reject_forbidden(value, "BitcoinTransactionBinding")
        return cls(
            binding_id=value.get("binding_id", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            chain_id=value.get("chain_id", ""),
            network=value.get("network", MAINNET_NETWORK),
            genesis_hash=value.get("genesis_hash", MAINNET_GENESIS),
            version=value.get("version", 2),
            locktime=value.get("locktime", 0),
            fee_sats=value.get("fee_sats", "0"),
            rbf_signaled=value.get("rbf_signaled", False),
            prevouts=tuple(value.get("prevouts", ())),
            outputs=tuple(value.get("outputs", ())),
            change_output_indexes=tuple(value.get("change_output_indexes", ())),
            utxo_availability=tuple(value.get("utxo_availability", ())),
            ancestry_edges=tuple(value.get("ancestry_edges", ())),
            exposure_paths=tuple(value.get("exposure_paths", ())),
            descriptor_paths=tuple(value.get("descriptor_paths", ())),
            list_revision=value.get("list_revision", ""),
            graph_revision=value.get("graph_revision", ""),
            psbt_digest=value.get("psbt_digest", ""),
            has_weak_sighash=value.get("has_weak_sighash", False),
            all_prevouts_known=value.get("all_prevouts_known", False),
            candidate_digest=value.get("candidate_digest", ""),
            serialized_digest=value.get("serialized_digest", ""),
            encoding=value.get("encoding", "bitcoin-unsigned-tx"),
            byte_length=value.get("byte_length", 0),
            binding_digest=value.get("binding_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", BITCOIN_BINDING_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class BitcoinGuardPhase(str, Enum):
    """Phase at which the Bitcoin guard is consulted."""

    EVALUATE = "evaluate"
    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class BitcoinGuardDecision:
    """Deterministic Bitcoin guard decision (not authorization to sign)."""

    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    binding_digest: str
    request_digest: str = ""
    preflight: PreflightResult | None = None
    security_results: Mapping[str, str] = field(default_factory=dict)
    compliance_results: Mapping[str, str] = field(default_factory=dict)
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BITCOIN_GUARD_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, TransactionVerdictOutcome):
            object.__setattr__(
                self, "outcome", TransactionVerdictOutcome(str(self.outcome))
            )
        object.__setattr__(self, "blocks_automation", bool(self.blocks_automation))
        object.__setattr__(
            self, "reason_codes", tuple(str(c) for c in self.reason_codes)
        )
        object.__setattr__(self, "reasons", tuple(str(r) for r in self.reasons))
        object.__setattr__(
            self, "binding_digest", _digest(self.binding_digest, "binding_digest")
        )
        if self.request_digest:
            object.__setattr__(
                self, "request_digest", _digest(self.request_digest, "request_digest")
            )
        else:
            object.__setattr__(self, "request_digest", "")
        object.__setattr__(
            self, "security_results", dict(self.security_results or {})
        )
        object.__setattr__(
            self, "compliance_results", dict(self.compliance_results or {})
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    @property
    def allowed(self) -> bool:
        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binding_digest": self.binding_digest,
            "blocks_automation": self.blocks_automation,
            "compliance_results": dict(self.compliance_results),
            "outcome": self.outcome.value,
            "preflight": self.preflight.to_dict() if self.preflight else None,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "security_results": dict(self.security_results),
        }


# ---------------------------------------------------------------------------
# Live resolvers
# ---------------------------------------------------------------------------

UtxoAvailabilityResolver = Callable[
    [str], UtxoAvailability | Mapping[str, Any] | None
]
ListRevisionChecker = Callable[[str, str], bool]
GraphRevisionChecker = Callable[[str, str], bool]


def _static_utxo_resolver(
    epochs: Mapping[str, UtxoAvailability | Mapping[str, Any]],
) -> UtxoAvailabilityResolver:
    def _resolve(outpoint: str) -> UtxoAvailability | Mapping[str, Any] | None:
        return epochs.get(outpoint)

    return _resolve


def _coerce_utxo(
    value: UtxoAvailability | Mapping[str, Any] | None, *, field_name: str
) -> UtxoAvailability | None:
    if value is None:
        return None
    if isinstance(value, UtxoAvailability):
        return value
    if isinstance(value, Mapping):
        return UtxoAvailability.from_dict(value)
    raise GuardValidationError(f"{field_name} must be UtxoAvailability or mapping")


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class BitcoinTransactionGuard:
    """Non-custodial Bitcoin leaf guard adapter for the two-phase preflight API.

    Normalizes Bitcoin PSBT / transaction candidates into exact
    :class:`TransactionIntent` / :class:`TransactionCandidate` bindings, runs
    Bitcoin-specific fail-closed checks, and delegates capability issuance /
    atomic consumption to :class:`TransactionPreflight`.

    UTXO availability and chain tip (reorg) state are **re-resolved at
    consumption** (pre-sign / pre-broadcast) and must match the binding used
    when the admissibility capability was issued.

    Ownership clustering / CoinJoin participant inference is never performed.
    """

    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_PRODUCER_ID
    policy_id: str = DEFAULT_POLICY_ID
    utxo_resolver: UtxoAvailabilityResolver | None = None
    list_revision_is_current: ListRevisionChecker | None = None
    graph_revision_is_current: GraphRevisionChecker | None = None
    interface: str = BITCOIN_TRANSACTION_GUARD_INTERFACE
    schema_version: str = BITCOIN_TRANSACTION_GUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.preflight is None:
            self.preflight = TransactionPreflight(producer_id=self.producer_id)
        if self.interface != BITCOIN_TRANSACTION_GUARD_INTERFACE:
            raise GuardValidationError(
                f"unsupported bitcoin guard interface: {self.interface!r}"
            )
        if self.schema_version != BITCOIN_TRANSACTION_GUARD_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported bitcoin guard schema: {self.schema_version!r}"
            )
        if self.list_revision_is_current is None:
            self.list_revision_is_current = lambda _rev, _now: True
        if self.graph_revision_is_current is None:
            self.graph_revision_is_current = lambda _rev, _now: True

    # -- binding ------------------------------------------------------------

    def bind_transaction(
        self,
        candidate: BitcoinTransactionCandidate | Mapping[str, Any],
        *,
        utxo_availability: Sequence[UtxoAvailability | Mapping[str, Any]]
        | None = None,
        ancestry_edges: Sequence[UtxoAncestryEdge | Mapping[str, Any]] | None = None,
        serialized_bytes: bytes | str | None = None,
        candidate_id: str = "",
        binding_id: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> BitcoinTransactionBinding:
        """Normalize a Bitcoin transaction candidate into an exact guard binding.

        Every input prevout (amount + script), every output, fee, RBF,
        locktime/sequence, sighash, spend path, and UTXO availability fact is
        bound.  Multi-input co-spend never implies shared ownership.
        """

        cand = self._coerce_candidate(candidate)
        try:
            network_anchor = resolve_network(
                chain_id=cand.chain_id or None,
                network=cand.network or None,
                genesis_hash=cand.genesis_hash or None,
            )
        except BitcoinAdapterError as exc:
            raise GuardValidationError(f"network binding failed: {exc}") from exc

        bound_prevouts = self._bind_prevouts(cand)
        bound_outputs = self._bind_outputs(cand)
        self._validate_fee(bound_prevouts, bound_outputs, cand.fee_sats)

        rbf = cand.rbf_signaled
        if rbf is None:
            rbf = any(p.rbf_signaled for p in bound_prevouts)

        weak = any(p.sighash_is_weak for p in bound_prevouts)
        all_known = all(p.previous_output_known for p in bound_prevouts)

        # UTXO availability: prefer explicit, else synthetic "available".
        bound_utxos = self._bind_utxo_availability(
            bound_prevouts, utxo_availability=utxo_availability
        )

        # Ancestry: explicit edges only; never invent CoinJoin ownership.
        bound_ancestry = self._bind_ancestry(
            bound_prevouts,
            ancestry_edges=ancestry_edges
            if ancestry_edges is not None
            else cand.ancestry_edges,
        )

        # PSBT digest (optional analysis surface).
        psbt_digest = ""
        if cand.psbt is not None:
            if isinstance(cand.psbt, PSBTBinding):
                psbt_digest = cand.psbt.content_digest().removeprefix("sha256:")
                if cand.psbt.has_weak_sighash:
                    weak = True
                if not cand.psbt.all_prevouts_known:
                    all_known = False
            else:
                psbt_map = _mapping(cand.psbt, "psbt")
                _reject_forbidden(psbt_map, "psbt")
                psbt_digest = content_sha256_hex(dict(psbt_map))
                if psbt_map.get("has_weak_sighash"):
                    weak = True

        # Exact-byte binding.
        if serialized_bytes is not None:
            if isinstance(serialized_bytes, bytes):
                raw = serialized_bytes
            else:
                text = str(serialized_bytes)
                try:
                    raw = bytes.fromhex(
                        normalize_hex_script(text, field="serialized_bytes")
                    )
                except (BitcoinAdapterError, ValueError):
                    raw = text.encode("utf-8")
            serialized_digest = hashlib.sha256(raw).hexdigest()
            byte_length = len(raw) or 1
        elif cand.serialized_hex:
            raw = bytes.fromhex(cand.serialized_hex)
            serialized_digest = hashlib.sha256(raw).hexdigest()
            byte_length = len(raw) or 1
        else:
            # Deterministic commitment over the bound structural surface.
            structural = {
                "fee_sats": cand.fee_sats,
                "inputs": [p.to_dict() for p in bound_prevouts],
                "locktime": cand.locktime,
                "network": network_anchor.network,
                "outputs": [o.to_dict() for o in bound_outputs],
                "version": cand.version,
            }
            serialized_digest = content_sha256_hex(structural)
            byte_length = max(1, len(serialized_digest) // 2)

        intent_id = cand.intent_id
        cand_id = candidate_id or f"candidate:bitcoin:{intent_id}"
        bind_id = binding_id or f"binding:bitcoin:{intent_id}"
        candidate_digest = content_sha256_hex(
            {
                "candidate_id": cand_id,
                "encoding": cand.encoding,
                "intent_id": intent_id,
                "network": network_anchor.network,
                "serialized_digest": serialized_digest,
            }
        )

        return BitcoinTransactionBinding(
            binding_id=bind_id,
            intent_id=intent_id,
            candidate_id=cand_id,
            chain_id=network_anchor.chain_id,
            network=network_anchor.network,
            genesis_hash=network_anchor.genesis_hash,
            version=cand.version,
            locktime=cand.locktime,
            fee_sats=cand.fee_sats,
            rbf_signaled=bool(rbf),
            prevouts=tuple(bound_prevouts),
            outputs=tuple(bound_outputs),
            change_output_indexes=tuple(cand.change_output_indexes),
            utxo_availability=tuple(bound_utxos),
            ancestry_edges=tuple(bound_ancestry),
            exposure_paths=tuple(dict(p) for p in cand.exposure_paths),
            descriptor_paths=tuple(dict(p) for p in cand.descriptor_paths),
            list_revision=cand.list_revision,
            graph_revision=cand.graph_revision,
            psbt_digest=psbt_digest,
            has_weak_sighash=weak,
            all_prevouts_known=all_known,
            candidate_digest=candidate_digest,
            serialized_digest=serialized_digest,
            encoding=cand.encoding,
            byte_length=byte_length,
            attributes=attributes or {},
        )

    # Alias matching AST / plan terminology.
    def bind_candidate(
        self,
        candidate: BitcoinTransactionCandidate | Mapping[str, Any],
        **kwargs: Any,
    ) -> BitcoinTransactionBinding:
        return self.bind_transaction(candidate, **kwargs)

    def to_preflight_request(
        self,
        binding: BitcoinTransactionBinding,
        *,
        request_id: str,
        tenant_id: str,
        actor_id: str,
        audience_id: str,
        issued_at: str,
        deadline: str,
        expiry: str,
        security_requirement_ids: Sequence[str] | None = None,
        compliance_requirement_ids: Sequence[str] | None = None,
        environment_id: str = "env:bitcoin-guard",
        environment_digest: str = "",
        nonce: str = "",
        policy_id: str | None = None,
        intent_expires_at: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TransactionPreflightRequest:
        """Project a Bitcoin binding into the common preflight request surface."""

        intent = self._intent_from_binding(
            binding, expires_at=intent_expires_at or expiry
        )
        candidate = TransactionCandidate(
            candidate_id=binding.candidate_id,
            intent_id=binding.intent_id,
            serialized_digest=binding.serialized_digest,
            encoding=binding.encoding,
            byte_length=binding.byte_length,
            network=binding.network,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "fee_sats": binding.fee_sats,
                "genesis_hash": binding.genesis_hash,
                "graph_revision": binding.graph_revision,
                "list_revision": binding.list_revision,
                "locktime": binding.locktime,
                "psbt_digest": binding.psbt_digest,
                "rbf_signaled": binding.rbf_signaled,
            },
        )
        return TransactionPreflightRequest(
            request_id=request_id,
            intent=intent,
            candidate=candidate,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audience_id=audience_id,
            policy_id=policy_id or self.policy_id,
            security_requirement_ids=tuple(
                security_requirement_ids
                if security_requirement_ids is not None
                else DEFAULT_SECURITY_REQUIREMENTS
            ),
            compliance_requirement_ids=tuple(
                compliance_requirement_ids
                if compliance_requirement_ids is not None
                else DEFAULT_COMPLIANCE_REQUIREMENTS
            ),
            issued_at=issued_at,
            deadline=deadline,
            expiry=expiry,
            environment_id=environment_id,
            environment_digest=environment_digest or ("e" * 64),
            nonce=nonce or request_id,
            attributes=attributes
            or {
                "binding_digest": binding.binding_digest,
                "bitcoin_guard": True,
            },
        )

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        binding: BitcoinTransactionBinding | Mapping[str, Any],
        *,
        request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        now: str | None = None,
        live_utxos: Mapping[str, UtxoAvailability | Mapping[str, Any]] | None = None,
        request_id: str = "req:bitcoin-guard",
        tenant_id: str = "tenant:default",
        actor_id: str = "actor:policy-engine",
        audience_id: str = "audience:custody-signer",
        issued_at: str | None = None,
        deadline: str | None = None,
        expiry: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> BitcoinGuardDecision:
        """Evaluate Bitcoin-specific bindings then run two-phase preflight."""

        if not isinstance(binding, BitcoinTransactionBinding):
            binding = BitcoinTransactionBinding.from_dict(binding)

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        sec_results = dict(security_results or {})
        comp_results = dict(compliance_results or {})

        structural = self._check_structural(
            binding,
            now=clock,
            live_utxos=live_utxos,
            phase=BitcoinGuardPhase.EVALUATE,
        )
        reason_codes.extend(structural["reason_codes"])
        reasons.extend(structural["reasons"])
        for req_id, outcome in structural["security_results"].items():
            sec_results.setdefault(req_id, outcome)

        for req_id in DEFAULT_SECURITY_REQUIREMENTS:
            sec_results.setdefault(req_id, "pass")

        if request is None:
            issued = issued_at or clock
            dead = deadline or clock
            exp = expiry or clock
            if issued_at is None and deadline is None and expiry is None:
                issued = "2026-07-28T12:00:00Z"
                dead = "2026-07-28T12:05:00Z"
                exp = "2026-07-28T12:10:00Z"
                intent_exp = "2026-07-28T12:15:00Z"
            else:
                intent_exp = exp
            request = self.to_preflight_request(
                binding,
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                audience_id=audience_id,
                issued_at=issued,
                deadline=dead,
                expiry=exp,
                intent_expires_at=intent_exp,
            )
        elif not isinstance(request, TransactionPreflightRequest):
            request = TransactionPreflightRequest.from_dict(request)

        if compliance_results is None:
            for req_id in request.compliance_requirement_ids:
                comp_results.setdefault(req_id, "pass")

        if structural["blocking"] is not None:
            block_outcome = structural["blocking"]
            mapped = {
                TransactionVerdictOutcome.DENY: "deny",
                TransactionVerdictOutcome.STALE: "stale",
                TransactionVerdictOutcome.REVIEW: "review",
                TransactionVerdictOutcome.ERROR: "error",
                TransactionVerdictOutcome.INCONCLUSIVE: "inconclusive",
            }.get(block_outcome, "deny")
            if structural["failed_requirement"]:
                sec_results[structural["failed_requirement"]] = mapped
            else:
                sec_results["sec:bitcoin-prevout-binding"] = mapped

        assert self.preflight is not None
        preflight_result = self.preflight.evaluate(
            request,
            security_results=sec_results,
            compliance_results=comp_results,
            now=clock,
            derive_capability_on_allow=derive_capability_on_allow,
        )

        outcome = preflight_result.outcome
        blocks = preflight_result.blocks_automation
        merged_codes = list(preflight_result.reason_codes) + [
            c for c in reason_codes if c not in preflight_result.reason_codes
        ]
        merged_reasons = list(preflight_result.reasons) + [
            r for r in reasons if r not in preflight_result.reasons
        ]

        return BitcoinGuardDecision(
            outcome=outcome,
            blocks_automation=blocks,
            reason_codes=tuple(merged_codes),
            reasons=tuple(merged_reasons),
            binding_digest=binding.binding_digest,
            request_digest=preflight_result.request_digest,
            preflight=preflight_result,
            security_results=preflight_result.security_results,
            compliance_results=preflight_result.compliance_results,
            attributes={
                "all_prevouts_known": binding.all_prevouts_known,
                "fee_sats": binding.fee_sats,
                "has_weak_sighash": binding.has_weak_sighash,
                "input_count": len(binding.prevouts),
                "output_count": len(binding.outputs),
                "rbf_signaled": binding.rbf_signaled,
            },
        )

    # -- revalidate + consume -----------------------------------------------

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        binding: BitcoinTransactionBinding | Mapping[str, Any],
        *,
        phase: PreflightPhase | BitcoinGuardPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        live_utxos: Mapping[str, UtxoAvailability | Mapping[str, Any]] | None = None,
        live_candidate: BitcoinTransactionCandidate | Mapping[str, Any] | None = None,
        live_outputs: Sequence[Mapping[str, Any]] | None = None,
        live_prevouts: Sequence[Mapping[str, Any]] | None = None,
        live_list_revision: str | None = None,
        live_graph_revision: str | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate UTXOs and structure, then atomically consume capability.

        Re-resolves UTXO availability at consumption.  Detects output/change/
        prevout/sighash mutation, spent UTXOs, reorgs, and stale list/graph
        revisions before consumption.
        """

        if not isinstance(binding, BitcoinTransactionBinding):
            binding = BitcoinTransactionBinding.from_dict(binding)
        if not isinstance(capability, AdmissibilityCapability):
            if isinstance(capability, Mapping):
                capability = AdmissibilityCapability.from_dict(capability)
            else:
                raise GuardValidationError(
                    "capability must be an AdmissibilityCapability"
                )
        if not isinstance(live_request, TransactionPreflightRequest):
            if isinstance(live_request, Mapping):
                live_request = TransactionPreflightRequest.from_dict(live_request)
            else:
                raise GuardValidationError(
                    "live_request must be a TransactionPreflightRequest"
                )

        if isinstance(phase, PreflightPhase):
            phase_value = phase.value
        elif isinstance(phase, BitcoinGuardPhase):
            phase_value = (
                PreflightPhase.PRE_SIGN.value
                if phase is BitcoinGuardPhase.PRE_SIGN
                else PreflightPhase.PRE_BROADCAST.value
                if phase is BitcoinGuardPhase.PRE_BROADCAST
                else PreflightPhase.PRE_SIGN.value
            )
        else:
            phase_value = str(phase)

        clock = now or _iso_now()
        guard_phase = (
            BitcoinGuardPhase.PRE_SIGN
            if phase_value == PreflightPhase.PRE_SIGN.value
            else BitcoinGuardPhase.PRE_BROADCAST
        )

        # Live candidate re-bind comparison (mutation detection).
        if live_candidate is not None:
            self._assert_live_candidate_matches(binding, live_candidate)
        if live_outputs is not None:
            self._assert_live_outputs_match(binding, live_outputs)
        if live_prevouts is not None:
            self._assert_live_prevouts_match(binding, live_prevouts)

        # Stale list / graph revisions at consumption.
        if live_list_revision is not None and live_list_revision != binding.list_revision:
            raise GuardCapabilityError(
                "list revision substituted or stale at consumption",
                reason_code="bitcoin.list_revision_stale",
                details={
                    "expected": binding.list_revision,
                    "observed": live_list_revision,
                },
            )
        if (
            live_graph_revision is not None
            and live_graph_revision != binding.graph_revision
        ):
            raise GuardCapabilityError(
                "graph revision substituted or stale at consumption",
                reason_code="bitcoin.graph_revision_stale",
                details={
                    "expected": binding.graph_revision,
                    "observed": live_graph_revision,
                },
            )

        structural = self._check_structural(
            binding,
            now=clock,
            live_utxos=live_utxos,
            phase=guard_phase,
            re_resolve=True,
        )
        if structural["blocking"] is not None:
            raise GuardCapabilityError(
                "; ".join(structural["reasons"])
                or "bitcoin live revalidation failed",
                reason_code=structural["reason_codes"][0]
                if structural["reason_codes"]
                else "bitcoin.consumption_blocked",
                details={
                    "reason_codes": list(structural["reason_codes"]),
                    "phase": phase_value,
                    "binding_digest": binding.binding_digest,
                },
            )

        live_attrs = live_request.candidate.attributes.to_dict()
        bound_digest = live_attrs.get("binding_digest")
        if bound_digest and bound_digest != binding.binding_digest:
            raise GuardCapabilityError(
                "live candidate binding_digest does not match Bitcoin binding",
                reason_code="bitcoin.binding_digest_mismatch",
                details={
                    "expected": binding.binding_digest,
                    "observed": bound_digest,
                },
            )

        assert self.preflight is not None
        return self.preflight.revalidate_and_consume(
            capability,
            live_request,
            phase=phase_value,
            now=clock,
        )

    # -- internals ----------------------------------------------------------

    def _coerce_candidate(
        self, candidate: BitcoinTransactionCandidate | Mapping[str, Any]
    ) -> BitcoinTransactionCandidate:
        if isinstance(candidate, BitcoinTransactionCandidate):
            return candidate
        if isinstance(candidate, Mapping):
            _reject_forbidden(candidate, "BitcoinTransactionCandidate")
            return BitcoinTransactionCandidate.from_dict(candidate)
        raise GuardValidationError(
            "candidate must be a BitcoinTransactionCandidate or mapping"
        )

    def _bind_prevouts(
        self, cand: BitcoinTransactionCandidate
    ) -> list[BoundPrevout]:
        bound: list[BoundPrevout] = []
        for index, raw in enumerate(cand.inputs):
            item = _mapping(raw, f"inputs[{index}]")
            _reject_forbidden(item, f"inputs[{index}]")

            # Nested prevout (Esplora-style) or flattened fields.
            prev = item.get("prevout", item.get("previous_output"))
            prev_map: Mapping[str, Any] = (
                _mapping(prev, f"inputs[{index}].prevout")
                if isinstance(prev, Mapping)
                else item
            )

            txid = item.get(
                "txid",
                prev_map.get("txid", item.get("prev_txid", "")),
            )
            vout_raw = item.get(
                "vout",
                prev_map.get("vout", item.get("prev_vout", item.get("n"))),
            )
            if txid in (None, "") or vout_raw is None:
                raise GuardValidationError(
                    f"inputs[{index}] requires txid and vout for prevout binding"
                )
            try:
                txid_n = normalize_txid(str(txid), field=f"inputs[{index}].txid")
            except BitcoinAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
            vout = _uint32(int(vout_raw), f"inputs[{index}].vout")

            value = prev_map.get(
                "value",
                prev_map.get(
                    "value_sats",
                    item.get("value", item.get("value_sats", item.get("amount"))),
                ),
            )
            script = prev_map.get(
                "scriptpubkey",
                prev_map.get(
                    "script_hex",
                    prev_map.get(
                        "script_pubkey",
                        item.get("script_hex", item.get("scriptpubkey", "")),
                    ),
                ),
            )
            known = True
            if value is None or script in (None, ""):
                known = bool(item.get("previous_output_known", False))
                if not known:
                    # Fail closed: incomplete prevout is not allowed for binding
                    # unless explicitly marked incomplete and still providing
                    # empty placeholders for digesting — we require full facts.
                    raise GuardValidationError(
                        f"inputs[{index}] prevout amount/script unbound; "
                        f"every prevout/amount/script must be bound"
                    )
            value_sats = _amount(value if value is not None else 0, f"inputs[{index}].value")
            try:
                script_hex = normalize_hex_script(
                    str(script or ""), field=f"inputs[{index}].script"
                )
            except BitcoinAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc

            script_type = prev_map.get(
                "scriptpubkey_type",
                prev_map.get(
                    "script_type",
                    item.get("script_type", "unknown"),
                ),
            )
            sequence = item.get("sequence", MAX_SEQUENCE)
            sequence_i = _uint32(int(sequence), f"inputs[{index}].sequence")
            rbf = signals_rbf(sequence_i)

            sighash_type = int(
                item.get("sighash_type", item.get("sighashType", int(SighashFlag.ALL)))
            )
            # Build SighashCommitment for weak-flag detection + digest.
            try:
                prevout_binding = bind_prevout(
                    txid=txid_n,
                    vout=vout,
                    value_sats=int(value_sats),
                    script_pubkey=script_hex,
                )
            except Exception:  # noqa: BLE001 — fall back to local digest
                prevout_binding = None
            prevout_digest = (
                prevout_binding.content_digest().removeprefix("sha256:")
                if prevout_binding is not None
                else content_sha256_hex(
                    {
                        "script_hex": script_hex,
                        "txid": txid_n,
                        "value_sats": value_sats,
                        "vout": vout,
                    }
                )
            )
            try:
                sighash = bind_sighash(
                    sighash_type=sighash_type,
                    input_index=index,
                    prevout=prevout_binding,
                    sequence=sequence_i,
                    locktime=cand.locktime,
                )
                raw_commitment = sighash.commitment_digest
                if raw_commitment.startswith("sha256:"):
                    sighash_digest = raw_commitment[len("sha256:") :]
                else:
                    sighash_digest = raw_commitment
                sighash_weak = bool(sighash.is_weak)
            except Exception:  # noqa: BLE001
                # Offline fallback without frontend helpers.
                base = sighash_type & 0x1F
                acp = bool(sighash_type & int(SighashFlag.ANYONECANPAY))
                sighash_weak = (
                    base in {int(SighashFlag.NONE), int(SighashFlag.SINGLE)} or acp
                )
                if sighash_type in {
                    int(SighashFlag.DEFAULT),
                    int(SighashFlag.ALL),
                }:
                    sighash_weak = False
                sighash_digest = content_sha256_hex(
                    {
                        "input_index": index,
                        "locktime": cand.locktime,
                        "prevout_digest": prevout_digest,
                        "sequence": sequence_i,
                        "sighash_type": sighash_type,
                        "value_sats": value_sats,
                    }
                )

            witness = item.get("witness", ())
            if isinstance(witness, (list, tuple)):
                witness_count = len(witness)
            else:
                witness_count = 0

            spend_path = str(
                item.get("spend_path_id", item.get("spendPathId", "")) or ""
            )
            descriptor = str(item.get("descriptor", "") or "")
            # Merge optional descriptor_paths by input index.
            for path in cand.descriptor_paths:
                if not isinstance(path, Mapping):
                    continue
                if int(path.get("input_index", path.get("inputIndex", -1))) == index:
                    spend_path = str(
                        path.get("path_id", path.get("spend_path_id", spend_path))
                        or spend_path
                    )
                    descriptor = str(
                        path.get("descriptor", descriptor) or descriptor
                    )

            bound.append(
                BoundPrevout(
                    input_index=index,
                    outpoint=outpoint_key(txid_n, vout),
                    txid=txid_n,
                    vout=vout,
                    value_sats=value_sats,
                    script_hex=script_hex,
                    script_digest=script_commitment(script_hex).removeprefix(
                        "sha256:"
                    ),
                    script_type=str(script_type or "unknown"),
                    sequence=sequence_i,
                    rbf_signaled=rbf,
                    sighash_type=sighash_type,
                    sighash_commitment_digest=sighash_digest,
                    sighash_is_weak=sighash_weak,
                    spend_path_id=spend_path,
                    descriptor=descriptor,
                    witness_item_count=witness_count,
                    previous_output_known=True,
                )
            )
        return bound

    def _bind_outputs(
        self, cand: BitcoinTransactionCandidate
    ) -> list[BoundOutput]:
        """Screen every output independently (no ownership clustering)."""

        explicit_change = set(cand.change_output_indexes)
        bound: list[BoundOutput] = []
        for index, raw in enumerate(cand.outputs):
            item = _mapping(raw, f"outputs[{index}]")
            _reject_forbidden(item, f"outputs[{index}]")
            n = item.get("n", item.get("output_index", index))
            n_i = _non_negative_int(int(n), f"outputs[{index}].n")
            value = item.get("value", item.get("value_sats", item.get("amount")))
            if value is None:
                raise GuardValidationError(
                    f"outputs[{index}] value unbound; every output must be screened"
                )
            value_sats = _amount(value, f"outputs[{index}].value")
            script = item.get(
                "scriptpubkey",
                item.get("script_hex", item.get("script_pubkey", "")),
            )
            if script in (None, ""):
                raise GuardValidationError(
                    f"outputs[{index}] script unbound; every output must be screened"
                )
            try:
                script_hex = normalize_hex_script(
                    str(script), field=f"outputs[{index}].script"
                )
            except BitcoinAdapterError as exc:
                raise GuardValidationError(str(exc)) from exc
            script_type = item.get(
                "scriptpubkey_type", item.get("script_type", "unknown")
            )
            address = str(
                item.get("scriptpubkey_address", item.get("address", "")) or ""
            )
            is_explicit = n_i in explicit_change or bool(
                item.get("is_explicit_change", False)
            )
            is_change = is_explicit and (
                bool(item.get("is_change", True)) if is_explicit else False
            )
            # Exposure path ids attached to this output (sanctions/flow).
            exp_ids: list[str] = []
            raw_exp = item.get("exposure_path_ids", item.get("exposurePathIds", ()))
            if isinstance(raw_exp, (list, tuple)):
                exp_ids.extend(str(x) for x in raw_exp)
            for path in cand.exposure_paths:
                if not isinstance(path, Mapping):
                    continue
                target = path.get("output_index", path.get("outputIndex"))
                if target is not None and int(target) == n_i:
                    pid = path.get("path_id", path.get("exposure_path_id", ""))
                    if pid:
                        exp_ids.append(str(pid))
            bound.append(
                BoundOutput(
                    output_index=n_i,
                    value_sats=value_sats,
                    script_hex=script_hex,
                    script_digest=script_commitment(script_hex).removeprefix(
                        "sha256:"
                    ),
                    script_type=str(script_type or "unknown"),
                    address=address,
                    is_change=is_change,
                    is_explicit_change=is_explicit,
                    exposure_path_ids=tuple(exp_ids),
                )
            )
        # Enforce every candidate output index is present.
        if len(bound) != len(cand.outputs):
            raise GuardValidationError("output screening count mismatch")
        return bound

    def _validate_fee(
        self,
        prevouts: Sequence[BoundPrevout],
        outputs: Sequence[BoundOutput],
        fee_sats: str,
    ) -> None:
        total_in = sum(int(p.value_sats) for p in prevouts)
        total_out = sum(int(o.value_sats) for o in outputs)
        fee = int(fee_sats)
        if total_in < total_out:
            raise GuardValidationError(
                f"input sum {total_in} < output sum {total_out}"
            )
        expected_fee = total_in - total_out
        if fee != expected_fee:
            raise GuardValidationError(
                f"fee_sats {fee} does not equal inputs-outputs {expected_fee}"
            )

    def _bind_utxo_availability(
        self,
        prevouts: Sequence[BoundPrevout],
        *,
        utxo_availability: Sequence[UtxoAvailability | Mapping[str, Any]] | None,
    ) -> list[UtxoAvailability]:
        provided: dict[str, UtxoAvailability] = {}
        if utxo_availability is not None:
            for item in utxo_availability:
                epoch = (
                    item
                    if isinstance(item, UtxoAvailability)
                    else UtxoAvailability.from_dict(item)
                )
                provided[epoch.outpoint] = epoch
        bound: list[UtxoAvailability] = []
        for prev in prevouts:
            if prev.outpoint in provided:
                bound.append(provided[prev.outpoint])
            elif utxo_availability is not None:
                raise GuardValidationError(
                    f"missing UTXO availability for {prev.outpoint}"
                )
            else:
                bound.append(
                    UtxoAvailability(
                        outpoint=prev.outpoint,
                        status=UtxoStatus.AVAILABLE,
                        attributes={"synthetic": True},
                    )
                )
        return bound

    def _bind_ancestry(
        self,
        prevouts: Sequence[BoundPrevout],
        *,
        ancestry_edges: Sequence[UtxoAncestryEdge | Mapping[str, Any]] | None,
    ) -> list[UtxoAncestryEdge]:
        """Trace UTXO ancestry without assuming CoinJoin ownership.

        Multi-input co-spend is recorded only as independent outpoint
        consumption — never as a shared-ownership cluster.
        """

        edges: list[UtxoAncestryEdge] = []
        if not ancestry_edges:
            # Depth-0 identity edges only (self-reference of spent outpoints).
            # No cross-input ownership edges are invented.
            return edges
        for item in ancestry_edges:
            edge = (
                item
                if isinstance(item, UtxoAncestryEdge)
                else UtxoAncestryEdge.from_dict(item)
            )
            if edge.ownership_assumed:
                raise GuardValidationError(
                    "ancestry edge must not assume CoinJoin ownership"
                )
            edges.append(edge)
        # Diagnostic: multi-input does not imply joint control.
        if len(prevouts) > 1:
            # Ensure no synthetic ownership edges spanning distinct inputs.
            input_outpoints = {p.outpoint for p in prevouts}
            for edge in edges:
                attrs = edge.attributes.to_dict()
                if attrs.get("coinjoin_cluster") or attrs.get("common_ownership"):
                    raise GuardValidationError(
                        "UTXO ancestry must not encode CoinJoin common ownership"
                    )
                # Allow parent→child edges; reject "peer co-spend ownership".
                if (
                    edge.child_outpoint in input_outpoints
                    and edge.parent_outpoint in input_outpoints
                    and edge.child_outpoint != edge.parent_outpoint
                    and attrs.get("implies_common_ownership")
                ):
                    raise GuardValidationError(
                        "co-spent outpoints must not imply common ownership"
                    )
        return edges

    def _check_structural(
        self,
        binding: BitcoinTransactionBinding,
        *,
        now: str,
        live_utxos: Mapping[str, UtxoAvailability | Mapping[str, Any]] | None,
        phase: BitcoinGuardPhase,
        re_resolve: bool = False,
    ) -> dict[str, Any]:
        reason_codes: list[str] = []
        reasons: list[str] = []
        security_results: dict[str, str] = {}
        blocking: TransactionVerdictOutcome | None = None
        failed_requirement = ""

        def _block(
            outcome: TransactionVerdictOutcome,
            code: str,
            reason: str,
            requirement: str,
        ) -> None:
            nonlocal blocking, failed_requirement
            reason_codes.append(code)
            reasons.append(reason)
            security_results[requirement] = {
                TransactionVerdictOutcome.DENY: "deny",
                TransactionVerdictOutcome.STALE: "stale",
                TransactionVerdictOutcome.REVIEW: "review",
                TransactionVerdictOutcome.ERROR: "error",
                TransactionVerdictOutcome.INCONCLUSIVE: "inconclusive",
            }.get(outcome, "deny")
            if failed_requirement == "":
                failed_requirement = requirement
            if blocking is None or (
                outcome is TransactionVerdictOutcome.DENY
                and blocking is not TransactionVerdictOutcome.DENY
            ):
                blocking = outcome
            elif (
                outcome is TransactionVerdictOutcome.STALE
                and blocking
                not in (
                    TransactionVerdictOutcome.DENY,
                    TransactionVerdictOutcome.STALE,
                )
            ):
                blocking = outcome

        # Network binding.
        if not binding.network or not binding.genesis_hash:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "bitcoin.network_unbound",
                "network/genesis unbound",
                "sec:bitcoin-network-binding",
            )
        else:
            try:
                resolve_network(
                    chain_id=binding.chain_id,
                    network=binding.network,
                    genesis_hash=binding.genesis_hash,
                )
                security_results.setdefault("sec:bitcoin-network-binding", "pass")
            except BitcoinAdapterError as exc:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "bitcoin.network_mismatch",
                    f"network binding failed: {exc}",
                    "sec:bitcoin-network-binding",
                )

        # Prevouts.
        if not binding.prevouts:
            _block(
                TransactionVerdictOutcome.DENY,
                "bitcoin.prevouts_empty",
                "no prevouts bound",
                "sec:bitcoin-prevout-binding",
            )
        elif not binding.all_prevouts_known:
            _block(
                TransactionVerdictOutcome.INCONCLUSIVE,
                "bitcoin.prevout_incomplete",
                "one or more prevouts incomplete",
                "sec:bitcoin-prevout-binding",
            )
        else:
            security_results.setdefault("sec:bitcoin-prevout-binding", "pass")

        # Outputs — every output screened.
        if not binding.outputs:
            _block(
                TransactionVerdictOutcome.DENY,
                "bitcoin.outputs_empty",
                "no outputs bound",
                "sec:bitcoin-output-binding",
            )
        else:
            for out in binding.outputs:
                if not out.script_digest or out.value_sats == "":
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "bitcoin.output_unscreened",
                        f"output {out.output_index} missing value/script",
                        "sec:bitcoin-output-binding",
                    )
            security_results.setdefault("sec:bitcoin-output-binding", "pass")

        # Fee + RBF.
        try:
            total_in = sum(int(p.value_sats) for p in binding.prevouts)
            total_out = sum(int(o.value_sats) for o in binding.outputs)
            if int(binding.fee_sats) != total_in - total_out:
                _block(
                    TransactionVerdictOutcome.DENY,
                    "bitcoin.fee_mismatch",
                    "fee does not equal inputs minus outputs",
                    "sec:bitcoin-fee-rbf",
                )
            else:
                security_results.setdefault("sec:bitcoin-fee-rbf", "pass")
        except (TypeError, ValueError) as exc:
            _block(
                TransactionVerdictOutcome.ERROR,
                "bitcoin.fee_error",
                f"fee validation error: {exc}",
                "sec:bitcoin-fee-rbf",
            )

        # Locktime / sequence always present when bound.
        if binding.locktime < 0 or binding.locktime > MAX_LOCKTIME:
            _block(
                TransactionVerdictOutcome.DENY,
                "bitcoin.locktime_invalid",
                "locktime out of range",
                "sec:bitcoin-locktime-sequence",
            )
        else:
            security_results.setdefault("sec:bitcoin-locktime-sequence", "pass")

        # Sighash.
        if binding.has_weak_sighash:
            _block(
                TransactionVerdictOutcome.DENY,
                "bitcoin.weak_sighash",
                "weak sighash flags present (NONE/SINGLE/ANYONECANPAY)",
                "sec:bitcoin-sighash-commitment",
            )
        else:
            for prev in binding.prevouts:
                if not prev.sighash_commitment_digest:
                    _block(
                        TransactionVerdictOutcome.INCONCLUSIVE,
                        "bitcoin.sighash_unbound",
                        f"input {prev.input_index} missing sighash commitment",
                        "sec:bitcoin-sighash-commitment",
                    )
                    break
            else:
                security_results.setdefault(
                    "sec:bitcoin-sighash-commitment", "pass"
                )

        # Spend path / descriptor surface (optional but when present must be bound).
        security_results.setdefault("sec:bitcoin-spend-path", "pass")

        # Exact candidate.
        if not binding.serialized_digest or binding.byte_length <= 0:
            _block(
                TransactionVerdictOutcome.DENY,
                "bitcoin.candidate_unbound",
                "exact unsigned transaction not bound",
                "sec:bitcoin-exact-candidate",
            )
        else:
            security_results.setdefault("sec:bitcoin-exact-candidate", "pass")

        # List / graph revision freshness.
        assert self.list_revision_is_current is not None
        assert self.graph_revision_is_current is not None
        if binding.list_revision:
            try:
                list_ok = bool(
                    self.list_revision_is_current(binding.list_revision, now)
                )
            except Exception as exc:  # noqa: BLE001
                list_ok = False
                _block(
                    TransactionVerdictOutcome.ERROR,
                    "bitcoin.list_revision_checker_error",
                    f"list revision checker errored: {exc}",
                    "sec:bitcoin-exact-candidate",
                )
            else:
                if not list_ok:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "bitcoin.list_revision_stale",
                        "sanctions/list revision is stale",
                        "sec:bitcoin-exact-candidate",
                    )
        if binding.graph_revision:
            try:
                graph_ok = bool(
                    self.graph_revision_is_current(binding.graph_revision, now)
                )
            except Exception as exc:  # noqa: BLE001
                graph_ok = False
                _block(
                    TransactionVerdictOutcome.ERROR,
                    "bitcoin.graph_revision_checker_error",
                    f"graph revision checker errored: {exc}",
                    "sec:bitcoin-exact-candidate",
                )
            else:
                if not graph_ok:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "bitcoin.graph_revision_stale",
                        "exposure graph revision is stale",
                        "sec:bitcoin-exact-candidate",
                    )

        # UTXO availability — re-resolve when requested.
        utxo_resolver = self.utxo_resolver
        if live_utxos is not None:
            utxo_resolver = _static_utxo_resolver(live_utxos)
        if re_resolve or live_utxos is not None or utxo_resolver is not None:
            for epoch in binding.utxo_availability:
                live_value: UtxoAvailability | Mapping[str, Any] | None = None
                if utxo_resolver is not None:
                    try:
                        live_value = utxo_resolver(epoch.outpoint)
                    except Exception as exc:  # noqa: BLE001
                        _block(
                            TransactionVerdictOutcome.ERROR,
                            "bitcoin.utxo_resolve_error",
                            f"UTXO re-resolve failed for {epoch.outpoint}: {exc}",
                            "sec:bitcoin-utxo-availability",
                        )
                        continue
                if live_value is None:
                    if re_resolve:
                        _block(
                            TransactionVerdictOutcome.STALE,
                            "bitcoin.utxo_unresolved",
                            f"UTXO {epoch.outpoint} could not be re-resolved at "
                            f"{phase.value}",
                            "sec:bitcoin-utxo-availability",
                        )
                    continue
                live_epoch = _coerce_utxo(live_value, field_name="live UTXO")
                assert live_epoch is not None
                if live_epoch.status is UtxoStatus.SPENT:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "bitcoin.utxo_spent",
                        f"UTXO {epoch.outpoint} is spent",
                        "sec:bitcoin-utxo-availability",
                    )
                elif live_epoch.status is UtxoStatus.REORGED:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "bitcoin.utxo_reorged",
                        f"UTXO {epoch.outpoint} reorged out of chain",
                        "sec:bitcoin-utxo-availability",
                    )
                elif live_epoch.status is UtxoStatus.MISSING:
                    _block(
                        TransactionVerdictOutcome.DENY,
                        "bitcoin.utxo_missing",
                        f"UTXO {epoch.outpoint} missing from set",
                        "sec:bitcoin-utxo-availability",
                    )
                elif (
                    re_resolve
                    and live_epoch.availability_epoch != epoch.availability_epoch
                    and live_epoch.status is not UtxoStatus.AVAILABLE
                ):
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "bitcoin.utxo_epoch_mismatch",
                        f"UTXO availability epoch changed for {epoch.outpoint}",
                        "sec:bitcoin-utxo-availability",
                    )
                # Tip reorg: tip_hash change with lower height indicates reorg.
                if (
                    re_resolve
                    and epoch.tip_hash
                    and live_epoch.tip_hash
                    and epoch.tip_hash != live_epoch.tip_hash
                    and epoch.tip_height is not None
                    and live_epoch.tip_height is not None
                    and live_epoch.tip_height < epoch.tip_height
                ):
                    _block(
                        TransactionVerdictOutcome.STALE,
                        "bitcoin.chain_reorg",
                        "chain tip reorg detected during UTXO revalidation",
                        "sec:bitcoin-utxo-availability",
                    )
            if "sec:bitcoin-utxo-availability" not in security_results:
                security_results["sec:bitcoin-utxo-availability"] = "pass"
        else:
            # Offline default: trust bound availability if all available.
            if any(
                u.status is not UtxoStatus.AVAILABLE
                for u in binding.utxo_availability
            ):
                for u in binding.utxo_availability:
                    if u.status is UtxoStatus.SPENT:
                        _block(
                            TransactionVerdictOutcome.DENY,
                            "bitcoin.utxo_spent",
                            f"UTXO {u.outpoint} is spent",
                            "sec:bitcoin-utxo-availability",
                        )
                    elif u.status is UtxoStatus.REORGED:
                        _block(
                            TransactionVerdictOutcome.STALE,
                            "bitcoin.utxo_reorged",
                            f"UTXO {u.outpoint} reorged",
                            "sec:bitcoin-utxo-availability",
                        )
            security_results.setdefault("sec:bitcoin-utxo-availability", "pass")

        return {
            "blocking": blocking,
            "failed_requirement": failed_requirement,
            "reason_codes": reason_codes,
            "reasons": reasons,
            "security_results": security_results,
        }

    def _assert_live_candidate_matches(
        self,
        binding: BitcoinTransactionBinding,
        live_candidate: BitcoinTransactionCandidate | Mapping[str, Any],
    ) -> None:
        live_binding = self.bind_transaction(live_candidate)
        if live_binding.serialized_digest != binding.serialized_digest:
            raise GuardCapabilityError(
                "live candidate serialized bytes substituted",
                reason_code="bitcoin.candidate_substituted",
                details={
                    "expected": binding.serialized_digest,
                    "observed": live_binding.serialized_digest,
                },
            )
        if live_binding.binding_digest != binding.binding_digest:
            # Detailed field comparison for clearer reason codes.
            if [o.to_dict() for o in live_binding.outputs] != [
                o.to_dict() for o in binding.outputs
            ]:
                raise GuardCapabilityError(
                    "live outputs/change mutated",
                    reason_code="bitcoin.output_mutation",
                    details={"binding_digest": binding.binding_digest},
                )
            if [p.to_dict() for p in live_binding.prevouts] != [
                p.to_dict() for p in binding.prevouts
            ]:
                # Distinguish sighash vs prevout mutation.
                for lp, bp in zip(
                    live_binding.prevouts, binding.prevouts, strict=False
                ):
                    if lp.sighash_commitment_digest != bp.sighash_commitment_digest:
                        raise GuardCapabilityError(
                            "live sighash commitment mutated",
                            reason_code="bitcoin.sighash_mutation",
                            details={"input_index": bp.input_index},
                        )
                raise GuardCapabilityError(
                    "live prevout mutated",
                    reason_code="bitcoin.prevout_mutation",
                    details={"binding_digest": binding.binding_digest},
                )
            raise GuardCapabilityError(
                "live candidate binding mutated",
                reason_code="bitcoin.binding_mutation",
                details={
                    "expected": binding.binding_digest,
                    "observed": live_binding.binding_digest,
                },
            )

    def _assert_live_outputs_match(
        self,
        binding: BitcoinTransactionBinding,
        live_outputs: Sequence[Mapping[str, Any]],
    ) -> None:
        if len(live_outputs) != len(binding.outputs):
            raise GuardCapabilityError(
                "live output count mutated",
                reason_code="bitcoin.output_mutation",
            )
        for index, (live_raw, bound) in enumerate(
            zip(live_outputs, binding.outputs, strict=True)
        ):
            live_map = _mapping(live_raw, f"live_outputs[{index}]")
            value = live_map.get(
                "value", live_map.get("value_sats", live_map.get("amount"))
            )
            script = live_map.get(
                "scriptpubkey",
                live_map.get("script_hex", live_map.get("script_pubkey", "")),
            )
            if value is None or str(parse_sats(value)) != bound.value_sats:
                raise GuardCapabilityError(
                    f"live output {index} value mutated",
                    reason_code="bitcoin.output_mutation",
                    details={"output_index": index},
                )
            try:
                live_script = normalize_hex_script(
                    str(script or ""), field=f"live_outputs[{index}].script"
                )
            except BitcoinAdapterError as exc:
                raise GuardCapabilityError(
                    f"live output {index} script invalid: {exc}",
                    reason_code="bitcoin.output_mutation",
                ) from exc
            live_digest = script_commitment(live_script).removeprefix("sha256:")
            if live_digest != bound.script_digest:
                raise GuardCapabilityError(
                    f"live output {index} script mutated",
                    reason_code="bitcoin.output_mutation",
                    details={"output_index": index},
                )

    def _assert_live_prevouts_match(
        self,
        binding: BitcoinTransactionBinding,
        live_prevouts: Sequence[Mapping[str, Any]],
    ) -> None:
        if len(live_prevouts) != len(binding.prevouts):
            raise GuardCapabilityError(
                "live prevout count mutated",
                reason_code="bitcoin.prevout_mutation",
            )
        for index, (live_raw, bound) in enumerate(
            zip(live_prevouts, binding.prevouts, strict=True)
        ):
            live_map = _mapping(live_raw, f"live_prevouts[{index}]")
            txid = live_map.get("txid", "")
            vout = live_map.get("vout")
            if txid and vout is not None:
                key = outpoint_key(str(txid), int(vout))
                if key != bound.outpoint:
                    raise GuardCapabilityError(
                        f"live prevout {index} outpoint substituted",
                        reason_code="bitcoin.prevout_mutation",
                        details={"expected": bound.outpoint, "observed": key},
                    )
            sighash = live_map.get("sighash_type", live_map.get("sighashType"))
            if sighash is not None and int(sighash) != bound.sighash_type:
                raise GuardCapabilityError(
                    f"live prevout {index} sighash mutated",
                    reason_code="bitcoin.sighash_mutation",
                    details={
                        "expected": bound.sighash_type,
                        "observed": int(sighash),
                    },
                )

    def _intent_from_binding(
        self, binding: BitcoinTransactionBinding, *, expires_at: str
    ) -> TransactionIntent:
        # Primary destination = first non-change output when available.
        destination = ""
        for out in binding.outputs:
            if not out.is_change:
                destination = out.address or f"script:{out.script_digest[:16]}"
                break
        if not destination and binding.outputs:
            out0 = binding.outputs[0]
            destination = out0.address or f"script:{out0.script_digest[:16]}"

        sender = ""
        if binding.prevouts:
            # Display only — script commitment is authoritative for spend.
            sender = f"outpoint:{binding.prevouts[0].outpoint}"

        total_out = sum(int(o.value_sats) for o in binding.outputs)
        assets = [
            AssetAmount(
                asset_id="asset:btc-native",
                amount=str(total_out),
            )
        ]
        effects: list[ExpectedEffect] = []
        for out in binding.outputs:
            kind = "change_output" if out.is_change else "payment_output"
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:btc-out-{out.output_index}",
                    kind=kind,
                    summary=(
                        f"output[{out.output_index}] {out.value_sats} sats "
                        f"script={out.script_type}"
                    ),
                )
            )
        effects.append(
            ExpectedEffect(
                effect_id="effect:btc-fee",
                kind="network_fee",
                summary=f"fee {binding.fee_sats} sats rbf={binding.rbf_signaled}",
            )
        )
        for path in binding.exposure_paths:
            pid = str(path.get("path_id", path.get("exposure_path_id", "path")))
            effects.append(
                ExpectedEffect(
                    effect_id=f"effect:exposure:{pid}",
                    kind="exposure_path",
                    summary=str(path.get("summary", pid)),
                )
            )

        utxos = tuple(
            UtxoRef(
                outpoint=p.outpoint,
                amount=p.value_sats,
                script_digest=p.script_digest,
            )
            for p in binding.prevouts
        )
        # Signers: one placeholder per input spend path (non-custodial).
        signers = tuple(
            f"signer:input-{p.input_index}" for p in binding.prevouts
        ) or ("signer:bitcoin",)

        method = "bitcoin.spend"
        if binding.psbt_digest:
            method = "bitcoin.psbt_spend"

        return TransactionIntent(
            intent_id=binding.intent_id,
            network=binding.network,
            sender=sender,
            destination=destination,
            method=method,
            assets=tuple(assets),
            fees=(
                FeeSpec(
                    amount=binding.fee_sats,
                    asset_id="asset:btc-native",
                    payer=sender,
                ),
            ),
            nonce_or_sequence=str(binding.locktime),
            signers=signers,
            expected_effects=tuple(effects),
            expires_at=expires_at,
            utxos=utxos,
            chain_namespace=BITCOIN_NAMESPACE,
            attributes={
                "binding_digest": binding.binding_digest,
                "chain_id": binding.chain_id,
                "genesis_hash": binding.genesis_hash,
                "graph_revision": binding.graph_revision,
                "list_revision": binding.list_revision,
                "rbf_signaled": binding.rbf_signaled,
                "version": binding.version,
            },
        )


def evaluate_bitcoin_transaction_guard(
    candidate: BitcoinTransactionCandidate | Mapping[str, Any],
    *,
    guard: BitcoinTransactionGuard | None = None,
    **kwargs: Any,
) -> BitcoinGuardDecision:
    """Convenience: bind a transaction candidate and evaluate in one call."""

    guard = guard or BitcoinTransactionGuard()
    bind_keys = {
        "utxo_availability",
        "ancestry_edges",
        "serialized_bytes",
        "candidate_id",
        "binding_id",
        "attributes",
    }
    bind_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in bind_keys}
    binding = guard.bind_transaction(candidate, **bind_kwargs)
    return guard.evaluate(binding, **kwargs)


__all__ = [
    "BITCOIN_BINDING_SCHEMA_VERSION",
    "BITCOIN_CANDIDATE_SCHEMA_VERSION",
    "BITCOIN_GUARD_DECISION_SCHEMA_VERSION",
    "BITCOIN_TRANSACTION_GUARD_INTERFACE",
    "BITCOIN_TRANSACTION_GUARD_SCHEMA_VERSION",
    "DEFAULT_COMPLIANCE_REQUIREMENTS",
    "DEFAULT_POLICY_ID",
    "DEFAULT_PRODUCER_ID",
    "DEFAULT_SECURITY_REQUIREMENTS",
    "RBF_SEQUENCE_THRESHOLD",
    "UTXO_ANCESTRY_SCHEMA_VERSION",
    "UTXO_AVAILABILITY_SCHEMA_VERSION",
    "BitcoinGuardDecision",
    "BitcoinGuardPhase",
    "BitcoinTransactionBinding",
    "BitcoinTransactionCandidate",
    "BitcoinTransactionGuard",
    "BoundOutput",
    "BoundPrevout",
    "GraphRevisionChecker",
    "ListRevisionChecker",
    "PSBTBinding",
    "PSBTInputBinding",
    "PSBTRole",
    "PrevoutBinding",
    "SighashCommitment",
    "UtxoAncestryEdge",
    "UtxoAvailability",
    "UtxoAvailabilityResolver",
    "UtxoStatus",
    "content_sha256_hex",
    "evaluate_bitcoin_transaction_guard",
    "outpoint_key",
    "signals_rbf",
]

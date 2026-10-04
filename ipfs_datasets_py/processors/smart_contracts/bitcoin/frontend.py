"""Bitcoin Script frontend: spend-condition normalization (CRYPTOIR-G250).

Normalizes legacy Script, SegWit, Tapscript leaves/control blocks, descriptors,
Miniscript, witnesses, PSBT input bindings, prevouts, sighash, timelock,
hashlock, and threshold spending paths into Crypto IR records.

**This is not an account-contract frontend.** Bitcoin UTXO spend conditions
are modeled explicitly: amounts are satoshis, identity is script/prevout
commitment, and incomplete branches fail closed.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..models import ensure_secret_safe
from .miniscript import (
    MINISCRIPT_SCHEMA_VERSION,
    DescriptorType,
    MiniscriptPolicy,
    OutputDescriptor,
    PolicyEquivalenceStatus,
    compare_descriptors,
    compare_policies,
    parse_descriptor,
    parse_miniscript,
)
from .script import (
    DEFAULT_MAX_OPS,
    DEFAULT_MAX_SCRIPT_BYTES,
    DEFAULT_MAX_WITNESS_ITEMS,
    SCRIPT_SCHEMA_VERSION,
    HashlockConstraint,
    PrevoutBinding,
    ScriptForm,
    ScriptProgram,
    ScriptVersion,
    SemanticPassStatus,
    SighashCommitment,
    SighashFlag,
    StackSemanticRecord,
    TimelockConstraint,
    WitnessStack,
    analyze_stack_semantics,
    bind_prevout,
    bind_sighash,
    bind_witness,
    decode_script,
    incomplete_spend_never_passes,
    normalize_script_bytes,
    normalize_txid,
)
from .tapscript import (
    TAPSCRIPT_SCHEMA_VERSION,
    ControlBlock,
    LeafAvailability,
    SpendPathKind,
    TaprootCommitment,
    TapscriptLeaf,
    bind_taproot_commitment,
    bind_tapscript_leaf,
    parse_control_block,
    tapscript_path_status,
)


FRONTEND_SCHEMA_VERSION = "smart-contract-bitcoin-frontend-v1"
FRONTEND_ID = "smart-contracts.bitcoin.frontend"
FRONTEND_VERSION = "1.0.0"
DEFAULT_MAX_PSBT_INPUTS = 256
DEFAULT_MAX_SPEND_PATHS = 64


class AnalysisMode(StrEnum):
    """How the frontend treated available spend evidence."""

    SPEND_PATH = "spend_path"
    KEY_PATH = "key_path"
    POLICY_ONLY = "policy_only"
    INCOMPLETE = "incomplete"


class PSBTRole(StrEnum):
    """PSBT role boundary (analysis only — no signing)."""

    CREATOR = "creator"
    UPDATER = "updater"
    SIGNER = "signer"
    FINALIZER = "finalizer"
    EXTRACTOR = "extractor"
    ANALYZER = "analyzer"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{name} must be a bool")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


@dataclass(frozen=True, slots=True)
class PSBTInputBinding:
    """PSBT per-input binding of prevout, scripts, witness, and sighash.

    Signing material is never accepted.  Missing prevout or incomplete script
    evidence leaves the input incomplete.
    """

    input_index: int
    prevout: PrevoutBinding | None
    redeem_script: ScriptProgram | None = None
    witness_script: ScriptProgram | None = None
    witness: WitnessStack | None = None
    sighash: SighashCommitment | None = None
    sequence: int | None = None
    taproot: TaprootCommitment | None = None
    partial_sigs_count: int = 0
    is_final: bool = False
    complete: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "input_index", _non_negative(self.input_index, "input_index")
        )
        if self.prevout is not None and not isinstance(self.prevout, PrevoutBinding):
            raise InvalidRequestError("prevout must be a PrevoutBinding or None")
        for name, value in (
            ("redeem_script", self.redeem_script),
            ("witness_script", self.witness_script),
        ):
            if value is not None and not isinstance(value, ScriptProgram):
                raise InvalidRequestError(f"{name} must be a ScriptProgram or None")
        if self.witness is not None and not isinstance(self.witness, WitnessStack):
            raise InvalidRequestError("witness must be a WitnessStack or None")
        if self.sighash is not None and not isinstance(self.sighash, SighashCommitment):
            raise InvalidRequestError("sighash must be a SighashCommitment or None")
        if self.sequence is not None:
            if (
                isinstance(self.sequence, bool)
                or not isinstance(self.sequence, int)
                or not 0 <= self.sequence <= 0xFFFFFFFF
            ):
                raise InvalidRequestError("sequence must be a uint32 integer")
        if self.taproot is not None and not isinstance(self.taproot, TaprootCommitment):
            raise InvalidRequestError("taproot must be a TaprootCommitment or None")
        object.__setattr__(
            self,
            "partial_sigs_count",
            _non_negative(self.partial_sigs_count, "partial_sigs_count"),
        )
        object.__setattr__(self, "is_final", _bool(self.is_final, "is_final"))
        object.__setattr__(self, "complete", _bool(self.complete, "complete"))
        if self.complete:
            if self.prevout is None or not self.prevout.known:
                raise InvalidRequestError(
                    "PSBT input complete requires known prevout binding"
                )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Reject signing surfaces in attributes.
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "complete": self.complete,
            "input_index": self.input_index,
            "is_final": self.is_final,
            "partial_sigs_count": self.partial_sigs_count,
            "prevout": self.prevout.to_dict() if self.prevout else None,
            "redeem_script": self.redeem_script.to_dict()
            if self.redeem_script
            else None,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "sighash": self.sighash.to_dict() if self.sighash else None,
            "taproot": self.taproot.to_dict() if self.taproot else None,
            "witness": self.witness.to_dict() if self.witness else None,
            "witness_script": self.witness_script.to_dict()
            if self.witness_script
            else None,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class PSBTBinding:
    """Transaction-level PSBT analysis binding (no signing / extraction)."""

    inputs: tuple[PSBTInputBinding, ...]
    locktime: int | None = None
    version: int | None = None
    role: PSBTRole = PSBTRole.ANALYZER
    all_prevouts_known: bool = False
    has_weak_sighash: bool = False
    complete: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        inputs = tuple(self.inputs)
        for index, item in enumerate(inputs):
            if not isinstance(item, PSBTInputBinding):
                raise InvalidRequestError(
                    f"inputs[{index}] must be a PSBTInputBinding"
                )
        object.__setattr__(self, "inputs", inputs)
        if self.locktime is not None:
            if (
                isinstance(self.locktime, bool)
                or not isinstance(self.locktime, int)
                or not 0 <= self.locktime <= 0xFFFFFFFF
            ):
                raise InvalidRequestError("locktime must be a uint32 integer")
        if self.version is not None:
            object.__setattr__(
                self, "version", _non_negative(self.version, "version")
            )
        role = self.role if isinstance(self.role, PSBTRole) else PSBTRole(str(self.role))
        object.__setattr__(self, "role", role)
        all_known = bool(inputs) and all(
            i.prevout is not None and i.prevout.known for i in inputs
        )
        object.__setattr__(self, "all_prevouts_known", all_known)
        weak = any(i.sighash is not None and i.sighash.is_weak for i in inputs)
        object.__setattr__(self, "has_weak_sighash", weak)
        eligible = all_known and all(i.complete for i in inputs) and not weak
        # Do not trust constructor complete flag if fields disagree.
        if self.complete and not eligible:
            raise InvalidRequestError(
                "PSBT complete requires known prevouts, complete inputs, no weak sighash"
            )
        object.__setattr__(self, "complete", bool(self.complete) and eligible)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_prevouts_known": self.all_prevouts_known,
            "attributes": thaw_json(self.attributes),
            "complete": self.complete,
            "has_weak_sighash": self.has_weak_sighash,
            "inputs": [item.to_dict() for item in self.inputs],
            "locktime": self.locktime,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class SpendingPathRecord:
    """One alternative spending path (threshold branch, tapleaf, etc.)."""

    path_id: str
    program: ScriptProgram | None
    stack: StackSemanticRecord | None
    tapleaf: TapscriptLeaf | None
    policy: MiniscriptPolicy | None
    available: bool
    pass_status: SemanticPassStatus
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_id", _required_text(self.path_id, "path_id"))
        if self.program is not None and not isinstance(self.program, ScriptProgram):
            raise InvalidRequestError("program must be a ScriptProgram or None")
        if self.stack is not None and not isinstance(self.stack, StackSemanticRecord):
            raise InvalidRequestError("stack must be a StackSemanticRecord or None")
        if self.tapleaf is not None and not isinstance(self.tapleaf, TapscriptLeaf):
            raise InvalidRequestError("tapleaf must be a TapscriptLeaf or None")
        if self.policy is not None and not isinstance(self.policy, MiniscriptPolicy):
            raise InvalidRequestError("policy must be a MiniscriptPolicy or None")
        object.__setattr__(self, "available", _bool(self.available, "available"))
        status = (
            self.pass_status
            if isinstance(self.pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.pass_status))
        )
        object.__setattr__(self, "pass_status", status)
        if status is SemanticPassStatus.PASS and not self.available:
            raise InvalidRequestError("unavailable spending path cannot pass")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(d, "diagnostics item") for d in self.diagnostics),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "available": self.available,
            "diagnostics": list(self.diagnostics),
            "pass_status": self.pass_status.value,
            "path_id": self.path_id,
            "policy": self.policy.to_dict() if self.policy else None,
            "program": self.program.to_dict() if self.program else None,
            "stack": self.stack.to_dict() if self.stack else None,
            "tapleaf": self.tapleaf.to_dict() if self.tapleaf else None,
        }


@dataclass(frozen=True, slots=True)
class BitcoinNormalizationResult:
    """Full frontend output for one UTXO spend-condition observation."""

    chain_id: str
    network: str
    prevout: PrevoutBinding | None
    primary_program: ScriptProgram | None
    stack: StackSemanticRecord | None
    taproot: TaprootCommitment | None
    policy: MiniscriptPolicy | None
    descriptor: OutputDescriptor | None
    psbt: PSBTBinding | None
    spending_paths: tuple[SpendingPathRecord, ...]
    analysis_mode: AnalysisMode
    semantic_pass_status: SemanticPassStatus
    policy_equivalence: PolicyEquivalenceStatus
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _required_text(self.chain_id, "chain_id"))
        object.__setattr__(
            self, "network", self.network.strip() if self.network else ""
        )
        if self.prevout is not None and not isinstance(self.prevout, PrevoutBinding):
            raise InvalidRequestError("prevout must be a PrevoutBinding or None")
        if self.primary_program is not None and not isinstance(
            self.primary_program, ScriptProgram
        ):
            raise InvalidRequestError("primary_program must be a ScriptProgram or None")
        if self.stack is not None and not isinstance(self.stack, StackSemanticRecord):
            raise InvalidRequestError("stack must be a StackSemanticRecord or None")
        if self.taproot is not None and not isinstance(self.taproot, TaprootCommitment):
            raise InvalidRequestError("taproot must be a TaprootCommitment or None")
        if self.policy is not None and not isinstance(self.policy, MiniscriptPolicy):
            raise InvalidRequestError("policy must be a MiniscriptPolicy or None")
        if self.descriptor is not None and not isinstance(
            self.descriptor, OutputDescriptor
        ):
            raise InvalidRequestError("descriptor must be an OutputDescriptor or None")
        if self.psbt is not None and not isinstance(self.psbt, PSBTBinding):
            raise InvalidRequestError("psbt must be a PSBTBinding or None")
        paths = tuple(self.spending_paths)
        for index, path in enumerate(paths):
            if not isinstance(path, SpendingPathRecord):
                raise InvalidRequestError(
                    f"spending_paths[{index}] must be a SpendingPathRecord"
                )
        object.__setattr__(self, "spending_paths", paths)
        mode = (
            self.analysis_mode
            if isinstance(self.analysis_mode, AnalysisMode)
            else AnalysisMode(str(self.analysis_mode))
        )
        object.__setattr__(self, "analysis_mode", mode)
        status = (
            self.semantic_pass_status
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.semantic_pass_status))
        )
        object.__setattr__(self, "semantic_pass_status", status)
        eq = (
            self.policy_equivalence
            if isinstance(self.policy_equivalence, PolicyEquivalenceStatus)
            else PolicyEquivalenceStatus(str(self.policy_equivalence))
        )
        object.__setattr__(self, "policy_equivalence", eq)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(d, "diagnostics item") for d in self.diagnostics),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Global invariant: incomplete / weak / hidden never pass.
        if status is SemanticPassStatus.PASS:
            if self.prevout is None or not self.prevout.known:
                raise InvalidRequestError("pass requires known prevout")
            if any(not p.available for p in paths if p.pass_status is SemanticPassStatus.PASS):
                raise InvalidRequestError("pass path must be available")
            if self.psbt is not None and self.psbt.has_weak_sighash:
                raise InvalidRequestError("pass forbidden with weak sighash in PSBT")
            if self.taproot is not None and self.taproot.hidden_branches:
                raise InvalidRequestError("pass forbidden with hidden taproot branches")
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.semantic_pass_status is SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.analysis_mode.value,
            "attributes": thaw_json(self.attributes),
            "chain_id": self.chain_id,
            "descriptor": self.descriptor.to_dict() if self.descriptor else None,
            "diagnostics": list(self.diagnostics),
            "network": self.network,
            "policy": self.policy.to_dict() if self.policy else None,
            "policy_equivalence": self.policy_equivalence.value,
            "prevout": self.prevout.to_dict() if self.prevout else None,
            "primary_program": self.primary_program.to_dict()
            if self.primary_program
            else None,
            "psbt": self.psbt.to_dict() if self.psbt else None,
            "schema_version": self.schema_version,
            "semantic_pass_status": self.semantic_pass_status.value,
            "spending_paths": [p.to_dict() for p in self.spending_paths],
            "stack": self.stack.to_dict() if self.stack else None,
            "taproot": self.taproot.to_dict() if self.taproot else None,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


class BitcoinScriptFrontend:
    """Normalize Bitcoin spend conditions into Crypto IR-oriented records.

    Offline by design.  Resource bounds are explicit.  The frontend never
    opens sockets, resolves secrets, signs, or broadcasts.
    """

    def __init__(
        self,
        *,
        max_script_bytes: int = DEFAULT_MAX_SCRIPT_BYTES,
        max_ops: int = DEFAULT_MAX_OPS,
        max_witness_items: int = DEFAULT_MAX_WITNESS_ITEMS,
        max_psbt_inputs: int = DEFAULT_MAX_PSBT_INPUTS,
        max_spend_paths: int = DEFAULT_MAX_SPEND_PATHS,
    ) -> None:
        self._max_script_bytes = _positive(max_script_bytes, "max_script_bytes")
        self._max_ops = _positive(max_ops, "max_ops")
        self._max_witness_items = _positive(max_witness_items, "max_witness_items")
        self._max_psbt_inputs = _positive(max_psbt_inputs, "max_psbt_inputs")
        self._max_spend_paths = _positive(max_spend_paths, "max_spend_paths")

    @property
    def frontend_id(self) -> str:
        return FRONTEND_ID

    @property
    def version(self) -> str:
        return FRONTEND_VERSION

    def decode_locking_script(
        self,
        script: bytes | str,
        *,
        version: ScriptVersion | str = ScriptVersion.LEGACY,
    ) -> ScriptProgram:
        """Decode a locking / redeem / witness script within resource bounds."""

        return decode_script(
            script,
            version=version,
            max_script_bytes=self._max_script_bytes,
            max_ops=self._max_ops,
        )

    def bind_prevout(
        self,
        *,
        txid: str,
        vout: int,
        value_sats: int,
        script_pubkey: bytes | str,
        known: bool = True,
        attributes: Mapping[str, Any] | None = None,
    ) -> PrevoutBinding:
        """Bind exact prevout amount and scriptPubKey for spend semantics."""

        data = normalize_script_bytes(script_pubkey)
        if len(data) > self._max_script_bytes:
            raise ResourceLimitError("script_pubkey exceeds max_script_bytes")
        return bind_prevout(
            txid=txid,
            vout=vout,
            value_sats=value_sats,
            script_pubkey=data,
            known=known,
            attributes=attributes,
        )

    def bind_sighash(
        self,
        *,
        sighash_type: int,
        input_index: int,
        prevout: PrevoutBinding | None = None,
        script_code: bytes | str = b"",
        sequence: int | None = None,
        locktime: int | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> SighashCommitment:
        """Bind sighash flags and commitment surface for one input."""

        return bind_sighash(
            sighash_type=sighash_type,
            input_index=input_index,
            prevout=prevout,
            script_code=script_code,
            sequence=sequence,
            locktime=locktime,
            attributes=attributes,
        )

    def bind_witness(self, items: Sequence[bytes | str]) -> WitnessStack:
        """Normalize a witness stack with resource bounds."""

        return bind_witness(
            items,
            max_items=self._max_witness_items,
            max_total_bytes=self._max_script_bytes,
        )

    def bind_tapscript_leaf(
        self,
        script: bytes | str,
        *,
        leaf_version: int = 0xC0,
        availability: LeafAvailability | str = LeafAvailability.AVAILABLE,
        attributes: Mapping[str, Any] | None = None,
    ) -> TapscriptLeaf:
        """Bind a Tapscript leaf (hidden leaves stay incomplete)."""

        data = normalize_script_bytes(script)
        if len(data) > self._max_script_bytes:
            raise ResourceLimitError("tapscript leaf exceeds max_script_bytes")
        return bind_tapscript_leaf(
            data,
            leaf_version=leaf_version,
            availability=availability,
            decode=True,
            attributes=attributes,
        )

    def parse_control_block(self, control: bytes | str) -> ControlBlock:
        """Parse a BIP-341 control block."""

        return parse_control_block(control)

    def bind_taproot(
        self,
        *,
        internal_key: bytes | str,
        output_key: bytes | str = b"",
        revealed_leaves: Sequence[TapscriptLeaf] = (),
        control_block: ControlBlock | None = None,
        hidden_branch_digests: Sequence[str] = (),
        spend_path: SpendPathKind | str = SpendPathKind.UNKNOWN,
        attributes: Mapping[str, Any] | None = None,
    ) -> TaprootCommitment:
        """Bind a Taproot commitment with hidden-branch tracking."""

        return bind_taproot_commitment(
            internal_key=internal_key,
            output_key=output_key,
            revealed_leaves=revealed_leaves,
            control_block=control_block,
            hidden_branch_digests=hidden_branch_digests,
            spend_path=spend_path,
            attributes=attributes,
        )

    def parse_miniscript(self, expression: str) -> MiniscriptPolicy:
        """Parse a Miniscript / policy expression."""

        return parse_miniscript(expression)

    def parse_descriptor(self, descriptor: str) -> OutputDescriptor:
        """Parse an output descriptor (checksum optional)."""

        return parse_descriptor(descriptor)

    def compare_policies(
        self,
        left: MiniscriptPolicy | str,
        right: MiniscriptPolicy | str,
    ) -> PolicyEquivalenceStatus:
        """Prove policy equality or return explicit unknown/unequal."""

        return compare_policies(left, right)

    def compare_descriptors(
        self,
        left: OutputDescriptor | str,
        right: OutputDescriptor | str,
    ) -> PolicyEquivalenceStatus:
        """Prove descriptor/policy equality or return explicit unknown."""

        return compare_descriptors(left, right)

    def bind_psbt_input(
        self,
        *,
        input_index: int,
        prevout: PrevoutBinding | None = None,
        redeem_script: bytes | str | ScriptProgram | None = None,
        witness_script: bytes | str | ScriptProgram | None = None,
        witness_items: Sequence[bytes | str] | None = None,
        sighash_type: int | None = None,
        sequence: int | None = None,
        locktime: int | None = None,
        taproot: TaprootCommitment | None = None,
        partial_sigs_count: int = 0,
        is_final: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> PSBTInputBinding:
        """Bind one PSBT input without accepting signing material."""

        redeem: ScriptProgram | None = None
        if isinstance(redeem_script, ScriptProgram):
            redeem = redeem_script
        elif redeem_script:
            redeem = self.decode_locking_script(redeem_script)

        witness_prog: ScriptProgram | None = None
        if isinstance(witness_script, ScriptProgram):
            witness_prog = witness_script
        elif witness_script:
            witness_prog = self.decode_locking_script(
                witness_script, version=ScriptVersion.SEG_WIT_V0
            )

        witness: WitnessStack | None = None
        if witness_items is not None:
            witness = self.bind_witness(witness_items)

        sighash: SighashCommitment | None = None
        if sighash_type is not None:
            script_code = b""
            if witness_prog is not None:
                script_code = bytes.fromhex(witness_prog.script_hex)
            elif redeem is not None:
                script_code = bytes.fromhex(redeem.script_hex)
            sighash = self.bind_sighash(
                sighash_type=sighash_type,
                input_index=input_index,
                prevout=prevout,
                script_code=script_code,
                sequence=sequence,
                locktime=locktime,
            )

        complete = (
            prevout is not None
            and prevout.known
            and (is_final or (witness is not None and witness.item_count > 0))
            and (sighash is None or not sighash.is_weak)
        )
        return PSBTInputBinding(
            input_index=input_index,
            prevout=prevout,
            redeem_script=redeem,
            witness_script=witness_prog,
            witness=witness,
            sighash=sighash,
            sequence=sequence,
            taproot=taproot,
            partial_sigs_count=partial_sigs_count,
            is_final=is_final,
            complete=complete,
            attributes=dict(attributes or {}),
        )

    def bind_psbt(
        self,
        inputs: Sequence[PSBTInputBinding],
        *,
        locktime: int | None = None,
        version: int | None = None,
        mark_complete: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> PSBTBinding:
        """Bind a multi-input PSBT analysis record."""

        if len(inputs) > self._max_psbt_inputs:
            raise ResourceLimitError("PSBT exceeds max_psbt_inputs")
        return PSBTBinding(
            inputs=tuple(inputs),
            locktime=locktime,
            version=version,
            role=PSBTRole.ANALYZER,
            complete=mark_complete,
            attributes=dict(attributes or {}),
        )

    def analyze_spend(
        self,
        *,
        chain_id: str,
        network: str = "",
        script_pubkey: bytes | str = b"",
        prevout: PrevoutBinding | None = None,
        redeem_script: bytes | str | None = None,
        witness_script: bytes | str | None = None,
        witness_items: Sequence[bytes | str] | None = None,
        sighash_type: int | None = None,
        sequence: int | None = None,
        locktime: int | None = None,
        input_index: int = 0,
        taproot: TaprootCommitment | None = None,
        policy_expression: str = "",
        descriptor: str = "",
        alternate_scripts: Sequence[bytes | str] = (),
        hidden_tap_branches: Sequence[str] = (),
        claim_pass: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> BitcoinNormalizationResult:
        """Normalize one spend-condition observation into Crypto IR records.

        Parameters model UTXO spend context only.  Alternate scripts become
        alternative spending paths; hidden tap branches remain incomplete.
        """

        chain = _required_text(chain_id, "chain_id")
        diagnostics: list[str] = []
        paths: list[SpendingPathRecord] = []

        # Primary locking program.
        primary: ScriptProgram | None = None
        if script_pubkey:
            primary = self.decode_locking_script(script_pubkey)
        elif prevout is not None and prevout.script_pubkey_hex:
            primary = self.decode_locking_script(prevout.script_pubkey_hex)

        # Bound prevout if only script_pubkey provided without prevout.
        if prevout is None and script_pubkey:
            diagnostics.append("prevout unbound — spend path incomplete")

        # Redeem / witness programs (P2SH / P2WSH).
        redeem_prog: ScriptProgram | None = None
        if redeem_script:
            redeem_prog = self.decode_locking_script(redeem_script)

        witness_prog: ScriptProgram | None = None
        if witness_script:
            witness_prog = self.decode_locking_script(
                witness_script, version=ScriptVersion.SEG_WIT_V0
            )

        # Effective program for stack analysis prefers witness/redeem body.
        effective = witness_prog or redeem_prog or primary

        witness: WitnessStack | None = None
        if witness_items is not None:
            witness = self.bind_witness(witness_items)

        sighash: SighashCommitment | None = None
        if sighash_type is not None:
            script_code = b""
            if witness_prog is not None:
                script_code = bytes.fromhex(witness_prog.script_hex)
            elif redeem_prog is not None:
                script_code = bytes.fromhex(redeem_prog.script_hex)
            elif primary is not None:
                script_code = bytes.fromhex(primary.script_hex)
            sighash = self.bind_sighash(
                sighash_type=sighash_type,
                input_index=input_index,
                prevout=prevout,
                script_code=script_code,
                sequence=sequence,
                locktime=locktime,
            )
            if sighash.is_weak:
                diagnostics.append("weak sighash flags present")

        stack: StackSemanticRecord | None = None
        if effective is not None:
            stack = analyze_stack_semantics(
                effective,
                prevout=prevout,
                sighash=sighash,
                witness=witness,
                claim_pass=claim_pass,
                sequence=sequence,
                locktime=locktime,
            )
            diagnostics.extend(stack.diagnostics)
            paths.append(
                SpendingPathRecord(
                    path_id="primary",
                    program=effective,
                    stack=stack,
                    tapleaf=None,
                    policy=None,
                    available=True,
                    pass_status=stack.pass_status,
                    diagnostics=stack.diagnostics,
                )
            )

        # Alternative spending paths (e.g. second branch of a tree / policy).
        for index, alt in enumerate(alternate_scripts):
            if len(paths) >= self._max_spend_paths:
                raise ResourceLimitError("spending paths exceed max_spend_paths")
            alt_prog = self.decode_locking_script(alt)
            alt_stack = analyze_stack_semantics(
                alt_prog,
                prevout=prevout,
                sighash=sighash,
                witness=None,
                claim_pass=False,
                sequence=sequence,
                locktime=locktime,
            )
            paths.append(
                SpendingPathRecord(
                    path_id=f"alternate:{index}",
                    program=alt_prog,
                    stack=alt_stack,
                    tapleaf=None,
                    policy=None,
                    available=True,
                    pass_status=alt_stack.pass_status,
                    diagnostics=alt_stack.diagnostics
                    + ("alternative spend path",),
                )
            )
            diagnostics.append(f"alternate spend path {index} recorded")

        # Taproot path.
        if taproot is not None:
            if hidden_tap_branches:
                # Merge additional hidden branch markers.
                taproot = bind_taproot_commitment(
                    internal_key=bytes.fromhex(taproot.internal_key_hex),
                    output_key=bytes.fromhex(taproot.output_key_hex)
                    if taproot.output_key_hex
                    else b"",
                    revealed_leaves=taproot.revealed_leaves,
                    control_block=taproot.control_block,
                    hidden_branch_digests=list(taproot.hidden_branches)
                    + list(hidden_tap_branches),
                    spend_path=taproot.spend_path,
                    attributes=dict(taproot.attributes),
                )
            tap_status = tapscript_path_status(taproot, claim_pass=claim_pass)
            if taproot.hidden_branches:
                diagnostics.append("hidden taproot branches remain incomplete")
                paths.append(
                    SpendingPathRecord(
                        path_id="taproot:hidden",
                        program=None,
                        stack=None,
                        tapleaf=None,
                        policy=None,
                        available=False,
                        pass_status=SemanticPassStatus.INCOMPLETE,
                        diagnostics=("hidden or unavailable branch",),
                    )
                )
            for leaf_index, leaf in enumerate(taproot.revealed_leaves):
                leaf_status = (
                    SemanticPassStatus.INCOMPLETE
                    if leaf.is_hidden
                    else (
                        stack.pass_status
                        if stack is not None and leaf.program is effective
                        else tapscript_path_status(taproot, claim_pass=claim_pass)
                    )
                )
                paths.append(
                    SpendingPathRecord(
                        path_id=f"tapleaf:{leaf_index}",
                        program=leaf.program,
                        stack=None,
                        tapleaf=leaf,
                        policy=None,
                        available=not leaf.is_hidden,
                        pass_status=leaf_status
                        if not leaf.is_hidden
                        else SemanticPassStatus.INCOMPLETE,
                        diagnostics=()
                        if not leaf.is_hidden
                        else ("leaf hidden or unavailable",),
                    )
                )
            if tap_status is not SemanticPassStatus.PASS:
                diagnostics.append(f"taproot path status={tap_status.value}")

        # Policy / descriptor.
        policy: MiniscriptPolicy | None = None
        if policy_expression:
            policy = self.parse_miniscript(policy_expression)
            if not policy.fully_parsed:
                diagnostics.append("miniscript policy not fully parsed")

        desc: OutputDescriptor | None = None
        policy_eq = PolicyEquivalenceStatus.UNKNOWN
        if descriptor:
            desc = self.parse_descriptor(descriptor)
            if desc.miniscript is not None:
                if policy is None:
                    policy = desc.miniscript
                else:
                    policy_eq = self.compare_policies(policy, desc.miniscript)
                    if policy_eq is PolicyEquivalenceStatus.PROVEN_UNEQUAL:
                        diagnostics.append("descriptor/miniscript policy mismatch")
                    elif policy_eq is PolicyEquivalenceStatus.UNKNOWN:
                        diagnostics.append(
                            "descriptor/miniscript policy equality unknown"
                        )

        # Analysis mode.
        if taproot is not None and taproot.spend_path is SpendPathKind.KEY_PATH:
            mode = AnalysisMode.KEY_PATH
        elif effective is not None or taproot is not None:
            mode = AnalysisMode.SPEND_PATH
        elif policy is not None or desc is not None:
            mode = AnalysisMode.POLICY_ONLY
        else:
            mode = AnalysisMode.INCOMPLETE

        # Aggregate semantic status (stack record is authoritative when present).
        weak = bool(sighash and sighash.is_weak)
        hidden = bool(taproot and taproot.hidden_branches)
        if stack is not None:
            status = stack.pass_status
        else:
            status = incomplete_spend_never_passes(
                fully_decoded=bool(effective and effective.fully_decoded)
                if effective
                else False,
                unsupported_opcodes=effective.unsupported_opcodes if effective else (),
                prevout_known=bool(prevout and prevout.known),
                weak_sighash=weak,
                hidden_branch=hidden,
                claim_pass=claim_pass,
            )
        if hidden and status is SemanticPassStatus.PASS:
            status = SemanticPassStatus.INCOMPLETE
        if policy_eq is PolicyEquivalenceStatus.PROVEN_UNEQUAL:
            diagnostics.append("policy mismatch forces fail-closed when claiming pass")
            if claim_pass or status is SemanticPassStatus.PASS:
                status = SemanticPassStatus.FAIL_CLOSED
        if not effective and not policy and not taproot:
            status = SemanticPassStatus.INCOMPLETE
            mode = AnalysisMode.INCOMPLETE
            diagnostics.append("no spend condition evidence supplied")

        # When only policy is available, never claim execution pass.
        if mode is AnalysisMode.POLICY_ONLY and claim_pass:
            status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append("policy-only analysis cannot claim execution pass")

        return BitcoinNormalizationResult(
            chain_id=chain,
            network=network,
            prevout=prevout,
            primary_program=primary or effective,
            stack=stack,
            taproot=taproot,
            policy=policy,
            descriptor=desc,
            psbt=None,
            spending_paths=tuple(paths),
            analysis_mode=mode,
            semantic_pass_status=status,
            policy_equivalence=policy_eq,
            diagnostics=tuple(dict.fromkeys(diagnostics)),  # stable unique
            attributes=dict(attributes or {}),
        )

    def normalize_psbt_spend(
        self,
        *,
        chain_id: str,
        psbt: PSBTBinding,
        network: str = "",
        policy_expression: str = "",
        descriptor: str = "",
        claim_pass: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> BitcoinNormalizationResult:
        """Normalize a PSBT binding into a spend-condition result."""

        if not psbt.inputs:
            raise InvalidRequestError("PSBT must contain at least one input")
        first = psbt.inputs[0]
        # Analyze first input as primary; remaining paths listed as alternates.
        script_hex = ""
        if first.prevout and first.prevout.script_pubkey_hex:
            script_hex = first.prevout.script_pubkey_hex
        elif first.witness_script is not None:
            script_hex = first.witness_script.script_hex
        elif first.redeem_script is not None:
            script_hex = first.redeem_script.script_hex

        result = self.analyze_spend(
            chain_id=chain_id,
            network=network,
            script_pubkey=script_hex,
            prevout=first.prevout,
            redeem_script=first.redeem_script.script_hex
            if first.redeem_script
            else None,
            witness_script=first.witness_script.script_hex
            if first.witness_script
            else None,
            witness_items=first.witness.items if first.witness else None,
            sighash_type=first.sighash.sighash_type if first.sighash else None,
            sequence=first.sequence,
            locktime=psbt.locktime,
            input_index=first.input_index,
            taproot=first.taproot,
            policy_expression=policy_expression,
            descriptor=descriptor,
            claim_pass=claim_pass and psbt.complete and not psbt.has_weak_sighash,
            attributes=attributes,
        )
        # Attach PSBT and fold multi-input prevout completeness.
        status = result.semantic_pass_status
        diagnostics = list(result.diagnostics)
        if not psbt.all_prevouts_known:
            diagnostics.append("not all PSBT prevouts known")
            if status is SemanticPassStatus.PASS:
                status = SemanticPassStatus.INCOMPLETE
        if psbt.has_weak_sighash:
            diagnostics.append("PSBT contains weak sighash")
            if claim_pass:
                status = SemanticPassStatus.FAIL_CLOSED
            elif status is SemanticPassStatus.PASS:
                status = SemanticPassStatus.FAIL_CLOSED

        return BitcoinNormalizationResult(
            chain_id=result.chain_id,
            network=result.network,
            prevout=result.prevout,
            primary_program=result.primary_program,
            stack=result.stack,
            taproot=result.taproot,
            policy=result.policy,
            descriptor=result.descriptor,
            psbt=psbt,
            spending_paths=result.spending_paths,
            analysis_mode=result.analysis_mode,
            semantic_pass_status=status,
            policy_equivalence=result.policy_equivalence,
            diagnostics=tuple(diagnostics),
            attributes=dict(result.attributes),
        )


__all__ = [
    "DEFAULT_MAX_PSBT_INPUTS",
    "DEFAULT_MAX_SPEND_PATHS",
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "AnalysisMode",
    "BitcoinNormalizationResult",
    "BitcoinScriptFrontend",
    "PSBTBinding",
    "PSBTInputBinding",
    "PSBTRole",
    "SpendingPathRecord",
    # Re-exported AST / semantic surface
    "ControlBlock",
    "DescriptorType",
    "HashlockConstraint",
    "LeafAvailability",
    "MiniscriptPolicy",
    "OutputDescriptor",
    "PolicyEquivalenceStatus",
    "PrevoutBinding",
    "ScriptForm",
    "ScriptProgram",
    "ScriptVersion",
    "SemanticPassStatus",
    "SighashCommitment",
    "SighashFlag",
    "SpendPathKind",
    "StackSemanticRecord",
    "TaprootCommitment",
    "TapscriptLeaf",
    "TimelockConstraint",
    "WitnessStack",
    "FRONTEND_SCHEMA_VERSION",
    "MINISCRIPT_SCHEMA_VERSION",
    "SCRIPT_SCHEMA_VERSION",
    "TAPSCRIPT_SCHEMA_VERSION",
]

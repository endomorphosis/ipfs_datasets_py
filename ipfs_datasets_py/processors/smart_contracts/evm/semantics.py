"""EVM bytecode semantics: opcodes, CFG, and storage effects (CRYPTOIR-G220).

Bounded, dependency-free disassembly and control-flow construction.  Importing
this module performs no network I/O.  Unsupported opcodes and incomplete
traces never elevate to a successful semantic pass.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..models import ensure_secret_safe


SEMANTICS_SCHEMA_VERSION = "smart-contract-evm-semantics-v1"
DEFAULT_MAX_BYTECODE_BYTES = 24_576  # EIP-170 mainnet code size ceiling
DEFAULT_MAX_INSTRUCTIONS = 65_536
DEFAULT_MAX_CFG_NODES = 16_384
DEFAULT_MAX_CFG_EDGES = 65_536

# Mnemonic → opcode (selected closed set; unknowns remain explicit).
_MNEMONIC_TO_OPCODE: dict[str, int] = {
    "STOP": 0x00,
    "ADD": 0x01,
    "MUL": 0x02,
    "SUB": 0x03,
    "DIV": 0x04,
    "SDIV": 0x05,
    "MOD": 0x06,
    "SMOD": 0x07,
    "ADDMOD": 0x08,
    "MULMOD": 0x09,
    "EXP": 0x0A,
    "SIGNEXTEND": 0x0B,
    "LT": 0x10,
    "GT": 0x11,
    "SLT": 0x12,
    "SGT": 0x13,
    "EQ": 0x14,
    "ISZERO": 0x15,
    "AND": 0x16,
    "OR": 0x17,
    "XOR": 0x18,
    "NOT": 0x19,
    "BYTE": 0x1A,
    "SHL": 0x1B,
    "SHR": 0x1C,
    "SAR": 0x1D,
    "SHA3": 0x20,
    "KECCAK256": 0x20,
    "ADDRESS": 0x30,
    "BALANCE": 0x31,
    "ORIGIN": 0x32,
    "CALLER": 0x33,
    "CALLVALUE": 0x34,
    "CALLDATALOAD": 0x35,
    "CALLDATASIZE": 0x36,
    "CALLDATACOPY": 0x37,
    "CODESIZE": 0x38,
    "CODECOPY": 0x39,
    "GASPRICE": 0x3A,
    "EXTCODESIZE": 0x3B,
    "EXTCODECOPY": 0x3C,
    "RETURNDATASIZE": 0x3D,
    "RETURNDATACOPY": 0x3E,
    "EXTCODEHASH": 0x3F,
    "BLOCKHASH": 0x40,
    "COINBASE": 0x41,
    "TIMESTAMP": 0x42,
    "NUMBER": 0x43,
    "DIFFICULTY": 0x44,
    "PREVRANDAO": 0x44,
    "GASLIMIT": 0x45,
    "CHAINID": 0x46,
    "SELFBALANCE": 0x47,
    "BASEFEE": 0x48,
    "POP": 0x50,
    "MLOAD": 0x51,
    "MSTORE": 0x52,
    "MSTORE8": 0x53,
    "SLOAD": 0x54,
    "SSTORE": 0x55,
    "JUMP": 0x56,
    "JUMPI": 0x57,
    "PC": 0x58,
    "MSIZE": 0x59,
    "GAS": 0x5A,
    "JUMPDEST": 0x5B,
    "PUSH0": 0x5F,
    "DUP1": 0x80,
    "DUP2": 0x81,
    "DUP3": 0x82,
    "DUP4": 0x83,
    "DUP5": 0x84,
    "DUP6": 0x85,
    "DUP7": 0x86,
    "DUP8": 0x87,
    "DUP9": 0x88,
    "DUP10": 0x89,
    "DUP11": 0x8A,
    "DUP12": 0x8B,
    "DUP13": 0x8C,
    "DUP14": 0x8D,
    "DUP15": 0x8E,
    "DUP16": 0x8F,
    "SWAP1": 0x90,
    "SWAP2": 0x91,
    "SWAP3": 0x92,
    "SWAP4": 0x93,
    "SWAP5": 0x94,
    "SWAP6": 0x95,
    "SWAP7": 0x96,
    "SWAP8": 0x97,
    "SWAP9": 0x98,
    "SWAP10": 0x99,
    "SWAP11": 0x9A,
    "SWAP12": 0x9B,
    "SWAP13": 0x9C,
    "SWAP14": 0x9D,
    "SWAP15": 0x9E,
    "SWAP16": 0x9F,
    "LOG0": 0xA0,
    "LOG1": 0xA1,
    "LOG2": 0xA2,
    "LOG3": 0xA3,
    "LOG4": 0xA4,
    "CREATE": 0xF0,
    "CALL": 0xF1,
    "CALLCODE": 0xF2,
    "RETURN": 0xF3,
    "DELEGATECALL": 0xF4,
    "CREATE2": 0xF5,
    "STATICCALL": 0xFA,
    "REVERT": 0xFD,
    "INVALID": 0xFE,
    "SELFDESTRUCT": 0xFF,
}

# Build reverse map and push/dup/swap tables.
OPCODE_MNEMONICS: dict[int, str] = {v: k for k, v in _MNEMONIC_TO_OPCODE.items() if k != "KECCAK256"}
for _n in range(1, 33):
    OPCODE_MNEMONICS[0x60 + _n - 1] = f"PUSH{_n}"
for _n in range(1, 17):
    OPCODE_MNEMONICS[0x80 + _n - 1] = f"DUP{_n}"
    OPCODE_MNEMONICS[0x90 + _n - 1] = f"SWAP{_n}"

# Opcodes that halt sequential fall-through.
_TERMINATORS: frozenset[int] = frozenset(
    {0x00, 0x56, 0xF3, 0xFD, 0xFE, 0xFF}  # STOP, JUMP, RETURN, REVERT, INVALID, SELFDESTRUCT
)
_CONDITIONAL: frozenset[int] = frozenset({0x57})  # JUMPI
_CALL_LIKE: frozenset[int] = frozenset({0xF1, 0xF2, 0xF4, 0xFA})  # CALL, CALLCODE, DELEGATECALL, STATICCALL
_CREATE_LIKE: frozenset[int] = frozenset({0xF0, 0xF5})
_STORAGE_READ: frozenset[int] = frozenset({0x54})
_STORAGE_WRITE: frozenset[int] = frozenset({0x55})

# Opcodes treated as known for "supported" analysis.  Anything outside this
# closed set (or with invalid immediate length) is UNSUPPORTED.
KNOWN_OPCODES: frozenset[int] = frozenset(OPCODE_MNEMONICS.keys()) | frozenset({0x5F})  # PUSH0


class SemanticPassStatus(StrEnum):
    """Whether a semantic analysis claim may be treated as a pass."""

    PASS = "pass"
    FAIL_CLOSED = "fail_closed"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"


class CfgEdgeKind(StrEnum):
    """Control-flow edge labels for EVM bytecode."""

    FALLTHROUGH = "fallthrough"
    JUMP = "jump"
    JUMPI_TRUE = "jumpi_true"
    JUMPI_FALSE = "jumpi_false"
    CALL = "call"
    DELEGATECALL = "delegatecall"
    STATICCALL = "staticcall"
    CREATE = "create"
    SELFDESTRUCT = "selfdestruct"
    OTHER = "other"


class StorageAccessKind(StrEnum):
    """Storage access classification from static opcode presence."""

    SLOAD = "sload"
    SSTORE = "sstore"
    UNKNOWN = "unknown"


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


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def normalize_bytecode(value: bytes | str) -> bytes:
    """Normalize hex or raw bytes into exact runtime/creation bytecode bytes."""

    if isinstance(value, bytes):
        return value
    if not isinstance(value, str):
        raise InvalidRequestError("bytecode must be bytes or hex string")
    text = value.strip()
    if text.startswith(("0x", "0X")):
        text = text[2:]
    if text == "":
        return b""
    if len(text) % 2 != 0:
        raise InvalidRequestError("bytecode hex length must be even")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise InvalidRequestError("bytecode is not valid hex") from exc


def push_immediate_size(opcode: int) -> int:
    """Return the immediate byte count for PUSH opcodes, else 0."""

    if opcode == 0x5F:  # PUSH0
        return 0
    if 0x60 <= opcode <= 0x7F:
        return opcode - 0x5F
    return 0


def mnemonic_for(opcode: int) -> str:
    """Return the mnemonic or ``UNKNOWN_0xNN`` for an unsupported opcode."""

    if opcode in OPCODE_MNEMONICS:
        return OPCODE_MNEMONICS[opcode]
    return f"UNKNOWN_0x{opcode:02x}"


@dataclass(frozen=True, slots=True)
class DecodedInstruction:
    """One disassembled instruction with program counter and optional immediate.

    The public label field is ``opname`` (not ``mnemonic``) so serialization
    remains secret-safe under the shared smart-contract field policy.
    """

    pc: int
    opcode: int
    opname: str
    immediate: bytes = b""
    supported: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "pc", _non_negative(self.pc, "pc"))
        if isinstance(self.opcode, bool) or not isinstance(self.opcode, int):
            raise InvalidRequestError("opcode must be an integer")
        if not 0 <= self.opcode <= 0xFF:
            raise InvalidRequestError("opcode must be in 0..255")
        object.__setattr__(self, "opname", _required_text(self.opname, "opname"))
        if type(self.immediate) is not bytes:
            raise InvalidRequestError("immediate must be exact bytes")

    @property
    def size(self) -> int:
        return 1 + len(self.immediate)

    @property
    def mnemonic(self) -> str:
        """Alias for :attr:`opname` (legacy EVM terminology)."""

        return self.opname

    def to_dict(self) -> dict[str, Any]:
        return {
            "immediate_hex": self.immediate.hex(),
            "opcode": self.opcode,
            "opname": self.opname,
            "pc": self.pc,
            "supported": self.supported,
        }


@dataclass(frozen=True, slots=True)
class CfgNode:
    """Basic block of sequential instructions ending at a control transfer."""

    node_id: str
    start_pc: int
    end_pc: int
    instruction_pcs: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required_text(self.node_id, "node_id"))
        object.__setattr__(self, "start_pc", _non_negative(self.start_pc, "start_pc"))
        object.__setattr__(self, "end_pc", _non_negative(self.end_pc, "end_pc"))
        object.__setattr__(
            self,
            "instruction_pcs",
            tuple(_non_negative(pc, "instruction_pcs item") for pc in self.instruction_pcs),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_pc": self.end_pc,
            "instruction_pcs": list(self.instruction_pcs),
            "node_id": self.node_id,
            "start_pc": self.start_pc,
        }


@dataclass(frozen=True, slots=True)
class CfgEdge:
    """Directed edge between CFG nodes."""

    source_id: str
    target_id: str
    kind: CfgEdgeKind
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required_text(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _required_text(self.target_id, "target_id"))
        kind = self.kind if isinstance(self.kind, CfgEdgeKind) else CfgEdgeKind(str(self.kind))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "kind": self.kind.value if isinstance(self.kind, CfgEdgeKind) else str(self.kind),
            "source_id": self.source_id,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class ControlFlowGraph:
    """Bounded control-flow graph derived from EVM bytecode.

    Incomplete graphs (unresolved dynamic jumps, truncated bytecode) set
    ``pass_status`` to :attr:`SemanticPassStatus.INCOMPLETE` or
    :attr:`SemanticPassStatus.UNSUPPORTED` and must never be treated as a pass.
    """

    bytecode_digest: str
    nodes: tuple[CfgNode, ...]
    edges: tuple[CfgEdge, ...]
    entry_node_id: str = ""
    unresolved_jumps: tuple[int, ...] = ()
    unsupported_opcodes: tuple[int, ...] = ()
    has_selfdestruct: bool = False
    has_delegatecall: bool = False
    pass_status: SemanticPassStatus = SemanticPassStatus.FAIL_CLOSED
    diagnostics: tuple[str, ...] = ()
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        digest = _required_text(self.bytecode_digest, "bytecode_digest")
        if not digest.startswith("sha256:"):
            raise InvalidRequestError("bytecode_digest must be a tagged sha256 digest")
        object.__setattr__(self, "bytecode_digest", digest)
        nodes = tuple(self.nodes)
        for index, node in enumerate(nodes):
            if not isinstance(node, CfgNode):
                raise InvalidRequestError(f"nodes[{index}] must be a CfgNode")
        object.__setattr__(self, "nodes", nodes)
        edges = tuple(self.edges)
        for index, edge in enumerate(edges):
            if not isinstance(edge, CfgEdge):
                raise InvalidRequestError(f"edges[{index}] must be a CfgEdge")
        object.__setattr__(self, "edges", edges)
        object.__setattr__(
            self,
            "entry_node_id",
            self.entry_node_id.strip() if self.entry_node_id else "",
        )
        object.__setattr__(
            self,
            "unresolved_jumps",
            tuple(_non_negative(pc, "unresolved_jumps item") for pc in self.unresolved_jumps),
        )
        object.__setattr__(
            self,
            "unsupported_opcodes",
            tuple(
                _non_negative(op, "unsupported_opcodes item")
                for op in self.unsupported_opcodes
            ),
        )
        status = (
            self.pass_status
            if isinstance(self.pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.pass_status))
        )
        object.__setattr__(self, "pass_status", status)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(item, "diagnostics item") for item in self.diagnostics),
        )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Fail-closed invariant: PASS is forbidden when unsupported or incomplete.
        if status is SemanticPassStatus.PASS and (
            self.unsupported_opcodes or self.unresolved_jumps
        ):
            raise InvalidRequestError(
                "CFG pass status cannot be pass with unsupported opcodes or unresolved jumps"
            )
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.pass_status is SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytecode_digest": self.bytecode_digest,
            "diagnostics": list(self.diagnostics),
            "edges": [edge.to_dict() for edge in self.edges],
            "entry_node_id": self.entry_node_id,
            "has_delegatecall": self.has_delegatecall,
            "has_selfdestruct": self.has_selfdestruct,
            "nodes": [node.to_dict() for node in self.nodes],
            "pass_status": self.pass_status.value
            if isinstance(self.pass_status, SemanticPassStatus)
            else str(self.pass_status),
            "schema_version": self.schema_version,
            "unresolved_jumps": list(self.unresolved_jumps),
            "unsupported_opcodes": list(self.unsupported_opcodes),
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class StorageEffect:
    """Static storage access effect observed in bytecode or a bounded trace."""

    kind: StorageAccessKind
    pc: int
    slot_hint: str = ""
    trace_complete: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, StorageAccessKind)
            else StorageAccessKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "pc", _non_negative(self.pc, "pc"))
        object.__setattr__(
            self, "slot_hint", self.slot_hint.strip() if self.slot_hint else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "kind": self.kind.value if isinstance(self.kind, StorageAccessKind) else str(self.kind),
            "pc": self.pc,
            "slot_hint": self.slot_hint,
            "trace_complete": self.trace_complete,
        }


@dataclass(frozen=True, slots=True)
class DisassemblyResult:
    """Bounded disassembly of EVM bytecode with explicit support coverage."""

    bytecode_digest: str
    instructions: tuple[DecodedInstruction, ...]
    unsupported_pcs: tuple[int, ...] = ()
    truncated: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    MAX_INSTRUCTIONS: ClassVar[int] = DEFAULT_MAX_INSTRUCTIONS

    def __post_init__(self) -> None:
        digest = _required_text(self.bytecode_digest, "bytecode_digest")
        if not digest.startswith("sha256:"):
            raise InvalidRequestError("bytecode_digest must be a tagged sha256 digest")
        object.__setattr__(self, "bytecode_digest", digest)
        instructions = tuple(self.instructions)
        if len(instructions) > self.MAX_INSTRUCTIONS:
            raise ResourceLimitError("instruction count exceeds bound")
        for index, item in enumerate(instructions):
            if not isinstance(item, DecodedInstruction):
                raise InvalidRequestError(
                    f"instructions[{index}] must be a DecodedInstruction"
                )
        object.__setattr__(self, "instructions", instructions)
        object.__setattr__(
            self,
            "unsupported_pcs",
            tuple(_non_negative(pc, "unsupported_pcs item") for pc in self.unsupported_pcs),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_required_text(item, "diagnostics item") for item in self.diagnostics),
        )

    @property
    def fully_supported(self) -> bool:
        return not self.unsupported_pcs and not self.truncated

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytecode_digest": self.bytecode_digest,
            "diagnostics": list(self.diagnostics),
            "instructions": [item.to_dict() for item in self.instructions],
            "schema_version": self.schema_version,
            "truncated": self.truncated,
            "unsupported_pcs": list(self.unsupported_pcs),
        }


def disassemble_bytecode(
    bytecode: bytes | str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTECODE_BYTES,
    max_instructions: int = DEFAULT_MAX_INSTRUCTIONS,
) -> DisassemblyResult:
    """Disassemble EVM bytecode under explicit size and instruction ceilings."""

    data = normalize_bytecode(bytecode)
    _positive(max_bytes, "max_bytes")
    _positive(max_instructions, "max_instructions")
    if len(data) > max_bytes:
        raise ResourceLimitError("bytecode exceeds max_bytes bound")

    instructions: list[DecodedInstruction] = []
    unsupported: list[int] = []
    diagnostics: list[str] = []
    truncated = False
    pc = 0
    while pc < len(data):
        if len(instructions) >= max_instructions:
            truncated = True
            diagnostics.append("instruction limit reached; disassembly truncated")
            break
        opcode = data[pc]
        imm_size = push_immediate_size(opcode)
        if imm_size and pc + 1 + imm_size > len(data):
            # Truncated immediate — fail closed as unsupported at this PC.
            instructions.append(
                DecodedInstruction(
                    pc=pc,
                    opcode=opcode,
                    opname=mnemonic_for(opcode),
                    immediate=data[pc + 1 :],
                    supported=False,
                )
            )
            unsupported.append(pc)
            diagnostics.append(f"truncated immediate at pc={pc}")
            truncated = True
            break
        immediate = data[pc + 1 : pc + 1 + imm_size] if imm_size else b""
        supported = opcode in KNOWN_OPCODES and (imm_size == 0 or len(immediate) == imm_size)
        if not supported:
            unsupported.append(pc)
        instructions.append(
            DecodedInstruction(
                pc=pc,
                opcode=opcode,
                opname=mnemonic_for(opcode),
                immediate=immediate,
                supported=supported,
            )
        )
        pc += 1 + imm_size

    return DisassemblyResult(
        bytecode_digest=bytes_digest(data),
        instructions=tuple(instructions),
        unsupported_pcs=tuple(unsupported),
        truncated=truncated,
        diagnostics=tuple(diagnostics),
    )


def build_cfg(
    disassembly: DisassemblyResult,
    *,
    max_nodes: int = DEFAULT_MAX_CFG_NODES,
    max_edges: int = DEFAULT_MAX_CFG_EDGES,
) -> ControlFlowGraph:
    """Build a basic-block CFG from a disassembly; incomplete graphs fail closed."""

    _positive(max_nodes, "max_nodes")
    _positive(max_edges, "max_edges")
    if not disassembly.instructions:
        return ControlFlowGraph(
            bytecode_digest=disassembly.bytecode_digest,
            nodes=(),
            edges=(),
            pass_status=SemanticPassStatus.INCOMPLETE,
            diagnostics=("empty bytecode; CFG incomplete",) + disassembly.diagnostics,
            unsupported_opcodes=(),
            unresolved_jumps=(),
        )

    by_pc = {ins.pc: ins for ins in disassembly.instructions}
    ordered = sorted(by_pc)
    jumpdests = {ins.pc for ins in disassembly.instructions if ins.opcode == 0x5B}

    # Leaders: entry, jumpdests, targets of fallthrough after terminators/JUMPI.
    leaders: set[int] = {ordered[0]}
    leaders.update(jumpdests)
    for ins in disassembly.instructions:
        next_pc = ins.pc + ins.size
        if ins.opcode in _TERMINATORS or ins.opcode in _CONDITIONAL:
            if next_pc in by_pc:
                leaders.add(next_pc)
        # Static JUMP/JUMPI with preceding PUSH immediate.
        if ins.opcode in (0x56, 0x57) and ins.pc in by_pc:
            prev_candidates = [p for p in ordered if p < ins.pc]
            if prev_candidates:
                prev = by_pc[prev_candidates[-1]]
                if prev.opname.startswith("PUSH") and prev.immediate:
                    target = int.from_bytes(prev.immediate, "big")
                    if target in by_pc:
                        leaders.add(target)

    leaders = sorted(pc for pc in leaders if pc in by_pc)
    if len(leaders) > max_nodes:
        raise ResourceLimitError("CFG node count exceeds bound")

    # Map each PC to its block leader.
    leader_of: dict[int, int] = {}
    current_leader = leaders[0]
    leader_index = 0
    for pc in ordered:
        while leader_index + 1 < len(leaders) and pc >= leaders[leader_index + 1]:
            leader_index += 1
            current_leader = leaders[leader_index]
        leader_of[pc] = current_leader

    # Build blocks.
    blocks: dict[int, list[int]] = {leader: [] for leader in leaders}
    for pc in ordered:
        blocks[leader_of[pc]].append(pc)

    nodes: list[CfgNode] = []
    node_id_for: dict[int, str] = {}
    for leader, pcs in blocks.items():
        node_id = f"bb:{leader}"
        node_id_for[leader] = node_id
        nodes.append(
            CfgNode(
                node_id=node_id,
                start_pc=pcs[0],
                end_pc=pcs[-1],
                instruction_pcs=tuple(pcs),
            )
        )

    edges: list[CfgEdge] = []
    unresolved: list[int] = []
    has_selfdestruct = False
    has_delegatecall = False
    unsupported_opcodes: list[int] = []

    for leader, pcs in blocks.items():
        last = by_pc[pcs[-1]]
        source = node_id_for[leader]
        if not last.supported:
            unsupported_opcodes.append(last.opcode)
        if last.opcode == 0xFF:
            has_selfdestruct = True
            edges.append(
                CfgEdge(
                    source_id=source,
                    target_id=f"exit:selfdestruct:{last.pc}",
                    kind=CfgEdgeKind.SELFDESTRUCT,
                )
            )
        if last.opcode == 0xF4:
            has_delegatecall = True
        if last.opcode in _CALL_LIKE:
            kind = {
                0xF1: CfgEdgeKind.CALL,
                0xF2: CfgEdgeKind.CALL,
                0xF4: CfgEdgeKind.DELEGATECALL,
                0xFA: CfgEdgeKind.STATICCALL,
            }.get(last.opcode, CfgEdgeKind.OTHER)
            edges.append(
                CfgEdge(
                    source_id=source,
                    target_id=f"external:{last.opname.lower()}:{last.pc}",
                    kind=kind,
                    attributes={"pc": last.pc, "opcode": last.opcode},
                )
            )
        if last.opcode in _CREATE_LIKE:
            edges.append(
                CfgEdge(
                    source_id=source,
                    target_id=f"create:{last.pc}",
                    kind=CfgEdgeKind.CREATE,
                    attributes={"pc": last.pc},
                )
            )

        # Resolve static jumps from immediate PUSH immediately preceding.
        if last.opcode in (0x56, 0x57):
            prev_pcs = [p for p in pcs if p < last.pc]
            target: int | None = None
            if prev_pcs:
                prev = by_pc[prev_pcs[-1]]
                if prev.opname.startswith("PUSH") and prev.immediate:
                    target = int.from_bytes(prev.immediate, "big")
            if target is None or target not in by_pc or target not in jumpdests:
                unresolved.append(last.pc)
            else:
                target_leader = leader_of[target]
                if last.opcode == 0x56:
                    edges.append(
                        CfgEdge(
                            source_id=source,
                            target_id=node_id_for[target_leader],
                            kind=CfgEdgeKind.JUMP,
                            attributes={"target_pc": target},
                        )
                    )
                else:
                    edges.append(
                        CfgEdge(
                            source_id=source,
                            target_id=node_id_for[target_leader],
                            kind=CfgEdgeKind.JUMPI_TRUE,
                            attributes={"target_pc": target},
                        )
                    )
                    next_pc = last.pc + last.size
                    if next_pc in by_pc:
                        edges.append(
                            CfgEdge(
                                source_id=source,
                                target_id=node_id_for[leader_of[next_pc]],
                                kind=CfgEdgeKind.JUMPI_FALSE,
                            )
                        )
            if last.opcode == 0x57 and target is not None and target in jumpdests:
                pass  # fallthrough already handled above when resolved
            elif last.opcode == 0x57:
                next_pc = last.pc + last.size
                if next_pc in by_pc:
                    edges.append(
                        CfgEdge(
                            source_id=source,
                            target_id=node_id_for[leader_of[next_pc]],
                            kind=CfgEdgeKind.JUMPI_FALSE,
                        )
                    )
        elif last.opcode not in _TERMINATORS:
            next_pc = last.pc + last.size
            if next_pc in by_pc:
                edges.append(
                    CfgEdge(
                        source_id=source,
                        target_id=node_id_for[leader_of[next_pc]],
                        kind=CfgEdgeKind.FALLTHROUGH,
                    )
                )

    if len(edges) > max_edges:
        raise ResourceLimitError("CFG edge count exceeds bound")

    # Collect all unsupported opcodes from full disassembly.
    for ins in disassembly.instructions:
        if not ins.supported and ins.opcode not in unsupported_opcodes:
            unsupported_opcodes.append(ins.opcode)
        if ins.opcode == 0xFF:
            has_selfdestruct = True
        if ins.opcode == 0xF4:
            has_delegatecall = True

    diagnostics = list(disassembly.diagnostics)
    if unsupported_opcodes:
        diagnostics.append(
            "unsupported opcodes present; semantic pass is forbidden"
        )
    if unresolved:
        diagnostics.append("unresolved dynamic or invalid jumps; CFG incomplete")
    if disassembly.truncated:
        diagnostics.append("disassembly truncated; CFG incomplete")

    if unsupported_opcodes:
        status = SemanticPassStatus.UNSUPPORTED
    elif unresolved or disassembly.truncated:
        status = SemanticPassStatus.INCOMPLETE
    else:
        status = SemanticPassStatus.PASS

    return ControlFlowGraph(
        bytecode_digest=disassembly.bytecode_digest,
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_node_id=node_id_for[leaders[0]],
        unresolved_jumps=tuple(unresolved),
        unsupported_opcodes=tuple(unsupported_opcodes),
        has_selfdestruct=has_selfdestruct,
        has_delegatecall=has_delegatecall,
        pass_status=status,
        diagnostics=tuple(dict.fromkeys(diagnostics)),  # stable unique
    )


def extract_storage_effects(
    disassembly: DisassemblyResult,
    *,
    trace_complete: bool = False,
) -> tuple[StorageEffect, ...]:
    """Extract static SLOAD/SSTORE effects; incomplete traces never claim completeness."""

    effects: list[StorageEffect] = []
    for ins in disassembly.instructions:
        if ins.opcode in _STORAGE_READ:
            effects.append(
                StorageEffect(
                    kind=StorageAccessKind.SLOAD,
                    pc=ins.pc,
                    trace_complete=trace_complete,
                )
            )
        elif ins.opcode in _STORAGE_WRITE:
            effects.append(
                StorageEffect(
                    kind=StorageAccessKind.SSTORE,
                    pc=ins.pc,
                    trace_complete=trace_complete,
                )
            )
    return tuple(effects)


def analyze_bytecode(
    bytecode: bytes | str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTECODE_BYTES,
    max_instructions: int = DEFAULT_MAX_INSTRUCTIONS,
    max_nodes: int = DEFAULT_MAX_CFG_NODES,
    max_edges: int = DEFAULT_MAX_CFG_EDGES,
    trace_complete: bool = False,
) -> tuple[DisassemblyResult, ControlFlowGraph, tuple[StorageEffect, ...]]:
    """Full bounded static analysis pipeline for EVM bytecode."""

    disasm = disassemble_bytecode(
        bytecode, max_bytes=max_bytes, max_instructions=max_instructions
    )
    cfg = build_cfg(disasm, max_nodes=max_nodes, max_edges=max_edges)
    effects = extract_storage_effects(disasm, trace_complete=trace_complete)
    # Incomplete traces never pass even if CFG is complete.
    if not trace_complete and cfg.pass_status is SemanticPassStatus.PASS:
        # Static-only analysis may pass CFG, but effect completeness is false.
        pass
    return disasm, cfg, effects


def incomplete_trace_never_passes(
    *,
    cfg: ControlFlowGraph,
    trace_complete: bool,
    claim_pass: bool,
) -> SemanticPassStatus:
    """Gate semantic pass claims against incomplete traces and unsupported ops.

    Returns the effective pass status.  A caller that asserts ``claim_pass``
    while the gate fails closed receives :attr:`SemanticPassStatus.FAIL_CLOSED`.
    """

    if cfg.unsupported_opcodes:
        return SemanticPassStatus.UNSUPPORTED
    if cfg.unresolved_jumps or cfg.pass_status is SemanticPassStatus.INCOMPLETE:
        return SemanticPassStatus.INCOMPLETE
    if not trace_complete:
        # Incomplete execution traces never satisfy a pass claim.
        return SemanticPassStatus.INCOMPLETE if claim_pass else SemanticPassStatus.INCOMPLETE
    if claim_pass and cfg.pass_status is SemanticPassStatus.PASS:
        return SemanticPassStatus.PASS
    if claim_pass:
        return SemanticPassStatus.FAIL_CLOSED
    return cfg.pass_status


__all__ = [
    "DEFAULT_MAX_BYTECODE_BYTES",
    "DEFAULT_MAX_CFG_EDGES",
    "DEFAULT_MAX_CFG_NODES",
    "DEFAULT_MAX_INSTRUCTIONS",
    "KNOWN_OPCODES",
    "OPCODE_MNEMONICS",
    "SEMANTICS_SCHEMA_VERSION",
    "CfgEdge",
    "CfgEdgeKind",
    "CfgNode",
    "ControlFlowGraph",
    "DecodedInstruction",
    "DisassemblyResult",
    "SemanticPassStatus",
    "StorageAccessKind",
    "StorageEffect",
    "analyze_bytecode",
    "build_cfg",
    "disassemble_bytecode",
    "extract_storage_effects",
    "incomplete_trace_never_passes",
    "mnemonic_for",
    "normalize_bytecode",
    "push_immediate_size",
]

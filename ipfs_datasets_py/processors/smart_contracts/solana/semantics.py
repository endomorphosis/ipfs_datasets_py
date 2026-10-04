"""Solana program semantics: privileges, owners, PDA, CPI (CRYPTOIR-G230).

Signer/writable privileges and account owners are first-class semantic
fields — never collapsed into generic call metadata.  CPI edges, inner
instructions, PDA seed constraints, and coverage remain explicit and
fail closed when incomplete.

Importing this module performs no network I/O.
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
from .loader import decode_base58, encode_base58, normalize_pubkey


SEMANTICS_SCHEMA_VERSION = "smart-contract-solana-semantics-v1"
DEFAULT_MAX_ELF_BYTES = 10 * 1024 * 1024  # 10 MiB bound for offline fixtures
DEFAULT_MAX_INSTRUCTIONS = 4_096
DEFAULT_MAX_CPI_EDGES = 16_384
DEFAULT_MAX_ACCOUNTS = 256
ELF_MAGIC = b"\x7fELF"


class SemanticPassStatus(StrEnum):
    """Outcome of a semantic coverage claim."""

    PASS = "pass"
    FAIL_CLOSED = "fail_closed"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class AccountKeySource(StrEnum):
    """Where a resolved account key originated."""

    STATIC = "static"
    LOOKUP_WRITABLE = "lookup_writable"
    LOOKUP_READONLY = "lookup_readonly"
    DERIVED_PDA = "derived_pda"
    UNKNOWN = "unknown"


class CPIEdgeKind(StrEnum):
    """Cross-program invocation edge classification."""

    OUTER = "outer"
    INNER = "inner"
    INVOKE = "invoke"
    INVOKE_SIGNED = "invoke_signed"
    UNKNOWN = "unknown"


class OwnerCheckStatus(StrEnum):
    """Whether an account owner was verified against an expected program."""

    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNCHECKED = "unchecked"
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


def normalize_elf_bytes(value: bytes | str) -> bytes:
    """Normalize SBF/ELF program bytes from raw or hex."""

    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith(("0x", "0X")):
            text = text[2:]
        if not text:
            return b""
        try:
            data = bytes.fromhex(text)
        except ValueError as exc:
            raise InvalidRequestError("ELF bytes must be valid hex") from exc
    else:
        raise InvalidRequestError("ELF payload must be bytes or hex string")
    return data


def assert_elf_magic(data: bytes, *, allow_empty: bool = False) -> None:
    """Fail closed when declared SBF ELF lacks the ELF magic header."""

    if not data:
        if allow_empty:
            return
        raise InvalidRequestError("SBF ELF bytes must not be empty")
    if len(data) < 4 or data[:4] != ELF_MAGIC:
        raise InvalidRequestError("SBF program bytes must begin with ELF magic")


@dataclass(frozen=True, slots=True)
class AccountPrivilege:
    """Per-account signer/writable privilege bits in account-list order.

    Privilege bits are first-class instruction semantics: they authorize
    mutation and signing and must not be treated as presentation metadata.
    """

    account_index: int
    pubkey: str
    is_signer: bool
    is_writable: bool
    owner: str = ""
    source: str = AccountKeySource.STATIC.value
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_index",
            _non_negative(self.account_index, "account_index"),
        )
        object.__setattr__(self, "pubkey", normalize_pubkey(self.pubkey, field="pubkey"))
        object.__setattr__(self, "is_signer", _bool(self.is_signer, "is_signer"))
        object.__setattr__(self, "is_writable", _bool(self.is_writable, "is_writable"))
        if self.owner:
            object.__setattr__(
                self, "owner", normalize_pubkey(self.owner, field="owner")
            )
        else:
            object.__setattr__(self, "owner", "")
        source = _required_text(str(self.source), "source")
        try:
            AccountKeySource(source)
        except ValueError as exc:
            raise InvalidRequestError(f"unsupported account key source: {source!r}") from exc
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_index": self.account_index,
            "attributes": thaw_json(self.attributes),
            "is_signer": self.is_signer,
            "is_writable": self.is_writable,
            "owner": self.owner,
            "pubkey": self.pubkey,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AccountPrivilege":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("AccountPrivilege must be a mapping")
        return cls(
            account_index=int(value.get("account_index", 0)),
            pubkey=str(value.get("pubkey", value.get("address", ""))),
            is_signer=bool(value.get("is_signer", value.get("signer", False))),
            is_writable=bool(value.get("is_writable", value.get("writable", False))),
            owner=str(value.get("owner", "")),
            source=str(value.get("source", AccountKeySource.STATIC.value)),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class OwnerCheck:
    """Explicit account-owner verification result."""

    account_pubkey: str
    expected_owner: str
    observed_owner: str = ""
    status: OwnerCheckStatus = OwnerCheckStatus.UNCHECKED
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_pubkey",
            normalize_pubkey(self.account_pubkey, field="account_pubkey"),
        )
        object.__setattr__(
            self,
            "expected_owner",
            normalize_pubkey(self.expected_owner, field="expected_owner"),
        )
        if self.observed_owner:
            object.__setattr__(
                self,
                "observed_owner",
                normalize_pubkey(self.observed_owner, field="observed_owner"),
            )
        else:
            object.__setattr__(self, "observed_owner", "")
        status = (
            self.status
            if isinstance(self.status, OwnerCheckStatus)
            else OwnerCheckStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        if status is OwnerCheckStatus.UNKNOWN and not self.diagnostics:
            raise InvalidRequestError("UNKNOWN owner check requires diagnostics")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_pubkey": self.account_pubkey,
            "diagnostics": list(self.diagnostics),
            "expected_owner": self.expected_owner,
            "observed_owner": self.observed_owner,
            "status": self.status.value
            if isinstance(self.status, OwnerCheckStatus)
            else str(self.status),
        }


def check_account_owner(
    *,
    account_pubkey: str,
    expected_owner: str,
    observed_owner: str | None = None,
) -> OwnerCheck:
    """Compare observed owner against expected program id."""

    if observed_owner is None:
        return OwnerCheck(
            account_pubkey=account_pubkey,
            expected_owner=expected_owner,
            status=OwnerCheckStatus.UNKNOWN,
            diagnostics=("observed owner not supplied",),
        )
    if not observed_owner:
        return OwnerCheck(
            account_pubkey=account_pubkey,
            expected_owner=expected_owner,
            observed_owner="",
            status=OwnerCheckStatus.UNCHECKED,
            diagnostics=("observed owner empty; owner check not performed",),
        )
    expected = normalize_pubkey(expected_owner, field="expected_owner")
    observed = normalize_pubkey(observed_owner, field="observed_owner")
    if expected == observed:
        return OwnerCheck(
            account_pubkey=account_pubkey,
            expected_owner=expected,
            observed_owner=observed,
            status=OwnerCheckStatus.MATCHED,
        )
    return OwnerCheck(
        account_pubkey=account_pubkey,
        expected_owner=expected,
        observed_owner=observed,
        status=OwnerCheckStatus.MISMATCH,
        diagnostics=(
            f"owner mismatch: expected {expected}, observed {observed}",
        ),
    )


@dataclass(frozen=True, slots=True)
class PDAConstraint:
    """Program-derived address seed constraint.

    Seeds and program id are semantic binding material.  A bump of ``None``
    means the bump was not observed (coverage incomplete), not that zero is
    implied.
    """

    program_id: str
    seeds: tuple[bytes, ...]
    derived_address: str = ""
    bump: int | None = None
    is_on_curve: bool | None = None
    verified: bool = False
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "program_id", normalize_pubkey(self.program_id, field="program_id")
        )
        if isinstance(self.seeds, (str, bytes, bytearray)) or not isinstance(
            self.seeds, Sequence
        ):
            raise InvalidRequestError("seeds must be a sequence of bytes")
        seeds: list[bytes] = []
        for index, seed in enumerate(self.seeds):
            if type(seed) is not bytes:
                raise InvalidRequestError(f"seeds[{index}] must be exact bytes")
            if len(seed) > 32:
                raise InvalidRequestError(
                    f"seeds[{index}] exceeds Solana max seed length of 32 bytes"
                )
            seeds.append(seed)
        if len(seeds) > 16:
            raise ResourceLimitError("PDA seed count exceeds Solana maximum of 16")
        object.__setattr__(self, "seeds", tuple(seeds))
        if self.derived_address:
            object.__setattr__(
                self,
                "derived_address",
                normalize_pubkey(self.derived_address, field="derived_address"),
            )
        else:
            object.__setattr__(self, "derived_address", "")
        if self.bump is not None:
            if isinstance(self.bump, bool) or not isinstance(self.bump, int):
                raise InvalidRequestError("bump must be an integer 0-255 or None")
            if self.bump < 0 or self.bump > 255:
                raise InvalidRequestError("bump must be in range 0-255")
        if self.is_on_curve is not None and not isinstance(self.is_on_curve, bool):
            raise InvalidRequestError("is_on_curve must be a bool or None")
        object.__setattr__(self, "verified", _bool(self.verified, "verified"))
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if self.verified and not self.derived_address:
            raise InvalidRequestError(
                "verified PDA constraint requires derived_address"
            )
        ensure_secret_safe(self.to_dict())

    @property
    def seeds_digest(self) -> str:
        # Deterministic multi-seed digest: length-prefixed concatenation.
        payload = b""
        for seed in self.seeds:
            payload += len(seed).to_bytes(2, "big") + seed
        return bytes_digest(payload) if payload else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "bump": self.bump,
            "derived_address": self.derived_address,
            "diagnostics": list(self.diagnostics),
            "is_on_curve": self.is_on_curve,
            "program_id": self.program_id,
            "schema_version": self.schema_version,
            "seeds_digest": self.seeds_digest,
            "seeds_hex": [seed.hex() for seed in self.seeds],
            "verified": self.verified,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def bind_pda_constraint(
    *,
    program_id: str,
    seeds: Sequence[bytes],
    derived_address: str = "",
    bump: int | None = None,
    verified: bool = False,
    is_on_curve: bool | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> PDAConstraint:
    """Construct a PDA seed constraint; verification remains explicit."""

    diagnostics: list[str] = []
    if verified and not derived_address:
        raise InvalidRequestError("cannot mark PDA verified without derived_address")
    if not derived_address:
        diagnostics.append("derived address not supplied; PDA binding incomplete")
    if bump is None:
        diagnostics.append("bump not observed; coverage incomplete for PDA derivation")
    return PDAConstraint(
        program_id=program_id,
        seeds=tuple(seeds),
        derived_address=derived_address,
        bump=bump,
        is_on_curve=is_on_curve,
        verified=verified,
        diagnostics=tuple(diagnostics),
        attributes=dict(attributes or {}),
    )


@dataclass(frozen=True, slots=True)
class CPIEdge:
    """One cross-program invocation edge (outer or inner instruction).

    Privilege indexes reference the resolved account list.  Owners and
    privilege bits live on the edge as first-class fields, not nested call
    metadata blobs.
    """

    caller_program_id: str
    callee_program_id: str
    kind: CPIEdgeKind = CPIEdgeKind.INVOKE
    outer_index: int = 0
    inner_index: int | None = None
    stack_height: int | None = None
    account_indexes: tuple[int, ...] = ()
    account_privileges: tuple[AccountPrivilege, ...] = ()
    data_digest: str = ""
    owner_checks: tuple[OwnerCheck, ...] = ()
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "caller_program_id",
            normalize_pubkey(self.caller_program_id, field="caller_program_id"),
        )
        object.__setattr__(
            self,
            "callee_program_id",
            normalize_pubkey(self.callee_program_id, field="callee_program_id"),
        )
        kind = (
            self.kind
            if isinstance(self.kind, CPIEdgeKind)
            else CPIEdgeKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "outer_index", _non_negative(self.outer_index, "outer_index")
        )
        if self.inner_index is not None:
            object.__setattr__(
                self, "inner_index", _non_negative(self.inner_index, "inner_index")
            )
        if self.stack_height is not None:
            object.__setattr__(
                self,
                "stack_height",
                _non_negative(self.stack_height, "stack_height"),
            )
        if isinstance(self.account_indexes, (str, bytes, bytearray)) or not isinstance(
            self.account_indexes, Sequence
        ):
            raise InvalidRequestError("account_indexes must be a sequence of integers")
        indexes = tuple(
            _non_negative(item, "account_index") for item in self.account_indexes
        )
        object.__setattr__(self, "account_indexes", indexes)
        privileges = tuple(self.account_privileges)
        for index, priv in enumerate(privileges):
            if not isinstance(priv, AccountPrivilege):
                raise InvalidRequestError(
                    f"account_privileges[{index}] must be an AccountPrivilege"
                )
        object.__setattr__(self, "account_privileges", privileges)
        if self.data_digest:
            digest = _required_text(self.data_digest, "data_digest")
            if not digest.startswith("sha256:"):
                raise InvalidRequestError("data_digest must be a tagged sha256 digest")
            object.__setattr__(self, "data_digest", digest)
        else:
            object.__setattr__(self, "data_digest", "")
        checks = tuple(self.owner_checks)
        for index, check in enumerate(checks):
            if not isinstance(check, OwnerCheck):
                raise InvalidRequestError(
                    f"owner_checks[{index}] must be an OwnerCheck"
                )
        object.__setattr__(self, "owner_checks", checks)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def is_inner(self) -> bool:
        return self.inner_index is not None or self.kind is CPIEdgeKind.INNER

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_indexes": list(self.account_indexes),
            "account_privileges": [item.to_dict() for item in self.account_privileges],
            "attributes": thaw_json(self.attributes),
            "callee_program_id": self.callee_program_id,
            "caller_program_id": self.caller_program_id,
            "data_digest": self.data_digest,
            "diagnostics": list(self.diagnostics),
            "inner_index": self.inner_index,
            "kind": self.kind.value if isinstance(self.kind, CPIEdgeKind) else str(self.kind),
            "outer_index": self.outer_index,
            "owner_checks": [item.to_dict() for item in self.owner_checks],
            "schema_version": self.schema_version,
            "stack_height": self.stack_height,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class CPIGraph:
    """Directed CPI graph with explicit coverage for inner instructions."""

    program_id: str
    edges: tuple[CPIEdge, ...]
    privileges: tuple[AccountPrivilege, ...] = ()
    pda_constraints: tuple[PDAConstraint, ...] = ()
    owner_checks: tuple[OwnerCheck, ...] = ()
    inner_instruction_coverage: bool = False
    coverage_notes: tuple[str, ...] = ()
    pass_status: SemanticPassStatus = SemanticPassStatus.INCOMPLETE
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "program_id", normalize_pubkey(self.program_id, field="program_id")
        )
        edges = tuple(self.edges)
        if len(edges) > DEFAULT_MAX_CPI_EDGES:
            raise ResourceLimitError("CPI edge count exceeds DEFAULT_MAX_CPI_EDGES")
        for index, edge in enumerate(edges):
            if not isinstance(edge, CPIEdge):
                raise InvalidRequestError(f"edges[{index}] must be a CPIEdge")
        object.__setattr__(self, "edges", edges)
        privileges = tuple(self.privileges)
        for index, priv in enumerate(privileges):
            if not isinstance(priv, AccountPrivilege):
                raise InvalidRequestError(
                    f"privileges[{index}] must be an AccountPrivilege"
                )
        object.__setattr__(self, "privileges", privileges)
        pdas = tuple(self.pda_constraints)
        for index, pda in enumerate(pdas):
            if not isinstance(pda, PDAConstraint):
                raise InvalidRequestError(
                    f"pda_constraints[{index}] must be a PDAConstraint"
                )
        object.__setattr__(self, "pda_constraints", pdas)
        checks = tuple(self.owner_checks)
        for index, check in enumerate(checks):
            if not isinstance(check, OwnerCheck):
                raise InvalidRequestError(
                    f"owner_checks[{index}] must be an OwnerCheck"
                )
        object.__setattr__(self, "owner_checks", checks)
        object.__setattr__(
            self,
            "inner_instruction_coverage",
            _bool(self.inner_instruction_coverage, "inner_instruction_coverage"),
        )
        object.__setattr__(
            self,
            "coverage_notes",
            tuple(
                _required_text(item, "coverage note") for item in self.coverage_notes
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
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Fail closed: PASS requires complete inner coverage and no UNKNOWN.
        if status is SemanticPassStatus.PASS:
            if not self.inner_instruction_coverage:
                raise InvalidRequestError(
                    "semantic pass forbidden without inner instruction coverage"
                )
            if any(
                check.status is OwnerCheckStatus.UNKNOWN for check in self.owner_checks
            ):
                raise InvalidRequestError(
                    "semantic pass forbidden with UNKNOWN owner checks"
                )
            if any(edge.kind is CPIEdgeKind.UNKNOWN for edge in self.edges):
                raise InvalidRequestError(
                    "semantic pass forbidden with UNKNOWN CPI edges"
                )
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.pass_status is SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "coverage_notes": list(self.coverage_notes),
            "diagnostics": list(self.diagnostics),
            "edges": [item.to_dict() for item in self.edges],
            "inner_instruction_coverage": self.inner_instruction_coverage,
            "owner_checks": [item.to_dict() for item in self.owner_checks],
            "pass_status": self.pass_status.value
            if isinstance(self.pass_status, SemanticPassStatus)
            else str(self.pass_status),
            "pda_constraints": [item.to_dict() for item in self.pda_constraints],
            "privileges": [item.to_dict() for item in self.privileges],
            "program_id": self.program_id,
            "schema_version": self.schema_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def build_cpi_graph(
    *,
    program_id: str,
    edges: Sequence[CPIEdge] = (),
    privileges: Sequence[AccountPrivilege] = (),
    pda_constraints: Sequence[PDAConstraint] = (),
    owner_checks: Sequence[OwnerCheck] = (),
    inner_instruction_coverage: bool = False,
    claim_pass: bool = False,
    attributes: Mapping[str, Any] | None = None,
) -> CPIGraph:
    """Assemble a CPI graph with explicit fail-closed coverage policy."""

    edge_list = tuple(edges)
    priv_list = tuple(privileges)
    pda_list = tuple(pda_constraints)
    check_list = tuple(owner_checks)
    diagnostics: list[str] = []
    coverage_notes: list[str] = []

    if not inner_instruction_coverage:
        coverage_notes.append("inner instruction coverage incomplete")
        diagnostics.append(
            "inner instructions not fully covered; CPI graph remains incomplete"
        )
    else:
        coverage_notes.append("inner instruction coverage complete")

    if any(check.status is OwnerCheckStatus.MISMATCH for check in check_list):
        diagnostics.append("one or more owner checks mismatched")
    if any(check.status is OwnerCheckStatus.UNKNOWN for check in check_list):
        diagnostics.append("one or more owner checks unknown")
    if any(edge.kind is CPIEdgeKind.UNKNOWN for edge in edge_list):
        diagnostics.append("one or more CPI edges have unknown kind")

    # Privileges are semantic: surface signers/writables in coverage notes.
    signer_count = sum(1 for p in priv_list if p.is_signer)
    writable_count = sum(1 for p in priv_list if p.is_writable)
    coverage_notes.append(
        f"privileges: {len(priv_list)} accounts, "
        f"{signer_count} signers, {writable_count} writable"
    )
    if any(not p.owner for p in priv_list):
        coverage_notes.append("some account owners unbound on privilege records")

    if claim_pass:
        if (
            inner_instruction_coverage
            and not any(c.status is OwnerCheckStatus.UNKNOWN for c in check_list)
            and not any(e.kind is CPIEdgeKind.UNKNOWN for e in edge_list)
            and not any(c.status is OwnerCheckStatus.MISMATCH for c in check_list)
        ):
            status = SemanticPassStatus.PASS
        elif any(e.kind is CPIEdgeKind.UNKNOWN for e in edge_list):
            status = SemanticPassStatus.UNSUPPORTED
            diagnostics.append("pass claim rejected: unknown CPI edges")
        elif not inner_instruction_coverage:
            status = SemanticPassStatus.INCOMPLETE
            diagnostics.append("pass claim rejected: incomplete inner coverage")
        else:
            status = SemanticPassStatus.FAIL_CLOSED
            diagnostics.append("pass claim rejected by fail-closed owner/CPI gate")
    else:
        status = SemanticPassStatus.INCOMPLETE
        if not edge_list and not priv_list:
            status = SemanticPassStatus.UNKNOWN
            diagnostics.append("no CPI edges or privileges supplied")

    return CPIGraph(
        program_id=program_id,
        edges=edge_list,
        privileges=priv_list,
        pda_constraints=pda_list,
        owner_checks=check_list,
        inner_instruction_coverage=inner_instruction_coverage,
        coverage_notes=tuple(coverage_notes),
        pass_status=status,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        attributes=dict(attributes or {}),
    )


def incomplete_coverage_never_passes(
    *,
    graph: CPIGraph,
    claim_pass: bool,
) -> SemanticPassStatus:
    """Guard: incomplete inner coverage or unknown edges never elevate to PASS."""

    if not claim_pass:
        if graph.pass_status is SemanticPassStatus.PASS:
            return SemanticPassStatus.INCOMPLETE
        return graph.pass_status
    if not graph.inner_instruction_coverage:
        return SemanticPassStatus.INCOMPLETE
    if any(edge.kind is CPIEdgeKind.UNKNOWN for edge in graph.edges):
        return SemanticPassStatus.UNSUPPORTED
    if any(check.status is OwnerCheckStatus.UNKNOWN for check in graph.owner_checks):
        return SemanticPassStatus.INCOMPLETE
    if any(check.status is OwnerCheckStatus.MISMATCH for check in graph.owner_checks):
        return SemanticPassStatus.FAIL_CLOSED
    return SemanticPassStatus.PASS


__all__ = [
    "DEFAULT_MAX_ACCOUNTS",
    "DEFAULT_MAX_CPI_EDGES",
    "DEFAULT_MAX_ELF_BYTES",
    "DEFAULT_MAX_INSTRUCTIONS",
    "ELF_MAGIC",
    "SEMANTICS_SCHEMA_VERSION",
    "AccountKeySource",
    "AccountPrivilege",
    "CPIEdge",
    "CPIEdgeKind",
    "CPIGraph",
    "OwnerCheck",
    "OwnerCheckStatus",
    "PDAConstraint",
    "SemanticPassStatus",
    "assert_elf_magic",
    "bind_pda_constraint",
    "build_cpi_graph",
    "check_account_owner",
    "decode_base58",
    "encode_base58",
    "incomplete_coverage_never_passes",
    "normalize_elf_bytes",
    "normalize_pubkey",
]

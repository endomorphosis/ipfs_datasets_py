"""Miniscript policies and output descriptors (CRYPTOIR-G250).

Descriptor/miniscript policy equality is **proven** only when both sides
normalize to identical policy trees; otherwise equality is explicitly
``unknown`` or ``unequal``.  This module models spending policies offline —
it is not a full miniscript compiler/type-checker.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError, ResourceLimitError
from ..models import ensure_secret_safe


MINISCRIPT_SCHEMA_VERSION = "smart-contract-bitcoin-miniscript-v1"
DEFAULT_MAX_POLICY_CHARS = 8_192
DEFAULT_MAX_TREE_NODES = 512
DEFAULT_MAX_KEYS = 100

_KEY_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:@+\-]+$")


class PolicyNodeKind(StrEnum):
    """Normalized miniscript / policy fragment kinds."""

    PK = "pk"
    PKH = "pkh"
    MULTI = "multi"
    THRESH = "thresh"
    OLDER = "older"
    AFTER = "after"
    SHA256 = "sha256"
    HASH256 = "hash256"
    RIPEMD160 = "ripemd160"
    HASH160 = "hash160"
    AND = "and"
    OR = "or"
    ANDOR = "andor"
    WRAP_A = "a"  # a:
    WRAP_S = "s"  # s:
    WRAP_C = "c"  # c:
    WRAP_D = "d"  # d:
    WRAP_V = "v"  # v:
    WRAP_J = "j"  # j:
    WRAP_N = "n"  # n:
    WRAP_T = "t"  # t:
    WRAP_L = "l"  # l:
    WRAP_U = "u"  # u:
    TRUE = "1"
    FALSE = "0"
    UNKNOWN = "unknown"


class PolicyEquivalenceStatus(StrEnum):
    """Whether two policies are proven equal, unequal, or unknown."""

    PROVEN_EQUAL = "proven_equal"
    PROVEN_UNEQUAL = "proven_unequal"
    UNKNOWN = "unknown"
    INCOMPARABLE = "incomparable"


class DescriptorType(StrEnum):
    """Output descriptor family."""

    PK = "pk"
    PKH = "pkh"
    WPKH = "wpkh"
    SH = "sh"
    WSH = "wsh"
    TR = "tr"
    MULTI = "multi"
    SORTED_MULTI = "sortedmulti"
    RAW = "raw"
    ADDR = "addr"
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


def _optional_digest(value: str, name: str) -> str:
    if not value:
        return ""
    text = _required_text(value, name)
    if not text.startswith("sha256:"):
        raise InvalidRequestError(f"{name} must be a tagged sha256 digest")
    return text


@dataclass(frozen=True, slots=True)
class PolicyNode:
    """One node in a normalized policy tree."""

    kind: PolicyNodeKind
    args: tuple[str, ...] = ()
    children: tuple["PolicyNode", ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, PolicyNodeKind)
            else PolicyNodeKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "args",
            tuple(_required_text(a, "args item") if a else "" for a in self.args),
        )
        # Allow empty string args only for placeholders — filter none that are
        # whitespace-only improperly already handled.
        children = tuple(self.children)
        for index, child in enumerate(children):
            if not isinstance(child, PolicyNode):
                raise InvalidRequestError(f"children[{index}] must be a PolicyNode")
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "args": list(self.args),
            "attributes": thaw_json(self.attributes),
            "children": [c.to_dict() for c in self.children],
            "kind": self.kind.value,
        }

    def canonical_form(self) -> str:
        """Deterministic string form for equality proofs."""

        if self.kind in {
            PolicyNodeKind.PK,
            PolicyNodeKind.PKH,
            PolicyNodeKind.SHA256,
            PolicyNodeKind.HASH256,
            PolicyNodeKind.RIPEMD160,
            PolicyNodeKind.HASH160,
            PolicyNodeKind.OLDER,
            PolicyNodeKind.AFTER,
        }:
            arg = self.args[0] if self.args else ""
            return f"{self.kind.value}({arg})"
        if self.kind is PolicyNodeKind.MULTI:
            k = self.args[0] if self.args else "0"
            keys = ",".join(self.args[1:])
            return f"multi({k},{keys})"
        if self.kind is PolicyNodeKind.THRESH:
            k = self.args[0] if self.args else "0"
            parts = ",".join(c.canonical_form() for c in self.children)
            return f"thresh({k},{parts})"
        if self.kind in {PolicyNodeKind.AND, PolicyNodeKind.OR}:
            parts = ",".join(c.canonical_form() for c in self.children)
            return f"{self.kind.value}({parts})"
        if self.kind is PolicyNodeKind.ANDOR:
            parts = ",".join(c.canonical_form() for c in self.children)
            return f"andor({parts})"
        if self.kind is PolicyNodeKind.TRUE:
            return "1"
        if self.kind is PolicyNodeKind.FALSE:
            return "0"
        if self.kind.value in {"a", "s", "c", "d", "v", "j", "n", "t", "l", "u"}:
            inner = self.children[0].canonical_form() if self.children else ""
            return f"{self.kind.value}:{inner}"
        if self.args:
            return f"{self.kind.value}({','.join(self.args)})"
        return self.kind.value


@dataclass(frozen=True, slots=True)
class MiniscriptPolicy:
    """Normalized Miniscript / spending-policy tree with key set and bounds.

    Policy equality against another policy is proven only via identical
    canonical forms; otherwise the status is explicitly unknown or unequal.
    """

    expression: str
    root: PolicyNode
    canonical: str
    policy_digest: str
    keys: tuple[str, ...]
    thresholds: tuple[tuple[int, int], ...]  # (k, n) pairs
    has_timelock: bool
    has_hashlock: bool
    fully_parsed: bool
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MINISCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "expression", _required_text(self.expression, "expression")
        )
        if not isinstance(self.root, PolicyNode):
            raise InvalidRequestError("root must be a PolicyNode")
        object.__setattr__(
            self, "canonical", _required_text(self.canonical, "canonical")
        )
        object.__setattr__(
            self,
            "policy_digest",
            _optional_digest(self.policy_digest, "policy_digest")
            if self.policy_digest
            else bytes_digest(self.canonical.encode("utf-8")),
        )
        keys = tuple(_required_text(k, "keys item") for k in self.keys)
        object.__setattr__(self, "keys", keys)
        thresholds = tuple(
            (int(k), int(n)) for k, n in self.thresholds
        )
        for index, (k, n) in enumerate(thresholds):
            if k < 0 or n < 0 or k > n:
                raise InvalidRequestError(
                    f"thresholds[{index}] must satisfy 0 <= k <= n"
                )
        object.__setattr__(self, "thresholds", thresholds)
        object.__setattr__(self, "has_timelock", _bool(self.has_timelock, "has_timelock"))
        object.__setattr__(self, "has_hashlock", _bool(self.has_hashlock, "has_hashlock"))
        object.__setattr__(
            self, "fully_parsed", _bool(self.fully_parsed, "fully_parsed")
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "canonical": self.canonical,
            "expression": self.expression,
            "fully_parsed": self.fully_parsed,
            "has_hashlock": self.has_hashlock,
            "has_timelock": self.has_timelock,
            "keys": list(self.keys),
            "policy_digest": self.policy_digest,
            "root": self.root.to_dict(),
            "schema_version": self.schema_version,
            "thresholds": [[k, n] for k, n in self.thresholds],
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    def equivalence(self, other: "MiniscriptPolicy") -> PolicyEquivalenceStatus:
        """Prove equality only when both fully parse to the same canonical form."""

        if not isinstance(other, MiniscriptPolicy):
            raise InvalidRequestError("other must be a MiniscriptPolicy")
        if not self.fully_parsed or not other.fully_parsed:
            return PolicyEquivalenceStatus.UNKNOWN
        if self.canonical == other.canonical:
            return PolicyEquivalenceStatus.PROVEN_EQUAL
        return PolicyEquivalenceStatus.PROVEN_UNEQUAL


@dataclass(frozen=True, slots=True)
class OutputDescriptor:
    """Output descriptor with optional miniscript body and checksum field.

    Checksum presence is recorded; validation of the BIP-380 checksum alphabet
    is optional offline evidence (not silently trusted as correctness).
    """

    descriptor: str
    descriptor_type: DescriptorType
    body: str
    checksum: str = ""
    checksum_present: bool = False
    miniscript: MiniscriptPolicy | None = None
    multipath: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MINISCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "descriptor", _required_text(self.descriptor, "descriptor")
        )
        dtype = (
            self.descriptor_type
            if isinstance(self.descriptor_type, DescriptorType)
            else DescriptorType(str(self.descriptor_type))
        )
        object.__setattr__(self, "descriptor_type", dtype)
        object.__setattr__(self, "body", self.body.strip() if self.body else "")
        object.__setattr__(
            self, "checksum", self.checksum.strip() if self.checksum else ""
        )
        object.__setattr__(
            self, "checksum_present", _bool(self.checksum_present, "checksum_present")
        )
        if self.miniscript is not None and not isinstance(
            self.miniscript, MiniscriptPolicy
        ):
            raise InvalidRequestError("miniscript must be a MiniscriptPolicy or None")
        object.__setattr__(self, "multipath", _bool(self.multipath, "multipath"))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "body": self.body,
            "checksum": self.checksum,
            "checksum_present": self.checksum_present,
            "descriptor": self.descriptor,
            "descriptor_type": self.descriptor_type.value,
            "miniscript": self.miniscript.to_dict() if self.miniscript else None,
            "multipath": self.multipath,
            "schema_version": self.schema_version,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


def _split_top_level_args(body: str) -> list[str]:
    """Split comma-separated args respecting nested parentheses."""

    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise InvalidRequestError("unbalanced parentheses in policy")
        elif ch == "," and depth == 0:
            parts.append(body[start:i].strip())
            start = i + 1
    parts.append(body[start:].strip())
    return [p for p in parts if p != "" or len(parts) == 1]


def _parse_policy_expr(
    expr: str,
    *,
    max_nodes: int,
    counter: list[int],
) -> PolicyNode:
    expr = expr.strip()
    if not expr:
        raise InvalidRequestError("empty policy expression")
    counter[0] += 1
    if counter[0] > max_nodes:
        raise ResourceLimitError("policy tree exceeds max_nodes")

    # Wrappers: c:, v:, s:, a:, d:, j:, n:, t:, l:, u:
    if len(expr) >= 2 and expr[1] == ":" and expr[0] in "ascdvjntlu":
        wrap_map = {
            "a": PolicyNodeKind.WRAP_A,
            "s": PolicyNodeKind.WRAP_S,
            "c": PolicyNodeKind.WRAP_C,
            "d": PolicyNodeKind.WRAP_D,
            "v": PolicyNodeKind.WRAP_V,
            "j": PolicyNodeKind.WRAP_J,
            "n": PolicyNodeKind.WRAP_N,
            "t": PolicyNodeKind.WRAP_T,
            "l": PolicyNodeKind.WRAP_L,
            "u": PolicyNodeKind.WRAP_U,
        }
        inner = _parse_policy_expr(expr[2:], max_nodes=max_nodes, counter=counter)
        return PolicyNode(kind=wrap_map[expr[0]], children=(inner,))

    if expr in {"0", "1"}:
        return PolicyNode(
            kind=PolicyNodeKind.FALSE if expr == "0" else PolicyNodeKind.TRUE
        )

    # function(args)
    open_idx = expr.find("(")
    if open_idx < 0 or not expr.endswith(")"):
        # Bare key token treated as pk(KEY) for descriptor-ish keys.
        if _KEY_TOKEN_RE.fullmatch(expr):
            return PolicyNode(kind=PolicyNodeKind.PK, args=(expr,))
        return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=(expr,))

    name = expr[:open_idx].strip().lower()
    body = expr[open_idx + 1 : -1]
    args = _split_top_level_args(body) if body else []

    if name in {"pk", "pk_k", "pk_h"}:
        kind = PolicyNodeKind.PKH if name == "pk_h" else PolicyNodeKind.PK
        if name == "pk_k":
            kind = PolicyNodeKind.PK
        if len(args) != 1:
            return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=tuple(args))
        return PolicyNode(kind=kind, args=(args[0],))
    if name == "pkh":
        if len(args) != 1:
            return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=tuple(args))
        return PolicyNode(kind=PolicyNodeKind.PKH, args=(args[0],))
    if name in {"multi", "sortedmulti"}:
        if len(args) < 2:
            return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=tuple(args))
        return PolicyNode(kind=PolicyNodeKind.MULTI, args=tuple(args))
    if name == "thresh":
        if len(args) < 2:
            return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=tuple(args))
        children = tuple(
            _parse_policy_expr(a, max_nodes=max_nodes, counter=counter)
            for a in args[1:]
        )
        return PolicyNode(kind=PolicyNodeKind.THRESH, args=(args[0],), children=children)
    if name in {"and", "and_v", "and_b", "and_n"}:
        children = tuple(
            _parse_policy_expr(a, max_nodes=max_nodes, counter=counter) for a in args
        )
        return PolicyNode(kind=PolicyNodeKind.AND, children=children)
    if name in {"or", "or_b", "or_c", "or_d", "or_i"}:
        children = tuple(
            _parse_policy_expr(a, max_nodes=max_nodes, counter=counter) for a in args
        )
        return PolicyNode(kind=PolicyNodeKind.OR, children=children)
    if name in {"andor"}:
        children = tuple(
            _parse_policy_expr(a, max_nodes=max_nodes, counter=counter) for a in args
        )
        return PolicyNode(kind=PolicyNodeKind.ANDOR, children=children)
    if name == "older":
        if len(args) != 1:
            return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=tuple(args))
        return PolicyNode(kind=PolicyNodeKind.OLDER, args=(args[0],))
    if name == "after":
        if len(args) != 1:
            return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=tuple(args))
        return PolicyNode(kind=PolicyNodeKind.AFTER, args=(args[0],))
    if name == "sha256":
        return PolicyNode(
            kind=PolicyNodeKind.SHA256, args=(args[0],) if args else ()
        )
    if name == "hash256":
        return PolicyNode(
            kind=PolicyNodeKind.HASH256, args=(args[0],) if args else ()
        )
    if name == "ripemd160":
        return PolicyNode(
            kind=PolicyNodeKind.RIPEMD160, args=(args[0],) if args else ()
        )
    if name == "hash160":
        return PolicyNode(
            kind=PolicyNodeKind.HASH160, args=(args[0],) if args else ()
        )
    return PolicyNode(kind=PolicyNodeKind.UNKNOWN, args=(name, *args))


def _collect_keys(node: PolicyNode, out: list[str]) -> None:
    if node.kind in {PolicyNodeKind.PK, PolicyNodeKind.PKH} and node.args:
        out.append(node.args[0])
    if node.kind is PolicyNodeKind.MULTI:
        out.extend(node.args[1:])
    for child in node.children:
        _collect_keys(child, out)


def _collect_thresholds(node: PolicyNode, out: list[tuple[int, int]]) -> None:
    if node.kind is PolicyNodeKind.MULTI and node.args:
        try:
            k = int(node.args[0])
            n = len(node.args) - 1
            out.append((k, n))
        except ValueError:
            pass
    if node.kind is PolicyNodeKind.THRESH and node.args:
        try:
            k = int(node.args[0])
            n = len(node.children)
            out.append((k, n))
        except ValueError:
            pass
    for child in node.children:
        _collect_thresholds(child, out)


def _has_kind(node: PolicyNode, kinds: set[PolicyNodeKind]) -> bool:
    if node.kind in kinds:
        return True
    return any(_has_kind(c, kinds) for c in node.children)


def _fully_known(node: PolicyNode) -> bool:
    if node.kind is PolicyNodeKind.UNKNOWN:
        return False
    return all(_fully_known(c) for c in node.children)


def parse_miniscript(
    expression: str,
    *,
    max_chars: int = DEFAULT_MAX_POLICY_CHARS,
    max_nodes: int = DEFAULT_MAX_TREE_NODES,
    attributes: Mapping[str, Any] | None = None,
) -> MiniscriptPolicy:
    """Parse a miniscript/policy expression into a :class:`MiniscriptPolicy`."""

    text = _required_text(expression, "expression")
    max_chars = _positive(max_chars, "max_chars")
    max_nodes = _positive(max_nodes, "max_nodes")
    if len(text) > max_chars:
        raise ResourceLimitError("policy expression exceeds max_chars")
    counter = [0]
    root = _parse_policy_expr(text, max_nodes=max_nodes, counter=counter)
    keys: list[str] = []
    _collect_keys(root, keys)
    # Stable unique order.
    seen: set[str] = set()
    uniq_keys: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            uniq_keys.append(key)
    thresholds: list[tuple[int, int]] = []
    _collect_thresholds(root, thresholds)
    canonical = root.canonical_form()
    fully = _fully_known(root)
    return MiniscriptPolicy(
        expression=text,
        root=root,
        canonical=canonical,
        policy_digest=bytes_digest(canonical.encode("utf-8")),
        keys=tuple(uniq_keys),
        thresholds=tuple(thresholds),
        has_timelock=_has_kind(root, {PolicyNodeKind.OLDER, PolicyNodeKind.AFTER}),
        has_hashlock=_has_kind(
            root,
            {
                PolicyNodeKind.SHA256,
                PolicyNodeKind.HASH256,
                PolicyNodeKind.RIPEMD160,
                PolicyNodeKind.HASH160,
            },
        ),
        fully_parsed=fully,
        attributes=dict(attributes or {}),
    )


def parse_descriptor(
    descriptor: str,
    *,
    parse_body_as_miniscript: bool = True,
    attributes: Mapping[str, Any] | None = None,
) -> OutputDescriptor:
    """Parse an output descriptor string (checksum optional)."""

    text = _required_text(descriptor, "descriptor")
    checksum = ""
    checksum_present = False
    body_full = text
    if "#" in text:
        # BIP-380: checksum after last '#'
        main, _, chk = text.rpartition("#")
        if main and chk:
            body_full = main
            checksum = chk
            checksum_present = True

    multipath = "<" in body_full and ">" in body_full
    open_idx = body_full.find("(")
    if open_idx < 0:
        return OutputDescriptor(
            descriptor=text,
            descriptor_type=DescriptorType.UNKNOWN,
            body=body_full,
            checksum=checksum,
            checksum_present=checksum_present,
            multipath=multipath,
            attributes=dict(attributes or {}),
        )

    head = body_full[:open_idx].strip().lower()
    type_map = {
        "pk": DescriptorType.PK,
        "pkh": DescriptorType.PKH,
        "wpkh": DescriptorType.WPKH,
        "sh": DescriptorType.SH,
        "wsh": DescriptorType.WSH,
        "tr": DescriptorType.TR,
        "multi": DescriptorType.MULTI,
        "sortedmulti": DescriptorType.SORTED_MULTI,
        "raw": DescriptorType.RAW,
        "addr": DescriptorType.ADDR,
    }
    dtype = type_map.get(head, DescriptorType.UNKNOWN)
    # Inner body between first '(' and matching ')'
    if not body_full.endswith(")"):
        inner = body_full[open_idx + 1 :]
    else:
        inner = body_full[open_idx + 1 : -1]

    miniscript: MiniscriptPolicy | None = None
    # Only peel outer script wrappers (sh/wsh/tr), never multi/pk policy heads.
    _wrapper_types = {
        "sh",
        "wsh",
        "tr",
    }
    if parse_body_as_miniscript and inner:
        # Nested descriptors: wsh(multi(...)) — parse innermost policy-ish form.
        candidate = inner
        while True:
            nested_open = candidate.find("(")
            if nested_open <= 0:
                break
            nested_head = candidate[:nested_open].strip().lower()
            if nested_head in _wrapper_types and candidate.endswith(")"):
                candidate = candidate[nested_open + 1 : -1]
                continue
            break
        try:
            policy_prefixes = (
                "multi(",
                "sortedmulti(",
                "pk(",
                "pkh(",
                "thresh(",
                "and(",
                "or(",
                "andor(",
                "older(",
                "after(",
                "sha256(",
                "hash160(",
                "hash256(",
                "ripemd160(",
                "c:",
                "v:",
                "s:",
                "a:",
                "d:",
                "j:",
                "n:",
                "t:",
                "l:",
                "u:",
            )
            if candidate.startswith(policy_prefixes):
                miniscript = parse_miniscript(candidate)
            elif head in {"multi", "sortedmulti"}:
                miniscript = parse_miniscript(f"multi({inner})")
            elif head in {"pk", "pkh", "wpkh"}:
                miniscript = parse_miniscript(
                    f"pk({inner})" if head != "pkh" else f"pkh({inner})"
                )
        except (InvalidRequestError, ResourceLimitError):
            miniscript = None

    return OutputDescriptor(
        descriptor=text,
        descriptor_type=dtype,
        body=inner,
        checksum=checksum,
        checksum_present=checksum_present,
        miniscript=miniscript,
        multipath=multipath,
        attributes=dict(attributes or {}),
    )


def compare_policies(
    left: MiniscriptPolicy | str,
    right: MiniscriptPolicy | str,
) -> PolicyEquivalenceStatus:
    """Compare two policies; equality is proven or explicitly unknown."""

    left_pol = left if isinstance(left, MiniscriptPolicy) else parse_miniscript(left)
    right_pol = right if isinstance(right, MiniscriptPolicy) else parse_miniscript(right)
    return left_pol.equivalence(right_pol)


def compare_descriptors(
    left: OutputDescriptor | str,
    right: OutputDescriptor | str,
) -> PolicyEquivalenceStatus:
    """Compare descriptors via miniscript body when both parse fully."""

    left_d = left if isinstance(left, OutputDescriptor) else parse_descriptor(left)
    right_d = right if isinstance(right, OutputDescriptor) else parse_descriptor(right)
    if left_d.descriptor_type != right_d.descriptor_type:
        # Different families may still wrap equivalent policies — unknown.
        if left_d.miniscript and right_d.miniscript:
            return left_d.miniscript.equivalence(right_d.miniscript)
        return PolicyEquivalenceStatus.INCOMPARABLE
    if left_d.miniscript and right_d.miniscript:
        return left_d.miniscript.equivalence(right_d.miniscript)
    # Fall back to exact descriptor string (without checksum).
    left_main = left_d.descriptor.split("#", 1)[0]
    right_main = right_d.descriptor.split("#", 1)[0]
    if left_main == right_main:
        return PolicyEquivalenceStatus.PROVEN_EQUAL
    if left_d.body and right_d.body and left_d.body == right_d.body:
        return PolicyEquivalenceStatus.PROVEN_EQUAL
    if not left_d.miniscript or not right_d.miniscript:
        return PolicyEquivalenceStatus.UNKNOWN
    return PolicyEquivalenceStatus.PROVEN_UNEQUAL


__all__ = [
    "DEFAULT_MAX_KEYS",
    "DEFAULT_MAX_POLICY_CHARS",
    "DEFAULT_MAX_TREE_NODES",
    "MINISCRIPT_SCHEMA_VERSION",
    "DescriptorType",
    "MiniscriptPolicy",
    "OutputDescriptor",
    "PolicyEquivalenceStatus",
    "PolicyNode",
    "PolicyNodeKind",
    "compare_descriptors",
    "compare_policies",
    "parse_descriptor",
    "parse_miniscript",
]

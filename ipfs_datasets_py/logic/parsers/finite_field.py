"""Finite-field, bitvector, and ZK constraint profiles.

Interface:

* ``FiniteFieldConstraintLogic@1`` — parse/print/elaborate for controlled
  finite-field arithmetic, fixed-width bitvectors, range constraints, and
  R1CS/PLONK-style circuit constraints with **explicit** modulus, range,
  bit-width, and circuit identities

Owned constructs:

* field modulus (prime modulus identity on every field profile and term)
* field operations ``+``, ``-``, ``*``, ``inv`` over a declared modulus
* fixed-width bitvectors ``BitVec[w]`` with explicit bit-width identity
* integer ranges ``range(t, lo, hi)`` with explicit bounds
* R1CS constraints ``r1cs(A, B, C)`` encoding ``A * B = C``
* PLONK-style gates ``plonk(a, b, c, ql, qr, qo, qm, qc)``
* circuit identity (stable circuit_id + constraint-system kind)

Authority ceilings (fail-closed):

* Simulated ZKP evidence is advisory only and **cannot** become ZK proof
  authority.
* Arithmetic-solver / SMT-over-field evidence is satisfiability or bounded
  only and **cannot** become ZK proof authority.
* Cryptographic ZK proof authority requires an independent cryptographic
  backend path; this module never grants it from simulation or SMT.

Grammar (connective precedence, low → high)::

    formula     ::= and_formula
    and         ::= atom (('and'|∧|',') atom)*
    atom        ::= 'r1cs' '(' term ',' term ',' term ')'
                  | 'plonk' '(' term (',' term){7} ')'
                  | 'range' '(' term ',' NUMBER ',' NUMBER ')'
                  | 'bits' '(' term ',' NUMBER ')'
                  | 'mod' '(' NUMBER ')' | 'field_mod' '(' NUMBER ')'
                  | 'bvand'|'bvor'|'bvxor'|'bvadd'|'bvsub'|'bvmul'
                    '(' term ',' term ')'
                  | 'eq' '(' term ',' term ')' | term '==' term
                  | '(' formula ')'
    term        ::= sum
    sum         ::= product (('+'|'-') product)*
    product     ::= unary (('*'|'/') unary)*
    unary       ::= '-' unary | 'inv' '(' term ')' | primary
    primary     ::= NUMBER | 'bv' NUMBER | IDENT | '(' term ')'

Evidence subset: finite field bitvector circuit r1cs plonk crypto zkp.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
    mk_false,
    mk_true,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseArtifact,
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    INDIVIDUAL_SORT,
    LogicSignature,
    LogicSort,
    atomic_sort,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE: Final = "FiniteFieldConstraintLogic@1"
FINITE_FIELD_PROFILE_INTERFACE: Final = "FiniteFieldProfile@1"
BITVECTOR_PROFILE_INTERFACE: Final = "BitvectorProfile@1"
ZK_CIRCUIT_PROFILE_INTERFACE: Final = "ZKCircuitProfile@1"

FF_NOTATION_ID: Final = "canonical_finite_field_constraint"
FF_NOTATION_VERSION: Final = "1.0.0"
FF_FAMILY_ID: Final = "finite_field_constraint"
FF_MODULE_VERSION: Final = "1.0.0"

FF_PARSE_RESULT_SCHEMA: Final = "canonical-finite-field-parse-result/v1"
FF_PROFILE_SCHEMA: Final = "finite-field-constraint-profile/v1"
FF_FIELD_PROFILE_SCHEMA: Final = "finite-field-profile/v1"
FF_BITVECTOR_PROFILE_SCHEMA: Final = "bitvector-profile/v1"
FF_CIRCUIT_PROFILE_SCHEMA: Final = "zk-circuit-profile/v1"
FF_EVIDENCE_CONTRACT_SCHEMA: Final = "finite-field.evidence-contract/v1"
FF_IDENTITY_SCHEMA: Final = "finite-field.identity/v1"
FF_LOWERING_RECEIPT_SCHEMA: Final = "finite-field.lowering-receipt/v1"
FF_SOURCE_MAP_SCHEMA: Final = "finite-field.source-map/v1"

# Extension payload schemas (versioned family.construct/vN).
FF_MODULUS_PAYLOAD_SCHEMA: Final = "finite_field.modulus/v1"
FF_FIELD_OP_PAYLOAD_SCHEMA: Final = "finite_field.field_op/v1"
FF_FIELD_EQ_PAYLOAD_SCHEMA: Final = "finite_field.field_eq/v1"
FF_RANGE_PAYLOAD_SCHEMA: Final = "finite_field.range/v1"
FF_BITS_PAYLOAD_SCHEMA: Final = "finite_field.bits/v1"
FF_BITVECTOR_OP_PAYLOAD_SCHEMA: Final = "finite_field.bitvector_op/v1"
FF_R1CS_PAYLOAD_SCHEMA: Final = "finite_field.r1cs/v1"
FF_PLONK_PAYLOAD_SCHEMA: Final = "finite_field.plonk/v1"
FF_LITERAL_PAYLOAD_SCHEMA: Final = "finite_field.literal/v1"
FF_WIRE_PAYLOAD_SCHEMA: Final = "finite_field.wire/v1"
FF_AND_PAYLOAD_SCHEMA: Final = "finite_field.constraint_and/v1"

FIELD_SORT: Final = atomic_sort("Field")
BITVECTOR_SORT_PREFIX: Final = "BitVec"
RANGE_SORT: Final = atomic_sort("Range")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "finite_field.unexpected_token"
CODE_TRAILING_INPUT: Final = "finite_field.trailing_input"
CODE_EMPTY_INPUT: Final = "finite_field.empty_input"
CODE_PARSE_DEPTH: Final = "finite_field.parse_depth_exceeded"
CODE_UNBALANCED: Final = "finite_field.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "finite_field.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "finite_field.unknown_character"
CODE_PROFILE_MISMATCH: Final = "finite_field.profile_mismatch"
CODE_ARITY_MISMATCH: Final = "finite_field.arity_mismatch"
CODE_INVALID_MODULUS: Final = "finite_field.invalid_modulus"
CODE_MODULUS_MISMATCH: Final = "finite_field.modulus_mismatch"
CODE_INVALID_BIT_WIDTH: Final = "finite_field.invalid_bit_width"
CODE_BIT_WIDTH_MISMATCH: Final = "finite_field.bit_width_mismatch"
CODE_INVALID_RANGE: Final = "finite_field.invalid_range"
CODE_RANGE_MISMATCH: Final = "finite_field.range_mismatch"
CODE_INVALID_CIRCUIT: Final = "finite_field.invalid_circuit"
CODE_CIRCUIT_MISMATCH: Final = "finite_field.circuit_mismatch"
CODE_ROUND_TRIP: Final = "finite_field.round_trip_failed"
CODE_AUTHORITY_CEILING: Final = "finite_field.authority_ceiling"
CODE_PROMOTION_REJECTED: Final = "finite_field.zk_promotion_rejected"
CODE_UNSUPPORTED_CONSTRAINT: Final = "finite_field.unsupported_constraint"
CODE_DIVISION_BY_ZERO: Final = "finite_field.division_by_zero_literal"

_ALL_FF_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_UNKNOWN_CHARACTER,
        CODE_PROFILE_MISMATCH,
        CODE_ARITY_MISMATCH,
        CODE_INVALID_MODULUS,
        CODE_MODULUS_MISMATCH,
        CODE_INVALID_BIT_WIDTH,
        CODE_BIT_WIDTH_MISMATCH,
        CODE_INVALID_RANGE,
        CODE_RANGE_MISMATCH,
        CODE_INVALID_CIRCUIT,
        CODE_CIRCUIT_MISMATCH,
        CODE_ROUND_TRIP,
        CODE_AUTHORITY_CEILING,
        CODE_PROMOTION_REJECTED,
        CODE_UNSUPPORTED_CONSTRAINT,
        CODE_DIVISION_BY_ZERO,
    }
)

# Connectives / operators.
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&", ","})
_EQ_OPS: Final[frozenset[str]] = frozenset({"==", "="})
_ADD_OPS: Final[frozenset[str]] = frozenset({"+", "-"})
_MUL_OPS: Final[frozenset[str]] = frozenset({"*", "/"})

_CONSTRAINT_ATOMS: Final[frozenset[str]] = frozenset(
    {
        "r1cs",
        "plonk",
        "range",
        "bits",
        "mod",
        "field_mod",
        "eq",
        "bvand",
        "bvor",
        "bvxor",
        "bvadd",
        "bvsub",
        "bvmul",
    }
)

_BV_BINOPS: Final[frozenset[str]] = frozenset(
    {"bvand", "bvor", "bvxor", "bvadd", "bvsub", "bvmul"}
)

_FF_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "r1cs",
    "plonk",
    "range",
    "bits",
    "mod",
    "field_mod",
    "eq",
    "inv",
    "bv",
    "bvand",
    "bvor",
    "bvxor",
    "bvadd",
    "bvsub",
    "bvmul",
    "field",
    "bitvec",
    "true",
    "false",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class ConstraintSystemKind(str, Enum):
    """Declared arithmetic constraint-system kind."""

    FIELD = "field"
    BITVECTOR = "bitvector"
    R1CS = "r1cs"
    PLONK = "plonk"
    MIXED = "mixed"


class FieldOpKind(str, Enum):
    """Field arithmetic operators."""

    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    NEG = "neg"
    INV = "inv"


class BitvectorOpKind(str, Enum):
    """Fixed-width bitvector operators."""

    AND = "bvand"
    OR = "bvor"
    XOR = "bvxor"
    ADD = "bvadd"
    SUB = "bvsub"
    MUL = "bvmul"


class EvidenceSource(str, Enum):
    """Origin of constraint-system evidence (closed set)."""

    SIMULATED_ZKP = "simulated_zkp"
    ARITHMETIC_SOLVER = "arithmetic_solver"
    SMT_BITVECTOR = "smt_bitvector"
    R1CS_CHECKER = "r1cs_checker"
    PLONK_CHECKER = "plonk_checker"
    CRYPTOGRAPHIC_ZK = "cryptographic_zk"
    NONE = "none"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by finite-field / circuit evidence.

    Intentionally non-hierarchical: satisfiability and simulation never
    become cryptographic ZK proof authority.
    """

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    SATISFIABILITY = "satisfiability"
    ZK_PROOF = "zk_proof"


class BoundednessKind(str, Enum):
    """Semantic bound for finite-field / circuit evidence."""

    FINITE_FIELD = "finite_field"
    FIXED_BIT_WIDTH = "fixed_bit_width"
    FINITE_RANGE = "finite_range"
    FINITE_CIRCUIT = "finite_circuit"
    RESOURCE_BOUNDED = "resource_bounded"
    UNBOUNDED = "unbounded"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    AND = 10
    EQ = 20
    ADD = 30
    MUL = 40
    UNARY = 50
    ATOM = 60


# Sources that may never claim ZK proof authority.
_NON_ZK_PROOF_SOURCES: Final[frozenset[EvidenceSource]] = frozenset(
    {
        EvidenceSource.SIMULATED_ZKP,
        EvidenceSource.ARITHMETIC_SOLVER,
        EvidenceSource.SMT_BITVECTOR,
        EvidenceSource.R1CS_CHECKER,
        EvidenceSource.PLONK_CHECKER,
        EvidenceSource.NONE,
    }
)

# Maximum authority each evidence source may claim.
_SOURCE_AUTHORITY_CEILING: Final[Mapping[EvidenceSource, EvidenceAuthority]] = {
    EvidenceSource.NONE: EvidenceAuthority.NONE,
    EvidenceSource.SIMULATED_ZKP: EvidenceAuthority.ADVISORY,
    EvidenceSource.ARITHMETIC_SOLVER: EvidenceAuthority.SATISFIABILITY,
    EvidenceSource.SMT_BITVECTOR: EvidenceAuthority.SATISFIABILITY,
    EvidenceSource.R1CS_CHECKER: EvidenceAuthority.BOUNDED,
    EvidenceSource.PLONK_CHECKER: EvidenceAuthority.BOUNDED,
    # Cryptographic ZK remains gated; this module never auto-grants it.
    EvidenceSource.CRYPTOGRAPHIC_ZK: EvidenceAuthority.ZK_PROOF,
}

_AUTHORITY_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.SATISFIABILITY: 2,
    EvidenceAuthority.ZK_PROOF: 3,
}


# ---------------------------------------------------------------------------
# Identity records (modulus / range / bit-width / circuit)
# ---------------------------------------------------------------------------


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyntaxContractError(f"{label} must be an integer")
    if value < 1:
        raise SyntaxContractError(f"{label} must be positive")
    return value


def _require_non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyntaxContractError(f"{label} must be an integer")
    if value < 0:
        raise SyntaxContractError(f"{label} must be non-negative")
    return value


def _parse_int_literal(text: str, *, label: str = "integer literal") -> int:
    raw = text.strip()
    if not raw:
        raise SyntaxContractError(f"{label} is empty")
    try:
        if raw.lower().startswith("0x"):
            return int(raw, 16)
        return int(raw, 10)
    except ValueError as error:
        raise SyntaxContractError(f"invalid {label}: {text!r}") from error


# Extension / artifact payloads freeze through JSON-safe integers only.
_JSON_SAFE_INT_MAX: Final = (1 << 53) - 1


def _json_int(value: int | None) -> int | str | None:
    """Encode integers for freeze-safe extension/artifact payloads."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyntaxContractError("json int encoding requires int or None")
    if abs(value) > _JSON_SAFE_INT_MAX:
        return str(value)
    return value


def _from_json_int(value: object, *, label: str = "integer") -> int | None:
    """Decode a JSON-safe integer (int or decimal string)."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise SyntaxContractError(f"{label} must not be a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 10)
        except ValueError as error:
            raise SyntaxContractError(f"invalid {label}: {value!r}") from error
    raise SyntaxContractError(f"{label} must be int or decimal string")


def is_probable_prime(n: int) -> bool:
    """Miller–Rabin probable-primality (deterministic for n < 2**64).

    Large cryptographic moduli (e.g. BN254 scalar field) are accepted when
    they pass a fixed multi-witness Miller–Rabin battery; trial division is
    used only for tiny n.
    """

    if n < 2:
        return False
    if n in {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}:
        return True
    if n % 2 == 0 or n % 3 == 0 or n % 5 == 0:
        return False
    # Write n-1 = 2^s * d with d odd.
    d = n - 1
    s = 0
    while d % 2 == 0:
        d //= 2
        s += 1
    # Deterministic bases for 64-bit; extra bases for larger field primes.
    if n < 2_047:
        bases = (2,)
    elif n < 1_373_653:
        bases = (2, 3)
    elif n < 9_080_191:
        bases = (31, 73)
    elif n < 25_326_001:
        bases = (2, 3, 5)
    elif n < 3_215_031_751:
        bases = (2, 3, 5, 7)
    elif n < 2**64:
        bases = (2, 3, 5, 7, 11, 13, 23)
    else:
        bases = (2, 3, 5, 7, 11, 13, 23, 29, 31, 37)

    def _check(a: int) -> bool:
        x = pow(a % n, d, n)
        if x == 1 or x == n - 1:
            return True
        for _ in range(s - 1):
            x = (x * x) % n
            if x == n - 1:
                return True
        return False

    return all(_check(a) for a in bases if a % n != 0)


@dataclass(frozen=True, slots=True)
class ModulusIdentity:
    """Explicit finite-field modulus identity.

    Every field term and field constraint is scoped by this modulus.  A
    mismatch between profile modulus and surface ``mod(N)`` fails closed.
    """

    modulus: int
    require_prime: bool = True
    schema_version: str = FF_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        modulus = _require_positive_int(self.modulus, "modulus")
        if modulus < 2:
            raise SyntaxContractError(
                f"field modulus must be >= 2; got {modulus}",
            )
        if self.require_prime and not is_probable_prime(modulus):
            raise SyntaxContractError(
                f"field modulus {modulus} is not prime; "
                "non-prime moduli require require_prime=False"
            )
        object.__setattr__(self, "modulus", modulus)
        if self.schema_version != FF_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported modulus identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "modulus"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_kind": self.identity_kind,
            "modulus": _json_int(self.modulus),
            "require_prime": self.require_prime,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModulusIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("ModulusIdentity must be a mapping")
        modulus = _from_json_int(value["modulus"], label="modulus")
        if modulus is None:
            raise SyntaxContractError("modulus is required")
        return cls(
            modulus=modulus,
            require_prime=bool(value.get("require_prime", True)),
            schema_version=str(value.get("schema_version") or FF_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class BitWidthIdentity:
    """Explicit fixed bit-width identity for bitvector profiles/terms."""

    bit_width: int
    schema_version: str = FF_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        width = _require_positive_int(self.bit_width, "bit_width")
        if width > 4096:
            raise SyntaxContractError(
                f"bit_width {width} exceeds controlled maximum 4096"
            )
        object.__setattr__(self, "bit_width", width)
        if self.schema_version != FF_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported bit-width identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "bit_width"

    @property
    def sort_name(self) -> str:
        # Sort identifiers must match LogicSort name grammar (no brackets).
        return f"{BITVECTOR_SORT_PREFIX}_{self.bit_width}"

    def sort(self) -> LogicSort:
        return atomic_sort(self.sort_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bit_width": self.bit_width,
            "identity_kind": self.identity_kind,
            "schema_version": self.schema_version,
            "sort_name": self.sort_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BitWidthIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("BitWidthIdentity must be a mapping")
        return cls(
            bit_width=int(value["bit_width"]),
            schema_version=str(value.get("schema_version") or FF_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class RangeIdentity:
    """Explicit inclusive integer range identity."""

    low: int
    high: int
    schema_version: str = FF_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        low = self.low
        high = self.high
        if isinstance(low, bool) or not isinstance(low, int):
            raise SyntaxContractError("range low must be an integer")
        if isinstance(high, bool) or not isinstance(high, int):
            raise SyntaxContractError("range high must be an integer")
        if low > high:
            raise SyntaxContractError(
                f"range low {low} must be <= high {high}"
            )
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)
        if self.schema_version != FF_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported range identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "range"

    @property
    def width(self) -> int:
        return self.high - self.low + 1

    def contains(self, value: int) -> bool:
        return self.low <= value <= self.high

    def to_dict(self) -> dict[str, Any]:
        return {
            "high": self.high,
            "identity_kind": self.identity_kind,
            "low": self.low,
            "schema_version": self.schema_version,
            "width": self.width,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RangeIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("RangeIdentity must be a mapping")
        return cls(
            low=int(value["low"]),
            high=int(value["high"]),
            schema_version=str(value.get("schema_version") or FF_IDENTITY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class CircuitIdentity:
    """Explicit circuit identity for R1CS/PLONK-style constraint systems."""

    circuit_id: str
    system: ConstraintSystemKind | str = ConstraintSystemKind.R1CS
    constraint_count: int | None = None
    public_input_count: int = 0
    schema_version: str = FF_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        circuit_id = str(self.circuit_id or "").strip()
        if not circuit_id:
            raise SyntaxContractError("circuit_id is required")
        if "\x00" in circuit_id:
            raise SyntaxContractError("circuit_id must not contain NUL")
        system = (
            self.system
            if isinstance(self.system, ConstraintSystemKind)
            else ConstraintSystemKind(str(self.system))
        )
        if self.constraint_count is not None:
            count = _require_non_negative_int(
                self.constraint_count, "constraint_count"
            )
            object.__setattr__(self, "constraint_count", count)
        public = _require_non_negative_int(
            self.public_input_count, "public_input_count"
        )
        object.__setattr__(self, "circuit_id", circuit_id)
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "public_input_count", public)
        if self.schema_version != FF_IDENTITY_SCHEMA:
            raise SyntaxContractError(
                f"unsupported circuit identity schema {self.schema_version!r}"
            )

    @property
    def identity_kind(self) -> str:
        return "circuit"

    def to_dict(self) -> dict[str, Any]:
        system = (
            self.system.value
            if isinstance(self.system, ConstraintSystemKind)
            else str(self.system)
        )
        return {
            "circuit_id": self.circuit_id,
            "constraint_count": self.constraint_count,
            "identity_kind": self.identity_kind,
            "public_input_count": self.public_input_count,
            "schema_version": self.schema_version,
            "system": system,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CircuitIdentity:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("CircuitIdentity must be a mapping")
        count = value.get("constraint_count")
        return cls(
            circuit_id=str(value.get("circuit_id") or ""),
            system=value.get("system", ConstraintSystemKind.R1CS.value),
            constraint_count=int(count) if count is not None else None,
            public_input_count=int(value.get("public_input_count", 0)),
            schema_version=str(value.get("schema_version") or FF_IDENTITY_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FiniteFieldProfile:
    """Explicit finite-field arithmetic profile (``FiniteFieldProfile@1``)."""

    profile_id: str
    modulus: ModulusIdentity | int
    admit_division: bool = True
    admit_inversion: bool = True
    schema_version: str = FF_FIELD_PROFILE_SCHEMA

    interface: ClassVar[str] = FINITE_FIELD_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError("FiniteFieldProfile.profile_id is required")
        modulus = self.modulus
        if isinstance(modulus, int):
            modulus = ModulusIdentity(modulus=modulus)
        elif not isinstance(modulus, ModulusIdentity):
            if isinstance(modulus, Mapping):
                modulus = ModulusIdentity.from_dict(modulus)
            else:
                raise SyntaxContractError(
                    "FiniteFieldProfile.modulus must be ModulusIdentity or int"
                )
        object.__setattr__(self, "modulus", modulus)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if self.schema_version != FF_FIELD_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported FiniteFieldProfile schema {self.schema_version!r}"
            )

    @property
    def modulus_value(self) -> int:
        assert isinstance(self.modulus, ModulusIdentity)
        return self.modulus.modulus

    @property
    def semantic_identity(self) -> dict[str, Any]:
        assert isinstance(self.modulus, ModulusIdentity)
        return {
            "admit_division": self.admit_division,
            "admit_inversion": self.admit_inversion,
            "modulus": self.modulus.to_dict(),
            "profile_id": self.profile_id,
        }

    def to_dict(self) -> dict[str, Any]:
        assert isinstance(self.modulus, ModulusIdentity)
        return {
            "admit_division": self.admit_division,
            "admit_inversion": self.admit_inversion,
            "interface": self.interface,
            "modulus": self.modulus.to_dict(),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FiniteFieldProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("FiniteFieldProfile must be a mapping")
        raw_mod = value.get("modulus")
        if isinstance(raw_mod, Mapping):
            modulus: ModulusIdentity | int = ModulusIdentity.from_dict(raw_mod)
        else:
            modulus = int(raw_mod) if raw_mod is not None else 0
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            modulus=modulus,
            admit_division=bool(value.get("admit_division", True)),
            admit_inversion=bool(value.get("admit_inversion", True)),
            schema_version=str(
                value.get("schema_version") or FF_FIELD_PROFILE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class BitvectorProfile:
    """Explicit fixed-width bitvector profile (``BitvectorProfile@1``)."""

    profile_id: str
    bit_width: BitWidthIdentity | int
    admit_arithmetic: bool = True
    admit_bitwise: bool = True
    schema_version: str = FF_BITVECTOR_PROFILE_SCHEMA

    interface: ClassVar[str] = BITVECTOR_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError("BitvectorProfile.profile_id is required")
        width = self.bit_width
        if isinstance(width, int):
            width = BitWidthIdentity(bit_width=width)
        elif not isinstance(width, BitWidthIdentity):
            if isinstance(width, Mapping):
                width = BitWidthIdentity.from_dict(width)
            else:
                raise SyntaxContractError(
                    "BitvectorProfile.bit_width must be BitWidthIdentity or int"
                )
        object.__setattr__(self, "bit_width", width)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if self.schema_version != FF_BITVECTOR_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported BitvectorProfile schema {self.schema_version!r}"
            )

    @property
    def width_value(self) -> int:
        assert isinstance(self.bit_width, BitWidthIdentity)
        return self.bit_width.bit_width

    @property
    def semantic_identity(self) -> dict[str, Any]:
        assert isinstance(self.bit_width, BitWidthIdentity)
        return {
            "admit_arithmetic": self.admit_arithmetic,
            "admit_bitwise": self.admit_bitwise,
            "bit_width": self.bit_width.to_dict(),
            "profile_id": self.profile_id,
        }

    def to_dict(self) -> dict[str, Any]:
        assert isinstance(self.bit_width, BitWidthIdentity)
        return {
            "admit_arithmetic": self.admit_arithmetic,
            "admit_bitwise": self.admit_bitwise,
            "bit_width": self.bit_width.to_dict(),
            "interface": self.interface,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BitvectorProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("BitvectorProfile must be a mapping")
        raw = value.get("bit_width")
        if isinstance(raw, Mapping):
            width: BitWidthIdentity | int = BitWidthIdentity.from_dict(raw)
        else:
            width = int(raw) if raw is not None else 0
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            bit_width=width,
            admit_arithmetic=bool(value.get("admit_arithmetic", True)),
            admit_bitwise=bool(value.get("admit_bitwise", True)),
            schema_version=str(
                value.get("schema_version") or FF_BITVECTOR_PROFILE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class ZKCircuitProfile:
    """Explicit R1CS/PLONK circuit profile (``ZKCircuitProfile@1``)."""

    profile_id: str
    circuit: CircuitIdentity
    admit_r1cs: bool = True
    admit_plonk: bool = True
    schema_version: str = FF_CIRCUIT_PROFILE_SCHEMA

    interface: ClassVar[str] = ZK_CIRCUIT_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError("ZKCircuitProfile.profile_id is required")
        circuit = self.circuit
        if not isinstance(circuit, CircuitIdentity):
            if isinstance(circuit, Mapping):
                circuit = CircuitIdentity.from_dict(circuit)
            else:
                raise SyntaxContractError(
                    "ZKCircuitProfile.circuit must be a CircuitIdentity"
                )
        object.__setattr__(self, "circuit", circuit)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if not self.admit_r1cs and not self.admit_plonk:
            raise SyntaxContractError(
                "ZKCircuitProfile must admit at least one of r1cs or plonk"
            )
        if self.schema_version != FF_CIRCUIT_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported ZKCircuitProfile schema {self.schema_version!r}"
            )

    @property
    def circuit_id(self) -> str:
        return self.circuit.circuit_id

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_plonk": self.admit_plonk,
            "admit_r1cs": self.admit_r1cs,
            "circuit": self.circuit.to_dict(),
            "profile_id": self.profile_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_plonk": self.admit_plonk,
            "admit_r1cs": self.admit_r1cs,
            "circuit": self.circuit.to_dict(),
            "interface": self.interface,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ZKCircuitProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("ZKCircuitProfile must be a mapping")
        raw = value.get("circuit")
        circuit = (
            raw
            if isinstance(raw, CircuitIdentity)
            else CircuitIdentity.from_dict(
                raw if isinstance(raw, Mapping) else {"circuit_id": str(raw or "")}
            )
        )
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            circuit=circuit,
            admit_r1cs=bool(value.get("admit_r1cs", True)),
            admit_plonk=bool(value.get("admit_plonk", True)),
            schema_version=str(
                value.get("schema_version") or FF_CIRCUIT_PROFILE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class FiniteFieldConstraintProfile:
    """Combined finite-field / bitvector / ZK constraint profile.

    Interface: ``FiniteFieldConstraintLogic@1`` (profile facet).
    """

    profile_id: str
    field: FiniteFieldProfile | None = None
    bitvector: BitvectorProfile | None = None
    circuit: ZKCircuitProfile | None = None
    default_range: RangeIdentity | None = None
    system: ConstraintSystemKind | str = ConstraintSystemKind.MIXED
    schema_version: str = FF_PROFILE_SCHEMA

    interface: ClassVar[str] = FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "FiniteFieldConstraintProfile.profile_id is required"
            )
        if self.field is None and self.bitvector is None and self.circuit is None:
            raise SyntaxContractError(
                "FiniteFieldConstraintProfile requires at least one of "
                "field, bitvector, or circuit sub-profile"
            )
        system = (
            self.system
            if isinstance(self.system, ConstraintSystemKind)
            else ConstraintSystemKind(str(self.system))
        )
        if self.field is not None and not isinstance(self.field, FiniteFieldProfile):
            raise SyntaxContractError("field must be a FiniteFieldProfile or None")
        if self.bitvector is not None and not isinstance(
            self.bitvector, BitvectorProfile
        ):
            raise SyntaxContractError(
                "bitvector must be a BitvectorProfile or None"
            )
        if self.circuit is not None and not isinstance(self.circuit, ZKCircuitProfile):
            raise SyntaxContractError("circuit must be a ZKCircuitProfile or None")
        if self.default_range is not None and not isinstance(
            self.default_range, RangeIdentity
        ):
            raise SyntaxContractError(
                "default_range must be a RangeIdentity or None"
            )
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if self.schema_version != FF_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported FiniteFieldConstraintProfile schema "
                f"{self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return FF_FAMILY_ID

    @property
    def modulus_identity(self) -> ModulusIdentity | None:
        if self.field is None:
            return None
        assert isinstance(self.field.modulus, ModulusIdentity)
        return self.field.modulus

    @property
    def bit_width_identity(self) -> BitWidthIdentity | None:
        if self.bitvector is None:
            return None
        assert isinstance(self.bitvector.bit_width, BitWidthIdentity)
        return self.bitvector.bit_width

    @property
    def circuit_identity(self) -> CircuitIdentity | None:
        if self.circuit is None:
            return None
        return self.circuit.circuit

    @property
    def semantic_identity(self) -> dict[str, Any]:
        system = (
            self.system.value
            if isinstance(self.system, ConstraintSystemKind)
            else str(self.system)
        )
        return {
            "bit_width": (
                self.bit_width_identity.to_dict()
                if self.bit_width_identity is not None
                else None
            ),
            "bitvector": (
                self.bitvector.semantic_identity if self.bitvector else None
            ),
            "circuit": (
                self.circuit_identity.to_dict()
                if self.circuit_identity is not None
                else None
            ),
            "default_range": (
                self.default_range.to_dict() if self.default_range else None
            ),
            "field": self.field.semantic_identity if self.field else None,
            "modulus": (
                self.modulus_identity.to_dict()
                if self.modulus_identity is not None
                else None
            ),
            "profile_id": self.profile_id,
            "system": system,
        }

    def identities(self) -> dict[str, Any]:
        """Explicit modulus/range/bit-width/circuit identity projection."""

        return {
            "bit_width": (
                self.bit_width_identity.to_dict()
                if self.bit_width_identity is not None
                else None
            ),
            "circuit": (
                self.circuit_identity.to_dict()
                if self.circuit_identity is not None
                else None
            ),
            "modulus": (
                self.modulus_identity.to_dict()
                if self.modulus_identity is not None
                else None
            ),
            "range": (
                self.default_range.to_dict() if self.default_range is not None else None
            ),
            "schema_version": FF_IDENTITY_SCHEMA,
        }

    def to_dict(self) -> dict[str, Any]:
        system = (
            self.system.value
            if isinstance(self.system, ConstraintSystemKind)
            else str(self.system)
        )
        return {
            "bitvector": self.bitvector.to_dict() if self.bitvector else None,
            "circuit": self.circuit.to_dict() if self.circuit else None,
            "default_range": (
                self.default_range.to_dict() if self.default_range else None
            ),
            "field": self.field.to_dict() if self.field else None,
            "interface": self.interface,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "system": system,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FiniteFieldConstraintProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError(
                "FiniteFieldConstraintProfile must be a mapping"
            )
        raw_field = value.get("field")
        raw_bv = value.get("bitvector")
        raw_circuit = value.get("circuit")
        raw_range = value.get("default_range")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            field=(
                FiniteFieldProfile.from_dict(raw_field)
                if isinstance(raw_field, Mapping)
                else None
            ),
            bitvector=(
                BitvectorProfile.from_dict(raw_bv)
                if isinstance(raw_bv, Mapping)
                else None
            ),
            circuit=(
                ZKCircuitProfile.from_dict(raw_circuit)
                if isinstance(raw_circuit, Mapping)
                else None
            ),
            default_range=(
                RangeIdentity.from_dict(raw_range)
                if isinstance(raw_range, Mapping)
                else None
            ),
            system=value.get("system", ConstraintSystemKind.MIXED.value),
            schema_version=str(value.get("schema_version") or FF_PROFILE_SCHEMA),
        )


def profile_finite_field(
    modulus: int = 21888242871839275222246405745257275088548364400416034343698204186575808495617,
    *,
    profile_id: str = "finite_field_bn254",
    require_prime: bool = True,
) -> FiniteFieldConstraintProfile:
    """BN254-scalar-style (or custom) finite-field profile."""

    return FiniteFieldConstraintProfile(
        profile_id=profile_id,
        field=FiniteFieldProfile(
            profile_id=f"{profile_id}:field",
            modulus=ModulusIdentity(
                modulus=modulus, require_prime=require_prime
            ),
        ),
        system=ConstraintSystemKind.FIELD,
    )


def profile_bitvector(
    bit_width: int = 32,
    *,
    profile_id: str = "bitvector_fixed",
) -> FiniteFieldConstraintProfile:
    """Fixed-width bitvector profile."""

    return FiniteFieldConstraintProfile(
        profile_id=profile_id,
        bitvector=BitvectorProfile(
            profile_id=f"{profile_id}:bitvector",
            bit_width=BitWidthIdentity(bit_width=bit_width),
        ),
        system=ConstraintSystemKind.BITVECTOR,
    )


def profile_r1cs(
    *,
    modulus: int = 17,
    circuit_id: str = "circuit:r1cs:1",
    profile_id: str = "r1cs_field",
    require_prime: bool = True,
) -> FiniteFieldConstraintProfile:
    """R1CS over a finite field with explicit modulus + circuit identities."""

    return FiniteFieldConstraintProfile(
        profile_id=profile_id,
        field=FiniteFieldProfile(
            profile_id=f"{profile_id}:field",
            modulus=ModulusIdentity(
                modulus=modulus, require_prime=require_prime
            ),
        ),
        circuit=ZKCircuitProfile(
            profile_id=f"{profile_id}:circuit",
            circuit=CircuitIdentity(
                circuit_id=circuit_id,
                system=ConstraintSystemKind.R1CS,
            ),
            admit_r1cs=True,
            admit_plonk=False,
        ),
        system=ConstraintSystemKind.R1CS,
    )


def profile_plonk(
    *,
    modulus: int = 17,
    circuit_id: str = "circuit:plonk:1",
    profile_id: str = "plonk_field",
    require_prime: bool = True,
) -> FiniteFieldConstraintProfile:
    """PLONK-style gates over a finite field."""

    return FiniteFieldConstraintProfile(
        profile_id=profile_id,
        field=FiniteFieldProfile(
            profile_id=f"{profile_id}:field",
            modulus=ModulusIdentity(
                modulus=modulus, require_prime=require_prime
            ),
        ),
        circuit=ZKCircuitProfile(
            profile_id=f"{profile_id}:circuit",
            circuit=CircuitIdentity(
                circuit_id=circuit_id,
                system=ConstraintSystemKind.PLONK,
            ),
            admit_r1cs=False,
            admit_plonk=True,
        ),
        system=ConstraintSystemKind.PLONK,
    )


def profile_finite_field_constraint_mixed(
    *,
    modulus: int = 17,
    bit_width: int = 32,
    circuit_id: str = "circuit:mixed:1",
    range_low: int = 0,
    range_high: int | None = None,
    profile_id: str = "finite_field_constraint_mixed",
    require_prime: bool = True,
) -> FiniteFieldConstraintProfile:
    """Combined field + bitvector + R1CS/PLONK profile for crypto/ZK use cases."""

    high = range_high if range_high is not None else (1 << bit_width) - 1
    return FiniteFieldConstraintProfile(
        profile_id=profile_id,
        field=FiniteFieldProfile(
            profile_id=f"{profile_id}:field",
            modulus=ModulusIdentity(
                modulus=modulus, require_prime=require_prime
            ),
        ),
        bitvector=BitvectorProfile(
            profile_id=f"{profile_id}:bitvector",
            bit_width=BitWidthIdentity(bit_width=bit_width),
        ),
        circuit=ZKCircuitProfile(
            profile_id=f"{profile_id}:circuit",
            circuit=CircuitIdentity(
                circuit_id=circuit_id,
                system=ConstraintSystemKind.MIXED,
            ),
            admit_r1cs=True,
            admit_plonk=True,
        ),
        default_range=RangeIdentity(low=range_low, high=high),
        system=ConstraintSystemKind.MIXED,
    )


def finite_field_semantic_identity(
    node: LogicNode,
    profile: FiniteFieldConstraintProfile,
) -> dict[str, Any]:
    """Stable semantic identity including modulus/range/bit-width/circuit."""

    extracted = extract_constraint_identities(node)
    return {
        "extracted": extracted,
        "family": FF_FAMILY_ID,
        "node_kind": (
            node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
        ),
        "profile": profile.semantic_identity,
        "profile_identities": profile.identities(),
    }


# ---------------------------------------------------------------------------
# Evidence contracts — simulated/SMT cannot become ZK proof authority
# ---------------------------------------------------------------------------


class AuthorityPromotionError(SyntaxContractError):
    """Raised when evidence is promoted beyond its declared authority ceiling."""


@dataclass(frozen=True, slots=True)
class FiniteFieldEvidenceContract:
    """Authority ceiling for finite-field / circuit evidence.

    Simulated ZKP and arithmetic-solver results are **never** ZK proof
    authority.  Cryptographic ZK proof authority cannot be constructed from
    those sources.
    """

    source: EvidenceSource | str
    authority: EvidenceAuthority | str
    bound: BoundednessKind | str = BoundednessKind.FINITE_CIRCUIT
    modulus: ModulusIdentity | None = None
    bit_width: BitWidthIdentity | None = None
    range: RangeIdentity | None = None
    circuit: CircuitIdentity | None = None
    grants_zk_proof_authority: bool = False
    schema_version: str = FF_EVIDENCE_CONTRACT_SCHEMA

    interface: ClassVar[str] = FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE

    def __post_init__(self) -> None:
        source = (
            self.source
            if isinstance(self.source, EvidenceSource)
            else EvidenceSource(str(self.source))
        )
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        bound = (
            self.bound
            if isinstance(self.bound, BoundednessKind)
            else BoundednessKind(str(self.bound))
        )
        ceiling = _SOURCE_AUTHORITY_CEILING[source]
        if _AUTHORITY_RANK[authority] > _AUTHORITY_RANK[ceiling]:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot claim {authority.value} "
                f"authority (ceiling={ceiling.value}); simulated or "
                "arithmetic-solver evidence cannot become ZK proof authority"
            )
        if authority is EvidenceAuthority.ZK_PROOF:
            if source is not EvidenceSource.CRYPTOGRAPHIC_ZK:
                raise AuthorityPromotionError(
                    f"{source.value} evidence cannot become ZK proof authority"
                )
            if self.grants_zk_proof_authority is not True:
                raise AuthorityPromotionError(
                    "ZK proof authority requires grants_zk_proof_authority=True "
                    "from a cryptographic backend; this profile module never "
                    "auto-grants it"
                )
        else:
            if self.grants_zk_proof_authority:
                raise AuthorityPromotionError(
                    f"{source.value}/{authority.value} cannot set "
                    "grants_zk_proof_authority=True"
                )
        if source in _NON_ZK_PROOF_SOURCES and authority is EvidenceAuthority.ZK_PROOF:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot become ZK proof authority"
            )
        if bound is BoundednessKind.UNBOUNDED and authority is EvidenceAuthority.ZK_PROOF:
            # ZK proof is still not unbounded classical theorem authority.
            pass
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "bound", bound)
        if self.modulus is not None and not isinstance(self.modulus, ModulusIdentity):
            raise SyntaxContractError("modulus must be ModulusIdentity or None")
        if self.bit_width is not None and not isinstance(
            self.bit_width, BitWidthIdentity
        ):
            raise SyntaxContractError("bit_width must be BitWidthIdentity or None")
        if self.range is not None and not isinstance(self.range, RangeIdentity):
            raise SyntaxContractError("range must be RangeIdentity or None")
        if self.circuit is not None and not isinstance(self.circuit, CircuitIdentity):
            raise SyntaxContractError("circuit must be CircuitIdentity or None")
        if self.schema_version != FF_EVIDENCE_CONTRACT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported evidence contract schema {self.schema_version!r}"
            )

    @property
    def authority_ceiling(self) -> EvidenceAuthority:
        assert isinstance(self.authority, EvidenceAuthority)
        return self.authority

    @property
    def source_ceiling(self) -> EvidenceAuthority:
        assert isinstance(self.source, EvidenceSource)
        return _SOURCE_AUTHORITY_CEILING[self.source]

    @property
    def may_promote_to_zk_proof(self) -> bool:
        return False

    @property
    def is_zk_proof(self) -> bool:
        return (
            self.authority_ceiling is EvidenceAuthority.ZK_PROOF
            and self.grants_zk_proof_authority
        )

    def promote_to_zk_proof(self) -> None:
        """Fail closed: simulated/SMT/checker evidence is never ZK proof."""

        source = (
            self.source.value
            if isinstance(self.source, EvidenceSource)
            else str(self.source)
        )
        authority = (
            self.authority.value
            if isinstance(self.authority, EvidenceAuthority)
            else str(self.authority)
        )
        raise AuthorityPromotionError(
            f"{source} evidence with authority={authority} cannot be promoted "
            "to ZK proof authority; simulated or arithmetic-solver evidence "
            "cannot become ZK proof authority"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority_ceiling.value,
            "authority_ceiling": self.authority_ceiling.value,
            "bit_width": self.bit_width.to_dict() if self.bit_width else None,
            "bound": (
                self.bound.value
                if isinstance(self.bound, BoundednessKind)
                else str(self.bound)
            ),
            "circuit": self.circuit.to_dict() if self.circuit else None,
            "grants_zk_proof_authority": bool(self.grants_zk_proof_authority),
            "interface": self.interface,
            "is_zk_proof": self.is_zk_proof,
            "may_promote_to_zk_proof": False,
            "modulus": self.modulus.to_dict() if self.modulus else None,
            "range": self.range.to_dict() if self.range else None,
            "schema_version": self.schema_version,
            "source": (
                self.source.value
                if isinstance(self.source, EvidenceSource)
                else str(self.source)
            ),
            "source_ceiling": self.source_ceiling.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FiniteFieldEvidenceContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("evidence contract must be a mapping")
        raw_mod = value.get("modulus")
        raw_bw = value.get("bit_width")
        raw_range = value.get("range")
        raw_circuit = value.get("circuit")
        return cls(
            source=value.get("source", EvidenceSource.NONE.value),
            authority=value.get("authority", EvidenceAuthority.NONE.value),
            bound=value.get("bound", BoundednessKind.FINITE_CIRCUIT.value),
            modulus=(
                ModulusIdentity.from_dict(raw_mod)
                if isinstance(raw_mod, Mapping)
                else None
            ),
            bit_width=(
                BitWidthIdentity.from_dict(raw_bw)
                if isinstance(raw_bw, Mapping)
                else None
            ),
            range=(
                RangeIdentity.from_dict(raw_range)
                if isinstance(raw_range, Mapping)
                else None
            ),
            circuit=(
                CircuitIdentity.from_dict(raw_circuit)
                if isinstance(raw_circuit, Mapping)
                else None
            ),
            grants_zk_proof_authority=bool(
                value.get("grants_zk_proof_authority", False)
            ),
            schema_version=str(
                value.get("schema_version") or FF_EVIDENCE_CONTRACT_SCHEMA
            ),
        )


def simulated_zkp_evidence_contract(
    profile: FiniteFieldConstraintProfile | None = None,
) -> FiniteFieldEvidenceContract:
    """Simulated ZKP evidence: advisory only; never ZK proof authority."""

    return FiniteFieldEvidenceContract(
        source=EvidenceSource.SIMULATED_ZKP,
        authority=EvidenceAuthority.ADVISORY,
        bound=BoundednessKind.RESOURCE_BOUNDED,
        modulus=profile.modulus_identity if profile else None,
        bit_width=profile.bit_width_identity if profile else None,
        range=profile.default_range if profile else None,
        circuit=profile.circuit_identity if profile else None,
        grants_zk_proof_authority=False,
    )


def arithmetic_solver_evidence_contract(
    profile: FiniteFieldConstraintProfile | None = None,
) -> FiniteFieldEvidenceContract:
    """Arithmetic/SMT solver evidence: satisfiability only; never ZK proof."""

    return FiniteFieldEvidenceContract(
        source=EvidenceSource.ARITHMETIC_SOLVER,
        authority=EvidenceAuthority.SATISFIABILITY,
        bound=BoundednessKind.FINITE_FIELD,
        modulus=profile.modulus_identity if profile else None,
        bit_width=profile.bit_width_identity if profile else None,
        range=profile.default_range if profile else None,
        circuit=profile.circuit_identity if profile else None,
        grants_zk_proof_authority=False,
    )


def smt_bitvector_evidence_contract(
    profile: FiniteFieldConstraintProfile | None = None,
) -> FiniteFieldEvidenceContract:
    """SMT bitvector evidence: satisfiability only; never ZK proof."""

    return FiniteFieldEvidenceContract(
        source=EvidenceSource.SMT_BITVECTOR,
        authority=EvidenceAuthority.SATISFIABILITY,
        bound=BoundednessKind.FIXED_BIT_WIDTH,
        modulus=profile.modulus_identity if profile else None,
        bit_width=profile.bit_width_identity if profile else None,
        range=profile.default_range if profile else None,
        circuit=profile.circuit_identity if profile else None,
        grants_zk_proof_authority=False,
    )


def r1cs_checker_evidence_contract(
    profile: FiniteFieldConstraintProfile | None = None,
) -> FiniteFieldEvidenceContract:
    """Local R1CS satisfaction checker: bounded only; never ZK proof."""

    return FiniteFieldEvidenceContract(
        source=EvidenceSource.R1CS_CHECKER,
        authority=EvidenceAuthority.BOUNDED,
        bound=BoundednessKind.FINITE_CIRCUIT,
        modulus=profile.modulus_identity if profile else None,
        bit_width=profile.bit_width_identity if profile else None,
        range=profile.default_range if profile else None,
        circuit=profile.circuit_identity if profile else None,
        grants_zk_proof_authority=False,
    )


def plonk_checker_evidence_contract(
    profile: FiniteFieldConstraintProfile | None = None,
) -> FiniteFieldEvidenceContract:
    """Local PLONK gate checker: bounded only; never ZK proof."""

    return FiniteFieldEvidenceContract(
        source=EvidenceSource.PLONK_CHECKER,
        authority=EvidenceAuthority.BOUNDED,
        bound=BoundednessKind.FINITE_CIRCUIT,
        modulus=profile.modulus_identity if profile else None,
        bit_width=profile.bit_width_identity if profile else None,
        range=profile.default_range if profile else None,
        circuit=profile.circuit_identity if profile else None,
        grants_zk_proof_authority=False,
    )


def cryptographic_zk_evidence_contract(
    profile: FiniteFieldConstraintProfile | None = None,
    *,
    grants_zk_proof_authority: bool = False,
) -> FiniteFieldEvidenceContract:
    """Cryptographic ZK path.

    Even for ``CRYPTOGRAPHIC_ZK``, ``grants_zk_proof_authority`` defaults to
    False so this module never auto-promotes; a real backend must opt in.
    """

    authority = (
        EvidenceAuthority.ZK_PROOF
        if grants_zk_proof_authority
        else EvidenceAuthority.BOUNDED
    )
    return FiniteFieldEvidenceContract(
        source=EvidenceSource.CRYPTOGRAPHIC_ZK,
        authority=authority,
        bound=BoundednessKind.FINITE_CIRCUIT,
        modulus=profile.modulus_identity if profile else None,
        bit_width=profile.bit_width_identity if profile else None,
        range=profile.default_range if profile else None,
        circuit=profile.circuit_identity if profile else None,
        grants_zk_proof_authority=grants_zk_proof_authority,
    )


def retain_authority_ceiling(
    evidence: FiniteFieldEvidenceContract,
    claimed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project evidence while retaining the declared authority ceiling.

    Any claim of ZK proof authority from a non-cryptographic source is
    rejected; the retained payload never escalates.
    """

    payload = evidence.to_dict()
    if claimed:
        claimed_authority = str(
            claimed.get("authority")
            or claimed.get("authority_ceiling")
            or payload["authority"]
        )
        claimed_zk = bool(claimed.get("grants_zk_proof_authority", False))
        claimed_is_zk = claimed_authority == EvidenceAuthority.ZK_PROOF.value or claimed_zk
        if claimed_is_zk and not evidence.is_zk_proof:
            raise AuthorityPromotionError(
                "claimed ZK proof authority exceeds retained ceiling "
                f"(source={payload['source']}, ceiling={payload['authority_ceiling']}); "
                "simulated or arithmetic-solver evidence cannot become ZK proof authority"
            )
        # Never copy escalated authority from the claim.
    retained = dict(payload)
    retained["authority"] = evidence.authority_ceiling.value
    retained["authority_ceiling"] = evidence.authority_ceiling.value
    retained["grants_zk_proof_authority"] = bool(evidence.grants_zk_proof_authority)
    retained["may_promote_to_zk_proof"] = False
    retained["is_zk_proof"] = evidence.is_zk_proof
    return retained


@dataclass(frozen=True, slots=True)
class FiniteFieldLoweringReceipt:
    """Receipt for one constraint-system lowering / evidence attachment."""

    document_id: str
    profile_id: str
    identities: dict[str, Any]
    evidence: dict[str, Any]
    authorizes_zk_proof: bool = False
    schema_version: str = FF_LOWERING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.authorizes_zk_proof and not self.evidence.get("is_zk_proof"):
            raise AuthorityPromotionError(
                "lowering receipt cannot authorize ZK proof without "
                "cryptographic ZK evidence"
            )
        if self.evidence.get("source") in {
            EvidenceSource.SIMULATED_ZKP.value,
            EvidenceSource.ARITHMETIC_SOLVER.value,
            EvidenceSource.SMT_BITVECTOR.value,
        } and (
            self.authorizes_zk_proof
            or self.evidence.get("authority") == EvidenceAuthority.ZK_PROOF.value
            or self.evidence.get("grants_zk_proof_authority")
        ):
            raise AuthorityPromotionError(
                "simulated or arithmetic-solver evidence cannot become "
                "ZK proof authority on a lowering receipt"
            )
        object.__setattr__(self, "authorizes_zk_proof", bool(self.authorizes_zk_proof))

    @property
    def authority_ceiling(self) -> str:
        return str(self.evidence.get("authority_ceiling") or self.evidence.get("authority"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_zk_proof": False if not self.authorizes_zk_proof else True,
            "authority_ceiling": self.authority_ceiling,
            "document_id": self.document_id,
            "evidence": dict(self.evidence),
            "identities": dict(self.identities),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FiniteFieldParseResult:
    """Typed result of a finite-field constraint parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: FiniteFieldConstraintProfile | None = None
    identities: dict[str, Any] = field(default_factory=dict)
    schema_version: str = FF_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identities": dict(self.identities),
            "interface": self.interface,
            "printed": self.printed,
            "profile": self.profile.to_dict() if self.profile else None,
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, ParseStatus)
            else str(self.status),
        }


class FiniteFieldParseError(SyntaxContractError):
    """Raised by raising helpers when a finite-field parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: FiniteFieldParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Diagnostics / cursor
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:ff:{code.replace('.', '-')}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


class _Cursor:
    def __init__(
        self,
        tokens: Sequence[LogicToken],
        document: SourceDocument,
    ) -> None:
        self.tokens = tuple(tokens)
        self.document = document
        self.index = 0
        self.depth = 0

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> LogicToken:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def is_eof(self) -> bool:
        return self.current().kind == TokenKind.EOF.value

    def advance(self) -> LogicToken:
        token = self.current()
        if not self.is_eof():
            self.index += 1
        return token

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = {item.casefold() for item in lexemes}
        if token.lexeme in lexemes or token.lexeme.casefold() in folded:
            return self.advance()
        return None

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        return self.match_any(frozenset(lexemes))

    def expect_lexeme(
        self, *lexemes: str, code: str = CODE_UNEXPECTED_TOKEN
    ) -> LogicToken:
        token = self.match_lexeme(*lexemes)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(repr(item) for item in lexemes)
        raise _ParseFail(
            _diag(
                code=code,
                message=f"expected {expected}; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def expect_number(self) -> LogicToken:
        token = self.current()
        if token.kind == TokenKind.NUMBER.value:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected number; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def expect_ident(self) -> LogicToken:
        token = self.current()
        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected identifier; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        if (
            start.start_char is not None
            and start.end_char is not None
            and end.start_char is not None
            and end.end_char is not None
        ):
            return SourceRange(
                start=start.start,
                end=end.end,
                start_char=start.start_char,
                end_char=end.end_char,
            )
        return SourceRange(start=start.start, end=end.end)


# ---------------------------------------------------------------------------
# Identity extraction from AST
# ---------------------------------------------------------------------------


def extract_constraint_identities(node: LogicNode) -> dict[str, Any]:
    """Walk a constraint AST and collect explicit identity fragments."""

    moduli: list[int] = []
    bit_widths: list[int] = []
    ranges: list[dict[str, int]] = []
    systems: list[str] = []
    circuit_ids: list[str] = []

    def walk(n: LogicNode) -> None:
        ext = n.extension
        if ext is not None:
            payload = dict(ext.payload)
            schema = ext.payload_schema
            if schema == FF_MODULUS_PAYLOAD_SCHEMA:
                mod = _from_json_int(payload.get("modulus"), label="modulus")
                if mod is not None:
                    moduli.append(mod)
            elif schema == FF_BITS_PAYLOAD_SCHEMA:
                bit_widths.append(int(payload["bit_width"]))
            elif schema == FF_RANGE_PAYLOAD_SCHEMA:
                ranges.append(
                    {"low": int(payload["low"]), "high": int(payload["high"])}
                )
            elif schema == FF_R1CS_PAYLOAD_SCHEMA:
                systems.append("r1cs")
                if payload.get("circuit_id"):
                    circuit_ids.append(str(payload["circuit_id"]))
                mod = _from_json_int(payload.get("modulus"), label="modulus")
                if mod is not None:
                    moduli.append(mod)
            elif schema == FF_PLONK_PAYLOAD_SCHEMA:
                systems.append("plonk")
                if payload.get("circuit_id"):
                    circuit_ids.append(str(payload["circuit_id"]))
                mod = _from_json_int(payload.get("modulus"), label="modulus")
                if mod is not None:
                    moduli.append(mod)
            elif schema == FF_BITVECTOR_OP_PAYLOAD_SCHEMA:
                if payload.get("bit_width") is not None:
                    bit_widths.append(int(payload["bit_width"]))
            elif schema == FF_FIELD_OP_PAYLOAD_SCHEMA:
                mod = _from_json_int(payload.get("modulus"), label="modulus")
                if mod is not None:
                    moduli.append(mod)
            elif schema == FF_FIELD_EQ_PAYLOAD_SCHEMA:
                mod = _from_json_int(payload.get("modulus"), label="modulus")
                if mod is not None:
                    moduli.append(mod)
            elif schema == FF_LITERAL_PAYLOAD_SCHEMA:
                mod = _from_json_int(payload.get("modulus"), label="modulus")
                if mod is not None:
                    moduli.append(mod)
            if payload.get("bit_width") is not None and schema not in {
                FF_BITS_PAYLOAD_SCHEMA,
                FF_BITVECTOR_OP_PAYLOAD_SCHEMA,
            }:
                try:
                    bit_widths.append(int(payload["bit_width"]))
                except (TypeError, ValueError):
                    pass
        for child in n.arguments:
            walk(child)
        if n.extension is not None:
            for child in n.extension.children:
                walk(child)

    walk(node)
    return {
        "bit_widths": sorted(set(bit_widths)),
        "circuit_ids": list(dict.fromkeys(circuit_ids)),
        "moduli": [_json_int(m) for m in sorted(set(moduli))],
        "ranges": ranges,
        "schema_version": FF_IDENTITY_SCHEMA,
        "systems": list(dict.fromkeys(systems)),
    }


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _FFParserEngine:
    """Recursive-descent finite-field / circuit constraint parser."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: FiniteFieldConstraintProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, document)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._seen_moduli: list[int] = []
        self._seen_widths: list[int] = []
        self._constraint_count = 0

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"{self.expression_id}:{prefix}:{self._counter}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def _field_modulus(self) -> int | None:
        ident = self.profile.modulus_identity
        return ident.modulus if ident is not None else None

    def _bit_width(self) -> int | None:
        ident = self.profile.bit_width_identity
        return ident.bit_width if ident is not None else None

    def _circuit_id(self) -> str | None:
        ident = self.profile.circuit_identity
        return ident.circuit_id if ident is not None else None

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if not self.document.text.strip():
            return None, (
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty finite-field constraint input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_formula()
            if not self.cursor.is_eof():
                tok = self.cursor.current()
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                        remediation="Remove trailing tokens or close open constructs",
                    )
                )
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_and()
        finally:
            self._leave()

    def _parse_and(self) -> LogicNode:
        left = self._parse_atom()
        while True:
            # Comma is a soft separator only when next token starts an atom.
            if self.cursor.match_any(frozenset({"and", "∧", "&", "&&"})) is not None:
                right = self._parse_atom()
            elif self.cursor.current().lexeme == ",":
                nxt = self.cursor.peek()
                if nxt.kind == TokenKind.EOF.value:
                    break
                # Lookahead: comma before another constraint atom or '('.
                if nxt.lexeme.casefold() in _CONSTRAINT_ATOMS or nxt.lexeme == "(":
                    self.cursor.advance()
                    right = self._parse_atom()
                else:
                    break
            else:
                break
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = LogicNode(
                node_id=self._nid("and"),
                kind=NodeKind.AND,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
                metadata={
                    "schema_version": FF_AND_PAYLOAD_SCHEMA,
                    "family": FF_FAMILY_ID,
                },
            )
        return left

    def _parse_atom(self) -> LogicNode:
        self._enter()
        try:
            token = self.cursor.current()
            if token.lexeme == "(":
                self.cursor.advance()
                inner = self._parse_formula()
                self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                return inner

            name = token.lexeme.casefold()
            if name in _CONSTRAINT_ATOMS and token.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                return self._parse_constraint_atom(name)

            # term == term
            left = self._parse_term()
            if self.cursor.match_any(_EQ_OPS) is not None:
                right = self._parse_term()
                span = self.cursor.range_span(
                    left.range or SourceRange(0, 0),
                    right.range or SourceRange(0, 0),
                )
                return self._build_field_eq(left, right, span)

            # Bare true/false as nullary constraints (rarely used).
            if left.kind is NodeKind.CONSTANT and left.symbol in {"true", "false"}:
                return mk_true(self._nid("true")) if left.symbol == "true" else mk_false(
                    self._nid("false")
                )

            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=(
                        f"expected constraint atom; got term starting at "
                        f"{token.lexeme!r}"
                    ),
                    range=token.range,
                    remediation=(
                        "Use r1cs(...), plonk(...), range(...), bits(...), "
                        "mod(...), bv* (...), or term == term"
                    ),
                )
            )
        finally:
            self._leave()

    def _parse_constraint_atom(self, name: str) -> LogicNode:
        start = self.cursor.advance()
        if name in {"mod", "field_mod"}:
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            num = self.cursor.expect_number()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            modulus = _parse_int_literal(num.lexeme, label="modulus")
            span = self.cursor.range_span(start.range, end.range)
            return self._build_modulus(modulus, span)

        if name == "r1cs":
            if self.profile.circuit is not None and not self.profile.circuit.admit_r1cs:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"r1cs is not admitted by profile "
                            f"{self.profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            a = self._parse_term()
            self.cursor.expect_lexeme(",")
            b = self._parse_term()
            self.cursor.expect_lexeme(",")
            c = self._parse_term()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_r1cs(a, b, c, span)

        if name == "plonk":
            if self.profile.circuit is not None and not self.profile.circuit.admit_plonk:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"plonk is not admitted by profile "
                            f"{self.profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            args: list[LogicNode] = []
            for index in range(8):
                if index:
                    self.cursor.expect_lexeme(",")
                args.append(self._parse_term())
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_plonk(args, span)

        if name == "range":
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            term = self._parse_term()
            self.cursor.expect_lexeme(",")
            lo_tok = self.cursor.expect_number()
            self.cursor.expect_lexeme(",")
            hi_tok = self.cursor.expect_number()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            low = _parse_int_literal(lo_tok.lexeme, label="range low")
            high = _parse_int_literal(hi_tok.lexeme, label="range high")
            span = self.cursor.range_span(start.range, end.range)
            return self._build_range(term, low, high, span)

        if name == "bits":
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            term = self._parse_term()
            self.cursor.expect_lexeme(",")
            w_tok = self.cursor.expect_number()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            width = _parse_int_literal(w_tok.lexeme, label="bit_width")
            span = self.cursor.range_span(start.range, end.range)
            return self._build_bits(term, width, span)

        if name == "eq":
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            left = self._parse_term()
            self.cursor.expect_lexeme(",")
            right = self._parse_term()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_field_eq(left, right, span)

        if name in _BV_BINOPS:
            if self.profile.bitvector is None:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"{name} requires a bitvector sub-profile on "
                            f"{self.profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            left = self._parse_term()
            self.cursor.expect_lexeme(",")
            right = self._parse_term()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_bv_op(name, left, right, span)

        raise _ParseFail(
            _diag(
                code=CODE_UNSUPPORTED_CONSTRAINT,
                message=f"unsupported constraint atom {name!r}",
                range=start.range,
            )
        )

    def _parse_term(self) -> LogicNode:
        return self._parse_sum()

    def _parse_sum(self) -> LogicNode:
        left = self._parse_product()
        while True:
            op_tok = self.cursor.match_any(_ADD_OPS)
            if op_tok is None:
                break
            right = self._parse_product()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            kind = FieldOpKind.ADD if op_tok.lexeme == "+" else FieldOpKind.SUB
            left = self._build_field_op(kind, (left, right), span)
        return left

    def _parse_product(self) -> LogicNode:
        left = self._parse_unary()
        while True:
            op_tok = self.cursor.match_any(_MUL_OPS)
            if op_tok is None:
                break
            right = self._parse_unary()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            if op_tok.lexeme == "/":
                if self.profile.field is not None and not self.profile.field.admit_division:
                    raise _ParseFail(
                        _diag(
                            code=CODE_PROFILE_MISMATCH,
                            message="division is not admitted by field profile",
                            range=span,
                        )
                    )
                kind = FieldOpKind.DIV
            else:
                kind = FieldOpKind.MUL
            left = self._build_field_op(kind, (left, right), span)
        return left

    def _parse_unary(self) -> LogicNode:
        if self.cursor.match_lexeme("-") is not None:
            start = self.cursor.current()
            inner = self._parse_unary()
            span = self.cursor.range_span(
                start.range, inner.range or start.range
            )
            return self._build_field_op(FieldOpKind.NEG, (inner,), span)
        token = self.cursor.current()
        if token.lexeme.casefold() == "inv" and token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            if self.profile.field is not None and not self.profile.field.admit_inversion:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message="inversion is not admitted by field profile",
                        range=token.range,
                    )
                )
            start = self.cursor.advance()
            self.cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            inner = self._parse_term()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._build_field_op(FieldOpKind.INV, (inner,), span)
        return self._parse_primary()

    def _parse_primary(self) -> LogicNode:
        token = self.cursor.current()
        if token.kind == TokenKind.NUMBER.value:
            self.cursor.advance()
            value = _parse_int_literal(token.lexeme, label="field literal")
            modulus = self._field_modulus()
            payload = {
                "literal": _json_int(value),
                "literal_kind": "integer",
                "modulus": _json_int(modulus),
                "schema_version": FF_LITERAL_PAYLOAD_SCHEMA,
            }
            return mk_extension(
                self._nid("lit"),
                family=FF_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("finite_field.literal",),
                payload_schema=FF_LITERAL_PAYLOAD_SCHEMA,
                payload=payload,
                sort=FIELD_SORT if modulus is not None else INDIVIDUAL_SORT,
                range=token.range,
            )

        if token.lexeme.casefold() == "bv" and token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            start = self.cursor.advance()
            num = self.cursor.expect_number()
            value = _parse_int_literal(num.lexeme, label="bitvector literal")
            width = self._bit_width()
            if width is None:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message="bv literal requires a bitvector profile bit_width",
                        range=start.range,
                    )
                )
            span = self.cursor.range_span(start.range, num.range)
            self._seen_widths.append(width)
            payload = {
                "bit_width": width,
                "literal": _json_int(value),
                "literal_kind": "bitvector",
                "schema_version": FF_LITERAL_PAYLOAD_SCHEMA,
            }
            return mk_extension(
                self._nid("bvlit"),
                family=FF_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("finite_field.bitvector_literal",),
                payload_schema=FF_LITERAL_PAYLOAD_SCHEMA,
                payload=payload,
                sort=BitWidthIdentity(bit_width=width).sort(),
                range=span,
            )

        if token.lexeme == "(":
            self.cursor.advance()
            inner = self._parse_term()
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            return inner

        if token.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            name = token.lexeme
            # Reject constraint keywords used as bare terms.
            if name.casefold() in _CONSTRAINT_ATOMS:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message=f"constraint keyword {name!r} is not a term",
                        range=token.range,
                    )
                )
            self.cursor.advance()
            width = self._bit_width()
            modulus = self._field_modulus()
            payload = {
                "name": name,
                "schema_version": FF_WIRE_PAYLOAD_SCHEMA,
                "modulus": _json_int(modulus),
                "bit_width": width,
            }
            if modulus is not None:
                wire_sort = FIELD_SORT
            elif width is not None:
                wire_sort = BitWidthIdentity(bit_width=width).sort()
            else:
                wire_sort = INDIVIDUAL_SORT
            return mk_extension(
                self._nid("wire"),
                family=FF_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("finite_field.wire",),
                payload_schema=FF_WIRE_PAYLOAD_SCHEMA,
                payload=payload,
                sort=wire_sort,
                range=token.range,
            )

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected term; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def _build_modulus(self, modulus: int, span: SourceRange) -> LogicNode:
        if modulus < 2:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_MODULUS,
                    message=f"modulus must be >= 2; got {modulus}",
                    range=span,
                )
            )
        profile_mod = self._field_modulus()
        if profile_mod is not None and modulus != profile_mod:
            raise _ParseFail(
                _diag(
                    code=CODE_MODULUS_MISMATCH,
                    message=(
                        f"surface modulus {modulus} does not match profile "
                        f"modulus {profile_mod}"
                    ),
                    range=span,
                    metadata={
                        "profile_modulus": profile_mod,
                        "surface_modulus": modulus,
                    },
                )
            )
        self._seen_moduli.append(modulus)
        self._constraint_count += 1
        payload = {
            "modulus": _json_int(modulus),
            "profile_id": self.profile.profile_id,
            "require_prime": (
                self.profile.field.modulus.require_prime
                if self.profile.field is not None
                and isinstance(self.profile.field.modulus, ModulusIdentity)
                else True
            ),
            "schema_version": FF_MODULUS_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("mod"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("finite_field.modulus",),
            payload_schema=FF_MODULUS_PAYLOAD_SCHEMA,
            payload=payload,
            range=span,
        )

    def _build_field_op(
        self,
        kind: FieldOpKind,
        children: Sequence[LogicNode],
        span: SourceRange,
    ) -> LogicNode:
        if self.profile.field is None and kind in {
            FieldOpKind.ADD,
            FieldOpKind.SUB,
            FieldOpKind.MUL,
            FieldOpKind.DIV,
            FieldOpKind.NEG,
            FieldOpKind.INV,
        }:
            # Field ops are still allowed as pure term builders under mixed
            # profiles that only declare circuit; modulus identity may be absent.
            pass
        modulus = self._field_modulus()
        if modulus is not None:
            self._seen_moduli.append(modulus)
        payload = {
            "kind": kind.value,
            "modulus": _json_int(modulus),
            "profile_id": self.profile.profile_id,
            "schema_version": FF_FIELD_OP_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid(f"fop_{kind.value}"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"finite_field.field_op.{kind.value}",),
            payload_schema=FF_FIELD_OP_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(children),
            sort=FIELD_SORT,
            range=span,
        )

    def _build_field_eq(
        self,
        left: LogicNode,
        right: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        modulus = self._field_modulus()
        if modulus is not None:
            self._seen_moduli.append(modulus)
        self._constraint_count += 1
        payload = {
            "kind": "field_eq",
            "modulus": _json_int(modulus),
            "profile_id": self.profile.profile_id,
            "schema_version": FF_FIELD_EQ_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("eq"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("finite_field.field_eq",),
            payload_schema=FF_FIELD_EQ_PAYLOAD_SCHEMA,
            payload=payload,
            children=(left, right),
            range=span,
        )

    def _build_range(
        self,
        term: LogicNode,
        low: int,
        high: int,
        span: SourceRange,
    ) -> LogicNode:
        try:
            identity = RangeIdentity(low=low, high=high)
        except SyntaxContractError as error:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_RANGE,
                    message=str(error),
                    range=span,
                )
            ) from error
        default = self.profile.default_range
        if default is not None and (
            identity.low < default.low or identity.high > default.high
        ):
            raise _ParseFail(
                _diag(
                    code=CODE_RANGE_MISMATCH,
                    message=(
                        f"range [{low}, {high}] is outside profile default "
                        f"[{default.low}, {default.high}]"
                    ),
                    range=span,
                    metadata={
                        "profile_range": default.to_dict(),
                        "surface_range": identity.to_dict(),
                    },
                )
            )
        self._constraint_count += 1
        payload = {
            "high": identity.high,
            "low": identity.low,
            "profile_id": self.profile.profile_id,
            "schema_version": FF_RANGE_PAYLOAD_SCHEMA,
            "width": identity.width,
        }
        return mk_extension(
            self._nid("range"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("finite_field.range",),
            payload_schema=FF_RANGE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(term,),
            range=span,
        )

    def _build_bits(
        self,
        term: LogicNode,
        width: int,
        span: SourceRange,
    ) -> LogicNode:
        try:
            identity = BitWidthIdentity(bit_width=width)
        except SyntaxContractError as error:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_BIT_WIDTH,
                    message=str(error),
                    range=span,
                )
            ) from error
        profile_width = self._bit_width()
        if profile_width is not None and width != profile_width:
            raise _ParseFail(
                _diag(
                    code=CODE_BIT_WIDTH_MISMATCH,
                    message=(
                        f"bits width {width} does not match profile "
                        f"bit_width {profile_width}"
                    ),
                    range=span,
                    metadata={
                        "profile_bit_width": profile_width,
                        "surface_bit_width": width,
                    },
                )
            )
        self._seen_widths.append(width)
        self._constraint_count += 1
        payload = {
            "bit_width": identity.bit_width,
            "profile_id": self.profile.profile_id,
            "schema_version": FF_BITS_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("bits"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("finite_field.bits",),
            payload_schema=FF_BITS_PAYLOAD_SCHEMA,
            payload=payload,
            children=(term,),
            range=span,
        )

    def _build_bv_op(
        self,
        name: str,
        left: LogicNode,
        right: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        width = self._bit_width()
        assert width is not None
        op = BitvectorOpKind(name)
        if op in {
            BitvectorOpKind.AND,
            BitvectorOpKind.OR,
            BitvectorOpKind.XOR,
        } and self.profile.bitvector is not None and not self.profile.bitvector.admit_bitwise:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=f"{name} bitwise op not admitted by bitvector profile",
                    range=span,
                )
            )
        if op in {
            BitvectorOpKind.ADD,
            BitvectorOpKind.SUB,
            BitvectorOpKind.MUL,
        } and self.profile.bitvector is not None and not self.profile.bitvector.admit_arithmetic:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=f"{name} arithmetic op not admitted by bitvector profile",
                    range=span,
                )
            )
        self._seen_widths.append(width)
        self._constraint_count += 1
        payload = {
            "bit_width": width,
            "kind": op.value,
            "profile_id": self.profile.profile_id,
            "schema_version": FF_BITVECTOR_OP_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid(op.value),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"finite_field.bitvector_op.{op.value}",),
            payload_schema=FF_BITVECTOR_OP_PAYLOAD_SCHEMA,
            payload=payload,
            children=(left, right),
            range=span,
        )

    def _build_r1cs(
        self,
        a: LogicNode,
        b: LogicNode,
        c: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        if self.profile.circuit is None and self.profile.system not in {
            ConstraintSystemKind.R1CS,
            ConstraintSystemKind.MIXED,
            ConstraintSystemKind.FIELD,
        }:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="r1cs requires an R1CS/mixed/field profile",
                    range=span,
                )
            )
        modulus = self._field_modulus()
        if modulus is not None:
            self._seen_moduli.append(modulus)
        circuit_id = self._circuit_id() or "circuit:anonymous:r1cs"
        self._constraint_count += 1
        payload = {
            "circuit_id": circuit_id,
            "kind": "r1cs",
            "modulus": _json_int(modulus),
            "profile_id": self.profile.profile_id,
            "relation": "A * B = C",
            "schema_version": FF_R1CS_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("r1cs"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("finite_field.r1cs",),
            payload_schema=FF_R1CS_PAYLOAD_SCHEMA,
            payload=payload,
            children=(a, b, c),
            range=span,
        )

    def _build_plonk(
        self,
        args: Sequence[LogicNode],
        span: SourceRange,
    ) -> LogicNode:
        if len(args) != 8:
            raise _ParseFail(
                _diag(
                    code=CODE_ARITY_MISMATCH,
                    message=f"plonk expects 8 arguments; got {len(args)}",
                    range=span,
                )
            )
        modulus = self._field_modulus()
        if modulus is not None:
            self._seen_moduli.append(modulus)
        circuit_id = self._circuit_id() or "circuit:anonymous:plonk"
        self._constraint_count += 1
        payload = {
            "circuit_id": circuit_id,
            "kind": "plonk",
            "modulus": _json_int(modulus),
            "profile_id": self.profile.profile_id,
            "relation": "ql*a + qr*b + qo*c + qm*a*b + qc = 0",
            "schema_version": FF_PLONK_PAYLOAD_SCHEMA,
            "selectors": ("ql", "qr", "qo", "qm", "qc"),
            "wires": ("a", "b", "c"),
        }
        return mk_extension(
            self._nid("plonk"),
            family=FF_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("finite_field.plonk",),
            payload_schema=FF_PLONK_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(args),
            range=span,
        )


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class FiniteFieldPrinter:
    """Deterministic printer for finite-field / circuit constraint ASTs."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        if style not in {PrintStyle.ASCII, PrintStyle.UNICODE}:
            raise SyntaxContractError(
                f"print style must be 'ascii' or 'unicode'; got {style!r}"
            )
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            return self._print_node(node.root, _Prec.BOTTOM)
        if not isinstance(node, LogicNode):
            raise SyntaxContractError("print requires a LogicNode or TypedExpression")
        return self._print_node(node, _Prec.BOTTOM)

    def _op(self, ascii_form: str, unicode_form: str) -> str:
        return unicode_form if self.style == PrintStyle.UNICODE else ascii_form

    def _print_node(self, node: LogicNode, parent_prec: int) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return "true"
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return "false"
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            left = self._print_node(node.arguments[0], _Prec.AND)
            right = self._print_node(node.arguments[1], _Prec.AND)
            text = f"{left} {self._op('and', '∧')} {right}"
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, parent_prec)
        if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
            return str(node.symbol or node.metadata.get("literal") or "?")
        if kind is NodeKind.VARIABLE or kind == NodeKind.VARIABLE.value:
            return str(node.symbol or "?")
        raise SyntaxContractError(
            f"cannot print node kind "
            f"{kind.value if isinstance(kind, NodeKind) else kind}"
        )

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        ext = node.extension
        if ext is None:
            raise SyntaxContractError("EXTENSION node missing extension payload")
        schema = ext.payload_schema
        payload = dict(ext.payload)
        children = list(ext.children)

        if schema == FF_MODULUS_PAYLOAD_SCHEMA:
            return f"mod({payload['modulus']})"

        if schema == FF_FIELD_EQ_PAYLOAD_SCHEMA:
            left = self._print_node(children[0], _Prec.EQ)
            right = self._print_node(children[1], _Prec.EQ)
            text = f"{left} == {right}"
            return self._paren(text, _Prec.EQ, parent_prec)

        if schema == FF_FIELD_OP_PAYLOAD_SCHEMA:
            kind = str(payload.get("kind"))
            if kind == FieldOpKind.NEG.value:
                inner = self._print_node(children[0], _Prec.UNARY)
                return self._paren(f"-{inner}", _Prec.UNARY, parent_prec)
            if kind == FieldOpKind.INV.value:
                inner = self._print_node(children[0], _Prec.BOTTOM)
                return f"inv({inner})"
            op_map = {
                FieldOpKind.ADD.value: "+",
                FieldOpKind.SUB.value: "-",
                FieldOpKind.MUL.value: "*",
                FieldOpKind.DIV.value: "/",
            }
            op = op_map.get(kind, kind)
            prec = _Prec.ADD if kind in {FieldOpKind.ADD.value, FieldOpKind.SUB.value} else _Prec.MUL
            left = self._print_node(children[0], prec)
            right = self._print_node(children[1], prec + 1)
            return self._paren(f"{left} {op} {right}", prec, parent_prec)

        if schema == FF_RANGE_PAYLOAD_SCHEMA:
            term = self._print_node(children[0], _Prec.BOTTOM)
            return f"range({term}, {payload['low']}, {payload['high']})"

        if schema == FF_BITS_PAYLOAD_SCHEMA:
            term = self._print_node(children[0], _Prec.BOTTOM)
            return f"bits({term}, {payload['bit_width']})"

        if schema == FF_R1CS_PAYLOAD_SCHEMA:
            a = self._print_node(children[0], _Prec.BOTTOM)
            b = self._print_node(children[1], _Prec.BOTTOM)
            c = self._print_node(children[2], _Prec.BOTTOM)
            return f"r1cs({a}, {b}, {c})"

        if schema == FF_PLONK_PAYLOAD_SCHEMA:
            parts = [self._print_node(c, _Prec.BOTTOM) for c in children]
            return f"plonk({', '.join(parts)})"

        if schema == FF_BITVECTOR_OP_PAYLOAD_SCHEMA:
            kind = str(payload.get("kind"))
            left = self._print_node(children[0], _Prec.BOTTOM)
            right = self._print_node(children[1], _Prec.BOTTOM)
            return f"{kind}({left}, {right})"

        if schema == FF_LITERAL_PAYLOAD_SCHEMA:
            lit = payload["literal"]
            if payload.get("literal_kind") == "bitvector":
                return f"bv {lit}"
            return str(lit)

        if schema == FF_WIRE_PAYLOAD_SCHEMA:
            return str(payload.get("name") or "w")

        raise SyntaxContractError(
            f"cannot print extension schema {schema!r}"
        )


# ---------------------------------------------------------------------------
# Parser facade
# ---------------------------------------------------------------------------


def _extract_profile(value: object) -> FiniteFieldConstraintProfile | None:
    if value is None:
        return None
    if isinstance(value, FiniteFieldConstraintProfile):
        return value
    if isinstance(value, Mapping):
        return FiniteFieldConstraintProfile.from_dict(value)
    return None


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:ff:1",
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind,
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if token.kind != TokenKind.EOF.value
    )
    covered = [token.range for token in tokens if token.kind != TokenKind.EOF.value]
    holes: list[LogicCSTNode] = []
    cursor = 0
    for item in sorted(covered, key=lambda value: value.start):
        if item.start > cursor:
            holes.append(
                LogicCSTNode(
                    node_id=f"node:gap:{cursor}:{item.start}",
                    kind="gap",
                    range=SourceRange(start=cursor, end=item.start),
                    role=CSTNodeRole.GAP,
                )
            )
        cursor = max(cursor, item.end)
    if cursor < document.byte_length:
        holes.append(
            LogicCSTNode(
                node_id=f"node:gap:{cursor}:{document.byte_length}",
                kind="gap",
                range=SourceRange(start=cursor, end=document.byte_length),
                role=CSTNodeRole.GAP,
            )
        )
    leaves = tuple(sorted((*children, *holes), key=lambda node: node.range.start))
    if not leaves and document.byte_length == 0:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=(),
        )
    else:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=leaves,
        )
    return LogicCST(
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_from_node(node: LogicNode) -> list[SurfaceASTRef]:
    refs: list[SurfaceASTRef] = []
    seq = [0]

    def walk(n: LogicNode) -> str:
        seq[0] += 1
        node_id = n.node_id if n.node_id else f"ast:{seq[0]}"
        child_ids: list[str] = []
        for child in n.arguments:
            child_ids.append(walk(child))
        if n.extension is not None:
            for child in n.extension.children:
                child_ids.append(walk(child))
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=safe_kind,
                range=span,
                child_ids=tuple(child_ids),
                metadata=meta,
            )
        )
        return node_id

    walk(node)
    return refs


def _signature_for_formula(
    root: LogicNode,
    profile: FiniteFieldConstraintProfile,
) -> LogicSignature:
    del root  # signature is profile-driven; root is available for future symbol harvest
    sorts: list[LogicSort] = [INDIVIDUAL_SORT]
    if profile.field is not None:
        sorts.append(FIELD_SORT)
    if profile.bitvector is not None:
        assert isinstance(profile.bitvector.bit_width, BitWidthIdentity)
        sorts.append(profile.bitvector.bit_width.sort())
    return LogicSignature(
        signature_id=f"sig:finite_field:{profile.profile_id}",
        family=FF_FAMILY_ID,
        profile=profile.profile_id,
        sorts=tuple(sorts),
        symbols=(),
        features=("finite_field_constraint", "arithmetic", "circuit"),
    )


class FiniteFieldParser:
    """Notation parser for finite-field / bitvector / ZK constraint syntax.

    Interface: ``FiniteFieldConstraintLogic@1``.
    """

    interface: ClassVar[str] = FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE
    notation_id: ClassVar[str] = FF_NOTATION_ID
    notation_version: ClassVar[str] = FF_NOTATION_VERSION

    def __init__(
        self,
        profile: FiniteFieldConstraintProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(
            profile, FiniteFieldConstraintProfile
        ):
            raise SyntaxContractError(
                "profile must be a FiniteFieldConstraintProfile"
            )
        self.profile = profile
        self.printer = FiniteFieldPrinter(style=print_style)
        self._lexer = BoundedLexer(keywords=_FF_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("finite_field_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:ff:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: FiniteFieldConstraintProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:ff:1",
        expression_id: str = "expr:ff:1",
    ) -> FiniteFieldParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message=(
                    "finite-field constraint parse requires a "
                    "FiniteFieldConstraintProfile"
                ),
                range=document.full_range(),
                remediation="Pass profile=profile_r1cs() or profile_bitvector()",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE},
            )
            return FiniteFieldParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:ff:lex:{index + 1}",
                    code=(
                        CODE_UNKNOWN_CHARACTER
                        if "unknown" in item.code
                        else (
                            CODE_LEXER_ERROR
                            if item.code.startswith("lexer.")
                            else item.code
                        )
                    ),
                    message=item.message,
                    severity=item.severity,
                    range=item.range,
                    remediation=item.remediation
                    or "Unknown characters no longer disappear; fix or remove them",
                    metadata={"lexer_code": item.code},
                )
                for index, item in enumerate(lex_result.diagnostics)
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=promoted,
                metadata={"interface": FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE},
            )
            return FiniteFieldParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _FFParserEngine(
            document=document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)

        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return FiniteFieldParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        printed = self.printer.print(root)
        extracted = extract_constraint_identities(root)
        identities = {
            **prof.identities(),
            "extracted": extracted,
        }
        signature = _signature_for_formula(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=FF_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            cst=cst,
            surface_ast=surface,
            diagnostics=all_diags,
            metadata={
                "interface": FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE,
                "profile": prof.to_dict(),
                "identities": identities,
                "printed": printed,
            },
        )
        return FiniteFieldParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            identities=identities,
        )


class FiniteFieldConstraintLogic:
    """Facade for ``FiniteFieldConstraintLogic@1``."""

    interface: ClassVar[str] = FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE

    def __init__(
        self,
        profile: FiniteFieldConstraintProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_r1cs()
        self.parser = FiniteFieldParser(self.profile, print_style=print_style)
        self.printer = FiniteFieldPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> FiniteFieldParseResult:
        document_id = str(kwargs.pop("document_id", "doc:ff:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:ff:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:ff:1"))
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise FiniteFieldParseError(
                "finite-field constraint parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def attach_evidence(
        self,
        result: FiniteFieldParseResult,
        evidence: FiniteFieldEvidenceContract,
        *,
        document_id: str = "doc:ff:1",
    ) -> FiniteFieldLoweringReceipt:
        """Attach evidence while retaining authority ceilings."""

        if result.profile is None:
            raise FiniteFieldParseError(
                "cannot attach evidence without a profile on the parse result"
            )
        retained = retain_authority_ceiling(evidence)
        identities = dict(result.identities) or result.profile.identities()
        authorizes = bool(retained.get("is_zk_proof"))
        return FiniteFieldLoweringReceipt(
            document_id=document_id,
            profile_id=result.profile.profile_id,
            identities=identities,
            evidence=retained,
            authorizes_zk_proof=authorizes,
        )


def parse_finite_field(
    text: str,
    profile: FiniteFieldConstraintProfile | None = None,
    **kwargs: Any,
) -> FiniteFieldParseResult:
    """Parse finite-field / circuit constraint *text* under *profile*."""

    logic = FiniteFieldConstraintLogic(profile or profile_r1cs())
    return logic.parse_text(text, **kwargs)


def print_finite_field(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return FiniteFieldPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: FiniteFieldConstraintProfile | None = None,
) -> tuple[FiniteFieldParseResult, FiniteFieldParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_r1cs()
    first = parse_finite_field(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_finite_field(first.root)
    second = parse_finite_field(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "FINITE_FIELD_CONSTRAINT_LOGIC_INTERFACE",
    "FINITE_FIELD_PROFILE_INTERFACE",
    "BITVECTOR_PROFILE_INTERFACE",
    "ZK_CIRCUIT_PROFILE_INTERFACE",
    "FF_FAMILY_ID",
    "FF_NOTATION_ID",
    "AuthorityPromotionError",
    "BitWidthIdentity",
    "BitvectorOpKind",
    "BitvectorProfile",
    "BoundednessKind",
    "CircuitIdentity",
    "ConstraintSystemKind",
    "EvidenceAuthority",
    "EvidenceSource",
    "FieldOpKind",
    "FiniteFieldConstraintLogic",
    "FiniteFieldConstraintProfile",
    "FiniteFieldEvidenceContract",
    "FiniteFieldLoweringReceipt",
    "FiniteFieldParseError",
    "FiniteFieldParseResult",
    "FiniteFieldParser",
    "FiniteFieldPrinter",
    "FiniteFieldProfile",
    "ModulusIdentity",
    "PrintStyle",
    "RangeIdentity",
    "ZKCircuitProfile",
    "arithmetic_solver_evidence_contract",
    "cryptographic_zk_evidence_contract",
    "extract_constraint_identities",
    "finite_field_semantic_identity",
    "is_probable_prime",
    "parse_finite_field",
    "parse_print_parse",
    "plonk_checker_evidence_contract",
    "print_finite_field",
    "profile_bitvector",
    "profile_finite_field",
    "profile_finite_field_constraint_mixed",
    "profile_plonk",
    "profile_r1cs",
    "r1cs_checker_evidence_contract",
    "retain_authority_ceiling",
    "simulated_zkp_evidence_contract",
    "smt_bitvector_evidence_contract",
]

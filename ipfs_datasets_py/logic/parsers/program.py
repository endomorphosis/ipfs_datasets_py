"""Hoare, contract, dynamic-logic, and verification-condition syntax (LFP-031).

Interfaces:

* ``ProgramLogicSyntax@1`` — parse/print/elaborate for Hoare triples, program
  contracts (pre/postconditions, modifies/frames, loop invariants/variants),
  program-indexed dynamic logic, and source-mapped surface forms over the
  shared software-verification program/contract IRs
* ``VerificationConditionBridge@1`` — deterministic lowering of a closed
  program-logic document to source-bound weakest-precondition /
  verification-condition obligations, with explicit binding and state versions

Namespace rules (fail-closed):

* Semantic family is always ``program`` (``dynamic_logic`` remains a profile /
  alias over program; never a second family).
* ``verification_condition`` is a *view role*, never a semantic family ID.
* Binding and program-state schema versions are explicit on every document and
  bridge artifact.
* Unsupported effects and incomplete loops become *obligations* (proof targets),
  never silent path assumptions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.software_verification.contracts import (
    PROGRAM_CONTRACT_SCHEMA_VERSION,
    ContractClause,
    ContractClauseKind,
    ContractValidationError,
    DynamicLogicExit,
    DynamicLogicFormula,
    DynamicLogicModality,
    DynamicProgramKind,
    ExceptionalPostcondition,
    FrameCondition,
    HoareTriple,
    LoopContract,
    ProgramContract,
)
from ipfs_datasets_py.logic.software_verification.program import (
    PROGRAM_IR_SCHEMA_VERSION,
    EffectSummary,
    ProgramIR,
    ProgramValidationError,
    Purity,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    VC_SCHEMA_VERSION,
    VC_SET_SCHEMA_VERSION,
    LoopVariantPolicy,
    SourceConstructKind,
    UnsupportedEffect,
    UnsupportedEffectKind,
    VCRuleKind,
    VCValidationError,
    VerificationConditionGenerator,
    VerificationConditionSet,
    VerificationObligation,
    WeakestPrecondition,
    generate_verification_conditions,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROGRAM_LOGIC_SYNTAX_INTERFACE: Final = "ProgramLogicSyntax@1"
VERIFICATION_CONDITION_BRIDGE_INTERFACE: Final = "VerificationConditionBridge@1"
PROGRAM_LOGIC_NOTATION_ID: Final = "canonical_program_logic"
PROGRAM_LOGIC_NOTATION_VERSION: Final = "1.0.0"
PROGRAM_LOGIC_PROFILE_ID: Final = "dynamic_hoare"
PROGRAM_LOGIC_FAMILY_ID: Final = "program"
PROGRAM_LOGIC_MODULE_VERSION: Final = "1.0.0"
PROGRAM_LOGIC_DOCUMENT_SCHEMA: Final = "program-logic-document/v1"
PROGRAM_LOGIC_BINDING_VERSION: Final = "program-binding/v1"
PROGRAM_LOGIC_STATE_VERSION: Final = "program-state/v1"
PROGRAM_LOGIC_SOURCE_MAP_SCHEMA: Final = "program-logic.source-map/v1"
PROGRAM_LOGIC_SURFACE_SCHEMA: Final = "program-logic.surface/v1"
VC_BRIDGE_SCHEMA: Final = "verification-condition-bridge/v1"
VC_BRIDGE_RESULT_SCHEMA: Final = "verification-condition-bridge-result/v1"
PROGRAM_LOGIC_IDENTITY_DOMAIN: Final = "logic.parsers.program-logic"
VC_VIEW_ROLE: Final = "verification_condition"
DYNAMIC_LOGIC_PROFILE_ID: Final = "dynamic_logic"

# Stable diagnostic codes.
CODE_INVALID_DOCUMENT: Final = "program.invalid_document"
CODE_MISSING_PROGRAM: Final = "program.missing_program_ir"
CODE_IDENTITY_MISMATCH: Final = "program.identity_mismatch"
CODE_EMPTY_INPUT: Final = "program.empty_input"
CODE_MALFORMED_JSON: Final = "program.malformed_json"
CODE_INVALID_CONTRACT: Final = "program.invalid_contract"
CODE_INVALID_HOARE: Final = "program.invalid_hoare"
CODE_INVALID_DYNAMIC: Final = "program.invalid_dynamic_logic"
CODE_INVALID_LOOP: Final = "program.invalid_loop"
CODE_UNSUPPORTED_EFFECT: Final = "program.unsupported_effect"
CODE_UNSUPPORTED_LOOP: Final = "program.unsupported_loop"
CODE_FAMILY_NAMESPACE: Final = "program.invalid_family_namespace"
CODE_VERSION_MISMATCH: Final = "program.version_mismatch"
CODE_SOURCE_MAP: Final = "program.missing_source_map"
CODE_BRIDGE: Final = "program.bridge_error"

_ALL_PROGRAM_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_INVALID_DOCUMENT,
        CODE_MISSING_PROGRAM,
        CODE_IDENTITY_MISMATCH,
        CODE_EMPTY_INPUT,
        CODE_MALFORMED_JSON,
        CODE_INVALID_CONTRACT,
        CODE_INVALID_HOARE,
        CODE_INVALID_DYNAMIC,
        CODE_INVALID_LOOP,
        CODE_UNSUPPORTED_EFFECT,
        CODE_UNSUPPORTED_LOOP,
        CODE_FAMILY_NAMESPACE,
        CODE_VERSION_MISMATCH,
        CODE_SOURCE_MAP,
        CODE_BRIDGE,
    }
)

# Surface constructs that are declaration-only or unsupported under this frontend.
UNSUPPORTED_LOOP_CONSTRUCTS: Final[frozenset[str]] = frozenset(
    {
        "foreach",
        "forall_loop",
        "parallel_for",
        "unbounded_recursion",
        "goto_loop",
        "exception_loop",
        "async_loop",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_HOARE_SURFACE_RE = re.compile(
    r"^\s*\{(?P<pre>.+?)\}\s*(?P<cmd>\S.*?)\s*\{(?P<post>.+?)\}\s*$",
    re.DOTALL,
)
_DYNAMIC_SURFACE_RE = re.compile(
    r"^\s*(?P<open>\[|<)(?P<prog>.+?)(?P<close>\]|>)\s*(?P<post>.+?)\s*$",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProgramLogicError(ValueError):
    """Raised when program-logic syntax is malformed or unsupported."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_INVALID_DOCUMENT,
        path: str = "",
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.remediation = remediation
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "remediation": self.remediation,
        }


class VerificationConditionBridgeError(ValueError):
    """Raised when VC bridge lowering fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_BRIDGE,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise ProgramLogicError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise ProgramLogicError(
            f"{label} must be a stable identifier",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramLogicError(
            f"{label} must be a mapping",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ProgramLogicError(
            f"{label} must be a sequence",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProgramLogicError(
            f"{label} must be a boolean",
            code=CODE_INVALID_DOCUMENT,
            path=label,
        )
    return value


def _reject_family_as_vc(family_id: str, *, path: str = "family_id") -> str:
    """Ensure verification_condition is never treated as a semantic family."""

    family = _text(family_id, path)
    normalized = family.casefold().replace("-", "_")
    if normalized in {"verification_condition", "vc", "verificationconditions"}:
        raise ProgramLogicError(
            "verification_condition is a view role, never a semantic family ID",
            code=CODE_FAMILY_NAMESPACE,
            path=path,
            remediation="Use family_id='program' with view_role='verification_condition'.",
        )
    return family


def _parse_program_ir(value: object, *, path: str = "program") -> ProgramIR:
    if isinstance(value, ProgramIR):
        return value
    try:
        return ProgramIR.from_dict(_mapping(value, path))
    except (TypeError, ValueError, ProgramValidationError) as error:
        raise ProgramLogicError(
            f"invalid ProgramIR payload: {error}",
            code=CODE_MISSING_PROGRAM,
            path=path,
        ) from error


def _parse_contract(value: object, *, path: str = "contract") -> ProgramContract:
    if isinstance(value, ProgramContract):
        return value
    try:
        return ProgramContract.from_dict(_mapping(value, path))
    except (TypeError, ValueError, ContractValidationError, ProgramValidationError) as error:
        raise ProgramLogicError(
            f"invalid ProgramContract: {error}",
            code=CODE_INVALID_CONTRACT,
            path=path,
        ) from error


def _parse_loop(value: object, *, path: str = "loop") -> LoopContract:
    if isinstance(value, LoopContract):
        return value
    raw = _mapping(value, path)
    construct = str(raw.get("construct", raw.get("kind", ""))).casefold()
    if construct in UNSUPPORTED_LOOP_CONSTRUCTS:
        raise ProgramLogicError(
            f"unsupported loop construct {construct!r}",
            code=CODE_UNSUPPORTED_LOOP,
            path=path,
            remediation=(
                "Supply a controlled LoopContract with invariants; "
                "unsupported constructs become bridge obligations, not assumptions."
            ),
        )
    try:
        return LoopContract.from_dict(raw)
    except (TypeError, ValueError, ContractValidationError, ProgramValidationError) as error:
        raise ProgramLogicError(
            f"invalid LoopContract: {error}",
            code=CODE_INVALID_LOOP,
            path=path,
        ) from error


def _parse_hoare(value: object, *, path: str = "hoare") -> HoareTriple:
    if isinstance(value, HoareTriple):
        return value
    try:
        return HoareTriple.from_dict(_mapping(value, path))
    except (TypeError, ValueError, ContractValidationError, ProgramValidationError) as error:
        raise ProgramLogicError(
            f"invalid HoareTriple: {error}",
            code=CODE_INVALID_HOARE,
            path=path,
        ) from error


def _parse_dynamic(value: object, *, path: str = "dynamic") -> DynamicLogicFormula:
    if isinstance(value, DynamicLogicFormula):
        return value
    try:
        return DynamicLogicFormula.from_dict(_mapping(value, path))
    except (TypeError, ValueError, ContractValidationError, ProgramValidationError) as error:
        raise ProgramLogicError(
            f"invalid DynamicLogicFormula: {error}",
            code=CODE_INVALID_DYNAMIC,
            path=path,
        ) from error


# ---------------------------------------------------------------------------
# Surface syntax forms (text-friendly, elaborate into IR records)
# ---------------------------------------------------------------------------


class SurfaceKind(StrEnum):
    """Kind of compact surface form admitted by ProgramLogicSyntax@1."""

    HOARE = "hoare"
    DYNAMIC_BOX = "dynamic_box"
    DYNAMIC_DIAMOND = "dynamic_diamond"
    MODIFIES = "modifies"
    REQUIRES = "requires"
    ENSURES = "ensures"
    INVARIANT = "invariant"
    VARIANT = "variant"


@dataclass(frozen=True, slots=True)
class SourceMapBinding:
    """Explicit source map binding for a surface or IR construct."""

    owner_id: str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = PROGRAM_LOGIC_SOURCE_MAP_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        sources = tuple(
            _identifier(item, "source_ref_ids item") for item in self.source_ref_ids
        )
        spans = tuple(_identifier(item, "span_ids item") for item in self.span_ids)
        if not sources and not spans:
            raise ProgramLogicError(
                f"source map for {self.owner_id!r} requires source_ref_ids or span_ids",
                code=CODE_SOURCE_MAP,
                path="source_map",
            )
        if len(sources) != len(set(sources)):
            raise ProgramLogicError(
                "source_ref_ids must not contain duplicates",
                code=CODE_SOURCE_MAP,
            )
        if len(spans) != len(set(spans)):
            raise ProgramLogicError(
                "span_ids must not contain duplicates",
                code=CODE_SOURCE_MAP,
            )
        object.__setattr__(self, "source_ref_ids", tuple(sorted(sources)))
        object.__setattr__(self, "span_ids", tuple(sorted(spans)))
        if self.schema_version != PROGRAM_LOGIC_SOURCE_MAP_SCHEMA:
            raise ProgramLogicError(
                f"unsupported source-map schema: {self.schema_version!r}",
                code=CODE_VERSION_MISMATCH,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceMapBinding":
        value = _mapping(value, "source map")
        return cls(
            owner_id=value.get("owner_id", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            schema_version=str(
                value.get("schema_version") or PROGRAM_LOGIC_SOURCE_MAP_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class SurfaceForm:
    """Compact surface form for Hoare / dynamic-logic / contract clauses.

    Surface forms are *not* proof results.  They elaborate into typed IR
    records (``HoareTriple``, ``DynamicLogicFormula``, ``FrameCondition``,
    ``ContractClause``) once expression and command identifiers are bound.
    """

    form_id: str
    kind: SurfaceKind | str
    text: str
    precondition_expression_id: str = ""
    postcondition_expression_id: str = ""
    program_ref_id: str = ""
    program_kind: DynamicProgramKind | str = DynamicProgramKind.COMMAND
    symbol_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PROGRAM_LOGIC_SURFACE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "form_id", _identifier(self.form_id, "form_id"))
        kind = (
            self.kind
            if isinstance(self.kind, SurfaceKind)
            else SurfaceKind(_text(self.kind, "kind"))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "text", _text(self.text, "text"))
        object.__setattr__(
            self,
            "precondition_expression_id",
            _text(
                self.precondition_expression_id,
                "precondition_expression_id",
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "postcondition_expression_id",
            _text(
                self.postcondition_expression_id,
                "postcondition_expression_id",
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "program_ref_id",
            _text(self.program_ref_id, "program_ref_id", optional=True),
        )
        program_kind = (
            self.program_kind
            if isinstance(self.program_kind, DynamicProgramKind)
            else DynamicProgramKind(
                _text(self.program_kind, "program_kind")
                if self.program_kind
                else DynamicProgramKind.COMMAND.value
            )
        )
        object.__setattr__(self, "program_kind", program_kind)
        symbols = tuple(_identifier(item, "symbol_ids item") for item in self.symbol_ids)
        if len(symbols) != len(set(symbols)):
            raise ProgramLogicError(
                "symbol_ids must not contain duplicates",
                code=CODE_INVALID_DOCUMENT,
                path="symbol_ids",
            )
        object.__setattr__(self, "symbol_ids", tuple(sorted(symbols)))
        sources = tuple(
            _identifier(item, "source_ref_ids item") for item in self.source_ref_ids
        )
        spans = tuple(_identifier(item, "span_ids item") for item in self.span_ids)
        if not sources and not spans:
            raise ProgramLogicError(
                f"surface form {self.form_id!r} must be source-mapped",
                code=CODE_SOURCE_MAP,
            )
        object.__setattr__(self, "source_ref_ids", tuple(sorted(sources)))
        object.__setattr__(self, "span_ids", tuple(sorted(spans)))
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise ProgramLogicError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_DOCUMENT,
            ) from error
        if self.schema_version != PROGRAM_LOGIC_SURFACE_SCHEMA:
            raise ProgramLogicError(
                f"unsupported surface schema: {self.schema_version!r}",
                code=CODE_VERSION_MISMATCH,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "form_id": self.form_id,
            "kind": self.kind.value,
            "postcondition_expression_id": self.postcondition_expression_id,
            "precondition_expression_id": self.precondition_expression_id,
            "program_kind": self.program_kind.value,
            "program_ref_id": self.program_ref_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "symbol_ids": list(self.symbol_ids),
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurfaceForm":
        value = _mapping(value, "surface form")
        return cls(
            form_id=value.get("form_id", ""),
            kind=value.get("kind", ""),
            text=value.get("text", ""),
            precondition_expression_id=value.get("precondition_expression_id", ""),
            postcondition_expression_id=value.get("postcondition_expression_id", ""),
            program_ref_id=value.get("program_ref_id", ""),
            program_kind=value.get("program_kind", DynamicProgramKind.COMMAND.value),
            symbol_ids=tuple(value.get("symbol_ids", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version") or PROGRAM_LOGIC_SURFACE_SCHEMA
            ),
        )

    def elaborate_hoare(self, *, triple_id: str | None = None) -> HoareTriple:
        """Elaborate a Hoare surface form into a typed triple."""

        if self.kind is not SurfaceKind.HOARE:
            raise ProgramLogicError(
                f"surface form {self.form_id!r} is not a Hoare triple",
                code=CODE_INVALID_HOARE,
            )
        if not self.precondition_expression_id or not self.postcondition_expression_id:
            raise ProgramLogicError(
                "Hoare surface form requires bound pre/post expression ids",
                code=CODE_INVALID_HOARE,
            )
        if not self.program_ref_id:
            raise ProgramLogicError(
                "Hoare surface form requires program_ref_id (command id)",
                code=CODE_INVALID_HOARE,
            )
        return HoareTriple(
            triple_id=triple_id or f"hoare:{self.form_id}",
            command_id=self.program_ref_id,
            precondition_ids=(self.precondition_expression_id,),
            normal_postcondition_ids=(self.postcondition_expression_id,),
            source_ref_ids=self.source_ref_ids,
            span_ids=self.span_ids,
        )

    def elaborate_dynamic(self, *, formula_id: str | None = None) -> DynamicLogicFormula:
        """Elaborate a box/diamond surface form into dynamic logic."""

        if self.kind is SurfaceKind.DYNAMIC_BOX:
            modality = DynamicLogicModality.BOX
        elif self.kind is SurfaceKind.DYNAMIC_DIAMOND:
            modality = DynamicLogicModality.DIAMOND
        else:
            raise ProgramLogicError(
                f"surface form {self.form_id!r} is not a dynamic-logic formula",
                code=CODE_INVALID_DYNAMIC,
            )
        if not self.postcondition_expression_id or not self.program_ref_id:
            raise ProgramLogicError(
                "dynamic-logic surface form requires program_ref_id and postcondition",
                code=CODE_INVALID_DYNAMIC,
            )
        return DynamicLogicFormula(
            formula_id=formula_id or f"dl:{self.form_id}",
            modality=modality,
            program_kind=self.program_kind,
            program_ref_id=self.program_ref_id,
            postcondition_expression_id=self.postcondition_expression_id,
            exit=DynamicLogicExit.NORMAL,
            source_ref_ids=self.source_ref_ids,
            span_ids=self.span_ids,
        )

    def elaborate_frame(self) -> FrameCondition:
        """Elaborate a modifies surface form into a frame condition."""

        if self.kind is not SurfaceKind.MODIFIES:
            raise ProgramLogicError(
                f"surface form {self.form_id!r} is not a modifies clause",
                code=CODE_INVALID_CONTRACT,
            )
        return FrameCondition(
            readable_symbol_ids=(),
            writable_symbol_ids=self.symbol_ids,
            allows_all_reads=False,
            allows_all_writes=False,
        )

    def elaborate_clause(
        self,
        *,
        clause_id: str | None = None,
        kind: ContractClauseKind | None = None,
    ) -> ContractClause:
        """Elaborate a requires/ensures/invariant/variant clause."""

        kind_map = {
            SurfaceKind.REQUIRES: ContractClauseKind.PRECONDITION,
            SurfaceKind.ENSURES: ContractClauseKind.POSTCONDITION,
            SurfaceKind.INVARIANT: ContractClauseKind.LOOP_INVARIANT,
            SurfaceKind.VARIANT: ContractClauseKind.LOOP_VARIANT,
        }
        if kind is None:
            if self.kind not in kind_map:
                raise ProgramLogicError(
                    f"surface form {self.form_id!r} is not a contract clause",
                    code=CODE_INVALID_CONTRACT,
                )
            kind = kind_map[self.kind]
        expression_id = (
            self.precondition_expression_id
            if kind is ContractClauseKind.PRECONDITION
            else self.postcondition_expression_id or self.precondition_expression_id
        )
        if not expression_id:
            raise ProgramLogicError(
                "contract clause surface form requires a bound expression id",
                code=CODE_INVALID_CONTRACT,
            )
        return ContractClause(
            clause_id=clause_id or f"clause:{self.form_id}",
            kind=kind,
            expression_id=expression_id,
            statement=self.text,
            source_ref_ids=self.source_ref_ids,
            span_ids=self.span_ids,
        )


def parse_hoare_surface(
    text: str,
    *,
    form_id: str,
    precondition_expression_id: str,
    postcondition_expression_id: str,
    command_id: str,
    source_ref_ids: Sequence[str],
    span_ids: Sequence[str] = (),
) -> SurfaceForm:
    """Parse compact ``{P} C {Q}`` text into a source-mapped surface form."""

    if not isinstance(text, str) or not text.strip():
        raise ProgramLogicError(
            "Hoare surface text must be non-empty",
            code=CODE_EMPTY_INPUT,
        )
    match = _HOARE_SURFACE_RE.match(text)
    if match is None:
        raise ProgramLogicError(
            "Hoare surface must match '{P} C {Q}'",
            code=CODE_INVALID_HOARE,
            remediation="Use curly-brace Hoare triple notation with a command token.",
        )
    return SurfaceForm(
        form_id=form_id,
        kind=SurfaceKind.HOARE,
        text=text.strip(),
        precondition_expression_id=precondition_expression_id,
        postcondition_expression_id=postcondition_expression_id,
        program_ref_id=command_id,
        program_kind=DynamicProgramKind.COMMAND,
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
        attributes={
            "pre_surface": match.group("pre").strip(),
            "command_surface": match.group("cmd").strip(),
            "post_surface": match.group("post").strip(),
        },
    )


def parse_dynamic_surface(
    text: str,
    *,
    form_id: str,
    postcondition_expression_id: str,
    program_ref_id: str,
    source_ref_ids: Sequence[str],
    span_ids: Sequence[str] = (),
    program_kind: DynamicProgramKind | str = DynamicProgramKind.COMMAND,
) -> SurfaceForm:
    """Parse compact ``[α]P`` / ``<α>P`` dynamic-logic surface text."""

    if not isinstance(text, str) or not text.strip():
        raise ProgramLogicError(
            "dynamic-logic surface text must be non-empty",
            code=CODE_EMPTY_INPUT,
        )
    match = _DYNAMIC_SURFACE_RE.match(text)
    if match is None:
        raise ProgramLogicError(
            "dynamic-logic surface must match '[α]P' or '<α>P'",
            code=CODE_INVALID_DYNAMIC,
        )
    open_tok = match.group("open")
    close_tok = match.group("close")
    if open_tok == "[" and close_tok != "]":
        raise ProgramLogicError(
            "mismatched dynamic-logic brackets",
            code=CODE_INVALID_DYNAMIC,
        )
    if open_tok == "<" and close_tok != ">":
        raise ProgramLogicError(
            "mismatched dynamic-logic angles",
            code=CODE_INVALID_DYNAMIC,
        )
    kind = (
        SurfaceKind.DYNAMIC_BOX if open_tok == "[" else SurfaceKind.DYNAMIC_DIAMOND
    )
    return SurfaceForm(
        form_id=form_id,
        kind=kind,
        text=text.strip(),
        postcondition_expression_id=postcondition_expression_id,
        program_ref_id=program_ref_id,
        program_kind=program_kind,
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
        attributes={
            "program_surface": match.group("prog").strip(),
            "post_surface": match.group("post").strip(),
            "modality": "box" if kind is SurfaceKind.DYNAMIC_BOX else "diamond",
        },
    )


# ---------------------------------------------------------------------------
# Strongest-postcondition view (dual of WP; descriptive, not a solver claim)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrongestPostcondition:
    """Strongest-postcondition view attached to a command or block exit.

    SP is a typed *view concept* dual to WP.  It is not a proof result and does
    not claim solver authority.
    """

    sp_id: str
    function_id: str
    program_point_kind: SourceConstructKind | str
    program_point_id: str
    exit_kind: str
    precondition_expression_ids: tuple[str, ...] = ()
    postcondition_expression_ids: tuple[str, ...] = ()
    rule: VCRuleKind | str = VCRuleKind.SKIP
    parent_contract_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sp_id", _identifier(self.sp_id, "sp_id"))
        object.__setattr__(
            self, "function_id", _identifier(self.function_id, "function_id")
        )
        kind = (
            self.program_point_kind
            if isinstance(self.program_point_kind, SourceConstructKind)
            else SourceConstructKind(_text(self.program_point_kind, "program_point_kind"))
        )
        object.__setattr__(self, "program_point_kind", kind)
        object.__setattr__(
            self,
            "program_point_id",
            _identifier(self.program_point_id, "program_point_id"),
        )
        object.__setattr__(self, "exit_kind", _text(self.exit_kind, "exit_kind"))
        pre = tuple(
            _identifier(item, "precondition_expression_ids item")
            for item in self.precondition_expression_ids
        )
        post = tuple(
            _identifier(item, "postcondition_expression_ids item")
            for item in self.postcondition_expression_ids
        )
        object.__setattr__(self, "precondition_expression_ids", pre)
        object.__setattr__(self, "postcondition_expression_ids", post)
        rule = (
            self.rule
            if isinstance(self.rule, VCRuleKind)
            else VCRuleKind(_text(self.rule, "rule"))
        )
        object.__setattr__(self, "rule", rule)
        parent = self.parent_contract_id
        if parent:
            parent = _identifier(parent, "parent_contract_id")
        object.__setattr__(self, "parent_contract_id", parent)
        sources = tuple(
            _identifier(item, "source_ref_ids item") for item in self.source_ref_ids
        )
        spans = tuple(_identifier(item, "span_ids item") for item in self.span_ids)
        if not sources and not spans:
            raise ProgramLogicError(
                f"SP {self.sp_id!r} must be source-mapped",
                code=CODE_SOURCE_MAP,
            )
        object.__setattr__(self, "source_ref_ids", tuple(sorted(sources)))
        object.__setattr__(self, "span_ids", tuple(sorted(spans)))
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise ProgramLogicError(
                "SP attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_DOCUMENT,
            ) from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "exit_kind": self.exit_kind,
            "function_id": self.function_id,
            "parent_contract_id": self.parent_contract_id,
            "postcondition_expression_ids": list(self.postcondition_expression_ids),
            "precondition_expression_ids": list(self.precondition_expression_ids),
            "program_point_id": self.program_point_id,
            "program_point_kind": self.program_point_kind.value,
            "rule": self.rule.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "sp_id": self.sp_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StrongestPostcondition":
        value = _mapping(value, "strongest postcondition")
        return cls(
            sp_id=value.get("sp_id", ""),
            function_id=value.get("function_id", ""),
            program_point_kind=value.get("program_point_kind", ""),
            program_point_id=value.get("program_point_id", ""),
            exit_kind=value.get("exit_kind", ""),
            precondition_expression_ids=tuple(
                value.get("precondition_expression_ids", ())
            ),
            postcondition_expression_ids=tuple(
                value.get("postcondition_expression_ids", ())
            ),
            rule=value.get("rule", VCRuleKind.SKIP.value),
            parent_contract_id=value.get("parent_contract_id", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=value.get("attributes", {}),
        )

    @classmethod
    def from_weakest_precondition(cls, wp: WeakestPrecondition) -> "StrongestPostcondition":
        """Dualize a WP record into an SP view (swap assumption/consequent roles)."""

        if not isinstance(wp, WeakestPrecondition):
            raise ProgramLogicError(
                "from_weakest_precondition requires WeakestPrecondition",
                code=CODE_BRIDGE,
            )
        return cls(
            sp_id=f"sp:{wp.wp_id.removeprefix('wp:')}" if wp.wp_id.startswith("wp:") else f"sp:{wp.wp_id}",
            function_id=wp.function_id,
            program_point_kind=wp.program_point_kind,
            program_point_id=wp.program_point_id,
            exit_kind=wp.exit_kind,
            precondition_expression_ids=wp.assumption_expression_ids,
            postcondition_expression_ids=wp.consequent_expression_ids,
            rule=wp.rule,
            parent_contract_id=wp.parent_contract_id,
            source_ref_ids=wp.source_ref_ids,
            span_ids=wp.span_ids,
            attributes={"dual_of": wp.wp_id, "view": "strongest_postcondition"},
        )


# ---------------------------------------------------------------------------
# Program logic document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgramLogicDocument:
    """Closed program-logic document under ``ProgramLogicSyntax@1``.

    Carries a validated :class:`ProgramIR` together with contracts, loop
    contracts, Hoare triples, dynamic-logic formulas, and optional surface
    forms.  Binding and state schema versions are explicit and identity-
    relevant.
    """

    program: ProgramIR
    contracts: tuple[ProgramContract, ...] = ()
    loop_contracts: tuple[LoopContract, ...] = ()
    hoare_triples: tuple[HoareTriple, ...] = ()
    dynamic_formulas: tuple[DynamicLogicFormula, ...] = ()
    surfaces: tuple[SurfaceForm, ...] = ()
    source_maps: tuple[SourceMapBinding, ...] = ()
    notation_id: str = PROGRAM_LOGIC_NOTATION_ID
    notation_version: str = PROGRAM_LOGIC_NOTATION_VERSION
    profile_id: str = PROGRAM_LOGIC_PROFILE_ID
    family_id: str = PROGRAM_LOGIC_FAMILY_ID
    binding_version: str = PROGRAM_LOGIC_BINDING_VERSION
    state_version: str = PROGRAM_LOGIC_STATE_VERSION
    schema_version: str = PROGRAM_LOGIC_DOCUMENT_SCHEMA
    document_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.program, ProgramIR):
            raise ProgramLogicError(
                "program must be a ProgramIR",
                code=CODE_MISSING_PROGRAM,
            )
        contracts = tuple(
            item if isinstance(item, ProgramContract) else _parse_contract(item)
            for item in _sequence(self.contracts, "contracts")
        )
        loops = tuple(
            item if isinstance(item, LoopContract) else _parse_loop(item)
            for item in _sequence(self.loop_contracts, "loop_contracts")
        )
        triples = tuple(
            item if isinstance(item, HoareTriple) else _parse_hoare(item)
            for item in _sequence(self.hoare_triples, "hoare_triples")
        )
        formulas = tuple(
            item if isinstance(item, DynamicLogicFormula) else _parse_dynamic(item)
            for item in _sequence(self.dynamic_formulas, "dynamic_formulas")
        )
        surfaces = tuple(
            item
            if isinstance(item, SurfaceForm)
            else SurfaceForm.from_dict(_mapping(item, "surface"))
            for item in _sequence(self.surfaces, "surfaces")
        )
        source_maps = tuple(
            item
            if isinstance(item, SourceMapBinding)
            else SourceMapBinding.from_dict(_mapping(item, "source_map"))
            for item in _sequence(self.source_maps, "source_maps")
        )

        contract_ids = [item.contract_id for item in contracts]
        if len(contract_ids) != len(set(contract_ids)):
            raise ProgramLogicError(
                "duplicate contract identifiers",
                code=CODE_INVALID_CONTRACT,
            )
        loop_ids = [item.loop_id for item in loops]
        if len(loop_ids) != len(set(loop_ids)):
            raise ProgramLogicError(
                "duplicate loop contract identifiers",
                code=CODE_INVALID_LOOP,
            )
        triple_ids = [item.triple_id for item in triples]
        if len(triple_ids) != len(set(triple_ids)):
            raise ProgramLogicError(
                "duplicate Hoare triple identifiers",
                code=CODE_INVALID_HOARE,
            )
        formula_ids = [item.formula_id for item in formulas]
        if len(formula_ids) != len(set(formula_ids)):
            raise ProgramLogicError(
                "duplicate dynamic-logic formula identifiers",
                code=CODE_INVALID_DYNAMIC,
            )
        form_ids = [item.form_id for item in surfaces]
        if len(form_ids) != len(set(form_ids)):
            raise ProgramLogicError(
                "duplicate surface form identifiers",
                code=CODE_INVALID_DOCUMENT,
            )

        # Closed-world validation against the program IR.
        try:
            for contract in contracts:
                contract.validate_against(self.program)
            for loop in loops:
                loop.validate_against(self.program)
            for triple in triples:
                triple.validate_against(self.program)
            for formula in formulas:
                formula.validate_against(self.program)
        except ContractValidationError as error:
            raise ProgramLogicError(
                str(error),
                code=CODE_INVALID_CONTRACT,
            ) from error

        object.__setattr__(
            self,
            "contracts",
            tuple(sorted(contracts, key=lambda item: item.contract_id)),
        )
        object.__setattr__(
            self,
            "loop_contracts",
            tuple(sorted(loops, key=lambda item: item.loop_id)),
        )
        object.__setattr__(
            self,
            "hoare_triples",
            tuple(sorted(triples, key=lambda item: item.triple_id)),
        )
        object.__setattr__(
            self,
            "dynamic_formulas",
            tuple(sorted(formulas, key=lambda item: item.formula_id)),
        )
        object.__setattr__(
            self,
            "surfaces",
            tuple(sorted(surfaces, key=lambda item: item.form_id)),
        )
        object.__setattr__(
            self,
            "source_maps",
            tuple(sorted(source_maps, key=lambda item: item.owner_id)),
        )
        object.__setattr__(
            self, "notation_id", _text(self.notation_id, "notation_id")
        )
        object.__setattr__(
            self, "notation_version", _text(self.notation_version, "notation_version")
        )
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(
            self,
            "family_id",
            _reject_family_as_vc(self.family_id, path="family_id"),
        )
        if self.family_id != PROGRAM_LOGIC_FAMILY_ID:
            raise ProgramLogicError(
                f"program-logic family_id must be {PROGRAM_LOGIC_FAMILY_ID!r}, "
                f"got {self.family_id!r}",
                code=CODE_FAMILY_NAMESPACE,
                path="family_id",
            )
        object.__setattr__(
            self, "binding_version", _text(self.binding_version, "binding_version")
        )
        object.__setattr__(
            self, "state_version", _text(self.state_version, "state_version")
        )
        if self.binding_version != PROGRAM_LOGIC_BINDING_VERSION:
            raise ProgramLogicError(
                f"unsupported binding_version {self.binding_version!r}; "
                f"expected {PROGRAM_LOGIC_BINDING_VERSION!r}",
                code=CODE_VERSION_MISMATCH,
                path="binding_version",
            )
        if self.state_version != PROGRAM_LOGIC_STATE_VERSION:
            raise ProgramLogicError(
                f"unsupported state_version {self.state_version!r}; "
                f"expected {PROGRAM_LOGIC_STATE_VERSION!r}",
                code=CODE_VERSION_MISMATCH,
                path="state_version",
            )
        if self.schema_version != PROGRAM_LOGIC_DOCUMENT_SCHEMA:
            raise ProgramLogicError(
                f"unsupported program-logic schema: {self.schema_version!r}",
                code=CODE_VERSION_MISMATCH,
            )
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise ProgramLogicError(
                "document_id does not match canonical program-logic identity",
                code=CODE_IDENTITY_MISMATCH,
            )
        object.__setattr__(self, "document_id", computed.cid)

    @property
    def interface(self) -> str:
        return PROGRAM_LOGIC_SYNTAX_INTERFACE

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=PROGRAM_LOGIC_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Identity preimage: program + contracts + Hoare + dynamic + versions.

        ``verification_condition`` never appears as a family id.  The optional
        view role is recorded only under ``view_roles`` for audit.
        """

        return {
            "binding_version": self.binding_version,
            "contracts": [item.to_dict() for item in self.contracts],
            "dynamic_formulas": [item.to_dict() for item in self.dynamic_formulas],
            "family_id": self.family_id,
            "hoare_triples": [item.to_dict() for item in self.hoare_triples],
            "interface": PROGRAM_LOGIC_SYNTAX_INTERFACE,
            "loop_contracts": [item.to_dict() for item in self.loop_contracts],
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "profile_id": self.profile_id,
            "program": self.program.semantic_dict(),
            "program_id": self.program.program_id,
            "program_schema_version": PROGRAM_IR_SCHEMA_VERSION,
            "schema_version": self.schema_version,
            "source_maps": [item.to_dict() for item in self.source_maps],
            "state_version": self.state_version,
            "surfaces": [item.to_dict() for item in self.surfaces],
            "view_roles": [VC_VIEW_ROLE],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["document_id"] = self.document_id
        payload["program"] = self.program.to_dict()
        return payload

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramLogicDocument":
        value = _mapping(value, "program logic document")
        # Reject payloads that claim VC as a family id.
        if "family_id" in value:
            _reject_family_as_vc(str(value.get("family_id") or ""), path="family_id")
        raw_program = value.get("program") or value.get("program_ir")
        if raw_program is None and (
            "functions" in value or "commands" in value or "symbols" in value
        ):
            # Bare ProgramIR payload with optional sibling contract fields.
            program_payload = {
                key: item
                for key, item in value.items()
                if key
                not in {
                    "contracts",
                    "loop_contracts",
                    "hoare_triples",
                    "dynamic_formulas",
                    "surfaces",
                    "source_maps",
                    "notation_id",
                    "notation_version",
                    "profile_id",
                    "family_id",
                    "binding_version",
                    "state_version",
                    "schema_version",
                    "document_id",
                    "interface",
                    "view_roles",
                    "program_id",
                    "program_schema_version",
                }
            }
            raw_program = program_payload
        if raw_program is None:
            raise ProgramLogicError(
                "program-logic document requires program or program_ir",
                code=CODE_MISSING_PROGRAM,
            )
        program = _parse_program_ir(raw_program)
        return cls(
            program=program,
            contracts=tuple(value.get("contracts", ())),
            loop_contracts=tuple(value.get("loop_contracts", ())),
            hoare_triples=tuple(value.get("hoare_triples", ())),
            dynamic_formulas=tuple(value.get("dynamic_formulas", ())),
            surfaces=tuple(value.get("surfaces", ())),
            source_maps=tuple(value.get("source_maps", ())),
            notation_id=str(value.get("notation_id") or PROGRAM_LOGIC_NOTATION_ID),
            notation_version=str(
                value.get("notation_version") or PROGRAM_LOGIC_NOTATION_VERSION
            ),
            profile_id=str(value.get("profile_id") or PROGRAM_LOGIC_PROFILE_ID),
            family_id=str(value.get("family_id") or PROGRAM_LOGIC_FAMILY_ID),
            binding_version=str(
                value.get("binding_version") or PROGRAM_LOGIC_BINDING_VERSION
            ),
            state_version=str(
                value.get("state_version") or PROGRAM_LOGIC_STATE_VERSION
            ),
            schema_version=str(
                value.get("schema_version") or PROGRAM_LOGIC_DOCUMENT_SCHEMA
            ),
            document_id=str(value.get("document_id") or ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "ProgramLogicDocument":
        if not isinstance(text, str) or not text.strip():
            raise ProgramLogicError(
                "JSON program-logic source must be non-empty text",
                code=CODE_EMPTY_INPUT,
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProgramLogicError(
                f"malformed program-logic JSON: {error}",
                code=CODE_MALFORMED_JSON,
            ) from error
        if not isinstance(payload, Mapping):
            raise ProgramLogicError(
                "program-logic JSON root must be an object",
                code=CODE_MALFORMED_JSON,
            )
        return cls.from_dict(payload)

    def elaborate(self) -> ProgramIR:
        """Return the embedded ProgramIR (already validated)."""

        return self.program

    def contract_for(self, function_id: str) -> ProgramContract | None:
        for contract in self.contracts:
            if contract.function_id == function_id:
                return contract
        return None

    def loops_for(self, function_id: str) -> tuple[LoopContract, ...]:
        return tuple(
            item for item in self.loop_contracts if item.function_id == function_id
        )


# ---------------------------------------------------------------------------
# Verification-condition bridge
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationConditionBridgeResult:
    """Bridge lowering result with explicit versions and view-role namespace.

    ``family_id`` is always ``program``.  ``view_role`` is always
    ``verification_condition``.  Unsupported effects/loops are promoted to
    obligations and are never recorded as discharged assumptions.
    """

    vc_sets: tuple[VerificationConditionSet, ...]
    strongest_postconditions: tuple[StrongestPostcondition, ...]
    document_id: str
    program_id: str
    binding_version: str
    state_version: str
    family_id: str = PROGRAM_LOGIC_FAMILY_ID
    view_role: str = VC_VIEW_ROLE
    profile_id: str = PROGRAM_LOGIC_PROFILE_ID
    interface: str = VERIFICATION_CONDITION_BRIDGE_INTERFACE
    schema_version: str = VC_BRIDGE_RESULT_SCHEMA
    vc_schema_version: str = VC_SET_SCHEMA_VERSION
    generator_schema_version: str = VC_SCHEMA_VERSION
    promoted_unsupported_obligation_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        vc_sets = tuple(
            item
            if isinstance(item, VerificationConditionSet)
            else VerificationConditionSet.from_dict(_mapping(item, "vc_set"))
            for item in self.vc_sets
        )
        sps = tuple(
            item
            if isinstance(item, StrongestPostcondition)
            else StrongestPostcondition.from_dict(_mapping(item, "sp"))
            for item in self.strongest_postconditions
        )
        object.__setattr__(self, "vc_sets", vc_sets)
        object.__setattr__(
            self,
            "strongest_postconditions",
            tuple(sorted(sps, key=lambda item: item.sp_id)),
        )
        object.__setattr__(
            self, "document_id", _text(self.document_id, "document_id", optional=True)
        )
        object.__setattr__(self, "program_id", _identifier(self.program_id, "program_id"))
        object.__setattr__(
            self, "binding_version", _text(self.binding_version, "binding_version")
        )
        object.__setattr__(
            self, "state_version", _text(self.state_version, "state_version")
        )
        family = _reject_family_as_vc(self.family_id, path="family_id")
        if family != PROGRAM_LOGIC_FAMILY_ID:
            raise VerificationConditionBridgeError(
                f"bridge family_id must be {PROGRAM_LOGIC_FAMILY_ID!r}",
                code=CODE_FAMILY_NAMESPACE,
            )
        object.__setattr__(self, "family_id", family)
        view = _text(self.view_role, "view_role")
        if view != VC_VIEW_ROLE:
            raise VerificationConditionBridgeError(
                f"bridge view_role must be {VC_VIEW_ROLE!r}",
                code=CODE_FAMILY_NAMESPACE,
            )
        object.__setattr__(self, "view_role", view)
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if self.interface != VERIFICATION_CONDITION_BRIDGE_INTERFACE:
            raise VerificationConditionBridgeError(
                f"unsupported bridge interface: {self.interface!r}",
                code=CODE_BRIDGE,
            )
        if self.schema_version != VC_BRIDGE_RESULT_SCHEMA:
            raise VerificationConditionBridgeError(
                f"unsupported bridge result schema: {self.schema_version!r}",
                code=CODE_VERSION_MISMATCH,
            )
        promoted = tuple(
            _identifier(item, "promoted_unsupported_obligation_ids item")
            for item in self.promoted_unsupported_obligation_ids
        )
        object.__setattr__(self, "promoted_unsupported_obligation_ids", promoted)
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise VerificationConditionBridgeError(
                "attributes must be immutable JSON-compatible data"
            ) from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binding_version": self.binding_version,
            "document_id": self.document_id,
            "family_id": self.family_id,
            "generator_schema_version": self.generator_schema_version,
            "interface": self.interface,
            "profile_id": self.profile_id,
            "program_id": self.program_id,
            "promoted_unsupported_obligation_ids": list(
                self.promoted_unsupported_obligation_ids
            ),
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "strongest_postconditions": [
                item.to_dict() for item in self.strongest_postconditions
            ],
            "vc_schema_version": self.vc_schema_version,
            "vc_sets": [item.to_dict() for item in self.vc_sets],
            "view_role": self.view_role,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationConditionBridgeResult":
        value = _mapping(value, "vc bridge result")
        if "family_id" in value:
            _reject_family_as_vc(str(value.get("family_id") or ""), path="family_id")
        return cls(
            vc_sets=tuple(value.get("vc_sets", ())),
            strongest_postconditions=tuple(value.get("strongest_postconditions", ())),
            document_id=value.get("document_id", ""),
            program_id=value.get("program_id", ""),
            binding_version=value.get(
                "binding_version", PROGRAM_LOGIC_BINDING_VERSION
            ),
            state_version=value.get("state_version", PROGRAM_LOGIC_STATE_VERSION),
            family_id=value.get("family_id", PROGRAM_LOGIC_FAMILY_ID),
            view_role=value.get("view_role", VC_VIEW_ROLE),
            profile_id=value.get("profile_id", PROGRAM_LOGIC_PROFILE_ID),
            interface=value.get("interface", VERIFICATION_CONDITION_BRIDGE_INTERFACE),
            schema_version=value.get("schema_version", VC_BRIDGE_RESULT_SCHEMA),
            vc_schema_version=value.get("vc_schema_version", VC_SET_SCHEMA_VERSION),
            generator_schema_version=value.get(
                "generator_schema_version", VC_SCHEMA_VERSION
            ),
            promoted_unsupported_obligation_ids=tuple(
                value.get("promoted_unsupported_obligation_ids", ())
            ),
            attributes=value.get("attributes", {}),
        )

    def all_obligations(self) -> tuple[VerificationObligation, ...]:
        items: list[VerificationObligation] = []
        for vc_set in self.vc_sets:
            items.extend(vc_set.obligations)
        return tuple(items)

    def unsupported_effect_obligations(self) -> tuple[VerificationObligation, ...]:
        return tuple(
            item
            for item in self.all_obligations()
            if item.rule is VCRuleKind.UNSUPPORTED_EFFECT
        )


class VerificationConditionBridge:
    """Lower program-logic documents to VC sets (``VerificationConditionBridge@1``).

    Binding and state versions are copied from the document onto every bridge
    result.  Unsupported effects and incomplete loops are promoted to
    ``VCRuleKind.UNSUPPORTED_EFFECT`` obligations and are never treated as
    path assumptions.  The semantic family remains ``program``; VC is only a
    view role.
    """

    interface: ClassVar[str] = VERIFICATION_CONDITION_BRIDGE_INTERFACE
    schema_version: ClassVar[str] = VC_BRIDGE_SCHEMA
    family_id: ClassVar[str] = PROGRAM_LOGIC_FAMILY_ID
    view_role: ClassVar[str] = VC_VIEW_ROLE

    def __init__(
        self,
        *,
        loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
        require_source_maps: bool = True,
        promote_unsupported_to_obligations: bool = True,
    ) -> None:
        policy = (
            loop_variant_policy
            if isinstance(loop_variant_policy, LoopVariantPolicy)
            else LoopVariantPolicy(str(loop_variant_policy))
        )
        if not isinstance(require_source_maps, bool):
            raise VerificationConditionBridgeError("require_source_maps must be boolean")
        if not isinstance(promote_unsupported_to_obligations, bool):
            raise VerificationConditionBridgeError(
                "promote_unsupported_to_obligations must be boolean"
            )
        self.loop_variant_policy = policy
        self.require_source_maps = require_source_maps
        self.promote_unsupported_to_obligations = promote_unsupported_to_obligations
        self._generator = VerificationConditionGenerator(
            loop_variant_policy=policy,
            require_source_maps=require_source_maps,
        )

    def lower(
        self,
        document: ProgramLogicDocument | Mapping[str, Any],
        *,
        function_id: str | None = None,
    ) -> VerificationConditionBridgeResult:
        """Lower contracts in ``document`` to verification-condition view sets."""

        if isinstance(document, Mapping):
            document = ProgramLogicDocument.from_dict(document)
        if not isinstance(document, ProgramLogicDocument):
            raise VerificationConditionBridgeError(
                "lower requires ProgramLogicDocument or mapping"
            )
        if document.family_id != PROGRAM_LOGIC_FAMILY_ID:
            raise VerificationConditionBridgeError(
                "document family_id must remain 'program'",
                code=CODE_FAMILY_NAMESPACE,
            )

        contracts = document.contracts
        if function_id is not None:
            contracts = tuple(
                item for item in contracts if item.function_id == function_id
            )
            if not contracts:
                raise VerificationConditionBridgeError(
                    f"no contract for function {function_id!r}",
                    code=CODE_INVALID_CONTRACT,
                )
        if not contracts:
            raise VerificationConditionBridgeError(
                "program-logic document requires at least one contract to lower",
                code=CODE_INVALID_CONTRACT,
            )

        vc_sets: list[VerificationConditionSet] = []
        strongest: list[StrongestPostcondition] = []
        promoted_ids: list[str] = []

        for contract in contracts:
            loops = document.loops_for(contract.function_id)
            try:
                vc_set = self._generator.generate(
                    document.program, contract, loops
                )
            except (VCValidationError, ContractValidationError) as error:
                # Incomplete/unsupported loops become explicit obligations when
                # the generator refuses silent discharge.
                message = str(error)
                if "loop" in message.casefold() or "variant" in message.casefold():
                    vc_set = self._unsupported_loop_vc_set(
                        document=document,
                        contract=contract,
                        loops=loops,
                        reason=message,
                    )
                else:
                    raise VerificationConditionBridgeError(
                        f"VC generation failed: {error}",
                        code=CODE_BRIDGE,
                    ) from error

            if self.promote_unsupported_to_obligations:
                vc_set, new_ids = self._promote_unsupported_effects(vc_set, contract)
                promoted_ids.extend(new_ids)

            # Never treat unsupported effects as assumptions on any obligation.
            self._assert_unsupported_not_assumed(vc_set)

            vc_sets.append(vc_set)
            for wp in vc_set.weakest_preconditions:
                strongest.append(StrongestPostcondition.from_weakest_precondition(wp))

        return VerificationConditionBridgeResult(
            vc_sets=tuple(vc_sets),
            strongest_postconditions=tuple(strongest),
            document_id=document.document_id,
            program_id=document.program.program_id,
            binding_version=document.binding_version,
            state_version=document.state_version,
            family_id=PROGRAM_LOGIC_FAMILY_ID,
            view_role=VC_VIEW_ROLE,
            profile_id=document.profile_id,
            promoted_unsupported_obligation_ids=tuple(sorted(set(promoted_ids))),
            attributes={
                "contract_ids": [item.contract_id for item in contracts],
                "program_schema_version": PROGRAM_IR_SCHEMA_VERSION,
                "contract_schema_version": PROGRAM_CONTRACT_SCHEMA_VERSION,
            },
        )

    def _promote_unsupported_effects(
        self,
        vc_set: VerificationConditionSet,
        contract: ProgramContract,
    ) -> tuple[VerificationConditionSet, list[str]]:
        """Ensure every unsupported effect has a corresponding obligation."""

        existing = {
            (
                item.source_construct_kind.value
                if isinstance(item.source_construct_kind, SourceConstructKind)
                else str(item.source_construct_kind),
                item.source_construct_id,
                item.attributes.to_dict().get("unsupported_effect_id", ""),
            )
            for item in vc_set.obligations
            if item.rule is VCRuleKind.UNSUPPORTED_EFFECT
        }
        # Also index by construct alone for loose matching.
        existing_constructs = {
            (item.source_construct_kind, item.source_construct_id)
            for item in vc_set.obligations
            if item.rule is VCRuleKind.UNSUPPORTED_EFFECT
        }

        extra: list[VerificationObligation] = []
        promoted: list[str] = []
        for effect in vc_set.unsupported_effects:
            key = (
                effect.construct_kind.value
                if isinstance(effect.construct_kind, SourceConstructKind)
                else str(effect.construct_kind),
                effect.construct_id,
                effect.effect_id,
            )
            construct_key = (effect.construct_kind, effect.construct_id)
            # Prefer effect-id match; fall back if an obligation already covers construct.
            if key in existing or (
                construct_key in existing_constructs
                and any(
                    item.attributes.to_dict().get("unsupported_effect_id")
                    == effect.effect_id
                    for item in vc_set.obligations
                    if item.rule is VCRuleKind.UNSUPPORTED_EFFECT
                )
            ):
                continue
            # Create obligation with empty assumptions — never assume the effect.
            sources = contract.source_ref_ids
            spans = contract.span_ids
            obligation = VerificationObligation(
                obligation_id=(
                    f"vc:unsupported_effect:{effect.construct_kind.value}:"
                    f"{effect.construct_id}:{contract.contract_id}:{effect.effect_id}"
                )[:255],
                rule=VCRuleKind.UNSUPPORTED_EFFECT,
                parent_contract_id=contract.contract_id,
                function_id=contract.function_id,
                source_construct_kind=effect.construct_kind,
                source_construct_id=effect.construct_id,
                assumption_expression_ids=(),
                goal_expression_ids=(),
                generated_symbol_ids=(),
                path_condition_expression_ids=(),
                statement=(
                    f"Unsupported effect {effect.kind.value} at "
                    f"{effect.construct_id}: {effect.description}"
                ),
                source_ref_ids=sources,
                span_ids=spans,
                attributes={
                    "unsupported_effect_id": effect.effect_id,
                    "unsupported_kind": effect.kind.value
                    if isinstance(effect.kind, UnsupportedEffectKind)
                    else str(effect.kind),
                    "symbol_ids": list(effect.symbol_ids),
                    "discharged_as": "obligation",
                    "never_assumption": True,
                },
            )
            extra.append(obligation)
            promoted.append(obligation.obligation_id)

        if not extra:
            return vc_set, promoted

        return (
            VerificationConditionSet(
                program_id=vc_set.program_id,
                function_id=vc_set.function_id,
                parent_contract_id=vc_set.parent_contract_id,
                obligations=tuple(vc_set.obligations) + tuple(extra),
                weakest_preconditions=vc_set.weakest_preconditions,
                generated_symbols=vc_set.generated_symbols,
                unsupported_effects=vc_set.unsupported_effects,
                loop_variant_policy=vc_set.loop_variant_policy,
                attributes=vc_set.attributes,
                vc_set_id="",
                schema_version=vc_set.schema_version,
            ),
            promoted,
        )

    def _unsupported_loop_vc_set(
        self,
        *,
        document: ProgramLogicDocument,
        contract: ProgramContract,
        loops: Sequence[LoopContract],
        reason: str,
    ) -> VerificationConditionSet:
        """Emit a VC set whose only content is unsupported-loop obligations."""

        function = next(
            item
            for item in document.program.functions
            if item.function_id == contract.function_id
        )
        obligations: list[VerificationObligation] = []
        unsupported: list[UnsupportedEffect] = []
        targets = list(loops) or [
            # Synthetic place-holder when no loop contract was supplied.
            None
        ]
        for index, loop in enumerate(targets):
            construct_id = (
                loop.loop_id if isinstance(loop, LoopContract) else f"loop:missing:{index}"
            )
            effect_id = f"unsupported:loop:{construct_id}"
            unsupported.append(
                UnsupportedEffect(
                    effect_id=effect_id,
                    kind=UnsupportedEffectKind.NONDETERMINISTIC,
                    construct_kind=SourceConstructKind.LOOP,
                    construct_id=construct_id,
                    description=reason,
                    parent_contract_id=contract.contract_id,
                )
            )
            obligations.append(
                VerificationObligation(
                    obligation_id=(
                        f"vc:unsupported_effect:loop:{construct_id}:"
                        f"{contract.contract_id}"
                    )[:255],
                    rule=VCRuleKind.UNSUPPORTED_EFFECT,
                    parent_contract_id=contract.contract_id,
                    function_id=function.function_id,
                    source_construct_kind=SourceConstructKind.LOOP,
                    source_construct_id=construct_id,
                    assumption_expression_ids=(),
                    goal_expression_ids=(),
                    path_condition_expression_ids=(),
                    statement=(
                        f"Unsupported or incomplete loop {construct_id}: {reason}"
                    ),
                    source_ref_ids=contract.source_ref_ids,
                    span_ids=contract.span_ids,
                    attributes={
                        "unsupported_effect_id": effect_id,
                        "unsupported_kind": "unsupported_loop",
                        "discharged_as": "obligation",
                        "never_assumption": True,
                        "reason": reason,
                    },
                )
            )
        return VerificationConditionSet(
            program_id=document.program.program_id,
            function_id=function.function_id,
            parent_contract_id=contract.contract_id,
            obligations=tuple(obligations),
            weakest_preconditions=(),
            generated_symbols=(),
            unsupported_effects=tuple(unsupported),
            loop_variant_policy=self.loop_variant_policy,
            attributes={
                "generator_interface": VERIFICATION_CONDITION_BRIDGE_INTERFACE,
                "unsupported_loop": True,
            },
            vc_set_id="",
        )

    @staticmethod
    def _assert_unsupported_not_assumed(vc_set: VerificationConditionSet) -> None:
        """Fail closed if an unsupported effect is treated as a path assumption."""

        unsupported_ids = {item.effect_id for item in vc_set.unsupported_effects}
        if not unsupported_ids:
            return
        for obligation in vc_set.obligations:
            if obligation.rule is VCRuleKind.UNSUPPORTED_EFFECT:
                # Obligations for unsupported effects must not smuggle the
                # effect into assumptions as if it were discharged.
                if obligation.attributes.to_dict().get("never_assumption") is False:
                    raise VerificationConditionBridgeError(
                        f"obligation {obligation.obligation_id} marks unsupported "
                        "effect as assumption",
                        code=CODE_UNSUPPORTED_EFFECT,
                    )
                continue
            # Effect ids must never appear among assumption expression ids.
            overlap = unsupported_ids.intersection(obligation.assumption_expression_ids)
            if overlap:
                raise VerificationConditionBridgeError(
                    f"unsupported effects {sorted(overlap)} appear as assumptions "
                    f"on obligation {obligation.obligation_id}",
                    code=CODE_UNSUPPORTED_EFFECT,
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "interface": self.interface,
            "loop_variant_policy": self.loop_variant_policy.value,
            "promote_unsupported_to_obligations": (
                self.promote_unsupported_to_obligations
            ),
            "require_source_maps": self.require_source_maps,
            "schema_version": self.schema_version,
            "view_role": self.view_role,
        }


# ---------------------------------------------------------------------------
# Public syntax facade
# ---------------------------------------------------------------------------


class ProgramLogicSyntax:
    """Facade for Hoare / contract / dynamic-logic program syntax.

    Interface: ``ProgramLogicSyntax@1``.
    """

    interface: ClassVar[str] = PROGRAM_LOGIC_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = PROGRAM_LOGIC_NOTATION_ID
    notation_version: ClassVar[str] = PROGRAM_LOGIC_NOTATION_VERSION
    profile_id: ClassVar[str] = PROGRAM_LOGIC_PROFILE_ID
    family_id: ClassVar[str] = PROGRAM_LOGIC_FAMILY_ID
    binding_version: ClassVar[str] = PROGRAM_LOGIC_BINDING_VERSION
    state_version: ClassVar[str] = PROGRAM_LOGIC_STATE_VERSION
    module_version: ClassVar[str] = PROGRAM_LOGIC_MODULE_VERSION

    def __init__(
        self,
        *,
        loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
    ) -> None:
        self.vc_bridge = VerificationConditionBridge(
            loop_variant_policy=loop_variant_policy
        )

    def parse_mapping(self, value: Mapping[str, Any]) -> ProgramLogicDocument:
        return ProgramLogicDocument.from_dict(value)

    def parse_json(self, text: str) -> ProgramLogicDocument:
        return ProgramLogicDocument.from_json(text)

    def parse_program_ir(
        self,
        program: ProgramIR,
        *,
        contracts: Sequence[ProgramContract | Mapping[str, Any]] = (),
        loop_contracts: Sequence[LoopContract | Mapping[str, Any]] = (),
        hoare_triples: Sequence[HoareTriple | Mapping[str, Any]] = (),
        dynamic_formulas: Sequence[DynamicLogicFormula | Mapping[str, Any]] = (),
        surfaces: Sequence[SurfaceForm | Mapping[str, Any]] = (),
    ) -> ProgramLogicDocument:
        if not isinstance(program, ProgramIR):
            raise ProgramLogicError(
                "parse_program_ir requires a ProgramIR",
                code=CODE_MISSING_PROGRAM,
            )
        return ProgramLogicDocument(
            program=program,
            contracts=tuple(contracts),
            loop_contracts=tuple(loop_contracts),
            hoare_triples=tuple(hoare_triples),
            dynamic_formulas=tuple(dynamic_formulas),
            surfaces=tuple(surfaces),
        )

    def elaborate(self, document: ProgramLogicDocument) -> ProgramIR:
        if not isinstance(document, ProgramLogicDocument):
            raise ProgramLogicError(
                "elaborate requires ProgramLogicDocument",
                code=CODE_INVALID_DOCUMENT,
            )
        return document.elaborate()

    def print_json(self, document: ProgramLogicDocument) -> str:
        if not isinstance(document, ProgramLogicDocument):
            raise ProgramLogicError(
                "print_json requires ProgramLogicDocument",
                code=CODE_INVALID_DOCUMENT,
            )
        return document.to_json()

    def print_hoare(self, triple: HoareTriple) -> str:
        """Print a compact ``{P} C {Q}`` surface form for a typed triple."""

        if not isinstance(triple, HoareTriple):
            raise ProgramLogicError(
                "print_hoare requires HoareTriple",
                code=CODE_INVALID_HOARE,
            )
        pre = " /\\ ".join(triple.precondition_ids)
        post = " /\\ ".join(triple.normal_postcondition_ids)
        return f"{{{pre}}} {triple.command_id} {{{post}}}"

    def print_dynamic(self, formula: DynamicLogicFormula) -> str:
        """Print a compact ``[α]P`` / ``<α>P`` surface form."""

        if not isinstance(formula, DynamicLogicFormula):
            raise ProgramLogicError(
                "print_dynamic requires DynamicLogicFormula",
                code=CODE_INVALID_DYNAMIC,
            )
        if formula.modality is DynamicLogicModality.BOX:
            return f"[{formula.program_ref_id}]{formula.postcondition_expression_id}"
        return f"<{formula.program_ref_id}>{formula.postcondition_expression_id}"

    def print_modifies(self, frame: FrameCondition) -> str:
        """Print a modifies clause from a frame condition."""

        if not isinstance(frame, FrameCondition):
            raise ProgramLogicError(
                "print_modifies requires FrameCondition",
                code=CODE_INVALID_CONTRACT,
            )
        if frame.allows_all_writes:
            return "modifies *"
        if not frame.writable_symbol_ids:
            return "modifies \\nothing"
        return "modifies " + ", ".join(frame.writable_symbol_ids)

    def lower_to_vc(
        self,
        document: ProgramLogicDocument | Mapping[str, Any],
        *,
        function_id: str | None = None,
    ) -> VerificationConditionBridgeResult:
        return self.vc_bridge.lower(document, function_id=function_id)


def parse_program_logic(
    value: Mapping[str, Any] | str | ProgramIR,
    *,
    contracts: Sequence[ProgramContract | Mapping[str, Any]] = (),
    loop_contracts: Sequence[LoopContract | Mapping[str, Any]] = (),
    hoare_triples: Sequence[HoareTriple | Mapping[str, Any]] = (),
    dynamic_formulas: Sequence[DynamicLogicFormula | Mapping[str, Any]] = (),
) -> ProgramLogicDocument:
    """Parse a structured program-logic document."""

    syntax = ProgramLogicSyntax()
    if isinstance(value, ProgramIR):
        return syntax.parse_program_ir(
            value,
            contracts=contracts,
            loop_contracts=loop_contracts,
            hoare_triples=hoare_triples,
            dynamic_formulas=dynamic_formulas,
        )
    if isinstance(value, str):
        return syntax.parse_json(value)
    return syntax.parse_mapping(value)


def lower_to_verification_conditions(
    value: ProgramLogicDocument | Mapping[str, Any],
    *,
    function_id: str | None = None,
    loop_variant_policy: LoopVariantPolicy | str = LoopVariantPolicy.OPTIONAL,
) -> VerificationConditionBridgeResult:
    """Lower a program-logic document through VerificationConditionBridge@1."""

    return VerificationConditionBridge(
        loop_variant_policy=loop_variant_policy
    ).lower(value, function_id=function_id)


def program_logic_namespace() -> dict[str, str]:
    """Return the canonical family / view / version namespace for this frontend."""

    return {
        "family_id": PROGRAM_LOGIC_FAMILY_ID,
        "view_role": VC_VIEW_ROLE,
        "profile_id": PROGRAM_LOGIC_PROFILE_ID,
        "dynamic_logic_profile": DYNAMIC_LOGIC_PROFILE_ID,
        "binding_version": PROGRAM_LOGIC_BINDING_VERSION,
        "state_version": PROGRAM_LOGIC_STATE_VERSION,
        "notation_id": PROGRAM_LOGIC_NOTATION_ID,
        "notation_version": PROGRAM_LOGIC_NOTATION_VERSION,
        "module_version": PROGRAM_LOGIC_MODULE_VERSION,
        "interface": PROGRAM_LOGIC_SYNTAX_INTERFACE,
        "bridge_interface": VERIFICATION_CONDITION_BRIDGE_INTERFACE,
    }


# Re-export IR vocabulary commonly needed by DSL authors.
__all__ = [
    "CODE_FAMILY_NAMESPACE",
    "CODE_UNSUPPORTED_EFFECT",
    "CODE_UNSUPPORTED_LOOP",
    "CODE_VERSION_MISMATCH",
    "DYNAMIC_LOGIC_PROFILE_ID",
    "PROGRAM_LOGIC_BINDING_VERSION",
    "PROGRAM_LOGIC_DOCUMENT_SCHEMA",
    "PROGRAM_LOGIC_FAMILY_ID",
    "PROGRAM_LOGIC_MODULE_VERSION",
    "PROGRAM_LOGIC_NOTATION_ID",
    "PROGRAM_LOGIC_PROFILE_ID",
    "PROGRAM_LOGIC_STATE_VERSION",
    "PROGRAM_LOGIC_SYNTAX_INTERFACE",
    "UNSUPPORTED_LOOP_CONSTRUCTS",
    "VC_VIEW_ROLE",
    "VERIFICATION_CONDITION_BRIDGE_INTERFACE",
    "ProgramLogicDocument",
    "ProgramLogicError",
    "ProgramLogicSyntax",
    "SourceMapBinding",
    "StrongestPostcondition",
    "SurfaceForm",
    "SurfaceKind",
    "VerificationConditionBridge",
    "VerificationConditionBridgeError",
    "VerificationConditionBridgeResult",
    "lower_to_verification_conditions",
    "parse_dynamic_surface",
    "parse_hoare_surface",
    "parse_program_logic",
    "program_logic_namespace",
    # Common IR surface for DSL construction.
    "ContractClause",
    "ContractClauseKind",
    "DynamicLogicExit",
    "DynamicLogicFormula",
    "DynamicLogicModality",
    "DynamicProgramKind",
    "EffectSummary",
    "ExceptionalPostcondition",
    "FrameCondition",
    "HoareTriple",
    "LoopContract",
    "LoopVariantPolicy",
    "ProgramContract",
    "ProgramIR",
    "Purity",
    "SourceConstructKind",
    "UnsupportedEffect",
    "UnsupportedEffectKind",
    "VCRuleKind",
    "VerificationConditionSet",
    "VerificationObligation",
    "WeakestPrecondition",
    "generate_verification_conditions",
]

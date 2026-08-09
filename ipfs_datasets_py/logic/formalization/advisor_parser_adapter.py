"""Deterministic parser boundary for SymbolicAI / Leanstral proposal candidates.

Interface: ``AdvisorCandidateParser@1`` (LFP-022).

SymbolicAI and Leanstral emit untrusted proposal candidates under
:mod:`ipfs_datasets_py.logic.formalization.proposal_advisors`.  This adapter
is the only join path from free-form proposal text into typed classical/rule
parser outputs:

* successful parse/elaboration yields a **typed candidate** that still carries
  ``authority="unverified_candidate_only"``;
* parse or type failure leaves the original proposal as an **unverified
  candidate** — never a proof, model, or authorization decision;
* confidence, ``is_valid``, and similarity never establish proof authority;
* backends are never invoked here and natural language is not re-fed to
  solvers without a successful deterministic parse.

Evidence subset: ErgoAI/SymbolicAI advisor-only result, deterministic parse
failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    ProposalCandidate,
    ProposalProvider,
    accept_candidate,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.parsers.flogic import (
    FLOGIC_FAMILY_ID,
    FLogicFrontend,
    FLogicParseResult,
)
from ipfs_datasets_py.logic.parsers.rules import (
    RULE_FAMILY_ID,
    SECPAL_FAMILY_ID,
    RuleFrontend,
    RuleParseResult,
    SecPALFrontend,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    SMTLIB2Frontend,
    SMTLIBParseResult,
)
from ipfs_datasets_py.logic.parsers.tptp import (
    TPTP_FAMILY_ID,
    TPTPFrontend,
    TPTPParseResult,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

ADVISOR_CANDIDATE_PARSER_INTERFACE: Final = "AdvisorCandidateParser@1"
ADVISOR_CANDIDATE_PARSER_VERSION: Final = "1.0.0"
ADVISOR_PARSE_RECEIPT_SCHEMA: Final = "advisor-candidate-parse-receipt/v1"
ADVISOR_PARSE_RESULT_SCHEMA: Final = "advisor-candidate-parse-result/v1"
ADVISOR_PARSER_MODULE_VERSION: Final = "1.0.0"

CODE_PARSE_FAILED: Final = "advisor_parser.parse_failed"
CODE_TYPE_FAILED: Final = "advisor_parser.type_failed"
CODE_UNSUPPORTED_NOTATION: Final = "advisor_parser.unsupported_notation"
CODE_UNVERIFIED: Final = "advisor_parser.unverified_candidate"
CODE_AUTHORITY: Final = "advisor_parser.authority_ceiling"
CODE_MALFORMED: Final = "advisor_parser.malformed"
CODE_EMPTY_BODY: Final = "advisor_parser.empty_body"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_PARSE_FAILED,
        CODE_TYPE_FAILED,
        CODE_UNSUPPORTED_NOTATION,
        CODE_UNVERIFIED,
        CODE_AUTHORITY,
        CODE_MALFORMED,
        CODE_EMPTY_BODY,
    }
)


class AdvisorParserError(ValueError):
    """Raised when advisor-parser boundary inputs are malformed."""

    def __init__(self, message: str, *, code: str = CODE_MALFORMED) -> None:
        super().__init__(message)
        self.code = code if code in _ALL_CODES else CODE_MALFORMED


class AdvisorNotation(StrEnum):
    """Closed set of deterministic notations an advisor body may target."""

    SMTLIB2 = "smtlib2"
    TPTP = "tptp"
    RULES = "datalog_rules"
    SECPAL = "secpal"
    FLOGIC = "flogic"
    AUTO = "auto"


class AdvisorParseDisposition(StrEnum):
    """Outcome of the deterministic parse/elaboration attempt."""

    TYPED_CANDIDATE = "typed_candidate"
    UNVERIFIED_CANDIDATE = "unverified_candidate"
    UNSUPPORTED_NOTATION = "unsupported_notation"


_NOTATION_FAMILY: Final[dict[AdvisorNotation, str]] = {
    AdvisorNotation.SMTLIB2: "first_order",
    AdvisorNotation.TPTP: TPTP_FAMILY_ID,
    AdvisorNotation.RULES: RULE_FAMILY_ID,
    AdvisorNotation.SECPAL: SECPAL_FAMILY_ID,
    AdvisorNotation.FLOGIC: FLOGIC_FAMILY_ID,
}

_NOTATION_PARSER_INTERFACE: Final[dict[AdvisorNotation, str]] = {
    AdvisorNotation.SMTLIB2: "SMTLIB2Frontend@1",
    AdvisorNotation.TPTP: "TPTPFrontend@1",
    AdvisorNotation.RULES: "RuleFrontend@1",
    AdvisorNotation.SECPAL: "SecPALFrontend@1",
    AdvisorNotation.FLOGIC: "FLogicFrontend@1",
}


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AdvisorParserError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise AdvisorParserError(f"{field_name} must not contain NUL bytes")
    return value


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        raise AdvisorParserError(
            f"{field_name} must be one of {[item.value for item in enum_type]}"
        ) from error


def normalize_notation(value: AdvisorNotation | str) -> AdvisorNotation:
    if isinstance(value, AdvisorNotation):
        return value
    key = str(value).strip().lower().replace("-", "_")
    aliases = {
        "smt": AdvisorNotation.SMTLIB2,
        "smtlib": AdvisorNotation.SMTLIB2,
        "smt_lib": AdvisorNotation.SMTLIB2,
        "smtlib2": AdvisorNotation.SMTLIB2,
        "tptp": AdvisorNotation.TPTP,
        "fof": AdvisorNotation.TPTP,
        "rules": AdvisorNotation.RULES,
        "datalog": AdvisorNotation.RULES,
        "datalog_rules": AdvisorNotation.RULES,
        "horn": AdvisorNotation.RULES,
        "secpal": AdvisorNotation.SECPAL,
        "authorization": AdvisorNotation.SECPAL,
        "flogic": AdvisorNotation.FLOGIC,
        "frame_logic": AdvisorNotation.FLOGIC,
        "ergoai": AdvisorNotation.FLOGIC,
        "auto": AdvisorNotation.AUTO,
    }
    if key not in aliases:
        raise AdvisorParserError(
            f"unsupported advisor notation: {value!r}",
            code=CODE_UNSUPPORTED_NOTATION,
        )
    return aliases[key]


# ---------------------------------------------------------------------------
# Receipt / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdvisorParseReceipt:
    """Deterministic record of one advisor body parse attempt."""

    candidate_id: str
    provider: ProposalProvider | str
    notation: AdvisorNotation | str
    disposition: AdvisorParseDisposition | str
    authority: str = UNVERIFIED_AUTHORITY
    result_authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    result_status: ResultStatus | str = ResultStatus.CANDIDATE
    parser_interface: str = ""
    logic_family: str = ""
    parse_ok: bool = False
    type_ok: bool = False
    diagnostics: tuple[str, ...] = ()
    body_digest: str = ""
    schema_version: str = ADVISOR_PARSE_RECEIPT_SCHEMA
    interface: str = ADVISOR_CANDIDATE_PARSER_INTERFACE
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _text(self.candidate_id, "candidate_id")
        )
        provider = (
            self.provider
            if isinstance(self.provider, ProposalProvider)
            else ProposalProvider(str(self.provider))
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self, "notation", normalize_notation(self.notation)  # type: ignore[arg-type]
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, AdvisorParseDisposition, "disposition"),
        )
        if self.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorParserError(
                "advisor parse receipt authority must remain "
                f"{UNVERIFIED_AUTHORITY!r}",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "authority", UNVERIFIED_AUTHORITY)
        object.__setattr__(
            self,
            "result_authority",
            (
                self.result_authority
                if isinstance(self.result_authority, ResultAuthority)
                else ResultAuthority(str(self.result_authority))
            ),
        )
        if self.result_authority is not ResultAuthority.CANDIDATE:
            raise AdvisorParserError(
                "advisor parse results cannot exceed candidate authority",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(
            self,
            "result_status",
            (
                self.result_status
                if isinstance(self.result_status, ResultStatus)
                else ResultStatus(str(self.result_status))
            ),
        )
        if self.result_status is not ResultStatus.CANDIDATE:
            raise AdvisorParserError(
                "advisor parse status must remain candidate",
                code=CODE_AUTHORITY,
            )
        for flag in ("parse_ok", "type_ok"):
            if not isinstance(getattr(self, flag), bool):
                raise AdvisorParserError(f"{flag} must be a boolean")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(str(item) for item in self.diagnostics),
        )
        object.__setattr__(
            self,
            "parser_interface",
            str(self.parser_interface or ""),
        )
        object.__setattr__(self, "logic_family", str(self.logic_family or ""))
        if self.body_digest and (
            not isinstance(self.body_digest, str) or len(self.body_digest) != 64
        ):
            # Accept either raw hex or empty; recompute allowed at construction sites.
            if not (
                isinstance(self.body_digest, str)
                and self.body_digest.startswith("sha256:")
            ):
                object.__setattr__(
                    self,
                    "body_digest",
                    str(self.body_digest),
                )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise AdvisorParserError(
                "receipt metadata must be immutable JSON data"
            ) from error
        if self.schema_version != ADVISOR_PARSE_RECEIPT_SCHEMA:
            raise AdvisorParserError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )
        if self.interface != ADVISOR_CANDIDATE_PARSER_INTERFACE:
            raise AdvisorParserError(
                f"unsupported interface: {self.interface!r}"
            )

    @property
    def is_proved(self) -> bool:
        return confidence_never_yields_proof()

    @property
    def remains_unverified(self) -> bool:
        return self.authority == UNVERIFIED_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "body_digest": self.body_digest,
            "candidate_id": self.candidate_id,
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AdvisorParseDisposition)
                else self.disposition
            ),
            "interface": self.interface,
            "is_proved": False,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "notation": (
                self.notation.value
                if isinstance(self.notation, AdvisorNotation)
                else self.notation
            ),
            "parse_ok": self.parse_ok,
            "parser_interface": self.parser_interface,
            "provider": (
                self.provider.value
                if isinstance(self.provider, ProposalProvider)
                else self.provider
            ),
            "remains_unverified": True,
            "result_authority": (
                self.result_authority.value
                if isinstance(self.result_authority, ResultAuthority)
                else self.result_authority
            ),
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "schema_version": self.schema_version,
            "type_ok": self.type_ok,
        }


@dataclass(frozen=True, slots=True)
class AdvisorParseResult:
    """Boundary result: typed artifact on success, unverified candidate always."""

    candidate: ProposalCandidate
    receipt: AdvisorParseReceipt
    typed_document: Any | None = None
    typed_kind: str = ""
    schema_version: str = ADVISOR_PARSE_RESULT_SCHEMA
    interface: str = ADVISOR_CANDIDATE_PARSER_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ProposalCandidate):
            raise AdvisorParserError("candidate must be a ProposalCandidate")
        if self.candidate.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorParserError(
                "proposal candidate authority must remain unverified",
                code=CODE_AUTHORITY,
            )
        if not isinstance(self.receipt, AdvisorParseReceipt):
            raise AdvisorParserError("receipt must be an AdvisorParseReceipt")
        if self.receipt.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorParserError(
                "parse receipt authority must remain unverified",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "typed_kind", str(self.typed_kind or ""))
        if self.schema_version != ADVISOR_PARSE_RESULT_SCHEMA:
            raise AdvisorParserError(
                f"unsupported result schema: {self.schema_version!r}"
            )

    @property
    def disposition(self) -> AdvisorParseDisposition:
        disp = self.receipt.disposition
        return (
            disp
            if isinstance(disp, AdvisorParseDisposition)
            else AdvisorParseDisposition(str(disp))
        )

    @property
    def parse_ok(self) -> bool:
        return self.receipt.parse_ok and self.receipt.type_ok

    @property
    def remains_unverified_candidate(self) -> bool:
        """True always for authority; also True when parse/type failed."""

        return self.candidate.authority == UNVERIFIED_AUTHORITY

    @property
    def is_proved(self) -> bool:
        return False

    def acceptance(
        self,
        *,
        independently_validated: bool = False,
    ) -> Any:
        """Admission still requires independent validation — parse alone is insufficient."""

        return accept_candidate(
            self.candidate,
            compiled=self.parse_ok,
            independently_validated=independently_validated,
            reasons=(
                ()
                if self.parse_ok
                else ("deterministic_parse_or_type_failed",)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        typed_payload: Any = None
        if self.typed_document is not None and hasattr(
            self.typed_document, "to_dict"
        ):
            typed_payload = self.typed_document.to_dict()
        return {
            "candidate": self.candidate.to_dict(),
            "disposition": self.disposition.value,
            "interface": self.interface,
            "is_proved": False,
            "parse_ok": self.parse_ok,
            "receipt": self.receipt.to_dict(),
            "remains_unverified_candidate": True,
            "schema_version": self.schema_version,
            "typed_document": typed_payload,
            "typed_kind": self.typed_kind,
        }


# ---------------------------------------------------------------------------
# AdvisorCandidateParser@1
# ---------------------------------------------------------------------------


class AdvisorCandidateParser:
    """Parse SymbolicAI / Leanstral proposal bodies through deterministic frontends.

    Interface: ``AdvisorCandidateParser@1``.

    Never elevates authority.  Parse/type failure returns the original
    :class:`ProposalCandidate` under :data:`UNVERIFIED_AUTHORITY`.
    """

    INTERFACE: ClassVar[str] = ADVISOR_CANDIDATE_PARSER_INTERFACE
    interface: ClassVar[str] = ADVISOR_CANDIDATE_PARSER_INTERFACE
    VERSION: ClassVar[str] = ADVISOR_CANDIDATE_PARSER_VERSION

    def __init__(self) -> None:
        self._smtlib = SMTLIB2Frontend()
        self._tptp = TPTPFrontend()
        self._rules = RuleFrontend()
        self._secpal = SecPALFrontend()
        self._flogic = FLogicFrontend()

    def parse(
        self,
        candidate: ProposalCandidate | Mapping[str, Any],
        *,
        notation: AdvisorNotation | str = AdvisorNotation.AUTO,
    ) -> AdvisorParseResult:
        """Attempt deterministic parse/elaboration of one proposal candidate."""

        cand = (
            candidate
            if isinstance(candidate, ProposalCandidate)
            else ProposalCandidate.from_dict(candidate)
        )
        if cand.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorParserError(
                "only unverified proposal candidates may enter the parser boundary",
                code=CODE_AUTHORITY,
            )
        body = cand.body
        body_digest = stable_digest({"body": body})
        notation_kind = normalize_notation(notation)

        if not body.strip():
            return self._unverified(
                cand,
                notation=notation_kind,
                diagnostics=(CODE_EMPTY_BODY, "empty proposal body"),
                body_digest=body_digest,
            )

        attempts = self._notation_order(notation_kind, body)
        last_diagnostics: list[str] = []
        for note in attempts:
            ok, typed, typed_kind, diagnostics = self._try_notation(note, body)
            if ok and typed is not None:
                receipt = AdvisorParseReceipt(
                    candidate_id=cand.candidate_id,
                    provider=cand.provider,
                    notation=note,
                    disposition=AdvisorParseDisposition.TYPED_CANDIDATE,
                    authority=UNVERIFIED_AUTHORITY,
                    result_authority=ResultAuthority.CANDIDATE,
                    result_status=ResultStatus.CANDIDATE,
                    parser_interface=_NOTATION_PARSER_INTERFACE[note],
                    logic_family=_NOTATION_FAMILY[note],
                    parse_ok=True,
                    type_ok=True,
                    diagnostics=tuple(diagnostics),
                    body_digest=body_digest,
                    metadata=FrozenMap(
                        {
                            "typed_kind": typed_kind,
                            "proposal_kind": cand.kind.value,
                        }
                    ),
                )
                return AdvisorParseResult(
                    candidate=cand,
                    receipt=receipt,
                    typed_document=typed,
                    typed_kind=typed_kind,
                )
            last_diagnostics.extend(diagnostics)

        # Parse/type failure: remain unverified candidate under proposal_advisors.
        return self._unverified(
            cand,
            notation=notation_kind if notation_kind is not AdvisorNotation.AUTO else (
                attempts[0] if attempts else AdvisorNotation.SMTLIB2
            ),
            diagnostics=tuple(last_diagnostics)
            or (CODE_PARSE_FAILED, "deterministic parse failed"),
            body_digest=body_digest,
        )

    def parse_symbolicai(
        self,
        candidate: ProposalCandidate | Mapping[str, Any],
        *,
        notation: AdvisorNotation | str = AdvisorNotation.AUTO,
    ) -> AdvisorParseResult:
        """Parse a SymbolicAI proposal; provider must be symai-class."""

        cand = (
            candidate
            if isinstance(candidate, ProposalCandidate)
            else ProposalCandidate.from_dict(candidate)
        )
        if cand.provider is not ProposalProvider.SYMAI:
            raise AdvisorParserError(
                "parse_symbolicai requires provider=symai",
                code=CODE_MALFORMED,
            )
        return self.parse(cand, notation=notation)

    def _unverified(
        self,
        candidate: ProposalCandidate,
        *,
        notation: AdvisorNotation,
        diagnostics: Sequence[str],
        body_digest: str,
    ) -> AdvisorParseResult:
        note = (
            notation
            if notation is not AdvisorNotation.AUTO
            else AdvisorNotation.SMTLIB2
        )
        receipt = AdvisorParseReceipt(
            candidate_id=candidate.candidate_id,
            provider=candidate.provider,
            notation=note,
            disposition=AdvisorParseDisposition.UNVERIFIED_CANDIDATE,
            authority=UNVERIFIED_AUTHORITY,
            result_authority=ResultAuthority.CANDIDATE,
            result_status=ResultStatus.CANDIDATE,
            parser_interface=_NOTATION_PARSER_INTERFACE.get(note, ""),
            logic_family=_NOTATION_FAMILY.get(note, ""),
            parse_ok=False,
            type_ok=False,
            diagnostics=tuple(str(item) for item in diagnostics),
            body_digest=body_digest,
            metadata=FrozenMap(
                {
                    "failure": "parse_or_type",
                    "proposal_kind": candidate.kind.value,
                    "under": "formalization/proposal_advisors.py",
                }
            ),
        )
        return AdvisorParseResult(
            candidate=candidate,
            receipt=receipt,
            typed_document=None,
            typed_kind="",
        )

    def _notation_order(
        self, notation: AdvisorNotation, body: str
    ) -> tuple[AdvisorNotation, ...]:
        if notation is not AdvisorNotation.AUTO:
            return (notation,)
        stripped = body.lstrip()
        head = stripped[:12].lower()
        ordered: list[AdvisorNotation] = []
        if head.startswith(("(set-", "(assert", "(declare", "(check")):
            ordered.append(AdvisorNotation.SMTLIB2)
        if head.startswith(("fof", "cnf", "tff", "%")):
            ordered.append(AdvisorNotation.TPTP)
        if " says " in body or "speaks-for" in body or "can " in body:
            ordered.append(AdvisorNotation.SECPAL)
        if ":-" in body or body.strip().endswith(".") or "?-" in body:
            ordered.append(AdvisorNotation.RULES)
        if "[" in body or "::" in body or ":-" in body:
            ordered.append(AdvisorNotation.FLOGIC)
        # Fallback exhaustive order for auto.
        for item in (
            AdvisorNotation.SMTLIB2,
            AdvisorNotation.TPTP,
            AdvisorNotation.SECPAL,
            AdvisorNotation.RULES,
            AdvisorNotation.FLOGIC,
        ):
            if item not in ordered:
                ordered.append(item)
        return tuple(ordered)

    def _try_notation(
        self, notation: AdvisorNotation, body: str
    ) -> tuple[bool, Any | None, str, tuple[str, ...]]:
        try:
            if notation is AdvisorNotation.SMTLIB2:
                result: SMTLIBParseResult = self._smtlib.parse_text(body)
                if result.ok and result.document is not None:
                    return True, result.document, "SmtlibDocument", ()
                diags = tuple(
                    f"{d.code}:{d.message}" for d in result.errors
                ) or (CODE_PARSE_FAILED,)
                return False, None, "", diags
            if notation is AdvisorNotation.TPTP:
                result_t: TPTPParseResult = self._tptp.parse_text(body)
                if result_t.ok and result_t.document is not None:
                    return True, result_t.document, "TPTPDocument", ()
                diags = tuple(
                    f"{d.code}:{d.message}" for d in result_t.errors
                ) or (CODE_PARSE_FAILED,)
                return False, None, "", diags
            if notation is AdvisorNotation.RULES:
                result_r: RuleParseResult = self._rules.parse_text(body)
                if result_r.ok and result_r.document is not None:
                    return True, result_r.document, "RuleDocument", ()
                diags = tuple(
                    f"{d.code}:{d.message}" for d in result_r.errors
                ) or (CODE_PARSE_FAILED,)
                return False, None, "", diags
            if notation is AdvisorNotation.SECPAL:
                result_s: RuleParseResult = self._secpal.parse_text(body)
                if result_s.ok and result_s.document is not None:
                    return True, result_s.document, "RuleDocument", ()
                diags = tuple(
                    f"{d.code}:{d.message}" for d in result_s.errors
                ) or (CODE_PARSE_FAILED,)
                return False, None, "", diags
            if notation is AdvisorNotation.FLOGIC:
                result_f: FLogicParseResult = self._flogic.parse_text(body)
                if result_f.ok and result_f.document is not None:
                    return True, result_f.document, "FLogicDocument", ()
                diags = tuple(
                    f"{d.code}:{d.message}" for d in result_f.errors
                ) or (CODE_PARSE_FAILED,)
                return False, None, "", diags
        except Exception as exc:  # fail closed to unverified candidate
            return False, None, "", (CODE_TYPE_FAILED, f"{type(exc).__name__}:{exc}")
        return False, None, "", (CODE_UNSUPPORTED_NOTATION,)


def parse_advisor_candidate(
    candidate: ProposalCandidate | Mapping[str, Any],
    *,
    notation: AdvisorNotation | str = AdvisorNotation.AUTO,
) -> AdvisorParseResult:
    """Module-level convenience for :class:`AdvisorCandidateParser`."""

    return AdvisorCandidateParser().parse(candidate, notation=notation)


__all__ = [
    "ADVISOR_CANDIDATE_PARSER_INTERFACE",
    "ADVISOR_CANDIDATE_PARSER_VERSION",
    "ADVISOR_PARSE_RECEIPT_SCHEMA",
    "ADVISOR_PARSE_RESULT_SCHEMA",
    "ADVISOR_PARSER_MODULE_VERSION",
    "CODE_AUTHORITY",
    "CODE_EMPTY_BODY",
    "CODE_MALFORMED",
    "CODE_PARSE_FAILED",
    "CODE_TYPE_FAILED",
    "CODE_UNSUPPORTED_NOTATION",
    "CODE_UNVERIFIED",
    "AdvisorCandidateParser",
    "AdvisorNotation",
    "AdvisorParseDisposition",
    "AdvisorParseReceipt",
    "AdvisorParseResult",
    "AdvisorParserError",
    "UNVERIFIED_AUTHORITY",
    "normalize_notation",
    "parse_advisor_candidate",
]

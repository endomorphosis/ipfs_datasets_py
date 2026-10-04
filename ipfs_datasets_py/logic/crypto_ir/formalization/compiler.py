"""Sound formal lowering contracts and the obligation compiler (CRYPTOIR-G320).

Each :class:`LoweringContract` declares a soundness scope and the theory
fragment it supports.  The :class:`ObligationCompiler` only emits a compiled
form when a reviewed contract accepts the payload; opaque
``security_verification_condition`` JSON, prose, and unsupported theories are
returned as explicit non-executable lowerings and are never handed to a
backend that does not compile that logic family.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Final, Iterable

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity
from ...ir_core.provenance import thaw_json
from ..identity import crypto_ir_identity
from ..provenance import freeze_json_mapping
from ..security_rules import FormalTargetKind
from .obligations import (
    CRYPTO_IR_FORMALIZATION_DOMAIN,
    NON_EXECUTABLE_LOGIC_FAMILIES,
    NON_EXECUTABLE_PAYLOAD_KINDS,
    OPAQUE_SECURITY_VERIFICATION_CONDITION,
    FormalObligation,
    FormalizationError,
    LogicFamily,
    ObligationPayloadKind,
    detect_payload_kind,
    is_executable_payload,
    logic_family_for_formal_target,
    _attributes,
    _enum,
    _identifier,
    _text,
    _unique_ids,
)


LOWERING_CONTRACT_SCHEMA_VERSION: Final[str] = "crypto-ir.lowering-contract@1.0.0"
LOWERED_FORM_SCHEMA_VERSION: Final[str] = "crypto-ir.lowered-form@1.0.0"
COMPILER_VERSION: Final[str] = "1.0.0"

_SMT_ASSERT_RE = re.compile(r"\(\s*assert\b", re.IGNORECASE)
_PROP_ATOM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROP_LITERAL_RE = re.compile(
    r"^(?P<neg>not\s+)?(?P<atom>true|false|[A-Za-z_][A-Za-z0-9_]*)$",
    re.IGNORECASE,
)


class LoweringStatus(str, Enum):
    """Outcome of a single lowering attempt (never a proof claim)."""

    COMPILED = "compiled"
    NOT_MODELED = "not_modeled"
    UNSUPPORTED = "unsupported"
    OPAQUE_REFUSED = "opaque_refused"
    INCOMPLETE_MODEL = "incomplete_model"
    ERROR = "error"


class TheoryFragment(str, Enum):
    """Reviewed theory fragments a contract may claim to support."""

    QF_BOOL = "QF_BOOL"
    QF_LIA = "QF_LIA"
    QF_BV = "QF_BV"
    PROPOSITIONAL = "propositional"
    FOL_CORE = "fol_core"
    DATALOG_POSITIVE = "datalog_positive"
    LTL_BOUNDED = "ltl_bounded"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SoundnessScope:
    """Explicit soundness boundary for one lowering contract.

    *assumptions* are trusted modeling choices; *exclusions* name what the
    lowering does **not** prove (e.g. unbounded reentrancy, full heap).
    """

    scope_id: str
    description: str
    assumptions: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    model_completeness_required: bool = True
    max_quantifier_depth: int = 0
    max_bitwidth: int = 0
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        object.__setattr__(
            self, "assumptions", _unique_ids(self.assumptions, "assumptions")
        )
        object.__setattr__(
            self, "exclusions", _unique_ids(self.exclusions, "exclusions")
        )
        if not isinstance(self.model_completeness_required, bool):
            raise FormalizationError("model_completeness_required must be a bool")
        for name in ("max_quantifier_depth", "max_bitwidth"):
            value = getattr(self, name)
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise FormalizationError(f"{name} must be a non-negative int")
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "attributes": thaw_json(self.attributes),
            "description": self.description,
            "exclusions": list(self.exclusions),
            "max_bitwidth": self.max_bitwidth,
            "max_quantifier_depth": self.max_quantifier_depth,
            "model_completeness_required": self.model_completeness_required,
            "scope_id": self.scope_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SoundnessScope":
        if not isinstance(value, Mapping):
            raise FormalizationError("SoundnessScope must be a mapping")
        return cls(
            scope_id=value.get("scope_id", ""),
            description=value.get("description", ""),
            assumptions=tuple(value.get("assumptions", ())),
            exclusions=tuple(value.get("exclusions", ())),
            model_completeness_required=bool(
                value.get("model_completeness_required", True)
            ),
            max_quantifier_depth=int(value.get("max_quantifier_depth", 0)),
            max_bitwidth=int(value.get("max_bitwidth", 0)),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class LoweringContract:
    """Reviewed, soundness-scoped lowering from a payload kind to a logic family.

    Contracts are the sole authority for what may be submitted to a backend.
    A contract that targets :attr:`LogicFamily.OPAQUE` or refuses a source
    never yields an executable compiled form.
    """

    contract_id: str
    source_payload_kinds: tuple[ObligationPayloadKind, ...]
    target_logic_family: LogicFamily
    supported_theories: tuple[TheoryFragment, ...]
    soundness_scope: SoundnessScope
    formal_target_kinds: tuple[FormalTargetKind, ...] = ()
    backend_families: tuple[str, ...] = ()
    produces_executable: bool = True
    description: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOWERING_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contract_id", _identifier(self.contract_id, "contract_id")
        )
        if (
            not isinstance(self.source_payload_kinds, tuple)
            or not self.source_payload_kinds
        ):
            kinds = tuple(
                _enum(ObligationPayloadKind, k, "source_payload_kinds")
                for k in (self.source_payload_kinds or ())
            )
        else:
            kinds = tuple(
                _enum(ObligationPayloadKind, k, "source_payload_kinds")
                for k in self.source_payload_kinds
            )
        if not kinds:
            raise FormalizationError("source_payload_kinds must be non-empty")
        object.__setattr__(self, "source_payload_kinds", kinds)
        object.__setattr__(
            self,
            "target_logic_family",
            _enum(LogicFamily, self.target_logic_family, "target_logic_family"),
        )
        theories = tuple(
            _enum(TheoryFragment, t, "supported_theories")
            for t in (self.supported_theories or ())
        )
        if not theories:
            raise FormalizationError("supported_theories must be non-empty")
        object.__setattr__(self, "supported_theories", theories)
        if not isinstance(self.soundness_scope, SoundnessScope):
            if isinstance(self.soundness_scope, Mapping):
                object.__setattr__(
                    self,
                    "soundness_scope",
                    SoundnessScope.from_dict(self.soundness_scope),
                )
            else:
                raise FormalizationError(
                    "soundness_scope must be SoundnessScope or mapping"
                )
        targets = tuple(
            _enum(FormalTargetKind, t, "formal_target_kinds")
            for t in (self.formal_target_kinds or ())
        )
        object.__setattr__(self, "formal_target_kinds", targets)
        backends = _unique_ids(self.backend_families, "backend_families")
        object.__setattr__(self, "backend_families", backends)
        if not isinstance(self.produces_executable, bool):
            raise FormalizationError("produces_executable must be a bool")
        # Non-executable logic families can never produce executable output.
        if self.target_logic_family in NON_EXECUTABLE_LOGIC_FAMILIES:
            object.__setattr__(self, "produces_executable", False)
        object.__setattr__(
            self, "description", _text(self.description, "description", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def accepts(
        self,
        obligation: FormalObligation,
        *,
        payload_kind: ObligationPayloadKind | None = None,
    ) -> bool:
        """Return True when this contract may attempt to lower *obligation*."""

        kind = payload_kind or obligation.payload_kind
        if kind not in self.source_payload_kinds:
            return False
        if self.formal_target_kinds and (
            obligation.formal_target_kind not in self.formal_target_kinds
        ):
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "backend_families": list(self.backend_families),
            "contract_id": self.contract_id,
            "description": self.description,
            "formal_target_kinds": [
                t.value if isinstance(t, FormalTargetKind) else t
                for t in self.formal_target_kinds
            ],
            "produces_executable": self.produces_executable,
            "schema_version": self.schema_version,
            "soundness_scope": self.soundness_scope.to_dict(),
            "source_payload_kinds": [
                k.value if isinstance(k, ObligationPayloadKind) else k
                for k in self.source_payload_kinds
            ],
            "supported_theories": [
                t.value if isinstance(t, TheoryFragment) else t
                for t in self.supported_theories
            ],
            "target_logic_family": (
                self.target_logic_family.value
                if isinstance(self.target_logic_family, LogicFamily)
                else self.target_logic_family
            ),
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_FORMALIZATION_DOMAIN}.lowering-contract",
        )


@dataclass(frozen=True, slots=True)
class LoweredForm:
    """Result of applying a lowering contract to one formal obligation.

    When :attr:`status` is not :attr:`LoweringStatus.COMPILED`,
    :attr:`may_submit` is always False and no backend may execute the body.
    """

    form_id: str
    obligation_id: str
    model_digest: str
    contract_id: str
    status: LoweringStatus
    logic_family: LogicFamily
    payload_kind: ObligationPayloadKind
    body: str
    theory: TheoryFragment
    soundness_scope_id: str
    may_submit: bool
    reason: str = ""
    assumption_ids: tuple[str, ...] = ()
    exclusion_ids: tuple[str, ...] = ()
    compiler_version: str = COMPILER_VERSION
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOWERED_FORM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "form_id", _identifier(self.form_id, "form_id"))
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "model_digest", _text(self.model_digest, "model_digest", allow_empty=True)
        )
        object.__setattr__(
            self, "contract_id", _identifier(self.contract_id, "contract_id")
        )
        object.__setattr__(
            self, "status", _enum(LoweringStatus, self.status, "status")
        )
        object.__setattr__(
            self, "logic_family", _enum(LogicFamily, self.logic_family, "logic_family")
        )
        object.__setattr__(
            self,
            "payload_kind",
            _enum(ObligationPayloadKind, self.payload_kind, "payload_kind"),
        )
        if not isinstance(self.body, str):
            raise FormalizationError("body must be a string")
        object.__setattr__(self, "theory", _enum(TheoryFragment, self.theory, "theory"))
        object.__setattr__(
            self,
            "soundness_scope_id",
            _identifier(self.soundness_scope_id, "soundness_scope_id"),
        )
        if not isinstance(self.may_submit, bool):
            raise FormalizationError("may_submit must be a bool")
        # Hard gate: non-compiled / non-executable never submit.
        if self.status is not LoweringStatus.COMPILED:
            object.__setattr__(self, "may_submit", False)
        if self.logic_family in NON_EXECUTABLE_LOGIC_FAMILIES:
            object.__setattr__(self, "may_submit", False)
        if self.payload_kind in NON_EXECUTABLE_PAYLOAD_KINDS:
            object.__setattr__(self, "may_submit", False)
        if self.may_submit and not is_executable_payload(self.payload_kind):
            object.__setattr__(self, "may_submit", False)
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", allow_empty=True)
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self, "exclusion_ids", _unique_ids(self.exclusion_ids, "exclusion_ids")
        )
        object.__setattr__(
            self,
            "compiler_version",
            _text(self.compiler_version, "compiler_version"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "body": self.body,
            "compiler_version": self.compiler_version,
            "contract_id": self.contract_id,
            "exclusion_ids": list(self.exclusion_ids),
            "form_id": self.form_id,
            "logic_family": (
                self.logic_family.value
                if isinstance(self.logic_family, LogicFamily)
                else self.logic_family
            ),
            "may_submit": self.may_submit,
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "payload_kind": (
                self.payload_kind.value
                if isinstance(self.payload_kind, ObligationPayloadKind)
                else self.payload_kind
            ),
            "reason": self.reason,
            "schema_version": self.schema_version,
            "soundness_scope_id": self.soundness_scope_id,
            "status": (
                self.status.value
                if isinstance(self.status, LoweringStatus)
                else self.status
            ),
            "theory": (
                self.theory.value if isinstance(self.theory, TheoryFragment) else self.theory
            ),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_FORMALIZATION_DOMAIN}.lowered-form",
        )


# ---------------------------------------------------------------------------
# Built-in lowerers
# ---------------------------------------------------------------------------


def _refuse(
    obligation: FormalObligation,
    *,
    contract_id: str,
    status: LoweringStatus,
    logic_family: LogicFamily,
    payload_kind: ObligationPayloadKind,
    reason: str,
    theory: TheoryFragment = TheoryFragment.NONE,
    soundness_scope_id: str = "scope.none",
    attributes: Mapping[str, Any] | None = None,
) -> LoweredForm:
    return LoweredForm(
        form_id=f"form.{obligation.obligation_id}.{contract_id}",
        obligation_id=obligation.obligation_id,
        model_digest=obligation.model_digest,
        contract_id=contract_id,
        status=status,
        logic_family=logic_family,
        payload_kind=payload_kind,
        body="",
        theory=theory,
        soundness_scope_id=soundness_scope_id,
        may_submit=False,
        reason=reason,
        assumption_ids=obligation.trusted_assumption_ids,
        attributes=attributes or {},
    )


def _normalize_prop_formula(text: str) -> str:
    """Normalize a tiny propositional fragment to SMT-LIB QF_BOOL body."""

    raw = text.strip()
    if not raw:
        raise FormalizationError("propositional formula must be non-empty")
    if _SMT_ASSERT_RE.search(raw):
        return raw if raw.endswith("\n") else raw + "\n"
    # Accept: true | false | p | not p | and(p,q) | or(p,q) | implies(p,q)
    lower = raw.lower().replace(" ", "")
    if lower in {"true", "false"}:
        return f"(assert {lower})\n(check-sat)\n"
    match = _PROP_LITERAL_RE.fullmatch(raw.strip())
    if match:
        atom = match.group("atom").lower()
        if match.group("neg"):
            return f"(assert (not {atom}))\n(check-sat)\n"
        return f"(assert {atom})\n(check-sat)\n"
    # and/or/implies functional forms
    for op, smt_op in (("and", "and"), ("or", "or"), ("implies", "=>")):
        prefix = f"{op}("
        if lower.startswith(prefix) and lower.endswith(")"):
            inner = lower[len(prefix) : -1]
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            if len(parts) < 2:
                raise FormalizationError(f"{op} requires at least two arguments")
            atoms: list[str] = []
            for part in parts:
                lit = _PROP_LITERAL_RE.fullmatch(part)
                if not lit:
                    raise FormalizationError(
                        f"unsupported propositional atom in {op}: {part!r}"
                    )
                atom = lit.group("atom").lower()
                if lit.group("neg"):
                    atoms.append(f"(not {atom})")
                else:
                    atoms.append(atom)
            joined = " ".join(atoms)
            return f"(assert ({smt_op} {joined}))\n(check-sat)\n"
    # Parenthesized SMT-style boolean terms without assert wrapper.
    if raw.startswith("(") and raw.endswith(")"):
        return f"(assert {raw})\n(check-sat)\n"
    if _PROP_ATOM_RE.fullmatch(raw):
        return f"(assert {raw.lower()})\n(check-sat)\n"
    raise FormalizationError(f"unsupported propositional formula: {raw!r}")


def _lower_propositional(
    obligation: FormalObligation, contract: LoweringContract
) -> LoweredForm:
    try:
        body = _normalize_prop_formula(str(obligation.payload))
    except FormalizationError as exc:
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.PROPOSITIONAL,
            payload_kind=ObligationPayloadKind.PROPOSITIONAL_FORMULA,
            reason=str(exc),
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    return LoweredForm(
        form_id=f"form.{obligation.obligation_id}.{contract.contract_id}",
        obligation_id=obligation.obligation_id,
        model_digest=obligation.model_digest,
        contract_id=contract.contract_id,
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.PROPOSITIONAL,
        payload_kind=ObligationPayloadKind.PROPOSITIONAL_FORMULA,
        body=body,
        theory=TheoryFragment.PROPOSITIONAL,
        soundness_scope_id=contract.soundness_scope.scope_id,
        may_submit=True,
        reason="propositional formula compiled to QF_BOOL SMT-LIB fragment",
        assumption_ids=obligation.trusted_assumption_ids
        + contract.soundness_scope.assumptions,
        exclusion_ids=contract.soundness_scope.exclusions,
    )


def _lower_smt_lib(
    obligation: FormalObligation, contract: LoweringContract
) -> LoweredForm:
    body = str(obligation.payload).strip()
    if not body:
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.SMT_LIB,
            payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
            reason="empty SMT-LIB body",
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    if not _SMT_ASSERT_RE.search(body):
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.SMT_LIB,
            payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
            reason="SMT-LIB body must contain at least one (assert ...) form",
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    if "(check-sat" not in body.lower():
        body = body.rstrip() + "\n(check-sat)\n"
    elif not body.endswith("\n"):
        body = body + "\n"
    theory = TheoryFragment.QF_BOOL
    if "bitvec" in body.lower() or "(_ bv" in body.lower():
        theory = TheoryFragment.QF_BV
    elif re.search(r"\bInt\b", body) or re.search(
        r"\(\s*[+\-*/]\b", body
    ):
        # Arithmetic operators only as SMT-LIB function heads, not hyphens
        # inside identifiers such as check-sat.
        theory = TheoryFragment.QF_LIA
    if theory not in contract.supported_theories and (
        TheoryFragment.QF_BOOL not in contract.supported_theories
    ):
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.SMT_LIB,
            payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
            reason=f"theory {theory.value} not in contract supported_theories",
            theory=theory,
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    return LoweredForm(
        form_id=f"form.{obligation.obligation_id}.{contract.contract_id}",
        obligation_id=obligation.obligation_id,
        model_digest=obligation.model_digest,
        contract_id=contract.contract_id,
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.SMT_LIB,
        payload_kind=ObligationPayloadKind.COMPILED_SMT_LIB,
        body=body,
        theory=theory if theory in contract.supported_theories else TheoryFragment.QF_BOOL,
        soundness_scope_id=contract.soundness_scope.scope_id,
        may_submit=True,
        reason="SMT-LIB fragment accepted under declared soundness scope",
        assumption_ids=obligation.trusted_assumption_ids
        + contract.soundness_scope.assumptions,
        exclusion_ids=contract.soundness_scope.exclusions,
    )


def _lower_fol(
    obligation: FormalObligation, contract: LoweringContract
) -> LoweredForm:
    body = str(obligation.payload).strip()
    if not body:
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.FOL,
            payload_kind=ObligationPayloadKind.FOL_FORMULA,
            reason="empty FOL formula",
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    # Bounded FOL core: allow quantifier-free or depth-limited forall/exists
    # already rendered as SMT-LIB.
    if _SMT_ASSERT_RE.search(body):
        quant_depth = body.lower().count("forall") + body.lower().count("exists")
        if quant_depth > contract.soundness_scope.max_quantifier_depth:
            return _refuse(
                obligation,
                contract_id=contract.contract_id,
                status=LoweringStatus.UNSUPPORTED,
                logic_family=LogicFamily.FOL,
                payload_kind=ObligationPayloadKind.FOL_FORMULA,
                reason=(
                    f"quantifier depth {quant_depth} exceeds scope max "
                    f"{contract.soundness_scope.max_quantifier_depth}"
                ),
                theory=TheoryFragment.FOL_CORE,
                soundness_scope_id=contract.soundness_scope.scope_id,
            )
        if "(check-sat" not in body.lower():
            body = body.rstrip() + "\n(check-sat)\n"
        return LoweredForm(
            form_id=f"form.{obligation.obligation_id}.{contract.contract_id}",
            obligation_id=obligation.obligation_id,
            model_digest=obligation.model_digest,
            contract_id=contract.contract_id,
            status=LoweringStatus.COMPILED,
            logic_family=LogicFamily.FOL,
            payload_kind=ObligationPayloadKind.FOL_FORMULA,
            body=body if body.endswith("\n") else body + "\n",
            theory=TheoryFragment.FOL_CORE,
            soundness_scope_id=contract.soundness_scope.scope_id,
            may_submit=True,
            reason="FOL core formula accepted within quantifier bound",
            assumption_ids=obligation.trusted_assumption_ids
            + contract.soundness_scope.assumptions,
            exclusion_ids=contract.soundness_scope.exclusions,
        )
    return _refuse(
        obligation,
        contract_id=contract.contract_id,
        status=LoweringStatus.UNSUPPORTED,
        logic_family=LogicFamily.FOL,
        payload_kind=ObligationPayloadKind.FOL_FORMULA,
        reason="FOL formula must be provided as SMT-LIB (assert ...) form",
        theory=TheoryFragment.FOL_CORE,
        soundness_scope_id=contract.soundness_scope.scope_id,
    )


def _lower_datalog(
    obligation: FormalObligation, contract: LoweringContract
) -> LoweredForm:
    payload = obligation.payload
    if isinstance(payload, str):
        rules = [line.strip() for line in payload.splitlines() if line.strip()]
    elif isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes, bytearray)
    ):
        rules = [str(item).strip() for item in payload if str(item).strip()]
    else:
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.DATALOG,
            payload_kind=ObligationPayloadKind.DATALOG_RULES,
            reason="datalog payload must be text rules or a sequence of rules",
            theory=TheoryFragment.DATALOG_POSITIVE,
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    if not rules:
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.DATALOG,
            payload_kind=ObligationPayloadKind.DATALOG_RULES,
            reason="empty datalog rule set",
            theory=TheoryFragment.DATALOG_POSITIVE,
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    # Positive Datalog only: reject negation and aggregation.
    for rule in rules:
        if re.search(r"\bnot\b", rule, re.IGNORECASE):
            return _refuse(
                obligation,
                contract_id=contract.contract_id,
                status=LoweringStatus.UNSUPPORTED,
                logic_family=LogicFamily.DATALOG,
                payload_kind=ObligationPayloadKind.DATALOG_RULES,
                reason="negation is outside positive-datalog soundness scope",
                theory=TheoryFragment.DATALOG_POSITIVE,
                soundness_scope_id=contract.soundness_scope.scope_id,
            )
        is_rule = ":-" in rule or "<-" in rule
        is_fact = (
            not is_rule
            and rule.endswith(".")
            and "(" in rule
            and ")" in rule
        )
        if not is_rule and not is_fact:
            return _refuse(
                obligation,
                contract_id=contract.contract_id,
                status=LoweringStatus.UNSUPPORTED,
                logic_family=LogicFamily.DATALOG,
                payload_kind=ObligationPayloadKind.DATALOG_RULES,
                reason=f"unsupported datalog rule form: {rule!r}",
                theory=TheoryFragment.DATALOG_POSITIVE,
                soundness_scope_id=contract.soundness_scope.scope_id,
            )
    body = "\n".join(rules) + "\n"
    return LoweredForm(
        form_id=f"form.{obligation.obligation_id}.{contract.contract_id}",
        obligation_id=obligation.obligation_id,
        model_digest=obligation.model_digest,
        contract_id=contract.contract_id,
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.DATALOG,
        payload_kind=ObligationPayloadKind.DATALOG_RULES,
        body=body,
        theory=TheoryFragment.DATALOG_POSITIVE,
        soundness_scope_id=contract.soundness_scope.scope_id,
        may_submit=True,
        reason="positive datalog rules accepted",
        assumption_ids=obligation.trusted_assumption_ids
        + contract.soundness_scope.assumptions,
        exclusion_ids=contract.soundness_scope.exclusions,
    )


def _lower_temporal(
    obligation: FormalObligation, contract: LoweringContract
) -> LoweredForm:
    body = str(obligation.payload).strip()
    if not body:
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.TEMPORAL,
            payload_kind=ObligationPayloadKind.TEMPORAL_FORMULA,
            reason="empty temporal formula",
            theory=TheoryFragment.LTL_BOUNDED,
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    # Bounded LTL: require an explicit bound annotation or G/F/X operators.
    if not re.search(r"\b(G|F|X|U|bound\s*=)\b", body):
        return _refuse(
            obligation,
            contract_id=contract.contract_id,
            status=LoweringStatus.UNSUPPORTED,
            logic_family=LogicFamily.TEMPORAL,
            payload_kind=ObligationPayloadKind.TEMPORAL_FORMULA,
            reason="temporal formula must use bounded LTL operators (G/F/X/U) or bound=",
            theory=TheoryFragment.LTL_BOUNDED,
            soundness_scope_id=contract.soundness_scope.scope_id,
        )
    return LoweredForm(
        form_id=f"form.{obligation.obligation_id}.{contract.contract_id}",
        obligation_id=obligation.obligation_id,
        model_digest=obligation.model_digest,
        contract_id=contract.contract_id,
        status=LoweringStatus.COMPILED,
        logic_family=LogicFamily.TEMPORAL,
        payload_kind=ObligationPayloadKind.TEMPORAL_FORMULA,
        body=body if body.endswith("\n") else body + "\n",
        theory=TheoryFragment.LTL_BOUNDED,
        soundness_scope_id=contract.soundness_scope.scope_id,
        may_submit=True,
        reason="bounded LTL fragment accepted",
        assumption_ids=obligation.trusted_assumption_ids
        + contract.soundness_scope.assumptions,
        exclusion_ids=contract.soundness_scope.exclusions,
    )


def _lower_opaque_refuse(
    obligation: FormalObligation, contract: LoweringContract
) -> LoweredForm:
    return _refuse(
        obligation,
        contract_id=contract.contract_id,
        status=LoweringStatus.OPAQUE_REFUSED,
        logic_family=LogicFamily.OPAQUE,
        payload_kind=obligation.payload_kind,
        reason=(
            f"refused opaque payload kind {obligation.payload_kind.value}: "
            f"{OPAQUE_SECURITY_VERIFICATION_CONDITION!r} / prose never compile "
            "into an executable solver family"
        ),
        soundness_scope_id=contract.soundness_scope.scope_id,
        attributes={
            "opaque_family": OPAQUE_SECURITY_VERIFICATION_CONDITION,
            "payload_kind": obligation.payload_kind.value,
        },
    )


_Lowerer = Callable[[FormalObligation, LoweringContract], LoweredForm]


def default_lowering_contracts() -> tuple[LoweringContract, ...]:
    """Reviewed built-in lowering contracts for Crypto IR formalization."""

    prop_scope = SoundnessScope(
        scope_id="scope.propositional.qf-bool",
        description=(
            "Sound for quantifier-free boolean obligations under a complete "
            "finite model of the named facts; excludes arithmetic, heaps, and "
            "unbounded concurrency."
        ),
        assumptions=("finite-fact-universe", "closed-world-named-atoms"),
        exclusions=("arithmetic", "heap", "unbounded-reentrancy", "quantifiers"),
        model_completeness_required=True,
        max_quantifier_depth=0,
    )
    smt_scope = SoundnessScope(
        scope_id="scope.smt.qf-bool-lia-bv",
        description=(
            "Sound for QF_BOOL / QF_LIA / QF_BV SMT-LIB fragments under the "
            "declared bitwidth and complete model facts."
        ),
        assumptions=("complete-required-facts", "trusted-assumption-ids-held"),
        exclusions=("full-EVM-semantics", "unbounded-loops", "external-oracles"),
        model_completeness_required=True,
        max_quantifier_depth=0,
        max_bitwidth=256,
    )
    fol_scope = SoundnessScope(
        scope_id="scope.fol.core-bounded",
        description="Sound for FOL core with quantifier depth at most 1.",
        assumptions=("complete-required-facts",),
        exclusions=("higher-order", "unbounded-quantifier-alternation"),
        model_completeness_required=True,
        max_quantifier_depth=1,
    )
    datalog_scope = SoundnessScope(
        scope_id="scope.datalog.positive",
        description="Sound for positive (negation-free) Datalog over finite EDB.",
        assumptions=("finite-edb", "positive-rules-only"),
        exclusions=("negation", "aggregation", "function-symbols"),
        model_completeness_required=True,
    )
    temporal_scope = SoundnessScope(
        scope_id="scope.temporal.ltl-bounded",
        description="Sound for bounded LTL monitor formulas only; not theorem proof.",
        assumptions=("finite-trace-bound",),
        exclusions=("unbounded-liveness", "branching-time-ctl"),
        model_completeness_required=True,
    )
    opaque_scope = SoundnessScope(
        scope_id="scope.opaque.refuse",
        description=(
            "Explicit non-lowering for opaque security_verification_condition "
            "JSON and prose; never executable."
        ),
        assumptions=(),
        exclusions=("all-solver-backends",),
        model_completeness_required=False,
    )
    return (
        LoweringContract(
            contract_id="lowering.propositional.v1",
            source_payload_kinds=(
                ObligationPayloadKind.PROPOSITIONAL_FORMULA,
                ObligationPayloadKind.COMPILED_SMT_LIB,
            ),
            target_logic_family=LogicFamily.PROPOSITIONAL,
            supported_theories=(TheoryFragment.PROPOSITIONAL, TheoryFragment.QF_BOOL),
            soundness_scope=prop_scope,
            formal_target_kinds=(
                FormalTargetKind.PROPOSITIONAL,
                FormalTargetKind.DETERMINISTIC,
            ),
            backend_families=("propositional", "z3", "cvc5"),
            produces_executable=True,
            description="Propositional / QF_BOOL lowering",
        ),
        LoweringContract(
            contract_id="lowering.smt-lib.v1",
            source_payload_kinds=(ObligationPayloadKind.COMPILED_SMT_LIB,),
            target_logic_family=LogicFamily.SMT_LIB,
            supported_theories=(
                TheoryFragment.QF_BOOL,
                TheoryFragment.QF_LIA,
                TheoryFragment.QF_BV,
            ),
            soundness_scope=smt_scope,
            formal_target_kinds=(FormalTargetKind.SMT_LIB,),
            backend_families=("z3", "cvc5"),
            produces_executable=True,
            description="Bounded SMT-LIB lowering for Z3/CVC5",
        ),
        LoweringContract(
            contract_id="lowering.fol.v1",
            source_payload_kinds=(ObligationPayloadKind.FOL_FORMULA,),
            target_logic_family=LogicFamily.FOL,
            supported_theories=(TheoryFragment.FOL_CORE,),
            soundness_scope=fol_scope,
            formal_target_kinds=(FormalTargetKind.FOL,),
            backend_families=("z3", "cvc5"),
            produces_executable=True,
            description="Bounded FOL core lowering",
        ),
        LoweringContract(
            contract_id="lowering.datalog.v1",
            source_payload_kinds=(ObligationPayloadKind.DATALOG_RULES,),
            target_logic_family=LogicFamily.DATALOG,
            supported_theories=(TheoryFragment.DATALOG_POSITIVE,),
            soundness_scope=datalog_scope,
            formal_target_kinds=(FormalTargetKind.DATALOG,),
            backend_families=("datalog",),
            produces_executable=True,
            description="Positive Datalog lowering",
        ),
        LoweringContract(
            contract_id="lowering.temporal.v1",
            source_payload_kinds=(ObligationPayloadKind.TEMPORAL_FORMULA,),
            target_logic_family=LogicFamily.TEMPORAL,
            supported_theories=(TheoryFragment.LTL_BOUNDED,),
            soundness_scope=temporal_scope,
            formal_target_kinds=(FormalTargetKind.TEMPORAL, FormalTargetKind.MONITOR),
            backend_families=("temporal-monitor",),
            produces_executable=True,
            description="Bounded LTL temporal lowering (monitor authority only)",
        ),
        LoweringContract(
            contract_id="lowering.opaque-refuse.v1",
            source_payload_kinds=(
                ObligationPayloadKind.SECURITY_VERIFICATION_CONDITION,
                ObligationPayloadKind.PROSE,
                ObligationPayloadKind.UNSUPPORTED,
                ObligationPayloadKind.EMPTY,
            ),
            target_logic_family=LogicFamily.OPAQUE,
            supported_theories=(TheoryFragment.NONE,),
            soundness_scope=opaque_scope,
            formal_target_kinds=(),
            backend_families=(),
            produces_executable=False,
            description="Refuse opaque SVC JSON and prose",
        ),
    )


_DEFAULT_LOWERERS: Final[Mapping[str, _Lowerer]] = {
    "lowering.propositional.v1": _lower_propositional,
    "lowering.smt-lib.v1": _lower_smt_lib,
    "lowering.fol.v1": _lower_fol,
    "lowering.datalog.v1": _lower_datalog,
    "lowering.temporal.v1": _lower_temporal,
    "lowering.opaque-refuse.v1": _lower_opaque_refuse,
}


class ObligationCompiler:
    """Compile formal obligations through reviewed lowering contracts.

    The compiler never executes a solver.  Submission is gated by
    :attr:`LoweredForm.may_submit` and the target backend's declared logic
    families (see :mod:`.portfolio`).
    """

    def __init__(
        self,
        contracts: Sequence[LoweringContract] | None = None,
        *,
        lowerers: Mapping[str, _Lowerer] | None = None,
        require_complete_model: bool = True,
    ) -> None:
        self._contracts: tuple[LoweringContract, ...] = tuple(
            contracts if contracts is not None else default_lowering_contracts()
        )
        if not self._contracts:
            raise FormalizationError("ObligationCompiler requires at least one contract")
        by_id = {c.contract_id: c for c in self._contracts}
        if len(by_id) != len(self._contracts):
            raise FormalizationError("lowering contract ids must be unique")
        self._by_id = by_id
        self._lowerers: dict[str, _Lowerer] = dict(_DEFAULT_LOWERERS)
        if lowerers:
            self._lowerers.update(lowerers)
        self._require_complete_model = bool(require_complete_model)

    @property
    def contracts(self) -> tuple[LoweringContract, ...]:
        return self._contracts

    def contract_by_id(self, contract_id: str) -> LoweringContract:
        try:
            return self._by_id[contract_id]
        except KeyError as exc:
            raise FormalizationError(f"unknown lowering contract: {contract_id!r}") from exc

    def select_contract(
        self, obligation: FormalObligation
    ) -> LoweringContract | None:
        """Return the first matching contract, preferring executable ones."""

        kind = obligation.payload_kind
        # Opaque / prose / empty always route to the refuse contract when present.
        if kind in NON_EXECUTABLE_PAYLOAD_KINDS:
            for contract in self._contracts:
                if (
                    not contract.produces_executable
                    and contract.accepts(obligation, payload_kind=kind)
                ):
                    return contract
        candidates = [
            c
            for c in self._contracts
            if c.produces_executable and c.accepts(obligation, payload_kind=kind)
        ]
        if candidates:
            return candidates[0]
        for contract in self._contracts:
            if contract.accepts(obligation, payload_kind=kind):
                return contract
        return None

    def compile(
        self,
        obligation: FormalObligation,
        *,
        model_complete: bool = True,
        missing_fact_ids: Sequence[str] = (),
    ) -> LoweredForm:
        """Lower *obligation* or return an explicit non-executable form."""

        if not isinstance(obligation, FormalObligation):
            raise FormalizationError("compile requires a FormalObligation")

        missing = tuple(missing_fact_ids)
        if missing or (self._require_complete_model and not model_complete):
            contract = self.select_contract(obligation)
            scope_id = (
                contract.soundness_scope.scope_id
                if contract is not None
                else "scope.none"
            )
            return _refuse(
                obligation,
                contract_id=contract.contract_id if contract else "lowering.none",
                status=LoweringStatus.INCOMPLETE_MODEL,
                logic_family=logic_family_for_formal_target(
                    obligation.formal_target_kind
                ),
                payload_kind=obligation.payload_kind,
                reason=(
                    "incomplete model: missing facts "
                    f"{list(missing) if missing else ['<model_complete=false>']}"
                ),
                soundness_scope_id=scope_id,
                attributes={"missing_fact_ids": list(missing)},
            )

        # Re-detect payload kind so callers cannot smuggle opaque JSON under a
        # compiled kind label without matching body shape.
        detected = detect_payload_kind(
            obligation.payload,
            formal_target_kind=obligation.formal_target_kind,
            declared_kind=None,
        )
        if (
            obligation.payload_kind in NON_EXECUTABLE_PAYLOAD_KINDS
            or detected in NON_EXECUTABLE_PAYLOAD_KINDS
        ):
            # Force opaque refuse path even if declared kind claimed compiled.
            effective = FormalObligation(
                obligation_id=obligation.obligation_id,
                category=obligation.category,
                statement=obligation.statement,
                formal_target=obligation.formal_target,
                formal_target_kind=obligation.formal_target_kind,
                model_digest=obligation.model_digest,
                required_fact_ids=obligation.required_fact_ids,
                required_semantic_dimensions=obligation.required_semantic_dimensions,
                payload=obligation.payload,
                payload_kind=detected
                if detected in NON_EXECUTABLE_PAYLOAD_KINDS
                else obligation.payload_kind,
                trusted_assumption_ids=obligation.trusted_assumption_ids,
                policy_id=obligation.policy_id,
                policy_revision=obligation.policy_revision,
                capability_ids=obligation.capability_ids,
                code_epoch=obligation.code_epoch,
                violation_witness=obligation.violation_witness,
                summary=obligation.summary,
                attributes=dict(obligation.attributes),
            )
            contract = self.select_contract(effective)
            if contract is None:
                return _refuse(
                    effective,
                    contract_id="lowering.none",
                    status=LoweringStatus.OPAQUE_REFUSED,
                    logic_family=LogicFamily.OPAQUE,
                    payload_kind=effective.payload_kind,
                    reason="no contract for opaque/non-executable payload",
                )
            lowerer = self._lowerers.get(contract.contract_id, _lower_opaque_refuse)
            return lowerer(effective, contract)

        contract = self.select_contract(obligation)
        if contract is None:
            return _refuse(
                obligation,
                contract_id="lowering.none",
                status=LoweringStatus.NOT_MODELED,
                logic_family=logic_family_for_formal_target(
                    obligation.formal_target_kind
                ),
                payload_kind=obligation.payload_kind,
                reason=(
                    f"no lowering contract for payload kind "
                    f"{obligation.payload_kind.value} / "
                    f"{obligation.formal_target_kind.value}"
                ),
            )
        lowerer = self._lowerers.get(contract.contract_id)
        if lowerer is None:
            return _refuse(
                obligation,
                contract_id=contract.contract_id,
                status=LoweringStatus.ERROR,
                logic_family=contract.target_logic_family,
                payload_kind=obligation.payload_kind,
                reason=f"no lowerer registered for contract {contract.contract_id}",
                soundness_scope_id=contract.soundness_scope.scope_id,
            )
        result = lowerer(obligation, contract)
        # Final hard gate: never mark may_submit if contract is non-executable.
        if not contract.produces_executable and result.may_submit:
            return LoweredForm(
                form_id=result.form_id,
                obligation_id=result.obligation_id,
                model_digest=result.model_digest,
                contract_id=result.contract_id,
                status=LoweringStatus.OPAQUE_REFUSED,
                logic_family=result.logic_family,
                payload_kind=result.payload_kind,
                body="",
                theory=result.theory,
                soundness_scope_id=result.soundness_scope_id,
                may_submit=False,
                reason="contract produces_executable is false",
                assumption_ids=result.assumption_ids,
                exclusion_ids=result.exclusion_ids,
                attributes=dict(result.attributes),
            )
        return result

    def compile_many(
        self,
        obligations: Iterable[FormalObligation],
        *,
        model_complete: bool = True,
        missing_fact_ids: Sequence[str] = (),
    ) -> tuple[LoweredForm, ...]:
        return tuple(
            self.compile(
                item,
                model_complete=model_complete,
                missing_fact_ids=missing_fact_ids,
            )
            for item in obligations
        )


__all__ = [
    "COMPILER_VERSION",
    "LOWERED_FORM_SCHEMA_VERSION",
    "LOWERING_CONTRACT_SCHEMA_VERSION",
    "LoweredForm",
    "LoweringContract",
    "LoweringStatus",
    "ObligationCompiler",
    "SoundnessScope",
    "TheoryFragment",
    "default_lowering_contracts",
]

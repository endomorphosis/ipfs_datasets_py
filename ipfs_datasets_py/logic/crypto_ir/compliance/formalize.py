"""Formal lowering of compliance rules and exposure into supported logic.

CRYPTOIR-G430 compiles explicit sanctions, ownership, direct-counterparty,
freshness, and risk-policy rules into *executable supported* forms with
completeness-qualified negative conclusions.

Unsupported theories, opaque prose, and truncated searches fail closed:
they never produce a claimed proof of absence or a designation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.crypto_ir.formalization.compiler import TheoryFragment
from ipfs_datasets_py.logic.crypto_ir.formalization.obligations import (
    LogicFamily,
    ObligationPayloadKind,
)
from ipfs_datasets_py.logic.crypto_ir.identity import crypto_ir_identity
from ipfs_datasets_py.logic.crypto_ir.provenance import AuthorityKind
from ipfs_datasets_py.logic.crypto_ir.schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.provenance import thaw_json

from .exposure import (
    BoundedExposure,
    ExposurePolicy,
    ExposureVerdict,
)
from .models import (
    CRYPTO_IR_COMPLIANCE_DOMAIN,
    ComplianceModelError,
    SanctionsPolicyOutcome,
    _digest,
    _identifier,
    _known,
    _mapping,
    _text,
)
from .rules import (
    CompliancePredicate,
    ComplianceRule,
    ComplianceRuleKind,
    ComplianceRuleSet,
    RuleEvaluationResult,
)


FORMALIZE_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.compliance-formalize@1.0.0"
)
FORMALIZER_VERSION: Final[str] = "1.0.0"

# Rule kinds this formalizer knows how to lower.
_SUPPORTED_KINDS: Final[frozenset[ComplianceRuleKind]] = frozenset(ComplianceRuleKind)

# Theories this formalizer produces.
_SUPPORTED_THEORIES: Final[frozenset[TheoryFragment]] = frozenset(
    {
        TheoryFragment.PROPOSITIONAL,
        TheoryFragment.DATALOG_POSITIVE,
        TheoryFragment.QF_BOOL,
    }
)


class FormalizeError(ComplianceModelError):
    """Raised when formalization inputs are malformed or unsupported."""


class FormalizationStatus(str, Enum):
    """Outcome of compliance formalization (never a theorem-prover claim)."""

    COMPILED = "compiled"
    UNSUPPORTED = "unsupported"
    TRUNCATED_FAIL_CLOSED = "truncated_fail_closed"
    INCOMPLETE_MODEL = "incomplete_model"
    ERROR = "error"


class NegativeConclusionKind(str, Enum):
    """How a negative (no-path / no-match) conclusion is qualified."""

    BOUNDED_ABSENCE = "bounded_absence"
    """No path within bounds under a COMPLETE completeness frontier."""

    UNSCOPED = "unscoped"
    """Must never be emitted — reserved to catch bugs."""

    NOT_APPLICABLE = "not_applicable"
    """Positive findings or non-absence verdicts."""

    REFUSED = "refused"
    """Truncation or incomplete frontier: absence not proved."""


def _enum(enum_type: type[Any], value: Any, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise FormalizeError(f"unsupported {name}: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class FormalClause:
    """One executable clause in a supported logic fragment."""

    clause_id: str
    predicate: str
    head: str
    body: tuple[str, ...]
    theory: TheoryFragment
    source_rule_id: str = ""
    executable: bool = True
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "clause_id", _identifier(self.clause_id, "clause_id"))
        object.__setattr__(self, "predicate", _text(self.predicate, "predicate"))
        object.__setattr__(self, "head", _text(self.head, "head"))
        body = tuple(_text(item, "body") for item in self.body)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "theory", _enum(TheoryFragment, self.theory, "theory"))
        object.__setattr__(
            self,
            "source_rule_id",
            _text(self.source_rule_id, "source_rule_id", allow_empty=True),
        )
        if type(self.executable) is not bool:
            raise FormalizeError("executable must be a boolean")
        object.__setattr__(
            self, "notes", tuple(_text(n, "notes") for n in self.notes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": list(self.body),
            "clause_id": self.clause_id,
            "executable": self.executable,
            "head": self.head,
            "notes": list(self.notes),
            "predicate": self.predicate,
            "source_rule_id": self.source_rule_id,
            "theory": self.theory.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalClause":
        value = _mapping(value, "FormalClause")
        return cls(
            clause_id=value.get("clause_id", ""),
            predicate=value.get("predicate", ""),
            head=value.get("head", ""),
            body=tuple(value.get("body", ())),
            theory=value.get("theory", TheoryFragment.PROPOSITIONAL.value),
            source_rule_id=value.get("source_rule_id", ""),
            executable=bool(value.get("executable", True)),
            notes=tuple(value.get("notes", ())),
        )


@dataclass(frozen=True, slots=True)
class FormalizedCompliance:
    """Compiled compliance program bound to exact policy/graph/list digests.

    ``negative_conclusion`` is completeness-qualified.  Truncation and
    incomplete frontiers yield ``REFUSED`` rather than a false global absence.
    """

    formalization_id: str
    status: FormalizationStatus
    logic_family: LogicFamily
    payload_kind: ObligationPayloadKind
    theory: TheoryFragment
    clauses: tuple[FormalClause, ...]
    executable: bool
    rule_set_id: str = ""
    rule_set_revision: str = ""
    rules_digest: str = ""
    exposure_id: str = ""
    exposure_verdict: str = ""
    policy_outcome: SanctionsPolicyOutcome | None = None
    negative_conclusion: NegativeConclusionKind = NegativeConclusionKind.NOT_APPLICABLE
    completeness_status: str = ""
    graph_snapshot_id: str = ""
    graph_digest: str = ""
    list_snapshot_id: str = ""
    list_revision: str = ""
    exposure_policy_digest: str = ""
    reason_codes: tuple[str, ...] = ()
    smt_lib_fragment: str = ""
    datalog_fragment: str = ""
    propositional_fragment: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FORMALIZE_SCHEMA_VERSION
    formalizer_version: str = FORMALIZER_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "formalization_id",
            _identifier(self.formalization_id, "formalization_id"),
        )
        object.__setattr__(
            self, "status", _enum(FormalizationStatus, self.status, "status")
        )
        object.__setattr__(
            self, "logic_family", _enum(LogicFamily, self.logic_family, "logic_family")
        )
        object.__setattr__(
            self,
            "payload_kind",
            _enum(ObligationPayloadKind, self.payload_kind, "payload_kind"),
        )
        object.__setattr__(self, "theory", _enum(TheoryFragment, self.theory, "theory"))
        clauses = tuple(
            item
            if isinstance(item, FormalClause)
            else FormalClause.from_dict(_mapping(item, "clauses"))
            for item in self.clauses
        )
        object.__setattr__(self, "clauses", clauses)
        if type(self.executable) is not bool:
            raise FormalizeError("executable must be a boolean")
        # Fail closed: non-compiled statuses are never executable.
        if self.status is not FormalizationStatus.COMPILED and self.executable:
            raise FormalizeError(
                "non-compiled formalization must not be marked executable"
            )
        if self.status is FormalizationStatus.COMPILED and not self.executable:
            raise FormalizeError("compiled formalization must be executable")
        if self.theory not in _SUPPORTED_THEORIES and self.executable:
            raise FormalizeError(
                f"theory {self.theory.value} is not supported for executable lowering"
            )
        for name in (
            "rule_set_id",
            "rule_set_revision",
            "exposure_id",
            "exposure_verdict",
            "completeness_status",
            "graph_snapshot_id",
            "graph_digest",
            "list_snapshot_id",
            "list_revision",
            "exposure_policy_digest",
            "smt_lib_fragment",
            "datalog_fragment",
            "propositional_fragment",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        if self.rules_digest:
            object.__setattr__(
                self, "rules_digest", _digest(self.rules_digest, "rules_digest")
            )
        if self.policy_outcome is not None:
            object.__setattr__(
                self,
                "policy_outcome",
                _enum(SanctionsPolicyOutcome, self.policy_outcome, "policy_outcome"),
            )
        object.__setattr__(
            self,
            "negative_conclusion",
            _enum(
                NegativeConclusionKind,
                self.negative_conclusion,
                "negative_conclusion",
            ),
        )
        if self.negative_conclusion is NegativeConclusionKind.UNSCOPED:
            raise FormalizeError(
                "unscoped negative conclusions are forbidden "
                "(incomplete search never proves global absence)"
            )
        codes = tuple(_identifier(c, "reason_codes") for c in self.reason_codes)
        if len(codes) != len(set(codes)):
            raise FormalizeError("reason_codes must be unique")
        object.__setattr__(self, "reason_codes", codes)
        if not isinstance(self.attributes, Mapping):
            raise FormalizeError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))
        if self.schema_version != FORMALIZE_SCHEMA_VERSION:
            raise FormalizeError(
                f"unsupported formalize schema: {self.schema_version}"
            )
        object.__setattr__(
            self, "formalizer_version", _text(self.formalizer_version, "formalizer_version")
        )

    @property
    def claims_global_absence(self) -> bool:
        """Always False: formalization never claims the unobserved world is empty."""

        return False

    @property
    def declares_designation(self) -> bool:
        return False

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.formalized-compliance",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(dict(self.attributes)),
            "claims_global_absence": self.claims_global_absence,
            "clauses": [c.to_dict() for c in self.clauses],
            "completeness_status": self.completeness_status,
            "datalog_fragment": self.datalog_fragment,
            "declares_designation": self.declares_designation,
            "executable": self.executable,
            "exposure_id": self.exposure_id,
            "exposure_policy_digest": self.exposure_policy_digest,
            "exposure_verdict": self.exposure_verdict,
            "formalization_id": self.formalization_id,
            "formalizer_version": self.formalizer_version,
            "graph_digest": self.graph_digest,
            "graph_snapshot_id": self.graph_snapshot_id,
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "logic_family": self.logic_family.value,
            "negative_conclusion": self.negative_conclusion.value,
            "payload_kind": self.payload_kind.value,
            "policy_outcome": None
            if self.policy_outcome is None
            else self.policy_outcome.value,
            "propositional_fragment": self.propositional_fragment,
            "reason_codes": list(self.reason_codes),
            "rule_set_id": self.rule_set_id,
            "rule_set_revision": self.rule_set_revision,
            "rules_digest": self.rules_digest,
            "schema_version": self.schema_version,
            "smt_lib_fragment": self.smt_lib_fragment,
            "status": self.status.value,
            "theory": self.theory.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizedCompliance":
        value = _mapping(value, "FormalizedCompliance")
        fields = frozenset(
            {
                "formalization_id",
                "status",
                "logic_family",
                "payload_kind",
                "theory",
                "clauses",
                "executable",
                "rule_set_id",
                "rule_set_revision",
                "rules_digest",
                "exposure_id",
                "exposure_verdict",
                "policy_outcome",
                "negative_conclusion",
                "completeness_status",
                "graph_snapshot_id",
                "graph_digest",
                "list_snapshot_id",
                "list_revision",
                "exposure_policy_digest",
                "reason_codes",
                "smt_lib_fragment",
                "datalog_fragment",
                "propositional_fragment",
                "attributes",
                "schema_version",
                "formalizer_version",
                "claims_global_absence",
                "declares_designation",
            }
        )
        _known(value, fields, "FormalizedCompliance")
        outcome = value.get("policy_outcome")
        return cls(
            formalization_id=value.get("formalization_id", ""),
            status=value.get("status", ""),
            logic_family=value.get("logic_family", ""),
            payload_kind=value.get("payload_kind", ""),
            theory=value.get("theory", ""),
            clauses=tuple(
                FormalClause.from_dict(item) for item in value.get("clauses", ())
            ),
            executable=bool(value.get("executable", False)),
            rule_set_id=value.get("rule_set_id", ""),
            rule_set_revision=value.get("rule_set_revision", ""),
            rules_digest=value.get("rules_digest", ""),
            exposure_id=value.get("exposure_id", ""),
            exposure_verdict=value.get("exposure_verdict", ""),
            policy_outcome=None if outcome in (None, "") else outcome,
            negative_conclusion=value.get(
                "negative_conclusion", NegativeConclusionKind.NOT_APPLICABLE.value
            ),
            completeness_status=value.get("completeness_status", ""),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            graph_digest=value.get("graph_digest", ""),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            exposure_policy_digest=value.get("exposure_policy_digest", ""),
            reason_codes=tuple(value.get("reason_codes", ())),
            smt_lib_fragment=value.get("smt_lib_fragment", ""),
            datalog_fragment=value.get("datalog_fragment", ""),
            propositional_fragment=value.get("propositional_fragment", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", FORMALIZE_SCHEMA_VERSION),
            formalizer_version=value.get("formalizer_version", FORMALIZER_VERSION),
        )


class ComplianceFormalizer:
    """Compile compliance rules and exposure facts into supported logic forms.

    The formalizer is deliberately offline and pure.  It does not invoke a
    solver backend; it produces a reviewed, executable *payload* that a
    portfolio may later submit only when the status is ``COMPILED``.
    """

    def __init__(
        self,
        *,
        preferred_theory: TheoryFragment = TheoryFragment.DATALOG_POSITIVE,
        fail_closed_on_truncation: bool = True,
        fail_closed_on_incomplete: bool = True,
    ) -> None:
        preferred_theory = _enum(TheoryFragment, preferred_theory, "preferred_theory")
        if preferred_theory not in _SUPPORTED_THEORIES:
            raise FormalizeError(
                f"preferred_theory {preferred_theory.value} is not supported"
            )
        if type(fail_closed_on_truncation) is not bool:
            raise FormalizeError("fail_closed_on_truncation must be a boolean")
        if type(fail_closed_on_incomplete) is not bool:
            raise FormalizeError("fail_closed_on_incomplete must be a boolean")
        self.preferred_theory = preferred_theory
        self.fail_closed_on_truncation = fail_closed_on_truncation
        self.fail_closed_on_incomplete = fail_closed_on_incomplete

    def formalize(
        self,
        rule_set: ComplianceRuleSet,
        *,
        exposure: BoundedExposure | None = None,
        exposure_policy: ExposurePolicy | None = None,
        evaluation: RuleEvaluationResult | None = None,
        extra_facts: Sequence[str] = (),
    ) -> FormalizedCompliance:
        """Lower rules (+ optional exposure/eval) into a FormalizedCompliance."""

        if not isinstance(rule_set, ComplianceRuleSet):
            raise FormalizeError("rule_set must be a ComplianceRuleSet")

        reason_codes: list[str] = []
        clauses: list[FormalClause] = []

        # Fail closed on truncation before producing a positive absence claim.
        if (
            exposure is not None
            and exposure.truncated
            and self.fail_closed_on_truncation
        ):
            return self._refuse(
                rule_set=rule_set,
                exposure=exposure,
                exposure_policy=exposure_policy,
                status=FormalizationStatus.TRUNCATED_FAIL_CLOSED,
                reason_codes=(
                    "unsupported_lowering_or_truncation_fails_closed",
                    "search_truncated",
                    *exposure.truncation_reasons,
                ),
                negative=NegativeConclusionKind.REFUSED,
            )

        if (
            exposure is not None
            and exposure.verdict is ExposureVerdict.INCOMPLETE_FRONTIER
            and self.fail_closed_on_incomplete
        ):
            return self._refuse(
                rule_set=rule_set,
                exposure=exposure,
                exposure_policy=exposure_policy,
                status=FormalizationStatus.INCOMPLETE_MODEL,
                reason_codes=(
                    "incomplete_completeness_frontier",
                    "absence_not_proved",
                ),
                negative=NegativeConclusionKind.REFUSED,
            )

        unsupported = [
            r
            for r in rule_set.rules
            if r.kind not in _SUPPORTED_KINDS or r.elevates_to_designation
        ]
        if unsupported:
            return self._refuse(
                rule_set=rule_set,
                exposure=exposure,
                exposure_policy=exposure_policy,
                status=FormalizationStatus.UNSUPPORTED,
                reason_codes=("unsupported_rule_kind_or_elevation",),
                negative=NegativeConclusionKind.NOT_APPLICABLE,
            )

        theory = self.preferred_theory
        for rule in rule_set.enabled_rules():
            clauses.extend(self._lower_rule(rule, theory))

        # Ground facts from exposure paths.
        if exposure is not None:
            clauses.extend(self._lower_exposure_facts(exposure, theory))
            reason_codes.extend(exposure.reason_codes)

        if evaluation is not None:
            for hit in evaluation.hits:
                clauses.append(
                    FormalClause(
                        clause_id=f"clause:hit:{hit.rule_id}:{hit.reason_code}",
                        predicate=hit.predicate.value,
                        head=f"RuleHit({hit.rule_id},{hit.outcome.value})",
                        body=(
                            f"reason={hit.reason_code}",
                            *(f"path={pid}" for pid in hit.path_ids),
                            *(f"evidence={eid}" for eid in hit.evidence_ids),
                        ),
                        theory=theory,
                        source_rule_id=hit.rule_id,
                        notes=("ground_hit",),
                    )
                )
            reason_codes.extend(evaluation.reason_codes)

        for index, fact in enumerate(extra_facts):
            text = _text(fact, "extra_facts")
            clauses.append(
                FormalClause(
                    clause_id=f"clause:fact:{index}",
                    predicate="Fact",
                    head=text,
                    body=(),
                    theory=theory,
                    notes=("injected_fact",),
                )
            )

        negative = NegativeConclusionKind.NOT_APPLICABLE
        if exposure is not None:
            if exposure.proves_no_connection:
                negative = NegativeConclusionKind.BOUNDED_ABSENCE
                reason_codes.append("bounded_absence_under_completeness_frontier")
                clauses.append(
                    FormalClause(
                        clause_id="clause:bounded-absence",
                        predicate=CompliancePredicate.BOUNDED_EXPOSURE.value,
                        head="NoPathWithinBounds(origin, targets, policy, frontier)",
                        body=(
                            f"origin={exposure.origin_node_id}",
                            f"frontier={exposure.frontier.status.value if exposure.frontier else 'none'}",
                            "scope=pinned_graph_list_policy_snapshots",
                            "not_global_absence",
                        ),
                        theory=theory,
                        notes=(
                            "completeness_qualified_negative",
                            "never_claims_global_absence",
                        ),
                    )
                )
            elif not exposure.paths:
                negative = NegativeConclusionKind.REFUSED
                reason_codes.append("absence_not_proved")

        smt = self._render_smt(clauses, exposure, rule_set)
        datalog = self._render_datalog(clauses)
        prop = self._render_propositional(clauses)

        policy_outcome: SanctionsPolicyOutcome | None = None
        if evaluation is not None:
            policy_outcome = evaluation.outcome
        elif exposure is not None:
            policy_outcome = exposure.policy_outcome

        logic_family, payload_kind = self._family_for_theory(theory)
        material = "\x00".join(
            (
                rule_set.rule_set_id,
                rule_set.revision,
                rule_set.rules_digest,
                exposure.exposure_id if exposure else "",
                theory.value,
                FORMALIZER_VERSION,
            )
        ).encode("utf-8")
        formalization_id = (
            f"formalize:{hashlib.sha256(material).hexdigest()[:40]}"
        )

        return FormalizedCompliance(
            formalization_id=formalization_id,
            status=FormalizationStatus.COMPILED,
            logic_family=logic_family,
            payload_kind=payload_kind,
            theory=theory,
            clauses=tuple(clauses),
            executable=True,
            rule_set_id=rule_set.rule_set_id,
            rule_set_revision=rule_set.revision,
            rules_digest=rule_set.rules_digest,
            exposure_id=exposure.exposure_id if exposure else "",
            exposure_verdict=exposure.verdict.value if exposure else "",
            policy_outcome=policy_outcome,
            negative_conclusion=negative,
            completeness_status=(
                exposure.frontier.status.value
                if exposure and exposure.frontier
                else ""
            ),
            graph_snapshot_id=exposure.graph_snapshot_id if exposure else "",
            graph_digest=exposure.graph_digest if exposure else "",
            list_snapshot_id=exposure.list_snapshot_id if exposure else "",
            list_revision=exposure.list_revision if exposure else "",
            exposure_policy_digest=(
                exposure_policy.rules_digest
                if exposure_policy is not None
                else (exposure.policy.rules_digest if exposure else "")
            ),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            smt_lib_fragment=smt,
            datalog_fragment=datalog,
            propositional_fragment=prop,
            attributes={
                "never_infers_unlimited_transitive_guilt": True,
                "never_claims_global_absence": True,
                "never_declares_designation": True,
                "clause_count": len(clauses),
            },
        )

    def _refuse(
        self,
        *,
        rule_set: ComplianceRuleSet,
        exposure: BoundedExposure | None,
        exposure_policy: ExposurePolicy | None,
        status: FormalizationStatus,
        reason_codes: Sequence[str],
        negative: NegativeConclusionKind,
    ) -> FormalizedCompliance:
        material = "\x00".join(
            (
                rule_set.rule_set_id,
                status.value,
                *reason_codes,
            )
        ).encode("utf-8")
        formalization_id = (
            f"formalize:{hashlib.sha256(material).hexdigest()[:40]}"
        )
        return FormalizedCompliance(
            formalization_id=formalization_id,
            status=status,
            logic_family=LogicFamily.UNSUPPORTED,
            payload_kind=ObligationPayloadKind.UNSUPPORTED,
            theory=TheoryFragment.NONE,
            clauses=(),
            executable=False,
            rule_set_id=rule_set.rule_set_id,
            rule_set_revision=rule_set.revision,
            rules_digest=rule_set.rules_digest,
            exposure_id=exposure.exposure_id if exposure else "",
            exposure_verdict=exposure.verdict.value if exposure else "",
            policy_outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
            negative_conclusion=negative,
            completeness_status=(
                exposure.frontier.status.value
                if exposure and exposure.frontier
                else ""
            ),
            graph_snapshot_id=exposure.graph_snapshot_id if exposure else "",
            graph_digest=exposure.graph_digest if exposure else "",
            list_snapshot_id=exposure.list_snapshot_id if exposure else "",
            list_revision=exposure.list_revision if exposure else "",
            exposure_policy_digest=(
                exposure_policy.rules_digest
                if exposure_policy is not None
                else (exposure.policy.rules_digest if exposure else "")
            ),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            attributes={
                "fail_closed": True,
                "never_claims_global_absence": True,
            },
        )

    def _lower_rule(
        self, rule: ComplianceRule, theory: TheoryFragment
    ) -> list[FormalClause]:
        head = (
            f"{rule.predicate.value}(subject) => Outcome({rule.outcome.value})"
        )
        body = [
            f"kind={rule.kind.value}",
            f"reason={rule.reason_code}",
            "elevates_to_designation=false",
        ]
        if rule.match_level is not None:
            body.append(f"match_level={rule.match_level.value}")
        if rule.ownership_threshold_basis_points is not None:
            body.append(
                f"threshold_bps={rule.ownership_threshold_basis_points}"
            )
        if rule.max_snapshot_age_seconds is not None:
            body.append(f"max_age_s={rule.max_snapshot_age_seconds}")
        return [
            FormalClause(
                clause_id=f"clause:rule:{rule.rule_id}",
                predicate=rule.predicate.value,
                head=head,
                body=tuple(body),
                theory=theory,
                source_rule_id=rule.rule_id,
                notes=("rule_lowering",),
            )
        ]

    def _lower_exposure_facts(
        self, exposure: BoundedExposure, theory: TheoryFragment
    ) -> list[FormalClause]:
        clauses: list[FormalClause] = [
            FormalClause(
                clause_id="clause:exposure-binding",
                predicate=CompliancePredicate.BOUNDED_EXPOSURE.value,
                head=(
                    f"BoundedExposure({exposure.origin_node_id},"
                    f"{exposure.verdict.value})"
                ),
                body=(
                    f"exposure_id={exposure.exposure_id}",
                    f"graph={exposure.graph_snapshot_id}",
                    f"list={exposure.list_snapshot_id}",
                    f"policy={exposure.policy.policy_id}@{exposure.policy.revision}",
                    f"truncated={str(exposure.truncated).lower()}",
                    "claims_designation=false",
                ),
                theory=theory,
                notes=("exposure_binding",),
            )
        ]
        for path in exposure.paths:
            kind = "DirectHit" if (path.is_direct or path.depth == 0) else "IndirectPath"
            clauses.append(
                FormalClause(
                    clause_id=f"clause:path:{path.path_id}",
                    predicate=CompliancePredicate.BOUNDED_EXPOSURE.value,
                    head=f"{kind}({path.origin_node_id},{path.target_node_id},{path.depth})",
                    body=(
                        f"path_id={path.path_id}",
                        f"nodes={','.join(path.node_ids)}",
                        f"edges={','.join(path.edge_ids)}",
                        f"listed={path.listed_identifier or path.target_address_ref}",
                        "claims_designation=false",
                    ),
                    theory=theory,
                    notes=("path_fact", path.explanation()[:200]),
                )
            )
            if path.is_direct or path.depth == 0:
                clauses.append(
                    FormalClause(
                        clause_id=f"clause:listed:{path.path_id}",
                        predicate=CompliancePredicate.LISTED_IDENTIFIER.value,
                        head=f"ListedIdentifier({path.target_node_id})",
                        body=(f"path_id={path.path_id}",),
                        theory=theory,
                        notes=("direct_listed_fact",),
                    )
                )
            else:
                clauses.append(
                    FormalClause(
                        clause_id=f"clause:indirect:{path.path_id}",
                        predicate=CompliancePredicate.BOUNDED_EXPOSURE.value,
                        head=(
                            f"BoundedIndirectExposure({path.origin_node_id},"
                            f"{path.target_node_id})"
                        ),
                        body=(
                            f"depth={path.depth}",
                            "not_a_designation",
                        ),
                        theory=theory,
                        notes=("indirect_exposure_fact",),
                    )
                )
        return clauses

    @staticmethod
    def _family_for_theory(
        theory: TheoryFragment,
    ) -> tuple[LogicFamily, ObligationPayloadKind]:
        if theory is TheoryFragment.DATALOG_POSITIVE:
            return LogicFamily.DATALOG, ObligationPayloadKind.DATALOG_RULES
        if theory is TheoryFragment.PROPOSITIONAL:
            return LogicFamily.PROPOSITIONAL, ObligationPayloadKind.PROPOSITIONAL_FORMULA
        if theory is TheoryFragment.QF_BOOL:
            return LogicFamily.SMT_LIB, ObligationPayloadKind.COMPILED_SMT_LIB
        return LogicFamily.UNSUPPORTED, ObligationPayloadKind.UNSUPPORTED

    @staticmethod
    def _render_smt(
        clauses: Sequence[FormalClause],
        exposure: BoundedExposure | None,
        rule_set: ComplianceRuleSet,
    ) -> str:
        lines = [
            "; crypto-ir compliance formalization (QF_BOOL fragment)",
            f"; rule_set={rule_set.rule_set_id}@{rule_set.revision}",
            f"; rules_digest={rule_set.rules_digest}",
        ]
        if exposure is not None:
            lines.append(f"; exposure_id={exposure.exposure_id}")
            lines.append(f"; verdict={exposure.verdict.value}")
            lines.append("; claims_global_absence=false")
        for clause in clauses:
            atom = (
                clause.head.replace(" ", "_")
                .replace("(", "_")
                .replace(")", "")
                .replace(",", "_")
                .replace("=>", "_implies_")
            )
            safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in atom)
            if not safe:
                safe = "clause"
            lines.append(f"(declare-const {safe[:80]} Bool)")
            lines.append(f"(assert {safe[:80]})")
        lines.append("; end")
        return "\n".join(lines)

    @staticmethod
    def _render_datalog(clauses: Sequence[FormalClause]) -> str:
        lines = ["% crypto-ir compliance datalog (positive)"]
        for clause in clauses:
            if clause.body:
                body = ", ".join(clause.body)
                lines.append(f"{clause.head} :- {body}.")
            else:
                lines.append(f"{clause.head}.")
        return "\n".join(lines)

    @staticmethod
    def _render_propositional(clauses: Sequence[FormalClause]) -> str:
        atoms = []
        for clause in clauses:
            atoms.append(clause.head)
        if not atoms:
            return "true"
        return " AND ".join(f"({a})" for a in atoms)


def formalize_compliance(
    rule_set: ComplianceRuleSet,
    *,
    exposure: BoundedExposure | None = None,
    exposure_policy: ExposurePolicy | None = None,
    evaluation: RuleEvaluationResult | None = None,
    preferred_theory: TheoryFragment = TheoryFragment.DATALOG_POSITIVE,
) -> FormalizedCompliance:
    """Convenience entry point for :class:`ComplianceFormalizer`."""

    formalizer = ComplianceFormalizer(preferred_theory=preferred_theory)
    return formalizer.formalize(
        rule_set,
        exposure=exposure,
        exposure_policy=exposure_policy,
        evaluation=evaluation,
    )


__all__ = [
    "FORMALIZER_VERSION",
    "FORMALIZE_SCHEMA_VERSION",
    "ComplianceFormalizer",
    "FormalClause",
    "FormalizationStatus",
    "FormalizeError",
    "FormalizedCompliance",
    "NegativeConclusionKind",
    "formalize_compliance",
]

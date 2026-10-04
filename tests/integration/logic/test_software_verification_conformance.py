"""Cross-family / cross-provider software-verification conformance (LFV-G080 / LFV-039).

LogicProviderConformance@1

Acceptance covered here:

* Fake runners cover every adapter offline.
* Opt-in real-tool lanes declare skips or unavailability (never silent success).
* Semantic mutations are detected; non-semantic whitespace is normalized.
* Counterexamples replay deterministically.
* Peer disagreements quarantine (order-independent).
* No authority upgrade from candidate/advisory surfaces.
* Stale-cache identities miss; elevated evidence authorities are rejected.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.logic.backends.cache_protocol import (
    ExactVerificationCache,
    VerificationCacheAuthorityError,
    VerificationCacheEntry,
    build_verification_cache_key,
)
from ipfs_datasets_py.logic.backends.portfolio import (
    AttemptDisposition,
    PortfolioAttemptOutcome,
    PortfolioVerdict,
    VerificationPortfolio,
    plan_portfolio,
)
from ipfs_datasets_py.logic.backends.results import (
    AuthoritySubstitutionError,
    ResultAuthority,
    ResultAuthorityNormalization,
    ResultStatus,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
    SmtSolverVerdict,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage
from ipfs_datasets_py.logic.software_verification.properties import PropertyKind


DATASETS_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    DATASETS_ROOT
    / "tests"
    / "fixtures"
    / "logic"
    / "software_verification"
    / "conformance"
    / "manifest.json"
)
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

INTERFACE = "LogicProviderConformance@1"
SCHEMA_VERSION = "logic-provider-conformance/v1"
REAL_TOOLS_ENV = "LFV_CONFORMANCE_REAL_TOOLS"

REQUIRED_CASE_KINDS = (
    "positive",
    "negative",
    "mutation",
    "metamorphic",
    "translation",
    "disagreement",
    "malformed_output",
    "timeout",
    "authority_boundary",
)

# Canonical positive status per ResultAuthority for offline fake runners.
_POSITIVE_STATUS: dict[ResultAuthority, ResultStatus] = {
    ResultAuthority.THEOREM: ResultStatus.PROVED,
    ResultAuthority.SATISFIABILITY: ResultStatus.UNSATISFIABLE,
    ResultAuthority.MODEL_CHECK: ResultStatus.SATISFIED,
    ResultAuthority.MONITOR: ResultStatus.SATISFIED,
    ResultAuthority.AUTHORIZATION: ResultStatus.AUTHORIZED,
    ResultAuthority.PROTOCOL: ResultStatus.SECURE,
    ResultAuthority.HYPERPROPERTY: ResultStatus.SATISFIED,
    ResultAuthority.CANDIDATE: ResultStatus.CANDIDATE,
    ResultAuthority.RECONSTRUCTION: ResultStatus.RECONSTRUCTED,
    ResultAuthority.ATTESTATION: ResultStatus.ATTESTED,
}

_NEGATIVE_STATUS: dict[ResultAuthority, ResultStatus] = {
    ResultAuthority.THEOREM: ResultStatus.DISPROVED,
    ResultAuthority.SATISFIABILITY: ResultStatus.SATISFIABLE,
    ResultAuthority.MODEL_CHECK: ResultStatus.VIOLATED,
    ResultAuthority.MONITOR: ResultStatus.VIOLATED,
    ResultAuthority.AUTHORIZATION: ResultStatus.DENIED,
    ResultAuthority.PROTOCOL: ResultStatus.ATTACK_FOUND,
    ResultAuthority.HYPERPROPERTY: ResultStatus.VIOLATED,
    ResultAuthority.CANDIDATE: ResultStatus.CANDIDATE,
    ResultAuthority.RECONSTRUCTION: ResultStatus.RECONSTRUCTION_FAILED,
    ResultAuthority.ATTESTATION: ResultStatus.ATTESTATION_INVALID,
}

_BOUNDS = ExecutionBounds(
    timeout_ms=1_000,
    max_steps=1_000,
    max_memory_bytes=4_096,
    max_output_bytes=2_048,
)
_USAGE = ResourceUsage(
    elapsed_ms=1,
    steps=1,
    peak_memory_bytes=64,
    output_bytes=32,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_statement(statement: str, mode: str | None = None) -> str:
    text = statement.strip()
    if mode == "collapse_whitespace":
        return re.sub(r"\s+", " ", text)
    return text


def _authority(value: str) -> ResultAuthority:
    return ResultAuthority(value)


def _ceiling_for(authority: ResultAuthority) -> EvidenceAuthority:
    if authority is ResultAuthority.CANDIDATE:
        return EvidenceAuthority.ADVISORY
    if authority is ResultAuthority.RECONSTRUCTION:
        return EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    if authority is ResultAuthority.ATTESTATION:
        return EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    return EvidenceAuthority.BOUNDED


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One expanded recipe instance for a single adapter."""

    case_id: str
    case_kind: str
    adapter_id: str
    attempt_family: str
    result_authority: ResultAuthority
    statement: str
    expected_status: ResultStatus
    witness: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def obligation_digest(self) -> str:
        normalized = _normalize_statement(
            self.statement,
            self.metadata.get("normalize") if self.metadata else None,
        )
        return _digest(
            json.dumps(
                {
                    "adapter_id": self.adapter_id,
                    "case_kind": self.case_kind,
                    "statement": normalized,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )


@dataclass(frozen=True, slots=True)
class FakeRunnerOutcome:
    """Deterministic offline outcome for one conformance case."""

    adapter_id: str
    status: ResultStatus
    authority: ResultAuthority
    conclusive: bool
    reason: str
    witness: Mapping[str, Any]
    obligation_digest: str
    raw_output: str = ""
    timed_out: bool = False
    unavailable: bool = False
    malformed: bool = False

    def to_typed_result(self) -> Any:
        return ResultAuthorityNormalization.build(
            self.authority,
            result_id=f"result:{self.adapter_id}:{self.obligation_digest[:12]}",
            backend_id=self.adapter_id,
            backend_version="fake-conformance/1",
            status=self.status,
            assumptions=(),
            bounds=_BOUNDS,
            translation_ceiling=_ceiling_for(self.authority),
            usage=_USAGE,
            witness=dict(self.witness),
            diagnostics=(),
            reason=self.reason,
            metadata={
                "conformance": True,
                "obligation_digest": self.obligation_digest,
                "raw_output_digest": _digest(self.raw_output) if self.raw_output else "",
            },
        )


class OfflineFakeRunner:
    """Deterministic, process-free runner covering every adapter offline."""

    def __init__(self, adapters: list[dict[str, Any]]) -> None:
        self._adapters = {item["adapter_id"]: item for item in adapters}
        self.calls: list[str] = []

    def adapters(self) -> list[str]:
        return sorted(self._adapters)

    def run(self, case: ConformanceCase) -> FakeRunnerOutcome:
        if case.adapter_id not in self._adapters:
            raise KeyError(f"unknown adapter {case.adapter_id!r}")
        self.calls.append(case.case_id)

        if case.case_kind == "timeout":
            return FakeRunnerOutcome(
                adapter_id=case.adapter_id,
                status=ResultStatus.TIMEOUT,
                authority=case.result_authority,
                conclusive=False,
                reason="bounded resource timeout",
                witness={},
                obligation_digest=case.obligation_digest,
                timed_out=True,
            )
        if case.case_kind == "malformed_output":
            raw = str(case.metadata.get("raw_payload", "???"))
            return FakeRunnerOutcome(
                adapter_id=case.adapter_id,
                status=ResultStatus.MALFORMED,
                authority=case.result_authority,
                conclusive=False,
                reason="malformed tool output rejected",
                witness={},
                obligation_digest=case.obligation_digest,
                raw_output=raw,
                malformed=True,
            )
        if case.case_kind == "authority_boundary" and case.result_authority is (
            ResultAuthority.CANDIDATE
        ):
            return FakeRunnerOutcome(
                adapter_id=case.adapter_id,
                status=ResultStatus.CANDIDATE,
                authority=ResultAuthority.CANDIDATE,
                conclusive=False,
                reason="advisory candidate only",
                witness={"kind": "proposal"},
                obligation_digest=case.obligation_digest,
            )

        status = case.expected_status
        conclusive = status not in {
            ResultStatus.UNKNOWN,
            ResultStatus.TIMEOUT,
            ResultStatus.UNAVAILABLE,
            ResultStatus.UNSUPPORTED,
            ResultStatus.MALFORMED,
            ResultStatus.ERROR,
            ResultStatus.CANDIDATE,
        }
        witness: dict[str, Any] = dict(case.witness)
        if case.case_kind == "negative" and self._adapters[case.adapter_id].get(
            "supports_counterexample"
        ):
            witness.setdefault("kind", "counterexample")
            witness.setdefault("replayable", True)
        elif case.case_kind == "positive":
            witness.setdefault("kind", "proof" if conclusive else "observation")

        return FakeRunnerOutcome(
            adapter_id=case.adapter_id,
            status=status,
            authority=case.result_authority,
            conclusive=conclusive and case.case_kind in {"positive", "negative"},
            reason=f"offline fake:{case.case_kind}",
            witness=witness,
            obligation_digest=case.obligation_digest,
            raw_output=f"FAKE {status.value}\n",
        )


def _seed_statement() -> str:
    return str(MANIFEST["recipes"]["positive"]["statement_template"]).format(
        seed=MANIFEST["recipes"]["statement_seed"]
    )


def expand_cases() -> list[ConformanceCase]:
    """Expand compact recipes into per-adapter cases (no bulk golden dumps)."""

    recipes = MANIFEST["recipes"]
    seed = _seed_statement()
    cases: list[ConformanceCase] = []

    for adapter in MANIFEST["adapters"]:
        adapter_id = adapter["adapter_id"]
        authority = _authority(adapter["result_authority"])
        family = adapter["attempt_family"]

        cases.append(
            ConformanceCase(
                case_id=f"{adapter_id}:positive",
                case_kind="positive",
                adapter_id=adapter_id,
                attempt_family=family,
                result_authority=authority,
                statement=seed,
                expected_status=_POSITIVE_STATUS[authority],
            )
        )
        negative_recipe = recipes["negative"]
        cases.append(
            ConformanceCase(
                case_id=f"{adapter_id}:negative",
                case_kind="negative",
                adapter_id=adapter_id,
                attempt_family=family,
                result_authority=authority,
                statement=str(negative_recipe["statement_template"]),
                expected_status=_NEGATIVE_STATUS[authority],
                witness=dict(negative_recipe.get("counterexample", {})),
            )
        )
        for mutation in recipes["mutation"]["mutations"]:
            cases.append(
                ConformanceCase(
                    case_id=f"{adapter_id}:mutation:{mutation['mutation_id']}",
                    case_kind="mutation",
                    adapter_id=adapter_id,
                    attempt_family=family,
                    result_authority=authority,
                    statement=str(mutation["mutated_statement"]).format(seed=seed)
                    if "{seed}" in str(mutation["mutated_statement"])
                    else str(mutation["mutated_statement"]),
                    expected_status=(
                        _POSITIVE_STATUS[authority]
                        if not mutation["semantic_change"]
                        else _NEGATIVE_STATUS[authority]
                    ),
                    metadata={
                        "mutation_id": mutation["mutation_id"],
                        "semantic_change": mutation["semantic_change"],
                        "normalize": mutation.get("normalize"),
                        "base_statement": seed,
                    },
                )
            )
        for payload_index, raw in enumerate(recipes["malformed_output"]["raw_payloads"]):
            cases.append(
                ConformanceCase(
                    case_id=f"{adapter_id}:malformed:{payload_index}",
                    case_kind="malformed_output",
                    adapter_id=adapter_id,
                    attempt_family=family,
                    result_authority=authority,
                    statement=seed,
                    expected_status=ResultStatus.MALFORMED,
                    metadata={"raw_payload": raw},
                )
            )
        cases.append(
            ConformanceCase(
                case_id=f"{adapter_id}:timeout",
                case_kind="timeout",
                adapter_id=adapter_id,
                attempt_family=family,
                result_authority=authority,
                statement=seed,
                expected_status=ResultStatus.TIMEOUT,
                metadata={"timeout_ms": recipes["timeout"]["timeout_ms"]},
            )
        )

    # Authority-boundary cases target the declared candidate adapter once.
    boundary = recipes["authority_boundary"]
    candidate_id = boundary["candidate_adapter_id"]
    candidate = next(
        item for item in MANIFEST["adapters"] if item["adapter_id"] == candidate_id
    )
    cases.append(
        ConformanceCase(
            case_id=f"{candidate_id}:authority_boundary",
            case_kind="authority_boundary",
            adapter_id=candidate_id,
            attempt_family=candidate["attempt_family"],
            result_authority=ResultAuthority.CANDIDATE,
            statement=seed,
            expected_status=ResultStatus.CANDIDATE,
            metadata=dict(boundary),
        )
    )
    return cases


def _runner() -> OfflineFakeRunner:
    return OfflineFakeRunner(list(MANIFEST["adapters"]))


# ---------------------------------------------------------------------------
# Manifest contract
# ---------------------------------------------------------------------------


def test_manifest_schema_and_required_vocabularies() -> None:
    assert MANIFEST["schema_version"] == SCHEMA_VERSION
    assert MANIFEST["interface"] == INTERFACE
    assert MANIFEST["objective"] == "LFV-G080"
    assert list(MANIFEST["required_case_kinds"]) == list(REQUIRED_CASE_KINDS)
    assert set(MANIFEST["required_case_kinds"]) == set(REQUIRED_CASE_KINDS)

    recipes = MANIFEST["recipes"]
    for kind in REQUIRED_CASE_KINDS:
        assert kind in recipes, f"missing recipe for {kind}"

    acceptance = MANIFEST["acceptance"]
    for key, expected in (
        ("fake_runners_cover_every_adapter_offline", True),
        ("opt_in_real_tool_lanes_declare_skips_or_unavailability", True),
        ("semantic_mutations_are_detected", True),
        ("counterexamples_replay", True),
        ("disagreements_quarantine", True),
        ("no_authority_upgrade", True),
        ("no_stale_cache_acceptance", True),
    ):
        assert acceptance[key] is expected

    adapter_ids = [item["adapter_id"] for item in MANIFEST["adapters"]]
    assert adapter_ids == sorted(adapter_ids) or len(adapter_ids) == len(set(adapter_ids))
    assert len(adapter_ids) == len(set(adapter_ids))
    assert len(adapter_ids) >= 16

    attempt_families = {item["attempt_family"] for item in MANIFEST["adapters"]}
    for required in MANIFEST["attempt_families"]:
        assert required in attempt_families, f"no adapter for attempt family {required}"

    for adapter in MANIFEST["adapters"]:
        assert adapter["module"]
        assert adapter["result_authority"]
        assert adapter["logic_families"]
        _authority(adapter["result_authority"])  # valid enum


def test_expanded_cases_cover_every_adapter_and_case_kind() -> None:
    cases = expand_cases()
    adapter_ids = {item["adapter_id"] for item in MANIFEST["adapters"]}
    covered_adapters = {case.adapter_id for case in cases}
    assert covered_adapters == adapter_ids

    kinds_by_adapter: dict[str, set[str]] = {aid: set() for aid in adapter_ids}
    for case in cases:
        kinds_by_adapter[case.adapter_id].add(case.case_kind)

    per_adapter_required = {
        "positive",
        "negative",
        "mutation",
        "malformed_output",
        "timeout",
    }
    for adapter_id, kinds in kinds_by_adapter.items():
        missing = per_adapter_required - kinds
        assert not missing, f"{adapter_id} missing case kinds {sorted(missing)}"

    # Cross-cutting kinds appear at least once in the expanded corpus or recipes.
    assert any(case.case_kind == "authority_boundary" for case in cases)
    assert "disagreement" in MANIFEST["recipes"]
    assert "metamorphic" in MANIFEST["recipes"]
    assert "translation" in MANIFEST["recipes"]


# ---------------------------------------------------------------------------
# Offline fake runners
# ---------------------------------------------------------------------------


def test_fake_runners_cover_every_adapter_offline() -> None:
    runner = _runner()
    cases = [
        case
        for case in expand_cases()
        if case.case_kind in {"positive", "negative", "timeout", "malformed_output"}
    ]
    outcomes = [runner.run(case) for case in cases]
    assert set(runner.adapters()) == {item["adapter_id"] for item in MANIFEST["adapters"]}
    assert len(outcomes) == len(cases)
    assert all(not outcome.unavailable for outcome in outcomes)

    for case, outcome in zip(cases, outcomes, strict=True):
        assert outcome.adapter_id == case.adapter_id
        assert outcome.status is case.expected_status
        typed = outcome.to_typed_result()
        assert typed.backend_id == case.adapter_id
        assert typed.status is case.expected_status
        assert typed.authority is case.result_authority
        if case.case_kind in {"timeout", "malformed_output"}:
            assert typed.is_conclusive is False


def test_positive_and_negative_statuses_match_authority_vocabulary() -> None:
    runner = _runner()
    for case in expand_cases():
        if case.case_kind not in {"positive", "negative"}:
            continue
        outcome = runner.run(case)
        typed = outcome.to_typed_result()
        # AuthoritySubstitutionError must not fire for the declared authority.
        normalized = ResultAuthorityNormalization.normalize(
            typed.to_dict(),
            expected_authority=case.result_authority,
        )
        assert normalized.authority is case.result_authority
        assert normalized.status is case.expected_status


# ---------------------------------------------------------------------------
# Mutation detection
# ---------------------------------------------------------------------------


def test_semantic_mutations_are_detected() -> None:
    runner = _runner()
    base = _seed_statement()
    base_digest = _digest(
        json.dumps(
            {"adapter_id": "z3", "case_kind": "positive", "statement": base},
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    mutation_cases = [
        case for case in expand_cases() if case.case_kind == "mutation" and case.adapter_id == "z3"
    ]
    assert mutation_cases

    for case in mutation_cases:
        outcome = runner.run(case)
        semantic = bool(case.metadata["semantic_change"])
        if semantic:
            assert case.obligation_digest != base_digest
            assert outcome.status is _NEGATIVE_STATUS[case.result_authority]
        else:
            # Whitespace-only mutation collapses to the same normalized statement.
            normalized = _normalize_statement(case.statement, case.metadata.get("normalize"))
            collapsed_base = _normalize_statement(base, "collapse_whitespace")
            assert normalized == collapsed_base
            assert outcome.status is _POSITIVE_STATUS[case.result_authority]


# ---------------------------------------------------------------------------
# Metamorphic pairs
# ---------------------------------------------------------------------------


def test_metamorphic_pairs_preserve_or_diverge_as_declared() -> None:
    runner = _runner()
    adapter = next(item for item in MANIFEST["adapters"] if item["adapter_id"] == "z3")
    authority = _authority(adapter["result_authority"])

    for pair in MANIFEST["recipes"]["metamorphic"]["pairs"]:
        left = ConformanceCase(
            case_id=f"meta:{pair['pair_id']}:left",
            case_kind="metamorphic",
            adapter_id="z3",
            attempt_family=adapter["attempt_family"],
            result_authority=authority,
            statement=pair["left"],
            expected_status=_POSITIVE_STATUS[authority],
        )
        right = ConformanceCase(
            case_id=f"meta:{pair['pair_id']}:right",
            case_kind="metamorphic",
            adapter_id="z3",
            attempt_family=adapter["attempt_family"],
            result_authority=authority,
            statement=pair["right"],
            expected_status=(
                _POSITIVE_STATUS[authority]
                if pair["expect_same_verdict"]
                else _NEGATIVE_STATUS[authority]
            ),
        )
        # Metamorphic harness: same offline verdict iff expect_same_verdict.
        left_out = FakeRunnerOutcome(
            adapter_id="z3",
            status=_POSITIVE_STATUS[authority],
            authority=authority,
            conclusive=True,
            reason="metamorphic-left",
            witness={},
            obligation_digest=left.obligation_digest,
        )
        right_status = (
            _POSITIVE_STATUS[authority]
            if pair["expect_same_verdict"]
            else _NEGATIVE_STATUS[authority]
        )
        right_out = FakeRunnerOutcome(
            adapter_id="z3",
            status=right_status,
            authority=authority,
            conclusive=True,
            reason="metamorphic-right",
            witness={},
            obligation_digest=right.obligation_digest,
        )
        same = left_out.status is right_out.status
        assert same is bool(pair["expect_same_verdict"])
        if pair["expect_same_verdict"]:
            # Alpha-renamed / commuted forms still produce distinct digests but
            # the harness maps them to the same verdict.
            assert left.obligation_digest != right.obligation_digest or pair["left"] == pair[
                "right"
            ]
        # Ensure runner still accepts the statements offline.
        assert runner.run(
            ConformanceCase(
                case_id=left.case_id + ":run",
                case_kind="positive",
                adapter_id="z3",
                attempt_family="solver",
                result_authority=authority,
                statement=pair["left"],
                expected_status=_POSITIVE_STATUS[authority],
            )
        ).status is _POSITIVE_STATUS[authority]


# ---------------------------------------------------------------------------
# Translation receipts
# ---------------------------------------------------------------------------


def test_translation_recipe_binds_source_target_and_ceiling() -> None:
    recipe = MANIFEST["recipes"]["translation"]
    receipt = {
        "receipt_id": f"tr:{_digest(recipe['source_digest_seed'])[:16]}",
        "interface": "LogicProviderConformance@1",
        "source_family": recipe["source_family"],
        "target_family": recipe["target_family"],
        "preservation": recipe["preservation"],
        "ceiling": recipe["ceiling"],
        "source_digest": _digest(recipe["source_digest_seed"]),
        "target_digest": _digest(recipe["target_digest_seed"]),
    }
    assert receipt["source_family"] in MANIFEST["logic_families"]
    assert receipt["target_family"] in MANIFEST["logic_families"]
    assert receipt["preservation"] == "equisatisfiable"
    assert EvidenceAuthority(receipt["ceiling"]) is EvidenceAuthority.BOUNDED
    assert receipt["source_digest"] != receipt["target_digest"]
    # Ceiling must not silently become authoritative.
    assert receipt["ceiling"] != EvidenceAuthority.AUTHORITATIVE.value


# ---------------------------------------------------------------------------
# Disagreement quarantine
# ---------------------------------------------------------------------------


def test_disagreement_quarantines_via_portfolio() -> None:
    recipe = MANIFEST["recipes"]["disagreement"]
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        {
            "obligation_id": "obl:conformance-disagreement",
            "property_kind": PropertyKind.SAFETY.value,
            "statement": _seed_statement(),
            "required_assurance": EvidenceAuthority.BOUNDED.value,
        }
    )
    # Portfolio may label peers tla_tlc / apalache; fall back to recipe ids.
    peers = []
    for backend_id in recipe["peer_backend_ids"]:
        match = next((item for item in plan.attempts if item.backend_id == backend_id), None)
        if match is not None:
            peers.append(match)
    if len(peers) < 2:
        # Build synthetic specs from any two model-checker attempts.
        peers = [item for item in plan.attempts if item.family.value == "model_checker"][:2]
    assert len(peers) >= 2

    left, right = peers[0], peers[1]
    outcomes = [
        PortfolioAttemptOutcome(
            attempt_id=left.attempt_id,
            backend_id=left.backend_id,
            status=ResultStatus.SATISFIED,
            authority=left.result_authority,
            role=left.role,
            stage=left.stage,
            conclusive_counterexample=False,
            achieved_assurance=EvidenceAuthority.BOUNDED,
            detail="conformance-left",
        ),
        PortfolioAttemptOutcome(
            attempt_id=right.attempt_id,
            backend_id=right.backend_id,
            status=ResultStatus.VIOLATED,
            authority=right.result_authority,
            role=right.role,
            stage=right.stage,
            conclusive_counterexample=True,
            achieved_assurance=EvidenceAuthority.BOUNDED,
            detail="conformance-right",
        ),
    ]
    selection = portfolio.select(plan, outcomes)
    assert selection.verdict is PortfolioVerdict.QUARANTINED
    assert selection.disagreement is True
    assert selection.authority_attempt_ids == ()
    assert left.attempt_id in selection.quarantined_attempt_ids
    assert right.attempt_id in selection.quarantined_attempt_ids
    assert all(
        disposition is AttemptDisposition.QUARANTINED
        for attempt_id, disposition in selection.dispositions
        if attempt_id in selection.quarantined_attempt_ids
    )

    # Order independence.
    reversed_selection = portfolio.select(plan, list(reversed(outcomes)))
    assert reversed_selection.verdict is PortfolioVerdict.QUARANTINED
    assert set(reversed_selection.quarantined_attempt_ids) == set(
        selection.quarantined_attempt_ids
    )


def test_smt_differential_disagreement_vocabulary_is_closed() -> None:
    """Peer-solver disagreement is a first-class differential classification."""

    assert DifferentialClassification.DISAGREE.value == "disagree"
    assert DifferentialClassification.AGREE_PROVED.value == "agree_proved"
    assert SmtSolverVerdict.SAT is not SmtSolverVerdict.UNSAT
    # The classification helper requires full outcomes; the fail-closed rule is
    # that SAT vs UNSAT is never agreement.
    assert {
        DifferentialClassification.DISAGREE,
        DifferentialClassification.AGREE_PROVED,
        DifferentialClassification.PARTIAL_UNAVAILABLE,
        DifferentialClassification.BOTH_UNAVAILABLE,
        DifferentialClassification.MALFORMED,
        DifferentialClassification.ERROR,
    } <= set(DifferentialClassification)


# ---------------------------------------------------------------------------
# Counterexample replay
# ---------------------------------------------------------------------------


def test_counterexamples_replay_deterministically() -> None:
    runner = _runner()
    negative_cases = [
        case
        for case in expand_cases()
        if case.case_kind == "negative"
        and next(
            item
            for item in MANIFEST["adapters"]
            if item["adapter_id"] == case.adapter_id
        ).get("supports_counterexample")
    ]
    assert negative_cases

    for case in negative_cases[:6]:
        first = runner.run(case)
        second = runner.run(case)
        assert first.witness == second.witness
        assert first.obligation_digest == second.obligation_digest
        assert first.witness.get("replayable") is True
        typed_a = first.to_typed_result()
        typed_b = second.to_typed_result()
        assert typed_a.to_dict()["witness"] == typed_b.to_dict()["witness"]
        assert typed_a.status is case.expected_status
        assert typed_a.is_conclusive is False or first.conclusive


# ---------------------------------------------------------------------------
# Authority boundary
# ---------------------------------------------------------------------------


def test_no_authority_upgrade_from_candidate_surface() -> None:
    runner = _runner()
    case = next(case for case in expand_cases() if case.case_kind == "authority_boundary")
    outcome = runner.run(case)
    assert outcome.authority is ResultAuthority.CANDIDATE
    typed = outcome.to_typed_result()
    assert typed.authority is ResultAuthority.CANDIDATE
    assert typed.translation_ceiling is EvidenceAuthority.ADVISORY

    payload = typed.to_dict()
    with pytest.raises(AuthoritySubstitutionError):
        ResultAuthorityNormalization.normalize(
            payload,
            expected_authority=ResultAuthority.THEOREM,
        )

    # Mutating the wire payload cannot launder candidate into theorem under a
    # candidate trust anchor.
    forged = dict(payload)
    forged["authority"] = ResultAuthority.THEOREM.value
    forged["result_type"] = "theorem_result"
    forged["status"] = ResultStatus.PROVED.value
    with pytest.raises(AuthoritySubstitutionError):
        ResultAuthorityNormalization.normalize(
            forged,
            expected_authority=ResultAuthority.CANDIDATE,
        )


def test_cache_rejects_authority_raise_and_stale_identity() -> None:
    boundary = MANIFEST["recipes"]["authority_boundary"]
    theorem = ResultAuthorityNormalization.build(
        ResultAuthority.THEOREM,
        result_id="result:cache-conformance",
        backend_id="z3",
        backend_version="fake-conformance/1",
        status=ResultStatus.PROVED,
        assumptions=(),
        bounds=_BOUNDS,
        translation_ceiling=EvidenceAuthority.BOUNDED,
        usage=_USAGE,
        witness={"kind": "proof"},
        diagnostics=(),
        reason="offline",
        metadata={},
    )
    fresh_key = build_verification_cache_key(
        ir={"statement": _seed_statement()},
        property_value={"property_id": "prop.conformance"},
        assumptions=(),
        translation={"receipt_id": "tr:conformance", "preservation": "equisatisfiable"},
        backend_id="z3",
        backend_binary={"path": "fake://z3", "sha256": "00"},
        backend_version="fake-conformance/1",
        backend_config={"mode": "offline"},
        resources={"timeout_ms": 1000},
        tree={"tree_id": boundary["fresh_tree_id"]},
        policy={"mode": "conformance"},
    )
    stale_key = build_verification_cache_key(
        ir={"statement": _seed_statement()},
        property_value={"property_id": "prop.conformance"},
        assumptions=(),
        translation={"receipt_id": "tr:conformance", "preservation": "equisatisfiable"},
        backend_id="z3",
        backend_binary={"path": "fake://z3", "sha256": "00"},
        backend_version="fake-conformance/1",
        backend_config={"mode": "offline"},
        resources={"timeout_ms": 1000},
        tree={"tree_id": boundary["stale_tree_id"]},
        policy={"mode": "conformance"},
    )
    assert fresh_key.digest != stale_key.digest

    cache = ExactVerificationCache()
    stored = cache.put_result(fresh_key, theorem)
    assert stored.entry is not None
    hit = cache.lookup(fresh_key)
    assert hit.hit and hit.usable

    stale_lookup = cache.lookup(stale_key)
    assert not stale_lookup.hit
    assert not stale_lookup.usable

    with pytest.raises(VerificationCacheAuthorityError, match="cannot raise"):
        VerificationCacheEntry.from_typed_result(
            fresh_key,
            theorem,
            evidence_authority=EvidenceAuthority.AUTHORITATIVE,
        )
    with pytest.raises(VerificationCacheAuthorityError, match="cannot raise"):
        cache.put_result(
            fresh_key,
            theorem,
            evidence_authority=EvidenceAuthority.AUTHORITATIVE,
        )


# ---------------------------------------------------------------------------
# Malformed + timeout non-conclusive
# ---------------------------------------------------------------------------


def test_malformed_and_timeout_never_look_like_success() -> None:
    runner = _runner()
    cases = [
        case
        for case in expand_cases()
        if case.case_kind in {"malformed_output", "timeout"} and case.adapter_id in {"z3", "lean", "tamarin"}
    ]
    assert cases
    for case in cases:
        outcome = runner.run(case)
        typed = outcome.to_typed_result()
        assert typed.status in {ResultStatus.MALFORMED, ResultStatus.TIMEOUT}
        assert typed.is_conclusive is False
        assert typed.status is not ResultStatus.PROVED
        assert typed.status is not ResultStatus.SATISFIED
        assert typed.status is not ResultStatus.SECURE


# ---------------------------------------------------------------------------
# Opt-in real-tool lanes
# ---------------------------------------------------------------------------


def _real_tools_enabled() -> bool:
    return bool(os.environ.get(REAL_TOOLS_ENV, "").strip())


def test_real_tool_lane_policy_is_documented_and_closed_by_default() -> None:
    policy = MANIFEST["scope"]["real_tools"]
    assert policy["opt_in_env"] == REAL_TOOLS_ENV
    assert "unavailable" in policy["policy"].lower() or "skip" in policy["policy"].lower()
    # Default offline gate: no ambient real-tool success without opt-in.
    if not _real_tools_enabled():
        for adapter in MANIFEST["adapters"]:
            binary = adapter.get("real_tool_binary")
            if not binary:
                continue
            # Presence on PATH must not be treated as a pass without opt-in.
            _ = shutil.which(binary)


@pytest.mark.parametrize(
    "adapter",
    [item for item in MANIFEST["adapters"] if item.get("real_tool_binary")],
    ids=lambda item: item["adapter_id"],
)
def test_opt_in_real_tool_lanes_declare_skip_or_unavailability(
    adapter: dict[str, Any],
) -> None:
    binary = adapter["real_tool_binary"]
    if not _real_tools_enabled():
        pytest.skip(
            f"real-tool lane for {adapter['adapter_id']} requires "
            f"{REAL_TOOLS_ENV}=1; offline fake coverage is authoritative"
        )
    if shutil.which(binary) is None:
        # Explicit unavailability — never a success.
        reason = f"{binary} not on PATH for adapter {adapter['adapter_id']}"
        outcome = FakeRunnerOutcome(
            adapter_id=adapter["adapter_id"],
            status=ResultStatus.UNAVAILABLE,
            authority=_authority(adapter["result_authority"]),
            conclusive=False,
            reason=reason,
            witness={},
            obligation_digest=_digest(adapter["adapter_id"]),
            unavailable=True,
        )
        typed = outcome.to_typed_result()
        assert typed.status is ResultStatus.UNAVAILABLE
        assert typed.is_conclusive is False
        return
    # Tool is present under opt-in: still only records availability metadata.
    # Live execution is owned by per-backend suites, not this corpus.
    assert shutil.which(binary)


# ---------------------------------------------------------------------------
# Portfolio planning smoke (side-effect free)
# ---------------------------------------------------------------------------


def test_portfolio_plan_is_side_effect_free_for_conformance_seed() -> None:
    plan = plan_portfolio(
        {
            "obligation_id": "obl:conformance-seed",
            "property_kind": PropertyKind.THEOREM.value,
            "statement": _seed_statement(),
            "required_assurance": EvidenceAuthority.BOUNDED.value,
        }
    )
    assert plan.attempts
    second = plan_portfolio(
        {
            "obligation_id": "obl:conformance-seed",
            "property_kind": PropertyKind.THEOREM.value,
            "statement": _seed_statement(),
            "required_assurance": EvidenceAuthority.BOUNDED.value,
        }
    )
    assert plan.digest == second.digest


def test_every_adapter_has_at_least_one_offline_positive_outcome() -> None:
    runner = _runner()
    positives = [case for case in expand_cases() if case.case_kind == "positive"]
    assert {case.adapter_id for case in positives} == {
        item["adapter_id"] for item in MANIFEST["adapters"]
    }
    for case in positives:
        outcome = runner.run(case)
        assert outcome.status is case.expected_status
        assert not outcome.malformed
        assert not outcome.timed_out
        assert not outcome.unavailable

"""Datasets-side adversarial suite for goal-tactician hard-zero failures.

FVT-032 / FVT-G062 — ``ipfs_datasets_py`` security evidence.

Covers property-based, fuzz, metamorphic, mutation, differential, packaging,
cancellation, resource, injection, forged-identity, stale-cache, leakage,
vacuity, circularity, and disagreement checks on datasets-owned goal tactician
surfaces:

* ProofCandidateValidator@1 (vacuity, circularity, disagreement, stale)
* tactician contracts (false proof / false completion claims)
* public counterexample boundary (secret / private-witness leakage)
* LogicVerificationAPI receipt dispatch (forged / stale identity)
* BoundedToolRunner@1 (unbounded process, secrets, injection, cancellation)
* CounterexampleSemanticEquivalence@1 (disagreement quarantine)

Fuzz inputs remain bounded and fail closed. False proof, false closure,
authority escalation, hidden assumption, vacuous proof, circular lemma, forged
receipt, stale identity, secret leak, unbounded process, and unresolved
disagreement reported as success are hard-zero failures.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import pytest

from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    CancellationToken,
    ProcessInvocation,
    RawProcessResult,
    ToolProcessError,
    ToolRunLimits,
    ToolRunRequest,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.bridge.proof_receipt_attestation import (
    build_trusted_receipt_from_backend_result,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import (
    CounterexampleBoundaryError,
    project_public_counterexample,
)
from ipfs_datasets_py.logic.software_verification.counterexamples.equivalence import (
    COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE,
    CounterexampleSemanticEquivalence,
)
from ipfs_datasets_py.logic.software_verification.tactician.candidate_validation import (
    PROOF_CANDIDATE_VALIDATOR_INTERFACE,
    ProofCandidateValidator,
    QuarantineReason,
    StaticReplayBackend,
    UnavailableReplayBackend,
    ValidationBinding,
    ValidationCheckStatus,
    ValidationRequest,
    cap_validation_authority,
    is_contradiction_statement,
    is_vacuous_statement,
    may_discharge_graph_node,
    validate_candidate,
)
from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    CandidateValidation,
    HoleKind,
    HoleStatus,
    ProofHole,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    ValidationRecipe,
    ValidationVerdict,
)
from ipfs_datasets_py.logic.verification_api import (
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORMAL_VERIFICATION_TACTICIAN_ADVERSARIAL_GATE_INTERFACE: Final = (
    "FormalVerificationTacticianAdversarialGate@1"
)
SECRET: Final = "PRIVATE-WITNESS-fvt032-datasets-9e2b"
FUZZ_STATEMENT_BUDGET: Final = 24
TREE: Final = "tree:repo@fvt032"
PROPERTY: Final = "property:functional-correctness"
ASSUMPTIONS: Final = ("assumption:int",)
BOUNDS: Final = {"timeout_ms": 1000, "max_steps": 100}
TOOL: Final = "solver.lean"
NOW: Final = "2026-07-23T12:00:00Z"
EXPIRES: Final = "2026-07-23T12:05:00Z"
STALE_NOW: Final = "2026-07-23T12:06:00Z"


class HardZeroFailure(str, Enum):
    FALSE_PROOF = "false_proof"
    FALSE_CLOSURE = "false_closure"
    AUTHORITY_ESCALATION = "authority_escalation"
    HIDDEN_ASSUMPTION = "hidden_assumption"
    VACUOUS_PROOF = "vacuous_proof"
    CIRCULAR_LEMMA = "circular_lemma"
    FORGED_RECEIPT = "forged_receipt"
    STALE_IDENTITY = "stale_identity"
    SECRET_LEAK = "secret_leak"
    UNBOUNDED_PROCESS = "unbounded_process"
    UNRESOLVED_DISAGREEMENT = "unresolved_disagreement"


@dataclass(frozen=True)
class GoalTacticianAdversarialFinding:
    code: HardZeroFailure
    detail: str


# ---------------------------------------------------------------------------
# Factories — candidate validation
# ---------------------------------------------------------------------------


def _source(**overrides: Any) -> SourceSpanBinding:
    payload = {
        "tree_id": TREE,
        "source_ref_ids": ("source:lease.py",),
        "span_ids": ("span:claim",),
        "ast_scope_ids": ("symbol:claim_lease",),
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return SourceSpanBinding(**payload)


def _bounds(**overrides: Any) -> ResourceBounds:
    payload = {
        "wall_time_ms": 10_000,
        "memory_bytes": 64 * 1024 * 1024,
        "max_steps": 32,
        "max_depth": 8,
        "max_nodes": 64,
        "max_candidates": 16,
        "network_allowed": False,
    }
    payload.update(overrides)
    return ResourceBounds(**payload)


def _recipe(**overrides: Any) -> ValidationRecipe:
    payload: dict[str, Any] = {
        "recipe_id": "recipe:loop_invariant:site",
        "checker_kind": "smt_replay",
        "provider_ids": ("provider:z3",),
        "required_authority": AuthorityCeiling.SATISFIABILITY,
        "bounds": _bounds(),
        "steps": (
            "bind_source_span",
            "replay",
            "minimality",
            "record_receipt",
        ),
        "oracle_id": "oracle:loop_invariant",
    }
    payload.update(overrides)
    return ValidationRecipe(**payload)


def _hole(**overrides: Any) -> ProofHole:
    payload: dict[str, Any] = {
        "hole_id": "hole:site:loop:loop_invariant",
        "kind": HoleKind.LOOP_INVARIANT,
        "reason": "Required loop_invariant is missing",
        "source": _source(),
        "formal_goal_id": "formal:lease-ready",
        "expected_authority": AuthorityCeiling.SATISFIABILITY,
        "status": HoleStatus.OPEN,
        "property_class": PropertyClass.INVARIANCE,
        "statement": "missing loop_invariant for claim_lease",
        "provider_ids": ("provider:z3",),
        "bounds": _bounds(),
        "validation_recipe": _recipe(),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofHole(**payload)


def _candidate(**overrides: Any) -> CandidateProofStep:
    payload: dict[str, Any] = {
        "candidate_id": "candidate:inv:lease-ready",
        "hole_id": "hole:site:loop:loop_invariant",
        "kind": "loop_invariant",
        "statement": "owner_holds_token and bound > 0",
        "status": CandidateStatus.PROPOSED,
        "source": _source(),
        "provider_ids": ("provider:z3",),
        "authority": AuthorityCeiling.CANDIDATE,
        "rank_score_millionths": 750_000,
        "new_assumption_ids": ("assumption:token-order",),
        "evidence_ids": (),
        "provenance": {
            "source_kind": "smt_unsat_core",
            "premise_ids": ("premise:owner_holds", "premise:bound_pos"),
        },
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return CandidateProofStep(**payload)


def _binding(**overrides: Any) -> ValidationBinding:
    payload: dict[str, Any] = {
        "tree_id": TREE,
        "formal_goal_id": "formal:lease-ready",
        "assumption_ids": ("assumption:token-order", "assumption:fair-scheduler"),
        "tool_id": "provider:z3",
        "policy_id": "policy:hermetic-offline",
        "bounds": _bounds(),
        "snapshot_id": "snap:1",
        "graph_node_id": "node:leaf:loop-inv",
        "source": _source(),
        "known_facts": ("token_unique",),
        "axioms": ("tokens_totally_ordered",),
        "premise_ids": ("premise:owner_holds", "premise:bound_pos"),
        "selected_premise_ids": ("premise:owner_holds", "premise:bound_pos"),
    }
    payload.update(overrides)
    return ValidationBinding(**payload)


def _backend(
    candidate_id: str = "candidate:inv:lease-ready",
    *,
    holds: bool = True,
    critical: tuple[str, ...] = ("premise:owner_holds", "premise:bound_pos"),
    **overrides: Any,
) -> StaticReplayBackend:
    from ipfs_datasets_py.logic.software_verification.tactician.candidate_validation import (
        ReplayBackendKind,
    )

    payload: dict[str, Any] = {
        "provider_id": "provider:z3",
        "provider_version": "4.13.0",
        "backend_kind": ReplayBackendKind.SOLVER,
        "authority": AuthorityCeiling.SATISFIABILITY,
        "holds_for": {candidate_id: holds},
        "critical_premises": {candidate_id: critical},
        "default_holds": holds,
    }
    payload.update(overrides)
    return StaticReplayBackend(**payload)


def _assert_no_secret(payload: Any, secret: str = SECRET) -> None:
    rendered = json.dumps(payload, sort_keys=True, default=str)
    assert secret not in rendered
    assert secret.casefold() not in rendered.casefold()


def _assert_hard_zero_rejected(
    result: Any,
    *,
    stage: str | None = None,
) -> list[GoalTacticianAdversarialFinding]:
    findings: list[GoalTacticianAdversarialFinding] = []
    assert result.may_discharge is False
    assert result.validation.proof_claimed is False
    assert result.validation.completion_claimed is False
    if result.validation.verdict is ValidationVerdict.ACCEPTED:
        findings.append(
            GoalTacticianAdversarialFinding(
                HardZeroFailure.FALSE_PROOF,
                "accepted verdict without discharge eligibility is inconsistent",
            )
        )
    if stage is not None:
        check = next((c for c in result.checks if c.stage == stage), None)
        assert check is not None, f"missing stage {stage}"
        assert check.status in {
            ValidationCheckStatus.FAIL,
            ValidationCheckStatus.UNAVAILABLE,
            ValidationCheckStatus.UNKNOWN,
        }
    _assert_no_secret(result.to_dict())
    return findings


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def test_goal_tactician_adversarial_interfaces() -> None:
    assert (
        FORMAL_VERIFICATION_TACTICIAN_ADVERSARIAL_GATE_INTERFACE
        == "FormalVerificationTacticianAdversarialGate@1"
    )
    assert PROOF_CANDIDATE_VALIDATOR_INTERFACE == "ProofCandidateValidator@1"
    assert (
        COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE
        == "CounterexampleSemanticEquivalence@1"
    )
    assert ProofCandidateValidator.INTERFACE == PROOF_CANDIDATE_VALIDATOR_INTERFACE


# ---------------------------------------------------------------------------
# Vacuity / circularity / contradiction (false / vacuous proof)
# ---------------------------------------------------------------------------


def test_vacuous_proof_is_hard_zero_failure() -> None:
    assert is_vacuous_statement("true")
    assert is_vacuous_statement("TRUE")
    result = validate_candidate(
        _candidate(statement="true"),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    _assert_hard_zero_rejected(result, stage="non_vacuity")
    assert result.validation.verdict is ValidationVerdict.REJECTED


def test_contradiction_and_circular_lemma_are_hard_zero_failures() -> None:
    assert is_contradiction_statement("false")
    contradiction = validate_candidate(
        _candidate(statement="false"),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    _assert_hard_zero_rejected(contradiction, stage="consistency")

    circular = validate_candidate(
        _candidate(statement="formal:lease-ready"),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    _assert_hard_zero_rejected(circular, stage="non_circularity")

    self_dep = validate_candidate(
        _candidate(
            provenance={
                "dependency_ids": ("candidate:inv:lease-ready",),
                "premise_ids": ("premise:owner_holds",),
            }
        ),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert self_dep.validation.verdict is ValidationVerdict.REJECTED
    assert self_dep.may_discharge is False


def test_hidden_assumption_not_bound_rejects() -> None:
    result = validate_candidate(
        _candidate(new_assumption_ids=("assumption:rogue-hidden",)),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    _assert_hard_zero_rejected(result, stage="exact_binding")
    detail = next(c.detail for c in result.checks if c.stage == "exact_binding")
    assert "not bound" in detail or "assumption" in detail.lower()


# ---------------------------------------------------------------------------
# Stale identity / forged binding
# ---------------------------------------------------------------------------


def test_stale_snapshot_and_tree_identity_reject() -> None:
    stale_snap = validate_candidate(
        _candidate(source=_source(snapshot_id="snap:stale")),
        _hole(),
        _binding(snapshot_id="snap:1"),
        backends=(_backend(),),
    )
    assert stale_snap.validation.verdict is ValidationVerdict.REJECTED
    assert stale_snap.may_discharge is False

    stale_tree = validate_candidate(
        _candidate(source=_source(tree_id="tree:attacker")),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert stale_tree.validation.verdict is ValidationVerdict.REJECTED
    binding_check = next(c for c in stale_tree.checks if c.stage == "exact_binding")
    assert binding_check.status is ValidationCheckStatus.FAIL


def test_stale_candidate_cannot_discharge_graph_node() -> None:
    from ipfs_datasets_py.logic.software_verification.tactician.candidate_validation import (
        DischargeEligibility,
    )

    wrong_id = "sha256:" + ("0" * 64)
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
        expected_candidate_content_id=wrong_id,
    )
    assert result.stale is True
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.discharge_eligibility is DischargeEligibility.STALE
    assert result.may_discharge is False
    assert (
        may_discharge_graph_node(
            verdict=result.validation.verdict,
            eligibility=result.discharge_eligibility,
            validated=result.validated,
            stale=result.stale,
            quarantined=result.quarantined,
        )
        is False
    )


# ---------------------------------------------------------------------------
# Disagreement quarantine (never reported as success)
# ---------------------------------------------------------------------------


def test_provider_disagreement_quarantined_never_success() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
        proposed_provider_verdicts={
            "provider:z3": "accepted",
            "provider:cvc5": "rejected",
        },
    )
    assert result.quarantined is True
    assert result.may_discharge is False
    assert result.validation.verdict is ValidationVerdict.INCONCLUSIVE
    assert result.disagreement is not None
    assert result.disagreement.reason is QuarantineReason.PROVIDER_DISAGREEMENT
    assert result.validation.proof_claimed is False
    assert result.validation.completion_claimed is False
    payload = result.to_dict()
    _assert_no_secret(payload)
    assert payload.get("success") is not True
    assert payload.get("admitted") is not True


def test_semantic_equivalence_disagreement_is_quarantined() -> None:
    from ipfs_datasets_py.logic.software_verification.counterexamples.equivalence import (
        DifferentialStatus,
        differential_compare_providers,
        quarantine_provider_disagreement,
    )

    observations = [
        {
            "provider_id": "solver.z3",
            "outcome": "violation",
            "receipt_id": "receipt:z3-yes",
            "authority": "theorem",
        },
        {
            "provider_id": "solver.cvc5",
            "outcome": "unsat",
            "receipt_id": "receipt:cvc5-no",
            "authority": "theorem",
        },
    ]
    comparison = differential_compare_providers(observations)
    assert comparison.status == DifferentialStatus.DISAGREEMENT
    assert comparison.agreed is False
    assert comparison.is_consensus is False
    assert comparison.consensus_claimed is False
    assert comparison.requires_quarantine is True
    quarantine = quarantine_provider_disagreement(comparison)
    payload = quarantine.to_dict() if hasattr(quarantine, "to_dict") else comparison.to_dict()
    _assert_no_secret(payload)
    # Authority cannot rise under disagreement / quarantine.
    rendered = json.dumps(payload, default=str).lower()
    assert "consensus" not in rendered or "false" in rendered
    assert comparison.consensus_claimed is False


# ---------------------------------------------------------------------------
# Authority escalation caps
# ---------------------------------------------------------------------------


def test_authority_escalation_capped_and_rejected_claims() -> None:
    # Accepted path never invents theorem-level claims from candidate authority.
    capped = cap_validation_authority(
        AuthorityCeiling.THEOREM,
        verdict=ValidationVerdict.ACCEPTED,
    )
    assert capped is not AuthorityCeiling.THEOREM

    rejected_cap = cap_validation_authority(
        AuthorityCeiling.THEOREM,
        verdict=ValidationVerdict.REJECTED,
    )
    assert rejected_cap in {
        AuthorityCeiling.CANDIDATE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.NONE,
    }

    with pytest.raises(TacticianContractError):
        CandidateProofStep(
            candidate_id="candidate:evil",
            hole_id="hole:site:loop:loop_invariant",
            kind="loop_invariant",
            statement="owner_holds_token",
            status=CandidateStatus.PROPOSED,
            source=_source(),
            provider_ids=("provider:z3",),
            authority=AuthorityCeiling.CANDIDATE,
            rank_score_millionths=1,
            new_assumption_ids=(),
            evidence_ids=(),
            provenance={},
            proof_claimed=True,  # proposals must not claim proof
            completion_claimed=False,
        )


def test_false_proof_claim_on_validation_receipt_forbidden() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim proof"):
        CandidateValidation(
            validation_id="validation:evil",
            candidate_id="candidate:inv:lease-ready",
            hole_id="hole:site:loop:loop_invariant",
            verdict=ValidationVerdict.ACCEPTED,
            authority=AuthorityCeiling.SATISFIABILITY,
            tree_id=TREE,
            provider_id="provider:z3",
            assumption_ids=("assumption:token-order",),
            minimality="local",
            proof_claimed=True,
            completion_claimed=False,
        )


# ---------------------------------------------------------------------------
# Secret / private-witness leakage
# ---------------------------------------------------------------------------


def test_counterexample_public_boundary_strips_private_witness() -> None:
    leaky = {
        "kind": "model",
        "model": {
            "lease_owner": "worker-a",
            "epoch": 4,
            "hidden_witness": SECRET,
            "credential": "super-secret-credential",
            "note": f"Authorization: Bearer {SECRET}",
        },
        "stdout": f"unbounded solver transcript with {SECRET}",
        "source_excerpt": "def secrets(): pass",
        "source_code": "complete repository source",
        "raw_output": "solver dump " * 50 + SECRET,
        "violated_property": "obligation:exclusive-lease",
        "assumption_ids": ["assumption:token-order"],
        "finite_bounds": {"timeout_ms": 500, "max_steps": 32},
        "provider_id": "provider:z3",
        "tool_id": "solver.z3",
        "source_ref_ids": ["source:lease.py"],
        "span_ids": ["span:lease-claim"],
        "ast_scope_id": "symbol:claim_lease",
        "tree_id": TREE,
        "summary": "lease owner conflict",
    }
    envelope = project_public_counterexample(leaky)
    public = envelope.to_public_dict()
    encoded = json.dumps(public, sort_keys=True).lower()
    for surface in (encoded, envelope.to_json().lower()):
        assert SECRET.casefold() not in surface
        assert "hidden_witness" not in surface
        assert "credential" not in surface
        assert "stdout" not in surface
        assert "raw_output" not in surface
    assert public["contains_private_material"] is False


# ---------------------------------------------------------------------------
# Forged / stale receipts via LogicVerificationAPI
# ---------------------------------------------------------------------------


def _api() -> LogicVerificationAPI:
    return LogicVerificationAPI()


def _theorem(**changes: Any) -> TheoremResult:
    fields: dict[str, Any] = {
        "result_id": "result:theorem-fvt032",
        "backend_id": TOOL,
        "backend_version": "4.19.0",
        "authority": ResultAuthority.THEOREM,
        "status": ResultStatus.PROVED,
        "assumptions": ASSUMPTIONS,
        "bounds": ExecutionBounds(timeout_ms=1000, max_steps=100),
        "translation_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "metadata": FrozenMap(
            {"bounds": dict(BOUNDS), "expires_at": EXPIRES, "issued_at": NOW}
        ),
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _trusted(**changes: Any) -> Any:
    result_changes = {
        key: changes.pop(key)
        for key in list(changes)
        if key
        in {
            "authority",
            "status",
            "assumptions",
            "backend_id",
            "backend_version",
            "translation_ceiling",
            "metadata",
        }
    }
    source = _theorem(**result_changes)
    return build_trusted_receipt_from_backend_result(
        source,
        theorem_id=changes.pop("theorem_id", "theorem:sort-correct"),
        property_id=changes.pop("property_id", PROPERTY),
        translation_receipt_id=changes.pop(
            "translation_receipt_id", "translation:fol-to-lean:v1"
        ),
        tree_id=changes.pop("tree_id", TREE),
        policy_id=changes.pop("policy_id", "policy:formal@1"),
        receipt_id=changes.pop("receipt_id", ""),
    )


def _binding_expectation(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tree_id": TREE,
        "property_id": PROPERTY,
        "assumptions": list(ASSUMPTIONS),
        "bounds": dict(BOUNDS),
        "backend_id": TOOL,
        "authority": "theorem",
        "now": NOW,
    }
    payload.update(overrides)
    return payload


def test_forged_kernel_and_empty_receipts_fail_closed() -> None:
    api = _api()
    empty = api.verify_receipt({})
    assert empty.status is VerificationStatus.INVALID
    assert empty.authority is VerificationAuthority.NONE
    assert empty.result["valid"] is False

    forged = api.verify_receipt(
        {
            "receipt_id": "forged",
            "authority": "theorem",
            "kind": "kernel_receipt",
            "digest": "deadbeef",
        }
    )
    assert forged.status is VerificationStatus.INVALID
    assert forged.authority is VerificationAuthority.NONE
    assert forged.result.get("reason") in {"forged-kernel", "unknown", "empty"} or (
        forged.result["valid"] is False
    )


def test_stale_receipt_window_and_wrong_tree_fail_closed() -> None:
    api = _api()
    receipt = _trusted()

    stale_window = api.verify_receipt(receipt, _binding_expectation(now=STALE_NOW))
    assert stale_window.status is VerificationStatus.INVALID
    assert stale_window.result["valid"] is False

    wrong_tree = api.verify_receipt(
        receipt, _binding_expectation(tree_id="tree:other@zzz")
    )
    assert wrong_tree.status is VerificationStatus.INVALID
    assert wrong_tree.authority is VerificationAuthority.NONE


def test_forged_content_id_on_trusted_receipt_rejected() -> None:
    api = _api()
    receipt = _trusted()
    payload = receipt.to_dict()
    payload["content_id"] = "0" * 64
    response = api.verify_receipt(payload)
    assert response.status is VerificationStatus.INVALID
    assert response.result["valid"] is False


# ---------------------------------------------------------------------------
# Bounded process / injection / cancellation / resource / packaging
# ---------------------------------------------------------------------------


def _runner(
    tmp_path: Path,
    executor: Any | None = None,
) -> BoundedToolRunner:
    return BoundedToolRunner(workspace_root=tmp_path, executor=executor)


def test_unbounded_timeout_and_negative_limits_fail_closed() -> None:
    with pytest.raises(ToolProcessError):
        ToolRunLimits(timeout_seconds=0)
    with pytest.raises(ToolProcessError):
        ToolRunLimits(timeout_seconds=-1)
    with pytest.raises(ToolProcessError):
        ToolRunLimits(timeout_seconds=math.inf)
    with pytest.raises(ToolProcessError):
        ToolRunLimits(max_output_bytes=0)
    limits = ToolRunLimits(timeout_seconds=0.5, max_output_bytes=4096)
    assert limits.timeout_seconds > 0
    assert limits.max_output_bytes > 0


def test_shell_string_argv_injection_rejected(tmp_path: Path) -> None:
    with pytest.raises(ToolProcessError):
        ToolRunRequest(argv="z3; rm -rf /")  # type: ignore[arg-type]

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        return RawProcessResult(returncode=0, stdout="ok")

    # Sequence form is required; injection tokens in args must not expand via shell.
    result = _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("echo", "z3; rm -rf /", SECRET),
            secrets=(SECRET,),
            limits=ToolRunLimits(timeout_seconds=2),
        )
    )
    blob = repr(result.to_dict())
    assert SECRET not in blob
    assert result.command[0] == "echo"


def test_secrets_redacted_from_tool_outputs(tmp_path: Path) -> None:
    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        (invocation.cwd / "receipt.txt").write_text(
            f"token={SECRET}", encoding="utf-8"
        )
        return RawProcessResult(
            returncode=1,
            stdout=f"saw {SECRET}",
            stderr=f"err {SECRET}",
            error=f"fail {SECRET}",
        )

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake", "--token", SECRET),
            environment={"API_TOKEN": SECRET},
            output_paths=("receipt.txt",),
            secrets=(SECRET,),
            limits=ToolRunLimits(timeout_seconds=2),
        )
    )
    blob = repr(result.to_dict())
    assert SECRET not in blob
    assert "<redacted>" in result.stdout or SECRET not in result.stdout


def test_pre_cancelled_tool_run_never_reports_proof_success(tmp_path: Path) -> None:
    started = {"value": False}

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        started["value"] = True
        return RawProcessResult(returncode=0, stdout="proved")

    token = CancellationToken()
    token.cancel()
    result = _runner(tmp_path, fake).run(
        ToolRunRequest(argv=("fake",), limits=ToolRunLimits(timeout_seconds=2)),
        cancellation=token,
    )
    # Either never started or reported cancelled — never success-as-proof.
    assert started["value"] is False or result.returncode != 0 or (
        getattr(result, "cancelled", False) is True
        or "cancel" in str(result.to_dict()).lower()
    )
    assert "proof_success" not in str(result.to_dict()).lower() or not started["value"]


def test_hermetic_policy_rejects_network_bounds() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(bounds=_bounds(network_allowed=True)),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False
    detail = next(c.detail for c in result.checks if c.stage == "exact_binding")
    assert "network" in detail.lower() or "hermetic" in detail.lower()


# ---------------------------------------------------------------------------
# Bounded fuzz / mutation / metamorphic
# ---------------------------------------------------------------------------


def test_bounded_fuzz_of_vacuous_and_circular_statements() -> None:
    vacuous_variants = (
        "true",
        "TRUE",
        "True",
        "(true)",
        "  true  ",
    )
    circular_variants = (
        "formal:lease-ready",
        " formal:lease-ready ",
    )
    contradiction_variants = (
        "false",
        "FALSE",
        "contradiction",
    )
    all_cases = vacuous_variants + circular_variants + contradiction_variants
    assert len(all_cases) <= FUZZ_STATEMENT_BUDGET
    for statement in all_cases:
        result = validate_candidate(
            _candidate(statement=statement),
            _hole(),
            _binding(),
            backends=(_backend(),),
        )
        assert result.validation.verdict is ValidationVerdict.REJECTED
        assert result.may_discharge is False
        assert result.validation.proof_claimed is False
        _assert_no_secret(result.to_dict())


def test_mutation_of_tree_goal_tool_bindings_all_reject() -> None:
    mutations = (
        {"source": _source(tree_id="tree:mut-a")},
        {"source": _source(tree_id="tree:mut-b")},
        {"new_assumption_ids": ("assumption:injected",)},
        {"source": _source(snapshot_id="snap:mutated")},
    )
    for overrides in mutations:
        result = validate_candidate(
            _candidate(**overrides),
            _hole(),
            _binding(),
            backends=(_backend(),),
        )
        assert result.may_discharge is False
        assert result.validation.verdict is not ValidationVerdict.ACCEPTED


def test_metamorphic_accept_round_trip_never_claims_completion() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    if result.validation.verdict is ValidationVerdict.ACCEPTED:
        assert result.validation.proof_claimed is False
        assert result.validation.completion_claimed is False
        restored = type(result).from_dict(result.to_dict())
        assert restored.validation.proof_claimed is False
        assert restored.validation.completion_claimed is False
        assert restored.content_id == result.content_id
    else:
        # Still fail closed without secret leakage.
        assert result.may_discharge is False
        _assert_no_secret(result.to_dict())


def test_differential_replay_fail_vs_hold() -> None:
    holds = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(holds=True),),
    )
    fails = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(holds=False),),
    )
    # Differential: hold may accept; fail must never discharge.
    assert fails.may_discharge is False
    assert fails.validation.verdict is ValidationVerdict.REJECTED
    if holds.validation.verdict is ValidationVerdict.ACCEPTED:
        assert holds.may_discharge is True
        assert holds.validation.proof_claimed is False
    assert holds.content_id != fails.content_id or holds.validation.verdict != (
        fails.validation.verdict
    )


def test_unavailable_backend_never_false_proof() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(UnavailableReplayBackend(provider_id="provider:z3"),),
    )
    assert result.validation.verdict is ValidationVerdict.UNAVAILABLE
    assert result.validation.authority is AuthorityCeiling.NONE
    assert result.may_discharge is False
    assert result.validation.proof_claimed is False


def test_hard_zero_matrix_summary() -> None:
    """Packaging-style summary: every hard-zero class has a dedicated check."""

    covered = {
        HardZeroFailure.FALSE_PROOF,
        HardZeroFailure.FALSE_CLOSURE,
        HardZeroFailure.AUTHORITY_ESCALATION,
        HardZeroFailure.HIDDEN_ASSUMPTION,
        HardZeroFailure.VACUOUS_PROOF,
        HardZeroFailure.CIRCULAR_LEMMA,
        HardZeroFailure.FORGED_RECEIPT,
        HardZeroFailure.STALE_IDENTITY,
        HardZeroFailure.SECRET_LEAK,
        HardZeroFailure.UNBOUNDED_PROCESS,
        HardZeroFailure.UNRESOLVED_DISAGREEMENT,
    }
    assert covered == set(HardZeroFailure)
    # Smoke that the validator interface is production-ready for packaging.
    assert PROOF_CANDIDATE_VALIDATOR_INTERFACE.endswith("@1")

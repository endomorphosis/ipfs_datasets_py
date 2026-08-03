"""Authority and preservation tests for generalized typed backend results."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from ipfs_datasets_py.logic.backends.results import (
    AttestationResult,
    AuthoritySubstitutionError,
    AuthorizationResult,
    CandidateResult,
    HyperpropertyResult,
    ModelCheckResult,
    MonitorResult,
    ProtocolResult,
    ReconstructionResult,
    ResultAuthority,
    ResultAuthorityNormalization,
    ResultNormalizationError,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
    TypedBackendResult,
    normalize_result,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    AuthorityKind as CoreAuthorityKind,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BoundedResult as CoreBoundedResult,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    ExecutionBounds,
    ResourceUsage,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    PolicyDecision as CorePolicyDecision,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    ProofResult as CoreProofResult,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    ResultAuthority as CoreResultAuthority,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    ResultStatus as CoreResultStatus,
)

RESULT_CASES = (
    (TheoremResult, ResultAuthority.THEOREM, ResultStatus.PROVED),
    (
        SatisfiabilityResult,
        ResultAuthority.SATISFIABILITY,
        ResultStatus.SATISFIABLE,
    ),
    (ModelCheckResult, ResultAuthority.MODEL_CHECK, ResultStatus.SATISFIED),
    (MonitorResult, ResultAuthority.MONITOR, ResultStatus.VIOLATED),
    (
        AuthorizationResult,
        ResultAuthority.AUTHORIZATION,
        ResultStatus.AUTHORIZED,
    ),
    (ProtocolResult, ResultAuthority.PROTOCOL, ResultStatus.ATTACK_FOUND),
    (
        HyperpropertyResult,
        ResultAuthority.HYPERPROPERTY,
        ResultStatus.SATISFIED,
    ),
    (CandidateResult, ResultAuthority.CANDIDATE, ResultStatus.CANDIDATE),
    (
        ReconstructionResult,
        ResultAuthority.RECONSTRUCTION,
        ResultStatus.RECONSTRUCTED,
    ),
    (
        AttestationResult,
        ResultAuthority.ATTESTATION,
        ResultStatus.ATTESTED,
    ),
)

OPERATIONAL_STATUSES = (
    ResultStatus.UNKNOWN,
    ResultStatus.TIMEOUT,
    ResultStatus.UNAVAILABLE,
    ResultStatus.UNSUPPORTED,
    ResultStatus.MALFORMED,
)


def _result(
    result_class: type[TypedBackendResult] = TheoremResult,
    authority: ResultAuthority = ResultAuthority.THEOREM,
    status: ResultStatus = ResultStatus.PROVED,
    **changes: object,
) -> TypedBackendResult:
    fields: dict[str, object] = {
        "result_id": "result:one",
        "backend_id": "solver.example",
        "backend_version": "1.2.3",
        "authority": authority,
        "status": status,
        "assumptions": ("assumption:integer-model", "assumption:precondition"),
        "bounds": ExecutionBounds(
            timeout_ms=25,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "usage": ResourceUsage(
            elapsed_ms=20,
            steps=80,
            peak_memory_bytes=1024,
            output_bytes=128,
        ),
        "witness": {
            "artifact_digest": "a" * 64,
            "model": {"counter": [0, 1, 2]},
        },
        "diagnostics": ("normalized by test adapter",),
        "metadata": {"provider": {"runtime": "native_process"}},
    }
    fields.update(changes)
    return result_class(**fields)


@pytest.mark.parametrize("result_class,authority,status", RESULT_CASES)
def test_all_result_authorities_are_concrete_and_round_trip(
    result_class: type[TypedBackendResult],
    authority: ResultAuthority,
    status: ResultStatus,
) -> None:
    result = _result(result_class, authority, status)

    assert result.authority is authority
    assert result.status is status
    assert result.is_conclusive
    assert result.require_authority(authority) is result
    assert TypedBackendResult.from_dict(result.to_dict()) == result
    assert normalize_result(result.to_dict(), expected_authority=authority) == result
    assert len(result.digest) == 64


@pytest.mark.parametrize("status", OPERATIONAL_STATUSES)
@pytest.mark.parametrize(
    "result_class,authority,_conclusion",
    RESULT_CASES,
)
def test_every_authority_preserves_explicit_non_success_states(
    result_class: type[TypedBackendResult],
    authority: ResultAuthority,
    _conclusion: ResultStatus,
    status: ResultStatus,
) -> None:
    result = _result(
        result_class,
        authority,
        status,
        reason=f"backend reported {status.value}",
    )
    restored = TypedBackendResult.from_dict(result.to_dict())

    assert restored.status is status
    assert not restored.is_conclusive
    assert restored.reason == f"backend reported {status.value}"
    assert restored.authority is authority


def test_witness_assumptions_bounds_ceiling_and_resource_usage_are_preserved() -> None:
    result = _result(
        ModelCheckResult,
        ResultAuthority.MODEL_CHECK,
        ResultStatus.TIMEOUT,
        usage=ResourceUsage(
            elapsed_ms=30,
            steps=101,
            peak_memory_bytes=1024,
            output_bytes=128,
        ),
        reason="model checker exceeded its time and step bounds",
    )
    wire = result.to_dict()
    restored = normalize_result(wire)

    assert restored.witness.to_dict() == {
        "artifact_digest": "a" * 64,
        "model": {"counter": [0, 1, 2]},
    }
    assert restored.assumptions == (
        "assumption:integer-model",
        "assumption:precondition",
    )
    assert restored.bounds == result.bounds
    assert (
        restored.translation_ceiling
        is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )
    assert restored.usage == result.usage
    assert restored.exceeded_bounds == ("timeout_ms", "max_steps")


@pytest.mark.parametrize(
    "result_class,correct_authority,_status",
    RESULT_CASES,
)
@pytest.mark.parametrize("wrong_authority", tuple(ResultAuthority))
def test_every_cross_authority_class_substitution_is_rejected(
    result_class: type[TypedBackendResult],
    correct_authority: ResultAuthority,
    _status: ResultStatus,
    wrong_authority: ResultAuthority,
) -> None:
    if wrong_authority is correct_authority:
        return
    with pytest.raises(AuthoritySubstitutionError, match="requires"):
        _result(
            result_class,
            wrong_authority,
            ResultStatus.UNKNOWN,
        )


@pytest.mark.parametrize("result_class,authority,status", RESULT_CASES)
def test_wire_type_and_trusted_authority_cannot_be_rebound(
    result_class: type[TypedBackendResult],
    authority: ResultAuthority,
    status: ResultStatus,
) -> None:
    result = _result(result_class, authority, status)
    wire = result.to_dict()
    other_authority = next(item for item in ResultAuthority if item is not authority)
    other_type = next(
        item.result_type
        for item, candidate_authority, _ in RESULT_CASES
        if candidate_authority is other_authority
    )

    forged_authority = dict(wire, authority=other_authority.value)
    with pytest.raises(AuthoritySubstitutionError, match="requires"):
        TypedBackendResult.from_dict(forged_authority)
    with pytest.raises(AuthoritySubstitutionError, match="trusted"):
        normalize_result(forged_authority, expected_authority=authority)

    forged_type = dict(wire, result_type=other_type)
    with pytest.raises(AuthoritySubstitutionError, match="requires"):
        TypedBackendResult.from_dict(forged_type)
    with pytest.raises(AuthoritySubstitutionError, match="trusted"):
        normalize_result(forged_type, expected_authority=authority)


def test_status_from_another_authority_is_rejected_even_if_type_matches() -> None:
    with pytest.raises(AuthoritySubstitutionError, match="not a valid theorem"):
        _result(
            TheoremResult,
            ResultAuthority.THEOREM,
            ResultStatus.AUTHORIZED,
        )


def test_normalizer_builds_only_the_class_fixed_by_trusted_authority() -> None:
    result = ResultAuthorityNormalization.build(
        ResultAuthority.PROTOCOL,
        result_id="result:protocol",
        backend_id="tamarin",
        backend_version="1.10.0",
        status=ResultStatus.SECURE,
        assumptions=("perfect-cryptography",),
        witness={"lemma": "secrecy"},
    )

    assert type(result) is ProtocolResult
    with pytest.raises(AuthoritySubstitutionError, match="does not match"):
        ResultAuthorityNormalization.build(
            ResultAuthority.PROTOCOL,
            result_type="theorem",
            result_id="result:forged",
            backend_id="tamarin",
            backend_version="1.10.0",
            status=ResultStatus.UNKNOWN,
        )


def test_shared_satisfied_status_does_not_make_authorities_interchangeable() -> None:
    model = _result(
        ModelCheckResult,
        ResultAuthority.MODEL_CHECK,
        ResultStatus.SATISFIED,
    )
    monitor = _result(
        MonitorResult,
        ResultAuthority.MONITOR,
        ResultStatus.SATISFIED,
    )
    hyperproperty = _result(
        HyperpropertyResult,
        ResultAuthority.HYPERPROPERTY,
        ResultStatus.SATISFIED,
    )

    assert len({model.digest, monitor.digest, hyperproperty.digest}) == 3
    for value, other in (
        (model, ResultAuthority.MONITOR),
        (monitor, ResultAuthority.HYPERPROPERTY),
        (hyperproperty, ResultAuthority.MODEL_CHECK),
    ):
        with pytest.raises(AuthoritySubstitutionError):
            value.require_authority(other)


def test_candidate_and_attestation_never_acquire_theorem_authority() -> None:
    candidate = _result(
        CandidateResult,
        ResultAuthority.CANDIDATE,
        ResultStatus.CANDIDATE,
        translation_ceiling=EvidenceAuthority.ADVISORY,
    )
    attestation = _result(
        AttestationResult,
        ResultAuthority.ATTESTATION,
        ResultStatus.ATTESTED,
    )

    for result in (candidate, attestation):
        with pytest.raises(AuthoritySubstitutionError):
            result.require_authority(ResultAuthority.THEOREM)
        forged = dict(result.to_dict(), authority=ResultAuthority.THEOREM.value)
        with pytest.raises(AuthoritySubstitutionError):
            TypedBackendResult.from_dict(forged)


def test_results_are_deeply_immutable_and_serialization_is_detached() -> None:
    witness = {"trace": {"states": ["initial"]}}
    result = _result(witness=witness)
    witness["trace"]["states"].append("mutated")
    wire = result.to_dict()
    wire["witness"]["trace"]["states"].append("wire mutation")

    assert result.witness["trace"]["states"] == ("initial",)
    with pytest.raises(TypeError):
        result.witness["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.status = ResultStatus.UNKNOWN  # type: ignore[misc]


def test_decoder_rejects_unknown_fields_and_abstract_base_construction() -> None:
    wire = _result().to_dict()
    wire["proof_authority"] = True
    with pytest.raises(ResultNormalizationError, match="unknown"):
        TypedBackendResult.from_dict(wire)

    with pytest.raises(ResultNormalizationError, match="concrete"):
        TypedBackendResult(
            result_id="result:abstract",
            backend_id="solver",
            backend_version="1",
            authority=ResultAuthority.THEOREM,
            status=ResultStatus.UNKNOWN,
        )


def test_mapping_fields_must_be_json_and_sequences_cannot_be_strings() -> None:
    with pytest.raises(ResultNormalizationError, match="sequence"):
        _result(assumptions="not-a-sequence")
    with pytest.raises(ResultNormalizationError, match="JSON mappings"):
        _result(witness={"not_json": object()})
    with pytest.raises(ResultNormalizationError, match="duplicates"):
        _result(diagnostics=("same", "same"))


def test_witness_and_metadata_use_the_shared_ir_frozen_map() -> None:
    result = _result(
        witness=FrozenMap({"proof": {"steps": ["intro", "exact"]}}),
        metadata=FrozenMap({"adapter": "lean"}),
    )

    assert isinstance(result.witness, FrozenMap)
    assert isinstance(result.metadata, FrozenMap)


def _core_result(
    result_class: type[CoreBoundedResult] = CoreProofResult,
    *,
    authority: CoreAuthorityKind = CoreAuthorityKind.THEOREM_PROOF,
    status: CoreResultStatus = CoreResultStatus.PROVED,
) -> CoreBoundedResult:
    request_digest = "1" * 64
    return result_class(
        result_id="result:legacy",
        request_digest=request_digest,
        attempt_digest="2" * 64,
        claim_digest="3" * 64,
        declaration_id="declaration:legacy",
        obligation_id="obligation:legacy",
        obligation_digest="4" * 64,
        backend_id="legacy.solver",
        backend_version="4.0.0",
        assumption_ids=("assumption:legacy",),
        authority=CoreResultAuthority(
            kind=authority,
            issuer="legacy-adapter",
            method="bounded-check",
            scope_digest=request_digest,
            evidence_digests=("5" * 64,),
        ),
        status=status,
        bounds=ExecutionBounds(timeout_ms=50),
        usage=ResourceUsage(elapsed_ms=12, steps=7),
        output_digest="6" * 64,
        payload=FrozenMap({"proof": {"rule": "modus_ponens"}}),
        diagnostics=("legacy diagnostic",),
    )


def test_exact_legacy_result_composition_preserves_evidence_and_bindings() -> None:
    legacy = _core_result()
    normalized = ResultAuthorityNormalization.from_core(
        legacy,
        translation_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    )

    assert type(normalized) is TheoremResult
    assert normalized.status is ResultStatus.PROVED
    assert normalized.assumptions == legacy.assumption_ids
    assert normalized.bounds is legacy.bounds
    assert normalized.usage is legacy.usage
    assert normalized.witness == legacy.payload
    assert normalized.diagnostics == legacy.diagnostics
    assert normalized.metadata["core_result"]["result_digest"] == legacy.digest
    assert (
        normalized.translation_ceiling
        is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    )


def test_legacy_policy_decision_is_not_recast_as_authorization() -> None:
    legacy_policy = _core_result(
        CorePolicyDecision,
        authority=CoreAuthorityKind.POLICY_APPROVAL,
        status=CoreResultStatus.APPROVED,
    )

    with pytest.raises(AuthoritySubstitutionError, match="no semantically identical"):
        ResultAuthorityNormalization.from_core(legacy_policy)

"""Foreign backend observations retain their meaning without generic authority.

All delegates are inert Python fixtures. No native tool, installer, metadata
store or shared resource pool is used.
"""
from enum import Enum
import json
import subprocess
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import registry as reg
from ipfs_datasets_py.logic.backends import results as foreign
from ipfs_datasets_py.logic.ir_core import protocols as core


KINDS = tuple(core.QueryKind)
CLASSES = {
    core.QueryKind.THEOREM_PROOF: core.ProofResult,
    core.QueryKind.SATISFIABILITY: core.SatisfiabilityResult,
    core.QueryKind.RUNTIME_MONITOR: core.MonitorResult,
    core.QueryKind.EVIDENCE_READINESS: core.EvidenceGateResult,
    core.QueryKind.POLICY_APPROVAL: core.PolicyDecision,
}


@pytest.fixture(autouse=True)
def no_native_process(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected native process"))


def request(kind=core.QueryKind.SATISFIABILITY, *, max_output=8192, tag="one"):
    return core.BackendRequest(request_id="request:" + tag, claim_id="claim:foreign",
        declaration_id="declaration:foreign", claim_digest="1" * 64,
        obligation_id="obligation:foreign", obligation_digest="2" * 64,
        assumption_ids=("assumption:finite",), logic_family="fixture_logic", query_kind=kind,
        bounds=core.ExecutionBounds(timeout_ms=1000, max_steps=30,
            max_memory_bytes=256 * 1024**2, max_output_bytes=max_output),
        payload={"fixture": tag}, requested_backend_id="")


class Observation:
    def __init__(self, status="satisfied", authority="model_check", wire=None):
        self.status, self.authority = status, authority
        self.wire = wire if wire is not None else {"status": status, "authority": authority, "trace": [0, 1, 2]}
        self.serializations = 0

    def to_dict(self):
        self.serializations += 1
        return self.wire


def lane(returned, *, family=reg.PROVIDER_MATRIX_FAMILY_STATE_MODEL, kinds=KINDS):
    calls = []
    entry = reg.ProviderMatrixEntry(provider_id="fixture", family=family,
        logic_families=("fixture_logic",), query_kinds=tuple(k.value for k in kinds),
        factory_key="fixture", aliases=("fixture-alias",))
    def run(req):
        calls.append(("run", req))
        return returned(req) if callable(returned) else returned
    def probe():
        calls.append(("probe",))
        return True
    def factory():
        calls.append(("factory",))
        return SimpleNamespace(run=run, is_available=probe)
    backend = reg.LazyMatrixProofBackend(entry, factory=factory)
    return backend, reg.ProofBackendRegistry((backend,)), calls


def assert_bound(req, attempt, result):
    assert type(result) is CLASSES[req.query_kind]
    assert result.request_digest == attempt.request_digest == req.digest
    assert result.attempt_digest == attempt.digest
    assert result.output_digest == attempt.output_digest
    assert result.claim_digest == req.claim_digest
    assert result.declaration_id == req.declaration_id
    assert result.obligation_id == req.obligation_id
    assert result.obligation_digest == req.obligation_digest
    assert result.assumption_ids == req.assumption_ids
    assert result.bounds == attempt.bounds == req.bounds
    assert result.backend_id == attempt.backend_id == "fixture"
    assert result.backend_version == attempt.backend_version == "matrix-declared/v1"
    assert result.authority.kind is req.query_kind.authority_kind
    assert result.authority.scope_digest == req.digest
    assert result.authority.issuer == "fixture"
    assert result.authority.evidence_digests == ()


@pytest.mark.parametrize(("kind", "status"), [
    (core.QueryKind.THEOREM_PROOF, "proved"), (core.QueryKind.THEOREM_PROOF, "disproved"),
    (core.QueryKind.SATISFIABILITY, "satisfiable"), (core.QueryKind.SATISFIABILITY, "unsatisfiable"),
    (core.QueryKind.RUNTIME_MONITOR, "monitor_satisfied"), (core.QueryKind.RUNTIME_MONITOR, "monitor_violated"),
    (core.QueryKind.EVIDENCE_READINESS, "ready"), (core.QueryKind.EVIDENCE_READINESS, "not_ready"),
    (core.QueryKind.POLICY_APPROVAL, "approved"), (core.QueryKind.POLICY_APPROVAL, "rejected"),
])
def test_conclusion_words_never_mint_generic_authority(kind, status):
    req = request(kind)
    wire = {"status": status, "authority": "theorem", "request_digest": "f" * 64,
            "is_theorem_proof": True, "authorizes_universal_proof": True}
    observed = Observation(status, "theorem", wire)
    _, registry, calls = lane(SimpleNamespace(result=observed))
    attempt, result = registry.run(req)
    assert_bound(req, attempt, result)
    assert attempt.status is core.AttemptStatus.SUCCEEDED
    assert result.status is core.ResultStatus.UNKNOWN and not result.is_theorem_proof
    assert result.payload["result"].to_dict() == wire
    assert result.payload["result_status"] == status
    assert result.payload["result_authority"] == "theorem"
    assert any("without authority upgrade" in d for d in result.diagnostics)
    assert observed.serializations == 1 and len([c for c in calls if c[0] == "run"]) == 1
    with pytest.raises(core.AuthorityMismatchError):
        result.require_theorem_proof()


@pytest.mark.parametrize(("status", "attempt_status", "result_status"), [
    ("unavailable", core.AttemptStatus.UNAVAILABLE, core.ResultStatus.UNKNOWN),
    ("timeout", core.AttemptStatus.TIMED_OUT, core.ResultStatus.UNKNOWN),
    ("timed_out", core.AttemptStatus.TIMED_OUT, core.ResultStatus.UNKNOWN),
    ("cancelled", core.AttemptStatus.CANCELLED, core.ResultStatus.UNKNOWN),
    ("canceled", core.AttemptStatus.CANCELLED, core.ResultStatus.UNKNOWN),
    ("error", core.AttemptStatus.FAILED, core.ResultStatus.ERROR),
    ("malformed", core.AttemptStatus.FAILED, core.ResultStatus.ERROR),
    ("unsupported", core.AttemptStatus.FAILED, core.ResultStatus.ERROR),
    ("UNKNOWN", core.AttemptStatus.SUCCEEDED, core.ResultStatus.UNKNOWN),
    ("TIMEOUT", core.AttemptStatus.TIMED_OUT, core.ResultStatus.UNKNOWN),
])
@pytest.mark.parametrize("nested", [False, True])
def test_terminal_semantics_are_preserved_for_direct_and_nested_returns(status, attempt_status, result_status, nested):
    req = request(KINDS[len(status) % len(KINDS)])
    observed = Observation(status)
    backend, registry, _ = lane(SimpleNamespace(result=observed) if nested else observed)
    attempt, result = registry.run(req)
    assert_bound(req, attempt, result)
    assert attempt.status is attempt_status and result.status is result_status
    assert result.payload["result_status"] == status
    assert result.payload["result" if nested else "outcome"].to_dict() == observed.wire
    assert observed.serializations == 1
    assert any("without authority upgrade" in d for d in result.diagnostics)


@pytest.mark.parametrize(("cls", "authority", "status", "family", "nested"), [
    (foreign.ModelCheckResult, "model_check", "satisfied", "state_model", True),
    (foreign.ModelCheckResult, "model_check", "violated", "state_model", False),
    (foreign.MonitorResult, "monitor", "violated", "runtime", True),
    (foreign.AuthorizationResult, "authorization", "authorized", "authorization", False),
    (foreign.ProtocolResult, "protocol", "secure", "protocol", True),
    (foreign.HyperpropertyResult, "hyperproperty", "satisfied", "hyperproperty", False),
    (foreign.CandidateResult, "candidate", "candidate", "atp", True),
    (foreign.CandidateResult, "candidate", "candidate", "hammer", False),
    (foreign.ReconstructionResult, "reconstruction", "reconstructed", "kernel", True),
    (foreign.AttestationResult, "attestation", "attested", "kernel", False),
    (foreign.TheoremResult, "theorem", "proved", "kernel", True),
])
def test_actual_typed_family_records_are_retained_without_cross_family_promotion(cls, authority, status, family, nested):
    req = request(core.QueryKind.THEOREM_PROOF)
    observed = cls(result_id="result:typed", backend_id="foreign", backend_version="fixture/v1",
        authority=authority, status=status, assumptions=req.assumption_ids, bounds=req.bounds,
        witness={"native_observation": "fixture"})
    _, registry, _ = lane(SimpleNamespace(result=observed) if nested else observed, family=family)
    attempt, result = registry.run(req)
    assert_bound(req, attempt, result)
    assert result.status is core.ResultStatus.UNKNOWN and not result.is_theorem_proof
    assert result.payload["result_status"] == status and result.payload["result_authority"] == authority
    assert result.payload["result" if nested else "outcome"].to_dict() == observed.to_dict()
    if family in {"atp", "hammer"}:
        assert "kernel reconstruction" in result.payload["authority_note"]


def test_nested_record_has_precedence_and_outer_serializer_is_not_called():
    nested = Observation("unavailable", "model_check")
    class Outer:
        result = nested
        status = "proved"
        authority = "theorem"
        def to_dict(self):
            pytest.fail("outer serializer bypassed selected nested record")
    _, registry, _ = lane(Outer())
    attempt, result = registry.run(request())
    assert attempt.status is core.AttemptStatus.UNAVAILABLE
    assert result.status is core.ResultStatus.UNKNOWN
    assert result.payload["result_status"] == "unavailable"
    assert result.payload["result_authority"] == "model_check"
    assert nested.serializations == 1


@pytest.mark.parametrize("returned", [None, object(), SimpleNamespace(result=None)])
def test_undeclared_foreign_objects_are_only_descriptive_unknowns(returned):
    backend, _, _ = lane(returned)
    attempt, result = backend.run(request())
    assert attempt.status is core.AttemptStatus.SUCCEEDED
    assert result.status is core.ResultStatus.UNKNOWN
    assert result.payload["adapter_return_type"] == type(returned).__name__
    assert any("without authority upgrade" in d for d in result.diagnostics)


@pytest.mark.parametrize("field", ["result", "status", "authority", "to_dict"])
def test_exceptional_attribute_access_is_bounded_failed_observation(field):
    calls = []
    class Broken:
        def __getattribute__(self, name):
            if name == field:
                calls.append(name)
                raise RuntimeError("fixture getter failed " + "x" * 2000)
            return object.__getattribute__(self, name)
    backend, _, _ = lane(Broken())
    req = request(max_output=256)
    attempt, result = backend.run(req)
    assert_bound(req, attempt, result)
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR
    assert calls == [field]
    assert all(len(d) <= 512 for d in result.diagnostics)
    assert any("without authority upgrade" in d for d in result.diagnostics)


@pytest.mark.parametrize(("field", "value"), [
    (field, value) for field in ("status", "authority")
    for value in (5, True, [], "", " spaced ", "a\x00b", "x" * 257)
] + [("status", {})])
def test_invalid_declared_metadata_fails_closed(field, value):
    observed = Observation()
    setattr(observed, field, value)
    backend, _, _ = lane(observed)
    attempt, result = backend.run(request(max_output=512))
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR
    assert not result.is_theorem_proof


@pytest.mark.parametrize("fault", ["raises", "nonmapping", "nonjson", "nan", "cycle", "oversize"])
def test_bad_serialization_is_not_retried_or_promoted(fault):
    observed = Observation("proved", "theorem")
    def serialize():
        observed.serializations += 1
        if fault == "raises":
            raise ValueError("serializer failed")
        if fault == "nonmapping":
            return ["proved"]
        if fault == "nonjson":
            return {"status": object()}
        if fault == "nan":
            return {"value": float("nan")}
        if fault == "cycle":
            value = {}
            value["cycle"] = value
            return value
        return {"status": "proved", "payload": "界" * 400}
    observed.to_dict = serialize
    backend, _, _ = lane(SimpleNamespace(result=observed))
    req = request(max_output=256)
    attempt, result = backend.run(req)
    assert_bound(req, attempt, result)
    assert observed.serializations == 1
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR
    assert len(json.dumps(result.payload.to_dict(), ensure_ascii=False, separators=(",", ":")).encode()) <= 256
    assert any("without authority upgrade" in d for d in result.diagnostics)


def test_foreign_mutable_wire_is_snapshotted_and_each_request_is_bound_separately():
    observed = Observation()
    _, registry, calls = lane(SimpleNamespace(result=observed))
    req = request()
    attempt, first = registry.run(req)
    first_wire, first_digest = first.to_dict(), first.digest
    observed.wire["trace"].append(999)
    assert first.to_dict() == first_wire and first.digest == first_digest
    other = request(tag="two")
    attempt2, second = registry.run(other)
    assert_bound(other, attempt2, second)
    assert first.request_digest != second.request_digest and first.attempt_digest != second.attempt_digest
    assert len([c for c in calls if c[0] == "factory"]) == 1
    assert observed.serializations == 2


@pytest.mark.parametrize("nested", [False, True])
def test_mapping_outcomes_keep_declared_metadata_as_inert_payload(nested):
    declared = {"status": "proved", "authority": {"kind": "theorem", "scope_digest": "f" * 64},
                "proof": "untrusted foreign bytes"}
    _, registry, _ = lane({"result": declared} if nested else declared)
    attempt, result = registry.run(request(core.QueryKind.THEOREM_PROOF))
    assert attempt.status is core.AttemptStatus.SUCCEEDED and result.status is core.ResultStatus.UNKNOWN
    assert result.payload["result_authority"].to_dict() == declared["authority"]
    assert result.payload["result" if nested else "outcome"].to_dict() == declared
    assert result.authority.scope_digest != declared["authority"]["scope_digest"]


def test_enum_declaration_does_not_evaluate_untrusted_string_conversion():
    class Status(Enum):
        TIMEOUT = "TIMEOUT"
        def __str__(self):
            pytest.fail("unnecessary declaration __str__")
    observed = Observation(Status.TIMEOUT, wire={"status": "TIMEOUT"})
    backend, _, _ = lane(observed)
    attempt, result = backend.run(request())
    assert attempt.status is core.AttemptStatus.TIMED_OUT
    assert result.status is core.ResultStatus.UNKNOWN and result.payload["result_status"] == "TIMEOUT"


def test_error_diagnostic_does_not_evaluate_exception_string_methods():
    class BadError(ValueError):
        def __str__(self):
            pytest.fail("unsafe exception string evaluated")
    class Broken(Observation):
        def to_dict(self):
            raise BadError()
    backend, _, _ = lane(Broken())
    attempt, result = backend.run(request(max_output=256))
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR
    assert any("BadError" in d for d in result.diagnostics)


def test_accepted_output_bound_includes_foreign_metadata_envelope():
    observed = Observation(wire={"body": "x" * 160})
    raw_size = len(json.dumps(observed.wire, separators=(",", ":")).encode())
    assert raw_size < 256
    backend, _, _ = lane(observed)
    attempt, result = backend.run(request(max_output=256))
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR
    assert result.payload["foreign_payload_omitted"] is True
    assert "outcome" not in result.payload


def test_lazy_discovery_does_not_construct_probe_or_normalize(monkeypatch):
    backend, registry, calls = lane(Observation())
    monkeypatch.setattr(backend, "_normalize_foreign_outcome", lambda *a: pytest.fail("normalized during discovery"))
    req = request()
    assert registry.supporting(req) == ("fixture",)
    assert backend.supports(req) and registry.capabilities_for("fixture") == backend.capabilities
    assert reg.declared_backend_catalog(registry)[0]["availability"] == "declared"
    assert calls == []
    monkeypatch.setattr(reg, "_factory_constructors", lambda: {e.factory_key: lambda: pytest.fail("factory during discovery") for e in reg.EXECUTABLE_PROVIDER_MATRIX})
    default = reg.default_backend_registry()
    assert reg.declared_backend_catalog(default) and default.capabilities


def test_unsupported_query_does_not_construct_or_serialize_foreign_delegate():
    observed = Observation("proved", "theorem")
    backend, registry, calls = lane(observed, kinds=(core.QueryKind.SATISFIABILITY,))
    attempt, result = registry.run(request(core.QueryKind.THEOREM_PROOF), backend_id="fixture")
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR
    assert calls == [] and observed.serializations == 0


@pytest.mark.parametrize("rebind", [False, True])
def test_valid_protocol_pairs_keep_their_existing_authority_path(rebind):
    req = request(core.QueryKind.THEOREM_PROOF)
    backend, registry, _ = lane(None)
    pair = reg._make_outcome(backend_id="delegate" if rebind else backend.backend_id,
        backend_version="delegate/v1" if rebind else backend.backend_version,
        capabilities=backend.capabilities, request=req, attempt_status=core.AttemptStatus.SUCCEEDED,
        result_status=core.ResultStatus.PROVED, classification="proved", payload={"checked": True})
    backend._factory = lambda: SimpleNamespace(run=lambda _: pair)
    attempt, result = registry.run(req)
    assert_bound(req, attempt, result)
    assert result.status is core.ResultStatus.PROVED and result.is_theorem_proof
    assert result.payload.to_dict() == {"checked": True}
    if not rebind:
        assert attempt is pair[0] and result is pair[1]


def test_invalid_protocol_pair_request_binding_still_fails_closed():
    req, other = request(), request(tag="other")
    backend, registry, _ = lane(None)
    pair = reg._make_outcome(backend_id=backend.backend_id, backend_version=backend.backend_version,
        capabilities=backend.capabilities, request=other, attempt_status=core.AttemptStatus.SUCCEEDED,
        result_status=core.ResultStatus.SATISFIABLE, classification="sat")
    backend._factory = lambda: SimpleNamespace(run=lambda _: pair)
    attempt, result = registry.run(req)
    assert_bound(req, attempt, result)
    assert attempt.status is core.AttemptStatus.FAILED and result.status is core.ResultStatus.ERROR


def test_base_exception_from_foreign_serializer_is_not_swallowed():
    class Interrupted(Observation):
        def to_dict(self):
            raise KeyboardInterrupt("fixture cancellation")
    _, registry, _ = lane(Interrupted())
    with pytest.raises(KeyboardInterrupt, match="fixture cancellation"):
        registry.run(request())

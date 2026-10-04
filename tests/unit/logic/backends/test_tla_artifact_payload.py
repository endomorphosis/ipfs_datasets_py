"""Serialized TLA execution retains compiler bounds and loss disclosures.

Injected executors provide bounded fixture observations. No native solver,
installer or shared scheduler is used.
"""
from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, registry, resource_admission
from ipfs_datasets_py.logic.backends.results import AuthoritySubstitutionError
from ipfs_datasets_py.logic.backends.smt import operation_budget
from ipfs_datasets_py.logic.backends.tla import compiler, execution_v2 as v2, runners
from ipfs_datasets_py.logic.ir_core import protocols


SUCCESS = "Model checking completed. No error has been found.\nChecker reports no error\n"
TRACE = ("Error: Invariant Safety is violated.\nThe following behavior constitutes a counter-example:\n"
         "State 1: <Initial predicate>\n/\\ n = 0\nState 2: <Next>\n/\\ n = 4\n")
HELP = "TLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31\nSYNOPSIS\nDESCRIPTION\n"


def artifact():
    return compiler.GeneratedTLAArtifacts(
        module_name="PayloadCounter",
        model_text=("---- MODULE PayloadCounter ----\nEXTENDS Integers\n\\* Déclaration bornée\n"
            "VARIABLE n\nInit == n = 0\nNext == n < 4 /\\ n' = n + 1\n"
            "Spec == Init /\\ [][Next]_n\nSafety == n \\in 0..3\nProgress == <> (n = 3)\n====\n"),
        tlc_config_text="SPECIFICATION Spec\nINVARIANT Safety\nPROPERTY Progress\nCHECK_DEADLOCK FALSE\n",
        apalache_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        source_map=(
            compiler.TLASourceMapEntry("source:variable:n", "state_variable", "n", "variable", "VARIABLE n"),
            compiler.TLASourceMapEntry("source:predicate:safety", "state_predicate", "Safety", "invariant", "Safety == n \\in 0..3"),
        ),
        losses=(compiler.ProjectionLoss(loss_id="loss:environment", projection="concurrency",
            severity="over_approximation", construct="environment interleavings",
            statement="The external environment is conservatively approximated.",
            handling="approximated", preservation="approximate", approximation="over_approximation"),),
        bounds=compiler.TLACompileBounds(max_steps=3, max_variables=5, max_actions=7,
            max_predicates=11, max_enum_members=13, max_integer_span=17,
            max_module_bytes=8192, default_integer_lower=-2, default_integer_upper=9),
        source_document_id="source:payload-counter", source_kind="concurrency",
        safety_properties=("Safety",), liveness_properties=("Progress",),
        fairness_limitations=("Only finite environment bounds are represented.",))


def request(payload, *, provider="tlc"):
    return protocols.BackendRequest(request_id="request:artifact-payload", claim_id="claim:counter",
        declaration_id="declaration:counter", claim_digest="1" * 64,
        obligation_id="obligation:counter", obligation_digest="2" * 64,
        assumption_ids=("assumption:bounded",), logic_family="state_transition",
        query_kind=protocols.QueryKind.SATISFIABILITY,
        bounds=protocols.ExecutionBounds(timeout_ms=2000, max_steps=9,
            max_memory_bytes=256 * 1024**2, max_output_bytes=65536),
        payload=payload, requested_backend_id=provider)


@pytest.fixture(autouse=True)
def no_native_or_shared_pool(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("artifact fixtures must not start native tools or consult the shared pool")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", denied)
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", denied)
    # Pin receipt timing so object and serialized paths can be compared exactly.
    clock = SimpleNamespace(monotonic=lambda: 100.0)
    monkeypatch.setattr(runners, "time", clock)
    monkeypatch.setattr(operation_budget, "time", clock)


@pytest.fixture
def backend_factory(tmp_path):
    workspaces = []
    def make(provider="tlc", *, counterexample=False):
        calls = []
        def execute(invocation, cancellation):
            phase = "version" if invocation.argv[-1] in ("-help", "version") else "model"
            inputs = {p.name: p.read_text() for p in invocation.cwd.iterdir() if p.is_file()}
            calls.append((phase, invocation, inputs))
            workspaces.append(invocation.cwd)
            if phase == "version":
                return process.RawProcessResult(returncode=1 if provider == "tlc" else 0,
                    stdout=HELP if provider == "tlc" else "0.58.3\n")
            return process.RawProcessResult(returncode=12 if counterexample else 0,
                stdout=TRACE if counterexample else SUCCESS)
        injected = process.BoundedToolRunner(executor=execute, workspace_root=tmp_path)
        kind = runners.TLCBackend if provider == "tlc" else runners.ApalacheBackend
        backend = kind(executable=sys.executable, runner=injected, jvm_probe=lambda: True,
            lazy_install=False, compiler=compiler.TLACompiler(bounds=compiler.TLACompileBounds(max_steps=71)))
        return backend, calls
    yield make
    assert all(not path.exists() for path in workspaces)


@pytest.mark.parametrize("provider", ["tlc", "apalache"])
@pytest.mark.parametrize("nested", [False, True])
def test_serialized_raw_execution_is_identical_to_typed_artifact_execution(backend_factory, provider, nested):
    original = artifact()
    wire = json.loads(json.dumps(original.to_dict(), ensure_ascii=False))
    unchanged = deepcopy(wire)
    req = request({"artifacts": wire} if nested else wire, provider=provider)
    backend, calls = backend_factory(provider)
    typed = backend.check(original, request=req)
    restored = backend.run(req)
    assert restored.to_dict() == typed.to_dict()
    assert restored.artifacts.to_dict() == original.to_dict()
    assert restored.artifacts.bounds == original.bounds != backend._compiler.bounds
    assert restored.artifacts.source_map == original.source_map
    assert restored.artifacts.losses == original.losses
    assert restored.receipt.artifact_digest == original.artifact_digest
    assert restored.request_digest == req.digest
    assert restored.result.bounds == req.bounds
    assert restored.result.authority.value == "model_check"
    with pytest.raises(AuthoritySubstitutionError):
        restored.result.require_authority("theorem")
    assert restored.receipt.bounded and not restored.receipt.unbounded_proof
    assert wire == unchanged
    assert [p for p, _, _ in calls] == ["model", "version", "model", "version"]
    for phase, invocation, inputs in calls:
        if phase == "model":
            assert inputs["PayloadCounter.tla"] == original.model_text
            assert original.configuration_for(provider) in inputs.values()
            if provider == "apalache":
                assert "--length=3" in invocation.argv


def test_roundtrip_preserves_source_mapping_for_counterexample_replay(backend_factory):
    original = artifact()
    backend, _ = backend_factory(counterexample=True)
    result = backend.run(request({"artifacts": original.to_dict()}))
    trace = result.receipt.counterexample
    assert trace is not None and [s.assignments["n"] for s in trace.states] == ["0", "4"]
    assert all("unmapped" not in note for note in trace.replay_notes)
    assert any("replayed mapped symbols: n" in note for note in trace.replay_notes)
    assert result.artifacts.losses == original.losses
    assert result.receipt.artifact_digest == original.artifact_digest


@pytest.mark.parametrize("provider", ["tlc", "apalache"])
def test_registry_retains_decoded_bounds_without_upgrading_model_authority(backend_factory, provider):
    original = artifact()
    backend, calls = backend_factory(provider)
    declared_id = "tla_tlc" if provider == "tlc" else "apalache"
    entry = next(e for e in registry.EXECUTABLE_PROVIDER_MATRIX if e.provider_id == declared_id)
    wrapper = registry.LazyMatrixProofBackend(entry, factory=lambda: backend)
    req = replace(request({"artifacts": original.to_dict()}, provider=provider), requested_backend_id="")
    attempt, result = registry.ProofBackendRegistry((wrapper,)).run(req, backend_id=declared_id)
    assert attempt.status is protocols.AttemptStatus.SUCCEEDED
    assert result.status is protocols.ResultStatus.UNKNOWN and not result.is_theorem_proof
    assert result.payload["result_status"] == "satisfied"
    assert result.payload["result_authority"] == "model_check"
    assert result.request_digest == attempt.request_digest == req.digest
    assert [p for p, _, _ in calls] == ["model", "version"]
    if provider == "apalache":
        assert "--length=3" in calls[0][1].argv


@pytest.mark.parametrize("provider", ["tlc", "apalache"])
def test_v2_mapping_and_typed_artifact_have_identical_bindings_and_losses(backend_factory, provider):
    original = artifact()
    selected, _ = backend_factory(provider)
    engine = v2.StateExecutionEngineV2(**{provider: selected})
    params = dict(request_id="request:v2:payload", provider=provider, bounds=request({}).bounds)
    typed = engine.execute(v2.StateExecutionRequestV2(artifacts=original, **params))
    encoded = engine.execute(v2.StateExecutionRequestV2(artifacts=original.to_dict(), **params))
    assert typed.to_dict() == encoded.to_dict()
    assert encoded.outcome.artifacts.losses == original.losses
    assert encoded.evidence.module.source_map_size == len(original.source_map)
    assert encoded.evidence.module.artifact_digest == original.artifact_digest
    assert dict(encoded.evidence.bounds.compile_bounds) == original.bounds.to_dict()
    assert encoded.evidence.bounds.max_steps == original.bounds.max_steps
    assert encoded.evidence.model_check_established and not encoded.evidence.is_theorem_authority


@pytest.mark.parametrize("include_digest", [False, True])
def test_canonical_reader_roundtrips_full_wire_including_optional_outer_digest(include_digest):
    original = artifact()
    payload = json.loads(json.dumps(original.to_dict(include_digest=include_digest), ensure_ascii=False))
    decoded = compiler.GeneratedTLAArtifacts.from_dict(payload)
    assert decoded == original
    assert decoded.to_dict() == original.to_dict()
    assert decoded.artifact_digest == original.artifact_digest


def test_real_compiler_output_passes_canonical_reader_and_execution(backend_factory):
    from ipfs_datasets_py.logic.software_verification.state import (
        Boundedness, FiniteDomainBound, PredicateRole, StatePredicate, StateSchema,
        StateTypeKind, StateVariable,
    )
    from ipfs_datasets_py.logic.software_verification.transitions import (
        StateTransitionIR, TransitionKind, TransitionRelation,
    )
    document = StateTransitionIR(
        schema=StateSchema(variables=(StateVariable("var:n", "n", StateTypeKind.INTEGER,
            Boundedness.FINITE, domain_bound=FiniteDomainBound("bound:n", lower=0, upper=3)),)),
        predicates=(StatePredicate("pred:init", PredicateRole.INITIAL, "n = 0", expression={"var:n": 0}),
            StatePredicate("pred:safety", PredicateRole.INVARIANT, "n >= 0", expression={"role": "invariant"})),
        actions=(), transitions=(TransitionRelation("rel:stutter", TransitionKind.STUTTER,
            "The finite counter may stutter.", allows_stutter=True),),
    )
    generated = compiler.TLACompiler(bounds=artifact().bounds).compile(document, module_name="PayloadCounter")
    assert generated.source_map and generated.losses
    payload = json.loads(json.dumps(generated.to_dict()))
    decoded = compiler.GeneratedTLAArtifacts.from_dict(payload)
    assert decoded.to_dict() == generated.to_dict()
    backend, calls = backend_factory()
    outcome = backend.run(request({"artifacts": payload}))
    assert outcome.artifacts == generated
    assert outcome.receipt.artifact_digest == generated.artifact_digest
    assert [phase for phase, _, _ in calls] == ["model", "version"]


@pytest.mark.parametrize("field", ["source_map", "losses", "safety_properties", "liveness_properties", "fairness_limitations"])
def test_explicit_empty_collections_are_preserved_not_replaced_by_defaults(field):
    original = replace(artifact(), **{field: ()})
    decoded = compiler.GeneratedTLAArtifacts.from_dict(original.to_dict())
    assert getattr(decoded, field) == ()
    assert decoded.to_dict() == original.to_dict()


def test_reader_detaches_mutable_payload_and_preserves_nested_order():
    original = artifact()
    payload = original.to_dict()
    payload["source_map"].reverse()
    payload.pop("artifact_digest")
    decoded = compiler.GeneratedTLAArtifacts.from_dict(payload)
    assert decoded.source_map == tuple(reversed(original.source_map))
    recorded = decoded.to_dict()
    payload["source_map"][0]["source_id"] = "mutated:source"
    payload["losses"][0]["statement"] = "mutated disclosure"
    payload["bounds"]["max_steps"] = 999
    assert decoded.to_dict() == recorded


def test_frozen_protocol_payload_is_a_supported_canonical_representation():
    original = artifact()
    frozen = request({"artifacts": original.to_dict()}).payload["artifacts"]
    assert compiler.GeneratedTLAArtifacts.from_dict(frozen).to_dict() == original.to_dict()


@pytest.mark.parametrize("field", ["model_digest", "tlc_config_digest", "apalache_config_digest", "artifact_digest"])
def test_supplied_digests_are_verified_instead_of_trusted(backend_factory, field):
    payload = artifact().to_dict()
    payload[field] = "0" * 64
    backend, calls = backend_factory()
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(payload)
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": payload}))
    assert calls == []


def set_path(value, path, replacement):
    cursor = value
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = replacement


INVALID_FIELDS = [
    (("schema_version",), "tla-generated-artifact/v999"),
    (("interface_version",), "TLABackend@999"),
    (("translator", "id"), "other-translator"),
    (("translator", "version"), "tla-compiler/v999"),
    (("bounded",), False), (("bounded",), 1),
    (("unbounded_proof",), True), (("unbounded_proof",), 0),
    (("bounds", "schema_version"), "tla-compile-bounds/v999"),
    (("bounds", "max_steps"), True), (("bounds", "max_steps"), "3"),
    (("bounds", "max_steps"), 3.0), (("bounds", "max_steps"), 0),
    (("bounds", "default_integer_lower"), False),
    (("source_map", 0, "schema_version"), "tla-source-map/v999"),
    (("source_map", 0, "source_id"), 17),
    (("source_map", 0, "tla_symbol"), "not a symbol"),
    (("source_map", 0), "not a mapping"),
    (("losses", 0, "schema_version"), "tla-projection-loss/v999"),
    (("losses", 0, "projection"), "unknown-projection"),
    (("losses", 0, "severity"), "unknown-severity"),
    (("losses", 0, "handling"), "unknown-handling"),
    (("losses", 0, "preservation"), "unknown-preservation"),
    (("losses", 0, "approximation"), "unknown-direction"),
    (("losses", 0, "statement"), 23),
    (("losses", 0), None),
    (("safety_properties",), "Safety"),
    (("liveness_properties",), "Progress"),
    (("fairness_limitations",), "not a sequence"),
    (("model_text",), 3), (("tlc_config_text",), None),
]


@pytest.mark.parametrize(("path", "replacement"), INVALID_FIELDS)
def test_invalid_canonical_metadata_is_rejected_before_raw_checker(backend_factory, path, replacement):
    payload = artifact().to_dict(include_digest=False)
    set_path(payload, path, replacement)
    backend, calls = backend_factory()
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(payload)
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": payload}))
    assert calls == []


@pytest.mark.parametrize("field", ["bounds", "source_map", "losses", "translator", "model_text", "model_digest"])
def test_incomplete_canonical_payload_does_not_fall_back_to_raw_defaults(backend_factory, field):
    payload = artifact().to_dict()
    payload.pop(field)
    backend, calls = backend_factory()
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": payload}))
    assert calls == []


def test_text_free_receipt_summary_is_not_an_executable_artifact(backend_factory):
    summary = artifact().to_dict(include_text=False)
    backend, calls = backend_factory()
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(summary)
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": summary}))
    assert calls == []


@pytest.mark.parametrize("location", [(), ("bounds",), ("source_map", 0), ("losses", 0), ("translator",)])
def test_unknown_fields_cannot_hide_unparsed_artifact_semantics(location):
    payload = artifact().to_dict(include_digest=False)
    target = payload
    for part in location:
        target = target[part]
    target["unreviewed_semantics"] = "must not be ignored"
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(payload)


@pytest.mark.parametrize(("path", "value"), [
    (("source_document_id",), " source:payload-counter "),
    (("source_kind",), " concurrency "),
    (("safety_properties", 0), " Safety "),
    (("source_map", 0, "source_id"), " source:variable:n "),
    (("source_map", 0, "line_hint"), " VARIABLE n "),
    (("losses", 0, "statement"), " padded disclosure "),
    (("losses", 0, "preservation"), "lossless"),
    (("fairness_limitations", 0), " padded limitation "),
])
def test_canonical_metadata_is_rejected_when_construction_would_rewrite_it(path, value):
    payload = artifact().to_dict(include_digest=False)
    set_path(payload, path, value)
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(payload)


@pytest.mark.parametrize("field", ["model_text", "tlc_config_text", "apalache_config_text"])
def test_canonical_text_is_not_silently_repaired(field):
    payload = artifact().to_dict(include_digest=False)
    payload[field] = payload[field].rstrip("\n")
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(payload)


@pytest.mark.parametrize("value", ["invalid\x00text\n", "invalid\ud800text\n"])
def test_canonical_model_text_must_be_nul_free_utf8(value):
    payload = artifact().to_dict(include_digest=False)
    payload["model_text"] = value
    with pytest.raises(compiler.TLACompilerError):
        compiler.GeneratedTLAArtifacts.from_dict(payload)


def test_declared_module_byte_limit_counts_utf8_bytes(backend_factory):
    payload = artifact().to_dict(include_digest=False)
    payload["bounds"]["max_module_bytes"] = len(payload["model_text"])
    assert len(payload["model_text"].encode("utf-8")) > payload["bounds"]["max_module_bytes"]
    backend, calls = backend_factory()
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": payload}))
    assert calls == []


@pytest.mark.parametrize("route", ["raw", "registry", "v2"])
def test_tampered_loss_disclosure_never_reaches_checker(backend_factory, monkeypatch, route):
    payload = artifact().to_dict()
    payload["losses"] = []  # Leave the compiler's artifact digest intact.
    backend, calls = backend_factory()
    checked = []
    monkeypatch.setattr(backend, "check", lambda *a, **k: checked.append(a) or pytest.fail("tampered artifact reached checker"))
    if route == "raw":
        with pytest.raises(runners.TLARunnerError):
            backend.run(request({"artifacts": payload}))
    elif route == "registry":
        entry = next(e for e in registry.EXECUTABLE_PROVIDER_MATRIX if e.provider_id == "tla_tlc")
        wrapper = registry.LazyMatrixProofBackend(entry, factory=lambda: backend)
        req = replace(request({"artifacts": payload}), requested_backend_id="")
        attempt, result = registry.ProofBackendRegistry((wrapper,)).run(req, backend_id="tla_tlc")
        assert attempt.status is protocols.AttemptStatus.FAILED
        assert result.status is protocols.ResultStatus.ERROR and not result.is_theorem_proof
    else:
        result = v2.StateExecutionEngineV2(tlc=backend).execute(v2.StateExecutionRequestV2(
            request_id="request:bad-losses", provider="tlc", artifacts=payload, bounds=request({}).bounds))
        assert result.disposition is v2.StateDisposition.MALFORMED
        assert not result.evidence.model_check_established and not result.evidence.is_theorem_authority
    assert checked == calls == []


@pytest.mark.parametrize("provider", ["tlc", "apalache"])
def test_legacy_minimal_raw_payload_retains_documented_defaults(backend_factory, provider):
    backend, calls = backend_factory(provider)
    payload = {"module_name": "PayloadCounter", "model_text": artifact().model_text.rstrip("\n")}
    outcome = backend.run(request({"artifacts": payload}, provider=provider))
    assert outcome.artifacts.model_text == artifact().model_text
    assert outcome.artifacts.bounds == backend._compiler.bounds
    assert outcome.artifacts.source_map == outcome.artifacts.losses == ()
    assert outcome.artifacts.safety_properties == ("Safety",)
    assert outcome.artifacts.bounded and not outcome.artifacts.unbounded_proof
    assert [phase for phase, _, _ in calls] == ["model", "version"]


def test_legacy_explicit_empty_properties_are_not_invented(backend_factory):
    backend, _ = backend_factory()
    payload = {"module_name": "PayloadCounter", "model_text": artifact().model_text,
               "safety_properties": [], "liveness_properties": [], "fairness_limitations": []}
    decoded = backend._artifacts_from_payload({"artifacts": payload})
    assert decoded.safety_properties == decoded.liveness_properties == decoded.fairness_limitations == ()


@pytest.mark.parametrize(("field", "value"), [
    ("model_text", 17), ("module_name", 17), ("tlc_config_text", ""),
    ("safety_properties", "Safety"), ("source_document_id", False),
])
def test_legacy_values_are_not_silently_coerced_or_defaulted(backend_factory, field, value):
    payload = {"model_text": artifact().model_text, field: value}
    backend, calls = backend_factory()
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": payload}))
    assert calls == []


@pytest.mark.parametrize("marker", ["schema_version", "bounds", "source_map", "losses", "bounded", "artifact_digest"])
def test_partial_canonical_declaration_cannot_downgrade_into_legacy_form(backend_factory, marker):
    payload = {"model_text": artifact().model_text, marker: artifact().to_dict()[marker]}
    backend, calls = backend_factory()
    with pytest.raises(runners.TLARunnerError):
        backend.run(request({"artifacts": payload}))
    assert calls == []


@pytest.mark.parametrize("bad", [None, "serialized text", [], 1])
def test_nonmapping_nested_artifact_is_not_replaced_by_top_level_model(backend_factory, bad):
    backend, calls = backend_factory()
    payload = {"artifacts": bad, "model_text": artifact().model_text}
    with pytest.raises(runners.TLARunnerError):
        backend.run(request(payload))
    assert calls == []

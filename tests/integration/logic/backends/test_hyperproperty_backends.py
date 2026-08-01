"""Integration contract for HyperLTL, AutoHyper, and MCHyper backends (LFV-G048).

Covers:

* separate discovery/capabilities per engine;
* quantifier order and observation maps surviving translation;
* counterexample multi-trace tuples with observation-map replay;
* explicit non-authoritative fallback bounds;
* absent tools and unsupported alternation returning non-success.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.hyperproperties.adapters import (
    AUTOHYPER_BACKEND_VERSION,
    AUTOHYPER_CAPABILITY,
    HYPERLTL_BACKEND_VERSION,
    HYPERLTL_CAPABILITY,
    MCHYPER_BACKEND_VERSION,
    MCHYPER_CAPABILITY,
    AutoHyperBackend,
    FallbackBoundDisclosure,
    HyperCheckOutcomeStatus,
    HyperEngine,
    HyperEvidencePath,
    HyperLTLBackend,
    HyperpropertyAdapterError,
    MCHyperBackend,
    ObservationMap,
    QuantifierOrder,
    parse_hyper_counterexample,
    probe_hyperproperty_backends,
    quantifier_alternation_count,
    render_hyperltl_formula,
    replay_hyper_counterexample,
)
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    ExecutionTrace,
    HyperpropertyFormula,
    HyperpropertyIR,
    HyperpropertyKind,
    InformationFlowPolicy,
    ObservationKind,
    ObservationSpec,
    QuantifierBinding,
    SecurityLabel,
    SecurityLevel,
    SelfCompositionBound,
    TraceQuantifier,
    TraceVariable,
)


def _policy(
    *,
    observations: tuple[str, ...] = ("status", "public_token"),
) -> InformationFlowPolicy:
    labels = (
        SecurityLabel("label:user", "user_id", SecurityLevel.LOW, ObservationKind.INPUT),
        SecurityLabel(
            "label:secret", "secret", SecurityLevel.HIGH, ObservationKind.INPUT
        ),
        SecurityLabel(
            "label:status", "status", SecurityLevel.LOW, ObservationKind.OUTPUT
        ),
        SecurityLabel(
            "label:token",
            "public_token",
            SecurityLevel.LOW,
            ObservationKind.OUTPUT,
        ),
    )
    observation_specs = tuple(
        ObservationSpec(
            f"obs:{field}",
            field,
            ObservationKind.OUTPUT,
            SecurityLevel.LOW,
        )
        for field in observations
    )
    return InformationFlowPolicy(
        policy_id="policy:ni-v1",
        low_input_fields=("user_id",),
        high_input_fields=("secret",),
        observation_fields=observations,
        labels=labels,
        observations=observation_specs,
        subject_fields=("task_id",),
        description="Two-trace noninterference policy",
    )


def _bound(
    *,
    max_traces: int = 8,
    max_pairs: int = 16,
) -> SelfCompositionBound:
    return SelfCompositionBound(
        "bound:finite",
        max_traces=max_traces,
        max_pairs=max_pairs,
        max_steps=64,
        description="Finite self-composition envelope",
    )


def _document(
    *,
    max_traces: int = 8,
    max_pairs: int = 16,
) -> HyperpropertyIR:
    return HyperpropertyIR.noninterference_document(
        policy=_policy(),
        bound=_bound(max_traces=max_traces, max_pairs=max_pairs),
        metadata={"subject": "information-flow"},
    )


def _alternating_document(
    *,
    signature: tuple[TraceQuantifier, ...],
) -> HyperpropertyIR:
    """Build a general multi-trace formula with the requested quantifier prefix."""

    variables = tuple(
        TraceVariable(f"var:pi{index + 1}", f"pi{index + 1}")
        for index in range(len(signature))
    )
    prefix = tuple(
        QuantifierBinding(
            f"bind:{index}",
            quantifier,
            variables[index].variable_id,
            index,
        )
        for index, quantifier in enumerate(signature)
    )
    formula = HyperpropertyFormula(
        formula_id="formula:alternating",
        kind=HyperpropertyKind.GENERAL,
        variables=variables,
        quantifier_prefix=prefix,
        matrix_statement=" ".join(
            f"{item.quantifier.value} {variables[index].name}."
            for index, item in enumerate(prefix)
        )
        + " true",
    )
    return HyperpropertyIR(
        formula=formula,
        information_flow_policy=_policy(),
        self_composition_bound=_bound(),
    )


def _trace(
    trace_id: str,
    *,
    user_id: str = "alice",
    secret: str = "s1",
    status: str = "ok",
    public_token: str = "tok",
    task_id: str = "task:1",
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        public_inputs={"user_id": user_id},
        private_inputs={"secret": secret},
        observations={"status": status, "public_token": public_token},
        subject={"task_id": task_id},
    )


def _request(
    document: HyperpropertyIR,
    *,
    backend_id: str = "hyperltl",
    allow_fallback: bool = False,
    traces: list[ExecutionTrace] | None = None,
) -> BackendRequest:
    payload: dict = {
        "document": document.to_dict(),
        "allow_fallback": allow_fallback,
    }
    if traces is not None:
        payload["traces"] = [
            {
                "trace_id": item.trace_id,
                "public_inputs": dict(item.public_inputs),
                "private_inputs": dict(item.private_inputs),
                "observations": dict(item.observations),
                "subject": dict(item.subject),
            }
            for item in traces
        ]
    return BackendRequest(
        request_id="request:hyper:test",
        claim_id="claim:hyper:test",
        declaration_id="declaration:hyper:test",
        claim_digest="1" * 64,
        obligation_id="obligation:hyper:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed",),
        logic_family="hyperproperty",
        query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(timeout_ms=250, max_steps=20),
        payload=FrozenMap(payload),
        requested_backend_id=backend_id,
    )


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    output_truncated: bool = False,
) -> BoundedToolRunner:
    def execute(invocation, _cancellation):
        del invocation
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            elapsed_seconds=0.012,
            timed_out=timed_out,
            output_truncated=output_truncated,
            process_tree_terminated=timed_out,
            error="executable not found" if unavailable else "",
        )

    return BoundedToolRunner(executor=execute)


def _vendor_identity(
    tmp_path: Path,
    engine: HyperEngine,
    *,
    environment: dict[str, str] | None = None,
) -> dict:
    executable = tmp_path / engine.value
    executable.write_bytes(f"{engine.value} reviewed executable\n".encode())
    executable.chmod(0o755)
    return {
        "artifact_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "authority_ceiling": "bounded",
        "authorizes_universal_proof": False,
        "executable": str(executable),
        "executable_kind": (
            "upstream_python_entrypoint"
            if engine is HyperEngine.MCHYPER
            else "upstream_compiled_binary"
        ),
        "is_hermetic_engine": False,
        "is_upstream_build": True,
        "is_vendor_build": True,
        "runtime_environment": environment or {},
        "tool_id": engine.value,
        "version": "reviewed-native-test",
    }


# ---------------------------------------------------------------------------
# Separate discovery / capabilities
# ---------------------------------------------------------------------------


def test_each_engine_has_distinct_capability_surface():
    hyper = HyperLTLBackend()
    auto = AutoHyperBackend()
    mc = MCHyperBackend()

    assert hyper.backend_version == HYPERLTL_BACKEND_VERSION == "HyperLTLBackend@1"
    assert auto.backend_version == AUTOHYPER_BACKEND_VERSION == "AutoHyperBackend@1"
    assert mc.backend_version == MCHYPER_BACKEND_VERSION == "MCHyperBackend@1"

    assert hyper.engine is HyperEngine.HYPERLTL
    assert auto.engine is HyperEngine.AUTOHYPER
    assert mc.engine is HyperEngine.MCHYPER

    assert hyper.engine_capability() == HYPERLTL_CAPABILITY
    assert auto.engine_capability() == AUTOHYPER_CAPABILITY
    assert mc.engine_capability() == MCHYPER_CAPABILITY

    assert hyper.capabilities().supports("hyperproperty", QueryKind.SATISFIABILITY)
    assert auto.capabilities().supports("autohyper", QueryKind.SATISFIABILITY)
    assert mc.capabilities().supports("mchyper", QueryKind.SATISFIABILITY)

    # Capability declarations are not interchangeable.
    assert set(hyper.engine_capability().executable_candidates) != set(
        auto.engine_capability().executable_candidates
    )
    assert (
        hyper.engine_capability().max_quantifier_alternations
        != auto.engine_capability().max_quantifier_alternations
        or hyper.engine_capability().supports_forall_exists
        != auto.engine_capability().supports_forall_exists
    )
    assert auto.engine_capability().supports_forall_exists is False
    assert mc.engine_capability().supports_exists_forall is False


def test_probe_discovers_engines_independently_without_implying_proof():
    available = HyperLTLBackend(
        which=lambda name: "/usr/bin/hyperltl" if name == "hyperltl" else None
    )
    missing = AutoHyperBackend(which=lambda _name: None)
    probes = probe_hyperproperty_backends((available, missing))
    assert probes[0].available is True
    assert probes[0].executable_path == "/usr/bin/hyperltl"
    assert probes[1].available is False
    assert "unavailable" in probes[1].reason
    # Discovery alone never yields a satisfied hyperproperty result.
    outcome = missing.check(_document())
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.external_tool_proof is False


# ---------------------------------------------------------------------------
# Translation preserves quantifier order and observation maps
# ---------------------------------------------------------------------------


def test_quantifier_order_and_observation_maps_survive_translation():
    document = _document()
    for backend in (HyperLTLBackend(), AutoHyperBackend(), MCHyperBackend()):
        translation = backend.translate(document)
        assert translation.quantifier_order.signature == ("forall", "forall")
        assert translation.quantifier_order.variable_names == ("pi1", "pi2")
        assert translation.quantifier_order.matches_document(document)

        obs = translation.observation_map
        assert obs.policy_id == "policy:ni-v1"
        assert obs.low_input_fields == ("user_id",)
        assert obs.high_input_fields == ("secret",)
        assert obs.observation_fields == ("status", "public_token")
        assert obs.observation_kinds["status"] == "output"

        # Round-trip through JSON packages written for the tool workspace.
        restored_order = QuantifierOrder.from_dict(
            json.loads(translation.auxiliary_files["quantifier_order.json"])
        )
        restored_obs = ObservationMap.from_dict(
            json.loads(translation.auxiliary_files["observation_map.json"])
        )
        assert restored_order.to_dict() == translation.quantifier_order.to_dict()
        assert restored_obs.to_dict() == translation.observation_map.to_dict()

        formula_text = translation.formula_text
        if backend.engine is HyperEngine.MCHYPER:
            assert formula_text.startswith("Forall (Forall (")
            assert 'AP "user_id" 0' in formula_text
            assert 'AP "user_id" 1' in formula_text
        else:
            assert "forall pi1." in formula_text
            assert "forall pi2." in formula_text
            # Order must not be swapped.
            assert formula_text.index("forall pi1.") < formula_text.index(
                "forall pi2."
            )
        assert "status" in formula_text
        assert "public_token" in formula_text
        assert "secret" not in formula_text  # high fields stay out of the formula text map


def test_render_preserves_alternating_quantifier_order():
    document = _alternating_document(
        signature=(TraceQuantifier.FORALL, TraceQuantifier.EXISTS, TraceQuantifier.FORALL)
    )
    text = render_hyperltl_formula(document, engine=HyperEngine.HYPERLTL)
    assert text.index("forall pi1.") < text.index("exists pi2.")
    assert text.index("exists pi2.") < text.index("forall pi3.")
    assert quantifier_alternation_count(document.formula.quantifier_prefix) == 2
    order = QuantifierOrder.from_document(document)
    assert order.signature == ("forall", "exists", "forall")
    assert order.matches_document(document)


# ---------------------------------------------------------------------------
# Engine execution, counterexamples, and replay
# ---------------------------------------------------------------------------


def test_engine_success_is_hyperproperty_authority_not_theorem():
    document = _document()
    backend = HyperLTLBackend(
        runner=_process_runner("property holds\nverified\n"),
        which=lambda name: "/bin/hyperltl" if name == "hyperltl" else None,
        executable="/bin/hyperltl",
    )
    outcome = backend.check(document)
    assert outcome.receipt.status is HyperCheckOutcomeStatus.SATISFIED
    assert outcome.receipt.evidence_path is HyperEvidencePath.ENGINE
    assert outcome.receipt.external_tool_proof is True
    assert outcome.receipt.authorizes_universal_proof is False
    assert outcome.result.authority is ResultAuthority.HYPERPROPERTY
    assert outcome.result.status is ResultStatus.SATISFIED
    assert outcome.result.translation_ceiling is EvidenceAuthority.BOUNDED
    assert outcome.result.metadata["external_tool_proof"] is True


def test_counterexample_trace_tuples_parse_and_replay():
    document = _document()
    translation = HyperLTLBackend().translate(document)
    raw = """\
counterexample
TRACE pi1:
  public.user_id = alice
  obs.status = ok
  obs.public_token = tok
TRACE pi2:
  public.user_id = alice
  obs.status = leak
  obs.public_token = tok
DIFF field=status left=ok right=leak
"""
    parsed = parse_hyper_counterexample(
        raw,
        formula_id=document.formula.formula_id,
        observation_map=translation.observation_map,
        quantifier_order=translation.quantifier_order,
    )
    assert parsed is not None
    assert len(parsed.traces) == 2
    assert parsed.traces[0].variable_id == "var:pi1"
    assert parsed.traces[1].variable_id == "var:pi2"
    assert parsed.differences[0].field == "status"
    # High/private inputs must not appear on the witness.
    assert "secret" not in parsed.traces[0].to_dict()
    assert "private_inputs" not in parsed.traces[0].to_dict()

    replayed = replay_hyper_counterexample(
        parsed, translation.observation_map, translation.quantifier_order
    )
    assert replayed.replayed is True
    assert any("replayed observations" in note for note in replayed.replay_notes)
    assert any("status" in note for note in replayed.replay_notes)
    bundle = replayed.to_witness_bundle()
    assert bundle.authorizes_universal_proof is False
    assert len(bundle.traces) == 2


def test_engine_violation_attaches_replayed_witness_bundle():
    counterexample = """\
violated
TRACE pi1:
  public.user_id = alice
  obs.status = ok
TRACE pi2:
  public.user_id = alice
  obs.status = leak
DIFF field=status left=ok right=leak
"""
    document = _document()
    backend = HyperLTLBackend(
        runner=_process_runner(counterexample, returncode=1),
        executable="/bin/hyperltl",
    )
    outcome = backend.check(document)
    assert outcome.result.status is ResultStatus.VIOLATED
    assert outcome.receipt.counterexample is not None
    assert outcome.receipt.counterexample.replayed is True
    witness = outcome.result.witness.to_dict()
    assert "witness_bundle" in witness
    assert witness["witness_bundle"]["role"] == "counterexample"
    assert len(witness["counterexample"]["traces"]) == 2


def test_autohyper_uses_explicit_system_auxiliary_and_argv():
    document = _document()
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        return RawProcessResult(
            returncode=0,
            stdout="sat\n",
            elapsed_seconds=0.01,
        )

    backend = AutoHyperBackend(
        runner=BoundedToolRunner(executor=execute),
        executable="/bin/AutoHyper",
    )
    outcome = backend.check(document)
    assert outcome.result.status is ResultStatus.SATISFIED
    assert invocations, "expected engine invocation"
    argv = invocations[0].argv
    assert argv[0] == "/bin/AutoHyper"
    assert "--explicit" in argv
    assert "system.explicit" in argv
    translation = outcome.translation
    assert translation is not None
    assert "system.explicit" in translation.auxiliary_files
    assert "Variables:" in translation.auxiliary_files["system.explicit"]
    explicit = translation.auxiliary_files["system.explicit"]
    assert '("user_id" Bool)' in explicit
    assert '("status" Bool)' in explicit
    assert '("public_token" Bool)' in explicit


@pytest.mark.parametrize(
    ("backend_type", "engine", "environment", "expected_tail"),
    [
        (
            HyperLTLBackend,
            HyperEngine.HYPERLTL,
            {"EAHYPER_SOLVER_DIR": "/opt/reviewed/eahyper-solvers"},
            ("-f", "property.hltl"),
        ),
        (
            AutoHyperBackend,
            HyperEngine.AUTOHYPER,
            {"DOTNET_ROOT": "/opt/reviewed/dotnet"},
            ("--explicit", "system.explicit", "property.hltl"),
        ),
    ],
)
def test_vendor_identity_runtime_environment_and_native_cli_are_consumed(
    tmp_path: Path,
    backend_type,
    engine: HyperEngine,
    environment: dict[str, str],
    expected_tail: tuple[str, ...],
) -> None:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        assert dict(invocation.environment) | environment == dict(
            invocation.environment
        )
        assert invocation.limits.enforce_file_size_limit is (
            engine is not HyperEngine.AUTOHYPER
        )
        assert (invocation.cwd / "property.hltl").is_file()
        return RawProcessResult(
            returncode=0,
            stdout="SAT\n",
            elapsed_seconds=0.01,
        )

    identity = _vendor_identity(
        tmp_path, engine, environment=environment
    )
    backend = backend_type(
        runner=BoundedToolRunner(executor=execute),
        engine_identity=identity,
    )

    outcome = backend.check(_document())

    assert outcome.result.status is ResultStatus.SATISFIED
    assert len(invocations) == 1  # Identity version avoids an invalid CLI probe.
    assert invocations[0].argv[1:] == expected_tail
    assert outcome.receipt.tool_version == "reviewed-native-test"
    if engine is HyperEngine.AUTOHYPER:
        assert any(
            "RLIMIT_FSIZE" in item
            for item in outcome.receipt.capability.limitations
        )


def test_vendor_identity_is_rehashed_before_adapter_consumption(
    tmp_path: Path,
) -> None:
    identity = _vendor_identity(tmp_path, HyperEngine.HYPERLTL)
    Path(identity["executable"]).write_bytes(b"tampered")

    with pytest.raises(
        HyperpropertyAdapterError,
        match="digest does not match",
    ):
        HyperLTLBackend(engine_identity=identity)


def test_native_formula_renderers_emit_upstream_parser_syntax():
    document = _document()

    eahyper = render_hyperltl_formula(
        document, engine=HyperEngine.HYPERLTL
    )
    assert not eahyper.startswith(";")
    assert "(user_id_pi1 <-> user_id_pi2)" in eahyper
    assert "(status_pi1 <-> status_pi2)" in eahyper

    autohyper = render_hyperltl_formula(
        document, engine=HyperEngine.AUTOHYPER
    )
    assert '{"user_id"_pi1 = "user_id"_pi2}' in autohyper
    assert '{"public_token"_pi1 = "public_token"_pi2}' in autohyper

    mchyper = render_hyperltl_formula(
        document, engine=HyperEngine.MCHYPER
    )
    assert mchyper.startswith("Forall (Forall (G (Implies ")
    assert 'Eq (AP "status" 0) (AP "status" 1)' in mchyper
    assert all(
        token not in mchyper
        for token in (";", "`", "$(", "\n", "\\")
    )


def test_mchyper_requires_aiger_and_uses_native_cli_contract():
    document = _document()
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        assert invocation.limits.enforce_file_size_limit is True
        assert (invocation.cwd / "system.aag").read_text(
            encoding="utf-8"
        ) == "aag 0 0 0 0 0\n"
        return RawProcessResult(
            returncode=0,
            stdout="Property proved. Time = 0.01 sec\n",
            elapsed_seconds=0.01,
        )

    backend = MCHyperBackend(
        runner=BoundedToolRunner(executor=execute),
        executable="/bin/mchyper",
    )
    missing = backend.check(document)
    assert missing.result.status is ResultStatus.UNSUPPORTED
    assert "requires an explicit AIGER" in missing.receipt.reason
    assert not invocations

    outcome = backend.check(
        document, system_model="aag 0 0 0 0 0\n"
    )

    assert outcome.result.status is ResultStatus.SATISFIED
    check_invocation = invocations[0]
    assert check_invocation.argv[0] == "/bin/mchyper"
    assert check_invocation.argv[1] == "-f"
    assert check_invocation.argv[2] == outcome.translation.formula_text
    assert check_invocation.argv[3:] == (
        "system.aag",
        "-pdr",
        "-cex",
        "--cex_file",
        "counterexample.txt",
        "-v",
        "1",
    )


# ---------------------------------------------------------------------------
# Absent tools and unsupported alternation → non-success
# ---------------------------------------------------------------------------


def test_absent_tool_returns_unavailable_without_fallback():
    document = _document()
    backend = MCHyperBackend(which=lambda _name: None)
    outcome = backend.check(document, allow_fallback=False)
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.status is HyperCheckOutcomeStatus.UNAVAILABLE
    assert outcome.receipt.evidence_path is HyperEvidencePath.NONE
    assert outcome.receipt.external_tool_proof is False
    assert "unavailable" in outcome.receipt.reason


def test_unsupported_alternation_returns_non_success():
    # AutoHyper rejects forall-exists prefixes.
    document = _alternating_document(
        signature=(TraceQuantifier.FORALL, TraceQuantifier.EXISTS)
    )
    backend = AutoHyperBackend(
        which=lambda name: "/bin/autohyper" if "auto" in name.lower() else None,
        executable="/bin/autohyper",
    )
    outcome = backend.check(document)
    assert outcome.result.status is ResultStatus.UNSUPPORTED
    assert outcome.receipt.status is HyperCheckOutcomeStatus.UNSUPPORTED
    assert "forall-exists" in outcome.receipt.reason

    # MCHyper rejects exists-forall prefixes.
    document_ef = _alternating_document(
        signature=(TraceQuantifier.EXISTS, TraceQuantifier.FORALL)
    )
    mc = MCHyperBackend(executable="/bin/mchyper")
    outcome_ef = mc.check(document_ef)
    assert outcome_ef.result.status is ResultStatus.UNSUPPORTED
    assert "exists-forall" in outcome_ef.receipt.reason


def test_too_many_alternations_are_unsupported_before_execution():
    # Five alternations exceed HyperLTL's default ceiling of four.
    signature = (
        TraceQuantifier.FORALL,
        TraceQuantifier.EXISTS,
        TraceQuantifier.FORALL,
        TraceQuantifier.EXISTS,
        TraceQuantifier.FORALL,
        TraceQuantifier.EXISTS,
    )
    document = _alternating_document(signature=signature)
    assert quantifier_alternation_count(document.formula.quantifier_prefix) == 5
    backend = HyperLTLBackend(executable="/bin/hyperltl")
    outcome = backend.check(document)
    assert outcome.result.status is ResultStatus.UNSUPPORTED
    assert "alternations" in outcome.receipt.reason
    assert outcome.receipt.command == ()


# ---------------------------------------------------------------------------
# Fallback bounds are explicit and non-authoritative
# ---------------------------------------------------------------------------


def test_fallback_bounds_are_explicit_and_not_external_tool_proof():
    document = _document(max_traces=4, max_pairs=6)
    traces = (
        _trace("t1", secret="s1", status="ok"),
        _trace("t2", secret="s2", status="ok"),
        _trace("t3", secret="s3", status="leak"),  # low-equivalent leak
    )
    backend = HyperLTLBackend(which=lambda _name: None)
    outcome = backend.check(
        document,
        traces=traces,
        allow_fallback=True,
    )
    assert outcome.receipt.evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION
    assert outcome.receipt.external_tool_proof is False
    assert outcome.receipt.authorizes_universal_proof is False
    assert outcome.receipt.fallback_bounds is not None
    assert outcome.receipt.fallback_bounds.max_traces == 4
    assert outcome.receipt.fallback_bounds.max_pairs == 6
    assert outcome.receipt.fallback_bounds.authoritative is False
    assert outcome.receipt.fallback_bounds.external_tool_proof is False
    assert "non-authoritative" in outcome.receipt.reason
    assert "max_traces=4" in outcome.receipt.reason
    assert outcome.result.authority is ResultAuthority.HYPERPROPERTY
    assert outcome.result.witness.to_dict()["external_tool_proof"] is False
    assert outcome.result.witness.to_dict()["fallback_bounds"]["max_pairs"] == 6
    # Violation under fallback remains hyperproperty evidence, not theorem proof.
    assert outcome.result.status is ResultStatus.VIOLATED
    assert outcome.receipt.counterexample is not None
    assert outcome.receipt.counterexample.replayed is True


def test_fallback_clean_sample_is_unknown_not_universal_holds():
    document = _document(max_traces=4, max_pairs=8)
    traces = (
        _trace("t1", secret="s1", status="ok"),
        _trace("t2", secret="s2", status="ok"),
    )
    backend = AutoHyperBackend(which=lambda _name: None)
    outcome = backend.check(document, traces=traces, allow_fallback=True)
    assert outcome.receipt.evidence_path is HyperEvidencePath.BOUNDED_SELF_COMPOSITION
    # Bounded holds stay non-conclusive for universal claims.
    assert outcome.result.status is ResultStatus.UNKNOWN
    assert outcome.receipt.fallback_bounds is not None
    assert "non-authoritative" in outcome.receipt.reason


def test_fallback_without_traces_stays_unavailable():
    document = _document()
    backend = MCHyperBackend(which=lambda _name: None)
    outcome = backend.check(document, allow_fallback=True, traces=None)
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert "no traces" in outcome.receipt.reason


def test_fallback_bound_disclosure_rejects_authority_claims():
    with pytest.raises(HyperpropertyAdapterError, match="cannot claim authority"):
        FallbackBoundDisclosure(
            max_traces=2,
            max_pairs=2,
            max_steps=1,
            bound_id="bound:bad",
            authoritative=True,
        )
    with pytest.raises(HyperpropertyAdapterError, match="external-tool"):
        FallbackBoundDisclosure(
            max_traces=2,
            max_pairs=2,
            max_steps=1,
            bound_id="bound:bad",
            external_tool_proof=True,
        )


# ---------------------------------------------------------------------------
# Request path and timeouts
# ---------------------------------------------------------------------------


def test_run_accepts_backend_request_payload():
    document = _document()
    traces = [
        _trace("t1", secret="a", status="ok"),
        _trace("t2", secret="b", status="leak"),
    ]
    request = _request(
        document,
        backend_id="hyperltl",
        allow_fallback=True,
        traces=traces,
    )
    backend = HyperLTLBackend(which=lambda _name: None)
    outcome = backend.run(request)
    assert outcome.request_digest == request.digest
    assert outcome.result.backend_id == "hyperltl"
    assert outcome.result.status is ResultStatus.VIOLATED


def test_timeout_is_non_success():
    document = _document()
    backend = HyperLTLBackend(
        runner=_process_runner("", returncode=None, timed_out=True),
        executable="/bin/hyperltl",
    )
    outcome = backend.check(document)
    assert outcome.result.status is ResultStatus.TIMEOUT
    assert outcome.receipt.status is HyperCheckOutcomeStatus.TIMEOUT
    assert outcome.receipt.external_tool_proof is False


def test_engine_unsupported_marker_is_non_success():
    document = _document()
    backend = HyperLTLBackend(
        runner=_process_runner("unsupported quantifier alternation\n", returncode=2),
        executable="/bin/hyperltl",
    )
    outcome = backend.check(document)
    assert outcome.result.status is ResultStatus.UNSUPPORTED


def test_probe_is_side_effect_free_path_lookup():
    calls: list[str] = []

    def which(name: str) -> str | None:
        calls.append(name)
        return None

    backend = HyperLTLBackend(which=which)
    probe = backend.probe()
    assert probe.available is False
    assert calls  # discovery looked for candidates
    assert backend.is_available() is False

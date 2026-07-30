"""Integration contract: source → VC → SMT → Z3/CVC5 vertical slice (FVT-010 / FVT-G011).

Acceptance covered here:

* checked-in buggy/fixed programs generate their own VCs and solver witnesses
  (no hand-injected counterexamples);
* Z3 and CVC5 agree, or disagreement is quarantined fail-closed;
* every result binds source spans, program tree, property, assumptions, tools,
  bounds, and translation receipts;
* unsupported constructs fail explicitly rather than being erased.
"""

from __future__ import annotations

import shutil

import pytest

from ipfs_datasets_py.logic.backends.results import ResultStatus
from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
    SmtRawSolverOutput,
)
from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.pipeline import (
    PIPELINE_SCHEMA_VERSION,
    SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE,
    ContractSpec,
    PipelineError,
    PipelineStatus,
    SourceToVerificationPipeline,
    attach_contract_specs,
    lower_vc_obligation_to_smt,
    run_source_to_verification_pipeline,
)
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    VCRuleKind,
    generate_verification_conditions,
)

# ---------------------------------------------------------------------------
# Checked-in buggy / fixed program pair (generate their own witnesses)
# ---------------------------------------------------------------------------

BUGGY_INCR = """\
def incr(x):
    return x
"""

FIXED_INCR = """\
def incr(x):
    return x + 1
"""

INCR_POST = ("result == x + 1",)


def _incr_contracts() -> list[ContractSpec]:
    return [
        ContractSpec(
            function_name="incr",
            postconditions=INCR_POST,
            contract_id="contract:incr-result-is-successor",
        )
    ]


def _bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=10_000,
        max_steps=100_000,
        max_memory_bytes=64 * 1024 * 1024,
        max_output_bytes=65_536,
    )


def _fixed_runner(stdout: str, **kwargs):
    def run(_smtlib: str, _bounds: ExecutionBounds) -> SmtRawSolverOutput:
        return SmtRawSolverOutput(
            stdout=stdout,
            stderr=kwargs.get("stderr", ""),
            returncode=kwargs.get("returncode", 0),
            elapsed_ms=kwargs.get("elapsed_ms", 5),
            solver_version=kwargs.get("solver_version", "mock-solver/1.0"),
            timed_out=kwargs.get("timed_out", False),
            unavailable=kwargs.get("unavailable", False),
        )

    return run


def _pipeline_with_mocks(
    *,
    z3_stdout: str,
    cvc5_stdout: str,
    execute: bool = True,
) -> SourceToVerificationPipeline:
    return SourceToVerificationPipeline(
        z3_backend=Z3SoftwareVerificationBackend(
            runner=_fixed_runner(z3_stdout, solver_version="z3-mock"),
            availability_probe=lambda: True,
            version_probe=lambda: "z3-mock",
        ),
        cvc5_backend=CVC5SoftwareVerificationBackend(
            runner=_fixed_runner(cvc5_stdout, solver_version="cvc5-mock"),
            availability_probe=lambda: True,
            version_probe=lambda: "cvc5-mock",
        ),
        bounds=_bounds(),
        execute_solvers=execute,
    )


# ---------------------------------------------------------------------------
# Interface / composition contracts
# ---------------------------------------------------------------------------


def test_pipeline_exposes_source_to_verification_pipeline_interface() -> None:
    pipeline = SourceToVerificationPipeline(execute_solvers=False)
    assert pipeline.INTERFACE == SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE
    assert pipeline.INTERFACE.endswith("@1")
    payload = pipeline.to_dict()
    assert payload["interface"] == SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE
    assert payload["schema_version"] == PIPELINE_SCHEMA_VERSION


def test_contract_specs_attach_and_vc_generation_is_source_bound() -> None:
    adapted = adapt_source_to_software_verification(FIXED_INCR, path="incr_fixed.py")
    assert adapted.program is not None
    program, contracts = attach_contract_specs(adapted.program, _incr_contracts())
    assert len(contracts) == 1
    vc_set = generate_verification_conditions(program, contracts[0])
    assert vc_set.obligations
    assert vc_set.parent_contract_id == contracts[0].contract_id
    post = vc_set.obligations_by_rule(VCRuleKind.POSTCONDITION_NORMAL)
    assert post
    for obligation in post:
        assert obligation.source_ref_ids or obligation.span_ids
        assert obligation.parent_contract_id == contracts[0].contract_id
        smt_obl, body_names = lower_vc_obligation_to_smt(program, obligation)
        assert smt_obl.goal is not None
        assert body_names  # return equality is part of the body encoding
        assert smt_obl.property_ids


# ---------------------------------------------------------------------------
# Buggy / fixed pair — self-generated VCs and witnesses
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_buggy_program_generates_vc_and_disproving_witness() -> None:
    """Buggy incr returns x; postcondition result == x + 1 is disproved by solvers."""

    result = SourceToVerificationPipeline(bounds=_bounds()).run(
        BUGGY_INCR,
        path="fixtures/incr_buggy.py",
        contracts=_incr_contracts(),
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.program is not None
    assert result.vc_sets
    assert result.obligation_results
    assert result.disproved is True
    assert result.proved is False

    first = result.obligation_results[0]
    assert first.solver_executed is True
    assert first.differential is not None
    assert first.differential.classification is DifferentialClassification.AGREE_DISPROVED
    assert first.differential.agreement is True
    # Witness/model is solver-generated, not injected by the test.
    assert first.differential.left.model_text or first.differential.right.model_text
    assert first.vc_obligation.rule is VCRuleKind.POSTCONDITION_NORMAL
    assert first.body_assumption_names


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_fixed_program_generates_vc_and_is_proved() -> None:
    result = run_source_to_verification_pipeline(
        FIXED_INCR,
        path="fixtures/incr_fixed.py",
        contracts=_incr_contracts(),
        bounds=_bounds(),
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.proved is True
    assert result.disproved is False
    report = result.obligation_results[0].differential
    assert report is not None
    assert report.classification is DifferentialClassification.AGREE_PROVED
    assert report.left.result.status is ResultStatus.PROVED
    assert report.right.result.status is ResultStatus.PROVED
    # Both solvers saw the same canonical script.
    assert report.left.compilation is not None
    assert report.right.compilation is not None
    assert report.left.compilation.script.digest == report.right.compilation.script.digest


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_buggy_and_fixed_pair_are_distinct_outcomes() -> None:
    pipeline = SourceToVerificationPipeline(bounds=_bounds())
    buggy = pipeline.run(BUGGY_INCR, path="pair_buggy.py", contracts=_incr_contracts())
    fixed = pipeline.run(FIXED_INCR, path="pair_fixed.py", contracts=_incr_contracts())
    assert buggy.disproved and not buggy.proved
    assert fixed.proved and not fixed.disproved
    assert buggy.program is not None and fixed.program is not None
    assert buggy.program.program_id != fixed.program.program_id


# ---------------------------------------------------------------------------
# Binding requirements
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_every_result_binds_source_tree_property_assumptions_tool_bounds_translation() -> None:
    result = SourceToVerificationPipeline(bounds=_bounds()).run(
        FIXED_INCR,
        path="bindings_fixed.py",
        contracts=_incr_contracts(),
    )
    assert result.bindings is not None
    bindings = result.bindings
    assert bindings.source.source_ref_ids
    assert bindings.source.span_ids
    assert bindings.source.program_id == result.program.program_id  # type: ignore[union-attr]
    assert bindings.source.path == "bindings_fixed.py"
    assert bindings.source.content_sha256
    assert bindings.property_ids
    assert bindings.assumption_ids  # language assumptions from the adapter
    assert "z3" in bindings.tool_ids
    assert "cvc5" in bindings.tool_ids
    assert any("smt" in tool for tool in bindings.tool_ids)
    assert bindings.bounds["timeout_ms"] == _bounds().timeout_ms
    assert bindings.translation_receipt_ids
    assert bindings.vc_set_ids
    assert bindings.parent_contract_ids == ("contract:incr-result-is-successor",)

    payload = result.to_dict()
    assert payload["bindings"]["source"]["program_id"]
    assert payload["interface"] == SOURCE_TO_VERIFICATION_PIPELINE_INTERFACE

    # Per-obligation binding through SMT attributes and differential report.
    obl = result.obligation_results[0]
    attrs = obl.smt_obligation.attributes.to_dict()
    assert attrs["source_ref_ids"] or attrs["span_ids"]
    assert attrs["parent_contract_id"]
    assert obl.compilation.receipt.receipt_id in bindings.translation_receipt_ids
    assert obl.differential is not None
    assert obl.differential.left.solver_version
    assert obl.differential.right.solver_version


# ---------------------------------------------------------------------------
# Disagreement quarantine (injectable solvers)
# ---------------------------------------------------------------------------


def test_solver_disagreement_is_quarantined() -> None:
    pipeline = _pipeline_with_mocks(
        z3_stdout="unsat\n",
        cvc5_stdout="sat\n(define-fun x () Int 0)\n",
    )
    result = pipeline.run(
        FIXED_INCR,
        path="disagree.py",
        contracts=_incr_contracts(),
    )
    assert result.status is PipelineStatus.DISAGREEMENT_QUARANTINED
    assert result.disagreement_quarantined is True
    report = result.obligation_results[0].differential
    assert report is not None
    assert report.classification is DifferentialClassification.DISAGREE
    assert report.agreement is False
    evidence = report.disagreement_evidence.to_dict()
    assert evidence["preserved"] is True
    assert evidence["left"]["verdict"] == "unsat"
    assert evidence["right"]["verdict"] == "sat"


def test_agreement_on_proved_with_injected_runners() -> None:
    pipeline = _pipeline_with_mocks(
        z3_stdout="unsat\n(body_return_0)\n",
        cvc5_stdout="unsat\n(body_return_0)\n",
    )
    result = pipeline.run(
        FIXED_INCR,
        path="mock_proved.py",
        contracts=_incr_contracts(),
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.proved is True
    assert result.obligation_results[0].differential.classification is (  # type: ignore[union-attr]
        DifferentialClassification.AGREE_PROVED
    )


def test_compile_only_mode_still_emits_vc_and_smt_without_solver_authority() -> None:
    pipeline = SourceToVerificationPipeline(execute_solvers=False, bounds=_bounds())
    result = pipeline.run(
        BUGGY_INCR,
        path="compile_only.py",
        contracts=_incr_contracts(),
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.obligation_results
    assert result.obligation_results[0].solver_executed is False
    assert result.obligation_results[0].differential is None
    assert result.obligation_results[0].compilation.script.digest
    assert result.proved is False  # no solver authority without execution


# ---------------------------------------------------------------------------
# Unsupported constructs fail closed
# ---------------------------------------------------------------------------


def test_unsupported_constructs_fail_explicitly_not_erased() -> None:
    unsupported_source = """\
class Counter:
    def __init__(self):
        self.n = 0
"""
    result = SourceToVerificationPipeline(fail_on_unsupported=True).run(
        unsupported_source,
        path="unsupported_class.py",
        contracts=[
            ContractSpec(function_name="missing", postconditions=("True",)),
        ],
    )
    assert result.status is PipelineStatus.UNSUPPORTED
    assert result.unsupported_constructs
    assert any("class" in item for item in result.unsupported_constructs)
    # Must not silently claim proof success.
    assert result.proved is False
    assert not result.obligation_results


def test_async_and_unknown_language_are_explicit() -> None:
    async_src = """\
async def tick():
    return 1
"""
    result = SourceToVerificationPipeline().run(
        async_src,
        path="async_tick.py",
        contracts=[ContractSpec("tick", postconditions=("result == 1",))],
    )
    assert result.status is PipelineStatus.UNSUPPORTED
    assert result.unsupported_constructs

    rust = SourceToVerificationPipeline().run(
        "fn main() {}",
        path="main.rs",
        language="rust",
        contracts=[ContractSpec("main", postconditions=("True",))],
    )
    assert rust.status is PipelineStatus.UNSUPPORTED
    assert any("language" in item or "rust" in item for item in rust.unsupported_constructs)


def test_missing_contracts_fail_closed() -> None:
    with pytest.raises(PipelineError, match="contracts are required"):
        # run() catches and returns ERROR status for contract resolution;
        # direct attach requires specs.
        SourceToVerificationPipeline(execute_solvers=False)._resolve_contracts(
            adapt_source_to_software_verification(FIXED_INCR, path="x.py").program,  # type: ignore[arg-type]
            None,
        )
    result = SourceToVerificationPipeline(execute_solvers=False).run(
        FIXED_INCR,
        path="no_contract.py",
        contracts=None,
    )
    assert result.status is PipelineStatus.ERROR
    assert any("contract" in item.lower() for item in result.diagnostics)


def test_unknown_name_in_postcondition_is_diagnostic() -> None:
    result = SourceToVerificationPipeline(execute_solvers=False).run(
        FIXED_INCR,
        path="bad_post.py",
        contracts=[
            ContractSpec(
                function_name="incr",
                postconditions=("result == missing_name + 1",),
            )
        ],
    )
    assert result.status is PipelineStatus.ERROR
    assert any("unknown name" in item for item in result.diagnostics)


# ---------------------------------------------------------------------------
# Precondition + postcondition path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_precondition_strengthens_postcondition_proof() -> None:
    """Under x >= 0, identity is a non-negative result."""

    source = """\
def nonneg_id(x):
    return x
"""
    contracts = [
        ContractSpec(
            function_name="nonneg_id",
            preconditions=("x >= 0",),
            postconditions=("result >= 0",),
            contract_id="contract:nonneg-id",
        )
    ]
    result = SourceToVerificationPipeline(bounds=_bounds()).run(
        source,
        path="nonneg_id.py",
        contracts=contracts,
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.proved is True

    # Without the precondition the same postcondition is disproved.
    open_contracts = [
        ContractSpec(
            function_name="nonneg_id",
            postconditions=("result >= 0",),
            contract_id="contract:nonneg-open",
        )
    ]
    open_result = SourceToVerificationPipeline(bounds=_bounds()).run(
        source,
        path="nonneg_open.py",
        contracts=open_contracts,
    )
    assert open_result.disproved is True


# ---------------------------------------------------------------------------
# Module convenience entry point
# ---------------------------------------------------------------------------


def test_module_level_run_helper_matches_class() -> None:
    pipeline = _pipeline_with_mocks(
        z3_stdout="unsat\n",
        cvc5_stdout="unsat\n",
    )
    via_class = pipeline.run(
        FIXED_INCR, path="helper_class.py", contracts=_incr_contracts()
    )
    via_helper = run_source_to_verification_pipeline(
        FIXED_INCR,
        path="helper_fn.py",
        contracts=_incr_contracts(),
        z3_backend=pipeline.z3_backend,
        cvc5_backend=pipeline.cvc5_backend,
        bounds=_bounds(),
    )
    assert via_class.status is PipelineStatus.SUCCESS
    assert via_helper.status is PipelineStatus.SUCCESS
    assert via_class.proved is via_helper.proved is True

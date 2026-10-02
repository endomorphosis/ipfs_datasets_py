"""Source-authored regressions for the explicit integer/boolean proof profile."""

from dataclasses import replace
import hashlib
import shutil

import pytest

from ipfs_datasets_py.logic.software_verification import codebase_pipeline as implementation
from ipfs_datasets_py.logic.software_verification.codebase_pipeline import (
    ContractSpec, PipelineStatus, SOURCE_SEMANTICS_PROFILE,
    SourceToVerificationPipeline, UnsupportedConstructError,
    attach_contract_specs, lower_vc_obligation_to_smt,
)
from ipfs_datasets_py.logic.software_verification.codebase_source_adapters import (
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    VCRuleKind, generate_verification_conditions,
)


@pytest.mark.parametrize("fail_on_unsupported", [True, False])
@pytest.mark.parametrize("source,post", [
    ("def f(x):\n    return x\n", "result == x"),
    ("def f(x: float) -> int:\n    return 1\n", "result == 1"),
    ("def f(x: str) -> str:\n    return x\n", "result == x"),
    ("def f(x: Any) -> int:\n    return 1\n", "result == 1"),
    ("def f(x: Custom) -> int:\n    return 1\n", "result == 1"),
    ("def f(x: list[int]) -> int:\n    return 1\n", "result == 1"),
    ("def f(x: int | None) -> int:\n    return 1\n", "result == 1"),
    ("def f(x: bool) -> int:\n    return x + 1\n", "result == 2"),
    ("def f(x: int) -> bool:\n    return not x\n", "result == False"),
    ("def f(x: int) -> int:\n    return x and 1\n", "result == x"),
    ("def f(x: int) -> int:\n    return x\n", "result == True"),
    ("def f(x: int) -> int:\n    return x\n", "result == (x or 1)"),
    ("def f(x: bool) -> bool:\n    return x\n", "result > False"),
    ("def f(x: int) -> bool:\n    return x\n", "result == True"),
    ("def f(x: bool) -> int:\n    return x\n", "result == 1"),
    ("def f(x: int) -> float:\n    return x\n", "result == x"),
    ("def f(x: int) -> int:\n    y: float = x + 1\n    return y\n", "result == x + 1"),
    ("def f(x: int) -> int:\n    return x / 2\n", "result == x"),
    ("def f(x: int) -> int:\n    return x // -2\n", "result == x"),
    ("def f(x: int) -> int:\n    return x % 0\n", "result == 0"),
    ("def f(x: int) -> int:\n    return x\n", "result == x // 1"),
    ("def f(x: int, y: int) -> int:\n    return x * y\n", "result == x * y"),
    ("def f(x: int) -> int:\n    return x\n", "x"),
    ("def f(x: bool) -> bool:\n    return x\n", "+result"),
    ("def f(x: bool) -> bool:\n    return x\n", "result == +x"),
])
def test_unsupported_types_and_operations_never_reach_solvers(
    monkeypatch, source, post, fail_on_unsupported,
):
    calls = []

    def unexpected_solver(*args, **kwargs):
        calls.append(1)
        raise AssertionError("unsupported source reached a checker")

    monkeypatch.setattr(implementation, "run_z3_cvc5_differential", unexpected_solver)
    result = SourceToVerificationPipeline(fail_on_unsupported=fail_on_unsupported).run(
        source, path="type_boundaries.py", contracts=(ContractSpec("f", postconditions=(post,)),),
    )
    assert result.status is PipelineStatus.UNSUPPORTED
    assert result.unsupported_constructs
    assert not result.proved and not result.disproved
    assert not result.obligation_results
    assert not calls


def test_all_selected_contracts_preflight_before_any_solver(monkeypatch):
    def unexpected_solver(*args, **kwargs):
        raise AssertionError("checker executed before all translations were validated")

    monkeypatch.setattr(implementation, "run_z3_cvc5_differential", unexpected_solver)
    result = SourceToVerificationPipeline().run(
        "def good(x: int) -> int:\n    return x + 1\n\ndef bad(x: float) -> float:\n    return x\n",
        path="preflight.py",
        contracts=(ContractSpec("good", postconditions=("result == x + 1",)),
                   ContractSpec("bad", postconditions=("result == x",))),
    )
    assert result.status is PipelineStatus.UNSUPPORTED
    assert not result.proved and not result.obligation_results


def test_direct_program_ir_cannot_bypass_type_admission():
    adapted = adapt_source_to_software_verification(
        "def f(x: int) -> int:\n    return x\n", path="direct_types.py", preserve_type_annotations=True,
    )
    program, contracts = attach_contract_specs(
        adapted.program, (ContractSpec("f", postconditions=("result == x",)),),
    )
    parameter_id = program.functions[0].parameter_symbol_ids[0]
    program = replace(program, symbols=tuple(
        replace(symbol, type_ref="float") if symbol.symbol_id == parameter_id else symbol
        for symbol in program.symbols
    ), program_id="")
    condition = generate_verification_conditions(program, contracts[0]).obligations_by_rule(
        VCRuleKind.POSTCONDITION_NORMAL,
    )[0]
    with pytest.raises(UnsupportedConstructError, match="float"):
        lower_vc_obligation_to_smt(program, condition)


@pytest.mark.parametrize("source,post", [
    ("def f(x: int) -> int:\n    return x + 1\n", "result == x + 1"),
    ("def f(x: int):\n    y = x + 1\n    return y * -2\n", "result == -2 * (x + 1)"),
    ("def f(x: bool) -> bool:\n    return not x\n", "result == (not x)"),
    ("def f(x: bool, y: bool) -> bool:\n    return x and y\n", "result == (x and y)"),
    ("def f(x: bool, y: bool) -> bool:\n    return x or y\n", "result == (x or y)"),
])
@pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="real SMT binaries unavailable")
def test_supported_profile_runs_both_real_checkers(source, post):
    revision = "snapshot:authored-int-bool"
    result = SourceToVerificationPipeline().run(
        source, path="typed.py", revision=revision,
        contracts=(ContractSpec("f", postconditions=(post,)),),
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.proved and not result.disproved
    assert result.bindings.source.source_revision == revision
    assert result.bindings.source.content_sha256 == hashlib.sha256(source.encode()).hexdigest()
    for outcome in result.obligation_results:
        assert outcome.solver_executed and outcome.differential is not None
        assert outcome.smt_obligation.attributes["source_semantics_profile"] == SOURCE_SEMANTICS_PROFILE
        assert outcome.differential.left.solver_version and outcome.differential.right.solver_version


@pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="real SMT binaries unavailable")
def test_distinct_sanitized_names_do_not_turn_false_properties_into_proofs():
    source = "def f(x: int, x_: int) -> int:\n    return x\n"
    result = SourceToVerificationPipeline().run(
        source, path="distinct_symbols.py",
        contracts=(ContractSpec("f", postconditions=("result == x_",)),),
    )
    assert result.status is PipelineStatus.SUCCESS
    assert result.disproved and not result.proved
    declarations = result.obligation_results[0].smt_obligation.functions
    assert len({item.name for item in declarations}) == 3


def test_preconditions_are_boolean_instead_of_python_truthiness():
    result = SourceToVerificationPipeline(execute_solvers=False).run(
        "def f(x: int) -> int:\n    return x\n",
        path="nonboolean_precondition.py",
        contracts=(ContractSpec("f", preconditions=("x",), postconditions=("result == x",)),),
    )
    assert result.status is PipelineStatus.UNSUPPORTED and not result.proved


def test_precondition_only_contract_cannot_be_used_as_its_own_postcondition(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a precondition declaration must not dispatch a solver")

    monkeypatch.setattr(implementation, "run_z3_cvc5_differential", forbidden)
    result = SourceToVerificationPipeline().run(
        "def f(x: int) -> int:\n    return x + 1\n", path="precondition_only.py",
        contracts=[ContractSpec("f", preconditions=("x > 0",))],
    )
    assert result.status is PipelineStatus.UNSUPPORTED
    assert not result.obligation_results and not result.proved


def test_entry_assumptions_are_not_admitted_solver_rules():
    with pytest.raises(UnsupportedConstructError, match="solver_rules"):
        SourceToVerificationPipeline(solver_rules=(VCRuleKind.PRECONDITION,))


@pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="real SMT binaries unavailable")
def test_multiple_contracts_for_one_function_keep_distinct_property_meanings():
    result = SourceToVerificationPipeline(include_supervisor_evidence=False).run(
        "def f(x: int) -> int:\n    return x + 1\n", path="two_contracts.py",
        contracts=[ContractSpec("f", postconditions=("result == x + 1",), contract_id="contract:correct"),
                   ContractSpec("f", postconditions=("result == x + 2",), contract_id="contract:incorrect")],
    )
    assert result.status is PipelineStatus.SUCCESS, result.diagnostics
    assert len(result.obligation_results) == 2
    assert result.obligation_results[0].differential.classification.value == "agree_proved"
    assert result.obligation_results[1].differential.classification.value == "agree_disproved"
    assert not result.proved and result.disproved
    assert len({expression.expression_id for expression in result.program.expressions}) == len(result.program.expressions)
    assert len({clause.clause_id for contract in result.contracts for clause in contract.postconditions}) == 2

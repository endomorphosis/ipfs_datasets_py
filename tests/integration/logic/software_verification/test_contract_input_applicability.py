"""Actual input-feasibility, coverage and domain-restricted property checks."""

from dataclasses import replace
import shutil

import pytest

from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
from ipfs_datasets_py.logic.backends.smt.differential import run_z3_cvc5_differential
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.applicability import (
    RequestedInputDomain, UnsupportedApplicabilityError, derive_contract_domain_obligations,
)
from ipfs_datasets_py.logic.software_verification.pipeline import (
    ContractSpec, PipelineStatus, SourceToVerificationPipeline, UnsupportedConstructError,
)


def _model(*, source="def f(x: int) -> int:\n    y = x + 1\n    return y\n",
           pre=(), post="result == x + 1"):
    result = SourceToVerificationPipeline(execute_solvers=False, include_supervisor_evidence=False).run(
        source, path="authored_applicability.py", revision="snapshot:input-applicability",
        contracts=[ContractSpec("f", preconditions=pre, postconditions=(post,))],
    )
    assert result.status is PipelineStatus.SUCCESS, result.diagnostics
    return result.program, result.contracts[0]


@pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="real SMT binaries unavailable")
@pytest.mark.parametrize("pre,domain,post,expected", [
    ((), ("True",), "result == x + 1", ("agree_satisfiable", "agree_satisfiable", "agree_proved", "agree_proved")),
    (("x > 0", "x < 0"), ("True",), "result == x + 1", ("agree_unsatisfiable", "agree_satisfiable", "agree_disproved", "agree_proved")),
    (("x > 0",), ("True",), "result > 0", ("agree_satisfiable", "agree_satisfiable", "agree_disproved", "agree_disproved")),
    ((), ("x > 0", "x < 0"), "result > 0", ("agree_satisfiable", "agree_unsatisfiable", "agree_proved", "agree_proved")),
    (("x > 0",), ("x > 1",), "result > 0", ("agree_satisfiable", "agree_satisfiable", "agree_proved", "agree_proved")),
    ((), ("x > 0",), "result > 0", ("agree_satisfiable", "agree_satisfiable", "agree_proved", "agree_proved")),
    ((), ("x < -1",), "result > 0", ("agree_satisfiable", "agree_satisfiable", "agree_proved", "agree_disproved")),
    (("x > 100",), ("x < -100",), "result == x + 1", ("agree_satisfiable", "agree_satisfiable", "agree_disproved", "agree_proved")),
])
def test_real_native_queries_preserve_distinct_scope(pre, domain, post, expected):
    program, contract = _model(pre=pre, post=post)
    checks = derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", domain))
    assert len(checks) == 4
    classifications = []
    for check in checks:
        compilation = SoftwareVerificationSMTCompiler().compile(check.smt_obligation)
        report = run_z3_cvc5_differential(compilation, bounds=ExecutionBounds(
            timeout_ms=3000, max_steps=100000, max_memory_bytes=128 * 1024 * 1024,
            max_output_bytes=64 * 1024,
        ))
        assert report.left.solver_version and report.right.solver_version
        classifications.append(report.classification.value)
    assert tuple(classifications) == expected


@pytest.mark.parametrize("predicate", [
    "result > 0", "y > 0", "old(x) > 0", "x", "x and True", "x == True",
    "x / 2 > 0", "x // 2 > 0", "x % 2 > 0", "x * x > 0", "[x] == [x]",
])
def test_input_predicates_fail_before_tools_if_not_entry_boolean_linear(predicate):
    program, contract = _model()
    with pytest.raises((UnsupportedConstructError, ValueError)):
        derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", (predicate,)))


def test_entry_queries_omit_body_result_and_postcondition():
    program, contract = _model(pre=("x > 0",), post="False")
    checks = derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", ("x > 1",)))
    parameters = set(program.functions[0].parameter_symbol_ids)
    for check in checks[:3]:
        assert not check.smt_obligation.assumptions
        assert len(check.smt_obligation.functions) == 1
        assert set(check.smt_obligation.attributes["parameter_symbol_bindings"]) == parameters
        assert "body_return" not in SoftwareVerificationSMTCompiler().compile(check.smt_obligation).smtlib
    last_script = SoftwareVerificationSMTCompiler().compile(checks[3].smt_obligation).smtlib
    assert "body_return" in last_script and "body_assign" in last_script
    assert checks[3].smt_obligation.attributes["original_vc"]["assumption_expression_ids"]
    assert checks[3].smt_obligation.attributes["original_vc"]["assumption_expression_ids"] != checks[3].smt_obligation.attributes["requested_domain_vc"]["assumption_expression_ids"]


def test_bool_domains_have_boolean_symbols_without_truthiness():
    program, contract = _model(source="def f(x: bool) -> bool:\n    return not x\n",
                               pre=("x",), post="result == (not x)")
    checks = derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", ("not x",)))
    assert all(check.smt_obligation.functions[0].range.name == "Bool" for check in checks[:3])


def test_precondition_cannot_use_an_output_as_an_entry_premise():
    program, contract = _model(pre=("result > 0",))
    with pytest.raises(UnsupportedApplicabilityError, match="entry parameters"):
        derive_contract_domain_obligations(program, contract, RequestedInputDomain("f"))


def test_domain_body_identity_changes_even_with_same_logical_selector():
    program, contract = _model()
    first = derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", ("x > 0",), "domain:shared"))
    second = derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", ("x < 0",), "domain:shared"))
    assert all(a.smt_obligation.obligation_id != b.smt_obligation.obligation_id for a, b in zip(first, second))


def test_exact_wire_roundtrip_and_canonical_fields():
    domain = RequestedInputDomain("f", [" x > 0 "])
    assert RequestedInputDomain.from_dict(domain.to_dict()) == domain
    for bad in ({**domain.to_dict(), "extra": True}, {**domain.to_dict(), "predicates": [" x > 0 "]}):
        with pytest.raises(UnsupportedApplicabilityError):
            RequestedInputDomain.from_dict(bad)


@pytest.mark.parametrize("kwargs", [
    {"function_name": True}, {"function_name": ""}, {"predicates": ()},
    {"predicates": "True"}, {"predicates": (True,)}, {"predicates": ("True",) * 33},
    {"predicates": ("x" * (16 * 1024 + 1),)}, {"domain_id": True},
])
def test_domain_shape_is_bounded_and_exact(kwargs):
    with pytest.raises(UnsupportedApplicabilityError):
        RequestedInputDomain(**{"function_name": "f", **kwargs})


def test_predicate_ast_work_is_bounded():
    program, contract = _model()
    with pytest.raises(UnsupportedApplicabilityError, match="size/depth"):
        derive_contract_domain_obligations(program, contract, RequestedInputDomain("f", (" and ".join(["True"] * 300),)))


def test_function_and_contract_correspondence_cannot_be_swapped():
    program, contract = _model(source="def f(x: int) -> int:\n    return x + 1\n\ndef other(z: int) -> int:\n    return z\n")
    with pytest.raises(UnsupportedApplicabilityError, match="another contracted"):
        derive_contract_domain_obligations(program, contract, RequestedInputDomain("other"))


def test_precondition_expression_cannot_use_another_functions_parameter():
    program, contract = _model(source="def f(x: int) -> int:\n    return x + 1\n\ndef other(z: int) -> int:\n    return z\n", pre=("x > 0",))
    by_id = {expression.expression_id: expression for expression in program.expressions}
    precondition = by_id[contract.preconditions[0].expression_id]
    left_id = precondition.operand_ids[0]
    foreign = program.functions[1].parameter_symbol_ids[0]
    program = replace(program, expressions=tuple(
        replace(expression, symbol_ids=(foreign,)) if expression.expression_id == left_id else expression
        for expression in program.expressions
    ), program_id="")
    with pytest.raises(ValueError, match="entry parameters|unknown ids"):
        derive_contract_domain_obligations(program, contract, RequestedInputDomain("f"))

"""Regressions for false proofs from linearizing Python execution.

These are authored programs, independent of benchmark fixtures.  The current
encoder must abstain until it has faithful CFG and SSA semantics; agreement
between two solvers cannot repair an incorrect source translation.
"""

from dataclasses import replace
import shutil

import pytest

from ipfs_datasets_py.logic.software_verification.pipeline import (
    ContractSpec,
    PipelineStatus,
    SourceToVerificationPipeline,
    UnsupportedConstructError,
    attach_contract_specs,
    lower_vc_obligation_to_smt,
)
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    SourceAdapterStatus,
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    VCRuleKind,
    generate_verification_conditions,
)


BRANCH_SOURCE = """\
def f(x):
    if x > 0:
        return 1
    else:
        return 2
"""


@pytest.mark.parametrize("fail_on_unsupported", [True, False])
@pytest.mark.parametrize(
    "source, reason",
    [
        (BRANCH_SOURCE, "path_sensitive_cfg"),
        ("def f(x):\n    y = 1\n    y = 2\n    return y\n", "SSA"),
        ("def f(x):\n    x = x + 1\n    return x\n", "SSA"),
        ("def f(x):\n    y = y + 1\n    return y\n", "ProgramIR validation failed"),
        ("def f(x):\n    y = missing\n    missing = 1\n    return y\n", "ProgramIR validation failed"),
        ("def f(x):\n    return 1\n    return 2\n", "after return"),
        ("def f(x):\n    return 1\n    y = 2\n", "after return"),
        ("def f(x):\n    return\n", "implicit/null return"),
        ("def f(x):\n    return None\n", "unsupported value None"),
        ("def f(x):\n    pass\n", "explicit terminal return"),
        ("def f(x):\n    callback(x)\n    return 1\n", "ProgramIR validation failed"),
    ],
)
def test_unmodeled_execution_cannot_prove_arbitrary_postcondition(
    source: str, reason: str, fail_on_unsupported: bool
) -> None:
    result = SourceToVerificationPipeline(
        fail_on_unsupported=fail_on_unsupported,
    ).run(
        source,
        path="authored_soundness.py",
        contracts=(ContractSpec("f", postconditions=("result == 999",)),),
    )
    assert result.status is PipelineStatus.UNSUPPORTED
    assert not result.proved
    assert not result.disproved
    assert not result.obligation_results
    # The permissive analysis mode still cannot bypass the body encoder.
    if source == BRANCH_SOURCE and not fail_on_unsupported:
        assert any("path semantics" in item for item in result.diagnostics)
    else:
        assert any(reason in item for item in (*result.unsupported_constructs, *result.diagnostics))


def test_branch_observations_remain_available_without_complete_semantics() -> None:
    result = adapt_source_to_software_verification(BRANCH_SOURCE, path="branch.py")
    assert result.status is SourceAdapterStatus.PARTIAL
    assert result.program is not None
    assert "python.if.path_sensitive_cfg" in result.unsupported_constructs
    assert any(command.attributes.get("branch_condition") for command in result.program.commands)


def test_direct_ir_to_smt_entrypoint_also_rejects_linearized_branches() -> None:
    adapted = adapt_source_to_software_verification(BRANCH_SOURCE, path="branch.py")
    program, contracts = attach_contract_specs(
        adapted.program,
        (ContractSpec("f", postconditions=("result == 999",)),),
    )
    conditions = generate_verification_conditions(program, contracts[0])
    obligation = conditions.obligations_by_rule(VCRuleKind.POSTCONDITION_NORMAL)[0]
    with pytest.raises(UnsupportedConstructError, match="path semantics"):
        lower_vc_obligation_to_smt(program, obligation)


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_supported_single_assignment_fragment_still_checks_real_solvers() -> None:
    source = "def f(x):\n    y = x + 1\n    z = y + 2\n    return z\n"
    pipeline = SourceToVerificationPipeline()
    valid = pipeline.run(
        source,
        path="authored_straight_line.py",
        contracts=(ContractSpec("f", postconditions=("result == x + 3",)),),
    )
    invalid = pipeline.run(
        source,
        path="authored_straight_line.py",
        contracts=(ContractSpec("f", postconditions=("result == x + 4",)),),
    )
    assert valid.status is PipelineStatus.SUCCESS
    assert valid.proved and not valid.disproved
    assert invalid.disproved and not invalid.proved
    assert all(item.solver_executed for item in valid.obligation_results)
    # A local solver result cannot become a claim covering omitted semantics.
    assert not replace(valid, status=PipelineStatus.PARTIAL).proved
    assert not replace(valid, unsupported_constructs=("opaque_callback",)).proved
    assert not replace(valid, disagreement_quarantined=True).proved

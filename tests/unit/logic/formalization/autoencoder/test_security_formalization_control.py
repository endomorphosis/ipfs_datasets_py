"""Real classifier, deterministic code targets, and authored-spec SMT evidence.

These controls deliberately fail the learned-formula capability gate: numerical
feature reconstruction and native source lowering are not a learned decoder.
"""
import ast
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tests.unit.logic.formalization.autoencoder.test_codebase_autoencoder_transfer import teacher, fork, joint_inputs  # noqa: F401
from tests.unit.logic.formalization.autoencoder.test_security_autoencoder_checkpoint import trained, package  # noqa: F401
from tests.unit.logic.security_ir.test_code_program_derivation import unit
from ipfs_datasets_py.logic.security_ir.code_program_derivation import derive_code_program
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.pipeline import attach_contract_specs, ContractSpec, lower_vc_obligation_to_smt
from ipfs_datasets_py.logic.software_verification.vc import generate_verification_conditions, VCRuleKind
from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend
from ipfs_datasets_py.logic.backends.results import ResultStatus
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

CONTROL = "def increment(x):\n    y = x + 1\n    return y\n"


def _compile_authored_postcondition(postcondition):
    code_unit, raw = unit(CONTROL)
    derived = derive_code_program(code_unit=code_unit, source_bytes=raw)
    assert derived["status"] == "derived"
    program = ProgramIR.from_dict(derived["projection"]["targets"][0]["native_document"])
    # The specification is independently authored here, never inferred from a
    # classifier label or claimed as a decoded autoencoder output.
    program, contracts = attach_contract_specs(program, [ContractSpec(function_name="increment",
        postconditions=(postcondition,), contract_id="contract:authored-increment")])
    contracts[0].validate_against(program)
    vcs = generate_verification_conditions(program, contracts[0])
    obligations = vcs.obligations_by_rule(VCRuleKind.POSTCONDITION_NORMAL)
    assert len(obligations) == 1
    obligation, body_names = lower_vc_obligation_to_smt(program, obligations[0])
    assert body_names == ("body_assign_0", "body_return_1")
    assert code_unit.cid in obligations[0].source_ref_ids
    compilation = SoftwareVerificationSMTCompiler().compile(obligation)
    return derived, program, contracts[0], compilation


def test_authored_control_generates_native_typed_vc_and_smt_without_solver_or_model():
    derived, program, contract, compilation = _compile_authored_postcondition("result == x + 1")
    assert compilation.receipt.receipt_id and compilation.script.digest
    assert "body_assign_0" in compilation.smtlib and "body_return_1" in compilation.smtlib
    assert "(check-sat)" in compilation.smtlib
    assert contract.function_id in {fn.function_id for fn in program.functions}
    assert derived["provider_calls"] == derived["solver_calls"] == 0
    assert derived["proof_authority"] is False
    assert derived["security_specification_inferred"] is False


@pytest.mark.skipif(shutil.which("z3") is None, reason="real Z3 unavailable; source/VC/SMT control remains required")
@pytest.mark.parametrize("postcondition,verdict", [("result == x + 1", ResultStatus.PROVED),
                                                   ("result == x + 2", ResultStatus.DISPROVED)])
def test_real_z3_checks_correct_and_wrong_authored_postconditions(postcondition, verdict):
    derived, _, _, compilation = _compile_authored_postcondition(postcondition)
    outcome = Z3SoftwareVerificationBackend().run(compilation,
        bounds=ExecutionBounds(timeout_ms=5000, max_steps=100000,
            max_memory_bytes=128 * 1024 * 1024, max_output_bytes=65536))
    assert outcome.result.status is verdict
    assert outcome.compilation.script.digest == compilation.script.digest
    assert outcome.solver_version
    if verdict is ResultStatus.DISPROVED:
        assert outcome.model_text
    else:
        assert outcome.unsat_core
    # Solver evidence concerns the explicitly modeled integer fragment and
    # authored postcondition. The classifier obtains no proof authority.
    assert derived["source_semantics_verified"] is False
    assert derived["assumptions"]["modeled_argument_type"].startswith("exact built-in Python int")


def test_real_checkpoint_supported_control_keeps_deterministic_target_independent_of_model(package, tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formalization_evaluation as evaluation
    from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder as trainer
    _, _, checkpoint = package
    monkeypatch.setattr(trainer, "train_codebase_autoencoder", lambda **kwargs: pytest.fail("E2E retrained"))
    repository = tmp_path / "authored-control"
    repository.mkdir()
    raw = CONTROL.encode()
    (repository / "control.py").write_bytes(raw)
    result = evaluation.run_security_formalization_evaluation(repository=repository,
        paths=["control.py"], source_hashes={"control.py": hashlib.sha256(raw).hexdigest()},
        checkpoint=checkpoint, output=tmp_path / "formal-evaluation")
    assert result["summary"]["sample_count"] == 1
    assert result["summary"]["program_ir_count"] == 1
    assert result["summary"]["learned_formula_count"] == 0
    assert result["summary"]["learned_formula_generation_passed"] is False
    assert result["missing_capabilities"]
    assert all(result[name] == 0 for name in ("provider_calls", "training_steps", "download_calls", "solver_calls"))
    with pytest.raises(evaluation.MissingFormalDecoderError):
        evaluation.require_learned_formula_generation(result)
    assert Path(tmp_path / "formal-evaluation/evaluation.json").is_file()
    assert Path(tmp_path / "formal-evaluation/inference/inference.json").is_file()
    row = result["function_results"][0]
    assert row["derivation"]["status"] == "derived"
    body = ast.get_source_segment(CONTROL, ast.parse(CONTROL).body[0]).encode()
    # Actual causal ablation: the second route invokes no checkpoint/model at
    # all, yet generates the exact same ProgramIR projection and derivation.
    model_off = derive_code_program(code_unit=CodeUnit.from_dict(row["code_unit"]), source_bytes=body)
    assert model_off == row["derivation"]
    assert model_off["projection"] == row["derivation"]["projection"]
    assert json.dumps(model_off, sort_keys=True) == json.dumps(row["derivation"], sort_keys=True)
    monkeypatch.setattr(evaluation.checkpoint_api, "infer_security_checkpoint",
                        lambda **kwargs: pytest.fail("model-off control invoked checkpoint inference"))
    baseline = evaluation.derive_security_source_programs(repository=repository, paths=["control.py"],
        source_hashes={"control.py": hashlib.sha256(raw).hexdigest()})
    assert {item["row_id"]: item for item in baseline["function_results"]} == {
        item["row_id"]: item for item in result["function_results"]}

"""Source-bound proof coverage for the unsealed pilot/development forms."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from benchmarks.logic_pipeline import adapters, contracts, runtime


_NEW_SUPPORTED_CASES = (
    (
        (
            "A licensed carrier must file a report. Mira is a licensed carrier. "
            "Therefore Mira is obligated to file a report."
        ),
        "theorem",
        "deontic",
        "obligated",
        "deontic_modus_ponens",
        "exact rule witness fact",
    ),
    (
        (
            "If notice is filed before the deadline, review begins afterward. "
            "Notice N1 was filed before the deadline. "
            "Therefore review of N1 begins afterward."
        ),
        "theorem",
        "temporal",
        "after",
        "temporal_conditional_instantiation",
        "exact rule witness fact",
    ),
    (
        (
            "For every court there is a clerk who serves every division of that "
            "court. Court East exists. Therefore some clerk serves every East "
            "division."
        ),
        "theorem",
        "fol",
        "serves",
        "nested_exists_forall_instantiation",
        "exact rule scope_witness",
    ),
    (
        (
            "No suspended permit is valid. Permit P3 is suspended. "
            "The claim that P3 is valid is false."
        ),
        "countermodel",
        "fol",
        "counterexample",
        "unary_exclusion_countermodel",
        "exact exclusion_rule witness fact",
    ),
    (
        (
            "No expired credential is active. Credential C5 is expired. "
            "The claim that C5 is active is false."
        ),
        "countermodel",
        "fol",
        "counterexample",
        "unary_exclusion_countermodel",
        "exact exclusion_rule witness fact",
    ),
    (
        (
            "Every bronze token is metal. Every metal token conducts. "
            "Token B is bronze. Therefore token B conducts."
        ),
        "theorem",
        "fol",
        "conducts",
        "two_step_unary_chain",
        "exact second_rule witness (first_rule witness fact)",
    ),
)

_RESIDUAL_UNSUPPORTED_CASES = (
    (
        (
            "Every agency assigns some reviewer to every permit. Agency North "
            "exists. Therefore each North permit has a reviewer."
        ),
        "theorem",
        "fol",
        "reviewed",
    ),
    (
        (
            "Any custodian who receives a key must return it. Ivo received key "
            "K4. Therefore Ivo is obligated to return K4."
        ),
        "theorem",
        "deontic",
        "obligated",
    ),
    (
        (
            "An appeal submitted before closure is heard after submission. "
            "Appeal A2 was timely submitted. Therefore A2 is heard later."
        ),
        "theorem",
        "temporal",
        "after",
    ),
    (
        (
            "All valid licenses authorize entry. License L2 is valid. Jo holds "
            "L2. Therefore Jo may enter."
        ),
        "theorem",
        "fol",
        "authorized",
    ),
    (
        (
            "Certified inspectors may enter sites. Uma is certified as inspector "
            "C9. C9 covers site S2. Therefore Uma may enter S2."
        ),
        "theorem",
        "fol",
        "authorized",
    ),
)


def _input(
    text: str,
    kind: str,
    logic: str,
    target: str,
) -> dict[str, object]:
    return {
        "text": text,
        "obligation_id": "source-coverage-obligation",
        "proof_obligation": {
            "kind": kind,
            "logic": logic,
            "target": target,
        },
    }


def _compile_translation(
    value: dict[str, object],
) -> tuple[runtime.CompiledObligation, runtime.ReviewedEntailmentTranslation | None]:
    compiled = runtime.compile_reviewed_obligation(value)
    assert compiled is not None
    return compiled, runtime._entailment_translation(
        value,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )


def _compiler_artifact(
    compiled: runtime.CompiledObligation,
    translation: runtime.ReviewedEntailmentTranslation,
) -> adapters.StageArtifact:
    assert translation.native_proof_text is not None
    candidate = {
        "schema": runtime.NATIVE_PROOF_CANDIDATE_SCHEMA,
        "translation_sha256": translation.digest,
        "obligation_sha256": compiled.obligation_sha256,
        "source_sha256": translation.source_sha256,
        "derivation": translation.shape,
        "certificate": translation.native_proof_text,
        "authoritative": False,
        "requires_independent_kernel": True,
    }
    return adapters.StageArtifact(
        stage=contracts.StageName.COMPILER,
        status=contracts.StageStatus.SUCCESS,
        data={
            "compiled_obligation": compiled.to_dict(),
            "compiled_obligation_sha256": compiled.digest,
            "entailment_translation": translation.to_dict(),
            "entailment_translation_sha256": translation.digest,
            "native_proof_candidate": candidate,
        },
        output_sha256=None,
        effective_identity={"implementation": "source-coverage-test"},
        invocation_index=0,
    )


@pytest.mark.parametrize(
    ("text", "kind", "logic", "target", "shape", "proof"),
    _NEW_SUPPORTED_CASES,
)
def test_additional_source_shapes_are_exact_and_label_blind(
    text: str,
    kind: str,
    logic: str,
    target: str,
    shape: str,
    proof: str,
) -> None:
    value = _input(text, kind, logic, target)
    compiled, translation = _compile_translation(value)
    relabeled, relabeled_translation = _compile_translation(
        {
            **value,
            "expected_class": "unsupported",
            "expected_ir": {"logic": "unrelated", "target": "unrelated"},
        }
    )

    assert translation is not None
    assert translation.shape == shape
    assert translation.native_proof_text == proof
    assert translation.hammer_proof_text == proof
    assert relabeled == compiled
    assert relabeled_translation == translation
    assert "expected_class" not in compiled.source_template
    assert "expected_ir" not in compiled.source_template


@pytest.mark.parametrize(
    ("text", "kind", "logic", "target", "_shape", "_proof"),
    _NEW_SUPPORTED_CASES,
)
def test_additional_source_shapes_pass_cvc5_and_native_lean(
    text: str,
    kind: str,
    logic: str,
    target: str,
    _shape: str,
    _proof: str,
) -> None:
    cvc5 = shutil.which("cvc5")
    lean = shutil.which("lean")
    if cvc5 is None or lean is None:
        pytest.skip("installed cvc5 and Lean executables are required")
    value = _input(text, kind, logic, target)
    compiled, translation = _compile_translation(value)
    assert translation is not None
    assert translation.native_proof_text is not None

    solver = subprocess.run(
        (cvc5, "--lang=smt2"),
        input=translation.smt2_problem,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    checked = subprocess.run(
        (lean, "-j", "1", "--stdin"),
        input=compiled.render(translation.native_proof_text),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert solver.returncode == 0, solver.stdout + solver.stderr
    assert solver.stdout.strip() == "unsat"
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize(
    ("text", "kind", "logic", "target", "_shape", "_proof"),
    _NEW_SUPPORTED_CASES,
)
def test_additional_source_candidates_pass_full_native_kernel_binding(
    tmp_path: Path,
    text: str,
    kind: str,
    logic: str,
    target: str,
    _shape: str,
    _proof: str,
) -> None:
    lean = shutil.which("lean")
    if lean is None:
        pytest.skip("installed Lean executable is required")
    value = _input(text, kind, logic, target)
    compiled, translation = _compile_translation(value)
    assert translation is not None
    compiler = _compiler_artifact(compiled, translation)
    runner = runtime.NativeKernelRunner(
        lean,
        "b" * 64,
        tmp_path / "kernel-state",
    )
    try:
        output = runner(
            adapters.StageRequest(
                run_id="source-coverage-test",
                case_id="source-coverage-case",
                case_manifest_sha256="a" * 64,
                variant_id="A1",
                input_data=value,
                requested_identity={"kernel": "lean"},
                environment_sha256="b" * 64,
                upstream_artifacts=(compiler,),
                invocation_index=1,
            )
        )
    finally:
        runner.close()

    assert output.status is contracts.StageStatus.SUCCESS
    assert output.kernel_accepted is True
    assert output.kernel_receipt_sha256 is not None
    assert output.data["accepted"] is True
    assert output.data["independent"] is True


@pytest.mark.parametrize(
    ("text", "kind", "logic", "target"),
    _RESIDUAL_UNSUPPORTED_CASES,
)
def test_semantically_incomplete_or_lexically_implicit_cases_stay_unsupported(
    text: str,
    kind: str,
    logic: str,
    target: str,
) -> None:
    compiled, translation = _compile_translation(
        _input(text, kind, logic, target)
    )

    assert translation is None
    assert "translation:unsupported" in compiled.source_template


@pytest.mark.parametrize(
    ("text", "kind", "logic", "target"),
    (
        (
            (
                "A licensed carrier must file a report. Mira is a licensed "
                "carrier. Therefore Mira is obligated to submit a report."
            ),
            "theorem",
            "deontic",
            "obligated",
        ),
        (
            (
                "If notice is filed before the deadline, review begins "
                "afterward. Notice N1 was filed before closure. Therefore review "
                "of N1 begins afterward."
            ),
            "theorem",
            "temporal",
            "after",
        ),
        (
            (
                "For every court there is a clerk who serves every division of "
                "that court. Court East exists. Therefore some clerk serves every "
                "West division."
            ),
            "theorem",
            "fol",
            "serves",
        ),
        (
            (
                "No suspended permit is valid. Permit P3 is suspended. "
                "The claim that P4 is valid is false."
            ),
            "countermodel",
            "fol",
            "counterexample",
        ),
        (
            (
                "Every bronze token is metal. Every metal token conducts. "
                "Token B is bronze. Therefore token B is conducts."
            ),
            "theorem",
            "fol",
            "conducts",
        ),
    ),
)
def test_translation_rejects_cross_sentence_binding_mismatches(
    text: str,
    kind: str,
    logic: str,
    target: str,
) -> None:
    compiled, translation = _compile_translation(
        _input(text, kind, logic, target)
    )

    assert translation is None
    assert "translation:unsupported" in compiled.source_template

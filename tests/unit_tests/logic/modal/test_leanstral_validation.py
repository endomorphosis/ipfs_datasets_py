"""Tests for isolated Leanstral projected-change validation."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LegalIRLeanTask,
    LeanstralProjectedValidationConfig,
    ModalLogicCodecConfig,
    PythonPatchProposal,
    compare_leanstral_holdout_pareto,
    load_leanstral_canary_manifest,
    validate_leanstral_projected_change,
)
from ipfs_datasets_py.logic.modal.leanstral_validation import (
    DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST,
    DEFAULT_LEANSTRAL_MUTATION_FIXTURE,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)


class _GuidanceAutoencoder:
    def compiler_guidance_for_sample(self, sample):
        return {
            "feature_groups": {"compiler_contract": ["modal:deontic"]},
            "legal_ir_view_gap_distribution": {"deontic_norms": 0.1},
            "legal_ir_view_metrics": {"cross_entropy_loss": 0.2},
            "ranked_guidance_features": [{"feature": "modal:deontic", "score": 1.0}],
            "synthesis_focus": ["legal_ir_multiview"],
        }


def _sample():
    text = "The agency must provide notice within 30 days after application."
    base = build_us_code_sample(title="5", section="552", text=text)
    result = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    ).encode(
        text,
        document_id=base.sample_id,
        citation=base.citation,
        source=base.source,
        source_embedding=base.embedding_vector,
    )
    return replace(
        base,
        modal_ir=result.modal_ir,
        frame_candidates=result.frame_candidates,
        selected_frame=result.selected_frame,
        losses=result.losses,
    )


def _task(sample=None) -> LegalIRLeanTask:
    sample = sample or _sample()
    return LegalIRLeanTask.from_sample(
        sample,
        autoencoder_guidance=_GuidanceAutoencoder().compiler_guidance_for_sample(sample),
    )


def _repo_with_allowed_file(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    target = repo / "ipfs_datasets_py/logic/modal/codec.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    return repo


def _allowed_patch(task: LegalIRLeanTask) -> PythonPatchProposal:
    change_spec = task.compiler_change_spec
    assert change_spec is not None
    return PythonPatchProposal(
        compiler_change_spec_id=str(change_spec["spec_id"]),
        summary="Change one allowed compiler rule fixture.",
        unified_diff=(
            "diff --git a/ipfs_datasets_py/logic/modal/codec.py b/ipfs_datasets_py/logic/modal/codec.py\n"
            "--- a/ipfs_datasets_py/logic/modal/codec.py\n"
            "+++ b/ipfs_datasets_py/logic/modal/codec.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        ),
    )


def test_projected_change_runs_in_disposable_worktree_and_accepts_pareto_safe_patch(tmp_path) -> None:
    sample = _sample()
    task = _task(sample)
    repo = _repo_with_allowed_file(tmp_path)
    manifest = load_leanstral_canary_manifest(DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST)
    config = LeanstralProjectedValidationConfig(
        repo_root=str(repo),
        worktree_parent=str(tmp_path),
        mutation_fixture_path=str(DEFAULT_LEANSTRAL_MUTATION_FIXTURE),
        holdout_manifest_path=str(DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST),
        validation_commands=(
            [
                "python",
                "-c",
                (
                    "from pathlib import Path; "
                    "assert Path('ipfs_datasets_py/logic/modal/codec.py').read_text() == 'VALUE = 2\\n'"
                ),
            ],
        ),
        cross_entropy_deadband=0.001,
        cosine_deadband=0.001,
    )

    result = validate_leanstral_projected_change(
        task,
        _allowed_patch(task),
        config=config,
        samples=(sample,),
        candidate_holdout_records=manifest.cases,
    )

    assert result.accepted is True
    assert result.reasons == ()
    assert result.changed_paths == ("ipfs_datasets_py/logic/modal/codec.py",)
    assert result.disposable_worktree_removed is True
    assert result.worktree_path
    assert not Path(result.worktree_path).exists()
    check_names = {check.name for check in result.checks}
    assert {
        "allowed_path",
        "apply_patch",
        "syntax",
        "focused_tests",
        "deterministic_round_trip",
        "theorem",
        "graph",
        "provenance",
        "anti_copy",
        "mutation",
        "frozen_holdout",
    }.issubset(check_names)
    payload = json.loads(result.to_json())
    assert payload["schema_version"] == "legal-ir-leanstral-projected-validation-v1"
    assert payload["report_id"].startswith("leanstral-validation-")


def test_projected_change_rejects_disallowed_paths_before_worktree(tmp_path) -> None:
    task = _task()
    repo = _repo_with_allowed_file(tmp_path)
    config = LeanstralProjectedValidationConfig(
        repo_root=str(repo),
        worktree_parent=str(tmp_path),
        require_focus_commands=False,
    )
    change_spec = task.compiler_change_spec
    assert change_spec is not None
    result = validate_leanstral_projected_change(
        task,
        PythonPatchProposal(
            compiler_change_spec_id=str(change_spec["spec_id"]),
            unified_diff=(
                "diff --git a/setup.py b/setup.py\n"
                "--- a/setup.py\n"
                "+++ b/setup.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
        ),
        config=config,
    )

    assert result.accepted is False
    assert "python_patch_touches_disallowed_path" in result.reasons
    assert result.worktree_path == ""


def test_holdout_pareto_rejects_cross_entropy_regression_beyond_deadband() -> None:
    manifest = load_leanstral_canary_manifest(DEFAULT_LEANSTRAL_HOLDOUT_MANIFEST)
    baseline = manifest.cases[0]
    candidate = replace(
        baseline,
        compiler_ir=replace(
            baseline.compiler_ir,
            cross_entropy_loss=baseline.compiler_ir.cross_entropy_loss + 0.02,
        ),
        record_id="",
    )

    comparisons = compare_leanstral_holdout_pareto(
        (baseline,),
        (candidate,),
        cross_entropy_deadband=0.001,
        cosine_deadband=0.001,
    )

    failed = [comparison for comparison in comparisons if not comparison.accepted]
    assert failed
    assert {comparison.reason_code for comparison in failed} == {
        "holdout_cross_entropy_regression"
    }

"""Tests for the typed, shadow-only Leanstral legal-IR lane."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LegalIRLeanTask,
    LeanstralConfig,
    LeanstralShadowRunner,
    ModalLogicCodecConfig,
    PythonPatchProposal,
    validate_python_patch_proposal,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)


class _GuidanceAutoencoder:
    """Keep Leanstral contract tests independent of the training cost."""

    def compiler_guidance_for_sample(self, sample):
        return {
            "feature_groups": {"compiler_contract": ["modal:deontic"]},
            "legal_ir_view_gap_distribution": {"deontic_norms": 0.1},
            "legal_ir_view_metrics": {"cross_entropy_loss": 0.2},
            "ranked_guidance_features": [
                {"feature": "modal:deontic", "score": 1.0}
            ],
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


def test_shadow_runner_validates_a_fixed_lean_goal_and_persists_artifact(tmp_path) -> None:
    sample = _sample()
    calls: list[dict[str, object]] = []

    def fake_generate(prompt: str, **kwargs: object) -> str:
        calls.append({"prompt": prompt, **kwargs})
        task = json.loads(prompt)["task"]
        change_spec = task["compiler_change_spec"]
        return json.dumps(
            {
                "schema_version": "legal-ir-leanstral-proposal-v1",
                "task_id": task["task_id"],
                "target_modal_ir_hash": task["modal_ir_hash"],
                "compiler_change_spec_id": change_spec["spec_id"],
                "proof": "by simp [wellFormed, modalityMatches, sourceProvenancePresent, String.length]",
                "deterministic_rule_hints": [
                    {
                        "action": "add_or_refine_spacy_rule",
                        "rationale": "Review the explicit obligation cue.",
                        "target_component": change_spec["target_component"],
                    }
                ],
                "notes": "Proof targets verifier-generated IR well-formedness only.",
            }
        )

    runner = LeanstralShadowRunner(
        LeanstralConfig(enabled=True, artifact_dir=str(tmp_path)),
        llm_generate=fake_generate,
    )
    result = runner.run(sample, autoencoder=_GuidanceAutoencoder())

    assert result.llm_called is True
    assert result.proposal is not None
    assert result.validation.accepted is True
    assert result.validation.proof_sha256
    assert result.artifact_path is not None
    assert (tmp_path / f"{result.task.task_id}.json").is_file()
    assert calls[0]["provider"] == "mistral_vibe"
    assert calls[0]["model_name"] == "Leanstral"
    assert calls[0]["mistral_vibe_agent"] == "lean"
    task_payload = json.loads(str(calls[0]["prompt"]))["task"]
    assert "legal_ir_view_metrics" in task_payload["autoencoder_evidence"]
    assert task_payload["projection_evidence"]["source_span_hashes"]
    assert task_payload["compiler_change_spec"]["patchable"] is True
    assert "ipfs_datasets_py/logic/modal/codec.py" in task_payload["compiler_change_spec"]["allowed_paths"]


def test_shadow_runner_rejects_proof_that_changes_the_trusted_boundary() -> None:
    sample = _sample()

    def fake_generate(prompt: str, **kwargs: object) -> str:
        del kwargs
        task = json.loads(prompt)["task"]
        return json.dumps(
            {
                "schema_version": "legal-ir-leanstral-proposal-v1",
                "task_id": task["task_id"],
                "target_modal_ir_hash": task["modal_ir_hash"],
                "compiler_change_spec_id": task["compiler_change_spec"]["spec_id"],
                "proof": "by sorry",
            }
        )

    result = LeanstralShadowRunner(
        LeanstralConfig(enabled=True),
        llm_generate=fake_generate,
    ).run(sample, autoencoder=_GuidanceAutoencoder())

    assert result.validation.accepted is False
    assert "forbidden_proof_construct" in result.validation.reasons


def test_python_patch_contract_only_admits_allowed_paths_after_git_check(tmp_path) -> None:
    sample = _sample()
    guidance = _GuidanceAutoencoder().compiler_guidance_for_sample(sample)
    task = LegalIRLeanTask.from_sample(sample, autoencoder_guidance=guidance)
    change_spec = task.compiler_change_spec
    assert change_spec is not None

    repo = tmp_path / "repo"
    target = repo / "ipfs_datasets_py/logic/modal/codec.py"
    target.parent.mkdir(parents=True)
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    allowed_patch = PythonPatchProposal(
        compiler_change_spec_id=str(change_spec["spec_id"]),
        summary="Change one allowed compiler rule fixture.",
        unified_diff=(
            "diff --git a/ipfs_datasets_py/logic/modal/codec.py b/ipfs_datasets_py/logic/modal/codec.py\n"
            "--- a/ipfs_datasets_py/logic/modal/codec.py\n"
            "+++ b/ipfs_datasets_py/logic/modal/codec.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        ),
    )

    accepted = validate_python_patch_proposal(task, allowed_patch, repo_root=str(repo))

    assert accepted.accepted is True
    assert accepted.changed_paths == ("ipfs_datasets_py/logic/modal/codec.py",)

    rejected = validate_python_patch_proposal(
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
        repo_root=str(repo),
    )

    assert rejected.accepted is False
    assert "python_patch_touches_disallowed_path" in rejected.reasons


def test_projection_change_updates_the_evidence_and_task_identity() -> None:
    sample = _sample()
    baseline_guidance = _GuidanceAutoencoder().compiler_guidance_for_sample(sample)
    changed_guidance = {
        **baseline_guidance,
        "legal_ir_view_gap_distribution": {"deontic_norms": 0.2},
    }

    baseline = LegalIRLeanTask.from_sample(
        sample,
        autoencoder_guidance=baseline_guidance,
    )
    changed = LegalIRLeanTask.from_sample(
        sample,
        autoencoder_guidance=changed_guidance,
    )

    assert baseline.projection_evidence is not None
    assert changed.projection_evidence is not None
    assert baseline.projection_evidence["evidence_id"] != changed.projection_evidence["evidence_id"]
    assert baseline.task_id != changed.task_id

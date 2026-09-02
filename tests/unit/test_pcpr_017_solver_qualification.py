"""PCPR-017: qualify real Datasets solver paths."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.solver_qualification import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    EXPECTED_FORMAL_TOOLCHAIN_DEPLOYMENT_IDENTITY,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OutcomeProbe,
    PCPR_017_GOAL_ID,
    PCPR_017_TASK_ID,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    SOLVER_NAMES,
    SolverQualificationError,
    current_head_live_probes,
    current_head_probes,
    current_head_static_probes,
    discover_solver_executable,
    observe_sealed_validation_environment,
    pcpr_017_receipt_promotion,
    qualify_current_head_solver_paths,
    qualify_solver_paths,
    solver_qualification_manifest,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_017_requirements() -> None:
    assert PCPR_017_TASK_ID == "PCPR-017"
    assert PCPR_017_GOAL_ID == "PCPR-G230"
    assert INTERFACE == "DatasetsSolverQualification@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/solver-qualification@1"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_017_solver_qualification.py"
    )
    assert SOLVER_NAMES == ("z3", "cvc5", "lean", "coq")
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    assert EXPECTED_FORMAL_TOOLCHAIN_DEPLOYMENT_IDENTITY == (
        "fa9916ef2e4a927ae633309de7ef09b9d85e798e9a6711ae13bc502c6015e0c8"
    )
    manifest = solver_qualification_manifest()
    assert manifest["import_side_effects"] == "none"
    assert "user_home" in manifest["rejected_live_sources"]
    assert "simulated_fixture" in manifest["rejected_live_sources"]
    assert "auto_install" in manifest["rejected_live_sources"]


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_solver_paths()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.hermetic_results_represented_as_live is False
    assert verdict.hermetic_semantic_workflows_qualified is True
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_017_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["hermetic_semantic_workflows_qualified"] is True
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_hermetic_semantic_workflows_are_not_live() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    for probe_id in (
        "canonical_ir_roundtrip",
        "source_lineage_validation",
        "context_pack_identity",
        "translation_receipt",
        "hermetic_proof_workflow",
        "hermetic_counterexample_workflow",
    ):
        assert probes[probe_id].present is True
        assert probes[probe_id].live is False
        assert probes[probe_id].evidence_kind == "measured_hermetic"
        assert probes[probe_id].simulated_represented_as_live is False
    assert probes["readme_auto_install_not_live"].present is True
    assert probes["manifest_advertises_solver_qualification"].present is True
    assert probes["simulated_results_represented_as_live"].present is False
    assert probes["hermetic_results_represented_as_live"].present is False
    assert probes["auto_install_represented_as_live"].present is False
    assert probes["user_home_solver_represented_as_live"].present is False


def test_live_solvers_are_honest_against_admitted_discovery() -> None:
    verdict = qualify_current_head_solver_paths()
    probes = {item.probe_id: item for item in verdict.probes}
    for solver in SOLVER_NAMES:
        path = discover_solver_executable(solver)
        probe = probes[f"live_{solver}_solver"]
        if path is None:
            assert probe.present is None
            assert probe.live is False
            assert probe.evidence_kind == "unavailable"
            assert getattr(verdict, f"live_{solver}_qualified") is False
            assert getattr(verdict, f"live_{solver}_evidence_kind") == "unavailable"
        else:
            assert "/home/" not in str(path)
            assert ".local" not in str(path)
            assert ".elan" not in str(path)
            assert probe.live is True
            assert probe.evidence_kind == "measured_live"
            assert probe.present is True
            assert getattr(verdict, f"live_{solver}_qualified") is True
            assert getattr(verdict, f"live_{solver}_evidence_kind") == "measured_live"
            assert probe.details.get("sha256")
            assert probe.details.get("source") in {
                "sealed_path",
                "approved_digest_bound_managed_root",
                "managed_root",
            }
    expected_live = (
        verdict.live_z3_qualified
        and verdict.live_cvc5_qualified
        and (verdict.live_lean_qualified or verdict.live_coq_qualified)
    )
    assert verdict.live_solver_qualified is expected_live
    if expected_live:
        assert verdict.live_solver_evidence_kind == "measured_live"
    elif not any(
        (
            verdict.live_z3_qualified,
            verdict.live_cvc5_qualified,
            verdict.live_lean_qualified,
            verdict.live_coq_qualified,
        )
    ):
        assert verdict.live_solver_evidence_kind == "unavailable"


def test_user_home_solver_path_is_rejected() -> None:
    home_z3 = Path.home() / ".local" / "bin" / "z3"
    discovered = discover_solver_executable("z3")
    if home_z3.is_file():
        assert discovered != home_z3.resolve()
        if discovered is not None:
            assert ".local" not in str(discovered)
            assert "/home/" not in str(discovered)


def test_sealed_environment_does_not_treat_missing_path_tools_as_zero() -> None:
    observed = observe_sealed_validation_environment()
    assert observed["PATH"] == SEALED_PATH
    assert observed["python3_12"] == SEALED_PYTHON
    for name in ("z3", "cvc5", "lean", "coqtop"):
        value = observed[name]
        assert value == "unavailable" or value.startswith("/")
        assert value != ""
        assert value != "0"
        assert value is not False
    assert observed["z3_python_module"] in {"unavailable"} or str(
        observed["z3_python_module"]
    ).startswith("/")
    if observed["z3_python_module"] != "unavailable":
        assert "/home/" not in str(observed["z3_python_module"])
        assert ".local" not in str(observed["z3_python_module"])


def test_manifest_advertises_solver_qualification() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSolverQualification@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_solver_qualification"
    ].endswith("solver-qualification@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "solver_qualification"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_readme_does_not_claim_auto_install_is_live() -> None:
    readme = (_PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "typed unavailable" in readme.lower()
    assert "not live qualification" in readme.lower()
    assert "enabled by default; set to `0` to disable" not in readme
    assert "PCPR-017" in readme


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(SolverQualificationError, match="simulated"):
        qualify_solver_paths(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_live_claim_without_measured_live_evidence_is_rejected() -> None:
    with pytest.raises(SolverQualificationError, match="measured_live"):
        qualify_solver_paths(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=True,
                    evidence_kind="measured",
                    live=True,
                    simulated_represented_as_live=False,
                    reason="must fail",
                ),
            )
        )


def test_receipt_promotion_rejects_closed_release() -> None:
    verdict = qualify_current_head_solver_paths()
    mutated = replace(
        verdict, closed_release_outcome="release_candidate_qualified"
    )
    with pytest.raises(SolverQualificationError, match="closed release"):
        pcpr_017_receipt_promotion(mutated)


def test_source_files_exist_under_datasets_root() -> None:
    assert (
        _PACKAGE_ROOT / "ipfs_datasets_py" / "assurance" / "solver_qualification.py"
    ).is_file()
    assert (_PACKAGE_ROOT / "README.md").is_file()
    assert (
        _PACKAGE_ROOT
        / "ipfs_datasets_py"
        / "logic"
        / "external_provers"
        / "README.md"
    ).is_file()


def test_current_head_probes_are_complete() -> None:
    probes = {item.probe_id: item for item in current_head_probes()}
    for probe_id in (
        "canonical_ir_roundtrip",
        "source_lineage_validation",
        "context_pack_identity",
        "translation_receipt",
        "hermetic_proof_workflow",
        "hermetic_counterexample_workflow",
        "live_z3_solver",
        "live_cvc5_solver",
        "live_lean_solver",
        "live_coq_solver",
        "live_solver_qualification",
        "readme_auto_install_not_live",
        "manifest_advertises_solver_qualification",
    ):
        assert probe_id in probes
    live = current_head_live_probes()
    assert {item.probe_id for item in live} >= {
        "live_z3_solver",
        "live_cvc5_solver",
        "live_lean_solver",
        "live_coq_solver",
        "live_solver_qualification",
    }

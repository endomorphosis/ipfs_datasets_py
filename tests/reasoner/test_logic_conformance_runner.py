from pathlib import Path

from ipfs_datasets_py.logic.conformance.py_reference_runner import (
    discover_engine_versions,
    run_python_reference,
)


def _vectors_dir() -> Path:
    current = Path(__file__).resolve()
    for root in (current, *current.parents):
        candidate = root / "implementation_plan" / "conformance" / "vectors"
        if candidate.exists():
            return candidate
    raise AssertionError("Unable to locate shared conformance vectors")


def test_python_conformance_runner_uses_module_backed_mode() -> None:
    versions = discover_engine_versions()

    assert versions["mode"] == "module-backed-policy-runner"


def test_python_conformance_results_record_real_prover_checks() -> None:
    envelope = run_python_reference(_vectors_dir(), limit=12)

    assert envelope["engineVersions"]["mode"] == "module-backed-policy-runner"
    assert all(result["proverId"] != "python-reference-policy-oracle" for result in envelope["results"])
    assert all(
        any(
            check.get("engine") == "tdfol" and check.get("status") == "proved"
            for check in result["metadata"]["pythonProverChecks"]
        )
        for result in envelope["results"]
    )


def test_deontic_vectors_record_dcec_reference_checks() -> None:
    envelope = run_python_reference(_vectors_dir(), subsystems=["deontic"], limit=10)

    assert any(result["status"] == "refuted" for result in envelope["results"])
    assert all(
        any(
            check.get("engine") == "dcec" and check.get("status") == "proved"
            for check in result["metadata"]["pythonProverChecks"]
        )
        for result in envelope["results"]
    )

"""FACP-023: Datasets FCA outcome adapter — false-success fallback replacement.

Acceptance coverage:
- Missing backend/dependency returns Unavailable
- Attempted-but-unobserved is not success
- Verified requires admitted verifier evidence
- Compatibility projection preserves non-success disposition
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest

TASK_ID = "FACP-023"
GOAL_ID = "FACP-G210"
BUNDLE = "facp/migration/datasets-outcomes"
EVIDENCE_ID = "facp/datasets-outcomes@1"

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
_OUTCOMES_MODULE = (
    _PACKAGE_ROOT / "ipfs_datasets_py" / "assurance" / "outcomes.py"
)

FORBIDDEN_SUCCESS_MARKERS = frozenset(
    {"success", "ok", "passed", "production_supported"}
)


def _load_outcomes_module():
    """Load assurance.outcomes without executing package-root ``__init__``."""
    pkg_name = "ipfs_datasets_py"
    assurance_name = "ipfs_datasets_py.assurance"
    mod_name = "ipfs_datasets_py.assurance.outcomes"
    pkg_dir = _PACKAGE_ROOT / "ipfs_datasets_py"
    assurance_dir = pkg_dir / "assurance"

    if pkg_name not in sys.modules or not hasattr(sys.modules[pkg_name], "__path__"):
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
        pkg.__file__ = str(pkg_dir / "__init__.py")
        sys.modules[pkg_name] = pkg
    if assurance_name not in sys.modules:
        assurance = types.ModuleType(assurance_name)
        assurance.__path__ = [str(assurance_dir)]  # type: ignore[attr-defined]
        assurance.__package__ = assurance_name
        sys.modules[assurance_name] = assurance

    if mod_name in sys.modules and hasattr(
        sys.modules[mod_name], "project_compatibility"
    ):
        return sys.modules[mod_name]

    spec = importlib.util.spec_from_file_location(mod_name, _OUTCOMES_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    sys.modules[assurance_name].outcomes = module  # type: ignore[attr-defined]
    return module


@pytest.fixture
def outcomes():
    return _load_outcomes_module()


def _assert_non_success(result: Any) -> None:
    assert result.ok is False
    assert result.is_success_disposition is False
    assert result.outcome not in {"Observed", "Verified"} or result.code not in {
        "effect_observed",
        "verified_admitted",
        "download_observed",
        "upload_observed",
        "semantic_observed",
        "pin_observed",
        "get_observed",
        "save_observed",
    }
    compat = result.to_legacy_compat_dict()
    assert compat["status"] != "success"
    assert compat["ok"] is False
    assert compat["disposition"] == "non_success"
    assert compat.get("success") is not True


def test_outcomes_module_exists_and_exports_contract(outcomes):
    assert _OUTCOMES_MODULE.is_file(), f"missing declared output: {_OUTCOMES_MODULE}"
    assert outcomes.TASK_ID == TASK_ID
    assert outcomes.GOAL_ID == GOAL_ID
    assert outcomes.BUNDLE == BUNDLE
    assert outcomes.EVIDENCE_ID == EVIDENCE_ID
    assert outcomes.UNSAFE_PROMOTION is False
    for name in (
        "DatasetOutcome",
        "EvidenceEnvelope",
        "unavailable_missing_backend",
        "unavailable_missing_dependency",
        "begin_attempt",
        "bind_effect_observation",
        "admit_verified",
        "project_compatibility",
        "replace_false_success_fallback",
        "resolve_download_outcome",
        "resolve_upload_outcome",
        "resolve_semantic_outcome",
        "validate_delegated_receipt",
        "INVENTORIED_FALSE_SUCCESS_FAMILIES",
        "VERIFIED_REQUIRED_EVIDENCE",
    ):
        assert hasattr(outcomes, name), name


def test_cold_import_of_assurance_outcomes_is_pure():
    """Importing the outcomes adapter must not install or mutate env."""
    script = textwrap.dedent(
        f"""
        import os, sys, json, importlib.util, types
        package_root = {_PACKAGE_ROOT.as_posix()!r}
        outcomes_path = {_OUTCOMES_MODULE.as_posix()!r}
        for k in (
            "IPFS_DATASETS_AUTO_INSTALL",
            "IPFS_KIT_AUTO_INSTALL_DEPS",
            "IPFS_AUTO_INSTALL",
        ):
            os.environ.pop(k, None)
        for n in list(sys.modules):
            if n == "ipfs_datasets_py" or n.startswith("ipfs_datasets_py."):
                del sys.modules[n]
        pkg = types.ModuleType("ipfs_datasets_py")
        pkg.__path__ = [package_root + "/ipfs_datasets_py"]
        sys.modules["ipfs_datasets_py"] = pkg
        assurance = types.ModuleType("ipfs_datasets_py.assurance")
        assurance.__path__ = [package_root + "/ipfs_datasets_py/assurance"]
        sys.modules["ipfs_datasets_py.assurance"] = assurance
        spec = importlib.util.spec_from_file_location(
            "ipfs_datasets_py.assurance.outcomes", outcomes_path
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        after = {{
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
            "IPFS_AUTO_INSTALL": os.environ.get("IPFS_AUTO_INSTALL"),
        }}
        print("FACP023::" + json.dumps({{
            "after": after,
            "task_id": mod.TASK_ID,
            "unsafe_promotion": mod.UNSAFE_PROMOTION,
        }}, sort_keys=True))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_WORKSPACE_ROOT),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    line = next(
        ln for ln in completed.stdout.splitlines() if ln.startswith("FACP023::")
    )
    payload = json.loads(line[len("FACP023::") :])
    assert payload["task_id"] == TASK_ID
    assert payload["unsafe_promotion"] is False
    assert payload["after"]["IPFS_DATASETS_AUTO_INSTALL"] is None
    assert payload["after"]["IPFS_KIT_AUTO_INSTALL_DEPS"] is None


# ---------------------------------------------------------------------------
# Acceptance: Missing backend/dependency → Unavailable
# ---------------------------------------------------------------------------


def test_missing_backend_returns_unavailable(outcomes):
    result = outcomes.unavailable_missing_backend(
        operation="download",
        backend="ipfs",
    )
    assert result.outcome == "Unavailable"
    assert result.code == "backend_unavailable"
    _assert_non_success(result)
    assert result.details.get("fallback_success_forbidden") is True


def test_missing_dependency_returns_unavailable(outcomes):
    result = outcomes.unavailable_missing_dependency(
        operation="upload",
        dependency="ipfs_kit_py",
    )
    assert result.outcome == "Unavailable"
    assert result.code == "dependency_unavailable"
    _assert_non_success(result)


def test_resolve_download_missing_backend_is_unavailable(outcomes):
    result = outcomes.resolve_download_outcome(backend_available=False)
    assert result.outcome == "Unavailable"
    assert result.defect_id == "DS-FALSE-001"
    _assert_non_success(result)


def test_resolve_upload_missing_dependency_is_unavailable(outcomes):
    result = outcomes.resolve_upload_outcome(
        backend_available=True,
        dependency_available=False,
    )
    assert result.outcome == "Unavailable"
    assert result.code == "dependency_unavailable"
    _assert_non_success(result)


def test_semantic_missing_vector_store_is_non_success(outcomes):
    result = outcomes.resolve_semantic_outcome(vector_store_available=False)
    assert result.outcome in {"Unavailable", "Simulated"}
    _assert_non_success(result)


# ---------------------------------------------------------------------------
# Acceptance: Attempted-but-unobserved is not success
# ---------------------------------------------------------------------------


def test_begin_attempt_is_not_success(outcomes):
    attempt = outcomes.begin_attempt(operation="download")
    assert attempt.outcome == "Attempted"
    assert attempt.envelope.effect == "started"
    _assert_non_success(attempt)


def test_attempted_without_observation_is_unknown_not_success(outcomes):
    attempt = outcomes.begin_attempt(operation="upload")
    result = outcomes.bind_effect_observation(
        attempt,
        observation_present=False,
    )
    assert result.outcome == "Unknown"
    assert result.code == "attempted_unobserved"
    assert result.details.get("success_forbidden_without_observation") is True
    _assert_non_success(result)


def test_observation_binding_yields_observed_success(outcomes):
    attempt = outcomes.begin_attempt(operation="download")
    observed = outcomes.bind_effect_observation(
        attempt,
        observation_present=True,
        observation_id="obs-1",
        admission_token="tok-1",
    )
    assert observed.outcome == "Observed"
    assert observed.ok is True
    assert "independent_effect_observation" in observed.evidence
    assert observed.envelope.effect == "observed"


def test_resolve_download_attempted_without_observation_not_success(outcomes):
    result = outcomes.resolve_download_outcome(
        backend_available=True,
        attempt_evidenced=True,
        observation_present=False,
    )
    assert result.outcome == "Attempted"
    _assert_non_success(result)


# ---------------------------------------------------------------------------
# Acceptance: Verified requires admitted verifier evidence
# ---------------------------------------------------------------------------


def _observed_download(outcomes):
    attempt = outcomes.begin_attempt(operation="download")
    return outcomes.bind_effect_observation(
        attempt,
        observation_present=True,
        observation_id="obs-verified",
        admission_token="admission:download",
        origin="hermetic_observed",
        integrity="digest_valid",
        authority="valid",
        policy="allowed",
    )


def test_verified_rejected_without_verifier_evidence(outcomes):
    observed = _observed_download(outcomes)
    assert observed.ok is True
    rejected = outcomes.admit_verified(observed, verifier_evidence={})
    assert rejected.outcome == "Rejected"
    assert rejected.code == "verified_missing_admitted_verifier_evidence"
    missing = set(rejected.details["missing_evidence"])
    assert "named_current_verifier" in missing
    assert "verifier_admission_closure" in missing
    _assert_non_success(rejected)


def test_verified_rejected_from_attempted(outcomes):
    attempt = outcomes.begin_attempt(operation="upload")
    rejected = outcomes.admit_verified(
        attempt,
        verifier_evidence={
            "named_current_verifier": "verifier-a",
            "verifier_admission_closure": "closure-a",
            "independent_effect_observation": True,
            "admission_token": "tok",
        },
    )
    assert rejected.outcome == "Rejected"
    assert rejected.code == "verified_requires_observed"
    _assert_non_success(rejected)


def test_verified_admitted_with_full_verifier_evidence(outcomes):
    observed = _observed_download(outcomes)
    verified = outcomes.admit_verified(
        observed,
        verifier_evidence={
            "named_current_verifier": "facp-datasets-verifier@1",
            "verifier_admission_closure": "closure:facp-023",
            "independent_effect_observation": True,
            "admission_token": "admission:download",
            "proof_role": "admitted",
            "proof": "verified",
        },
    )
    assert verified.outcome == "Verified"
    assert verified.code == "verified_admitted"
    assert verified.ok is True
    assert verified.envelope.proof == "verified"
    assert "named_current_verifier" in verified.evidence
    assert "verifier_admission_closure" in verified.evidence


def test_verified_rejects_candidate_proof_role(outcomes):
    observed = _observed_download(outcomes)
    rejected = outcomes.admit_verified(
        observed,
        verifier_evidence={
            "named_current_verifier": "facp-datasets-verifier@1",
            "verifier_admission_closure": "closure:facp-023",
            "independent_effect_observation": True,
            "admission_token": "admission:download",
            "proof_role": "candidate",
        },
    )
    assert rejected.outcome == "Rejected"
    assert rejected.code == "verified_requires_admitted_proof"
    _assert_non_success(rejected)


# ---------------------------------------------------------------------------
# Acceptance: Compatibility projection preserves non-success disposition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy,expected_outcome",
    [
        (
            {"status": "success", "dataset": None},
            "Unavailable",
        ),
        (
            {"status": "success", "attempt_evidenced": True},
            "Attempted",
        ),
        (
            {
                "status": "success",
                "content": "Mock content for CID QmABC",
                "mock": True,
            },
            "Simulated",
        ),
        (
            {
                "status": "success",
                "cid": "Qm000000001",
                "durable_effect": False,
                "simulated": True,
            },
            "Simulated",
        ),
        (
            {
                "status": "success",
                "note": (
                    "Simulated semantic search - full implementation requires "
                    "vector store integration"
                ),
            },
            "Simulated",
        ),
        (
            {"success": True},
            "Unavailable",
        ),
        (
            {"backend_available": False, "status": "success"},
            "Unavailable",
        ),
    ],
)
def test_compatibility_projection_preserves_non_success(
    outcomes, legacy, expected_outcome
):
    projected = outcomes.project_compatibility(legacy, operation="download")
    assert projected.outcome == expected_outcome
    _assert_non_success(projected)
    assert projected.unsafe_promotion is False
    # Must never re-emit a success boolean for clamped stubs.
    compat = projected.to_legacy_compat_dict()
    for marker in FORBIDDEN_SUCCESS_MARKERS:
        assert compat.get(marker) is not True


def test_compatibility_projection_observation_backed_may_be_observed(outcomes):
    projected = outcomes.project_compatibility(
        {
            "status": "success",
            "durable_effect": True,
            "independent_effect_observation": True,
            "observation_present": True,
        },
        operation="download",
    )
    assert projected.outcome == "Observed"
    assert projected.ok is True


def test_inventoried_families_never_emit_false_success(outcomes):
    assert len(outcomes.INVENTORIED_FALSE_SUCCESS_FAMILIES) == 9
    for family in outcomes.INVENTORIED_FALSE_SUCCESS_FAMILIES:
        result = outcomes.replace_false_success_fallback(
            family=family,
            backend_available=False,
        )
        assert result.defect_family == family
        assert result.defect_id == outcomes.INVENTORY_DEFECT_IDS[family]
        _assert_non_success(result)

        simulated = outcomes.replace_false_success_fallback(
            family=family,
            backend_available=True,
            simulated=True,
        )
        assert simulated.outcome in {"Simulated", "Unavailable", "Attempted"}
        _assert_non_success(simulated)


def test_upload_simulated_cid_is_not_success(outcomes):
    result = outcomes.resolve_upload_outcome(
        backend_available=True,
        allow_simulated_cid=True,
        family="upload_mock_cid_success",
    )
    assert result.outcome == "Simulated"
    assert result.defect_id == "DS-FALSE-004"
    _assert_non_success(result)


def test_semantic_simulated_hits_not_observed_or_verified(outcomes):
    result = outcomes.resolve_semantic_outcome(
        vector_store_available=True,
        simulated_hits=True,
    )
    assert result.outcome == "Simulated"
    assert result.outcome not in {"Observed", "Verified"}
    _assert_non_success(result)


# ---------------------------------------------------------------------------
# Effect-observation binding + delegated receipt validation
# ---------------------------------------------------------------------------


def test_delegated_receipt_missing_is_unavailable(outcomes):
    result = outcomes.validate_delegated_receipt({})
    assert result.outcome == "Unavailable"
    _assert_non_success(result)


def test_delegated_receipt_without_observation_not_success(outcomes):
    result = outcomes.validate_delegated_receipt(
        {"receipt_id": "r1", "attempt_evidenced": True},
        operation="upload",
    )
    assert result.outcome == "Attempted"
    _assert_non_success(result)


def test_delegated_receipt_with_observation_and_signature(outcomes):
    result = outcomes.validate_delegated_receipt(
        {
            "receipt_id": "r-live",
            "independent_effect_observation": True,
            "signed_receipt": True,
            "admission_token": "admission:delegated",
            "environment": "live",
        },
        operation="download",
    )
    assert result.outcome == "Observed"
    assert result.ok is True
    assert result.envelope.origin == "live_observed"


def test_delegated_receipt_revoked_is_rejected(outcomes):
    result = outcomes.validate_delegated_receipt(
        {
            "receipt_id": "r-revoked",
            "revoked": True,
            "independent_effect_observation": True,
        }
    )
    assert result.outcome == "Rejected"
    _assert_non_success(result)


def test_outcome_to_dict_carries_task_identity(outcomes):
    result = outcomes.unavailable_missing_backend(
        operation="get",
        backend="ipfs",
    )
    payload = result.to_dict()
    assert payload["task_id"] == TASK_ID
    assert payload["evidence_id"] == EVIDENCE_ID
    assert payload["ok"] is False
    assert payload["unsafe_promotion"] is False
    assert set(payload["envelope"]) == set(outcomes.DIMENSION_ORDER)

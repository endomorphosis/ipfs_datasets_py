"""Synthetic execution receipts for public adapter projection tests only."""
from types import SimpleNamespace


def unavailable_operation(**kwargs):
    return SimpleNamespace(status="unavailable", reason_code="installed_artifact_missing",
                           native_runtime={}, preparation=None, observation=None,
                           to_dict=lambda: {"status": "unavailable",
                                            "reason_code": "installed_artifact_missing",
                                            "grants_proof_authority": False})

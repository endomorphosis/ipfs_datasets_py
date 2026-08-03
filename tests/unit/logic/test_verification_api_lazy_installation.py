"""FVT-087 gates for the public transactional lazy-installer facade."""

from __future__ import annotations

import importlib
import socket
import subprocess
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.external_provers import lazy_installer
from ipfs_datasets_py.logic.verification_api import (
    LogicVerificationAPI,
    VerificationStatus,
)


@contextmanager
def _test_process_lock(_provider: str):
    yield {"cross_process": True, "lock_name": "test.lock"}


def _forbid_plugin_import(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = importlib.import_module

    def guarded(name: str, *args, **kwargs):
        if ".logic.backends.installers." in name or name.endswith("prover_installer"):
            calls.append(name)
            raise AssertionError(f"plugin import forbidden: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(lazy_installer.importlib, "import_module", guarded)
    return calls


def test_inventory_plan_denial_dry_run_and_offline_never_import_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _forbid_plugin_import(monkeypatch)

    inventory = lazy_installer.reviewed_installer_inventory()
    assert {item["tool_id"] for item in inventory} >= {
        "z3", "cvc5", "lean", "zkp-circuit", "secpal", "ergoai"
    }
    plan = lazy_installer.plan_reviewed_install("lean")
    assert plan["installer_module"].endswith(".kernel")
    assert plan["discovery_imports_plugin"] is False

    denied = lazy_installer.execute_reviewed_install("z3")
    dry = lazy_installer.execute_reviewed_install("cvc5", dry_run=True)
    offline = lazy_installer.execute_reviewed_install(
        "lean", allow_install=True, offline=True
    )
    assert denied["status"] == "authorization_required"
    assert dry["status"] == "planned"
    assert offline["status"] == "blocked"
    assert not denied["install_attempted"]
    assert not dry["install_attempted"]
    assert not offline["install_attempted"]
    assert calls == []


def test_api_probe_and_discovery_do_not_resolve_installer() -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("probe/discovery must not execute installer facade")

    api = LogicVerificationAPI(installer_executor=forbidden)
    assert api.list_providers().status is VerificationStatus.DECLARATIVE
    assert api.provider_capabilities().status is VerificationStatus.DECLARATIVE
    assert api.probe_provider("z3").status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.UNAVAILABLE,
    }


def test_api_dry_run_returns_bounded_plan_without_mutation() -> None:
    api = LogicVerificationAPI()
    response = api.install_provider("z3", dry_run=True, request_id="req:plan")
    assert response.status is VerificationStatus.DECLARATIVE
    assert response.result["status"] == "planned"
    assert response.result["mutation_authorized"] is False
    assert response.result["install_attempted"] is False
    assert response.result["plan"]["provider_id"] == "z3"
    assert response.result["plan"]["plan_digest"]


def test_installer_options_cannot_override_authorization_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _forbid_plugin_import(monkeypatch)
    response = LogicVerificationAPI().install_provider(
        "z3",
        allow_install=True,
        installer_options={"yes": False, "hermetic_shim": True},
    )
    assert response.status is VerificationStatus.INVALID
    assert response.result["status"] == "invalid_options"
    assert set(response.result["evidence"]["unsupported_options"]) == {
        "hermetic_shim",
        "yes",
    }
    assert response.result["install_attempted"] is False
    assert calls == []


def test_explicit_authorization_invokes_only_selected_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def ensure_z3(**kwargs):
        calls.append(dict(kwargs))
        return SimpleNamespace(
            status="installed",
            installed=True,
            checksum_verified=False,
            executable_path="/managed/z3",
            bindings={
                "transactional_publication": True,
                "semantic_probe": {"version": "4.12.2"},
            },
            to_dict=lambda: {
                "status": "installed",
                "installed": True,
                "checksum_verified": False,
                "executable_path": "/managed/z3",
                "bindings": {
                    "transactional_publication": True,
                    "semantic_probe": {"version": "4.12.2"},
                },
            },
        )

    original = importlib.import_module

    def selected(name: str, *args, **kwargs):
        if name.endswith(".installers.solver"):
            return SimpleNamespace(ensure_z3=ensure_z3)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(lazy_installer.importlib, "import_module", selected)
    monkeypatch.setattr(
        lazy_installer, "_cross_process_install_lock", _test_process_lock
    )
    response = LogicVerificationAPI().install_provider("z3", allow_install=True)

    assert response.status is VerificationStatus.PARTIAL
    assert response.result["certified"] is False
    assert response.result["status"] == "installed_unverified"
    assert response.result["installed"] is True
    assert response.result["mutation_authorized"] is True
    assert response.result["evidence"]["dependency"]["callable"] == "ensure_z3"
    assert response.result["evidence"]["rollback"]["verified"] is True
    assert calls and calls[0]["yes"] is True


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_non_boolean_consent_never_reaches_injected_executor(value: object) -> None:
    calls: list[object] = []

    def forbidden(*args, **_kwargs):
        calls.append(args)
        raise AssertionError("executor must not be invoked")

    response = LogicVerificationAPI(installer_executor=forbidden).install_provider(
        "z3", allow_install=value  # type: ignore[arg-type]
    )
    assert response.status is VerificationStatus.INVALID
    assert response.result["install_attempted"] is False
    assert calls == []


def test_denied_dry_run_and_offline_short_circuit_injected_executor() -> None:
    calls: list[object] = []

    def forbidden(*args, **_kwargs):
        calls.append(args)
        raise AssertionError("executor must not be invoked")

    api = LogicVerificationAPI(installer_executor=forbidden)
    assert api.install_provider("z3").status is VerificationStatus.UNSUPPORTED
    assert api.install_provider("z3", dry_run=True).status is VerificationStatus.DECLARATIVE
    assert api.install_provider(
        "z3", allow_install=True, offline=True
    ).status is VerificationStatus.UNAVAILABLE
    assert calls == []


@pytest.mark.parametrize("private_key", ["private_witness", "proving_key_bytes"])
def test_nested_private_receipt_material_fails_closed(private_key: str) -> None:
    def executor(*_args, **_kwargs):
        return {
            "status": "installed",
            "installed": True,
            "bindings": {"nested": {private_key: "TOPSECRET"}},
        }

    response = LogicVerificationAPI(installer_executor=executor).install_provider(
        "z3", allow_install=True
    )
    assert response.status is VerificationStatus.INVALID
    assert "TOPSECRET" not in str(response.to_dict())


def test_binary_receipt_material_fails_closed_but_secret_safe_flag_survives() -> None:
    bad = LogicVerificationAPI(
        installer_executor=lambda *_args, **_kwargs: {
            "status": "installed",
            "installed": True,
            "bindings": {"blob": b"private"},
        }
    ).install_provider("z3", allow_install=True)
    assert bad.status is VerificationStatus.INVALID

    safe = LogicVerificationAPI(
        installer_executor=lambda *_args, **_kwargs: {
            "status": "available",
            "installed": True,
            "certified": False,
            "evidence": {"secret_safe": True},
        }
    ).install_provider("zkp-circuit", allow_install=True)
    assert safe.status is VerificationStatus.PARTIAL
    assert safe.result["evidence"]["secret_safe"] is True


def test_progress_adapter_accepts_one_and_two_argument_plugin_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    def ensure_z3(**kwargs):
        kwargs["on_progress"]("building")
        kwargs["on_progress"]("installed", "ready")
        return {
            "status": "blocked",
            "installed": False,
            "checksum_verified": False,
        }

    original = importlib.import_module

    def selected(name: str, *args, **kwargs):
        if name.endswith(".installers.solver"):
            return SimpleNamespace(ensure_z3=ensure_z3)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(lazy_installer.importlib, "import_module", selected)
    monkeypatch.setattr(
        lazy_installer, "_cross_process_install_lock", _test_process_lock
    )
    receipt = lazy_installer.execute_reviewed_install(
        "z3", allow_install=True, progress=events.append
    )
    assert receipt["status"] == "blocked"
    assert [event.phase for event in events] == ["installing", "installed"]


def test_plan_binds_sanitized_options_without_exposing_absolute_path(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "binding.json"
    lock.write_text("{}", encoding="utf-8")
    default = lazy_installer.plan_reviewed_install("zkp-circuit")
    selected = lazy_installer.plan_reviewed_install(
        "zkp-circuit", installer_options={"deployment_lock_path": str(lock)}
    )
    assert selected["plan_digest"] != default["plan_digest"]
    public = selected["installer_options"]["deployment_lock_path"]
    assert public["basename"] == "binding.json"
    assert str(tmp_path) not in str(public)


def test_attempt_ids_are_unique_and_installed_without_evidence_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = importlib.import_module

    def selected(name: str, *args, **kwargs):
        if name.endswith(".installers.solver"):
            return SimpleNamespace(
                ensure_z3=lambda **_kwargs: {
                    "status": "installed",
                    "installed": True,
                    "checksum_verified": False,
                }
            )
        return original(name, *args, **kwargs)

    monkeypatch.setattr(lazy_installer.importlib, "import_module", selected)
    monkeypatch.setattr(
        lazy_installer, "_cross_process_install_lock", _test_process_lock
    )
    first = lazy_installer.execute_reviewed_install("z3", allow_install=True)
    second = lazy_installer.execute_reviewed_install("z3", allow_install=True)
    assert first["transaction_id"] != second["transaction_id"]
    assert first["certified"] is False
    assert first["status"] == "installed_unverified"


def test_authorization_failure_reports_pre_invocation_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.logic.backends.installers import registry

    monkeypatch.setattr(
        registry,
        "authorize_installer_entry_install",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("denied")),
    )
    receipt = lazy_installer.execute_reviewed_install("z3", allow_install=True)
    assert receipt["status"] == "failed"
    assert receipt["mutation_authorized"] is False
    assert receipt["install_attempted"] is False
    assert receipt["evidence"]["plugin_invoked"] is False


def test_registry_plugins_are_real_importable_callables_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("plugin import must not execute commands or open network")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request, "urlretrieve", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for entry in lazy_installer.reviewed_installer_inventory():
        module = importlib.import_module(entry["module_path"])
        assert callable(getattr(module, entry["ensure_name"], None)), entry


def test_zkp_binding_plugin_validates_secret_safe_public_lock(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.backends.installers.zkp import ensure_zkp_circuit

    lock = tmp_path / "zkp.json"
    lock.write_text(
        """{
          "schema_version":"zkp-deployment-lock/v1",
          "interface":"ZKPDeploymentLock@1",
          "tool_id":"zkp-circuit",
          "secret_safety":{
            "forbid_private_witness_in_lock":true,
            "forbid_proving_key_bytes_in_lock":true,
            "forbid_verification_key_bytes_in_lock":true,
            "forbid_trapdoor_in_lock":true,
            "forbid_witness_in_public_receipts":true,
            "reference_private_artifacts_by_digest_only":true
          },
          "circuit":{"circuit_id":"c:1","circuit_public_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
          "keys":{"verification_key":{"verification_key_id":"vk:1","verification_key_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}
        }""",
        encoding="utf-8",
    )
    receipt = ensure_zkp_circuit(yes=True, deployment_lock_path=lock)
    assert receipt.status == "available"
    assert receipt.checksum_verified is False
    assert receipt.bindings["deployment_lock_checksum_verified"] is True
    assert receipt.bindings["referenced_artifacts_verified"] is False
    assert receipt.bindings["secret_safe"] is True
    assert receipt.bindings["network_attempted"] is False


def test_zkp_binding_rejects_private_material(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.backends.installers.zkp import ensure_zkp_circuit

    lock = tmp_path / "bad.json"
    lock.write_text(
        '{"schema_version":"zkp-deployment-lock/v1","interface":"ZKPDeploymentLock@1",'
        '"tool_id":"zkp-circuit","private_witness":"leak",'
        '"secret_safety":{}}',
        encoding="utf-8",
    )
    receipt = ensure_zkp_circuit(
        yes=True, strict=False, deployment_lock_path=lock
    )
    assert receipt.status == "failed"
    assert "deployment_lock_invalid" in receipt.reason_codes


def test_z3_and_lean_never_delegate_to_unsafe_legacy_installers(monkeypatch) -> None:
    from ipfs_datasets_py.logic.backends.installers import kernel, solver

    monkeypatch.setattr(solver.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(kernel, "_lean_path", lambda: "")
    monkeypatch.setattr(
        solver, "authorize_installer_entry_install", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        kernel, "authorize_installer_entry_install", lambda *_args, **_kwargs: object()
    )

    z3_receipt = solver.ensure_z3(yes=True)
    lean_receipt = kernel.ensure_lean(yes=True)
    assert z3_receipt.status == "blocked"
    assert "transactional_user_local_installer_unavailable" in z3_receipt.reason_codes
    assert lean_receipt.status == "blocked"
    assert "checksummed_artifact_unavailable" in lean_receipt.reason_codes


def test_zkp_binding_requires_canonical_sha256_identities(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.backends.installers.zkp import ensure_zkp_circuit

    lock = tmp_path / "bad-digest.json"
    lock.write_text(
        """{
          "schema_version":"zkp-deployment-lock/v1",
          "interface":"ZKPDeploymentLock@1",
          "tool_id":"zkp-circuit",
          "secret_safety":{
            "forbid_private_witness_in_lock":true,
            "forbid_proving_key_bytes_in_lock":true,
            "forbid_verification_key_bytes_in_lock":true,
            "forbid_trapdoor_in_lock":true,
            "forbid_witness_in_public_receipts":true,
            "reference_private_artifacts_by_digest_only":true
          },
          "circuit":{"circuit_id":"c:1","circuit_public_digest":"not-a-digest"},
          "keys":{"verification_key":{"verification_key_id":"vk:1","verification_key_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}
        }""",
        encoding="utf-8",
    )
    receipt = ensure_zkp_circuit(
        yes=True, strict=False, deployment_lock_path=lock
    )
    assert receipt.status == "failed"
    assert "deployment_lock_invalid" in receipt.reason_codes

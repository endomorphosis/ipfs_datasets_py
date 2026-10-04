"""Public routes use the bounded installer; native lifecycle is tested separately."""
from contextlib import nullcontext
import importlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends.installers import isabelle as legacy
from ipfs_datasets_py.logic.backends.installers import isabelle_preparation as preparation
from ipfs_datasets_py.logic.backends.installers import registry
from ipfs_datasets_py.logic.external_provers import isabelle_setup as setup
from ipfs_datasets_py.logic.external_provers import lazy_installer as lazy
from ipfs_datasets_py.logic.hammers.frontends import base
from ipfs_datasets_py.logic.integration.bridges import prover_installer as bridge


def prepared(*, usable=True):
    data = {
        "usable": usable, "command_available": True, "smoke_accepted": usable,
        "readiness_level": "kernel_smoke", "reason_code": "observed",
        "native_runtime": {"version": "Isabelle2025-2",
                           "executable": "/installed/Isabelle2025-2/bin/isabelle"},
        "probes": [{"phase": "smoke", "observation": {"returncode": 0}}],
        "grants_proof_authority": False, "grants_repository_authority": False,
    }
    return SimpleNamespace(**data, to_dict=lambda: data)


def hol_build(*, succeeded=True, published=True):
    return {"status": "built" if succeeded else "failed", "build_succeeded": succeeded,
            "persistent_heap_published": published,
            "observation": {"returncode": 0 if succeeded else 1,
                            "error": None if succeeded else "bounded fixture refusal"}}


def installed(*, usable=True, preparation_data=None, status=None, build=None, reasons=None):
    data = {"status": status or ("installed" if usable else "failed"),
            "reason_codes": reasons if reasons is not None else (
                [] if usable else ["publication_validation_failed"]),
            "preparation": prepared().to_dict() if preparation_data is None else preparation_data,
            "hol_build": build, "build_hol_requested": build is not None}
    return SimpleNamespace(usable=usable, status=data["status"],
        executable="/installed/Isabelle2025-2/bin/isabelle", to_dict=lambda: data)


@pytest.fixture
def installation(monkeypatch):
    module = importlib.import_module("ipfs_datasets_py.logic.backends.installers.isabelle_installation")
    monkeypatch.setattr(legacy, "read_version_banner", lambda *a, **kw: pytest.fail("legacy version probe"))
    monkeypatch.setattr(legacy, "probe_theory_processor", lambda *a, **kw: pytest.fail("legacy help probe"))
    monkeypatch.setattr(legacy, "ensure_isabelle", lambda *a, **kw: pytest.fail("legacy installer"))
    monkeypatch.delenv("IPFS_DATASETS_PY_ISABELLE_INSTALL_COMMAND", raising=False)
    return module


@pytest.mark.parametrize("install_root", [None, "/isolated/install"])
@pytest.mark.parametrize("smoke", [False, True])
def test_setup_install_reuses_final_bounded_preparation_without_extra_probes(
    installation, monkeypatch, install_root, smoke,
):
    calls = []
    monkeypatch.setattr(installation, "ensure_isabelle_installation",
        lambda **kw: calls.append(kw) or installed())
    monkeypatch.setattr(preparation, "prepare_isabelle_runtime",
        lambda **kw: pytest.fail("duplicated preparation or preliminary probe"))
    monkeypatch.setattr(lazy, "lazy_install_prover", lambda *a, **kw: pytest.fail("legacy lazy setup"))
    result = setup.ensure_isabelle_ready(install=True, smoke=smoke, timeout=8, install_root=install_root)
    assert result["ready"] and result["installation"]["successful"]
    assert result["readiness_level"] == "kernel_smoke"
    assert result["capability"]["executables"]["isabelle"]["path"] == installed().executable
    assert result["bounded_preparation"]["grants_proof_authority"] is False
    assert len(calls) == 1
    assert 0 < calls[0].pop("timeout_seconds") <= 8
    assert calls == [{"yes": True, "strict": False, "install_root": install_root,
                     "build_hol": False, "allow_download": True}]
    assert (result["smoke"] is not None) is smoke
    if smoke:
        assert result["smoke"]["accepted"]


@pytest.mark.parametrize("historical", [False, True])
def test_setup_refuses_failed_publication_even_with_successful_old_preparation(
    installation, monkeypatch, historical,
):
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw:
        installed(usable=False, preparation_data=prepared().to_dict() if historical else {}))
    monkeypatch.setattr(preparation, "prepare_isabelle_runtime", lambda **kw: pytest.fail("retry on failure"))
    result = setup.ensure_isabelle_ready(install=True, smoke=True)
    assert not result["ready"] and not result["capability"]["available"]
    assert not result["installation"]["successful"] and not result["smoke"]["accepted"]
    assert result["capability"]["unavailable_reason"] == "publication_validation_failed"


def test_setup_success_status_without_final_observation_does_not_establish_readiness(installation, monkeypatch):
    monkeypatch.setattr(installation, "ensure_isabelle_installation",
                        lambda **kw: installed(preparation_data={}))
    result = setup.ensure_isabelle_ready(install=True)
    assert not result["ready"] and not result["capability"]["available"]


@pytest.mark.parametrize("allow_install", [False, True])
def test_setup_build_is_one_transaction_with_final_preparation_reused(installation, monkeypatch, allow_install):
    clock = [10.0]
    calls = []
    monkeypatch.setattr(setup.time, "monotonic", lambda: clock[0])

    def install(**options):
        calls.append(options)
        clock[0] += 4
        return installed(build=hol_build())

    monkeypatch.setattr(installation, "ensure_isabelle_installation", install)
    monkeypatch.setattr(base, "run_bounded_process", lambda *a, **kw: pytest.fail("legacy standalone build"))
    monkeypatch.setattr(preparation, "prepare_isabelle_runtime", lambda **kw: pytest.fail("duplicated preparation"))
    result = setup.ensure_isabelle_ready(install=allow_install, build_hol=True, smoke=True, timeout=10)
    assert result["ready"] and result["smoke"]["accepted"]
    assert calls == [{"yes": True, "strict": False, "install_root": None,
        "timeout_seconds": 10, "build_hol": True, "allow_download": allow_install}]
    assert result["hol_build"]["returncode"] == 0 and result["hol_build"]["error"] is None
    assert result["hol_build"]["build"]["persistent_heap_published"] is True
    assert "unpublished staged system heaps" in result["hol_build_scope"]
    assert "One setup deadline" in result["timeout_scope"]


@pytest.mark.parametrize("install,build", [(True, False), (False, True), (True, True)])
def test_setup_expiration_preserves_committed_history_without_claiming_current_readiness(
    installation, monkeypatch, install, build,
):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(setup.time, "monotonic", lambda: clock[0])

    def finish(**options):
        calls.append(options)
        clock[0] = 10.0
        return installed(build=hol_build() if build else None)

    monkeypatch.setattr(installation, "ensure_isabelle_installation", finish)
    monkeypatch.setattr(base, "run_bounded_process", lambda *a, **kw: pytest.fail("legacy standalone build"))
    monkeypatch.setattr(preparation, "prepare_isabelle_runtime", lambda **kw: pytest.fail("late preparation"))
    result = setup.ensure_isabelle_ready(install=install, build_hol=build, smoke=True, timeout=10)
    assert not result["ready"] and not result["capability"]["available"]
    assert result["readiness_level"] == "setup_deadline_exceeded"
    assert result["installation"]["successful"]  # historical committed installation remains reported
    assert len(calls) == 1 and calls[0]["timeout_seconds"] == 10
    assert not result["smoke"]["accepted"]


def test_build_only_missing_verified_cache_is_blocked_without_fallback(installation, monkeypatch):
    calls = []
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw:
        calls.append(kw) or installed(usable=False, preparation_data={}, status="blocked",
                                     reasons=["verified_archive_required"]))
    monkeypatch.setattr(preparation, "prepare_isabelle_runtime", lambda **kw: pytest.fail("fallback preparation"))
    monkeypatch.setattr(base, "run_bounded_process", lambda *a, **kw: pytest.fail("legacy fallback build"))
    result = setup.ensure_isabelle_ready(build_hol=True, smoke=True)
    assert not result["ready"] and not result["smoke"]["accepted"]
    assert result["capability"]["unavailable_reason"] == "verified_archive_required"
    assert result["hol_build"]["returncode"] is None
    assert result["hol_build"]["error"] == "verified_archive_required"
    assert len(calls) == 1 and calls[0]["allow_download"] is False
    assert calls[0]["yes"] is True and calls[0]["build_hol"] is True


@pytest.mark.parametrize("build", [None, {}, hol_build(succeeded=False), hol_build(published=False)])
def test_successful_smoke_does_not_promote_missing_or_unpublished_requested_build(
    installation, monkeypatch, build,
):
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw: installed(build=build))
    result = setup.ensure_isabelle_ready(build_hol=True, smoke=True)
    assert not result["ready"] and not result["capability"]["available"]
    assert not result["smoke"]["accepted"] and not result["installation"]["successful"]
    assert result["capability"]["unavailable_reason"] == "persistent_hol_build_not_published"


@pytest.mark.parametrize("install,build,budget", [(False, False, 120), (True, False, 600),
                                                  (False, True, 3600), (True, True, 3600)])
@pytest.mark.parametrize("requested", [None, 12.5])
def test_timeout_default_depends_on_operation_and_explicit_budget_is_preserved(
    installation, monkeypatch, install, build, budget, requested,
):
    calls = []
    monkeypatch.setattr(setup.time, "monotonic", lambda: 5.0)
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw:
        calls.append(kw) or installed(build=hol_build() if build else None))
    monkeypatch.setattr(preparation, "prepare_isabelle_runtime", lambda **kw:
        calls.append(kw) or prepared())
    result = setup.ensure_isabelle_ready(install=install, build_hol=build, timeout=requested)
    assert result["ready"] and len(calls) == 1
    assert calls[0]["timeout_seconds"] == (budget if requested is None else requested)


@pytest.mark.parametrize("timeout", [False, True, 0, -1, float("inf"), float("nan"), 3601, "120"])
def test_invalid_timeout_rejected_before_any_work(installation, monkeypatch, timeout):
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw: pytest.fail("invalid budget admitted"))
    with pytest.raises(ValueError, match="timeout must be finite"):
        setup.ensure_isabelle_ready(build_hol=True, timeout=timeout)


@pytest.mark.parametrize("yes,force", [(False, False), (False, True), (True, False), (True, True)])
def test_bridge_forwards_actual_owner_and_limits_without_legacy_discovery(installation, monkeypatch, yes, force):
    calls = []
    parent, scheduler, cancellation = object(), object(), object()
    monkeypatch.setattr(bridge, "_which", lambda *a: pytest.fail("unadmitted preliminary discovery"))
    monkeypatch.setattr(bridge, "_external_prover_root", lambda: "/configured/root")
    monkeypatch.setattr(installation, "ensure_isabelle_installation",
        lambda **kw: calls.append(kw) or installed(usable=yes))
    assert bridge.ensure_isabelle(yes=yes, strict=False, force=force, timeout_seconds=17,
        parent_lease=parent, scheduler=scheduler, cancellation=cancellation, memory_mb=3072) is yes
    assert calls == [{"yes": yes, "strict": False, "force": force, "on_progress": None,
        "install_root": "/configured/root", "timeout_seconds": 17, "parent_lease": parent,
        "scheduler": scheduler, "cancellation": cancellation, "memory_mb": 3072}]


@pytest.mark.parametrize("strict", [False, True])
def test_bridge_preserves_strict_error_policy(installation, monkeypatch, strict):
    def fail(**kw):
        raise ValueError("bounded installation refused")
    monkeypatch.setattr(installation, "ensure_isabelle_installation", fail)
    if strict:
        with pytest.raises(ValueError, match="bounded installation refused"):
            bridge.ensure_isabelle(yes=True, strict=True)
    else:
        assert not bridge.ensure_isabelle(yes=True, strict=False)


def test_custom_override_is_explicit_and_labeled_legacy(installation, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_ISABELLE_INSTALL_COMMAND", "owner-selected-command")
    monkeypatch.setattr(bridge, "_run_custom_solver_installer", lambda *a, **kw: True)
    monkeypatch.setattr(bridge, "_which", lambda name: "/custom/isabelle")
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw: pytest.fail("ordinary install"))
    messages = []
    assert bridge.ensure_isabelle(yes=True, strict=True, on_progress=lambda phase, message: messages.append(message))
    assert any("legacy uncontained override" in message for message in messages)


def test_custom_override_cannot_run_without_yes(installation, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_ISABELLE_INSTALL_COMMAND", "owner-selected-command")
    monkeypatch.setattr(bridge, "_run_custom_solver_installer", lambda *a, **kw: pytest.fail("unauthorized custom install"))
    monkeypatch.setattr(installation, "ensure_isabelle_installation", lambda **kw: installed(usable=False))
    assert not bridge.ensure_isabelle(yes=False, strict=True)


def test_registry_and_ordinary_lazy_dispatch_select_bounded_installer(installation, monkeypatch, tmp_path):
    entry = registry.get_installer_entry("isabelle")
    assert entry.module_path == installation.__name__
    assert entry.ensure_name == "ensure_isabelle_installation"
    calls = []
    monkeypatch.setattr(installation, "ensure_isabelle_installation",
        lambda **kw: calls.append(kw) or installed(status="already_present"))
    # Ordinary first use takes the compatibility bridge; explicit reviewed
    # installation resolves the registry entry above. Both select this owner.
    assert lazy._resolve_reviewed_installer("isabelle") is None
    monkeypatch.setattr(lazy, "prover_lazy_install_enabled", lambda _: True)
    monkeypatch.setattr(lazy, "_cross_process_install_lock", lambda _: nullcontext())
    monkeypatch.setattr(bridge, "_external_prover_root", lambda: tmp_path)
    monkeypatch.setattr(bridge, "_which", lambda *a: pytest.fail("legacy lazy discovery"))
    monkeypatch.setattr(lazy, "clear_feature_detection_cache", lambda: None)
    monkeypatch.setattr(lazy, "import_time_install_forbidden", lambda: False)
    assert lazy._lazy_install_prover_once("isabelle", force=True, strict=True)
    assert calls == [{"yes": True, "strict": True, "force": True, "on_progress": None,
        "install_root": tmp_path, "timeout_seconds": 600, "parent_lease": None,
        "scheduler": None, "cancellation": None, "memory_mb": 2048}]


def test_explicit_reviewed_install_uses_new_registry_entry_without_proof_certification(
    installation, monkeypatch, tmp_path,
):
    calls = []
    monkeypatch.setattr(installation, "ensure_isabelle_installation",
        lambda **kw: calls.append(kw) or installed(status="already_present"))
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: tmp_path)
    monkeypatch.setattr(lazy, "_install_lock", lambda _: nullcontext())
    monkeypatch.setattr(lazy, "_cross_process_install_lock", lambda _: nullcontext({}))
    result = lazy.execute_reviewed_install("isabelle", allow_install=True, strict=True)
    assert result["available"] and result["install_attempted"]
    assert result["authority"] == "none" and result["certified"] is False
    assert result["plan"]["installer_module"] == installation.__name__
    assert result["plan"]["installer_callable"] == "ensure_isabelle_installation"
    assert calls == [{"yes": True, "strict": True, "force": False,
                     "on_progress": None, "install_root": str(tmp_path)}]

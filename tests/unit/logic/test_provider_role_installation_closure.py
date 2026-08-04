"""Unit gates for installer-role closure (FVT-G227 / FVT-095).

Proves FormalVerificationInstallerRegistry@1 entries carry public roles, that
every entry resolves to a real ensure_* callable (never placeholder dispatch),
and that import/inventory/dry-run/offline paths stay non-mutating.
"""

from __future__ import annotations

import importlib
import socket
import subprocess
import urllib.request

import pytest

from ipfs_datasets_py.logic.backends.installers import registry as installer_registry
from ipfs_datasets_py.logic.backends.installers.registry import (
    CLOSED_DISPATCH_SURFACES,
    DISPATCH_ADVISOR,
    DISPATCH_ARTIFACT_INTAKE,
    DISPATCH_COMPATIBILITY_LOOKUP,
    DISPATCH_INVENTORY,
    DISPATCH_VERIFICATION,
    INSTALLER_ENTRY_SCHEMA,
    InstallerPublicRole,
    InstallerRegistryError,
    SUPPORT_ONLY_TOOL_IDS,
    assert_installer_entries_resolve_to_callables,
    assert_registry_aligned_with_lock,
    build_default_installer_registry,
    get_installer_entry,
    list_installer_entries,
    list_installer_entries_by_role,
    resolve_installer_implementation,
    support_only_installer_tool_ids,
)
from ipfs_datasets_py.logic.external_provers import lazy_installer
from ipfs_datasets_py.logic.verification_api import (
    LogicVerificationAPI,
    VerificationStatus,
)


FOCUS_TOOLS = {
    "ergoai": InstallerPublicRole.ADVISOR,
    "symbolicai": InstallerPublicRole.ADVISOR,
    "runtime-mtl-external": InstallerPublicRole.AUTHORITY,
    "souffle": InstallerPublicRole.SHADOW,
    "secpal": InstallerPublicRole.ARCHIVAL_INTAKE,
    "stack": InstallerPublicRole.SUPPORT,
    "temurin-jdk": InstallerPublicRole.SUPPORT,
    "maude": InstallerPublicRole.SUPPORT,
    "opam": InstallerPublicRole.SUPPORT,
}


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    installer_registry.reset_default_installer_registry()
    yield
    installer_registry.reset_default_installer_registry()


def test_default_registry_includes_role_closure_tools() -> None:
    reg = build_default_installer_registry()
    tool_ids = set(reg.list_tool_ids())
    assert FOCUS_TOOLS.keys() <= tool_ids
    assert "temurin-jdk" in tool_ids
    assert SUPPORT_ONLY_TOOL_IDS == frozenset(
        {"stack", "temurin-jdk", "maude", "opam"}
    )
    assert support_only_installer_tool_ids(registry=reg) == SUPPORT_ONLY_TOOL_IDS


@pytest.mark.parametrize("tool_id,role", sorted(FOCUS_TOOLS.items()))
def test_focus_tools_have_expected_public_roles(
    tool_id: str, role: InstallerPublicRole
) -> None:
    entry = get_installer_entry(tool_id)
    assert entry.public_role is role
    assert entry.schema_version == INSTALLER_ENTRY_SCHEMA
    assert set(entry.dispatch_surfaces) <= CLOSED_DISPATCH_SURFACES
    payload = entry.to_dict()
    assert payload["public_role"] == role.value
    assert payload["support_only"] is (role is InstallerPublicRole.SUPPORT)
    assert DISPATCH_INVENTORY in entry.dispatch_surfaces
    if role is InstallerPublicRole.SUPPORT:
        assert entry.semantic_axis_applicable is False
        assert entry.authority_axis_applicable is False
        assert entry.public_verification_applicable is False
        assert DISPATCH_VERIFICATION not in entry.dispatch_surfaces
        assert DISPATCH_ADVISOR not in entry.dispatch_surfaces
    elif role is InstallerPublicRole.ADVISOR:
        assert DISPATCH_ADVISOR in entry.dispatch_surfaces
        assert DISPATCH_VERIFICATION not in entry.dispatch_surfaces
        assert entry.public_verification_applicable is False
        assert entry.authority_axis_applicable is False
    elif role is InstallerPublicRole.ARCHIVAL_INTAKE:
        assert DISPATCH_ARTIFACT_INTAKE in entry.dispatch_surfaces
        assert DISPATCH_COMPATIBILITY_LOOKUP in entry.dispatch_surfaces
        assert DISPATCH_VERIFICATION not in entry.dispatch_surfaces
        assert entry.is_live_verification_provider is False
    elif role is InstallerPublicRole.SHADOW:
        assert DISPATCH_VERIFICATION in entry.dispatch_surfaces
        assert entry.authority_axis_applicable is False
        assert entry.is_live_verification_provider is True
    else:
        assert DISPATCH_VERIFICATION in entry.dispatch_surfaces
        assert entry.is_live_verification_provider is True


def test_every_registry_entry_resolves_to_real_callable_not_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("callable resolution must not run commands or network I/O")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    resolved = assert_installer_entries_resolve_to_callables()
    assert len(resolved) == len(list_installer_entries())
    for item in resolved:
        assert item["placeholder"] is False
        assert item["callable_resolved"] is True
        assert item["ensure_name"].startswith("ensure_")
        assert not item["ensure_name"].endswith("_placeholder")
        # Re-check without import (metadata path).
        meta = resolve_installer_implementation(
            item["tool_id"], import_callable=False
        )
        assert meta["callable_resolved"] is False
        assert meta["module_path"] == item["module_path"]


def test_placeholder_ensure_name_is_refused() -> None:
    from ipfs_datasets_py.logic.backends.installers.registry import (
        FormalVerificationInstallerRegistry,
        InstallerEntry,
        InstallerPluginFamily,
    )

    entry = InstallerEntry(
        tool_id="fake-tool",
        family=InstallerPluginFamily.SOLVER,
        ensure_name="ensure_fake_tool",
        license="MIT",
        source="https://example.invalid/fake",
        identity_kind="test",
    )
    private = FormalVerificationInstallerRegistry(
        plugins=build_default_installer_registry().plugins,
        entries=(entry,),
    )
    meta = resolve_installer_implementation(
        "fake-tool", import_callable=False, registry=private
    )
    assert meta["placeholder"] is False

    placeholder_entry = InstallerEntry(
        tool_id="fake-placeholder",
        family=InstallerPluginFamily.SOLVER,
        ensure_name="ensure_z3",
        license="MIT",
        source="https://example.invalid/fake",
        identity_kind="test",
    )
    object.__setattr__(placeholder_entry, "ensure_name", "ensure_placeholder")
    private_placeholder = FormalVerificationInstallerRegistry(
        plugins=build_default_installer_registry().plugins,
        entries=(placeholder_entry,),
    )
    with pytest.raises(InstallerRegistryError, match="placeholder"):
        resolve_installer_implementation(
            "fake-placeholder",
            import_callable=False,
            registry=private_placeholder,
        )


def test_registry_aligned_with_lock_including_temurin() -> None:
    assert_registry_aligned_with_lock()
    entry = get_installer_entry("temurin-jdk")
    assert entry.ensure_name == "ensure_temurin_jdk"
    assert entry.family.value == "advisors"
    assert entry.support_only is True


def test_list_entries_by_role_partitions_closed_set() -> None:
    support = list_installer_entries_by_role(InstallerPublicRole.SUPPORT)
    advisors = list_installer_entries_by_role("advisor")
    archival = list_installer_entries_by_role(InstallerPublicRole.ARCHIVAL_INTAKE)
    assert {item.tool_id for item in support} == set(SUPPORT_ONLY_TOOL_IDS)
    assert {"ergoai", "symbolicai"} <= {item.tool_id for item in advisors}
    assert {item.tool_id for item in archival} == {"secpal"}


def test_import_inventory_dry_run_offline_never_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("side-effect free path opened a process or network socket")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request, "urlretrieve", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    original = importlib.import_module
    plugin_calls: list[str] = []

    def guarded(name: str, *args, **kwargs):
        if ".logic.backends.installers." in name and not name.endswith(".registry"):
            plugin_calls.append(name)
            raise AssertionError(f"plugin import forbidden: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(lazy_installer.importlib, "import_module", guarded)

    inventory = lazy_installer.reviewed_installer_inventory()
    assert {item["tool_id"] for item in inventory} >= set(FOCUS_TOOLS)
    for item in inventory:
        assert "public_role" in item
        assert "dispatch_surfaces" in item

    for tool_id in FOCUS_TOOLS:
        plan = lazy_installer.plan_reviewed_install(tool_id)
        assert plan["discovery_imports_plugin"] is False
        assert plan["installer_callable"].startswith("ensure_")
        denied = lazy_installer.execute_reviewed_install(tool_id)
        dry = lazy_installer.execute_reviewed_install(tool_id, dry_run=True)
        offline = lazy_installer.execute_reviewed_install(
            tool_id, allow_install=True, offline=True
        )
        assert denied["status"] == "authorization_required"
        assert dry["status"] == "planned"
        assert offline["status"] == "blocked"
        assert denied["install_attempted"] is False
        assert dry["install_attempted"] is False
        assert offline["install_attempted"] is False

    api = LogicVerificationAPI()
    for tool_id in FOCUS_TOOLS:
        response = api.install_provider(tool_id, dry_run=True)
        assert response.status is VerificationStatus.DECLARATIVE
        assert response.result["install_attempted"] is False
        assert response.result["provider_role"]["provider_id"] == tool_id

    assert plugin_calls == []


def test_api_role_metadata_on_support_and_secpal_install_plans() -> None:
    api = LogicVerificationAPI()
    for tool_id in SUPPORT_ONLY_TOOL_IDS:
        response = api.install_provider(tool_id, dry_run=True)
        assert response.result["support_only"] is True
        assert response.result["semantic_axis_applicable"] is False
        assert response.result["authority_axis_applicable"] is False
        assert response.result["public_verification_applicable"] is False
    secpal = api.install_provider("secpal", dry_run=True)
    assert secpal.result["live_verification_provider"] is False
    assert secpal.result["artifact_intake_only"] is True
    assert secpal.result["provider_role"]["public_role"] == "archival_intake"


def test_missing_callable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyModule:
        pass

    original = importlib.import_module

    def fake(name: str, *args, **kwargs):
        if name.endswith(".installers.solver"):
            return EmptyModule()
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)
    with pytest.raises(InstallerRegistryError, match="does not export callable"):
        resolve_installer_implementation("z3", import_callable=True)

"""Datasets-owned cold bridge for the optional proof-reuse pytest plugin.

The bridge is intentionally tiny: pytest can load it from this distribution's
``pytest11`` entry point even when the accelerator is not installed.  If the
accelerator is absent it contributes no hooks; if importing its actual plugin
fails for any other reason, the error is deliberately allowed to surface.
"""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Any


ACCELERATOR_PLUGIN_MODULE = "ipfs_accelerate_py.testing.proof_reuse.plugin"
_OPTIONAL_TOP_LEVEL_PACKAGE = "ipfs_accelerate_py"
PLUGIN_NAME = "ipfs-proof-reuse"


def _is_absent_namespace(spec: Any) -> bool:
    """Return whether *spec* describes only a PEP 420 namespace root.

    An empty, uninitialised gitlink is visible to Python as a namespace package.
    ``NamespaceLoader`` is not a stable absence signal, so absence is classified
    by the PEP 420 fields themselves.  A regular package always has an origin.
    """

    return (
        spec is not None
        and spec.origin is None
        and spec.submodule_search_locations is not None
    )


def _accelerator_is_absent_namespace() -> bool:
    """Return whether no accelerator implementation plugin is discoverable.

    A namespace root alone is not enough to suppress an import failure.  A
    separately installed namespace portion may provide the proof-reuse plugin;
    if that plugin then fails while importing, its failure is actionable and
    must remain visible.  Only an absent plugin target beneath a namespace root
    represents the uninitialised nested-gitlink case.
    """

    try:
        spec = importlib.util.find_spec(_OPTIONAL_TOP_LEVEL_PACKAGE)
    except (AttributeError, ImportError, ValueError):
        # Classification failures are not optional absence.  Retain the
        # original plugin import failure so incomplete installs stay visible.
        return False
    if spec is None:
        return True
    if not _is_absent_namespace(spec):
        return False

    try:
        return importlib.util.find_spec(ACCELERATOR_PLUGIN_MODULE) is None
    except ModuleNotFoundError as error:
        # ``find_spec`` raises when an intermediate namespace child (normally
        # ``testing``) does not exist.  That is still the empty-gitlink case.
        # Any unrelated failure is a real dependency/import problem.
        if _is_optional_chain_miss(error):
            return True
        raise


def _is_optional_chain_miss(error: ModuleNotFoundError) -> bool:
    """Return whether an import miss names the accelerator module chain."""

    missing = error.name or ""
    return missing == ACCELERATOR_PLUGIN_MODULE or ACCELERATOR_PLUGIN_MODULE.startswith(
        f"{missing}."
    )


def _load_accelerator_plugin() -> ModuleType | None:
    """Load the plugin while distinguishing absence from a broken install.

    A missing top-level distribution and an empty PEP 420 namespace/gitlink are
    optional absence.  Once a regular accelerator package exists, a missing
    ``testing`` hierarchy is an incomplete installation and must be visible.
    Missing transitive dependencies from a found plugin are always visible.
    """

    try:
        return importlib.import_module(ACCELERATOR_PLUGIN_MODULE)
    except ModuleNotFoundError as error:
        if _is_optional_chain_miss(error) and _accelerator_is_absent_namespace():
            return None
        raise


def _register_accelerator(pluginmanager: Any) -> None:
    """Load and register the implementation once during pytest startup."""

    if pluginmanager.get_plugin(PLUGIN_NAME) is not None:
        return
    if pluginmanager.get_plugin(ACCELERATOR_PLUGIN_MODULE) is not None:
        return

    accelerator_plugin = _load_accelerator_plugin()
    if accelerator_plugin is None:
        return
    is_registered = getattr(pluginmanager, "is_registered", None)
    if is_registered is not None and is_registered(accelerator_plugin):
        return
    pluginmanager.register(accelerator_plugin, PLUGIN_NAME)


def pytest_addoption(parser: Any, pluginmanager: Any) -> None:
    """Register early enough for accelerator-defined command-line options."""

    del parser
    _register_accelerator(pluginmanager)


def pytest_configure(config: Any) -> None:
    """Cover plugin managers which configure without adding options first."""

    _register_accelerator(config.pluginmanager)

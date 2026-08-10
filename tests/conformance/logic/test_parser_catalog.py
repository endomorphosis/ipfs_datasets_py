"""Conformance: lazy inert parser catalog projection (LFP-040).

Acceptance:

* Every individual parser contributes an inert local descriptor
* Descriptors never edit a shared registry
* Final catalog has no duplicate / eager / unknown entry
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DEFAULT_REGISTRY,
)
from ipfs_datasets_py.logic.parsers.catalog import (
    CATALOG_TASK_ID,
    DEFAULT_PARSER_CATALOG,
    LOGIC_PARSER_CATALOG_INTERFACE,
    PARSER_CONTRIBUTION_MODULES,
    DuplicateParserCatalogEntryError,
    EagerParserCatalogEntryError,
    LocalParserContribution,
    LogicParserCatalog,
    UnknownParserCatalogEntryError,
    build_parser_catalog,
    collect_local_parser_contributions,
)
from ipfs_datasets_py.logic.syntax_core.registry import (
    LogicParserDescriptor,
    LogicParserRegistry,
    ParserKey,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_parser_catalog_interface_identity() -> None:
    catalog = DEFAULT_PARSER_CATALOG
    assert catalog.INTERFACE == LOGIC_PARSER_CATALOG_INTERFACE
    assert catalog.INTERFACE == "LogicParserCatalog@1"
    assert catalog.task_id == CATALOG_TASK_ID
    assert catalog.task_id == "LFP-040"
    payload = catalog.to_dict()
    assert payload["interface"] == "LogicParserCatalog@1"
    restored = LogicParserCatalog.from_dict(payload)
    assert restored.descriptor_ids == catalog.descriptor_ids


def test_every_parser_module_contributes_inert_local_descriptor() -> None:
    contributions = collect_local_parser_contributions()
    assert contributions
    modules = {item.module for item in contributions}
    assert modules == set(PARSER_CONTRIBUTION_MODULES)

    catalog = build_parser_catalog(validate=True)
    assert catalog.is_inert() is True
    assert catalog.is_eager() is False
    assert catalog.mutates_shared_registry() is False

    for item in catalog:
        assert item.descriptor.metadata.get("inert") is True
        assert item.descriptor.metadata.get("lazy") is True
        assert item.descriptor.metadata.get("eager") is not True
        assert item.descriptor.metadata.get("shared_registry_mutated") is not True
        assert item.descriptor.implementation
        assert item.descriptor.implementation.startswith(
            "ipfs_datasets_py.logic.parsers."
        )
        # Implementation path is a label only — family modules stay unloaded
        # by the catalog module itself.
        assert item.module in PARSER_CONTRIBUTION_MODULES


def test_catalog_does_not_edit_shared_registry() -> None:
    registry = LogicParserRegistry()
    before_len = len(registry)
    before_ids = {item.descriptor_id for item in registry.descriptors()}

    catalog = build_parser_catalog(validate=True)
    assert catalog.mutates_shared_registry() is False
    assert len(catalog) >= len(PARSER_CONTRIBUTION_MODULES)

    assert len(registry) == before_len
    after_ids = {item.descriptor_id for item in registry.descriptors()}
    assert after_ids == before_ids
    # Catalog descriptors are not auto-registered into the shared registry.
    for descriptor_id in catalog.descriptor_ids:
        assert descriptor_id not in after_ids


def test_catalog_rejects_duplicate_descriptor_ids() -> None:
    base = collect_local_parser_contributions()
    duplicate = base[0]
    with pytest.raises(DuplicateParserCatalogEntryError, match="duplicate"):
        LogicParserCatalog(contributions=base + (duplicate,))


def test_catalog_rejects_duplicate_keys() -> None:
    first = collect_local_parser_contributions()[0]
    twin = LocalParserContribution(
        module=first.module,
        descriptor=LogicParserDescriptor(
            descriptor_id="parser:local:duplicate-key-twin",
            key=first.descriptor.key,
            family_id=first.family_id,
            features=first.descriptor.features,
            implementation=first.descriptor.implementation,
            metadata={
                "inert": True,
                "lazy": True,
                "eager": False,
                "shared_registry_mutated": False,
            },
        ),
    )
    with pytest.raises(DuplicateParserCatalogEntryError, match="duplicate parser key"):
        LogicParserCatalog(contributions=(first, twin))


def test_catalog_rejects_eager_contribution() -> None:
    first = collect_local_parser_contributions()[0]
    with pytest.raises(EagerParserCatalogEntryError, match="eager"):
        LocalParserContribution(
            module=first.module,
            descriptor=LogicParserDescriptor(
                descriptor_id="parser:local:eager-bad",
                key=ParserKey(
                    notation_id="eager_notation",
                    notation_version="1.0.0",
                    semantic_profile_id="eager_profile",
                ),
                family_id="first_order",
                features=("parse",),
                implementation="ipfs_datasets_py.logic.parsers.fol:CanonicalFOLParser",
                metadata={
                    "inert": True,
                    "lazy": True,
                    "eager": True,
                    "shared_registry_mutated": False,
                },
            ),
        )


def test_catalog_rejects_unknown_family() -> None:
    with pytest.raises(UnknownParserCatalogEntryError, match="unknown family"):
        LogicParserCatalog(
            contributions=(
                LocalParserContribution(
                    module="fol",
                    descriptor=LogicParserDescriptor(
                        descriptor_id="parser:local:unknown-family",
                        key=ParserKey(
                            notation_id="unknown_family_notation",
                            notation_version="1.0.0",
                            semantic_profile_id="classical",
                        ),
                        family_id="not_a_registered_family_xyz",
                        features=("parse",),
                        implementation=(
                            "ipfs_datasets_py.logic.parsers.fol:CanonicalFOLParser"
                        ),
                        metadata={
                            "inert": True,
                            "lazy": True,
                            "eager": False,
                            "shared_registry_mutated": False,
                        },
                    ),
                ),
            )
        )


def test_catalog_rejects_unknown_module() -> None:
    with pytest.raises(UnknownParserCatalogEntryError, match="unknown parser contribution"):
        LocalParserContribution(
            module="not_a_parser_module",
            descriptor=LogicParserDescriptor(
                descriptor_id="parser:local:bad-module",
                key=ParserKey(
                    notation_id="bad_module_notation",
                    notation_version="1.0.0",
                    semantic_profile_id="classical",
                ),
                family_id="first_order",
                features=("parse",),
                implementation="ipfs_datasets_py.logic.parsers.fol:CanonicalFOLParser",
                metadata={
                    "inert": True,
                    "lazy": True,
                    "eager": False,
                    "shared_registry_mutated": False,
                },
            ),
        )


def test_catalog_families_are_baseline_or_registry() -> None:
    catalog = DEFAULT_PARSER_CATALOG
    allowed = set(BASELINE_FAMILY_IDS) | set(DEFAULT_REGISTRY.families)
    for item in catalog:
        assert item.family_id in allowed


def test_catalog_validate_closure_requires_all_modules() -> None:
    partial = tuple(
        item
        for item in collect_local_parser_contributions()
        if item.module != "fol"
    )
    catalog = LogicParserCatalog(contributions=partial)
    with pytest.raises(UnknownParserCatalogEntryError, match="missing contributions"):
        catalog.validate_closure()


def test_catalog_module_does_not_import_family_parser_implementations() -> None:
    """Importing catalog must not eagerly load family frontend modules."""

    parent_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "ipfs_datasets_py.logic.parsers.catalog"
        or name.startswith("ipfs_datasets_py.logic.parsers.catalog.")
    }
    script = textwrap.dedent(
        """
        import importlib
        import sys

        prefixes = (
            "ipfs_datasets_py.logic.parsers.fol",
            "ipfs_datasets_py.logic.parsers.smtlib",
            "ipfs_datasets_py.logic.parsers.tptp",
            "ipfs_datasets_py.logic.parsers.modal",
            "ipfs_datasets_py.logic.parsers.temporal",
        )
        catalog_mod = importlib.import_module("ipfs_datasets_py.logic.parsers.catalog")
        catalog = catalog_mod.build_parser_catalog(validate=True)
        assert catalog.is_inert() is True
        loaded = {
            name
            for name in sys.modules
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
        }
        assert loaded == set(), sorted(loaded)
        print("ok")
        """
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(REPO_ROOT), env.get("PYTHONPATH", ""))
        if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok" in completed.stdout
    for name, module in parent_modules.items():
        assert sys.modules.get(name) is module


def test_default_catalog_round_trip() -> None:
    catalog = DEFAULT_PARSER_CATALOG
    restored = LogicParserCatalog.from_dict(catalog.to_dict())
    assert restored.descriptor_ids == catalog.descriptor_ids
    assert restored.modules == catalog.modules
    assert restored.is_inert() is True

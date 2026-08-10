"""Publication tests for LogicSyntaxCore@1 and LazyParserPublication@1 (LFP-016).

Evidence subset:

* cold import starts no network / process / model / installer
* canonical export list is complete and lazy
* lazy parser descriptors are inert local contracts
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.parsers import (
    DEFAULT_LAZY_PARSER_PUBLICATION,
    LAZY_PARSER_PUBLICATION_INTERFACE,
    LazyParserPublication,
    local_parser_descriptors,
    publish_lazy_parser_catalog,
)
from ipfs_datasets_py.logic.syntax_core import (
    LOGIC_SYNTAX_CORE_INTERFACE,
    LOGIC_SYNTAX_CORE_VERSION,
)

# tests/unit/logic/syntax_core -> nested ipfs_datasets_py package root
REPO_ROOT = Path(__file__).resolve().parents[4]


def test_logic_syntax_core_interface_and_version() -> None:
    assert LOGIC_SYNTAX_CORE_INTERFACE == "LogicSyntaxCore@1"
    assert LOGIC_SYNTAX_CORE_VERSION == "1.0.0"


def test_canonical_export_list_is_complete_and_lazy() -> None:
    parent_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "ipfs_datasets_py.logic.syntax_core"
        or name.startswith("ipfs_datasets_py.logic.syntax_core.")
    }
    script = textwrap.dedent(
        """
        import importlib
        import sys

        core = importlib.import_module("ipfs_datasets_py.logic.syntax_core")
        loaded_leaves = {
            name
            for name in sys.modules
            if name.startswith("ipfs_datasets_py.logic.syntax_core.")
            and name != "ipfs_datasets_py.logic.syntax_core"
        }
        assert not any(
            leaf.endswith(suffix)
            for leaf in loaded_leaves
            for suffix in (
                ".elaboration",
                ".codec",
                ".lexer",
                ".algebra",
                ".registry",
            )
        ), sorted(loaded_leaves)
        required = {
            "LOGIC_SYNTAX_CORE_INTERFACE",
            "LOGIC_SYNTAX_CORE_VERSION",
            "SourceDocument",
            "LogicCST",
            "TypedExpression",
            "ParseArtifact",
            "LogicSignature",
            "LogicParserRegistry",
            "ElaborationResult",
            "TypedLogicCodec",
            "LogicExpressionAlgebra",
            "BoundedLexer",
            "LogicDiagnostic",
        }
        missing = sorted(required - set(core.__all__))
        assert missing == [], missing
        assert core.TypedExpression is not None
        assert core.SourceDocument is not None
        assert "TypedExpression" in core.__dict__
        assert "SourceDocument" in core.__dict__
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


def test_lazy_parser_publication_is_inert_and_local() -> None:
    publication = publish_lazy_parser_catalog()
    assert publication.INTERFACE == LAZY_PARSER_PUBLICATION_INTERFACE
    assert publication is DEFAULT_LAZY_PARSER_PUBLICATION
    assert publication.is_inert() is True

    descriptors = local_parser_descriptors()
    assert len(descriptors) >= 1
    assert publication.descriptor_ids == tuple(
        item.descriptor_id for item in descriptors
    )
    for item in descriptors:
        assert item.metadata.get("inert") is True
        assert item.metadata.get("lazy") is True
        assert item.implementation  # path label only
        # Implementation path is a string label — never imported by publication.
        assert "ipfs_datasets_py.logic.parsers." in item.implementation

    payload = publication.to_dict()
    assert payload["interface"] == "LazyParserPublication@1"
    restored = LazyParserPublication.from_dict(payload)
    assert restored.descriptor_ids == publication.descriptor_ids
    assert restored.is_inert() is True


def test_lazy_parser_publication_rejects_unknown_interface() -> None:
    with pytest.raises(ValueError, match="unknown lazy parser publication"):
        LazyParserPublication.from_dict(
            {
                "interface": "LazyParserPublication@9",
                "descriptors": [],
            }
        )


def test_cold_import_starts_no_network_process_model_or_installer() -> None:
    """Import syntax_core and parsers under side-effect guards in a subprocess."""

    script = textwrap.dedent(
        """
        import builtins
        import importlib
        import os
        import socket
        import subprocess
        import sys
        import threading

        def forbidden(operation):
            def fail(*args, **kwargs):
                raise AssertionError(f"{operation} during cold import: {args!r}")
            return fail

        # Network
        socket.create_connection = forbidden("socket.create_connection")
        socket.getaddrinfo = forbidden("socket.getaddrinfo")
        _orig_socket = socket.socket
        class GuardedSocket(_orig_socket):
            def connect(self, *a, **k):
                raise AssertionError("socket.connect during cold import")
            def connect_ex(self, *a, **k):
                raise AssertionError("socket.connect_ex during cold import")
        socket.socket = GuardedSocket

        # Process / installer
        subprocess.Popen = forbidden("subprocess.Popen")
        subprocess.run = forbidden("subprocess.run")
        subprocess.call = forbidden("subprocess.call")
        subprocess.check_call = forbidden("subprocess.check_call")
        subprocess.check_output = forbidden("subprocess.check_output")
        os.system = forbidden("os.system")
        threading.Thread.start = forbidden("threading.Thread.start")

        # Model-ish heavy imports must not appear after package import.
        banned = ("torch", "transformers", "requests", "urllib3", "httpx")

        # Drop package modules for a true cold import.
        for name in list(sys.modules):
            if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
                del sys.modules[name]

        core = importlib.import_module("ipfs_datasets_py.logic.syntax_core")
        parsers = importlib.import_module("ipfs_datasets_py.logic.parsers")

        assert core.LOGIC_SYNTAX_CORE_INTERFACE == "LogicSyntaxCore@1"
        assert "TypedExpression" in core.__all__
        assert parsers.LAZY_PARSER_PUBLICATION_INTERFACE == "LazyParserPublication@1"
        assert parsers.publish_lazy_parser_catalog().is_inert() is True

        for name in banned:
            assert name not in sys.modules, f"{name} loaded on cold import"

        # Access one export to ensure lazy resolution still stays offline.
        _ = core.SourceDocument
        _ = parsers.local_parser_descriptors()

        for name in banned:
            assert name not in sys.modules, f"{name} loaded on attribute access"

        print("ok")
        """
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pythonpath = os.pathsep.join(
        part
        for part in (str(REPO_ROOT), env.get("PYTHONPATH", ""))
        if part
    )
    env["PYTHONPATH"] = pythonpath
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

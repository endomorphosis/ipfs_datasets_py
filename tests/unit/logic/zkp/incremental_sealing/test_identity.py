"""Regression tests for deterministic IPS-007 identities."""

from __future__ import annotations

import importlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    ABSENCE_TOKEN,
    CANONICALIZATION_VERSION,
    IDENTITY_SUBSET,
    PropertyIdentity,
    RepositoryState,
    SourceArtifactIdentity,
    SourceSymbolIdentity,
    TestSelectorIdentity,
    IdentityError,
    canonical_cid,
    canonical_cid_for_bytes,
    canonicalize_relative_path,
    known_vectors,
    parse_strict_json,
    validate_profile_cid,
)

MODULE_NAME = "ipfs_datasets_py.logic.zkp.incremental_sealing.identity"


def _sample_tree_cid(*, marker: str = "clean") -> str:
    return canonical_cid(
        {
            "entries": [
                {
                    "path": "pkg/main.py",
                    "content_cid": canonical_cid_for_bytes(f"module {marker}\n".encode()),
                    "byte_length": len(f"module {marker}\n".encode()),
                }
            ]
        }
    )


def _clean_repository(**overrides: object) -> RepositoryState:
    payload = {
        "repository_id": "repo/datasets",
        "revision": "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "tree_cid": _sample_tree_cid(),
        "dirty_overlay_cid": ABSENCE_TOKEN,
        "parent_revision_ids": (),
    }
    payload.update(overrides)
    return RepositoryState(**payload)  # type: ignore[arg-type]


def test_identity_subset_and_known_vectors_cover_required_cases() -> None:
    assert IDENTITY_SUBSET == "ips/canonical-identities@1"
    vectors = known_vectors()
    assert vectors["identity_subset"] == IDENTITY_SUBSET
    required = {
        "clean_repository",
        "dirty_overlay_repository",
        "revised_repository",
        "source_artifact",
        "source_symbol",
        "test_selector",
        "property",
    }
    assert required <= set(vectors["vectors"])
    # Known vectors must be deterministic across recomputation.
    again = known_vectors()
    for name in required:
        assert vectors["vectors"][name]["identity_cid"] == again["vectors"][name]["identity_cid"]
    clean = vectors["vectors"]["clean_repository"]["identity_cid"]
    dirty = vectors["vectors"]["dirty_overlay_repository"]["identity_cid"]
    revised = vectors["vectors"]["revised_repository"]["identity_cid"]
    assert clean != dirty
    assert clean != revised
    assert dirty != revised


def test_byte_identical_states_yield_identical_ids() -> None:
    left = _clean_repository()
    right = _clean_repository()
    assert left.identity_cid() == right.identity_cid()
    assert left.to_canonical_json() == right.to_canonical_json()

    artifact_a = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/main.py",
        data=b"same-bytes",
    )
    artifact_b = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/main.py",
        data=b"same-bytes",
    )
    assert artifact_a.identity_cid() == artifact_b.identity_cid()
    assert artifact_a.content_cid == artifact_b.content_cid == canonical_cid_for_bytes(b"same-bytes")

    # Key insertion order must not affect structured identity.
    cid_left = canonical_cid({"b": 1, "a": 2})
    cid_right = canonical_cid({"a": 2, "b": 1})
    assert cid_left == cid_right


def test_content_path_schema_and_canonicalization_mutations_change_identity() -> None:
    base_repo = _clean_repository()
    base_cid = base_repo.identity_cid()

    # Content mutation (tree bytes).
    content_mutated = _clean_repository(tree_cid=_sample_tree_cid(marker="mutated"))
    assert content_mutated.identity_cid() != base_cid

    # Path mutation for artifacts.
    artifact = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/main.py",
        data=b"body",
    )
    path_mutated = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/other.py",
        data=b"body",
    )
    content_mutated_artifact = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/main.py",
        data=b"body!",
    )
    assert artifact.identity_cid() != path_mutated.identity_cid()
    assert artifact.identity_cid() != content_mutated_artifact.identity_cid()

    # Schema mutation is rejected or, if forced into payload CID, changes identity.
    with pytest.raises(IdentityError, match="schema"):
        RepositoryState(
            repository_id="repo/datasets",
            revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            tree_cid=base_repo.tree_cid,
            dirty_overlay_cid=ABSENCE_TOKEN,
            parent_revision_ids=(),
            schema="ipfs_datasets_py/logic/zkp/incremental_sealing/identity/repository-state@2",
        )
    payload = base_repo.to_canonical()
    payload["schema"] = (
        "ipfs_datasets_py/logic/zkp/incremental_sealing/identity/repository-state@2"
    )
    assert canonical_cid(payload) != base_cid

    # Canonicalization version mutation.
    canon_mutated = _clean_repository(canonicalization_version="ips/canonicalization@2")
    assert canon_mutated.identity_cid() != base_cid

    # Symbol / test / property field mutations.
    artifact_id = artifact.identity_cid()
    symbol = SourceSymbolIdentity(
        repository_id="repo/datasets",
        module_path="pkg/main.py",
        qualified_name="pkg.main:entry",
        symbol_kind="function",
        source_artifact_id=artifact_id,
    )
    symbol_path = SourceSymbolIdentity(
        repository_id="repo/datasets",
        module_path="pkg/other.py",
        qualified_name="pkg.main:entry",
        symbol_kind="function",
        source_artifact_id=artifact_id,
    )
    assert symbol.identity_cid() != symbol_path.identity_cid()

    test_sel = TestSelectorIdentity(
        repository_id="repo/datasets",
        node_id="tests/test_main.py::test_entry",
        module_path="tests/test_main.py",
        function_name="test_entry",
        parameter_case=ABSENCE_TOKEN,
    )
    test_param = TestSelectorIdentity(
        repository_id="repo/datasets",
        node_id="tests/test_main.py::test_entry[case0]",
        module_path="tests/test_main.py",
        function_name="test_entry",
        parameter_case="case0",
    )
    assert test_sel.identity_cid() != test_param.identity_cid()

    statement = canonical_cid({"statement": "P", "logic": "fol"})
    prop = PropertyIdentity(
        repository_id="repo/datasets",
        property_name="prop/a",
        statement_cid=statement,
        obligation_kind="formal_obligation",
    )
    prop_name = PropertyIdentity(
        repository_id="repo/datasets",
        property_name="prop/b",
        statement_cid=statement,
        obligation_kind="formal_obligation",
    )
    assert prop.identity_cid() != prop_name.identity_cid()


def test_round_trips_preserve_identity() -> None:
    repo = _clean_repository(
        parent_revision_ids=("rev-0000000000000000000000000000000000000001",),
    )
    restored = RepositoryState.from_canonical(json.loads(repo.to_canonical_json()))
    assert restored == repo
    assert restored.identity_cid() == repo.identity_cid()

    artifact = SourceArtifactIdentity.from_bytes(
        repository_id="repo/datasets",
        path="pkg/main.py",
        data=b"body",
    )
    assert (
        SourceArtifactIdentity.from_canonical(json.loads(artifact.to_canonical_json()))
        == artifact
    )

    symbol = SourceSymbolIdentity(
        repository_id="repo/datasets",
        module_path="pkg/main.py",
        qualified_name="pkg.main:entry",
        symbol_kind="function",
        source_artifact_id=artifact.identity_cid(),
    )
    assert SourceSymbolIdentity.from_canonical(symbol.to_canonical()) == symbol

    test_sel = TestSelectorIdentity(
        repository_id="repo/datasets",
        node_id="tests/test_main.py::test_entry",
        module_path="tests/test_main.py",
        function_name="test_entry",
        parameter_case=ABSENCE_TOKEN,
    )
    assert TestSelectorIdentity.from_canonical(test_sel.to_canonical()) == test_sel

    prop = PropertyIdentity(
        repository_id="repo/datasets",
        property_name="prop/a",
        statement_cid=canonical_cid({"statement": "P"}),
        obligation_kind="formal_obligation",
    )
    assert PropertyIdentity.from_canonical(prop.to_canonical()) == prop


def test_rejects_path_ambiguity() -> None:
    for bad in (
        "/abs/path.py",
        "pkg/../main.py",
        "pkg/./main.py",
        "pkg//main.py",
        "pkg\\main.py",
        "pkg/main.py/",
        "~/pkg/main.py",
        "C:pkg/main.py",
        "",
        " ",
    ):
        with pytest.raises(IdentityError):
            canonicalize_relative_path(bad)
    assert canonicalize_relative_path("pkg/main.py") == "pkg/main.py"


def test_rejects_pseudo_cids_floats_cycles_duplicate_keys_and_secrets() -> None:
    with pytest.raises(IdentityError, match="pseudo-CID|invalid profile CID"):
        validate_profile_cid("sha256:" + ("ab" * 32))
    with pytest.raises(IdentityError, match="pseudo-CID|invalid profile CID"):
        validate_profile_cid("cid:not-a-real-cid")
    with pytest.raises(IdentityError, match="pseudo-CID|invalid profile CID"):
        validate_profile_cid("QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG")

    with pytest.raises(IdentityError, match="float"):
        canonical_cid({"value": 1.5})
    with pytest.raises(IdentityError, match="float|non-finite"):
        canonical_cid({"value": math.nan})

    cyclic: dict[str, object] = {"a": 1}
    cyclic["self"] = cyclic
    with pytest.raises(IdentityError, match="cycle"):
        canonical_cid(cyclic)

    with pytest.raises(IdentityError, match="duplicate map key"):
        parse_strict_json('{"a":1,"a":2}')
    assert parse_strict_json('{"b":1,"a":2}') == {"b": 1, "a": 2}

    with pytest.raises(IdentityError, match="secret|nondeterministic"):
        RepositoryState.from_canonical(
            {
                **_clean_repository().to_canonical(),
                "timestamp": "now",
            }
        )
    with pytest.raises(IdentityError, match="secret|nondeterministic"):
        canonical_cid({"created_at": "2020-01-01T00:00:00Z", "x": 1})


def test_unsorted_parents_and_source_domain_enforced() -> None:
    with pytest.raises(IdentityError, match="sorted"):
        RepositoryState(
            repository_id="repo/datasets",
            revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            tree_cid=_sample_tree_cid(),
            dirty_overlay_cid=ABSENCE_TOKEN,
            parent_revision_ids=("z-parent", "a-parent"),
        )
    structured = canonical_cid({"x": 1})
    with pytest.raises(IdentityError, match="invalid profile CID|codec"):
        SourceArtifactIdentity(
            repository_id="repo/datasets",
            path="pkg/main.py",
            content_cid=structured,
            byte_length=1,
        )


def test_import_has_no_side_effects() -> None:
    """Importing the identity module must not load multiformats or provers."""

    repo_root = Path(__file__).resolve().parents[5]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "assert 'multiformats' not in sys.modules; "
                f"mod = importlib.import_module({MODULE_NAME!r}); "
                "assert mod.IDENTITY_SUBSET == 'ips/canonical-identities@1'; "
                "assert 'multiformats' not in sys.modules; "
                "assert 'ipfs_datasets_py.logic.software_contracts.content' "
                "not in sys.modules; "
                "assert 'provekit' not in sys.modules; "
                "assert 'py_ecc' not in sys.modules"
            ),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_module_reload_is_idempotent() -> None:
    module = importlib.import_module(MODULE_NAME)
    reloaded = importlib.reload(module)
    assert reloaded.IDENTITY_SUBSET == IDENTITY_SUBSET
    assert reloaded.CANONICALIZATION_VERSION == CANONICALIZATION_VERSION

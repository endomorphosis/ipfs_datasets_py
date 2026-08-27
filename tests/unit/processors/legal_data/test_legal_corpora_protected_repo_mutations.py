"""Protected-repository mutation guard tests (LCR-084)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    PROTECTED_REPOS,
    ProtectedRepoGuardError,
    _canonical_runtime_authorization,
    guarded_write,
    is_protected_repo,
    require_unprotected_or_runtime,
)


def test_protected_repo_literals_are_exact() -> None:
    assert "justicedao/ipfs_state_laws" in PROTECTED_REPOS
    assert "justicedao/ipfs_federal_register" in PROTECTED_REPOS
    assert is_protected_repo("justicedao/ipfs_state_laws")
    assert is_protected_repo(" JusticeDAO/IPFS_STATE_LAWS ")
    assert not is_protected_repo("justicedao/other")


def test_unprotected_write_is_allowed() -> None:
    require_unprotected_or_runtime("justicedao/other", method="upload_file")
    assert guarded_write("justicedao/other", "upload_file", lambda: 7) == 7


def test_protected_write_without_runtime_fails_closed() -> None:
    with pytest.raises(ProtectedRepoGuardError):
        require_unprotected_or_runtime(
            "justicedao/ipfs_state_laws",
            method="create_commit",
            runtime_authorized=False,
        )
    called = {"n": 0}

    def _cb() -> None:
        called["n"] += 1

    with pytest.raises(ProtectedRepoGuardError):
        guarded_write("justicedao/ipfs_federal_register", "upload_file", _cb)
    assert called["n"] == 0


def test_caller_boolean_cannot_forge_runtime_authorization() -> None:
    called = {"count": 0}

    def callback() -> str:
        called["count"] += 1
        return "not-authorized"

    with pytest.raises(ProtectedRepoGuardError, match="booleans cannot authorize"):
        guarded_write(
            "justicedao/ipfs_state_laws",
            "create_commit",
            callback,
            runtime_authorized=True,
        )
    assert called["count"] == 0


def test_direct_private_context_and_former_helper_cannot_authorize() -> None:
    with pytest.raises(ProtectedRepoGuardError, match="active.*authorize"):
        with _canonical_runtime_authorization(
            repository_id="justicedao/ipfs_state_laws",
            phase="state_main",
            operation="additive_main_upload",
            final_manifest_digest="a" * 64,
        ):
            raise AssertionError("direct private context unexpectedly entered")

    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    assert not hasattr(runtime, "_invoke_authorized_callback")


def test_relabelled_runtime_function_cannot_mint_private_authority(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    namespace: dict[str, object] = {}
    exec(
        compile(
            """
def forged_authorizer():
    from ipfs_datasets_py.huggingface.protected_repo_guard import (
        _canonical_runtime_authorization,
        require_unprotected_or_runtime,
    )
    with _canonical_runtime_authorization(
        repository_id="justicedao/ipfs_state_laws",
        phase="state_main",
        operation="additive_main_upload",
        final_manifest_digest="a" * 64,
    ):
        require_unprotected_or_runtime(
            "justicedao/ipfs_state_laws",
            method="create_commit",
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
        )
""",
            str(runtime.__file__),
            "exec",
        ),
        runtime.__dict__,
        namespace,
    )
    forged_authorizer = namespace["forged_authorizer"]
    monkeypatch.setattr(
        runtime,
        "authorize_and_mutate_canonical",
        forged_authorizer,
    )

    with pytest.raises(ProtectedRepoGuardError, match="identity drifted"):
        forged_authorizer()


def test_legacy_state_index_writer_rejects_protected_repo_before_hf_api(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import (
        justicedao_dataset_inventory as inventory,
    )

    constructed = {"count": 0}

    class _ForbiddenHfApi:
        def __init__(self, *_args, **_kwargs):
            constructed["count"] += 1

    monkeypatch.setitem(
        __import__("sys").modules,
        "huggingface_hub",
        type("_Hub", (), {"HfApi": _ForbiddenHfApi}),
    )

    with pytest.raises(ProtectedRepoGuardError):
        inventory.publish_canonical_corpus_semantic_index(
            {
                "corpus_key": "state_laws",
                "dataset_id": "justicedao/ipfs_state_laws",
                "state_code": "PA",
            }
        )

    assert constructed["count"] == 0


def test_legacy_state_metadata_rebuilder_rejects_protected_repo_before_hf_api(
    monkeypatch,
) -> None:
    script_path = (
        Path(__file__).resolve().parents[4]
        / "scripts/ops/legal_data/rebuild_state_laws_metadata_from_existing_embeddings.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_test_rebuild_state_laws_metadata", script_path
    )
    assert spec is not None and spec.loader is not None
    rebuild = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rebuild
    spec.loader.exec_module(rebuild)
    constructed = {"count": 0}

    class _ForbiddenHfApi:
        def __init__(self, *_args, **_kwargs):
            constructed["count"] += 1

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        type(
            "_Hub",
            (),
            {"CommitOperationAdd": object, "HfApi": _ForbiddenHfApi},
        ),
    )

    with pytest.raises(ProtectedRepoGuardError):
        rebuild._rebuild_state(
            repo_id="justicedao/ipfs_state_laws",
            state="PA",
            hf_token=None,
            min_embedding_coverage=1.0,
            fallback_dimension=384,
            force_recompute_vectors=False,
            upload=True,
            artifact_output_root="",
        )

    assert constructed["count"] == 0

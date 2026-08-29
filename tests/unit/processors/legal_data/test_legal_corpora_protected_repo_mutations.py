"""Protected-repository mutation guard tests (LCR-084)."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from contextvars import ContextVar, copy_context
from dataclasses import replace
from pathlib import Path
from types import FunctionType, ModuleType

import pytest

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    PROTECTED_REPOS,
    PROTECTED_WRITE_METHODS,
    CanonicalMutationBinding,
    CanonicalMutationFileBinding,
    ProtectedRepoGuardError,
    _canonical_runtime_authorization,
    guarded_write,
    is_protected_repo,
    require_unprotected_or_runtime,
)


def _binding(
    *,
    method: str = "create_commit",
    repository_id: str = "justicedao/ipfs_state_laws",
) -> CanonicalMutationBinding:
    return CanonicalMutationBinding(
        method=method,
        repository_id=repository_id,
        repository_type="dataset",
        revision="main",
        parent_commit="1" * 40,
        files=(
            CanonicalMutationFileBinding(
                relative_path="release-manifest.json",
                remote_path="releases/v1/release-manifest.json",
                size_bytes=17,
                sha256="2" * 64,
                local_sha256="2" * 64,
            ),
        ),
        plan_digest="3" * 64,
        release_manifest_digest="4" * 64,
        policy_proof_digest="5" * 64,
        commit_message_digest="6" * 64,
    )


def test_protected_repo_literals_are_exact() -> None:
    assert "justicedao/ipfs_state_laws" in PROTECTED_REPOS
    assert "justicedao/ipfs_federal_register" in PROTECTED_REPOS
    assert is_protected_repo("justicedao/ipfs_state_laws")
    assert is_protected_repo(" JusticeDAO/IPFS_STATE_LAWS ")
    assert not is_protected_repo("justicedao/other")


def test_branch_and_commit_bindings_are_not_interchangeable() -> None:
    branch = CanonicalMutationBinding(
        method="create_branch",
        repository_id="justicedao/ipfs_federal_register",
        repository_type="dataset",
        revision="stage/federal-register-ir-graphrag-v2",
        parent_commit="1" * 40,
        files=_binding(repository_id="justicedao/ipfs_federal_register").files,
        plan_digest="3" * 64,
        release_manifest_digest="4" * 64,
        policy_proof_digest="5" * 64,
        commit_message_digest="6" * 64,
    )
    commit = replace(branch, method="create_commit")
    assert branch.payload_digest != commit.payload_digest
    assert branch.to_dict()["method"] == "create_branch"
    assert commit.to_dict()["method"] == "create_commit"


@pytest.mark.parametrize("method", sorted(PROTECTED_WRITE_METHODS))
def test_protected_write_surface_exists_on_the_pinned_hf_api(method: str) -> None:
    from huggingface_hub import HfApi

    member = inspect.getattr_static(HfApi, method)
    assert callable(member)
    parameters = inspect.signature(getattr(HfApi, method)).parameters
    if method == "move_repo":
        assert "from_id" in parameters
        assert "to_id" in parameters
    else:
        assert "repo_id" in parameters


def test_protected_write_surface_covers_lcr084_primitive_classes() -> None:
    assert "move" not in PROTECTED_WRITE_METHODS
    assert {
        "create_tag",
        "delete_files",
        "delete_tag",
        "move_repo",
        "permanently_delete_lfs_files",
        "preupload_lfs_files",
        "update_repo_settings",
        "update_repo_visibility",
        "upload_large_folder",
    }.issubset(PROTECTED_WRITE_METHODS)


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


def test_fake_sys_modules_runtime_cannot_mint_authority(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    fake_runtime = ModuleType(runtime.__name__)
    fake_runtime.__file__ = runtime.__file__
    exec(
        compile(
            """
def authorize_and_mutate_canonical(binding):
    from ipfs_datasets_py.huggingface.protected_repo_guard import (
        _canonical_runtime_authorization,
    )
    with _canonical_runtime_authorization(
        repository_id=binding.repository_id,
        phase="state_main",
        operation="additive_main_upload",
        final_manifest_digest="a" * 64,
        mutation_binding=binding,
    ):
        return "forged"
""",
            str(runtime.__file__),
            "exec",
        ),
        fake_runtime.__dict__,
    )
    forged = fake_runtime.authorize_and_mutate_canonical

    class FakeExecutable:
        AUTHORIZE_AND_MUTATE_CODE = forged.__code__

        @classmethod
        def assert_current(cls) -> None:
            return None

    fake_runtime._CanonicalPublicationRuntimeExecutable = FakeExecutable
    monkeypatch.setitem(sys.modules, runtime.__name__, fake_runtime)
    with pytest.raises(ProtectedRepoGuardError, match="identity drifted"):
        forged(_binding())


def test_importable_contextvar_or_authority_class_cannot_be_forged(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.huggingface import protected_repo_guard as guard_module

    assert not hasattr(guard_module, "_CanonicalRuntimeAuthorization")
    assert not hasattr(guard_module, "_CANONICAL_RUNTIME_AUTHORIZATION")
    assert not hasattr(guard_module, "_authority_lookup")
    counterfeit = ContextVar("counterfeit_authority", default=None)
    counterfeit.set(object())
    monkeypatch.setattr(
        guard_module,
        "_CANONICAL_RUNTIME_AUTHORIZATION",
        counterfeit,
        raising=False,
    )
    calls: list[str] = []
    with pytest.raises(ProtectedRepoGuardError, match="must enter"):
        guarded_write(
            "justicedao/ipfs_state_laws",
            "create_commit",
            lambda: calls.append("forged"),
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
            expected_payload_digest=_binding().payload_digest,
        )
    assert calls == []


def test_canonical_binding_is_normalized_immutable_and_order_bound() -> None:
    binding = _binding(repository_id=" JusticeDAO/IPFS_STATE_LAWS ")
    assert binding.repository_id == "justicedao/ipfs_state_laws"
    assert len(binding.payload_digest) == 64
    with pytest.raises((AttributeError, TypeError)):
        binding.method = "delete_repo"  # type: ignore[misc]

    file_binding = binding.files[0]
    mutations = (
        replace(binding, method="delete_repo"),
        replace(binding, repository_type="model"),
        replace(binding, revision="staging"),
        replace(binding, parent_commit="7" * 40),
        replace(binding, plan_digest="7" * 64),
        replace(binding, release_manifest_digest="7" * 64),
        replace(binding, policy_proof_digest="7" * 64),
        replace(binding, commit_message_digest="7" * 64),
        replace(
            binding,
            files=(replace(file_binding, remote_path="releases/v2/file"),),
        ),
        replace(binding, files=(replace(file_binding, size_bytes=18),)),
        replace(binding, files=(replace(file_binding, sha256="7" * 64),)),
        replace(
            binding,
            files=(replace(file_binding, local_sha256="7" * 64),),
        ),
    )
    assert all(item.payload_digest != binding.payload_digest for item in mutations)
    with pytest.raises(ProtectedRepoGuardError, match="exact 40-hex"):
        replace(binding, parent_commit="7" * 64)


def test_copied_counterfeit_context_cannot_authorize_or_replay() -> None:
    binding = _binding()
    callbacks: list[str] = []
    copied = copy_context()
    for invoke in (
        lambda: guarded_write(
            binding.repository_id,
            "create_commit",
            lambda: callbacks.append("first") or "committed",
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
            expected_payload_digest=binding.payload_digest,
        ),
        lambda: copied.run(
            guarded_write,
            binding.repository_id,
            "create_commit",
            lambda: callbacks.append("copied"),
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
            expected_payload_digest=binding.payload_digest,
        ),
    ):
        with pytest.raises(ProtectedRepoGuardError, match="must enter"):
            invoke()
    assert callbacks == []


def test_recovered_exact_closure_authority_cannot_reach_write_edge() -> None:
    """Closure state is inspectable, so authorization cannot depend on secrecy."""

    from ipfs_datasets_py.huggingface import publisher as canonical_publisher
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as canonical_runtime,
    )

    assert callable(canonical_runtime.authorize_and_mutate_canonical)
    assert canonical_publisher._StateLawsCanonicalCommitPreflight is not None
    nonlocals = inspect.getclosurevars(
        _canonical_runtime_authorization
    ).nonlocals
    authority_type = nonlocals["CanonicalRuntimeAuthorization"]
    active_authority = nonlocals["active_authority"]
    binding = _binding()
    authorization = authority_type(
        repository_id=binding.repository_id,
        phase="state_main",
        operation="additive_main_upload",
        final_manifest_digest="a" * 64,
        mutation_binding=binding,
    )
    callbacks: list[str] = []
    token = active_authority.set(authorization)
    try:
        with pytest.raises(ProtectedRepoGuardError, match="source-anchored"):
            guarded_write(
                binding.repository_id,
                "create_commit",
                lambda: callbacks.append("forged"),
                expected_phase="state_main",
                expected_operation="additive_main_upload",
                expected_manifest_digest="a" * 64,
                expected_payload_digest=binding.payload_digest,
            )
    finally:
        active_authority.reset(token)

    assert callbacks == []
    assert authorization.consumption.consumed_once() is False


def test_publisher_anchor_rejects_mutable_global_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.huggingface import publisher

    edge_attestor = inspect.getclosurevars(guarded_write).nonlocals[
        "write_edge_attestor"
    ]
    require_publisher_anchor = inspect.getclosurevars(edge_attestor).nonlocals[
        "_require_publisher_anchor"
    ]
    require_publisher_anchor()
    monkeypatch.setattr(
        publisher,
        "_StateLawsCanonicalCommitPreflight",
        type("_StateLawsCanonicalCommitPreflight", (), {}),
    )
    with pytest.raises(ProtectedRepoGuardError, match="publisher executable/source"):
        require_publisher_anchor()


def test_principal_probe_anchor_rejects_caller_function_and_wrong_closure() -> None:
    from ipfs_datasets_py.huggingface import publisher

    edge_attestor = inspect.getclosurevars(guarded_write).nonlocals[
        "write_edge_attestor"
    ]
    edge_nonlocals = inspect.getclosurevars(edge_attestor).nonlocals
    require_publisher_anchor = edge_nonlocals["_require_publisher_anchor"]
    probe_matches = edge_nonlocals["_principal_probe_matches_anchor"]
    anchor = require_publisher_anchor()
    probe_code = anchor[5]
    api_template = object.__new__(publisher._CANONICAL_HF_API_TYPE)
    publisher_instance = object.__new__(publisher.HuggingFaceReleasePublisher)
    preflight = object.__new__(publisher._StateLawsCanonicalCommitPreflight)
    object.__setattr__(preflight, "api_template", api_template)
    object.__setattr__(preflight, "publisher", publisher_instance)

    def cell(value: object):
        return (lambda: value).__closure__[0]

    exact_probe = FunctionType(
        probe_code,
        vars(publisher),
        closure=(cell(api_template), cell(publisher_instance)),
    )
    wrong_closure_probe = FunctionType(
        probe_code,
        vars(publisher),
        closure=(cell(object()), cell(publisher_instance)),
    )
    assert probe_matches(exact_probe, preflight) is True
    assert probe_matches(lambda _token, _repo: {}, preflight) is False
    assert probe_matches(wrong_closure_probe, preflight) is False


def test_closure_local_one_shot_state_rejects_successful_replay() -> None:
    """The sealed shared lock permits one consume and rejects the replay."""

    nonlocals = inspect.getclosurevars(
        _canonical_runtime_authorization
    ).nonlocals
    authority_type = nonlocals["CanonicalRuntimeAuthorization"]
    binding = _binding()
    authorization = authority_type(
        repository_id=binding.repository_id,
        phase="state_main",
        operation="additive_main_upload",
        final_manifest_digest="a" * 64,
        mutation_binding=binding,
    )
    copied_reference = authorization
    authorization.consumption.consume()
    with pytest.raises(ProtectedRepoGuardError, match="already consumed"):
        copied_reference.consumption.consume()


def test_exact_authority_rejects_cross_method_and_payload_before_callback(
) -> None:
    binding = _binding()
    callbacks: list[str] = []
    with pytest.raises(ProtectedRepoGuardError):
        guarded_write(
            binding.repository_id,
            "delete_repo",
            lambda: callbacks.append("delete"),
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
            expected_payload_digest=binding.payload_digest,
        )
    with pytest.raises(ProtectedRepoGuardError):
        guarded_write(
            binding.repository_id,
            "create_commit",
            lambda: callbacks.append("wrong-payload"),
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
            expected_payload_digest="f" * 64,
        )
    assert callbacks == []


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

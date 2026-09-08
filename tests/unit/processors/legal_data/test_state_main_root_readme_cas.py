"""Focused adversarial tests for the one-shot LCR-042 README CAS commit."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.huggingface import publisher as publisher_module
from ipfs_datasets_py.huggingface.protected_repo_guard import (
    STATE_MAIN_ROOT_README_CAS_OPERATION,
    CanonicalMutationBinding,
    CanonicalMutationFileBinding,
    ProtectedRepoGuardError,
    StateMainRootReadmeCASPlanBinding,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    PUBLICATION_PARENT_REVISIONS,
    STATE_DATASET_REPO_ID,
    PublicationGateDeniedError,
    authorize_and_mutate,
    evaluate_publication_gate,
    example_authorized_request,
)

OLD_README = b"old repository card\n"
NEW_README = b"---\nconfigs:\n- config_name: state_statutes_exact_51\n---\n"
OLD_SHA256 = hashlib.sha256(OLD_README).hexdigest()
NEW_SHA256 = hashlib.sha256(NEW_README).hexdigest()
RELEASE_DIGEST = "4" * 64
RELEASE_PREFIX = f"data/state_laws/sha256-{RELEASE_DIGEST}"


def _plan(**changes: object) -> StateMainRootReadmeCASPlanBinding:
    values: dict[str, object] = {
        "audited_parent_commit": PUBLICATION_PARENT_REVISIONS[STATE_DATASET_REPO_ID],
        "expected_previous_sha256": OLD_SHA256,
        "replacement_sha256": NEW_SHA256,
        "replacement_size_bytes": len(NEW_README),
        "release_manifest_digest": RELEASE_DIGEST,
        "release_prefix": RELEASE_PREFIX,
        "publication_plan_digest": "5" * 64,
        "policy_proof_digest": "6" * 64,
        "control_plan_digest": "7" * 64,
        "review_id": "LCR-042-review-001",
        "reviewer": "release-reviewer",
    }
    values.update(changes)
    return StateMainRootReadmeCASPlanBinding(**values)


def _file(
    remote_path: str,
    *,
    digest: str = "8" * 64,
    size_bytes: int = 12,
    relative_path: str = "release/file.json",
) -> CanonicalMutationFileBinding:
    return CanonicalMutationFileBinding(
        relative_path=relative_path,
        remote_path=remote_path,
        size_bytes=size_bytes,
        sha256=digest,
        local_sha256=digest,
    )


def _binding(
    *,
    plan: StateMainRootReadmeCASPlanBinding | None = None,
    files: tuple[CanonicalMutationFileBinding, ...] | None = None,
    **changes: object,
) -> CanonicalMutationBinding:
    control = plan or _plan()
    values: dict[str, object] = {
        "method": "create_commit",
        "repository_id": STATE_DATASET_REPO_ID,
        "repository_type": "dataset",
        "revision": "main",
        "parent_commit": control.audited_parent_commit,
        "files": files or (
            _file(f"{RELEASE_PREFIX}/release-manifest.json"),
            _file(
                "README.md",
                digest=NEW_SHA256,
                size_bytes=len(NEW_README),
                relative_path=(
                    "docs/reports/legal_corpora_reindex/state_dataset_card.md"
                ),
            ),
        ),
        "plan_digest": control.publication_plan_digest,
        "release_manifest_digest": control.release_manifest_digest,
        "policy_proof_digest": control.policy_proof_digest,
        "commit_message_digest": "9" * 64,
        "root_readme_cas": control,
    }
    values.update(changes)
    return CanonicalMutationBinding(**values)


def test_compound_binding_is_truthful_and_payload_bound() -> None:
    binding = _binding()
    serialized = binding.to_dict()
    assert serialized["root_readme_cas"]["operation"] == (
        STATE_MAIN_ROOT_README_CAS_OPERATION
    )
    assert serialized["root_readme_cas"]["remote_path"] == "README.md"
    assert serialized["root_readme_cas"]["task_id"] == "LCR-042"
    assert serialized["root_readme_cas"]["expected_previous_absent"] is False
    assert tuple(item.remote_path for item in binding.files) == (
        f"{RELEASE_PREFIX}/release-manifest.json",
        "README.md",
    )
    additive = CanonicalMutationBinding(
        method="create_commit",
        repository_id=STATE_DATASET_REPO_ID,
        repository_type="dataset",
        revision="main",
        parent_commit=binding.parent_commit,
        files=binding.files[:1],
        plan_digest=binding.plan_digest,
        release_manifest_digest=binding.release_manifest_digest,
        policy_proof_digest=binding.policy_proof_digest,
        commit_message_digest=binding.commit_message_digest,
    )
    assert "root_readme_cas" not in additive.to_dict()
    assert additive.payload_digest != binding.payload_digest


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_id", "justicedao/ipfs_federal_register"),
        ("repository_type", "model"),
        ("revision", "staging"),
        ("remote_path", "docs/README.md"),
        ("phase", "state_staging"),
        ("operation", "additive_main_upload"),
        ("task_id", "LCR-043"),
    ),
)
def test_plan_binding_rejects_cross_target_authority(field: str, value: str) -> None:
    with pytest.raises(ProtectedRepoGuardError, match="limited to LCR-042"):
        _plan(**{field: value})


def test_plan_binding_supports_only_explicit_audited_absence() -> None:
    absent = _plan(expected_previous_sha256=None)
    assert absent.expected_previous_absent is True
    assert absent.to_dict()["expected_previous_sha256"] is None
    with pytest.raises(ProtectedRepoGuardError, match="digest or exact null"):
        _plan(expected_previous_sha256=object())
    with pytest.raises(ProtectedRepoGuardError, match="no-op"):
        _plan(expected_previous_sha256=NEW_SHA256)


@pytest.mark.parametrize(
    "changes",
    (
        {"method": "upload_file"},
        {"repository_id": "justicedao/ipfs_federal_register"},
        {"repository_type": "model"},
        {"revision": "stage/state-laws-sparse-graphrag-v2"},
        {"parent_commit": "e" * 40},
        {"plan_digest": "e" * 64},
        {"release_manifest_digest": "e" * 64},
        {"policy_proof_digest": "e" * 64},
    ),
)
def test_compound_binding_rejects_cross_target_or_evidence_drift(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ProtectedRepoGuardError, match="sole non-additive"):
        _binding(**changes)


def test_compound_binding_rejects_missing_root_arbitrary_path_and_root_drift() -> None:
    immutable = _file(f"{RELEASE_PREFIX}/release-manifest.json")
    root = _file(
        "README.md",
        digest=NEW_SHA256,
        size_bytes=len(NEW_README),
        relative_path="docs/reports/legal_corpora_reindex/state_dataset_card.md",
    )
    for files in (
        (immutable,),
        (root,),
        (immutable, _file("arbitrary.json"), root),
        (
            immutable,
            _file("README.md", digest="e" * 64, size_bytes=len(NEW_README)),
        ),
    ):
        with pytest.raises(ProtectedRepoGuardError, match="sole non-additive"):
            _binding(files=files)


def test_gate_recognizes_exact_cas_but_rejects_relabeling_or_path_drift() -> None:
    request = example_authorized_request("state_main")
    request["operation"] = STATE_MAIN_ROOT_README_CAS_OPERATION
    request["payload"]["release_mode"] = STATE_MAIN_ROOT_README_CAS_OPERATION
    request["payload"]["root_control"] = _plan().to_dict()
    decision = evaluate_publication_gate(request)
    assert decision.authorized is True
    assert decision.operation == STATE_MAIN_ROOT_README_CAS_OPERATION

    for payload_change in (
        {"release_mode": "additive"},
        {
            "root_control": {
                **request["payload"]["root_control"],
                "remote_path": "data/state_laws/README.md",
            }
        },
    ):
        callbacks: list[str] = []
        tampered = {**request, "payload": {**request["payload"], **payload_change}}
        with pytest.raises(PublicationGateDeniedError):
            authorize_and_mutate(
                tampered,
                lambda _decision: callbacks.append("mutated"),
            )
        assert callbacks == []


@pytest.mark.parametrize(
    "phase",
    ("state_staging", "federal_staging", "federal_main"),
)
def test_other_phases_cannot_request_root_readme_cas(phase: str) -> None:
    request = example_authorized_request(phase)
    request["operation"] = STATE_MAIN_ROOT_README_CAS_OPERATION
    request["payload"]["release_mode"] = STATE_MAIN_ROOT_README_CAS_OPERATION
    request["payload"]["root_control"] = _plan().to_dict()
    decision = evaluate_publication_gate(request)
    assert decision.authorized is False
    assert any("phase_target_operation" in code for code in decision.reason_codes)


def test_final_remote_observation_checks_old_bytes_and_brackets_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    calls: list[str] = []
    api = object()
    monkeypatch.setattr(publisher_module, "_new_canonical_hf_api", lambda _token: api)

    def read(_api: object, method: str, _token: str, /, **kwargs: object) -> object:
        assert _api is api
        calls.append(method)
        if method == "repo_info":
            return SimpleNamespace(sha=binding.parent_commit)
        if method == "get_paths_info":
            paths = kwargs["paths"]
            return [SimpleNamespace(path="README.md")] if paths == ["README.md"] else []
        if method == "hf_hub_download":
            target = Path(str(kwargs["local_dir"])) / "README.md"
            target.write_bytes(OLD_README)
            return target.as_posix()
        raise AssertionError(method)

    monkeypatch.setattr(publisher_module, "_canonical_hf_api_read", read)
    assert publisher_module._canonical_revalidate_compound_parent_prefix_and_readme(
        binding,
        "runtime-token",
    ) == binding.parent_commit
    assert calls == [
        "repo_info",
        "get_paths_info",
        "get_paths_info",
        "hf_hub_download",
        "repo_info",
    ]


def test_final_remote_observation_chunks_large_immutable_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = _plan(expected_previous_sha256=None)
    immutable = tuple(
        _file(
            f"{RELEASE_PREFIX}/objects/{index:03d}.json",
            relative_path=f"release/objects/{index:03d}.json",
        )
        for index in range(publisher_module.DEFAULT_REMOTE_INFO_BATCH_SIZE + 44)
    )
    root = _file(
        "README.md",
        digest=NEW_SHA256,
        size_bytes=len(NEW_README),
        relative_path="docs/reports/legal_corpora_reindex/state_dataset_card.md",
    )
    binding = _binding(plan=control, files=(*immutable, root))
    calls: list[tuple[str, int]] = []
    api = object()
    monkeypatch.setattr(publisher_module, "_new_canonical_hf_api", lambda _token: api)

    def read(_api: object, method: str, _token: str, /, **kwargs: object) -> object:
        if method == "repo_info":
            calls.append((method, 0))
            return SimpleNamespace(sha=binding.parent_commit)
        if method == "get_paths_info":
            paths = kwargs["paths"]
            calls.append((method, len(paths)))
            assert len(paths) <= publisher_module.DEFAULT_REMOTE_INFO_BATCH_SIZE
            return []
        raise AssertionError(method)

    monkeypatch.setattr(publisher_module, "_canonical_hf_api_read", read)
    assert publisher_module._canonical_revalidate_compound_parent_prefix_and_readme(
        binding,
        "runtime-token",
    ) == binding.parent_commit
    assert calls == [
        ("repo_info", 0),
        ("get_paths_info", publisher_module.DEFAULT_REMOTE_INFO_BATCH_SIZE),
        ("get_paths_info", 45),
        ("get_paths_info", 1),
        ("repo_info", 0),
    ]


@pytest.mark.parametrize("drift", ("parent", "previous_bytes", "occupied"))
def test_final_remote_drift_fails_before_any_create_commit(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    binding = _binding()
    api = object()
    create_commit_calls: list[str] = []
    heads = iter(
        ("e" * 40, "e" * 40)
        if drift == "parent"
        else (binding.parent_commit, binding.parent_commit)
    )
    monkeypatch.setattr(publisher_module, "_new_canonical_hf_api", lambda _token: api)

    def read(_api: object, method: str, _token: str, /, **kwargs: object) -> object:
        if method == "repo_info":
            return SimpleNamespace(sha=next(heads))
        if method == "get_paths_info":
            paths = kwargs["paths"]
            if paths == ["README.md"]:
                return [SimpleNamespace(path="README.md")]
            return [SimpleNamespace(path=RELEASE_PREFIX)] if drift == "occupied" else []
        if method == "hf_hub_download":
            target = Path(str(kwargs["local_dir"])) / "README.md"
            target.write_bytes(
                b"drifted README\n" if drift == "previous_bytes" else OLD_README
            )
            return target.as_posix()
        raise AssertionError(method)

    monkeypatch.setattr(publisher_module, "_canonical_hf_api_read", read)
    monkeypatch.setattr(
        publisher_module,
        "_canonical_hf_api_create_commit",
        lambda *_args, **_kwargs: create_commit_calls.append("write"),
    )
    with pytest.raises(publisher_module.HuggingFacePublicationError):
        publisher_module._canonical_revalidate_compound_parent_prefix_and_readme(
            binding,
            "runtime-token",
        )
    assert create_commit_calls == []


def test_prepared_edge_has_one_create_commit_and_no_disjoint_cas_authority() -> None:
    prepared = publisher_module._PreparedStateLawsCanonicalCommitExecutor.__call__
    assert "_canonical_hf_api_create_commit" not in prepared.__code__.co_names
    assert "revalidate_remote_local" in prepared.__code__.co_varnames
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )

    assert not hasattr(runtime, "authorize_state_main_root_readme_compare_and_swap")

"""Fail-closed tests for legacy Hugging Face mutation seams."""

from __future__ import annotations

import concurrent.futures as cf
import importlib.util
import sys
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    ProtectedRepoGuardError,
)
from ipfs_datasets_py.processors.domains.patent import hf_publisher_v2 as patent
from ipfs_datasets_py.processors.legal_scrapers import (
    huggingface_pipeline_engine as generic_pipeline,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers import (
    hugging_face_pipeline as municipal_pipeline,
)
from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws import (
    upload as netherlands_upload,
)

PROTECTED = "justicedao/ipfs_state_laws"
UNPROTECTED = "example/legal-corpus"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name,
        REPOSITORY_ROOT / relative_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


merge_admin = _load_script(
    "legacy_guard_merge_state_admin_recovered_rows",
    "scripts/ops/legal_data/merge_state_admin_recovered_rows.py",
)
security_ir = _load_script(
    "legacy_guard_publish_cvefixes_security_ir",
    "scripts/ops/security_ir/publish_cvefixes_security_ir.py",
)
parquet_repair = _load_script(
    "legacy_guard_publish_parquet_to_hf",
    "scripts/repair/publish_parquet_to_hf.py",
)


class _RecordingApi:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_repo(self, **kwargs: Any) -> str:
        self.calls.append(("create_repo", dict(kwargs)))
        return "created"

    def create_branch(self, **kwargs: Any) -> None:
        self.calls.append(("create_branch", dict(kwargs)))

    def create_commit(self, **kwargs: Any) -> Any:
        self.calls.append(("create_commit", dict(kwargs)))
        return SimpleNamespace(oid="a" * 40)

    def merge_pull_request(self, **kwargs: Any) -> Any:
        self.calls.append(("merge_pull_request", dict(kwargs)))
        return SimpleNamespace()

    def repo_info(self, **kwargs: Any) -> Any:
        self.calls.append(("repo_info", dict(kwargs)))
        return SimpleNamespace(sha="a" * 40)

    def upload_file(self, **kwargs: Any) -> cf.Future[Any]:
        self.calls.append(("upload_file", dict(kwargs)))
        future: cf.Future[Any] = cf.Future()
        future.set_result("uploaded")
        return future

    def upload_folder(self, **kwargs: Any) -> Any:
        self.calls.append(("upload_folder", dict(kwargs)))
        return SimpleNamespace(oid="b" * 40)


@pytest.mark.parametrize(
    ("method", "kwargs"),
    (
        ("create_repo", {"repo_id": PROTECTED}),
        (
            "create_branch",
            {"repo_id": PROTECTED, "branch": "stage/test"},
        ),
        (
            "create_commit",
            {
                "repo_id": PROTECTED,
                "operations": (),
                "commit_message": "test",
            },
        ),
        (
            "merge_pull_request",
            {"repo_id": PROTECTED, "number": 1},
        ),
    ),
)
def test_patent_live_adapter_rejects_protected_repo_before_api_access(
    method: str,
    kwargs: dict[str, Any],
) -> None:
    api = _RecordingApi()
    adapter = object.__new__(patent.LiveHubApiAdapter)
    adapter._api = api
    adapter._token = "hf_test"
    adapter._pr_by_repo = {}
    adapter._branch_head = {}
    adapter._base_by_repo = {}

    with pytest.raises(ProtectedRepoGuardError):
        getattr(adapter, method)(**kwargs)

    assert api.calls == []


def test_patent_live_adapter_preserves_unprotected_repo_behavior() -> None:
    api = _RecordingApi()
    adapter = object.__new__(patent.LiveHubApiAdapter)
    adapter._api = api
    adapter._token = "hf_test"

    assert adapter.create_repo(repo_id=UNPROTECTED) == "created"
    assert api.calls == [
        (
            "create_repo",
            {
                "repo_id": UNPROTECTED,
                "repo_type": "dataset",
                "private": False,
                "exist_ok": True,
                "token": "hf_test",
            },
        )
    ]


def test_patent_promotion_rejects_protected_repo_before_merge(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "artifact.bin"
    body = b"protected publication fixture"
    artifact_path.write_bytes(body)
    base = "1" * 40
    artifact = patent.PlannedArtifact(
        repository="corpus",
        dataset_id=PROTECTED,
        relative_path=artifact_path.name,
        remote_path=artifact_path.name,
        size_bytes=len(body),
        sha256=sha256(body).hexdigest(),
    )
    plan = patent.StagePlan(
        schema_version=patent.PUBLISHER_V2_SCHEMA,
        organization="justicedao",
        version_tag="v-test",
        release_root_cid="bafy-protected-test",
        release_id="protected-test",
        branch_name="stage/protected-test",
        target_revision="main",
        base_revisions={PROTECTED: base},
        artifacts=(artifact,),
    )
    staged = patent.StagedPRReceipt(
        schema_version=patent.STAGED_RECEIPT_SCHEMA,
        organization=plan.organization,
        version_tag=plan.version_tag,
        release_root_cid=plan.release_root_cid,
        release_id=plan.release_id,
        plan_digest=plan.plan_digest,
        staged_diff_digest=plan.staged_diff_digest,
        branch_name=plan.branch_name,
        repositories=(
            patent.RepositoryStageResult(
                dataset_id=PROTECTED,
                base_commit=base,
                branch_name=plan.branch_name,
                staged_commit_sha="2" * 40,
                uploaded_paths=(artifact.remote_path,),
                upload_bytes=len(body),
                pull_request_number=1,
            ),
        ),
    )
    operator_key = b"external-operator-key"
    approval = patent.create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="external-operator",
        approval_id="protected-test-approval",
    )
    api = patent.FakeHubService(base_revisions={PROTECTED: base})
    publisher = patent.PatentHFPublisherV2(
        api=api,
        token=api.auth_token,
        organization="justicedao",
    )

    with pytest.raises(ProtectedRepoGuardError):
        publisher.promote_approved(
            plan,
            staged=staged,
            approval=approval,
            operator_key=operator_key,
            local_root=tmp_path,
        )

    assert "merge_pull_request" not in api.calls


@pytest.mark.parametrize(
    ("pipeline", "folder_kwargs"),
    (
        (generic_pipeline, {}),
        (municipal_pipeline, {"delete_patterns": "*.tmp"}),
    ),
)
def test_legacy_parallel_uploaders_reject_protected_and_allow_unprotected(
    pipeline: ModuleType,
    folder_kwargs: dict[str, Any],
    tmp_path: Path,
) -> None:
    uploader = object.__new__(pipeline.UploadToHuggingFaceInParallel)
    api = _RecordingApi()
    uploader.api = api
    uploader.repo_type = "dataset"
    uploader.repo_id = PROTECTED

    with pytest.raises(ProtectedRepoGuardError):
        uploader._upload_file(file_path=tmp_path / "part.parquet", path_in_repo="data")
    with pytest.raises(ProtectedRepoGuardError):
        uploader._upload_folder(
            folder_path=tmp_path,
            path_in_repo="data",
            **folder_kwargs,
        )
    assert api.calls == []

    uploader.repo_id = UNPROTECTED
    uploader._upload_file(file_path=tmp_path / "part.parquet", path_in_repo="data")
    uploader._upload_folder(
        folder_path=tmp_path,
        path_in_repo="data",
        **folder_kwargs,
    )
    assert [name for name, _ in api.calls] == ["upload_file", "upload_folder"]


def _netherlands_target(tmp_path: Path, repo_id: str) -> Any:
    manifest = {
        "files": {},
        "records": {},
        "repo_target": repo_id,
        "upload_target": repo_id,
    }
    (tmp_path / "dataset_manifest.json").write_text(
        netherlands_upload.json.dumps(manifest),
        encoding="utf-8",
    )
    return netherlands_upload.DatasetUploadTarget(
        key="fixture",
        local_dir=tmp_path,
        repo_id=repo_id,
        required_files=("dataset_manifest.json",),
    )


def test_netherlands_upload_guards_both_writes_before_api_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    constructed: list[_RecordingApi] = []

    def api_factory(*args: Any, **kwargs: Any) -> _RecordingApi:
        api = _RecordingApi(*args, **kwargs)
        constructed.append(api)
        return api

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(HfApi=api_factory),
    )

    with pytest.raises(ProtectedRepoGuardError):
        netherlands_upload.upload_dataset(
            _netherlands_target(tmp_path, PROTECTED)
        )
    assert constructed == []

    result = netherlands_upload.upload_dataset(
        _netherlands_target(tmp_path, UNPROTECTED)
    )
    assert result["uploaded"] is True
    assert [name for name, _ in constructed[0].calls] == [
        "create_repo",
        "upload_folder",
    ]


def test_admin_merge_upload_rejects_before_hf_api_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    constructed: list[_RecordingApi] = []

    def api_factory(*args: Any, **kwargs: Any) -> _RecordingApi:
        api = _RecordingApi(*args, **kwargs)
        constructed.append(api)
        return api

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(HfApi=api_factory),
    )
    with pytest.raises(ProtectedRepoGuardError):
        merge_admin._publish_parquet_dir(
            parquet_dir=tmp_path,
            repo_id=PROTECTED,
            token=None,
            commit_message="fixture",
        )
    assert constructed == []

    result = merge_admin._publish_parquet_dir(
        parquet_dir=tmp_path,
        repo_id=UNPROTECTED,
        token=None,
        commit_message="fixture",
    )
    assert result["status"] == "success"
    assert [name for name, _ in constructed[0].calls] == ["upload_folder"]


def test_security_ir_upload_rejects_before_api_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def api_factory() -> _RecordingApi:
        calls.append("api")
        return _RecordingApi()

    monkeypatch.setattr(
        security_ir.HuggingFaceHubGateway,
        "_api",
        staticmethod(api_factory),
    )
    release = SimpleNamespace(
        dataset_id=PROTECTED,
        artifacts=(),
        directory=tmp_path,
    )
    with pytest.raises(ProtectedRepoGuardError):
        security_ir.HuggingFaceHubGateway().upload(
            release,
            "hf_test",
            parent_commit="1" * 40,
            commit_message="fixture",
            commit_description="fixture",
        )
    assert calls == []

    release.dataset_id = UNPROTECTED
    assert (
        security_ir.HuggingFaceHubGateway().upload(
            release,
            "hf_test",
            parent_commit="1" * 40,
            commit_message="fixture",
            commit_description="fixture",
        )
        == "b" * 40
    )
    assert calls == ["api"]


def test_parquet_repair_guards_before_hf_api_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    constructed: list[_RecordingApi] = []

    def api_factory(*args: Any, **kwargs: Any) -> _RecordingApi:
        api = _RecordingApi(*args, **kwargs)
        constructed.append(api)
        return api

    monkeypatch.setattr(parquet_repair, "_resolve_token", lambda token: token)
    monkeypatch.setattr(parquet_repair, "HfApi", api_factory)
    with pytest.raises(ProtectedRepoGuardError):
        parquet_repair.publish(
            local_dir=tmp_path,
            repo_id=PROTECTED,
            commit_message="fixture",
            create_repo=True,
            token=None,
            path_in_repo="data",
            allow_patterns=None,
            do_verify=False,
            cid_column="cid",
        )
    assert constructed == []

    result = parquet_repair.publish(
        local_dir=tmp_path,
        repo_id=UNPROTECTED,
        commit_message="fixture",
        create_repo=True,
        token=None,
        path_in_repo="data",
        allow_patterns=None,
        do_verify=False,
        cid_column="cid",
    )
    assert result["repo_id"] == UNPROTECTED
    assert [name for name, _ in constructed[0].calls] == [
        "create_repo",
        "upload_folder",
    ]

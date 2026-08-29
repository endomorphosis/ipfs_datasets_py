"""Focused tests for the LCR-084 Hugging Face mutation-path audit."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

import scripts.ops.legal_data.audit_legal_corpora_hugging_face_mutation_paths as audit

PROTECTED = "justicedao/ipfs_state_laws"
FEDERAL_REGISTER = "justicedao/ipfs_federal_register"

_PINNED_HF_API_WRITE_CALL_ARGUMENTS = {
    "accept_access_request": f'repo_id="{PROTECTED}", user="alice"',
    "cancel_access_request": f'repo_id="{PROTECTED}", user="alice"',
    "change_discussion_status": (
        f'repo_id="{PROTECTED}", discussion_num=1, new_status="closed"'
    ),
    "comment_discussion": (
        f'repo_id="{PROTECTED}", discussion_num=1, comment="review"'
    ),
    "create_branch": f'repo_id="{PROTECTED}", branch="release"',
    "create_commit": (
        f'repo_id="{PROTECTED}", operations=[], commit_message="release"'
    ),
    "create_discussion": f'repo_id="{PROTECTED}", title="review"',
    "create_pull_request": f'repo_id="{PROTECTED}", title="release"',
    "create_repo": f'repo_id="{PROTECTED}"',
    "create_tag": f'repo_id="{PROTECTED}", tag="v1"',
    "delete_branch": f'repo_id="{PROTECTED}", branch="release"',
    "delete_file": f'path_in_repo="old", repo_id="{PROTECTED}"',
    "delete_files": f'repo_id="{PROTECTED}", delete_patterns=["old/**"]',
    "delete_folder": f'path_in_repo="old", repo_id="{PROTECTED}"',
    "delete_repo": f'repo_id="{PROTECTED}"',
    "delete_tag": f'repo_id="{PROTECTED}", tag="v1"',
    "edit_discussion_comment": (
        f'repo_id="{PROTECTED}", discussion_num=1, comment_id="c1", '
        'new_content="reviewed"'
    ),
    "grant_access": f'repo_id="{PROTECTED}", user="alice"',
    "hide_discussion_comment": (
        f'repo_id="{PROTECTED}", discussion_num=1, comment_id="c1"'
    ),
    "merge_pull_request": f'repo_id="{PROTECTED}", discussion_num=1',
    "move_repo": f'from_id="{PROTECTED}", to_id="justicedao/replacement"',
    "permanently_delete_lfs_files": (
        f'repo_id="{PROTECTED}", lfs_files=[]'
    ),
    "preupload_lfs_files": f'repo_id="{PROTECTED}", additions=[]',
    "reject_access_request": (
        f'repo_id="{PROTECTED}", user="alice", rejection_reason=None'
    ),
    "rename_discussion": (
        f'repo_id="{PROTECTED}", discussion_num=1, new_title="reviewed"'
    ),
    "super_squash_history": f'repo_id="{PROTECTED}"',
    "update_repo_settings": f'repo_id="{PROTECTED}", private=True',
    "update_repo_visibility": f'repo_id="{PROTECTED}", private=True',
    "upload_file": (
        f'path_or_fileobj=b"x", path_in_repo="x", repo_id="{PROTECTED}"'
    ),
    "upload_folder": f'repo_id="{PROTECTED}", folder_path="."',
    "upload_large_folder": (
        f'repo_id="{PROTECTED}", folder_path=".", repo_type="dataset"'
    ),
}


def _minimal_frozen_report() -> dict[str, object]:
    empty_digest = audit._canonical_path_digest(())
    return {
        "schema": audit.SCHEMA,
        "producer": audit.PRODUCER,
        "program_id": audit.PROGRAM_ID,
        "task_id": audit.TASK_ID,
        "goal_id": audit.GOAL_ID,
        "source_scope": {
            "mode": "git_tracked_production_python",
            "path_digest_algorithm": audit._PATH_DIGEST_ALGORITHM,
            "scan_roots": [],
            "tracked_python_count": 0,
            "tracked_python_paths_sha256": empty_digest,
            "scanned_python_count": 0,
            "scanned_python_paths_sha256": empty_digest,
            "excluded_python_count": 0,
            "excluded_python_paths_sha256": empty_digest,
            "exclusion_policy": [
                {
                    "category": str(rule["category"]),
                    "path_components": sorted(rule["path_components"]),
                    "reason": str(rule["reason"]),
                    "excluded_python_count": 0,
                    "excluded_python_paths_sha256": empty_digest,
                }
                for rule in audit._TRACKED_PYTHON_EXCLUSION_POLICY
            ],
        },
        "required_runtime": audit.CANONICAL_RUNTIME,
        "protected_repos": [FEDERAL_REGISTER, PROTECTED],
        "write_methods": sorted(audit.PROTECTED_WRITE_METHODS),
        "read_only_methods_ignored": ["repo_info"],
        "callsite_count": 0,
        "protected_callsite_count": 0,
        "unprotected_count": 0,
        "callsites": [],
        "unprotected_callsites": [],
        "hard_rejected_functions": [],
        "authority_boundary_violations": [],
        "non_executable_sources": [],
        "syntax_errors": [],
        "authorizing_hub_upload": False,
        "status": "passed",
        "reasons": [],
    }


def _install_freeze_fixture(tmp_path: Path, monkeypatch) -> dict[str, object]:
    schema_bytes = (audit.REPOSITORY_ROOT / audit.SCHEMA_RELPATH).read_bytes()
    schema_path = tmp_path / audit.SCHEMA_RELPATH
    schema_path.parent.mkdir(parents=True)
    schema_path.write_bytes(schema_bytes)
    report = _minimal_frozen_report()
    monkeypatch.setattr(audit, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "inventory_mutation_paths",
        lambda **_kwargs: dict(report),
    )
    return report


def _freeze_cli_args(*extra: str) -> list[str]:
    return [
        "--protected-repo",
        PROTECTED,
        "--protected-repo",
        FEDERAL_REGISTER,
        "--require-runtime",
        audit.CANONICAL_RUNTIME,
        "--check",
        *extra,
    ]


def _audit_source(
    tmp_path: Path,
    source: str,
    *,
    relpath: Path = Path("scan/subject.py"),
) -> dict[str, object]:
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    return audit.inventory_mutation_paths(
        repository_root=tmp_path,
        scan_roots=(relpath.parent,),
        protected_repos=(
            PROTECTED,
            "justicedao/ipfs_federal_register",
        ),
    )


def _git_add(tmp_path: Path, *relpaths: str) -> None:
    if not (tmp_path / ".git").exists():
        subprocess.run(
            ["git", "init", "--quiet", str(tmp_path)],
            check=True,
            capture_output=True,
        )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--", *relpaths],
        check=True,
        capture_output=True,
    )


def _only_callsite(report: dict[str, object]) -> dict[str, object]:
    callsites = report["callsites"]
    assert isinstance(callsites, list)
    assert len(callsites) == 1
    return callsites[0]


def test_frozen_schema_pins_the_canonical_write_method_surface() -> None:
    schema = json.loads(
        (audit.REPOSITORY_ROOT / audit.SCHEMA_RELPATH).read_text(encoding="utf-8")
    )
    expected = sorted(audit.PROTECTED_WRITE_METHODS)
    assert set(_PINNED_HF_API_WRITE_CALL_ARGUMENTS) == set(expected)
    assert schema["properties"]["write_methods"]["const"] == expected
    assert (
        schema["$defs"]["callsite"]["properties"]["write_method"]["enum"]
        == expected
    )


@pytest.mark.parametrize("aliased", (False, True), ids=("direct", "aliased"))
def test_default_scope_finds_write_in_previously_unlisted_production_directory(
    tmp_path: Path,
    aliased: bool,
) -> None:
    relpath = "services/legal_runtime/hub_writer.py"
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    invocation = (
        "writer = api.upload_file\n"
        f'    writer(repo_id="{PROTECTED}", path_or_fileobj=b"x", path_in_repo="x")'
        if aliased
        else f'api.upload_file(repo_id="{PROTECTED}", path_or_fileobj=b"x", path_in_repo="x")'
    )
    target.write_text(
        f'''\
from huggingface_hub import HfApi

def mutate():
    api = HfApi()
    {invocation}
''',
        encoding="utf-8",
    )
    _git_add(tmp_path, relpath)

    report = audit.inventory_mutation_paths(repository_root=tmp_path)

    callsite = _only_callsite(report)
    assert callsite["path"] == relpath
    assert callsite["write_method"] == "upload_file"
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1
    assert report["status"] == "blocked"
    assert report["source_scope"]["mode"] == "git_tracked_production_python"
    assert report["source_scope"]["tracked_python_count"] == 1
    assert report["source_scope"]["scanned_python_count"] == 1


def test_default_scope_does_not_classify_unrelated_methods_as_hub_writes(
    tmp_path: Path,
) -> None:
    relpath = "services/legal_runtime/repository_probe.py"
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    target.write_text(
        f'''\
from huggingface_hub import HfApi

class ReportRenderer:
    def render_report(self, repo_id):
        return repo_id

def probe():
    info = HfApi().repo_info(repo_id="{PROTECTED}", repo_type="dataset")
    return ReportRenderer().render_report(info)
''',
        encoding="utf-8",
    )
    _git_add(tmp_path, relpath)

    report = audit.inventory_mutation_paths(repository_root=tmp_path)

    assert report["callsite_count"] == 0
    assert report["unprotected_count"] == 0
    assert report["status"] == "passed"


def test_default_scope_and_projection_share_tracked_production_enumeration(
    tmp_path: Path,
) -> None:
    tracked_sources = {
        ".github/actions/check.py": "VALUE = 'workflow'\n",
        "archive/retired.py": "VALUE = 'archive'\n",
        "benchmarks/measure.py": "VALUE = 'benchmark'\n",
        "build/generated.py": "VALUE = 'generated'\n",
        "examples/demo.py": "VALUE = 'example'\n",
        "services/runtime.py": "VALUE = 'runtime'\n",
        "services/test_support/runtime.py": "VALUE = 'runtime support'\n",
        "services/tests/test_runtime.py": "VALUE = 'test'\n",
        "vendor/dependency.py": "VALUE = 'vendor'\n",
    }
    for relpath, source in tracked_sources.items():
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    untracked_writer = tmp_path / "other/untracked_writer.py"
    untracked_writer.parent.mkdir(parents=True)
    untracked_writer.write_text(
        f'''\
from huggingface_hub import HfApi
HfApi().delete_repo(repo_id="{PROTECTED}")
''',
        encoding="utf-8",
    )
    _git_add(tmp_path, *tracked_sources)

    report = audit.inventory_mutation_paths(repository_root=tmp_path)
    projection = audit.mutation_source_projection(repository_root=tmp_path)

    scanned_paths = [item["path"] for item in projection]
    expected_scanned = [
        ".github/actions/check.py",
        "benchmarks/measure.py",
        "examples/demo.py",
        "services/runtime.py",
        "services/test_support/runtime.py",
    ]
    assert scanned_paths == expected_scanned
    assert report["callsite_count"] == 0
    scope = report["source_scope"]
    assert scope["tracked_python_count"] == 9
    assert scope["tracked_python_paths_sha256"] == audit._canonical_path_digest(
        tracked_sources
    )
    assert scope["scanned_python_count"] == 5
    assert scope["scanned_python_paths_sha256"] == audit._canonical_path_digest(
        expected_scanned
    )
    assert scope["excluded_python_count"] == 4
    assert scope["excluded_python_paths_sha256"] == audit._canonical_path_digest(
        set(tracked_sources) - set(expected_scanned)
    )
    exclusions = {
        item["category"]: item for item in scope["exclusion_policy"]
    }
    assert {
        category: item["excluded_python_count"]
        for category, item in exclusions.items()
    } == {"archive": 1, "vendor": 1, "generated": 1, "tests": 1}


def test_paired_capture_cannot_bind_safe_ast_to_restored_unsafe_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    relpath = "services/legal_runtime/hub_writer.py"
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    safe_source = b"VALUE = 'captured safe source'\n"
    unsafe_source = f'''\
from huggingface_hub import HfApi
HfApi().delete_repo(repo_id="{PROTECTED}")
'''.encode()
    target.write_bytes(unsafe_source)
    _git_add(tmp_path, relpath)

    capture_requested = threading.Event()
    safe_installed = threading.Event()
    capture_finished = threading.Event()
    unsafe_restored = threading.Event()
    swap_errors: list[BaseException] = []
    reads: list[bytes] = []
    real_reader = audit._read_componentwise_regular_source

    def _swap_and_restore() -> None:
        try:
            assert capture_requested.wait(timeout=5)
            safe_swap = target.with_name("hub_writer.safe")
            safe_swap.write_bytes(safe_source)
            os.replace(safe_swap, target)
            safe_installed.set()
            assert capture_finished.wait(timeout=5)
            unsafe_swap = target.with_name("hub_writer.unsafe")
            unsafe_swap.write_bytes(unsafe_source)
            os.replace(unsafe_swap, target)
            unsafe_restored.set()
        except BaseException as exc:  # noqa: BLE001 - surfaced on the test thread
            swap_errors.append(exc)
            safe_installed.set()
            unsafe_restored.set()

    def _synchronized_reader(root_descriptor: int, path: str) -> bytes:
        if path != relpath or reads:
            return real_reader(root_descriptor, path)
        capture_requested.set()
        assert safe_installed.wait(timeout=5)
        payload = real_reader(root_descriptor, path)
        reads.append(payload)
        capture_finished.set()
        assert unsafe_restored.wait(timeout=5)
        return payload

    swapper = threading.Thread(target=_swap_and_restore, daemon=True)
    monkeypatch.setattr(
        audit,
        "_read_componentwise_regular_source",
        _synchronized_reader,
    )
    swapper.start()
    try:
        capture = audit.capture_mutation_audit(repository_root=tmp_path)
    finally:
        capture_requested.set()
        capture_finished.set()
        swapper.join(timeout=5)

    assert not swapper.is_alive()
    assert swap_errors == []
    assert reads == [safe_source]
    assert target.read_bytes() == unsafe_source
    assert capture.report["callsite_count"] == 0
    assert capture.report["unprotected_count"] == 0
    assert capture.report["status"] == "passed"
    assert capture.source_projection == (
        {
            "path": relpath,
            "sha256": audit.hashlib.sha256(safe_source).hexdigest(),
            "size_bytes": len(safe_source),
        },
    )


def test_default_scope_rejects_tracked_python_symlink(tmp_path: Path) -> None:
    relpath = "services/linked.py"
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    target.symlink_to("missing-target.py")
    _git_add(tmp_path, relpath)

    with pytest.raises(audit.MutationPathAuditError, match="must not be a symlink"):
        audit.inventory_mutation_paths(repository_root=tmp_path)


def test_default_scope_rejects_tracked_python_nonregular_file(tmp_path: Path) -> None:
    relpath = "services/runtime.py"
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    _git_add(tmp_path, relpath)
    target.unlink()
    os.mkfifo(target)

    with pytest.raises(audit.MutationPathAuditError, match="not a regular file"):
        audit.inventory_mutation_paths(repository_root=tmp_path)


def test_default_scope_rejects_unreadable_tracked_python(
    tmp_path: Path,
    monkeypatch,
) -> None:
    relpath = "services/runtime.py"
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    _git_add(tmp_path, relpath)
    real_open = audit.os.open

    def _deny_target(
        path: object,
        flags: int,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == target.name and dir_fd is not None:
            raise PermissionError("denied by test")
        if dir_fd is None:
            return real_open(path, flags)
        return real_open(path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(audit.os, "open", _deny_target)

    with pytest.raises(audit.MutationPathAuditError, match="unreadable"):
        audit.inventory_mutation_paths(repository_root=tmp_path)


def test_syntax_error_is_byte_bound_non_executable_source_not_a_blocker(
    tmp_path: Path,
) -> None:
    source = b"def broken(:\n"
    relpath = Path("services/broken_migration.py")
    target = tmp_path / relpath
    target.parent.mkdir(parents=True)
    target.write_bytes(source)

    report = audit.inventory_mutation_paths(
        repository_root=tmp_path,
        scan_roots=(relpath.parent,),
    )

    assert report["syntax_errors"] == []
    assert report["status"] == "passed"
    assert report["non_executable_sources"] == [
        {
            "path": relpath.as_posix(),
            "sha256": audit.hashlib.sha256(source).hexdigest(),
            "size_bytes": len(source),
            "error_type": "SyntaxError",
            "line": 1,
            "column": 12,
            "message": "invalid syntax",
        }
    ]


@pytest.mark.parametrize(
    ("method", "arguments"),
    sorted(_PINNED_HF_API_WRITE_CALL_ARGUMENTS.items()),
)
@pytest.mark.parametrize("aliased", (False, True), ids=("direct", "aliased"))
def test_pinned_hf_api_write_surface_is_inventoried_for_direct_and_alias_calls(
    tmp_path: Path,
    method: str,
    arguments: str,
    aliased: bool,
) -> None:
    invocation = (
        f"writer = api.{method}\n    writer({arguments})"
        if aliased
        else f"api.{method}({arguments})"
    )
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def mutate():
    api = HfApi()
    {invocation}
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == method
    assert callsite["protected_repos"] == [PROTECTED]
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1


@pytest.mark.parametrize("aliased", (False, True), ids=("direct", "aliased"))
def test_move_repo_protected_destination_is_inventoried(
    tmp_path: Path,
    aliased: bool,
) -> None:
    arguments = f'from_id="justicedao/source", to_id="{PROTECTED}"'
    invocation = (
        f"writer = api.move_repo\n    writer({arguments})"
        if aliased
        else f"api.move_repo({arguments})"
    )
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def mutate():
    api = HfApi()
    {invocation}
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "move_repo"
    assert callsite["protected_repos"] == [PROTECTED]
    assert callsite["protected_target"] is True


def _exact_two_stage_source() -> str:
    return '''\
import os
from collections import OrderedDict
from dataclasses import dataclass
from ipfs_datasets_py.huggingface.protected_repo_guard import guarded_write, require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

_CANONICAL_HF_API_METHODS = {"create_commit": lambda api, **kwargs: None}
_PROTECTED_TRANSPORT_ENV_NAMES = ()

def _assert_canonical_hf_api_executables_current():
    pass

def _new_canonical_hf_api(runtime_token):
    return object()

def _fresh_canonical_hf_session():
    _assert_canonical_hf_api_executables_current()
    configured = tuple(
        name
        for name in _PROTECTED_TRANSPORT_ENV_NAMES
        if str(os.environ.get(name) or "").strip()
    )
    if configured:
        raise RuntimeError("environment drift")
    _CANONICAL_HF_RESET_SESSIONS()
    session = _CANONICAL_HF_GET_SESSION()
    if type(session) is not _CANONICAL_REQUESTS_SESSION_TYPE or _CANONICAL_HF_GET_SESSION() is not session:
        raise RuntimeError("session drift")
    state = object.__getattribute__(session, "__dict__")
    if type(state) is not dict or set(state) != {
        "adapters",
        "auth",
        "cert",
        "cookies",
        "headers",
        "hooks",
        "max_redirects",
        "params",
        "proxies",
        "stream",
        "trust_env",
        "verify",
    }:
        raise RuntimeError("session surface drift")
    headers = state["headers"]
    hooks = state["hooks"]
    cookies = state["cookies"]
    adapters = state["adapters"]
    header_items = tuple(
        sorted((str(key).casefold(), str(value)) for key, value in headers.items())
    ) if type(headers) is _CANONICAL_HEADER_DICT_TYPE else ()
    if (
        header_items != _CANONICAL_REQUESTS_DEFAULT_HEADERS
        or state["auth"] is not None
        or type(state["proxies"]) is not dict
        or state["proxies"]
        or type(hooks) is not dict
        or set(hooks) != {"response"}
        or type(hooks["response"]) is not list
        or hooks["response"]
        or type(state["params"]) is not dict
        or state["params"]
        or state["stream"] is not False
        or state["verify"] is not True
        or state["cert"] is not None
        or type(state["max_redirects"]) is not int
        or isinstance(state["max_redirects"], bool)
        or state["max_redirects"] != 30
        or state["trust_env"] is not True
        or type(cookies) is not _CANONICAL_COOKIE_JAR_TYPE
        or len(cookies) != 0
        or type(adapters) is not OrderedDict
        or tuple(adapters) != ("https://", "http://")
    ):
        raise RuntimeError("session config drift")
    for adapter in adapters.values():
        adapter_state = object.__getattribute__(adapter, "__dict__")
        retries = adapter_state.get("max_retries") if type(adapter_state) is dict else None
        if (
            type(adapter) is not _CANONICAL_HF_ADAPTER_TYPE
            or type(adapter_state) is not dict
            or set(adapter_state) != {
                "_pool_block",
                "_pool_connections",
                "_pool_maxsize",
                "config",
                "max_retries",
                "poolmanager",
                "proxy_manager",
            }
            or adapter_state["config"] != {}
            or adapter_state["proxy_manager"] != {}
            or adapter_state["_pool_connections"] != 10
            or adapter_state["_pool_maxsize"] != 10
            or adapter_state["_pool_block"] is not False
            or getattr(retries, "total", None) != 0
            or getattr(retries, "read", None) is not False
        ):
            raise RuntimeError("adapter drift")
    state["trust_env"] = False
    if (
        _CANONICAL_HF_GET_SESSION() is not session
        or object.__getattribute__(session, "__dict__").get("trust_env") is not False
    ):
        raise RuntimeError("session replacement")
    return session

def _canonical_hf_api_create_commit(runtime_token, /, **kwargs):
    """Fixed fixture transport."""
    _assert_canonical_hf_api_executables_current()
    if "token" in kwargs:
        raise RuntimeError("token must be boundary-owned")
    api = _new_canonical_hf_api(runtime_token)
    if object.__getattribute__(api, "__dict__").get("token") != runtime_token:
        raise RuntimeError("token drift")
    session = _fresh_canonical_hf_session()
    if _CANONICAL_HF_GET_SESSION() is not session:
        raise RuntimeError("session drift")
    return _CANONICAL_HF_API_METHODS["create_commit"](
        api,
        token=runtime_token,
        **kwargs,
    )

@dataclass(frozen=True)
class _StateLawsCanonicalCommitPreflight:
    canonical_candidate_digest: str
    canonical_message: str
    mutation_binding: object
    operations_payload: tuple

    def prepare(self, decision, runtime_token):
        canonical_candidate_digest = self.canonical_candidate_digest
        return _PreparedStateLawsCanonicalCommitExecutor(
            canonical_candidate_digest=canonical_candidate_digest,
            canonical_message=self.canonical_message,
            mutation_binding=self.mutation_binding,
            operations_payload=self.operations_payload,
            runtime_token=runtime_token,
        )

@dataclass(frozen=True)
class _PreparedStateLawsCanonicalCommitExecutor:
    canonical_candidate_digest: str
    canonical_message: str
    mutation_binding: object
    operations_payload: tuple
    runtime_token: str

    def __call__(self):
        payload_digest = self.mutation_binding.payload_digest
        require_unprotected_or_runtime(
            self.mutation_binding.repository_id,
            method="create_commit",
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=self.canonical_candidate_digest,
            expected_payload_digest=payload_digest,
        )

        def commit_once():
            return _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )

        return guarded_write(
            self.mutation_binding.repository_id,
            "create_commit",
            commit_once,
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=self.canonical_candidate_digest,
            expected_payload_digest=payload_digest,
        )

def mutate(request, binding):
    preflight = _StateLawsCanonicalCommitPreflight(
        "a" * 64,
        "message",
        binding,
        (),
    )
    return authorize_and_mutate_canonical(request, preflight)
'''


def _exact_runtime_authority_source() -> str:
    return '''\
def authorize_and_mutate_canonical(request, mutation_executor):
    prepared_executor = prepare_method(mutation_executor, bound, runtime_token)
    prepared_call = _require_attested_prepared_executor(
        prepared_executor,
        expected_binding=executor_binding,
        expected_candidate_digest=bound.final_manifest_digest,
        runtime_token=runtime_token,
    )
    final_executor_binding, final_prepare_method = (
        _require_attested_mutation_executor(mutation_executor)
    )
    final_prepared_call = _require_attested_prepared_executor(
        prepared_executor,
        expected_binding=executor_binding,
        expected_candidate_digest=bound.final_manifest_digest,
        runtime_token=runtime_token,
    )
    if (
        final_executor_binding != executor_binding
        or final_prepare_method is not prepare_method
        or final_prepared_call is not prepared_call
    ):
        raise RuntimeError("executor drift")
    with _canonical_runtime_authorization(
        repository_id=bound.dataset_repo_id,
        phase=bound.phase,
        operation=bound.operation,
        final_manifest_digest=bound.final_manifest_digest,
        mutation_binding=executor_binding,
        preflight_executor=mutation_executor,
        prepare_method=prepare_method,
        prepared_executor=prepared_executor,
        prepared_call=prepared_call,
        principal=final_snapshot['principal'],
        principal_authority_digest=final_snapshot['principal_authority_digest'],
        principal_probe=req.principal_probe,
        credential_identity=final_snapshot['credential_identity'],
        credentials_scope=final_snapshot['credentials_scope'],
        token_env=final_snapshot['token_env'],
    ) as authorization:
        result = prepared_call(prepared_executor)
        _assert_canonical_runtime_authorization_consumed(authorization)
        return result

class _CanonicalPublicationRuntimeExecutable:
    pass

_register_canonical_runtime_trust_anchor(
    runtime_module=sys.modules[__name__],
    authorizer=authorize_and_mutate_canonical,
    runtime_executable=_CanonicalPublicationRuntimeExecutable,
)
del _register_canonical_runtime_trust_anchor
'''


def test_imported_but_unused_runtime_does_not_authorize_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate():
    api = HfApi()
    api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1
    assert report["status"] == "blocked"


def test_module_level_write_call_is_inventoried(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

api = HfApi()
api.delete_repo(repo_id="{PROTECTED}")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["function"] == "<module>"
    assert callsite["write_method"] == "delete_repo"
    assert callsite["protection"] == "unprotected"


def test_write_alias_and_rebinding_are_resolved(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

TARGET = "{PROTECTED}"

def mutate():
    api = HfApi()
    commit = api.repo_info
    commit = api.create_commit
    commit(repo_id=TARGET, operations=[])
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "create_commit"
    assert callsite["protection"] == "unprotected"


def test_method_resolver_alias_is_a_write_not_a_read(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
class Publisher:
    def publish(self):
        writer = self._require_api_method("create_commit")
        writer(repo_id="{PROTECTED}", operations=[])
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "create_commit"
    assert callsite["protection"] == "unprotected"


def test_partial_write_alias_with_bound_repo_is_resolved(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from functools import partial as bind
from huggingface_hub import HfApi

def mutate():
    api = HfApi()
    writer = bind(api.upload_file, repo_id="{PROTECTED}")
    writer(path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "upload_file"
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"


def test_hf_api_and_repo_info_read_are_not_mutations(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def probe():
    api = HfApi()
    return api.repo_info(repo_id="{PROTECTED}", repo_type="dataset")
''',
    )
    assert report["callsite_count"] == 0
    assert report["unprotected_count"] == 0
    assert report["status"] == "passed"


def test_guard_in_unrelated_function_does_not_protect_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def unused_guard():
    require_unprotected_or_runtime("{PROTECTED}", method="upload_file")

def mutate():
    api = HfApi()
    api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_protected_literal_in_unrelated_function_does_not_taint_arbitrary_value(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def documentation_value():
    return "{PROTECTED}"

def generic_writer(target):
    api = HfApi()
    api.upload_file(repo_id=target, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protected_target"] is False
    assert callsite["protection"] == "not_a_proven_protected_target"
    assert report["unprotected_count"] == 0


def test_uncalled_public_repo_parameter_is_potentially_protected(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi

def evil(repo_id):
    HfApi().upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["repo_expression"] == "repo_id"
    assert callsite["potential_protected_target"] is True
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1
    assert report["status"] == "blocked"


def test_unknown_repository_bearing_attribute_is_potentially_protected(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi

def evil(config):
    api = HfApi()
    api.create_commit(repo_id=config.repository_id, operations=[])
''',
    )
    callsite = _only_callsite(report)
    assert callsite["repo_expression"] == "config.repository_id"
    assert callsite["potential_protected_target"] is True
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1


def test_protected_repo_matching_is_case_insensitive_through_aliases(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi

TARGET = "JusticeDAO/IPFS_State_Laws"

def mutate():
    alias = TARGET
    api = HfApi()
    api.upload_file(repo_id=alias, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protected_target"] is True
    assert callsite["protected_repos"] == [PROTECTED]
    assert callsite["protection"] == "unprotected"


def test_legacy_guard_must_dominate_api_construction_and_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(repo_id="{PROTECTED}"):
    require_unprotected_or_runtime(repo_id, method="upload_file")
    api = HfApi()
    api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "legacy_dominating_guard"
    assert callsite["guard_lines"]
    assert report["unprotected_count"] == 0


def test_legacy_guard_accepts_dynamic_same_repository_parameter(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(repo_id):
    require_unprotected_or_runtime(repo_id, method="upload_file")
    api = HfApi()
    api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["potential_protected_target"] is True
    assert callsite["protection"] == "legacy_dominating_guard"
    assert report["unprotected_count"] == 0


def test_guard_for_different_object_attribute_does_not_authorize(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

class Writer:
    def mutate(self):
        require_unprotected_or_runtime(self.audit_repo_id, method="upload_file")
        api = HfApi()
        api.upload_file(
            repo_id=self.repository_id,
            path_or_fileobj="x",
            path_in_repo="x",
        )
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_guard_after_api_construction_is_not_dominating(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(repo_id="{PROTECTED}"):
    api = HfApi()
    require_unprotected_or_runtime(repo_id, method="upload_file")
    api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert "construction" in str(callsite["reason"])


def test_caller_forgeable_runtime_override_is_not_a_guard(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(runtime_authorized=False):
    require_unprotected_or_runtime(
        "{PROTECTED}",
        method="upload_file",
        runtime_authorized=runtime_authorized,
    )
    api = HfApi()
    api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_raw_canonical_lambda_callback_is_not_authority(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate(request):
    api = HfApi()
    return authorize_and_mutate_canonical(
        request,
        lambda decision: api.create_commit(repo_id="{PROTECTED}", operations=[]),
    )
''',
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is True
    assert callsite["protection"] == "unprotected"
    assert "ancestry" in str(callsite["reason"])
    assert report["unprotected_count"] == 1


def test_exact_bound_guarded_lambda_is_still_not_attested_executor(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import (
    guarded_write,
    require_unprotected_or_runtime,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        manifest_digest = "a" * 64
        payload_digest = "b" * 64
        require_unprotected_or_runtime(
            repo_id,
            method="create_commit",
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=manifest_digest,
            expected_payload_digest=payload_digest,
        )
        api = HfApi()
        return guarded_write(
            repo_id,
            "create_commit",
            lambda: api.create_commit(repo_id=repo_id, operations=[]),
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=manifest_digest,
            expected_payload_digest=payload_digest,
        )
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is True
    assert callsite["attested_executor"] is False
    assert callsite["protection"] == "unprotected"
    assert callsite["guarded_write_exact_binding"] is True
    assert callsite["guarded_write_individual"] is True
    assert callsite["exact_binding_guard_lines"]
    assert "source-attested" in str(callsite["reason"])
    assert report["unprotected_count"] == 1


def test_guarded_write_missing_payload_binding_is_not_canonical_authority(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import guarded_write, require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        require_unprotected_or_runtime(
            repo_id, method="create_commit", expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
        api = HfApi()
        return guarded_write(
            repo_id, "create_commit",
            lambda: api.create_commit(repo_id=repo_id, operations=[]),
            expected_phase="state_main", expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64,
        )
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert callsite["guarded_write_exact_binding"] is False
    assert "missing an exact payload binding" in str(callsite["reason"])


def test_guard_and_wrapper_payload_bindings_must_be_identical(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import guarded_write, require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        manifest_digest = "a" * 64
        payload_digest = "b" * 64
        other_payload_digest = "c" * 64
        require_unprotected_or_runtime(
            repo_id, method="create_commit", expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=manifest_digest,
            expected_payload_digest=payload_digest,
        )
        api = HfApi()
        return guarded_write(
            repo_id, "create_commit",
            lambda: api.create_commit(repo_id=repo_id, operations=[]),
            expected_phase="state_main", expected_operation="additive_main_upload",
            expected_manifest_digest=manifest_digest,
            expected_payload_digest=other_payload_digest,
        )
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert "identical exact payload binding" in str(callsite["reason"])


def test_guarded_write_method_must_match_individual_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import guarded_write, require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        require_unprotected_or_runtime(
            repo_id, method="create_commit", expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
        api = HfApi()
        return guarded_write(
            repo_id, "upload_file",
            lambda: api.create_commit(repo_id=repo_id, operations=[]),
            expected_phase="state_main", expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert "target or method" in str(callsite["reason"])


def test_exact_guard_after_method_resolution_is_not_dominating(tmp_path: Path) -> None:
    source = (
        _exact_two_stage_source()
        .replace(
            """\
        payload_digest = self.mutation_binding.payload_digest
        require_unprotected_or_runtime(
""",
            """\
        payload_digest = self.mutation_binding.payload_digest
        writer = _canonical_hf_api_create_commit
        require_unprotected_or_runtime(
""",
        )
        .replace(
            "return _canonical_hf_api_create_commit(\n",
            "return writer(\n",
        )
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert callsite["attested_executor"] is True
    assert "does not dominate" in str(callsite["reason"])


def test_method_alias_lambda_alias_and_partial_cannot_replace_sealed_executor(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from functools import partial
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import guarded_write, require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        require_unprotected_or_runtime(
            repo_id, method="create_commit", expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
        writer = HfApi().create_commit
        callback = lambda: writer(repo_id=repo_id, operations=[])
        return guarded_write(
            repo_id, "create_commit", callback,
            expected_phase="state_main", expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
    return authorize_and_mutate_canonical(request, partial(commit))
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert callsite["attested_executor"] is False
    assert callsite["guarded_write_individual"] is True


def test_partial_bound_write_cannot_replace_sealed_executor(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from functools import partial
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import guarded_write, require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        require_unprotected_or_runtime(
            repo_id, method="create_commit", expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
        writer = HfApi().create_commit
        return guarded_write(
            repo_id, "create_commit",
            partial(writer, repo_id=repo_id, operations=[]),
            expected_phase="state_main", expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert callsite["attested_executor"] is False
    assert callsite["guarded_write_individual"] is True


def test_fake_guarded_write_name_does_not_enclose_canonical_mutation(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import authorize_and_mutate_canonical

def guarded_write(repo_id, method, callback, **kwargs):
    return callback()

def mutate(request, repo_id="{PROTECTED}"):
    def commit(decision):
        require_unprotected_or_runtime(
            repo_id, method="create_commit", expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
        api = HfApi()
        return guarded_write(
            repo_id, "create_commit",
            lambda: api.create_commit(repo_id=repo_id, operations=[]),
            expected_phase="state_main", expected_operation="additive_main_upload",
            expected_manifest_digest="a" * 64, expected_payload_digest="b" * 64,
        )
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert callsite["guarded_write_lines"] == []


def test_exact_two_stage_preflight_resolves_prepared_executor_call(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        _exact_two_stage_source(),
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is True
    assert callsite["attested_executor"] is True
    assert "canonical_runtime" in callsite["protection_variants"]
    assert callsite["guarded_write_exact_binding"] is True
    assert callsite["prepared_binding_exact"] is True
    assert callsite["api_primitive_attested"] is True
    assert callsite["api_primitive_exact_call"] is True
    assert report["unprotected_count"] == 0


def test_live_publisher_closure_factory_attestation_is_exact() -> None:
    publisher = audit.REPOSITORY_ROOT / audit._PUBLISHER_RELPATH
    tree = audit.ast.parse(publisher.read_bytes(), filename=str(publisher))

    attestation = audit._attested_prepared_factory_call(tree)

    assert attestation is not None
    prepared_call, assignment_call = attestation
    assert prepared_call.name == "prepared_call"
    assert audit._source(assignment_call.func) == audit._PREPARED_CALL_FACTORY


@pytest.mark.parametrize(
    ("label", "old", "new"),
    (
        (
            "spoofed_helper",
            "        create_commit=_canonical_hf_api_create_commit,\n",
            "        create_commit=guarded_write,\n",
        ),
        (
            "spoofed_branch_helper",
            "        create_branch=_canonical_hf_api_create_branch,\n",
            "        create_branch=guarded_write,\n",
        ),
        (
            "renamed_transport",
            "        def commit_once() -> Any:\n",
            "        def renamed_commit() -> Any:\n",
        ),
        (
            "renamed_branch_transport",
            "            def branch_once() -> Any:\n",
            "            def renamed_branch() -> Any:\n",
        ),
        (
            "phase_binding_drift",
            "        phase = f\"{corpus}_{target}\"\n",
            '        phase = "state_main"\n',
        ),
        (
            "branch_method_binding_drift",
            '                method="create_branch",\n',
            "                method=self.mutation_binding.method,\n",
        ),
        (
            "missing_helper",
            "        rehash_files=_rehash_prepared_snapshot_files,\n",
            "",
        ),
        (
            "same_named_spoof",
            "class HuggingFacePublicationError(ValueError):\n",
            (
                "def guarded_write(*args, **kwargs):\n"
                "    return None\n\n\n"
                "class HuggingFacePublicationError(ValueError):\n"
            ),
        ),
    ),
)
def test_publisher_closure_factory_drift_fails_closed(
    tmp_path: Path,
    label: str,
    old: str,
    new: str,
) -> None:
    publisher = audit.REPOSITORY_ROOT / audit._PUBLISHER_RELPATH
    source = publisher.read_text(encoding="utf-8")
    assert old in source, label

    report = _audit_source(
        tmp_path / label,
        source.replace(old, new, 1),
        relpath=Path(audit._PUBLISHER_RELPATH),
    )

    assert report["status"] == "blocked", label
    assert any(
        item["symbol"] == audit._PREPARED_CALL_FACTORY
        and item["error"]
        in {
            "prepared_executor_factory_or_assignment_not_exact",
            "prepared_executor_factory_helpers_not_exact",
        }
        for item in report["authority_boundary_violations"]
    ), label


def test_live_publisher_legacy_fallback_requires_exact_dominating_guard(
    tmp_path: Path,
) -> None:
    publisher = audit.REPOSITORY_ROOT / audit._PUBLISHER_RELPATH
    source = publisher.read_text(encoding="utf-8")
    guard = '''\
                require_unprotected_or_runtime(
                    self.repository_id,
                    method="create_commit",
                )
'''
    assert source.count(guard) == 1

    report = _audit_source(
        tmp_path,
        source.replace(guard, "", 1),
        relpath=Path(audit._PUBLISHER_RELPATH),
    )

    fallback = [
        item
        for item in report["callsites"]
        if item["function"]
        == "HuggingFaceReleasePublisher.publish_append_only.<locals>.execute_commit"
    ]
    assert len(fallback) == 1
    assert fallback[0]["protection"] == "unprotected"
    assert report["status"] == "blocked"
    assert report["unprotected_count"] >= 1


def test_session_boundary_drift_deattests_create_commit(
    tmp_path: Path,
) -> None:
    replacements = {
        "missing_cache_reset": (
            "    _CANONICAL_HF_RESET_SESSIONS()\n",
            "",
        ),
        "response_hook_allowed": (
            '        or hooks["response"]\n',
            '        or (hooks["response"] and False)\n',
        ),
        "unsafe_trust_env": (
            '    state["trust_env"] = False\n',
            '    state["trust_env"] = True\n',
        ),
        "missing_same_session_recheck": (
            (
                '    if (\n'
                '        _CANONICAL_HF_GET_SESSION() is not session\n'
                '        or object.__getattribute__(session, "__dict__").get("trust_env") is not False\n'
                '    ):\n'
                '        raise RuntimeError("session replacement")\n'
            ),
            "",
        ),
    }
    for label, (old, new) in replacements.items():
        source = _exact_two_stage_source()
        assert old in source, label
        report = _audit_source(
            tmp_path / label,
            source.replace(old, new, 1),
            relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
        )
        callsite = _only_callsite(report)
        assert callsite["api_primitive_attested"] is False, label
        assert callsite["protection"] == "unprotected", label
        assert report["status"] == "blocked", label


def test_prepared_alias_partial_and_lambda_cannot_replace_preflight(
    tmp_path: Path,
) -> None:
    original = '''\
def mutate(request, binding):
    preflight = _StateLawsCanonicalCommitPreflight(
        "a" * 64,
        "message",
        binding,
        (),
    )
    return authorize_and_mutate_canonical(request, preflight)
'''
    replacements = {
        "alias": '''\
def mutate(request, binding):
    prepared = _PreparedStateLawsCanonicalCommitExecutor(
        "a" * 64, "message", binding, (), "token"
    )
    callback = prepared
    return authorize_and_mutate_canonical(request, callback)
''',
        "partial": '''\
def mutate(request, binding):
    prepared = _PreparedStateLawsCanonicalCommitExecutor(
        "a" * 64, "message", binding, (), "token"
    )
    callback = partial(prepared)
    return authorize_and_mutate_canonical(request, callback)
''',
        "lambda": '''\
def mutate(request, binding):
    prepared = _PreparedStateLawsCanonicalCommitExecutor(
        "a" * 64, "message", binding, (), "token"
    )
    callback = lambda: prepared()
    return authorize_and_mutate_canonical(request, callback)
''',
    }
    for label, replacement in replacements.items():
        source = _exact_two_stage_source().replace(original, replacement)
        if label == "partial":
            source = source.replace(
                "from dataclasses import dataclass\n",
                "from dataclasses import dataclass\nfrom functools import partial\n",
            )
        report = _audit_source(
            tmp_path / label,
            source,
            relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
        )
        callsite = _only_callsite(report)
        assert callsite["canonical_callback"] is False, label
        assert callsite["attested_executor"] is False, label
        assert callsite["protection"] == "unprotected", label
        assert "preflight-to-prepared" in str(callsite["reason"]), label


def test_preflight_must_construct_exact_prepared_capsule(tmp_path: Path) -> None:
    source = _exact_two_stage_source().replace(
        "return _PreparedStateLawsCanonicalCommitExecutor(\n",
        "return build_prepared_capsule(\n",
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is False
    assert callsite["attested_executor"] is False
    assert callsite["protection"] == "unprotected"
    assert "preflight-to-prepared" in str(callsite["reason"])


def test_prepared_transport_requires_exact_runtime_token_and_wrapper_binding(
    tmp_path: Path,
) -> None:
    token_mismatch = _exact_two_stage_source().replace(
        """\
            return _canonical_hf_api_create_commit(
                self.runtime_token,
""",
        """\
            return _canonical_hf_api_create_commit(
                self.canonical_message,
""",
    )
    base = _exact_two_stage_source()
    before, marker, after = base.rpartition(
        "expected_payload_digest=payload_digest"
    )
    assert marker
    binding_mismatch = (
        before
        + "expected_payload_digest=self.canonical_candidate_digest"
        + after
    )
    cases = {
        "token": (token_mismatch, "exact prepared token and binding"),
        "binding": (binding_mismatch, "identical exact payload binding"),
    }
    for label, (source, reason) in cases.items():
        report = _audit_source(
            tmp_path / label,
            source,
            relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
        )
        callsite = _only_callsite(report)
        assert callsite["attested_executor"] is True, label
        assert callsite["protection"] == "unprotected", label
        assert reason in str(callsite["reason"]), label


def test_prepared_executor_guarded_callback_cannot_delegate_the_write(
    tmp_path: Path,
) -> None:
    source = _exact_two_stage_source().replace(
        """\
        def commit_once():
            return _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )
""",
        """\
        def helper():
            return _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )

        def commit_once():
            return helper()
""",
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsite = _only_callsite(report)
    assert callsite["attested_executor"] is True
    assert callsite["guarded_write_individual"] is False
    assert callsite["protection"] == "unprotected"
    assert "delegates beyond" in str(callsite["reason"])


def test_injected_create_commit_property_and_generic_resolver_are_both_blocked(
    tmp_path: Path,
) -> None:
    source = _exact_two_stage_source().replace(
        "from dataclasses import dataclass\n",
        f'''\
from dataclasses import dataclass
from huggingface_hub import HfApi

class InjectedApi:
    @property
    def create_commit(self):
        HfApi().delete_repo(repo_id="{PROTECTED}")
        return lambda **kwargs: None

class Publisher:
    def __init__(self):
        self.api = InjectedApi()

    def _require_api_method(self, name):
        return getattr(self.api, name)
''',
    ).replace(
        """\
        def commit_once():
            return _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )
""",
        """\
        writer = Publisher()._require_api_method("create_commit")

        def commit_once():
            return writer(
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )
""",
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsites = report["callsites"]
    assert isinstance(callsites, list)
    by_method = {item["write_method"]: item for item in callsites}
    assert {"create_commit", "delete_repo"}.issubset(by_method)
    assert by_method["create_commit"]["protection"] == "unprotected"
    assert by_method["create_commit"]["api_primitive_attested"] is False
    assert "injected or unattested" in str(by_method["create_commit"]["reason"])
    assert by_method["delete_repo"]["protection"] == "unprotected"
    assert report["unprotected_count"] >= 2


def test_local_alias_cannot_replace_exact_create_commit_primitive_call(
    tmp_path: Path,
) -> None:
    source = _exact_two_stage_source().replace(
        """\
        def commit_once():
            return _canonical_hf_api_create_commit(
""",
        """\
        writer = _canonical_hf_api_create_commit

        def commit_once():
            return writer(
""",
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsite = _only_callsite(report)
    assert callsite["attested_executor"] is True
    assert callsite["api_primitive_attested"] is True
    assert callsite["api_primitive_exact_call"] is False
    assert callsite["protection"] == "unprotected"
    assert "exact prepared token and binding" in str(callsite["reason"])


def test_injected_uploader_resolved_before_guard_is_not_authorized(
    tmp_path: Path,
) -> None:
    source = (
        _exact_two_stage_source()
        .replace(
            "from dataclasses import dataclass\n",
            "from dataclasses import dataclass\nfrom huggingface_hub import HfApi\n",
        )
        .replace(
            """\
        payload_digest = self.mutation_binding.payload_digest
        require_unprotected_or_runtime(
""",
            """\
        payload_digest = self.mutation_binding.payload_digest
        uploader = HfApi().create_commit
        require_unprotected_or_runtime(
""",
        )
        .replace(
            "return _canonical_hf_api_create_commit(\n",
            "return uploader(\n",
        )
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert callsite["attested_executor"] is True
    assert "does not dominate" in str(callsite["reason"])


def test_one_guarded_write_callback_cannot_cover_two_mutations(tmp_path: Path) -> None:
    source = _exact_two_stage_source().replace(
        """\
        def commit_once():
            return _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )
""",
        """\
        def commit_once():
            _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )
            return _canonical_hf_api_create_commit(
                self.runtime_token,
                repo_id=self.mutation_binding.repository_id,
                repo_type=self.mutation_binding.repository_type,
                operations=self.operations_payload,
                commit_message=self.canonical_message,
                revision=self.mutation_binding.revision,
                parent_commit=self.mutation_binding.parent_commit,
            )
""",
    )
    report = _audit_source(
        tmp_path,
        source,
        relpath=Path("ipfs_datasets_py/huggingface/publisher.py"),
    )
    callsites = report["callsites"]
    assert isinstance(callsites, list)
    assert len(callsites) == 2
    assert report["unprotected_count"] == 2
    assert all(item["guarded_write_individual"] is False for item in callsites)
    assert all("more than one" in str(item["reason"]) for item in callsites)


def test_same_named_fake_canonical_attribute_does_not_authorize(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def mutate(fake, request):
    api = HfApi()
    return fake.authorize_and_mutate_canonical(
        request,
        lambda decision: api.create_commit(repo_id="{PROTECTED}", operations=[]),
    )
''',
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is False
    assert callsite["protection"] == "unprotected"


def test_runtime_authority_wraps_only_exact_prepared_call(tmp_path: Path) -> None:
    relpath = Path(
        "ipfs_datasets_py/processors/legal_data/"
        "legal_corpora_publication_runtime.py"
    )
    report = _audit_source(
        tmp_path / "exact",
        _exact_runtime_authority_source(),
        relpath=relpath,
    )
    assert report["authority_boundary_violations"] == []
    assert report["status"] == "passed"

    exact_line = "        result = prepared_call(prepared_executor)\n"
    variants = {
        "alias": (
            "        callback = prepared_call\n"
            "        result = callback(prepared_executor)\n"
        ),
        "partial": (
            "        callback = partial(prepared_call, prepared_executor)\n"
            "        result = callback()\n"
        ),
        "lambda": (
            "        callback = lambda: prepared_call(prepared_executor)\n"
            "        result = callback()\n"
        ),
        "multiple": (
            "        prepared_call(prepared_executor)\n"
            "        result = prepared_call(prepared_executor)\n"
        ),
    }
    for label, replacement in variants.items():
        report = _audit_source(
            tmp_path / label,
            _exact_runtime_authority_source().replace(exact_line, replacement),
            relpath=relpath,
        )
        violations = report["authority_boundary_violations"]
        assert isinstance(violations, list)
        assert any(
            item["error"]
            == "canonical_authority_does_not_wrap_exact_prepared_call"
            for item in violations
        ), label
        assert report["status"] == "blocked", label

    boundary_variants = {
        "missing_final_prepared_attestation": (
            (
                "    final_prepared_call = _require_attested_prepared_executor(\n"
                "        prepared_executor,\n"
                "        expected_binding=executor_binding,\n"
                "        expected_candidate_digest=bound.final_manifest_digest,\n"
                "        runtime_token=runtime_token,\n"
                "    )\n"
            ),
            "    final_prepared_call = prepared_call\n",
        ),
        "missing_prepared_frame_binding": (
            "        prepared_call=prepared_call,\n",
            "",
        ),
        "missing_principal_edge_binding": (
            "        principal=final_snapshot['principal'],\n",
            "",
        ),
        "missing_principal_probe_binding": (
            "        principal_probe=req.principal_probe,\n",
            "",
        ),
    }
    for label, (old, new) in boundary_variants.items():
        source = _exact_runtime_authority_source()
        assert old in source
        report = _audit_source(
            tmp_path / label,
            source.replace(old, new, 1),
            relpath=relpath,
        )
        assert report["status"] == "blocked", label
        assert report["authority_boundary_violations"], label


def test_guard_private_context_seal_and_anchor_references_are_rejected(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from ipfs_datasets_py.huggingface.protected_repo_guard import (
    _canonical_runtime_authorization,
)
from ipfs_datasets_py.huggingface import protected_repo_guard as guard

leaked_context = getattr(guard, "active_authority")
leaked_seal = guard.authority_seal
leaked_anchor = vars(guard)["runtime_anchor"]
leaked_edge = getattr(guard, "_attest_canonical_prepared_write_edge")
leaked_publisher_anchor = getattr(
    guard, "_register_canonical_publisher_trust_anchor"
)
''',
    )
    violations = report["authority_boundary_violations"]
    assert isinstance(violations, list)
    assert {item["symbol"] for item in violations} == {
        "_canonical_runtime_authorization",
        "_attest_canonical_prepared_write_edge",
        "active_authority",
        "authority_seal",
        "runtime_anchor",
        "_register_canonical_publisher_trust_anchor",
    }
    assert report["status"] == "blocked"


def test_reassigned_condition_invalidates_earlier_conditional_guard(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(publish, repo_id="{PROTECTED}"):
    if publish:
        require_unprotected_or_runtime(repo_id, method="upload_file")
    publish = True
    if publish:
        api = HfApi()
        api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_raw_canonical_nested_callback_delegation_is_not_authority(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate(request):
    api = HfApi()
    def commit(decision):
        return api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["function"].endswith("<locals>.commit")
    assert callsite["protection"] == "unprotected"
    assert "guarded_write" in str(callsite["reason"])


def test_fail_closed_probe_does_not_turn_lambda_into_attested_executor(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import (
    guarded_write,
    is_protected_repo,
    require_unprotected_or_runtime,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def publish(repo_id, protected_mode, request):
    if is_protected_repo(repo_id) and not protected_mode:
        raise PermissionError("canonical runtime required")

    def execute():
        manifest_digest = "a" * 64
        payload_digest = "b" * 64
        require_unprotected_or_runtime(
            repo_id,
            method="create_commit",
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=manifest_digest,
            expected_payload_digest=payload_digest,
        )
        api = HfApi()
        return guarded_write(
            repo_id,
            "create_commit",
            lambda: api.create_commit(repo_id=repo_id, operations=[]),
            expected_phase="state_main",
            expected_operation="additive_main_upload",
            expected_manifest_digest=manifest_digest,
            expected_payload_digest=payload_digest,
        )

    if protected_mode:
        return authorize_and_mutate_canonical(
            request,
            lambda decision: execute(),
        )
    else:
        return execute()
''',
    )
    callsite = _only_callsite(report)
    assert callsite["analysis_context_count"] == 2
    assert callsite["protection_variants"] == ["unprotected"]
    assert callsite["protection"] == "unprotected"
    assert "source-attested" in str(callsite["reason"])
    assert report["unprotected_count"] == 1


def test_fail_closed_probe_does_not_authorize_true_branch_without_runtime(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import is_protected_repo

def publish(repo_id, protected_mode):
    if is_protected_repo(repo_id) and not protected_mode:
        raise PermissionError("canonical runtime required")

    def execute():
        return HfApi().create_commit(repo_id=repo_id, operations=[])

    if protected_mode:
        return execute()
    else:
        return execute()
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1


def test_refresh_publish_and_create_selectors_hard_rejection_is_inventoryable(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
async def refresh_state_laws_corpus(args):
    direct_external_mutation_requested = bool(
        getattr(args, "publish_to_hf", False)
        or getattr(args, "create_repo", False)
    )
    if direct_external_mutation_requested:
        return {"status": "failed_preflight"}
    return {"status": "ok"}
''',
    )
    assert report["hard_rejected_functions"] == [
        {
            "path": "scan/subject.py",
            "function": "refresh_state_laws_corpus",
            "line": 6,
            "selector": "direct_external_mutation_requested",
            "selector_expression": "bool(getattr(args, 'publish_to_hf', False) or getattr(args, 'create_repo', False))",
            "mechanism": "refresh_hard_rejection",
        }
    ]


def test_refresh_hard_rejection_does_not_mask_importable_private_writer(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

async def refresh_state_laws_corpus(args):
    direct_external_mutation_requested = bool(
        getattr(args, "publish_to_hf", False)
        or getattr(args, "create_repo", False)
    )
    if direct_external_mutation_requested:
        return {{"status": "failed_preflight"}}

def _publish_state_parquet_file(repo_id="{PROTECTED}"):
    HfApi().upload_file(
        repo_id=repo_id,
        path_or_fileobj="state.parquet",
        path_in_repo="state.parquet",
    )
''',
    )

    callsite = _only_callsite(report)
    assert callsite["function"] == "_publish_state_parquet_file"
    assert callsite["write_method"] == "upload_file"
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1
    assert report["status"] == "blocked"
    assert any(
        item["function"] == "refresh_state_laws_corpus"
        and item["mechanism"] == "refresh_hard_rejection"
        for item in report["hard_rejected_functions"]
    )


def test_live_tree_has_no_unprotected_protected_repo_writer() -> None:
    report = audit.inventory_mutation_paths()
    assert report["authorizing_hub_upload"] is False
    assert report["syntax_errors"] == []
    assert report["authority_boundary_violations"] == []
    assert report["callsite_count"] >= 1
    assert report["protected_callsite_count"] >= 1
    assert report["unprotected_count"] == 0, report["reasons"]
    assert report["status"] == "passed"
    prepared_calls = [
        item
        for item in report["callsites"]
        if item["path"] == "ipfs_datasets_py/huggingface/publisher.py"
        and str(item["function"]).startswith(
            "_PreparedStateLawsCanonicalCommitExecutor.__call__"
        )
    ]
    assert {item["write_method"] for item in prepared_calls} == {
        "create_branch",
        "create_commit",
    }
    assert len(prepared_calls) == 2
    for prepared_call in prepared_calls:
        assert prepared_call["attested_executor"] is True
        assert prepared_call["prepared_binding_exact"] is True
        assert prepared_call["api_primitive_attested"] is True
        assert prepared_call["api_primitive_exact_call"] is True
        assert prepared_call["guarded_write_individual"] is True
        assert "canonical_runtime" in prepared_call["protection_variants"]
    assert any(
        item["function"] == "refresh_state_laws_corpus"
        and item["mechanism"] == "refresh_hard_rejection"
        for item in report["hard_rejected_functions"]
    )


def test_cli_check_rejects_stale_frozen_report(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    measured = _install_freeze_fixture(tmp_path, monkeypatch)
    frozen = dict(measured)
    frozen["required_runtime"] = "stale.runtime"
    report_path = tmp_path / audit.REPORT_RELPATH
    report_path.parent.mkdir(parents=True)
    report_path.write_text(audit._canonical_report_text(frozen), encoding="utf-8")

    assert audit.main(_freeze_cli_args()) == 2
    assert "does not exactly match" in capsys.readouterr().err


def test_cli_check_rejects_malformed_frozen_report(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _install_freeze_fixture(tmp_path, monkeypatch)
    report_path = tmp_path / audit.REPORT_RELPATH
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"schema":', encoding="utf-8")

    assert audit.main(_freeze_cli_args()) == 2
    assert "not strict UTF-8 JSON" in capsys.readouterr().err


def test_cli_check_rejects_duplicate_frozen_report_key(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    measured = _install_freeze_fixture(tmp_path, monkeypatch)
    canonical = audit._canonical_report_text(measured)
    schema_line = f'  "schema": "{audit.SCHEMA}",\n'
    assert schema_line in canonical
    duplicated = canonical.replace(schema_line, schema_line * 2, 1)
    report_path = tmp_path / audit.REPORT_RELPATH
    report_path.parent.mkdir(parents=True)
    report_path.write_text(duplicated, encoding="utf-8")

    assert audit.main(_freeze_cli_args()) == 2
    assert "duplicate key 'schema'" in capsys.readouterr().err


def test_cli_check_rejects_report_that_fails_v2_schema(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    measured = _install_freeze_fixture(tmp_path, monkeypatch)
    frozen = dict(measured)
    frozen["authorizing_hub_upload"] = True
    report_path = tmp_path / audit.REPORT_RELPATH
    report_path.parent.mkdir(parents=True)
    report_path.write_text(audit._canonical_report_text(frozen), encoding="utf-8")

    assert audit.main(_freeze_cli_args()) == 2
    output = capsys.readouterr().err
    assert "fails schema at authorizing_hub_upload" in output
    assert "False was expected" in output


def test_cli_write_canonical_report_then_checks_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    measured = _install_freeze_fixture(tmp_path, monkeypatch)

    assert audit.main(_freeze_cli_args("--write")) == 0
    report_path = tmp_path / audit.REPORT_RELPATH
    assert report_path.read_text(encoding="utf-8") == audit._canonical_report_text(
        measured
    )
    assert audit.main(_freeze_cli_args()) == 0


def test_cli_check_passes_live_tree() -> None:
    assert (
        audit.main(
            [
                "--protected-repo",
                PROTECTED,
                "--protected-repo",
                FEDERAL_REGISTER,
                "--require-runtime",
                "ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime",
                "--check",
            ]
        )
        == 0
    )

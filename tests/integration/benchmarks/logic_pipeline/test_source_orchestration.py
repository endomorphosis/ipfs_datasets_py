"""Isolated live execution tests for the HSSL-G240 source boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.adapters import (
    LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
)
from benchmarks.logic_pipeline.capabilities import (
    BoundedProcessResult,
    CapabilityKind,
    WorktreeSafetyReceipt,
    prepare_isolated_worktree,
)
from benchmarks.logic_pipeline.causal_batch import (
    CausalRuntimeBatchError,
    persist_causal_runtime_batch_v2,
    validate_causal_runtime_batch_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CaseResultRecord,
    FailureCode,
    Split,
    StageName,
    StageStatus,
)
from benchmarks.logic_pipeline.causal_runtime import (
    CompilerReferenceExposureV2,
)
from benchmarks.logic_pipeline.namespace_provenance import (
    G240PrivateReplayValidationSourcesV2,
    G240RuntimeNamespaceEvidenceSetV2,
    build_g240_namespace_policy_v2,
    g240_recursive_gitlinks_cid,
    g240_replay_namespace_request_v2,
    validate_g240_private_replay_sources_v2,
)
from benchmarks.logic_pipeline.replay import run_g240_detached_replay_v2
from benchmarks.logic_pipeline.source_orchestration import (
    SourceRuntimeOrchestrationError,
    _g240_landlock_regular_or_directory,
    _g240_landlock_source_files,
    _g240_protected_path_component,
    _g240_validate_dynamic_read_path,
    _validate_runtime_preflight,
    build_g240_source_executor_contract_v2,
    build_g240_source_orchestration_evidence_set_v2,
    g240_source_git_commit_cid,
    run_g240_source_job_v2,
    validate_g240_private_source_sources_v2,
    validate_g240_source_orchestration_evidence_set_v2,
)
from benchmarks.logic_pipeline.source_bootstrap_contract import (
    G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2,
)
from benchmarks.logic_pipeline.source_bootstrap import (
    G240SourceBootstrapError,
    _observe_source,
)
from benchmarks.logic_pipeline.source_executor import (
    G240_EXECUTION_REQUEST_SCHEMA_V2,
    G240_LIVE_ADAPTER_FACTORY_ID_V2,
    G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
    G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2,
    G240ExecutionRequestV2,
    G240SourceExecutorError,
    _G240DiskCache,
    _G240_SYNTHETIC_TEST_CAPABILITY_V2,
    _g240_replay_compiler_semantic_projection_v2,
    _g240_replay_stage_semantic_projection_v2,
    _semantic_result_cid,
    build_g240_live_adapter_configuration_v2,
    build_g240_synthetic_adapter_configuration_v2,
    validate_g240_production_execution_request_v2,
    validate_g240_runtime_for_execution_request_v2,
)
from benchmarks.logic_pipeline.source_reconciliation import (
    _capture_benchmark_bounded_gitlinks,
    _materialize_recursive_local_gitlinks,
)
from benchmarks.logic_pipeline.runtime import (
    RuntimeBindingError,
    prepare_symai_runtime_configuration,
)
from tests.integration.benchmarks.logic_pipeline.test_causal_runtime_batch import (
    _inputs,
)
from tests.integration.benchmarks.logic_pipeline.test_live_runtime import (
    _inventory as _live_inventory,
)


def _git(
    repository: Path,
    *arguments: str,
    child_umask: int | None = None,
) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        **(
            {}
            if child_umask is None
            else {"umask": child_umask}
        ),
        env={
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )
    return result.stdout.strip()


def _authority(name: str) -> str:
    return cid_for_dag_json(
        {
            "schema": "synthetic-g240-source-authority.v1",
            "name": name,
        }
    )


def _runtime_environment_artifacts(tmp_path: Path) -> dict[str, Path]:
    """Create harmless fixture locks that exercise the production binding."""

    root = tmp_path / "runtime-environment-artifacts"
    root.mkdir()
    lock = root / "requirements.lock"
    receipt = root / "provision-receipt.json"
    lock.write_text("fixture-runtime==1\n", encoding="utf-8")
    receipt.write_text('{"fixture":true}\n', encoding="utf-8")
    lock.chmod(0o444)
    receipt.chmod(0o444)
    return {
        "python_lock": lock.resolve(),
        "provision_receipt": receipt.resolve(),
    }


def _pinned_symai_fixture_runtime(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    """Create one isolated pinned venv package for the production fixture."""

    virtualenv = tmp_path / "pinned-symai-runtime"
    subprocess.run(
        (
            sys.executable,
            "-m",
            "venv",
            "--without-pip",
            virtualenv.as_posix(),
        ),
        check=True,
        capture_output=True,
        timeout=30,
    )
    interpreter = (virtualenv / "bin" / "python").absolute()
    probe = subprocess.run(
        (
            interpreter.as_posix(),
            "-I",
            "-c",
            "import json,site;print(json.dumps(site.getsitepackages()))",
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    site_packages = tuple(
        Path(value).resolve(strict=True)
        for value in json.loads(probe.stdout)
        if Path(value).is_dir()
    )
    selected = tuple(
        path for path in site_packages if path.is_relative_to(virtualenv)
    )
    assert len(selected) == 1
    package = selected[0] / "symai"
    package.mkdir()
    initializer = package / "__init__.py"
    initializer.write_text(
        '__version__ = "1.14.0"\n',
        encoding="utf-8",
    )
    initializer.chmod(0o444)
    package_cid = cid_for_bytes(initializer.read_bytes())
    lock = virtualenv / "symai-runtime.lock"
    lock.write_bytes(
        canonical_dag_json_bytes(
            {
                "schema": "tracked-symai-runtime-lock.v1",
                "distribution": "symbolicai",
                "version": "1.14.0",
                "module": "symai",
                "module_file_cid": package_cid,
            }
        )
        + b"\n"
    )
    lock.chmod(0o444)
    resolved = subprocess.run(
        (
            interpreter.as_posix(),
            "-I",
            "-c",
            (
                "from pathlib import Path;import symai;"
                "print(Path(symai.__file__).resolve())"
            ),
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert Path(resolved.stdout.strip()) == initializer.resolve(strict=True)
    return interpreter, initializer.resolve(strict=True), lock.resolve(
        strict=True
    )


@pytest.mark.parametrize(
    "name",
    (
        "corpus.jsonl",
        "manifest.json",
        "holdout.json",
        "fixture.py",
        "external_fixtures",
        "performance_snapshots",
        "agent_supervisor",
    ),
)
def test_landlock_dynamic_protected_filename_tokens_fail_closed(
    name: str,
) -> None:
    assert _g240_protected_path_component(name) is True


def test_landlock_read_path_rejects_parent_symlink_escape(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical"
    physical.mkdir()
    payload = physical / "tool"
    payload.write_text("#!/bin/sh\n", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)

    assert _g240_landlock_regular_or_directory(payload) == payload
    assert _g240_landlock_regular_or_directory(alias / "tool") is None


def test_direct_source_executor_invocation_requires_bootstrap() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        ),
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        close_fds=True,
        env={
            "PATH": os.defpath,
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
    )

    assert result.returncode != 0
    assert "must be entered by the tracked bootstrap" in result.stderr


def test_dynamic_landlock_grants_reject_protected_and_unreviewed_files(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    worktree = prepared[5]
    contract = prepared[7]
    reviewed = frozenset(
        _g240_landlock_source_files(
            worktree,
            git_executable_path=contract.git_executable_path,
            git_executable_cid=contract.git_executable_cid,
        )
    )
    protected = tmp_path / "corpus.jsonl"
    protected.write_text("unopened protected sentinel\n", encoding="utf-8")
    unreviewed = worktree.worktree_root / "source.txt"

    for candidate in (protected, unreviewed):
        with pytest.raises(
            SourceRuntimeOrchestrationError,
            match="forbidden Git, protected-data, or sensitive",
        ):
            _g240_validate_dynamic_read_path(
                candidate,
                worktree=worktree,
                reviewed_worktree_files=reviewed,
                field="adversarial dynamic path",
            )


def test_landlock_reviewed_sources_exclude_ignored_python_file(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    worktree = prepared[5]
    contract = prepared[7]
    ignored = (
        worktree.worktree_root
        / "benchmarks"
        / "logic_pipeline"
        / "ignored_payload.py"
    )
    exclude = Path(
        _git(
            worktree.worktree_root,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "info/exclude",
        )
    )
    exclude.write_text(
        exclude.read_text(encoding="utf-8")
        + "\n/benchmarks/logic_pipeline/ignored_payload.py\n",
        encoding="utf-8",
    )
    ignored.write_text(
        'raise RuntimeError("ignored source must never be admitted")\n',
        encoding="utf-8",
    )
    assert (
        _git(
            worktree.worktree_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        == ""
    )

    reviewed = frozenset(
        _g240_landlock_source_files(
            worktree,
            git_executable_path=contract.git_executable_path,
            git_executable_cid=contract.git_executable_cid,
        )
    )

    assert ignored.resolve(strict=True) not in reviewed
    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="forbidden Git, protected-data, or sensitive",
    ):
        _g240_validate_dynamic_read_path(
            ignored.resolve(strict=True),
            worktree=worktree,
            reviewed_worktree_files=reviewed,
            field="ignored adversarial Python path",
        )


@pytest.mark.parametrize(
    "mutation",
    ("bytes", "executable-mode", "writable-mode", "symlink"),
)
def test_landlock_reviewed_sources_reject_tracked_source_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    prepared = _prepared(tmp_path)
    worktree = prepared[5]
    contract = prepared[7]
    tracked = (
        worktree.worktree_root
        / "benchmarks"
        / "logic_pipeline"
        / "source_executor.py"
    )
    if mutation == "bytes":
        tracked.write_bytes(
            tracked.read_bytes() + b"\n# adversarial byte drift\n"
        )
    elif mutation == "executable-mode":
        tracked.chmod((tracked.stat().st_mode & 0o777) | 0o111)
    elif mutation == "writable-mode":
        tracked.chmod((tracked.stat().st_mode & 0o777) | 0o022)
    else:
        external = tmp_path / "external-source.py"
        external.write_text(
            'raise RuntimeError("external source")\n',
            encoding="utf-8",
        )
        tracked.unlink()
        tracked.symlink_to(external)

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="reviewed G240 tracked source",
    ):
        _g240_landlock_source_files(
            worktree,
            git_executable_path=contract.git_executable_path,
            git_executable_cid=contract.git_executable_cid,
        )


def test_physical_symai_cache_persists_canonical_entries(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "physical-symai-cache"
    cache_root.mkdir(mode=0o700)
    first = _G240DiskCache(cache_root)
    value = {
        "raw_output": '{"class":"proved"}',
        "metadata": {
            "effective_provider_name": "ipfs_accelerate_py",
            "effective_model_name": "leanstral",
        },
    }

    first["fixture-cache-key"] = value
    second = _G240DiskCache(cache_root)

    assert second["fixture-cache-key"] == value
    assert tuple(second) == ("fixture-cache-key",)
    assert len(second) == 1
    entries = tuple(cache_root.glob("entry-*.json"))
    assert len(entries) == 1
    assert entries[0].stat().st_mode & 0o077 == 0
    with pytest.raises(
        G240SourceExecutorError,
        match="cannot be overwritten",
    ):
        second["fixture-cache-key"] = {"raw_output": "changed"}


def test_symai_preflight_configuration_is_state_scoped_and_cid_bound(
    tmp_path: Path,
) -> None:
    config_root = (tmp_path / "job-state" / "symai-runtime").resolve()

    projected_cid = prepare_symai_runtime_configuration(
        config_root,
        model="Leanstral-119B",
        import_package=False,
    )
    config_path = config_root / ".symai" / "symai.config.json"
    payload = config_path.read_bytes()

    assert projected_cid == cid_for_bytes(payload)
    assert config_path.stat().st_mode & 0o077 == 0
    assert json.loads(payload) == {
        "NEUROSYMBOLIC_ENGINE_API_KEY": "ipfs",
        "NEUROSYMBOLIC_ENGINE_MODEL": "ipfs:Leanstral-119B",
        "SYMBOLIC_ENGINE": "ipfs",
    }
    with pytest.raises(
        RuntimeBindingError,
        match="configuration drifted",
    ):
        prepare_symai_runtime_configuration(
            config_root,
            model="different-model",
            import_package=False,
        )


def test_executor_contract_preserves_a_virtualenv_launcher(
    tmp_path: Path,
) -> None:
    virtualenv = tmp_path / "pinned-runtime"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--without-pip",
            str(virtualenv),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    launcher = (virtualenv / "bin" / "python").absolute()

    contract = build_g240_source_executor_contract_v2(
        (
            "python",
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        ),
        entrypoint_kind="python-module",
        environment_cid=_authority("virtualenv-environment"),
        environment_sha256="a" * 64,
        executor_identity_cid=_authority("virtualenv-executor"),
        interpreter_path=launcher,
    )

    assert Path(contract.interpreter_path) == launcher
    assert Path(contract.interpreter_path).resolve() == Path(
        sys.executable
    ).resolve()


def _repository(
    tmp_path: Path,
    *,
    include_modal_codec_stub: bool = False,
    include_symai_stub: bool = False,
) -> tuple[Path, str]:
    checkout = tmp_path / "active-source"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch=main")
    _git(checkout, "config", "user.name", "G240 Source Tests")
    _git(
        checkout,
        "config",
        "user.email",
        "g240-source@example.invalid",
    )
    repository_root = Path(__file__).resolve().parents[4]
    shutil.copytree(
        repository_root / "benchmarks",
        checkout / "benchmarks",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    if include_modal_codec_stub:
        modal_root = checkout / "ipfs_datasets_py" / "logic" / "modal"
        modal_root.mkdir(parents=True)
        hammers_root = (
            checkout / "ipfs_datasets_py" / "logic" / "hammers"
        )
        hammers_root.mkdir(parents=True)
        optimizer_root = (
            checkout
            / "ipfs_datasets_py"
            / "optimizers"
            / "logic_theorem_optimizer"
        )
        optimizer_root.mkdir(parents=True)
        extraction_root = (
            checkout
            / "ipfs_datasets_py"
            / "knowledge_graphs"
            / "extraction"
        )
        extraction_root.mkdir(parents=True)
        for package in (
            checkout / "ipfs_datasets_py" / "__init__.py",
            checkout / "ipfs_datasets_py" / "logic" / "__init__.py",
            modal_root / "__init__.py",
            hammers_root / "__init__.py",
            checkout / "ipfs_datasets_py" / "optimizers" / "__init__.py",
            optimizer_root / "__init__.py",
            checkout
            / "ipfs_datasets_py"
            / "knowledge_graphs"
            / "__init__.py",
            extraction_root / "__init__.py",
            checkout / "spacy" / "__init__.py",
            checkout / "en_core_web_sm" / "__init__.py",
        ):
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_text("", encoding="utf-8")
        (checkout / "spacy" / "__init__.py").write_text(
            '__version__ = "fixture-1"\n',
            encoding="utf-8",
        )
        (checkout / "en_core_web_sm" / "__init__.py").write_text(
            '__version__ = "fixture-model-1"\n',
            encoding="utf-8",
        )
        (modal_root / "codec.py").write_text(
            """
class ModalLogicCodecConfig:
    pass


class _Encoded:
    parser_name = "tracked-test-modal-codec"

    def __init__(self, text, document_id, source):
        self.modal_ir = {
            "document_id": document_id,
            "normalized_text": text,
            "source": source,
            "version": "test-v1",
            "formulas": [
                {
                    "id": "formula-1",
                    "operator": {"family": "deontic"},
                    "predicate": {
                        "name": "applies",
                        "arguments": ["regulated-party"],
                        "role": "root",
                    },
                    "provenance": {"start": 0, "end": len(text)},
                }
            ],
        }


class DeterministicModalLogicCodec:
    def __init__(self, config):
        self.config = config

    def encode(self, text, *, document_id, source):
        return _Encoded(text, document_id, source)
""".lstrip(),
            encoding="utf-8",
        )
        shutil.copy2(
            repository_root
            / "ipfs_datasets_py"
            / "logic"
            / "hammers"
            / "process_lifecycle.py",
            hammers_root / "process_lifecycle.py",
        )
        (optimizer_root / "spacy_modal_codec.py").write_text(
            """
class _Doc(list):
    ents = ()


class _NLP:
    pipe_names = ["parser"]
    meta = {
        "name": "tracked-test-spacy",
        "version": "1",
        "lang": "en",
    }

    def __call__(self, text):
        return _Doc()


class _Encoding:
    used_fallback_model = False

    def __init__(self, text, document_id, source):
        self.text = text
        self.document_id = document_id
        self.source = source

    def to_dict(self):
        return {
            "normalized_text": self.text,
            "tokens": [],
            "sentences": [
                {
                    "text": self.text,
                    "start_char": 0,
                    "end_char": len(self.text),
                }
            ],
            "cues": [],
        }


class _ModalIR:
    def __init__(self, encoding):
        self.encoding = encoding

    def to_dict(self):
        return {
            "document_id": self.encoding.document_id,
            "normalized_text": self.encoding.text,
            "source": self.encoding.source,
            "version": "test-v1",
            "formulas": [
                {
                    "id": "formula-1",
                    "operator": {"family": "deontic"},
                    "predicate": {
                        "name": "applies",
                        "arguments": ["regulated-party"],
                        "role": "root",
                    },
                    "provenance": {
                        "start": 0,
                        "end": len(self.encoding.text),
                    },
                }
            ],
        }


class SpaCyLegalEncoder:
    used_fallback_model = False

    def __init__(self, model_name):
        self.model_name = model_name
        self.nlp = _NLP()

    def encode(self, text, *, document_id, citation, source):
        return _Encoding(text, document_id, source)


class SpaCyModalIRCompiler:
    def compile(self, encoding):
        return _ModalIR(encoding)
""".lstrip(),
            encoding="utf-8",
        )
        (extraction_root / "srl.py").write_text(
            """
class SRLExtractor:
    def __init__(self, nlp=None):
        self.nlp = nlp

    def extract_srl(self, text):
        return []
""".lstrip(),
            encoding="utf-8",
        )
        test_lean = checkout / "test-bin" / "lean"
        test_lean.parent.mkdir()
        test_lean.write_text(
            "#!/bin/sh\nexit 0\n",
            encoding="utf-8",
        )
        test_lean.chmod(0o755)
    if include_symai_stub:
        utility_root = checkout / "ipfs_datasets_py" / "utils"
        for package in (utility_root / "__init__.py",):
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_text(
                '__version__ = "tracked-fixture-1"\n',
                encoding="utf-8",
            )
        (utility_root / "symai_ipfs_engine.py").write_text(
            """
import json


class IPFSSyMAINeurosymbolicEngine:
    def __init__(
        self,
        _engine,
        _model_environment,
        *,
        provider,
        model_name,
        route_binding,
        **_options,
    ):
        self.provider = provider
        self.model_name = model_name
        self.route_binding = dict(route_binding)

    def forward(self, _argument):
        response = {
            "logic_family": "deontic",
            "target": "comply",
            "class": "proved",
            "predicates": ["regulated_party", "comply"],
            "entities": ["regulated_party", "ordinance"],
            "completeness": {
                "logic_family": True,
                "target": True,
                "class": True,
                "predicates": True,
                "entities": True,
            },
            "ambiguity_flags": [],
            "confidence_millionths": 950000,
            "validation_errors": [],
        }
        metadata = {
            "backend": "llm_router",
            "format": "json_schema",
            "router_provider": self.provider,
            "effective_provider_name": self.provider,
            "effective_model_name": self.model_name,
            **self.route_binding,
        }
        return (
            [json.dumps(response, sort_keys=True, separators=(",", ":"))],
            metadata,
        )
""".lstrip(),
            encoding="utf-8",
        )
        (
            checkout / "ipfs_datasets_py" / "llm_router.py"
        ).write_text(
            """
def get_last_generation_trace():
    return {}
""".lstrip(),
            encoding="utf-8",
        )
        accelerate_source = tmp_path / "ipfs-accelerate-source"
        accelerate_source.mkdir()
        _git(accelerate_source, "init", "--initial-branch=main")
        _git(
            accelerate_source,
            "config",
            "user.name",
            "G240 Source Tests",
        )
        _git(
            accelerate_source,
            "config",
            "user.email",
            "g240-source@example.invalid",
        )
        accelerate_package = (
            accelerate_source
            / "ipfs_accelerate_py"
            / "agent_supervisor"
        )
        accelerate_package.mkdir(parents=True)
        for package in (
            accelerate_source / "ipfs_accelerate_py" / "__init__.py",
            accelerate_package / "__init__.py",
        ):
            package.write_text("", encoding="utf-8")
        (
            accelerate_package / "leanstral_proof_provider.py"
        ).write_text(
            """
class LeanstralProofProviderConfig:
    def __init__(self, **values):
        self.values = dict(values)


class _FixtureProvider:
    def prove(self, _request):
        raise RuntimeError("tracked fixture provider was not selected")


def create_leanstral_proof_provider(_config=None, **_options):
    return _FixtureProvider()
""".lstrip(),
            encoding="utf-8",
        )
        _git(accelerate_source, "add", "--all")
        _git(
            accelerate_source,
            "commit",
            "--no-gpg-sign",
            "-m",
            "tracked fixture provider",
        )
        _git(
            checkout,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "--name",
            "ipfs_accelerate_py",
            accelerate_source.as_posix(),
            "ipfs_accelerate_py",
        )
    (checkout / "source.txt").write_text(
        "synthetic pinned source\n",
        encoding="utf-8",
    )
    _git(checkout, "add", "--all")
    _git(
        checkout,
        "commit",
        "--no-gpg-sign",
        "-m",
        "synthetic pinned source",
    )
    return checkout, _git(checkout, "rev-parse", "HEAD")


def _prepared(
    tmp_path: Path,
):
    plan, manifest, profile, evidence_by_job = _inputs(
        tmp_path / "synthetic-evidence"
    )
    runtime = evidence_by_job[plan.jobs[0].job_id]
    checkout, commit = _repository(tmp_path)
    paths = RunPaths.for_run(
        plan.run_id,
        benchmark_root=tmp_path / "run-state",
    )
    worktree = prepare_isolated_worktree(
        checkout,
        run_paths=paths,
        base_revision=commit,
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(
        worktree.worktree_root,
        worktree.worktree_commit,
    )
    environment_cid = cid_for_dag_json(
        {"schema": "synthetic-g240-environment.v1"}
    )
    executor_contract = build_g240_source_executor_contract_v2(
        (
            "python",
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        ),
        entrypoint_kind="python-module",
        environment_cid=environment_cid,
        environment_sha256=plan.environment_sha256,
        executor_identity_cid=_authority("executor"),
    )
    policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=g240_source_git_commit_cid(commit),
        recursive_gitlinks_cid=g240_recursive_gitlinks_cid(gitlinks),
        environment_cid=environment_cid,
        runtime_orchestration_policy_cid=str(
            executor_contract.contract_cid
        ),
        namespace_authority_cid=_authority("policy"),
    )
    job = plan.jobs[0]
    runtime = evidence_by_job[job.job_id]
    semantic_result = CaseResultRecord.from_stages(
        runtime.semantic_frontend
    )
    execution_request = G240ExecutionRequestV2.create(
        execution_mode="source",
        execution_run_id=plan.run_id,
        source_run_id=plan.run_id,
        source_commit=commit,
        policy_cid=str(policy.policy_cid),
        runtime_orchestration_policy_cid=str(
            executor_contract.contract_cid
        ),
        plan=plan,
        job=job,
        coordinate=policy.job_map[
            (policy.plan_cids[0], job.job_id)
        ],
        environment_cid=environment_cid,
        environment_sha256=str(plan.environment_sha256),
        semantic_result=semantic_result,
        compiler_exposure=runtime.compiler_exposure,
        source_text=runtime.source_text,
        proof_context=runtime.proof_context,
        adapter_factory_id=G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
        adapter_configuration=(
            build_g240_synthetic_adapter_configuration_v2()
        ),
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    return (
        plan,
        manifest,
        profile,
        job,
        runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    )


def _execute(tmp_path: Path):
    (
        plan,
        manifest,
        profile,
        job,
        runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    namespace_root = worktree.state_root / "source-namespaces"
    result = run_g240_source_job_v2(
        policy=policy,
        plan=plan,
        job=job,
        worktree_safety_receipt=worktree,
        namespace_root=namespace_root,
        executor_contract=executor_contract,
        execution_request=execution_request,
        namespace_observer_identity_cid=_authority(
            "namespace-observer"
        ),
        orchestration_observer_identity_cid=_authority(
            "orchestration-observer"
        ),
        timeout_seconds=10,
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    namespace_set = G240RuntimeNamespaceEvidenceSetV2(
        policy=policy,
        plan_cids=(result.runtime_namespace_receipt.plan_cid,),
        receipts=(result.runtime_namespace_receipt,),
        validator_identity_cid=_authority("namespace-validator"),
        complete=True,
        holdout_included=False,
    )
    return result, namespace_set, manifest, profile


def test_bootstrap_rejects_submodule_filter_before_status_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, commit = _repository(
        tmp_path,
        include_modal_codec_stub=True,
        include_symai_stub=True,
    )
    worktree = prepare_isolated_worktree(
        checkout,
        run_paths=RunPaths.for_run(
            "bootstrap-child-filter",
            benchmark_root=tmp_path / "bootstrap-filter-state",
        ),
        base_revision=commit,
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(checkout, commit)
    _materialize_recursive_local_gitlinks(
        checkout,
        worktree.worktree_root,
        tuple(item for item in gitlinks if item.depth == 1),
    )
    submodule = worktree.worktree_root / "ipfs_accelerate_py"
    git_dir = Path(
        _git(
            submodule,
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
        )
    )
    attributes = git_dir / "info" / "attributes"
    attributes.parent.mkdir(parents=True, exist_ok=True)
    attributes.write_text(
        "ipfs_accelerate_py/*.py filter=bootstrap-audit\n",
        encoding="utf-8",
    )
    marker = tmp_path / "bootstrap-child-filter-marker"
    driver = tmp_path / "bootstrap-child-clean-filter"
    driver.write_text(
        "#!/bin/sh\n"
        f"printf executed > {marker.as_posix()}\n"
        "cat\n",
        encoding="utf-8",
    )
    driver.chmod(0o755)
    _git(
        submodule,
        "config",
        "filter.bootstrap-audit.clean",
        driver.as_posix(),
    )
    _git(
        submodule,
        "config",
        "filter.bootstrap-audit.required",
        "true",
    )
    monkeypatch.setenv("HSSL_G240_EXPECTED_SOURCE_COMMIT", commit)
    executable = Path(
        shutil.which("git", path=os.defpath) or ""
    ).resolve(strict=True)

    with pytest.raises(
        G240SourceBootstrapError,
        match="bootstrap Git filters",
    ):
        _observe_source(
            worktree.worktree_root,
            executable,
        )

    assert not marker.exists()


def test_live_source_runner_emits_source_recomputed_complete_set(
    tmp_path: Path,
) -> None:
    result, namespace_set, _manifest, _profile = _execute(tmp_path)

    policy, namespace_receipt, orchestration = (
        validate_g240_private_source_sources_v2(
            result.validation_sources
        )
    )
    assert policy.policy_cid == orchestration.policy_cid
    assert (
        namespace_receipt.receipt_cid
        == orchestration.runtime_namespace_receipt_cid
    )
    assert orchestration.process_group_reaped is True
    assert orchestration.active_process_count_after_reap == 0
    assert orchestration.worktree_clean_after is True
    assert (
        orchestration.runtime_orchestration_policy_cid
        == result.validation_sources.executor_contract.contract_cid
    )
    assert (
        orchestration.command_cid
        == result.validation_sources.executor_contract.command_template_cid
    )
    assert (
        orchestration.interpreter_identity_cid
        == result.validation_sources.executor_contract.interpreter_identity_cid
    )
    assert (
        Path(result.process_result.arguments[0])
        == Path(
            result.validation_sources.executor_contract.interpreter_path
        )
    )
    assert (
        orchestration.execution_request_cid
        == result.validation_sources.execution_request.request_cid
    )
    assert (
        orchestration.confinement_profile_cid
        == G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
    )
    assert orchestration.synthetic_test_only is True
    assert orchestration.landlock_policy_cid is None
    assert orchestration.landlock_receipt_cid is None
    assert orchestration.landlock_receipt_payload_cid is None
    preflight = json.loads(
        result.validation_sources.runtime_preflight_payload
    )
    assert (
        preflight["bootstrap_confinement_receipt"][
            "receipt_channel_one_shot"
        ]
        is False
    )
    assert not hasattr(orchestration, "namespace_root")
    assert {
        "execution_request",
        "execution_request_path",
        "source_text",
        "proof_context",
        "adapter_configuration",
    }.isdisjoint(orchestration.to_dict())

    evidence_set = build_g240_source_orchestration_evidence_set_v2(
        namespace_set,
        (result.validation_sources,),
        validator_identity_cid=_authority(
            "orchestration-validator"
        ),
    )
    replayed = validate_g240_source_orchestration_evidence_set_v2(
        evidence_set.to_dict(),
        runtime_namespace_evidence_set=namespace_set,
        validation_sources=(result.validation_sources,),
    )
    assert replayed.complete is True
    assert replayed.holdout_included is False
    assert replayed.receipts == (orchestration,)
    serialized = json.dumps(replayed.to_dict(), sort_keys=True)
    assert str(tmp_path) not in serialized
    assert str(Path(sys.executable).resolve(strict=True)) not in serialized
    assert "stdout" not in serialized
    assert "stderr" not in serialized


def test_synthetic_source_is_test_schema_and_requires_private_capability(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    assert (
        execution_request.schema
        == G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
    )
    with pytest.raises(
        G240SourceExecutorError,
        match="production validation rejects test-only",
    ):
        validate_g240_production_execution_request_v2(
            execution_request
        )
    with pytest.raises(
        G240SourceExecutorError,
        match="synthetic request creation requires the private test-only",
    ):
        G240ExecutionRequestV2.create(
            execution_mode="source",
            execution_run_id=plan.run_id,
            source_run_id=plan.run_id,
            source_commit=execution_request.source_commit,
            policy_cid=str(policy.policy_cid),
            runtime_orchestration_policy_cid=str(
                executor_contract.contract_cid
            ),
            plan=plan,
            job=job,
            coordinate=policy.job_map[
                (policy.plan_cids[0], job.job_id)
            ],
            environment_cid=policy.environment_cid,
            environment_sha256=str(plan.environment_sha256),
            semantic_result=execution_request.typed_semantic_result,
            compiler_exposure=(
                execution_request.typed_compiler_exposure
            ),
            source_text=execution_request.source_text,
            proof_context=execution_request.proof_context,
            adapter_factory_id=(
                G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
            ),
            adapter_configuration=(
                build_g240_synthetic_adapter_configuration_v2()
            ),
        )
    namespace_root = worktree.state_root / "synthetic-without-capability"
    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="private test-only capability",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=namespace_root,
            executor_contract=executor_contract,
            execution_request=execution_request,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
        )
    assert not namespace_root.exists()


def test_production_non_a0_warm_request_has_no_precomputed_frontend(
    tmp_path: Path,
) -> None:
    inventory = _live_inventory()
    source_text = "A warm non-A0 production source request."
    plan = build_semantic_ablation_plan(
        inventory.run_id,
        (
            AblationCase.create(
                "production-warm-case",
                {"text": source_text},
                split=Split.PILOT,
            ),
        ),
        case_manifest_sha256="d" * 64,
        split=Split.PILOT,
        seed=17,
        variant_ids=("A0", "A1"),
        cache_modes=(CacheMode.WARM,),
        environment_sha256=inventory.sha256,
    )
    environment_cid = _authority("production-environment")
    contract = build_g240_source_executor_contract_v2(
        (
            "python",
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        ),
        entrypoint_kind="python-module",
        environment_cid=environment_cid,
        environment_sha256=inventory.sha256,
        executor_identity_cid=_authority("production-executor"),
        runtime_environment_artifacts=(
            _runtime_environment_artifacts(tmp_path)
        ),
    )
    policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=_authority("production-source-commit"),
        recursive_gitlinks_cid=_authority("production-gitlinks"),
        environment_cid=environment_cid,
        runtime_orchestration_policy_cid=str(contract.contract_cid),
        namespace_authority_cid=_authority("production-policy"),
    )
    job = next(
        item
        for item in plan.jobs
        if item.variant_id == "A1"
        and item.cache_mode is CacheMode.WARM
    )
    request = G240ExecutionRequestV2.create(
        execution_mode="source",
        execution_run_id=plan.run_id,
        source_run_id=plan.run_id,
        source_commit="a" * 40,
        policy_cid=str(policy.policy_cid),
        runtime_orchestration_policy_cid=(
            policy.runtime_orchestration_policy_cid
        ),
        plan=plan,
        job=job,
        coordinate=policy.job_map[
            (policy.plan_cids[0], job.job_id)
        ],
        environment_cid=environment_cid,
        environment_sha256=inventory.sha256,
        interpreter_identity_cid=contract.interpreter_identity_cid,
        git_executable_cid=contract.git_executable_cid,
        runtime_environment_artifacts=(
            contract.runtime_environment_artifacts
        ),
        source_text=source_text,
        proof_context={
            "obligation_id": "production-child-obligation",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        },
        adapter_factory_id=G240_LIVE_ADAPTER_FACTORY_ID_V2,
        adapter_configuration=(
            build_g240_live_adapter_configuration_v2(inventory)
        ),
    )

    assert request.schema == G240_EXECUTION_REQUEST_SCHEMA_V2
    assert request.semantic_result is None
    assert request.compiler_exposure is None
    assert (
        validate_g240_production_execution_request_v2(request)
        == request
    )
    with pytest.raises(
        G240SourceExecutorError,
        match="no precomputed semantic result",
    ):
        _ = request.typed_semantic_result


def test_live_factory_uses_and_enforces_the_measured_leanstral_token_cap(
) -> None:
    inventory = _live_inventory()
    configuration = build_g240_live_adapter_configuration_v2(inventory)

    assert (
        configuration["leanstral_max_new_tokens"]
        == LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    )
    with pytest.raises(
        G240SourceExecutorError,
        match="leanstral_max_new_tokens must be from 1 to",
    ):
        build_g240_live_adapter_configuration_v2(
            inventory,
            leanstral_max_new_tokens=(
                LEANSTRAL_MEASURED_MAX_NEW_TOKENS + 1
            ),
        )


def test_production_source_factory_rejects_precomputed_frontend(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        _worktree,
        policy,
        executor_contract,
        _execution_request,
    ) = _prepared(tmp_path)
    with pytest.raises(
        G240SourceExecutorError,
        match="must not precompute frontend outcomes",
    ):
        G240ExecutionRequestV2.create(
            execution_mode="source",
            execution_run_id=plan.run_id,
            source_run_id=plan.run_id,
            source_commit="a" * 40,
            policy_cid=str(policy.policy_cid),
            runtime_orchestration_policy_cid=str(
                executor_contract.contract_cid
            ),
            plan=plan,
            job=job,
            coordinate=policy.job_map[
                (policy.plan_cids[0], job.job_id)
            ],
            environment_cid=policy.environment_cid,
            environment_sha256=str(plan.environment_sha256),
            semantic_result=CaseResultRecord.from_stages(
                runtime.semantic_frontend
            ),
            compiler_exposure=runtime.compiler_exposure,
            source_text=runtime.source_text,
            proof_context=runtime.proof_context,
            adapter_factory_id=G240_LIVE_ADAPTER_FACTORY_ID_V2,
            adapter_configuration=(
                build_g240_live_adapter_configuration_v2(
                    _live_inventory()
                )
            ),
        )


@pytest.mark.parametrize(
    ("candidate_variant", "symai_available"),
    (("A1", False), ("A5", True)),
)
def test_full_plan_production_child_executes_non_a0_warm_frontend_and_a0(
    tmp_path: Path,
    candidate_variant: str,
    symai_available: bool,
) -> None:
    source_text = "A regulated party must comply with the ordinance."
    symai_interpreter: Path | None = None
    symai_initializer: Path | None = None
    symai_lock: Path | None = None
    if symai_available:
        (
            symai_interpreter,
            symai_initializer,
            symai_lock,
        ) = _pinned_symai_fixture_runtime(tmp_path)
    checkout, commit = _repository(
        tmp_path,
        include_modal_codec_stub=True,
        include_symai_stub=symai_available,
    )
    assert not (checkout / "symai").exists()
    available = {
        CapabilityKind.LEAN_TOOLCHAIN,
        CapabilityKind.SPACY_PIPELINE,
    }
    if symai_available:
        available.update(
            {
                CapabilityKind.SYMAI,
                CapabilityKind.LLM_ROUTER,
                CapabilityKind.LEANSTRAL_SERVICE,
            }
        )
    base_inventory = _live_inventory(
        unavailable=frozenset(
            kind
            for kind in CapabilityKind
            if kind not in available
        )
    )
    plan_run_id = base_inventory.run_id
    paths = RunPaths.for_run(
        plan_run_id,
        benchmark_root=tmp_path / "production-run-state",
    )
    worktree = prepare_isolated_worktree(
        checkout,
        run_paths=paths,
        base_revision=commit,
    )
    if symai_available:
        source_gitlinks = _capture_benchmark_bounded_gitlinks(
            checkout,
            commit,
        )
        _materialize_recursive_local_gitlinks(
            checkout,
            worktree.worktree_root,
            tuple(
                item for item in source_gitlinks if item.depth == 1
            ),
        )
    assert not (worktree.worktree_root / "symai").exists()
    test_lean = worktree.worktree_root / "test-bin" / "lean"
    inventory = replace(
        base_inventory,
        capabilities=tuple(
            replace(
                record,
                identity={
                    "implementation": "tracked-test-lean",
                    "lean": {
                        "path": test_lean.as_posix(),
                        "version": "tracked-test",
                    },
                    "lake": {
                        "path": test_lean.as_posix(),
                        "version": "tracked-test",
                    },
                },
            )
            if record.kind is CapabilityKind.LEAN_TOOLCHAIN
            else record
            for record in base_inventory.capabilities
        ),
    )
    plan = build_semantic_ablation_plan(
        inventory.run_id,
        (
            AblationCase.create(
                "production-child-case",
                {"text": source_text},
                split=Split.PILOT,
            ),
        ),
        case_manifest_sha256="e" * 64,
        split=Split.PILOT,
        seed=29,
        variant_ids=tuple(f"A{index}" for index in range(13)),
        cache_modes=(CacheMode.WARM,),
        environment_sha256=inventory.sha256,
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(
        worktree.worktree_root,
        worktree.worktree_commit,
    )
    environment_cid = _authority("production-child-environment")
    runtime_artifacts = _runtime_environment_artifacts(tmp_path)
    if symai_available:
        assert symai_initializer is not None
        assert symai_lock is not None
        runtime_artifacts.update(
            {
                "python-module.symai": symai_initializer,
                "symai_runtime_lock": symai_lock,
            }
        )
    executor_contract = build_g240_source_executor_contract_v2(
        (
            "python",
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        ),
        entrypoint_kind="python-module",
        environment_cid=environment_cid,
        environment_sha256=inventory.sha256,
        executor_identity_cid=_authority(
            "production-child-executor"
        ),
        interpreter_path=symai_interpreter,
        runtime_environment_artifacts=runtime_artifacts,
    )
    if symai_available:
        assert symai_interpreter is not None
        assert Path(executor_contract.interpreter_path) == symai_interpreter
    policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=g240_source_git_commit_cid(commit),
        recursive_gitlinks_cid=g240_recursive_gitlinks_cid(gitlinks),
        environment_cid=environment_cid,
        runtime_orchestration_policy_cid=str(
            executor_contract.contract_cid
        ),
        namespace_authority_cid=_authority(
            "production-child-policy"
        ),
    )
    job = next(
        item
        for item in plan.jobs
        if item.variant_id == candidate_variant
        and item.cache_mode is CacheMode.WARM
    )
    request = G240ExecutionRequestV2.create(
        execution_mode="source",
        execution_run_id=plan.run_id,
        source_run_id=plan.run_id,
        source_commit=commit,
        policy_cid=str(policy.policy_cid),
        runtime_orchestration_policy_cid=str(
            executor_contract.contract_cid
        ),
        plan=plan,
        job=job,
        coordinate=policy.job_map[
            (policy.plan_cids[0], job.job_id)
        ],
        environment_cid=environment_cid,
        environment_sha256=inventory.sha256,
        interpreter_identity_cid=(
            executor_contract.interpreter_identity_cid
        ),
        git_executable_cid=executor_contract.git_executable_cid,
        runtime_environment_artifacts=(
            executor_contract.runtime_environment_artifacts
        ),
        source_text=source_text,
        proof_context={
            "obligation_id": "production-child-obligation",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        },
        adapter_factory_id=G240_LIVE_ADAPTER_FACTORY_ID_V2,
        adapter_configuration=(
            build_g240_live_adapter_configuration_v2(inventory)
        ),
    )

    result = run_g240_source_job_v2(
        policy=policy,
        plan=plan,
        job=job,
        worktree_safety_receipt=worktree,
        namespace_root=worktree.state_root / "production-source",
        executor_contract=executor_contract,
        execution_request=request,
        namespace_observer_identity_cid=_authority(
            "production-child-namespace-observer"
        ),
        orchestration_observer_identity_cid=_authority(
            "production-child-orchestration-observer"
        ),
        timeout_seconds=20,
    )

    runtime = result.runtime_evidence
    assert result.process_result.returncode == 0
    assert request.semantic_result is None
    assert request.compiler_exposure is None
    assert runtime.case_result.variant_id == candidate_variant
    assert runtime.case_result.cache_mode is CacheMode.WARM
    assert {
        stage.variant_id for stage in runtime.semantic_frontend
    } == {candidate_variant}
    if symai_available:
        symai = next(
            stage
            for stage in runtime.semantic_frontend
            if stage.stage is StageName.SYMAI
        )
        assert symai.status is StageStatus.SUCCESS
        assert symai.data["backend_provenance"]["router_metadata"][
            "routing_backend"
        ] == "existing_leanstral_service"
    exposure = runtime.compiler_exposure.compiler_record
    assert exposure.variant_id == "A0"
    assert exposure.case_id == job.case_id
    assert exposure.split is plan.split
    assert exposure.cache_mode is job.cache_mode
    assert exposure.run_id == plan.run_id
    assert (
        result.orchestration_receipt.confinement_profile_cid
        == G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
    )
    assert result.orchestration_receipt.synthetic_test_only is False
    assert result.orchestration_receipt.landlock_policy_cid is not None
    assert result.orchestration_receipt.landlock_receipt_cid is not None
    assert (
        result.orchestration_receipt.landlock_receipt_payload_cid
        is not None
    )
    assert (
        result.validation_sources.landlock_transport_observation
        is not None
    )
    if symai_available:
        assert symai_initializer is not None
        preflight = json.loads(
            result.validation_sources.runtime_preflight_payload
        )
        symai_cid = cid_for_bytes(symai_initializer.read_bytes())
        assert preflight["imports"]["symai"] == {
            "module_file_cid": symai_cid,
            "version": "1.14.0",
        }
        assert preflight["runtime_environment_artifact_cids"][
            "python-module.symai"
        ] == symai_cid
        landlock_transport = (
            result.validation_sources.landlock_transport_observation
        )
        assert landlock_transport is not None
        for mutation in ("missing", "mismatched"):
            changed_preflight = json.loads(json.dumps(preflight))
            if mutation == "missing":
                del changed_preflight["imports"]["symai"]
            else:
                changed_preflight["imports"]["symai"][
                    "module_file_cid"
                ] = cid_for_bytes(b"mismatched SyMAI module")
            with pytest.raises(
                SourceRuntimeOrchestrationError,
                match="Python-module artifact/import join changed",
            ):
                _validate_runtime_preflight(
                    changed_preflight,
                    request=request,
                    contract=executor_contract,
                    landlock_sources=landlock_transport.policy_sources,
                    landlock_receipt=landlock_transport.receipt,
                    expected_gitlink_commit=(
                        worktree.submodule_commits.get(
                            "ipfs_accelerate_py"
                        )
                    ),
                )
        assert (
            symai_initializer.is_relative_to(checkout) is False
            and symai_initializer.is_relative_to(
                worktree.worktree_root
            )
            is False
        )

    replay_run_id = f"live-runtime-replay-{candidate_variant.lower()}"
    replay_launch = g240_replay_namespace_request_v2(
        source_policy=policy,
        source_receipt=result.runtime_namespace_receipt,
        replay_run_id=replay_run_id,
    )
    replay_execution_request = G240ExecutionRequestV2.create_replay(
        request,
        replay_run_id=replay_run_id,
        replay_process_namespace_cid=str(
            replay_launch["replay_process_namespace_cid"]
        ),
        replay_state_namespace_cid=str(
            replay_launch["replay_state_namespace_cid"]
        ),
        replay_output_namespace_cid=str(
            replay_launch["replay_output_namespace_cid"]
        ),
        replay_cache_namespace_cids=(
            replay_launch["replay_cache_namespace_cids"]
        ),
        source_runtime_evidence=runtime,
    )
    (
        replay_runtime,
        replay_namespace,
        replay_orchestration,
        replay_request,
        replay_receipt,
        replay_worktree,
    ) = run_g240_detached_replay_v2(
        checkout,
        worktree,
        policy,
        result.runtime_namespace_receipt,
        runtime,
        source_execution_request=request,
        replay_execution_request=replay_execution_request,
        replay_run_id=replay_run_id,
        executor_contract=executor_contract,
        benchmark_root=tmp_path / "production-replay-state",
        replay_executor_identity_cid=_authority(
            "production-replay-executor"
        ),
        replay_namespace_observer_identity_cid=_authority(
            "production-replay-namespace-observer"
        ),
        orchestration_observer_identity_cid=_authority(
            "production-replay-orchestration-observer"
        ),
        timeout_seconds=20,
    )
    replay_private = G240PrivateReplayValidationSourcesV2(
        source_policy=policy,
        executor_contract=executor_contract,
        source_namespace_receipt=result.runtime_namespace_receipt,
        namespace_receipt=replay_namespace,
        orchestration_receipt=replay_orchestration,
        source_worktree_safety_receipt=worktree,
        replay_request=replay_request,
        replay_receipt=replay_receipt,
        replay_worktree_safety_receipt=replay_worktree,
        evidence_payload=(
            canonical_dag_json_bytes(replay_runtime.to_dict()) + b"\n"
        ),
    )
    validate_g240_private_replay_sources_v2(
        replay_private,
        source_runtime_evidence=runtime,
        replay_runtime_evidence=replay_runtime,
    )
    assert replay_runtime.case_result.run_id == replay_run_id
    assert replay_worktree.worktree_root != worktree.worktree_root
    assert replay_worktree.state_root != worktree.state_root
    assert (
        replay_namespace.replay_process_namespace_cid
        != result.runtime_namespace_receipt.process_namespace_cid
    )
    assert (
        replay_namespace.replay_state_namespace_cid
        != result.runtime_namespace_receipt.state_namespace_cid
    )
    assert (
        replay_namespace.replay_output_namespace_cid
        != result.runtime_namespace_receipt.output_namespace_cid
    )
    assert replay_orchestration.runtime_preflight_cid is not None
    assert replay_orchestration.synthetic_test_only is False
    assert replay_orchestration.landlock_policy_cid is not None
    assert replay_orchestration.landlock_receipt_cid is not None
    assert replay_orchestration.landlock_receipt_payload_cid is not None
    assert replay_private.landlock_transport_observation is not None


def _g240_projection_record(
    record,
    *,
    plan_digest: str,
    job_id: str,
):
    return replace(
        record,
        provenance=replace(
            record.provenance,
            source=(
                "benchmarks.logic_pipeline.adapters",
                "ablation_plan",
                plan_digest,
                job_id,
            ),
        ),
    )


def _g240_success_payload(record, data: object):
    def plain(value: object) -> object:
        if isinstance(value, Mapping):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(item) for item in value]
        return value

    plain_data = plain(data)
    return replace(
        record,
        status=StageStatus.SUCCESS,
        data=plain_data,
        output_sha256=hashlib.sha256(
            canonical_dag_json_bytes(plain_data)
        ).hexdigest(),
        failure_code=None,
        failure_detail=None,
    )


def test_synthetic_frontend_records_remain_strictly_exact(
    tmp_path: Path,
) -> None:
    (
        _plan,
        _manifest,
        _profile,
        _job,
        runtime,
        _worktree,
        _policy,
        _executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    original = runtime.compiler_exposure.compiler_record
    drifted_record = replace(
        original,
        telemetry=replace(
            original.telemetry,
            wall_time_ms=original.telemetry.wall_time_ms + 1,
        ),
    )
    drifted_exposure = CompilerReferenceExposureV2.from_compiler_record(
        drifted_record,
        source_text=runtime.source_text,
    )
    drifted_result = CaseResultRecord.from_stages((drifted_record,))
    drifted_request = replace(
        execution_request,
        semantic_result=drifted_result.to_dict(),
        semantic_result_cid=_semantic_result_cid(drifted_result),
        compiler_exposure=drifted_exposure.to_dict(),
        compiler_exposure_cid=drifted_exposure.receipt_cid,
        request_cid=None,
    )

    with pytest.raises(
        G240SourceExecutorError,
        match="semantic_frontend",
    ):
        validate_g240_runtime_for_execution_request_v2(
            runtime,
            drifted_request,
        )


def test_production_replay_projection_allows_only_run_local_fields(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        _worktree,
        _policy,
        _executor_contract,
        _execution_request,
    ) = _prepared(tmp_path)
    record = _g240_projection_record(
        runtime.compiler_exposure.compiler_record,
        plan_digest=plan.digest,
        job_id=job.job_id,
    )
    expected = _g240_replay_stage_semantic_projection_v2(
        record,
        expected_plan_digest=plan.digest,
    )
    source = record.provenance.source
    allowed = (
        replace(record, run_id="projection-replay-run"),
        replace(
            record,
            telemetry=replace(
                record.telemetry,
                cpu_time_ms=record.telemetry.cpu_time_ms + 1,
            ),
        ),
        replace(
            record,
            provenance=replace(
                record.provenance,
                upstream_stage_digests=("f" * 64,),
            ),
        ),
        replace(
            record,
            provenance=replace(
                record.provenance,
                source=(
                    source[0],
                    source[1],
                    "e" * 64,
                    source[3],
                ),
            ),
        ),
    )
    for changed in allowed:
        accepted_plan_digest = (
            "e" * 64
            if changed.provenance.source[2] == "e" * 64
            else plan.digest
        )
        assert (
            _g240_replay_stage_semantic_projection_v2(
                changed,
                expected_plan_digest=accepted_plan_digest,
            )
            == expected
        )

    with pytest.raises(
        G240SourceExecutorError,
        match="unsupported provenance source route",
    ):
        _g240_replay_stage_semantic_projection_v2(
            allowed[-1],
            expected_plan_digest=plan.digest,
        )


def test_production_replay_projection_rejects_stable_stage_tampering(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        _worktree,
        _policy,
        _executor_contract,
        _execution_request,
    ) = _prepared(tmp_path)
    record = _g240_projection_record(
        runtime.compiler_exposure.compiler_record,
        plan_digest=plan.digest,
        job_id=job.job_id,
    )
    expected = _g240_replay_stage_semantic_projection_v2(
        record,
        expected_plan_digest=plan.digest,
    )
    source = record.provenance.source
    provenance = record.provenance
    changed_data = {
        **dict(record.data),
        "projection_tamper": True,
    }
    tampered = {
        "adapter_source": replace(
            record,
            provenance=replace(
                provenance,
                source=(
                    "tampered.adapter",
                    source[1],
                    source[2],
                    source[3],
                ),
            ),
        ),
        "source_marker": replace(
            record,
            provenance=replace(
                provenance,
                source=(
                    source[0],
                    "tampered_plan",
                    source[2],
                    source[3],
                ),
            ),
        ),
        "source_job": replace(
            record,
            provenance=replace(
                provenance,
                source=(
                    source[0],
                    source[1],
                    source[2],
                    "tampered-job",
                ),
            ),
        ),
        "adapter_id": replace(
            record,
            provenance=replace(
                provenance,
                adapter_id="tampered-adapter",
            ),
        ),
        "model_identity": replace(
            record,
            provenance=replace(
                provenance,
                effective_identity={
                    **dict(provenance.effective_identity),
                    "model": "tampered-model",
                },
            ),
        ),
        "environment": replace(
            record,
            provenance=replace(
                provenance,
                environment_sha256="c" * 64,
            ),
        ),
        "input": replace(
            record,
            provenance=replace(
                provenance,
                input_sha256="d" * 64,
            ),
        ),
        "data_and_output": _g240_success_payload(
            record,
            changed_data,
        ),
        "status": replace(
            record,
            status=StageStatus.FAILED,
            output_sha256=None,
            failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            failure_detail="projection tamper",
        ),
    }
    for category, changed in tampered.items():
        if category == "source_marker":
            with pytest.raises(
                G240SourceExecutorError,
                match="unsupported provenance source route",
            ):
                _g240_replay_stage_semantic_projection_v2(
                    changed,
                    expected_plan_digest=plan.digest,
                )
            continue
        assert (
            _g240_replay_stage_semantic_projection_v2(
                changed,
                expected_plan_digest=plan.digest,
            )
            != expected
        ), category


def test_compiler_projection_retains_protocol_source_artifact_and_candidate(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        _worktree,
        _policy,
        _executor_contract,
        _execution_request,
    ) = _prepared(tmp_path)
    record = _g240_projection_record(
        runtime.compiler_exposure.compiler_record,
        plan_digest=plan.digest,
        job_id=job.job_id,
    )
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        record,
        source_text=runtime.source_text,
    )
    expected = _g240_replay_compiler_semantic_projection_v2(
        exposure,
        expected_plan_digest=plan.digest,
    )
    assert {
        "semantic_protocol_cid",
        "causal_proof_protocol_cid",
        "source_cid",
        "compiler_artifact",
        "compiler_artifact_cid",
        "compiler_artifact_sha256",
        "compiler_candidate",
    }.issubset(expected)

    changed_record = _g240_success_payload(
        record,
        {**dict(record.data), "compiler_artifact_tamper": True},
    )
    changed_exposure = CompilerReferenceExposureV2.from_compiler_record(
        changed_record,
        source_text=runtime.source_text,
    )
    assert (
        _g240_replay_compiler_semantic_projection_v2(
            changed_exposure,
            expected_plan_digest=plan.digest,
        )
        != expected
    )

    def candidate_exposure(certificate: str):
        data = {
            **dict(record.data),
            "native_proof_candidate": {
                "certificate": certificate,
            },
        }
        candidate_record = _g240_success_payload(record, data)
        return CompilerReferenceExposureV2.from_compiler_record(
            candidate_record,
            source_text=runtime.source_text,
        )

    first_candidate = _g240_replay_compiler_semantic_projection_v2(
        candidate_exposure("by exact True.intro"),
        expected_plan_digest=plan.digest,
    )
    second_candidate = _g240_replay_compiler_semantic_projection_v2(
        candidate_exposure("by exact And.intro True.intro True.intro"),
        expected_plan_digest=plan.digest,
    )
    assert first_candidate != second_candidate
    for field in (
        "semantic_protocol_cid",
        "causal_proof_protocol_cid",
        "source_cid",
        "compiler_artifact_cid",
        "compiler_candidate",
    ):
        changed = dict(expected)
        changed[field] = {"tampered": field}
        assert changed != expected


def test_available_symai_projection_ignores_only_operational_cache_fields(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        _worktree,
        _policy,
        _executor_contract,
        _execution_request,
    ) = _prepared(tmp_path)
    base = _g240_projection_record(
        runtime.compiler_exposure.compiler_record,
        plan_digest=plan.digest,
        job_id=job.job_id,
    )
    stable_route = {
        "engine": "symai-neurosymbolic",
        "router": "ipfs_datasets_py.llm_router",
        "requested_provider": "ipfs_accelerate_py",
        "effective_provider": "ipfs_accelerate_py",
        "requested_model": "Leanstral-119B",
        "effective_model": "Leanstral-119B",
        "router_metadata": {
            "backend": "llm_router",
            "format": "json_schema",
            "router_provider": "ipfs_accelerate_py",
            "resolved_provider_name": "leanstral_local",
            "resolved_model_name": "leanstral-model",
            "service_endpoint": "http://127.0.0.1:8080/v1",
            "routing_backend": "existing_leanstral_service",
        },
        "attempts": 1,
        "retries": 0,
        "dry_run": False,
        "starts_model_server": False,
        "reuses_existing_model_service": True,
    }
    stable_identity = {
        "implementation": "symai",
        "requested_provider": "ipfs_accelerate_py",
        "effective_provider": "ipfs_accelerate_py",
        "requested_model": "Leanstral-119B",
        "effective_model": "Leanstral-119B",
        "validated_response_cid": _authority("symai-response"),
        "cache_namespace": "run-a/cache/warm",
        "cache_key": "a" * 64,
        "cache_hit": False,
        "graph_invoked": True,
    }
    semantic = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
        ),
        "candidate_ir": {
            "predicate": "applies",
            "cache": {"semantic_nested_value": "retained"},
        },
        "backend_provenance": stable_route,
        "cache": {
            "namespace": "run-a/cache/warm",
            "key": "a" * 64,
            "hit": False,
        },
        "raw_output": "run-local raw response",
    }
    source_stage = _g240_success_payload(
        replace(
            base,
            stage=StageName.SYMAI,
            adapter_version="2",
            provenance=replace(
                base.provenance,
                adapter_id="symai",
                adapter_version="2",
                effective_identity=stable_identity,
            ),
        ),
        semantic,
    )
    replay_semantic = {
        **semantic,
        "backend_provenance": {
            **stable_route,
            "attempts": 3,
            "retries": 2,
        },
        "cache": {
            "namespace": "run-b/cache/warm",
            "key": "b" * 64,
            "hit": True,
        },
        "raw_output": "different operational envelope",
    }
    replay_stage = _g240_success_payload(
        replace(
            source_stage,
            run_id="projection-symai-replay",
            telemetry=replace(
                source_stage.telemetry,
                model_calls=source_stage.telemetry.model_calls + 1,
            ),
            provenance=replace(
                source_stage.provenance,
                source=(
                    source_stage.provenance.source[0],
                    source_stage.provenance.source[1],
                    "b" * 64,
                    source_stage.provenance.source[3],
                ),
                effective_identity={
                    **stable_identity,
                    "cache_namespace": "run-b/cache/warm",
                    "cache_key": "b" * 64,
                    "cache_hit": True,
                    "retries": 2,
                },
            ),
        ),
        replay_semantic,
    )
    source_projection = _g240_replay_stage_semantic_projection_v2(
        source_stage,
        expected_plan_digest=plan.digest,
    )
    replay_projection = _g240_replay_stage_semantic_projection_v2(
        replay_stage,
        expected_plan_digest="b" * 64,
    )
    assert replay_projection == source_projection

    missing_route = _g240_success_payload(
        replay_stage,
        {
            key: value
            for key, value in replay_semantic.items()
            if key != "backend_provenance"
        },
    )
    with pytest.raises(
        G240SourceExecutorError,
        match="lacks stable backend provenance",
    ):
        _g240_replay_stage_semantic_projection_v2(
            missing_route,
            expected_plan_digest="b" * 64,
        )

    nested_semantic_tamper = _g240_success_payload(
        replay_stage,
        {
            **replay_semantic,
            "candidate_ir": {
                "predicate": "tampered",
                "cache": {"semantic_nested_value": "retained"},
            },
        },
    )
    assert (
        _g240_replay_stage_semantic_projection_v2(
            nested_semantic_tamper,
            expected_plan_digest="b" * 64,
        )
        != source_projection
    )

    for field, value in (
        ("effective_model", "tampered-model"),
        ("service_endpoint", "http://127.0.0.1:9999/v1"),
        ("routing_backend", "tampered-backend"),
        ("backend", "tampered-router"),
        ("format", "tampered-format"),
        ("router_provider", "tampered-router-provider"),
    ):
        route = dict(replay_semantic["backend_provenance"])
        if field in {
            "service_endpoint",
            "routing_backend",
            "backend",
            "format",
            "router_provider",
        }:
            metadata = dict(route["router_metadata"])
            metadata[field] = value
            route["router_metadata"] = metadata
            data = {**replay_semantic, "backend_provenance": route}
            changed = _g240_success_payload(replay_stage, data)
        else:
            identity = dict(replay_stage.provenance.effective_identity)
            identity[field] = value
            route[field] = value
            changed = _g240_success_payload(
                replace(
                    replay_stage,
                    provenance=replace(
                        replay_stage.provenance,
                        effective_identity=identity,
                    ),
                ),
                {**replay_semantic, "backend_provenance": route},
            )
        assert (
            _g240_replay_stage_semantic_projection_v2(
                changed,
                expected_plan_digest="b" * 64,
            )
            != source_projection
        ), field


@pytest.mark.parametrize("key", ["PATH", "PYTHONPATH", "PYTHONHOME"])
def test_runner_rejects_interpreter_environment_overrides_before_writes(
    tmp_path: Path,
    key: str,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    namespace_root = worktree.state_root / f"interpreter-env-{key.lower()}"
    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="reserved G240 environment",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=namespace_root,
            executor_contract=executor_contract,
            execution_request=execution_request,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
            environment={key: "/caller/override"},
            _test_only_synthetic_capability=(
                _G240_SYNTHETIC_TEST_CAPABILITY_V2
            ),
        )
    assert not namespace_root.exists()


def test_g211_persists_complete_source_orchestration_evidence(
    tmp_path: Path,
) -> None:
    result, namespace_set, manifest, profile = _execute(tmp_path)
    sources = result.validation_sources
    orchestration_set = (
        build_g240_source_orchestration_evidence_set_v2(
            namespace_set,
            (sources,),
            validator_identity_cid=_authority(
                "orchestration-validator"
            ),
        )
    )
    output_root = tmp_path / "g211-persisted"
    persisted = persist_causal_runtime_batch_v2(
        sources.plan,
        manifest,
        profile,
        {sources.job.job_id: result.runtime_evidence},
        output_root=output_root,
        runtime_namespace_evidence_set=namespace_set,
        source_orchestration_evidence_set=orchestration_set,
        source_orchestration_validation_sources=(sources,),
    )

    assert (
        persisted.source_orchestration_evidence_set
        == orchestration_set
    )
    assert (
        persisted.receipt["source_orchestration_evidence_set_cid"]
        == orchestration_set.evidence_set_cid
    )
    persisted_path = (
        output_root
        / "state"
        / "source-runtime-orchestration-evidence-set.json"
    )
    assert persisted_path.is_file()
    assert str(tmp_path) not in persisted_path.read_text(
        encoding="utf-8"
    )
    replayed = validate_causal_runtime_batch_v2(
        sources.plan,
        manifest,
        profile,
        output_root=output_root,
    )
    assert (
        replayed.source_orchestration_evidence_set
        == orchestration_set
    )


def test_g211_rejects_public_orchestration_without_private_sources(
    tmp_path: Path,
) -> None:
    result, namespace_set, manifest, profile = _execute(tmp_path)
    sources = result.validation_sources
    orchestration_set = (
        build_g240_source_orchestration_evidence_set_v2(
            namespace_set,
            (sources,),
            validator_identity_cid=_authority(
                "orchestration-validator"
            ),
        )
    )
    output_root = tmp_path / "unvalidated-public-record"

    with pytest.raises(
        CausalRuntimeBatchError,
        match="private validation sources",
    ):
        persist_causal_runtime_batch_v2(
            sources.plan,
            manifest,
            profile,
            {sources.job.job_id: result.runtime_evidence},
            output_root=output_root,
            runtime_namespace_evidence_set=namespace_set,
            source_orchestration_evidence_set=orchestration_set,
        )
    assert not output_root.exists()


def test_runner_rejects_reserved_environment_before_writes(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    namespace_root = worktree.state_root / "reserved-env"

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="reserved G240 environment",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=namespace_root,
            executor_contract=executor_contract,
            execution_request=execution_request,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
            environment={"HSSL_G240_JOB_ID": "forged"},
        )
    assert not namespace_root.exists()


def test_executor_contract_rejects_inline_or_postfreeze_command(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="path-free non-inline",
    ):
        build_g240_source_executor_contract_v2(
            ("python", "-c", "print('post-outcome')"),
            entrypoint_kind="python-module",
            environment_cid=executor_contract.environment_cid,
            environment_sha256=executor_contract.environment_sha256,
            executor_identity_cid=_authority("forged-executor"),
        )

    copied_after_freeze = build_g240_source_executor_contract_v2(
        ("forged-runner",),
        entrypoint_kind="installed-cli",
        environment_cid=executor_contract.environment_cid,
        environment_sha256=executor_contract.environment_sha256,
        executor_identity_cid=_authority("forged-executor"),
    )
    namespace_root = worktree.state_root / "postfreeze-command"
    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="differs from the frozen namespace",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=namespace_root,
            executor_contract=copied_after_freeze,
            execution_request=execution_request,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
        )
    assert not namespace_root.exists()


def test_runner_rejects_prefrozen_foreign_tracked_executor_before_writes(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    foreign_contract = build_g240_source_executor_contract_v2(
        (
            "python",
            "-m",
            "benchmarks.logic_pipeline.causal_runtime",
        ),
        entrypoint_kind="python-module",
        environment_cid=executor_contract.environment_cid,
        environment_sha256=executor_contract.environment_sha256,
        executor_identity_cid=executor_contract.executor_identity_cid,
    )
    foreign_policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=policy.source_commit_cid,
        recursive_gitlinks_cid=policy.recursive_gitlinks_cid,
        environment_cid=policy.environment_cid,
        runtime_orchestration_policy_cid=str(
            foreign_contract.contract_cid
        ),
        namespace_authority_cid=policy.namespace_authority_cid,
    )
    namespace_root = worktree.state_root / "foreign-prefrozen-executor"

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="tracked production G240 source executor",
    ):
        run_g240_source_job_v2(
            policy=foreign_policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=namespace_root,
            executor_contract=foreign_contract,
            execution_request=execution_request,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
        )
    assert not namespace_root.exists()


def test_runner_rejects_prefrozen_foreign_interpreter_before_writes(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    namespace_root = worktree.state_root / "foreign-interpreter"

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="pinned Python interpreter identity changed",
    ):
        replace(
            executor_contract,
            interpreter_identity_cid=_authority(
                "foreign-python-interpreter"
            ),
            contract_cid=None,
        )
    assert not namespace_root.exists()


def test_runner_rejects_unregistered_adapter_factory_before_writes(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    request_value = execution_request.to_dict()
    request_value["adapter_factory_id"] = "unregistered-factory"
    request_value["request_cid"] = cid_for_dag_json(
        {
            key: value
            for key, value in request_value.items()
            if key != "request_cid"
        }
    )
    namespace_root = worktree.state_root / "unregistered-adapter"

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="execution request failed typed replay",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=namespace_root,
            executor_contract=executor_contract,
            execution_request=request_value,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
        )
    assert not namespace_root.exists()


def test_runner_rejects_request_environment_different_from_plan(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        _runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    request_value = execution_request.to_dict()
    request_value["environment_sha256"] = "c" * 64
    request_value["request_cid"] = cid_for_dag_json(
        {
            key: value
            for key, value in request_value.items()
            if key != "request_cid"
        }
    )

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="execution request failed typed replay",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=worktree,
            namespace_root=worktree.state_root / "environment-mismatch",
            executor_contract=executor_contract,
            execution_request=request_value,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
        )


def test_runner_rejects_stale_gitlink_receipt_before_writes(
    tmp_path: Path,
) -> None:
    (
        plan,
        _manifest,
        _profile,
        job,
        runtime,
        worktree,
        policy,
        executor_contract,
        execution_request,
    ) = _prepared(tmp_path)
    stale = WorktreeSafetyReceipt(
        **{
            **worktree.to_dict(),
            "source_checkout": worktree.source_checkout,
            "source_git_common_dir": worktree.source_git_common_dir,
            "worktree_root": worktree.worktree_root,
            "state_root": worktree.state_root,
            "submodule_commits": {"vendor/forged": "a" * 40},
        }
    )
    namespace_root = worktree.state_root / "stale-gitlinks"
    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="source/Gitlink projection",
    ):
        run_g240_source_job_v2(
            policy=policy,
            plan=plan,
            job=job,
            worktree_safety_receipt=stale,
            namespace_root=namespace_root,
            executor_contract=executor_contract,
            execution_request=execution_request,
            namespace_observer_identity_cid=_authority(
                "namespace-observer"
            ),
            orchestration_observer_identity_cid=_authority(
                "orchestration-observer"
            ),
            timeout_seconds=10,
        )
    assert not namespace_root.exists()


def test_private_validator_rejects_noncanonical_request_bytes(
    tmp_path: Path,
) -> None:
    result, _namespace_set, _manifest, _profile = _execute(tmp_path)
    sources = result.validation_sources
    noncanonical = (
        json.dumps(
            sources.execution_request.to_dict(),
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="request bytes are not exact canonical JSON",
    ):
        validate_g240_private_source_sources_v2(
            replace(
                sources,
                execution_request_payload=noncanonical,
            )
        )


def test_private_source_bundle_rejects_fabricated_process_result(
    tmp_path: Path,
) -> None:
    result, _namespace_set, _manifest, _profile = _execute(tmp_path)
    fabricated = BoundedProcessResult(
        arguments=result.process_result.arguments,
        returncode=0,
        stdout="",
        stderr="",
        timed_out=False,
        process_group_reaped=True,
    )

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="live process authority",
    ):
        replace(
            result.validation_sources,
            process_result=fabricated,
        )


def test_private_validator_rejects_namespace_rebase(
    tmp_path: Path,
) -> None:
    result, _namespace_set, _manifest, _profile = _execute(tmp_path)
    receipt = result.runtime_namespace_receipt
    rebased = replace(
        receipt,
        process_namespace_cid=cid_for_dag_json(
            {"schema": "synthetic-forged-process-namespace.v1"}
        ),
        receipt_cid=None,
    )
    sources = replace(
        result.validation_sources,
        runtime_namespace_receipt=rebased,
    )

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="runtime namespace sources failed replay",
    ):
        validate_g240_private_source_sources_v2(sources)


def test_private_validator_rejects_worktree_dirtied_after_execution(
    tmp_path: Path,
) -> None:
    result, _namespace_set, _manifest, _profile = _execute(tmp_path)
    worktree = result.validation_sources.worktree_safety_receipt
    assert isinstance(worktree, WorktreeSafetyReceipt)
    (worktree.worktree_root / "untracked-after-run.txt").write_text(
        "stale live checkout\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SourceRuntimeOrchestrationError,
        match="not live, clean, and detached",
    ):
        validate_g240_private_source_sources_v2(
            result.validation_sources
        )

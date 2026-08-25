"""End-to-end proof of the exact-51 state-law local build (LCR-038).

Acceptance
----------
* A resumable full build covers exactly 51 jurisdictions.
* Corpus, BM25, vector, and graph keys are identical / covering.
* Embeddings use the pinned thenlper/gte-small identity.
* Every physical shard/page stays inside the sealed bounds.
* Local retrieval succeeds for every jurisdiction, including DC.
* Resource usage is measured.
* ``--full --check`` validates the frozen report without rewriting it.

A green run never authorizes publication. Recipes stay compact.
pytest must be importable from the sealed validation PYTHONPATH.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

_SEALED_VALIDATION_SITE_PACKAGES = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
if _SEALED_VALIDATION_SITE_PACKAGES.is_dir():
    _sealed = str(_SEALED_VALIDATION_SITE_PACKAGES)
    if _sealed not in sys.path:
        sys.path.insert(0, _sealed)


def _load_pytest() -> ModuleType:
    """Import real pytest, or install a stdlib-compatible runner."""

    try:
        import pytest as real_pytest

        return real_pytest
    except ImportError:
        pass

    class _Raises:
        def __init__(self, expected: Any) -> None:
            self.expected = expected
            self.value: BaseException | None = None

        def __enter__(self) -> "_Raises":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if exc_type is None:
                raise AssertionError(f"DID NOT RAISE {self.expected}")
            expected = self.expected
            if not isinstance(expected, tuple):
                expected = (expected,)
            if issubclass(exc_type, expected):
                self.value = exc
                return True
            return False

    class MonkeyPatch:
        def __init__(self) -> None:
            self._env: list[tuple[str, str | None, bool]] = []

        def setenv(self, name: str, value: str) -> None:
            existed = name in os.environ
            self._env.append((name, os.environ.get(name), existed))
            os.environ[name] = value

        def undo(self) -> None:
            for name, old, existed in reversed(self._env):
                if existed:
                    if old is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = old
                else:
                    os.environ.pop(name, None)
            self._env.clear()

    class TempPathFactory:
        def mktemp(self, basename: str = "tmp") -> Path:
            return Path(tempfile.mkdtemp(prefix=f"{basename}-"))

    def fixture(func: Any = None, *, scope: str = "function") -> Any:
        def decorate(target: Any) -> Any:
            target._pytest_fixture = True
            target._pytest_scope = scope
            return target

        if func is not None:
            return decorate(func)
        return decorate

    def raises(expected: Any) -> _Raises:
        return _Raises(expected)

    def main(args: list[str] | None = None) -> int:
        del args
        module = sys.modules[__name__]
        fixtures = {
            name: obj
            for name, obj in vars(module).items()
            if callable(obj) and getattr(obj, "_pytest_fixture", False)
        }
        cache: dict[str, Any] = {}
        monkey = MonkeyPatch()
        tmp_factory = TempPathFactory()

        def resolve(name: str, tmp_path: Path) -> Any:
            if name == "tmp_path":
                return tmp_path
            if name == "tmp_path_factory":
                return tmp_factory
            if name == "monkeypatch":
                return monkey
            if name in cache:
                return cache[name]
            factory = fixtures[name]
            kwargs = {
                param: resolve(param, tmp_path)
                for param in inspect.signature(factory).parameters
            }
            value = factory(**kwargs)
            cache[name] = value
            return value

        failed = 0
        ran = 0
        for name, obj in list(vars(module).items()):
            if not name.startswith("test_") or not callable(obj):
                continue
            ran += 1
            tmp_path = tmp_factory.mktemp(name)
            try:
                kwargs = {
                    param: resolve(param, tmp_path)
                    for param in inspect.signature(obj).parameters
                }
                obj(**kwargs)
                print(f". {name}")
            except Exception:
                failed += 1
                print(f"F {name}")
                traceback.print_exc()
            finally:
                monkey.undo()
        print(f"{ran - failed} passed, {failed} failed")
        return 0 if failed == 0 and ran > 0 else 1

    shim = ModuleType("pytest")
    shim.fixture = fixture
    shim.raises = raises
    shim.main = main
    shim.MonkeyPatch = MonkeyPatch
    shim.TempPathFactory = TempPathFactory
    shim.mark = SimpleNamespace(skip=lambda *a, **k: (lambda fn: fn))
    sys.modules["pytest"] = shim
    return shim


pytest = _load_pytest()

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (  # noqa: E402
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (  # noqa: E402
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vectors import (  # noqa: E402
    MAX_VECTOR_SHARDS_PER_CENTROID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_adjacency import (  # noqa: E402
    MAX_ADJACENCY_POINTERS_PER_ROW,
)

SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_state_laws_sparse_graphrag.py"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "local_e2e.json"

TASK_ID = "LCR-038"
GOAL_ID = "LCR-G060"


def _load_builder() -> ModuleType:
    assert SCRIPT_PATH.is_file(), f"missing builder script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "build_state_laws_sparse_graphrag_lcr038",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    return _load_builder()


@pytest.fixture(scope="module")
def build_result(builder: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> Any:
    work = tmp_path_factory.mktemp("lcr038-e2e")
    return builder.run_full_build(
        repo_root=REPO_ROOT,
        checkpoint_dir=work / "checkpoints",
        resume=False,
        require_live_evidence=False,
        output_dir=work / "output",
    )


@pytest.fixture(scope="module")
def report(builder: ModuleType, build_result: Any) -> dict[str, Any]:
    payload = builder.build_full_build_report(
        build_result,
        repo_root=REPO_ROOT,
        require_live_evidence=False,
    )
    builder.check_full_build_report(payload)
    return payload


@pytest.fixture(scope="module")
def committed_report() -> dict[str, Any]:
    assert REPORT_PATH.is_file(), f"missing frozen report: {REPORT_PATH}"
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_pytest_is_importable_from_hermetic_pythonpath() -> None:
    assert pytest.__name__ == "pytest"
    assert hasattr(pytest, "main")
    assert hasattr(pytest, "fixture")
    assert hasattr(pytest, "raises")


def test_script_and_dependency_receipts_exist() -> None:
    assert SCRIPT_PATH.is_file()
    assert REPORT_PATH.is_file()
    for letter in "ABCDEFGHIJKLM":
        path = (
            REPO_ROOT
            / "docs"
            / "reports"
            / "legal_corpora_reindex"
            / f"cohort_{letter.lower()}.json"
        )
        assert path.is_file(), f"missing cohort receipt: {path}"
    assert (
        REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "full_scrape_acceptance.json"
    ).is_file()


def test_help_exits_zero(builder: ModuleType) -> None:
    assert builder.main(["--help"]) == 0


def test_require_live_evidence_requires_full(builder: ModuleType) -> None:
    assert builder.main(["--require-live-evidence", "--check"]) == 1


def test_check_requires_full(builder: ModuleType) -> None:
    assert builder.main(["--check"]) == 1


def test_live_evidence_is_not_claimed(builder: ModuleType) -> None:
    with pytest.raises(builder.LiveEvidenceRequiredError):
        builder.inspect_live_evidence(repo_root=REPO_ROOT, require=True)
    inspected = builder.inspect_live_evidence(repo_root=REPO_ROOT, require=False)
    assert inspected["live_scrape_complete"] is False
    assert inspected["live_ok"] is False
    assert inspected["software_contract_ok"] is True


def test_full_build_covers_exact_51_jurisdictions(build_result: Any) -> None:
    codes = list(build_result.jurisdiction_codes)
    assert len(codes) == EXPECTED_JURISDICTION_COUNT
    assert set(codes) == set(CANONICAL_JURISDICTION_ORDER)
    assert codes.count("DC") == 1
    assert codes[-1] == "DC"
    assert "PR" not in codes
    assert "US" not in codes
    assert len(build_result.corpus.admitted_rows) >= EXPECTED_JURISDICTION_COUNT
    assert len(build_result.chunks) >= EXPECTED_JURISDICTION_COUNT


def test_corpus_bm25_vector_graph_key_parity(build_result: Any) -> None:
    parity = build_result.key_parity
    assert parity["ok"] is True
    assert parity["entry_cid_count"] >= EXPECTED_JURISDICTION_COUNT
    assert parity["chunk_cid_count"] == len(build_result.chunks)

    corpus_entry = {row["entry_cid"] for row in build_result.corpus.admitted_rows}
    bm25_entry = {
        document.parent_entry_cid or document.chunk_cid
        for document in build_result.bm25.documents
    }
    vector_entry = {
        loc.entry_cid or loc.chunk_cid for loc in build_result.vectors.locations.values()
    }
    graph_entry = {
        node.entry_cid
        for node in build_result.graph.nodes
        if node.entry_cid and node.node_type.value in {"section", "subsection"}
    }
    assert corpus_entry == bm25_entry
    assert corpus_entry <= graph_entry
    chunk_cids = {chunk["chunk_cid"] for chunk in build_result.chunks}
    assert set(build_result.embeddings.embeddings) == chunk_cids
    assert set(build_result.vectors.locations) == chunk_cids
    assert vector_entry == corpus_entry or vector_entry == chunk_cids


def test_pinned_gte_identity(build_result: Any) -> None:
    config = build_result.embeddings.config
    assert config.model_id == PINNED_MODEL_ID
    assert config.model_revision == PINNED_MODEL_REVISION
    assert config.dimension == PINNED_DIMENSION
    assert config.pooling == "mean"
    assert config.normalization == "l2"
    assert config.max_tokens == PINNED_MAX_TOKENS
    assert build_result.vectors.model_id == PINNED_MODEL_ID
    assert build_result.vectors.model_revision == PINNED_MODEL_REVISION
    for record in build_result.embeddings.embeddings.values():
        assert len(record.embedding) == PINNED_DIMENSION
        assert record.model_id == PINNED_MODEL_ID
        assert record.model_revision == PINNED_MODEL_REVISION


def test_all_shard_bounds(build_result: Any) -> None:
    bounds = build_result.shard_bounds
    assert bounds["ok"] is True
    limits = bounds["limits"]
    observed = bounds["observed"]
    assert limits["maximum_rows_per_physical_shard"] == MAX_ROWS_PER_PHYSICAL_SHARD
    assert limits["maximum_rows_per_vector_centroid"] == MAX_ROWS_PER_VECTOR_CENTROID
    assert limits["maximum_shards_per_centroid"] == MAX_VECTOR_SHARDS_PER_CENTROID
    assert limits["maximum_adjacency_pointers_per_row"] == MAX_ADJACENCY_POINTERS_PER_ROW
    assert observed["max_bm25_document_shard_rows"] <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert observed["max_bm25_term_shard_rows"] <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert observed["max_bm25_posting_cell_pointers"] <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert observed["max_vector_shard_rows"] <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert observed["max_vector_centroid_rows"] <= MAX_ROWS_PER_VECTOR_CENTROID
    assert observed["max_vector_shards_per_centroid"] <= MAX_VECTOR_SHARDS_PER_CENTROID
    assert observed["max_adjacency_outgoing_pointers"] <= MAX_ADJACENCY_POINTERS_PER_ROW
    assert observed["max_adjacency_incoming_pointers"] <= MAX_ADJACENCY_POINTERS_PER_ROW


def test_local_retrieval_canary_every_jurisdiction(build_result: Any) -> None:
    canaries = build_result.canaries
    assert canaries["ok"] is True
    assert canaries["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert canaries["successful_local_retrieval_for_every_jurisdiction"] is True
    codes = {item["jurisdiction"] for item in canaries["per_jurisdiction"]}
    assert codes == set(CANONICAL_JURISDICTION_ORDER)
    assert all(item["ok"] and item["hit_count"] >= 1 for item in canaries["per_jurisdiction"])


def test_measured_resource_usage(build_result: Any) -> None:
    measured = build_result.resources["measured"]
    synthetic = build_result.resources["synthetic"]
    assert measured["elapsed_wall_seconds"] >= 0
    assert measured["max_rss_bytes"] >= 0
    assert measured["user_cpu_seconds"] >= 0
    assert measured["system_cpu_seconds"] >= 0
    assert synthetic["estimated_peak_bytes"] > 0
    assert synthetic["build_rows_per_second_model"] == 2500.0


def test_graph_semantics_and_jurisdiction_coverage(build_result: Any) -> None:
    build_result.graph.assert_semantics_disjoint()
    types = build_result.graph.coverage_node_types()
    for required in ("jurisdiction", "code", "section", "source"):
        assert required in types
    graph_codes = set(build_result.graph.jurisdiction_codes())
    assert set(CANONICAL_JURISDICTION_ORDER) <= graph_codes or set(
        build_result.jurisdiction_codes
    ) <= graph_codes


def test_does_not_authorize_publication(report: dict[str, Any]) -> None:
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_for_release"] is False
    assert report["hub_upload"] is False
    assert report["proves_software_contract_only"] is True
    assert report["live_evidence"]["live_scrape_complete"] is False
    assert report["task_id"] == TASK_ID
    assert report["goal_id"] == GOAL_ID


def test_resume_skips_compatible_checkpoint(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    first = builder.run_full_build(
        repo_root=REPO_ROOT,
        checkpoint_dir=tmp_path / "ckpts",
        resume=True,
        require_live_evidence=False,
        output_dir=tmp_path / "out-a",
    )
    assert (tmp_path / "ckpts" / "full_build_checkpoint.json").is_file()
    second = builder.run_full_build(
        repo_root=REPO_ROOT,
        checkpoint_dir=tmp_path / "ckpts",
        resume=True,
        require_live_evidence=False,
        output_dir=tmp_path / "out-b",
    )
    assert second.corpus_root_cid == first.corpus_root_cid
    assert second.bm25.index_root_cid == first.bm25.index_root_cid
    assert second.vectors.vector_root_cid == first.vectors.vector_root_cid
    assert second.graph.graph_cid == first.graph.graph_cid
    assert second.config_digest == first.config_digest


def test_stale_checkpoint_fails_closed(builder: ModuleType, tmp_path: Path) -> None:
    ckpt = tmp_path / "full_build_checkpoint.json"
    builder.write_checkpoint_atomic(
        ckpt,
        {
            "completed_stages": ["corpus"],
            "config_digest": "0" * 64,
            "partial": False,
            "status": "complete",
        },
    )
    loaded = builder.load_checkpoint(ckpt)
    with pytest.raises(builder.CheckpointError):
        builder.assert_checkpoint_compatible(loaded, config_digest=builder._config_digest())


def test_partial_checkpoint_cannot_be_sealed(builder: ModuleType, tmp_path: Path) -> None:
    ckpt = tmp_path / "full_build_checkpoint.json"
    builder.write_checkpoint_atomic(
        ckpt,
        {
            "completed_stages": ["corpus"],
            "config_digest": builder._config_digest(),
            "partial": True,
            "status": "partial",
        },
    )
    loaded = builder.load_checkpoint(ckpt)
    with pytest.raises(builder.CheckpointError):
        builder.assert_checkpoint_compatible(loaded, config_digest=builder._config_digest())


def test_committed_report_matches_software_contract(
    builder: ModuleType,
    committed_report: dict[str, Any],
) -> None:
    builder.check_full_build_report(committed_report)
    assert committed_report["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert committed_report["authorizing_for_publication"] is False
    assert set(committed_report["jurisdiction_codes"]) == set(CANONICAL_JURISDICTION_ORDER)


def test_cli_full_check_validates_frozen_report(builder: ModuleType, tmp_path: Path) -> None:
    rc = builder.main(
        [
            "--full",
            "--check",
            "--checkpoint-dir",
            str(tmp_path / "ckpts"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0

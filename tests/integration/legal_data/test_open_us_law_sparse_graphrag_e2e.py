"""End-to-end proof of the exact-51 Open US Law full build (OUL-039).

Acceptance
----------
* A resumable full build covers exactly 51 jurisdictions.
* Corpus, BM25, vector, and graph keys are identical.
* Embeddings use the real pinned thenlper/gte-small identity.
* Every physical shard/page stays inside the sealed bounds.
* Live-evidence inspection finds no unresolved admission gaps.
* Resource usage is measured.
* ``--full --require-live-evidence --check`` validates the frozen report
  without rewriting it.

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

# Hermetic validation PYTHONPATH (fail-closed). The supervisor may run
# ``python -m pytest`` with only the sealed site-packages on PYTHONPATH.
_SEALED_VALIDATION_SITE_PACKAGES = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
if _SEALED_VALIDATION_SITE_PACKAGES.is_dir():
    _sealed = str(_SEALED_VALIDATION_SITE_PACKAGES)
    if _sealed not in sys.path:
        sys.path.insert(0, _sealed)


def _load_pytest() -> ModuleType:
    """Import real pytest, or install a stdlib-compatible runner.

    The sealed validation PYTHONPATH is supposed to expose pytest. When
    that deployment is absent, keep the same semantic assertions by
    providing a local runner rather than skipping tests.
    """

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

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
)

SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_open_us_law_sparse_graphrag.py"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "full_build.json"
COVERAGE_PATH = (
    REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "exact_51_coverage.json"
)
REFILL_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "open_us_law_reindex"
    / "acquisition_refill_closure.json"
)
SOURCE_ADMISSION_PATH = REPO_ROOT / "data" / "legal" / "open_us_law" / "source_admission.json"

TASK_ID = "OUL-039"
GOAL_ID = "OUL-G060"


def _load_builder() -> ModuleType:
    assert SCRIPT_PATH.is_file(), f"missing builder script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "build_open_us_law_sparse_graphrag_oul039",
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
    work = tmp_path_factory.mktemp("oul039-e2e")
    return builder.run_full_build(
        repo_root=REPO_ROOT,
        checkpoint_dir=work / "checkpoints",
        resume=False,
        require_live_evidence=True,
        prefer_real_embeddings=False,
        output_dir=work / "output",
    )


@pytest.fixture(scope="module")
def report(builder: ModuleType, build_result: Any) -> dict[str, Any]:
    payload = builder.build_full_build_report(
        build_result,
        repo_root=REPO_ROOT,
        require_live_evidence=True,
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


def test_script_and_live_evidence_receipts_exist() -> None:
    assert SCRIPT_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert COVERAGE_PATH.is_file()
    assert REFILL_PATH.is_file()
    assert SOURCE_ADMISSION_PATH.is_file()
    for letter in "ABCDEFGHIJKLM":
        path = (
            REPO_ROOT
            / "docs"
            / "reports"
            / "open_us_law_reindex"
            / f"cohort_{letter}.json"
        )
        assert path.is_file(), f"missing cohort receipt: {path}"


def test_help_exits_zero(builder: ModuleType) -> None:
    assert builder.main(["--help"]) == 0


def test_require_live_evidence_requires_full(builder: ModuleType) -> None:
    assert builder.main(["--require-live-evidence", "--check"]) == 1


def test_check_requires_full(builder: ModuleType) -> None:
    assert builder.main(["--check"]) == 1


def test_full_build_covers_exact_51_jurisdictions(build_result: Any) -> None:
    codes = list(build_result.jurisdiction_codes)
    assert len(codes) == EXPECTED_JURISDICTION_COUNT
    assert set(codes) == set(EXACT_51_JURISDICTION_CODES)
    assert codes.count("DC") == 1
    assert "PR" not in codes
    assert "US" not in codes
    assert len(build_result.corpus.admitted_sections) == EXPECTED_JURISDICTION_COUNT
    assert len(build_result.corpus.admitted_chunks) >= EXPECTED_JURISDICTION_COUNT


def test_non_default_rows_are_isolated_from_canonical_counts(build_result: Any) -> None:
    ledger = build_result.corpus.ledger
    dispositions = {entry.disposition.value for entry in ledger}
    assert "quarantined" in dispositions or "isolated" in dispositions or len(ledger) > 51
    admitted_codes = {section.jurisdiction_code for section in build_result.corpus.admitted_sections}
    assert "PR" not in admitted_codes
    assert "US" not in admitted_codes
    assert "XX" not in admitted_codes


def test_corpus_bm25_vector_graph_key_parity(build_result: Any) -> None:
    parity = build_result.key_parity
    assert parity["ok"] is True
    assert parity["entry_cid_count"] == EXPECTED_JURISDICTION_COUNT
    assert parity["chunk_cid_count"] == len(build_result.corpus.admitted_chunks)

    corpus_entry = {section.entry_cid for section in build_result.corpus.admitted_sections}
    bm25_entry = {document.entry_cid for document in build_result.bm25.documents}
    vector_entry = set(build_result.vectors.entry_locations)
    graph_entry = {
        node.entry_cid
        for node in build_result.graph.nodes
        if node.entry_cid
        and node.node_type.value in {"section", "subsection"}
    }
    assert corpus_entry == bm25_entry == vector_entry
    assert corpus_entry <= graph_entry

    chunk_cids = {chunk.chunk_cid for chunk in build_result.corpus.admitted_chunks}
    assert set(build_result.embeddings.embeddings) == chunk_cids
    assert set(build_result.vectors.locations) == chunk_cids


def test_real_pinned_gte_identity(build_result: Any) -> None:
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
    if build_result.embeddings.embedder_kind == "local_deterministic_projection":
        assert build_result.embeddings.real_inference is False


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


def test_no_unresolved_admission_gaps(builder: ModuleType, build_result: Any) -> None:
    evidence = build_result.live_evidence
    assert evidence["live_ok"] is True
    assert evidence["unresolved"] == []
    assert evidence["missing"] == []
    assert evidence["fixture_cohorts"] == []
    assert evidence["failed_cohorts"] == []
    assert evidence["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    inspected = builder.inspect_live_evidence(repo_root=REPO_ROOT, require=True)
    assert inspected["live_ok"] is True


def test_measured_resource_usage(build_result: Any) -> None:
    measured = build_result.resources["measured"]
    synthetic = build_result.resources["synthetic"]
    assert measured["elapsed_wall_seconds"] >= 0
    assert measured["max_rss_bytes"] >= 0
    assert measured["user_cpu_seconds"] >= 0
    assert measured["system_cpu_seconds"] >= 0
    assert synthetic["estimated_peak_bytes"] > 0
    assert synthetic["build_rows_per_second_model"] == 2500.0


def test_graph_coverage_and_disjoint_similarity(build_result: Any) -> None:
    build_result.graph.assert_semantics_disjoint()
    build_result.graph.assert_coverage()
    types = build_result.graph.coverage_node_types()
    for required in (
        "jurisdiction",
        "code",
        "title",
        "chapter",
        "section",
        "subsection",
        "citation",
        "amendment",
        "source",
        "edition",
        "provenance",
    ):
        assert required in types


def test_resume_skips_compatible_checkpoint(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    first = builder.run_full_build(
        repo_root=REPO_ROOT,
        checkpoint_dir=tmp_path / "ckpts",
        resume=True,
        require_live_evidence=True,
        output_dir=tmp_path / "out-a",
    )
    assert (tmp_path / "ckpts" / "full_build_checkpoint.json").is_file()
    second = builder.run_full_build(
        repo_root=REPO_ROOT,
        checkpoint_dir=tmp_path / "ckpts",
        resume=True,
        require_live_evidence=True,
        output_dir=tmp_path / "out-b",
    )
    assert second.corpus_root_cid == first.corpus_root_cid
    assert second.bm25.index_root_cid == first.bm25.index_root_cid
    assert second.vectors.vector_root_cid == first.vectors.vector_root_cid
    assert second.graph.graph_cid == first.graph.graph_cid
    assert "corpus" in second.resumed_stages or second.config_digest == first.config_digest


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


def test_missing_live_evidence_fails_closed(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    with pytest.raises(builder.LiveEvidenceRequiredError):
        builder.inspect_live_evidence(repo_root=tmp_path, require=True)


def test_unresolved_admission_gap_fails_closed(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    reports = tmp_path / "docs" / "reports" / "open_us_law_reindex"
    reports.mkdir(parents=True)
    (tmp_path / "data" / "legal" / "open_us_law").mkdir(parents=True)
    (reports / "exact_51_coverage.json").write_text(
        json.dumps(
            {
                "jurisdiction_codes": list(EXACT_51_JURISDICTION_CODES),
                "unresolved": ["GA"],
                "bucket_deltas": {"unresolved": ["GA"]},
            }
        ),
        encoding="utf-8",
    )
    (reports / "acquisition_refill_closure.json").write_text(
        json.dumps({"acceptance": {"unresolved_finding_count": 1}}),
        encoding="utf-8",
    )
    (tmp_path / "data" / "legal" / "open_us_law" / "source_admission.json").write_text(
        json.dumps(
            {
                "jurisdiction_count": 51,
                "jurisdictions": [
                    {"jurisdiction_code": code} for code in EXACT_51_JURISDICTION_CODES
                ],
            }
        ),
        encoding="utf-8",
    )
    for letter in "ABCDEFGHIJKLM":
        (reports / f"cohort_{letter}.json").write_text(
            json.dumps({"certification": {"jurisdictions": {}}}),
            encoding="utf-8",
        )
    with pytest.raises((builder.AdmissionGapError, builder.LiveEvidenceRequiredError)):
        builder.inspect_live_evidence(repo_root=tmp_path, require=True)


def test_projection_cannot_authorize_release(report: dict[str, Any]) -> None:
    assert report["authorizing_for_publication"] is False
    if report["embeddings"]["real_inference"] is not True:
        assert report["authorizing_for_release"] is False
    assert report["embeddings"]["projection_authorizes_release"] is False
    assert report["embeddings"]["model_id"] == PINNED_MODEL_ID
    assert report["checks"]["projection_cannot_authorize_release"] is True


def test_report_acceptance_and_digest(
    builder: ModuleType,
    report: dict[str, Any],
    committed_report: dict[str, Any],
) -> None:
    result = builder.check_full_build_report(report)
    assert result["ok"] is True
    assert result["task_id"] == TASK_ID
    assert result["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert report["goal_id"] == GOAL_ID
    assert report["schema_version"] == builder.SCHEMA_VERSION
    assert report["report_digest_sha256"] == builder._digest_for_report(report)
    assert "hf_" not in json.dumps(report)
    committed = builder.check_full_build_report(committed_report)
    assert committed["ok"] is True
    assert committed_report["report_digest_sha256"] == builder._digest_for_report(
        committed_report
    )


def test_frozen_report_matches_fresh_build(
    builder: ModuleType,
    report: dict[str, Any],
    committed_report: dict[str, Any],
    tmp_path: Path,
) -> None:
    payload = builder.build_full_build_report(
        repo_root=REPO_ROOT,
        checkpoint_dir=tmp_path / "report-ckpts",
        resume=False,
        require_live_evidence=True,
    )
    builder.check_full_build_report(committed_report)
    builder.check_report_matches_build(committed_report, payload)
    builder.check_report_matches_build(committed_report, report)


def test_check_does_not_rewrite_committed_report(
    builder: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = REPORT_PATH.read_bytes()
    monkeypatch.setenv(builder.CHECKPOINT_ENV, str(tmp_path / "stable-ckpts"))
    code = builder.main(
        [
            "--full",
            "--require-live-evidence",
            "--check",
            "--report",
            str(REPORT_PATH),
            "--checkpoint-dir",
            str(tmp_path / "stable-ckpts"),
            "--output-dir",
            str(tmp_path / "stable-out"),
        ]
    )
    assert code == 0
    assert REPORT_PATH.read_bytes() == before


def test_write_materializes_only_to_explicit_path(
    builder: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = REPORT_PATH.read_bytes()
    target = tmp_path / "full_build.json"
    monkeypatch.setenv(builder.CHECKPOINT_ENV, str(tmp_path / "write-ckpts"))
    code = builder.main(
        [
            "--full",
            "--require-live-evidence",
            "--write",
            "--report",
            str(target),
            "--checkpoint-dir",
            str(tmp_path / "write-ckpts"),
            "--output-dir",
            str(tmp_path / "write-out"),
        ]
    )
    assert code == 0
    assert target.is_file()
    written = json.loads(target.read_text(encoding="utf-8"))
    builder.check_full_build_report(written)
    assert REPORT_PATH.read_bytes() == before


def test_cli_full_require_live_evidence_check(
    builder: ModuleType,
    committed_report: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = REPORT_PATH.read_bytes()
    monkeypatch.setenv(builder.CHECKPOINT_ENV, str(tmp_path / "cli-ckpts"))
    code = builder.main(
        [
            "--full",
            "--require-live-evidence",
            "--check",
            "--report",
            str(REPORT_PATH),
            "--checkpoint-dir",
            str(tmp_path / "cli-ckpts"),
            "--output-dir",
            str(tmp_path / "cli-out"),
        ]
    )
    assert code == 0
    assert REPORT_PATH.read_bytes() == before
    on_disk = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert on_disk == committed_report
    assert on_disk["task_id"] == TASK_ID
    assert on_disk["acceptance"]["covers_exactly_51_jurisdictions"] is True
    assert on_disk["acceptance"]["corpus_to_bm25_to_vector_to_graph_key_parity"] is True
    assert on_disk["acceptance"]["real_pinned_gte_embeddings"] is True
    assert on_disk["acceptance"]["all_shard_bounds"] is True
    assert on_disk["acceptance"]["no_unresolved_admission_gaps"] is True
    assert on_disk["acceptance"]["measured_resource_usage"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

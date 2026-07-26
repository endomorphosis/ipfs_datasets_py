"""Executable evidence for the reviewed immutable benchmark corpus."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path

import pytest

import benchmarks.logic_pipeline as logic_pipeline
from benchmarks.logic_pipeline import cases
from benchmarks.logic_pipeline.contracts import Split


FROZEN_CORPUS_SHA256 = (
    "a2720cee073bfe4221594c5b29d8a4557865f272f4d2c2c3553dfeab74c03509"
)
FROZEN_SEMANTIC_SHA256 = (
    "9a1747aac8ab7393147795b7f756318a67f66b6f4eedd6ed368b0337c5e46932"
)
FROZEN_MANIFEST_SHA256 = (
    "58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26"
)


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path]:
    corpus_path = tmp_path / "corpus.jsonl"
    manifest_path = tmp_path / "manifest.json"
    corpus_path.write_bytes(cases.DEFAULT_CORPUS_PATH.read_bytes())
    manifest_path.write_bytes(cases.DEFAULT_MANIFEST_PATH.read_bytes())
    return corpus_path, manifest_path


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _write_lines(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(cases.canonical_json(value) + "\n" for value in values),
        encoding="utf-8",
    )


def _read_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    path.write_text(cases.canonical_json(value) + "\n", encoding="utf-8")


def test_objective_evidence_and_public_api_are_stable() -> None:
    assert (
        cases.HSSLEV0201B64()
        == "reviewed immutable semantic and proof benchmark corpus"
    )
    assert logic_pipeline.HSSLEV0201B64 is cases.HSSLEV0201B64
    assert cases.CASE_SCHEMA.endswith(".case.v1")
    assert cases.CORPUS_MANIFEST_SCHEMA.endswith(".corpus-manifest.v1")
    assert set(logic_pipeline.__all__) >= {
        "BenchmarkCase",
        "CorpusManifest",
        "ReviewedCorpus",
        "load_reviewed_corpus",
        "load_unsealed_pilot_development",
    }


def test_default_corpus_is_frozen_reviewed_and_representative() -> None:
    corpus = cases.load_reviewed_corpus()

    assert corpus.manifest.case_count == len(corpus.cases) == 30
    assert corpus.manifest.corpus_sha256 == FROZEN_CORPUS_SHA256
    assert corpus.manifest.semantic_sha256 == FROZEN_SEMANTIC_SHA256
    assert corpus.manifest_sha256 == FROZEN_MANIFEST_SHA256
    assert (
        cases.corpus_manifest_sha256(corpus.manifest)
        == FROZEN_MANIFEST_SHA256
    )
    assert {case.split for case in corpus.cases} == set(Split)
    assert len({case.stratum for case in corpus.cases}) == 10
    assert {case.expected_class for case in corpus.cases} == set(
        cases.ExpectedClass
    )
    assert tuple(corpus.by_id) == tuple(case.case_id for case in corpus.cases)


def test_unsealed_loader_stops_before_holdout_tail(tmp_path: Path) -> None:
    source_lines = cases.DEFAULT_CORPUS_PATH.read_bytes().splitlines(
        keepends=True
    )
    assert len(source_lines) == 30
    corpus_path = tmp_path / "corpus.jsonl"
    corpus_path.write_bytes(
        b"".join(source_lines[:20]) + b"{sealed-holdout-not-json}\n" * 10
    )

    manifest, unsealed = cases.load_unsealed_pilot_development(
        corpus_path,
        cases.DEFAULT_MANIFEST_PATH,
    )

    assert cases.corpus_manifest_sha256(manifest) == FROZEN_MANIFEST_SHA256
    assert len(unsealed) == 20
    assert {case.split for case in unsealed} == {
        Split.PILOT,
        Split.DEVELOPMENT,
    }


def test_every_case_has_acceptance_fields_and_reviewed_ground_truth() -> None:
    corpus = cases.load_reviewed_corpus()

    for case in corpus.cases:
        assert case.case_id
        assert case.split in Split
        assert case.stratum
        assert (
            hashlib.sha256(case.source_text.encode("utf-8")).hexdigest()
            == case.source_sha256
        )
        assert case.expected_class in cases.ExpectedClass
        assert case.expected_ir
        assert case.provenance["source_ref"]
        assert case.provenance["model_generated_ground_truth"] is False
        assert case.review.status == "approved"
        assert case.review.semantic_target_approved is True
        assert len(case.review.reviewer_ids) >= 2
        assert case.review.model_output_used is False
        if case.expected_class in {
            cases.ExpectedClass.PROVED,
            cases.ExpectedClass.DISPROVED,
        }:
            assert case.proof_obligation
            assert case.review.proof_obligation_approved
        else:
            assert case.proof_obligation is None
            assert not case.review.proof_obligation_approved


def test_manifest_binds_exact_case_order_and_content() -> None:
    corpus = cases.load_reviewed_corpus()
    assert tuple(entry.ordinal for entry in corpus.manifest.cases) == tuple(
        range(len(corpus.cases))
    )
    assert tuple(entry.case_id for entry in corpus.manifest.cases) == tuple(
        case.case_id for case in corpus.cases
    )
    assert tuple(entry.case_sha256 for entry in corpus.manifest.cases) == tuple(
        cases.case_sha256(case) for case in corpus.cases
    )
    assert (
        hashlib.sha256(cases.DEFAULT_CORPUS_PATH.read_bytes()).hexdigest()
        == corpus.manifest.corpus_sha256
    )
    with pytest.raises(cases.CorpusContractError, match="order or content"):
        cases.ReviewedCorpus(
            manifest=corpus.manifest,
            cases=tuple(reversed(corpus.cases)),
        )


def test_loaded_records_and_nested_semantics_are_deeply_immutable() -> None:
    corpus = cases.load_reviewed_corpus()
    case = corpus.cases[0]

    with pytest.raises(FrozenInstanceError):
        case.case_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        case.expected_ir["target"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        case.provenance["source_ref"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        corpus.by_id["new"] = case  # type: ignore[index]
    with pytest.raises(TypeError):
        corpus.manifest.split_counts["pilot"] = 0  # type: ignore[index]


def test_import_is_dependency_free_and_does_not_read_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {
        "hammer",
        "ipfs_datasets_py",
        "leanstral",
        "spacy",
        "symai",
        "symbolicai",
    }
    real_import = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.partition(".")[0] in forbidden:
            raise AssertionError(f"unexpected optional import: {name}")
        return real_import(name, *args, **kwargs)

    def fail_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("package import must not read fixture data")

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(Path, "read_bytes", fail_read)
    assert cases.HSSLEV0201B64()


def test_corpus_byte_tampering_fails_before_use(tmp_path: Path) -> None:
    corpus_path, manifest_path = _copy_fixture(tmp_path)
    raw = corpus_path.read_bytes()
    corpus_path.write_bytes(raw.replace(b"archivist", b"registrar", 1))

    with pytest.raises(cases.CorpusContractError, match="byte digest"):
        cases.load_reviewed_corpus(corpus_path, manifest_path)


def test_source_digest_tampering_fails_case_validation(tmp_path: Path) -> None:
    corpus_path, _ = _copy_fixture(tmp_path)
    values = _read_lines(corpus_path)
    values[0]["source_text"] = "Tampered source."
    _write_lines(corpus_path, values)

    with pytest.raises(cases.CorpusContractError, match="source_sha256"):
        cases.load_corpus(corpus_path)


def test_manifest_rejects_reordered_cases_even_with_new_corpus_digest(
    tmp_path: Path,
) -> None:
    corpus_path, manifest_path = _copy_fixture(tmp_path)
    values = _read_lines(corpus_path)
    values[0], values[1] = values[1], values[0]
    _write_lines(corpus_path, values)
    manifest = _read_manifest(manifest_path)
    manifest["corpus_sha256"] = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    _write_manifest(manifest_path, manifest)

    with pytest.raises(cases.CorpusContractError, match="order or content"):
        cases.load_reviewed_corpus(corpus_path, manifest_path)


def test_manifest_rejects_semantic_tampering_even_if_outer_digests_are_changed(
    tmp_path: Path,
) -> None:
    corpus_path, manifest_path = _copy_fixture(tmp_path)
    values = _read_lines(corpus_path)
    expected_ir = values[0]["expected_ir"]
    assert isinstance(expected_ir, dict)
    expected_ir["target"] = "tampered"
    _write_lines(corpus_path, values)
    parsed = cases.load_corpus(corpus_path)
    manifest = _read_manifest(manifest_path)
    manifest["corpus_sha256"] = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    entries = manifest["cases"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entries[0]["case_sha256"] = cases.case_sha256(parsed[0])
    _write_manifest(manifest_path, manifest)

    with pytest.raises(cases.CorpusContractError, match="semantic target digest"):
        cases.load_reviewed_corpus(corpus_path, manifest_path)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("review", "status"), "pending", "review status"),
        (("review", "model_output_used"), True, "model output"),
        (
            ("provenance", "model_generated_ground_truth"),
            True,
            "model-generated",
        ),
    ],
)
def test_unreviewed_or_model_generated_ground_truth_is_rejected(
    tmp_path: Path,
    path: tuple[str, str],
    value: object,
    message: str,
) -> None:
    corpus_path, _ = _copy_fixture(tmp_path)
    values = _read_lines(corpus_path)
    parent = values[0][path[0]]
    assert isinstance(parent, dict)
    parent[path[1]] = value
    _write_lines(corpus_path, values)

    with pytest.raises(cases.CorpusContractError, match=message):
        cases.load_corpus(corpus_path)


def test_provable_class_without_proof_obligation_is_rejected(
    tmp_path: Path,
) -> None:
    corpus_path, _ = _copy_fixture(tmp_path)
    values = _read_lines(corpus_path)
    values[0]["proof_obligation"] = None
    review = values[0]["review"]
    assert isinstance(review, dict)
    review["proof_obligation_approved"] = False
    _write_lines(corpus_path, values)

    with pytest.raises(cases.CorpusContractError, match="proof_obligation"):
        cases.load_corpus(corpus_path)


def test_unknown_and_duplicate_json_fields_fail_closed(tmp_path: Path) -> None:
    corpus_path, _ = _copy_fixture(tmp_path)
    values = _read_lines(corpus_path)
    values[0]["post_review_edit"] = True
    _write_lines(corpus_path, values)
    with pytest.raises(cases.CorpusContractError, match="unknown"):
        cases.load_corpus(corpus_path)

    first = cases.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8").splitlines()[0]
    duplicate = first.replace(
        '{"case_id":"pilot-p01",',
        '{"case_id":"pilot-p01","case_id":"pilot-p01",',
        1,
    )
    corpus_path.write_text(duplicate + "\n", encoding="utf-8")
    with pytest.raises(cases.CorpusContractError, match="duplicate JSON"):
        cases.load_corpus(corpus_path)


def test_noncanonical_json_and_missing_final_newline_are_rejected(
    tmp_path: Path,
) -> None:
    corpus_path, manifest_path = _copy_fixture(tmp_path)
    corpus_path.write_bytes(corpus_path.read_bytes().rstrip(b"\n"))
    with pytest.raises(cases.CorpusContractError, match="newline-terminated"):
        cases.load_corpus(corpus_path)

    manifest_path.write_text(
        json.dumps(_read_manifest(manifest_path), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(cases.CorpusContractError, match="canonical"):
        cases.load_manifest(manifest_path)

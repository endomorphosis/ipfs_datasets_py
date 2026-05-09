"""Tests for U.S. Code parquet dataset adapters."""

from __future__ import annotations

import os

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import ModalTodoSupervisor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyModalCodec,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
    HF_USCODE_DATASET_ID,
    USCODE_LAWS_PARQUET,
    iter_uscode_records_from_parquet,
    load_hf_uscode_samples,
    load_uscode_embeddings_from_parquet,
    load_uscode_samples_from_parquet,
)

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


def test_uscode_parquet_fixture_converts_to_legal_samples(tmp_path) -> None:
    laws_path, embeddings_path = _write_uscode_fixture(tmp_path)

    samples = load_uscode_samples_from_parquet(
        laws_path,
        embeddings_parquet=embeddings_path,
        limit=2,
    )

    assert len(samples) == 2
    assert samples[0].citation == "5 U.S.C. 552"
    assert samples[0].embedding_vector == [0.1, 0.2, 0.3]
    assert samples[0].modal_ir.formulas
    assert samples[1].selected_frame is not None


def test_uscode_embeddings_loader_uses_first_vector_per_cid(tmp_path) -> None:
    _, embeddings_path = _write_uscode_fixture(tmp_path)

    embeddings = load_uscode_embeddings_from_parquet(embeddings_path, cids=["cid-5-552"])

    assert embeddings == {"cid-5-552": [0.1, 0.2, 0.3]}


def test_supervisor_optimizes_uscode_parquet_samples(tmp_path) -> None:
    laws_path, embeddings_path = _write_uscode_fixture(tmp_path)
    samples = load_uscode_samples_from_parquet(
        laws_path,
        embeddings_parquet=embeddings_path,
        limit=2,
    )
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor()
    before = autoencoder.evaluate(samples)

    run = supervisor.optimize(
        samples,
        autoencoder=autoencoder,
        max_iterations=3,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.final_evaluation.cross_entropy_loss < before.cross_entropy_loss
    assert run.final_evaluation.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert supervisor.queue.status_counts()["completed"] >= 4


def test_supervisor_can_load_and_optimize_uscode_parquet_directly(tmp_path) -> None:
    laws_path, embeddings_path = _write_uscode_fixture(tmp_path)
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor()

    run = supervisor.optimize_uscode_parquet(
        laws_path,
        embeddings_parquet=embeddings_path,
        autoencoder=autoencoder,
        limit=2,
        max_iterations=2,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.steps
    assert run.final_evaluation.embedding_cosine_similarity > 0.999


def test_supervisor_optimizes_uscode_parquet_with_spacy_codec(tmp_path) -> None:
    laws_path, embeddings_path = _write_uscode_fixture(tmp_path)
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )
    supervisor = ModalTodoSupervisor()

    run = supervisor.optimize_uscode_parquet(
        laws_path,
        embeddings_parquet=embeddings_path,
        autoencoder=autoencoder,
        limit=2,
        max_iterations=2,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.final_evaluation.cross_entropy_loss < run.steps[0].before.cross_entropy_loss
    assert run.final_evaluation.embedding_cosine_similarity > run.steps[0].before.embedding_cosine_similarity
    assert supervisor.queue.status_counts()["completed"] >= 4


def test_iter_uscode_records_honors_limit(tmp_path) -> None:
    laws_path, _ = _write_uscode_fixture(tmp_path)

    records = list(iter_uscode_records_from_parquet(laws_path, limit=1))

    assert len(records) == 1
    assert records[0].citation == "5 U.S.C. 552"


def test_uscode_loaders_support_offsets_for_holdout_windows(tmp_path) -> None:
    laws_path, embeddings_path = _write_uscode_fixture(tmp_path)

    records = list(iter_uscode_records_from_parquet(laws_path, limit=1, offset=1))
    samples = load_uscode_samples_from_parquet(
        laws_path,
        embeddings_parquet=embeddings_path,
        limit=1,
        offset=1,
    )

    assert records[0].citation == "42 U.S.C. 1983"
    assert samples[0].citation == "42 U.S.C. 1983"
    assert samples[0].embedding_vector == [0.4, 0.5, 0.6]


def test_supervisor_can_validate_uscode_parquet_on_holdout_offset(tmp_path) -> None:
    laws_path, embeddings_path = _write_uscode_fixture(tmp_path)
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor()

    run = supervisor.optimize_uscode_parquet(
        laws_path,
        embeddings_parquet=embeddings_path,
        autoencoder=autoencoder,
        limit=1,
        offset=0,
        validation_limit=1,
        validation_offset=1,
        max_iterations=1,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.steps[0].validation_before is not None
    assert run.steps[0].validation_after is not None
    assert run.validation_final_evaluation is not None


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_PY_RUN_HF_USCODE_LIVE") != "1",
    reason="Set IPFS_DATASETS_PY_RUN_HF_USCODE_LIVE=1 to hit Hugging Face.",
)
def test_hf_uscode_live_dataset_smoke() -> None:
    samples = load_hf_uscode_samples(limit=2)

    assert HF_USCODE_DATASET_ID == "justicedao/ipfs_uscode"
    assert USCODE_LAWS_PARQUET == "uscode_parquet/laws.parquet"
    assert len(samples) == 2
    assert all(sample.source == "us_code" for sample in samples)


def _write_uscode_fixture(tmp_path):
    laws_path = tmp_path / "laws.parquet"
    embeddings_path = tmp_path / "laws_embeddings.parquet"
    laws_table = pa.table(
        {
            "ipfs_cid": ["cid-5-552", "cid-42-1983", "cid-18-1001"],
            "title_number": ["5", "42", "18"],
            "title_name": ["Government Organization", "Public Health", "Crimes"],
            "section_number": ["552", "1983", "1001"],
            "law_name": [
                "Public information",
                "Civil action for deprivation of rights",
                "Statements or entries generally",
            ],
            "source_url": [
                "https://uscode.house.gov/view.xhtml?req=5+552",
                "https://uscode.house.gov/view.xhtml?req=42+1983",
                "https://uscode.house.gov/view.xhtml?req=18+1001",
            ],
            "text": [
                "Each agency must make records promptly available to any person.",
                "Every person may bring an action when rights are deprived under color of law.",
                "Whoever knowingly makes a false statement shall be fined or imprisoned.",
            ],
            "citation_text": ["5 U.S.C. 552", "42 U.S.C. 1983", "18 U.S.C. 1001"],
            "normalized_citation": ["5 U.S.C. 552", "42 U.S.C. 1983", "18 U.S.C. 1001"],
        }
    )
    embeddings_table = pa.table(
        {
            "cid": ["cid-5-552", "cid-42-1983", "cid-18-1001"],
            "embedding": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.6, 0.2, 0.1]],
            "text_chunk_order": [0, 0, 0],
        }
    )
    pq.write_table(laws_table, laws_path)
    pq.write_table(embeddings_table, embeddings_path)
    return laws_path, embeddings_path

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers._utils.make_openai_embeddings import (
    RouterEmbedding,
    _derive_output_parquet_path,
    _resolve_input_dir,
)


def test_router_embedding_defaults_to_gte_small() -> None:
    embedder = RouterEmbedding()
    assert embedder.model == "thenlper/gte-small"
    assert embedder.device == "cuda"


def test_prepare_row_for_embedding_excludes_cid_and_embedding_cid() -> None:
    embedder = RouterEmbedding()
    row = {
        "cid": "bafy-secret-cid",
        "embedding_cid": "bafy-embedding-id",
        "title": "US Code Title",
        "section_text": "This section governs legal obligations.",
    }

    text = embedder._prepare_row_for_embedding(row)

    assert "bafy-secret-cid" not in text
    assert "bafy-embedding-id" not in text
    assert "US Code Title" in text
    assert "governs legal obligations" in text


def test_prepare_row_for_embedding_fallback_omits_identifier_fields() -> None:
    embedder = RouterEmbedding()
    row = {
        "cid": "bafy-omit-me",
        "id": "internal-id",
        "content": "",
        "custom_text": "Meaningful provision text.",
    }

    text = embedder._prepare_row_for_embedding(row)

    assert "bafy-omit-me" not in text
    assert "internal-id" not in text
    assert "Meaningful provision text." in text


def test_prepare_row_for_embedding_skips_json_and_url_metadata() -> None:
    embedder = RouterEmbedding()
    row = {
        "ipfs_cid": "bafy-ignore-this",
        "source_url": "https://example.com/law",
        "raw_json": '{"x": 1, "y": 2}',
        "text": "Primary legal text content for retrieval.",
        "law_name": "Sample Law Name",
        "title_name": "General Provisions",
    }

    text = embedder._prepare_row_for_embedding(row)

    assert "bafy-ignore-this" not in text
    assert "https://example.com/law" not in text
    assert '{"x": 1, "y": 2}' not in text
    assert "Primary legal text content for retrieval." in text
    assert "Sample Law Name" in text


def test_resolve_input_dir_supports_fish_uri() -> None:
    path = _resolve_input_dir("fish://barberb@192.168.0.48/home/barberb/.ipfs_datasets/us_code/uscode_parquet/")
    assert path == Path("/home/barberb/.ipfs_datasets/us_code/uscode_parquet")


def test_derive_output_parquet_path_generic_and_html() -> None:
    assert _derive_output_parquet_path(Path("/tmp/123_html.parquet")) == Path("/tmp/123_embeddings.parquet")
    assert _derive_output_parquet_path(Path("/tmp/title_1.parquet")) == Path("/tmp/title_1_embeddings.parquet")

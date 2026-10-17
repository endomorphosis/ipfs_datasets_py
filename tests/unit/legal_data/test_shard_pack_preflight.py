"""A shard directory with a bad revision or unpacked articles fails before build."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.build import (
    build_country,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
    preflight_local_shard_source,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.load_sharded_laws import (
    load_sharded_laws,
)

_SHA = "351bceff9e8e77acdc7222e303e6af644bc80e02"


def _shard_dir(root: Path) -> Path:
    source = root / "austria_municipal"
    data = source / "data"
    data.mkdir(parents=True)
    pq.write_table(pa.table({"id": ["a"]}), data / "laws-00001.parquet")
    pq.write_table(pa.table({"article": ["1"]}), data / "articles-00001.parquet")
    return source


def test_missing_revision_fails_before_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _shard_dir(tmp_path)

    def _build_must_not_start(*_args, **_kwargs):
        raise AssertionError("build must not start")

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.build.get_country",
        _build_must_not_start,
    )
    with pytest.raises(ValueError, match="40 lowercase hex"):
        preflight_local_shard_source(str(source))
    with pytest.raises(ValueError, match="40 lowercase hex"):
        build_country(str(source))


def test_article_shards_without_articles_parquet_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _shard_dir(tmp_path)
    (source / "pack_meta.json").write_text(
        '{"slug": "austria_municipal", "source_revision": "%s"}\n' % _SHA,
        encoding="utf-8",
    )
    import ipfs_datasets_py.processors.legal_scrapers.world_law.load_sharded_laws as pack

    real_concat = pack._concat

    def _skip_articles(shards: list[Path], dest: Path) -> None:
        if dest.name == "articles.parquet":
            return
        real_concat(shards, dest)

    monkeypatch.setattr(pack, "_concat", _skip_articles)
    with pytest.raises(FileNotFoundError, match="data/articles.parquet"):
        load_sharded_laws(
            source,
            tmp_path / "packed",
            slug="austria_municipal",
            source_dataset="endomorphosis/ipfs_austria_municipal_laws",
            source_revision=_SHA,
        )
    assert not (tmp_path / "packed" / "data" / "articles.parquet").exists()

"""Concatenate ``data/laws-*.parquet`` into the single file ``load_source`` can read.

``*_html.parquet`` is ignored. Article shards are written to ``data/articles.parquet``
when any exist. ``pack_meta.json`` stores a 40-hex Hub SHA.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")


def require_source_revision(source_dir: Path) -> str:
    """Return the pack SHA, or raise before a build reads the directory."""

    meta = _read_pack_meta(source_dir)
    revision = str(meta.get("source_revision") or meta.get("revision") or "")
    if _SHA.fullmatch(revision) is None:
        raise ValueError("source_revision must be 40 lowercase hex characters")
    return revision


def _read_pack_meta(source_dir: Path) -> dict[str, object]:
    meta_path = Path(source_dir) / "pack_meta.json"
    if not meta_path.is_file():
        return {}
    try:
        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def load_sharded_laws(
    source_dir: Path,
    dest_dir: Path,
    *,
    slug: str,
    source_dataset: str,
    source_revision: str,
) -> dict[str, object]:
    if _SHA.fullmatch(source_revision) is None:
        raise ValueError("source_revision must be 40 lowercase hex characters")
    data_in = Path(source_dir)
    data_out = Path(dest_dir) / "data"
    data_out.mkdir(parents=True, exist_ok=True)
    law_shards = _shards(data_in, "laws")
    if not law_shards:
        raise FileNotFoundError(f"no data/laws-*.parquet shards in {data_in}")
    _concat(law_shards, data_out / "laws.parquet")
    article_shards = _shards(data_in, "articles")
    if article_shards:
        articles_path = data_out / "articles.parquet"
        _concat(article_shards, articles_path)
        if not articles_path.is_file():
            raise FileNotFoundError(
                "article shards were not written to data/articles.parquet"
            )
    meta = {
        "slug": slug,
        "source_dataset": source_dataset,
        "source_revision": source_revision,
    }
    (Path(dest_dir) / "pack_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "laws": str(data_out / "laws.parquet"),
        "articles": str(data_out / "articles.parquet") if article_shards else None,
        "pack_meta": meta,
    }


def _shards(source_dir: Path, stem: str) -> list[Path]:
    data = source_dir / "data"
    if not data.is_dir():
        return []
    found = []
    for path in sorted(data.glob(f"{stem}-*.parquet")):
        if path.name.endswith("_html.parquet") or "_html" in path.name:
            continue
        found.append(path)
    return found


def _concat(shards: list[Path], dest: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    tables = [pq.read_table(path) for path in shards]
    table = pa.concat_tables(tables, promote_options="default")
    pq.write_table(table, dest)

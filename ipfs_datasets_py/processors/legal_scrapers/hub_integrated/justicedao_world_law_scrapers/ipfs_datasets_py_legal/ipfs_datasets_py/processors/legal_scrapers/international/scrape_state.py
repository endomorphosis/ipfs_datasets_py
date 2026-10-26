"""Skip already-published Hugging Face gazette rows on later collector runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .catalog import get_snapshot_corpus
from .helpers.paths import corpora_root

STATE_FILENAME = "huggingface_scrape_state.json"
PUBLISHED_IDS_FILENAME = "published_ids.jsonl"
INDEX_FILENAME = "index.jsonl"
SKIP_KEY_FIELDS = (
    "id",
    "identifier",
    "official_identifier",
    "source_url",
    "eli",
    "json_path",
)


@dataclass(frozen=True)
class PublishedScrapeState:
    country_code: str
    dataset_id: str
    revision: str = ""
    synced_at: str = ""
    law_count: int = 0
    skip_key_count: int = 0
    index_seeded: bool = False
    parquet_path: str = ""
    skipped_download: bool = False
    error: Optional[str] = None
    skip_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("skip_keys", None)
        return payload


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def jurisdiction_dir(country_code: str, *, corpora_dir: Path | str | None = None) -> Path:
    root = Path(corpora_dir).expanduser().resolve() if corpora_dir else corpora_root()
    return root / str(country_code or "").strip().lower()


def state_path(country_code: str, *, corpora_dir: Path | str | None = None) -> Path:
    return jurisdiction_dir(country_code, corpora_dir=corpora_dir) / STATE_FILENAME


def published_ids_path(country_code: str, *, corpora_dir: Path | str | None = None) -> Path:
    return jurisdiction_dir(country_code, corpora_dir=corpora_dir) / PUBLISHED_IDS_FILENAME


def _slug_id(cc: str, official: str) -> str:
    value = (official or "").strip()
    value = value.replace("https://", "").replace("http://", "")
    value = re.sub(r"[/\\]+", "__", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value)
    value = value.strip("-._").lower()
    if not value:
        return ""
    prefix = str(cc or "").strip().lower()
    if prefix and not value.startswith(f"{prefix}-"):
        value = f"{prefix}-{value}"
    return value[:180]


def skip_keys_for_row(country_code: str, row: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in SKIP_KEY_FIELDS:
        raw = row.get(field)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        keys.add(text)
        if field == "json_path":
            stem = Path(text).stem
            if stem:
                keys.add(stem)
        slug = _slug_id(country_code, text)
        if slug:
            keys.add(slug)
    return {key for key in keys if key}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.is_file():
        return keys
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                keys.add(line)
                continue
            if isinstance(payload, dict):
                for field in ("id", "identifier", "official_identifier", "source_url", "eli"):
                    value = str(payload.get(field) or "").strip()
                    if value:
                        keys.add(value)
            elif payload:
                keys.add(str(payload))
    return keys


def load_skip_keys(country_code: str, *, corpora_dir: Path | str | None = None) -> set[str]:
    folder = jurisdiction_dir(country_code, corpora_dir=corpora_dir)
    keys: set[str] = set()
    instruments = folder / "instruments"
    if instruments.is_dir():
        keys.update(path.stem for path in instruments.glob("*.json"))
    keys.update(_read_jsonl_keys(folder / PUBLISHED_IDS_FILENAME))
    keys.update(_read_jsonl_keys(folder / INDEX_FILENAME))
    state = _read_json(folder / STATE_FILENAME)
    for item in state.get("skip_keys") or []:
        value = str(item or "").strip()
        if value:
            keys.add(value)
    return keys


def load_published_scrape_state(country_code: str, *, corpora_dir: Path | str | None = None) -> PublishedScrapeState | None:
    payload = _read_json(state_path(country_code, corpora_dir=corpora_dir))
    if not payload:
        return None
    return PublishedScrapeState(
        country_code=str(payload.get("country_code") or country_code).upper(),
        dataset_id=str(payload.get("dataset_id") or ""),
        revision=str(payload.get("revision") or ""),
        synced_at=str(payload.get("synced_at") or ""),
        law_count=int(payload.get("law_count") or 0),
        skip_key_count=int(payload.get("skip_key_count") or 0),
        index_seeded=bool(payload.get("index_seeded")),
        parquet_path=str(payload.get("parquet_path") or ""),
        skipped_download=True,
    )


def _dataset_revision(dataset_id: str) -> str:
    try:
        from huggingface_hub import HfApi

        info = HfApi().dataset_info(dataset_id)
        return str(getattr(info, "sha", "") or "")
    except Exception:
        return ""


def _download_laws_parquet(dataset_id: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import hf_hub_download

    local = hf_hub_download(
        repo_id=dataset_id,
        filename="data/laws.parquet",
        repo_type="dataset",
        local_dir=str(dest.parent.parent / "hf_snapshot"),
    )
    return Path(local)


def _rows_from_parquet(path: Path) -> list[dict[str, Any]]:
    wanted = ["id", "identifier", "official_identifier", "source_url", "eli", "json_path"]
    try:
        import pyarrow.parquet as pq

        schema_names = set(pq.read_schema(path).names)
        columns = [name for name in wanted if name in schema_names]
        table = pq.read_table(path, columns=columns)
        return table.to_pylist()
    except Exception:
        pass
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
        keep = [name for name in wanted if name in frame.columns]
        return frame[keep].to_dict(orient="records")
    except Exception as exc:
        raise RuntimeError(f"Unable to read laws parquet {path}: {exc}") from exc


def _write_published_ids(path: Path, rows: Sequence[Mapping[str, Any]], country_code: str) -> set[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: set[str] = set()
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            row_keys = sorted(skip_keys_for_row(country_code, row))
            keys.update(row_keys)
            payload = {
                "id": str(row.get("id") or "").strip() or None,
                "identifier": str(row.get("identifier") or "").strip() or None,
                "official_identifier": str(row.get("official_identifier") or "").strip() or None,
                "source_url": str(row.get("source_url") or "").strip() or None,
                "eli": str(row.get("eli") or "").strip() or None,
                "skip_keys": row_keys,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return keys


def _seed_index_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> int:
    existing = _read_jsonl_keys(path)
    added = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            ident = str(row.get("id") or "").strip()
            if not ident or ident in existing:
                continue
            handle.write(
                json.dumps(
                    {
                        "id": ident,
                        "identifier": str(row.get("identifier") or "").strip() or None,
                        "source_url": str(row.get("source_url") or "").strip() or None,
                        "status": "published_huggingface",
                        "source": "huggingface",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            existing.add(ident)
            added += 1
    return added


def sync_published_scrape_state(
    key: str,
    *,
    corpora_dir: Path | str | None = None,
    force: bool = False,
    download: bool = True,
    rows: Optional[Iterable[Mapping[str, Any]]] = None,
    revision: Optional[str] = None,
) -> PublishedScrapeState:
    entry = get_snapshot_corpus(key)
    country_code = entry.country_code
    folder = jurisdiction_dir(country_code, corpora_dir=corpora_dir)
    folder.mkdir(parents=True, exist_ok=True)
    cached = load_published_scrape_state(country_code, corpora_dir=corpora_dir)
    remote_revision = str(revision or "").strip()
    provided_rows = [dict(row) for row in rows] if rows is not None else None

    if provided_rows is None and download and not remote_revision:
        remote_revision = _dataset_revision(entry.source_dataset_id)

    if (
        not force
        and provided_rows is None
        and cached is not None
        and cached.skip_key_count > 0
        and published_ids_path(country_code, corpora_dir=corpora_dir).is_file()
        and (not remote_revision or cached.revision == remote_revision)
    ):
        return PublishedScrapeState(
            country_code=cached.country_code,
            dataset_id=cached.dataset_id or entry.source_dataset_id,
            revision=cached.revision,
            synced_at=cached.synced_at,
            law_count=cached.law_count,
            skip_key_count=cached.skip_key_count,
            index_seeded=cached.index_seeded,
            parquet_path=cached.parquet_path,
            skipped_download=True,
        )

    parquet_path = ""
    try:
        if provided_rows is None:
            if not download:
                if cached is not None:
                    return cached
                return PublishedScrapeState(
                    country_code=country_code,
                    dataset_id=entry.source_dataset_id,
                    error="No local Hugging Face scrape state to reuse",
                )
            local_parquet = _download_laws_parquet(entry.source_dataset_id, folder / "hf_snapshot" / "data" / "laws.parquet")
            parquet_path = str(local_parquet)
            law_rows = _rows_from_parquet(local_parquet)
        else:
            law_rows = provided_rows
        skip_keys = _write_published_ids(folder / PUBLISHED_IDS_FILENAME, law_rows, country_code)
        seeded = _seed_index_jsonl(folder / INDEX_FILENAME, law_rows)
        state = PublishedScrapeState(
            country_code=country_code,
            dataset_id=entry.source_dataset_id,
            revision=remote_revision,
            synced_at=_utcnow(),
            law_count=len(law_rows),
            skip_key_count=len(skip_keys),
            index_seeded=seeded > 0 or (cached.index_seeded if cached else False),
            parquet_path=parquet_path,
            skipped_download=False,
            skip_keys=sorted(skip_keys),
        )
        (folder / STATE_FILENAME).write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
        return state
    except Exception as exc:
        if cached is not None:
            return PublishedScrapeState(
                country_code=cached.country_code,
                dataset_id=cached.dataset_id,
                revision=cached.revision,
                synced_at=cached.synced_at,
                law_count=cached.law_count,
                skip_key_count=cached.skip_key_count,
                index_seeded=cached.index_seeded,
                parquet_path=cached.parquet_path,
                skipped_download=True,
                error=str(exc),
            )
        return PublishedScrapeState(
            country_code=country_code,
            dataset_id=entry.source_dataset_id,
            error=str(exc),
        )


__all__ = [
    "INDEX_FILENAME",
    "PUBLISHED_IDS_FILENAME",
    "PublishedScrapeState",
    "STATE_FILENAME",
    "jurisdiction_dir",
    "load_published_scrape_state",
    "load_skip_keys",
    "published_ids_path",
    "skip_keys_for_row",
    "state_path",
    "sync_published_scrape_state",
]

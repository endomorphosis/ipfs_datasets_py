"""CID-keyed incremental GraphRAG rebuild for country-laws IR.

Follows the US Code / patent persistent-index pattern:

* ``entry_cid`` is the durable identity (not positional ``document_index``).
* A matching source revision + parquet digest is a no-op.
* Unchanged CIDs reuse embeddings; BM25/graph are rebuilt from the current
  corpus because ``document_index`` is a shard pointer, not an identity.
* Delta refresh is never labeled equivalent to a full rebuild.

Public Hub reads stay anonymous. Publication to ``justicedao/*`` is a separate
gated upload step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from . import SCHEMA_VERSION

class RebuildKind(str, Enum):
    UNCHANGED = "unchanged"
    DELTA_REFRESH = "delta_refresh"
    FULL_REBUILD = "full_rebuild"

    @classmethod
    def coerce(cls, value: Any) -> "RebuildKind":
        if isinstance(value, RebuildKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "skip": cls.UNCHANGED,
            "noop": cls.UNCHANGED,
            "none": cls.UNCHANGED,
            "delta": cls.DELTA_REFRESH,
            "incremental": cls.DELTA_REFRESH,
            "partial": cls.DELTA_REFRESH,
            "full": cls.FULL_REBUILD,
            "rebuild": cls.FULL_REBUILD,
            "force": cls.FULL_REBUILD,
        }
        if text in aliases:
            return aliases[text]
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        raise ValueError(f"unknown rebuild kind: {value!r}")


class BuildMode(str, Enum):
    AUTO = "auto"
    FULL = "full"
    DELTA = "delta"

    @classmethod
    def coerce(cls, value: Any) -> "BuildMode":
        if isinstance(value, BuildMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "incremental": cls.DELTA,
            "diff": cls.DELTA,
            "rebuild": cls.FULL,
            "complete": cls.FULL,
        }
        if text in aliases:
            return aliases[text]
        for mode in cls:
            if mode.value == text or mode.name.lower() == text:
                return mode
        raise ValueError(f"unknown build mode: {value!r}")


@dataclass(frozen=True)
class CorpusDelta:
    added_cids: tuple[str, ...] = ()
    removed_cids: tuple[str, ...] = ()
    unchanged_cids: tuple[str, ...] = ()
    prior_count: int = 0
    current_count: int = 0
    changed_ratio: float = 1.0
    equivalent_to_full: bool = False

    @property
    def n_added(self) -> int:
        return len(self.added_cids)

    @property
    def n_removed(self) -> int:
        return len(self.removed_cids)

    @property
    def n_unchanged(self) -> int:
        return len(self.unchanged_cids)

    def to_dict(self, *, include_cids: bool = False, cid_sample: int = 8) -> dict[str, Any]:
        payload = {
            "n_added": self.n_added,
            "n_removed": self.n_removed,
            "n_unchanged": self.n_unchanged,
            "prior_count": self.prior_count,
            "current_count": self.current_count,
            "changed_ratio": self.changed_ratio,
            "equivalent_to_full": self.equivalent_to_full,
        }
        if include_cids:
            payload["added_cids"] = list(self.added_cids)
            payload["removed_cids"] = list(self.removed_cids)
            payload["unchanged_cids"] = list(self.unchanged_cids)
        else:
            payload["added_cids_sample"] = list(self.added_cids[:cid_sample])
            payload["removed_cids_sample"] = list(self.removed_cids[:cid_sample])
        return payload


@dataclass(frozen=True)
class RebuildPlan:
    kind: RebuildKind
    mode: BuildMode
    reason: str
    source_revision: str
    prior_revision: str | None = None
    source_fingerprint: str = ""
    prior_fingerprint: str | None = None
    delta: CorpusDelta | None = None
    reuse_embeddings: bool = False
    skip_build: bool = False
    equivalent_to_full: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "mode": self.mode.value,
            "reason": self.reason,
            "source_revision": self.source_revision,
            "prior_revision": self.prior_revision,
            "source_fingerprint": self.source_fingerprint,
            "prior_fingerprint": self.prior_fingerprint,
            "delta": None if self.delta is None else self.delta.to_dict(include_cids=False),
            "reuse_embeddings": self.reuse_embeddings,
            "skip_build": self.skip_build,
            "equivalent_to_full": self.equivalent_to_full,
            "schema_version": SCHEMA_VERSION,
        }


@dataclass
class PriorRelease:
    directory: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    corpus: pd.DataFrame | None = None
    vectors_by_cid: dict[str, list[float]] | None = None

    @property
    def source_revision(self) -> str | None:
        return (
            self.manifest.get("dataset_revision")
            or (self.manifest.get("source") or {}).get("source_revision")
        )

    @property
    def fingerprint(self) -> str:
        return source_fingerprint_from_manifest(self.manifest)


def source_fingerprint(source_meta: Mapping[str, Any]) -> str:
    """Stable skip key: Hub SHA plus parquet digests when present."""
    revision = str(source_meta.get("source_revision") or "")
    laws = str(source_meta.get("laws_sha256") or "")
    articles = str(source_meta.get("articles_sha256") or "")
    return f"{revision}|{laws}|{articles}"


def source_fingerprint_from_manifest(manifest: Mapping[str, Any]) -> str:
    revision = str(
        manifest.get("dataset_revision")
        or (manifest.get("source") or {}).get("source_revision")
        or ""
    )
    sha = manifest.get("input_sha256") or {}
    laws = str(sha.get("laws.parquet") or "")
    articles = str(sha.get("articles.parquet") or "")
    if not laws and not articles:
        src = manifest.get("source") or {}
        laws = str(src.get("laws_sha256") or "")
        articles = str(src.get("articles_sha256") or "")
    return f"{revision}|{laws}|{articles}"


def _cid_set(frame: pd.DataFrame | None) -> set[str]:
    if frame is None or frame.empty or "entry_cid" not in frame.columns:
        return set()
    return {str(x) for x in frame["entry_cid"].dropna().astype(str) if str(x).strip()}


def diff_corpus(
    prior: pd.DataFrame | None,
    current: pd.DataFrame,
) -> CorpusDelta:
    """Diff two CID-keyed corpora. Same ``entry_cid`` implies same body."""
    current_cids = _cid_set(current)
    prior_cids = _cid_set(prior)
    added = tuple(sorted(current_cids - prior_cids))
    removed = tuple(sorted(prior_cids - current_cids))
    unchanged = tuple(sorted(current_cids & prior_cids))
    current_count = int(len(current_cids))
    prior_count = int(len(prior_cids))
    if current_count == 0:
        ratio = 1.0 if prior_count else 0.0
    else:
        ratio = 1.0 - (len(unchanged) / float(current_count))
    equivalent = prior_count == 0 or (not unchanged and current_count > 0)
    return CorpusDelta(
        added_cids=added,
        removed_cids=removed,
        unchanged_cids=unchanged,
        prior_count=prior_count,
        current_count=current_count,
        changed_ratio=float(ratio),
        equivalent_to_full=equivalent,
    )


def plan_rebuild(
    *,
    mode: BuildMode | str,
    source_meta: Mapping[str, Any],
    prior: PriorRelease | None,
    current_corpus: pd.DataFrame | None = None,
    force: bool = False,
    rebuild_stub_vectors: bool = True,
    compare_normalized: bool = False,
) -> RebuildPlan:
    """Decide skip / delta / full from source fingerprints and CID overlap."""
    mode = BuildMode.coerce(mode)
    revision = str(source_meta.get("source_revision") or "")
    fingerprint = source_fingerprint(source_meta)
    prior_revision = prior.source_revision if prior is not None else None
    prior_fp = prior.fingerprint if prior is not None else None

    if force or mode is BuildMode.FULL:
        delta = None
        if current_corpus is not None and prior is not None:
            delta = diff_corpus(prior.corpus, current_corpus)
        return RebuildPlan(
            kind=RebuildKind.FULL_REBUILD,
            mode=mode,
            reason="operator forced full rebuild" if force else "build mode is full",
            source_revision=revision,
            prior_revision=prior_revision,
            source_fingerprint=fingerprint,
            prior_fingerprint=prior_fp,
            delta=delta,
            reuse_embeddings=False,
            skip_build=False,
            equivalent_to_full=True,
        )

    if prior is None:
        return RebuildPlan(
            kind=RebuildKind.FULL_REBUILD,
            mode=mode,
            reason="no prior release",
            source_revision=revision,
            prior_revision=None,
            source_fingerprint=fingerprint,
            prior_fingerprint=None,
            delta=None,
            reuse_embeddings=False,
            skip_build=False,
            equivalent_to_full=True,
        )

    prior_vector_status = str(
        ((prior.manifest.get("vector") or {}) if prior.manifest else {}).get("status")
        or ((prior.manifest.get("incremental") or {}).get("vectors") or {}).get("status")
        or ""
    ).strip().lower()
    stub_vectors = rebuild_stub_vectors and prior_vector_status in {
        "stub",
        "stub_missing_encoder",
        "incomplete",
        "partial",
    }

    fingerprint_match = bool(prior_fp == fingerprint and fingerprint.strip("|") and not stub_vectors)
    if fingerprint_match and not (compare_normalized and current_corpus is not None):
        return RebuildPlan(
            kind=RebuildKind.UNCHANGED,
            mode=mode,
            reason="source revision and parquet digests match prior release",
            source_revision=revision,
            prior_revision=prior_revision,
            source_fingerprint=fingerprint,
            prior_fingerprint=prior_fp,
            delta=CorpusDelta(
                unchanged_cids=tuple(sorted(_cid_set(prior.corpus))),
                prior_count=int(len(_cid_set(prior.corpus))),
                current_count=int(len(_cid_set(prior.corpus))),
                changed_ratio=0.0,
                equivalent_to_full=False,
            ),
            reuse_embeddings=True,
            skip_build=True,
            equivalent_to_full=False,
        )

    delta = None
    if current_corpus is not None:
        delta = diff_corpus(prior.corpus, current_corpus)
        if delta.n_added == 0 and delta.n_removed == 0 and not stub_vectors:
            return RebuildPlan(
                kind=RebuildKind.UNCHANGED,
                mode=mode,
                reason="normalized entry_cids match the prior release",
                source_revision=revision,
                prior_revision=prior_revision,
                source_fingerprint=fingerprint,
                prior_fingerprint=prior_fp,
                delta=delta,
                reuse_embeddings=True,
                skip_build=True,
                equivalent_to_full=False,
            )
        if delta.equivalent_to_full:
            return RebuildPlan(
                kind=RebuildKind.FULL_REBUILD,
                mode=mode,
                reason="CID overlap is empty; delta equals a full rebuild",
                source_revision=revision,
                prior_revision=prior_revision,
                source_fingerprint=fingerprint,
                prior_fingerprint=prior_fp,
                delta=delta,
                reuse_embeddings=False,
                skip_build=False,
                equivalent_to_full=True,
            )

    reason = (
        "source fingerprint matches but vectors are stub/incomplete; encode missing CIDs"
        if stub_vectors and prior_fp == fingerprint
        else "source changed; reuse embeddings for unchanged entry_cids"
    )
    return RebuildPlan(
        kind=RebuildKind.DELTA_REFRESH,
        mode=mode,
        reason=reason,
        source_revision=revision,
        prior_revision=prior_revision,
        source_fingerprint=fingerprint,
        prior_fingerprint=prior_fp,
        delta=delta,
        reuse_embeddings=True,
        skip_build=False,
        equivalent_to_full=False,
    )


def _read_sharded_parquet(directory: Path) -> pd.DataFrame | None:
    if not directory.is_dir():
        return None
    parts = sorted(directory.glob("part-*.parquet"))
    if not parts:
        parts = sorted(p for p in directory.rglob("*.parquet") if p.is_file())
    if not parts:
        return None
    frames = [pd.read_parquet(p) for p in parts]
    return pd.concat(frames, ignore_index=True) if frames else None


def load_release_manifest(release_dir: Path) -> dict[str, Any]:
    path = Path(release_dir) / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_release_corpus(release_dir: Path) -> pd.DataFrame | None:
    release_dir = Path(release_dir)
    corpus = _read_sharded_parquet(release_dir / "data" / "corpus")
    if corpus is not None:
        return corpus
    checkpoint = release_dir / "corpus.parquet"
    if checkpoint.is_file():
        return pd.read_parquet(checkpoint)
    return None


def embeddings_from_vector_table(frame: pd.DataFrame) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    if frame is None or frame.empty:
        return out
    if "entry_cid" not in frame.columns or "embedding" not in frame.columns:
        return out
    for rec in frame.itertuples(index=False):
        cid = str(getattr(rec, "entry_cid", "") or "")
        emb = getattr(rec, "embedding", None)
        if not cid or emb is None:
            continue
        if isinstance(emb, float) and pd.isna(emb):
            continue
        try:
            values = [float(x) for x in list(emb)]
        except Exception:
            continue
        if not values:
            continue
        out[cid] = values
    return out


def load_release_vectors_by_cid(release_dir: Path) -> dict[str, list[float]]:
    frame = _read_sharded_parquet(Path(release_dir) / "data" / "vectors")
    if frame is None:
        return {}
    return embeddings_from_vector_table(frame)


def load_prior_release(release_dir: Path | None) -> PriorRelease | None:
    if release_dir is None:
        return None
    directory = Path(release_dir)
    if not directory.is_dir():
        return None
    manifest = load_release_manifest(directory)
    if not manifest and not (directory / "data").is_dir():
        return None
    return PriorRelease(
        directory=directory,
        manifest=manifest,
        corpus=load_release_corpus(directory),
        vectors_by_cid=None,
    )


def load_embedding_cache(path: Path) -> dict[str, list[float]]:
    if not path.is_file():
        return {}
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return {}
    return embeddings_from_vector_table(frame)


def save_embedding_cache(
    path: Path,
    by_cid: Mapping[str, Iterable[float]],
    *,
    model_name: str,
    dimension: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "entry_cid": cid,
            "embedding": list(vec),
            "model_name": model_name,
            "dimension": int(dimension),
        }
        for cid, vec in sorted(by_cid.items())
    ]
    frame = pd.DataFrame(rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def merge_embedding_maps(
    *maps: Mapping[str, list[float]] | None,
) -> dict[str, list[float]]:
    merged: dict[str, list[float]] = {}
    for mapping in maps:
        if not mapping:
            continue
        merged.update(mapping)
    return merged


def fetch_hub_prior(
    slug: str,
    dest: Path | None = None,
    *,
    cache_root: Path | None = None,
) -> Path | None:
    """Download JusticeDAO corpus+vector shards to use as an incremental parent.

    Missing Hub IR is not an error: first-time countries return ``None``.
    """
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import RepositoryNotFoundError

    from .auth import operator_token, public_token
    from .catalog import target_repo

    root = Path(cache_root) if cache_root is not None else (
        Path.home() / ".ipfs_datasets" / "country-laws-ir" / "cache" / "hub-ir"
    )
    dest = Path(dest) if dest is not None else (root / slug)
    dest.mkdir(parents=True, exist_ok=True)
    repo = target_repo(slug)
    try:
        snapshot_download(
            repo_id=repo,
            repo_type="dataset",
            local_dir=str(dest),
            allow_patterns=[
                "manifest.json",
                "data/vectors/**",
                "data/corpus/**",
                "indexes/vector_chunks.parquet",
            ],
            token=operator_token() or public_token(),
        )
    except RepositoryNotFoundError:
        return None
    except Exception:
        if not (dest / "manifest.json").is_file():
            return None
        raise
    if not (dest / "manifest.json").is_file():
        return None
    return dest

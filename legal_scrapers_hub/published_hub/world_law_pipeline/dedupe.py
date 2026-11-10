"""Cross-lane content dedupe for bulk HF imports (records with source="hf:<dataset>").

A record imported from an endomorphosis/ipfs_<cc>_laws dataset (an "import") is dropped when the SAME
document already exists as a primary (non-import) record of the same country, possibly under a
different place_key (so its CID differs).  "Same document" is deliberately strict - nothing that is
merely similar is dropped:
  * identical normalized source URL, or identical official identifier (ELI / CELEX), or
  * identical normalized-text sha256 (text >= MIN_TEXT chars) AND (same adopted_date or same normalized title).
The primary record (e.g. the EU bot's scraped source) is kept; dropped imports are written to the
dedupe log so nothing is lost silently.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

MIN_TEXT = 200
_WS = re.compile(r"\s+")


def is_import(rec: Dict[str, Any]) -> bool:
    s = rec.get("source")
    if s is None:
        em = rec.get("extra_metadata")
        if isinstance(em, str) and '"hf:' in em:
            try:
                s = json.loads(em).get("source")
            except ValueError:
                s = None
        elif isinstance(em, dict):
            s = em.get("source")
    return isinstance(s, str) and s.startswith("hf:")


def norm_text(t: Optional[str]) -> str:
    if not t:
        return ""
    t = unicodedata.normalize("NFKC", t)
    return _WS.sub(" ", t).strip().casefold()


def text_hash(t: Optional[str]) -> Optional[str]:
    n = norm_text(t)
    return hashlib.sha256(n.encode("utf-8")).hexdigest() if len(n) >= MIN_TEXT else None


def norm_url(u: Optional[str]) -> Optional[str]:
    if not u or not isinstance(u, str):
        return None
    u = u.strip()
    u = re.sub(r"^https?://(www\.)?", "", u, flags=re.I).rstrip("/")
    return u.lower() or None


def official_ids(rec: Dict[str, Any]) -> Iterable[str]:
    em = rec.get("extra_metadata")
    if isinstance(em, str):
        try:
            em = json.loads(em)
        except ValueError:
            em = {}
    d = dict(em or {}) if isinstance(em, dict) else {}
    d.update({k: v for k, v in rec.items() if v is not None})
    for k in ("eli", "celex"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            yield f"{k}:{v.strip().lower()}"


def keys_of(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {"url": norm_url(rec.get("source_url")), "ids": list(official_ids(rec)),
            "th": text_hash(rec.get("text")), "date": (rec.get("adopted_date") or None),
            "title": norm_text(rec.get("title_native")) or None}


class PrimaryIndex:
    """Keys of primary (non-import) records of one country -> 'place_key/doc_id' of the primary."""

    def __init__(self) -> None:
        self.url: Dict[str, str] = {}
        self.ids: Dict[str, str] = {}
        self.th: Dict[str, list] = {}

    def __len__(self) -> int:
        return len(self.url) + len(self.ids) + len(self.th)

    def add(self, rec: Dict[str, Any], place_key: str) -> None:
        if is_import(rec):
            return
        ref = f"{place_key}/{rec.get('doc_id')}"
        k = keys_of(rec)
        if k["url"]:
            self.url.setdefault(k["url"], ref)
        for i in k["ids"]:
            self.ids.setdefault(i, ref)
        if k["th"]:
            self.th.setdefault(k["th"], []).append((k["date"], k["title"], ref))

    def match(self, rec: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """(reason, primary ref) if rec is the same document as a primary record, else None."""
        k = keys_of(rec)
        if k["url"] and k["url"] in self.url:
            return "source_url", self.url[k["url"]]
        for i in k["ids"]:
            if i in self.ids:
                return "official_id", self.ids[i]
        if k["th"]:
            for date, title, ref in self.th.get(k["th"], []):
                if (date and date == k["date"]) or (title and title == k["title"]):
                    return "text_hash", ref
        return None

    def to_obj(self) -> Dict[str, Any]:
        return {"url": self.url, "ids": self.ids, "th": self.th}

    @classmethod
    def from_obj(cls, o: Dict[str, Any]) -> "PrimaryIndex":
        p = cls()
        p.url, p.ids = dict(o.get("url", {})), dict(o.get("ids", {}))
        p.th = {k: [tuple(x) for x in v] for k, v in o.get("th", {}).items()}
        return p


_COLS = ["doc_id", "source_url", "text", "adopted_date", "title_native", "extra_metadata"]


def build_index(cc: str, nat_out_root: Path, staged_files: Iterable[Tuple[str, Path]], iter_staged) -> PrimaryIndex:
    """Primary records of country cc: published national parquet + this run's staged non-import files."""
    import pyarrow.parquet as pq
    idx = PrimaryIndex()
    d = nat_out_root / "data" / cc
    if d.exists():
        for p in sorted(d.glob("*_html.parquet")):
            key = p.name[: -len("_html.parquet")]
            key = re.sub(r"\.s\d{4,}$", "", key)
            pf = pq.ParquetFile(str(p))
            cols = [c for c in _COLS if c in pf.schema_arrow.names]
            for b in pf.iter_batches(batch_size=256, columns=cols):
                for r in b.to_pylist():
                    idx.add(r, key)
    for key, path in staged_files:
        for _, rec in iter_staged(path):
            if isinstance(rec, dict):
                idx.add(rec, key)
    return idx

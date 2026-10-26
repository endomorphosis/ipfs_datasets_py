"""Duplicate indexes for NEW rows (added 2026-10-19, "dedup" change).

1. Old-repo source-URL index: normalized source URLs of every older endomorphosis/justicedao
   ipfs_*_laws / ipfs_*_municipal_laws dataset -> the repo that already has it.
   File: state/dedup/old_urls.sqlite, table u(url TEXT PRIMARY KEY, repo TEXT) WITHOUT ROWID
   (url = norm_url(); repo = first repo seen, alphabetical scan order).
2. Published world_municipal_law index: state/dedup/mun_published.sqlite,
   tables pu(url PRIMARY KEY, ref) and ph(th PRIMARY KEY, ref); ref = "<CC>/<place_key>/<doc_id>".

Nothing here touches published rows; callers only tag/strip NEW rows (doc_ids not yet published).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import os

STATE_DIR = Path(os.environ.get("WORLD_LAW_DEDUP_DIR") or (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/dedup"))
OLD_URLS_DB = STATE_DIR / "old_urls.sqlite"
MUN_PUB_DB = STATE_DIR / "mun_published.sqlite"

_TRACK = re.compile(r"^(utm_[a-z]+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|_ga|_gl|igshid|yclid|ref_src|"
                    r"spm|sessionid|jsessionid|phpsessid|sid|cfid|cftoken)$", re.I)
_WS = re.compile(r"\s+")
_WAYBACK = re.compile(r"^https?://(?:www\.)?(?:web\.)?archive\.org/web/\d{1,14}[a-z_]*/(.+)$", re.I)
MIN_TEXT = 200


def norm_url(u: Any) -> Optional[str]:
    """Canonical comparison key for a source URL.

    scheme dropped (http == https), host lower-cased, leading 'www.' and default port dropped,
    ';jsessionid=..' path params dropped, tracking query params (utm_*, fbclid, gclid, session ids...)
    dropped, remaining query params sorted, fragment dropped, trailing '/' dropped, percent-encoding
    normalized.  Path case is kept (paths are case-sensitive on many servers).  Non-http(s) values
    (and huggingface.co dataset placeholders) give None.
    """
    if not isinstance(u, str):
        return None
    u = u.strip()
    if not u:
        return None
    m = _WAYBACK.match(u)
    if m:  # archive copies compare as their original URL
        u = m.group(1)
        if not re.match(r"^https?://", u, re.I):
            u = re.sub(r"^(https?):/+", r"\1://", u, flags=re.I)
    if u.startswith("//"):
        u = "http:" + u
    if not re.match(r"^https?://", u, re.I):
        if re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I) or "." not in u.split("/")[0]:
            return None
        u = "http://" + u
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    if host == "huggingface.co" and p.path.startswith("/datasets/"):
        return None
    port = p.port if p.port not in (None, 80, 443) else None
    netloc = host + (f":{port}" if port else "")
    path = re.sub(r";jsessionid=[^/?#]*", "", p.path, flags=re.I)
    path = quote(unquote(path), safe="/:@!$&'()*+,;=-._~%")
    path = re.sub(r"/{2,}", "/", path).rstrip("/")
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACK.match(k)]
    query = urlencode(sorted(q), doseq=True)
    return netloc + path + (("?" + query) if query else "")


def norm_text(t: Optional[str]) -> str:
    if not t:
        return ""
    return _WS.sub(" ", unicodedata.normalize("NFKC", t)).strip().casefold()


def text_hash(t: Optional[str]) -> Optional[str]:
    n = norm_text(t)
    return hashlib.sha256(n.encode("utf-8")).hexdigest()[:32] if len(n) >= MIN_TEXT else None


def repo_slug(repo: str) -> str:
    """'endomorphosis/ipfs_dominican_republic_laws' -> 'dominicanrepublic' (alias-insensitive)."""
    n = repo.split("/")[-1]
    n = re.sub(r"^ipfs_", "", n)
    n = re.sub(r"(_municipal)?_laws(_ir)?$", "", n)
    return n.replace("_", "")


class SqliteIndex:
    def __init__(self, path: Path, table: str, key: str = "url", val: str = "repo") -> None:
        self.path, self.table, self.key, self.val = Path(path), table, key, val
        self._con: Optional[sqlite3.Connection] = None

    @property
    def con(self) -> sqlite3.Connection:
        if self._con is None:
            self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        return self._con

    def exists(self) -> bool:
        return self.path.exists()

    def get(self, k: Optional[str]) -> Optional[str]:
        if not k:
            return None
        r = self.con.execute(f"SELECT {self.val} FROM {self.table} WHERE {self.key}=?", (k,)).fetchone()
        return r[0] if r else None

    def __len__(self) -> int:
        return self.con.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0]

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None


def old_url_index(path: Path = OLD_URLS_DB) -> SqliteIndex:
    return SqliteIndex(path, "u", "url", "repo")


def lookup_old_url(url: str, path: Path = OLD_URLS_DB, exclude_repos: Iterable[str] = ()) -> Optional[str]:
    """Repo of an older ipfs_* dataset that already has this source URL, else None."""
    idx = old_url_index(path)
    try:
        r = idx.get(norm_url(url))
    finally:
        idx.close()
    if r and repo_slug(r) in {repo_slug(x) for x in exclude_repos}:
        return None
    return r


def create_db(path: Path, ddl: Iterable[str]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    for d in ddl:
        con.execute(d)
    return con


class PubIndex:
    """Published world_municipal_law keys: get("source_url"|"text_hash", value) -> "<CC>/<place_key>/<doc_id>"."""

    def __init__(self, path: Path = MUN_PUB_DB) -> None:
        self.path = Path(path)
        self.t = {"source_url": SqliteIndex(path, "pu", "url", "ref"), "text_hash": SqliteIndex(path, "ph", "th", "ref")}

    def exists(self) -> bool:
        return self.path.exists()

    def get(self, kind: str, val: Optional[str]) -> Optional[str]:
        return self.t[kind].get(val) if self.exists() else None

    def close(self) -> None:
        for x in self.t.values():
            x.close()

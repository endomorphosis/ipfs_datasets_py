"""Duplicate checks for NEW rows (2026-10-19 "dedup" change). See SCHEMA.md "Pointer rows".

Check A  old_repo   : normalized source URL already in an older ipfs_*_laws / ipfs_*_municipal_laws repo
                      (state/dedup/old_urls.sqlite).  Applies to world_municipal_law AND world_national_law.
                      An hf: import is never matched against its own source repo (alias-insensitive slug).
Check B  cross_place: world_municipal_law only.  Same normalized source URL, or same normalized-text sha
                      (>= 200 chars), in a DIFFERENT place, either already published
                      (state/dedup/mun_published.sqlite) or staged in the same run.  One canonical copy is
                      kept; the others become pointer rows to "<CC>/<place_key>/<doc_id>" of the canonical.
                      Canonical choice: published copy (never modified) > German Amt/Verbandsgemeinde/
                      Samtgemeinde/Verwaltungsgemeinschaft place > (PT diariodarepublica.pt) the place named
                      as issuer in the title > most specific admin level > smallest place_key.
                      If a NEW row outranks a published copy (e.g. new Amt row vs published member-
                      Gemeinde row) the new row is kept in full and the published one is only COUNTED as
                      a later-removal candidate (published rows are never rewritten here).

Pointer row (mode "pointer", default): the row is kept (same doc_id/cid/metadata/source_url) but
  text=None, content_complete=False, source_policy gets token "duplicate_pointer", and extra_metadata
  gets {"duplicate_of": "<repo>" | "<CC>/<place_key>/<doc_id>", "duplicate_check": "old_repo"|"cross_place",
        "duplicate_key": "source_url"|"text_hash"}.
Other modes (state/dedup/config.json): "tag" (keep text, add tags), "skip" (drop row, logged), "off".
Only rows whose doc_id is NOT already published in that place are touched.

NO-EMPTY RULE (2026-10-20, Benjamin): dedup never leaves a place with zero rows.  run_loop collects the hits of
a place, then counts the place's full rows that would remain (existing published rows + new rows, minus rows
that are already pointer rows, minus rows that "skip"/"pointer" would strip).  If that count is 0, NO hit is
applied for that place: all its rows are kept in full, unmodified (logged as mode "kept_place_would_be_emptied",
stats xdedup_places_kept_would_be_emptied / xdedup_rows_kept_would_be_emptied).  Applies to both old_repo and
cross_place, for every mode.  "tag" keeps text, so it never empties a place.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import dedup_index as DX

def _config_path() -> Path:
    return DX.STATE_DIR / "config.json"
DEFAULT_CFG = {"old_repo": "pointer", "cross_place": "pointer", "prepass_budget_s": 1200}
CANDIDATE_CSV = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
POINTER_POLICY = "duplicate_pointer"
_AMT = re.compile(r"^(amt|verbandsgemeinde|vg|samtgemeinde|verwaltungsgemeinschaft|vwg|gemeindeverwaltungsverband|"
                  r"verwaltungsverband)\b", re.I)
_LEVEL = {"parish": 1, "freguesia": 1, "uniao_de_freguesias": 1, "gram_panchayat": 1, "village": 1,
          "town": 2, "township": 2, "municipality": 3, "city": 3, "union": 3, "subcounty": 3,
          "district": 4, "county": 4, "province": 5, "region": 6, "state": 6}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CFG)
    try:
        cfg.update(json.loads(Path(path or _config_path()).read_text()))
    except (OSError, ValueError):
        pass
    return cfg


_PLACES: Dict[str, Tuple[str, str]] = {}


def place_info(place_id: str, rec: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """(place_name, admin_level) from the record, else the global_municipalities candidate CSV."""
    if rec and (rec.get("place_name") or rec.get("admin_level")):
        return str(rec.get("place_name") or ""), str(rec.get("admin_level") or "")
    if not _PLACES and CANDIDATE_CSV.exists():
        with CANDIDATE_CSV.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("country_code") in ("DE", "PT", "AT") and r.get("place_id"):
                    _PLACES[r["place_id"]] = (r.get("place_name") or "", r.get("admin_level") or "")
        _PLACES.setdefault("", ("", ""))
    return _PLACES.get(place_id, ("", ""))


def is_amt(name: str) -> bool:
    return bool(name and _AMT.search(name.strip()))


def rank(c: Dict[str, Any]) -> Tuple:
    """Lower sorts first = better canonical.  c: {cc, key, place_id, name, level, title, url, published}."""
    pub = 0 if c.get("published") else 1
    amt = 0 if (c.get("cc") == "DE" and is_amt(c.get("name", ""))) else 1
    issuer = 1
    if c.get("cc") == "PT" and "diariodarepublica.pt" in (c.get("url") or ""):
        nm = (c.get("name") or "").strip().casefold()
        nm = re.sub(r"^(município|municipio|câmara municipal|freguesia|união das freguesias)\s+(de|da|do|das|dos)\s+", "", nm)
        if nm and nm in (c.get("title") or "").casefold():
            issuer = 0
    lvl = _LEVEL.get((c.get("level") or "").lower(), 9)
    return (pub, amt, issuer, lvl, c.get("key") or "")


def candidate(cc, key, rec, published=False) -> Dict[str, Any]:
    name, level = place_info(rec.get("place_id") or "", rec)
    return {"cc": cc, "key": key, "doc_id": str(rec.get("doc_id")), "place_id": rec.get("place_id"),
            "name": name, "level": level, "title": rec.get("title_native") or rec.get("title") or "",
            "url": rec.get("source_url") or "", "published": published}


def rec_text(rec: Dict[str, Any]) -> Optional[str]:
    t = rec.get("text")
    if not t and rec.get("html"):
        try:
            from world.common import html_to_text
            t = html_to_text(rec["html"])
        except Exception:  # noqa: BLE001
            t = None
    return t


def _parse_ref(ref: str) -> Tuple[str, str, str]:
    cc, key, did = ref.split("/", 2)
    return cc, key, did


def plan_cross_place(staged: Iterable[Tuple[str, str, Path]], iter_staged, pub: Optional["DX.PubIndex"],
                     budget_s: float = 1e9, stats=None) -> Dict[Tuple[str, str], Dict[str, Dict[str, str]]]:
    """Return {(cc, key): {doc_id: {"duplicate_of", "duplicate_key"}}} for staged municipal rows that are
    cross-place duplicates.  staged: (cc, key, path) of municipal staged files of this run.
    Raises TimeoutError past budget_s (caller then disables the check for this run)."""
    t0 = time.time()
    by: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}   # (kind, value) -> candidates
    for cc, key, path in staged:
        for _, rec in iter_staged(path):
            if not isinstance(rec, dict) or rec.get("doc_id") in (None, ""):
                continue
            c = candidate(cc, key, rec)
            u = DX.norm_url(rec.get("source_url"))
            h = DX.text_hash(rec_text(rec))
            c["_u"], c["_h"] = u, h
            if u:
                by.setdefault(("source_url", u), []).append(c)
            if h:
                by.setdefault(("text_hash", h), []).append(c)
            if time.time() - t0 > budget_s:
                raise TimeoutError(f"cross-place prepass over budget ({budget_s:.0f}s)")
    out: Dict[Tuple[str, str], Dict[str, Dict[str, str]]] = {}
    decided: set = set()
    for (kind, val), cs in sorted(by.items(), key=lambda kv: kv[0][0] != "source_url"):
        cands = list(cs)
        ref = pub.get(kind, val) if pub is not None and pub.exists() else None
        if ref:
            pcc, pkey, pdid = _parse_ref(ref)
            cands.append({"cc": pcc, "key": pkey, "doc_id": pdid, "published": True, "url": cands[0]["url"],
                          "title": "", **dict(zip(("name", "level"), place_info(""))), "_ref": ref})
        if len({(c["cc"], c["key"]) for c in cands}) < 2:
            continue
        # published rows always win, but a new Amt row outranks a published member row: rank with
        # published as the 2nd criterion for DE Amt, i.e. compare without the published bit first
        best_new = min((c for c in cands if not c.get("published")), key=rank)
        canon = min(cands, key=rank)
        if canon.get("published") and best_new["cc"] == "DE" and is_amt(best_new["name"]) and not is_amt(
                place_info_name_of(canon)):
            if stats is not None:
                stats["xdedup_published_outranked"] += 1
            canon = best_new
        cref = canon.get("_ref") or f'{canon["cc"]}/{canon["key"]}/{canon["doc_id"]}'
        for c in cands:
            if c is canon or c.get("published") or (c["cc"], c["key"]) == (canon["cc"], canon["key"]):
                continue
            k = (c["cc"], c["key"], c["doc_id"])
            if k in decided:
                continue
            decided.add(k)
            out.setdefault((c["cc"], c["key"]), {})[c["doc_id"]] = {"duplicate_of": cref, "duplicate_key": kind}
    return out


def place_info_name_of(c: Dict[str, Any]) -> str:
    if c.get("name"):
        return c["name"]
    key = c.get("key") or ""
    m = re.match(r"wd_(Q\d+)$", key)
    return place_info(f"wd:{m.group(1)}")[0] if m else ""


class OldRepoCheck:
    """Per-process lazy wrapper over old_urls.sqlite (opened read-only on first use)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.idx = DX.old_url_index(path or DX.STATE_DIR / "old_urls.sqlite")

    def available(self) -> bool:
        return self.idx.exists()

    def match(self, rec: Dict[str, Any]) -> Optional[str]:
        if not self.available():
            return None
        repo = self.idx.get(DX.norm_url(rec.get("source_url")))
        if not repo:
            return None
        src = str(rec.get("source") or "")
        own = rec.get("hf_dataset") or (src[3:] if src.startswith("hf:") else None)
        if not own:
            em = rec.get("extra_metadata")
            if isinstance(em, str) and '"hf_dataset"' in em:
                try:
                    own = json.loads(em).get("hf_dataset")
                except ValueError:
                    own = None
        if own and DX.repo_slug(own) == DX.repo_slug(repo):
            return None
        return repo


STRIPPING_MODES = ("pointer", "skip")


def strips_content(mode: str) -> bool:
    """True if applying this mode removes the row's full content (pointer) or the row itself (skip)."""
    return mode in STRIPPING_MODES


def would_empty(full_rows_left: int, stripped: int) -> bool:
    """No-empty rule: applying `stripped` skip/pointer hits would leave the place with no full row."""
    return stripped > 0 and full_rows_left <= 0


def apply_pointer(row: Dict[str, Any], target: str, check: str, key: str, mode: str) -> Optional[Dict[str, Any]]:
    """Mutate a NORMALIZED row into a pointer/tagged row; returns None for mode 'skip'."""
    if mode == "skip":
        return None
    em = row.get("extra_metadata")
    try:
        d = json.loads(em) if isinstance(em, str) and em.strip() else (dict(em) if isinstance(em, dict) else {})
    except ValueError:
        d = {"_raw_extra_metadata": em}
    d.update({"duplicate_of": target, "duplicate_check": check, "duplicate_key": key})
    row["extra_metadata"] = json.dumps(d, ensure_ascii=False, sort_keys=True)
    pol = [p for p in (row.get("source_policy") or "").split(";") if p]
    if POINTER_POLICY not in pol:
        pol.append(POINTER_POLICY)
    row["source_policy"] = ";".join(pol)
    if mode == "pointer":
        row["text"] = None
        row["content_complete"] = False
    return row


def add_published_keys(db: Path, keys) -> int:
    """Insert (norm_url, text_hash, ref) of rows that were just published (first ref wins). Missing db -> 0."""
    keys = list(keys)
    if not keys or not Path(db).exists():
        return 0
    import sqlite3
    con = sqlite3.connect(str(db), timeout=60)
    try:
        con.executemany("INSERT OR IGNORE INTO pu VALUES(?,?)", [(u, r) for u, _, r in keys if u])
        con.executemany("INSERT OR IGNORE INTO ph VALUES(?,?)", [(h, r) for _, h, r in keys if h])
        con.commit()
    finally:
        con.close()
    return len(keys)

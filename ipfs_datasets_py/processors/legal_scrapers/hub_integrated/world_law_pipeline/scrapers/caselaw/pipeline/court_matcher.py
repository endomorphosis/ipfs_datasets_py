"""Court matcher against the deduped court dimension of ipfs_court_data @ ef54093beb (read-only).
entity_key is NOT a primary key and is source-specific: courts are grouped by (country_iso, admin1, normalised name);
canonical key = min(entity_key) of the group; all keys kept as candidates. Never writes a fuzzy winner < 0.92 as matched."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import glob, re, unicodedata, hashlib, difflib
from urllib.parse import urlparse
import pyarrow.parquet as pq
from caselaw_schema import provisional_key, COURTS_DATASET_REVISION

COURTS_GLOB = (str(_LEGAL_WS) + "/courts/hub_floor/ipfs_court_data/data/phase*/court/part-0000.parquet")
ABBR = {"ct": "court", "sup": "supreme", "dist": "district", "app": "appeal", "cir": "circuit"}

def norm_name(s: str | None) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(ABBR.get(w, w) for w in s.split())

def host_of(u: str | None) -> str | None:
    if not u: return None
    try:
        h = urlparse(u if "//" in u else "//" + u).hostname
    except ValueError:
        return None
    return h[4:] if h and h.startswith("www.") else h

def _tokset(a, b):
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb: return 0.0
    inter = ta & tb
    return max(len(inter) / len(ta | tb), difflib.SequenceMatcher(None, a, b).ratio() if len(inter) else 0.0)

class CourtMatcher:
    def __init__(self, rows: list[dict] | None = None):
        """rows=None -> read the pinned courts dataset; rows=[{entity_key,country_iso,admin1,name,website}] -> test fixture."""
        if rows is None:
            rows = []
            for f in sorted(glob.glob(COURTS_GLOB)):
                rows += pq.read_table(f, columns=["entity_key", "country_iso", "admin1", "name", "website"]).to_pylist()
        self.n_rows = len(rows)
        self.groups: dict[tuple, dict] = {}
        for r in rows:
            nn = norm_name(r["name"])
            if not nn: continue
            g = self.groups.setdefault((r["country_iso"], r["admin1"], nn), {"keys": set(), "hosts": set(), "name": r["name"]})
            g["keys"].add(r["entity_key"])
            h = host_of(r["website"])
            if h: g["hosts"].add(h)
        self.by_host: dict[tuple, set] = {}
        for k, g in self.groups.items():
            for h in g["hosts"]: self.by_host.setdefault((k[0], h), set()).add(k)
        self.n_courts = len(self.groups)
        self.stats = {"matched": 0, "ambiguous": 0, "unmatched": 0}
        self.unmatched: dict[tuple, int] = {}

    def match(self, country_iso: str, court_name: str | None, admin1: str | None = None, website: str | None = None,
              source_name: str | None = None, discriminator: str | None = None) -> dict:
        nn = norm_name(court_name)
        res = None
        g = self.groups.get((country_iso, admin1, nn)) if nn else None
        if g: res = ("exact", 1.0, [(country_iso, admin1, nn)])
        if res is None and website:
            ks = self.by_host.get((country_iso, host_of(website)), set())
            if len(ks) == 1: res = ("website", 1.0, list(ks))
            elif len(ks) > 1: res = ("website_multi", 0.0, list(ks))
        if res is None and nn:
            cands = [(k, _tokset(nn, k[2])) for k in self.groups if k[0] == country_iso and k[1] == admin1]
            cands = sorted([c for c in cands if c[1] >= 0.92], key=lambda x: -x[1])
            if len(cands) == 1 or (cands and cands[0][1] > cands[1][1]): res = ("fuzzy", cands[0][1], [cands[0][0]])
            elif cands: res = ("fuzzy_tie", cands[0][1], [c[0] for c in cands[:3]])
        out = {"court_entity_key": None, "court_key_provisional": None, "court_match_status": "unmatched", "meta": {}}
        if res and res[0] in ("exact", "website", "fuzzy") and len(res[2]) == 1:
            grp = self.groups[res[2][0]]
            out.update(court_entity_key=min(grp["keys"]), court_match_status="matched")
            out["meta"] = {"court_match_method": res[0], "court_match_score": res[1],
                           "court_entity_key_candidates": sorted(grp["keys"]), "courts_dataset_revision": COURTS_DATASET_REVISION}
        elif res:
            out["court_match_status"] = "ambiguous"
            out["meta"] = {"court_match_method": res[0], "court_match_candidates": [list(map(str, k)) for k in res[2][:3]],
                           "courts_dataset_revision": COURTS_DATASET_REVISION}
        if out["court_match_status"] != "matched":
            out["court_key_provisional"] = provisional_key(country_iso, admin1, nn, source_name, discriminator)
            key = (country_iso, admin1, court_name or "")
            self.unmatched[key] = self.unmatched.get(key, 0) + 1
        self.stats[out["court_match_status"]] += 1
        return out

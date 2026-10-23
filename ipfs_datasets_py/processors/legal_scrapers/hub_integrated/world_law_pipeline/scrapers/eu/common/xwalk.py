"""Low-memory reader of the shared place-code crosswalk /workspace/world_law/pipeline/codes/place_codes.csv.

Only the requested country's code systems are loaded (lazily); codes that map to >1 place_id are dropped.
Prefer place_codes.parquet when present (same columns) for faster country filters.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv
import re
from pathlib import Path
from typing import Optional

PATH = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_codes.csv"))
PARQUET = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_codes.parquet"))
SYSTEMS = {
    "PL": ("pl_teryt_terc", "pl_nts"),
    "NL": ("nl_cbs_gemeente",),
    "AT": ("at_gkz",),
    "ES": ("es_ine",),
}


def _norm(cc: str, code: str) -> str:
    d = re.sub(r"\D", "", code or "")
    if cc == "PL" and len(d) == 10:            # NTS-style R WW SS PP GG T -> TERYT WWPPGGT
        return d[1:3] + d[5:7] + d[7:9] + d[9]
    if cc == "NL":
        return d.zfill(4)
    if cc == "ES":
        return d.zfill(5) if d else ""
    return d


class Crosswalk:
    def __init__(self, path: Path = PATH):
        self.path = path
        self.m: dict = {}

    def _load_parquet(self, cc: str, systems: tuple) -> Optional[dict]:
        if not PARQUET.exists():
            return None
        try:
            import pyarrow.parquet as pq
            import pyarrow.compute as pc
            t = pq.read_table(
                PARQUET,
                columns=["place_id", "country_code", "code_system", "code", "is_current"],
                filters=[
                    ("country_code", "=", cc),
                ],
            )
            d: dict = {}
            cc_col = t.column("country_code")
            sys_col = t.column("code_system")
            code_col = t.column("code")
            pid_col = t.column("place_id")
            cur_col = t.column("is_current")
            systems_set = set(systems)
            for i in range(t.num_rows):
                if sys_col[i].as_py() not in systems_set:
                    continue
                cur = cur_col[i].as_py()
                if cur is False or cur == "False":
                    continue
                k = _norm(cc, code_col[i].as_py() or "")
                if not k:
                    continue
                d.setdefault(k, set()).add(pid_col[i].as_py())
            return {k: next(iter(v)) for k, v in d.items() if len(v) == 1}
        except Exception:
            return None

    def _load(self, cc: str) -> dict:
        systems = SYSTEMS.get(cc, ())
        if not systems:
            return {}
        loaded = self._load_parquet(cc, systems)
        if loaded is not None:
            return loaded
        d: dict = {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r["country_code"] != cc or r["code_system"] not in systems:
                        continue
                    if r.get("is_current") == "False":
                        continue
                    k = _norm(cc, r["code"])
                    if not k:
                        continue
                    d.setdefault(k, set()).add(r["place_id"])
        return {k: next(iter(v)) for k, v in d.items() if len(v) == 1}

    def get(self, cc: str, code: str) -> Optional[str]:
        if cc not in self.m:
            self.m[cc] = self._load(cc)
        return self.m[cc].get(_norm(cc, code))


XWALK = Crosswalk()


# --------------------------------------------------------------------------- place_additions.csv
# Places the uploader added outside the candidate CSV (PL land powiats = county, NL water boards, Frisian municipalities).
ADDITIONS_PATH = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_additions.csv"))


class Additions:
    """place_id -> row, plus (country, code_system, code) -> place_id for the official code carried in the file."""

    def __init__(self, path: Path = ADDITIONS_PATH):
        self.path = path
        self._rows: Optional[dict] = None
        self._codes: Optional[dict] = None

    def _load(self):
        self._rows, self._codes = {}, {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self._rows[r["place_id"]] = r
                    if r.get("official_code"):
                        self._codes[(r["country_code"], r["official_code_system"], r["official_code"].lower())] = r["place_id"]

    def row(self, place_id: str) -> Optional[dict]:
        if self._rows is None:
            self._load()
        return self._rows.get(place_id)

    def by_code(self, cc: str, system: str, code: str) -> Optional[str]:
        if self._codes is None:
            self._load()
        return self._codes.get((cc, system, (code or "").lower()))

    def rows(self, cc: Optional[str] = None):
        if self._rows is None:
            self._load()
        return [r for r in self._rows.values() if cc is None or r["country_code"] == cc]


ADDITIONS = Additions()


# --------------------------------------------------------------------------- place_successors.csv + denylist
# Dissolved/merged municipalities -> current successor (EE 2017 reform via EHAK, BE mergers via NIS/REFNIS).
# Split municipalities (n_successors > 1) are ambiguous and are NOT resolved.
SUCCESSORS_PATH = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_successors.csv"))

# candidate places that must never be mapped to (non-current / not a municipality); qid -> reason
DENY = {"Q603919": "Piringen (deelgemeente of Tongeren)", "Q28041377": "Amelscheid (part of Sankt Vith)",
        "Q1976577": "Sint-Lambrechts-Herk (merged into Hasselt 1977)", "Q61392784": "Mündi (non-current)",
        "Q125705383": "École Vervloesem (a school, not a place)"}


def denied(place_id_or_qid: Optional[str]) -> bool:
    q = (place_id_or_qid or "").split(":")[-1]
    return q in DENY


def _sfold(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFC", s or "").lower()
    return " ".join(s.replace("’", "'").split())


class Successors:
    """lookup(cc, name=None, code=None) -> {"status": "ok"|"ambiguous"|None, "place_id", "successor_name",
    "old_name", "old_code", "dissolved_date", "candidates"}. Names match each ' / '-separated variant of old_name,
    with and without a trailing ' (…)' qualifier."""

    def __init__(self, path: Path = SUCCESSORS_PATH):
        self.path = path
        self._by_code = None
        self._by_name = None
        self._by_qid = None

    def _load(self):
        from collections import defaultdict
        bc, bn, bq = defaultdict(list), defaultdict(list), defaultdict(list)
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    cc = r["country_code"]
                    if r.get("old_code"):
                        bc[(cc, r["old_code"].lstrip("0"))].append(r)
                    if r.get("old_place_qid"):
                        bq[r["old_place_qid"]].append(r)
                    for v in (r.get("old_name") or "").split(" / "):
                        v = _sfold(v)
                        if v:
                            for k in {v, re.sub(r"\s*\(.*\)$", "", v)}:
                                bn[(cc, k)].append(r)
        self._by_code, self._by_name, self._by_qid = bc, bn, bq

    @staticmethod
    def _pack(rows):
        if not rows:
            return {"status": None}
        succ = sorted({r["successor_place_id"] for r in rows})
        olds = sorted({r.get("old_code") or r.get("old_name") for r in rows})
        r = rows[0]
        base = {"old_name": r["old_name"], "old_code": r.get("old_code") or None, "dissolved_date": r.get("dissolved_date") or None,
                "candidates": succ}
        if len(olds) > 1 or len(succ) > 1 or any((x.get("n_successors") or "1") != "1" for x in rows):
            return dict(base, status="ambiguous", place_id=None, successor_name=None)
        return dict(base, status="ok", place_id=succ[0], successor_name=r.get("successor_name"),
                    successor_code=r.get("successor_code") or None, source=r.get("source"))

    def lookup(self, cc: str, name: Optional[str] = None, code: Optional[str] = None, qid: Optional[str] = None) -> dict:
        if self._by_code is None:
            self._load()
        if code:
            rows = self._by_code.get((cc, str(code).lstrip("0")))
            if rows:
                return self._pack(rows)
        if qid:
            rows = [r for r in self._by_qid.get(qid.split(":")[-1], []) if r["country_code"] == cc]
            if rows:
                return self._pack(rows)
        if name:
            v = _sfold(name)
            rows = self._by_name.get((cc, v)) or self._by_name.get((cc, re.sub(r"\s*\(.*\)$", "", v)))
            if rows:
                return self._pack(rows)
        return {"status": None}


SUCCESSORS = Successors()

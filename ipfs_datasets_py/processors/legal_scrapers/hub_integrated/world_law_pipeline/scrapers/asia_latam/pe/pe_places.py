"""Peru municipality resolver: gob.pe institution name (+slug) -> place_id (Wikidata district QIDs from the candidate list).
Wikidata has no usable district UBIGEO (P844 covers only 25 departments + a handful of items; P1196 is 'manner of death'),
so matching is name + province/department hierarchy (Wikidata P131) + official website (P856) host vs gob.pe slug."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, re, unicodedata, collections
from pathlib import Path
from urllib.parse import urlparse
HERE = Path(__file__).resolve().parent


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"^(distrito|provincia|departamento|region)\s+(de|del)\s+", "", s.strip())
    s = re.sub(r"^(distrito|provincia|departamento)\s+", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


class PEResolver:
    def __init__(self):
        cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"] == "PE"}
        self.cand = cand
        self.info = collections.defaultdict(lambda: {"names": set(), "prov": set(), "dept": set(), "hosts": set()})
        for r in csv.DictReader(open(HERE / "wd_pe_hier.csv")):
            q = r["item"].rsplit("/", 1)[1]
            if q not in cand or cand[q]["admin_level"] != "municipality":
                continue
            i = self.info[q]
            for n in (r["itemLabel"], r.get("alias"), cand[q]["place_name"]):
                if n:
                    i["names"].add(norm(n))
            if r.get("p1Label"):
                i["prov"].add(norm(r["p1Label"]))
            if r.get("p2Label"):
                i["dept"].add(norm(r["p2Label"]))
            for u in (r.get("site"), cand[q].get("source_url")):
                if u:
                    i["hosts"].add((urlparse(u).hostname or "").lower())
        self.capital = {}                      # norm(province label) -> norm(capital label)  (Wikidata P36)
        cp = HERE / "wd_pe_prov_capital.csv"
        if cp.exists():
            for r in csv.DictReader(open(cp)):
                self.capital[norm(r["provLabel"])] = norm(r["capLabel"])
        # Official INEI UBIGEO list (via shared crosswalk pipeline/codes): ubigeo -> place_id, district/province/dept names
        import sys
        sys.path.insert(0, str(HERE.parent / "common"))
        from place_codes import code_to_place, CACHE
        self.ubi2pid = code_to_place("pe_ubigeo", "PE")
        self.ubi = []
        for r in csv.DictReader(open(CACHE / "pe_ubigeo_geodir.csv", encoding="utf-8-sig")):
            self.ubi.append((r["Ubigeo"].zfill(6), norm(r["Distrito"]), norm(r["Provincia"]), norm(r["Departamento"])))
        self.by_name = collections.defaultdict(set)
        for q, i in self.info.items():
            for n in i["names"]:
                self.by_name[n].add(q)

    def _place(self, q, match, extra=None):
        c = self.cand[q]
        d = {"place_id": c["place_id"], "qid": q, "place_name": c["place_name"], "admin_level": "municipality", "match": match,
             "province_name": sorted(self.info[q]["prov"])[0] if self.info[q]["prov"] else None,
             "department_name": sorted(self.info[q]["dept"])[0] if self.info[q]["dept"] else None}
        d.update(extra or {})
        return d

    def _by_host(self, qs, slug):
        s = (slug or "").lower()
        if not s:
            return set()
        return {q for q in qs if any(h.split(".")[0] == s or (h.startswith("www.") and h.split(".")[1] == s) for h in self.info[q]["hosts"])}

    def _ubigeo_place(self, code, match, kind):
        pid = self.ubi2pid.get(code)
        if not pid:
            return None
        q = pid.split(":", 1)[1]
        if q in self.cand:
            return self._place(q, match, {"municipality_kind": kind, "ubigeo": code})
        u = next(x for x in self.ubi if x[0] == code)
        return {"place_id": pid, "qid": q, "place_name": u[1].title(), "admin_level": "municipality", "match": match,
                "province_name": u[2], "department_name": u[3], "municipality_kind": kind, "ubigeo": code}

    def resolve_ubigeo(self, kind, name, hints):
        """Fallback on the official UBIGEO list. Provincial/metropolitan municipality -> capital district DDPP01."""
        hs = set(hints)
        if kind in ("provincial", "metropolitana"):
            provs = {(u[0][:4], u[2], u[3]) for u in self.ubi if name == u[2] or name.startswith(u[2] + " ")}
            if hs:
                provs = {p for p in provs if p[1] in hs or p[2] in hs} or provs
            if len(provs) == 1:
                return self._ubigeo_place(next(iter(provs))[0] + "01", "provincial_municipality_to_capital_district_ubigeo", kind)
            return None
        ds = [u for u in self.ubi if u[1] == name]
        if not ds and not hs:  # "castilla piura": district name + its province/department name (hyphen lost by norm)
            ds = [u for u in self.ubi if name.startswith(u[1] + " ") and name[len(u[1]) + 1:] in (u[2], u[3])]
        if hs:
            ds = [u for u in ds if u[2] in hs or u[3] in hs] or ([] if len(ds) > 1 else ds)
        if len(ds) == 1:
            return self._ubigeo_place(ds[0][0], "district_name_ubigeo" + ("_hint" if hs else ""), kind or "distrital")
        return None

    def resolve(self, inst_name, slug=None):
        r = self._resolve(inst_name, slug)
        if r.get("place_id") or r.get("match") in ("not_municipal", "centro_poblado_not_in_list"):
            return r
        n = norm(inst_name)
        m = re.match(r"^(?:la\s+)?municipalidad\s+(distrital|provincial|metropolitana)?\s*(?:de\s+|del\s+)?(.*)$", n)
        if m:
            parts = [p.strip() for p in re.split(r"\s+-\s+|\s*,\s*", re.sub(r"\s+(?:provincia|departamento|region)\s+(?:de\s+)?", " - ", m.group(2).strip())) if p.strip()]
            u = self.resolve_ubigeo(m.group(1) or "", parts[0], parts[1:]) if parts else None
            if u:
                return u
        return r

    def _resolve(self, inst_name, slug=None):
        n = norm(inst_name)
        m = re.match(r"^(?:la\s+)?municipalidad\s+(distrital|provincial|metropolitana|de centro poblado|del centro poblado|centro poblado)?\s*(?:de\s+|del\s+)?(.*)$", n)
        if not m:
            return {"match": "not_municipal"}
        kind, rest = m.group(1) or "", m.group(2).strip()
        if "centro poblado" in kind:
            return {"match": "centro_poblado_not_in_list", "kind": "centro_poblado"}
        parts = [p.strip() for p in re.split(r"\s+-\s+|\s*,\s*", re.sub(r"\s+(?:provincia|departamento|region)\s+(?:de\s+)?", " - ", rest)) if p.strip()]
        name, hints = parts[0], parts[1:]
        qs = set(self.by_name.get(name, set()))
        if kind in ("provincial", "metropolitana"):
            cap = {q for q in qs if name in self.info[q]["prov"]}
            if len(cap) == 1:
                return self._place(next(iter(cap)), "provincial_municipality_to_capital_district", {"municipality_kind": kind})
            capn = next((self.capital[k] for k in (norm("provincia de " + name), name) if k in self.capital), None)
            if capn:
                cap2 = {q for q in self.by_name.get(capn, set()) if any(name in pv for pv in self.info[q]["prov"])}
                if len(cap2) == 1:
                    return self._place(next(iter(cap2)), "provincial_municipality_to_capital_district_p36", {"municipality_kind": kind})
            hq = self._by_host(qs or set(self.info), slug)
            if len(hq) == 1:
                return self._place(next(iter(hq)), "provincial_municipality_by_official_site", {"municipality_kind": kind})
            return {"match": "ambiguous" if cap or qs else "unmatched", "municipality_kind": kind, "name_norm": name}
        if hints and len(qs) > 1:
            f = {q for q in qs if any(h in self.info[q]["prov"] or h in self.info[q]["dept"] for h in hints)}
            if f:
                qs = f
        if len(qs) > 1:
            hq = self._by_host(qs, slug)
            if len(hq) == 1:
                return self._place(next(iter(hq)), "name_plus_official_site", {"municipality_kind": kind or "distrital"})
        if len(qs) == 1:
            return self._place(next(iter(qs)), "name" + ("_hint" if hints else ""), {"municipality_kind": kind or "distrital"})
        if not qs:
            hq = self._by_host(set(self.info), slug)
            if len(hq) == 1:
                return self._place(next(iter(hq)), "official_site_only", {"municipality_kind": kind or "distrital"})
        return {"match": "ambiguous" if qs else "unmatched", "municipality_kind": kind or "distrital", "name_norm": name,
                "candidates": sorted(qs)[:5]}

"""Spanish municipality resolver: INE code (Wikidata P772) <-> place_id, plus name+province lookup."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, re, unicodedata, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    m = re.match(r"^(.*?),\s*(el|la|los|las|l'|lo|els|les|o|a|os|as|es|sa|ses)$", s.strip())
    if m:
        s = f"{m.group(2)} {m.group(1)}"
    s = s.replace("l'", "l ").replace("'", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


class Resolver:
    def __init__(self):
        cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"] == "ES"}
        self.cand = cand
        self.ine2q = collections.defaultdict(set)
        self.by_name = collections.defaultdict(set)  # (prov, normname) -> ine
        for fn in ("wd_p772.csv", "wd_p772_labels.csv"):
            p = HERE / fn
            if not p.exists():
                continue
            for r in csv.DictReader(open(p)):
                ine = r["ine"].strip()
                if not re.fullmatch(r"\d{5}", ine):
                    continue
                q = r["item"].rsplit("/", 1)[1]
                self.ine2q[ine].add(q)
                lab = r.get("label") or ""
                for part in re.split(r"\s*/\s*|\s+-\s+", lab) + [lab]:
                    if part:
                        self.by_name[(ine[:2], norm(part))].add(ine)

        # Official INE diccionario 2025 names (incl. bilingual "A/B" forms) + shared crosswalk es_ine -> place_id
        import sys, openpyxl
        sys.path.insert(0, str(HERE.parent / "common"))
        from place_codes import code_to_place, CACHE
        self.ine2pid = code_to_place("es_ine", "ES")
        self.pid2q = {c["place_id"]: q for q, c in cand.items()}
        wb = openpyxl.load_workbook(CACHE / "ine_es_diccionario25.xlsx", read_only=True)
        for r in wb.active.iter_rows(min_row=3, values_only=True):
            if not r or not r[1] or not r[2] or not r[4]:
                continue
            ine = f"{str(r[1]).zfill(2)}{str(r[2]).zfill(3)}"
            for part in re.split(r"\s*/\s*|\s+-\s+", str(r[4])) + [str(r[4])]:
                if part:
                    self.by_name[(ine[:2], norm(part))].add(ine)
        wb.close()

    def place_for_ine(self, ine):
        q = self.pid2q.get(self.ine2pid.get(ine, ""))
        for q in ([q] if q else []) + sorted(self.ine2q.get(ine, [])):
            if q in self.cand:
                c = self.cand[q]
                return {"place_id": c["place_id"], "qid": q, "ine": ine, "place_name": c["place_name"], "admin_level": c["admin_level"] or "municipality"}
        return None

    PREFIX_RE = re.compile(r"^(?:(?:excmo|excma|excelentisimo|excelentisima|ilmo|ilma|ilustrisimo|ilustrisima|m i|muy ilustre)\s+)*"
                           r"(?:ajuntament|ayuntamiento|ayto|concello|udala|concejo|ajuntamentu)\s+(de\s+|d\s+|del\s+|dels\s+|da\s+|do\s+)?")

    def _variants(self, name):
        # "Ayuntamiento de Lucena. Intervención de Fondos" -> issuer is the ayuntamiento; drop the department suffix
        m0 = re.match(r"^((?:excmo\.?\s*|ilmo\.?\s*)?(?:ayuntamiento|ajuntament|concello)\s+.+?)\.\s+\S", name or "", re.I)
        if m0:
            name = m0.group(1)
        n = norm(name)
        out = [n]
        m = self.PREFIX_RE.match(n)
        if m:
            rest = n[m.end():]
            art = (m.group(1) or "").strip()
            out += [rest] + ({"del": ["el " + rest], "dels": ["els " + rest], "da": ["a " + rest], "do": ["o " + rest]}.get(art, []))
        for v in list(out):
            v2 = re.sub(r"\s*(ko\s+)?udala$", "", v)          # Basque "Xko Udala"
            v2 = re.sub(r"ko$", "", v2) if v2 != v else v2
            if v2 != v:
                out.append(v2.strip())
        return [v for v in dict.fromkeys(out) if v]

    def resolve(self, name, prov):
        ines = set()
        for n in self._variants(name):
            ines = self.by_name.get((prov, n)) or set()
            if ines:
                break
        if len(ines) == 1:
            ine = next(iter(ines))
            p = self.place_for_ine(ine)
            if p:
                return dict(p, match="name_province")
            return {"ine": ine, "match": "ine_not_in_candidate"}
        if ines:
            return {"match": "ambiguous"}
        return self._resolve_loose(name, prov)

    # ---- round-10 fallback (only reached when the exact name+province lookup fails) ----
    NONMUNI_RE = re.compile(r"mancomun|mankomun|diputaci|deputaci|aldundi|entidad local|e\.\s*l\.\s*[am]\b|\bela\b|eatim|\belm\b|"
                            r"junta vecinal|junta administrativa|concejo abierto|pedan|consorci|partzuergo|comunidad de regantes|"
                            r"patronato|organismo|instituto|gerencia|fundaci|agrupaci|consell comarcal|comarca|cuadrilla|kuadrilla|"
                            r"parzoner|sociedad|empresa|tesorer|zerbitzu|servicios? sociales|area metropolitana|cabildo", re.I)
    TYPO_PREFIX_RE = re.compile(r"^(?:m\s*i|mi|muy ilustre|excmo|excma|ilmo|ilma)?\s*(a[a-z]{6,12}|ayto|aytm?o)\s+(?:de\s+|del\s+|d\s+)?(.+)$")

    @staticmethod
    def _lev(a, b):
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    def _lookup(self, cands, prov):
        hits = set()
        for c in dict.fromkeys(cands):
            got = self.by_name.get((prov, c))
            if got:
                hits |= got
                if len(hits) == 1:
                    return hits
        return hits

    def _resolve_loose(self, name, prov):
        if not name or self.NONMUNI_RE.search(name):
            return {"match": "unmatched"}
        raw = name.strip()
        raw = re.sub(r"^(.*?)\s*\((el|la|los|las|l'|o|a|os|as|es|sa|ses)\)\s*$", r"\2 \1", raw, flags=re.I)  # 'Toba (La)'
        n = norm(raw)
        n = re.sub(r"\bsta\s+m(a)?\b", "santa maria", n); n = re.sub(r"\bsta\b", "santa", n); n = re.sub(r"\bsto\b", "santo", n)
        had_prefix, body = False, n
        m = self.TYPO_PREFIX_RE.match(n)
        if m and (m.group(1) in ("ayto", "aytmo", "ayto") or self._lev(m.group(1), "ayuntamiento") <= 3):
            had_prefix, body = True, m.group(2)
        m2 = self.PREFIX_RE.match(n)
        if m2:
            had_prefix, body = True, n[m2.end():]
        if not body:
            return {"match": "unmatched"}
        arts = r"^(el|la|los|las|l|lo|els|les|o|a|os|as|es|sa|ses)\s+"
        cands = [body, re.sub(arts, "", body)] + [a + " " + body for a in ("la", "el", "a", "o", "los", "las")]
        parts = [x.strip() for x in re.split(r"\s*[-/]\s*|\s+-\s+", raw) if x.strip()]
        cands += [norm(" ".join(body.split()))]
        hits = self._lookup(cands, prov)
        how = "name_province_loose"
        if not hits and len(parts) > 1:
            hits = self._lookup([self._variants(pp)[-1] for pp in parts] + [norm(pp) for pp in parts], prov)
            how = "name_province_part"
        if not hits and had_prefix and len(body) >= 5:            # fuzzy only for explicit ayuntamiento issuers
            import difflib
            names = [nm for (pv, nm) in self.by_name if pv == prov]
            sc = sorted(((difflib.SequenceMatcher(None, body, nm).ratio(), nm) for nm in names), reverse=True)[:2]
            if sc and sc[0][0] >= 0.88 and (len(sc) < 2 or sc[0][0] - sc[1][0] >= 0.04):
                hits = self.by_name[(prov, sc[0][1])]
                how = f"name_province_fuzzy:{sc[0][0]:.2f}"
        if len(hits) == 1:
            ine = next(iter(hits))
            p = self.place_for_ine(ine)
            if p:
                return dict(p, match=how)
            return {"ine": ine, "match": "ine_not_in_candidate"}
        return {"match": "ambiguous" if hits else "unmatched"}

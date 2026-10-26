"""Indonesia kabupaten/kota -> place_id (wd:Q...) via the Kemendagri region code (Wikidata P2588,
'administrative code of Indonesia', verified 2026-10-10: Kab. Bogor Q10363=32.01, Kota Bandung Q10389=32.73).

Chain: BPK page 'T.E.U.' / 'Lokasi' / title / URL slug -> (kind kab|kota, name) -> P2588 code (Wikidata labels +
aliases; city codes are NN.7x, regency codes NN.0x-NN.6x) -> qid -> row in global_municipalities_candidate.csv.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, re, unicodedata
from collections import defaultdict
from pathlib import Path

ID_DIR = Path(__file__).resolve().parent.parent / "id"
CAND = (_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv")

ALIASES_EXTRA = {  # spelling variants seen in BPK slugs/titles -> canonical normalized name
    "gunungsitoli": "gunungsitoli", "tanjungbalai": "tanjungbalai", "pangkajenekepulauan": "pangkajenedankepulauan",
    "pangkep": "pangkajenedankepulauan", "tojounauna": "tojounauna", "fakfak": "fakfak", "tolitoli": "tolitoli",
    "kepulauansangiheTalaud": "", "labuhanbatu": "labuhanbatu", "labuhanbatuselatan": "labuhanbatuselatan",
    "labuhanbatuutara": "labuhanbatuutara", "baubau": "baubau", "pagaralam": "pagaralam", "lubuklinggau": "lubuklinggau",
    "toba": "tobasamosir", "tobasamosir": "tobasamosir", "sijunjung": "sawahluntosijunjung", "polewalimandar": "polewalimandar",
    "kotabaru": "kotabaru", "kotawaringinbarat": "kotawaringinbarat", "kotawaringintimur": "kotawaringintimur",
    "kotamobagu": "kotamobagu", "kuantansengingi": "kuantansingingi", "pasuruan": "pasuruan", "probolinggo": "probolinggo",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(kabupaten|kab|kota|regency|city|of|administrasi|adm)\b\.?", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def kind_of(code):
    return "kota" if code.split(".")[1].startswith("7") else "kab"


class IdPlaces:
    def __init__(self):
        self.cand = {}
        for r in csv.DictReader(open(CAND, encoding="utf-8")):
            if r["country_code"] == "ID" and r["admin_level"] == "municipality":
                self.cand[r["qid"]] = r
        self.code_qid = defaultdict(set)
        self.lut = defaultdict(set)  # (kind, normname) -> codes
        self.code_label = {}
        rows = list(csv.DictReader(open(ID_DIR / "wd_P2588.csv", encoding="utf-8")))
        rows += [dict(item=r["item"], code=r["code"], label_id=r["alias"], label_en="")
                 for r in csv.DictReader(open(ID_DIR / "wd_P2588_alias.csv", encoding="utf-8"))]
        for r in rows:
            code = r["code"]
            if not re.fullmatch(r"\d\d\.\d\d", code):
                continue
            q = r["item"].rsplit("/", 1)[-1]
            self.code_qid[code].add(q)
            k = kind_of(code)
            for lab in (r.get("label_id"), r.get("label_en")):
                if lab:
                    n = norm(lab)
                    if n:
                        self.lut[(k, n)].add(code)
                        self.code_label.setdefault(code, lab)

    def resolve(self, kind, name, prov_hint=None):
        """(kind, name) -> (candidate_row, code, None) or (None, None, reason)."""
        n = norm(name)
        n = ALIASES_EXTRA.get(n, n) or n
        codes = self.lut.get((kind, n), set())
        if prov_hint:
            codes = {c for c in codes if c.startswith(prov_hint)} or codes
        if not codes:
            return None, None, "no_code"
        qids = {q for c in codes for q in self.code_qid.get(c, ()) if q in self.cand}
        if len(qids) == 1:
            q = next(iter(qids))
            code = max(c for c in codes if q in self.code_qid[c])  # newest code after province splits
            return self.cand[q], code, None
        if not qids:
            return None, max(codes), "code_not_in_candidate_csv"
        return None, None, "ambiguous:" + ",".join(sorted(qids))


SLUG_RX = re.compile(r"^(?:perda|perbup|perwali|qanun|kepbup|kepwal|perkab|perkot|perdes|perdasus|perdais|peraturan|keputusan)"
                     r"-(kab|kota)-([a-z0-9-]+?)(?:-no(?:-|$)|-nomor|-tahun|-$|$)")
TEU_RX = re.compile(r"T\.E\.U\.?\s*\n\s*Indonesia,\s*(Kabupaten|Kota)\s+(?:Administrasi\s+)?([^\n,]+)", re.I)
LOK_RX = re.compile(r"Lokasi\s*\n\s*Pemerintah\s+(Kabupaten|Kota)\s+([^\n,]+)", re.I)
TITLE_RX = re.compile(r"\b(Kabupaten|Kota|Kab\.)\s+([A-Z][\w' -]+?)\s+(?:Nomor|No\.?)\b")


def extract_kind_name(url, text, title):
    """Returns (kind, name, how) or (None, None, None)."""
    for rx, how in ((TEU_RX, "teu"), (LOK_RX, "lokasi")):
        m = rx.search(text or "")
        if m:
            return ("kota" if m.group(1).lower() == "kota" else "kab"), m.group(2).strip(), how
    m = TITLE_RX.search(title or "")
    if m:
        return ("kota" if m.group(1).lower() == "kota" else "kab"), m.group(2).strip(), "title"
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    m = SLUG_RX.match(slug)
    if m:
        return m.group(1), m.group(2).replace("-", " "), "slug"
    return None, None, None

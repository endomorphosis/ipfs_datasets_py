"""Greek municipality name matching: Diavgeia org label ('ΔΗΜΟΣ ΑΒΔΗΡΩΝ', genitive) -> candidate CSV (English names)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, unicodedata, difflib

def strip_acc(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

DI = [("ου", "ou"), ("αι", "e"), ("ει", "i"), ("οι", "i"), ("υι", "i"), ("αυ", "av"), ("ευ", "ev"), ("μπ", "b"), ("ντ", "d"),
      ("γκ", "g"), ("γγ", "ng"), ("τσ", "ts"), ("τζ", "tz")]
MONO = {"α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m",
        "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "i", "φ": "f", "χ": "ch", "ψ": "ps",
        "ω": "o"}
WORDS = {"βορειας": "north", "βορειου": "north", "βορειων": "north", "βορειο": "north", "νοτιας": "south", "νοτιου": "south",
         "νοτιων": "south", "δυτικης": "west", "δυτικου": "west", "δυτικων": "west", "ανατολικης": "east",
         "ανατολικου": "east", "ανατολικων": "east", "κεντρικης": "central", "κεντρικων": "central", "κεντρικου": "central",
         "αρχαιας": "ancient", "ιερας": "", "πολης": "", "νεας": "nea", "νεου": "neo", "αγιου": "agios", "αγιας": "agia",
         "αγιων": "agioi", "αθηναιων": "athens", "πειραιως": "piraeus", "θεσσαλονικης": "thessaloniki"}
EN_DROP = re.compile(r"\b(municipality|municipal unit|of|dimos|the)\b")


def translit(w):
    w = strip_acc(w.lower())
    if w in WORDS:
        return WORDS[w]
    o, i = "", 0
    while i < len(w):
        d = w[i:i + 2]
        hit = next((v for k, v in DI if k == d), None)
        if hit is not None:
            o += hit; i += 2; continue
        o += MONO.get(w[i], w[i]); i += 1
    return o


def skel(w):
    """consonant skeleton without endings: robust to genitive/nominative + transliteration variants."""
    w = re.sub(r"(ou|on|os|as|is|es|ia|io|a|i|o|e|ai|oi|ion|ou)$", "", w)
    w = w.replace("y", "i").replace("ph", "f").replace("kh", "ch").replace("c", "k").replace("kh", "ch").replace("w", "o")
    return re.sub(r"[aeiou]", "", w)


def tokens_gr(label):
    s = re.sub(r"^ΔΗΜΟΣ\s+", "", label.strip(), flags=re.I)
    return [translit(t) for t in re.split(r"[\s\-–,]+", s) if t]


def tokens_en(name):
    s = EN_DROP.sub(" ", strip_acc(name.lower()))
    return [t for t in re.split(r"[^a-z]+", s) if t]


def score(gt, et):
    gt = [t for t in gt if t]; et = [t for t in et if t]
    if not gt or not et:
        return 0.0
    dirs = {"north", "south", "west", "east", "central", "ancient"}
    if (set(gt) & dirs) != (set(et) & dirs):
        return 0.0
    g = [skel(t) for t in gt if t not in dirs]
    e = [skel(t) for t in et if t not in dirs]
    if not g or not e:
        return 0.0
    r = difflib.SequenceMatcher(None, "".join(g), "".join(e)).ratio()
    norm = lambda ts: re.sub(r"(ou|on|os|as|is|es|a|i|o|e)$", "", "".join(ts).replace("y", "i"))
    f = difflib.SequenceMatcher(None, norm([t for t in gt if t not in dirs]), norm([t for t in et if t not in dirs])).ratio()
    return 0.6 * r + 0.4 * f + (0.05 if len(g) == len(e) else 0)


class GrPlaces:
    def __init__(self, cand_rows):
        self.c = [(r, tokens_en(r["place_name"])) for r in cand_rows]

    def match(self, label, latin=None, exclude=()):
        """exclude: place_ids owned by an exact code; they are never name-match targets."""
        c = [(r, et) for r, et in self.c if r["place_id"] not in exclude]
        gt = tokens_gr(label)
        best = sorted(((score(gt, et), r["place_id"], r) for r, et in c), key=lambda x: -x[0])
        if latin:
            lt = tokens_en(re.sub(r"^(dimos|dhmos|d)(?=[a-z])", "", latin.lower()))
            best2 = sorted(((score(lt, et), r["place_id"], r) for r, et in c), key=lambda x: -x[0])
            if best2 and (not best or best2[0][0] > best[0][0]):
                best = best2
        best = [b for i, b in enumerate(best) if b[1] not in {x[1] for x in best[:i]}]   # dedupe candidate rows
        if best and best[0][0] >= 0.8 and (len(best) == 1 or best[1][0] < best[0][0] - 0.03):
            return best[0][2], round(best[0][0], 2)
        return None, round(best[0][0], 2) if best else 0


CODES_CSV = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_codes.csv")
ADDITIONS_CSV = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_additions.csv")


def load_org_codes(path=CODES_CSV):
    """Diavgeia org uid -> place_id from the shared crosswalk (code_system gr_diavgeia_org). Former places
    (is_current False) are kept on purpose: a pre-2019 org issued its acts as that former municipality.
    Streams the CSV (no pyarrow needed); uids that map to more than one place are dropped."""
    import csv
    d = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] == "GR" and r["code_system"] == "gr_diavgeia_org" and r["code"]:
                d.setdefault(r["code"].strip(), set()).add(r["place_id"])
    return {k: next(iter(v)) for k, v in d.items() if len(v) == 1}


def load_additions(cc="GR", path=ADDITIONS_CSV):
    import csv
    with open(path, encoding="utf-8") as f:
        return {r["place_id"]: r for r in csv.DictReader(f) if r["country_code"] == cc}


def assign(gp, orgs, codes=None, extra_rows=None):
    """one org -> one place. Returns {uid: (row, score, via)} with via 'code' or 'name'.
    1. EXACT CODE FIRST: an org whose uid is in `codes` (place_codes gr_diavgeia_org) gets that place, whatever any
       fuzzy score says. Rows come from the candidate list, else from `extra_rows` (place_additions).
    2. Name matching only for orgs without a code, and only against places that NO org owns by code, so a
       high fuzzy score (e.g. Chaidari 6313 -> Hydra 0.97) can never take a code-owned place or override a code.
    3. Among name matches, keep the higher-scoring org when two map to the same candidate (margin 0.03)."""
    codes = codes or {}
    extra_rows = extra_rows or {}
    by_pid = {r["place_id"]: r for r, _ in gp.c}
    out, claimed = {}, set(codes.values())
    for o in orgs:
        pid = codes.get(str(o["uid"]))
        if pid:
            r = by_pid.get(pid)
            if r is None and pid in extra_rows:
                x = extra_rows[pid]
                r = {"place_id": pid, "qid": x.get("qid") or pid.split(":")[-1], "place_name": x.get("name"),
                     "country_code": "GR", "admin_level": x.get("admin_level") or "municipality"}
            if r is None:
                r = {"place_id": pid, "qid": pid.split(":")[-1], "place_name": o.get("label"), "country_code": "GR",
                     "admin_level": "municipality"}
            out[o["uid"]] = (r, 1.0, "code")
    got = {}
    for o in orgs:
        if o["uid"] in out or str(o["uid"]) in codes:
            continue
        r, sc = gp.match(o["label"], o.get("latinName"), exclude=claimed)
        if r:
            got.setdefault(r["place_id"], []).append((sc, o["uid"], r))
    for pid, lst in got.items():
        lst.sort(key=lambda x: -x[0])
        if len(lst) == 1 or lst[0][0] > lst[1][0] + 0.03:
            out[lst[0][1]] = (lst[0][2], lst[0][0], "name")
    return out

#!/usr/bin/env python3
"""GB / IE place list for the ukie lane (from the shared candidate CSV) + place-code crosswalk.

phase 1 = GB principal councils (municipality / unitary_authority / council_area / principal_area / county / district)
phase 2 = GB town / parish / community councils (parish, community)
phase 3 = IE local authorities (county / city / 'city and county' councils; 31 LAs)
Usage: python3 places.py init      # load places into the state db (idempotent)
       python3 places.py codes     # write _state/place_codes_gaps.csv (places lacking GB/IE official codes)
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
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.util import STATE_DIR, State  # noqa: E402

CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
CODES = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/codes/place_codes.csv"))
ADDITIONS = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/codes/place_additions.csv"))
GSS_REVIEWED = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/proposed/GB_gss_reviewed.csv"))
# Normalizer decisions 2026-10-17: duplicate candidate rows -> canonical place (never stage to the left side)
CANON = {"wd:Q161491": "wd:Q21496716",      # Reading town -> Reading (borough council area)
         "wd:Q140626421": "wd:Q21683242",   # Leicester 'upcoming' row -> Leicester unitary
         "wd:Q504530": "wd:Q178356",        # Walsall duplicate
         "wd:Q131463862": "wd:Q80967",      # Na h-Eileanan an Iar -> Outer Hebrides
         "wd:Q1761": "wd:Q4810766"}         # Dublin (city) -> Dublin City Council
GREATER_LONDON = "wd:Q23306"
PRINCIPAL = {"municipality", "unitary_authority", "council_area", "principal_area", "county", "district"}
LOCAL = {"parish", "community"}
IE_LA = {"county", "city", "municipality"}
# official code systems we would expect for these places (none exist in place_codes yet for GB/IE)
WANT = {"GB": "gb_ons_gss (Wikidata P836)", "IE": "ie_osi_la / ie_cso (no Wikidata property; LA id)"}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    s = re.sub(r"^(london borough of|royal borough of|city and county of|city of|borough of|county of|"
               r"metropolitan borough of|the)\s+", "", s.strip())
    for _ in range(3):
        s = re.sub(r"\s+(city|borough|district|county|metropolitan borough|metropolitan district|council|"
                   r"unitary authority|regional|metropolitan)$", "", s)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def phase_of(r):
    cc, lvl = r["country_code"], r["admin_level"]
    if cc == "GB":
        return 1 if lvl in PRINCIPAL else 2 if lvl in LOCAL else None
    if cc == "IE":
        return 3 if lvl in IE_LA else None
    return None


NAME_FIX = {"wd:Q156150": "Powys", "wd:Q596885": "Blaenau Gwent"}   # candidate labels not in English
LANE_CANON = {}   # filled by load(): GSS-less duplicate principal rows -> same-name row with a current GSS (ukie rule)


def current_gss():
    have = set()
    with CODES.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] == "GB" and r["code_system"] == "gb_gss" and r.get("is_current") in ("True", "true", "1"):
                have.add(r["place_id"])
    return have


def upcoming_areas():
    """'Upcoming' local-government-reorganisation areas (future unitaries such as North Kent, Greater Norwich,
    Greater Nottingham): GB unitary_authority rows with no current gb_gss code, plus GSS-review rejects for future
    unitaries. Never stage to these; docs go to the current councils."""
    have = current_gss()
    up = set()
    for r in csv.DictReader(CAND.open(encoding="utf-8")):
        if r["country_code"] == "GB" and r["admin_level"] == "unitary_authority" and r["place_id"] not in have:
            up.add(r["place_id"])
    if GSS_REVIEWED.exists():
        for r in csv.DictReader(GSS_REVIEWED.open(encoding="utf-8")):
            if r["decision"] == "reject" and "future unitary" in r["reason"]:
                up.add(r["place_id"])
    return up - set(CANON.values())


def load():
    out, up = [], upcoming_areas()
    rows = list(csv.DictReader(CAND.open(encoding="utf-8")))
    for a in csv.DictReader(ADDITIONS.open(encoding="utf-8")):   # e.g. Greater London (wd:Q23306, region)
        if a["country_code"] in ("GB", "IE"):
            rows.append({"place_id": a["place_id"], "place_name": a["name"], "country_code": a["country_code"],
                         "qid": a["qid"], "admin_level": a["admin_level"], "iso_3166_2": a["iso_3166_2"],
                         "source_url": "", "population": ""})
    have = current_gss()
    for r in rows:
        if r["place_id"] in NAME_FIX:
            r["place_name"] = NAME_FIX[r["place_id"]]
    gss_names = {(fold(r["place_name"]), r["admin_level"]): r["place_id"] for r in rows
                 if r["country_code"] == "GB" and r["place_id"] in have}
    for r in rows:
        if r["country_code"] not in ("GB", "IE") or r["place_id"] in CANON or r["place_id"] in up:
            continue
        ph = phase_of(r) or (1 if r["admin_level"] == "region" else None)
        # ukie rule 2026-10-18: a GB principal council must hold a current GSS code (Greater London excepted).
        # GSS-less same-name duplicates -> LANE_CANON; GSS-less towns ('municipality') -> phase 2; others dropped.
        if ph == 1 and r["country_code"] == "GB" and r["place_id"] not in have and r["place_id"] != GREATER_LONDON:
            k = (fold(r["place_name"]), r["admin_level"])
            if k in gss_names and r["admin_level"] != "municipality":
                LANE_CANON[r["place_id"]] = gss_names[k]
                continue
            ph = 2 if r["admin_level"] == "municipality" else None
        if ph:
            r["phase"] = ph
            r["site"] = (r["source_url"] or "").split(",")[0].strip()
            out.append(r)
    return out


class Places:
    def __init__(self):
        self.rows = load()
        self.by_id = {r["place_id"]: r for r in self.rows}
        self.by_name = {}
        for r in self.rows:
            self.by_name.setdefault((r["country_code"], fold(r["place_name"])), []).append(r)

    def get(self, pid):
        pid = CANON.get(pid, pid)
        return self.by_id.get(LANE_CANON.get(pid, pid))

    def find(self, cc, name, phase=None):
        c = self.by_name.get((cc, fold(name)), [])
        if phase:
            c = [r for r in c if r["phase"] == phase]          # strict: never fall back to another phase
        return c[0] if len(c) == 1 else None


def place_codes():
    """{place_id: {code_system: code}} for GB/IE from codes/place_codes.csv (current codes only)."""
    out = {}
    with CODES.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["country_code"] in ("GB", "IE") and r.get("is_current", "True") in ("True", "true", "1", ""):
                out.setdefault(r["place_id"], {})[r["code_system"]] = r["code"]
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    P = Places()
    if cmd == "init":
        st = State()
        n = 0
        for r in P.rows:
            if st.place(r["place_id"]) is None:
                st.upsert_place(place_id=r["place_id"], cc=r["country_code"], phase=r["phase"], name=r["place_name"],
                                tier=r["admin_level"], site=r["site"] or None, status="todo")
                n += 1
        print("added", n, "of", len(P.rows), st.summary()["phases"])
    elif cmd == "codes":
        pc = place_codes()
        gaps = STATE_DIR / "place_codes_gaps.csv"
        with gaps.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["place_id", "country_code", "phase", "admin_level", "place_name", "codes_present",
                        "missing_code_system"])
            for r in P.rows:
                have = pc.get(r["place_id"], {})
                if not any(k.startswith(("gb_", "ie_")) for k in have):
                    w.writerow([r["place_id"], r["country_code"], r["phase"], r["admin_level"], r["place_name"],
                                ";".join(f"{k}={v}" for k, v in sorted(have.items())), WANT[r["country_code"]]])
        print("wrote", gaps)


if __name__ == "__main__":
    main()

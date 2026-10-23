"""Fiji national Local Government subsidiary legislation (Cap.125) from laws.gov.fj API -> iso:FJ.
List = items of the LGA 1972 tree not assigned to a town (same rule as out/eap/eap_fj_bylaws.py;
equals out/eap/FJ/_national_lg_regs.json once that run finishes). Resumable ckpt; ~1 req / 2 s."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, html, requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/us")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from stage_util import write_part, utcstamp, now_iso, check_space
import robots
API = "https://www.laws.gov.fj/api"; DELAY = 2.0
ONLY = os.environ.get("FJ_ONLY")
CK = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/FJ/_ckpt_lg") + ("2" if ONLY else ""); os.makedirs(CK, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = robots.UA
def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)
TOWNS = {"SUVA","LAUTOKA","NADI","BA","LABASA","LAMI","LEVUKA","NASINU","NAUSORI","RAKIRAKI","SAVUSAVU","SIGATOKA","TAVUA"}
def town_of(t):
    t = t.upper().replace("\u2009", " ").strip(); m = re.match(r"LOCAL GOVERNMENT \(([A-Z]+)", t)
    w = m[1] if m else re.match(r"[A-Z]+", t)[0]; return w if w in TOWNS else None
def leaves(n, acc):
    for x in n: acc.append((int(x.get("Position") or 0), x["LegalId"], x.get("Title", ""))); leaves(x.get("SectionData", []), acc)
    return acc
def get(u):
    for i in range(5):
        try:
            r = S.get(u, timeout=60); time.sleep(DELAY)
            if r.status_code == 200: return r.json()
            log("http", r.status_code, u)
            if r.status_code in (401, 403, 404): return None
        except Exception as e: log("err", u, e)
        time.sleep(min(600, 15 * 2 ** i))
def main():
    rb, info = robots.robots_for(API + "/"); log("robots", info)
    if not robots.allowed(API + "/get_act_by_id/10110"): log("robots disallow -> stop"); return
    tf = f"{CK}/tree.json"
    if not os.path.exists(tf):
        t = get(f"{API}/get_act_by_id/10110"); json.dump(t, open(tf, "w"))
    tree = json.load(open(tf)); nat = [x for x in tree[1]["Sections"] if not town_of(x["Title"])]
    if ONLY:
        ids = set(json.load(open(ONLY))); nat = [x for x in tree[1]["Sections"] if x["LegalId"] in ids]
    log("national items", len(nat))
    pf = f"{CK}/parts.jsonl"; done = {json.loads(l)["legal_id"] for l in open(pf)} if os.path.exists(pf) else set()
    for x in nat:
        if x["LegalId"] in done: continue
        hs, upd = [], None
        for pos, lid, ti in sorted(leaves([x], [])):
            u = f"{API}/retrieve_html/{lid}"
            if not robots.allowed(u): log("robots disallow", u); continue
            d = get(u)
            if d: hs.append(d.get("section_html", "")); upd = upd or d.get("act_last_updated")
        with open(pf, "a") as f:
            f.write(json.dumps({"legal_id": x["LegalId"], "title": x["Title"].strip(), "year": x.get("Year"), "status": x.get("Status"),
                                "repealed": x.get("IsRepealed"), "act_id": x.get("ActId"), "html": "\n".join(hs), "updated": upd, "at": now_iso()}, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
        log("got", x["LegalId"], len(hs), sum(map(len, hs)))
    recs = []
    for l in open(pf):
        p = json.loads(l)
        if not p["html"].strip(): log("empty", p["legal_id"]); continue
        txt = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", html.unescape(re.sub(r"<[^>]+>", " ", p["html"])))).strip()
        title = re.sub(r"\s+", " ", p["title"])
        recs.append({"place_id": "iso:FJ", "country_code": "FJ", "doc_id": "fj_laws_" + p["legal_id"].replace(".BODY", ""),
            "source_platform": "fj_laws_gov_fj", "source_url": f"{API}/retrieve_html/{p['legal_id']}",
            "doc_type": "regulation", "language": "en", "title_native": title, "html_title": title, "html": p["html"], "text": txt,
            "number": p["legal_id"].replace(".BODY", ""), "adopted_date": p["year"] if (p.get("year") or "").isdigit() else None,
            "in_force": p.get("status") == "Active" and p.get("repealed") == "false", "consolidated": True, "content_format": "html",
            "retrieved_at": p["at"], "extra_metadata": {"api_url": f"{API}/retrieve_html/{p['legal_id']}", "parent_act": "Local Government Act 1972 (Cap. 125)", "last_updated": p.get("updated"), "robots": info.get("rule")}})
    check_space(); log(write_part("FJ", "iso:FJ", f"lgregs{'add' if ONLY else ''}{utcstamp()}p0001", recs, log))
if __name__ == "__main__": main()

"""Spain tranche-1 campaign runner (BORM = Murcia, BOCM = Madrid).

Generalizes the validated ES pilot (../es_pilot/harvest_es_pilot.py): same
adapters, gates and row builder, but full-region scope — every INE municipio
of the region, every ordenanza/reglamento definitiva in the window, no
per-municipio act cap. Normalization/validation go through the shared
world_municipal library; each validated municipio is published immediately
to endomorphosis/ipfs_spain_municipal_laws as data/{ine}_html.parquet
(Portugal layout) and remote-verified. Progress lives in campaign_state.json
so any interrupted run resumes cleanly (published/zero_acts are skipped).

HF auth: dynamic credential surrogate (connector custom.huggingface),
never printed or persisted.
"""

from __future__ import annotations

import os as _os

# Egress quirk (AGENTS.md): httpx chokes on the bracketed IPv6 entries in the
# ambient no_proxy/NO_PROXY — must be force-set, not setdefault, before any
# huggingface_hub/httpx use.
_os.environ["no_proxy"] = "localhost,127.0.0.1"
_os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import importlib.util
import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GOAL_HIDDEN = ROOT.parent
WINDOW = ("2024-10-06", "2026-10-12")
REPO = "endomorphosis/ipfs_spain_municipal_laws"
STATE_PATH = ROOT / "campaign_state.json"  # legacy (BORM run of 2026-10-12)
STATE_PATHS = {"borm": ROOT / "campaign_state.json",
               "bocm": ROOT / "campaign_state_bocm.json"}
DATA_DIR = ROOT / "data"
VAL_DIR = ROOT / "validation"

# ---------------------------------------------------------------- pilot reuse
_spec = importlib.util.spec_from_file_location(
    "es_pilot", GOAL_HIDDEN / "es_pilot" / "harvest_es_pilot.py")
pilot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot)
pilot.WINDOW = WINDOW  # widen the pilot's date window to campaign scope

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from ipfs_datasets_py.processors.legal_scrapers import world_municipal as wm  # noqa: E402

# ---------------------------------------------------------------- HF publish
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
import os  # noqa: E402

os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402


def hf_api(refresh: bool = False):
    from huggingface_hub import HfApi
    tok = str(dynamic_credential_entry("custom.huggingface")["surrogate"]).strip()
    return HfApi(token=tok)


def publish_municipio(api, ine: str, parquet: Path, name: str, portal: str,
                      acts: int, rows: int) -> str:
    """Upload one municipio parquet; verify it exists at the commit; return oid."""
    path_in_repo = f"data/{ine}_html.parquet"
    msg = (f"ES tranche 1 ({portal.upper()}): {ine} {name} — "
           f"{acts} acts, {rows} rows")
    try:
        info = api.upload_file(path_or_fileobj=str(parquet),
                               path_in_repo=path_in_repo, repo_id=REPO,
                               repo_type="dataset", commit_message=msg)
        verify_api = api
    except Exception:
        verify_api = hf_api(refresh=True)  # one token-refresh retry
        info = verify_api.upload_file(path_or_fileobj=str(parquet),
                                      path_in_repo=path_in_repo, repo_id=REPO,
                                      repo_type="dataset", commit_message=msg)
    oid = getattr(info, "oid", None) or getattr(info, "commit_oid", None)
    files = verify_api.list_repo_files(REPO, repo_type="dataset", revision=oid)
    if path_in_repo not in files:
        raise RuntimeError(f"verify failed: {path_in_repo} not at commit {oid}")
    return oid


# ---------------------------------------------------------------- registries
def deinvert(name: str) -> str:
    m = re.match(r"^(.*),\s*(El|La|Los|Las)$", name)
    return f"{m.group(2)} {m.group(1)}" if m else name


def load_municipios(portal: str) -> list[dict]:
    ine = json.loads((ROOT / "registries" / "ine_28_30.json").read_text())
    if portal == "borm":
        cross = json.loads((ROOT / "registries" / "borm_crosswalk.json").read_text())
        out = []
        for m in ine["30"]:
            c = cross[m["ine"]]
            out.append({"ine": m["ine"], "name": m["name"],
                        "portal_id": c["borm_id"],
                        "aliases": [m["name"], deinvert(m["name"]), c["borm_name"],
                                    f"Ayuntamiento de {deinvert(m['name'])}",
                                    f"Ayuntamiento de {c['borm_name']}"]})
        return out
    cross = json.loads((ROOT / "registries" / "bocm_crosswalk.json").read_text())
    out = []
    for m in ine["28"]:
        c = cross[m["ine"]]
        plain = deinvert(m["name"])
        out.append({"ine": m["ine"], "name": m["name"],
                    "portal_id": c["org_id"],
                    "aliases": [m["name"], plain, c["org_name"],
                                f"Ayuntamiento de {plain}"]})
    # flagship pilot towns first, then INE order
    out.sort(key=lambda d: (d["ine"] not in ("28079", "28005"), d["ine"]))
    return out


# ---------------------------------------------------------------- state
def load_state(portal: str) -> dict:
    p = STATE_PATHS[portal]
    if p.exists():
        return json.loads(p.read_text())
    return {"window": list(WINDOW), "repo": REPO, "portal": portal,
            "started": datetime.now(timezone.utc).isoformat(), "municipios": {}}


def save_state(state: dict, portal: str) -> None:
    STATE_PATHS[portal].write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- candidates
def borm_candidates_full(http, ayto_id: int, log) -> list[dict]:
    # Real API contract (scripts/anuncio/factories/anuncioFactory.js):
    # ?pageNumber=N (1-based) & pageSize=M. The pilot's ?pagina= is ignored
    # by the server (always returns page 1) — harmless at pilot scope,
    # corrected here.
    out = []
    for page in range(1, 501):
        r = http.get(f"{pilot.BORM}/services/anuncio/ayuntamiento/{ayto_id}"
                     f"?pageNumber={page}&pageSize=100")
        root = ET.fromstring(r.content)
        items = []
        for li in root.iter("listItems"):
            f = {c.tag: (c.text or "") for c in li}
            if f.get("id"):
                items.append(f)
        if not items:
            log(f"  borm page {page}: empty, stop")
            break
        dates = []
        for f in items:
            ts = int(f.get("fechaPublicacion") or 0) // 1000
            d = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
            dates.append(d)
            s = f.get("sumario", "")
            if WINDOW[0] <= d <= WINDOW[1] and pilot.ORDEN_RE.search(s) \
                    and re.search(r"definitiva", s, re.I):
                out.append({"id": f["id"], "title": s.strip(), "date": d,
                            "pages": int(f.get("paginas") or 0),
                            "numero": f.get("numero", ""),
                            "boletin": f.get("numeroBoletin", "")})
        oldest = min(dates) if dates else None
        if page % 5 == 0 or oldest and oldest < WINDOW[0]:
            log(f"  borm page {page}: {len(items)} items, {len(out)} candidates, oldest {oldest}")
        if oldest and oldest < WINDOW[0]:
            break
    return out


def bocm_candidates_full(http, org_id: str, log) -> list[dict]:
    from bs4 import BeautifulSoup
    out = []
    for page in range(300):
        url = f"{pilot.BOCM}/advanced-search/p/field_orden_organo_y_organismo_3/{org_id}/seccion/8387"
        if page:
            url += f"/page/{page}"
        r = http.get(url)
        soup = BeautifulSoup(r.text, "lxml")
        rows = []
        for art in soup.select("article.node-orden"):
            about = (art.get("about") or "").strip("/")
            desc = art.select_one(".field-name-field-short-description .field-item")
            if about and desc:
                rows.append((about.upper(), desc.get_text(" ", strip=True).lstrip("–- ").strip()))
        if not rows:
            log(f"  bocm page {page}: no rows, stop")
            break
        dates = [c[5:13] for c, _ in rows]
        for cve, title in rows:
            d = f"{cve[5:9]}-{cve[9:11]}-{cve[11:13]}"
            if WINDOW[0] <= d <= WINDOW[1] and pilot.ORDEN_RE.search(title):
                out.append({"cve": cve, "title": title, "date": d})
        if page % 10 == 0 or max(dates) < WINDOW[0].replace("-", ""):
            log(f"  bocm page {page}: {len(rows)} results, {len(out)} candidates, newest {max(dates)}")
        if max(dates) < WINDOW[0].replace("-", ""):
            break
    return out


# ---------------------------------------------------------------- gates
def attribution_ok_any(act: dict, aliases: list[str]) -> bool:
    head = act["text"][:3000].upper()
    title = act["title"].upper()
    return any(a.upper() in head or a.upper() in title for a in aliases if a)


def borm_detail_raw(http, cand: dict, name: str):
    """pilot.borm_detail, but also returns the pre-strip raw text.

    borm_detail strips the 3-line gazette header (section / municipio /
    anuncio no.) when line 2 names the municipio — yet that header is
    often the ONLY attribution in the first 3,000 chars, so gating
    attribution on the stripped text falsely rejects full ordinances
    (found 2026-10-13: San Pedro del Pinatar anuncio 840617, a 13-article
    IAE ordinance whose town name appears at char 25 of the raw text and
    not again until ~char 18,670 of the stripped text). Attribution is
    therefore checked against the raw text; rows are still built from
    the stripped text, exactly as the pilot/campaign always did.
    """
    r = http.get(f"{pilot.BORM}/services/anuncio/{cand['id']}/txt")
    raw = r.content.decode("utf-8", "replace").strip()
    if len(raw) < 200:  # announcement-only or empty: PDF chain, as pilot
        rp = http.get(f"{pilot.BORM}/services/anuncio/{cand['id']}/pdf")
        if rp.content[:4] == b"%PDF":
            raw = pilot.pdf_to_text(rp.content).strip()
    lines = [ln.strip() for ln in raw.split("\n")]
    text = raw
    if len(lines) > 4 and lines[1].lower() == name.lower():
        text = "\n".join(lines[3:]).strip()
    act = {"regeling_id": cand["id"],
           "work_id": f"BORM núm. {cand['boletin']} anuncio {cand['numero']}",
           "title": cand["title"], "text": text,
           "source_url": f"{pilot.BORM}/services/anuncio/{cand['id']}/txt",
           "xml_url": f"{pilot.BORM}/services/anuncio/{cand['id']}/pdf",
           "date": cand["date"], "lang": "es"}
    return act, raw


# ---------------------------------------------------------------- per-municipio
def run_municipio(portal: str, m: dict, http, api, state: dict, log) -> dict:
    ine, name = m["ine"], m["name"]
    entry = {"ine": ine, "name": name, "portal": portal,
             "portal_id": m["portal_id"], "status": "harvesting",
             "candidates": 0, "kept_acts": 0, "rejected": 0, "rows": 0,
             "commit": None, "verified": False,
             "updated": datetime.now(timezone.utc).isoformat()}
    acts: list[dict] = []
    try:
        if portal == "borm":
            cands = borm_candidates_full(http, int(m["portal_id"]), log)
            entry["candidates"] = len(cands)
            for c in cands:
                try:
                    act, raw = borm_detail_raw(http, c, deinvert(name))
                except Exception as e:  # noqa: BLE001
                    log(f"  ! borm {c['id']}: {e}")
                    continue
                if act and attribution_ok_any({**act, "text": raw}, m["aliases"]) \
                        and pilot.article_count(act) >= 2:
                    acts.append(act)
                    log(f"  + borm {c['id']}: kept ({pilot.article_count(act)} articles)")
                elif act:
                    entry["rejected"] += 1
        else:
            cands = bocm_candidates_full(http, str(m["portal_id"]), log)
            entry["candidates"] = len(cands)
            for c in cands:
                try:
                    act = pilot.bocm_detail(http, c)
                except Exception as e:  # noqa: BLE001
                    log(f"  ! {c['cve']}: {e}")
                    continue
                if act and attribution_ok_any(act, m["aliases"]) \
                        and pilot.article_count(act) >= 2:
                    acts.append(act)
                    log(f"  + {c['cve']}: kept ({pilot.article_count(act)} articles)")
                elif act:
                    entry["rejected"] += 1
    except Exception as e:  # noqa: BLE001
        entry["status"] = "failed"
        entry["error"] = f"{type(e).__name__}: {e}"
        log(f"  !! {name}: {entry['error']}")
        return entry

    entry["kept_acts"] = len(acts)
    if not acts:
        entry["status"] = "zero_acts"
        return entry

    rows: list[dict] = []
    for act in acts:
        rows.extend(pilot.make_rows(act, ine, name, len(rows)))
    table = wm.rows_to_table(rows)
    errors = wm.validate_table(table, jurisdiction_id=ine,
                               jurisdiction_name=name, country="ES")
    VAL_DIR.mkdir(parents=True, exist_ok=True)
    (VAL_DIR / f"{ine}_validation.json").write_text(json.dumps(
        {"ine": ine, "name": name, "rows": table.num_rows,
         "valid": not errors, "errors": errors}, indent=2, ensure_ascii=False))
    if errors:
        entry["status"] = "validation_failed"
        entry["error"] = "; ".join(errors[:5])
        log(f"  !! {name}: validation failed: {entry['error']}")
        return entry
    entry["rows"] = wm.write_html_parquet(DATA_DIR / f"{ine}_html.parquet", table)
    entry["status"] = "validated"
    try:
        oid = publish_municipio(api, ine, DATA_DIR / f"{ine}_html.parquet",
                                name, portal, len(acts), entry["rows"])
    except Exception as e:  # noqa: BLE001 — publish failure must not lose the run
        entry["publish_error"] = f"{type(e).__name__}: {e}"
        log(f"  !! {name}: publish failed (kept local, status=validated): {e}")
        return entry
    entry["commit"] = oid
    entry["verified"] = True
    entry["status"] = "published"
    entry["updated"] = datetime.now(timezone.utc).isoformat()
    log(f"  ✓ {name}: published commit {oid} ({entry['rows']} rows)")
    return entry


def main() -> None:
    portal = sys.argv[1]
    only = None
    limit = None
    for a in sys.argv[2:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    state = load_state(portal)
    api = hf_api()
    http = pilot.Polite(0.6) if portal == "borm" else pilot.Polite(10.2)

    def log(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    done = 0
    for m in load_municipios(portal):
        if only and m["ine"] not in only:
            continue
        prev = state["municipios"].get(m["ine"], {})
        if prev.get("status") in ("published", "zero_acts"):
            continue
        if limit is not None and done >= limit:
            break
        log(f"== {m['name']} ({m['ine']}) via {portal} id={m['portal_id']} ==")
        if prev.get("status") == "validated" and \
                (DATA_DIR / f"{m['ine']}_html.parquet").exists():
            # publish-only resume: parquet already harvested + validated
            entry = dict(prev)
            try:
                oid = publish_municipio(api, m["ine"],
                                        DATA_DIR / f"{m['ine']}_html.parquet",
                                        m["name"], portal,
                                        prev.get("kept_acts", 0), prev.get("rows", 0))
                entry.update({"commit": oid, "verified": True,
                              "status": "published",
                              "updated": datetime.now(timezone.utc).isoformat()})
                entry.pop("publish_error", None)
                log(f"  ✓ {m['name']}: published (resume) commit {oid}")
            except Exception as e:  # noqa: BLE001
                entry["publish_error"] = f"{type(e).__name__}: {e}"
                log(f"  !! {m['name']}: publish resume failed: {e}")
            state["municipios"][m["ine"]] = entry
            save_state(state, portal)
            done += 1
            continue
        entry = run_municipio(portal, m, http, api, state, log)
        state["municipios"][m["ine"]] = entry
        save_state(state, portal)
        done += 1
    log(f"run complete: {done} municipios processed this run")


if __name__ == "__main__":
    main()

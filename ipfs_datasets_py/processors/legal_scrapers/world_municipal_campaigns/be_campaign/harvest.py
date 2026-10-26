"""Flanders campaign tranche 1 — harvest (inline SPARQL + Gelinkt Notuleren
template route), normalize via world_municipal (pilot's besluit_rows),
validate fail-closed, write per-gemeente parquets + campaign state.

SPARQL results are cached per gemeente under be_campaign/cache/ so a
mid-gemeente interruption does not lose fetched batches."""
import importlib.util
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CAMP = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/be_campaign"
SCRIPTS = CAMP / "scripts"
PARQ = CAMP / "parquets"
CACHE = CAMP / "cache"
PARQ.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # repo snapshot #3: sparql_client.py sits beside this file
import sparql_client as sc  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "be_pilot", Path(__file__).resolve().parent.parent / "be_pilot" / "be_pilot_build.py")  # repo snapshot #3: sibling pilot dir (was an absolute hidden_files path)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report  # noqa: E402

PFX = sc.PFX
REG_TYPES = pilot.REG_TYPES
TYPE_ORDER = list(REG_TYPES)  # priority = pilot dict order

cw = json.load(open(CAMP / "crosswalk.json"))
inv = json.load(open(CAMP / "inventory.json"))
GEMEENTEN = {g["nis"]: g for g in cw["gemeenten"]}
ORDER = ["73042", "24055", "23100", "24011", "11016", "13002"]  # by besluit count desc

STATE_PATH = CAMP / "campaign_state.json"
state = json.load(open(STATE_PATH)) if STATE_PATH.exists() else {"gemeenten": {}}

client = sc.SparqlClient(delay=1.5)
http = requests.Session()
http.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-campaign/0.1"})


def save_state():
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def cache_load(nis, what):
    p = CACHE / f"{nis}_{what}.json"
    return json.load(open(p)) if p.exists() else {}


def cache_save(nis, what, data):
    (CACHE / f"{nis}_{what}.json").write_text(json.dumps(data, ensure_ascii=False))


def source_rank(url):
    if "/uittreksels/" in url and url.endswith("/raw"):
        return 0
    if "/uittreksels/" in url:
        return 1
    if url.endswith("/besluitenlijst"):
        return 2
    if url.endswith("/notulen"):
        return 3
    return 4


def pick_source(derived):
    return sorted(derived, key=lambda u: (source_rank(u), u))[0] if derived else ""


def type_label(types):
    for t in TYPE_ORDER:
        if t in types:
            return REG_TYPES[t]
    return ""


def batch_values(nis, uris, what):
    """what: 'value' -> {uri: str}; 'articles' -> {uri: [ {number, value} ]}"""
    cache = cache_load(nis, what)
    todo = [u for u in uris if u not in cache]
    B = int(os.environ.get("BE_BATCH", "25"))
    for i in range(0, len(todo), B):
        chunk = todo[i:i + B]
        vals = " ".join(f"<{u}>" for u in chunk)
        if what == "value":
            q = PFX + f"SELECT ?b ?v WHERE {{ VALUES ?b {{ {vals} }} ?b prov:value ?v }}"
            rows, _ = client.query(q)
            for r in sc.bindings_map(rows):
                cache[r["b"]] = r["v"]
        else:
            q = PFX + f"""SELECT ?b ?number ?value WHERE {{ VALUES ?b {{ {vals} }}
              ?b eli:has_part ?a . ?a a besluit:Artikel ; prov:value ?value .
              OPTIONAL {{ ?a eli:number ?number }} }}"""
            rows, _ = client.query(q)
            grouped = defaultdict(list)
            for r in sc.bindings_map(rows):
                grouped[r["b"]].append({"number": r.get("number", ""), "value": r.get("value", "")})
            for u in chunk:
                cache[u] = grouped.get(u, [])
        cache_save(nis, what, cache)
        print(f"    {nis} {what}: batch {i // B + 1} done ({len(cache)} cached)", flush=True)
    if what == "articles":
        def key(a):
            try:
                return (0, int(a.get("number", "")), "")
            except (TypeError, ValueError):
                return (1, 0, a.get("number", ""))
        return {u: sorted(cache.get(u, []), key=key) for u in uris}
    return {u: cache[u] for u in uris if u in cache}


def orgaan_labels(nis, uris):
    cache = cache_load(nis, "org")
    todo = [u for u in uris if u not in cache]
    B = 200
    for i in range(0, len(todo), B):
        vals = " ".join(f"<{u}>" for u in todo[i:i + B])
        q = PFX + f"""SELECT DISTINCT ?b ?orgaanLabel WHERE {{ VALUES ?b {{ {vals} }}
          ?b eli:passed_by ?org . ?org besluit:classificatie ?cls . ?cls skos:prefLabel ?orgaanLabel }}"""
        rows, _ = client.query(q)
        counts = defaultdict(lambda: defaultdict(int))
        for r in sc.bindings_map(rows):
            counts[r["b"]][r["orgaanLabel"]] += 1
        for u in todo[i:i + B]:
            c = counts.get(u, {})
            cache[u] = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if c else ""
        cache_save(nis, "org", cache)
    return {u: cache.get(u, "") for u in uris}


def _typeof_names(el):
    toks = el.get("typeof")
    toks = toks if isinstance(toks, list) else [toks or ""]
    names = set()
    for t in toks:
        for tok in t.split():
            names.add(tok.rsplit("#", 1)[-1].rsplit(":", 1)[-1])
    return names


def _content_of(container):
    """Extract (kind, payload) from a besluit container element: article list
    when the value embeds eli:has_part article elements, else the value HTML."""
    v = container.find(attrs={"property": "prov:value"}, recursive=False)
    if v is None:
        v = container.find(attrs={"property": "prov:value"})
    if v is None:
        return None
    arts = []
    for art in v.find_all(attrs={"typeof": True}):
        if "Artikel" not in _typeof_names(art):
            continue
        num_el = art.find(attrs={"property": "eli:number"})
        num = num_el.get_text(strip=True) if num_el else ""
        av = art.find(attrs={"property": "prov:value"})
        arts.append({"number": num, "value": str(av) if av is not None else str(art)})
    if arts:
        return ("articles", arts)
    return ("value", str(v))


def _prop_ends(name):
    return lambda p: bool(p) and p.endswith(name)


def find_page_content(soup, besluit_uri):
    """Match a besluit on a publication page: (1) container whose resource is
    the register URI; (2) behandeling join — the local content element whose
    prov:wasGeneratedBy / behandelt references match the register besluit's
    behandeling/agendapunt on the same page."""
    containers = [el for el in soup.find_all(attrs={"typeof": True})
                  if "Besluit" in _typeof_names(el)]
    for el in containers:
        if el.get("resource") == besluit_uri:
            got = _content_of(el)
            if got:
                return got
    reg = soup.find(attrs={"resource": besluit_uri})
    if reg is not None:
        beh = reg
        while beh is not None and "BehandelingVanAgendapunt" not in _typeof_names(beh):
            beh = beh.parent
        if beh is not None:
            beh_uri = beh.get("resource")
            ag = beh.find(attrs={"property": _prop_ends("behandelt")})
            ag_uri = ag.get("resource") if ag is not None else None
            for el in containers:
                wg = el.find(attrs={"property": "prov:wasGeneratedBy"})
                bt = el.find(attrs={"property": _prop_ends("behandelt")})
                if (wg is not None and beh_uri and wg.get("resource") == beh_uri) or \
                   (bt is not None and ag_uri and bt.get("resource") == ag_uri):
                    got = _content_of(el)
                    if got:
                        return got
    return None


def extract_page_value(url, besluit_uri, strict=False):
    """Fetch a Gelinkt Notuleren page; return (kind, payload, err) with
    kind 'value' (HTML string) or 'articles' (list of {number, value}).
    strict=True (list/notulen pages): only a verified besluit match counts —
    never grab another besluit's text from a multi-besluit page."""
    last_err = None
    for attempt in range(2):
        try:
            r = http.get(url, timeout=180)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(5 * (attempt + 1))
                continue
            soup = BeautifulSoup(r.text, "lxml")
            got = find_page_content(soup, besluit_uri)
            if got:
                return got[0], got[1], None
            vals = soup.find_all(attrs={"property": "prov:value"})
            if strict:
                last_err = f"no matching prov:value ({len(vals)} candidates, strict)"
            elif len(vals) == 1:
                return "value", str(vals[0]), None
            elif besluit_uri in r.text and vals:
                return "value", str(vals[0]), None
            else:
                last_err = f"no matching prov:value ({len(vals)} candidates)"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
        time.sleep(5 * (attempt + 1))
    return None, None, last_err


def clean_articles(arts):
    """Drop register/page articles with whitespace-only bodies — an empty
    article node must not block the besluit-level value fallback."""
    return [a for a in (arts or []) if (a.get("value") or "").strip()]


def fetch_from_pages(rec):
    """Try the besluit's Gelinkt Notuleren pages; return (kind, payload, err)."""
    cands = sorted(rec["derived"], key=lambda u: (source_rank(u), u))
    extra = [u[: -len("/besluitenlijst")] + "/notulen" for u in rec["derived"]
             if u.endswith("/besluitenlijst")]
    for u in extra:
        if u not in cands:
            cands.append(u)
    kind, payload, err = None, None, None
    for url in cands:
        strict = url.endswith("/besluitenlijst") or url.endswith("/notulen")
        kind, payload, err = extract_page_value(url, rec["uri"], strict=strict)
        if kind:
            break
        time.sleep(1.0)
    return kind, payload, err


def rows_from_page(g, rec, org, kind, payload, reg_articles):
    page_articles = payload if kind == "articles" else []
    page_value = payload if kind == "value" else ""
    detail = {"title": rec["title"], "datepub": rec["datepub"],
              "derived": pick_source(rec["derived"]),
              "orgaanLabel": org.get(rec["uri"], ""), "value": page_value}
    return pilot.besluit_rows(g, detail, clean_articles(reg_articles) or clean_articles(page_articles),
                              rec["uri"], type_label(rec["types"]))


def harvest_gemeente(nis):
    inv_g = inv["per_gemeente"][nis]
    g = {"nis": nis, "name": GEMEENTEN[nis]["name"]}
    inline = inv_g["inline"]
    stubs = inv_g["stub"]
    all_uris = [r["uri"] for r in inline] + [r["uri"] for r in stubs]
    org = orgaan_labels(nis, all_uris)
    values = batch_values(nis, [r["uri"] for r in inline], "value")
    articles = batch_values(nis, all_uris, "articles")
    rows_all, harvested, stub_failed = [], [], []

    def keep(rows):
        """Fail-closed hygiene: never emit rows whose text is empty (document
        shells with structural markup but no content)."""
        return [r for r in rows if pilot.strip_tags(r["html"]).strip()]

    for rec in inline:
        detail = {"title": rec["title"], "datepub": rec["datepub"],
                  "derived": pick_source(rec["derived"]),
                  "orgaanLabel": org.get(rec["uri"], ""),
                  "value": values.get(rec["uri"], "")}
        rows = pilot.besluit_rows(g, detail, clean_articles(articles.get(rec["uri"], [])),
                                  rec["uri"], type_label(rec["types"]))
        route = "inline"
        if not rows:
            # register value unusable (empty/stub article) -> publication page
            kind, payload, err = fetch_from_pages(rec)
            if kind:
                rows = rows_from_page(g, rec, org, kind, payload, articles.get(rec["uri"], []))
                route = "inline+page"
        rows = keep(rows)
        if rows:
            rows_all.extend(rows)
            harvested.append({"uri": rec["uri"], "route": route, "rows": len(rows)})
        else:
            stub_failed.append({"uri": rec["uri"], "route": "inline",
                                "reason": "no usable text in register value/articles or publication pages"})

    for rec in stubs:
        kind, payload, err = fetch_from_pages(rec)
        if not kind:
            stub_failed.append({"uri": rec["uri"], "route": "template", "reason": err or "extraction failed"})
            continue
        rows = keep(rows_from_page(g, rec, org, kind, payload, articles.get(rec["uri"], [])))
        if rows:
            rows_all.extend(rows)
            harvested.append({"uri": rec["uri"], "route": "template", "rows": len(rows)})
        else:
            stub_failed.append({"uri": rec["uri"], "route": "template",
                                "reason": "no usable text on publication pages (empty document shells)"})

    st = {"name": g["name"], "crosswalked": True,
          "inline_besluiten": len(inline), "stub_besluiten": len(stubs),
          "harvested": len(harvested), "failed": stub_failed}
    if not rows_all:
        st["validation"] = "FAILED: no rows"
        state["gemeenten"][nis] = st
        save_state()
        print(f"{g['name']}: NO ROWS", flush=True)
        return
    rows_all = pilot.finalize_rows(rows_all)
    table = rows_to_table(rows_all)
    errors = validate_table(table, jurisdiction_id=nis, jurisdiction_name=g["name"], country="BE")
    if errors:
        st["validation"] = "FAILED: " + "; ".join(errors)
        state["gemeenten"][nis] = st
        save_state()
        print(f"{g['name']}: VALIDATION FAILED: {errors}", flush=True)
        return
    n = write_html_parquet(PARQ / f"{nis}_html.parquet", table)
    write_validation_report(PARQ / f"{nis}_validation.json",
                            validation_report(table, jurisdiction_id=nis,
                                              jurisdiction_name=g["name"], country="BE"))
    st.update(rows=n, validation="pass", parquet=f"parquets/{nis}_html.parquet", published=False)
    state["gemeenten"][nis] = st
    save_state()
    print(f"{g['name']} ({nis}): {len(harvested)}/{len(all_uris)} besluiten -> {n} rows "
          f"(failed: {len(stub_failed)})", flush=True)


def main():
    only = sys.argv[1:] or ORDER
    for nis in only:
        if state.get("gemeenten", {}).get(nis, {}).get("validation") == "pass":
            print(f"{nis}: already validated, skipping (delete state entry to redo)", flush=True)
            continue
        try:
            harvest_gemeente(nis)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            state["gemeenten"][nis] = {"name": GEMEENTEN[nis]["name"], "validation": "ERROR",
                                       "traceback": traceback.format_exc()[-800:]}
            save_state()
    print("SPARQL requests:", client.n_requests, flush=True)


if __name__ == "__main__":
    main()

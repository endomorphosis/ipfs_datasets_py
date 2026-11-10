"""Per-country counts for the EU phase -> publish/EU_COUNTS.md (+ stdout)"""
import json, glob, os, collections
ROOT = "/workspace/world_courts"
EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE EU".split()
def jl(p): return [json.loads(l) for f in glob.glob(p) for l in open(f)]
lines = ["| cc | courthouses | bodies | geo | precise geo | place_ids | wikidata | judges | forms | rules | rule sets | crosswalk |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
tot = collections.Counter()
for cc in EU:
    d = f"{ROOT}/data/{cc.lower()}"
    ch = jl(f"{d}/{cc.lower()}_courthouses.jsonl"); h = [r for r in ch if r["record_type"] == "courthouse"]; b = len(ch) - len(h)
    geo = sum(1 for r in h if (r.get("geo") or {}).get("lat") is not None); pg = sum(1 for r in h if r.get("geo_source") in ("osm", "wikidata", "upstream", "official"))
    pl = sum(1 for r in h if r.get("place_ids")); wd = sum(1 for r in h if r.get("wikidata"))
    j = len(jl(f"{d}/{cc.lower()}_judges.jsonl")); f = len(jl(f"{d}/{cc.lower()}_forms*.jsonl")); ru = jl(f"{d}/{cc.lower()}_rules.jsonl"); x = len(jl(f"{d}/{cc.lower()}_rules_crosswalk.jsonl"))
    row = dict(h=len(h), b=b, geo=geo, pg=pg, pl=pl, wd=wd, j=j, f=f, r=len(ru), rs=len({r["rule_set_id"] for r in ru}), x=x); tot.update(row)
    lines.append(f"| {cc} | {len(h)} | {b} | {geo} | {pg} | {pl} | {wd} | {j} | {f} | {len(ru)} | {row['rs']} | {x} |")
lines.append(f"| **total** | {tot['h']} | {tot['b']} | {tot['geo']} | {tot['pg']} | {tot['pl']} | {tot['wd']} | {tot['j']} | {tot['f']} | {tot['r']} | {tot['rs']} | {tot['x']} |")
table = list(lines)
rows_ = {}
for l in table[2:-1]:
    c = [x.strip() for x in l.strip("|").split("|")]; rows_[c[0]] = [int(x) for x in c[1:]]
def lack(i): return " ".join(k for k, v in rows_.items() if k != "EU" and v[i] == 0)
summ = [f"# EU (phase 6) summary — world_courts", "",
 f"Generated {__import__('time').strftime('%Y-%m-%d %H:%M %Z')} by `scrapers/courts/intl/eu_stats.py`. 27 member states plus `EU` (CJEU: Court of Justice, General Court).", "",
 f"**Totals:** {tot['h']} courthouses, {tot['b']} court bodies, {tot['geo']} geocoded ({tot['pg']} at building level via OSM/Wikidata/upstream; the rest are municipality or postcode centroids), {tot['pl']} with place_ids, {tot['wd']} with a wikidata id, {tot['j']} judges, {tot['f']} forms, {tot['r']} rules in {tot['rs']} rule sets, {tot['x']} rule-to-court crosswalk links.", "",
 "## Coverage gaps (generated)", "",
 f"- No rules: {lack(8)}", f"- No forms (national; EU standard forms are under `EU`): {lack(7)}", f"- No judge roster: {lack(6)}", "",
 "## Sources and caveats", "",
 "- Courthouses: e-Justice European Court Database (open API) merged with OSM and Wikidata; DE/NL/IE rows also merged with the upstream endomorphosis ipfs_*_courts datasets (provenance in `upstream_json`). `geo_source` states the coordinate precision; place_ids come from the Wikidata P1566/P131 chain, then name matching.",
 "- Hierarchy: `court_body` nodes `{cc}-{family}-{tier}`; no geographic appeal-district links except imported IE rows.",
 "- Rules are official texts where reachable, otherwise tagged in `site_policy`: `archive:wayback` (RO, LV, EU instruments), `secondary_state_body` (PT via PGDL), `secondary_nonstate` (CY via CyLaw). Several are outdated or as-published only and say so in `rule_set`: FR (LEGI snapshot 2025-07-13), HR (NN texts), SI (UPB 2007/2021), IE (as made), BE (partial, art. 1386-1675/27), FI 689/1997 and 705/2007, DK (LBK 1298/2025).",
 "- Forms: EU standard forms (EUR-Lex via Wayback) and national forms for NL, SE, FI, HR, SI and EE (kohus.ee; the LV, CY, LU, MT, LT and BG crawls found none). Brochures, protocols, budgets, job descriptions and guidance were filtered out (AT, FI, EE; rejected items are kept in `<cc>_rejected_brochures.jsonl`, not published as forms).",
 "- Not collected: IT, HU, LT, LU, BG, AT, CZ, GR rules; see blockers below.", "",
 "## Blockers", "",
 "- e-justice.europa.eu 403; EUR-Lex WAF (read via Wayback); Cellar unreachable.",
 "- Unreachable or bot-blocked from the box (no bypass attempted): ris.bka.gv.at (AT), e-sbirka.cz (CZ), njt.hu and birosag.hu (HU), legislatie.just.ro and just.ro (RO, via Wayback only), likumi.lv (LV, via Wayback only), e-seimas.lrs.lt and teismai.lt (LT, Cloudflare), data.legilux.public.lu (LU, 403), lex.bg (BG, Cloudflare; private anyway), ministryofjustice.gr (GR, 403), domstol.dk (DK, 403), justice.belgium.be rules (BE, WAF after one request), obcan.justice.gov.sk (SK), justice.gov.mt and judiciarymalta.gov.mt (MT).",
 "- JS-only official portals: normattiva/Gazzetta Ufficiale (IT), diariodarepublica.pt (PT), Legilux (LU).",
 "- courts.ie robots.txt disallows /docs/ (IE forms not crawled).",
 "- Wikidata WDQS ~1 request/minute; gn_FR (GeoNames to Wikidata map for France) missing, so FR place_ids use name matching.",
 "- Forms: tiesas.lv (LV) lists no downloadable form files in the crawled section; cylaw/judicial.gov.cy (CY) is a Lotus Notes site that redirects to http; no national form pages found for LU, MT, LT or BG.",
 "- Judges: only CJEU (90, `needs_review`) and IE (198, imported). National supreme and constitutional court rosters were not collected.", "",
 "## Per-country counts", ""] + table
open(f"{ROOT}/publish/EU_COUNTS.md", "w").write("\n".join(summ) + "\n"); print("\n".join(table))

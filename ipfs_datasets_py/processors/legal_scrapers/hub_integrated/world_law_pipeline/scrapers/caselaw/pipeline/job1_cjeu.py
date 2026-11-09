"""Job 1: CJEU judgments via EU Cellar (SPARQL listing + XHTML manifestations, English). Bounded sample, newest first."""
import sys, re, json, hashlib, time, datetime
from cl_common import *

CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
SRC = "cjeu_cellar"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
LICENCE = "EU institutions reuse policy (Commission Decision 2011/833/EU; CURIA copyright notice permits reproduction of judicial decisions); no CC licence verified for case-law"
TERMS = {"basis": "CURIA copyright notice: 'You may reproduce the judicial decisions found in the case-law database' (third-party-copyright caveat); "
                  "Decision 2011/833/EU generally permits commercial/non-commercial reuse with attribution; no AI-training/TDM reservation found in the "
                  "notices or in publications.europa.eu robots.txt (no Content-Signal). Human legal review of the third-party caveat still advised.",
         "evidence_url": ["https://curia.europa.eu/site/jcms/d2_5167/en/copyright", "https://eur-lex.europa.eu/eli/dec/2011/833/oj/eng",
                          "https://publications.europa.eu/robots.txt"], "checked": "2026-10-29",
         "pending_legal_review": True}   # r5: pending_legal_review=true => rows ship restricted_ai_training=TRUE until a human clears the third-party-copyright caveat
DENY_CELEX = {"62014FJ0050", "62014FJ0051"}   # CURIA robots.txt disallows these cases (take-down style); never ingested
COURT = {"C": "Court of Justice of the European Union", "T": "General Court", "F": "Civil Service Tribunal"}  # used for BOTH matcher input and court_name_raw
Q = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?celex ?date ?ecli ?m WHERE {
 ?work cdm:resource_legal_id_celex ?celex .
 ?work cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/JUDG> .
 ?work cdm:work_date_document ?date .
 OPTIONAL { ?work cdm:case-law_ecli ?ecli }
 ?e cdm:expression_belongs_to_work ?work .
 ?e cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
 ?m cdm:manifestation_manifests_expression ?e . ?m cdm:manifestation_type ?mt .
 FILTER(str(?mt)="xhtml")
 FILTER(?date >= "%s"^^xsd:date && ?date < "%s"^^xsd:date)
} ORDER BY DESC(?date) ?celex LIMIT 3000"""

def months_back(start=(2026, 10)):
    y, m = start
    while y >= 1953:
        yield y, m
        m -= 1
        if m == 0: y, m = y - 1, 12

def nxt(y, m): return (y + (m == 12), 1 if m == 12 else m + 1)

def main():
    print(now_la(), "start", preflight("start"), flush=True)
    f = Fetcher(1.0); out = SourceOut(SRC); matcher = CourtMatcher()
    n_done = len(out.seen); fails = []; skipped_noeng = 0
    print("resume: already have", n_done, flush=True)
    t0 = time.time()
    for y, m in months_back():
        if n_done >= CAP: break
        y2, m2 = nxt(y, m)
        r = f.get(SPARQL, params={"query": Q % (f"{y}-{m:02d}-01", f"{y2}-{m2:02d}-01")}, headers={"Accept": "application/sparql-results+json"})
        recs = {}
        for b in r.json()["results"]["bindings"]:
            c = b["celex"]["value"]
            d = recs.setdefault(c, {"date": b["date"]["value"], "ecli": b.get("ecli", {}).get("value"), "ms": []})
            d["ms"].append(b["m"]["value"])
        for celex, d in recs.items():
            if n_done >= CAP: break
            if celex in out.seen or celex in DENY_CELEX: continue
            mm = re.match(r"^6(\d{4})(CJ|TJ|FJ)(\d{4})$", celex)
            if not mm:  # keep scope to plain judgments
                continue
            text = None; url = None
            for mu in d["ms"]:
                u = mu.replace("http://", "https://") + "/DOC_1"
                try:
                    resp = f.get(u, headers={"Accept": "application/xhtml+xml"})
                except RobotsDenied as e:
                    fails.append((celex, f"robots: {e}")); break
                except requests.RequestException as e:
                    fails.append((celex, repr(e)[:150])); continue
                if resp is None: continue
                tx = html_to_text(resp.content)
                if len(tx) >= 500:
                    text, url, raw_sha = tx, u, hashlib.sha256(resp.content).hexdigest(); break
            if text is None:
                skipped_noeng += 1; fails.append((celex, "no usable English xhtml")); continue
            court_letter = mm.group(2)[0]; yr = mm.group(1)[2:]
            docket = f"{court_letter}-{int(mm.group(3))}/{yr}"
            cm = matcher.match("EU", COURT[court_letter], source_name=SRC, discriminator=court_letter)
            sf = f"cellar_sparql_{y}-{m:02d}"
            base = lambda kind, rid: common_row(kind, source_name=SRC, source_type="cjeu_cellar_sparql_rest", rec_id=rid, country_iso="EU", level="national",
                                                juris_raw="EU", url=url, phase="phaseA", source_file=sf, licence=LICENCE, licence_class="unknown")  # no verified licence text => unknown (not "open")
            dec = base("decision", celex)
            dec.update(court_entity_key=cm["court_entity_key"], court_key_provisional=cm["court_key_provisional"], court_match_status=cm["court_match_status"],
                       court_name_raw=COURT[court_letter], docket_number=docket, decision_date=d["date"], ecli=d["ecli"] if d["ecli"] and cs.RE_ECLI.match(d["ecli"]) else None,
                       canonical_key=(d["ecli"] or None), decision_type="judgment", language="en", opinion_count=1, restricted_ai_training=True, ocr=False, text_sha256=cs.text_sha256(text),
                       parties_redaction_status="unknown",
                       metadata_json={"terms": TERMS, "extras": {"celex": celex}, "courts_dataset_revision": cs.COURTS_DATASET_REVISION, **cm["meta"], "cellar_work_manifestations": d["ms"][:3]})
            op = base("opinion", celex + "#lead")
            op.update(decision_id=dec["id"], opinion_type="judgment", text=text, text_format="xhtml", ocr=False, text_backend="bs4-html.parser",
                      text_sha256=cs.text_sha256(text), restricted_ai_training=True, parties_redaction_status="unknown", language="en",
                      metadata_json={"terms": TERMS, "source_sha256": raw_sha, "extras": {"celex": celex}})
            if not out.add_pair(dec, op): fails.append(f"{celex}: rejected row (see rejected_rows.jsonl)"); continue
            out.seen.add(celex); n_done += 1
            if out.full():
                for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
            if n_done % 100 == 0:
                write_state(SRC, {"rows": n_done, "cap": CAP, "last_month": f"{y}-{m:02d}", "http_requests": f.n, "fails": len(fails)})
                print(now_la(), f"progress {n_done}/{CAP} month={y}-{m:02d} reqs={f.n} fails={len(fails)} elapsed={time.time()-t0:.0f}s", flush=True)
    for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
    up = dump_unmatched(SRC, matcher)
    summary = write_summary(SRC, fails=fails[:50], n_fails=len(fails), http_requests=f.n, rows_this_run=out.rows, shards_this_run=out.shards, bytes_this_run=out.bytes, court_match_stats_this_run=matcher.stats, unmatched_file=up, end_gate=preflight("end"), finished_la=now_la())
    print(json.dumps(summary, indent=1), flush=True)

if __name__ == "__main__":
    try:
        main()
    except StopJob as e:
        print(now_la(), str(e), flush=True); sys.exit(3)

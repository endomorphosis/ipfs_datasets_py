"""Job 2: NL Rechtspraak Open Data (ECLI index -> content XML). Bounded sample: PER_YEAR uitspraken for each year 2024..2013."""
import sys, re, hashlib, time, datetime
import xml.etree.ElementTree as ET
from cl_common import *
import r6_rules

PER_WIN = int(sys.argv[1]) if len(sys.argv) > 1 else 10  # per half-month window
YEARS = list(range(int(sys.argv[2]) if len(sys.argv) > 2 else 2024, int(sys.argv[3]) if len(sys.argv) > 3 else 2012, -1))
SRC = "nl_rechtspraak"
IDX = "https://data.rechtspraak.nl/uitspraken/zoeken"
CONTENT = "https://data.rechtspraak.nl/uitspraken/content"
LICENCE = "CC0-1.0 / Publiek domein (Raad voor de Rechtspraak, via data.overheid.nl dataset 'uitspraken-rechtspraak-nl')"
TERMS = {"basis": "data.overheid.nl dataset 'Uitspraken Rechtspraak.nl' lists licence 'Publiek domein' and format 'XML CC-0 (1.0)', owner Raad voor de Rechtspraak; "
                  "no AI-training/TDM reservation found there. Judgments are published pseudonymised by the Raad. Site asks for <=10 req/s (we use ~1/s).",
         "evidence_url": ["https://data.overheid.nl/dataset/uitspraken-rechtspraak-nl", "https://www.rechtspraak.nl/Uitspraken/Paginas/Open-Data.aspx"],
         "checked": "2026-10-29", "pending_legal_review": False}
NS = {"atom": "http://www.w3.org/2005/Atom", "dcterms": "http://purl.org/dc/terms/", "psi": "http://psi.rechtspraak.nl/",
      "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}
BLOCK = {"para", "title", "nr", "parablock", "section", "li", "listitem", "paragroup", "table", "row"}

def local(tag): return tag.rsplit("}", 1)[-1]

def to_text(el, out):
    if el.text: out.append(el.text)
    for ch in el:
        to_text(ch, out)
        if ch.tail: out.append(ch.tail)
    if local(el.tag) in BLOCK: out.append("\n")

def body_text(root):
    for name in ("uitspraak", "conclusie"):
        for el in root.iter():
            if local(el.tag) == name:
                out = []; to_text(el, out)
                t = re.sub(r"[ \t\r\f\v\u00a0]+", " ", "".join(out))
                t = re.sub(r" ?\n ?", "\n", t); t = re.sub(r"\n{3,}", "\n\n", t).strip()
                return name, t
    return None, ""

def level_for(court):
    c = court.lower()
    return ("regional", 6) if ("rechtbank" in c or "gerechtshof" in c) else ("national", 2)

def sensitivity(subjects):
    s = " ".join(subjects).lower(); fl = []
    if "vreemdelingen" in s: fl.append("immigration")
    if "strafrecht" in s: fl.append("criminal")
    if "personen- en familierecht" in s or "familie" in s or "jeugd" in s: fl.append("family")
    if "belasting" in s: fl.append("tax")
    return fl

def main():
    print(now_la(), "start", preflight("start"), flush=True)
    f = Fetcher(1.0); out = SourceOut(SRC, max_rows=500); matcher = CourtMatcher()
    n_done = len(out.seen); fails = []; t0 = time.time()
    print("resume: already have", n_done, flush=True)
    import calendar
    wins = [(yr, mo, h) for yr in YEARS for mo in range(1, 13) for h in (1, 2)]
    for yr, mo, h in wins:
        last = calendar.monthrange(yr, mo)[1]
        d0, d1 = (f"{yr}-{mo:02d}-01", f"{yr}-{mo:02d}-15") if h == 1 else (f"{yr}-{mo:02d}-16", f"{yr}-{mo:02d}-{last}")
        r = f.get(IDX, params={"type": "Uitspraak", "max": PER_WIN + 10, "from": 0, "return": "DOC", "date": [d0, d1]})
        feed = ET.fromstring(r.content)
        eclis = [e.findtext("atom:id", namespaces=NS) for e in feed.findall("atom:entry", NS)]
        got = 0
        for ecli in eclis:
            if got >= PER_WIN: break
            if not ecli or ecli in out.seen: continue
            try:
                resp = f.get(CONTENT, params={"id": ecli})
            except RobotsDenied as e:
                fails.append((ecli, f"robots {e}")); continue
            except requests.RequestException as e:
                fails.append((ecli, repr(e)[:150])); continue
            if resp is None:
                fails.append((ecli, "404")); continue
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as e:
                fails.append((ecli, f"xml {e}")); continue
            kind, text = body_text(root)
            if len(text) < 200:
                fails.append((ecli, "no/short body")); continue
            d = root.find(".//rdf:Description", {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"})
            g = lambda tag: (d.findtext(tag, namespaces=NS) or "").strip() or None
            court = g("dcterms:creator")   # None when absent: unnamed-court key path, court_name_raw NULL
            date = g("dcterms:date") or g("dcterms:issued")
            if date and not cs.RE_DATE.match(date): date = None
            subjects = [(s.text or "").strip() for s in d.findall("dcterms:subject", NS)]
            proc = [(s.text or "").strip() for s in d.findall("psi:procedure", NS)]
            lvl, _ = level_for(court or "")
            docket = g("psi:zaaknummer")
            if docket and cs.RE_CASE_NAME_VALUE.search(docket): docket = None   # docket looked like a case name: not stored
            iso = r6_rules.nl_territory(court) or "NL"   # r6: Aruba/Curaçao/Sint Maarten courts -> AW/CW/SX (joint courts stay NL)
            cm = matcher.match(iso, court, source_name=SRC, discriminator=ecli.split(":")[2] if ecli.count(":") >= 2 else None)
            url = f"{CONTENT}?id={ecli}"
            base = lambda k, rid: common_row(k, source_name=SRC, source_type="nl_rechtspraak_api", rec_id=rid, country_iso=iso, level=lvl, juris_raw="NL",
                                             url=url, phase="phaseA", source_file=f"rechtspraak_index_{yr}-{mo:02d}-h{h}", licence=LICENCE, licence_class="open")
            dec = base("decision", ecli)
            dec.update(court_entity_key=cm["court_entity_key"], court_key_provisional=cm["court_key_provisional"], court_match_status=cm["court_match_status"],
                       court_name_raw=court, docket_number=docket, decision_date=date, ecli=ecli if cs.RE_ECLI.match(ecli) else None, canonical_key=ecli,
                       decision_type={"uitspraak": "judgment", "conclusie": "advocate_general_opinion"}[kind], language=(g("dcterms:language") or "nl"),
                       opinion_count=1, restricted_ai_training=False, ocr=False, text_sha256=cs.text_sha256(text), parties_redaction_status="source_pseudonymised",
                       sensitivity_flags=sensitivity(subjects) or None,
                       metadata_json={"terms": TERMS, "subjects": subjects, "procedure": proc, "seat": g("dcterms:spatial"), "publisher": g("dcterms:publisher"),
                                      "courts_dataset_revision": cs.COURTS_DATASET_REVISION, **cm["meta"]})
            op = base("opinion", ecli + "#lead")
            op.update(decision_id=dec["id"], opinion_type="judgment" if kind == "uitspraak" else "other", text=text, text_format="xml", ocr=False,
                      text_backend="xml.etree", text_sha256=cs.text_sha256(text), restricted_ai_training=False, parties_redaction_status="source_pseudonymised",
                      language=dec["language"], metadata_json={"terms": TERMS, "source_sha256": hashlib.sha256(resp.content).hexdigest()})
            if not out.add_pair(dec, op):
                fails.append((ecli, "rejected by row validation (see rejected_rows.jsonl)")); continue
            out.seen.add(ecli); n_done += 1; got += 1
            if out.full():
                for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
            if n_done % 100 == 0:
                write_state(SRC, {"rows": n_done, "window": f"{yr}-{mo:02d}-h{h}", "per_win": PER_WIN, "http_requests": f.n, "fails": len(fails)})
                print(now_la(), f"progress {n_done} win={yr}-{mo:02d}-h{h} reqs={f.n} fails={len(fails)} elapsed={time.time()-t0:.0f}s", flush=True)
    for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
    up = dump_unmatched(SRC, matcher)
    summary = write_summary(SRC, fails=fails[:50], n_fails=len(fails), http_requests=f.n, rows_this_run=out.rows, shards_this_run=out.shards, bytes_this_run=out.bytes, court_match_stats_this_run=matcher.stats, unmatched_file=up, end_gate=preflight("end"), finished_la=now_la())
    print(json.dumps(summary, indent=1), flush=True)

if __name__ == "__main__":
    try:
        main()
    except StopJob as e:
        print(now_la(), str(e), flush=True); sys.exit(3)

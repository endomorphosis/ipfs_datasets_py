"""Job 3: Swiss court decisions via entscheidsuche.ch open API (_search.php, Elasticsearch). Stratified sample ~TOTAL rows over all non-upload courts.
Respects robots.txt (/hidden, /archiv not touched), docs/Blockliste.json, 1 req/1.5 s. No bger.ch direct access (TLS issue not bypassed)."""
import sys, re, random, time, math
from cl_common import *
import r6_rules

TOTAL = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
BASE_Q = int(sys.argv[2]) if len(sys.argv) > 2 else 12
SRC = "ch_entscheidsuche"; API = "https://entscheidsuche.ch/_search.php"; BLOCK = "https://entscheidsuche.ch/docs/Blockliste.json"
LICENCE = "No licence: Swiss court decisions are not protected by copyright (Art. 5 para 1 lit. c URG); entscheidsuche.ch states data may be freely used and reused, attribution requested (https://entscheidsuche.ch/dataUsage)"
TERMS = {"basis": "entscheidsuche.ch /dataUsage ('Die ... Daten stehen allen Interessierten zur freien Benutzung und Weiterbearbeitung zur Verfuegung'; please cite entscheidsuche.ch as source; voluntary donation for commercial use) and API description PDF "
                  "('You are free to use the API and the cases in any way you want'); decisions uncopyrighted under Art. 5(1)(c) URG. No AI/TDM reservation found; robots.txt allows /_search.php and /docs. "
                  "Anonymisation is done by the publishing courts and has NOT been verified per court (data-protection caveat).",
         "evidence_url": ["https://entscheidsuche.ch/dataUsage", "https://entscheidsuche.ch/pdf/EntscheidsucheAPI.pdf", "https://entscheidsuche.ch/robots.txt"],
         "checked": "2026-10-29", "pending_legal_review": True, "attribution": "entscheidsuche.ch", "excluded": "user uploads (*_UPL), Blockliste.json ids, /hidden, /archiv"}
DATE_RE = re.compile(r"\s\d{1,2}\.\d{1,2}\.\d{4}")

class PostFetcher(Fetcher):
    def post(self, url, payload, tries=3):
        last = None
        for i in range(tries):
            self.gate.enforce(url); self.n += 1
            try:
                r = self.s.post(url, json=payload, timeout=(10, 120))
            except requests.RequestException as e:
                last = repr(e); time.sleep(min(60, 5 * 2 ** i)); continue
            if r.status_code in (403, 429):
                self.blocked += 1
                if self.blocked >= 3: raise StopJob(f"STOP: {r.status_code} x3 (not bypassing)")
                time.sleep(min(300, int(r.headers.get("Retry-After", "30") or 30))); last = f"HTTP {r.status_code}"; continue
            if r.status_code >= 500: last = f"HTTP {r.status_code}"; time.sleep(min(60, 5 * 2 ** i)); continue
            r.raise_for_status(); self.blocked = 0; return r.json()
        raise requests.RequestException(f"giving up: {last}")

def court_name(src, lang):
    t = src.get("title") or {}
    title = t.get(lang) or t.get("de") or next(iter(t.values()), None)
    m = (src.get("meta") or {}); meta = m.get(lang) or m.get("de") or next(iter(m.values()), None)
    nm = None
    if title:
        mm = DATE_RE.search(title); nm = (title[:mm.start()] if mm else None)
    nm = (nm or meta or "").strip() or None
    if nm and cs.RE_CASE_NAME_VALUE.search(nm): nm = (meta or "").strip() or None   # never keep a case-name-like string
    if nm and cs.RE_CASE_NAME_VALUE.search(nm): nm = None
    return nm

def main():
    print(now_la(), "start", preflight("start"), flush=True)
    f = PostFetcher(1.5); out = SourceOut(SRC, max_rows=500); matcher = CourtMatcher(); fails = []; skipped = {}; t0 = time.time()
    bl = f.get(BLOCK); blocked = set(x for v in json.loads(bl.content).values() for x in v) if bl is not None else set()
    print("blocklist ids", len(blocked), flush=True)
    agg = f.post(API, {"size": 0, "aggs": {"h": {"terms": {"field": "hierarchy", "size": 700}}}})
    courts = sorted((b["key"], b["doc_count"]) for b in agg["aggregations"]["h"]["buckets"] if re.fullmatch(r"[A-Z]{2}_[A-Za-z]+", b["key"]) and not b["key"].endswith("_UPL"))
    quota = {c: min(n, BASE_Q) for c, n in courts}
    left = TOTAL - sum(quota.values()); big = [(c, n) for c, n in courts if n > BASE_Q]
    for _ in range(5):
        if left <= 0 or not big: break
        add = max(1, left // len(big))
        for c, n in big:
            a = min(add, n - quota[c], left)
            quota[c] += a; left -= a
        big = [(c, n) for c, n in big if quota[c] < n]
    print("courts", len(courts), "planned", sum(quota.values()), flush=True)
    n_done = len(out.seen)
    print("resume: already have", n_done, flush=True)
    for court, cnt in courts:
        want = quota[court]; got = 0; frm = 0
        have = sum(1 for s in out.seen if s.startswith(court + "_"))
        if have >= want: continue
        while got + have < want and frm < cnt:
            size = min(10, want - got - have + 3)   # +3 headroom for skips
            q = {"size": size, "from": frm, "_source": ["date", "hierarchy", "language", "title", "meta", "reference", "attachment", "canton", "id"],
                 "query": {"function_score": {"query": {"term": {"hierarchy": court}}, "random_score": {"seed": 20261029}}}}
            try:
                res = f.post(API, q)
            except requests.RequestException as e:
                fails.append((court, repr(e)[:150])); break
            hits = res["hits"]["hits"]
            if not hits: break
            frm += len(hits)
            for h in hits:
                if got + have >= want: break
                s = h["_source"]; rid = s.get("id") or h["_id"]
                if rid in out.seen: continue
                if rid in blocked: skipped["blocklist"] = skipped.get("blocklist", 0) + 1; continue
                att = s.get("attachment") or {}
                text = (att.get("content") or "").strip()
                text = re.sub(r"[ \t\r\f\v\u00a0]+", " ", text); text = re.sub(r" ?\n ?", "\n", text); text = re.sub(r"\n{3,}", "\n\n", text).strip()
                if len(text) < 200: skipped["no_short_text"] = skipped.get("no_short_text", 0) + 1; continue
                lang = att.get("language") or s.get("language")
                lang = lang if lang in cs.ISO639_1 else None
                date = s.get("date"); date = date if date and cs.RE_DATE.match(date) else None
                hier = s.get("hierarchy") or []; canton = (s.get("canton") or rid[:2])
                federal = canton == "CH"
                admin1 = None if federal else f"CH-{canton}"
                nm = court_name(s, lang or "de")
                ref = (s.get("reference") or [None])[0]
                ref = ref if ref and not cs.RE_CASE_NAME_VALUE.search(ref) else None
                cm = matcher.match("CH", nm, admin1=admin1, source_name=SRC, discriminator="_".join(rid.split("_")[:2]))
                url = att.get("content_url") or f"https://entscheidsuche.ch/docs/{court}/{rid}"
                base = lambda k, r_: common_row(k, source_name=SRC, source_type="entscheidsuche_api", rec_id=r_, country_iso="CH", level="national" if federal else "state",
                                                juris_raw=canton, admin1=admin1, url=url, phase="phaseA", source_file=f"entscheidsuche_{court}", licence=LICENCE, licence_class="open")
                dec = base("decision", rid)
                dec.update(court_entity_key=cm["court_entity_key"], court_key_provisional=cm["court_key_provisional"], court_match_status=cm["court_match_status"],
                           court_name_raw=nm, docket_number=ref, decision_date=date, canonical_key=None, decision_type="other", language=lang, opinion_count=1,
                           restricted_ai_training=True, ocr=False, text_sha256=cs.text_sha256(text), parties_redaction_status="unknown",
                           metadata_json={"terms": TERMS, "hierarchy": hier, "content_type": att.get("content_type"), "courts_dataset_revision": cs.COURTS_DATASET_REVISION, **cm["meta"]})
                op = base("opinion", rid + "#lead")
                op.update(decision_id=dec["id"], opinion_type="other", text=text, text_format="plain", ocr=False, text_backend="entscheidsuche_extracted", text_sha256=cs.text_sha256(text),
                          restricted_ai_training=True, parties_redaction_status="unknown", language=lang, metadata_json={"terms": TERMS})
                r6_rules.apply_ch_date(dec, text)   # r6: Jan-1 placeholder dates -> year precision
                if not out.add_pair(dec, op):
                    fails.append((rid, "rejected by row validation (see rejected_rows.jsonl)")); continue
                out.seen.add(rid); got += 1; n_done += 1
                if out.full():
                    for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
                if n_done % 100 == 0:
                    preflight("ch progress")
                    write_state(SRC, {"rows": n_done, "court": court, "http_requests": f.n, "fails": len(fails)})
                    print(now_la(), f"progress {n_done} court={court} reqs={f.n} fails={len(fails)} elapsed={time.time()-t0:.0f}s", flush=True)
    for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
    up = dump_unmatched(SRC, matcher)
    summary = write_summary(SRC, courts=len(courts), blocklist_ids=len(blocked), fails=fails[:50], n_fails=len(fails), skipped_this_run=skipped, http_requests=f.n, rows_this_run=out.rows, shards_this_run=out.shards, bytes_this_run=out.bytes, court_match_stats_this_run=matcher.stats, unmatched_file=up, end_gate=preflight("end"), finished_la=now_la())
    print(json.dumps(summary, indent=1), flush=True)

if __name__ == "__main__":
    try: main()
    except StopJob as e: print(now_la(), str(e), flush=True); sys.exit(3)

#!/usr/bin/env python3
"""Spain: provincial / autonomous gazettes that are network-blocked from the box (TLS failure, connection error,
HTTP 500, HTTP 403 for Málaga & SC Tenerife), from web archives -> municipal ordinances/regulations in
staging/asia_latam/ES/.  --set robots: the 12 robots.txt-disallowed BOPs (Toledo, Las Palmas, Girona, Tarragona, A Coruña, Pontevedra,
Barcelona, Alicante, Illes Balears, Álava, Bizkaia Bao_bob, Huelva) from the archive only, archived_robots_disallowed.
Ourense (portalapi getDetalle) is never touched; sedelectronica.es is a separate job (sede_arch.py).

  es_arch.py [--gazettes zamora,sevilla,...] [--max-fetch N] [--rediscover]

Discovery: Wayback (+ CC when cached) prefix listing of each gazette host, PDFs only, small records (per-anuncio PDFs;
whole-issue PDFs >--max-kb are skipped). Each PDF is fetched from the archive, the anuncio header is checked with the
live es_bop.py criteria (ordenanza/reglamento/normas reguladoras, not padrón/convocatoria/...) and the issuing
ayuntamiento is resolved with es/es_places.Resolver (name + province -> INE P772 -> wd:Q).
"""
from __future__ import annotations

import argparse, csv, hashlib, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "es"))
from arch_common import wb_deferred, WBDeferred, listing_failed  # noqa: E402,F401
from arch_common import STAGE, STOP, ArchiveError, ArchiveFetcher, CheckedFetcher, Capture, State, append_csv, pdf_text, provenance_fields  # noqa
from es_places import Resolver  # noqa: E402

JOB = "ES_bop_archive"  # --set robots -> "ES_bop_archive_robots"
log = logging.getLogger(JOB)
TARGET_RE = re.compile(r"\b(ordenan[cz]as?|ordenança|ordenantza|normas? reguladoras?|normes? reguladores?|regulamento municipal|"
                       r"reglament(?:o|s)? (?:municipal|regulador|org[aá]nico|del servicio|de r[eé]gimen interno|de funcionamiento|de uso|"
                       r"de participaci[oó]n|de honores|del cementerio|de la (?:piscina|biblioteca|escuela|residencia))|"
                       r"reglament (?:municipal|org[aà]nic|regulador))", re.I)
EXCLUDE_RE = re.compile(r"\b(padr[oó]n|padr[oó]|convocatoria|bases (espec|gener)|oferta de empleo|licitaci|contrataci|subvenci)", re.I)
ISSUER_RE = re.compile(r"^\s*((?:excmo\.?\s+|ilmo\.?\s+|m\.\s*i\.\s+)*(?:ayuntamiento|ajuntament|concello|concejo|udala)\s+(?:de\s+|d'|del\s+|dels\s+|da\s+|do\s+)?[^\n]{2,60}|[^\n]{2,60}ko\s+udala)\s*$", re.I | re.M)
BLOCKED_ROBOTS = {"toledo", "las palmas", "girona", "tarragona", "a coruña", "pontevedra", "barcelona", "alicante",
                  "illes balears", "álava", "araba"}


# robots.txt-disallowed BOPs: archived copies allowed (Benjamin via coordinator 2026-10-10), NEVER live-fetched.
# host = where the bulletin PDFs live; flt = Wayback "original:" regex restricting a shared host to the BOP paths.
ROBOTS_SPEC = {
    "acoruna": dict(host="bop.dacoruna.gal"), "pontevedra": dict(host="boppo.depo.gal"),
    "toledo": dict(host="bop.diputoledo.es"), "laspalmas": dict(host="www.boplaspalmas.net"),
    "barcelona": dict(host="bop.diba.cat"), "huelva": dict(host="s2.diphuelva.es"),
    "alava": dict(host="www.araba.eus", flt="(?i).*botha.*"),
    "bizkaia": dict(host="www.bizkaia.eus", flt="(?i).*bao_bob.*"),
    "girona": dict(host="www.ddgi.cat", flt="(?i).*/bop/.*"),
    "tarragona": dict(host="www.dipta.cat", flt="(?i).*/(ebop|bopt)/.*"),
    "alicante": dict(host="www.dip-alicante.es", flt="(?i).*/bop/.*"),
    "boib": dict(host="www.caib.es", flt="(?i).*/eboib.*"),
}
SET = {"set": "blocked"}


def gazettes():
    out = {}
    for r in csv.DictReader(open(STAGE / "_bop_registry_es.csv", encoding="utf-8")):
        want = ("robots_disallow",) if SET["set"] == "robots" else ("unreachable", "blocked_http_403")
        if r["status"] not in want:
            continue
        name = r["gazette"]
        if "sedelectronica" in r["host"] or "depourense" in r["host"]:  # Ourense: never touch getDetalle
            continue
        if SET["set"] != "robots" and any(b in name.lower() for b in BLOCKED_ROBOTS):
            continue
        import unicodedata
        nm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        key = re.sub(r"[^a-z]", "", nm.split("(")[-1].split(")")[0] if "(" in nm else nm)
        u = urlparse(r["url"])
        prefix = u.netloc + (u.path if u.path not in ("", "/") else "/")
        out[key] = {"key": key, "name": name, "prov": r["province_code"].zfill(2), "prefix": prefix, "host": u.netloc,
                    "status": r["status"], "reason": r["reason"]}
        if SET["set"] == "robots":
            sp = ROBOTS_SPEC.get(key)
            if not sp:
                logging.getLogger(JOB).warning("robots gazette without spec: %s (%s) -> skipped", key, name)
                del out[key]
                continue
            out[key].update(host=sp["host"], prefix=sp["host"] + "/", flt=sp.get("flt"))
    return out


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB + ("_robots" if SET["set"] == "robots" else ""), "ES", batch_prefix="archive", chunk=100)
        self.fx = CheckedFetcher(cc_crawls=4)
        self.G = gazettes()
        self.res = Resolver()

    def discover(self):
        cand, per = [], {}
        for g in self.a.gazettes or sorted(self.G):
            G = self.G[g]
            caps = []
            if self.a.cc:
                caps += self.fx.cc_captures(G["host"] + "/", "prefix", filters=["mime:application/pdf"])
            flt = ["mimetype:application/pdf"]
            path = G["prefix"][len(G["host"]):].strip("/")
            if G.get("flt"):
                flt.append("original:" + G["flt"])
            elif path:  # gazette lives on a shared host (sede.asturias.es/bopa, web.larioja.org/bor, dipsegovia.es/bop)
                flt.append("original:.*" + re.split(r"[-/]", path)[0] + ".*")
            try:
                caps += self.fx.wb_captures(G["host"] + "/", "prefix", collapse="urlkey", max_rows=300000, filters=flt)
            except ArchiveError as e:
                listing_failed(e, g)
                per[g] = {"error": str(e)[:100]}
                continue
            keep = [c for c in caps if c.status in (200, None) and (c.length or 0) < self.a.max_kb * 1024
                    and "getdetalle" not in c.original_url.lower()]
            per[g] = {"captures": len(caps), "small_pdfs": len(keep)}
            log.info("%s: pdf captures=%d small=%d", g, len(caps), len(keep))
            seen = set()
            for c in sorted(keep, key=lambda c: c.timestamp, reverse=True):
                k = g + "|" + re.sub(r"^https?://(www\.)?", "", c.original_url.split("?")[0].lower()).replace(":80/", "/")
                if k in seen:
                    continue
                seen.add(k)
                cand.append({"key": k, "g": g, "ts": c.timestamp, "caps": [c.to_dict()]})
        # interleave gazettes, newest first within each
        by = {}
        for r in cand:
            by.setdefault(r["g"], []).append(r)
        order, i = [], 0
        while any(i < len(v) for v in by.values()):
            for v in by.values():
                if i < len(v):
                    order.append(v[i])
            i += 1
        with (self.st.dir / "candidates.jsonl.tmp").open("w") as f:
            for r in order:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(self.st.dir / "candidates.jsonl.tmp", self.st.dir / "candidates.jsonl")
        (self.st.dir / "discovery.json").write_text(json.dumps(per, indent=1, ensure_ascii=False))
        return order

    HEAD_RE = re.compile(r"^\s*(?:(?:EXCMO|EXCMA|ILMO|ILMA|M\.\s*I)\.?\s+)?(AYUNTAMIENTO|AJUNTAMENT|CONCELLO|CONCEJO|UDALA|"
                         r"MANCOMUNIDAD|MANCOMUNITAT|DIPUTACI[OÓ]N|COMARCA|CONSORCIO|JUNTA|MINISTERIO|DELEGACI[OÓ]N|"
                         r"SUBDELEGACI[OÓ]N|CONFEDERACI[OÓ]N|JUZGADO|TRIBUNAL|SERVICIO|CONSEJER[IÍ]A|ENTIDAD LOCAL|[A-ZÁÉÍÓÚÑ ]+KO UDALA)\b[^\n]*$",
                         re.M)

    def segments(self, text):
        """Split a gazette PDF (single anuncio or whole issue) at upper-case issuer headings."""
        heads = [m for m in self.HEAD_RE.finditer(text) if m.group(0).strip() == m.group(0).strip().upper()]
        segs = []
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            segs.append((m.group(0).strip(), text[m.start():end]))
        return segs

    def build(self, r, doc):
        G = self.G[r["g"]]
        if doc.body[:5] != b"%PDF-":
            return [], "not_pdf"
        text = pdf_text(doc.body)
        if len(text) < 300:
            return [], "no_text"
        out, why = [], "no_municipal_ordinance"
        path = urlparse(doc.original_url).path
        occ = {}
        for heading, seg in self.segments(text):
            if not re.match(r"(?i)\s*(?:(?:excmo|excma|ilmo|ilma|m\.\s*i)\.?\s+)?(ayuntamiento|ajuntament|concello|concejo|udala)|.+ko udala", heading):
                continue
            body = re.sub(r"\n\s*BOLET[IÍ]N OFICIAL DE LA PROVINCIA[^\n]*\n[^\n]*P[aá]g\.\s*\d+[^\n]*", "\n", seg)
            lines = [l.strip() for l in body[:1500].split("\n") if l.strip()]
            if not TARGET_RE.search(re.sub(r"-\s+(?=[a-záéíóúñ])", "", " ".join(lines[1:15]))) or EXCLUDE_RE.search(" ".join(lines[1:6])):
                continue
            issuer = re.sub(r"\s{2,}.*$", "", heading).strip()
            if re.fullmatch(r"(?i)(ayuntamiento|ajuntament|concello|concejo)s?", issuer):  # name on the next line
                nxt = next((l for l in lines[1:3] if l), "")
                if not nxt or len(nxt) > 60:
                    continue
                issuer = nxt
            place = self.res.resolve(issuer.title(), G["prov"]) or self.res.resolve(issuer, G["prov"])
            if not place or not place.get("place_id"):
                append_csv(STAGE / "_unmatched_es_bop_archive.csv", ["gazette", "issuer", "province", "url", "why", "at"],
                           [r["g"], issuer, G["prov"], doc.original_url, (place or {}).get("match", "no_match"),
                            time.strftime("%Y-%m-%d %H:%M")])
                why = "unmatched"
                continue
            occ[issuer] = occ.get(issuer, 0) + 1
            flat = re.sub(r"-\s+(?=[a-záéíóúñ])", "", " ".join(lines[1:15]))
            mt = TARGET_RE.search(flat)
            title = flat[max(0, mt.start() - 60): mt.end() + 140].strip()[:500] if mt else issuer
            dt = "ordinance" if re.search(r"ordenan[cz]a|ordenança|ordenantza", title, re.I) else "regulation"
            seg_t = body.strip()
            rec = {"place_id": place["place_id"], "country_code": "ES",
                   "doc_id": f"es_bop_{r['g']}_arch:" + hashlib.sha1(f"{path.lower()}|{issuer.lower()}|{occ[issuer]}".encode()).hexdigest()[:16],
                   "source_platform": f"es_bop_{r['g']}", "source_url": doc.original_url, "doc_type": dt, "language": "es",
                   "html_title": f"{issuer.title()}: {title}"[:600], "title_native": title, "in_force": None, "consolidated": False,
                   "content_format": "pdf_text", "text": seg_t, "retrieved_at": doc.fetched_at,
                   "place_name": place.get("place_name"), "qid": place.get("qid"), "admin_level": place.get("admin_level") or "municipality",
                   "platform": f"es_bop_{r['g']}", "platform_place_id": place.get("ine"), "ine_code": place.get("ine"),
                   "issuer_name": issuer, "province_code": G["prov"], "match": place.get("match"),
                   "segment_of_pdf": True, "source_policy": "archived_robots_disallowed" if G["status"] == "robots_disallow"
                   else "network_blocked_archive_fallback",
                   "block_reason": f"{G['status']}: {G['reason']}"[:200],
                   "content_sha256": hashlib.sha256(seg_t.encode()).hexdigest()}
            d = re.search(r"\b(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+((?:19|20)\d\d)", text[:400], re.I)
            M = {m: i + 1 for i, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}
            if d and d.group(2).lower() in M:
                rec["published_date"] = f"{d.group(3)}-{M[d.group(2).lower()]:02d}-{int(d.group(1)):02d}"
            rec.update(provenance_fields(doc))
            out.append({k: v for k, v in rec.items() if v is not None or k == "in_force"})
        return out, ("ok" if out else why)

    def run(self):
        cp = self.st.dir / "candidates.jsonl"
        cands = self.discover() if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
        self.st.stats["candidates"] = len(cands)
        self.st.save(self.fx)
        n = 0
        for r in cands:
            if STOP["flag"] or (self.a.max_fetch and n >= self.a.max_fetch):
                break
            if r["key"] in self.st.done:
                continue
            n += 1
            if r["key"] in self.st.deferred:
                continue
            exc = None
            try:
                doc = self.fx.fetch_best([Capture(**c) for c in r["caps"]], max_tries=2)
            except ArchiveError as e:
                doc, exc = None, e
            if wb_deferred(self.fx, doc, exc):
                self.st.defer(r["key"]); continue
            if doc is None:
                self.st.stats["no_good_capture"] += 1; self.st.mark(r["key"], "no_good_capture"); continue
            try:
                recs, why = self.build(r, doc)
            except Exception as e:
                log.exception("build %s", r["key"]); recs, why = [], f"error:{type(e).__name__}"
            if not recs:
                self.st.stats[why] += 1; self.st.mark(r["key"], why); continue
            self.st.stats["pdfs_with_docs"] += 1
            for i, rec in enumerate(recs):
                self.st.add(r["key"] + (f"#{i}" if i else ""), rec)
            if len(recs) > 1:  # mark the pdf key itself done once all its segments are staged/pending
                pass
            self.st.maybe_flush(1800)
            if n % 25 == 0:
                self.st.save(self.fx)
                log.info("progress %d staged=%d %s", n, self.st.stats["staged"], dict(self.st.stats))
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gazettes", type=lambda s: s.split(","), default=None)
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--max-kb", type=int, default=600)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--cc", action="store_true")
    ap.add_argument("--set", choices=["blocked", "robots"], default="blocked",
                    help="blocked = network-blocked BOPs; robots = robots.txt-disallowed BOPs (archive only)")
    a = ap.parse_args()
    SET["set"] = a.set
    Job(a).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())

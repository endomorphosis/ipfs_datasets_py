#!/usr/bin/env python3
"""Currency check of the pre-2021 NSTAR rows + replacement texts from the kommuner's own websites.

NSTAR's public status page lists the regulativ each kommune last *reported*, which is not always the one in force: 26 of the NSTAR rows
were approved before 2021 (25 flagged 'baseret på et forældet paradigme'). Each was checked by hand on the kommune's website
(2026-10-17); the outcome is recorded in CURRENCY below and used by build_dk_municipal.py:
  replaced            - a newer adopted regulativ is published by the kommune as a born-digital PDF; the NSTAR row is dropped and a row
                        built from the kommune PDF takes its place (source_url = that PDF; the stale NSTAR id is kept in extras)
  superseded          - a newer regulativ exists but no born-digital PDF could be fetched; the NSTAR text is kept with
                        law_status='superseded' and superseded_by = the kommune page that documents the newer regulativ
  current             - the kommune website still publishes (or links NSTAR for) the same regulativ; kept as in_force
  unverified_current  - nothing newer found, but the kommune site does not confirm the NSTAR version either; kept, flagged
EXTRA lists kommune PDFs added for regulativer NSTAR cannot serve (Læsø erhverv: NSTAR's PDF render fails server-side).

Only born-digital PDFs are used (pdftotext; no OCR). robots.txt is checked per host; requests are 1.5 s apart; PDFs are streamed to text
and deleted. usage: collect_dk_kommune_pdfs.py [OUTDIR]   (default: dk_build) -> OUTDIR/kommune_texts.jsonl.gz
"""
import gzip, hashlib, json, os, re, subprocess, sys, tempfile, time, urllib.parse, urllib.robotparser
import requests

UA = "legal-corpora research collector (municipal regulations dataset; read-only, spaced requests)"
SLEEP = 1.5
CHECKED = "2026-10-17"

def R(url, note):  # replaced by a kommune-site PDF
    return dict(outcome="replaced", url=url, note=note)
def S(url, note):
    return dict(outcome="superseded", superseded_by=url, note=note)
def C(url, note):
    return dict(outcome="current", evidence_url=url, note=note)
def U(url, note):
    return dict(outcome="unverified_current", evidence_url=url, note=note)

# key: NSTAR document id of the pre-2021 row (as in the pack id dk-mun-<kode>-<id>)
CURRENCY = {
 "312":  S("https://www.htk.dk/p/Dokumenter%20Htk.dk/Driftsbyen/Husholdningaffald/H%C3%B8je-Taastrup-Kommunes-regulativ-for-husholdningsaffald-2022.pdf",
           "Høje-Taastrup husholdning: NSTAR has the 2011 regulativ; the kommune/HTK Forsyning publish the regulativ vedtaget 22-06-2021, gældende 01-01-2022 (it repeals a 2019 version). htk.dk answers HTTP 403 to this collector and no archive copy was available, so the newer text was not ingested."),
 "1691": S("https://ishoj.dk/media/u1hdy2vq/punkt_85_bilag_1_statusnotat_og_handleplan_ishoej_20232024.pdf",
           "Ishøj husholdning: NSTAR has the 2016 regulativ; Ishøj's statusnotat 2023/24 says the byråd adopted a new regulativ in August 2022 and an updated one in October 2023. ishoj.dk answers HTTP 403 to this collector, so the newer PDF was not fetched."),
 "1292": R("https://cdn.gribskov.dk/gribskovkommune/Media/638453817374341303/Regulativ%20for%20Husholdningsaffald.pdf",
           "Gribskov husholdning: NSTAR has the 20-12-2013 regulativ; the kommune publishes the regulativ vedtaget/i kraft 05-09-2023 that repeals it (with a transition clause for §§10-19)."),
 "1296": R("https://gribskov.dk/Media/638542289842231194/Gribskov%20Kommunes%20Regulativ%20for%20Erhvervsaffald.pdf",
           "Gribskov erhverv: NSTAR has the 2013 regulativ; the kommune publishes the regulativ for erhvervsaffald vedtaget/i kraft 05-09-2023."),
 "1443": R("https://halsnaes.dk/media/15219/Bilag%201%20Halsn%C3%A6s%20Kommunes%20regulativ%20for%20husholdningssaffald%20juni%202023.pdf",
           "Halsnæs husholdning: NSTAR has the 2014 regulativ; the kommune publishes the regulativ vedtaget/i kraft 22-06-2023 (which itself repeals a 2022 version)."),
 "1382": R("https://halsnaes.dk/media/15220/Bilag%202%20Halsn%C3%A6s%20Kommunes%20regulativ%20for%20erhvervsaffalds%20juni%20%202023.pdf",
           "Halsnæs erhverv: NSTAR has the 2014 regulativ; the kommune publishes the regulativ for erhvervsaffald vedtaget/i kraft 22-06-2023."),
 "2021": R("https://aabenraa.dk/media/gszfgb2r/regulativ-for-husholdningsaffald.pdf",
           "Aabenraa husholdning: NSTAR has the 2018 regulativ; aabenraa.dk publishes the regulativ vedtaget 03-12-2025, gældende 01-01-2026 (it repeals the 01-01-2023 one)."),
 "2206": R("https://aabenraa.dk/media/lz2fnt4m/wt-regulativ-for-erhvervsaffald.pdf",
           "Aabenraa erhverv: NSTAR has the 2020 regulativ; aabenraa.dk ('Affald fra erhverv', Dokumenter) publishes the regulativ for erhvervsaffald gældende fra 01-01-2023. The PDF's metadata title still reads 'Udkast til ...', but the text is the adopted version (Gældende fra / træder i kraft 01-01-2023) and it is the one the kommune links as its regulativ."),
 "1007": R("https://www.dragoer.dk/media/xq4mvd0r/regulativ-for-erhvervsaffald_2023.pdf",
           "Dragør erhverv: NSTAR has the 2012 regulativ; dragoer.dk ('Affaldsplan, regler og regulativer') publishes 'Regulativ for erhvervsaffald 2023'."),
 "1747": S("https://www.svendborg.dk/erhverv/miljoe-landbrug-og-vand/affald-fra-erhverv/",
           "Svendborg erhverv: NSTAR has the 2016 regulativ; svendborg.dk says the regulativ for erhvervsaffald was updated and adopted in May 2024. The page's PDF link is script-rendered and could not be resolved by this collector."),
 "1903": C("https://ballerup.dk/sites/default/files/2021-11/Regulativ%20for%20Erhvervsaffald%202018.pdf", "Ballerup erhverv: ballerup.dk still hosts the 2018 regulativ; nothing newer found."),
 "2171": C("https://www.bronderslev.dk/p/Borger/Regulativ-for-husholdningsaffald-2018.pdf", "Brønderslev husholdning: the kommune still publishes the 2018 regulativ (bronderslev.dk + plan viewer); only the erhverv regulativ was renewed (2025)."),
 "920":  C("https://www.fmk.dk/erhverv/miljoe-industri-og-landbrug/affald-fra-erhverv/regulativ-for-erhvervsaffald/", "Faaborg-Midtfyn erhverv: fmk.dk (updated 21-05-2026) still shows the 2012 regulativ in force and says a revision is under way."),
 "1502": C("https://fanoe.dk/media/it2dfjn3/regulativplusforpluserhvervsaffaldplus2016.pdf", "Fanø erhverv: fanoe.dk hosts the regulativ i kraft 01-01-2016 (vedtaget 18-05-2015), the same as NSTAR."),
 "1177": C("https://www.frederikssund.dk/Borger/Bolig--byggeri/affald/lovgivning-regler-og-vejledninger", "Frederikssund erhverv: the kommune's regulativ page links NSTAR for the erhverv regulativ (this 2010 one); nothing newer found."),
 "2149": C("https://www.furesoe.dk/borger/affald-og-genbrug/affaldsgebyrer-og-regulativer/affaldsregulativer", "Furesø erhverv: furesoe.dk lists one regulativ for erhvervsaffald (file 'gældende fra 2019'); nothing newer found."),
 "991":  C("https://www.glostrup.dk/media/9043/affaldsregulativ-erhvervsaffald.pdf", "Glostrup erhverv: glostrup.dk links the regulativ gældende fra 15-03-2012, the same as NSTAR."),
 "2232": C("https://www.htk.dk/erhvervsliv/erhvervsaffald/regulativ-for-erhvervsaffald", "Høje-Taastrup erhverv: htk.dk refers to NSTAR for the regulativ for erhvervsaffald; nothing newer found."),
 "1753": C("https://www.jammerbugt.dk/media/3uwbzrum/affaldsregulativ-for-erhvervsaffald-21-december-2016.pdf", "Jammerbugt erhverv: jammerbugt.dk (updated 13-04-2026) links the regulativ of 21 December 2016, the same as NSTAR."),
 "1754": C("https://lejre.dk/erhverv/erhvervsaffald/erhvervsaffald/regulativ-for-erhvervsaffald", "Lejre erhverv: lejre.dk refers to NSTAR ('vælg fanen Erhvervsaffald'); nothing newer found."),
 "1171": C("https://www.odsherred.dk/media/1jvptqwt/regulativ-for-erhvervsaffald-2013_0.pdf", "Odsherred erhverv: odsherred.dk links the 2013 regulativ for erhvervsaffald (next to a 2025 household one)."),
 "1882": C("https://rebild.dk/sites/default/files/2021-01/regulativ_for_erhvervsaffald_01-12-2017%20%281%29_0.pdf", "Rebild erhverv: rebild.dk links the regulativ i kraft 01-12-2017, the same as NSTAR."),
 "2449": C("https://solrod.dk/Media/638695032489345831/regulativ-for-erhvervsaffald-i-solroed-kommune.pdf", "Solrød erhverv: solrod.dk links the March 2020 regulativ (vedtaget 04-11-2019), the same generation as NSTAR."),
 "1702": C("https://www.vallensbaek.dk/Media/638763349316923897/vallensbaek_regulativ_for_erhvervsaffald_pr_01-06-2016.pdf", "Vallensbæk erhverv: vallensbaek.dk links the regulativ vedtaget 17-02-2016, the same as NSTAR."),
 "1796": U("https://frederikshavn.viewer.dkplan.niras.dk/plan/33", "Frederikshavn erhverv: the kommune's plan viewer has a 'Regulativ for erhvervsaffald' page but shows no date; nothing newer found."),
 "2188": U("https://ishoj.dk/borger/bolig/affald-og-genbrug/", "Ishøj erhverv: no newer regulativ for erhvervsaffald found; ishoj.dk answers HTTP 403 to this collector, so it could not be confirmed."),
}

# adoption / effective dates read from the kommune PDFs (ISO); used for date / effective_from of the replacement rows
DATES = {
 "1292": ("2023-09-05", "2023-09-05"), "1296": ("2023-09-05", "2023-09-05"),
 "1443": ("2023-06-22", "2023-06-22"), "1382": ("2023-06-22", "2023-06-22"),
 "2021": ("2025-12-03", "2026-01-01"),
 "2206": (None, "2023-01-01"),          # the text states no adoption date; date falls back to the ikrafttrædelse
 "1007": ("2023-06-22", "2023-07-01"),
 ("erhverv", "Læsø"): ("2020-11-30", "2021-01-01"),
}

# regulativer NSTAR cannot serve; added from the kommune site (or an archive replay of it)
EXTRA = {
 ("erhverv", "Læsø"): dict(
    url="https://web.archive.org/web/20250809044921id_/https://www.laesoe.dk/p/L%C3%A6s%C3%B8-Kommune---Regulativ-for-erhvervsaffald-2025.pdf",
    original_url="https://www.laesoe.dk/p/L%C3%A6s%C3%B8-Kommune---Regulativ-for-erhvervsaffald-2025.pdf", nstar_document_id="3126",
    note=("Læsø erhverv: NSTAR regulativ 3126 (approved 31-08-2026) cannot be downloaded; NSTAR's PDF render fails server-side (HTTP 200 text/html, a 134-byte "
          "'HttpUnhandledException' page after ~183 s; retried twice on 2026-10-17). laesoe.dk answers HTTP 403 to this collector, so the kommune's "
          "'Regulativ for erhvervsaffald 2025' PDF (born-digital, Adobe PDFMaker) was taken from its Wayback Machine capture of 2025-08-09. Its text says "
          "vedtaget 30-11-2020 / i kraft 01-01-2021. It may NOT be the latest: NSTAR's 3126 is newer, and laesoe.dk now lists a '...Læsø-Kommune-2026.pdf'.")),
}

def fetch_text(s, url, robots):
    p = urllib.parse.urlsplit(url); host = f"{p.scheme}://{p.netloc}"
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = s.get(host + "/robots.txt", timeout=30); rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception: rp.parse([])
        robots[host] = rp; time.sleep(SLEEP)
    if not robots[host].can_fetch(UA, url): raise RuntimeError("robots.txt disallows " + url)
    d = s.get(url, timeout=120); time.sleep(SLEEP)
    if d.status_code != 200 or d.content[:4] != b"%PDF": raise RuntimeError(f"HTTP {d.status_code} {d.headers.get('content-type')}")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(d.content); tf.flush()
        info = subprocess.run(["pdfinfo", tf.name], capture_output=True, text=True).stdout
        txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", tf.name, "-"], capture_output=True, text=True).stdout
    prod = (re.search(r"Producer:\s+(.*)", info) or [None, None])[1]; crea = (re.search(r"Creator:\s+(.*)", info) or [None, None])[1]
    if re.search(r"(?i)paper capture|scan|ocr|KM_C\d+", f"{prod} {crea}"): raise RuntimeError(f"not born-digital ({crea} / {prod})")
    return dict(text=txt, pages=int((re.search(r"Pages:\s+(\d+)", info) or [0, 0])[1]), producer=prod, creator=crea,
                pdf_bytes=len(d.content), pdf_sha256=hashlib.sha256(d.content).hexdigest(), filename=urllib.parse.unquote(p.path.rsplit("/", 1)[-1]),
                retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

def main(out="dk_build"):
    s = requests.Session(); s.headers["User-Agent"] = UA; robots = {}
    jobs = [("replace", k, v["url"], v) for k, v in CURRENCY.items() if v["outcome"] == "replaced"] + [("extra", k, v["url"], v) for k, v in EXTRA.items()]
    with gzip.open(f"{out}/kommune_texts.jsonl.gz", "wt") as w:
        for kind, k, url, v in jobs:
            rec = dict(kind=kind, key=list(k) if isinstance(k, tuple) else k, source_url=url)
            try: rec.update(fetch_text(s, url, robots))
            except Exception as e: rec["error"] = f"{type(e).__name__}: {e}"[:300]
            w.write(json.dumps(rec, ensure_ascii=False) + "\n"); print(kind, k, rec.get("pages"), rec.get("producer"), rec.get("error") or "", flush=True)

if __name__ == "__main__":
    main(*(sys.argv[1:2]))

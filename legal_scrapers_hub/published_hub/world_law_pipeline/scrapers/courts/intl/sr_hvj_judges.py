"""Suriname Hof van Justitie judges (public names/titles only) from two official rechtspraak.sr sources:
 1) 'Beschikking verdeling werkzaamheden Hof van Justitie 2026-2027' (scanned PDF, OCR text; signed 31 Jul 2026, in force 1 Oct 2026):
    president, leden, leden-plaatsvervanger and further judges assigned to chambers/units.
 2) news 'Hof van Justitie Suriname versterkt met vijftien rechters' (23 Oct 2026): 15 new leden-plaatsvervanger.
Names are normalised from noisy OCR by hand (canonical list below); each name is kept only if its surname is found in the fetched source.
Registry/griffie staff are excluded. Usage: sr_hvj_judges.py [--dry]"""
import json, re, sys, time, hashlib, subprocess, tempfile, unicodedata, datetime, html, os
import requests
UA = "WorldCourtsResearchBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_courts; polite research crawl)"
OUT = "/workspace/world_courts/data/sr/sr_judges.jsonl"
PDF = "https://rechtspraak.sr/wp-content/uploads/2026/10/Beschikking-verdeling-werkzaamheden-Hof-van-Justitie-2026-2027.pdf"
NEWS = "https://rechtspraak.sr/actualiteiten/hof-van-justitie-suriname-versterkt-met-vijftien-rechters/"
POLICY = "robots_allowed|rechtspraak.sr: Hof van Justitie Suriname official website (no open licence stated)"
COURT = "sr-supreme-court"  # Hof van Justitie (highest court of Suriname)
PRES = [("I.H.M.H. Rasoelbaks", "President van het Hof van Justitie", "chief")]
LEDEN = ["D.D. Sewratan", "I.S. Chhangur-Lachitjaran", "S.S.S. Wijnhard", "M.V. Kuldip Singh", "D.G.W. Karamat Ali",
         "R.M. Praag", "S.S. Nanhoe-Gangadin", "E.P. Rudge"]
PLV = ["S. Punwasi", "L.C. Ravenberg", "C.A. Wallerlei", "D.M. Haakmat-Sniphout", "A. Adelaar", "S.S. Bikhari", "D. Bandhoe",
       "S.T. Kasanpawiro-Sewdien", "C.S. Klein-Jules", "M.C. Mettendaf", "J.S. Kasdipowidjojo", "M.T. Sanches"]
OTHER = ["A. Charan", "A.C. Johanns", "S.M.M. Chu", "J.M. Jensen", "I. Sonai", "R.H. Elgin", "R.G. Chatterpal", "D.E. Nanhoe", "M.K. Dayala"]
NEW15 = ["Cherida R. Tamsiran-Harris", "Genaro L.E. Alpin", "Kajal Tahdil", "Olton J. Helstone", "Vanessa A. Akaamba", "Anushka A. Bajnath",
         "Julio R. Amatoemar", "Nathaly N. Amatkarijo", "Maytrie Behari", "Grasilla A.T.T. Sitaram", "Sushant R. Mohan", "Latoya S. Rozenblad",
         "Stephanie M. Doelbakir-Kent", "Charisma N. Voorburg-Blank", "Negesty N. Winter"]
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")
def get(u):
    r = requests.get(u, headers={"User-Agent": UA}, timeout=90); r.raise_for_status(); time.sleep(3); return r
def main():
    dry = "--dry" in sys.argv
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pdf = get(PDF); psha = hashlib.sha256(pdf.content).hexdigest()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf.content); f.flush()
        ptxt = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    news = get(NEWS); nsha = hashlib.sha256(news.content).hexdigest()
    ntxt = html.unescape(re.sub(r"<[^>]+>", " ", news.text))
    flat = re.sub(r"\s+", "", ptxt).lower()
    def found(name, txt):
        sur = name.split()[-1].split("-")[0]
        return sur.lower()[:6] in txt
    rows = []
    def add(name, title, ptype, src, sha, txt, extraction, review):
        if not found(name, txt): print("not found in source, skipped:", name); return
        rows.append({"judge_id": f"{COURT}-{slug(name)}", "court_id": COURT, "name": name, "title": title, "position_type": ptype,
                     "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "SR", "roster_url": src, "source_url": src,
                     "source_kind": "official", "site_policy": POLICY, "retrieved_at": now, "needs_review": review, "extraction": extraction,
                     "license": "Hof van Justitie Suriname official publication (facts)", "source_sha256": sha, "language": "nl"})
    ex1 = "Beschikking verdeling werkzaamheden Hof van Justitie 1 okt 2026 - 30 sep 2027 (scanned PDF; OCR names normalised by hand)"
    for n, t, p in PRES: add(n, t, p, PDF, psha, flat, ex1, False)
    for n in LEDEN: add(n, "Lid van het Hof van Justitie", "judge", PDF, psha, flat, ex1, False)
    for n in PLV: add(n, "Lid-plaatsvervanger van het Hof van Justitie", "judge", PDF, psha, flat, ex1, False)
    for n in OTHER: add(n, "Rechter, Hof van Justitie (assigned to chambers/units in the 2026-2027 work allocation; rank not stated)", "judge", PDF, psha, flat, ex1, True)
    for n in NEW15: add(n, "Lid-plaatsvervanger van het Hof van Justitie (installed 23 Oct 2026)", "judge", NEWS, nsha, re.sub(r"\s+", "", ntxt).lower(),
                        "rechtspraak.sr news item 23 Oct 2026: installation of 15 new judges", False)
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            if l.strip(): have.add(json.loads(l)["judge_id"])
    new = [r for r in rows if r["judge_id"] not in have]
    seen = set(); new = [r for r in new if not (r["judge_id"] in seen or seen.add(r["judge_id"]))]
    print("parsed", len(rows), "new", len(new))
    if not dry and new:
        with open(OUT, "a") as f:
            for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
main()

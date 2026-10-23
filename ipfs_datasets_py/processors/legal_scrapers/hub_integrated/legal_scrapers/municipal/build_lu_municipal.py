#!/usr/bin/env python3
"""Build the Luxembourg municipal corpus (communal regulations) from the collector output.
Usage: python build_lu_municipal.py [BUILD_DIR] [OUT_DIR]   (defaults: lu_build, luxembourg_municipal; relative to the working directory)
Inputs in BUILD_DIR: communes.json, links.jsonl, fetch_log.jsonl, docs/<sha20>.pdf, legilux_rc.jsonl (collect_lu_communes.py)."""
import os, sys, re, json, urllib.parse, collections, hashlib, shutil, unicodedata, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import pyarrow as pa, pyarrow.parquet as pq
import lu_fixes as F
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id

COLLECTORS = ("lu_common.py", "lu_fixes.py", "collect_lu_communes.py", "build_lu_municipal.py")
LIC = ("Luxembourg communal regulations are official acts (loi communale modifiée du 13 décembre 1988, art. 82: published by the commune); "
       "official texts are excluded from copyright protection (loi du 18 avril 2001 sur les droits d'auteur, art. 8). Texts as published by the communes.")
STATS = collections.Counter()
DROPS = collections.defaultdict(list)
MAX_PDF_BYTES = 40_000_000
NEAR_J = 0.90

def shingles(t, k=5):
    w = re.findall(r"\w+", t.lower()); return {" ".join(w[i:i + k]) for i in range(0, max(1, len(w) - k + 1))}
def jacc(a, b): return len(a & b) / max(1, len(a | b))

TITLE_START = re.compile(r"(?i)^(nouveau\s+|nouvelle\s+|projet\s+)?(r[eèé]glement|reglement|verordnung|gemeindereglement|polizeiverordnung|statuts|(re)?fixation|modification|"
                         r"adaptation|introduction|instauration|création|abrogation|taxe|tarif|chapitre|r\.?o\.?i\b|ordre\s+intérieur|code\s+de|reglement-taxe|règlement-taxe|kapitel)")
STATE_T = re.compile(r"(?i)r[eèé]glement\s+(grand[- ]ducal|ministériel|\((ue|ce|cee)\))|loi\b|großherzogliche|grossherzogliche")
def _join_title(ls, i, s):
    """a title continues on the next lines ('Règlement général de police modifié du' / '16 avril 2024'; 'REGLEMENT COMMUNAL DU 4 DECEMBRE 2023
    RELATIF AUX' / 'SUBVENTIONS …'; 'RÈGLEMENT' / 'SUR LES BÂTISSES,'): join up to 5 lines while the title has no end and the next line is short"""
    j = i + 1
    while j < min(len(ls), i + 8) and len(s) < 300:
        n = ls[j].strip()
        if not n: 
            if len(s) >= 12: break
            j += 1; continue
        if F.ARTICLE_LINE.match(n) or len(n) > 120 or re.search(r"(?i)^(vu|considérant|gesehen|le\s+conseil|der\s+gemeinderat|chapitre|titre|kapitel|sommaire|version|arrêté|date|présents|séance)", n): break
        ends = re.search(r"(?i)(\b(du|de|des|aux?|la|le|les|relatif|relative|concernant|portant|sur|pour|et|à|vom|über|zur|zum|der|die|des|für|und)|[,–-])$", s)
        upper = sum(c.isupper() for c in s) > 0.7 * max(1, sum(c.isalpha() for c in s))
        if not ends and len(s) >= 12 and not re.match(r"[a-zà-ÿ0-9«(]", n) and not (upper and n.isupper()): break
        s = s + " " + n; j += 1
        if re.search(r"[.;]$", n): break
    return re.sub(r"\s+", " ", s).strip(" .:;-–")[:250]
GENERIC_T = re.compile(r"(?i)(r[eèé]glements?(\s+communaux|\s+communal)?|r[eèé]glement[- ]taxes?|verordnung|reglement)")
def clean_title(link_text, text, url):
    """the regulation's title. Order: the 'Objet :' / 'Point de l'ordre du jour :' line of a deliberation extract; the first line that starts
    with a title word ('Règlement …', 'Fixation d'une taxe …'; never a cited 'Règlement grand-ducal' / 'Loi'); the link text; the file name"""
    lt = re.sub(r"\((FR|DE|EN|LU|LB)\)|\bPDF\b|\d+([.,]\d+)?\s?(Ko|Mo|KB|MB|kB)\b|\bDownload\b|Télécharger|Herunterladen|Eroflueden", " ", link_text or "", flags=re.I)
    lt = re.sub(r"\s+", " ", lt).strip(" -–|")
    if len(lt) < 8 or re.fullmatch(r"[\d\s_.-]+", lt): lt = ""
    if lt and " " not in lt: lt = re.sub(r"[-_]+", " ", lt)          # a file name used as link text
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("filename")
    seg = [x for x in urllib.parse.unquote(url.split("?")[0].split("#")[0]).split("/") if x]
    fn = re.sub(r"[_-]+", " ", os.path.splitext(q[0] if q else (seg[-1] if seg else ""))[0]).strip()
    if re.fullmatch(r"[\d\s]+", fn): fn = ""
    ls = [l.strip() for l in text.split("\n")]
    for i, l in enumerate(ls[:60]):
        m = re.match(r"(?i)^(\d{1,3}\s*[-–.)]\s*)?(point\s+(no|n°)?\s*[\d.]+\s+)?(de\s+l['’=]ordre\s+du\s+jour\s*[-–:]?|objet\s*:|betreff\s*:|concerne\s*:|point\s+de\s+l['’]ordre\s+du\s+jour\s*:)\s*(point\s+[\d.]+\s*[-–:]?\s*)?([\d.]+\s*[-–.)]?\s+)?(?P<t>.*)$", l)
        if not m: continue
        v = m.group("t").strip()
        while True:   # 'Objet: Point 13.3 de l'ordre du jour: Règlement …', '- 4c Objet: Adaptation …'
            w = re.sub(r"(?i)^(objet\s*:|point\s+(no|n°)?\s*[\w.]+\s*(de\s+l['’=]ordre\s+du\s+jour)?\s*[:–-]?|de\s+l['’=]ordre\s+du\s+jour\s*[:–-]?|[-–.:\d\s]+|[a-z]\s+)\s*", "", v)
            if w == v: break
            v = w
        k = i
        if len(re.findall(r"[A-Za-zÀ-ÿ]", v)) < 4:     # 'Objet:' / 'Point de l'ordre du jour : - 12 –' with the subject on the next line(s)
            nxt = [(j, re.sub(r"(?i)^(objet\s*:\s*)", "", ls[j])) for j in range(i + 1, min(len(ls), i + 4)) if ls[j]]
            nxt = [(j, x) for j, x in nxt if (TITLE_START.match(x) or F.REG_T.search(x)) and not re.match(r"(?i)(date|séance|présents|absents|m\.|mme|vu\b)", x)]
            if not nxt: continue
            k, v = nxt[0]
        if len(v) >= 6 and not STATE_T.match(v):
            t = _join_title(ls, k, v)
            if GENERIC_T.fullmatch(t) and lt: return lt
            return t
    generic = None
    for i, l in enumerate(ls[:80]):
        if 5 <= len(l) <= 300 and TITLE_START.match(l) and not STATE_T.match(l) and not F.ARTICLE_LINE.match(l):
            t = _join_title(ls, i, l)
            if len(t) < 12 or not (F.REG_T.search(t) or re.match(r"(?i)(re)?fixation|taxe|tarif|chapitre", t)): continue
            if re.match(r"(?i)chapitre|kapitel", t) and (F.REG_T.search(lt) or F.REG_T.search(fn)): break   # a chapter heading, not the title
            if GENERIC_T.fullmatch(t):     # 'REGLEMENT COMMUNAL', 'REGLEMENT-TAXE': keep looking for the full title line, else the link text
                generic = generic or (i, t); continue
            return t
    if lt and (F.REG_T.search(lt) or not generic): return lt
    if generic:   # 'REGLEMENT COMMUNAL' / 'Primes dans le cadre de l'aide au logement': the subtitle names it
        sub = next((x for x in ls[generic[0] + 1:generic[0] + 4] if len(x) >= 8), "")
        return (generic[1] + (" – " + sub if sub and not F.ARTICLE_LINE.match(sub) else ""))[:250]
    if lt: return lt
    if fn: return fn
    for l in ls[:120]:   # a numbered register extract ('202603030061.pdf'): the first line naming a regulation
        if 12 <= len(l) <= 250 and F.REG_T.search(l) and not F.ARTICLE_LINE.match(l): return re.sub(r"\s+", " ", l).strip(" .:-–")
    return ls[0][:250] if ls else ""

TEMP_RX = re.compile(r"(?i)modification\s+temporaire|r[eèé]glement(ation)?\s+(temporaire|d['’]urgence)|temporaire\s+de\s+la\s+circulation|\b\d{4}-\d{4}\s*MT\b|vorläufige|zeitweilige")
def ref_title(title, text):
    """(title, fix): a collège extract carries its internal reference ('RÉF. INT.: 2026-0467 MT'); when the link text names another
    reference ('2026-0463 MT …', a mislinked file), the title is rebuilt from the text: the reference + the subject lines after it"""
    m = re.search(r"(?i)R[ÉE]F\.?\s*INT\.?\s*:\s*(\d{4}-\d{4})\s*([A-Z]{1,3})?", text[:2500]); t0 = re.match(r"\s*(\d{4}-\d{4})\b", title)
    if not m or not t0 or m.group(1) == t0.group(1): return title, None
    after = [x.strip() for x in text[m.end():m.end() + 600].split("\n")]
    subj = []
    for x in after:
        if not x: 
            if subj: break
            continue
        if re.match(r"(?i)(le\s+coll[eè]ge|ouï|considérant|vu\b)", x): break
        subj.append(x)
        if len(subj) >= 3: break
    new = re.sub(r"\s+", " ", f"{m.group(1)} {m.group(2) or ''} " + " – ".join(subj)).strip()
    return new[:250], dict(link_title=title, reason="link text names another reference than the document's 'RÉF. INT.'")

def commune_names(c):
    n = [c["name"]] + c.get("aliases", [])
    if c["lau"] == "0304": n += ["Ville de Luxembourg", "Stadt Luxemburg", "Luxembourg-Ville"]
    return [x for x in dict.fromkeys(n) if x]

def other_issuer(text, me, allc):
    """the commune named as issuer in the first 2,500 characters ('commune de X', 'Gemeinde X', 'conseil communal de X', 'Ville de X'),
    when it is another commune and this commune is not named there"""
    h = text[:2500]
    own = any(re.search(r"(?i)\b" + re.escape(n) + r"\b", h) for n in commune_names(me))
    if own: return None
    for c in allc:
        if c["lau"] == me["lau"]: continue
        for n in commune_names(c):
            if len(n) >= 4 and re.search(r"(?i)(commune|ville|gemeinde|gemeng|conseil\s+communal|gemeinderat|administration\s+communale)\s+(de\s+|d['’]\s?|der\s+|vun\s+)?" + re.escape(n) + r"\b", h):
                return c["name"]
    return None

def legilux_index(B):
    idx = collections.defaultdict(list)
    p = f"{B}/legilux_rc.jsonl"
    if not os.path.exists(p): return idx
    for l in open(p):
        x = json.loads(l); m = re.match(r"(?s)Règlement communal\s*-\s*(Commune\s+de\s+|Ville\s+de\s+)?([^\n]+?)\.?\n(.*)", x["title"] or "")
        x["commune"] = m.group(2).strip() if m else None; x["subject"] = (m.group(3) if m else x["title"] or "").strip()
        idx[x.get("date_document")].append(x)
    return idx
GENERIC_W = set("règlement reglement règlements communal communale communaux commune ville relatif relative relatifs concernant portant "
                "modification modifications modifié modifiée nouveau nouvelle général générale taxes taxe fixation refixation adaptation "
                "introduction abrogation chapitre conseil article articles dans pour avec sans leur leurs celle celui cette".split())
def _tw(s):
    return {w for w in re.findall(r"\w{4,}", unicodedata.normalize("NFC", s.lower())) if w not in GENERIC_W and not w.isdigit()}
def legilux_match(idx, me, adopt, title):
    """Legilux publication notices for this act: same adoption date, the commune named in the notice (or, for the older Mémorial notices
    without the commune in the title, the commune named in the notice text), AND the subject matching the title: >= 30 % of the
    title's specific words (generic words such as 'règlement', 'communal', 'taxe' ignored) occur in the notice subject, and a tax regulation
    is not matched to a plain regulation (or the reverse). When several
    notices pass, the one with the best overlap is kept if it leads the next by >= 0.15; otherwise none (ambiguous)."""
    if not adopt: return []
    tw = _tw(title); names = [n.lower() for n in commune_names(me)]; sc = []
    if not tw: return []
    for x in idx.get(adopt, []):
        if not ((x["commune"] and x["commune"].lower() in names) or (not x["commune"] and any(n in (x["title"] or "").lower() for n in names))): continue
        # a tax regulation and the plain regulation adopted the same day are different acts ('Règlement-taxe … nuits blanches' vs 'Règlement communal concernant l'octroi d'autorisations …')
        tx = lambda z: bool(re.search(r"(?i)taxe|tarif|redevance", z or "")); rg = lambda z: bool(re.search(r"(?i)r[eèé]glement", z or ""))
        if tx(title) != tx(x["subject"]) and (rg(title) and rg(x["subject"])): STATS["legilux_tax_mismatch"] += 1; continue
        o = len(tw & _tw(x["subject"])) / len(tw)
        if o >= 0.3: sc.append((o, x))
    sc.sort(key=lambda z: -z[0])
    if len(sc) > 1 and sc[0][0] - sc[1][0] < 0.15: STATS["legilux_ambiguous"] += 1; return []
    return [sc[0][1]] if sc else []

# Verifier re-verify fixes (countries-laws-verifier/lu_municipal_reverify.md, 2026-10-17): values the text layer does not give cleanly
VERIFIER_OVERRIDES = {
    "lu-mun-0110-doc-b882bd2a19a0": dict(date="2024-02-08", basis="session_date_ocr_damaged", note="the session line is OCR-damaged ('8 f&vrier 2024'); the publication-announcement date had been taken"),
    "lu-mun-0110-doc-bbab507ef92c": dict(date="2024-02-08", basis="session_date_ocr_damaged", note="the session line is OCR-damaged ('8 f&vrier 2024'); the publication-announcement date had been taken"),
    "lu-mun-0208-doc-1582bc39b39c": dict(date="2026-03-13", basis="readoption_deliberation_date", first_adoption_date="2026-01-30",
                                         note="first adopted 30.01.2026; re-adopted 13.03.2026 after the Ministry's remarks (the approval refers to that deliberation)"),
    "lu-mun-0104-doc-f2aae8cc8de9": dict(date="2023-11-14", basis="session_date_ocr_damaged", note="'Séance publique du 1411112023' (OCR-damaged 14/11/2023)"),
    "lu-mun-0305-doc-63c4927a97c1": dict(reject_notices=True, note="the only date-matched Legilux notice (b1961) is a partial annulment of the waste regulation, not this act (adaptation of the waste-evacuation subsidy regulation)"),
}

def main(B="lu_build", OUT="luxembourg_municipal"):
    communes = json.load(open(f"{B}/communes.json")); byl = {c["lau"]: c for c in communes}
    links = [json.loads(l) for l in open(f"{B}/links.jsonl")]
    flog = [json.loads(l) for l in open(f"{B}/fetch_log.jsonl")] if os.path.exists(f"{B}/fetch_log.jsonl") else []
    fl = {r["url"]: r for r in flog}
    lidx = legilux_index(B); STATS["legilux_notices"] = sum(len(v) for v in lidx.values())
    today = datetime.date.today().isoformat()
    # one document per (commune, PDF content): the same file linked from several pages / URLs is one act
    docs = {}
    for l in links:
        r = fl.get(l["url"])
        if not r: STATS["link_not_fetched"] += 1; DROPS["fetch_failures"].append(dict(url=l["url"], lau=l["lau"], error="not fetched")); continue
        if not r.get("ok"): STATS["fetch_failed"] += 1; DROPS["fetch_failures"].append(dict(url=l["url"], lau=l["lau"], error=r.get("error"))); continue
        k = (l["lau"], r["sha256"])
        if k in docs: docs[k]["alt_urls"].append(l["url"]); STATS["same_file_other_url"] += 1; continue
        docs[k] = dict(link=l, fetch=r, alt_urls=[])
    STATS["documents"] = len(docs)
    acts = []
    for (lau, sha), d in sorted(docs.items()):
        me = byl[lau]; l = d["link"]; r = d["fetch"]; path = f"{B}/docs/{r['file']}"
        if r.get("bytes", 0) > MAX_PDF_BYTES: STATS["excluded_too_large"] += 1; DROPS["text_layer"].append(dict(url=l["url"], reason="pdf > 40 MB")); continue
        tc = f"{B}/text/{os.path.basename(path)}.txt"   # pdftotext output cached per document (small; speeds rebuilds)
        if os.path.exists(tc): raw = open(tc, encoding="utf-8").read()
        else:
            raw = F.pdf_text(path); os.makedirs(f"{B}/text", exist_ok=True); open(tc, "w", encoding="utf-8").write(raw)
        pages = F.pdf_pages(path)
        ok, why = F.text_quality(raw, pages)
        if not ok: STATS["excluded_" + why] += 1; DROPS["text_layer"].append(dict(url=l["url"], lau=lau, reason=why, pages=pages)); continue
        raw, cover_date, cover = F.split_cover_letter(raw)
        if cover: STATS["ministry_cover_letter_removed"] += 1
        raw, memo = F.strip_memorial_pages(raw)
        if memo: STATS["memorial_pages_removed"] += memo
        text = F.clean_text(raw)
        text, sig = F.strip_signature_tail(text)
        if sig: STATS["signature_block_removed"] += 1
        text, letter_date, letter = F.strip_citizen_letter(text)
        if letter: STATS["citizen_letter_removed"] += 1
        title = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", clean_title(l.get("link_text"), text, l["url"]))).strip()   # link texts are not cleaned
        title, title_fix = ref_title(title, text)
        kind, why = F.classify(title, text, l.get("link_text") or "")
        if kind != "regulation":
            STATS["excluded_" + why] += 1; DROPS["not_regulation"].append(dict(url=l["url"], lau=lau, reason=why, title=title[:160])); continue
        oth = other_issuer(text, me, communes)
        if oth: STATS["excluded_wrong_file_other_commune"] += 1; DROPS["wrong_file"].append(dict(url=l["url"], lau=lau, reason=f"issued by {oth}", title=title[:160])); continue
        lang = F.language(text)
        adopt, appr, basis = F.act_dates(title, text, today)
        if letter and letter_date: adopt, basis = letter_date, "vote_date_in_citizen_letter"   # 'Le règlement a été voté en date du 25 avril 2012'
        if appr and adopt and appr < adopt: appr = None
        if cover_date and not appr and (not adopt or cover_date >= adopt): appr = cover_date   # the ministry's approval letter date
        organ = F.issuing_organ(text)
        notices = legilux_match(lidx, me, adopt, title)
        temp = organ == "college_echevinal" and bool(TEMP_RX.search(title + "\n" + text[:3000]))
        acts.append(dict(lau=lau, sha=sha, me=me, link=l, fetch=r, alt_urls=d["alt_urls"], text=text, title=title, lang=lang, adopt=adopt,
                         appr=appr, basis=basis, notices=notices, pages=pages, organ=organ, cover=cover, sig=sig, memo=memo, letter=letter,
                         title_fix=title_fix, temp=temp))
    # identical text (after cleaning) inside a commune: one act
    seen = {}; keep = []
    for a in acts:
        k = (a["lau"], hashlib.sha256(a["text"].encode()).hexdigest())
        if k in seen: seen[k]["alt_urls"].append(a["link"]["url"]); STATS["folded_identical_text"] += 1; DROPS["folded_identical_text"].append(dict(url=a["link"]["url"], kept=seen[k]["link"]["url"])); continue
        seen[k] = a; keep.append(a)
    # near duplicates inside a commune (re-uploads, coordinated vs. signed copy): Jaccard >= 0.9 on 5-word shingles -> keep the newer
    # adoption date, then the longer text
    by = collections.defaultdict(list)
    for a in keep: a["sh"] = shingles(a["text"]); by[a["lau"]].append(a)
    final = []
    for lau, xs in by.items():
        xs.sort(key=lambda a: (a["adopt"] or "", len(a["text"])), reverse=True); kept = []
        for a in xs:
            hit = next((k for k in kept if a["lang"] == k["lang"] and jacc(a["sh"], k["sh"]) >= NEAR_J), None)
            if hit:
                j = round(jacc(a["sh"], hit["sh"]), 3); hit["alt_urls"].append(a["link"]["url"]); STATS["folded_near_duplicate"] += 1
                DROPS["folded_near_duplicate"].append(dict(url=a["link"]["url"], kept=hit["link"]["url"], jaccard=j)); continue
            kept.append(a)
        final += kept
    # a superseded version: same commune, same title, and the newer text lists the older one's vote in its procedure block ('Vote du conseil
    # communal 28 octobre 2016 … Vote du conseil communal-révision octobre 2019 25 novembre 2019'): the older copy is folded into the newer
    def dates_in(t):   # the votes listed in the procedure block ('Vote du conseil communal 28 octobre 2016'), not any cited date
        return {F._date(m.group("d")) for m in F.CLAUSE.finditer(t[:3000]) if re.match(r"(?i)vote", m.group(0))} - {None}
    norm = lambda x: re.sub(r"\W+", " ", unicodedata.normalize("NFKD", x.lower())).strip()
    drop = set()
    for a in final:
        for b in final:
            if a is b or id(a) in drop or a["lau"] != b["lau"] or norm(a["title"]) != norm(b["title"]): continue
            if a["adopt"] and b["adopt"] and a["adopt"] < b["adopt"] and a["adopt"] in dates_in(b["text"]):
                b["alt_urls"].append(a["link"]["url"]); drop.add(id(a)); STATS["folded_superseded_version"] += 1
                DROPS["folded_superseded_version"].append(dict(url=a["link"]["url"], kept=b["link"]["url"], older_adoption=a["adopt"], newer_adoption=b["adopt"]))
                break
    final = [a for a in final if id(a) not in drop]
    rows, arts = [], []; ids = set(); hidden = []
    for a in sorted(final, key=lambda a: (a["lau"], a["adopt"] or "", a["sha"])):
        me = a["me"]; t = a["text"]
        native = "doc-" + a["sha"][:12]
        lid = municipal_law_id("LU", a["lau"], native); assert lid not in ids, lid; ids.add(lid)
        ov = VERIFIER_OVERRIDES.get(lid); a["override"] = None
        if ov:
            STATS["verifier_override"] += 1; a["override"] = dict(ov, previous_date=a["adopt"], previous_basis=a["basis"])
            if "date" in ov: a["adopt"], a["basis"] = ov["date"], ov["basis"]
            if ov.get("reject_notices"): a["rejected_notices"] = [x["eli"] for x in a["notices"]]; a["notices"] = []
            if a["appr"] and a["adopt"] and a["appr"] < a["adopt"]: a["appr"] = None
        recs, cov, info = F.split_articles(t)
        if len(recs) > 1:
            for lab, _, body in recs:
                inner = body.split("\n", 1)[1] if (lab != "0" and "\n" in body) else (body if lab == "0" else "")
                if F.loose_heading_run(inner) >= 3: hidden.append((lid, lab))
        else:
            if F.loose_heading_run(t) >= 3: hidden.append((lid, "whole"))
        assert cov >= 0.95, (lid, cov)
        labs = [x[0] for x in recs]; assert len(labs) == len(set(labs)), (lid, "dup labels")
        marker = {"art": {"fr": "Art.", "de": "Art.", "lb": "Art."}, "article": {"fr": "Article"}, "artikel": {"de": "Artikel", "lb": "Artikel"}}
        mk = info.get("marker")
        ex = dict(source_page=a["link"].get("page"), link_text=a["link"].get("link_text"), alt_urls=a["alt_urls"], pdf_sha256=a["sha"], pdf_pages=a["pages"],
                  language=a["lang"], adoption_date=a["adopt"], approval_date=a["appr"], date_basis=a["basis"],
                  article_marker=(mk or None), article_label_language=a["lang"], numbering_gaps=info.get("gaps") or None,
                  article_blocks=info.get("blocks") if info.get("blocks", 0) > 1 else None, toc_lines_skipped=info.get("toc_lines_skipped") or None,
                  legilux_notices=[dict(eli=x["eli"], title=x["title"][:300], publication_date=x["publication_date"], status=x["status"]) for x in a["notices"]] or None,
                  municipality_wikidata=me.get("qid"), canton=me.get("canton"), issuing_organ=a["organ"],
                  ministry_cover_letter_removed=a["cover"] or None, signature_block_removed=a["sig"] or None, memorial_pages_removed=a["memo"] or None,
                  citizen_letter_removed=a["letter"] or None, title_from_text_reference=a["title_fix"],
                  temporary_traffic_regulation=a["temp"] or None,
                  first_adoption_date=(a["override"] or {}).get("first_adoption_date"), verifier_override=a["override"],
                  legilux_notices_rejected=a.get("rejected_notices") or None,
                  temporary_note=("collège règlement temporaire / d'urgence de circulation (loi du 14 février 1955, art. 5; loi communale art. 58): "
                                  "a temporary measure within the collège's competence, most of them expired; measures over 72 h need council confirmation") if a["temp"] else None)
        # a bilingual parallel text (French and German columns) gives article records in two languages
        al = collections.Counter(F.language(b) for lab, _, b in recs if lab != "0" and len(b) > 200)
        if len(recs) > 3 and len([k for k, n in al.items() if n >= 0.2 * sum(al.values())]) >= 2:
            ex["languages_in_articles"] = dict(al); ex["bilingual_parallel_text"] = True; STATS["bilingual_parallel_text"] += 1
        ex = {k: v for k, v in ex.items() if v not in (None, [], {})}
        status = "unknown"
        if a["notices"] and all(x["status"] and x["status"].startswith("no-longer") for x in a["notices"]): status = "repealed"
        eli = a["notices"][0]["eli"] if len(a["notices"]) == 1 else None
        for lab, htitle, body in recs:
            arts.append(dict(law_id=lid, id=f"{lid}-art-{lab}", title=a["title"], text=body, source_url=a["link"]["url"], document_number=native,
                             article_number=lab, record_type="preamble" if lab == "0" and len(recs) > 1 else ("whole_text" if len(recs) == 1 else ("annex" if lab.startswith("annexe-") else ("chapter_text" if lab.startswith("chapitre-") else "article"))),
                             metadata_json=json.dumps({"heading": htitle} if htitle else {}, ensure_ascii=False)))
        rows.append(dict(id=lid, title=a["title"], text=t, source_url=a["link"]["url"], source_type="official_pdf", jurisdiction=f"LU/{me['name']}",
                         country="Luxembourg", language=a["lang"], eli=eli, date=a["adopt"], date_issued=a["adopt"], retrieved_at=a["fetch"]["retrieved_at"],
                         license=LIC, law_status=status, identifier=native, official_identifier=None, article_count=len(recs), json_path=None,
                         metadata_json=json.dumps({"extras": ex}, ensure_ascii=False), jurisdiction_level="municipal", admin_level=8, country_iso="LU",
                         admin1=me.get("canton"), municipality=me["name"], municipality_code=a["lau"], source_body=f"{me['name']} (" + ("collège des bourgmestre et échevins / Schäfferot" if a["organ"] == "college_echevinal" else "conseil communal / Gemengerot") + ")"))
        STATS["whole_text_records"] += len(recs) == 1
    if hidden: json.dump(hidden, open(f"{B}/hidden_runs.json", "w"))
    assert not hidden, ("records with >= 3 sequential article headings inside", len(hidden), hidden[:5])
    # gates (every failure is collected, then reported together)
    fails = []
    for r in rows:
      try:
          txt = r["text"] + "\n" + r["title"]
          assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd\ue000-\uf8ff\x80-\x9f]", txt), (r["id"], "control / FFFD / PUA / C1")
          assert "(cid:" not in txt, r["id"]
          assert F.garble_rate(r["text"]) <= 50, (r["id"], "garbled OCR text layer", round(F.garble_rate(r["text"])))
          assert unicodedata.normalize("NFC", txt) == txt and unicodedata.normalize("NFKC", r["text"]) == r["text"], (r["id"], "not NFC/NFKC")
          assert not F.loose_combining(txt), (r["id"], "loose combining mark", F.loose_combining(txt)[:3])
          assert not F.mixed_tokens(txt), (r["id"], "mixed-script tokens", F.mixed_tokens(txt)[:5])
          assert not F.SIG.search(r["text"]), (r["id"], "signature residue", F.SIG.search(r["text"]).group(0)[:80])
          tl = r["text"][-600:]
          assert not F.CLOSE.search(tl) and not re.search(r"(?im)^\s*\((s|sé)\.?\)", tl), (r["id"], "closing formula / signatures at the end", tl[-120:])
          assert r["language"] in ("fr", "de", "lb"), r["id"]
          assert not r["date"] or "1800-01-01" <= r["date"] <= today, (r["id"], r["date"])
          assert re.fullmatch(r"lu-mun-\d{4}-doc-[0-9a-f]{12}", r["id"]), r["id"]
      except AssertionError as e: fails.append(e.args[0] if e.args else r['id'])
    if fails: json.dump(fails, open(f"{B}/gate_failures.json", "w"), ensure_ascii=False, default=str)
    assert not fails, (len(fails), fails[:8])
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA); assert len(set(at["id"].to_pylist())) == at.num_rows
    cnt = collections.Counter(x["law_id"] for x in arts); assert all(cnt[r["id"]] == r["article_count"] for r in rows)
    os.makedirs(f"{OUT}/data", exist_ok=True); os.makedirs(f"{OUT}/scrapers", exist_ok=True)
    pq.write_table(t, f"{OUT}/data/laws.parquet", compression="zstd"); pq.write_table(at, f"{OUT}/data/articles.parquet", compression="zstd")
    for f in COLLECTORS: shutil.copy(f"{HERE}/{f}", f"{OUT}/scrapers/{f}")
    shutil.copy(f"{os.path.dirname(HERE)}/schema.py", f"{OUT}/scrapers/schema.py")
    files = {}
    for root, _, fs in os.walk(OUT):
        for f in fs:
            p = os.path.join(root, f); rel = os.path.relpath(p, OUT)
            if rel in ("MANIFEST.json", "README.md", "HANDOFF_READY") or "__pycache__" in rel: continue
            files[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    mc = collections.Counter(r["municipality"] for r in rows)
    man = dict(slug="luxembourg_municipal", country_iso="LU", collectors=list(COLLECTORS), built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               laws_rows=len(rows), articles_rows=len(arts), municipalities={c["name"]: mc.get(c["name"], 0) for c in communes[:int(os.environ.get("LU_TOP", "30"))]},
               language_counts=dict(collections.Counter(r["language"] for r in rows)), law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)),
               date_basis_counts=dict(collections.Counter(json.loads(r["metadata_json"])["extras"].get("date_basis") or "none" for r in rows)),
               build_stats=dict(STATS), fetch_failures=DROPS["fetch_failures"], build_dropped_text_layer=DROPS["text_layer"],
               build_dropped_not_regulation=DROPS["not_regulation"], build_dropped_wrong_file=DROPS["wrong_file"],
               build_folded_identical_text=DROPS["folded_identical_text"], build_folded_near_duplicate=DROPS["folded_near_duplicate"],
               build_folded_superseded_version=DROPS["folded_superseded_version"], sha256=files,
               id_rule="lu-mun-<LAU code without 'LU'>-doc-<first 12 hex of the PDF's sha256> (schema.municipal_law_id)",
               helper_modules={"lu_common.py": "scrapers/lu_common.py (robots.txt matcher, 1 req/s per host, cache); imported by collect_lu_communes.py",
                               "lu_fixes.py": "scrapers/lu_fixes.py (text layer, cleaning, classification, dates, article splitter); imported by build_lu_municipal.py",
                               "schema.py": "scrapers/schema.py (pinned schemas, validate_municipal_table, municipal_law_id); imported by build_lu_municipal.py"},
               sources=dict(texts="commune websites (PDFs linked from the communes' pages; robots.txt honoured, 1 req/s per host)",
                            index="Legilux SPARQL endpoint https://data.legilux.public.lu/sparqlendpoint (types RC / RTC: publication notices, matched by date and commune)"))
    json.dump(man, open(f"{OUT}/MANIFEST.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(dict(laws=len(rows), articles=len(arts), stats=dict(STATS)), ensure_ascii=False))

if __name__ == "__main__":
    main(*(sys.argv[1:3]))

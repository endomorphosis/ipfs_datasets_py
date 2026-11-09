#!/usr/bin/env python3
"""Pure helpers for the German Landesrecht densify lane (ipfs_germany_laws, DE-<Land> rows). No network.

Pattern: gi_build (Gibraltar) collector, itself based on endomorphosis/ipfs_datasets_py @ a1b5c73e world collectors.
Row shape = the live ipfs_germany_laws schema at tip 4911b83b (id, title, text, source_url, source_type, jurisdiction, ...).
"""
import hashlib, html, json, os, re
from urllib.parse import urlsplit

COUNTRY, LANG = "Germany", "de"
HUB_REPO = "endomorphosis/ipfs_germany_laws"
HUB_TIP = os.environ.get("DE_HUB_TIP", "92488791e93016b06d0c26e7dd158ab401c69522")  # SN law-text <br> fix live 2026-10-15 23:22 PT (parent 9c40c341); set after each upload

# Per-Land adapters. enabled=False lands are refused by the collector (no request is ever made).
LANDS = {
    "SN": {"jurisdiction": "DE-SN", "host": "www.revosax.sachsen.de", "source_type": "revosax", "min_delay": 5.0, "enabled": True,
           "license": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Sächsische Staatskanzlei / revosax.sachsen.de (REVOSax)",
           "seed": "https://www.revosax.sachsen.de/sitemap.xml"},
    "BB": {"jurisdiction": "DE-BB", "host": "bravors.brandenburg.de", "source_type": "bravors", "min_delay": 20.0, "enabled": True,
           "license": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Land Brandenburg / bravors.brandenburg.de (BRAVORS)",
           "seed": "https://bravors.brandenburg.de/de/vorschriften_fundstellennachweis_verwaltungsvorschriften_chronologisch"},
    "NW": {"jurisdiction": "DE-NW", "host": "recht.nrw.de", "source_type": "recht_nrw", "min_delay": 5.0, "enabled": True,
           "license": "Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; Ministerium des Innern des Landes Nordrhein-Westfalen / recht.nrw.de",
           "seed": "https://recht.nrw.de/sitemap.xml", "since": "2026-10-02T15:43Z"},  # newest DE-NW retrieved_at on tip 4911b83b
    "NI": {"jurisdiction": "DE-NI", "host": "voris.wolterskluwer-online.de", "source_type": "voris", "min_delay": 10.0, "enabled": True,
           "licence_gate": True,
           "license": "Official statute text (amtliche Werke, § 5 Abs. 1 UrhG); Land Niedersachsen / NI-VORIS (voris.wolterskluwer-online.de). "
                      "Portal states a § 44b(3) UrhG TDM reservation (/nutzungsvorbehalt); collected on the user's decision, see source_terms_note",
           "seed": "https://voris.wolterskluwer-online.de/browse/csh-da-filter%21a52e918e-8a02-41f8-8b62-1c4b6a92ff6a"},
    "HB": {"jurisdiction": "DE-HB", "host": "www.transparenz.bremen.de", "source_type": "transparenz_bremen", "min_delay": 5.0, "enabled": True,
           "licence_gate": True,
           "license": "Official statute text (amtliche Werke, § 5 Abs. 1 UrhG); Freie Hansestadt Bremen / transparenz.bremen.de. "
                      "Portal documents carry CC BY-NC-ND labels; collected on the user's decision, see source_terms_note",
           "seed": "https://www.transparenz.bremen.de/vorschriften-72741?id=72743&gsid=kogis_tp_berlin01.c.60176.de&_article_id=72741&fulltext="
                   "&vorschriften%5B0%5D={cat}&gltigkeit%5B0%5D=In+Kraft&sort=titel&order=asc&max=50&skip={skip}",
           "categories": ["Gesetze+und+Rechtsverordnungen", "Verwaltungsvorschriften"]},
}

# User decision relayed by Chief of Staff on 2026-10-13; recorded on every row (metadata_json) and in the pack card.
SOURCE_TERMS_NOTE = ("User decision relayed by Chief of Staff on 2026-10-13: 'I want the entire law, the government laws are not "
                     "copyrighted' (official statute text, § 5 UrhG). Applies to DE-SN (incl. amending acts, VwV), DE-BB VwV, the "
                     "DE-NW change set, DE-NI (NI-VORIS) and DE-HB (transparenz.bremen.de). Collected robots fail-closed, no WAF/"
                     "challenge bypass, polite throttling.")
LICENCE_FLAG = "LICENCE_GO_NDS_HB"  # must exist in $DE_WORK before NI/HB fetch anything

# ---------------------------------------------------------------- bounds
BOUNDS = {"max_laws_per_slice_pack": 2500, "max_text_bytes": 200 * 1024 * 1024, "max_page_bytes": 8 * 1024 * 1024,
          "max_sections_per_law": 3000, "min_text_chars": 80, "date_min": "1800-01-01", "date_max": "2026-12-31"}

RE_SN_LAW = re.compile(r"^/vorschrift/(\d+)(?:-[A-Za-z0-9._%-]*)?$")


def sn_path_allowed(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc != LANDS["SN"]["host"] or u.query or u.fragment:
        return False
    return u.path == "/sitemap.xml" or bool(RE_SN_LAW.match(u.path))


def sn_kind(slug):
    s = slug or ""
    if s.startswith("Aend") or "Aenderung" in s:
        return "amending"
    if s.startswith("VwV") or "Verwaltungsvorschrift" in s:
        return "vwv"
    if s.startswith("Bek") or "Bekanntmachung" in s:
        return "bek"
    return "law"


def parse_sn_sitemap(xml):
    """{revosax_id: url} for /vorschrift/ locs, with kind."""
    out = {}
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or ""):
        loc = html.unescape(loc)
        p = urlsplit(loc).path
        m = RE_SN_LAW.match(p)
        if m and sn_path_allowed(loc):
            slug = p.split("-", 1)[1] if "-" in p.rsplit("/", 1)[-1] else ""
            out.setdefault(m.group(1), {"url": loc, "kind": sn_kind(slug)})
    return out


def _text(fr):
    fr = re.sub(r"(?i)<br\s*/?>|</p>|</dd>|</dt>|</h\d>|</li>|</tr>", "\n", fr or "")
    fr = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fr)
    lines = [re.sub(r"[ \t\xa0]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", ln))).strip() for ln in fr.split("\n")]
    return "\n".join(l for l in lines if l)


MONTHS = {m: i for i, m in enumerate(["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
                                      "oktober", "november", "dezember"], 1)}


def de_date(s):
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", (s or "").replace("\xa0", " "))
    if not m or m.group(2).lower() not in MONTHS:
        return ""
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


# ---- SN (REVOSax) parser, revised 2026-10-17 after CoS rejected the DE-SN amending densify. Root causes fixed here:
#  * tags were stripped line by line, so a tag whose attribute value wraps (title="...\n...") survived as raw text
#    (`<section data-anchor=...>`, `<a href=... title=...>`) -> tags are now removed across lines with an attribute-aware regex;
#  * `<section\b([^>]*)>` stopped at a '>' inside a quoted attribute (title="...<br>..."), so the section lost its title (title fell
#    back to the internal anchor, e.g. 'a2') and the rest of the attribute leaked into the text -> attribute-aware open-tag regex;
#  * title attributes carrying markup (<br>, &lt;br&gt;, soft hyphen) lost the word break -> a line break / tag inside a title is
#    a space, soft hyphens are dropped;
#  * revosax itself drops a word break in ONE rendering of a heading: the section title attribute ('Artikel 1
#    SächsischesWassergesetz (SächsWG)', de-sn-12867) or the Eingangsformel h3 ('zur Änderung derInfektionsschutzgesetz-...',
#    de-sn-19479), while the h4 / h1 / Vollzitat print the same words with the break -> _respace() unites the word breaks of
#    renderings that are identical ignoring whitespace; h1/Vollzitat compounds wrapped after a hyphen are re-joined;
#  * footnote anchors on one line became bare digits ('... Fachschule 1'), split ones raw HTML -> every revosax footnote anchor is
#    now a '[n]' marker plus a plain-text 'Fußnoten:' block (the format the pipeline already used).
_TAG_ANY = re.compile(r"""<[A-Za-z!/?](?:[^<>"']|"[^"]*"|'[^']*')*>""")
_SEC_OPEN = re.compile(r"""<section\b((?:[^>"']|"[^"]*"|'[^']*')*)>""")
_SN_FN = re.compile(r"""(?is)<a\b((?:[^>"']|"[^"]*"|'[^']*')*)>\s*([^<]{0,12}?)\s*</a\s*>""")
_NBSP_SHY = re.compile("[\xad\u200b]")


def _attr_val(attrs, name):
    m = re.search(r"""(?is)(?:^|\s)%s\s*=\s*(?:"([^"]*)"|'([^']*)')""" % re.escape(name), attrs or "")
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else None


def _plain_attr(v):
    """Attribute text -> one line: entities decoded, markup (<br>, tags) and line breaks become spaces, soft hyphens dropped."""
    v = html.unescape(v or "")
    v = re.sub(r"(?i)<br\s*/?>", " ", v)
    v = _TAG_ANY.sub(" ", v)
    v = _NBSP_SHY.sub("", v)
    return re.sub(r"[ \t\r\n]+", " ", v).strip()


def _sn_footnotes(fr, notes):
    """revosax footnote anchors -> ' [n]'; their title attribute is collected into notes {n: text} (document order)."""
    def rep(m):
        attrs, label = m.group(1), (m.group(2) or "").strip()
        href = _attr_val(attrs, "href") or ""; cls = _attr_val(attrs, "class") or ""
        if "FNID_" not in href and "fussnote" not in cls:
            return m.group(0)
        n = (re.search(r"FNID_(\d+)", href) or re.search(r"(\d+)", label) or [None, str(len(notes) + 1)])[1]
        note = _plain_attr(_attr_val(attrs, "title") or "")
        if note and n not in notes:
            notes[n] = note
        return f" [{n}]"
    return _SN_FN.sub(rep, fr or "")


def _sn_text(fr, notes=None):
    """HTML fragment -> text lines. Same line-break rules as _text, but tags (incl. ones whose attributes wrap lines) are removed
    across lines before the split; footnote anchors -> [n] (+ notes)."""
    own = {} if notes is None else notes
    fr = _sn_footnotes(fr, own)
    fr = re.sub(r"""(?is)<(script|style)\b(?:[^>"']|"[^"]*"|'[^']*')*>.*?</\1\s*>""", " ", fr)
    fr = re.sub(r"(?i)<br\s*/?>|</p\s*>|</dd\s*>|</dt\s*>|</h\d\s*>|</li\s*>|</tr\s*>", "\n", fr)
    fr = _TAG_ANY.sub(" ", fr)
    lines = [re.sub(r"[ \t\xa0]+", " ", html.unescape(ln)).strip() for ln in fr.split("\n")]
    return "\n".join(l for l in lines if l)


_WS = re.compile(r"[\s\xa0]")


def _hyph_join(t):
    """'Infektionsschutzgesetz-\nZuständigkeitsverordnung' (a compound wrapped after its hyphen) -> one word."""
    return re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "-", t or "")


def _respace(primary, *alts):
    """revosax sometimes drops a word break in one rendering of a heading only (title attribute 'SächsischesWassergesetz', the
    Eingangsformel h3 'derInfektionsschutzgesetz-...') while another rendering of the SAME words keeps it (the h4 / h1 text).
    If an alternative has the same characters ignoring whitespace, the word breaks of both are united; the primary's own
    whitespace characters (e.g. NBSP in 'Artikel\xa01') are kept. Different wording -> primary unchanged."""
    if not primary:
        return primary
    key = _WS.sub("", primary)
    for alt in alts:
        if not alt or _WS.sub("", alt) != key or alt == primary:
            continue
        out, j = [], 0
        for ch in primary:
            if _WS.match(ch):
                out.append(ch)
                while j < len(alt) and _WS.match(alt[j]):
                    j += 1
                continue
            if j < len(alt) and _WS.match(alt[j]) and out and not _WS.match(out[-1]):
                out.append(" ")
            while j < len(alt) and _WS.match(alt[j]):
                j += 1
            out.append(ch); j += 1
        primary = "".join(out)
    return primary


def _respace_map(before, after, fixes):
    """Collect the glued words _respace split ('derInfektionsschutzgesetz-...' -> 'der Infektionsschutzgesetz-...')."""
    if before and after and before != after:
        for w in before.split():
            if len(w) > 6:
                f = _respace(w, _find_span(after, w))
                if f != w:
                    fixes[w] = f


def _find_span(text, w):
    """The span of text that equals w ignoring whitespace (None if absent)."""
    key = _WS.sub("", w)
    if not key:
        return None
    pat = r"[\s\xa0]*".join(re.escape(c) for c in key)
    m = re.search(pat, text)
    return m.group(0) if m else None


def _apply_fixes(text, fixes):
    for w, f in fixes.items():
        text = re.sub(r"(?<!\S)%s(?!\S)" % re.escape(w), f, text)
    return text


def _with_notes(text, notes):
    return text + ("\n\nFußnoten:\n" + "\n".join(f"[{n}] {t}" for n, t in notes.items()) if notes else "")


def parse_sn_page(page, url):
    """REVOSax /vorschrift/<id> page -> title, date, vollzitat, sections."""
    page = page or ""
    m = RE_SN_LAW.match(urlsplit(url).path)
    rid = m.group(1) if m else ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    short = _plain_attr(_hyph_join(_sn_text(h1.group(1))).replace("\n", " ")) if h1 else ""
    vz = re.search(r"<p>\s*Vollzitat:(.*?)</p>", page, re.S)
    vollzitat = _hyph_join(_sn_text(vz.group(1))) if vz else ""
    head = re.search(r"""<header\b(?:[^>"']|"[^"]*"|'[^']*')*title="Eingangsformel"(?:[^>"']|"[^"]*"|'[^']*')*>(.*?)</header>""", page, re.S)
    long_title, fixes = "", {}
    if head:
        ht = re.sub(r"(?s)<p\b.*", "", head.group(1))
        ht = re.sub(r"""(?is)<a\b(?:[^>"']|"[^"]*"|'[^']*')*(?:fussnote|FNID_)(?:[^>"']|"[^"]*"|'[^']*')*>.*?</a\s*>""", " ", ht)  # no footnotes in titles
        long_title = _NBSP_SHY.sub("", _sn_text(ht)).replace("\n", " ")
        long_title = re.sub(r" {2,}", " ", long_title).strip()
        raw_long = long_title
        long_title = _respace(long_title, short, re.sub(r"\s+vom\s.*$", "", vollzitat.replace("\n", " ")))
        _respace_map(raw_long, long_title, fixes)
    vom = re.search(r"<b>\s*Vom\s+([^<]+)</b>", head.group(1)) if head else None
    date = de_date(vom.group(1)) if vom else de_date(vollzitat)
    art = re.search(r'<article[^>]*id="lesetext"[^>]*>(.*?)</article>', page, re.S)
    body = art.group(1) if art else ""
    secs = []
    opens = list(_SEC_OPEN.finditer(body))
    for k, sm in enumerate(opens):  # nested sections: each section's own text runs to the next <section> opening
        attrs = sm.group(1)
        inner = body[sm.end(): opens[k + 1].start() if k + 1 < len(opens) else len(body)]
        t = _attr_val(attrs, "title"); a = _attr_val(attrs, "id")
        notes = {}
        txt = _sn_text(inner, notes)
        if txt:
            title = _plain_attr(t) if t is not None else ""
            h = re.search(r"(?is)<h\d\b[^>]*>(.*?)</h\d\s*>", inner)
            if title and h:  # the section heading as printed keeps word breaks the title attribute can lose
                raw_t = title
                title = _respace(title, _plain_attr(_sn_text(h.group(1)).replace("\n", " ")))
                _respace_map(raw_t, title, fixes)
            if not title:  # no title attribute: the section's own heading line, never the internal anchor
                first = txt.split("\n", 1)[0]
                title = first if RE_ENBEZ.match(first) and len(first) <= 120 else ""
            secs.append({"anchor": a if a else str(len(secs) + 1), "title": title, "text": _with_notes(txt, notes)})
    allnotes = {}
    full = _with_notes(_sn_text(body, allnotes), allnotes)
    if fixes:  # the same glued words in the printed text (Eingangsformel, Inhaltsübersicht)
        full = _apply_fixes(full, fixes)
        for sec in secs:
            sec["text"] = _apply_fixes(sec["text"], fixes)
    return {"revosax_id": rid, "short_title": short, "title": long_title or short, "vollzitat": vollzitat, "date": date,
            "sections": secs, "text": full}


# ---------------------------------------------------------------- PII scan (gazette texts normally carry none)
# Revised 2026-10-17 after CoS rejected the DE-SN amending densify (76 over-redactions: 60 table numbers taken for tax ids,
# 12 official treasury IBANs printed in the law, 4 official mailboxes). Only personal data of PRIVATE individuals is redacted:
#  - e-mail: kept when the domain is an authority / public-body domain (soft hyphens and line-wrap tolerated) or the local part is a
#    functional mailbox (poststelle@, datenschutz@, info@ ...); otherwise redacted.
#  - IBAN: kept when it is an official account: Deutsche Bundesbank bank code (BLZ xxx000 00 / BIC MARKDEF1xxx) or a public payee
#    (Bundes-/Landes-/Staats-/Gerichtskasse, Finanzamt, Fonds, Freistaat ...) within 160 chars before it; otherwise redacted.
#  - Steuer-IdNr: only an 11-digit number on ONE line, introduced by a tax-id label (Steuer-ID, Steuer-Identifikationsnummer,
#    IdNr ...) within 40 chars; bare digit runs (tables, amounts, Aktenzeichen) never fire.
_SHY = "\xad\u200b"
RE_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+[" + _SHY + r"]*\.[" + _SHY + r"]*)+[A-Za-z]{2,}\b")
RE_IBAN = re.compile(r"\bDE ?\d{2}(?:[ \xa0]?\d{4}){4}[ \xa0]?\d{2}\b")
RE_STEUER = re.compile(r"(?i)(?:steuer[- ]?(?:id|identifikations)(?:[- ]?(?:nr|nummer))?\.?|\bidnr\.?|identifikationsnummer(?: nach § 139b AO)?)"
                       r"[ \t:.\xa0-]{0,40}?(\d{2}[ \xa0]?\d{3}[ \xa0]?\d{3}[ \xa0]?\d{3})(?![\d])")
OFFICIAL_MAIL = re.compile(r"@(?:[a-z0-9-]+\.)*(?:sachsen|brandenburg|nrw|niedersachsen|bremen|bund|berlin|hamburg|hessen|bayern|saarland|"
                           r"thueringen|sachsen-anhalt|schleswig-holstein|rlp|mv-regierung|landtag[a-z-]*|bundesbank|bsi|bfdi)\.de$|"
                           r"@[a-z0-9.-]*\.(?:gov|europa\.eu|gv\.at|admin\.ch)$|@(?:[a-z0-9-]+\.)*(?:landkreis|kreis|stadt|gemeinde)[a-z0-9-]*\.de$", re.I)
FUNCTIONAL_LOCAL = re.compile(r"^(?:poststelle|post|info|kontakt|datenschutz|datenschutzbeauftragte[rn]?|dsb|presse|service|buergerservice|"
                              r"verwaltung|sekretariat|zentrale|vergabe|beschwerde[n]?|phishing|spam|[a-z]*meldung(?:en)?|abuse|cert|security|sicherheit|it-sicherheit|"
                              r"poststelle\.[a-z0-9-]+|[a-z]+stelle|office|mail|webmaster|redaktion|kanzlei|geschaeftsstelle|einreichung|antrag|"
                              r"[a-z0-9-]*(?:referat|abteilung|amt|stelle|behoerde|ministerium|portal|team|service|support)[a-z0-9.-]*)$", re.I)
OFFICIAL_PAYEE = re.compile(r"(?i)bundeskasse|landeskasse|landeshauptkasse|staatskasse|gerichtskasse|justizkasse|amtskasse|zahlstelle|"
                            r"finanzamt|bundesbank|freistaat|landesamt|bundesamt|staatsministerium|ministerium|fonds|sondervermögen|"
                            r"anstalt des öffentlichen rechts|körperschaft|landesdirektion|regierungspräsidium|kommunal|stadtkasse|kreiskasse")
RE_BIC_BBK = re.compile(r"(?i)\bMARK\s?DE\s?F\s?1")


# a public body's own sub-domain anywhere in the host (also when the printed TLD part has a typo, e.g. the official
# 'spammeldung@lit.justiz.sachsden.de' in de-sn-20360)
OFFICIAL_HOST_LABEL = re.compile(r"(?i)@(?:[a-z0-9-]+\.)*(?:justiz|polizei|landtag|bundestag|gericht|[a-z-]*gericht|staatsanwaltschaft|"
                                 r"finanzamt|finanzverwaltung|landesamt|bundesamt|ministerium|[a-z]*ministerium|staatskanzlei|"
                                 r"landesdirektion|regierungspraesidium|bezirksregierung|kreis|landkreis|stadt|gemeinde)\.")


def _mail_plain(m):
    return re.sub("[" + _SHY + "]", "", m)


def mail_is_official(addr):
    a = _mail_plain(addr)
    return bool(OFFICIAL_MAIL.search(a) or OFFICIAL_HOST_LABEL.search(a)) or bool(FUNCTIONAL_LOCAL.match(a.split("@", 1)[0]))


def iban_is_official(iban, before, after=""):
    digits = re.sub(r"\D", "", iban)  # kk + BLZ(8) + account(10)
    blz = digits[2:10]
    if len(blz) == 8 and blz[3:] == "00000":  # Deutsche Bundesbank branch (BLZ xxx000 00): accounts of public bodies only
        return True
    return bool(OFFICIAL_PAYEE.search(before[-160:])) or bool(RE_BIC_BBK.search(after[:40]))


def pii_scan(text):
    """Return (redacted_text, hits). Redacts only personal data of private individuals (see the rules above); official
    accounts and functional / authority mailboxes stay verbatim. hits = [(kind, value)] of the redactions made."""
    hits = []
    src = text or ""

    def mail(m):
        if mail_is_official(m.group(0)):
            return m.group(0)
        hits.append(("email", m.group(0))); return "[REDACTED-email]"
    t = RE_EMAIL.sub(mail, src)

    def iban(m):
        if iban_is_official(m.group(0), m.string[:m.start()], m.string[m.end():]):
            return m.group(0)
        hits.append(("iban", m.group(0))); return "[REDACTED-iban]"
    t = RE_IBAN.sub(iban, t)

    def steuer(m):
        hits.append(("taxid", m.group(1))); return m.group(0)[:m.start(1) - m.start(0)] + "[REDACTED-taxid]"
    t = RE_STEUER.sub(steuer, t)
    return t, hits


# ---------------------------------------------------------------- records
RE_ENBEZ = re.compile(r"^\s*((?:§§?|Art\.?|Artikel|Anlage|Abschnitt|Teil|[IVXLC]+\.|\d+[a-z]?\.)\s*[0-9a-z]*)\s*(.*)$")


def law_id(land, rid):
    return f"de-{land.lower()}-{rid}"


def sha(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def check_bounds(rec):
    """Return list of bound violations (empty = ok)."""
    bad = []
    if len(rec.get("text") or "") < BOUNDS["min_text_chars"]:
        bad.append("text_too_short")
    if len((rec.get("text") or "").encode()) > BOUNDS["max_page_bytes"]:
        bad.append("text_too_large")
    if len(rec.get("sections") or []) > BOUNDS["max_sections_per_law"]:
        bad.append("too_many_sections")
    d = rec.get("date") or ""
    if d and not (BOUNDS["date_min"] <= d <= BOUNDS["date_max"]):
        bad.append("date_out_of_range")
    if not rec.get("title"):
        bad.append("no_title")
    return bad


def make_rows(land, info, url, retrieved_at):
    L = LANDS[land]
    lid = law_id(land, info.get("key") or info["revosax_id"])
    text, hits = pii_scan(info["text"])
    arts = []
    for s in info["sections"]:
        st, h2 = pii_scan(s["text"]); hits += h2
        m = RE_ENBEZ.match(s["title"] or "")
        enbez, titel = (m.group(1).strip(), (m.group(2) or "").strip() or None) if m else (s["title"] or s["anchor"], None)
        # live-tip article shape (ipfs_germany_laws 4911b83b): id "<law_id>:<enbez>", source_url = law url
        arts.append({"law_id": lid, "id": f"{lid}:{enbez}", "title": s["title"] or enbez, "text": st, "source_url": url,
                     "document_number": None, "article_number": None, "record_type": "article",
                     "metadata_json": json.dumps({"doknr": s["anchor"], "enbez": enbez, "titel": titel,
                                                  "gliederungsbez": None, "gliederungstitel": None}, ensure_ascii=False)})
    seen = {}
    for a in arts:  # unique article ids within a law
        seen[a["id"]] = seen.get(a["id"], 0) + 1
        if seen[a["id"]] > 1:
            a["id"] = f"{a['id']}#{seen[a['id']]}"
    meta = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": info["short_title"],
            "canonical_law_url": url, "metadata": {"license": L["license"], "retrieved_at": retrieved_at, "official_id": info.get("official_id") or info["revosax_id"],
            "vollzitat": info["vollzitat"], "kind": info.get("kind", ""), "collector": "de_laender_build", "pii_redactions": len(hits),
            "rights": {"not_legal_advice": True, "license": L["license"]}, "source_terms_note": SOURCE_TERMS_NOTE}}
    law = {"id": lid, "title": info["title"], "text": text, "source_url": url, "source_type": L["source_type"],
           "jurisdiction": L["jurisdiction"], "country": COUNTRY, "language": LANG, "eli": None, "date": info["date"] or None,
           "date_issued": info["date"] or None, "retrieved_at": retrieved_at, "license": L["license"], "law_status": "current",
           "identifier": lid, "official_identifier": info["short_title"] or None, "article_count": len(arts), "json_path": None,
           "metadata_json": json.dumps(meta, ensure_ascii=False)}
    return law, arts, hits


# ================================================================ other Länder (regex only; no bs4)
def _host_ok(url, land):
    u = urlsplit(url)
    return u.scheme == "https" and u.netloc == LANDS[land]["host"] and not u.fragment


RE_BB_YEAR = re.compile(r"^/de/vorschriften_fundstellennachweis_verwaltungsvorschriften_chronologisch(?:/year/\d{4})?$")
RE_BB_VV = re.compile(r"^/verwaltungsvorschriften/([A-Za-z0-9_.-]+)$")
RE_NW_LAW = re.compile(r"^/lrgv/(gesetz|rechtsverordnung|bekanntmachung|verwaltungsvorschrift)/(\d{8})-([a-z0-9-]+)/?$")
RE_NW_SM = re.compile(r"^/sitemap(?:/page/\d+/sitemap)?\.xml$")
RE_NI = re.compile(r"^/browse/(?:csh-da-filter%21[A-Za-z0-9%_-]+|document/[0-9a-f-]{36})$")
RE_HB_META = re.compile(r"^/metainformationen/[a-z0-9-]+-(\d+)$")


def path_allowed(land, url):
    """Per-Land scope: only listing/document paths of the official host. Anything else (incl. redirect targets) is refused."""
    if land == "SN":
        return sn_path_allowed(url)
    if not _host_ok(url, land):
        return False
    u = urlsplit(url); p = u.path
    if land == "BB":
        return not u.query and (bool(RE_BB_YEAR.match(p)) or bool(RE_BB_VV.match(p)))
    if land == "NW":
        return not u.query and (bool(RE_NW_SM.match(p)) or bool(RE_NW_LAW.match(p)))
    if land == "NI":
        return not u.query and bool(RE_NI.match(p))
    if land == "HB":
        if p == "/vorschriften-72741":
            return "fulltext=" in u.query
        return bool(RE_HB_META.match(p)) and "template=20_gp_ifg_meta_detail_d" in u.query
    return False


def _kind_from_title(t):
    t = t or ""
    if re.search(r"(?i)\b(?:änderung|aenderung|aufhebung)|ändG\b|ÄndVO|zur Änderung", t):
        return "amending"
    if re.search(r"(?i)verwaltungsvorschrift|runderlass|erlass\b|rderl|richtlinie|vwv", t):
        return "vwv"
    if re.search(r"(?i)bekanntmachung", t):
        return "bek"
    return "law"


# ---- BB (BRAVORS) Verwaltungsvorschriften
def parse_bb_years(page):
    return sorted({"https://bravors.brandenburg.de" + h for h in
                   re.findall(r'href="(/de/vorschriften_fundstellennachweis_verwaltungsvorschriften_chronologisch/year/\d{4})"', page or "")})


def parse_bb_vv_list(page):
    out = {}
    for h in re.findall(r'href="(/verwaltungsvorschriften/[A-Za-z0-9_.-]+)"', page or ""):
        slug = h.rsplit("/", 1)[1]
        out.setdefault("vv-" + slug.lower().replace("_", "-"), {"url": "https://bravors.brandenburg.de" + h,
                                                                  "kind": "amending" if re.match(r"(?i)\d*_?aend|aufheb", slug) else "vwv"})
    return out


def _box(page, cls, stop):
    i = page.find(cls)
    if i < 0:
        return ""
    i = page.find(">", i) + 1
    j = min([k for k in (page.find(x, i) for x in stop) if k > 0] or [len(page)])
    return page[i:j]


def _split_heads(body):
    """Split HTML on h2-h6 headings -> [{anchor,title,text}]; text before the first heading is a header section."""
    parts = re.split(r"(?is)(<h[2-6][^>]*>.*?</h[2-6]>)", body or "")
    secs, cur = [], {"anchor": "header", "title": "", "text": ""}
    for part in parts:
        if re.match(r"(?is)<h[2-6]", part):
            if cur["text"].strip() or cur["title"]:
                secs.append(cur)
            a = re.search(r'(?:name|id)="([^"]+)"', part)
            cur = {"anchor": a.group(1) if a else str(len(secs) + 1), "title": _text(part).replace("\n", " "), "text": ""}
        else:
            cur["text"] += part
    if cur["text"].strip() or cur["title"]:
        secs.append(cur)
    for s in secs:
        s["text"] = _text(s["text"])
    return [s for s in secs if s["text"] or s["title"]]


def parse_bb_page(page, url):
    slug = RE_BB_VV.match(urlsplit(url).path).group(1)
    kopf = _text(_box(page, "reiterbox_innen_kopf", ['class="reiterbox_innen_text"']))
    body = _box(page, 'class="reiterbox_innen_text"', ['class="reiterbox_innen_fuss"', 'id="footer"', "<footer", 'class="footer'])
    title = kopf.split("\n")[0] if kopf else slug
    m = re.search(r"vom\s+(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s+\d{4})", kopf)
    secs = _split_heads(body)
    text = "\n".join(x for x in [kopf, _text(body)] if x)
    return {"key": "vv-" + slug.lower().replace("_", "-"), "official_id": f"bravors:verwaltungsvorschriften/{slug}", "revosax_id": "",
            "short_title": title, "title": title, "vollzitat": kopf[:600], "date": de_date(m.group(1)) if m else "",
            "sections": secs, "text": text}


# ---- NW (recht.nrw.de) change set since the tip
def parse_nw_sitemap_index(xml):
    return [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "") if RE_NW_SM.match(urlsplit(u).path)]


def parse_nw_sitemap(xml, since):
    """[(url, lastmod, typ)] for /lrgv/ law URLs with lastmod > since (the tip's NRW harvest time)."""
    out = []
    for loc, lm in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>\s*<lastmod>\s*([^<\s]+)\s*</lastmod>", xml or ""):
        m = RE_NW_LAW.match(urlsplit(loc).path)
        if m and lm > since:
            out.append((loc.rstrip("/") + "/", lm, m.group(1)))
    return out


def nw_since(tag):
    """lastmod floor for an NW sub-lane: 'delta' (or no tag) = changes since the tip harvest; 'bek' / 'vwv' = everything."""
    return LANDS["NW"]["since"] if tag in ("", "-", "delta") else ""


NW_KIND = {"gesetz": "law", "rechtsverordnung": "law", "bekanntmachung": "bek", "verwaltungsvorschrift": "vwv"}


def parse_nw_page(page, url):
    term = re.search(r"taxonomy/term/(\d+)", page or "")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page or "", re.S)
    title = _text(h1.group(1)).replace("\n", " ") if h1 else ""
    box = _text(_box(page, "block-rnrw-legal-document-info-box", ['class="field field--field_body"', "legaldoc-article"]))
    info = {}
    lines = box.split("\n")
    for k, ln in enumerate(lines[:-1]):
        if ln in ("Ausfertigungsdatum", "Gültig ab", "Gültig bis"):
            info[ln] = lines[k + 1]
    def ddmmyyyy(s):
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s or "")
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
    secs = []
    for k, blk in enumerate(re.split(r'<section class="legaldoc-article">', page or "")[1:]):
        blk = blk.split("</section>")[0]
        blk = re.sub(r'(?is)<div class="alert.*?</button>\s*</div>', " ", blk)
        blk = re.sub(r'(?is)<ul class="print-copy-overlay.*?</ul>', " ", blk)
        blk = re.sub(r'(?is)<button.*?</button>', " ", blk)
        num = re.search(r'(?is)field--field_num[^>]*>(.*?)</div>', blk)
        hl = re.search(r'(?is)field--field_headline[^>]*>(.*?)</div>', blk)
        a = re.search(r'id="([0-9a-f-]{36})"', blk)
        t = " ".join(x for x in [_text(num.group(1)) if num else "", _text(hl.group(1)) if hl else ""] if x)
        tx = re.search(r'(?is)field--field_text[^>]*>(.*)', blk)
        body = _text(tx.group(1)) if tx else ""
        if body or t:
            secs.append({"anchor": a.group(1) if a else str(k + 1), "title": t, "text": body})
    tid = term.group(1) if term else ""
    return {"key": tid or RE_NW_LAW.match(urlsplit(url).path).group(3)[:60], "official_id": f"taxonomy/term/{tid}" if tid else url,
            "revosax_id": "", "short_title": title, "title": title, "vollzitat": "", "date": ddmmyyyy(info.get("Ausfertigungsdatum")),
            "valid_from": ddmmyyyy(info.get("Gültig ab")), "sections": secs,
            "text": "\n".join([title] + [f"{s['title']}\n{s['text']}".strip() for s in secs])}


# ---- HB (transparenz.bremen.de)
def parse_hb_list(page):
    """(total, [(doc_id, meta_url)])"""
    m = re.search(r"von\s+\(([\d.]+)\)", page or "")
    total = int(m.group(1).replace(".", "")) if m else 0
    out = []
    for did, body in re.findall(r'<li class="search-result-item" data-id="(\d+)">(.*?)</li>', page or "", re.S):
        u = re.search(r'href="(https://www\.transparenz\.bremen\.de/metainformationen/[^"]+template=20_gp_ifg_meta_detail_d)"', body)
        if u:
            out.append((did, html.unescape(u.group(1))))
    if not out:  # layout without data-id
        for u in re.findall(r'href="(https://www\.transparenz\.bremen\.de/metainformationen/[^"]+template=20_gp_ifg_meta_detail_d)"', page or ""):
            u = html.unescape(u); did = RE_HB_META.match(urlsplit(u).path).group(1)
            if (did, u) not in out:
                out.append((did, u))
    return total, out


def parse_hb_page(page, url, did=""):
    hd = {}
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", _box(page, "TableRahmenkpl", ['class="jgwsAiZDoc"', "jgwsAiZDoc"]) or ""):
        tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(tds) == 2:
            hd.setdefault(_text(tds[0]).rstrip(":").strip(), _text(tds[1]))
    tt = re.search(r'(?is)class="docLayoutTitel"[^>]*>(.*?)</(?:div|h\d|p)>', page or "")
    title = re.sub(r"\s+", " ", _text(tt.group(1))) if tt else ""
    if not title:
        t2 = re.search(r"(?is)<title>(.*?)</title>", page or ""); title = _text(t2.group(1)) if t2 else ""
    docs = re.split(r'<div class="jgwsAiZDoc"', page or "")[1:]
    secs = []
    for k, d in enumerate(docs):
        a = re.search(r'id="jgwsAiZDoc-jlr-([A-Za-z0-9]+)"', d)
        d = d[d.find(">") + 1:]
        d = re.split(r'(?i)<div[^>]+class="(?:TableRahmenkpl|footer|kogis_footer)', d)[0]
        d = re.sub(r"(?is)<a[^>]*>\s*(?:Einzelansicht|Seitenanfang)\s*</a>", " ", d)
        d = re.sub(r"(?i)\b(?:Einzelansicht|Seitenanfang)\b", " ", d)
        h = re.search(r"(?is)<h[2-5][^>]*>(.*?)</h[2-5]>", d)
        head = _text(h.group(1)).replace("\n", " ") if h else ""
        body = _text(re.sub(r"(?is)<h[2-5][^>]*>.*?</h[2-5]>", " ", d, count=1) if h else d)
        if body or head:
            secs.append({"anchor": a.group(1) if a else str(k + 1), "title": head or ("Eingangsformel" if k <= 1 else ""), "text": body})
    first = re.search(r'id="jgwsAiZDoc-jlr-([A-Za-z0-9]+)"', page or "")
    key = (first.group(1) if first else did or (RE_HB_META.match(urlsplit(url).path) or [None, ""])[1]).lower()
    date = ""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", hd.get("Ausfertigungsdatum", ""))
    if m:
        date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    else:
        m = re.search(r"vom\s+(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s+\d{4})\s*$", title)
        date = de_date(m.group(1)) if m else ""
    lic = re.search(r"(?i)\b(cc[ -]by(?:[ -](?:nc|nd|sa))*)", page or "")
    return {"key": key, "official_id": first.group(1) if first else did, "revosax_id": "", "short_title": hd.get("juris-Abkürzung") or title,
            "title": title, "vollzitat": hd.get("Fundstelle", ""), "date": date, "portal_label": lic.group(1).strip() if lic else "",
            "sections": secs, "text": "\n".join([title] + [f"{s['title']}\n{s['text']}".strip() for s in secs])}


# ---- NI (NI-VORIS browse tree; one document per law head / article)
def parse_ni_browse(page):
    """(children [(url,label)], documents [(url,label)]) of a browse page; navigation/breadcrumb links are excluded by the caller."""
    kids, docs = [], []
    for h, lab in re.findall(r'<a[^>]+href="(/browse/[^"]+)"[^>]*>(.*?)</a>', page or "", re.S):
        lab = re.sub(r"\s+", " ", _text(lab)).strip()
        u = "https://voris.wolterskluwer-online.de" + h
        if h.startswith("/browse/document/"):
            if (u, lab) not in docs and RE_NI.match(h):
                docs.append((u, lab))
        elif "PHC-%7B0000" not in h and RE_NI.match(h) and (u, lab) not in kids:
            kids.append((u, lab))
    return kids, docs


def is_ni_law_node(label):
    return bool(re.search(r",NI\s+-\s+", label or ""))


def parse_ni_doc(page):
    art = re.search(r'(?is)<article id="([0-9a-f-]{36})_wkde-document"[^>]*>(.*?)</article>', page or "")
    if not art:
        return None
    uid, a = art.group(1), art.group(2)
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", a)
    bib = {}
    for dt, dd in re.findall(r"(?is)<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", a):
        bib.setdefault(_text(dt), _text(dd))
    body = re.search(r'(?is)class="wkde-document-body"[^>]*>(.*)', a)
    return {"uid": uid, "heading": _text(h1.group(1)).replace("\n", " ") if h1 else "", "bib": bib, "text": _text(body.group(1)) if body else ""}


def ni_assemble(node_label, docs):
    """docs = [(url, parsed)] in tree order; first is the law head. -> generic info dict."""
    head = docs[0][1]
    bib = head["bib"]
    title = bib.get("Titel") or head["heading"]
    m = re.search(r"Vom\s+(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s+\d{4})", head["text"])
    fs = re.search(r"\(([^()]*GVBl[^()]*)\)", head["text"][:400])
    secs = [{"anchor": d["uid"], "title": d["heading"] if k else "Eingangsformel", "text": d["text"]} for k, (u, d) in enumerate(docs) if d["text"] or d["heading"]]
    abbr = (bib.get("Redaktionelle Abkürzung") or node_label.split(" - ")[0]).strip()
    key = re.sub(r"[^a-z0-9]+", "-", abbr.lower().replace(",ni", "")).strip("-") or head["uid"]
    return {"key": key + "-" + head["uid"][:8], "official_id": head["uid"], "revosax_id": "", "short_title": abbr, "title": title,
            "vollzitat": fs.group(1) if fs else "", "date": de_date(m.group(1)) if m else "", "normtyp": bib.get("Normtyp", ""),
            "sections": secs, "text": "\n".join([title] + [f"{s['title']}\n{s['text']}".strip() for s in secs])}


# ---- record clean-up (2026-10-15, after CoS rejected the DE-SN densify): applied to every collected record at pack time,
# so it holds for every future Land pack. Live tip rows are never touched (append-only).
from finalize_gate import (strip_html_footnotes, strip_html_title, is_contents_row, fold_heading_rows, is_heading_only,  # noqa: E402
                           is_bodyless, is_repeal_placeholder, has_raw_html, RAW_HTML)

_TITLE_BODY = re.compile(r"(\sVom \d{1,2}\.\s*\S+\s+\d{4})\s+(\S.{20,})$", re.S)
# norm headings (2026-10-17): an empty 'Artikel N' / '§ N' row is never merged into the next Artikel (CoS); see clean_record.
NORM_HEAD = re.compile(r"^\s*(?:Artikel|Art\.|§§?)\s*\d", re.I)
ATTACH_TITLE = re.compile(r"^\s*(?:Anlagen?|Anh[aä]nge?|Anlage\s*\d+[a-z]?|Anhang\s*\d+[a-z]?)\s*$", re.I)
ATTACH_STUB = re.compile(r"^\s*(?:Karten?|Übersichtskarten?|Anhang|Anh[aä]nge|Anlagen?|Plan|Pläne|Lageplan|Flurkarte|Abbildung(?:en)?|Tabelle(?:n)?|Muster|Formular)\s*\d*\s*$", re.I)


def clean_title(t):
    """Promulgation-date line 'Vom <date>' ends a revosax title; anything after it is body text that leaked in."""
    t = strip_html_title(t)
    m = _TITLE_BODY.search(t)
    return t[:m.end(1)].strip() if m else t


def _clean_meta(mj):
    """Strip HTML out of every string in a metadata_json document (e.g. a revosax <a ... data-name=...> left in `titel`)."""
    if not mj or ("<" not in mj and "&lt;" not in mj):
        return mj, False
    try:
        d = json.loads(mj)
    except ValueError:
        return mj, False
    hit = [False]

    def walk(v):
        if isinstance(v, str):
            if RAW_HTML.search(v):
                hit[0] = True
                return strip_html_title(v)
            return v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v
    d = walk(d)
    return (json.dumps(d, ensure_ascii=False), True) if hit[0] else (mj, False)


def repeal_placeholder_row(a):
    """'Artikel 7\n1\n(außer Kraft)' / 'Artikel 2\n(aufgehoben) 1' / '... [1] ... Fußnoten:' -> stray footnote digits and markers
    stripped from the text; the footnote note (if any) is kept in metadata_json.footnotes; metadata_json.body_status =
    'repealed_placeholder' (the live schema has no body_status column)."""
    text = a.get("text") or ""
    notes = ""
    m = re.search(r"\n\s*Fußnoten:\s*\n(.*)\Z", text, re.S)
    if m:
        notes, text = m.group(1).strip(), text[:m.start()]
    text = re.sub(r"\s*\[\d{1,3}\]", "", text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out = []
    for k, ln in enumerate(lines):
        if k and re.fullmatch(r"\d{1,3}", ln):
            continue  # superscript footnote number on its own line
        if k:
            ln = re.sub(r"(\))\s+\d{1,3}$", r"\1", ln)  # '(aufgehoben) 1'
        out.append(ln)
    try:
        md = json.loads(a.get("metadata_json") or "{}")
    except ValueError:
        md = {}
    md["body_status"] = "repealed_placeholder"
    if notes:
        md["footnotes"] = notes
    return dict(a, text="\n".join(out), metadata_json=json.dumps(md, ensure_ascii=False))


def clean_record(rec):
    """Returns (rec, stats). Strips raw HTML (footnote anchors -> '[n]' + plain 'Fußnoten:' block; any other tag; HTML inside
    metadata_json strings), drops contents-list rows, trims body text out of titles, recomputes article_count, and (2026-10-17):
      * repeal placeholders ('Artikel 7 (aufgehoben)') are KEPT, tagged metadata_json.body_status='repealed_placeholder', stray
        footnote digits stripped;
      * an empty norm heading ('Artikel N' / '§ N' with no body, incl. heading + footnote digits only) is never merged into the next
        Artikel: it is folded only when the next row is not itself a norm heading row (Artikel -> its § rows), otherwise dropped
        (known gap, listed);
      * rows with a heading plus only footnote markers/digits are dropped; attachment stubs ('Anlagen' -> 'Karte') are dropped;
      * other heading-only rows (Teil/Abschnitt/Zustimmungsgesetz ...) fold into the next article as before; trailing ones drop."""
    st = {"footnote_rows": 0, "footnote_law_texts": 0, "contents_dropped": [], "headings_folded": 0, "headings_dropped": [],
          "titles_trimmed": [], "norm_headings_dropped": [], "footnote_digit_rows_dropped": [], "attachment_stubs_dropped": [],
          "repealed_placeholders": [], "metadata_html_cleaned": 0, "folded_ids": []}
    law = dict(rec["law"])
    t, n = strip_html_footnotes(law.get("text") or "")
    if n or t != (law.get("text") or ""):
        st["footnote_law_texts"] += 1; law["text"] = t
    nt = clean_title(law.get("title"))
    if nt != law.get("title"):
        st["titles_trimmed"].append(law["id"]); law["title"] = nt
    law["metadata_json"], hit = _clean_meta(law.get("metadata_json"))
    st["metadata_html_cleaned"] += int(hit)
    arts = []
    for a in rec.get("articles", []):
        a = dict(a)
        tx, n1 = strip_html_footnotes(a.get("text") or "")
        ti = strip_html_title(a.get("title") or "")
        if tx != (a.get("text") or "") or ti != (a.get("title") or ""):
            st["footnote_rows"] += 1
        a["text"], a["title"] = tx, ti
        a["metadata_json"], hit = _clean_meta(a.get("metadata_json"))
        st["metadata_html_cleaned"] += int(hit)
        if is_contents_row(ti):
            st["contents_dropped"].append(a["id"]); continue
        arts.append(a)
    # classify and fold (one pass)
    out, carry = [], []
    for k, a in enumerate(arts):
        ti, tx = a["title"], a["text"]
        if is_repeal_placeholder(ti, tx):
            a = repeal_placeholder_row(a); st["repealed_placeholders"].append(a["id"])
        elif is_bodyless(ti, tx):
            if NORM_HEAD.match(ti):
                nxt = arts[k + 1] if k + 1 < len(arts) else None
                if nxt is not None and not (NORM_HEAD.match(nxt["title"]) and _norm_kind(nxt["title"]) == _norm_kind(ti)):
                    carry.append(a); continue  # 'Artikel 3' heading over the § rows of the act it contains
                (st["footnote_digit_rows_dropped"] if _fn_residue(ti, tx) else st["norm_headings_dropped"]).append(a["id"]); continue
            if _fn_residue(ti, tx) and not is_heading_only(ti, tx):
                st["footnote_digit_rows_dropped"].append(a["id"]); continue
            carry.append(a); continue
        elif ATTACH_TITLE.match(ti) and ATTACH_STUB.match(tx or ""):
            st["attachment_stubs_dropped"].append(a["id"]); continue
        if carry:
            a = dict(a, text="\n".join(c["title"].strip() for c in carry) + "\n" + (a.get("text") or ""))
            st["folded_ids"] += [c["id"] for c in carry]; carry = []
        out.append(a)
    st["headings_dropped"] = [c["id"] for c in carry]
    st["headings_folded"] = len(st["folded_ids"])
    law["article_count"] = len(out)
    return dict(rec, law=law, articles=out), st


def _fn_residue(ti, tx):
    """The text carries footnote markers / a footnote block / standalone digits that are not in the heading."""
    if re.search(r"\[\d{1,3}\]|\nFußnoten:", tx or ""):
        return True
    d = lambda x: sorted(re.findall(r"(?<![\w.])\d{1,3}(?![\w.])", re.sub(r"\s+", " ", x or "")))  # noqa: E731
    return d(tx) != d(ti)


def _norm_kind(t):
    return "art" if re.match(r"^\s*(?:Artikel|Art\.)", t or "", re.I) else "par"

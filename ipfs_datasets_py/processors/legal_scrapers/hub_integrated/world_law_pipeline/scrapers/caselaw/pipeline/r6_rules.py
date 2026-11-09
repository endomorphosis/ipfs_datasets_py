"""r6 row rules shared by the jobs (via cl_common.add_pair) and migrate_r5_to_r6.py. Pure functions over local data; no network."""
from __future__ import annotations
import json, re
import caselaw_schema as cs
from court_matcher import norm_name

_EXEC = re.compile(r"regierungsrat|bundesrat|conseil f.d.ral|consiglio federale|regierungsstatthalter|conseil d.[eé]tat|consiglio di stato|staatsrat", re.I)
_COURT = re.compile(r"gericht|\btribunal\b|\btribunale\b|\btribunaux r.gional|\btribunaux d.arbitrage|\bcour\b|\bcorte\b|\bcourt\b|\bcamera\b|\bgiudice\b|\bpretura\b", re.I)
_COMM = re.compile(r"kommission|commission|commissione|rekurs|aufsicht|surveillance", re.I)
# r7: collections are checked BEFORE courts (a series name that contains a court word is still a collection): Sammlung/Sammelwerk, Rechenschaftsbericht (TG annual report),
# "Praxis des Kantons-/Verwaltungsgerichts" / PVG (GR), ARGVP (AR)
_COLL = re.compile(r"sammlung|sammelwerk|rechenschaftsbericht|\bpraxis des\b|\bpvg\b|\bargvp\b", re.I)
_ADMIN = re.compile(r"verwaltungsbeh|verwaltungspraxis|departement|department|direktion|bundesamt|\bamt\b|beh.rde|autorit|direction", re.I)
_MIXED = re.compile(r"andere beh.rden und gerichte", re.I)
_GRUNDBUCH = re.compile(r"entscheide grundbuch", re.I)   # r7: AG "Entscheide Grundbuch und Notariat" mixes Verwaltungsgericht and administrative bodies: kept NULL (not assessed)
# r7: judicial supervisory bodies (debt enforcement / guardianship supervisory authorities are courts of the cantonal judiciary) -> court
_SUPERVISORY_COURT = re.compile(r"aufsichtsbeh.rde\s+(?:f.r\s+|in\s+)?(?:schuldbetreibung|betreibungs)|autorit. (?:sup.rieure )?de surveillance\s+(?:LP\b|en mati.re de poursuite)|autorit. tut.laire", re.I)
_LEGAL_PROF = re.compile(r"avocat|anwalt|notar", re.I)   # lawyer / notary supervision & appeal authorities (both language twins) -> commission_or_regulator
_CEDH = re.compile(r"\bcedh\b|\begmr\b|\becthr\b", re.I)   # r7: the European Court of Human Rights is not a Swiss body: the Swiss name rules below never apply to it
_EXACT = ((re.compile(r"^(?:OG|Obergericht)$"), "court"), (re.compile(r"^\d+\.\s*Abteilung$"), "court"), (re.compile(r"^Justizleitung$|\bJustizleitung$", re.I), "court"), (re.compile(r"^Verwaltung$"), "administrative_authority"))


def body_type_for(source: str, name: str | None) -> str | None:
    """Issuing-body class. Only CH (entscheidsuche) contains non-court bodies; CJEU, NL and BR bodies are all courts. NULL = mixed / not assessed.
    r7 order (CH): CEDH -> court (Swiss rules do not apply); mixed / Grundbuch -> NULL; collection; executive; exact series names (AR OG, Verwaltung; TG N. Abteilung; Justizleitung);
    court; judicial supervisory (SchKG / tutelle) -> court; lawyer/notary bodies -> commission; commission; administrative; else NULL."""
    if source != "ch_entscheidsuche": return "court"
    if not name: return None
    if _CEDH.search(name): return "court"
    if _MIXED.search(name) or _GRUNDBUCH.search(name): return None
    if _COLL.search(name): return "collection"
    if _EXEC.search(name): return "executive_body"
    for rx, bt in _EXACT:
        if rx.search(name): return bt
    if _COURT.search(name): return "court"
    if _SUPERVISORY_COURT.search(name): return "court"
    if _LEGAL_PROF.search(name): return "commission_or_regulator"
    if _COMM.search(name): return "commission_or_regulator"
    if _ADMIN.search(name): return "administrative_authority"
    return None


# r7: rows that are not decisions at all (guidelines / explanatory documents published in a decision source): flagged metadata.not_decision, body_type NULL
NOT_DECISION = {
    "ZH_SOBE_001_undefined_1998-08-10": "UVEK (Federal Department of Environment, Transport, Energy and Communications) guideline document, not a decision",
    "ZH_SOBE_001_undefined_2004-07-16": "ASTRA/UVEK explanatory notes on the Ordnungsbussengesetz and Ordnungsbussenverordnung, not a decision",
}


TERRITORIES = (("aruba", "AW"), ("cura\u00e7ao", "CW"), ("curacao", "CW"), ("sint maarten", "SX"))


def nl_territory(court_name: str | None) -> str | None:
    """ISO code of a Kingdom-of-the-Netherlands territory court (Aruba AW, Cura\u00e7ao CW, Sint Maarten SX) when the name names exactly ONE of them.
    Joint courts naming several territories (Gemeenschappelijk Hof, Gerecht in Ambtenarenzaken) stay NL."""
    if not court_name: return None
    n = court_name.casefold(); iso = {i for t, i in TERRITORIES if t in n}
    return next(iter(iso)) if len(iso) == 1 else None


_SID_SUFFIX = re.compile(r"_(\d{4}-\d{2}-\d{2}|\d{4}|nodate)$")


def ch_year_precision(source_record_id: str, decision_date: str | None, text: str | None):
    """CH: a Jan-1 date is a PLACEHOLDER (year precision) when the source gave no day. Evidence, in order:
    (1) source_record_id ends _YYYY (year-only), (2) ends _nodate, (3) has no date suffix AND the text never mentions 1 January <year>.
    A source_record_id ending in a full YYYY-MM-DD means the source supplied the day: never touched. -> evidence label or None."""
    d = decision_date
    if not (isinstance(d, str) and len(d) == 10 and d.endswith("-01-01")): return None
    m = _SID_SUFFIX.search(source_record_id or "")
    if m and "-" in m.group(1): return None
    if m: return "source_id_nodate" if m.group(1) == "nodate" else "source_id_year_only"
    y = d[:4]
    if re.search(r"(?:\b0?1\.\s?(?:0?1\.|januar)\s?%s|\b1(?:er)?\.?\s+(?:janvier|januar|gennaio)\s+%s|\b1\u00b0\s+gennaio\s+%s)" % (y, y, y), text or "", re.I): return None
    return "source_id_no_date_and_no_1_january_in_text"


def _meta(r):
    m = r.get("metadata_json") or {}
    if isinstance(m, str): m = json.loads(m)
    r["metadata_json"] = m
    return m


def _flags(r):
    f = r.get("sensitivity_flags")
    if isinstance(f, str): f = json.loads(f)
    return list(f or [])


def apply_r6(dec: dict, op: dict | None = None) -> dict:
    """In place, idempotent. Normalises docket/court labels, assigns body_type, redacts e-mail addresses in the opinion text (rehashing opinion and decision,
    flagging the decision personal_contact), recording originals/counts in metadata_json. Returns a stats dict."""
    st = {"labels": 0, "emails": 0, "body_type": 0, "key": 0}
    md = _meta(dec)
    for col in ("docket_number", "court_name_raw"):
        v = dec.get(col); c = cs.clean_label(v)
        if c != v:
            dec[col] = c; md.setdefault("normalised_labels", {})[col] = v; st["labels"] += 1
            if col == "court_name_raw":
                if dec.get("court_match_status") == "matched": raise ValueError("court name changed on a matched row: rematch needed " + str(dec.get("source_record_id")))
                if dec.get("court_key_provisional"):
                    iso, a1 = dec["country_iso"], dec.get("admin1")
                    new = cs.provisional_key(iso, a1, norm_name(c), dec.get("source_name"), (dec.get("source_record_id") or "").split(":")[2] if (dec.get("source_record_id") or "").count(":") >= 2 else None)
                    if new != dec["court_key_provisional"]: dec["court_key_provisional"] = new; st["key"] += 1
    if dec.get("body_type") is None:
        bt = body_type_for(dec.get("source_name"), dec.get("court_name_raw"))   # r7: apply_r7 recomputes body_type afterwards
        if bt: dec["body_type"] = bt; st["body_type"] += 1
    if op is not None and op.get("text"):
        new, n = cs.redact_emails(op["text"])
        if n:
            om = _meta(op)
            om.setdefault("contact_redaction", {"emails_redacted": 0, "token": cs.EMAIL_TOKEN, "rule": "email_v2", "original_text_sha256": op.get("text_sha256")})
            if om["contact_redaction"].get("rule") == "email_v1": om["contact_redaction"]["rule"] = "email_v1+email_v2"
            om["contact_redaction"]["emails_redacted"] += n
            old_h = op.get("text_sha256"); op["text"] = new; op["text_sha256"] = cs.text_sha256(new)
            if dec.get("text_sha256") == old_h: dec["text_sha256"] = op["text_sha256"]
            dm = md.setdefault("contact_redaction", {"emails_redacted": 0, "token": cs.EMAIL_TOKEN, "rule": "email_v2", "original_text_sha256": old_h})
            if dm.get("rule") == "email_v1": dm["rule"] = "email_v1+email_v2"
            dm["emails_redacted"] += n
            fl = _flags(dec)
            if "personal_contact" not in fl: fl.append("personal_contact")
            dec["sensitivity_flags"] = sorted(fl)
            st["emails"] += n
    return st


_MONTHS = {"januar": 1, "janvier": 1, "gennaio": 1, "februar": 2, "f\u00e9vrier": 2, "fevrier": 2, "febbraio": 2, "m\u00e4rz": 3, "marz": 3, "mars": 3, "marzo": 3, "april": 4, "avril": 4, "aprile": 4,
           "mai": 5, "maggio": 5, "juni": 6, "juin": 6, "giugno": 6, "juli": 7, "juillet": 7, "luglio": 7, "august": 8, "ao\u00fbt": 8, "aout": 8, "agosto": 8, "september": 9, "septembre": 9, "settembre": 9,
           "oktober": 10, "octobre": 10, "ottobre": 10, "november": 11, "novembre": 11, "dezember": 12, "d\u00e9cembre": 12, "decembre": 12, "dicembre": 12}
_HEAD_DATE = re.compile(r"\b(?:vom|du|del|dal|am)\s+(\d{1,2})\s*\.?\s*(?:er\b)?\s*(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s+(\d{4})\b", re.I)
_BGE_ID = re.compile(r"(?:^|_)(?:BGE|ATF|DTF)-")
HEAD_CHARS = 700


def ch_text_date(source_record_id: str, year: str, text: str | None):
    """r7: BGE/ATF/DTF leading cases: the judgment's own full date, taken ONLY from the heading (first %d chars) as 'vom|du|del <d> <Month> <year>' and only when that year equals the
    year already known from the id. Garbled OCR headings (e.g. 'SO. Januar 1926', '19S5') and mid-text pages never match. -> (YYYY-MM-DD, snippet, offset) or None.""" % HEAD_CHARS
    if not (source_record_id and _BGE_ID.search(source_record_id) and text): return None
    m = _HEAD_DATE.search(text[:HEAD_CHARS])
    if not m or m.group(3) != year: return None
    mo = _MONTHS[m.group(2).casefold()]; d = int(m.group(1))
    import calendar
    if not 1 <= d <= calendar.monthrange(int(year), mo)[1]: return None
    return f"{year}-{mo:02d}-{d:02d}", " ".join(m.group(0).split()), m.start()


_DOCKET_YEAR4 = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
_DOCKET_YY = re.compile(r"^[A-Z0-9]+-(\d\d)-\d+")


def docket_year(docket: str | None) -> int | None:
    """r7: the year of a CH docket ONLY when unambiguous: exactly one distinct 4-digit 19xx/20xx year, and any leading 'XXX-YY-N' two-digit segment must agree with it.
    Dockets with only a two-digit segment (O3V-22-22), or two disagreeing years (O1Z-15-13 ARGVP 2018 3732), are ambiguous -> None."""
    if not docket: return None
    ys = {int(y) for y in _DOCKET_YEAR4.findall(docket)}
    if len(ys) != 1: return None
    y = next(iter(ys)); m = _DOCKET_YY.match(docket)
    if m and int(m.group(1)) != y % 100: return None
    return y


_DEC31_TEXT = lambda y: re.compile(r"\b31\.?\s*(?:dezember|d\u00e9cembre|decembre|dicembre)\s+%s|\b31\.\s?12\.\s?(?:%s|%s)\b" % (y, y, y[2:]), re.I)


def ch_date_r7(dec: dict, text: str | None) -> str | None:
    """CH only, idempotent (metadata.date_placeholder.rule == 'date_r7'). Handles BOTH raw ingest rows (full Jan-1 / 12-31 dates) and r6 rows (YYYY + date_placeholder).
    Outcomes: 'recovered' (full date from the BGE heading), 'year' (year precision), 'null' (date unknown), None (untouched).
      - evidence source_id_nodate (id ends _nodate; the index put these at 2021-01-01): year from the docket if unambiguous (year_basis=docket_year), else decision_date/year NULL (date_unknown).
      - evidence ...year_only / no_date_and_no_1_january_in_text on BGE/ATF ids: try the heading date; else year precision (as r6).
      - source_id_dec31_not_in_text: id suffix is a full YYYY-12-31 but the text never states 31 December: year precision (collection year-end placeholder). A 12-31 that the text states is untouched."""
    md = _meta(dec); ph = md.get("date_placeholder"); sid = dec.get("source_record_id") or ""; d = dec.get("decision_date")
    if ph is not None and ph.get("rule") == "date_r7": return None
    if ph is None:
        ev = ch_year_precision(sid, d, text)
        if ev is None and isinstance(d, str) and len(d) == 10 and d.endswith("-12-31"):
            m = _SID_SUFFIX.search(sid)
            if m and m.group(1) == d and not _DEC31_TEXT(d[:4]).search(text or ""): ev = "source_id_dec31_not_in_text"
        if not ev: return None
        orig = d
    else:
        ev, orig = ph["evidence"], ph["original_decision_date"]
    year = orig[:4]; new_ph = {"evidence": ev, "original_decision_date": orig, "rule": "date_r7"}
    if ev == "source_id_nodate":
        new_ph["source_default"] = True   # the source index supplied 2021-01-01 for an id with no date
        y = docket_year(dec.get("docket_number"))
        if y is None:
            dec["decision_date"] = None; dec["decision_year"] = None; md.pop("date_precision", None); new_ph["date_unknown"] = True; out = "null"
        else:
            dec["decision_date"] = str(y); dec["decision_year"] = y; md["date_precision"] = "year"; new_ph["year_basis"] = "docket_year"; out = "year"
    else:
        rec = ch_text_date(sid, year, text) if ev != "source_id_dec31_not_in_text" else None
        if rec:
            dec["decision_date"] = rec[0]; dec["decision_year"] = int(year); md.pop("date_precision", None)
            new_ph["recovered_from_text"] = {"snippet": rec[1], "offset": rec[2], "region": "heading"}; out = "recovered"
        else:
            dec["decision_date"] = year; dec["decision_year"] = int(year); md["date_precision"] = "year"; out = "year"
    md["date_placeholder"] = new_ph
    return out


def apply_ch_date(dec: dict, text: str | None) -> str | None:
    """Back-compat name used by job3_ch: r7 behaviour (ch_date_r7)."""
    return ch_date_r7(dec, text)


# ---------------------------------------------------------------- r8
_MON_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ANCHOR_DATE = re.compile(r"\b(?:arr[\u00ea\u00e9e]t|urteil|sentenza)\s+(?:du|vom|del)\s+(\d{1,2})\s*\.?\s*(?:er\b)?\s*(" + _MON_ALT + r")\s+(\d{4})\b", re.I)
_ANCHOR_DATE2 = re.compile(r"\b(?:du|vom|del)\s+(\d{1,2})\s*\.?\s*(?:er\b)?\s*(" + _MON_ALT + r")\s+(\d{4})\s+(?:dans\s+la\s+cause|in\s+Sachen|nella\s+causa)\b", re.I)   # 'Extrait de l'arret ... du 9 juin 1908 dans la cause X' (OCR-damaged 'arret' still anchored by the formula)
ANCHOR_CHARS = 1500
_AR_HEAD_DATE = re.compile(r"\b(?:Urteil|Beschluss)\s+vom\s+(\d{1,2})\.\s*(" + _MON_ALT + r")\s+(\d{4})\b", re.I)
_ZERO_SUFFIX = re.compile(r"_0000-00-00$")
_ARGVP_DOCKET = re.compile(r"^ARGVP\s+\d{4}\s+\d+$")


def _valid_date(y: int, mo: int, d: int) -> bool:
    import calendar
    return 1 <= d <= calendar.monthrange(y, mo)[1]


def ch_text_date_anchored(source_record_id: str, year: str, text: str | None):
    """r8: BGE/ATF/DTF leading cases whose heading rule (first %d chars) found nothing: the judgment's full date from an ANCHORED 'arr\u00eat du|Urteil vom|sentenza del <d> <Month> <year>' phrase, or the formula '(du|vom|del) <d> <Month> <year> dans la cause|in Sachen|nella causa' (survives an OCR-damaged 'arr\u00eat'), in the first %d chars,
    only when the year equals the year already known from the id. Never 'the first date': a creditors' meeting date earlier in the text cannot match because it carries no anchor. -> (YYYY-MM-DD, snippet, offset) or None.""" % (HEAD_CHARS, ANCHOR_CHARS)
    if not (source_record_id and _BGE_ID.search(source_record_id) and text): return None
    ms = [m_ for m_ in (_ANCHOR_DATE.search(text[:ANCHOR_CHARS]), _ANCHOR_DATE2.search(text[:ANCHOR_CHARS])) if m_]
    m = min(ms, key=lambda m_: m_.start()) if ms else None
    if not m or m.group(3) != year: return None
    mo = _MONTHS[m.group(2).casefold()]; d = int(m.group(1))
    if not _valid_date(int(year), mo, d): return None
    return f"{year}-{mo:02d}-{d:02d}", " ".join(m.group(0).split()), m.start()


def ar_head_date(source_record_id: str, docket: str | None, text: str | None):
    """r8: AR Obergericht dockets 'O<n><X>-YY-N' (YY = FILING year, never the decision year): the full date from the heading phrase 'Urteil|(Zirkular-)Beschluss vom <d>. <Month> <yyyy>' in the first %d chars
    (so 'Entscheiddatum vom ...' of a later federal ruling or the appealed 'Verf\u00fcgung ... vom' never match); sanity: 2000+YY <= year <= 2000+YY+3. No 20YY guess. -> (YYYY-MM-DD, snippet, offset) or None.""" % HEAD_CHARS
    m0 = _DOCKET_YY.match(docket or "")
    if not (source_record_id and source_record_id.startswith("AR_OG_") and m0 and text): return None
    m = _AR_HEAD_DATE.search(text[:HEAD_CHARS])
    if not m: return None
    y = int(m.group(3)); mo = _MONTHS[m.group(2).casefold()]; d = int(m.group(1)); yy = 2000 + int(m0.group(1))
    if not (yy <= y <= yy + 3 and _valid_date(y, mo, d)): return None
    return f"{y}-{mo:02d}-{d:02d}", " ".join(m.group(0).split()), m.start()


def ch_date_r8(dec: dict, text: str | None) -> str | None:
    """CH only, idempotent (date_placeholder.rule == 'date_r8'); runs after ch_date_r7. Outcomes: 'zero_date_flagged', 'publication_year', 'recovered_ar', 'recovered_anchor', None.
      - NULL date from an id ending _0000-00-00 (no placeholder yet): flag date_placeholder{evidence=source_id_zero_date, date_unknown=true}; the year is NOT guessed.
      - ARGVP-docket rows (docket exactly 'ARGVP yyyy nnnn', year_basis docket_year): that year is the ARGVP VOLUME (publication) year, not a decision year -> decision_date/year NULL, date_unknown=true,
        year_basis=publication_volume_year, the year kept in metadata_json.publication_year.
      - NULL-date AR_OG rows (date_unknown, ambiguous docket): full date from the 'Urteil|Beschluss vom ...' heading phrase (ar_head_date) -> date_unknown removed, recovered_from_text kept.
      - BGE/ATF rows still at year precision: anchored 'arr\u00eat du ...' phrase (ch_text_date_anchored) -> full date."""
    md = _meta(dec); ph = md.get("date_placeholder"); sid = dec.get("source_record_id") or ""; d = dec.get("decision_date")
    if ph is None:
        if d is None and _ZERO_SUFFIX.search(sid):
            md["date_placeholder"] = {"evidence": "source_id_zero_date", "original_decision_date": "0000-00-00", "date_unknown": True, "rule": "date_r8"}; return "zero_date_flagged"
        return None
    if ph.get("rule") != "date_r7": return None
    ev = ph.get("evidence")
    if ev == "source_id_nodate":
        dock = dec.get("docket_number") or ""
        if _ARGVP_DOCKET.match(dock) and ph.get("year_basis") == "docket_year" and dec.get("decision_year") is not None:
            md["publication_year"] = int(dec["decision_year"]); dec["decision_date"] = None; dec["decision_year"] = None; md.pop("date_precision", None)
            ph.pop("year_basis", None); ph.update(date_unknown=True, year_basis="publication_volume_year", rule="date_r8"); return "publication_year"
        if ph.get("date_unknown") and d is None:
            rec = ar_head_date(sid, dock, text)
            if rec:
                dec["decision_date"] = rec[0]; dec["decision_year"] = int(rec[0][:4]); md.pop("date_precision", None); ph.pop("date_unknown", None)
                ph["recovered_from_text"] = {"snippet": rec[1], "offset": rec[2], "region": "heading", "anchor": "Urteil|Beschluss vom"}; ph["rule"] = "date_r8"; return "recovered_ar"
    elif ev in ("source_id_no_date_and_no_1_january_in_text", "source_id_year_only") and md.get("date_precision") == "year" and dec.get("decision_year") is not None:
        rec = ch_text_date_anchored(sid, str(dec["decision_year"]), text)
        if rec:
            dec["decision_date"] = rec[0]; md.pop("date_precision", None)
            ph["recovered_from_text"] = {"snippet": rec[1], "offset": rec[2], "region": "first_%d_chars" % ANCHOR_CHARS, "anchor": "arr\u00eat du|Urteil vom|sentenza del | du <date> dans la cause"}; ph["rule"] = "date_r8"; return "recovered_anchor"
    return None


_TG_NAV = re.compile(r"^(?:TVR|RBOG)\s+\d{4}(?:\s+Nr\.\s*\d+)?$")
_TG_FOOT = re.compile(r"\s*Obergericht\s+Verwaltungsgericht\s+Copyright Kanton Thurgau\s+Powered by Scroll Sites & Atlassian Confluence\s*$")


def strip_tg_nav(text: str | None):
    """r7: TG (Thurgau) pages: drop the website navigation that precedes the decision ('Skip to main content / Main navigation / ... / the TVR|RBOG year-and-number menu') and the page footer
    ('Obergericht Verwaltungsgericht / Copyright Kanton Thurgau / Powered by Scroll Sites ...'). -> (new_text, head_chars, tail_chars) or None when the page does not start with the nav marker."""
    if not text or not text.startswith("Skip to main content\n"): return None
    lines = text.split("\n"); idx = [k for k, l in enumerate(lines) if _TG_NAV.match(l.strip())]
    if not idx: return None
    head = "\n".join(lines[:idx[-1] + 1]); rest = text[len(head):]; rest2 = rest.lstrip("\n")
    foot = _TG_FOOT.search(rest2); body = rest2[:foot.start()] if foot else rest2.rstrip()
    if len(body.strip()) < 200: return None
    return body, len(text) - len(rest2), len(rest2) - len(body)


def _set_text(dec, op, new):
    old_h = op.get("text_sha256"); op["text"] = new; op["text_sha256"] = cs.text_sha256(new)
    if dec.get("text_sha256") == old_h: dec["text_sha256"] = op["text_sha256"]
    return old_h


def apply_r7(dec: dict, op: dict | None = None) -> dict:
    """In place, idempotent: r7 rules on top of r6. Order: TG navigation strip (rehash) -> CH date rules -> apply_r6 (labels, e-mail redaction with the r7 regex, personal_contact)
    -> body_type recomputed with the r7 rules -> not_decision flag. Returns a stats dict (keys of apply_r6 plus tg_strip, date, body_type_changed, not_decision)."""
    st = {"tg_strip": 0, "date": None, "body_type_changed": 0, "not_decision": 0}
    sid = dec.get("source_record_id") or ""
    if op is not None and dec.get("source_name") == "ch_entscheidsuche" and sid.startswith("TG_"):
        r = strip_tg_nav(op.get("text"))
        if r:
            old_h = _set_text(dec, op, r[0]); info = {"rule": "tg_nav_v1", "head_chars": r[1], "tail_chars": r[2], "original_text_sha256": old_h}
            _meta(op)["boilerplate_stripped"] = info; _meta(dec)["boilerplate_stripped"] = dict(info); st["tg_strip"] = 1
    if dec.get("source_name") == "ch_entscheidsuche": st["date"] = ch_date_r7(dec, (op or {}).get("text"))
    st.update(apply_r6(dec, op))
    bt = body_type_for(dec.get("source_name"), dec.get("court_name_raw"))
    if sid in NOT_DECISION:
        bt = None; md = _meta(dec)
        if "not_decision" not in md: md["not_decision"] = {"reason": NOT_DECISION[sid], "rule": "r7_manual_review"}; st["not_decision"] = 1
        if op is not None: _meta(op).setdefault("not_decision", {"reason": NOT_DECISION[sid], "rule": "r7_manual_review"})
    if dec.get("body_type") != bt: dec["body_type"] = bt; st["body_type_changed"] = 1
    return st


def apply_r8(dec: dict, op: dict | None = None) -> dict:
    """In place, idempotent: r8 rules on top of r7 (apply_r7 first). Adds st['date8'] (see ch_date_r8)."""
    st = apply_r7(dec, op)
    st["date8"] = ch_date_r8(dec, (op or {}).get("text")) if dec.get("source_name") == "ch_entscheidsuche" else None
    return st

#!/usr/bin/env python3
"""Finalize gate shared by the Europe Gap builders (DE Länder densify, GI packs, territory packs). Pure, no network.
Added 2026-10-15 after CoS rejected the DE-SN densify HUB-READY (contents-list rows, raw revosax footnote HTML, card kind
counts taken before drops). Four checks (4th added 2026-10-15 22:50 PT), each must be 0 / True before a pack may be staged:
  1. contents_rows      article rows that are a table of contents (title is a contents heading)
  2. raw_html_rows      law/article titles, texts or metadata_json strings still carrying HTML markup: ANY tag (generic regex,
                        2026-10-17), escaped tags, attribute residue, FNID anchors
  3. card_matches_data  every count printed on the card equals the count recomputed from the written parquet
  4. heading_only_ok    heading-only rows (text == title, whitespace collapsed: 'Teil 1\nX' == 'Teil 1 X') == the number the
                        card discloses as kept (0 for DE, where they are folded into the next article)
Plus the helpers the builders use to get there: strip_html_footnotes (anchors -> plain-text footnotes) and fold_heading_rows.
"""
import re

CONTENTS_TITLE = re.compile(
    r"^\s*(?:inhaltsverzeichnis|inhaltsübersicht|inhaltsuebersicht|table of contents|contents|arrangement of (?:sections|regulations|rules|clauses)|"
    r"indholdsfortegnelse|innehållsförteckning|innihaldsyvirlit)\s*(?:\[\d+\]|\d+)?\s*[:.]?\s*$", re.I)
HTML_TAGS = r"(?:a|abbr|b|br|dd|div|dl|dt|em|font|h[1-6]|i|img|li|ol|p|span|strong|sub|sup|table|tbody|td|th|thead|tr|u|ul)"
# Generic raw-HTML detector (2026-10-17, after `<section data-anchor=...>` tags passed the old tag list): ANY tag name, not a list.
#  - a tag with attribute syntax, any case, closed or cut off:   <section data-anchor="1" ...>   <a href="/x" title="..."   <A HREF=x>
#  - a bare open/close/void tag whose name is all-lowercase or all-uppercase: <p> </div> <br/> <BR> <wbr> <o:p>
#  - escaped markup (&lt;section ...&gt;), comments/doctype, and attribute residue of a broken tag ('...)">').
#  Statute placeholders such as <ER/SIE>, <Name>, <Ort> and comparisons like "a < b > c" are not markup and do not match.
_ATTR = r"""[A-Za-z_:][-\w:.]*\s*=\s*(?:"[^"]*"?|'[^']*'?|[^\s"'<>=`]+)"""
RAW_HTML = re.compile(
    r"<[A-Za-z][-\w:]*\s+" + _ATTR +                                     # tag with attributes (closed or not)
    r"|</?(?:[a-z][a-z0-9]*(?:[:-][a-z0-9]+)*|[A-Z][A-Z0-9]*)\s*/?>"         # bare tag, one-case name
    r"|&lt;/?[A-Za-z][-\w:]*(?:\s|/?&gt;)"                                  # escaped tag
    r"|<!--|<!DOCTYPE|<!\[CDATA\["                                            # comment / doctype / cdata
    r'|"\s*/?>'                                                              # residue of a cut-off attribute value
    r"|\bclass=\"fussnote_link\"|href=\"#FNID_\d+\"|\bfussnote_link\b|\bdata-(?:anchor|level|link|name|id)=")
_FN_ANCHOR = re.compile(r"(?is)<a\b([^>]*)>[ \t]*(\d{1,3}(?:[ \t]+\d{1,3})*(?=\s*(?:<|$))|\d{1,3}|[^<\d]{0,12}?(?=\s*</a))?(?:\s*</a\s*>)?")
_FN_TRUNC = re.compile(r"(?is)<a\b[^>]*$")  # anchor cut off at the end of a split article
_BR = re.compile(r"(?i)<br\s*/?>")
_TAG_LIST = re.compile(r"(?is)</?%s\b[^>]*>" % HTML_TAGS)
# any real tag (2026-10-17): a tag with attribute syntax (any name, attribute values may wrap lines), or a bare tag with a one-case
# name. '<ER/SIE>', '<Name>', 'a < b > c' are statute text and stay.
_ATTR_STRICT = r"""[A-Za-z_:][-\w:.]*(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'<>=`]+))?"""
_ATTR_EQ = r"""[A-Za-z_:][-\w:.]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'<>=`]+)"""
_TAG = re.compile(r"<[A-Za-z][-\w:]*(?:\s+" + _ATTR_STRICT + r")*?\s+" + _ATTR_EQ + r"(?:\s+" + _ATTR_STRICT + r")*\s*/?>|</?(?:[a-z][a-z0-9]*(?:[:-][a-z0-9]+)*|[A-Z][A-Z0-9]*)\s*/?>")


def ws(s):
    """Whitespace-collapsed form used for every heading-only comparison: runs of spaces/newlines -> one space, stripped."""
    return re.sub(r"\s+", " ", s or "").strip()


_FN_BLOCK = re.compile(r"\n\s*Fußnoten:\s*\n.*\Z", re.S)
_FN_MARK = re.compile(r"\s*\[\d{1,3}\]")
REPEAL = re.compile(r"^\(?\s*(?:aufgehoben|weggefallen|außer\s+kraft|ausser\s+kraft|gestrichen|entfallen|nicht\s+mehr\s+belegt)\s*\)?\.?$", re.I)


def is_heading_only(title, text):
    t = ws(text)
    return bool(t) and t == ws(title)


def body_text(title, text):
    """What the row says beyond its own heading: the footnote block and [n] markers are removed, standalone 1-3 digit words
    (superscript footnote numbers such as 'Artikel 7\n1\n(außer Kraft)' or '... Fachschule 1') are ignored on both sides, and the
    heading (title) words are removed from the start. '' = the row carries no body of its own."""
    def toks(x):
        return [w for w in ws(_FN_MARK.sub(" ", x or "")).split(" ") if w and not re.fullmatch(r"\d{1,3}", w)]
    tt = toks(_FN_BLOCK.sub("", text or "")); hh = toks(title)
    if hh and tt[:len(hh)] == hh:
        return " ".join(tt[len(hh):])
    j = lambda x: re.sub(r"[\W_]+", "", "".join(x))  # noqa: E731  letters/digits only: wrap, spacing, line-end hyphen, '( X )' vs '(X'
    if hh and j(tt) and j(tt) == j(hh):  # same heading as the title, only punctuation/spacing differs
        return ""
    return " ".join(tt)


def is_bodyless(title, text):
    """Heading-only in the wider sense: nothing but the heading, footnote markers/digits and a footnote block."""
    return bool(ws(text)) and body_text(title, text) == ""


def is_repeal_placeholder(title, text):
    """'Artikel 7 (aufgehoben)' / '(außer Kraft)' / '(weggefallen)' rows: the heading itself says the norm is repealed."""
    h = ws(_FN_MARK.sub("", title or ""))
    m = re.search(r"\(([^()]*)\)\s*$", h)
    tail = m.group(0) if m else ""
    b = body_text(title, text)
    return bool(tail and REPEAL.match(tail)) and (b == "" or bool(REPEAL.match(b)))


def _attr(attrs, name):
    m = re.search(r'(?is)\b%s\s*=\s*"([^"]*)"' % name, attrs)
    return m.group(1) if m else ""


def strip_html_footnotes(text):
    """revosax-style '<a title="NOTE" class="fussnote_link" href="#FNID_n"> n</a>' -> inline '[n]' plus a plain-text
    'Fußnoten:' block at the end; any other known HTML tag is removed. Returns (clean_text, n_footnotes_converted)."""
    if not text or ("<" not in text and "&lt;" not in text):
        return text, 0
    notes, order = {}, []

    def anchor(m):
        attrs, label = m.group(1), (m.group(2) or "").strip()
        href = _attr(attrs, "href"); note = re.sub(r"\s+", " ", _attr(attrs, "title")).strip()
        n = (re.search(r"FNID_(\d+)", href) or re.search(r"(\d+)", label or "") or [None, str(len(order) + 1)])[1]
        if note and n not in notes:
            notes[n] = note; order.append(n)
        return f" [{n}]" if (note or "FNID" in href) else (label and f" {label}" or "")

    out = _FN_ANCHOR.sub(anchor, text)
    m = _FN_TRUNC.search(out)
    if m:  # truncated anchor: keep its note if the title attribute is complete
        note = re.sub(r"\s+", " ", _attr(m.group(0) + '"', "title")).strip()
        out = out[:m.start()].rstrip()
        if note:
            mm = re.search(r"FNID_(\d+)", m.group(0)); n = mm.group(1) if mm else str(len(order) + 1); notes[n] = note; order.append(n); out += f" [{n}]"
    out = _BR.sub("\n", out)  # a line break separates words: never glue them (fixed 2026-10-15 after 'elektronischenInformations-')
    out = _TAG_LIST.sub("", out)
    out = _TAG.sub("\x00", out)  # any other tag (e.g. <section data-anchor=...>): a space, never glue words;
    out = re.sub(r"(?m)^[ \t\x00]*\x00[ \t\x00]*\n", "", out).replace("\x00", " ")  # a line that held only a tag goes away
    out = re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]{2,}", " ", out)).strip()
    if order:
        out += "\n\nFußnoten:\n" + "\n".join(f"[{n}] {notes[n]}" for n in order)
    return out, len(order)


def strip_html_title(title):
    """Titles keep no footnotes: anchors and their numeric labels are removed, notes dropped."""
    t, n = strip_html_footnotes(title or "")
    t = t.split("\n\nFußnoten:")[0]
    if n or "<" in (title or ""):
        t = re.sub(r"\s*\[\d+\](?=[^\s.,;:)\]])", " ", t); t = re.sub(r"\s*\[\d+\]", "", t)
    return re.sub(r"\s+", " ", t).strip() if n or "<" in (title or "") else t.strip()


def is_contents_row(title):
    return bool(CONTENTS_TITLE.match(title or ""))


def fold_heading_rows(articles):
    """Heading-only rows (text == title after whitespace collapse) are folded into the next row of the same law (their heading is prepended to its
    text); a trailing heading-only row is dropped. Returns (articles, folded_ids, dropped_ids). Ids of kept rows unchanged."""
    out, carry, folded, dropped = [], [], [], []
    for a in articles:
        if is_heading_only(a.get("title"), a.get("text")):
            carry.append(a); continue
        if carry:
            a = dict(a, text="\n".join(c["title"].strip() for c in carry) + "\n" + (a.get("text") or ""))
            folded += [c["id"] for c in carry]; carry = []
        out.append(a)
    dropped = [c["id"] for c in carry]
    return out, folded, dropped


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def row_strings(row):
    """Every text-bearing field of a row: title, text and each string inside metadata_json (decoded; raw string if not JSON)."""
    import json
    out = [row.get("title") or "", row.get("text") or ""]
    m = row.get("metadata_json")
    if m:
        try:
            out += list(_strings(json.loads(m)))
        except (ValueError, TypeError):
            out.append(str(m))
    return out


def has_raw_html(row):
    return any(RAW_HTML.search(s) for s in row_strings(row))


def body_status(row):
    import json
    try:
        return (json.loads(row.get("metadata_json") or "{}") or {}).get("body_status")
    except (ValueError, TypeError, AttributeError):
        return None


def gate(law_rows, article_rows, card_counts, data_counts, heading_only_allowed=0, bodyless_check=False):
    """law_rows / article_rows: iterables of dicts (only the rows this pack adds). card_counts / data_counts: dicts of
    the numbers printed on the card vs recomputed from the parquet. heading_only_allowed: heading-only rows (whitespace-
    collapsed text == title) the card discloses as kept (GI/territory one-line sections); 0 for DE (folded). Raw HTML = generic tag
    regex over title, text and every metadata_json string. Rows tagged metadata_json.body_status='repealed_placeholder' are counted
    apart, not as heading-only. bodyless_check (DE): heading + footnote markers/digits only also counts as heading-only.
    Returns a dict; 'ok' is True only if every check passes."""
    law_rows, article_rows = list(law_rows), list(article_rows)
    contents = [a.get("id") for a in article_rows if is_contents_row(a.get("title"))]
    html_a = [a.get("id") for a in article_rows if has_raw_html(a)]
    html_l = [x.get("id") for x in law_rows if has_raw_html(x)]
    diff = {k: {"card": card_counts.get(k), "data": data_counts.get(k)} for k in set(card_counts) | set(data_counts)
            if card_counts.get(k) != data_counts.get(k)}
    repealed = [a.get("id") for a in article_rows if body_status(a) == "repealed_placeholder"]
    heading_only_ids = [a.get("id") for a in article_rows if body_status(a) != "repealed_placeholder"
                        and (is_heading_only(a.get("title"), a.get("text")) or (bodyless_check and is_bodyless(a.get("title"), a.get("text"))))]
    heading_only = len(heading_only_ids)
    res = {"contents_rows": len(contents), "contents_row_ids": contents[:20],
           "raw_html_article_rows": len(html_a), "raw_html_law_rows": len(html_l), "raw_html_ids": (html_a + html_l)[:20],
           "card_matches_data": not diff, "card_vs_data_diff": diff,
           "heading_only_rows": heading_only, "heading_only_ids": heading_only_ids[:20], "heading_only_allowed": heading_only_allowed,
           "heading_only_ok": heading_only == heading_only_allowed, "repealed_placeholder_rows": len(repealed)}
    res["ok"] = res["contents_rows"] == 0 and res["raw_html_article_rows"] == 0 and res["raw_html_law_rows"] == 0 and res["card_matches_data"] and res["heading_only_ok"]
    return res


_FILE_ROW = re.compile(r"^\|\s*`?([\w./-]+\.parquet)`?\s*\|\s*[\d,]+\s*\|\s*([\d,]+)\s*\|", re.M)


def card_file_rows(card):
    """'| data/laws-00002.parquet | 1,234 | 56 | `sha` |' rows of a dataset card -> {path: rows}."""
    return {m.group(1): int(m.group(2).replace(",", "")) for m in _FILE_ROW.finditer(card or "")}


def pack_gate(pack, laws_f, arts_f, card_text, extra_card=None, extra_data=None, heading_only_allowed=0):
    """GI / territory packs: whole files are new rows. Card numbers checked = the files-table rows of this pack's
    parquet files (+ any extra_card/extra_data pairs, e.g. kind or language counts)."""
    import pyarrow.parquet as pq
    from pathlib import Path
    pack = Path(pack)
    def cols(f):
        names = pq.read_schema(pack / f).names
        return [c for c in ("id", "title", "text", "metadata_json") if c in names]
    lt = pq.read_table(pack / laws_f, columns=cols(laws_f)).to_pylist()
    at = pq.read_table(pack / arts_f, columns=cols(arts_f)).to_pylist()
    rows = card_file_rows(card_text)
    card = {f"rows:{laws_f}": rows.get(laws_f), f"rows:{arts_f}": rows.get(arts_f), **(extra_card or {})}
    data = {f"rows:{laws_f}": len(lt), f"rows:{arts_f}": len(at), **(extra_data or {})}
    return gate(lt, at, card, data, heading_only_allowed)

"""ZSTD parquet writer matching justicedao/american_municipal_law schema (minus pandas index)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HTML_COLUMNS = ["cid", "doc_id", "doc_order", "html_title", "html"]
CITATION_COLUMNS = [
    "bluebook_cid",
    "cid",
    "title",
    "title_num",
    "date",
    "public_law_num",
    "chapter",
    "chapter_num",
    "history_note",
    "ordinance",
    "section",
    "enacted",
    "year",
    "place_name",
    "state_name",
    "state_code",
    "bluebook_sate_code",  # dataset typo, keep
    "bluebook_citation",
]

STATE_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}

# Bluebook T10-style abbreviations
BLUEBOOK_STATE = {
    "AL": "Ala.", "AK": "Alaska", "AZ": "Ariz.", "AR": "Ark.", "CA": "Cal.",
    "CO": "Colo.", "CT": "Conn.", "DE": "Del.", "DC": "D.C.", "FL": "Fla.",
    "GA": "Ga.", "HI": "Haw.", "ID": "Idaho", "IL": "Ill.", "IN": "Ind.",
    "IA": "Iowa", "KS": "Kan.", "KY": "Ky.", "LA": "La.", "ME": "Me.",
    "MD": "Md.", "MA": "Mass.", "MI": "Mich.", "MN": "Minn.", "MS": "Miss.",
    "MO": "Mo.", "MT": "Mont.", "NE": "Neb.", "NV": "Nev.", "NH": "N.H.",
    "NJ": "N.J.", "NM": "N.M.", "NY": "N.Y.", "NC": "N.C.", "ND": "N.D.",
    "OH": "Ohio", "OK": "Okla.", "OR": "Or.", "PA": "Pa.", "RI": "R.I.",
    "SC": "S.C.", "SD": "S.D.", "TN": "Tenn.", "TX": "Tex.", "UT": "Utah",
    "VT": "Vt.", "VA": "Va.", "WA": "Wash.", "WV": "W. Va.", "WI": "Wis.",
    "WY": "Wyo.", "PR": "P.R.",
}

_B32 = "abcdefghijklmnopqrstuvwxyz234567"


def _b32encode(data: bytes) -> str:
    bits = 0
    value = 0
    out: List[str] = []
    for b in data:
        value = (value << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_B32[(value >> bits) & 31])
    if bits:
        out.append(_B32[(value << (5 - bits)) & 31])
    return "".join(out)


def cid_v1_raw_sha256(text: str) -> str:
    """CIDv1 (base32, raw, sha2-256) of UTF-8 text. Matches dataset cids."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    cid_bytes = bytes([0x01, 0x55, 0x12, 0x20]) + digest
    return "b" + _b32encode(cid_bytes)


def html_cid(gnis: str, doc_id: str) -> str:
    return cid_v1_raw_sha256(f"{gnis}_{doc_id}.json")


def bluebook_cid(place_name: str, bb_state: str, title: str, history_note: str) -> str:
    return cid_v1_raw_sha256(f"{place_name}{bb_state}{title}{history_note}")


def strip_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_title_num(title: str) -> str:
    t = title or ""
    m = re.search(
        r"(?i)\b(?:sec(?:tion)?|§)\.?\s*([0-9A-Za-z]+(?:[.\-:][0-9A-Za-z]+)*)",
        t,
    )
    if m:
        return m.group(1)
    m = re.search(r"(?i)\bchapter\s+([0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)", t)
    if m:
        return m.group(1)
    m = re.search(r"(?i)\barticle\s+([IVXLCDM]+|[0-9A-Za-z]+)", t)
    if m:
        return m.group(1)
    return ""


def extract_chapter_num(chapter: str) -> str:
    m = re.search(r"(?i)\bchapter\s+([0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)", chapter or "")
    return m.group(1) if m else ""


def _year_from_short(yy: int) -> int:
    return 1900 + yy if yy >= 50 else 2000 + yy


def parse_year(date_s: str) -> str:
    if not date_s:
        return ""
    m = re.search(r"\b(19|20)\d{2}\b", date_s)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{2})\b", date_s)
    if m:
        return str(_year_from_short(int(m.group(3))))
    m = re.search(r"\b(\d{2})\b", date_s)
    if m:
        return str(_year_from_short(int(m.group(1))))
    return ""


def _split_history_notes(blob: str) -> List[str]:
    blob = blob.strip()
    if blob.startswith("(") and blob.endswith(")"):
        blob = blob[1:-1].strip()
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in blob:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == ";" and depth == 0:
            piece = "".join(buf).strip(" ;")
            if piece:
                parts.append(piece)
            buf = []
        else:
            buf.append(ch)
    piece = "".join(buf).strip(" ;")
    if piece:
        parts.append(piece)
    return parts or ([blob] if blob else [])


def extract_history_notes(html: str) -> List[str]:
    """Pull Municode history notes from section HTML."""
    if not html:
        return []
    notes: List[str] = []
    for cls in (
        r"historynote\d*",
        r"history-note",
        r"refeditor\d*",
        r"refhistory\d*",
        r"refmanual\d*",
    ):
        for m in re.finditer(
            rf'<p[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</p>',
            html,
            flags=re.I | re.S,
        ):
            plain = strip_tags(m.group(1))
            if re.search(r"(?i)\b(ord\.|res\.|ord\b)", plain):
                notes.extend(_split_history_notes(plain))
    if not notes:
        for m in re.finditer(
            r"\(((?:Ord\.|Res\.)[^()]{3,180})\)",
            strip_tags(html),
        ):
            notes.extend(_split_history_notes(m.group(1)))
    # de-dupe preserving order
    seen = set()
    out = []
    for n in notes:
        n = re.sub(r"\s+", " ", n).strip(" ;")
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def parse_history_fields(note: str) -> Dict[str, str]:
    ordinance = ""
    section = ""
    date_s = ""
    m = re.search(r"((?:Ord\.|Res\.)(?:\s+No\.)?[^,;]*)", note)
    if m:
        ordinance = m.group(1).strip(" ,;")
    m = re.search(r"(§+\s*[^,;]+)", note)
    if m:
        section = m.group(1).strip(" ,;")
    m = re.search(r"\b(\d{1,2}-\d{1,2}-\d{2,4})\b", note)
    if m:
        date_s = m.group(1)
    else:
        m = re.search(
            r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)[.]?\s+\d{1,2},\s+\d{4})\b",
            note,
            re.I,
        )
        if m:
            date_s = m.group(1)
    year = parse_year(date_s) or parse_year(note)
    return {
        "history_note": note,
        "ordinance": ordinance,
        "section": section,
        "date": date_s,
        "year": year,
        "enacted": year,
    }


def _code_kind(place_name: str) -> str:
    n = (place_name or "").lower()
    if "county" in n and "city" not in n:
        return "County Code"
    return "Municipal Code"


def format_bluebook(
    place_name: str,
    bb_state: str,
    title_num: str,
    year: str,
    kind: str,
) -> str:
    parts = [f"{place_name}, {bb_state}, {kind}"]
    if title_num:
        parts.append(f"§ {title_num}")
    cite = ", ".join(parts) if title_num else f"{place_name}, {bb_state}, {kind}"
    if year:
        cite = f"{cite} ({year})"
    return cite


def docs_to_html_rows(docs: Sequence[Dict[str, Any]], gnis: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for doc in docs:
        doc_id = str(doc.get("Id") or doc.get("doc_id") or "")
        if not doc_id:
            continue
        title_html = doc.get("TitleHtml") or ""
        title_plain = doc.get("Title") or strip_tags(title_html)
        if not title_html and title_plain:
            title_html = f'<div class="chunk-title">{title_plain}</div>'
        html = doc.get("Content") or '<div class="chunk-content"></div>'
        if html and 'class="chunk-content"' not in html:
            html = f'<div class="chunk-content">{html}</div>'
        try:
            order = int(doc.get("DocOrderId") or doc.get("doc_order") or 0)
        except (TypeError, ValueError):
            order = 0
        if order < 0:
            order = 0
        rows.append(
            {
                "cid": html_cid(str(gnis), doc_id),
                "doc_id": doc_id,
                "doc_order": order,
                "html_title": title_html,
                "html": html,
                "_title": title_plain,
            }
        )
    rows.sort(key=lambda r: (r["doc_order"], r["doc_id"]))
    return rows


def html_rows_to_citation_rows(
    html_rows: Sequence[Dict[str, Any]],
    *,
    place_name: str,
    state_code: str,
) -> List[Dict[str, Any]]:
    state_code = (state_code or "").upper()
    state_name = STATE_NAME.get(state_code, state_code)
    bb_state = BLUEBOOK_STATE.get(state_code, state_code)
    kind = _code_kind(place_name)
    chapter = ""
    chapter_num = ""
    out: List[Dict[str, Any]] = []
    for row in html_rows:
        title = row.get("_title") or strip_tags(row.get("html_title") or "")
        if re.match(r"(?i)^\s*chapter\s+", title):
            chapter = title
            chapter_num = extract_chapter_num(chapter)
        title_num = extract_title_num(title)
        notes = extract_history_notes(row.get("html") or "")
        if not notes:
            notes = [""]
        for note in notes:
            parsed = parse_history_fields(note) if note else {
                "history_note": "", "ordinance": "", "section": "",
                "date": "", "year": "", "enacted": "",
            }
            year = parsed["year"]
            cite = format_bluebook(place_name, bb_state, title_num, year, kind)
            out.append(
                {
                    "bluebook_cid": bluebook_cid(place_name, bb_state, title, parsed["history_note"]),
                    "cid": row["cid"],
                    "title": title,
                    "title_num": title_num,
                    "date": parsed["date"],
                    "public_law_num": "NA",
                    "chapter": chapter,
                    "chapter_num": chapter_num,
                    "history_note": parsed["history_note"],
                    "ordinance": parsed["ordinance"],
                    "section": parsed["section"],
                    "enacted": parsed["enacted"],
                    "year": year,
                    "place_name": place_name,
                    "state_name": state_name,
                    "state_code": state_code,
                    "bluebook_sate_code": bb_state,
                    "bluebook_citation": cite,
                }
            )
    return out


def _compression() -> str:
    pa, _pq = _ensure_pyarrow()
    try:
        if pa.Codec.is_available("zstd"):
            return "zstd"
    except Exception:
        pass
    return "snappy"


def _ensure_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        return pa, pq
    except ImportError as e:
        raise RuntimeError(
            "pyarrow is required. Use /workspace/muni/.venv or set PYTHONPATH to its site-packages."
        ) from e


def write_html_parquet(path: Path, rows: Sequence[Dict[str, Any]]) -> int:
    pa, pq = _ensure_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "cid": [r["cid"] for r in rows],
            "doc_id": [r["doc_id"] for r in rows],
            "doc_order": pa.array([int(r["doc_order"]) for r in rows], type=pa.uint32()),
            "html_title": [r["html_title"] for r in rows],
            "html": [r["html"] for r in rows],
        }
    )
    pq.write_table(table, str(path), compression=_compression())
    return table.num_rows


def write_citation_parquet(path: Path, rows: Sequence[Dict[str, Any]]) -> int:
    pa, pq = _ensure_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {col: [r.get(col, "") if r.get(col) is not None else "" for r in rows] for col in CITATION_COLUMNS}
    table = pa.table(data)
    pq.write_table(table, str(path), compression=_compression())
    return table.num_rows


def write_metadata(path: Path, place_name: str, state_code: str, total_sections: int, last_updated_ms: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if last_updated_ms is None:
        last_updated_ms = int(time.time() * 1000)
    path.write_text(
        json.dumps(
            {
                "place_name": place_name,
                "state_code": state_code,
                "total_sections": int(total_sections),
                "last_updated": int(last_updated_ms),
            },
            separators=(",", ":"),
        )
        + "\n"
    )


def write_jurisdiction(
    out_root: Path,
    gnis: str,
    html_rows: Sequence[Dict[str, Any]],
    place_name: str,
    state_code: str,
    last_updated_ms: Optional[int] = None,
) -> Dict[str, Any]:
    gnis = str(gnis)
    data_dir = Path(out_root) / "american_law" / "data"
    html_path = data_dir / f"{gnis}_html.parquet"
    cite_path = data_dir / f"{gnis}_citation.parquet"
    meta_path = data_dir / "metadata" / f"{gnis}.json"
    n_html = write_html_parquet(html_path, html_rows)
    cite_rows = html_rows_to_citation_rows(html_rows, place_name=place_name, state_code=state_code)
    n_cite = write_citation_parquet(cite_path, cite_rows)
    write_metadata(meta_path, place_name, state_code, n_html, last_updated_ms)
    return {
        "gnis": gnis,
        "html_rows": n_html,
        "citation_rows": n_cite,
        "html_path": str(html_path),
        "citation_path": str(cite_path),
        "metadata_path": str(meta_path),
    }


def validate_html_schema(path: Path, sample_path: Path) -> Dict[str, Any]:
    pa, pq = _ensure_pyarrow()
    got = pq.read_table(str(path))
    sample = pq.read_table(str(sample_path))
    sample_cols = [c for c in sample.column_names if c != "__index_level_0__"]
    got_cols = list(got.column_names)
    ok = got_cols == sample_cols
    type_ok = True
    notes = []
    if got_cols != sample_cols:
        notes.append(f"columns {got_cols} != sample {sample_cols}")
    for name in sample_cols:
        if name not in got.schema.names:
            type_ok = False
            continue
        st = sample.schema.field(name).type
        gt = got.schema.field(name).type
        if str(st) != str(gt):
            # uint32 vs int64 still acceptable for doc_order if values fit
            notes.append(f"type {name}: got {gt} sample {st}")
            if name != "doc_order":
                type_ok = False
    return {
        "ok": ok and ("__index_level_0__" not in got_cols),
        "columns": got_cols,
        "sample_columns_minus_index": sample_cols,
        "types_ok": type_ok,
        "compression_note": f"written with {_compression()}",
        "notes": notes,
        "rows": got.num_rows,
    }

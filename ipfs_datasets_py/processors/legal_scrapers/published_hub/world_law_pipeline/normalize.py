"""Normalize staged records to the world_municipal_law html-parquet schema."""
from __future__ import annotations

import html as _html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import schema as S  # noqa: E402
from world.common import html_to_text  # noqa: E402

_TRUE = {"true", "1", "yes", "y", "t"}
_FALSE = {"false", "0", "no", "n", "f"}


def _bool(v: Any) -> Any:
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        if s in ("", "null", "none", "unknown"):
            return None
    return v  # leave invalid -> validator flags it


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    s = str(v)
    return s if s.strip() else None


def _date(v: Any) -> Optional[str]:
    s = _str(v)
    if s is None:
        return None
    s = s.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ]", s)
    return m.group(1) if m else s


def _ts(v: Any, default: str) -> str:
    s = _str(v)
    if s is None:
        return default
    s = s.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$", s):
        return s + "Z"  # naive -> assume UTC
    return s


_KNOWN_KEYS = set(S.HTML_COLUMNS) | set(S.PLACE_FIELDS) | S.DROP_KEYS | {"extra_metadata"}


def provenance(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Optional provenance columns + extra_metadata JSON (all other staged keys, minus DROP_KEYS)."""
    subs = S._sub_dicts(rec)  # [top, extra_metadata, extra_metadata.archive]
    out: Dict[str, Any] = {}
    for k in S.PROVENANCE_STR + S.PROVENANCE_BOOL:
        v = None
        for d in subs:
            if d.get(k) not in (None, ""):
                v = d.get(k)
                break
        if k == "source_policy":
            v = ";".join(S.source_policies(rec)) or None
        elif k in S.PROVENANCE_BOOL:
            v = _bool(v)
        else:
            v = _str(v)
            v = v.strip() if v else None
        out[k] = v
    extra: Dict[str, Any] = {k: v for k, v in rec.items() if k not in _KNOWN_KEYS and v is not None}
    if len(subs) > 1:
        for k, v in subs[1].items():
            if k in S.DROP_KEYS or v is None:
                continue
            if k == "archive" and isinstance(v, dict):
                rest = {kk: vv for kk, vv in v.items() if kk not in out and kk not in S.DROP_KEYS}
                if rest:
                    extra.setdefault("archive", rest)
                continue
            if k in out or k in _KNOWN_KEYS:
                continue
            extra.setdefault(k, v)
    elif rec.get("extra_metadata") not in (None, "", {}):
        extra["extra_metadata"] = rec["extra_metadata"]  # non-dict payload kept verbatim
    out["extra_metadata"] = json.dumps(extra, ensure_ascii=False, sort_keys=True, default=str) if extra else None
    return out


def normalize_record(rec: Dict[str, Any], *, default_order: int, default_retrieved_at: str
                     ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (row with exactly S.HTML_COLUMNS, place_fields)."""
    r = dict(rec)
    cc = (_str(r.get("country_code")) or "").strip().upper() or None
    pid = (_str(r.get("place_id")) or "").strip() or None
    gnis = _str(r.get("gnis"))
    gnis = gnis.strip() if gnis else None
    if pid and pid.startswith("gnis:") and not gnis:
        gnis = pid[5:]
    if not pid and gnis and (cc or "US") == "US":
        pid = f"gnis:{gnis}"
        cc = cc or "US"
    doc_id = _str(r.get("doc_id"))
    doc_id = doc_id.strip() if doc_id else None
    lang = _str(r.get("language"))
    if lang:
        parts = lang.strip().replace("_", "-").split("-")
        lang = "-".join([parts[0].lower()] + parts[1:])
    title_native = _str(r.get("title_native"))
    number = _str(r.get("number"))
    html = _str(r.get("html"))
    text = _str(r.get("text"))
    if not html and text:
        html = f'<div class="chunk-content"><pre>{_html.escape(text)}</pre></div>'
    if not text and html:
        text = html_to_text(html) or None
    html_title = _str(r.get("html_title"))
    if not html_title and (title_native or number):
        html_title = f'<div class="chunk-title">{_html.escape(title_native or number)}</div>'
    try:
        order = int(r.get("doc_order")) if r.get("doc_order") not in (None, "") else default_order
    except (TypeError, ValueError):
        order = -1  # validator flags
    row: Dict[str, Any] = {
        "cid": None,
        "doc_id": doc_id,
        "doc_order": order,
        "html_title": html_title,
        "html": html,
        "place_id": pid,
        "country_code": cc,
        "gnis": gnis,
        "source_platform": _str(r.get("source_platform")),
        "source_url": (_str(r.get("source_url")) or "").strip() or None,
        "doc_type": (_str(r.get("doc_type")) or "").strip().lower() or None,
        "language": lang,
        "title_native": title_native,
        "number": number,
        "adopted_date": _date(r.get("adopted_date")),
        "published_date": _date(r.get("published_date")),
        "effective_date": _date(r.get("effective_date")),
        "in_force": _bool(r.get("in_force")),
        "consolidated": _bool(r.get("consolidated")),
        "content_format": (_str(r.get("content_format")) or "").strip().lower() or None,
        "text": text,
        "retrieved_at": _ts(r.get("retrieved_at"), default_retrieved_at),
    }
    row.update(provenance(r))
    row["pdf_ref"] = None  # v1.2.0: filled by the pipeline from state/pdf_refs/ (run_loop.build_place)
    if pid and doc_id:
        try:
            row["cid"] = S.html_cid(S.place_key(pid, gnis, cc), doc_id)
        except ValueError:
            pass
    place = {k: _str(r.get(k)) for k in S.PLACE_FIELDS if _str(r.get(k))}
    return row, place


def rows_to_table(rows: Sequence[Dict[str, Any]]):
    import pyarrow as pa
    sch = S.html_schema()
    return pa.Table.from_pylist([{c: r.get(c) for c in S.HTML_COLUMNS} for r in rows], schema=sch)


def write_html_parquet(path: Path, rows: Sequence[Dict[str, Any]]) -> int:
    """Atomic ZSTD write of the full world schema."""
    import pyarrow.parquet as pq
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = rows_to_table(rows)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(t, str(tmp), compression="zstd")
    tmp.replace(path)
    return t.num_rows


def us_html_rows_to_world(html_rows: Sequence[Dict[str, Any]], *, place_key: str, country_code: str,
                          place_id: Optional[str], gnis: Optional[str], source_platform: str,
                          source_url: str, language: str = "en", doc_type: str = "code_section",
                          consolidated: bool = True, retrieved_at: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lift rows from docs_to_html_rows() (US scrapers) into the world schema."""
    ra = retrieved_at or S.utc_now_iso()
    out = []
    for r in html_rows:
        out.append({
            "cid": r["cid"], "doc_id": r["doc_id"], "doc_order": int(r["doc_order"]),
            "html_title": r.get("html_title"), "html": r.get("html"),
            "place_id": place_id or (f"gnis:{gnis}" if gnis else S.place_id_from_key(place_key)),
            "country_code": country_code, "gnis": gnis, "source_platform": source_platform,
            "source_url": source_url, "doc_type": doc_type, "language": language,
            "title_native": r.get("_title") or None, "number": None, "adopted_date": None,
            "published_date": None, "effective_date": None, "in_force": None,
            "consolidated": consolidated, "content_format": "html",
            "text": html_to_text(r.get("html") or "") or None, "retrieved_at": ra,
        })
    return out

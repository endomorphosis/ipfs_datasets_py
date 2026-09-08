#!/usr/bin/env python3
"""Collect BOE legislación consolidada del Estado into JSON records.

Official source: https://www.boe.es/datosabiertos/api/legislacion-consolidada
Reuse: AEBOE resolución 27 Jun 2024 — https://www.boe.es/informacion/aviso_legal/index.php
Texts are consolidated and merely informative (not the authentic official gazette text).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import urllib3
from urllib3.util.retry import Retry

ROOT = Path("/workspace/legal-corpora/es")
INSTR = ROOT / "instruments"
LOGS = ROOT / "logs"
INDEX_PATH = ROOT / "index.jsonl"
FAILED_PATH = LOGS / "failed.jsonl"
CATALOG_PATH = LOGS / "catalog_estatal.jsonl"
SUMMARY_PATH = ROOT / "SUMMARY.md"
LOG_PATH = LOGS / "collector.log"

BASE = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
UA = (
    "legal-corpora-es-collector/1.0 "
    "(research corpus of BOE open data; polite; "
    "https://www.boe.es/datosabiertos/)"
)
LICENSE = (
    "BOE open data reuse terms (licencia tipo AEBOE, Resolución 27 junio 2024); "
    "https://www.boe.es/informacion/aviso_legal/index.php ; "
    "reutilización comercial y no comercial con atribución "
    "('Fuente de los datos: Agencia Estatal Boletín Oficial del Estado'); "
    "texto consolidado de carácter meramente informativo, sin valor oficial; "
    "no sugerir carácter oficial ni patrocinio de la AEBOE. "
    "Not CC-BY as a named instrument; official reuse licence equivalent in spirit to attribution."
)
TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")  # YYYYMMDD for version pick
WORKERS = 8
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

log = logging.getLogger("collector")
_index_lock = threading.Lock()
_fail_lock = threading.Lock()
_stats_lock = threading.Lock()
STATS = {
    "ok": 0,
    "fail": 0,
    "skip": 0,
    "bytes": 0,
    "empty_text": 0,
    "started": time.time(),
}


def setup_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    INSTR.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers.clear()
    log.addHandler(fh)
    log.addHandler(sh)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ymd(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def safe_id(ident: str) -> str:
    s = SAFE_RE.sub("_", ident.strip())
    return s or "unknown"


def local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def child_text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None:
        return None
    t = "".join(el.itertext()).strip()
    return t or None


def code_text(el: Optional[ET.Element]) -> Tuple[Optional[str], Optional[str]]:
    if el is None:
        return None, None
    return el.attrib.get("codigo"), (child_text(el) or None)


def make_http() -> urllib3.PoolManager:
    retry = Retry(
        total=6,
        connect=5,
        read=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    return urllib3.PoolManager(
        num_pools=4,
        maxsize=WORKERS + 2,
        retries=retry,
        timeout=urllib3.Timeout(connect=20.0, read=180.0),
        headers={"User-Agent": UA, "Accept": "application/xml"},
        block=True,
    )


def http_get(http: urllib3.PoolManager, url: str) -> Tuple[int, bytes]:
    last_err = None
    for attempt in range(6):
        try:
            r = http.request("GET", url, preload_content=True)
            status = r.status
            data = r.data or b""
            if status in (429, 500, 502, 503, 504):
                time.sleep(min(30, 1.5 ** attempt) + 0.05 * attempt)
                last_err = f"HTTP {status}"
                continue
            return status, data
        except Exception as e:
            last_err = str(e)
            time.sleep(min(30, 1.5 ** attempt))
    raise RuntimeError(f"GET failed after retries: {url} ({last_err})")


def version_sort_key(ver: ET.Element) -> Tuple[str, str]:
    fv = ver.attrib.get("fecha_vigencia") or ""
    fp = ver.attrib.get("fecha_publicacion") or ""
    return (fv or fp or "", fp or "")


def pick_current_version(bloque: ET.Element) -> Optional[ET.Element]:
    versions = [c for c in list(bloque) if local(c.tag) == "version"]
    if not versions:
        return None
    in_force = []
    for v in versions:
        fv = v.attrib.get("fecha_vigencia") or v.attrib.get("fecha_publicacion") or ""
        if not fv or fv <= TODAY:
            in_force.append(v)
    pool = in_force or versions
    return max(pool, key=version_sort_key)


def element_lines(el: ET.Element) -> List[str]:
    """Flatten a version (or similar) into readable lines, preserving block structure."""
    lines: List[str] = []

    def walk(node: ET.Element, depth: int = 0) -> None:
        tag = local(node.tag).lower()
        if tag in ("version",):
            for ch in list(node):
                walk(ch, depth + 1)
            return
        if tag in ("p", "h1", "h2", "h3", "h4", "li", "titulo", "nota"):
            txt = " ".join("".join(node.itertext()).split())
            if txt:
                lines.append(txt)
            return
        if tag in ("br",):
            return
        if tag in ("table",):
            for tr in node.iter():
                if local(tr.tag).lower() == "tr":
                    cells = []
                    for cell in list(tr):
                        if local(cell.tag).lower() in ("td", "th"):
                            cells.append(" ".join("".join(cell.itertext()).split()))
                    row = " | ".join(c for c in cells if c)
                    if row:
                        lines.append(row)
            return
        if tag in ("ul", "ol", "div", "span", "blockquote", "section"):
            for ch in list(node):
                walk(ch, depth + 1)
            return
        txt = " ".join("".join(node.itertext()).split())
        if txt:
            lines.append(txt)

    for ch in list(el):
        walk(ch)
    if not lines:
        txt = " ".join("".join(el.itertext()).split())
        if txt:
            lines.append(txt)
    return lines


def parse_metadatos(meta: Optional[ET.Element]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if meta is None:
        return out
    for ch in list(meta):
        name = local(ch.tag)
        if name in ("ambito", "departamento", "rango", "estado_consolidacion"):
            code, text = code_text(ch)
            out[name] = {"codigo": code, "texto": text}
        else:
            out[name] = child_text(ch)
    return out


def parse_materias(analisis: Optional[ET.Element]) -> List[Dict[str, str]]:
    mats: List[Dict[str, str]] = []
    if analisis is None:
        return mats
    for m in analisis.iter():
        if local(m.tag) == "materia":
            code = m.attrib.get("codigo")
            text = child_text(m)
            if code or text:
                mats.append({"codigo": code or "", "texto": text or ""})
    return mats


def build_record(ident: str, catalog_item: Dict[str, Any], xml_bytes: bytes) -> Dict[str, Any]:
    retrieved = iso_now()
    root = ET.fromstring(xml_bytes)
    status_el = None
    data_el = None
    for ch in list(root):
        t = local(ch.tag)
        if t == "status":
            status_el = ch
        elif t == "data":
            data_el = ch
    status_code = None
    if status_el is not None:
        for ch in list(status_el):
            if local(ch.tag) == "code":
                status_code = child_text(ch)
    if status_code and status_code != "200":
        raise RuntimeError(f"API status {status_code} for {ident}")
    if data_el is None:
        raise RuntimeError(f"no <data> for {ident}")

    meta_el = None
    analisis_el = None
    texto_el = None
    for ch in list(data_el):
        t = local(ch.tag)
        if t == "metadatos":
            meta_el = ch
        elif t == "analisis":
            analisis_el = ch
        elif t == "texto":
            texto_el = ch

    meta = parse_metadatos(meta_el)
    # fill from catalog if XML meta sparse
    def cat(key, default=None):
        v = catalog_item.get(key)
        if isinstance(v, dict):
            return v
        return v if v is not None else default

    title = meta.get("titulo") or catalog_item.get("titulo") or ident
    url_eli = meta.get("url_eli") or catalog_item.get("url_eli")
    html_url = (
        meta.get("url_html_consolidada")
        or catalog_item.get("url_html_consolidada")
        or f"https://www.boe.es/buscar/act.php?id={ident}"
    )
    api_url = f"{BASE}/id/{ident}"
    date_issued = ymd(meta.get("fecha_disposicion") or catalog_item.get("fecha_disposicion"))
    materias = parse_materias(analisis_el)

    documents: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    n_blocks = 0
    n_with_version = 0
    if texto_el is not None:
        for bloque in list(texto_el):
            if local(bloque.tag) != "bloque":
                continue
            n_blocks += 1
            bid = bloque.attrib.get("id") or f"bloque-{n_blocks}"
            btipo = bloque.attrib.get("tipo") or ""
            ver = pick_current_version(bloque)
            if ver is None:
                continue
            n_with_version += 1
            lines = element_lines(ver)
            body = "\n".join(lines).strip()
            heading = lines[0] if lines else ""
            if heading and len(heading) > 240:
                heading = heading[:237] + "..."
            doc_title = heading or (f"{btipo} {bid}".strip())
            if body:
                if heading and heading != title:
                    text_parts.append(heading)
                    rest = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
                    if rest:
                        text_parts.append(rest)
                else:
                    text_parts.append(body)
            documents.append(
                {
                    "id": f"{ident}/{bid}",
                    "title": doc_title,
                    "text": body,
                    "source_url": f"{BASE}/id/{ident}/texto/bloque/{bid}",
                    "metadata": {
                        "block_id": bid,
                        "block_type": btipo,
                        "id_norma": ver.attrib.get("id_norma"),
                        "fecha_publicacion": ymd(ver.attrib.get("fecha_publicacion")),
                        "fecha_vigencia": ymd(ver.attrib.get("fecha_vigencia")),
                        "n_versions_in_block": sum(
                            1 for c in list(bloque) if local(c.tag) == "version"
                        ),
                    },
                }
            )

    full_text = "\n\n".join(p for p in text_parts if p).strip()
    notice = (
        "Texto consolidado de carácter meramente informativo, sin valor oficial. "
        "Únicamente tienen carácter oficial y auténtico los textos publicados en "
        "el Boletín Oficial del Estado."
    )
    if full_text:
        full_text = notice + "\n\n" + full_text
    else:
        full_text = notice

    rango = meta.get("rango") or cat("rango") or {}
    depto = meta.get("departamento") or cat("departamento") or {}
    ambito = meta.get("ambito") or cat("ambito") or {}
    estado = meta.get("estado_consolidacion") or cat("estado_consolidacion") or {}

    record = {
        "id": ident,
        "title": title,
        "jurisdiction": "ES",
        "country": "Spain",
        "language": "es",
        "source_type": "national_legislation",
        "source_url": html_url,
        "eli": url_eli or None,
        "date_issued": date_issued,
        "text": full_text,
        "documents": documents,
        "metadata": {
            "license": LICENSE,
            "retrieved_at": retrieved,
            "official_id": ident,
            "publisher": "BOE",
            "source_name": "boe.es",
            "reuse_terms_url": "https://www.boe.es/informacion/aviso_legal/index.php",
            "api_url": api_url,
            "texto_consolidado_informativo": True,
            "ambito": ambito.get("texto") if isinstance(ambito, dict) else ambito,
            "departamento": depto.get("texto") if isinstance(depto, dict) else depto,
            "rango": rango.get("texto") if isinstance(rango, dict) else rango,
            "numero_oficial": meta.get("numero_oficial") or catalog_item.get("numero_oficial"),
            "diario": meta.get("diario") or catalog_item.get("diario"),
            "fecha_publicacion": ymd(meta.get("fecha_publicacion") or catalog_item.get("fecha_publicacion")),
            "fecha_vigencia": ymd(meta.get("fecha_vigencia") or catalog_item.get("fecha_vigencia")),
            "fecha_actualizacion": meta.get("fecha_actualizacion")
            or catalog_item.get("fecha_actualizacion"),
            "vigencia_agotada": meta.get("vigencia_agotada") or catalog_item.get("vigencia_agotada"),
            "estatus_derogacion": meta.get("estatus_derogacion"),
            "estatus_anulacion": meta.get("estatus_anulacion"),
            "estado_consolidacion": estado.get("texto") if isinstance(estado, dict) else estado,
            "materias": materias,
            "n_blocks": n_blocks,
            "n_current_blocks": n_with_version,
            "collection": "legislacion-consolidada-estatal",
        },
    }
    return record


def load_done() -> set:
    done = set()
    if not INDEX_PATH.exists():
        return done
    with INDEX_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "ok" and rec.get("id"):
                done.add(rec["id"])
    return done


def load_catalog() -> List[Dict[str, Any]]:
    items = []
    with CATALOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def append_jsonl(path: Path, obj: Dict[str, Any], lock: threading.Lock) -> None:
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    with lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def write_instrument(sid: str, record: Dict[str, Any]) -> int:
    dest = INSTR / f"{sid}.json"
    tmp = INSTR / f".{sid}.json.tmp"
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, dest)
    return dest.stat().st_size


def process_one(
    http: urllib3.PoolManager, item: Dict[str, Any]
) -> Tuple[str, str, Optional[int], Optional[str]]:
    ident = item["identificador"]
    sid = safe_id(ident)
    url = f"{BASE}/id/{ident}"
    status, data = http_get(http, url)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {ident} ({len(data)} bytes)")
    if not data.lstrip().startswith(b"<?xml") and not data.lstrip().startswith(b"<"):
        raise RuntimeError(f"non-XML body for {ident}: {data[:120]!r}")
    record = build_record(ident, item, data)
    nbytes = write_instrument(sid, record)
    empty = not (record.get("text") or "").replace(
        "Texto consolidado de carácter meramente informativo, sin valor oficial. "
        "Únicamente tienen carácter oficial y auténtico los textos publicados en "
        "el Boletín Oficial del Estado.",
        "",
    ).strip()
    append_jsonl(
        INDEX_PATH,
        {
            "id": ident,
            "safe_id": sid,
            "status": "ok",
            "title": record.get("title"),
            "source_url": record.get("source_url"),
            "eli": record.get("eli"),
            "date_issued": record.get("date_issued"),
            "bytes": nbytes,
            "n_documents": len(record.get("documents") or []),
            "empty_body": empty,
            "retrieved_at": record["metadata"]["retrieved_at"],
        },
        _index_lock,
    )
    return ident, "ok", nbytes, None if not empty else "empty_body"


def write_summary(listed: int, note: str = "") -> None:
    bytes_total = 0
    n_ok = 0
    n_empty = 0
    if INDEX_PATH.exists():
        with INDEX_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "ok":
                    n_ok += 1
                    bytes_total += int(rec.get("bytes") or 0)
                    if rec.get("empty_body"):
                        n_empty += 1
    n_fail = 0
    fail_examples = []
    if FAILED_PATH.exists():
        with FAILED_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                n_fail += 1
                if len(fail_examples) < 15:
                    fail_examples.append(f"- {rec.get('id')}: {rec.get('error')}")
    inst_count = len(list(INSTR.glob("*.json")))
    elapsed = time.time() - STATS["started"]
    body = f"""# Spain — legislación consolidada del Estado (BOE)

Collection of **current Spanish state consolidated legislation** from the official
BOE open-data API. Consolidated texts are **merely informative** and have no official
authentic value (only the electronic BOE gazette text is authentic).

## Source

- Publisher: Agencia Estatal Boletín Oficial del Estado (BOE)
- API: https://www.boe.es/datosabiertos/api/legislacion-consolidada
- Docs: https://www.boe.es/datosabiertos/ / https://boe.es/datosabiertos/documentos/APIconsolidada.pdf
- ELI: https://www.boe.es/legislacion/eli.php
- Scope filter: `ambito@codigo:1` (Estatal). Autonómica excluded.
- Per-instrument endpoint: `GET /id/{{id}}` (XML: metadatos + análisis + texto with all block versions)
- Current text: in-force version of each block as of `{TODAY}` (`fecha_vigencia`/`fecha_publicacion` ≤ today; else latest version)

## License / reuse

{LICENSE}

## Counts

| Metric | Value |
|---|---|
| Listed (catalog, estatal) | {listed} |
| Collected (index ok) | {n_ok} |
| Instrument JSON files | {inst_count} |
| Failed (last-run log) | {n_fail} |
| Empty body (notice only) | {n_empty} |
| Bytes on disk (instrument JSON) | {bytes_total} ({bytes_total/1_000_000:.1f} MB) |
| Elapsed (this process, s) | {elapsed:.0f} |
| Retrieved (UTC) | {iso_now()} |

## Layout

- `instruments/{{safe_id}}.json` — one record per consolidada
- `index.jsonl` — resume index
- `logs/catalog_estatal.jsonl` — API list of estatal instruments
- `logs/collector.log` — collector log
- `logs/failed.jsonl` — per-item failures (retried on resume)

{note}

## Failures (sample)

{chr(10).join(fail_examples) if fail_examples else "(none)"}

## Record notes

- `text` is the concatenated current consolidated body, prefixed with the official
  informative-character notice required by BOE reuse conditions.
- `documents[]` are current versions of each consolidada block (artículo, disposición, anexo, …).
- Historical intermediate versions remain in the BOE API but are not duplicated into `text`.
"""
    SUMMARY_PATH.write_text(body, encoding="utf-8")


def main() -> int:
    setup_logging()
    INSTR.mkdir(parents=True, exist_ok=True)
    listed_items = load_catalog()
    listed = len(listed_items)
    done = load_done()
    pending = [it for it in listed_items if it.get("identificador") not in done]
    log.info(
        "catalog=%s done=%s pending=%s workers=%s today=%s",
        listed,
        len(done),
        len(pending),
        WORKERS,
        TODAY,
    )
    STATS["skip"] = len(done)
    write_summary(listed, note="Run in progress.")
    if not pending:
        log.info("nothing pending")
        write_summary(listed, note="Complete — nothing pending.")
        return 0

    http = make_http()
    processed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_one, http, it): it.get("identificador") for it in pending}
        for fut in as_completed(futs):
            ident = futs[fut]
            processed += 1
            try:
                ident, status, nbytes, extra = fut.result()
                with _stats_lock:
                    STATS["ok"] += 1
                    STATS["bytes"] += nbytes or 0
                    if extra == "empty_body":
                        STATS["empty_text"] += 1
                if processed % 25 == 0 or processed == len(pending):
                    log.info(
                        "progress %s/%s ok=%s fail=%s skip=%s bytes=%s last=%s",
                        processed,
                        len(pending),
                        STATS["ok"],
                        STATS["fail"],
                        STATS["skip"],
                        STATS["bytes"],
                        ident,
                    )
                if processed % 200 == 0:
                    write_summary(listed, note="Run in progress.")
            except Exception as e:
                with _stats_lock:
                    STATS["fail"] += 1
                err = f"{type(e).__name__}: {e}"
                log.warning("FAIL %s %s", ident, err)
                append_jsonl(
                    FAILED_PATH,
                    {"id": ident, "error": err, "trace": traceback.format_exc()[-2000:], "at": iso_now()},
                    _fail_lock,
                )
                if processed % 25 == 0:
                    log.info(
                        "progress %s/%s ok=%s fail=%s",
                        processed,
                        len(pending),
                        STATS["ok"],
                        STATS["fail"],
                    )

    write_summary(
        listed,
        note=f"Finished. ok={STATS['ok']} fail={STATS['fail']} skipped_resume={STATS['skip']}",
    )
    log.info("DONE ok=%s fail=%s skip=%s bytes=%s", STATS["ok"], STATS["fail"], STATS["skip"], STATS["bytes"])
    return 0 if STATS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

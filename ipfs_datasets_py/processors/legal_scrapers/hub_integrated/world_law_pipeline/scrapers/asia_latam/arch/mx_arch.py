#!/usr/bin/env python3
"""Mexico Orden Jurídico Nacional (www.ordenjuridico.gob.mx; TLS EOF from the box egress) state & municipal law
from web archives -> staging/asia_latam/MX/.

  mx_arch.py [--max-fetch N] [--rediscover]

Discovery: Wayback (+CC when cached) listing of /Documentos/Estatal/ (PDF/DOC). Folder <Estado>/ -> state law,
place iso:MX-XX (adm1); folder <Estado>/Todos los Municipios/ -> municipal law: the municipio is read from the
document text ("Municipio de X" / "Ayuntamiento de X") and matched within the state to INEGI codes (Wikidata P3801,
mx/wd_P3801.csv) -> wd:Q in the candidate CSV; unmatched -> _unmatched_mx.csv.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, csv, hashlib, json, logging, os, re, sys, time, unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from arch_common import wb_deferred, WBDeferred  # noqa: E402,F401
from arch_common import STAGE, STOP, ArchiveError, ArchiveFetcher, CheckedFetcher, Capture, State, append_csv, pdf_text, provenance_fields  # noqa
from common_docx import docx_text  # noqa: E402

JOB = "MX_ordenjuridico_archive"
log = logging.getLogger(JOB)
STATES = {  # INEGI state code -> (ISO 3166-2, folder names)
    "01": ("MX-AGU", ["aguascalientes"]), "02": ("MX-BCN", ["baja california"]), "03": ("MX-BCS", ["baja california sur"]),
    "04": ("MX-CAM", ["campeche"]), "05": ("MX-COA", ["coahuila", "coahuila de zaragoza"]), "06": ("MX-COL", ["colima"]),
    "07": ("MX-CHP", ["chiapas"]), "08": ("MX-CHH", ["chihuahua"]), "09": ("MX-CMX", ["distrito federal", "ciudad de mexico"]),
    "10": ("MX-DUR", ["durango"]), "11": ("MX-GUA", ["guanajuato"]), "12": ("MX-GRO", ["guerrero"]), "13": ("MX-HID", ["hidalgo"]),
    "14": ("MX-JAL", ["jalisco"]), "15": ("MX-MEX", ["estado de mexico", "mexico"]), "16": ("MX-MIC", ["michoacan"]),
    "17": ("MX-MOR", ["morelos"]), "18": ("MX-NAY", ["nayarit"]), "19": ("MX-NLE", ["nuevo leon"]), "20": ("MX-OAX", ["oaxaca"]),
    "21": ("MX-PUE", ["puebla"]), "22": ("MX-QUE", ["queretaro"]), "23": ("MX-ROO", ["quintana roo"]),
    "24": ("MX-SLP", ["san luis potosi"]), "25": ("MX-SIN", ["sinaloa"]), "26": ("MX-SON", ["sonora"]), "27": ("MX-TAB", ["tabasco"]),
    "28": ("MX-TAM", ["tamaulipas"]), "29": ("MX-TLA", ["tlaxcala"]), "30": ("MX-VER", ["veracruz"]), "31": ("MX-YUC", ["yucatan"]),
    "32": ("MX-ZAC", ["zacatecas"]),
}
FOLDER2STATE = {f: k for k, (_, fs) in STATES.items() for f in fs}
DOC_RX = re.compile(r"(?i)ordenjuridico\.gob\.mx(?::\d+)?/Documentos/Estatal/(.+?)/([^/]+\.(?:pdf|docx?))$")
MUNI_RX = re.compile(r"(?i)\b(?:municipio|ayuntamiento(?: constitucional)?|h\. ayuntamiento)\s+(?:de|del)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\. ]{2,50}?)(?=[,\.;:\n]|\s+(?:del estado|estado|jal|zac|ver|pue|en|para|que|y)\b)")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(municipio|ayuntamiento)\s+(de|del)\s+", "", s.strip())
    return re.sub(r"[^a-z0-9]", "", s)


class Places:
    def __init__(self):
        cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"),
                                                          encoding="utf-8")) if r["country_code"] == "MX"}
        self.cand = cand
        self.lut = {}
        for r in csv.DictReader(open(HERE.parent / "mx" / "wd_P3801.csv", encoding="utf-8")):
            q = r["item"].rsplit("/", 1)[-1]
            code = r["code"].zfill(5)
            if q in cand:
                self.lut.setdefault((code[:2], norm(r["itemLabel"])), set()).add((q, code))

    def resolve(self, st, name):
        hits = self.lut.get((st, norm(name)), set())
        if len(hits) == 1:
            q, code = next(iter(hits))
            return self.cand[q], code
        return None, None


class Job:
    def __init__(self, a):
        self.a = a
        self.st = State(JOB, "MX", batch_prefix="archive", chunk=100)
        self.fx = CheckedFetcher(cc_crawls=4)
        self.P = Places()

    def discover(self):
        caps = []
        url = "www.ordenjuridico.gob.mx/Documentos/Estatal/"
        if self.a.cc:
            caps += self.fx.cc_captures(url, "prefix")
        caps += self.fx.wb_captures(url, "prefix", collapse="urlkey", max_rows=300000)
        cand = {}
        for c in caps:
            if c.status not in (200, None):
                continue
            m = DOC_RX.search(unquote(c.original_url))
            if not m:
                continue
            k = (m.group(1) + "/" + m.group(2)).lower()
            cand.setdefault(k, []).append(c)
        out = []
        for k, cs in sorted(cand.items()):
            cs.sort(key=lambda c: (c.source == "commoncrawl", c.timestamp), reverse=True)
            out.append({"key": k, "caps": [c.to_dict() for c in cs[:3]]})
        with (self.st.dir / "candidates.jsonl.tmp").open("w") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(self.st.dir / "candidates.jsonl.tmp", self.st.dir / "candidates.jsonl")
        (self.st.dir / "discovery.json").write_text(json.dumps({"captures": len(caps), "candidates": len(out)}))
        return out

    def build(self, r, doc):
        folder = r["key"].rsplit("/", 1)[0]
        parts = folder.split("/")
        fn = unicodedata.normalize("NFKD", parts[0]).encode("ascii", "ignore").decode().lower().strip()
        st = FOLDER2STATE.get(fn)
        if not st:
            return None, "unknown_state_folder"
        if doc.body[:5] == b"%PDF-":
            text, fmt = pdf_text(doc.body), "pdf_text"
        elif doc.body[:2] == b"PK":
            text, fmt = docx_text(doc.body), "docx_text"
        else:
            return None, "unsupported_format"  # legacy .doc (OLE) not converted
        if len(text) < 300:
            return None, "no_text"
        lines = [l.strip() for l in text[:4000].split("\n") if l.strip()]
        title = next((l for l in lines if re.match(r"(?i)(ley|c[oó]digo|reglamento|bando|decreto|estatuto|constituci|lineamientos|acuerdo|norma)", l)), lines[0])[:500]
        iso, _ = STATES[st]
        municipal = len(parts) > 1 and "municipio" in parts[1]
        if municipal:
            row = None
            for m in MUNI_RX.finditer(text[:6000]):
                row, code = self.P.resolve(st, m.group(1))
                if row:
                    break
            if not row:
                append_csv(STAGE / "_unmatched_mx.csv", ["key", "url", "state", "first_muni_mention", "at"],
                           [r["key"], doc.original_url, st, (MUNI_RX.search(text[:6000]) or [None, ""])[1] if MUNI_RX.search(text[:6000]) else "",
                            time.strftime("%Y-%m-%d %H:%M")])
                return None, "unmatched_municipio"
            place = {"place_id": row["place_id"], "place_name": row["place_name"], "qid": row["qid"],
                     "admin_level": row["admin_level"] or "municipality", "iso_3166_2": iso, "platform_place_id": code}
        else:
            place = {"place_id": f"iso:{iso}", "place_name": parts[0], "admin_level": "adm1", "iso_3166_2": iso,
                     "platform_place_id": st}
        dt = "ordinance" if municipal and re.search(r"(?i)bando|reglamento", title) else (
            "statute" if re.search(r"(?i)^(ley|c[oó]digo|constituci)", title) else "regulation")
        rec = {"place_id": place["place_id"], "country_code": "MX", "doc_id": "mx_ojn:" + r["key"],
               "source_platform": "mx_ordenjuridico", "source_url": doc.original_url, "doc_type": dt, "language": "es",
               "html_title": title, "title_native": title, "consolidated": True, "in_force": None, "content_format": fmt,
               "text": text, "retrieved_at": doc.fetched_at, "platform": "mx_ordenjuridico",
               **{k: v for k, v in place.items() if k != "place_id"},
               "source_policy": "network_blocked_archive_fallback",
               "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
        rec.update(provenance_fields(doc))
        return {k: v for k, v in rec.items() if v not in (None, "") or k == "in_force"}, "ok"

    def run(self):
        cp = self.st.dir / "candidates.jsonl"
        cands = self.discover() if (self.a.rediscover or not cp.exists()) else [json.loads(l) for l in cp.open()]
        # municipal folders first (the lane's focus), then state law
        cands.sort(key=lambda r: 0 if "/todos los municipios/" in r["key"] else 1)
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
                rec, why = self.build(r, doc)
            except Exception as e:
                log.exception("build %s", r["key"]); rec, why = None, f"error:{type(e).__name__}"
            if rec is None:
                self.st.stats[why] += 1; self.st.mark(r["key"], why); continue
            self.st.add(r["key"], rec)
            self.st.maybe_flush(1800)
            if n % 25 == 0:
                self.st.save(self.fx)
        self.st.flush()
        self.st.save(self.fx, final=not STOP["flag"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--cc", action="store_true")
    Job(ap.parse_args()).run()


if __name__ == "__main__":
    main()
    import arch_common as _ac
    sys.exit(_ac.exit_code())

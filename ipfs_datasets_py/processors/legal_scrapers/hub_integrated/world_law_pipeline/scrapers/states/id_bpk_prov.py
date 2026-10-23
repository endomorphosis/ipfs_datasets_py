"""Indonesia BPK JDIH (peraturan.bpk.go.id) PROVINCE regulations (Perda/Pergub/Kepgub Provinsi) from web archives
-> iso:ID-<prov>.

Live: peraturan.bpk.go.id answers a Cloudflare challenge (403 "Just a moment...") even for /robots.txt (2026-10-17 PT)
=> not bypassed; robots unreachable => disallow-all; archive-only (Wayback; CC when available).
Candidates: national lane ID_bpk_regional discovery (1,235 Details pages, perda|pergub|kepgub-prov-*); kabupaten/kota
acts are the asia_latam lane's (ID_bpk_kabkota, doc_id id_bpk:<n>), national acts the national lane's.
Details page metadata parsing (parse_meta / id_date) is copied from asia_latam/arch/id_bpk.py; the archived-PDF index
(/Download/<id>/ captures) is that job's pdf_index.jsonl, read-only. doc_id id_bpk_regional:<n> as in the national lane.
Text-layer PDF -> pdf_text (metadata block + PDF text); image-only PDF -> OCR manifest + content_complete=false row;
PDF not archived -> metadata/abstract row with content_complete=false.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import hashlib, json, re
from urllib.parse import urljoin

from archive.core import Capture, ArchiveTransient
from deferq import fetch_best_or_defer  # noqa: E402  (deferral-aware fetch_best)
from arch_common import html_extract, pdf_text, has_text, clean, queue_scanned_pdf_archived, archived_rec
from places import ID_PROV, norm, id_province_from_slug  # national lane table (read-only)

POLICY = "archived_robots_disallowed"
BASIS = "robots.txt behind Cloudflare challenge (403 'Just a moment...') on peraturan.bpk.go.id, 2026-10-17 => disallow-all; not bypassed; archived copies only"
PDF_INDEX = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_archive_work/ID_bpk_kabkota/pdf_index.jsonl")
DL = re.compile(r"(?i)/(?:Download|Read)/(\d+)/")
FIELDS = ["Judul", "T.E.U.", "Nomor", "Bentuk", "Bentuk Singkat", "Tahun", "Tempat Penetapan", "Tanggal Penetapan",
          "Tanggal Pengundangan", "Tanggal Berlaku", "Sumber", "Subjek", "Status", "Bahasa", "Lokasi", "Bidang"]
MONTHS = {m: i + 1 for i, m in enumerate("januari februari maret april mei juni juli agustus september oktober november "
                                          "desember".split())}
MONTHS.update({"nopember": 11, "pebruari": 2})
PROV_NAMES = {"AC": "Aceh", "SU": "Sumatera Utara", "SB": "Sumatera Barat", "RI": "Riau", "KR": "Kepulauan Riau",
              "JA": "Jambi", "SS": "Sumatera Selatan", "BB": "Kepulauan Bangka Belitung", "BE": "Bengkulu", "LA": "Lampung",
              "JK": "DKI Jakarta", "JB": "Jawa Barat", "BT": "Banten", "JT": "Jawa Tengah", "YO": "DI Yogyakarta",
              "JI": "Jawa Timur", "BA": "Bali", "NB": "Nusa Tenggara Barat", "NT": "Nusa Tenggara Timur",
              "KB": "Kalimantan Barat", "KT": "Kalimantan Tengah", "KS": "Kalimantan Selatan", "KI": "Kalimantan Timur",
              "KU": "Kalimantan Utara", "SA": "Sulawesi Utara", "ST": "Sulawesi Tengah", "SN": "Sulawesi Selatan",
              "SG": "Sulawesi Tenggara", "GO": "Gorontalo", "SR": "Sulawesi Barat", "MA": "Maluku", "MU": "Maluku Utara",
              "PA": "Papua", "PB": "Papua Barat", "PE": "Papua Pegunungan", "PS": "Papua Selatan", "PT": "Papua Tengah",
              "PD": "Papua Barat Daya"}


def id_date(s):   # copied from asia_latam/arch/id_bpk.py
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+((?:19|20)\d\d)", s or "")
    if not m:
        return None
    mo = MONTHS.get(m.group(2).lower())
    return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}" if mo else None


def parse_meta(text):   # copied from asia_latam/arch/id_bpk.py
    k = text.find("\nMETADATA")
    lines = (text[k:] if k >= 0 else text).split("\n")
    meta, i, labels = {}, 0, set(FIELDS)
    while i < len(lines):
        l = lines[i].strip()
        if l in labels and l not in meta and i + 1 < len(lines):
            j, vals = i + 1, []
            while j < len(lines) and lines[j].strip() not in labels and len(vals) < 4:
                v = lines[j].strip()
                if v in ("UJI MATERI", "FILE-FILE", "Bidang") or v.startswith("Halaman ini"):
                    break
                vals.append(v); j += 1
                if l not in ("Subjek", "Bidang"):
                    break
            meta[l] = " ; ".join(vals); i = j
        else:
            i += 1
    return meta


def prov_from_teu(teu):
    m = re.search(r"Provinsi\s+([A-Za-z .'-]+)", teu or "")
    if not m:
        return None
    key = norm(m.group(1))
    best = max((k for k in ID_PROV if key == k or key.startswith(k)), key=len, default=None)
    return f"ID-{ID_PROV[best]}" if best else None


class Adapter:
    key = "id_bpk_prov"
    nat_target = "ID_bpk_regional"
    tag = "id_bpk_regional-archive"
    platform = "id_bpk_regional"

    def __init__(self):
        self.dl = {}
        try:
            for l in open(PDF_INDEX, encoding="utf-8"):
                r = json.loads(l); self.dl[r["id"]] = r["caps"]
        except OSError:
            pass

    def eligible(self, r):
        return None

    def build(self, r, doc):
        title0, page_title, text, links = html_extract(doc.text(), [], None)
        meta = parse_meta(text)
        teu = meta.get("T.E.U.", "")
        if re.search(r"\b(Kabupaten|Kota)\b", teu):
            return None, "kabkota_level"
        code = prov_from_teu(teu)
        how = "teu"
        if not code:
            p = id_province_from_slug(doc.original_url.rstrip("/").rsplit("/", 1)[-1].lower())
            code, how = (p[0] if p else None), "slug"
        if not code:
            return None, "no_place:" + teu[:40]
        title = meta.get("Judul") or page_title
        head = "\n".join(f"{k}: {meta[k]}" for k in FIELDS if meta.get(k))
        i = text.find("ABSTRAK:")
        abstrak = clean(text[i:i + 6000]) if i >= 0 else ""
        seen, pdocs, ptxts, scanned = [], [], [], []
        for href in links:
            m = DL.search(href or "")
            if not m or m.group(1) in seen:
                continue
            seen.append(m.group(1))
            caps = self.dl.get(m.group(1))
            if not caps:
                try:
                    caps = [c.to_dict() for c in self.fx.wb_captures(urljoin(doc.original_url, href), "exact", limit=-3)]
                except ArchiveTransient:
                    raise
                except Exception:
                    caps = []
            if not caps or len(pdocs) >= 3:
                continue
            pdoc = fetch_best_or_defer(self.fx, [Capture(**c) for c in caps], max_tries=2)   # ItemDeferred -> requeued
            # None = true miss (round 3); throttle/timeout/breaker raise ArchiveDeferred -> item requeued
            if pdoc is not None and pdoc.body[:5] == b"%PDF-":
                t = pdf_text(pdoc.body)
                if has_text(t):
                    pdocs.append(pdoc); ptxts.append(t)
                else:
                    scanned.append(pdoc)
        pid = f"iso:{code}"
        did = f"{self.platform}:{r['key']}"
        queued = False
        if ptxts:
            body, fmt = title + "\n\n" + head + "\n\n" + "\n\n".join(ptxts), "pdf_text"
            missing = len(seen) - len(pdocs)
            complete = doc.content_complete and all(p.content_complete for p in pdocs) and missing == 0
            reason = f"pdf_not_archived_or_scanned:{missing}_of_{len(seen)}" if missing else None
        else:
            body, fmt, complete = title + "\n\n" + head + ("\n\n" + abstrak if abstrak else ""), "html", False
            reason = ("scanned_pdf_no_text_layer:queued_for_ocr" if scanned else
                      "landing_page_only:pdf_not_archived" if seen else "landing_page_only:no_pdf_link")
        if scanned and not ptxts:
            sp = scanned[0]
            queued = queue_scanned_pdf_archived(did, pid, "ID", sp.original_url, sp.archive_url, POLICY,
                                                sp.archive_timestamp, hashlib.sha256(sp.body).hexdigest(),
                                                sp.archive_source, sp.archive_crawl_id, sp.content_type or "application/pdf")
        status = (meta.get("Status") or "").lower()
        rec = {
            "place_id": pid, "country_code": "ID", "doc_id": did, "source_platform": self.platform,
            "source_url": doc.original_url, "doc_type": "regulation", "language": "id",
            "title_native": (title or r["key"])[:1000], "consolidated": False, "content_format": fmt,
            "text": clean(body), "retrieved_at": doc.fetched_at, "place_name": PROV_NAMES.get(code[3:], code),
            "iso_3166_2": code, "admin_level": "adm1", "platform": self.platform, "platform_place_id": code,
            "source_official": True, "source_org": "JDIH BPK RI (peraturan.bpk.go.id), Badan Pemeriksa Keuangan",
            "license_note": "Indonesian regulations are not subject to copyright (UU 28/2014 Hak Cipta, Pasal 42); archived copy via web archive",
        }
        if meta.get("Nomor"):
            rec["number"] = meta["Nomor"] + (f"/{meta['Tahun']}" if meta.get("Tahun") else "")
        for k, f in (("adopted_date", "Tanggal Penetapan"), ("published_date", "Tanggal Pengundangan"),
                     ("effective_date", "Tanggal Berlaku")):
            d = id_date(meta.get(f))
            if d:
                rec[k] = d
        if "adopted_date" not in rec and re.fullmatch(r"(19|20)\d\d", meta.get("Tahun", "")):
            rec["adopted_date"] = meta["Tahun"]
        if status:
            rec["in_force"] = True if status.startswith("berlaku") else (False if ("tidak" in status or "cabut" in status) else None)
        extra = dict(bentuk=meta.get("Bentuk"), teu=teu or None, sumber=meta.get("Sumber"), subjek=meta.get("Subjek"),
                     status=meta.get("Status"), place_match=how, incomplete_reason=reason, ocr_queued=queued or None,
                     pdf_download_ids=seen or None, pdf_archive=[p.provenance() for p in pdocs] or None)
        rec.update(archived_rec(doc, POLICY, BASIS, **extra))
        rec["content_complete"] = bool(complete)
        rec["extra_metadata"]["archive"]["content_complete"] = bool(complete)
        return rec, "ok"

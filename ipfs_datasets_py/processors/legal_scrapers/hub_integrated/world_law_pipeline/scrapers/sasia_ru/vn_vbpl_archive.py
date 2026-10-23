"""VN provincial legal documents from the legacy vbpl.vn/<province>/Pages/vbpq-toanvan.aspx pages,
fetched from the Wayback Machine (live vbpl.vn is now a Next.js app; /Pages/ and /api/ are robots-disallowed
and the box gets WAF 403s). Keeps only docs issued by the provincial HĐND/UBND (local law).
Usage: python vn_vbpl_archive.py [--per-place 3] [--stage] [--only slug,..] [--stats PATH]

2026-10-18 (throttle deferral): the shared ArchiveFetcher raises archive.ArchiveDeferred on 429/5xx or while
web.archive.org is cooling down. Such items are NOT dropped any more: they are listed in the stats entry
({"status": "deferred", "deferred": [...], "not_before": epoch}) and the province is NOT staged, so a province is never
staged truncated. vn_driver.py persists that queue (_ru/vn_deferred.jsonl) and re-runs the province after not_before;
the re-run is cheap because CDX listings and fetched bodies are in the archive disk cache.
Status per province: complete (staged if docs) | deferred | breaker | transient (all three: not staged, retry later) |
cdx_error (other CDX error; driver retries later and parks after repeated failures, never 'done').
12:10 API follow-up: a listing flagged .truncated/.deferred (CaptureList) defers the province; timeouts (now at most
1 retry -> ArchiveTransient, still breaker failures) defer the item/province as transient/breaker, never a miss."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, re, json, html as H, argparse, time, os
from datetime import datetime, timezone
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ArchiveFetcher, StagedWriter, provenance_fields, ArchiveDeferred, ArchiveTransient, ArchiveError, good_doc
from archive import ratelimit
from schema import validate_record

# slug, place_id, place_name, admin_level
PLACES = [
 ('angiang', 'iso:VN-44', 'An Giang', 'adm1'),
 ('bariavungtau', 'iso:VN-43', 'Bà Rịa - Vũng Tàu', 'adm1'),
 ('bacgiang', 'iso:VN-54', 'Bắc Giang', 'adm1'),
 ('backan', 'iso:VN-53', 'Bắc Kạn', 'adm1'),
 ('baclieu', 'iso:VN-55', 'Bạc Liêu', 'adm1'),
 ('bacninh', 'iso:VN-56', 'Bắc Ninh', 'adm1'),
 ('bentre', 'iso:VN-50', 'Bến Tre', 'adm1'),
 ('binhdinh', 'iso:VN-31', 'Bình Định', 'adm1'),
 ('binhduong', 'iso:VN-57', 'Bình Dương', 'adm1'),
 ('binhphuoc', 'iso:VN-58', 'Bình Phước', 'adm1'),
 ('binhthuan', 'iso:VN-40', 'Bình Thuận', 'adm1'),
 ('camau', 'iso:VN-59', 'Cà Mau', 'adm1'),
 ('cantho', 'wd:Q216075', 'Cần Thơ', 'municipality'),
 ('caobang', 'iso:VN-04', 'Cao Bằng', 'adm1'),
 ('danang', 'wd:Q25282', 'Da Nang', 'municipality'),
 ('daklak', 'iso:VN-33', 'Đắk Lắk', 'adm1'),
 ('daknong', 'iso:VN-72', 'Đắk Nông', 'adm1'),
 ('dienbien', 'iso:VN-71', 'Điện Biên', 'adm1'),
 ('dongnai', 'wd:Q33271', 'Đồng Nai', 'municipality'),
 ('dongthap', 'iso:VN-45', 'Đồng Tháp', 'adm1'),
 ('gialai', 'iso:VN-30', 'Gia Lai', 'adm1'),
 ('hagiang', 'iso:VN-03', 'Hà Giang', 'adm1'),
 ('hanam', 'iso:VN-63', 'Hà Nam', 'adm1'),
 ('hanoi', 'wd:Q1858', 'Hanoi', 'municipality'),
 ('hatinh', 'iso:VN-23', 'Hà Tĩnh', 'adm1'),
 ('haiduong', 'iso:VN-61', 'Hải Dương', 'adm1'),
 ('haiphong', 'wd:Q72818', 'Haiphong', 'municipality'),
 ('haugiang', 'iso:VN-73', 'Hậu Giang', 'adm1'),
 ('hochiminh', 'wd:Q1854', 'Ho Chi Minh City', 'municipality'),
 ('hoabinh', 'iso:VN-14', 'Hòa Bình', 'adm1'),
 ('hungyen', 'iso:VN-66', 'Hưng Yên', 'adm1'),
 ('khanhhoa', 'iso:VN-34', 'Khánh Hòa', 'adm1'),
 ('kiengiang', 'iso:VN-47', 'Kiên Giang', 'adm1'),
 ('kontum', 'iso:VN-28', 'Kon Tum', 'adm1'),
 ('laichau', 'iso:VN-01', 'Lai Châu', 'adm1'),
 ('lamdong', 'iso:VN-35', 'Lâm Đồng', 'adm1'),
 ('langson', 'iso:VN-09', 'Lạng Sơn', 'adm1'),
 ('laocai', 'iso:VN-02', 'Lào Cai', 'adm1'),
 ('longan', 'iso:VN-41', 'Long An', 'adm1'),
 ('namdinh', 'iso:VN-67', 'Nam Định', 'adm1'),
 ('nghean', 'iso:VN-22', 'Nghệ An', 'adm1'),
 ('ninhbinh', 'iso:VN-18', 'Ninh Bình', 'adm1'),
 ('ninhthuan', 'iso:VN-36', 'Ninh Thuận', 'adm1'),
 ('phutho', 'iso:VN-68', 'Phú Thọ', 'adm1'),
 ('phuyen', 'iso:VN-32', 'Phú Yên', 'adm1'),
 ('quangbinh', 'iso:VN-24', 'Quảng Bình', 'adm1'),
 ('quangnam', 'iso:VN-27', 'Quảng Nam', 'adm1'),
 ('quangngai', 'iso:VN-29', 'Quảng Ngãi', 'adm1'),
 ('quangninh', 'wd:Q33396', 'Quảng Ninh', 'municipality'),
 ('quangtri', 'iso:VN-25', 'Quảng Trị', 'adm1'),
 ('soctrang', 'iso:VN-52', 'Sóc Trăng', 'adm1'),
 ('sonla', 'iso:VN-05', 'Sơn La', 'adm1'),
 ('tayninh', 'iso:VN-37', 'Tây Ninh', 'adm1'),
 ('thaibinh', 'iso:VN-20', 'Thái Bình', 'adm1'),
 ('thainguyen', 'iso:VN-69', 'Thái Nguyên', 'adm1'),
 ('thanhhoa', 'iso:VN-21', 'Thanh Hóa', 'adm1'),
 ('thuathienhue', 'wd:Q36399', 'Huế', 'municipality'),
 ('tiengiang', 'iso:VN-46', 'Tiền Giang', 'adm1'),
 ('travinh', 'iso:VN-51', 'Trà Vinh', 'adm1'),
 ('tuyenquang', 'iso:VN-07', 'Tuyên Quang', 'adm1'),
 ('vinhlong', 'iso:VN-49', 'Vĩnh Long', 'adm1'),
 ('vinhphuc', 'iso:VN-70', 'Vĩnh Phúc', 'adm1'),
 ('yenbai', 'iso:VN-06', 'Yên Bái', 'adm1'),
]
INFORCE = {"Còn hiệu lực": True, "Hết hiệu lực toàn bộ": False, "Hết hiệu lực một phần": True, "Ngưng hiệu lực": False, "Chưa có hiệu lực": False}
LOCAL = re.compile(r"(ỦY|UỶ) BAN NHÂN DÂN|HỘI ĐỒNG NHÂN DÂN", re.I)
TYPES = re.compile(r"^\s*(QUYẾT ĐỊNH|NGHỊ QUYẾT|CHỈ THỊ|QUY ĐỊNH)\s*$", re.M)

def to_text(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    t = H.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())

def parse(body):
    h = body.decode("utf-8", "replace")
    i = h.find('id="toanvancontent"')
    if i < 0: return None
    j = h.rfind('class="fulltext"', 0, i)
    info = {}
    if j >= 0:
        vb = h[j:i]
        st = re.search(r"Hiệu lực:\s*</span>\s*([^<]+)<", vb)
        ef = re.search(r"Ngày có hiệu lực:\s*</span>\s*(\d{1,2})/(\d{1,2})/(\d{4})", vb)
        if st: info["status"] = st.group(1).strip()
        if ef: info["effective_date"] = f"{ef.group(3)}-{int(ef.group(2)):02d}-{int(ef.group(1)):02d}"
        hd = to_text(vb)
        nm = re.search(r"Số\s*:?\s*([0-9]+\s*/\s*[0-9]{2,4}\s*/\s*[A-ZĐa-z0-9\-–]+)", hd)
        if nm: info["number"] = re.sub(r"\s+", "", nm.group(1))
        dm = re.search(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", hd)
        if dm: info["adopted_date"] = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
        info["header"] = hd[:600]
    seg = h[h.rfind("<div", 0, i):]
    seg = seg[:seg.find('class="vbProperties"')] if 'class="vbProperties"' in seg else seg[:400000]
    text = to_text(seg)
    if len(text) < 300: return None
    return seg, text, info

def _defer_entry(slug, item, url, e, not_before, reason):
    return {"slug": slug, "item": item, "url": url, "not_before": round(float(not_before), 1),
            "reason": reason, "error": str(e)[:200]}


def _transient_reason(e):
    s = str(e)
    if "breaker" in s or not ratelimit.wayback_available():
        return "breaker"
    return "transient"


TRANSIENT_RETRY_S = 300


def make_rec(slug, pid, name, lvl, item, c, doc, seg, text, info, now):
    head = info.get("header", "") + "\n" + text[:800]
    if not LOCAL.search(head): return None
    mt = TYPES.search(text[:1500]); dtype_vn = mt.group(1) if mt else None
    pre = text[:mt.start()] if mt else head
    num = re.search(r"Số\s*:?\s*([0-9]+\s*/\s*[0-9]{2,4}\s*/\s*[A-ZĐa-z0-9\-–]+)", pre)
    dm = re.search(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", pre)
    title = None
    if mt:
        after = text[mt.end():mt.end()+400].strip().splitlines()
        title = (dtype_vn + " " + (after[0] if after else "")).strip()
    title = title or (num.group(1) if num else f"vbpl {slug} {item}")
    rec = {"place_id": pid, "country_code": "VN", "doc_id": f"vbpl:{slug}:{item}",
           "source_platform": "vn_vbpl", "source_url": c.original_url.replace(":80/", "/"),
           "doc_type": "decision" if dtype_vn in ("QUYẾT ĐỊNH","CHỈ THỊ") else "regulation",
           "language": "vi", "title_native": title[:500], "number": re.sub(r"\s+","",num.group(1)) if num else None,
           "adopted_date": f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}" if dm else None,
           "in_force": INFORCE.get(info.get("status")), "effective_date": info.get("effective_date"), "status_native": info.get("status"), "consolidated": False, "content_format": "html",
           "html": f'<div class="chunk-content">{seg}</div>', "text": text, "retrieved_at": now,
           "source_official": True, "source_org": "Bộ Tư pháp — CSDL quốc gia về VBPL (vbpl.vn)",
           "place_name": name, "admin_level": lvl, "platform": "vn_vbpl", "platform_place_id": slug,
           **provenance_fields(doc, source_policy="archived_robots_disallowed",
                               robots_basis="vbpl.vn robots.txt Disallow: /Pages/")}
    if info.get("number"): rec["number"] = info["number"]
    if info.get("adopted_date"): rec["adopted_date"] = info["adopted_date"]
    if pid.startswith("wd:"): rec["qid"] = pid[3:]
    else: rec["iso_3166_2"] = pid[4:]
    rec["possibly_stale"] = True
    return rec


def process_place(fx, slug, pid, name, lvl, per_place, now):
    """-> (recs, stat). stat['status'] == 'complete' only if no item (and not the CDX listing) was deferred;
    callers must not stage or mark done otherwise."""
    recs = []; seen = 0; deferred = []
    cdx_url = f"vbpl.vn/{slug}/Pages/vbpq-toanvan.aspx"
    try:
        caps = fx.wb_captures(cdx_url, "prefix", collapse="urlkey", limit=max(60, per_place * 4),
                              filters=["mimetype:text/html", "original:.*[Ii]tem[Ii][Dd]=.*"])
    except ArchiveDeferred as e:
        d = _defer_entry(slug, "__cdx__", cdx_url, e, e.not_before, "deferred")
        return [], {"status": "deferred", "docs": 0, "deferred": [d], "not_before": d["not_before"]}
    except ArchiveTransient as e:
        r = _transient_reason(e)
        d = _defer_entry(slug, "__cdx__", cdx_url, e, time.time() + (0 if r == "breaker" else TRANSIENT_RETRY_S), r)
        return [], {"status": r, "docs": 0, "deferred": [d], "not_before": d["not_before"], "error": str(e)[:200]}
    except Exception as e:
        return [], {"status": "cdx_error", "docs": 0, "deferred": [], "error": str(e)[:200]}
    # 12:10 API: listings may come back as a CaptureList flagged .truncated/.deferred (wb_captures still raises,
    # but never trust an incomplete listing): defer the whole province, never 'complete'/'empty'.
    if getattr(caps, "truncated", False) or getattr(caps, "deferred", False):
        dd = getattr(caps, "deferral", None)
        nb = float(getattr(dd, "not_before", 0) or 0) or time.time() + TRANSIENT_RETRY_S
        d = _defer_entry(slug, "__cdx__", cdx_url, dd or "listing truncated", nb, "deferred")
        return [], {"status": "deferred", "docs": 0, "deferred": [d], "not_before": d["not_before"], "listing_truncated": True}
    byid = {}
    for c in caps:
        m = re.search(r"ItemID=(\d+)", c.original_url, re.I)
        if m: byid.setdefault(m.group(1), c)
    for item, c in list(byid.items())[::-1]:
        if len(recs) >= per_place or seen >= per_place * 4: break
        try:
            doc = fx.fetch_capture(c)            # == fetch_best([c], max_tries=1) but lets ArchiveDeferred through
            if not good_doc(doc): doc = None
        except ArchiveDeferred as e:             # requeue, keep going (no sleep, no retry of this item now)
            deferred.append(_defer_entry(slug, item, c.original_url, e, e.not_before, "deferred")); continue
        except ArchiveTransient as e:            # breaker open / gave up on network errors: retry later, not a miss
            r = _transient_reason(e)
            deferred.append(_defer_entry(slug, item, c.original_url, e, time.time() + (0 if r == "breaker" else TRANSIENT_RETRY_S), r)); continue
        except ArchiveError:
            doc = None                           # permanent (404 replay, bad record, cached failure)
        except Exception:
            doc = None
        seen += 1
        if not doc: continue
        p = parse(doc.body)
        if not p: continue
        seg, text, info = p
        rec = make_rec(slug, pid, name, lvl, item, c, doc, seg, text, info, now)
        if rec is None: continue
        errs = validate_record(rec)
        if errs: print("INVALID", slug, item, errs); continue
        recs.append(rec)
    if deferred:
        kinds = {d["reason"] for d in deferred}
        st = "breaker" if kinds == {"breaker"} else ("deferred" if "deferred" in kinds else sorted(kinds)[0])
        return recs, {"status": st, "docs": len(recs), "deferred": deferred,
                      "not_before": max(d["not_before"] for d in deferred), "captures": len(byid)}
    return recs, {"status": "complete", "docs": len(recs), "deferred": [], "captures": len(byid)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--per-place", type=int, default=3)
    ap.add_argument("--stage", action="store_true"); ap.add_argument("--only", default=""); ap.add_argument("--out", default=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_test"))
    ap.add_argument("--stats", default="/tmp/vn_vbpl_stats.json")
    a = ap.parse_args()
    fx = ArchiveFetcher(use_cc=False, lane=os.environ.get("ARCHIVE_LANE") or "sasia_ru")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = {}; allrecs = {}

    def dump():
        tmp = a.stats + f".{os.getpid()}.tmp"
        json.dump(stats, open(tmp, "w")); os.replace(tmp, a.stats)
    for slug, pid, name, lvl in PLACES:
        if a.only and slug not in a.only.split(","): continue
        recs, st = process_place(fx, slug, pid, name, lvl, a.per_place, now)
        if st["status"] == "complete":
            allrecs[(slug, pid)] = recs
            if a.stage and recs:
                w = StagedWriter((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru"), "VN", pid, batch_prefix="archive-vbpl")
                for r in recs:
                    e = w.add(r)
                    if e: print("REJECT", e)
                w.flush(); print("staged", w.written, flush=True)
                st["staged"] = [str(x) for x in (w.written or [])]
        else:
            print("NOT STAGED", slug, st["status"], len(st["deferred"]), "deferred item(s); not_before",
                  time.strftime("%H:%M:%S", time.localtime(st.get("not_before", 0))), flush=True)
        stats[slug] = st
        dump()
        print(slug, pid, len(recs), "docs", st["status"], flush=True)
    dump()
    import pathlib
    if allrecs:
        out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
        with open(out / "vn_vbpl_test.jsonl", "w", encoding="utf-8") as f:
            for v in allrecs.values():
                for r in v: f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

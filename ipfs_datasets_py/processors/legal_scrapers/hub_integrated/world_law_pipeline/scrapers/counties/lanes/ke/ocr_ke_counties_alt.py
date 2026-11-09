#!/usr/bin/env python3
"""Batch 4 (Kenya) repair: OCR/text for county-assembly PDFs of empty-38 laws of live laws-00001 from the PDFs cached by fetch_ke_empty38.py.
Offline (no network).

Per PDF: pdffonts + pdftotext -layout first. A text layer is used as-is when it is usable (>= 200 non-space chars per
page on average over pages with text, and English function-word share >= 0.25); then no OCR. Otherwise every page is
rendered with pdftoppm (300 dpi, gray) and OCR'd with tesseract 5 (eng, --psm 3, OMP_THREAD_LIMIT=1), at most 2 page
workers. Word confidences come from tesseract's TSV output (level-5 words, conf >= 0).
Fleet gates: start only when MemAvailable >= 5.5 GiB and disk >= 12,600 MiB held 120 s; hard stop (checkpointed,
resumable) when MemAvailable < 3 GiB held 15 s, disk < 12,500 MiB, or RSS (self + children) > 1 GiB.

Input : $MUNI_STAGE/empty38.json, $MUNI_STAGE/empty38/pdf/<id>.pdf
Output: $MUNI_STAGE/empty38/text/<id>.json (one checkpoint per law: text, backend, pages, confidences).
rc 0 ok | 3 hard stop | 5 start gate not met."""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke/b3"))
PDF, TXT = STAGE / "counties" / "pdf", STAGE / "counties" / "text"
TMP = Path(os.environ.get("KE_OCR_TMP", str(STAGE / "counties" / "tmp")))
WORKERS = 1  # fleet: 1 OCR worker
DPI = 300
STOP = {"reason": None}
STATUS = Path("/dev/shm/muni_africa/status_ke_b3_counties.txt")
def slog(m):
    import time
    line = time.strftime("%Y-%m-%dT%H:%M:%S%z") + " " + m
    print(line, flush=True)
    open(STATUS, "a").write(line + "\n")

PEAK = {"rss": 0.0}
FUNC = frozenset("the of and to in a by be shall or any for is on as at with from this that such which under these all are "
                 "act county section an it may not other its has have been person".split())


def mem_gib():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2**20
    return 0.0


def disk_mib():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 2**20


def rss_tree_mib():
    kids, rss = {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            st = open(f"/proc/{d}/stat").read()
            kids.setdefault(int(st.rsplit(")", 1)[1].split()[1]), []).append(int(d))
            for line in open(f"/proc/{d}/status"):
                if line.startswith("VmRSS:"):
                    rss[int(d)] = int(line.split()[1]) / 1024
                    break
        except (OSError, ValueError, IndexError):
            continue
    tot, todo = 0.0, [os.getpid()]
    while todo:
        p = todo.pop()
        tot += rss.get(p, 0.0)
        todo.extend(kids.get(p, []))
    return tot


def watchdog():
    low = None
    while STOP["reason"] is None:
        m = mem_gib()
        low = (low or time.time()) if m < 3.0 else None
        r = rss_tree_mib()
        PEAK["rss"] = max(PEAK["rss"], r)
        if low and time.time() - low >= 15:
            STOP["reason"] = f"MemAvailable {m:.2f} GiB < 3 GiB held >= 15 s"
        elif disk_mib() < 12500:
            STOP["reason"] = "disk < 12500 MiB"
        elif r > 1024:
            STOP["reason"] = f"RSS {r:.0f} MiB > 1024 MiB"
        time.sleep(1)


def slog(m):
    line = time.strftime("%Y-%m-%dT%H:%M:%S%z") + " " + m
    print(line, flush=True)
    open(Path("/dev/shm/muni_africa/status_ke_b3_counties.txt"), "a").write(line + "\n")

def start_gate(hold=120, max_wait=2700):
    deadline = time.time() + max_wait
    ok_since = None
    while time.time() < deadline:
        if STOP["reason"]:
            slog(f"ocr start gate aborted: {STOP['reason']}")
            return False
        m, d = mem_gib(), disk_mib()
        if m >= 5.5 and d >= 12600:
            ok_since = ok_since or time.time()
            held = time.time() - ok_since
            if held >= hold:
                slog(f"ocr start gate passed: MemAvailable {m:.2f} GiB held {held:.0f}s")
                return True
            if int(held) % 30 < 6:
                slog(f"ocr start gate holding: {m:.2f} GiB held {held:.0f}/{hold}s")
        else:
            if ok_since is not None:
                slog(f"ocr start gate reset: {m:.2f} GiB")
            ok_since = None
            # log at most every 60s
            if int(time.time()) % 60 < 6:
                slog(f"ocr start gate waiting: MemAvailable {m:.2f} GiB")
        time.sleep(5)
    slog(f"ocr start gate not met within {max_wait}s")
    return False


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def npages(pdf):
    m = re.search(rb"Pages:\s+(\d+)", run(["pdfinfo", str(pdf)]).stdout)
    return int(m.group(1)) if m else 0


def func_share(t):
    w = re.findall(r"[A-Za-z]+", t.lower())
    return sum(x in FUNC for x in w) / len(w) if w else 0.0


def clean(t):
    t = re.sub(r"[ \t]+\n", "\n", t.replace("\f", "\n"))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def text_layer(pdf, n):
    fonts = [l for l in run(["pdffonts", str(pdf)]).stdout.decode("utf-8", "replace").splitlines()[2:] if l.strip()]
    pages = []
    for p in range(1, n + 1):
        pages.append(run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(p), "-l", str(p), str(pdf), "-"]).stdout.decode("utf-8", "replace"))
    chars = [len(re.sub(r"\s", "", t)) for t in pages]
    with_text = [c for c in chars if c >= 50]
    joined = "\n".join(pages)
    usable = bool(with_text) and len(with_text) >= 0.8 * n and sum(with_text) / len(with_text) >= 200 and func_share(joined) >= 0.25
    return {"fonts": len(fonts), "chars": sum(chars), "pages_with_text": len(with_text), "usable": usable, "pages": pages}


def ocr_page(pdf, p, wd):
    if STOP["reason"]:
        raise RuntimeError(STOP["reason"])
    base = wd / f"p{p:04d}"
    run(["pdftoppm", "-r", str(DPI), "-gray", "-png", "-f", str(p), "-l", str(p), "-singlefile", str(pdf), str(base)])
    img = base.with_suffix(".png")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    subprocess.run(["tesseract", str(img), str(base), "-l", "eng", "--psm", "3", "txt", "tsv"], capture_output=True, env=env, timeout=900)
    txt = base.with_suffix(".txt").read_text("utf-8", "replace") if base.with_suffix(".txt").exists() else ""
    confs = []
    if base.with_suffix(".tsv").exists():
        for line in base.with_suffix(".tsv").read_text("utf-8", "replace").splitlines()[1:]:
            f = line.split("\t")
            if len(f) >= 12 and f[0] == "5" and f[11].strip():
                try:
                    c = float(f[10])
                except ValueError:
                    continue
                if c >= 0:
                    confs.append(c)
    for s in (".png", ".txt", ".tsv"):
        base.with_suffix(s).unlink(missing_ok=True)
    return p, txt, confs


def do_law(it):
    pdf = PDF / f"{it['id']}.pdf"
    out = TXT / f"{it['id']}.json"
    if out.exists():
        return "cached"
    if not pdf.exists():
        out.write_text(json.dumps({"id": it["id"], "error": "pdf_missing"}))
        return "pdf_missing"
    n = npages(pdf)
    tl = text_layer(pdf, n)
    rec = {"id": it["id"], "pages": n, "pdffonts_fonts": tl["fonts"], "text_layer_chars": tl["chars"],
           "text_layer_pages_with_text": tl["pages_with_text"]}
    if tl["usable"]:
        rec.update(backend="pdftotext", text=clean("\n".join(tl["pages"])))
    else:
        wd = Path(tempfile.mkdtemp(prefix=it["id"][-20:] + "_", dir=TMP))
        t0 = time.time()
        try:
            with ThreadPoolExecutor(WORKERS) as ex:
                res = sorted(ex.map(lambda p: ocr_page(pdf, p, wd), range(1, n + 1)))
        finally:
            shutil.rmtree(wd, ignore_errors=True)
        allc = [c for _p, _t, cs in res for c in cs]
        rec.update(backend="tesseract_ocr", text=clean("\n".join(t for _p, t, _c in res)), ocr_seconds=round(time.time() - t0, 1),
                   ocr_mean_conf=round(sum(allc) / len(allc), 1) if allc else None, ocr_words=len(allc),
                   ocr_hi_conf_share=round(sum(c >= 80 for c in allc) / len(allc), 3) if allc else None,
                   ocr_page_mean_conf=[round(sum(cs) / len(cs), 1) if cs else None for _p, _t, cs in res])
    rec["func_word_share"] = round(func_share(rec["text"]), 3)
    rec["nonspace_chars"] = len(re.sub(r"\s", "", rec["text"]))
    mm = json.load(open(STAGE / "counties" / "match_map.json")) if (STAGE / "counties" / "match_map.json").exists() else {}
    if it["id"] in mm:
        rec["alt_source"] = mm[it["id"]].get("url")
        rec["alt_source_host"] = "nairobiassembly.go.ke"
        rec["match_score"] = mm[it["id"]].get("score")
        rec["match_title"] = mm[it["id"]].get("title_link")
    rec["ok"] = rec.get("nonspace_chars", 0) >= 200
    rec["mean_conf"] = rec.get("ocr_mean_conf")
    rec["text_backend"] = rec.get("backend")
    out.write_text(json.dumps(rec, ensure_ascii=False))
    return f"{rec['backend']} pages={n} chars={rec['nonspace_chars']} conf={rec.get('ocr_mean_conf')} t={rec.get('ocr_seconds')}"


def main():
    TXT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    items = json.load(open(STAGE / "empty38.json"))
    only = os.environ.get("KE_ONLY")
    if only:
        items = [i for i in items if i["id"] in only.split(",")]
    items = [i for i in items if (PDF / f"{i['id']}.pdf").exists()]
    items.sort(key=lambda i: (PDF / f"{i['id']}.pdf").stat().st_size)
    slog(f"ocr: {len(items)} PDFs to process, workers=1")
    # stagger
    last = Path("/dev/shm/muni_last_start")
    if last.exists():
        age = time.time() - last.stat().st_mtime
        if age < 300:
            slog(f"ocr stagger wait {300-age:.0f}s")
            time.sleep(300 - age + 1)
    if not os.environ.get("KE_SKIP_GATE") and not start_gate():
        return 5
    Path("/dev/shm/muni_last_start").touch()
    threading.Thread(target=watchdog, daemon=True).start()
    for k, it in enumerate(items, 1):
        if STOP["reason"]:
            break
        try:
            r = do_law(it)
        except Exception as e:
            r = f"ERROR {type(e).__name__}: {str(e)[:150]}"
        slog(f"ocr {k}/{len(items)} {it['id']} {r} peak_rss={PEAK['rss']:.0f}MiB")
    if STOP["reason"]:
        slog(f"ocr HARD STOP: {STOP['reason']}")
        return 3
    slog("ocr done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""ZA batch 5 (A), OFFLINE step 1: per-page text for every fetched Free State gazette PDF (no network, no slot).
OCR decision = the fleet 100-body-chars-per-page rule: a page's pdftotext layer is kept if it has >= 100 body chars
after removing reproduction stamps / gazette page headers / page numbers / rule lines; otherwise the page is OCR'd
(pdftoppm 250 dpi gray -> tesseract eng --psm 3, OMP_THREAD_LIMIT=1, 1 worker). Pages whose OCR also yields < 100 body
chars are recorded as blank. Output: $FS_STAGE/pages/<pdf sha256[:16]>.json (resumable, atomic), one per gazette.
Memory rules as in the fetch step (pause = sleep until MemAvailable >= 4.5 GiB; < 3 GiB / disk < 12,500 MiB = exit 3)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import json, os, re, subprocess, sys, time
from pathlib import Path
STAGE = Path(os.environ.get("FS_STAGE", "/dev/shm/muni_africa/fs"))
RAW = Path(os.environ.get("FS_RAW", (str(_LEGAL_WS) + "/muni/fs_raw")))
DPI = 250
STAMP_LINES = re.compile(r"(?im)^.*(?:Reproduced by Sabinet|Copyright Authority No|GICS\.co\.za|PROVINCIAL GAZETTE|PROVINSIALE KOERANT|"
                         r"^\s*(?:LOCAL AUTHORITY|PROVINCIAL) NOTICE \d+\s*$|^\s*\d{1,4}\s*$).*$")   # collector rule
RULE_LINES = re.compile(r"(?m)^[\s_\-–—=.…·*]*$")


def body_chars(t):
    return len(re.sub(r"\s", "", RULE_LINES.sub("", STAMP_LINES.sub("", t or ""))))


def mem_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) / 2**20
    return 99.0


def disk_mib():
    st = os.statvfs("/"); return st.f_bavail * st.f_frsize / 2**20


def gate():
    if mem_gib() < 3.0 or disk_mib() < 12500:
        print("HARD STOP (memory/disk)", flush=True); sys.exit(3)
    if mem_gib() < 4.0:
        t0 = time.time()
        while mem_gib() < 4.0 and time.time() - t0 < 60:
            time.sleep(5)
        if mem_gib() < 4.0:
            print(time.strftime("%H:%M:%S"), "PAUSE (MemAvailable < 4 GiB for 60 s)", flush=True)
            while mem_gib() < 4.5:
                if mem_gib() < 3.0:
                    sys.exit(3)
                time.sleep(15)


def mean_conf(tsv):
    tot = n = 0.0
    for line in open(tsv, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        c = line.split("\t")
        if len(c) >= 12 and c[11].strip():
            try:
                v = float(c[10])
            except ValueError:
                continue
            if v >= 0:
                tot += v; n += 1
    return (round(tot / n, 1) if n else None), int(n)


def ocr_page(pdf, k, tmpdir):
    tag = tmpdir / f"o{os.getpid()}_{k}"
    subprocess.run(["nice", "-n", "10", "pdftoppm", "-f", str(k), "-l", str(k), "-r", str(DPI), "-gray", "-png", "-singlefile", str(pdf), str(tag)],
                   capture_output=True, timeout=300)
    img, txt, conf, words = Path(f"{tag}.png"), "", None, 0
    if img.exists():
        subprocess.run(["nice", "-n", "10", "tesseract", str(img), str(tag), "-l", "eng", "--psm", "3", "txt", "tsv"], capture_output=True,
                       timeout=600, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        if Path(f"{tag}.txt").exists():
            txt = Path(f"{tag}.txt").read_text("utf-8", "replace")
        if Path(f"{tag}.tsv").exists():
            conf, words = mean_conf(f"{tag}.tsv")
    for s in (".png", ".txt", ".tsv"):
        try:
            os.unlink(f"{tag}{s}")
        except OSError:
            pass
    return txt, conf, words


def main():
    out = STAGE / "pages"; out.mkdir(parents=True, exist_ok=True); tmp = STAGE / "tmp_ocr"; tmp.mkdir(exist_ok=True)
    recs = [json.loads(l) for l in open(STAGE / "fetch.jsonl")]
    last = {}
    for d in recs:
        last[d["url"]] = d
    todo = [d for d in last.values() if d["status"] == "fetched"]
    n_ocr = n_pages = 0
    for i, d in enumerate(todo, 1):
        dest = out / f"{d['sha256'][:16]}.json"
        if dest.exists():
            j = json.loads(dest.read_text()); n_pages += len(j["pages"]); n_ocr += sum(p["source"] == "ocr" for p in j["pages"]); continue
        pdf = RAW / d["file"]
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"^Pages:\s+(\d+)", info, re.M)
        pages = []
        for k in range(1, (int(m.group(1)) if m else 0) + 1):
            gate()
            t = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(k), "-l", str(k), str(pdf), "-"], capture_output=True,
                               timeout=120).stdout.decode("utf-8", "replace")
            bc = body_chars(t)
            if bc >= 100:
                raw = subprocess.run(["pdftotext", "-enc", "UTF-8", "-f", str(k), "-l", str(k), str(pdf), "-"], capture_output=True,
                                     timeout=120).stdout.decode("utf-8", "replace")   # reading order (bilingual 2-column pages)
                pages.append({"page": k, "source": "text_layer", "body_chars": bc, "text": t, "text_raw": raw})
            else:
                o, conf, words = ocr_page(pdf, k, tmp)
                ob = body_chars(o)
                if ob >= 100:
                    pages.append({"page": k, "source": "ocr", "body_chars": ob, "text_layer_body_chars": bc, "conf": conf, "words": words, "text": o})
                else:   # blank / decorative page: keep whatever text there was, flag it
                    pages.append({"page": k, "source": "blank", "body_chars": max(bc, ob), "conf": conf, "text": t if bc >= ob else o})
        j = {"url": d["url"], "title": d["title"], "file": d["file"], "sha256": d["sha256"], "bytes": d["bytes"], "pages": pages}
        dest.with_suffix(".part").write_text(json.dumps(j, ensure_ascii=False)); os.replace(dest.with_suffix(".part"), dest)
        n_pages += len(pages); n_ocr += sum(p["source"] == "ocr" for p in pages)
        print(time.strftime("%H:%M:%S"), f"[{i}/{len(todo)}] {d['title'][:60]}: {len(pages)} pp, ocr {sum(p['source'] == 'ocr' for p in pages)}, "
              f"blank {sum(p['source'] == 'blank' for p in pages)}", flush=True)
    (STAGE / "EXTRACT_DONE.json").write_text(json.dumps({"gazettes": len(todo), "pages": n_pages, "pages_ocr": n_ocr}))
    print("EXTRACT DONE", n_pages, "pages,", n_ocr, "OCR'd", flush=True)


if __name__ == "__main__":
    main()

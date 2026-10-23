#!/usr/bin/env python3
"""Parallel page-level render+OCR driver for the AT OCR completion.

Same established chain (pdftoppm 300 dpi -> tesseract deu, restart-proof
tessroot binary + local tessdata), same outputs as
ocr_at_completion.py's ocr phase (ocr_work/text/*.txt +
ocr_work/ocr_stats.json with identical fields and quality gates) — but
pages are rendered and OCR'd with a small worker pool and checkpointed
PER PAGE (ocr_work/pagetext/<key>/pNN.txt), because the serial per-doc
run was starved for hours under multi-lane VM load and died in a VM
restart. Page texts are joined in page order, exactly as the serial
driver joined them.
"""
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ocr_at_completion as OC  # noqa: E402  (reuse gates/probe/TESS_CMD)

WORK = OC.WORK
PAGES = WORK / "pages"
PAGETEXT = WORK / "pagetext"
RENDER_WORKERS = 3
OCR_WORKERS = 3


def key_of(e):
    return f"{e['gkz']}_{e['hub_id'] or e['file_name']}"


def width_of(n):
    return max(2, len(str(n)))


def render_page(e, i):
    """Render page i (1-based) of doc e to PAGES/<key>/p-<padded>.png."""
    key = key_of(e)
    d = PAGES / key
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"p-{i:0{width_of(e['pages'])}d}.png"
    if out.exists() and out.stat().st_size > 0:
        return (key, i, "cached")
    pdf = OC.H.RAW / "pdf" / e["gkz"] / e["file_name"]
    tmp_prefix = d / f"tmp{i}"
    subprocess.run(["pdftoppm", "-r", "300", "-png", "-f", str(i), "-l", str(i),
                    str(pdf), str(tmp_prefix)], check=True, timeout=3600)
    produced = sorted(d.glob(f"tmp{i}*.png"))
    if not produced:
        raise RuntimeError(f"no render output for {key} page {i}")
    produced[0].replace(out)
    return (key, i, "rendered")


def ocr_page(e, i):
    key = key_of(e)
    pt_dir = PAGETEXT / key
    pt_dir.mkdir(parents=True, exist_ok=True)
    pt = pt_dir / f"p{i:0{width_of(e['pages'])}d}.txt"
    if pt.exists():
        return (key, i, "cached")
    png = PAGES / key / f"p-{i:0{width_of(e['pages'])}d}.png"
    o = subprocess.run(OC.TESS_CMD + [str(png), "stdout", "-l", "deu"],
                       capture_output=True, timeout=1200, env=OC.TESS_ENV)
    pt.write_text(o.stdout.decode("utf-8", errors="replace"), encoding="utf-8")
    return (key, i, "ocred")


def main():
    deferred = json.loads((WORK / "at_deferred.json").read_text(encoding="utf-8"))
    stats_path = WORK / "ocr_stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else []
    done_docs = {(s["gkz"], s["file_name"]) for s in stats}
    todo = [e for e in deferred if (e["gkz"], e["file_name"]) not in done_docs]
    print(f"{len(todo)} docs to OCR ({len(done_docs)} already in stats)", flush=True)

    jobs = [(e, i) for e in todo for i in range(1, e["pages"] + 1)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=RENDER_WORKERS) as ex:
        for n, res in enumerate(ex.map(lambda j: render_page(*j), jobs), 1):
            if n % 10 == 0 or res[2] == "rendered" and n == len(jobs):
                print(f"render {n}/{len(jobs)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"all renders done in {time.time()-t0:.0f}s", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as ex:
        for n, res in enumerate(ex.map(lambda j: ocr_page(*j), jobs), 1):
            if n % 10 == 0:
                print(f"ocr {n}/{len(jobs)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"all page OCR done in {time.time()-t0:.0f}s", flush=True)

    for e in todo:
        key = key_of(e)
        w = width_of(e["pages"])
        parts = [(PAGETEXT / key / f"p{i:0{w}d}.txt").read_text(encoding="utf-8")
                 for i in range(1, e["pages"] + 1)]
        text = "\n".join(parts)
        OC.TEXTS.mkdir(parents=True, exist_ok=True)
        (OC.TEXTS / f"{key}.txt").write_text(text, encoding="utf-8")
        chars = len(text.strip())
        nons = re.sub(r"\s+", "", text)
        alpha = sum(c.isalpha() for c in nons)
        st = dict(e)
        st.update({
            "ocr_chars": chars,
            "ocr_pages_rendered": e["pages"],
            "alpha_ratio": round(alpha / max(1, len(nons)), 3),
            "chars_per_page": round(chars / max(1, e["pages"]), 1),
            "name_hit": OC.probe_hit(text, OC.name_probe(e["name"])),
            "text_file": f"text/{key}.txt",
            "ocr_seconds": 0,
        })
        reasons = []
        if st["ocr_chars"] < 300:
            reasons.append(f"only {st['ocr_chars']} OCR chars (near-empty)")
        if st["alpha_ratio"] < 0.55:
            reasons.append(f"alpha ratio {st['alpha_ratio']} < 0.55 (garbled?)")
        if not st["name_hit"]:
            reasons.append("Gemeinde name not found in OCR text (attribution)")
        st["quality_pass"] = not reasons
        st["quality_reasons"] = reasons
        stats.append(st)
        stats_path.write_text(json.dumps(stats, indent=1, ensure_ascii=False),
                              encoding="utf-8")
        print(f"DONE {e['gkz']} {e['file_name']}: {chars} chars, alpha "
              f"{st['alpha_ratio']}, name={st['name_hit']}, "
              f"pass={st['quality_pass']} {reasons if reasons else ''}", flush=True)
    print(f"stats complete: {len(stats)}/19 docs")


if __name__ == "__main__":
    main()

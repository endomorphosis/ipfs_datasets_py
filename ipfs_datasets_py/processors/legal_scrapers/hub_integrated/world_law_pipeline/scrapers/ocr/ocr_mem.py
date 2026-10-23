"""Shared memory guards for OCR jobs (added 2026-10-14 after OOM kills)."""
import os, re, resource, subprocess, sys, time
from pathlib import Path
MIN_AVAIL_GB = float(os.environ.get("OCR_MIN_AVAIL_GB", "3"))
PDFTOPPM_AS_BYTES = 3 * 1024**3   # address-space cap for each pdftoppm child
TESS_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")

def mem_available_gb():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"): return int(ln.split()[1]) / 1024**2
    return 0.0

def mem_gate(log=None, min_gb=MIN_AVAIL_GB):
    """Block (sleep 30s, re-check) until MemAvailable >= min_gb. Call before starting each doc."""
    while True:
        m = mem_available_gb()
        if m >= min_gb: return m
        msg = f"MEMGATE wait: MemAvailable {m:.2f} GB < {min_gb} GB"
        (log or (lambda s: print(s, file=sys.stderr, flush=True)))(msg)
        time.sleep(30)

def _cap(): resource.setrlimit(resource.RLIMIT_AS, (PDFTOPPM_AS_BYTES, PDFTOPPM_AS_BYTES))

def pdf_pages(pdf):
    r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=120)
    m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
    return int(m.group(1)) if m else 0

def render_pages(pdf, dpi, max_pages, td):
    """Yield page PNG paths, rendering ONE page per pdftoppm call (memory-capped)."""
    n = pdf_pages(pdf)
    if n <= 0: n = max_pages  # fall back; pdftoppm stops at the last page
    for i in range(1, min(n, max_pages) + 1):
        pre = f"{td}/p{i:04d}"
        r = subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", "-singlefile", "-f", str(i), "-l", str(i), str(pdf), pre],
                           capture_output=True, timeout=900, preexec_fn=_cap)
        img = Path(pre + ".png")
        if r.returncode != 0 or not img.exists():
            if i == 1: raise subprocess.CalledProcessError(r.returncode, "pdftoppm", r.stdout, r.stderr)
            break
        yield img

#!/usr/bin/env python3
"""Batch 3 (Kenya): ONE paced re-fetch of the Samburu County Nomotio Livestock Improvement Center Act, 2022 (Samburu
County Acts No. 1 of 2022), dropped from batch 2 (section split failed). Reuses the batch-2 fetch stack unchanged
(collect_ke_samburu_muni.get: robots_guard on every hop incl. robots.txt, hard pacer max(5 s, Crawl-Delay) over all fleet
request logs for the host, TLS verify=True, one request in flight, hard stop on challenge / 403 / 429 / 503).
Verifies the sha256 recorded in batch 2. Writes $MUNI_STAGE/requests.jsonl and $MUNI_STAGE/nomotio/<sha-prefix>.pdf.
Never uploads. rc 0 ok | 2 sha mismatch | 3 hard stop."""
import hashlib, json, os, sys
from pathlib import Path

os.environ.setdefault("MUNI_STAGE", "/dev/shm/muni_africa/ke/b3")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_ke_samburu_muni as C  # noqa: E402

URL = ("https://www.samburuassembly.go.ke/download/119/acts/8353/"
       "the-samburu-county-nomotio-livestock-improvement-center-act-2022.pdf")
SHA = "727a477e2281257afa3d745b138db72ddc87eb18fd0b71d646908b48d6d11dee"


def main():
    out = C.STAGE / "nomotio" / f"{SHA[:12]}.pdf"
    if out.exists() and hashlib.sha256(out.read_bytes()).hexdigest() == SHA:
        print("cached, sha ok; no request"); return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    C.start_pacing()
    tmp = out.with_suffix(".part")
    try:
        st, _txt, final, n, ctype = C.get(URL, stream_to=tmp, cap=8 * 1024 * 1024)
    except C.HardStop as e:
        print("HARD STOP:", e); return 3
    sends = [dict(zip(("t", "host", "kind", "url", "gap", "actual"), s)) for s in C.PACER.sends]
    sha = hashlib.sha256(tmp.read_bytes()).hexdigest() if tmp.exists() else None
    res = {"url": URL, "status": st, "final": final, "bytes": n, "ctype": ctype, "sha256": sha, "sha_ok": sha == SHA,
           "sends": [{"at": C.iso_ms(s["t"]), "kind": s["kind"], "url": s["url"], "required_gap_s": s["gap"],
                      "actual_gap_s": None if s["actual"] is None else round(s["actual"], 3)} for s in sends],
           "counts": dict(C.COUNT), "at": C.now()}
    (C.STAGE / "nomotio" / "fetch_result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    if sha != SHA:
        return 2
    tmp.rename(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

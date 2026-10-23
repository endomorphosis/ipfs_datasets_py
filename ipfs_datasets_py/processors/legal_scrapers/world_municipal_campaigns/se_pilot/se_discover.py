"""Sweden pilot — collection discovery via curl (hard-capped).

Per kommun: fetch robots.txt (posture), then try known/candidate
författningssamling index URLs; for any 200 page mentioning
'författning', extract document links (PDFs and doc pages).
Checkpoints discovery_state.json after every kommun.
"""
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

OUT = Path(__file__).resolve().parent
STATE = OUT / "discovery_state.json"
UA = "world-municipal-law-pilot/1.0 (research; polite harvest)"

KNOWN_INDEX = {
    "0380": ["https://www.uppsala.se/kommun-och-politik/dokumentsamlingar/lokala-foreskrifter/"],
    "1880": ["https://orebro.se/kommun--politik/dokument-statistik--undersokningar/dokument--undersokningar/kommunal-forfattningssamling.html"],
}
SITES = {
    "0180": "https://start.stockholm",
    "1480": "https://goteborg.se",
    "1280": "https://malmo.se",
    "0380": "https://www.uppsala.se",
    "0580": "https://www.linkoping.se",
    "1880": "https://orebro.se",
    "2480": "https://www.umea.se",
    "2580": "https://www.lulea.se",
    "0680": "https://www.jonkoping.se",
    "1980": "https://www.vasteras.se",
    "0980": "https://gotland.se",
    "2180": "https://www.gavle.se",
}
CANDIDATE_PATHS = [
    "/forfattningssamling", "/forfattningssamlingen",
    "/kommun-och-politik/forfattningssamling",
    "/kommun--politik/forfattningssamling",
    "/kommun-och-politik/forfattningssamling/",
    "/politik-och-organisation/forfattningssamling",
    "/kommun-och-politik/styrdokument/forfattningssamling",
]


def curl(url, max_time=45, binary=False):
    cmd = ["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
           "-w", "\n%{http_code} %{url_effective}", url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=max_time + 15)
        out = p.stdout
        tail = out.rsplit(b"\n", 1)[-1].decode("utf-8", "replace")
        body = out[: len(out) - len(tail) - 1] if b"\n" in out else out
        m = re.match(r"(\d{3}) (\S+)", tail.strip())
        code = int(m.group(1)) if m else None
        eff = m.group(2) if m else url
        return {"status": code, "final_url": eff,
                "body": body if binary else body.decode("utf-8", "replace"),
                "bytes": len(body), "curl_rc": p.returncode,
                "stderr": p.stderr.decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "final_url": url, "body": "" if not binary else b"",
                "bytes": 0, "error": f"{type(e).__name__}: {e}"}


def robots_allows(robots_text, path):
    """Crude check: '*' group Disallow rules covering path."""
    if not robots_text:
        return True, "no robots text"
    groups = re.split(r"(?im)^\s*user-agent:", robots_text)
    for g in groups[1:]:
        agents = g.split("\n", 1)[0].strip().lower()
        if agents not in ("*",):
            continue
        for line in g.splitlines()[1:]:
            line = line.strip()
            if line.lower().startswith("disallow:"):
                rule = line.split(":", 1)[1].strip()
                if rule and path.startswith(rule):
                    return False, f"Disallow: {rule}"
    return True, "ok"


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {"kommuner": {}}
    for code, site in SITES.items():
        if code in state["kommuner"]:
            print(f"[{code}] done, skip", flush=True)
            continue
        print(f"[{code}] {site} ...", flush=True)
        e = {"site": site}
        rob = curl(urljoin(site, "/robots.txt"), 30)
        e["robots"] = {"status": rob["status"], "bytes": rob["bytes"]}
        robots_text = rob["body"] if rob["status"] == 200 else ""
        if robots_text:
            (OUT / "scratch" / f"robots_{code}.txt").write_text(robots_text, encoding="utf-8")
        tries = KNOWN_INDEX.get(code, []) + [site.rstrip("/") + p for p in CANDIDATE_PATHS]
        found = []
        for url in tries:
            path = urlparse(url).path
            ok, why = robots_allows(robots_text, path)
            if not ok:
                e.setdefault("robots_blocked", []).append({"url": url, "rule": why})
                continue
            r = curl(url, 45)
            rec = {"url": url, "status": r["status"], "final_url": r["final_url"],
                   "bytes": r["bytes"]}
            if r["status"] == 200 and ("rfattning" in r["body"] or "reskrift" in r["body"]):
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r["body"], "html.parser")
                docs = []
                for a in soup.find_all("a", href=True):
                    href = urljoin(r["final_url"], a["href"])
                    txt = " ".join(a.get_text().split())
                    if (href.lower().endswith((".pdf", ".docx", ".doc"))
                            or "/download/" in href or "/dokument/" in href.lower()):
                        docs.append({"url": href, "text": txt[:120]})
                rec["doc_links"] = docs
                rec["n_doc_links"] = len(docs)
                found.append(rec)
                (OUT / "scratch" / f"index_{code}.html").write_text(r["body"], encoding="utf-8")
            e.setdefault("tried", []).append(rec)
            time.sleep(1.5)
            if found and code in KNOWN_INDEX:
                break
        e["found_index"] = found
        state["kommuner"][code] = e
        STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
        print(f"[{code}] robots={e['robots']['status']} found={len(found)} "
              f"docs={sum(f.get('n_doc_links', 0) for f in found)}", flush=True)
        time.sleep(2)
    print("discovery done")


if __name__ == "__main__":
    main()

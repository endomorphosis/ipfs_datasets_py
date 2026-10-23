"""Mexico tranche 2 — discovery probe.

For each target municipio: robots.txt posture, homepage reachability,
one-level crawl of normatividad / reglamentos / transparencia / bando
links, harvesting candidate PDF URLs (bando|reglamento|codigo keywords).
Checkpointed to mx_tranche2/probe/discovery.json. Hard-capped curl only.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

OUT_DIR = Path(__file__).resolve().parent.parent
RESULTS = OUT_DIR / "probe" / "discovery.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"

CANDIDATES = [
    ("14098", "San Pedro Tlaquepaque", "Jalisco", "https://tlaquepaque.gob.mx"),
    ("14101", "Tonalá", "Jalisco", "https://tonala.gob.mx"),
    ("11017", "Irapuato", "Guanajuato", "https://www.irapuato.gob.mx"),
    ("11007", "Celaya", "Guanajuato", "https://www.celaya.gob.mx"),
    ("25012", "Mazatlán", "Sinaloa", "https://www.mazatlan.gob.mx"),
    ("25001", "Ahome", "Sinaloa", "https://www.ahome.gob.mx"),
    ("02001", "Ensenada", "Baja California", "https://www.ensenada.gob.mx"),
    ("22016", "San Juan del Río", "Querétaro", "https://www.sanjuandelrio.gob.mx"),
    ("30193", "Veracruz", "Veracruz", "https://veracruzmunicipio.gob.mx"),
    ("30087", "Xalapa", "Veracruz", "https://xalapa.gob.mx"),
    ("30039", "Coatzacoalcos", "Veracruz", "https://www.coatzacoalcos.gob.mx"),
    ("30131", "Poza Rica de Hidalgo", "Veracruz", "https://pozarica.gob.mx"),
    ("13048", "Pachuca de Soto", "Hidalgo", "https://www.pachuca.gob.mx"),
    ("28038", "Tampico", "Tamaulipas", "https://tampico.gob.mx"),
    ("28041", "Victoria", "Tamaulipas", "https://ciudadvictoria.gob.mx"),
    ("28022", "Matamoros", "Tamaulipas", "https://www.matamoros.gob.mx"),
    ("28027", "Nuevo Laredo", "Tamaulipas", "https://nld.gob.mx"),
    ("10007", "Gómez Palacio", "Durango", "https://gomezpalacio.gob.mx"),
    ("03003", "La Paz", "Baja California Sur", "https://lapaz.gob.mx"),
    ("03008", "Los Cabos", "Baja California Sur", "https://www.loscabos.gob.mx"),
    ("16102", "Uruapan", "Michoacán", "https://uruapan.gob.mx"),
    ("16108", "Zamora", "Michoacán", "https://www.zamora.gob.mx"),
    ("18017", "Tepic", "Nayarit", "https://www.tepic.gob.mx"),
    ("14067", "Puerto Vallarta", "Jalisco", "https://www.puertovallarta.gob.mx"),
]

PAGE_KW = ("normatividad", "reglamento", "bando", "transparencia",
           "marco-juridico", "marco_juridico", "marcojuridico", "juridico",
           "leyes", "ordenjuridico", "orden-juridico")
PDF_KW = ("bando", "reglamento", "codigo", "ordenanza")


def fetch(url, timeout=25):
    try:
        p = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA,
             "-w", "\n%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 10)
        body, _, code = p.stdout.rpartition("\n")
        return (int(code) if code.isdigit() else 0), body
    except Exception as e:  # noqa: BLE001
        return 0, f"ERR {e}"


HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
A_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def strip_tags(s):
    return re.sub(r"<[^>]+>", " ", s).strip()


def probe(code, name, state, base):
    entry = {"name": name, "state": state, "base": base}
    rc, robots = fetch(base + "/robots.txt")
    entry["robots_status"] = rc
    entry["robots_text"] = robots[:1500] if rc else ""
    hc, home = fetch(base + "/")
    entry["home_status"] = hc
    entry["home_bytes"] = len(home)
    pdfs = {}
    pages = []
    if hc == 200:
        links = []
        for href, txt in A_RE.findall(home):
            u = urljoin(base + "/", href)
            low = (u + " " + strip_tags(txt)).lower()
            if u.lower().endswith(".pdf"):
                if any(k in u.lower() for k in PDF_KW):
                    pdfs[u] = strip_tags(txt)[:120]
            elif any(k in low for k in PAGE_KW):
                links.append(u)
        # also try common direct paths
        for path in ("/normatividad", "/reglamentos", "/transparencia",
                     "/marco-juridico", "/normatividad-municipal"):
            links.append(urljoin(base + "/", path.lstrip("/")))
        seen = set()
        todo = []
        for u in links:
            if u not in seen:
                seen.add(u)
                todo.append(u)
        for u in todo[:8]:
            pc, page = fetch(u)
            pages.append({"url": u, "status": pc, "bytes": len(page)})
            if pc == 200:
                for href, txt in A_RE.findall(page):
                    pu = urljoin(u, href)
                    if pu.lower().endswith(".pdf") or ".pdf" in pu.lower():
                        if any(k in pu.lower() for k in PDF_KW):
                            pdfs[pu] = strip_tags(txt)[:120]
            time.sleep(1)
    entry["pages_probed"] = pages
    entry["candidate_pdfs"] = [{"url": u, "link_text": t} for u, t in sorted(pdfs.items())]
    return entry


def main():
    only = sys.argv[1:]
    results = {}
    if RESULTS.exists():
        results = json.loads(RESULTS.read_text())
    for code, name, state, base in CANDIDATES:
        if only and code not in only:
            continue
        if code in results and results[code].get("home_status"):
            continue
        entry = probe(code, name, state, base)
        results[code] = entry
        print(code, name, "home", entry["home_status"],
              "pdfs", len(entry["candidate_pdfs"]), flush=True)
        RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("DONE", len(results))


if __name__ == "__main__":
    main()

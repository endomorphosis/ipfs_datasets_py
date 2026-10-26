"""Redirect hops must be robots-checked BEFORE they are requested (same-host redirect into a Disallow path)."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_same_host_redirect_into_disallowed_path_not_requested(tmp_path):
    import http.server
    import threading
    crawler = _load("de_ortsrecht_crawler")
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            hits.append(self.path)
            if self.path == "/robots.txt":
                body = b"User-agent: *\nDisallow: /Portals/\n"
                self.send_response(200); self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            elif self.path == "/LinkClick.aspx":
                self.send_response(302); self.send_header("Location", "/Portals/3/doc.pdf")
                self.send_header("Content-Length", "0"); self.end_headers()
            elif self.path == "/go-ok":
                self.send_response(301); self.send_header("Location", "/ok.html")
                self.send_header("Content-Length", "0"); self.end_headers()
            else:
                body = b"<html><body>ok</body></html>"
                self.send_response(200); self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    try:
        crawler.MIN_DELAY = 0.0
        crawler.TMP_DIR = tmp_path
        f = crawler.Fetcher(crawler.FetchCache(tmp_path / "c.sqlite"), tmp_path / "_raw")
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        rec = f.get(base + "/LinkClick.aspx")
        assert rec["error"] == "robots_disallowed", rec
        assert "/Portals/3/doc.pdf" not in hits
        rec2 = f.get(base + "/go-ok")
        assert not rec2["error"] and rec2["final_url"].endswith("/ok.html") and b"ok" in rec2["body"]
    finally:
        srv.shutdown()


def test_fr_module_loads_and_upgrades_http():
    fr = _load("fr_actes_crawler")
    assert fr.canon("http://www.mairie-x.fr/actes?id=1") == "https://www.mairie-x.fr/actes?id=1"
    assert fr.score_seed({"url": "https://x.fr/recueil-des-actes-administratifs", "text": ""}) >= 50
    assert fr.schema_doc_type(fr.guess_doc_type("Délibération du conseil municipal")) == "decision"
    assert fr.place_key("wd:Q90") == "wd_Q90"

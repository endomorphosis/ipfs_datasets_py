# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from rfc9309 import Robots  # noqa: E402

_spec = importlib.util.spec_from_file_location("crawler", HERE / "de_ortsrecht_crawler.py")
crawler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crawler)


def test_robots_wildcards_and_precedence():
    r = Robots("User-agent: *\nDisallow: /*.pdf$\nDisallow: /fileadmin/\nAllow: /fileadmin/ok/\nCrawl-delay: 4\n")
    ua = crawler.UA_TOKEN
    assert not r.can_fetch(ua, "https://x.de/a/b.pdf")
    assert r.can_fetch(ua, "https://x.de/a/b.pdf?x=1")
    assert not r.can_fetch(ua, "https://x.de/fileadmin/a.html")
    assert r.can_fetch(ua, "https://x.de/fileadmin/ok/a.html")
    assert r.crawl_delay(ua) == 4


def test_robots_specific_group_wins():
    r = Robots("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /cgi-bin/\n")
    assert not r.can_fetch(crawler.UA_TOKEN, "https://x.de/ortsrecht")


def test_canon_keeps_query_bytes():
    u = "https://www.elze.de/media/custom/3016_930_1.PDF?1657026093"
    assert crawler.canon(u) == u
    assert crawler.canon("https://a.de/x?utm_source=1&id=3") == "https://a.de/x?id=3"


def test_schema_record_validates():
    sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
    import schema
    d = {"place_id": "wd:Q1", "qid": "Q1", "municipality_name": "X", "source_url": "https://x.de",
         "homepage": "https://x.de", "section_url": "https://x.de/ortsrecht", "doc_url": "https://x.de/a.pdf",
         "requested_url": "https://x.de/a.pdf", "title": "Hundesteuersatzung (PDF, 120 KB)",
         "doc_type_guess": "satzung", "content_type": "pdf", "fetched_at": crawler.now_iso(), "text": "§ 1 ...",
         "sha256": "0" * 64}
    rec = crawler.to_schema_record(d, 0)
    assert schema.validate_record(rec) == []
    assert rec["title_native"] == "Hundesteuersatzung"
    assert crawler.place_key("wd:Q1") == "wd_Q1"


def _minimal_pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def test_pdf_streamed_to_disk_text_extracted_and_temp_removed(tmp_path):
    import http.server
    import threading
    site = tmp_path / "site"
    site.mkdir()
    (site / "hundesteuersatzung.pdf").write_bytes(_minimal_pdf("Satzung ueber die Hundesteuer Paragraph 1"))

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        crawler.TMP_DIR = tmp_path / "_tmp"
        crawler.TMP_DIR.mkdir()
        crawler.MIN_DELAY = 0.0
        f = crawler.Fetcher(crawler.FetchCache(tmp_path / "c.sqlite"), tmp_path / "_raw")
        url = f"http://127.0.0.1:{srv.server_address[1]}/hundesteuersatzung.pdf"
        rec = f.get(url)
        assert not rec["error"], rec["error"]
        assert rec["path"].endswith(".pdftxt.gz")
        assert "Hundesteuer" in crawler.body_bytes(rec).decode()
        assert list(crawler.TMP_DIR.iterdir()) == []          # temp PDF deleted
        assert not list((tmp_path / "_raw").rglob("*.pdf"))    # PDF bytes never kept
        rec2 = f.get(url)                                      # served from disk cache
        assert rec2["cached"] and "Hundesteuer" in crawler.body_bytes(rec2).decode()
    finally:
        srv.shutdown()


def test_docsink_streams_and_aborts(tmp_path):
    sink = crawler.DocSink(tmp_path, "wd_Q1")
    base = {"place_id": "wd:Q1", "qid": "Q1", "municipality_name": "X", "source_url": "https://x.de",
            "homepage": "https://x.de", "section_url": "", "doc_type_guess": "satzung", "content_type": "pdf",
            "fetched_at": crawler.now_iso(), "sha256": "0" * 64}
    sink.add({**base, "doc_url": "https://x.de/a.pdf", "requested_url": "https://x.de/a.pdf", "title": "A", "text": "§ 1"})
    sink.add({**base, "doc_url": "https://x.de/a.pdf", "requested_url": "https://x.de/a.pdf", "title": "A", "text": "§ 1"})
    sink.add({**base, "doc_url": "https://x.de/b.pdf", "requested_url": "https://x.de/b.pdf", "title": "B", "text": ""})
    assert sink.rows == 1 and sink.found == 3 and len(sink.scanned) == 1 and sink.dropped["dup_doc_id"] == 1
    assert sink.tmp.exists() and sink.tmp.name.endswith(".tmp")
    sink.abort()
    assert not sink.tmp.exists()

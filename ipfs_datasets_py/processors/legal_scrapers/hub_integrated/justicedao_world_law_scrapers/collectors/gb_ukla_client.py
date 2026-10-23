"""Polite single-connection client for www.legislation.gov.uk (robots Crawl-delay 5 -> 5.5 s), shared by probe/collector."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import datetime as dt, os, time, urllib.error, urllib.request
UA = ('legal-corpora-gb-ukla/1.0 (research corpus of UK Local Acts, OGL v3; robots crawl-delay honoured; '
      '+https://huggingface.co/endomorphosis)')
DELAY = 5.5
LAST_FILE = '{_CORPORA}/gb_ukla/probe/.last_request'

class Stop(Exception):
    pass

class Client:
    def __init__(self, log=print, status_file='{_CORPORA}/gb_ukla/probe/status_lines.txt', delay=DELAY):
        self.log = log; self.status_file = status_file; self.delay = delay; self.cbad = 0; self.nreq = 0
    def _last(self):
        try: return float(open(LAST_FILE).read().strip())
        except Exception: return 0.0
    def get(self, url, accept=None, max_tries=4):
        if '/data.pdf' in url or '/data.docx' in url or url.split('legislation.gov.uk', 1)[-1].startswith('/defralex'):
            raise ValueError(f'robots-disallowed path refused: {url}')
        back = 30
        for attempt in range(max_tries):
            w = self._last() + self.delay - time.time()
            if w > 0: time.sleep(w)
            req = urllib.request.Request(url, headers={'User-Agent': UA, **({'Accept': accept} if accept else {})})
            st, body, hdr = None, b'', {}
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    st = r.status; body = r.read(); hdr = dict(r.headers); final = r.geturl()
            except urllib.error.HTTPError as e:
                st = e.code; hdr = dict(e.headers or {}); final = url
                try: body = e.read()
                except Exception: pass
            except Exception as e:
                st = -1; body = repr(e).encode(); final = url
            with open(LAST_FILE, 'w') as f: f.write(str(time.time()))
            self.nreq += 1
            if self.status_file:
                with open(self.status_file, 'a') as f:
                    f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} PT\t{url}\tHTTP {st}\tbytes={len(body)}\tctype={hdr.get('Content-Type','')}\tfinal={final}\n")
            if st in (403, 429, 503):
                self.cbad += 1
                if self.cbad >= 3: raise Stop(f'3 consecutive {st} (last {url})')
            elif st != -1:
                self.cbad = 0
            if st in (200, 404, 410): return st, hdr, body
            if st in (429, 500, 502, 503, 504, -1, 403):
                s = 300 if st in (503, 504) else back  # API docs: wait >=5 min on 503/504
                self.log(f'HTTP {st} {url} -> backoff {s}s'); time.sleep(s); back = min(back * 2, 600); continue
            return st, hdr, body
        return st, hdr, body

"""Pre-fetch skip for URLs already covered by the older endomorphosis/justicedao repos or the world datasets
(Normalizer request 2026-10-19). Wraps pipeline/tools/old_url_check.py (imports fine under pipeline/venv; if the
import fails we fall back to the CLI under hf-venv, run on batches). Persistent cache:
staging/states/_state/old_url_cache.tsv  (url \t covered_by or -). Disable with STATES_OLD_SKIP=0 or --no-old-skip."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, subprocess
from pathlib import Path
TOOLS = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/tools")
HFPY = "/workspace/hf-venv/bin/python"
CACHE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/states/_state/old_url_cache.tsv"))
URL_KEYS = ("url", "source_url", "original_url", "page_url", "href")


def item_url(it):
    for k in URL_KEYS:
        v = it.get(k) if isinstance(it, dict) else None
        if isinstance(v, str) and v.startswith("http"):
            return v
    caps = it.get("caps") if isinstance(it, dict) else None
    if caps:
        c = caps[0]
        v = c.get("original_url") if isinstance(c, dict) else (c[1] if isinstance(c, (list, tuple)) and len(c) > 1 else None)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


class OldSkip:
    def __init__(self, enabled=True, log=None):
        self.enabled = enabled and os.environ.get("STATES_OLD_SKIP", "1") != "0"
        self.log = log or (lambda m: None)
        self.cache, self.chk, self.mode = {}, None, "off"
        self.n_checked = self.n_skipped = self.n_cache_hits = 0
        if not self.enabled:
            return
        if CACHE.exists():
            for line in CACHE.open(encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) == 2:
                    self.cache[p[0]] = None if p[1] == "-" else p[1]
        try:
            sys.path.insert(0, TOOLS)
            from old_url_check import UrlChecker
            self.chk, self.mode = UrlChecker(), "import"
        except Exception as e:
            self.mode = "cli" if os.path.exists(HFPY) else "off"
            self.log(f"old_url_check import failed ({type(e).__name__}); mode={self.mode}")
        self._fh = CACHE.open("a", encoding="utf-8")

    def _remember(self, url, cov):
        self.cache[url] = cov
        self._fh.write(f"{url}\t{cov or '-'}\n")

    def prefetch(self, urls):
        """Resolve many URLs at once (one CLI call per 5000 in cli mode)."""
        if not self.enabled or self.mode == "off":
            return
        new = [u for u in dict.fromkeys(urls) if u and u not in self.cache]
        if self.mode == "import":
            for u in new:
                try:
                    self._remember(u, self.chk.covered(u))
                except Exception:
                    pass
        else:
            import json
            for i in range(0, len(new), 5000):
                b = new[i:i + 5000]
                try:
                    out = subprocess.run([HFPY, f"{TOOLS}/old_url_check.py", "--json", "-f", "-"], input="\n".join(b),
                                         capture_output=True, text=True, timeout=600).stdout
                except Exception:
                    continue
                for line in out.splitlines():
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    cov = r.get("old_repo") or (f"world_municipal_law:{r['published_ref']}" if r.get("published_ref") else None)
                    self._remember(r["url"], cov)
        self._fh.flush()

    def covered(self, url):
        if not self.enabled or not url or self.mode == "off":
            return None
        self.n_checked += 1
        if url in self.cache:
            self.n_cache_hits += 1
        else:
            self.prefetch([url])
        cov = self.cache.get(url)
        if cov:
            self.n_skipped += 1
        return cov

    def summary(self):
        return f"old-url skip: mode={self.mode} checked={self.n_checked} covered_skipped={self.n_skipped} cache_hits={self.n_cache_hits}"

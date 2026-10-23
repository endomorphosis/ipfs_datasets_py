#!/usr/bin/env python3
"""Upstream skip helper for lanes: is a source URL already covered?

Index files (read-only, sqlite, rebuilt by the normalizer bot):
  /workspace/world_law/state/dedup/old_urls.sqlite       u(url PRIMARY KEY, repo)  older ipfs_*_laws / ipfs_*_municipal_laws repos
  /workspace/world_law/state/dedup/mun_published.sqlite  pu(url PRIMARY KEY, ref)  rows already in world_municipal_law
Keys are dedup_index.norm_url(url).

CLI:
  old_url_check.py URL [URL ...]          one line per URL:  <url>\t<covered_by or ->
  old_url_check.py -f urls.txt            (or '-' for stdin) same, for a file of URLs
  old_url_check.py --filter -f urls.txt   print only the URLs NOT covered (pipe into the fetch queue)
  --no-published                          check only the old repos (not world_municipal_law)
  --json                                  JSON lines {"url","norm","old_repo","published_ref"}
Exit code: 0.

Python:
  sys.path.insert(0, "/workspace/world_law/pipeline/tools"); from old_url_check import covered, UrlChecker
  covered("https://...")  -> "endomorphosis/ipfs_netherlands_municipal_laws" | "world_municipal_law:NL/wd_Q.../doc" | None
  with UrlChecker() as c: c.check(url) -> dict   (keeps the sqlite connections open for bulk use)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dedup_index as DX  # noqa: E402


class UrlChecker:
    def __init__(self, published: bool = True, state_dir: Path = None):
        d = Path(state_dir) if state_dir else DX.STATE_DIR
        self.old = DX.old_url_index(d / "old_urls.sqlite")
        self.pub = DX.PubIndex(d / "mun_published.sqlite") if published else None

    def check(self, url: str) -> dict:
        n = DX.norm_url(url)
        o = self.old.get(n) if (n and self.old.exists()) else None
        p = self.pub.get("source_url", n) if (n and self.pub is not None) else None
        return {"url": url, "norm": n, "old_repo": o, "published_ref": p}

    def covered(self, url: str):
        r = self.check(url)
        return r["old_repo"] or (f"world_municipal_law:{r['published_ref']}" if r["published_ref"] else None)

    def close(self):
        self.old.close()
        if self.pub is not None:
            self.pub.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def covered(url: str, published: bool = True):
    with UrlChecker(published) as c:
        return c.covered(url)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*")
    ap.add_argument("-f", "--file")
    ap.add_argument("--filter", action="store_true")
    ap.add_argument("--no-published", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    urls = list(a.urls)
    if a.file:
        fh = sys.stdin if a.file == "-" else open(a.file, encoding="utf-8")
        urls += [l.strip() for l in fh if l.strip()]
    with UrlChecker(not a.no_published) as c:
        for u in urls:
            r = c.check(u)
            cov = r["old_repo"] or (f"world_municipal_law:{r['published_ref']}" if r["published_ref"] else None)
            if a.filter:
                if not cov:
                    print(u)
            elif a.json:
                print(json.dumps(r, ensure_ascii=False))
            else:
                print(f"{u}\t{cov or '-'}")


if __name__ == "__main__":
    main()

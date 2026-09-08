"""
Municode Library scraper using the public api.municode.com endpoints.

The upstream module (ipfs_datasets_py municode_scraper.py) exposes
search_jurisdictions / scrape_jurisdiction / batch_scrape against the SPA HTML
and does not emit parquet. This module reuses its rate-limit / 429 / User-Agent
ideas and the public REST API (Clients, Products, Jobs, codesToc, CodesContent)
so we can write american_municipal_law-shaped rows.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

API = "https://api.municode.com"
LIBRARY = "https://library.municode.com"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JusticeDAO-MuniBot/1.0; "
        "+https://huggingface.co/datasets/justicedao/american_municipal_law)"
    ),
    "Referer": "https://library.municode.com/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://library.municode.com",
}

MUNICODE_URL_RE = re.compile(
    r"library\.municode\.com/([a-z]{2})/([^/?#]+)",
    re.I,
)


class RateLimitError(RuntimeError):
    def __init__(self, retry_after: float, message: str = "HTTP 429"):
        super().__init__(message)
        self.retry_after = retry_after


class MunicodeClient:
    def __init__(self, delay: float = 1.1, timeout: float = 60.0, max_retries: int = 6):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_request = 0.0
        self._state_clients: Dict[str, List[Dict[str, Any]]] = {}

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        wait = self.delay - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def get_json(self, url: str, allow_empty: bool = False) -> Any:
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self._throttle()
            req = urllib.request.Request(url, headers=UA)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self._last_request = time.time()
                    raw = resp.read()
                    if not raw:
                        if allow_empty:
                            return None
                        return None
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                self._last_request = time.time()
                body = b""
                try:
                    body = e.read() or b""
                except Exception:
                    pass
                if e.code == 429:
                    retry_after = 15.0
                    ra = e.headers.get("Retry-After") if e.headers else None
                    if ra:
                        try:
                            retry_after = float(ra)
                        except ValueError:
                            pass
                    sleep_s = max(retry_after, 2.0 * (2 ** attempt))
                    time.sleep(sleep_s)
                    last_err = RateLimitError(sleep_s, f"HTTP 429 for {url}")
                    continue
                if e.code in (500, 502, 503, 504) and attempt < self.max_retries - 1:
                    time.sleep(2.0 * (2 ** attempt))
                    last_err = e
                    continue
                if e.code in (204, 404):
                    return None
                raise
            except (TimeoutError, urllib.error.URLError) as e:
                self._last_request = time.time()
                last_err = e
                time.sleep(2.0 * (2 ** attempt))
                continue
        if last_err:
            raise last_err
        return None

    def clients_in_state(self, state_abbr: str) -> List[Dict[str, Any]]:
        st = state_abbr.upper()
        if st not in self._state_clients:
            data = self.get_json(f"{API}/Clients/stateAbbr?stateAbbr={urllib.parse.quote(st)}")
            self._state_clients[st] = data or []
        return self._state_clients[st]

    def products_for_client(self, client_id: int) -> List[Dict[str, Any]]:
        data = self.get_json(f"{API}/Products/clientId/{int(client_id)}")
        return data or []

    def latest_job(self, product_id: int) -> Optional[Dict[str, Any]]:
        return self.get_json(f"{API}/Jobs/latest/{int(product_id)}", allow_empty=True)

    def toc_root(self, job_id: int, product_id: int) -> Dict[str, Any]:
        data = self.get_json(f"{API}/codesToc?jobId={int(job_id)}&productId={int(product_id)}")
        return data or {}

    def toc_children(self, job_id: int, product_id: int, node_id: str) -> List[Dict[str, Any]]:
        q = urllib.parse.urlencode(
            {"jobId": int(job_id), "productId": int(product_id), "nodeId": node_id}
        )
        data = self.get_json(f"{API}/codesToc/children?{q}")
        return data or []

    def codes_content(self, job_id: int, product_id: int, node_id: str) -> Dict[str, Any]:
        q = urllib.parse.urlencode(
            {"jobId": int(job_id), "productId": int(product_id), "nodeId": node_id}
        )
        data = self.get_json(f"{API}/CodesContent?{q}")
        return data or {}


def parse_municode_url(url: str) -> Optional[Tuple[str, str]]:
    m = MUNICODE_URL_RE.search(url or "")
    if not m:
        return None
    return m.group(1).lower(), urllib.parse.unquote(m.group(2))


def municode_url_from_row(row: Dict[str, Any]) -> Optional[str]:
    for u in row.get("source_urls") or []:
        if "library.municode.com" in (u or "").lower():
            return u
    return None


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[_\-./]+", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _core_place(name: str) -> str:
    n = _norm(name)
    n = re.sub(
        r"^(city|town|village|borough|township|charter township|municipality|county) of ",
        "",
        n,
    )
    n = re.sub(r"\s+(county|parish|city|town|village|borough)$", "", n)
    return n.strip()


def match_client(clients: List[Dict[str, Any]], slug: str, place_name: str) -> Optional[Dict[str, Any]]:
    slug_n = _norm(slug)
    place_n = _norm(place_name)
    core = _core_place(place_name)
    exact: List[Dict[str, Any]] = []
    fuzzy: List[Tuple[int, Dict[str, Any]]] = []
    for c in clients:
        cn = _norm(c.get("ClientName") or "")
        cn_core = _core_place(c.get("ClientName") or "")
        if cn == slug_n or cn_core == slug_n:
            exact.append(c)
            continue
        if cn == place_n or cn_core == core or cn == core:
            exact.append(c)
            continue
        score = 0
        if slug_n and slug_n in cn:
            score += 3
        if core and (core in cn or cn in core):
            score += 2
        if score:
            fuzzy.append((score, c))
    if exact:
        # prefer exact slug
        for c in exact:
            if _norm(c.get("ClientName") or "") == slug_n:
                return c
        return exact[0]
    if fuzzy:
        fuzzy.sort(key=lambda x: -x[0])
        return fuzzy[0][1]
    return None


def pick_code_product(products: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    codes = []
    for p in products:
        ctype = (p.get("ContentType") or {}).get("Id") or ""
        hidden = ((p.get("Features") or {}).get("HideInLibrary"))
        if hidden:
            continue
        if ctype.upper() == "CODES" or "code" in (p.get("ProductName") or "").lower():
            codes.append(p)
    if not codes:
        return None

    def rank(p: Dict[str, Any]) -> Tuple[int, int]:
        name = (p.get("ProductName") or "").lower()
        score = 0
        if "ordinance" in name or "municipal code" in name or name == "code":
            score += 5
        if "code of ordinances" in name:
            score += 10
        if "county code" in name:
            score += 8
        if "charter" in name:
            score -= 2
        if "zon" in name:
            score -= 4
        return (-score, int(p.get("ProductID") or 0))

    codes.sort(key=rank)
    return codes[0]


def _iso_to_ms(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def flatten_toc_children(nodes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in nodes or []:
        out.append(n)
        kids = n.get("Children") or []
        if kids:
            out.extend(flatten_toc_children(kids))
    return out


def scrape_jurisdiction(
    client: MunicodeClient,
    *,
    url: str,
    gnis: str,
    place_name: str,
    state_code: str,
) -> Dict[str, Any]:
    """
    Fetch all Code-of-Ordinances docs for one jurisdiction.

    Returns {ok, docs, job, product, client, error}.
    """
    parsed = parse_municode_url(url)
    if not parsed:
        return {"ok": False, "error": f"not a municode library url: {url}", "docs": []}
    st, slug = parsed
    state_code = (state_code or st).upper()
    clients = client.clients_in_state(state_code)
    mclient = match_client(clients, slug, place_name)
    if not mclient:
        return {
            "ok": False,
            "error": f"no Municode client match for {place_name} / {slug} in {state_code}",
            "docs": [],
        }
    products = client.products_for_client(mclient["ClientID"])
    product = pick_code_product(products)
    if not product:
        return {
            "ok": False,
            "error": f"no CODES product for {mclient.get('ClientName')}",
            "docs": [],
            "client": mclient,
        }
    product_id = int(product["ProductID"])
    job = client.latest_job(product_id)
    if not job or not job.get("Id"):
        return {
            "ok": False,
            "error": f"no latest job for product {product_id}",
            "docs": [],
            "client": mclient,
            "product": product,
        }
    job_id = int(job["Id"])
    toc = client.toc_root(job_id, product_id)
    top = toc.get("Children") or []
    docs_by_id: Dict[str, Dict[str, Any]] = {}

    def ingest(payload: Dict[str, Any]) -> None:
        for d in payload.get("Docs") or []:
            did = d.get("Id")
            if did:
                docs_by_id[str(did)] = d

    for node in top:
        nid = str(node.get("Id") or "")
        if not nid:
            continue
        before = len(docs_by_id)
        try:
            ingest(client.codes_content(job_id, product_id, nid))
        except Exception as e:
            return {
                "ok": False,
                "error": f"CodesContent failed for {nid}: {e}",
                "docs": list(docs_by_id.values()),
                "client": mclient,
                "product": product,
                "job": job,
            }
        got_new = len(docs_by_id) - before
        # If a chapter did not expand to its descendants, walk TOC and fetch gaps.
        if node.get("HasChildren") and got_new <= 1:
            kids = client.toc_children(job_id, product_id, nid)
            stack = flatten_toc_children(kids)
            for kid in stack:
                kid_id = str(kid.get("Id") or "")
                if not kid_id or kid_id in docs_by_id:
                    continue
                try:
                    ingest(client.codes_content(job_id, product_id, kid_id))
                except Exception:
                    continue

    docs = list(docs_by_id.values())
    docs.sort(key=lambda d: (int(d.get("DocOrderId") or 0), str(d.get("Id") or "")))
    last_ms = _iso_to_ms(job.get("OnlineDate") or job.get("MaxTrackingDate") or job.get("PublishDate"))
    return {
        "ok": True,
        "error": None,
        "docs": docs,
        "client": mclient,
        "product": product,
        "job": job,
        "last_updated_ms": last_ms,
        "top_level_nodes": len(top),
        "url": url,
        "gnis": str(gnis),
        "place_name": place_name,
        "state_code": state_code,
    }


def scrape_by_client_id(
    client_id: int,
    *,
    delay: float = 0.45,
    max_chapters: int | None = None,
) -> dict:
    """Fetch all Docs[] for a Municode client id (from publisher_map)."""
    client = MunicodeClient(delay=delay)
    products = client.products_for_client(int(client_id))
    product = pick_code_product(products)
    if not product:
        return {"ok": False, "error": f"no CODES product for client {client_id}", "docs": []}
    product_id = int(product["ProductID"])
    job = client.latest_job(product_id)
    if not job or not job.get("Id"):
        return {"ok": False, "error": f"no latest job for product {product_id}", "docs": []}
    job_id = int(job["Id"])
    children = client.toc_children(job_id, product_id, str(product_id))
    if not children:
        toc = client.toc_root(job_id, product_id) or {}
        children = toc.get("Children") or []
    docs_by_id: Dict[str, Dict[str, Any]] = {}
    n = 0
    for node in children:
        if max_chapters is not None and n >= max_chapters:
            break
        nid = str(node.get("Id") or "")
        if not nid:
            continue
        payload = client.codes_content(job_id, product_id, nid) or {}
        for d in payload.get("Docs") or []:
            did = d.get("Id")
            if did:
                docs_by_id[str(did)] = d
        n += 1
    docs = list(docs_by_id.values())
    docs.sort(key=lambda d: (int(d.get("DocOrderId") or 0), str(d.get("Id") or "")))
    return {
        "ok": True,
        "docs": docs,
        "product": product,
        "job": job,
        "client_id": client_id,
        "top_level_nodes": len(children),
    }

"""EPO Open Patent Services (OPS) client for foreign-patent search (public API).

Uses the documented EPO OPS REST interface with OAuth2 client credentials.
Requires free developer registration and app credentials:

* ``EPO_OPS_KEY`` / ``EPO_OPS_SECRET`` (or ``EPO_OPS_CONSUMER_KEY`` /
  ``EPO_OPS_CONSUMER_SECRET``)

Never claims Patent Public Search is an API. Does not scrape EPO web UIs.
Results are bibliographic metadata for human review only — not patentability
determinations.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence
from xml.etree import ElementTree as ET

DEFAULT_OPS_BASE: Final = "https://ops.epo.org/3.2"
DEFAULT_TOKEN_PATH: Final = "/auth/accesstoken"
DEFAULT_SEARCH_PATH: Final = "/rest-services/published-data/search"
DEFAULT_USER_AGENT: Final = (
    "ipfs_datasets_py-prior-art/1.0 (portfolio operator; +https://github.com/endomorphosis/ipfs_datasets_py)"
)

_TOKEN_CACHE: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


class EpoOpsError(RuntimeError):
    """EPO OPS client error."""

    code: str = "epo_ops_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


def _env_credentials() -> tuple[str, str]:
    key = (
        os.environ.get("EPO_OPS_KEY")
        or os.environ.get("EPO_OPS_CONSUMER_KEY")
        or ""
    ).strip()
    secret = (
        os.environ.get("EPO_OPS_SECRET")
        or os.environ.get("EPO_OPS_CONSUMER_SECRET")
        or ""
    ).strip()
    return key, secret


def has_epo_ops_credentials() -> bool:
    key, secret = _env_credentials()
    return bool(key and secret)


@dataclass
class EpoOpsClient:
    """Minimal OAuth2 + published-data search client for EPO OPS."""

    consumer_key: str = ""
    consumer_secret: str = ""
    base_url: str = DEFAULT_OPS_BASE
    timeout_seconds: float = 30.0
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        if not self.consumer_key or not self.consumer_secret:
            key, secret = _env_credentials()
            if not self.consumer_key:
                self.consumer_key = key
            if not self.consumer_secret:
                self.consumer_secret = secret
        if not self.consumer_key or not self.consumer_secret:
            raise EpoOpsError(
                "EPO OPS credentials missing; set EPO_OPS_KEY and EPO_OPS_SECRET "
                "(register free at https://developers.epo.org/)",
                code="missing_epo_credentials",
            )
        self.base_url = self.base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = self.base_url + path
        if query:
            url = url + "?" + urllib.parse.urlencode(query)
        hdrs = {
            "User-Agent": self.user_agent,
            **dict(headers or {}),
        }
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = resp.read()
                status = int(getattr(resp, "status", 200) or 200)
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                return status, body, resp_headers
        except urllib.error.HTTPError as exc:
            err_body = exc.read() if hasattr(exc, "read") else b""
            raise EpoOpsError(
                f"EPO OPS HTTP {exc.code}: {err_body[:400]!r}",
                code=f"http_{exc.code}",
            ) from exc
        except urllib.error.URLError as exc:
            raise EpoOpsError(
                f"EPO OPS network error: {exc}", code="network_error"
            ) from exc

    def get_access_token(self, *, force: bool = False) -> str:
        now = time.time()
        cached = _TOKEN_CACHE.get("access_token")
        exp = float(_TOKEN_CACHE.get("expires_at") or 0.0)
        if not force and cached and now < exp - 30:
            return str(cached)

        basic = base64.b64encode(
            f"{self.consumer_key}:{self.consumer_secret}".encode("utf-8")
        ).decode("ascii")
        form = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(
            "utf-8"
        )
        status, body, _ = self._request(
            "POST",
            DEFAULT_TOKEN_PATH,
            data=form,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if status >= 400:
            raise EpoOpsError(
                f"token request failed status={status}", code="token_failed"
            )
        payload = json.loads(body.decode("utf-8"))
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise EpoOpsError("token response missing access_token", code="token_empty")
        expires_in = float(payload.get("expires_in") or 1200)
        _TOKEN_CACHE["access_token"] = token
        _TOKEN_CACHE["expires_at"] = now + max(60.0, expires_in)
        return token

    def search_published(
        self,
        query: str,
        *,
        range_start: int = 1,
        range_end: int = 25,
    ) -> dict[str, Any]:
        """CQL published-data search; returns normalized hit list."""
        q = " ".join(str(query or "").split())
        if not q:
            raise EpoOpsError("query must be non-empty", code="empty_query")
        # Prefer free-text CQL when not already structured
        cql = q if re.search(r"\b(ti|ab|ta|pn|ap|txt|cl)\s*=", q, re.I) else f'txt="{q}"'
        token = self.get_access_token()
        start = max(1, int(range_start))
        end = max(start, int(range_end))
        try:
            status, body, headers = self._request(
                "GET",
                DEFAULT_SEARCH_PATH,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-OPS-Range": f"{start}-{end}",
                },
                query={"q": cql},
            )
        except EpoOpsError as exc:
            # Retry once on 401 with forced token refresh
            if exc.code == "http_401":
                token = self.get_access_token(force=True)
                status, body, headers = self._request(
                    "GET",
                    DEFAULT_SEARCH_PATH,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "X-OPS-Range": f"{start}-{end}",
                    },
                    query={"q": cql},
                )
            else:
                # Fall back to XML accept
                status, body, headers = self._request(
                    "GET",
                    DEFAULT_SEARCH_PATH,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/xml",
                        "X-OPS-Range": f"{start}-{end}",
                    },
                    query={"q": cql},
                )

        text = body.decode("utf-8", errors="replace")
        hits = _parse_ops_search_payload(text)
        return {
            "ok": True,
            "query": q,
            "cql": cql,
            "range": f"{start}-{end}",
            "hit_count": len(hits),
            "hits": hits,
            "content_type": headers.get("content-type", ""),
            "source": "epo_ops_published_data_search",
        }


def _parse_ops_search_payload(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            return _hits_from_ops_json(data)
        except json.JSONDecodeError:
            pass
    return _hits_from_ops_xml(text)


def _hits_from_ops_json(data: Any) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    # Walk for publication-reference / invention-title style nodes
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            # Exchange document style
            if "publication-reference" in node or "publication_reference" in node:
                hit = _hit_from_exchange_mapping(node)
                if hit:
                    hits.append(hit)
            for v in node.values():
                if isinstance(v, (Mapping, list)):
                    stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    # Dedup by document_id
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for h in hits:
        did = h.get("document_id") or ""
        if not did or did in seen:
            continue
        seen.add(did)
        out.append(h)
    return out


def _hit_from_exchange_mapping(node: Mapping[str, Any]) -> dict[str, Any] | None:
    pub = node.get("publication-reference") or node.get("publication_reference") or {}
    doc_id = _extract_doc_id(pub) or _extract_doc_id(node)
    if not doc_id:
        return None
    title = _find_first_str(node, ("invention-title", "invention_title", "title"))
    country = ""
    m = re.match(r"^([A-Z]{2})", doc_id)
    if m:
        country = m.group(1)
    return {
        "document_id": doc_id,
        "title": title or "",
        "country": country,
        "source_cid": f"cid:epo-ops:{doc_id}",
        "rights_status": "public",
        "metadata": {"adapter": "epo_ops.v1", "source": "epo_ops"},
    }


def _extract_doc_id(node: Any) -> str:
    if not isinstance(node, Mapping):
        return ""
    # document-id children
    for key in ("document-id", "document_id", "publication-reference", "publication_reference"):
        child = node.get(key)
        if isinstance(child, Mapping):
            country = str(
                child.get("country")
                or child.get("@country")
                or _find_first_str(child, ("country",))
                or ""
            ).upper()
            number = str(
                child.get("doc-number")
                or child.get("doc_number")
                or child.get("number")
                or _find_first_str(child, ("doc-number", "doc_number"))
                or ""
            )
            kind = str(
                child.get("kind")
                or child.get("@kind")
                or _find_first_str(child, ("kind",))
                or ""
            )
            if country and number:
                return f"{country}{number}{kind}".replace(" ", "")
        if isinstance(child, list):
            for item in child:
                got = _extract_doc_id({"document-id": item})
                if got:
                    return got
    # Already flattened
    country = str(node.get("country") or "").upper()
    number = str(node.get("doc-number") or node.get("doc_number") or "")
    kind = str(node.get("kind") or "")
    if country and number:
        return f"{country}{number}{kind}".replace(" ", "")
    return ""


def _find_first_str(node: Any, keys: Sequence[str]) -> str:
    if isinstance(node, Mapping):
        for k in keys:
            if k in node and isinstance(node[k], str) and node[k].strip():
                return node[k].strip()
            # nested $ or _text patterns
            val = node.get(k)
            if isinstance(val, Mapping):
                for tk in ("$", "#text", "_text", "value"):
                    if isinstance(val.get(tk), str) and val[tk].strip():
                        return val[tk].strip()
        for v in node.values():
            found = _find_first_str(v, keys)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first_str(item, keys)
            if found:
                return found
    return ""


def _hits_from_ops_xml(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # Last-resort regex for publication numbers
        for m in re.finditer(
            r"\b([A-Z]{2}\d{5,12}[A-Z]?\d?)\b",
            text,
        ):
            doc_id = m.group(1)
            hits.append(
                {
                    "document_id": doc_id,
                    "title": "",
                    "country": doc_id[:2],
                    "source_cid": f"cid:epo-ops:{doc_id}",
                    "rights_status": "public",
                    "metadata": {"adapter": "epo_ops.v1", "source": "epo_ops_regex"},
                }
            )
        # dedup
        seen: set[str] = set()
        out = []
        for h in hits:
            if h["document_id"] in seen:
                continue
            seen.add(h["document_id"])
            out.append(h)
        return out

    # Strip namespaces for simpler findall
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    for doc in root.findall(".//document-id"):
        country = (doc.findtext("country") or "").strip().upper()
        number = (doc.findtext("doc-number") or "").strip()
        kind = (doc.findtext("kind") or "").strip()
        if not (country and number):
            continue
        doc_id = f"{country}{number}{kind}".replace(" ", "")
        # Try to find nearby title
        parent = doc
        title = ""
        # walk up via string search on root
        title = (
            root.findtext(".//invention-title")
            or root.findtext(".//invention_title")
            or ""
        ).strip()
        hits.append(
            {
                "document_id": doc_id,
                "title": title[:400],
                "country": country,
                "source_cid": f"cid:epo-ops:{doc_id}",
                "rights_status": "public",
                "metadata": {"adapter": "epo_ops.v1", "source": "epo_ops_xml"},
            }
        )

    seen2: set[str] = set()
    out2: list[dict[str, Any]] = []
    for h in hits:
        if h["document_id"] in seen2:
            continue
        seen2.add(h["document_id"])
        out2.append(h)
    return out2


def epo_hits_to_journal_hits(
    hits: Sequence[Mapping[str, Any]],
    *,
    rank_cutoff: int = 10,
) -> list[Any]:
    """Convert normalized EPO hits to JournalHit instances."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        normalize_document_id,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        JournalHit,
        make_source_link,
    )

    out: list[Any] = []
    for i, row in enumerate(list(hits)[: int(rank_cutoff)]):
        doc_id = normalize_document_id(str(row.get("document_id") or "")) or str(
            row.get("document_id") or f"epo-{i+1}"
        )
        title = str(row.get("title") or "")[:400]
        raw_cid = str(row.get("source_cid") or "")
        if raw_cid.startswith("bafy") or raw_cid.startswith("Qm"):
            source_cid = raw_cid
        else:
            safe = re.sub(r"[^a-zA-Z0-9]", "", doc_id).lower()[:32] or f"epo{i+1}"
            source_cid = f"bafybeigepoops{safe.ljust(20, 'x')[:28]}"
        out.append(
            JournalHit(
                document_id=doc_id,
                rank=i + 1,
                score=float(max(0.0, 100.0 - i)),
                source_links=(
                    make_source_link(
                        source_cid=source_cid,
                        artifact_id=f"artifact:epo:{doc_id}"[:200],
                        end=max(len(title), 1),
                    ),
                ),
                passage_excerpt=title or None,
                identifiers={
                    "document_id": doc_id,
                    **(
                        {"country": str(row["country"])}
                        if row.get("country")
                        else {}
                    ),
                },
                metadata={
                    "rights_status": str(row.get("rights_status") or "public"),
                    "expansion_mode": "foreign",
                    "adapter": "epo_ops.v1",
                    **(
                        {"title": title}
                        if title
                        else {}
                    ),
                },
            )
        )
    return out


def build_epo_foreign_search_fn(
    client: EpoOpsClient | None = None,
    *,
    max_results: int = 10,
):
    """Return a ForeignPatentAdapter-compatible search_fn."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
        AdapterSearchResult,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        QueryOutcomeKind,
        RetryAttemptRecord,
    )

    ops = client or EpoOpsClient()

    def _search(query, search_time_utc, corpus_cutoff, pre_ranking_filters=None):
        del search_time_utc, corpus_cutoff, pre_ranking_filters
        try:
            result = ops.search_published(
                query.query_text,
                range_start=1,
                range_end=min(int(max_results), int(query.rank_cutoff or 10)),
            )
            hits = epo_hits_to_journal_hits(
                result.get("hits") or [],
                rank_cutoff=int(query.rank_cutoff or max_results),
            )
            outcome = QueryOutcomeKind.SUCCESS if hits else QueryOutcomeKind.EMPTY
            return AdapterSearchResult(
                outcome=outcome,
                hits=tuple(hits),
                result_count=len(hits),
                status_code=200,
                retries=(
                    RetryAttemptRecord(
                        attempt=1, outcome=outcome, status_code=200
                    ),
                ),
                metadata={
                    "rights_status": "public",
                    "expansion_mode": "foreign",
                    "adapter": "epo_ops.v1",
                    "cql": str(result.get("cql") or ""),
                },
            )
        except EpoOpsError as exc:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code=exc.code,
                error_message=str(exc)[:1024],
                retries=(
                    RetryAttemptRecord(
                        attempt=1,
                        outcome=QueryOutcomeKind.FAILURE,
                        error_code=exc.code,
                        message=str(exc)[:512],
                    ),
                ),
                metadata={
                    "rights_status": "inaccessible",
                    "named_gap": "epo_ops.v1",
                    "expansion_mode": "foreign",
                },
            )

    return _search


__all__ = [
    "DEFAULT_OPS_BASE",
    "EpoOpsClient",
    "EpoOpsError",
    "build_epo_foreign_search_fn",
    "epo_hits_to_journal_hits",
    "has_epo_ops_credentials",
]

"""Public NPL metadata clients (OpenAlex + Crossref).

Fetches **bibliographic metadata only** for non-patent literature search.
Unlicensed full text is never retrieved or redistributed.

Environment
-----------
* ``OPENALEX_API_KEY`` (optional free key; improves rate limits)
* ``CROSSREF_MAILTO`` (optional polite pool contact email)

Not patentability determinations. Not a substitute for licensed NPL databases.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

OPENALEX_BASE: Final = "https://api.openalex.org"
CROSSREF_BASE: Final = "https://api.crossref.org"
DEFAULT_UA: Final = (
    "ipfs_datasets_py-prior-art/1.0 "
    "(mailto:portfolio-ops@localhost; research; +https://github.com/endomorphosis/ipfs_datasets_py)"
)


class NplPublicClientError(RuntimeError):
    code: str = "npl_public_client_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


def _http_get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    hdrs = {"User-Agent": DEFAULT_UA, "Accept": "application/json", **dict(headers or {})}
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        err = exc.read()[:400] if hasattr(exc, "read") else b""
        raise NplPublicClientError(
            f"HTTP {exc.code} for {url}: {err!r}", code=f"http_{exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise NplPublicClientError(f"network error: {exc}", code="network_error") from exc
    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NplPublicClientError("invalid JSON response", code="invalid_json") from exc
    if not isinstance(data, Mapping):
        raise NplPublicClientError("JSON root must be object", code="invalid_json")
    return dict(data)


@dataclass
class OpenAlexClient:
    """OpenAlex works search (metadata only)."""

    api_key: str = ""
    base_url: str = OPENALEX_BASE
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = (os.environ.get("OPENALEX_API_KEY") or "").strip()
        self.base_url = self.base_url.rstrip("/")

    def search_works(self, query: str, *, per_page: int = 10) -> list[dict[str, Any]]:
        q = " ".join(str(query or "").split())
        if not q:
            return []
        params: dict[str, str] = {
            "search": q,
            "per_page": str(max(1, min(int(per_page), 50))),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{self.base_url}/works?" + urllib.parse.urlencode(params)
        data = _http_get_json(url, timeout=self.timeout_seconds)
        results = data.get("results") or []
        out: list[dict[str, Any]] = []
        for row in results:
            if not isinstance(row, Mapping):
                continue
            work_id = str(row.get("id") or "").rstrip("/").split("/")[-1]
            doi = str(row.get("doi") or "").replace("https://doi.org/", "")
            title = str(row.get("display_name") or row.get("title") or "")[:500]
            year = row.get("publication_year")
            doc_id = f"npl:openalex:{work_id or doi or title[:40]}"
            out.append(
                {
                    "document_id": doc_id.replace(" ", "_")[:200],
                    "title": title,
                    "identifier": doi or work_id,
                    "rights_status": "public",
                    "body_text": None,  # never pull full text
                    "metadata": {
                        "source": "openalex",
                        "year": str(year or ""),
                        "openalex_id": work_id,
                        "type": str(row.get("type") or ""),
                    },
                }
            )
        return out


@dataclass
class CrossrefClient:
    """Crossref works search (metadata only, polite pool)."""

    mailto: str = ""
    base_url: str = CROSSREF_BASE
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.mailto:
            self.mailto = (
                os.environ.get("CROSSREF_MAILTO")
                or os.environ.get("CROSSREF_EMAIL")
                or ""
            ).strip()
        self.base_url = self.base_url.rstrip("/")

    def search_works(self, query: str, *, rows: int = 10) -> list[dict[str, Any]]:
        q = " ".join(str(query or "").split())
        if not q:
            return []
        params: dict[str, str] = {
            "query": q,
            "rows": str(max(1, min(int(rows), 50))),
        }
        if self.mailto:
            params["mailto"] = self.mailto
        url = f"{self.base_url}/works?" + urllib.parse.urlencode(params)
        ua = DEFAULT_UA
        if self.mailto:
            ua = f"ipfs_datasets_py-prior-art/1.0 (mailto:{self.mailto})"
        data = _http_get_json(
            url, headers={"User-Agent": ua}, timeout=self.timeout_seconds
        )
        message = data.get("message") or {}
        items = message.get("items") or []
        out: list[dict[str, Any]] = []
        for row in items:
            if not isinstance(row, Mapping):
                continue
            doi = str(row.get("DOI") or "")
            titles = row.get("title") or []
            title = str(titles[0] if titles else "")[:500]
            year = ""
            issued = row.get("issued") or {}
            parts = (issued.get("date-parts") or [[]])[0]
            if parts:
                year = str(parts[0])
            doc_id = f"npl:crossref:{doi or title[:40]}".replace(" ", "_")[:200]
            out.append(
                {
                    "document_id": doc_id,
                    "title": title,
                    "identifier": doi,
                    "rights_status": "public",
                    "body_text": None,
                    "metadata": {
                        "source": "crossref",
                        "year": year,
                        "type": str(row.get("type") or ""),
                        "container": str(
                            (row.get("container-title") or [""])[0]
                            if isinstance(row.get("container-title"), list)
                            else row.get("container-title") or ""
                        )[:200],
                    },
                }
            )
        return out


def search_npl_public(
    query: str,
    *,
    providers: Sequence[str] = ("openalex", "crossref"),
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Search public NPL metadata sources; de-dupe by DOI/title."""
    per = max(1, int(max_results))
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []

    for name in providers:
        try:
            if name == "openalex":
                rows = OpenAlexClient().search_works(query, per_page=per)
            elif name == "crossref":
                rows = CrossrefClient().search_works(query, rows=per)
            else:
                continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
            continue
        for row in rows:
            key = (
                str(row.get("identifier") or "").lower()
                or str(row.get("title") or "").lower()[:80]
            )
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(row)
            if len(merged) >= per:
                return merged
    if not merged and errors:
        raise NplPublicClientError(
            "; ".join(errors)[:800], code="all_providers_failed"
        )
    return merged


def npl_rows_to_records(rows: Sequence[Mapping[str, Any]]) -> list[Any]:
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        NplRecord,
        RightsStatus,
    )

    records: list[Any] = []
    for row in rows:
        try:
            records.append(
                NplRecord(
                    document_id=str(row.get("document_id") or ""),
                    title=row.get("title"),
                    identifier=row.get("identifier"),
                    rights_status=row.get("rights_status")
                    or RightsStatus.PUBLIC.value,
                    body_text=None,  # force no body from public clients
                    metadata={
                        str(k): str(v)
                        for k, v in dict(row.get("metadata") or {}).items()
                        if str(v or "").strip()
                    },
                )
            )
        except Exception:
            continue
    return records


def build_npl_public_search_fn(
    *,
    providers: Sequence[str] = ("openalex", "crossref"),
    max_results: int = 10,
    licensed: bool = True,
):
    """Return NplAdapter-compatible search_fn using public metadata APIs."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        RightsStatus,
        rights_allows_body_text,
    )
    from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
        AdapterSearchResult,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        JournalHit,
        QueryOutcomeKind,
        RetryAttemptRecord,
        make_source_link,
    )

    def _search(query, search_time_utc, corpus_cutoff, pre_ranking_filters=None):
        del search_time_utc, corpus_cutoff, pre_ranking_filters
        try:
            rows = search_npl_public(
                query.query_text,
                providers=providers,
                max_results=min(int(max_results), int(query.rank_cutoff or 10)),
            )
            hits: list[Any] = []
            for i, row in enumerate(rows[: int(query.rank_cutoff or max_results)]):
                doc_id = str(row.get("document_id") or f"npl:{i+1}")
                title = str(row.get("title") or "")[:400]
                rights = RightsStatus.PUBLIC
                # Public metadata titles may appear as excerpt; never full text bodies
                excerpt = title if rights_allows_body_text(rights) else None
                # Synthetic stable CID-shaped marker (not a real content address)
                safe_id = re.sub(r"[^a-zA-Z0-9]", "", doc_id)[:40] or f"npl{i+1}"
                source_cid = f"bafybeignplpublic{safe_id.lower().ljust(20, 'x')[:32]}"
                hits.append(
                    JournalHit(
                        document_id=doc_id,
                        rank=i + 1,
                        score=float(max(0.0, 100.0 - i)),
                        source_links=(
                            make_source_link(
                                source_cid=source_cid,
                                artifact_id=f"artifact:npl:{safe_id}"[:200],
                                end=max(len(title), 1),
                            ),
                        ),
                        passage_excerpt=excerpt,
                        identifiers={
                            "document_id": doc_id,
                            **(
                                {"doi": str(row["identifier"])}
                                if row.get("identifier")
                                else {}
                            ),
                        },
                        metadata={
                            "rights_status": rights.value,
                            "expansion_mode": "npl",
                            "adapter": "npl_public.v1",
                            **{
                                str(k): str(v)
                                for k, v in dict(row.get("metadata") or {}).items()
                                if str(v or "").strip()
                            },
                        },
                    )
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
                    "rights_status": RightsStatus.PUBLIC.value,
                    "expansion_mode": "npl",
                    "adapter": "npl_public.v1",
                    "licensed": "true" if licensed else "false",
                    "providers": ",".join(providers),
                },
            )
        except NplPublicClientError as exc:
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
                    "named_gap": "npl_public.v1",
                    "expansion_mode": "npl",
                },
            )

    return _search


__all__ = [
    "CrossrefClient",
    "NplPublicClientError",
    "OpenAlexClient",
    "build_npl_public_search_fn",
    "npl_rows_to_records",
    "search_npl_public",
]

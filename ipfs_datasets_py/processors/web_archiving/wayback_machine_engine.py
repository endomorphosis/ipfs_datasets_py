"""Wayback Machine search and retrieval engine — canonical location.

Contains domain logic for Internet Archive's Wayback Machine integration.
MCP tool wrapper lives in:
    ipfs_datasets_py/mcp_server/tools/web_archive_tools/wayback_machine_search.py

Reusable by:
    - MCP server tools (mcp_server/tools/web_archive_tools/)
    - CLI commands
    - Direct Python imports
"""

import hashlib
import json
import logging
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence
from urllib.parse import urlencode, urlparse, urlsplit, urlunparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

logger = logging.getLogger(__name__)

_MODULE_SOURCE_PATH = Path(__file__).resolve()
MODULE_IMPORT_SOURCE_SHA256 = hashlib.sha256(_MODULE_SOURCE_PATH.read_bytes()).hexdigest()


def assert_module_source_unchanged() -> str:
    """Fail if this producer's source bytes changed after module import."""

    current = hashlib.sha256(_MODULE_SOURCE_PATH.read_bytes()).hexdigest()
    if current != MODULE_IMPORT_SOURCE_SHA256:
        raise RuntimeError(f"loaded module source drifted on disk: {_MODULE_SOURCE_PATH}")
    return current


@dataclass(frozen=True)
class ExactHttpLocator:
    """Parsed HTTP(S) locator whose path and query spelling stay byte-exact."""

    raw: str
    scheme: str
    hostname: str
    path: str
    query: str
    has_query: bool


@dataclass(frozen=True)
class WaybackArchiveLocator:
    """One canonical Wayback replay locator and its embedded original."""

    raw: str
    timestamp: str
    modifier: str
    original_url: str


def parse_exact_http_locator(value: object) -> ExactHttpLocator:
    """Parse a strict, unauthenticated, default-port HTTP(S) locator.

    The returned path/query are the original spellings.  In particular this
    function never decodes percent escapes, turns ``+`` into a space, reorders
    query pairs, or moves a terminal slash across the query delimiter.
    """

    if type(value) is not str:
        raise ValueError("HTTP(S) locators must use an exact string value")
    raw_value = value
    raw = raw_value.strip()
    if not raw or raw != raw_value or any(character.isspace() for character in raw):
        raise ValueError("HTTP(S) locators must be non-empty and contain no whitespace")
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in raw):
        raise ValueError("HTTP(S) locators must use transport-stable ASCII spelling")
    # urlsplit treats an empty fragment marker as no fragment.  Reject the raw
    # delimiter so both ``#value`` and a terminal empty ``#`` fail closed.
    if "#" in raw:
        raise ValueError("HTTP(S) locators must not contain fragments")
    if "\\" in raw:
        raise ValueError("HTTP(S) locators must not contain backslashes")
    try:
        parsed = urlsplit(raw)
        # requests decodes percent escapes in the authority while preparing a
        # request.  Reject them before deriving either the host identity or an
        # embedded Wayback original from a spelling the transport will mutate.
        if "%" in parsed.netloc:
            raise ValueError("HTTP(S) locator authority must not contain percent escapes")
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("HTTP(S) locator has an invalid authority or port") from exc
    scheme = parsed.scheme.lower()
    hostname = str(parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname or not parsed.netloc:
        raise ValueError("HTTP(S) locators must be absolute")
    if not raw.startswith(f"{scheme}://"):
        raise ValueError("HTTP(S) locator scheme spelling is not transport-stable")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("HTTP(S) locators must not contain authentication")
    expected_port = 80 if scheme == "http" else 443
    if port not in {None, expected_port}:
        raise ValueError("HTTP(S) locators must use their scheme's default port")
    # ``hostname:`` has no numeric port and otherwise slips through .port.
    authority_without_default = parsed.netloc
    if hostname.startswith("[") or hostname.endswith("]"):
        raise ValueError("HTTP(S) locator has an invalid host")
    host_spelling = f"[{parsed.hostname}]" if ":" in str(parsed.hostname or "") else str(parsed.hostname)
    allowed_authorities = {host_spelling, hostname}
    if port is not None:
        allowed_authorities.update(
            {f"{host_spelling}:{expected_port}", f"{hostname}:{expected_port}"}
        )
    if authority_without_default.lower() not in {
        authority.lower() for authority in allowed_authorities
    }:
        raise ValueError("HTTP(S) locator has a non-canonical authority")
    if authority_without_default != authority_without_default.lower():
        raise ValueError("HTTP(S) locator authority spelling is not transport-stable")
    if parsed.path and not parsed.path.startswith("/"):
        raise ValueError("HTTP(S) locator path must be absolute")
    if "?" in raw and parsed.query == "":
        # requests removes a terminal empty query delimiter.  Treating the
        # prepared request as the submitted locator would therefore be false.
        raise ValueError("HTTP(S) locator has a transport-unstable empty query")

    # requests/urllib3 normalize dot segments, lowercase percent escapes, and
    # percent-encoded unreserved characters while preparing a request.  Reject
    # those spellings up front; stable escapes such as uppercase ``%2F`` stay
    # byte-exact and remain distinct identity components.
    escaped_components = (parsed.path, parsed.query)
    unreserved = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
    stable_path_characters = unreserved | frozenset("!$&'()*+,;=:@/%")
    stable_query_characters = stable_path_characters | frozenset("?")
    for component_index, component in enumerate(escaped_components):
        stable_characters = (
            stable_path_characters
            if component_index == 0
            else stable_query_characters
        )
        if any(character not in stable_characters for character in component):
            raise ValueError("HTTP(S) locator contains transport-unstable characters")
        index = 0
        while index < len(component):
            if component[index] != "%":
                index += 1
                continue
            escape = component[index + 1 : index + 3]
            if len(escape) != 2 or re.fullmatch(r"[0-9A-F]{2}", escape) is None:
                raise ValueError("HTTP(S) locator has a transport-unstable percent escape")
            if chr(int(escape, 16)) in unreserved:
                raise ValueError(
                    "HTTP(S) locator percent-encodes an unreserved character"
                )
            index += 3

    decoded_path_for_segments = re.sub(
        r"%2E",
        ".",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if any(segment in {".", ".."} for segment in decoded_path_for_segments.split("/")):
        raise ValueError("HTTP(S) locator path contains a transport-unstable dot segment")
    return ExactHttpLocator(
        raw=raw,
        scheme=scheme,
        hostname=hostname,
        path=parsed.path,
        query=parsed.query,
        has_query="?" in raw,
    )


def exact_http_locator_identity(
    value: object,
    *,
    allow_http_https_equivalence: bool = False,
) -> tuple[str, str, str, bool, str]:
    """Return strict identity, tolerating at most one PATH terminal slash."""

    parsed = parse_exact_http_locator(value)
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    scheme = "http(s)" if allow_http_https_equivalence else parsed.scheme
    return (scheme, parsed.hostname, path, parsed.has_query, parsed.query)


def same_exact_http_locator(
    left: object,
    right: object,
    *,
    allow_http_https_equivalence: bool = False,
) -> bool:
    """Compare parsed locators without query/path aliasing."""

    try:
        return exact_http_locator_identity(
            left,
            allow_http_https_equivalence=allow_http_https_equivalence,
        ) == exact_http_locator_identity(
            right,
            allow_http_https_equivalence=allow_http_https_equivalence,
        )
    except ValueError:
        return False


_WAYBACK_ARCHIVE_URL_RE = re.compile(
    r"^https://web\.archive\.org/web/(\d{14})(id_|if_)?/(https?://.+)$"
)


def parse_wayback_archive_url(
    value: object,
    *,
    allowed_modifiers: Sequence[str] = ("", "id_"),
    require_identity_modifier: bool = False,
) -> WaybackArchiveLocator:
    """Parse an anchored canonical Wayback archive locator."""

    raw_value = str(value or "")
    raw = raw_value.strip()
    if raw != raw_value or "#" in raw or any(character.isspace() for character in raw):
        raise ValueError("Wayback archive locator is not canonical")
    match = _WAYBACK_ARCHIVE_URL_RE.fullmatch(raw)
    if match is None:
        raise ValueError("Wayback archive locator must use canonical HTTPS replay syntax")
    timestamp, modifier, original_url = match.groups()
    modifier = modifier or ""
    if modifier not in set(allowed_modifiers):
        raise ValueError("Wayback replay modifier is not allowed")
    if require_identity_modifier and modifier != "id_":
        raise ValueError("Wayback replay must use the identity modifier")
    if not _valid_capture_timestamp(timestamp):
        raise ValueError("Wayback replay timestamp must be a real fourteen-digit instant")
    parse_exact_http_locator(original_url)
    return WaybackArchiveLocator(
        raw=raw,
        timestamp=timestamp,
        modifier=modifier,
        original_url=original_url,
    )


def validate_wayback_cdx_url(value: object, *, require_query: bool = False) -> str:
    """Validate the canonical HTTPS CDX endpoint without normalizing its query."""

    parsed = parse_exact_http_locator(value)
    if (
        not parsed.raw.startswith("https://web.archive.org/")
        or parsed.scheme != "https"
        or parsed.hostname != "web.archive.org"
        or parsed.path != "/cdx/search/cdx"
        or (require_query and (not parsed.has_query or not parsed.query))
    ):
        raise ValueError("Wayback CDX URL must be canonical HTTPS web.archive.org/cdx/search/cdx")
    return parsed.raw


async def fetch_wayback_cdx_rows(
    cdx_url: str,
    *,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Fetch one bounded Wayback CDX query through the shared archive layer.

    The complete JSON response is retained as a digest-bearing discovery
    receipt while callers receive both the original row matrix and normalized
    capture dictionaries.  Only the canonical HTTPS Wayback CDX endpoint is
    allowed and redirects are forbidden.
    """

    try:
        secure_url = validate_wayback_cdx_url(cdx_url)
    except ValueError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "results": [],
            "rows": [],
        }
    timeout = max(1, int(timeout_seconds or 30))

    def _blocking_fetch() -> tuple[int, str, bytes]:
        import requests

        response = requests.get(
            secure_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
            allow_redirects=False,
        )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code != 200:
            error = RuntimeError(
                f"Wayback CDX request did not return exact HTTP 200: {status_code or '<missing>'}"
            )
            setattr(error, "response", response)
            raise error
        final_url = str(getattr(response, "url", "") or "").strip()
        validate_wayback_cdx_url(final_url)
        if final_url != secure_url:
            raise RuntimeError("Wayback CDX response locator drifted from the exact request")
        return status_code, final_url, bytes(response.content or b"")

    try:
        status_code, final_url, payload = await asyncio.to_thread(_blocking_fetch)
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, list):
            raise ValueError("Wayback CDX response must be a JSON row matrix")
        rows: List[List[Any]] = [list(row) for row in decoded if isinstance(row, list)]
        if not rows:
            headers: List[str] = []
            data_rows: List[List[Any]] = []
        else:
            headers = [str(value or "").strip().lower() for value in rows[0]]
            data_rows = rows[1:]

        results: List[Dict[str, Any]] = []
        for row in data_rows:
            projected = {
                headers[index]: value
                for index, value in enumerate(row)
                if index < len(headers) and headers[index]
            }
            timestamp = str(projected.get("timestamp") or "").strip()
            original_url = str(
                projected.get("original") or projected.get("url") or ""
            ).strip()
            normalized = dict(projected)
            normalized["timestamp"] = timestamp
            normalized["original_url"] = original_url
            normalized["wayback_url"] = (
                f"https://web.archive.org/web/{timestamp}id_/{original_url}"
                if timestamp and original_url
                else ""
            )
            results.append(normalized)

        fetched_at = datetime.now(timezone.utc).isoformat()
        receipt = {
            "schema_version": "wayback-cdx-discovery-receipt-v1",
            "source_transport": "wayback_cdx",
            "query_url": secure_url,
            "response_url": final_url,
            "response_status": status_code,
            "response_sha256": hashlib.sha256(payload).hexdigest(),
            "response_length": len(payload),
            "row_count": len(results),
            "fetched_at": fetched_at,
        }
        return {
            "status": "success",
            "url": secure_url,
            "count": len(results),
            "rows": rows,
            "results": results,
            "receipt": receipt,
        }
    except Exception as exc:
        logger.error("Wayback CDX query failed for %s: %s", secure_url, exc)
        error_result: Dict[str, Any] = {
            "status": "error",
            "url": secure_url,
            "error": f"{type(exc).__name__}: {exc}",
            "results": [],
            "rows": [],
        }
        error_response = getattr(exc, "response", None)
        try:
            error_status = int(getattr(error_response, "status_code", 0) or 0)
        except (TypeError, ValueError):
            error_status = 0
        if error_status:
            error_result["response_status"] = error_status
        response_headers = getattr(error_response, "headers", None)
        if isinstance(response_headers, Mapping):
            retry_after = str(response_headers.get("Retry-After") or "").strip()
            if retry_after:
                error_result["retry_after"] = retry_after
        return error_result


_WAYBACK_CAPTURE_TIMESTAMP_RE = re.compile(r"^\d{14}$")
# web.archive.org rejects a request line above 4094 bytes.  Live bounded
# verification on 2026-08-26 proved an eight-target/1777-byte Virginia exact
# filter succeeds and a 22-target/4383-byte filter receives HTTP 400.  Keep a
# conservative half-limit byte bound plus the independently proven target cap.
_WAYBACK_CDX_MAX_QUERY_URL_BYTES = 2_048
_WAYBACK_CDX_MAX_EXACT_TARGETS_PER_QUERY = 8


def _exact_wayback_inventory_url(value: str) -> str:
    """Validate and return one exact HTTP(S) frontier locator."""

    try:
        return parse_exact_http_locator(value).raw
    except ValueError as exc:
        raise ValueError("Wayback inventory URLs must be valid HTTP(S) locators") from exc


def _same_exact_wayback_original(left: str, right: str) -> bool:
    """Keep Wayback's embedded original bound to the official locator.

    A terminal slash is the only tolerated spelling difference.  In
    particular, an archived ``http`` page is not silently relabeled as the
    bytes of an ``https`` official locator.
    """

    return same_exact_http_locator(left, right)


def _canonical_locator_spelling(locator: ExactHttpLocator, path: str) -> str:
    hostname = (
        f"[{locator.hostname}]" if ":" in locator.hostname else locator.hostname
    )
    rendered = f"{locator.scheme}://{hostname}{path}"
    if locator.has_query:
        rendered += f"?{locator.query}"
    return rendered


def _exact_original_spellings(value: str) -> List[str]:
    """Return only spellings in the parsed one-terminal-PATH-slash identity."""

    locator = parse_exact_http_locator(value)
    raw_path = locator.path
    if raw_path.endswith("//"):
        paths = [raw_path]
    elif raw_path.endswith("/"):
        paths = [raw_path[:-1], raw_path]
    else:
        paths = [raw_path, raw_path + "/"]
    spellings: List[str] = []
    for path in paths:
        canonical = _canonical_locator_spelling(locator, path)
        if canonical not in spellings:
            spellings.append(canonical)
        # Preserve the submitted scheme/authority spelling as a CDX filter
        # alternative while keeping its exact path/query untouched.
        split = urlsplit(locator.raw)
        submitted = f"{split.scheme}://{split.netloc}{path}"
        if locator.has_query:
            submitted += f"?{locator.query}"
        if submitted not in spellings:
            spellings.append(submitted)
    return spellings


def _wayback_inventory_groups(
    urls: Sequence[str],
) -> List[tuple[str, List[str]]]:
    """Group exact URLs under tight same-origin CDX prefixes.

    Query-bearing locators remain exact groups because a path prefix cannot
    safely represent their query identity.  Ordinary pages share their parent
    directory and, when possible, a common filename prefix.  This reduces a
    title/chapter/section frontier to a bounded number of CDX calls without
    conflating origins or response identities.
    """

    grouped: Dict[tuple[str, str, str, str], List[str]] = {}
    for url in urls:
        parsed = urlparse(url)
        if parsed.params or parsed.query:
            group_key = (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                f";{parsed.params}?{parsed.query}",
            )
        else:
            path = parsed.path or "/"
            parent = posixpath.dirname(path)
            if not parent.endswith("/"):
                parent += "/"
            group_key = (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parent,
                "",
            )
        grouped.setdefault(group_key, []).append(url)

    planned: List[tuple[str, List[str]]] = []
    for (scheme, netloc, parent_or_path, query_marker), members in grouped.items():
        if query_marker:
            prefix = members[0]
        else:
            basenames = [posixpath.basename(urlparse(member).path) for member in members]
            filename_prefix = (
                posixpath.commonprefix(basenames)
                if len(members) > 1
                else basenames[0]
            )
            # A one-character filename prefix is generally broader than the
            # already bounded directory query and provides no useful safety.
            if len(filename_prefix) < 2:
                filename_prefix = ""
            prefix = urlunparse(
                (scheme, netloc, parent_or_path + filename_prefix, "", "", "")
            )
        planned.append((prefix, members))
    planned.sort(key=lambda item: item[0])
    return planned


def _coalesce_wayback_inventory_groups(
    groups: Sequence[tuple[str, List[str]]],
    *,
    max_queries: int,
) -> List[tuple[str, List[str]]]:
    """Broaden sibling path prefixes only as needed to honor a query bound."""

    working = [(prefix, list(members)) for prefix, members in groups]
    while len(working) > max_queries:
        # Broadening can make formerly distinct child groups share the exact
        # same prefix.  Merge those groups in place before walking to their
        # parent; otherwise `/vacode/` siblings are accidentally widened once
        # more to the host root merely because they remain separate rows.
        identical_prefixes: Dict[str, List[int]] = {}
        for index, (prefix, _members) in enumerate(working):
            identical_prefixes.setdefault(prefix, []).append(index)
        identical_candidates = [
            (prefix, indexes)
            for prefix, indexes in identical_prefixes.items()
            if len(indexes) > 1
        ]
        if identical_candidates:
            prefix, merge_indexes = sorted(
                identical_candidates,
                key=lambda item: (-len(item[1]), item[0]),
            )[0]
            merge_set = set(merge_indexes)
            merged_members: List[str] = []
            for index in merge_indexes:
                merged_members.extend(working[index][1])
            working = [
                group for index, group in enumerate(working) if index not in merge_set
            ]
            working.append((prefix, list(dict.fromkeys(merged_members))))
            working.sort(key=lambda item: item[0])
            continue
        covering_candidates: List[tuple[int, List[int]]] = []
        for ancestor_index, (ancestor_prefix, _ancestor_members) in enumerate(
            working
        ):
            parsed_ancestor = urlparse(ancestor_prefix)
            if (
                parsed_ancestor.params
                or parsed_ancestor.query
                or not str(parsed_ancestor.path or "/").endswith("/")
            ):
                continue
            covered_indexes = []
            for other_index, (other_prefix, _other_members) in enumerate(working):
                parsed_other = urlparse(other_prefix)
                if (
                    parsed_other.scheme.lower() == parsed_ancestor.scheme.lower()
                    and parsed_other.netloc.lower() == parsed_ancestor.netloc.lower()
                    and str(parsed_other.path or "/").startswith(
                        str(parsed_ancestor.path or "/")
                    )
                ):
                    covered_indexes.append(other_index)
            if len(covered_indexes) > 1:
                covering_candidates.append((ancestor_index, covered_indexes))
        if covering_candidates:
            # Prefer the deepest already-planned ancestor.  It is the tightest
            # prefix that safely covers its descendants and avoids broadening a
            # mixed-depth `/vacode/` frontier to the host root.
            ancestor_index, merge_indexes = sorted(
                covering_candidates,
                key=lambda item: (
                    -len(
                        [
                            part
                            for part in urlparse(working[item[0]][0]).path.split("/")
                            if part
                        ]
                    ),
                    -len(item[1]),
                    working[item[0]][0],
                ),
            )[0]
            ancestor_prefix = working[ancestor_index][0]
            merge_set = set(merge_indexes)
            merged_members = []
            for index in merge_indexes:
                merged_members.extend(working[index][1])
            working = [
                group for index, group in enumerate(working) if index not in merge_set
            ]
            working.append(
                (ancestor_prefix, list(dict.fromkeys(merged_members)))
            )
            working.sort(key=lambda item: item[0])
            continue
        sibling_buckets: Dict[tuple[str, str, str], List[int]] = {}
        broadened_prefixes: Dict[int, str] = {}
        for index, (prefix, members) in enumerate(working):
            parsed_members = [urlparse(member) for member in members]
            if any(parsed.params or parsed.query for parsed in parsed_members):
                continue
            parsed_prefix = urlparse(prefix)
            origin = (
                parsed_prefix.scheme.lower(),
                parsed_prefix.netloc.lower(),
            )
            if any(
                (parsed.scheme.lower(), parsed.netloc.lower()) != origin
                for parsed in parsed_members
            ):
                continue
            prefix_path = parsed_prefix.path or "/"
            common_directory = (
                prefix_path.rstrip("/")
                if prefix_path.endswith("/")
                else posixpath.dirname(prefix_path)
            ) or "/"
            parent_directory = (
                posixpath.dirname(common_directory.rstrip("/")) or "/"
            )
            if not parent_directory.endswith("/"):
                parent_directory += "/"
            scheme, netloc = origin
            broadened_prefixes[index] = urlunparse(
                (scheme, netloc, parent_directory, "", "", "")
            )
            sibling_buckets.setdefault(
                (scheme, netloc, parent_directory),
                [],
            ).append(index)

        candidates = [
            (key, indexes)
            for key, indexes in sibling_buckets.items()
            if len(indexes) > 1
        ]
        if not candidates:
            made_progress = False
            broadened_working: List[tuple[str, List[str]]] = []
            for index, (prefix, members) in enumerate(working):
                broader = broadened_prefixes.get(index, prefix)
                made_progress = made_progress or broader != prefix
                broadened_working.append((broader, members))
            if not made_progress:
                break
            working = broadened_working
            working.sort(key=lambda item: item[0])
            continue
        # Merge the deepest siblings first.  For equal depth, prefer the
        # largest reduction and then lexical order for deterministic plans.
        (scheme, netloc, parent_directory), merge_indexes = sorted(
            candidates,
            key=lambda item: (
                -len([part for part in item[0][2].split("/") if part]),
                -len(item[1]),
                item[0],
            ),
        )[0]
        merged_members: List[str] = []
        merge_set = set(merge_indexes)
        for index in merge_indexes:
            merged_members.extend(working[index][1])
        merged_prefix = urlunparse(
            (scheme, netloc, parent_directory, "", "", "")
        )
        working = [
            group for index, group in enumerate(working) if index not in merge_set
        ]
        working.append((merged_prefix, list(dict.fromkeys(merged_members))))
        working.sort(key=lambda item: item[0])
    return working


def _wayback_exact_original_filter(
    urls: Sequence[str],
) -> tuple[str, int]:
    """Return one Java/Python-compatible exact-original alternation.

    Wayback's CDX server applies ``filter=original:<regex>`` before ``limit``.
    Each target admits only its exact spelling and the one terminal-slash
    variant already tolerated by replay identity checks.  The resulting row
    universe is therefore bounded by two collapsed URL keys per target.  The
    inventory query sorts captures in reverse chronological order before that
    collapse so the retained row for each URL key is its latest HTTP-200
    capture rather than its earliest.
    """

    variants: List[str] = []
    for url in dict.fromkeys(urls):
        for variant in _exact_original_spellings(url):
            if variant and variant not in variants:
                variants.append(variant)
    if not variants:
        raise ValueError("Wayback exact-original filter requires at least one URL")
    expression = "^(?:" + "|".join(re.escape(value) for value in variants) + ")$"
    return f"original:{expression}", len(variants)


def _wayback_inventory_query_url(
    prefix: str,
    *,
    limit: int,
    exact_originals: Sequence[str],
) -> tuple[str, int]:
    unique_originals = list(dict.fromkeys(exact_originals))
    logical_identities = {
        exact_http_locator_identity(original) for original in unique_originals
    }
    if len(logical_identities) > _WAYBACK_CDX_MAX_EXACT_TARGETS_PER_QUERY:
        raise ValueError(
            "Wayback exact-target inventory query exceeds the proven target "
            f"bound: targets={len(logical_identities)} "
            f"max={_WAYBACK_CDX_MAX_EXACT_TARGETS_PER_QUERY}"
        )
    exact_filter, variant_count = _wayback_exact_original_filter(unique_originals)
    params: List[tuple[str, str]] = [
        ("url", prefix),
        ("matchType", "prefix"),
        ("output", "json"),
        (
            "fl",
            "urlkey,timestamp,original,mimetype,statuscode,digest,length",
        ),
        ("filter", "statuscode:200"),
        ("filter", exact_filter),
        ("sort", "reverse"),
        ("collapse", "urlkey"),
        ("limit", str(limit)),
    ]
    query_url = "https://web.archive.org/cdx/search/cdx?" + urlencode(
        params,
        doseq=True,
        safe=":/",
    )
    query_url_bytes = len(query_url.encode("ascii"))
    if query_url_bytes > _WAYBACK_CDX_MAX_QUERY_URL_BYTES:
        raise ValueError(
            "Wayback exact-target inventory query exceeds the bounded request "
            f"length: bytes={query_url_bytes} "
            f"max={_WAYBACK_CDX_MAX_QUERY_URL_BYTES}"
        )
    return query_url, variant_count


def _valid_capture_timestamp(value: object) -> str:
    raw_timestamp = str(value or "")
    timestamp = raw_timestamp.strip()
    if timestamp != raw_timestamp:
        return ""
    if not _WAYBACK_CAPTURE_TIMESTAMP_RE.fullmatch(timestamp):
        return ""
    try:
        datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return ""
    return timestamp


def wayback_identity_replay_url(
    url: str,
    *,
    timestamp: Optional[str] = None,
) -> str:
    """Build an Internet Archive identity replay URL.

    pywb's ``id_`` modifier returns the original response body without the
    HTML/CSS rewriting used for browser playback.  A timestamp keeps strict
    callers bound to one CDX-selected capture; omitting it requests the latest
    available raw capture.
    """

    original_url = parse_exact_http_locator(url).raw
    if timestamp is None:
        replay_key = "id_"
    else:
        capture_timestamp = _valid_capture_timestamp(timestamp)
        if not capture_timestamp:
            raise ValueError(
                "Wayback identity replay requires a real fourteen-digit timestamp"
            )
        replay_key = f"{capture_timestamp}id_"
    return f"https://web.archive.org/web/{replay_key}/{original_url}"


async def fetch_wayback_capture_inventory(
    urls: Sequence[str],
    *,
    timeout_seconds: int = 30,
    max_queries: int = 128,
    max_queries_per_origin: Optional[int] = None,
    max_results_per_query: int = 5000,
    result_multiplier: int = 8,
    query_attempts: int = 2,
    retry_delay_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Discover exact Wayback captures for a multi-page frontier.

    The frontier is reduced to tight same-origin prefix groups.  The optional
    per-origin bound limits those logical groups; mandatory physical chunks
    added for the independently proven target/request-byte bounds remain
    visible in separate stats.  Every chunk is server-filtered to its escaped
    exact originals before the result limit is applied.  Partitioning is
    deterministic and stays proportional to encoded bytes rather than falling
    back to one CDX request per page.  Returned captures are exact-URL,
    HTTP-200, real-timestamp matches only, regardless of the MIME label
    reported by CDX.  The exact replay body remains subject to the caller's
    content validator before parser-input retention.  Callers can therefore
    recover HTML, XML, PDF, or mislabeled captures without issuing a second
    CDX request per page or admitting a wrong body.
    """

    if isinstance(max_queries, bool) or int(max_queries) <= 0:
        raise ValueError("max_queries must be positive")
    if max_queries_per_origin is not None and (
        isinstance(max_queries_per_origin, bool)
        or int(max_queries_per_origin) <= 0
    ):
        raise ValueError("max_queries_per_origin must be positive or None")
    if isinstance(max_results_per_query, bool) or int(max_results_per_query) <= 0:
        raise ValueError("max_results_per_query must be positive")
    if isinstance(result_multiplier, bool) or int(result_multiplier) <= 0:
        raise ValueError("result_multiplier must be positive")
    if isinstance(query_attempts, bool) or not 1 <= int(query_attempts) <= 3:
        raise ValueError("query_attempts must be between one and three")
    if isinstance(retry_delay_seconds, bool) or float(retry_delay_seconds) < 0:
        raise ValueError("retry_delay_seconds must be non-negative")
    timeout = max(1, int(timeout_seconds or 30))
    requested = [_exact_wayback_inventory_url(url) for url in urls]
    aliases_by_identity: Dict[
        tuple[str, str, str, bool, str],
        List[str],
    ] = {}
    unique_by_identity: Dict[tuple[str, str, str, bool, str], str] = {}
    for requested_url in requested:
        identity = exact_http_locator_identity(requested_url)
        aliases_by_identity.setdefault(identity, [])
        if requested_url not in aliases_by_identity[identity]:
            aliases_by_identity[identity].append(requested_url)
        unique_by_identity.setdefault(identity, requested_url)
    unique_urls = list(unique_by_identity.values())
    if not unique_urls:
        return {
            "status": "success",
            "captures_by_url": {},
            "receipts": [],
            "errors": [],
            "stats": {
                "requested_pages": 0,
                "unique_pages": 0,
                "prefix_groups_planned": 0,
                "prefix_queries_planned": 0,
                "prefix_queries_attempted": 0,
                "prefix_queries_succeeded": 0,
                "prefix_queries_failed": 0,
                "cdx_requests": 0,
                "cdx_retries": 0,
                "matched_pages": 0,
                "unmatched_pages": 0,
            },
        }

    raw_groups = _wayback_inventory_groups(unique_urls)
    if max_queries_per_origin is None:
        groups = _coalesce_wayback_inventory_groups(
            raw_groups,
            max_queries=int(max_queries),
        )
    else:
        groups_by_origin: Dict[tuple[str, str], List[tuple[str, List[str]]]] = {}
        for prefix, members in raw_groups:
            parsed_prefix = urlparse(prefix)
            origin = (
                parsed_prefix.scheme.lower(),
                parsed_prefix.netloc.lower(),
            )
            groups_by_origin.setdefault(origin, []).append((prefix, members))
        groups = []
        for origin in sorted(groups_by_origin):
            groups.extend(
                _coalesce_wayback_inventory_groups(
                    groups_by_origin[origin],
                    max_queries=int(max_queries_per_origin),
                )
            )
        groups.sort(key=lambda item: item[0])
    if len(groups) > int(max_queries):
        raise ValueError(
            "Wayback inventory requires more prefix queries than the configured "
            f"bound: planned={len(groups)} max_queries={int(max_queries)}"
        )

    def _build_query_plan(
        prefix: str,
        members: Sequence[str],
    ) -> tuple[str, List[str], int, str, int]:
        exact_members = list(members)
        submitted_spellings: List[str] = []
        for member in exact_members:
            identity = exact_http_locator_identity(member)
            for alias in aliases_by_identity.get(identity, [member]):
                if alias not in submitted_spellings:
                    submitted_spellings.append(alias)
        query_limit = min(
            int(max_results_per_query),
            max(100, len(exact_members) * max(2, int(result_multiplier))),
        )
        query_url, exact_variant_count = _wayback_inventory_query_url(
            prefix,
            limit=query_limit,
            exact_originals=submitted_spellings,
        )
        if query_limit < exact_variant_count:
            raise ValueError(
                "Wayback exact-target inventory cannot prove non-truncation: "
                f"limit={query_limit} variants={exact_variant_count}"
            )
        return (
            prefix,
            exact_members,
            query_limit,
            query_url,
            exact_variant_count,
        )

    logical_groups_by_origin: Dict[str, int] = {}
    for prefix, _members in groups:
        parsed_prefix = urlparse(prefix)
        origin = urlunparse(
            (
                parsed_prefix.scheme.lower(),
                parsed_prefix.netloc.lower(),
                "",
                "",
                "",
                "",
            )
        )
        logical_groups_by_origin[origin] = (
            logical_groups_by_origin.get(origin, 0) + 1
        )

    query_plans: List[tuple[str, List[str], int, str, int]] = []
    for prefix, members in groups:
        ordered_members = sorted(dict.fromkeys(members))
        current_members: List[str] = []
        current_plan: tuple[str, List[str], int, str, int] | None = None
        for member in ordered_members:
            candidate_members = [*current_members, member]
            try:
                candidate_plan = _build_query_plan(prefix, candidate_members)
            except ValueError:
                if not current_members or current_plan is None:
                    # A single exact locator that cannot fit cannot be safely
                    # subdivided.  Fail before issuing any inventory request.
                    raise
                query_plans.append(current_plan)
                current_members = [member]
                current_plan = _build_query_plan(prefix, current_members)
            else:
                current_members = candidate_members
                current_plan = candidate_plan
        if current_plan is not None:
            query_plans.append(current_plan)

    query_plans_by_origin: Dict[str, int] = {}
    for prefix, _members, _limit, _query_url, _variants in query_plans:
        parsed_prefix = urlparse(prefix)
        origin = urlunparse(
            (
                parsed_prefix.scheme.lower(),
                parsed_prefix.netloc.lower(),
                "",
                "",
                "",
                "",
            )
        )
        query_plans_by_origin[origin] = query_plans_by_origin.get(origin, 0) + 1

    captures_by_url: Dict[str, Dict[str, Any]] = {}
    receipts: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    successful_queries = 0
    inventory_rows = 0
    eligible_rows = 0
    cdx_requests = 0
    cdx_retries = 0

    max_query_url_bytes = 0
    exact_filter_variants = 0

    for prefix, members, query_limit, query_url, exact_variant_count in query_plans:
        max_query_url_bytes = max(max_query_url_bytes, len(query_url.encode("ascii")))
        exact_filter_variants += exact_variant_count
        outcome: Mapping[str, Any] = {}
        for attempt_index in range(int(query_attempts)):
            cdx_requests += 1
            observed = await fetch_wayback_cdx_rows(
                query_url,
                timeout_seconds=timeout,
            )
            outcome = observed if isinstance(observed, Mapping) else {}
            if outcome.get("status") == "success":
                break
            try:
                response_status = int(outcome.get("response_status") or 0)
            except (TypeError, ValueError):
                response_status = 0
            error_text = str(outcome.get("error") or "").lower()
            transient = response_status in {408, 425, 429, 500, 502, 503, 504} or any(
                token in error_text
                for token in (
                    "connection refused",
                    "max retries exceeded",
                    "timed out",
                    "timeout",
                    "temporarily unavailable",
                )
            )
            if not transient or attempt_index + 1 >= int(query_attempts):
                break
            cdx_retries += 1
            delay = min(
                5.0,
                float(retry_delay_seconds) * (2**attempt_index),
            )
            retry_after = str(outcome.get("retry_after") or "").strip()
            try:
                delay = max(delay, min(5.0, float(retry_after)))
            except (TypeError, ValueError):
                pass
            if delay > 0:
                await asyncio.sleep(delay)
        if not isinstance(outcome, Mapping) or outcome.get("status") != "success":
            errors.append(
                {
                    "prefix": prefix,
                    "error": str(
                        outcome.get("error")
                        if isinstance(outcome, Mapping)
                        else "invalid Wayback inventory response"
                    ),
                }
            )
            continue
        receipt = outcome.get("receipt")
        if isinstance(receipt, Mapping) and receipt:
            retained_receipt = dict(receipt)
            retained_receipt["query_prefix"] = prefix
            retained_receipt["query_target_count"] = len(members)
            receipts.append(retained_receipt)

        target_lookup = {
            exact_http_locator_identity(member): member for member in members
        }
        results = outcome.get("results")
        if not isinstance(results, list):
            results = []
        inventory_rows += len(results)
        unexpected_originals: List[str] = []
        if len(results) > exact_variant_count:
            errors.append(
                {
                    "prefix": prefix,
                    "error": (
                        "Wayback exact-target response exceeded its proven row "
                        f"universe: rows={len(results)} "
                        f"variants={exact_variant_count}"
                    ),
                }
            )
            continue
        for raw_capture in results:
            if not isinstance(raw_capture, Mapping):
                continue
            original_url = str(
                raw_capture.get("original_url") or raw_capture.get("original") or ""
            ).strip()
            try:
                original_identity = exact_http_locator_identity(original_url)
            except ValueError:
                unexpected_originals.append(original_url)
                continue
            if original_identity not in target_lookup:
                unexpected_originals.append(original_url)
        if unexpected_originals:
            errors.append(
                {
                    "prefix": prefix,
                    "error": (
                        "Wayback CDX response violated the exact-original server "
                        f"filter: unexpected_rows={len(unexpected_originals)}"
                    ),
                }
            )
            continue
        successful_queries += 1
        candidates: Dict[str, List[Dict[str, Any]]] = {}
        for raw_capture in results:
            if not isinstance(raw_capture, Mapping):
                continue
            capture = dict(raw_capture)
            original_url = str(
                capture.get("original_url") or capture.get("original") or ""
            ).strip()
            try:
                original_identity = exact_http_locator_identity(original_url)
            except ValueError:
                continue
            official_url = target_lookup.get(original_identity)
            if official_url is None or not _same_exact_wayback_original(
                original_url,
                official_url,
            ):
                continue
            try:
                status_code = int(
                    capture.get("statuscode") or capture.get("status_code") or 0
                )
            except (TypeError, ValueError):
                continue
            timestamp = _valid_capture_timestamp(capture.get("timestamp"))
            if status_code != 200 or not timestamp:
                continue
            capture["original_url"] = official_url
            capture["timestamp"] = timestamp
            capture["status_code"] = status_code
            capture["wayback_url"] = wayback_identity_replay_url(
                official_url,
                timestamp=timestamp,
            )
            capture["wayback_cdx_query_url"] = query_url
            if isinstance(receipt, Mapping):
                capture["wayback_cdx_response_sha256"] = str(
                    receipt.get("response_sha256") or ""
                ).strip()
                capture["wayback_cdx_fetched_at"] = str(
                    receipt.get("fetched_at") or ""
                ).strip()
            candidates.setdefault(official_url, []).append(capture)
            eligible_rows += 1

        for official_url, matched in candidates.items():
            matched.sort(key=lambda item: str(item["timestamp"]), reverse=True)
            selected = matched[0]
            identity = exact_http_locator_identity(official_url)
            for alias in aliases_by_identity.get(identity, [official_url]):
                alias_capture = dict(selected)
                alias_capture["original_url"] = alias
                alias_capture["wayback_url"] = wayback_identity_replay_url(
                    alias,
                    timestamp=str(selected["timestamp"]),
                )
                captures_by_url[alias] = alias_capture

    failed_queries = len(query_plans) - successful_queries
    if successful_queries == len(query_plans):
        status = "success"
    elif successful_queries:
        status = "partial"
    else:
        status = "error"
    return {
        "status": status,
        "captures_by_url": captures_by_url,
        "receipts": receipts,
        "errors": errors,
        "stats": {
            "requested_pages": len(requested),
            "unique_pages": len(unique_urls),
            "duplicate_page_requests_avoided": len(requested) - len(unique_urls),
            "prefix_groups_planned": len(groups),
            "prefix_queries_planned": len(query_plans),
            "prefix_queries_attempted": len(query_plans),
            "prefix_queries_succeeded": successful_queries,
            "prefix_queries_failed": failed_queries,
            "cdx_requests": cdx_requests,
            "cdx_retries": cdx_retries,
            "inventory_rows": inventory_rows,
            "eligible_capture_rows": eligible_rows,
            "matched_pages": sum(
                identity in {
                    exact_http_locator_identity(url) for url in captures_by_url
                }
                for identity in aliases_by_identity
            ),
            "matched_requested_aliases": len(captures_by_url),
            "unmatched_pages": sum(
                identity not in {
                    exact_http_locator_identity(url) for url in captures_by_url
                }
                for identity in aliases_by_identity
            ),
            "max_queries": int(max_queries),
            "max_queries_per_origin": (
                int(max_queries_per_origin)
                if max_queries_per_origin is not None
                else None
            ),
            "logical_prefix_groups_by_origin": dict(logical_groups_by_origin),
            "exact_filter_batches_by_origin": dict(query_plans_by_origin),
            "max_results_per_query": int(max_results_per_query),
            "server_side_exact_original_filter": True,
            "server_side_mimetype_filter": False,
            "server_side_latest_capture_order": "reverse",
            "server_side_collapse": "urlkey",
            "exact_original_filter_variants": exact_filter_variants,
            "exact_filter_query_batches": len(query_plans),
            "exact_filter_batches_added": len(query_plans) - len(groups),
            "max_query_url_bytes": max_query_url_bytes,
            "query_url_byte_bound": _WAYBACK_CDX_MAX_QUERY_URL_BYTES,
            "query_target_bound": _WAYBACK_CDX_MAX_EXACT_TARGETS_PER_QUERY,
            "exact_filter_non_truncation_proved": True,
        },
    }


async def search_wayback_machine(
    url: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    collapse: Optional[str] = None,
    output_format: Literal["json", "cdx"] = "json",
) -> Dict[str, Any]:
    """Search Wayback Machine for captures of a URL.

    Args:
        url: URL to search for
        from_date: Start date (YYYYMMDD format)
        to_date: End date (YYYYMMDD format)
        limit: Maximum number of results
        collapse: Field to collapse on (e.g., 'timestamp:8' for daily snapshots)
        output_format: Output format - "json" or "cdx"

    Returns:
        Dict containing captures list and metadata
    """
    # Keep discovery on the shared strict transport path.  A third-party
    # client can otherwise follow redirects without exposing the final CDX
    # locator, preventing callers from proving which inventory was queried.
    return await _search_wayback_direct_api(
        url, from_date, to_date, limit, collapse, output_format
    )


async def _search_wayback_direct_api(
    url: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    collapse: Optional[str] = None,
    output_format: Literal["json", "cdx"] = "json",
) -> Dict[str, Any]:
    """Direct API search fallback for Wayback Machine."""
    try:
        official_url = parse_exact_http_locator(url).raw
        params: List[tuple[str, str]] = [
            ("url", official_url),
            ("output", "json"),
            ("limit", str(limit)),
        ]
        if from_date:
            params.append(("from", str(from_date)))
        if to_date:
            params.append(("to", str(to_date)))
        if collapse:
            params.append(("collapse", str(collapse)))
        cdx_url = "https://web.archive.org/cdx/search/cdx?" + urlencode(
            params,
            doseq=True,
            safe=":/",
        )
        outcome = await fetch_wayback_cdx_rows(cdx_url, timeout_seconds=30)
        if outcome.get("status") != "success":
            return dict(outcome)
        if output_format == "json":
            results = list(outcome.get("results") or [])
        else:
            rows = list(outcome.get("rows") or [])
            headers = rows[0] if rows else []
            results = [dict(zip(headers, record)) for record in rows[1:]]
        return {
            "status": "success",
            "results": results,
            "url": official_url,
            "count": len(results),
            "receipt": outcome.get("receipt"),
        }
    except Exception as e:
        logger.error(f"Direct Wayback API search failed for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def get_wayback_content(
    url: str,
    timestamp: Optional[str] = None,
    closest: bool = True,
) -> Dict[str, Any]:
    """Get original, unrewritten content from Wayback for a specific URL.

    Args:
        url: URL to retrieve
        timestamp: Specific timestamp (YYYYMMDDHHMMSS format), or None for latest
        closest: If True, get closest capture to timestamp

    Returns:
        Dict containing content and metadata
    """
    try:
        official_url = parse_exact_http_locator(url).raw
        if not closest:
            return await _get_wayback_content_direct(
                official_url,
                timestamp,
                closest=False,
            )
        try:
            from wayback import Mode, WaybackClient
        except ImportError:
            return await _get_wayback_content_direct(url, timestamp, closest)

        client = WaybackClient()
        target_date = (
            datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
            if timestamp
            else datetime.now(timezone.utc)
        )

        try:
            capture = client.get_memento(
                official_url,
                timestamp=target_date,
                mode=Mode.original,
                exact=not closest,
            )
            try:
                response_status = int(getattr(capture, "status_code", 0) or 0)
            except (TypeError, ValueError):
                response_status = 0
            if response_status != 200:
                return {
                    "status": "error",
                    "error": (
                        "Wayback capture did not have exact HTTP 200 status: "
                        f"{response_status or '<missing>'}"
                    ),
                    "response_status": response_status,
                }
            capture_timestamp = capture.timestamp.strftime("%Y%m%d%H%M%S")
            capture_url = str(
                getattr(capture, "memento_url", "")
                or getattr(capture, "archive_url", "")
            ).strip()
            try:
                final_locator = parse_wayback_archive_url(
                    capture_url,
                    allowed_modifiers=("id_",),
                    require_identity_modifier=True,
                )
            except ValueError:
                return {
                    "status": "error",
                    "error": "Wayback client did not return identity replay",
                    "response_status": response_status,
                }
            if (
                final_locator.timestamp != capture_timestamp
                or not same_exact_http_locator(
                    final_locator.original_url,
                    official_url,
                )
            ):
                return {
                    "status": "error",
                    "error": "Wayback client replay identity drifted",
                    "response_status": response_status,
                }
            capture_headers = getattr(capture, "headers", {})
            content_type = ""
            if isinstance(capture_headers, Mapping):
                content_type = str(
                    capture_headers.get("content-type")
                    or capture_headers.get("Content-Type")
                    or ""
                )
            content_type = str(
                getattr(capture, "mime_type", "") or content_type
            )
            original_url = str(
                getattr(capture, "url", "")
                or getattr(capture, "original_url", "")
                or ""
            )
            if not same_exact_http_locator(original_url, official_url):
                return {
                    "status": "error",
                    "error": "Wayback client original locator drifted",
                    "response_status": response_status,
                }
            return {
                "status": "success",
                "content": capture.content,
                "content_type": content_type,
                "wayback_url": capture_url,
                "capture_timestamp": capture_timestamp,
                "original_url": original_url,
                "response_status": response_status,
                "replay_modifier": "id_",
            }
        except Exception as capture_error:
            logger.error(f"Failed to get capture: {capture_error}")
            return {"status": "error", "error": f"No capture found for {official_url}: {capture_error}"}
    except Exception as e:
        logger.error(f"Failed to get Wayback content for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def _get_wayback_content_direct(
    url: str,
    timestamp: Optional[str] = None,
    closest: bool = True,
) -> Dict[str, Any]:
    """Direct content retrieval fallback."""
    try:
        import requests

        wayback_url = wayback_identity_replay_url(
            url,
            timestamp=timestamp,
        )
        response = requests.get(
            wayback_url,
            timeout=30,
            allow_redirects=False,
        )
        response_status = int(getattr(response, "status_code", 0) or 0)
        if response_status != 200:
            return {
                "status": "error",
                "error": (
                    "Wayback replay did not have exact HTTP 200 status: "
                    f"{response_status}"
                ),
                "response_status": response_status,
            }

        response_url = str(getattr(response, "url", "") or "").strip()
        try:
            final_locator = parse_wayback_archive_url(
                response_url,
                allowed_modifiers=("id_",),
                require_identity_modifier=True,
            )
        except ValueError:
            return {
                "status": "error",
                "error": "Wayback replay did not return a canonical final identity locator",
                "response_status": response_status,
            }
        official_url = parse_exact_http_locator(url).raw
        expected_timestamp = _valid_capture_timestamp(timestamp) if timestamp else ""
        if expected_timestamp and final_locator.timestamp != expected_timestamp:
            return {
                "status": "error",
                "error": "Wayback replay timestamp drifted from the exact request",
                "response_status": response_status,
            }
        if not same_exact_http_locator(final_locator.original_url, official_url):
            return {
                "status": "error",
                "error": "Wayback replay original locator drifted from the exact request",
                "response_status": response_status,
            }

        return {
            "status": "success",
            "content": response.content,
            "content_type": response.headers.get("content-type", "text/html"),
            "wayback_url": response_url,
            "capture_timestamp": final_locator.timestamp,
            "original_url": final_locator.original_url,
            "response_status": response_status,
            "replay_modifier": "id_",
        }
    except Exception as e:
        logger.error(f"Direct Wayback content retrieval failed for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def archive_to_wayback(url: str) -> Dict[str, Any]:
    """Archive a URL to Wayback Machine.

    Args:
        url: URL to archive

    Returns:
        Dict containing archived_url, job_id and metadata
    """
    try:
        try:
            import internetarchive as ia  # noqa: F401
        except ImportError:
            return await _archive_to_wayback_direct(url)

        archive_url = f"https://web.archive.org/save/{url}"
        return {
            "status": "success",
            "archived_url": archive_url,
            "message": f"Submitted {url} for archiving to Wayback Machine",
        }
    except Exception as e:
        logger.error(f"Failed to archive {url} to Wayback Machine: {e}")
        return {"status": "error", "error": str(e)}


async def _archive_to_wayback_direct(url: str) -> Dict[str, Any]:
    """Direct archive submission fallback."""
    try:
        import requests

        save_url = f"https://web.archive.org/save/{url}"
        response = requests.get(save_url, timeout=60)
        response.raise_for_status()
        return {
            "status": "success",
            "archived_url": save_url,
            "message": f"Successfully submitted {url} for archiving",
        }
    except Exception as e:
        logger.error(f"Direct archive submission failed for {url}: {e}")
        return {"status": "error", "error": str(e)}

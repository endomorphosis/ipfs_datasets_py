"""Bounded pages of exact source-replayed, unresolved numerical obligations.

The native report owns the rows and their interpretations. A continuation is
a deterministic selection within one report and query, never authorization or
proof. Source bytes and projection bodies are deliberately absent from pages.
"""
from __future__ import annotations

import hashlib
import json

from . import numerical_logic

PAGE_SCHEMA = "numerical-obligation-page@1"
CURSOR_SCHEMA = "numerical-obligation-cursor@1"
MAX_PAGE_BYTES = 65_536
MAX_LIMIT = numerical_logic.MAX_OBLIGATIONS
_AUTHORITY = dict(proof_authority=False, formalization_authority=False,
    completion_authority=False, execution_authority=False,
    source_semantics_verified=False, whole_program_semantics_verified=False,
    source_obligations_discharged=0, source_executed=False,
    model_inference_calls=0, provider_calls=0, solver_calls=0)


class NumericalObligationRetrievalError(ValueError):
    """An invalid, stale, foreign or undersized numerical page request."""


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise NumericalObligationRetrievalError("inert numerical page JSON required") from exc


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _filter(value, name):
    if value is not None and (type(value) is not str or not value
                              or len(value.encode("utf-8")) > 512):
        raise NumericalObligationRetrievalError("bounded exact " + name + " filter required")
    return value


def page_numerical_obligations(*, report, source_text, path, cursor=None,
                               function_id=None, kind=None, limit=8, max_bytes=8192):
    """Return whole pending rows after exact source/report replay.

    Rows retain native order. Exact filters may match no rows; ``total_count``
    still describes the unfiltered report. ``offset`` and ``remaining_count``
    account for matched rows outside this page. A changed source, report,
    filter, limit or byte budget invalidates old cursors. Cursor offsets must
    be reachable by repeatedly paging the same immutable query from zero.

    ``binding.report_id`` is the native report's self identity, whereas
    ``binding.report_sha256`` hashes its complete canonical UTF-8 JSON. A
    filesystem owner's different JSON serialization can have another hash.
    The byte bound covers this entire page, including its next cursor and
    authority fields. An envelope or first row that cannot fit is refused;
    neither partial rows nor non-progressing continuations are returned.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise NumericalObligationRetrievalError("bounded positive integer limit required")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_PAGE_BYTES:
        raise NumericalObligationRetrievalError("bounded positive integer max_bytes required")
    function_id = _filter(function_id, "function_id")
    kind = _filter(kind, "kind")
    if type(path) is not str or not path or len(path.encode("utf-8")) > 4096:
        raise NumericalObligationRetrievalError("bounded exact report path required")
    if type(source_text) is not str:
        raise NumericalObligationRetrievalError("exact source text required")
    try:
        owner = numerical_logic
        if (type(report) is dict and report.get("profile") == "python-numerical-guarded-structure@2"
                and report.get("schema") == "numerical-source-logic/v2"):
            from . import numerical_logic_v2
            owner = numerical_logic_v2
        native = owner.validate_numerical_logic_report(report, source_text, path=path)
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise NumericalObligationRetrievalError("numerical report failed exact source replay") from exc
    binding = dict(path=path, source_sha256=native["source_sha256"],
                   report_id=native["report_sha256"], report_sha256=_digest(native))
    query = dict(function_id=function_id, kind=kind, limit=limit, max_bytes=max_bytes)
    request_sha256 = _digest(dict(schema=PAGE_SCHEMA, binding=binding, query=query))
    all_rows = native["pending_obligations"]
    rows = [row for row in all_rows
            if (function_id is None or function_id in row["function_ids"])
            and (kind is None or row["kind"] == kind)]

    def continuation(offset):
        return dict(schema=CURSOR_SCHEMA, request_sha256=request_sha256, offset=offset)

    def render(start, stop):
        exhausted = stop == len(rows)
        return dict(schema=PAGE_SCHEMA, binding=binding, query=query,
            request_sha256=request_sha256, total_count=len(all_rows),
            matched_count=len(rows), filtered_out_count=len(all_rows) - len(rows),
            offset=start, returned_count=stop - start, remaining_count=len(rows) - stop,
            rows=rows[start:stop], next_cursor=None if exhausted else continuation(stop),
            exhausted=exhausted, status="exhausted" if exhausted else "more_available",
            **_AUTHORITY)

    def build(start):
        if not rows:
            page = render(0, 0)
            if len(_wire(page)) > max_bytes:
                raise NumericalObligationRetrievalError("page envelope exceeds byte bound")
            return page
        chosen = None
        # Last-page cursor removal can make a longer page smaller. Inspect all
        # allowed ends rather than assuming serialized size is monotonic.
        for stop in range(start + 1, min(len(rows), start + limit) + 1):
            candidate = render(start, stop)
            if len(_wire(candidate)) <= max_bytes:
                chosen = candidate
        if chosen is None:
            raise NumericalObligationRetrievalError("one complete obligation row cannot fit byte bound")
        return chosen

    offset = 0
    if cursor is not None:
        if (type(cursor) is not dict
                or set(cursor) != {"schema", "request_sha256", "offset"}
                or type(cursor["schema"]) is not str or cursor["schema"] != CURSOR_SCHEMA
                or type(cursor["request_sha256"]) is not str
                or cursor["request_sha256"] != request_sha256
                or type(cursor["offset"]) is not int
                or not 0 < cursor["offset"] < len(rows)):
            raise NumericalObligationRetrievalError("stale, foreign or malformed numerical cursor")
        target = cursor["offset"]
        while offset < target:
            prior = build(offset)
            offset += prior["returned_count"]
        if offset != target:
            raise NumericalObligationRetrievalError("cursor is not a deterministic page boundary")
    return build(offset)


__all__ = ["PAGE_SCHEMA", "CURSOR_SCHEMA", "MAX_PAGE_BYTES",
           "NumericalObligationRetrievalError", "page_numerical_obligations"]

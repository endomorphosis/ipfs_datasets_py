"""Exact unresolved-row pagination; no model, solver or target execution."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as logic
from ipfs_datasets_py.logic.software_verification import numerical_obligation_retrieval as pages


SOURCE = '''import numpy as np
def selected_pair(matrix):
    values, vectors = np.linalg.eig(matrix)
    chosen = np.argmax(values.real)
    return values[chosen], vectors[:, chosen]

def selection(values):
    return np.argmin(values)
'''


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


@pytest.fixture(scope="module")
def native():
    return logic.formalize_numerical_source(SOURCE, path="authored.py")


def page(native, **kwargs):
    return pages.page_numerical_obligations(report=native, source_text=SOURCE,
        path="authored.py", **kwargs)


def test_all_pages_retain_complete_rows_in_order_with_exact_counts(native):
    cursor = None
    collected = []
    while True:
        value = page(native, cursor=cursor, limit=3)
        assert value["schema"] == pages.PAGE_SCHEMA
        assert value["offset"] == len(collected)
        assert value["returned_count"] == len(value["rows"])
        assert value["total_count"] == value["matched_count"] == len(native["pending_obligations"])
        assert value["filtered_out_count"] == 0
        assert len(wire(value)) <= 8192
        collected.extend(value["rows"])
        assert len(collected) + value["remaining_count"] == value["matched_count"]
        assert value["source_obligations_discharged"] == value["provider_calls"] == value["solver_calls"] == 0
        for key in ("proof_authority", "formalization_authority", "execution_authority",
                    "completion_authority", "source_semantics_verified", "source_executed"):
            assert value[key] is False
        assert "projections" not in value and SOURCE.encode() not in wire(value)
        cursor = value["next_cursor"]
        if cursor is None:
            assert value["exhausted"] is True and value["status"] == "exhausted"
            break
        assert value["exhausted"] is False and value["status"] == "more_available"
        assert cursor["offset"] == len(collected)
    assert collected == native["pending_obligations"]
    assert len({row["obligation_id"] for row in collected}) == len(collected)


def test_binding_distinguishes_native_report_id_and_full_canonical_digest(native):
    value = page(native)
    assert value["binding"] == dict(path="authored.py", source_sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
        report_id=native["report_sha256"], report_sha256=hashlib.sha256(wire(native)).hexdigest())
    assert value["query"] == dict(function_id=None, kind=None, limit=8, max_bytes=8192)


def test_byte_budget_reduces_rows_without_slicing_or_losing_continuation(native):
    cursor = None
    rows = []
    lengths = []
    while True:
        value = page(native, cursor=cursor, limit=256, max_bytes=2300)
        assert len(wire(value)) <= 2300
        lengths.append(value["returned_count"])
        rows.extend(value["rows"])
        cursor = value["next_cursor"]
        if cursor is None:
            break
    assert len(lengths) > 1 and all(count > 0 for count in lengths)
    assert rows == native["pending_obligations"]


def test_filters_keep_distinct_full_and_matched_populations(native):
    fid = native["structural"]["program"]["functions"][-1]["function_id"]
    expected = [row for row in native["pending_obligations"]
                if fid in row["function_ids"] and row["kind"] == "selection"]
    value = page(native, function_id=fid, kind="selection")
    assert value["rows"] == expected and len(expected) == 1
    assert value["matched_count"] == 1 and value["total_count"] > 1
    assert value["filtered_out_count"] == value["total_count"] - 1
    assert value["exhausted"] is True and value["next_cursor"] is None
    empty = page(native, function_id="function:not-in-this-report")
    assert empty["total_count"] == len(native["pending_obligations"])
    assert empty["rows"] == [] and empty["matched_count"] == 0 and empty["exhausted"] is True


def test_empty_native_obligation_population_is_honest_not_a_proof():
    source = "def identity(value):\n    return value\n"
    report = logic.formalize_numerical_source(source, path="empty.py")
    value = pages.page_numerical_obligations(report=report, source_text=source, path="empty.py")
    assert value["rows"] == [] and value["total_count"] == value["matched_count"] == 0
    assert value["next_cursor"] is None and value["exhausted"] is True
    assert value["source_semantics_verified"] is False
    with pytest.raises(pages.NumericalObligationRetrievalError, match="envelope"):
        pages.page_numerical_obligations(report=report, source_text=source, path="empty.py", max_bytes=1)


def test_unicode_source_path_uses_utf8_byte_budget_and_exact_source_binding():
    path = "数学/éigen.py"
    source = SOURCE.replace("selected_pair", "sélection")
    report = logic.formalize_numerical_source(source, path=path)
    value = pages.page_numerical_obligations(report=report, source_text=source, path=path,
                                            limit=2, max_bytes=4096)
    assert path.encode() in wire(value) and len(wire(value)) <= 4096
    assert value["binding"]["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert value["rows"] == report["pending_obligations"][:2]


@pytest.mark.parametrize("kwargs", [dict(limit=True), dict(limit=0), dict(limit=257), dict(limit=1.0),
    dict(max_bytes=True), dict(max_bytes=0), dict(max_bytes=65537), dict(max_bytes=8192.0),
    dict(function_id=[]), dict(function_id=""), dict(function_id="x"*513),
    dict(kind={}), dict(kind=""), dict(kind="x"*513)])
def test_invalid_limits_and_filters_refused(native, kwargs):
    with pytest.raises(pages.NumericalObligationRetrievalError):
        page(native, **kwargs)


@pytest.mark.parametrize("damage", ["boolean", "zero", "negative", "float", "end", "middle", "extra", "schema", "binding"])
def test_malformed_or_nonboundary_cursor_refused(native, damage):
    cursor = deepcopy(page(native, limit=3)["next_cursor"])
    if damage == "boolean": cursor["offset"] = True
    elif damage == "zero": cursor["offset"] = 0
    elif damage == "negative": cursor["offset"] = -1
    elif damage == "float": cursor["offset"] = 3.0
    elif damage == "end": cursor["offset"] = len(native["pending_obligations"])
    elif damage == "middle": cursor["offset"] = 1
    elif damage == "extra": cursor["authority"] = True
    elif damage == "schema": cursor["schema"] = []
    else: cursor["request_sha256"] = "0"*64
    with pytest.raises(pages.NumericalObligationRetrievalError):
        page(native, limit=3, cursor=cursor)


@pytest.mark.parametrize("change", [dict(limit=4), dict(max_bytes=8191), dict(kind="selection"),
                                    dict(function_id="function:2")])
def test_query_change_invalidates_cursor(native, change):
    cursor = page(native, limit=3)["next_cursor"]
    with pytest.raises(pages.NumericalObligationRetrievalError, match="cursor"):
        page(native, cursor=cursor, **(dict(limit=3) | change))


def test_changed_source_with_overlapping_local_ids_cannot_reuse_cursor(native):
    cursor = page(native, limit=3)["next_cursor"]
    changed = SOURCE + "\n# Same local AST identities, different captured bytes.\n"
    report = logic.formalize_numerical_source(changed, path="authored.py")
    assert report["pending_obligations"] == native["pending_obligations"]
    with pytest.raises(pages.NumericalObligationRetrievalError, match="cursor"):
        pages.page_numerical_obligations(report=report, source_text=changed,
                                        path="authored.py", limit=3, cursor=cursor)


@pytest.mark.parametrize("damage", ["authority", "status", "source", "path", "omitted_row"])
def test_rehashed_report_tamper_fails_source_replay(native, damage):
    bad = deepcopy(native)
    if damage == "authority": bad["pending_obligations"][0]["proof_authority"] = 0
    elif damage == "status": bad["pending_obligations"][0]["status"] = "proved"
    elif damage == "source": bad["source_sha256"] = "0"*64
    elif damage == "path": bad["path"] = "foreign.py"
    else: bad["pending_obligations"].pop()
    bad["report_sha256"] = hashlib.sha256(wire({k:v for k,v in bad.items() if k != "report_sha256"})).hexdigest()
    with pytest.raises(pages.NumericalObligationRetrievalError, match="source replay"):
        page(bad)


def test_foreign_path_or_source_cannot_replay_native_report(native):
    for source, path in [(SOURCE, "foreign.py"), (SOURCE+"\n", "authored.py")]:
        with pytest.raises(pages.NumericalObligationRetrievalError, match="source replay"):
            pages.page_numerical_obligations(report=native, source_text=source, path=path)


def test_too_small_complete_row_refused_instead_of_truncated_or_empty_cursor(native):
    with pytest.raises(pages.NumericalObligationRetrievalError, match="complete obligation row"):
        page(native, max_bytes=1000)


def test_returned_rows_are_detached_from_supplied_native_report(native):
    value = page(native, limit=1)
    value["rows"][0]["status"] = "corrupted by caller"
    assert native["pending_obligations"][0]["status"] == "pending"
    assert page(native, limit=1)["rows"][0]["status"] == "pending"

"""Exact unresolved-row pagination; no model, solver or target execution."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as logic
from ipfs_datasets_py.logic.software_verification import numerical_logic_v2, numerical_logic_v3
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


@pytest.fixture(scope="module", params=[logic, numerical_logic_v2, numerical_logic_v3],
                ids=["straight", "guarded", "control"])
def profile_native(request):
    source = SOURCE + "\ndef scan(items):\n    for item in items:\n        inspect(item)\n"
    return source, request.param.formalize_numerical_source(source, path="authored.py")


def selected_page(profile_native, **kwargs):
    source, report = profile_native
    return pages.page_numerical_obligations(report=report, source_text=source, path="authored.py", **kwargs)


def test_omitted_and_none_obligation_id_preserve_all_page_and_cursor_bytes(profile_native):
    cursor = None
    while True:
        omitted = selected_page(profile_native, cursor=cursor, limit=2)
        explicit_none = selected_page(profile_native, cursor=cursor, limit=2, obligation_id=None)
        assert wire(omitted) == wire(explicit_none)
        assert "obligation_id" not in omitted["query"]
        assert omitted["request_sha256"] == hashlib.sha256(wire(dict(
            schema=pages.PAGE_SCHEMA, binding=omitted["binding"], query=omitted["query"]))).hexdigest()
        cursor = omitted["next_cursor"]
        if cursor is None:
            break


def test_exact_id_selects_whole_native_rows_without_authority(profile_native):
    _, report = profile_native
    for row in report["pending_obligations"]:
        value = selected_page(profile_native, obligation_id=row["obligation_id"])
        assert value["query"]["obligation_id"] == row["obligation_id"]
        assert value["rows"] == [row]
        assert value["matched_count"] == value["returned_count"] == 1
        assert value["total_count"] == len(report["pending_obligations"])
        assert value["filtered_out_count"] == value["total_count"] - 1
        assert value["remaining_count"] == value["offset"] == 0
        assert value["next_cursor"] is None and value["exhausted"] is True
        assert all(value[key] == expected for key, expected in pages._AUTHORITY.items())
        if "proof_scope" in row:
            assert value["rows"][0]["proof_scope"] == row["proof_scope"]
            assert value["rows"][0]["evaluation_context_role"] == "source_anchor_only"


def test_exact_id_intersects_function_and_kind_filters(profile_native):
    _, report = profile_native
    row = report["pending_obligations"][0]
    query = dict(obligation_id=row["obligation_id"], function_id=row["function_ids"][0], kind=row["kind"])
    assert selected_page(profile_native, **query)["rows"] == [row]
    for changed in (dict(function_id="foreign-function"), dict(kind="foreign-kind"),
                    dict(obligation_id="foreign-obligation")):
        empty = selected_page(profile_native, **(query | changed))
        assert empty["rows"] == [] and empty["matched_count"] == 0
        assert empty["exhausted"] is True and empty["next_cursor"] is None
        assert empty["total_count"] == len(report["pending_obligations"])


def test_equal_cardinality_ids_have_distinct_query_and_cursor_bindings(profile_native):
    _, report = profile_native
    first, second = report["pending_obligations"][:2]
    left = selected_page(profile_native, obligation_id=first["obligation_id"], limit=1)
    right = selected_page(profile_native, obligation_id=second["obligation_id"], limit=1)
    assert left["matched_count"] == right["matched_count"] == 1
    assert left["request_sha256"] != right["request_sha256"]
    cursor = selected_page(profile_native, limit=1)["next_cursor"]
    with pytest.raises(pages.NumericalObligationRetrievalError, match="cursor"):
        selected_page(profile_native, obligation_id=first["obligation_id"], limit=1, cursor=cursor)
    # Exact IDs are unique, so no continuation can exist even if a caller
    # constructs one with the selected request's otherwise-correct digest.
    forged = dict(schema=pages.CURSOR_SCHEMA, request_sha256=left["request_sha256"], offset=1)
    for key in (first["obligation_id"], second["obligation_id"]):
        with pytest.raises(pages.NumericalObligationRetrievalError, match="cursor"):
            selected_page(profile_native, obligation_id=key, limit=1, cursor=forged)


class StringSubclass(str):
    pass


@pytest.mark.parametrize("value", [False, 1, 1.0, [], {}, b"id", "", "x"*513,
    "é"*257, "\ud800", "\udfff", StringSubclass("id")])
def test_malformed_exact_id_filters_have_bounded_domain_errors(native, value):
    with pytest.raises(pages.NumericalObligationRetrievalError, match="bounded exact obligation_id filter"):
        page(native, obligation_id=value)


@pytest.mark.parametrize("value", ["' OR 1=1; --", "*", "../foreign", "$(touch never)", "id\x00suffix", "é"*256])
def test_hostile_or_maximum_utf8_ids_are_inert_exact_empty_queries(native, value):
    result = page(native, obligation_id=value)
    assert result["query"]["obligation_id"] == value
    assert result["rows"] == [] and result["matched_count"] == 0
    assert result["total_count"] == len(native["pending_obligations"])
    assert all(result[key] == expected for key, expected in pages._AUTHORITY.items())


@pytest.mark.parametrize("field", ["kind", "function_id"])
def test_existing_filter_surrogates_are_normalized_to_retrieval_error(native, field):
    with pytest.raises(pages.NumericalObligationRetrievalError, match="bounded exact " + field):
        page(native, **{field: "\ud800"})


def test_selected_row_and_empty_envelope_exact_byte_bounds(native):
    for key in (native["pending_obligations"][0]["obligation_id"], "absent"):
        initial = page(native, obligation_id=key)
        budget = len(wire(initial))
        # Serializing a smaller budget can itself remove a decimal digit.
        for _ in range(4):
            exact = page(native, obligation_id=key, max_bytes=budget)
            if len(wire(exact)) == budget:
                break
            budget = len(wire(exact))
        assert len(wire(exact)) == budget and exact["rows"] == initial["rows"]
        with pytest.raises(pages.NumericalObligationRetrievalError, match="byte bound"):
            page(native, obligation_id=key, max_bytes=budget-1)


def test_nonmatching_exact_id_does_not_skip_source_replay(native):
    damaged = deepcopy(native)
    damaged["pending_obligations"][0]["status"] = "proved"
    damaged["report_sha256"] = hashlib.sha256(wire({k:v for k,v in damaged.items() if k != "report_sha256"})).hexdigest()
    with pytest.raises(pages.NumericalObligationRetrievalError, match="source replay"):
        page(damaged, obligation_id="absent")
    with pytest.raises(pages.NumericalObligationRetrievalError, match="source replay"):
        pages.page_numerical_obligations(report=native, source_text=SOURCE+"\n", path="authored.py", obligation_id="absent")


def test_selected_row_mutation_does_not_modify_native_report(native):
    row = native["pending_obligations"][0]
    result = page(native, obligation_id=row["obligation_id"])
    result["rows"][0]["status"] = "corrupted"
    assert row["status"] == "pending"
    assert page(native, obligation_id=row["obligation_id"])["rows"][0]["status"] == "pending"

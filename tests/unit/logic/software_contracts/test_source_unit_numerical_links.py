"""Authored exact whole-file joins, independent byte expectations and frontiers."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_function_units as units
from ipfs_datasets_py.logic.software_verification import numerical_logic as numerical
from ipfs_datasets_py.logic.software_contracts import source_unit_numerical_links as api


SOURCE = b'''import numpy as np
def selected(matrix):
    values, vectors = np.linalg.eig(matrix)
    chosen = np.argmax(np.abs(values))
    return values[chosen], vectors[:, chosen]

def check(matrix, value, vector):
    assert not np.allclose(vector, 0)
    assert np.allclose(matrix @ vector, value * vector)
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def prepare(source=SOURCE, path="package/fixture.py"):
    inventory = units.extract_function_units(source_bytes=source,
        source_sha256=sha(source), source_path=path)
    report = numerical.formalize_numerical_source(source.decode(), path=path)
    return inventory, report


def bind(source=SOURCE, path="package/fixture.py"):
    inventory, report = prepare(source, path)
    return api.bind_function_unit_logic(source_bytes=source, unit_inventory=inventory,
                                        numerical_report=report)


def test_exact_function_ranges_ids_counts_and_replay():
    inventory, native = prepare()
    result = api.bind_function_unit_logic(source_bytes=SOURCE, unit_inventory=inventory,
                                         numerical_report=native)
    assert result["unit_count"] == result["matched_unit_count"] == result["native_function_count"] == 2
    assert result["unmatched_unit_count"] == result["unmatched_native_function_count"] == 0
    expected_first = SOURCE[SOURCE.index(b"def selected"):SOURCE.index(b"\n\ndef check")]
    expected_second = SOURCE[SOURCE.index(b"def check"):].rstrip(b"\n")
    for link, expected in zip(result["links"], (expected_first, expected_second)):
        assert SOURCE[link["start_byte"]:link["end_byte"]] == expected
        assert link["raw_span_sha256"] == sha(expected)
        assert link["structural_status"] == "structurally_complete"
        assert link["scalar_guard_status"] == "unsupported"
        assert link["scalar_guard_reason"] == "two_distinct_parameters_required"
        assert link["source_obligations_discharged"] == 0
        assert link["span_ids"] and link["source_ref_ids"]
    assert result["compound_contract_count"] == 1
    assert result["assertion_requirement_count"] == 2
    assert result["links"][0]["compound_contract_count"] == 1
    assert result["links"][1]["assertion_requirement_count"] == 2
    assert result["pending_obligation_count"] == result["linked_pending_obligation_count"]
    assert not result["unlinked_pending_obligation_ids"]
    assert result["inventory_sha256"] == sha(wire(inventory))
    assert result["numerical_report_sha256"] == sha(wire(native))
    assert result["numerical_report_id"] == native["report_sha256"]
    assert api.validate_function_unit_logic_links(result, source_bytes=SOURCE,
        unit_inventory=inventory, numerical_report=native) == result


def test_artifact_refs_resolve_to_exact_payloads_without_copying_bodies():
    inventory, native = prepare()
    report = api.bind_function_unit_logic(source_bytes=SOURCE, unit_inventory=inventory, numerical_report=native)
    catalog = {row["artifact_id"]: row for row in report["artifacts"]}
    assert len(catalog) == len(report["artifacts"])
    assert {row["family"] for row in catalog.values()} == {"program", "first_order", "higher_order"}
    for row in catalog.values():
        value = native
        for part in row["report_pointer"].split("/")[1:]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert row["artifact_sha256"] == sha(wire(value))
        assert row["artifact_id"] == row["family"] + ":" + row["artifact_sha256"]
        if row["encoding"] == "Lean4":
            assert row["source_sha256"] == sha(value["source"].encode())
            assert row["lake_executed"] is False
    for link in report["links"]:
        assert set(link["family_artifact_ids"]) <= catalog.keys()
        for artifact_id in link["family_artifact_ids"]:
            row = catalog[artifact_id]
            if "obligation_id" in row:
                assert row["obligation_id"] in link["pending_obligation_ids"]
    output = wire(report).decode()
    assert "normalized_source_text" not in output
    assert "matrix @ vector" not in output and "np.linalg.eig" not in output
    assert "namespace" not in output and "declare-const" not in output
    assert len(output) < len(wire(native))


def test_changed_module_import_invalidates_identical_function_body_join():
    first = b"import numpy as np\ndef selected(a):\n    return np.linalg.eig(a)\n"
    second = first.replace(b"numpy", b"other")
    old_units, old_native = prepare(first)
    new_units, new_native = prepare(second)
    assert old_units["units"][0]["normalized_body_sha256"] == new_units["units"][0]["normalized_body_sha256"]
    assert old_units["units"][0]["unit_id"] != new_units["units"][0]["unit_id"]
    for inventory, native in ((old_units, old_native), (new_units, old_native), (old_units, new_native)):
        with pytest.raises(api.SourceUnitNumericalLinkError, match="exact replay"):
            api.bind_function_unit_logic(source_bytes=second, unit_inventory=inventory, numerical_report=native)
    old = bind(first)
    new = bind(second)
    assert old["import_context"]["bindings_sha256"] != new["import_context"]["bindings_sha256"]
    assert old["pending_obligation_count"] == 3 and new["pending_obligation_count"] == 1
    assert not new["import_context"]["runtime_identity_verified"]


def test_duplicate_names_join_distinct_exact_ranges_not_name_identity():
    source = b"def same(a):\n    return a[0]\n\ndef same(a):\n    return a[1]\n"
    report = bind(source)
    assert report["matched_unit_count"] == 2
    first, second = report["links"]
    assert first["unit_id"] != second["unit_id"] and first["function_id"] != second["function_id"]
    assert first["start_byte"] == 0
    assert second["start_byte"] == source.index(b"def same", 1)
    assert set(first["pending_obligation_ids"]).isdisjoint(second["pending_obligation_ids"])


def test_nested_and_class_units_never_match_a_containing_function():
    source = b'''def outer(a):
    def inner(b):
        return b[0]
    return a
class Holder:
    def method(self, x):
        return x[0]
'''
    report = bind(source)
    assert report["unit_count"] == 3 and report["matched_unit_count"] == 1
    assert report["unmatched_unit_count"] == 2
    assert report["links"][0]["structural_status"] == "partial"
    for row in report["links"][1:]:
        assert row["function_id"] is None and row["status"] == "unmatched"
        assert row["unmatched_reason"] == "no_exact_native_function_span"
        assert row["family_artifact_ids"] == row["pending_obligation_ids"] == []


@pytest.mark.parametrize("suffix", ["# café\n", "# Unicode\u2028inside a comment\n"])
def test_utf8_comments_have_independent_raw_byte_ranges(suffix):
    source = (suffix + "import numpy as np\ndef f(a):\n    # naïve\n    return a[0] # façade\n").encode()
    link, = bind(source)["links"]
    start = source.index(b"def f")
    end = source.index(b" # fa")
    assert (link["start_byte"], link["end_byte"]) == (start, end)
    assert link["raw_span_sha256"] == sha(source[start:end])


def test_crlf_extractor_frontier_keeps_native_unmatched_functions_and_obligations():
    source = b"def f(a):\r\n    return a[0]\r\n"
    report = bind(source)
    assert report["inventory_frontier"] == "source_line_controls_not_mapped"
    assert report["unit_count"] == report["matched_unit_count"] == 0
    assert report["native_function_count"] == report["unmatched_native_function_count"] == 1
    assert report["pending_obligation_count"] == len(report["unlinked_pending_obligation_ids"]) == 1
    assert report["linked_pending_obligation_count"] == 0


@pytest.mark.parametrize("source,frontier", [(b"x = 1\n", "no_function_units"),
    (b"def malformed(:\n    pass\n", "complete_python_source_required")])
def test_frontiers_do_not_invent_unit_or_proof_coverage(source, frontier):
    report = bind(source)
    assert report["inventory_frontier"] == frontier
    assert report["unit_count"] == report["matched_unit_count"] == report["native_function_count"] == 0
    assert report["pending_obligation_count"] == report["source_obligations_discharged"] == 0


def test_partial_loop_with_zero_obligations_does_not_inherit_other_function_lean_artifact():
    source = b"def f(a):\n    return a[0]\ndef g(a):\n    for x in a:\n        print(x)\n"
    report = bind(source)
    loop = report["links"][1]
    assert loop["structural_status"] == "partial" and loop["unsupported_constructs"]
    assert loop["pending_obligation_count"] == 0
    assert len(loop["family_artifact_ids"]) == 1
    assert loop["family_artifact_ids"][0].startswith("program:")


def test_existing_scalar_eligible_shape_is_not_a_candidate_or_proof():
    source = b"def plus(a: int, b: int) -> int:\n    return a + b\n"
    report = bind(source)
    row, = report["links"]
    assert row["scalar_guard_status"] == "eligible_source_shape" and row["scalar_guard_reason"] is None
    for value in (row, report):
        for key in api._FALSE:
            assert value[key] is False
    assert report["provider_calls"] == report["solver_calls"] == report["source_obligations_discharged"] == 0


@pytest.mark.parametrize("damage", ["id", "hash", "normalization", "range", "map", "producer",
    "extra", "authority", "drop"])
def test_resealed_inventory_tampering_is_rejected(damage):
    inventory, native = prepare()
    row = inventory["units"][0]
    if damage == "id": row["unit_id"] = "0" * 64
    elif damage == "hash": row["normalized_body_sha256"] = "0" * 64
    elif damage == "normalization": row["normalized_source_text"] += "\n"
    elif damage == "range": row["start_byte"] += 1
    elif damage == "map": row["source_binding"]["line_byte_map"][0]["source_start_byte"] += 1
    elif damage == "producer": inventory["producer"] = {}
    elif damage == "extra": row["inference_disposition"] = "selected"
    elif damage == "authority": row["proof_authority"] = True
    else: inventory["units"].pop()
    with pytest.raises(api.SourceUnitNumericalLinkError, match="exact replay"):
        api.bind_function_unit_logic(source_bytes=SOURCE, unit_inventory=inventory, numerical_report=native)


@pytest.mark.parametrize("damage", ["path", "span", "function", "obligation", "contract", "artifact",
                                  "authority", "hash"])
def test_resealed_native_report_tampering_is_rejected(damage):
    inventory, native = prepare()
    if damage == "path": native["path"] = "other.py"
    elif damage == "span": native["structural"]["program"]["spans"][0]["start_byte"] += 1
    elif damage == "function": native["structural"]["program"]["functions"][0]["function_id"] = "other"
    elif damage == "obligation": native["pending_obligations"].pop()
    elif damage == "contract": native["compound_contracts"] = []
    elif damage == "artifact": native["projections"]["lean"]["source"] += "\n"
    elif damage == "authority": native["proof_authority"] = True
    else: native["source_sha256"] = "0" * 64
    native["report_sha256"] = sha(wire({k: v for k, v in native.items() if k != "report_sha256"}))
    with pytest.raises(api.SourceUnitNumericalLinkError, match="exact replay"):
        api.bind_function_unit_logic(source_bytes=SOURCE, unit_inventory=inventory, numerical_report=native)


@pytest.mark.parametrize("damage", ["id", "hash", "count", "authority", "shape", "artifact",
                                  "pointer", "unmatched", "import", "producer"])
def test_link_replay_rejects_metadata_promotions_and_resealed_references(damage):
    inventory, native = prepare()
    report = api.bind_function_unit_logic(source_bytes=SOURCE, unit_inventory=inventory, numerical_report=native)
    if damage == "id": report["links"][0]["function_id"] = "foreign"
    elif damage == "hash": report["numerical_report_sha256"] = "0" * 64
    elif damage == "count": report["matched_unit_count"] += 1
    elif damage == "authority": report["links"][0]["proof_authority"] = True
    elif damage == "shape": report["links"][0]["scalar_guard_status"] = "verified"
    elif damage == "artifact": report["artifacts"][0]["artifact_sha256"] = "0" * 64
    elif damage == "pointer": report["artifacts"][0]["report_pointer"] = "/secret"
    elif damage == "unmatched": report["unmatched_native_function_ids"].append("invented")
    elif damage == "import": report["import_context"]["runtime_identity_verified"] = True
    else: report["producer"] = {}
    report["report_sha256"] = sha(wire({k: v for k, v in report.items() if k != "report_sha256"}))
    with pytest.raises(api.SourceUnitNumericalLinkError, match="links differ"):
        api.validate_function_unit_logic_links(report, source_bytes=SOURCE,
            unit_inventory=inventory, numerical_report=native)


@pytest.mark.parametrize("source", [b"", b"x" * 65537, "def f(): pass", b"\xff"])
def test_wrong_or_oversize_original_bytes_rejected(source):
    inventory, native = prepare()
    with pytest.raises(api.SourceUnitNumericalLinkError):
        api.bind_function_unit_logic(source_bytes=source, unit_inventory=inventory, numerical_report=native)


def test_input_json_bound_and_non_json_rejected():
    inventory, native = prepare()
    for value in ({"extra": "x" * (api.MAX_REPORT_BYTES + 1)}, {"bad": float("nan")}, {"bad": object()}):
        with pytest.raises(api.SourceUnitNumericalLinkError):
            api.bind_function_unit_logic(source_bytes=SOURCE, unit_inventory=value, numerical_report=native)


def test_prepare_is_pure_and_never_executes_source_or_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("subprocess execution is forbidden")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    source = b'raise RuntimeError("never execute this")\ndef f(a):\n    return a[0]\n'
    report = bind(source)
    assert report["matched_unit_count"] == 1
    assert report["model_inference_executed"] is report["training_performed"] is False


def test_unit_and_native_bounds_are_hard_refusals_never_partial_inventory():
    source = b"\n".join(f"def f{i}(a):\n    return a[0]\n".encode() for i in range(33))
    inventory = units.extract_function_units(source_bytes=source, source_sha256=sha(source), source_path="f.py")
    assert len(inventory["units"]) == 33
    with pytest.raises(api.SourceUnitNumericalLinkError, match="exact replay"):
        api.bind_function_unit_logic(source_bytes=source, unit_inventory=inventory, numerical_report={})

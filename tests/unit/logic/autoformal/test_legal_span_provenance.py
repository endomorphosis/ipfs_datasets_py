"""Pinned authored projections never establish historical or legal authority."""
import ast
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance

CACHE = {"repository": "fixture/span-cache", "revision": "a" * 40, "artifact_sha256": "b" * 64}
PROJECTION = {"source_span_id": "demo:1", "legal_id": "usc:us:10:1", "source_text": "Agency shall retain café notice. §1"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def source_fixture(tmp_path, literals=None, body=None):
    literals = [tuple(PROJECTION.values())] if literals is None else literals
    path = tmp_path / "authored.py"
    source = ("raise RuntimeError('source must never execute')\n\n"
              "def demonstration_spans():\n" + (body if body is not None else
              "    rows = " + repr(tuple(literals)) + "\n    return rows\n"))
    path.write_text(source, encoding="utf-8")
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef))
    pin = {"source_id": "fixture:authored-literals", "path": str(path),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "function_name": "demonstration_spans",
        "function_ast_sha256": hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest(),
        "projection_profile": provenance.PROJECTION_PROFILE}
    return path, [pin]


def flat(**changes):
    return {**PROJECTION, "source_revision": "observed-short-revision", "source_sha256": "not-authenticated",
            "model": {"identity": "legacy-declared-model", "complete": True}, "admitted": True,
            "formalized": True, "unknown_future": {"retain": [None, "雪", True]}, **changes}


def paired(version="uscode-paired-span-census/v1"):
    return {"schema_version": version, "source": {"span_id": PROJECTION["source_span_id"],
        "legal_id": PROJECTION["legal_id"], "text": PROJECTION["source_text"],
        "revision": "legacy-short-revision", "text_sha256": "declaration-only"},
        "autoencoder": {"model_identity": "legacy-mock-diagnostic", "complete": True,
                        "formal_outputs": [{"target_conditioned": True, "payload_json": "{}"}]},
        "compiler": {"canonical_complete": True}, "admitted": True, "formalized": True,
        "unknown_future": {"retain": [None, "雪"]}}


def inputs(rows, pins, *, start_ordinal=7):
    catalog = provenance.catalog_from_sources(pins)
    return {"cache_identity": deepcopy(CACHE), "start_ordinal": start_ordinal,
        "expected_row_sha256s": [intake.row_sha256(row) for row in rows],
        "expected_record_sha256s": [intake.record_sha256(row, ordinal=start_ordinal + i, cache_identity=CACHE)
                                   for i, row in enumerate(rows)],
        "demonstration_catalog": catalog, "expected_catalog_sha256": digest(catalog),
        "expected_catalog_source_pins": deepcopy(pins)}


def test_catalog_is_full_literal_ast_custody_without_executing_module(tmp_path):
    _, pins = source_fixture(tmp_path, [tuple(PROJECTION.values()), ("scrap", "", "5, 1990, 104 Stat.")])
    catalog = provenance.catalog_from_sources(pins)
    assert catalog["sources"] == pins
    assert catalog["demonstrations"][0]["projection"] == PROJECTION
    assert catalog["demonstrations"][1]["projection"]["legal_id"] == ""
    assert [row["literal_ordinal"] for row in catalog["demonstrations"]] == [0, 1]
    assert provenance.catalog_sha256(catalog) == digest(catalog)


@pytest.mark.parametrize("profile", [None, "span_export_fields/v1", "uscode-autoformal-span-evidence/v1",
                                     "uscode-paired-span-census/v1", "uscode-paired-span-census/v2"])
def test_all_supported_profiles_match_only_three_fields_and_keep_authority_false(tmp_path, profile):
    _, pins = source_fixture(tmp_path)
    row = paired(profile) if profile and "paired" in profile else flat()
    if profile and "paired" not in profile:
        row["schema_version"] = profile
    args = inputs([row], pins)
    report = provenance.reconcile_span_provenance([row], **args)
    observed = report["rows"][0]
    assert observed["classification"] == "exact_authored_projection_match"
    assert observed["raw_row"] == row and observed["row_ordinal"] == 7
    assert observed["match_scope"] == "literal_source_span_id_legal_id_source_text_only"
    assert observed["source_identity"]["projection_sha256"] == digest(PROJECTION)
    assert observed["source_identity"]["declared_revision"] == ("legacy-short-revision" if "paired" in (profile or "") else "observed-short-revision")
    assert observed["legacy_producer_declarations_status"] == "raw_observations_only_not_execution_proof"
    assert all(value is False for value in observed["authority"].values())
    assert all(value is False for value in report["authority"].values())
    assert report["population_complete"] is True and report["whole_cache_coverage_verified"] is False
    assert report["historical_producer_attribution"] == "not_established_by_literal_projection_match"
    assert provenance.provenance_report_sha256(report) == digest(report)
    assert provenance.validate_span_provenance(report, [row], expected_report_sha256=digest(report), **args) == report
    if profile and "paired" in profile:
        assert "paired_projection_only_not_supported_formal_transport" in {issue["code"] for issue in observed["issues"]}


def test_repeated_physical_rows_have_distinct_record_identity_and_complete_classification(tmp_path):
    _, pins = source_fixture(tmp_path)
    rows = [flat(), flat(), flat(source_text="Unmatched authored text.")]
    report = provenance.reconcile_span_provenance(rows, **inputs(rows, pins, start_ordinal=22))
    assert [item["row_ordinal"] for item in report["rows"]] == [22, 23, 24]
    assert report["rows"][0]["raw_row_sha256"] == report["rows"][1]["raw_row_sha256"]
    assert len({item["record_sha256"] for item in report["rows"]}) == 3
    assert report["classification_counts"] == {"exact_authored_projection_match": 2, "no_authored_projection_match": 1}
    assert report["row_count"] == sum(report["classification_counts"].values()) == len(report["rows"])


def test_repeated_authored_literals_remain_ambiguous_without_first_match_selection(tmp_path):
    _, pins = source_fixture(tmp_path, [tuple(PROJECTION.values()), tuple(PROJECTION.values())])
    rows = [flat()]
    result = provenance.reconcile_span_provenance(rows, **inputs(rows, pins))
    observed = result["rows"][0]
    assert observed["classification"] == "ambiguous_authored_projection_match"
    assert [item["literal_ordinal"] for item in observed["matched_demonstrations"]] == [0, 1]
    assert len({item["demonstration_id"] for item in observed["matched_demonstrations"]}) == 2


@pytest.mark.parametrize("field,value", [("source_span_id", "demo:1 "), ("legal_id", "USC:us:10:1"),
    ("legal_id", "usc:us:10:2"), ("source_text", PROJECTION["source_text"].replace("é", "e\u0301")),
    ("source_text", PROJECTION["source_text"] + " ")])
def test_literal_identity_and_unicode_are_not_normalized(tmp_path, field, value):
    _, pins = source_fixture(tmp_path)
    rows = [flat(**{field: value})]
    result = provenance.reconcile_span_provenance(rows, **inputs(rows, pins))
    assert result["rows"][0]["classification"] == "no_authored_projection_match"
    assert result["rows"][0]["raw_row"] == rows[0]


def test_aliases_are_retained_but_never_used_to_fill_projection(tmp_path):
    _, pins = source_fixture(tmp_path)
    row = flat(id=PROJECTION["source_span_id"], text=PROJECTION["source_text"])
    row.pop("source_span_id"); row.pop("source_text")
    report = provenance.reconcile_span_provenance([row], **inputs([row], pins))
    observed = report["rows"][0]
    assert observed["classification"] == "incomplete_source_projection"
    assert observed["matched_demonstrations"] == [] and observed["raw_row"] == row
    assert observed["source_identity"]["source_span_id"] is None


def test_conflicting_alias_does_not_change_explicit_three_field_comparison_scope(tmp_path):
    _, pins = source_fixture(tmp_path)
    row = flat(id="conflicting-alias", text="Not the canonical source_text.")
    observed = provenance.reconcile_span_provenance([row], **inputs([row], pins))["rows"][0]
    assert observed["classification"] == "exact_authored_projection_match"
    assert len([issue for issue in observed["issues"] if issue["code"] == "nonmatching_alias_observation_not_used"]) == 2
    assert observed["authority"]["entire_row_matches_authored_source"] is False


@pytest.mark.parametrize("row", [flat(source_text=None), flat(source_span_id=""),
    {"schema_version": "unknown/v99", **flat()}, {"schema_version": {"unexpected": True}, **flat()},
    {"schema_version": "uscode-paired-span-census/v1", "source": None, "legacy_complete": True}])
def test_incomplete_and_unsupported_rows_are_retained_as_explicit_observations(tmp_path, row):
    _, pins = source_fixture(tmp_path)
    report = provenance.reconcile_span_provenance([row], **inputs([row], pins))
    observed = report["rows"][0]
    assert observed["classification"] in {"unsupported_source_profile", "incomplete_source_projection"}
    assert observed["raw_row"] == row and observed["matched_demonstrations"] == []
    assert observed["issues"] and report["row_count"] == 1


@pytest.mark.parametrize("damage", ["raw_unknown", "reorder", "missing", "extra", "ordinal", "cache_revision", "cache_artifact", "row_pin", "record_pin"])
def test_independent_ordered_population_custody_rejects_every_membership_dimension(tmp_path, damage):
    _, pins = source_fixture(tmp_path)
    rows = [flat(), flat(source_span_id="other")]
    args = inputs(rows, pins)
    if damage == "raw_unknown": rows[0]["unknown_future"]["retain"][0] = "changed"
    elif damage == "reorder": rows.reverse()
    elif damage == "missing": rows.pop()
    elif damage == "extra": rows.append(deepcopy(rows[0]))
    elif damage == "ordinal": args["start_ordinal"] += 1
    elif damage == "cache_revision": args["cache_identity"]["revision"] = "c" * 40
    elif damage == "cache_artifact": args["cache_identity"]["artifact_sha256"] = "c" * 64
    elif damage == "row_pin": args["expected_row_sha256s"][0] = "0" * 64
    else: args["expected_record_sha256s"][0] = "0" * 64
    with pytest.raises(ValueError):
        provenance.reconcile_span_provenance(rows, **args)


@pytest.mark.parametrize("damage", ["omitted", "extra", "reordered", "projection", "source", "unknown_field", "independent_pin"])
def test_self_rehashed_catalog_cannot_override_independently_pinned_authored_source(tmp_path, damage):
    _, pins = source_fixture(tmp_path, [tuple(PROJECTION.values()), ("other", "usc:us:10:2", "Other literal.")])
    rows = [flat()]
    args = inputs(rows, pins)
    catalog = args["demonstration_catalog"]
    if damage == "omitted": catalog["demonstrations"].pop()
    elif damage == "extra": catalog["demonstrations"].append(deepcopy(catalog["demonstrations"][0]))
    elif damage == "reordered": catalog["demonstrations"].reverse()
    elif damage == "projection": catalog["demonstrations"][0]["projection"]["source_text"] = "Forged literal."
    elif damage == "source": catalog["sources"][0]["source_sha256"] = "0" * 64
    elif damage == "unknown_field": catalog["future_authority"] = True
    args["expected_catalog_sha256"] = "0" * 64 if damage == "independent_pin" else digest(catalog)
    with pytest.raises(ValueError):
        provenance.reconcile_span_provenance(rows, **args)


@pytest.mark.parametrize("damage", ["bytes", "function_ast", "function_name", "source_identity", "source_symlink", "duplicate_source", "unknown_pin", "source_too_large"])
def test_catalog_source_identity_and_immutable_bytes_are_external_required_inputs(tmp_path, damage):
    path, pins = source_fixture(tmp_path)
    rows = [flat()]
    args = inputs(rows, pins)
    source = args["expected_catalog_source_pins"][0]
    if damage == "bytes": path.write_text(path.read_text() + "\n# Changed outside function\n")
    elif damage == "function_ast": source["function_ast_sha256"] = "0" * 64
    elif damage == "function_name": source["function_name"] = "absent_function"
    elif damage == "source_identity": source["source_id"] = "different-source"
    elif damage == "source_symlink":
        alias = tmp_path / "alias.py"; alias.symlink_to(path); source["path"] = str(alias)
    elif damage == "duplicate_source": args["expected_catalog_source_pins"].append(deepcopy(source))
    elif damage == "unknown_pin": source["catalog_authenticated"] = True
    else:
        path.write_bytes(b"#" * (provenance.MAX_SOURCE_BYTES + 1))
        source["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises((ValueError, OSError)):
        provenance.reconcile_span_provenance(rows, **args)


@pytest.mark.parametrize("body", ["    rows = build_dynamic_rows()\n    return rows\n",
    "    rows = ()\n    rows = ()\n    return rows\n", "    return [('id', 'legal', 'text')]\n",
    "    rows = (('id', 'legal', 'text', 'extra'),)\n    return rows\n"])
def test_only_declared_closed_literal_source_profile_is_supported(tmp_path, body):
    _, pins = source_fixture(tmp_path, body=body)
    with pytest.raises(ValueError):
        provenance.catalog_from_sources(pins)


@pytest.mark.parametrize("damage", ["authority", "classification", "raw_unknown", "omit_row", "source_identity", "internal_digest"])
def test_resealed_report_forgery_is_rejected_by_complete_regeneration(tmp_path, damage):
    _, pins = source_fixture(tmp_path)
    rows = [flat(), flat()]
    args = inputs(rows, pins)
    report = provenance.reconcile_span_provenance(rows, **args)
    independent = digest(report)
    if damage == "authority": report["rows"][0]["authority"]["model_invocation_verified"] = True
    elif damage == "classification": report["rows"][0]["classification"] = "historical_producer_verified"
    elif damage == "raw_unknown": report["rows"][0]["raw_row"]["unknown_future"]["retain"][0] = "forged"
    elif damage == "omit_row": report["rows"].pop()
    elif damage == "source_identity": report["rows"][0]["source_identity"]["legal_id"] = "different"
    else: report["provenance_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="independent complete provenance report pin"):
        provenance.validate_span_provenance(report, rows, expected_report_sha256=independent, **args)
    with pytest.raises(ValueError, match="complete regeneration"):
        provenance.validate_span_provenance(report, rows, expected_report_sha256=digest(report), **args)


@pytest.mark.parametrize("damage", ["empty_rows", "too_many_rows", "bool_ordinal", "negative_ordinal", "nonfinite", "oversize_row"])
def test_finite_explicit_population_bounds_never_return_partial_reports(tmp_path, damage):
    _, pins = source_fixture(tmp_path)
    rows = [flat()]
    args = inputs(rows, pins)
    if damage == "empty_rows": rows = []
    elif damage == "too_many_rows": rows = [flat()] * (provenance.MAX_ROWS + 1)
    elif damage == "bool_ordinal": args["start_ordinal"] = True
    elif damage == "negative_ordinal": args["start_ordinal"] = -1
    elif damage == "nonfinite": rows[0]["unknown_future"] = float("nan")
    else: rows[0]["unknown_future"] = "x" * (intake.MAX_ROW_BYTES + 1)
    with pytest.raises(ValueError):
        provenance.reconcile_span_provenance(rows, **args)

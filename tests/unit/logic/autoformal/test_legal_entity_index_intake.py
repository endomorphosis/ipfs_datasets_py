"""Offline physical-index fixtures preserve unresolved/duplicate observations."""
from copy import deepcopy
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as intake


def row(kind, **values):
    result = {key: False if key in intake.BOOLEAN_FIELDS else "" for key in intake.FIELDS}
    result.update(record_kind=kind, **values)
    return result


def rows():
    a = row("node", node_id="A", graph_kind="section", meta_category="scope", label="Café §")
    edge = row("edge", src="A", dst="B", graph_kind="CITES", meta_category="citation",
               logic_role="reference", in_formula=True, admitted=True, formalized=True)
    return [edge, a, row("node", node_id="B", label="Café §"), deepcopy(a), deepcopy(edge),
            row("edge", src="B", dst="outside"), row("edge", src="", dst="B"),
            row("node", node_id=""), row("category", label="participant"),
            row("logical_relation", graph_kind="CITES"), row("term", label="Café §"),
            row("unexpected", label="retain unknown kind and fields", logic_role="unknown"),
            row("node", node_id=None), row("edge", src=None, dst=None),
            row(None, in_formula=None, admitted=None, formalized=None), row("edge", src="B", dst="B")]


def write(path, records, schema=None):
    if schema is None:
        schema = pa.schema([pa.field(key, pa.bool_() if key in intake.BOOLEAN_FIELDS else pa.string())
                            for key in intake.FIELDS])
    pq.write_table(pa.Table.from_pylist(records, schema=schema), path, row_group_size=3)
    return dict(expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), expected_rows=len(records),
                max_rows=100, batch_size=2, revision="immutable-hub-revision-fixture")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "index.parquet"
    return path, write(path, rows())


def test_lossless_rows_keep_ordinals_unicode_nulls_and_unreviewed_legacy_flags(source):
    path, request = source
    observations = list(intake.iter_observed_rows(path, **request))
    assert [o["raw_row"] for o in observations] == rows()
    assert [o["ordinal"] for o in observations] == list(range(16))
    assert [(o["row_group"], o["row_group_ordinal"]) for o in observations] == [(i // 3, i % 3) for i in range(16)]
    assert observations[1]["raw_row_sha256"] == observations[3]["raw_row_sha256"]
    assert observations[1]["observation_sha256"] != observations[3]["observation_sha256"]
    assert observations[0]["raw_row"]["admitted"] is True
    assert all(not value for o in observations for value in o["authority"].values())
    assert observations[0]["source"]["raw_row_file_byte_mapping_verified"] is False
    assert observations[11]["declared_classification_hint"] is None


def test_census_has_exclusive_dispositions_and_never_guesses_empty_ids_or_endpoints(source):
    path, request = source
    result = intake.census_parquet(path, **request)
    assert result["rows"] == sum(result["disposition_counts"].values()) == 16
    assert result["disposition_counts"] == {
        "category_observation": 1, "edge_observation_ambiguous_endpoint": 2,
        "edge_observation_unique_declared_endpoints": 1, "edge_observation_unresolved_endpoint": 3,
        "logical_relation_observation": 1, "node_observation": 3,
        "node_observation_missing_identity": 2, "term_observation": 1, "unknown_record_kind_observation": 2}
    assert result["duplicate_raw_row_groups"] == result["duplicate_raw_row_extra_instances"] == 2
    assert result["duplicate_node_identities"] == result["duplicate_node_identity_extra_instances"] == 1
    assert result["edge_source_endpoint_missing_rows"] == 2
    assert result["edge_target_endpoint_missing_rows"] == 2
    assert result["null_field_counts"]["node_id"] == 1
    assert result["empty_string_field_counts"]["node_id"] > 1
    assert result["population_complete"] is True
    assert result["coverage_scope"] == "exact_pinned_parquet_rows_only"
    assert result["complete_section_coverage_verified"] is False
    assert all(not flag for flag in result["authority"].values())
    assert intake.validate_census(result, path, **request) == result


def test_ordered_stream_hash_is_batch_independent_and_order_sensitive(tmp_path):
    path = tmp_path / "index.parquet"
    request = write(path, rows())
    first = intake.census_parquet(path, **request)
    second = intake.census_parquet(path, **{**request, "batch_size": 3})
    assert first["ordered_stream_sha256"] == second["ordered_stream_sha256"]
    reordered = rows(); reordered[0], reordered[1] = reordered[1], reordered[0]
    changed = write(path, reordered)
    assert intake.census_parquet(path, **changed)["ordered_stream_sha256"] != first["ordered_stream_sha256"]


def test_observation_custody_is_detached_and_revision_specific(source):
    path, request = source
    stream = intake.iter_observed_rows(path, **request)
    first = next(stream)
    first["source"]["expected_rows"] = 0
    assert len(list(stream)) == 15
    original = next(intake.iter_observed_rows(path, **request))
    changed = next(intake.iter_observed_rows(path, **{**request, "revision": "other-revision"}))
    assert original["raw_row_sha256"] == changed["raw_row_sha256"]
    assert original["observation_sha256"] != changed["observation_sha256"]


@pytest.mark.parametrize("damage", ["authority", "count", "unknown", "population"])
def test_self_resealed_summary_cannot_replace_independently_replayed_census(source, damage):
    path, request = source
    result = intake.census_parquet(path, **request)
    if damage == "authority": result["authority"]["admitted"] = True
    elif damage == "count": result["disposition_counts"]["node_observation"] += 1
    elif damage == "unknown": result["ignored"] = True
    else: result["rows"] -= 1
    result["census_sha256"] = intake._digest({key: value for key, value in result.items() if key != "census_sha256"})
    with pytest.raises(intake.EntityIndexIntakeError, match="trusted full replay"):
        intake.validate_census(result, path, **request)


@pytest.mark.parametrize("damage", ["hash", "rows", "file_bound", "row_bound", "group_bound", "decoded_bound"])
def test_preflight_rejects_wrong_pins_or_resource_bounds_before_row_decode(source, monkeypatch, damage):
    path, request = source
    if damage == "hash": request["expected_file_sha256"] = "0" * 64
    elif damage == "rows": request["expected_rows"] -= 1
    elif damage == "file_bound": request["max_file_bytes"] = 1
    elif damage == "row_bound": request["max_rows"] = 1
    elif damage == "group_bound": request["max_row_group_bytes"] = 1
    else: request["max_decoded_bytes"] = 1
    def forbidden(*args): pytest.fail("preflight failure decoded source rows")
    monkeypatch.setattr(intake, "_rows", forbidden)
    with pytest.raises(intake.EntityIndexIntakeError): intake.census_parquet(path, **request)


@pytest.mark.parametrize("damage", ["extra", "type", "order", "duplicate"])
def test_unsupported_schema_is_refused_without_silent_field_loss(tmp_path, damage):
    fields = [pa.field(key, pa.bool_() if key in intake.BOOLEAN_FIELDS else pa.string()) for key in intake.FIELDS]
    if damage == "extra": fields.append(pa.field("unknown_column", pa.string()))
    elif damage == "type": fields[0] = pa.field("record_kind", pa.int64())
    elif damage == "order": fields[0], fields[1] = fields[1], fields[0]
    else: fields[-1] = pa.field("admitted", pa.bool_())
    path = tmp_path / "index.parquet"
    schema = pa.schema(fields)
    pq.write_table(pa.Table.from_arrays([pa.array([], type=f.type) for f in fields], schema=schema), path)
    request = dict(expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), expected_rows=0,
                   max_rows=100, batch_size=2)
    with pytest.raises(intake.EntityIndexIntakeError): intake.census_parquet(path, **request)


def test_runtime_expansion_raw_row_and_distinct_value_bounds_fail_without_partial_census(source, monkeypatch):
    path, request = source
    for option in ("max_batch_bytes", "max_row_bytes"):
        with pytest.raises(intake.EntityIndexIntakeError):
            intake.census_parquet(path, **{**request, option: 1})
    monkeypatch.setattr(intake, "MAX_DISTINCT_VALUES", 1)
    with pytest.raises(intake.EntityIndexIntakeError, match="distinct observation"):
        intake.census_parquet(path, **request)


@pytest.mark.parametrize("damage", ["rewrite", "replace"])
def test_file_movement_is_detected_when_iteration_finishes_or_closes(source, damage):
    path, request = source
    stream = intake.iter_observed_rows(path, **request)
    next(stream)
    raw = path.read_bytes()
    if damage == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(raw)
        replacement.replace(path)
    else: path.write_bytes(raw)
    with pytest.raises(intake.EntityIndexIntakeError, match="changed|replaced"):
        stream.close()


def test_symlink_source_alias_is_rejected(source, tmp_path):
    path, request = source
    alias = tmp_path / "alias.parquet"
    alias.symlink_to(path)
    with pytest.raises(intake.EntityIndexIntakeError, match="aliased"):
        intake.census_parquet(alias, **request)


def test_empty_population_is_exact_without_invented_record_kinds(tmp_path):
    path = tmp_path / "empty.parquet"
    request = write(path, [])
    result = intake.census_parquet(path, **request)
    assert result["rows"] == sum(result["disposition_counts"].values()) == 0
    assert result["value_counts"]["record_kind"] == []
    assert list(intake.iter_observed_rows(path, **request)) == []


def test_binding_only_validation_requires_independent_prior_census_pin_and_never_decodes_rows(source, monkeypatch):
    path, request = source
    result = intake.census_parquet(path, **request)
    def forbidden(*args): pytest.fail("binding-only validator decoded source rows")
    monkeypatch.setattr(intake, "_rows", forbidden)
    validation = intake.validate_census_bindings(result, path, expected_census_sha256=result["census_sha256"], **request)
    assert validation["fresh_row_replay_performed"] is False
    assert validation["coverage_scope"] == "immutable_file_and_independently_pinned_prior_census_only"
    with pytest.raises(intake.EntityIndexIntakeError, match="independently pinned"):
        intake.validate_census_bindings(result, path, expected_census_sha256="0" * 64, **request)
    changed = deepcopy(result)
    changed["rows"] += 1
    changed["census_sha256"] = intake._digest({k: v for k, v in changed.items() if k != "census_sha256"})
    with pytest.raises(intake.EntityIndexIntakeError, match="independently pinned"):
        intake.validate_census_bindings(changed, path, expected_census_sha256=result["census_sha256"], **request)
    with pytest.raises(intake.EntityIndexIntakeError, match="source custody"):
        intake.validate_census_bindings(result, path, expected_census_sha256=result["census_sha256"],
                                       **{**request, "revision": "other-revision"})


def test_bounded_scratch_exhaustion_never_returns_a_partial_census(tmp_path):
    path = tmp_path / "index.parquet"
    # SQLite stores raw-row hashes and node IDs, not display labels. Long unique
    # IDs force real B-tree allocation beyond the four-page scratch ceiling.
    request = write(path, [row("node", node_id=f"node:{i}:" + str(i) * 1000) for i in range(80)])
    with pytest.raises(intake.EntityIndexIntakeError, match="on-disk observation"):
        intake.census_parquet(path, **{**request, "max_scratch_bytes": 4 * 4096})


def test_actual_classification_rule_records_are_ontology_observations_without_authority(tmp_path):
    path = tmp_path / "ontology.parquet"
    declared = row("classification_rule", meta_category="participant", graph_kind="lexical_role",
                   label="office", logic_role="bearer", in_formula=True, admitted=True, formalized=True)
    request = write(path, [declared, deepcopy(declared), row("future_unknown_kind")])
    result = intake.census_parquet(path, **request)
    assert result["disposition_counts"]["classification_rule_observation"] == 2
    assert result["disposition_counts"]["unknown_record_kind_observation"] == 1
    assert sum(result["disposition_counts"].values()) == 3
    assert result["duplicate_raw_row_extra_instances"] == 1
    observed = list(intake.iter_observed_rows(path, **request))
    assert observed[0]["raw_row"] == observed[1]["raw_row"] == declared
    assert observed[0]["observation_sha256"] != observed[1]["observation_sha256"]
    assert observed[0]["declared_classification_hint"] is None
    assert all(not value for record in observed for value in record["authority"].values())


@pytest.mark.parametrize("records", [[], rows()])
def test_v2_is_explicit_and_preserves_the_complete_default_v1_report(tmp_path, records):
    path = tmp_path / "index.parquet"
    request = write(path, records)
    old = intake.census_parquet(path, **request)
    detailed = intake.census_parquet(path, endpoint_details=True, **request)
    assert old["schema"] == intake.SCHEMA
    assert detailed["schema"] == intake.DETAILED_SCHEMA
    assert "endpoint_integrity" not in old
    projected = deepcopy(detailed)
    projected.pop("endpoint_integrity")
    projected.pop("census_sha256")
    projected["schema"] = intake.SCHEMA
    projected["census_sha256"] = intake._digest(projected)
    assert projected == old
    assert not any(detailed["authority"].values())
    assert detailed["endpoint_integrity"]["semantic_identity_verified"] is False
    assert detailed["census_sha256"] != old["census_sha256"]


def test_v2_partitions_edges_and_retains_overlapping_diagnostics_and_multiplicity(tmp_path):
    path = tmp_path / "mixed.parquet"
    records = [row("node", node_id="A"), row("node", node_id="A", label="different record"),
               row("node", node_id="B")]
    endpoints = [("A", "B"), ("A", "B"), (None, "B"), ("", "ghost"),
                 ("ghost", "B"), ("B", "ghost"), ("A", "ghost"), ("", "A"),
                 (None, None), ("B", "B"), (" ", "B")]
    records += [row("edge", src=src, dst=dst) for src, dst in endpoints]
    records += [row("logical_relation", src="B", dst="B"), row("node", node_id=None)]
    request = write(path, records)
    result = intake.census_parquet(path, endpoint_details=True, **request)
    detail = result["endpoint_integrity"]
    assert detail["record_kind"] == "edge"
    assert detail["edge_rows"] == 11
    assert detail["missing_endpoint_values"] == {"source": 4, "target": 1, "both": 1, "either": 4}
    assert detail["nonempty_dangling_references"] == {"source": 2, "target": 3, "either": 5}
    assert detail["ambiguous_declared_references"] == {"source": 3, "target": 1, "either": 4}
    assert detail["exclusive_edge_dispositions"] == {
        "missing_endpoint_value": 4, "nonempty_dangling_endpoint": 4,
        "ambiguous_declared_endpoint": 2, "unique_declared_endpoints": 1}
    assert detail["endpoint_counts_may_overlap"] is True
    assert sum(detail["exclusive_edge_dispositions"].values()) == len(endpoints)
    assert result["edge_source_endpoint_missing_rows"] == 6
    assert result["edge_target_endpoint_missing_rows"] == 4


def test_v2_does_not_normalize_identifiers_or_turn_matching_into_semantic_identity(tmp_path):
    path = tmp_path / "exact.parquet"
    request = write(path, [row("node", node_id=" A"), row("node", node_id=" "),
        row("edge", src=" A", dst=" "), row("edge", src="A", dst=" ")])
    result = intake.census_parquet(path, endpoint_details=True, **request)
    detail = result["endpoint_integrity"]
    assert detail["exclusive_edge_dispositions"] == {
        "missing_endpoint_value": 0, "nonempty_dangling_endpoint": 1,
        "ambiguous_declared_endpoint": 0, "unique_declared_endpoints": 1}
    assert detail["matching_policy"] == "exact_nonempty_node_id_equality_no_normalization"
    assert detail["semantic_identity_verified"] is False
    assert not any(result["authority"].values())


def test_v2_replay_and_bindings_require_the_explicit_version_and_independent_pin(source, monkeypatch):
    path, request = source
    result = intake.census_parquet(path, endpoint_details=True, **request)
    assert intake.validate_census(result, path, endpoint_details=True, **request) == result
    with pytest.raises(intake.EntityIndexIntakeError, match="trusted full replay"):
        intake.validate_census(result, path, **request)
    def forbidden(*args):
        pytest.fail("binding-only validator decoded rows")
    monkeypatch.setattr(intake, "_rows", forbidden)
    check = intake.validate_census_bindings(result, path, endpoint_details=True,
        expected_census_sha256=result["census_sha256"], **request)
    assert check["fresh_row_replay_performed"] is False
    with pytest.raises(intake.EntityIndexIntakeError, match="closed prior census"):
        intake.validate_census_bindings(result, path, expected_census_sha256=result["census_sha256"], **request)
    altered = deepcopy(result)
    altered["endpoint_integrity"]["exclusive_edge_dispositions"]["unique_declared_endpoints"] += 1
    altered["census_sha256"] = intake._digest({k: v for k, v in altered.items() if k != "census_sha256"})
    with pytest.raises(intake.EntityIndexIntakeError, match="independently pinned"):
        intake.validate_census_bindings(altered, path, endpoint_details=True,
            expected_census_sha256=result["census_sha256"], **request)


@pytest.mark.parametrize("flag", [0, 1, None, "true", [], {}])
def test_endpoint_details_rejects_coercible_nonboolean_requests_before_opening_source(tmp_path, flag):
    request = dict(expected_file_sha256="0" * 64, expected_rows=0, max_rows=1, batch_size=1,
                   endpoint_details=flag)
    with pytest.raises(intake.EntityIndexIntakeError, match="boolean endpoint_details"):
        intake.census_parquet(tmp_path / "absent.parquet", **request)
    with pytest.raises(intake.EntityIndexIntakeError, match="boolean endpoint_details"):
        intake.validate_census_bindings({}, tmp_path / "absent.parquet",
            expected_census_sha256="0" * 64, **request)


def test_v2_diagnostics_are_independent_of_batch_and_row_group_boundaries(tmp_path):
    path = tmp_path / "index.parquet"
    request = write(path, rows())
    first = intake.census_parquet(path, endpoint_details=True, **request)
    second = intake.census_parquet(path, endpoint_details=True, **{**request, "batch_size": 1})
    assert first["endpoint_integrity"] == second["endpoint_integrity"]
    assert first["ordered_stream_sha256"] == second["ordered_stream_sha256"]


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong/v9"), ("matching_policy", "normalize_labels"), ("record_kind", "logical_relation"),
    ("semantic_identity_verified", True), ("endpoint_counts_may_overlap", 1), ("extra", "ignored"),
    ("edge_rows", True), ("edge_rows", -1), ("exclusive_edge_dispositions", {}),
    ("missing_endpoint_values", None),
    ("nonempty_dangling_references", {"source": True, "target": 1, "either": 1}),
    ("ambiguous_declared_references", {"source": -1, "target": 3, "either": 2}),
])
def test_v2_pinned_bindings_still_validate_closed_semantics_and_counter_types(source, monkeypatch, field, value):
    path, request = source
    result = intake.census_parquet(path, endpoint_details=True, **request)
    result["endpoint_integrity"][field] = value
    result["census_sha256"] = intake._digest({k: v for k, v in result.items() if k != "census_sha256"})
    def forbidden(*args):
        pytest.fail("binding validation must not decode rows")
    monkeypatch.setattr(intake, "_rows", forbidden)
    # A matching independently supplied digest does not make invalid schema or
    # claimed semantic authority admissible to the binding-only interface.
    with pytest.raises(intake.EntityIndexIntakeError):
        intake.validate_census_bindings(result, path, endpoint_details=True,
            expected_census_sha256=result["census_sha256"], **request)

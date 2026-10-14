"""Real Parquet, external pins and lossless candidate-only graph exchange."""
import hashlib
import json
import os
import struct
import subprocess
import sys
from copy import deepcopy

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ipfs_datasets_py.logic.autoformal import corpus_graph as graph
from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange as exchange
from ipfs_datasets_py.logic.autoformal.corpus_contracts import CorpusContractError, seal_record
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def evidence(label):
    return seal_record({"schema": "test/opaque-evidence/v1", "label": label})["record_cid"]


def node(kind, label, **kwargs):
    if kind in graph.ASSERTIONS:
        kwargs.setdefault("source_occurrence_cids", [evidence("physical occurrence")])
        kwargs.setdefault("interpretation_cids", [evidence("interpretation")])
    return graph.build_node(node_type=kind, stable_id=label, content_cid=evidence(label), **kwargs)


def snapshot():
    norm = node("norm_assertion", "rule A", alternative_group_id="reading", alternative_id="A")
    actor = node("entity", "Secretary")
    condition = node("expression", "condition", scope_cid=evidence("scoped subsection"))
    edges = [graph.build_edge(src_cid=norm["record_cid"], dst_cid=actor["record_cid"],
                relation="HAS_ACTOR", ordinal=index, evidence_cids=[evidence("binding")]) for index in (0, 1)]
    edges.append(graph.build_edge(src_cid=norm["record_cid"], dst_cid=condition["record_cid"],
        relation="HAS_CONDITION", ordinal=0, evidence_cids=[evidence("attachment")]))
    return graph.build_graph_snapshot([norm, actor, condition], edges)


def pin(manifest):
    return hashlib.sha256(canonical_dag_json_bytes(manifest)).hexdigest()


def bundle(tmp_path, value=None):
    path = tmp_path / "bundle"
    value = snapshot() if value is None else value
    manifest = exchange.write_graph_bundle(value, path)
    return path, manifest, value


def read(path, manifest):
    return exchange.load_graph_bundle(path, expected_manifest_sha256=pin(manifest))


def reseal(record):
    return seal_record({key: value for key, value in record.items() if key not in {"record_cid", "cid_scope"}})


def replace_file(path, manifest, name, raw, *, snapshot_cid=None):
    (path / name).write_bytes(raw)
    changed = deepcopy(manifest)
    changed["files"][name].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    if snapshot_cid is not None:
        changed["snapshot_cid"] = snapshot_cid
    changed = reseal(changed)
    (path / exchange.MANIFEST_FILE).write_bytes(canonical_dag_json_bytes(changed))
    return changed


def replace_table(path, manifest, name, table, *, compression="NONE"):
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression=compression, use_dictionary=False, write_statistics=False,
                   store_schema=False)
    return replace_file(path, manifest, name, output.getvalue().to_pybytes())


def test_public_exchange_import_does_not_load_pyarrow_or_models():
    program = '''
import sys
from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange
assert not any(name.split('.')[0] in {'pyarrow', 'torch', 'transformers'} for name in sys.modules)
assert corpus_graph_exchange.FORMAT_PROFILE == 'candidate-graph-parquet-with-canonical-records/v1'
'''
    subprocess.run([sys.executable, "-c", program], check=True, capture_output=True, text=True)


def test_real_parquet_roundtrip_preserves_exact_snapshot_and_readable_columns(tmp_path):
    value = snapshot()
    before = deepcopy(value)
    path, manifest, _ = bundle(tmp_path, value)
    loaded = read(path, manifest)
    assert loaded == {"manifest": manifest, "snapshot": before}
    assert value == before
    assert (path / "snapshot.json").read_bytes() == canonical_dag_json_bytes(before)
    assert (path / "manifest.json").read_bytes() == canonical_dag_json_bytes(manifest)
    nodes = pq.read_table(path / "nodes.parquet").to_pylist()
    edges = pq.read_table(path / "edges.parquet").to_pylist()
    assert {row["stable_id"] for row in nodes} == {"rule A", "Secretary", "condition"}
    assert all(row["src_cid"] and row["dst_cid"] for row in edges)
    assert [json.loads(row["record_json"]) for row in nodes] == before["nodes"]
    assert [json.loads(row["record_json"]) for row in edges] == before["edges"]
    assert sorted(row["ordinal"] for row in edges if row["relation"] == "HAS_ACTOR") == [0, 1]
    assert manifest["view"] == "candidate"
    assert all(manifest[key] is False for key in exchange._FLAGS)
    loaded["snapshot"]["nodes"][0]["stable_id"] = "mutated result"
    assert value == before


def test_zero_edge_table_retains_explicit_schema(tmp_path):
    value = graph.build_graph_snapshot([node("entity", "unresolved entity")], [])
    path, manifest, _ = bundle(tmp_path, value)
    table = pq.read_table(path / "edges.parquet")
    assert table.num_rows == manifest["edge_count"] == 0
    assert table.schema.names == list(exchange._EDGE_COLUMNS)
    assert read(path, manifest)["snapshot"] == value


def test_external_manifest_sha_is_required_and_wrong_pin_refuses(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    with pytest.raises(TypeError):
        exchange.load_graph_bundle(path)
    with pytest.raises(CorpusContractError):
        exchange.load_graph_bundle(path, expected_manifest_sha256="0" * 64)
    with pytest.raises(CorpusContractError):
        exchange.load_graph_bundle(path, expected_manifest_sha256=True)
    assert read(path, manifest)["manifest"] == manifest


@pytest.mark.parametrize("name", list(exchange.PAYLOAD_FILES))
def test_payload_tampering_refuses_before_payload_parsing(tmp_path, name, monkeypatch):
    path, manifest, _ = bundle(tmp_path)
    raw = (path / name).read_bytes()
    (path / name).write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    def forbidden():
        raise AssertionError("Parquet parser must not run before all payload hashes pass")
    monkeypatch.setattr(exchange, "_arrow", forbidden)
    with pytest.raises(CorpusContractError, match="SHA256 differs"):
        read(path, manifest)


def test_existing_directory_is_never_overwritten(tmp_path):
    path, manifest, value = bundle(tmp_path)
    original = {file.name: file.read_bytes() for file in path.iterdir()}
    with pytest.raises(CorpusContractError):
        exchange.write_graph_bundle(value, path)
    assert {file.name: file.read_bytes() for file in path.iterdir()} == original
    assert read(path, manifest)["snapshot"] == value


@pytest.mark.parametrize("missing", list(exchange.BUNDLE_FILES))
def test_incomplete_bundle_refuses(tmp_path, missing):
    path, manifest, _ = bundle(tmp_path)
    (path / missing).unlink()
    with pytest.raises(CorpusContractError, match="incomplete bundle"):
        read(path, manifest)


def test_unknown_filename_is_not_silently_ignored(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    (path / "extra.json").write_text("{}")
    with pytest.raises(CorpusContractError, match="unknown filenames"):
        read(path, manifest)


def test_directory_parent_and_file_symlinks_refuse(tmp_path):
    path, manifest, value = bundle(tmp_path)
    directory_alias = tmp_path / "alias"
    directory_alias.symlink_to(path, target_is_directory=True)
    with pytest.raises(CorpusContractError):
        read(directory_alias, manifest)
    with pytest.raises(CorpusContractError):
        exchange.write_graph_bundle(value, directory_alias / "child")
    original = (path / "nodes.parquet").read_bytes()
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(original)
    (path / "nodes.parquet").unlink()
    (path / "nodes.parquet").symlink_to(outside)
    with pytest.raises(CorpusContractError):
        read(path, manifest)


def test_traversal_refuses_even_when_it_resolves_to_existing_bundle(tmp_path):
    path, manifest, value = bundle(tmp_path)
    traversal = path / ".." / "bundle"
    with pytest.raises(CorpusContractError, match="traversal"):
        read(traversal, manifest)
    with pytest.raises(CorpusContractError, match="traversal"):
        exchange.write_graph_bundle(value, tmp_path / ".." / "new-bundle")


def test_nonregular_payload_refuses_without_blocking(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    (path / "nodes.parquet").unlink()
    os.mkfifo(path / "nodes.parquet")
    with pytest.raises(CorpusContractError, match="regular bundle file"):
        read(path, manifest)


def test_rebound_projection_disagreement_is_rejected(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    values = table.to_pylist()
    values[0]["stable_id"] = "a different projection"
    changed = replace_table(path, manifest, "nodes.parquet", pa.Table.from_pylist(values, schema=table.schema))
    with pytest.raises(CorpusContractError, match="projection disagrees"):
        read(path, changed)


@pytest.mark.parametrize("kind", ["extra_column", "wrong_type", "object_rows"])
def test_unknown_or_object_parquet_schema_refuses_before_row_conversion(tmp_path, kind):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    if kind == "extra_column":
        table = table.append_column("injected", pa.array(["x"] * table.num_rows))
    elif kind == "wrong_type":
        index = table.schema.get_field_index("stable_id")
        table = table.set_column(index, "stable_id", pa.array([1] * table.num_rows))
    else:
        index = table.schema.get_field_index("record_json")
        table = table.set_column(index, "record_json", pa.array([{"nested": "object"}] * table.num_rows))
    changed = replace_table(path, manifest, "nodes.parquet", table)
    with pytest.raises(CorpusContractError, match="incompatible Parquet columns"):
        read(path, changed)


def test_compressed_parquet_bomb_profile_is_refused_before_decoding(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    changed = replace_table(path, manifest, "nodes.parquet", table, compression="zstd")
    with pytest.raises(CorpusContractError, match="compressed/dictionary/nonplain"):
        read(path, changed)


def test_dictionary_profile_is_refused(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="NONE", use_dictionary=True, store_schema=False)
    changed = replace_file(path, manifest, "nodes.parquet", output.getvalue().to_pybytes())
    with pytest.raises(CorpusContractError, match="compressed/dictionary/nonplain"):
        read(path, changed)


def test_noncanonical_record_json_cannot_replace_canonical_records(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    rows = table.to_pylist()
    rows[0]["record_json"] = json.dumps(json.loads(rows[0]["record_json"]), indent=2)
    changed = replace_table(path, manifest, "nodes.parquet", pa.Table.from_pylist(rows, schema=table.schema))
    with pytest.raises(CorpusContractError, match="projection disagrees"):
        read(path, changed)


def test_rebound_duplicate_ids_cannot_reconstruct_snapshot(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    rows = table.to_pylist()
    rows[1] = deepcopy(rows[0])
    changed = replace_table(path, manifest, "nodes.parquet", pa.Table.from_pylist(rows, schema=table.schema))
    with pytest.raises(CorpusContractError, match="duplicate graph node"):
        read(path, changed)


def test_rebound_dangling_endpoint_refuses(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "edges.parquet")
    rows = table.to_pylist()
    record = json.loads(rows[0]["record_json"])
    record["dst_cid"] = evidence("not in the graph")
    record = reseal(record)
    rows[0].update(record_cid=record["record_cid"], dst_cid=record["dst_cid"],
                   record_json=canonical_dag_json_bytes(record).decode())
    changed = replace_table(path, manifest, "edges.parquet", pa.Table.from_pylist(rows, schema=table.schema))
    with pytest.raises(CorpusContractError, match="dangling graph endpoint"):
        read(path, changed)


def test_parquet_record_order_cannot_change_even_with_fresh_file_bindings(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    changed = replace_table(path, manifest, "nodes.parquet", table.take(pa.array(list(reversed(range(table.num_rows))))))
    with pytest.raises(CorpusContractError, match="record order"):
        read(path, changed)


@pytest.mark.parametrize("field", list(exchange._FLAGS))
def test_resealed_manifest_cannot_claim_authority(tmp_path, field):
    path, manifest, _ = bundle(tmp_path)
    changed = deepcopy(manifest)
    changed[field] = True
    changed = reseal(changed)
    (path / "manifest.json").write_bytes(canonical_dag_json_bytes(changed))
    with pytest.raises(CorpusContractError, match="cannot claim authority"):
        read(path, changed)


def test_resealed_snapshot_cannot_claim_review_or_formalization(tmp_path):
    path, manifest, value = bundle(tmp_path)
    changed_snapshot = deepcopy(value)
    changed_snapshot["formalized"] = True
    changed_snapshot = reseal(changed_snapshot)
    changed = replace_file(path, manifest, "snapshot.json", canonical_dag_json_bytes(changed_snapshot),
                           snapshot_cid=changed_snapshot["record_cid"])
    with pytest.raises(CorpusContractError, match="candidate-only"):
        read(path, changed)


def test_manifest_path_injection_and_bool_counts_are_rejected(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    for edit in (lambda value: value["files"].update({"../outside": value["files"]["nodes.parquet"]}),
                 lambda value: value.update(node_count=True),
                 lambda value: value.update(format_profile="another-profile/v1")):
        changed = deepcopy(manifest)
        edit(changed)
        changed = reseal(changed)
        (path / "manifest.json").write_bytes(canonical_dag_json_bytes(changed))
        with pytest.raises(CorpusContractError):
            read(path, changed)


def test_metadata_row_count_mismatch_is_rejected(tmp_path):
    path, manifest, _ = bundle(tmp_path)
    table = pq.read_table(path / "nodes.parquet")
    changed = replace_table(path, manifest, "nodes.parquet", table.slice(0, 1))
    with pytest.raises(CorpusContractError, match="row/group count"):
        read(path, changed)


def test_footer_and_decoded_budgets_precede_full_read(tmp_path, monkeypatch):
    path, manifest, _ = bundle(tmp_path)
    raw = (path / "nodes.parquet").read_bytes()
    malicious = raw[:-8] + struct.pack("<I", exchange.MAX_FOOTER_BYTES + 1) + raw[-4:]
    changed = replace_file(path, manifest, "nodes.parquet", malicious)
    with pytest.raises(CorpusContractError, match="footer exceeds"):
        read(path, changed)
    changed = replace_file(path, changed, "nodes.parquet", raw)
    monkeypatch.setattr(exchange, "MAX_DECODED_BYTES", 1)
    with pytest.raises(CorpusContractError, match="decoded budget"):
        read(path, changed)


def test_file_and_manifest_limits_are_enforced(tmp_path, monkeypatch):
    path, manifest, _ = bundle(tmp_path)
    monkeypatch.setattr(exchange, "MAX_PARQUET_BYTES", 1)
    with pytest.raises(CorpusContractError, match="size"):
        read(path, manifest)
    monkeypatch.setattr(exchange, "MAX_MANIFEST_BYTES", 1)
    with pytest.raises(CorpusContractError, match="bounded regular"):
        read(path, manifest)


def test_writer_does_not_commit_manifest_before_successful_readback(tmp_path, monkeypatch):
    def failure(*_args):
        raise CorpusContractError("injected readback failure")
    monkeypatch.setattr(exchange, "_read_content", failure)
    path = tmp_path / "failed-attempt"
    with pytest.raises(CorpusContractError, match="readback failure"):
        exchange.write_graph_bundle(snapshot(), path)
    assert not (path / "manifest.json").exists()
    assert (path / "nodes.parquet").exists()


def test_writer_removes_only_its_manifest_if_final_readback_fails(tmp_path, monkeypatch):
    def failure(*_args, **_kwargs):
        raise CorpusContractError("injected final readback failure")
    monkeypatch.setattr(exchange, "load_graph_bundle", failure)
    path = tmp_path / "failed-attempt"
    with pytest.raises(CorpusContractError, match="final readback failure"):
        exchange.write_graph_bundle(snapshot(), path)
    assert not (path / "manifest.json").exists()
    assert (path / "snapshot.json").exists()

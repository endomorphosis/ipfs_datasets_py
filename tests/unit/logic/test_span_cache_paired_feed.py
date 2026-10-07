"""Real typed paired bytes exercise the feed; remote transport is inert."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal.span_cache_feed import (
    FeedError, HubExchangeClient, SpanCacheFeed, paired_source_records,
)
from tests.unit.logic.test_span_cache_feed import A, B, Remote, make_bundle, open_feed


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_row(span="paired-source", *, text="The agency shall retain the record.", release="source-release", guided=True):
    rule = {"modality": "Obligation", "actor": "agency", "action": "retain", "object": "record"}
    row = {"source_span_id": span, "text": text, "legal_id": "usc:us:5:8410", "release_id": release,
           "compiler_result": {"compiler_status": "compiled", "rules": [rule], "components": [],
                               "compilation_complete": True, "decompiled": text, "roundtrip": True},
           "autoencoder_observation": {"raw_decoder": {"embedding": [0.125] * 8},
               "embedding_representation": {"embedding_model": "mock:stable-sha256/8", "semantic_embeddings": False}}}
    if guided:
        row["model_formal_outputs"] = [{"family": "typed_deontic", "format": paired.FORMAL_FORMAT,
            "payload": rule, "origin": "autoencoder_guided_compiler", "independent": False,
            "target_conditioned": True, "syntax_status": "not_checked"}]
        row["model_formal_output_provenance"] = {"source_text_sha256": digest(text.encode()),
            "model_identity": "diagnostic:test", "complete": True, "origin": "autoencoder_guided_compiler"}
    return row


def build_fixture(version, *, label="paired-one", rows=None, receipt_extra=""):
    rows = rows or [source_row()]
    receipt = {"rows": [{"source_span_id": row["source_span_id"], "text": row["text"]} for row in rows],
               "test_only_evidence": receipt_extra}
    bundle = paired.build_paired_census(rows, agent_id=label, code_identity="synthetic:test",
                                       model_identity="diagnostic:test", original_receipt=receipt)
    if version == 1:
        aliases = {}
        bundle["schema_version"] = paired.LEGACY_SCHEMA
        for row in bundle["paired_spans"]:
            old = row["observation_id"]
            row["schema_version"] = paired.LEGACY_SCHEMA
            row["autoencoder"].pop("learned_formula_capture_verified")
            row["autoencoder"].pop("learned_formula_observation_artifact_sha256")
            row["comparison"] = paired._compare_formal_outputs_v1(row["autoencoder"], row["compiler"])
            rehash_row(row)
            aliases[old] = row["observation_id"]
        for goal in bundle["goals"]:
            goal["observation_ids"] = [aliases[item] for item in goal["observation_ids"]]
    return bundle


def rehash_row(row):
    body = {key: value for key, value in row.items() if key != "observation_id"}
    body["goal_ids"] = []
    row["observation_id"] = digest(encoded(body))


def serialize_fixture(tmp_path, bundle, *, version=2, one_digest=False):
    """Historical v1 fixture serialization uses its exact native Arrow schema."""
    label = bundle["agent_id"]
    root = tmp_path / (label + "-v" + str(version))
    root.mkdir(parents=True, exist_ok=True)
    prefix = "autoformal/uscode/paired-v" + str(version)
    tables, files = {}, {}
    for kind in paired.TABLE_NAMES:
        table = pa.Table.from_pylist(bundle[kind], schema=paired.arrow_schemas(bundle["schema_version"])[kind])
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd", row_group_size=32)
        raw = sink.getvalue().to_pybytes()
        sha = digest(raw)
        filename = kind + "-" + ("" if one_digest else "1" * 64 + "-") + sha + ".parquet"
        path = root / filename
        path.write_bytes(raw)
        name = f"{prefix}/{kind}/{label}/{filename}"
        files[name] = path
        tables[kind] = {"path_in_repo": name, "filename": filename, "sha256": sha,
                        "bytes": len(raw), "row_count": len(bundle[kind])}
    manifest = {"schema": "uscode-paired-span-bundle/v" + str(version),
        "repository_id": paired.REPOSITORY, "agent_id": label, "tables": tables,
        "original_receipt_artifact_sha256": bundle["original_receipt_artifact_sha256"],
        "admitted": False, "formalized": False, "enqueued": False}
    fp = digest(encoded(manifest))
    name = f"{prefix}/manifests/{label}/manifest-{fp}.json"
    manifest.update(fingerprint=fp, path_in_repo=name)
    raw = encoded(manifest)
    path = root / Path(name).name
    path.write_bytes(raw)
    files[name] = path
    entry = {"path": name, "type": "file", "size": len(raw),
             "oid": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    return entry, files, manifest


def paired_remote(tmp_path, version=2, **kwargs):
    bundle = build_fixture(version, **kwargs)
    entry, files, manifest = serialize_fixture(tmp_path, bundle, version=version, one_digest=version == 1)
    return Remote([entry], files), bundle, entry, manifest


@pytest.mark.parametrize("version", [1, 2])
def test_paired_delivery_preserves_source_compiler_provenance_and_artifact_refs(tmp_path, version):
    remote, fixture, entry, manifest = paired_remote(tmp_path, version, receipt_extra="complete-receipt")
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["errors"] == []
        record = result["records"][0]
        row = fixture["paired_spans"][0]
        assert record["text"] == row["source"]["text"]
        assert record["source_revision"] == row["source"]["revision"]
        assert record["sample"]["text"] == row["source"]["text"]
        assert "embedding_vector" not in record["sample"]
        observation = record["observations"][0]
        assert observation["paired_row"] == row
        assert observation["paired_row"]["autoencoder"]["raw_vector"] == [0.125] * 8
        assert observation["paired_row"]["comparison"]["status"] == "diagnostic_agree"
        assert observation["artifact_references"][0]["artifact_sha256"] == fixture["artifacts"][0]["artifact_sha256"]
        loaded = paired.load_paired_census_bundle(result["new_bundles"][0]["manifest_path"])
        assert paired.decode_artifact(loaded["artifacts"][0]) == paired.decode_artifact(fixture["artifacts"][0])
        assert observation["artifact_table"]["sha256"] == manifest["tables"]["artifacts"]["sha256"]
        assert all(record[k] is False for k in ["admitted", "formalized", "qualified", "proof_authority", "source_authority_authenticated"])
        assert result["weights_downloaded"] is result["training_executed"] is result["enqueued"] is False
        assert len(remote.calls) == 4
        assert feed.poll_once()["records"] == result["records"]
        assert len(remote.calls) == 4
    with open_feed(tmp_path, remote) as feed:
        resumed = feed.poll_once()
        assert resumed["records"] == result["records"]
        fp = resumed["new_bundles"][0]["fingerprint"]
        with pytest.raises(FeedError, match="acknowledgement"):
            feed.acknowledge(entry["path"], fingerprint="wrong")
        feed.acknowledge(entry["path"], fingerprint=fp)
        feed.acknowledge(entry["path"], fingerprint=fp)
        assert feed.poll_once()["counts"] == {"acknowledged": 1}


def test_mixed_legacy_v1_v2_tree_preserves_each_observation(tmp_path):
    legacy, lf = make_bundle(tmp_path)
    r1, _, e1, _ = paired_remote(tmp_path, 1, label="paired-one")
    r2, _, e2, _ = paired_remote(tmp_path, 2, label="paired-two")
    remote = Remote([legacy, e1, e2], {**lf, **r1.files[A], **r2.files[A]})
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["errors"] == [] and len(result["new_bundles"]) == 3
        assert len(result["records"]) == 2
        paired_record = next(row for row in result["records"] if "source_revision" in row)
        assert len(paired_record["observations"]) == 2
        assert len(paired_record["provenance"]["observations"]) == 2
        assert {o["paired_schema"] for o in paired_record["observations"]} == {paired.SCHEMA, paired.LEGACY_SCHEMA}


def test_paired_identity_preserves_source_generation_and_machine_shards(tmp_path):
    r1, _, e1, _ = paired_remote(tmp_path, label="first", rows=[source_row(release="old")])
    r2, _, e2, _ = paired_remote(tmp_path, label="second", rows=[source_row(release="new")])
    remote = Remote([e1, e2], {**r1.files[A], **r2.files[A]})
    records = []
    for index in range(3):
        with open_feed(tmp_path / str(index), remote, shard_count=3, shard_index=index) as feed:
            records.extend(feed.poll_once()["records"])
    assert len(records) == 2 and len({r["record_id"] for r in records}) == 2
    assert {r["source_revision"] for r in records} == {"old", "new"}


@pytest.mark.parametrize("version", [1, 2])
def test_pending_paired_tables_recover_at_original_commit_when_head_moves(tmp_path, version):
    remote, _, entry, manifest = paired_remote(tmp_path, version)
    table = manifest["tables"]["artifacts"]["path_in_repo"]
    remote.fail.add(table)
    with open_feed(tmp_path, remote) as feed:
        failed = feed.poll_once()
        assert failed["records"] == [] and failed["counts"] == {"pending": 1}
        assert failed["discovery"]["complete"] is True
        with pytest.raises(FeedError):
            feed.acknowledge(entry["path"], fingerprint=manifest["fingerprint"])
    remote.head = B
    remote.fail.clear()
    with open_feed(tmp_path, remote) as feed:
        recovered = feed.poll_once()
        assert recovered["errors"] == [] and recovered["new_bundles"][0]["revision"] == A
        assert all(call[0] == A for call in remote.calls)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("mutation", ["source_hash", "agent", "model", "repository", "schema", "comparison", "authority"])
def test_rehashed_paired_rows_cannot_change_source_producer_comparison_or_authority(tmp_path, version, mutation):
    bundle = build_fixture(version)
    row = bundle["paired_spans"][0]
    if mutation == "source_hash": row["source"]["text_sha256"] = "0" * 64
    elif mutation == "agent": row["provenance"]["agent_id"] = "other-agent"
    elif mutation == "model": row["autoencoder"]["model_identity"] = "other-model"
    elif mutation == "repository": row["repository_id"] = "other/repository"
    elif mutation == "schema": row["schema_version"] = "unknown/v9"
    elif mutation == "comparison": row["comparison"]["agrees"] = False
    else: row["admitted"] = True
    rehash_row(row)
    entry, files, _ = serialize_fixture(tmp_path, bundle, version=version)
    with open_feed(tmp_path, Remote([entry], files)) as feed:
        result = feed.poll_once()
        assert result["records"] == [] and result["counts"] == {"pending": 1}
        assert result["errors"][0]["phase"] == "bundle"


def test_v2_forged_learned_capture_cannot_be_delivered(tmp_path):
    bundle = build_fixture(2)
    row = bundle["paired_spans"][0]
    row["autoencoder"].update(learned_formula_capture_verified=True,
                             learned_formula_observation_artifact_sha256="f" * 64)
    rehash_row(row)
    entry, files, _ = serialize_fixture(tmp_path, bundle)
    with open_feed(tmp_path, Remote([entry], files)) as feed:
        result = feed.poll_once()
        assert result["records"] == []
        assert "capture artifact" in result["errors"][0]["message"]


@pytest.mark.parametrize("version", [1, 2])
def test_paired_capability_goals_remain_descriptive_and_source_bound(tmp_path, version):
    remote, fixture, _, _ = paired_remote(tmp_path, version, rows=[source_row(guided=False)])
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["errors"] == []
        goals = result["records"][0]["observations"][0]["goal_rows"]
        assert goals == fixture["goals"]
        assert goals[0]["record_kind"] == "capability_gap"
        assert goals[0]["enqueued"] is goals[0]["admitted"] is False


@pytest.mark.parametrize("setting", [{"max_download_files": 3}, {"max_ready_bytes": 100}, {"max_bundle_bytes": 100}])
def test_paired_limits_retain_pending_work_and_retry(tmp_path, setting):
    remote, _, _, _ = paired_remote(tmp_path)
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once(**setting)
        assert result["records"] == [] and result["counts"] == {"pending": 1}
        assert feed.poll_once()["errors"] == []


def test_aggregate_artifact_expansion_is_bounded_before_full_loader(tmp_path, monkeypatch):
    remote, _, _, _ = paired_remote(tmp_path, receipt_extra="x" * 100_000)
    def forbidden(*args, **kwargs):
        raise AssertionError("expanded loader must not run after preflight exceeds budget")
    monkeypatch.setattr(paired, "load_paired_census_bundle", forbidden)
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once(max_ready_bytes=20_000)
        assert result["records"] == []
        assert "artifact expansion exceeds ready bound" in result["errors"][0]["message"]


def test_multi_bundle_ready_budget_does_not_silently_drop_pending_bundle(tmp_path):
    r1, _, e1, _ = paired_remote(tmp_path, label="first")
    r2, _, e2, _ = paired_remote(tmp_path, label="second", rows=[source_row(span="second")])
    remote = Remote([e1, e2], {**r1.files[A], **r2.files[A]})
    with open_feed(tmp_path, remote) as feed:
        first = feed.poll_once(max_bundles=1)
        measured = first["decoded_bytes"]
        result = feed.poll_once(max_ready_bytes=measured + 100)
        assert len(result["new_bundles"]) == 1 and result["counts"] == {"ready": 1, "pending": 1}
        assert result["decoded_bytes"] <= measured + 100
        assert len(feed.poll_once()["new_bundles"]) == 2


@pytest.mark.parametrize("version", [1, 2])
def test_tampered_ready_table_rejects_and_can_redownload(tmp_path, version):
    remote, _, _, _ = paired_remote(tmp_path, version)
    with open_feed(tmp_path, remote) as feed:
        first = feed.poll_once()
        Path(first["new_bundles"][0]["table_paths"]["artifacts"]).write_bytes(b"bad")
        failed = feed.poll_once()
        assert failed["records"] == [] and failed["download_file_attempts"] == 0
        assert failed["counts"] == {"pending": 1}
        assert feed.poll_once()["errors"] == []


def test_completed_v1_feed_migrates_once_without_losing_old_ack_or_pending_revision(tmp_path):
    legacy, files = make_bundle(tmp_path)
    r, _, new, _ = paired_remote(tmp_path)
    remote = Remote([legacy], files)
    with open_feed(tmp_path, remote) as feed:
        old = feed.poll_once()
        feed.acknowledge(legacy["path"], fingerprint=old["new_bundles"][0]["fingerprint"])
    import duckdb
    cx = duckdb.connect(str(tmp_path / "feed.duckdb"))
    config = json.loads(cx.execute("SELECT config FROM feed_meta").fetchone()[0])
    config["schema"] = "span-cache-incremental-feed/v1"
    config.pop("discovery_root")
    cx.execute("UPDATE feed_meta SET config=?", [encoded(config).decode()])
    cx.close()
    remote.head = B
    remote.entries[A] = [legacy, new]
    remote.files[A] = {**files, **r.files[A]}
    remote.entries[B] = [legacy, new]
    remote.files[B] = remote.files[A]
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["errors"] == [] and result["discovery"]["revision"] == A
        assert result["counts"] == {"acknowledged": 1, "ready": 1}
        assert result["new_bundles"][0]["revision"] == A
    with open_feed(tmp_path, remote) as feed:
        assert feed.poll_once()["discovery"]["revision"] == B


def test_hub_discovery_uses_broad_pinned_root_and_strict_cursor(monkeypatch):
    import huggingface_hub.utils
    calls = []
    class Response:
        status_code = 200
        links = {}
        headers = {}
        request = SimpleNamespace(url="fixture")
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, _): yield b"[]"
    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs["params"]["recursive"] is True
            return Response()
    monkeypatch.setattr(huggingface_hub.utils, "get_session", lambda: Session())
    api = SimpleNamespace(endpoint="https://huggingface.co", _build_hf_headers=lambda: {})
    client = HubExchangeClient(api=api)
    client.list_page(paired.REPOSITORY, A, "", max_entries=100)
    assert calls[0].endswith("/tree/" + A + "/autoformal%2Fuscode")
    with pytest.raises(FeedError, match="pagination cursor"):
        client.list_page(paired.REPOSITORY, A, calls[0].replace(A, B), max_entries=100)


@pytest.mark.parametrize("name", ["weights/model.bin", "autoformal/uscode/paired-v2/artifacts/agent/model.parquet",
    "autoformal/uscode/paired-v3/manifests/agent/manifest-" + "a" * 64 + ".json",
    "autoformal/uscode/paired-v2/../weights/model.parquet"])
def test_hub_paired_paths_cannot_redirect_to_weights_or_unknown_namespaces(name):
    client = HubExchangeClient(api=SimpleNamespace(endpoint="https://huggingface.co"))
    with pytest.raises(FeedError):
        client.fetch(paired.REPOSITORY, A, name, Path("unused"), max_bytes=10)


def test_long_unicode_paired_source_is_preserved_exactly(tmp_path):
    text = "The agency shall retain café records. " * 1000
    remote, _, _, _ = paired_remote(tmp_path, rows=[source_row(text=text)])
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["errors"] == []
        assert result["records"][0]["text"] == text
        assert result["records"][0]["source_text_sha256"] == digest(text.encode())
        assert len(text.encode()) > 32 * 1024


def test_real_v2_exporter_sanitized_namespace_preserves_original_agent(tmp_path):
    bundle = build_fixture(2, label="publisher.agent")
    written = paired.write_paired_census_bundle(bundle, tmp_path / "native-export")
    value = json.loads(Path(written["manifest"]["path"]).read_bytes())
    raw = Path(written["manifest"]["path"]).read_bytes()
    entry = {"path": value["path_in_repo"], "type": "file", "size": len(raw),
             "oid": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    files = {written[kind]["path_in_repo"]: Path(written[kind]["path"]) for kind in paired.TABLE_NAMES}
    files[entry["path"]] = Path(written["manifest"]["path"])
    assert "/publisher-agent/" in entry["path"]
    with open_feed(tmp_path, Remote([entry], files)) as feed:
        result = feed.poll_once()
        assert result["errors"] == []
        assert result["records"][0]["observations"][0]["paired_row"]["provenance"]["agent_id"] == "publisher.agent"


@pytest.mark.parametrize("mutation", ["weights", "version", "kind", "agent", "digest", "extra_table", "authority", "schema"])
def test_paired_manifest_refuses_redirect_or_authority_before_table_download(tmp_path, mutation):
    remote, _, old_entry, value = paired_remote(tmp_path)
    item = value["tables"]["paired_spans"]
    if mutation == "weights": item["path_in_repo"] = "autoformal/uscode/weights/model.parquet"
    elif mutation == "version": item["path_in_repo"] = item["path_in_repo"].replace("paired-v2", "paired-v1")
    elif mutation == "kind": item["path_in_repo"] = item["path_in_repo"].replace("/paired_spans/", "/artifacts/")
    elif mutation == "agent": item["path_in_repo"] = item["path_in_repo"].replace("/paired-one/", "/other/")
    elif mutation == "digest": item["sha256"] = "f" * 64
    elif mutation == "extra_table": value["tables"]["weights"] = deepcopy(item)
    elif mutation == "authority": value["admitted"] = True
    else: value["schema"] = "uscode-paired-span-bundle/v1"
    body = {k: v for k, v in value.items() if k not in {"fingerprint", "path_in_repo"}}
    fp = digest(encoded(body))
    name = str(Path(old_entry["path"]).with_name("manifest-" + fp + ".json"))
    value.update(fingerprint=fp, path_in_repo=name)
    raw = encoded(value)
    old_path = remote.files[A].pop(old_entry["path"])
    old_path.write_bytes(raw)
    remote.files[A][name] = old_path
    remote.entries[A] = [{"path": name, "type": "file", "size": len(raw),
                          "oid": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}]
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["records"] == [] and result["counts"] == {"pending": 1}
        assert [call[1] for call in remote.calls] == [name]


def test_paired_ready_repository_parent_alias_is_refused(tmp_path):
    remote, _, _, _ = paired_remote(tmp_path)
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        table = Path(result["new_bundles"][0]["table_paths"]["artifacts"])
        old_parent = table.parent
        outside = tmp_path / "aliased-tables"
        old_parent.rename(outside)
        old_parent.symlink_to(outside, target_is_directory=True)
        failed = feed.poll_once()
        assert failed["records"] == []
        assert "filesystem alias" in failed["errors"][0]["message"]

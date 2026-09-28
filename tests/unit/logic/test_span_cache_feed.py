"""Durable feed tests use real exchange bytes and isolated local DuckDB owners."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.logic.autoformal.span_cache_exchange import publish_compiled_exchange
from ipfs_datasets_py.logic.autoformal.span_cache_feed import FeedError, SpanCacheFeed, source_records

A, B = "a" * 40, "b" * 40


def make_bundle(tmp_path, label="one", *, text="The agency shall retain records.", span="source-1"):
    receipt = publish_compiled_exchange([{
        "source_span_id": span, "legal_id": "usc:us:5:8410", "text": text,
        "autoencoder_text": "The duty was omitted.", "decompiled": "", "agrees": False,
        "cosine_similarity": 0.2, "cross_entropy_loss": 1.0, "reconstruction_loss": 0.1,
        "source_provenance": {"source": "fixture retained source", "label": label},
    }], tmp_path / label, upload=False, agent_id=label, code_identity="synthetic:test")
    manifest = Path(receipt["manifest"]["path"])
    value = json.loads(manifest.read_text())
    raw = manifest.read_bytes()
    files = {value["path_in_repo"]: manifest,
             value["census"]["path_in_repo"]: Path(receipt["census"]["path"]),
             value["goals"]["path_in_repo"]: Path(receipt["goals"]["path"])}
    entry = {"path": value["path_in_repo"], "type": "file", "size": len(raw),
             "oid": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    return entry, files


class Remote:
    def __init__(self, entries, files):
        self.head = A
        self.entries = {A: entries, B: entries}
        self.files = {A: files, B: files}
        self.calls = []
        self.fail = set()
        self.offline = False

    def resolve(self, repo, revision):
        if self.offline:
            raise OSError("offline")
        return self.head

    def list_page(self, repo, revision, cursor, *, max_entries):
        start = int(cursor or 0)
        selected = self.entries[revision][start:start + max_entries]
        end = start + len(selected)
        return selected, str(end) if end < len(self.entries[revision]) else ""

    def fetch(self, repo, revision, filename, directory, *, max_bytes):
        self.calls.append((revision, filename, max_bytes))
        if filename in self.fail:
            raise OSError("temporary failure")
        source = self.files[revision][filename]
        assert source.stat().st_size <= max_bytes
        target = directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target


def open_feed(tmp_path, remote, **kwargs):
    return SpanCacheFeed(tmp_path / "feed.duckdb", tmp_path / "artifacts", client=remote, **kwargs)


def test_verified_delivery_repeats_until_durable_ack_and_reopens(tmp_path):
    entry, files = make_bundle(tmp_path)
    remote = Remote([entry], files)
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["errors"] == [] and len(result["records"]) == 1
        record = result["records"][0]
        assert record["sample"] == {"title": "5", "section": "8410", "text": "The agency shall retain records.", "citation": "usc:us:5:8410"}
        assert record["observations"][0]["input"]["source_provenance"]["label"] == "one"
        assert record["admitted"] is False and record["source_authority_authenticated"] is False
        assert result["weights_downloaded"] is False and result["training_executed"] is False
        assert len(remote.calls) == 3
        again = feed.poll_once()
        assert again["records"] == result["records"] and len(remote.calls) == 3
    with open_feed(tmp_path, remote) as feed:
        resumed = feed.poll_once()
        assert resumed["records"] == result["records"]
        bundle = resumed["new_bundles"][0]
        with pytest.raises(FeedError, match="acknowledgement"):
            feed.acknowledge(entry["path"], fingerprint="incorrect")
        feed.acknowledge(entry["path"], fingerprint=bundle["fingerprint"])
        feed.acknowledge(entry["path"], fingerprint=bundle["fingerprint"])
        assert feed.poll_once()["new_bundles"] == []
    with open_feed(tmp_path, remote) as feed:
        assert feed.poll_once()["counts"] == {"acknowledged": 1}


def test_pending_commit_and_paginated_inventory_survive_moving_head(tmp_path):
    e1, f1 = make_bundle(tmp_path, "one")
    e2, f2 = make_bundle(tmp_path, "two", span="source-2")
    e3, f3 = make_bundle(tmp_path, "three", span="source-3")
    remote = Remote([e1, e2], {**f1, **f2})
    remote.entries[B] = [e1, e2, e3]
    remote.files[B] = {**f1, **f2, **f3}
    remote.fail.add(e1["path"])
    with open_feed(tmp_path, remote) as feed:
        first = feed.poll_once(max_listing_entries=1, max_bundles=1)
        assert first["errors"] and first["discovery"]["complete"] is False
    remote.head = B
    remote.fail.clear()
    with open_feed(tmp_path, remote) as feed:
        second = feed.poll_once(max_listing_entries=1)
        assert second["discovery"]["revision"] == A
        assert {b["revision"] for b in second["new_bundles"]} == {A}
        for b in second["new_bundles"]:
            feed.acknowledge(b["manifest_in_repo"], fingerprint=b["fingerprint"])
        seen = []
        for _ in range(3):
            current = feed.poll_once(max_listing_entries=1)
            seen.extend(current["new_bundles"])
        assert [b["manifest_in_repo"] for b in seen] == [e3["path"]]
        assert seen[0]["revision"] == B


def test_new_observations_deduplicate_same_source_record_and_freeze_machine_shard(tmp_path):
    e1, f1 = make_bundle(tmp_path, "one")
    e2, f2 = make_bundle(tmp_path, "two")
    remote = Remote([e1, e2], {**f1, **f2})
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert len(result["new_bundles"]) == 2 and len(result["records"]) == 1
        assert len(result["records"][0]["observations"]) == 2
        assert len(result["records"][0]["provenance"]["observations"]) == 2
        with pytest.raises(FeedError, match="owner"):
            open_feed(tmp_path, remote)
    with pytest.raises(FeedError, match="configuration"):
        open_feed(tmp_path, remote, shard_count=2, shard_index=1)
    assigned = []
    for i in range(3):
        folder = tmp_path / str(i)
        folder.mkdir()
        with open_feed(folder, remote, shard_count=3, shard_index=i) as feed:
            assigned.extend(feed.poll_once()["records"])
    assert len(assigned) == 1 and assigned[0]["record_id"] == result["records"][0]["record_id"]


def test_offline_poll_returns_retained_verified_inputs(tmp_path):
    entry, files = make_bundle(tmp_path)
    remote = Remote([entry], files)
    with open_feed(tmp_path, remote) as feed:
        original = feed.poll_once()
        remote.offline = True
        result = feed.poll_once()
        assert result["records"] == original["records"]
        assert result["errors"][0]["phase"] == "discovery"
        assert result["download_file_attempts"] == 0


def test_immutable_manifest_conflict_does_not_replace_pending_revision(tmp_path):
    entry, files = make_bundle(tmp_path)
    remote = Remote([entry], files)
    with open_feed(tmp_path, remote) as feed:
        assert not feed.poll_once()["errors"]
        remote.head = B
        remote.entries[B] = [{**entry, "oid": "f" * 40}]
        result = feed.poll_once()
        assert "immutable exchange manifest changed" in result["errors"][0]["message"]
        assert result["new_bundles"][0]["revision"] == A


def test_bounded_download_and_ready_decode_retry(tmp_path):
    entry, files = make_bundle(tmp_path)
    remote = Remote([entry], files)
    with open_feed(tmp_path, remote) as feed:
        first = feed.poll_once(max_download_files=1)
        assert first["records"] == [] and first["download_file_attempts"] == 1
        assert first["counts"] == {"pending": 1}
        second = feed.poll_once(max_ready_bytes=100)
        assert second["records"] == [] and second["counts"] == {"pending": 1}
        third = feed.poll_once()
        assert len(third["records"]) == 1
        assert third["download_file_attempts"] == 3


def test_tampered_retained_bytes_are_rejected_on_replay(tmp_path):
    entry, files = make_bundle(tmp_path)
    remote = Remote([entry], files)
    with open_feed(tmp_path, remote) as feed:
        first = feed.poll_once()
        manifest = Path(first["new_bundles"][0]["manifest_path"])
        value = json.loads(manifest.read_text())
        parquet = tmp_path / "artifacts" / A / value["census"]["path_in_repo"]
        parquet.write_bytes(b"corrupt")
        second = feed.poll_once()
        assert second["records"] == [] and second["errors"]
        assert len(remote.calls) == 3


@pytest.mark.parametrize("setting", [{"max_bundles": 0}, {"max_download_bytes": True}, {"max_listing_entries": -1}])
def test_bounds_fail_before_network(tmp_path, setting):
    remote = Remote([], {})
    with open_feed(tmp_path, remote) as feed:
        with pytest.raises(FeedError):
            feed.poll_once(**setting)
        assert remote.calls == []


def test_foreign_database_rejected(tmp_path):
    import duckdb
    path = tmp_path / "feed.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE unrelated (id INTEGER)")
    con.close()
    with pytest.raises(FeedError, match="foreign"):
        open_feed(tmp_path, Remote([], {}))


def test_tree_rejects_noncommit_resolution_and_oversized_manifest(tmp_path):
    entry, files = make_bundle(tmp_path)
    remote = Remote([entry], files)
    remote.head = "main"
    with open_feed(tmp_path, remote) as feed:
        assert feed.poll_once()["errors"] and remote.calls == []
        remote.head = A
        remote.entries[A] = [{**entry, "size": 2 * 1024 * 1024}]
        assert feed.poll_once()["errors"] and remote.calls == []


def test_manifest_cannot_redirect_downloads_to_weights(tmp_path):
    entry, files = make_bundle(tmp_path)
    path = files[entry["path"]]
    value = json.loads(path.read_text())
    value["census"]["path_in_repo"] = "autoformal/uscode/weights/model.parquet"
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    entry = {**entry, "size": len(raw), "oid": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    remote = Remote([entry], files)
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once()
        assert result["records"] == []
        assert "canonical census/goals" in result["errors"][0]["message"]
        assert [call[1] for call in remote.calls] == [entry["path"]]


def test_failed_download_reserves_its_byte_budget_before_retrying_other_files(tmp_path):
    e1, f1 = make_bundle(tmp_path, "one")
    e2, f2 = make_bundle(tmp_path, "two", span="second")
    remote = Remote([e1, e2], {**f1, **f2})
    remote.fail.update([e1["path"], e2["path"]])
    maximum = max(e1["size"], e2["size"])
    with open_feed(tmp_path, remote) as feed:
        result = feed.poll_once(max_download_bytes=maximum)
        assert result["records"] == []
        assert result["download_byte_budget_used"] <= maximum
        assert sum(call[2] for call in remote.calls) <= maximum
        assert result["downloaded_bytes"] == 0


def test_hub_client_rejects_foreign_pagination_and_weight_paths_before_network():
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.autoformal.span_cache_feed import HubExchangeClient
    client = HubExchangeClient(api=SimpleNamespace(endpoint="https://huggingface.co"))
    with pytest.raises(FeedError, match="pagination cursor"):
        client.list_page("owner/dataset", A, "https://attacker.example/api/secret", max_entries=100)
    with pytest.raises(FeedError, match="only exchange"):
        client.fetch("owner/dataset", A, "weights/model.bin", Path("unused"), max_bytes=10)


def test_hub_client_bounds_page_bytes_and_entries(monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.autoformal.span_cache_feed import HubExchangeClient
    import huggingface_hub.utils

    class Response:
        status_code = 200
        links = {}
        headers = {}
        request = SimpleNamespace(url="fixture")
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, _): yield b"[{},{}]"
    class Session:
        def get(self, *args, **kwargs):
            assert kwargs["stream"] is True and kwargs["allow_redirects"] is False
            return Response()
    monkeypatch.setattr(huggingface_hub.utils, "get_session", lambda: Session())
    api = SimpleNamespace(endpoint="https://huggingface.co", _build_hf_headers=lambda: {})
    with pytest.raises(FeedError, match="byte bound"):
        HubExchangeClient(api=api, max_page_bytes=3).list_page("owner/dataset", A, "", max_entries=10)
    with pytest.raises(FeedError, match="entry bound"):
        HubExchangeClient(api=api).list_page("owner/dataset", A, "", max_entries=1)

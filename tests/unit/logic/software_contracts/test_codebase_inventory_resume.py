"""Pure page-chain/inert protocol controls, not native scan qualification.

Real CAS publication/read identity is used. Native source owners, registered
lineage and isolated workers are qualified separately; lifecycle tests label
and replace those boundaries explicitly, without fitting or launching jobs.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import builtins
import hashlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import SnapshotEntry, _raw_display
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_resume_worker as worker


def cid(name):
    return cid_for_structured({"pure_control": name})


def root_body(count=3, page_entries=2, inferred=1024):
    snapshot = cid("snapshot")
    head = CodebaseHead("pure-owner", 1, cid("manifest"), snapshot,
        "rev:pure-owner:snapshot:" + snapshot, cid("receipt"))
    members = []
    for index in range(count):
        raw = f"def step{index}(n):\n    return n + {index + 1}\n".encode()
        entry = SnapshotEntry(f"source{index:04d}.py", "source", len(raw), cid_for_bytes(raw))
        members.append({"source_key": entry.source_key, "path": entry.path, "raw_path_hex": entry.raw_path_hex,
            "entry_cid": entry.entry_cid, "source_cid": entry.source_cid, "ast_cid": cid(f"ast{index}"),
            "parse_status": "ok", "source_size_bytes": entry.size_bytes, "opaque_reason": None})
    artifact = {"sha256": hashlib.sha256(b"model").hexdigest(), "bytes": 5}
    model = {"version_id": "pure-version", "variant_id": "pure-variant", "artifact": artifact,
        "artifact_cid": cid_for_bytes(b"model"), "contract_sha256": "1" * 64,
        "state_sha256": "2" * 64, "feature_space_sha256": "3" * 64,
        "latent_width": 8, "feature_columns": 2, "projection_ids": ["a", "b"],
        "projection_widths": {"a": 1, "b": 1}, "ancestry": [{"version_id": "pure-version", "artifact": artifact}]}
    files = {"pure.protocol": "4" * 64}
    return {"schema": scan.ROOT_SCHEMA, "head": head.to_dict(), "head_cid": cid_for_structured(head.to_dict()),
        "members": members, "membership_cid": cid_for_structured(members), "model": model,
        "limits": scan.CodebaseScanResumeLimits(page_entries=page_entries, max_inferred_rows=inferred).to_dict(),
        "optimized": True, "implementation": {"files": files, "sha256": scan.features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}, "authority": dict(scan._FALSE)}


def root_record(value):
    return scan.CodebaseScanResumeRoot.from_dict(cid_for_structured(value), value)


def page_body(root, start=0, previous=None, disposition="deferred_budget"):
    r = root.to_dict()
    end = min(start + r["limits"]["page_entries"], len(r["members"]))
    entries = [{"member_index": index, "source_key": member["source_key"], "entry_cid": member["entry_cid"],
        "disposition": disposition, "reason": "pure_control", "target_sha256": None, "source_digest": None,
        "coverage": [], "inference_index": None} for index, member in enumerate(r["members"][start:end], start)]
    return {"schema": scan.PAGE_SCHEMA, "root_cid": root.artifact_cid, "head_cid": r["head_cid"],
        "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"],
        "start": start, "end": end, "total_entries": len(r["members"]),
        "page_membership_cid": cid_for_structured(r["members"][start:end]), "previous_page_cid": previous,
        "entries": entries, "inference": None, "worker_receipt": None,
        "coverage": {"inventory_entries": len(entries), "inferred_rows": 0, "dispositions": {disposition: len(entries)}},
        "authority": dict(scan._FALSE)}


def page_record(value):
    raw = scan._wire(value)
    return scan.CodebaseScanResumePage(cid_for_bytes(raw), raw)


def stored_chain(tmp_path, count=3, page_entries=2):
    cas = ImmutableCAS(tmp_path / "cas", max_object_bytes=16 * 1024 * 1024)
    root = root_record(root_body(count, page_entries))
    cas.put(root.to_dict())
    pages, previous = [], None
    for start in range(0, count, page_entries):
        page = page_record(page_body(root, start, previous))
        cas.put_bytes(page._payload)
        pages.append(page)
        previous = page.artifact_cid
    return cas, root, pages


def completion(root, pages):
    counts = {"deferred_budget": len(root.to_dict()["members"])} if pages else {}
    value = scan._completion_value(root, [scan._descriptor(page) for page in pages],
        len(root.to_dict()["members"]), 0, counts)
    return scan.CodebaseScanResumeCompletion.from_dict(cid_for_structured(value), value)


@pytest.mark.parametrize("name", tuple(scan.CodebaseScanResumeLimits.__dataclass_fields__))
@pytest.mark.parametrize("value", [0, -1, True, 1.0])
def test_limits_refuse_aliases_and_invalid_bounds(name, value):
    with pytest.raises(scan.CodebaseScanResumeError):
        replace(scan.CodebaseScanResumeLimits(), **{name: value})


@pytest.mark.parametrize("name", tuple(scan.CodebaseScanResumeLimits.__dataclass_fields__))
def test_limits_do_not_widen_profile(name):
    maximum = dict(zip(scan.CodebaseScanResumeLimits.__dataclass_fields__,
        (1024, 64, 1024, 1024, 65536, 4194304, 4194304, 33554432, 16777216)))[name]
    with pytest.raises(scan.CodebaseScanResumeError):
        replace(scan.CodebaseScanResumeLimits(), **{name: maximum + 1})


def test_limits_refuse_unfinishable_page_profile():
    with pytest.raises(scan.CodebaseScanResumeError, match="complete"):
        scan.CodebaseScanResumeLimits(max_pages=1)


def test_large_chain_rehydrates_in_new_cas_owner_without_numerical_jobs(tmp_path):
    cas, root, pages = stored_chain(tmp_path, count=300, page_entries=64)
    complete = completion(root, pages)
    assert cas.put(complete.to_dict()) == complete.artifact_cid
    reopened = ImmutableCAS(cas.root, max_object_bytes=16 * 1024 * 1024)
    assert scan.load_codebase_scan_resume_root(reopened, root.artifact_cid) == root
    loaded = scan.load_codebase_scan_resume_page(reopened, pages[0].artifact_cid)
    cursor = scan.CodebaseScanResumeCursor.from_dict(json.loads(json.dumps(loaded.next_cursor.to_dict())))
    assert cursor.next_offset == 64
    assert cursor.previous_page_cid == pages[0].artifact_cid
    assert pages[-1].next_cursor is None
    assert scan.load_codebase_scan_resume_completion(reopened, complete.artifact_cid) == complete
    descriptors, offset, inferred, counts = scan._walk(reopened, root, pages[-1].artifact_cid, lambda: 30)
    assert offset == 300 and inferred == 0 and counts == {"deferred_budget": 300}
    assert descriptors == complete.to_dict()["pages"]
    refs = complete.advisory_refs(root)
    assert scan.validate_codebase_scan_completion_refs(refs) == refs
    refs["members"][0]["path"] = "mutated.py"
    assert complete.advisory_refs(root)["members"][0]["path"] != "mutated.py"


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "reorder", "head", "model", "alias", "source", "size"])
def test_root_constructor_rejects_rehashed_malformed_bindings(mutation):
    value = root_body()
    if mutation == "missing":
        del value["limits"]
    elif mutation == "extra":
        value["training_executed"] = False
    elif mutation == "duplicate":
        value["members"].append(deepcopy(value["members"][0]))
        value["membership_cid"] = cid_for_structured(value["members"])
    elif mutation == "reorder":
        value["members"].reverse()
        value["membership_cid"] = cid_for_structured(value["members"])
    elif mutation == "head":
        value["head_cid"] = cid("foreign")
    elif mutation == "model":
        value["model"]["artifact_cid"] = cid_for_bytes(b"other")
    elif mutation == "alias":
        value["model"]["latent_width"] = True
    elif mutation == "source":
        value["members"][0]["source_cid"] = cid("wrong-codec")
    else:
        value["members"][0]["source_size_bytes"] = None
    with pytest.raises((scan.CodebaseScanResumeError, ValueError, TypeError)):
        root_record(value)


@pytest.mark.parametrize("name", tuple(scan._FALSE))
@pytest.mark.parametrize("flag", [0, True])
def test_false_authority_flags_refuse_boolean_integer_aliases(name, flag):
    value = root_body()
    value["authority"][name] = flag
    with pytest.raises(scan.CodebaseScanResumeError, match="False"):
        root_record(value)


def test_opaque_unknown_size_and_raw_path_remain_explicit():
    value = root_body(1)
    entry = SnapshotEntry(_raw_display(b"\xff"), "opaque", None, None, "invalid_utf8_path", "ff")
    value["members"] = [{"source_key": entry.source_key, "path": entry.path, "raw_path_hex": entry.raw_path_hex,
        "entry_cid": entry.entry_cid, "source_cid": None, "ast_cid": None, "parse_status": "opaque",
        "source_size_bytes": None, "opaque_reason": entry.opaque_reason}]
    value["membership_cid"] = cid_for_structured(value["members"])
    root = root_record(value)
    assert root.to_dict()["members"][0]["source_size_bytes"] is None


@pytest.mark.parametrize("mutation", ["root", "head", "membership", "model", "skip", "duplicate", "alias", "authority", "terminal"])
def test_page_binding_refuses_rehashed_wrong_join(mutation):
    root = root_record(root_body())
    value = page_body(root)
    if mutation == "root":
        value["root_cid"] = cid("other-root")
    elif mutation == "head":
        value["head_cid"] = cid("other-head")
    elif mutation == "membership":
        value["page_membership_cid"] = cid("other-members")
    elif mutation == "model":
        value["model_artifact_cid"] = cid_for_bytes(b"other-model")
    elif mutation == "skip":
        value["entries"][0]["member_index"] = 1
    elif mutation == "duplicate":
        value["entries"][1]["source_key"] = value["entries"][0]["source_key"]
    elif mutation == "alias":
        value["coverage"]["inferred_rows"] = False
    elif mutation == "authority":
        value["authority"]["scan_execution_attested"] = 0
    else:
        value["total_entries"] = 2
    with pytest.raises(scan.CodebaseScanResumeError):
        page = page_record(value)
        scan._bind_page(page, root)


def test_gap_and_forged_cursor_cannot_skip_durable_prefix(tmp_path):
    cas, root, pages = stored_chain(tmp_path, count=5, page_entries=2)
    value = pages[-1].to_dict()
    value["previous_page_cid"] = pages[0].artifact_cid
    bad = page_record(value)
    cas.put_bytes(bad._payload)
    with pytest.raises(scan.CodebaseScanResumeError, match="omission"):
        scan._walk(cas, root, bad.artifact_cid, lambda: 30)
    with pytest.raises(scan.CodebaseScanResumeError, match="incomplete"):
        descriptors, offset, inferred, counts = scan._walk(cas, root, pages[0].artifact_cid, lambda: 30)
        scan._completion_value(root, descriptors, offset, inferred, counts)


def test_empty_inventory_can_have_empty_completeness():
    root = root_record(root_body(0))
    complete = completion(root, [])
    assert complete.advisory_refs(root)["coverage"] == {
        "inventory_entries": 0, "inferred_rows": 0, "pages": 0, "dispositions": {}}


@pytest.mark.parametrize("mutation", ["missing", "repeat", "gap", "count", "scope", "authority"])
def test_completion_and_refs_refuse_rehashed_false_completeness(tmp_path, mutation):
    _, root, pages = stored_chain(tmp_path)
    value = completion(root, pages).to_dict()
    if mutation == "missing":
        value["pages"].pop()
    elif mutation == "repeat":
        value["pages"].append(deepcopy(value["pages"][-1]))
    elif mutation == "gap":
        value["pages"][-1]["start"] += 1
    elif mutation == "count":
        value["coverage"]["inventory_entries"] = True
    elif mutation == "scope":
        value["membership_cid"] = cid("foreign-scope")
    else:
        value["authority"]["completion_authority"] = 0
    with pytest.raises(scan.CodebaseScanResumeError):
        record = scan.CodebaseScanResumeCompletion.from_dict(cid_for_structured(value), value)
        record.advisory_refs(root)


@pytest.mark.parametrize("mutation", ["float", "alias", "extra", "projection", "pages"])
def test_refs_pure_historical_validator_is_closed_and_float_free(tmp_path, mutation):
    _, root, pages = stored_chain(tmp_path)
    refs = completion(root, pages).advisory_refs(root)
    if mutation == "float":
        refs["coverage"]["inferred_rows"] = 0.0
    elif mutation == "alias":
        refs["authority"]["scan_execution_attested"] = 0
    elif mutation == "extra":
        refs["trusted"] = True
    elif mutation == "projection":
        refs["model"]["projection_widths"]["a"] = 2
    else:
        refs["pages"].reverse()
    with pytest.raises((scan.CodebaseScanResumeError, ValueError, TypeError)):
        scan.validate_codebase_scan_completion_refs(refs)


def test_cas_rehashed_missing_or_corrupt_bytes_cannot_rehydrate(tmp_path):
    cas, root, pages = stored_chain(tmp_path)
    cas.path_for(pages[0].artifact_cid, source=True).write_bytes(b"{}")
    with pytest.raises(ValueError):
        scan.load_codebase_scan_resume_page(cas, pages[0].artifact_cid)
    with pytest.raises(FileNotFoundError):
        scan.load_codebase_scan_resume_root(cas, cid("missing"))


def request():
    return {"schema": worker.SCHEMA, "root_cid": cid("root"), "root": {}, "optimized": True,
        "contract": {}, "feature_space": {}, "state": {}, "targets": [{}], "member_indices": [0],
        "max_seconds": 120, "limits": {"max_rows": 16, "max_target_bytes": 4194304,
            "max_input_bytes": 33554432, "max_output_bytes": 16777216}}


@pytest.fixture
def prohibit_numerical_import(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            pytest.fail("invalid inert protocol reached Torch")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.mark.parametrize("mutation", ["extra", "schema", "optimized", "deadline", "alias", "indices", "empty", "bound"])
def test_worker_invalid_protocol_is_refused_before_torch(prohibit_numerical_import, mutation):
    value = request()
    if mutation == "extra":
        value["trusted_inventory"] = True
    elif mutation == "schema":
        value["schema"] = "old-profile@1"
    elif mutation == "optimized":
        value["optimized"] = 0
    elif mutation == "deadline":
        value["max_seconds"] = True
    elif mutation == "alias":
        value["limits"]["max_rows"] = True
    elif mutation == "indices":
        value["member_indices"] = [True]
    elif mutation == "empty":
        value["targets"] = []
    else:
        value["limits"]["max_input_bytes"] = 1
    with pytest.raises(ValueError):
        worker.execute(value)


def test_worker_duplicate_and_nonfinite_json_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"optimized":true,"optimized":false}', object_pairs_hook=worker._json_pairs)
    with pytest.raises(ValueError, match="nonfinite"):
        json.loads('{"n":NaN}', parse_constant=worker._json_constant)


def test_cached_fake_receiving_replays_whole_chain_and_never_infers(tmp_path, monkeypatch):
    cas, root, pages = stored_chain(tmp_path)
    complete = completion(root, pages)
    cas.put(complete.to_dict())
    index, seen = SimpleNamespace(artifacts=cas), []
    @contextmanager
    def fake_scope(*args, **kwargs):
        yield None, None, lambda: 30
    monkeypatch.setattr(scan, "_scope", fake_scope)
    monkeypatch.setattr(scan, "_entry", lambda *args: (None, None, [], b"registry"))
    monkeypatch.setattr(scan, "_replay_page", lambda *args: seen.append((args[5].artifact_cid, args[6])))
    monkeypatch.setattr(scan, "_close", lambda *args: seen.append("closing"))
    monkeypatch.setattr(scan, "_worker", lambda *args: pytest.fail("receiving validation ran inference"))
    assert scan.validate_current_codebase_scan_completion(complete, index, ".", root=root, registry=None) == complete
    assert seen == [(pages[0].artifact_cid, 0), (pages[1].artifact_cid, 0), "closing"]


def test_cached_fake_final_source_fence_failure_never_returns_completion(tmp_path, monkeypatch):
    cas, root, pages = stored_chain(tmp_path)
    index = SimpleNamespace(artifacts=cas)
    @contextmanager
    def fake_scope(*args, **kwargs):
        yield None, None, lambda: 30
    monkeypatch.setattr(scan, "_scope", fake_scope)
    monkeypatch.setattr(scan, "_entry", lambda *args: (None, None, [], b"registry"))
    monkeypatch.setattr(scan, "_replay_page", lambda *args: None)
    def stale(*args):
        raise scan.StaleCodebaseError("controlled late source drift")
    monkeypatch.setattr(scan, "_close", stale)
    with pytest.raises(scan.StaleCodebaseError, match="drift"):
        scan.complete_current_codebase_scan(index, ".", root=root, registry=None, tail_page_cid=pages[-1].artifact_cid)
    # Publication before the final fence may leave immutable, inert orphans.
    expected = completion(root, pages)
    assert scan.load_codebase_scan_resume_completion(cas, expected.artifact_cid) == expected


def test_cached_fake_wrong_cursor_offset_is_refused_before_page_inference(tmp_path, monkeypatch):
    cas, root, pages = stored_chain(tmp_path)
    index = SimpleNamespace(artifacts=cas)
    @contextmanager
    def fake_scope(*args, **kwargs):
        yield None, None, lambda: 30
    monkeypatch.setattr(scan, "_scope", fake_scope)
    monkeypatch.setattr(scan, "_entry", lambda *args: (None, None, [], b"registry"))
    monkeypatch.setattr(scan, "_replay_page", lambda *args: None)
    monkeypatch.setattr(scan, "_prepare_page", lambda *args: pytest.fail("forged cursor prepared a new page"))
    cursor = scan.CodebaseScanResumeCursor(root.artifact_cid, 1, pages[0].artifact_cid)
    with pytest.raises(scan.CodebaseScanResumeError, match="offset"):
        scan.scan_current_codebase_page(index, ".", root=root, registry=None, cursor=cursor)


def cached_fake_preparation(monkeypatch, root, payloads=None):
    """Replace native target execution only to test deterministic packing policy."""
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseUnit
    r = root.to_dict()
    positions = {row["source_key"]: index for index, row in enumerate(r["members"])}
    canonical_wire = scan._wire
    entries = [SnapshotEntry(row["path"], "source", row["source_size_bytes"], row["source_cid"]) for row in r["members"]]
    units = [CodebaseUnit(row["source_key"], row["entry_cid"], row["ast_cid"], "ok") for row in r["members"]]
    manifest = SimpleNamespace(snapshot=SimpleNamespace(entries=entries, snapshot_cid=r["head"]["snapshot_cid"]),
                               units=units, cid=r["head"]["manifest_cid"])
    chain = [(None, {"contract": {}, "state": {}, "feature_space": {}}, {"selections": []})]
    monkeypatch.setattr(scan, "_member_native", lambda *args, **kwargs: (b"pure fake source", object()))
    monkeypatch.setattr(scan, "_member_disposition", lambda *args: ("captured_python", ()))
    monkeypatch.setattr(scan.numerical, "prepare_inventory_vocabulary", lambda *args: object())
    monkeypatch.setattr(scan.numerical, "inventory_target_coverage", lambda *args: {"compatible": True,
        "coverage": [{"projection_id": name, "known_atoms": 1, "unknown_atoms": 0} for name in ["a", "b"]]})
    class FakeTarget:
        def __init__(self, binding):
            self.value = {"ready_for_training": True,
                "source_digest": hashlib.sha256(binding["source_key"].encode()).hexdigest()}
            if payloads is not None:
                self.value["payload"] = payloads[positions[binding["source_key"]]]
            self.canonical_bytes = canonical_wire(self.value)
        def to_dict(self):
            return deepcopy(self.value)
    monkeypatch.setattr(scan.targets, "_prepare_bound", lambda **kwargs: FakeTarget(kwargs["binding"]))
    return SimpleNamespace(), manifest, None, chain


@pytest.mark.parametrize("count,start", [(0, 0), (4, 0), (20, 16), (104, 96)])
@pytest.mark.parametrize("retain", [True, False])
def test_cached_fake_incremental_charge_matches_complete_json_with_unicode_and_index_digits(monkeypatch, count, start, retain):
    """Packing protocol only; independently compare full JSON for every prefix."""
    root = root_record(root_body(count, page_entries=16))
    payloads = [{"text": 'café 雪 🦊 "\\\n', "number": index} for index in range(count)]
    index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root, payloads)
    actual_wire, calls = scan._wire, {"request": 0, "target": 0}
    def observed_wire(value):
        if type(value) is dict and "targets" in value:
            calls["request"] += 1
        if type(value) is dict and "ready_for_training" in value:
            calls["target"] += 1
        return actual_wire(value)
    monkeypatch.setattr(scan, "_wire", observed_wire)
    entries, request = scan._prepare_page(index, root, manifest, receipt, chain, start, 0, lambda: 30,
                                          retain_targets=retain)
    expected = scan._payload(root, chain[0][1])
    byte_count = len(actual_wire(expected))
    for inference_index, row in enumerate(entries):
        target = {"ready_for_training": True, "source_digest": hashlib.sha256(row["source_key"].encode()).hexdigest(),
                  "payload": payloads[row["member_index"]]}
        byte_count += len(actual_wire(target)) + len(str(row["member_index"])) + (2 if inference_index else 0)
        expected["targets"].append(target)
        expected["member_indices"].append(row["member_index"])
        assert byte_count == len(actual_wire(expected))
        assert row["inference_index"] == inference_index and row["disposition"] == "inferred"
        assert row["target_sha256"] == hashlib.sha256(actual_wire(target)).hexdigest()
    assert calls == {"request": 2 if retain else 1, "target": len(entries)}
    if retain:
        assert request == expected
    else:
        assert request["targets"] == request["member_indices"] == []


def cached_fake_budget_root(monkeypatch, optimized, delta):
    """Fix the exact encoded limit digit widths before choosing a byte edge."""
    value = root_body(4, page_entries=4)
    value["optimized"] = optimized
    payloads = ["small café", "large" * 20000, "雪" * 20000, "last 🦊"]
    for _ in range(4):
        root = root_record(value)
        index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root, payloads)
        request = scan._payload(root, chain[0][1])
        for ordinal in (0, 3):
            member = root.to_dict()["members"][ordinal]
            request["targets"].append({"ready_for_training": True,
                "source_digest": hashlib.sha256(member["source_key"].encode()).hexdigest(), "payload": payloads[ordinal]})
            request["member_indices"].append(ordinal)
        limit = len(scan._wire(request)) + 64 + delta
        if value["limits"]["max_input_bytes"] == limit:
            return root, index, manifest, receipt, chain
        value["limits"]["max_input_bytes"] = limit
    pytest.fail("pure byte-edge limit did not converge")


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_cached_fake_exact_byte_edge_and_multiple_deferrals_preserve_all_members(monkeypatch, optimized, delta):
    root, index, manifest, receipt, chain = cached_fake_budget_root(monkeypatch, optimized, delta)
    entries, request = scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)
    expected_indices = [0] if delta < 0 else [0, 3]
    assert request["member_indices"] == expected_indices
    assert len(entries) == 4 and [row["member_index"] for row in entries] == list(range(4))
    assert [row["member_index"] for row in entries if row["disposition"] == "inferred"] == expected_indices
    assert len(scan._wire(request)) + 64 <= root.to_dict()["limits"]["max_input_bytes"]
    for row in entries:
        assert row["target_sha256"] is not None and row["coverage"]
        if row["member_index"] not in expected_indices:
            assert row["reason"] == "page_worker_input_byte_budget" and row["inference_index"] is None
    if optimized:
        replayed, inert_request = scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30,
                                                    retain_targets=False)
        assert replayed == entries
        assert inert_request["targets"] == inert_request["member_indices"] == []


def test_cached_fake_default_and_optout_prepare_identical_target_order_fields_and_global_budget(monkeypatch):
    payloads = ["é" * 20, "雪\n", "last 🦊", "beyond global budget"]
    outputs = []
    for optimized in (True, False):
        value = root_body(4, page_entries=4, inferred=2)
        value["optimized"] = optimized
        root = root_record(value)
        index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root, payloads)
        entries, request = scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)
        outputs.append((entries, request["targets"], request["member_indices"]))
    assert outputs[0] == outputs[1]
    assert outputs[0][2] == [0, 1]


@pytest.mark.parametrize("mutation", ["manifest", "snapshot"])
@pytest.mark.parametrize("optimized", [True, False])
def test_cached_fake_page_target_phase_closes_same_manifest_identity(monkeypatch, mutation, optimized):
    value = root_body(4, page_entries=4)
    value["optimized"] = optimized
    root = root_record(value)
    index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root)
    real_disposition, mutated = scan._member_disposition, []
    def mutate_at_member(*args):
        if not mutated:
            if mutation == "manifest":
                manifest.cid = cid("late-manifest-substitution")
            else:
                manifest.snapshot.snapshot_cid = cid("late-snapshot-substitution")
            mutated.append(True)
        return real_disposition(*args)
    monkeypatch.setattr(scan, "_member_disposition", mutate_at_member)
    with pytest.raises(scan.CodebaseScanResumeError, match="page native manifest changed"):
        scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)


def test_cached_fake_global_inference_budget_stays_fixed_across_pages(monkeypatch):
    root = root_record(root_body(5, page_entries=2, inferred=1))
    index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root)
    first, request1 = scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)
    assert [row["disposition"] for row in first] == ["inferred", "deferred_budget"]
    assert first[1]["reason"] == "global_inferred_row_budget"
    assert len(request1["targets"]) == 1
    second, request2 = scan._prepare_page(index, root, manifest, receipt, chain, 2, 1, lambda: 30)
    assert [row["disposition"] for row in second] == ["deferred_budget", "deferred_budget"]
    assert request2["targets"] == [] and request2["member_indices"] == []


def test_cached_fake_first_page_byte_refusal_retains_every_member(monkeypatch):
    value = root_body(3)
    value["limits"]["max_input_bytes"] = 1
    root = root_record(value)
    index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root)
    entries, request = scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)
    assert len(entries) == 2 and request["targets"] == []
    assert all(row["disposition"] == "deferred_budget" and row["reason"] == "page_worker_input_byte_budget" for row in entries)
    page_value = page_body(root)
    page_value["entries"] = entries
    page = page_record(page_value)
    scan._bind_page(page, root)
    assert page.next_cursor.next_offset == 2


@pytest.mark.parametrize("native_error,expected", [
    ("CodebaseIR target exceeds its byte bound", "deferred_budget"),
    ("function inventory exceeds the target profile", "unsupported_target"),
    ("source binding corrupt", None),
])
def test_cached_fake_native_frontiers_do_not_hide_integrity_errors(monkeypatch, native_error, expected):
    root = root_record(root_body())
    index, manifest, receipt, chain = cached_fake_preparation(monkeypatch, root)
    def refuse(**kwargs):
        raise scan.targets.CodebaseTargetError(native_error)
    monkeypatch.setattr(scan.targets, "_prepare_bound", refuse)
    if expected is None:
        with pytest.raises(scan.targets.CodebaseTargetError, match="corrupt"):
            scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)
    else:
        entries, request = scan._prepare_page(index, root, manifest, receipt, chain, 0, 0, lambda: 30)
        assert all(row["disposition"] == expected for row in entries)
        assert request["targets"] == []


def test_cached_fake_receiving_rejects_rehashed_native_ledger_disposition(monkeypatch):
    root = root_record(root_body())
    page = page_record(page_body(root))
    expected = deepcopy(page.to_dict()["entries"])
    expected[0]["reason"] = "fresh_native_disposition"
    monkeypatch.setattr(scan, "_prepare_page", lambda *args, **kwargs: (expected, {}))
    with pytest.raises(scan.CodebaseScanResumeError, match="dispositions"):
        scan._replay_page(None, root, None, None, None, page, 0, lambda: 30)


def numerical_page_body(root):
    """Synthetic finite numerical bytes; no native producer execution claimed."""
    value = page_body(root)
    for index, entry in enumerate(value["entries"]):
        entry.update(disposition="inferred", reason=None, target_sha256="5" * 64,
            source_digest=hashlib.sha256(entry["source_key"].encode()).hexdigest(), inference_index=index,
            coverage=[{"projection_id": name, "known_atoms": 1, "unknown_atoms": 0} for name in ["a", "b"]])
    r = root.to_dict()
    value["inference"] = {"schema": "native-projection-feature-inference/v1",
        "contract_sha256": r["model"]["contract_sha256"], "state_sha256": r["model"]["state_sha256"],
        "feature_space_sha256": r["model"]["feature_space_sha256"],
        "rows": [{"source_digest": entry["source_digest"], "latent": [0.0] * 8,
            "reconstructed_projection_features": {"a": [0.0], "b": [0.0]}} for entry in value["entries"]],
        "coverage": [item for entry in value["entries"] for item in entry["coverage"]],
        "training_executed": False, "decoded_formulas_generated": False,
        "representation": "native_compiler_structural_features_not_semantic_text_embeddings", **scan.features.FALSE}
    value["coverage"] = {"inventory_entries": len(value["entries"]), "inferred_rows": len(value["entries"]),
                          "dispositions": {"inferred": len(value["entries"])}}
    value["worker_receipt"] = {"executable_sha256": "6" * 64, "worker_sha256": "7" * 64,
        "input_sha256": "8" * 64, "output_sha256": "9" * 64, "input_bytes": 1, "output_bytes": 1,
        "elapsed_ms": 1, "returncode": 0, "workspace_cleaned": True,
        "limits": {"resident_memory_bytes": 1024 * 1024 * 1024,
                   "max_input_bytes": 32 * 1024 * 1024, "max_output_bytes": 16 * 1024 * 1024},
        "memory_enforcement": "sampled_process_tree_rss_with_possible_overshoot", "source_execution_attested": False}
    return value


@pytest.mark.parametrize("mutation", ["width", "projection", "source", "index", "state", "nonfinite", "boolean", "coverage", "receipt"])
def test_numerical_page_constructor_and_root_binding_validate_deep_shape(mutation):
    root = root_record(root_body())
    value = numerical_page_body(root)
    if mutation == "width":
        value["inference"]["rows"][0]["latent"].pop()
    elif mutation == "projection":
        value["inference"]["rows"][0]["reconstructed_projection_features"]["a"].append(0.0)
    elif mutation == "source":
        value["inference"]["rows"][0]["source_digest"] = "a" * 64
    elif mutation == "index":
        value["entries"][0]["inference_index"] = True
    elif mutation == "state":
        value["inference"]["state_sha256"] = "a" * 64
    elif mutation == "nonfinite":
        value["inference"]["rows"][0]["latent"][0] = float("inf")
    elif mutation == "boolean":
        value["inference"]["rows"][0]["latent"][0] = True
    elif mutation == "coverage":
        value["entries"][0]["coverage"][0]["known_atoms"] = True
    else:
        value["worker_receipt"]["source_execution_attested"] = 0
    with pytest.raises((scan.CodebaseScanResumeError, ValueError)):
        scan._bind_page(page_record(value), root)


def test_numerical_rehash_remains_explicitly_advisory_execution_unattested():
    root = root_record(root_body())
    value = numerical_page_body(root)
    original = page_record(value)
    scan._bind_page(original, root)
    value["inference"]["rows"][0]["latent"][0] = 0.5
    changed = page_record(value)
    scan._bind_page(changed, root)
    assert changed.artifact_cid != original.artifact_cid
    assert changed.to_dict()["authority"]["scan_execution_attested"] is False
    assert changed.to_dict()["worker_receipt"]["source_execution_attested"] is False


def test_cached_fake_catalog_owner_substitution_is_refused(monkeypatch):
    monkeypatch.setattr(scan.training, "_native_owners", lambda *args: None)
    catalog = SimpleNamespace(store=object(), artifacts=object())
    index = SimpleNamespace(catalog=catalog, ingestor=SimpleNamespace(store=catalog.store), artifacts=catalog.artifacts)
    with pytest.raises(scan.CodebaseScanResumeError, match="exact structural"):
        scan._owners(index, None)

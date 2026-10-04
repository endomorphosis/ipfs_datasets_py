"""Inert HfApi contract tests; no remote publication or model execution."""
import copy
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ir_model_hub_publish as pub


def pin(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def make_plan(tmp_path, *, card=False):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"schema":"authored-release-index/v1","model_quality":false}')
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(b'{"retained_parameters":[1,2,3]}')
    operations = [{"file_pin": pin(manifest), "path_in_repo": "releases/fixed/manifest.json"},
                  {"file_pin": pin(checkpoint), "path_in_repo": "releases/fixed/checkpoint.json"}]
    if card:
        readme = tmp_path / "README.md"
        readme.write_text("# Experimental retained assets\n")
        operations.append({"file_pin": pin(readme), "path_in_repo": "README.md"})
    return {"schema": pub.PLAN_SCHEMA, "manifest_pin": pin(manifest),
            "repository_id": "Publicus/legal-ir-autoencoder-384d", "private_new": True,
            "operations": operations}


def addition(**kwargs):
    return SimpleNamespace(**kwargs)


class NotFound(RuntimeError):
    def __init__(self, status=404):
        super().__init__("inert provider error")
        self.response = SimpleNamespace(status_code=status)


class FakeAPI:
    """Models immutable commit snapshots and optimistic parent comparison."""

    def __init__(self, *, exists=True, private=True, files=None, lfs=()):
        self.exists, self.private = exists, private
        self.head = "1" * 40
        self.revisions = {self.head: dict(files or {})}
        self.lfs = set(lfs)
        self.calls, self.commits, self.creates = [], [], []
        self.on_info = self.on_commit = None
        self.info_count = 0
        self.override_rows = None

    def model_info(self, repo_id, *, files_metadata, revision=None):
        assert files_metadata is True
        self.calls.append(("info", repo_id, revision))
        self.info_count += 1
        if self.on_info:
            self.on_info(self)
        if not self.exists:
            raise NotFound()
        revision = self.head if revision is None else revision
        rows = []
        for path, data in self.revisions[revision].items():
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            lfs = None
            if path in self.lfs:
                lfs = SimpleNamespace(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            rows.append(SimpleNamespace(rfilename=path, size=len(data), blob_id=blob, lfs=lfs))
        if self.override_rows:
            rows = self.override_rows(rows)
        return SimpleNamespace(sha=revision, private=self.private, siblings=rows)

    def create_repo(self, repo_id, *, repo_type, private, exist_ok):
        assert repo_type == "model" and exist_ok is False and not self.exists
        self.calls.append(("create", repo_id))
        self.creates.append(private)
        self.exists, self.private = True, private

    def create_commit(self, repo_id, *, repo_type, parent_commit, operations, commit_message):
        assert repo_type == "model"
        self.calls.append(("commit", repo_id, parent_commit))
        if self.on_commit:
            self.on_commit(self)
        if parent_commit != self.head:
            raise RuntimeError("inert optimistic CAS conflict")
        files = dict(self.revisions[parent_commit])
        paths = []
        for operation in operations:
            assert type(operation.path_or_fileobj) is bytes
            assert operation.path_in_repo not in files
            files[operation.path_in_repo] = operation.path_or_fileobj
            paths.append(operation.path_in_repo)
        self.head = "2" * 40
        self.revisions[self.head] = files
        self.commits.append({"parent": parent_commit, "paths": paths})
        return SimpleNamespace(oid=self.head)


def invoke(plan, api, factory=addition):
    return pub.publish_ir_model_hub_release(plan, api=api, operation_factory=factory)


@pytest.mark.parametrize("private", [True, False])
def test_new_repository_uses_explicit_visibility_and_exact_returned_commit(tmp_path, private):
    plan = make_plan(tmp_path, card=True)
    plan["private_new"] = private
    api = FakeAPI(exists=False)
    result = invoke(plan, api)
    assert api.creates == [private]
    assert api.commits == [{"parent": "1" * 40, "paths": [x["path_in_repo"] for x in plan["operations"]]}]
    assert result["revision"] == "2" * 40 and result["repository_private"] is private
    assert result["repository_created"] and result["commit_started"] and result["commit_returned"]
    assert result["repository_create_started"] and result["repository_create_returned"]
    assert not result["repository_creation_indeterminate"]
    assert result["files_verified"] and not result["idempotent_reuse"]
    assert all(x["verified"] and x["sha256"] == x["file_pin"]["sha256"] for x in result["files"])
    assert api.calls[-1] == ("info", plan["repository_id"], "2" * 40)


@pytest.mark.parametrize("existing_private", [True, False])
def test_existing_visibility_is_preserved_even_when_preference_differs(tmp_path, existing_private):
    plan = make_plan(tmp_path)
    plan["private_new"] = not existing_private
    api = FakeAPI(private=existing_private)
    result = invoke(plan, api)
    assert api.creates == [] and result["repository_private"] is existing_private
    assert result["existing_visibility_preserved"]


def test_complete_exact_release_reuses_immutable_revision_without_commit(tmp_path):
    plan = make_plan(tmp_path, card=True)
    files = {x["path_in_repo"]: open(x["file_pin"]["path"], "rb").read() for x in plan["operations"]}
    api = FakeAPI(files=files)
    result = invoke(plan, api)
    assert api.creates == api.commits == []
    assert result["revision"] == "1" * 40 and result["idempotent_reuse"]
    assert not result["commit_started"] and not result["commit_returned"]
    assert result["reused_paths"] == list(files) and result["created_paths"] == []


def test_mixed_release_adds_only_missing_files_and_preserves_unrelated_files(tmp_path):
    plan = make_plan(tmp_path)
    manifest = plan["operations"][0]
    data = open(manifest["file_pin"]["path"], "rb").read()
    api = FakeAPI(files={manifest["path_in_repo"]: data, "README.md": b"prior card"})
    result = invoke(plan, api)
    assert api.commits[0]["paths"] == [plan["operations"][1]["path_in_repo"]]
    assert api.revisions[api.head]["README.md"] == b"prior card"
    assert result["reused_paths"] == [manifest["path_in_repo"]]


@pytest.mark.parametrize("destination", ["releases/fixed/checkpoint.json", "README.md"])
def test_conflicting_existing_path_including_card_refuses_before_commit(tmp_path, destination):
    plan = make_plan(tmp_path, card=True)
    api = FakeAPI(files={destination: b"different existing payload"})
    with pytest.raises(pub.HubPublicationError) as caught:
        invoke(plan, api)
    assert api.commits == [] and api.creates == []
    assert caught.value.receipt["files_verified"] is False


def test_optimistic_parent_conflict_is_not_retried_or_overwritten(tmp_path):
    plan = make_plan(tmp_path)
    api = FakeAPI()
    api.on_commit = lambda a: setattr(a, "head", "3" * 40)
    with pytest.raises(pub.HubPublicationError) as caught:
        invoke(plan, api)
    assert caught.value.receipt["commit_started"] is True
    assert caught.value.receipt["commit_returned"] is False
    assert len([x for x in api.calls if x[0] == "commit"]) == 1 and api.commits == []


def test_lfs_payload_identity_uses_sha256_and_size_not_pointer_blob(tmp_path):
    plan = make_plan(tmp_path)
    api = FakeAPI(lfs={plan["operations"][1]["path_in_repo"]})
    result = invoke(plan, api)
    assert result["files"][1]["remote_identity"] == {
        "scheme": "lfs-payload-sha256", "sha256": plan["operations"][1]["file_pin"]["sha256"],
        "bytes": plan["operations"][1]["file_pin"]["bytes"]}
    assert result["files"][0]["remote_identity"]["scheme"] == "git-blob-sha1"


@pytest.mark.parametrize("problem", ["blob", "size", "lfs_sha", "lfs_size", "duplicate", "missing"])
def test_returned_commit_metadata_must_authenticate_every_file(tmp_path, problem):
    plan = make_plan(tmp_path)
    api = FakeAPI(lfs={plan["operations"][1]["path_in_repo"]})
    def damage(rows):
        if api.info_count == 1:
            return rows
        if problem == "blob": rows[0].blob_id = "0" * 40
        elif problem == "size": rows[0].size += 1
        elif problem == "lfs_sha": rows[1].lfs.sha256 = "0" * 64
        elif problem == "lfs_size": rows[1].lfs.size += 1
        elif problem == "duplicate": rows.append(rows[0])
        elif problem == "missing": rows.pop()
        return rows
    api.override_rows = damage
    with pytest.raises(pub.HubPublicationError) as caught:
        invoke(plan, api)
    assert caught.value.receipt["commit_returned"] is True
    assert caught.value.receipt["files_verified"] is False


@pytest.mark.parametrize("phase", ["initial_metadata", "after_commit", "returned_metadata"])
def test_source_drift_before_and_after_commit_is_refused(tmp_path, phase):
    plan = make_plan(tmp_path)
    api = FakeAPI()
    source = plan["operations"][1]["file_pin"]["path"]
    def mutate():
        with open(source, "wb") as stream:
            stream.write(b"changed retained checkpoint")
    if phase == "initial_metadata": api.on_info = lambda _: mutate()
    elif phase == "after_commit": api.on_commit = lambda _: mutate()
    else: api.on_info = lambda a: mutate() if a.info_count == 2 else None
    with pytest.raises(pub.HubPublicationError) as caught:
        invoke(plan, api)
    assert caught.value.receipt["files_verified"] is False
    assert bool(api.commits) == (phase != "initial_metadata")


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_nonregular_and_alias_sources_refuse_without_api_effects(tmp_path, kind):
    plan = make_plan(tmp_path)
    source = tmp_path / "checkpoint.json"
    source.unlink()
    if kind == "symlink": source.symlink_to(tmp_path / "manifest.json")
    elif kind == "directory": source.mkdir()
    else: os.mkfifo(source)
    api = FakeAPI()
    with pytest.raises(pub.HubPublicationError): invoke(plan, api)
    assert api.calls == []


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a/../escape", "a//b", "a/./b",
                                    "a/", "a\\b", "https://remote", "space name", ""])
def test_unsafe_remote_paths_refuse_before_api(tmp_path, path):
    plan = make_plan(tmp_path)
    plan["operations"][1]["path_in_repo"] = path
    api = FakeAPI()
    with pytest.raises(pub.HubPublicationError): invoke(plan, api)
    assert api.calls == []


@pytest.mark.parametrize("problem", ["extra", "schema", "repo", "visibility", "duplicate_path",
                                      "missing_manifest", "bool_bytes", "wrong_sha", "empty_files"])
def test_closed_plan_and_exact_manifest_association_are_required(tmp_path, problem):
    plan = make_plan(tmp_path)
    if problem == "extra": plan["extra"] = "not admitted"
    elif problem == "schema": plan["schema"] = "unsupported"
    elif problem == "repo": plan["repository_id"] = "Publicus/../wrong"
    elif problem == "visibility": plan["private_new"] = 1
    elif problem == "duplicate_path": plan["operations"].append(copy.deepcopy(plan["operations"][0]))
    elif problem == "missing_manifest": plan["operations"].pop(0)
    elif problem == "bool_bytes": plan["operations"][1]["file_pin"]["bytes"] = True
    elif problem == "wrong_sha": plan["operations"][1]["file_pin"]["sha256"] = "z" * 64
    elif problem == "empty_files": plan["operations"] = []
    api = FakeAPI()
    with pytest.raises(pub.HubPublicationError): invoke(plan, api)
    assert api.calls == []


@pytest.mark.parametrize("raw", [b'{"same":1,"same":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]'])
def test_authenticated_manifest_still_requires_strict_json_object(tmp_path, raw):
    plan = make_plan(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(raw)
    plan["manifest_pin"] = pin(manifest)
    plan["operations"][0]["file_pin"] = pin(manifest)
    api = FakeAPI()
    with pytest.raises(pub.HubPublicationError): invoke(plan, api)
    assert api.calls == []


def test_declared_total_bound_is_checked_before_source_reads(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    monkeypatch.setattr(pub, "MAX_TOTAL_BYTES", 1)
    monkeypatch.setattr(pub, "_read_pin", lambda _: pytest.fail("must not read"))
    with pytest.raises(pub.HubPublicationError): invoke(plan, FakeAPI())


def test_provider_forbidden_is_not_treated_as_repository_absence(tmp_path):
    plan = make_plan(tmp_path)
    api = FakeAPI()
    api.on_info = lambda _: (_ for _ in ()).throw(NotFound(403))
    with pytest.raises(pub.HubPublicationError): invoke(plan, api)
    assert api.creates == []


def test_partial_new_repository_receipt_survives_later_failure(tmp_path):
    plan = make_plan(tmp_path)
    api = FakeAPI(exists=False)
    api.on_info = lambda a: setattr(a, "private", False) if a.info_count == 2 else None
    with pytest.raises(pub.HubPublicationError) as caught: invoke(plan, api)
    assert caught.value.receipt["repository_created"] is True
    assert api.commits == []


def test_caller_plan_and_returned_receipt_are_detached(tmp_path):
    plan = make_plan(tmp_path)
    before = copy.deepcopy(plan)
    api = FakeAPI()
    result = invoke(plan, api)
    result["manifest_pin"]["sha256"] = "0" * 64
    result["files"][0]["file_pin"]["bytes"] = -1
    assert plan == before


def test_reentrant_caller_mutation_cannot_change_captured_selection(tmp_path):
    plan = make_plan(tmp_path)
    api = FakeAPI()
    api.on_info = lambda _: plan.update(repository_id="Other/changed", private_new=False)
    result = invoke(plan, api)
    assert result["repository_id"] == "Publicus/legal-ir-autoencoder-384d"
    assert all(call[1] == result["repository_id"] for call in api.calls)


def test_factory_receives_immutable_bytes_and_wrong_factory_payload_is_detected(tmp_path):
    plan = make_plan(tmp_path)
    def wrong(**kwargs):
        assert type(kwargs["path_or_fileobj"]) is bytes
        kwargs["path_or_fileobj"] = b"substituted"
        return addition(**kwargs)
    with pytest.raises(pub.HubPublicationError) as caught: invoke(plan, FakeAPI(), wrong)
    assert caught.value.receipt["commit_returned"] and not caught.value.receipt["files_verified"]


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_propagate(tmp_path, exception):
    api = FakeAPI()
    api.on_info = lambda _: (_ for _ in ()).throw(exception())
    with pytest.raises(exception): invoke(make_plan(tmp_path), api)


def test_no_runtime_or_quality_authority_is_granted(tmp_path):
    result = invoke(make_plan(tmp_path), FakeAPI())
    for key in ["repository_supplied_python_executed", "trust_remote_code", "model_loaded",
                "numerical_quality_qualified", "teacher_qualified", "proof_qualified",
                "cross_repository_transaction_atomic"]:
        assert result[key] is False


def test_invalid_plan_refuses_before_lazy_sdk_import(tmp_path, monkeypatch):
    import builtins
    plan = make_plan(tmp_path)
    plan["schema"] = "wrong"
    original_import = builtins.__import__
    def guard(name, *args, **kwargs):
        if name == "huggingface_hub": pytest.fail("invalid plan must not import SDK")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guard)
    with pytest.raises(pub.HubPublicationError): pub.publish_ir_model_hub_release(plan)


@pytest.mark.parametrize("problem", ["revision", "visibility", "nonlist_files"])
def test_returned_repository_snapshot_is_strict(tmp_path, problem):
    plan = make_plan(tmp_path)
    api = FakeAPI()
    original_info = api.model_info
    def info(*args, **kwargs):
        result = original_info(*args, **kwargs)
        if kwargs.get("revision"):
            if problem == "revision": result.sha = "0" * 40
            elif problem == "visibility": result.private = not result.private
            else: result.siblings = None
        return result
    api.model_info = info
    with pytest.raises(pub.HubPublicationError) as caught: invoke(plan, api)
    assert caught.value.receipt["commit_returned"] and not caught.value.receipt["files_verified"]


def test_read_race_changes_file_after_first_read_and_refuses(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    source = tmp_path / "manifest.json"
    original_read = pub.os.read
    done = False
    def race(fd, count):
        nonlocal done
        data = original_read(fd, count)
        if data and not done:
            done = True
            source.write_bytes(b'{"changed":true}')
        return data
    monkeypatch.setattr(pub.os, "read", race)
    api = FakeAPI()
    with pytest.raises(pub.HubPublicationError): invoke(plan, api)
    assert done and api.calls == []


def test_lost_create_response_preserves_indeterminate_attempt_and_never_retries(tmp_path):
    api = FakeAPI(exists=False)
    original_create = api.create_repo
    def lost_response(*args, **kwargs):
        original_create(*args, **kwargs)
        raise RuntimeError("inert lost response after server creation")
    api.create_repo = lost_response
    with pytest.raises(pub.HubPublicationError) as caught:
        invoke(make_plan(tmp_path), api)
    result = caught.value.receipt
    assert api.exists and len(api.creates) == 1 and api.commits == []
    assert result["repository_create_started"] is True
    assert result["repository_create_returned"] is False
    assert result["repository_creation_indeterminate"] is True
    assert result["repository_created"] is False  # No successful response was observed.
    assert result["commit_started"] is False and result["files_verified"] is False

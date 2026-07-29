"""Tests for the fail-closed CVEfixes Security IR publication command."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


SCRIPT = (
    Path(__file__).resolve().parents[5]
    / "scripts"
    / "ops"
    / "security_ir"
    / "publish_cvefixes_security_ir.py"
)
SPEC = importlib.util.spec_from_file_location("publish_cvefixes_security_ir", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
publisher: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


TARGET = "sofiyapervane/cvefixes-security-ir-graphrag"
SOURCE = "hitoshura25/cvefixes"
SOURCE_REVISION = "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"
RELEASE_ROOT = "b" + ("a" * 58)
INITIAL_COMMIT = "1" * 40
PUBLISHED_COMMIT = "2" * 40


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()


def _parquet_bytes(config: str) -> bytes:
    record_id = "b" + ("z" * 58)
    record = {
        "record_id": record_id,
        "record_type": config,
    }
    table = pa.Table.from_pydict(
        {
            "record_id": [record_id],
            "record_type": [config],
            "authority": ["candidate"],
            "source_cids": [["b" + ("s" * 58)]],
            "parent_cids": [["b" + ("p" * 58)]],
            "config_cid": ["b" + ("q" * 58)],
            "record_json": [_canonical(record).decode()],
        },
        schema=pa.schema(
            [
                pa.field("record_id", pa.string(), nullable=False),
                pa.field("record_type", pa.string(), nullable=False),
                pa.field("authority", pa.string(), nullable=False),
                pa.field("source_cids", pa.list_(pa.string()), nullable=False),
                pa.field("parent_cids", pa.list_(pa.string()), nullable=False),
                pa.field("config_cid", pa.string(), nullable=False),
                pa.field("record_json", pa.string(), nullable=False),
            ]
        ),
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue().to_pybytes()


def _descriptor(
    path: str,
    content: bytes,
    media_type: str,
    *,
    config: str = "",
) -> dict[str, Any]:
    result = {
        "byte_length": len(content),
        "content_id": "b"
        + base64.b32encode(hashlib.sha512(content).digest())
        .decode()
        .lower()[:58],
        "media_type": media_type,
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    if config:
        result["config_name"] = config
        result["row_count"] = 1
    return result


@pytest.fixture
def staged_release(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    contents = {
        "README.md": b"---\nlicense: Apache-2.0\n---\n# Test release\n",
        "evaluation-report.json": _canonical(
            {"grants_execution_authority": False}
        ),
        "data/graph_node/train-00000-of-00001.parquet": _parquet_bytes(
            "graph_node"
        ),
        "data/policy_candidate/train-00000-of-00001.parquet": _parquet_bytes(
            "policy_candidate"
        ),
    }
    features = {
        "authority": {"dtype": "string"},
        "config_cid": {"dtype": "string"},
        "parent_cids": {"feature": {"dtype": "string"}},
        "record_id": {"dtype": "string"},
        "record_json": {"dtype": "string"},
        "record_type": {"dtype": "string"},
        "source_cids": {"feature": {"dtype": "string"}},
    }
    contents["dataset_infos.json"] = _canonical(
        {
            "configs": {
                "graph_node": {
                    "features": features,
                    "splits": {
                        "train": {
                            "num_bytes": len(
                                contents[
                                    "data/graph_node/"
                                    "train-00000-of-00001.parquet"
                                ]
                            ),
                            "num_examples": 1,
                        }
                    },
                },
                "policy_candidate": {
                    "features": features,
                    "splits": {
                        "train": {
                            "num_bytes": len(
                                contents[
                                    "data/policy_candidate/"
                                    "train-00000-of-00001.parquet"
                                ]
                            ),
                            "num_examples": 1,
                        }
                    },
                },
            },
            "dataset_id": TARGET,
            "derived_dataset_root": "b" + ("d" * 58),
            "schema_version": publisher.PARQUET_SCHEMA_VERSION,
        }
    )
    descriptors = []
    media_types = {
        "README.md": "text/markdown; charset=utf-8",
        "dataset_infos.json": "application/json",
        "evaluation-report.json": "application/json",
    }
    for path, content in sorted(contents.items()):
        config = Path(path).parts[1] if path.endswith(".parquet") else ""
        descriptors.append(
            _descriptor(
                path,
                content,
                (
                    "application/vnd.apache.parquet"
                    if config
                    else media_types[path]
                ),
                config=config,
            )
        )
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    manifest = {
        "artifacts": descriptors,
        "dataset_id": TARGET,
        "derived_dataset_root": "b" + ("d" * 58),
        "release_manifest": {
            "dataset_id": TARGET,
            "payload": {
                "release_root": RELEASE_ROOT,
                "release_schema_version": publisher.RELEASE_SCHEMA_VERSION,
            },
            "shard_cids": [
                item["content_id"]
                for item in descriptors
                if item["path"].endswith(".parquet")
            ],
        },
        "release_root": RELEASE_ROOT,
        "schema_version": publisher.RELEASE_SCHEMA_VERSION,
        "source": {
            "dataset_id": SOURCE,
            "source_revision": SOURCE_REVISION,
        },
    }
    (root / "manifest.json").write_bytes(_canonical(manifest))
    return root


class FakeHub:
    def __init__(
        self,
        release_dir: Path,
        *,
        viewer_columns: Sequence[str] = publisher.EXPECTED_COLUMNS,
    ) -> None:
        self.release_dir = release_dir
        self.current_head = INITIAL_COMMIT
        self.history = [INITIAL_COMMIT]
        self.files: dict[tuple[str, str], bytes] = {}
        self.upload_calls = 0
        self.auth_calls = 0
        self.viewer_columns = tuple(viewer_columns)
        self.token_values: list[str] = []

    def authenticate(self, token: str) -> str:
        self.auth_calls += 1
        self.token_values.append(token)
        return "release-operator"

    def head(self, repo_id: str, token: str | None) -> str:
        assert repo_id == TARGET
        if token:
            self.token_values.append(token)
        return self.current_head

    def revisions(
        self, repo_id: str, token: str | None, *, limit: int
    ) -> Sequence[str]:
        assert repo_id == TARGET
        return tuple(self.history[:limit])

    def read_file(
        self, repo_id: str, revision: str, path: str, token: str | None
    ) -> bytes:
        assert repo_id == TARGET
        try:
            return self.files[(revision, path)]
        except KeyError as exc:
            raise publisher.RemoteVerificationError("missing test file") from exc

    def upload(
        self,
        release: Any,
        token: str,
        *,
        parent_commit: str,
        commit_message: str,
        commit_description: str,
    ) -> str:
        assert parent_commit == INITIAL_COMMIT
        assert token not in commit_message
        assert token not in commit_description
        assert release.idempotency_key in commit_description
        self.upload_calls += 1
        self.current_head = PUBLISHED_COMMIT
        self.history.insert(0, PUBLISHED_COMMIT)
        for path in release.directory.rglob("*"):
            if path.is_file():
                self.files[
                    (PUBLISHED_COMMIT, path.relative_to(release.directory).as_posix())
                ] = path.read_bytes()
        return PUBLISHED_COMMIT

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        token: str | None,
    ) -> Mapping[str, Any]:
        manifest = json.loads(
            (self.release_dir / "manifest.json").read_text()
        )
        configs = sorted(
            {
                item["config_name"]
                for item in manifest["artifacts"]
                if "config_name" in item
            }
        )
        if endpoint == "is-valid":
            return {"viewer": True}
        if endpoint == "splits":
            return {
                "splits": [
                    {"dataset": TARGET, "config": config, "split": "train"}
                    for config in configs
                ]
            }
        if endpoint == "parquet":
            return {
                "parquet_files": [
                    {
                        "config": item["config_name"],
                        "dataset": TARGET,
                        "filename": Path(item["path"]).name,
                        "size": item["byte_length"],
                        "split": "train",
                    }
                    for item in manifest["artifacts"]
                    if "config_name" in item
                ]
            }
        if endpoint == "first-rows":
            config = params["config"]
            record_id = "b" + ("z" * 58)
            values = {
                "record_id": record_id,
                "record_type": config,
                "authority": "candidate",
                "source_cids": ["b" + ("s" * 58)],
                "parent_cids": ["b" + ("p" * 58)],
                "config_cid": "b" + ("q" * 58),
                "record_json": _canonical(
                    {"record_id": record_id, "record_type": config}
                ).decode(),
            }
            return {
                "config": config,
                "dataset": TARGET,
                "features": [
                    {"feature_idx": index, "name": name, "type": {}}
                    for index, name in enumerate(self.viewer_columns)
                ],
                "rows": [
                    {
                        "row": {
                            name: values[name]
                            for name in self.viewer_columns
                            if name in values
                        },
                        "row_idx": 0,
                        "truncated_cells": [],
                    }
                ],
                "split": "train",
            }
        raise AssertionError(endpoint)


def _seed_remote(hub: FakeHub, release_dir: Path, revision: str) -> None:
    for path in release_dir.rglob("*"):
        if path.is_file():
            hub.files[
                (revision, path.relative_to(release_dir).as_posix())
            ] = path.read_bytes()


def test_default_is_credential_free_dry_run(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "hf_" + ("x" * 30)
    monkeypatch.setenv("HF_TOKEN", secret)
    before = {
        path.relative_to(staged_release).as_posix(): path.read_bytes()
        for path in staged_release.rglob("*")
        if path.is_file()
    }

    result = publisher.publish_release(staged_release)

    assert result["dry_run"] is True
    assert result["status"] == "planned"
    assert result["target_repo"] == TARGET
    assert result["source_revision"] == SOURCE_REVISION
    assert secret not in json.dumps(result)
    assert before == {
        path.relative_to(staged_release).as_posix(): path.read_bytes()
        for path in staged_release.rglob("*")
        if path.is_file()
    }


def test_execute_authenticates_uploads_verifies_and_proposes_receipt(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "hf_" + ("t" * 30)
    monkeypatch.setenv("CVEFIXES_TEST_TOKEN", token)
    hub = FakeHub(staged_release)

    receipt = publisher.publish_release(
        staged_release,
        execute=True,
        token_env="CVEFIXES_TEST_TOKEN",
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )

    serialized = json.dumps(receipt)
    assert hub.auth_calls == 1
    assert hub.upload_calls == 1
    assert receipt["status"] == "proposed"
    assert receipt["authoritative"] is False
    assert receipt["grants_completion_authority"] is False
    assert receipt["grants_execution_authority"] is False
    assert receipt["principal"] == "release-operator"
    assert receipt["hub_commit"] == PUBLISHED_COMMIT
    assert receipt["operation"] == "uploaded"
    assert receipt["verification"]["remote_revision_verified"] is True
    assert receipt["verification"]["remote_manifest_verified"] is True
    assert receipt["verification"]["remote_artifacts_verified"] is True
    assert receipt["verification"]["dataset_viewer"]["verified"] is True
    assert token not in serialized
    assert "token" not in serialized.casefold()
    assert all(value == token for value in hub.token_values)


def test_same_target_source_release_tuple_is_verified_without_upload(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("i" * 30))
    hub = FakeHub(staged_release)
    hub.current_head = PUBLISHED_COMMIT
    hub.history = [PUBLISHED_COMMIT, INITIAL_COMMIT]
    _seed_remote(hub, staged_release, PUBLISHED_COMMIT)

    receipt = publisher.publish_release(
        staged_release,
        execute=True,
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )

    assert hub.upload_calls == 0
    assert receipt["operation"] == "verified_existing"
    assert receipt["hub_commit"] == PUBLISHED_COMMIT


def test_missing_environment_token_fails_before_remote_access(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    hub = FakeHub(staged_release)

    with pytest.raises(publisher.AuthenticationError, match="environment variable"):
        publisher.publish_release(staged_release, execute=True, gateway=hub)

    assert hub.auth_calls == 0
    assert hub.upload_calls == 0


def test_viewer_schema_mismatch_prevents_receipt(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("v" * 30))
    hub = FakeHub(
        staged_release,
        viewer_columns=publisher.EXPECTED_COLUMNS[:-1],
    )

    with pytest.raises(
        publisher.ViewerNotReadyError, match="feature binding mismatch"
    ):
        publisher.publish_release(
            staged_release,
            execute=True,
            gateway=hub,
            viewer_attempts=1,
        )

    assert hub.upload_calls == 1


def test_remote_shard_mismatch_prevents_receipt(
    staged_release: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("r" * 30))
    hub = FakeHub(staged_release)
    original_upload = hub.upload

    def corrupting_upload(*args: Any, **kwargs: Any) -> str:
        revision = original_upload(*args, **kwargs)
        shard = next(
            path
            for revision_path, path in hub.files
            if revision_path == revision and path.endswith(".parquet")
        )
        hub.files[(revision, shard)] += b"corrupt"
        return revision

    hub.upload = corrupting_upload

    with pytest.raises(
        publisher.RemoteVerificationError, match="remote artifact verification"
    ):
        publisher.publish_release(staged_release, execute=True, gateway=hub)


def test_local_inventory_hash_schema_and_symlink_fail_closed(
    staged_release: Path, tmp_path: Path
) -> None:
    extra = staged_release / "unexpected.txt"
    extra.write_text("not in manifest")
    with pytest.raises(publisher.LocalReleaseError, match="exactly match"):
        publisher.load_local_release(staged_release)
    extra.unlink()

    shard = next(staged_release.rglob("*.parquet"))
    original = shard.read_bytes()
    shard.write_bytes(original + b"corrupt")
    with pytest.raises(publisher.LocalReleaseError, match="content mismatch"):
        publisher.load_local_release(staged_release)
    shard.write_bytes(original)

    (staged_release / "link").symlink_to(tmp_path)
    with pytest.raises(publisher.LocalReleaseError, match="symlinks"):
        publisher.load_local_release(staged_release)


def test_receipt_is_atomic_secret_free_and_read_only_verifiable(
    staged_release: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "hf_" + ("w" * 30)
    monkeypatch.setenv("HF_TOKEN", token)
    hub = FakeHub(staged_release)
    receipt = publisher.publish_release(
        staged_release,
        execute=True,
        gateway=hub,
        now=lambda: "2026-07-29T12:00:00Z",
    )
    output = tmp_path / "external" / "receipt.json"

    publisher.write_receipt(receipt, output)
    verification = publisher.verify_receipt(output, gateway=hub)

    assert verification["status"] == "verified"
    assert verification["hub_commit"] == PUBLISHED_COMMIT
    assert token not in output.read_text()
    assert not (output.parent / f".{output.name}.tmp").exists()
    with pytest.raises(publisher.PublicationError, match="already exists"):
        publisher.write_receipt(receipt, output)


def test_receipt_verification_rejects_authority_claim(
    staged_release: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_" + ("a" * 30))
    hub = FakeHub(staged_release)
    receipt = publisher.publish_release(
        staged_release, execute=True, gateway=hub
    )
    receipt["grants_completion_authority"] = True
    path = tmp_path / "forged.json"
    path.write_bytes(_canonical(receipt))

    with pytest.raises(publisher.LocalReleaseError, match="authority"):
        publisher.verify_receipt(path, gateway=hub)

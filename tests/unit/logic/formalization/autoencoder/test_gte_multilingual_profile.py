"""Asset-admission integrity tests; fixtures are not native model numerics."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py"
spec = importlib.util.spec_from_file_location("gte_multilingual_profile_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, allow_nan=False).encode()


@pytest.fixture
def assets(tmp_path, monkeypatch):
    model = tmp_path / "model"
    code = tmp_path / "code"
    model.mkdir()
    code.mkdir()
    raw = {
        ("model", "config.json"): encode({"model_type": "new", "hidden_size": 768,
             "max_position_embeddings": 8192, "auto_map": subject.AUTO_MAP}),
        ("model", "tokenizer_config.json"): encode({"tokenizer_class": "XLMRobertaTokenizer",
             "model_max_length": 32768}),
        ("model", "special_tokens_map.json"): encode({"cls_token": "<s>"}),
        ("model", "tokenizer.json"): encode({"version": "1.0", "model": {"type": "Unigram"}}),
        # Tiny opaque bytes test content integrity only. No tensor loader runs.
        ("model", "model.safetensors"): b"synthetic-not-a-native-model",
        ("code", "configuration.py"): b"raise AssertionError('must never be imported')\n",
        ("code", "modeling.py"): b"raise AssertionError('must never be imported')\n",
    }
    published = {}
    files = []
    for (role, name), content in raw.items():
        (model if role == "model" else code).joinpath(name).write_bytes(content)
        published[role, name] = {"sha256": digest(content), "bytes": len(content)}
        files.append({"relative_to": role, "path": name, **published[role, name]})
    monkeypatch.setattr(subject, "PUBLISHED_ASSETS", published)
    manifest = {"schema": subject.MANIFEST_SCHEMA, "model_revision": subject.MODEL_REV,
                "code_revision": subject.CODE_REV, "files": files}
    path = tmp_path / "assets.json"
    path.write_bytes(encode(manifest))
    return {"root": tmp_path, "model": model, "code": code, "manifest": manifest, "path": path}


def inspect(assets, expected=None):
    return subject.inspect_local_assets(assets["path"],
        expected_sha256=expected or digest(assets["path"].read_bytes()),
        model_directory=assets["model"], code_directory=assets["code"])


def save_manifest(assets):
    assets["path"].write_bytes(encode(assets["manifest"]))


def test_admission_binds_exact_profile_and_never_claims_model_inference(assets):
    result = inspect(assets)
    assert result["status"] == "available"
    assert result["profile_id"] == subject.PROFILE_ID
    assert result["manifest_sha256"] == digest(assets["path"].read_bytes())
    assert len(result["files"]) == 7
    assert result["unavailable_reasons"] == []
    assert result["proof_authority"] is False
    assert result["model_numerics_verified"] is False
    assert subject.PROFILE["max_tokens"] == 8192
    assert subject.PROFILE["dimension"] == 768
    assert subject.PROFILE["attention_implementation"] == "eager"


def test_missing_manifest_allows_only_optional_no_pin_and_does_not_create_roots(tmp_path):
    result = subject.inspect_local_assets(tmp_path / "assets.json", expected_sha256=None,
        model_directory=tmp_path / "model", code_directory=tmp_path / "code")
    assert result["status"] == "unavailable"
    assert result["manifest_sha256"] is None
    assert result["unavailable_reasons"] == ["missing_manifest"]
    assert not (tmp_path / "model").exists()


def test_existing_manifest_requires_expected_sha256(assets):
    with pytest.raises(ValueError, match="expected manifest SHA256"):
        subject.inspect_local_assets(assets["path"], expected_sha256=None,
            model_directory=assets["model"], code_directory=assets["code"])


def test_expected_manifest_hash_mismatch_stops_admission(assets):
    with pytest.raises(ValueError, match="manifest SHA256 mismatch"):
        inspect(assets, "0" * 64)


@pytest.mark.parametrize("missing", ["model.safetensors", "tokenizer.json", "configuration.py"])
def test_missing_required_file_is_unavailable(assets, missing):
    role = "code" if missing.endswith(".py") else "model"
    (assets[role] / missing).unlink()
    result = inspect(assets)
    assert result["status"] == "unavailable"
    assert "missing_asset:" + role + "/" + missing in result["unavailable_reasons"]


def test_missing_manifest_entry_is_explicitly_unavailable(assets):
    assets["manifest"]["files"] = [entry for entry in assets["manifest"]["files"]
                                     if entry["path"] != "model.safetensors"]
    save_manifest(assets)
    result = inspect(assets)
    assert "missing_manifest_entry:model/model.safetensors" in result["unavailable_reasons"]


@pytest.mark.parametrize("role", ["model", "code"])
def test_missing_root_is_unavailable(assets, role):
    for path in assets[role].iterdir():
        path.unlink()
    assets[role].rmdir()
    result = inspect(assets)
    assert result["status"] == "unavailable"
    assert "missing_" + role + "_directory" in result["unavailable_reasons"]


@pytest.mark.parametrize("field", ["model_revision", "code_revision", "schema"])
def test_existing_manifest_rejects_wrong_pins_and_schema(assets, field):
    assets["manifest"][field] = "wrong"
    save_manifest(assets)
    with pytest.raises(ValueError):
        inspect(assets)


@pytest.mark.parametrize("field", ["manifest", "entry"])
def test_unknown_manifest_or_entry_fields_fail(assets, field):
    value = assets["manifest"] if field == "manifest" else assets["manifest"]["files"][0]
    value["unknown"] = True
    save_manifest(assets)
    with pytest.raises(ValueError, match="closed schema"):
        inspect(assets)


def test_duplicate_manifest_entries_fail(assets):
    assets["manifest"]["files"][0] = dict(assets["manifest"]["files"][1])
    save_manifest(assets)
    with pytest.raises(ValueError, match="duplicate asset"):
        inspect(assets)


@pytest.mark.parametrize("path", ["../config.json", "/config.json", "./config.json", "code\\configuration.py", "nested//config.json"])
def test_manifest_path_escape_or_ambiguous_spelling_fails(assets, path):
    assets["manifest"]["files"][0]["path"] = path
    save_manifest(assets)
    with pytest.raises(ValueError):
        inspect(assets)


@pytest.mark.parametrize("key,value", [("sha256", "0" * 64), ("bytes", True), ("bytes", 0), ("bytes", 9)])
def test_published_asset_hash_and_size_are_independent_of_caller_pin(assets, key, value):
    assets["manifest"]["files"][0][key] = value
    save_manifest(assets)
    with pytest.raises(ValueError):
        inspect(assets)


@pytest.mark.parametrize("file", ["model.safetensors", "config.json", "modeling.py"])
def test_asset_content_change_fails_even_if_manifest_does_not_change(assets, file):
    role = "code" if file.endswith(".py") else "model"
    path = assets[role] / file
    raw = path.read_bytes()
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match="asset SHA256 mismatch"):
        inspect(assets)


@pytest.mark.parametrize("file", ["surprise.py", "surprise.so", "pytorch_model.bin", "weights.pkl", "other.safetensors", "model.safetensors.index.json"])
def test_unknown_code_pickle_and_sharded_weights_fail(assets, file):
    (assets["model"] / file).write_text("unused but forbidden")
    with pytest.raises(ValueError):
        inspect(assets)


@pytest.mark.parametrize("location", ["manifest", "root", "asset", "nested"])
def test_symlinks_are_rejected(assets, location):
    if location == "manifest":
        original = assets["path"]
        replacement = original.with_name("real-manifest.json")
        original.rename(replacement)
        original.symlink_to(replacement)
    elif location == "root":
        original = assets["model"]
        replacement = original.with_name("real-model")
        original.rename(replacement)
        original.symlink_to(replacement, target_is_directory=True)
    elif location == "asset":
        original = assets["model"] / "config.json"
        replacement = assets["root"] / "real-config.json"
        original.rename(replacement)
        original.symlink_to(replacement)
    else:
        (assets["model"] / "nested").symlink_to(assets["code"], target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        inspect(assets)


def test_ancestor_symlink_is_rejected_even_outside_asset_root(assets):
    alias = assets["root"] / "alias"
    alias.symlink_to(assets["root"], target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        subject.inspect_local_assets(alias / "assets.json",
            expected_sha256=digest(assets["path"].read_bytes()), model_directory=assets["model"],
            code_directory=assets["code"])


@pytest.mark.parametrize("kind", ["same", "nested", "relative"])
def test_roots_must_be_absolute_and_independent(assets, kind):
    code = assets["model"] if kind == "same" else assets["model"] / "nested"
    if kind == "relative":
        code = "relative-code"
    with pytest.raises(ValueError):
        subject.inspect_local_assets(assets["path"], expected_sha256=digest(assets["path"].read_bytes()),
            model_directory=assets["model"], code_directory=code)


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{"value":1e999}', b'[]', b'{'])
def test_json_is_strict_even_when_caller_hash_matches(assets, raw):
    assets["path"].write_bytes(raw)
    with pytest.raises(ValueError):
        inspect(assets)


def test_json_manifest_byte_bound_is_enforced(assets, monkeypatch):
    monkeypatch.setattr(subject, "MAX_MANIFEST_BYTES", 8)
    with pytest.raises(ValueError, match="size bound"):
        inspect(assets)


def test_weight_digest_streams_using_bounded_reads(assets, monkeypatch):
    monkeypatch.setattr(subject, "HASH_CHUNK_BYTES", 4)
    assert inspect(assets)["status"] == "available"


def test_wrong_weight_size_fails_before_hashing_weight_payload(assets, monkeypatch):
    weight = assets["model"] / "model.safetensors"
    weight.write_bytes(weight.read_bytes() + b"unexpected extra bytes")
    original = subject._read_or_hash

    def guarded(path, *args, **kwargs):
        assert path != weight, "incorrect-size weight should not be hashed"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(subject, "_read_or_hash", guarded)
    with pytest.raises(ValueError, match="asset byte count mismatch"):
        inspect(assets)


def test_stat_change_after_individual_file_read_is_rejected(assets, monkeypatch):
    original = subject._file_stat
    calls = 0

    def changing(path):
        nonlocal calls
        if path == assets["code"] / "configuration.py":
            calls += 1
            if calls == 3:
                with path.open("ab") as stream:
                    stream.write(b"# change after hash\n")
        return original(path)

    monkeypatch.setattr(subject, "_file_stat", changing)
    with pytest.raises(ValueError, match="changed during inspection"):
        inspect(assets)


@pytest.mark.parametrize("key,value", [("hidden_size", 786), ("max_position_embeddings", 32768), ("auto_map", {}), ("model_type", "bert")])
def test_configuration_semantics_are_checked_with_synthetic_pinned_bytes(assets, monkeypatch, key, value):
    path = assets["model"] / "config.json"
    document = json.loads(path.read_bytes())
    document[key] = value
    content = encode(document)
    path.write_bytes(content)
    published = dict(subject.PUBLISHED_ASSETS)
    published["model", "config.json"] = {"sha256": digest(content), "bytes": len(content)}
    monkeypatch.setattr(subject, "PUBLISHED_ASSETS", published)
    assets["manifest"]["files"][0].update(published["model", "config.json"])
    save_manifest(assets)
    with pytest.raises(ValueError, match="configuration"):
        inspect(assets)


def test_tokenizer_remote_code_is_not_supported(assets, monkeypatch):
    path = assets["model"] / "tokenizer_config.json"
    content = encode({"auto_map": {"AutoTokenizer": "unknown.code"}})
    path.write_bytes(content)
    published = dict(subject.PUBLISHED_ASSETS)
    published["model", "tokenizer_config.json"] = {"sha256": digest(content), "bytes": len(content)}
    monkeypatch.setattr(subject, "PUBLISHED_ASSETS", published)
    assets["manifest"]["files"][1].update(published["model", "tokenizer_config.json"])
    save_manifest(assets)
    with pytest.raises(ValueError, match="tokenizer executable"):
        inspect(assets)


def test_directory_entry_bound_is_enforced(assets, monkeypatch):
    monkeypatch.setattr(subject, "MAX_DIRECTORY_ENTRIES", 1)
    with pytest.raises(ValueError, match="entry bound"):
        inspect(assets)

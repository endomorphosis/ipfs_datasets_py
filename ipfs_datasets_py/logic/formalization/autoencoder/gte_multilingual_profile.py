"""Pinned, read-only local asset admission for the 768D GTE CPU profile.

Only the standard library is imported. This module never downloads assets,
imports model code, loads tensor weights, or claims semantic qualification.
Local files must be ordinary files, not Hugging Face cache symlinks.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat

MODEL_REPO = "Alibaba-NLP/gte-multilingual-base"
MODEL_REV = "9bbca17d9273fd0d03d5725c7a4b0f6b45142062"
CODE_REPO = "Alibaba-NLP/new-impl"
CODE_REV = "40ced75c3017eb27626c9d4ea981bde21a2662f4"
PROFILE_ID = (f"{MODEL_REPO}@{MODEL_REV}:code={CODE_REPO}@{CODE_REV}:"
              "d768:pool=cls:norm=l2:cpu:float32:tokens8192:reject_overlength:v1")
PROFILE = {"dimension": 768, "max_tokens": 8192, "pooling": "cls",
           "normalization": "l2", "device": "cpu", "dtype": "float32",
           "attention_implementation": "eager", "overlength_policy": "reject"}
MANIFEST_SCHEMA = "gte-multilingual-local-assets/v1"
RECEIPT_SCHEMA = "gte-multilingual-local-assets-receipt/v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_WEIGHT_BYTES = 16 * 1024 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
MAX_DIRECTORY_ENTRIES = 10000

# These hashes identify published content at the two pinned revisions, not
# caller-supplied claims about a revision. LFS hashes come from the pinned HF
# tree API; small-file hashes come from the pinned resolve endpoint bytes.
PUBLISHED_ASSETS = {
    ("model", "config.json"): {"sha256": "711bdc81365fc25d30533cf05b9fdf588e5ba01f18540fbbb1307d787597a313", "bytes": 1429},
    ("model", "tokenizer_config.json"): {"sha256": "24cebbf2ef20fc317256e03e52ac7b2ca326586f946a8427ecac036332bf0933", "bytes": 1149},
    ("model", "special_tokens_map.json"): {"sha256": "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835", "bytes": 964},
    ("model", "tokenizer.json"): {"sha256": "f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af", "bytes": 17082756},
    ("model", "model.safetensors"): {"sha256": "f5a35a10faa54da7717870af1517c9b41e9bd8e3880bc5a8e9363d4c3c63e9b0", "bytes": 610753338},
    ("code", "configuration.py"): {"sha256": "3411088045ffb8a9a0aa9936eae275896b39983a2ee5b08f091b44e6289e4fe4", "bytes": 7127},
    ("code", "modeling.py"): {"sha256": "374670b416fcc82f081c9cd28b5fd61c2bd91bbe18eb4798fcc48a81f9c250a0", "bytes": 59023},
}
AUTO_MAP = {
    "AutoConfig": f"{CODE_REPO}--configuration.NewConfig",
    "AutoModel": f"{CODE_REPO}--modeling.NewModel",
    "AutoModelForMaskedLM": f"{CODE_REPO}--modeling.NewForMaskedLM",
    "AutoModelForMultipleChoice": f"{CODE_REPO}--modeling.NewForMultipleChoice",
    "AutoModelForQuestionAnswering": f"{CODE_REPO}--modeling.NewForQuestionAnswering",
    "AutoModelForSequenceClassification": f"{CODE_REPO}--modeling.NewForSequenceClassification",
    "AutoModelForTokenClassification": f"{CODE_REPO}--modeling.NewForTokenClassification",
}
_EXECUTABLE_SUFFIXES = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib", ".exe", ".sh"}
_UNSUPPORTED_WEIGHT_SUFFIXES = {".bin", ".pt", ".pth", ".ckpt", ".pkl", ".pickle", ".h5"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value, label):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             label + " must be a lowercase SHA256")
    return value


def _absolute(value, label):
    _require(isinstance(value, (str, os.PathLike)), label + " must be an absolute local path")
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts,
             label + " must be absolute without traversal")
    return path


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _open_file(path):
    """Open every path component with NOFOLLOW, including ancestor directories."""
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=parent)
            os.close(parent)
            parent = next_fd
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                             dir_fd=parent)
        return descriptor
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            raise
        raise ValueError("asset path must contain ordinary files and directories without symlinks") from error
    finally:
        os.close(parent)


def _file_stat(path):
    descriptor = _open_file(path)
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode), "regular asset file required")
        return info
    finally:
        os.close(descriptor)


def _read_or_hash(path, limit, *, retain=False):
    descriptor = _open_file(path)
    chunks = [] if retain else None
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "regular asset file required")
        _require(0 < before.st_size <= limit, "asset file is empty or exceeds size bound")
        total = 0
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while True:
                chunk = stream.read(min(HASH_CHUNK_BYTES, limit - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                _require(total <= limit, "asset file exceeds size bound")
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
        after = os.fstat(descriptor)
        _require(total == before.st_size and _identity(before) == _identity(after),
                 "asset file changed while reading")
    finally:
        os.close(descriptor)
    _require(_identity(before) == _identity(_file_stat(path)), "asset file changed while reading")
    return digest.hexdigest(), total, b"".join(chunks) if chunks is not None else None, _identity(before)


def _parse_json(raw, label):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON number in " + label)

    def number(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite JSON number in " + label)
        return parsed

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=number)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON in " + label) from error
    _require(type(value) is dict, label + " must be a JSON object")
    return value


def _directory(path):
    # A nonexistent root is unavailable; an existing symlink/other type fails.
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            try:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=descriptor)
            except FileNotFoundError:
                return False
            except OSError as error:
                raise ValueError("asset roots must be directories without symlinks") from error
            os.close(descriptor)
            descriptor = next_fd
        return True
    finally:
        os.close(descriptor)


def _scan_root(root, role):
    entries = 0

    def inaccessible(error):
        raise ValueError("cannot inspect asset directory") from error

    for directory, directories, files in os.walk(root, followlinks=False, onerror=inaccessible):
        for name in directories + files:
            entries += 1
            _require(entries <= MAX_DIRECTORY_ENTRIES, "asset directory entry bound exceeded")
            path = Path(directory) / name
            info = path.lstat()
            _require(not stat.S_ISLNK(info.st_mode), "symlinks are forbidden in asset roots")
            if name in directories:
                _require(stat.S_ISDIR(info.st_mode), "ordinary asset directory required")
                continue
            _require(stat.S_ISREG(info.st_mode), "ordinary asset file required")
            relative = path.relative_to(root).as_posix()
            key = role, relative
            _require(path.suffix.lower() not in _EXECUTABLE_SUFFIXES or key in PUBLISHED_ASSETS,
                     "unknown executable code in asset root: " + relative)
            _require(path.suffix.lower() not in _UNSUPPORTED_WEIGHT_SUFFIXES,
                     "pickle or unsupported weight format is forbidden: " + relative)
            _require(not (name.endswith(".safetensors") and key not in PUBLISHED_ASSETS)
                     and not name.endswith(".safetensors.index.json"),
                     "sharded or unknown weights are unsupported")


def _manifest_entries(manifest):
    _require(set(manifest) == {"schema", "model_revision", "code_revision", "files"},
             "manifest fields must match the closed schema")
    _require(manifest["schema"] == MANIFEST_SCHEMA, "unsupported local-assets manifest schema")
    _require(manifest["model_revision"] == MODEL_REV and manifest["code_revision"] == CODE_REV,
             "model and code revision pins do not match the profile")
    _require(type(manifest["files"]) is list and len(manifest["files"]) <= len(PUBLISHED_ASSETS),
             "manifest files must be a bounded list")
    entries = {}
    for entry in manifest["files"]:
        _require(type(entry) is dict and set(entry) == {"relative_to", "path", "sha256", "bytes"},
                 "asset entry fields must match the closed schema")
        role, name = entry["relative_to"], entry["path"]
        _require(type(role) is str and role in {"model", "code"}, "invalid asset root role")
        _require(type(name) is str and name and "\\" not in name and "\x00" not in name,
                 "asset path must be a relative POSIX path")
        relative = PurePosixPath(name)
        _require(not relative.is_absolute() and ".." not in relative.parts
                 and relative.as_posix() == name and "." not in relative.parts,
                 "asset path must be relative without traversal")
        key = role, name
        _require(key in PUBLISHED_ASSETS, "asset file is outside the admitted profile closure")
        _require(key not in entries, "duplicate asset entry")
        _sha(entry["sha256"], "asset SHA256")
        _require(type(entry["bytes"]) is int and 0 < entry["bytes"] <= MAX_WEIGHT_BYTES,
                 "asset bytes must be a bounded positive integer")
        published = PUBLISHED_ASSETS[key]
        _require(entry["sha256"] == published["sha256"], "asset SHA256 does not match published revision")
        _require(entry["bytes"] == published["bytes"],
                 "asset bytes do not match published revision")
        entries[key] = dict(entry)
    return entries


def inspect_local_assets(manifest_path, *, expected_sha256, model_directory, code_directory):
    """Authenticate a closed, explicit local asset set without loading a model.

    Missing inputs return ``status='unavailable'``. Existing malformed inputs,
    mismatched pins/hashes, symlinks, unsupported weights, and unknown executable
    code raise ``ValueError``. An absent manifest may use ``expected_sha256=None``;
    an existing manifest always requires a real caller-supplied SHA256 pin.
    """
    manifest_path = _absolute(manifest_path, "manifest_path")
    roots = {"model": _absolute(model_directory, "model_directory"),
             "code": _absolute(code_directory, "code_directory")}
    _require(roots["model"] != roots["code"] and not roots["model"].is_relative_to(roots["code"])
             and not roots["code"].is_relative_to(roots["model"]), "asset roots must be separate")
    if expected_sha256 is not None:
        _sha(expected_sha256, "expected manifest SHA256")
    # Validate existing roots even when the manifest is not present. Missing
    # roots remain ordinary unavailable inputs; an existing symlink is invalid.
    available_roots = {role: _directory(root) for role, root in roots.items()}
    result = {"schema": RECEIPT_SCHEMA, "status": "unavailable", "profile_id": PROFILE_ID,
              "model_revision": MODEL_REV, "code_revision": CODE_REV,
              "manifest_sha256": None, "model_directory": str(roots["model"]),
              "code_directory": str(roots["code"]), "files": [], "unavailable_reasons": [],
              "proof_authority": False, "model_numerics_verified": False}
    try:
        manifest_digest, _, raw, manifest_identity = _read_or_hash(
            manifest_path, MAX_MANIFEST_BYTES, retain=True)
    except FileNotFoundError:
        result["unavailable_reasons"].append("missing_manifest")
        return result
    _sha(expected_sha256, "expected manifest SHA256")
    _require(manifest_digest == expected_sha256, "manifest SHA256 mismatch")
    result["manifest_sha256"] = manifest_digest
    entries = _manifest_entries(_parse_json(raw, "assets manifest"))
    for role, root in roots.items():
        if not available_roots[role]:
            result["unavailable_reasons"].append("missing_" + role + "_directory")
        else:
            _scan_root(root, role)
    checked = []
    for key in sorted(PUBLISHED_ASSETS):
        role, name = key
        if key not in entries:
            result["unavailable_reasons"].append("missing_manifest_entry:" + role + "/" + name)
            continue
        if not available_roots[role]:
            continue
        path = roots[role] / name
        bound = MAX_WEIGHT_BYTES if name == "model.safetensors" else MAX_JSON_BYTES
        try:
            _require(_file_stat(path).st_size == entries[key]["bytes"],
                     "asset byte count mismatch: " + role + "/" + name)
            digest, count, file_raw, identity = _read_or_hash(path, bound, retain=name.endswith(".json"))
        except FileNotFoundError:
            result["unavailable_reasons"].append("missing_asset:" + role + "/" + name)
            continue
        _require(digest == entries[key]["sha256"], "asset SHA256 mismatch: " + role + "/" + name)
        _require(count == entries[key]["bytes"], "asset byte count mismatch: " + role + "/" + name)
        if file_raw is not None:
            document = _parse_json(file_raw, name)
            if name == "config.json":
                _require(document.get("hidden_size") == 768 and type(document.get("hidden_size")) is int
                         and document.get("max_position_embeddings") == 8192
                         and type(document.get("max_position_embeddings")) is int
                         and document.get("model_type") == "new" and document.get("auto_map") == AUTO_MAP,
                         "model configuration does not match the 768D profile")
            elif name == "tokenizer_config.json":
                _require(not document.get("auto_map"), "tokenizer executable auto_map is unsupported")
        checked.append((path, identity))
        result["files"].append(dict(entries[key]))
    # Catch replacements between individual file reads and completion. The
    # worker must retain the same pins when it loads assets after admission.
    for path, identity in [(manifest_path, manifest_identity), *checked]:
        _require(_identity(_file_stat(path)) == identity, "asset file changed during inspection")
    for role, root in roots.items():
        if available_roots[role]:
            _scan_root(root, role)
    if not result["unavailable_reasons"]:
        result["status"] = "available"
    return result

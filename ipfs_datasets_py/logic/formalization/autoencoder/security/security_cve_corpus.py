"""Explicit, bounded Publicus corpus profiles and family-separated code inputs.

The immutable control plane selects original rows; the existing native canonical
export verifies their preimages. Retrieval/policy graph counts are never returned
as model input features. This module creates no weights and changes no existing
training, export or checkpoint contract.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import urlopen

from . import security_cve_canonical_export as canonical
from .security_cve_training_source import BenchmarkExclusions, CVETrainingSourceError, HuggingFaceSourcePin, _family, native

DATASET_ID = "Publicus/cvefixes-security-ir-graphrag"
PROFILE_SCHEMA = "publicus-security-code-corpus-profile@1"
SCHEMA = "publicus-security-code-corpus@1"
SPLITS = ("train", "validation", "test")
MAX_RESPONSE = 1024 * 1024
PROFILE_FIELDS = {"schema", "pin", "repository_splits", "graph_shards", "benchmark_exclusions",
    "budget", "split_unit", "proof_authority", "execution_authority"}
MANIFEST_FIELDS = {"schema", "profile", "profile_sha256", "source_inspection", "exports", "totals",
    "input_semantics", "target_semantics", "holdout_evaluated", "proof_authority", "execution_authority"}
INSPECTION_FIELDS = {"pin", "native_control_receipt", "artifact_groups", "canonical_rows_reconstructed_from",
    "retrieval_tables_are_code_training_examples", "original_bodies_loaded_by_inspection",
    "policy_and_formal_views", "proof_authority", "execution_authority"}


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CVETrainingSourceError("exact corpus SHA256 required")
    return value


def _portable_manifest(value):
    canonical._reject_raw_fields(value)
    if isinstance(value, dict):
        if set(value) & {"raw_body", "body_text", "raw_source", "source_excerpt"}:
            raise CVETrainingSourceError("raw bodies are excluded from corpus manifests")
        for key, item in value.items():
            if key in {"proof_authority", "execution_authority", "grants_execution_authority",
                       "formalization_authority", "completion_authority", "proof_authoritative"} and item is not False:
                raise CVETrainingSourceError("corpus metadata cannot confer authority")
            _portable_manifest(item)
    elif isinstance(value, list):
        for item in value:
            _portable_manifest(item)


def _inspection(value, pin):
    if (type(value) is not dict or set(value) != INSPECTION_FIELDS or value["pin"] != pin.to_dict()
            or any(value[key] is not False for key in ("proof_authority", "execution_authority",
                "retrieval_tables_are_code_training_examples", "original_bodies_loaded_by_inspection"))
            or value["canonical_rows_reconstructed_from"] != "CID-verified original source rows through native canonical projector/classifier"
            or value["policy_and_formal_views"] != "classification-only candidate targets; unresolved action/scope; no proved formulas"):
        raise CVETrainingSourceError("closed non-authoritative corpus inspection required")
    receipt = native.HuggingFaceCompleteReleaseReceipt(**value["native_control_receipt"])
    if any(getattr(receipt, key) != getattr(pin, key) for key in ("dataset_id", "revision", "manifest_sha256", "release_root")):
        raise CVETrainingSourceError("native corpus receipt pin differs")
    for key, item in asdict(receipt).items():
        if key.endswith("_root") and (type(item) is not str or re.fullmatch(r"b[a-z2-7]{58}", item) is None):
            raise CVETrainingSourceError("native corpus root must be a content identity")
        if key.endswith("_count") and (type(item) is not int or not 0 <= item <= 10**12):
            raise CVETrainingSourceError("native corpus counts must be bounded integers")
    if receipt.offline is not True:
        raise CVETrainingSourceError("corpus inspection must use verified local control files")
    groups = value["artifact_groups"]
    if type(groups) is not dict or not groups or len(groups) > 32:
        raise CVETrainingSourceError("bounded corpus artifact groups required")
    for key, group in groups.items():
        if (type(key) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) is None
                or type(group) is not dict or set(group) != {"files", "bytes", "rows"}
                or any(type(count) is not int or count < 0 for count in group.values())):
            raise CVETrainingSourceError("closed counted corpus artifact group required")
    _portable_manifest(value)


def _profile(profile):
    if type(profile) is not dict or set(profile) != PROFILE_FIELDS or profile["schema"] != PROFILE_SCHEMA:
        raise CVETrainingSourceError("closed Publicus corpus profile required")
    pin = HuggingFaceSourcePin.from_dict(profile["pin"])
    if pin.dataset_id != DATASET_ID:
        raise CVETrainingSourceError("explicit Publicus SecurityIR corpus required")
    exclusions = BenchmarkExclusions(**profile["benchmark_exclusions"])
    if asdict(exclusions) != {k: tuple(v) for k, v in profile["benchmark_exclusions"].items()}:
        raise CVETrainingSourceError("canonical benchmark exclusions required")
    if (profile["split_unit"] != "canonical_repository_family"
            or profile["proof_authority"] is not False or profile["execution_authority"] is not False):
        raise CVETrainingSourceError("family separation cannot confer program authority")
    splits, budget = profile["repository_splits"], profile["budget"]
    if type(splits) is not dict or set(splits) != set(SPLITS):
        raise CVETrainingSourceError("explicit train, validation and test repository families required")
    families = []
    for name in SPLITS:
        urls = splits[name]
        if type(urls) is not list or not 1 <= len(urls) <= 4:
            raise CVETrainingSourceError("one to four explicit families per split required")
        for url in urls:
            family = _family(url)
            if exclusions.excludes_family(url):
                raise CVETrainingSourceError("benchmark family excluded before metadata or original-row access")
            families.append(family)
    if len(set(families)) != len(families):
        raise CVETrainingSourceError("repository families must be disjoint across all split assignments")
    if (type(budget) is not dict or set(budget) != {"max_original_rows", "max_response_bytes", "max_total_response_bytes"}
            or any(type(v) is not int for v in budget.values())
            or not len(families) <= budget["max_original_rows"] <= 12
            or not 1 <= budget["max_response_bytes"] <= MAX_RESPONSE
            or not budget["max_response_bytes"] <= budget["max_total_response_bytes"] <= 12 * MAX_RESPONSE):
        raise CVETrainingSourceError("explicit bounded corpus row and transport budget required")
    shards = profile["graph_shards"]
    if (type(shards) is not list or not 1 <= len(shards) <= 4 or len(set(shards)) != len(shards)
            or any(type(p) is not str or re.fullmatch(r"data/graph/nodes/part-[0-9]{6}\.parquet", p) is None for p in shards)):
        raise CVETrainingSourceError("bounded derived graph selection required")
    return pin, exclusions


def build_security_corpus_profile(*, pin: HuggingFaceSourcePin, repository_splits: dict,
                                 graph_shards, exclusions: BenchmarkExclusions,
                                 max_original_rows=12, max_response_bytes=MAX_RESPONSE,
                                 max_total_response_bytes=12 * MAX_RESPONSE):
    """Freeze source identity, family split and accepted selected-row JSON budget.

    A custom transport that downloads shards or ranges must enforce and receipt
    its actual network-byte budget separately, including preparation and failures.
    The accepted row-response budget cannot stand in for total network ingress.
    """
    value = {"schema": PROFILE_SCHEMA, "pin": pin.to_dict(),
        "repository_splits": {name: list(urls) for name, urls in repository_splits.items()},
        "graph_shards": list(graph_shards), "benchmark_exclusions": asdict(exclusions),
        "budget": {"max_original_rows": max_original_rows, "max_response_bytes": max_response_bytes,
                   "max_total_response_bytes": max_total_response_bytes},
        "split_unit": "canonical_repository_family", "proof_authority": False, "execution_authority": False}
    value = json.loads(_bytes(value))
    _profile(value)
    return value


def validate_security_corpus_profile(profile: dict):
    """Return an independently copied, validated JSON profile without I/O."""
    value = json.loads(_bytes(profile))
    _profile(value)
    return value


def inspect_security_corpus(*, metadata_root: Path, pin: HuggingFaceSourcePin):
    """Verify manifest, original-row routing and control tables without code reads."""
    if type(pin) is not HuggingFaceSourcePin or pin.dataset_id != DATASET_ID:
        raise CVETrainingSourceError("explicit Publicus SecurityIR pin required")
    loaded = native.load_huggingface_complete_release(metadata_root, pin, offline=True)
    root = Path(metadata_root).resolve(strict=True)
    raw = native._bounded_bytes(native._safe_file(root, "manifest.json"), 8 * MAX_RESPONSE, "manifest")
    if _sha(raw) != pin.manifest_sha256:
        raise CVETrainingSourceError("corpus manifest changed after native verification")
    manifest = native._strict_json_object(raw, "corpus manifest")
    groups = {}
    for item in manifest["artifacts"]:
        group = groups.setdefault(item.get("config_name", "control"), {"files": 0, "bytes": 0, "rows": 0})
        group["files"] += 1; group["bytes"] += item["byte_length"]; group["rows"] += item.get("row_count", 0)
    result = {"pin": pin.to_dict(), "native_control_receipt": asdict(loaded.receipt), "artifact_groups": groups,
        "canonical_rows_reconstructed_from": "CID-verified original source rows through native canonical projector/classifier",
        "retrieval_tables_are_code_training_examples": False, "original_bodies_loaded_by_inspection": False,
        "policy_and_formal_views": "classification-only candidate targets; unresolved action/scope; no proved formulas",
        "proof_authority": False, "execution_authority": False}
    _inspection(result, pin)
    return result


def _root(path, *, fresh=False):
    path = Path(path)
    if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
            or (fresh and path.exists()) or any(x.lower() in {"legal-ir", "legal_ir", "shared-weights"} for x in path.parts)):
        raise CVETrainingSourceError("fresh isolated canonical security corpus namespace required")
    return path


def _project_pair(pair):
    inputs = pair["input"]
    # Labels and graph counts are target-derived. Do not let them become source
    # features just because the legacy canonical envelope retains both objects.
    return {"row_id": pair["row_id"], "source_cid": pair["source_cid"],
        "source_family": pair["source_family"], "source_paths": pair["source_paths"],
        "body_sha256": pair["body_sha256"], "source_record_cid": pair["source_record_cid"],
        "code_unit_cids": pair["code_unit_cids"], "candidate_cid": pair["candidate_cid"],
        "input": {key: inputs[key] for key in ("lexical_token_counts", "tokenizer", "tokenizer_sha256",
            "ast_projection_family", "ast_feature_vocabulary", "ast_samples", "ast_status", "ast_source_path_kind")},
        "target": pair["target"], "proof_authority": False, "execution_authority": False}


def fetch_corpus_cve_row(selection, maximum=MAX_RESPONSE):
    """Resolve one row from the Publicus release's declared upstream source.

    The viewer cannot pin a source commit. A changed, truncated, reordered or
    otherwise unexpected response fails canonical source-preimage verification.
    Publicus selects the identity; the native manifest separately pins its
    hitoshura25/cvefixes ancestry. No retry or whole-shard download is implicit.
    """
    if (type(selection) is not canonical.SelectedCVERow or type(maximum) is not int
            or not 0 < maximum <= MAX_RESPONSE):
        raise CVETrainingSourceError("bounded metadata-selected corpus row required")
    _family(selection.repository_url)
    url = "https://datasets-server.huggingface.co/rows?" + urlencode({
        "dataset": canonical.CVEFIXES_DATASET_ID, "config": "default", "split": "train",
        "offset": selection.row_index, "length": 1})
    with urlopen(url, timeout=55) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise CVETrainingSourceError("corpus selected row response exceeds byte budget")
    return raw


def load_security_corpus(root: Path, *, expected_manifest_sha256: str):
    """Revalidate all canonical records, family splits and cross-split body hashes."""
    root = _root(root)
    if {p.name for p in root.iterdir()} != {"corpus-manifest.json", *SPLITS}:
        raise CVETrainingSourceError("closed corpus split inventory required")
    raw = canonical.codebase_autoencoder._read(root / "corpus-manifest.json", limit=4 * MAX_RESPONSE)
    if _sha(raw) != _digest(expected_manifest_sha256):
        raise CVETrainingSourceError("corpus manifest digest differs")
    manifest = native._strict_json_object(raw, "corpus manifest")
    if type(manifest) is not dict or set(manifest) != MANIFEST_FIELDS or manifest["schema"] != SCHEMA:
        raise CVETrainingSourceError("closed source-bound corpus manifest required")
    pin, exclusions = _profile(manifest["profile"])
    _portable_manifest(manifest)
    _inspection(manifest["source_inspection"], pin)
    if (manifest["profile_sha256"] != _sha(_bytes(manifest["profile"]))
            or manifest["proof_authority"] is not False or manifest["execution_authority"] is not False
            or manifest["holdout_evaluated"] is not False
            or manifest["input_semantics"] != "source-body lexical and optional AST observations only"
            or manifest["target_semantics"] != "native audit/CWE/polarity classification candidates, not formulas or proofs"
            or set(manifest["exports"]) != set(SPLITS)
            or manifest["source_inspection"].get("pin") != pin.to_dict()):
        raise CVETrainingSourceError("corpus pin, semantics or authority differs")
    body_splits, source_splits, rows, totals = {}, {}, {}, {"original_rows": 0, "training_pairs": 0, "response_bytes": 0}
    shared_source_ledger = None
    for split in SPLITS:
        descriptor = manifest["exports"][split]
        if type(descriptor) is not dict or set(descriptor) != {"path", "manifest_sha256"} or descriptor["path"] != split:
            raise CVETrainingSourceError("exact relative split export binding required")
        loaded = canonical.load_canonical_cve_training(root / split, expected_manifest_sha256=_digest(descriptor["manifest_sha256"]))
        exported = loaded["manifest"]
        _portable_manifest(exported)
        graphs = exported["graph_artifacts"]
        if (type(graphs) is not list or len(graphs) != len(manifest["profile"]["graph_shards"])
                or any(type(item) is not dict or set(item) != {"path", "sha256", "content_id"} for item in graphs)
                or {item["path"] for item in graphs} != set(manifest["profile"]["graph_shards"])
                or exported["native_control_receipt"] != manifest["source_inspection"]["native_control_receipt"]):
            raise CVETrainingSourceError("canonical split graph selection or control receipt differs")
        for item in graphs:
            _digest(item["sha256"])
            if type(item["content_id"]) is not str or re.fullmatch(r"b[a-z2-7]{58}", item["content_id"]) is None:
                raise CVETrainingSourceError("canonical graph content identity required")
        _digest(exported["routing_index_sha256"])
        source_ledger = {"graph_artifacts": sorted(graphs, key=lambda item: item["path"]),
                         "routing_index_sha256": exported["routing_index_sha256"]}
        if shared_source_ledger is not None and source_ledger != shared_source_ledger:
            raise CVETrainingSourceError("split graph or routing ledger differs")
        shared_source_ledger = source_ledger
        wanted = {_family(x) for x in manifest["profile"]["repository_splits"][split]}
        if (exported["pin"] != pin.to_dict()
                or exported["benchmark_exclusions"] != json.loads(_bytes(asdict(exclusions)))):
            raise CVETrainingSourceError("canonical export corpus pin or exclusions differ")
        selected = exported["selected_rows"]
        if ({_family(x["repository_url"]) for x in selected} != wanted or len(selected) != len(wanted)
                or any(x["native_source_cid_preimage_verified"] is not True or x["raw_body_persisted"] is not False
                       or type(x["response_bytes"]) is not int or not 0 < x["response_bytes"] <= manifest["profile"]["budget"]["max_response_bytes"] for x in selected)):
            raise CVETrainingSourceError("split selections differ from admitted families or transport budget")
        if {x["source_family"] for x in loaded["training_pairs"]} != wanted:
            raise CVETrainingSourceError("every selected family needs actual body-derived training observations")
        selected_sources = {x["source_cid"]: x for x in selected}
        for pair in loaded["training_pairs"]:
            selection = selected_sources.get(pair["source_cid"])
            if (selection is None or selection["row_index"] != pair["source_row_index"]
                    or selection["repository_url"] != pair["repository_url"]):
                raise CVETrainingSourceError("training observation differs from metadata-selected source")
            for ledger, identity in ((body_splits, pair["body_sha256"]), (source_splits, pair["source_cid"])):
                if identity in ledger and ledger[identity] != split:
                    raise CVETrainingSourceError("cross-split code-body or source-identity overlap")
                ledger[identity] = split
        totals["original_rows"] += len(selected); totals["training_pairs"] += len(loaded["training_pairs"])
        totals["response_bytes"] += sum(x["response_bytes"] for x in selected)
        rows[split] = [_project_pair(pair) for pair in loaded["training_pairs"]]
    if (totals != manifest["totals"] or totals["original_rows"] > manifest["profile"]["budget"]["max_original_rows"]
            or totals["response_bytes"] > manifest["profile"]["budget"]["max_total_response_bytes"]):
        raise CVETrainingSourceError("corpus aggregate transport budget differs")
    return {"manifest": manifest, "splits": rows,
        "legacy_train_descriptor": {"output": str(root / "train"), "manifest_sha256": manifest["exports"]["train"]["manifest_sha256"]},
        "proof_authority": False, "execution_authority": False, "holdout_evaluated": False}


def ingest_security_corpus(*, profile: dict, metadata_root: Path, data_root: Path, output: Path,
                           fetcher=fetch_corpus_cve_row):
    """Export at most one CID-verified row per explicitly assigned family."""
    profile = json.loads(_bytes(profile))
    pin, exclusions = _profile(profile)
    output = _root(output, fresh=True)
    inspection = inspect_security_corpus(metadata_root=metadata_root, pin=pin)
    _inspection(inspection, pin)
    # Preflight every split using only verified metadata before the first body.
    for split in SPLITS:
        canonical._select_rows(metadata_root=metadata_root, data_root=data_root, pin=pin,
            graph_shards=tuple(profile["graph_shards"]), repository_urls=tuple(profile["repository_splits"][split]), exclusions=exclusions)
    requests, response_bytes = 0, 0
    def bounded_fetch(selection, maximum):
        nonlocal requests, response_bytes
        budget = profile["budget"]
        if requests >= budget["max_original_rows"]:
            raise CVETrainingSourceError("corpus original-row request budget exhausted")
        remaining = budget["max_total_response_bytes"] - response_bytes
        limit = min(maximum, budget["max_response_bytes"], remaining)
        if limit <= 0:
            raise CVETrainingSourceError("corpus aggregate response budget exhausted")
        requests += 1
        raw = fetcher(selection, limit)
        if type(raw) is not bytes or not 0 < len(raw) <= limit:
            raise CVETrainingSourceError("corpus response exceeds declared byte budget")
        response_bytes += len(raw)
        return raw
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".security-corpus-", dir=output.parent) as temporary:
        stage = Path(temporary) / "corpus"; stage.mkdir()
        exports, pair_count = {}, 0
        for split in SPLITS:
            result = canonical.export_canonical_cve_training(metadata_root=metadata_root, data_root=data_root, pin=pin,
                graph_shards=tuple(profile["graph_shards"]), repository_urls=tuple(profile["repository_splits"][split]),
                exclusions=exclusions, output=stage / split, fetcher=bounded_fetch)
            # Canonical v1 names its default offset transport. This wrapper has
            # a different resolver (or an injected bounded fixture), so record
            # that distinction without changing existing v1 validator code.
            child_path = stage / split / "manifest.json"
            child = json.loads(child_path.read_bytes())
            child["transport"] = "bounded corpus resolver; native source CID preimage checked; viewer revision unpinned"
            child_raw = _bytes(child); child_path.write_bytes(child_raw)
            exports[split] = {"path": split, "manifest_sha256": _sha(child_raw)}
            pair_count += result["training_pair_count"]
        manifest = {"schema": SCHEMA, "profile": profile, "profile_sha256": _sha(_bytes(profile)),
            "source_inspection": inspection, "exports": exports,
            "totals": {"original_rows": requests, "training_pairs": pair_count, "response_bytes": response_bytes},
            "input_semantics": "source-body lexical and optional AST observations only",
            "target_semantics": "native audit/CWE/polarity classification candidates, not formulas or proofs",
            "holdout_evaluated": False, "proof_authority": False, "execution_authority": False}
        raw = _bytes(manifest); digest = _sha(raw)
        (stage / "corpus-manifest.json").write_bytes(raw)
        load_security_corpus(stage, expected_manifest_sha256=digest)
        if output.exists():
            raise CVETrainingSourceError("corpus output appeared during ingestion")
        stage.rename(output)
    checked = load_security_corpus(output, expected_manifest_sha256=digest)
    return {"schema": SCHEMA, "output": str(output), "manifest_sha256": digest,
        "profile_sha256": manifest["profile_sha256"], "totals": manifest["totals"],
        "legacy_train_descriptor": checked["legacy_train_descriptor"], "holdout_evaluated": False,
        "provider_calls": 0, "proof_authority": False, "execution_authority": False}

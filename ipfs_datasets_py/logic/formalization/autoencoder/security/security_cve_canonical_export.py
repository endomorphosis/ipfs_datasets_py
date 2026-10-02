"""Bounded metadata-selected CVE code observations and canonical SecurityIR targets.

Repository exclusions precede every original-row request. The viewer is an
untrusted transport: native row CIDs must match the immutable release routing
index. Only digest-bearing canonical records and screened numeric/token
observations are exported. Classification candidates remain audit-only and
unresolved; no deny policy, proof result, or executable authority is inferred.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Callable
from urllib.parse import urlencode
from urllib.request import urlopen

from ipfs_datasets_py.logic.security_ir.cvefixes.classification import materialize_classification
from ipfs_datasets_py.logic.security_ir.cvefixes.graph import build_cvefixes_graph
from ipfs_datasets_py.logic.security_ir.cvefixes.projector import (
    ProjectorConfig, canonical_source_row_cid, project_cvefixes_row,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.release_policy import (
    CVEFIXES_BODY_FIELDS, CVEfixesReleasePolicy, LicenseProvenance, PUBLIC_RELEASE_PROFILE,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    CodeUnit, DerivedDataset, PolicyCandidate, SourceRecord, canonical_config_cid,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.source_snapshot import (
    CVEFIXES_DATASET_ID, CVEFIXES_REVISION, CVEfixesRowAdapter, CVEfixesRowBounds,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.vocabulary import validate_cvefixes_policy_attributes

from . import codebase_autoencoder
from .security_cve_training_source import (
    BenchmarkExclusions, CVETrainingSourceError, FEATURES, PROJECTION,
    HuggingFaceSourcePin, _family, _read_graph_shard, native,
)

SCHEMA = "canonical-cve-code-security-training/v1"
_MAX_RESPONSE = 1024 * 1024
_MAX_ROWS = 4
_PROJECTOR = ProjectorConfig(max_hunks=16, max_symbols_per_unit=128,
    max_semantic_facts=512, max_excerpt_chars=1, max_predicate_chars=1024)
_EXPORT_CONFIG = canonical_config_cid({"export_schema": SCHEMA, "code_unit_excerpts": "omitted"},
                                     schema_version=SCHEMA)
_PAYLOAD_FIELDS = {
    "source_record": PUBLIC_RELEASE_PROFILE.allowed_fields | {
        "body_digests", "content_trust", "instruction_handling", "profile", "source_provenance",
        "grants_execution_authority", "export_schema", "repository_witness_cid",
        "native_projection_cid", "admission_id", "release_policy_sha256"},
    "code_unit": {"body_cid", "body_sha256", "body_treatment", "candidate_paths", "commit_hash",
        "cve_id", "end_line", "evidence_polarity", "extraction_method", "grants_execution_authority",
        "origin_code_unit_cid", "pair_key", "path_ambiguous", "repository", "source_revision",
        "source_row_index", "start_line", "symbol", "symbol_kind"},
    "policy_candidate": {"candidate_role", "classification_status", "exact_policy_constraints_present",
        "forbidden_constraint_resolution", "grants_execution_authority", "language_annotation",
        "language_annotation_is_policy_constraint", "language_annotation_status", "materializer_version",
        "projection_cid", "projection_config_cid", "semantic_fact_count", "semantic_facts_promoted",
        "source_row_index"},
    "formal_view": {"candidate_cid", "classification_only", "exact_forbidden_action_resolved",
        "exact_forbidden_scope_resolved", "grants_execution_authority", "materializer_version",
        "projection_cid", "proof_authoritative", "resolution"},
}


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_raw_fields(value, *, body_digests: bool = False) -> None:
    """Portable derivatives cannot hide raw fields behind a recomputed file hash."""
    if isinstance(value, dict):
        if body_digests:
            if not set(value) <= CVEFIXES_BODY_FIELDS:
                raise CVETrainingSourceError("unknown code-body digest field")
            for descriptor in value.values():
                if (not isinstance(descriptor, dict) or set(descriptor) != {"sha256", "utf8_bytes"}
                        or not isinstance(descriptor["sha256"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"]) is None
                        or type(descriptor["utf8_bytes"]) is not int or descriptor["utf8_bytes"] < 0):
                    raise CVETrainingSourceError("body digest cannot contain original body content")
            return
        forbidden = CVEFIXES_BODY_FIELDS | {"excerpt", "diff_header", "body", "source_text", "source_code", "raw_row", "raw_response"}
        if set(value) & forbidden:
            raise CVETrainingSourceError("raw body or excerpt fields are forbidden in portable derivatives")
        for key, item in value.items():
            _reject_raw_fields(item, body_digests=(key == "body_digests"))
    elif isinstance(value, list):
        for item in value:
            _reject_raw_fields(item)


@dataclass(frozen=True)
class SelectedCVERow:
    source_cid: str
    row_index: int
    repository_url: str
    repository_node_cid: str
    source_shard_cid: str
    source_shard_path: str


def _select_rows(*, metadata_root: Path, data_root: Path, pin: HuggingFaceSourcePin,
                 graph_shards: tuple[str, ...], repository_urls: tuple[str, ...],
                 exclusions: BenchmarkExclusions) -> tuple[list[SelectedCVERow], dict]:
    if (not isinstance(exclusions, BenchmarkExclusions) or not repository_urls
            or len(repository_urls) > _MAX_ROWS
            or len(set(map(_family, repository_urls))) != len(repository_urls)):
        raise CVETrainingSourceError("select one to four distinct repository families")
    if any(exclusions.excludes_family(url) for url in repository_urls):
        raise CVETrainingSourceError("benchmark repository excluded before original-row access")
    if not graph_shards or len(set(graph_shards)) != len(graph_shards) or len(graph_shards) > 4:
        raise CVETrainingSourceError("bounded unique verified graph shards required")
    loaded = native.load_huggingface_complete_release(metadata_root, pin, offline=True)
    metadata_root = Path(metadata_root).resolve(strict=True)
    if Path(data_root).is_symlink():
        raise CVETrainingSourceError("graph data root must not be a symlink")
    data_root = Path(data_root).resolve(strict=True)
    raw = native._bounded_bytes(native._safe_file(metadata_root, "manifest.json"), 8 * _MAX_RESPONSE, "manifest")
    if _sha(raw) != pin.manifest_sha256:
        raise CVETrainingSourceError("manifest changed after verification")
    manifest = native._strict_json_object(raw, "manifest")
    descriptors = {item["path"]: native._ArtifactDescriptor.from_dict(item) for item in manifest["artifacts"]}
    if any(path not in descriptors for path in graph_shards):
        raise CVETrainingSourceError("unlisted graph shard")
    chosen = [descriptors[path] for path in graph_shards]
    if sum(x.byte_length for x in chosen) > 8 * _MAX_RESPONSE or sum(x.row_count for x in chosen) > 16384:
        raise CVETrainingSourceError("graph selection exceeds metadata bounds")
    nodes = [node for descriptor in chosen for node in _read_graph_shard(
        data_root, descriptor, max_bytes=8 * _MAX_RESPONSE, max_rows=16384)]
    index_descriptor = descriptors["indexes/original_rows.parquet"]
    index = native._read_index_table(metadata_root, index_descriptor,
                                    limits=native.HuggingFaceCompleteReleaseLimits())
    by_cid = {row["security_ir_source_cid"]: row for row in index.to_pylist()}
    selections = []
    for requested in repository_urls:
        matches = [node for node in nodes if node.node_type == "repository"
                   and _family(node.payload["repository"]) == _family(requested)]
        if len(matches) != 1:
            raise CVETrainingSourceError("repository must have exactly one verified metadata witness")
        node = matches[0]
        if not node.source_cids or any(cid not in by_cid for cid in node.source_cids):
            raise CVETrainingSourceError("repository references unverified upstream row identities")
        rows = sorted((by_cid[cid] for cid in node.source_cids
                       if by_cid[cid]["source_status"] == "admitted"), key=lambda row: row["source_row_index"])
        if not rows:
            raise CVETrainingSourceError("repository has no admitted source row")
        row = rows[0]
        selections.append(SelectedCVERow(row["security_ir_source_cid"], row["source_row_index"],
            node.payload["repository"], node.cid, row["source_shard_cid"], row["source_shard_path"]))
    return selections, {"pin": pin.to_dict(), "native_control_receipt": asdict(loaded.receipt),
        "license_provenance": manifest["source"], "routing_index_sha256": index_descriptor.sha256,
        "graph_artifacts": [{"path": x.path, "sha256": x.sha256, "content_id": x.content_id} for x in chosen]}


def fetch_selected_cve_row(selection: SelectedCVERow, maximum: int = _MAX_RESPONSE) -> bytes:
    """Request precisely one metadata-approved row; never fetch whole source shards."""
    if type(selection) is not SelectedCVERow or type(maximum) is not int or not 0 < maximum <= _MAX_RESPONSE:
        raise CVETrainingSourceError("bounded typed row selection required")
    url = "https://datasets-server.huggingface.co/rows?" + urlencode({
        "dataset": "Publicus/cvefixes-security-ir-graphrag", "config": "original_data",
        "split": "train", "offset": selection.row_index, "length": 1})
    with urlopen(url, timeout=55) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise CVETrainingSourceError("selected original-row response exceeds bound")
    return raw


def _verified_row(response: bytes, selection: SelectedCVERow, exclusions: BenchmarkExclusions):
    if type(response) is not bytes or len(response) > _MAX_RESPONSE:
        raise CVETrainingSourceError("bounded original-row response required")
    wrapper = native._strict_json_object(response, "selected original-row response")
    rows = wrapper.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise CVETrainingSourceError("one selected upstream row required")
    envelope = rows[0]
    raw = envelope.get("row")
    # Inspect repository routing metadata before examining or adapting body fields.
    if (not isinstance(raw, dict) or raw.get("repo_url") != selection.repository_url
            or exclusions.excludes_family(raw["repo_url"])
            or envelope.get("row_idx") != selection.row_index or envelope.get("truncated_cells") != []):
        raise CVETrainingSourceError("selected repository, index or complete-row binding differs")
    paths = raw.get("file_paths")
    if not isinstance(paths, list) or not paths:
        raise CVETrainingSourceError("source file provenance required before body adaptation")
    if any(not isinstance(path, str) or PurePosixPath(path.replace("\\", "/")).name.casefold()
           in exclusions.file_names for path in paths):
        raise CVETrainingSourceError("benchmark filename excluded before training")
    row = CVEfixesRowAdapter(CVEfixesRowBounds(max_body_chars=512_000,
        max_total_text_chars=1_000_000)).adapt(raw, row_index=selection.row_index)
    if canonical_source_row_cid(row) != selection.source_cid:
        raise CVETrainingSourceError("native source-row CID differs from immutable pinned routing index")
    for field in ("vulnerable_code", "fixed_code", "diff_with_context"):
        body = getattr(row, field)
        if body and _sha(body.encode()) in exclusions.code_sha256:
            raise CVETrainingSourceError("benchmark code-body hash excluded before projection or training")
    return row


def _materialize_row(row, selection: SelectedCVERow, license_provenance: LicenseProvenance,
                     exclusions: BenchmarkExclusions) -> tuple[list, list[dict]]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as lexical

    admission = CVEfixesReleasePolicy().evaluate(row.to_dict(),
        license_provenance=license_provenance, profile=PUBLIC_RELEASE_PROFILE)
    if not admission.admitted:
        raise CVETrainingSourceError("native public release policy rejected selected row")
    if any(finding.category.value == "personal_data" and finding.field in {"vulnerable_code", "fixed_code"}
           for finding in admission.scan_report.findings):
        raise CVETrainingSourceError("personal-data body cannot become lexical training observations")
    projection = project_cvefixes_row(row, config=_PROJECTOR)
    classification = materialize_classification(row, projection)
    attrs = validate_cvefixes_policy_attributes(classification.candidate.scope)
    if not attrs.classification_only or classification.candidate.effect != "audit":
        raise CVETrainingSourceError("native classification unexpectedly created policy authority")
    source = SourceRecord(source_cids=(selection.source_cid,), parent_cids=(projection.cid,),
        config_cid=_EXPORT_CONFIG, source_uri="hf://datasets/" + CVEFIXES_DATASET_ID,
        source_revision=CVEFIXES_REVISION, row_key=f"{row.row_index:05d}:{row.cve_id}:{row.hash}",
        payload={**dict(admission.projected_record), "grants_execution_authority": False,
            "export_schema": SCHEMA, "repository_witness_cid": selection.repository_node_cid,
            "native_projection_cid": projection.cid, "admission_id": admission.admission_id,
            "release_policy_sha256": admission.policy_sha256})
    units = []
    for unit in projection.code_units:
        if unit.payload["body_sha256"] in exclusions.code_sha256:
            raise CVETrainingSourceError("benchmark projected code hash excluded before feature extraction")
        if PurePosixPath(unit.path.replace("\\", "/")).name.casefold() in exclusions.file_names:
            raise CVETrainingSourceError("benchmark projected filename excluded before feature extraction")
        # Retain native code-body identities while making a separately identified
        # public canonical record with every textual body excerpt omitted.
        payload = {k: v for k, v in unit.to_dict()["payload"].items()
                   if k not in {"excerpt", "excerpt_truncated", "excerpt_sanitized_nul", "diff_header"}}
        payload.update(body_treatment="digest_only", origin_code_unit_cid=unit.cid)
        units.append(CodeUnit(source_cids=unit.source_cids, parent_cids=(unit.cid, projection.cid),
            config_cid=_EXPORT_CONFIG, unit_kind=unit.unit_kind, language=unit.language,
            path=unit.path, polarity=unit.polarity, payload=payload))
    graph = build_cvefixes_graph((projection,),
        cwe_by_cve={row.cve_id: row.cwe_id} if row.cwe_id and row.cwe_id.startswith("CWE-") else {})
    counts = {key: 0 for key in FEATURES}
    for node in graph.nodes:
        counts["node_" + node.node_type] += 1
        if node.node_type == "code_unit" and node.payload.get("polarity") in {"vulnerable", "fixed"}:
            counts["code_unit_" + node.payload["polarity"]] += 1
    pairs = []
    for polarity in ("vulnerable", "fixed"):
        body = getattr(row, polarity + "_code")
        if not body:
            continue
        digest = _sha(body.encode())
        body_units = [unit for unit in units if unit.polarity == polarity and unit.payload["body_sha256"] == digest]
        if not body_units:
            raise CVETrainingSourceError("body lacks an exact canonical CodeUnit digest binding")
        # Screening in the shared AST feature adapter precedes lexical extraction.
        try:
            ast_samples, unsupported = codebase_autoencoder._features({"body.py": body.encode()}, ["body.py"], 1024)
            ast_status = "available" if ast_samples else "unsupported"
        except ValueError as exc:
            if str(exc) != "no admitted Python function features for code autoencoder":
                raise
            ast_samples, unsupported, ast_status = [], [], "unsupported"
        if row.language and row.language.casefold() != "python":
            ast_samples, unsupported, ast_status = [], [], "unsupported_language"
        tokens = Counter("token:" + token for token in lexical._token_features(body, max_tokens=40))
        identity = {"source_cid": selection.source_cid, "polarity": polarity, "body_sha256": digest}
        pairs.append({**identity, "row_id": "sha256:" + _sha(_json(identity)),
            "source_family": _family(row.repo_url), "repository_url": row.repo_url,
            "source_row_index": row.row_index, "source_paths": list(row.file_paths),
            "source_record_cid": source.cid, "code_unit_cids": sorted(unit.cid for unit in body_units),
            "candidate_cid": classification.candidate.cid,
            "input": {"projection_family": PROJECTION, "feature_counts": counts,
                "lexical_token_counts": dict(sorted(tokens.items())),
                "tokenizer": "native-modal-autoencoder._token_features/max_tokens=40",
                "tokenizer_sha256": _sha(Path(lexical.__file__).read_bytes()),
                "ast_projection_family": "code_ast@1", "ast_feature_vocabulary": list(codebase_autoencoder.FEATURES),
                "ast_samples": ast_samples, "ast_status": ast_status,
                "ast_source_path_kind": "virtual_single_body_not_repository_file", "ast_unsupported": unsupported},
            "target": {"effect": "audit", "classification_only": True,
                "cwe_ids": [term.name for term in attrs.cwe_ids], "unknown_cwe": not bool(attrs.cwe_ids),
                "polarity": polarity, "exact_forbidden_action_resolved": False,
                "exact_forbidden_scope_resolved": False, "proof_authoritative": False},
            "training_admitted": True, "grants_execution_authority": False})
    if not pairs:
        raise CVETrainingSourceError("selected row contains no paired code-body observations")
    return [source, *units, classification.candidate, classification.formal_view], pairs


def export_canonical_cve_training(*, metadata_root: Path, data_root: Path, pin: HuggingFaceSourcePin,
                                 graph_shards: tuple[str, ...], repository_urls: tuple[str, ...],
                                 exclusions: BenchmarkExclusions, output: Path,
                                 fetcher: Callable = fetch_selected_cve_row) -> dict:
    """Create a fresh separate export, with no target code execution or model calls."""
    output = Path(output).absolute()
    if output.resolve() != output or output.exists():
        raise CVETrainingSourceError("fresh canonical export directory required")
    selections, provenance = _select_rows(metadata_root=metadata_root, data_root=data_root, pin=pin,
        graph_shards=graph_shards, repository_urls=repository_urls, exclusions=exclusions)
    license_provenance = LicenseProvenance.from_dict(provenance["license_provenance"])
    if (license_provenance.dataset_id != CVEFIXES_DATASET_ID
            or license_provenance.source_revision != CVEFIXES_REVISION
            or not license_provenance.reviewed_for_release):
        raise CVETrainingSourceError("pinned reviewed upstream license provenance required")
    records, pairs, receipts = [], [], []
    for selection in selections:
        if exclusions.excludes_family(selection.repository_url):
            raise CVETrainingSourceError("repository exclusion changed before fetch")
        raw = fetcher(selection, _MAX_RESPONSE)
        row = _verified_row(raw, selection, exclusions)
        derived, observations = _materialize_row(row, selection, license_provenance, exclusions)
        records.extend(derived); pairs.extend(observations)
        receipts.append({**asdict(selection), "response_sha256": _sha(raw), "response_bytes": len(raw),
            "native_source_cid_preimage_verified": True, "raw_body_persisted": False})
    dataset = DerivedDataset(records=tuple(records))
    pair_body = {"schema": SCHEMA, "training_pairs": pairs}
    manifest = {"schema": SCHEMA, "namespace": "code-security-cve", **provenance,
        "benchmark_exclusions": asdict(exclusions), "selected_rows": receipts,
        "canonical_dataset_cid": dataset.cid, "canonical_record_count": len(dataset.records),
        "training_pair_count": len(pairs), "feature_vocabulary": list(FEATURES),
        "projection_family": PROJECTION,
        "target_vocabulary": sorted({term for pair in pairs for term in pair["target"]["cwe_ids"]}),
        "target_semantics": "native classification-only audit/CWE/polarity; not security truth or deny policy",
        "transport_revision_pinned": False, "source_content_bound_to_pinned_revision": True,
        "transport": "HF viewer exact metadata-selected offset, length=1; native CID checked",
        "raw_bodies_persisted": False, "raw_body_excerpts_exported": False,
        "provider_calls": 0, "target_code_executed": False, "legal_state_modified": False,
        "proof_authoritative": False, "grants_execution_authority": False,
        "implementation_sha256": _sha(Path(__file__).read_bytes())}
    blobs = {"canonical-records.json": dataset.canonical_bytes(), "training-pairs.json": _json(pair_body)}
    manifest["artifacts"] = {name: {"sha256": _sha(raw), "bytes": len(raw)} for name, raw in blobs.items()}
    manifest_bytes = _json(manifest)
    output.mkdir(parents=True, mode=0o700)
    for name, raw in {**blobs, "manifest.json": manifest_bytes}.items():
        with (output / name).open("xb") as handle:
            handle.write(raw)
    digest = _sha(manifest_bytes)
    load_canonical_cve_training(output, expected_manifest_sha256=digest)
    return {"status": "exported", "manifest": str(output / "manifest.json"),
            "manifest_sha256": digest, "canonical_dataset_cid": dataset.cid,
            "canonical_record_count": len(dataset.records), "training_pair_count": len(pairs),
            "source_row_count": len(selections), "provider_calls": 0,
            "proof_authoritative": False, "grants_execution_authority": False}


def load_canonical_cve_training(root: Path, *, expected_manifest_sha256: str) -> dict:
    """Verify immutable export files, native records and every input/target link."""
    root = Path(root).absolute()
    if root.resolve(strict=True) != root or root.is_symlink():
        raise CVETrainingSourceError("canonical export root required")
    if {path.name for path in root.iterdir()} != {"manifest.json", "canonical-records.json", "training-pairs.json"}:
        raise CVETrainingSourceError("canonical export must contain only its three public artifacts")
    raw = codebase_autoencoder._read(root / "manifest.json", limit=2 * _MAX_RESPONSE)
    if _sha(raw) != expected_manifest_sha256:
        raise CVETrainingSourceError("canonical export manifest digest differs")
    manifest = native._strict_json_object(raw, "canonical export manifest")
    if manifest.get("schema") != SCHEMA or manifest.get("namespace") != "code-security-cve":
        raise CVETrainingSourceError("wrong export domain or schema")
    HuggingFaceSourcePin.from_dict(manifest["pin"])
    license_provenance = LicenseProvenance.from_dict(manifest["license_provenance"])
    if (not license_provenance.reviewed_for_release or license_provenance.dataset_id != CVEFIXES_DATASET_ID
            or license_provenance.source_revision != CVEFIXES_REVISION
            or manifest.get("projection_family") != PROJECTION
            or manifest.get("feature_vocabulary") != list(FEATURES)
            or manifest.get("grants_execution_authority") is not False
            or manifest.get("proof_authoritative") is not False
            or manifest.get("raw_bodies_persisted") is not False
            or manifest.get("raw_body_excerpts_exported") is not False
            or manifest.get("legal_state_modified") is not False
            or manifest.get("target_code_executed") is not False
            or type(manifest.get("provider_calls")) is not int or manifest["provider_calls"] != 0):
        raise CVETrainingSourceError("canonical export provenance, projection or authority differs")
    if set(manifest["artifacts"]) != {"canonical-records.json", "training-pairs.json"}:
        raise CVETrainingSourceError("closed canonical export inventory required")
    values = {}
    for name, descriptor in manifest["artifacts"].items():
        raw = codebase_autoencoder._read(root / name, limit=16 * _MAX_RESPONSE)
        if _sha(raw) != descriptor["sha256"] or len(raw) != descriptor["bytes"]:
            raise CVETrainingSourceError("canonical export artifact digest differs")
        values[name] = native._strict_json_object(raw, name)
        _reject_raw_fields(values[name])
    for record in values["canonical-records.json"]["records"]:
        fields = _PAYLOAD_FIELDS.get(record.get("record_type"))
        if fields is None or not set(record.get("payload", {})) <= fields:
            raise CVETrainingSourceError("closed native portable record payload required")
    dataset = DerivedDataset.from_dict(values["canonical-records.json"])
    if dataset.cid != manifest["canonical_dataset_cid"] or len(dataset.records) != manifest["canonical_record_count"]:
        raise CVETrainingSourceError("native canonical dataset root differs")
    by_cid = {record.cid: record for record in dataset.records}
    pairs = values["training-pairs.json"]["training_pairs"]
    exclusions = BenchmarkExclusions(**manifest["benchmark_exclusions"])
    if len(pairs) != manifest["training_pair_count"] or len({pair["row_id"] for pair in pairs}) != len(pairs):
        raise CVETrainingSourceError("canonical training-pair inventory differs")
    for pair in pairs:
        if (set(pair) != {"source_cid", "polarity", "body_sha256", "row_id", "source_family",
                "repository_url", "source_row_index", "source_paths", "source_record_cid",
                "code_unit_cids", "candidate_cid", "input", "target", "training_admitted",
                "grants_execution_authority"}
                or set(pair["input"]) != {"projection_family", "feature_counts", "lexical_token_counts",
                    "tokenizer", "tokenizer_sha256", "ast_projection_family", "ast_feature_vocabulary",
                    "ast_samples", "ast_status", "ast_source_path_kind", "ast_unsupported"}):
            raise CVETrainingSourceError("closed derived training-pair fields required")
        source, candidate = by_cid.get(pair["source_record_cid"]), by_cid.get(pair["candidate_cid"])
        units = [by_cid.get(cid) for cid in pair["code_unit_cids"]]
        if (not isinstance(source, SourceRecord) or not isinstance(candidate, PolicyCandidate) or not units
                or source.source_cids != (pair["source_cid"],) or candidate.source_cids != source.source_cids
                or candidate.effect != "audit" or candidate.payload.get("candidate_role") != "classification_only"
                or exclusions.excludes_family(pair["repository_url"])
                or pair["source_family"] != _family(pair["repository_url"])
                or pair["body_sha256"] in exclusions.code_sha256
                or source.payload.get("repo_url") != pair["repository_url"]
                or source.payload.get("row_index") != pair["source_row_index"]
                or list(source.payload.get("file_paths", ())) != pair["source_paths"]
                or source.source_revision != CVEFIXES_REVISION
                or pair.get("training_admitted") is not True
                or pair.get("grants_execution_authority") is not False
                or any(PurePosixPath(path.replace("\\", "/")).name.casefold() in exclusions.file_names
                       for path in pair["source_paths"])):
            raise CVETrainingSourceError("canonical source/candidate/exclusion link differs")
        identity = {name: pair[name] for name in ("source_cid", "polarity", "body_sha256")}
        if pair["row_id"] != "sha256:" + _sha(_json(identity)):
            raise CVETrainingSourceError("training pair identity differs from source/body/polarity")
        for unit in units:
            if (not isinstance(unit, CodeUnit) or unit.source_cids != source.source_cids
                    or unit.polarity != pair["polarity"] or unit.payload.get("body_sha256") != pair["body_sha256"]
                    or unit.payload.get("repository") != pair["repository_url"]
                    or "excerpt" in unit.payload or unit.payload.get("body_treatment") != "digest_only"):
                raise CVETrainingSourceError("canonical body digest/polarity link differs")
        attrs = validate_cvefixes_policy_attributes(candidate.scope)
        expected_target = {"effect": "audit", "classification_only": True,
            "cwe_ids": [term.name for term in attrs.cwe_ids], "unknown_cwe": not bool(attrs.cwe_ids),
            "polarity": pair["polarity"], "exact_forbidden_action_resolved": False,
            "exact_forbidden_scope_resolved": False, "proof_authoritative": False}
        if (pair["target"] != expected_target or pair["input"].get("projection_family") != PROJECTION
                or set(pair["input"]["feature_counts"]) != set(FEATURES)):
            raise CVETrainingSourceError("canonical training target or projection family differs")
        if any(type(value) is not int or value < 0 for value in pair["input"]["feature_counts"].values()):
            raise CVETrainingSourceError("graph feature counts must be finite nonnegative integers")
        tokens = pair["input"]["lexical_token_counts"]
        if (not isinstance(tokens, dict)
                or any(not key.startswith("token:") or type(value) is not int or value <= 0 for key, value in tokens.items())
                or sum(tokens.values()) > 40):
            raise CVETrainingSourceError("native lexical feature contract differs")
    if manifest["target_vocabulary"] != sorted({term for pair in pairs for term in pair["target"]["cwe_ids"]}):
        raise CVETrainingSourceError("candidate target vocabulary differs from native classifications")
    return {"manifest": manifest, "records": dataset.records, "training_pairs": pairs}

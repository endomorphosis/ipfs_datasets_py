"""Bounded sparse update publication for independently qualified model lanes.

The DuckDB/Quack owner supplies immutable registry records. A release carries
the entire sparse dependency closure, qualification evidence and exact base
hash; it never uploads a full anchor or downloads weights. Replay requires an
already provisioned local anchor. Optional Hub lane updates use an owner
policy callback and repository-parent CAS, never a global best-model pointer.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from .autoencoder_release import _version_record
from .publisher import _read_regular_file_nofollow_components, _reject_secrets
from ..optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from ..optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch

SCHEMA = "autoencoder-incremental-qualified-publication/v1"
HEAD_SCHEMA = "autoencoder-qualified-lane-head/v1"
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
PREFIX = "autoformal/uscode/autoencoders"
MAX_UPLOAD_BYTES = 128 * 1024 * 1024
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_FILES = 512
GATES = ("metric_gate", "semantic_gate", "family_syntax_gate", "family_coverage_gate", "lake_gate", "heldout_gate")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_LANE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z")
_KINDS = {"sparse_manifest": ".sparse_manifest.json", "sparse_patch": ".sparse_patch.json",
          "qualification": ".qualification.json", "lean_source": ".Legal.lean",
          "lake_log": ".lake.log", "lakefile": ".lakefile.lean", "lean_toolchain": ".lean-toolchain"}
_PROJECT = {"lakefile": b"import Lake\nopen Lake DSL\npackage \xc2\xablegal\xc2\xbb\n@[default_target]\nlean_lib Legal\n",
            "lean_toolchain": b"leanprover/lean4:v4.26.0\n"}


class IncrementalPublicationError(ValueError):
    """Unverified, incompatible, conflicting or over-budget publication."""


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode() + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ref(raw: bytes) -> dict[str, Any]:
    return {"sha256": _sha(raw), "bytes": len(raw)}


def _read(path: Path, maximum: int, expected: Mapping[str, Any] | None = None) -> bytes:
    raw = _read_regular_file_nofollow_components(path.absolute(), label="sparse publication artifact",
                                                maximum_bytes=maximum)
    if expected is not None and _ref(raw) != sparse.artifact_ref(expected):
        raise IncrementalPublicationError("immutable artifact byte identity changed")
    return raw


def _object(raw: bytes) -> dict[str, Any]:
    value = sparse._parse(raw)
    if not isinstance(value, dict):
        raise IncrementalPublicationError("JSON object required")
    return value


def _write(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _read(path, max(len(raw), 1)) != raw:
            raise IncrementalPublicationError("immutable local publication path conflicts")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _qualified(receipt: Mapping[str, Any], version: Mapping[str, Any]) -> None:
    if (receipt.get("schema_version") != "autoencoder-candidate-qualification/v1"
            or receipt.get("execution_mode") != "native_candidate_qualification"
            or receipt.get("qualified") is not True
            or receipt.get("candidate_version_id") != version["version_id"]
            or receipt.get("candidate_artifact") != version["artifact"]
            or receipt.get("qualification_scope") != "embedding_model_and_deterministic_source_compiler_pipeline"
            or receipt.get("model_emits_text_or_formulas") is not False
            or receipt.get("admitted") is not False or receipt.get("formalized") is not False):
        raise IncrementalPublicationError("native qualification is missing or bound to another candidate")
    gates = receipt.get("gate_results", {})
    if any(gates.get(name, {}).get("passed") is not True for name in GATES):
        raise IncrementalPublicationError("all unchanged qualification gates must pass")
    rows = receipt.get("rows")
    training = receipt.get("sample_count")
    validation = receipt.get("heldout_sample_count")
    if (type(training) is not int or training < 1 or type(validation) is not int or validation < 1
            or not isinstance(rows, list) or len(rows) != training + validation or len(rows) > 1024):
        raise IncrementalPublicationError("qualification requires complete training and validation rows")
    for row in rows:
        if (not isinstance(row, Mapping) or row.get("qualified") is not True
                or any(row.get(name, {}).get("passed") is not True for name in GATES[:-1])):
            raise IncrementalPublicationError("qualification row disagrees with summary")
        metric = row["metric_gate"]
        numbers = [metric.get(name) for name in ("embedding_cosine_similarity", "reconstruction_loss",
                                                 "min_cosine", "max_reconstruction_loss")]
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers)
                or not .72 <= numbers[2] <= numbers[0] <= 1 or not 0 <= numbers[1] <= numbers[3] <= .20):
            raise IncrementalPublicationError("absolute metric qualification is not satisfied")
        source = row.get("source", {})
        text = source.get("text")
        if not isinstance(text, str) or _sha(text.encode()) != row.get("source_sha256"):
            raise IncrementalPublicationError("qualification source text hash differs")
        if re.search(r"constitution|us_const|us-const", str(source.get("title", "")), re.I):
            raise IncrementalPublicationError("Constitution cannot be published as qualified")
        from ..logic.autoformal.family_qualification import REQUIRED_FAMILIES, validate_family_artifact
        semantics = row["semantic_gate"].get("rows", [])
        families = row["family_syntax_gate"].get("rows", [])
        lakes = row["lake_gate"].get("rows", [])
        coverage = row["family_coverage_gate"].get("rows", [])
        if (not semantics or len(semantics) != len(families) or len(semantics) != len(lakes)
                or len(semantics) != len(coverage)):
            raise IncrementalPublicationError("complete per-clause semantic/syntax/coverage/Lake evidence required")
        for semantic, family, cover, lake in zip(semantics, families, coverage, lakes):
            start, end = semantic.get("start"), semantic.get("end")
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                    or semantic.get("status") != "roundtrip_ok" or not semantic.get("decompiled")
                    or family.get("source_id") != semantic.get("clause_id")
                    or family.get("source_sha256") != _sha(text[start:end].encode())
                    or set(family.get("required_families", [])) != set(REQUIRED_FAMILIES)
                    or set(family.get("families", {})) != set(REQUIRED_FAMILIES)):
                raise IncrementalPublicationError("required syntax/semantic source binding missing")
            rule = dict(semantic.get("rule", {}))
            rule.pop("temporal_records", None)
            rule_digest = _sha(json.dumps(rule, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False, allow_nan=False).encode())
            if family.get("canonical_rule") != rule or family.get("rule_sha256") != rule_digest:
                raise IncrementalPublicationError("family syntax canonical rule binding differs")
            if (family.get("schema") != "autoformal-family-qualification/v2"
                    or family.get("passed") is not True or family.get("full_floor_passed") is not True
                    or family.get("full_family_semantics_covered") is not True
                    or family.get("schema_capability_coverage_complete") is not True
                    or cover.get("passed") is not True
                    or cover.get("full_family_semantics_covered") is not True
                    or cover.get("schema_capability_coverage_complete") is not True
                    or cover.get("source_id") != family.get("source_id")
                    or cover.get("source_sha256") != family.get("source_sha256")
                    or cover.get("rule_sha256") != rule_digest):
                raise IncrementalPublicationError("required family semantics/schema coverage evidence missing or unbound")
            for name, artifact in family["families"].items():
                formula = artifact.get("formula")
                if (artifact.get("passed") is not True or artifact.get("source_bound") is not True
                        or artifact.get("syntax_valid") is not True or not isinstance(formula, str)
                        or artifact.get("formula_sha256") != _sha(formula.encode())
                        or artifact.get("rule_sha256") != rule_digest
                        or artifact.get("source_sha256") != family["source_sha256"]
                        or validate_family_artifact(name, formula)["passed"] is not True):
                    raise IncrementalPublicationError("required native syntax evidence failed")
            lock = lake.get("source_lock", {})
            if (lake.get("passed") is not True or lake.get("lake_ok") is not True
                    or lake.get("command") != ["lake", "build", "Legal"]
                    or type(lake.get("returncode")) is not int or lake["returncode"] != 0
                    or lake.get("scope") != "source_locked_numeric_pattern"
                    or lake.get("toolchain") != "leanprover/lean4:v4.26.0"
                    or lock.get("ok") is not True
                    or lock.get("lock", {}).get("proof_profile") != "legal-numeric-tactics/v1"
                    or lock.get("lock", {}).get("candidate_source_sha256") != lake.get("lean_source_sha256")
                    or lock.get("lock", {}).get("expected_source_sha256") != lake.get("lean_source_sha256")):
                raise IncrementalPublicationError("source-locked Lake qualification missing")
            from ..optimizers.logic_theorem_optimizer.autoencoder_candidate_qualification import _statement_lock
            statement_lock, _, statement_sha = _statement_lock()
            if statement_sha != receipt.get("source_sha256", {}).get("statement_lock"):
                raise IncrementalPublicationError("statement-lock producer changed; qualification review required")
            expected_pattern = statement_lock.pattern_from_rule(semantic["rule"])
            if expected_pattern != lake.get("pattern") or not expected_pattern:
                raise IncrementalPublicationError("Lake theorem is not the canonical source pattern")
            locked = statement_lock.lock_statement(lock.get("source", ""), statement_lock.render_lean(expected_pattern))
            if locked.get("ok") is not True:
                raise IncrementalPublicationError("Lean source fails current pinned statement lock")
    if not receipt.get("source_sha256") or not receipt.get("sample_set_sha256"):
        raise IncrementalPublicationError("qualification producer/sample provenance missing")


def _remote(ref: Mapping[str, Any], kind: str) -> str:
    return f"{PREFIX}/artifacts/{ref['sha256']}{_KINDS[kind]}"


def _proofs(receipt: Mapping[str, Any], *, read_local: bool) -> tuple[list[dict], dict]:
    records, snapshots = [], {}
    for row in receipt["rows"]:
        for index, lake in enumerate(row["lake_gate"]["rows"]):
            source = (lake["source_lock"]["source"].rstrip() + "\n").encode()
            if _sha(source) != lake["lean_source_sha256"]:
                raise IncrementalPublicationError("locked Lean source hash differs")
            definitions = {"lean_source": _ref(source), "lake_log": sparse.artifact_ref(lake["log"]),
                           **{kind: _ref(raw) for kind, raw in _PROJECT.items()}}
            if read_local:
                source_path = Path(lake["source_file"]).absolute()
                log_path = Path(lake["log"]["path"]).absolute()
                if source_path.name != "Legal.lean" or log_path != source_path.with_name("lake.log"):
                    raise IncrementalPublicationError("Lake evidence paths are not one locked project")
                for kind, path in {"lean_source": source_path, "lake_log": log_path,
                                   "lakefile": source_path.with_name("lakefile.lean"),
                                   "lean_toolchain": source_path.with_name("lean-toolchain")}.items():
                    raw = _read(path, 4 * 1024 * 1024, definitions[kind])
                    if kind == "lake_log" and (b"Built Legal" not in raw or b"error:" in raw):
                        raise IncrementalPublicationError("Lake log does not record a successful Legal build")
                    snapshots[_sha(raw)] = (definitions[kind], raw, kind)
            records.append({"sample_id": row["sample_id"], "build_index": index,
                            "files": [{**ref, "kind": kind} for kind, ref in sorted(definitions.items())]})
    return records, snapshots


def _namespace(version: Mapping[str, Any], variant: Mapping[str, Any], lane_id: str) -> str:
    language = variant.get("source_language")
    if not isinstance(language, str) or not _LANGUAGE.fullmatch(language):
        raise IncrementalPublicationError("variant needs an explicit source_language")
    if not isinstance(lane_id, str) or not _LANE.fullmatch(lane_id) or ".." in lane_id:
        raise IncrementalPublicationError("lane_id must be a bounded path component")
    return f"{PREFIX}/{language}/{_sha(version['variant_id'].encode())}/lanes/{lane_id}"


def stage_sparse_update(registry: Any, version_id: str, qualification_artifact: Mapping[str, Any],
                        destination: str | Path, *, lane_id: str,
                        repository_id: str = REPOSITORY) -> dict[str, Any]:
    """Prepare reviewed bytes from the existing owner; no Hub or head mutation.

    ``registry`` is an already owned AutoencoderRegistry-compatible interface.
    The owner alone opens DuckDB; workers never receive a database connection.
    This method consumes owner-local artifacts, not remote artifact paths.
    """
    if repository_id != REPOSITORY:
        raise IncrementalPublicationError("this publication contract targets the authorized span-cache dataset")
    version = _version_record(registry.get_version(version_id))
    variant_record = registry.get_variant(version["variant_id"])
    variant = variant_record["manifest"]
    namespace = _namespace(version, variant, lane_id)
    qualification_ref = sparse.artifact_ref(qualification_artifact)
    receipt_raw = _read(Path(registry.artifact_path(qualification_ref)), MAX_RECEIPT_BYTES, qualification_ref)
    receipt = _object(receipt_raw)
    _qualified(receipt, version)
    _reject_secrets(receipt, label="qualification evidence")
    resolver = lambda ref: registry.artifact_path(ref)
    resolved = sparse.resolve_checkpoint(version["artifact"], resolver=resolver)
    if resolved.manifest is None:
        raise IncrementalPublicationError("incremental publication requires a sparse candidate, never a full checkpoint")
    lineage = [version]
    while lineage[-1]["artifact"] != dict(resolved.anchor_checkpoint):
        if len(lineage) >= 9:
            raise IncrementalPublicationError("sparse version lineage exceeds supported depth")
        if lineage[-1]["parent_version_id"] is None:
            raise IncrementalPublicationError("version lineage ends before its sparse anchor")
        parent = _version_record(registry.get_version(lineage[-1]["parent_version_id"]))
        if parent["variant_id"] != version["variant_id"] or parent in lineage:
            raise IncrementalPublicationError("foreign or cyclic version lineage")
        lineage.append(parent)
    if (receipt.get("materialized_checkpoint") != dict(resolved.materialized_checkpoint)
            or {tuple(sorted(sparse.artifact_ref(item).items())) for item in receipt.get("checkpoint_artifacts", [])}
            != {tuple(sorted(dict(item).items())) for item in resolved.artifacts}):
        raise IncrementalPublicationError("qualification checkpoint closure differs from replayed candidate")
    manifest_ids = {row["artifact"]["sha256"] for row in lineage[:-1]}
    for child, parent in zip(lineage, lineage[1:]):
        manifest = sparse.decode_manifest(_read(Path(resolver(child["artifact"])), 1024 * 1024, child["artifact"]))
        if manifest["parent"] != parent["artifact"] or manifest["base_version_id"] != parent["version_id"]:
            raise IncrementalPublicationError("registry lineage differs from sparse checkpoint lineage")
    if lineage[-1]["artifact"] != dict(resolved.anchor_checkpoint):
        raise IncrementalPublicationError("registry lineage does not end at the exact preseed anchor")
    snapshots: dict[str, tuple[dict[str, Any], bytes, str]] = {}
    for ref in resolved.artifacts:
        if ref == resolved.anchor_checkpoint:
            continue
        kind = "sparse_manifest" if ref["sha256"] in manifest_ids else "sparse_patch"
        raw = _read(Path(resolver(ref)), MAX_UPLOAD_BYTES, ref)
        sparse.decode_manifest(raw) if kind == "sparse_manifest" else decode_patch(raw)
        snapshots[ref["sha256"]] = (dict(ref), raw, kind)
    snapshots[qualification_ref["sha256"]] = (qualification_ref, receipt_raw, "qualification")
    proof_evidence, proof_snapshots = _proofs(receipt, read_local=True)
    snapshots.update(proof_snapshots)
    if len(snapshots) > MAX_FILES or sum(len(row[1]) for row in snapshots.values()) > MAX_UPLOAD_BYTES:
        raise IncrementalPublicationError("incremental upload exceeds bounded file/byte budget")
    paths = []
    destination = Path(destination).absolute()
    for digest, (ref, raw, kind) in sorted(snapshots.items()):
        _write(destination / "artifacts" / digest, raw)
        paths.append({**ref, "kind": kind, "path_in_repo": _remote(ref, kind),
                      "qualification_role": "dependency_only" if kind.startswith("sparse_") else "candidate_evidence"})
    qualified_digest = qualification_ref["sha256"]
    manifest_path = f"{namespace}/versions/{version_id.removeprefix('sha256:')}/{qualified_digest}/update.json"
    manifest = {
        "schema": SCHEMA, "repository_id": repository_id, "repository_type": "dataset",
        "path_in_repo": manifest_path, "lane_head_path": namespace + "/qualified.json",
        "lane_id": lane_id, "source_language": variant["source_language"], "variant_manifest": variant,
        "version": version, "version_lineage": lineage, "files": paths,
        "qualification_artifact": qualification_ref, "qualified_candidate_only": True,
        "proof_evidence": proof_evidence,
        "qualification_samples": [{"sample_id": row["sample_id"], "split": row["split"],
            "source_sha256": row["source_sha256"], "title": row["source"].get("title"),
            "section": row["source"].get("section"), "citation": row["source"].get("citation")}
            for row in receipt["rows"]],
        "qualification_scope": receipt["qualification_scope"],
        "sample_set_sha256": receipt["sample_set_sha256"],
        "checkpoint_artifact": version["artifact"], "anchor_checkpoint": dict(resolved.anchor_checkpoint),
        "materialized_checkpoint": dict(resolved.materialized_checkpoint),
        "sparse_replay_verified": True, "base_preseed_required": True, "self_contained_restore": False,
        "full_checkpoint_uploaded": False, "model_emits_text_or_formulas": False,
        "ancestors_qualified": False, "admitted": False, "formalized": False,
        "statutory_corpus_qualified": False, "full_corpus_qualified": False,
        "generalization_canary": False,
    }
    _reject_secrets(manifest, label="incremental release manifest")
    manifest_raw = _json(manifest)
    if len(manifest_raw) > MAX_MANIFEST_BYTES:
        raise IncrementalPublicationError("publication manifest exceeds byte bound")
    local = destination / f"update-{_sha(manifest_raw)}.json"
    # Last write commits the locally staged bundle. Orphan content is inert.
    _write(local, manifest_raw)
    return {"manifest_path": str(local), "manifest_artifact": _ref(manifest_raw),
            "path_in_repo": manifest_path, "upload_bytes": len(manifest_raw) + sum(len(x[1]) for x in snapshots.values()),
            "file_count": len(snapshots) + 1, "uploaded": False, "promoted": False,
            "base_preseed_required": True, "admitted": False}


def load_sparse_update(manifest_path: str | Path) -> dict[str, Any]:
    """Validate a local bundle without downloading or loading base weights."""
    path = Path(manifest_path).absolute()
    raw = _read(path, MAX_MANIFEST_BYTES)
    manifest = _object(raw)
    if manifest.get("schema") != SCHEMA or _json(manifest) != raw or manifest.get("repository_id") != REPOSITORY:
        raise IncrementalPublicationError("invalid canonical publication manifest")
    version = _version_record(manifest["version"])
    flags = {"qualified_candidate_only": True, "sparse_replay_verified": True, "base_preseed_required": True,
             "self_contained_restore": False, "full_checkpoint_uploaded": False,
             "model_emits_text_or_formulas": False, "ancestors_qualified": False,
             "admitted": False, "formalized": False, "statutory_corpus_qualified": False,
             "full_corpus_qualified": False, "generalization_canary": False}
    if (any(manifest.get(key) is not value for key, value in flags.items())
            or manifest.get("checkpoint_artifact") != version["artifact"]
            or manifest.get("source_language") != manifest["variant_manifest"].get("source_language")
            or manifest.get("repository_type") != "dataset"):
        raise IncrementalPublicationError("publication authority/identity flags changed")
    namespace = _namespace(version, manifest["variant_manifest"], manifest["lane_id"])
    qualification = sparse.artifact_ref(manifest["qualification_artifact"])
    expected_path = f"{namespace}/versions/{version['version_id'].removeprefix('sha256:')}/{qualification['sha256']}/update.json"
    if manifest.get("path_in_repo") != expected_path or manifest.get("lane_head_path") != namespace + "/qualified.json":
        raise IncrementalPublicationError("publication path differs from bound language/variant/lane")
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise IncrementalPublicationError("invalid publication file count")
    snapshots, by_sha, total = {}, {}, 0
    for file in files:
        ref = sparse.artifact_ref(file)
        kind = file.get("kind")
        if kind not in _KINDS:
            raise IncrementalPublicationError("full checkpoints and unknown file types are not publication artifacts")
        expected = _remote(ref, kind)
        role = "dependency_only" if kind.startswith("sparse_") else "candidate_evidence"
        if (file.get("path_in_repo") != expected or ref["sha256"] in by_sha
                or file.get("qualification_role") != role):
            raise IncrementalPublicationError("unsafe, duplicate or mismatched artifact path")
        total += ref["bytes"]
        if total > MAX_UPLOAD_BYTES:
            raise IncrementalPublicationError("publication byte budget exceeded")
        content = _read(path.parent / "artifacts" / ref["sha256"], ref["bytes"], ref)
        if kind == "sparse_manifest":
            sparse.decode_manifest(content)
        elif kind == "sparse_patch":
            decode_patch(content)
        elif kind == "qualification":
            if ref != qualification:
                raise IncrementalPublicationError("unbound qualification evidence")
            _qualified(_object(content), version)
        elif kind in _PROJECT and content != _PROJECT[kind]:
            raise IncrementalPublicationError("pinned Lake project metadata differs")
        elif kind == "lake_log" and (b"Built Legal" not in content or b"error:" in content):
            raise IncrementalPublicationError("published Lake log does not record a successful build")
        snapshots[expected] = content
        by_sha[ref["sha256"]] = (ref, content, kind)
    if qualification["sha256"] not in by_sha or version["artifact"]["sha256"] not in by_sha:
        raise IncrementalPublicationError("candidate or qualification artifact missing")
    if manifest.get("anchor_checkpoint", {}).get("sha256") in by_sha:
        raise IncrementalPublicationError("full preseed anchor must not be uploaded")
    receipt = _object(by_sha[qualification["sha256"]][1])
    proof_records, _ = _proofs(receipt, read_local=False)
    if manifest.get("proof_evidence") != proof_records:
        raise IncrementalPublicationError("proof evidence differs from exact qualification")
    required = {qualification["sha256"]}
    for proof in proof_records:
        for evidence in proof["files"]:
            entry = by_sha.get(evidence["sha256"])
            if entry is None or entry[0] != sparse.artifact_ref(evidence) or entry[2] != evidence["kind"]:
                raise IncrementalPublicationError("missing or altered proof artifact")
            required.add(evidence["sha256"])
    lineage = [_version_record(row) for row in manifest.get("version_lineage", [])]
    if not 2 <= len(lineage) <= 9 or lineage[0] != version or lineage[-1]["artifact"] != manifest["anchor_checkpoint"]:
        raise IncrementalPublicationError("incomplete version lineage")
    closure = {manifest["anchor_checkpoint"]["sha256"]: sparse.artifact_ref(manifest["anchor_checkpoint"])}
    for child, parent in zip(lineage, lineage[1:]):
        if child["parent_version_id"] != parent["version_id"] or parent["variant_id"] != version["variant_id"]:
            raise IncrementalPublicationError("version lineage mismatch")
        ref = child["artifact"]
        entry = by_sha.get(ref["sha256"])
        if entry is None or entry[0] != ref or entry[2] != "sparse_manifest":
            raise IncrementalPublicationError("missing sparse ancestor manifest")
        decoded = sparse.decode_manifest(entry[1])
        if decoded["parent"] != parent["artifact"] or decoded["base_version_id"] != parent["version_id"]:
            raise IncrementalPublicationError("sparse parent/version binding differs")
        required.add(ref["sha256"])
        closure[ref["sha256"]] = ref
        for patch in decoded["patches"]:
            entry = by_sha.get(patch["sha256"])
            if entry is None or entry[0] != patch or entry[2] != "sparse_patch":
                raise IncrementalPublicationError("missing sparse ancestor patch")
            required.add(patch["sha256"])
            closure[patch["sha256"]] = patch
    if required != set(by_sha):
        raise IncrementalPublicationError("orphan publication artifacts are forbidden")
    if (receipt.get("checkpoint_artifacts") != list(closure.values())
            and {tuple(sorted(sparse.artifact_ref(item).items())) for item in receipt.get("checkpoint_artifacts", [])}
            != {tuple(sorted(item.items())) for item in closure.values()}):
        raise IncrementalPublicationError("qualification sparse closure differs")
    candidate = sparse.decode_manifest(by_sha[version["artifact"]["sha256"]][1])
    if (manifest.get("materialized_checkpoint") != candidate["materialized_checkpoint"]
            or receipt.get("materialized_checkpoint") != candidate["materialized_checkpoint"]
            or manifest.get("qualification_scope") != receipt["qualification_scope"]
            or manifest.get("sample_set_sha256") != receipt["sample_set_sha256"]):
        raise IncrementalPublicationError("manifest identity or scope differs from qualification")
    expected_samples = [{"sample_id": row["sample_id"], "split": row["split"],
                        "source_sha256": row["source_sha256"], "title": row["source"].get("title"),
                        "section": row["source"].get("section"), "citation": row["source"].get("citation")}
                       for row in receipt["rows"]]
    if manifest.get("qualification_samples") != expected_samples:
        raise IncrementalPublicationError("manifest qualification sample scope changed")
    snapshots[expected_path] = raw
    return {"manifest": manifest, "manifest_artifact": _ref(raw), "snapshots": snapshots, "by_sha": by_sha}


def replay_sparse_update(manifest_path: str | Path, *, local_anchor_resolver: Callable) -> dict[str, Any]:
    """Replay exact closure using a caller-provisioned base; no network/import."""
    bundle = load_sparse_update(manifest_path)
    manifest = bundle["manifest"]
    root = Path(manifest_path).absolute().parent
    def resolve(ref):
        if ref["sha256"] in bundle["by_sha"]:
            return root / "artifacts" / ref["sha256"]
        if ref != manifest["anchor_checkpoint"]:
            raise IncrementalPublicationError("unpublished sparse dependency")
        return local_anchor_resolver(ref)
    resolved = sparse.resolve_checkpoint(manifest["checkpoint_artifact"], resolver=resolve)
    if dict(resolved.materialized_checkpoint) != manifest["materialized_checkpoint"]:
        raise IncrementalPublicationError("replayed state differs from publication identity")
    return {"replayed": True, "materialized_checkpoint": dict(resolved.materialized_checkpoint),
            "state_identity": resolved.state_identity, "depth": resolved.depth,
            "base_preseed_required": True, "downloaded_weights": False,
            "registered": False, "promoted": False, "admitted": False}


def _matches(remote: Any, raw: bytes) -> bool:
    lfs = getattr(remote, "lfs", None)
    digest = lfs.get("sha256") if isinstance(lfs, Mapping) else getattr(lfs, "sha256", None)
    if digest:
        return digest == _sha(raw)
    git_digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return getattr(remote, "blob_id", None) == git_digest


def publish_sparse_update(manifest_path: str | Path, *, upload: bool = False,
                          promote_lane: bool = False, expected_lane_head: Mapping[str, Any] | None = None,
                          owner_head_validator: Callable[[Mapping[str, Any]], bool] | None = None,
                          api: Any = None) -> dict[str, Any]:
    """Atomic append and optional lane CAS, with immutable retry recovery.

    Publication is not promotion. Head advancement additionally requires the
    trusted owner's policy, plus exact previously observed head bytes (or
    absence). Neither downloaded metadata nor worker booleans authorize it.
    """
    bundle = load_sparse_update(manifest_path)
    manifest = bundle["manifest"]
    snapshots = bundle["snapshots"]
    result = {"schema": SCHEMA, "repository_id": REPOSITORY,
              "manifest_artifact": bundle["manifest_artifact"], "uploaded": False,
              "lane_promoted": False, "dry_run": not upload, "admitted": False,
              "full_checkpoint_uploaded": False, "base_preseed_required": True}
    if promote_lane:
        if owner_head_validator is None or owner_head_validator(manifest) is not True:
            raise IncrementalPublicationError("lane advancement requires a trusted owner policy")
        generation = 0
        if expected_lane_head is not None:
            if (expected_lane_head.get("schema") != HEAD_SCHEMA
                    or expected_lane_head.get("variant_id") != manifest["version"]["variant_id"]
                    or expected_lane_head.get("lane_id") != manifest["lane_id"]
                    or expected_lane_head.get("source_language") != manifest["source_language"]
                    or type(expected_lane_head.get("generation")) is not int
                    or expected_lane_head["generation"] < 1):
                raise IncrementalPublicationError("expected lane head binding is invalid")
            generation = expected_lane_head["generation"]
            if len(_json(expected_lane_head)) > 65_536:
                raise IncrementalPublicationError("expected head metadata exceeds bound")
        desired_head = {"schema": HEAD_SCHEMA, "variant_id": manifest["version"]["variant_id"],
                        "source_language": manifest["source_language"], "lane_id": manifest["lane_id"],
                        "version_id": manifest["version"]["version_id"], "generation": generation + 1,
                        "manifest_artifact": bundle["manifest_artifact"], "manifest_path": manifest["path_in_repo"],
                        "qualification_scope": manifest["qualification_scope"],
                        "sample_set_sha256": manifest["sample_set_sha256"], "global_best": False,
                        "admitted": False, "formalized": False}
        snapshots[manifest["lane_head_path"]] = _json(desired_head)
        result["lane_head"] = desired_head
    if not upload:
        return result
    from huggingface_hub import HfApi, CommitOperationAdd
    api = api or HfApi()
    info = api.repo_info(repo_id=REPOSITORY, repo_type="dataset")
    parent = str(info.sha)
    if not _COMMIT.fullmatch(parent):
        raise IncrementalPublicationError("Hub returned no immutable parent commit")
    remote_rows = list(api.get_paths_info(REPOSITORY, list(snapshots), repo_type="dataset", revision=parent))
    if len(remote_rows) > len(snapshots):
        raise IncrementalPublicationError("remote metadata exceeds requested path count")
    present = set()
    observed = set()
    for remote in remote_rows:
        remote_path = str(getattr(remote, "path", "") or getattr(remote, "rfilename", ""))
        if remote_path not in snapshots or remote_path in observed:
            raise IncrementalPublicationError("unexpected or duplicate remote path")
        observed.add(remote_path)
        if _matches(remote, snapshots[remote_path]):
            present.add(remote_path)
        elif promote_lane and remote_path == manifest["lane_head_path"]:
            if expected_lane_head is None or not _matches(remote, _json(expected_lane_head)):
                raise IncrementalPublicationError("lane head compare-and-swap conflict")
        else:
            raise IncrementalPublicationError("immutable remote artifact conflicts")
    if promote_lane and expected_lane_head is not None:
        remote_paths = {str(getattr(row, "path", "") or getattr(row, "rfilename", "")) for row in remote_rows}
        if manifest["lane_head_path"] not in remote_paths:
            raise IncrementalPublicationError("expected lane head disappeared")
    operations = [CommitOperationAdd(path_in_repo=path, path_or_fileobj=raw)
                  for path, raw in snapshots.items() if path not in present]
    if operations:
        created = api.create_commit(repo_id=REPOSITORY, repo_type="dataset", operations=operations,
                                    parent_commit=parent,
                                    commit_message="Append qualified sparse autoencoder update and exact evidence")
        commit = str(getattr(created, "oid", "") or (created.get("oid", "") if isinstance(created, Mapping) else ""))
    else:
        commit = parent
    if not _COMMIT.fullmatch(commit):
        raise IncrementalPublicationError("Hub returned no immutable publication commit")
    verified = set()
    for remote in api.get_paths_info(REPOSITORY, list(snapshots), repo_type="dataset", revision=commit):
        path = str(getattr(remote, "path", "") or getattr(remote, "rfilename", ""))
        if path not in snapshots or path in verified or not _matches(remote, snapshots[path]):
            raise IncrementalPublicationError("pinned post-publication artifact verification failed")
        verified.add(path)
    if verified != set(snapshots):
        raise IncrementalPublicationError("pinned publication is missing expected artifacts")
    result.update(uploaded=True, dry_run=False, commit_sha=commit, parent_commit=parent,
                  lane_promoted=promote_lane, remote_already_present=not operations)
    # Content-addressed delivery receipts survive ambiguous retries or a later
    # unrelated Hub commit without overwriting historical evidence.
    receipt = Path(manifest_path).absolute().parent / "deliveries" / f"{_sha(_json(result))}.json"
    _write(receipt, _json(result))
    return {**result, "receipt_path": str(receipt)}


def enqueue_sparse_update(registry: Any, manifest_path: str | Path) -> dict[str, Any]:
    """Durably queue one verified bundle through the existing owner outbox.

    The content-addressed operation makes a crash between this enqueue and the
    runner's progress commit safe to retry. This performs no network request.
    """
    bundle = load_sparse_update(manifest_path)
    manifest = bundle["manifest"]
    if _version_record(registry.get_version(manifest["version"]["version_id"])) != manifest["version"]:
        raise IncrementalPublicationError("publication version differs from owner registry")
    root = Path(manifest_path).absolute().parent
    for ref, _, _ in bundle["by_sha"].values():
        staged = registry.stage_artifact(root / "artifacts" / ref["sha256"], expected_sha256=ref["sha256"])
        if staged != ref:
            raise IncrementalPublicationError("owner staging changed publication artifact identity")
    plan = registry.stage_artifact(manifest_path, expected_sha256=bundle["manifest_artifact"]["sha256"])
    result = registry.enqueue_publication("sparse-publication-" + plan["sha256"],
                                          manifest["version"]["version_id"], plan)
    return {**result, "plan_artifact": plan, "uploaded": False, "admitted": False}


def deliver_sparse_update(registry: Any, event_id: str, *, upload: bool = False,
                          worker_id: str = "sparse-hf-publisher", state_directory: str | Path | None = None,
                          api: Any = None) -> dict[str, Any]:
    """Deliver exactly one owned outbox event; acknowledge only pinned success.

    Failed or ambiguous network calls leave the event durable and retryable.
    Reusing a live lease is allowed only for its exact worker and owner epoch.
    The delivery path never promotes a lane or imports downloaded weights.
    """
    event = registry.get_outbox_event("huggingface", event_id)
    if event["status"] == "acknowledged":
        return {**event["receipt"], "event_id": event_id, "acknowledged": True, "already_delivered": True}
    if event["kind"] != "publication_requested":
        return {"event_id": event_id, "uploaded": False, "acknowledged": False, "deferred": "different_event_kind"}
    plan = sparse.artifact_ref(event["payload"]["plan_artifact"])
    raw = _read(Path(registry.artifact_path(plan)), MAX_MANIFEST_BYTES, plan)
    manifest = _object(raw)
    if manifest.get("schema") != SCHEMA:
        return {"event_id": event_id, "uploaded": False, "acknowledged": False, "deferred": "different_publication_schema"}
    if (manifest["version"]["version_id"] != event["payload"]["version_id"]
            or _version_record(registry.get_version(event["payload"]["version_id"])) != manifest["version"]):
        raise IncrementalPublicationError("outbox publication version binding differs")
    root = Path(state_directory) if state_directory is not None else Path(registry.artifact_root).parent / "hf-sparse-publications"
    directory = root.absolute() / plan["sha256"]
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise IncrementalPublicationError("invalid outbox publication file count")
    total = 0
    for item in files:
        ref = sparse.artifact_ref(item)
        total += ref["bytes"]
        if total > MAX_UPLOAD_BYTES:
            raise IncrementalPublicationError("outbox publication exceeds byte bound")
        content = _read(Path(registry.artifact_path(ref)), ref["bytes"], ref)
        _write(directory / "artifacts" / ref["sha256"], content)
    local = directory / ("update-" + plan["sha256"] + ".json")
    _write(local, raw)
    load_sparse_update(local)
    if not upload:
        return {**publish_sparse_update(local), "event_id": event_id, "acknowledged": False}
    from uuid import uuid4
    attempt = "sparse-delivery-" + uuid4().hex
    lease = event.get("lease")
    if lease and registry._live(lease) and lease.get("worker_id") == worker_id:
        lease = registry.renew_outbox(attempt + "-renew", event_id, "huggingface", lease)["lease"]
    else:
        lease = registry.claim_outbox_event(attempt + "-claim", event_id, "huggingface", worker_id)["delivery"]["lease"]
    result = publish_sparse_update(local, upload=True, api=api)
    receipt = {**result, "event_id": event_id, "version_id": event["payload"]["version_id"]}
    acknowledged = registry.ack_outbox(attempt + "-ack", event_id, "huggingface", receipt, lease)
    return {**receipt, "acknowledged": acknowledged["acknowledged"]}

"""Recover exact complete Python files for pinned, family-split CVE observations.

GitHub commit metadata establishes the single-parent relationship through its
HTTPS API; it is not a locally replayed Git commit-object proof. Tree and blob
Git SHA-1 preimages are independently checked, and retained UTF-8 file bytes
receive SHA-256 and native SourceRecord/CodeUnit identities. No diff is patched,
no source is executed, and row polarity is not a per-function security label.
"""
from __future__ import annotations

import ast
import base64
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import warnings
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import security_cve_corpus as corpus_api
from . import security_cve_canonical_export as canonical
from .security_cve_training_source import BenchmarkExclusions, CVETrainingSourceError, _family
from ..source_screening import _contains_secret, _credential_path_reason
from ....ir_core.identity import canonical_identity
from ....security_ir.cvefixes.schemas import SourceRecord, CodeUnit, DerivedDataset, canonical_config_cid

SCHEMA = "security-cve-complete-source-context@1"
MAXIMUM = 1024 * 1024
AUTHORITY = {"proof_authority": False, "execution_authority": False,
             "source_semantics_verified": False, "heldout_evaluated": False}
BOUNDARY = "local source context; repository license review required before redistribution; corpus label is not a per-file or per-function vulnerability proof"


class SourceContextError(CVETrainingSourceError):
    pass


class FetchUnavailable(Exception):
    def __init__(self, reason, *, response_bytes=0):
        if reason not in {"http_error", "network_error", "redirect_refused", "response_too_large"}:
            raise ValueError("closed source transport failure required")
        self.reason, self.response_bytes = reason, response_bytes
        super().__init__(reason)


class _Frontier(Exception):
    pass


def _json(value):
    return canonical._json(value)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _git(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()


def _hex(value, length=40):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{%d}" % length, value) is None:
        raise SourceContextError("exact immutable source object digest required")
    return value


def _path(value):
    if (type(value) is not str or not value or len(value) > 512 or "\\" in value
            or any(ord(x) < 32 for x in value) or "%" in value
            or str(PurePosixPath(value)) != value or PurePosixPath(value).is_absolute()
            or any(x in {".", ".."} for x in value.split("/"))):
        raise SourceContextError("canonical relative repository path required")
    return value


def _repository(value):
    family = _family(value)
    if (not value.startswith("https://github.com/") or not re.fullmatch(
            r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", family)):
        raise SourceContextError("explicit public GitHub repository required")
    return family


@dataclass(frozen=True)
class GitSourceRequest:
    repository_url: str
    kind: str
    object_sha: str

    def __post_init__(self):
        _repository(self.repository_url); _hex(self.object_sha)
        if self.kind not in {"commits", "trees", "blobs"}:
            raise SourceContextError("closed Git object request required")

    @property
    def key(self):
        return _family(self.repository_url) + "/" + self.kind + "/" + self.object_sha

    @property
    def url(self):
        return "https://api.github.com/repos/" + _repository(self.repository_url).split("/", 1)[1] + "/git/" + self.kind + "/" + self.object_sha


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FetchUnavailable("redirect_refused")


def _response_bytes(response, maximum):
    chunks, count = [], 0
    # read1 returns available bytes after one underlying read, so a subsequent
    # timeout does not erase the already-accounted earlier chunks.
    reader = getattr(response, "read1", response.read)
    try:
        while count <= maximum:
            chunk = reader(min(65536, maximum + 1 - count))
            if not chunk:
                break
            chunks.append(chunk); count += len(chunk)
    except (TimeoutError, OSError):
        raise FetchUnavailable("network_error", response_bytes=count) from None
    return b"".join(chunks)


def fetch_public_git_object(request: GitSourceRequest, maximum: int) -> bytes:
    """Anonymous, no-redirect, bounded HTTPS request. No credentials are read."""
    if type(request) is not GitSourceRequest or type(maximum) is not int or not 0 < maximum <= MAXIMUM:
        raise SourceContextError("typed bounded public source request required")
    http = Request(request.url, headers={"Accept": "application/vnd.github+json",
        "User-Agent": "ipfs-datasets-source-context/1", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with build_opener(_NoRedirect).open(http, timeout=30) as response:
            raw = _response_bytes(response, maximum)
        if len(raw) > maximum:
            raise FetchUnavailable("response_too_large", response_bytes=len(raw))
        return raw
    except HTTPError as error:
        try:
            raw = _response_bytes(error, maximum)
        finally:
            error.close()
        raise FetchUnavailable("http_error", response_bytes=len(raw)) from None
    except (URLError, TimeoutError):
        raise FetchUnavailable("network_error") from None


def _budget(value):
    default = {"max_requests": 64, "max_response_bytes": MAXIMUM,
               "max_total_response_bytes": 16 * MAXIMUM, "max_file_bytes": 512 * 1024, "max_files": 32}
    value = default if value is None else dict(value)
    if (set(value) != set(default) or any(type(x) is not int or x <= 0 for x in value.values())
            or any(value[k] > default[k] for k in default)
            or value["max_total_response_bytes"] < value["max_response_bytes"]):
        raise SourceContextError("bounded explicit source-context budget required")
    return value


def _plans(corpus, expected_manifest_sha256):
    checked = corpus_api.load_security_corpus(corpus, expected_manifest_sha256=expected_manifest_sha256)
    exclusions = BenchmarkExclusions(**checked["manifest"]["profile"]["benchmark_exclusions"])
    plans = []
    for split in corpus_api.SPLITS:
        loaded = canonical.load_canonical_cve_training(Path(corpus) / split,
            expected_manifest_sha256=checked["manifest"]["exports"][split]["manifest_sha256"])
        for record in loaded["records"]:
            if not isinstance(record, SourceRecord):
                continue
            value = record.to_dict(); payload = value["payload"]
            repository, revision = payload["repo_url"], _hex(payload["hash"])
            if exclusions.excludes_family(repository):
                raise SourceContextError("benchmark repository excluded before source network access")
            _repository(repository)
            paths = payload["file_paths"]
            if type(paths) is not list or not paths or len(paths) > 128 or len(set(paths)) != len(paths):
                raise SourceContextError("unambiguous declared changed-file paths required")
            for path in paths:
                _path(path)
                if PurePosixPath(path).name.casefold() in exclusions.file_names or _credential_path_reason(path):
                    raise SourceContextError("benchmark or credential source path excluded before source network access")
            plans.append({"split": split, "source_record": value, "repository_url": repository,
                "repository_family": _family(repository), "fixed_revision": revision,
                "paths": sorted(path for path in paths if path.endswith(".py")
                    and not any(part in {"test", "tests"} for part in PurePosixPath(path).parts)),
                "omitted_paths": sorted(path for path in paths if not path.endswith(".py")
                    or any(part in {"test", "tests"} for part in PurePosixPath(path).parts))})
    return plans, exclusions


def _commit(request, value):
    if value.get("sha") != request.object_sha or type(value.get("parents")) is not list or type(value.get("tree")) is not dict:
        raise SourceContextError("commit response revision, parents or tree differs")
    parents = [_hex(item["sha"]) for item in value["parents"]]
    if len(parents) > 16 or len(set(parents)) != len(parents) or request.object_sha in parents:
        raise SourceContextError("invalid commit parent identities")
    return {"sha": request.object_sha, "tree_sha": _hex(value["tree"]["sha"]), "parents": parents,
            "commit_object_preimage_verified": False, "binding": "pinned HTTPS Git API response"}


def _tree(request, value):
    if value.get("sha") != request.object_sha or value.get("truncated") is not False or type(value.get("tree")) is not list:
        raise SourceContextError("complete exact Git tree response required")
    entries = []
    for row in value["tree"]:
        path = _path(row["path"])
        if "/" in path or row.get("mode") not in {"040000", "100644", "100755", "120000", "160000"}:
            raise SourceContextError("nonrecursive Git tree and known object mode required")
        wanted = {"040000": "tree", "100644": "blob", "100755": "blob", "120000": "blob", "160000": "commit"}[row["mode"]]
        if row.get("type") != wanted:
            raise SourceContextError("Git tree object mode and type disagree")
        entries.append({"path": path, "mode": row["mode"], "type": wanted, "sha": _hex(row["sha"])})
    if len(entries) > 16384 or len({x["path"] for x in entries}) != len(entries):
        raise SourceContextError("bounded unique Git tree entries required")
    entries.sort(key=lambda x: (x["path"] + ("/" if x["type"] == "tree" else "")).encode())
    raw = b"".join(x["mode"].lstrip("0").encode() + b" " + x["path"].encode() + b"\x00" + bytes.fromhex(x["sha"]) for x in entries)
    if _git("tree", raw) != request.object_sha:
        raise SourceContextError("Git tree SHA-1 preimage differs")
    return {"sha": request.object_sha, "tree": entries, "truncated": False}


def _blob(request, value, budget, exclusions):
    if value.get("sha") != request.object_sha or value.get("encoding") != "base64" or type(value.get("content")) is not str:
        raise SourceContextError("exact encoded Git blob required")
    try:
        raw = base64.b64decode(value["content"].replace("\n", ""), validate=True)
    except (ValueError, base64.binascii.Error):
        raise SourceContextError("invalid Git blob encoding") from None
    if type(value.get("size")) is not int or value["size"] != len(raw) or len(raw) > budget["max_file_bytes"]:
        raise SourceContextError("complete bounded Git file size differs")
    if _git("blob", raw) != request.object_sha:
        raise SourceContextError("Git blob SHA-1 preimage differs")
    if _sha(raw) in exclusions.code_sha256:
        raise SourceContextError("benchmark source bytes excluded")
    if _contains_secret(raw):
        raise SourceContextError("complete source refused by native secret screen")
    try:
        raw.decode("utf-8")
    except UnicodeError:
        raise _Frontier("non_utf8_source") from None
    return raw


def _coverage(raw):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, ValueError, UnicodeError, RecursionError):
        return {"status": "unsupported", "function_count": 0}
    return {"status": "valid", "function_count": sum(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) for x in ast.walk(tree))}


def _records(plan, path, polarity, revision, tree_sha, blob_sha, raw, config_cid):
    origin = SourceRecord.from_dict(plan["source_record"])
    sha = _sha(raw)
    source = SourceRecord(source_cids=origin.source_cids, parent_cids=(origin.cid,), config_cid=config_cid,
        source_uri=plan["repository_url"], source_revision=revision,
        row_key=origin.row_key + ":" + polarity + ":" + path,
        payload={"context_schema": SCHEMA, "path": path, "repository_family": plan["repository_family"],
            "split": plan["split"], "fixed_revision": plan["fixed_revision"], "root_tree_sha": tree_sha,
            "blob_sha": blob_sha, "body_sha256": sha, "body_bytes": len(raw), "body_scope": "complete_repository_file",
            "polarity_interpretation": "CVE fixing commit versus its unique parent; not function-level vulnerability classification",
            "license_scope": BOUNDARY, "grants_execution_authority": False})
    body_cid = canonical_identity({"body": raw.decode("utf-8")}, domain="cvefixes-security-ir/code-body", schema_version="cvefixes-code-body/v1").cid
    unit = CodeUnit(source_cids=origin.source_cids, parent_cids=(origin.cid, source.cid), config_cid=config_cid,
        unit_kind="file", language="python", path=path, polarity=polarity,
        payload={"body_sha256": sha, "body_cid": body_cid, "source_context_cid": source.cid,
            "source_revision": revision, "body_scope": "complete_repository_file", "grants_execution_authority": False})
    return source, unit


def _resolve(plan, path, polarity, lookup):
    repository = plan["repository_url"]
    fixed = lookup(GitSourceRequest(repository, "commits", plan["fixed_revision"]))
    if len(fixed["parents"]) != 1:
        raise _Frontier("unique_parent_unavailable")
    revision = plan["fixed_revision"] if polarity == "fixed" else fixed["parents"][0]
    commit = fixed if polarity == "fixed" else lookup(GitSourceRequest(repository, "commits", revision))
    tree_sha = commit["tree_sha"]; current = tree_sha
    parts = path.split("/")
    for index, part in enumerate(parts):
        tree = lookup(GitSourceRequest(repository, "trees", current))
        item = next((row for row in tree["tree"] if row["path"] == part), None)
        if item is None:
            raise _Frontier("path_absent_at_exact_revision; rename_or_deletion_not_inferred")
        if index < len(parts) - 1:
            if item["type"] != "tree": raise _Frontier("path_component_is_not_tree")
            current = item["sha"]
        elif item["mode"] not in {"100644", "100755"}:
            raise _Frontier("symlink_or_submodule_source_unsupported")
        else:
            return revision, tree_sha, item["sha"], lookup(GitSourceRequest(repository, "blobs", item["sha"]))
    raise SourceContextError("empty source path")


def _assemble(plans, lookup, config_cid):
    entries, frontiers, split_hashes = [], [], {}
    # Native datasets require at least one record. Retain the exact originating
    # SourceRecords even for an entirely unsupported recovery, without inventing
    # a CodeUnit or promoting its classification metadata to source features.
    records = {p["source_record"]["record_id"]: SourceRecord.from_dict(p["source_record"]) for p in plans}
    for plan in plans:
        for path in plan["paths"]:
            for polarity in ("vulnerable", "fixed"):
                identity = {"split": plan["split"], "source_record_cid": plan["source_record"]["record_id"],
                    "repository_family": plan["repository_family"], "path": path, "polarity": polarity}
                try:
                    revision, tree_sha, blob_sha, raw = _resolve(plan, path, polarity, lookup)
                except _Frontier as error:
                    frontiers.append({**identity, "reason": str(error)}); continue
                sha = _sha(raw)
                if sha in split_hashes and split_hashes[sha] != plan["split"]:
                    raise SourceContextError("recovered complete-file bytes overlap across corpus splits")
                split_hashes[sha] = plan["split"]
                source, unit = _records(plan, path, polarity, revision, tree_sha, blob_sha, raw, config_cid)
                records[source.cid], records[unit.cid] = source, unit
                entries.append({**identity, "revision": revision, "body_sha256": sha, "body_bytes": len(raw),
                    "body_path": "bodies/" + sha + ".py", "blob_sha": blob_sha,
                    "source_context_cid": source.cid, "code_unit_cid": unit.cid, "ast": _coverage(raw)})
    return entries, frontiers, DerivedDataset(records=tuple(records.values()))


def recover_security_source_context(*, corpus: Path, expected_manifest_sha256: str,
        output: Path, fetcher=fetch_public_git_object, budget=None):
    """Recover changed non-test Python paths only; never infer rename mappings."""
    corpus = corpus_api._root(corpus); output = corpus_api._root(output, fresh=True)
    plans, exclusions = _plans(corpus, expected_manifest_sha256); budget = _budget(budget)
    if not plans:
        raise SourceContextError("source context requires admitted corpus source records")
    if output == corpus or corpus in output.parents or sum(2 * len(p["paths"]) for p in plans) > budget["max_files"]:
        raise SourceContextError("isolated bounded complete-source selection required")
    config = {"schema": SCHEMA, "budget": budget, "selection": "declared changed non-test Python paths",
        "parent_policy": "exactly one parent; no guessed merge or rename mapping"}
    config_cid = canonical_config_cid(config, schema_version=SCHEMA)
    objects, bodies, attempts = {}, {}, []
    consumed = 0
    def lookup(request):
        nonlocal consumed
        if request.key not in objects:
            if exclusions.excludes_family(request.repository_url):
                raise SourceContextError("benchmark excluded before public source request")
            remaining = budget["max_total_response_bytes"] - consumed
            if len(attempts) >= budget["max_requests"] or remaining <= 1:
                objects[request.key] = {"request": asdict(request), "status": "unavailable", "reason": "transport_budget_exhausted"}
            else:
                limit = min(budget["max_response_bytes"], remaining - 1)
                try:
                    raw = fetcher(request, limit)
                    if type(raw) is not bytes or not raw or len(raw) > limit:
                        raise SourceContextError("source fetcher violated bounded byte response contract")
                    consumed += len(raw)
                    attempts.append({"request": asdict(request), "response_bytes": len(raw), "response_sha256": _sha(raw), "status": "received"})
                    value = canonical.native._strict_json_object(raw, "public source object")
                    if request.kind == "commits": normalized = _commit(request, value)
                    elif request.kind == "trees": normalized = _tree(request, value)
                    else:
                        body = _blob(request, value, budget, exclusions); digest = _sha(body); bodies[digest] = body
                        normalized = {"sha": request.object_sha, "body_sha256": digest, "bytes": len(body)}
                    objects[request.key] = {"request": asdict(request), "status": "available", "value": normalized}
                except FetchUnavailable as error:
                    if type(error.response_bytes) is not int or not 0 <= error.response_bytes <= limit + 1:
                        raise SourceContextError("transport failure byte accounting differs")
                    consumed += error.response_bytes
                    attempts.append({"request": asdict(request), "response_bytes": error.response_bytes, "response_sha256": None, "status": error.reason})
                    objects[request.key] = {"request": asdict(request), "status": "unavailable", "reason": error.reason}
                except _Frontier as error:
                    objects[request.key] = {"request": asdict(request), "status": "unavailable", "reason": str(error)}
        item = objects[request.key]
        if item["status"] == "unavailable": raise _Frontier(item["reason"])
        value = item["value"]
        return bodies[value["body_sha256"]] if request.kind == "blobs" else value
    entries, frontiers, records = _assemble(plans, lookup, config_cid)
    # Revalidate original corpus identity after all network work.
    if _plans(corpus, expected_manifest_sha256)[0] != plans:
        raise SourceContextError("pinned corpus changed during source recovery")
    manifest = {"schema": SCHEMA, "corpus": {"output": str(corpus), "manifest_sha256": expected_manifest_sha256},
        "config": config, "config_cid": config_cid, "plans": plans, "objects": objects, "attempts": attempts,
        "response_body_bytes": consumed, "network_byte_scope": "HTTP response bodies including received failures; excludes protocol headers and connection overhead",
        "entries": entries, "frontiers": frontiers, "records_sha256": _sha(records.canonical_bytes()),
        "license_scope": BOUNDARY, "fragment_reconstruction_used": False, "model_training_steps": 0,
        "commit_binding": "pinned HTTPS API metadata; full commit-object hash preimage not reconstructed", **AUTHORITY}
    raw = _json(manifest); digest = _sha(raw)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".source-context-", dir=output.parent) as temp:
        stage = Path(temp) / "context"; stage.mkdir(); (stage / "bodies").mkdir()
        for sha, body in bodies.items(): (stage / "bodies" / (sha + ".py")).write_bytes(body)
        (stage / "records.json").write_bytes(records.canonical_bytes()); (stage / "manifest.json").write_bytes(raw)
        load_security_source_context(stage, expected_manifest_sha256=digest)
        if output.exists(): raise SourceContextError("source output appeared during recovery")
        stage.rename(output)
    return {"schema": SCHEMA, "output": str(output), "manifest_sha256": digest,
        "complete_file_count": len(entries), "frontier_count": len(frontiers),
        "valid_ast_file_count": sum(x["ast"]["status"] == "valid" for x in entries),
        "function_count": sum(x["ast"]["function_count"] for x in entries),
        "request_count": len(attempts), "response_body_bytes": consumed, **AUTHORITY}


def load_security_source_context(root: Path, *, expected_manifest_sha256: str):
    """Replay exact corpus, Git tree/blob identities, complete files and CIDs offline."""
    root = corpus_api._root(root)
    if {p.name for p in root.iterdir()} != {"manifest.json", "records.json", "bodies"} or (root / "bodies").is_symlink():
        raise SourceContextError("closed complete-source artifact inventory required")
    raw = canonical.codebase_autoencoder._read(root / "manifest.json", limit=8 * MAXIMUM)
    if _sha(raw) != _hex(expected_manifest_sha256, 64): raise SourceContextError("source-context manifest digest differs")
    value = canonical.native._strict_json_object(raw, "complete source manifest")
    fields = {"schema", "corpus", "config", "config_cid", "plans", "objects", "attempts", "response_body_bytes",
        "network_byte_scope", "entries", "frontiers", "records_sha256", "license_scope", "fragment_reconstruction_used", "model_training_steps", "commit_binding", *AUTHORITY}
    if (set(value) != fields or value["schema"] != SCHEMA or any(value[k] is not False for k in AUTHORITY)
            or value["fragment_reconstruction_used"] is not False or value["model_training_steps"] != 0 or value["license_scope"] != BOUNDARY
            or value["commit_binding"] != "pinned HTTPS API metadata; full commit-object hash preimage not reconstructed"
            or value["network_byte_scope"] != "HTTP response bodies including received failures; excludes protocol headers and connection overhead"):
        raise SourceContextError("closed non-authoritative complete-source manifest required")
    if set(value["corpus"]) != {"output", "manifest_sha256"}: raise SourceContextError("exact source corpus descriptor required")
    plans, exclusions = _plans(Path(value["corpus"]["output"]), value["corpus"]["manifest_sha256"])
    config = value["config"]; budget = _budget(config.get("budget"))
    expected_config = {"schema": SCHEMA, "budget": budget, "selection": "declared changed non-test Python paths", "parent_policy": "exactly one parent; no guessed merge or rename mapping"}
    if config != expected_config or value["plans"] != plans or value["config_cid"] != canonical_config_cid(config, schema_version=SCHEMA):
        raise SourceContextError("source recovery selection or configuration differs")
    if not plans or sum(2 * len(plan["paths"]) for plan in plans) > budget["max_files"]:
        raise SourceContextError("complete source file selection exceeds replay budget")
    objects = value["objects"]; touched, bodies = set(), {}
    for key, item in objects.items():
        request = GitSourceRequest(**item["request"])
        if key != request.key or exclusions.excludes_family(request.repository_url): raise SourceContextError("source object routing differs")
        if item["status"] == "unavailable":
            if set(item) != {"request", "status", "reason"} or item["reason"] not in {"http_error", "network_error", "redirect_refused", "response_too_large", "transport_budget_exhausted", "non_utf8_source"}:
                raise SourceContextError("closed source retrieval frontier required")
        elif item["status"] == "available":
            if set(item) != {"request", "status", "value"}: raise SourceContextError("closed source object evidence required")
            evidence = item["value"]
            if request.kind == "commits":
                expected = _commit(request, {"sha": evidence["sha"], "tree": {"sha": evidence["tree_sha"]}, "parents": [{"sha": x} for x in evidence["parents"]]})
                if evidence != expected: raise SourceContextError("commit evidence authority or shape differs")
            elif request.kind == "trees":
                if evidence != _tree(request, evidence): raise SourceContextError("tree evidence shape differs")
            else:
                if set(evidence) != {"sha", "body_sha256", "bytes"} or evidence["sha"] != request.object_sha:
                    raise SourceContextError("closed body evidence required")
                sha = _hex(evidence["body_sha256"], 64)
                body = canonical.codebase_autoencoder._read(root / "bodies" / (sha + ".py"), limit=budget["max_file_bytes"])
                if _sha(body) != sha or _git("blob", body) != request.object_sha or len(body) != evidence["bytes"]:
                    raise SourceContextError("complete source bytes differ from Git blob or SHA256")
                if sha in exclusions.code_sha256 or _contains_secret(body): raise SourceContextError("source exclusion or screen differs")
                body.decode("utf-8"); bodies[sha] = body
        else: raise SourceContextError("unknown source object status")
    attempts = value["attempts"]
    if type(attempts) is not list or len(attempts) > budget["max_requests"]: raise SourceContextError("source request budget differs")
    attempted = set(); consumed = 0
    for attempt in attempts:
        if set(attempt) != {"request", "response_bytes", "response_sha256", "status"}: raise SourceContextError("closed transport receipt required")
        req = GitSourceRequest(**attempt["request"]); count = attempt["response_bytes"]
        remaining = budget["max_total_response_bytes"] - consumed
        limit = min(budget["max_response_bytes"], remaining - 1)
        allowance = limit if attempt["status"] == "received" else limit + 1
        if (req.key in attempted or req.key not in objects or type(count) is not int
                or limit <= 0 or not 0 <= count <= allowance):
            raise SourceContextError("source response receipt binding differs")
        attempted.add(req.key); consumed += count
        item = objects[req.key]
        if attempt["status"] == "received":
            _hex(attempt["response_sha256"], 64)
            if item["status"] == "unavailable" and item["reason"] != "non_utf8_source":
                raise SourceContextError("received source object and frontier disagree")
        elif attempt["status"] not in {"http_error", "network_error", "redirect_refused", "response_too_large"} or attempt["response_sha256"] is not None:
            raise SourceContextError("source transport status differs")
        elif item["status"] != "unavailable" or item["reason"] != attempt["status"]:
            raise SourceContextError("failed transport cannot certify an available source object")
    if consumed != value["response_body_bytes"] or consumed > budget["max_total_response_bytes"]:
        raise SourceContextError("source response byte budget differs")
    for key, item in objects.items():
        if key not in attempted and not (item["status"] == "unavailable" and item["reason"] == "transport_budget_exhausted"):
            raise SourceContextError("source object lacks transport evidence")
    def lookup(request):
        touched.add(request.key)
        if request.key not in objects: raise SourceContextError("incomplete source evidence replay")
        item = objects[request.key]
        if item["status"] == "unavailable": raise _Frontier(item["reason"])
        return bodies[item["value"]["body_sha256"]] if request.kind == "blobs" else item["value"]
    entries, frontiers, records = _assemble(plans, lookup, value["config_cid"])
    if touched != set(objects) or entries != value["entries"] or frontiers != value["frontiers"]:
        raise SourceContextError("complete source coverage or frontier replay differs")
    records_raw = canonical.codebase_autoencoder._read(root / "records.json", limit=8 * MAXIMUM)
    if _sha(records_raw) != value["records_sha256"] or records_raw != records.canonical_bytes():
        raise SourceContextError("native complete source record identities differ")
    if {p.name for p in (root / "bodies").iterdir()} != {sha + ".py" for sha in bodies}:
        raise SourceContextError("closed source-body inventory differs")
    return {"manifest": value, "records": records.records, "entries": entries, "frontiers": frontiers, **AUTHORITY}

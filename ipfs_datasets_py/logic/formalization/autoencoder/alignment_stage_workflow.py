"""Publish pinned stage diagnostics in a bounded trusted subprocess.

This is not an OS sandbox or semantic admission. Embedded paths are never
selected implicitly. A nonnull role file binding selects a detached role file:
its JSON equals the role without ``file_binding`` and ``content_sha256``.
The full sealed saved ranking file is selected separately for scoring.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import json
import math
import os
import resource
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import alignment_lane_bundle as lane
from . import alignment_stage_declarations as core

SCHEMA = "alignment-stage-workflow/v1"
MAX_AGGREGATE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MEMORY_BYTES = 768 * 1024 * 1024
SELECTION_FIELDS = {"path", "sha256", "bytes"}
LANE_SELECTIONS = {"query_bundle", "expected_query_lane", "bank_bundle", "expected_bank_lane"}
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_stage_workflow.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_stage_declarations.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_lane_bundle.py",
    "scripts/ops/autoencoder/run_alignment_stage.py",
)


def _path(value):
    core._require(type(value) is str and value.strip() and len(value) <= 4096 and "\x00" not in value,
                  "bounded explicit file path required")
    path = Path(value)
    core._require(".." not in path.parts, "parent traversal paths are unsupported")
    return path.absolute()


def _components(path, *, missing=False):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            core._require(missing, "selected path component is missing")
            continue
        core._require(not stat.S_ISLNK(info.st_mode), "symlink path components are forbidden")


def _selection(value):
    core._closed(value, SELECTION_FIELDS, "explicit file selection")
    path = _path(value["path"])
    core._sha(value["sha256"], "selected exact file SHA")
    core._int(value["bytes"], 1, MAX_FILE_BYTES, "selected file bytes")
    return {**value, "path": str(path)}


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        core._require(key not in value, "duplicate JSON key forbidden")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("nonfinite JSON constant forbidden")


def _parse(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
        core._raw(value)
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("strict bounded finite UTF8 JSON required") from error


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(selection, *, parse=True):
    path = _path(selection["path"])
    _components(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        core._require(stat.S_ISREG(before.st_mode) and before.st_size == selection["bytes"],
                      "selected regular file size differs")
        data = stream.read(selection["bytes"] + 1)
        after = os.fstat(stream.fileno())
    _components(path)
    core._require(_identity(before) == _identity(after) == _identity(path.lstat())
                  and len(data) == selection["bytes"], "selected file changed while reading")
    core._require(hashlib.sha256(data).hexdigest() == selection["sha256"], "selected file SHA differs")
    return _parse(data) if parse else None


def _seal(value):
    value["content_sha256"] = core._digest(value)
    return value


def _pins(values):
    return core._bindings(values)


def _pre_reference_saved(saved, expected):
    """Replay saved integrity with unavailable placeholders, never review labels."""
    core._pins({"saved_rankings": saved}, {"saved_rankings": expected["saved_rankings"]})
    core._require(type(saved) is dict and type(saved.get("rows")) is list,
                  "selected saved ranking role required before reference access")
    references = _seal({"schema": "alignment-scoring-reference-bindings/v1", "file_binding": None,
                       "rows": [{"id": row["id"], "input_sha256": row["input_sha256"], "reference_sha256": None,
                                 "admission_receipt_sha256": None, "fidelity_evaluation": 0, "status": "unavailable",
                                 "reason": "pre-reference integrity check only"} for row in saved["rows"]]})
    policy = _seal({"schema": "alignment-score-policy/v1", "reference_policy": "admitted_references_only/v1",
                    "metric_policy": "not_implemented/v1"})
    values = {"saved_rankings": saved, "frozen_bank": saved["rank_declaration"]["frozen_bank"],
              "references": references, "score_policy": policy}
    declaration = _seal({"schema": core.SCORE_SCHEMA, **values})
    core.validate_score_declaration(declaration, expected_bindings=_pins(values))


def _role_files(value, prefix=""):
    result = {}
    if type(value) is dict:
        if "schema" in value and "content_sha256" in value and value.get("file_binding") is not None:
            result[prefix] = value
        for name, item in value.items():
            result.update(_role_files(item, prefix + "." + name if prefix else name))
    elif type(value) is list:
        for index, item in enumerate(value):
            result.update(_role_files(item, prefix + "." + str(index)))
    return result


def _check_role_files(declaration, selections, read):
    roles = _role_files(declaration)
    core._closed(selections, roles, "explicit detached role file selections")
    for name, role in roles.items():
        selection = selections[name]
        core._require(_selection(role["file_binding"]) == selection, "role file differs from explicit selection")
        expected = {key: item for key, item in role.items() if key not in {"file_binding", "content_sha256"}}
        core._require(core._raw(read(selection)) == core._raw(expected), "detached role file content differs")


def _check_validation(value, stage):
    core._seal_check(value, "worker stage validation")
    core._require(value["schema"] == core.VALIDATION_SCHEMA and value["stage"] == stage,
                  "worker validation stage differs")
    core._require(all(value.get(name) is False for name in core.FALSE), "worker validation claims authority/execution")
    core._require(value["verification_status"] == value["admission_status"] == "pending", "worker admission remains pending")
    authorization = {"fit": "fit_authorized", "rank": "ranking_authorized", "score": "scoring_authorized"}[stage]
    core._require(value[authorization] is False, "worker declaration cannot authorize execution/admission")
    core._zero_masks(value["masks"])
    for name in ("model_calls", "encoder_calls", "prover_calls", "optimizer_updates"):
        core._int(value[name], 0, 0, "worker " + name)


def _check_arithmetic(result, declaration, validation, query, bank):
    from . import alignment_raw_ranking as raw

    saved, diagnostic = result["saved_rankings"], result["diagnostic_receipt"]
    _pre_reference_saved(saved, {"saved_rankings": _pins({"saved_rankings": saved})["saved_rankings"]})
    core._require(core._raw(saved["rank_declaration"]) == core._raw(declaration) and saved["file_binding"] is None,
                  "raw saved generation differs from selected declaration")
    core._seal_check(diagnostic, "raw helper diagnostic")
    qlane, blane = declaration["lane_validation"], declaration["frozen_bank"]["lane_validation"]
    core._require(declaration["ranking_policy"]["mode"] == "raw_source_to_source" and declaration["checkpoint_binding"] is None
                  and qlane["stage"] in raw.RAW_STAGES and blane["stage"] in raw.RAW_STAGES
                  and qlane["lane_id"] != "leanstral" and blane["lane_id"] != "leanstral", "raw-only worker evidence required")
    for key in ("id", "input_sha256"):
        core._require({row[key] for row in query["rows"]}.isdisjoint({row[key] for row in bank["rows"]}),
                      "raw worker query/TRAIN identities overlap")
    eligible, available = blane["available_count"], qlane["available_count"]
    ranked = available if eligible else 0
    count = available * eligible
    expected = {"schema": raw.SCHEMA, "status": "completed_raw_source_ranking_diagnostic",
        "execution_scope": "pure_stdlib_cosine_arithmetic_not_production_or_fidelity_scoring",
        "declaration_sha256": core._digest(declaration), "stage_validation_sha256": core._digest(validation),
        "query_bundle_sha256": core._digest(query), "bank_bundle_sha256": core._digest(bank),
        "query_lane_validation_sha256": core._digest(qlane), "bank_lane_validation_sha256": core._digest(blane),
        "saved_rankings_sha256": core._digest(saved), "profile_sha256": qlane["profile_sha256"],
        "lane_id": qlane["lane_id"], "stage": qlane["stage"], "dimension": qlane["dimension"],
        "query_count": qlane["row_count"], "available_query_count": available,
        "unavailable_query_count": qlane["unavailable_count"], "zero_ablation_query_count": qlane["zero_ablation_count"],
        "bank_row_count": blane["row_count"], "eligible_candidate_count": eligible,
        "unavailable_candidate_count": blane["unavailable_count"], "zero_ablation_candidate_count": blane["zero_ablation_count"],
        "ranked_query_count": ranked, "unavailable_ranking_count": qlane["row_count"] - ranked,
        "similarity_evaluation_count": count, "returned_hit_count": ranked * min(declaration["ranking_policy"]["top_k"], eligible),
        "ranking_operation_executed": True, "cosine_computation_executed": count > 0,
        "metric": raw.METRIC, "tie_break": core.TIE_BREAK, "vector_values_modified": False,
        "exact_id_disjointness_verified": True, "exact_full_input_disjointness_verified": True,
        "bank_split_declarations_checked": True, "verification_status": "pending", "admission_status": "pending",
        "masks": dict.fromkeys(lane.MASKS, 0), "optimizer_updates": 0, "model_calls": 0, "encoder_calls": 0,
        "decoder_calls": 0, "prover_calls": 0, "checkpoint_loads": 0, "fidelity_scored_query_count": 0, **raw.FALSE}
    core._require(core._raw(expected) == core._raw({key: value for key, value in diagnostic.items() if key != "content_sha256"}),
                  "raw helper diagnostic generation/count/scope differs")
    core._require(sum(row["status"] == "available" for row in saved["rows"]) == ranked
                  and sum(len(row["hits"]) for row in saved["rows"]) == expected["returned_hit_count"],
                  "saved ranking availability/hit counts differ")


def _worker_execute(request):
    started = time.monotonic()
    observed, cache, order = {}, {}, []

    def read(selection):
        key = selection["path"]
        if key not in cache:
            cache[key] = _read(selection)
            observed[key] = selection
            order.append(key)
        else:
            core._require(observed[key] == selection, "conflicting selections for one file")
        return cache[key]

    stage = request["stage"]
    expected = read(request["expected_bindings_binding"])
    saved = None
    if stage == "score":
        saved = read(request["saved_rankings_binding"])
        _pre_reference_saved(saved, expected)
    declaration = read(request["declaration_binding"])
    references = None
    if stage == "score":
        references = read(request["reference_bundle_binding"])
        core._require(core._raw(saved) == core._raw(declaration["saved_rankings"]),
                      "score declaration differs from durable selected saved rankings")
        core._require(core._raw(references) == core._raw(declaration["references"]),
                      "score reference role differs from separate selected reference bundle")
    validators = {"fit": core.validate_fit_declaration, "rank": core.validate_rank_declaration,
                  "score": core.validate_score_declaration}
    validation = validators[stage](declaration, expected_bindings=expected)
    _check_validation(validation, stage)
    _check_role_files(declaration, request["role_file_selections"], read)
    arithmetic = None
    if stage == "rank":
        from .alignment_raw_ranking import rank_raw_source_bundles

        selected = {name: read(value) for name, value in request["lane_bundle_selections"].items()}
        result = rank_raw_source_bundles(declaration, selected["query_bundle"], selected["bank_bundle"],
            expected_bindings=expected, expected_query_lane=selected["expected_query_lane"],
            expected_bank_lane=selected["expected_bank_lane"])
        core._closed(result, {"saved_rankings", "diagnostic_receipt"}, "raw ranking helper result")
        _check_arithmetic(result, declaration, validation, selected["query_bundle"], selected["bank_bundle"])
        saved, arithmetic = result["saved_rankings"], result["diagnostic_receipt"]
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"validation": validation, "saved_rankings": saved if stage == "rank" else None,
            "raw_ranking_diagnostic": arithmetic, "selected_bindings": list(observed.values()), "read_order": order,
            "worker_usage": {"cpu_seconds": usage.ru_utime + usage.ru_stime,
                             "wall_seconds": time.monotonic() - started, "peak_rss_kib": usage.ru_maxrss},
            "pre_reference_saved_integrity_checked": stage == "score"}


class _RejectOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "scipy", "transformers", "spacy", "sentence_transformers",
                                     "tensorflow", "jax", "lean", "z3", "cvc5"}:
            raise ImportError("optional numerical/prover stacks forbidden in diagnostic worker")
        return None


def _worker_main():
    sys.meta_path.insert(0, _RejectOptional())
    try:
        request = _parse(sys.stdin.buffer.read(65537))
        core._require(len(core._raw(request)) <= 65536, "bounded worker request required")
        seconds = request["worker_timeout_seconds"]
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RESPONSE_BYTES, MAX_RESPONSE_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        output = {"ok": True, "result": _worker_execute(request)}
    except (ValueError, KeyError, TypeError, OSError, ImportError, RuntimeError, MemoryError, OverflowError, RecursionError) as error:
        category = "invalid_input" if isinstance(error, ValueError | KeyError | TypeError) else "worker_unavailable"
        output = {"ok": False, "category": category}
    data = core._raw(output)
    core._require(len(data) <= MAX_RESPONSE_BYTES, "bounded worker response required")
    sys.stdout.buffer.write(data)


def _selections(request):
    values = [request["declaration_binding"], request["expected_bindings_binding"]]
    values += list((request["lane_bundle_selections"] or {}).values())
    values += list(request["role_file_selections"].values())
    values += [value for value in (request["saved_rankings_binding"], request["reference_bundle_binding"]) if value is not None]
    unique = {}
    for value in values:
        core._require(value["path"] not in unique or unique[value["path"]] == value, "conflicting selected file pins")
        unique[value["path"]] = value
    core._require(sum(value["bytes"] for value in unique.values()) <= MAX_AGGREGATE_BYTES,
                  "aggregate selected files exceed 64MiB")
    return list(unique.values())


def _sources(stage):
    root = Path(__file__).resolve().parents[4]
    names = list(_SOURCE_FILES)
    if stage == "rank":
        names.append("ipfs_datasets_py/logic/formalization/autoencoder/alignment_raw_ranking.py")
    values = []
    for name in names:
        path = root / name
        _components(path)
        info = path.lstat()
        core._require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_FILE_BYTES, "bounded regular source owner required")
        data = path.read_bytes()
        core._require(len(data) == info.st_size and _identity(info) == _identity(path.lstat()),
                      "source owner changed while pinning")
        values.append({"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return root, values


def _child(request, root):
    encoded_request = core._raw(request)
    core._require(len(encoded_request) <= 65536, "bounded worker request required")
    bootstrap = """
import sys,types
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root))
for name,relative in [('ipfs_datasets_py','ipfs_datasets_py'),('ipfs_datasets_py.logic','ipfs_datasets_py/logic'),
('ipfs_datasets_py.logic.formalization','ipfs_datasets_py/logic/formalization'),
('ipfs_datasets_py.logic.formalization.autoencoder','ipfs_datasets_py/logic/formalization/autoencoder')]:
    module=types.ModuleType(name);module.__path__=[str(root/relative)];module.__package__=name;sys.modules[name]=module
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_stage_workflow import _worker_main
_worker_main()
"""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="alignment-stage-worker-") as temporary, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", bootstrap, str(root)], cwd=temporary,
                                   env=environment, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.communicate(encoded_request, timeout=request["worker_timeout_seconds"])
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise ValueError("diagnostic worker deadline exceeded") from error
        core._require(process.returncode == 0, "diagnostic worker failed or exceeded resource limits")
        core._require(stdout.tell() <= MAX_RESPONSE_BYTES and stderr.tell() <= MAX_RESPONSE_BYTES,
                      "diagnostic worker output bound exceeded")
        stdout.seek(0)
        response = _parse(stdout.read(MAX_RESPONSE_BYTES + 1))
    core._require(type(response) is dict and response.get("ok") is True, "diagnostic worker rejected selected inputs")
    core._closed(response, {"ok", "result"}, "trusted worker response")
    return response["result"], time.monotonic() - started


def _write(directory, name, value):
    data = core._raw(value) + b"\n"
    core._require(len(data) <= MAX_RESPONSE_BYTES, "published JSON exceeds byte bound")
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    binding = {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    _read(binding, parse=False)
    core._require(stat.S_IMODE(path.stat().st_mode) == 0o600, "published file permissions differ")
    return binding


def run_alignment_stage(stage, declaration_binding, expected_bindings_binding, output_directory, *,
                        lane_bundle_selections=None, saved_rankings_binding=None, reference_bundle_binding=None,
                        role_file_selections=None, worker_timeout_seconds=30):
    """Check selected files and publish diagnostic evidence in a fresh directory.

    Rank alone performs source-vector cosine arithmetic. Score first validates
    a durable saved generation, then opens reference declarations. Fit and score
    remain blocked. Process isolation is trusted and resource bounded, not an
    OS sandbox, independent provenance verifier or semantic review process.
    """
    core._require(type(stage) is str and stage in {"fit", "rank", "score"}, "known diagnostic stage required")
    core._int(worker_timeout_seconds, 1, 60, "worker timeout seconds")
    directory = _path(str(output_directory))
    _components(directory, missing=True)
    core._require(not directory.exists(), "fresh output directory required")
    core._require(directory.parent.is_dir(), "existing output parent directory required")
    if stage == "rank":
        core._closed(lane_bundle_selections, LANE_SELECTIONS, "independent query/TRAIN lane selections")
        lane_bundle_selections = {name: _selection(value) for name, value in lane_bundle_selections.items()}
        core._require(saved_rankings_binding is None and reference_bundle_binding is None, "ranking cannot select references")
    else:
        core._require(lane_bundle_selections is None, "lane bundles are selected only for raw ranking")
        if stage == "score":
            saved_rankings_binding, reference_bundle_binding = _selection(saved_rankings_binding), _selection(reference_bundle_binding)
        else:
            core._require(saved_rankings_binding is None and reference_bundle_binding is None, "fit cannot select scoring files")
    role_file_selections = {} if role_file_selections is None else role_file_selections
    core._require(type(role_file_selections) is dict and len(role_file_selections) <= 32, "bounded explicit role-file selections required")
    for name in role_file_selections:
        core._text(name, "role selection name", maximum=1024)
    request = {"stage": stage, "declaration_binding": _selection(declaration_binding),
               "expected_bindings_binding": _selection(expected_bindings_binding),
               "lane_bundle_selections": lane_bundle_selections, "saved_rankings_binding": saved_rankings_binding,
               "reference_bundle_binding": reference_bundle_binding,
               "role_file_selections": {name: _selection(value) for name, value in role_file_selections.items()},
               "worker_timeout_seconds": worker_timeout_seconds}
    selected = _selections(request)
    for value in selected:
        _components(_path(value["path"]))
    root, sources = _sources(stage)
    result, wall = _child(request, root)
    core._closed(result, {"validation", "saved_rankings", "raw_ranking_diagnostic", "selected_bindings", "read_order",
                          "worker_usage", "pre_reference_saved_integrity_checked"}, "worker result")
    _check_validation(result["validation"], stage)
    core._require(result["pre_reference_saved_integrity_checked"] is (stage == "score"), "worker reference gate differs")
    core._closed(result["worker_usage"], {"cpu_seconds", "wall_seconds", "peak_rss_kib"}, "observed worker usage")
    for name in ("cpu_seconds", "wall_seconds"):
        value = result["worker_usage"][name]
        core._require(type(value) is float and math.isfinite(value) and 0 <= value <= worker_timeout_seconds + 1,
                      "bounded finite observed worker time required")
    core._int(result["worker_usage"]["peak_rss_kib"], 1, MEMORY_BYTES // 1024, "observed worker peak RSS")
    if stage == "rank":
        from .alignment_raw_ranking import FALSE as RAW_FALSE

        core._require(type(result["saved_rankings"]) is dict and type(result["raw_ranking_diagnostic"]) is dict,
                      "raw ranking worker evidence required")
        core._seal_check(result["saved_rankings"], "worker saved rankings")
        core._seal_check(result["raw_ranking_diagnostic"], "worker arithmetic diagnostic")
        core._require(result["raw_ranking_diagnostic"]["saved_rankings_sha256"] == core._digest(result["saved_rankings"]),
                      "worker saved ranking output binding differs")
        diagnostic, saved = result["raw_ranking_diagnostic"], result["saved_rankings"]
        core._require(all(diagnostic.get(name) is False for name in RAW_FALSE), "worker ranking diagnostic claims authority")
        core._require(diagnostic["verification_status"] == diagnostic["admission_status"] == "pending"
                      and diagnostic["ranking_operation_executed"] is True, "worker raw diagnostic scope differs")
        core._zero_masks(diagnostic["masks"])
        for name in ("model_calls", "encoder_calls", "decoder_calls", "prover_calls", "optimizer_updates",
                     "checkpoint_loads", "fidelity_scored_query_count"):
            core._int(diagnostic[name], 0, 0, "worker raw " + name)
        _pre_reference_saved(saved, {"saved_rankings": _pins({"saved_rankings": saved})["saved_rankings"]})
        core._require(diagnostic["declaration_sha256"] == result["validation"]["declaration_sha256"] == core._digest(saved["rank_declaration"])
                      and diagnostic["stage_validation_sha256"] == core._digest(result["validation"]),
                      "worker raw/declaration validation generation differs")
    else:
        core._require(result["saved_rankings"] is None and result["raw_ranking_diagnostic"] is None,
                      "blocked fit/score cannot emit rankings or arithmetic evidence")
    core._require(sorted(result["selected_bindings"], key=lambda value: value["path"]) == sorted(selected, key=lambda value: value["path"]),
                  "worker did not consume exactly the explicitly selected files")
    for value in [*selected, *sources]:
        _read(value, parse=False)
    _components(directory, missing=True)
    core._require(not directory.exists(), "output path appeared before publication")
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    artifacts = {"validation": _write(directory, "validation.json", result["validation"])}
    if stage == "rank":
        artifacts["saved_rankings"] = _write(directory, "saved_rankings.json", result["saved_rankings"])
        artifacts["raw_ranking_diagnostic"] = _write(directory, "raw_ranking_diagnostic.json", result["raw_ranking_diagnostic"])
    report = _seal({"schema": SCHEMA, "stage": stage,
                    "status": "completed_diagnostic_raw_ranking" if stage == "rank" else result["validation"]["status"],
                    "declaration_validation_status": result["validation"]["status"],
                    "request_sha256": core._digest(request), "selected_file_bindings": selected,
                    "source_bindings": sources, "dependency_binding_scope": "explicit_owners_not_complete_stdlib_dependency_closure",
                    "artifacts": artifacts, "worker_usage": result["worker_usage"], "parent_worker_wall_seconds": wall,
                    "resource_limits": {"cpu_soft_seconds": worker_timeout_seconds, "cpu_hard_seconds": worker_timeout_seconds + 1,
                                        "address_space_bytes": MEMORY_BYTES, "output_file_bytes": MAX_RESPONSE_BYTES},
                    "read_order": result["read_order"], "pre_reference_saved_integrity_checked": result["pre_reference_saved_integrity_checked"],
                    "selected_file_bindings_verified": True, "child_isolation": "trusted_resource_bounded_subprocess",
                    "os_sandbox": False, "reviewer_identity_authenticated": False, "split_provenance_authenticated": False,
                    "source_fidelity_established": False, "semantic_label_admission": False, "proof_authority": False,
                    "qualified": False, "accepted": False, "training_executed": False, "scoring_executed": False,
                    "ranking_operation_executed": stage == "rank", "model_calls": 0, "encoder_calls": 0, "prover_calls": 0,
                    "optimizer_updates": 0, "fidelity_scores_created": 0, "masks": dict.fromkeys(lane.MASKS, 0)})
    report_binding = _write(directory, "report.json", report)
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    for value in [*selected, *sources, *artifacts.values(), report_binding]:
        _read(value, parse=False)
    _components(directory)
    core._require(stat.S_IMODE(directory.stat().st_mode) == 0o700, "published directory permissions differ")
    return json.loads(core._raw(report))


__all__ = ["run_alignment_stage"]

"""Retained byte custody, with genuine current source/review regeneration.

The module-scoped packets contain deliberately synthetic historical compiler
claims and artifact bytes. They test readback under independently supplied unit
pins, never authentication of compilation, a fresh proof or legal meaning.
No compiler, process identity probe, model, cache or database is used.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_v2 as preparer
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_native_v2 as native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_packet_v2 as owner
from ipfs_datasets_py.logic.backends import process


_SPEC = importlib.util.spec_from_file_location(
    "_genuine_preservation_packet_source_fixtures",
    Path(__file__).with_name("test_legal_corpus_definition_use_preservation_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

TOOLCHAIN = _FIXTURE.TOOLCHAIN
LAKE = "/synthetic-not-installed/legal-packet/bin/lake"
LEAN = "/synthetic-not-installed/legal-packet/bin/lean"
BINARIES = {LAKE: hashlib.sha256(b"synthetic lake identity").hexdigest(),
            LEAN: hashlib.sha256(b"synthetic lean identity").hexdigest()}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def seal(value):
    return contracts.seal_record({key: item for key, item in value.items()
                                  if key not in {"record_cid", "cid_scope"}})


def historical_lifecycle():
    # Historical identity deliberately differs from the process reading it.
    parent = os.getpid() + 100_000
    leader = parent + 1
    return {
        "schema": "native-owned-tool-lifecycle@1",
        "parent": {"pid": parent, "birth_ticks": 17},
        "leader": {"pid": leader, "birth_ticks": 18, "parent_pid": parent,
                   "process_group_id": leader, "session_id": leader},
        "observed_descendants": [], "leader_reaped": True,
        "descendant_tracking_complete": True, "group_scan_complete": True,
        "remaining_group_members": [], "remaining_tracked_descendants": [],
        "readers": {"started": 2, "joined": 2},
        "stdin_writer": {"started": 0, "joined": 0},
        "workspace": {"device": 1, "inode": 2, "removed": True},
        "cleanup_confirmed": True, "observation_errors": [],
        "ownership_is_sampled": True, "kernel_containment_attested": False,
    }


@dataclass(frozen=True)
class SyntheticPacket:
    data: dict
    preparation: object
    files: tuple


def synthetic_packet(family, *, data=None):
    data = _FIXTURE.original_data(family) if data is None else data
    preparation = _FIXTURE.prepare(data)
    manifest = preparation.to_dict()
    source_files = {name: body.encode() for name, body in preparation.files}
    artifact_files = {
        ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean":
        b"explicit synthetic artifact, no compilation or proof authentication"
        for module in manifest["expected_modules"]
    }
    stdout = "\n".join("'" + name + "' does not depend on any axioms"
                       for name in manifest["theorems"]) + "\n"
    logs = {"stdout.txt": stdout.encode(), "stderr.txt": b"", "runner-error.txt": b""}
    life = historical_lifecycle()
    command = [LAKE, "--offline", "--no-cache", "build", "legal"]
    version = TOOLCHAIN.rsplit(":v", 1)[1]
    observations = {
        "command": command, "expected_command": command,
        "runtime": "native", "pid": life["leader"]["pid"], "returncode": 0,
        "expected_modules": manifest["expected_modules"],
        "compiled_modules": manifest["expected_modules"],
        "manifest_coverage_passed": True, "executed_project_readback_passed": True,
        "executed_project_sha256": {name: sha(raw) for name, raw in source_files.items()},
        "producer_pins": native._pins(native._owners(), manifest),
        "binary_sha256": dict(BINARIES), "binaries_unchanged": True,
        "version_probes": {name: {"command": [path, "--version"], "returncode": 0,
                                  "stdout": "synthetic " + name + " version " + version + "\n", "stderr": ""}
                           for name, path in (("lake", LAKE), ("lean", LEAN))},
        "toolchain_probed": True, "installed_toolchain_verified": True,
        "post_run_validation_passed": True, "post_run_validation_error": None,
        "binary_recheck_error": None, "original_preparation_unchanged": True,
        "artifact_sha256": {name: sha(raw) for name, raw in artifact_files.items()},
        "artifact_bytes": {name: len(raw) for name, raw in artifact_files.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                           for name in artifact_files},
        "theorems": manifest["theorems"],
        "conditional_theorems": manifest["conditional_theorems"],
        "preservation_theorems": manifest["preservation_theorems"],
        "theorem_axiom_dependencies": {name: [] for name in manifest["theorems"]},
        "axiom_observations_passed": True, "axiom_observation_errors": [],
        "concrete_kernel_status": "checked_exact_four_fragment_instances",
        "conditional_kernel_status": "checked_under_explicit_hypotheses",
        "stdout": stdout, "stderr": "", "error": "",
        "log_sha256": {name: sha(raw) for name, raw in logs.items()},
        "log_bytes": {name: len(raw) for name, raw in logs.items()},
        "receipt_text_truncated": False, "elapsed_seconds": 0.01,
        "termination_reason": "", "timed_out": False, "cancelled": False,
        "unavailable": False, "output_truncated": False,
        "workspace_limit_exceeded": False, "resource_exhausted": False,
        "workspace_cleaned": True, "process_tree_terminated": False,
        "native_lifecycle": life, "cleanup_confirmed": True,
        "observed_process_scope_passed": True, "ownership_is_sampled": True,
        "kernel_containment_attested": False, "native_runtime_verified": True,
    }
    receipt = seal({
        "schema": native.BUILD_SCHEMA, "profile": native.PROFILE,
        "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": preparer.preparation_sha256(preparation),
        "preparation_manifest_sha256": sha(preparation.manifest_json.encode()),
        "corpus_preparation_full_canonical_sha256": _FIXTURE.corpus_sha256(data["corpus_preparation"]),
        "assessment_file_sha256": data["expected_assessment_file_sha256"],
        "toolchain": TOOLCHAIN, "original_preparation_state": native._original_preparation_state(manifest),
        "preservation_fragments": manifest["preservation_fragments"],
        "reference_contract": manifest["reference_contract"],
        "native_observations": observations,
        "build_passed": True, "status": "corpus_native_preservation_checks_passed",
        "authority": dict(native.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        # This is the producer's claimed scope, retained as synthetic input.
        "proof_scope": "Twelve exact concrete checks for the donor, consumer, alias and joint native AST values, closedness and denotation against each unchanged formula_0; three original conditional corpus theorems retain every donor, consumer and alias hypothesis. No assumed alias fact, universal emitter, JSON byte-parser, legal-source fidelity or model-convergence theorem is established.",
        **(native.FALSE_FLAGS | {
            "backend_executed": True, "lean_compilation_verified": True,
            "proof_checked": True, "kernel_proofs_checked": True,
            "corpus_native_AST_preservation_proved": True, "conditional_proofs_verified": True,
        }),
    })
    packet = {"project/" + name: raw for name, raw in source_files.items()}
    packet["project/corpus-manifest.json"] = preparation.manifest_json.encode()
    packet.update({"executed-inputs/" + name: raw for name, raw in source_files.items()})
    packet.update({"compiled/" + name.removeprefix(".lake/build/lib/lean/"): raw
                   for name, raw in artifact_files.items()})
    packet.update(logs)
    packet["build-receipt.json"] = canonical(receipt)
    assert len(packet) == 49
    return SyntheticPacket(data, preparation, tuple(sorted(packet.items())))


@pytest.fixture(scope="module")
def packets():
    return {family: synthetic_packet(family) for family in ("fol", "tdfol")}


@pytest.fixture
def base(packets):
    return packets["fol"]


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("retained packet consumer reached execution, identity probe or backend")
    monkeypatch.setattr(native, "build_definition_use_preservation_native_v2", forbidden)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native, "_binary_recheck", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(process, "_linux_owned_identity", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    class DenyBackendImport:
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == name or fullname.startswith(name + ".")
                   for name in ("duckdb", "torch", "transformers")):
                forbidden()
    deny = DenyBackendImport()
    sys.meta_path.insert(0, deny)
    yield
    sys.meta_path.remove(deny)


def arguments(base, files=None):
    files = base.files if files is None else files
    return {
        "expected_preparation_sha256": preparer.preparation_sha256(base.preparation),
        "expected_corpus_preparation_sha256": _FIXTURE.corpus_sha256(base.data["corpus_preparation"]),
        "expected_assessment_file_sha256": base.data["expected_assessment_file_sha256"],
        "expected_receipt_file_sha256": sha(dict(files)["build-receipt.json"]),
        "expected_bundle_sha256": owner.packet_sha256(files),
        "review_inputs": base.data["review_inputs"], "toolchain": TOOLCHAIN,
        "expected_binary_sha256": dict(BINARIES),
    }


def read(base, files=None, *, repin=False, **overrides):
    files = base.files if files is None else files
    return owner.validate_definition_use_preservation_packet_v2(
        files, base.data["corpus_preparation"], base.data["assessment_raw"],
        **(arguments(base, files if repin else None) | overrides),
    )


def changed_receipt(base, edit):
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    edit(receipt)
    files["build-receipt.json"] = canonical(seal(receipt))
    return tuple(sorted(files.items()))


def changed_logs(base, *, stdout=None, stderr=None):
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    observed = receipt["native_observations"]
    for name, field, text in (("stdout.txt", "stdout", stdout), ("stderr.txt", "stderr", stderr)):
        if text is not None:
            raw = text.encode()
            files[name] = raw
            observed["log_bytes"][name] = len(raw)
            observed["log_sha256"][name] = sha(raw)
            observed[field] = raw[:32768].decode("utf-8", errors="replace").replace("\x00", "\\u0000")
    observed["receipt_text_truncated"] = any(len(files[name]) > 32768
                                              for name in ("stdout.txt", "stderr.txt", "runner-error.txt"))
    files["build-receipt.json"] = canonical(seal(receipt))
    return tuple(sorted(files.items()))


def test_public_import_is_stdlib_only():
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','multiformats','pyarrow','duckdb','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_packet_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('RetainedDefinitionUsePreservationPacket','packet_sha256','validate_definition_use_preservation_packet_v2'):
    assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, owner.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_bundle_digest_commits_all_sorted_paths_lengths_and_raw_hashes(base):
    rows = [{"path": path, "bytes": len(raw), "sha256": sha(raw)} for path, raw in base.files]
    assert owner.packet_sha256(base.files) == sha(canonical(rows))
    assert owner.packet_sha256(base.files) != sha(dict(base.files)["build-receipt.json"])
    receipt = json.loads(dict(base.files)["build-receipt.json"])
    assert owner.packet_sha256(base.files) != receipt["reference_contract"]["reference_key_sha256"]


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_complete_packet_replays_current_inputs_but_does_not_execute_or_grant_authority(
    packets, family, no_execution,
):
    base = packets[family]
    source_before = deepcopy(base.data["review_inputs"])
    result = read(base)
    assert type(result) is owner.RetainedDefinitionUsePreservationPacket
    assert result.files == base.files
    observation = result.to_dict()
    assert observation["schema"] == "legal-corpus-v2-definition-use-preservation-packet-observation/v1"
    assert observation["readback_verified"] is observation["current_preparation_replayed"] is True
    assert observation["historical_kernel_observations_retained"] is True
    assert observation["packet_bundle_sha256"] == owner.packet_sha256(base.files)
    assert observation["receipt_file_sha256"] == sha(dict(base.files)["build-receipt.json"])
    assert observation["historical_native_receipt"] == json.loads(dict(base.files)["build-receipt.json"])
    assert observation["historical_native_receipt"]["native_observations"]["native_lifecycle"]["parent"]["pid"] != os.getpid()
    assert observation["packet_inventory"] == [{"path": path, "bytes": len(raw), "sha256": sha(raw)}
                                               for path, raw in base.files]
    historical_pins = observation["historical_native_receipt"]["native_observations"]["producer_pins"]
    assert observation["historical_producer_pins"] == historical_pins
    assert observation["current_producer_pins"] == historical_pins | {
        str(Path(owner.__file__).resolve()): sha(Path(owner.__file__).read_bytes())}
    assert observation["reference_contract"] == base.preparation.to_dict()["reference_contract"]
    assert observation["source_custody"]["original_corpus_source_review_dependencies_replayed"] is True
    assert observation["source_custody"]["source_review_eligibility_unchanged"] is True
    assert observation["source_custody"]["filesystem_acquisition_performed"] is False
    assert observation["source_custody"]["historical_process_liveness_inspected"] is False
    assert base.data["review_inputs"] == source_before
    for name in ("proof_checked", "kernel_proofs_checked", "backend_executed", "lean_compilation_verified",
                 "source_semantics_verified", "source_fidelity_proved", "model_executed", "model_convergence_proved",
                 "legal_proof_cache_compatible", "proof_cache_admission_verified", "admitted",
                 "installed_compiler_revalidated"):
        assert observation[name] is False, name
    assert all(value is False for value in observation["authority"].values())
    assert type(observation["training_mask"]) is type(observation["evaluation_gold_mask"]) is int
    assert observation["training_mask"] == observation["evaluation_gold_mask"] == 0
    reference = native.receipt_reference(dict(base.files)["build-receipt.json"],
                                         sha(dict(base.files)["build-receipt.json"])).to_dict()
    assert reference["review_status"] == "unreviewed" and reference["content_cid"] == ""
    assert reference["metadata"]["retained_artifacts_validated"] is False
    assert reference["metadata"]["proof_validation_performed"] is False
    observation["historical_native_receipt"]["build_passed"] = False
    assert result.to_dict()["historical_native_receipt"]["build_passed"] is True


@pytest.mark.parametrize("field,value", [
    ("expected_preparation_sha256", "A" * 64),
    ("expected_corpus_preparation_sha256", "0" * 64),
    ("expected_assessment_file_sha256", "0" * 64),
    ("expected_receipt_file_sha256", "0" * 64),
    ("expected_bundle_sha256", "0" * 64),
    ("expected_bundle_sha256", "A" * 64),
    ("expected_receipt_file_sha256", True),
])
def test_independent_pin_refusal_precedes_lazy_owners(base, monkeypatch, field, value):
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("lazy owners reached before pin refusal"))
    with pytest.raises(ValueError):
        read(base, **{field: value})


@pytest.mark.parametrize("damage", ["list", "unsorted", "duplicate", "mutable", "traversal", "backslash", "deep_path", "absolute"])
def test_closed_immutable_byte_transport_refuses_before_lazy_owners(base, monkeypatch, damage):
    files = base.files
    if damage == "list": files = list(files)
    elif damage == "unsorted": files = tuple(reversed(files))
    elif damage == "duplicate": files = tuple(sorted((*files[:-1], files[0])))
    else:
        rows = list(files)
        path, raw = rows[0]
        if damage == "mutable": raw = bytearray(raw)
        elif damage == "traversal": path = "../packet"
        elif damage == "backslash": path = "project\\packet"
        elif damage == "deep_path": path = "project/a/b/c/d.lean"
        else: path = "/absolute-packet"
        rows[0] = (path, raw)
        files = tuple(sorted(rows))
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("lazy owners reached before transport refusal"))
    with pytest.raises(ValueError):
        read(base, files)


@pytest.mark.parametrize("group", ["project/", "executed-inputs/", "compiled/", "root"])
def test_every_packet_member_is_required_before_lazy_owners(base, monkeypatch, group):
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("lazy owners reached for incomplete packet"))
    selected = [path for path, _ in base.files if ("/" not in path if group == "root" else path.startswith(group))]
    assert len(selected) == {"project/": 17, "executed-inputs/": 16, "compiled/": 12, "root": 4}[group]
    for missing in selected:
        with pytest.raises(ValueError):
            read(base, tuple(row for row in base.files if row[0] != missing))


@pytest.mark.parametrize("damage", ["receipt_duplicate", "receipt_nonfinite", "manifest_duplicate"])
def test_json_refusal_after_exact_raw_pins_does_not_accept_ambiguous_records(base, no_execution, damage):
    files = dict(base.files)
    if damage == "receipt_duplicate": files["build-receipt.json"] = b'{"schema":"one","schema":"two"}'
    elif damage == "receipt_nonfinite": files["build-receipt.json"] = b'{"elapsed":NaN}'
    else: files["project/corpus-manifest.json"] = b'{"schema":"one","schema":"two"}'
    with pytest.raises(ValueError):
        read(base, tuple(sorted(files.items())), repin=True)


@pytest.mark.parametrize("group", ["project/", "executed-inputs/", "compiled/", "stdout.txt", "stderr.txt"])
def test_repinned_changed_retained_content_does_not_replace_claimed_observations(base, no_execution, group):
    files = dict(base.files)
    name = next(path for path in files if path.startswith(group))
    files[name] += b"changed exact retained content"
    with pytest.raises(ValueError):
        read(base, tuple(sorted(files.items())), repin=True)


@pytest.mark.parametrize("field,value", [
    ("build_passed", False), ("proof_checked", False),
    ("proof_cache_admission_verified", True), ("model_convergence_proved", True),
    ("training_mask", 1), ("source_semantics_verified", True),
])
def test_self_resealed_claims_preserve_failure_and_no_authority_boundary(base, no_execution, field, value):
    files = changed_receipt(base, lambda receipt: receipt.__setitem__(field, value))
    with pytest.raises(ValueError):
        read(base, files, repin=True)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "foreign", "nonempty", "wrong_path", "inline", "stderr"])
def test_all_fifteen_full_stdout_axiom_observations_are_required(base, no_execution, damage):
    receipt = json.loads(dict(base.files)["build-receipt.json"])
    names = receipt["native_observations"]["theorems"]
    lines = dict(base.files)["stdout.txt"].decode().splitlines()
    target = names[-1]
    if damage == "missing": lines = lines[:-1]
    elif damage == "duplicate": lines.append(lines[-1])
    elif damage == "foreign": lines.append("'Foreign.theorem' does not depend on any axioms")
    elif damage == "nonempty": lines[-1] = "'" + target + "' depends on axioms: [sorryAx]"
    elif damage == "wrong_path": lines[-1] = "info: Foreign.lean:1:0: " + lines[-1]
    elif damage == "inline": lines[-1] = "prefix " + lines[-1]
    else:
        files = changed_logs(base, stdout="\n".join(lines[:-1]) + "\n", stderr=lines[-1] + "\n")
    if damage != "stderr": files = changed_logs(base, stdout="\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        read(base, files, repin=True)


@pytest.mark.parametrize("damage", ["parent_birth", "leader_parent", "session", "cleanup", "remaining", "readers"])
def test_historical_lifecycle_requires_internal_identity_and_cleanup(base, no_execution, damage):
    def edit(receipt):
        life = receipt["native_observations"]["native_lifecycle"]
        if damage == "parent_birth": life["parent"]["birth_ticks"] = True
        elif damage == "leader_parent": life["leader"]["parent_pid"] += 1
        elif damage == "session": life["leader"]["session_id"] += 1
        elif damage == "cleanup": life["cleanup_confirmed"] = False
        elif damage == "remaining": life["remaining_group_members"] = [life["leader"]]
        else: life["readers"]["joined"] = 1
    with pytest.raises(ValueError):
        read(base, changed_receipt(base, edit), repin=True)


@pytest.mark.parametrize("damage", ["reference_key", "role_target", "binary", "producer", "source_state"])
def test_resealed_reference_context_cannot_replace_complete_current_replay(base, no_execution, damage):
    def edit(receipt):
        if damage == "reference_key":
            reference = receipt["reference_contract"]
            reference["key_material"]["assessment_file_sha256"] = "0" * 64
            reference["reference_key_sha256"] = sha(canonical(reference["key_material"]))
            receipt["reference_contract"] = seal(reference)
        elif damage == "role_target": receipt["preservation_fragments"][0]["target_declaration"] = "Foreign.formula_0"
        elif damage == "binary": receipt["native_observations"]["binary_sha256"][LAKE] = "0" * 64
        elif damage == "producer":
            pins = receipt["native_observations"]["producer_pins"]
            pins[next(iter(pins))] = "0" * 64
        else: receipt["original_preparation_state"]["original_corpus_preparation_state"]["review_evidence_status"] = "accepted"
    with pytest.raises(ValueError):
        read(base, changed_receipt(base, edit), repin=True)


@pytest.mark.parametrize("damage", ["source", "review", "dependency"])
def test_current_original_inputs_are_publicly_regenerated(base, no_execution, damage):
    review_inputs = deepcopy(base.data["review_inputs"])
    if damage == "source":
        review_inputs["component_raw"] += b"changed source component"
    elif damage == "review": review_inputs["policy"]["mode"] = "changed-untrusted-mode"
    else:
        identity = next(iter(review_inputs["observed_artifact_sha256s"]))
        review_inputs["observed_artifact_sha256s"][identity] = None
    with pytest.raises(ValueError):
        read(base, review_inputs=review_inputs)


def test_complete_logs_are_checked_beyond_receipt_preview(base, no_execution):
    stdout = dict(base.files)["stdout.txt"].decode()
    padding = "bounded harmless retained log\n" * 1800
    bad = changed_logs(base, stdout=stdout + padding + "'Foreign.theorem' depends on axioms: [sorryAx]\n")
    assert len(dict(bad)["stdout.txt"]) > 32768
    with pytest.raises(ValueError):
        read(base, bad, repin=True)


def test_nonempty_artifacts_are_required_even_with_resealed_hashes(base, no_execution):
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    observations = receipt["native_observations"]
    artifact = next(iter(observations["artifact_files"]))
    files[observations["artifact_files"][artifact]] = b""
    observations["artifact_bytes"][artifact] = 0
    observations["artifact_sha256"][artifact] = sha(b"")
    files["build-receipt.json"] = canonical(seal(receipt))
    with pytest.raises(ValueError):
        read(base, tuple(sorted(files.items())), repin=True)


@pytest.mark.parametrize("kind,maximum", [("receipt", 1024**2), ("log", 12 * 1024**2), ("artifact", 8 * 1024**2)])
def test_input_byte_bounds_refuse_before_lazy_owners_even_under_matching_caller_pins(
    base, monkeypatch, kind, maximum,
):
    files = dict(base.files)
    name = {"receipt": "build-receipt.json", "log": "stdout.txt"}.get(kind)
    if name is None: name = next(path for path in files if path.startswith("compiled/"))
    files[name] = b"x" * (maximum + 1)
    files = tuple(sorted(files.items()))
    inventory_pin = sha(canonical([{"path": path, "bytes": len(raw), "sha256": sha(raw)}
                                   for path, raw in files]))
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("lazy owners reached for oversized packet"))
    with pytest.raises(ValueError):
        read(base, files, expected_bundle_sha256=inventory_pin,
             expected_receipt_file_sha256=sha(dict(files)["build-receipt.json"]))


def test_binary_identity_input_is_a_closed_absolute_sibling_pair_before_lazy_owners(base, monkeypatch):
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("lazy owners reached for malformed binary pair"))
    maps = [{}, dict(BINARIES) | {"/other/compiler": "1" * 64},
            {"relative/lake": "1" * 64, LEAN: "2" * 64},
            {LAKE: "1" * 64, "/different/bin/lean": "2" * 64},
            {LAKE: True, LEAN: "2" * 64}]
    for pins in maps:
        with pytest.raises(ValueError):
            read(base, expected_binary_sha256=pins)


@pytest.mark.parametrize("change_after_replay", [1, 2])
def test_inputs_changed_after_either_genuine_public_replay_are_refused(
    base, no_execution, monkeypatch, change_after_replay,
):
    review_inputs = deepcopy(base.data["review_inputs"])
    original = native.validate_definition_use_preservation_native_v2
    calls = []
    def replay_then_change(*args, **kwargs):
        checked = original(*args, **kwargs)
        calls.append(checked)
        if len(calls) == change_after_replay:
            key = next(iter(review_inputs["observed_artifact_sha256s"]))
            review_inputs["observed_artifact_sha256s"][key] = None
        return checked
    monkeypatch.setattr(native, "validate_definition_use_preservation_native_v2", replay_then_change)
    with pytest.raises(ValueError):
        read(base, review_inputs=review_inputs)
    assert len(calls) == change_after_replay


def test_valid_rejected_review_is_retained_as_rejected_after_packet_readback(base, no_execution):
    signed = deepcopy(base.data["signed"])
    signed["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    data = _FIXTURE._FIXTURE.refresh_assessment(signed)
    data["corpus_preparation"] = _FIXTURE.corpus.prepare_definition_use_corpus_v2(**_FIXTURE._FIXTURE.arguments(data))
    rejected = synthetic_packet("fol", data=data)
    result = read(rejected).to_dict()
    historical = result["historical_native_receipt"]["original_preparation_state"]["original_corpus_preparation_state"]
    assert historical["review_evidence_status"] == data["assessment"]["evidence_assessment_status"]
    assert historical["review_blockers"] == data["assessment"]["blockers"]
    assert historical["review_blockers"]
    assert result["admitted"] is result["proof_cache_admission_verified"] is False


def test_wrong_complete_preservation_pin_requires_and_fails_genuine_current_regeneration(base, no_execution):
    with pytest.raises(ValueError):
        read(base, expected_preparation_sha256="0" * 64)


# Direct complete parent-norm packets are a separate receipt-consistency profile.
# Every runtime/artifact value below is deliberately synthetic authored data.
# Original outer-operation acceptance is unavailable to this bytes-only API.
from dataclasses import replace as _parent_norm_packet_replace
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as _parent_norm_packet_preparer
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_native_v2 as _parent_norm_packet_native


@pytest.fixture(scope="module")
def parent_norm_packet_base(tmp_path_factory):
    import tempfile
    lake_fixture = _FIXTURE._FIXTURE
    helpers = lake_fixture.parent_norm_helpers.__wrapped__()
    data = lake_fixture._parent_norm_materialize(
        helpers, Path(tempfile.mkdtemp(prefix="parent-norm-packet-originals-",
                                       dir=tmp_path_factory.getbasetemp())))
    preparation = _parent_norm_packet_preparer.prepare_parent_norm_corpus_v1(**data)
    manifest = preparation.to_dict()
    sources = {name: body.encode("utf-8") for name, body in preparation.files}
    artifacts = {".lake/build/lib/lean/" + module.replace(".", "/") + ".olean":
                 b"explicitly synthetic parent-norm artifact; never compiled"
                 for module in manifest["expected_modules"]}
    theorem = manifest["conditional_theorems"][0]
    stdout = "'" + theorem + "' does not depend on any axioms\n"
    logs = {"stdout.txt": stdout.encode(), "stderr.txt": b"", "runner-error.txt": b""}
    life = historical_lifecycle()
    command = [LAKE, "--offline", "--no-cache", "build", "legal"]
    version = TOOLCHAIN.rsplit(":v", 1)[1]
    flags = dict(_parent_norm_packet_preparer.PARENT_NORM_FALSE_FLAGS)
    flags.update(_parent_norm_packet_native.FALSE_FLAGS)
    flags.update(backend_executed=True, lean_compilation_verified=True,
                 proof_checked=True, kernel_proofs_checked=True, conditional_proofs_verified=True)
    receipt = seal({
        "schema": _parent_norm_packet_native.PARENT_NORM_BUILD_SCHEMA,
        "profile": _parent_norm_packet_native.PARENT_NORM_NATIVE_PROFILE,
        "preparation_cid": manifest["record_cid"],
        "preparation_full_canonical_sha256": _parent_norm_packet_preparer.parent_norm_preparation_sha256(preparation),
        "preparation_manifest_sha256": sha(preparation.manifest_json.encode()),
        "correspondence_sha256": data["expected_correspondence_sha256"],
        "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
        "parent_source_binding_sha256": manifest["parent_source_binding_sha256"],
        "original_norm_sha256": sha(canonical(manifest["original_norm"])),
        "review_intake_binding_sha256": sha(canonical(manifest["review_intake_binding"])),
        "source_context_sha256": sha(canonical(manifest["original_parent_context"])),
        "retained_unresolved_sha256": sha(canonical(manifest["correspondence"]["retained_unresolved"])),
        "review_blockers": manifest["review_blockers"],
        "original_preparation_build_eligible": manifest["build_eligible"],
        "original_preparation_execution_handoff": manifest["execution_handoff"],
        "preservation_kind": "definitional_alias_identity_only",
        "original_preparation_unchanged": True,
        "toolchain": TOOLCHAIN, "command": command, "expected_command": command,
        "runtime": "native", "pid": life["leader"]["pid"], "returncode": 0,
        "expected_modules": manifest["expected_modules"],
        "compiled_modules": manifest["expected_modules"],
        "manifest_coverage_passed": True, "executed_project_readback_passed": True,
        "executed_project_sha256": {name: sha(raw) for name, raw in sources.items()},
        "producer_pins": _parent_norm_packet_native._parent_norm_native_pins(
            _parent_norm_packet_native._owners(), manifest),
        "binary_sha256": dict(BINARIES), "binaries_unchanged": True,
        "version_probes": {name: {"command": [path, "--version"], "returncode": 0,
                                   "stdout": "synthetic " + name + " version " + version + "\n", "stderr": ""}
                           for name, path in (("lake", LAKE), ("lean", LEAN))},
        "post_run_validation_passed": True, "post_run_validation_error": None,
        "binary_recheck_error": None,
        "artifact_sha256": {name: sha(raw) for name, raw in artifacts.items()},
        "artifact_bytes": {name: len(raw) for name, raw in artifacts.items()},
        "artifact_files": {name: "compiled/" + name.removeprefix(".lake/build/lib/lean/")
                           for name in artifacts},
        "conditional_theorems": manifest["conditional_theorems"],
        "conditional_kernel_status": "checked_under_explicit_hypotheses",
        "theorem_axiom_dependencies": {theorem: []},
        "axiom_observations_passed": True, "axiom_observation_errors": [],
        "theorem_assumptions": [text for text in manifest["theorem_assumptions"] if text not in {
            "Modular joint equivalence is a generated definitional obligation; native kernel checking has not run.",
            "This profile prepares files only; native and incremental qualification have not run."}],
        "original_preparation_theorem_assumptions": manifest["theorem_assumptions"],
        "stdout": stdout, "stderr": "", "error": "",
        "log_sha256": {name: sha(raw) for name, raw in logs.items()},
        "log_bytes": {name: len(raw) for name, raw in logs.items()},
        "receipt_text_truncated": False, "elapsed_seconds": 0.01, "termination_reason": "",
        "timed_out": False, "cancelled": False, "unavailable": False,
        "output_truncated": False, "workspace_limit_exceeded": False, "resource_exhausted": False,
        "workspace_cleaned": True, "process_tree_terminated": False,
        "native_lifecycle": life, "cleanup_confirmed": True, "observed_process_scope_passed": True,
        "ownership_is_sampled": True, "kernel_containment_attested": False,
        "build_passed": True, "native_runtime_verified": True,
        "status": "conditional_native_checks_passed", "alias_assumption_proved": False,
        "source_to_model_equivalence_proved": False,
        "authority": dict(_parent_norm_packet_native.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "scope": "Only original_norm_preserved, a definitional alias identity under explicit "
                 "Entity, Agent, Interpretation and time. No norm truth, source meaning, governing edition, "
                 "definition applicability, graph/corpus admission, model equivalence or convergence claim.",
        **flags,
    })
    packet = {"project/" + name: raw for name, raw in sources.items()}
    packet["project/corpus-manifest.json"] = preparation.manifest_json.encode()
    packet.update({"executed-inputs/" + name: raw for name, raw in sources.items()})
    packet.update({"compiled/" + name.removeprefix(".lake/build/lib/lean/"): raw
                   for name, raw in artifacts.items()})
    packet.update(logs)
    packet["build-receipt.json"] = canonical(receipt)
    assert len(packet) == 23 and len(preparation.files) == 7
    return SyntheticPacket(data, preparation, tuple(sorted(packet.items())))


@pytest.fixture
def parent_norm_packet_no_execution(no_execution, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("parent packet reader reached native execution or installed binary inspection")
    monkeypatch.setattr(_parent_norm_packet_native, "build_parent_norm_native_v1", forbidden)
    monkeypatch.setattr(_parent_norm_packet_native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(_parent_norm_packet_native, "_binary_recheck", forbidden)


def _parent_norm_packet_arguments(base, files=None):
    files = base.files if files is None else files
    return {
        "expected_preparation_sha256": _parent_norm_packet_preparer.parent_norm_preparation_sha256(base.preparation),
        "expected_correspondence_sha256": base.data["expected_correspondence_sha256"],
        "correspondence_inputs": base.data["correspondence_inputs"], "toolchain": TOOLCHAIN,
        "expected_receipt_file_sha256": sha(dict(files)["build-receipt.json"]),
        "expected_bundle_sha256": owner.parent_norm_packet_sha256(files),
        "expected_binary_sha256": dict(BINARIES),
    }


def _parent_norm_packet_read(base, files=None, *, repin=False, preparation=None, **overrides):
    files = base.files if files is None else files
    return owner.validate_parent_norm_native_packet_v1(
        files, base.preparation if preparation is None else preparation, base.data["correspondence"],
        **(_parent_norm_packet_arguments(base, files if repin else None) | overrides))


def _parent_norm_packet_edit_receipt(base, edit):
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    edit(receipt)
    files["build-receipt.json"] = canonical(seal(receipt))
    return tuple(sorted(files.items()))


def _parent_norm_packet_edit_log(base, text):
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    raw = text.encode()
    files["stdout.txt"] = raw
    receipt["stdout"] = raw[:owner.MAX_LOG_PREVIEW_BYTES].decode(errors="replace").replace("\x00", "\\u0000")
    receipt["log_sha256"]["stdout.txt"] = sha(raw)
    receipt["log_bytes"]["stdout.txt"] = len(raw)
    receipt["receipt_text_truncated"] = len(raw) > owner.MAX_LOG_PREVIEW_BYTES
    files["build-receipt.json"] = canonical(seal(receipt))
    return tuple(sorted(files.items()))


def test_parent_norm_packet_complete_genuine_replay_is_receipt_consistency_only(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch):
    base = parent_norm_packet_base
    before = deepcopy(base.data)
    genuine = _parent_norm_packet_native.validate_parent_norm_native_v1
    replays = []
    def counted(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        replays.append(checked)
        return checked
    monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", counted)
    result = _parent_norm_packet_read(base)
    value = result.to_dict()
    assert len(replays) == 2 and all(checked == base.preparation for checked in replays)
    assert result.files == base.files and base.data == before
    assert value["schema"] == owner.PARENT_NORM_PACKET_SCHEMA
    assert value["profile"] == owner.PARENT_NORM_PACKET_PROFILE
    assert value["readback_verified"] is value["current_preparation_replayed"] is True
    assert value["packet_bundle_sha256"] == owner.parent_norm_packet_sha256(base.files)
    assert value["historical_native_receipt"] == json.loads(dict(base.files)["build-receipt.json"])
    assert value["historical_producer_pins"] == value["historical_native_receipt"]["producer_pins"]
    assert value["accepted_execution"] is value["accepted_outer_operation"] is False
    assert value["accepted_operation_result_bound"] is False
    assert value["outer_operation_outcome"] == "unprovided" and value["receipt_consistency_only"] is True
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is type(value["evaluation_gold_mask"]) is int
    assert value["training_mask"] == value["evaluation_gold_mask"] == 0
    assert all(value[name] is False for name in owner.FALSE_FLAGS)
    # The old official digest/profile stays exactly49 files, never a23-file alias.
    with pytest.raises(ValueError):
        owner.packet_sha256(base.files)


def test_parent_norm_packet_persisted_true_before_failed_outer_closeout_is_not_acceptance(
        parent_norm_packet_base, parent_norm_packet_no_execution):
    # A later outer failure is information outside the packet. Even a completely
    # consistent persisted true receipt cannot establish that absent final result.
    outside_outer_result = {"completed": False, "qualified": False,
                            "failure": "closing physical source witness changed after persistence"}
    original = dict(parent_norm_packet_base.files)["build-receipt.json"]
    assert json.loads(original)["build_passed"] is True and outside_outer_result["qualified"] is False
    observed = _parent_norm_packet_read(parent_norm_packet_base).to_dict()
    assert observed["historical_native_receipt"]["build_passed"] is True
    assert observed["accepted_execution"] is observed["accepted_outer_operation"] is False
    assert observed["accepted_operation_result_bound"] is False
    assert observed["outer_operation_outcome"] == "unprovided"
    assert observed["receipt_consistency_only"] is True
    assert dict(parent_norm_packet_base.files)["build-receipt.json"] == original


@pytest.mark.parametrize("field", ["expected_preparation_sha256", "expected_correspondence_sha256",
                                   "expected_receipt_file_sha256", "expected_bundle_sha256"])
def test_parent_norm_packet_independent_wrong_pins_refuse(
        parent_norm_packet_base, parent_norm_packet_no_execution, field):
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base, **{field: "0" * 64})


@pytest.mark.parametrize("damage", ["list", "mutable_bytes", "duplicate", "unsorted", "missing", "extra"])
def test_parent_norm_packet_closed_transport_refuses_before_delegates(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, damage):
    base = parent_norm_packet_base
    files = base.files
    if damage == "list":
        files = list(files)
    elif damage == "mutable_bytes":
        files = (files[0][0], bytearray(files[0][1])), *files[1:]
    elif damage == "duplicate":
        files = files[:-1] + (files[0],)
    elif damage == "unsorted":
        files = tuple(reversed(files))
    elif damage == "missing":
        files = files[:-1]
    else:
        files = files + (("project/extra.txt", b"unexpected"),)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid parent packet entered operation dependencies")
    monkeypatch.setattr(owner, "_parent_norm_packet_owners", forbidden)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(base, files)


@pytest.mark.parametrize("damage", ["boolean_mask", "claimed_legal_truth", "claimed_global_toolchain",
                                    "wrong_profile", "wrong_schema", "failed_status", "failed_closing",
                                    "extra_field", "wrong_producer_path"])
def test_parent_norm_packet_resealed_receipt_claims_refuse(
        parent_norm_packet_base, parent_norm_packet_no_execution, damage):
    def edit(receipt):
        if damage == "boolean_mask":
            receipt["training_mask"] = False
        elif damage == "claimed_legal_truth":
            receipt["norm_truth_proved"] = True
        elif damage == "claimed_global_toolchain":
            receipt["installed_toolchain_verified"] = True
        elif damage == "wrong_profile":
            receipt["profile"] = native.PROFILE
        elif damage == "wrong_schema":
            receipt["schema"] = native.BUILD_SCHEMA
        elif damage == "failed_status":
            receipt["status"] = "conditional_native_checks_failed"
        elif damage == "failed_closing":
            receipt["post_run_validation_passed"] = False
            receipt["post_run_validation_error"] = {"type": "ValueError", "message": "closing custody failed"}
            receipt["post_run_custody_error"] = dict(receipt["post_run_validation_error"])
        elif damage == "extra_field":
            receipt["outer_operation_accepted"] = True
        else:
            key = next(iter(receipt["producer_pins"]))
            receipt["producer_pins"]["/different-generation/" + Path(key).name] = receipt["producer_pins"].pop(key)
    files = _parent_norm_packet_edit_receipt(parent_norm_packet_base, edit)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base, files, repin=True)


@pytest.mark.parametrize("damage", ["manifest", "executed_source", "empty_artifact", "wrong_artifact_hash", "input_commitment", "rehashed_norm_preparation"])
def test_parent_norm_packet_rehashed_members_cannot_replace_current_originals(
        parent_norm_packet_base, parent_norm_packet_no_execution, damage):
    base = parent_norm_packet_base
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    offered, overrides = base.preparation, {}
    if damage == "manifest":
        manifest = json.loads(files["project/corpus-manifest.json"])
        manifest["original_norm"]["native_ast_sha256"] = "0" * 64
        files["project/corpus-manifest.json"] = canonical(seal(manifest))
        receipt["preparation_manifest_sha256"] = sha(files["project/corpus-manifest.json"])
    elif damage == "executed_source":
        name = next(name for name in files if name.startswith("executed-inputs/") and name.endswith(".lean"))
        files[name] += b"-- altered executed source\n"
        receipt["executed_project_sha256"][name.removeprefix("executed-inputs/")] = sha(files[name])
    elif damage == "input_commitment":
        receipt["original_input_commitment_sha256"] = "0" * 64
    elif damage == "rehashed_norm_preparation":
        manifest = base.preparation.to_dict()
        originals = dict(base.preparation.files)
        name = next(name for name in originals if "/Norm_" in name and name.endswith(".lean"))
        originals[name] += "\n-- an edited, rehashed norm is not authoritative regeneration\n"
        manifest["file_sha256"][name] = sha(originals[name].encode())
        offered = _parent_norm_packet_replace(base.preparation,
            manifest_json=canonical(seal(manifest)).decode(), files=tuple(sorted(originals.items())))
        overrides["expected_preparation_sha256"] = _parent_norm_packet_preparer.parent_norm_preparation_sha256(offered)
        for original_name, text in offered.files:
            files["project/" + original_name] = files["executed-inputs/" + original_name] = text.encode()
        files["project/corpus-manifest.json"] = offered.manifest_json.encode()
        receipt["preparation_cid"] = offered.to_dict()["record_cid"]
        receipt["preparation_full_canonical_sha256"] = overrides["expected_preparation_sha256"]
        receipt["preparation_manifest_sha256"] = sha(files["project/corpus-manifest.json"])
        receipt["executed_project_sha256"][name] = sha(originals[name].encode())
    else:
        name = next(name for name in files if name.startswith("compiled/"))
        observed = ".lake/build/lib/lean/" + name.removeprefix("compiled/")
        if damage == "empty_artifact":
            files[name] = b""
            receipt["artifact_bytes"][observed] = 0
            receipt["artifact_sha256"][observed] = sha(b"")
        else:
            receipt["artifact_sha256"][observed] = "0" * 64
    files["build-receipt.json"] = canonical(seal(receipt))
    with pytest.raises(ValueError):
        _parent_norm_packet_read(base, tuple(sorted(files.items())), repin=True,
                                 preparation=offered, **overrides)


@pytest.mark.parametrize("damage", ["missing_axiom", "unexpected_axiom", "late_axiom_after_preview", "invalid_utf8"])
def test_parent_norm_packet_full_logs_refuse_resealed_false_observations(
        parent_norm_packet_base, parent_norm_packet_no_execution, damage):
    base = parent_norm_packet_base
    theorem = base.preparation.to_dict()["conditional_theorems"][0]
    if damage == "missing_axiom":
        files = _parent_norm_packet_edit_log(base, "synthetic compilation omitted theorem observation\n")
    elif damage == "unexpected_axiom":
        files = _parent_norm_packet_edit_log(base, "'" + theorem + "' depends on axioms: [Classical.choice]\n")
    elif damage == "late_axiom_after_preview":
        text = dict(base.files)["stdout.txt"].decode() + " " * (owner.MAX_LOG_PREVIEW_BYTES + 1)
        files = _parent_norm_packet_edit_log(base, text + "\n'" + theorem + "' depends on axioms: [sorryAx]\n")
    else:
        values = dict(base.files)
        receipt = json.loads(values["build-receipt.json"])
        values["stdout.txt"] = b"\xff"
        receipt["stdout"] = "\ufffd"
        receipt["log_sha256"]["stdout.txt"] = sha(b"\xff")
        receipt["log_bytes"]["stdout.txt"] = 1
        values["build-receipt.json"] = canonical(seal(receipt))
        files = tuple(sorted(values.items()))
    with pytest.raises(ValueError):
        _parent_norm_packet_read(base, files, repin=True)


@pytest.mark.parametrize("field,value", [("training_mask", 1), ("evaluation_gold_mask", True),
                                       ("authority", {"proof": True})])
def test_parent_norm_packet_authority_never_promotes(
        parent_norm_packet_base, parent_norm_packet_no_execution, field, value):
    files = _parent_norm_packet_edit_receipt(parent_norm_packet_base,
                                           lambda receipt: receipt.__setitem__(field, value))
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base, files, repin=True)


@pytest.mark.parametrize("after", [1, 2])
def test_parent_norm_packet_originals_changed_after_genuine_replay_refuse(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, after):
    base = parent_norm_packet_base
    inputs = deepcopy(base.data["correspondence_inputs"])
    genuine = _parent_norm_packet_native.validate_parent_norm_native_v1
    observed = []
    def returned(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        observed.append(checked)
        if len(observed) == after:
            inputs["expected_mapping_request_sha256"] = "0" * 64
        return checked
    monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", returned)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(base, correspondence_inputs=inputs)
    assert len(observed) == after


@pytest.mark.parametrize("after", [1, 2])
def test_parent_norm_packet_late_delegate_replacement_refuses_before_changed_callback(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, after):
    genuine = _parent_norm_packet_native.validate_parent_norm_native_v1
    observed, unexpected = [], []
    def replacement(*args, **kwargs):
        unexpected.append(True)
        return parent_norm_packet_base.preparation
    def returned(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        observed.append(checked)
        if len(observed) == after:
            monkeypatch.setattr(owner, "_parent_norm_packet_receipt_matches", replacement)
        return checked
    monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", returned)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base)
    assert len(observed) == after and unexpected == []


@pytest.mark.parametrize("after", [1, 2])
def test_parent_norm_packet_local_source_drift_after_genuine_replay_refuses(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, tmp_path, after):
    copied_source = tmp_path / "copied_packet_source.py"
    copied_source.write_bytes(Path(owner.__file__).read_bytes())
    monkeypatch.setattr(owner, "__file__", str(copied_source))
    genuine = _parent_norm_packet_native.validate_parent_norm_native_v1
    observed = []
    def returned(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        observed.append(checked)
        if len(observed) == after:
            copied_source.write_bytes(copied_source.read_bytes() + b"\n# late test-local source drift\n")
        return checked
    monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", returned)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base)
    assert len(observed) == after


def test_parent_norm_packet_late_observation_serialization_mutation_refuses(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch):
    genuine = owner._wire
    changed = []
    def encoded(value, *args, **kwargs):
        result = genuine(value, *args, **kwargs)
        if type(value) is dict and value.get("schema") == owner.PARENT_NORM_PACKET_SCHEMA:
            value["accepted_execution"] = True
            changed.append(True)
        return result
    monkeypatch.setattr(owner, "_wire", encoded)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base)
    assert changed


@pytest.mark.parametrize("damage", ["nonordinary_inputs", "oversized_log", "invalid_binary", "boolean_preparation_pin"])
def test_parent_norm_packet_bounded_preflight_refuses_before_delegates(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, damage):
    base = parent_norm_packet_base
    kwargs = _parent_norm_packet_arguments(base)
    files = base.files
    if damage == "nonordinary_inputs":
        class DictSubclass(dict):
            pass
        kwargs["correspondence_inputs"] = DictSubclass(base.data["correspondence_inputs"])
    elif damage == "oversized_log":
        values = dict(files)
        values["stdout.txt"] = b"x" * (owner.MAX_LOG_BYTES + 1)
        files = tuple(sorted(values.items()))
    elif damage == "invalid_binary":
        kwargs["expected_binary_sha256"] = {LAKE: "0" * 64, "/other/bin/lean": "1" * 64}
    else:
        kwargs["expected_preparation_sha256"] = True
    def forbidden(*args, **kwargs):
        pytest.fail("invalid parent packet preflight entered operation dependencies")
    monkeypatch.setattr(owner, "_parent_norm_packet_owners", forbidden)
    with pytest.raises(ValueError):
        owner.validate_parent_norm_native_packet_v1(
            files, base.preparation, base.data["correspondence"], **kwargs)


def test_parent_norm_packet_profile_is_not_official_preservation_or_legacy_storage(
        parent_norm_packet_base, base, parent_norm_packet_no_execution, monkeypatch):
    # Both source-qualified historical profiles keep distinct closed populations.
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base, base.files)
    with pytest.raises(ValueError):
        read(base, parent_norm_packet_base.files)
    assert owner.MAX_FILES == 49 and owner.MAX_MODULES == 12 and owner.MAX_THEOREMS == 15



def test_parent_norm_packet_wrong_independent_binary_hash_refuses_before_replay(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch):
    binaries = dict(BINARIES)
    binaries[LEAN] = "0" * 64
    def forbidden(*args, **kwargs):
        pytest.fail("wrong independent historical binary commitment reached replay")
    monkeypatch.setattr(owner, "_parent_norm_packet_owners", forbidden)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base, expected_binary_sha256=binaries)


def test_parent_norm_packet_late_native_validator_replacement_never_invokes_changed_call(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch):
    genuine = _parent_norm_packet_native.validate_parent_norm_native_v1
    observed, unexpected = [], []
    def replacement(*args, **kwargs):
        unexpected.append(True)
        return parent_norm_packet_base.preparation
    def returned(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        observed.append(checked)
        monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", replacement)
        return checked
    monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", returned)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base)
    assert len(observed) == 1 and unexpected == []



@pytest.mark.parametrize("after", [1, 2])
def test_parent_norm_packet_primary_callback_failure_survives_secondary_terminal_custody_failure(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, after):
    base = parent_norm_packet_base
    inputs = deepcopy(base.data["correspondence_inputs"])
    genuine = owner._parent_norm_packet_current_preparation
    calls = []
    class PrimaryCallbackFailure(ValueError):
        pass
    primary = PrimaryCallbackFailure("explicit primary parent-packet callback failure")
    def failed_after_genuine_return(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        calls.append(checked)
        if len(calls) == after:
            inputs["expected_mapping_request_sha256"] = "0" * 64
            raise primary
        return checked
    monkeypatch.setattr(owner, "_parent_norm_packet_current_preparation", failed_after_genuine_return)
    with pytest.raises(PrimaryCallbackFailure, match="explicit primary") as caught:
        _parent_norm_packet_read(base, correspondence_inputs=inputs)
    assert caught.value is primary and len(calls) == after
    notes = getattr(primary, "__notes__", [])
    assert notes and any(any(word in note.lower() for word in ("closing", "custody", "fence"))
                         for note in notes)



@pytest.mark.parametrize("delegate", ["seal", "constructor"])
def test_parent_norm_packet_genuine_final_delegate_cannot_substitute_accepted_execution(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, delegate):
    changed = []
    if delegate == "seal":
        genuine = contracts.seal_record
        def substituted(value, *args, **kwargs):
            result = genuine(value, *args, **kwargs)
            if type(value) is dict and value.get("schema") == owner.PARENT_NORM_PACKET_SCHEMA:
                edited = {key: item for key, item in deepcopy(result).items()
                          if key not in {"record_cid", "cid_scope"}}
                edited["accepted_execution"] = True
                changed.append(True)
                return genuine(edited)
            return result
        monkeypatch.setattr(contracts, "seal_record", substituted)
    else:
        genuine = owner.RetainedDefinitionUsePreservationPacket.__init__
        def substituted(result, *args, **kwargs):
            genuine(result, *args, **kwargs)
            edited = json.loads(result.observation_json)
            if edited.get("schema") == owner.PARENT_NORM_PACKET_SCHEMA:
                edited["accepted_execution"] = True
                object.__setattr__(result, "observation_json", canonical(seal(edited)).decode())
                changed.append(True)
        monkeypatch.setattr(owner.RetainedDefinitionUsePreservationPacket, "__init__", substituted)
    with pytest.raises(ValueError):
        _parent_norm_packet_read(parent_norm_packet_base)
    assert changed



@pytest.mark.parametrize("after", [1, 2])
def test_parent_norm_packet_original_physical_file_drift_after_genuine_replay_refuses(
        parent_norm_packet_base, parent_norm_packet_no_execution, monkeypatch, after):
    base = parent_norm_packet_base
    parent_file = _FIXTURE._FIXTURE._parent_norm_parent_path(base.data)
    original_bytes = parent_file.read_bytes()
    genuine = _parent_norm_packet_native.validate_parent_norm_native_v1
    observed = []
    def returned(*args, **kwargs):
        checked = genuine(*args, **kwargs)
        observed.append(checked)
        if len(observed) == after:
            parent_file.write_bytes(original_bytes + b"\nlate physical parent witness drift\n")
        return checked
    monkeypatch.setattr(_parent_norm_packet_native, "validate_parent_norm_native_v1", returned)
    try:
        with pytest.raises(ValueError):
            _parent_norm_packet_read(base)
        assert len(observed) == after
    finally:
        parent_file.write_bytes(original_bytes)
        assert parent_file.read_bytes() == original_bytes


# Compatibility preparation is an identity binding. These tests never build Lean.
_COMPATIBILITY_ROUTES = ("parent", "direct", "conditional", "native", "preservation")
_PARENT_COMPATIBILITY_PREMISES = (
    "The complete supplied authored relational AST and native body are unchanged, with O/P/F as separate uninterpreted parameters.",
    "The preservation theorem is only a definitional alias identity, not a proof of the norm or its source meaning.",
    "No definition is applied, no membership or governing applicability is inferred, and all source/context/edition issues remain open.",
)
_DIRECT_COMPATIBILITY_SCOPE = (
    "Only original_norm_preserved, a definitional alias identity under explicit "
    "Entity, Agent, Interpretation and time. No norm truth, source meaning, governing edition, "
    "definition applicability, graph/corpus admission, model equivalence or convergence claim."
)
_DIRECT_BUILD_PASSED_PREMISE = (
    "A persisted build_passed receipt does not establish accepted execution or an accepted outer operation."
)
_NATIVE_IDENTITY_PREMISE = (
    "The retained 23-case/69-phase native qualification is an identity reference. This request does not rerun it."
)
_CONDITIONAL_COMPATIBILITY_PREMISES = (
    "The complete supplied norm and unary donor use the same arbitrary Entity carrier, Interpretation and fixed formal Nat time.",
    "hDefinition remains an explicit unverified premise; body mode additionally assumes exact matching hMembership.",
    "Only conditional definition instances and unchanged original-norm alias identity are prepared; norm truth, actual membership and applicability are not inferred.",
    "Every parent norm/definition population, unresolved context, alternative and nomination remains retained in the complete original parent-bound report in the project input file.",
    "No definition substitution, modal rewrite, statutory meaning, civil legal-as-of decision, graph admission or learning target is supplied.",
)
_PRESERVATION_COMPATIBILITY_PREMISES = (
    "One supplied Interpretation, Entity carrier and Nat evaluation time are shared by all fragments.",
    "Predicate-to-donor-body equivalence assumes the exact donor definition and explicit alias; neither is proved as a fact.",
    "Joint assembly assumes the exact donor definition, consumer definition and alias.",
    "Modular joint equivalence is a generated definitional obligation; native kernel checking has not run.",
    "No conclusion about the consumer head follows from the donor body without its separate complete Boolean body obligations.",
    "All four certificates use the original LegalCorpusV2.Interpretation and target the original module formula_0 directly.",
    "Concrete AST value reconstruction, closedness and denotation do not establish statutory source meaning or the alias premise.",
    "Python JSON parsing, reification and cryptographic commitments remain outside the kernel theorem.",
    "All fifteen generated theorem obligations require separate native kernel execution.",
)
_PARENT_COMPATIBILITY_IMPORTS = (
    {"role": "prelude", "imports": []},
    {"role": "norm", "imports": ["prelude"]},
    {"role": "preservation", "imports": ["norm"]},
    {"role": "root", "imports": ["preservation"]},
)
_CONDITIONAL_COMPATIBILITY_IMPORTS = (
    {"role": "prelude", "imports": []},
    {"role": "norm", "imports": ["prelude"]},
    {"role": "definition", "imports": ["prelude"]},
    {"role": "occurrence", "imports": ["norm", "definition"]},
    {"role": "preservation", "imports": ["norm", "occurrence"]},
    {"role": "root", "imports": ["preservation"]},
)
_PRESERVATION_ROLE_NAMES = ("donor", "consumer", "alias", "joint")
_BASE_UNRESOLVED = (
    "governing_definition", "source_meaning", "source_edition", "definition_applicability",
    "legal_review", "compiler_not_rerun",
)


def compatibility_candidate(route, *, candidate_id=None, ast_kind="native_ast", mode=None, **overrides):
    """Exact selected-AST request row. Overrides may replace a closure with None."""
    record = owner.lean_compatibility_route(route)
    closure = owner.lean_compatibility_closure(route, mode=mode)
    candidate_id = route + "_selected" if candidate_id is None else candidate_id
    candidate = {
        "candidate_id": candidate_id,
        "profile": record["profile"],
        "ast_sha256": sha(candidate_id.encode()),
        "ast_kind": ast_kind,
        "imports": closure["imports"],
        "premises": closure["premises"],
        "axioms": closure["axioms"],
        "artifact_closure": closure["artifact_closure"],
    }
    candidate.update(overrides)
    return candidate


def compatibility_request(candidates):
    raw = canonical({"schema": owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA, "candidates": list(candidates)})
    return raw, sha(raw)


def _compatibility_report(candidates):
    raw, digest = compatibility_request(candidates)
    return owner.prepare_lean_compatibility_request_v1(raw, expected_request_sha256=digest), raw, digest


def _assert_admission_blocked(row):
    assert row["unresolved_prerequisites"]
    assert row["lean_admitted"] is False
    assert row["legal_admission"] is False
    assert row["admitted"] is False
    assert row["formalized"] is False
    assert row["semantic_preservation_claimed"] is False
    assert row["compiler_invoked"] is False
    assert row["selected_ast_replaced"] is False


def test_compatibility_public_names_extend_the_packet_owner():
    for name in (
        "LEAN_COMPATIBILITY_REQUEST_SCHEMA",
        "lean_compatibility_routes",
        "lean_compatibility_route",
        "lean_compatibility_closure",
        "prepare_lean_compatibility_request_v1",
        "lean_compatibility_request_sha256",
        "validate_lean_compatibility_request_v1",
    ):
        assert hasattr(owner, name) and name in owner.__all__
    assert owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA == "legal-lean-compatibility-request/v1"


def test_compatibility_request_binds_selected_ast_to_exact_route_closure(no_execution, monkeypatch):
    monkeypatch.setattr(os, "system", lambda *args, **kwargs: pytest.fail("os.system reached"))
    candidates = [
        compatibility_candidate(route, ast_kind="typed_expression" if route == "preservation" else "native_ast")
        for route in _COMPATIBILITY_ROUTES
    ]
    report, raw, digest = _compatibility_report(candidates)
    assert set(report) == {
        "compatibility_matrix", "request_import_premise_axiom_closure", "artifact_closure",
        "unresolved_questions", "reuse_owners",
    }
    rows = report["compatibility_matrix"]
    assert [row["route"] for row in rows] == list(_COMPATIBILITY_ROUTES)
    assert [row["candidate_id"] for row in rows] == [row["route"] + "_selected" for row in rows]
    by_route = {row["route"]: row for row in rows}
    profiles = {
        "parent": "replayed-parent-literal-complete-authored-norm-project/v1",
        "direct": "replayed-retained-parent-literal-complete-authored-norm-native-byte-packet/v1",
        "conditional": "replayed-parent-bound-norm-definition-conditional-project/v1",
        "native": "replayed-parent-literal-complete-authored-norm-native-build/v1",
        "preservation": "replayed-retained-v2-corpus-preservation-byte-packet/v1",
    }
    for route, row in by_route.items():
        assert row["disposition"] == "bound" and row["reason"] == "exact_route_closure"
        assert row["closure_bound"] is True
        assert row["profile"] == profiles[route]
        assert row["ast_sha256"] == sha((route + "_selected").encode())
        assert row["ast_kind"] == ("typed_expression" if route == "preservation" else "native_ast")
        _assert_admission_blocked(row)
        assert list(_BASE_UNRESOLVED) == [item for item in row["unresolved_prerequisites"]
                                           if item in _BASE_UNRESOLVED]

    parent = by_route["parent"]
    assert parent["imports"] == [dict(item) for item in _PARENT_COMPATIBILITY_IMPORTS]
    assert parent["premises"] == list(_PARENT_COMPATIBILITY_PREMISES)
    assert parent["axioms"]["theorem_count"] == 1
    assert parent["axioms"]["theorem_roles"] == ["original_norm_preserved"]
    assert parent["axioms"]["introduced"] is False
    assert parent["axioms"]["expected_dependencies"] == []
    assert parent["axioms"]["observed_dependencies"] is None
    assert parent["axioms"]["retained_empty_observation_required"] is False
    assert parent["axioms"]["historical_observations_rerun"] is False
    artifact = parent["artifact_closure"]
    assert artifact["kind"] == "lake_project"
    assert artifact["project_files"] == 7 and artifact["modules"] == 4 and artifact["theorems"] == 1
    assert artifact["packet_files"] is None and artifact["packet_index_supported"] is False
    assert artifact["compiled_artifacts"] == 0 and artifact["expected_olean_modules"] == 4
    assert artifact["retained_cases"] == 68 and artifact["retained_phases"] == 204
    assert artifact["build_eligible"] is False and artifact["compiler_rerun"] is False
    assert artifact["closure_status"] == "preparation_only"
    assert parent["retained_evidence_ids"] == ["parent-complete-norm-preparation-68-204"]

    direct = by_route["direct"]
    assert direct["imports"] == parent["imports"]
    assert direct["premises"] == [
        *_PARENT_COMPATIBILITY_PREMISES, _DIRECT_COMPATIBILITY_SCOPE, _DIRECT_BUILD_PASSED_PREMISE,
    ]
    assert direct["axioms"]["retained_empty_observation_required"] is True
    assert direct["axioms"]["theorem_count"] == 1
    artifact = direct["artifact_closure"]
    assert artifact["kind"] == "retained_packet"
    assert (artifact["project_files"], artifact["executed_inputs"], artifact["compiled_artifacts"],
            artifact["root_files"]) == (8, 7, 4, 4)
    assert sum((8, 7, 4, 4)) == artifact["packet_files"] == 23
    assert artifact["modules"] == 4 and artifact["theorems"] == 1
    assert artifact["packet_index_supported"] is True and artifact["receipt_consistency_only"] is True
    assert artifact["retained_cases"] == 23 and artifact["retained_phases"] == 69
    assert artifact["closure_status"] == "retained_packet_identity"
    assert direct["retained_evidence_ids"] == [
        "parent-complete-norm-native-23-69", "direct-parent-norm-packet-23",
    ]

    conditional = by_route["conditional"]
    assert conditional["imports"] == [dict(item) for item in _CONDITIONAL_COMPATIBILITY_IMPORTS]
    assert conditional["premises"] == list(_CONDITIONAL_COMPATIBILITY_PREMISES)
    assert conditional["axioms"]["theorem_count"] == 2
    assert conditional["axioms"]["required_suffix"] == "original_norm_preserved"
    assert conditional["axioms"]["retained_empty_observation_required"] is True
    artifact = conditional["artifact_closure"]
    assert artifact["kind"] == "parent_bound_project"
    assert artifact["project_files"] == 9 and artifact["modules"] == 6 and artifact["source_inputs"] == 9
    assert artifact["mode"] == "instance_only" and artifact["theorems"] == 2
    assert artifact["retained_files"] == 29 and artifact["compiled_modules"] == 6
    assert artifact["packet_files"] is None and artifact["packet_index_supported"] is False
    assert artifact["retained_pure_cases"] == 32 and artifact["retained_pure_phases"] == 96
    assert artifact["retained_native_cases"] == 2 and artifact["retained_native_phases"] == 6
    assert artifact["closure_status"] == "retained_29_file_identity_without_packet_index_reader"
    assert conditional["retained_evidence_ids"] == [
        "parent-bound-pure-32-96", "parent-bound-native-2-6", "parent-bound-retained-files-29",
    ]
    assert conditional["unresolved_prerequisites"][-1] == "packet_index_reader_absent"

    native_row = by_route["native"]
    assert native_row["imports"] == parent["imports"]
    assert native_row["premises"] == [*_PARENT_COMPATIBILITY_PREMISES, _NATIVE_IDENTITY_PREMISE]
    assert native_row["axioms"]["retained_empty_observation_required"] is True
    artifact = native_row["artifact_closure"]
    assert artifact["kind"] == "native_build_contract"
    assert artifact["project_files"] == 7 and artifact["modules"] == 4 and artifact["theorems"] == 1
    assert artifact["retained_capture_files"] == 23 and artifact["compiled_artifacts"] == 4
    assert artifact["executed_inputs"] == 7 and artifact["packet_files"] is None
    assert artifact["packet_index_supported"] is False
    assert artifact["retained_cases"] == 23 and artifact["retained_phases"] == 69
    assert artifact["closure_status"] == "historical_identity_not_rerun"
    assert native_row["retained_evidence_ids"] == ["parent-complete-norm-native-23-69"]

    preservation = by_route["preservation"]
    roles = list(_PRESERVATION_ROLE_NAMES)
    assert preservation["imports"] == [
        {"role": "prelude", "imports": []},
        {"role": "donor", "imports": ["prelude"]},
        {"role": "consumer", "imports": ["prelude"]},
        {"role": "alias", "imports": ["donor", "consumer"]},
        {"role": "joint", "imports": ["donor", "consumer", "alias"]},
        {"role": "corpus_root", "imports": ["joint"]},
        {"role": "semantics", "imports": ["prelude"]},
        *({"role": "preservation_" + role, "imports": [role, "semantics"]} for role in roles),
        {"role": "preservation_root", "imports": ["corpus_root", *("preservation_" + role for role in roles)]},
    ]
    assert len(preservation["imports"]) == 12
    assert preservation["premises"] == list(_PRESERVATION_COMPATIBILITY_PREMISES)
    theorem_roles = ["consumer_predicate_iff_donor_body", "joint_of_components", "joint_matches_original"]
    theorem_roles.extend(role + "." + suffix for role in roles
                         for suffix in ("native_value_exact", "native_ast_closed", "denotation_matches_native"))
    assert preservation["axioms"]["theorem_count"] == 15
    assert preservation["axioms"]["theorem_roles"] == theorem_roles
    assert preservation["axioms"]["required_suffix"] == "role_qualified"
    assert preservation["axioms"]["retained_empty_observation_required"] is True
    artifact = preservation["artifact_closure"]
    assert artifact["kind"] == "retained_packet"
    assert artifact["project_sources"] == 16 and artifact["project_files"] == 17
    assert artifact["executed_inputs"] == 16 and artifact["compiled_artifacts"] == 12
    assert artifact["root_files"] == 4 and artifact["packet_files"] == 49
    assert sum((17, 16, 12, 4)) == 49
    assert artifact["modules"] == 12 and artifact["theorems"] == 15
    assert artifact["packet_index_supported"] is True
    assert artifact["closure_status"] == "retained_packet_identity"
    assert preservation["retained_evidence_ids"] == ["official-v2-preservation-packet-49"]

    catalog = {item["route"]: item for item in owner.lean_compatibility_routes()}
    assert catalog["parent"]["namespace"] == catalog["direct"]["namespace"] == catalog["native"]["namespace"] == "LegalCorpusParentNorm"
    assert catalog["conditional"]["namespace"] == "LegalCorpusBoundNormDefinition"
    assert catalog["preservation"]["namespace"] == "LegalCorpusV2Preservation"
    assert catalog["preservation"]["project_profile"] != catalog["preservation"]["profile"]
    evidence = {item["evidence_id"]: item for item in report["artifact_closure"]["retained_evidence"]}
    assert evidence["parent-complete-norm-preparation-68-204"]["cases"] == 68
    assert evidence["parent-complete-norm-preparation-68-204"]["phases"] == 204
    assert evidence["parent-complete-norm-preparation-68-204"]["owner_symbol"] == "prepare_parent_norm_corpus_v1"
    assert evidence["parent-complete-norm-native-23-69"]["cases"] == 23
    assert evidence["parent-complete-norm-native-23-69"]["phases"] == 69
    assert evidence["parent-complete-norm-native-23-69"]["owner_symbol"] == "validate_parent_norm_native_v1"
    assert evidence["direct-parent-norm-packet-23"]["retained_files"] == 23
    assert evidence["parent-bound-pure-32-96"]["cases"] == 32
    assert evidence["parent-bound-pure-32-96"]["phases"] == 96
    assert evidence["parent-bound-native-2-6"]["cases"] == 2
    assert evidence["parent-bound-native-2-6"]["phases"] == 6
    assert evidence["parent-bound-native-2-6"]["owner_symbol"] == "build_parent_bound_norm_definition_native_v1"
    assert evidence["parent-bound-retained-files-29"]["retained_files"] == 29
    assert evidence["parent-bound-retained-files-29"]["owner_symbol"] == "prepare_parent_bound_norm_definition_corpus_v1"
    assert evidence["official-v2-preservation-packet-49"]["retained_files"] == 49
    assert all(item["rerun"] is False for item in evidence.values())
    symbols = [item["symbol"] for item in report["reuse_owners"]]
    assert symbols == [
        "prepare_parent_norm_corpus_v1",
        "validate_parent_norm_native_packet_v1",
        "prepare_parent_norm_preservation_index_v1",
        "prepare_parent_bound_norm_definition_corpus_v1",
        "validate_parent_bound_norm_definition_native_v1",
        "validate_parent_norm_native_v1",
        "prepare_definition_use_preservation_v2",
        "validate_definition_use_preservation_packet_v2",
        "prepare_definition_use_preservation_index_v2",
    ]
    assert "prepare_lean_compatibility_request_v1" not in symbols
    questions = {item["question_id"]: item["status"] for item in report["unresolved_questions"]}
    assert questions == {
        "governing_definition": "unanswered",
        "source_meaning": "unanswered",
        "content_derived_module_names": "unanswered",
        "lean_admission": "blocked",
        "legal_admission": "blocked",
        "conditional_packet_index": "unanswered",
        "training_gold": "unanswered",
    }
    assert report["request_import_premise_axiom_closure"]["schema"] == "legal-lean-request-import-premise-axiom-closure/v1"
    assert report["request_import_premise_axiom_closure"]["compiler_rerun"] is False
    assert report["request_import_premise_axiom_closure"]["axioms_introduced"] is False
    assert report["artifact_closure"]["schema"] == "legal-lean-artifact-closure/v1"
    assert report["artifact_closure"]["compiler_rerun"] is False
    assert owner.lean_compatibility_request_sha256(report) == sha(canonical(report))
    checked = owner.validate_lean_compatibility_request_v1(
        report, raw, expected_request_sha256=digest,
        expected_report_sha256=owner.lean_compatibility_request_sha256(report))
    assert canonical(checked) == canonical(report)


def test_compatibility_body_mode_binds_three_theorems_without_admission(no_execution):
    report, _raw, _digest = _compatibility_report([
        compatibility_candidate("conditional", candidate_id="conditional_body", mode="body_with_membership"),
    ])
    row = report["compatibility_matrix"][0]
    assert row["disposition"] == "bound" and row["closure_bound"] is True
    assert row["axioms"]["theorem_count"] == 3
    assert row["artifact_closure"]["mode"] == "body_with_membership"
    assert row["artifact_closure"]["theorems"] == 3
    assert row["artifact_closure"]["retained_files"] == 29
    assert row["artifact_closure"]["packet_index_supported"] is False
    assert row["artifact_closure"]["packet_files"] is None
    _assert_admission_blocked(row)
    assert "packet_index_reader_absent" in row["unresolved_prerequisites"]


def test_foreign_profile_precedes_missing_closure_and_blocks_admission(no_execution):
    foreign = compatibility_candidate(
        "parent", candidate_id="foreign_profile_case", profile="replayed-foreign-profile/v9",
        premises=None, artifact_closure=None, imports=None, axioms=None,
    )
    report, _raw, _digest = _compatibility_report([foreign])
    row = report["compatibility_matrix"][0]
    assert row["disposition"] == "foreign_profile" and row["reason"] == "foreign_profile"
    assert row["route"] is None and row["retained_evidence_ids"] == []
    assert row["closure_bound"] is False
    assert row["imports"] is row["premises"] is row["axioms"] is row["artifact_closure"] is None
    assert row["profile"] == "replayed-foreign-profile/v9"
    assert row["ast_sha256"] == sha(b"foreign_profile_case")
    _assert_admission_blocked(row)
    assert "premise_closure_absent" not in row["unresolved_prerequisites"]


@pytest.mark.parametrize("field,disposition,reason,prerequisite", [
    ("premises", "missing_premise_closure", "premises_absent", "premise_closure_absent"),
    ("artifact_closure", "missing_artifact_closure", "artifact_closure_absent", "artifact_closure_absent"),
    ("imports", "missing_import_closure", "imports_absent", "import_closure_absent"),
    ("axioms", "missing_axiom_closure", "axioms_absent", "axiom_closure_absent"),
])
def test_missing_route_closure_keeps_identity_and_blocks_admission(
        field, disposition, reason, prerequisite, no_execution):
    candidate = compatibility_candidate("direct", candidate_id="direct_gap_" + field, **{field: None})
    report, _raw, _digest = _compatibility_report([candidate])
    row = report["compatibility_matrix"][0]
    assert row["disposition"] == disposition and row["reason"] == reason
    assert row["route"] == "direct" and row["closure_bound"] is False
    assert row["retained_evidence_ids"] == [
        "parent-complete-norm-native-23-69", "direct-parent-norm-packet-23",
    ]
    assert row["imports"] is row["premises"] is row["axioms"] is row["artifact_closure"] is None
    assert row["unresolved_prerequisites"] == [*_BASE_UNRESOLVED, prerequisite]
    _assert_admission_blocked(row)


def test_missing_premise_precedes_missing_artifact(no_execution):
    candidate = compatibility_candidate(
        "preservation", candidate_id="preservation_two_gaps", premises=None, artifact_closure=None,
    )
    report, _raw, _digest = _compatibility_report([candidate])
    row = report["compatibility_matrix"][0]
    assert row["disposition"] == "missing_premise_closure"
    assert row["reason"] == "premises_absent"
    assert row["route"] == "preservation" and row["closure_bound"] is False
    assert "premise_closure_absent" in row["unresolved_prerequisites"]
    assert "artifact_closure_absent" not in row["unresolved_prerequisites"]
    _assert_admission_blocked(row)


def test_closure_mismatch_does_not_admit_or_replace_the_selected_ast(no_execution):
    parent = compatibility_candidate("parent", candidate_id="parent_premise_drift")
    parent["premises"] = list(parent["premises"])
    parent["premises"][0] = parent["premises"][0][:-1] + "X"
    direct = compatibility_candidate("direct", candidate_id="direct_theorem_count")
    direct["axioms"] = deepcopy(direct["axioms"])
    direct["axioms"]["theorem_count"] = 2
    conditional = compatibility_candidate("conditional", candidate_id="conditional_false_index")
    conditional["artifact_closure"] = deepcopy(conditional["artifact_closure"])
    conditional["artifact_closure"]["packet_index_supported"] = True
    native_row = compatibility_candidate("native", candidate_id="native_unexpected_mode")
    native_row["artifact_closure"] = deepcopy(native_row["artifact_closure"])
    native_row["artifact_closure"]["mode"] = "instance_only"
    invented = compatibility_candidate(
        "conditional", candidate_id="conditional_invented_mode", mode="body_with_membership")
    invented["artifact_closure"] = deepcopy(invented["artifact_closure"])
    invented["artifact_closure"]["mode"] = "invented_mode"
    cases = (
        ("parent", parent), ("direct", direct), ("conditional", conditional),
        ("native", native_row), ("conditional", invented),
    )
    report, _raw, _digest = _compatibility_report([candidate for _route, candidate in cases])
    for (route, candidate), row in zip(cases, report["compatibility_matrix"]):
        assert row["disposition"] == "closure_mismatch"
        assert row["reason"] == "closure_differs_from_route"
        assert row["route"] == route and row["closure_bound"] is False
        assert row["ast_sha256"] == candidate["ast_sha256"]
        assert row["imports"] is row["premises"] is row["axioms"] is row["artifact_closure"] is None
        _assert_admission_blocked(row)
    assert report["compatibility_matrix"][2]["unresolved_prerequisites"][-1] == "packet_index_reader_absent"


def test_compatibility_serialization_is_stable_and_order_sensitive(no_execution):
    candidates = [compatibility_candidate(route) for route in _COMPATIBILITY_ROUTES]
    report, raw, digest = _compatibility_report(candidates)
    again, _raw, _digest = _compatibility_report(candidates)
    assert canonical(again) == canonical(report)
    reordered = json.dumps(
        {"candidates": candidates, "schema": owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA},
        ensure_ascii=False, allow_nan=False).encode()
    third = owner.prepare_lean_compatibility_request_v1(reordered, expected_request_sha256=sha(reordered))
    assert canonical(third) == canonical(report)
    swapped = list(reversed(candidates))
    reversed_report, _raw, _digest = _compatibility_report(swapped)
    assert owner.lean_compatibility_request_sha256(reversed_report) != owner.lean_compatibility_request_sha256(report)
    assert [row["candidate_id"] for row in reversed_report["compatibility_matrix"]] == [
        row["candidate_id"] for row in reversed(report["compatibility_matrix"])
    ]
    pin = owner.lean_compatibility_request_sha256(report)
    tampered = deepcopy(report)
    tampered["compatibility_matrix"][0]["candidate_id"] = "rewritten_candidate"
    with pytest.raises(ValueError):
        owner.validate_lean_compatibility_request_v1(
            tampered, raw, expected_request_sha256=digest, expected_report_sha256=pin)
    with pytest.raises(ValueError):
        owner.prepare_lean_compatibility_request_v1(raw, expected_request_sha256="0" * 64)
    duplicate = raw.replace(b"{", b'{"schema":"legal-lean-compatibility-request/v1",', 1)
    with pytest.raises(ValueError):
        owner.prepare_lean_compatibility_request_v1(duplicate, expected_request_sha256=sha(duplicate))


def test_compatibility_request_rejects_duplicate_ids_bad_shapes_and_empty_sets(no_execution):
    with pytest.raises(ValueError):
        _compatibility_report([
            compatibility_candidate("parent", candidate_id="same_candidate"),
            compatibility_candidate("direct", candidate_id="same_candidate"),
        ])
    with pytest.raises(ValueError):
        _compatibility_report([])
    with pytest.raises(ValueError):
        _compatibility_report([
            compatibility_candidate("parent", candidate_id="parent_" + str(index))
            for index in range(17)
        ])
    shaped = compatibility_candidate("native", candidate_id="native_bad_imports")
    shaped["imports"] = {"role": "prelude", "imports": []}
    with pytest.raises(ValueError):
        _compatibility_report([shaped])
    uppercase = compatibility_candidate("parent", candidate_id="parent_uppercase_ast")
    uppercase["ast_sha256"] = uppercase["ast_sha256"].upper()
    with pytest.raises(ValueError):
        _compatibility_report([uppercase])

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


def compatibility_candidates():
    raw = owner.retained_lean_compatibility_request_bytes()
    return json.loads(raw.decode())["candidates"]


def compatibility_request(candidates):
    raw = canonical({"schema": owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA, "candidates": candidates})
    return raw, owner.prepare_lean_compatibility_request_v1(
        raw, expected_request_sha256=sha(raw))


def test_compatibility_request_binds_selected_ast_and_blocks_admission():
    candidates = compatibility_candidates()
    raw, report = compatibility_request(candidates)
    assert [row["route"] for row in report["compatibility_matrix"]] == list(owner.LEAN_COMPATIBILITY_ROUTES)
    assert [row["candidate_id"] for row in report["compatibility_matrix"]] == [
        row["candidate_id"] for row in json.loads(raw)["candidates"]]
    parent, direct, conditional, native, preservation = report["compatibility_matrix"]
    assert parent["missing_packet_index_profile"] == parent["profile"]
    assert parent["packet_index_reader"] is None and parent["packet_index_admitted"] is False
    assert parent["artifact_closure"]["retained_files"] == 29
    assert parent["evidence"][0]["pure_cases"] == 32 and parent["evidence"][0]["pure_phases"] == 96
    assert parent["evidence"][0]["actual_native_cases"] == 2 and parent["evidence"][0]["actual_native_phases"] == 6
    assert parent["evidence"][0]["counts_pooled"] is False
    assert parent["ast_sha256"] == parent["evidence"][0]["sha256"]
    assert direct["evidence"][0]["cases"] == 68 and direct["evidence"][0]["phases"] == 204
    assert direct["artifact_closure"]["packet_files"] == 23
    assert direct["packet_index_reader"] == "validate_parent_norm_native_packet_v1"
    assert native["evidence"][0]["cases"] == 23 and native["evidence"][0]["phases"] == 69
    assert conditional["artifact_closure"] == {"modules": 6, "project_files": 9, "theorems": 3}
    assert len(preservation["axioms"]) == 15 and len(preservation["imports"]) == 12
    assert preservation["artifact_closure"]["packet_files"] == 49
    assert preservation["evidence"][0]["historical_cohort_rerun"] is False
    closure = report["request_import_premise_axiom_closure"]
    assert closure["compiler_invoked"] is False
    assert [(row["route"], row["imports"], row["premises"], row["axioms"]) for row in closure["candidates"]] == [
        (row["route"], row["imports"], row["premises"], row["axioms"]) for row in report["compatibility_matrix"]]
    assert report["artifact_closure"]["compiler_invoked"] is False
    assert all(row["packet_index_admitted"] is False for row in report["artifact_closure"]["rows"])
    assert all(question["status"] == "unanswered" for question in report["unresolved_questions"])
    assert {question["id"] for question in report["unresolved_questions"]} >= {
        "parent_bound_29_file_packet_index_unadmitted", "lean_admission_blocked", "legal_admission_blocked"}
    assert all(row["lean_admitted"] is False and row["legal_admitted"] is False and row["admitted"] is False
               and row["formalized"] is False and row["compiler_invoked"] is False and row["introduced_axioms"] == []
               for row in report["compatibility_matrix"])
    assert any(item["symbol"] == "not_registered" and item["packet_index_api_registered"] is False
               for item in report["reuse_owners"])


@pytest.mark.parametrize("route", owner.LEAN_COMPATIBILITY_ROUTES)
def test_compatibility_request_refuses_foreign_profile(route):
    candidates = [row for row in compatibility_candidates() if row["route"] == route]
    candidates[0]["profile"] = "foreign-lean-profile/v9"
    raw = canonical({"schema": owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA, "candidates": candidates})
    with pytest.raises(ValueError, match="foreign compatibility profile"):
        owner.prepare_lean_compatibility_request_v1(raw, expected_request_sha256=sha(raw))


@pytest.mark.parametrize("route", owner.LEAN_COMPATIBILITY_ROUTES)
def test_compatibility_request_refuses_missing_premise_or_artifact_closure(route):
    base = [row for row in compatibility_candidates() if row["route"] == route][0]
    missing_premise = deepcopy(base)
    missing_premise["premises"] = missing_premise["premises"][:-1]
    missing_artifact = deepcopy(base)
    missing_artifact["artifact_closure"] = dict(missing_artifact["artifact_closure"])
    missing_artifact["artifact_closure"].pop(next(iter(missing_artifact["artifact_closure"])))
    for damaged, message in ((missing_premise, "missing premise closure"),
                             (missing_artifact, "missing artifact closure")):
        raw = canonical({"schema": owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA, "candidates": [damaged]})
        with pytest.raises(ValueError, match=message):
            owner.prepare_lean_compatibility_request_v1(raw, expected_request_sha256=sha(raw))


def test_compatibility_request_refuses_new_axioms_and_admission_claims():
    candidate = [row for row in compatibility_candidates() if row["route"] == "native"][0]
    axiomed = deepcopy(candidate)
    axiomed["axioms"] = {"original_norm_preserved": ["sorryAx"]}
    claimed = deepcopy(candidate)
    claimed["lean_admitted"] = True
    for damaged in (axiomed, claimed):
        raw = canonical({"schema": owner.LEAN_COMPATIBILITY_REQUEST_SCHEMA, "candidates": [damaged]})
        with pytest.raises(ValueError):
            owner.prepare_lean_compatibility_request_v1(raw, expected_request_sha256=sha(raw))


def test_compatibility_request_serialization_is_stable_and_order_sensitive():
    left_rows = compatibility_candidates()
    right_rows = list(reversed(left_rows))
    left_raw, left = compatibility_request(left_rows)
    right_raw, right = compatibility_request(right_rows)
    again_raw, again = compatibility_request(json.loads(left_raw.decode())["candidates"])
    assert again == left and again_raw == left_raw
    assert [row["route"] for row in left["compatibility_matrix"]] == [
        row["route"] for row in left_rows]
    assert [row["route"] for row in right["compatibility_matrix"]] == [
        row["route"] for row in right_rows]
    assert owner.lean_compatibility_request_sha256(left) != owner.lean_compatibility_request_sha256(right)
    digest = owner.lean_compatibility_request_sha256(left)
    assert digest == sha(canonical(left))
    regenerated = owner.validate_lean_compatibility_request_v1(
        left, left_raw, expected_request_sha256=sha(left_raw), expected_report_sha256=digest)
    assert regenerated == left
    damaged = deepcopy(left)
    damaged["compatibility_matrix"][0]["lean_admitted"] = True
    with pytest.raises(ValueError):
        owner.validate_lean_compatibility_request_v1(
            damaged, left_raw, expected_request_sha256=sha(left_raw),
            expected_report_sha256=owner.lean_compatibility_request_sha256(damaged))


def test_compatibility_request_does_not_invoke_a_compiler_or_packet_owners(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("compiler or packet owner invoked")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(owner, "_owners", refuse)
    monkeypatch.setattr(owner, "_parent_norm_packet_owners", refuse)
    raw, report = compatibility_request(compatibility_candidates())
    assert report["artifact_closure"]["compiler_invoked"] is False
    assert all(row["compiler_invoked"] is False for row in report["compatibility_matrix"])

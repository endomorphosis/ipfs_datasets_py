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


# Parent-bound packets retain declared synthetic compiler observations while
# genuine physical-parent preparation and selected reader replays stay separate.
# Import this one canonical native owning-test module so packet/index fixtures
# can share its existing genuine baseline within an admitted worker.
_PARENT_BOUND_PACKET_BASELINE = None


def _parent_bound_packet_helpers():
    import importlib
    return importlib.import_module(
        "tests.unit.logic.autoformal.test_legal_corpus_definition_use_native_v2")


def _parent_bound_packet_new(directory):
    helpers = _parent_bound_packet_helpers()
    directory.mkdir(parents=True, exist_ok=True)
    modes = helpers._parent_bound_norm_native_cached(directory / "originals")
    packets = {}
    # Only history construction is instrumented. This does not qualify source
    # replay or compilation; all patches close before any genuine reader test.
    with pytest.MonkeyPatch.context() as patch:
        install = helpers.synthetic_compiler.__wrapped__(patch, directory)
        replay_calls = helpers.instrumented_parent_bound_norm_replay.__wrapped__(patch)
        for mode, (data, preparation) in modes.items():
            executable, calls = install(preparation)
            output = directory / ("synthetic-history-" + mode)
            receipt = helpers._parent_bound_norm_native_build(
                data, preparation, executable, output)
            assert len(calls) >= 1
            manifest = preparation.to_dict()
            source_names = [name for name, _ in preparation.files]
            artifact_names = [name.replace(".", "/") + ".olean"
                              for name in manifest["expected_modules"]]
            files = {"project/" + name: (output / "project" / name).read_bytes()
                     for name in source_names}
            files["project/corpus-manifest.json"] = (output / "project/corpus-manifest.json").read_bytes()
            files.update({"executed-inputs/" + name: (output / "executed-inputs" / name).read_bytes()
                          for name in source_names})
            files.update({"compiled/" + name: (output / "compiled" / name).read_bytes()
                          for name in artifact_names})
            files.update({name: (output / name).read_bytes()
                          for name in ("stdout.txt", "stderr.txt", "runner-error.txt")})
            # The packet's externally supplied synthetic identities deliberately
            # use strict sibling names and complete version records. They are
            # not the native fixture's temporary executable names or real tools.
            command = [LAKE, "--offline", "--no-cache", "build", "legal"]
            life = historical_lifecycle()
            version = TOOLCHAIN.rsplit(":v", 1)[1]
            receipt.update(command=command, expected_command=command,
                           binary_sha256=dict(BINARIES), pid=life["leader"]["pid"],
                           native_lifecycle=life,
                           version_probes={name: {"command": [path, "--version"], "returncode": 0,
                               "stdout": "synthetic " + name + " version " + version + "\n", "stderr": ""}
                               for name, path in (("lake", LAKE), ("lean", LEAN))})
            files["build-receipt.json"] = canonical(seal(receipt))
            assert len(source_names) == 9 and len(artifact_names) == 6 and len(files) == 29
            packets[mode] = SyntheticPacket(data, preparation, tuple(sorted(files.items())))
        assert len(replay_calls) == 4  # two instrumented peer returns per unit build
    return packets


def _parent_bound_packet_cached(tmp_path_factory):
    global _PARENT_BOUND_PACKET_BASELINE
    if _PARENT_BOUND_PACKET_BASELINE is None:
        import tempfile
        directory = Path(tempfile.mkdtemp(prefix="parent-bound-packet-originals-",
                                         dir=tmp_path_factory.getbasetemp()))
        _PARENT_BOUND_PACKET_BASELINE = _parent_bound_packet_new(directory)
    return _PARENT_BOUND_PACKET_BASELINE


@pytest.fixture(scope="module")
def parent_bound_packet_modes(tmp_path_factory):
    return _parent_bound_packet_cached(tmp_path_factory)


@pytest.fixture
def parent_bound_packet_no_execution(no_execution, monkeypatch):
    current = _parent_bound_packet_helpers().native
    def forbidden(*args, **kwargs):
        pytest.fail("parent-bound packet reader entered native tools or binary inspection")
    for name in ("build_parent_bound_norm_definition_native_v1", "_installed_toolchain", "_binary_recheck"):
        monkeypatch.setattr(current, name, forbidden)


def _parent_bound_packet_arguments(base, files=None):
    files = base.files if files is None else files
    producer = _parent_bound_packet_helpers().native._parent_bound_norm_native_preparer()
    return {"expected_preparation_sha256": producer.parent_bound_norm_definition_preparation_sha256(base.preparation),
            "expected_bound_report_sha256": base.data["expected_bound_report_sha256"],
            "bound_definition_inputs": base.data["bound_definition_inputs"], "toolchain": TOOLCHAIN,
            "expected_receipt_file_sha256": sha(dict(files)["build-receipt.json"]),
            "expected_bundle_sha256": owner.parent_bound_norm_definition_packet_sha256(files),
            "expected_binary_sha256": dict(BINARIES)}


def _parent_bound_packet_read(base, files=None, *, repin=False, preparation=None, **overrides):
    files = base.files if files is None else files
    return owner.validate_parent_bound_norm_definition_native_packet_v1(
        files, base.preparation if preparation is None else preparation, base.data["bound_report"],
        **(_parent_bound_packet_arguments(base, files if repin else None) | overrides))


def _parent_bound_packet_receipt(base, edit):
    files = dict(base.files)
    receipt = json.loads(files["build-receipt.json"])
    edit(receipt)
    files["build-receipt.json"] = canonical(seal(receipt))
    return tuple(sorted(files.items()))


def _parent_bound_packet_logs(base, stdout):
    files = dict(base.files); receipt = json.loads(files["build-receipt.json"])
    raw = stdout.encode(); files["stdout.txt"] = raw
    receipt["stdout"] = raw[:owner.MAX_LOG_PREVIEW_BYTES].decode(errors="replace").replace("\x00", "\\u0000")
    receipt["log_sha256"]["stdout.txt"] = sha(raw); receipt["log_bytes"]["stdout.txt"] = len(raw)
    receipt["receipt_text_truncated"] = len(raw) > owner.MAX_LOG_PREVIEW_BYTES
    files["build-receipt.json"] = canonical(seal(receipt))
    return tuple(sorted(files.items()))


def _parent_bound_packet_parent_path(base, endpoint):
    original = base.data["bound_definition_inputs"]["companion_inputs"]
    replay = (original["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"]
              if endpoint == "norm" else original["definitions"][0]["preparation_inputs"]["parent_inputs"]["replay_inputs"])
    return Path(replay["parent_text_views_inputs"]["parent_descriptor"]["local_path"])


def _parent_bound_packet_unaccepted(value):
    assert value["receipt_consistency_only"] is True
    assert value["accepted_execution"] is value["accepted_outer_operation"] is False
    assert value["accepted_operation_result_bound"] is False
    assert value["outer_operation_outcome"] == "unprovided"
    assert value["selected_interpretation"] is None and value["governing_definition_use"] is None
    assert value["norm_interpretation_ready"] is False
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    for name in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(value[name]) is int and value[name] == 0
    assert all(value[name] is False for name in owner.FALSE_FLAGS)


@pytest.fixture
def instrumented_parent_bound_packet_replay(monkeypatch):
    """Fresh raw-storage returns only; NO genuine native/preparer replay credit."""
    from dataclasses import replace
    current = _parent_bound_packet_helpers().native
    calls = []
    def copied(preparation, bound_report, **kwargs):
        result = replace(preparation)
        calls.append((result, bound_report, kwargs))
        return result
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", copied)
    return calls


def test_parent_bound_packet_profiles_and_legacy_digest_populations_stay_separate(parent_bound_packet_modes):
    base = parent_bound_packet_modes["instance_only"]
    assert owner.PARENT_BOUND_NORM_PACKET_SCHEMA != owner.PARENT_NORM_PACKET_SCHEMA
    assert owner.PARENT_BOUND_NORM_PACKET_PROFILE != owner.PARENT_NORM_PACKET_PROFILE
    assert len(base.files) == 29
    changed = dict(base.files); changed["stdout.txt"] += b"\nchanged committed bytes\n"
    assert owner.parent_bound_norm_definition_packet_sha256(base.files) != owner.parent_bound_norm_definition_packet_sha256(tuple(sorted(changed.items())))
    with pytest.raises(ValueError): owner.packet_sha256(base.files)
    with pytest.raises(ValueError): owner.parent_norm_packet_sha256(base.files)
    with pytest.raises(ValueError): owner.parent_bound_norm_definition_packet_sha256(base.files[:-1])


@pytest.mark.parametrize("mode", ["instance_only", "body_with_membership"], ids=["instance", "membership"])
def test_parent_bound_packet_genuine_two_mode_validation_is_consistency_only(
        parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch, mode):
    base = parent_bound_packet_modes[mode]; before = deepcopy(base.data)
    current = _parent_bound_packet_helpers().native
    genuine = current.validate_parent_bound_norm_definition_native_v1; calls = []
    def observed(*args, **kwargs):
        checked = genuine(*args, **kwargs); calls.append(checked); return checked
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", observed)
    retained = _parent_bound_packet_read(base); value = retained.to_dict()
    assert len(calls) == 2 and retained.files == base.files and base.data == before
    assert all(item == base.preparation for item in calls)
    assert value["schema"] == owner.PARENT_BOUND_NORM_PACKET_SCHEMA
    assert value["profile"] == owner.PARENT_BOUND_NORM_PACKET_PROFILE
    assert value["readback_verified"] is value["current_preparation_replayed"] is True
    assert value["bound_definition_mode"] == mode
    assert value["bound_definition_report_sha256"] == base.data["expected_bound_report_sha256"]
    receipt = value["historical_native_receipt"]; manifest = base.preparation.to_dict()
    assert receipt == json.loads(dict(base.files)["build-receipt.json"])
    assert len(receipt["expected_modules"]) == len(receipt["compiled_modules"]) == 6
    assert len(receipt["executed_project_sha256"]) == 9
    assert len(receipt["conditional_theorems"]) == (2 if mode == "instance_only" else 3)
    assert receipt["theorem_axiom_dependencies"] == {name: [] for name in manifest["conditional_theorems"]}
    assert receipt["original_preparation_theorem_assumptions"] == manifest["theorem_assumptions"]
    assert value["retained_manifest_field_sha256"] == receipt["retained_manifest_field_sha256"]
    binding = json.loads(dict(base.files)["project/bound-norm-input-bindings.json"])
    assert canonical(binding["parent_bound_definition_report"]) == canonical(base.data["bound_report"])
    assert manifest["original_norm"]["source_binding"] is None and manifest["original_norm"]["source_bound"] is False
    _parent_bound_packet_unaccepted(value)
    _parent_bound_packet_export_capsule(base, retained, mode)


@pytest.mark.parametrize("field", ["expected_preparation_sha256", "expected_bound_report_sha256", "expected_receipt_file_sha256", "expected_bundle_sha256"])
def test_parent_bound_packet_independent_pins_refuse_before_owners(
        parent_bound_packet_modes, monkeypatch, field):
    base = parent_bound_packet_modes["instance_only"]; kwargs = _parent_bound_packet_arguments(base); kwargs[field] = "0" * 64
    monkeypatch.setattr(owner, "_parent_bound_norm_packet_owners", lambda: pytest.fail("preflight entered owners"))
    with pytest.raises(ValueError): owner.validate_parent_bound_norm_definition_native_packet_v1(base.files, base.preparation, base.data["bound_report"], **kwargs)


@pytest.mark.parametrize("damage", ["mutable", "missing", "extra", "duplicate"])
def test_parent_bound_packet_closed_transport_refuses_before_owners(parent_bound_packet_modes, monkeypatch, damage):
    base = parent_bound_packet_modes["instance_only"]; kwargs = _parent_bound_packet_arguments(base); files = base.files
    if damage == "mutable": files = ((files[0][0], bytearray(files[0][1])),) + files[1:]
    elif damage == "missing": files = files[:-1]
    elif damage == "extra": files = tuple(sorted(files + (("project/unexpected.lean", b"x"),)))
    else: files = files + (files[0],)
    monkeypatch.setattr(owner, "_parent_bound_norm_packet_owners", lambda: pytest.fail("transport entered owners"))
    with pytest.raises(ValueError): owner.validate_parent_bound_norm_definition_native_packet_v1(files, base.preparation, base.data["bound_report"], **kwargs)


@pytest.mark.parametrize("damage", ["boolean-pin", "binary-pair"])
def test_parent_bound_packet_scalar_bounds_refuse_before_owners(parent_bound_packet_modes, monkeypatch, damage):
    base = parent_bound_packet_modes["instance_only"]; kwargs = _parent_bound_packet_arguments(base)
    if damage == "boolean-pin": kwargs["expected_preparation_sha256"] = True
    else: kwargs["expected_binary_sha256"] = {LAKE: BINARIES[LAKE], "/other/bin/lean": BINARIES[LEAN]}
    monkeypatch.setattr(owner, "_parent_bound_norm_packet_owners", lambda: pytest.fail("bounds entered owners"))
    with pytest.raises(ValueError): owner.validate_parent_bound_norm_definition_native_packet_v1(base.files, base.preparation, base.data["bound_report"], **kwargs)


@pytest.mark.parametrize("damage", ["project", "executed", "empty-artifact", "bound-report"])
def test_parent_bound_packet_rehashed_content_does_not_replace_original_project(
        parent_bound_packet_modes, parent_bound_packet_no_execution, instrumented_parent_bound_packet_replay, damage):
    base = parent_bound_packet_modes["body_with_membership"]; files = dict(base.files); receipt = json.loads(files["build-receipt.json"])
    if damage in ("project", "executed"):
        prefix = "project/" if damage == "project" else "executed-inputs/"
        name = next(name for name, _ in base.preparation.files if name.endswith(".lean")); files[prefix + name] += b"\n-- changed retained source\n"
        if damage == "executed": receipt["executed_project_sha256"][name] = sha(files[prefix + name])
    elif damage == "empty-artifact":
        path = next(iter(receipt["artifact_files"])); files[receipt["artifact_files"][path]] = b""; receipt["artifact_sha256"][path] = sha(b""); receipt["artifact_bytes"][path] = 0
    else:
        name = "bound-norm-input-bindings.json"; changed = json.loads(files["project/" + name]); changed["parent_bound_definition_report"]["semantic_mask"] = False; raw = canonical(changed)
        files["project/" + name] = files["executed-inputs/" + name] = raw; receipt["executed_project_sha256"][name] = sha(raw)
    files["build-receipt.json"] = canonical(seal(receipt))
    with pytest.raises(ValueError): _parent_bound_packet_read(base, tuple(sorted(files.items())), repin=True)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nonempty"])
def test_parent_bound_packet_complete_theorem_stdout_remains_required(
        parent_bound_packet_modes, parent_bound_packet_no_execution, instrumented_parent_bound_packet_replay, damage):
    base = parent_bound_packet_modes["body_with_membership"]; lines = dict(base.files)["stdout.txt"].decode().splitlines()
    if damage == "missing": lines = lines[:-1]
    elif damage == "duplicate": lines.append(lines[0])
    else: lines[0] = lines[0].replace("does not depend on any axioms", "depends on axioms: [sorryAx]")
    with pytest.raises(ValueError): _parent_bound_packet_read(base, _parent_bound_packet_logs(base, "\n".join(lines) + "\n"), repin=True)


@pytest.mark.parametrize("damage", ["foreign-producer", "context-commitment", "assumptions", "semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"])
def test_parent_bound_packet_resealed_provenance_or_premises_do_not_promote(
        parent_bound_packet_modes, parent_bound_packet_no_execution, instrumented_parent_bound_packet_replay, damage):
    base = parent_bound_packet_modes["body_with_membership"]
    def edit(receipt):
        if damage == "foreign-producer":
            path = next(iter(receipt["producer_pins"])); receipt["producer_pins"]["/foreign-generation/owner.py"] = receipt["producer_pins"].pop(path)
        elif damage == "context-commitment": receipt["retained_manifest_field_sha256"]["original_parent_context_bindings"] = "0" * 64
        elif damage == "assumptions": receipt["theorem_assumptions"] = receipt["original_preparation_theorem_assumptions"] = receipt["theorem_assumptions"][:-1]
        else: receipt[damage] = False
    with pytest.raises(ValueError): _parent_bound_packet_read(base, _parent_bound_packet_receipt(base, edit), repin=True)


@pytest.mark.parametrize("damage", ["caller", "actual-return"])
def test_parent_bound_packet_late_original_and_actual_storage_remain_held(
        parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch, damage):
    from dataclasses import replace
    base = parent_bound_packet_modes["instance_only"]; current = _parent_bound_packet_helpers().native; inputs = deepcopy(base.data["bound_definition_inputs"]); calls = []
    def copied(preparation, *args, **kwargs):
        result = replace(preparation); calls.append(result)
        if len(calls) == 2:
            if damage == "caller": inputs["expected_request_sha256"] = "0" * 64
            else: object.__setattr__(calls[0], "files", list(calls[0].files))
        return result
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", copied)
    with pytest.raises(ValueError): _parent_bound_packet_read(base, bound_definition_inputs=inputs)
    assert len(calls) == 2


@pytest.mark.parametrize("endpoint", ["norm", "definition"])
def test_parent_bound_packet_last_native_return_cannot_hide_physical_drift(
        parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch, endpoint):
    from dataclasses import replace
    base = parent_bound_packet_modes["instance_only"]; current = _parent_bound_packet_helpers().native; path = _parent_bound_packet_parent_path(base, endpoint); before = path.read_bytes(); calls = []
    def copied(preparation, *args, **kwargs):
        result = replace(preparation); calls.append(result)
        if len(calls) == 2: path.write_bytes(before + b"\nlate physical parent drift\n")
        return result
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", copied)
    try:
        with pytest.raises(ValueError): _parent_bound_packet_read(base)
        assert len(calls) == 2
    finally: path.write_bytes(before)


def test_parent_bound_packet_changed_matcher_is_never_dispatched(
        parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch):
    from dataclasses import replace
    base = parent_bound_packet_modes["instance_only"]; current = _parent_bound_packet_helpers().native; calls = []; unexpected = []
    def changed(*args, **kwargs): unexpected.append(True); raise AssertionError("changed matcher dispatched")
    def copied(preparation, *args, **kwargs):
        calls.append(True); monkeypatch.setattr(owner, "_parent_bound_norm_packet_receipt_matches", changed); return replace(preparation)
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", copied)
    with pytest.raises(ValueError): _parent_bound_packet_read(base)
    assert len(calls) == 1 and unexpected == []


def test_parent_bound_packet_runtime_false_to_zero_is_type_sensitive(
        parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch):
    from dataclasses import replace
    base = parent_bound_packet_modes["instance_only"]; current = _parent_bound_packet_helpers().native; calls = []
    assert owner.FALSE_FLAGS["proof_checked"] is False
    def copied(preparation, *args, **kwargs):
        calls.append(True)
        if len(calls) == 2: monkeypatch.setitem(owner.FALSE_FLAGS, "proof_checked", 0)
        return replace(preparation)
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", copied)
    with pytest.raises(ValueError): _parent_bound_packet_read(base)
    assert len(calls) == 2


@pytest.mark.parametrize("delegate", ["seal", "actual-result"])
def test_parent_bound_packet_final_delegate_cannot_launder_acceptance(
        parent_bound_packet_modes, parent_bound_packet_no_execution, instrumented_parent_bound_packet_replay, monkeypatch, delegate):
    changed = []
    if delegate == "seal":
        genuine = contracts.seal_record
        def substituted(value, *args, **kwargs):
            result = genuine(value, *args, **kwargs)
            if type(value) is dict and value.get("schema") == owner.PARENT_BOUND_NORM_PACKET_SCHEMA:
                edit = result.copy(); edit["accepted_execution"] = True; result = genuine({k:v for k,v in edit.items() if k not in {"record_cid", "cid_scope"}}); changed.append(True)
            return result
        monkeypatch.setattr(contracts, "seal_record", substituted)
    else:
        genuine = owner.RetainedDefinitionUsePreservationPacket.__init__
        def substituted(result, *args, **kwargs):
            genuine(result, *args, **kwargs)
            edit = json.loads(result.observation_json)
            if edit.get("schema") == owner.PARENT_BOUND_NORM_PACKET_SCHEMA:
                edit["accepted_execution"] = True; object.__setattr__(result, "observation_json", canonical(seal(edit)).decode()); changed.append(True)
        monkeypatch.setattr(owner.RetainedDefinitionUsePreservationPacket, "__init__", substituted)
    with pytest.raises(ValueError): _parent_bound_packet_read(parent_bound_packet_modes["instance_only"])
    assert changed


def test_parent_bound_packet_primary_failure_keeps_secondary_custody_note(
        parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch):
    base = parent_bound_packet_modes["instance_only"]; current = _parent_bound_packet_helpers().native; inputs = deepcopy(base.data["bound_definition_inputs"]); failure = RuntimeError("original delegate failure")
    def failed(*args, **kwargs): inputs["expected_request_sha256"] = "0" * 64; raise failure
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", failed)
    with pytest.raises(RuntimeError) as caught: _parent_bound_packet_read(base, bound_definition_inputs=inputs)
    assert caught.value is failure and getattr(failure, "__notes__", ())


_PARENT_BOUND_CAPSULE_CODEC = "legal-ir-parent-bound-preservation-tagged-tree/v1"
_PARENT_BOUND_CAPSULE_MAX_PART = 16 * 1024**2
_PARENT_BOUND_CAPSULE_ENV = "IPFS_DATASETS_PARENT_BOUND_PRESERVATION_"


def _parent_bound_capsule_tree(value):
    import base64
    import math
    count = [0]
    def encode(item, depth):
        count[0] += 1
        if depth > 128 or count[0] > 2_000_000: raise ValueError("bounded capsule tree required")
        kind = type(item)
        if item is None: return {"type": "null"}
        if kind is bool: return {"type": "bool", "value": item}
        if kind is int: return {"type": "int", "value": str(item)}
        if kind is float:
            if not math.isfinite(item): raise ValueError("finite capsule float required")
            return {"type": "float", "value": item.hex()}
        if kind is str: return {"type": "str", "value": item}
        if kind is bytes: return {"type": "bytes", "value": base64.b64encode(item).decode("ascii")}
        if kind in (list, tuple):
            return {"type": "list" if kind is list else "tuple", "value": [encode(x, depth + 1) for x in item]}
        if kind is dict and all(type(k) is str for k in item):
            return {"type": "dict", "value": [[k, encode(item[k], depth + 1)] for k in sorted(item)]}
        raise ValueError("ordinary typed capsule tree required")
    return encode(value, 0)


def _parent_bound_capsule_untree(tree):
    import base64
    import math
    import re
    count = [0]
    def decode(item, depth):
        count[0] += 1
        if depth > 128 or count[0] > 2_000_000 or type(item) is not dict: raise ValueError("bounded tagged capsule required")
        tag = item.get("type")
        if tag == "null" and set(item) == {"type"}: return None
        if set(item) != {"type", "value"}: raise ValueError("closed capsule tag required")
        value = item["value"]
        if tag == "bool" and type(value) is bool: return value
        if tag == "str" and type(value) is str: return value
        if tag == "int" and type(value) is str and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value): return int(value)
        if tag == "float" and type(value) is str:
            result = float.fromhex(value)
            if math.isfinite(result) and result.hex() == value: return result
        if tag == "bytes" and type(value) is str:
            result = base64.b64decode(value, validate=True)
            if base64.b64encode(result).decode("ascii") == value: return result
        if tag in ("tuple", "list") and type(value) is list:
            items = [decode(x, depth + 1) for x in value]
            return tuple(items) if tag == "tuple" else items
        if tag == "dict" and type(value) is list:
            result = {}; keys = []
            for pair in value:
                if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str or pair[0] in result: raise ValueError("unique capsule keys required")
                keys.append(pair[0]); result[pair[0]] = decode(pair[1], depth + 1)
            if keys == sorted(keys): return result
        raise ValueError("unsupported or noncanonical capsule tag")
    return decode(tree, 0)


def _parent_bound_capsule_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("duplicate capsule JSON field")
            result[key] = value
        return result
    def nonfinite(value): raise ValueError("nonfinite capsule JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def _parent_bound_capsule_encode(value):
    tagged = _parent_bound_capsule_tree(value)
    if canonical(_parent_bound_capsule_tree(_parent_bound_capsule_untree(tagged))) != canonical(tagged): raise ValueError("capsule roundtrip changed types")
    raw = canonical({"schema": _PARENT_BOUND_CAPSULE_CODEC, "tree": tagged})
    if len(raw) > _PARENT_BOUND_CAPSULE_MAX_PART: raise ValueError("capsule part exceeds16MiB")
    return raw


def _parent_bound_capsule_decode(raw):
    doc = _parent_bound_capsule_json(raw)
    if type(doc) is not dict or set(doc) != {"schema", "tree"} or doc["schema"] != _PARENT_BOUND_CAPSULE_CODEC: raise ValueError("closed capsule part required")
    result = _parent_bound_capsule_untree(doc["tree"])
    if _parent_bound_capsule_encode(result) != raw: raise ValueError("noncanonical capsule part")
    return result


def _parent_bound_capsule_read(path, maximum):
    import stat
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path: raise ValueError("literal absolute capsule path required")
    for parent in path.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode): raise ValueError("unaliased capsule ancestry required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum: raise ValueError("bounded ordinary capsule file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream: raw = stream.read(maximum + 1)
        after = os.fstat(descriptor); current = path.lstat()
        identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        if len(raw) != before.st_size or identity(before) != identity(after) or identity(before) != identity(current): raise ValueError("capsule file changed")
        return raw
    finally: os.close(descriptor)


def _parent_bound_capsule_descriptor(path, raw=None):
    raw = _parent_bound_capsule_read(path, _PARENT_BOUND_CAPSULE_MAX_PART) if raw is None else raw
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def _parent_bound_capsule_checked(descriptor, maximum=_PARENT_BOUND_CAPSULE_MAX_PART):
    import re
    if type(descriptor) is not dict or set(descriptor) != {"path", "bytes", "sha256"}: raise ValueError("closed capsule descriptor required")
    if type(descriptor["path"]) is not str or type(descriptor["bytes"]) is not int or not 0 < descriptor["bytes"] <= maximum or type(descriptor["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", descriptor["sha256"]): raise ValueError("exact capsule descriptor types required")
    raw = _parent_bound_capsule_read(descriptor["path"], maximum)
    if len(raw) != descriptor["bytes"] or sha(raw) != descriptor["sha256"]: raise ValueError("capsule descriptor changed")
    return raw


def _parent_bound_capsule_save(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(directory)
    finally: os.close(directory)
    return _parent_bound_capsule_descriptor(path, raw)


def _parent_bound_capsule_source_root():
    native = _parent_bound_packet_helpers().native
    path = Path(native.__file__).resolve(strict=True).parents[3]
    if path != Path(native.__file__).parents[3]: raise ValueError("unaliased frozen source root required")
    return str(path)


def _parent_bound_packet_export_capsule(base, retained, mode):
    exported = os.environ.get(_PARENT_BOUND_CAPSULE_ENV + "CAPSULE_EXPORT_ROOT")
    if exported is None: return None
    import re
    generation = os.environ.get(_PARENT_BOUND_CAPSULE_ENV + "SOURCE_GENERATION_SHA256")
    if type(generation) is not str or not re.fullmatch("[0-9a-f]{64}", generation): raise ValueError("explicit export source generation required")
    parent = Path(exported)
    if not parent.is_absolute(): raise ValueError("explicit absolute capsule export root required")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.resolve(strict=True) != parent: raise ValueError("unaliased capsule export root required")
    if mode not in ("instance_only", "body_with_membership") or retained.files != base.files: raise ValueError("exact selected capsule mode required")
    directory = parent / mode; directory.mkdir(mode=0o700)
    values = {"inputs": base.data, "preparation": {"manifest_json": base.preparation.manifest_json, "files": base.preparation.files},
              "packet": {"packet_files": retained.files, "actualobservation_json": retained.observation_json}}
    parts = {name: _parent_bound_capsule_save(directory / (name + ".json"), _parent_bound_capsule_encode(value)) for name, value in values.items()}
    manifest = {"schema": "legal-ir-parent-bound-preservation-mode-capsule/v1", "mode": mode,
                "codec": _PARENT_BOUND_CAPSULE_CODEC, "source_root": _parent_bound_capsule_source_root(),
                "source_generation_sha256": generation, "parts": parts,
                "observation_sha256": sha(retained.observation_json.encode())}
    return _parent_bound_capsule_save(directory / "mode-manifest.json", canonical(manifest))


def _parent_bound_packet_load_capsule(mode):
    import re
    manifest_path = os.environ.get(_PARENT_BOUND_CAPSULE_ENV + "CAPSULE_MANIFEST")
    expected = os.environ.get(_PARENT_BOUND_CAPSULE_ENV + "CAPSULE_MANIFEST_SHA256")
    generation = os.environ.get(_PARENT_BOUND_CAPSULE_ENV + "SOURCE_GENERATION_SHA256")
    if not manifest_path or type(expected) is not str or not re.fullmatch("[0-9a-f]{64}", expected) or type(generation) is not str or not re.fullmatch("[0-9a-f]{64}", generation): raise ValueError("explicit accepted capsule manifest pins required")
    raw = _parent_bound_capsule_read(manifest_path, _PARENT_BOUND_CAPSULE_MAX_PART)
    if sha(raw) != expected: raise ValueError("root capsule manifest hash differs")
    manifest = _parent_bound_capsule_json(raw)
    required = {"schema", "accepted", "completed", "source_root", "source_generation_sha256", "modes"}
    if type(manifest) is not dict or set(manifest) != required or manifest["schema"] != "legal-ir-parent-bound-preservation-input-capsules/v1" or manifest["accepted"] is not True or manifest["completed"] is not True or manifest["source_root"] != _parent_bound_capsule_source_root() or manifest["source_generation_sha256"] != generation or type(manifest["modes"]) is not dict or set(manifest["modes"]) != {"instance_only", "body_with_membership"}: raise ValueError("accepted same-generation capsule manifest required")
    mode_ref = manifest["modes"][mode]; mode_raw = _parent_bound_capsule_checked(mode_ref); selected = _parent_bound_capsule_json(mode_raw)
    if type(selected) is not dict or set(selected) != {"schema", "mode", "codec", "source_root", "source_generation_sha256", "parts", "observation_sha256"} or selected["schema"] != "legal-ir-parent-bound-preservation-mode-capsule/v1" or selected["mode"] != mode or selected["codec"] != _PARENT_BOUND_CAPSULE_CODEC or selected["source_root"] != manifest["source_root"] or selected["source_generation_sha256"] != generation or type(selected["parts"]) is not dict or set(selected["parts"]) != {"inputs", "preparation", "packet"}: raise ValueError("closed exact mode capsule required")
    directory = Path(mode_ref["path"]).parent
    refs = [mode_ref]
    values = {}
    for name in ("inputs", "preparation", "packet"):
        descriptor = selected["parts"][name]
        if type(descriptor) is not dict or set(descriptor) != {"path", "bytes", "sha256"} or type(descriptor["path"]) is not str: raise ValueError("closed capsule part descriptor required")
        if Path(descriptor["path"]) != directory / (name + ".json"): raise ValueError("capsule part path changed role")
        refs.append(descriptor); values[name] = _parent_bound_capsule_decode(_parent_bound_capsule_checked(descriptor))
    prep = values["preparation"]; packet = values["packet"]; data = values["inputs"]
    if type(prep) is not dict or set(prep) != {"manifest_json", "files"} or type(prep["manifest_json"]) is not str or type(prep["files"]) is not tuple or type(packet) is not dict or set(packet) != {"packet_files", "actualobservation_json"} or type(packet["packet_files"]) is not tuple or type(packet["actualobservation_json"]) is not str or type(data) is not dict: raise ValueError("exact retained capsule object storage required")
    producer = _parent_bound_packet_helpers().native._parent_bound_norm_native_preparer()
    preparation = producer.DefinitionUseCorpusPreparation(prep["manifest_json"], prep["files"])
    base = SyntheticPacket(data, preparation, packet["packet_files"])
    retained = owner.RetainedDefinitionUsePreservationPacket(packet["actualobservation_json"], packet["packet_files"])
    arguments = _parent_bound_packet_arguments(base)
    observation = retained.to_dict()
    if observation["bound_definition_mode"] != mode or sha(retained.observation_json.encode()) != selected["observation_sha256"] or observation["preparation_full_canonical_sha256"] != arguments["expected_preparation_sha256"] or observation["bound_definition_report_sha256"] != arguments["expected_bound_report_sha256"] or observation["packet_bundle_sha256"] != arguments["expected_bundle_sha256"] or observation["receipt_file_sha256"] != arguments["expected_receipt_file_sha256"]: raise ValueError("capsule commitments differ")
    _parent_bound_packet_unaccepted(observation)
    def recheck():
        if _parent_bound_capsule_read(manifest_path, _PARENT_BOUND_CAPSULE_MAX_PART) != raw: raise ValueError("root capsule changed")
        for descriptor in refs: _parent_bound_capsule_checked(descriptor)
    recheck()
    return {"base": base, "retained": retained, "mode": mode, "manifest": manifest,
            "manifest_ref": _parent_bound_capsule_descriptor(Path(manifest_path), raw), "mode_ref": mode_ref, "recheck": recheck}


def test_parent_bound_packet_capsule_codec_preserves_authority_types():
    value = {"zero": 0, "false": False, "tuple": (b"\x00\xff", -0.0), "list": [None, "é"]}
    raw = _parent_bound_capsule_encode(value); restored = _parent_bound_capsule_decode(raw)
    assert type(restored["zero"]) is int and type(restored["false"]) is bool
    assert type(restored["tuple"]) is tuple and type(restored["list"]) is list
    assert restored["tuple"][0] == b"\x00\xff" and restored["tuple"][1].hex() == (-0.0).hex()
    assert _parent_bound_capsule_encode(False) != _parent_bound_capsule_encode(0)


def test_parent_bound_packet_capsule_codec_refuses_executable_or_ambiguous_values():
    with pytest.raises(ValueError): _parent_bound_capsule_untree({"type": "object", "value": "os.system"})
    with pytest.raises(ValueError): _parent_bound_capsule_untree({"type": "dict", "value": [["same", {"type": "null"}], ["same", {"type": "null"}]]})
    with pytest.raises(ValueError): _parent_bound_capsule_untree({"type": "bool", "value": 0})


@pytest.mark.parametrize("damage", ["five-fields", "depth"])
def test_parent_bound_packet_complete_outer_profile_refuses_before_owners(parent_bound_packet_modes, monkeypatch, damage):
    base = parent_bound_packet_modes["instance_only"]; arguments = _parent_bound_packet_arguments(base)
    original = deepcopy(arguments["bound_definition_inputs"])
    if damage == "five-fields": original.pop("expected_companion_sha256")
    else:
        nested = "leaf"
        for _ in range(49): nested = {"next": nested}
        original["companion_inputs"]["norm_preparation"]["oversized-depth"] = nested
    arguments["bound_definition_inputs"] = original
    monkeypatch.setattr(owner, "_parent_bound_norm_packet_owners", lambda: pytest.fail("outer profile entered owners"))
    with pytest.raises(ValueError, match="node/depth" if damage == "depth" else None): owner.validate_parent_bound_norm_definition_native_packet_v1(base.files, base.preparation, base.data["bound_report"], **arguments)


def test_parent_bound_packet_shared_helper_kwdefault_types_remain_fenced(parent_bound_packet_modes, parent_bound_packet_no_execution, monkeypatch):
    from dataclasses import replace
    base = parent_bound_packet_modes["instance_only"]; current = _parent_bound_packet_helpers().native; calls = []
    assert owner._bound_tree.__kwdefaults__["allow_bytes"] is False
    def copied(preparation, *args, **kwargs):
        calls.append(True)
        if len(calls) == 2: monkeypatch.setitem(owner._bound_tree.__kwdefaults__, "allow_bytes", 0)
        return replace(preparation)
    monkeypatch.setattr(current, "validate_parent_bound_norm_definition_native_v1", copied)
    with pytest.raises(ValueError): _parent_bound_packet_read(base)
    assert len(calls) == 2


def _parent_bound_packet_terminal_boundary_lines():
    import ast
    tree = ast.parse(Path(owner.__file__).read_bytes())
    public = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "validate_parent_bound_norm_definition_native_packet_v1")
    terminal = next(node for node in public.body if isinstance(node, ast.FunctionDef) and node.name == "terminal")
    callbacks = [node for node in terminal.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    serialized = [node for node in callbacks if isinstance(node.value.func, ast.Name) and node.value.func.id == "serialized_fence"]
    last_guard = [node for node in callbacks if isinstance(node.value.func, ast.Name) and node.value.func.id == "fence"][-1]
    # The declared new profile ends its overridable observation serializer before
    # a full original/held/physical guard that does not serialize observations.
    assert any(key.arg == "serialization" and isinstance(key.value, ast.Constant) and key.value.value is False
               for key in last_guard.value.keywords)
    assert serialized[-1].lineno < last_guard.lineno
    return serialized[-1].lineno, last_guard.lineno


def _parent_bound_packet_last_serialization_line():
    return _parent_bound_packet_terminal_boundary_lines()[0]


@pytest.mark.parametrize("damage", ["caller", "observation"])
def test_parent_bound_packet_last_serializer_return_cannot_change_terminal_custody(
        parent_bound_packet_modes, parent_bound_packet_no_execution, instrumented_parent_bound_packet_replay, monkeypatch, damage):
    base = parent_bound_packet_modes["instance_only"]; inputs = deepcopy(base.data["bound_definition_inputs"])
    target = _parent_bound_packet_last_serialization_line(); genuine = owner._wire; changed = []
    def encoded(value, *args, **kwargs):
        raw = genuine(value, *args, **kwargs)
        frame = sys._getframe(1); terminal = None
        while frame is not None:
            if frame.f_code.co_name == "terminal" and frame.f_code.co_filename == owner.__file__: terminal = frame; break
            frame = frame.f_back
        if (terminal is not None and terminal.f_lineno == target and not changed
                and type(value) is dict and value.get("schema") == owner.PARENT_BOUND_NORM_PACKET_SCHEMA):
            if damage == "caller": inputs["expected_request_sha256"] = "0" * 64
            else: value["accepted_execution"] = True
            changed.append(damage)
        return raw
    monkeypatch.setattr(owner, "_wire", encoded)
    with pytest.raises(ValueError): _parent_bound_packet_read(base, bound_definition_inputs=inputs)
    assert changed == [damage]


@pytest.mark.parametrize("delegate,damage", [("pins", "caller"), ("pins", "actual-preparation"), ("witness", "caller"), ("witness", "actual-preparation")], ids=["pins-caller", "pins-actual", "last-witness-caller", "last-witness-actual"])
def test_parent_bound_packet_last_producer_return_keeps_raw_terminal_custody(
        parent_bound_packet_modes, parent_bound_packet_no_execution, instrumented_parent_bound_packet_replay, monkeypatch, delegate, damage):
    base = parent_bound_packet_modes["instance_only"]; inputs = deepcopy(base.data["bound_definition_inputs"])
    target = _parent_bound_packet_terminal_boundary_lines()[1]
    name = "_parent_bound_norm_packet_pins" if delegate == "pins" else "_parent_bound_norm_packet_file_witness"
    genuine = getattr(owner, name); changed = []
    def returned(*args, **kwargs):
        result = genuine(*args, **kwargs); frame = sys._getframe(1); terminal = guard = None
        while frame is not None:
            if frame.f_code.co_filename == owner.__file__:
                if frame.f_code.co_name == "fence": guard = frame
                if frame.f_code.co_name == "terminal": terminal = frame; break
            frame = frame.f_back
        last_witness = True
        if delegate == "witness":
            physical = None if guard is None else guard.f_locals.get("physical")
            last_witness = bool(physical) and len(args) == 2 and args[1] is physical[-1][0]
        if terminal is not None and terminal.f_lineno == target and last_witness and not changed:
            if damage == "caller": inputs["expected_request_sha256"] = "0" * 64
            else: object.__setattr__(instrumented_parent_bound_packet_replay[0][0], "files", list(instrumented_parent_bound_packet_replay[0][0].files))
            changed.append((delegate, damage))
        return result
    monkeypatch.setattr(owner, name, returned)
    with pytest.raises(ValueError): _parent_bound_packet_read(base, bound_definition_inputs=inputs)
    assert changed == [(delegate, damage)]

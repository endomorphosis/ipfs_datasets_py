"""Contract and real-compiler checks for the small source-bound pilot gate."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_pilot_lake as pilot
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunLimits, ToolRunRequest


TOOLCHAIN = "leanprover/lean4:v4.34.1"


def candidate(identity="clerk", modality="O"):
    source = f"The {identity} must file the report."
    return {"candidate_id": identity, "source_text": source,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "canonical_ir": {"rules": [{"modality": modality, "actor": identity,
                                        "action": "file", "object": "report", "conditions": [],
                                        "exceptions": [], "temporal": []}]}}


@pytest.fixture
def installed_lake():
    configured = os.environ.get("LEGAL_PILOT_TEST_LAKE")
    path = Path(configured) if configured else Path.home() / ".elan/toolchains/leanprover--lean4---v4.34.1/bin/lake"
    if not path.is_file():
        pytest.skip("explicit native Lean 4.34.1 toolchain unavailable")
    return str(path)


def test_preparation_is_deterministic_source_bound_and_has_all_imports():
    rows = [candidate(), candidate("director", "P")]
    prepared = pilot.prepare_legal_pilot(rows, toolchain=TOOLCHAIN)
    assert prepared == pilot.prepare_legal_pilot(rows, toolchain=TOOLCHAIN)
    pilot.validate_legal_pilot_preparation(prepared)
    files = dict(prepared.files)
    assert files["LegalPilot.lean"].splitlines() == [
        "import LegalPilot.Candidate0000", "import LegalPilot.Candidate0001"]
    assert 'name = "legal"' in files["lakefile.toml"]
    assert prepared.to_dict()["candidates"][0]["source_sha256"] == rows[0]["source_sha256"]
    assert not prepared.to_dict()["backend_executed"]
    assert not prepared.to_dict()["source_semantics_verified"]
    with pytest.raises(FrozenInstanceError):
        prepared.input_json = "changed"


def test_missing_import_is_refused_even_when_hash_is_updated():
    prepared = pilot.prepare_legal_pilot([candidate(), candidate("director")], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    files["LegalPilot.lean"] = "import LegalPilot.Candidate0000\n"
    manifest = prepared.to_dict()
    manifest["file_sha256"]["LegalPilot.lean"] = hashlib.sha256(files["LegalPilot.lean"].encode()).hexdigest()
    tampered = replace(prepared, files=tuple(sorted(files.items())), manifest_json=pilot._json(manifest))
    with pytest.raises(ValueError, match="coverage changed"):
        pilot.validate_legal_pilot_preparation(tampered)


def test_changed_candidate_or_source_is_refused():
    row = candidate()
    row["source_text"] += " unless exempt."
    with pytest.raises(ValueError, match="source_sha256"):
        pilot.prepare_legal_pilot([row], toolchain=TOOLCHAIN)
    prepared = pilot.prepare_legal_pilot([candidate()], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    files["LegalPilot/Candidate0000.lean"] += "this is not Lean\n"
    with pytest.raises(ValueError, match="coverage changed"):
        pilot.validate_legal_pilot_preparation(replace(prepared, files=tuple(sorted(files.items()))))


@pytest.mark.parametrize("facet", ["conditions", "exceptions", "temporal"])
def test_unsupported_qualifier_blocks_whole_batch_without_subset_project(facet, tmp_path):
    row = candidate("director")
    row["canonical_ir"]["rules"][0][facet] = ["unsupported"]
    output = tmp_path / "blocked"
    receipt = pilot.build_legal_pilot([candidate(), row], toolchain=TOOLCHAIN,
                                     lake_executable="not-invoked", output_directory=output).to_dict()
    assert receipt["status"] == "blocked"
    assert [r["status"] for r in receipt["candidates"]] == ["supported", "unsupported"]
    assert not receipt["backend_executed"]
    assert not receipt["build_passed"]
    assert not (output / "lakefile.toml").exists()


def test_unsupported_family_and_placeholder_remain_visible():
    row = candidate()
    row["family"] = "tdfol"
    prepared = pilot.prepare_legal_pilot([row], toolchain=TOOLCHAIN).to_dict()
    assert prepared["candidates"][0]["status"] == "unsupported"
    row = candidate()
    row["canonical_ir"]["rules"][0]["action"] = "sorry"
    prepared = pilot.prepare_legal_pilot([row], toolchain=TOOLCHAIN).to_dict()
    assert "placeholder" in prepared["candidates"][0]["reason"]


@pytest.mark.parametrize("mutate", [
    lambda r: r["canonical_ir"]["rules"][0].update(modality="B"),
    lambda r: r["canonical_ir"].update(rules=[]),
    lambda r: r.update(source_sha256="0" * 64),
    lambda r: r.update(source_text="x" * (pilot.MAX_SOURCE_BYTES + 1)),
])
def test_invalid_candidates_are_rejected(mutate):
    row = candidate()
    mutate(row)
    with pytest.raises(ValueError):
        pilot.prepare_legal_pilot([row], toolchain=TOOLCHAIN)


def test_real_lowercase_target_builds_every_candidate_and_persists_receipt(installed_lake, tmp_path):
    output = tmp_path / "legal"
    frozen = pilot.build_legal_pilot([candidate(), candidate("director", "P")], toolchain=TOOLCHAIN,
                                     lake_executable=installed_lake, output_directory=output)
    receipt = frozen.to_dict()
    assert receipt["build_passed"], receipt.get("stdout", "") + receipt.get("stderr", "")
    assert receipt["backend_executed"]
    assert receipt["command"][-2:] == ["build", "legal"]
    assert receipt["manifest_coverage_passed"]
    assert set(receipt["compiled_modules"]) == {
        "LegalPilot", "LegalPilot.Prelude", "LegalPilot.Candidate0000", "LegalPilot.Candidate0001"}
    assert json.loads((output / "pilot-receipt.json").read_text()) == receipt
    digest = receipt.pop("receipt_sha256")
    assert hashlib.sha256(pilot._json(receipt).encode()).hexdigest() == digest
    assert all(not receipt[key] for key in ("admitted", "formalized", "proof_authority", "source_semantics_verified"))
    receipt["build_passed"] = False
    assert frozen.to_dict()["build_passed"]
    with pytest.raises(ValueError, match="fresh output_directory"):
        pilot.build_legal_pilot([candidate()], toolchain=TOOLCHAIN,
                               lake_executable=installed_lake, output_directory=output)


def test_real_target_fails_for_broken_second_candidate(installed_lake):
    """An invalid nonfirst candidate must be reached by the lowercase target."""
    prepared = pilot.prepare_legal_pilot([candidate(), candidate("director")], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    files["LegalPilot/Candidate0001.lean"] += "def invalid_candidate : Nat := True\n"
    result = BoundedToolRunner().run(ToolRunRequest(
        argv=(installed_lake, "build", "legal"), input_files=files,
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "2"},
        limits=ToolRunLimits(timeout_seconds=60, cpu_seconds=60, max_workspace_bytes=128 * 1024**2)))
    assert result.pid is not None
    assert result.returncode != 0
    assert "Candidate0001" in result.stdout + result.stderr


def test_explicit_toolchain_must_match_binary(installed_lake):
    with pytest.raises(ValueError, match="does not match"):
        pilot.build_legal_pilot([candidate()], toolchain="leanprover/lean4:v0.0.1", lake_executable=installed_lake)

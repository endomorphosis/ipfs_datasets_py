"""Source bindings, explicit interpretations, complete builds and rejection."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_qualified_lake as gate
from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as bridge
from scripts.ops.legal_ir import check_legal_qualified_decoder_outputs as check

TOOLCHAIN = "leanprover/lean4:v4.34.1"


@pytest.mark.parametrize("names", [[], ["first"], ["first", "first"]])
def test_incomplete_or_duplicate_model_coverage_cannot_pass(names):
    with pytest.raises(ValueError):
        check.validate_model_coverage({"runs": [{"name": name} for name in names]},
            {"first": {"challenge": "hash"}, "second": {"challenge": "hash"}})


def test_complete_model_coverage_matches_freeze():
    check.validate_model_coverage({"runs": [{"name": "first"}, {"name": "second"}]},
        {"first": {"challenge": "hash"}, "second": {"challenge": "hash"}})


def candidate(identity="clerk", temporal="within 10 days"):
    text = f"The {identity} must submit the report {temporal} if requested unless emergency."
    return {"candidate_id": identity, "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "canonical_ir": {"rules": [{"modality": "O", "actor": identity, "action": "submit", "object": "report",
                                    "conditions": ["requested"], "exceptions": ["emergency"], "temporal": [temporal]}]}}


def entry(row=None):
    row = row or candidate()
    return {"candidate": row, "interpretation": check.synthetic_interpretation(row, policy=check.POLICY)}


@pytest.fixture
def lake():
    path = Path.home() / ".elan/toolchains/leanprover--lean4---v4.34.1/bin/lake"
    if not path.is_file():
        pytest.skip("native Lean4.34.1 is not installed")
    return str(path)


def test_unfilled_interpretation_has_no_implicit_policy():
    row = candidate()
    prepared = gate.prepare_qualified_legal([{"candidate": row, "interpretation": bridge.interpretation_skeleton(row)}],
                                           toolchain=TOOLCHAIN)
    assert not prepared.to_dict()["all_candidates_supported"]
    assert "lakefile.toml" not in dict(prepared.files)


def test_qualification_is_explicit_and_source_bound():
    value = entry()
    before = deepcopy(value)
    prepared = gate.prepare_qualified_legal([value], toolchain=TOOLCHAIN)
    gate.validate_preparation(prepared)
    assert value == before
    receipt = prepared.to_dict()
    assert receipt["all_candidates_supported"] and not receipt["source_semantics_verified"]
    assert not receipt["admitted"] and not receipt["all_logic_families_supported"]
    assert receipt["candidates"][0]["interpretation_sha256"] == gate._sha(gate._json(value["interpretation"]))
    source = dict(prepared.files)["LegalQualified/Candidate0000.lean"]
    assert "requested" in source and "emergency" in source and "origin + 10" in source


@pytest.mark.parametrize("field", ["conditions", "exceptions", "temporal"])
def test_dropping_a_qualifier_invalidates_its_interpretation(field):
    value = entry()
    value["candidate"]["canonical_ir"]["rules"][0][field] = []
    result = gate.prepare_qualified_legal([value], toolchain=TOOLCHAIN).to_dict()
    assert not result["all_candidates_supported"]


def test_source_tamper_and_duplicate_identity_reject_before_build():
    value = entry()
    value["candidate"]["source_text"] += " Different."
    with pytest.raises(ValueError, match="source_sha256"):
        gate.prepare_qualified_legal([value], toolchain=TOOLCHAIN)
    with pytest.raises(ValueError, match="unique"):
        gate.prepare_qualified_legal([entry(), entry()], toolchain=TOOLCHAIN)


def test_unsupported_interpretation_blocks_entire_batch(tmp_path):
    value = entry(candidate("director"))
    value["interpretation"]["formulas"][0]["exception_scope"] = "unknown"
    result = gate.build_qualified_legal([entry(), value], toolchain=TOOLCHAIN,
        lake_executable="not-executed", output_directory=tmp_path / "blocked").to_dict()
    assert result["status"] == "blocked" and not result["backend_executed"]
    assert [r["status"] for r in result["candidates"]] == ["supported", "unsupported"]
    assert not (tmp_path / "blocked/lakefile.toml").exists()


def test_removed_import_cannot_be_hidden_by_updating_manifest_hash():
    prepared = gate.prepare_qualified_legal([entry(), entry(candidate("director"))], toolchain=TOOLCHAIN)
    files, manifest = dict(prepared.files), prepared.to_dict()
    files["LegalQualified.lean"] = "import LegalQualified.Candidate0000\n"
    manifest["file_sha256"]["LegalQualified.lean"] = gate._sha(files["LegalQualified.lean"])
    with pytest.raises(ValueError, match="coverage changed"):
        gate.validate_preparation(replace(prepared, files=tuple(sorted(files.items())), manifest_json=gate._json(manifest)))


def test_synthetic_policy_never_guesses_calendar_clock():
    with pytest.raises(ValueError, match="calendar"):
        check.synthetic_interpretation(candidate(temporal="before 2043-01-01"), policy=check.POLICY)
    with pytest.raises(ValueError, match="policy"):
        check.synthetic_interpretation(candidate(), policy=None)


def test_reference_free_selection_records_all_rejections():
    rows = [candidate(), candidate("director", "before 2043-01-01"), candidate("officer")]
    sources = [{"id": r["candidate_id"], "source_text": r["source_text"], "source_sha256": r["source_sha256"]} for r in rows]
    generated = [{"status": "decoded", "canonical_ir": r["canonical_ir"], "source_sha256": r["source_sha256"],
                  "target_access": False, "teacher_forcing": False} for r in rows]
    generated[-1].update(status="abstained", canonical_ir=None, reason="copied_span_overlap")
    result = check.select_candidates(sources, generated, toolchain=TOOLCHAIN, policy=check.POLICY)
    assert result["source_count"] == 3 and result["supported_count"] == 1 and result["decoded_count"] == 2
    assert result["exclusion_counts"] == {"explicit_interpretation_unsupported": 1, "decoder_abstained": 1}
    generated[0]["target_access"] = True
    with pytest.raises(ValueError, match="reference access"):
        check.select_candidates(sources, generated, toolchain=TOOLCHAIN, policy=check.POLICY)


def test_real_qualified_target_builds_every_module_and_persists_declarations(lake, tmp_path):
    output = tmp_path / "qualified"
    result = gate.build_qualified_legal([entry(), entry(candidate("director", "for at least 2 hours"))],
        toolchain=TOOLCHAIN, lake_executable=lake, output_directory=output).to_dict()
    assert result["build_passed"], result.get("stdout", "") + result.get("stderr", "")
    assert result["command"][-2:] == ["build", "legal"] and result["manifest_coverage_passed"]
    assert len(result["compiled_modules"]) == 4
    assert (output / "qualified-inputs.json").is_file()
    assert not result["source_semantics_verified"]
    with pytest.raises(ValueError, match="fresh"):
        gate.build_qualified_legal([entry()], toolchain=TOOLCHAIN, lake_executable=lake, output_directory=output)


def test_real_false_scope_claim_fails_lowercase_target(lake):
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunLimits, ToolRunRequest
    prepared = gate.prepare_qualified_legal([entry(), entry(candidate("director"))], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    # Candidate0001 must actually be reached. No declared legal interpretation
    # permits this fabricated proof of False.
    files["LegalQualified/Candidate0001.lean"] += "\nexample : False := by decide\n"
    result = BoundedToolRunner().run(ToolRunRequest(argv=(lake, "build", "legal"), input_files=files,
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "2"},
        limits=ToolRunLimits(timeout_seconds=60, cpu_seconds=60, max_workspace_bytes=128 * 1024**2)))
    assert result.pid is not None and result.returncode != 0
    assert "Candidate0001" in result.stdout + result.stderr

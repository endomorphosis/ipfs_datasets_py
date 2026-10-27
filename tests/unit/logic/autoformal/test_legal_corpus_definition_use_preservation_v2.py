"""Source/review replay and in-corpus concrete AST preservation preparation.

The donor/consumer sources, review signatures, original corpus project and four
standalone AST preparations all use their genuine public owners. Preparation
executes no native compiler. Authored fixtures establish no statutory meaning.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as corpus
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_v2 as owner


_SPEC = importlib.util.spec_from_file_location(
    "_genuine_corpus_definition_use_preservation_fixtures",
    Path(__file__).with_name("test_legal_corpus_definition_use_lake_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
TOOLCHAIN = _FIXTURE.TOOLCHAIN
ROLES = ("donor", "consumer", "alias", "joint")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def corpus_sha256(preparation):
    return sha(canonical({"manifest": preparation.to_dict(),
                          "files": [list(row) for row in preparation.files]}))


def original_data(family="fol"):
    data = _FIXTURE.assessment_data(family)
    data["corpus_preparation"] = corpus.prepare_definition_use_corpus_v2(**_FIXTURE.arguments(data))
    return data


def arguments(data):
    return {
        "expected_corpus_preparation_sha256": corpus_sha256(data["corpus_preparation"]),
        "expected_assessment_file_sha256": data["expected_assessment_file_sha256"],
        "review_inputs": data["review_inputs"], "toolchain": data["toolchain"],
    }


def prepare(data, **overrides):
    return owner.prepare_definition_use_preservation_v2(
        data["corpus_preparation"], data["assessment_raw"], **(arguments(data) | overrides)
    )


def validate(data, preparation, **overrides):
    return owner.validate_definition_use_preservation_v2(
        preparation, data["corpus_preparation"], data["assessment_raw"],
        **({"expected_preparation_sha256": owner.preparation_sha256(preparation)}
           | arguments(data) | overrides),
    )


def meta(preparation):
    return json.loads(preparation.manifest_json)


def reseal(preparation, manifest=None, files=None):
    manifest = meta(preparation) if manifest is None else manifest
    files = dict(preparation.files) if files is None else files
    manifest["file_sha256"] = {name: sha(text.encode()) for name, text in sorted(files.items())}
    manifest = contracts.seal_record({key: value for key, value in manifest.items()
                                      if key not in {"record_cid", "cid_scope"}})
    return replace(preparation, manifest_json=canonical(manifest).decode(), files=tuple(sorted(files.items())))


@pytest.fixture(scope="module")
def base():
    data = original_data()
    return data, prepare(data)


def test_public_import_is_stdlib_only_without_source_or_native_owners():
    script = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','multiformats','pyarrow','duckdb','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_corpus_preservation_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('DefinitionUsePreservationPreparation','prepare_definition_use_preservation_v2','validate_definition_use_preservation_v2','preparation_sha256'):
    assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, owner.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_all_four_roles_target_exact_original_modules_under_one_interpretation(family):
    data = original_data(family)
    before = deepcopy(data["review_inputs"])
    original = data["corpus_preparation"]
    original_manifest, original_files = original.to_dict(), dict(original.files)
    preparation = prepare(data)
    manifest, files = meta(preparation), dict(preparation.files)
    assert len(files) == len(preparation.files) == 16
    assert len(manifest["expected_modules"]) == len(set(manifest["expected_modules"])) == 12
    assert manifest["expected_modules"][:6] == original_manifest["expected_modules"]
    assert manifest["expected_modules"][-1] == "LegalCorpusV2Preservation"
    assert files["lean-toolchain"] == TOOLCHAIN + "\n"
    assert 'roots = ["LegalCorpusV2", "LegalCorpusV2Preservation"]' in files["lakefile.toml"]
    for name, text in original.files:
        if name.endswith(".lean") or name in {"lean-toolchain", "v2-input-bindings.json"}:
            assert files[name] == text, name
    assert manifest["file_sha256"] == {name: sha(text.encode()) for name, text in sorted(files.items())}
    assert manifest["conditional_theorems"] == original_manifest["conditional_theorems"]
    assert manifest["theorems"] == manifest["conditional_theorems"] + manifest["preservation_theorems"]
    assert len(manifest["preservation_theorems"]) == 12
    assert len(set(manifest["theorems"])) == 15
    assert [row["role"] for row in manifest["preservation_fragments"]] == list(ROLES)
    role_sources = {row["role"]: row for row in original_manifest["native_fragments"]}
    all_source = "\n".join(text for name, text in preparation.files if name.endswith(".lean"))
    assert all_source.count("structure Interpretation (Entity Agent : Type)") == 1
    assert all_source.count("inductive NativeValue") == 1
    assert all_source.count("inductive UnaryFOL") == 1
    assert all_source.count("#print axioms") == 15
    for role in ROLES:
        target = role_sources[role]["module"] + ".formula_0 i t"
        assert target in all_source
        assert role_sources[role]["native"]["lean_body"] in files[role_sources[role]["module"].replace(".", "/") + ".lean"]
        binding = next(row for row in manifest["preservation_fragments"] if row["role"] == role)
        assert binding["original_module"] == role_sources[role]["module"]
        assert binding["native_ast_sha256"] == role_sources[role]["native"]["native_ast_sha256"]
        assert binding["lean_body_sha256"] == sha(role_sources[role]["native"]["lean_body"].encode())
        proof_source = files[binding["preservation_module"].replace(".", "/") + ".lean"]
        assert target in proof_source
        assert "denote i typedNativeAst emptyEnvironment t" in proof_source
        assert "(i : Interpretation Entity Agent)" in proof_source
        assert "def formula_0" not in proof_source
        assert "structure Interpretation" not in proof_source
        assert len(binding["theorems"]) == 3
    assert manifest["original_corpus_preparation_full_canonical_sha256"] == corpus_sha256(original)
    assert manifest["original_corpus_preparation_manifest_sha256"] == sha(original.manifest_json.encode())
    assert manifest["original_corpus_preparation_cid"] == original_manifest["record_cid"]
    inputs = json.loads(files["preservation-inputs.json"])
    assert inputs["original_corpus_preparation"] == {
        "manifest_json": original.manifest_json, "files": [list(row) for row in original.files],
    }
    assert inputs["original_native_fragments"] == [row["native"] for row in original_manifest["native_fragments"]]
    reference = manifest["reference_contract"]
    assert reference["requires_successful_exact_native_receipt"] is True
    assert reference["legal_proof_cache_compatible"] is False
    assert reference["proof_cache_admission_verified"] is False
    assert reference["proof_checked"] is False
    assert all(value is False for value in reference["authority"].values())
    assert reference["training_mask"] == reference["evaluation_gold_mask"] == 0
    assert reference["key_material"]["preservation_fragments"] == manifest["preservation_fragments"]
    seen = set()
    for module in manifest["expected_modules"]:
        path = module.replace(".", "/") + ".lean"
        actual = re.findall(r"(?m)^import ([A-Za-z][A-Za-z0-9_.]*)$", files[path])
        assert actual == manifest["module_imports"][module]
        assert set(actual) <= seen
        seen.add(module)
    assert all(value is False for value in manifest["authority"].values())
    assert all(manifest[name] is False for name in owner.FALSE_FLAGS)
    assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
    assert manifest["preparation_only"] is True
    assert validate(data, preparation) == preparation
    assert data["review_inputs"] == before
    assert dict(original.files) == original_files and original.to_dict() == original_manifest


@pytest.mark.parametrize("status", ["pending", "rejected", "stale_dependency"])
def test_source_review_outcome_remains_separate_from_prepared_kernel_obligations(base, status):
    original, _ = base
    signed = deepcopy(original["signed"])
    if status == "pending":
        signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
        signed["registry"]["keys"] = []
        signed["reviews"] = []
        _FIXTURE._COMBINED._REVIEW.refresh(signed)
    elif status == "rejected":
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    else:
        key = next(row["artifact_id"] for row in signed["manifest"]["artifacts"]
                   if row["artifact_id"].startswith("definition-lookup:"))
        signed["observed_artifact_sha256s"][key] = "0" * 64
    data = _FIXTURE.refresh_assessment(signed)
    data["corpus_preparation"] = corpus.prepare_definition_use_corpus_v2(**_FIXTURE.arguments(data))
    preparation = prepare(data)
    manifest = meta(preparation)
    assert manifest["original_preparation_state"]["review_evidence_status"] == data["assessment"]["evidence_assessment_status"]
    assert manifest["original_preparation_state"]["review_blockers"] == data["assessment"]["blockers"]
    assert manifest["original_preparation_state"]["review_blockers"]
    assert all(value is False for value in manifest["authority"].values())
    assert validate(data, preparation) == preparation


@pytest.mark.parametrize("field,value", [
    ("expected_corpus_preparation_sha256", "0" * 64),
    ("expected_assessment_file_sha256", "A" * 64),
    ("expected_corpus_preparation_sha256", True),
    ("toolchain", TOOLCHAIN + "\n"), ("toolchain", "leanprover/lean4:latest"),
])
def test_independent_commitments_and_toolchain_refuse_before_owners(base, field, value):
    data, _ = base
    with patch.object(owner, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            prepare(data, **{field: value})


@pytest.mark.parametrize("damage", ["raw_html", "review", "dependency", "component", "assessment"])
def test_full_original_source_review_and_dependency_inputs_are_replayed(base, damage):
    original, _ = base
    data = deepcopy(original)
    inputs = data["review_inputs"]
    if damage == "raw_html":
        source = inputs["use_inputs"]["donor_evidence_inputs"]["candidate_inputs"]
        source["raw_html"] += b" changed original source"
    elif damage == "review": inputs["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    elif damage == "dependency":
        key = next(iter(inputs["observed_artifact_sha256s"]))
        inputs["observed_artifact_sha256s"][key] = "0" * 64
    elif damage == "component":
        record = json.loads(inputs["component_raw"])
        record["alias_record"]["assumed_not_proved"] = False
        inputs["component_raw"] = canonical(record)
    else: data["assessment_raw"] += b" changed transport"
    with pytest.raises(ValueError):
        prepare(data)


@pytest.mark.parametrize("damage", ["original_lean", "drop_role", "swap_roles", "theorem", "authority", "new_root", "semantics", "fragment_pin", "cache_promotion"])
def test_resealed_complete_project_cannot_retarget_original_or_preservation_obligations(base, damage):
    data, original = base
    manifest, files = meta(original), dict(original.files)
    old_modules = data["corpus_preparation"].to_dict()["expected_modules"]
    if damage == "original_lean":
        path = old_modules[1].replace(".", "/") + ".lean"
        files[path] = files[path].replace("↔", "→", 1)
    elif damage == "drop_role": manifest["preservation_fragments"].pop(2)
    elif damage == "swap_roles": manifest["preservation_fragments"][0], manifest["preservation_fragments"][1] = manifest["preservation_fragments"][1], manifest["preservation_fragments"][0]
    elif damage == "theorem": manifest["preservation_theorems"][-1] = "Foreign.fake"
    elif damage == "authority": manifest["proof_authority"] = True
    elif damage == "new_root": files["LegalCorpusV2Preservation.lean"] = "import " + old_modules[-1] + "\n"
    elif damage == "semantics":
        path = next(name for name, text in files.items() if "inductive UnaryFOL" in text)
        files[path] = files[path].replace(".implication", ".equivalence", 1)
    elif damage == "fragment_pin": manifest["preservation_fragments"][0]["foreign_fragment_pin"] = "0" * 64
    else:
        reference = manifest["reference_contract"]
        reference["legal_proof_cache_compatible"] = reference["proof_cache_admission_verified"] = True
        manifest["reference_contract"] = contracts.seal_record({key: value for key, value in reference.items()
                                                               if key not in {"record_cid", "cid_scope"}})
    changed = reseal(original, manifest, files)
    with pytest.raises(ValueError):
        validate(data, changed)


@pytest.mark.parametrize("damage", ["mutable_assessment", "oversize_assessment", "duplicate_assessment", "nonfinite_assessment", "extra_review_field"])
def test_bounded_closed_transport_refuses_before_lazy_operation_imports(base, damage):
    original, _ = base
    data = deepcopy(original)
    if damage == "mutable_assessment": data["assessment_raw"] = bytearray(data["assessment_raw"])
    elif damage == "oversize_assessment": data["assessment_raw"] = b" " * (1024**2 + 1)
    elif damage == "duplicate_assessment": data["assessment_raw"] = b'{"schema":"a","schema":"b"}'
    elif damage == "nonfinite_assessment": data["assessment_raw"] = b'{"bad":NaN}'
    else: data["review_inputs"]["unknown"] = None
    data["expected_assessment_file_sha256"] = sha(data["assessment_raw"])
    with patch.object(owner, "_owners", side_effect=AssertionError("lazy owners reached")):
        with pytest.raises(ValueError):
            prepare(data)


def test_preparation_does_not_execute_native_or_duckdb_engines(base):
    data, _ = base
    with patch.object(subprocess, "run", side_effect=AssertionError("process reached")), patch.object(
        subprocess, "Popen", side_effect=AssertionError("process reached")
    ):
        preparation = prepare(data)
        assert validate(data, preparation) == preparation


def test_warm_preservation_cache_rechecks_non_direct_native_producer(base, monkeypatch):
    data, _ = base
    prepared = prepare(data)
    from ipfs_datasets_py.logic.autoformal import legal_pilot_lake
    target = Path(legal_pilot_lake.__file__).resolve()
    assert target not in {Path(module.__file__).resolve() for module in owner._owners()}
    original = Path.read_bytes
    observed = []
    def changed(path):
        raw = original(path)
        if path.resolve() == target:
            observed.append(str(target))
            return raw + b"\n# changed transitive producer fixture\n"
        return raw
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError):
        prepare(data)
    assert observed
    assert type(prepared) is owner.DefinitionUsePreservationPreparation

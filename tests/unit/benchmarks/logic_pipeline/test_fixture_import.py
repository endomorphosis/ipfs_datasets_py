"""Executable evidence for provenance-preserving fixture reuse."""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib
import json
from pathlib import Path
import shutil
from typing import Callable

import pytest

from benchmarks.logic_pipeline import fixture_import


FROZEN_MANIFEST_SHA256 = (
    "93bc8297c84b85a018305edc311c42d0df345978af767e4b93b1e509d974a0fd"
)


def _manifest_value(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_canonical(path: Path, value: object) -> str:
    raw = (fixture_import.canonical_json(value) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _copy_import_tree(tmp_path: Path) -> tuple[Path, Path]:
    repository_root = tmp_path / "repository"
    manifest_path = (
        repository_root
        / "tests"
        / "fixtures"
        / "logic_pipeline_benchmark"
        / "fixture_import_manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    shutil.copy2(fixture_import.DEFAULT_IMPORT_MANIFEST_PATH, manifest_path)
    manifest = _manifest_value(manifest_path)
    imports = manifest["imports"]
    assert isinstance(imports, list)
    for item in imports:
        assert isinstance(item, dict)
        relative = Path(item["source_path"])
        destination = repository_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture_import.DEFAULT_REPOSITORY_ROOT / relative, destination)
    return repository_root, manifest_path


def _rewrite_manifest(
    manifest_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> str:
    manifest = _manifest_value(manifest_path)
    mutate(manifest)
    imports = manifest["imports"]
    assert isinstance(imports, list)
    manifest["imports_sha256"] = hashlib.sha256(
        fixture_import.canonical_json(imports).encode("utf-8")
    ).hexdigest()
    return _write_canonical(manifest_path, manifest)


def _entry(
    manifest: dict[str, object],
    import_id: str,
) -> dict[str, object]:
    imports = manifest["imports"]
    assert isinstance(imports, list)
    matches = [
        item
        for item in imports
        if isinstance(item, dict) and item.get("import_id") == import_id
    ]
    assert len(matches) == 1
    return matches[0]


def test_objective_evidence_and_frozen_manifest_identity_are_stable() -> None:
    assert (
        fixture_import.HSSLEV0217E25()
        == "provenance-preserving existing regression and ambiguity fixture imports"
    )
    assert fixture_import.FIXTURE_IMPORT_SCHEMA.endswith(".fixture-import.v1")
    assert fixture_import.FIXTURE_IMPORT_MANIFEST_SCHEMA.endswith(
        ".fixture-import-manifest.v1"
    )
    assert (
        fixture_import.FROZEN_IMPORT_MANIFEST_SHA256
        == FROZEN_MANIFEST_SHA256
    )
    assert (
        hashlib.sha256(
            fixture_import.DEFAULT_IMPORT_MANIFEST_PATH.read_bytes()
        ).hexdigest()
        == FROZEN_MANIFEST_SHA256
    )


def test_default_imports_cover_every_required_existing_fixture_family() -> None:
    imported = fixture_import.load_fixture_imports()

    assert imported.manifest.import_count == len(imported.fixtures) == 9
    assert imported.manifest_sha256 == FROZEN_MANIFEST_SHA256
    assert dict(imported.manifest.family_counts) == {
        "legal_ir_ambiguity": 2,
        "fol_deontic_modal": 2,
        "hammer": 3,
        "leanstral": 2,
    }
    assert dict(imported.manifest.coverage_counts) == {
        "negative": 4,
        "positive": 5,
    }
    assert set(imported.by_id) == {
        "hammer-nat-add-comm",
        "hammer-poisoned-add-comm",
        "hammer-reconstruction-failed",
        "leanstral-invert-modality",
        "leanstral-remove-modal-cue",
        "legal-ir-conflict-waiver",
        "legal-ir-privacy-notice",
        "tdfol-obligation-window",
        "tdfol-prohibition",
    }


def test_literal_first_order_deontic_and_modal_coverage_is_explicit() -> None:
    imported = fixture_import.load_fixture_imports()
    fol_specs = [
        fixture.spec
        for fixture in imported.fixtures
        if fixture.spec.family is fixture_import.FixtureFamily.FOL_DEONTIC_MODAL
    ]
    tags = {tag for spec in fol_specs for tag in spec.semantic_tags}

    assert {"first_order", "deontic", "modal"} <= tags
    assert all(spec.coverage is fixture_import.Coverage.POSITIVE for spec in fol_specs)
    assert {
        fixture.payload["id"]
        for fixture in imported.fixtures
        if fixture.spec.family is fixture_import.FixtureFamily.FOL_DEONTIC_MODAL
    } == {"obligation_with_window", "prohibition_simple"}


def test_original_identifiers_source_references_and_payloads_are_preserved() -> None:
    imported = fixture_import.load_fixture_imports()

    for fixture in imported.fixtures:
        spec = fixture.spec
        assert fixture.payload[spec.identity_field] == spec.original_id
        assert spec.source_reference == (
            f"{spec.source_path}#{spec.identity_field}={spec.original_id}"
        )
        assert spec.expected_result_origin == "existing_fixture"
        assert spec.model_generated_expected_result is False

    privacy = imported.by_id["legal-ir-privacy-notice"]
    assert privacy.payload["packet_id"] == "external-expert-privacy-notice-001"
    assert privacy.payload["source_document_id"] == "privacy-act-552a-e4"
    ambiguity = privacy.payload["acceptable_ambiguity"]
    assert isinstance(ambiguity, Mapping)
    assert ambiguity["allowed"] is True

    theorem = imported.by_id["hammer-nat-add-comm"]
    assert theorem.payload["theorem_id"] == "Hammer.Nat.add_comm"
    assert theorem.payload["statement"] == (
        "theorem add_comm : forall a b : Nat, Nat.add a b = Nat.add b a"
    )

    mutation = imported.by_id["leanstral-invert-modality"]
    assert mutation.payload["original_text"] == (
        "The agency must provide notice within 30 days after application."
    )
    assert mutation.payload["mutated_text"] == (
        "The agency must not provide notice within 30 days after application."
    )
    assert mutation.payload["expected_hash_change"] is True


def test_positive_negative_ambiguity_hammer_and_regression_roles_survive() -> None:
    imported = fixture_import.load_fixture_imports()
    legal = [
        fixture.spec
        for fixture in imported.fixtures
        if fixture.spec.family is fixture_import.FixtureFamily.LEGAL_IR_AMBIGUITY
    ]
    hammer = [
        fixture.spec
        for fixture in imported.fixtures
        if fixture.spec.family is fixture_import.FixtureFamily.HAMMER
    ]
    leanstral = [
        fixture.spec
        for fixture in imported.fixtures
        if fixture.spec.family is fixture_import.FixtureFamily.LEANSTRAL
    ]

    assert all("ambiguity" in spec.semantic_tags for spec in legal)
    assert {spec.coverage for spec in hammer} == set(fixture_import.Coverage)
    assert all("regression" in spec.semantic_tags for spec in leanstral)
    assert all(
        spec.coverage is fixture_import.Coverage.NEGATIVE for spec in leanstral
    )


def test_imported_records_are_deeply_immutable_and_ordered() -> None:
    imported = fixture_import.load_fixture_imports()
    first = imported.fixtures[0]

    assert tuple(spec.ordinal for spec in imported.manifest.imports) == tuple(
        range(9)
    )
    assert tuple(imported.by_id) == tuple(
        fixture.spec.import_id for fixture in imported.fixtures
    )
    with pytest.raises(FrozenInstanceError):
        first.spec.original_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        first.payload["packet_id"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        imported.by_id["new"] = first  # type: ignore[index]
    with pytest.raises(TypeError):
        imported.manifest.family_counts["hammer"] = 0  # type: ignore[index]
    citations = first.payload["citations"]
    assert isinstance(citations, tuple)
    with pytest.raises(TypeError):
        citations[0]["citation"] = "changed"  # type: ignore[index]


def test_direct_record_construction_cannot_bypass_digest_or_immutability() -> None:
    imported = fixture_import.load_fixture_imports()
    source_manifest = imported.manifest
    family_counts = dict(source_manifest.family_counts)
    coverage_counts = dict(source_manifest.coverage_counts)
    rebuilt_manifest = fixture_import.FixtureImportManifest(
        manifest_id=source_manifest.manifest_id,
        version=source_manifest.version,
        import_count=source_manifest.import_count,
        family_counts=family_counts,
        coverage_counts=coverage_counts,
        imports_sha256=source_manifest.imports_sha256,
        imports=source_manifest.imports,
    )

    family_counts["hammer"] = 0
    coverage_counts["positive"] = 0
    assert rebuilt_manifest.family_counts["hammer"] == 3
    assert rebuilt_manifest.coverage_counts["positive"] == 5
    with pytest.raises(TypeError):
        rebuilt_manifest.family_counts["hammer"] = 0  # type: ignore[index]

    fixture = imported.by_id["hammer-reconstruction-failed"]
    tampered_payload = dict(fixture.payload)
    tampered_payload["case_type"] = "accepted_candidate"
    with pytest.raises(
        fixture_import.FixtureImportError,
        match="record_sha256",
    ):
        fixture_import.ImportedFixture(
            spec=fixture.spec,
            payload=tampered_payload,
        )


def test_repeated_loads_are_deterministic() -> None:
    first = fixture_import.load_fixture_imports()
    second = fixture_import.load_fixture_imports()

    assert first.manifest == second.manifest
    assert first.fixtures == second.fixtures
    assert tuple(first.by_id) == tuple(second.by_id)
    assert tuple(
        fixture.spec.record_sha256 for fixture in first.fixtures
    ) == tuple(fixture.spec.record_sha256 for fixture in second.fixtures)
    assert (
        fixture_import.FixtureImportSpec.from_mapping(
            first.manifest.imports[0].to_dict()
        )
        == first.manifest.imports[0]
    )
    assert (
        fixture_import.FixtureImportManifest.from_mapping(
            first.manifest.to_dict()
        )
        == first.manifest
    )
    with pytest.raises(
        fixture_import.FixtureImportError,
        match="manifest_sha256",
    ):
        replace(first, manifest_sha256="a" * 64)


def test_module_import_is_dependency_free_and_performs_no_fixture_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {
        "hammer",
        "ipfs_datasets_py",
        "leanstral",
        "spacy",
        "symai",
        "symbolicai",
    }
    real_import = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.partition(".")[0] in forbidden:
            raise AssertionError(f"unexpected optional import: {name}")
        return real_import(name, *args, **kwargs)

    def fail_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("module import must not read fixture data")

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(Path, "read_bytes", fail_read)
    reloaded = importlib.reload(fixture_import)
    assert reloaded.HSSLEV0217E25()


def test_manifest_byte_tampering_fails_against_code_pin(tmp_path: Path) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)
    raw = manifest_path.read_bytes()
    manifest_path.write_bytes(raw.replace(b"positive", b"negative", 1))

    with pytest.raises(
        fixture_import.FixtureImportError,
        match="manifest digest mismatch",
    ):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
        )


def test_source_byte_tampering_fails_before_record_use(tmp_path: Path) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)
    source_path = (
        repository_root
        / "tests"
        / "reasoner"
        / "fixtures"
        / "tdfol_conformance_cases.json"
    )
    raw = source_path.read_bytes()
    source_path.write_bytes(raw.replace(b"Company A", b"Company B", 1))

    with pytest.raises(
        fixture_import.FixtureImportError,
        match="source fixture digest mismatch",
    ):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
        )


def test_record_tampering_fails_even_with_rewritten_source_digest(
    tmp_path: Path,
) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)
    relative = Path("tests/reasoner/fixtures/tdfol_conformance_cases.json")
    source_path = repository_root / relative
    source = json.loads(source_path.read_text(encoding="utf-8"))
    assert isinstance(source, list) and isinstance(source[0], dict)
    source[0]["sentence"] = "Company B shall file report within 30 days."
    _write_canonical(source_path, source)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

    def update_source_digest(manifest: dict[str, object]) -> None:
        _entry(manifest, "tdfol-obligation-window")["source_sha256"] = source_sha256
        _entry(manifest, "tdfol-prohibition")["source_sha256"] = source_sha256

    reviewed_manifest_sha256 = _rewrite_manifest(
        manifest_path, update_source_digest
    )
    with pytest.raises(
        fixture_import.FixtureImportError,
        match="selected record digest mismatch",
    ):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
            expected_manifest_sha256=reviewed_manifest_sha256,
        )


def test_model_generated_expected_result_fails_even_with_rewritten_digests(
    tmp_path: Path,
) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)
    relative = Path("tests/fixtures/logic/modal/leanstral_mutations.json")
    source_path = repository_root / relative
    source = json.loads(source_path.read_text(encoding="utf-8"))
    assert isinstance(source, dict)
    mutations = source["mutations"]
    assert isinstance(mutations, list) and isinstance(mutations[0], dict)
    mutations[0]["model_generated_ground_truth"] = True
    _write_canonical(source_path, source)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    record_sha256 = hashlib.sha256(
        fixture_import.canonical_json(mutations[0]).encode("utf-8")
    ).hexdigest()

    def approve_all_outer_digests(manifest: dict[str, object]) -> None:
        for import_id in (
            "leanstral-invert-modality",
            "leanstral-remove-modal-cue",
        ):
            _entry(manifest, import_id)["source_sha256"] = source_sha256
        _entry(manifest, "leanstral-invert-modality")[
            "record_sha256"
        ] = record_sha256

    reviewed_manifest_sha256 = _rewrite_manifest(
        manifest_path, approve_all_outer_digests
    )
    with pytest.raises(
        fixture_import.FixtureImportError,
        match="model-generated expected result",
    ):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
            expected_manifest_sha256=reviewed_manifest_sha256,
        )


def test_ambiguous_source_selector_fails_closed(tmp_path: Path) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)
    relative = Path("tests/reasoner/fixtures/tdfol_conformance_cases.json")
    source_path = repository_root / relative
    source = json.loads(source_path.read_text(encoding="utf-8"))
    assert isinstance(source, list)
    source.append(source[0])
    _write_canonical(source_path, source)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

    def update_source_digest(manifest: dict[str, object]) -> None:
        _entry(manifest, "tdfol-obligation-window")["source_sha256"] = source_sha256
        _entry(manifest, "tdfol-prohibition")["source_sha256"] = source_sha256

    reviewed_manifest_sha256 = _rewrite_manifest(
        manifest_path, update_source_digest
    )
    with pytest.raises(
        fixture_import.FixtureImportError,
        match="exactly one record",
    ):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
            expected_manifest_sha256=reviewed_manifest_sha256,
        )


def test_manifest_rejects_model_attestation_path_traversal_and_unknown_fields(
    tmp_path: Path,
) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)

    def enable_model_result(manifest: dict[str, object]) -> None:
        _entry(manifest, "hammer-nat-add-comm")[
            "model_generated_expected_result"
        ] = True

    digest = _rewrite_manifest(manifest_path, enable_model_result)
    with pytest.raises(
        fixture_import.FixtureImportError,
        match="model-generated expected results are forbidden",
    ):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
            expected_manifest_sha256=digest,
        )

    traversal_root, manifest_path = _copy_import_tree(tmp_path / "traversal")

    def traverse(manifest: dict[str, object]) -> None:
        item = _entry(manifest, "hammer-nat-add-comm")
        item["source_path"] = "../outside.json"
        item["source_reference"] = (
            "../outside.json#theorem_id=Hammer.Nat.add_comm"
        )

    digest = _rewrite_manifest(manifest_path, traverse)
    with pytest.raises(fixture_import.FixtureImportError, match="source_path"):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=traversal_root,
            expected_manifest_sha256=digest,
        )

    unknown_root, manifest_path = _copy_import_tree(tmp_path / "unknown")

    def unknown(manifest: dict[str, object]) -> None:
        _entry(manifest, "hammer-nat-add-comm")["post_review_edit"] = True

    digest = _rewrite_manifest(manifest_path, unknown)
    with pytest.raises(fixture_import.FixtureImportError, match="unknown"):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=unknown_root,
            expected_manifest_sha256=digest,
        )


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    repository_root, manifest_path = _copy_import_tree(tmp_path)
    raw = manifest_path.read_bytes()
    duplicate = raw.replace(
        b'{"coverage_counts":',
        b'{"schema":"duplicate","coverage_counts":',
        1,
    )
    manifest_path.write_bytes(duplicate)

    with pytest.raises(fixture_import.FixtureImportError, match="duplicate JSON"):
        fixture_import.load_fixture_imports(
            manifest_path,
            repository_root=repository_root,
            expected_manifest_sha256=hashlib.sha256(duplicate).hexdigest(),
        )

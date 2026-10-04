"""Executable contract for the cross-repository logic capability census."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest


DATASETS_ROOT = Path(__file__).resolve().parents[4]
SUPERPROJECT_ROOT = DATASETS_ROOT.parent
MATRIX_PATH = (
    DATASETS_ROOT
    / "tests"
    / "fixtures"
    / "logic"
    / "software_verification"
    / "capability_matrix.json"
)
DOC_PATH = (
    DATASETS_ROOT
    / "docs"
    / "logic"
    / "software_verification_capability_inventory.md"
)
MATRIX = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

EXPECTED_CATEGORIES = {
    "adapter",
    "authority_role",
    "compiler",
    "conformance_suite",
    "installer",
    "logic_family",
    "probe",
    "provider",
    "public_access_path",
}
EXPECTED_FAMILIES = {
    "cec_dcec",
    "deontic",
    "flogic",
    "fol",
    "intent_ir",
    "legal_ir",
    "modal",
    "security_ir",
    "tdfol",
}
EXPECTED_PUBLIC_CHANNELS = {
    "cli",
    "mcp",
    "provider_protocol",
    "python",
}
EXPECTED_IDS = (
    "adapter.cross_logic_bridges",
    "adapter.domain_formalization",
    "adapter.external_atp_smt",
    "adapter.itp_frontends",
    "adapter.supervisor_ipfs_datasets",
    "adapter.supervisor_program_ast",
    "authority.attestation",
    "authority.capability_health",
    "authority.kernel_reconstruction",
    "authority.proposal_candidate",
    "authority.solver_evidence",
    "compiler.backend_smt",
    "compiler.formalization",
    "compiler.hammer_translation",
    "compiler.legacy_family_converters",
    "compiler.modal",
    "conformance.api_v1",
    "conformance.capability_probes",
    "conformance.hammer",
    "conformance.ir_families",
    "conformance.provider_protocol",
    "family.cec_dcec",
    "family.deontic",
    "family.flogic",
    "family.fol",
    "family.intent_ir",
    "family.legal_ir",
    "family.modal",
    "family.security_ir",
    "family.tdfol",
    "installer.lazy_external_provers",
    "installer.prover_cli",
    "probe.hammer_environment",
    "probe.logic_pipeline",
    "probe.mcp_capabilities",
    "probe.supervisor",
    "provider.backend_registry",
    "provider.cec_tdfol_native",
    "provider.external_router",
    "provider.flogic",
    "provider.hammer",
    "provider.itp_kernels",
    "provider.knowledge_graphs",
    "provider.learned_proposals",
    "provider.supervisor_protocol",
    "provider.zkp_backends",
    "public.cli_logic",
    "public.cli_prover_installer",
    "public.mcp_logic",
    "public.python_logic_api",
    "public.supervisor_provider",
)
ENTRY_KEYS = {
    "access",
    "category",
    "component",
    "evidence",
    "families",
    "id",
    "layer",
    "notes",
    "repository_paths",
    "states",
}
STATE_KEYS = {
    "authoritative_for",
    "canary",
    "declared",
    "discoverable",
    "installed",
    "reconstruction_capable",
    "shadow",
    "smoke_tested",
    "translation_conformant",
}
EVIDENCE_KEYS = {
    "reconstruction",
    "smoke_tests",
    "translation_conformance",
}
INSTALLATION_STATES = {
    "declared_only",
    "installed",
    "not_applicable",
    "runtime_probed",
}
PROOF_AUTHORITY_CLAIMS = {
    "bounded_solver_outcome",
    "kernel_checked_proof",
    "source_translation",
}


def _is_sorted_unique_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item for item in value)
        and value == sorted(set(value))
    )


def _repo_path_error(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return "must be a non-empty string"
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        return "must be a normalized superproject-relative POSIX path"
    return None


def _matrix_errors(matrix: Any, *, check_files: bool = True) -> list[str]:
    """Return every schema and cross-field violation in a matrix payload."""

    errors: list[str] = []
    if not isinstance(matrix, dict):
        return ["matrix must be an object"]

    expected_top_level = [
        "schema_version",
        "interface",
        "description",
        "scope",
        "state_definitions",
        "authority_claims",
        "entries",
        "documentation_anchors",
    ]
    if list(matrix) != expected_top_level:
        errors.append("top-level fields or field order do not match the v1 contract")
    if matrix.get("schema_version") != "logic-capability-matrix/v1":
        errors.append("unsupported schema_version")
    if matrix.get("interface") != "LogicCapabilityMatrix@1":
        errors.append("unsupported interface")

    scope = matrix.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope must be an object")
        scope = {}
    if set(scope.get("required_categories", ())) != EXPECTED_CATEGORIES:
        errors.append("scope.required_categories does not cover the reviewed census")
    if scope.get("layers") != ["datasets", "supervisor", "cross_repository"]:
        errors.append("scope.layers does not match the reviewed layer vocabulary")
    if scope.get("path_root") != "superproject":
        errors.append("scope.path_root must be superproject")

    state_definitions = matrix.get("state_definitions")
    if not isinstance(state_definitions, dict) or set(state_definitions) != STATE_KEYS:
        errors.append("state_definitions must define every maturity state exactly once")
    authority_claims = matrix.get("authority_claims")
    if not isinstance(authority_claims, dict) or not authority_claims:
        errors.append("authority_claims must be a non-empty closed vocabulary")
        authority_claims = {}

    entries = matrix.get("entries")
    if not isinstance(entries, list):
        return [*errors, "entries must be an array"]
    ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
    if tuple(ids) != EXPECTED_IDS:
        errors.append("entry IDs are incomplete, duplicated, renamed, or unsorted")

    observed_categories: set[str] = set()
    observed_families: set[str] = set()
    observed_channels: set[str] = set()
    observed_installation_states: set[str] = set()
    observed_boolean_values = {
        name: set()
        for name in (
            "discoverable",
            "reconstruction_capable",
            "shadow",
            "translation_conformant",
        )
    }

    for index, entry in enumerate(entries):
        prefix = (
            str(entry.get("id", f"entries[{index}]"))
            if isinstance(entry, dict)
            else f"entries[{index}]"
        )
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: entry must be an object")
            continue
        if set(entry) != ENTRY_KEYS:
            errors.append(f"{prefix}: fields do not match the entry contract")

        category = entry.get("category")
        if category not in EXPECTED_CATEGORIES:
            errors.append(f"{prefix}: unknown category {category!r}")
        else:
            observed_categories.add(category)
        if entry.get("layer") not in {"datasets", "supervisor", "cross_repository"}:
            errors.append(f"{prefix}: unknown layer")
        if not isinstance(entry.get("component"), str) or not entry["component"].strip():
            errors.append(f"{prefix}: component must be non-empty")
        if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
            errors.append(f"{prefix}: notes must be non-empty")

        families = entry.get("families")
        if not _is_sorted_unique_strings(families):
            errors.append(f"{prefix}: families must be sorted unique strings")
            families = []
        unknown_families = set(families) - EXPECTED_FAMILIES
        if unknown_families:
            errors.append(f"{prefix}: unknown families {sorted(unknown_families)!r}")
        observed_families.update(families)
        if category == "logic_family" and len(families) != 1:
            errors.append(f"{prefix}: logic-family rows must name exactly one family")

        paths = entry.get("repository_paths")
        if not _is_sorted_unique_strings(paths) or not paths:
            errors.append(f"{prefix}: repository_paths must be non-empty and sorted")
            paths = []

        states = entry.get("states")
        if not isinstance(states, dict) or set(states) != STATE_KEYS:
            errors.append(f"{prefix}: states do not match the maturity contract")
            states = {}
        for name in (
            "canary",
            "declared",
            "discoverable",
            "reconstruction_capable",
            "shadow",
            "smoke_tested",
            "translation_conformant",
        ):
            if not isinstance(states.get(name), bool):
                errors.append(f"{prefix}: states.{name} must be a boolean")
            elif name in observed_boolean_values:
                observed_boolean_values[name].add(states[name])
        if states.get("declared") is not True:
            errors.append(f"{prefix}: every matrix row must be explicitly declared")

        installed = states.get("installed")
        if installed not in INSTALLATION_STATES:
            errors.append(f"{prefix}: states.installed is invalid")
        else:
            observed_installation_states.add(installed)
        if installed in {"installed", "runtime_probed"} and not paths:
            errors.append(f"{prefix}: installed/runtime-probed rows need a source path")

        authoritative_for = states.get("authoritative_for")
        if not _is_sorted_unique_strings(authoritative_for):
            errors.append(
                f"{prefix}: states.authoritative_for must be sorted unique strings"
            )
            authoritative_for = []
        unknown_claims = set(authoritative_for) - set(authority_claims)
        if unknown_claims:
            errors.append(
                f"{prefix}: unknown authority claims {sorted(unknown_claims)!r}"
            )
        if states.get("shadow") and authoritative_for:
            errors.append(f"{prefix}: shadow rows must not claim authority")
        if states.get("canary") and set(authoritative_for) & PROOF_AUTHORITY_CLAIMS:
            errors.append(f"{prefix}: canary rows must not claim proof authority")

        evidence = entry.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_KEYS:
            errors.append(f"{prefix}: evidence does not match the evidence contract")
            evidence = {}
        for evidence_name in EVIDENCE_KEYS:
            evidence_paths = evidence.get(evidence_name)
            if not _is_sorted_unique_strings(evidence_paths):
                errors.append(
                    f"{prefix}: evidence.{evidence_name} must be sorted unique paths"
                )
                evidence[evidence_name] = []
        for state_name, evidence_name in (
            ("smoke_tested", "smoke_tests"),
            ("translation_conformant", "translation_conformance"),
            ("reconstruction_capable", "reconstruction"),
        ):
            has_evidence = bool(evidence.get(evidence_name))
            if states.get(state_name) is not has_evidence:
                errors.append(
                    f"{prefix}: states.{state_name} disagrees with "
                    f"evidence.{evidence_name}"
                )

        access = entry.get("access")
        if not isinstance(access, list):
            errors.append(f"{prefix}: access must be an array")
            access = []
        if category == "public_access_path" and len(access) != 1:
            errors.append(f"{prefix}: public access rows require exactly one route")
        if category != "public_access_path" and access:
            errors.append(f"{prefix}: only public access rows may declare routes")
        for route in access:
            if not isinstance(route, dict) or set(route) != {
                "channel",
                "path",
                "symbol",
                "target",
            }:
                errors.append(f"{prefix}: public route fields are invalid")
                continue
            channel = route.get("channel")
            if channel not in EXPECTED_PUBLIC_CHANNELS:
                errors.append(f"{prefix}: unknown public channel {channel!r}")
            else:
                observed_channels.add(channel)
            if route.get("path") not in paths:
                errors.append(f"{prefix}: public route path is not a repository path")
            if not isinstance(route.get("target"), str) or not route["target"].strip():
                errors.append(f"{prefix}: public route target must be non-empty")
            if not isinstance(route.get("symbol"), str) or not route["symbol"].isidentifier():
                errors.append(f"{prefix}: public route symbol must be an identifier")

        all_paths = [
            *paths,
            *(
                path
                for evidence_name in EVIDENCE_KEYS
                for path in evidence.get(evidence_name, ())
            ),
            *(route.get("path") for route in access if isinstance(route, dict)),
        ]
        for raw_path in all_paths:
            path_error = _repo_path_error(raw_path)
            if path_error:
                errors.append(f"{prefix}: path {raw_path!r} {path_error}")
            elif check_files and not (SUPERPROJECT_ROOT / raw_path).is_file():
                errors.append(f"{prefix}: stale repository path {raw_path!r}")

    if observed_categories != EXPECTED_CATEGORIES:
        errors.append("entries do not cover every required category")
    if observed_families != EXPECTED_FAMILIES:
        errors.append("entries do not cover every reviewed logic family")
    if observed_channels != EXPECTED_PUBLIC_CHANNELS:
        errors.append("entries do not cover every reviewed public channel")
    if not {"not_applicable", "runtime_probed"} <= observed_installation_states:
        errors.append("matrix does not distinguish source and runtime installation")
    for state_name, values in observed_boolean_values.items():
        if values != {False, True}:
            errors.append(f"matrix does not distinguish both {state_name} states")
    return errors


def _statically_defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.rpartition(".")[2] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
    return names


def test_matrix_schema_coverage_and_cross_field_consistency() -> None:
    assert _matrix_errors(MATRIX) == []


def test_all_public_access_symbols_resolve_statically_without_import_side_effects() -> None:
    for entry in MATRIX["entries"]:
        for route in entry["access"]:
            source = SUPERPROJECT_ROOT / route["path"]
            assert route["symbol"] in _statically_defined_names(source), (
                f"{entry['id']}: {route['symbol']!r} is stale in {route['path']}"
            )


def test_documentation_is_complete_and_tracks_every_matrix_row() -> None:
    documentation = DOC_PATH.read_text(encoding="utf-8")
    assert "`LogicCapabilityMatrix@1`" in documentation
    assert "`logic-capability-matrix/v1`" in documentation
    for anchor in MATRIX["documentation_anchors"]:
        assert anchor in documentation
    for entry_id in EXPECTED_IDS:
        assert f"`{entry_id}`" in documentation
    for state_name in STATE_KEYS:
        assert f"`{state_name}`" in documentation
    for claim in MATRIX["authority_claims"]:
        assert f"`{claim}`" in documentation


@pytest.mark.parametrize(
    ("entry_id", "mutation", "expected_error"),
    [
        (
            "provider.learned_proposals",
            lambda entry: entry["states"].update(
                {"authoritative_for": ["kernel_checked_proof"]}
            ),
            "shadow rows must not claim authority",
        ),
        (
            "compiler.backend_smt",
            lambda entry: entry["evidence"].update({"translation_conformance": []}),
            "states.translation_conformant disagrees",
        ),
        (
            "provider.itp_kernels",
            lambda entry: entry["repository_paths"].append(
                "ipfs_datasets_py/ipfs_datasets_py/logic/does_not_exist.py"
            ),
            "repository_paths must be non-empty and sorted",
        ),
    ],
)
def test_inconsistent_metadata_is_rejected(
    entry_id: str,
    mutation: Any,
    expected_error: str,
) -> None:
    mutated = deepcopy(MATRIX)
    entry = next(item for item in mutated["entries"] if item["id"] == entry_id)
    mutation(entry)
    assert any(expected_error in error for error in _matrix_errors(mutated))


def test_stale_paths_are_rejected_even_when_metadata_is_otherwise_valid() -> None:
    mutated = deepcopy(MATRIX)
    entry = next(
        item for item in mutated["entries"] if item["id"] == "family.fol"
    )
    entry["repository_paths"] = [
        "ipfs_datasets_py/ipfs_datasets_py/logic/fol/stale.py"
    ]
    errors = _matrix_errors(mutated)
    assert any("stale repository path" in error for error in errors)

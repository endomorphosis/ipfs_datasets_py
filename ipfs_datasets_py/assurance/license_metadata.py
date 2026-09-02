"""Fail-closed PCPR-016 Datasets license metadata authority.

Make LICENSE, pyproject metadata, classifiers, README, wheels, and source
distributions agree. AGPL is the package license. Dual-license authority is
explicitly not granted. Historical MIT packaging metadata is not a grant.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live. Missing solvers stay typed
unavailable. Built wheel and sdist artifacts that are not present remain
typed unavailable and are not recorded as passing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsLicenseMetadata@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/license-authority@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/license-authority-verdict@1"
)
PCPR_016_TASK_ID: Final = "PCPR-016"
PCPR_016_GOAL_ID: Final = "PCPR-G230"
PCPR_015_TASK_ID: Final = "PCPR-015"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = (
    "proof-carrying-platform-qualification-and-release-v1"
)
EVIDENCE_ID: Final = "pcpr/datasets-license-metadata@1"

CANONICAL_SPDX: Final = "AGPL-3.0-only"
CANONICAL_LICENSE_FILE: Final = "LICENSE"
CANONICAL_LICENSE_TITLE: Final = "GNU AFFERO GENERAL PUBLIC LICENSE"
CANONICAL_LICENSE_VERSION: Final = "Version 3"
CANONICAL_CLASSIFIER: Final = (
    "License :: OSI Approved :: GNU Affero General Public License v3"
)
DUAL_LICENSE_AUTHORITY: Final = "none"
AUTHORITATIVE_SURFACES: Final[tuple[str, ...]] = (
    "LICENSE",
    "pyproject.toml",
    "setup.py",
    "README.md",
)

CLOSED_RELEASE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "release_candidate_qualified",
        "non_promoted_supervisor_unqualified",
        "non_promoted_import_or_false_success",
        "non_promoted_live_storage_gap",
        "non_promoted_live_compute_gap",
        "non_promoted_solver_gap",
        "non_promoted_packaging_gap",
        "non_promoted_dependency_reproducibility",
        "non_promoted_security_failure",
        "non_promoted_interoperability_gap",
        "non_promoted_reference_workflow_failure",
        "non_promoted_unmeasured",
        "non_promoted_operator_gate_required",
    }
)
PROMOTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "supervisor_promoted",
        "supervisor_non_promoted",
        "rnd_non_promoted",
        "typed_unavailable",
        "typed_blocked",
    }
)
EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "measured_live",
        "measured_hermetic",
        "estimated",
        "simulated",
        "unavailable",
    }
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_016_license_metadata.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"

MANIFEST_LICENSE_LINE: Final = "include LICENSE"
SETUPTOOLS_LICENSE_FILES: Final = ("LICENSE",)

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "license_file_is_agpl_v3",
        "pyproject_license_agrees",
        "setup_classifier_agrees",
        "setup_license_field_agrees",
        "readme_license_agrees",
        "dual_license_not_granted",
        "mit_not_authoritative",
        "manifest_in_includes_license",
        "setuptools_ships_license_file",
        "distribution_metadata_declared_to_agree",
        "egg_info_license_agrees",
        "manifest_advertises_license_metadata",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "dual_license_granted",
        "mit_authoritative",
        "simulated_results_represented_as_live",
        "runtime_unavailable_represented_as_live",
        "built_wheel_represented_as_live",
        "built_sdist_represented_as_live",
    }
)

RESIDUAL_MIT_DOCUMENTATION: Final[tuple[str, ...]] = (
    "docs/guides/FINANCE_WORKFLOW_GUIDE.md",
    "docs/tdfol/_build/html/_sources/index.rst.txt",
    "docs/tdfol/_build/html/_sources/license.rst.txt",
    "docs/archive/root_status_reports/EXTERNAL_PROVER_INTEGRATION.md",
    "ipfs_datasets_py/processors/multimedia/omni_converter_mk2/README.md",
)

_CLASSIFIER_RE: Final = re.compile(
    r"""['"]License :: OSI Approved :: ([^'"]+)['"]"""
)
_SETUP_LICENSE_RE: Final = re.compile(
    r"""(?m)^\s*license\s*=\s*['"]([^'"]+)['"]"""
)
_README_HEADING_RE: Final = re.compile(
    r"^##[^\n]*\bLicense\b[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)
_MIT_LICENSE_GRANT_RE: Final = re.compile(
    r"Permission is hereby granted, free of charge, to any person obtaining a copy",
)
_POSITIVE_DUAL_RE: Final = re.compile(
    r"(?:dual[- ]licen(?:se|sed)\s+under|(?:MIT|Expat)\s+OR\s+AGPL|AGPL\s+OR\s+(?:MIT|Expat)|SPDX-License-Identifier:\s*(?:MIT|Expat)\s+OR)",
    re.IGNORECASE,
)
_NEGATED_DUAL_RE: Final = re.compile(
    r"(?:not dual-licensed|dual-license(?: authority)? is not granted|dual_license_authority[\"']?\s*[:=]\s*[\"']none[\"'])",
    re.IGNORECASE,
)

_CID_RE: Final = re.compile(r"^b[a-z2-7]+$")


class LicenseMetadataError(Exception):
    """Fail-closed PCPR-016 contract error."""


class LicenseMetadataAdmissionError(LicenseMetadataError):
    """Raised when license metadata is rejected."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """CIDv1 DAG-JSON/sha2-256 identity (baguqeera…)."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def discover_datasets_root(start: Path | None = None) -> Path | None:
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ipfs_datasets_py").is_dir() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    return None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LicenseMetadataError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise LicenseMetadataError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise LicenseMetadataError(
            f"{name} must not be a closed PCPR release outcome"
        )


def license_authority_manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "interface": INTERFACE,
        "spdx": CANONICAL_SPDX,
        "license_file": CANONICAL_LICENSE_FILE,
        "classifier": CANONICAL_CLASSIFIER,
        "dual_license_authority": DUAL_LICENSE_AUTHORITY,
        "authoritative_surfaces": list(AUTHORITATIVE_SURFACES),
        "import_side_effects": "none",
        "task_id": PCPR_016_TASK_ID,
        "goal_id": PCPR_016_GOAL_ID,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_license_file(text: str) -> dict[str, Any]:
    body = _text(text, "LICENSE")
    title_ok = CANONICAL_LICENSE_TITLE in body
    version_ok = CANONICAL_LICENSE_VERSION in body
    mit_grant = bool(_MIT_LICENSE_GRANT_RE.search(body))
    if title_ok and version_ok and not mit_grant:
        spdx = CANONICAL_SPDX
        family = "AGPL-3.0"
    elif mit_grant and "GNU AFFERO GENERAL PUBLIC LICENSE" not in body:
        spdx = "MIT"
        family = "MIT"
    else:
        spdx = "unresolved"
        family = "unresolved"
    return {
        "family": family,
        "spdx": spdx,
        "title_present": title_ok,
        "version_present": version_ok,
        "mit_grant_present": mit_grant,
        "agrees": spdx == CANONICAL_SPDX,
    }


def parse_pyproject_license(text: str) -> dict[str, Any]:
    payload = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(payload, dict):
        raise LicenseMetadataError("pyproject.toml must be a table")
    project = payload.get("project")
    if not isinstance(project, dict):
        raise LicenseMetadataError("pyproject.toml [project] is required")
    license_value = project.get("license")
    spdx: str | None = None
    file_name: str | None = None
    form = "missing"
    if isinstance(license_value, str):
        form = "spdx-string"
        spdx = license_value.strip()
    elif isinstance(license_value, dict):
        raw_text = license_value.get("text")
        raw_file = license_value.get("file")
        if isinstance(raw_text, str) and raw_text.strip():
            form = "text"
            spdx = raw_text.strip()
        if isinstance(raw_file, str) and raw_file.strip():
            form = "file" if form == "missing" else form
            file_name = raw_file.strip()
            if spdx is None and file_name == CANONICAL_LICENSE_FILE:
                spdx = CANONICAL_SPDX
    tool = payload.get("tool")
    license_files: tuple[str, ...] = ()
    if isinstance(tool, dict):
        setuptools = tool.get("setuptools")
        if isinstance(setuptools, dict):
            raw_files = setuptools.get("license-files")
            if isinstance(raw_files, list):
                license_files = tuple(
                    str(item).strip()
                    for item in raw_files
                    if isinstance(item, str) and str(item).strip()
                )
    classifiers = project.get("classifiers")
    project_classifiers: tuple[str, ...] = ()
    if isinstance(classifiers, list):
        project_classifiers = tuple(
            str(item)
            for item in classifiers
            if isinstance(item, str) and item.startswith("License ::")
        )
    agrees = spdx == CANONICAL_SPDX and (
        not project_classifiers
        or CANONICAL_CLASSIFIER in project_classifiers
    )
    return {
        "form": form,
        "spdx": spdx,
        "file": file_name,
        "license_files": list(license_files),
        "classifiers": list(project_classifiers),
        "agrees": agrees,
    }


def parse_setup_license(text: str) -> dict[str, Any]:
    body = _text(text, "setup.py")
    classifiers = tuple(_CLASSIFIER_RE.findall(body))
    fields = tuple(_SETUP_LICENSE_RE.findall(body))
    license_field = fields[-1] if fields else None
    agrees = (
        CANONICAL_CLASSIFIER.split(" :: ", 2)[-1] in classifiers
        or CANONICAL_CLASSIFIER in (
            f"License :: OSI Approved :: {item}" for item in classifiers
        )
    ) and license_field == CANONICAL_SPDX
    # Classifier regex captures the OSI-approved suffix, not the full string.
    agrees = classifiers == (
        "GNU Affero General Public License v3",
    ) and license_field == CANONICAL_SPDX
    return {
        "classifiers": [f"License :: OSI Approved :: {item}" for item in classifiers],
        "license_field": license_field,
        "agrees": agrees,
        "mit_classifier_present": any("MIT License" in item for item in classifiers),
    }


def parse_readme_license(text: str) -> dict[str, Any]:
    body = _text(text, "README.md")
    match = _README_HEADING_RE.search(body)
    if match is None:
        raise LicenseMetadataError("README.md is missing a License heading")
    start = match.end()
    nxt = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(body)
    section = body[start:end].strip()
    mentions_agpl = CANONICAL_SPDX in section
    mentions_file = "LICENSE" in section
    claims_mit = bool(
        re.search(r"licensed under the MIT\b", section, re.IGNORECASE)
    )
    dual_negated = bool(_NEGATED_DUAL_RE.search(section))
    dual_granted = bool(_POSITIVE_DUAL_RE.search(section)) and not dual_negated
    agrees = (
        mentions_agpl
        and mentions_file
        and not claims_mit
        and dual_negated
        and not dual_granted
        and CANONICAL_SPDX in section
    )
    return {
        "section": section,
        "mentions_agpl": mentions_agpl,
        "mentions_license_file": mentions_file,
        "claims_mit": claims_mit,
        "dual_license_granted": dual_granted,
        "dual_license_negated": dual_negated,
        "agrees": agrees,
    }


def parse_egg_info_license(text: str) -> dict[str, Any]:
    license_field = None
    license_file = None
    classifiers: list[str] = []
    for line in _text(text, "PKG-INFO").splitlines():
        if line.startswith("License: "):
            license_field = line.split(":", 1)[1].strip()
        elif line.startswith("License-File: "):
            license_file = line.split(":", 1)[1].strip()
        elif line.startswith("Classifier: License ::"):
            classifiers.append(line.split(":", 1)[1].strip())
    agrees = (
        license_field == CANONICAL_SPDX
        and (license_file in {None, CANONICAL_LICENSE_FILE})
        and (
            not classifiers
            or CANONICAL_CLASSIFIER in classifiers
        )
    )
    return {
        "license_field": license_field,
        "license_file": license_file,
        "classifiers": classifiers,
        "agrees": agrees,
    }


def _authoritative_bodies(root: Path) -> dict[str, str]:
    return {
        "LICENSE": _read_text(root / "LICENSE"),
        "pyproject.toml": _read_text(root / "pyproject.toml"),
        "setup.py": _read_text(root / "setup.py"),
        "README.md": _read_text(root / "README.md"),
    }


def _dual_license_granted(bodies: Mapping[str, str]) -> bool:
    for body in bodies.values():
        if _POSITIVE_DUAL_RE.search(body) and not _NEGATED_DUAL_RE.search(body):
            return True
    return False


def _mit_authoritative(parsed: Mapping[str, Mapping[str, Any]]) -> bool:
    license_file = parsed["license_file"]
    pyproject = parsed["pyproject"]
    setup = parsed["setup"]
    readme = parsed["readme"]
    if license_file.get("mit_grant_present") is True:
        return True
    if license_file.get("spdx") == "MIT":
        return True
    if pyproject.get("spdx") == "MIT":
        return True
    if setup.get("mit_classifier_present") is True:
        return True
    if setup.get("license_field") == "MIT":
        return True
    if readme.get("claims_mit") is True:
        return True
    return False


@dataclass(frozen=True)
class OutcomeProbe:
    probe_id: str
    present: bool | None
    evidence_kind: str
    live: bool
    simulated_represented_as_live: bool
    reason: str
    details: Mapping[str, Any] = MappingProxyType({})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "present": self.present,
            "evidence_kind": self.evidence_kind,
            "live": self.live,
            "simulated_represented_as_live": self.simulated_represented_as_live,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class LicenseMetadataVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    license_surfaces_agree: bool
    dual_license_authority: str
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    built_wheel_evidence_kind: str
    built_sdist_evidence_kind: str
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "license_surfaces_agree": self.license_surfaces_agree,
            "dual_license_authority": self.dual_license_authority,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "built_wheel_evidence_kind": self.built_wheel_evidence_kind,
            "built_sdist_evidence_kind": self.built_sdist_evidence_kind,
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _probe(
    probe_id: str,
    present: bool | None,
    *,
    reason: str,
    evidence_kind: str = "measured",
    live: bool = False,
    details: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind=evidence_kind,
        live=live,
        simulated_represented_as_live=False,
        reason=reason,
        details=MappingProxyType(dict(details or {})),
    )


def current_head_static_probes(
    start: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    probes: list[OutcomeProbe] = []
    if root is None:
        missing = "datasets source root was not found"
        for probe_id in sorted(REQUIRED_GOOD_PROBE_IDS):
            probes.append(_probe(probe_id, False, reason=missing))
        probes.extend(_terminal_negative_probes(root=None))
        return tuple(probes)

    try:
        bodies = _authoritative_bodies(root)
        license_parsed = parse_license_file(bodies["LICENSE"])
        pyproject_parsed = parse_pyproject_license(bodies["pyproject.toml"])
        setup_parsed = parse_setup_license(bodies["setup.py"])
        readme_parsed = parse_readme_license(bodies["README.md"])
    except (OSError, LicenseMetadataError, tomllib.TOMLDecodeError) as exc:
        for probe_id in sorted(REQUIRED_GOOD_PROBE_IDS):
            probes.append(_probe(probe_id, False, reason=str(exc)))
        probes.extend(_terminal_negative_probes(root=root))
        return tuple(probes)

    probes.append(
        _probe(
            "license_file_is_agpl_v3",
            license_parsed["agrees"] is True,
            reason=(
                "LICENSE is the GNU Affero General Public License v3 text"
                if license_parsed["agrees"]
                else "LICENSE is not GNU AGPL v3"
            ),
            details={
                "spdx": license_parsed["spdx"],
                "family": license_parsed["family"],
            },
        )
    )
    probes.append(
        _probe(
            "pyproject_license_agrees",
            pyproject_parsed["agrees"] is True,
            reason=(
                "pyproject.toml license metadata is AGPL-3.0-only"
                if pyproject_parsed["agrees"]
                else "pyproject.toml license metadata does not agree with AGPL-3.0-only"
            ),
            details={
                "form": pyproject_parsed["form"],
                "spdx": pyproject_parsed["spdx"],
                "file": pyproject_parsed["file"],
            },
        )
    )
    classifier_ok = setup_parsed["classifiers"] == [CANONICAL_CLASSIFIER]
    probes.append(
        _probe(
            "setup_classifier_agrees",
            classifier_ok,
            reason=(
                "setup.py license classifier is GNU Affero General Public License v3"
                if classifier_ok
                else "setup.py license classifier does not agree"
            ),
            details={"classifiers": setup_parsed["classifiers"]},
        )
    )
    probes.append(
        _probe(
            "setup_license_field_agrees",
            setup_parsed["license_field"] == CANONICAL_SPDX,
            reason=(
                "setup.py license= is AGPL-3.0-only"
                if setup_parsed["license_field"] == CANONICAL_SPDX
                else "setup.py license= does not agree with AGPL-3.0-only"
            ),
            details={"license_field": setup_parsed["license_field"]},
        )
    )
    probes.append(
        _probe(
            "readme_license_agrees",
            readme_parsed["agrees"] is True,
            reason=(
                "README license section is AGPL-3.0-only and not dual-licensed"
                if readme_parsed["agrees"]
                else "README license section does not agree"
            ),
            details={
                "mentions_agpl": readme_parsed["mentions_agpl"],
                "claims_mit": readme_parsed["claims_mit"],
                "dual_license_granted": readme_parsed["dual_license_granted"],
                "dual_license_negated": readme_parsed["dual_license_negated"],
            },
        )
    )

    dual_granted = _dual_license_granted(bodies)
    probes.append(
        _probe(
            "dual_license_not_granted",
            dual_granted is False
            and DUAL_LICENSE_AUTHORITY == "none"
            and readme_parsed["dual_license_negated"] is True,
            reason=(
                "Dual-license authority is explicitly none"
                if dual_granted is False
                else "A dual-license grant is present on an authoritative surface"
            ),
            details={"dual_license_authority": DUAL_LICENSE_AUTHORITY},
        )
    )
    probes.append(
        _probe(
            "dual_license_granted",
            dual_granted,
            reason=(
                "No dual-license grant is present on authoritative surfaces"
                if dual_granted is False
                else "A dual-license grant is present"
            ),
        )
    )

    parsed = {
        "license_file": license_parsed,
        "pyproject": pyproject_parsed,
        "setup": setup_parsed,
        "readme": readme_parsed,
    }
    mit_auth = _mit_authoritative(parsed)
    probes.append(
        _probe(
            "mit_not_authoritative",
            mit_auth is False,
            reason=(
                "MIT is not the authoritative package license"
                if mit_auth is False
                else "MIT remains on an authoritative license surface"
            ),
        )
    )
    probes.append(
        _probe(
            "mit_authoritative",
            mit_auth,
            reason=(
                "MIT is not authoritative"
                if mit_auth is False
                else "MIT remains authoritative"
            ),
        )
    )

    manifest_text = ""
    manifest_ok = False
    try:
        manifest_text = _read_text(root / "MANIFEST.in")
        manifest_ok = MANIFEST_LICENSE_LINE in manifest_text.splitlines() or (
            MANIFEST_LICENSE_LINE in manifest_text
        )
    except OSError as exc:
        probes.append(
            _probe(
                "manifest_in_includes_license",
                False,
                reason=str(exc),
            )
        )
    else:
        probes.append(
            _probe(
                "manifest_in_includes_license",
                manifest_ok,
                reason=(
                    "MANIFEST.in includes LICENSE"
                    if manifest_ok
                    else "MANIFEST.in does not include LICENSE"
                ),
            )
        )

    ships_license = CANONICAL_LICENSE_FILE in tuple(
        pyproject_parsed.get("license_files") or ()
    )
    probes.append(
        _probe(
            "setuptools_ships_license_file",
            ships_license,
            reason=(
                "setuptools license-files includes LICENSE"
                if ships_license
                else "setuptools license-files does not include LICENSE"
            ),
            details={
                "license_files": list(pyproject_parsed.get("license_files") or ())
            },
        )
    )

    declared_agree = (
        license_parsed["agrees"] is True
        and pyproject_parsed["agrees"] is True
        and setup_parsed["agrees"] is True
        and readme_parsed["agrees"] is True
        and mit_auth is False
        and dual_granted is False
        and manifest_ok
        and ships_license
    )
    probes.append(
        _probe(
            "distribution_metadata_declared_to_agree",
            declared_agree,
            reason=(
                "LICENSE, pyproject, setup.py, README, and license-file shipping agree on AGPL-3.0-only"
                if declared_agree
                else "Distribution license declarations do not yet agree"
            ),
            details={"spdx": CANONICAL_SPDX},
        )
    )

    egg_path = root / "ipfs_datasets_py.egg-info" / "PKG-INFO"
    if egg_path.is_file():
        try:
            egg_parsed = parse_egg_info_license(_read_text(egg_path))
            probes.append(
                _probe(
                    "egg_info_license_agrees",
                    egg_parsed["agrees"] is True,
                    reason=(
                        "Tracked egg-info PKG-INFO License field is AGPL-3.0-only"
                        if egg_parsed["agrees"]
                        else "Tracked egg-info PKG-INFO License field does not agree"
                    ),
                    details={
                        "license_field": egg_parsed["license_field"],
                        "license_file": egg_parsed["license_file"],
                    },
                )
            )
        except (OSError, LicenseMetadataError) as exc:
            probes.append(
                _probe("egg_info_license_agrees", False, reason=str(exc))
            )
    else:
        probes.append(
            _probe(
                "egg_info_license_agrees",
                False,
                reason="Tracked egg-info PKG-INFO is absent",
            )
        )

    residual_hits: list[str] = []
    for relpath in RESIDUAL_MIT_DOCUMENTATION:
        path = root / relpath
        if not path.is_file():
            continue
        try:
            body = _read_text(path)
        except OSError:
            continue
        if re.search(r"\bMIT License\b", body) or re.search(
            r"licensed under the MIT\b", body, re.IGNORECASE
        ):
            residual_hits.append(relpath)
    probes.append(
        _probe(
            "residual_nonauthoritative_mit_documentation",
            bool(residual_hits),
            reason=(
                "Non-authoritative documentation still mentions MIT; that is not a dual-license grant"
                if residual_hits
                else "No listed residual MIT documentation remains"
            ),
            details={"paths": residual_hits},
        )
    )

    manifest_ok_probe = False
    manifest_reason = (
        "LogicPlatformManifest does not advertise DatasetsLicenseMetadata@1"
    )
    try:
        from ipfs_datasets_py.logic.platform.manifest import (
            DEFAULT_LOGIC_PLATFORM_MANIFEST,
        )

        versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
        roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
        operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
        manifest_ok_probe = (
            versions.get(INTERFACE) == "1"
            and roots.get("datasets_license_metadata") == SCHEMA
            and operations.get("license_metadata") == "1"
        )
        if manifest_ok_probe:
            manifest_reason = (
                "LogicPlatformManifest advertises DatasetsLicenseMetadata@1."
            )
    except Exception as exc:  # pragma: no cover - import/shape failure is a probe
        manifest_reason = str(exc)
    probes.append(
        _probe(
            "manifest_advertises_license_metadata",
            manifest_ok_probe,
            reason=manifest_reason,
        )
    )

    probes.extend(_terminal_negative_probes(root=root))
    return tuple(probes)


def _terminal_negative_probes(*, root: Path | None) -> tuple[OutcomeProbe, ...]:
    dist_dir = (root / "dist") if root is not None else None
    wheels = ()
    sdists = ()
    if dist_dir is not None and dist_dir.is_dir():
        wheels = tuple(
            sorted(path.name for path in dist_dir.glob("*.whl") if path.is_file())
        )
        sdists = tuple(
            sorted(
                path.name
                for path in dist_dir.glob("*.tar.gz")
                if path.is_file()
            )
        )
    return (
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "runtime_unavailable_represented_as_live",
            False,
            reason="License metadata probes are not represented as live.",
        ),
        _probe(
            "built_wheel_represented_as_live",
            False,
            reason="No built wheel is represented as live qualification.",
        ),
        _probe(
            "built_sdist_represented_as_live",
            False,
            reason="No built sdist is represented as live qualification.",
        ),
        _probe(
            "built_wheel_metadata",
            None if not wheels else True,
            evidence_kind="unavailable" if not wheels else "measured",
            reason=(
                "No built wheel artifact is present in dist/; source declarations are the live evidence for this task."
                if not wheels
                else "Built wheel artifact names were observed locally and are not a published release."
            ),
            details={"artifacts": list(wheels)},
        ),
        _probe(
            "built_sdist_metadata",
            None if not sdists else True,
            evidence_kind="unavailable" if not sdists else "measured",
            reason=(
                "No built sdist artifact is present in dist/; source declarations are the live evidence for this task."
                if not sdists
                else "Built sdist artifact names were observed locally and are not a published release."
            ),
            details={"artifacts": list(sdists)},
        ),
        _probe(
            "live_solver_qualification",
            None,
            evidence_kind="unavailable",
            reason=(
                "This task does not qualify live solvers. Missing Z3/cvc5/Lean/Coq "
                "evidence stays typed unavailable and is not recorded as False or passing."
            ),
        ),
    )


def qualify_license_metadata(
    probes: Sequence[OutcomeProbe],
) -> LicenseMetadataVerdict:
    if not probes:
        raise LicenseMetadataError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise LicenseMetadataError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise LicenseMetadataError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in {
            "live_solver_qualification",
            "built_wheel_metadata",
            "built_sdist_metadata",
            "residual_nonauthoritative_mit_documentation",
        }:
            continue
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    agree = not blockers
    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    wheel_kind = next(
        (
            item.evidence_kind
            for item in normalized
            if item.probe_id == "built_wheel_metadata"
        ),
        "unavailable",
    )
    sdist_kind = next(
        (
            item.evidence_kind
            for item in normalized
            if item.probe_id == "built_sdist_metadata"
        ),
        "unavailable",
    )
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_016_TASK_ID,
        "goal_id": PCPR_016_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "license_surfaces_agree": agree,
        "dual_license_authority": DUAL_LICENSE_AUTHORITY,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "built_wheel_evidence_kind": wheel_kind,
        "built_sdist_evidence_kind": sdist_kind,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return LicenseMetadataVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        license_surfaces_agree=agree,
        dual_license_authority=DUAL_LICENSE_AUTHORITY,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        built_wheel_evidence_kind=wheel_kind,
        built_sdist_evidence_kind=sdist_kind,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_license_metadata() -> LicenseMetadataVerdict:
    return qualify_license_metadata(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeram2brcbor6mwzx3h3emwoy66xgtnmnb256ddgk4bvbipcdhadxc4a"
)


def pcpr_016_receipt_promotion(
    verdict: LicenseMetadataVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise LicenseMetadataError(
            "license metadata must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise LicenseMetadataError(
            "license metadata must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise LicenseMetadataError(
            "license metadata completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise LicenseMetadataError(
            "license metadata must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise LicenseMetadataError(
            "promotion_status must not be a closed release outcome"
        )
    if verdict.dual_license_authority != DUAL_LICENSE_AUTHORITY:
        raise LicenseMetadataError(
            "dual-license authority must remain explicit"
        )
    return verdict.to_mapping()


__all__ = [
    "AUTHORITATIVE_SURFACES",
    "CANONICAL_CLASSIFIER",
    "CANONICAL_LICENSE_FILE",
    "CANONICAL_SPDX",
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "DUAL_LICENSE_AUTHORITY",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "LicenseMetadataAdmissionError",
    "LicenseMetadataError",
    "LicenseMetadataVerdict",
    "OutcomeProbe",
    "PCPR_016_GOAL_ID",
    "PCPR_016_TASK_ID",
    "SCHEMA",
    "content_identity",
    "current_head_static_probes",
    "discover_datasets_root",
    "license_authority_manifest",
    "parse_egg_info_license",
    "parse_license_file",
    "parse_pyproject_license",
    "parse_readme_license",
    "parse_setup_license",
    "pcpr_016_receipt_promotion",
    "qualify_current_head_license_metadata",
    "qualify_license_metadata",
]

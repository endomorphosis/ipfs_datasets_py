#!/usr/bin/env python3
"""Build a deterministic, read-only inventory of tracked Security IR artifacts.

The inventory intentionally makes no authority decision between legacy
variants.  In particular, ``-new``, temporary, and mutable ``latest`` names are
grouped with their siblings and classified as ambiguous.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence


INTERFACE = "SecurityArtifactInventory@1"
SCHEMA_VERSION = "security-ir-artifact-inventory/v1"
DEFAULT_ARTIFACT_ROOT = PurePosixPath("security_ir_artifacts")
DEFAULT_OUTPUT = PurePosixPath(
    "docs/security_verification/security_ir_artifact_inventory.json"
)

CLASSIFICATIONS = (
    "source",
    "golden",
    "run_output",
    "promoted_evidence",
    "environment_record",
    "transient_compiler_output",
    "ambiguous",
    "unknown",
)

_FORMAL_SOURCE_FORMATS = {
    "coq_source",
    "lean_source",
    "proverif_source",
    "smtlib2_source",
    "tamarin_source",
    "tla_plus_source",
    "typescript_source",
}
_TRANSIENT_FORMATS = {
    "coq_auxiliary",
    "coq_compiled_object",
    "coq_compilation_marker",
    "coq_quick_compiled_object",
    "coq_symbol_table",
}
_RUN_NAME_MARKERS = (
    "-audit",
    "-decision",
    "-differential",
    "-health",
    "-lock",
    "-preflight",
    "-probe",
    "-report",
    "-reproduction",
    "-result",
    "-run",
    "-status",
    "-trace",
    "-verification",
    "-verdict",
)
_SOURCE_NAME_MARKERS = (
    "assumption",
    "campaign-manifest",
    "claim",
    "formalization-profile",
    "manifest",
    "mapping",
    "model-ir",
    "policy",
    "schema",
    "template",
)
_PROMOTED_NAME_MARKERS = (
    "assessment",
    "assurance",
    "coverage",
    "evidence",
    "packet",
)
_JSON_DECODE_FAILED = object()


class InventoryError(RuntimeError):
    """Raised when a complete, trustworthy inventory cannot be produced."""


def _as_repo_relative(path: str | PurePosixPath, *, label: str) -> PurePosixPath:
    """Validate and normalize a repository-relative POSIX path."""

    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or value == PurePosixPath("."):
        raise InventoryError(f"{label} must be a non-empty repository-relative path: {path}")
    return value


def tracked_artifact_paths(
    repo_root: Path,
    artifact_root: str | PurePosixPath = DEFAULT_ARTIFACT_ROOT,
) -> list[str]:
    """Return sorted Git-tracked files below *artifact_root*.

    Git is the authority for inventory scope because the migration plan calls
    for every tracked legacy artifact, not arbitrary local build output.
    """

    root = repo_root.resolve()
    relative_root = _as_repo_relative(artifact_root, label="artifact root")
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                os.fspath(root),
                "ls-files",
                "-z",
                "--",
                relative_root.as_posix(),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        message = detail.decode("utf-8", errors="replace").strip()
        raise InventoryError(
            f"could not enumerate tracked artifacts with Git{f': {message}' if message else ''}"
        ) from exc

    paths = [
        item.decode("utf-8", errors="surrogateescape")
        for item in completed.stdout.split(b"\0")
        if item
    ]
    return sorted(paths)


def _read_artifact(repo_root: Path, relative_path: PurePosixPath) -> bytes:
    candidate = repo_root.joinpath(*relative_path.parts)
    if candidate.is_symlink():
        return os.fsencode(os.readlink(candidate))
    if not candidate.is_file():
        raise InventoryError(f"tracked artifact is missing or is not a file: {relative_path}")
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise InventoryError(f"could not read tracked artifact {relative_path}: {exc}") from exc


def _decode_json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _JSON_DECODE_FAILED


def detect_format(path: str | PurePosixPath, data: bytes) -> str:
    """Detect an artifact format without optional platform dependencies."""

    relative_path = PurePosixPath(path)
    name = relative_path.name.lower()
    suffix = relative_path.suffix.lower()

    if suffix == ".json":
        parsed = _decode_json(data)
        if parsed is _JSON_DECODE_FAILED:
            return "invalid_json"
        if name.endswith(".schema.json"):
            return "json_schema"
        return "json"
    if suffix == ".md":
        return "markdown"
    if suffix == ".ts":
        return "typescript_source"
    if suffix in {".smt2", ".smt"}:
        return "smtlib2_source"
    if suffix == ".tla":
        return "tla_plus_source"
    if suffix == ".lean":
        return "lean_source"
    if suffix == ".v":
        return "coq_source"
    if suffix == ".pv":
        return "proverif_source"
    if suffix == ".spthy":
        return "tamarin_source"
    if suffix == ".cid":
        return "legacy_identifier"
    if suffix == ".aux":
        return "coq_auxiliary"
    if suffix == ".glob":
        return "coq_symbol_table"
    if suffix == ".vo":
        return "coq_compiled_object"
    if suffix == ".vos":
        return "coq_quick_compiled_object"
    if suffix == ".vok":
        return "coq_compilation_marker"
    if suffix == ".txt":
        return "plain_text_log"
    if b"\0" in data[:4096]:
        return "binary"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "plain_text"


def _identifier_representation(value: str) -> str:
    lowered = value.lower()
    if lowered.startswith("sha256:") and len(lowered) == 71:
        return "sha256_prefixed"
    if len(lowered) == 64 and all(character in "0123456789abcdef" for character in lowered):
        return "sha256_hex"
    if value.startswith("Qm"):
        return "cidv0"
    if lowered.startswith(("baf", "bag", "bafk", "bafy")):
        return "cidv1"
    return "opaque"


def _legacy_ids(
    path: PurePosixPath,
    data: bytes,
    parsed_json: Any,
) -> list[dict[str, str]]:
    identifiers: list[dict[str, str]] = []

    def add(field: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        normalized = value.strip()
        identifiers.append(
            {
                "field": field,
                "representation": _identifier_representation(normalized),
                "source_path": path.as_posix(),
                "value": normalized,
            }
        )

    if path.suffix.lower() == ".cid":
        try:
            for line_number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
                add(f"line:{line_number}", line)
        except UnicodeDecodeError:
            pass

    if isinstance(parsed_json, Mapping):
        for key in sorted(parsed_json):
            lowered = str(key).lower()
            if lowered in {"cid", "legacy_id"} or lowered.endswith("_cid"):
                value = parsed_json[key]
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        add(f"$.{key}[{index}]", item)
                else:
                    add(f"$.{key}", value)
            elif lowered == "legacy_ids" and isinstance(parsed_json[key], list):
                for index, item in enumerate(parsed_json[key]):
                    add(f"$.{key}[{index}]", item)

    return sorted(
        identifiers,
        key=lambda item: (item["source_path"], item["field"], item["value"]),
    )


def _variant_candidate(path: PurePosixPath) -> tuple[str, PurePosixPath] | None:
    name = path.name
    lowered = name.lower()
    suffix = path.suffix
    stem = path.stem

    if stem.lower().endswith("-new"):
        return "new_suffix", path.with_name(stem[:-4] + suffix)
    if stem.lower().endswith("_new"):
        return "new_suffix", path.with_name(stem[:-4] + suffix)
    if lowered.endswith((".tmp", ".temp", ".bak", ".orig", "~")):
        trimmed = name[:-1] if lowered.endswith("~") else name.rsplit(".", 1)[0]
        return "temporary_name", path.with_name(trimmed)
    for marker in (".tmp", ".temp", ".bak", ".orig"):
        if stem.lower().endswith(marker):
            return "temporary_name", path.with_name(stem[: -len(marker)] + suffix)
    if stem.lower().endswith(("-latest", "_latest")):
        return "mutable_latest_alias", path.with_name(stem[:-7] + suffix)
    return None


def find_variant_groups(paths: Iterable[str | PurePosixPath]) -> list[dict[str, Any]]:
    """Link ambiguous variant names to siblings without selecting authority."""

    path_set = {PurePosixPath(path) for path in paths}
    raw_groups: list[tuple[str, PurePosixPath, tuple[PurePosixPath, ...]]] = []
    for path in sorted(path_set):
        candidate = _variant_candidate(path)
        if candidate is None:
            continue
        kind, base = candidate
        members = tuple(sorted({path, base} & path_set))
        # Keep singleton groups too: the naming convention is ambiguous even
        # when its presumed sibling is absent from the tracked tree.
        raw_groups.append((kind, base, members))

    groups: list[dict[str, Any]] = []
    for index, (kind, base, members) in enumerate(
        sorted(set(raw_groups), key=lambda item: (item[1].as_posix(), item[0])),
        start=1,
    ):
        if kind == "new_suffix":
            reason = (
                "An unversioned `-new`/`_new` name has no manifest establishing "
                "lineage or authority relative to its sibling."
            )
        elif kind == "temporary_name":
            reason = (
                "A temporary-name artifact may be an incomplete or intermediate "
                "write and has no manifest establishing authority."
            )
        else:
            reason = (
                "A mutable `latest` alias does not identify an immutable run and "
                "has no manifest establishing authority."
            )
        groups.append(
            {
                "authority_selected": False,
                "base_path": base.as_posix(),
                "group_id": f"variant-{index:03d}",
                "kind": kind,
                "paths": [member.as_posix() for member in members],
                "reason": reason,
                "recommendation": (
                    "Retain every variant; review provenance and content before a "
                    "separate migration manifest selects or promotes anything."
                ),
            }
        )
    return groups


def _likely_producers(path: PurePosixPath, detected_format: str) -> list[str]:
    value = path.as_posix()
    name = path.name.lower()

    if "/_apalache-out/" in value:
        return ["Apalache model checker"]
    if detected_format in {
        "coq_auxiliary",
        "coq_compiled_object",
        "coq_compilation_marker",
        "coq_quick_compiled_object",
        "coq_symbol_table",
    }:
        return ["Coq compiler (coqc)"]
    if detected_format == "smtlib2_source":
        if "/tla/_apalache-out/" in value:
            return ["Apalache model checker"]
        return ["Security IR SMT-LIB compiler or solver workflow"]
    if detected_format == "coq_source":
        return ["Security IR Coq projection generator or repository author"]
    if detected_format == "lean_source":
        return ["Security IR Lean projection generator or repository author"]
    if detected_format == "proverif_source":
        return ["Security IR ProVerif projection generator"]
    if detected_format == "tamarin_source":
        return ["Security IR Tamarin projection generator"]
    if detected_format == "tla_plus_source":
        return ["Security IR TLA+ projection generator"]
    if detected_format == "typescript_source":
        return ["scripts/ops/security_verification/emit_security_typescript_schema.py"]
    if "fuzz" in path.parts or "counterexample" in value:
        return ["Security IR fuzzing or disproof workflow"]
    if "environment" in path.parts:
        return ["Security verification environment probe workflow"]
    if "recovery" in path.parts:
        return ["agent-supervisor recovery or artifact-retention workflow"]
    if name in {"security-model-ir.json", "security-model-ir.cid"}:
        if "testnet" in path.parts:
            return ["scripts/ops/security_verification/project_xaman_testnet_security_model.py"]
        return ["scripts/ops/security_verification/generate_xaman_security_model_ir.py"]
    if "source-claim" in name or "source-coverage" in name:
        return ["scripts/ops/security_verification/build_xaman_source_claim_coverage.py"]
    if "public-source-assessment" in name:
        return ["scripts/ops/security_verification/build_xaman_public_source_assessment.py"]
    if "solver-portfolio" in name:
        return ["Security IR solver portfolio workflow"]
    if "protocol" in path.parts or "protocol" in name:
        return ["Security IR protocol projection or verification workflow"]
    if any(marker in name for marker in ("report", "probe", "preflight", "verdict")):
        return ["Security verification report workflow"]
    if any(marker in name for marker in ("manifest", "policy", "schema", "template")):
        return ["repository authoring or Security IR artifact generator"]
    return ["unidentified legacy Security IR workflow"]


def _classify(
    path: PurePosixPath,
    detected_format: str,
    variant_groups: Sequence[Mapping[str, Any]],
) -> str:
    value = path.as_posix()
    name = path.name.lower()

    if variant_groups:
        return "ambiguous"
    if "/_apalache-out/" in value or detected_format in _TRANSIENT_FORMATS:
        return "transient_compiler_output"
    if "environment" in path.parts:
        return "environment_record"
    if detected_format in _FORMAL_SOURCE_FORMATS:
        return "source"
    if (
        name in {"proof-baseline.json", "disproof-baseline.json", "assurance-baseline.md"}
        or name.startswith("test-proof")
        or name.startswith("test-disproof")
        or "counterexamples" in path.parts
        or name == "disproof-vectors.json"
    ):
        return "golden"
    if "recovery" in path.parts:
        return "run_output"
    if "production" in path.parts:
        return "promoted_evidence"
    if name.endswith(("-template.json", ".schema.json")) or "policies" in path.parts:
        return "source"
    if any(marker in name for marker in _RUN_NAME_MARKERS):
        return "run_output"
    if any(marker in name for marker in _SOURCE_NAME_MARKERS):
        return "source"
    if any(marker in name for marker in _PROMOTED_NAME_MARKERS):
        return "promoted_evidence"
    if "corpora" in path.parts or detected_format == "legacy_identifier":
        return "promoted_evidence"
    return "unknown"


def _recommendation(classification: str) -> str:
    return {
        "source": (
            "Retain as an input/source candidate and bind its digest and producer "
            "to a migration manifest before relocation."
        ),
        "golden": (
            "Retain as a golden/compatibility candidate and verify its expected "
            "semantics before manifest promotion."
        ),
        "run_output": (
            "Retain and associate with an immutable run manifest, inputs, and "
            "producer version before considering promotion."
        ),
        "promoted_evidence": (
            "Retain and verify provenance; add an integrity-checked promoted "
            "artifact manifest without rewriting the legacy file."
        ),
        "environment_record": (
            "Retain as a non-authoritative environment observation and bind it "
            "to the originating run and tool versions."
        ),
        "transient_compiler_output": (
            "Retain during the initial audit; exclude from promotion and only "
            "regenerate after the producer and toolchain are pinned."
        ),
        "ambiguous": (
            "Retain every related variant; review lineage and content without "
            "selecting, overwriting, or deleting an authority in this inventory."
        ),
        "unknown": (
            "Retain and manually identify producer, role, and authority before "
            "migration or promotion."
        ),
    }[classification]


def _is_temporary(path: PurePosixPath, detected_format: str) -> bool:
    candidate = _variant_candidate(path)
    return (
        (candidate is not None and candidate[0] == "temporary_name")
        or "/_apalache-out/" in path.as_posix()
        or detected_format in _TRANSIENT_FORMATS
    )


def build_inventory(
    repo_root: Path,
    *,
    artifact_root: str | PurePosixPath = DEFAULT_ARTIFACT_ROOT,
    tracked_paths: Iterable[str | PurePosixPath] | None = None,
) -> dict[str, Any]:
    """Build an inventory using only artifact bytes and repository-relative paths."""

    root = repo_root.resolve()
    relative_root = _as_repo_relative(artifact_root, label="artifact root")
    raw_paths = (
        tracked_artifact_paths(root, relative_root)
        if tracked_paths is None
        else [PurePosixPath(path).as_posix() for path in tracked_paths]
    )
    paths: list[PurePosixPath] = []
    for raw_path in sorted(set(raw_paths)):
        path = _as_repo_relative(raw_path, label="artifact path")
        try:
            path.relative_to(relative_root)
        except ValueError as exc:
            raise InventoryError(
                f"artifact path is outside {relative_root.as_posix()}: {path}"
            ) from exc
        paths.append(path)

    variant_groups = find_variant_groups(paths)
    groups_by_path: dict[str, list[dict[str, Any]]] = {}
    for group in variant_groups:
        for member in group["paths"]:
            groups_by_path.setdefault(member, []).append(group)

    artifact_rows: list[dict[str, Any]] = []
    sidecar_ids: dict[str, list[dict[str, str]]] = {}
    raw_records: list[tuple[PurePosixPath, bytes, str, Any]] = []
    for path in paths:
        data = _read_artifact(root, path)
        detected_format = detect_format(path, data)
        parsed_json = (
            _decode_json(data)
            if detected_format in {"json", "json_schema"}
            else _JSON_DECODE_FAILED
        )
        raw_records.append((path, data, detected_format, parsed_json))
        if detected_format == "legacy_identifier":
            target = path.with_suffix(".json").as_posix()
            sidecar_ids[target] = _legacy_ids(path, data, parsed_json)

    for path, data, detected_format, parsed_json in raw_records:
        path_string = path.as_posix()
        groups = groups_by_path.get(path_string, [])
        classification = _classify(path, detected_format, groups)
        legacy_ids = _legacy_ids(path, data, parsed_json) + sidecar_ids.get(path_string, [])
        legacy_ids = sorted(
            legacy_ids,
            key=lambda item: (item["source_path"], item["field"], item["value"]),
        )
        artifact_rows.append(
            {
                "ambiguity_reasons": [group["reason"] for group in groups],
                "classification": classification,
                "detected_format": detected_format,
                "legacy_ids": legacy_ids,
                "likely_producers": _likely_producers(path, detected_format),
                "path": path_string,
                "recommendation": _recommendation(classification),
                "related_paths": sorted(
                    {
                        related
                        for group in groups
                        for related in group["paths"]
                        if related != path_string
                    }
                ),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "temporary": _is_temporary(path, detected_format),
                "variant_kinds": sorted({group["kind"] for group in groups}),
            }
        )

    classification_counts = {
        classification: sum(
            row["classification"] == classification for row in artifact_rows
        )
        for classification in CLASSIFICATIONS
    }
    format_names = sorted({row["detected_format"] for row in artifact_rows})
    format_counts = {
        detected_format: sum(
            row["detected_format"] == detected_format for row in artifact_rows
        )
        for detected_format in format_names
    }

    return {
        "artifacts": artifact_rows,
        "interface": INTERFACE,
        "policy": {
            "authority_selection": "none",
            "inventory_is_migration_authority": False,
            "read_only": True,
            "recommendations_are_non_destructive": True,
        },
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "artifact_root": relative_root.as_posix(),
            "selection": "git_tracked_files_only",
        },
        "summary": {
            "ambiguous_count": classification_counts["ambiguous"],
            "artifact_count": len(artifact_rows),
            "classification_counts": classification_counts,
            "format_counts": format_counts,
            "legacy_id_count": sum(len(row["legacy_ids"]) for row in artifact_rows),
            "new_variant_count": sum(
                (
                    (candidate := _variant_candidate(PurePosixPath(row["path"])))
                    is not None
                    and candidate[0] == "new_suffix"
                )
                for row in artifact_rows
            ),
            "temporary_count": sum(row["temporary"] for row in artifact_rows),
            "total_size_bytes": sum(row["size_bytes"] for row in artifact_rows),
        },
        "variant_groups": variant_groups,
    }


def serialize_inventory(inventory: Mapping[str, Any]) -> str:
    """Return the canonical checked-in representation."""

    return json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--artifact-root",
        default=DEFAULT_ARTIFACT_ROOT.as_posix(),
        help="repository-relative tracked artifact directory",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT.as_posix(),
        help="repository-relative output JSON path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the output is absent or differs; do not write",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        output_path = _as_repo_relative(args.output, label="output path")
        inventory = build_inventory(repo_root, artifact_root=args.artifact_root)
        content = serialize_inventory(inventory)
        destination = repo_root.joinpath(*output_path.parts)
        if args.check:
            try:
                existing = destination.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"inventory check failed: {exc}", file=sys.stderr)
                return 1
            if existing != content:
                print(
                    f"inventory check failed: {output_path.as_posix()} is stale",
                    file=sys.stderr,
                )
                return 1
            print(
                f"inventory is current: {inventory['summary']['artifact_count']} artifacts"
            )
            return 0

        _write_atomic(destination, content)
        print(
            f"wrote {output_path.as_posix()}: "
            f"{inventory['summary']['artifact_count']} artifacts"
        )
        return 0
    except InventoryError as exc:
        print(f"inventory failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

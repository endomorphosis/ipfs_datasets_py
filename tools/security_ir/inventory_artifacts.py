#!/usr/bin/env python3
"""Build a deterministic, read-only inventory of legacy Security IR artifacts.

The inventory is deliberately descriptive.  In particular, it records
temporary files and variant relationships but never selects an authoritative
member of a variant group.  The only path this program writes is the requested
inventory output, which must be outside the artifact tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "SecurityArtifactInventory@1"
DEFAULT_ARTIFACT_ROOT = "security_ir_artifacts"
DEFAULT_OUTPUT = "docs/security_verification/security_ir_artifact_inventory.json"

CLASSIFICATIONS = (
    "source",
    "golden",
    "run output",
    "promoted evidence",
    "environment record",
    "transient compiler output",
    "ambiguous",
    "unknown",
)

_ID_FIELD = re.compile(r"(?:^id$|_ids?$|^cid$|_cids?$)")
_NEW_VARIANT = re.compile(r"-new(?=\.[^.]+$)")
_TMP_VARIANT = re.compile(r"\.tmp(?=\.[^.]+$)")
_LATEST_VARIANT = re.compile(r"-latest(?=\.[^.]+$)")

_FORMAT_BY_SUFFIX = {
    ".aux": "coq-auxiliary",
    ".cid": "legacy-identifier",
    ".glob": "coq-globalization",
    ".json": "json",
    ".lean": "lean-source",
    ".md": "markdown",
    ".pv": "proverif-source",
    ".smt": "smt-lib",
    ".smt2": "smt-lib",
    ".spthy": "tamarin-source",
    ".tla": "tla-plus-source",
    ".ts": "typescript-source",
    ".txt": "plain-text",
    ".v": "coq-source",
    ".vo": "coq-compiled",
    ".vok": "coq-compiled-check",
    ".vos": "coq-compiled-summary",
}

_SOURCE_FORMATS = {
    "coq-source",
    "lean-source",
    "markdown",
    "proverif-source",
    "smt-lib",
    "tamarin-source",
    "tla-plus-source",
    "typescript-source",
}

_TRANSIENT_FORMATS = {
    "coq-auxiliary",
    "coq-compiled",
    "coq-compiled-check",
    "coq-compiled-summary",
    "coq-globalization",
}

_SOURCE_NAME_TOKENS = (
    "assumption",
    "claim",
    "facts",
    "model-ir",
    "policy",
    "schema",
    "template",
    "plan",
)

_RUN_NAME_TOKENS = (
    "bundle",
    "counterexample",
    "coverage",
    "decision",
    "fuzz",
    "lock",
    "manifest",
    "mapping",
    "packet",
    "preflight",
    "profile",
    "receipt",
    "report",
    "result",
    "review",
    "status",
    "trace",
    "verdict",
    "workflow",
)

# Ordered from the most specific path signatures to broad fallbacks.
_PRODUCER_RULES: tuple[tuple[str, str], ...] = (
    ("/_apalache-out/", "Apalache model checker"),
    ("/proof-kernel/", "Lean/Coq proof-kernel workflow"),
    (
        "/testnet/fuzz/",
        "scripts/ops/security_verification/run_xaman_testnet_fuzzing.py",
    ),
    (
        "/testnet/tla/",
        "scripts/ops/security_verification/generate_xaman_testnet_apalache.py",
    ),
    (
        "/testnet/protocol/",
        "scripts/ops/security_verification/generate_xaman_testnet_protocol.py",
    ),
    (
        "/self-hosted-testnet/protocol/",
        "scripts/ops/security_verification/generate_xaman_self_hosted_resolution_protocol.py",
    ),
    (
        "/protocol/",
        "scripts/ops/security_verification/generate_xaman_protocol_projection.py",
    ),
    (
        "/tla/",
        "scripts/ops/security_verification/generate_xaman_tla_workflow.py",
    ),
    (
        "/testnet/smtlib/",
        "scripts/ops/security_verification/prove_xaman_testnet_smt_claims.py",
    ),
    (
        "/smtlib/",
        "ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all",
    ),
    (
        "/assurance-run/",
        "scripts/ops/security_verification/run_security_ir_assurance_baseline.py",
    ),
    (
        "/production/",
        "Security verification production-evidence workflow",
    ),
    (
        "/recovery/",
        "Security verification recovery workflow",
    ),
    (
        "/environment/",
        "scripts/ops/security_verification probe/provision workflow",
    ),
    (
        "/runtime/",
        "Xaman runtime evidence capture/validation workflow",
    ),
    (
        "/corpora/xaman-app/",
        "Xaman Security IR extraction/verification workflow",
    ),
)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether *path* is within *parent* without requiring existence."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _normalise_relative_path(value: str | Path) -> PurePosixPath:
    """Validate and normalize a repository-relative path."""

    raw = str(value).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"artifact paths must be repository-relative: {value!s}")
    return path


def tracked_artifact_paths(
    repo_root: Path,
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
) -> list[PurePosixPath]:
    """Return Git-tracked files below *artifact_root* in bytewise path order."""

    repo_root = repo_root.resolve()
    root = _normalise_relative_path(artifact_root)
    command = ["git", "ls-files", "-z", "--", root.as_posix()]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required for a tracked-only inventory") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"unable to enumerate tracked artifacts: {detail}") from exc

    paths: list[PurePosixPath] = []
    prefix = root.parts
    for value in result.stdout.split(b"\0"):
        if not value:
            continue
        try:
            decoded = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("tracked artifact path is not valid UTF-8") from exc
        path = _normalise_relative_path(decoded)
        if path.parts[: len(prefix)] != prefix:
            raise RuntimeError(f"git returned an out-of-scope artifact path: {decoded}")
        paths.append(path)
    return sorted(set(paths), key=lambda item: item.as_posix().encode("utf-8"))


def filesystem_artifact_paths(
    repo_root: Path,
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
) -> list[PurePosixPath]:
    """Return all files below *artifact_root*, primarily for fixture audits."""

    repo_root = repo_root.resolve()
    relative_root = _normalise_relative_path(artifact_root)
    absolute_root = repo_root.joinpath(*relative_root.parts)
    if not absolute_root.is_dir():
        raise FileNotFoundError(f"artifact root does not exist: {relative_root}")

    paths = [
        PurePosixPath(path.relative_to(repo_root).as_posix())
        for path in absolute_root.rglob("*")
        if path.is_file() or path.is_symlink()
    ]
    return sorted(set(paths), key=lambda item: item.as_posix().encode("utf-8"))


def _read_artifact(repo_root: Path, relative_path: PurePosixPath) -> tuple[bytes, str]:
    """Read file bytes without following symbolic links outside the audit tree."""

    path = repo_root.joinpath(*relative_path.parts)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"tracked artifact is missing: {relative_path}") from exc
    if path.is_symlink():
        return os.readlink(path).encode("utf-8", errors="surrogateescape"), "symbolic-link"
    if not path.is_file():
        raise ValueError(f"tracked artifact is not a regular file: {relative_path}")
    data = path.read_bytes()
    if len(data) != metadata.st_size:
        raise RuntimeError(f"artifact changed while it was read: {relative_path}")
    return data, "regular-file"


def detect_format(path: PurePosixPath, data: bytes, file_type: str = "regular-file") -> str:
    """Detect the artifact's content format, validating JSON when applicable."""

    if file_type == "symbolic-link":
        return "symbolic-link"
    if data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        return "git-lfs-pointer"

    suffix = path.suffix.lower()
    expected = _FORMAT_BY_SUFFIX.get(suffix)
    if expected == "json":
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "invalid-json"
        return "json"
    if expected:
        return expected
    if b"\0" in data[:8192]:
        return "binary"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "utf-8-text"


def _variant_metadata(path: PurePosixPath) -> dict[str, Any]:
    value = path.as_posix()
    name = path.name
    kinds: list[str] = []
    base_name = name

    if _NEW_VARIANT.search(base_name):
        kinds.append("new")
        base_name = _NEW_VARIANT.sub("", base_name)
    if _TMP_VARIANT.search(base_name):
        kinds.append("temporary")
        base_name = _TMP_VARIANT.sub("", base_name)
    if _LATEST_VARIANT.search(base_name):
        kinds.append("latest")
        base_name = _LATEST_VARIANT.sub("", base_name)

    if "/_apalache-out/" in f"/{value}":
        kinds.append("compiler-temporary")
    if path.suffix.lower() in {".aux", ".glob", ".vo", ".vok", ".vos"}:
        kinds.append("compiler-temporary")

    variant_of = None
    if base_name != name:
        variant_of = path.with_name(base_name).as_posix()
    return {
        "is_temporary": any(
            kind in {"temporary", "compiler-temporary"} for kind in kinds
        ),
        "is_new_variant": "new" in kinds,
        "is_mutable_alias": "latest" in kinds,
        "variant_kinds": sorted(set(kinds)),
        "variant_of": variant_of,
    }


def _classify(
    path: PurePosixPath,
    detected_format: str,
    variant: dict[str, Any],
) -> str:
    value = f"/{path.as_posix().lower()}"
    name = path.name.lower()

    if variant["is_new_variant"] or variant["is_mutable_alias"]:
        return "ambiguous"
    if variant["is_temporary"] or detected_format in _TRANSIENT_FORMATS:
        return "transient compiler output"
    if "/environment/" in value or "environment-probe" in name:
        return "environment record"
    if "baseline" in name or name.startswith("test-"):
        return "golden"
    if "/production/" in value or "/policies/" in value or "promoted" in name:
        return "promoted evidence"
    if detected_format in _SOURCE_FORMATS:
        return "source"
    if detected_format == "legacy-identifier" or any(
        token in name for token in _SOURCE_NAME_TOKENS
    ):
        return "source"
    if detected_format == "json" and any(token in name for token in _RUN_NAME_TOKENS):
        return "run output"
    if detected_format == "json":
        return "run output"
    return "unknown"


def _legacy_ids(detected_format: str, data: bytes) -> list[dict[str, str]]:
    """Extract explicit top-level legacy identity fields without interpretation."""

    identities: set[tuple[str, str]] = set()
    if detected_format == "legacy-identifier":
        try:
            value = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            value = ""
        if value:
            identities.add(("sidecar", value))
    elif detected_format == "json":
        payload = json.loads(data.decode("utf-8"))
        if isinstance(payload, dict):
            for field, value in payload.items():
                if not _ID_FIELD.search(str(field)):
                    continue
                values: Iterable[Any]
                if isinstance(value, list):
                    values = value
                else:
                    values = (value,)
                for item in values:
                    if isinstance(item, (str, int)) and not isinstance(item, bool):
                        identities.add((str(field), str(item)))
    return [
        {"field": field, "value": value}
        for field, value in sorted(
            identities,
            key=lambda item: (item[0].encode("utf-8"), item[1].encode("utf-8")),
        )
    ]


def _likely_producers(path: PurePosixPath, detected_format: str) -> list[str]:
    value = f"/{path.as_posix()}"
    producers = [
        producer for signature, producer in _PRODUCER_RULES if signature in value
    ]
    if detected_format.startswith("coq-") and "Coq compiler (coqc)" not in producers:
        producers.insert(0, "Coq compiler (coqc)")
    if detected_format == "legacy-identifier":
        producers.append("Security IR canonicalization/CID workflow")
    if not producers:
        producers.append("legacy Security IR workflow (exact producer not recorded)")
    return list(dict.fromkeys(producers))


def _ambiguity_reasons(
    path: PurePosixPath,
    classification: str,
    detected_format: str,
    variant: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if variant["is_new_variant"]:
        reasons.append(
            "The '-new' suffix coexists with or implies an earlier name, "
            "but records no reviewed authority decision."
        )
    if variant["is_mutable_alias"]:
        reasons.append(
            "The '-latest' suffix is a mutable alias and does not identify an immutable run."
        )
    if "temporary" in variant["variant_kinds"]:
        reasons.append(
            "The temporary filename may contain an interrupted or intermediate write."
        )
    if "compiler-temporary" in variant["variant_kinds"]:
        reasons.append(
            "The path or suffix identifies tool-generated compiler/model-checker output."
        )
    if detected_format == "invalid-json":
        reasons.append("The .json file does not contain valid UTF-8 JSON.")
    if classification == "unknown":
        reasons.append("No current classification or producer signature matched.")
    return reasons


def _recommendations(classification: str, variant: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if variant["is_new_variant"] or variant["is_mutable_alias"]:
        recommendations.append(
            "Compare all variants and record a reviewed migration decision; "
            "do not select authority from the filename."
        )
    if classification == "transient compiler output":
        recommendations.append(
            "Keep during this audit; exclude from promoted evidence and regenerate "
            "only through a recorded toolchain run."
        )
    elif classification == "source":
        recommendations.append(
            "Preserve exact bytes and bind the source to a versioned input manifest."
        )
    elif classification == "golden":
        recommendations.append(
            "Preserve exact bytes and bind the artifact to a reviewed golden-corpus manifest."
        )
    elif classification == "run output":
        recommendations.append(
            "Bind the output to an immutable run manifest with producer, inputs, "
            "configuration, and parent digests."
        )
    elif classification == "promoted evidence":
        recommendations.append(
            "Require a reviewed promotion manifest before treating this artifact "
            "as authoritative evidence."
        )
    elif classification == "environment record":
        recommendations.append(
            "Record as observational run metadata; do not include environment "
            "details in deterministic declaration identity."
        )
    elif classification == "ambiguous" and not recommendations:
        recommendations.append(
            "Retain all candidates and require a reviewed authority decision before migration."
        )
    elif classification == "unknown":
        recommendations.append(
            "Classify manually and identify the producer before migration or promotion."
        )
    return recommendations


def _artifact_record(repo_root: Path, path: PurePosixPath) -> dict[str, Any]:
    data, file_type = _read_artifact(repo_root, path)
    detected_format = detect_format(path, data, file_type)
    variant = _variant_metadata(path)
    classification = _classify(path, detected_format, variant)
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "file_type": file_type,
        "detected_format": detected_format,
        "classification": classification,
        "likely_producers": _likely_producers(path, detected_format),
        "legacy_ids": _legacy_ids(detected_format, data),
        "is_temporary": variant["is_temporary"],
        "is_new_variant": variant["is_new_variant"],
        "is_mutable_alias": variant["is_mutable_alias"],
        "variant_kinds": variant["variant_kinds"],
        "variant_of": variant["variant_of"],
        "ambiguity_reasons": _ambiguity_reasons(
            path, classification, detected_format, variant
        ),
        "recommendations": _recommendations(classification, variant),
        "authority_selected": False,
    }


def _variant_groups(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    known_paths = {record["path"] for record in records}
    groups: dict[str, list[str]] = {}
    for record in records:
        base = record["variant_of"]
        if base is None:
            continue
        members = groups.setdefault(base, [])
        if base in known_paths:
            members.append(base)
        members.append(record["path"])

    output = []
    for base, members in groups.items():
        output.append(
            {
                "base_path": base,
                "paths": sorted(set(members), key=lambda item: item.encode("utf-8")),
                "authority_selected": False,
                "ambiguity_reason": (
                    "Filename variants alone do not establish chronology, review state, "
                    "or evidentiary authority."
                ),
                "recommendation": (
                    "Retain every path until content, producer, provenance, and review "
                    "records support an explicit migration decision."
                ),
            }
        )
    return sorted(output, key=lambda item: item["base_path"].encode("utf-8"))


def build_inventory(
    repo_root: str | Path,
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
    *,
    tracked_only: bool = True,
) -> dict[str, Any]:
    """Create an in-memory deterministic inventory without writing any files."""

    repo = Path(repo_root).resolve()
    relative_root = _normalise_relative_path(artifact_root)
    absolute_root = repo.joinpath(*relative_root.parts)
    if not absolute_root.is_dir():
        raise FileNotFoundError(f"artifact root does not exist: {relative_root}")

    paths = (
        tracked_artifact_paths(repo, relative_root)
        if tracked_only
        else filesystem_artifact_paths(repo, relative_root)
    )
    records = [_artifact_record(repo, path) for path in paths]
    classification_counts = Counter(record["classification"] for record in records)
    format_counts = Counter(record["detected_format"] for record in records)
    inventory_preimage = json.dumps(
        records, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_root": relative_root.as_posix(),
        "scope": "git-tracked files" if tracked_only else "filesystem files",
        "artifact_count": len(records),
        "total_size_bytes": sum(record["size_bytes"] for record in records),
        "inventory_sha256": hashlib.sha256(inventory_preimage).hexdigest(),
        "classification_counts": {
            name: classification_counts.get(name, 0) for name in CLASSIFICATIONS
        },
        "format_counts": dict(sorted(format_counts.items())),
        "temporary_artifact_count": sum(
            bool(record["is_temporary"]) for record in records
        ),
        "new_variant_count": sum(
            bool(record["is_new_variant"]) for record in records
        ),
        "mutable_alias_count": sum(
            bool(record["is_mutable_alias"]) for record in records
        ),
        "authority_decisions_made": 0,
        "legacy_id_extraction": (
            "Explicit top-level JSON fields named id/cid, ending in _id/_ids/_cid/_cids, "
            "plus .cid sidecar contents; values are recorded verbatim, not normalized."
        ),
        "variant_groups": _variant_groups(records),
        "artifacts": records,
    }


def render_inventory(inventory: dict[str, Any]) -> str:
    """Serialize an inventory using the repository's stable JSON representation."""

    return json.dumps(inventory, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def write_inventory(
    inventory: dict[str, Any],
    output_path: str | Path,
    *,
    repo_root: str | Path,
) -> None:
    """Atomically write an inventory, refusing to modify the artifact tree."""

    repo = Path(repo_root).resolve()
    output = Path(output_path)
    if not output.is_absolute():
        output = repo / output
    output = output.resolve()
    artifact_root = repo / inventory["artifact_root"]
    if _is_relative_to(output, artifact_root.resolve()):
        raise ValueError("inventory output must be outside the artifact tree")

    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_inventory(inventory)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


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
        default=DEFAULT_ARTIFACT_ROOT,
        help=f"repository-relative artifact tree (default: {DEFAULT_ARTIFACT_ROOT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help=f"inventory JSON path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="inventory every filesystem file instead of only Git-tracked files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if --output is absent or differs; do not write",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="write the inventory to stdout instead of --output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inventory = build_inventory(
            args.repo_root,
            args.artifact_root,
            tracked_only=not args.include_untracked,
        )
        rendered = render_inventory(inventory)
        output = args.output if args.output.is_absolute() else args.repo_root / args.output

        if args.check:
            try:
                current = output.read_text(encoding="utf-8")
            except FileNotFoundError:
                print(f"inventory is missing: {output}", file=sys.stderr)
                return 1
            if current != rendered:
                print(f"inventory is stale: {output}", file=sys.stderr)
                return 1
            return 0
        if args.stdout:
            sys.stdout.write(rendered)
            return 0
        write_inventory(inventory, output, repo_root=args.repo_root)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"inventory failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

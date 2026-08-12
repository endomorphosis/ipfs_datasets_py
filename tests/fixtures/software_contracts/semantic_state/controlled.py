"""SemanticStateControlledFixture@1 — public loader and materializer.

Materialized trees are ordinary files.  Tests create temporary Git repositories
and scan them through the public ISI API; this module never constructs
dependency edges or stores receipts.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .recipe import (
    BASELINE_FILES,
    BASELINE_PROOF_IDS,
    BASELINE_TEST_NODE_IDS,
    FORBIDDEN_CASE_FIELDS,
    MUTATION_CASES,
    REQUIRED_MUTATION_KINDS,
    case_by_id,
)

INTERFACE_NAME = "SemanticStateControlledFixture@1"
SCHEMA_NAME = "ipfs-datasets.software-contracts.semantic-state-controlled-fixture@1"

FIXTURE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"


@dataclass(frozen=True, slots=True)
class FileOp:
    """One deterministic file mutation operation."""

    op: str
    path: str = ""
    content: str = ""
    source: str = ""
    dest: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FileOp:
        op = str(raw["op"])
        if op == "write":
            return cls(op=op, path=str(raw["path"]), content=str(raw["content"]))
        if op == "delete":
            return cls(op=op, path=str(raw["path"]))
        if op == "rename":
            return cls(op=op, source=str(raw["from"]), dest=str(raw["to"]))
        raise ValueError(f"unsupported file op: {op!r}")


@dataclass(frozen=True, slots=True)
class MutationCase:
    """Independently declared mutation case with authored selection oracle."""

    case_id: str
    kind: str
    description: str
    changed_paths: tuple[str, ...]
    file_ops: tuple[FileOp, ...]
    affected_tests: tuple[str, ...]
    affected_proofs: tuple[str, ...]
    semantic_change: bool
    requires_full_fallback: bool
    formatting_only: bool
    deleted_symbols: tuple[str, ...] = ()
    deleted_tests: tuple[str, ...] = ()
    rename_pairs: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> MutationCase:
        unknown_forbidden = FORBIDDEN_CASE_FIELDS.intersection(raw)
        if unknown_forbidden:
            raise ValueError(
                "mutation case encodes forbidden analyzer-bypass fields: "
                + ", ".join(sorted(unknown_forbidden))
            )
        file_ops = tuple(FileOp.from_mapping(item) for item in raw.get("file_ops", ()))
        rename_pairs = tuple(
            (str(a), str(b)) for a, b in tuple(raw.get("rename_pairs", ()) or ())
        )
        return cls(
            case_id=str(raw["case_id"]),
            kind=str(raw["kind"]),
            description=str(raw["description"]),
            changed_paths=tuple(str(p) for p in raw.get("changed_paths", ())),
            file_ops=file_ops,
            affected_tests=tuple(str(x) for x in raw.get("affected_tests", ())),
            affected_proofs=tuple(str(x) for x in raw.get("affected_proofs", ())),
            semantic_change=bool(raw.get("semantic_change", True)),
            requires_full_fallback=bool(raw.get("requires_full_fallback", False)),
            formatting_only=bool(raw.get("formatting_only", False)),
            deleted_symbols=tuple(str(x) for x in raw.get("deleted_symbols", ())),
            deleted_tests=tuple(str(x) for x in raw.get("deleted_tests", ())),
            rename_pairs=rename_pairs,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "kind": self.kind,
            "description": self.description,
            "changed_paths": list(self.changed_paths),
            "file_ops": [
                (
                    {"op": op.op, "path": op.path, "content": op.content}
                    if op.op == "write"
                    else {"op": op.op, "path": op.path}
                    if op.op == "delete"
                    else {"op": op.op, "from": op.source, "to": op.dest}
                )
                for op in self.file_ops
            ],
            "affected_tests": list(self.affected_tests),
            "affected_proofs": list(self.affected_proofs),
            "semantic_change": self.semantic_change,
            "requires_full_fallback": self.requires_full_fallback,
            "formatting_only": self.formatting_only,
        }
        if self.deleted_symbols:
            payload["deleted_symbols"] = list(self.deleted_symbols)
        if self.deleted_tests:
            payload["deleted_tests"] = list(self.deleted_tests)
        if self.rename_pairs:
            payload["rename_pairs"] = [list(pair) for pair in self.rename_pairs]
        return payload


@dataclass(frozen=True, slots=True)
class SemanticStateControlledFixture:
    """Closed fixture catalog: baseline files, mutation cases, and oracles."""

    interface: str
    schema: str
    baseline_files: Mapping[str, str]
    test_universe: tuple[str, ...]
    proof_universe: tuple[str, ...]
    cases: tuple[MutationCase, ...]

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)

    def get_case(self, case_id: str) -> MutationCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(f"unknown mutation case: {case_id!r}")

    def cases_by_kind(self) -> dict[str, MutationCase]:
        return {case.kind: case for case in self.cases}

    def authored_oracle(self, case_id: str) -> tuple[str, ...]:
        return self.get_case(case_id).affected_tests

    def authored_proof_oracle(self, case_id: str) -> tuple[str, ...]:
        return self.get_case(case_id).affected_proofs


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def load_controlled_fixture() -> SemanticStateControlledFixture:
    """Load and validate the checked-in controlled fixture catalog."""
    manifest = load_manifest()
    if manifest.get("interface") != INTERFACE_NAME:
        raise ValueError(
            f"manifest interface {manifest.get('interface')!r} != {INTERFACE_NAME!r}"
        )
    cases = tuple(MutationCase.from_mapping(raw) for raw in MUTATION_CASES)
    _validate_catalog(cases, manifest)
    baseline = {str(path): str(content) for path, content in sorted(BASELINE_FILES.items())}
    return SemanticStateControlledFixture(
        interface=INTERFACE_NAME,
        schema=str(manifest.get("schema", SCHEMA_NAME)),
        baseline_files=baseline,
        test_universe=tuple(sorted(BASELINE_TEST_NODE_IDS)),
        proof_universe=tuple(sorted(BASELINE_PROOF_IDS)),
        cases=cases,
    )


def _validate_catalog(cases: Sequence[MutationCase], manifest: Mapping[str, Any]) -> None:
    if not cases:
        raise ValueError("controlled fixture declares no mutation cases")
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate mutation case_id values")
    # Deterministic catalog order: required-kind order, then any extras by case_id.
    required = tuple(manifest.get("required_mutation_kinds") or REQUIRED_MUTATION_KINDS)
    kinds = [case.kind for case in cases]
    if len(set(kinds)) != len(kinds):
        raise ValueError("mutation kinds must be unique (one independent case per kind)")
    missing = [kind for kind in required if kind not in kinds]
    if missing:
        raise ValueError(f"missing required mutation kinds: {missing}")
    expected_kind_order = list(required) + sorted(
        kind for kind in kinds if kind not in required
    )
    if kinds != expected_kind_order:
        raise ValueError(
            "mutation cases must follow deterministic required-kind order; "
            f"got {kinds}, expected {expected_kind_order}"
        )
    baseline_universe = set(BASELINE_TEST_NODE_IDS)
    for case in cases:
        if list(case.changed_paths) != sorted(case.changed_paths):
            raise ValueError(f"{case.case_id}: changed_paths must be sorted")
        if list(case.affected_tests) != sorted(case.affected_tests):
            raise ValueError(f"{case.case_id}: affected_tests must be sorted")
        if list(case.affected_proofs) != sorted(case.affected_proofs):
            raise ValueError(f"{case.case_id}: affected_proofs must be sorted")
        if case.formatting_only:
            if case.semantic_change:
                raise ValueError(f"{case.case_id}: formatting_only cannot be semantic")
            if case.affected_tests or case.affected_proofs:
                raise ValueError(
                    f"{case.case_id}: formatting-only oracle must be empty "
                    "(ordinary truth, not analyzer bypass)"
                )
        for path in case.changed_paths:
            if path.startswith("/") or ".." in Path(path).parts:
                raise ValueError(f"{case.case_id}: non-relative path {path!r}")
        for test_id in case.affected_tests:
            if test_id not in baseline_universe and test_id not in case.deleted_tests:
                raise ValueError(
                    f"{case.case_id}: affected test {test_id!r} not in baseline universe"
                )


def materialize_baseline(destination: Path | str) -> Path:
    """Write the baseline repository into ``destination`` (created if needed)."""
    dest = Path(destination)
    if dest.exists():
        if any(dest.iterdir()):
            raise FileExistsError(f"destination is not empty: {dest}")
    else:
        dest.mkdir(parents=True, exist_ok=True)
    for rel_path, content in sorted(BASELINE_FILES.items()):
        path = dest / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return dest


def apply_mutation(repository: Path | str, case_id: str) -> MutationCase:
    """Apply an independently declared mutation to an existing repository tree."""
    repo = Path(repository)
    case = MutationCase.from_mapping(case_by_id()[case_id])
    for op in case.file_ops:
        if op.op == "write":
            target = repo / op.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(op.content, encoding="utf-8")
        elif op.op == "delete":
            target = repo / op.path
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            else:
                raise FileNotFoundError(f"delete target missing: {op.path}")
        elif op.op == "rename":
            source = repo / op.source
            dest = repo / op.dest
            if not source.exists():
                raise FileNotFoundError(f"rename source missing: {op.source}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            source.rename(dest)
        else:  # pragma: no cover - validated at load time
            raise ValueError(f"unsupported op {op.op!r}")
    return case


def materialize_mutated(destination: Path | str, case_id: str) -> tuple[Path, MutationCase]:
    """Materialize baseline then apply one mutation case."""
    dest = materialize_baseline(destination)
    case = apply_mutation(dest, case_id)
    return dest, case


def iter_repository_files(root: Path | str) -> tuple[tuple[str, str], ...]:
    """Return sorted (relative posix path, text) pairs for a materialized tree."""
    base = Path(root)
    items: list[tuple[str, str]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if rel.startswith(".git/") or rel == ".git":
            continue
        items.append((rel, path.read_text(encoding="utf-8")))
    return tuple(items)


def repository_digest(root: Path | str) -> str:
    """Deterministic content digest of a materialized repository."""
    import hashlib

    hasher = hashlib.sha256()
    for rel, text in iter_repository_files(root):
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(text.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def changed_paths_between(before: Path | str, after: Path | str) -> tuple[str, ...]:
    """Return sorted relative paths whose presence or content differs."""
    left = dict(iter_repository_files(before))
    right = dict(iter_repository_files(after))
    paths = set(left) | set(right)
    changed = [path for path in paths if left.get(path) != right.get(path)]
    return tuple(sorted(changed))


def assert_no_checked_in_git(root: Path | str | None = None) -> None:
    base = Path(root) if root is not None else FIXTURE_ROOT
    if (base / ".git").exists():
        raise AssertionError(f"checked-in .git is forbidden under {base}")


def forbidden_fixture_artifacts(root: Path | str | None = None) -> tuple[str, ...]:
    """Return any forbidden artifact paths found under the fixture tree."""
    base = Path(root) if root is not None else FIXTURE_ROOT
    forbidden_names = {
        ".git",
        "state_store",
        "receipts",
        "DependencyEdge",
    }
    found: list[str] = []
    for path in base.rglob("*"):
        name = path.name
        if name in forbidden_names or name.endswith(".receipt.json"):
            found.append(path.relative_to(base).as_posix())
    return tuple(sorted(found))


def case_ids() -> tuple[str, ...]:
    return tuple(str(case["case_id"]) for case in MUTATION_CASES)


def list_mutation_cases() -> tuple[MutationCase, ...]:
    return load_controlled_fixture().cases


def ensure_sorted_paths(paths: Iterable[str]) -> tuple[str, ...]:
    values = tuple(str(path) for path in paths)
    if values != tuple(sorted(values)):
        raise ValueError(f"paths are not sorted: {values!r}")
    return values

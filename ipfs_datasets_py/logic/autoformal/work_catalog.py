"""Navigate the canonical LegalIR work without loading a registered owner.

This module reads one bounded JSON catalog and, on explicit ``--check``,
inspects named canonical files and their declared APIs using the stdlib AST.
It never imports a numerical/runtime owner, traverses historical archives,
opens a checkpoint, calls a model, or queries admission/resource state.
Recorded qualification labels are attributed saved-evidence summaries, not a
new execution, legal-meaning review, or proof-admission decision.

Run directly to avoid unrelated package initialization::

    python ipfs_datasets_py/logic/autoformal/work_catalog.py --check
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path


_HOME_REL = Path("ipfs_datasets_py/logic/autoformal")
_MAX_CATALOG_BYTES = 2 * 1024 * 1024
_MAX_COMPONENT_BYTES = 2 * 1024 * 1024
_SCHEMA = "legal-autoformal-work-catalog/v1"


def _closed_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate catalog key: " + key)
        value[key] = item
    return value


def _read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(_MAX_CATALOG_BYTES + 1)
    if len(raw) > _MAX_CATALOG_BYTES:
        raise ValueError("catalog exceeds bounded metadata size: " + str(path))
    try:
        value = json.loads(raw, object_pairs_hook=_closed_object,
                           parse_constant=lambda token: (_ for _ in ()).throw(
                               ValueError("nonfinite catalog number: " + token)))
    except RecursionError as exc:
        raise ValueError("catalog nesting exceeds parser limit") from exc
    if type(value) is not dict:
        raise ValueError("catalog must be a JSON object: " + str(path))
    return value


def _catalog_at(path):
    value = _read_json(path)
    if value.get("schema") != _SCHEMA:
        raise ValueError("unsupported work catalog schema")
    return value


def load_catalog():
    """Return detached curated metadata adjacent to this module."""
    return _catalog_at(Path(__file__).resolve().parent / "docs/work_catalog.json")


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(label + " must be a nonempty string")
    return value


def _strings(value, label):
    if type(value) is not list:
        raise ValueError(label + " must be a list of strings")
    for item in value:
        _text(item, label + " entry")
    return value


def _records(value, label):
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise ValueError(label + " must be a list of objects")
    return value


def _index(records, label):
    result = {}
    for item in records:
        key = _text(item.get("id"), label + " ID")
        if key in result:
            raise ValueError("duplicate " + label + " ID: " + key)
        result[key] = item
    return result


def _prototype_counts(records):
    counts = {"archived_prototypes": len(records),
              "archived_unselected_prototypes": 0,
              "archived_prototypes_with_installed_successors": 0}
    for item in records:
        status = item.get("status")
        if status == "archived_unselected_prototype":
            counts["archived_unselected_prototypes"] += 1
        elif status == "archived_source_with_installed_canonical_successor":
            counts["archived_prototypes_with_installed_successors"] += 1
        else:
            raise ValueError("unknown archived prototype status")
    return counts


def list_components():
    """Return metadata records; no registered module is imported."""
    return deepcopy(load_catalog()["components"])


def component(component_id):
    """Return one detached owner record without reading backlog or archives."""
    for item in load_catalog()["components"]:
        if item["id"] == component_id:
            return deepcopy(item)
    raise KeyError(component_id)


def section(name):
    """Return one explicit metadata section, without executing its owners."""
    allowed = {"components", "selected_evidence", "archived_prototypes",
               "known_candidate_relationships", "required_documentation",
               "historical_survey_reference", "archive_policy", "limits"}
    if name not in allowed:
        raise KeyError(name)
    return deepcopy(load_catalog()[name])


_TASK_CORE = ("id", "title", "status", "priority", "depends_on")
_TASK_DETAIL = _TASK_CORE + ("acceptance_criteria", "reuse_owners", "remaining_scope", "deliverables")


def _backlog(repo_root=None):
    path = (_canonical_path(Path(repo_root).resolve(), str(_HOME_REL / "docs/BACKLOG.json"))
            if repo_root is not None else
            Path(__file__).resolve().parent / "docs/BACKLOG.json")
    value = _read_json(path)
    if value.get("schema") != "legal-ir-active-work-items/v1":
        raise ValueError("unsupported active backlog schema")
    records = value.get("tasks")
    if type(records) is not list or len(records) != 24:
        raise ValueError("preserved 24-task active backlog required")
    by_id = _index(_records(records, "active tasks"), "active task")
    edges = {}
    for task_id, item in by_id.items():
        dependencies = _strings(item.get("depends_on"), task_id + " dependencies")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError(task_id + ": duplicate dependency")
        for dependency in dependencies:
            if dependency not in by_id:
                raise ValueError(task_id + ": unknown dependency " + dependency)
            if dependency == task_id:
                raise ValueError(task_id + ": self dependency")
        edges[task_id] = dependencies
    visiting, visited = set(), set()
    def visit(task_id):
        if task_id in visiting:
            raise ValueError("active task dependency cycle at " + task_id)
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in edges[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)
    for task_id in by_id:
        visit(task_id)
    return records


def tasks():
    """Project task IDs/titles/statuses/priorities/dependencies only."""
    return [{key: deepcopy(item.get(key)) for key in _TASK_CORE} for item in _backlog()]


def task(task_id, *, full=False):
    """Return compact task scope; full historical fields require explicit opt-in."""
    for item in _backlog():
        if item["id"] == task_id:
            return deepcopy(item) if full else {
                key: deepcopy(item.get(key)) for key in _TASK_DETAIL}
    raise KeyError(task_id)


def _canonical_path(root, relative):
    if type(relative) is not str:
        raise ValueError("canonical path must be a string")
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("canonical path must remain repository relative")
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("canonical path escapes repository: " + relative)
    return target


def check_catalog(repo_root=None):
    """Check explicit canonical paths, API declarations and metadata joins.

    This is a source-navigation check. It neither requalifies the registered
    components nor reads the archive groups, saved readers or raw model data.
    ZIP/source integrity belongs to the separately recorded migration review.
    An explicit root supplies the catalog and backlog as well as source files.
    """
    root = (Path(repo_root).resolve() if repo_root is not None
            else Path(__file__).resolve().parents[3])
    errors = []
    component_count = documentation_count = evidence_count = prototype_count = None
    owners = None
    try:
        owners = _catalog_at(_canonical_path(
            root, str(_HOME_REL / "docs/work_catalog.json")))
        statuses = owners.get("qualification_status_meaning")
        if type(statuses) is not dict or not statuses:
            raise ValueError("qualification status meanings must be a nonempty object")
        components = _index(_records(owners.get("components"), "components"), "component")
        evidence = _index(_records(owners.get("selected_evidence"), "selected evidence"),
                          "selected evidence")
        prototypes = _index(_records(owners.get("archived_prototypes"), "archived prototypes"),
                            "archived prototype")
        _prototype_counts(list(prototypes.values()))
        relationships = _records(owners.get("known_candidate_relationships"),
                                 "known candidate relationships")
        documentation = _strings(owners.get("required_documentation"),
                                  "required documentation")
        survey = owners.get("historical_survey_reference")
        if type(survey) is not dict:
            raise ValueError("historical survey reference must be an object")
        component_count, documentation_count = len(components), len(documentation)
        evidence_count, prototype_count = len(evidence), len(prototypes)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append("catalog metadata: " + str(exc))
        owners = None
    try:
        active_task_count = len(_backlog(root))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        active_task_count = None
        errors.append("active backlog: " + str(exc))
    if owners is not None:
        for component_id, item in components.items():
            try:
                status = _text(item.get("status"), "qualification status")
                if status not in statuses:
                    raise ValueError("unknown qualification status")
                references = _strings(item.get("evidence_ids"), "evidence references")
                if any(key not in evidence for key in references):
                    raise ValueError("unknown evidence reference")
                path_text = _text(item.get("path"), "component path")
                owner_module = _text(item.get("owner_module"), "owner module")
                if owner_module != path_text.removesuffix(".py").replace("/", "."):
                    raise ValueError("module/path metadata differs")
                apis = _strings(item.get("apis"), "declared APIs")
                path = _canonical_path(root, path_text)
                if not path.is_file():
                    raise ValueError("required canonical owner is missing")
                with path.open("rb") as stream:
                    raw = stream.read(_MAX_COMPONENT_BYTES + 1)
                if len(raw) > _MAX_COMPONENT_BYTES:
                    raise ValueError("component exceeds bounded source size")
                tree = ast.parse(raw, filename=path_text)
                names = {node.name for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                              ast.ClassDef))}
                missing = sorted(set(apis) - names)
                if missing:
                    raise ValueError("declared APIs missing: " + ", ".join(missing))
            except (KeyError, OSError, SyntaxError, TypeError, ValueError) as exc:
                errors.append(component_id + ": " + str(exc))
        for prototype_id, item in prototypes.items():
            try:
                fields = ("canonical_successor_component_id", "canonical_successor_path")
                if item["status"] == "archived_unselected_prototype":
                    if any(key in item for key in fields):
                        raise ValueError("unselected prototype declares an installed successor")
                    continue
                successor_id = _text(item.get(fields[0]), "successor component ID")
                if successor_id not in components:
                    raise ValueError("unknown successor component")
                successor = components[successor_id]
                if _text(item.get(fields[1]), "successor path") != successor.get("path"):
                    raise ValueError("successor path differs from registered owner")
                qualification = _text(item.get("new_canonical_port_qualification"),
                                      "successor qualification")
                if qualification not in statuses or qualification != successor.get("status"):
                    raise ValueError("successor qualification differs from registered owner")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(prototype_id + ": " + str(exc))
        try:
            if _text(survey.get("evidence_id"), "historical survey evidence ID") not in evidence:
                raise ValueError("unknown historical survey evidence reference")
        except (TypeError, ValueError) as exc:
            errors.append("historical survey: " + str(exc))
        for number, item in enumerate(relationships):
            try:
                canonical = _text(item.get("canonical_path"), "candidate canonical path")
                if not any(owner.get("path") == canonical for owner in components.values()):
                    raise ValueError("candidate canonical path has no registered owner")
                if "evidence_id" in item:
                    reference = _text(item["evidence_id"], "candidate evidence ID")
                    if reference not in evidence:
                        raise ValueError("unknown candidate evidence reference")
            except (TypeError, ValueError) as exc:
                errors.append("candidate relationship " + str(number) + ": " + str(exc))
        for relative in documentation:
            try:
                if not _canonical_path(root, relative).is_file():
                    raise ValueError("required documentation is missing")
            except (OSError, ValueError) as exc:
                errors.append(relative + ": " + str(exc))
    return {"schema": "legal-autoformal-work-catalog-check/v1",
            "valid": not errors, "errors": errors,
            "components_checked": component_count,
            "documentation_paths_checked": documentation_count,
            "saved_evidence_records": evidence_count,
            "archived_prototype_records": prototype_count,
            "active_task_count": active_task_count,
            "archive_paths_traversed": 0, "registered_owners_imported": 0,
            "model_or_native_execution": False,
            "qualification_or_proof_admission_performed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summary", action="store_true", help="print the landing metadata")
    mode.add_argument("--tasks", action="store_true", help="print compact active task list")
    mode.add_argument("--component", metavar="ID", help="print one compact implementation owner")
    mode.add_argument("--task", metavar="ID", help="print compact scope for one active task")
    parser.add_argument("--full", action="store_true",
                        help="include historical fields only with explicit --task ID")
    mode.add_argument("--check", action="store_true",
                      help="check explicit canonical files/docs/APIs using metadata and AST")
    mode.add_argument("--section", choices=["components", "selected_evidence",
        "archived_prototypes", "known_candidate_relationships",
        "required_documentation", "historical_survey_reference", "archive_policy", "limits"],
        help="print one curated metadata section")
    parser.add_argument("--repo-root", type=Path,
                        help="explicit canonical checkout root for --check")
    args = parser.parse_args(argv)
    if args.full and args.task is None:
        parser.error("--full requires --task ID")
    try:
        if args.check:
            result = check_catalog(args.repo_root)
        elif args.tasks:
            result = tasks()
        elif args.task:
            result = task(args.task, full=args.full)
        elif args.component is not None:
            result = component(args.component)
        elif args.section:
            result = section(args.section)
        else:
            values = load_catalog()
            result = {"canonical_home": values["canonical_home"],
                      "entry_point": values["entry_point"],
                      "active_backlog": values["active_backlog"],
                      "components": len(values["components"]),
                      "active_tasks": len(_backlog()),
                      "selected_evidence_records": len(values["selected_evidence"]),
                      **_prototype_counts(_records(values.get("archived_prototypes"),
                                                   "archived prototypes")),
                      "scope": "Curated metadata only; use --check or --section NAME."}
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.exit(2, "catalog error: " + str(exc) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 1 if args.check and not result["valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

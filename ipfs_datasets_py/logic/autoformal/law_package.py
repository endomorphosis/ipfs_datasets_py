"""Compile the span cache and entity stitch into one Lean 4.26.0 package.

Term definitions are shared. A ready section imports the terms its clauses
use. Citation modules import a section and its two-hop targets, and nothing
imports a citation module. A green build is a compile receipt. admitted and
formalized stay false. The package has no sorry, admit, axiom, or Mathlib.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lake_probe import MAX_SOURCE, pattern_from_rule, render_norm
from .lean_units import KIND_CODE, statute_fingerprint, term_fingerprint
from .meta_ontology import contains_lookup_phrase, normalize_lookup


REPO_ID = "justicedao/uscode-autoformal-lean-for-law"
TOOLCHAIN = "leanprover/lean4:v4.26.0\n"
MAX_TERM_DEFS = 64
MAX_CITE_IMPORTS = 32
MAX_LAKE_MODULES = 64
STITCH_FILES = (
    "section-neighborhoods.parquet",
    "term-index.parquet",
    "inconsistencies.parquet",
    "lean-units.parquet",
    "logic-occurrences.parquet",
)
REFUSED_NAMES = {
    "kg-logic-index.parquet",
    "kg-meta-ontology.parquet",
    "meta-ontology.parquet",
    "entity-resume-checkpoint.parquet",
    "entity-resume-checkpoint-v2.parquet",
    "resume-checkpoint.parquet",
    "sealed-spans.parquet",
}
_CATEGORY_DIR = {
    "participant": "Participant",
    "act": "Act",
    "object": "Object",
    "deontic": "Deontic",
    "state": "State",
}
_CATEGORY_PREFIX = {
    "participant": "participant",
    "act": "act",
    "object": "object",
    "deontic": "deontic",
    "state": "state",
}
_LEAN_KEYWORDS = {
    "admit", "at", "axiom", "by", "class", "decide", "def", "else", "end",
    "export", "false", "forall", "from", "fun", "if", "import", "in",
    "inductive", "infix", "instance", "let", "match", "meta", "mutual",
    "namespace", "noncomputable", "notation", "open", "partial", "prefix",
    "private", "protected", "set_option", "sorry", "structure", "then",
    "theorem", "true", "universe", "unsafe", "variable", "where", "with",
}
_FORBIDDEN = re.compile(r"\b(?:sorry|admit|axiom)\b")
_MODULE_ATOM = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ROLE_FIELDS = ("actor", "action", "object", "modality")
_ROLE_LISTS = ("conditions", "exceptions", "temporal", "qualifiers")
MANIFEST_FIELDS = (
    "path", "sha256", "module", "legal_id", "term_id", "record_kind",
    "admitted", "formalized", "lake_ok", "lake_error", "reason",
)


class LawPackageError(ValueError):
    """The law package cannot be assembled without inventing a module."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return list(loaded) if isinstance(loaded, list) else []
    return []


def _ids(values: Sequence[Any]) -> str:
    cleaned = sorted({str(item) for item in values if str(item)})
    return json.dumps(cleaned, separators=(",", ":"))


def _category(kind: str, value: str) -> str:
    from .entity_cache import term_category

    return term_category(kind, value)


def _atom_body(value: str) -> str:
    chars = []
    for char in str(value or ""):
        if char.isascii() and char.isalnum():
            chars.append(char)
        else:
            chars.append("_")
    body = re.sub(r"_+", "_", "".join(chars)).strip("_")
    return body


def sanitize_ident(value: str) -> str:
    """Lean def fragment. Empty when the surface cannot be named."""

    body = _atom_body(str(value or "").lower())
    if not body:
        return ""
    if body[0].isdigit():
        body = "n_" + body
    if body in _LEAN_KEYWORDS:
        body = "k_" + body
    return body


def _module_atom(value: str, *, digit_prefix: str = "D") -> str:
    raw = str(value or "").strip()
    if _MODULE_ATOM.fullmatch(raw) and raw not in _LEAN_KEYWORDS:
        return raw
    body = _atom_body(raw)
    if not body:
        return ""
    if body[0].isdigit() or body in _LEAN_KEYWORDS:
        body = digit_prefix + body
    if not body or body[0].isdigit() or body in _LEAN_KEYWORDS:
        return ""
    return body


def _parse_legal_id(legal_id: str) -> tuple[str, str] | None:
    parts = str(legal_id or "").strip().split(":")
    if len(parts) != 4 or parts[0] != "usc" or parts[1] != "us":
        return None
    title = _atom_body(parts[2])
    section = _atom_body(parts[3])
    if not title or not section:
        return None
    return "T" + title, "S" + section


def _lean_string(text: str) -> str | None:
    raw = str(text or "")
    if _FORBIDDEN.search(raw):
        return None
    escaped = (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )
    literal = '"' + escaped + '"'
    if _FORBIDDEN.search(literal):
        return None
    return literal


def _fits(source: str) -> bool:
    return len(source.encode("utf-8")) <= MAX_SOURCE


def law_module(legal_id: str) -> dict[str, Any]:
    """Path and Lean name for one section, or a gap when it will not sanitize."""

    parsed = _parse_legal_id(legal_id)
    if parsed is None:
        return {"gap": True, "legal_id": str(legal_id or ""), "reason": "unsanitizable_legal_id"}
    title, section = parsed
    module = f"Law.Title.{title}.{section}"
    return {
        "gap": False,
        "legal_id": str(legal_id or "").strip(),
        "module": module,
        "namespace": module,
        "path": f"Law/Title/{title}/{section}.lean",
        "section": section,
        "title": title,
    }


def term_module(category: str, surface: str) -> dict[str, Any]:
    """Path and Lean name for one shared term. The shard file starts at S00."""

    cat = str(category or "")
    if cat not in _CATEGORY_DIR:
        return {"gap": True, "reason": "unknown_category", "category": cat}
    key = normalize_lookup(surface)
    ident = sanitize_ident(key)
    if not ident:
        return {"gap": True, "normalized": key, "reason": "unsanitizable_term"}
    prefix = _CATEGORY_PREFIX[cat]
    name = f"{prefix}_{ident}"
    if name in _LEAN_KEYWORDS:
        name = "k_" + name
    directory = _CATEGORY_DIR[cat]
    bucket = "H" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:2]
    namespace = f"Law.Term.{directory}"
    module = f"{namespace}.{bucket}.S00"
    return {
        "bucket": bucket,
        "category": cat,
        "directory": directory,
        "gap": False,
        "module": module,
        "name": name,
        "namespace": namespace,
        "normalized": key,
        "path": f"Law/Term/{directory}/{bucket}/S00.lean",
        "qualified": f"{namespace}.{name}",
    }


def document_module(document_id: str, legal_id: str = "") -> dict[str, Any]:
    """One document file. A legal id selects one section pair and does not merge siblings."""

    atom = _module_atom(document_id)
    if not atom:
        return {
            "document_id": str(document_id or ""),
            "gap": True,
            "reason": "unsanitizable_document",
        }
    if legal_id:
        info = law_module(legal_id)
        if info.get("gap"):
            return info
        suffix = str(info["title"]) + str(info["section"])
        return {
            "document_id": str(document_id or ""),
            "gap": False,
            "legal_id": info["legal_id"],
            "module": f"Law.Document.{atom}.{suffix}",
            "namespace": f"Law.Document.{atom}.{suffix}",
            "path": f"Law/Document/{atom}/{suffix}.lean",
        }
    return {
        "document_id": str(document_id or ""),
        "gap": False,
        "module": f"Law.Document.{atom}",
        "namespace": f"Law.Document.{atom}",
        "path": f"Law/Document/{atom}.lean",
    }


def _import_lines(imports: Sequence[str]) -> list[str]:
    unique: list[str] = []
    for item in imports:
        text = str(item or "").strip()
        if text and text not in unique:
            unique.append(text)
    kernel = [item for item in unique if item == "Law.Kernel"]
    rest = sorted(item for item in unique if item != "Law.Kernel")
    return [f"import {item}" for item in kernel + rest]


def _render_file(namespace: str, imports: Sequence[str], body: Sequence[str]) -> str:
    lines = _import_lines(imports)
    if lines:
        lines.append("")
    lines.append(f"namespace {namespace}")
    lines.append("")
    lines.extend(body)
    if body and body[-1] != "":
        lines.append("")
    lines.append(f"end {namespace}")
    lines.append("")
    return "\n".join(lines)


def render_kernel() -> str:
    """Modality codes, terms, and clauses. The only shared vocabulary."""

    return "\n".join([
        "namespace Law.Kernel",
        "",
        "def modalityObligation : Nat := 0",
        "def modalityPermission : Nat := 1",
        "def modalityProhibition : Nat := 2",
        "",
        "structure Term where",
        "  kindCode : Nat",
        "  fingerprint : Nat",
        "",
        "structure Clause where",
        "  modality : Nat",
        "  participant : Term",
        "  act : Term",
        "  object? : Option Term",
        "  state? : Option Term",
        "",
        "end Law.Kernel",
        "",
    ])


def _statute_lines(fingerprint: int) -> list[str]:
    return [
        f"def statuteFingerprint : Nat := {fingerprint}",
        "def statuteLocked (n : Nat) : Bool := decide (n = statuteFingerprint)",
        "theorem statuteDefined : statuteLocked statuteFingerprint = true := by",
        "  unfold statuteLocked statuteFingerprint",
        "  decide",
        "",
    ]


def _used_lines(used: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in used:
        index = int(item["index"])
        fingerprint = int(item["fingerprint"])
        lines.extend([
            f"def usedStatute{index} : Nat := {fingerprint}",
            f"theorem usedStatuteDefined{index} : usedStatute{index} = {fingerprint} := by",
            f"  unfold usedStatute{index}",
            "  decide",
            "",
        ])
    return lines


def _string_def(name: str, text: str) -> list[str]:
    literal = _lean_string(text)
    if literal is None or not name or name in _LEAN_KEYWORDS:
        return []
    return [f"def {name} : String := {literal}"]


def _mention_lines(mentions: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    surfaces: set[str] = set()
    spans: set[str] = set()
    for item in mentions:
        name = str(item.get("name") or "")
        if not name:
            continue
        if name not in surfaces:
            surfaces.add(name)
            lines.extend(_string_def(name, str(item.get("surface") or "")))
        span_id = str(item.get("span_id") or "")
        span_name = sanitize_ident(span_id)
        span_def = f"{name}_span_{span_name}" if span_name else ""
        if span_id and span_def and span_def not in spans:
            spans.add(span_def)
            lines.extend(_string_def(span_def, span_id))
    if lines:
        lines.append("")
    return lines


def _clause_lines(clause: Mapping[str, Any], index: int) -> list[str]:
    name = str(clause["name"])
    object_ref = str(clause.get("object_ref") or "")
    state_ref = str(clause.get("state_ref") or "")
    lines = [
        f"def {name} : Law.Kernel.Clause := {{",
        f"  modality := {int(clause['modality'])},",
        f"  participant := {clause['participant']},",
        f"  act := {clause['act']},",
        f"  object? := {'some ' + object_ref if object_ref else 'none'},",
        f"  state? := {'some ' + state_ref if state_ref else 'none'}",
        "}",
        render_norm(
            {"modality": int(clause["modality"]), "fingerprint": int(clause["fingerprint"])},
            suffix=str(index),
        ).rstrip(),
        "",
    ]
    return lines


def render_term_module(terms: Sequence[Mapping[str, Any]]) -> str:
    """One shard of shared term defs. Names live in the category namespace."""

    rows = [item for item in terms if isinstance(item, Mapping)]
    if not rows:
        return ""
    namespace = str(rows[0]["namespace"])
    body: list[str] = []
    for item in rows:
        name = str(item["name"])
        kind = int(item["kind_code"])
        fingerprint = int(item["fingerprint"])
        body.extend([
            f"def {name}_kindCode : Nat := {kind}",
            f"def {name}_fingerprint : Nat := {fingerprint}",
            f"def {name} : Law.Kernel.Term := {{ kindCode := {kind}, fingerprint := {fingerprint} }}",
            f"def {name}_locked (k f : Nat) : Bool := decide (k = {name}_kindCode /\\ f = {name}_fingerprint)",
            f"theorem {name}_defined : {name}_locked {name}_kindCode {name}_fingerprint = true := by",
            f"  unfold {name}_locked {name}_kindCode {name}_fingerprint",
            "  decide",
            "",
        ])
    return _render_file(namespace, ["Law.Kernel"], body)


def _section_body(section: Mapping[str, Any], clauses: Sequence[Mapping[str, Any]]) -> list[str]:
    body: list[str] = []
    if section.get("used_only"):
        body.extend(_used_lines(section.get("used") or []))
        return body
    if section.get("header", True):
        body.extend(_statute_lines(int(section["fingerprint"])))
        for span_id in section.get("gaps") or []:
            body.extend(_string_def("gap_" + sanitize_ident(str(span_id)), str(span_id)))
        for slot in section.get("slots") or []:
            body.extend(_string_def("slot_" + sanitize_ident(str(slot)), str(slot)))
        if section.get("unresolved"):
            body.extend(_string_def("unresolvedCitation", "unresolved_citation"))
        codifies = str(section.get("codifies") or "")
        if codifies:
            body.extend(_string_def("codifies", codifies))
        body.extend(_used_lines(section.get("used") or []))
        body.extend(_mention_lines(section.get("mentions") or []))
    for clause in clauses:
        body.extend(_clause_lines(clause, int(clause["norm_index"])))
    return body


def _section_imports(clauses: Sequence[Mapping[str, Any]]) -> list[str]:
    imports = ["Law.Kernel"]
    for clause in clauses:
        for item in clause.get("imports") or []:
            if item not in imports:
                imports.append(str(item))
    return imports


def render_section_module(
    section: Mapping[str, Any],
    clauses: Sequence[Mapping[str, Any]],
    terms: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> str:
    """One section file. Term shards are imported. Other sections are not."""

    prepared = [dict(clause) for clause in clauses]
    if terms:
        for clause in prepared:
            for key in ("participant_key", "act_key", "object_key", "state_key"):
                found = terms.get(clause.get(key)) if clause.get(key) else None
                if found is None:
                    continue
                slot = str(key).split("_", 1)[0]
                target = "object_ref" if slot == "object" else "state_ref" if slot == "state" else slot
                clause[target] = found["qualified"]
                clause.setdefault("imports", [])
                if found["module"] not in clause["imports"]:
                    clause["imports"].append(found["module"])
    return _render_file(
        str(section["namespace"]),
        _section_imports(prepared),
        _section_body(section, prepared),
    )


def render_cite_module(source: Mapping[str, Any], targets: Sequence[Mapping[str, Any]]) -> str:
    """Leaf theorem. Importing this module is refused by the assembler."""

    imports = [str(source["module"])]
    for target in targets:
        module = str(target["module"])
        if module not in imports:
            imports.append(module)
    body: list[str] = []
    for target in targets:
        index = int(target["index"])
        left = f"{source['namespace']}.usedStatute{index}"
        right = f"{target['namespace']}.statuteFingerprint"
        body.extend([
            f"theorem cites_{index} : {left} = {right} := by",
            f"  unfold {left} {right}",
            "  decide",
            "",
        ])
    return _render_file(str(source["cite_namespace"]), imports, body)


def render_document_module(document: Mapping[str, Any], section: Mapping[str, Any]) -> str:
    """One document proves its fingerprint equals its one section."""

    fingerprint = statute_fingerprint(str(section["legal_id"]))
    target = f"{section['module']}.statuteFingerprint"
    body = [
        f"def documentFingerprint : Nat := {fingerprint}",
        f"theorem documentSection : documentFingerprint = {target} := by",
        f"  unfold documentFingerprint {target}",
        "  decide",
        "",
    ]
    return _render_file(str(document["namespace"]), [str(section["module"])], body)


def _largest_prefix(section: Mapping[str, Any], clauses: Sequence[Mapping[str, Any]]) -> tuple[int, str]:
    rows = list(clauses)
    if not rows:
        return 0, render_section_module(section, [], {})
    if not _fits(render_section_module(section, rows[:1], {})):
        return 0, render_section_module(section, [], {})
    best_n = 0
    best = render_section_module(section, [], {})
    low, high = 1, len(rows)
    while low <= high:
        mid = (low + high) // 2
        source = render_section_module(section, rows[:mid], {})
        if _fits(source):
            best_n = mid
            best = source
            low = mid + 1
        else:
            high = mid - 1
    return best_n, best


def _section_shard(section: Mapping[str, Any], index: int) -> tuple[str, str]:
    atom = f"C{index:02d}"
    path = str(Path(str(section["path"])).with_suffix("") / f"{atom}.lean").replace("\\", "/")
    return path, str(section["module"]) + "." + atom


def _bare_section(section: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "codifies": "",
        "fingerprint": section.get("fingerprint", 0),
        "gaps": [],
        "header": False,
        "legal_id": section.get("legal_id", ""),
        "mentions": [],
        "module": section["module"],
        "namespace": section["namespace"],
        "path": section["path"],
        "slots": [],
        "unresolved": False,
        "used": [],
        "used_only": False,
    }


def pack_section_files(
    section: Mapping[str, Any],
    clauses: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str, str, str]]:
    """Primary section file, then C shards when one file would pass 16 KiB."""

    remaining = list(clauses)
    count, source = _largest_prefix(section, remaining)
    files = [(str(section["path"]), str(section["module"]), source, "section")]
    if count:
        remaining = remaining[count:]
    shard = 0
    while remaining:
        path, module = _section_shard(section, shard)
        scoped = _bare_section(section)
        count, source = _largest_prefix(scoped, remaining)
        if count < 1:
            source = render_section_module(scoped, remaining[:1], {})
            count = 1
        files.append((path, module, source, "section_shard"))
        remaining = remaining[count:]
        shard += 1
    return files


def _manifest_row(
    *,
    path: str = "",
    source: str = "",
    module: str = "",
    legal_id: str = "",
    term_ids: Sequence[Any] = (),
    record_kind: str,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "admitted": False,
        "formalized": False,
        "lake_error": "lake_not_run",
        "lake_ok": False,
        "legal_id": legal_id,
        "module": module,
        "path": path,
        "reason": reason,
        "record_kind": record_kind,
        "sha256": _sha(source) if source else "",
        "term_id": _ids(term_ids),
    }


def _stitch_directory(path: str | Path) -> Path:
    directory = Path(path)
    if (directory / "logic-occurrences.parquet").is_file():
        return directory
    nested = directory / "autoformal" / "uscode"
    if (nested / "logic-occurrences.parquet").is_file():
        return nested
    raise LawPackageError("stitch directory is missing logic-occurrences.parquet")


def _read_stitch(directory: Path, name: str) -> list[dict[str, Any]]:
    if name not in STITCH_FILES or name in REFUSED_NAMES:
        raise LawPackageError("refusing to read " + name)
    path = directory / name
    if path.name != name or path.is_symlink() or not path.is_file():
        raise LawPackageError("stitch table is not a file: " + name)
    import pyarrow.parquet as pq

    return [dict(row) for row in pq.read_table(path).to_pylist()]


def _load_spans(path: str | Path) -> dict[str, Any]:
    from .span_cache import SpanCacheError, span_groups_from_parquet

    try:
        return span_groups_from_parquet(path)
    except SpanCacheError as exc:
        raise LawPackageError(str(exc)) from exc


def _rule_values(rule: Mapping[str, Any]) -> list[str]:
    found = [str(rule.get(kind) or "").strip() for kind in _ROLE_FIELDS]
    for kind in _ROLE_LISTS:
        for item in _json_list(rule.get(kind)):
            found.append(str(item or "").strip())
    return [item for item in found if item]


def _covered_by_rule(rule: Mapping[str, Any], normalized: str) -> bool:
    if not normalized:
        return False
    for value in _rule_values(rule):
        if normalize_lookup(value) == normalized or contains_lookup_phrase(value, normalized):
            return True
    return False


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    for item in _json_list(value):
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _state_text(rule: Mapping[str, Any]) -> str:
    return _first_text(rule.get("conditions")) or _first_text(rule.get("temporal"))


def _term_catalog(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    gaps: list[dict[str, Any]] = []
    for row in rows:
        kind = str(row.get("kind") or "")
        value = str(row.get("value") or "")
        if not kind or not value or kind == "decompiled":
            continue
        category = _category(kind, value)
        if category not in _CATEGORY_DIR:
            continue
        groups.setdefault((category, normalize_lookup(value)), []).append(row)
    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    for key, members in groups.items():
        category, normalized = key
        ordered = sorted(members, key=lambda item: str(item.get("term_id") or ""))
        winner = ordered[0]
        named = term_module(category, str(winner.get("value") or normalized))
        term_ids = [str(item.get("term_id") or "") for item in ordered]
        if named.get("gap"):
            gaps.append(_manifest_row(
                legal_id="",
                module="",
                reason=str(named.get("reason") or "unsanitizable_term"),
                record_kind="gap",
                term_ids=term_ids,
            ))
            continue
        catalog[key] = {
            **named,
            "fingerprint": term_fingerprint(str(winner.get("kind") or ""), str(winner.get("value") or "")),
            "kind": str(winner.get("kind") or ""),
            "kind_code": int(KIND_CODE.get(str(winner.get("kind") or ""), 2)),
            "term_ids": [item for item in term_ids if item],
            "value": str(winner.get("value") or ""),
        }
    by_namespace: dict[str, list[dict[str, Any]]] = {}
    for item in catalog.values():
        by_namespace.setdefault(str(item["namespace"]), []).append(item)
    for items in by_namespace.values():
        seen: set[str] = set()
        for item in sorted(items, key=lambda row: str(row["name"])):
            name = str(item["name"])
            if name in seen:
                name = f"{name}_{item['bucket'][1:]}"
                item["name"] = name
                item["qualified"] = str(item["namespace"]) + "." + name
            seen.add(str(item["name"]))
    return catalog, gaps


def _assign_term_shards(catalog: Mapping[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in catalog.values():
        buckets.setdefault((str(item["directory"]), str(item["bucket"])), []).append(item)
    shards: list[dict[str, Any]] = []
    for (directory, bucket), items in sorted(buckets.items()):
        pending = sorted(items, key=lambda row: str(row["name"]))
        shard_index = 0
        while pending:
            current: list[dict[str, Any]] = []
            for item in list(pending):
                trial = current + [item]
                if current and (
                    len(trial) > MAX_TERM_DEFS
                    or not _fits(render_term_module(trial))
                ):
                    break
                current = trial
            if not current:
                current = [pending[0]]
            module = f"Law.Term.{directory}.{bucket}.S{shard_index:02d}"
            path = f"Law/Term/{directory}/{bucket}/S{shard_index:02d}.lean"
            for item in current:
                item["module"] = module
                item["path"] = path
            shards.append({"module": module, "path": path, "terms": current})
            pending = pending[len(current):]
            shard_index += 1
    return shards


def _lookup_term(
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    kind: str,
    value: str,
) -> Mapping[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    category = _category(kind, text)
    if category not in _CATEGORY_DIR:
        return None
    return catalog.get((category, normalize_lookup(text)))


def _prepare_clause(
    span: Mapping[str, Any],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    norm_index: int,
) -> tuple[dict[str, Any] | None, str]:
    rule = span.get("rule") if isinstance(span.get("rule"), Mapping) else {}
    pattern = pattern_from_rule(rule)
    if pattern is None:
        return None, ""
    participant = _lookup_term(catalog, "actor", str(rule.get("actor") or ""))
    act = _lookup_term(catalog, "action", str(rule.get("action") or ""))
    if participant is None or act is None:
        return None, "missing_term"
    object_term = _lookup_term(catalog, "object", str(rule.get("object") or ""))
    state_value = _state_text(rule)
    state_term = None
    if state_value:
        for kind in ("conditions", "temporal", "exceptions", "qualifiers"):
            state_term = _lookup_term(catalog, kind, state_value)
            if state_term is not None:
                break
    span_id = str(span.get("source_span_id") or "")
    ident = sanitize_ident(span_id) or f"n_{norm_index}"
    imports = [str(participant["module"]), str(act["module"])]
    if object_term is not None and object_term["module"] not in imports:
        imports.append(str(object_term["module"]))
    if state_term is not None and state_term["module"] not in imports:
        imports.append(str(state_term["module"]))
    return {
        "act": act["qualified"],
        "fingerprint": int(pattern["fingerprint"]),
        "imports": imports,
        "modality": int(pattern["modality"]),
        "name": "clause_" + ident,
        "norm_index": norm_index,
        "object_ref": "" if object_term is None else str(object_term["qualified"]),
        "participant": participant["qualified"],
        "span_id": span_id,
        "state_ref": "" if state_term is None else str(state_term["qualified"]),
    }, ""


def _mentions_for(
    legal_id: str,
    clauses: Sequence[Mapping[str, Any]],
    occurrences: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    by_span = {
        str(item.get("source_span_id") or ""): item.get("rule") if isinstance(item.get("rule"), Mapping) else {}
        for item in clauses
    }
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in occurrences:
        if str(row.get("legal_id") or "") != legal_id or str(row.get("hit_kind") or "") != "mention":
            continue
        surface = str(row.get("surface") or row.get("normalized") or "").strip()
        normalized = normalize_lookup(surface)
        ident = sanitize_ident(normalized)
        if not surface or not ident:
            continue
        span_id = str(row.get("span_id") or "")
        rule = by_span.get(span_id, {})
        if _covered_by_rule(rule, normalized):
            continue
        key = (ident, span_id)
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "name": "mention_" + ident,
            "span_id": span_id,
            "surface": surface,
        })
    found.sort(key=lambda item: (item["name"], item["span_id"]))
    return found


def _open_slots(clauses: Sequence[Mapping[str, Any]], listed: Sequence[Any]) -> list[str]:
    slots = [str(item) for item in listed if str(item)]
    for clause in clauses:
        rule = clause.get("rule") if isinstance(clause.get("rule"), Mapping) else {}
        span_id = str(clause.get("source_span_id") or "")
        if not span_id:
            continue
        if not str(rule.get("actor") or "").strip():
            slots.append(f"stitch:{span_id}:actor")
        if not str(rule.get("action") or "").strip():
            slots.append(f"stitch:{span_id}:action")
    unique: list[str] = []
    for slot in slots:
        if slot not in unique and _lean_string(slot) is not None:
            unique.append(slot)
    return unique


def _cite_target_module(legal_id: str, ready: set[str], not_ready: set[str]) -> dict[str, Any] | None:
    if legal_id in not_ready:
        return None
    info = law_module(legal_id)
    if info.get("gap"):
        return None
    info["stub"] = legal_id not in ready
    info["fingerprint"] = statute_fingerprint(legal_id)
    return info


def _lakefile() -> str:
    return "\n".join([
        "import Lake",
        "open Lake DSL",
        "",
        "package law",
        "",
        "@[default_target]",
        "lean_lib Law where",
        "  roots := #[]",
        "  globs := #[`Law.+]",
        "",
    ])


def _module_of(path: str) -> str:
    relative = Path(path)
    if relative.suffix != ".lean":
        return ""
    return ".".join(relative.with_suffix("").parts)


def _imports_of(source: str) -> list[str]:
    found = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            parts = stripped.split()
            if len(parts) >= 2:
                found.append(parts[1])
    return found


def _reject_generated(files: Mapping[str, str]) -> None:
    graph: dict[str, list[str]] = {}
    for path, source in files.items():
        if not path.startswith("Law/") or not path.endswith(".lean"):
            continue
        if _FORBIDDEN.search(source):
            raise LawPackageError("refusing sorry, admit, or axiom in " + path)
        module = _module_of(path)
        imports = _imports_of(source)
        for target in imports:
            if not target.startswith("Law."):
                raise LawPackageError("refusing import " + target)
            if target.startswith("Law.Cite"):
                raise LawPackageError("refusing to import cite module " + target)
        if "/Cite/" in path and any(not item.startswith("Law.Title.") for item in imports):
            raise LawPackageError("cite module imports a non-section")
        if "/Term/" in path and imports != ["Law.Kernel"]:
            raise LawPackageError("term module imports more than the kernel")
        if "/Document/" in path and (len(imports) != 1 or not imports[0].startswith("Law.Title.")):
            raise LawPackageError("document module must import one section")
        if "/Title/" in path and any(
            not item.startswith("Law.Kernel") and not item.startswith("Law.Term.")
            for item in imports
        ):
            raise LawPackageError("section module imports another section")
        graph[module] = imports
    for module, imports in graph.items():
        for target in imports:
            if target not in graph:
                raise LawPackageError("missing imported module " + target)
    color: dict[str, int] = {}

    def visit(module: str) -> None:
        state = color.get(module, 0)
        if state == 1:
            raise LawPackageError("import cycle at " + module)
        if state == 2:
            return
        color[module] = 1
        for target in graph.get(module, []):
            visit(target)
        color[module] = 2

    for module in graph:
        visit(module)


def _neighborhood_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    found = {}
    for row in rows:
        legal_id = str(row.get("span_legal_id") or row.get("legal_id") or "")
        if legal_id:
            found[legal_id] = row
    return found


def _codifies(row: Mapping[str, Any]) -> str:
    if "codifies" not in row:
        return ""
    value = row.get("codifies")
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if str(item))
    else:
        text = str(value or "").strip()
        if text.startswith("["):
            items = [str(item) for item in _json_list(text) if str(item)]
            text = ", ".join(items)
    return text if _lean_string(text) is not None else ""


def assemble_law_package(stitch_dir: str | Path, spans: str | Path) -> dict[str, Any]:
    """Read the five stitch tables and sealed-spans.parquet. Do not open the logic index."""

    directory = _stitch_directory(stitch_dir)
    neighborhoods = _neighborhood_map(_read_stitch(directory, "section-neighborhoods.parquet"))
    term_rows = _read_stitch(directory, "term-index.parquet")
    inconsistencies = _read_stitch(directory, "inconsistencies.parquet")
    _read_stitch(directory, "lean-units.parquet")
    occurrences = _read_stitch(directory, "logic-occurrences.parquet")
    grouped = _load_spans(spans)
    ready = set(grouped["ready"])
    not_ready = set(grouped["not_ready"])
    catalog, gaps = _term_catalog(term_rows)
    shards = _assign_term_shards(catalog)
    files: dict[str, str] = {
        "lean-toolchain": TOOLCHAIN,
        "Law/Kernel.lean": render_kernel(),
    }
    manifest = [
        _manifest_row(path="lean-toolchain", source=TOOLCHAIN, module="", record_kind="toolchain"),
        _manifest_row(
            path="Law/Kernel.lean",
            source=files["Law/Kernel.lean"],
            module="Law.Kernel",
            record_kind="kernel",
        ),
    ]
    manifest.extend(gaps)
    for shard in shards:
        source = render_term_module(shard["terms"])
        files[shard["path"]] = source
        term_ids = [term_id for item in shard["terms"] for term_id in item["term_ids"]]
        manifest.append(_manifest_row(
            path=shard["path"],
            source=source,
            module=shard["module"],
            record_kind="term_shard",
            term_ids=term_ids,
            reason="" if _fits(source) else "source_overflow",
        ))
        for item in shard["terms"]:
            manifest.append(_manifest_row(
                path=shard["path"],
                source=source,
                module=str(item["qualified"]),
                record_kind="term",
                term_ids=item["term_ids"],
            ))
    entity_legal = {}
    documents: dict[str, set[str]] = {}
    for row in occurrences:
        legal_id = str(row.get("legal_id") or "")
        entity_id = str(row.get("entity_id") or "")
        document_id = str(row.get("document_id") or "")
        if entity_id and legal_id:
            entity_legal[entity_id] = legal_id
        if document_id and legal_id:
            documents.setdefault(document_id, set()).add(legal_id)
    cited_modules: dict[str, dict[str, Any]] = {}
    for legal_id in sorted(ready):
        info = law_module(legal_id)
        if info.get("gap"):
            manifest.append(_manifest_row(
                legal_id=legal_id,
                reason="unsanitizable_legal_id",
                record_kind="gap",
            ))
            continue
        clauses = list(grouped["statutes"].get(legal_id, []))
        neighborhood = neighborhoods.get(legal_id, {})
        targets = [str(item) for item in _json_list(neighborhood.get("definition_targets")) if str(item)]
        unique_targets: list[str] = []
        for target in targets:
            if target not in unique_targets:
                unique_targets.append(target)
        unique_targets.sort()
        used = []
        cite_targets = []
        for target_id in unique_targets:
            target = _cite_target_module(target_id, ready, not_ready)
            if target is None:
                manifest.append(_manifest_row(
                    legal_id=legal_id,
                    reason="citation_not_ready",
                    record_kind="gap",
                    term_ids=[target_id],
                ))
                continue
            index = len(used)
            used.append({"fingerprint": target["fingerprint"], "index": index})
            cite_targets.append({
                "fingerprint": target["fingerprint"],
                "index": index,
                "legal_id": target_id,
                "module": target["module"],
                "namespace": target["namespace"],
                "stub": target["stub"],
            })
            cited_modules[target_id] = target
        reasons = [str(item) for item in _json_list(neighborhood.get("reasons"))]
        gap_ids = [str(item) for item in _json_list(neighborhood.get("gap_span_ids")) if str(item)]
        for item in grouped["gaps"].get(legal_id, []):
            span_id = str(item.get("source_span_id") or "")
            if span_id and span_id not in gap_ids:
                gap_ids.append(span_id)
        prepared = []
        norm_index = 0
        for clause in clauses:
            built, reason = _prepare_clause(clause, catalog, norm_index)
            if built is None:
                if reason:
                    manifest.append(_manifest_row(
                        legal_id=legal_id,
                        path=str(info["path"]),
                        reason=reason,
                        record_kind="gap",
                        term_ids=[str(clause.get("source_span_id") or "")],
                    ))
                continue
            prepared.append(built)
            norm_index += 1
        section = {
            **info,
            "codifies": _codifies(neighborhood),
            "fingerprint": statute_fingerprint(legal_id),
            "gaps": gap_ids,
            "header": True,
            "mentions": _mentions_for(legal_id, clauses, occurrences),
            "slots": _open_slots(clauses, _json_list(neighborhood.get("open_stitch_slots"))),
            "unresolved": "unresolved_citation" in reasons,
            "used": used,
            "used_only": False,
        }
        for path, module, source, kind in pack_section_files(section, prepared):
            files[path] = source
            manifest.append(_manifest_row(
                path=path,
                source=source,
                module=module,
                legal_id=legal_id,
                record_kind=kind,
                reason="" if _fits(source) else "source_overflow",
            ))
        for slot in section["slots"]:
            manifest.append(_manifest_row(
                path=str(info["path"]),
                legal_id=legal_id,
                reason="open_stitch_slot",
                record_kind="gap",
                term_ids=[slot],
            ))
        for span_id in gap_ids:
            manifest.append(_manifest_row(
                path=str(info["path"]),
                legal_id=legal_id,
                reason="gap_span",
                record_kind="gap",
                term_ids=[span_id],
            ))
        if section["unresolved"]:
            manifest.append(_manifest_row(
                path=str(info["path"]),
                legal_id=legal_id,
                reason="unresolved_citation",
                record_kind="gap",
            ))
        for offset in range(0, len(cite_targets), MAX_CITE_IMPORTS - 1):
            chunk = cite_targets[offset:offset + MAX_CITE_IMPORTS - 1]
            shard = offset // (MAX_CITE_IMPORTS - 1)
            cite_path = f"Law/Cite/{info['title']}/{info['section']}/C{shard:02d}.lean"
            cite_module = f"Law.Cite.{info['title']}.{info['section']}.C{shard:02d}"
            source = {
                "cite_namespace": f"Law.Cite.{info['title']}.{info['section']}",
                "module": info["module"],
                "namespace": info["namespace"],
            }
            cite_source = render_cite_module(source, chunk)
            files[cite_path] = cite_source
            manifest.append(_manifest_row(
                path=cite_path,
                source=cite_source,
                module=cite_module,
                legal_id=legal_id,
                record_kind="cite",
                term_ids=[str(item["legal_id"]) for item in chunk],
                reason="" if _fits(cite_source) else "source_overflow",
            ))
    for legal_id, target in sorted(cited_modules.items()):
        if not target.get("stub"):
            continue
        if target["path"] in files:
            continue
        source = _render_file(str(target["namespace"]), ["Law.Kernel"], _statute_lines(int(target["fingerprint"])))
        files[target["path"]] = source
        manifest.append(_manifest_row(
            path=target["path"],
            source=source,
            module=target["module"],
            legal_id=legal_id,
            record_kind="stub",
            reason="fingerprint_stub",
        ))
    pending_ids: dict[str, list[str]] = {}
    for legal_id in not_ready:
        spans_for = [
            str(item.get("source_span_id") or "")
            for item in grouped["pending"].get(legal_id, [])
            if str(item.get("source_span_id") or "")
        ]
        pending_ids[legal_id] = spans_for
    for row in inconsistencies:
        if str(row.get("kind") or "") != "section_not_ready":
            continue
        legal_id = entity_legal.get(str(row.get("entity_id") or ""), "")
        if not legal_id or legal_id in ready:
            continue
        span_id = str(row.get("span_id") or "")
        bucket = pending_ids.setdefault(legal_id, [])
        if span_id and span_id not in bucket:
            bucket.append(span_id)
        not_ready.add(legal_id)
    for legal_id in sorted(not_ready):
        if legal_id in ready:
            continue
        manifest.append(_manifest_row(
            legal_id=legal_id,
            reason="section_not_ready",
            record_kind="gap",
            term_ids=pending_ids.get(legal_id, []),
        ))
    for document_id, legal_ids in sorted(documents.items()):
        chosen = sorted(legal_id for legal_id in legal_ids if legal_id in ready and not law_module(legal_id).get("gap"))
        if not chosen:
            continue
        pairs = [(document_id, legal_id) for legal_id in chosen] if len(chosen) > 1 else [(document_id, "")]
        for doc_id, legal_id in pairs:
            info = document_module(doc_id, legal_id)
            target_id = legal_id or chosen[0]
            if info.get("gap"):
                manifest.append(_manifest_row(
                    legal_id=target_id,
                    reason=str(info.get("reason") or "unsanitizable_document"),
                    record_kind="gap",
                    term_ids=[doc_id],
                ))
                continue
            section = law_module(target_id)
            source = render_document_module(info, section)
            files[str(info["path"])] = source
            manifest.append(_manifest_row(
                path=str(info["path"]),
                source=source,
                module=str(info["module"]),
                legal_id=target_id,
                record_kind="document",
                term_ids=[doc_id],
            ))
    modules = [_module_of(path) for path in files if path.startswith("Law/") and path.endswith(".lean")]
    lakefile = _lakefile()
    if "Mathlib" in lakefile or re.search(r"\brequire\b", lakefile):
        raise LawPackageError("refusing a Mathlib requirement")
    files["lakefile.lean"] = lakefile
    manifest.append(_manifest_row(path="lakefile.lean", source=lakefile, module="law", record_kind="package"))
    _reject_generated(files)
    manifest.sort(key=lambda row: (
        row["record_kind"], row["path"], row["module"], row["legal_id"], row["term_id"], row["reason"],
    ))
    for row in manifest:
        row["admitted"] = False
        row["formalized"] = False
        row["lake_ok"] = False
    return {
        "admitted": False,
        "files": files,
        "formalized": False,
        "manifest": manifest,
        "modules": sorted(module for module in modules if module),
    }


def write_law_package(out_dir: str | Path, assembled: Mapping[str, Any]) -> Path:
    """Write the package. Refuses the logic index, the span cache, and resume checkpoints."""

    out = Path(out_dir)
    if out.name in REFUSED_NAMES or out.is_symlink():
        raise LawPackageError("refusing to write " + out.name)
    out.mkdir(parents=True, exist_ok=True)
    files = dict(assembled.get("files") or {})
    wanted = set(files)
    keep = {"autoformal/law/manifest.sha256"}
    if out.exists():
        for path in sorted(out.rglob("*"), reverse=True):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(out).as_posix()
            if relative in wanted or relative in keep:
                continue
            managed = relative in {"lakefile.lean", "lean-toolchain"} or relative.startswith("Law/") or relative.startswith("autoformal/law/")
            if not managed:
                continue
            if path.name in REFUSED_NAMES:
                raise LawPackageError("refusing to replace " + path.name)
            path.unlink()
    for relative, source in sorted(files.items()):
        path = Path(relative)
        if path.name in REFUSED_NAMES or any(part in REFUSED_NAMES for part in path.parts):
            raise LawPackageError("refusing to write " + relative)
        target = out / path
        if target.is_symlink():
            raise LawPackageError("refusing to write " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(source), encoding="utf-8")
    rows = []
    for row in assembled.get("manifest") or []:
        item = {field: row.get(field, "") for field in MANIFEST_FIELDS}
        item["admitted"] = False
        item["formalized"] = False
        item["lake_ok"] = bool(row.get("lake_ok"))
        rows.append(item)
    return _write_manifest(out, rows)


def _write_manifest(out: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([
        ("path", pa.string()),
        ("sha256", pa.string()),
        ("module", pa.string()),
        ("legal_id", pa.string()),
        ("term_id", pa.string()),
        ("record_kind", pa.string()),
        ("admitted", pa.bool_()),
        ("formalized", pa.bool_()),
        ("lake_ok", pa.bool_()),
        ("lake_error", pa.string()),
        ("reason", pa.string()),
    ])
    normalized = []
    for row in rows:
        item = {field: row.get(field, "") for field in MANIFEST_FIELDS}
        item["admitted"] = False
        item["formalized"] = False
        item["lake_ok"] = bool(row.get("lake_ok"))
        normalized.append(item)
    manifest = out / "autoformal" / "law" / "manifest.parquet"
    if manifest.name in REFUSED_NAMES:
        raise LawPackageError("refusing to write manifest.parquet")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if manifest.is_symlink():
        raise LawPackageError("refusing to write manifest.parquet")
    if normalized:
        table = pa.Table.from_pylist(normalized, schema=schema)
    else:
        table = pa.table({field.name: pa.array([], type=field.type) for field in schema}, schema=schema)
    temporary = manifest.with_name(".manifest.parquet.tmp")
    if temporary.exists() and not temporary.is_symlink():
        temporary.unlink()
    pq.write_table(table, temporary)
    os.replace(temporary, manifest)
    return manifest


def _manifest_hash(out_dir: Path) -> str:
    manifest = out_dir / "autoformal" / "law" / "manifest.parquet"
    if not manifest.is_file() or manifest.is_symlink():
        raise LawPackageError("manifest.parquet is not a file")
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def upload_law_package(out_dir: str | Path, *, repo_id: str = REPO_ID) -> dict[str, Any]:
    """Upload only justicedao/uscode-autoformal-lean-for-law. A repeated manifest hash is skipped."""

    if repo_id != REPO_ID:
        raise LawPackageError("refusing to upload " + str(repo_id))
    out = Path(out_dir)
    for name in REFUSED_NAMES:
        if (out / name).exists():
            raise LawPackageError("refusing to upload " + name)
    digest = _manifest_hash(out)
    stamp = out / "autoformal" / "law" / "manifest.sha256"
    if stamp.is_file() and not stamp.is_symlink() and stamp.read_text(encoding="utf-8").strip() == digest:
        return {
            "admitted": False,
            "fingerprint": digest,
            "formalized": False,
            "skipped": True,
            "uploaded": False,
        }
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        folder_path=str(out),
        repo_id=repo_id,
        repo_type="dataset",
        ignore_patterns=["autoformal/law/manifest.sha256", *REFUSED_NAMES],
        commit_message="autoformal lean for law",
    )
    stamp.write_text(digest + "\n", encoding="utf-8")
    return {
        "admitted": False,
        "fingerprint": digest,
        "formalized": False,
        "skipped": False,
        "uploaded": True,
    }


def _installed_lake() -> str:
    toolchain = Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin/lake"
    if toolchain.is_file():
        return str(toolchain)
    found = shutil.which("lake")
    if not found:
        return ""
    try:
        proc = subprocess.run(
            [found, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if "4.26.0" in (proc.stdout or "") + (proc.stderr or ""):
        return found
    return ""


def _law_modules(out_dir: Path) -> list[str]:
    law = out_dir / "Law"
    if not law.is_dir():
        return []
    modules = []
    for path in sorted(law.rglob("*.lean")):
        if path.is_file() and not path.is_symlink():
            modules.append(".".join(path.relative_to(out_dir).with_suffix("").parts))
    return modules


def lake_build_law(out_dir: str | Path) -> dict[str, Any]:
    """Build at most 64 modules with an already installed Lean 4.26.0. Not an admit."""

    out = Path(out_dir)
    modules = _law_modules(out)
    if len(modules) > MAX_LAKE_MODULES:
        return {
            "admitted": False,
            "built": [],
            "formalized": False,
            "lake_error": "lake_module_cap",
            "lake_ok": False,
        }
    binary = _installed_lake()
    if not binary:
        return {
            "admitted": False,
            "built": [],
            "formalized": False,
            "lake_error": "toolchain_unavailable",
            "lake_ok": False,
        }
    env = os.environ.copy()
    bindir = str(Path(binary).parent)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(
            [binary, "build"],
            cwd=str(out),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "admitted": False,
            "built": [],
            "formalized": False,
            "lake_error": "lake_failed",
            "lake_ok": False,
            "detail": str(exc),
        }
    text = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and "error:" not in text
    return {
        "admitted": False,
        "built": modules if ok else [],
        "formalized": False,
        "lake_error": "" if ok else "lake_failed",
        "lake_ok": ok,
    }


def apply_lake_result(out_dir: str | Path, result: Mapping[str, Any]) -> None:
    """Record the compile receipt. formalized stays false."""

    import pyarrow.parquet as pq

    out = Path(out_dir)
    manifest = out / "autoformal" / "law" / "manifest.parquet"
    rows = pq.read_table(manifest).to_pylist()
    built = set(result.get("built") or [])
    error = str(result.get("lake_error") or "")
    ok = bool(result.get("lake_ok"))
    for row in rows:
        row["admitted"] = False
        row["formalized"] = False
        module_name = str(row.get("module") or "")
        path_module = _module_of(str(row.get("path") or ""))
        built_row = ok and str(row.get("record_kind") or "") != "gap" and (
            module_name in built or path_module in built
        )
        if built_row:
            row["lake_error"] = ""
            row["lake_ok"] = True
        else:
            row["lake_error"] = error or "lake_not_run"
            row["lake_ok"] = False
    _write_manifest(out, rows)

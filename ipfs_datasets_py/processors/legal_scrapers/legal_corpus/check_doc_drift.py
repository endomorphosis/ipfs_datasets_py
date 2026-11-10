"""Compare landed version constants, docs, and display contracts.

The checker reads kind, adapter, and view modules. It fails when
``instrument-modules.md``, ``adapters.md``, or a view doc omits one of
those constants or cites a different string for its name. It does not
edit those docs, the board, or a supervisor. Display contracts are evaluated
in memory with Node's TypeScript support; their accepted kind versions must
match the Python kind exports exactly.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_CITE = re.compile(r"`([A-Z][A-Z0-9_]*)`(?:\s+is|\s+to)?\s+(?:\|\s*)?`([^`]+)`")
_CONST = re.compile(r"(?m)^(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_VIEW_MARKERS = (
    "_SCHEMA",
    "_VERSION",
    "_VIEW",
    "_INTERFACE_ID",
    "_CONTRACT_ID",
)
_DOC_LABELS = {
    "kinds": "legal_corpus/docs/instrument-modules.md",
    "adapters": "legal_corpus/docs/adapters.md",
    "view-site": "worldwidelaws.github.io/docs/worldwide/instrument-views.md",
    "view-swissknife": "swissknife/src/services/legal-corpus-views/README.md",
}

_VIEW_CONTRACT_PROBE = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { stripTypeScriptTypes } = require('node:module');

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const context = vm.createContext({});
  const modules = new Map();
  function load(filename) {
    if (modules.has(filename)) return modules.get(filename);
    const source = stripTypeScriptTypes(fs.readFileSync(filename, 'utf8'));
    const module = new vm.SourceTextModule(source, { context, identifier: filename });
    modules.set(filename, module);
    return module;
  }
  const contract = load(path.resolve(input.contract));
  await contract.link((specifier, parent) => {
    if (!specifier.startsWith('.')) throw new Error(`non-relative import ${specifier}`);
    let filename = path.resolve(path.dirname(parent.identifier), specifier);
    if (filename.endsWith('.js')) filename = filename.slice(0, -3) + '.ts';
    else if (!path.extname(filename)) filename += '.ts';
    return load(filename);
  });
  await contract.evaluate({ timeout: 1000 });
  const exported = contract.namespace;
  const kinds = exported.KIND_VERSIONS;
  const acceptance = {};
  for (const version of new Set([...input.candidates, ...Object.values(kinds)])) {
    try {
      acceptance[version] = exported.acceptInstrumentVersion(version);
    } catch {
      acceptance[version] = null;
    }
  }
  const bindings = exported.VIEW_BINDINGS.map(binding => ({
    version: binding.kindVersion,
    resolved: exported.kindVersionForView(binding.viewId),
  }));
  console.log(JSON.stringify({ kinds, acceptance, bindings }));
})().catch(error => {
  console.error(String(error));
  process.exitCode = 1;
});
"""


@dataclass(frozen=True)
class VersionConstant:
    """One version string assigned by a landed module."""

    family: str
    module: str
    name: str
    value: str


@dataclass(frozen=True)
class Drift:
    """A doc omitted a version constant or cited a different string."""

    kind: str
    document: str
    module: str
    name: str
    value: str
    cited: str = ""


def _corpus() -> Path:
    return Path(__file__).resolve().parent


def _lift() -> Path:
    """Workspace that holds the SwissKnife view package.

    ``resolve`` follows the datasets symlink, so the search starts from both
    the linked path and the path used to load this file.
    """

    marker = Path("swissknife/src/services/legal-corpus-views")
    origins = (Path(__file__).resolve().parent, Path(__file__).absolute().parent)
    for origin in origins:
        for parent in (origin, *origin.parents):
            if (parent / marker).is_dir():
                return parent
    raise RuntimeError("SwissKnife legal-corpus view package was not found")


def _string_literals(expr: str) -> tuple[str, ...]:
    found = re.findall(r"'([^'\\]*)'|\"([^\"\\]*)\"", expr)
    return tuple(item.strip() for pair in found for item in pair if item.strip())


def _pinned_expected(expr: str) -> tuple[str, ...] | None:
    match = re.search(r"\bpinned\s*\(", expr)
    if match is None:
        return None
    depth = 1
    args: list[str] = []
    buf: list[str] = []
    for char in expr[match.end():]:
        if char in "({[":
            depth += 1
            buf.append(char)
        elif char in ")}]":
            depth -= 1
            if depth == 0:
                args.append("".join(buf))
                break
            buf.append(char)
        elif char == "," and depth == 1:
            args.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    if len(args) < 2:
        return ()
    return _string_literals(args[1])


def _view_version_name(name: str) -> bool:
    return name.isupper() and any(marker in name for marker in _VIEW_MARKERS)


def _statements(text: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    for match in _CONST.finditer(text):
        depth = 0
        end = match.end()
        while end < len(text):
            char = text[end]
            if char in "({[":
                depth += 1
            elif char in ")}]":
                depth = max(0, depth - 1)
            elif char == ";" and depth == 0:
                end += 1
                break
            end += 1
        found.append((match.group(1), text[match.end():end]))
    return tuple(found)


def read_view_text(module: str, text: str, family: str) -> tuple[VersionConstant, ...]:
    """Read version constants from one TypeScript view module."""

    rows: list[VersionConstant] = []
    for name, expr in _statements(text):
        if not _view_version_name(name):
            continue
        pinned = _pinned_expected(expr)
        values = pinned if pinned is not None else _string_literals(expr)
        for value in dict.fromkeys(values):
            rows.append(VersionConstant(family, module, name, value))
    return tuple(rows)


def read_view_tree(directory: Path, family: str) -> tuple[VersionConstant, ...]:
    """Read version constants from the TypeScript modules in one view tree."""

    if not directory.is_dir():
        return ()
    rows: list[VersionConstant] = []
    for path in sorted(directory.glob("*.ts")):
        if path.name.endswith(".test.ts") or path.name.endswith(".d.ts"):
            continue
        rows.extend(read_view_text(path.name, path.read_text(encoding="utf-8"), family))
    return tuple(rows)


def _index():
    path = _corpus() / "module_index_v1.py"
    spec = importlib.util.spec_from_file_location("lcm_doc_drift_index", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module index is missing at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _python_constants(index, relative: str, family: str) -> tuple[VersionConstant, ...]:
    loaded = index._load_file(
        _corpus() / relative,
        "lcm_doc_drift_" + relative.replace("/", "_").removesuffix(".py"),
    )
    rows: list[VersionConstant] = []
    for name, value in vars(loaded).items():
        if not index._version_name(name):
            continue
        for item in index._strings(value):
            rows.append(VersionConstant(family, relative, name, item))
    return tuple(rows)


def landed_constants() -> tuple[VersionConstant, ...]:
    """Version constants from the landed kind, adapter, and view modules."""

    index = _index()
    rows: list[VersionConstant] = []
    for item in index.KIND_INDEX:
        rows.extend(_python_constants(index, item.path, "kinds"))
    rows.extend(_python_constants(index, "instrument_v1.py", "kinds"))
    for item in index.ADAPTER_INDEX:
        rows.extend(_python_constants(index, item.path, "adapters"))
    site, _site_doc, swissknife, _swissknife_doc = _view_paths()
    rows.extend(read_view_tree(site, "view-site"))
    rows.extend(read_view_tree(swissknife, "view-swissknife"))
    return tuple(rows)


def _view_paths() -> tuple[Path, Path, Path, Path]:
    lift = _lift()
    site_root = None
    for candidate in (lift / "worldwidelaws.github.io", lift.parent / "worldwidelaws.github.io"):
        views = candidate / "src/lib/worldwide/views"
        doc = candidate / "docs/worldwide/instrument-views.md"
        if views.is_dir() and doc.is_file():
            site_root = candidate
            break
    if site_root is None:
        site_root = lift.parent / "worldwidelaws.github.io"
    swissknife = lift / "swissknife/src/services/legal-corpus-views"
    return (
        site_root / "src/lib/worldwide/views",
        site_root / "docs/worldwide/instrument-views.md",
        swissknife,
        swissknife / "README.md",
    )


def landed_documents() -> dict[str, str]:
    """Doc texts keyed by the module family that must be quoted there."""

    corpus = _corpus()
    site_views, site_doc, swissknife_views, swissknife_doc = _view_paths()
    found = {
        "kinds": corpus / "docs/instrument-modules.md",
        "adapters": corpus / "docs/adapters.md",
        "view-site": site_doc,
        "view-swissknife": swissknife_doc,
    }
    del site_views, swissknife_views
    return {
        family: path.read_text(encoding="utf-8")
        for family, path in found.items()
        if path.is_file()
    }


def _public_names(name: str) -> tuple[str, ...]:
    if name.startswith("_") and not name.startswith("__"):
        return (name, name[1:])
    return (name,)


def _module_sections(text: str, modules: Sequence[str]) -> dict[str, str]:
    """Bind citations to the modules named in each markdown section.

    Short documents without source paths can still quote constants directly.
    Once paths are supplied, another module's section cannot satisfy a quote.
    """

    found: dict[str, list[str]] = {module: [] for module in modules}
    for section in re.split(r"(?m)(?=^#{1,6} )", text):
        paths = re.findall(r"`([^`]+)`", section)
        for module in modules:
            if any(path == module or path.endswith("/" + module) for path in paths):
                found[module].append(section)
    if not any(found.values()):
        return dict.fromkeys(modules, text)
    return {module: "\n".join(sections) for module, sections in found.items()}


def find_drift(
    constants: Sequence[VersionConstant],
    documents: Mapping[str, str],
) -> tuple[Drift, ...]:
    """Return omissions and different citations. Docs are not modified."""

    grouped: dict[str, list[VersionConstant]] = {}
    for item in constants:
        grouped.setdefault(item.family, []).append(item)
    findings: list[Drift] = []
    for family, rows in grouped.items():
        if family not in documents:
            findings.append(Drift("omitted", family, rows[0].module, "document", family))
            continue
        by_module: dict[str, list[VersionConstant]] = {}
        all_tokens = set(re.findall(r"`([^`]*)`", documents[family]))
        seen: set[str] = set()
        for row in rows:
            by_module.setdefault(row.module, []).append(row)
            if row.value not in seen and row.value not in all_tokens:
                findings.append(Drift("omitted", family, row.module, row.name, row.value))
            seen.add(row.value)
        scoped = _module_sections(documents[family], tuple(by_module))
        for module, module_rows in by_module.items():
            text = scoped[module]
            allowed: dict[str, set[str]] = {}
            for row in module_rows:
                for name in _public_names(row.name):
                    allowed.setdefault(name, set()).add(row.value)
            cited_seen: set[tuple[str, str]] = set()
            for name, cited in _CITE.findall(text):
                if name not in allowed or cited in allowed[name]:
                    continue
                pair = (name, cited)
                if pair in cited_seen:
                    continue
                cited_seen.add(pair)
                findings.append(Drift(
                    "different_string", family, module, name,
                    ", ".join(sorted(allowed[name])), cited,
                ))
    return tuple(sorted(findings, key=lambda item: (
        item.kind, item.document, item.module, item.name, item.value, item.cited,
    )))


def _missing_view_tree(constants: Sequence[VersionConstant], family: str, directory: Path) -> Drift | None:
    if directory.is_dir() and any(row.family == family for row in constants):
        return None
    return Drift("omitted", family, directory.as_posix(), "view-modules", "view-modules")


def python_kind_versions() -> dict[str, str]:
    """Read the six instrument kinds and their defining Python exports.

    ``status_v1`` pins a vocabulary, rather than an instrument kind. The
    shared interface's KINDS tuple determines which modules a view accepts.
    """

    index = _index()
    instrument = index._load_file(_corpus() / "instrument_v1.py", "lcm_view_instrument")
    found: dict[str, str] = {}
    for kind in instrument.KINDS:
        module = index._load_file(_corpus() / f"kinds/{kind}_v1.py", f"lcm_view_kind_{kind}")
        version = module.INTERFACE_ID
        if not isinstance(version, str) or not version:
            raise ValueError(f"kinds/{kind}_v1.py has no kind interface id")
        found[kind] = version
    return found


def probe_view_contract(directory: Path, candidates: Sequence[str]) -> dict:
    """Evaluate the landed TypeScript and its relative imports without writes."""

    proc = subprocess.run(
        ["node", "--no-warnings", "--experimental-vm-modules", "-e", _VIEW_CONTRACT_PROBE],
        input=json.dumps({"contract": str(directory / "contract.ts"), "candidates": list(candidates)}),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or f"node exit {proc.returncode}").strip())
    return json.loads(proc.stdout)


def check_view_contracts(constants: Sequence[VersionConstant] | None = None) -> tuple[Drift, ...]:
    """Require exact kind mappings and exercise each contract's acceptance guard."""

    expected = python_kind_versions()
    versions = set(expected.values())
    if constants is None:
        constants = landed_constants()
    interfaces = {
        row.value for row in constants if row.family == "kinds" and row.name == "INTERFACE_ID"
    }
    candidates = sorted(versions | interfaces | {version + ".unknown" for version in versions})
    site, _site_doc, swissknife, _swissknife_doc = _view_paths()
    findings: list[Drift] = []
    for family, directory in (("view-site", site), ("view-swissknife", swissknife)):
        try:
            result = probe_view_contract(directory, candidates)
            actual = result["kinds"]
            for kind in sorted(expected.keys() | actual.keys()):
                version = expected.get(kind, "<absent>")
                rendered = actual.get(kind, "<missing>")
                if rendered != version:
                    findings.append(Drift(
                        "different_string", family, "contract.ts", f"KIND_VERSIONS.{kind}",
                        version, str(rendered),
                    ))
            for version in sorted(set(candidates) | set(actual.values())):
                accepted = result["acceptance"][version]
                wanted = version if version in versions else None
                if accepted != wanted:
                    findings.append(Drift(
                        "different_string", family, "contract.ts", "acceptInstrumentVersion",
                        wanted or "<rejected>", str(accepted) if accepted is not None else "<rejected>",
                    ))
            bound = set()
            for binding in result["bindings"]:
                version = binding["version"]
                bound.add(version)
                if version not in versions or binding["resolved"] != version:
                    findings.append(Drift(
                        "different_string", family, "contract.ts", "VIEW_BINDINGS",
                        ", ".join(sorted(versions)), str(binding),
                    ))
            if bound != versions:
                findings.append(Drift(
                    "different_string", family, "contract.ts", "VIEW_BINDINGS",
                    ", ".join(sorted(versions)), ", ".join(sorted(bound)) or "<missing>",
                ))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError) as exc:
            findings.append(Drift(
                "different_string", family, "contract.ts", "contract-runtime",
                "loadable instrument view contract", str(exc),
            ))
    return tuple(findings)


def check_landed() -> tuple[Drift, ...]:
    """Check module citations and agreement between Python and view contracts."""

    site_views, _site_doc, swissknife_views, _swissknife_doc = _view_paths()
    constants = landed_constants()
    findings = list(find_drift(constants, landed_documents()))
    findings.extend(check_view_contracts(constants))
    for family, directory in (("view-site", site_views), ("view-swissknife", swissknife_views)):
        missing = _missing_view_tree(constants, family, directory)
        if missing is not None:
            findings.append(missing)
    return tuple(sorted(findings, key=lambda item: (
        item.kind, item.document, item.module, item.name, item.value, item.cited,
    )))


def format_finding(item: Drift) -> str:
    document = _DOC_LABELS.get(item.document, item.document)
    if item.kind == "omitted":
        return f"omitted\t{document}\t{item.module}\t{item.name}\t{item.value}"
    cited = item.cited or item.value
    return (
        f"different_string\t{document}\t{item.module}\t{item.name}\t"
        f"{item.value}\tcited={cited}"
    )


def main() -> int:
    findings = check_landed()
    if not findings:
        print("ok")
        return 0
    for item in findings:
        print(format_finding(item))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

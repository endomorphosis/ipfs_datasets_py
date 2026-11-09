"""Regenerate schema_caselaw_v6.md table section from caselaw_schema.SCHEMAS.

Reads templates from (in order): package ``docs/`` next to this file, then
``$CASE_LAW_ROOT`` or ``$IPFS_DATASETS_LEGAL_WORKSPACE/case_law``. Writes
``schema_caselaw_v6.md`` into package ``docs/`` when present, otherwise under the
workspace case_law root. Requires ``schema_caselaw_v0.md`` as a path-contract check.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG_DOCS = _HERE / "docs"
_WS_CASE = Path(os.environ.get("CASE_LAW_ROOT", str(_LEGAL_WS / "case_law")))

def _find(*names: str) -> Path:
    for base in (_PKG_DOCS, _HERE, _WS_CASE, _WS_CASE / "pipeline"):
        for name in names:
            p = base / name
            if p.is_file():
                return p
    raise FileNotFoundError(f"missing template among {names} (looked in {_PKG_DOCS}, {_HERE}, {_WS_CASE})")

sys.path.insert(0, str(_HERE))
import caselaw_schema as cs

def tables() -> str:
    out = []
    for kind, title in (
        ("decision", "decision (case-level metadata, no text)"),
        ("opinion", "opinion (text units; FK first among type-specific columns)"),
        ("docket", "docket"),
        ("citation_edge", "citation_edge"),
    ):
        out += [f"### {title}", "| # | column | type | null? |", "|---|---|---|---|"]
        for i, f in enumerate(cs.SCHEMAS[kind], 1):
            out.append(f"| {i} | `{f.name}` | `{str(f.type)}` | {'yes' if f.nullable else '**no**'} |")
        out.append("")
    return "\n".join(out)

def main() -> Path:
    v0 = _find("schema_caselaw_v0.md")
    head = _find("doc_v6_head.md").read_text(encoding="utf-8")
    tail = _find("doc_v6_tail.md").read_text(encoding="utf-8")
    body = head + "\n## Tables\n" + tables() + "\n" + tail
    if _PKG_DOCS.is_dir():
        out = _PKG_DOCS / "schema_caselaw_v6.md"
    else:
        out = _WS_CASE / "schema_caselaw_v6.md"
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print("wrote", out, "bytes", out.stat().st_size, "from", v0)
    return out

if __name__ == "__main__":
    main()

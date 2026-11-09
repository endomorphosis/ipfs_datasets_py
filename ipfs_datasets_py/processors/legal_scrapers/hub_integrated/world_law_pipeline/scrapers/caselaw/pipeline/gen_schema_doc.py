# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import re
import caselaw_schema as cs
old = open((str(_LEGAL_WS) + "/case_law/schema_caselaw_v0.md")).read().splitlines()
def tables():
    out = []
    for kind, title in (("decision", "decision (case-level metadata, no text)"), ("opinion", "opinion (text units; FK first among type-specific columns)"),
                        ("docket", "docket"), ("citation_edge", "citation_edge")):
        out += [f"### {title}", "| # | column | type | null? |", "|---|---|---|---|"]
        for i, f in enumerate(cs.SCHEMAS[kind], 1):
            out.append(f"| {i} | `{f.name}` | `{str(f.type)}` | {'yes' if f.nullable else '**no**'} |")
        out.append("")
    return "\n".join(out)
head = open((str(_LEGAL_WS) + "/case_law/pipeline/doc_v6_head.md")).read()
tail = open((str(_LEGAL_WS) + "/case_law/pipeline/doc_v6_tail.md")).read()
open((str(_LEGAL_WS) + "/case_law/schema_caselaw_v6.md"), "w").write(head + "\n## Tables\n" + tables() + "\n" + tail)
